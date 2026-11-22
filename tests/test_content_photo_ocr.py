"""글자 읽기(결정 D-512)의 순수 규칙 — `content/photo_ocr.py`(작업자 줄 -> 후보 다듬기)와 `photo_manifest.py` 의 새 함수·한도 분리, `PhotoBoard.differs_from` 고침(설계서 4-2·3-10 ①⑤).

지키는 것:
  1) 다듬기 — 순서 그대로·한 줄 정리·빈 줄 조용히 빼기·같은 글 되풀이 빼기·입구 검사에 걸린 줄은 글을 되풀이하지 않고 개수만·줄 수 한도 60·작업자 줄이 이상한 모양이어도 안 터짐.
  2) 한도 분리 — 읽은 글자 칸은 60개, 관찰한 대상 칸은 20개(저장한 파일을 읽을 때도 같다). 줄당 200자는 그대로.
  3) `remove_item`·`merge_items` — 확정이 풀리고, 이은 글도 입구 검사를 거치며(두 줄을 이어 주민번호 모양이 되면 거절), 저장하는 모양은 그대로이고, 원래 목록은 안 바뀐다.
  4) `differs_from` — 읽은 글은 저장하지 않으므로 '저장 안 한 변경' 으로 세지 않는다. 그 밖의 고침은 그대로 센다.
"""
import ast
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.content import photo_ocr as po  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.ui.core import photo_view as pv  # noqa: E402

SOURCE = ROOT / "src" / "chanceblog_desktop" / "content" / "photo_ocr.py"
USER_DIR, FILE_STEM = "UNIQ-USERDIR-q7w2", "UNIQ-FILE-k3x9"
RESIDENT = ("900101", "1234567")                       # 따로는 평범한 숫자, 공백으로 이으면 주민등록번호 모양


def path_of(number):
    return f"C:\\Users\\{USER_DIR}\\Pictures\\{FILE_STEM}-{number:02d}.jpg"


def build(count=1):
    manifest = pm.empty_manifest()
    for number in range(1, count + 1):
        manifest, _id = pm.add_photo(manifest, path_of(number), photo_type="메뉴판")
    return manifest


def read(manifest, lines, photo_id="p001"):
    return pm.set_analysis(manifest, photo_id, method=po.METHOD, texts=lines)[0]


def texts_of(manifest, photo_id="p001", kind=pm.TEXTS):
    return [item.text for item in getattr(manifest.photo(photo_id), kind)]


def refused(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except AppError as error:
        return error
    raise AssertionError("AppError 가 나지 않았다")


class PrepareTest(unittest.TestCase):
    def test_the_order_is_kept_and_each_line_is_tidied_to_one_line(self):
        result = po.prepare(["  한우   불고기 \t전골 ", "된장찌개", "공기밥  1,000원"])
        self.assertEqual(result.texts, ("한우 불고기 전골", "된장찌개", "공기밥 1,000원"))
        self.assertEqual((result.filtered, result.over_limit, result.blank, result.duplicates, result.found), (0, 0, 0, 0, 3))

    def test_blank_lines_and_repeats_are_dropped_quietly_and_not_reported_as_hidden(self):
        result = po.prepare(["메뉴", "", "   ", "\u200b\u200d", "메뉴", " 메뉴 ", "가격"])
        self.assertEqual(result.texts, ("메뉴", "가격"))
        self.assertEqual((result.blank, result.duplicates, result.filtered, result.hidden), (3, 2, 0, 0))

    def test_lines_that_fail_the_entry_check_are_only_counted_and_never_repeated(self):
        long_line = "가" * (po.MAX_LINE_CHARS + 1)
        tag = "<" + "script" + ">alert(1)</" + "script" + ">"
        numbered = " ".join(RESIDENT)
        result = po.prepare(["정상 줄", long_line, tag, numbered, "{{사진 1}}", "4111 1111 1111 1111", "마지막 줄"])
        self.assertEqual(result.texts, ("정상 줄", "마지막 줄"))
        self.assertEqual((result.filtered, result.hidden), (5, 5))
        self.assertNotIn("script", repr(result))
        self.assertNotIn("정상", repr(result), "글은 repr 에 나오지 않는다")

    def test_a_line_of_exactly_the_limit_is_kept(self):
        result = po.prepare(["가" * po.MAX_LINE_CHARS])
        self.assertEqual((result.found, result.filtered), (1, 0))

    def test_more_lines_than_the_limit_are_cut_and_counted(self):
        lines = [f"줄 {number}" for number in range(po.MAX_LINES + 5)]
        result = po.prepare(lines)
        self.assertEqual((result.found, result.over_limit, result.truncated), (60, 5, True))
        self.assertEqual(result.texts[0], "줄 0")
        self.assertEqual(result.texts[-1], "줄 59")

    def test_the_limit_can_be_lowered_but_never_raised_above_sixty(self):
        lines = [f"줄 {number}" for number in range(70)]
        self.assertEqual(po.prepare(lines, 3).found, 3)
        self.assertEqual(po.prepare(lines, 100).found, 60)
        self.assertEqual(po.prepare(lines, -1).found, 60)
        self.assertEqual(po.prepare(lines, True).found, 60)
        self.assertEqual(po.prepare(lines, 0).found, 0)

    def test_filtered_lines_do_not_use_up_the_limit(self):
        lines = ["가" * 300] * 10 + [f"줄 {number}" for number in range(60)]
        result = po.prepare(lines)
        self.assertEqual((result.found, result.filtered, result.over_limit), (60, 10, 0))

    def test_worker_lines_may_be_text_or_objects_and_other_shapes_are_counted_not_raised(self):
        result = po.prepare([{"text": "객체 줄", "cx": 0.1, "cy": 0.2, "h": 0.03}, "글 줄", 7, None, {"cx": 0.1}, ["x"], {"text": 5}])
        self.assertEqual(result.texts, ("객체 줄", "글 줄"))
        self.assertEqual(result.filtered, 5)

    def test_a_list_is_required_and_anything_else_is_an_empty_result(self):
        for bad in (None, "글", 5, {"text": "x"}, object()):
            result = po.prepare(bad)
            self.assertEqual((result.found, result.filtered, result.over_limit), (0, 0, 0))

    def test_the_result_is_a_value_that_cannot_be_changed(self):
        result = po.prepare(["가"])
        with self.assertRaises(Exception):
            result.filtered = 3

    def test_the_same_input_gives_the_same_result(self):
        lines = ["가 나", "다", "다", "라" * 300, ""]
        self.assertEqual(po.prepare(lines), po.prepare(list(lines)))

    def test_digits_in_a_line_ask_for_the_number_reminder(self):
        self.assertTrue(po.has_digits(["공기밥 1,000원"]))
        self.assertTrue(po.has_digits(["가", "０１０"]))
        self.assertFalse(po.has_digits(["한우 불고기", "된장"]))
        self.assertFalse(po.has_digits([]))
        self.assertFalse(po.has_digits([5, None]))


class ApplyTest(unittest.TestCase):
    def test_the_lines_become_unconfirmed_candidates_and_the_photo_confirmation_is_released(self):
        manifest = pm.set_confirmed(build(2), "p001", True)
        updated, result = po.apply(manifest, "p001", ["한우 불고기", "", "가격 12,000"])
        photo = updated.photo("p001")
        self.assertEqual([(item.text, item.confirmed) for item in photo.visible_text], [("한우 불고기", False), ("가격 12,000", False)])
        self.assertEqual((photo.analysis_method, photo.confirmed_by_user, photo.observed_objects), (po.METHOD, False, ()))
        self.assertEqual((result.found, result.blank, result.filtered), (2, 1, 0))
        self.assertEqual(updated.photo("p002"), manifest.photo("p002"), "다른 사진은 그대로")

    def test_a_new_reading_replaces_the_old_one_including_what_the_user_confirmed(self):
        manifest, _result = po.apply(build(), "p001", ["가", "나"])
        manifest = pm.confirm_item(manifest, "p001", pm.TEXTS, 0, True)
        manifest, _result = po.apply(manifest, "p001", ["다"])
        self.assertEqual([(item.text, item.confirmed) for item in manifest.photo("p001").visible_text], [("다", False)])

    def test_sixty_lines_fit_and_the_sixty_first_is_counted_as_cut(self):
        manifest, result = po.apply(build(), "p001", [f"줄 {number}" for number in range(61)])
        self.assertEqual((len(manifest.photo("p001").visible_text), result.over_limit, result.filtered), (60, 1, 0))

    def test_the_method_name_passes_the_existing_rule_and_is_not_manual(self):
        self.assertRegex(po.METHOD, r"local:[a-z0-9][a-z0-9._-]{0,39}")
        self.assertNotEqual(po.METHOD, pm.METHOD_MANUAL)

    def test_the_manifest_may_drop_more_and_the_count_is_added(self):
        """다듬기가 놓친 줄을 `set_analysis` 가 버리면 거른 수에 더한다(두 번째 방어선)."""
        manifest = build()
        original = pm.set_analysis
        calls = []

        def stingy(man, photo_id, **kwargs):
            calls.append(kwargs)
            updated, _dropped = original(man, photo_id, **kwargs)
            return updated, 2

        pm.set_analysis = stingy
        try:
            _updated, result = po.apply(manifest, "p001", ["가", "나"])
        finally:
            pm.set_analysis = original
        self.assertEqual((result.filtered, calls[0]["method"]), (2, po.METHOD))

    def test_the_saved_form_never_carries_the_read_text(self):
        manifest, _result = po.apply(build(), "p001", ["비밀 아닌 글", "가격 100"])
        saved = manifest.to_dict(False)
        self.assertEqual((saved["photos"][0]["visible_text"], saved["photos"][0]["analysis_method"]), ([], pm.METHOD_MANUAL))
        self.assertNotIn("비밀 아닌 글", manifest.to_text(False))


class LimitSplitTest(unittest.TestCase):
    def test_the_two_limits_are_pinned_as_literal_numbers(self):
        self.assertEqual((pm.MAX_TEXT_ITEMS, pm.MAX_OBJECT_ITEMS, pm.MAX_OBSERVATIONS, pm.MAX_OBSERVATION_CHARS), (60, 20, 20, 200))
        self.assertEqual((pm.item_limit(pm.TEXTS), pm.item_limit(pm.OBJECTS)), (60, 20))
        self.assertEqual((po.MAX_LINES, po.MAX_LINE_CHARS), (60, 200))

    def test_the_text_column_holds_sixty_and_the_object_column_twenty(self):
        manifest = build()
        updated, dropped = pm.set_analysis(manifest, "p001", method="local:x", texts=[f"글{n}" for n in range(61)], objects=[f"물건{n}" for n in range(21)])
        photo = updated.photo("p001")
        self.assertEqual((len(photo.visible_text), len(photo.observed_objects), dropped), (60, 20, 2))

    def test_the_boundaries_are_exact(self):
        manifest = build()
        updated, dropped = pm.set_analysis(manifest, "p001", method="local:x", texts=[f"글{n}" for n in range(60)], objects=[f"물건{n}" for n in range(20)])
        self.assertEqual((len(updated.photo("p001").visible_text), len(updated.photo("p001").observed_objects), dropped), (60, 20, 0))

    def test_a_saved_file_is_read_with_the_same_limits(self):
        manifest = build()
        raw = manifest.to_dict(True)
        raw["photos"][0]["visible_text"] = [{"text": f"글{n}", "confirmed": False} for n in range(60)]
        self.assertEqual(len(pm.PhotoManifest.from_dict(raw).photo("p001").visible_text), 60)
        raw["photos"][0]["visible_text"] = [{"text": f"글{n}", "confirmed": False} for n in range(61)]
        refused(pm.PhotoManifest.from_dict, raw)
        raw["photos"][0]["visible_text"] = []
        raw["photos"][0]["observed_objects"] = [{"text": f"물건{n}", "confirmed": False} for n in range(21)]
        refused(pm.PhotoManifest.from_dict, raw)

    def test_the_refusal_names_the_limit_of_that_column(self):
        raw = build().to_dict(True)
        raw["photos"][0]["visible_text"] = [{"text": f"글{n}", "confirmed": False} for n in range(61)]
        self.assertIn("60개", str(refused(pm.PhotoManifest.from_dict, raw).slots))
        raw["photos"][0]["visible_text"] = []
        raw["photos"][0]["observed_objects"] = [{"text": f"물건{n}", "confirmed": False} for n in range(21)]
        self.assertIn("20개", str(refused(pm.PhotoManifest.from_dict, raw).slots))


class RemoveItemTest(unittest.TestCase):
    def setUp(self):
        self.manifest = pm.set_confirmed(read(build(), ["가", "나", "다"]), "p001", True)

    def test_the_item_leaves_the_list_and_the_confirmation_is_released(self):
        updated = pm.remove_item(self.manifest, "p001", pm.TEXTS, 1)
        self.assertEqual(texts_of(updated), ["가", "다"])
        self.assertFalse(updated.photo("p001").confirmed_by_user)

    def test_the_first_and_last_can_be_removed_and_the_last_one_leaves_an_empty_list(self):
        self.assertEqual(texts_of(pm.remove_item(self.manifest, "p001", pm.TEXTS, 0)), ["나", "다"])
        self.assertEqual(texts_of(pm.remove_item(self.manifest, "p001", pm.TEXTS, 2)), ["가", "나"])
        one = read(build(), ["하나"])
        self.assertEqual(texts_of(pm.remove_item(one, "p001", pm.TEXTS, 0)), [])

    def test_the_other_confirmations_are_kept(self):
        manifest = pm.confirm_item(self.manifest, "p001", pm.TEXTS, 2, True)
        updated = pm.remove_item(manifest, "p001", pm.TEXTS, 0)
        self.assertEqual([(item.text, item.confirmed) for item in updated.photo("p001").visible_text], [("나", False), ("다", True)])

    def test_the_original_manifest_is_not_changed(self):
        before = self.manifest.to_dict(True)
        pm.remove_item(self.manifest, "p001", pm.TEXTS, 0)
        self.assertEqual(self.manifest.to_dict(True), before)

    def test_a_bad_number_or_kind_or_photo_is_refused(self):
        for index in (-1, 3, 99, True, None, "0", 1.0):
            self.assertEqual(refused(pm.remove_item, self.manifest, "p001", pm.TEXTS, index).code, "CONTENT_INVALID", index)
        self.assertEqual(refused(pm.remove_item, self.manifest, "p001", "zzz", 0).code, "CONTENT_INVALID")
        self.assertEqual(refused(pm.remove_item, self.manifest, "p009", pm.TEXTS, 0).code, "CONTENT_INVALID")

    def test_the_other_column_and_other_photos_are_untouched(self):
        manifest, _dropped = pm.set_analysis(build(2), "p001", method="local:x", texts=["가", "나"], objects=["의자"])
        updated = pm.remove_item(manifest, "p001", pm.TEXTS, 0)
        self.assertEqual((texts_of(updated), texts_of(updated, kind=pm.OBJECTS)), (["나"], ["의자"]))
        self.assertEqual(updated.photo("p002"), manifest.photo("p002"))

    def test_the_saved_form_is_the_same_before_and_after(self):
        manifest = read(build(), ["가", "나"])
        self.assertEqual(pm.remove_item(manifest, "p001", pm.TEXTS, 0).to_dict(False), manifest.to_dict(False))


class MergeItemsTest(unittest.TestCase):
    def setUp(self):
        self.manifest = pm.set_confirmed(read(build(), ["한우 불고기", "12,000", "공기밥"]), "p001", True)

    def test_two_lines_become_one_unconfirmed_line_joined_by_one_space(self):
        manifest = pm.confirm_item(self.manifest, "p001", pm.TEXTS, 0, True)
        updated = pm.merge_items(manifest, "p001", pm.TEXTS, 0)
        self.assertEqual([(item.text, item.confirmed) for item in updated.photo("p001").visible_text], [("한우 불고기 12,000", False), ("공기밥", False)])
        self.assertFalse(updated.photo("p001").confirmed_by_user)

    def test_the_second_from_last_can_be_merged_and_the_last_cannot(self):
        self.assertEqual(texts_of(pm.merge_items(self.manifest, "p001", pm.TEXTS, 1)), ["한우 불고기", "12,000 공기밥"])
        self.assertEqual(refused(pm.merge_items, self.manifest, "p001", pm.TEXTS, 2).code, "CONTENT_INVALID")

    def test_merging_releases_the_photo_confirmation_just_like_removing_does(self):
        """검증 S SP-17 — 글이 바뀌면(두 줄을 이으면) 사진 확정이 풀린다. 확정된 사진에서 곧바로 이어도 풀려야 한다(항목 확인을 거치지 않은 경우)."""
        self.assertIs(self.manifest.photo("p001").confirmed_by_user, True, "대조 — 이은 줄이 아직 없을 때 사진은 확정된 상태다")
        for index in (0, 1):
            with self.subTest(index=index):
                merged = pm.merge_items(self.manifest, "p001", pm.TEXTS, index)
                self.assertIs(merged.photo("p001").confirmed_by_user, False)
                self.assertEqual([item.confirmed for item in merged.photo("p001").visible_text], [False, False])
        manifest, _dropped = pm.set_analysis(build(), "p001", method="local:x", objects=["의자", "탁자"])
        manifest = pm.set_confirmed(manifest, "p001", True)
        self.assertIs(pm.merge_items(manifest, "p001", pm.OBJECTS, 0).photo("p001").confirmed_by_user, False, "대상 칸도 같다")

    def test_a_bad_number_is_refused(self):
        for index in (-1, 3, True, None, "0"):
            self.assertEqual(refused(pm.merge_items, self.manifest, "p001", pm.TEXTS, index).code, "CONTENT_INVALID", index)

    def test_the_joined_text_goes_through_the_entry_check_and_both_lines_stay_when_it_fails(self):
        too_long = read(build(), ["가" * 150, "나" * 100])
        self.assertEqual(refused(pm.merge_items, too_long, "p001", pm.TEXTS, 0).code, "CONTENT_INVALID")
        self.assertEqual(texts_of(too_long), ["가" * 150, "나" * 100])
        resident = read(build(), list(RESIDENT))
        self.assertEqual(refused(pm.merge_items, resident, "p001", pm.TEXTS, 0).code, "CONTENT_INVALID", "따로는 평범한 숫자, 이으면 주민번호 모양")
        self.assertEqual(texts_of(resident), list(RESIDENT))

    def test_exactly_two_hundred_characters_can_be_joined(self):
        manifest = read(build(), ["가" * 100, "나" * 99])
        self.assertEqual(len(texts_of(pm.merge_items(manifest, "p001", pm.TEXTS, 0))[0]), 200)

    def test_the_reason_never_repeats_the_text(self):
        resident = read(build(), list(RESIDENT))
        error = refused(pm.merge_items, resident, "p001", pm.TEXTS, 0)
        self.assertNotIn(RESIDENT[1], str(error.slots) + error.detail)

    def test_the_original_manifest_is_not_changed_and_the_saved_form_is_the_same(self):
        manifest = read(build(), ["가", "나", "다"])
        before = manifest.to_dict(True)
        updated = pm.merge_items(manifest, "p001", pm.TEXTS, 0)
        self.assertEqual(manifest.to_dict(True), before)
        self.assertEqual(updated.to_dict(False), manifest.to_dict(False))

    def test_the_object_column_still_refuses_a_guess_about_a_person(self):
        manifest, _dropped = pm.set_analysis(build(), "p001", method="local:x", objects=["의자", "탁자"])
        self.assertEqual(texts_of(pm.merge_items(manifest, "p001", pm.OBJECTS, 0), kind=pm.OBJECTS), ["의자 탁자"])


class DiffersFromTest(unittest.TestCase):
    def board_with(self, manifest):
        board = pv.PhotoBoard()
        board.load(manifest)
        return board

    def test_reading_text_is_not_an_unsaved_change(self):
        saved = build(2)
        board = self.board_with(saved)
        self.assertFalse(board.differs_from(saved))
        board.manifest, _result = po.apply(board.manifest, "p001", ["한우 불고기", "12,000"])
        self.assertFalse(board.differs_from(saved), "읽은 글은 저장하지 않는다 — 저장 안 한 변경이 아니다")
        board.manifest = pm.confirm_item(board.manifest, "p001", pm.TEXTS, 0, True)
        board.manifest = pm.remove_item(board.manifest, "p001", pm.TEXTS, 1)
        self.assertFalse(board.differs_from(saved))

    def test_a_real_change_still_counts_even_with_read_text_present(self):
        saved = build(2)
        board = self.board_with(saved)
        board.manifest, _result = po.apply(board.manifest, "p001", ["글"])
        board.manifest = pm.update_photo(board.manifest, "p001", user_note="새 메모")
        self.assertTrue(board.differs_from(saved))

    def test_a_released_confirmation_counts_because_the_confirmation_is_saved(self):
        saved = pm.set_confirmed(build(2), "p001", True)
        board = self.board_with(saved)
        self.assertFalse(board.differs_from(saved))
        board.manifest, _result = po.apply(board.manifest, "p001", ["글"])
        self.assertTrue(board.differs_from(saved), "읽으면 확정이 풀리고, 확정은 저장하는 값이다")

    def test_the_old_behaviour_for_the_other_cases_is_kept(self):
        saved = build(2)
        board = self.board_with(saved)
        board.manifest = pm.remove_photo(board.manifest, "p002")
        self.assertTrue(board.differs_from(saved))
        self.assertFalse(self.board_with(pm.empty_manifest()).differs_from(None))
        self.assertTrue(self.board_with(build(1)).differs_from(None))
        self.assertTrue(self.board_with(build(1)).differs_from("x"))

    def test_without_any_analysis_the_new_rule_gives_exactly_the_old_answer_for_random_lists(self):
        """동작 불변(라운드 2) — 분석 칸이 없는 목록끼리는 새 규칙(저장하는 모양끼리)과 옛 규칙(데이터클래스 같음)의 답이 늘 같다. 글자 읽기를 안 쓰면 '저장 안 한 변경' 판정이 한 글자도 안 바뀐다. 씨앗을 고정한 무작위 300쌍."""
        import dataclasses
        import random
        rng = random.Random(20261122)
        kinds = ("메뉴판", "간판", "음식", "기타")
        seen = {True: 0, False: 0}
        for _ in range(300):
            base = pm.empty_manifest()
            for number in range(1, rng.randint(0, 4) + 1):
                base, _id = pm.add_photo(base, path_of(number), photo_type=rng.choice(kinds), user_note=rng.choice(("", "메모", "다른 메모")))
            other = base
            fresh = [20]                                                                      # 새로 넣는 사진의 파일 번호(겹치지 않게 늘기만 한다)
            for _step in range(rng.randint(0, 3)):
                if not other.photos:
                    other, _id = pm.add_photo(other, path_of(fresh[0]), photo_type=rng.choice(kinds))
                    fresh[0] += 1
                    continue
                photo_id = rng.choice(other.photos).photo_id
                action = rng.choice(("note", "confirm", "remove", "type", "setting", "move", "add"))
                if action == "note":
                    other = pm.update_photo(other, photo_id, user_note=rng.choice(("", "메모", "새 메모")))
                elif action == "confirm":
                    other = pm.set_confirmed(other, photo_id, rng.choice((True, False)))
                elif action == "remove":
                    other = pm.remove_photo(other, photo_id)
                elif action == "type":
                    other = pm.update_photo(other, photo_id, photo_type=rng.choice(kinds))
                elif action == "setting":
                    other = pm.update_photo(other, photo_id, setting=rng.choice(("", "실내", "야경")))
                elif action == "move" and len(other.photos) > 1:
                    other = pm.move_photo(other, photo_id, rng.randint(1, len(other.photos)))
                elif action == "add" and len(other.photos) < 6:
                    other, _id = pm.add_photo(other, path_of(fresh[0]), photo_type=rng.choice(kinds))
                    fresh[0] += 1
            old_answer = dataclasses.replace(other, draft_id="") != dataclasses.replace(base, draft_id="")
            board = pv.PhotoBoard()
            board.load(other)
            self.assertEqual(board.differs_from(base), old_answer)
            seen[old_answer] += 1
        self.assertTrue(seen[True] > 30 and seen[False] > 30, f"표본이 한쪽으로 치우쳤다: {seen}")

    def test_the_draft_number_is_still_not_compared(self):
        saved = build(1)
        board = self.board_with(saved)
        import dataclasses
        board.manifest = dataclasses.replace(saved, draft_id="dd-" + "0123456789abcdef0123")
        self.assertFalse(board.differs_from(saved))


class PureFileTest(unittest.TestCase):
    def test_the_rule_file_uses_no_file_network_clock_or_process(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported - {"__future__"}, {"re", "dataclasses"})
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertFalse(names & {"open", "print", "input", "exec", "eval"})

    def test_the_file_has_no_tilde_or_web_address(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("~", text)
        self.assertNotIn("http", text.lower())


if __name__ == "__main__":
    unittest.main()
