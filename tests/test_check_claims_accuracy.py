"""'지어내지 않기' 검사 정확도 2차(묶음 c2) 시험 — 독립 검증이 잰 기준선(미탐 34%·오탐 8%·관용·요청 문장 오탐 31%·질문 우회 20/20 통과·후기 전제 판정 오인)을 고친 규칙이 예문 앞에서 그대로 서 있는지 지킨다.

지키는 것:
  1) 개발용 예문(`claims_accuracy_examples.py`) — 위반은 걸리고, 평범한 문장·부탁·조건·관용 문장은 아무것도 안 걸리고, 확인 권장은 그 분류가 나오되 위반은 아니고, 질문으로 위장한 경험 단정은 걸리고, 독자에게 묻는 진짜 질문은 통과한다.
  2) 새로 만든 규칙 하나하나(말투 판정·1인칭 표지·'…해 보니' 일반화·표지 없는 과거형·따옴표 뒤 조사·조사 응답·방법 안내·확인 권장 보강·후기 전제 판정) — 걸리는 쪽과 지나가는 쪽을 둘 다 문장 전체로 비교한다.
  3) 정규식은 선형 시간이고 위반은 한 건도 버리지 않는다.
이 시험의 예문은 구현자가 규칙을 고치는 데 쓴 것이라 '개발용'이다 — 보류용 수치는 문서(README·D-33 ⑤)에 따로 적는다.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import claims_accuracy_examples as ex  # noqa: E402
from chanceblog_desktop.check import claims as cl  # noqa: E402
from chanceblog_desktop.content import post_types as pt  # noqa: E402


def violated(text):
    return {claim.category for claim in cl.find_violations(text)}


class DevelopmentExamplesTest(unittest.TestCase):
    def test_the_example_lists_are_big_enough_to_pin_the_rules(self):
        self.assertGreaterEqual(len(ex.VIOLATIONS), 150)
        self.assertGreaterEqual(len(ex.PASSES), 120)
        self.assertGreaterEqual(len(ex.TOLERATED), 90)
        self.assertGreaterEqual(len(ex.REVIEWS), 60)
        self.assertGreaterEqual(len(ex.QUESTION_BYPASS), 15)
        self.assertGreaterEqual(len(ex.QUESTION_REAL), 20)
        self.assertGreaterEqual(len(ex.REVIEW_TITLES), 20)
        self.assertGreaterEqual(len(ex.INFO_TITLES), 15)

    def test_every_experience_claim_is_a_violation(self):
        missed = [text for _, text in ex.VIOLATIONS if not cl.find_violations(text)]
        self.assertEqual(missed, [])

    def test_every_plain_sentence_finds_nothing_at_all(self):
        flagged = [(text, cl.find_claims(text)) for text in ex.PASSES if cl.find_claims(text)]
        self.assertEqual(flagged, [])

    def test_requests_conditions_and_idioms_are_not_violations(self):
        flagged = [(text, cl.find_violations(text)) for text in ex.TOLERATED if cl.find_violations(text)]
        self.assertEqual(flagged, [])

    def test_every_review_sentence_gets_its_category_and_is_never_a_violation(self):
        wrong = []
        for want, text in ex.REVIEWS:
            found = cl.find_claims(text)
            if want not in {claim.category for claim in found} or any(cl.is_violation(claim.category) for claim in found):
                wrong.append((want, text))
        self.assertEqual(wrong, [])

    def test_a_question_that_only_looks_like_one_is_still_a_violation(self):
        passed = [text for text in ex.QUESTION_BYPASS if not cl.find_violations(text)]
        self.assertEqual(passed, [])

    def test_a_real_question_to_the_reader_passes(self):
        flagged = [(text, cl.find_violations(text)) for text in ex.QUESTION_REAL if cl.find_violations(text)]
        self.assertEqual(flagged, [])

    def test_review_titles_are_premises_and_leave_no_fragment(self):
        for title in ex.REVIEW_TITLES:
            with self.subTest(title=title):
                self.assertIsNotNone(pt.premise_of(title, "키워드"))
                stripped = pt.strip_premise(title)
                self.assertTrue(stripped.strip())
                self.assertEqual(cl.find_violations([stripped]), ())
                self.assertFalse(any(word in stripped for word in ("후기", "리뷰", "訪問", "後記", "써봤", "써본", "써보니")), stripped)

    def test_review_titles_with_a_common_noun_tail_are_premises_and_leave_no_fragment(self):
        """c2-fix(H1) — 진짜 후기 제목 뒤에 사진·순위·점수·구성·광고·차이·형식·통계가 붙어도 후기다(앞 판은 33개 중 31개를 후기를 설명하는 글로 읽어 제목에 '후기' 가 그대로 남았다)."""
        self.assertGreaterEqual(len(ex.LIST_TAIL_REVIEW_TITLES), 30)
        for title in ex.LIST_TAIL_REVIEW_TITLES:
            with self.subTest(title=title):
                self.assertIsNotNone(pt.premise_of(title, "키워드"))
                stripped = pt.strip_premise(title)
                self.assertTrue(stripped.strip())
                self.assertEqual(cl.find_violations([stripped]), ())
                self.assertFalse(any(word in stripped for word in ("후기", "리뷰", "訪問", "後記", "써봤", "써본", "써보니")), stripped)

    def test_titles_about_reviews_are_not_review_premises(self):
        for title in ex.INFO_TITLES:
            with self.subTest(title=title):
                self.assertIsNone(pt.premise_of(title, "키워드"))

    def test_plain_titles_stay_exactly_as_they_were(self):
        for title in ex.PLAIN_TITLES:
            with self.subTest(title=title):
                self.assertIsNone(pt.premise_of(title, "키워드"))
                self.assertEqual(pt.strip_premise(title), title)


class MoodTest(unittest.TestCase):
    """문장의 말투 — 부탁·권유·다짐으로 끝나는 말과 독자에게 묻는 말은 겪은 일을 단정하지 않는다."""

    def test_a_request_with_a_modifier_form_passes(self):
        for text in ("써 본 느낌을 알려 주세요.", "다녀온 후기를 댓글로 남겨 주세요.", "직접 사용해 본 후에 결정하세요.", "써 본 뒤에는 솔직한 느낌을 꼭 공유할 생각이에요.", "먹어 본 뒤에 평가해 주시면 큰 도움이 됩니다.",
                     "다음에는 직접 가서 확인한 뒤 다시 정리해 보겠습니다.", "방문 후기를 쓰고 싶다면 직접 다녀온 뒤에 적는 것이 좋습니다.", "직접 방문하여 확인하시기 바랍니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_a_request_that_also_reports_a_past_event_is_still_a_violation(self):
        self.assertTrue(cl.find_violations("직접 써 본 소감을 정리해서 올렸고 만약 마음에 든다면 알려 주세요"))
        self.assertTrue(cl.find_violations("써 봤는데 좋았어요. 여러분도 써 보세요."))
        self.assertTrue(cl.find_violations("써 봤는데 좋았으니 여러분도 써 보세요."))
        self.assertTrue(cl.find_violations("써 보니 이 제품은 정말 추천합니다."))

    def test_a_question_to_the_reader_passes_but_a_disguised_claim_does_not(self):
        for text in ("써 보셨나요?", "써 보니 어떠셨나요?", "구매했는데 만족하시나요", "직접 써 봤을 때 어떠셨나요", "직접 써 본 느낌은 어떠셨나요?", "다녀오신 분 계신가요?"):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())
        for text in ("저는 직접 써 봤는데 정말 좋았죠?", "한 달 써 보니 정말 편했죠?", "직접 구매해서 써 봤는데 어떻게 생각하세요?", "어제 그 카페에 다녀왔는데, 분위기가 참 좋았죠?", "솔직히 저는 환불을 두 번이나 받았잖아요?",
                     "저는 직접 써 봤는데 어때요?", "어제 택배를 받아서 바로 뜯어봤거든요?"):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))

    def test_conditional_and_concessive_forms_are_not_claims(self):
        for text in ("방문했다고 해서 원하는 결과가 보장되는 것은 아닙니다.", "구매했다고 해서 모든 기능을 바로 쓸 수 있는 것은 아닙니다.", "아무리 열어 봤자 소용이 없습니다.", "써 본 사람마다 느낌이 다를 수 있습니다.",
                     "구독해 보고 마음에 들지 않으면 언제든 해지할 수 있습니다.", "구입했다면 영수증을 꼭 보관해 두세요.", "방문했을 때 확인해야 할 항목을 체크리스트로 만들어 두었습니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_the_condition_marker_after_a_claim_word_must_be_close_to_it(self):
        self.assertEqual(cl.find_violations("방문했을 경우 영수증을 챙기세요."), ())                     # '을경우' — 하지 않은 일을 안내하는 말
        self.assertTrue(cl.find_violations("다녀왔는데 좋았습니다 정말 만족스러운 하루였어요 방문했을 경우를 대비해 적어 둡니다"))

    def test_a_how_to_about_writing_a_review_is_not_a_report_but_a_case_name_is_still_found(self):
        self.assertEqual(cl.find_violations("다녀온 후기를 남기는 방법은 아래에 정리해 두었습니다."), ())
        self.assertTrue(cl.find_violations("A씨는 이 방법을 따랐습니다."))
        self.assertTrue(cl.find_violations("회사 동료 B씨는 이 방법으로 합격했습니다."))

    def test_the_relative_clause_of_something_someone_told_is_not_a_report(self):
        self.assertEqual(cl.find_violations("지인이 알려 준 정보는 한 번 더 확인합니다."), ())
        self.assertTrue(cl.find_violations("지인이 알려줬고 바로 샀어요."))

    def test_a_quoted_review_followed_by_a_particle_is_a_mention(self):
        for text in ('"다녀왔는데 별로였다"는 한 줄 평은 개인 취향일 수 있습니다.', "'직접 써 봤는데 좋았어요'라는 후기는 믿기 어렵습니다.", "('…하곤 했어요')는 알려 둔 한계입니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())
        self.assertTrue(cl.find_violations('"좋아요"라고 적었지만 직접 써 봤는데 별로였어요.'))

    def test_a_survey_answer_is_not_a_conversation_the_writer_had(self):
        self.assertEqual(violated("설문에 참여한 부모의 72%가 영상 시청 시간 제한이 필요하다고 답했어요."), set())
        self.assertIn(cl.DIALOGUE, violated("상담원이 필요하다고 답했어요."))

    def test_the_mood_check_never_hides_a_violation_behind_a_long_text(self):
        text = "써 본 느낌을 알려 주세요. " * 200 + "저는 직접 써 봤는데 정말 좋았어요."
        self.assertEqual(len(cl.find_violations(text)), 2, "마지막 문장의 위반 둘이 그대로 나온다(사용·체감)")


class BroaderRulesTest(unittest.TestCase):
    def test_a_tried_form_of_any_verb_is_an_experience_but_a_look_up_is_not(self):
        for text in ("설치해 보니 금방 끝났습니다.", "여러 번 반복해 실험해 봤습니다.", "투어에 참여해 보니 설명이 친절했어요.", "렌즈를 갈아 끼우고 찍어 보니 선명도가 달랐어요.", "강릉 바닷가 펜션에 묵어 보니 조용했습니다."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))
        for text in ("공식 자료를 확인해 보니 지원 기기가 표에 정리되어 있었습니다.", "두 제품의 차이를 비교해 봤습니다.", "필요한 서류를 알아보니 세 가지였습니다.", "이 글에서는 선택 기준을 정리해 봤습니다.", "두 제품의 차이를 표로 만들어 보았습니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_a_first_person_marker_with_a_past_statement_is_an_experience_but_a_word_inside_another_word_is_not(self):
        self.assertTrue(cl.find_violations("저는 점심시간에 국숫집에 들러 줄을 서 봤어요."))
        self.assertTrue(cl.find_violations("제가 받은 배당금은 바로 재투자했다."))
        self.assertEqual(cl.find_violations("이 글은 끝나는 방식을 설명했습니다."), (), "'끝나는' 속의 '나는' 은 글쓴이가 아니다")
        later = cl.find_violations("끝나는 길에 국숫집 줄을 섰어요 저는 일찍 갔어요.")
        self.assertEqual([claim.word for claim in later if claim.word.startswith("저는")], ["저는일찍갔어요"], "앞의 '나는' 은 낱말 가운데라 건너뛰고 뒤의 '저는' 은 잡는다")
        self.assertEqual(cl.find_violations("저는 이 글에서 두 가지 방법을 비교했습니다."), ())
        self.assertEqual(cl.find_violations("저는 아직 이 제품을 써 보지 못했습니다."), ())
        self.assertEqual(cl.find_violations("저는 직접 써 보지 않았습니다."), ())

    def test_a_past_statement_in_a_casual_ending_needs_a_personal_signal(self):
        self.assertTrue(cl.find_violations("정말 놀랐어요."))
        self.assertTrue(cl.find_violations("아침마다 이 세럼을 발랐더니 피부톤이 환해졌어요."))
        for text in ("연구팀이 새로운 소재를 개발했어요.", "이 마을은 오래전부터 도자기로 유명했어요.", "정부가 새로운 지원 정책을 발표했습니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_a_daily_life_verb_without_a_marker_is_an_experience_but_a_participle_of_it_is_not(self):
        self.assertTrue(cl.find_violations("주말에 제주 협재해변을 걸었는데 물이 정말 맑았습니다."))
        self.assertTrue(cl.find_violations("렌터카를 빌려서 해안도로를 따라 달렸습니다."))
        self.assertEqual(cl.find_violations("이 기능만 건너뛰었습니다."), (), "'건너뛰었' 은 달린 것이 아니다")
        self.assertEqual(cl.find_violations("끝없이 기다렸다가 이어서 올립니다."), (), "'-었다가' 는 끝맺은 과거형이 아니다")

    def test_a_negated_quality_is_an_experience_but_a_negated_action_is_not(self):
        self.assertTrue(cl.find_violations("가방 무게가 부담스럽지 않았어요."))
        self.assertTrue(cl.find_violations("한겨울에도 하나도 춥지 않았습니다."))
        self.assertEqual(cl.find_violations("구매하지 않았습니다."), ())
        self.assertEqual(cl.find_violations("다녀온 적이 없는 곳이라 후기 형식으로는 쓰지 않았습니다."), ())

    def test_income_and_dialogue_and_case_forms(self):
        for text in ("저는 블로그 광고 수익으로 커피값을 벌었음.", "이번 달 수익이 처음으로 십만 원을 넘었어요.", "첫 정산금이 통장에 들어왔습니다.", "점원이 신제품이라며 시향지를 건네줬습니다.",
                     "이삿날 포장이사 팀이 짐을 꼼꼼하게 옮겨 주셨어요.", "후배 박군은 이 방법으로 자격증을 땄습니다.", "친구 지연이는 이 크림을 바르고 트러블이 올라왔습니다.", "저희 매장에 오신 한 손님은 영수증을 잃어버려서 곤란해하셨습니다.",
                     "I asked the barista about the beans and she recommended a lighter roast.", "My friend Jisoo used the same card abroad and got charged a hidden fee."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))
        self.assertEqual(cl.find_violations("수익이 늘어날 수 있습니다."), (), "앞날의 말은 겪은 일이 아니다")

    def test_the_relative_particle_forms_of_a_modifier_stay_tolerated_for_every_stem(self):
        for stem in ("써", "먹어", "입어", "발라", "설치해", "다녀"):
            for tail in (" 본 느낌을 알려 주세요.", " 본 뒤에 결정하세요."):
                text = stem + tail
                with self.subTest(text=text):
                    self.assertEqual(cl.find_violations(text), ())


class FoundByTheMutationReviewTest(unittest.TestCase):
    def test_a_letter_pair_inside_the_day_before_yesterday_is_not_my_friend(self):
        self.assertEqual(cl.find_violations("어제 친구에게 전화를 걸어 보기로 했다."), ())
        self.assertEqual(cl.find_violations("그제 지인에게 연락해 둘 예정입니다."), ())
        self.assertTrue(cl.find_violations("제 친구가 이 카페를 추천해 줬어요."))
        self.assertTrue(cl.find_violations("제 지인은 이 방법으로 합격했습니다."))

    def test_a_report_word_is_not_a_tried_verb_when_the_title_is_stripped(self):
        self.assertEqual(pt.strip_premise("시장조사보고서 작성 후기"), "시장조사보고서 작성")
        self.assertEqual(pt.strip_premise("연구 보고서 작성 후기"), "연구 보고서 작성")
        self.assertEqual(pt.strip_premise("노트북 앉아 보고 고른 이유"), "노트북 고른 이유")


class ReviewValuesTest(unittest.TestCase):
    def test_new_forms_of_prices_times_dates_and_statistics(self):
        cases = (
            (cl.TIME, "역에서 걸어서 10분 거리입니다."), (cl.TIME, "조리 시간은 약 25분입니다."), (cl.TIME, "대기 시간이 40분 안팎입니다."), (cl.TIME, "배송은 보통 이틀 만에 도착합니다."), (cl.TIME, "충전은 한 시간 반이면 끝납니다."),
            (cl.TIME, "새벽 6시에 문을 엽니다."), (cl.TIME, "무료 체험 기간은 14일이다."), (cl.TIME, "보증은 3개월간 유지됩니다."),
            (cl.DATE, "다음 달 5일에 업데이트가 예정되어 있습니다."), (cl.DATE, "하반기에 새 모델이 나온다는 소식이 있습니다."), (cl.DATE, "공식 발표는 3월 둘째 주에 있었다."), (cl.DATE, "접수는 3월 초부터 시작됩니다."),
            (cl.STAT, "국내 사용자는 약 300만 명으로 추산됩니다."), (cl.STAT, "통계청 자료를 보면 1인 가구가 늘고 있습니다."), (cl.STAT, "판매량이 지난해보다 두 배 늘었다고 합니다."), (cl.STAT, "평점은 5점 만점에 4.6점입니다."),
            (cl.STAT, "한국소비자원 발표에 따라 개선 권고가 나왔습니다."), (cl.STAT, "불량률이 1.2% 수준입니다."), (cl.STAT, "과반수가 찬성했습니다."), (cl.STAT, "주가가 반토막이 났습니다."),
            (cl.PRICE, "한 개에 만 원씩 받습니다."), (cl.PRICE, "한 장에 만 원짜리입니다."), (cl.PRICE, "한 잔에 천 원짜리입니다."),
        )
        for want, text in cases:
            with self.subTest(text=text):
                found = cl.find_claims(text)
                self.assertIn(want, {claim.category for claim in found})
                self.assertFalse(any(cl.is_violation(claim.category) for claim in found))

    def test_an_ordinary_period_phrase_is_not_a_review(self):
        for text in ("일주일 동안 사용할 수 있는 무료 체험이 있습니다.", "한 달 동안 환불이 가능한지 확인합니다.", "점유율은 전년 대비 높아졌습니다."):
            with self.subTest(text=text):
                self.assertEqual([claim for claim in cl.find_claims(text) if claim.category == cl.TIME and "동안" in claim.word], [])

    def test_two_times_is_not_a_body_part(self):
        self.assertEqual(cl.find_violations("점유율은 전년보다 세 배 늘었습니다."), ())


class ReviewPremiseTest(unittest.TestCase):
    def test_titles_that_say_what_the_writer_tried_are_premises_and_lose_the_verb(self):
        for title, expected in (("아이와 키즈카페 다녀와 보니", "아이와 키즈카페"), ("캠핑 의자 직접 앉아 보고 고른 이유", "캠핑 의자 고른 이유"), ("수영장 강습 등록해 보니", "수영장 강습"),
                                ("치과 임플란트 상담 받아 본 후기", "치과 임플란트 상담"), ("구독 서비스 해지까지 해 본 과정", "구독 서비스 해지"), ("서촌 한옥 카페 訪問 後記", "서촌 한옥 카페"),
                                ("에어프라이어 써본 결과", "에어프라이어"), ("신형 아이폰으로 바꿔 보니", "신형 아이폰")):
            with self.subTest(title=title):
                self.assertIsNotNone(pt.premise_of(title, "키워드"))
                self.assertEqual(pt.strip_premise(title), expected)

    def test_a_look_up_or_a_report_title_is_not_a_trial(self):
        for title in ("가격 비교해 본 결과 정리", "필요한 서류 알아본 방법", "연구 보고서 작성 요령", "영화 대본 쓰는 법", "노트북 램 업그레이드 가이드"):
            with self.subTest(title=title):
                self.assertIsNone(pt.premise_of(title, "키워드"))

    def test_a_guide_about_reviews_is_not_a_review_but_a_review_is(self):
        for title in ("블로그 후기 글 잘 쓰는 법", "맛집 후기 믿어도 될까 가려 읽는 법", "구매 후기 조작 구별법", "여행 후기 사진 잘 찍는 방법", "체험단 후기 쓸 때 꼭 밝혀야 하는 문구", "앱 리뷰 점수가 이렇게 매겨집니다"):
            with self.subTest(title=title):
                self.assertIsNone(pt.premise_of(title, "키워드"))
        for title in ("협찬 후기", "무선청소기 사용 후기 쓰는 법 직접 써보니", "구매 후기와 장단점"):
            with self.subTest(title=title):
                self.assertIsNotNone(pt.premise_of(title, "키워드"))

    def test_a_noun_that_hides_a_verb_stem_is_still_stripped_by_the_word_list(self):
        self.assertEqual(pt.strip_premise("노트북구매해본"), "노트북")
        self.assertEqual(pt.strip_premise("청소기써본후기"), "청소기")

    def test_the_sharing_of_the_stem_lists_is_one_source(self):
        self.assertIs(pt.COGNITIVE_STEMS, cl.COGNITIVE_STEMS)
        self.assertIs(pt.NEUTRAL_STEMS, cl.NEUTRAL_STEMS)


class LinearTimeTest(unittest.TestCase):
    def assert_fast(self, text, limit=6.0):
        started = time.perf_counter()
        cl.find_claims(text)
        self.assertLess(time.perf_counter() - started, limit, f"{len(text)}자")

    def test_the_new_rules_are_linear_on_adversarial_texts(self):
        for text in ("해" * 300_000, "해봤 " * 100_000, "제가 " * 100_000, "나는 끝나는 떠나는 " * 30_000, "저는 가나다라마바사 봤습니다만 " * 15_000, "구경하고 왔다 " * 30_000, "했더니 " * 60_000,
                     "설문 응답자 72% 가 답했습니다 " * 15_000, "다녀온 후기 " * 40_000, "써 보니 " * 50_000, "좋았어요 " * 60_000 + "?", "써 본 느낌 " * 40_000 + "알려 주세요"):
            self.assert_fast(text)

    def test_the_ratio_between_nine_times_and_three_times_the_input_stays_near_three(self):
        def best(text):
            result = 9.0
            for _ in range(3):
                started = time.perf_counter()
                cl.find_violations(text)
                result = min(result, time.perf_counter() - started)
            return result
        for unit in ("제가 가나다라마바사 ", "해봤 ", "써 본 느낌 알려 주세요 ", "저는 점심에 국숫집에 들러 줄을 섰어요 "):
            small, big = best(unit * 3_000), best(unit * 27_000)
            with self.subTest(unit=unit):
                self.assertLess(big / max(small, 1e-4), 20, "9배 입력에 시간이 20배를 넘으면 선형이 아니다(잡음을 넉넉히 둔 상한)")


if __name__ == "__main__":
    unittest.main()
