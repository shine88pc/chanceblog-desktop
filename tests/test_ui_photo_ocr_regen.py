"""저장해 둔 초안을 열어 '다시 만들기' 를 할 때 사진 속 글자 문단이 소리 없이 빠지지 않게 하는 화면 규칙(결정 D-517 ④, `ui/core/drafts_view.py`) — 순수 시험(PySide6 없음, 가짜 공급자만).
읽은 글은 저장하지 않는다(설계 4-3) — 그래서 저장해 둔 초안을 열면 사진 정보에는 읽은 글이 없고, 글을 안 고쳤으면 '다시 만들기' 에 확인창도 없어서 저장해 둔 글에 있던 '사진 속 글자' 문단이 새 글에서 조용히 빠졌다(독립 검증이 가장 먼저 볼 곳).

지키는 것:
  1) 글자 읽기를 쓸 수 있는 실행(컨트롤러가 붙어 있다)에서 저장해 둔 초안을 열었고 확정한 사진이 있는데 그 가운데 하나라도 지금 확정한 읽은 글이 없으면(부분만 읽은 때도 읽지 않은 사진의 문단이 빠진다 — 독립 검증 S SP-2), 글을 안 고쳤어도 '다시 만들기' 앞에 확인창이 먼저다(안 물은 채로는 시작하지 않는다).
  2) 걱정이 없는 때는 지금과 같다 — 글자 읽기가 없는 실행·이 세션에서 만든 글(열어 둔 글이 아니다)·확정한 사진이 없음·확정한 사진마다 확정한 읽은 글이 있음(새 글에 그 문단들이 다시 들어간다)·다시 만든 뒤.
  3) 글을 고친 때는 원래 확인창에 한 문장만 더한다(두 번 묻지 않는다). 그만두면 다시 눌렀을 때 또 묻는다.
  4) 글은 읽지 않는다 — 틀 문장을 코드로 찾지 않고 화면 쪽 신호(열었는가·컨트롤러·확정한 사진·확정한 줄)만 본다.
"""
import ast
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from test_ui_drafts_save_core import drive, saved_id  # noqa: E402
from test_ui_photo_save_core import confirm, store, with_photos  # noqa: E402

from chanceblog_desktop.ui.core import photo_ocr_panel as pp  # noqa: E402
from chanceblog_desktop.ui.core import photo_ocr_view as pov  # noqa: E402
from chanceblog_desktop.ui.core import text  # noqa: E402

T = text.T
LINE = "한우 불고기 전골 28,000원"
SOURCE = ROOT / "src" / "chanceblog_desktop" / "ui" / "core" / "drafts_view.py"


def reopened(reader=True, confirmed=(1,)):
    """사진 두 장이 든 초안을 저장하고 떠났다가 다시 연 상태 → `(컨트롤러, 공급자)`. `confirmed` 는 확정해 둔 사진 번호들, `reader` 가 참이면 글자 읽기 컨트롤러가 붙어 있다."""
    controller, provider = with_photos(2)
    for number in confirmed:
        confirm(controller, number)
    if reader:
        pov.OcrBoard(controller.photos, pov.FakeOcrProvider(default=pov.OcrOutcome((LINE,))))
    store(controller, "save")
    draft_id = saved_id(provider)
    controller.leave()
    store(controller, "open", draft_id)
    return controller, provider


def read_and_confirm(controller, photo_id="p001"):
    """열어 둔 초안의 한 사진을 읽고 그 줄을 맞아요로 하고 사진을 확정한다 — 새 글에 읽은 글이 들어갈 상태."""
    controller.photos.open()
    panel = pp.OcrPanel(controller.photos.ocr)
    assert panel.read(photo_id) == "queued"
    job = panel.ocr.begin_next(0.0)
    panel.ready(0.0)
    assert panel.finish(job.token, pov.OcrOutcome((LINE,)), 0.0) == "applied"
    panel.confirm_line(photo_id, 0, True)
    controller.photos.confirm(photo_id, True)
    return panel


class AskTest(unittest.TestCase):
    def test_a_reopened_draft_with_a_confirmed_photo_and_no_read_text_asks_before_the_remake_even_without_edits(self):
        controller, _provider = reopened()
        self.assertTrue(controller.opened_saved)
        self.assertEqual((controller.text_unsaved(), controller.photo_text_at_risk()), (False, True))
        self.assertEqual(controller.start_regenerate(), ("unconfirmed", None), "묻지 않고는 시작하지 않는다")
        dialog = controller.regen_dialog()
        self.assertEqual(dialog, {"title": T["pho_ocr_regen_title"], "body": T["pho_ocr_regen_body"], "ok": T["pho_ocr_regen_ok"], "cancel": T["drf_cancel"]})
        self.assertTrue(controller.regen_asked)
        self.assertEqual(drive(controller, controller.start_regenerate), "started", "확인창을 보인 뒤에는 시작한다")
        self.assertFalse(controller.opened_saved, "다시 만든 글은 지금 메모리의 사진 정보로 만든 것이다")
        self.assertFalse(controller.photo_text_at_risk())
        self.assertIsNone(controller.regen_dialog(), "다시 만든 뒤에는 묻지 않는다")

    def test_saying_no_closes_the_question_and_the_next_press_asks_again(self):
        controller, _provider = reopened()
        self.assertIsNotNone(controller.regen_dialog())
        controller.discard_regen()
        self.assertFalse(controller.regen_asked)
        self.assertEqual(controller.start_regenerate(), ("unconfirmed", None))
        self.assertIsNotNone(controller.regen_dialog(), "그만둔 뒤 다시 눌러도 묻는다")
        self.assertTrue(controller.opened_saved, "아무것도 바뀌지 않았다")

    def test_a_confirmed_read_line_in_memory_means_the_new_text_gets_the_paragraph_so_nothing_is_asked(self):
        controller, _provider = reopened()
        read_and_confirm(controller)
        placed = controller._photos_to_place()
        self.assertEqual([photo.confirmed_texts for photo in placed if photo.confirmed_texts], [(LINE,)], "확정한 줄이 새 글로 간다")
        self.assertFalse(controller.photo_text_at_risk())
        self.assertIsNone(controller.regen_dialog())
        self.assertEqual(drive(controller, controller.start_regenerate), "started")

    def test_a_line_that_is_read_but_not_confirmed_does_not_count(self):
        controller, _provider = reopened(confirmed=(1, 2))
        controller.photos.open()
        panel = pp.OcrPanel(controller.photos.ocr)
        panel.read("p001")
        job = panel.ocr.begin_next(0.0)
        panel.ready(0.0)
        panel.finish(job.token, pov.OcrOutcome((LINE,)), 0.0)
        self.assertFalse(controller.photos.photo("p001").confirmed_by_user, "새로 읽으면 사진의 확정이 풀린다(기존 규칙) — 그 사진은 새 글에 들어가지 않는다")
        self.assertEqual([photo.confirmed_texts for photo in controller._photos_to_place()], [()], "남은 확정한 사진(p002)에는 읽은 글이 없다")
        self.assertTrue(controller.photo_text_at_risk(), "확인 전 줄은 초안으로 가지 않는다 — 문단은 여전히 빠질 수 있다")
        self.assertIsNotNone(controller.regen_dialog())

    def test_with_two_confirmed_photos_and_only_one_with_a_confirmed_read_text_the_other_may_still_lose_its_paragraph(self):
        """독립 검증 S SP-2 — 확정한 사진이 둘인데 하나만 읽은 글을 확정했으면, 다시 만든 글에는 그 사진의 문단만 들어가고 읽지 않은 사진의 저장해 둔 문단은 소리 없이 빠진다 — 그래서 묻는다."""
        controller, _provider = reopened(confirmed=(1, 2))
        read_and_confirm(controller, "p001")
        placed = controller._photos_to_place()
        self.assertEqual([bool(photo.confirmed_texts) for photo in placed], [True, False], "새 글에 가는 사진은 둘이고 하나에만 읽은 글이 있다")
        self.assertTrue(controller.photo_text_at_risk(), "읽지 않은 사진의 문단은 빠질 수 있다")
        self.assertEqual(controller.start_regenerate(), ("unconfirmed", None), "묻지 않고는 시작하지 않는다")
        self.assertEqual(controller.regen_dialog(), {"title": T["pho_ocr_regen_title"], "body": T["pho_ocr_regen_body"], "ok": T["pho_ocr_regen_ok"], "cancel": T["drf_cancel"]})
        self.assertEqual(drive(controller, controller.start_regenerate), "started")

    def test_when_every_confirmed_photo_has_a_confirmed_read_text_nothing_is_asked(self):
        controller, _provider = reopened(confirmed=(1, 2))
        read_and_confirm(controller, "p001")
        read_and_confirm(controller, "p002")
        self.assertEqual([bool(photo.confirmed_texts) for photo in controller._photos_to_place()], [True, True])
        self.assertEqual((controller.photo_text_at_risk(), controller.regen_dialog()), (False, None), "모든 사진의 문단이 새 글에 다시 들어간다")
        self.assertEqual(drive(controller, controller.start_regenerate), "started")

    def test_when_the_text_was_edited_too_the_old_question_gets_one_more_sentence_and_nothing_else_changes(self):
        controller, _provider = reopened()
        controller.set_body(controller.body + "\n\n내가 고친 문단이에요.")
        self.assertTrue(controller.text_unsaved())
        dialog = controller.regen_dialog()
        self.assertEqual(dialog["title"], T["drf_regen_title"])
        self.assertEqual(dialog["body"], T["drf_regen_body"] + " " + T["pho_ocr_regen_more"])
        self.assertEqual((dialog["ok"], dialog["cancel"]), (T["drf_regen_ok"], T["drf_cancel"]))


class QuietTest(unittest.TestCase):
    def test_without_the_reader_the_question_is_exactly_what_it_was(self):
        controller, _provider = reopened(reader=False)
        self.assertIsNone(controller.photos.ocr)
        self.assertEqual((controller.opened_saved, controller.photo_text_at_risk()), (True, False))
        self.assertIsNone(controller.regen_dialog(), "글자 읽기가 없으면 글을 안 고친 저장한 초안의 다시 만들기는 묻지 않는다(지금과 같다)")
        self.assertEqual(drive(controller, controller.start_regenerate), "started")
        controller.set_body("고친 글")
        self.assertEqual(controller.regen_dialog()["body"], T["drf_regen_body"], "고친 글이 있을 때의 확인창 글도 한 글자 그대로다")

    def test_a_draft_made_in_this_session_never_asks_even_with_the_reader_and_confirmed_photos(self):
        controller, _provider = with_photos(2)
        confirm(controller, 1)
        pov.OcrBoard(controller.photos, pov.FakeOcrProvider())
        self.assertFalse(controller.opened_saved)
        self.assertEqual((controller.photo_text_at_risk(), controller.regen_dialog()), (False, None))
        store(controller, "save")
        self.assertFalse(controller.opened_saved, "이 세션에서 저장한 것은 연 것이 아니다 — 읽은 글은 메모리에 그대로 있다")
        self.assertIsNone(controller.regen_dialog())

    def test_no_confirmed_photo_means_no_paragraph_could_have_been_made_so_nothing_is_asked(self):
        controller, _provider = reopened(confirmed=())
        self.assertEqual((controller.photos.count, controller._photos_to_place()), (2, ()))
        self.assertEqual((controller.photo_text_at_risk(), controller.regen_dialog()), (False, None))

    def test_when_the_photo_info_check_blocks_the_remake_nothing_is_asked_because_nothing_could_be_made(self):
        """사진 정보 검사(키·토큰 모양)가 막으면 보낼 사진 목록이 `None` 이다 — 어차피 만들지 못하니 묻지 않는다(목록이 비었을 때와 달리 `None` 을 `all` 에 넣으면 오류가 난다)."""
        controller, _provider = reopened()
        self.assertTrue(controller.photo_text_at_risk())
        with mock.patch.object(controller, "_photos_to_place", return_value=None):
            self.assertEqual((controller.photo_text_at_risk(), controller.regen_dialog()), (False, None))

    def test_leaving_clears_the_flag_and_a_new_target_starts_clean(self):
        controller, _provider = reopened()
        self.assertTrue(controller.opened_saved)
        controller.leave()
        self.assertFalse(controller.opened_saved)
        self.assertFalse(controller.photo_text_at_risk())


class SourceTest(unittest.TestCase):
    def test_the_rule_never_reads_the_text_of_the_body_for_a_frame_sentence(self):
        """독립 검증이 이 한계를 직접 판단할 수 있게 규칙이 무엇을 보는지 코드로 못박는다 — 글(`self.body`·`body_text`)을 읽거나 틀 문장을 비교하지 않는다."""
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "photo_text_at_risk")
        body = ast.unparse(method)
        for forbidden in ("self.body", "body_text", "saved_snapshot", "사진에 적힌"):
            self.assertNotIn(forbidden, body)
        names = {node.attr for node in ast.walk(method) if isinstance(node, ast.Attribute)}
        self.assertLessEqual(names, {"photos", "ocr", "opened_saved", "_photos_to_place", "confirmed_texts"})


if __name__ == "__main__":
    unittest.main()
