"""후속 정리 묶음(POLISH-1)의 순수 시험(PySide6 없이 돈다 — CI 와 같은 조건) — 블로그 관리 후속(M080)과 사진 넣어 글쓰기(M081·M082)가 병합된 뒤 독립 검증이 '병합은 막지 않지만 고칠 만하다' 고 남긴 작은 일들.

지키는 것:
  1) 개수가 붙는 칩의 글 모양 — 이름이 숫자로 끝나면(`네이버 블로그 1`) 개수가 그 숫자에 붙어 읽히지 않게 가운뎃점·쉼표로 가른다(Q2-8). 문장 속 줄(Seed 가져오기·일괄 바꾸기 확인창)은 이름 뒤에 쌍점을 둔다.
  2) 주 화면의 채널 칩·요약·거르기에 보이는 이름은 `CHANNEL_CHIP_LIMIT`(20자)까지만 — 넘으면 …, 전체 이름은 접근 이름과 툴팁(`tip`)에 둔다(Q3-2). 서랍의 12자(`DRAWER_LIMIT`)와는 다른 값이다. Seed 칩 이름 함수(`scope_chip_name`·`channel_chip_name`)는 모르는 소속·열쇠를 오류로 내고, 후보 채널 칩은 다섯 채널 밖 열쇠도 같은 한도로 줄인다(독립 검증 뒤 더한 시험 — Q QP-2).
실제 블로그 이름·아이디·주소는 이 시험에 없다(예시 값뿐).
"""
import dataclasses
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_ui_candidates_core as cc  # noqa: E402
import test_ui_drafts_core as dc  # noqa: E402
import test_ui_photo_core as pc  # noqa: E402
import test_ui_photo_save_core as psc  # noqa: E402
import test_ui_seeds_core as sc  # noqa: E402

from chanceblog_desktop.ui.core import candidate_rules, channel_names as cn, drafts_view as dv, part_rules, photo_rules as rules, seed_form as sf, text  # noqa: E402

T = text.T
LONG30 = ("가나다라마바사아자차카타파하" * 3)[:30]                                      # 한도(30자) 가득한 별명
LONG30_B = ("나다라마바사아자차카타파하가" * 3)[:30]
TWIN = {"naver_a": (LONG30, True), "naver_b": (LONG30, True), "blogger_ko": ("", True), "blogger_en": ("", False), "github_pages": ("", False)}      # 같은 서른 자 별명 둘 — 가른 이름이 마흔두 자가 된다(검증 Q4-4)
MIXED = {"naver_a": (LONG30, True), "naver_b": ("예시 가게", True), "blogger_ko": (LONG30_B, True), "blogger_en": ("", True), "github_pages": ("", False)}


class ChipCaptionTest(unittest.TestCase):
    def test_every_name_is_split_from_the_count_by_a_middle_dot_whether_or_not_it_ends_with_a_digit(self):
        self.assertEqual(part_rules.chip_caption("네이버 블로그 1", 6), "네이버 블로그 1 · 6")
        self.assertEqual(part_rules.chip_caption("Blogger 2", 0), "Blogger 2 · 0")
        self.assertEqual(part_rules.chip_caption("맛집 2024", 12), "맛집 2024 · 12")
        self.assertEqual(part_rules.chip_caption("전체", 19), "전체 · 19", "숫자로 끝나지 않는 이름도 같은 가운뎃점(POLISH-2 QP-4 ①)")
        self.assertEqual(part_rules.chip_caption("GitHub Pages", 1), "GitHub Pages · 1")
        self.assertEqual(part_rules.chip_caption("공통", 3), "공통 · 3")

    def test_a_chip_without_a_count_shows_the_name_only_whatever_the_last_character(self):
        for name in ("네이버 블로그 1", "전체", "A&B"):
            self.assertEqual(part_rules.chip_caption(name, None), name)
            self.assertEqual(part_rules.chip_accessible(name, None), name)

    def test_the_accessible_name_uses_a_comma_after_a_name_that_ends_with_a_digit_so_it_is_not_read_as_one_number(self):
        self.assertEqual(part_rules.chip_accessible("네이버 블로그 1", 6), "네이버 블로그 1, 6")
        self.assertEqual(part_rules.chip_accessible("Blogger 1", 11), "Blogger 1, 11")
        self.assertEqual(part_rules.chip_accessible("전체", 19), "전체 19")
        self.assertEqual(part_rules.chip_accessible("GitHub Pages", 1), "GitHub Pages 1")

    def test_the_count_is_kept_as_it_is_even_when_zero(self):
        self.assertEqual(part_rules.chip_caption("Blogger 1", 0), "Blogger 1 · 0")
        self.assertEqual(part_rules.chip_caption("전체", 0), "전체 · 0")
        self.assertEqual(part_rules.chip_accessible("Blogger 1", 0), "Blogger 1, 0", "개수 0 도 접근 이름에 그대로 — 화면 읽기 프로그램은 `0개` 를 읽는다(0 을 감추면 `Blogger 1` 만 남아 개수가 없는 칩과 같아진다)")
        self.assertEqual(part_rules.chip_accessible("전체", 0), "전체 0")


class SentenceRowTest(unittest.TestCase):
    """문장 속에 ` · ` 로 이어 붙는 채널 줄(Seed 가져오기·일괄 바꾸기 확인창)은 이름 뒤에 쌍점 — `네이버 블로그 1: 3개 · 네이버 블로그 2: 2개`(옛 글은 `네이버 블로그 1 3개 · 네이버 블로그 2 2개` 라 `네이버 블로그 13개` 처럼 읽혔다). 후보 만들기 확인창의 줄도 같은 모양이 됐다(POLISH-2 QP-4 ③ — 새 시험은 `test_ui_polish2_core`)."""

    def test_the_summary_chip_the_import_row_the_bulk_row_and_the_filter_a11y_split_the_name_from_the_count(self):
        self.assertEqual(T["seeds_channel_chip"].format(name="네이버 블로그 1", n=3, gen="후보 생성 켜짐"), "네이버 블로그 1 · 3개 · 후보 생성 켜짐")
        self.assertEqual(T["seeds_imp_channel_row"].format(name="네이버 블로그 1", n=2, gen="후보 생성 켜짐"), "네이버 블로그 1: 2개(후보 생성 켜짐)")
        self.assertEqual(T["seeds_bulk_count_row"].format(name="네이버 블로그 1", before=3, after=7), "네이버 블로그 1: 3개 → 7개")
        self.assertEqual(T["cand_filter_channel_a11y"].format(name="네이버 블로그 1", n=6), "채널 네이버 블로그 1, 6개")

    def test_no_wording_puts_a_channel_name_straight_in_front_of_a_number_any_more(self):
        """이름이 들어가는 칸 `{name}` 바로 뒤에 공백 하나와 숫자 칸이 오는 문구(`{name} {n}개`)가 채널 이름 줄에 남지 않았다."""
        for key in ("seeds_channel_chip", "seeds_imp_channel_row", "seeds_bulk_count_row", "cand_filter_channel_a11y"):
            self.assertNotRegex(T[key], r"\{name\} \{(?:n|before)\}", key)

    def test_the_import_dialog_uses_the_new_row(self):
        controller = sc.seeds_view.SeedsController(sc.seeds.FakeSeedsProvider(import_mode="ok"), sc.jobs.JobRunner())
        sc.load(controller)
        sc.drive(controller, sc.partial(controller.start_import_preview, "가짜 파일 위치"))
        body = controller.import_dialog()["body"]
        self.assertIn("네이버 블로그 1: 2개(후보 생성 켜짐)", body)
        self.assertNotIn("네이버 블로그 1 2개", body)


class ChipLimitTest(unittest.TestCase):
    def tearDown(self):
        cn.use(None)

    def names(self, items):
        cn.use(cn.labels(items))

    def test_the_chip_limit_is_its_own_constant_wider_than_the_drawer_and_inside_the_service_alias_limit(self):
        self.assertEqual(cn.CHANNEL_CHIP_LIMIT, 20)
        self.assertGreater(cn.CHANNEL_CHIP_LIMIT, cn.DRAWER_LIMIT, "주 화면은 서랍(폭 420)보다 넓다")
        self.assertLess(cn.CHANNEL_CHIP_LIMIT, cn.LIMIT, "서른 자 별명은 칩에서 줄어든다")
        self.assertEqual(cn.DRAWER_LIMIT, 12, "서랍의 한도는 그대로다")
        self.assertFalse(hasattr(cn, "CHIP_LIMIT"), "카드 칩의 `candidate_rules.CHIP_LIMIT`(14자)와 이름이 같은 다른 상수가 되지 않게 채널 이름 쪽은 `CHANNEL_CHIP_LIMIT` 하나뿐이다")
        self.assertEqual(candidate_rules.CHIP_LIMIT, 14, "카드 칩의 한도는 그대로다")

    def test_the_chip_name_is_the_whole_name_when_it_fits_and_a_cut_name_with_an_ellipsis_when_it_does_not(self):
        self.assertEqual([cn.chip_label(key) for key in cn.ORDER], [cn.label(key) for key in cn.ORDER], "기본 이름은 줄지 않는다")
        self.names(MIXED)
        self.assertEqual(cn.chip_label("naver_b"), "예시 가게", "스무 자 안쪽은 그대로")
        for key in ("naver_a", "blogger_ko"):
            shown = cn.chip_label(key)
            self.assertLessEqual(len(shown), cn.CHANNEL_CHIP_LIMIT, key)
            self.assertTrue(shown.endswith("…"), key)
            self.assertTrue(cn.label(key).startswith(shown[:-1]), key)
            self.assertEqual(cn.full_if_cut(key, shown), cn.label(key), "줄였으면 전체 이름이 툴팁·접근 이름이다")
        self.assertEqual(cn.full_if_cut("naver_b", cn.chip_label("naver_b")), "", "줄이지 않았으면 툴팁이 따로 없다")

    def test_two_blogs_with_the_same_thirty_character_alias_keep_five_different_short_names_within_the_limit(self):
        self.names(TWIN)
        full = cn.current()
        self.assertGreater(len(full["naver_a"]), 40, "같은 별명 둘을 가른 이름은 마흔 자를 넘는다(이 시험의 전제)")
        shorts = {key: cn.chip_label(key) for key in cn.ORDER}
        self.assertTrue(all(len(value) <= cn.CHANNEL_CHIP_LIMIT for value in shorts.values()), shorts)
        self.assertEqual(len({value.casefold() for value in shorts.values()}), 5, shorts)
        self.assertEqual(shorts, cn.short_names(full, cn.CHANNEL_CHIP_LIMIT), "줄이는 규칙은 서랍과 같은 `short_names` 이고 길이만 다르다")
        self.assertNotEqual(shorts, cn.short_names(full), "서랍(열두 자)과는 다른 글이다")

    def test_the_cut_never_touches_the_stored_alias_or_the_full_label_or_the_drawer_label(self):
        self.names(MIXED)
        before = (cn.current(), {key: cn.short_label(key) for key in cn.ORDER})
        for key in cn.ORDER:
            cn.chip_label(key)
        self.assertEqual((cn.current(), {key: cn.short_label(key) for key in cn.ORDER}), before)
        self.assertEqual(cn.label("naver_a"), LONG30)
        self.assertEqual(cn.chip_label("no_such_key"), "no_such_key", "모르는 열쇠는 그대로")

    def test_the_seed_summary_chip_shows_the_cut_name_and_keeps_the_full_name_in_the_accessible_name_and_the_tooltip(self):
        self.names(MIXED)
        controller = sc.new_controller()
        rows = {row["key"]: row for row in controller.view()["summary"]["channels"]["rows"]}
        cut = rows["naver_a"]
        self.assertIn(cn.chip_label("naver_a"), cut["chip"]["text"])
        self.assertNotIn(LONG30, cut["chip"]["text"], "긴 별명은 칩 글에서 줄어든다")
        self.assertIn(LONG30, cut["a11y"], "접근 이름은 전체 이름")
        self.assertEqual(cut["chip"]["tip"], T["seeds_channel_chip"].format(name=LONG30, n=cut["count"], gen=cut["generation"]["text"]), "툴팁은 전체 이름이 든 같은 칩 글")
        short = rows["naver_b"]
        self.assertEqual(short["chip"]["tip"], "", "줄이지 않았으면 툴팁이 따로 없다")
        self.assertTrue(short["chip"]["text"].startswith("예시 가게 · "))
        other = rows["blogger_en"]
        self.assertEqual(other["chip"]["text"], T["seeds_channel_chip"].format(name="Blogger 2", n=other["count"], gen=other["generation"]["text"]))

    def test_the_seed_scope_filter_chips_show_the_cut_name_and_keep_the_full_name_as_the_tip_while_the_keys_are_unchanged(self):
        self.names(MIXED)
        controller = sc.new_controller()
        chips = {chip["key"]: chip for chip in controller.view()["filters"]["scope"]}
        self.assertEqual(list(chips), ["all", *sf.DISPLAY_SCOPES], "키와 순서는 그대로")
        self.assertEqual(chips["naver_a"]["label"], cn.chip_label("naver_a"))
        self.assertEqual(chips["naver_a"]["tip"], LONG30)
        self.assertEqual((chips["common"]["label"], chips["common"]["tip"], chips["all"]["tip"]), ("공통", "", ""))
        self.assertEqual((chips["naver_b"]["label"], chips["naver_b"]["tip"]), ("예시 가게", ""))
        self.assertEqual({chip["tip"] for chip in controller.view()["filters"]["status"]} | {chip["tip"] for chip in controller.view()["filters"]["importance"]}, {""}, "다른 거르기 칩에는 툴팁이 없다")
        self.assertEqual(len({chip["label"].casefold() for chip in chips.values()}), len(chips), "줄인 뒤에도 서로 다른 글이다")

    def test_the_seed_drawer_chips_still_use_the_twelve_character_names(self):
        self.names(MIXED)
        controller = sc.new_controller()
        controller.open_new()
        field = next(item for item in controller.drawer_view()["fields"] if item["name"] == "scope")
        option = next(item for item in field["options"] if item["value"] == "naver_a")
        self.assertEqual(option["label"], cn.short_label("naver_a"))
        self.assertLessEqual(len(option["label"]), cn.DRAWER_LIMIT)

    def test_the_candidate_channel_filter_chips_show_the_cut_name_the_full_name_stays_in_the_accessible_name_and_the_tip(self):
        self.names(MIXED)
        controller = cc.new_controller()
        chips = {chip["key"]: chip for chip in controller.view()["filters"]["channel"]}
        self.assertEqual(chips["naver_a"]["label"], cn.chip_label("naver_a"))
        self.assertEqual(chips["naver_a"]["tip"], LONG30)
        self.assertEqual(chips["naver_a"]["a11y"], T["cand_filter_channel_a11y"].format(name=LONG30, n=chips["naver_a"]["count"]))
        self.assertEqual((chips["all"]["label"], chips["all"]["tip"]), ("전체", ""))
        self.assertEqual((chips["naver_b"]["label"], chips["naver_b"]["tip"]), ("예시 가게", ""))
        other = controller.view()["filters"]["status"]
        self.assertEqual({chip["tip"] for chip in other}, {""}, "다른 거르기 칩에는 툴팁이 없다")
        self.assertEqual(len({chip["label"].casefold() for chip in chips.values()}), len(chips), "줄인 뒤에도 서로 다른 글이다")
        self.assertEqual(controller.channel_info("naver_a")["name"], LONG30, "카드·상세가 쓰는 이름은 전체 이름 그대로다")

    def test_the_draft_blog_chips_show_the_cut_name_and_keep_the_full_name_in_the_accessible_name_and_the_tip(self):
        self.names(MIXED)
        controller = dc.made(dc.GENERIC)
        blogs = {item["key"]: item for item in controller.view()["normal"]["options"]["blogs"]}
        self.assertEqual(list(blogs), ["naver_a", "naver_b"])
        self.assertEqual(blogs["naver_a"]["label"], cn.chip_label("naver_a"))
        self.assertEqual(blogs["naver_a"]["tip"], LONG30)
        self.assertEqual(blogs["naver_a"]["a11y"], T["drf_blog_a11y"].format(name=LONG30))
        self.assertEqual((blogs["naver_b"]["label"], blogs["naver_b"]["tip"]), ("예시 가게", ""))

    def test_the_seed_chip_name_functions_raise_for_an_unknown_scope_or_channel_like_the_full_and_drawer_name_functions(self):
        """독스트링이 약속한 동작 — 이름 규칙(`cn.label`·`short_label`·`chip_label`)은 모르는 열쇠를 그대로 돌려주므로 오류는 함수 첫머리의 검증 줄이 낸다. 그 줄을 지워도 옛 시험은 통과했다(검증 Q QP-2)."""
        for function in (sf.scope_name, sf.scope_short_name, sf.scope_chip_name, sf.channel_name, sf.channel_short_name, sf.channel_chip_name):
            with self.subTest(function.__name__), self.assertRaises(KeyError):
                function("모르는 열쇠")
        self.assertEqual(cn.chip_label("모르는 열쇠"), "모르는 열쇠", "이름 규칙 자체는 모르는 열쇠를 그대로 돌려준다 — 오류를 내는 것은 위 함수들의 검증 줄이다")

    def test_the_seed_chip_names_are_the_cut_names_of_the_five_channels_and_the_common_scope_is_left_as_it_is(self):
        self.names(MIXED)
        self.assertEqual(sf.scope_chip_name("common"), sf.scope_name("common"), "공통은 그대로")
        for key in cn.ORDER:
            self.assertEqual(sf.scope_chip_name(key), cn.chip_label(key), key)
            self.assertEqual(sf.channel_chip_name(key), cn.chip_label(key), key)
        self.assertNotEqual(sf.scope_chip_name("naver_a"), sf.scope_name("naver_a"), "서른 자 별명은 칩 이름에서 줄어든다")
        self.assertLessEqual(len(sf.channel_chip_name("naver_a")), cn.CHANNEL_CHIP_LIMIT)
        self.assertGreater(len(sf.channel_chip_name("naver_a")), cn.DRAWER_LIMIT, "서랍의 열두 자가 아니라 주 화면의 스무 자 기준이다")
        self.assertEqual((sf.scope_chip_name("naver_b"), sf.channel_chip_name("naver_b")), ("예시 가게", "예시 가게"))

    def test_a_channel_outside_the_five_gets_its_chip_name_cut_at_the_same_limit_and_keeps_its_full_name_as_the_tip(self):
        """채널 칩을 만드는 쪽(`candidates_view._chip_name`)은 다섯 채널이 아닌 열쇠도 같은 한도로 줄인다 — 지금 화면에서는 닿기 어려운 길이지만 독스트링이 약속한 동작이다(검증 Q QP-2·S SP-3: 한도를 서른으로 바꿔도 시험이 통과했다)."""
        provider = cc.cd.FakeCandidatesProvider()
        data = provider.load_candidates(cc.SAFE, cc.NEVER)
        data = dataclasses.replace(data, channels=(*data.channels, cc.cd.ChannelInfo("extra_channel", LONG30, None, True)))
        controller = cc.new_controller(provider, data)
        chips = {chip["key"]: chip for chip in controller.view()["filters"]["channel"]}
        chip = chips["extra_channel"]
        self.assertEqual(len(chip["label"]), cn.CHANNEL_CHIP_LIMIT, chip)
        self.assertTrue(chip["label"].endswith("…") and LONG30.startswith(chip["label"][:-1]), chip)
        self.assertEqual(chip["tip"], LONG30, "줄였으면 전체 이름이 툴팁")
        self.assertEqual(chip["a11y"], T["cand_filter_channel_a11y"].format(name=LONG30, n=chip["count"]), "접근 이름은 전체 이름")
        self.assertEqual(list(chips)[-1], "extra_channel", "다섯 채널 뒤에 놓인다")

    def test_the_twin_names_never_make_a_chip_longer_than_the_limit_on_the_three_main_screens(self):
        self.names(TWIN)
        seeds_view = sc.new_controller().view()
        widest = max(len(row["chip"]["text"].split(" · ")[0]) for row in seeds_view["summary"]["channels"]["rows"])
        self.assertLessEqual(widest, cn.CHANNEL_CHIP_LIMIT, "Seed 요약 칩의 이름")
        self.assertLessEqual(max(len(chip["label"]) for chip in seeds_view["filters"]["scope"]), cn.CHANNEL_CHIP_LIMIT, "Seed 소속 칩")
        self.assertLessEqual(max(len(chip["label"]) for chip in cc.new_controller().view()["filters"]["channel"]), cn.CHANNEL_CHIP_LIMIT, "후보 채널 칩")
        self.assertLessEqual(max(len(item["label"]) for item in dc.made(dc.GENERIC).view()["normal"]["options"]["blogs"]), cn.CHANNEL_CHIP_LIMIT, "초안 블로그 칩")


class PlaceFoldRuleTest(unittest.TestCase):
    """POLISH-1 M-2 — 종류를 고르면 기본 '들어갈 곳' 이 생겨 접힌 `자리 정하기` 가 저절로 펼쳐지고 한 줄이 749px 가 되던 것: 종류가 정한 기본값은 펼치지 않고 한 줄 요약(`들어갈 곳: … ▸`)만 보이게, 사용자가 직접 고른 값·설명 글이 있을 때만 펼친다."""

    def board(self):
        return pc.new_board(1)

    def place(self, board, photo_id="p001"):
        return pc.row_of(board, photo_id)["place"]

    def test_choosing_a_type_never_opens_the_place_part_and_the_folded_button_summarises_the_default_place(self):
        expected = {"간판": "들어갈 곳: 도입 ▸", "건물 외관": "들어갈 곳: 도입 ▸", "메뉴판": "들어갈 곳: 내용 소제목 ▸", "대표 메뉴": "들어갈 곳: 내용 소제목 ▸", "음식": "들어갈 곳: 내용 소제목 ▸",
                    "반찬": "들어갈 곳: 내용 소제목 ▸", "인테리어": "들어갈 곳: 분위기 소제목 ▸", "지도 캡처": T["pho_place_open"], "기타": T["pho_place_open"]}
        self.assertEqual(set(expected), set(rules.TYPES), "아홉 종류 모두")
        for label, summary in expected.items():
            with self.subTest(label):
                board = self.board()
                board.set_type("p001", label)
                place = self.place(board)
                self.assertFalse(place["open"], label)
                self.assertEqual(place["open_text"], summary, label)
                self.assertEqual(place["close_text"], T["pho_place_close"])

    def test_a_place_the_user_chose_opens_the_part_and_a_value_equal_to_the_default_does_not(self):
        board = self.board()
        board.set_type("p001", "간판")
        self.assertEqual(board.set_section("p001", "마무리"), "ok")
        place = self.place(board)
        self.assertTrue(place["open"], "기본값(도입)이 아닌 들어갈 곳은 사용자가 고른 값이다")
        self.assertEqual(place["open_text"], "들어갈 곳: 마무리 ▸")
        board.set_section("p001", "도입")
        self.assertFalse(self.place(board)["open"], "기본값과 같으면 사용자가 고른 것으로 보지 않는다")
        board.set_section("p001", "")
        place = self.place(board)
        self.assertTrue(place["open"], "간판에서 직접 '자동' 을 골랐다 — 기본값(도입)과 다르다")
        self.assertEqual(place["open_text"], "들어갈 곳: 자동 ▸", "자동도 요약에 나온다")
        board.set_type("p001", "기타")
        self.assertFalse(self.place(board)["open"], "기타의 기본값은 자동이라 비어 있으면 사용자가 고른 것이 아니다")
        self.assertEqual(self.place(board)["open_text"], T["pho_place_open"])

    def test_a_chosen_place_stays_when_the_type_changes_and_keeps_the_part_open(self):
        board = self.board()
        board.set_type("p001", "간판")
        board.set_section("p001", "마무리")
        board.set_type("p001", "음식")
        place = self.place(board)
        self.assertEqual(place["section"]["value"], "마무리", "사용자가 고른 들어갈 곳은 종류를 바꿔도 그대로다")
        self.assertTrue(place["open"])

    def test_a_caption_or_a_chosen_position_opens_the_part_whatever_the_type_default_is(self):
        for act, label in ((lambda board: board.set_text("p001", "caption", "기본 반찬"), "설명 글"), (lambda board: board.set_placement("p001", "top"), "자리")):
            with self.subTest(label):
                board = self.board()
                board.set_type("p001", "음식")
                self.assertFalse(self.place(board)["open"], "기본값만 있을 때")
                act(board)
                self.assertTrue(self.place(board)["open"], label)

    def test_the_accessible_name_of_the_button_says_the_current_place_only_when_there_is_one(self):
        board = self.board()
        self.assertEqual(self.place(board)["a11y"], T["pho_place_a11y"].format(n=1))
        board.set_type("p001", "인테리어")
        self.assertEqual(self.place(board)["a11y"], T["pho_place_a11y_now"].format(n=1, section="분위기 소제목"))
        self.assertIn("지금은 분위기 소제목", self.place(board)["a11y"])

    def test_a_section_text_the_later_stage_wrote_is_shown_cut_and_masked_in_the_summary(self):
        board = self.board()
        board.set_type("p001", "기타")
        self.assertEqual(board._apply("p001", preferred_section="가" * 40), "ok", "나중 단계가 적은 소제목 글은 이미 있는 값으로만 들어온다 — 시험은 규칙 안쪽 길로 넣는다")
        place = self.place(board)
        self.assertTrue(place["open"])
        self.assertEqual(place["open_text"], T["pho_place_summary"].format(section=rules.section_text("가" * 40)))
        self.assertLessEqual(len(rules.section_text("가" * 40)), 30)
        self.assertEqual((rules.section_text(""), rules.section_text("도입")), (T["pho_section_auto"], T["pho_section_intro"]))

    def test_the_row_keys_are_the_same_so_the_screen_has_nothing_new_to_read(self):
        board = self.board()
        row = pc.row_of(board)
        self.assertEqual(set(row["place"]), {"open", "open_text", "close_text", "a11y", "section", "kind", "nth"})


class LeaveAndSaveWordingTest(unittest.TestCase):
    """PQ-24·PQ-26 — 사진 정보를 저장할 길이 막힌 초안의 떠나기 질문은 이유 문장이 물음 앞이고, 저장 알림은 시각과 둘째 문장을 가운뎃점으로 가른다."""

    REASON = "넣어 둔 사진 정보는 저장해 둔 사진 정보 파일을 읽을 수 없어서 저장되지 않아요."

    def opened(self):
        controller, _provider, _draft_id = psc.opened_with_state("broken")
        controller.photos.add_paths([psc.path_of(7), psc.path_of(8)])
        return controller

    def test_the_reason_comes_before_the_question_in_the_two_way_and_three_way_leave_and_close_texts(self):
        controller = self.opened()
        self.assertEqual(controller.leave_dialog("leave")["body"], "넣어 둔 사진 2장의 정보는 아직 저장되지 않아서 다른 화면으로 가면 사라져요. 사진 파일은 그대로 있어요. " + self.REASON + " 그래도 이동할까요?")
        self.assertEqual(controller.leave_dialog("close")["body"], "넣어 둔 사진 2장의 정보는 아직 저장되지 않아서 앱을 닫으면 사라져요. 사진 파일은 그대로 있어요. " + self.REASON + " 그래도 닫을까요?")
        controller.discard_leave()
        controller.set_body(controller.body + " 고침")
        self.assertEqual(controller.leave_dialog("leave")["body"], "이 초안에 고친 내용이 저장되지 않았어요. " + self.REASON + " 저장하고 이동할까요?")
        self.assertEqual(controller.leave_dialog("close")["body"], "이 초안에 고친 내용이 저장되지 않았어요. " + self.REASON + " 저장하고 앱을 닫을까요?")

    def test_the_question_is_the_last_sentence_of_every_leave_text_with_or_without_the_reason(self):
        controller = self.opened()
        for kind in ("leave", "close"):
            body = controller.leave_dialog(kind)["body"]
            self.assertTrue(body.endswith("?") and body.count("?") == 1, body)
            self.assertTrue(body.index(self.REASON) < body.rindex("까요?"), body)
            controller.discard_leave()

    def test_the_helper_puts_the_reason_before_the_last_sentence_and_in_front_when_there_is_no_sentence_break(self):
        self.assertEqual(dv._reason_before_question("가나다. 라마바?", "이유."), "가나다. 이유. 라마바?")
        self.assertEqual(dv._reason_before_question("하나. 둘. 셋?", "이유."), "하나. 둘. 이유. 셋?")
        self.assertEqual(dv._reason_before_question("물음?", "이유."), "이유. 물음?")

    def test_the_save_notice_that_says_the_photo_info_was_not_saved_splits_the_time_from_the_second_sentence(self):
        self.assertEqual(T["pho_saved_with_note"].format(saved="초안을 저장했어요 · 2026-11-05 18:02", note=T["pho_saved_without_photos"]), "초안을 저장했어요 · 2026-11-05 18:02 · 사진 정보는 저장하지 않았어요.")
        controller = self.opened()
        controller.set_body(controller.body + " 고침")
        psc.store(controller, "save")
        level, message = controller.notice
        self.assertEqual(level, "info")
        self.assertTrue(message.startswith("초안을 저장했어요 · ") and message.endswith(" · " + T["pho_saved_without_photos"]), message)
        self.assertEqual(message.count(" · "), 2, "시각 앞과 둘째 문장 앞, 두 곳에 가운뎃점이 있다")


if __name__ == "__main__":
    unittest.main()
