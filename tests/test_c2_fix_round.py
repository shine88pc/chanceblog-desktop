"""'지어내지 않기' 검사 정확도 2차(c2)를 독립 검증한 뒤의 수정 라운드(c2-fix) 시험 — 검증이 찾은 '기준선이 막던 것이 새로 통과하는' 두 건을 닫은 규칙이 그대로 서 있는지 지킨다.

H1 후기 전제 판정: '방문 후기 사진 모음'·'구매 후기 순위' 처럼 진짜 후기 제목 꼬리에 흔한 명사가 붙으면 후기다(앞 판은 설명 글로 읽어 제목에 '후기' 가 그대로 남았다).
H2 현재형 단정 + 부탁 꼬리: '직접 써 본 결과 아주 편합니다, 댓글 남겨 주세요' 는 부탁이 아니라 겪은 일을 단정하고 부탁을 덧붙인 말이다(앞 판은 꾸미는 낱말('써 본')을 부탁이 있으면 무조건 지나가게 했다).
  · 부탁 끝말 앞에 단정하는 서술어(…합니다·…이니·…라서·…해요)가 끼면 꾸미는 낱말을 면제하지 않는다.
  · 평가·짐작·추천 끝말(…좋습니다·…수 있습니다·…것 같아요·…권합니다)은 안내 틀('…하는 것이 좋습니다'·'…하면 됩니다')이 아니면 독자에게 하는 말이 아니라 단정이다 — 주어를 줄인 '써 본 결과 만족할 수 있습니다' 도 걸린다. 높임 '…남기실 수 있습니다' 만 1인칭·때 표지가 없을 때 독자 말이다.
  · '하면·하시면·할 때…' 같은 조건 표지도 앞에 단정이 끼어 있으면(…편합니다 궁금하시면 …) 조건이 아니다. 따옴표 뒤의 '는·도·란' 도 글쓴이가 자기 말이라 가리키면 가리키는 말이 아니다.
이 시험의 문장은 c2-fix 구현자가 새로 쓴 것이다 — 기대값은 코드에서 베끼지 않았고, 문장 전체의 분류 튜플을 견준다. 네트워크·파일 없이 돈다.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.check import claims as cl  # noqa: E402
from chanceblog_desktop.content import draft_plan as dp  # noqa: E402
from chanceblog_desktop.content import post_types as pt  # noqa: E402
from chanceblog_desktop.content.candidates import Candidate  # noqa: E402
from chanceblog_desktop.content.profiles import POST_TYPES  # noqa: E402

USE, VISIT = cl.EXPERIENCE_USE, cl.EXPERIENCE_VISIT

# 겪은 일을 현재형으로 단정하는 말(꾸미는 낱말 '써 본·다녀온·구매한' + 서술어) — 이 끝에 부탁이 붙어도 겪은 일의 단정이다
CLAIM_STEMS = (
    "직접 써 본 결과 배터리가 이틀을 갑니다", "직접 먹어 본 결과 국물이 깔끔합니다", "제가 직접 구매한 제품이라 품질은 확실합니다", "직접 다녀온 곳이라 분위기는 제가 보증합니다",
    "제가 직접 입어 본 옷이니 사이즈 걱정은 없습니다", "제가 직접 가 본 식당이라 메뉴 추천이 정확해요", "직접 사용해 본 소감은 만족입니다", "직접 체험해 본 결과를 바탕으로 말씀드립니다",
    "직접 써 본 결과 만족스러우니", "제가 직접 설치한 방법을 알려 드립니다", "직접 해 본 방법이라 효과가 확실합니다", "직접 써 본 결과 화면이 선명해서 좋습니다",
)
REQUEST_TAILS = ("", ", 댓글 남겨 주세요.", " 믿고 보세요.", " 참고해 주세요.", " 구독 눌러 주세요.", " 궁금하시면 물어보세요.", ", 도움이 되시길 바랍니다.", " 많이 이용해 주세요.", " 의견 부탁드립니다.", " 한번 써 보세요.")


def kinds(text):
    return tuple(claim.category for claim in cl.find_violations(text))


class ClaimWithARequestTailTest(unittest.TestCase):
    """H2 — 겪은 일을 단정한 말에 부탁·권유 꼬리가 붙어도 위반이다(기준선이 걸던 것을 새 판도 건다)."""

    def test_every_claim_stem_with_every_request_tail_is_a_violation(self):
        for stem in CLAIM_STEMS:
            for tail in REQUEST_TAILS:
                text = stem + (tail if tail else ".")
                with self.subTest(text=text):
                    self.assertTrue(cl.find_violations(text), text)

    def test_a_claim_that_ends_with_an_assessment_instead_of_a_request_is_a_violation(self):
        for text in ("직접 써 본 결과 화면이 선명해서 좋습니다.", "직접 다녀온 곳이라 서비스가 좋아요.", "직접 써 본 결과 오래 쓸 수 있습니다.", "제가 직접 먹어 본 곳이라 추천하고 싶은 것 같아요.",
                     "직접 써 본 결과 소음이 거의 없는 것 같습니다.", "제가 써 본 결과 가격 대비 성능이 좋습니다."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_the_claim_word_is_what_is_reported_not_the_request(self):
        found = cl.find_violations("직접 써 본 결과 아주 편합니다, 댓글 남겨 주세요.")
        self.assertEqual([claim.category for claim in found], [USE])
        self.assertEqual(found[0].word, "직접써본")
        found = cl.find_violations("직접 다녀온 곳이니 참고하세요.")
        self.assertEqual([(claim.category, claim.word) for claim in found], [(VISIT, "직접다녀온")])

    def test_a_request_alone_with_a_modifier_form_still_passes(self):
        for text in ("써 본 느낌을 알려 주세요.", "다녀온 후기를 남겨 주세요.", "직접 사용해 본 후에 결정하세요.", "직접 다녀온 곳이 어디인지 알려 주세요.", "먹어 본 뒤에 평가해 주시면 큰 도움이 됩니다.",
                     "다음에는 직접 가서 확인한 뒤 다시 정리해 보겠습니다.", "직접 써 본 분의 평가는 언제든 환영이에요.", "방문 후기를 쓰고 싶다면 직접 다녀온 뒤에 적는 것이 좋습니다."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)

    def test_an_assessment_ending_is_an_assertion_unless_it_is_an_advice_frame(self):
        for text in ("써 본 결과 만족할 수 있습니다.", "써 본 느낌이 좋습니다.", "써 본 결과 배터리가 오래 가는 것 같아요.", "써 본 결과 이 제품을 권합니다.", "직접 써 본 결과 화면이 선명해서 좋습니다."):
            with self.subTest(text=text):
                self.assertTrue(kinds(text), "주어를 줄인 경험 단정도 평가 끝말을 부탁으로 보지 않는다(기준선도 걸었다)")
        for text in ("직접 써 본 뒤에 결정하는 것이 좋습니다.", "써 본 뒤에 결정하면 됩니다.", "직접 써 본 뒤에 결정하시길 권합니다.", "써 본 뒤에 후기를 쓰는 편이 좋습니다.", "직접 다녀온 뒤에 적는 게 좋아요.", "직접 써 본 뒤에 후기를 쓰면 좋습니다.", "직접 써 본 뒤에 결정하는 것이 더 좋습니다.", "직접 써 본 뒤에 결정하는 것이 가장 좋습니다.", "직접 다녀온 뒤에 적는 게 훨씬 좋아요.", "써 본 뒤에 후기를 쓰는 편이 제일 좋습니다.", "직접 써 본 뒤에 결정하기를 권합니다.", "직접 써 본 뒤에 결정하는 것을 권장합니다.", "써 본 뒤에 결정하시길 권해요."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), "'…하는 것이 좋습니다'·'…하면 됩니다'·'…하시길 권합니다' 는 독자에게 하는 안내다")

    def test_a_question_word_ends_the_part_that_is_checked_for_an_assertion(self):
        self.assertEqual(kinds("직접 다녀온 곳이 어디예요?"), ())
        self.assertEqual(kinds("직접 써 본 결과 어떠셨는지 알려 주세요."), ())
        self.assertTrue(kinds("직접 써 본 결과 아주 편합니다 어떠셨는지 알려 주세요."))

    def test_an_assertion_after_the_request_marker_does_not_count(self):
        self.assertEqual(kinds("써 본 느낌을 알려 주시면 큰 도움이 됩니다."), ())
        self.assertEqual(kinds("직접 사용해 본 소감을 남겨 주시면 감사합니다."), ())

    def test_a_how_to_noun_after_a_modifier_form_is_not_a_guide(self):
        self.assertTrue(kinds("제가 직접 설치한 방법을 알려 드립니다, 댓글 남겨 주세요."))
        self.assertEqual(kinds("다녀온 후기를 남기는 방법은 아래에 정리해 두었습니다."), ())


class ConditionGuardWithAnAssertionBetweenTest(unittest.TestCase):
    """H2 두 번째 길 — '하면·하시면·할 때·하실 때·하기 전' 이 낱말 바로 뒤의 조건이면 가드이고, 단정한 말 뒤에 붙은 '궁금하시면 …' 이면 가드가 아니다."""

    GUARDS = ("하면", "하시면", "할때", "하실때", "하기전")

    def test_a_condition_right_after_the_claim_word_is_a_guard(self):
        for guard in self.GUARDS:
            text = f"써 보니 별로라고 {guard} 환불해 드립니다"
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)

    def test_a_condition_behind_a_stated_claim_is_no_guard(self):
        for guard in self.GUARDS:
            text = f"직접 써 본 결과 아주 편합니다 궁금{guard} 물어보세요"
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (USE,), text)

    def test_an_older_guard_word_behind_a_stated_claim_is_no_guard_either(self):
        self.assertEqual(kinds("직접 써 본 결과 아주 편합니다 도움이 되셨으면 공감 눌러 주세요"), (USE,))
        self.assertEqual(kinds("직접 써 본 결과 아주 편합니다 궁금하다면 물어보세요"), (USE,))

    def test_a_condition_marker_is_still_a_guard_for_a_negation_and_a_conditional(self):
        for text in ("직접 써 본 적이 없다면 후기를 쓰지 않습니다.", "방문했다면 영수증을 보관하세요.", "직접 써 본 사람이라면 누구나 알 수 있습니다.", "써 본 적이 없는 제품은 설명서 기준으로 적습니다."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)


class QuoteFollowedByAParticleTest(unittest.TestCase):
    """H2 세 번째 길 — 따옴표로 묶은 말 뒤의 '는·도·란' 은 그 말을 가리키지만, 글쓴이가 자기 말·자기 후기라고 가리키면 겪은 일을 말하는 것이다."""

    def test_a_quote_the_writer_calls_his_own_is_a_claim(self):
        for text in ('"직접 써 봤는데 정말 좋았어요"는 제가 한 말입니다.', "'어제 다녀왔는데 좋았어요'도 제 솔직한 후기입니다.", '저는 "직접 먹어 봤는데 맛있었어요"란 말을 하고 싶습니다.',
                     '"직접 써 봤는데 정말 편했어요"는 저의 후기입니다.', '나는 "써 보니 정말 좋았어요"는 말을 자주 합니다.', "'어제다녀왔는데좋았어요'도제솔직한후기입니다."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_a_quote_that_is_only_pointed_at_still_passes(self):
        for text in ('"다녀왔는데 별로였다"는 한 줄 평은 개인 취향일 수 있습니다.', "'직접 써 봤는데 좋았어요'라는 후기는 믿기 어렵습니다.", "('…하곤 했어요')는 알려 둔 한계입니다.", '"직접 써 봤는데 좋았어요"도 흔한 후기 문구입니다.'):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)

    def test_the_first_person_must_be_close_to_the_quote(self):
        far = '"직접 써 봤는데 정말 좋았어요"는 흔히 보는 한 줄 평이라 이 글에서는 그대로 쓰지 않습니다. 저는 이 제품을 써 보지 않았습니다.'
        self.assertEqual(kinds(far), ())


class ReviewTitlesThroughTheDraftPlanTest(unittest.TestCase):
    """H1 — 진짜 `draft plan` 길: 후기 제목에 흔한 명사 꼬리가 붙어도 안전 대체가 일어나고 제목·소제목에 후기 낱말이 남지 않는다."""

    def test_review_titles_with_a_common_noun_tail_are_replaced_and_leave_no_review_word(self):
        titles = ("성수동 카페 방문 후기 사진 모음", "홍대 맛집 방문 후기 순위", "노트북 구매 후기 점수 정리", "헬스장 이용 후기 사진 포함", "화장품 사용 후기 광고 없음", "수영장 방문 후기 광고 아님",
                  "운동화 구매 후기 차이점", "커피머신 사용 후기 통계", "유럽 여행 후기 일정 구성", "태블릿 사용 후기 비교 차이")
        for title in titles:
            with self.subTest(title=title):
                candidate = Candidate.new(title, title.split(" ")[0], ("naver_a",), post_type=POST_TYPES[0], now="2026-11-02T03:00:00Z")
                plan = dp.build_plan(candidate, None, None, today="2026-11-03")
                self.assertIsNotNone(plan.replaced, "안전 대체를 했다는 안내가 있어야 한다")
                shown = " ".join([plan.topic, *plan.titles, *plan.subheadings])
                self.assertNotIn("후기", shown)

    def test_a_guide_about_reviews_is_left_alone(self):
        for title in ("후기 사진 고르는 요령", "리뷰 점수 계산 원리", "별점 순위가 정해지는 방식", "체험단이란 무엇일까", "후기 광고 표기 규정 정리"):
            with self.subTest(title=title):
                self.assertIsNone(pt.premise_of(title, "키워드"))


class AssertionWindowAndEndingsTest(unittest.TestCase):
    """단정하는 서술어를 찾는 창(낱말 뒤 60글자·낱말 앞 12글자)과 서술어 어미 하나하나 — 어미 하나만 이유가 되는 문장으로 고정한다(앞 변이 점검에서 살아남은 곳)."""

    FILLER = "가나다라마바사아자차카타파하"                     # 14글자 — 서술어도 부탁 낱말도 아니다

    def test_every_ending_of_a_stated_claim_alone_keeps_the_request_from_hiding_it(self):
        for ending in ("편합니다", "맛있어요", "괜찮아요", "편해요", "쉬워요", "정말 대단하네요", "훌륭하군요", "좋지요", "아주 편하죠", "제품이에요", "제 최애예요", "품질이 우수하므로", "속도가 빨라서", "가성비가 좋으니", "믿을 만하니까", "가볍고 튼튼하니", "가격이 싸니까", "소리가 크니까",
                       "사이즈가 크게 나오니", "믿고 가니", "금방 되니", "겉으로 보니", "자세히 말씀드리니", "소리가 크니", "가격이 싸니", "잘 쓰니", "표정이 예쁘니", "속도가 빠르니"):
            text = f"직접 써 본 결과 {ending}, 댓글 남겨 주세요."
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_the_window_is_exactly_sixty_syllables_after_the_word(self):
        seen = "직접 써 본" + (self.FILLER * 5)[:56] + "편합니다 댓글 남겨 주세요."              # 서술어가 낱말 뒤 60글자 안에서 끝난다
        unseen = "직접 써 본" + (self.FILLER * 5)[:57] + "편합니다 댓글 남겨 주세요."            # 한 글자 더 멀다
        self.assertTrue(cl.find_violations(seen), seen)
        self.assertEqual(kinds(unseen), (), unseen)

    def test_a_clause_ending_that_is_part_of_a_longer_word_does_not_count(self):
        self.assertEqual(kinds("직접 써 본 사람이라면 누구나 느낌을 알려 주세요."), ())
        self.assertEqual(kinds("직접 써 본 느낌이라는 말을 남겨 주세요."), ())
        self.assertEqual(kinds("직접 써 본 느낌이라고 해서 댓글 남겨 주세요."), ())
        self.assertEqual(kinds("직접 다녀온 후기를 매니저에게 알려 주세요."), (), "'매니저' 속 '니' 는 이유를 잇는 어미가 아니다")
        self.assertEqual(kinds("직접 써 본 후기를 어머니께 보여 주세요."), (), "'어머니' 속 '니' 도 아니다")

    def test_an_opinion_or_a_recommendation_after_a_first_person_trial_is_a_claim_but_a_plan_or_an_advice_is_not(self):
        self.assertTrue(kinds("직접 써 본 결과 정말 좋다는 생각입니다."), "'…다는 생각입니다' 는 의견이다")
        self.assertEqual(kinds("직접 써 본 뒤에 결정할 생각입니다."), (), "'…할 생각입니다' 는 앞으로의 뜻이다")
        self.assertTrue(kinds("직접 써 본 결과 이 제품을 권합니다."), "겪은 일을 바탕으로 하는 추천")
        self.assertEqual(kinds("직접 써 본 뒤에 결정하시길 권합니다."), (), "'…하시길 권합니다' 는 안내다")

    def test_the_claim_is_seen_when_it_is_up_to_sixty_syllables_after_the_word_but_not_beyond(self):
        near = "직접 써 본 결과 " + self.FILLER * 3 + "가 편합니다, 댓글 남겨 주세요."            # 서술어가 낱말 뒤 약 45글자
        far = "직접 써 본 결과 " + self.FILLER * 5 + "가 편합니다, 댓글 남겨 주세요."             # 서술어가 낱말 뒤 약 75글자
        self.assertTrue(cl.find_violations(near), near)
        self.assertEqual(kinds(far), (), "창 밖의 서술어는 보지 않는다(긴 글에서 낱말마다 끝까지 훑지 않으려는 대가 — 알려 둔 한계)")


class HonorificAbilityAndFirstPersonMarkTest(unittest.TestCase):
    """높임 '…남기실 수 있습니다' 는 독자에게 하는 말이라 지나가지만, 1인칭·때 표지가 낱말 안이나 앞 12글자 안에 있으면('직접 써 본 결과 만족하실 수 있습니다') 겪은 일을 바탕으로 한 단정이다."""

    def test_an_honorific_ability_is_for_the_reader(self):
        for text in ("다녀온 후기를 남기실 수 있습니다.", "다녀온 후기를 남기실 수 있어요.", "다녀온 후기를 남기실 수도 있습니다.", "다녀온 후기를 남기실 수도 있어요."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)

    def test_the_same_ending_after_a_first_person_trial_or_without_the_honorific_is_a_claim(self):
        for text in ("직접 써 본 결과 만족하실 수 있습니다.", "제가 써 본 결과 만족하실 수도 있습니다.", "써 본 결과 만족할 수 있습니다.", "써 본 결과 만족할 수도 있어요."):
            with self.subTest(text=text):
                self.assertTrue(kinds(text), text)

    def test_the_first_person_mark_reaches_ten_syllables_between_it_and_the_word(self):
        near = "저는 " + "가나다라마바사아자차" + "써 본 결과 만족하실 수 있습니다."          # 표지 끝과 낱말 사이 10글자(표지 포함 12글자 안)
        far = "저는 " + "가나다라마바사아자차카" + "써 본 결과 만족하실 수 있습니다."          # 11글자 — 표지가 아니다
        self.assertTrue(cl.find_violations(near), near)
        self.assertEqual(kinds(far), (), far)


class SmallListGapsTest(unittest.TestCase):
    """독립 검증자가 변이로 찾은 '낱말 목록의 항목 하나를 빼도 시험이 안 깨지는 곳' — 항목 하나만 이유가 되는 문장으로 고정한다(앞 변이 점검에서 살아남은 곳)."""

    def test_two_request_endings_alone_let_a_modifier_form_pass(self):
        self.assertEqual(kinds("다녀온 후기를 남겨 보세요."), (), "끝말 '보세요'")
        self.assertEqual(kinds("다녀온 후기를 남기기 바랍니다."), (), "끝말 '바랍니다'")

    def test_a_condition_that_names_the_case_guards_a_closed_form(self):
        self.assertEqual(kinds("써 보니 불편한 경우에는 환불해 드립니다."), (), "가드 '한경우'")
        self.assertTrue(kinds("써 보니 불편했고 그래서 환불해 드립니다."))

    def test_the_marker_before_a_saw_verb_reaches_sixteen_syllables_not_seventeen(self):
        sixteen = "가나다라마바사아자차카타파하거한"                  # 받침 있는 글자로 끝나 '이은 글자 + 봤' 규칙에 안 걸린다
        self.assertEqual(len(sixteen), 16)
        self.assertEqual(kinds("직접" + sixteen + "봤습니다."), (USE,))
        self.assertEqual(kinds("직접" + sixteen[:-1] + "너한" + "봤습니다."), ())

    def test_an_english_first_person_income_phrase(self):
        self.assertEqual(kinds("I got paid for this post last week."), (cl.EXPERIENCE_INCOME,))

    def test_a_daily_verb_alone_is_the_writers_day(self):
        self.assertEqual(kinds("점심을 먹었습니다."), (USE,))
        self.assertEqual(kinds("공원에서 산책했습니다."), (VISIT,))

    def test_we_as_the_subject_and_a_pharmacist_as_the_one_who_acted(self):
        self.assertEqual(kinds("저희는 오래된 집을 천천히 고쳤습니다."), (USE,))
        self.assertEqual(kinds("약사님이 복용량을 조절하셨습니다."), (cl.DIALOGUE,))

    def test_a_first_person_past_with_a_reason_ending_is_a_claim(self):
        self.assertEqual(kinds("저는 큰 목소리를 냈으니 이제 기다립니다."), (USE,), "과거 줄기 '냈' + 이은 어미 '으니'")
        self.assertEqual(kinds("저는 어제 시험을 쳤으니까 결과를 기다립니다."), (USE,), "'쳤으니까' 도 '으니' 로 이어 읽는다")

    def test_a_word_that_says_what_the_writer_tried_keeps_a_title_a_premise_even_next_to_a_guide_word(self):
        self.assertIsNotNone(pt.premise_of("후기 쓰는 법 직접 써본 팁", "키워드"))
        self.assertIsNone(pt.premise_of("후기 쓰는 법 팁", "키워드"))


class FalseAlarmsOfTheNewRulesTest(unittest.TestCase):
    """M1 — c2 가 새로 만든 오탐 묶음(해요체 정보 글·3인칭 기사체·흔한 안내문·부정 + 조사)의 원인을 고친 규칙. 걸려야 하는 쪽도 함께 지킨다(고침이 미탐을 늘리지 않게)."""

    def test_a_polite_past_about_a_thing_or_a_change_in_an_info_text_passes(self):
        for text in ("이번 개정으로 수수료가 낮아졌어요.", "지난해 이 지역 집값이 많이 올랐어요.", "새 요금제가 지난달에 나왔어요.", "가족 요금제가 새로 바뀌었어요.", "친구 추천 이벤트는 작년에 끝났어요.",
                     "훨씬 빨라졌어요.", "이번 업데이트에서 오류가 대부분 고쳐졌어요.", "완전히 새로운 방식으로 바뀌었어요.", "새 모델은 지난주에 발표됐어요."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)

    def test_the_same_polite_past_with_a_personal_mark_is_still_an_experience(self):
        for text in ("제가 써 보니 피부가 환해졌어요.", "오늘 아침 방이 환해졌어요.", "아이가 좋아해서 정말 놀랐어요.", "남편은 처음으로 직접 요리를 했어요.", "어제 정말 많이 걸었어요.", "친구와 함께 갔는데 줄이 길었어요."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_a_news_or_biography_sentence_with_a_third_person_subject_is_not_the_writers_day(self):
        for verb, text in (("나섰", "경찰이 실종자 수색에 나섰다."), ("맡았", "그는 위원회에서 간사 역할을 맡았다."), ("잃었", "그녀는 사고로 가족을 잃었다."), ("보냈", "그녀는 어린 시절을 해외에서 보냈습니다."),
                           ("배웠", "그는 대학원에서 통계학을 배웠습니다."), ("견뎠", "선수들은 혹독한 환경을 끝까지 견뎠다."), ("닦았", "연구진이 기술 기반을 닦았다."), ("입었", "정부는 피해 지역 복구에 나섰고 주민들은 큰 피해를 입었습니다.")):
            with self.subTest(verb=verb):
                self.assertEqual(kinds(text), (), text)

    def test_the_same_daily_verbs_without_a_third_person_subject_are_still_the_writers_day(self):
        for verb, text in (("나섰", "새벽에 혼자 산책에 나섰습니다."), ("맡았", "이번 달부터 반 모임 총무를 맡았습니다."), ("잃었", "지갑을 잃었습니다."), ("보냈", "주말을 집에서 보냈습니다."), ("배웠", "요리를 배웠습니다."),
                           ("견뎠", "무더위를 선풍기 하나로 견뎠습니다."), ("닦았", "신발을 깨끗이 닦았습니다."), ("입었", "새 패딩을 입었습니다."), ("시켰", "치킨을 시켰습니다."), ("달렸", "한강변을 달렸습니다.")):
            with self.subTest(verb=verb):
                self.assertTrue(cl.find_violations(text), text)

    def test_a_damage_idiom_and_a_causative_are_not_daily_verbs(self):
        for text in ("이 마을은 태풍으로 큰 피해를 입었습니다.", "회사는 큰 손실을 입었습니다.", "그 선수는 무릎에 부상을 입었습니다.", "산업 전반이 타격을 입었습니다.", "규제를 완화시켰습니다.", "새 엔진이 연비를 크게 향상시켰습니다.", "그는 평생 연구에 매달렸습니다."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)

    def test_a_third_person_subject_must_start_a_word_and_a_people_noun_needs_the_plural(self):
        self.assertTrue(cl.find_violations("그 이상으로 맛있게 먹었습니다."), "'그 이상' 속 '그이' 는 3인칭 주어가 아니다")
        self.assertTrue(cl.find_violations("사람이 많아서 한참 걸었습니다."), "'사람이' 는 복수가 아니라 3인칭 기사 주어로 보지 않는다")
        self.assertEqual(kinds("많은 사람들이 목숨을 잃었습니다."), ())
        self.assertEqual(kinds("선수는 힘든 훈련을 끝까지 견뎠습니다."), ())
        self.assertTrue(cl.find_violations("행사 총감독이 챙겨 준 간식을 먹었습니다."), "'총감독이' 속 '감독이' 는 낱말 가운데라 3인칭 주어 표지가 아니다")
        self.assertEqual(kinds("감독이 챙겨 준 간식을 먹었습니다."), (), "낱말이 감독이로 시작하면 3인칭 주어다")

    def test_a_hanging_verb_is_not_a_running_verb(self):
        self.assertEqual(kinds("철봉에 한참 매달렸습니다."), (), "'매달렸' 속 '달렸' 은 달린 것이 아니다")
        self.assertTrue(cl.find_violations("철봉 앞에서 한참 달렸습니다."))

    def test_advice_with_a_conversation_word_passes_but_a_recount_is_a_claim(self):
        for text in ("증상이 계속되면 의사와 상담하세요.", "접수 후에는 담당자와 통화로 일정을 확정해 주세요.", "상담을 받으려면 먼저 예약을 해야 합니다.", "채팅으로 문의하세요.", "전문가의 상담을 받으세요.", "약사와 상담하는 것이 좋습니다.",
                     "임산부는 반드시 의사와 상담한 뒤 드세요."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)
        for text in ("의사와 상담했는데 괜찮다고 했습니다.", "약사와 통화했습니다.", "직원님과 연락처를 교환했습니다.", "상담을 받았는데 친절했습니다.", "병원에서 상담을 받았습니다.", "의사와 상담하니 안심이 됐어요.", "상담을 받아 보니 비용이 생각보다 낮았습니다."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_a_negation_with_a_particle_is_not_a_claim_of_the_negated_act(self):
        for text in ("저는 직접 써 보지는 않았습니다.", "저도 직접 가 보지도 않았습니다.", "저는 이 서비스를 사용해 보지를 않았습니다.", "저는 아직 써 보지는 못했어요.", "저는 직접 방문하지는 않았습니다만 공식 안내를 옮겼습니다."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)
        self.assertTrue(cl.find_violations("저는 직접 써 보았습니다."))

    def test_not_few_is_an_experience_but_did_not_write_is_not(self):
        for text in ("표에는 가격을 적지 않았습니다.", "의견은 적지 않았습니다.", "세부 내용은 여기에 적지 않았습니다."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)
        for text in ("비용이 적지 않았어요.", "부담이 적지 않았습니다."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_a_formal_adjective_about_a_topic_is_not_an_experience_but_a_bare_one_or_a_chatty_one_is(self):
        for text in ("그의 연설은 상징적이었습니다.", "이 사건은 역사적이었습니다.", "당시 이 방식은 매우 일반적이었습니다.", "초기 결과는 압도적이었다."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)
        for text in ("압도적이었습니다.", "분위기가 감동적이었어요.", "서비스가 이상적이었습니다.", "이 영화는 정말 감동적이었어요.", "그의 연설은 인상적이었습니다."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_getting_used_to_it_is_a_claim_only_in_the_past(self):
        for text in ("처음에는 어색해도 금방 익숙해집니다.", "이 앱은 금세 익숙해질 만큼 쉽게 만들어졌습니다.", "이 모드를 켜면 눈이 덜 피곤하다고 제조사는 설명합니다."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)
        for text in ("금방 익숙해졌어요.", "금세 익숙했습니다.", "눈이 덜 피곤했어요."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_a_text_written_without_spaces_is_read_everywhere_like_before(self):
        self.assertTrue(cl.find_violations("방이정말환해졌어요"), "붙여 쓰면 낱말 경계를 몰라 신호 낱말을 어디서든 센다(띄어 쓰든 붙여 쓰든 같은 말)")
        self.assertTrue(cl.find_violations("정부는새정책에따라지원금지급에나섰습니다"), "붙여 쓰면 3인칭 주어도 알아볼 수 없어 건너뛰지 않는다 — 안 걸러 내는 쪽이 안전하다")
        self.assertTrue(cl.find_violations("방이 정말 환해졌어요"))
        self.assertEqual(kinds("정부는 새 정책에 따라 지원금 지급에 나섰습니다."), ())

    def test_what_the_signal_cut_would_have_dropped_is_caught_by_its_own_rule(self):
        self.assertEqual(kinds("지난주에 이 책상을 구입해서 조립까지 마쳤어요."), (cl.EXPERIENCE_BUY,), "때 표지가 붙은 구입 서술")
        self.assertEqual(kinds("지난주에 이 책상을 구입해서 설치했습니다."), (USE, cl.EXPERIENCE_BUY))
        self.assertEqual(kinds("이 책상을 구입해서 조립까지 마쳤어요."), (), "때 표지가 없으면 구입 서술만으로는 걸지 않는다")
        self.assertTrue(cl.find_violations("이번 달 애드센스 수익이 처음으로 십만 원을 넘겼어요."))
        self.assertTrue(cl.find_violations("공기가 차가워서 정신이 번쩍 들었어요."))
        self.assertEqual(kinds("구입해서 쓰세요."), ())


class NormalSuggestedTopicsStayCleanTest(unittest.TestCase):
    """'e'(후보 자동 제안 `candidates suggest`)는 제안한 주제·키워드가 경험을 단정하지 않는지 `check/claims.py` 로 거른다 — 정상 주제 16개와 보조 키워드가 이 검사에 걸리지 않아야 한다(고침이 '구매 전·방문 전·사용 전' 같은 안내 낱말까지 걸지 않는지)."""

    TOPICS = ("난방비 줄이는 방법과 확인할 기준", "연말정산 서류 준비 순서 정리", "공기청정기 고르기 전 확인할 체크리스트", "캠핑 처음 시작할 때 준비물 정리", "가계부 쓰는 법 기본 정리", "겨울철 보일러 관리 요령",
              "스마트폰 요금제 비교 기준", "청소 루틴 만드는 방법", "김장 준비 순서와 주의할 점", "다이어트 식단 짜는 기준", "육아용품 구매 전 확인사항", "제주 여행 계획 세우는 순서",
              "방문 전 확인할 운영 정보 정리", "사용 전에 알아둘 주의사항", "장마철 곰팡이 예방 방법", "설 명절 선물 고르는 기준")
    KEYWORDS = ("난방 체크리스트", "연말정산 서류", "공기청정기 선택", "캠핑 준비", "가계부 기본", "보일러 관리", "요금제 비교", "청소 방법", "김장 순서", "다이어트 식단", "육아용품 구매 전", "제주 여행 계획", "방문 전 확인", "사용 전 주의", "곰팡이 예방", "선물 기준")

    def test_sixteen_normal_topics_and_their_keywords_have_no_violation(self):
        self.assertEqual(len(self.TOPICS), 16)
        for text in self.TOPICS + self.KEYWORDS:
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), (), text)
                self.assertEqual(cl.find_violations([text]), (), text)

    def test_the_same_topics_are_not_review_premises(self):
        for text in self.TOPICS:
            with self.subTest(text=text):
                self.assertIsNone(pt.premise_of(text, "키워드"), text)


class LinearTimeOfTheNewChecksTest(unittest.TestCase):
    def assert_fast(self, text, limit=6.0):
        started = time.perf_counter()
        cl.find_violations(text)
        self.assertLess(time.perf_counter() - started, limit, f"{len(text)}자")

    def test_the_assertion_search_is_bounded_per_word(self):
        self.assert_fast("직접 써 본 결과 아주 편합니다 " * 15_000 + "댓글 남겨 주세요")
        self.assert_fast("써 본 느낌 " * 40_000 + "알려 주세요")
        self.assert_fast("직접 써 본 결과 아주 편합니다 궁금하시면 " * 12_000)
        self.assert_fast('"직접 써 봤는데 좋았어요"는 제가 한 말입니다 ' * 6_000)

    def test_nine_times_the_input_takes_about_nine_times_as_long(self):
        def best(text):
            result = 9.0
            for _ in range(3):
                started = time.perf_counter()
                cl.find_violations(text)
                result = min(result, time.perf_counter() - started)
            return result
        for unit in ("직접 써 본 결과 아주 편합니다 ", "써 본 느낌 ", '"직접 써 봤는데 좋았어요"는 제가 한 말입니다 '):
            small, big = best(unit * 2_000), best(unit * 18_000)
            with self.subTest(unit=unit):
                self.assertLess(big / max(small, 1e-4), 20, "9배 입력에 시간이 20배를 넘으면 선형이 아니다(잡음을 넉넉히 둔 상한)")


if __name__ == "__main__":
    unittest.main()
