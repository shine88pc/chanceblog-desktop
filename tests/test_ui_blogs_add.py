"""블로그 관리 화면의 **'블로그 추가' 흐름과 보기 고르기**(blogsel — D-493 부터)의 순수 시험(PySide6 없이 돈다 — CI 와 같은 조건): 등록한 블로그만 카드로 보이는 규칙·종류 고르기·새 블로그 연결(속의 빈 슬롯)·낱말 제안 칩·보기 고르기·제안 문장·실제 서비스로 저장.

지키는 것:
  1) 카드는 **등록한 블로그만**(+ 주소 없이 내용만 있는 슬롯 + 지금 새로 연결하는 슬롯)이고 맨 끝에 '블로그 추가' 카드가 있다. 읽은 값(저장 형식의 다섯 슬롯)은 그대로이고 다시 쓰이지 않는다.
  2) '블로그 추가' 는 종류(네이버·Blogger·GitHub Pages)를 고르게 하고 같은 종류의 빈 슬롯(네이버 2·Blogger 2·GitHub 1)을 속에서 쓴다. 자리가 다 찼으면 쉬운 문장으로 알리고 아무것도 열지 않는다. 내용이 있는 슬롯은 덮어쓰지 않는다.
  3) **화면 글 어디에도 슬롯 이름이 없다**(`네이버 A`·`Blogger 한글`·`naver_a` …) — 카드·폼·종류 고르기·확인창 모두. 카드와 폼 머리의 이름은 별명(없으면 종류 + 번호)이다.
  4) 새로 연결하는 슬롯의 이름 칸은 비어 있고 별명은 종류 + 번호로 제안해 미리 넣는다. 저장은 필수 칸(이름·블로그 주소)이 차야 하고, 저장하면 카드가 '등록됨' 으로 바뀐다. 취소(되돌리기)는 연결을 그만두는 일이다.
  5) 낱말 칸의 제안 칩은 한도·우선/제외 겹침을 칩이 만들지 못하게 하고, 보기 칸은 하나를 고르거나 직접 입력하며, 별명·소개글은 제안 문장을 눌러 쓴다. 저장하는 값은 기존과 같은 글이다.
  6) 읽기·고르기·고치기·종류 고르기는 파일에 닿지 않고, 저장한 값은 서비스를 거쳐 기존과 똑같은 파일 모양으로 쓰인다(엔진 칸·다른 슬롯은 그대로).
실제 블로그 이름·아이디·주소는 이 시험에 없다(예시 값뿐).
"""
import dataclasses
import json
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.ui import blogs_adapter  # noqa: E402
from chanceblog_desktop.ui.core import blog_form as bf  # noqa: E402
from chanceblog_desktop.ui.core import blog_options as bo  # noqa: E402
from chanceblog_desktop.ui.core import app_state, blogs, blogs_view, jobs, services, text  # noqa: E402
from test_ui_blogs_core import NEVER, SAFE, drive, load, new_controller, start_new  # noqa: E402,I001

T = text.T
TILDE = chr(0x7E)                                   # 물결 글자는 시험 글에도 직접 쓰지 않는다(문서·주석에 물결표를 두지 않는 규칙)
SLOT_NAME = re.compile(r"네이버 [AB]\b|Blogger (?:한글|영문)|naver_[ab]|blogger_(?:ko|en)|github_pages")


def fields_of(controller):
    return {field["name"]: field for section in controller.view()["form"]["sections"] for field in section["fields"]}


def view_strings(view):
    """뷰모델 속 모든 글(내부 열쇠 칸은 건너뛴다)."""
    out = []

    def walk(value, name=""):
        if isinstance(value, str):
            if name not in ("key", "name", "kind", "preset", "tone", "level", "state", "value", "dirty_names", "assist", "selected"):
                out.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, key)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item, name)

    walk(view)
    return out


# ---- 1) 카드 규칙 ------------------------------------------------------------------------------------------------------------------------
class CardRuleTest(unittest.TestCase):
    def test_the_sample_shows_only_its_three_registered_blogs_and_an_add_card_at_the_end(self):
        view = new_controller().view()
        self.assertEqual([card["key"] for card in view["list"]["cards"]], ["blogger_ko", "naver_a", "naver_b"])
        self.assertEqual(view["list"]["add"], {"key": "add", "title": "블로그 추가", "desc": "연결할 사이트를 골라요.", "a11y": T["blogs_add_a11y"], "selected": False})
        self.assertIsNone(view["picker"])
        self.assertEqual(view["form"]["key"], "naver_a")

    def test_an_empty_profile_shows_no_cards_the_add_card_selected_and_the_kind_picker_instead_of_a_form(self):
        controller = new_controller("empty")
        view = controller.view()
        self.assertEqual((view["list"]["cards"], view["form"], view["selected"]), ([], None, None))
        self.assertTrue(view["list"]["add"]["selected"])
        self.assertEqual([kind["kind"] for kind in view["picker"]["kinds"]], ["naver", "blogger", "github"])
        self.assertEqual(view["picker"]["close"], "", "닫고 돌아갈 카드가 없으면 닫기 단추도 없다")
        self.assertEqual([kind["left"] for kind in view["picker"]["kinds"]], [2, 2, 1])

    def test_the_stored_slots_stay_five_and_reading_never_changes_them(self):
        controller = new_controller()
        self.assertEqual([slot.key for slot in controller.data.slots], list(bf.SLOTS))
        before = {slot.key: slot.raw() for slot in controller.data.slots}
        controller.view()
        controller.open_picker()
        controller.close_picker()
        controller.view()
        self.assertEqual({slot.key: slot.raw() for slot in controller.data.slots}, before)
        self.assertEqual(controller.provider.calls, ["load"])

    def test_a_slot_with_content_but_no_address_is_a_card_not_a_hidden_slot(self):
        """손으로 고친 파일의 주소 없는 슬롯 — 숨기면 내용도 지울 길도 안 보인다. '등록 전' 카드로 보이고 지울 수 있다."""
        controller = new_controller("empty")
        provider = controller.provider
        provider.slots["github_pages"] = dataclasses.replace(provider.slots["github_pages"], alias="손으로 쓴 별명", display_name="손으로 쓴 이름")
        provider.revision += 1
        load(controller)
        view = controller.view()
        self.assertEqual([card["key"] for card in view["list"]["cards"]], ["github_pages"])
        card = view["list"]["cards"][0]
        self.assertEqual((card["registered"], card["fresh"], card["status"]["text"], card["sub"], card["title"]), (False, False, "등록 전", T["blogs_card_unfinished_desc"], "손으로 쓴 별명"))
        self.assertEqual(view["selected"], "github_pages")
        self.assertEqual([action["key"] for action in view["form"]["actions"]], ["save", "revert", "clone", "delete"])
        self.assertTrue(controller.can_clear())
        self.assertEqual(view["form"]["title"], T["blogs_form_unfinished"].format(slot="손으로 쓴 별명"))
        self.assertEqual(controller.kind_free("github"), 0, "내용이 있는 슬롯은 빈 슬롯이 아니다 — 새 블로그가 덮어쓰지 않는다")
        self.assertIsNone(controller.start_adding("github"))

    def test_the_card_title_is_the_alias_or_the_kind_and_number_and_the_status_follows_the_registration(self):
        controller = new_controller()
        cards = {card["key"]: card for card in controller.view()["list"]["cards"]}
        self.assertEqual({key: card["title"] for key, card in cards.items()}, {"blogger_ko": "Blogger 1", "naver_a": "예시 별명", "naver_b": "네이버 블로그 2"})
        self.assertEqual({key: card["status"]["text"] for key, card in cards.items()}, {"blogger_ko": "등록됨", "naver_a": "등록됨", "naver_b": "등록됨"})
        self.assertEqual(cards["naver_a"]["a11y"], "예시 별명, 등록됨, 예시 블로그 가, 선택됨")


# ---- 2) 종류 고르기 · 새 블로그 연결 ---------------------------------------------------------------------------------------------------------
class AddFlowTest(unittest.TestCase):
    def test_each_kind_fills_its_slots_in_order_and_a_full_kind_opens_nothing(self):
        controller = new_controller("empty")
        self.assertEqual(start_new(controller, "naver"), "naver_a")
        controller.revert()
        self.assertEqual(controller.listed_keys(), ())
        self.assertEqual(start_new(controller, "naver"), "naver_a", "취소하면 같은 자리가 다시 비어 있다")
        controller.open_picker()
        self.assertEqual(start_new(controller, "naver"), "naver_b", "열어 둔 슬롯은 건너뛴다")
        controller.open_picker()
        self.assertIsNone(controller.start_adding("naver"), "자리가 다 찼다")
        self.assertTrue(controller.picking, "열지 못했으면 종류 고르기가 그대로 열려 있다")
        self.assertEqual(start_new(controller, "blogger"), "blogger_ko")
        controller.open_picker()
        self.assertEqual(start_new(controller, "blogger"), "blogger_en")
        controller.open_picker()
        self.assertEqual(start_new(controller, "github"), "github_pages")
        controller.open_picker()
        self.assertIsNone(controller.start_adding("github"))
        self.assertIsNone(controller.start_adding("no_such_kind"))
        self.assertEqual(controller.listed_keys(), tuple(bf.SLOTS), "다섯 슬롯이 모두 새 블로그로 열려 있다")

    def test_the_picker_says_how_many_are_linked_and_why_a_kind_cannot_take_another(self):
        controller = new_controller()
        controller.open_picker()
        picker = controller.view()["picker"]
        kinds = {kind["kind"]: kind for kind in picker["kinds"]}
        self.assertEqual((kinds["naver"]["enabled"], kinds["naver"]["left"], kinds["naver"]["reason"]), (False, 0, T["blogs_pick_full"]))
        self.assertEqual((kinds["blogger"]["enabled"], kinds["blogger"]["left"], kinds["blogger"]["reason"]), (True, 1, ""))
        self.assertEqual((kinds["github"]["enabled"], kinds["github"]["left"]), (True, 1))
        self.assertEqual(kinds["naver"]["count"], "연결 2개 · 남은 자리 0개")
        self.assertEqual(kinds["blogger"]["count"], "연결 1개 · 남은 자리 1개")
        self.assertEqual(kinds["github"]["count"], "연결 0개 · 남은 자리 1개")
        self.assertIn("더 연결할 수 없음", kinds["naver"]["a11y"])
        self.assertNotIn("더 연결할 수 없음", kinds["blogger"]["a11y"])
        self.assertEqual((picker["title"], picker["close"]), (T["blogs_pick_title"], T["blogs_pick_close"]))
        self.assertEqual(controller.view()["form"], None, "종류 고르기가 열려 있으면 폼 자리는 종류 고르기다")
        self.assertTrue(controller.view()["list"]["add"]["selected"])
        self.assertFalse(any(card["selected"] for card in controller.view()["list"]["cards"]), "종류 고르기가 열려 있으면 어느 카드도 선택 표시가 없다")

    def test_the_picker_opens_and_closes_without_touching_the_provider_or_the_drafts(self):
        controller = new_controller()
        controller.edit("alias", "고치던 별명")
        calls = list(controller.provider.calls)
        self.assertTrue(controller.open_picker())
        self.assertTrue(controller.close_picker())
        self.assertEqual((controller.selected, controller.values("naver_a")["alias"]), ("naver_a", "고치던 별명"), "고치던 내용은 그대로다")
        self.assertEqual(controller.provider.calls, calls)
        self.assertFalse(controller.close_picker(), "열려 있지 않으면 닫을 것이 없다")
        controller.open_picker()
        controller.select("naver_b")
        self.assertFalse(controller.picking, "카드를 누르면 종류 고르기가 닫히고 그 카드의 폼이 열린다")
        self.assertEqual(controller.view()["form"]["key"], "naver_b")

    def test_a_write_in_progress_blocks_opening_the_picker_and_starting_a_new_blog(self):
        controller = new_controller(delay=0.4)
        controller.edit("alias", "고친 별명")
        status, job = controller.start_save()
        self.assertEqual(status, "started")
        self.assertFalse(controller.open_picker())
        self.assertIsNone(controller.start_adding("github"))
        self.assertFalse(controller.close_picker())
        job.join(10)

    def test_a_new_blog_form_has_a_blank_name_a_suggested_alias_and_only_save_and_cancel(self):
        controller = new_controller("empty")
        key = start_new(controller)
        view = controller.view()
        self.assertEqual((controller.selected, controller.picking, controller.listed_keys()), (key, False, (key,)))
        form = view["form"]
        fields = fields_of(controller)
        self.assertEqual((fields["display_name"]["value"], fields["alias"]["value"], fields["blog_ref"]["value"]), ("", "네이버 블로그 1", ""), "이름은 비어 있고(기본 프로필의 이름은 슬롯 이름이다) 별명은 제안해 넣는다")
        self.assertEqual((form["title"], form["fresh"], form["registered"], form["status"]["text"], form["unsaved"]), ("네이버 블로그 새로 연결하기", True, False, "등록 전", None))
        self.assertEqual([(action["key"], action["text"], action["enabled"]) for action in form["actions"]], [("save", "저장", True), ("revert", "취소", True)])
        card = view["list"]["cards"][0]
        self.assertEqual((card["fresh"], card["registered"], card["headline"], card["sub"], card["status"]["text"], card["unsaved"], card["title"]), (True, False, "새 블로그", T["blogs_card_new_desc"], "등록 전", False, "네이버 블로그 1"))
        self.assertEqual(controller.dirty_names(key), ("alias",), "제안해 넣은 별명이 바뀐 칸이다 — 이름은 아직 아무것도 아니다")
        self.assertEqual(controller.base_raw(key)["display_name"], "네이버 A", "저장된 값은 그대로다 — 폼만 이름을 비워 보인다")
        self.assertEqual({field["name"]: field["error"] for field in fields.values() if field["error"]}, {}, "처음 보는 폼은 오류로 시작하지 않는다")

    def test_the_text_of_the_stored_default_name_is_a_real_input_for_a_new_blog_because_the_form_base_is_the_blank_name(self):
        """저장된 기본 프로필의 이름(슬롯 이름)과 **같은 글**을 사용자가 쳐도 입력으로 남는다 — 폼의 바탕은 빈 이름이라 같은 글이 아니다(저장된 값과 견주면 쳐 넣은 이름이 초안에서 사라져 빈칸으로 돌아간다)."""
        controller = new_controller("empty")
        key = start_new(controller)
        default = controller.base_raw(key)["display_name"]
        self.assertTrue(default)
        self.assertTrue(controller.edit("display_name", default))
        self.assertEqual(controller.values(key)["display_name"], default)
        self.assertIn("display_name", controller.dirty_names(key))
        controller.edit("blog_ref", "example-blog-a")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        self.assertEqual(controller.slot_map()[key].display_name, default, "그 이름으로 등록된다")
        again = new_controller("empty")
        other = start_new(again)
        again.edit("display_name", "임시 이름")
        again.edit("display_name", "")
        self.assertEqual(set(again.drafts[other]), {"alias"}, "이름을 다시 비우면 바탕(빈 이름)과 같아져 초안에서 빠진다")

    def test_saving_needs_the_name_and_the_address_and_then_the_card_turns_into_a_registered_one(self):
        controller = new_controller("empty")
        key = start_new(controller)
        status, problems = controller.start_save()
        self.assertEqual((status, problems), ("invalid", {"display_name": "required", "blog_ref": "required"}))
        self.assertEqual(controller.provider.calls, ["load"], "칸에 문제가 있으면 서비스를 부르지 않는다")
        controller.edit("display_name", "예시 블로그 가")
        controller.edit("blog_ref", "example-blog-a")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        slot = controller.slot_map()[key]
        self.assertEqual((slot.display_name, slot.blog_ref, slot.alias), ("예시 블로그 가", "example-blog-a", "네이버 블로그 1"))
        self.assertNotIn(key, controller.adding)
        card = controller.view()["list"]["cards"][0]
        self.assertEqual((card["registered"], card["fresh"], card["status"]["text"], card["headline"]), (True, False, "등록됨", "예시 블로그 가"))
        self.assertEqual([action["key"] for action in controller.view()["form"]["actions"]], ["save", "revert", "clone", "delete"], "저장하면 보통 블로그의 폼이 된다")
        self.assertEqual(controller.notice, ("ok", T["blogs_saved"]))

    def test_cancel_drops_the_draft_and_the_card_and_moves_to_the_next_card_or_the_picker(self):
        controller = new_controller()
        controller.open_picker()
        key = start_new(controller, "github")
        controller.edit("display_name", "임시 이름")
        self.assertEqual(controller.listed_keys(), ("github_pages", "blogger_ko", "naver_a", "naver_b"))
        self.assertTrue(controller.revert())
        self.assertNotIn(key, controller.drafts)
        self.assertEqual((controller.selected, controller.listed_keys()), ("naver_a", ("blogger_ko", "naver_a", "naver_b")), "의도적 갱신(blogsel 수정 1, D-493 ⑤·검증 Q-2): 취소하면 슬롯 순서의 첫 카드가 아니라 새 블로그를 열기 전에 폼에 열려 있던 카드(naver_a)로 돌아간다")
        self.assertEqual(controller.provider.calls, ["load"], "취소는 파일에 닿지 않는다")
        empty = new_controller("empty")
        start_new(empty)
        empty.revert()
        self.assertIsNone(empty.selected)
        self.assertIsNotNone(empty.view()["picker"], "카드가 하나도 없으면 종류 고르기가 다시 열린다")

    def test_a_started_new_blog_stays_as_a_card_with_its_draft_when_another_card_is_opened(self):
        controller = new_controller()
        controller.open_picker()
        key = start_new(controller, "github")
        controller.edit("display_name", "저장 전 이름")
        controller.select("naver_a")
        self.assertEqual([card["key"] for card in controller.view()["list"]["cards"]], ["github_pages", "blogger_ko", "naver_a", "naver_b"], "새 블로그가 카드로 남아 있다")
        controller.select(key)
        self.assertEqual(fields_of(controller)["display_name"]["value"], "저장 전 이름", "입력은 지워지지 않는다")
        self.assertEqual(controller.kind_free("github"), 0, "열어 둔 슬롯은 빈 자리로 세지 않는다")

    def test_a_slot_name_never_reaches_any_text_on_the_screen(self):
        controller = new_controller()
        every = []
        for step in (lambda: None, controller.open_picker, lambda: start_new(controller, "github"), lambda: controller.edit("display_name", "예시 이름"), lambda: controller.start_save(), controller.revert,
                     lambda: controller.select("blogger_ko"), lambda: controller.select("naver_b")):
            step()
            every.extend(view_strings(controller.view()))
            if controller.selected:
                every.append(controller.delete_dialog()["body"] if controller.can_clear() else "")
        self.assertGreater(len(every), 300)
        for item in every:
            self.assertNotRegex(item, SLOT_NAME, item)
        empty = new_controller("empty")
        for item in view_strings(empty.view()):
            self.assertNotRegex(item, SLOT_NAME, item)
        start_new(empty, "blogger")
        for item in view_strings(empty.view()):
            self.assertNotRegex(item, SLOT_NAME, item)


# ---- 2-2) 수정 1(검증 S·Q 1차) — 낡은 자료에 얹힌 입력·취소 뒤 돌아가는 자리·종류 고르기 가드 ------------------------------------------------------
def fill_elsewhere(controller, key, **changes):
    """다른 곳(손으로 고친 파일·두 번째 프로세스·백업 복원)이 그 슬롯을 먼저 바꾼다 — 화면이 들고 있는 자료는 낡은 판이 된다."""
    provider = controller.provider
    provider.slots[key] = dataclasses.replace(provider.slots[key], **changes)
    provider.revision += 1


class StaleInputTest(unittest.TestCase):
    """새 블로그로 열어 둔 슬롯이 그 사이 다른 곳에서 채워지면(검증 S-1) 입력이 남의 블로그에 얹히지 않고, 비워진 슬롯의 낡은 입력은 되살아나지 않는다(검증 Q-9)."""

    def conflict_then_reload(self, controller):
        self.assertEqual(drive(controller, controller.start_save), ("started", "failed", True), "낡은 판이라 서비스가 첫 저장을 거절한다")
        load(controller)                                                                           # 셸이 하듯 최신 내용을 다시 읽는다

    def test_a_slot_filled_elsewhere_never_takes_the_input_of_a_new_blog_the_input_moves_to_the_next_free_slot_of_the_kind(self):
        controller = new_controller("empty")
        first = start_new(controller, "naver")
        controller.edit("display_name", "내 새 블로그")
        controller.edit("blog_ref", "example-new-blog")
        controller.toggle_choice("main_topics", "소형가전")
        fill_elsewhere(controller, first, display_name="다른 쪽 블로그", blog_ref="example-other-blog", alias="다른 쪽 별명", intro="다른 쪽 소개")
        self.conflict_then_reload(controller)
        self.assertEqual((controller.selected, sorted(controller.adding)), ("naver_b", ["naver_b"]), "입력은 같은 종류의 다른 빈 자리로 옮겨져 그 자리의 새 블로그 폼이 다시 열린다")
        other = controller.values(first)
        self.assertEqual((other["display_name"], other["blog_ref"], other["alias"], other["intro"]), ("다른 쪽 블로그", "example-other-blog", "다른 쪽 별명", "다른 쪽 소개"), "남의 블로그에는 아무것도 얹히지 않는다")
        self.assertNotIn(first, controller.drafts)
        form = fields_of(controller)
        self.assertEqual((form["display_name"]["value"], form["blog_ref"]["value"], form["alias"]["value"], form["main_topics"]["value"]), ("내 새 블로그", "example-new-blog", "네이버 블로그 2", "소형가전"),
                         "입력은 그대로이고, 제안 그대로였던 별명만 새 자리의 번호로 다시 제안한다")
        self.assertTrue(controller.view()["form"]["fresh"])
        self.assertEqual(controller.notice, ("warning", T["blogs_taken_moved"]), "이유를 쉬운 말로 알린다 — 조용히 바뀌지 않는다")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        slots = controller.provider.slots
        self.assertEqual((slots["naver_a"].blog_ref, slots["naver_a"].display_name, slots["naver_b"].blog_ref, slots["naver_b"].display_name), ("example-other-blog", "다른 쪽 블로그", "example-new-blog", "내 새 블로그"))

    def test_when_the_kind_has_no_other_free_slot_the_input_is_dropped_and_the_reason_is_told(self):
        controller = new_controller("empty")
        fill_elsewhere(controller, "naver_b", display_name="이미 있던 블로그", blog_ref="example-b-blog")
        load(controller)
        first = start_new(controller, "naver")
        self.assertEqual(first, "naver_a")
        controller.edit("display_name", "내 새 블로그")
        controller.edit("blog_ref", "example-new-blog")
        fill_elsewhere(controller, first, display_name="다른 쪽 블로그", blog_ref="example-other-blog")
        self.conflict_then_reload(controller)
        self.assertEqual((controller.adding, controller.selected), (set(), "naver_b"), "자리가 없으면 입력을 버리고 열어 두기 전의 카드로 돌아간다")
        self.assertNotIn(first, controller.drafts)
        self.assertEqual(controller.values(first)["display_name"], "다른 쪽 블로그", "남의 블로그 값이 그대로다")
        self.assertEqual(controller.notice, ("warning", T["blogs_taken_dropped"]), "버렸다면 이유를 알린다 — 확인 없이 조용히 사라지지 않는다")

    def test_a_moved_blogger_form_keeps_the_values_the_user_saw_even_where_the_other_slot_has_another_default(self):
        controller = new_controller("empty")
        first = start_new(controller, "blogger")
        self.assertEqual((first, fields_of(controller)["language"]["value"]), ("blogger_ko", "ko"))
        controller.edit("display_name", "내 Blogger")
        controller.edit("blog_ref", "example-blogger")
        fill_elsewhere(controller, first, display_name="다른 쪽", blog_ref="example-other")
        self.conflict_then_reload(controller)
        self.assertEqual(controller.selected, "blogger_en")
        self.assertEqual(fields_of(controller)["language"]["value"], "ko", "사용자가 본 값 그대로 — 새 슬롯의 기본 언어(en)로 슬며시 바뀌지 않는다")
        self.assertEqual(controller.drafts["blogger_en"]["language"], "ko")

    def test_the_input_of_a_blog_emptied_elsewhere_does_not_come_back_in_the_next_new_blog_form(self):
        controller = new_controller()
        controller.select("naver_b")
        controller.edit("display_name", "고치던 이름")
        controller.edit("alias", "고치던 별명")
        controller.toggle_choice("main_topics", "소형가전")
        self.assertTrue(controller.is_dirty("naver_b"))
        controller.provider.clear_blog("naver_b", str(controller.provider.revision), SAFE, NEVER)                 # 다른 곳이 그 블로그를 지웠다
        load(controller)
        self.assertNotIn("naver_b", controller.listed_keys())
        for table in (controller.drafts, controller.touched, controller.service_problems):
            self.assertNotIn("naver_b", table)
        self.assertEqual(controller.notice, ("warning", T["blogs_edit_gone"]), "고치던 입력을 버렸다면 알린다")
        controller.open_picker()
        self.assertEqual(start_new(controller, "naver"), "naver_b")
        self.assertEqual(controller.drafts["naver_b"], {"alias": "네이버 블로그 2"}, "낡은 입력이 되살아나지 않는다 — 제안 별명만 들어 있다")
        form = fields_of(controller)
        self.assertEqual((form["display_name"]["value"], form["main_topics"]["value"]), ("", ""))
        self.assertEqual(controller.touched.get("naver_b"), None)

    def test_opening_a_new_blog_never_revives_leftover_input_of_that_slot(self):
        """방어선 — 어떤 길로든 그 자리에 낡은 입력 상태가 남아 있어도 새 블로그 폼은 깨끗하게 시작한다."""
        controller = new_controller("empty")
        controller.drafts["naver_a"] = {"display_name": "낡은 이름", "alias": "낡은 별명"}
        controller.touched["naver_a"] = {"display_name"}
        controller.submitted.add("naver_a")
        controller.custom_open.add(("naver_a", "tone"))
        controller.service_problems["naver_a"] = {"blog_ref": "invalid"}
        self.assertEqual(start_new(controller, "naver"), "naver_a")
        self.assertEqual(controller.drafts["naver_a"], {"alias": "네이버 블로그 1"})
        self.assertEqual((controller.touched.get("naver_a"), "naver_a" in controller.submitted, ("naver_a", "tone") in controller.custom_open, controller.service_problems.get("naver_a")), (None, False, False, None))
        self.assertEqual(fields_of(controller)["display_name"]["value"], "")

    def test_a_vanished_card_without_input_is_cleaned_without_a_notice(self):
        controller = new_controller()
        controller.select("naver_b")                                                                      # 고친 것은 없다
        controller.provider.clear_blog("naver_b", str(controller.provider.revision), SAFE, NEVER)
        load(controller)
        self.assertIsNone(controller.notice, "버릴 입력이 없으면 알릴 것도 없다")
        self.assertNotIn("naver_b", controller.listed_keys())

    def test_two_open_new_blog_forms_are_checked_one_by_one_the_stale_one_is_dropped_and_the_other_stays(self):
        controller = new_controller("empty")
        first = start_new(controller, "naver")
        controller.edit("display_name", "첫 입력")
        controller.open_picker()
        second = start_new(controller, "naver")
        controller.edit("display_name", "둘째 입력")
        controller.edit("blog_ref", "example-second")
        self.assertEqual((first, second), ("naver_a", "naver_b"))
        fill_elsewhere(controller, first, display_name="다른 쪽 블로그", blog_ref="example-other-blog")
        self.conflict_then_reload(controller)
        self.assertEqual((controller.adding, controller.selected), ({"naver_b"}, "naver_b"), "채워진 첫 자리의 입력만 버려지고(남은 빈 자리가 없다) 둘째 폼은 그대로다")
        self.assertEqual(fields_of(controller)["display_name"]["value"], "둘째 입력")
        self.assertNotIn(first, controller.drafts)
        self.assertEqual(controller.notice, ("warning", T["blogs_taken_dropped"]))


# ---- 3) 복제·삭제와 새 카드 ---------------------------------------------------------------------------------------------------------------
class CloneAndClearTest(unittest.TestCase):
    def test_clone_never_picks_a_slot_the_user_is_filling_and_the_clone_becomes_a_card(self):
        controller = new_controller()
        controller.select("blogger_ko")
        self.assertEqual(controller.clone_info()[2], "blogger_en")
        controller.open_picker()
        key = start_new(controller, "blogger")
        self.assertEqual(key, "blogger_en")
        controller.select("blogger_ko")
        allowed, reason, target = controller.clone_info()
        self.assertEqual((allowed, reason, target), (False, T["blogs_clone_no_target"], None), "입력 중인 새 블로그 자리에는 복제하지 않는다")
        controller.select(key)
        controller.revert()
        controller.select("blogger_ko")
        self.assertEqual(drive(controller, controller.start_clone), ("started", "ok", False))
        self.assertEqual(controller.selected, "blogger_en")
        self.assertEqual([card["key"] for card in controller.view()["list"]["cards"]], ["blogger_en", "blogger_ko", "naver_a", "naver_b"], "복제한 블로그가 카드가 된다")
        self.assertEqual(controller.view()["form"]["actions"][2]["hint"], "", "복제할 자리가 없으면 힌트도 없다")

    def test_the_clone_hint_names_the_kind_and_never_a_slot(self):
        controller = new_controller()
        controller.select("blogger_ko")
        actions = {action["key"]: action for action in controller.view()["form"]["actions"]}
        self.assertEqual(actions["clone"]["hint"], T["blogs_clone_hint"].format(kind="Blogger"))
        self.assertNotRegex(actions["clone"]["hint"], SLOT_NAME)

    def test_deleting_the_last_registered_blog_leaves_the_empty_picker(self):
        controller = new_controller("empty")
        key = start_new(controller)
        controller.edit("display_name", "예시 블로그 가")
        controller.edit("blog_ref", "example-blog-a")
        drive(controller, controller.start_save)
        self.assertEqual(drive(controller, controller.start_clear), ("started", "ok", False))
        self.assertEqual((controller.listed_keys(), controller.selected), ((), None))
        view = controller.view()
        self.assertIsNotNone(view["picker"])
        self.assertEqual(view["list"]["cards"], [])
        self.assertEqual(controller.notice, ("ok", T["blogs_cleared"]))
        self.assertEqual(controller.start_adding("naver"), key, "지운 자리는 다시 쓰인다")


class DefaultNameTest(unittest.TestCase):
    """저장된 이름 칸이 그 슬롯의 기본 이름(슬롯 이름)이면 카드·접근 이름·삭제 확인창에는 쓰지 않는다(검증 S-2·Q-8). 저장된 값은 건드리지 않고, 이름 입력 칸에는 저장된 값이 그대로 보인다(사용자 자료)."""

    def test_user_name_is_empty_for_a_blank_or_the_slots_default_name_only(self):
        for key in bf.SLOTS:
            default = bf.default_values(key)["display_name"]
            self.assertEqual((bf.user_name(key, default), bf.user_name(key, f"  {default} "), bf.user_name(key, ""), bf.user_name(key, None)), ("", "", "", ""), key)
            self.assertEqual(bf.user_name(key, "내가 정한 이름"), "내가 정한 이름")
        self.assertEqual(bf.user_name("naver_b", bf.default_values("naver_a")["display_name"]), bf.default_values("naver_a")["display_name"], "다른 슬롯의 기본 이름은 사용자가 쓴 글이다")

    def test_a_slot_with_only_an_alias_and_the_default_name_shows_the_kind_name_and_never_the_slot_name(self):
        """손으로 고친 파일의 '주소 없이 별명만 있는 슬롯'(검증 S 의 R2) — 이름 칸은 기본 이름 그대로다."""
        controller = new_controller("empty")
        fill_elsewhere(controller, "naver_b", alias="손으로 쓴 별명")
        load(controller)
        view = controller.view()
        card = view["list"]["cards"][0]
        self.assertEqual((card["key"], card["registered"], card["title"], card["headline"]), ("naver_b", False, "손으로 쓴 별명", T["blogs_kind_naver"]))
        self.assertIn(T["blogs_kind_naver"], card["a11y"], "접근 이름의 이름 자리도 종류 이름이다")
        for item in view_strings(view) + [controller.delete_dialog()["body"]]:
            self.assertNotRegex(item, SLOT_NAME, item)
        self.assertIn(T["blogs_del_unnamed"], controller.delete_dialog()["body"])
        self.assertEqual(fields_of(controller)["display_name"]["value"], bf.default_values("naver_b")["display_name"], "이름 입력 칸에는 저장된 값이 그대로 보인다 — 사용자 자료이고 화면 글이 아니다")

    def test_the_delete_dialog_of_a_selected_empty_slot_names_no_one(self):
        controller = new_controller("empty")
        controller.select("naver_b")
        dialog = controller.delete_dialog()
        self.assertIn(T["blogs_del_unnamed"], dialog["body"])
        self.assertNotRegex(dialog["body"], SLOT_NAME)


class CancelReturnTest(unittest.TestCase):
    """새 블로그 `취소` 뒤에는 열기 전에 폼에 열려 있던 카드로 돌아간다(검증 Q-2) — 첫 카드의 `되돌리기` 가 같은 자리에 나타나 연타가 그 카드의 입력을 버리는 일을 없앤다."""

    def test_cancel_goes_back_to_the_card_that_was_open_before_adding_and_keeps_its_input(self):
        controller = new_controller()
        controller.select("naver_b")
        controller.edit("alias", "고치던 별명")
        controller.open_picker()
        key = start_new(controller, "github")
        self.assertEqual(controller.selected, key)
        self.assertTrue(controller.revert())
        self.assertEqual(controller.selected, "naver_b", "슬롯 순서의 첫 카드(blogger_ko)가 아니라 열기 전의 카드다")
        self.assertEqual(controller.drafts["naver_b"], {"alias": "고치던 별명"}, "그 카드의 저장 전 입력은 그대로다")
        self.assertIsNone(controller.return_to)

    def test_cancel_goes_to_the_first_card_when_the_card_before_adding_is_gone(self):
        controller = new_controller()
        controller.select("naver_b")
        controller.open_picker()
        start_new(controller, "github")
        controller.provider.clear_blog("naver_b", str(controller.provider.revision), SAFE, NEVER)                 # 그 사이 다른 곳이 그 블로그를 지웠다
        load(controller)
        self.assertEqual(controller.selected, "github_pages", "열어 둔 새 블로그 폼은 그대로다")
        self.assertTrue(controller.revert())
        self.assertEqual(controller.selected, "blogger_ko", "돌아갈 카드가 사라졌으면 첫 카드다")

    def test_after_hopping_between_cards_cancel_returns_to_the_card_left_last_before_the_new_form(self):
        controller = new_controller()
        controller.select("naver_b")
        controller.open_picker()
        key = start_new(controller, "github")
        controller.select("blogger_ko")
        controller.select(key)
        self.assertEqual(controller.return_to, "blogger_ko", "입력 중인 새 블로그 카드로 옮겨 올 때 있던 카드")
        controller.revert()
        self.assertEqual(controller.selected, "blogger_ko")

    def test_cancel_with_no_card_before_goes_to_the_picker(self):
        controller = new_controller("empty")
        start_new(controller, "naver")
        controller.revert()
        self.assertEqual((controller.selected, controller.picker_shown()), (None, True))


class PickerGuardTest(unittest.TestCase):
    """종류 고르기가 열려 있을 때만 종류 고르기 신호를 받는다(검증 Q-13) — 신호가 겹쳐 두 번 와도 슬롯 둘이 잡히지 않는다."""

    def test_a_kind_is_taken_only_while_the_kind_picker_is_shown(self):
        controller = new_controller()
        self.assertFalse(controller.picker_shown())
        self.assertIsNone(controller.start_adding("github"), "종류 고르기가 닫혀 있으면 아무 일도 없다")
        self.assertEqual((controller.adding, controller.selected, controller.drafts), (set(), "naver_a", {}))
        controller.open_picker()
        self.assertEqual(controller.start_adding("github"), "github_pages")
        self.assertFalse(controller.picker_shown())
        self.assertIsNone(controller.start_adding("blogger"), "이미 폼이 열렸다 — 같은 신호가 한 번 더 와도 슬롯이 둘 잡히지 않는다")
        self.assertEqual(controller.adding, {"github_pages"})

    def test_with_no_card_the_picker_is_shown_from_the_start_and_a_second_signal_is_ignored(self):
        controller = new_controller("empty")
        self.assertTrue(controller.picker_shown())
        self.assertEqual(controller.start_adding("naver"), "naver_a")
        self.assertIsNone(controller.start_adding("naver"))
        self.assertEqual(controller.adding, {"naver_a"})


class AfterSaveCleanupTest(unittest.TestCase):
    """저장이 끝나면 그 슬롯의 입력 상태가 비워지고, 이후 다른 곳이 바꾼 칸은 최신 값으로 보인다(검증 S-5 의 N01)."""

    def test_a_saved_blogs_input_state_is_cleared_and_an_outside_change_of_the_same_field_shows_up_afterwards(self):
        controller = new_controller()
        controller.edit("intro", "내가 쓴 소개")
        controller.open_custom("tone")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        for table in (controller.drafts, controller.touched, controller.service_problems):
            self.assertNotIn("naver_a", table)
        self.assertNotIn("naver_a", controller.submitted)
        self.assertFalse(any(slot == "naver_a" for slot, _name in controller.custom_open))
        fill_elsewhere(controller, "naver_a", intro="다른 곳에서 바꾼 소개")
        load(controller)
        self.assertEqual(controller.values("naver_a")["intro"], "다른 곳에서 바꾼 소개", "낡은 초안이 남아 있으면 남의 변경을 되돌려 쓰게 된다")
        self.assertFalse(controller.is_dirty("naver_a"))


class CloseDialogTest(unittest.TestCase):
    """저장하지 않은 블로그 입력이 있으면 앱 닫기 확인창의 글이 있다(검증 Q-5) — 입력이 없으면 없다."""

    def test_the_close_dialog_exists_only_for_unsaved_input_and_new_forms_count_only_what_the_user_typed(self):
        controller = new_controller()
        self.assertIsNone(controller.close_dialog())
        controller.edit("intro", "저장 전 소개")
        dialog = controller.close_dialog()
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), (T["blogs_close_title"], T["blogs_close_ok"], T["blogs_close_cancel"]))
        for item in dialog.values():
            self.assertNotRegex(item, SLOT_NAME, item)
        controller.revert()
        self.assertIsNone(controller.close_dialog(), "되돌리면 없다")
        controller.open_picker()
        start_new(controller, "github")
        self.assertFalse(controller.has_unsaved(), "새 블로그 폼에 미리 넣은 제안 별명만 있으면 사용자가 친 것이 아니다")
        controller.edit("display_name", "새 블로그 이름")
        self.assertTrue(controller.has_unsaved())
        controller.revert()
        self.assertFalse(controller.has_unsaved(), "취소하면 없다")

    def test_a_write_in_progress_or_an_unread_list_never_asks(self):
        controller = new_controller()
        controller.edit("intro", "저장 전 소개")
        controller.pending = {"kind": "save", "key": "naver_a", "target": None}
        gate = threading.Event()                                                                          # 시험이 열어 주기 전에는 끝나지 않는 쓰기 — 시간에 기대지 않는다
        job = controller.runner.start(blogs_view.WRITE_KEY, lambda progress, cancelled: gate.wait(30))
        self.addCleanup(job.join, 10)
        self.addCleanup(gate.set)
        self.assertTrue(controller.busy)
        self.assertFalse(controller.has_unsaved(), "쓰는 중에는 앱을 닫아도 쓰기를 마칠 때까지 기다린다")
        blank = blogs_view.BlogsController(blogs.FakeBlogsProvider(), jobs.JobRunner())
        self.assertIsNone(blank.close_dialog(), "아직 읽지 않았다")

    def test_the_app_state_asks_for_blog_input_only_after_the_drafts_screen_has_nothing_to_ask(self):
        state = app_state.AppState(services.FakeHomeProvider())
        load(state.blogs)
        self.assertIsNone(state.close_guard())
        state.blogs.edit("intro", "저장 전 소개")
        self.assertEqual(state.close_guard()["title"], T["blogs_close_title"])


# ---- 4) 낱말 제안 칩 -----------------------------------------------------------------------------------------------------------------------
class WordChipTest(unittest.TestCase):
    def options(self, controller, name):
        return {option["value"]: option for option in fields_of(controller)[name]["options"]}

    def test_a_chip_adds_and_removes_a_word_and_keeps_the_hand_written_words(self):
        controller = new_controller()
        controller.select("naver_a")
        self.assertEqual(controller.values("naver_a")["main_topics"], "예시 주제 하나, 예시 주제 둘, 예시 주제 셋")
        self.assertTrue(controller.toggle_choice("main_topics", "소형가전"))
        self.assertEqual(controller.values("naver_a")["main_topics"], "예시 주제 하나, 예시 주제 둘, 예시 주제 셋, 소형가전", "손으로 쓴 낱말은 그대로 두고 뒤에 붙는다")
        self.assertTrue(self.options(controller, "main_topics")["소형가전"]["checked"])
        self.assertEqual(controller.dirty_names("naver_a"), ("main_topics",))
        self.assertTrue(controller.toggle_choice("main_topics", "소형가전"))
        self.assertFalse(controller.is_dirty("naver_a"), "켰다 끄면 저장된 값과 같아 바뀐 것이 아니다")
        self.assertEqual(bf.typed_values("naver_a", controller.values("naver_a"))["main_topics"], ("예시 주제 하나", "예시 주제 둘", "예시 주제 셋"))

    def test_only_the_suggested_words_can_be_chips_and_other_fields_have_no_word_chips(self):
        controller = new_controller()
        for bad in (("main_topics", "예시 주제 하나"), ("main_topics", ""), ("priority_keywords", "없는 낱말"), ("alias", "소형가전"), ("tone", "친근한 말투"), ("display_name", "x"), ("no_field", "x")):
            self.assertFalse(controller.toggle_choice(*bad), bad)
        self.assertFalse(controller.is_dirty("naver_a"))
        self.assertTrue(controller.toggle_choice("categories", "정보형"), "카테고리의 제안에는 글 유형 이름도 있다")
        self.assertFalse(controller.toggle_choice("main_topics", "정보형"), "주요 주제의 제안에는 글 유형 이름이 없다")

    def test_the_chips_stop_at_the_limit_and_turning_a_word_off_always_works(self):
        controller = new_controller("empty")
        start_new(controller)
        spec = bf.SPEC["main_topics"]
        for word in bo.TOPIC_WORDS[:spec.count]:
            self.assertTrue(controller.toggle_choice("main_topics", word), word)
        self.assertFalse(controller.toggle_choice("main_topics", bo.TOPIC_WORDS[spec.count]), "한도를 넘겨 켤 수 없다")
        options = self.options(controller, "main_topics")
        self.assertEqual([word for word, option in options.items() if option["disabled"]], [word for word in bo.TOPIC_WORDS if word not in bo.TOPIC_WORDS[:spec.count]], "못 고르는 칩은 꺼져 있다")
        self.assertTrue(all(options[word]["reason"] == T["bf_chip_full"] for word in bo.TOPIC_WORDS[spec.count:]))
        self.assertTrue(all(not options[word]["disabled"] for word in bo.TOPIC_WORDS[:spec.count]), "고른 칩은 끌 수 있다")
        self.assertEqual(fields_of(controller)["main_topics"]["extra"], T["bf_note_full"].format(count=spec.count))
        self.assertEqual(controller.problems("naver_a").get("main_topics"), None, "한도까지는 서비스 검사를 통과한다")
        self.assertTrue(controller.toggle_choice("main_topics", bo.TOPIC_WORDS[0]))
        self.assertTrue(controller.toggle_choice("main_topics", bo.TOPIC_WORDS[spec.count]), "하나를 빼면 다른 낱말을 켤 수 있다")
        self.assertEqual(fields_of(controller)["main_topics"]["extra"], T["bf_note_full"].format(count=spec.count))

    def test_a_word_chosen_in_one_keyword_field_cannot_be_chosen_in_the_other_so_the_overlap_error_cannot_be_made_by_chips(self):
        controller = new_controller("empty")
        start_new(controller)
        self.assertTrue(controller.toggle_choice("priority_keywords", "소형가전"))
        self.assertFalse(controller.toggle_choice("exclude_keywords", "소형가전"), "우선에서 고른 낱말은 제외에서 고를 수 없다")
        options = self.options(controller, "exclude_keywords")
        self.assertEqual((options["소형가전"]["disabled"], options["소형가전"]["reason"]), (True, T["bf_chip_other"]))
        self.assertFalse(options["PC 주변기기"]["disabled"])
        self.assertTrue(controller.toggle_choice("exclude_keywords", "PC 주변기기"))
        self.assertFalse(controller.toggle_choice("priority_keywords", "PC 주변기기"), "반대쪽도 같다")
        self.assertEqual(bf.overlap_names(bf.typed_values("naver_a", controller.values("naver_a"))), (), "칩으로는 겹침이 생기지 않는다")
        self.assertTrue(controller.toggle_choice("priority_keywords", "소형가전"), "고른 낱말을 끄는 것은 늘 된다")
        self.assertTrue(controller.toggle_choice("exclude_keywords", "소형가전"), "비운 뒤에는 반대쪽에서 고를 수 있다")
        self.assertEqual(self.options(controller, "priority_keywords")["소형가전"]["reason"], T["bf_chip_other"])

    def test_typing_a_overlapping_word_still_gives_the_overlap_error_and_the_chips_do_not_hide_it(self):
        controller = new_controller()
        controller.edit("exclude_keywords", "예시 제외어, 예시 키워드 둘")
        self.assertEqual(controller.problems("naver_a"), {"priority_keywords": "overlap", "exclude_keywords": "overlap"})
        self.assertEqual(fields_of(controller)["exclude_keywords"]["error"], T["bf_err_overlap_exclude_keywords"])

    def test_the_other_field_check_is_case_insensitive_like_the_service(self):
        controller = new_controller("empty")
        start_new(controller)
        controller.edit("priority_keywords", "api 한도")
        self.assertFalse(controller.toggle_choice("exclude_keywords", "API 한도"), "대소문자가 달라도 같은 낱말이다")
        self.assertTrue(self.options(controller, "priority_keywords")["API 한도"]["checked"], "대소문자 구분 없이 고른 것으로 보인다")

    def test_every_chip_choice_the_screen_allows_is_accepted_by_the_service(self):
        controller = new_controller("empty")
        start_new(controller)
        for name in ("main_topics", "categories", "priority_keywords"):
            for word in bo.WORD_SUGGESTIONS[name][:bf.SPEC[name].count]:
                self.assertTrue(controller.toggle_choice(name, word), (name, word))
        typed = bf.typed_values("naver_a", controller.values("naver_a"))
        self.assertEqual(controller.problems("naver_a").get("display_name"), "required")
        profile = bp.apply_fields(bp.default_profile("naver_a"), {name: typed[name] for name in ("main_topics", "categories", "priority_keywords")})
        self.assertEqual((profile.main_topics, profile.priority_keywords), (typed["main_topics"], typed["priority_keywords"]))


# ---- 5) 보기 고르기와 제안 문장 -----------------------------------------------------------------------------------------------------------
class ChoiceAndSuggestionTest(unittest.TestCase):
    def test_a_choice_sets_the_value_and_picking_it_again_clears_it(self):
        controller = new_controller("empty")
        start_new(controller)
        self.assertTrue(controller.choose_option("tone", "친근한 말투"))
        field = fields_of(controller)["tone"]
        self.assertEqual((field["value"], field["custom"], [option["value"] for option in field["options"] if option["checked"]]), ("친근한 말투", False, ["친근한 말투"]))
        self.assertTrue(controller.choose_option("tone", "정중한 설명체"))
        self.assertEqual(controller.values(controller.selected)["tone"], "정중한 설명체", "다른 보기를 고르면 바뀐다")
        self.assertTrue(controller.choose_option("tone", "정중한 설명체"))
        self.assertEqual((controller.values(controller.selected)["tone"], controller.is_dirty(controller.selected)), ("", True), "고른 보기를 다시 누르면 비워진다")
        for bad in (("tone", "없는 보기"), ("tone", ""), ("alias", "친근한 말투"), ("main_topics", "소형가전"), ("channel_role", "친근한 말투"), ("no_field", "x")):
            self.assertFalse(controller.choose_option(*bad), bad)

    def test_direct_input_opens_the_text_box_and_keeps_the_typed_text_even_when_it_equals_a_choice(self):
        controller = new_controller("empty")
        start_new(controller)
        self.assertFalse(fields_of(controller)["audience"]["custom"])
        self.assertTrue(controller.open_custom("audience"))
        field = fields_of(controller)["audience"]
        self.assertEqual((field["custom"], [option for option in field["options"] if option["checked"]]), (True, []), "직접 입력이 열려 있으면 어느 보기도 선택 표시가 없다")
        controller.edit("audience", "대학생")
        field = fields_of(controller)["audience"]
        self.assertTrue(field["custom"], "입력한 글이 보기와 같아져도 입력 칸은 닫히지 않는다(치는 도중에 칸이 사라지지 않게)")
        self.assertTrue(controller.choose_option("audience", "대학생"))
        field = fields_of(controller)["audience"]
        self.assertEqual((field["custom"], [option["value"] for option in field["options"] if option["checked"]]), (False, ["대학생"]), "보기를 누르면 직접 입력이 닫힌다")
        self.assertFalse(controller.open_custom("display_name"))
        self.assertFalse(controller.open_custom("main_topics"))

    def test_choosing_the_option_that_equals_the_text_typed_in_direct_input_sets_it_instead_of_clearing_it(self):
        controller = new_controller("empty")
        start_new(controller)
        controller.open_custom("tone")
        controller.edit("tone", "친근한 말투")
        self.assertTrue(controller.choose_option("tone", "친근한 말투"))
        self.assertEqual(controller.values(controller.selected)["tone"], "친근한 말투")
        self.assertFalse(fields_of(controller)["tone"]["custom"])

    def test_a_stored_value_outside_the_choices_is_shown_as_direct_input_and_is_never_erased_by_looking_at_it(self):
        controller = new_controller()
        before = dict(controller.values("naver_a"))
        field = fields_of(controller)["tone"]
        self.assertEqual((field["value"], field["custom"], [option for option in field["options"] if option["checked"]]), ("친절한 설명체", True, []))
        self.assertEqual(controller.values("naver_a"), before)
        self.assertFalse(controller.is_dirty("naver_a"))
        controller.choose_option("tone", "친근한 말투")
        self.assertEqual(controller.values("naver_a")["tone"], "친근한 말투")
        controller.revert()
        self.assertEqual(controller.values("naver_a")["tone"], "친절한 설명체", "되돌리면 손으로 쓴 값이 그대로 돌아온다")
        self.assertTrue(fields_of(controller)["tone"]["custom"])

    def test_revert_and_a_successful_save_close_the_direct_input_boxes_of_that_blog(self):
        controller = new_controller()
        controller.choose_option("tone", "친근한 말투")
        controller.open_custom("audience")
        self.assertEqual(controller.custom_open, {("naver_a", "audience")})
        controller.revert()
        self.assertEqual(controller.custom_open, set())
        controller.open_custom("audience")
        controller.edit("alias", "저장할 별명")
        drive(controller, controller.start_save)
        self.assertEqual(controller.custom_open, set())

    def test_the_alias_suggestion_shows_while_the_alias_differs_and_using_it_only_fills_the_box(self):
        controller = new_controller()
        controller.select("naver_b")
        field = fields_of(controller)["alias"]
        self.assertEqual(field["value"], "")
        suggestion = field["suggestion"]
        self.assertEqual((suggestion["text"], suggestion["label"], suggestion["button"]), ("네이버 블로그 2", T["bf_suggest_label"], T["bf_suggest_use"]))
        self.assertIn("별명", suggestion["a11y"])
        calls = list(controller.provider.calls)
        self.assertTrue(controller.apply_suggestion("alias"))
        self.assertEqual((controller.values("naver_b")["alias"], controller.is_dirty("naver_b")), ("네이버 블로그 2", True))
        self.assertIsNone(fields_of(controller)["alias"]["suggestion"], "이미 그 글이면 제안을 다시 보이지 않는다")
        self.assertEqual(controller.provider.calls, calls, "제안을 쓰는 것은 저장이 아니다")
        controller.edit("alias", "고친 별명")
        self.assertEqual(fields_of(controller)["alias"]["suggestion"]["text"], "네이버 블로그 2", "고쳤다면 제안이 다시 보인다")
        self.assertFalse(controller.apply_suggestion("tone"))
        self.assertFalse(controller.apply_suggestion("no_field"))

    def test_the_intro_suggestion_follows_what_was_chosen_above_and_is_empty_without_materials(self):
        controller = new_controller("empty")
        start_new(controller)
        self.assertIsNone(fields_of(controller)["intro"]["suggestion"], "재료가 없으면 제안하지 않는다")
        self.assertFalse(controller.apply_suggestion("intro"))
        controller.choose_option("channel_role", "정보 공유")
        self.assertEqual(fields_of(controller)["intro"]["suggestion"]["text"], "정보 공유 블로그예요.")
        controller.choose_option("audience", "대학생")
        controller.toggle_choice("main_topics", "소형가전")
        expected = "소형가전 이야기를 담아요. 대학생에게 도움이 되는 정보 공유 블로그예요."
        self.assertEqual(fields_of(controller)["intro"]["suggestion"]["text"], expected, "고른 값이 바뀌면 제안도 바뀐다")
        self.assertTrue(controller.apply_suggestion("intro"))
        self.assertEqual(controller.values(controller.selected)["intro"], expected)
        self.assertIsNone(fields_of(controller)["intro"]["suggestion"])
        controller.edit("intro", expected + " 직접 덧붙인 문장.")
        self.assertIsNotNone(fields_of(controller)["intro"]["suggestion"], "사용자가 고친 글은 제안으로 덮어쓰지 않는다 — 다시 눌러야만 바뀐다")
        self.assertEqual(controller.values(controller.selected)["intro"], expected + " 직접 덧붙인 문장.")

    def test_the_masked_suggestion_text_hides_a_key_shape_but_the_value_that_is_used_is_the_real_one(self):
        secret = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
        controller = new_controller("empty")
        start_new(controller)
        controller.open_custom("audience")
        controller.edit("audience", "독자 " + secret)
        shown = fields_of(controller)["intro"]["suggestion"]["text"]
        self.assertNotIn(secret, shown, "화면에 보이는 제안에는 키 모양이 가려진다")
        self.assertIn(secret, bf.suggest_intro(controller.values(controller.selected)), "입력 칸에 들어가는 글은 서비스가 거르도록 그대로다 — 서비스가 키 모양 글을 거절한다")


# ---- 6) 이미지 칸 --------------------------------------------------------------------------------------------------------------------------
class ImageFieldTest(unittest.TestCase):
    def test_the_image_fields_are_read_only_places_chosen_by_the_file_dialog_and_nothing_else_is_read_only(self):
        controller = new_controller()
        fields = fields_of(controller)
        self.assertEqual({name for name, field in fields.items() if field["readonly"]}, {"profile_image", "cover_image"})
        self.assertEqual({name for name, field in fields.items() if field["kind"] == "path"}, {"profile_image", "cover_image"})
        for name in ("profile_image", "cover_image"):
            self.assertEqual(fields[name]["placeholder"], T["bf_placeholder_path"])
            self.assertIn("파일 고르기", fields[name]["hint"])
            self.assertTrue(controller.edit(name, "C:/예시 폴더/예시 이미지.png"), "고른 위치는 그대로 칸에 들어간다(다이얼로그가 준 글)")
        self.assertEqual(bf.typed_values("naver_a", controller.values("naver_a"))["profile_image"], "C:/예시 폴더/예시 이미지.png")


# ---- 7) 주소 도움말 ---------------------------------------------------------------------------------------------------------------------
class AddressHelpTest(unittest.TestCase):
    def test_the_address_help_follows_the_kind_and_the_example_is_made_up(self):
        controller = new_controller()
        controller.select("naver_a")
        self.assertEqual(fields_of(controller)["blog_ref"]["hint"], T["bf_ref_help_naver"])
        controller.select("blogger_ko")
        self.assertEqual(fields_of(controller)["blog_ref"]["hint"], T["bf_ref_help_web"])
        controller.select("github_pages")
        self.assertEqual(fields_of(controller)["blog_ref"]["hint"], T["bf_ref_help_web"])
        self.assertIn("예) example-blog", T["bf_ref_help_naver"])
        for key in ("bf_ref_help_naver", "bf_ref_help_web"):
            self.assertNotRegex(T[key], r"https?://|www\.", "웹 주소를 문구에 쓰지 않는다")
            self.assertNotIn(TILDE, T[key])
        self.assertTrue(bf.problem_of(bf.SPEC["blog_ref"], "example-blog") == "")
        self.assertEqual(bf.problem_of(bf.SPEC["blog_ref"], "a b"), "bad_ref", "주소는 여전히 서비스와 같은 판정이다")


# ---- 8) 실제 서비스로 ------------------------------------------------------------------------------------------------------------------
class RealServiceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.ctx = ss.make_ctx(tmp.name)
        self.root = Path(self.ctx.workspace.root)
        self.paths = tf.topic_paths(self.ctx.workspace)
        self.provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: self.ctx)

    def controller(self):
        controller = blogs_view.BlogsController(self.provider, jobs.JobRunner())
        load(controller)
        return controller

    def stored(self):
        return {profile.key: profile for profile in bp.read_snapshot(self.ctx).profiles}

    def test_adding_opening_the_picker_and_filling_the_chips_write_nothing_until_save(self):
        before, listing = ss.tree_snapshot(self.root), sorted(str(path) for path in self.root.parent.rglob("*"))
        controller = self.controller()
        controller.open_picker()
        start_new(controller, "blogger")
        controller.toggle_choice("main_topics", "소형가전")
        controller.choose_option("tone", "친근한 말투")
        controller.open_custom("audience")
        controller.apply_suggestion("intro")
        controller.view()
        controller.revert()
        self.assertEqual(ss.tree_snapshot(self.root), before)
        self.assertEqual(sorted(str(path) for path in self.root.parent.rglob("*")), listing, "고르기·고치기·취소는 파일도 폴더도 만들지 않는다")

    def test_two_naver_blogs_then_the_kind_is_full_and_a_deleted_place_is_reused(self):
        controller = self.controller()
        first = start_new(controller, "naver")
        controller.edit("display_name", "예시 블로그 가")
        controller.edit("blog_ref", "example-blog-a")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        controller.open_picker()
        second = start_new(controller, "naver")
        controller.edit("display_name", "예시 블로그 나")
        controller.edit("blog_ref", "example-blog-b")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        self.assertEqual((first, second), ("naver_a", "naver_b"))
        stored = self.stored()
        self.assertEqual((stored["naver_a"].alias, stored["naver_b"].alias), ("네이버 블로그 1", "네이버 블로그 2"))
        controller.open_picker()
        picker = controller.view()["picker"]
        self.assertEqual([(kind["kind"], kind["enabled"]) for kind in picker["kinds"]], [("naver", False), ("blogger", True), ("github", True)])
        self.assertIsNone(controller.start_adding("naver"))
        controller.select("naver_a")
        self.assertEqual(drive(controller, controller.start_clear), ("started", "ok", False))
        self.assertEqual([card["key"] for card in controller.view()["list"]["cards"]], ["naver_b"])
        self.assertEqual(controller.selected, "naver_b")
        self.assertEqual(len(bp.read_snapshot(self.ctx).profiles), 5, "저장 형식의 슬롯은 다섯 그대로다")
        controller.open_picker()
        self.assertEqual(start_new(controller, "naver"), "naver_a", "지운 자리는 다시 쓰인다")

    def test_a_blog_saved_by_the_old_screen_with_the_default_name_shows_no_slot_name_on_the_card_the_access_name_or_the_delete_dialog(self):
        """옛 화면에서는 이름 칸에 기본값(슬롯 이름)이 미리 들어 있었다 — 안 고치고 주소만 넣어 저장한 파일을 서비스로 똑같이 만든다(검증 S-2). 저장된 값은 그대로이고 카드·접근 이름·삭제 확인창만 슬롯 이름을 쓰지 않는다."""
        for key, kind in (("naver_a", "naver"), ("blogger_ko", "blogger"), ("blogger_en", "blogger"), ("github_pages", "github"), ("naver_b", "naver")):
            default = bf.default_values(key)["display_name"]
            bp.save_slot(self.ctx, key, {"display_name": default, "blog_ref": "example-old-blog"}, expected_version=bp.read_snapshot(self.ctx).version)
            self.assertEqual(self.stored()[key].display_name, default, "저장된 값은 슬롯 이름 그대로다(바꾸지 않는다)")
        controller = self.controller()
        view = controller.view()
        self.assertEqual([card["key"] for card in view["list"]["cards"]], ["github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"])
        for card in view["list"]["cards"]:
            self.assertEqual(card["headline"], T["blogs_kind_" + bf.KIND_KEY[card["key"]]], card["key"])
            self.assertEqual(card["a11y"].split(", ")[2], card["headline"], "접근 이름의 이름 자리도 같다")
        for key in bf.SLOTS:
            controller.select(key)
            body = controller.delete_dialog()["body"]
            self.assertIn(T["blogs_del_unnamed"], body, key)
            for item in view_strings(controller.view()) + [body]:
                self.assertNotRegex(item, SLOT_NAME, f"{key}: {item}")
            self.assertEqual(fields_of(controller)["display_name"]["value"], bf.default_values(key)["display_name"], f"{key}: 이름 입력 칸에는 저장된 값이 그대로 보인다(사용자 자료)")
        controller.select("naver_a")
        controller.edit("display_name", "내가 정한 이름")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        card = next(item for item in controller.view()["list"]["cards"] if item["key"] == "naver_a")
        self.assertEqual(card["headline"], "내가 정한 이름", "사용자가 이름을 정하면 그 이름이 보인다")

    def test_the_real_service_refuses_the_first_save_of_a_slot_filled_elsewhere_and_the_reload_puts_no_input_on_the_other_blog(self):
        """검증 S 의 R1 — 새 블로그를 열어 둔 사이 다른 곳이 같은 슬롯에 다른 블로그를 저장했다."""
        controller = self.controller()
        first = start_new(controller, "naver")
        controller.edit("display_name", "내 새 블로그")
        controller.edit("blog_ref", "example-new-blog")
        bp.save_slot(self.ctx, first, {"display_name": "다른 쪽 블로그", "blog_ref": "example-other-blog", "alias": "다른 쪽 별명", "intro": "다른 쪽 소개"}, expected_version=bp.read_snapshot(self.ctx).version)
        raw = self.paths.profiles.read_bytes()
        self.assertEqual(drive(controller, controller.start_save), ("started", "failed", True))
        self.assertEqual(self.paths.profiles.read_bytes(), raw, "거절된 저장은 파일을 바꾸지 않는다")
        load(controller)
        self.assertEqual((controller.selected, sorted(controller.adding), controller.notice), ("naver_b", ["naver_b"], ("warning", T["blogs_taken_moved"])))
        self.assertEqual((controller.values("naver_a")["display_name"], controller.values("naver_a")["intro"]), ("다른 쪽 블로그", "다른 쪽 소개"))
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        stored = self.stored()
        self.assertEqual((stored["naver_a"].display_name, stored["naver_a"].blog_ref, stored["naver_a"].alias, stored["naver_a"].intro), ("다른 쪽 블로그", "example-other-blog", "다른 쪽 별명", "다른 쪽 소개"), "남의 블로그는 그대로다")
        self.assertEqual((stored["naver_b"].display_name, stored["naver_b"].blog_ref, stored["naver_b"].alias), ("내 새 블로그", "example-new-blog", "네이버 블로그 2"))

    def test_the_saved_file_is_exactly_what_the_service_writes_for_the_same_values_so_the_engine_sees_no_difference(self):
        """저장하는 값은 기존과 같은 글이다 — 화면으로 보기를 골라 저장한 파일이, 같은 값을 서비스 함수로 직접 저장한 파일과 **바이트까지 같다**(엔진 칸·다른 슬롯·판은 그대로)."""
        controller = self.controller()
        start_new(controller, "naver")
        controller.edit("display_name", "예시 블로그 가")
        controller.edit("blog_ref", "example-blog-a")
        controller.choose_option("channel_role", "정보 공유")
        controller.choose_option("audience", "대학생")
        controller.choose_option("tone", "친근한 말투")
        for word in ("소형가전", "PC 주변기기"):
            controller.toggle_choice("main_topics", word)
        controller.toggle_choice("categories", "정보형")
        controller.toggle_choice("priority_keywords", "숙박")
        controller.toggle_choice("exclude_keywords", "지역")
        controller.apply_suggestion("intro")
        intro = controller.values("naver_a")["intro"]
        self.assertTrue(intro)
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as other:
            twin = ss.make_ctx(other)
            bp.save_slot(twin, "naver_a", {"display_name": "예시 블로그 가", "blog_ref": "example-blog-a", "alias": "네이버 블로그 1", "channel_role": "정보 공유", "audience": "대학생", "tone": "친근한 말투",
                                           "main_topics": ("소형가전", "PC 주변기기"), "categories": ("정보형",), "intro": intro, "priority_keywords": ("숙박",), "exclude_keywords": ("지역",)},
                         expected_version=bp.read_snapshot(twin).version)
            self.assertEqual(self.paths.profiles.read_bytes(), tf.topic_paths(twin.workspace).profiles.read_bytes())
        data = json.loads(self.paths.profiles.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], 2)
        self.assertEqual(len(data["profiles"]), 5)
        mine = next(item for item in data["profiles"] if item["key"] == "naver_a")
        default = bp.default_profile("naver_a").to_dict()
        engine = ("weights", "top_n", "cluster_cap", "subheading_min", "trend_use", "dup_cutoffs", "topic_clusters", "expansion_directions", "evergreen_pct", "realtime_pct", "history_enabled", "home_regions", "day_trip_regions")
        for name in engine:
            self.assertEqual(mine[name], default[name], f"{name}: 엔진 칸은 그대로다")
        for key in ("naver_b", "blogger_ko", "blogger_en", "github_pages"):
            self.assertEqual(next(item for item in data["profiles"] if item["key"] == key), bp.default_profile(key).to_dict(), f"{key}: 다른 슬롯은 그대로다")
        self.assertEqual((mine["main_topics"], mine["categories"], mine["priority_keywords"], mine["exclude_keywords"], mine["channel_role"], mine["audience"], mine["tone"]),
                         (["소형가전", "PC 주변기기"], ["정보형"], ["숙박"], ["지역"], "정보 공유", "대학생", "친근한 말투"))

    def test_an_old_file_with_hand_written_values_outside_the_lists_is_shown_and_kept_when_another_field_is_saved(self):
        profiles = tuple(dataclasses.replace(p, blog_ref="example-blog-a", display_name="예시 블로그 가", channel_role="손으로 쓴 역할", audience="손으로 쓴 독자", tone="손으로 쓴 문체", main_topics=("손으로 쓴 주제", "소형가전"),
                                             categories=("손으로 쓴 분류",), priority_keywords=("손으로 쓴 우선",)) if p.key == "naver_a" else p for p in ch_default())
        self.paths.folder.mkdir(parents=True, exist_ok=True)
        self.paths.profiles.write_text(json.dumps(bp.channels.profiles_to_dict(profiles), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raw = self.paths.profiles.read_bytes()
        controller = self.controller()
        fields = fields_of(controller)
        for name in ("channel_role", "audience", "tone"):
            self.assertEqual((fields[name]["custom"], [option for option in fields[name]["options"] if option["checked"]]), (True, []), name)
            self.assertTrue(fields[name]["value"].startswith("손으로 쓴"), name)
        self.assertTrue(next(option for option in fields["main_topics"]["options"] if option["value"] == "소형가전")["checked"])
        self.assertEqual(fields["main_topics"]["value"], "손으로 쓴 주제, 소형가전")
        self.assertFalse(controller.is_dirty("naver_a"))
        self.assertEqual(self.paths.profiles.read_bytes(), raw, "읽기는 다시 쓰지 않는다")
        controller.toggle_choice("main_topics", "PC 주변기기")
        self.assertEqual(drive(controller, controller.start_save), ("started", "ok", False))
        after = self.stored()["naver_a"]
        self.assertEqual((after.main_topics, after.channel_role, after.audience, after.tone, after.categories, after.priority_keywords), (("손으로 쓴 주제", "소형가전", "PC 주변기기"), "손으로 쓴 역할", "손으로 쓴 독자", "손으로 쓴 문체", ("손으로 쓴 분류",), ("손으로 쓴 우선",)))


def ch_default():
    return bp.channels.default_profiles()


class SourceRulesTest(unittest.TestCase):
    CORE = ROOT / "src" / "chanceblog_desktop" / "ui" / "core"

    def test_the_new_pure_module_has_no_toolkit_clock_network_or_file_access(self):
        source = (self.CORE / "blog_options.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*(?:import|from)\s+(?:PySide6|urllib|http|socket|subprocess|os|shutil|pathlib|random|time|datetime)\b")
        for forbidden in ("open(", "write_text", "read_text", "datetime.now(", "time.time(", "random.", "requests", "urlopen"):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", source), [])
        self.assertNotIn(TILDE, source, "물결표를 쓰지 않는다")
        self.assertNotRegex(source, r"https?://")

    def test_the_choices_come_with_no_real_blog_names_and_no_slot_names(self):
        source = (self.CORE / "blog_options.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, SLOT_NAME)
        for word in ("ssae" + "ssace", "shine" + "5652", "스마트" + "프라이싱", "디지털" + "찬스"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
