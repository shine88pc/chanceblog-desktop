"""'지어내지 않기' 검사 정확도 c2-fix 2차 수정 시험 — 독립 델타 검증(`조건부 병합 가능`)이 찾은 같은 갈래의 구멍 N1·N2·N3 를 닫은 규칙이 그대로 서 있는지 지킨다.

N1 '표지(꾸미는 낱말) + 단정 서술 절 + 부탁 꼬리': 앞 판은 서술 어미를 하나씩 열거한 목록(`_ASSERT`)에 없는 끝말('…나니·…더라·…는데·…ㄴ다·…편')이 오면 부탁이 붙은 경험 단정을 지나가게 했다.
  이제는 어미가 무엇이든 '꾸미는 낱말의 머리말 뒤 ~ 부탁 앞'이 부탁의 목적어로 보기에 길면(조사 붙은 머리말 7글자·조사 없는 머리말 3글자 초과) 서술 절로 본다. 이 시험은 서술 끝 43종(검증자 15종 + 구현자가 새로 쓴 28종)을 모두 건다.
N2 '…라고 적는 경우가 많습니다' 처럼 낱말 자신의 끝('…했어요')이 낱말 뒤에 남아도 '경우' 가드는 풀리지 않는다.
N3 '광안리 횟집 방문 후기 다시 갈 만할까' 처럼 후기 낱말이 장소·경험 낱말 뒤에 오면 후기 자체의 제목이다(후기를 설명하는 글은 후기 낱말이 앞머리에 선다).
이 시험의 문장은 c2-fix 구현자가 새로 쓴 것이다 — 기대값은 코드에서 베끼지 않았다. 네트워크·파일 없이 돈다.
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

USE = cl.EXPERIENCE_USE


def kinds(text):
    return tuple(claim.category for claim in cl.find_violations(text))


# 겪은 일을 현재형으로 단정하는 절의 끝 모양 43종 — 앞 판의 서술어 목록에 없던 것(검증자가 연 15종 + 구현자가 새로 쓴 28종)을 모두 담는다. (태그, 절)
OPEN_ENDINGS = (
    ("나니", "소음이 거의 안 나니"), ("기니", "손에 착 감기니"), ("시니", "분위기가 좋으시니"), ("주니", "양도 넉넉히 주니"), ("드니", "가격이 부담 없이 드니"), ("자니", "고치자니"),
    ("해서", "분위기가 아늑해서"), ("한데", "서비스가 친절한데"), ("인데", "가성비가 좋은 편인데"), ("고", "가볍고 튼튼하고"), ("며", "맛이 진하며"), ("다", "정말 괜찮다"),
    ("지만", "조금 비싸지만"), ("면서", "가볍고 조용하면서"), ("거든요", "정말 조용하거든요"),
    ("는데", "소음이 거의 없는데"), ("아서", "화면이 밝아서"), ("기에", "가격이 합리적이기에"), ("길래", "너무 마음에 들길래"), ("더라고요", "생각보다 편하더라고요"),
    ("더군요", "생각보다 가볍더군요"), ("잖아요", "원래 튼튼하잖아요"), ("는걸요", "꽤 오래 가는걸요"), ("ㄴ다", "배터리가 오래 간다"), ("음", "소음이 거의 없음"),
    ("랍니다", "정말 편하답니다"), ("군", "정말 편하군"), ("네", "정말 편하네"), ("지", "꽤 괜찮지"), ("면서도", "무게가 가벼우면서도"), ("ㄹ뿐", "조금 무거울 뿐"),
    ("편", "가성비가 좋은 편"), ("ㄹ듯", "오래 쓸 듯"), ("것같아서", "오래 갈 것 같아서"), ("거든", "정말 조용하거든"), ("ㄴ걸", "꽤 괜찮은걸"),
    ("다니", "이렇게 조용하다니"), ("더라", "정말 편하더라"), ("던데", "생각보다 가볍던데"), ("구요", "색이 예쁘구요"), ("어", "소음이 거의 없어"),
    ("야", "정말 최고야"), ("잖아", "원래 튼튼하잖아"),
)
HEADS = ("제가 직접 써 본 결과", "써 본 결과", "직접 먹어 본 후기로는", "내가 사용해 본 소감은", "써 본 뒤", "다녀온 후기로는")        # 1인칭 표지가 있는 것·없는 것, 머리말에 조사가 없거나 주제 조사가 붙은 것
TAILS = ("참고해 보세요", "믿고 구매하세요", "한번 방문해 주세요", "확인해 주세요")


class StructureCatchesAnyEndingTest(unittest.TestCase):
    """N1 — 서술 어미를 열거하지 않고 '꾸미는 낱말 + 절 + 부탁 꼬리' 구조로 거는 규칙."""

    def test_every_clause_ending_with_every_head_and_every_request_tail_is_a_violation(self):
        for tag, clause in OPEN_ENDINGS:
            for head in HEADS:
                for tail in TAILS:
                    text = f"{head} {clause} {tail}."
                    with self.subTest(ending=tag, text=text):
                        self.assertTrue(cl.find_violations(text), text)

    def test_a_clause_that_is_not_in_any_ending_list_is_caught_the_same(self):
        for text in ("제가 직접 써 본 결과 가나다라마바 참고하세요.", "써 본 결과 가나다라마바 믿고 구매하세요.", "직접 먹어 본 후기로는 하하하하하 한번 방문해 주세요."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_a_head_with_a_particle_followed_by_a_clause_with_its_own_subject_is_a_violation(self):
        for text in ("제가 직접 써 본 후기를 남기니 많은 도움이 되길 바랍니다.", "직접 써 본 후기를 올렸는데 소음이 거의 없어서 참고하세요.", "제가 다녀온 후기를 정리했는데 가격이 합리적이라서 많이 읽어 주세요."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_a_word_with_a_subject_particle_after_the_head_makes_the_short_part_a_clause(self):
        for text in ("써 본 후기를 분위기가 좋아 참고하세요.", "써 본 후기를 맛이 좋아 참고하세요.", "써 본 후기를 서비스가 아늑해 참고하세요."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (USE,), text)
        self.assertEqual(kinds("써 본 후기를 좋아 참고하세요."), (), "주어 없이 짧은 말")
        self.assertEqual(kinds("써 본 후기를 댓글로 편하게 참고하세요."), (), "목적어 사슬")

    def test_an_interrogative_word_inside_the_claim_does_not_hide_it(self):
        for text in ("제가 직접 써 본 결과 어떤 상황에서도 아주 편합니다 참고하세요.", "제가 직접 써 본 결과 몇 번을 써도 만족스럽습니다 참고하세요.", "직접 다녀온 후기로는 어디를 가도 사람이 많습니다 참고하세요.",
                     "제가 직접 써 본 결과 언제나 만족스러워요 한번 써 보세요.", "제가 직접 써 본 결과 어떤 상황에서도 소음이 거의 없어요 확인해 주세요."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text), text)

    def test_a_question_to_the_reader_is_still_a_question(self):
        for text in ("직접 다녀온 곳이 어디예요?", "직접 써 본 결과 어떠셨는지 알려 주세요.", "써 본 후 어떠셨는지 알려 주세요.", "직접 써 본 느낌은 어떠세요?"):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)

    def test_a_spaceless_text_is_judged_strictly(self):
        self.assertTrue(cl.find_violations("제가직접써본결과소음이거의안나니참고하세요."))
        self.assertTrue(cl.find_violations("써본결과소음이거의없는데참고해보세요."))

    def test_a_spaceless_text_adds_three_syllables_for_the_request_word(self):
        self.assertEqual(kinds("써본결과가나다라참고하세요."), (), "사이 4글자 + 부탁 낱말 '참고' 2글자 = 6글자까지는 부탁이다")
        self.assertTrue(cl.find_violations("써본결과가나다라마참고하세요."), "7글자부터는 서술 절")


class RequestShapesStayCleanTest(unittest.TestCase):
    """N1 의 대가를 지킨다 — 독자에게 하는 부탁·안내(꾸미는 낱말이 목적어·때가 되는 꼴)는 서술 절이 아니다."""

    LEGIT = (
        "써 본 느낌을 아래 설문에 남겨 주세요.", "먹어 본 소감을 한 줄씩 남겨 주세요.", "사용해 본 후기를 공유해 주시면 감사하겠습니다.", "설치해 본 뒤에 문제가 생기면 이 글에 댓글로 남겨 주세요.",
        "직접 입어 본 뒤에 사이즈가 맞지 않으면 교환을 신청하세요.", "써 본 뒤에는 어떠셨는지 꼭 알려 주세요.", "다녀온 곳이 있다면 후기를 알려 주세요.", "직접 해 본 방법이 있으면 공유해 주세요.",
        "먹어 본 메뉴 중에 추천하고 싶은 것이 있다면 알려 주세요.", "가 본 곳의 후기를 댓글로 남겨 주시면 다음 글에 반영하겠습니다.", "써 본 분들의 후기를 기다립니다.", "구매해 본 적이 있다면 가격을 알려 주세요.",
        "직접 사용해 본 뒤에 구매를 결정하시길 바랍니다.", "여러분이 써 본 느낌을 댓글에 적어 주세요.", "직접 써 본 느낌이 궁금하시다면 댓글로 질문해 주세요.", "사용해 본 분이 계시면 장단점을 나눠 주세요.",
        "써 본 소감은 댓글로 남겨 주세요.", "써 본 느낌을 댓글로 편하게 남겨 주세요.", "직접 다녀온 후기를 사진과 함께 올려 주세요.", "써 본 뒤에 오류가 나면 재부팅부터 해 보세요.",
        "먹어 보고 나서 알레르기 반응이 나타나면 즉시 중단하세요.", "직접 가서 확인한 뒤 다시 정리해 보겠습니다.", "직접 체험한 경험이 있는 분은 댓글로 공유해 주세요.", "써 본 뒤에는 솔직한 느낌을 꼭 공유할 생각이에요.",
    )

    def test_a_request_whose_object_or_time_is_the_modifier_form_passes(self):
        for text in self.LEGIT:
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)

    def test_the_request_word_itself_is_not_counted_as_part_of_the_clause(self):
        self.assertEqual(kinds("써 본 느낌을 가나다라마바사 알려 주세요."), ())
        self.assertEqual(kinds("써 본 결과 가나다 참고하세요."), ())

    def test_the_part_in_between_is_seven_syllables_with_a_particle_and_three_without(self):
        self.assertEqual(kinds("써 본 느낌을 가나다라마바사 알려 주세요."), (), "조사 붙은 머리말 7글자")
        self.assertEqual(kinds("써 본 느낌을 가나다라마바사아 알려 주세요."), (USE,), "8글자는 서술 절")
        self.assertEqual(kinds("써 본 결과 가나다 참고하세요."), (), "조사 없는 머리말 3글자")
        self.assertEqual(kinds("써 본 결과 가나다라 참고하세요."), (USE,), "4글자는 서술 절")

    def test_every_particle_on_the_head_gives_the_longer_limit_and_a_topic_particle_the_shorter(self):
        for particle in ("을", "를", "에", "이", "가", "의", "도", "만", "와", "과", "에는", "에도", "에서", "에서는"):
            with self.subTest(particle=particle):
                self.assertEqual(kinds(f"써 본 느낌{particle} 가나다라마바사 알려 주세요."), (), "7글자까지")
                self.assertEqual(kinds(f"써 본 느낌{particle} 가나다라마바사아 알려 주세요."), (USE,), "8글자부터")
        for particle in ("은", "는", "로는"):
            with self.subTest(particle=particle):
                self.assertEqual(kinds(f"써 본 느낌{particle} 가나다 알려 주세요."), (), "주제 조사는 3글자까지")
                self.assertEqual(kinds(f"써 본 느낌{particle} 가나다라 알려 주세요."), (USE,), "4글자부터")

    def test_a_condition_in_between_is_advice_for_the_reader_but_the_writers_own_if_is_not(self):
        self.assertEqual(kinds("설치해 본 뒤에 오류가 나면 재부팅부터 해 보세요."), ())
        self.assertEqual(kinds("써 본 뒤 불편하시면 고객센터에 문의하세요."), ())
        self.assertTrue(kinds("제가 써 본 결과를 요약하면 다음과 같으니 참고하세요."), "글쓴이가 말을 잇는 '요약하면' 은 독자에게 거는 조건이 아니다")
        self.assertTrue(kinds("제가 직접 써 본 결과 가볍고 조용하면서 참고하세요."), "'하면서' 는 조건이 아니라 이어 주는 말이다")
        self.assertTrue(kinds("제가 직접 써 본 후기를 정리하자면 소음이 거의 없어서 참고하세요."), "글쓴이가 말을 잇는 '정리하자면'")

    def test_people_who_have_tried_are_a_third_party_not_the_writer(self):
        for text in ("방문해 본 분이 많아 보이니 후기를 참고하세요.", "방문해 본 분이 많으니 후기를 참고하세요.", "방문해 본 분은 많아 보이니 후기를 참고하세요.", "방문해 본 분도 많아 보이니 후기를 참고하세요.",
                     "방문해 본 분께 감사드리니 후기를 참고하세요.", "직접 써 본 분께 질문을 드리면 도움이 되니 댓글로 알려 주세요.", "사용해 본 분은 대부분 만족하시니 참고하세요."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)

    def test_a_connective_modifier_form_is_followed_by_a_chain_of_actions(self):
        self.assertEqual(kinds("직접 가서 확인한 뒤 다시 정리해 보겠습니다."), ())
        self.assertEqual(kinds("먹어 보고 나서 알레르기 반응이 나타나면 즉시 중단하세요."), ())
        self.assertEqual(kinds("들어서자마자 보인 점을 알려 주세요."), (), "'…자마자' 로 끝난 낱말")
        self.assertEqual(kinds("갔다가 알게 된 점을 알려 주세요."), (), "'…다가' 로 끝난 낱말")

    def test_an_experience_that_does_not_exist_or_a_quote_concession_is_not_a_claim(self):
        self.assertEqual(kinds("직접 써 본 느낌이라고 해서 댓글 남겨 주세요."), (), "'이라고 해서' — 다고 해서 의 동무")
        self.assertEqual(kinds("직접 써 본 느낌이라고 해도 댓글 남겨 주세요."), ())


class CaseGuardWithTheWordsOwnEndingTest(unittest.TestCase):
    """N2 — '…라고 적는 경우가 많습니다' 의 낱말 자신의 끝('…했어요')을 '앞의 단정'으로 세어 '경우' 가드를 풀지 않는다."""

    def test_a_sentence_that_explains_how_reviews_are_written_passes(self):
        for text in ("후기에 '배송이 빨랐어요'라고 적는 경우가 많습니다.", "후기에 \"직접 써 봤는데 좋았어요\"라고 쓰는 경우가 흔합니다.", "리뷰에 '정말 편했어요'라고 남기는 경우 별점이 같이 올라갑니다.",
                     "'써 보니 만족했어요'라고 적는 경우도 있습니다."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)

    def test_each_of_the_three_case_forms_keeps_the_guard_by_itself(self):
        self.assertEqual(kinds("후기에 '배송이 빨랐어요'라고 적는 경우가 많습니다."), (), "는 경우")
        self.assertEqual(kinds("후기에 '배송이 빨랐어요'라고 적을 경우 별점이 같이 올라갑니다."), (), "을 경우")
        self.assertEqual(kinds("후기에 '배송이 빨랐어요'라고 한 경우가 많습니다."), (), "한 경우")

    def test_a_claim_with_a_case_word_after_a_stated_claim_is_still_a_claim(self):
        self.assertTrue(kinds("직접 써 본 결과 아주 편합니다 만족한 분이 많은 경우라 믿고 보세요."))
        self.assertTrue(kinds("저는 어제 써 봤고 정말 좋았어요."))


class ReviewTitlesWithATailTest(unittest.TestCase):
    """N3 — 후기 낱말이 제목의 앞머리가 아니면 후기 자체의 제목이다('헷갈리면 후기로 본다')."""

    REVIEW_TITLES = (
        "광안리 횟집 방문 후기 다시 갈 만할까", "캠핑카 대여 이용 후기 가성비는 될까", "무인 카페 이용 후기 재방문할까", "무선 이어폰 두 달 후기 소리 차이는", "전기장판 사용 후기 전기세 차이는",
        "스마트 체중계 3주 후기 정확도 차이는", "오피스텔 입주 후기 만족도 될까", "제주 감성 숙소 후기 사진 고르는 팁", "커피머신 한 달 후기 순위 기준", "프린터 구매 후기 광고 아님 이유",
        "홈트 기구 사용 후기 구조 방식", "서핑 강습 체험 후기 사진 요령", "맥북 에어 1년 후기 배터리 구성 이유", "산후조리원 이용 후기 비용 차이는",
    )
    INFO_TITLES = (
        "후기의 비밀", "리뷰 점수의 함정", "별점 리뷰의 의미는 무엇일까", "후기 조작의 원리", "체험단 후기란 무엇일까", "가짜 후기 사진 차이는 무엇일까", "후기 사진 고르는 요령", "리뷰 점수 계산 원리",
        "별점 순위가 정해지는 방식",
    )

    def test_a_title_with_the_review_word_after_a_place_or_an_experience_word_is_a_review(self):
        for title in self.REVIEW_TITLES:
            with self.subTest(title=title):
                self.assertIsNotNone(pt.premise_of(title, "키워드"), title)
                self.assertIsNotNone(pt.premise_of("제목", title), title)

    def test_a_title_with_the_review_word_at_the_front_that_explains_reviews_is_no_review(self):
        for title in self.INFO_TITLES:
            with self.subTest(title=title):
                self.assertIsNone(pt.premise_of(title, "키워드"), title)

    def test_the_review_word_may_follow_at_most_four_syllables(self):
        self.assertIsNone(pt.premise_of("가나다라후기의 비밀", "키워드"))
        self.assertEqual(pt.premise_of("가나다라마후기의 비밀", "키워드").kind, "review")
        self.assertIsNone(pt.premise_of("가나다라후기 사진 고르는 요령", "키워드"))
        self.assertEqual(pt.premise_of("가나다라마후기 사진 고르는 요령", "키워드").kind, "review")

    def test_up_to_two_leading_symbols_do_not_push_the_review_word_back(self):
        self.assertIsNone(pt.premise_of("※ 후기 사진 고르는 요령", "키워드"))
        self.assertIsNone(pt.premise_of("★후기의 비밀", "키워드"))
        self.assertEqual(pt.premise_of("★★★ 후기의 비밀", "키워드").kind, "review")

    def test_real_review_titles_with_a_tail_are_replaced_through_the_draft_plan(self):
        for title in ("광안리 횟집 방문 후기 다시 갈 만할까", "캠핑카 대여 이용 후기 가성비는 될까", "무선 이어폰 두 달 후기 소리 차이는", "무인 카페 이용 후기 재방문할까"):
            with self.subTest(title=title):
                candidate = Candidate.new(title, title.split(" ")[0], ("naver_a",), post_type=POST_TYPES[0], now="2026-11-02T03:00:00Z")
                plan = dp.build_plan(candidate, None, None, today="2026-11-03")
                self.assertIsNotNone(plan.replaced, "안전 대체를 했다는 안내가 있어야 한다")
                shown = " ".join([plan.topic, *plan.titles, *plan.subheadings])
                self.assertNotIn("후기", shown)


class PinnedMutationSurvivorsTest(unittest.TestCase):
    """독립 검증자의 변이 시험에서 살아남은 네 곳(시험 공백) — 그 낱말 하나만 이유가 되는 문장으로 고정한다."""

    def test_an_honorific_reason_ending_is_an_assertion_by_that_ending_alone(self):
        self.assertEqual(kinds("직접 써 본 후기를 올리시니까 참고하세요."), (USE,), "'시' 뒤의 '니까' 는 다른 어미 낱말에 안 걸리고 사이도 짧다")

    def test_a_how_much_or_how_many_question_is_cut_at_the_interrogative(self):
        self.assertEqual(kinds("직접 써 본 느낌이 몇 점이에요?"), (), "묻는 낱말 '몇'")
        self.assertEqual(kinds("직접 다녀온 곳이 얼마예요?"), (), "묻는 낱말 '얼마'")

    def test_a_quote_the_writer_calls_ours_is_not_a_mention(self):
        self.assertTrue(cl.find_violations('"직접 써 봤는데 정말 좋았어요"는 저희가 한 말입니다.'), "1인칭 '저희' 가 따옴표 가까이에 있다")

    def test_a_consultation_the_writer_had_is_a_dialogue(self):
        self.assertIn(cl.DIALOGUE, kinds("상담을 받아 봤습니다."))

    def test_the_writers_own_if_keeps_a_claim_from_being_read_as_a_condition(self):
        for connective in ("요약하면", "정리하면", "종합하면", "말씀드리면", "한마디로 말하면"):
            text = f"제가 써 본 후기를 {connective} 소음이 거의 없어서 참고하세요."
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (USE,), text)

    def test_a_reader_condition_without_an_assertion_is_still_a_guard(self):
        self.assertEqual(kinds("써 본 느낌은 쓰노라면 참고하세요."), ())
        self.assertEqual(kinds("써 본 후 어떤 점이 좋았는지 알려 주세요."), ())


class StructureRuleIsLinearTest(unittest.TestCase):
    """새 구조 판정이 긴 글에서 제곱 시간이 되지 않는다(낱말마다 앞뒤 60글자만 본다)."""

    def test_one_long_sentence_with_many_modifier_forms_is_linear(self):
        unit = "써 본 느낌을 알려 주세요 "
        small, big = unit * 4000 + "참고하세요", unit * 12000 + "참고하세요"
        start = time.perf_counter()
        cl.find_violations(small)
        first = time.perf_counter() - start
        start = time.perf_counter()
        cl.find_violations(big)
        second = time.perf_counter() - start
        self.assertLess(second, max(first, 0.05) * 20, f"3배 입력이 {second / max(first, 0.001):.1f}배 걸렸다(선형이면 3 안팎)")


if __name__ == "__main__":
    unittest.main()
