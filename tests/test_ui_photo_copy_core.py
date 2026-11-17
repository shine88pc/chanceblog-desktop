"""본문에 사진 자리가 있는 초안의 복사(컨트롤러·관문 — 사진 연동 3단계, 순수 층) 시험.

지키는 것:
  1) `본문 복사`·`전체 복사` 는 정확한 `{{사진 N}}` 을 `[이미지 N]` 으로 바꿔 복사한다(그 밖의 글은 한 글자도 안 바뀐다). 제목·키워드·태그·요약 복사는 그대로다.
  2) 복사 전 확인창은 어긋남(없는 사진·확정 안 한 사진·본문에 없는 사진·되풀이·순서·정확하지 않은 중괄호)을 **번호로만** 보이고, 어긋남이 없으면 올릴 사진 순서를 번호와 짧은 파일 이름으로 보인다(경로 없음). 한 번 확인하면 같은 줄은 다시 묻지 않는다.
  3) 사진도 자리표시자도 없으면 관문은 지금과 같다. 키·토큰 모양은 여전히 막는다.
"""
import dataclasses
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ui_drafts_save_core import drive, made_saving  # noqa: E402
from test_ui_photo_make_core import confirm  # noqa: E402
from test_ui_photo_save_core import path_of  # noqa: E402

from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.ui.core import draft_rules as rules  # noqa: E402
from chanceblog_desktop.ui.core import text  # noqa: E402

T = text.T
NAME = {1: "UNIQ-FILE-s3x1-01.jpg", 2: "UNIQ-FILE-s3x1-02.jpg", 3: "UNIQ-FILE-s3x1-03.jpg"}


def with_photos(confirmed=(1, 2), count=3):
    """사진을 넣고 확정한 뒤 다시 만들어 본문에 사진 자리가 들어간 컨트롤러."""
    controller, provider = made_saving()
    controller.photos.add_paths([path_of(number) for number in range(1, count + 1)])
    for number in confirmed:
        confirm(controller, number, user_subject=f"대상 {number}")
    drive(controller)
    return controller, provider


BS = chr(92)
WINUSER = "UNIQ-WINUSER-cy41"
PATH = "C:" + BS + "Users" + BS + WINUSER + BS + "Pictures" + BS + "간판.jpg"


def name_of(number):
    return f"UNIQ-FILE-s3x1-{number:02d}.jpg"


def with_note(note, count=2):
    """첫 사진의 메모에 `note` 를 적고 확정한 사진 `count` 장으로 다시 만든 글."""
    controller, _provider = made_saving()
    controller.photos.add_paths([path_of(number) for number in range(1, count + 1)])
    confirm(controller, 1, user_subject="매장 입구 간판", user_note=note)
    for number in range(2, count + 1):
        confirm(controller, number, user_subject=f"대상 {number}")
    drive(controller)
    return controller


def copied(controller, item):
    """복사 단추를 누르고 확인창이 뜨면 `그래도 복사` 까지 눌러 복사된 글을 돌려준다."""
    decision, content = controller.copy_decision(item)
    if decision == "confirm":
        return controller.confirm_copy(item)
    return content if decision == "copy" else None


class ConvertTest(unittest.TestCase):
    def test_body_and_all_copies_turn_the_slots_into_image_marks_and_nothing_else_changes(self):
        controller, _provider = with_photos()
        self.assertEqual(sorted(number for number, _s, _e in pm.find_placeholders(controller.body)), [1, 2])
        body = copied(controller, "body")
        self.assertNotIn("{{", body)
        self.assertIn("[이미지 1]", body)
        self.assertIn("[이미지 2]", body)
        self.assertEqual(body, controller.body.replace("{{사진 1}}", "[이미지 1]").replace("{{사진 2}}", "[이미지 2]"))
        everything = copied(controller, "all")
        self.assertEqual(everything, controller.title + chr(10) + chr(10) + body)

    def test_title_keywords_tags_and_summary_copies_are_untouched(self):
        controller, _provider = with_photos()
        self.assertEqual(copied(controller, "title"), controller.title)
        names = [name for name, _items in controller.gate("title").reasons]
        self.assertFalse({"photos", "uploads"} & set(names), "제목 복사의 확인창에는 사진 줄이 없다")
        for item in ("keywords", "tags", "summary"):
            decision, content = controller.copy_decision(item)
            self.assertEqual((decision, content), ("copy", controller.text_for(item)))

    def test_stray_braces_the_user_typed_stay_as_typed_and_are_reported(self):
        controller, _provider = with_photos()
        controller.set_body(controller.body + "\n\n{{ 이름 }} 님께 드립니다")
        lines, uploads = controller.photo_gate_lines("body")
        self.assertEqual(lines, (T["pho_gate_stray"].format(n=2),))
        self.assertEqual(uploads, ())
        body = copied(controller, "body")
        self.assertIn("{{ 이름 }} 님께 드립니다", body)
        self.assertNotIn("{{사진", body)


class GateTest(unittest.TestCase):
    def test_the_gate_shows_the_upload_order_by_number_and_short_name_and_asks_only_once(self):
        controller, _provider = with_photos()
        gate = controller.gate("body")
        reasons = dict(gate.reasons)
        self.assertEqual(reasons["uploads"], (T["pho_gate_upload_line"].format(n=1, name=NAME[1]), T["pho_gate_upload_line"].format(n=2, name=NAME[2])))
        self.assertNotIn("photos", reasons, "어긋남이 없다")
        self.assertEqual(gate.count, sum(len(items) for name, items in gate.reasons if name != "uploads"), "올릴 사진 줄은 '확인 권장 N건' 에 세지 않는다")
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(decision, "confirm")
        self.assertIn(T["pho_gate_uploads"].format(n=2), dialog["body"])
        self.assertIn(NAME[1], dialog["body"])
        self.assertNotIn("UNIQ-USERDIR", dialog["body"] + dialog["title"], "경로는 없다")
        self.assertIsNotNone(controller.confirm_copy("body"))
        self.assertEqual(controller.copy_decision("body")[0], "copy", "한 번 확인했으면 같은 줄은 다시 묻지 않는다")
        self.assertEqual(controller.copy_decision("all")[0], "copy", "전체 복사도 같은 확인을 쓴다")

    def test_a_dialog_with_only_the_upload_order_is_the_soft_info_dialog(self):
        controller, _provider = with_photos()
        gate = rules.Gate(False, (("uploads", (T["pho_gate_upload_line"].format(n=1, name="a.jpg"),)),), True, {"uploads": {"x"}})
        dialog = controller.gate_dialog("body", gate)
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"], dialog["count"]), (T["pho_upload_title"], T["pho_upload_ok"], T["drf_cancel"], 0))
        self.assertIn(T["pho_upload_tail"], dialog["body"])
        many = rules.Gate(False, (("uploads", tuple(T["pho_gate_upload_line"].format(n=number, name="a.jpg") for number in range(1, 13))),), True, {"uploads": set()})
        body = controller.gate_dialog("body", many)["body"]
        self.assertEqual(sum(1 for line in body.splitlines() if line.startswith("· [이미지 ")), 8)
        self.assertIn(T["drf_gate_more"].format(n=4), body)

    def test_when_the_other_reasons_were_already_read_a_new_upload_order_still_opens_the_dialog_once(self):
        controller, _provider = with_photos()
        for name, keys in controller.gate("body").keys.items():
            if name != "uploads":
                controller.ack.setdefault(name, set()).update(keys)                       # 확인 권장·분야·고친 글 확인은 이미 읽었다
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(decision, "confirm", "올릴 사진 순서가 처음이면 그것만으로도 창이 뜬다")
        self.assertIn(T["pho_gate_uploads"].format(n=2), dialog["body"])
        self.assertIsNotNone(controller.confirm_copy("body"))
        self.assertEqual(controller.copy_decision("body")[0], "copy", "한 번 읽었으면 다시 묻지 않는다")
        confirm_again = with_photos(confirmed=(1,))[0]
        for name, keys in confirm_again.gate("body").keys.items():
            if name != "uploads":
                confirm_again.ack.setdefault(name, set()).update(keys)
        confirm_again.copy_decision("body")
        confirm_again.confirm_copy("body")
        confirm_again.photos.add_paths([path_of(9)])
        confirm(confirm_again, 4, user_subject="새 사진")
        drive(confirm_again)
        self.assertEqual(confirm_again.copy_decision("body")[0], "confirm", "올릴 사진이 달라지면 새 줄이니 한 번 더 알린다")

    def test_every_kind_of_mismatch_is_listed_by_number_only(self):
        controller, _provider = with_photos(confirmed=(1, 2, 3))
        self.assertEqual(controller.photo_gate_lines("body")[0], ())
        confirm(controller, 3)
        controller.photos.set_text("p001", "user_note", "고침")                              # 확정이 풀린다 → 본문에는 자리가 남아 있다
        self.assertEqual(controller.photo_gate_lines("body")[0], (T["pho_gate_unconfirmed"].format(numbers="1"),))
        controller.photos.remove("p002")
        lines = controller.photo_gate_lines("body")[0]
        self.assertEqual(lines, (T["pho_gate_dangling"].format(numbers="2"), T["pho_gate_unconfirmed"].format(numbers="1")))
        controller, _provider = with_photos(confirmed=(1, 2))
        confirm(controller, 3)
        self.assertEqual(controller.photo_gate_lines("body")[0], (T["pho_gate_missing"].format(numbers="3"),))
        controller.set_body(controller.body.replace("{{사진 3}}", "") + "\n\n{{사진 1}}")
        self.assertEqual(controller.photo_gate_lines("body")[0], (T["pho_gate_missing"].format(numbers="3"), T["pho_gate_repeated"].format(numbers="1")))
        controller, _provider = with_photos(confirmed=(1, 2))
        controller.photos.move("p002", -1)
        self.assertEqual(controller.photo_gate_lines("body")[0], (T["pho_gate_order"],))

    def test_a_mismatch_hides_the_upload_list_and_is_shown_in_the_check_dialog_without_a_path(self):
        controller, _provider = with_photos()
        confirm(controller, 3)
        gate = controller.gate("body")
        names = [name for name, _items in gate.reasons]
        self.assertIn("photos", names)
        self.assertNotIn("uploads", names)
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(decision, "confirm")
        self.assertIn(T["pho_gate_photos"].format(n=1), dialog["body"])
        self.assertIn(T["pho_gate_missing"].format(numbers="3"), dialog["body"])
        self.assertNotIn("UNIQ-", dialog["body"], "번호뿐이다 — 파일 이름·경로 없음")
        self.assertEqual(dataclasses.replace(gate).blocked, False)

    def test_the_title_copy_never_asks_about_photos(self):
        controller, _provider = with_photos(confirmed=(1, 2))
        confirm(controller, 3)
        self.assertEqual(controller.photo_gate_lines("title"), ((), ()))
        self.assertEqual(controller.photo_gate_lines("tags"), ((), ()))

    def test_without_photos_and_without_slots_the_gate_is_what_it_was(self):
        controller, _provider = made_saving()
        self.assertEqual(controller.photo_gate_lines("body"), ((), ()))
        self.assertEqual(controller.photo_gate_lines("all"), ((), ()))
        names = [name for name, _items in controller.gate("body").reasons]
        self.assertFalse({"photos", "uploads"} & set(names))
        self.assertEqual(controller.final_text("body"), controller.body)
        controller.photos.add_paths([path_of(1)])
        self.assertEqual(controller.photo_gate_lines("body")[0], (), "확정하지 않은 사진은 본문에 안 들어가니 어긋남이 아니다")

    def test_braces_in_a_body_without_photos_or_photo_slots_are_not_the_photo_gates_business(self):
        controller, _provider = made_saving()
        controller.set_body(controller.body + chr(10) * 2 + "{{이름}} 님께 {{ 주소 }} 로 보내요")
        self.assertEqual(controller.photo_gate_lines("body"), ((), ()), "사진 기능을 안 쓰는 글의 중괄호는 글 모양 점검만 본다 — 복사 관문은 지금과 같다")
        self.assertFalse({"photos", "uploads"} & {name for name, _items in controller.gate("body").reasons})
        self.assertEqual(controller.final_text("body"), controller.body, "복사할 글도 그대로")

    def test_a_key_shape_in_the_body_still_blocks_the_copy_even_with_photos(self):
        controller, _provider = with_photos()
        controller.set_body(controller.body + "\n\n내 키는 AIza" + "A" * 35 + " 입니다")
        decision, _content = controller.copy_decision("body")
        self.assertEqual(decision, "blocked")
        self.assertIsNone(controller.final_text("body"))


class PathNoteTest(unittest.TestCase):
    """메모·대상·설명 글에 붙여 넣은 파일 경로(검증 S PS-4, 설계 부록 3) — 막지 않고 복사 확인창에 한 줄로 알린다. 경로 글은 창 어디에도 안 보이고, 사진을 안 쓰는 글은 지금과 같다."""

    def test_a_path_pasted_into_a_memo_gets_one_info_line_in_the_dialog_and_the_path_is_not_in_the_dialog(self):
        controller = with_note("원본 위치 " + PATH)
        self.assertIn(PATH, controller.body, "메모가 본문에 그대로 들어간다(이 시험의 전제)")
        self.assertEqual(controller.photo_gate_notes("body"), (T["pho_gate_paths"],))
        self.assertEqual(controller.photo_gate_notes("all"), (T["pho_gate_paths"],))
        self.assertEqual(controller.photo_gate_notes("title"), (), "제목 복사에는 없다")
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(decision, "confirm")
        self.assertEqual(dialog["body"].count(T["pho_gate_paths"]), 1)
        for leak in (PATH, WINUSER, "Pictures", "간판.jpg"):
            self.assertNotIn(leak, dialog["title"] + dialog["body"], "경로 글은 창에 되풀이하지 않는다")

    def test_a_memo_that_is_an_experience_sentence_gets_the_line_too(self):
        controller = with_note("비 오는 날 직접 찍었어요 " + PATH)
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(decision, "confirm")
        self.assertIn(T["pho_gate_paths"], dialog["body"])

    def test_the_line_is_for_information_so_it_is_not_counted_in_the_title_and_is_asked_only_once(self):
        controller = with_note("원본 위치 " + PATH)
        gate = controller.gate("body")
        self.assertIn("paths", [name for name, _items in gate.reasons])
        self.assertEqual(gate.count, sum(len(items) for name, items in gate.reasons if name not in ("uploads", "paths")), "알려 드리는 줄은 '확인 권장 N건' 에 세지 않는다")
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(dialog["title"], T["drf_gate_title"].format(n=gate.count))
        self.assertIsNotNone(controller.confirm_copy("body"))
        self.assertEqual(controller.copy_decision("body")[0], "copy", "한 번 알렸으면 다시 묻지 않는다")
        self.assertEqual(controller.copy_decision("all")[0], "copy", "전체 복사도 같은 확인을 쓴다")

    def test_the_copy_is_not_blocked_and_the_path_goes_into_the_copied_text_as_typed(self):
        controller = with_note("원본 위치 " + PATH)
        self.assertIn(PATH, copied(controller, "body"), "막지도 지우지도 않는다 — 알리기만 한다")

    def test_a_memo_without_a_path_gets_no_line(self):
        controller = with_note("원본 위치는 따로 없어요")
        self.assertEqual(controller.photo_gate_notes("body"), ())
        self.assertNotIn("paths", [name for name, _items in controller.gate("body").reasons])

    def test_a_draft_without_photos_is_what_it_was_even_with_a_path_in_the_text(self):
        controller, _provider = made_saving()
        before = [name for name, _items in controller.gate("body").reasons]
        controller.set_body(controller.body + chr(10) * 2 + "원본 위치 " + PATH)
        self.assertEqual(controller.photo_gate_notes("body"), ())
        self.assertEqual([name for name, _items in controller.gate("body").reasons], before, "사진 기능을 안 쓰는 글의 관문은 지금과 같다")
        self.assertEqual(controller.final_text("body"), controller.body)

    def test_a_listed_photo_that_is_not_placed_yet_still_counts_as_using_the_photo_feature(self):
        controller, _provider = made_saving()
        controller.photos.add_paths([path_of(1)])
        controller.set_body(controller.body + chr(10) * 2 + "원본 위치 " + PATH)
        self.assertEqual(controller.photo_gate_notes("body"), (T["pho_gate_paths"],))


class InfoDialogTest(unittest.TestCase):
    """알려 드리는 줄(올릴 사진 순서·경로 안내)만 있는 창은 부드러운 안내창이고, 섞인 창에는 경로 줄이 건수 머리 없이 한 줄이며 `[이미지 N]` 설명이 끝 안내 앞에 있다(검증 Q PQ-9)."""

    def info_gate(self, *names):
        groups = {"uploads": tuple(T["pho_gate_upload_line"].format(n=number, name="a.jpg") for number in (1, 2)), "paths": (T["pho_gate_paths"],)}
        return rules.Gate(False, tuple((name, groups[name]) for name in names), True, {name: set(groups[name]) for name in names})

    def test_the_upload_order_with_the_path_line_is_one_soft_dialog_and_the_line_comes_before_the_mark_explanation(self):
        controller, _provider = with_photos()
        dialog = controller.gate_dialog("body", self.info_gate("uploads", "paths"))
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"], dialog["count"]), (T["pho_upload_title"], T["pho_upload_ok"], T["drf_cancel"], 0))
        lines = dialog["body"].splitlines()
        self.assertEqual(lines[0], T["pho_gate_uploads"].format(n=2))
        self.assertEqual(lines[-2:], [T["pho_gate_paths"], T["pho_upload_tail"]])

    def test_the_path_line_alone_is_a_soft_dialog_with_its_own_title(self):
        controller, _provider = with_photos()
        dialog = controller.gate_dialog("body", self.info_gate("paths"))
        self.assertEqual(dialog, {"title": T["pho_paths_title"], "body": T["pho_gate_paths"], "ok": T["pho_upload_ok"], "cancel": T["drf_cancel"], "count": 0})

    def test_the_upload_order_alone_keeps_its_own_dialog(self):
        controller, _provider = with_photos()
        dialog = controller.gate_dialog("body", self.info_gate("uploads"))
        self.assertEqual(dialog["title"], T["pho_upload_title"])
        self.assertNotIn(T["pho_gate_paths"], dialog["body"])
        self.assertEqual(dialog["body"].splitlines()[-1], T["pho_upload_tail"])

    def test_in_the_mixed_dialog_the_path_line_has_no_head_and_the_image_marks_are_explained_before_the_closing_line(self):
        controller = with_note("원본 위치 " + PATH)
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(decision, "confirm")
        lines = dialog["body"].splitlines()
        self.assertTrue(set(name for name, _items in controller.gate("body").reasons) - {"uploads", "paths"}, "확인 권장이 함께 뜨는 섞인 창이다")
        self.assertTrue(lines[lines.index(T["pho_gate_paths"]) - 1].startswith("· [이미지 "), "경로 줄은 올릴 사진 줄 바로 뒤에 머리 없이 한 줄이다")
        self.assertEqual(lines[-3:], [T["pho_gate_paths"], T["pho_upload_tail"], T["drf_gate_tail"]])

    def test_a_mixed_dialog_without_an_upload_order_has_no_image_mark_explanation(self):
        controller, _provider = with_photos()
        confirm(controller, 3)                                                              # 확정했는데 본문에 자리가 없다 → 어긋남이 있어 올릴 사진 순서는 숨는다
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(decision, "confirm")
        self.assertNotIn("uploads", [name for name, _items in controller.gate("body").reasons])
        self.assertNotIn(T["pho_upload_tail"], dialog["body"])
        self.assertEqual(dialog["body"].splitlines()[-1], T["drf_gate_tail"])


class GateGroupTest(unittest.TestCase):
    def inspection(self):
        return types.SimpleNamespace(unchanged=False, claims=(), secret=False, places=())

    def test_notes_become_the_paths_group_which_is_info_only_and_asked_once(self):
        gate = rules.gate_for("body", self.inspection(), (), False, {}, notes=("줄",))
        self.assertEqual((gate.reasons, gate.count, gate.needs_dialog, gate.blocked), ((("paths", ("줄",)),), 0, True, False))
        again = rules.gate_for("body", self.inspection(), (), False, dict(gate.keys), notes=("줄",))
        self.assertEqual((again.reasons, again.needs_dialog), ((("paths", ("줄",)),), False), "확인했으면 같은 줄은 다시 묻지 않는다")
        self.assertEqual(rules.gate_for("body", self.inspection(), (), False, {}).reasons, (), "알릴 것이 없으면 그룹도 없다")
        self.assertEqual((rules.GATE_GROUPS[-2:], rules.INFO_GATE_GROUPS), (("uploads", "paths"), ("uploads", "paths")))


class UploadLinesTest(unittest.TestCase):
    """검증 Q PQ-6 — 복사 확인창의 '올릴 사진' 줄이 가장 흔한 창(확인 권장이 함께 뜨는 섞인 창)에서 시험되지 않았다."""

    def lines_of(self, dialog):
        return [line for line in dialog["body"].splitlines() if line.startswith("· [이미지 ")]

    def test_ten_photos_in_the_mixed_dialog_show_exactly_eight_lines_and_the_rest_as_a_count(self):
        controller, _provider = with_photos(confirmed=tuple(range(1, 11)), count=10)
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(decision, "confirm")
        self.assertTrue({name for name, _items in controller.gate("body").reasons} - {"uploads"}, "확인 권장이 함께 뜨는 섞인 창이다")
        lines = self.lines_of(dialog)
        self.assertEqual(len(lines), 8)
        self.assertEqual(lines[0], "· " + T["pho_gate_upload_line"].format(n=1, name=name_of(1)))
        self.assertEqual(lines[-1], "· " + T["pho_gate_upload_line"].format(n=8, name=name_of(8)))
        self.assertIn(T["pho_gate_uploads"].format(n=10), dialog["body"])
        self.assertIn(T["drf_gate_more"].format(n=2), dialog["body"])

    def test_with_no_photo_listed_the_slots_left_in_the_body_are_pointed_out(self):
        controller, _provider = with_photos()
        for photo_id in ("p001", "p002", "p003"):
            controller.photos.remove(photo_id)
        self.assertEqual(controller.photos.count, 0)
        self.assertEqual(sorted(number for number, _s, _e in pm.find_placeholders(controller.body)), [1, 2])
        self.assertEqual(controller.photo_gate_lines("body")[0], (T["pho_gate_dangling"].format(numbers="1, 2"),))
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(decision, "confirm")
        self.assertIn(T["pho_gate_photos"].format(n=1), dialog["body"])
        self.assertIn(T["pho_gate_dangling"].format(numbers="1, 2"), dialog["body"])

    def test_the_upload_order_follows_the_body_not_the_numbers(self):
        controller, _provider = with_photos(confirmed=(1, 2, 3), count=3)
        controller.photos.move("p003", -1)
        controller.photos.move("p003", -1)                                                  # 목록 순서 3·1·2 — 번호는 그대로
        drive(controller)
        self.assertEqual([number for number, _s, _e in pm.find_placeholders(controller.body)], [3, 1, 2])
        expected = tuple(T["pho_gate_upload_line"].format(n=number, name=name_of(number)) for number in (3, 1, 2))
        self.assertEqual(controller.photo_gate_lines("body"), ((), expected))

    def test_a_mismatch_counts_in_the_dialog_title(self):
        controller, _provider = with_photos()
        confirm(controller, 3)
        gate = controller.gate("body")
        self.assertIn("photos", [name for name, _items in gate.reasons])
        self.assertEqual(gate.count, sum(len(items) for name, items in gate.reasons if name != "uploads"), "어긋남 묶음은 '확인 권장 N건' 에 센다")
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(dialog["title"], T["drf_gate_title"].format(n=gate.count))
        self.assertGreaterEqual(gate.count, len(dict(gate.reasons)["photos"]))


if __name__ == "__main__":
    unittest.main()
