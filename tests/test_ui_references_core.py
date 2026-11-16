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

    def test_a_failed_list_shows_the_fixed_sentence_and_stops_saying_loading(self):
        """이름의 '그것뿐' 을 거두었다(검증자 Q) — 거절 문장만 보는 시험이었다. 실패하면 '읽는 중' 이 같이 뜨지 않아야 하고(Q-06), 비어 있다고도 말하지 않는다(읽지 못한 것이다)."""
        library, _ = make(refuse=("list",))
        self.assertEqual(library.open(), "failed")
        view = library.view()
        self.assertEqual(view["message"], "가짜 공급자의 고정 거절 문장이에요")
        self.assertEqual((view["list"]["loading"], view["list"]["empty"], view["list"]["rows"]), ("", "", []))
        self.assertEqual(view["list"]["failed"], T["ref_fail_load"])

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

    def test_the_open_row_has_a_visible_marker_and_a_spoken_name_and_the_others_do_not(self):
        """검증자 Q-10(색만으로 표시하지 않는다)·변이 C17 — 열린 글 줄은 파랑뿐 아니라 보이는 글자('지금 편집 중')와 읽어 주는 이름 둘 다에 표시가 있고, 다른 줄에는 없다."""
        library, _ = make()
        library.open()
        library.select("bbbbbbbb")
        rows = {row["id"]: row for row in library.view()["list"]["rows"]}
        self.assertTrue(rows["bbbbbbbb"]["selected"])
        self.assertTrue(rows["bbbbbbbb"]["label"].endswith(" · 지금 편집 중"), rows["bbbbbbbb"]["label"])
        self.assertTrue(rows["bbbbbbbb"]["a11y"].endswith(", 지금 편집 중"), rows["bbbbbbbb"]["a11y"])
        self.assertEqual(rows["bbbbbbbb"]["a11y"], T["ref_row_selected_a11y"].format(title="둘째 글", chars="9", when="2026-11-15 11:00"))
        self.assertNotIn("지금 편집 중", rows["aaaaaaaa"]["label"])
        self.assertNotIn("지금 편집 중", rows["aaaaaaaa"]["a11y"])
        self.assertEqual(rows["aaaaaaaa"]["a11y"], T["ref_row_a11y"].format(title="첫 글", chars="4", when="2026-11-15 10:00"))
        library.new_post()
        self.assertFalse(any("지금 편집 중" in row["label"] + row["a11y"] for row in library.view()["list"]["rows"]))

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

    def test_when_the_open_post_disappears_from_the_list_the_editor_returns_to_new_and_the_text_left_in_the_box_counts_as_unsaved(self):
        """독립 검증 Q-04 — 열어 둔 글이 바깥에서 지워져 목록에서 사라지면 새 글 모습으로 바뀌지만 편집 칸의 글은 그대로다. 그 글은 저장 안 한 새 글이므로 변경 표시가 켜져 닫기·새 글이 확인 없이 버리지 않는다(옛 시험은 여기서 dirty=False 를 못박고 있었다)."""
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        del provider.items["aaaaaaaa"]
        library.refresh()
        self.assertEqual((library.current, library.mode, library.dirty), (None, "new", True))
        self.assertEqual(library.notice, T["ref_vanished"])
        self.assertEqual(library.view()["editor"]["state"], T["ref_dirty"])
        self.assertEqual(library.leave("close"), "ask", "칸의 글이 확인 없이 버려지지 않는다")
        library.keep_editing()
        self.assertEqual(library.new_post(), "dirty")

    def test_a_box_that_was_already_emptied_is_clean_when_its_post_vanishes(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        library.edited("", "")
        del provider.items["aaaaaaaa"]
        library.refresh()
        self.assertEqual((library.current, library.mode, library.dirty), (None, "new", False))
        self.assertEqual(library.leave("close"), "go")

    def test_saving_after_the_post_vanished_keeps_it_as_a_new_post_and_the_notice_is_replaced(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        library.edited("고친 제목", "고친 본문")
        del provider.items["aaaaaaaa"]
        library.refresh()
        self.assertEqual(library.save("고친 제목", "고친 본문"), "saved")
        self.assertNotEqual(library.current, "aaaaaaaa")
        self.assertEqual((library.mode, library.dirty, library.notice), ("edit", False, T["ref_done_saved"]))
        self.assertEqual(sorted(provider.items)[0], "bbbbbbbb")
        self.assertEqual(len(provider.items), 2, "새 글로 보관됐다")

    def test_the_notice_of_an_earlier_job_stays_and_the_vanished_one_follows_it(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        del provider.items["aaaaaaaa"]
        self.assertEqual(library.add_file("C:/x/a.txt"), "added")
        self.assertEqual(library.notice, T["ref_done_file"] + " " + T["ref_vanished"])

    def test_the_delete_question_of_a_post_that_vanished_is_dropped(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        library.ask_delete()
        del provider.items["aaaaaaaa"]
        library.refresh()
        self.assertEqual((library.delete_step, library.delete_target), (0, None))
        self.assertEqual(library.advance_delete(), "idle")
        self.assertNotIn("delete", provider.calls)

    def test_a_post_that_did_not_vanish_keeps_the_open_state_and_adds_no_notice(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        del provider.items["bbbbbbbb"]
        library.refresh()
        self.assertEqual((library.current, library.mode, library.dirty, library.notice), ("aaaaaaaa", "edit", False, ""))

    def test_editing_again_after_saving_takes_back_the_saved_notice(self):
        """검증자 Q-09 — 저장한 뒤 다시 고치면 '저장하지 않은 변경이 있어요.' 와 '저장했어요.' 가 한 화면에 같이 남았다."""
        library, _ = make(items={})
        library.open()
        library.edited("글", "본문")
        self.assertEqual(library.save("글", "본문"), "saved")
        self.assertEqual(library.notice, T["ref_done_saved"])
        self.assertFalse(library.edited("글", "본문"), "그대로면 안내가 남는다")
        self.assertEqual(library.notice, T["ref_done_saved"])
        self.assertTrue(library.edited("글", "본문 고침"))
        self.assertEqual(library.notice, "", "고치면 저장했다는 안내를 거둔다")
        self.assertFalse(library.edited("글", "본문"))
        self.assertEqual(library.notice, "", "다시 되돌려도 안내는 돌아오지 않는다")


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

    def test_after_a_delete_the_editor_returns_to_new_even_if_reading_the_list_fails(self):
        """지운 뒤 목록을 다시 읽다 실패해도 열린 글·저장 안 한 변경 표시가 남지 않는다(목록 갱신이 아니라 지우기 자신이 정리한다)."""
        library, provider = self.open_one()
        library.edited("고친 제목", "고친 본문")
        self.assertTrue(library.dirty)
        library.ask_delete()
        library.advance_delete()
        provider.refuse = ("list",)
        self.assertEqual(library.advance_delete(), "deleted")
        self.assertEqual((library.current, library.mode, library.dirty, library.delete_step), (None, "new", False, 0))
        self.assertEqual(library.baseline, rv.digest("", ""))
        self.assertEqual(library.view()["editor"]["state"], "")
        self.assertNotIn("aaaaaaaa", provider.items)

    def test_opening_another_post_while_a_delete_question_is_open_clears_the_question_so_a_wrong_post_is_never_deleted(self):
        """독립 검증 S-R6(변이 U03) — 목록의 `열기` 는 지우기 확인이 떠 있는 동안에도 눌린다. 다른 글을 열면 지우기 확인(단계·대상)이 비워져야 한다 — 안 비우면 '계속' 두 번이 **앞에 열었던 다른 글**을 지운다."""
        library, provider = self.open_one()
        self.assertEqual(library.ask_delete(), "step1")
        self.assertEqual((library.delete_step, library.delete_target), (1, "aaaaaaaa"))
        status, opened = library.select("bbbbbbbb")
        self.assertEqual((status, opened.ref_id, library.current), ("opened", "bbbbbbbb", "bbbbbbbb"))
        self.assertEqual((library.delete_step, library.delete_target), (0, None), "다른 글을 열면 지우기 확인이 비워진다")
        self.assertEqual(library.view()["delete"]["step"], 0)
        self.assertEqual(library.advance_delete(), "idle", "비워진 확인에서 '계속' 은 아무 일도 하지 않는다")
        self.assertEqual(library.advance_delete(), "idle")
        self.assertNotIn("delete", provider.calls)
        self.assertEqual(sorted(provider.items), ["aaaaaaaa", "bbbbbbbb"], "두 글 모두 남아 있다")
        library.ask_delete()
        self.assertEqual(library.delete_target, "bbbbbbbb", "새로 묻는 대상은 지금 열린 글이다")
        library.advance_delete()
        library.advance_delete()
        self.assertEqual(sorted(provider.items), ["aaaaaaaa"], "지워진 것은 지금 열린 글 하나뿐이다")

    def test_an_open_result_that_arrives_late_clears_the_delete_question_on_its_own(self):
        """`select` 가 지우기 확인을 먼저 그만두게 된 뒤(Q-03)에도 `apply_opened` 자신이 확인을 비워야 한다 — 늦게 도착한 '열린 글' 결과가 앞 글의 지우기 확인을 살려 두면 안 된다(변이 U03 을 이 길로도 지킨다)."""
        library, provider = self.open_one()
        library.ask_delete()
        ticket = library.begin()
        self.assertTrue(library.apply_opened(ticket, rv.OpenedRef("bbbbbbbb", "둘째 글", "둘째 본문 입니다")))
        self.assertEqual((library.delete_step, library.delete_target, library.pending, library.current), (0, None, None, "bbbbbbbb"))
        self.assertEqual(library.advance_delete(), "idle")
        self.assertNotIn("delete", provider.calls)

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


class LeaveEscapeTest(unittest.TestCase):
    """닫기 단추·Esc·창 닫기(X·Alt+F4)가 모두 같은 '저장 안 한 변경' 확인을 거치고, 확인이 열려 있으면 다른 일이 꺼진다(offscreen 에서 처음 띄워 보고 Esc 가 확인 없이 닫던 틈을 고쳤다)."""

    def dirty_library(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        library.edited("고친 제목", "고친 본문")
        return library, provider

    def test_leaving_a_clean_dialog_goes_and_a_dirty_one_asks_for_every_kind(self):
        library, _ = make()
        self.assertEqual(library.leave("close"), "closed", "열려 있지 않으면 할 일이 없다")
        library.open()
        self.assertEqual((library.leave("close"), library.pending), ("go", None))
        self.assertEqual((library.leave("quit"), library.pending), ("go", None))
        library.edited("글", "본문")
        for kind in ("close", "quit"):
            self.assertEqual((library.leave(kind), library.pending), ("ask", (kind,)))
            library.keep_editing()
        self.assertTrue(library.dirty)

    def test_escape_follows_the_decision_table(self):
        library, _ = make()
        self.assertEqual(library.escape(), "closed")
        library.open()
        self.assertEqual(library.escape(), "close", "저장 안 한 변경이 없으면 바로 닫는다")
        library.edited("글", "본문")
        self.assertEqual((library.escape(), library.pending), ("ask_close", ("close",)), "변경이 있으면 닫기 전에 묻는다")
        self.assertEqual((library.escape(), library.pending), ("keep_editing", ("close",)), "묻는 중에 Esc 는 닫지 않고 계속 고치는 쪽이다(여기서는 상태만 정하고 화면이 `keep_editing` 을 한다)")
        library.keep_editing()
        self.assertIsNone(library.pending)

    def test_escape_looks_at_the_delete_question_before_the_discard_question_even_if_both_were_forced(self):
        """두 질문은 이제 함께 열리지 않지만(검증자 Q-03) 규칙의 순서는 못박아 둔다 — 지우기 확인이 먼저, 그다음 버릴지 묻는 중, 그다음 저장 안 한 변경(변이 C04)."""
        library, _ = self.dirty_library()
        library.delete_step, library.delete_target, library.pending = 1, "aaaaaaaa", ("close",)
        self.assertEqual(library.escape(), "cancel_delete")
        library.delete_step, library.delete_target = 0, None
        self.assertEqual(library.escape(), "keep_editing")
        library.pending = None
        self.assertEqual(library.escape(), "ask_close")

    def test_escape_cancels_a_delete_confirmation_before_anything_else(self):
        library, provider = self.dirty_library()
        library.save("고친 제목", "고친 본문")
        library.ask_delete()
        library.edited("또 고침", "또 고친 본문")
        self.assertEqual(library.escape(), "cancel_delete")
        self.assertNotIn("delete", provider.calls)
        library.advance_delete() if library.delete_step else None
        library.ask_delete()
        library.advance_delete()
        self.assertEqual(library.escape(), "cancel_delete", "2단계에서도 그만둔다")

    def test_selecting_or_new_with_unsaved_changes_remembers_what_it_was_asked_to_do(self):
        library, _ = self.dirty_library()
        self.assertEqual(library.select("bbbbbbbb")[0], "dirty")
        self.assertEqual(library.pending, ("select", "bbbbbbbb"))
        self.assertEqual(library.new_post(), "dirty")
        self.assertEqual(library.pending, ("new",), "나중에 물은 일이 앞의 것을 바꾼다")
        self.assertEqual(library.take_pending(), ("new",))
        self.assertIsNone(library.pending)
        self.assertIsNone(library.take_pending())
        library.select("bbbbbbbb")
        self.assertEqual(library.select("bbbbbbbb", discard=True)[0], "opened")
        self.assertIsNone(library.pending, "열면 기다리던 일이 사라진다")

    def test_save_open_and_close_clear_the_pending_question(self):
        library, _ = self.dirty_library()
        library.leave("close")
        library.pending = None
        library.leave("close")
        self.assertEqual(library.save("고친 제목", "고친 본문"), "saved")
        self.assertIsNone(library.pending)
        library.edited("x", "y")
        library.leave("quit")
        library.close()
        self.assertIsNone(library.pending)
        library.open()
        self.assertIsNone(library.pending)

    def test_the_view_shows_the_question_of_each_kind_and_turns_the_other_buttons_off(self):
        library, _ = self.dirty_library()
        view = library.view()
        self.assertEqual(view["discard"]["open"], False)
        self.assertTrue(all(view["buttons"][name]["enabled"] for name in ("save", "new", "pick", "delete", "close")))
        shown = {}
        for kind, how in (("select", lambda: library.select("bbbbbbbb")), ("new", library.new_post), ("close", library.leave), ("quit", lambda: library.leave("quit"))):
            library.keep_editing()
            how()
            view = library.view()
            discard = view["discard"]
            self.assertEqual((discard["open"], discard["kind"]), (True, kind))
            self.assertEqual(discard["question"], T["ref_discard_q_" + kind])
            self.assertEqual((discard["yes"], discard["no"]), (T["ref_discard_yes_" + kind], T["ref_discard_no"]))
            self.assertEqual((discard["yes_a11y"], discard["no_a11y"]), (T["ref_discard_yes_a11y_" + kind], T["ref_discard_no_a11y"]))
            self.assertFalse(any(view["buttons"][name]["enabled"] for name in ("save", "new", "pick", "delete")), kind)
            self.assertTrue(view["buttons"]["close"]["enabled"], "닫기는 남는다")
            shown[kind] = discard["question"]
        self.assertEqual(len(set(shown.values())), 4, "묻는 말은 일마다 다르다")
        library.keep_editing()
        self.assertEqual(library.view()["discard"]["question"], "")

    def test_the_limits_sentence_reads_with_a_thousands_separator(self):
        library, _ = make()
        library.open()
        limits = library.view()["limits"]
        self.assertIn("50개", limits)
        self.assertIn("80자", limits)
        self.assertIn("100,000자", limits)


class OneQuestionTest(unittest.TestCase):
    """독립 검증 Q-03 — 지우기 확인이 열린 채 다른 길(열기·새 글·닫기·창 닫기)이 오면 질문이 둘 쌓여 화면에는 하나만 보였고 닫기·창 X 가 먹통처럼 보였다. 이제 그런 요청이 오면 먼저 지우기 확인을 그만두고 그 요청의 질문 하나만 남는다."""

    def dirty_with_delete_open(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        library.ask_delete()
        library.edited("고친 제목", "고친 본문")                                    # 지우기 확인이 떠 있어도 편집 칸은 꺼지지 않는다
        return library, provider

    def test_every_other_way_cancels_the_delete_question_first_and_leaves_exactly_one_question(self):
        ways = (("열기", lambda lib: lib.select("bbbbbbbb")[0], "dirty", "select"), ("새 글", lambda lib: lib.new_post(), "dirty", "new"),
                ("닫기", lambda lib: lib.leave("close"), "ask", "close"), ("창 닫기", lambda lib: lib.leave("quit"), "ask", "quit"))
        for label, act, expected, kind in ways:
            with self.subTest(label):
                library, provider = self.dirty_with_delete_open()
                self.assertEqual((library.delete_step, library.delete_target), (1, "aaaaaaaa"))
                self.assertEqual(act(library), expected)
                self.assertEqual((library.delete_step, library.delete_target), (0, None), "지우기 확인은 그만둔다")
                self.assertEqual(library.pending[0], kind, "그 길의 질문 하나가 남는다")
                view = library.view()
                self.assertEqual(view["delete"]["step"], 0)
                self.assertEqual((view["discard"]["open"], view["discard"]["kind"]), (True, kind))
                self.assertNotIn("delete", provider.calls, "지우기는 일어나지 않았다")
                self.assertEqual(library.advance_delete(), "idle", "그만둔 지우기에 '계속' 을 눌러도 아무 일이 없다")

    def test_when_nothing_is_unsaved_the_other_way_just_goes_and_the_delete_question_is_gone(self):
        library, provider = make()
        library.open()
        library.select("aaaaaaaa")
        library.ask_delete()
        self.assertEqual(library.leave("close"), "go")
        self.assertEqual((library.delete_step, library.delete_target, library.pending), (0, None, None))
        library.ask_delete()
        self.assertEqual(library.new_post(), "ready")
        self.assertEqual((library.delete_step, library.pending), (0, None))
        library.select("aaaaaaaa")
        library.ask_delete()
        self.assertEqual(library.select("bbbbbbbb")[0], "opened")
        self.assertEqual((library.delete_step, library.pending, library.current), (0, None, "bbbbbbbb"))
        self.assertNotIn("delete", provider.calls)

    def test_starting_a_delete_replaces_a_waiting_discard_question(self):
        library, _ = make()
        library.open()
        library.select("aaaaaaaa")
        library.edited("고침", "고친 본문")
        library.select("bbbbbbbb")
        self.assertEqual(library.pending, ("select", "bbbbbbbb"))
        self.assertEqual(library.ask_delete(), "step1")
        self.assertIsNone(library.pending, "질문은 늘 하나")
        self.assertEqual(library.delete_step, 1)

    def test_after_any_action_the_two_questions_are_never_open_together(self):
        """무작위 걷기(씨앗 고정) — 화면 규칙의 모든 동작을 아무 순서로 불러도(눌릴 수 없는 단추까지) 기다리는 질문이 둘이 되지 않는다. 검증자 Q 의 걷기 도구(`walk_core.py` I2)와 같은 불변 조건이다."""
        import random
        calls = ["select_a", "select_b", "select_nope", "select_discard", "new", "new_discard", "leave_close", "leave_quit", "escape", "keep", "take", "ask_delete", "delete_next", "cancel_delete",
                 "edit", "revert", "save", "pick", "refresh", "reload", "toggle_refuse"]
        for seed in range(150):
            rng = random.Random(20261116 + seed)
            library, provider = make()
            library.open()
            for step in range(60):
                name = rng.choice(calls)
                if name.startswith("select_"):
                    library.select({"a": "aaaaaaaa", "b": "bbbbbbbb", "nope": "nope9999", "discard": "bbbbbbbb"}[name[7:]], discard=name == "select_discard")
                elif name.startswith("new"):
                    library.new_post(discard=name == "new_discard")
                elif name.startswith("leave_"):
                    library.leave(name[6:])
                elif name == "escape":
                    action = library.escape()
                    if action == "cancel_delete":
                        library.cancel_delete()
                    elif action == "keep_editing":
                        library.keep_editing()
                elif name == "keep":
                    library.keep_editing()
                elif name == "take":
                    library.take_pending()
                elif name == "ask_delete":
                    library.ask_delete()
                elif name == "delete_next":
                    library.advance_delete()
                elif name == "cancel_delete":
                    library.cancel_delete()
                elif name == "edit":
                    library.edited(rng.choice(["", "제목", "다른 제목"]), rng.choice(["", "본문", "다른 본문"]))
                elif name == "revert":
                    library.rebase("", "")
                elif name == "save":
                    library.save(rng.choice(["", "제목"]), rng.choice(["", "본문"]))
                elif name == "pick":
                    library.add_file(rng.choice(["", "C:/x/a.txt"]))
                elif name == "refresh":
                    library.refresh()
                elif name == "reload":
                    library.reload()
                else:
                    provider.refuse = tuple(rng.sample(["list", "open", "save", "add", "add_file", "delete"], rng.choice([0, 0, 1, 2])))
                self.assertFalse(library.pending is not None and library.delete_step, f"씨앗 {seed} 걸음 {step} {name}: pending={library.pending} delete_step={library.delete_step}")


class RebaseTest(unittest.TestCase):
    """독립 검증 Q-01 의 화면 쪽 방어 — 편집 칸이 글을 되읽으며 글자(줄 끝 같은 것)를 바꿔도, 칸에서 되읽은 글을 기준으로 다시 잡으면 열자마자 '저장하지 않은 변경' 이 켜지지 않는다."""

    def test_a_box_that_reads_the_text_back_differently_would_look_edited_until_the_baseline_is_taken_from_the_box(self):
        raw = "첫 줄\r\n둘째 줄\u2028셋째 줄\u00a0끝"
        back = "첫 줄\n둘째 줄\n셋째 줄 끝"
        library, _ = make(items={"aaaaaaaa": ["제목", raw, "2026-11-15T01:00:00Z"]})
        library.open()
        status, opened = library.select("aaaaaaaa")
        self.assertEqual((status, opened.body), ("opened", raw))
        self.assertTrue(library.edited(opened.title, back), "기준이 칸에 채운 글(원문)이면 되읽은 글은 달라 보인다 — 거짓 변경 표시")
        self.assertTrue(library.rebase(opened.title, back))
        self.assertFalse(library.dirty, "되읽은 글을 기준으로 다시 잡으면 깨끗하다")
        self.assertFalse(library.edited(opened.title, back))
        self.assertEqual(library.view()["editor"]["state"], T["ref_clean"])
        self.assertTrue(library.edited(opened.title, back + "x"), "그 뒤 정말 고치면 변경 표시가 켜진다")
        self.assertTrue(library.edited(opened.title + "x", back))
        self.assertFalse(library.edited(opened.title, back), "되돌리면 다시 꺼진다")

    def test_rebase_holds_only_a_fingerprint_and_does_nothing_when_closed(self):
        library, _ = make()
        self.assertFalse(library.rebase(TITLE_MARK, BODY_MARK), "열려 있지 않으면 아무 일도 하지 않는다")
        library.open()
        library.new_post()
        self.assertTrue(library.rebase(TITLE_MARK, BODY_MARK))
        self.assertNotIn(BODY_MARK, state_text(library) + repr(library.view()))
        self.assertNotIn(TITLE_MARK, state_text(library) + repr(library.view()))
        self.assertTrue(library.rebase(None, 5) and not library.dirty, "글이 아닌 값은 빈 글로 본다")

    def test_a_clean_dialog_does_not_ask_to_discard_after_the_box_changed_the_text(self):
        library, _ = make(items={"aaaaaaaa": ["제목", "가\r\n나", "2026-11-15T01:00:00Z"]})
        library.open()
        library.select("aaaaaaaa")
        library.rebase("제목", "가\n나")
        library.edited("제목", "가\n나")
        self.assertEqual(library.leave("close"), "go", "안 고쳤으면 묻지 않는다")
        self.assertEqual(library.select("aaaaaaaa")[0], "opened")
        self.assertEqual(library.new_post(), "ready")


class LoadFailedTest(unittest.TestCase):
    """독립 검증 Q-06 — 목록 읽기가 실패하면 '읽는 중이에요…' 가 계속 남고 다시 읽을 길이 없었다."""

    def test_a_failed_list_offers_to_read_again_and_says_it_could_not_read(self):
        library, _ = make(refuse=("list",))
        self.assertEqual(library.open(), "failed")
        view = library.view()
        self.assertEqual(view["list"]["failed"], T["ref_fail_load"])
        self.assertEqual(view["list"]["loading"], "")
        self.assertTrue(view["list"]["reload"]["visible"])
        self.assertEqual((view["list"]["reload"]["text"], view["list"]["reload"]["a11y"]), (T["ref_reload"], T["ref_reload_a11y"]))
        self.assertFalse(library.loaded)

    def test_reading_again_clears_the_failure_and_the_old_refusal_sentence(self):
        library, provider = make(refuse=("list",))
        library.open()
        self.assertNotEqual(library.view()["message"], "")
        provider.refuse = ()
        self.assertEqual(library.reload(), "loaded")
        view = library.view()
        self.assertEqual((view["list"]["failed"], view["list"]["loading"], view["message"]), ("", "", ""))
        self.assertFalse(view["list"]["reload"]["visible"])
        self.assertEqual(len(view["list"]["rows"]), 2)

    def test_reading_again_that_fails_again_keeps_the_offer_and_shows_the_sentence_again(self):
        library, _ = make(refuse=("list",))
        library.open()
        self.assertEqual(library.reload(), "failed")
        view = library.view()
        self.assertTrue(view["list"]["reload"]["visible"])
        self.assertEqual(view["message"], "가짜 공급자의 고정 거절 문장이에요")

    def test_a_list_that_failed_after_an_earlier_success_keeps_the_rows_and_offers_again(self):
        library, provider = make()
        library.open()
        provider.refuse = ("list",)
        self.assertEqual(library.refresh(), "failed")
        view = library.view()
        self.assertEqual(len(view["list"]["rows"]), 2, "앞서 읽은 줄은 남는다")
        self.assertTrue(view["list"]["reload"]["visible"])
        provider.refuse = ()
        self.assertEqual(library.reload(), "loaded")
        self.assertFalse(library.view()["list"]["reload"]["visible"])

    def test_opening_again_starts_without_the_failure_and_a_closed_library_does_nothing(self):
        library, provider = make(refuse=("list",))
        self.assertEqual(library.reload(), "closed")
        self.assertEqual(provider.calls, [])
        library.open()
        library.close()
        provider.refuse = ()
        library.open()
        self.assertFalse(library.view()["list"]["reload"]["visible"])
        self.assertEqual(library.view()["list"]["failed"], "")

    def test_a_late_failure_from_an_old_generation_does_not_turn_the_offer_on(self):
        class Racing(rv.FakeReferencesProvider):
            """목록을 읽는 사이에 더 새로운 일이 시작되는 공급자(늦게 온 실패가 된다)."""
            library = None

            def list_rows(self):
                self.library.begin()
                raise rv.ReferencesRefusal("늦은 실패")

        provider = Racing(ITEMS)
        library = rv.ReferenceLibrary(provider)
        provider.library = library
        library.is_open = True
        self.assertEqual(library.refresh(), "stale")
        self.assertFalse(library.load_failed)
        self.assertEqual((library.message, library.view()["list"]["failed"]), ("", ""))


class NoTextInStateTest(unittest.TestCase):
    def test_no_title_or_body_stays_in_the_state_after_a_full_session(self):
        library, provider = make(items={})
        library.open()
        library.new_post()
        library.rebase(TITLE_MARK, BODY_MARK)
        library.edited(TITLE_MARK, BODY_MARK)
        library.save(TITLE_MARK, BODY_MARK)
        ref_id = library.current
        library.select(ref_id, discard=True)
        library.rebase(TITLE_MARK, BODY_MARK)
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
