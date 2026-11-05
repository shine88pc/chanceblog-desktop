"""브랜드 단독 판정·유형 확인·하위 후보(`topics/brand.py`) 시험 — P2b 보완 B1~B9(D-55).

지키는 것:
  B1) **표는 초기값 — 전략 원문 확인 전이다.** 브랜드 64개(필수 8개 포함)·제품 유형 9개·하위 후보 틀 22개·유형별 틀 순서·유형 확인 표를 값으로 못박고, 틀의 불변식(관점이 일반 확장과 겹치지 않음 …)을 지킨다.
  B2) 판정 — '브랜드 이름만 있다' 의 정답표 87개(한 브랜드 38·나열 7·음성 42)와 조건을 하나씩 바꾼 변형. 영문 채널은 '해당 없음'.
  B3) 유형 확인(단일 → 씨앗의 분류·협찬 태그 → 채널의 주제 묶음 → 주력, 모호하면 보류). B4) 하위 후보 — 최대 3개·틀 순서·허용 방향만·작성 가능성·실패하면 보류.
  B5) 브랜드는 안전·협찬 신호가 아니다(표시도 알림도 0)·`brand.py` 의 가져오기는 허용 목록뿐. B6) 구체화 후보의 근거 점수에 감점이 없다. B7) 요청서 §5 의 예(Gemini·NVIDIA)가 글자까지 같다.
  B8) 결정성(집합을 순회해 출력 순서를 정하는 곳이 없다). B9) 협찬과 브랜드 — 협찬 태그가 없으면 협찬 경로 후보가 없고 있으면 표시 없이 '협업 가능 유형' 줄이 붙는다.
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import ast
import dataclasses
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.content.candidates import forbidden_claim, keyword_key  # noqa: E402
from chanceblog_desktop.topics import brand as br  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import expand as ex  # noqa: E402
from chanceblog_desktop.topics import feasibility as fe  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402

A, B = ts.PROFILES["naver_a"], ts.PROFILES["naver_b"]
ALL_ON = tuple(dataclasses.replace(profile, generation_enabled=True) for profile in ch.default_profiles())
BRAND_NAMES = (
    "Gemini", "Claude", "ChatGPT", "Copilot", "Perplexity", "Midjourney", "DeepSeek", "Grok", "OpenAI", "Anthropic", "NVIDIA", "AMD", "Intel", "ASUS", "MSI", "GIGABYTE", "Corsair", "Seagate",
    "Western Digital", "Kingston", "SK hynix", "ASRock", "Cooler Master", "Logitech", "Razer", "Keychron", "BenQ", "Dell", "Lenovo", "Acer", "Dyson", "쿠쿠", "쿠첸", "위닉스", "코웨이", "발뮤다", "필립스",
    "일렉트로룩스", "로보락", "삼성", "LG", "Apple", "샤오미", "Google", "네이버", "카카오", "쿠팡", "YouTube", "Instagram", "Telegram", "Discord", "Microsoft", "Notion", "Obsidian", "Slack", "Figma",
    "GitHub", "Adobe", "Canva", "Docker", "VS Code", "야놀자", "Airbnb", "Agoda")
SINGLE = ("Gemini", "gemini", "GEMINI", "  Gemini  ", "Gemini.", "제미나이", "제미나이를", "제미니", "Google Gemini", "Claude", "클로드", "클로드는", "ChatGPT", "Chat GPT", "챗GPT", "챗 지피티", "NVIDIA", "nvidia",
          "엔비디아", "삼성", "삼성전자", "삼성 전자", "삼성이", "LG", "엘지", "LG전자", "네이버", "Naver", "네이버가", "Microsoft", "마이크로소프트", "마이크로 소프트", "Apple", "애플", "VS Code", "VSCode",
          "Cooler Master", "SK하이닉스")
LISTS = ("삼성 LG", "삼성, LG", "삼성/LG", "삼성과 LG", "삼성LG", "Gemini Claude", "NVIDIA AMD Intel")
NEGATIVE = ("삼성 노트북 비교", "삼성 노트북", "Gemini API", "Gemini 2.5", "Gemini vs Claude", "Gemini 와 Claude 비교", "NVIDIA RTX 4090", "삼성동", "삼성역 맛집", "삼성전자서비스센터", "네이버 블로그", "네이버페이",
            "네이버 지도", "LG 그램", "LGBTQ", "Claudette", "ChatGPT 사용법", "클로드 코드", "Apple pie", "애플리케이션", "Microsoft Excel 단축키", "마이크로소프트 오피스", "제미나이 사용법", "구글링", "슬랙 채널",
            "Slack channel", "Booking", "Meta", "모델", "Model", "추천", "비교", "가이드", "Pro", "프로", "best", "AI", "GPU", "노트북", "로봇청소기", "", "!!!")


def seed(keyword, *, major="가", minor="없는 분류", **changes):
    values = dict(seed_id="s1", major=major, minor=minor, keyword=keyword, seed_type="general", scope="common", priority=False, excluded_keywords=(), sponsor_tag=None, state="active",
                  registered_on="2026-05-01", last_selected_on=None, active_since=None)
    values.update(changes)
    return sd.Seed(**values)


def names(hits):
    return [hit.display for hit in hits] if hits else None


def eul(text):
    last = text[-1]
    return "을" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 else "를"


class TablesTest(unittest.TestCase):                                                                           # B1
    def test_the_module_says_the_tables_are_initial_values(self):
        doc = Path(br.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
        self.assertIn("초기값 — 전략 원문 확인 전", doc)

    def test_there_are_sixty_four_brands_in_this_order_with_the_eight_required_ones(self):
        self.assertEqual(tuple(hit.display for hit in br.BRANDS), BRAND_NAMES)
        self.assertEqual(len(br.BRANDS), 64)
        for required in ("Gemini", "Claude", "NVIDIA", "삼성", "LG", "네이버", "Microsoft", "ChatGPT"):
            self.assertIn(required, BRAND_NAMES)

    def test_the_types_the_counts_per_type_and_the_ambiguous_brands_are_exactly_these(self):
        self.assertEqual(br.BRAND_TYPES, ("ai_service", "gpu", "pc_parts", "pc_peripheral", "appliance", "smartphone", "platform", "software", "travel"))
        self.assertEqual(dict(br.TYPE_KO), {"ai_service": "AI 서비스", "gpu": "그래픽카드(GPU)", "pc_parts": "PC 부품", "pc_peripheral": "PC 주변기기", "appliance": "가전", "smartphone": "스마트폰",
                                            "platform": "플랫폼·서비스", "software": "소프트웨어·업무 도구", "travel": "숙박·여행"})
        mains = [hit.types[0] for hit in br.BRANDS]
        self.assertEqual([mains.count(kind) for kind in br.BRAND_TYPES], [10, 2, 11, 7, 11, 2, 8, 10, 3])
        self.assertEqual(sorted(hit.display for hit in br.BRANDS if hit.ambiguous), ["Google", "LG", "삼성", "샤오미"])
        for hit in br.BRANDS:
            self.assertTrue(set(hit.types) <= set(br.BRAND_TYPES), hit.display)
            self.assertEqual(len(set(hit.types)), len(hit.types))
        self.assertEqual({hit.display for hit in br.BRANDS if "api" in hit.traits}, {"Gemini", "Claude", "ChatGPT", "Perplexity", "DeepSeek", "Grok", "OpenAI", "Anthropic"})

    def test_an_alias_key_belongs_to_one_brand_only_and_a_hangul_reading_is_all_hangul(self):
        owners = {}
        for key, number in br.ALIASES:
            self.assertGreaterEqual(len(key), 2, key)
            owners.setdefault(key, set()).add(number)
        self.assertEqual([key for key, brands in owners.items() if len(brands) > 1], [])
        for hit in br.BRANDS:
            self.assertTrue(all("가" <= char <= "힣" for char in hit.reading), hit.display)
        alias_keys = set(owners)
        for hit in br.BRANDS:
            self.assertIn(keyword_key(hit.display), alias_keys, "표시는 자동으로 별칭이다")
        self.assertNotIn("레이저", alias_keys, "일반 낱말이라 읽기를 별칭으로 쓰지 않는다")
        self.assertNotIn("델", alias_keys)

    def test_the_words_that_are_deliberately_not_aliases_never_make_a_brand(self):
        self.assertEqual(len(br.NOT_ALIASES), 17)
        for word in br.NOT_ALIASES:
            with self.subTest(word=word):
                self.assertIsNone(br.find_brands(word))
                self.assertNotIn(keyword_key(word), {key for key, _number in br.ALIASES})

    def test_there_are_twenty_two_templates_and_each_type_lists_its_templates_in_this_order(self):
        self.assertEqual(len(br.SUBTOPICS), 22)
        self.assertEqual(dict(br.TYPE_SUBTOPICS), {
            "ai_service": ("plan_compare", "api_usage", "automation_security", "usage_limits"), "gpu": ("gpu_vram", "official_specs", "gpu_generation", "warranty"),
            "pc_parts": ("parts_compat", "official_specs", "warranty", "purpose_criteria"), "pc_peripheral": ("purpose_criteria", "connection_compat", "care_check", "running_cost"),
            "appliance": ("buying_criteria", "care_check", "running_cost", "warranty"), "smartphone": ("purpose_criteria", "phone_security", "phone_storage"),
            "platform": ("account_security", "policy_change", "usage_limits"), "software": ("plan_compare", "automation_security", "workflow_settings"),
            "travel": ("cancel_refund", "price_compare", "booking_organize")})
        used = {name for names_ in br.TYPE_SUBTOPICS.values() for name in names_}
        self.assertEqual(used, set(br.SUBTOPICS))

    def test_the_template_invariants_hold(self):
        angles = {direction.angle for direction in ex.DIRECTIONS.values()}
        seen_angles = set()
        for name, template in br.SUBTOPICS.items():
            with self.subTest(template=name):
                self.assertIn(keyword_key(template.direction), ex.DIRECTIONS)                      # 방향 낱말이 일반 확장의 표에 있다
                self.assertIn(template.content_type, md.CONTENT_TYPES)
                self.assertIn(template.search_intent, md.SEARCH_INTENTS)
                self.assertTrue(ch.is_slug(template.angle))
                self.assertNotIn(template.angle, angles, "브랜드 관점이 일반 확장의 관점과 겹치지 않는다")
                self.assertNotIn(template.angle, seen_angles, "틀끼리 관점이 겹치지 않는다")
                seen_angles.add(template.angle)
                self.assertIn(template.condition, ("", "api", "brand_free"))
                self.assertEqual("{brand}" in template.topic, template.condition != "brand_free")
        self.assertEqual([name for name, template in br.SUBTOPICS.items() if "{brand}" not in template.topic], ["gpu_generation"])
        for kind, listed in br.TYPE_SUBTOPICS.items():
            keywords = [br.SUBTOPICS[name].keyword for name in listed]
            angles_of_type = [br.SUBTOPICS[name].angle for name in listed]
            self.assertEqual(len(set(keywords)), len(keywords), kind)
            self.assertEqual(len(set(angles_of_type)), len(angles_of_type), kind)

    def test_the_context_tables_cover_every_cluster_and_every_tag_the_generator_knows(self):
        known = set(ex.CLUSTER_LABELS)
        self.assertEqual(set(br.CLUSTER_TYPES) | set(br.TYPELESS_CLUSTERS), known)
        self.assertEqual(set(br.CLUSTER_TYPES) & set(br.TYPELESS_CLUSTERS), set())
        self.assertEqual(len(br.CLUSTER_TYPES), 21)
        self.assertEqual(set(br.TAG_TYPES), set(gn.CLUSTER_MONETIZATION.values()))
        for kinds in (*br.CLUSTER_TYPES.values(), *br.TAG_TYPES.values()):
            self.assertTrue(set(kinds) <= set(br.BRAND_TYPES))

    def test_brand_is_not_a_safety_flag_name_and_the_state_names_are_the_requests(self):
        for flag in md.SAFETY_FLAGS:
            self.assertNotIn("brand_only", flag)
        self.assertEqual((br.STATE_BRAND_ONLY, br.STATE_NOT_BRAND, br.MAX_SUBTOPICS, br.KEEP_ALL), ("BRAND_ONLY", "NOT_BRAND", 3, True))


class FindBrandsTest(unittest.TestCase):                                                                       # B2
    def test_the_answer_table_has_eighty_seven_rows(self):
        self.assertEqual((len(SINGLE), len(LISTS), len(NEGATIVE)), (38, 7, 42))

    def test_one_brand_alone_is_found_in_any_spelling(self):
        for text in SINGLE:
            with self.subTest(text=text):
                hits = br.find_brands(text)
                self.assertIsNotNone(hits, text)
                self.assertEqual(len(hits), 1, text)

    def test_two_or_more_brands_in_a_row_are_a_list(self):
        for text in LISTS:
            with self.subTest(text=text):
                hits = br.find_brands(text)
                self.assertIsNotNone(hits, text)
                self.assertGreaterEqual(len(hits), 2)
                self.assertLessEqual(len(hits), 4)

    def test_anything_with_another_word_a_number_or_an_unknown_name_is_not_brand_only(self):
        for text in NEGATIVE:
            with self.subTest(text=text):
                self.assertIsNone(br.find_brands(text), text)

    def test_the_right_brand_comes_back_and_the_spelling_pairs_are_the_same_brand(self):
        for pair in (("Gemini", "제미나이"), ("Claude", "클로드"), ("ChatGPT", "챗지피티"), ("NVIDIA", "엔비디아"), ("삼성", "삼성전자"), ("LG", "엘지"), ("Microsoft", "마이크로소프트"), ("네이버", "Naver"),
                     ("Apple", "애플"), ("VS Code", "VSCode"), ("GitHub", "깃허브"), ("Google", "구글")):
            with self.subTest(pair=pair):
                self.assertEqual(br.find_brands(pair[0])[0].key, br.find_brands(pair[1])[0].key)
        self.assertEqual(names(br.find_brands("Google Gemini")), ["Gemini"], "한 브랜드의 별칭이다")
        self.assertEqual(names(br.find_brands("삼성, LG")), ["삼성", "LG"])
        self.assertEqual(names(br.find_brands("NVIDIA AMD Intel")), ["NVIDIA", "AMD", "Intel"])

    def test_each_condition_changed_one_at_a_time(self):
        for text in ("  Gemini", "Gemini  ", "GEMINI", "gEmInI", "ＧＥＭＩＮＩ", "제미나이를", "클로드는", "네이버가", "삼성이", "엔비디아의", "구글에서", "삼성엘지", "엔비디아에이엠디", "삼성 and LG",
                     "삼성 및 LG", "삼성 그리고 LG", "삼성 와 LG", "Gemini, Claude", "Gemini·Claude", "Gemini/Claude", "Gemini & Claude", "Gemini + Claude"):
            with self.subTest(text=text):
                self.assertIsNotNone(br.find_brands(text), text)
        for text in ("Gemini vs Claude", "Gemini 비교", "Gemini 사용법", "Gemini API", "Gemini 2", "삼성동", "Claudette", "LGBTQ", "애플리케이션", "구글링", "Gemini 대 Claude"):
            with self.subTest(text=text):
                self.assertIsNone(br.find_brands(text), text)

    def test_more_than_four_brands_or_a_very_long_text_is_not_brand_only(self):
        self.assertIsNone(br.find_brands("삼성 LG 애플 구글 네이버"))
        self.assertIsNone(br.find_brands("삼성" * 40))
        self.assertIsNone(br.find_brands(3))
        self.assertIsNone(br.find_brands(None))

    def test_english_channels_are_not_applicable_so_todays_behaviour_stays(self):
        for profile in ch.default_profiles():
            view = br.assess(seed("Gemini"), profile)
            if profile.language == "en":
                self.assertEqual(view, br.NOT_BRAND_VIEW)
            else:
                self.assertEqual(view.state, "BRAND_ONLY")
        self.assertEqual(br.assess(seed("Gemini 2.5"), B), br.NOT_BRAND_VIEW)


class ResolveTypeTest(unittest.TestCase):                                                                      # B3
    def resolve(self, keyword, profile, **seed_changes):
        hit = br.find_brands(keyword)[0]
        return br.resolve_type(hit, seed(keyword, **seed_changes), profile)

    def test_a_brand_with_one_type_is_that_type(self):
        self.assertEqual(self.resolve("Gemini", B), ("ai_service", "single"))
        self.assertEqual(self.resolve("NVIDIA", A), ("gpu", "single"))

    def test_the_seeds_category_or_sponsor_tag_narrows_the_types_first(self):
        self.assertEqual(self.resolve("삼성", A, major="가", minor="소형가전"), ("appliance", "seed"))
        self.assertEqual(self.resolve("삼성", A, major="가", minor="PC 주변기기"), ("pc_peripheral", "seed"))
        self.assertEqual(self.resolve("삼성", A, sponsor_tag="small_appliance"), ("appliance", "seed"))
        self.assertEqual(self.resolve("LG", A, major="가", minor="PC 주변기기"), ("pc_peripheral", "seed"))

    def test_the_channels_own_clusters_narrow_the_types_next(self):
        self.assertEqual(self.resolve("삼성", B), ("pc_parts", "channel"))

    def test_an_ambiguous_brand_that_the_context_cannot_decide_is_not_decided_and_a_plain_brand_takes_its_main_type(self):
        self.assertEqual(self.resolve("삼성", A), (None, ""))
        self.assertEqual(self.resolve("LG", B), (None, ""))
        self.assertEqual(self.resolve("AMD", B), ("gpu", "primary"))
        self.assertEqual(self.resolve("Microsoft", B), ("software", "primary"))

    def test_a_context_that_has_no_overlap_does_not_narrow(self):
        self.assertEqual(self.resolve("삼성", A, major="가", minor="숙박"), (None, ""), "씨앗의 맥락(숙박·여행)이 브랜드의 유형과 겹치지 않으면 줄이지 않고 채널로 가도 둘이 남아 보류")
        self.assertEqual(self.resolve("삼성", B, major="가", minor="소형가전"), ("pc_parts", "channel"), "채널(네이버 B)이 그 묶음을 다루지 않으면 씨앗의 분류도 맥락이 되지 못한다")

    def test_wrong_kinds_are_programming_errors(self):
        hit = br.find_brands("Gemini")[0]
        with self.assertRaises(TypeError):
            br.resolve_type("Gemini", seed("Gemini"), B)
        with self.assertRaises(TypeError):
            br.resolve_type(hit, "씨앗", B)
        with self.assertRaises(TypeError):
            br.assess("Gemini", B)


class SubtopicsTest(unittest.TestCase):                                                                        # B4
    def test_every_brand_on_every_channel_and_seed_kind_gives_at_most_three_ordered_checked_subtopics(self):
        count = 0
        for hit in br.BRANDS:
            for profile in ALL_ON:
                if profile.language == "en":
                    continue
                for kind in ("general", "priority", "seasonal", "sponsorable"):
                    view = br.assess(seed(hit.display, major="가", minor="소형가전" if hit.types[0] == "appliance" else "없는 분류", seed_type=kind, sponsor_tag="small_appliance" if kind == "sponsorable" else None), profile)
                    count += 1
                    if view.outcome != "ready":
                        continue
                    self.assertLessEqual(len(view.subtopics), br.MAX_SUBTOPICS)
                    order = br.TYPE_SUBTOPICS[view.brand_type]
                    positions = [order.index(sub.template) for sub in view.subtopics]
                    self.assertEqual(positions, sorted(positions), (hit.display, profile.key))
                    self.assertEqual(len({sub.keyword for sub in view.subtopics}), len(view.subtopics))
                    self.assertEqual(len({sub.angle for sub in view.subtopics}), len(view.subtopics))
                    for sub in view.subtopics:
                        self.assertIsNone(forbidden_claim(sub.topic))
                        self.assertIsNone(forbidden_claim(sub.keyword))
                        self.assertLessEqual(len(sub.topic), md.MAX_TOPIC)
                        self.assertLessEqual(len(sub.keyword), 60)
                        self.assertIn(keyword_key(sub.direction), ex.DIRECTIONS)
        self.assertGreater(count, 1000)

    def test_naver_a_and_naver_b_give_different_templates_for_the_same_brand(self):
        gemini_b = [sub.template for sub in br.assess(seed("Gemini"), B).subtopics]
        gemini_a = [sub.template for sub in br.assess(seed("Gemini"), A).subtopics]
        self.assertEqual(gemini_b, ["plan_compare", "api_usage", "automation_security"])
        self.assertEqual(gemini_a, ["plan_compare", "automation_security", "usage_limits"], "API 연동 이 네이버 A 방향에 없어 건너뛴다")
        self.assertEqual([sub.template for sub in br.assess(seed("NVIDIA"), B).subtopics], ["gpu_vram", "official_specs", "gpu_generation"])
        self.assertEqual([sub.template for sub in br.assess(seed("NVIDIA"), A).subtopics], ["official_specs", "gpu_generation", "warranty"])
        self.assertEqual([sub.template for sub in br.assess(seed("다이슨", major="가", minor="소형가전"), B).subtopics], ["running_cost", "warranty"], "네이버 B 는 구매 기준·관리 방법 방향이 없어 두 개뿐이다")
        self.assertEqual([sub.template for sub in br.assess(seed("Dyson", major="가", minor="소형가전"), A).subtopics], ["buying_criteria", "care_check", "running_cost"])

    def test_a_brand_without_an_api_skips_the_api_template(self):
        for name in ("Copilot", "Midjourney"):
            templates = [sub.template for sub in br.assess(seed(name), B).subtopics]
            self.assertNotIn("api_usage", templates)
            self.assertEqual(templates, ["plan_compare", "automation_security", "usage_limits"])

    def test_a_sentence_or_keyword_longer_than_the_candidate_limits_is_left_out_with_the_too_long_reason(self):
        with mock.patch.object(br, "MAX_KEYWORD", 10):
            view = br.assess(seed("Gemini"), B)
        self.assertEqual((view.outcome, view.subtopics), ("low_foundation", ()))
        self.assertEqual([(item.reason, item.count) for item in view.skipped], [("too_long", 1), ("too_long", 1), ("too_long", 1)])
        with mock.patch.object(br, "MAX_TOPIC", 20):
            self.assertEqual(br.assess(seed("Gemini"), B).outcome, "low_foundation")

    def test_only_the_template_without_a_brand_in_its_sentence_is_marked_brand_free(self):
        view = br.assess(seed("NVIDIA"), B)
        self.assertEqual([(sub.template, sub.brand_free) for sub in view.subtopics], [("gpu_vram", False), ("official_specs", False), ("gpu_generation", True)])
        self.assertEqual(sum(sub.brand_free for sub in br.assess(seed("Gemini"), B).subtopics), 0)

    def test_the_object_particle_in_the_sentence_matches_an_independent_rule(self):
        for hit in br.BRANDS:
            view = br.assess(seed(hit.display, major="가", minor="소형가전" if "appliance" in hit.types[:1] else "없는 분류"), ALL_ON[3])
            for sub in view.subtopics:
                if sub.template == "automation_security":
                    self.assertEqual(sub.topic, f"업무 자동화에 {hit.display}{eul(hit.reading)} 연결할 때 확인할 보안 설정")

    def test_the_sentence_uses_the_table_display_name_even_when_the_operator_wrote_the_korean_reading(self):
        view = br.assess(seed("엔비디아"), B)
        self.assertEqual(view.subtopics[0].topic, "NVIDIA 그래픽카드의 VRAM을 로컬 AI 기준으로 비교하는 방법")
        self.assertEqual(view.hits[0].display, "NVIDIA")

    def test_how_many_of_the_twenty_two_templates_pass_the_writability_check_at_each_minimum(self):
        for minimum, passing in ((4, 22), (7, 19), (8, 16), (9, 1), (10, 0)):
            with self.subTest(minimum=minimum):
                count = sum(fe.assess(template.content_type, template.search_intent, subheading_min=minimum).level != fe.LEVEL_LOW for template in br.SUBTOPICS.values())
                self.assertEqual(count, passing)

    def test_when_every_subtopic_fails_the_check_the_view_is_low_foundation_and_a_partial_failure_is_ready_with_a_record(self):
        for minimum, outcome, kept, dropped in ((8, "ready", 2, 1), (9, "low_foundation", 0, 3), (10, "low_foundation", 0, 3)):
            with self.subTest(minimum=minimum):
                view = br.assess(seed("Gemini"), dataclasses.replace(B, subheading_min=minimum))
                self.assertEqual((view.outcome, len(view.subtopics)), (outcome, kept))
                unfeasible = [item for item in view.skipped if item.reason == "brand_unfeasible"]
                self.assertEqual(sum(item.count for item in unfeasible), dropped)
        view = br.assess(seed("Gemini"), dataclasses.replace(B, subheading_min=8))
        self.assertEqual(next(item for item in view.skipped).detail, "구체화한 하위 주제 1개는 소제목 최소 수(8개)를 채우지 못해 쓰지 않습니다")
        low = br.assess(seed("Gemini"), dataclasses.replace(B, subheading_min=10))
        self.assertEqual(low.skipped[0].detail, "구체화한 하위 주제 3개가 모두 소제목 최소 수(10개)를 채우지 못해 ‘작성 기반 부족’ 으로 보류했습니다")
        self.assertEqual(low.notes, ("소제목 최소 수를 채우지 못한 하위 주제: 3개",))

    def test_an_excluded_keyword_of_the_seed_blocks_only_the_templates_that_contain_it(self):
        view = br.assess(seed("Gemini", excluded_keywords=("보안",)), B)
        self.assertEqual([sub.template for sub in view.subtopics], ["plan_compare", "api_usage"], "떨어진 틀을 네 번째 틀로 메우지 않는다")
        self.assertEqual([item.reason for item in view.skipped], ["excluded_keyword"])
        everything = br.assess(seed("Gemini", excluded_keywords=("Gemini",)), B)
        self.assertEqual((everything.outcome, len(everything.subtopics)), ("needs_topic", 0), "씨앗 낱말 자체가 제외 키워드면 모든 방향이 막혀 허용 틀이 하나도 없다")
        self.assertTrue(everything.skipped and all(item.reason == "excluded_keyword" for item in everything.skipped))

    def test_a_list_an_undecidable_type_or_no_allowed_template_needs_a_topic_and_makes_no_subtopic(self):
        for keyword, minor in (("삼성 LG", "없는 분류"), ("삼성", "없는 분류")):
            view = br.assess(seed(keyword, minor=minor), A)
            self.assertEqual((view.state, view.outcome, view.subtopics, view.count), ("BRAND_ONLY", "needs_topic", (), 0))
            self.assertTrue(view.detail and view.notes)
        with mock.patch.object(br, "TYPE_SUBTOPICS", {**br.TYPE_SUBTOPICS, "ai_service": ("api_usage",)}):             # 이 채널(네이버 A)의 방향에 'API 연동' 이 없어 허용 틀이 하나도 없다
            none_allowed = br.assess(seed("Gemini"), A)
        self.assertEqual((none_allowed.state, none_allowed.outcome, none_allowed.subtopics), ("BRAND_ONLY", "needs_topic", ()))
        self.assertEqual(none_allowed.notes, ("이 채널에서 쓸 수 있는 하위 주제 틀이 없습니다",))
        self.assertTrue(none_allowed.detail.startswith("브랜드 이름만 있는데 이 채널에서 쓸 수 있는 하위 주제 틀이 없어 보류했습니다"))

    def test_the_view_never_changes_its_inputs_and_gives_the_same_answer_twice(self):
        made = seed("Gemini")
        before = made.to_dict()
        first = br.assess(made, B)
        self.assertEqual(made.to_dict(), before)
        self.assertEqual(first, br.assess(made, B))


class NoSignalTest(unittest.TestCase):                                                                         # B5
    def test_no_brand_name_alias_or_template_sentence_is_a_safety_or_sponsor_signal(self):
        texts = [hit.display for hit in br.BRANDS] + [key for key, _number in br.ALIASES]
        for hit in br.BRANDS:
            for template in br.SUBTOPICS.values():
                values = {"brand": hit.display, "eul": "를"}
                texts.append(template.topic.format(**values))
                texts.append(template.keyword.format(**values))
        self.assertGreater(len(texts), 1500)
        for text in texts:
            report = sf.check_text([text])
            self.assertEqual((report.flags, report.findings), ((), ()), text)

    def test_the_brand_module_imports_only_the_allowed_modules(self):
        allowed_relative = {"": {"expand", "feasibility", "wording"}, "channels": None, "dedupe": None, "seeds": None, "model": None}
        tree = ast.parse(Path(br.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    self.assertIn(node.module, ("__future__", "re", "unicodedata", "types", "typing"))
                elif node.level == 1:
                    self.assertIn(node.module or "", allowed_relative, node.module)
                    if node.module is None:
                        self.assertTrue({alias.name for alias in node.names} <= allowed_relative[""], [alias.name for alias in node.names])
                else:
                    self.assertEqual((node.level, node.module), (2, "content.candidates"))
            elif isinstance(node, ast.Import):
                self.assertTrue({alias.name for alias in node.names} <= {"re", "unicodedata"}, [alias.name for alias in node.names])
        text = Path(br.__file__).read_text(encoding="utf-8")
        for forbidden in ("safety", "concepts", "notice", "SAFETY_FLAGS"):
            self.assertNotIn(f"import {forbidden}", text)
            self.assertNotIn(f"from .{forbidden}", text)


class NoPenaltyTest(unittest.TestCase):                                                                        # B6
    def test_a_specified_candidates_evidence_is_the_plain_base_and_no_flag_is_set(self):
        for keyword in ("Gemini", "NVIDIA", "Claude", "Dyson"):
            found = gn.generate(B, [seed(keyword, major="가", minor="소형가전" if keyword == "Dyson" else "없는 분류")], [], (), "2026-11-10", target=100)
            for candidate in found.candidates:
                with self.subTest(keyword=keyword, topic=candidate.topic):
                    self.assertEqual(candidate.safety_flags, ())
                    self.assertEqual(candidate.scores.factors.evidence, gn.EVIDENCE_BASE[candidate.content_type])

    def test_replacing_the_brand_by_a_neutral_word_changes_neither_the_flags_nor_the_evidence(self):
        found = gn.generate(B, [seed("Gemini")], [], (), "2026-11-10", target=100)
        for candidate in found.candidates:
            neutral = dataclasses.replace(candidate, topic=candidate.topic.replace("Gemini", "예시제품"), primary_keyword=candidate.primary_keyword.replace("Gemini", "예시제품"),
                                          secondary_keywords=tuple(word.replace("Gemini", "예시제품") for word in candidate.secondary_keywords))
            self.assertEqual(sf.assess(candidate).flags, sf.assess(neutral).flags)
            self.assertEqual(gn._evidence(candidate, sf.assess(candidate).flags, gn._Extra()), gn._evidence(neutral, sf.assess(neutral).flags, gn._Extra()))


class RequestExamplesTest(unittest.TestCase):                                                                  # B7
    def test_gemini_on_naver_b_gives_the_three_sentences_of_the_request_in_that_order(self):
        found = gn.generate(B, [seed("Gemini")], [], (), "2026-11-10", target=100)
        self.assertEqual({c.topic for c in found.candidates}, {"Gemini 무료·유료 기능을 비교할 때 확인할 항목", "Gemini API 사용량을 관리하는 방법", "업무 자동화에 Gemini를 연결할 때 확인할 보안 설정"})
        view = br.assess(seed("Gemini"), B)
        self.assertEqual((view.state, view.outcome), ("BRAND_ONLY", "ready"))
        self.assertEqual([sub.topic for sub in view.subtopics], ["Gemini 무료·유료 기능을 비교할 때 확인할 항목", "Gemini API 사용량을 관리하는 방법", "업무 자동화에 Gemini를 연결할 때 확인할 보안 설정"])

    def test_nvidia_on_naver_b_gives_the_three_sentences_of_the_request_in_that_order(self):
        view = br.assess(seed("NVIDIA"), B)
        self.assertEqual((view.state, view.outcome), ("BRAND_ONLY", "ready"))
        self.assertEqual([sub.topic for sub in view.subtopics], ["NVIDIA 그래픽카드의 VRAM을 로컬 AI 기준으로 비교하는 방법", "NVIDIA 신제품 공식 사양을 확인할 때 볼 항목", "로컬 AI용 GPU를 선택할 때 세대와 VRAM을 비교하는 기준"])
        found = gn.generate(B, [seed("NVIDIA")], [], (), "2026-11-10", target=100)
        self.assertEqual({c.topic for c in found.candidates}, {sub.topic for sub in view.subtopics})

    def test_the_seven_names_of_the_request_are_all_recognized_as_brand_only(self):
        for name in ("Gemini", "Claude", "NVIDIA", "삼성", "LG", "네이버", "Microsoft"):
            with self.subTest(name=name):
                self.assertEqual(br.assess(seed(name), B).state, "BRAND_ONLY")
                self.assertEqual(br.assess(seed(name), A).state, "BRAND_ONLY")


class DeterminismTest(unittest.TestCase):                                                                      # B8
    def test_no_code_in_the_module_walks_a_set_to_decide_an_output_order(self):
        tree = ast.parse(Path(br.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            iterables = []
            if isinstance(node, ast.For):
                iterables.append(node.iter)
            elif isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp)):
                iterables.extend(generator.iter for generator in node.generators)
            for item in iterables:
                self.assertFalse(isinstance(item, (ast.Set, ast.SetComp)) or (isinstance(item, ast.Call) and getattr(item.func, "id", "") in ("set", "frozenset")), ast.dump(item)[:80])
        self.assertNotIn("PARTICLES)", "".join(line for line in Path(br.__file__).read_text(encoding="utf-8").splitlines() if "for " in line and "sorted" not in line))

    def test_the_result_does_not_depend_on_the_order_of_the_seeds_given(self):
        pool = [seed("Gemini", seed_id="a"), seed("Claude", seed_id="b"), seed("노트북", seed_id="c", major="가", minor="소형가전")]
        forward = gn.generate(B, pool, [], (), "2026-11-10", target=100)
        backward = gn.generate(B, list(reversed(pool)), [], (), "2026-11-10", target=100)
        self.assertEqual({c.candidate_id for c in forward.candidates}, {c.candidate_id for c in backward.candidates})
        self.assertEqual(forward.routes, backward.routes)


class SponsorAndBrandTest(unittest.TestCase):                                                                  # B9
    def test_a_brand_seed_without_a_sponsor_tag_makes_no_sponsor_candidates(self):
        found = gn.generate(A, [seed("Dyson", major="가", minor="소형가전")], [], (), "2026-11-10", target=100)
        self.assertEqual({c.source_type for c in found.candidates}, {"seed"})
        self.assertTrue(all(c.monetization_tags == () for c in found.candidates))

    def test_with_a_tag_a_sponsor_route_candidate_appears_with_no_flag_and_the_possibility_line(self):
        found = gn.generate(A, [seed("Dyson", major="가", minor="소형가전", sponsor_tag="small_appliance")], [], (), "2026-11-10", target=100)
        sponsor = [c for c in found.candidates if c.source_type == "sponsor"]
        self.assertTrue(sponsor)
        for candidate in sponsor:
            self.assertEqual(candidate.monetization_tags, ("small_appliance",))
            self.assertNotIn("sponsor_disclosure", candidate.safety_flags)
            self.assertTrue(candidate.selection_reasons[0].endswith(" — 협업 가능 유형 ‘소형가전’(협찬이 확정된 것은 아닙니다)"), candidate.selection_reasons[0])


if __name__ == "__main__":
    unittest.main()
