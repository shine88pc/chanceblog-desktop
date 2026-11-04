"""'지어내지 않기' 검사 c2b 시험 — 글쓴이를 가리키는 1인칭 규칙(독립 델타 3차 검증이 제안한 한 줄, D-33 ⑬ ㉲)이 그대로 서 있는지 지킨다.

규칙: '제가·저는·저도·내가·우리는·우리가·저희는(저희가·저희도·저희만·저희끼리)' 가 낱말이 시작하고 끝나는 자리에서 꾸미는 낱말('써 본·다녀온 …') 앞 12글자(`WRITER_SPAN`) 안에 서 있고
꾸미는 낱말의 머리말 뒤 ~ 부탁 앞에 서술 절이 비어 있지 않고 부탁 꼬리가 그 경험을 근거로 권하는 말('참고하세요'·'확인해 주세요'·'써 보세요' …, `_RECOMMEND`)이면, 그 절이 얼마나 짧든
겪은 일을 단정한 말('제가 직접 써 본 결과 편해서 참고하세요')로 본다. 독립 검증(c2bf)이 찾은 새 오탐 가족 — 동사 '나는'·독자에게 경험을 청하는 부탁('…알려 주세요')·독자에게 거는 조건 안내('…막히면 질문하세요')·
이어 가는 낱말('직접 써서 만든 자료') — 때문에 '나는' 은 목록에서 빼고, 꼬리를 추천류로 좁히고, 규칙을 이어 가는 낱말·'…면' 조건 검사 뒤로 옮겼다.
다만 부탁 꼬리가 글쓴이 자신의 앞으로의 계획·다짐('…알려 드릴게요'·'…올릴 예정입니다')이거나 절이 계획을 이유로 이어 가면('…올릴 테니') 1인칭은 그 계획의 주어이므로 이 규칙을 쓰지 않는다.
12글자·낱말 시작·끝 자리·'요금제가'·'우리가족이' 같은 낱말 속 글자·문턱(7·3)·계획 꼬리 24종·추천 꼬리 낱말 8개·'…면' 조건 뒤 순서는 이 시험이 못 박는다 — 일부러 어겨 본 변이 점검의 기록은 D-33 ⑬ ㉲.
이 시험의 문장은 c2b·c2bf 구현자가 새로 쓴 것이다(맹검 예문은 저장소에 올리지 않았다). 네트워크·파일 없이 돈다.
"""
import itertools
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.check import claims as cl  # noqa: E402

USE = cl.EXPERIENCE_USE
VISIT = cl.EXPERIENCE_VISIT


def kinds(text, **options):
    return tuple(claim.category for claim in cl.find_violations(text, **options))


def caught(text):
    return bool(cl.find_violations(text))


def uncaught(sentences):
    return [text for text in sentences if not caught(text)]


def wrongly_caught(sentences):
    return [text for text in sentences if caught(text)]


PRONOUNS = ("제가", "저는", "저도", "내가", "우리는", "우리가", "저희는")                                              # 글쓴이를 가리키는 1인칭 7종(지시서 목록에서 동사와 겹치는 '나는' 을 뺐다 — 저희는 주어 조사가 붙은 꼴)
HEADS = ("직접 써 본 결과", "써 본 후기를", "다녀온 후기는", "직접 먹어 본 소감은", "써 본 뒤에", "사용해 본 느낌이")        # 꾸미는 낱말 + 머리말 — 조사 없는 것·주제 조사·목적격·때·주어 조사
CLAUSES = ("가", "가나", "가나다", "편해서", "가나다라", "가나다라마바사", "가나다라마바사아", "생각보다 훨씬 조용하고 편해서")  # 서술 절 — 1~3글자·4·7글자·8글자·긴 절
TAILS = ("참고하세요", "확인해 주세요", "써 보세요", "믿고 보세요")                                                      # 글쓴이 경험을 근거로 권하는 부탁 꼬리(`_RECOMMEND`)
FILL = "마바사아자차카타파하거너더러"                                                                                # 다른 규칙에 걸리지 않는 뜻 없는 채움 글자


class PronounClosesShortClauseTest(unittest.TestCase):
    """대명사 7종 × 머리말 6 × 서술 절 8 × 추천 꼬리 4 — 절이 짧아 부탁의 말과 길이로 못 가르던 것까지 모두 위반이다."""

    def test_every_pronoun_head_clause_and_tail_is_a_violation(self):
        missed = [text for pronoun, head, clause, tail in itertools.product(PRONOUNS, HEADS, CLAUSES, TAILS) if not caught(text := f"{pronoun} {head} {clause} {tail}.")]
        self.assertEqual(missed, [], f"{len(missed)}개를 못 걸렀다: {missed[:3]}")

    def test_the_short_clause_is_caught_whatever_the_ending_of_the_clause_is(self):
        for text in ("제가 직접 써 본 결과 편해서 참고하세요.", "저는 직접 써 본 후기를 공들여 적은 만큼 참고하세요.", "내가 다녀온 후기는 좋아서 가 보세요.", "제가 직접 사용해 본 결과 좋아서 참고하세요.",
                     "저는 직접 먹어 본 소감이 좋아서 가 보세요.", "우리는 써 본 결과 가벼워 믿고 구매하세요.", "제가 써 본 결과를 가나다 참고하세요.", "제가 써 본 느낌을 가나다 참고하세요."):
            with self.subTest(text=text):
                self.assertTrue(caught(text), text)

    def test_the_head_verbs_of_the_modifier_word_do_not_matter(self):
        verbs = ("먹어 본 결과", "입어 본 결과", "해 본 결과", "사용해 본 결과", "이용해 본 결과", "방문해 본 후기는", "구매해 본 후기는", "가 본 후기는", "다녀온 후기는", "써 본 결과")
        missed = uncaught(f"제가 직접 {verb} 가나다 참고하세요." for verb in verbs)
        self.assertEqual(missed, [], missed)

    def test_the_category_is_the_one_the_modifier_word_belongs_to(self):
        self.assertEqual(kinds("제가 직접 써 본 결과 가나다 참고하세요."), (USE,))
        self.assertEqual(kinds("제가 다녀온 후기는 가나다 참고하세요."), (VISIT,))

    def test_the_same_sentences_without_the_pronoun_keep_the_old_limits(self):
        # 문턱(조사 없는 머리말 3글자·조사 붙은 머리말 7글자)은 바꾸지 않았다 — 대명사가 없으면 판정은 그대로다(짧은 절은 아직 새어 나간다 — 알려진 한계)
        self.assertFalse(caught("직접 써 본 결과 가나다 참고하세요."), "3글자 — 부탁의 말과 구문이 같다")
        self.assertTrue(caught("직접 써 본 결과 가나다라 참고하세요."), "4글자부터 서술 절")
        self.assertFalse(caught("써 본 후기를 가나다라마바사 참고하세요."), "조사 붙은 머리말 7글자")
        self.assertTrue(caught("써 본 후기를 가나다라마바사아 참고하세요."), "8글자부터 서술 절")
        self.assertFalse(caught("직접 써 본 결과 편해서 참고하세요."))
        self.assertFalse(caught("직접 써 본 후기를 공들여 적은 만큼 참고하세요."))

    def test_a_long_clause_is_still_caught_with_or_without_the_pronoun(self):
        for text in ("직접 써 본 결과 가나다라마바사아 참고하세요.", "제가 직접 써 본 결과 가나다라마바사아 참고하세요.", "써 본 결과 생각보다 훨씬 조용하고 편해서 참고하세요."):
            self.assertTrue(caught(text), text)


class WindowTest(unittest.TestCase):
    """꾸미는 낱말 앞 12글자(`WRITER_SPAN`) — 대명사가 시작하는 자리부터 낱말이 시작하는 자리까지의 거리가 12글자까지면 단정이다."""

    def sentence(self, pronoun, size, modifier):
        return f"{pronoun} {FILL[:size]} {modifier} 가나다 참고하세요."

    def test_the_window_is_twelve_syllables_for_a_modifier_word_that_starts_after_the_head_verb(self):
        for pronoun in ("제가", "저희는"):                         # 2글자·3글자 대명사
            for distance, expected in ((10, True), (11, True), (12, True), (13, False), (14, False)):
                size = distance - len(pronoun)
                text = self.sentence(pronoun, size, "직접 써 본 결과")
                with self.subTest(pronoun=pronoun, distance=distance):
                    self.assertEqual(caught(text), expected, f"거리 {distance}: {text}")

    def test_the_window_counts_from_where_the_whole_matched_word_starts(self):
        # '써 본 결과' 는 머리말('결과')까지 한 낱말로 잡히는 꼴 — 낱말이 시작하는 자리에서 센다
        for pronoun in ("제가", "우리는"):
            for distance, expected in ((11, True), (12, True), (13, False)):
                size = distance - len(pronoun)
                text = self.sentence(pronoun, size, "써 본 결과")
                with self.subTest(pronoun=pronoun, distance=distance):
                    self.assertEqual(caught(text), expected, f"거리 {distance}: {text}")

    def test_a_pronoun_right_before_the_modifier_word_counts(self):
        for text in ("제가 직접 써 본 결과 가나다 참고하세요.", "제가 써 본 결과 가나다 참고하세요.", "내가 이 제품을 써 본 결과 가나다 참고하세요.", "소음이 거의 없으니 제가 직접 써 본 후기를 가나다 참고하세요."):
            self.assertTrue(caught(text), text)

    def test_a_pronoun_inside_the_matched_word_counts_too(self):
        # '제가 다녀온' 은 대명사까지 한 낱말로 잡히는 꼴('제가다녀온')이다
        for text in ("제가 다녀온 후기를 가나다 참고하세요.", "제가 다녀온 곳은 가나다 참고하세요.", "제가 다녀온 곳이 어디인지 확인해 주세요."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (VISIT,), text)

    def test_a_pronoun_after_the_modifier_word_does_not_count(self):
        self.assertFalse(caught("직접 써 본 결과 제가 참고하세요."), "절 안의 대명사는 꾸미는 낱말의 주어가 아니다")
        self.assertFalse(caught("써 본 느낌을 저는 알려 주세요."))

    def test_a_pronoun_alone_without_a_modifier_word_is_not_a_violation(self):
        for text in ("제가 가나다 참고하세요.", "저는 아직 가나다라 기다립니다.", "우리는 가나다 알려 주세요."):
            self.assertFalse(caught(text), text)


class LettersInsideAWordTest(unittest.TestCase):
    """대명사 글자가 낱말 속에 있으면 글쓴이를 가리키는 말이 아니다 — 낱말이 시작하는 자리·끝나는 자리에서만 센다."""

    def test_letters_inside_another_word_are_not_the_writer(self):
        for text in ("요금제가 직접 써 본 결과 가나다 참고하세요.", "그 요금제가 직접 써 본 결과 가나다 참고하세요.", "우리가족이 직접 써 본 결과 가나다 참고하세요.", "저희가족이 직접 써 본 결과 가나다 참고하세요.",
                     "제가끔 직접 써 본 결과 가나다 참고하세요.", "일이 끝나는 날 직접 써 본 결과 가나다 참고하세요.", "요금제가 써 본 결과 가나다 참고하세요.", "우리가족이 써 본 후기를 가나다 참고하세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_the_same_pronoun_as_a_word_of_its_own_counts(self):
        for text in ("제가 직접 써 본 결과 가나다 참고하세요.", "요금제가 제가 직접 써 본 결과 가나다 참고하세요.", "우리가족이 우리가 직접 써 본 결과 가나다 참고하세요.", "제가, 직접 써 본 결과 가나다 참고하세요."):
            self.assertTrue(caught(text), text)

    def test_the_word_ends_where_a_space_or_a_mark_comes(self):
        self.assertTrue(caught("저는, 직접 써 본 결과 가나다 참고하세요."))
        self.assertTrue(caught('(제가) 직접 써 본 결과 가나다 참고하세요.'))
        self.assertFalse(caught("제가직접 써 본 결과 가나다 참고하세요."), "띄어쓰기를 빠뜨린 '제가직접' 은 한 낱말이라 대명사로 읽지 않는다")


class EachPronounTest(unittest.TestCase):
    """대명사 하나하나가 규칙을 켠다(하나를 목록에서 빼면 이 시험이 잡는다)."""

    SENTENCE = "{} 직접 써 본 결과 가나다 참고하세요."

    def test_each_of_the_listed_pronouns_alone_makes_the_violation(self):
        for pronoun in ("제가", "저는", "저도", "내가", "우리는", "우리가", "저희가", "저희는", "저희도", "저희만", "저희끼리"):
            with self.subTest(pronoun=pronoun):
                self.assertEqual(kinds(self.SENTENCE.format(pronoun)), (USE,))

    def test_naneun_is_not_a_writer_pronoun_because_it_is_also_a_verb(self):
        # '나는' 은 '소리가 나는'·'향이 나는' 의 동사와 겹쳐 대명사 목록에서 뺐다 — 독립 검증이 찾은 오탐(동사 '나는' 12문장 중 9개가 새로 걸렸다)
        self.assertIsNone(cl._WRITER.search("나는"))
        for text in ("소리가 나는 의자를 써 본 느낌을 솔직하게 알려 주세요.", "향이 나는 제품을 써 본 느낌을 솔직하게 알려 주세요.", "냄새가 나는 곳을 다녀온 후기를 자세히 남겨 주세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)
        # 추천 꼬리와 짧은 절이 붙어도 동사 '나는' 은 글쓴이가 아니다 — 대명사 '나는' 으로 시작하는 단정도 이 규칙으로는 못 건다(알려진 한계)
        for text in ("소리가 나는 의자를 써 본 결과 가나다 참고하세요.", "냄새가 나는 곳을 다녀온 후기를 가나다 참고하세요.", "나는 직접 써 본 결과 가나다 참고하세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_without_a_pronoun_the_same_sentence_passes(self):
        self.assertEqual(kinds(self.SENTENCE.format("")), ())
        self.assertEqual(kinds(self.SENTENCE.format("여러분이")), ())
        self.assertEqual(kinds(self.SENTENCE.format("고객님이")), ())

    def test_other_pronouns_or_the_possessive_forms_are_not_counted(self):
        for pronoun in ("저희", "저희를", "저희의", "우리", "제", "저의", "그가", "너는"):
            with self.subTest(pronoun=pronoun):
                self.assertEqual(kinds(self.SENTENCE.format(pronoun)), (), pronoun)

    def test_a_business_possessive_in_a_request_to_readers_passes(self):
        for text in ("저희 제품을 직접 써 본 느낌을 댓글로 편하게 남겨 주세요.", "저희 제품을 써 본 느낌을 댓글로 알려 주세요.", "저희 가게에 직접 다녀온 후기를 가나다 남겨 주세요.", "저희 서비스를 이용해 본 소감을 알려 주세요.",
                     "우리 제품을 써 본 느낌을 댓글로 알려 주세요.", "저희 앱을 써 본 분들의 의견을 기다립니다."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)


class PlansAndEmptyClausesAreNotClaimsTest(unittest.TestCase):
    """대명사가 계획·다짐의 주어이거나 사이에 서술 절이 없으면 이 규칙을 쓰지 않는다."""

    # 글쓴이 자신의 계획·다짐 꼬리 24종(`_PLEDGE`) — 앞의 절이 비어 있지 않아도 겪은 일의 단정이 아니다
    PLEDGES = (
        "제가 직접 써 본 뒤에 솔직한 후기를 올리겠습니다.", "제가 직접 써 본 뒤에 솔직한 후기를 올리겠어요.", "제가 직접 써 본 뒤에 솔직한 후기를 올리겠죠.", "제가 직접 써 본 뒤에 솔직한 후기를 올리겠지요.", "제가 직접 써 본 뒤에 솔직한 후기를 올리겠다.",
        "제가 직접 써 본 뒤에 솔직한 후기를 정리할게요.", "제가 직접 써 본 뒤에 솔직한 후기를 올려 볼게요.", "제가 직접 써 본 뒤에 솔직한 후기를 알려 드릴게요.", "제가 직접 써 본 뒤에 솔직한 후기를 공유할래요.",
        "제가 직접 써 본 뒤에 솔직한 후기를 올릴 예정입니다.", "제가 직접 써 본 뒤에 솔직한 후기를 올릴 예정이에요.", "제가 직접 써 본 뒤에 솔직한 후기를 올릴 계획입니다.", "제가 직접 써 본 뒤에 솔직한 후기를 올릴 계획이에요.",
        "제가 직접 써 본 뒤에 솔직한 후기를 올릴 생각입니다.", "제가 직접 써 본 뒤에 솔직한 후기를 올릴 생각이에요.", "제가 직접 써 본 뒤에 솔직한 후기를 올릴 생각이다.",
        "제가 직접 써 본 뒤에 솔직한 후기를 공유할 것입니다.", "제가 직접 써 본 뒤에 솔직한 후기를 공유할 거예요.", "제가 직접 써 본 뒤에 솔직한 후기를 공유할 겁니다.", "제가 직접 써 본 뒤에 솔직한 후기를 써 볼 겁니다.",
        "제가 직접 써 본 뒤에 솔직한 후기를 써 볼 거예요.", "제가 직접 써 본 뒤에 솔직한 후기를 올리려고 합니다.", "제가 직접 써 본 뒤에 솔직한 후기를 올리려고 해요.", "제가 직접 써 본 뒤에 솔직한 후기를 올리려고요.",
    )

    def test_a_plan_or_a_pledge_with_the_pronoun_as_its_subject_passes(self):
        self.assertEqual(len(self.PLEDGES), 24)
        self.assertEqual(wrongly_caught(self.PLEDGES), [])

    def test_a_pledge_followed_by_a_recommendation_word_still_passes(self):
        # 추천 꼬리 조건이 생긴 뒤로 계획 꼬리 제외는 '…올리겠습니다 참고하세요' 처럼 계획 뒤에 추천 낱말이 붙은 문장에서만 일을 한다 — 24종 각각을 못 박는다
        for text in self.PLEDGES:
            sentence = text[:-1] + " 참고하세요."
            with self.subTest(text=sentence):
                self.assertFalse(caught(sentence), sentence)
        for text in ("제가 써 본 뒤에 편하게 알려 드릴게요 참고하세요.", "저는 써 본 뒤에 후기를 올릴 예정입니다 확인해 주세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_every_pledge_word_is_also_a_request_ending_so_the_cut_finds_it(self):
        words = cl._PLEDGE.pattern.removeprefix("(?:").removesuffix(")").split("|")
        self.assertEqual(len(words), 24)
        for word in words:
            with self.subTest(word=word):
                self.assertIn(word, cl._REQUEST_WORDS)

    def test_plans_of_other_shapes_with_the_pronoun_pass(self):
        for text in ("제가 써 본 뒤에 알려 드릴게요.", "제가 써 본 뒤에 바로 알려 드릴게요.", "저는 직접 다녀온 뒤에 후기를 올릴 계획입니다.", "제가 써 본 뒤에는 솔직한 느낌을 꼭 공유할 생각이에요.",
                     "저는 다음 주에 직접 다녀온 뒤에 후기를 올릴 예정입니다.", "제가 써 본 뒤에 정리해서 공유해 드릴게요.", "저는 써 본 뒤에 후기를 꼭 남기려고 합니다.", "제가 써 본 뒤에 장단점을 솔직히 알려 드릴게요.",
                     "우리는 다녀온 뒤에 사진과 함께 후기를 올리겠습니다.", "제가 직접 써 본 후에 천천히 답변을 드리겠습니다.", "저도 설치해 본 뒤에 다시 글을 쓸 생각입니다.", "우리가 가 본 뒤에 일정을 공유할 예정이에요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_a_clause_that_goes_on_with_a_plan_passes(self):
        self.assertFalse(caught("제가 써 본 뒤에 후기를 올릴 테니 참고하세요."))
        self.assertFalse(caught("제가 써 본 뒤에 후기를 올릴 테니 기다려 주세요."))
        self.assertFalse(caught("제가 써 본 뒤에 올릴 테니 확인해 주세요."))

    def test_the_plan_word_has_to_be_in_the_clause_and_the_pledge_has_to_be_the_tail(self):
        self.assertTrue(caught("내일 쉴 테니 제가 직접 써 본 결과 가나다 참고하세요."), "'테니' 가 꾸미는 낱말 앞에 있다")
        self.assertTrue(caught("제가 직접 써 본 결과 가나다 참고하세요 나중에 올릴 테니 기다려 주세요."), "'테니' 가 부탁 뒤에 있다")
        self.assertTrue(caught("제가 직접 써 본 결과 가나다 참고하세요 또 알려 드릴게요."), "계획 꼬리가 첫 부탁 뒤에 있다")
        self.assertTrue(caught("제가 직접 써 본 결과 가나다 참고하세요 다음에 올릴 계획입니다."))

    def test_a_pledge_tail_does_not_hide_a_long_clause_the_old_rule_already_caught(self):
        self.assertTrue(caught("제가 직접 써 본 결과 가나다라마바사아 알려 드릴게요."))
        self.assertTrue(caught("제가 직접 써 본 결과 소음이 거의 없어서 계속 쓸 계획입니다."))
        self.assertTrue(caught("제가 직접 써 본 결과 가나다 올릴 테니 참고하세요."), "절이 길어('가나다올릴테니') 낡은 규칙이 이미 걸렀다")

    def test_a_request_to_readers_is_not_a_pledge(self):
        for text in ("제가 직접 써 본 결과 가나다 참고해 주시면 감사하겠습니다.", "제가 직접 써 본 결과 가나다 참고해 주시면 고맙겠습니다.", "제가 직접 써 본 결과 가나다 참고하시기 바랍니다.", "제가 직접 써 본 결과 가나다 참고해 주시길 바랍니다."):
            with self.subTest(text=text):
                self.assertTrue(caught(text), text)

    def test_without_a_clause_between_the_head_and_the_request_the_rule_stays_out(self):
        for text in ("제가 써 본 느낌을 알려 주세요.", "저는 이 제품을 사려는데 써 본 느낌을 알려 주세요.", "제가 직접 써 본 결과 참고하세요.", "제가 직접 써 본 결과를 참고하세요.", "저희가 다녀온 후기를 읽어 주세요.",
                     "소음이 거의 없으니 제가 직접 써 본 결과를 참고하세요.", "제가 써 본 후기를 확인해 주세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_a_third_person_or_a_negation_after_the_word_is_guarded_before_the_rule(self):
        for text in ("제가 올린 글을 읽어 본 분은 댓글 남겨 주세요.", "제가 아직 써 본 적이 없어서 써 본 분은 알려 주세요.", "저는 이 제품을 사려는데 써 본 분은 후기를 알려 주세요.", "저희 매장에 다녀온 분은 후기를 남겨 주세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)


class OthersWhoTriedAreNotTheWriterTest(unittest.TestCase):
    """꾸미는 낱말 바로 뒤가 '써 본 분의 후기'·'다녀온 분을' 처럼 해 본 사람이면 그 경험은 글쓴이 것이 아니다 — 앞에 대명사가 있어도(다른 절의 주어) 이 규칙을 쓰지 않는다."""

    PEOPLE = ("분의", "분을", "분에게", "분과", "분만", "분으로")

    def test_a_person_who_tried_is_somebody_else_with_every_particle(self):
        for particle in self.PEOPLE:
            text = f"저는 아직 못 써 봐서 직접 써 본 {particle} 가나다 참고하세요."
            with self.subTest(particle=particle):
                self.assertFalse(caught(text), text)

    def test_a_natural_sentence_with_a_negation_and_the_reviews_of_others_passes(self):
        for text in ("저는 써 본 적이 없어서 직접 써 본 분의 후기를 참고하세요.", "저는 아직 못 가 봐서 다녀온 분의 후기를 가나다 참고하세요.", "저는 못 먹어 봐서 먹어 본 분의 소감을 가나다 참고하세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_the_same_sentence_with_a_thing_instead_of_a_person_is_a_claim(self):
        for text in ("저는 아직 못 써 봐서 직접 써 본 후기를 가나다 참고하세요.", "저는 아직 못 써 봐서 직접 써 본 결과 가나다 참고하세요.", "제가 직접 써 본 분위기 가나다 참고하세요."):
            with self.subTest(text=text):
                self.assertTrue(caught(text), text)


class RuleRunsAfterTheConditionAndConnectiveChecksTest(unittest.TestCase):
    """독립 검증(c2bf)의 안 OW — 이 규칙은 이어 가는 낱말('직접 써서')과 조건('…면') 검사를 지난 뒤에만 본다. 독자에게 거는 조건 안내('…막히면 질문하세요')가 먼저 지나가고,
    글쓴이 경험 단정이어도 '…면' 낱말('…비교하면·…보면·…길다면')이 든 것은 걸지 못한다(알려진 한계) — 대명사가 없는 같은 문장도 낡은 규칙대로 새어 나간다."""

    def test_a_condition_inside_the_clause_makes_it_reader_advice_for_the_rule(self):
        text = "제가 직접 써 본 결과 소음이 거의 없고 가벼워서 출퇴근이 길다면 참고하세요."
        self.assertFalse(caught(text), "'…길다면' 조건이 있으면 독자에게 하는 안내로 본다 — 경험 단정이어도 이 규칙으로는 못 건다(한계)")
        self.assertFalse(caught(text.replace("제가 ", "")), "대명사가 없어도 같다")
        self.assertTrue(caught(text.replace("길다면", "길어서")), "조건 낱말만 바꾸면 같은 문장이 단정으로 걸린다")

    def test_a_connective_modifier_word_is_not_judged_by_the_rule(self):
        # '직접 써서'·'다녀와서' 는 같이 하는 일을 잇는 낱말이다 — '직접 써서 만든 자료' 의 '써서' 는 글을 썼다는 뜻일 수 있어 단정으로 보지 않는다
        for text in ("제가 직접 써서 소음이 거의 없어서 참고하세요.", "제가 직접 다녀와서 가나다 참고하세요.", "저는 직접 써서 가나다 참고하세요.", "제가 직접 써서 만든 자료를 참고하세요.", "제가 직접 써서 정리한 표를 참고하세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)
        self.assertFalse(caught("직접 써서 소음이 거의 없어서 참고하세요."))
        self.assertFalse(caught("직접 다녀와서 가나다 참고하세요."))
        self.assertTrue(caught("제가 직접 써 본 결과 소음이 거의 없어서 참고하세요."), "머리말이 '써 본 결과' 면 단정이다")

    def test_the_conditions_of_reader_advice_with_a_pronoun_pass(self):
        # 대명사가 다른 서술어의 주어인 독자 조건 안내 — 새 규칙이 '…면' 검사보다 앞이던 c2b 에서 새로 걸리던 모양('…나면·…막히면' 은 `_guarded` 14글자 조건 목록 밖)
        for text in ("제가 알려 드린 대로 따라 해 본 뒤 막히면 질문하세요.", "제가 알려 드린 대로 따라 해 본 뒤 오류가 나면 로그를 확인해 주세요.", "제가 알려 드린 대로 따라 해 본 뒤 막히면 아래 글을 참고하세요.",
                     "제가 올린 설정표를 보고 따라 해 본 뒤 문제가 생기면 확인해 주세요.", "제가 정리한 순서대로 써 본 뒤 이상한 점이 보이면 참고하세요.", "제가 직접 써 본 결과 소음이 거의 없고 가벼워서 참고하시면 감사하겠습니다."):          # 꼬리 바로 앞 낱말이 '…하시면' — 낱말 뒤 14글자 밖이라 `_guarded` 가 아니라 '…면' 검사가 가른다
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_the_conditions_of_reader_advice_without_a_pronoun_are_unchanged(self):
        for text in ("써 본 뒤에 오류가 나면 재부팅부터 해 보세요.", "설치해 본 뒤에 오류가 나면 재부팅부터 해 보세요.", "직접 가서 확인한 뒤 다시 정리해 보겠습니다.", "먹어 보고 나서 알레르기 반응이 나타나면 즉시 중단하세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_a_pledge_that_goes_with_a_condition_still_passes(self):
        for text in ("제가 써 본 뒤에 오류가 나면 알려 드릴게요.", "제가 직접 가서 확인한 뒤 다시 정리해 보겠습니다.", "저는 써 본 뒤에 불편한 점이 있으면 그대로 올리겠습니다."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_the_writers_own_continuing_if_is_not_a_condition(self):
        # '정리하면·요약하면·종합하면·말하면·말씀드리면·…자면' 은 글쓴이가 말을 잇는 '…면' — 독자에게 거는 조건이 아니라 경험 단정을 막지 않는다
        for text in ("제가 직접 써 본 결과를 요약하면 편해서 참고하세요.", "제가 직접 써 본 결과를 정리하면 가벼워서 참고하세요.", "제가 써 본 결과를 종합하면 만족해서 참고하세요.", "제가 써 본 결과를 한마디로 말하면 편해서 참고하세요.",
                     "제가 써 본 결과를 풀어 보자면 가벼워서 참고하세요."):
            with self.subTest(text=text):
                self.assertTrue(caught(text), text)

    def test_the_writers_other_if_words_are_taken_for_conditions_a_known_limit(self):
        # '비교하면·보면·생각하면' 같은 글쓴이의 '…면' 낱말은 독자 조건 안내와 가를 수 없어 걸지 못한다 — '화면·반면·수면' 처럼 '면' 으로 끝나는 명사·부사도 같다(검사가 낱말 끝 글자만 본다).
        # 같은 문장에서 '…면' 낱말만 빼면 걸린다
        for text, claim in (("제가 직접 써 본 결과 가격을 비교하면 편해서 참고하세요.", "제가 직접 써 본 결과 가격이 편해서 참고하세요."),
                            ("제가 직접 써 본 결과 화면 선명하고 속도 빨라 참고하세요.", "제가 직접 써 본 결과 선명하고 속도 빨라 참고하세요."),
                            ("제가 직접 써 본 결과 반면 품질도 의외로 좋아 참고하세요.", "제가 직접 써 본 결과 품질도 의외로 좋아 참고하세요."),
                            ("제가 직접 써 본 결과 다시 보면 가벼워서 참고하세요.", "제가 직접 써 본 결과 다시 가벼워서 참고하세요."),
                            ("제가 직접 써 본 결과 생각하면 편해서 참고하세요.", "제가 직접 써 본 결과 정말 편해서 참고하세요.")):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)
                self.assertTrue(caught(claim), claim)


class OnlyARecommendationTailCountsTest(unittest.TestCase):
    """독립 검증(c2bf)의 안 W — 이 규칙은 부탁 꼬리가 글쓴이가 겪은 일을 근거로 권하는 말(`_RECOMMEND`)일 때만 쓴다. 독자에게 경험을 청하는 부탁('알려 주세요'·'남겨 주세요')은 걸지 않는다."""

    RECOMMEND_TAILS = (("참고", "참고하세요"), ("확인해주세요", "확인해 주세요"), ("써보세요", "써 보세요"), ("가보세요", "가 보세요"), ("드셔보세요", "드셔 보세요"), ("믿고", "믿고 보세요"), ("구경해보세요", "구경해 보세요"),
                       ("추천", "추천해 주세요"))
    ASK_TAILS = ("알려 주세요", "남겨 주세요", "공유해 주세요", "의견 주세요", "말씀해 주세요", "질문해 주세요", "들려 주세요", "보내 주세요", "적어 주세요")

    def test_the_listed_recommendation_words_are_exactly_the_eight_and_each_one_alone_makes_the_violation(self):
        self.assertEqual(sorted(cl._RECOMMEND.pattern.split("|")), sorted(word for word, _ in self.RECOMMEND_TAILS))
        for word, tail in self.RECOMMEND_TAILS:
            text = f"제가 직접 써 본 결과 편해서 {tail}."
            with self.subTest(word=word):
                self.assertTrue(caught(text), text)

    def test_a_request_for_the_readers_own_experience_is_not_a_recommendation(self):
        for tail in self.ASK_TAILS:
            text = f"제가 직접 써 본 결과 편해서 {tail}."
            with self.subTest(tail=tail):
                self.assertFalse(caught(text), "경험을 청하는 꼬리는 이 규칙으로 걸지 않는다(한계: 단정 뒤에 부탁을 덧붙인 말도 못 건다)")

    def test_other_common_recommendations_are_left_out_on_purpose(self):
        # '이용해·사용해·방문해 보세요'·'구매하세요·예약하세요' 도 흔한 권유지만 더하지 않았다 — 독자에게 순서를 안내하는 문장('…해 본 뒤에 바로 사용해 보세요')의 새 오탐이 늘어서다(D-33 ⑬ ㉲ 빠진 꼬리 점검)
        for tail in ("이용해 보세요", "사용해 보세요", "체험해 보세요", "방문해 보세요", "들러 보세요", "구매하세요", "예약하세요"):
            text = f"제가 직접 써 본 결과 편해서 {tail}."
            with self.subTest(tail=tail):
                self.assertFalse(caught(text), "단정이어도 이 꼬리는 이 규칙으로 못 건다(한계) — 대신 독자 순서 안내의 오탐을 늘리지 않는다")
        for text in ("제가 정리한 순서대로 설치해 본 뒤에 바로 사용해 보세요.", "제가 올린 설정표를 보고 따라 해 본 뒤에 천천히 이용해 보세요.", "제가 쓴 가이드를 따라 해 본 뒤에 미리 예약하세요.",
                     "제가 올린 사진을 참고해 가 본 뒤에 꼭 방문해 보세요.", "제가 만든 체크리스트로 점검해 본 뒤에 신중하게 구매하세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_a_reader_step_with_a_try_it_tail_is_still_caught_a_known_weakness(self):
        # 알려진 약한 곳 — 독자에게 순서를 안내하는 문장에 '써·드셔 보세요' 꼬리가 붙으면 새로 걸린다(내 예문 45개 중 2개). 이 줄을 고치면 문서(D-33 ⑬ ㉲ 한계 ⑤)도 함께 고친다
        for text in ("제가 정리한 방법으로 써 본 뒤에 바로 써 보세요.", "제가 써 둔 레시피를 따라 만들어 본 뒤에 맛있게 드셔 보세요."):
            with self.subTest(text=text):
                self.assertTrue(caught(text), text)

    def test_other_endings_that_are_not_recommendations_pass_too(self):
        for tail in ("기다립니다.", "환영합니다.", "부탁드립니다.", "감사합니다.", "어떠세요?"):
            text = f"제가 직접 써 본 결과 편해서 {tail}"
            with self.subTest(tail=tail):
                self.assertFalse(caught(text), text)

    def test_the_reader_requests_the_independent_verification_found_pass(self):
        for text in ("제가 올린 사진을 보고 써 본 느낌을 댓글로 알려 주세요.", "제가 만든 앱을 써 본 느낌을 솔직하게 알려 주세요.", "우리가 만든 앱을 써 본 느낌을 솔직하게 남겨 주세요.", "제가 올린 코스를 따라 다녀온 후기를 댓글로 남겨 주세요.",
                     "제가 추천한 제품을 써 본 뒤 후기를 알려 주세요.", "제가 만든 앱을 써 본 느낌이 어떤지 알려 주세요.", "저는 이 제품을 사려는데 써 본 느낌을 솔직하게 알려 주세요.", "우리가 만든 앱을 써 본 느낌을 솔직하게 댓글로 남겨 주세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_a_long_clause_with_any_tail_is_still_caught_by_the_old_length_rule(self):
        for tail in self.ASK_TAILS[:3]:
            text = f"제가 직접 써 본 결과 가나다라마바사아 {tail}."
            with self.subTest(tail=tail):
                self.assertTrue(caught(text), text)
                self.assertTrue(caught(text.replace("제가 ", "")), "대명사가 없어도 낡은 길이 규칙이 건다")

    def test_the_recommendation_word_is_looked_for_from_the_last_word_before_the_cut_not_in_the_clause(self):
        self.assertFalse(caught("제가 직접 써 본 결과 참고돼 알려 주세요."), "절 안의 '참고' 는 꼬리가 아니다")
        self.assertFalse(caught("제가 직접 써 본 결과 추천돼 알려 주세요."), "절 안의 '추천' 도 마찬가지다")
        self.assertTrue(caught("제가 직접 써 본 결과 편해서 알려 주세요 참고하세요."), "끊는 자리 뒤의 추천 꼬리는 본다(첫 부탁이 경험을 청해도)")
        self.assertTrue(caught("제가 직접 써 본 결과 편해서 알려 주세요 가 보세요."))

    def test_the_other_limits_of_the_rule_still_hold_with_a_recommendation_tail(self):
        for text in ("제가 써 본 뒤에 알려 드릴게요 참고하세요.", "제가 써 본 뒤에 후기를 올릴 테니 참고하세요.", "저는 써 본 적이 없어서 직접 써 본 분의 후기를 참고하세요.", "제가 써 본 결과를 참고하세요.", "제가 직접 써 본 결과 참고하세요.", "저희 제품을 써 본 느낌을 참고하세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_a_disguised_question_claim_is_not_caught_by_this_rule_a_known_limit(self):
        self.assertFalse(caught("제가 직접 써 본 결과 편한 것 같은데 어떠세요?"), "단정 뒤에 묻는 꼬리 — 추천 꼬리가 아니라 이 규칙으로는 못 건다(한계)")
        self.assertTrue(caught("제가 직접 써 본 결과 편한 것 같은데 참고하세요."), "같은 단정에 추천 꼬리가 붙으면 걸린다")


class ScopeTest(unittest.TestCase):
    """영어·붙여 쓴 글·따옴표·사용자가 입력한 경험 — 이 규칙이 닿는 범위."""

    def test_english_sentences_are_not_touched(self):
        for text in ("If you have tried it yourself, please share your thoughts below.", "We would love to hear what you tried, so please share.", "Please tell me what you tried.", "I will try it myself and report back."):
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (), text)
        self.assertTrue(caught("I tried it myself and it was quiet so please check it out."), "영어 1인칭 경험은 영어 규칙이 이미 건다")

    def test_a_spaceless_text_does_not_know_the_words_and_is_judged_as_before(self):
        self.assertTrue(caught("제가직접써본결과가나다라마바참고하세요."), "붙여 쓴 글은 서술 절 쪽(엄격)")
        self.assertFalse(caught("제가써본뒤에알려드릴게요."), "계획 문장은 붙여 써도 그대로 통과")
        self.assertFalse(caught("제가써본느낌을알려주세요."))
        self.assertFalse(caught("제가써본결과가나다라참고하세요."), "낱말 경계를 모르면 1인칭 규칙을 쓰지 않고 길이 규칙만 본다(사이 4글자 + 부탁 낱말 2글자 = 6글자까지는 부탁)")
        self.assertFalse(caught("요금제가써본결과가나다라참고하세요."), "'요금제가' 속 '제가' 를 가를 수 없어서이기도 하다")
        self.assertTrue(caught("제가써본결과가나다라마참고하세요."), "7글자부터는 서술 절")

    def test_a_quoted_phrase_that_is_only_mentioned_stays_masked(self):
        self.assertFalse(caught('"제가 직접 써 본 결과 가나다"라는 후기를 참고하세요.'))

    def test_the_experience_the_user_gave_is_exempt_only_for_the_same_sentence(self):
        given = "제가 직접 써 본 결과 가나다 참고하세요."
        self.assertEqual(kinds(given, experience_given=True, user_sentences=[given]), ())
        self.assertEqual(kinds(given, experience_given=True, user_sentences=["다른 문장입니다."]), (USE,))
        self.assertEqual(kinds(given, experience_given=False, user_sentences=[given]), (USE,))

    def test_the_rule_works_inside_a_text_of_several_sentences_and_in_find_claims(self):
        text = "안녕하세요. 제가 직접 써 본 결과 편해서 참고하세요. 가격은 확인하세요."
        found = cl.find_violations(text)
        self.assertEqual([(claim.category, claim.position) for claim in found], [(USE, 1)])
        self.assertIn(USE, [claim.category for claim in cl.find_claims(text) if cl.is_violation(claim.category)])

    def test_a_question_to_the_reader_stays_a_question_but_a_disguised_claim_does_not(self):
        self.assertFalse(caught("제가 써 본 뒤에 어떠셨는지 알려 주세요."))
        self.assertFalse(caught("제가 직접 써 본 결과 가나다 어떠세요?"))
        self.assertFalse(caught("제가 직접 써 본 결과 편한 것 같은데 어떠세요?"), "c2b 는 걸었지만 꼬리가 추천류가 아니라 이 규칙으로는 못 건다(OnlyARecommendationTailCountsTest 의 한계)")
        self.assertTrue(caught("제가 직접 써 본 결과 편한 것 같은데 참고하세요."), "같은 단정이 추천 꼬리와 붙으면 걸린다")


class ProbeHeadsAndAdverbsTest(unittest.TestCase):
    """앞 말과 머리말의 변형 — 대명사와 낱말 사이에 목적어·때·장소가 끼어도 같은 문장이다."""

    def test_an_object_a_time_or_a_place_between_the_pronoun_and_the_modifier_word(self):
        for text in ("내가 이 제품을 써 본 결과 가나다 참고하세요.", "내가 이 제품을 직접 써 본 결과 가나다 참고하세요.", "저는 지난달에 직접 써 본 결과 가나다 참고하세요.", "우리는 어제 이 식당에 다녀온 후기는 가나다 참고하세요.",
                     "저희는 이 호텔을 직접 가 본 후기는 가나다 참고하세요."):
            with self.subTest(text=text):
                self.assertTrue(caught(text), text)


class ObjectEndedClauseIsAReaderGuideTest(unittest.TestCase):
    """절이 '…을·…를' 로 끝나면 추천 꼬리가 받는 목적어('결과를 확인해 주세요')라 독자에게 순서를 안내하는 말이다 — 걸지 않는다(c2bf 2차, 독립 재확인의 안 P)."""

    def test_a_reader_guide_whose_clause_ends_with_an_object_marker_is_not_caught(self):
        for text in ("제가 정리한 순서대로 설치해 본 뒤 결과를 확인해 주세요.",
                     "제가 정리한 방법으로 써 본 뒤에 결과를 참고하세요.",
                     "제가 알려 드린 대로 따라 해 본 뒤 결과를 확인해 주세요.",
                     "제가 정리한 순서대로 해 본 뒤 설정을 확인해 주세요."):
            with self.subTest(text=text):
                self.assertFalse(caught(text), text)

    def test_the_known_loss_is_a_short_experience_claim_that_ends_with_an_object(self):
        self.assertFalse(caught("제가 직접 써 본 결과 장점을 참고하세요."), "독자 순서 안내와 가를 수 없어 일부러 걸지 않는다(한계 ⑧ — 기준선도 못 걸던 것)")

    def test_the_same_claims_without_an_object_marker_are_still_caught(self):
        for text in ("제가 직접 써 본 결과 편한 것 같은데 참고하세요.", "내가 이 제품을 써 본 결과 가나다 참고하세요."):
            with self.subTest(text=text):
                self.assertTrue(caught(text), text)


class WriterRuleIsLinearTest(unittest.TestCase):
    """새 규칙이 긴 글에서 제곱 시간이 되지 않는다(낱말마다 앞 12글자와 절만 본다). 한 문장 시험의 단위는 걸리지 않는 계획 문장이라 문장 끝까지 낱말마다 새 줄을 지난다 —
    첫 위반에서 끝나는 단위로는 새 줄의 비용을 재지 못한다(독립 검증 권장 4: 결과는 같고 제곱 시간인 변이를 잡으려면 끝까지 도는 입력이 필요하다)."""

    def timed(self, text):
        start = time.perf_counter()
        cl.find_violations(text)
        return time.perf_counter() - start

    def test_one_long_sentence_with_many_pronoun_and_modifier_forms_is_linear(self):
        unit = "제가 써 본 뒤에 후기를 올릴 테니 참고하세요 "                       # 걸리지 않는 단위 — 대명사·꾸미는 낱말·계획 표지가 있어 규칙의 모든 조건을 지나간다
        self.assertFalse(cl.find_violations(unit * 3), "단위가 걸리면 첫 위반에서 끝나 비용을 못 잰다")
        first, second = self.timed(unit * 3000), self.timed(unit * 9000)
        if second >= max(first, 0.05) * 6:                                                                                   # 바쁜 PC 에서 한 번 튄 값일 수 있어 한 번 더 재고 빠른 쪽을 쓴다
            first, second = min(first, self.timed(unit * 3000)), min(second, self.timed(unit * 9000))
        self.assertLess(second, max(first, 0.05) * 6, f"3배 입력이 {second / max(first, 0.001):.1f}배 걸렸다(선형이면 3 안팎)")

    def test_one_long_sentence_without_a_recommend_word_after_it_is_linear(self):
        unit = "제가 써 본 결과 편해서 알려 주세요 "                              # 걸리지 않고 추천 낱말이 뒤에 없는 단위 — 추천 꼬리 검색이 문장 끝까지 훑으면 제곱 시간이 된다(독립 재확인이 찾음)
        self.assertFalse(cl.find_violations(unit * 3), "단위가 걸리면 첫 위반에서 끝나 비용을 못 잰다")
        first, second = self.timed(unit * 2000), self.timed(unit * 6000)
        if second >= max(first, 0.05) * 6:                                                                                   # 바쁜 PC 에서 한 번 튄 값일 수 있어 한 번 더 재고 빠른 쪽을 쓴다
            first, second = min(first, self.timed(unit * 2000)), min(second, self.timed(unit * 6000))
        self.assertLess(second, max(first, 0.05) * 6, f"3배 입력이 {second / max(first, 0.001):.1f}배 걸렸다(선형이면 3 안팎)")

    def test_many_sentences_are_linear(self):
        unit = "제가 직접 써 본 결과 가나다 참고하세요. 요금제가 써 본 느낌을 알려 주세요. "
        first, second = self.timed(unit * 1000), self.timed(unit * 3000)
        self.assertLess(second, max(first, 0.05) * 20, f"3배 입력이 {second / max(first, 0.001):.1f}배 걸렸다(선형이면 3 안팎)")


if __name__ == "__main__":
    unittest.main()
