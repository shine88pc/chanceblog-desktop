"""사진 연동 3단계(저장·되돌릴 사본·본문 연결·복사)가 2단계 수정 묶음(WIP 11)·블로그 후속(M080 — 별명·`&&`·서랍 줄임)과 만나는 곳의 순수 시험(PySide6 없이 돈다 — CI 에서도 돈다).

지키는 것:
  1) **별명이 사진 문구에 새지 않는다** — 블로그 관리가 정한 채널 별명(`&`·중괄호·자리표시자 모양·긴 글)이 바뀌어도 복사 확인창의 올릴 사진 줄·어긋남 줄·떠나기·닫기 확인창·사진 카드는 한 글자도 안 바뀌고, 사진 문구 표(`pho_*`)는 채널·별명 자리를 갖지 않는다.
  2) **'고친 내용' 판정이 글·사진·초안 유무에 따라 서로 어긋나지 않는다** — 다시 만들기는 글만(`text_unsaved`), 떠나기·앱 닫기·블로그 이름이 바뀔 때 다시 그릴지(`shell._typing_would_be_lost`)는 둘 다(`has_unsaved`)를 본다. 초안이 아직 없으면 사진이 있는 것만으로 묻고(저장할 곳이 없다), 초안이 있으면 저장한 사진 정보와 다를 때만 묻는다.
"""
import json
import string
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ui_drafts_save_core import made_saving, saving  # noqa: E402
from test_ui_photo_copy_core import with_photos  # noqa: E402
from test_ui_photo_save_core import path_of  # noqa: E402

from chanceblog_desktop.ui.core import channel_names as cn  # noqa: E402
from chanceblog_desktop.ui.core import photo_text, text  # noqa: E402

T = text.T
TRICKY = {"naver_a": "A&B {사진 1}", "naver_b": "{{사진 9}} 별명", "blogger_ko": "가" * 40, "blogger_en": "&lt;b&gt; 사진", "github_pages": "[이미지 1] & more"}
MARKS = ("A&B", "{{사진 9}}", "별명", "&lt;", "more", "가" * 12)


def photo_surface(controller):
    """사진과 관련해 사용자에게 보이는 글 — 복사 확인창(올릴 사진 줄·어긋남)·사진 카드·떠나기·닫기 확인창 — 을 한 글로 모은다."""
    decision, dialog = controller.copy_decision("body")
    parts = {"copy": [decision, dialog if isinstance(dialog, dict) else None], "card": controller.photos_card(),
             "leave": controller.leave_dialog("leave"), "close": controller.leave_dialog("close")}
    return json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)


class NamesDoNotLeakTest(unittest.TestCase):
    def tearDown(self):
        cn.use(None)

    def test_the_photo_texts_have_no_channel_or_alias_slot(self):
        fields = set()
        for key, value in photo_text.PHOTO_T.items():
            for _literal, field, _spec, _conversion in string.Formatter().parse(value):
                if field is not None:
                    fields.add(field)
        self.assertFalse(fields & {"blog", "channel", "alias", "label", "blog_name", "channel_name"}, sorted(fields))
        self.assertEqual({key for key in photo_text.PHOTO_T if "{별명}" in photo_text.PHOTO_T[key]}, set())

    def test_changing_the_aliases_changes_no_character_of_the_photo_surface(self):
        cn.use(None)
        plain, _provider = with_photos()
        plain_text = photo_surface(plain)
        cn.use(cn.labels({key: (alias, True) for key, alias in TRICKY.items()}))
        fancy, _provider = with_photos()
        fancy_text = photo_surface(fancy)
        self.assertIn("confirm", plain_text, "시험의 전제: 확정한 사진이 본문에 들어가 복사 확인창이 뜬다")
        self.assertEqual(fancy_text, plain_text)
        for mark in MARKS:
            self.assertNotIn(mark, fancy_text)

    def test_the_leave_and_close_questions_with_unsaved_photos_never_name_a_channel(self):
        for aliases in (None, {key: (alias, True) for key, alias in TRICKY.items()}):
            cn.use(cn.labels(aliases) if aliases else None)
            controller, _provider = made_saving()
            controller.photos.add_paths([path_of(1), path_of(2)])
            for kind in ("leave", "close"):
                dialog = controller.leave_dialog(kind)
                self.assertIsNotNone(dialog)
                shown = json.dumps(dialog, ensure_ascii=False)
                for mark in MARKS:
                    self.assertNotIn(mark, shown, (kind, aliases is not None))
                self.assertEqual([choice["key"] for choice in dialog["choices"]], ["save", "discard", "stay"], "저장 기능이 있으면 사진만 달라도 세 갈래")


class UnsavedQuestionsTest(unittest.TestCase):
    def flags(self, controller):
        return {"text": controller.text_unsaved(), "photos": controller.photos_unsaved(), "has": controller.has_unsaved(),
                "leave": controller.leave_dialog("leave") is not None, "regen": controller.regen_dialog() is not None}

    def test_with_no_draft_yet_photos_alone_ask_with_the_photo_only_question_and_regenerate_has_nothing_to_ask(self):
        controller, _provider = saving()
        self.assertIsNone(controller.result)
        self.assertEqual(self.flags(controller), {"text": False, "photos": False, "has": False, "leave": False, "regen": False})
        controller.photos.add_paths([path_of(1)])
        self.assertEqual(self.flags(controller), {"text": False, "photos": True, "has": True, "leave": True, "regen": False})
        dialog = controller.leave_dialog("leave")
        self.assertEqual(dialog["title"], T["pho_leave_title"])
        self.assertNotIn("choices", dialog, "저장할 초안이 없으니 '저장' 갈래도 없다")

    def test_with_a_draft_the_photo_question_follows_the_saved_photo_info_and_remaking_follows_the_text_only(self):
        controller, _provider = made_saving()
        self.assertEqual(self.flags(controller), {"text": False, "photos": False, "has": False, "leave": False, "regen": False})
        controller.photos.add_paths([path_of(1), path_of(2)])
        self.assertEqual(self.flags(controller), {"text": False, "photos": True, "has": True, "leave": True, "regen": False}, "사진만 달라졌다 — 떠날 때는 묻지만 다시 만들기는 묻지 않는다")
        controller.set_body(controller.body + chr(10) * 2 + "고친 문단이에요.")
        self.assertEqual(self.flags(controller), {"text": True, "photos": True, "has": True, "leave": True, "regen": True}, "글도 고쳤다 — 다시 만들기도 묻는다")
        edited, _provider = made_saving()                                    # 확인창을 보이기 전에 단추를 누르면(`regen_dialog` 가 '물었음' 을 적기 전에)
        edited.photos.add_paths([path_of(1)])
        edited.set_body(edited.body + chr(10) * 2 + "고친 문단이에요.")
        self.assertEqual(edited.start_regenerate(on_done=lambda *_a: None, on_error=lambda *_a: None), ("unconfirmed", None), "글을 고쳤으면 확인창을 보이기 전에는 시작하지 않는다")

    def test_remaking_with_only_the_photos_changed_starts_straight_away_and_keeps_the_photos(self):
        controller, _provider = made_saving()
        controller.photos.add_paths([path_of(1), path_of(2)])
        self.assertTrue(controller.photos_unsaved() and not controller.text_unsaved())
        holder = {}
        status, job = controller.start_regenerate(on_done=lambda result, _payload: holder.setdefault("ok", result), on_error=lambda failure, _payload: holder.setdefault("failed", failure))
        self.assertEqual(status, "started", "사진만 달라졌으면 다시 만들기는 묻지 않고 시작한다")
        job.join(30)
        self.assertTrue(controller.apply_made(holder["ok"]))
        self.assertEqual(controller.photos.count, 2, "새 초안이 와도 사진 목록은 남는다")


if __name__ == "__main__":
    unittest.main()
