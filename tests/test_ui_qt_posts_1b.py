"""글 흐름 1b(결정 D-642 이후)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 복사용 패키지 카드·복사 단추·복사했어요·발행 주소 기록 대화·그래도 승인하기·발행 기록 화면·작업 로그 카드를 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_posts_1b_core`·`test_ui_posts_1b_adapter`). 사용자의 클립보드·데이터 폴더·설정 파일은 건드리지 않는다(가짜 공급자·가짜 클립보드·임시 폴더).
창은 시험 클래스마다 한 번만 만든다(`setUpClass`) — 시험 시간이 길어지지 않게(지시서: 모듈당 러너 기준 5분 안). 크기 여섯 시험만 창을 크기마다 새로 만든다.

지키는 것:
  1) 복사용 패키지 카드는 복사 준비됨·복사함·직접 발행함에서만 보이고 주요 단추는 하나다. **복사 단추는 클립보드에만 쓰고 상태를 바꾸지 않으며**(공급자를 부르지 않는다) 고른 블로그의 글만 복사한다. 키 모양이 든 부분은 복사 단추가 꺼진다.
  2) `복사했어요` 를 눌러야 복사함이 되고, `발행 주소 기록` 대화는 복사함에서만 열리며 잘못된 주소는 서비스를 부르지 않고 칸 옆에 이유가 보이고 칸의 글은 닫히면(취소·Esc·성공) 지워진다.
  3) 두 블로그 글이 많이 비슷해 막힐 때만 `그래도 승인하기` 가 켜지고 센 확인창(처음 포커스는 취소)을 거쳐야 하며 취소하면 아무것도 바뀌지 않는다.
  4) 발행 기록 화면은 읽기뿐이고(쓰는 단추 없음·공급자의 쓰기 길을 부르지 않음) 오래된 순서가 기본이며 여섯 상태·주소 복사·작업 로그 카드(접어 두었다가 펼칠 때 읽음, 키 모양은 가려짐)가 있다.
  5) 필수 창 크기 여섯에서 가로 스크롤이 없고 단추가 창 안에 있으며 모든 단추·칸이 접근 이름을 가진다. 사이드바는 메뉴 여덟이 들어가고 다음 단계 상자가 없다.
  6) 실제 서비스로 끝까지 돌려도 데이터 폴더 밖에 아무것도 생기지 않고 보기만 하는 동안은 한 바이트도 바뀌지 않는다.
"""
import hashlib
import importlib.util
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import service_support as support  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.ui import posts_adapter  # noqa: E402
from chanceblog_desktop.ui.core import app_state, post_fake, post_history, posts, services, text  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QPushButton, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module

T = text.T
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
KEY = support.KEY
A, B, PAGES = posts.NAVER_A, posts.NAVER_B, posts.PAGES
SIZES = ((1366, 768), (1093, 614), (1536, 864), (1280, 720), (1920, 1080), (900, 560))
GOOD_URL = "https://blog.naver.com/exampleaaa/223000000001"
STOP_SENTENCE = "이 영양제를 먹으면 통증이 완전히 사라집니다."
RAW_FIELDS = {"category": "생활", "image_url": "https://img.example.invalid/a.jpg"}
NL = chr(10)


def ready(provider, project_id, platform=A, ack=False):
    """검토를 시작하고 승인해 복사 준비됨으로 만든다(공급자의 길 — 화면을 거치지 않는다)."""
    provider.review_post(posts.ReviewRequest(project_id, platform, None), SAFE, NEVER)
    return provider.approve_post(posts.ApproveRequest(project_id, platform, 1, ack), SAFE, NEVER)


def ready_by_hand(provider, project_id, platform=A):
    """승인 검사를 거치지 않고 복사 준비됨으로 옮긴다 — 키 모양이 든 글도 이 상태에 둘 수 있다(가짜 공급자의 메모리만 바꾼다)."""
    project = provider.projects[project_id]
    project.set_rendered(platform, "손으로 만든 렌더링", now=provider._next_stamp())
    project.transition(platform, st.REVIEW_REQUIRED, now=provider._next_stamp())
    project.transition(platform, st.READY_TO_COPY, now=provider._next_stamp())


def copied(provider, project_id, platform=A, flag=True):
    return provider.mark_copied(posts.CopiedRequest(project_id, platform, flag), SAFE, NEVER)


def record(provider, project_id, platform=A, url=GOOD_URL):
    return provider.record_published(posts.RecordRequest(project_id, platform, url), SAFE, NEVER)


class Recording(post_fake.FakePostsProvider):
    """쓰기 요청을 적어 두는 가짜 공급자 — 화면이 서비스 쪽으로 무엇을 보냈는지 시험이 본다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests = []

    def approve_post(self, request, progress, cancelled):
        self.requests.append(("approve", request))
        return super().approve_post(request, progress, cancelled)

    def record_published(self, request, progress, cancelled):
        self.requests.append(("record", request))
        return super().record_published(request, progress, cancelled)

    def mark_copied(self, request, progress, cancelled):
        self.requests.append(("copied", request))
        return super().mark_copied(request, progress, cancelled)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()

    def setUp(self):
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda kind, value, trace: self.errors.append(f"{kind.__name__}: {value}")

    def tearDown(self):
        sys.excepthook = self._hook
        self.assertEqual(self.errors, [], "화면 슬롯 안에서 예외가 났다")

    def settle(self, times=6):
        ui_offscreen.settle(self.app, times)

    def wait_for(self, condition, seconds=10):
        self.assertTrue(ui_offscreen.wait_until(self.app, condition, seconds), f"{seconds}초 안에 기다린 상태가 되지 않았다")

    # ---- 창 만들기 — 클립보드는 늘 가짜다(이 PC 의 클립보드를 건드리지 않는다) ----
    @classmethod
    def open_window(cls, provider, size=(1366, 768), page="posts", wait=True):
        copies = []
        window = shell_module.AppShell(services.FakeHomeProvider(), posts=provider, clipboard=lambda value: (copies.append(value), True)[1], file_picker=lambda parent, title, filters: "", autoload=False)
        window.test_copies = copies
        window.resize(*size)
        window.show()
        ui_offscreen.settle(cls.app, 6)
        window.activateWindow()
        ui_offscreen.wait_until(cls.app, window.isActiveWindow, 2)
        if page != "home":
            window.go(page)
            controller = window.state.posts if page == "posts" else window.state.history
            if wait and not ui_offscreen.wait_until(cls.app, lambda: controller.state != "loading" and not controller.loading, 10):
                raise AssertionError("화면이 처음 읽기를 마치지 못했다")
            ui_offscreen.settle(cls.app, 6)
        return window

    @classmethod
    def shared(cls, provider, **kwargs):
        """클래스의 모든 시험이 함께 쓰는 창 — 클래스가 끝나면 닫는다."""
        window = cls.open_window(provider, **kwargs)
        cls.addClassCleanup(window.close)
        return window

    def make(self, provider, **kwargs):
        """이 시험만 쓰는 창 — 시험이 끝나면 닫는다."""
        window = self.open_window(provider, **kwargs)
        self.addCleanup(window.close)
        return window

    # ---- 찾기 ----
    def labels(self, root):
        return [label.plain_text() for label in root.findChildren(UI.Label)]

    def shown_labels(self, root):
        """눈에 보이는 글만 — 접어 둔 자세히·진단 정보 안의 글은 빠진다."""
        return [label.plain_text() for label in root.findChildren(UI.Label) if label.isVisibleTo(root)]

    def buttons(self, root):
        return {button.text(): button for button in root.findChildren(QAbstractButton)}

    def primary_buttons(self, window):
        return [button for button in window.screen_widget.findChildren(QPushButton) if button.property("kind") == "primary" and button.isVisibleTo(window)]

    def dialog_button(self, window, label):
        return {button.text(): button for button in window.dialog.findChildren(QAbstractButton)}[label]

    def wait_write(self, window):
        self.wait_for(lambda: not window.state.posts.busy and window.state.posts.pending is None)
        self.settle(8)

    def review_ui(self, window):
        return window.screen_widget.posts_ui.review

    def reopen(self, window, project_id):
        """목록을 다시 읽고 그 글의 상세를 연다(공급자가 바깥에서 바뀐 것을 화면이 읽는 길)."""
        window.post_close()
        self.settle(3)
        window.reload_posts()
        self.wait_for(lambda: not window.state.posts.loading and window.state.posts.row(project_id) is not None)
        window.post_open(project_id)
        self.wait_for(lambda: window.state.posts.detail_state == "normal" and window.state.posts.open_id == project_id)
        self.settle(8)

    def close_open_dialog(self, window):
        if window.dialog.is_open:
            window.close_dialog()
            self.settle(3)


class PostsQtPackageTest(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = Recording("empty")
        cls.window = cls.shared(cls.provider)

    def tearDown(self):
        self.close_open_dialog(self.window)
        super().tearDown()

    def fresh(self, prepare=None, markdown=None, title="복사할 글", platform=A):
        """새 글 하나를 공급자에 더하고(필요하면 준비하고) 목록을 다시 읽어 그 글을 연 뒤 고른 블로그를 보인다."""
        project_id = self.provider.add_post(title, markdown if markdown is not None else post_fake.sample_text())
        if prepare is not None:
            prepare(self.provider, project_id)
        self.reopen(self.window, project_id)
        self.window.post_platform(platform)
        self.settle(4)
        del self.window.test_copies[:]
        return project_id

    def show(self, project_id, platform=A):
        self.reopen(self.window, project_id)
        self.window.post_platform(platform)
        self.settle(4)

    def card(self):
        return self.review_ui(self.window).package

    def test_the_card_follows_the_status_nothing_then_ready_then_copied_then_published(self):
        project_id = self.fresh()
        self.assertIsNone(self.card(), "시작 전에는 카드가 없다")
        ready(self.provider, project_id)
        self.show(project_id)
        card = self.card()
        self.assertEqual((card.property("package_mode"), card.accessibleName()), ("ready", T["post_pkg_a11y"].format(name="네이버 A")))
        self.assertEqual(sorted(card.buttons), ["all", "body", "copied", "tags", "title"])
        self.assertEqual(card.buttons["title"].accessibleName(), T["post_pkg_copy_title_a11y"].format(name="네이버 A"))
        self.assertIn(T["post_pkg_sub"], self.labels(card))
        copied(self.provider, project_id)
        self.show(project_id)
        self.assertEqual((self.card().property("package_mode"), sorted(self.card().buttons)), ("copied", ["all", "body", "record", "tags", "title", "uncopy"]))
        record(self.provider, project_id)
        self.show(project_id)
        self.assertEqual((self.card().property("package_mode"), sorted(self.card().buttons)), ("published", ["url"]))
        self.assertIn(T["post_published_url"].format(url=GOOD_URL), self.labels(self.card()))

    def test_the_detail_page_has_exactly_one_primary_button_in_each_package_state(self):
        project_id = self.fresh(lambda provider, pid: ready(provider, pid))
        self.assertEqual([button.text() for button in self.primary_buttons(self.window)], [T["post_copied"]])
        copied(self.provider, project_id)
        self.show(project_id)
        self.assertEqual([button.text() for button in self.primary_buttons(self.window)], [T["post_record"]])

    def test_a_copy_button_writes_only_to_the_clipboard_and_changes_nothing_else(self):
        project_id = self.fresh(lambda provider, pid: ready(provider, pid))
        package = self.window.state.posts.package()
        calls_before = list(self.provider.calls)
        for kind, expected in (("title", package.title), ("body", package.body), ("tags", package.tags), ("all", package.copy_text)):
            with self.subTest(kind=kind):
                del self.window.test_copies[:]
                self.card().buttons[kind].click()
                self.settle(3)
                self.assertEqual(self.window.test_copies, [expected])
        self.assertEqual(self.provider.calls, calls_before, "복사는 공급자를 부르지 않는다")
        self.assertEqual(self.window.state.posts.detail.platform(A).status, st.READY_TO_COPY, "복사 단추를 눌러도 복사함이 되지 않는다")
        self.assertEqual(self.provider.projects[project_id].variants[A].status, st.READY_TO_COPY)
        self.assertEqual([item for item in self.provider.requests if item[0] == "copied" and item[1].project_id == project_id], [])

    def test_the_button_copies_the_chosen_blogs_package_and_never_the_other_ones(self):
        def both(provider, pid):
            ready(provider, pid, A)
            ready(provider, pid, B, ack=True)

        project_id = self.fresh(both)
        self.assertEqual(self.card().accessibleName(), T["post_pkg_a11y"].format(name="네이버 A"))
        self.card().buttons["tags"].click()
        self.settle(3)
        self.window.post_platform(B)
        self.settle(4)
        self.assertEqual(self.card().accessibleName(), T["post_pkg_a11y"].format(name="네이버 B"))
        self.card().buttons["tags"].click()
        self.settle(3)
        self.assertEqual(self.window.test_copies, ["#예시 #에이", "#예시 #비"])
        self.assertEqual({key: self.provider.projects[project_id].variants[key].status for key in (A, B)}, {A: st.READY_TO_COPY, B: st.READY_TO_COPY}, "복사해도 두 블로그 상태는 그대로다")

    def test_a_copied_a_does_not_change_b_and_the_two_cards_stay_independent(self):
        def both(provider, pid):
            ready(provider, pid, A)
            ready(provider, pid, B, ack=True)

        project_id = self.fresh(both)
        self.card().buttons["copied"].click()
        self.wait_write(self.window)
        self.assertEqual({key: self.provider.projects[project_id].variants[key].status for key in (A, B)}, {A: st.COPY_COMPLETED, B: st.READY_TO_COPY})
        self.window.post_platform(B)
        self.settle(4)
        self.assertEqual((self.card().property("package_mode"), sorted(self.card().buttons)), ("ready", ["all", "body", "copied", "tags", "title"]), "B 는 아직 복사 준비됨이다")
        self.window.post_platform(A)
        self.settle(4)
        self.assertEqual(self.card().property("package_mode"), "copied")

    def test_a_key_shaped_package_part_is_not_copied_and_its_button_is_off(self):
        project_id = self.fresh(ready_by_hand, markdown="## 소제목" + NL + NL + "본문 줄 " + KEY + " 이어지는 글입니다.", title="일반 제목")
        self.assertIn(KEY, self.provider.projects[project_id].source_content)
        card = self.card()
        self.assertEqual(card.property("package_mode"), "ready")
        self.assertEqual({kind: card.buttons[kind].isEnabled() for kind in ("title", "body", "tags", "all")}, {"title": True, "body": False, "tags": True, "all": False})
        self.assertIn(T["post_pkg_copy_blocked"], self.labels(card))
        card.buttons["body"].click()                                                           # 꺼진 단추라 눌려도 아무 일이 없다
        self.settle(3)
        self.assertEqual(self.window.test_copies, [])
        self.assertFalse(self.window.post_copy("all"), "단추를 거치지 않고 불러도 키 모양이 든 글은 복사하지 않는다")
        self.assertEqual(self.window.test_copies, [])
        everything = self.labels(self.window.screen_widget) + [widget.accessibleName() for widget in self.window.screen_widget.findChildren(QWidget)]
        for piece in (KEY, KEY[:10], KEY[-10:]):
            self.assertFalse([item for item in everything if piece in item], "화면의 어느 글에도 키 글이 없다")

    def test_pressing_copied_marks_the_post_and_uncopy_goes_back_one_step(self):
        project_id = self.fresh(lambda provider, pid: ready(provider, pid))
        self.card().buttons["copied"].click()
        self.wait_write(self.window)
        self.assertEqual(self.window.state.posts.detail.platform(A).status, st.COPY_COMPLETED)
        self.assertEqual([(name, request.copied) for name, request in self.provider.requests if name == "copied"][-1], ("copied", True))
        self.assertEqual(self.window.state.posts.notice, ("ok", T["post_done_copied"]))
        self.assertEqual(sorted(self.card().buttons), ["all", "body", "record", "tags", "title", "uncopy"])
        self.assertNotIn("copied", self.card().buttons, "복사함에는 복사했어요 단추가 없다")
        self.card().buttons["uncopy"].click()
        self.wait_write(self.window)
        self.assertEqual(self.window.state.posts.detail.platform(A).status, st.READY_TO_COPY)
        self.assertEqual([(name, request.copied) for name, request in self.provider.requests if name == "copied"][-1], ("copied", False))
        self.assertEqual(self.window.state.posts.notice, ("ok", T["post_done_uncopied"]))
        self.assertEqual(self.window.state.posts.open_id, project_id)

    def test_keyboard_alone_presses_copied_and_the_focus_goes_to_the_next_action(self):
        self.fresh(lambda provider, pid: ready(provider, pid))
        self.window.activateWindow()
        self.settle(3)
        button = self.card().buttons["copied"]
        button.setFocus(Qt.TabFocusReason)
        self.settle(3)
        QTest.keyClick(button, Qt.Key_Space)
        self.wait_write(self.window)
        self.assertEqual(self.window.state.posts.detail.platform(A).status, st.COPY_COMPLETED)
        focused = QApplication.focusWidget()
        self.assertIsNotNone(focused)
        self.assertEqual(focused.property("focus_key"), "post:record", "누른 단추가 사라진 자리에서 다음에 할 일(발행 주소 기록)로 포커스가 간다")

    def test_a_published_post_shows_the_address_and_copies_it_with_one_button(self):
        self.fresh(lambda provider, pid: (ready(provider, pid), copied(provider, pid), record(provider, pid)))
        self.assertEqual(self.card().property("package_mode"), "published")
        self.card().buttons["url"].click()
        self.settle(3)
        self.assertEqual(self.window.test_copies, [GOOD_URL])
        self.assertEqual(self.primary_buttons(self.window), [], "직접 발행함에는 주요 단추가 없다")
        self.assertIn(T["post_review_after_done"], self.labels(self.window.screen_widget))

    def test_a_health_claim_in_the_pages_one_line_description_blocks_and_only_the_place_is_shown(self):
        project_id = self.fresh(platform=PAGES)
        self.buttons(self.window.screen_widget)[T["post_review_start"]].click()
        self.settle()
        form = self.window.post_pages_form
        self.assertIsNotNone(form)
        for name, value in {**RAW_FIELDS, "description": STOP_SENTENCE}.items():
            form.inputs[name].setText(value)
        form.start_button.click()
        self.wait_write(self.window)
        review = self.review_ui(self.window)
        by = {frame.property("post_part"): frame for frame in review.findChildren(QWidget) if str(frame.property("post_part")).startswith("section:")}
        self.assertEqual(by["section:health"].badge.text(), T["post_badge_block"])
        self.assertTrue([line for line in self.labels(by["section:health"]) if T["post_where_description"] in line], "걸린 곳이 어느 칸(한 줄 설명)인지 보인다")
        self.assertEqual(by["section:secret"].badge.text(), T["post_badge_pass"], "막힌 것은 건강 효과 단정 하나뿐이다")
        self.assertFalse(review.buttons["approve"].isEnabled())
        self.assertIn(T["post_approve_why_blocked"], self.labels(review))
        self.assertEqual(self.provider.projects[project_id].variants[PAGES].status, st.REVIEW_REQUIRED)

    # ---- 발행 주소 기록 대화 ----
    def copied_post(self):
        project_id = self.fresh(lambda provider, pid: (ready(provider, pid), copied(provider, pid)))
        self.card().buttons["record"].click()
        self.settle(4)
        self.assertTrue(self.window.dialog.is_open)
        return project_id, self.window.post_record_form

    def test_the_record_dialog_opens_only_from_copied_and_starts_empty_with_the_start_button_off(self):
        self.fresh(lambda provider, pid: ready(provider, pid))
        self.assertIsNone(self.window.post_record(), "복사 준비됨에서는 열리지 않는다")
        self.assertFalse(self.window.dialog.is_open)
        self.close_open_dialog(self.window)
        project_id, form = self.copied_post()
        self.assertEqual(self.window.dialog.accessibleName(), T["post_rec_title"])
        self.assertEqual((form.input.text(), form.input.accessibleName(), form.start_button.isEnabled(), form.cancel_button.isEnabled()), ("", T["post_rec_a11y"], False, True))
        self.assertEqual(self.provider.calls[-1], "load_post", "대화를 열기만 해서는 서비스를 부르지 않는다")
        self.assertEqual(QApplication.focusWidget(), form.input)
        self.assertEqual(self.provider.projects[project_id].variants[A].status, st.COPY_COMPLETED)

    def test_a_bad_address_is_stopped_on_the_screen_with_the_reason_and_a_good_one_is_recorded(self):
        project_id, form = self.copied_post()
        before = len([item for item in self.provider.requests if item[0] == "record"])
        form.input.setText("http://blog.naver.com/x/1")
        self.assertTrue(form.start_button.isEnabled())
        form.start_button.click()
        self.settle(4)
        self.assertTrue(form.problem.isVisible())
        self.assertEqual(form.problem.plain_text(), T["post_rec_p_scheme"])
        self.assertEqual(len([item for item in self.provider.requests if item[0] == "record"]), before, "걸린 주소는 서비스를 부르지 않는다")
        self.assertEqual(form.input.text(), "http://blog.naver.com/x/1", "칸의 글은 그대로다")
        form.input.setText(f"https://blog.naver.com/x/{KEY}")
        form.start_button.click()
        self.settle(4)
        self.assertEqual(form.problem.plain_text(), T["post_rec_p_secret"])
        self.assertFalse([item for item in self.labels(self.window.dialog) if KEY[:10] in item], "키 모양 주소는 이유 문장에도 되풀이하지 않는다")
        self.assertEqual(len([item for item in self.provider.requests if item[0] == "record"]), before)
        form.input.setText(GOOD_URL)
        form.start_button.click()
        self.wait_write(self.window)
        self.assertIsNone(self.window.post_record_form)
        self.assertFalse(self.window.dialog.is_open)
        self.assertEqual(self.window.state.posts.detail.platform(A).status, st.PUBLISHED_MANUAL)
        self.assertEqual(self.provider.requests[-1][1].url, GOOD_URL)
        self.assertIn(T["post_published_url"].format(url=GOOD_URL), self.labels(self.card()))
        self.assertEqual(self.window.state.posts.notice, ("ok", T["post_done_recorded"]))
        self.assertEqual(form.input.text(), "", "성공해서 닫혀도 칸은 비워진다")
        self.assertEqual(self.window.state.posts.open_id, project_id)

    def test_korean_text_from_the_input_method_turns_the_start_button_on_and_the_dialog_is_not_redrawn_while_typing(self):
        project_id, form = self.copied_post()
        form.input.setText("https://blog.naver.com/exampleaaa/")
        form.input.setFocus(Qt.OtherFocusReason)
        event = QInputMethodEvent()
        event.setCommitString("글번호")
        QApplication.sendEvent(form.input, event)
        self.settle(2)
        self.assertEqual(form.input.text(), "https://blog.naver.com/exampleaaa/글번호")
        self.assertTrue(form.start_button.isEnabled())
        self.assertIs(self.window.post_record_form, form, "입력하는 동안 대화를 다시 그리지 않는다(입력기 조합이 끊기지 않는다)")
        form.start_button.click()
        self.wait_write(self.window)
        self.assertEqual(self.window.state.posts.detail.platform(A).status, st.PUBLISHED_MANUAL)
        self.assertIn(T["post_published_url"].format(url="https://blog.naver.com/exampleaaa/글번호"), self.labels(self.card()))
        self.assertEqual(self.window.state.posts.open_id, project_id)

    def test_a_refusal_from_the_service_keeps_the_dialog_open_with_one_easy_sentence_and_the_address_in_the_field(self):
        project_id, form = self.copied_post()
        self.provider.fail["record_published"] = posts.PostFailure(T["post_fail_address"], code="NAVER_PUBLISH_URL_INVALID", kind="address")
        self.addCleanup(self.provider.fail.pop, "record_published", None)
        form.input.setText(GOOD_URL)
        form.start_button.click()
        self.wait_write(self.window)
        self.assertTrue(self.window.dialog.is_open)
        self.assertIs(self.window.post_record_form, form)
        self.assertEqual(form.message.plain_text(), T["post_fail_address"])
        self.assertEqual(form.input.text(), GOOD_URL, "칸의 글은 그대로다(고칠 수 있게)")
        self.assertEqual(self.provider.projects[project_id].variants[A].status, st.COPY_COMPLETED)
        self.provider.fail.pop("record_published", None)
        form.start_button.click()
        self.wait_write(self.window)
        self.assertEqual(self.window.state.posts.detail.platform(A).status, st.PUBLISHED_MANUAL, "고치지 않고 다시 눌러도 이제 기록된다")

    def test_closing_the_record_dialog_by_cancel_or_escape_wipes_the_field_and_the_next_one_starts_empty(self):
        self.fresh(lambda provider, pid: (ready(provider, pid), copied(provider, pid)))
        for how in ("cancel", "escape"):
            with self.subTest(how=how):
                self.card().buttons["record"].click()
                self.settle(4)
                form = self.window.post_record_form
                form.input.setText("https://blog.naver.com/x/1")
                if how == "cancel":
                    form.cancel_button.click()
                else:
                    self.window.escape()
                self.settle(4)
                self.assertFalse(self.window.dialog.is_open)
                self.assertIsNone(self.window.post_record_form)
                self.assertEqual(form.input.text(), "", "닫히면 칸을 비운다")
                self.assertFalse(self.window.state.posts.record_open)
        self.card().buttons["record"].click()
        self.settle(4)
        self.assertEqual(self.window.post_record_form.input.text(), "")

    def test_after_the_record_dialog_closes_no_address_text_is_left_in_the_controller(self):
        self.fresh(lambda provider, pid: (ready(provider, pid), copied(provider, pid)))
        self.card().buttons["record"].click()
        self.settle(4)
        self.window.post_record_form.input.setText("https://blog.naver.com/zzz/987654321")
        self.window.post_record_start()
        self.settle(2)
        self.window.post_record_cancel()
        self.settle(4)
        self.assertNotIn("987654321", repr(vars(self.window.state.posts)))
        self.assertEqual((self.window.state.posts.record_problem, self.window.state.posts.record_message), ("", ""))

    def test_tab_stays_inside_the_record_dialog_and_the_screen_behind_it_has_no_tab_stop(self):
        self.fresh(lambda provider, pid: (ready(provider, pid), copied(provider, pid)))
        self.window.activateWindow()
        self.settle(3)
        self.card().buttons["record"].click()
        self.settle(4)
        form = self.window.post_record_form
        outside = [widget for widget in self.window.screen_widget.findChildren(QWidget) if widget.focusPolicy() != Qt.NoFocus]
        self.assertEqual(outside, [], "대화가 열려 있는 동안 화면 쪽에는 Tab 정거장이 없다")
        seen = set()
        for _ in range(10):
            QTest.keyClick(QApplication.focusWidget() or form.input, Qt.Key_Tab)
            self.settle(1)
            widget = QApplication.focusWidget()
            if widget is not None:
                seen.add(widget)
        self.assertTrue(all(form.isAncestorOf(widget) or widget is form for widget in seen), "포커스가 대화 밖으로 나가지 않는다")

    def test_every_button_and_input_of_the_package_card_and_the_record_dialog_has_an_accessible_name(self):
        self.fresh(lambda provider, pid: (ready(provider, pid), copied(provider, pid)))
        for button in self.card().findChildren(QAbstractButton):
            if button.isVisibleTo(self.window):
                self.assertTrue(button.accessibleName() or button.text(), f"접근 이름이 없다: {button.property('focus_key')}")
                self.assertGreaterEqual(button.height(), 34, button.text())
        self.card().buttons["record"].click()
        self.settle(4)
        form = self.window.post_record_form
        for widget in form.findChildren(QWidget):
            if isinstance(widget, QAbstractButton) or type(widget).__name__ == "QLineEdit":
                if widget.isVisibleTo(form):
                    self.assertTrue(widget.accessibleName() or widget.text(), type(widget).__name__)
        self.assertTrue(form.start_button.accessibleName() and form.cancel_button.accessibleName())


class PostsQtSimilarityAckTest(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = Recording("empty")
        cls.window = cls.shared(cls.provider)

    def tearDown(self):
        self.close_open_dialog(self.window)
        super().tearDown()

    def fresh(self):
        """A 는 이미 복사 준비됨이고 같은 글로 B 를 화면에서 검토해 '많이 비슷함' 으로 막힌 모습."""
        provider, window = self.provider, self.window
        project_id = provider.add_post("비슷한 글", post_fake.sample_text())
        ready(provider, project_id, A)
        self.reopen(window, project_id)
        window.post_platform(B)
        self.settle(4)
        window.post_review(B)
        self.wait_write(window)
        return project_id

    def buttons_of_review(self):
        return self.review_ui(self.window).buttons

    def test_only_the_similarity_blocks_so_the_normal_approve_is_off_and_the_strong_one_is_on(self):
        self.fresh()
        buttons = self.buttons_of_review()
        self.assertFalse(buttons["approve"].isEnabled())
        self.assertTrue(buttons["approve_similarity"].isEnabled())
        self.assertEqual(buttons["approve_similarity"].text(), T["post_sim_button"])
        self.assertEqual(buttons["approve_similarity"].accessibleName(), T["post_sim_button_a11y"].format(name="네이버 B"))
        self.assertIn(T["post_sim_note"], self.labels(self.review_ui(self.window)))
        self.assertEqual([button.text() for button in self.primary_buttons(self.window)], [T["post_review_again"]], "주요 단추는 하나다 — 그래도 승인하기는 보조 단추다")

    def test_the_strong_dialog_starts_with_cancel_focused_and_cancelling_changes_nothing(self):
        project_id = self.fresh()
        before = len([item for item in self.provider.requests if item[0] == "approve"])
        self.buttons_of_review()["approve_similarity"].click()
        self.settle(4)
        self.assertTrue(self.window.dialog.is_open)
        self.assertEqual(self.window.dialog.accessibleName(), T["post_sim_title"])
        self.assertIn("100%", self.window.dialog.findChild(UI.DialogBody).plain_text())
        cancel, ok = self.dialog_button(self.window, T["post_sim_cancel"]), self.dialog_button(self.window, T["post_sim_ok"])
        self.assertIs(self.window.dialog_default, cancel, "처음 포커스는 취소다")
        self.assertEqual(ok.property("kind"), "primary")
        self.assertEqual(self.window.state.posts.approve_asked[-1], "similarity")
        cancel.click()
        self.settle(4)
        self.assertFalse(self.window.dialog.is_open)
        self.assertIsNone(self.window.state.posts.approve_asked, "취소하면 확인했다는 표시도 거둔다")
        self.assertEqual(len([item for item in self.provider.requests if item[0] == "approve"]), before)
        self.assertEqual(self.provider.projects[project_id].variants[B].status, st.REVIEW_REQUIRED)

    def test_confirming_the_strong_dialog_approves_with_the_acknowledgement_and_only_then(self):
        project_id = self.fresh()
        self.buttons_of_review()["approve_similarity"].click()
        self.settle(4)
        self.dialog_button(self.window, T["post_sim_ok"]).click()
        self.wait_write(self.window)
        name, request = self.provider.requests[-1]
        self.assertEqual((name, request.similarity_ack), ("approve", True))
        self.assertEqual(self.provider.projects[project_id].variants[B].status, st.READY_TO_COPY)
        self.assertEqual(self.window.state.posts.notice, ("ok", T["post_done_approved_similarity"]))

    def test_escape_closes_the_strong_dialog_like_cancel(self):
        project_id = self.fresh()
        self.buttons_of_review()["approve_similarity"].click()
        self.settle(4)
        self.window.escape()
        self.settle(4)
        self.assertFalse(self.window.dialog.is_open)
        self.assertIsNone(self.window.state.posts.approve_asked)
        self.assertEqual(self.provider.projects[project_id].variants[B].status, st.REVIEW_REQUIRED)

    def test_the_normal_approve_confirm_alone_cannot_carry_the_acknowledgement(self):
        self.fresh()
        before = len(self.provider.requests)
        status, _detail = self.window.state.posts.start_approve(**self.window.posts_write_bridge.callbacks())
        self.assertEqual(status, "refused", "유사도로 막힌 글은 일반 승인으로는 시작하지 않는다")
        self.settle(4)
        self.assertEqual(self.provider.requests[before:], [], "공급자에게 어떤 승인 요청도 가지 않았다")


class PostsQtHistoryTest(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = Recording("normal")
        cls.window = cls.shared(cls.provider, page="history")

    def open_screen(self):
        """처음 모습으로 — 오래된 순서로 두고 목록을 다시 읽는다."""
        window = self.window
        window.state.history.set_order("oldest")
        window.reload_history()
        self.wait_for(lambda: window.state.history.state != "loading" and not window.state.history.loading)
        self.settle(6)
        return window.screen_widget.history_ui

    def test_the_menu_is_after_posts_in_the_core_group_and_opens_the_screen_without_a_next_steps_box(self):
        window = self.window
        self.assertEqual(list(window.nav_buttons), ["home", "topics", "drafts", "posts", "history", "seed", "blogs", "settings"])
        self.assertEqual(window.nav_buttons["history"].accessibleName(), "발행 기록 메뉴로 이동")
        self.assertEqual((window.state.page, window.nav_buttons["history"].isChecked(), window.nav_buttons["posts"].isChecked()), ("history", True, False))
        self.assertEqual(list(S.SCREEN_BUILDERS), [key for key, _label, _icon in app_state.NAV])
        self.assertEqual(list(window.sidebar.group_titles), ["core", "data", "system"])
        self.assertIsNone(window.sidebar.soon_list)
        self.assertIn(T["hist_title"], self.labels(window.screen_widget))
        self.assertIn(T["hist_sub"], self.labels(window.screen_widget))

    def test_the_rows_are_oldest_first_and_a_row_says_platform_state_and_time(self):
        ui = self.open_screen()
        self.assertEqual(list(ui.rows), ["exh00001:naver_a", "exh00002:naver_b", "exh00003:github_pages"])
        texts = self.labels(ui.rows["exh00001:naver_a"])
        self.assertIn(T["hist_row_meta"].format(platform="네이버 A", status="직접 발행함", when="2026-10-21 12:20"), texts)
        self.assertIn(T["hist_row_url"].format(url="https://blog.naver.com/exampleid/100000000001"), texts)
        self.assertIn(T["hist_row_meta"].format(platform="네이버 B", status="복사 준비됨", when="2026-11-10 15:40"), self.labels(ui.rows["exh00002:naver_b"]))
        self.assertEqual(ui.order_button.text(), T["hist_order_to_newest"])
        self.assertIn(T["hist_count"].format(n=3), self.labels(ui.list_card))

    def test_the_order_button_flips_the_list_both_ways_and_keeps_the_focus_on_itself(self):
        ui = self.open_screen()
        calls = list(self.provider.calls)
        ui.order_button.setFocus(Qt.TabFocusReason)
        ui.order_button.click()
        self.settle(6)
        ui = self.window.screen_widget.history_ui
        self.assertEqual(list(ui.rows), ["exh00003:github_pages", "exh00002:naver_b", "exh00001:naver_a"])
        self.assertEqual(ui.order_button.text(), T["hist_order_to_oldest"])
        self.assertEqual(self.provider.calls, calls, "순서를 바꿔도 다시 읽지 않는다")
        self.assertEqual(QApplication.focusWidget(), ui.order_button)
        ui.order_button.click()
        self.settle(6)
        self.assertEqual(list(self.window.screen_widget.history_ui.rows)[0], "exh00001:naver_a")

    def test_the_copy_button_copies_the_address_only_for_a_row_that_has_one(self):
        ui = self.open_screen()
        del self.window.test_copies[:]
        self.assertEqual(sorted(ui.copy_buttons), ["exh00001:naver_a"])
        self.assertEqual(ui.copy_buttons["exh00001:naver_a"].accessibleName(), T["hist_copy_url_a11y"].format(title="예시 — 겨울 난방비 줄이는 방법"))
        ui.copy_buttons["exh00001:naver_a"].click()
        self.settle(3)
        self.assertEqual(self.window.test_copies, ["https://blog.naver.com/exampleid/100000000001"])

    def test_the_screen_is_read_only_no_write_button_and_no_write_call(self):
        ui = self.open_screen()
        ui.order_button.click()
        self.settle(4)
        writes = {"import_post", "review_post", "approve_post", "revoke_post", "mark_copied", "record_published"}
        self.assertEqual(writes & set(self.provider.calls), set())
        names = [button.text() for button in self.window.screen_widget.findChildren(QAbstractButton) if button.isVisibleTo(self.window)]
        for word in ("승인", "기록하기", "지우기", "삭제", "저장", "올리기", "발행하기", "고치기"):
            self.assertFalse([name for name in names if word in name], f"쓰는 단추가 보인다: {word}")
        self.assertEqual(self.primary_buttons(self.window), [], "읽기 전용이라 주요 단추가 없다")
        self.assertEqual([item for item in self.provider.requests if item[0] in ("approve", "record", "copied")], [], "읽기 화면은 쓰기 요청을 만들지 않는다")

    def test_every_button_of_the_history_screen_has_an_accessible_name_and_a_big_enough_target(self):
        self.open_screen()
        for button in self.window.screen_widget.findChildren(QAbstractButton):
            if button.isVisibleTo(self.window):
                self.assertTrue(button.accessibleName() or button.text(), f"접근 이름이 없다: {button.property('focus_key')}")
                self.assertGreaterEqual(button.height(), 34, button.text() or button.accessibleName())

    def test_the_sample_badge_explains_that_the_rows_are_examples(self):
        self.open_screen()
        badges = [widget for widget in self.window.screen_widget.findChildren(QWidget) if widget.accessibleName() == T["sample_tag"]]
        self.assertTrue(badges)
        self.window.show_sample_info("history")
        self.settle()
        self.assertIn(T["hist_sample_dialog_body"], self.window.dialog.findChild(UI.DialogBody).plain_text())
        self.close_open_dialog(self.window)


class PostsQtWorkLogTest(Base):
    def test_the_log_card_is_closed_then_reads_when_opened_and_shows_the_newest_line_first(self):
        provider = Recording("normal")
        window = self.make(provider, page="history")
        ui = window.screen_widget.history_ui
        self.assertEqual(ui.log_card.property("log_state"), "closed")
        self.assertEqual(ui.log_toggle.text(), T["hist_log_show"])
        self.assertNotIn("load_work_log", provider.calls, "접혀 있는 동안은 읽지 않는다")
        ui.log_toggle.click()
        self.wait_for(lambda: window.state.history.log_state == "normal")
        self.settle(6)
        ui = window.screen_widget.history_ui
        names = ("QtCriticalMsg", "ValueError", "KeyError")
        lines = [item for item in self.shown_labels(ui.log_card) if any(name in item for name in names)]
        self.assertEqual(len(lines), 3)
        self.assertIn("QtCriticalMsg", lines[0], "최신 줄이 위에 있다")
        self.assertIn("KeyError", lines[2])
        self.assertIn(T["hist_log_count"].format(n=3), self.shown_labels(ui.log_card))
        self.assertEqual((ui.log_toggle.text(), ui.log_card.property("log_state")), (T["hist_log_hide"], "normal"))
        self.assertEqual(provider.calls.count("load_work_log"), 1)
        names_of_buttons = [button.text() for button in ui.log_card.findChildren(QAbstractButton)]
        for word in ("지우기", "내보내기", "복사", "저장", "삭제"):
            self.assertFalse([name for name in names_of_buttons if word in name], f"작업 로그 카드에 쓰는 단추가 있다: {word}")
        ui.log_toggle.click()
        self.settle(6)
        self.assertEqual(window.screen_widget.history_ui.log_card.property("log_state"), "closed")
        window.screen_widget.history_ui.log_toggle.click()
        self.settle(6)
        self.assertEqual(provider.calls.count("load_work_log"), 1, "다시 펼쳐도 이미 읽은 로그는 다시 읽지 않는다")

    def test_a_log_that_cannot_be_read_says_so_in_an_easy_sentence_and_a_retry_works(self):
        provider = Recording("normal", fail={"load_work_log": posts.PostFailure(T["post_fail_corrupt"], code="LOG_UNREADABLE", kind="corrupt")})
        window = self.make(provider, page="history")
        window.screen_widget.history_ui.log_toggle.click()
        self.wait_for(lambda: window.state.history.log_state == "error")
        self.settle(6)
        ui = window.screen_widget.history_ui
        self.assertIn(T["hist_log_error"], self.shown_labels(ui.log_card))
        self.assertFalse([item for item in self.shown_labels(ui.log_card) if "LOG_UNREADABLE" in item], "코드는 접힌 진단 정보에만 있다")
        self.assertTrue([item for item in self.labels(ui.log_card) if "LOG_UNREADABLE" in item])
        self.assertEqual(len(window.screen_widget.history_ui.rows), 3, "작업 로그를 못 읽어도 목록은 그대로다")
        provider.fail.pop("load_work_log")
        ui.log_retry.click()
        self.wait_for(lambda: window.state.history.log_state == "normal")
        self.settle(6)
        self.assertEqual(window.screen_widget.history_ui.log_card.property("log_state"), "normal")

    def test_a_key_shaped_log_line_never_reaches_a_label_and_a_key_shaped_address_cannot_be_copied(self):
        class Odd(Recording):
            def load_history(self, progress, cancelled):
                rows = (post_history.HistoryEntry("odd1", "새 상태 글", "github_pages", "MERGE_PENDING", 1, "2026-11-02T00:00:00Z"),
                        post_history.HistoryEntry("odd2", "주소 글", "naver_a", st.PUBLISHED_MANUAL, 1, "2026-11-03T00:00:00Z", f"https://blog.naver.com/x/1?token={KEY}", "2026-11-04T00:00:00Z"),
                        post_history.HistoryEntry("odd3", "제목 " + KEY, "naver_b", st.COPY_COMPLETED, 1, "2026-11-05T00:00:00Z"))
                return post_history.HistoryData(rows, 0, "ok", True, False)

            def load_work_log(self, progress, cancelled):
                return post_history.WorkLogData((post_history.LogEntry("2026-11-24T05:30:12Z", "slot", KEY, ("shell.py:2",)),), 1, 0, 0, True)

        window = self.make(Odd("empty"), page="history")
        ui = window.screen_widget.history_ui
        blob = "\n".join(self.labels(window.screen_widget))
        self.assertIn(T["post_status_unknown"], blob, "모르는 상태는 알 수 없음으로 보인다")
        self.assertFalse(ui.copy_buttons["odd2:naver_a"].isEnabled(), "키 모양이 든 주소는 복사 단추가 꺼진다")
        del window.test_copies[:]
        window.history_copy_url("odd2:naver_a")
        self.assertEqual(window.test_copies, [], "단추를 거치지 않고 불러도 키 모양이 든 주소는 복사하지 않는다")
        ui.log_toggle.click()
        self.wait_for(lambda: window.state.history.log_state == "normal")
        self.settle(6)
        everything = self.labels(window.screen_widget) + [widget.accessibleName() for widget in window.screen_widget.findChildren(QWidget)] + [widget.toolTip() for widget in window.screen_widget.findChildren(QWidget)]
        for start in range(0, len(KEY) - 5, 3):
            self.assertFalse([item for item in everything if KEY[start:start + 6] in item], f"연속 6글자 조각도 화면 글에 없다: {start}")


class PostsQtHistoryStatesTest(Base):
    def test_the_empty_state_has_one_primary_button_that_goes_to_the_posts_screen(self):
        window = self.make(Recording("empty"), page="history")
        self.assertEqual(window.state.history.state, "empty")
        primary = self.primary_buttons(window)
        self.assertEqual([button.text() for button in primary], [T["hist_empty_button"]])
        self.assertEqual(primary[0].accessibleName(), T["hist_empty_button_a11y"])
        self.assertIn(T["hist_empty_title"], self.labels(window.screen_widget))
        self.assertIsNone(window.screen_widget.history_ui.order_button, "빈 화면에는 정렬 단추가 없다")
        primary[0].click()
        self.wait_for(lambda: window.state.page == "posts")

    def test_the_error_state_is_an_easy_sentence_with_retry_and_the_code_only_in_the_folded_info(self):
        window = self.make(Recording("error"), page="history")
        self.assertEqual(window.state.history.state, "error")
        texts = self.shown_labels(window.screen_widget)
        self.assertIn(T["hist_error_title"], texts)
        self.assertIn(T["hist_retry"], self.buttons(window.screen_widget))
        self.assertFalse([item for item in texts if "SAMPLE_POSTS_UNREADABLE" in item], "오류 코드는 기본 화면의 글에 없다")
        self.assertTrue([item for item in self.labels(window.screen_widget) if "SAMPLE_POSTS_UNREADABLE" in item], "코드는 접힌 진단 정보에 있다")
        window.state.history.provider.scenario = "normal"
        self.buttons(window.screen_widget)[T["hist_retry"]].click()
        self.wait_for(lambda: window.state.history.state in ("normal", "empty"))
        self.assertNotEqual(window.state.history.state, "error")

    def test_the_partial_and_offline_states_show_a_band_and_keep_the_rows(self):
        for scenario, banner in (("partial", T["hist_partial"].format(n=1)), ("offline", T["hist_offline"])):
            with self.subTest(scenario=scenario):
                window = self.make(Recording(scenario), page="history")
                self.assertEqual(window.state.history.state, scenario)
                self.assertIn(banner, self.labels(window.screen_widget))
                self.assertEqual(len(window.screen_widget.history_ui.rows), 3)

    def test_the_loading_state_shows_a_skeleton_and_a_sentence_and_the_reload_button_is_off(self):
        gate = threading.Event()

        class Held(Recording):
            def load_history(self, progress, cancelled):
                gate.wait(20)                                                                  # 시험이 문을 열 때까지 읽는 중이다(시간으로 기다리지 않는다 — 바쁜 PC 에서도 같다)
                return super().load_history(progress, cancelled)

        window = self.make(Held("normal"), page="history", wait=False)
        self.addCleanup(gate.set)
        self.settle(2)
        self.assertEqual(window.state.history.state, "loading")
        self.assertIn(T["hist_loading"], self.labels(window.screen_widget))
        self.assertTrue([widget for widget in window.screen_widget.findChildren(QWidget) if widget.accessibleName() == T["hist_loading_a11y"]])
        self.assertFalse(window.screen_widget.history_ui.reload_button.isEnabled(), "읽는 중에는 다시 읽기가 꺼져 있다")
        gate.set()
        self.wait_for(lambda: window.state.history.state == "normal")
        self.settle(6)
        self.assertEqual(len(window.screen_widget.history_ui.rows), 3)

    def test_a_long_list_shows_fifty_and_a_more_button_that_adds_fifty(self):
        class Many(Recording):
            def load_history(self, progress, cancelled):
                rows = tuple(post_history.HistoryEntry(f"many{number:04d}", f"예시 글 {number}", "naver_a", st.READY_TO_COPY, 1, f"2026-11-01T00:{number // 60:02d}:{number % 60:02d}Z") for number in range(120))
                return post_history.HistoryData(rows, 0, "ok", True, False)

        window = self.make(Many("empty"), page="history")
        ui = window.screen_widget.history_ui
        self.assertEqual(len(ui.rows), 50)
        self.assertEqual(ui.more_button.accessibleName(), T["hist_more_a11y"])
        ui.more_button.click()
        self.settle(6)
        self.assertEqual(len(window.screen_widget.history_ui.rows), 100)


class PostsQtLayoutTest(Base):
    def check_window(self, window, size):
        self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, f"{size}: 가로 스크롤이 없다")
        for button in window.screen_widget.findChildren(QPushButton):
            if not button.isVisibleTo(window) or not button.text():
                continue
            self.assertLessEqual(button.mapTo(window, button.rect().topRight()).x(), window.width(), f"{size}: {button.text()} 단추가 창 밖에 있다")
            self.assertGreaterEqual(button.height(), 34, f"{size}: {button.text()} 누르는 칸이 너무 작다")

    def test_the_package_card_and_the_record_dialog_fit_in_every_required_size(self):
        for size in SIZES:
            with self.subTest(size=size):
                provider = Recording("empty")
                project_id = provider.add_post("글 하나 " + "아주 긴 제목 " * 8, post_fake.sample_text() + NL + NL + "- 항목" * 20)
                ready(provider, project_id)
                window = self.open_window(provider, size=size)
                window.post_open(project_id)
                self.wait_for(lambda: window.state.posts.detail_state == "normal" and window.state.posts.open_id == project_id)
                self.settle(8)
                window.post_platform(A)
                self.settle(6)
                self.check_window(window, size)
                copied(provider, project_id)
                self.reopen(window, project_id)
                window.post_platform(A)
                self.settle(6)
                self.check_window(window, size)
                window.screen_widget.posts_ui.review.package.buttons["record"].click()
                self.settle(6)
                dialog = window.dialog
                self.assertTrue(dialog.is_open)
                self.assertLessEqual(dialog.width(), window.width(), size)
                self.assertLessEqual(dialog.height(), window.height(), size)
                self.assertGreaterEqual(dialog.y(), 0, size)
                window.escape()
                self.settle(4)
                window.close()

    def test_the_history_screen_fits_every_required_size_with_the_log_card_open(self):
        for size in SIZES:
            with self.subTest(size=size):
                window = self.open_window(Recording("normal"), size=size, page="history")
                self.check_window(window, size)
                window.screen_widget.history_ui.log_toggle.click()
                self.wait_for(lambda: window.state.history.log_state == "normal")
                self.settle(6)
                self.check_window(window, size)
                window.close()


class PostsQtSidebarTest(Base):
    def test_eight_menus_fit_the_minimum_window_with_no_next_steps_box_and_no_taller_than_before(self):
        window = self.make(Recording("empty"), size=(900, 560), page="home")
        height = window.sidebar.minimumSizeHint().height()
        self.assertIsNone(window.sidebar.soon_list)
        self.assertLessEqual(height, 488, "1a 가 맞춘 높이(488) 안에 여덟 메뉴가 들어간다 — 다음 단계 상자가 없어졌다")
        self.assertLessEqual(height, 560 - 60, "최소 창(900x560)의 높이 안에 들어간다")
        self.assertEqual(len(window.nav_buttons), 8)
        for button in window.nav_buttons.values():
            self.assertTrue(42 <= button.height() <= 46, button.height())
        brand = window.sidebar.findChild(QWidget, "brandcard")
        self.assertLess(window.nav_buttons["settings"].geometry().bottom(), brand.geometry().top())

    def test_the_shell_is_wired_to_the_history_screen_through_the_one_table_and_the_one_mixin(self):
        import ast
        qt_dir = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"
        klass = next(node for node in ast.parse((qt_dir / "shell.py").read_text(encoding="utf-8")).body if isinstance(node, ast.ClassDef) and node.name == "AppShell")
        self.assertEqual([ast.unparse(base) for base in klass.bases], ["HistoryFlowMixin", "PostFlowMixin", "QMainWindow"])
        self.assertIn("_history_builder", [node.name for node in ast.parse((qt_dir / "screens.py").read_text(encoding="utf-8")).body if isinstance(node, ast.FunctionDef)])


class PostsQtRealServiceTest(Base):
    """실제 서비스(임시 데이터 폴더)로 화면에서 끝까지 — 보기만 하는 동안 한 바이트도 안 바뀌고, 쓰는 일은 데이터 폴더 안에서만 일어난다."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = support.make_ctx(self.tmp.name, repo="")
        support.naver_profiles(self.ctx)
        self.provider = posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: self.ctx)
        self.root = Path(self.tmp.name)

    def stats(self, root):
        return {path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) for path in sorted(Path(root).rglob("*")) if path.is_file()}

    def status(self, project_id, platform=A):
        return support.status_of(self.ctx, project_id, platform)

    def new_post(self):
        return self.provider.import_post(posts.ImportRequest("markdown", "에너지 절약 습관", support.ko_text()), SAFE, NEVER).detail.project_id

    def test_copy_then_record_then_history_through_the_screen_with_the_real_service(self):
        from chanceblog_desktop.service import projects, review
        project_id = self.new_post()
        window = self.make(self.provider)
        outside = {path: data for path, data in support.tree_snapshot(self.root).items() if not path.startswith("data/")}
        self.reopen(window, project_id)
        window.post_platform(A)
        self.settle(4)
        self.review_ui(window).buttons["review"].click()
        self.wait_write(window)
        self.review_ui(window).buttons["approve"].click()
        self.settle()
        self.dialog_button(window, T["post_confirm_ok"]).click()
        self.wait_write(window)
        self.assertEqual(self.status(project_id), "READY_TO_COPY")
        card = self.review_ui(window).package
        self.assertEqual(card.property("package_mode"), "ready")
        stored = review.read_naver_package(self.ctx.reading_only(), project_id, "naver_a")
        before = self.stats(self.ctx.workspace.root)
        card.buttons["all"].click()
        self.settle(3)
        self.assertEqual(window.test_copies[-1], stored.copy_text, "복사한 글은 서비스가 만든 패키지 그대로다")
        self.assertEqual(self.stats(self.ctx.workspace.root), before, "복사 단추는 한 바이트도 바꾸지 않는다")
        self.review_ui(window).package.buttons["copied"].click()
        self.wait_write(window)
        self.assertEqual(self.status(project_id), "COPY_COMPLETED")
        self.review_ui(window).package.buttons["record"].click()
        self.settle(4)
        form = window.post_record_form
        form.input.setText("https://blog.naver.com/")
        form.start_button.click()
        self.settle(4)
        self.assertEqual(form.problem.plain_text(), T["post_rec_p_path"], "글 주소(경로)가 없는 주소는 글 주소가 아니다")
        self.assertEqual(self.status(project_id), "COPY_COMPLETED")
        form.input.setText(GOOD_URL)
        form.start_button.click()
        self.wait_write(window)
        self.assertEqual(self.status(project_id), "PUBLISHED_MANUAL")
        self.assertEqual(projects.show_project(self.ctx, project_id).variant(A).published_url, GOOD_URL)
        self.assertIn(T["post_published_url"].format(url=GOOD_URL), self.labels(self.review_ui(window).package))
        window.go("history")
        self.wait_for(lambda: window.state.history.state != "loading" and not window.state.history.loading)
        self.settle(6)
        ui = window.screen_widget.history_ui
        key = f"{project_id}:naver_a"
        self.assertIn(key, ui.rows)
        self.assertIn(T["hist_row_url"].format(url=GOOD_URL), self.labels(ui.rows[key]))
        ui.copy_buttons[key].click()
        self.settle(3)
        self.assertEqual(window.test_copies[-1], GOOD_URL)
        ui.log_toggle.click()
        self.wait_for(lambda: window.state.history.log_state in ("normal", "empty"))
        self.settle(6)
        self.assertIn(T["hist_log_empty"], self.labels(window.screen_widget.history_ui.log_card))
        after = {path: data for path, data in support.tree_snapshot(self.root).items() if not path.startswith("data/")}
        self.assertEqual(after, outside, "데이터 폴더 밖은 한 바이트도 안 바뀐다")
        inside = sorted(path.relative_to(self.ctx.workspace.root).as_posix() for path in self.ctx.workspace.root.rglob("*") if path.is_file())
        self.assertFalse([path for path in inside if path.startswith(("publish", "backups"))], inside)

    def test_only_looking_at_the_history_and_the_log_never_changes_a_byte(self):
        project_id = self.new_post()
        ready(self.provider, project_id)
        copied(self.provider, project_id)
        record(self.provider, project_id)
        before = self.stats(self.ctx.workspace.root)
        window = self.make(self.provider, page="history")
        ui = window.screen_widget.history_ui
        self.assertEqual(list(ui.rows), [f"{project_id}:naver_a"])
        ui.log_toggle.click()
        self.wait_for(lambda: window.state.history.log_state in ("normal", "empty"))
        window.reload_history()
        self.wait_for(lambda: not window.state.history.loading)
        window.history_toggle_order()
        window.go("posts")
        self.wait_for(lambda: not window.state.posts.loading)
        window.go("history")
        self.wait_for(lambda: not window.state.history.loading)
        self.settle(6)
        self.assertEqual(self.stats(self.ctx.workspace.root), before)

    def test_a_published_post_is_shown_with_its_address_in_the_card_after_a_fresh_read(self):
        project_id = self.new_post()
        ready(self.provider, project_id)
        copied(self.provider, project_id)
        record(self.provider, project_id)
        window = self.make(self.provider)
        self.reopen(window, project_id)
        window.post_platform(A)
        self.settle(4)
        card = self.review_ui(window).package
        self.assertEqual((card.property("package_mode"), sorted(card.buttons)), ("published", ["url"]))
        card.buttons["url"].click()
        self.settle(3)
        self.assertEqual(window.test_copies, [GOOD_URL])


if __name__ == "__main__":
    unittest.main()
