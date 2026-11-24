"""글 검토 화면(글 흐름 1a, 결정 D-620 이후)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 메뉴·여섯 상태·가져오기 대화·미리보기·검토 카드·승인 확인창·크기·접근성·실제 서비스로 끝까지 돌려 본 모습을 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_posts_core`·`test_ui_posts_adapter`). 사용자의 클립보드·보관소·데이터 폴더·설정 파일은 건드리지 않는다(가짜 공급자·임시 폴더).

지키는 것:
  1) 메뉴에 `글 검토` 가 핵심 작업 묶음의 초안 작성 다음에 있고 누르면 새 화면이 열린다. 목록의 주요 단추는 하나다. 읽는 중·오류·빈·일부만·오프라인 모습이 문장으로 보인다.
  2) 가져오기 대화는 입력이 있는 채로 닫으면 먼저 묻고(처음 포커스는 안전한 쪽) 닫으면 칸을 비운다. 실패하면 대화·칸의 글이 그대로이고 이유가 보인다. 앱 닫기도 같은 확인이다.
  3) 미리보기는 글자만 그리고(서식 글 위젯 없음·스크립트는 글자 그대로·키 모양은 가림) 긴 글은 앞부분만 보인다.
  4) 검토 결과의 세 층이 글자 배지와 함께 보이고, 막힘이 있으면 승인 단추가 꺼지며, 승인은 확인창(처음 포커스는 취소)을 거쳐야 하고, 승인 취소로 검토 중에 돌아간다.
  5) 필수 창 크기 여섯에서 가로 스크롤이 없고 단추가 창 안에 있으며, 모든 단추·칸이 접근 이름을 가진다.
  6) 실제 서비스로 끝까지 돌려도 데이터 폴더 밖에 아무것도 생기지 않고 읽기만 하는 동안은 한 바이트도 바뀌지 않는다.
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import service_support as support  # noqa: E402

from chanceblog_desktop.ui import posts_adapter  # noqa: E402
from chanceblog_desktop.ui.core import app_state, post_fake, posts, services, text  # noqa: E402

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
    from chanceblog_desktop.ui.qt import blog_parts, post_parts
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module

T = text.T
SIZES = ((1366, 768), (1093, 614), (1536, 864), (1280, 720), (1920, 1080), (900, 560))
PICKED = "C:/예시 폴더/내 글.md"                                    # 선택기가 돌려줄 가짜 위치 — 그런 파일은 없다(가짜 공급자는 읽지 않는다)
KEY = support.KEY
RAW_FIELDS = {"category": "생활", "image_url": "https://img.example.invalid/a.jpg"}
NL = chr(10)


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

    def activate(self, window):
        window.activateWindow()
        ui_offscreen.wait_until(self.app, window.isActiveWindow, 2)

    def make(self, provider=None, size=(1366, 768), picker=None, go=True, wait=True):
        provider = provider or post_fake.FakePostsProvider()
        window = shell_module.AppShell(services.FakeHomeProvider(), posts=provider, file_picker=picker or (lambda parent, title, filters: PICKED), autoload=False)
        window.resize(*size)
        window.show()
        self.addCleanup(window.close)
        self.settle()
        self.activate(window)
        if go:
            window.go("posts")
            if wait:
                ui_offscreen.wait_until(self.app, lambda: window.state.posts.state != "loading" and not window.state.posts.loading, 10)
            self.settle()
        return window

    def ui(self, window):
        return window.screen_widget.posts_ui

    def labels(self, root):
        return [label.plain_text() for label in root.findChildren(UI.Label)]

    def shown_labels(self, root):
        """눈에 보이는 글만 — 접어 둔 자세히·진단 정보 안의 글은 빠진다."""
        return [label.plain_text() for label in root.findChildren(UI.Label) if label.isVisibleTo(root)]

    def buttons(self, root):
        return {button.text(): button for button in root.findChildren(QAbstractButton)}

    def rows(self, window):
        card = self.ui(window).list_card
        return {} if card is None else {row.post_id: row for row in card.findChildren(post_parts.PostRow)}

    @staticmethod
    def next_stop(widget):
        """Tab 으로 갈 다음 정거장 — 초점을 받을 수 있고 보이고 켜진 다음 위젯(글자 줄 같은 정거장 아닌 위젯은 건너뛴다)."""
        probe = widget.nextInFocusChain()
        while probe is not widget:
            if probe.focusPolicy() != Qt.NoFocus and probe.isVisibleTo(probe.window()) and probe.isEnabled():
                return probe
            probe = probe.nextInFocusChain()
        return None

    def open_post(self, window, project_id):
        QTest.mouseClick(self.rows(window)[project_id], Qt.LeftButton)
        ui_offscreen.wait_until(self.app, lambda: window.state.posts.detail_state == "normal", 10)
        self.settle(8)

    def wait_write(self, window):
        ui_offscreen.wait_until(self.app, lambda: not window.state.posts.busy and window.state.posts.pending is None, 10)
        self.settle(8)

    def add_long(self, provider, title="긴 글"):
        return provider.add_post(title, post_fake.sample_text())

    def with_post(self, markdown=None, title="검토할 글", **kwargs):
        provider = post_fake.FakePostsProvider("empty", **kwargs)
        project_id = provider.add_post(title, markdown if markdown is not None else post_fake.sample_text())
        window = self.make(provider)
        self.open_post(window, project_id)
        return window, provider, project_id

    def pages_review(self, window, **change):
        self.buttons(window.screen_widget)[T["post_review_start"]].click()
        self.settle()
        form = window.post_pages_form
        self.assertIsNotNone(form)
        for name, value in {**RAW_FIELDS, **change}.items():
            form.inputs[name].setText(value)
        form.start_button.click()
        self.wait_write(window)
        return form

    def primary_buttons(self, root):
        return [button for button in root.findChildren(QPushButton) if button.property("kind") == "primary" and button.isVisibleTo(root.window())]

    def dialog_button(self, window, label):
        return {button.text(): button for button in window.dialog.findChildren(QAbstractButton)}[label]


class PostsQtMenuTest(Base):
    def test_the_menu_is_in_the_core_group_after_drafts_and_opens_the_screen(self):
        window = self.make(go=False)
        self.assertEqual(list(window.nav_buttons), ["home", "topics", "drafts", "posts", "seed", "blogs", "settings"])
        self.assertEqual(window.nav_buttons["posts"].accessibleName(), "글 검토 메뉴로 이동")
        self.assertEqual(list(window.sidebar.group_titles), ["core", "data", "system"])
        window.nav_buttons["posts"].click()
        ui_offscreen.wait_until(self.app, lambda: window.state.posts.state != "loading", 10)
        self.settle()
        self.assertEqual((window.state.page, window.nav_buttons["posts"].isChecked(), window.nav_buttons["home"].isChecked()), ("posts", True, False))
        self.assertEqual(len(self.rows(window)), 4)
        self.assertEqual(list(S.SCREEN_BUILDERS), [key for key, _label, _icon in app_state.NAV])
        self.assertIn("posts", S.SCREEN_BUILDERS)

    def test_the_list_has_exactly_one_primary_button_and_it_is_the_import_button(self):
        window = self.make()
        primary = self.primary_buttons(window.screen_widget)
        self.assertEqual([button.text() for button in primary], [T["post_import"]])
        self.assertEqual(primary[0].accessibleName(), T["post_import_a11y"])

    def test_opening_the_screen_reads_but_never_writes(self):
        provider = post_fake.FakePostsProvider()
        window = self.make(provider)
        self.assertEqual(set(provider.calls), {"load_posts"})
        window.go("home")
        window.go("posts")
        ui_offscreen.wait_until(self.app, lambda: not window.state.posts.loading, 10)
        self.assertNotIn("import_post", provider.calls)
        self.assertNotIn("review_post", provider.calls)

    def test_the_example_data_badge_is_there_and_explains_itself(self):
        window = self.make()
        badges = [widget for widget in window.screen_widget.findChildren(QWidget) if widget.accessibleName() == T["sample_tag"]]
        self.assertTrue(badges)
        window.show_sample_info("posts")
        self.settle()
        self.assertIn(T["post_sample_dialog_body"], self.labels(window.dialog) + [label.plain_text() for label in window.dialog.findChildren(UI.Label)] + [window.dialog.findChild(UI.DialogBody).plain_text()])


class PostsQtStatesTest(Base):
    def test_the_loading_state_shows_a_skeleton_and_a_sentence(self):
        window = self.make(post_fake.FakePostsProvider(delay=0.6), wait=False)
        self.assertEqual(window.state.posts.state, "loading")
        self.assertIn(T["post_loading"], self.labels(window.screen_widget))
        self.assertTrue([widget for widget in window.screen_widget.findChildren(QWidget) if widget.accessibleName() == T["post_loading_a11y"]])
        self.assertFalse(self.ui(window).import_button is None)
        ui_offscreen.wait_until(self.app, lambda: window.state.posts.state == "normal", 10)
        self.settle()
        self.assertEqual(len(self.rows(window)), 4)

    def test_the_empty_state_has_one_primary_button_in_the_card_and_a_quiet_header_button(self):
        window = self.make(post_fake.FakePostsProvider("empty"))
        self.assertIn(T["post_empty_title"], self.labels(window.screen_widget))
        primary = self.primary_buttons(window.screen_widget)
        self.assertEqual(len(primary), 1)
        self.assertEqual(primary[0].property("focus_key"), "post:import-empty")
        self.assertEqual(self.ui(window).import_button.property("kind"), "secondary")
        primary[0].click()
        self.settle()
        self.assertTrue(window.dialog.is_open)

    def test_the_error_state_is_an_easy_sentence_with_retry_and_the_code_only_in_the_folded_info(self):
        window = self.make(post_fake.FakePostsProvider("error"))
        texts = self.shown_labels(window.screen_widget)
        self.assertIn(T["post_error_title"], texts)
        self.assertIn(T["post_retry"], self.buttons(window.screen_widget))
        self.assertFalse([item for item in texts if "SAMPLE_POSTS_UNREADABLE" in item], "오류 코드는 기본 화면의 글에 없다")
        disclosure = window.screen_widget.findChild(UI.Disclosure)
        self.assertIn("SAMPLE_POSTS_UNREADABLE", disclosure.body.plain_text())
        self.assertFalse(disclosure.body.isVisible(), "진단 정보는 접혀 있다")
        window.state.posts.provider.scenario = "normal"
        self.buttons(window.screen_widget)[T["post_retry"]].click()
        ui_offscreen.wait_until(self.app, lambda: window.state.posts.state in ("normal", "empty"), 10)
        self.assertNotEqual(window.state.posts.state, "error")

    def test_the_partial_state_shows_a_band_and_the_unreadable_row_cannot_be_opened(self):
        window = self.make(post_fake.FakePostsProvider("partial"))
        self.assertIn(T["post_partial"].format(n=1), self.labels(window.screen_widget))
        broken = [row for row in self.ui(window).list_card.findChildren(post_parts.PostRow) if row.post_id == "exmbroken"][0]
        self.assertEqual(broken.focusPolicy(), Qt.NoFocus)
        QTest.mouseClick(broken, Qt.LeftButton)
        self.settle()
        self.assertEqual(window.state.page, "posts")
        self.assertIsNone(window.state.posts.open_id)

    def test_the_offline_state_shows_its_band(self):
        window = self.make(post_fake.FakePostsProvider("offline"))
        self.assertIn(T["post_offline"], self.labels(window.screen_widget))

    def test_a_long_list_shows_fifty_and_a_more_button_that_adds_fifty(self):
        window = self.make(post_fake.FakePostsProvider("many"))
        self.assertEqual(len(self.rows(window)), 50)
        more = self.ui(window).list_card.more_button
        self.assertEqual(more.accessibleName(), T["post_more_a11y"])
        more.click()
        self.settle()
        self.assertEqual(len(self.rows(window)), 100)

    def test_a_key_shaped_title_never_reaches_a_label_or_an_accessible_name(self):
        provider = post_fake.FakePostsProvider("empty")
        provider.add_post("제목 " + KEY, post_fake.sample_text())
        window = self.make(provider)
        names = self.labels(window.screen_widget) + [widget.accessibleName() for widget in window.screen_widget.findChildren(QWidget)]
        self.assertFalse([item for item in names if KEY[:12] in item])


class PostsQtImportTest(Base):
    def open_import(self, window):
        self.ui(window).import_button.click()
        self.settle()
        self.assertTrue(window.dialog.is_open)
        return window.post_import_form

    def test_the_dialog_opens_empty_with_the_start_button_off_and_nothing_called(self):
        provider = post_fake.FakePostsProvider("empty")
        window = self.make(provider)
        form = self.open_import(window)
        self.assertEqual((form.title_text(), form.body_text(), form.start_button.isEnabled(), form.cancel_button.isEnabled()), ("", "", False, True))
        self.assertEqual(provider.calls, ["load_posts"])
        self.assertEqual(window.dialog.accessibleName(), T["post_im_title"])
        self.assertIsNotNone(form.title_input.accessibleName())
        self.assertEqual(QApplication.focusWidget(), form.title_input)

    def test_typing_a_title_and_a_body_in_korean_turns_the_start_button_on_and_importing_opens_the_post(self):
        provider = post_fake.FakePostsProvider("empty")
        window = self.make(provider)
        form = self.open_import(window)
        form.title_input.setText("새로 쓴 글")
        form.body_input.setFocus(Qt.OtherFocusReason)
        event = QInputMethodEvent()
        event.setCommitString("한글 본문을 입력기로 넣어요. " * 3)
        QApplication.sendEvent(form.body_input, event)
        self.settle(2)
        self.assertTrue(form.start_button.isEnabled())
        self.assertTrue(window.state.posts.import_dirty)
        form.start_button.click()
        self.wait_write(window)
        self.assertFalse(window.dialog.is_open)
        self.assertIsNone(window.post_import_form)
        self.assertEqual((window.state.posts.view()["mode"], len(provider.projects)), ("detail", 1))
        self.assertIn("새로 쓴 글", self.labels(window.screen_widget))
        self.assertIn(T["post_im_done"].format(title="새로 쓴 글"), self.labels(window.screen_widget))

    def test_closing_with_typed_text_asks_first_and_keeps_the_text_until_the_discard_is_chosen(self):
        window = self.make(post_fake.FakePostsProvider("empty"))
        form = self.open_import(window)
        form.title_input.setText("쓰던 글")
        form.body_input.setPlainText("본문 일부")
        form.cancel_button.click()
        self.settle(4)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual((form.title_text(), form.body_text()), ("쓰던 글", "본문 일부"))
        self.assertTrue(window.state.posts.import_ask)
        self.assertIn(T["post_im_discard_q"], self.labels(form))
        self.assertEqual(QApplication.focusWidget().text(), T["post_im_discard_no"], "처음 포커스는 안전한 쪽(계속 쓰기)")
        self.buttons(form)[T["post_im_discard_no"]].click()
        self.settle(4)
        self.assertEqual((form.body_text(), window.state.posts.import_ask), ("본문 일부", False))
        window.escape()
        self.settle(4)
        self.assertTrue(window.state.posts.import_ask, "Esc 도 같은 확인이 먼저다")
        window.escape()
        self.settle(4)
        self.assertFalse(window.state.posts.import_ask, "확인 줄이 떠 있을 때 Esc 는 계속 쓰기다")
        form.cancel_button.click()
        self.buttons(form)[T["post_im_discard_yes"]].click()
        self.settle(4)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual((form.title_text(), form.body_text()), ("", ""), "닫으면 칸이 비워진다")
        self.assertFalse(form.body_input.document().isUndoAvailable())
        self.assertFalse(window.state.posts.import_open)

    def test_closing_an_untouched_dialog_needs_no_question_and_esc_closes_it(self):
        window = self.make(post_fake.FakePostsProvider("empty"))
        form = self.open_import(window)
        window.escape()
        self.settle(4)
        self.assertFalse(window.dialog.is_open)
        self.assertIsNone(window.post_import_form)
        form = self.open_import(window)
        form.cancel_button.click()
        self.settle(4)
        self.assertFalse(window.dialog.is_open)

    def test_a_refused_import_keeps_the_dialog_and_the_text_and_says_why_without_the_key(self):
        provider = post_fake.FakePostsProvider("empty")
        window = self.make(provider)
        form = self.open_import(window)
        form.title_input.setText("키가 든 글")
        form.body_input.setPlainText("첫 줄" + NL + "둘째 " + KEY)
        form.start_button.click()
        self.wait_write(window)
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(form.body_text(), "첫 줄" + NL + "둘째 " + KEY, "입력은 그대로 남는다")
        self.assertTrue(form.message.isVisibleTo(form))
        self.assertIn("본문 2번째 줄", form.message.plain_text())
        self.assertNotIn(KEY[:10], form.message.plain_text())
        self.assertEqual(len(provider.projects), 0)
        self.assertEqual(window.state.posts.view()["mode"], "list")

    def test_a_picked_file_fills_the_body_and_a_title_suggestion_and_says_so(self):
        window = self.make(post_fake.FakePostsProvider("empty"))
        form = self.open_import(window)
        form.pick_button.click()
        ui_offscreen.wait_until(self.app, lambda: not window.state.posts.reading_file, 10)
        self.settle(6)
        self.assertEqual(form.title_text(), "내 글")
        self.assertIn("에너지 절약", form.body_text())
        self.assertIn(T["post_im_read_ok"], form.note.plain_text())
        self.assertTrue(form.start_button.isEnabled())
        self.assertNotIn(form.body_text()[:30], repr(window.state.posts.view()) + repr(vars(window.state.posts)), "컨트롤러는 읽은 글을 쥐지 않는다")

    def test_a_cp949_file_and_a_bad_file_say_so_and_leave_the_text_alone(self):
        window = self.make(post_fake.FakePostsProvider("empty"), picker=lambda parent, title, filters: "C:/폴더/cp949 글.md")
        form = self.open_import(window)
        form.pick_button.click()
        ui_offscreen.wait_until(self.app, lambda: not window.state.posts.reading_file, 10)
        self.settle(6)
        self.assertIn(T["post_im_cp949"], form.note.plain_text())
        window2 = self.make(post_fake.FakePostsProvider("empty"), picker=lambda parent, title, filters: "C:/폴더/나쁜.bad")
        form2 = self.open_import(window2)
        form2.title_input.setText("그대로")
        form2.pick_button.click()
        ui_offscreen.wait_until(self.app, lambda: not window2.state.posts.reading_file, 10)
        self.settle(6)
        self.assertIn("글 파일이 아닌 것 같아요", form2.message.plain_text())
        self.assertEqual(form2.title_text(), "그대로")

    def test_cancelling_the_file_picker_does_nothing(self):
        provider = post_fake.FakePostsProvider("empty")
        window = self.make(provider, picker=lambda parent, title, filters: "")
        form = self.open_import(window)
        form.pick_button.click()
        self.settle(4)
        self.assertNotIn("read_import_file", provider.calls)

    def test_the_html_kind_hides_the_file_button_and_imports_pasted_html(self):
        provider = post_fake.FakePostsProvider("empty")
        window = self.make(provider)
        form = self.open_import(window)
        form.kinds.chips["html"].click()
        self.settle(4)
        self.assertFalse(form.pick_button.isVisibleTo(form))
        self.assertIn(T["post_im_html_note"], form.kind_note.plain_text())
        form.title_input.setText("옛 글")
        form.body_input.setPlainText("<h2>소제목</h2><p>문단이에요</p><script>alert(1)</script>")
        form.start_button.click()
        self.wait_write(window)
        project = next(iter(provider.projects.values()))
        self.assertNotIn("script", project.source_content.lower())

    def test_closing_the_app_with_typed_text_asks_in_the_same_dialog_first(self):
        window = self.make(post_fake.FakePostsProvider("empty"))
        form = self.open_import(window)
        form.body_input.setPlainText("아직 가져오지 않은 글")
        self.assertFalse(window.close(), "입력이 있으면 닫히지 않는다")
        self.settle(4)
        self.assertTrue(window.isVisible())
        self.assertTrue(window.state.posts.import_ask)
        self.assertEqual(QApplication.focusWidget().text(), T["post_im_discard_no"])
        self.buttons(form)[T["post_im_discard_no"]].click()
        self.assertTrue(window.isVisible(), "계속 쓰기를 고르면 앱도 열려 있다")
        self.assertFalse(window.state.posts.import_quit)
        self.assertFalse(window.close())
        self.buttons(form)[T["post_im_discard_yes"]].click()
        self.settle(4)
        self.assertFalse(window.isVisible(), "그래도 닫기를 고르면 앱이 닫힌다")

    def test_the_wait_for_the_app_close_never_leaks_into_a_later_cancel_of_the_dialog(self):
        window = self.make(post_fake.FakePostsProvider("empty"))
        form = self.open_import(window)
        form.body_input.setPlainText("아직 가져오지 않은 글")
        self.assertFalse(window.close())
        self.assertTrue(window.state.posts.import_quit)
        form.body_input.insertPlainText(" 더 입력해요")
        self.settle(2)
        self.assertFalse(window.state.posts.import_ask or window.state.posts.import_quit, "확인 줄이 뜬 뒤 계속 입력하면 앱 닫기를 기다리지 않는다")
        form.cancel_button.click()
        self.settle(4)
        self.assertTrue(window.state.posts.import_ask)
        self.assertFalse(window.state.posts.import_quit)
        form.cancel_button.click()
        self.settle(4)
        self.assertTrue(window.dialog.is_open and window.state.posts.import_ask, "확인 줄이 떠 있을 때 취소를 또 눌러도 닫히지 않는다")
        self.buttons(form)[T["post_im_discard_yes"]].click()
        self.settle(4)
        self.assertFalse(window.dialog.is_open)
        self.assertTrue(window.isVisible(), "대화만 닫혔고 앱은 열려 있다")

    def test_closing_the_app_while_importing_does_not_ask_and_leaves_no_wait_behind(self):
        import threading
        gate = threading.Event()

        class Gated(post_fake.FakePostsProvider):
            def import_post(self, request, progress, cancelled):
                gate.wait(10)
                raise posts.PostFailure(T["post_fail_input_plain"], code="CONTENT_INVALID", kind="input")

        window = self.make(Gated("empty"))
        form = self.open_import(window)
        form.title_input.setText("제목")
        form.body_input.setPlainText("본문 글이에요")
        form.start_button.click()
        ui_offscreen.wait_until(self.app, lambda: window.state.posts.busy, 5)
        self.assertFalse(window.close(), "가져오는 중에는 닫히지 않는다")
        self.assertFalse(window.state.posts.import_quit or window.state.posts.import_ask)
        gate.set()
        self.wait_write(window)
        self.assertTrue(window.dialog.is_open, "실패했으니 대화는 열려 있다")
        form.cancel_button.click()
        self.settle(4)
        self.buttons(form)[T["post_im_discard_yes"]].click()
        self.settle(4)
        self.assertTrue(window.isVisible(), "실패한 뒤의 그래도 닫기는 대화만 닫는다")

    def test_a_file_name_with_dots_keeps_everything_but_the_extension_as_the_title_suggestion(self):
        window = self.make(post_fake.FakePostsProvider("empty"), picker=lambda parent, title, filters: "C:/폴더/2026.11.24 후기.md")
        form = self.open_import(window)
        form.pick_button.click()
        ui_offscreen.wait_until(self.app, lambda: not window.state.posts.reading_file, 10)
        self.settle(6)
        self.assertEqual(form.title_text(), "2026.11.24 후기")

    def test_a_file_read_over_a_typed_body_says_so_and_ctrl_z_brings_the_typed_text_back(self):
        window = self.make(post_fake.FakePostsProvider("empty"))
        form = self.open_import(window)
        form.body_input.setPlainText("직접 쓴 본문")
        form.pick_button.click()
        ui_offscreen.wait_until(self.app, lambda: not window.state.posts.reading_file, 10)
        self.settle(6)
        self.assertIn("에너지 절약", form.body_text())
        self.assertIn(T["post_im_replaced"], form.note.plain_text())
        form.body_input.undo()
        self.assertEqual(form.body_text(), "직접 쓴 본문", "되돌리기 한 번으로 쓰던 글이 돌아온다")

    def test_a_redraw_under_an_open_dialog_keeps_the_tab_inside_the_dialog(self):
        window = self.make(post_fake.FakePostsProvider())
        self.open_import(window)
        window.state.posts.start_load(**window.posts_bridge.callbacks())
        ui_offscreen.wait_until(self.app, lambda: not window.state.posts.loading, 10)
        self.settle(6)
        outside = [widget for widget in window.screen_widget.findChildren(QWidget) if widget.focusPolicy() != Qt.NoFocus]
        self.assertEqual(outside, [], "다시 그린 화면에도 대화 밖 Tab 정거장이 없다")

    def test_an_unexpected_error_after_the_controller_closed_the_dialog_still_closes_the_dialog_parts(self):
        import contextlib
        import io
        window = self.make(post_fake.FakePostsProvider("empty"))
        form = self.open_import(window)
        form.title_input.setText("제목")
        form.body_input.setPlainText(post_fake.sample_text())
        controller = window.state.posts
        original = controller.apply_write_ok

        def boom(outcome):
            original(outcome)                                                   # 컨트롤러는 이미 대화를 닫았다
            raise RuntimeError("예기치 못한 오류")

        controller.apply_write_ok = boom
        with contextlib.redirect_stderr(io.StringIO()):
            form.start_button.click()
            self.wait_write(window)
            self.settle(6)
        self.assertFalse(window.dialog.is_open, "Esc 도 단추도 안 듣는 닫을 수 없는 대화가 남지 않는다")
        self.assertIsNone(window.post_import_form)

    def test_a_list_read_before_a_write_that_arrives_after_it_is_dropped_and_read_again(self):
        import threading
        gate = threading.Event()

        class Slow(post_fake.FakePostsProvider):
            def load_posts(self, progress, cancelled):
                data = super().load_posts(progress, cancelled)                  # 쓰기 전 모습을 먼저 읽고
                if not gate.is_set():
                    gate.wait(10)                                               # 문이 열릴 때까지 쥐고 있다
                return data

        provider = Slow("empty")
        window = self.make(provider, wait=False)
        ui_offscreen.wait_until(self.app, lambda: window.state.posts.loading, 5)
        form = self.open_import(window)
        form.title_input.setText("방금 가져온 글")
        form.body_input.setPlainText(post_fake.sample_text())
        form.start_button.click()
        self.wait_write(window)
        self.assertEqual(len(provider.projects), 1)
        gate.set()                                                              # 늦게 온 쓰기 전 목록이 이제 도착한다
        ui_offscreen.wait_until(self.app, lambda: window.state.posts.data is not None and not window.state.posts.loading, 10)
        self.settle(8)
        self.assertEqual(len(window.state.posts.data.rows), 1, "쓰기 전 목록은 버리고 다시 읽어 방금 가져온 글이 목록에 있다")

    def test_the_app_closes_at_once_when_the_dialog_is_empty(self):
        window = self.make(post_fake.FakePostsProvider("empty"))
        self.open_import(window)
        self.assertTrue(window.close())

    def test_a_second_dialog_is_not_opened_over_the_first_and_import_is_off_while_writing(self):
        window = self.make(post_fake.FakePostsProvider("empty"))
        form = self.open_import(window)
        self.assertIsNone(window.post_import())
        self.assertIs(window.post_import_form, form)


class PostsQtPreviewTest(Base):
    SCRIPT = "<script>alert(1)</script>"

    def test_the_preview_draws_text_only_and_keeps_a_script_as_visible_characters(self):
        markdown = "## 소제목" + NL + NL + "보통 문단." + NL + NL + "- 항목 하나" + NL + "- 항목 둘" + NL + NL + "> 인용 글" + NL + NL + self.SCRIPT
        window, _provider, _project_id = self.with_post(markdown)
        card = self.ui(window).preview
        blocks = [widget for widget in card.findChildren(QWidget) if widget.property("block")]
        self.assertEqual([widget.property("block") for widget in blocks][:5], ["heading", "paragraph", "list", "quote", "paragraph"])
        shown = [label for label in card.findChildren(UI.Label) if label.plain_text() == self.SCRIPT]
        self.assertEqual(len(shown), 1, "스크립트 글자가 글자 그대로 보인다")
        self.assertIn("&lt;script&gt;", shown[0].text(), "Qt 에는 이스케이프된 글이 넘어간다 — 서식으로 읽히지 않는다")
        self.assertNotIn("<script>", shown[0].text())
        classes = {type(widget).__name__ for widget in window.screen_widget.findChildren(QWidget)}
        self.assertFalse(classes & {"QTextBrowser", "QTextEdit", "QWebEngineView", "QMessageBox"}, classes)

    def test_a_key_shape_in_the_post_is_masked_in_every_label_and_name(self):
        window, _provider, _project_id = self.with_post(post_fake.sample_text() + NL + NL + "앞 " + KEY + " 뒤 문단")
        everything = self.labels(window.screen_widget) + [widget.accessibleName() for widget in window.screen_widget.findChildren(QWidget)] + [widget.toolTip() for widget in window.screen_widget.findChildren(QWidget)]
        self.assertFalse([item for item in everything if KEY[:12] in item or KEY[-12:] in item])
        self.assertTrue([item for item in everything if "가림" in item], "가렸다는 표지는 보인다")

    def test_a_long_post_draws_eighty_blocks_and_says_it_is_cut(self):
        provider = post_fake.FakePostsProvider("empty")
        project_id = provider.add_post("긴 글", (NL + NL).join(f"문단 {number}" for number in range(300)))
        window = self.make(provider)
        self.open_post(window, project_id)
        card = self.ui(window).preview
        self.assertEqual(len([widget for widget in card.findChildren(QWidget) if widget.property("block")]), 80)
        self.assertIn(T["post_preview_cut"].format(total=300, shown=80), self.labels(card))

    def test_the_preview_card_has_its_note_info_and_an_accessible_name(self):
        window, _provider, _project_id = self.with_post()
        card = self.ui(window).preview
        self.assertEqual(card.accessibleName(), T["post_preview_a11y"])
        self.assertIn(T["post_preview_note"], self.labels(card))
        self.assertTrue([item for item in self.labels(card) if item.startswith("본문 ")])

    def test_opening_and_closing_a_post_works_with_the_keyboard_and_returns_focus_to_the_row(self):
        provider = post_fake.FakePostsProvider("empty")
        project_id = self.add_long(provider)
        window = self.make(provider)
        row = self.rows(window)[project_id]
        row.setFocus(Qt.TabFocusReason)
        QTest.keyClick(row, Qt.Key_Return)
        ui_offscreen.wait_until(self.app, lambda: window.state.posts.detail_state == "normal", 10)
        self.settle(8)
        self.assertEqual(window.state.posts.open_id, project_id)
        back = self.ui(window).back_button
        self.assertEqual(back.accessibleName(), T["post_back_a11y"])
        back.click()
        self.settle(6)
        self.assertEqual((window.state.posts.open_id, QApplication.focusWidget().property("focus_key")), (None, "post:row:" + project_id))


class PostsQtReviewTest(Base):
    def test_a_pages_review_asks_for_the_values_first_and_shows_the_three_layers_with_text_badges(self):
        window, provider, _project_id = self.with_post()
        self.buttons(window.screen_widget)[T["post_review_start"]].click()
        self.settle()
        form = window.post_pages_form
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(provider.calls.count("review_post"), 0, "값을 받기 전에는 서비스를 부르지 않는다")
        form.start_button.click()
        self.settle(4)
        self.assertTrue(window.dialog.is_open)
        self.assertTrue(form.problem_labels["category"].isVisibleTo(form))
        self.assertTrue(form.problem_labels["image_url"].isVisibleTo(form))
        self.assertEqual(QApplication.focusWidget(), form.inputs["category"], "문제가 있는 첫 칸으로 포커스가 간다")
        self.assertEqual(provider.calls.count("review_post"), 0)
        for name, value in RAW_FIELDS.items():
            form.inputs[name].setText(value)
        form.lang_strip.chips["en"].click()
        form.lang_strip.chips["ko"].click()
        form.start_button.click()
        self.wait_write(window)
        self.assertFalse(window.dialog.is_open)
        self.assertIsNone(window.post_pages_form)
        sections = {frame.property("post_part"): frame for frame in self.ui(window).review.findChildren(QWidget) if str(frame.property("post_part")).startswith("section:")}
        self.assertEqual(sorted(sections), ["section:gates", "section:health", "section:secret", "section:summary"])
        for key in ("section:gates", "section:health", "section:secret"):
            self.assertEqual(sections[key].badge.text(), T["post_badge_pass"], key)
        self.assertIn(T["post_gate_pass"], self.labels(sections["section:gates"]))

    def test_the_pages_dialog_values_come_back_the_second_time_and_are_wiped_when_closed(self):
        window, _provider, _project_id = self.with_post()
        self.pages_review(window)
        self.buttons(window.screen_widget)[T["post_review_again"]].click()
        self.settle()
        form = window.post_pages_form
        self.assertEqual((form.inputs["category"].text(), form.inputs["image_url"].text()), ("생활", RAW_FIELDS["image_url"]))
        form.cancel_button.click()
        self.settle(4)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual((form.inputs["category"].text(), form.inputs["image_url"].text()), ("", ""), "닫으면 칸이 비워진다")

    def test_values_typed_and_cancelled_come_back_next_time_but_a_key_shaped_set_is_not_remembered(self):
        window, _provider, _project_id = self.with_post()
        review = T["post_review_start"]
        self.buttons(window.screen_widget)[review].click()
        self.settle()
        form = window.post_pages_form
        form.inputs["category"].setText("생활")
        form.inputs["tags"].setText("에너지, 습관")
        form.cancel_button.click()
        self.settle(4)
        self.assertFalse(window.dialog.is_open)
        self.buttons(window.screen_widget)[review].click()
        self.settle()
        again = window.post_pages_form
        self.assertEqual((again.inputs["category"].text(), again.inputs["tags"].text()), ("생활", "에너지, 습관"), "취소해도 쓰던 값은 이 앱을 연 동안 남는다")
        again.inputs["description"].setText("설명 " + KEY)
        window.escape()
        self.settle(4)
        self.assertFalse(window.dialog.is_open)
        self.buttons(window.screen_widget)[review].click()
        self.settle()
        third = window.post_pages_form
        self.assertEqual(third.inputs["description"].text(), "", "키 모양이 든 값은 기억하지 않아 다시 채워지지 않는다")
        self.assertEqual(third.inputs["category"].text(), "생활", "그 전에 기억한 값은 그대로다")
        self.assertNotIn(KEY[:12], repr(window.state.posts.pages_raw))

    def test_a_key_shaped_description_is_refused_and_the_dialog_stays_open_with_the_place_and_kind(self):
        refused = posts.PostFailure(T["post_fail_secret"].format(where="한 줄 설명", kinds="Google API 키"), code="SECRET_SHAPE_FOUND", kind="secret")
        window, _provider, _project_id = self.with_post(fail={"review_post": refused})
        self.buttons(window.screen_widget)[T["post_review_start"]].click()
        self.settle()
        form = window.post_pages_form
        for name, value in {**RAW_FIELDS, "description": "설명 " + KEY}.items():
            form.inputs[name].setText(value)
        form.start_button.click()
        self.wait_write(window)
        self.assertTrue(window.dialog.is_open, "키 모양 거절은 대화를 열어 둔 채 이유만 보인다")
        self.assertIs(window.post_pages_form, form)
        self.assertIn("Google API 키", form.message.plain_text())
        self.assertNotIn(KEY[:12], form.message.plain_text())
        self.assertEqual(form.inputs["description"].text(), "설명 " + KEY, "칸의 글은 그대로다(고칠 수 있게)")
        self.assertNotIn(window.state.posts.open_id, window.state.posts.pages_raw)

    def test_the_pages_dialog_tab_order_follows_the_order_on_the_screen(self):
        window, _provider, _project_id = self.with_post()
        self.buttons(window.screen_widget)[T["post_review_start"]].click()
        self.settle()
        form = window.post_pages_form
        order = [form.inputs["category"], *form.lang_strip.chips.values(), form.inputs["image_url"], form.inputs["tags"], form.inputs["description"], form.cancel_button, form.start_button]
        for first, second in zip(order, order[1:]):
            self.assertIs(self.next_stop(first), second)

    def test_a_blocked_review_shows_block_badges_and_the_approve_button_is_off_with_a_reason(self):
        window, _provider, _project_id = self.with_post("## 짧은 글" + NL + NL + "짧아요." + NL + NL + "<div>태그</div>")
        self.pages_review(window)
        review = self.ui(window).review
        gates = [frame for frame in review.findChildren(QWidget) if frame.property("post_part") == "section:gates"][0]
        self.assertEqual(gates.badge.text(), T["post_badge_block"])
        lines = self.shown_labels(gates)
        self.assertIn(T["post_gate_len_body"], lines)
        self.assertIn(T["post_gate_raw_html"], lines)
        self.assertFalse([line for line in lines if "LEN_BODY" in line], "보이는 줄에는 코드가 없다")
        approve = review.buttons["approve"]
        self.assertFalse(approve.isEnabled())
        self.assertIn(T["post_approve_why_blocked"], self.labels(review))
        approve.click()
        self.settle(4)
        self.assertFalse(window.dialog.is_open, "꺼진 단추는 확인창을 띄우지 않는다")

    def test_a_health_claim_and_a_key_shape_each_block_and_show_only_place_and_kind(self):
        window, _provider, _project_id = self.with_post(post_fake.sample_text() + NL + NL + "이 영양제를 먹으면 통증이 완전히 사라집니다. " + KEY)
        self.pages_review(window)
        review = self.ui(window).review
        by = {frame.property("post_part"): frame for frame in review.findChildren(QWidget) if str(frame.property("post_part")).startswith("section:")}
        self.assertEqual(by["section:health"].badge.text(), T["post_badge_block"])
        self.assertEqual(by["section:secret"].badge.text(), T["post_badge_block"])
        everything = " ".join(self.labels(review))
        self.assertNotIn(KEY[:12], everything)
        self.assertIn("Google API 키", everything)
        self.assertFalse(review.buttons["approve"].isEnabled())

    def test_naver_without_a_profile_says_so_and_with_profiles_reviews_and_blocks_the_same_text_twice(self):
        window, provider, _project_id = self.with_post(profiles=())
        window.post_platform(posts.NAVER_A)
        self.settle()
        review = self.ui(window).review
        self.assertIn(T["post_naver_profile_missing"], [bar.text.plain_text() for bar in review.findChildren(blog_parts.NoticeBar)])
        self.assertFalse(review.buttons["review"].isEnabled())
        window2, provider2, _id2 = self.with_post()
        window2.post_platform(posts.NAVER_A)
        self.settle()
        self.buttons(window2.screen_widget)[T["post_review_start"]].click()
        self.wait_write(window2)
        self.assertEqual(window2.state.posts.detail.platform(posts.NAVER_A).status, "REVIEW_REQUIRED")
        window2.post_platform(posts.NAVER_B)
        self.settle()
        self.buttons(window2.screen_widget)[T["post_review_start"]].click()
        self.wait_write(window2)
        review2 = self.ui(window2).review
        naver = [frame for frame in review2.findChildren(QWidget) if frame.property("post_part") == "section:naver"][0]
        self.assertEqual(naver.badge.text(), T["post_badge_block"])
        self.assertFalse(review2.buttons["approve"].isEnabled())

    def test_the_platform_chips_have_names_with_state_and_pick_the_platform(self):
        window, _provider, _project_id = self.with_post()
        review = self.ui(window).review
        self.assertEqual(list(review.chips), list(posts.PLATFORMS))
        self.assertEqual(review.chips[posts.PAGES].accessibleName(), T["post_chip_a11y"].format(name="GitHub Pages", status="시작 전"))
        review.chips[posts.NAVER_B].click()
        self.settle()
        self.assertEqual(window.state.posts.platform, posts.NAVER_B)
        self.assertIn(T["post_status_line"].format(status="시작 전"), self.labels(self.ui(window).review))

    def test_a_review_that_is_running_shows_the_working_sentence_and_turns_the_buttons_off(self):
        import threading
        gate = threading.Event()

        class Gated(post_fake.FakePostsProvider):
            def review_post(self, request, progress, cancelled):
                gate.wait(10)
                return super().review_post(request, progress, cancelled)

        provider = Gated("empty")
        project_id = provider.add_post("글", post_fake.sample_text())
        window = self.make(provider)
        self.open_post(window, project_id)
        self.buttons(window.screen_widget)[T["post_review_start"]].click()
        self.settle()
        form = window.post_pages_form
        for name, value in RAW_FIELDS.items():
            form.inputs[name].setText(value)
        form.start_button.click()
        self.settle(6)
        self.assertTrue(window.state.posts.busy)
        self.assertFalse(form.start_button.isEnabled())
        self.assertEqual(form.working.plain_text(), T["post_res_running"])
        self.assertIn(T["post_res_running"], self.labels(window.screen_widget))
        gate.set()
        self.wait_write(window)


class PostsQtApproveTest(Base):
    def reviewed(self, markdown=None):
        window, provider, project_id = self.with_post(markdown)
        self.pages_review(window)
        return window, provider, project_id

    def test_approve_opens_a_confirm_first_with_cancel_focused_and_the_not_publishing_sentence(self):
        window, provider, project_id = self.reviewed()
        approve = self.ui(window).review.buttons["approve"]
        self.assertTrue(approve.isEnabled())
        self.assertEqual(approve.property("kind"), "primary")
        approve.click()
        self.settle()
        self.assertTrue(window.dialog.is_open)
        self.assertEqual(provider.calls.count("approve_post"), 0, "확인창이 뜬 것만으로는 승인하지 않는다")
        body = window.dialog.findChild(UI.DialogBody).plain_text()
        self.assertIn("어디에도 올리지 않아요", body)
        self.assertIn("GitHub Pages", body)
        self.assertEqual(window.dialog_default.text(), T["post_confirm_cancel"])
        self.assertEqual(QApplication.focusWidget(), window.dialog_default)
        QTest.keyClick(window.dialog_default, Qt.Key_Return)
        self.settle(4)
        self.assertFalse(window.dialog.is_open)
        self.assertEqual(provider.calls.count("approve_post"), 0, "Enter 를 잘못 눌러도 승인되지 않는다")
        self.assertEqual(window.state.posts.detail.platform(posts.PAGES).status, "REVIEW_REQUIRED")
        self.assertIsNone(window.state.posts.approve_asked, "취소하면 확인했다는 표시도 거둔다")

    def test_confirming_approves_shows_the_notice_and_a_revoke_button_that_goes_back(self):
        window, provider, project_id = self.reviewed()
        self.ui(window).review.buttons["approve"].click()
        self.settle()
        self.dialog_button(window, T["post_confirm_ok"]).click()
        self.wait_write(window)
        self.assertEqual(provider.projects[project_id].variants[posts.PAGES].status, "APPROVED")
        self.assertIn(T["post_done_approved"], [bar.text.plain_text() for bar in window.screen_widget.findChildren(blog_parts.NoticeBar)])
        review = self.ui(window).review
        self.assertNotIn("approve", review.buttons)
        self.assertEqual(review.buttons["revoke"].accessibleName(), T["post_revoke_a11y"].format(name="GitHub Pages"))
        self.assertIn(T["post_review_again_note"], self.labels(review))
        self.assertEqual(self.primary_buttons(review), [], "승인한 뒤에는 주요 단추가 없다")
        review.buttons["revoke"].click()
        self.wait_write(window)
        self.assertEqual(provider.projects[project_id].variants[posts.PAGES].status, "REVIEW_REQUIRED")
        self.assertIn(T["post_done_revoked"], [bar.text.plain_text() for bar in window.screen_widget.findChildren(blog_parts.NoticeBar)])

    def test_a_post_changed_elsewhere_cannot_be_approved_and_the_screen_reads_it_again(self):
        window, provider, project_id = self.reviewed()
        self.ui(window).review.buttons["approve"].click()
        self.settle()
        provider.edit(project_id, source_content="## 그 사이 고침" + NL + NL + post_fake.sample_text())
        self.dialog_button(window, T["post_confirm_ok"]).click()
        self.wait_write(window)
        ui_offscreen.wait_until(self.app, lambda: window.state.posts.detail_state == "normal" and not window.state.posts.loading, 10)
        self.settle(8)
        self.assertNotEqual(provider.projects[project_id].variants[posts.PAGES].status, "APPROVED")
        self.assertIn(T["post_fail_stale"], [bar.text.plain_text() for bar in window.screen_widget.findChildren(blog_parts.NoticeBar)])
        self.assertNotIn("approve", self.ui(window).review.buttons, "다시 검토하기 전에는 승인 단추 자리가 없다")

    def test_an_old_result_after_a_reload_must_be_read_again_before_approving(self):
        window, provider, project_id = self.reviewed()
        window.go("home")
        window.go("posts")
        ui_offscreen.wait_until(self.app, lambda: window.state.posts.detail_state == "normal" and not window.state.posts.loading, 10)
        self.settle(8)
        self.assertEqual(window.state.posts.review.project_id, project_id, "이 앱을 연 동안 받은 결과는 그대로 있다")
        self.assertTrue(self.ui(window).review.buttons["approve"].isEnabled())
        window.state.posts.review = None
        window.render()
        self.settle()
        review = self.ui(window).review
        self.assertFalse(review.buttons["approve"].isEnabled())
        self.assertIn(T["post_res_lost"], self.labels(review))

    def test_nothing_is_written_while_only_looking_at_a_review_result(self):
        window, provider, project_id = self.reviewed()
        before = list(provider.calls)
        for _ in range(3):
            window.render()
            self.settle(2)
        window.post_platform(posts.NAVER_A)
        window.post_platform(posts.PAGES)
        self.assertEqual(provider.calls, before)


class PostsQtLayoutTest(Base):
    def check_window(self, window, size):
        scroll = window.scroll
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, f"{size}: 가로 스크롤이 없다")
        body = window.screen_widget
        for button in body.findChildren(QPushButton):
            if not button.isVisibleTo(body.window()) or not button.text():
                continue
            right = button.mapTo(window, button.rect().topRight()).x()
            self.assertLessEqual(right, window.width(), f"{size}: {button.text()} 단추가 창 밖에 있다")
            self.assertGreaterEqual(button.height(), 34, f"{size}: {button.text()} 누르는 칸이 너무 작다")

    def test_list_detail_review_and_both_dialogs_fit_in_every_required_size(self):
        for size in SIZES:
            with self.subTest(size=size):
                provider = post_fake.FakePostsProvider("empty")
                project_id = provider.add_post("글 하나 " + "아주 긴 제목 " * 8, post_fake.sample_text() + NL + NL + "- 항목" * 20)
                window = self.make(provider, size=size)
                self.check_window(window, size)
                self.open_post(window, project_id)
                self.check_window(window, size)
                self.pages_review(window)
                self.check_window(window, size)
                self.buttons(window.screen_widget)[T["post_review_again"]].click()
                self.settle()
                form = window.post_pages_form
                dialog = window.dialog
                self.assertLessEqual(dialog.width(), window.width(), size)
                self.assertLessEqual(dialog.height(), window.height(), size)
                self.assertGreaterEqual(dialog.y(), 0, size)
                form.cancel_button.click()
                self.settle(4)
                window.post_close()
                self.settle(4)
                self.ui(window).import_button.click()
                self.settle()
                self.assertLessEqual(window.dialog.width(), window.width(), size)
                self.assertLessEqual(window.dialog.height(), window.height(), size)
                window.escape()
                self.settle(4)
                window.close()

    def test_every_button_input_and_group_has_an_accessible_name(self):
        window, _provider, _project_id = self.with_post()
        self.pages_review(window)
        for root in (window.screen_widget,):
            for button in root.findChildren(QAbstractButton):
                if button.isVisibleTo(window):
                    self.assertTrue(button.accessibleName() or button.text(), f"접근 이름이 없다: {button.property('focus_key')}")
        self.buttons(window.screen_widget)[T["post_review_again"]].click()
        self.settle()
        for widget in window.post_pages_form.findChildren(QWidget):
            if isinstance(widget, (QAbstractButton,)) or type(widget).__name__ in ("QLineEdit", "PasteBox"):
                if widget.isVisibleTo(window.post_pages_form):
                    self.assertTrue(widget.accessibleName() or getattr(widget, "text", lambda: "")(), type(widget).__name__)

    def test_tab_stays_inside_the_open_dialog(self):
        window = self.make(post_fake.FakePostsProvider("empty"))
        self.ui(window).import_button.click()
        self.settle()
        form = window.post_import_form
        outside = [widget for widget in window.screen_widget.findChildren(QWidget) if widget.focusPolicy() != Qt.NoFocus]
        self.assertEqual(outside, [], "대화가 열려 있는 동안 화면 쪽에는 Tab 정거장이 없다")
        seen = set()
        for _ in range(12):
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_Tab)
            self.settle(1)
            widget = QApplication.focusWidget()
            if widget is not None:
                seen.add(widget)
        self.assertTrue(all(form.isAncestorOf(widget) or widget is form for widget in seen), "포커스가 대화 밖으로 나가지 않는다")


class PostsQtRealServiceTest(Base):
    """실제 서비스(임시 데이터 폴더)로 화면에서 끝까지 — 읽기만 하는 동안 한 바이트도 안 바뀌고, 쓰는 일은 데이터 폴더 안에서만 일어난다."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = support.make_ctx(self.tmp.name, repo="")
        self.provider = posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: self.ctx)
        self.root = Path(self.tmp.name)

    def stats(self, root):
        import hashlib
        return {path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) for path in sorted(Path(root).rglob("*")) if path.is_file()}

    def test_import_review_approve_and_revoke_through_the_screen_with_the_real_service(self):
        window = self.make(self.provider)
        self.assertEqual(len(self.rows(window)), 0)
        self.assertIn(T["post_empty_title"], self.labels(window.screen_widget))
        outside = {path: data for path, data in support.tree_snapshot(self.root).items() if not path.startswith("data/")}
        window.post_import()
        self.settle()
        form = window.post_import_form
        form.title_input.setText("에너지 절약 습관")
        form.body_input.setPlainText(support.ko_text())
        form.start_button.click()
        self.wait_write(window)
        self.assertEqual(window.state.posts.view()["mode"], "detail")
        self.assertEqual([row.title for row in projects_list(self.ctx)], ["에너지 절약 습관"])
        self.pages_review(window, category="경제·일")
        self.assertEqual(support.status_of(self.ctx, window.state.posts.open_id), "REVIEW_REQUIRED")
        self.ui(window).review.buttons["approve"].click()
        self.settle()
        self.dialog_button(window, T["post_confirm_ok"]).click()
        self.wait_write(window)
        self.assertEqual(support.status_of(self.ctx, window.state.posts.open_id), "APPROVED")
        self.ui(window).review.buttons["revoke"].click()
        self.wait_write(window)
        self.assertEqual(support.status_of(self.ctx, window.state.posts.open_id), "REVIEW_REQUIRED")
        after = {path: data for path, data in support.tree_snapshot(self.root).items() if not path.startswith("data/")}
        self.assertEqual(after, outside, "데이터 폴더 밖은 한 바이트도 안 바뀐다")
        inside = sorted(path.relative_to(self.ctx.workspace.root).as_posix() for path in self.ctx.workspace.root.rglob("*") if path.is_file())
        self.assertFalse([path for path in inside if path.startswith(("publish", "backups"))], inside)

    def test_only_looking_never_changes_a_byte(self):
        first = self.provider.import_post(posts.ImportRequest("markdown", "글", support.ko_text()), lambda *a: None, lambda: False).detail
        before = self.stats(self.ctx.workspace.root)
        window = self.make(self.provider)
        self.open_post(window, first.project_id)
        window.post_platform(posts.NAVER_A)
        window.post_platform(posts.PAGES)
        window.go("home")
        window.go("posts")
        ui_offscreen.wait_until(self.app, lambda: not window.state.posts.loading, 10)
        self.settle(6)
        self.assertEqual(self.stats(self.ctx.workspace.root), before)

    def test_a_key_shaped_post_is_refused_by_the_service_and_the_screen_shows_place_and_kind(self):
        window = self.make(self.provider)
        window.post_import()
        self.settle()
        form = window.post_import_form
        form.title_input.setText("키 글")
        form.body_input.setPlainText("첫 줄" + NL + "둘째 " + KEY)
        form.start_button.click()
        self.wait_write(window)
        self.assertTrue(window.dialog.is_open)
        self.assertIn("본문 2번째 줄", form.message.plain_text())
        self.assertNotIn(KEY[:10], form.message.plain_text())
        self.assertFalse(self.ctx.workspace.store_path.exists() and projects_list(self.ctx))


def projects_list(ctx):
    from chanceblog_desktop.service import projects
    return projects.list_projects(ctx)


if __name__ == "__main__":
    unittest.main()
