"""다른 화면이 채널(블로그 슬롯)을 부르는 이름(`ui/core/channel_names.py` — blogsel-2, D-510)의 순수 시험(PySide6 없이 돈다 — CI 와 같은 조건).

지키는 것:
  1) 이름 규칙은 블로그 관리 카드 윗줄과 같다 — 카드로 보이는 슬롯은 별명(없으면 종류 + 번호), 카드가 아닌 슬롯은 종류 이름(번호가 있는 종류는 번호까지, 한 자리뿐인 GitHub Pages 는 종류 이름 그대로).
  2) 별명은 키·토큰 모양을 가리고 길면 자르며, 같은 이름이 둘이면 `(종류 + 번호)` 를 덧붙여 가른다 — 어느 경우에도 다섯 이름이 모두 다르다.
  3) 화면이 쓰는 켜 둔 이름(`use`·`label`)은 `AppState.refresh_names` 가 블로그 관리가 읽은 자료로 정하고, 닫히면(None) 별명 없는 기본 이름으로 돌아간다 — 옛 고정 이름(`네이버 A`)은 어디에도 없다.
  4) 홈의 채널 열쇠(A·B)와 아바타 글자도 같은 이름에서 나온다.
실제 블로그 이름·아이디·주소는 이 시험에 없다(예시 값뿐).
"""
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chanceblog_desktop.ui.core import app_state, blog_form as bf, blogs, blogs_view, channel_names as cn, jobs, services, text  # noqa: E402

SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
T = text.T
OLD_NAMES = re.compile(r"네이버 [AB]\b|Blogger (?:한글|영문)|블로그 [AB]\b|Naver [AB]|naver_[ab]|blogger_(?:ko|en)|github_pages")
KEY = "AKIA" + "ABCDEFGHIJKLMNOP"                                              # 키 모양 시험 글(진짜 키가 아니다)
DEFAULTS = {"naver_a": "네이버 블로그 1", "naver_b": "네이버 블로그 2", "blogger_ko": "Blogger 1", "blogger_en": "Blogger 2", "github_pages": "GitHub Pages"}


def loaded(scenario="normal"):
    controller = blogs_view.BlogsController(blogs.FakeBlogsProvider(scenario), jobs.JobRunner())
    controller.apply_loaded(controller.provider.load_blogs(SAFE, NEVER))
    return controller


class LabelRuleTest(unittest.TestCase):
    def tearDown(self):
        cn.use(None)

    def test_without_any_data_every_channel_has_a_plain_kind_name_and_never_an_old_fixed_name(self):
        self.assertEqual(cn.labels(None), DEFAULTS)
        self.assertEqual(cn.DEFAULT, DEFAULTS)
        self.assertEqual(list(cn.ORDER), ["naver_a", "naver_b", "blogger_ko", "blogger_en", "github_pages"], "종류별 채움 순서")
        for name in DEFAULTS.values():
            self.assertIsNone(OLD_NAMES.search(name), name)

    def test_a_listed_slot_shows_its_alias_or_the_suggested_kind_and_number_and_an_unlisted_slot_shows_the_kind(self):
        items = {"naver_a": ("내 맛집 블로그", True), "naver_b": ("", True), "blogger_ko": ("", False), "blogger_en": ("영문 일기", False), "github_pages": ("", True)}
        labels = cn.labels(items)
        self.assertEqual(labels["naver_a"], "내 맛집 블로그")
        self.assertEqual(labels["naver_b"], "네이버 블로그 2", "별명이 없으면 종류 + 번호 제안")
        self.assertEqual(labels["blogger_ko"], "Blogger 1", "카드가 아닌 슬롯은 종류 이름(번호가 있는 종류는 번호까지)")
        self.assertEqual(labels["blogger_en"], "Blogger 2", "카드가 아닌 슬롯의 별명은 쓰지 않는다")
        self.assertEqual(labels["github_pages"], "GitHub Pages 1", "카드로 보이는 슬롯은 카드 윗줄과 같다")
        self.assertEqual(cn.labels({"github_pages": ("", False)})["github_pages"], "GitHub Pages", "한 자리뿐인 종류는 카드가 아니면 종류 이름 그대로")

    def test_the_label_of_every_card_is_exactly_the_title_of_the_card_in_the_blog_screen(self):
        controller = loaded()
        labels = cn.labels(cn.entries(controller.data, controller.adding))
        for card in controller.view()["list"]["cards"]:
            self.assertEqual(labels[card["key"]], card["title"], card["key"])

    def test_the_entries_of_the_read_data_mark_the_registered_and_the_opening_slots_as_cards(self):
        controller = loaded("empty")
        self.assertEqual({key: listed for key, (_alias, listed) in cn.entries(controller.data).items()}, dict.fromkeys(cn.ORDER, False))
        self.assertIsNone(cn.entries(None))
        controller.open_picker()
        key = controller.start_adding("naver")
        self.assertTrue(cn.entries(controller.data, controller.adding)[key][1], "새로 연결하는 중인 슬롯도 카드다")
        self.assertEqual(cn.labels(cn.entries(controller.data, controller.adding))["naver_a"], "네이버 블로그 1")

    def test_a_key_shaped_alias_is_masked_and_a_long_alias_is_cut(self):
        shown = cn.labels({"naver_a": ("별명 " + KEY, True)})["naver_a"]
        self.assertNotIn(KEY[:10], shown)
        long = cn.labels({"naver_a": ("가" * 80, True)})["naver_a"]
        self.assertLessEqual(len(long), cn.LIMIT)
        self.assertEqual(len(set(cn.labels({"naver_a": ("가" * 80, True)}).values())), 5)
        self.assertLessEqual(len(cn.labels({"naver_a": ("가나다라마바사아자차카타파하", True)}, limit=10)["naver_a"]), 10, "자르는 길이는 부르는 쪽이 정한다(좁은 자리)")

    def test_two_blogs_with_the_same_name_get_the_kind_and_number_added_so_all_five_names_differ(self):
        labels = cn.labels({"naver_a": ("내 블로그", True), "naver_b": ("내 블로그", True), "blogger_ko": ("", False), "blogger_en": ("", False), "github_pages": ("", False)})
        self.assertEqual((labels["naver_a"], labels["naver_b"]), ("내 블로그 (네이버 블로그 1)", "내 블로그 (네이버 블로그 2)"))
        self.assertEqual(len(set(labels.values())), 5)
        clash = cn.labels({"naver_a": ("네이버 블로그 2", True), "naver_b": ("", True)})                    # 한 블로그의 별명이 다른 슬롯의 기본 이름과 같아도
        self.assertEqual((clash["naver_a"], clash["naver_b"]), ("네이버 블로그 2 (네이버 블로그 1)", "네이버 블로그 2"))
        self.assertEqual(len(set(label.casefold() for label in clash.values())), 5)
        same_case = cn.labels({"naver_a": ("My Blog", True), "naver_b": ("my blog", True)})
        self.assertNotEqual(same_case["naver_a"].casefold(), same_case["naver_b"].casefold(), "대소문자만 다른 이름도 가른다")

    def test_the_kind_and_number_added_to_a_long_name_is_never_cut_and_the_second_pass_numbers_start_at_two(self):
        """검증 Q2-5(B05·B07): 한도(30자) 가득한 같은 별명 둘에도 덧붙인 `(종류 + 번호)` 가 잘리지 않고, 그래도 겹치면 `#2` 부터 번호를 붙인다."""
        long = "가" * cn.LIMIT
        labels = cn.labels({"naver_a": (long, True), "naver_b": (long, True)})
        self.assertEqual((labels["naver_a"], labels["naver_b"]), (f"{long} (네이버 블로그 1)", f"{long} (네이버 블로그 2)"), "덧붙인 글은 한도 밖에서도 잘리지 않는다")
        clash = cn.labels({"naver_a": ("Z", True), "naver_b": ("Z", True), "blogger_ko": ("Z (네이버 블로그 1)", True)})        # 첫 가르기 뒤에도 겹치면
        self.assertEqual((clash["naver_a"], clash["naver_b"], clash["blogger_ko"]), ("Z (네이버 블로그 1)", "Z (네이버 블로그 2)", "Z (네이버 블로그 1) #2"), "안전망의 번호는 2 부터다")
        self.assertEqual(len({label.casefold() for label in clash.values()}), 5)

    def test_names_that_differ_only_in_case_are_told_apart_by_the_first_pass_not_left_for_the_safety_net(self):
        """검증 Q2-5(B06): 대소문자만 다른 이름도 첫 단계에서 `(종류 + 번호)` 로 가른다 — `#2` 안전망이 대신 가르는 것이 아니다."""
        labels = cn.labels({"naver_a": ("My Blog", True), "naver_b": ("my blog", True)})
        self.assertEqual((labels["naver_a"], labels["naver_b"]), ("My Blog (네이버 블로그 1)", "my blog (네이버 블로그 2)"))


class ReservedTextTest(unittest.TestCase):
    """검증 S3-1: 별명이 칩 곁의 고정 글(`공통`·`전체`·`모든 소속`)과 같으면 서로 다른 칩이 같은 글이 된다 — 소속(전체 채널 대 한 채널)·거르기(전체 대 한 채널)를 잘못 고를 수 있다. 서비스는 이런 별명을 받는다."""

    def tearDown(self):
        cn.use(None)

    def test_the_reserved_texts_are_exactly_the_fixed_chip_texts_that_sit_beside_the_channel_chips(self):
        from chanceblog_desktop.topics import wording
        self.assertEqual(cn.COMMON_SCOPE, wording.SCOPE_KO["common"], "서비스의 소속 이름 `공통` 과 같다")
        self.assertEqual({T["cand_all"], T["seeds_all"], T["seeds_scope_all"]}, {"전체", "모든 소속"}, "채널 칩 곁의 거르기 `전체`·`모든 소속` 이 바뀌면 이 시험이 빨개진다")
        self.assertEqual({T["seeds_status_proposed"], T["seeds_status_active"], T["seeds_status_inactive"]}, {"승인 전", "사용 중", "쉬는 중"}, "Seed 상태 칩의 낱말이 바뀌면 이 시험이 빨개진다(POLISH-1 Q4-2)")
        self.assertEqual(cn.RESERVED, frozenset({"공통", "전체", "모든소속", "승인전", "사용중", "쉬는중"}), "공백을 없앤 모양")

    def test_the_fold_ignores_every_space_and_the_case(self):
        self.assertEqual(cn._fold(" 공 통 "), cn._fold("공통"))
        self.assertEqual(cn._fold(" A b "), cn._fold("ab"))
        self.assertEqual(cn._fold("ABC"), cn._fold("abc"))
        self.assertNotEqual(cn._fold("공통점"), cn._fold("공통"))

    def test_an_alias_that_reads_like_a_fixed_chip_text_gets_the_kind_and_number_added_whatever_the_spaces(self):
        for alias in ("공통", "전체", "모든 소속", " 공 통 ", "전 체", "모든소속", "공통\t"):
            labels = cn.labels({"naver_a": (alias, True), "naver_b": ("", True)})
            self.assertEqual(labels["naver_a"], f"{bf.clean_line(alias)} (네이버 블로그 1)", repr(alias))
            self.assertNotIn(cn._fold(labels["naver_a"]), cn.RESERVED, repr(alias))
            self.assertEqual(len({value.casefold() for value in labels.values()}), 5, repr(alias))
        near = cn.labels({"naver_a": ("공통점", True), "naver_b": ("전체 보기", True)})
        self.assertEqual((near["naver_a"], near["naver_b"]), ("공통점", "전체 보기"), "고정 글과 같을 때만 덧붙인다 — 비슷한 글은 그대로")

    def test_the_kind_names_and_the_default_names_never_read_like_a_fixed_chip_text(self):
        self.assertTrue(set(cn.DEFAULT.values()).isdisjoint(cn.RESERVED))
        self.assertTrue({cn._fold(value) for value in cn.DEFAULT.values()}.isdisjoint(cn.RESERVED))

    def test_an_alias_that_reads_like_a_status_chip_word_of_the_seed_summary_gets_the_kind_and_number_added(self):
        """POLISH-1 Q4-2 — Seed 요약 줄에서 채널 칩 곁에 서는 상태 칩의 낱말(`사용 중`·`쉬는 중`·`승인 전`)과 같은 별명은 같은 글로 읽혔다(`사용 중 5개` 곁에 `사용 중 3개 · 후보 생성 켜짐`). 낱말은 문구 표에서 읽어 온다."""
        for word in (T["seeds_status_active"], T["seeds_status_inactive"], T["seeds_status_proposed"]):
            for alias in (word, word.replace(" ", ""), " ".join(word.replace(" ", "")), f" {word} "):
                labels = cn.labels({"naver_a": (alias, True), "naver_b": ("", True)})
                self.assertEqual(labels["naver_a"], f"{bf.clean_line(alias)} (네이버 블로그 1)", repr(alias))
                self.assertNotIn(cn._fold(labels["naver_a"]), cn.RESERVED, repr(alias))
                self.assertEqual(len({value.casefold() for value in labels.values()}), 5, repr(alias))
        near = cn.labels({"naver_a": ("사용 중인 블로그", True), "naver_b": ("쉬는 중 메모", True), "blogger_ko": ("승인", True)})
        self.assertEqual((near["naver_a"], near["naver_b"], near["blogger_ko"]), ("사용 중인 블로그", "쉬는 중 메모", "승인"), "낱말과 같을 때만 덧붙인다 — 비슷한 글은 그대로")

    def test_the_status_words_in_the_reserved_set_are_read_from_the_wording_table_not_typed_again(self):
        """글자를 새로 박지 않는다 — 문구 표의 상태 낱말을 바꾸면 가름 목록도 따라간다(소스에 낱말이 없다)."""
        source = Path(cn.__file__).read_text(encoding="utf-8")
        for word in ("승인 전", "사용 중", "쉬는 중"):
            self.assertNotIn(word, source.split("RESERVED = ", 1)[1].split("\n", 1)[0].split("#", 1)[0], word)
        for key in ("seeds_status_proposed", "seeds_status_active", "seeds_status_inactive"):
            self.assertIn(f'T["{key}"]', source, key)

    def test_a_kind_with_one_slot_adds_no_number_to_the_kind_it_appends_while_a_kind_with_two_slots_does(self):
        """POLISH-1 Q4-3 — 한 자리뿐인 종류(GitHub Pages)는 `전체 (GitHub Pages 1)` 이 아니라 `전체 (GitHub Pages)`(기본 이름 `_kind_name` 과 같은 규칙). 자리가 둘인 종류는 번호까지(`공통 (네이버 블로그 1)`)."""
        for alias in ("전체", "모든 소속", "공통", "사용 중"):
            labels = cn.labels({"github_pages": (alias, True)})
            self.assertEqual(labels["github_pages"], f"{alias} (GitHub Pages)", alias)
            self.assertNotIn("GitHub Pages 1", labels["github_pages"], alias)
        two = cn.labels({"naver_a": ("전체", True), "naver_b": ("전체", True), "blogger_ko": ("공통", True), "blogger_en": ("모든 소속", True), "github_pages": ("전체", True)})
        self.assertEqual(two, {"naver_a": "전체 (네이버 블로그 1)", "naver_b": "전체 (네이버 블로그 2)", "blogger_ko": "공통 (Blogger 1)", "blogger_en": "모든 소속 (Blogger 2)", "github_pages": "전체 (GitHub Pages)"})
        same = cn.labels({"blogger_en": ("맛집", True), "github_pages": ("맛집", True)})                     # 같은 이름 가르기도 같은 규칙이다
        self.assertEqual((same["blogger_en"], same["github_pages"]), ("맛집 (Blogger 2)", "맛집 (GitHub Pages)"))
        self.assertEqual(len({value.casefold() for value in same.values()}), 5)
        self.assertEqual(cn.labels({"github_pages": ("", True)})["github_pages"], "GitHub Pages 1", "카드 윗줄은 그대로 — 별명이 없으면 제안 이름(번호 포함)이다")


class RegistryTest(unittest.TestCase):
    def tearDown(self):
        cn.use(None)

    def test_the_active_names_start_as_the_defaults_change_with_use_and_go_back_with_none(self):
        self.assertEqual(cn.current(), DEFAULTS)
        self.assertEqual(cn.label("naver_a"), "네이버 블로그 1")
        self.assertTrue(cn.use(cn.labels({"naver_a": ("예시 별명", True)})))
        self.assertEqual((cn.label("naver_a"), cn.label("naver_b")), ("예시 별명", "네이버 블로그 2"))
        self.assertFalse(cn.use(cn.labels({"naver_a": ("예시 별명", True)})), "같은 이름이면 바뀐 것이 아니다")
        self.assertTrue(cn.use(None))
        self.assertEqual(cn.label("naver_a"), "네이버 블로그 1")
        self.assertEqual(cn.label("no_such_key"), "no_such_key", "모르는 열쇠는 그대로")

    def test_the_home_keys_and_the_avatar_letter_come_from_the_same_names(self):
        cn.use(cn.labels({"naver_a": ("맛집 블로그", True)}))
        self.assertEqual((cn.home_label("A"), cn.home_label("B"), cn.home_label("C")), ("맛집 블로그", "네이버 블로그 2", ""))
        self.assertEqual((cn.avatar_letter("naver_a"), cn.avatar_letter("naver_b")), ("맛", "2"), "별명이 있으면 별명의 첫 글자, 기본 이름이면 번호")
        cn.use(None)
        self.assertEqual([cn.avatar_letter(key) for key in cn.ORDER], ["1", "2", "1", "2", "G"])

    def test_the_avatar_letter_is_the_number_only_for_the_suggested_default_name_not_for_an_alias_the_user_made_up_that_ends_in_a_digit(self):
        """검증 Q2-5(B08): 기본 이름(`네이버 블로그 1`)일 때만 번호이고, 사용자가 정한 별명이 숫자로 끝나도(`맛집 2`) 첫 글자다."""
        cn.use(cn.labels({"naver_a": ("맛집 2", True), "naver_b": ("", True)}))
        self.assertEqual((cn.avatar_letter("naver_a"), cn.avatar_letter("naver_b")), ("맛", "2"))

    def test_the_app_state_keeps_the_names_from_the_blog_data_and_tells_when_they_changed(self):
        state = app_state.AppState(services.FakeHomeProvider())
        self.assertEqual(cn.current(), DEFAULTS, "새 상태는 별명 없는 기본 이름으로 시작한다")
        self.assertFalse(state.refresh_names(), "아직 못 읽었으면 바뀔 것이 없다")
        state.blogs.apply_loaded(state.blogs.provider.load_blogs(SAFE, NEVER))
        self.assertTrue(state.refresh_names())
        self.assertEqual((cn.label("naver_a"), cn.label("naver_b"), cn.label("blogger_ko")), ("예시 별명", "네이버 블로그 2", "Blogger 1"))
        self.assertFalse(state.refresh_names(), "다시 정해도 같으면 바뀐 것이 아니다")
        state.blogs.select("naver_a")
        state.blogs.edit("alias", "새 별명")
        self.assertFalse(state.refresh_names(), "저장하기 전의 입력은 이름을 바꾸지 않는다")
        app_state.AppState(services.FakeHomeProvider())
        self.assertEqual(cn.current(), DEFAULTS, "새 상태가 만들어지면 켜 둔 이름을 비운다")


class OtherScreensUseTheNamesTest(unittest.TestCase):
    """다른 화면의 뷰모델이 옛 고정 이름이 아니라 이 이름을 쓴다(각 화면의 자세한 시험은 그 화면 시험에 있다)."""

    def tearDown(self):
        cn.use(None)

    def test_the_seed_names_follow_the_labels(self):
        from chanceblog_desktop.ui.core import seed_form as sf
        cn.use(cn.labels({"naver_a": ("예시 별명", True)}))
        self.assertEqual([sf.channel_name(code) for code in sf.CHANNEL_ORDER], [cn.label(code) for code in sf.CHANNEL_ORDER])
        self.assertEqual((sf.scope_name("common"), sf.scope_name("naver_a")), ("공통", "예시 별명"))
        with self.assertRaises(KeyError):
            sf.channel_name("no_such_channel")
        for unknown in (sf.scope_name, sf.scope_short_name, sf.channel_short_name):                  # 검증 S2-8: 모르는 소속·채널은 이름을 지어 보이지 않고 오류다(열쇠 글자가 그대로 화면에 나가지 않게)
            with self.assertRaises(KeyError, msg=unknown.__name__):
                unknown("no_such_scope")

    def test_the_home_rows_carry_the_badge_letter_of_the_screen_name_while_the_colour_key_stays_a_or_b(self):
        from test_ui_c1c_core import channel, rec
        from chanceblog_desktop.ui.core import board_view
        view = board_view.channel_vm(channel("A", [rec("하나")]))
        self.assertEqual((view["rows"][0]["channel"], view["rows"][0]["badge"]), ("A", "1"), "색을 정하는 열쇠는 A·B 그대로이고 글자는 별명 없는 기본 이름의 번호")
        cn.use(cn.labels({"naver_b": ("맛집 블로그", True)}))
        other = board_view.channel_vm(channel("B", [rec("둘")]))
        self.assertEqual((other["rows"][0]["channel"], other["rows"][0]["badge"], other["name"]), ("B", "맛", "맛집 블로그"))

    def test_no_screen_text_of_the_fake_screens_has_an_old_fixed_name(self):
        state = app_state.AppState(services.FakeHomeProvider())
        state.blogs.apply_loaded(state.blogs.provider.load_blogs(SAFE, NEVER))
        state.refresh_names()
        found = []

        def walk(value, where):
            if isinstance(value, str):
                if OLD_NAMES.search(value):
                    found.append((where, value[:60]))
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key not in ("key", "id", "channel", "selected"):                                          # 열쇠·코드 칸은 글이 아니다
                        walk(item, where + "." + str(key))
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    walk(item, where + f"[{index}]")

        state.seeds.apply_loaded(state.seeds.provider.load_seeds(SAFE, NEVER))
        state.candidates.apply_loaded(state.candidates.provider.load_candidates(SAFE, NEVER))
        views = {"seeds": state.seeds_view(), "candidates": state.candidates_view(), "drafts": state.drafts_view(), "blogs": state.blogs_view()}
        self.assertEqual(views["seeds"]["state"], "normal", "시험이 실제로 Seed 를 읽었다")
        self.assertTrue(views["seeds"]["summary"], "채널별 쓸 수 있는 수 칩이 있다")
        self.assertTrue(views["candidates"]["grid"]["cards"], "시험이 실제로 후보 카드를 읽었다")
        for name, view in views.items():
            walk(view, name)
        self.assertEqual(found, [], "옛 고정 이름이 화면 글에 남았다")



class SourceNotesTest(unittest.TestCase):
    """검증 Q3-5·S3-4: 옛 이름을 말하는 설명이 남지 않고, 가져온 도우미 함수의 이름을 매개변수가 가리지 않는다."""

    SRC = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"

    def test_the_avatar_docstring_describes_the_letter_rule_as_it_is(self):
        text = (self.SRC / "candidate_parts.py").read_text(encoding="utf-8")
        self.assertNotIn("네이버 A·B 는 A·B", text, "옛 규칙(채널 열쇠 글자)이다")
        self.assertIn("channel_names.avatar_letter", text)
        self.assertIn("끝 숫자", text)

    def test_no_parameter_of_a_component_factory_hides_the_imported_ampersand_helper(self):
        import ast
        tree = ast.parse((self.SRC / "components.py").read_text(encoding="utf-8"))
        helpers = {alias.asname or alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module == "core.channel_names" or isinstance(node, ast.ImportFrom) and (node.module or "").endswith("channel_names") for alias in node.names}
        self.assertEqual(len(helpers), 1, helpers)
        parameters = {argument.arg for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.Lambda)) for argument in (*node.args.args, *node.args.kwonlyargs)}
        self.assertTrue(helpers.isdisjoint(parameters), f"가져온 함수 {helpers} 를 가리는 매개변수가 있다: {helpers & parameters}")
        self.assertNotIn("button_text", helpers, "`StateCard(…, button_text=…)` 매개변수와 같은 이름으로 가져오지 않는다(호출자는 키워드로 쓸 수 있다)")


LONG_A = "가나다라마바사아자차카타파하" * 2                       # 28자
LONG_B = LONG_A + "가"                                          # 29자 — 열두 자로 줄이면 LONG_A 와 같아진다


def home_state():
    provider = services.FakeHomeProvider("normal")
    state = app_state.AppState(provider)
    state.apply_home(provider.load_home(SAFE, NEVER))
    return state


def seed_options(view, name):
    return next(field for field in view["fields"] if field["name"] == name)["options"]


class NarrowPlacesTest(unittest.TestCase):
    """서랍처럼 좁은 자리(폭 420)에 보이는 이름 — 긴 별명이 서랍을 넘치게 해 오른쪽 열·`{이름} 초안` 단추·닫기(X)가 잘렸다(검증 Q2-1, 필수). 그래서 열두 자로 줄이고(넘으면 …) 전체 이름은 툴팁·접근 이름에 따로 싣는다.
    줄이는 규칙(`channel_names.short_names`)과 그것을 쓰는 뷰모델(홈 서랍·Seed 서랍 칩)을 본다 — Qt 쪽의 '서랍보다 안 넓다' 는 `test_ui_qt_drawer_names` 가 본다."""

    def tearDown(self):
        cn.use(None)

    def test_a_name_up_to_the_limit_is_kept_and_a_longer_one_is_cut_to_exactly_the_limit_with_an_ellipsis(self):
        limit = cn.DRAWER_LIMIT
        self.assertEqual(limit, 12)
        cn.use(cn.labels({"naver_a": ("가" * limit, True), "naver_b": ("가" * (limit + 1), True)}))
        self.assertEqual(cn.short_label("naver_a"), "가" * limit, "경계(열두 자)는 줄이지 않는다")
        self.assertEqual(cn.short_label("naver_b"), "가" * (limit - 1) + "…", "열세 자부터 줄여 열두 자(…까지)")
        self.assertEqual((cn.label("naver_a"), cn.label("naver_b")), ("가" * limit, "가" * (limit + 1)), "전체 이름은 그대로다")
        self.assertEqual(cn.short_label("no_such_slot"), "no_such_slot", "모르는 열쇠는 그대로")
        self.assertEqual((cn.short_home_label("B"), cn.short_home_label("C")), ("가" * (limit - 1) + "…", ""))

    def test_the_default_names_are_never_cut_so_the_view_models_of_the_defaults_stay_as_they_were(self):
        self.assertEqual({key: cn.short_label(key) for key in cn.ORDER}, DEFAULTS)
        self.assertEqual({key: cn.full_if_cut(key, cn.short_label(key)) for key in cn.ORDER}, dict.fromkeys(cn.ORDER, ""))

    def test_two_names_that_become_the_same_once_cut_are_told_apart_by_a_number_and_stay_within_the_limit(self):
        cn.use(cn.labels({"naver_a": (LONG_A, True), "naver_b": (LONG_B, True)}))
        self.assertNotEqual(cn.label("naver_a"), cn.label("naver_b"))
        short = {key: cn.short_label(key) for key in cn.ORDER}
        self.assertEqual(len({value.casefold() for value in short.values()}), 5, "줄인 뒤에도 다섯 이름이 모두 다르다")
        self.assertTrue(short["naver_b"].endswith(" #2"))
        self.assertTrue(all(len(value) <= cn.DRAWER_LIMIT for value in short.values()), short)

    def test_three_blogs_with_the_same_alias_keep_five_different_cut_names(self):
        cn.use(cn.labels({"naver_a": ("맛집", True), "naver_b": ("맛집", True), "blogger_ko": ("맛집", True)}))
        short = {key: cn.short_label(key) for key in cn.ORDER}
        self.assertEqual(len({value.casefold() for value in short.values()}), 5, short)
        self.assertTrue(all(len(value) <= cn.DRAWER_LIMIT for value in short.values()), short)

    def test_button_text_doubles_every_ampersand_so_qt_shows_it_and_makes_no_shortcut_and_changes_nothing_else(self):
        """검증 S2-3: Qt 는 단추 글의 `&` 를 Alt 단축키 표시로 읽는다 — 별명 `A&B` 는 `AB`(Alt+B)·`&lt;` 는 `lt;` 로 보였다. `&&` 로 쓰면 글자 그대로다(표시 규칙은 이 한 곳)."""
        self.assertEqual(cn.button_text("A&B 블로그"), "A&&B 블로그")
        self.assertEqual(cn.button_text("&lt;"), "&&lt;")
        self.assertEqual(cn.button_text("AT&T&"), "AT&&T&&")
        self.assertEqual(cn.button_text("<b>x</b> 맛집"), "<b>x</b> 맛집", "`&` 밖의 글은 그대로다")
        self.assertEqual(cn.button_text("네이버 블로그 1"), "네이버 블로그 1")
        self.assertEqual(cn.button_text(5), "5")

    def test_two_cut_names_that_differ_only_in_case_are_told_apart_too(self):
        """검증 Q3-4: 줄인 이름의 같은 이름 가르기는 대소문자를 가리지 않는다(`ABC…`·`abc…` 가 열두 자 안에서 같아지면 `#2`)."""
        upper, lower = "ABCDEFGHIJKLMNOP", "abcdefghijklmnop"
        cn.use(cn.labels({"naver_a": (upper, True), "naver_b": (lower, True)}))
        self.assertNotEqual(cn.label("naver_a").casefold(), cn.label("naver_b").casefold(), "전체 이름은 첫 가르기에서 이미 갈렸다")
        short = {key: cn.short_label(key) for key in cn.ORDER}
        self.assertEqual((short["naver_a"], short["naver_b"]), ("ABCDEFGHIJK…", "abcdefgh… #2"), "줄이면 대소문자만 다르다 — 둘째에 `#2` 가 붙는다")
        self.assertEqual(len({value.casefold() for value in short.values()}), 5)

    def test_display_order_puts_the_channels_in_the_card_order_and_keeps_unknown_keys_last(self):
        """검증 Q3-1: 줄 글에 늘어놓는 채널은 엔진(저장) 순서가 아니라 블로그 관리의 카드 순서다 — 표시 전용이다(값·저장 순서는 그대로)."""
        engine = ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b")
        self.assertEqual(cn.display_order(engine), ["naver_a", "naver_b", "blogger_ko", "blogger_en", "github_pages"])
        self.assertEqual(cn.display_order(("zz", "naver_b", "naver_a")), ["naver_a", "naver_b", "zz"])
        items = [types.SimpleNamespace(key=key) for key in engine]
        self.assertEqual([item.key for item in cn.display_order(items, key=lambda item: item.key)], ["naver_a", "naver_b", "blogger_ko", "blogger_en", "github_pages"])
        self.assertEqual(cn.display_order(()), [])

    def test_the_full_name_is_given_only_for_a_cut_name(self):
        cn.use(cn.labels({"naver_a": (LONG_A, True)}))
        self.assertEqual(cn.full_if_cut("naver_a", cn.short_label("naver_a")), LONG_A)
        self.assertEqual(cn.full_if_cut("naver_b", cn.short_label("naver_b")), "")

    def test_the_home_drawer_shows_the_cut_name_and_carries_the_full_name_only_when_the_name_was_cut(self):
        state = home_state()
        state.open_drawer("rA1")
        plain = state.drawer_view()
        self.assertEqual((plain["blog_label"], plain["drafts"]), ("네이버 블로그 1", [{"key": "A", "label": "네이버 블로그 1 초안"}]), "기본 이름은 줄이지 않아 칸이 늘지 않는다(옛 `블로그 A 초안` 도 아니다)")
        self.assertNotIn("blog_tip", plain)
        cn.use(cn.labels({"naver_a": (LONG_A, True), "naver_b": (LONG_B, True)}))
        state.open_drawer("rA1")
        cut = state.drawer_view()
        self.assertEqual(cut["blog_label"], cn.short_label("naver_a"))
        self.assertEqual(cut["blog_tip"], LONG_A)
        self.assertEqual(cut["drafts"], [{"key": "A", "label": f"{cn.short_label('naver_a')} 초안", "tip": f"{LONG_A} 초안"}])
        self.assertLessEqual(len(cut["drafts"][0]["label"]), cn.DRAWER_LIMIT + len(" 초안"))

    def test_the_two_draft_buttons_of_the_home_drawer_stay_different_even_when_both_names_are_cut_to_the_same_text(self):
        state = app_state.AppState(services.FakeHomeProvider())
        state.apply_home(services.HomeData(topics=(services.Topic(id="t1", title="주제", blogs=("A", "B")),)))
        cn.use(cn.labels({"naver_a": (LONG_A, True), "naver_b": (LONG_B, True)}))
        state.open_drawer("t1")
        buttons = state.drawer_view()["drafts"]
        self.assertEqual([item["key"] for item in buttons], ["A", "B"])
        self.assertNotEqual(buttons[0]["label"], buttons[1]["label"])
        self.assertEqual([item["tip"] for item in buttons], [f"{LONG_A} 초안", f"{LONG_B} 초안"], "전체 이름은 그대로 전해진다")

    def test_the_seed_drawer_chips_keep_the_keys_as_values_and_show_the_names_with_the_full_name_as_a_tip_only_when_cut(self):
        """검증 Q2-5: 저장되는 값은 열쇠(`naver_a`)이고 화면 이름이 값으로 새지 않는다 — PySide6 가 없는 CI 에서도 지킨다. 칩 글은 화면 이름(옛 고정 이름이 아니다)."""
        from chanceblog_desktop.topics import seeds as sd
        from chanceblog_desktop.ui.core import seed_form as sf, seeds, seeds_view
        controller = seeds_view.SeedsController(seeds.FakeSeedsProvider("normal"), jobs.JobRunner())
        controller.apply_loaded(controller.provider.load_seeds(SAFE, NEVER))
        controller.open_new()
        controller.edit("scope", "common")                                                        # 공통을 고르면 허용 채널 칸이 나타난다
        plain = controller.drawer_view()
        self.assertEqual(seed_options(plain, "allowed_channels"), [{"value": code, "label": DEFAULTS[code]} for code in sf.DISPLAY_CHANNELS], "값은 열쇠, 글은 기본 이름 — 줄이지 않으면 `tip` 칸이 없다(순서는 블로그 관리의 카드 순서)")
        self.assertEqual(seed_options(plain, "scope"), [{"value": scope, "label": "공통" if scope == sd.SCOPE_COMMON else DEFAULTS[scope]} for scope in sf.DISPLAY_SCOPES])
        cn.use(cn.labels({"naver_a": (LONG_A, True), "naver_b": (LONG_B, True)}))
        cut = controller.drawer_view()
        channels = {item["value"]: item for item in seed_options(cut, "allowed_channels")}
        self.assertEqual(set(channels), set(sf.CHANNEL_ORDER), "값은 여전히 열쇠다")
        self.assertEqual(list(channels), ["naver_a", "naver_b", "blogger_ko", "blogger_en", "github_pages"], "칩 순서는 블로그 관리의 카드 순서다(검증 Q2-4)")
        self.assertEqual(channels["naver_a"]["label"], cn.short_label("naver_a"))
        self.assertEqual(channels["naver_a"]["tip"], LONG_A)
        self.assertNotEqual(channels["naver_a"]["label"], channels["naver_b"]["label"])
        self.assertNotIn("tip", channels["github_pages"], "줄이지 않은 이름에는 `tip` 이 없다")
        scopes = {item["value"]: item for item in seed_options(cut, "scope")}
        self.assertEqual((scopes[sd.SCOPE_COMMON]["label"], scopes["naver_a"]["tip"]), ("공통", LONG_A))
        self.assertTrue(all(len(item["label"]) <= cn.DRAWER_LIMIT for item in (*channels.values(), *scopes.values())))


if __name__ == "__main__":
    unittest.main()
