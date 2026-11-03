"""2차 검증이 찾은 우회 — 물음표만 붙이거나 꼬리 질문을 단 선언, '…다고 생각합니다' 로 단정하는 말 — 이 '지어낸 경험' 검사를 빠져나가지 못하게 고정한다.

지키는 것:
  1) 겪은 일을 말하는 평서문(-했습니다·-했어요)은 끝에 물음표만 붙여도, 뒤에 꼬리 질문(아닌가요?·어떠세요?)을 달아도, 쉼표로 이어도 위반이다.
  2) 독자에게 묻는 말(높임 -셨나요·-셨어요·-세요, 의문사 어땠어요, 부탁 -주시겠어요)은 그대로 지나간다 — 과거형 서술이 없기 때문이다.
  3) 효과·수익을 단정한 말 뒤에 '…다고 생각합니다·확신합니다·말할 수 있습니다' 가 붙으면 자기 판단이므로 위반이고, '…다고 합니다' 처럼 남의 말을 옮기는 것은 지나간다.
알려진 한계: 높임이 아닌 반말·구어 질문('써 봤어요?')은 겪은 일을 말하는 것과 형태가 같아 걸린다 — '써 보셨나요?' 로 바꿔 쓴다.
네트워크·파일 없이 돈다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.check import claims as cl  # noqa: E402

STATEMENTS = (                                                    # 겪은 일을 말하는 평서문 20개 — 끝이 -습니다·-어요
    "저는 이 청소기를 직접 써 봤는데 흡입력이 좋았습니다", "제가 지난주에 이 식당에 다녀왔는데 음식이 빨리 나왔어요", "한 달 먹어 봤더니 속이 편했습니다", "직접 설치해 보니 생각보다 쉬웠어요",
    "이 방법으로 수익을 냈습니다", "어제 방문했더니 직원이 친절했습니다", "제가 직접 입어 보니 편안했어요", "써 보니 소음이 조용했어요", "이 가게는 가 봤더니 깔끔했어요",
    "직접 구매해서 써 보니 편했어요", "지난달에 샀는데 만족했어요", "저희 가족이 먹어 보니 맛있었어요", "직접 해 봤더니 괜찮았어요", "제가 직접 타 보니 승차감이 부드러웠습니다",
    "한 달 복용했더니 피로가 줄었습니다", "직접 써 본 결과 속도가 빨랐습니다", "이용해 보니 놀랐어요", "광고로 수익을 올렸습니다", "사용해 보니 배터리가 오래 갔어요", "직접 방문했는데 매장이 한산했습니다",
)
TAILS = ("죠?", " 아닌가요?", " 믿어지시나요?", " 어떠세요?", ", 그렇죠?", ", 여러분은 어떠세요?", " 안 그런가요?", " 어떠셨나요?")
QUESTIONS = (                                                     # 독자에게 묻는 말 — 과거형 서술이 없다
    "써 보니 어떠셨나요?", "써 보니 어땠어요?", "직접 써 보셨어요?", "다녀오신 분은 어떠셨어요?", "써 보니 어떠세요?", "방문해 보니 어땠나요?", "사용해 본 경험이 있으신가요?",
    "여러분은 써 보니 만족하셨나요?", "직접 써 봤을 때 어떠셨나요", "써 본 소감을 알려 주시겠어요?", "써 본 소감을 알려 주실 수 있나요?", "이 제품을 써 본 분은 계신가요?",
    "써 보니 만족한 점이 있어요?", "직접 사용해 본 후기를 남겨 주시겠습니까?", "다녀오신 후기를 공유해 주시겠어요?", "한 달 써 보니 어떠셨는지 궁금합니다?",
)
OWN_VIEW = ("이 방법으로 수익을 냈다고 생각합니다", "정말 만족스러웠다고 생각합니다", "광고로 수익을 올렸다고 확신합니다", "효과를 봤다고 자부합니다", "저는 매우 편했다고 믿습니다",
            "훌륭했다고 말해도 좋습니다", "효과가 좋았다고 판단합니다", "이 방법으로 수익을 냈다고 말할 수 있습니다", "매우 편했다고 느낍니다", "훌륭했다고 평가합니다", "이 방식으로 효과를 봤다고 인정합니다",
            "이 방법으로 수익을 냈다고 저는 생각합니다", "이 방법으로 수익을 냈다고 정말 믿습니다", "수익이 났다는 점을 확신합니다", "이 방법으로 수익을 냈다고 봅니다", "이 방법으로 수익을 냈다고 봐요", "효과가 좋았다고 느껴요",
            "효과가 좋았다고 느끼고 있습니다", "이 방법으로 수익을 냈다고 단언합니다", "이 방법으로 수익을 냈다고 장담합니다", "이 방법으로 수익을 냈다고 여깁니다", "이 방법으로 수익을 냈다고 여겨요")
HEARSAY = ("수익을 냈다고 합니다", "많은 분이 만족했다고 해요", "효과를 봤다고 합니다만 사람마다 다릅니다", "수익을 냈다고 하는 분도 있습니다", "편했다고 들었습니다", "수익을 냈다는 후기가 있습니다",
            "수익을 냈다고 하던데 저도 맞다고 생각합니다", "수익을 냈다고 하는데 그렇게 생각합니다")


def kinds(text):
    return {claim.category for claim in cl.find_violations(text)}


class QuestionMarkOnlyTest(unittest.TestCase):
    def test_every_statement_is_a_violation_without_a_question_mark(self):
        for text in STATEMENTS:
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))

    def test_a_trailing_question_mark_does_not_hide_a_statement(self):
        for text in STATEMENTS:
            for mark in ("?", "？", " ?", "??", "?)", '?"'):
                with self.subTest(text=text, mark=mark):
                    self.assertEqual(kinds(text + mark), kinds(text), "물음표를 붙여도 같은 분류가 걸려야 한다")

    def test_a_tail_question_after_a_statement_does_not_hide_it(self):
        for text in STATEMENTS:
            for tail in TAILS:
                with self.subTest(text=text, tail=tail):
                    self.assertTrue(cl.find_violations(text + tail))

    def test_a_banmal_or_exclaiming_statement_with_a_question_mark_is_still_one(self):
        for text in ("정말 좋았다?", "저는 써 봤는데 만족했네요?", "써 봤더니 편했군요?", "직접 써 봤더니 편했다?"):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))

    def test_the_known_limit_a_casual_question_in_the_same_form_is_flagged(self):
        for text in ("써 봤어요?", "혹시 먹어 봤어요?"):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))


class RealQuestionsStayExemptTest(unittest.TestCase):
    def test_questions_to_the_reader_pass(self):
        for text in QUESTIONS:
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_a_question_is_checked_as_a_whole_sentence_and_an_ordinary_sentence_next_to_it_still_counts(self):
        text = "써 보니 어떠셨나요? 저는 직접 써 봤는데 만족했습니다."
        self.assertEqual({claim.position for claim in cl.find_violations(text)}, {1})
        self.assertEqual({claim.position for claim in cl.find_violations("저는 직접 써 봤는데 만족했습니다. 써 보니 어떠셨나요?")}, {0})

    def test_the_past_statement_probe_has_exact_edges(self):
        states = cl._states_past
        for text in ("좋았어요", "만족했습니다", "맛있었어요", "정말좋았다", "써봤네요", "편했군요", "놀랐어요", "어땠어요좋았어요"):
            with self.subTest(text=text):
                self.assertTrue(states(text), text)
        for text in ("어땠어요", "어떠셨어요", "알려주시겠어요", "있어요", "있습니다", "어땠나요", "좋았다면", "다", "", "가나다", "어요좋았", "습니다좋았", "뭐였어요", "무엇이었어요", "어디였어요", "언제였어요", "누구였어요", "왜였어요", "얼마였어요", "어떠했어요"):
            with self.subTest(text=text):
                self.assertFalse(states(text), text)

    def test_the_past_syllable_means_a_final_double_s_except_honorific_future_and_exist(self):
        for char in "았었했였봤썼갔왔랐웠":
            with self.subTest(char=char):
                self.assertTrue(cl._past_syllable(char))
        for char in "셨겠있가나다힣a1 ㅆ":
            with self.subTest(char=char):
                self.assertFalse(cl._past_syllable(char))


class NegationStaysExemptTest(unittest.TestCase):
    def test_a_negating_word_right_after_a_claim_word_still_exempts_it(self):
        for text in ("직접 써 본 것이 아닌 자료입니다", "직접 방문한 곳이 아닌 후보를 정리했습니다", "직접 써 본 것이 아닌가 싶어서 확인했습니다", "써 본 소감은 아닌 것 같습니다"):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_the_guard_word_must_come_within_the_window_right_after_the_claim_word(self):
        self.assertTrue(cl.find_violations("직접 써 본 소감을 정리해서 올렸고 만약 마음에 든다면 알려 주세요"))
        self.assertEqual(cl.find_violations("직접 써 본 소감을 정리하고 마음에 든다면 알려 주세요"), ())

    def test_only_the_question_tag_is_read_as_a_tag_not_as_a_negation(self):
        self.assertTrue(cl.find_violations("직접 써 본 소감이 만족했습니다 아닌가요?"))
        self.assertTrue(cl.find_violations("직접 써 본 소감이 좋았습니다 아닌가요"))


class OwnViewAfterAClaimTest(unittest.TestCase):
    def test_a_claim_followed_by_i_think_or_i_am_sure_is_a_violation(self):
        for text in OWN_VIEW:
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))

    def test_a_claim_passed_on_from_others_stays_exempt(self):
        for text in HEARSAY:
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_the_own_view_probe_only_reads_the_few_letters_after_the_quote_mark(self):
        self.assertTrue(cl.find_violations("수익을 냈다고 생각합니다"))
        self.assertEqual(cl.find_violations("수익을 냈다고 하는 분이 많고 이 점은 좋은 방향이라고 생각합니다"), ())


if __name__ == "__main__":
    unittest.main()
