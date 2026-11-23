"""사진 정리 창의 글자 읽기 화면(결정 D-513, 설계서 2-2에서 2-9, 시험 계획 T-C)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 진짜 키·마우스 이벤트로 눌러 본다.
**PySide6 가 없으면 통째로 건너뛴다**(저장소 CI 에는 PySide6 가 없다). 읽는 쪽은 가짜 공급자(`FakeOcrProvider` — 기다렸다 주는 것·즉시 주는 것)이고, 진짜 어댑터 흐름은 가짜 작업자(`tests/ocr_fake_worker.py`)로 따로 시험한다(`test_ui_qt_photo_ocr_flow.py`).
사진 이름·글은 모두 지어낸 것이고 사용자의 사진·클립보드·데이터 폴더는 건드리지 않는다.

지키는 것:
  1) 꺼져 있으면 지금과 같다 — 컨트롤러가 없거나(도구 없음·관문 꺼짐) 있어도 읽을 수 없으면 사진 정리 창에서 보이는 글·접근 이름·Tab 정거장이 글자 읽기가 없던 때와 한 글자도 다르지 않다. 진짜 어댑터를 물려도 작업자는 한 번도 안 뜬다.
  2) 칸의 모습 — 단추(글자 읽기·다시 읽기·더 크게·취소)·상태 줄(준비·읽는 중·몇 초째·오래 걸림·실패·멈춤)·찾지 못함·읽은 글 목록·확인 줄 둘(다시 읽기·모두 맞아요). 상태는 색만이 아니라 늘 글이다.
  3) 읽은 글 목록 키보드 — Tab 정거장 하나·위아래·Home·End·Space·Enter·F2·Esc·Delete(꾹 눌러도 한 번)·마우스 체크 상자·고치기·빼기·합치기·되돌리기. 접근 이름·설명은 지금 고른 줄을 말하고 상태가 바뀌면 같이 바뀐다.
  4) 포커스 — 단추가 사라지면 남은 부품으로 옮겨 가고 확인 줄이 뜨면 안전한 쪽(그만두기)에 선다. Esc 는 고치기·확인 줄·읽는 중 취소가 먼저이고 할 일이 없을 때만 창을 닫는다.
  5) 읽는 중 — 사진 확정은 건너뛰고 알리며, 창을 닫거나 사진을 지우면 요청이 취소되고 늦게 온 결과는 버려진다. 새로 읽거나 줄을 고쳐 확정이 풀리면 줄에 안내가 뜬다.
  6) 크기 — 일곱 창 크기에서 가로 스크롤·글자 잘림·삐져나옴이 없고 줄이 많으면 목록 안에서 스크롤하며(높이 상한), 60줄에서도 느려지지 않는다.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import test_ui_qt_photo as tq  # noqa: E402     (시험 도구만 이어 쓴다 — 그 모듈의 시험 클래스는 가져오지 않는다)

from chanceblog_desktop.ui.core import photo_ocr_view as pov  # noqa: E402
from chanceblog_desktop.ui.core import photo_view as pv  # noqa: E402
from chanceblog_desktop.ui.core import services, tokens  # noqa: E402
from chanceblog_desktop.ui.core.clock import FixedClock  # noqa: E402

HAVE = tq.HAVE
if HAVE:
    import ui_offscreen
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QAccessible, QKeyEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QLineEdit, QWidget
    from chanceblog_desktop.ui import photo_adapter
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import photo_ocr_parts as parts
    from chanceblog_desktop.ui.qt import shell as shell_module
    from chanceblog_desktop.ui.qt import theme

T = tq.T
qd = tq.qd
fake_path = tq.fake_path
SIZES = tq.SIZES

LINES = ("한우 불고기 전골 28,000원", "된장찌개 9,000원", "공기밥 1,000원", "식사 후 커피 무료")
MANY = tuple(f"차림표 {number} 번 메뉴 {number * 1000:,}원" for number in range(1, 61))
HIDDEN = ("가" * 201, "900101-1234567", "가" + chr(0x3164) + "나")                    # 입구 검사가 가리는 줄 셋(너무 긴 줄·주민등록번호 모양·보이지 않는 글자) — '읽은 글 중 3줄은 보여 드리지 않았어요(…)' 안내가 일곱 크기에서 잘리지 않아야 한다(검증 SQ 권고 3, 결정 D-593)


class BlockingProvider(pov.FakeOcrProvider):
    """`read` 가 풀어 줄 때까지 기다리는 가짜 공급자 — 읽는 중인 모습을 붙잡아 볼 때 쓴다(`release()` 로 모두 풀어 준다)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.gate, self.started = threading.Event(), threading.Event()

    def read(self, job):
        self.started.set()
        self.gate.wait(10)
        return super().read(job)

    def release(self):
        self.gate.set()


class Clock:
    """시험이 손으로 움직이는 단조 시계(초) — 읽는 중의 초 글과 시간 규칙을 시계 없이 본다."""

    def __init__(self, start=1000.0):
        self.value = start

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class OcrBase(tq.PhotoBase):
    """글자 읽기가 붙은 사진 정리 창 도구 — 초안 화면까지 가서 사진을 넣고 창을 연다."""

    def setUp(self):
        super().setUp()
        self.clock = Clock()

    def make_ocr(self, provider=None, size=(1600, 960), reader=None, real_files=False, **options):
        """`real_files` 면 진짜 사진 파일 공급자와 진짜 사진 읽기(`ocr_input`)를 쓰고(미리보기도 진짜), 아니면 가짜 공급자와 가짜 읽기를 쓴다."""
        provider = provider if provider is not None else pov.FakeOcrProvider(default=pov.OcrOutcome(LINES))
        self.provider = provider
        candidates = qd.candidates_with(tq.GENERIC, tq.SOFTWARE, tq.APPLIANCE, tq.STOPPED, tq.OTHER_CHANNEL)
        reading = dict(monotonic=self.clock, **options)
        if not real_files:
            reading["reader"] = reader or (lambda path, size_name: (1, 1, b"abc"))
        window = shell_module.AppShell(services.FakeHomeProvider(), candidates=candidates, autoload=False, clock=FixedClock(qd.NOW), clipboard=self.clipboard, url_opener=lambda url: self.opened.append(url) or True,
                                       files_picker=self.pick_files, file_picker=self.pick_one, photos=photo_adapter.ServicePhotoProvider() if real_files else pv.FakePhotoProvider(),
                                       photo_preview_maker=None if real_files else self.make_preview, ocr=provider, ocr_options=reading)
        window.resize(*size)
        window.show()
        self.addCleanup(lambda: (window.state.drafts.leave(), window.close()))
        self.settle()
        self.activate(window)
        if not window.isActiveWindow():                                                   # 바쁜 PC 에서 활성이 늦으면 직접 맞춘다(키 시험은 활성 창이 있어야 한다)
            QApplication.setActiveWindow(window)
            self.settle(3)
        window.go("topics")
        self.assertTrue(ui_offscreen.wait_until(self.app, lambda: window.state.candidates.state != "loading" and not window.state.candidates.loading, 10))
        self.settle()
        return window

    def ocr_sheet(self, photos=2, provider=None, size=(1600, 960), paths=None, **options):
        """초안이 보이는 창에서 사진 정리 창을 열고 사진을 넣는다(`paths` 를 주면 그 위치들, 아니면 지어낸 위치 `photos` 장) → (창, 사진 정리 창 안쪽)."""
        window = self.make_ocr(provider=provider, size=size, real_files=paths is not None, **options)
        self.open_candidate(window, "분야를 알 수 없는")
        self.make_button(window).click()
        self.assertTrue(self.wait_draft(window))
        window, form = self.sheet(window)
        self.add_photos(form, *(paths if paths is not None else [fake_path(number) for number in range(1, photos + 1)]))
        return window, form

    def block(self, form, photo_id="p001"):
        return form.rows[photo_id].ocr_block

    def wait_for(self, condition, seconds=10):
        self.assertTrue(ui_offscreen.wait_until(self.app, condition, seconds), "기다리던 일이 일어나지 않았다")

    def wait_state(self, form, state, photo_id="p001", seconds=30):
        self.wait_for(lambda: self.block(form, photo_id).vm is not None and self.block(form, photo_id).vm["state"] == state, seconds)      # 진짜 작업자 프로세스가 뜨는 흐름은 아주 바쁜 PC 에서 10초를 넘길 수 있다 — 기다림의 위쪽 한도만 늘렸고 단정은 그대로다(독립 검증 S SP-12)
        self.settle(3)

    def read_done(self, form, photo_id="p001"):
        self.block(form, photo_id).read_button.click()
        self.wait_state(form, "done", photo_id)
        return self.block(form, photo_id)

    def describe(self, widget):
        """포커스가 어긋났을 때 읽기 쉽게 — 위젯 종류·접근 이름·focus_key·보임·켜짐."""
        if widget is None:
            return "없음"
        return f"{type(widget).__name__}({widget.accessibleName()!r}, key={widget.property('focus_key')!r}, 보임={widget.isVisible()}, 켜짐={widget.isEnabled()})"

    def assertFocus(self, expected, message=""):
        """지금 키보드 포커스가 `expected` 인지 — 아니면 어디에 있는지·창이 활성인지를 함께 보인다."""
        actual = QApplication.focusWidget()
        self.assertIs(actual, expected, f"{message} — 있어야 할 곳 {self.describe(expected)}, 실제 포커스 {self.describe(actual)}, 활성 창 있음 {QApplication.activeWindow() is not None}")

    def key(self, widget, key, modifier=None):
        modifier = Qt.NoModifier if modifier is None else modifier     # 기본값을 정의 시점에 `Qt.NoModifier` 로 두면 PySide6 가 없는 CI 에서 파일을 불러오다 NameError 가 난다
        self.assertIsNotNone(widget, "키를 받을 위젯이 없다(포커스가 어디에도 없다) — QTest 에 None 을 주면 프로세스가 통째로 죽는다")
        QTest.keyClick(widget, key, modifier)
        self.settle(2)

    def row_texts(self, block):
        return [row.text.plain_text() for row in block.lines.rows]

    def watch_accessibility(self):
        """읽는 프로그램(접근성)에 보내는 알림을 모은다 → 목록 `[(종류, 대상)]`. PySide6 에는 알림을 가로채는 길(`installUpdateHandler`)이 없어서 부품 파일이 `QAccessible` 을 부르는 자리에 알림만 모으는 대역을 끼운다(시험이 끝나면 되돌린다).
        진짜 읽는 프로그램이 이 알림을 읽는지는 운영자 PC 에서 본다."""
        events = []

        class Spy:
            NameChanged, Alert = QAccessible.NameChanged, QAccessible.Alert

            @staticmethod
            def updateAccessibility(event):
                events.append((event.type(), event.object()))

        patcher = mock.patch.object(parts, "QAccessible", Spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return events

    def fingerprint(self, form):
        """사진 정리 창에서 보이는 모든 것 — 위젯 종류·접근 이름·글(입력 칸은 안내 글)을 위에서 아래 순서로. 글자 읽기가 없던 때와 견주는 데 쓴다."""
        found = []
        for widget in form.findChildren(QWidget):
            if not widget.isVisibleTo(form):
                continue
            label = widget.plain_text() if isinstance(widget, UI.Label) else widget.text() if isinstance(widget, (QLabel, QAbstractButton)) else widget.placeholderText() if isinstance(widget, QLineEdit) else ""
            found.append((type(widget).__name__, widget.accessibleName(), label, int(widget.focusPolicy().value)))
        stops = [stop.accessibleName() for card in form.ordered_cards() for stop in card.stops() if stop.isVisibleTo(form) and stop.isEnabled() and bool(stop.focusPolicy() & Qt.TabFocus)]
        return found, stops


# ---- 1) 꺼져 있으면 지금과 같다 ------------------------------------------------------------------------------------------------------
class OffTest(OcrBase):
    def test_without_a_reader_nothing_of_it_exists_in_the_window_or_the_sheet(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2))
        self.assertEqual((window.ocr_runner, window.state.ocr, window.state.drafts.photos.ocr, form.ocr_runner, form.ocr_intro, form.has_ocr()), (None, None, None, None, None, False))
        self.assertEqual([card.ocr_block for card in form.rows.values()], [None, None])
        for widget in form.findChildren(QWidget):
            self.assertNotIn("글자 읽기", widget.accessibleName())
            self.assertNotIn("읽은 글", widget.accessibleName())
        shown = " ".join(self.shown_texts(form))
        self.assertNotIn("글자 읽기", shown)
        self.assertNotIn("읽은 글", shown)

    def test_a_reader_that_cannot_read_leaves_the_visible_sheet_exactly_as_it_was(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2))
        plain = self.fingerprint(form)
        window.close_dialog()
        off = pov.FakeOcrProvider(is_available=False)
        window2, form2 = self.ocr_sheet(photos=2, provider=off)
        self.assertIsNotNone(window2.ocr_runner, "컨트롤러는 붙어 있다")
        self.assertEqual(self.fingerprint(form2), plain, "읽을 수 없으면 보이는 글·접근 이름·Tab 정거장이 한 글자도 다르지 않다")
        self.assertFalse(form2.ocr_intro.isVisibleTo(form2))
        self.assertTrue(all(card.ocr_block is not None and not card.ocr_block.isVisibleTo(form2) for card in form2.rows.values()))
        self.assertEqual(off.calls, [], "읽기를 한 번도 시키지 않았다")

    def test_a_real_adapter_with_the_gate_off_adds_nothing_and_never_starts_a_worker(self):
        from chanceblog_desktop.ui.ocr_provider import WorkerAdapter
        import outgoing_support as og
        window, form = self.sheet()
        self.add_photos(form, fake_path(1))
        plain = self.fingerprint(form)
        window.close_dialog()
        adapter = WorkerAdapter([sys.executable, "-c", "raise SystemExit(7)"], verify=None)
        with og.Tripwire() as wire:
            window2, form2 = self.ocr_sheet(photos=1, provider=adapter)
            self.assertFalse(adapter.available(), "소스 상수가 꺼져 있다")
            self.assertEqual(self.fingerprint(form2), plain, "작업자를 물려도 관문이 꺼져 있으면 보이는 것이 한 글자도 다르지 않다")
            self.assertFalse(form2.rows["p001"].ocr_block.isVisibleTo(form2))
            self.settle(4)
        self.assertEqual((wire.calls, adapter.launches, adapter.process), ([], 0, None))


# ---- 2) 칸의 모습 ------------------------------------------------------------------------------------------------------------------
class BlockTest(OcrBase):
    def test_before_reading_there_is_only_the_name_the_button_and_the_hint(self):
        window, form = self.ocr_sheet(photos=2)
        self.assertEqual(form.ocr_intro.plain_text(), T["pho_ocr_intro"])
        self.assertTrue(form.ocr_intro.isVisibleTo(form))
        block = self.block(form)
        self.assertTrue(all(widget.isVisibleTo(form) for widget in (block.title, block.read_button, block.hint)))
        self.assertEqual((block.title.plain_text(), block.read_button.text(), block.read_button.accessibleName(), block.hint.plain_text()), ("사진 속 글자", "글자 읽기", "사진 1 글자 읽기", "이 PC 안에서만 읽어요"))
        self.assertEqual(self.block(form, "p002").read_button.accessibleName(), "사진 2 글자 읽기")
        for widget in (block.bigger_button, block.cancel_button, block.status, block.result, block.reread, block.none):
            self.assertFalse(widget.isVisibleTo(form))
        self.assertGreaterEqual(block.read_button.height(), tokens.SIZE["hit"] - 8)

    def test_the_parts_of_every_button_row_belong_to_their_row_from_the_start_so_showing_one_never_opens_a_window_of_its_own(self):
        """독립 확인 중 잡은 결함의 못 — 부모 없는 위젯에 `setVisible(True)` 를 하면 별도의 창으로 잠깐 떠서 앱 창의 활성(포커스)을 빼앗고 윈도에서는 작은 창이 번쩍인다. 단추 줄의 부품은 처음부터 그 줄의 자식이다."""
        window, form = self.ocr_sheet(photos=1)
        block = self.block(form)
        for row in (block.head, block.tools, block.reread.buttons, block.all_ask.buttons):
            self.assertFalse(row.isWindow(), "단추 줄 자체도 부모가 있다")
            self.assertTrue(block.isAncestorOf(row))
            for widget in row.widgets:
                self.assertIs(widget.parentWidget(), row, widget.accessibleName() or type(widget).__name__)
                self.assertFalse(widget.isWindow(), widget.accessibleName() or type(widget).__name__)

    def test_going_through_every_state_never_opens_a_stray_window_or_takes_the_window_activation(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=2, provider=provider)

        def visible_windows():
            return sorted(type(widget).__name__ for widget in QApplication.topLevelWidgets() if widget.isVisible())

        before = visible_windows()
        self.assertTrue(window.isActiveWindow(), "시험 창은 활성이다")
        block = self.block(form)
        block.read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        self.assertEqual((visible_windows(), window.isActiveWindow()), (before, True), "읽는 중")
        provider.release()
        self.wait_state(form, "done")
        self.assertEqual((visible_windows(), window.isActiveWindow()), (before, True), "읽은 글")
        block.all_button.click()
        self.settle(3)
        block.all_ask.no.click()
        block.read_button.click()
        self.settle(3)
        self.assertEqual((visible_windows(), window.isActiveWindow()), (before, True), "확인 줄")
        block.reread.no.click()
        self.settle(3)
        self.assertEqual((visible_windows(), window.isActiveWindow()), (before, True), "확인 줄을 닫은 뒤")

    def test_pressing_read_shows_cancel_instead_moves_the_focus_there_and_counts_the_seconds(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=1, provider=provider)
        block = self.block(form)
        block.read_button.setFocus(Qt.TabFocusReason)
        block.read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        self.assertEqual((block.read_button.isVisibleTo(form), block.cancel_button.isVisibleTo(form), block.cancel_button.text()), (False, True, "취소"))
        self.assertFocus(block.cancel_button, "누른 단추가 사라지면 취소 단추로 포커스가 간다")
        self.assertEqual((block.status.plain_text(), block.status.isVisibleTo(form)), ("사진 속 글자를 읽고 있어요 · 0초", True))
        self.clock.advance(7)
        form.ocr_tick()
        self.assertEqual(block.status.plain_text(), "사진 속 글자를 읽고 있어요 · 7초")
        self.assertEqual(block.status.accessibleName(), "사진 1 글자 읽기 상태: 사진 속 글자를 읽고 있어요", "접근 이름에는 초가 없다")
        self.clock.advance(10)
        form.ocr_tick()
        self.assertEqual(block.status.plain_text().split("\n")[1], T["pho_ocr_slow"])
        self.assertEqual(block.status.accessibleName(), "사진 1 글자 읽기 상태: 사진 속 글자를 읽고 있어요. " + T["pho_ocr_slow"])
        provider.release()
        self.wait_state(form, "done")
        self.assertEqual((block.cancel_button.isVisibleTo(form), block.read_button.isVisibleTo(form), block.read_button.text()), (False, True, "다시 읽기"))
        self.assertFocus(block.lines, "끝나면 읽은 글 목록으로 포커스가 간다")

    def test_the_result_shows_the_title_the_guide_the_digits_note_and_every_line_not_confirmed_yet(self):
        window, form = self.ocr_sheet(photos=1)
        block = self.read_done(form)
        self.assertEqual(self.row_texts(block), list(LINES))
        self.assertEqual(block.lines_title.plain_text(), "읽은 글 4줄 · 아직 확인 전이에요")
        self.assertIn("틀릴 수 있어요", block.guide.plain_text())
        self.assertTrue(block.digits.isVisibleTo(form))
        self.assertEqual([(row.state.plain_text(), row.property("ocrline")) for row in block.lines.rows], [("확인 전", "pending")] * 4, "확인 전은 글과 점선 테두리로 알린다")
        self.assertEqual((form.rows["p001"].confirm_box.isChecked(), form.board.photo("p001").confirmed_by_user), (False, False))
        self.assertEqual([item.confirmed for item in form.board.photo("p001").visible_text], [False] * 4, "읽은 줄은 모두 확인 전이다")

    def test_a_line_with_html_looking_characters_is_shown_as_plain_text_and_the_names_keep_the_raw_text(self):
        window, form = self.ocr_sheet(photos=1, provider=pov.FakeOcrProvider(default=pov.OcrOutcome(("A&B 3 < 5 맛있는 집", "<b>굵게</b> 아님"))))
        block = self.read_done(form)
        shown = [row.text.plain_text() for row in block.lines.rows]
        self.assertEqual(shown[0], "A&B 3 < 5 맛있는 집")
        row = block.lines.rows[0]
        self.assertIn("&amp;", row.text.text(), "화면의 글은 HTML 로 읽히지 않게 이스케이프한 것이다")
        self.assertIn("&lt;", row.text.text())
        self.assertNotIn("<b>", "".join(r.text.text() for r in block.lines.rows), "태그 모양 줄은 입구 검사가 거르고 남은 글도 태그로 읽히지 않는다")
        self.assertEqual(row.text.accessibleDescription(), "A&B 3 < 5 맛있는 집")

    def test_a_confirmed_line_says_confirmed_in_words_and_has_a_solid_border(self):
        window, form = self.ocr_sheet(photos=1)
        block = self.read_done(form)
        block.lines.rows[1].check.click()
        self.settle(3)
        row = block.lines.rows[1]
        self.assertEqual((row.state.plain_text(), row.property("ocrline"), row.check.isChecked()), ("확인함", "done", True))
        self.assertEqual(block.lines_title.plain_text(), "읽은 글 4줄 중 확인 1줄")
        self.assertEqual((block.lines.rows[0].property("ocrline"), block.lines.rows[0].check.isChecked()), ("pending", False))
        self.assertTrue(form.board.photo("p001").visible_text[1].confirmed)
        self.assertFalse(form.board.photo("p001").confirmed_by_user, "줄 확인과 사진 확정은 따로다")

    def test_nothing_found_says_so_with_the_way_out_and_no_list(self):
        window, form = self.ocr_sheet(photos=1, provider=pov.FakeOcrProvider(default=pov.OcrOutcome(())))
        block = self.read_done(form)
        self.assertEqual((block.none.isVisibleTo(form), block.result.isVisibleTo(form), block.none.plain_text()), (True, False, T["pho_ocr_none"]))
        self.assertTrue(block.bigger_button.isVisibleTo(form) and block.read_button.isVisibleTo(form), "다시 읽기와 크게 읽기가 있다")
        self.assertEqual(block.read_button.text(), "글자 읽기")

    def test_a_failure_shows_a_red_fixed_sentence_with_a_button_to_try_again(self):
        window, form = self.ocr_sheet(photos=1, provider=pov.FakeOcrProvider(default=pov.OcrOutcome(error="died")))
        block = self.block(form)
        block.read_button.setFocus(Qt.TabFocusReason)
        block.read_button.click()
        self.wait_state(form, "failed")
        self.assertEqual(block.status.plain_text(), T["pho_ocr_err_failed"])
        self.assertEqual(block.status.property("tone"), "red")
        self.assertIn(T["pho_ocr_err_failed"], block.status.accessibleName())
        self.assertTrue(block.read_button.isVisibleTo(form) and not block.cancel_button.isVisibleTo(form))
        self.assertFocus(block.read_button, "끝나면 다시 시도할 단추로 포커스가 간다")

    def test_a_failure_raises_an_alert_and_the_seconds_ticking_never_does(self):
        provider = BlockingProvider(default=pov.OcrOutcome(error="died"))
        window, form = self.ocr_sheet(photos=1, provider=provider)
        block = self.block(form)
        events = self.watch_accessibility()
        block.read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        events.clear()
        for _ in range(3):
            self.clock.advance(2)
            form.ocr_tick()
        self.assertEqual([kind for kind, target in events if target is block.status], [], "매초 바뀌는 초 글은 읽는 프로그램에 알리지 않는다")
        provider.release()
        self.wait_state(form, "failed")
        kinds = [kind for kind, target in events if target is block.status]
        self.assertIn(QAccessible.Alert, kinds, "실패는 놓치면 안 되는 알림이다")
        self.assertIn(QAccessible.NameChanged, kinds)

    def test_the_third_failure_in_a_row_turns_the_tool_off_for_this_run_and_says_why(self):
        window, form = self.ocr_sheet(photos=1, provider=pov.FakeOcrProvider(default=pov.OcrOutcome(error="died")))
        block = self.block(form)
        for number in range(3):
            self.assertTrue(block.read_button.isVisibleTo(form), number)
            block.read_button.click()
            self.wait_for(lambda: block.vm["state"] == "failed" and not window.state.ocr.active)
        self.assertEqual(window.state.ocr.disabled_code, "OCR_UNAVAILABLE")
        self.assertEqual(block.status.plain_text().split("\n"), [T["pho_ocr_err_failed"], T["pho_ocr_off_note"]])
        self.assertFalse(block.read_button.isVisibleTo(form), "끈 뒤에는 읽기 단추가 없다")
        self.assertFalse(form.ocr_intro.isVisibleTo(form))

    def test_cancel_stops_the_read_says_so_and_a_late_answer_is_thrown_away(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=1, provider=provider)
        block = self.block(form)
        block.read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        block.cancel_button.click()
        self.settle(3)
        self.assertEqual((block.status.plain_text(), block.read_button.isVisibleTo(form), block.cancel_button.isVisibleTo(form)), ("글자 읽기를 멈췄어요", True, False))
        self.assertEqual(provider.cancelled, [1], "읽는 쪽에 취소를 알렸다")
        provider.release()
        self.wait_for(lambda: window.state.ocr.active is None)
        self.settle(3)
        self.assertEqual(self.row_texts(block), [], "취소한 뒤에 온 결과는 버린다")
        self.assertEqual(form.board.photo("p001").visible_text, ())

    def test_two_photos_are_read_one_after_the_other_and_the_second_waits_with_how_many_are_ahead(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=2, provider=provider)
        first, second = self.block(form, "p001"), self.block(form, "p002")
        first.read_button.click()
        self.assertTrue(provider.started.wait(20))
        second.read_button.click()
        self.settle(3)
        self.assertEqual((first.status.plain_text(), second.status.plain_text()), ("사진 속 글자를 읽고 있어요 · 0초", "차례를 기다리는 중이에요(앞에 1장)"))
        self.assertTrue(second.cancel_button.isVisibleTo(form), "기다리는 중에도 취소할 수 있다")
        provider.release()
        self.wait_state(form, "done", "p001")
        self.wait_state(form, "done", "p002")
        self.assertEqual([call[1] for call in provider.calls], ["p001", "p002"], "먼저 누른 순서로 한 장씩")

    def test_the_next_photo_starts_by_itself_when_one_ends_even_if_nothing_redraws_the_sheet(self):
        """한 장이 끝나면 진행자가 곧바로 다음 장을 시작한다 — 다시 그리기(`PhotoSheet.refresh` 도 진행자를 한 번 흔든다)가 대신 시작해 주지 않아도."""
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=2, provider=provider)
        window.ocr_runner.changed.disconnect(form.refresh)
        self.block(form, "p001").read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.block(form, "p002").read_button.click()
        self.settle(3)
        provider.release()
        self.wait_for(lambda: [call[1] for call in provider.calls] == ["p001", "p002"])
        self.wait_for(lambda: window.state.ocr.active is None)

    def test_the_bigger_read_asks_before_replacing_and_then_reads_at_the_bigger_size(self):
        window, form = self.ocr_sheet(photos=1)
        block = self.read_done(form)
        block.bigger_button.click()
        self.settle(3)
        self.assertEqual((block.reread.isVisibleTo(form), block.reread.message.plain_text()), (True, T["pho_ocr_reread_ask"]))
        self.assertFocus(block.reread.no, "확인 줄이 뜨면 처음 포커스는 그만두기")
        self.assertEqual([call[2] for call in self.provider.calls], ["960"], "묻는 동안은 읽지 않는다")
        block.reread.yes.click()
        self.wait_for(lambda: len(self.provider.calls) == 2 and self.block(form).vm["state"] == "done")
        self.assertEqual([call[2] for call in self.provider.calls], ["960", "1600"])
        self.assertFalse(block.reread.isVisibleTo(form))

    def test_saying_no_to_reading_again_changes_nothing_and_closes_the_question(self):
        window, form = self.ocr_sheet(photos=1)
        block = self.read_done(form)
        block.lines.rows[0].check.click()
        self.settle(2)
        block.read_button.click()
        self.settle(3)
        self.assertTrue(block.reread.isVisibleTo(form))
        block.reread.no.click()
        self.settle(3)
        self.assertFalse(block.reread.isVisibleTo(form))
        self.assertEqual(([(item.text, item.confirmed) for item in form.board.photo("p001").visible_text][:2]), [(LINES[0], True), (LINES[1], False)])
        self.assertEqual(len(self.provider.calls), 1)

    def test_all_right_asks_first_with_the_safe_button_focused_then_confirms_only_the_lines(self):
        window, form = self.ocr_sheet(photos=1)
        block = self.read_done(form)
        block.all_button.click()
        self.settle(3)
        self.assertTrue(block.all_ask.isVisibleTo(form))
        self.assertEqual(block.all_ask.message.plain_text(), T["pho_ocr_all_ask"].format(n=4))
        self.assertFocus(block.all_ask.no)
        self.assertFalse(block.all_button.isEnabled(), "확인 줄이 떠 있는 동안은 또 누르지 않는다")
        self.assertEqual([item.confirmed for item in form.board.photo("p001").visible_text], [False] * 4, "묻기만 했다")
        block.all_ask.yes.click()
        self.settle(3)
        self.assertEqual(([item.confirmed for item in form.board.photo("p001").visible_text], block.all_ask.isVisibleTo(form)), ([True] * 4, False))
        self.assertEqual((block.lines_title.plain_text(), form.board.photo("p001").confirmed_by_user), ("읽은 글 4줄 중 확인 4줄", False), "줄은 모두 확인해도 사진은 확정되지 않는다")
        self.assertFocus(block.lines, "확인 줄이 사라지면 목록으로 돌아온다")

    def test_a_question_asked_before_reading_again_never_comes_back_for_the_new_lines_and_they_are_asked_anew(self):
        """독립 검증 S SP-1 — 모두 맞아요 확인 줄을 띄운 채 다시 읽으면, 새 줄이 와도 확인 줄이 되살아나지 않는다(보지 못한 줄을 한꺼번에 맞아요로 만드는 길이 없다). 새 줄에는 새로 묻는다."""
        provider = pov.FakeOcrProvider(outcomes={"p001": [pov.OcrOutcome(LINES), pov.OcrOutcome(MANY[:6])]})
        window, form = self.ocr_sheet(photos=1, provider=provider)
        block = self.read_done(form)
        block.all_button.click()
        self.settle(3)
        self.assertTrue(block.all_ask.isVisibleTo(form))
        block.read_button.click()
        self.settle(3)
        self.assertTrue(block.reread.isVisibleTo(form))
        block.reread.yes.click()
        self.wait_for(lambda: len(provider.calls) == 2 and self.block(form).vm["state"] == "done")
        self.settle(4)
        self.assertEqual(block.lines_title.plain_text(), T["pho_ocr_title"].format(n=6))
        self.assertFalse(block.all_ask.isVisibleTo(form), "낡은 확인 줄은 되살아나지 않는다")
        self.assertEqual([item.confirmed for item in form.board.photo("p001").visible_text], [False] * 6, "새 줄은 하나도 확인되지 않았다")
        self.assertTrue(block.all_button.isEnabled(), "새 줄에는 새로 묻는다")
        block.all_button.click()
        self.settle(3)
        self.assertEqual(block.all_ask.message.plain_text(), T["pho_ocr_all_ask"].format(n=6))
        self.assertEqual([item.confirmed for item in form.board.photo("p001").visible_text], [False] * 6, "묻기만 했다")

    def test_confirming_the_photo_while_it_reads_is_skipped_with_a_notice(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=2, provider=provider)
        self.block(form, "p001").read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        form.rows["p001"].confirm_box.click()
        self.settle(3)
        self.assertEqual((form.board.photo("p001").confirmed_by_user, form.rows["p001"].confirm_box.isChecked()), (False, False))
        self.assertEqual((form.notice.plain_text(), form.notice.isVisibleTo(form)), (T["pho_ocr_confirm_busy"], True))
        form.all_button.click()
        self.settle(3)
        form.confirm_buttons[0].click()                                                         # 모두 확인 — 읽는 중인 사진은 건너뛴다
        self.settle(3)
        self.assertEqual([photo.confirmed_by_user for photo in form.board.manifest.photos], [False, True])
        provider.release()
        self.wait_state(form, "done", "p001")

    def test_a_line_action_on_a_confirmed_photo_loosens_it_and_leaves_the_note_on_that_row(self):
        window, form = self.ocr_sheet(photos=1)
        block = self.read_done(form)
        form.rows["p001"].confirm_box.click()
        self.settle(3)
        self.assertTrue(form.board.photo("p001").confirmed_by_user)
        block.lines.rows[0].check.click()
        self.settle(3)
        card = form.rows["p001"]
        self.assertEqual((form.board.photo("p001").confirmed_by_user, card.confirm_box.isChecked()), (False, False))
        self.assertEqual((card.changed_note.plain_text(), card.changed_note.isVisibleTo(form)), (T["pho_unconfirmed_note"], True))

    def test_a_new_read_that_replaces_lines_of_a_confirmed_photo_leaves_the_note(self):
        window, form = self.ocr_sheet(photos=1)
        form.rows["p001"].confirm_box.click()
        self.settle(3)
        self.read_done(form)
        card = form.rows["p001"]
        self.assertEqual((form.board.photo("p001").confirmed_by_user, card.changed_note.plain_text()), (False, T["pho_unconfirmed_note"]))

    def test_the_file_problem_of_a_photo_hides_the_read_button_for_that_photo_only(self):
        window, form = self.ocr_sheet(photos=2)
        form.board.states["p002"] = pv.FileState("p002", "missing")
        form.refresh()
        self.assertTrue(self.block(form, "p001").read_button.isVisibleTo(form))
        self.assertFalse(self.block(form, "p002").isVisibleTo(form))


# ---- 3) 읽은 글 목록의 키보드 -----------------------------------------------------------------------------------------------------------
class ListKeysTest(OcrBase):
    def done(self, photos=1, **kwargs):
        window, form = self.ocr_sheet(photos=photos, **kwargs)
        block = self.read_done(form)
        block.lines.setFocus(Qt.TabFocusReason)
        self.settle(2)
        return window, form, block

    def test_the_list_is_one_tab_stop_and_the_buttons_inside_the_rows_are_not(self):
        window, form, block = self.done()
        card = form.rows["p001"]
        stops = [widget for widget in card.stops() if widget.isVisibleTo(form) and widget.isEnabled() and bool(widget.focusPolicy() & Qt.TabFocus)]
        self.assertEqual([widget for widget in stops if widget is block.lines or block.lines.isAncestorOf(widget)], [block.lines], "읽은 글이 60줄이어도 Tab 정거장은 하나")
        for row in block.lines.rows:
            for inner in (row.check, row.edit_button, row.remove_button):
                self.assertEqual(inner.focusPolicy(), Qt.ClickFocus)
        names = [widget.accessibleName() for widget in stops if block.isAncestorOf(widget)]
        self.assertEqual(names[0:3], ["사진 1 글자 다시 읽기", "사진 1 글자를 더 크게 다시 읽기", "사진 1 읽은 글 4줄 중 1번째, 확인 전"], names)

    def test_tab_goes_through_the_block_in_reading_order_into_the_place_button(self):
        window, form, block = self.done()
        card = form.rows["p001"]
        chips = [chip for chip in card.stops() if isinstance(chip, QAbstractButton) and chip.property("focus_key") and "pho:setting:p001" in chip.property("focus_key") and chip.focusPolicy() == Qt.StrongFocus]
        self.assertTrue(chips, "장소 분위기 칩의 Tab 정거장이 있다")
        last_chip = chips[-1]
        last_chip.setFocus(Qt.TabFocusReason)
        self.assertFocus(last_chip, "칩에서 시작한다")
        self.settle(2)
        seen = []
        for _ in range(7):
            self.key(QApplication.focusWidget(), Qt.Key_Tab)
            seen.append(QApplication.focusWidget())
        self.assertEqual(seen[:5], [block.read_button, block.bigger_button, block.lines, block.all_button, block.merge_button], [widget.accessibleName() for widget in seen])
        self.assertIs(seen[5], card.place_toggle, "읽은 글 칸 다음은 자리 정하기")

    def test_up_down_home_end_move_the_chosen_line_and_the_name_and_description_follow(self):
        window, form, block = self.done()
        lines = block.lines
        self.assertEqual((lines.current, lines.accessibleName(), lines.accessibleDescription()), (0, "사진 1 읽은 글 4줄 중 1번째, 확인 전", LINES[0]))
        self.key(lines, Qt.Key_Down)
        self.assertEqual((lines.current, lines.accessibleName(), lines.accessibleDescription()), (1, "사진 1 읽은 글 4줄 중 2번째, 확인 전", LINES[1]))
        self.key(lines, Qt.Key_End)
        self.assertEqual(lines.current, 3)
        self.key(lines, Qt.Key_Down)
        self.assertEqual(lines.current, 3, "끝에서 멈춘다(돌지 않는다)")
        self.key(lines, Qt.Key_Home)
        self.key(lines, Qt.Key_Up)
        self.assertEqual(lines.current, 0)
        self.assertFocus(lines, "방향키는 목록 밖으로 포커스를 보내지 않는다")
        self.assertEqual([row.property("current") for row in lines.rows], [True, False, False, False])

    def test_space_toggles_the_chosen_line_and_the_accessible_name_says_confirmed(self):
        window, form, block = self.done()
        lines = block.lines
        self.key(lines, Qt.Key_Down)
        self.key(lines, Qt.Key_Space)
        self.assertEqual([item.confirmed for item in form.board.photo("p001").visible_text], [False, True, False, False])
        self.assertEqual(lines.accessibleName(), "사진 1 읽은 글 4줄 중 2번째, 확인함")
        self.assertEqual((lines.rows[1].state.plain_text(), lines.rows[1].check.isChecked()), ("확인함", True))
        self.key(lines, Qt.Key_Space)
        self.assertEqual([item.confirmed for item in form.board.photo("p001").visible_text], [False] * 4)
        self.assertEqual(lines.accessibleName(), "사진 1 읽은 글 4줄 중 2번째, 확인 전")
        self.assertFocus(lines)

    def test_enter_opens_the_box_with_the_text_and_enter_again_saves_and_goes_to_the_next_line(self):
        window, form, block = self.done()
        lines = block.lines
        self.key(lines, Qt.Key_Return)
        editor = lines.rows[0].editor
        self.assertEqual((editor.isVisibleTo(form), editor.text(), editor.accessibleName(), lines.rows[0].text.isVisibleTo(form)), (True, LINES[0], "사진 1 읽은 글 1번째 줄 글자", False))
        self.assertFocus(editor)
        editor.setText("한우 불고기 전골 29,000원")
        self.key(editor, Qt.Key_Return)
        self.assertEqual(form.board.photo("p001").visible_text[0].text, "한우 불고기 전골 29,000원")
        self.assertEqual((lines.rows[0].editor.isVisibleTo(form), lines.current, QApplication.focusWidget()), (False, 1, lines))
        self.assertEqual(lines.rows[0].text.plain_text(), "한우 불고기 전골 29,000원")

    def test_f2_edits_a_confirmed_line_and_editing_makes_it_not_confirmed_again(self):
        window, form, block = self.done()
        lines = block.lines
        self.key(lines, Qt.Key_Space)
        self.assertTrue(form.board.photo("p001").visible_text[0].confirmed)
        self.key(lines, Qt.Key_F2)
        editor = lines.rows[0].editor
        editor.setText("고친 글")
        self.key(editor, Qt.Key_Return)
        self.assertEqual([(item.text, item.confirmed) for item in form.board.photo("p001").visible_text][0], ("고친 글", False))
        self.assertEqual(lines.rows[0].state.plain_text(), "확인 전")

    def test_escape_in_the_box_stops_editing_without_closing_the_sheet_and_the_text_stays(self):
        window, form, block = self.done()
        lines = block.lines
        self.key(lines, Qt.Key_F2)
        editor = lines.rows[0].editor
        editor.setText("버릴 글")
        self.key(editor, Qt.Key_Escape)
        self.assertIsNotNone(window.photo_form, "창은 닫히지 않는다")
        self.assertEqual((editor.isVisibleTo(form), lines.rows[0].text.plain_text(), form.board.photo("p001").visible_text[0].text, QApplication.focusWidget()), (False, LINES[0], LINES[0], lines))

    def test_escape_in_the_box_stops_only_the_editing_even_while_the_whole_sheet_asks_to_confirm_all(self):
        """고치는 입력 칸은 창의 Esc 단축키보다 먼저 Esc 를 받는다(`ShortcutOverride`) — 단축키 길로 가면 사진 정리 창의 '모두 확인' 확인 줄이 먼저 닫히고 고치던 글은 그대로 남는다."""
        window, form, block = self.done()
        lines = block.lines
        form.all_button.click()
        self.settle(3)
        self.assertTrue(form.board.confirm_all_asked, "창 전체의 모두 확인 확인 줄이 떠 있다")
        lines.setFocus(Qt.TabFocusReason)
        self.key(lines, Qt.Key_F2)
        editor = lines.rows[0].editor
        self.assertTrue(editor.isVisibleTo(form))
        self.key(editor, Qt.Key_Escape)
        self.assertEqual((lines.editing, bool(form.board.confirm_all_asked), window.photo_form is not None), (None, True, True), "Esc 한 번은 고치기만 그만둔다 — 확인 줄은 그대로다")

    def test_a_text_the_entrance_check_refuses_stays_in_the_box_with_the_reason_under_the_line(self):
        window, form, block = self.done()
        lines = block.lines
        self.key(lines, Qt.Key_F2)
        editor = lines.rows[0].editor
        editor.setText("900101-1234567")
        self.key(editor, Qt.Key_Return)
        row = lines.rows[0]
        self.assertTrue(editor.isVisibleTo(form), "받아들이지 않으면 고치기를 끝내지 않는다")
        self.assertEqual((row.error.isVisibleTo(form), "주민등록번호나 카드 번호처럼 보이는 숫자는 받지 않아요" in row.error.plain_text()), (True, True))
        self.assertEqual(form.board.photo("p001").visible_text[0].text, LINES[0])
        self.key(editor, Qt.Key_Escape)
        self.assertFalse(row.error.isVisibleTo(form), "그만두면 이유도 사라진다")
        editor_empty = None
        self.key(lines, Qt.Key_F2)
        editor_empty = lines.rows[0].editor
        editor_empty.setText("   ")
        self.key(editor_empty, Qt.Key_Return)
        self.assertEqual(lines.rows[0].error.plain_text(), T["pho_ocr_line_empty"])
        self.assertEqual(form.board.photo("p001").visible_text[0].text, LINES[0], "비워서 줄이 사라지지 않는다")

    def test_delete_removes_the_chosen_line_and_the_undo_button_brings_it_back_once(self):
        window, form, block = self.done()
        lines = block.lines
        self.key(lines, Qt.Key_Down)
        self.key(lines, Qt.Key_Delete)
        self.assertEqual([item.text for item in form.board.photo("p001").visible_text], [LINES[0], LINES[2], LINES[3]])
        self.assertEqual((self.row_texts(block), lines.current, QApplication.focusWidget()), ([LINES[0], LINES[2], LINES[3]], 1, lines))
        self.assertTrue(block.undo_button.isVisibleTo(form))
        self.assertEqual((block.undo_button.text(), block.removed.plain_text()), ("뺀 줄 되돌리기", "읽은 글에서 한 줄을 뺐어요."))
        block.undo_button.click()
        self.settle(3)
        self.assertEqual(self.row_texts(block), list(LINES))
        self.assertFalse(block.undo_button.isVisibleTo(form))

    def test_holding_a_key_down_never_repeats_the_destructive_ones(self):
        window, form, block = self.done()
        lines = block.lines
        for key in (Qt.Key_Delete, Qt.Key_Space, Qt.Key_F2):
            QApplication.sendEvent(lines, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, "", True, 1))          # 자동 반복(키를 계속 누름)
            self.settle(1)
        self.assertEqual(self.row_texts(block), list(LINES))
        self.assertEqual(([item.confirmed for item in form.board.photo("p001").visible_text], lines.editing), ([False] * 4, None))

    def test_the_arrow_keys_with_a_modifier_are_left_alone(self):
        window, form, block = self.done()
        lines = block.lines
        self.key(lines, Qt.Key_Down, Qt.ControlModifier)
        self.assertEqual(lines.current, 0)

    def test_the_mouse_checkbox_remove_edit_and_double_click_work_and_give_the_focus_back_to_the_list(self):
        window, form, block = self.done()
        lines = block.lines
        lines.rows[2].check.click()
        self.settle(3)
        self.assertEqual(([item.confirmed for item in form.board.photo("p001").visible_text], lines.current, QApplication.focusWidget()), ([False, False, True, False], 2, lines))
        lines.rows[0].edit_button.click()
        self.settle(3)
        self.assertEqual((lines.editing, lines.rows[0].editor.isVisibleTo(form)), (0, True))
        self.key(lines.rows[0].editor, Qt.Key_Escape)
        lines.rows[3].remove_button.click()
        self.settle(3)
        self.assertEqual(self.row_texts(block), list(LINES[:3]))
        QTest.mouseDClick(lines.rows[1].text, Qt.LeftButton)
        self.settle(3)
        self.assertEqual(lines.editing, 1)
        self.key(lines.rows[1].editor, Qt.Key_Escape)

    def test_merge_joins_the_chosen_line_with_the_one_below_and_is_off_on_the_last_line(self):
        window, form, block = self.done()
        lines = block.lines
        self.assertEqual(block.merge_button.accessibleName(), "사진 1 읽은 글 1번째 줄을 아래 줄과 합치기")
        self.key(lines, Qt.Key_Down)
        self.assertEqual(block.merge_button.accessibleName(), "사진 1 읽은 글 2번째 줄을 아래 줄과 합치기")
        block.merge_button.click()
        self.settle(3)
        self.assertEqual(self.row_texts(block), [LINES[0], f"{LINES[1]} {LINES[2]}", LINES[3]])
        self.assertEqual(form.board.photo("p001").visible_text[1].confirmed, False)
        lines.setFocus(Qt.TabFocusReason)
        self.key(lines, Qt.Key_End)
        self.assertFalse(block.merge_button.isEnabled(), "마지막 줄은 아래 줄이 없다")

    def test_the_list_is_locked_and_not_a_tab_stop_while_it_reads_again(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        provider.release()                                                                  # 첫 읽기는 바로 끝나게 하고
        window, form, block = self.done(provider=provider)
        provider.gate.clear()                                                               # 다시 읽기만 붙잡는다
        provider.started.clear()
        block.read_button.click()
        self.settle(3)
        block.reread.yes.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        self.assertFalse(block.lines.isEnabled())
        self.assertEqual(block.lines.isEnabled() and bool(block.lines.focusPolicy() & Qt.TabFocus), False)
        for row in block.lines.rows:
            self.assertFalse(row.check.isEnabled() or row.edit_button.isEnabled() or row.remove_button.isEnabled())
        self.assertFalse(block.all_button.isEnabled())
        provider.release()
        self.wait_state(form, "done")
        self.assertTrue(block.lines.isEnabled())

    def test_moving_the_line_and_changing_the_confirmation_tell_the_accessibility_layer(self):
        window, form, block = self.done()
        lines = block.lines
        events = self.watch_accessibility()
        self.key(lines, Qt.Key_Down)
        moved = [kind for kind, target in events if target is lines]
        self.assertIn(QAccessible.NameChanged, moved, "줄을 옮기면 이름이 바뀌었다고 알린다")
        events.clear()
        self.key(lines, Qt.Key_Space)
        self.assertIn(QAccessible.NameChanged, [kind for kind, target in events if target is lines], "맞아요를 켜면 이름('확인함')이 바뀌었다고 알린다")
        events.clear()
        self.key(lines, Qt.Key_Space)
        self.key(lines, Qt.Key_Space)
        again = [kind for kind, target in events if target is lines]
        self.assertTrue(again.count(QAccessible.NameChanged) >= 2)

    def test_a_line_under_the_list_tells_the_keys(self):
        window, form, block = self.done()
        self.assertEqual((block.keys.plain_text(), block.keys.isVisibleTo(form)), (T["pho_ocr_keys"], True))
        for key in ("방향키", "스페이스", "엔터", "F2", "Delete"):
            self.assertIn(key, T["pho_ocr_keys"])
        self.assertEqual(block.lines.toolTip(), "", "툴팁은 긴 목록 아래 화면 밖에 뜨므로 쓰지 않는다")


# ---- 4) Esc·포커스 ------------------------------------------------------------------------------------------------------------------
class EscapeTest(OcrBase):
    def test_escape_on_the_cancel_button_cancels_the_read_and_keeps_the_sheet_open(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=1, provider=provider)
        block = self.block(form)
        block.read_button.setFocus(Qt.TabFocusReason)
        block.read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        self.assertFocus(block.cancel_button, "누른 단추가 사라지면 취소 단추로 포커스가 간다")
        self.key(block.cancel_button, Qt.Key_Escape)
        self.assertIsNotNone(window.photo_form)
        self.assertEqual(block.status.plain_text(), T["pho_ocr_cancelled"])
        provider.release()
        self.wait_for(lambda: window.state.ocr.active is None)

    def test_escape_closes_the_question_first_and_the_sheet_only_when_there_is_nothing_to_stop(self):
        window, form = self.ocr_sheet(photos=1)
        block = self.read_done(form)
        block.all_button.click()
        self.settle(3)
        self.assertFocus(block.all_ask.no)
        self.key(block.all_ask.no, Qt.Key_Escape)
        self.assertEqual((block.all_ask.isVisibleTo(form), window.photo_form is not None), (False, True), "확인 줄만 닫힌다")
        self.assertFocus(block.lines)
        block.read_button.click()
        self.settle(3)
        self.key(block.reread.no, Qt.Key_Escape)
        self.assertEqual((block.reread.isVisibleTo(form), window.photo_form is not None), (False, True))
        self.key(block.lines, Qt.Key_Escape)
        self.settle(4)
        self.assertIsNone(window.photo_form, "할 일이 없으면 Esc 는 창을 닫는다(지금과 같다)")

    def test_escape_somewhere_else_in_the_sheet_closes_it_even_while_a_read_runs_and_cancels_the_read(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=2, provider=provider)
        self.block(form).read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        form.rows["p002"].subject.edit.setFocus(Qt.TabFocusReason)
        self.key(form.rows["p002"].subject.edit, Qt.Key_Escape)
        self.settle(4)
        self.assertIsNone(window.photo_form)
        self.assertEqual(provider.cancelled, [1], "창을 닫으면 읽는 중인 요청이 취소된다")
        provider.release()
        self.wait_for(lambda: window.state.ocr.active is None)

    def test_the_focus_goes_to_the_read_button_when_the_question_closes_and_there_is_no_list(self):
        window, form = self.ocr_sheet(photos=1, provider=pov.FakeOcrProvider(default=pov.OcrOutcome(())))
        block = self.read_done(form)
        block.read_button.setFocus(Qt.TabFocusReason)
        self.assertEqual(block.reread.isVisibleTo(form), False, "읽은 줄이 없으면 확인 없이 바로 읽는다")
        block.read_button.click()
        self.wait_for(lambda: len(window.state.ocr.provider.calls) == 2 and block.vm["state"] == "done")
        self.assertFocus(block.read_button)


# ---- 5) 읽는 중에 일어나는 일 ------------------------------------------------------------------------------------------------------
class InterplayTest(OcrBase):
    def test_closing_the_sheet_while_it_reads_cancels_the_request_and_drops_the_late_result(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=1, provider=provider)
        self.block(form).read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        self.assertEqual(window.photos_close(), "closed")
        self.settle(3)
        self.assertEqual(provider.cancelled, [1])
        provider.release()
        self.wait_for(lambda: window.state.ocr.active is None)
        self.settle(3)
        self.assertEqual(window.state.drafts.photos.photo("p001").visible_text, (), "닫은 뒤에 온 결과는 목록을 바꾸지 않는다")
        window, form = self.sheet(window)
        self.assertEqual(self.block(form).vm["state"], "cancelled", "다시 열면 멈춘 상태이고 읽은 글은 없다")

    def test_removing_the_photo_being_read_cancels_it_and_the_late_result_goes_nowhere(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=2, provider=provider)
        self.block(form, "p001").read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        form.rows["p001"].remove.click()
        self.settle(4)
        self.assertEqual(provider.cancelled, [1])
        provider.release()
        self.wait_for(lambda: window.state.ocr.active is None)
        self.settle(3)
        self.assertEqual([photo.photo_id for photo in window.state.drafts.photos.manifest.photos], ["p002"])
        self.assertEqual(window.state.drafts.photos.photo("p002").visible_text, (), "다른 사진에는 아무것도 들어가지 않았다")

    def test_relinking_the_photo_being_read_cancels_it_and_the_late_result_goes_nowhere(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=2, provider=provider)
        self.block(form, "p001").read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        self.relinks.append(fake_path(9))
        self.assertEqual(window.photos_relink("p001"), "ok")
        self.settle(4)
        self.assertEqual(provider.cancelled, [1], "다른 파일로 이어 붙이면 읽던 요청이 취소된다")
        provider.release()
        self.wait_for(lambda: window.state.ocr.active is None)
        self.settle(3)
        self.assertEqual((window.state.drafts.photos.photo("p001").visible_text, self.block(form, "p001").vm["state"]), ((), "idle"), "옛 파일의 결과는 새 파일에 들어가지 않는다")
        self.assertTrue(self.block(form, "p001").read_button.isVisibleTo(form))

    def test_leaving_the_draft_resets_everything_and_the_old_result_never_shows(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=1, provider=provider)
        self.block(form).read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        window.close_dialog()
        window.state.drafts.leave()
        self.settle(3)
        provider.release()
        self.wait_for(lambda: window.state.ocr.active is None)
        self.settle(3)
        self.assertEqual((window.state.drafts.photos.count, window.state.ocr.states), (0, {}))

    def test_a_stale_cancel_number_is_never_forwarded_to_the_request_that_runs_now(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=1, provider=provider)
        self.block(form).read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        ocr = window.state.ocr
        self.assertEqual(ocr.active.token, 1)
        ocr.cancels.append(99)                                                               # 이미 끝난 요청의 낡은 취소 번호
        window.ocr_runner.sync()
        self.assertEqual((provider.cancelled, ocr.cancels), ([], []), "지금 읽는 요청이 아닌 번호는 알리지 않고 버린다")
        provider.release()
        self.wait_state(form, "done")

    def test_a_cancel_that_comes_while_the_picture_is_being_read_is_not_sent_on_to_the_worker(self):
        """독립 검증 S Q1 — 어댑터가 작업 스레드에서 부르는 `_prepare` 훅은 사진을 읽고 줄이는 사이에 취소됐으면 작업자에 보내지 않는다(어댑터는 시작에서 취소 표시를 지워 이 확인이 없으면 취소가 사라진다)."""
        from chanceblog_desktop.errors import AppError
        window, form = self.ocr_sheet(photos=1)
        runner = window.ocr_runner
        job = mock.Mock(token=41, size="960", cancelled=False)
        runner._paths[41] = "합성 위치"
        seen = []

        def cancelled_meanwhile(path, size):
            seen.append((path, size))
            job.cancelled = True
            return (2, 1, b"abcdef")

        runner.reader = cancelled_meanwhile
        with self.assertRaises(AppError) as caught:
            runner._prepare(job)
        self.assertEqual((caught.exception.code, seen), ("OCR_FAILED", [("합성 위치", "960")]))
        job.cancelled = False
        runner.reader = lambda path, size: (2, 1, b"abcdef")
        self.assertEqual(runner._prepare(job), (2, 1, b"abcdef"), "취소되지 않았으면 읽은 것을 그대로 준다")
        with self.assertRaises(AppError) as unknown:
            runner._prepare(mock.Mock(token=42, size="960", cancelled=False))
        self.assertEqual(unknown.exception.code, "OCR_FAILED", "위치가 없는 요청은 읽지 않는다")

    def test_the_picture_location_is_kept_only_while_it_is_read(self):
        """독립 검증 S Q2 — 사진 위치는 진행자의 `_paths` 에 읽는 동안만 있다(끝나면 — 결과든 실패든 — 지운다)."""
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=1, provider=provider)
        runner = window.ocr_runner
        self.assertEqual(runner._paths, {})
        self.block(form).read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.assertEqual(list(runner._paths.values()), [form.board.local_path("p001")], "읽는 동안은 이 요청의 위치 하나")
        provider.release()
        self.wait_state(form, "done")
        self.assertEqual(runner._paths, {}, "끝나면 비운다")

    def test_a_tick_expires_a_read_that_took_too_long_and_asks_the_reader_to_end_it(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        provider.terminate_calls = []
        provider.terminate = lambda: provider.terminate_calls.append(1)
        window, form = self.ocr_sheet(photos=1, provider=provider)
        block = self.block(form)
        block.read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        self.clock.advance(pov.READ_TIMEOUT_S + 1)
        window.ocr_runner.tick()
        self.settle(4)
        self.assertEqual(block.status.plain_text(), T["pho_ocr_err_timeout"])
        self.wait_for(lambda: provider.terminate_calls == [1])                                  # 트리 종료는 화면을 붙잡지 않으려고 별도 스레드가 부른다
        self.assertEqual(provider.terminate_calls, [1], "읽는 쪽에 프로세스 트리 종료를 부탁했다")
        provider.release()
        self.wait_for(lambda: window.state.ocr.active is None)

    def test_a_cancel_that_the_reader_does_not_finish_in_three_seconds_is_ended_by_the_tick(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        provider.terminate_calls = []
        provider.terminate = lambda: provider.terminate_calls.append(1)
        window, form = self.ocr_sheet(photos=2, provider=provider)
        self.block(form, "p001").read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        self.block(form, "p001").cancel_button.click()
        self.settle(3)
        window.ocr_runner.tick()                                                               # 취소한 시각을 처음 확인한 때부터 3초를 센다
        self.clock.advance(pov.CANCEL_WAIT_S + 1)
        window.ocr_runner.tick()
        self.settle(3)
        self.wait_for(lambda: provider.terminate_calls == [1])
        self.assertEqual(provider.terminate_calls, [1])
        provider.release()
        self.wait_for(lambda: window.state.ocr.active is None)

    def test_the_idle_worker_is_asked_to_leave_after_five_minutes_without_blocking_the_screen(self):
        provider = pov.FakeOcrProvider(default=pov.OcrOutcome(LINES))
        calls = []
        provider.maybe_idle_exit = lambda: calls.append(1) or True
        window, form = self.ocr_sheet(photos=1, provider=provider)
        self.read_done(form)
        runner = window.ocr_runner
        self.assertTrue(window.state.ocr.worker_ready)
        self.clock.advance(pov.IDLE_EXIT_S - 1)
        runner.tick()
        self.settle(2)
        self.assertEqual(calls, [])
        self.clock.advance(2)
        runner.tick()
        self.wait_for(lambda: calls == [1])
        self.assertFalse(window.state.ocr.worker_ready, "다음 읽기는 준비부터 다시 한다")

    def test_closing_the_app_ends_the_worker_even_while_a_read_runs(self):
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=1, provider=provider)
        self.block(form).read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(3)
        started = time.monotonic()
        window._close_confirmed = True                                                         # 저장하지 않은 사진 정보가 있어 닫기 확인이 먼저 뜬다 — 사용자가 '그래도 닫기' 를 눌렀다고 본다
        window.close()
        self.assertLess(time.monotonic() - started, 6, "앱을 닫는 데 오래 걸리지 않는다")
        self.assertEqual((provider.shut_down >= 1, provider.cancelled), (True, [1]))
        provider.release()

    def test_the_runner_goes_quiet_when_nothing_runs(self):
        provider = pov.FakeOcrProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=1, provider=provider)
        runner = window.ocr_runner
        self.read_done(form)
        self.assertFalse(runner.busy())
        self.assertEqual(runner._timer.interval(), runner.idle_ms, "일이 없고 작업자만 떠 있으면 느린 시계다")
        window.state.ocr.worker_stopped()
        runner.sync()
        self.assertFalse(runner._timer.isActive(), "일도 작업자도 없으면 시계가 멈춘다")


# ---- 6) 크기·줄이 많을 때 ------------------------------------------------------------------------------------------------------------
class FitTest(OcrBase):
    def check_fit(self, window, form, label):
        dialog = window.dialog
        self.settle(6)                                                                     # 먼저 이벤트 루프를 여섯 바퀴 돌린다(배율 점검 자식 프로세스와 같다) — 잡히기 전에 '잘림 없음' 으로 지나가지 않게
        ui_offscreen.wait_until(self.app, lambda: not ui_offscreen.find_clipping(dialog) and not ui_offscreen.find_squeezed(dialog), 5)      # 겹친 배치(줄 → 칸 → 사진 줄 → 창)는 층마다 이벤트 루프를 한 바퀴씩 돌아 자리를 잡는다 — 실제 화면에서는 몇 밀리초지만 시험은 잡힐 때까지(최대 5초) 기다린 뒤 본다
        self.settle(2)
        self.assertTrue(window.rect().contains(dialog.geometry()), (label, dialog.geometry(), window.rect()))
        self.assertEqual(form.scroll.horizontalScrollBar().maximum(), 0, label)
        self.assertEqual(ui_offscreen.find_clipping(dialog), [], label)
        self.assertEqual(ui_offscreen.find_squeezed(dialog), [], label)
        for button in (form.add_button, form.all_button, form.close_button):
            bottom = button.mapTo(window, button.rect().bottomRight())
            self.assertTrue(window.rect().contains(bottom) and button.isVisible(), (label, button.accessibleName()))
        for block in [card.ocr_block for card in form.rows.values() if card.ocr_block is not None]:
            self.assertEqual(block.scroll.horizontalScrollBar().maximum(), 0, (label, "목록 안에도 가로 스크롤이 없다"))

    def test_every_state_fits_every_size_without_clipping_scrolling_sideways_or_hiding_the_buttons(self):
        for size in SIZES:
            with self.subTest(size=size):
                provider = BlockingProvider(default=pov.OcrOutcome(LINES + MANY[:20] + HIDDEN))
                window, form = self.ocr_sheet(photos=2, provider=provider, size=size)
                self.check_fit(window, form, (size, "읽기 전"))
                block = self.block(form)
                block.read_button.click()
                self.assertTrue(provider.started.wait(20))
                self.clock.advance(20)
                form.ocr_tick()
                self.check_fit(window, form, (size, "읽는 중·오래 걸림"))
                provider.release()
                self.wait_state(form, "done")
                self.check_fit(window, form, (size, "읽은 글 24줄"))
                self.assertEqual(block.notes.plain_text(), T["pho_ocr_hidden"].format(m=len(HIDDEN)), (size, "거른 줄 안내(가장 긴 안내 글)가 실제로 보이는 채로 위의 잘림 점검을 지났다"))
                self.assertTrue(block.notes.isVisible(), size)
                block.lines.setFocus(Qt.TabFocusReason)
                self.key(block.lines, Qt.Key_F2)
                block.lines.rows[0].editor.setText("가" * 150)
                self.check_fit(window, form, (size, "고치는 중"))
                block.lines.rows[0].editor.setText("900101-1234567")
                self.key(block.lines.rows[0].editor, Qt.Key_Return)
                self.check_fit(window, form, (size, "이유가 보이는 줄"))
                self.key(block.lines.rows[0].editor, Qt.Key_Escape)
                block.all_button.click()
                self.settle(4)
                self.check_fit(window, form, (size, "모두 맞아요 확인 줄"))
                block.all_ask.no.click()
                block.read_button.click()
                self.settle(4)
                self.check_fit(window, form, (size, "다시 읽기 확인 줄"))
                block.reread.no.click()
                self.settle(3)
                window.close_dialog()
                window.state.drafts.leave()                                               # 고친 사진 정보가 남아 있으면 닫기가 확인을 먼저 묻는다 — 크기마다 창을 말끔히 닫는다
                window.close()

    def test_the_window_grows_when_the_status_gains_its_second_line_even_though_nothing_else_redraws_it(self):
        """독립 검증 S Q11 — 읽는 중 15초가 넘어 상태 글이 두 줄이 되면(시계 한 번이 상태 줄만 바꾼다 — `ocr_tick`) 창의 키가 그만큼 커진다."""
        provider = BlockingProvider(default=pov.OcrOutcome(LINES))
        window, form = self.ocr_sheet(photos=1, provider=provider, size=(1600, 1700))                   # 창이 충분히 높아 대화상자가 창 높이 한도에 닿지 않는다(한도에 닿으면 키가 늘 같아 맞춤을 볼 수 없다)
        block = self.block(form)
        block.read_button.click()
        self.assertTrue(provider.started.wait(20))
        self.settle(8)
        one_line = window.dialog.height()
        self.assertLess(one_line, window.height() - 32 - 40, "대화상자가 창 높이 한도보다 한참 낮다")
        self.assertEqual(block.status.plain_text().count("\n"), 0)
        self.clock.advance(20)
        form.ocr_tick()
        self.assertEqual(block.status.plain_text().count("\n"), 1, "15초가 넘어 보조 글이 둘째 줄로 붙었다")
        self.settle(8)
        ui_offscreen.wait_until(self.app, lambda: window.dialog.height() > one_line, 5)
        self.assertGreater(window.dialog.height(), one_line, "상태 글이 두 줄이 되면 창이 그만큼 커진다")
        provider.release()
        self.wait_state(form, "done")

    def test_sixty_lines_scroll_inside_a_capped_list_and_the_keyboard_keeps_the_chosen_line_in_view(self):
        provider = pov.FakeOcrProvider(default=pov.OcrOutcome(MANY))
        window, form = self.ocr_sheet(photos=1, provider=provider, size=(1366, 768))
        block = self.read_done(form)
        self.settle(10)                                                                     # 줄 위젯 예순 개가 겹친 배치(줄 → 목록 → 칸 → 사진 줄)에 자리를 잡을 때까지 — 일찍 재면 변이(상한 없앰)도 통과한다
        self.assertEqual(len(block.lines.rows), 60)
        scroll = block.scroll
        self.assertLessEqual(scroll.height(), parts.LIST_MAX_HEIGHT + 2 * scroll.frameWidth() + 1, "목록 높이에는 상한이 있다")
        self.assertGreaterEqual(scroll.viewport().height(), 7 * block.lines.rows[0].height(), "상한이 너무 낮지 않다 — 줄이 많아도 한 번에 일곱 줄 넘게 보인다(독립 검증 Q MQ6)")
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0, "줄이 많으면 목록 안에서 스크롤된다")
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        block.lines.setFocus(Qt.TabFocusReason)
        self.key(block.lines, Qt.Key_End)
        self.settle(3)
        row = block.lines.rows[59]
        top = row.mapTo(scroll.viewport(), row.rect().topLeft()).y()
        bottom = row.mapTo(scroll.viewport(), row.rect().bottomLeft()).y()
        self.assertTrue(0 <= top and bottom <= scroll.viewport().height() + 1, ("마지막 줄이 목록 안에서 보인다", top, bottom, scroll.viewport().height()))
        self.assertEqual(block.lines.accessibleName(), "사진 1 읽은 글 60줄 중 60번째, 확인 전")
        for _ in range(5):
            self.key(block.lines, Qt.Key_Up)
        self.assertEqual(block.lines.current, 54)

    def test_a_low_window_scrolls_both_the_body_and_the_list_and_keeps_the_chosen_line_in_view(self):
        provider = pov.FakeOcrProvider(default=pov.OcrOutcome(MANY))
        window, form = self.ocr_sheet(photos=1, provider=provider, size=(900, 560))
        block = self.read_done(form)
        self.check_fit(window, form, "낮은 창·60줄")
        self.assertGreater(form.scroll.verticalScrollBar().maximum(), 0, "몸이 길어 창 몸이 스크롤된다")
        self.assertGreater(block.scroll.verticalScrollBar().maximum(), 0, "목록은 그 안에서 따로 스크롤된다")
        for button in (form.add_button, form.all_button, form.close_button):
            self.assertFalse(form.scroll.isAncestorOf(button), "단추 줄은 스크롤 밖에 늘 보인다")
        block.lines.setFocus(Qt.TabFocusReason)
        for key, index in ((Qt.Key_End, 59), (Qt.Key_Home, 0)):
            self.key(block.lines, key)
            self.settle(3)
            self.assertEqual(block.lines.current, index)
            row = block.lines.rows[index]
            for area in (block.scroll, form.scroll):
                top, bottom = row.mapTo(area.viewport(), row.rect().topLeft()).y(), row.mapTo(area.viewport(), row.rect().bottomLeft()).y()
                self.assertTrue(-1 <= top and bottom <= area.viewport().height() + 1, (index, "고른 줄이 두 스크롤 영역 안에서 보인다", top, bottom, area.viewport().height()))

    def test_sixty_lines_do_not_make_the_sheet_slow(self):
        provider = pov.FakeOcrProvider(default=pov.OcrOutcome(MANY))
        window, form = self.ocr_sheet(photos=3, provider=provider, size=(1366, 768))
        for photo_id in ("p001", "p002", "p003"):
            self.read_done(form, photo_id)
        started = time.perf_counter()
        for _ in range(5):
            form.refresh()
        refresh = (time.perf_counter() - started) / 5
        block = self.block(form)
        block.lines.setFocus(Qt.TabFocusReason)
        started = time.perf_counter()
        for _ in range(20):
            QTest.keyClick(block.lines, Qt.Key_Down)
        move = (time.perf_counter() - started) / 20
        self.assertLess(refresh, 1.5, f"세 장 x 60줄 다시 그리기 {refresh:.3f}초")
        self.assertLess(move, 0.3, f"방향키 한 번 {move:.3f}초")
        self.assertEqual(len(block.lines.rows), 60, "줄 위젯은 줄 수만큼뿐이다")

    def test_the_list_widgets_follow_the_line_count_without_leaving_extra_ones(self):
        window, form = self.ocr_sheet(photos=1, provider=pov.FakeOcrProvider(default=pov.OcrOutcome(LINES)))
        block = self.read_done(form)
        lines = block.lines
        self.assertEqual(len(lines.rows), 4)
        lines.setFocus(Qt.TabFocusReason)
        for _ in range(4):
            self.key(lines, Qt.Key_Delete)
        self.assertEqual((len(lines.rows), block.result.isVisibleTo(form), block.none.plain_text()), (0, False, T["pho_ocr_all_removed"]))
        self.assertEqual(form.board.photo("p001").visible_text, ())


# ---- 6-1) 저장해 둔 초안을 열어 '다시 만들기' 를 할 때 ----------------------------------------------------------------------------------
class RegenTest(OcrBase):
    """저장해 둔 글에 있던 사진 속 글자 문단이 '다시 만들기' 로 소리 없이 빠지지 않는다(D-517 ④). 열어 둔 글의 상태는 컨트롤러의 `opened_saved` 로 흉내 낸다 — 진짜 열기 길은 순수 시험(`test_ui_photo_ocr_regen`)이 본다."""

    def closed_with_a_confirmed_photo(self):
        window, form = self.ocr_sheet(photos=1)
        form.rows["p001"].confirm_box.click()
        self.settle(3)
        self.assertEqual(window.photos_close(), "closed")
        self.settle(4)
        return window

    def test_a_reopened_draft_asks_first_says_what_may_vanish_and_the_safe_button_has_the_focus(self):
        window = self.closed_with_a_confirmed_photo()
        controller = window.state.drafts
        controller.opened_saved = True
        made = controller.make_count
        window.drf_remake()
        self.settle(3)
        self.assertTrue(window.dialog.is_open)
        shown = self.shown_texts(window.dialog)
        self.assertIn(T["pho_ocr_regen_title"], shown)
        self.assertIn(T["pho_ocr_regen_body"], shown)
        buttons = self.dialog_buttons(window)
        self.assertEqual(sorted(buttons), sorted([T["pho_ocr_regen_ok"], T["drf_cancel"]]))
        self.assertFocus(buttons[T["drf_cancel"]], "처음 포커스는 안전한 쪽(취소)")
        buttons[T["drf_cancel"]].click()
        self.settle(3)
        self.assertEqual((window.dialog.is_open, controller.make_count, controller.opened_saved), (False, made, True), "그만두면 아무것도 만들지 않는다")
        window.drf_remake()
        self.settle(3)
        self.assertTrue(window.dialog.is_open, "그만둔 뒤 다시 눌러도 묻는다")
        self.dialog_buttons(window)[T["pho_ocr_regen_ok"]].click()
        self.assertTrue(self.wait_draft(window))
        self.assertEqual((controller.make_count, controller.opened_saved), (made + 1, False), "물은 뒤에는 새 글을 만든다")

    def test_a_draft_made_in_this_window_is_remade_without_a_question(self):
        window = self.closed_with_a_confirmed_photo()
        controller = window.state.drafts
        self.assertFalse(controller.opened_saved)
        made = controller.make_count
        window.drf_remake()
        self.settle(3)
        self.assertFalse(window.dialog.is_open, "열어 둔 글이 아니면 지금처럼 곧바로 만든다")
        self.assertTrue(self.wait_draft(window))
        self.assertEqual(controller.make_count, made + 1)

    def test_with_edited_text_the_old_dialog_gets_one_more_sentence(self):
        window = self.closed_with_a_confirmed_photo()
        controller = window.state.drafts
        controller.opened_saved = True
        controller.set_body(controller.body + "\n\n내가 고친 문단이에요.")
        window.drf_remake()
        self.settle(3)
        shown = self.shown_texts(window.dialog)
        self.assertIn(T["drf_regen_title"], shown)
        self.assertIn(T["drf_regen_body"] + " " + T["pho_ocr_regen_more"], shown)
        self.assertEqual(sorted(self.dialog_buttons(window)), sorted([T["drf_regen_ok"], T["drf_cancel"]]))
        self.dialog_buttons(window)[T["drf_cancel"]].click()
        self.settle(3)


class AskInViewTest(OcrBase):
    """독립 검증 Q QP-19 — 확인 줄('읽은 글 모두 맞아요' 질문·'다시 읽기' 확인 줄)이 처음 뜰 때 사용자가 보는 곳 안으로 온다. 프로그램으로 옮긴 포커스는 스크롤이 따라가지 않아서, 누른 단추가 몸의 아래쪽에 있으면 확인 줄이 통째로 화면 밖에 떴다(단추 아래 8px 에서 눌렀을 때 4/70px 만 보임)."""
    WINDOWS = ((1366, 768), (1280, 720), (900, 560))

    def seen(self, widget, form):
        """위젯이 창 몸(스크롤 영역)의 보이는 곳 안에 들어온 높이 → `(들어온 px, 전체 px)`."""
        area = form.scroll
        top = widget.mapTo(area.viewport(), widget.rect().topLeft()).y()
        return max(0, min(top + widget.height(), area.viewport().height()) - max(top, 0)), widget.height()

    def put_at_bottom_edge(self, form, widget, margin=8):
        """단추가 몸의 보이는 곳 아래 끝(`margin` 위)에 오게 몸을 스크롤한다 — 사용자가 단추를 눌러 보려고 스크롤해 둔 모양."""
        area = form.scroll
        bar = area.verticalScrollBar()
        top = widget.mapTo(area.widget(), widget.rect().topLeft()).y()
        bar.setValue(max(0, min(top + widget.height() + margin - area.viewport().height(), bar.maximum())))
        self.settle(5)

    def assertInView(self, form, widgets, label):
        ui_offscreen.wait_until(self.app, lambda: all(self.seen(widget, form)[0] == self.seen(widget, form)[1] for widget in widgets), 5)       # 겹친 배치가 자리를 잡은 뒤에 맞춰지므로 기다린다
        self.settle(2)
        for widget in widgets:
            shown, total = self.seen(widget, form)
            self.assertEqual(shown, total, (label, self.describe(widget), "몸의 보이는 곳 안에 온전히 들어와야 한다"))

    def test_the_all_right_question_is_fully_in_view_when_it_opens_under_a_button_at_the_bottom_edge(self):
        for size in self.WINDOWS:
            with self.subTest(size=size):
                provider = pov.FakeOcrProvider(default=pov.OcrOutcome(MANY[:24]))
                window, form = self.ocr_sheet(photos=1, provider=provider, size=size)
                block = self.read_done(form)
                self.settle(8)
                self.put_at_bottom_edge(form, block.all_button)
                shown, total = self.seen(block.all_button, form)
                self.assertEqual(shown, total, "먼저 단추가 온전히 보이게 맞춰 두었다")
                QTest.mouseClick(block.all_button, Qt.LeftButton)
                self.settle(3)
                self.assertTrue(block.all_ask.isVisibleTo(form))
                self.assertFocus(block.all_ask.no, "처음 포커스는 안전한 쪽")
                self.assertInView(form, (block.all_ask, block.all_ask.message, block.all_ask.yes, block.all_ask.no), (size, "마우스"))
                block.all_ask.no.click()
                window.close_dialog()

    def test_the_all_right_question_is_fully_in_view_after_tab_and_space_too(self):
        for size in ((1366, 768), (900, 560)):
            with self.subTest(size=size):
                provider = pov.FakeOcrProvider(default=pov.OcrOutcome(MANY[:24]))
                window, form = self.ocr_sheet(photos=2, provider=provider, size=size)
                block = self.read_done(form)
                self.settle(8)
                form.scroll.verticalScrollBar().setValue(0)
                self.settle(4)
                block.lines.setFocus(Qt.OtherFocusReason)
                self.settle(3)
                self.key(block.lines, Qt.Key_Tab)
                self.assertFocus(block.all_button, "목록 다음 Tab 정거장은 모두 맞아요 단추")
                self.key(block.all_button, Qt.Key_Space)
                self.settle(3)
                self.assertTrue(block.all_ask.isVisibleTo(form))
                self.assertInView(form, (block.all_ask, block.all_ask.yes, block.all_ask.no), (size, "Tab 과 Space"))
                block.all_ask.no.click()
                window.close_dialog()

    def test_the_reread_question_is_fully_in_view_too_for_a_lower_photo_row(self):
        for size in ((1366, 768), (1280, 720)):
            with self.subTest(size=size):
                provider = pov.FakeOcrProvider(default=pov.OcrOutcome(MANY[:24]))
                window, form = self.ocr_sheet(photos=2, provider=provider, size=size)
                self.read_done(form)
                second = self.read_done(form, "p002")
                self.settle(8)
                self.put_at_bottom_edge(form, second.read_button)
                shown, total = self.seen(second.read_button, form)
                self.assertEqual(shown, total, "먼저 단추가 온전히 보이게 맞춰 두었다")
                QTest.mouseClick(second.read_button, Qt.LeftButton)
                self.settle(3)
                self.assertTrue(second.reread.isVisibleTo(form))
                self.assertInView(form, (second.reread, second.reread.yes, second.reread.no), (size, "다시 읽기"))
                second.reread.no.click()
                window.close_dialog()

    def test_a_question_that_is_already_open_does_not_pull_the_scroll_back_when_the_sheet_is_drawn_again(self):
        provider = pov.FakeOcrProvider(default=pov.OcrOutcome(MANY[:24]))
        window, form = self.ocr_sheet(photos=1, provider=provider, size=(1366, 768))
        block = self.read_done(form)
        self.settle(8)
        self.put_at_bottom_edge(form, block.all_button)
        QTest.mouseClick(block.all_button, Qt.LeftButton)
        self.assertInView(form, (block.all_ask, block.all_ask.no), "열릴 때")
        ui_offscreen.wait_until(self.app, lambda: False, 0.4)                                 # 늦게 맞추는 시계(160ms)까지 지나간 뒤 — 사용자가 그 사이에 스크롤하지는 않는다
        bar = form.scroll.verticalScrollBar()
        bar.setValue(0)                                                                       # 사용자가 위로 올려 읽는 중
        self.settle(4)
        form.refresh()
        block.apply(block.vm)                                                                 # 같은 뷰모델로 한 번 더 그린다 — 이미 열려 있는 확인 줄을 다시 그리는 길
        self.settle(8)
        ui_offscreen.wait_until(self.app, lambda: False, 0.5)                                 # 겹친 시계가 지나갈 때까지
        self.assertEqual(bar.value(), 0, "이미 열려 있는 확인 줄은 다시 그릴 때마다 스크롤을 끌어오지 않는다")
        block.all_ask.no.click()
        window.close_dialog()


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")           # 이 시험은 `theme` 모듈(PySide6 를 불러옴)을 쓴다 — 없는 CI 에서는 건너뛴다
class ThemeTest(unittest.TestCase):
    def test_the_two_line_states_differ_by_border_style_and_every_color_comes_from_the_tokens(self):
        colors = tokens.palette()
        qss = theme.build_qss(colors)
        rules = [line for line in qss.splitlines() if line.startswith("QFrame[ocrline")]
        self.assertEqual(len(rules), 4, rules)
        pending, done, current, focused = rules
        self.assertTrue(pending.startswith("QFrame[ocrline] ") and "1px dashed" in pending, "확인 전은 점선")
        self.assertTrue(done.startswith('QFrame[ocrline="done"]') and "1px solid" in done and "dashed" not in done, "확인함은 실선")
        self.assertIn('[current="true"]', current)
        self.assertTrue('[focused="true"]' in focused and f"{tokens.FOCUS_RING_PX}px solid {colors['border_focus']}" in focused, "포커스 테두리는 토큰의 포커스 색")
        for rule in rules:
            for fragment in re.findall(r"#[0-9a-fA-F]{3,8}", rule):
                self.assertIn(fragment, colors.values(), "스타일시트의 색은 모두 토큰에서 온다")
        self.assertNotEqual(pending.split("border:")[1].split(";")[0], done.split("border:")[1].split(";")[0])


# ---- 6-2) 화면 배율 125%·150% ---------------------------------------------------------------------------------------------------
@unittest.skipUnless(HAVE and os.name == "nt", "PySide6 와 윈도 글꼴이 있어야 한다(글자 잘림은 글꼴에 달렸다)")
class ScaleTest(unittest.TestCase):
    """배율은 프로세스가 시작될 때 `QT_SCALE_FACTOR` 환경 변수로 정해야 해서 자식 프로세스(`tests/photo_ocr_scale_probe.py`)를 배율마다 돌린다 — **실제 윈도 배율 설정이 아니라 Qt 자체의 High DPI 경로로 흉내 낸 것이다**
    (실제 윈도 125·150% 렌더·한글 입력기·화면 읽기 프로그램은 운영자 PC 에서 본다). 창의 논리 크기는 아래 일곱 크기 그대로다."""
    STATES = ["읽기 전", "읽는 중·오래 걸림", "읽은 글 24줄", "고치는 중", "이유가 보이는 줄", "모두 맞아요 확인 줄", "다시 읽기 확인 줄"]

    def probe(self, width, height, scale):
        environment = dict(os.environ, PYTHONUTF8="1")
        environment.pop("QT_SCALE_FACTOR", None)
        if scale != 1.0:
            environment["QT_SCALE_FACTOR"] = str(scale)
        done = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tests" / "photo_ocr_scale_probe.py"), str(width), str(height)], capture_output=True, text=True, encoding="utf-8", env=environment, timeout=300,
                              creationflags=0x08000000)
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        return json.loads(done.stdout.strip().splitlines()[-1])

    def check(self, width, height, scale):
        report = self.probe(width, height, scale)
        self.assertEqual(report["scale"], scale)
        minimum = tokens.LAYOUT["window_min"]                                              # 앱 창에는 가장 작은 크기(900x560)가 있어 그보다 낮은 논리 크기(910x512)는 그 크기로 열린다
        self.assertEqual(report["logical"], [max(width, minimum[0]), max(height, minimum[1])])
        self.assertEqual([item["label"] for item in report["reports"]], self.STATES)
        shown = {item["label"]: item["note"] for item in report["reports"]}
        self.assertEqual(shown["읽은 글 24줄"], T["pho_ocr_hidden"].format(m=3), (width, height, scale, "거른 줄 안내(가장 긴 안내 글 — 자식 프로세스가 거를 줄 셋을 함께 읽힌다)가 보이는 채로 잘림을 점검했다"))
        for item in report["reports"]:
            label = (width, height, scale, item["label"])
            self.assertTrue(item["inside"], label)
            self.assertEqual((item["hscroll"], item["list_hscroll"]), (0, 0), label)
            self.assertEqual(item["clipping"], [], label)
            self.assertEqual(item["squeezed"], [], label)
            self.assertTrue(item["buttons"], label)

    def test_every_one_of_the_seven_sizes_fits_at_150_percent_without_clipping_or_sideways_scrolling(self):
        for width, height in SIZES:
            with self.subTest(size=(width, height), scale=1.5):
                self.check(width, height, 1.5)

    def test_the_laptop_size_and_the_minimum_window_also_fit_at_125_percent_and_at_full_scale(self):
        for width, height, scale in ((1366, 768, 1.25), (900, 560, 1.25), (1366, 768, 1.0)):
            with self.subTest(size=(width, height), scale=scale):
                self.check(width, height, scale)


if __name__ == "__main__":
    unittest.main()
