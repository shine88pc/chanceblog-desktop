"""참고 글 보관함의 화면 규칙(`ui/core/references_view.py`, 결정 D-490) 시험 — PySide6 를 쓰지 않는다(그래서 CI 의 모든 칸에서 돈다).

지키는 것: 열기·목록·선택·편집 중(저장 안 한 변경 표시)·저장(새 글·고치기)·파일에서 올리기·지우기 확인(두 단계)·낡은 결과 버리기(세대 번호)·글이 상태에 남지 않음(지문뿐)·문구 규칙·서비스 한도와 같은 상수.
"""
import ast
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import service_support as ss  # noqa: E402,F401  (vendor 경로를 올린다)
from chanceblog_desktop.service import own_posts, references  # noqa: E402
from chanceblog_desktop.ui.core import references_view as rv  # noqa: E402
from chanceblog_desktop.ui.core.references_text import REF_T  # noqa: E402
from chanceblog_desktop.ui.core.text import FORBIDDEN, T  # noqa: E402

SOURCE = ROOT / "src" / "chanceblog_desktop" / "ui" / "core" / "references_view.py"
TITLE_MARK, BODY_MARK = "UNIQ-TITLE-ui9k-제목", "UNIQ-BODY-ui3m-본문"
ITEMS = {"aaaaaaaa": ["첫 글", "첫 본문", "2026-11-15T01:00:00Z"], "bbbbbbbb": ["둘째 글", "둘째 본문 입니다", "2026-11-15T02:00:00Z"]}


def make(items=None, **kwargs):
    provider = rv.FakeReferencesProvider(ITEMS if items is None else items, **kwargs)
    library = rv.ReferenceLibrary(provider)
    return library, provider


def state_text(library):
    """상태 객체가 쥔 모든 값의 글(지문·번호·문장)."""
    return repr(vars(library).get("rows")) + repr({key: value for key, value in vars(library).items() if key not in ("provider", "rows")})


class ConstantsTest(unittest.TestCase):
    def test_the_limits_match_the_service(self):
        self.assertEqual((rv.MAX_REFERENCES, rv.TITLE_MAX, rv.BODY_MAX), (references.MAX_REFERENCES, references.TITLE_MAX, references.MAX_BODY_CHARS))
        self.assertEqual(rv.BODY_MAX, own_posts.MAX_TEXT_CHARS)
        self.assertEqual(rv.FILE_SUFFIXES, own_posts.ALLOWED_SUFFIXES)

    def test_the_texts_are_in_t_and_follow_the_text_rules(self):
        for key, value in REF_T.items():
            self.assertIn(key, T)
            self.assertEqual(T[key], value)
            self.assertTrue(key.startswith("ref_"))
            self.assertNotIn(chr(0x7E), value, key)
            self.assertNotRegex(value, r"https?://")
            for word in FORBIDDEN:
                self.assertNotIn(word, value, key)
        limits = T["ref_limits"].format(n=50, title=80, body=100000)
        self.assertIn("50개", limits)
        self.assertIn("80자", limits)
        self.assertIn("100000자", limits)

    def test_when_text_is_korean_time_and_unreadable_stamps_are_empty(self):
        self.assertEqual(rv.when_text("2026-11-15T13:05:00Z"), "2026-11-15 22:05")
        self.assertEqual(rv.when_text("2026-11-15T20:00:00Z"), "2026-11-16 05:00")
        for bad in ("", "어제", None, "2026-11-15 13:05:00"):
            self.assertEqual(rv.when_text(bad), "")


class OpenListTest(unittest.TestCase):
    def test_opening_reads_the_list_newest_first_and_the_folder(self):
        library, provider = make(folder="가짜 폴더 위치")
        self.assertEqual(library.open(), "loaded")
        view = library.view()
        self.assertEqual([row["id"] for row in view["list"]["rows"]], ["bbbbbbbb", "aaaaaaaa"])
        self.assertEqual(view["list"]["count"], "2개 보관 중")
        self.assertEqual(view["folder"]["text"], "가짜 폴더 위치")
        self.assertEqual((view["list"]["empty"], view["list"]["loading"], view["list"]["skipped"]), ("", "", ""))
        self.assertEqual(view["editor"]["mode"], "new")
        self.assertFalse(view["buttons"]["delete"]["enabled"])
        self.assertIn("list", provider.calls)

    def test_an_empty_vault_says_so_and_skipped_files_are_only_counted(self):
        library, _ = make(items={}, skipped=3)
        library.open()
        view = library.view()
        self.assertEqual(view["list"]["empty"], T["ref_list_empty"])
        self.assertEqual(view["list"]["skipped"], T["ref_skipped"].format(n=3))
        self.assertEqual(view["list"]["rows"], [])

    def test_before_the_list_arrives_it_says_loading(self):
        library, _ = make()
        library.is_open = True
        self.assertEqual(library.view()["list"]["loading"], T["ref_list_loading"])

    def test_a_failed_list_shows_the_fixed_sentence_and_nothing_else(self):
        library, _ = make(refuse=("list",))
        self.assertEqual(library.open(), "failed")
        self.assertEqual(library.view()["message"], "가짜 공급자의 고정 거절 문장이에요")

    def test_closed_library_does_nothing(self):
        library, provider = make()
        self.assertEqual((library.refresh(), library.select("aaaaaaaa")[0], library.new_post(), library.save("a", "b"), library.add_file("x"), library.ask_delete(), library.advance_delete()),
                         ("closed", "closed", "closed", "closed", "closed", "closed", "closed"))
        self.assertEqual(provider.calls, [])

    def test_row_titles_are_masked_before_they_reach_the_screen(self):
        key = ss.KEY
        library, _ = make(items={"aaaaaaaa": [f"제목 {key} 끝", "본문", "2026-11-15T01:00:00Z"]})
        library.open()
        view = library.view()
        self.assertNotIn(key, repr(view))


class SelectEditTest(unittest.TestCase):
    def test_selecting_opens_the_post_and_makes_it_the_clean_open_post(self):
        library, _ = make()
        library.open()
        status, opened = library.select("aaaaaaaa")
        self.assertEqual((status, opened.title, opened.body), ("opened", "첫 글", "첫 본문"))
        view = library.view()
        self.assertEqual((view["editor"]["mode"], view["editor"]["dirty"], view["editor"]["state"]), ("edit", False, T["ref_clean"]))
        self.assertTrue(view["buttons"]["delete"]["enabled"])
        self.assertEqual([row["selected"] for row in view["list"]["rows"]], [False, True])

    def test_editing_marks_unsaved_changes_by_comparing_fingerprints_only(self):
        library, _ = make()
        library.open()
        library.select("aaaaaaaa")
        self.assertTrue(library.edited("첫 글", "첫 본문 고침"))
        self.assertEqual(library.view()["editor"]["state"], T["ref_dirty"])
        self.assertFalse(library.edited("첫 글", "첫 본문"), "원래대로 돌아오면 표시가 사라진다")
        library.edited("첫 글" + TITLE_MARK, BODY_MARK)
        self.assertNotIn(TITLE_MARK, state_text(library))
        self.assertNotIn(BODY_MARK, state_text(library))

    def test_selecting_or_new_with_unsaved_changes_needs_the_discard_confirmation(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        library.edited("고친 제목", "고친 본문")
        calls = len(provider.calls)
        self.assertEqual(library.select("bbbbbbbb"), ("dirty", None))
        self.assertEqual(library.new_post(), "dirty")
        self.assertEqual(len(provider.calls), calls, "확인 전에는 공급자도 부르지 않는다")
        self.assertEqual(library.current, "aaaaaaaa")
        self.assertEqual(library.select("bbbbbbbb", discard=True)[0], "opened")
        self.assertEqual(library.current, "bbbbbbbb")
        library.edited("x", "y")
        self.assertEqual(library.new_post(discard=True), "ready")
        self.assertEqual((library.mode, library.current, library.dirty), ("new", None, False))

    def test_opening_a_missing_post_fails_with_the_fixed_sentence(self):
        library, _ = make()
        library.open()
        status, opened = library.select("zzzzzzzz")
        self.assertEqual((status, opened), ("failed", None))
        self.assertEqual(library.view()["message"], "가짜 공급자의 고정 거절 문장이에요")
        self.assertEqual(library.current, None)

    def test_saving_a_new_post_adds_it_refreshes_the_list_and_opens_it(self):
        library, provider = make()
        library.open()
        library.new_post()
        self.assertEqual(library.save("새 제목", "새 본문입니다"), "saved")
        view = library.view()
        self.assertEqual(len(view["list"]["rows"]), 3)
        self.assertEqual((library.mode, view["editor"]["dirty"], view["notice"]), ("edit", False, T["ref_done_saved"]))
        self.assertEqual(provider.calls.count("add"), 1)
        self.assertNotIn("새 본문입니다", state_text(library))
        self.assertNotIn("새 제목", state_text(library))

    def test_saving_an_open_post_overwrites_it(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        library.edited("고친 제목", "고친 본문")
        self.assertEqual(library.save("고친 제목", "고친 본문"), "saved")
        self.assertEqual(provider.items["aaaaaaaa"][:2], ["고친 제목", "고친 본문"])
        self.assertEqual(provider.calls.count("save"), 1)
        self.assertFalse(library.dirty)
        self.assertEqual(library.view()["list"]["rows"][0]["id"], "aaaaaaaa", "고친 글이 맨 위로 온다")

    def test_a_refused_save_keeps_the_open_post_and_the_dirty_mark(self):
        library, _ = make()
        library.open()
        library.select("aaaaaaaa")
        library.edited("", "본문")
        self.assertEqual(library.save("", "본문"), "refused")
        self.assertEqual(library.view()["message"], "가짜 공급자의 고정 거절 문장이에요")
        self.assertEqual((library.current, library.dirty), ("aaaaaaaa", True))

    def test_the_limits_are_enforced_by_the_provider_and_shown_as_a_fixed_sentence(self):
        library, provider = make()
        library.open()
        library.new_post()
        for title, body in (("가" * 81, "본문"), ("제목", "나" * 100_001), ("  ", "본문"), ("제목", "  ")):
            self.assertEqual(library.save(title, body), "refused")
        self.assertEqual(len(provider.items), 2)
        full = {f"id{n:06d}": [f"글 {n}", "본문", "2026-11-15T01:00:00Z"] for n in range(50)}
        library, provider = make(items=full)
        library.open()
        library.new_post()
        self.assertEqual(library.save("쉰한째", "본문"), "refused")
        self.assertEqual(len(provider.items), 50)

    def test_the_view_counts_the_body_without_holding_it(self):
        library, _ = make()
        library.open()
        view = library.view(body_chars=1234)
        self.assertEqual(view["editor"]["count"], "1234자")
        self.assertIn("1234", view["editor"]["count_a11y"])


class FileAddTest(unittest.TestCase):
    def test_adding_a_file_adds_it_to_the_list_and_keeps_the_open_post(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        self.assertEqual(library.add_file("선택한 위치.txt", "  파일 제목 "), "added")
        self.assertEqual(provider.calls.count("add_file"), 1)
        self.assertEqual(len(library.view()["list"]["rows"]), 3)
        self.assertEqual(library.current, "aaaaaaaa")
        self.assertEqual(library.view()["notice"], T["ref_done_file"])

    def test_a_cancelled_picker_never_calls_the_provider(self):
        library, provider = make()
        library.open()
        for empty in ("", None):
            self.assertEqual(library.add_file(empty), "cancelled")
        self.assertNotIn("add_file", provider.calls)

    def test_a_refused_file_shows_the_fixed_sentence_and_does_not_keep_the_location(self):
        library, _ = make(refuse=("add_file",))
        library.open()
        self.assertEqual(library.add_file("비밀 위치/내 글.txt"), "refused")
        self.assertEqual(library.view()["message"], "가짜 공급자의 고정 거절 문장이에요")
        self.assertNotIn("비밀 위치", state_text(library))
        self.assertNotIn("비밀 위치", repr(library.view()))

    def test_a_cp949_file_adds_the_reading_note(self):
        library, provider = make()
        provider.add_file = lambda path, title: (provider.add(title or "가져온 글", "본문"), True)
        library.open()
        self.assertEqual(library.add_file("a.txt"), "added")
        self.assertIn(T["ref_note_cp949"], library.view()["notice"])


class StaleResultTest(unittest.TestCase):
    def test_a_result_that_arrives_after_closing_or_a_newer_start_is_dropped(self):
        library, _ = make()
        library.open()
        ticket = library.begin()
        library.close()
        self.assertFalse(library.apply_list(ticket, rv.RefListing((rv.RefRow("zzzzzzzz", "낡은", 1, "2026-11-15T01:00:00Z"),))))
        self.assertEqual(library.rows, ())
        library.open()
        old = library.begin()
        newer = library.begin()
        self.assertFalse(library.apply_opened(old, rv.OpenedRef("aaaaaaaa", "낡은 글", "낡은 본문")))
        self.assertEqual(library.current, None)
        self.assertTrue(library.apply_opened(newer, rv.OpenedRef("aaaaaaaa", "새 글", "새 본문")))
        self.assertFalse(library.apply_opened(newer + 99, rv.OpenedRef("bbbbbbbb", "다른", "다른")), "미래의 번호도 받지 않는다")
        self.assertEqual(library.current, "aaaaaaaa")

    def test_a_late_failure_is_dropped_too(self):
        library, _ = make()
        library.open()
        old = library.begin()
        library.begin()
        self.assertFalse(library.apply_failed(old, "낡은 실패"))
        self.assertEqual(library.view()["message"], "")

    def test_close_forgets_everything_and_reopening_starts_clean(self):
        library, _ = make()
        library.open()
        library.select("aaaaaaaa")
        library.edited("고침", "고침")
        generation = library.generation
        library.close()
        self.assertGreater(library.generation, generation)
        self.assertEqual((library.rows, library.current, library.dirty, library.is_open), ((), None, False, False))
        library.open()
        self.assertEqual((library.current, library.dirty, library.mode), (None, False, "new"))

    def test_when_the_open_post_disappears_from_the_list_the_editor_returns_to_new(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        del provider.items["aaaaaaaa"]
        library.refresh()
        self.assertEqual((library.current, library.mode, library.dirty), (None, "new", False))


class DeleteTest(unittest.TestCase):
    def open_one(self, **kwargs):
        library, provider = make(**kwargs)
        library.open()
        library.select("aaaaaaaa")
        return library, provider

    def test_deleting_is_two_steps_and_only_the_second_continue_deletes(self):
        library, provider = self.open_one()
        self.assertEqual(library.ask_delete(), "step1")
        self.assertEqual(library.view()["delete"]["question"], T["ref_delete_q1"])
        self.assertEqual(library.view()["delete"]["next"]["text"], T["ref_delete_next"])
        self.assertNotIn("delete", provider.calls)
        self.assertEqual(library.advance_delete(), "step2")
        self.assertEqual(library.view()["delete"]["question"], T["ref_delete_q2"])
        self.assertEqual(library.view()["delete"]["next"]["text"], T["ref_delete_yes"])
        self.assertNotIn("delete", provider.calls, "두 번째 확인 전에는 지우지 않는다")
        self.assertEqual(library.advance_delete(), "deleted")
        self.assertEqual(provider.calls.count("delete"), 1)
        self.assertNotIn("aaaaaaaa", provider.items)
        self.assertEqual((library.current, library.mode, library.delete_step), (None, "new", 0))
        self.assertEqual(library.view()["notice"], T["ref_done_deleted"])

    def test_cancelling_at_any_step_deletes_nothing(self):
        for steps in (0, 1):
            library, provider = self.open_one()
            library.ask_delete()
            for _ in range(steps):
                library.advance_delete()
            self.assertTrue(library.cancel_delete())
            self.assertEqual(library.delete_step, 0)
            self.assertEqual(library.advance_delete(), "idle")
            self.assertNotIn("delete", provider.calls)
            self.assertIn("aaaaaaaa", provider.items)
        self.assertFalse(library.cancel_delete())

    def test_nothing_to_delete_when_no_post_is_open(self):
        library, provider = make()
        library.open()
        self.assertEqual(library.ask_delete(), "none")
        self.assertEqual(library.view()["message"], T["ref_none_selected"])
        self.assertEqual(library.advance_delete(), "idle")
        self.assertNotIn("delete", provider.calls)

    def test_buttons_are_off_while_a_confirmation_is_open(self):
        library, _ = self.open_one()
        library.ask_delete()
        buttons = library.view()["buttons"]
        self.assertFalse(buttons["save"]["enabled"] or buttons["new"]["enabled"] or buttons["pick"]["enabled"] or buttons["delete"]["enabled"])
        self.assertTrue(buttons["close"]["enabled"])

    def test_a_refused_delete_shows_the_fixed_sentence_and_resets_the_steps(self):
        library, provider = self.open_one(refuse=("delete",))
        library.ask_delete()
        library.advance_delete()
        self.assertEqual(library.advance_delete(), "refused")
        self.assertEqual((library.delete_step, library.view()["message"]), (0, "가짜 공급자의 고정 거절 문장이에요"))
        self.assertIn("aaaaaaaa", provider.items)

    def test_a_delete_in_flight_is_dropped_if_the_dialog_was_closed(self):
        library, provider = self.open_one()
        library.ask_delete()
        library.advance_delete()
        library.close()
        self.assertEqual(library.advance_delete(), "closed")
        self.assertNotIn("delete", provider.calls)


class NoTextInStateTest(unittest.TestCase):
    def test_no_title_or_body_stays_in_the_state_after_a_full_session(self):
        library, provider = make(items={})
        library.open()
        library.new_post()
        library.edited(TITLE_MARK, BODY_MARK)
        library.save(TITLE_MARK, BODY_MARK)
        ref_id = library.current
        library.select(ref_id, discard=True)
        library.edited(TITLE_MARK + "2", BODY_MARK + "2")
        library.save(TITLE_MARK + "2", BODY_MARK + "2")
        library.ask_delete()
        library.advance_delete()
        library.advance_delete()
        shown = repr(library.view())
        held = state_text(library)
        self.assertNotIn(BODY_MARK, held + shown)
        self.assertNotIn(BODY_MARK, repr(library.rows))
        self.assertNotIn(BODY_MARK, repr(vars(library)))

    def test_the_value_objects_do_not_show_the_title_or_text_in_repr(self):
        opened, row = rv.OpenedRef("aaaaaaaa", TITLE_MARK, BODY_MARK), rv.RefRow("aaaaaaaa", TITLE_MARK, 3, "2026-11-15T01:00:00Z")
        for value in (opened, row, rv.RefListing((row,))):
            self.assertNotIn(TITLE_MARK, repr(value))
            self.assertNotIn(BODY_MARK, repr(value))

    def test_a_refusal_carries_no_earlier_error(self):
        library, _ = make(refuse=("open",))
        library.open()
        try:
            library.provider.open("aaaaaaaa")
        except rv.ReferencesRefusal as error:
            self.assertIsNone(error.__context__)


class SourceRulesTest(unittest.TestCase):
    def test_the_core_module_imports_no_qt_file_network_or_service_modules(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        banned = {"PySide6", "os", "pathlib", "socket", "subprocess", "urllib", "http", "logging", "tempfile", "shutil", "json", "sqlite3"}
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            for name in names:
                self.assertNotIn(name.split(".")[0], banned, name)
            if isinstance(node, ast.ImportFrom) and node.level:
                self.assertNotIn("service", (node.module or "").split("."), "화면 규칙은 서비스를 직접 가져오지 않는다")
        called = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertFalse(called & {"print", "open", "eval", "exec"})

    def test_the_text_has_no_tilde_or_web_address(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn(chr(0x7E), text)
        self.assertNotIn("http", text)


if __name__ == "__main__":
    unittest.main()
