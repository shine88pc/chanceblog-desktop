"""앱 전체 화면에서 채널(블로그 슬롯)이 **블로그 관리의 별명**으로 불리는지 — PySide6 시험(창을 화면에 띄우지 않고 offscreen). **PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_channel_names`).
blogsel-2(D-510): Seed 관리의 소속 선택·주제 후보·초안 작성·홈이 `네이버 A`·`블로그 A` 같은 고정 이름 대신 블로그 관리의 별명(없으면 종류 + 번호)을 쓴다.

지키는 것:
  1) 앱의 어느 화면(홈·주제 후보·Seed 관리·블로그 관리·설정·초안 작성)의 보이는 글·접근 이름·툴팁에도 옛 고정 이름(`네이버 A`·`Blogger 한글`·`블로그 A` …)이 없다 — 별명을 읽기 전(기본 이름)에도, 읽은 뒤에도.
  2) 블로그 관리에서 별명을 저장하면 다른 화면이 그 별명을 쓴다. 앱이 열릴 때 블로그 정보를 한 번 읽어(읽기만) 블로그 관리 화면을 열지 않아도 별명이 보인다.
  3) 이름은 보이는 글뿐이다 — 채널 열쇠(`naver_a`)·저장 파일은 그대로이고 이 시험은 파일에 아무것도 쓰지 않는다(가짜 공급자).
"""
import dataclasses
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from test_ui_qt_blogs import HAVE, Base  # noqa: E402,I001
from test_ui_qt_drafts import Base as DraftsBase  # noqa: E402,I001

from chanceblog_desktop.ui.core import blogs, services  # noqa: E402
from chanceblog_desktop.ui.core import channel_names as cn  # noqa: E402

if HAVE:
    import ui_offscreen
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from chanceblog_desktop.ui.qt import shell as shell_module
    from test_ui_qt_blogs_add import screen_texts

SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731

OLD_NAMES = re.compile(r"네이버 [AB]\b|Blogger (?:한글|영문)|블로그 [AB]\b|Naver [AB]|naver_[ab]|blogger_(?:ko|en)|github_pages")
PAGES = ("home", "topics", "seed", "blogs", "settings")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class AppWideNamesTest(Base):
    def visit(self, window, page):
        window.go(page)
        if page == "home":
            window.reload()                                                                    # 시험 창은 앱이 열릴 때의 읽기(autoload)를 하지 않는다 — 홈을 직접 읽는다
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading" and window.state.blogs.state != "loading" and window.state.seeds.state != "loading" and window.state.candidates.state != "loading", 15)
        self.settle(10)
        return screen_texts(window)

    def old_names_in(self, window):
        found = []
        for page in PAGES:
            for item in self.visit(window, page):
                if OLD_NAMES.search(item):
                    found.append((page, item[:80]))
        return found

    def test_no_page_of_the_app_names_a_channel_with_an_old_fixed_name_before_and_after_the_aliases_are_read(self):
        window = self.make(page=None)
        self.assertEqual(cn.current(), cn.DEFAULT, "별명을 읽기 전에는 기본 이름")
        self.assertEqual(self.old_names_in(window), [], "기본 이름일 때 옛 고정 이름이 남았다")
        self.visit(window, "blogs")                                                            # 블로그 정보를 읽는다
        self.assertEqual(cn.label("naver_a"), "예시 별명")
        self.assertEqual(self.old_names_in(window), [], "별명을 읽은 뒤에 옛 고정 이름이 남았다")

    def test_the_alias_saved_in_the_blog_screen_is_the_name_the_other_screens_use(self):
        window = self.make()
        self.type_into(window, "alias", "새 맛집 별명")
        self.action(window, "save").click()
        self.wait_write(window)
        self.assertEqual(cn.label("naver_a"), "새 맛집 별명", "저장하면 이름이 바로 바뀐다")
        for page, expected in (("home", "새 맛집 별명 추천"), ("seed", "새 맛집 별명"), ("topics", "새 맛집 별명")):
            texts = " | ".join(self.visit(window, page))
            self.assertIn(expected, texts, page)
            self.assertNotIn("예시 별명", texts, f"{page}: 옛 별명이 남지 않는다")

    def test_the_aliases_are_read_when_the_app_opens_so_the_other_screens_show_them_without_visiting_the_blog_screen(self):
        window = self.make(page=None)
        self.assertEqual(window.state.page, "home")
        window.reload()
        ui_offscreen.wait_until(self.app, lambda: window.state.list_state != "loading", 10)
        self.settle(6)
        self.assertNotIn("예시 별명 추천", " | ".join(screen_texts(window)), "아직 별명을 읽기 전의 홈")
        window._load_blog_names()
        ui_offscreen.wait_until(self.app, lambda: window.state.blogs.state == "normal", 10)
        self.settle(8)
        self.assertEqual(cn.label("naver_a"), "예시 별명")
        texts = " | ".join(screen_texts(window))
        self.assertIn("예시 별명 추천", texts, "홈이 다시 그려져 별명을 쓴다")
        self.assertEqual([item for item in screen_texts(window) if OLD_NAMES.search(item)], [])

    def test_a_backup_restore_reads_the_aliases_again_so_no_screen_keeps_the_old_names(self):
        """검증 Q2-2: 복원은 이 앱이 블로그 프로필 파일(`channel_profiles.json`)을 바꾸는 길이다 — 복원이 끝나면 다른 화면의 채널 이름(별명)도 새로 읽는다(옛 별명이 남지 않는다)."""
        provider = blogs.FakeBlogsProvider()
        window = self.make(provider, page=None)
        window._load_blog_names()
        ui_offscreen.wait_until(self.app, lambda: cn.label("naver_a") == "예시 별명", 10)
        provider.slots["naver_a"] = dataclasses.replace(provider.slots["naver_a"], alias="복원된 별명")                 # 복원이 파일을 바꾼 것과 같다
        with mock.patch.object(window, "_backups", return_value=mock.Mock()), mock.patch.object(window, "_reload_after_backups"), mock.patch.object(window, "_render_backups"), \
                mock.patch.object(window, "_give_backup_focus"), mock.patch.object(window, "reload"):
            window._show_backups_written(types.SimpleNamespace(action="created"))
            self.settle(6)
            self.assertEqual(cn.label("naver_a"), "예시 별명", "복원이 아닌 백업 만들기는 이름을 다시 읽지 않는다")
            window._show_backups_written(types.SimpleNamespace(action="restored"))
        ui_offscreen.wait_until(self.app, lambda: cn.label("naver_a") == "복원된 별명", 10)
        self.assertEqual(cn.label("naver_a"), "복원된 별명")

    def test_the_app_reads_the_aliases_by_itself_when_it_starts_with_the_automatic_read_on(self):
        """검증 Q2-6(Q14): 시험 창은 늘 `autoload=False` 로 열어 앱이 열릴 때 별명을 읽는 길(`QTimer.singleShot(0, _load_blog_names)`)을 안 탔다 — 이 시험은 `autoload=True` 로 연다."""
        window = shell_module.AppShell(services.FakeHomeProvider(), blogs=blogs.FakeBlogsProvider(), autoload=True)
        window.resize(1366, 768)
        window.show()
        self.addCleanup(self.close_window, window)
        self.assertEqual(cn.current(), cn.DEFAULT, "열린 직후에는 아직 별명이 없다")
        ui_offscreen.wait_until(self.app, lambda: cn.label("naver_a") == "예시 별명", 15)
        self.assertEqual(cn.label("naver_a"), "예시 별명", "블로그 관리를 열지 않아도 앱이 열릴 때 별명을 읽었다")

    def test_the_names_stay_when_a_later_read_of_the_blog_data_fails(self):
        """검증 S2-1·S2-2: 블로그 정보를 다시 읽다 실패해도 이미 읽은 별명은 그대로다(이전에 보이던 내용은 지우지 않는다) — 이름을 기본으로 되돌리거나 화면이 옛 고정 이름으로 돌아가지 않는다."""
        provider = blogs.FakeBlogsProvider()
        window = self.make(provider, page=None)
        window._load_blog_names()
        ui_offscreen.wait_until(self.app, lambda: cn.label("naver_a") == "예시 별명", 10)
        provider.scenario = "error"                                                                    # 다음 읽기는 실패한다
        window._load_blog_names()
        ui_offscreen.wait_until(self.app, lambda: window.state.blogs.state == "error", 10)
        self.settle(4)
        self.assertEqual(window.state.blogs.state, "error")
        self.assertEqual(cn.label("naver_a"), "예시 별명", "읽기가 실패해도 이름은 그대로다")
        window._names_changed()
        self.assertEqual(cn.label("naver_a"), "예시 별명", "이름을 다시 정해도(읽어 둔 자료가 남아 있다) 그대로다")
        self.assertEqual([item for item in screen_texts(window) if OLD_NAMES.search(item)], [])

    def test_a_closed_window_gives_the_names_back_so_the_next_state_starts_plain(self):
        window = self.make()
        self.assertEqual(cn.label("naver_a"), "예시 별명")
        self.close_window(window)
        self.assertEqual(cn.current(), cn.DEFAULT)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class DraftsNamesTest(DraftsBase):
    def test_the_draft_screen_names_the_blogs_with_the_aliases_and_has_no_old_fixed_name(self):
        window = self.drafted()
        provider = window.state.blogs.provider
        window.state.blogs.apply_loaded(provider.load_blogs(lambda *a: None, lambda: False))
        window._names_changed()
        self.settle(8)
        texts = screen_texts(window)
        joined = " | ".join(texts)
        self.assertIn("예시 별명", joined, "블로그 칩이 별명을 쓴다")
        self.assertEqual([item for item in texts if OLD_NAMES.search(item)], [])
        self.addCleanup(cn.use, None)

    def test_a_name_change_never_redraws_the_drafts_screen_while_it_holds_unsaved_edits(self):
        """검증 Q2-6(Q18): 초안에 고친 내용이 있으면 이름이 바뀌어도 화면을 다시 그리지 않는다(입력을 지킨다 — D-510 ③) — 이름은 다음에 그릴 때 바뀐다."""
        window = self.drafted()
        ui = self.ui(window)
        editor, page = ui.editor, window.screen_widget
        editor.setFocus(Qt.OtherFocusReason)
        QTest.keyClicks(editor, "abc")
        self.settle(2)
        self.assertTrue(window.state.drafts.has_unsaved())
        provider = window.state.blogs.provider
        provider.slots["naver_a"] = dataclasses.replace(provider.slots["naver_a"], alias="바뀐 별명")
        window.state.blogs.apply_loaded(provider.load_blogs(SAFE, NEVER))
        window._names_changed()
        self.settle(4)
        self.addCleanup(cn.use, None)
        self.assertEqual(cn.label("naver_a"), "바뀐 별명", "이름은 바뀌었다")
        self.assertIs(window.screen_widget, page, "고친 초안이 있으면 화면을 다시 그리지 않는다")
        self.assertIs(self.ui(window).editor, editor)
        self.assertIn("abc", editor.toPlainText())


if __name__ == "__main__":
    unittest.main()
