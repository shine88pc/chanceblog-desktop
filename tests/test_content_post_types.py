"""글 유형 틀 5종과 안전 대체 규칙(`content/post_types.py`) 시험.

지키는 것:
  1) 틀 5종의 단계 이름과 순서가 요구서의 구조 그대로이고 각 단계에 소제목·핵심 내용 문구가 두 말씨(0·1)로 있으며 `{kw}` 자리가 소제목에 있다.
  2) 사용자의 경험이 입력되면 마무리 바로 앞에 경험 단락이 더해지고(유형마다 이름이 다르다), 입력이 없으면 더해지지 않는다.
  3) 글 유형은 사용자가 정한 것 → 후보의 추천(정보형이 아닐 때) → 프로필의 기본(정보형이 아닐 때) → 정보형 순으로 정해진다(모든 조합 전수).
  4) 경험을 전제한 후보(방문·제품 체험·직접 사용·일반 후기)는 가장 구체적인 형식으로 읽히고 평범한 글은 걸리지 않는다. 경험 낱말은 제목·소제목에 쓸 글에서 걷어 낸다.
  5) 틀의 모든 문구(소제목·핵심 내용·제목·검색 의도·주의사항·덧붙이는 단락)는 경험·가격·날짜·통계를 단정하지 않고 결과를 약속하지 않는다(`check/claims.py`·후보의 표현 규칙으로 전수 확인).
네트워크·파일 없이 돈다.
"""
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.check import claims  # noqa: E402
from chanceblog_desktop.content import post_types as pt  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.content.candidates import forbidden_claim  # noqa: E402
from chanceblog_desktop.content.profiles import DEFAULT_POST_TYPE, POST_TYPES  # noqa: E402

EXPECTED_STEPS = {
    "정보형": ("독자가 궁금해하는 문제", "핵심 개념", "확인할 기준", "활용 방법", "주의사항", "핵심 정리"),
    "비교형": ("비교 목적", "공통 기준", "대상별 특징", "장점과 제한", "상황별 선택 기준", "정리"),
    "문제 해결형": ("문제 증상", "가능한 원인", "확인 순서", "해결 방법", "재발 방지", "추가 확인사항"),
    "제품·서비스 소개형": ("제품 또는 서비스 개요", "주요 기능", "적합한 사용자", "선택 전 확인사항", "장점과 제한", "정리"),
    "장소·업체 정보형": ("장소 또는 업체 개요", "주요 정보", "이용 전 확인사항", "메뉴·서비스 또는 시설", "적합한 방문 목적", "공식 정보 확인 안내"),
}
SUBJECT = "보일러 점검"


def all_phrases():
    """틀이 가진 모든 문구(`{kw}` 는 평범한 주제로 채운다) — (어디, 문장)."""
    for post_type, steps in pt.TEMPLATES.items():
        for step in (*steps, pt.EXPERIENCE_STEPS[post_type]):
            yield f"{post_type}/{step.key}/이름", step.name
            for voice in pt.VOICES:
                yield f"{post_type}/{step.key}/소제목{voice}", step.head(voice, SUBJECT)
                yield f"{post_type}/{step.key}/핵심{voice}", step.point(voice)
    for step in (pt.LEAD_STEP, *pt.EXTRA_STEPS):
        yield f"{step.key}/이름", step.name
        for voice in pt.VOICES:
            yield f"{step.key}/소제목{voice}", step.head(voice, SUBJECT)
            yield f"{step.key}/핵심{voice}", step.point(voice)
    for post_type in POST_TYPES:
        for voice in pt.VOICES:
            yield f"{post_type}/검색의도{voice}", pt.INTENTS[post_type][voice]
            for title in pt.TITLES[post_type][voice]:
                yield f"{post_type}/제목{voice}", title.replace("{kw}", SUBJECT)
        for caution in pt.CAUTIONS[post_type]:
            yield f"{post_type}/주의", caution
    for title in pt.SHORT_TITLES:
        yield "짧은 제목", title.replace("{kw}", SUBJECT)
    for post_type, audience in pt.AUDIENCES.items():
        yield f"{post_type}/독자", audience


class TemplateTest(unittest.TestCase):
    def test_there_are_exactly_the_five_types_in_the_profile_order(self):
        self.assertEqual(tuple(pt.TEMPLATES), POST_TYPES)
        self.assertEqual(len(POST_TYPES), 5)
        self.assertEqual((pt.INFO, pt.COMPARE, pt.TROUBLE, pt.PRODUCT, pt.PLACE), POST_TYPES)
        for table in (pt.EXPERIENCE_STEPS, pt.INTENTS, pt.TITLES, pt.CAUTIONS, pt.TAG_TAILS):
            self.assertEqual(set(table), set(POST_TYPES))

    def test_step_names_and_order_follow_the_requirement_structure(self):
        for post_type, names in EXPECTED_STEPS.items():
            with self.subTest(post_type=post_type):
                self.assertEqual(tuple(step.name for step in pt.TEMPLATES[post_type]), names)
                self.assertEqual(tuple(step.name for step in pt.template_steps(post_type)), names)

    def test_every_step_has_a_unique_key_and_two_voices(self):
        for post_type, steps in pt.TEMPLATES.items():
            self.assertEqual(len({step.key for step in steps}), len(steps), post_type)
            for step in steps:
                with self.subTest(post_type=post_type, step=step.key):
                    self.assertEqual((len(step.heads), len(step.points)), (2, 2))
                    self.assertNotEqual(step.heads[0], step.heads[1])
                    self.assertNotEqual(step.points[0], step.points[1])
                    self.assertTrue(all("{kw}" in head for head in step.heads))
                    self.assertTrue(all("{kw}" not in point for point in step.points))
                    self.assertEqual(step.head(0, "주제"), step.heads[0].replace("{kw}", "주제"))
                    self.assertIn("주제", step.head(1, "주제"))
                    self.assertEqual(step.point(1), step.points[1])

    def test_the_voice_map_covers_every_platform_and_the_naver_blogs_differ(self):
        self.assertEqual(set(pt.VOICE), set(st.PLATFORMS))
        self.assertTrue(set(pt.VOICE.values()) <= set(pt.VOICES))
        self.assertEqual((pt.VOICE["naver_a"], pt.VOICE["naver_b"]), (0, 1))

    def test_the_two_voices_have_different_phrases_everywhere(self):
        for post_type in POST_TYPES:
            with self.subTest(post_type=post_type):
                self.assertNotEqual(pt.TITLES[post_type][0], pt.TITLES[post_type][1])
                self.assertFalse(set(pt.TITLES[post_type][0]) & set(pt.TITLES[post_type][1]))
                self.assertEqual((len(pt.TITLES[post_type][0]), len(pt.TITLES[post_type][1])), (3, 3))
                self.assertNotEqual(pt.INTENTS[post_type][0], pt.INTENTS[post_type][1])
                self.assertNotEqual(pt.TAG_TAILS[post_type][0], pt.TAG_TAILS[post_type][1])
                self.assertEqual(len(pt.CAUTIONS[post_type]), 2)

    def test_experience_paragraph_goes_right_before_the_closing_step_and_only_when_asked(self):
        names = {"정보형": "경험 이야기", "비교형": "경험 이야기", "문제 해결형": "경험 이야기", "제품·서비스 소개형": "사용 경험", "장소·업체 정보형": "방문 경험"}
        for post_type in POST_TYPES:
            with self.subTest(post_type=post_type):
                plain = pt.template_steps(post_type)
                with_experience = pt.template_steps(post_type, experience=True)
                self.assertEqual(len(with_experience), len(plain) + 1)
                self.assertEqual(with_experience[-2].name, names[post_type])
                self.assertEqual(with_experience[-1], plain[-1])
                self.assertEqual(with_experience[:-2], plain[:-1])
                self.assertNotIn(names[post_type], [step.name for step in plain])
                self.assertEqual(pt.template_steps(post_type, experience=False), plain)

    def test_the_visit_paragraph_is_only_named_a_visit_paragraph_for_places(self):
        self.assertNotIn("방문", " ".join(step.name for post_type in POST_TYPES if post_type != pt.PLACE for step in pt.template_steps(post_type, experience=True)))
        self.assertNotIn("방문 경험", [step.name for step in pt.template_steps(pt.PLACE)])

    def test_the_extra_and_lead_steps(self):
        self.assertEqual([step.name for step in pt.EXTRA_STEPS], ["자주 묻는 질문", "용어 풀이", "점검표"])
        self.assertEqual(pt.LEAD_STEP.name, "핵심 먼저 보기")
        self.assertEqual(len({step.key for step in (*pt.EXTRA_STEPS, pt.LEAD_STEP)}), 4)


class PhraseSafetyTest(unittest.TestCase):
    def test_no_template_phrase_claims_experience_price_date_or_statistics(self):
        seen = 0
        for where, text in all_phrases():
            seen += 1
            with self.subTest(where=where, text=text):
                self.assertEqual(claims.find_claims(text), (), "경험·가격·날짜·통계를 단정하는 말이 있다")
        self.assertGreater(seen, 200)

    def test_no_template_phrase_promises_a_result(self):
        for where, text in all_phrases():
            with self.subTest(where=where, text=text):
                self.assertIsNone(forbidden_claim(text))

    def test_no_phrase_has_digits_or_markup_or_leftover_placeholders(self):
        for where, text in all_phrases():
            with self.subTest(where=where):
                self.assertFalse(any(ch.isdigit() for ch in text), text)
                self.assertNotIn("{", text)
                self.assertNotIn("}", text)
                self.assertNotIn("<", text)
                self.assertEqual(text, text.strip())
                self.assertNotIn("  ", text)

    def test_titles_stay_short_enough_for_the_common_title_limit(self):
        for post_type in POST_TYPES:
            for voice in pt.VOICES:
                for title in pt.TITLES[post_type][voice]:
                    with self.subTest(title=title):
                        self.assertLessEqual(len(title.replace("{kw}", SUBJECT)), 40)
                        self.assertIn("{kw}", title)


class ResolvePostTypeTest(unittest.TestCase):
    def test_every_combination_follows_user_then_candidate_then_profile_then_default(self):
        options = (None, "", DEFAULT_POST_TYPE, "비교형", "문제 해결형")
        for user, candidate, profile in itertools.product(options, options, options):
            expected = (DEFAULT_POST_TYPE, "default")
            if user:
                expected = (user, "user")
            elif candidate and candidate != DEFAULT_POST_TYPE:
                expected = (candidate, "candidate")
            elif profile and profile != DEFAULT_POST_TYPE:
                expected = (profile, "profile")
            with self.subTest(user=user, candidate=candidate, profile=profile):
                self.assertEqual(pt.resolve_post_type(user, candidate, profile), expected)

    def test_the_users_own_choice_wins_even_when_it_is_the_default_type(self):
        self.assertEqual(pt.resolve_post_type("정보형", "비교형", "문제 해결형"), ("정보형", "user"))

    def test_the_candidates_recommendation_beats_the_profile_default_unless_it_is_the_default(self):
        self.assertEqual(pt.resolve_post_type(None, "비교형", "문제 해결형"), ("비교형", "candidate"))
        self.assertEqual(pt.resolve_post_type(None, "정보형", "문제 해결형"), ("문제 해결형", "profile"))
        self.assertEqual(pt.resolve_post_type(None, None, None), ("정보형", "default"))


class PremiseTest(unittest.TestCase):
    CASES = (
        ("visit", ("서울 맛집 방문 후기", "카페 방문후기", "제주도 다녀온 곳", "성수동 맛집 다녀왔어요", "신상 카페 방문기", "한강 가본 곳", "호텔 후기", "맛집 후기 모음", "여행후기")),
        ("product", ("이어폰 체험 후기", "체험단 제품 후기", "무선청소기 구매후기", "언박싱 후기", "내돈내산 정리", "제품 리뷰 모음", "개봉기", "협찬 후기")),
        ("use", ("노트북 사용 후기", "로봇청소기 사용기", "직접 써본 에어프라이어", "한달 사용 후기", "장기사용 리뷰", "실사용 후기", "써봤어요", "이용 후기")),
        ("review", ("보일러 교체 후기", "정수기 리뷰", "다이어트 경험담", "자격증 준비 경험기", "솔직 후기", "솔직 리뷰", "겪어본 이야기")),
    )
    PLAIN = ("겨울 보일러 점검 순서", "노트북 추천 비교", "무선 청소기 선택 기준", "서울 한강 야경 명소", "전기요금 절약 방법", "방문 전 확인사항", "구매 가이드", "무료 체험판 사용법", "후기를 쓰는 요령 정리하는 중",
             "난방비 줄이는 방법", "냉장고 소음 해결", "에어컨 청소 순서")

    def test_each_kind_is_recognised_and_gets_its_replacement(self):
        expected = {"visit": ("방문 후기", "위치·이용 정보와 방문 전 확인사항", pt.PLACE), "product": ("제품 체험 후기", "공개된 제품 정보와 구매 전 확인사항", pt.PRODUCT),
                    "use": ("직접 사용 후기", "기능과 선택 기준 정리", pt.PRODUCT), "review": ("경험형 후기", "정보형 안내 글", None)}
        for kind, topics in self.CASES:
            for topic in topics:
                with self.subTest(kind=kind, topic=topic):
                    found = pt.premise_of(topic, "키워드")
                    self.assertIsNotNone(found, topic)
                    if found.kind != kind:
                        # 앞선(더 구체적인) 규칙이 먼저 읽는 것은 허용하되 그 규칙의 대체는 정해진 것이어야 한다
                        self.assertIn(found.kind, ("visit", "product", "use"), topic)
                    self.assertEqual((found.label_from, found.label_to, found.post_type), expected[found.kind])

    def test_the_exact_kind_for_the_clear_examples(self):
        clear = {"서울 맛집 방문 후기": "visit", "이어폰 체험 후기": "product", "노트북 사용 후기": "use", "보일러 교체 후기": "review", "카페 방문기": "visit", "구매후기": "product", "로봇청소기 사용기": "use",
                 "다이어트 경험담": "review"}
        for topic, kind in clear.items():
            with self.subTest(topic=topic):
                self.assertEqual(pt.premise_of(topic).kind, kind)

    def test_the_more_specific_form_wins(self):
        self.assertEqual(pt.premise_of("제품 사용 후기, 방문 후기").kind, "visit")
        self.assertEqual(pt.premise_of("제품 체험 후기 사용 후기").kind, "product")
        self.assertEqual(pt.premise_of("사용 후기 경험담").kind, "use")
        self.assertEqual(pt.premise_of("카페 방문 후기 체험단").kind, "visit")                  # 방문 낱말과 제품 낱말이 함께 있으면 방문이 먼저다
        self.assertEqual(pt.premise_of("이어폰 체험 후기 사용 후기").kind, "product")

    def test_plain_topics_are_not_premises(self):
        for topic in self.PLAIN:
            with self.subTest(topic=topic):
                self.assertIsNone(pt.premise_of(topic, "키워드"))

    def test_the_words_come_from_any_of_the_given_texts_and_blank_ones_are_skipped(self):
        self.assertEqual(pt.premise_of("보일러", "점검", "교체 후기").kind, "review")
        self.assertIsNone(pt.premise_of("", None, "보일러"))
        self.assertIsNone(pt.premise_of())

    def test_spacing_and_width_do_not_hide_a_premise(self):
        self.assertEqual(pt.premise_of("방 문 후 기").kind, "visit")
        self.assertEqual(pt.premise_of("ＡＩ 사용　후기").kind, "use")

    def test_replacements_map_to_the_specified_formats(self):
        formats = {rule.kind: rule for rule, _words in pt.PREMISE_RULES}
        self.assertEqual(list(formats), ["visit", "product", "use", "review"])
        self.assertEqual(formats["visit"].post_type, pt.PLACE)
        self.assertEqual(formats["product"].post_type, pt.PRODUCT)
        self.assertEqual(formats["use"].post_type, pt.PRODUCT)
        self.assertIsNone(formats["review"].post_type)
        self.assertEqual(len({rule.label_to for rule in formats.values()}), 4)

    def test_strip_premise_removes_the_words_and_a_dangling_action_word(self):
        cases = {"보일러 사용 후기": "보일러", "OO식당 방문 후기": "OO식당", "직접 써본 노트북": "노트북", "겨울 보일러 점검 순서": "겨울 보일러 점검 순서", "이어폰 체험단 모집": "이어폰 모집", "솔직 후기": "", "후기": "",
                 "노트북 사용후기 모음": "노트북 모음", "맛집 다녀온 후기": "맛집", "내돈내산 청소기 후기": "청소기", "": "", "   ": ""}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(pt.strip_premise(text), expected)

    NEW_KINDS = (
        ("product", ("아이오닉 6 시승기", "운동화 시착기", "에어프라이어 체험담", "에어프라이어 체험", "무선 이어폰 hands-on", "iPhone 15 unboxing", "신형 노트북 언박싱과 후기", "서울 맛집 시식기", "에어프라이어 시음기",
                     "에어프라이어 hands on", "에어프라이어 Unboxing")),
        ("use", ("에어프라이어 사용 소감", "에어프라이어 먹어봤어요", "에어프라이어 직접 먹어본", "에어프라이어 써보니", "에어프라이어 도전기", "배달 앱 비교 써봤어요", "에어프라이어 입어봤어요")),
        ("review", ("iPhone 15 review", "에어프라이어 honest review", "성수동 카페 後記", "성수동 카페 訪問後記", "에어프라이어 Reviews")),
        ("visit", ("서울 근교 캠핑장 다녀왔어요", "제주 여행기", "성수동 카페 가봤어요", "경주 답사")),
    )

    def test_the_forms_the_review_found_missing_are_premises(self):
        for kind, topics in self.NEW_KINDS:
            for topic in topics:
                with self.subTest(kind=kind, topic=topic):
                    found = pt.premise_of(topic, "키워드")
                    self.assertIsNotNone(found, topic)
                    if kind in ("review", "visit"):
                        self.assertEqual(found.kind, kind, topic)

    def test_experience_words_inside_other_words_or_non_review_experiences_are_not_premises(self):
        for topic in ("iPhone preview guide", "Preview of the 2027 laptops", "무료 체험판 사용법", "체험 학습 장소 추천", "어린이 체험 프로그램 안내", "체험관 이용 안내", "체험 신청 방법", "체험형 전시 정보", "test reviewer tools"):
            with self.subTest(topic=topic):
                self.assertIsNone(pt.premise_of(topic, "키워드"))

    def test_a_word_boundary_decides_english_words(self):
        self.assertEqual(pt.premise_of("iPhone 15 review").kind, "review")
        self.assertEqual(pt.premise_of("My honest REVIEW of the laptop").kind, "review")
        self.assertEqual(pt.premise_of("Laptop hands-on").kind, "product")
        self.assertIsNone(pt.premise_of("reviewer guide"))

    def test_strip_premise_works_on_words_not_on_letters(self):
        cases = {
            "배달 앱 비교 써봤어요": "배달 앱 비교", "무선 이어폰 비교 직접 써봤더니": "무선 이어폰 비교", "로봇청소기 구매 후기와 장단점": "로봇청소기 구매와 장단점", "신형 노트북 언박싱과 후기": "신형 노트북",
            "서울 근교 캠핑장 다녀왔어요": "서울 근교 캠핑장", "iPhone 15 review": "iPhone 15", "에어프라이어 honest review": "에어프라이어", "에어프라이어 먹어봤어요": "에어프라이어", "에어프라이어 써보니": "에어프라이어",
            "에어프라이어 사용 소감": "에어프라이어", "아이오닉 6 시승기": "아이오닉 6", "에어프라이어 체험담": "에어프라이어", "에어프라이어 도전기": "에어프라이어", "성수동 카페 後記": "성수동 카페",
            "노트북 후기와 장단점 비교": "노트북과 장단점 비교", "청소기 후기랑 사용법": "청소기랑 사용법", "에어컨 후기나 가격": "에어컨이나 가격", "서울 맛집 방문 후기": "서울 맛집", "노트북 사용 후기를 정리": "노트북 정리",
            "성수동 카페 가봤더니": "성수동 카페", "냉장고 써 봤습니다": "냉장고", "솔직하게 써본 노트북": "노트북", "직접 해봤어요 청소기 비교": "청소기 비교", "신발 시착기와 장단점": "신발과 장단점",
            "휴대폰 후기 모음": "휴대폰 모음", "후기": "", "써봤어요": "", "직접 써봤어요 후기": "",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(pt.strip_premise(text), expected)

    INFO_ARTICLES = ("후기 작성 방법", "체험단 신청 방법", "맛집 리뷰 앱 추천", "후기 잘 쓰는 법", "리뷰 작성 요령", "체험단 모집 사이트", "블로그 후기 쓰는 방법", "리뷰 이벤트 참여 방법", "체험 후기 양식 예시", "리뷰 사이트 순위")

    def test_articles_about_reviews_are_not_reviews(self):
        for topic in self.INFO_ARTICLES:
            with self.subTest(topic=topic):
                self.assertIsNone(pt.premise_of(topic, "키워드"))
                self.assertIsNone(pt.premise_of("제목", topic))

    def test_a_real_review_that_mentions_an_info_word_is_still_a_review(self):
        for topic, kind in (("서울 맛집 방문 후기 추천 메뉴", "visit"), ("노트북 사용 후기 장단점 방법", "use"), ("이어폰 체험 후기 방법", "product"), ("홈트 기구 직접 써보고 쓰는 방법", "use"), ("한 달 써본 청소기 추천", "use"), ("제주 다녀왔어요 맛집 추천", "visit")):
            with self.subTest(topic=topic):
                found = pt.premise_of(topic)
                self.assertIsNotNone(found, topic)
                self.assertEqual(found.kind, kind, topic)

    def test_each_visit_word_is_read_as_a_visit(self):
        for topic in ("한옥마을 탐방", "경주 답사", "제주 여행기", "성수동 카페 가봤어요", "서울 숙소후기"):
            with self.subTest(topic=topic):
                self.assertEqual(pt.premise_of(topic).kind, "visit")

    def test_the_joining_particle_follows_the_last_sound_of_digits_and_letters(self):
        cases = {"아이폰15 후기와 장단점": "아이폰15와 장단점", "아이폰 3 후기와 가격": "아이폰 3과 가격", "ELM 후기와 가격": "ELM과 가격", "AI 후기와 가격": "AI와 가격", "갤럭시 S24 후기랑 가격": "갤럭시 S24랑 가격",
                 "갤럭시 S25 후기랑 가격": "갤럭시 S25랑 가격", "노트북 후기랑 가격": "노트북이랑 가격", "에어컨 후기나 가격": "에어컨이나 가격", "청소기 후기나 가격": "청소기나 가격"}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(pt.strip_premise(text), expected)
        self.assertFalse(pt._has_final(""))
        self.assertFalse(pt._has_final("…"))

    def test_a_token_made_only_of_punctuation_is_dropped(self):
        self.assertEqual(pt.strip_premise("노트북 - 사용 후기"), "노트북")
        self.assertEqual(pt.strip_premise("노트북 — 후기"), "노트북")
        self.assertEqual(pt.strip_premise("- ·"), "")

    def test_a_compound_that_starts_with_a_review_word_loses_only_the_review_word(self):
        self.assertEqual(pt.strip_premise("직접구매해본 노트북"), "노트북")
        self.assertEqual(pt.strip_premise("직접써본후기 청소기"), "청소기")
        self.assertEqual(pt.strip_premise("솔직하게 써본 노트북"), "노트북")
        self.assertEqual(pt.strip_premise("직접체험기 노트북"), "노트북")

    def test_overlapping_words_are_removed_longest_first(self):
        self.assertEqual(pt.strip_premise("노트북구매해본"), "노트북")
        self.assertEqual(pt.strip_premise("노트북사용해본후기"), "노트북")
        self.assertEqual(pt.strip_premise("청소기써본후기"), "청소기")

    def test_a_duration_and_a_felt_point_before_a_review_word_go_with_it(self):
        self.assertEqual(pt.strip_premise("에어프라이어 한 달 사용 후기"), "에어프라이어")
        self.assertEqual(pt.strip_premise("에어프라이어 3개월 사용 후기"), "에어프라이어")
        self.assertEqual(pt.strip_premise("홈트 기구 직접 써보고 느낀 점"), "홈트 기구")
        self.assertEqual(pt.strip_premise("홈트 기구 써 보고 느낀 점"), "홈트 기구")
        self.assertEqual(pt.strip_premise("노트북 사용 후기를 정리"), "노트북 정리")
        self.assertEqual(pt.strip_premise("노트북 사용 후기와"), "노트북")                     # 이어 줄 낱말이 없으면 조사도 동작 낱말도 남기지 않는다

    REVIEW_STYLE = (                                      # 후기형 후보의 키워드 25개 — 걷어 낸 뒤에 어미·조사 조각이 남지 않는다
        "배달 앱 비교 써봤어요", "무선 이어폰 비교 직접 써봤더니", "로봇청소기 구매 후기와 장단점", "신형 노트북 언박싱과 후기", "서울 근교 캠핑장 다녀왔어요", "공기청정기 사용 후기", "정수기 렌탈 직접 써본 후기",
        "에어프라이어 써보니", "전기장판 먹어봤어요 아니고 써봤어요", "노트북 파우치 구매후기와 비교", "무선 마우스 장기 사용 후기", "아이패드 케이스 내돈내산 후기", "제주 한달살이 다녀왔어요", "성수동 맛집 방문기",
        "러닝화 시착기와 사이즈", "전기자전거 시승기", "믹서기 체험단 후기", "보조배터리 솔직 리뷰", "태블릿 거치대 써보니 좋았던 점", "캠핑 의자 직접 가본 캠핑장", "유모차 비교 사용 후기와 가격", "커피머신 도전기",
        "스마트워치 hands-on", "iPhone 16 unboxing", "Galaxy S25 review",
    )

    def test_review_style_keywords_leave_no_ending_or_particle_fragment(self):
        fragments = {"어요", "더니", "와", "과", "를", "을", "이", "가", "은", "는", "의", "도", "에", "랑", "나", "습니다", "는데", "어요?", "고"}
        for keyword in self.REVIEW_STYLE:
            with self.subTest(keyword=keyword):
                stripped = pt.strip_premise(keyword)
                self.assertTrue(stripped, keyword)
                words = stripped.split()
                self.assertFalse(set(words) & fragments, stripped)
                self.assertFalse(words[-1].endswith(("어요", "더니", "습니다", "는데")), stripped)
                self.assertNotIn("  ", stripped)
                for word in ("후기", "리뷰", "review", "써봤", "다녀왔", "언박싱", "unboxing", "hands-on", "시승기", "시착기", "체험단", "먹어봤", "써보니"):
                    self.assertNotIn(word, stripped.casefold(), stripped)

    def test_strip_premise_never_leaves_a_claim_word_that_it_knows(self):
        for _kind, topics in PremiseTest.CASES:
            for topic in topics:
                with self.subTest(topic=topic):
                    stripped = pt.strip_premise(topic)
                    self.assertEqual(claims.find_violations([stripped]), (), stripped)


if __name__ == "__main__":
    unittest.main()
