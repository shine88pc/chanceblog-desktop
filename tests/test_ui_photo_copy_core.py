"""본문에 사진 자리가 있는 초안의 복사(컨트롤러·관문 — 사진 연동 3단계, 순수 층) 시험.

지키는 것:
  1) `본문 복사`·`전체 복사` 는 정확한 `{{사진 N}}` 을 `[이미지 N]` 으로 바꿔 복사한다(그 밖의 글은 한 글자도 안 바뀐다). 제목·키워드·태그·요약 복사는 그대로다.
  2) 복사 전 확인창은 어긋남(없는 사진·확정 안 한 사진·본문에 없는 사진·되풀이·순서·정확하지 않은 중괄호)을 **번호로만** 보이고, 어긋남이 없으면 올릴 사진 순서를 번호와 짧은 파일 이름으로 보인다(경로 없음). 한 번 확인하면 같은 줄은 다시 묻지 않는다.
  3) 사진도 자리표시자도 없으면 관문은 지금과 같다. 키·토큰 모양은 여전히 막는다.
"""
import dataclasses
import sys
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


if __name__ == "__main__":
    unittest.main()
