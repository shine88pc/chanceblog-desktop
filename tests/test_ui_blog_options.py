"""블로그 관리 화면의 **보기 목록과 제안**(blogsel — D-493 부터)의 순수 시험(PySide6 없이 돈다 — CI 와 같은 조건): 한 줄 칸의 보기 셋·낱말 칸의 제안 칩 넷·별명과 소개글 제안 문장·낱말 켜고 끄기·'카드로 보이는 슬롯' 규칙.
직접 입력하던 칸을 **프로그램이 제안하고 사용자가 고르게** 바꾸는 규칙이라, 여기서는 저장하는 값이 **기존과 같은 글**(서비스가 읽는 칸·한도·검사 그대로)인지를 중심으로 못박는다.

지키는 것:
  1) 보기 목록(`ui/core/blog_options.py`)은 운영자 요청의 값 그대로다 — 채널 역할 다섯·대상 독자 여섯·문체 넷. 낱말 제안은 앱이 이미 가진 목록(주제 묶음 이름·협찬 분야 이름·글 유형)에서만 온다.
  2) **보기를 고른 값은 서비스(`ChannelProfile`)가 그대로 받는다** — 모든 보기·모든 제안 낱말·모든 제안 문장이 서비스 검사를 통과한다(한도·위험한 표기·낱말 모양). 한도를 넘는 조합은 칩이 만들지 못한다.
  3) 제안 문장(별명·소개글)은 고른 값으로만 만들고, 재료가 없으면 비며, 위험한 표기는 빼고, 소개글 상한을 넘기지 않는다. 슬롯 이름(`네이버 A`)은 어느 제안에도 없다.
  4) 낱말 켜고 끄기는 나머지 낱말과 순서를 그대로 둔다(대소문자 구분 없이 같은 낱말은 하나로 본다). 보기 밖의 저장된 값은 '직접 입력' 으로 그대로 보인다.
  5) 카드로 보이는 슬롯(`is_listed`)과 종류별 빈 슬롯(`free_slot`)은 서비스의 '등록됨'·'비어 있음' 판정과 같은 규칙 위에 있다 — 내용이 있는 슬롯은 숨지도 덮어써지지도 않는다.
실제 블로그 이름·아이디·주소는 이 시험에 없다(예시 값뿐).
"""
import dataclasses
import itertools
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chanceblog_desktop.content.profiles import POST_TYPES, clean_line, find_markup  # noqa: E402
from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import wording  # noqa: E402
from chanceblog_desktop.ui.core import blog_form as bf  # noqa: E402
from chanceblog_desktop.ui.core import blog_options as bo  # noqa: E402
from chanceblog_desktop.ui.core import text  # noqa: E402

T = text.T
TILDE = chr(0x7E)                                   # 물결 글자는 시험 글에도 직접 쓰지 않는다(문서·주석에 물결표를 두지 않는 규칙)
PROFILES = {profile.key: profile for profile in ch.default_profiles()}
SEPARATORS = (",", "，", "、", ";", "\n")
SLOT_NAME = re.compile(r"네이버 [AB]\b|Blogger (?:한글|영문)|naver_[ab]|blogger_(?:ko|en)|github_pages")


def service_accepts(key, **fields):
    try:
        bp.apply_fields(PROFILES[key], fields)
    except bp.ProfileProblems:
        return False
    return True


# ---- 1) 보기 목록 ------------------------------------------------------------------------------------------------------------------------
class ListTest(unittest.TestCase):
    def test_the_three_line_choices_are_exactly_the_requested_values(self):
        self.assertEqual(bo.ROLE_CHOICES, ("정보 공유", "후기 기록", "제품 비교", "브랜드 소개", "일상 기록"))
        self.assertEqual(bo.AUDIENCE_CHOICES, ("20–30대 직장인", "대학생", "주부", "여행자", "개발 입문자", "자영업자"))
        self.assertEqual(bo.TONE_CHOICES, ("친근한 말투", "정중한 설명체", "간결한 정보체", "생생한 후기체"))
        self.assertEqual(dict(bo.LINE_CHOICES), {"channel_role": bo.ROLE_CHOICES, "audience": bo.AUDIENCE_CHOICES, "tone": bo.TONE_CHOICES})
        self.assertNotIn(TILDE, "".join(bo.AUDIENCE_CHOICES), "물결표 대신 가운뎃줄(–)을 쓴다")

    def test_the_word_suggestions_come_only_from_the_lists_the_app_already_has(self):
        clusters = tuple(wording.CLUSTER_KO.values())
        tags = tuple(wording.TAG_KO.values())
        self.assertEqual(bo.TOPIC_WORDS, clusters, "주제 묶음 이름 그대로(같은 이름이 둘 있지 않으므로 줄이지 않는다)")
        self.assertEqual(len(clusters), 26)
        self.assertEqual(bo.SPONSOR_WORDS, tags)
        self.assertEqual(bo.WORD_SUGGESTIONS["main_topics"], clusters)
        self.assertEqual(bo.WORD_SUGGESTIONS["categories"], bo._unique(tags, POST_TYPES))
        for name in ("priority_keywords", "exclude_keywords"):
            self.assertEqual(bo.WORD_SUGGESTIONS[name], bo._unique(clusters, tags), name)
        self.assertTrue(set(POST_TYPES) <= set(bo.WORD_SUGGESTIONS["categories"]))
        self.assertTrue(set(tags) <= set(bo.WORD_SUGGESTIONS["priority_keywords"]))
        self.assertEqual(set(bo.WORD_SUGGESTIONS), {"main_topics", "categories", "priority_keywords", "exclude_keywords"})
        for name, words in bo.WORD_SUGGESTIONS.items():
            self.assertEqual(len({word.casefold() for word in words}), len(words), f"{name}: 같은 낱말이 두 번 없다")

    def test_the_field_table_gives_every_field_the_right_kind_of_help(self):
        by_name = {spec.name: spec for spec in bf.FIELDS}
        self.assertEqual({name: spec.choices for name, spec in by_name.items() if spec.choices}, dict(bo.LINE_CHOICES))
        self.assertEqual({name: spec.suggest for name, spec in by_name.items() if spec.suggest}, dict(bo.WORD_SUGGESTIONS))
        self.assertEqual({name: spec.assist for name, spec in by_name.items() if spec.assist}, {"alias": "alias", "intro": "intro"})
        for name, spec in by_name.items():
            if spec.choices:
                self.assertEqual(spec.kind, "line", name)
            if spec.suggest:
                self.assertEqual(spec.kind, "words", name)
        for name in ("display_name", "blog_ref", "language", "generation_enabled", "monetization_focus", "preferred_post_types", "color_preset", "profile_image", "cover_image"):
            self.assertEqual((by_name[name].choices, by_name[name].suggest, by_name[name].assist), ((), (), ""), f"{name}: 이름·주소·이미지는 사용자만 안다 — 보기를 두지 않는다")
        self.assertEqual({spec.kind for spec in bf.FIELDS if spec.name.endswith("_image")}, {"path"})

    def test_every_choice_and_suggestion_fits_its_field_limits_and_is_a_clean_word(self):
        for name, choices in bo.LINE_CHOICES.items():
            spec = bf.SPEC[name]
            for choice in choices:
                self.assertLessEqual(len(choice), spec.limit, f"{name}: {choice}")
                self.assertEqual(clean_line(choice), choice, "한 줄로 다듬어도 그대로다")
                self.assertIsNone(find_markup(choice))
                self.assertEqual(bf.problem_of(spec, bf.normalize(spec, choice)), "", f"{name}: {choice}")
        for name, words in bo.WORD_SUGGESTIONS.items():
            spec = bf.SPEC[name]
            for word in words:
                self.assertLessEqual(len(word), spec.limit, f"{name}: {word}")
                self.assertEqual(clean_line(word), word)
                self.assertIsNone(find_markup(word))
                self.assertFalse(any(separator in word for separator in SEPARATORS), f"{name}: {word} 에 낱말을 나누는 글자가 있다")
                self.assertEqual(bf.split_words(word), (word,), "낱말 하나로 읽힌다")

    def test_the_service_accepts_every_choice_and_every_suggested_word(self):
        """저장하는 값은 기존과 같은 글이다 — 보기·제안 낱말 하나하나를 서비스의 `ChannelProfile` 이 그대로 받는다(칸 검사)."""
        for key in bp.SLOTS:
            for name, choices in bo.LINE_CHOICES.items():
                for choice in choices:
                    self.assertTrue(service_accepts(key, **{name: choice}), f"{key} {name} {choice}")
            for name, words in bo.WORD_SUGGESTIONS.items():
                for word in words:
                    self.assertTrue(service_accepts(key, **{name: (word,)}), f"{key} {name} {word}")

    def test_picking_more_words_than_the_limit_is_what_the_service_refuses_and_what_the_chips_prevent(self):
        for name in ("main_topics", "priority_keywords", "categories"):
            spec = bf.SPEC[name]
            everything = bo.WORD_SUGGESTIONS[name]
            self.assertTrue(service_accepts("naver_a", **{name: everything[:spec.count]}), name)
            if len(everything) > spec.count:
                self.assertFalse(service_accepts("naver_a", **{name: everything[:spec.count + 1]}), f"{name}: 한도 하나 넘으면 서비스가 거절한다 — 그래서 칩이 한도에서 멈춘다")
        self.assertGreater(len(bo.TOPIC_WORDS), ch.MAX_MAIN_TOPICS)
        self.assertGreater(len(bo.KEYWORD_WORDS), ch.MAX_KEYWORDS)


# ---- 2) 제안 문장 -------------------------------------------------------------------------------------------------------------------------
class SuggestionTest(unittest.TestCase):
    def test_the_intro_follows_the_fixed_pattern_for_every_combination_of_materials(self):
        full = bo.suggest_intro("정보 공유", "대학생", "친근한 말투", ("소형가전", "PC 주변기기"))
        self.assertEqual(full, "소형가전·PC 주변기기 이야기를 담아요. 대학생에게 도움이 되는 정보 공유 블로그예요. ‘친근한 말투’ 느낌으로 읽기 편하게 써요.")
        self.assertEqual(bo.suggest_intro("정보 공유", "", "", ()), "정보 공유 블로그예요.")
        self.assertEqual(bo.suggest_intro("", "주부", "", ()), "주부에게 도움이 되는 글을 써요.")
        self.assertEqual(bo.suggest_intro("", "", "생생한 후기체", ()), "‘생생한 후기체’ 느낌으로 읽기 편하게 써요.")
        self.assertEqual(bo.suggest_intro("", "", "", ("소형가전",)), "소형가전 이야기를 담아요.")
        self.assertEqual(bo.suggest_intro("제품 비교", "여행자", "", ()), "여행자에게 도움이 되는 제품 비교 블로그예요.")
        self.assertEqual(bo.suggest_intro("", "", "", ()), "", "재료가 없으면 제안하지 않는다")
        self.assertEqual(bo.suggest_intro("", "", "", None), "")
        self.assertEqual(bo.suggest_intro(None, 5, ["x"], ()), "", "글이 아닌 재료는 없는 것으로 본다")

    def test_only_the_first_three_topics_are_used_and_the_order_is_kept(self):
        words = ("소형가전", "PC 주변기기", "숙박", "지역", "배포")
        self.assertEqual(bo.suggest_intro("", "", "", words), "소형가전·PC 주변기기·숙박 이야기를 담아요.")
        self.assertEqual(bo.TOPIC_PICK, 3)

    def test_no_josa_is_attached_to_a_user_word_so_every_ending_reads_right(self):
        """조사(을·를·으로·이에요)가 낱말의 받침에 따라 달라지는 자리에는 낱말을 붙이지 않는다 — 받침이 있든 없든, 영문·숫자로 끝나도 같은 틀이다."""
        for audience in ("대학생", "주부", "개발 입문자", "자영업자", "여행자", "Python 입문자", "20–30대 직장인", "30대"):
            text_ = bo.suggest_intro("", audience, "", ())
            self.assertTrue(text_.startswith(audience + "에게 도움이 되는 글을 써요."), audience)
        for tone in ("친근한 말투", "정중한 설명체", "간결한 정보체", "생생한 후기체", "Simple"):
            self.assertIn(f"‘{tone}’ 느낌으로", bo.suggest_intro("", "", tone, ()))
        self.assertTrue(bo.suggest_intro("제품 비교", "", "", ()).endswith("제품 비교 블로그예요."))

    def test_dangerous_pieces_are_left_out_and_the_rest_is_kept(self):
        self.assertEqual(bo.suggest_intro("<script>x</script>", "대학생", "", ()), "대학생에게 도움이 되는 글을 써요.")
        self.assertEqual(bo.suggest_intro("정보 공유", "<b>굵게</b>", "", ()), "정보 공유 블로그예요.")
        self.assertEqual(bo.suggest_intro("", "", "{{ 템플릿 }}", ()), "")
        self.assertEqual(bo.suggest_intro("", "", "", ("<img src=x onerror=1>", "소형가전")), "소형가전 이야기를 담아요.")

    def test_the_intro_never_passes_the_limit_and_the_service_always_accepts_it(self):
        longest = "가" * ch.MAX_AUDIENCE
        cases = [("정보 공유", "대학생", "친근한 말투", ("소형가전", "PC 주변기기", "숙박")), ("", longest, longest, ("가" * 30,) * 3), ("나" * ch.MAX_ROLE, longest, "다" * ch.MAX_TONE, ("라" * 30,) * 3),
                 ("", "", longest, ())]
        for role, audience, tone, topics in cases:
            result = bo.suggest_intro(role, audience, tone, topics)
            self.assertLessEqual(len(result), ch.MAX_INTRO)
            self.assertEqual(clean_line(result), result)
            self.assertTrue(service_accepts("naver_a", intro=result), result)
        self.assertEqual(bo.suggest_intro("", "", "라" * 400, ()), "", "한 문장도 못 담으면 제안하지 않는다")
        tight = bo.suggest_intro("나" * ch.MAX_ROLE, "가" * ch.MAX_AUDIENCE, "다" * ch.MAX_TONE, ("라" * 30,) * 3)
        self.assertTrue(tight.startswith("라" * 30), "상한에 걸리면 뒤의 문장부터 뺀다")

    def test_every_combination_of_the_choices_gives_a_suggestion_the_service_accepts(self):
        for role, audience, tone in itertools.product(("",) + bo.ROLE_CHOICES, ("",) + bo.AUDIENCE_CHOICES, ("",) + bo.TONE_CHOICES):
            result = bo.suggest_intro(role, audience, tone, bo.TOPIC_WORDS[:3])
            self.assertTrue(result)
            self.assertTrue(service_accepts("naver_b", intro=result), (role, audience, tone))
            self.assertIsNone(find_markup(result))
            self.assertNotRegex(result, SLOT_NAME)

    def test_the_form_builds_the_intro_from_the_current_input_and_falls_back_to_categories(self):
        values = {"channel_role": "  정보   공유 ", "audience": "대학생", "tone": "", "main_topics": "소형가전, PC 주변기기", "categories": "정보형"}
        self.assertEqual(bf.suggest_intro(values), "소형가전·PC 주변기기 이야기를 담아요. 대학생에게 도움이 되는 정보 공유 블로그예요.")
        self.assertEqual(bf.suggest_intro({**values, "main_topics": ""}), "정보형 이야기를 담아요. 대학생에게 도움이 되는 정보 공유 블로그예요.", "주요 주제가 없으면 카테고리로 만든다")
        self.assertEqual(bf.suggest_intro({}), "")
        self.assertEqual(bf.suggest_intro({"main_topics": None, "channel_role": None}), "")

    def test_the_alias_is_the_kind_name_and_the_number_inside_the_kind_and_never_a_slot_name(self):
        expected = {"naver_a": "네이버 블로그 1", "naver_b": "네이버 블로그 2", "blogger_ko": "Blogger 1", "blogger_en": "Blogger 2", "github_pages": "GitHub Pages 1"}
        for key in bp.SLOTS:
            alias = bf.suggest_alias(key)
            self.assertEqual(alias, expected[key])
            self.assertLessEqual(len(alias), ch.MAX_ALIAS)
            self.assertNotRegex(alias, SLOT_NAME)
            self.assertTrue(service_accepts(key, alias=alias), key)
            self.assertEqual(bf.card_title(key, ""), alias)
            self.assertEqual(bf.card_title(key, "   "), alias, "공백뿐인 별명은 없는 것이다")
        self.assertEqual(bf.card_title("naver_a", "내  별명"), "내 별명", "별명이 있으면 별명(한 줄로 다듬어)")
        secret = "AK" + "IA" + "ABCDEFGHIJKLMNOP"                                 # 키 모양의 가짜 값 — 조각으로 나눠 적는다
        self.assertNotIn(secret, bf.card_title("naver_a", "별명 " + secret), "별명에 키 모양이 있어도 카드에는 가려서 보인다")


# ---- 3) 낱말·보기 다루기 ---------------------------------------------------------------------------------------------------------------------
class WordsTest(unittest.TestCase):
    def test_toggling_a_word_keeps_the_other_words_and_their_order(self):
        self.assertEqual(bf.toggle_word("", "소형가전"), "소형가전")
        self.assertEqual(bf.toggle_word("가, 나", "다"), "가, 나, 다", "맨 뒤에 붙는다")
        self.assertEqual(bf.toggle_word("가, 나, 다", "나"), "가, 다", "있으면 뺀다 — 나머지 순서는 그대로")
        self.assertEqual(bf.toggle_word("가,나;다\n라", "다"), "가, 나, 라", "쉼표·세미콜론·줄바꿈으로 쓴 글도 낱말로 읽는다")
        self.assertEqual(bf.split_words(bf.toggle_word(bf.toggle_word("가, 나", "다"), "다")), ("가", "나"), "켰다 끄면 같은 낱말 목록으로 돌아온다")

    def test_the_same_word_in_another_case_counts_as_the_same_word(self):
        self.assertEqual(bf.toggle_word("API 한도", "api 한도"), "", "대소문자가 달라도 같은 낱말 — 서비스의 중복 규칙(casefold)과 같다")
        self.assertEqual(bf.picked_words("API 한도, 소형가전"), frozenset({"api 한도", "소형가전"}))
        self.assertEqual(bf.picked_words(None), frozenset())
        self.assertEqual(bf.picked_words("가, 가"), frozenset({"가"}))

    def test_a_hand_written_duplicate_is_removed_whole_when_the_word_is_turned_off(self):
        self.assertEqual(bf.toggle_word("가, 나, 가", "가"), "나")

    def test_line_choice_state_shows_a_stored_value_outside_the_choices_as_direct_input(self):
        spec = bf.SPEC["tone"]
        self.assertEqual(bf.line_choice_state(spec, ""), (False, ""))
        self.assertEqual(bf.line_choice_state(spec, "친근한 말투"), (False, "친근한 말투"))
        self.assertEqual(bf.line_choice_state(spec, "  친근한   말투 "), (False, "친근한 말투"), "공백만 다른 것은 같은 보기다")
        self.assertEqual(bf.line_choice_state(spec, "손으로 쓴 문체"), (True, ""), "보기 밖의 저장된 값은 '직접 입력' 으로 보이고 지워지지 않는다")
        self.assertEqual(bf.line_choice_state(spec, "친근한 말투", custom_opened=True), (True, ""), "'직접 입력' 을 눌렀으면 같은 글이어도 직접 입력이다")
        self.assertEqual(bf.line_choice_state(spec, None), (False, ""))


# ---- 4) 카드로 보이는 슬롯 · 종류로 빈 슬롯 찾기 ---------------------------------------------------------------------------------------------
class ListingRulesTest(unittest.TestCase):
    def slots(self, **changes):
        out = {key: bf.default_values(key) for key in bf.SLOTS}
        for key, change in changes.items():
            out[key] = {**out[key], **change}
        return out

    def test_the_kinds_and_their_slots_are_the_services_and_cover_each_slot_once(self):
        self.assertEqual(bf.KINDS, ("naver", "blogger", "github"))
        self.assertEqual(bf.KIND_SLOTS, {"naver": ("naver_a", "naver_b"), "blogger": ("blogger_ko", "blogger_en"), "github": ("github_pages",)})
        self.assertEqual(tuple(bf.KIND_SLOTS.values()), bp.SLOT_KINDS, "복제와 같은 종류 묶음")
        self.assertEqual(sorted(slot for slots in bf.KIND_SLOTS.values() for slot in slots), sorted(bp.SLOTS))
        self.assertEqual([len(bf.KIND_SLOTS[kind]) for kind in bf.KINDS], [2, 2, 1], "네이버 2·Blogger 2·GitHub Pages 1")
        for kind in bf.KINDS:
            self.assertTrue(T["blogs_kind_" + kind] and T["blogs_kinddesc_" + kind])

    def test_registered_matches_the_service_and_a_slot_with_content_is_listed_even_without_an_address(self):
        """등록됨은 서비스의 판정(블로그 ID 또는 주소가 있다)과 같고, 카드로 보이는 슬롯은 등록됐거나 내용이 있거나 새로 연결하는 중인 슬롯이다 — 주소 없이 내용만 있는 슬롯(손으로 고친 파일)이 숨어 덮어써지지 않는다."""
        arrangements = ({}, {"blog_ref": "example-blog-a"}, {"display_name": "다른 이름"}, {"alias": "예시"}, {"priority_keywords": "예시"}, {"generation_enabled": False}, {"alias": "   "}, {"blog_ref": ""},
                        {"display_name": "다른 이름", "blog_ref": "example-blog-a"}, {"preferred_post_types": ("정보형",)}, {"color_preset": "cool_technology"})
        for key in bp.SLOTS:
            for change in arrangements:
                raw = {**bf.default_values(key), **change}
                profile = dataclasses.replace(PROFILES[key], **{name: value for name, value in bf.typed_values(key, raw).items() if name in bp.form_fields(key)})
                with self.subTest(key=key, change=change):
                    self.assertEqual(bf.is_registered(raw), bp.is_registered(profile))
                    self.assertEqual(bf.is_listed(key, raw), bp.is_registered(profile) or not bp.is_empty(profile))
                    self.assertTrue(bf.is_listed(key, raw, adding=True), "새로 연결하는 중이면 늘 카드로 보인다")

    def test_a_free_slot_is_the_first_unlisted_slot_of_the_kind_and_a_full_kind_has_none(self):
        empty = self.slots()
        self.assertEqual([bf.free_slot(kind, empty) for kind in bf.KINDS], ["naver_a", "blogger_ko", "github_pages"])
        self.assertEqual([bf.free_count(kind, empty) for kind in bf.KINDS], [2, 2, 1])
        one = self.slots(naver_a={"blog_ref": "example-blog-a"})
        self.assertEqual((bf.free_slot("naver", one), bf.free_count("naver", one)), ("naver_b", 1))
        both = self.slots(naver_a={"blog_ref": "example-blog-a"}, naver_b={"blog_ref": "example-blog-b"})
        self.assertEqual((bf.free_slot("naver", both), bf.free_count("naver", both)), (None, 0))
        first_gone = self.slots(naver_b={"blog_ref": "example-blog-b"})
        self.assertEqual(bf.free_slot("naver", first_gone), "naver_a", "지운 자리는 다시 쓰인다")
        github = self.slots(github_pages={"blog_ref": "example-blog-g"})
        self.assertEqual((bf.free_slot("github", github), bf.free_count("github", github)), (None, 0))

    def test_a_slot_with_content_is_never_a_free_slot_and_an_opened_one_is_not_free_either(self):
        content = self.slots(naver_a={"alias": "손으로 쓴 별명"})
        self.assertEqual(bf.free_slot("naver", content), "naver_b", "내용이 있는 슬롯은 덮어쓰지 않는다")
        opened = self.slots()
        self.assertEqual(bf.free_slot("naver", opened, adding={"naver_a"}), "naver_b", "이미 새 블로그로 열어 둔 슬롯은 건너뛴다")
        self.assertIsNone(bf.free_slot("naver", opened, adding={"naver_a", "naver_b"}))
        self.assertEqual(bf.free_count("naver", opened, adding={"naver_a"}), 1)

    def test_the_form_base_of_an_empty_slot_has_a_blank_name_and_a_slot_with_content_keeps_its_own(self):
        for key in bp.SLOTS:
            stored = bf.default_values(key)
            self.assertTrue(stored["display_name"], "기본 프로필의 이름은 슬롯 이름이다")
            self.assertEqual(bf.form_base(key, stored)["display_name"], "", key)
            self.assertEqual({name: value for name, value in bf.form_base(key, stored).items() if name != "display_name"}, {name: value for name, value in stored.items() if name != "display_name"})
            used = {**stored, "alias": "예시"}
            self.assertEqual(bf.form_base(key, used), used, "내용이 있으면 저장된 값 그대로")
            registered = {**stored, "blog_ref": "example-blog-a", "display_name": "예시 블로그 가"}
            self.assertEqual(bf.form_base(key, registered), registered)

    def test_clone_does_not_pick_a_slot_that_is_being_opened_as_a_new_blog(self):
        slots = self.slots(naver_a={"blog_ref": "example-blog-a"})
        self.assertEqual(bf.clone_state(slots, "naver_a"), (True, "", "naver_b"))
        self.assertEqual(bf.clone_state(slots, "naver_a", reserved={"naver_b"}), (False, T["blogs_clone_no_target"], None), "입력 중인 새 블로그를 덮어쓰지 않는다")
        self.assertEqual(bf.clone_state(slots, "naver_a", reserved=()), (True, "", "naver_b"))


if __name__ == "__main__":
    unittest.main()
