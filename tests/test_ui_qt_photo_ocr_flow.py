"""사진 정리 창의 글자 읽기를 **진짜 어댑터**(`WorkerAdapter` — 진짜 프로세스)와 **가짜 작업자**(`tests/ocr_ui_worker.py`, 순수 파이썬)로 끝까지 돌려 보는 PySide6 시험 — 단추 → 진행자 → 작업 스레드 → 사진 읽기·줄이기(`ocr_input`) → 작업자 → 응답 검증 → 화면 스레드 → 줄 목록.
진짜 엔진·진짜 사진 속 글자는 없다(작업자가 지어낸 줄을 준다). **PySide6 가 없으면 통째로 건너뛴다.** 시험에서는 낮은 우선순위를 끈다(PC 가 바쁠 때 낮은 우선순위의 가짜 작업자가 굶어 시간 초과가 나는 것을 막는다 — 우선순위 자체는 이 시험이 보는 것이 아니다).

지키는 것:
  1) 상태 흐름 — 준비 중(작업자가 늦게 준비됨) → 읽는 중 → 완료. 두 번째 읽기는 준비 없이 바로 읽는 중이다(작업자는 한 번만 떴다).
  2) 취소·시간 초과·죽음·네트워크 시도 차단 보고 — 화면의 고정 문장과 상태·버튼, 프로세스가 정말 끝났는지, 연속 실패 3번이면 끄는지, 차단 보고는 한 번에 끄는지.
  3) 앱을 닫으면 작업자가 남지 않는다.
  4) 진짜 사진 한 장 — 작업자가 받은 바이트(가로·세로·픽셀·읽는 크기뿐)를 가로채 경로·파일 이름·사진 번호·메모·Exif 가 없음을 보고, 원본 파일·폴더는 그대로이다. 큰 PNG 는 작업자에 보내지도 않고 '사진이 너무 커서' 로 끝난다. 없어진 사진은 일반 실패다.
"""
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
import outgoing_support as og  # noqa: E402
import test_ui_qt_photo_ocr as to  # noqa: E402     (시험 도구만 이어 쓴다 — 그 모듈의 시험 클래스는 가져오지 않는다)
from capability_support import local_ocr_off, local_ocr_on  # noqa: E402

from chanceblog_desktop.ui import ocr_adapter as oadapter  # noqa: E402
from chanceblog_desktop.ui.core import photo_ocr_view as pov  # noqa: E402

HAVE = to.HAVE
T = to.T
WORKER = str(HERE / "ocr_ui_worker.py")
if HAVE:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from chanceblog_desktop.ui.ocr_provider import WorkerAdapter

LINES = ("한우 불고기 전골 28,000원", "된장찌개 9,000원")


def pid_alive(pid):
    done = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True)
    return str(pid).encode("ascii") in (done.stdout or b"")


def png_header_only(width, height):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    return bytes.fromhex("89504e470d0a1a0a") + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", bytes.fromhex("789c030000000001")) + chunk(b"IEND", b"")


@unittest.skipUnless(HAVE and os.name == "nt", "PySide6 와 윈도(프로세스 번호 확인)가 있어야 한다")
class FlowBase(to.OcrBase):
    def setUp(self):
        super().setUp()
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        patcher = mock.patch.object(oadapter, "BELOW_NORMAL", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pidfile = self.tmp / "worker.pid"
        self.dump = self.tmp / "request.bin"

    def adapter(self, *extra, mode="ok", **options):
        options.setdefault("prepare_timeout", 60)
        options.setdefault("read_timeout", 60)
        options.setdefault("verify", None)                                           # 확인 없음을 일부러 고른다(B1 어댑터는 verify 를 꼭 받는다)
        adapter = WorkerAdapter([sys.executable, "-B", WORKER, "--mode", mode, "--pidfile", str(self.pidfile), *extra], **options)
        adapter.priority_class = 0                                                   # 아주 바쁜 PC 에서 낮은 우선순위 작업자가 굶지 않게(없는 속성이면 쓰이지 않는다)
        self.addCleanup(adapter.shutdown)
        return adapter

    def pid(self):
        self.wait_for(lambda: self.pidfile.exists() and self.pidfile.read_text(encoding="utf-8").strip(), 20)
        return int(self.pidfile.read_text(encoding="utf-8").strip())

    def wait_dead(self, pid, seconds=15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if not pid_alive(pid):
                return True
            time.sleep(0.1)
        return False

    def states_seen(self, form, until, photo_id="p001", seconds=40):
        """`until` 상태가 될 때까지 화면 상태 이름의 바뀜을 차례로 모은다."""
        seen = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            vm = self.block(form, photo_id).vm
            state = vm["state"] if vm is not None else None
            if not seen or seen[-1] != state:
                seen.append(state)
            if state == until:
                return seen
            time.sleep(0.01)
        self.fail(f"{until} 가 되지 않았다: {seen}")


class StatesTest(FlowBase):
    def test_a_slow_start_walks_preparing_then_reading_then_done_and_the_second_read_needs_no_preparing(self):
        adapter = self.adapter("--ready-delay", "1.5", "--delay", "1.2", "--lines", "|".join(LINES))
        window, form = self.ocr_sheet(photos=1, provider=adapter)
        block = self.block(form)
        block.read_button.setFocus(Qt.TabFocusReason)
        block.read_button.click()
        self.assertEqual(block.vm["state"], "preparing", "작업자가 아직 준비되지 않았다")
        self.assertEqual(block.status.plain_text(), T["pho_ocr_preparing"])
        self.assertTrue(block.cancel_button.isVisibleTo(form))
        seen = self.states_seen(form, "done")
        self.assertEqual(seen, ["preparing", "reading", "done"], seen)
        self.assertEqual(self.row_texts(block), list(LINES))
        self.assertEqual((adapter.launches, window.state.ocr.worker_ready, window.state.ocr.failures), (1, True, 0))
        self.assertEqual(self.pid() > 0, True)
        block.read_button.click()
        self.settle(3)
        block.reread.yes.click()
        self.assertEqual(block.vm["state"], "reading", "이미 떠 있는 작업자는 준비 없이 바로 읽는 중이다")
        self.assertEqual(self.states_seen(form, "done")[-1], "done")
        self.assertEqual(adapter.launches, 1, "작업자는 한 번만 떴다")

    def test_the_worker_gets_a_request_with_only_size_and_pixels_and_the_screen_never_shows_a_path(self):
        adapter = self.adapter("--dump", str(self.dump), "--lines", "|".join(LINES))
        image = QImage(300, 200, QImage.Format_RGB32)
        image.fill(QColor(255, 0, 0))
        painter = QPainter(image)
        painter.fillRect(150, 0, 150, 200, QColor(0, 0, 255))
        painter.end()
        folder = self.tmp / "사진 폴더 UNIQ-DIR-m3k7"
        folder.mkdir()
        photo = folder / "메뉴판 UNIQ-NAME-t9r2.png"
        self.assertTrue(image.save(str(photo)))
        before = {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in folder.iterdir()}
        window, form = self.ocr_sheet(paths=[str(photo)], provider=adapter, size=(1600, 960))
        block = self.block(form)
        block.read_button.click()
        self.wait_state(form, "done")
        raw = self.dump.read_bytes()
        head, body = raw.split(b"\n", 1)
        message = json.loads(head)
        self.assertEqual(sorted(message), ["fmt", "h", "id", "n", "size", "t", "w"])
        self.assertEqual((message["t"], message["fmt"], message["w"], message["h"], message["n"], message["size"]), ("ocr", "rgb24", 300, 200, 300 * 200 * 3, "960"))
        self.assertEqual(len(body), 300 * 200 * 3)
        self.assertEqual((tuple(body[0:3]), tuple(body[-3:])), ((255, 0, 0), (0, 0, 255)), "RGB 순서 그대로 사진의 왼쪽 위는 빨강·오른쪽 아래는 파랑이다")
        for fragment in ("UNIQ", "사진".encode("utf-8"), b"Exif", b"EXIF", b"p001", b".png", b"Users", b"C:\\", b"Temp", "메뉴판".encode("utf-8")):
            self.assertNotIn(fragment if isinstance(fragment, bytes) else fragment.encode("ascii"), raw[:len(head) + 1], fragment)
        self.assertEqual(self.row_texts(block), list(LINES))
        self.assertEqual({item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in folder.iterdir()}, before, "원본과 폴더가 그대로다")
        shown = " ".join(self.shown_texts(form)) + " ".join(widget.accessibleName() for widget in form.findChildren(to.QWidget))
        self.assertNotIn("UNIQ-DIR-m3k7", shown, "폴더 이름이 어디에도 안 보인다")

    def test_a_big_png_is_never_sent_to_the_worker_and_ends_with_the_big_photo_sentence(self):
        adapter = self.adapter()
        big = self.tmp / "아주 큰 사진.png"
        big.write_bytes(png_header_only(7746, 7746))
        window, form = self.ocr_sheet(paths=[str(big)], provider=adapter)
        block = self.block(form)
        self.assertTrue(block.read_button.isVisibleTo(form), "큰 사진도 단추는 있다 — 눌러 보면 이유를 말한다")
        block.read_button.click()
        self.wait_state(form, "failed")
        self.assertEqual(block.status.plain_text(), T["pho_ocr_err_toobig"])
        self.assertEqual((adapter.launches, adapter.process, window.state.ocr.disabled_code, window.state.ocr.failures), (0, None, "", 0), "작업자는 뜨지도 않았고 사용자의 사진 문제는 실패로 세지 않는다")
        self.assertTrue(block.read_button.isVisibleTo(form))

    def test_a_photo_that_vanished_after_it_was_added_is_a_plain_failure_naming_nothing(self):
        adapter = self.adapter()
        image = QImage(40, 30, QImage.Format_RGB32)
        image.fill(QColor(10, 20, 30))
        photo = self.tmp / "곧 사라질 사진 UNIQ-GONE-w5q1.png"
        self.assertTrue(image.save(str(photo)))
        window, form = self.ocr_sheet(paths=[str(photo)], provider=adapter)
        photo.unlink()
        block = self.block(form)
        block.read_button.click()
        self.wait_state(form, "failed")
        self.assertEqual(block.status.plain_text(), T["pho_ocr_err_failed"])
        self.assertEqual((adapter.launches, window.state.ocr.failures), (0, 1))
        self.assertNotIn("UNIQ-GONE", block.status.plain_text() + block.status.accessibleName())


class StopsTest(FlowBase):
    def test_cancelling_a_read_ends_the_process_after_the_wait_and_the_screen_says_it_stopped(self):
        adapter = self.adapter("--delay", "30", cancel_wait=0.6)
        window, form = self.ocr_sheet(photos=1, provider=adapter, reader=lambda path, size: (16, 16, bytes(range(256)) * 3))
        block = self.block(form)
        block.read_button.click()
        self.wait_state(form, "reading")
        pid = self.pid()
        started = time.monotonic()
        block.cancel_button.click()
        self.settle(2)
        self.assertEqual((block.status.plain_text(), block.read_button.isVisibleTo(form)), (T["pho_ocr_cancelled"], True))
        self.wait_for(lambda: window.state.ocr.active is None, 20)
        self.assertLess(time.monotonic() - started, 15, "취소를 기다리는 시간은 짧다")
        self.assertTrue(self.wait_dead(pid), "작업자가 끝났다")
        self.assertEqual((adapter.process, window.state.ocr.worker_ready, self.row_texts(block)), (None, False, []))

    def test_a_read_that_takes_too_long_is_ended_and_says_so(self):
        adapter = self.adapter("--delay", "30", read_timeout=1.0)
        window, form = self.ocr_sheet(photos=1, provider=adapter, reader=lambda path, size: (16, 16, bytes(range(256)) * 3))
        block = self.block(form)
        block.read_button.click()
        self.wait_state(form, "failed")
        pid = self.pid()
        self.assertEqual(block.status.plain_text(), T["pho_ocr_err_timeout"])
        self.assertTrue(self.wait_dead(pid))
        self.assertEqual((adapter.process, window.state.ocr.worker_ready, window.state.ocr.failures), (None, False, 1))

    def test_a_worker_that_dies_fails_the_read_and_three_in_a_row_turn_the_tool_off(self):
        adapter = self.adapter(mode="die")
        window, form = self.ocr_sheet(photos=1, provider=adapter, reader=lambda path, size: (16, 16, bytes(range(256)) * 3))
        block = self.block(form)
        for number in range(3):
            self.assertTrue(block.read_button.isVisibleTo(form), number)
            block.read_button.click()
            self.wait_for(lambda: block.vm["state"] == "failed" and window.state.ocr.active is None, 60)
            self.settle(2)
        self.assertEqual((window.state.ocr.disabled_code, adapter.launches), ("OCR_UNAVAILABLE", 3))
        self.assertEqual(block.status.plain_text().split("\n"), [T["pho_ocr_err_failed"], T["pho_ocr_off_note"]])
        self.assertFalse(block.read_button.isVisibleTo(form))

    def test_a_network_attempt_report_turns_the_tool_off_at_once_with_the_unexpected_sentence(self):
        adapter = self.adapter(mode="net_blocked")
        window, form = self.ocr_sheet(photos=2, provider=adapter, reader=lambda path, size: (16, 16, bytes(range(256)) * 3))
        block = self.block(form)
        block.read_button.click()
        self.wait_state(form, "failed")
        self.assertEqual(block.status.plain_text(), T["pho_ocr_err_unexpected"])
        self.assertEqual(window.state.ocr.disabled_code, "OCR_UNEXPECTED")
        self.assertFalse(self.block(form, "p002").isVisibleTo(form), "끈 뒤에는 다른 사진에도 읽기 단추가 없다")
        self.assertFalse(form.ocr_intro.isVisibleTo(form))
        self.assertTrue(self.wait_dead(self.pid()))

    def test_closing_the_app_ends_the_worker_even_in_the_middle_of_a_read(self):
        adapter = self.adapter("--delay", "60")
        window, form = self.ocr_sheet(photos=1, provider=adapter, reader=lambda path, size: (16, 16, bytes(range(256)) * 3))
        self.block(form).read_button.click()
        self.wait_state(form, "reading")
        pid = self.pid()
        started = time.monotonic()
        window._close_confirmed = True                                                         # 저장하지 않은 사진 정보가 있어 닫기 확인이 먼저 뜬다 — 사용자가 '그래도 닫기' 를 눌렀다고 본다
        window.close()
        self.assertLess(time.monotonic() - started, 10, "닫는 데 오래 걸리지 않는다")
        self.assertTrue(self.wait_dead(pid, 20), "앱을 닫으면 작업자가 남지 않는다")

    def test_with_the_gate_off_the_same_adapter_never_starts_and_the_button_is_not_there(self):
        local_ocr_off()
        adapter = self.adapter()
        with og.Tripwire() as wire:
            window, form = self.ocr_sheet(photos=1, provider=adapter)
            self.assertFalse(self.block(form).isVisibleTo(form))
            self.settle(3)
        self.assertEqual((wire.calls, adapter.launches, self.pidfile.exists()), ([], 0, False))
        local_ocr_on()


if __name__ == "__main__":
    unittest.main()
