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


if __name__ == "__main__":
    unittest.main()
