"""'지어내지 않기' 검사의 새 규칙(부탁·꾸미는 낱말·1인칭 표지·설문·질문 말투·창 길이 …)을 변이 시험으로 확인해, 살아남은 변이마다 그 한 곳만 건드려야 결과가 달라지는 문장을 하나씩 고정한다.

원칙: 문장 전체를 `find_violations` 에 넣어 분류의 튜플을 통째로 견준다(`()` 는 지나간다는 뜻). 기대값은 규칙의 뜻(부탁·질문·조건이면 지나가고, 겪은 일을 단정하면 걸린다)에서 정했다.
한 문장에는 그 낱말(끝말·표지) 하나만 이유가 되도록 했다 — 같은 뜻의 다른 낱말이 함께 있으면 하나를 지워도 결과가 같아 변이를 놓친다. 네트워크·파일 없이 돈다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.check import claims as cl  # noqa: E402

USE, VISIT, BUY, INCOME, EFFECT, DIALOGUE, CASE = (cl.EXPERIENCE_USE, cl.EXPERIENCE_VISIT, cl.EXPERIENCE_BUY, cl.EXPERIENCE_INCOME, cl.EXPERIENCE_EFFECT, cl.DIALOGUE, cl.CASE)


def kinds(text, **options):
    return tuple(claim.category for claim in cl.find_violations(text, **options))


def review_kinds(text):
    return tuple(claim.category for claim in cl.find_reviews(text))


class Table(unittest.TestCase):
    def check(self, rows):
        for text, expected in rows:
            with self.subTest(text=text):
                self.assertEqual(kinds(text), expected)


class RequestEndingsTest(Table):
    """'다녀온 후기' 같은 꾸미는 모양은 부탁·다짐·안내로 끝나면 지나간다 — 끝말마다 그 끝말 하나만 이유가 되는 문장."""

    def test_every_request_ending_alone_lets_the_modifier_form_pass(self):
        self.check((
            ("다녀온 후기를 남겨 주시기를 부탁드립니다", ()),          # 부탁드립니다(6글자 — REQUEST_SPAN 이 이보다 작으면 못 찾는다)
            ("다녀온 후기를 올려 주시는 분을 환영합니다", ()),         # 환영합니다
            ("다녀온 후기를 기다립니다", ()),                          # 기다립니다
            ("다녀온 후기를 먼저 확인해야 합니다", ()),                 # 해야합니다
            ("다녀온 후기를 공유해 주셔서 감사합니다", ()),             # 감사합니다
            ("다녀온 후기를 남기실 수 있습니다", ()),                   # 수있습니다
            ("다녀온 후기를 곧 올릴 예정입니다", ()),                   # 예정입니다
            ("다녀온 후기를 곧 공유할게요", ()),                        # 할게요
            ("다녀온 후기를 곧 올리려고 합니다", ()),                   # 려고합니다
            ("다녀온 후기를 같이 공유합시다", ()),                      # 합시다
        ))

    def test_a_request_in_the_middle_of_the_sentence_counts_too(self):
        self.check((
            ("다녀온 후기를 남겨 주시면 확인합니다", ()),               # 주시면
            ("다녀온 후기를 남겨 주실 분을 찾습니다", ()),              # 주실분
            ("다녀온 후기를 정리해 주실 거라 믿습니다", ()),            # 해주실
        ))

    def test_the_same_modifier_form_as_a_plain_report_is_a_violation(self):
        self.check((
            ("다녀온 후기를 올렸습니다", (VISIT,)),
            ("다녀온 후기를 먼저 확인했습니다", (VISIT,)),
            ("다녀온 후기를 남겨 주셨습니다", (VISIT, DIALOGUE)),
        ))


class ModifierWordsTest(Table):
    """꾸미는 낱말('써 본 경험'·'다녀온 곳'·'방문한 매장' …)로 끝난 낱말은 부탁 안에서 지나가고, 끝맺은 모양은 걸린다."""

    def test_each_modifier_word_passes_inside_a_request(self):
        self.check((
            ("써 본 경험을 알려 주세요", ()),                            # 경험
            ("다녀온 곳을 알려 주세요", ()),                            # 곳
            ("방문한 매장을 알려 주세요", ()),                          # 매장
            ("들어서자마자 보인 점을 알려 주세요", ()),                  # 자마자
            ("갔다가 알게 된 점을 알려 주세요", ()),                     # 다가
        ))


class HowToGuideTest(Table):
    """'다녀온 후기를 쓰는 방법' 처럼 쓰는 법을 안내하는 말은 겪은 일의 보고가 아니다 — 보고 낱말('후기'·'소감' …)과 안내 낱말('요령'·'가이드'·'팁' …)이 함께 있을 때만."""

    def test_a_report_word_with_a_how_to_word_after_it_passes(self):
        self.check((
            ("다녀온 소감을 남기는 방법을 알려드립니다", ()),            # 보고 낱말 '소감'
            ("다녀온 후기를 쓰는 요령을 알려드립니다", ()),              # 안내 낱말 '요령'
            ("다녀온 후기를 쓰는 가이드를 알려드립니다", ()),            # 안내 낱말 '가이드'
            ("다녀온 후기를 쓰는 팁을 알려드립니다", ()),                # 안내 낱말 '팁'
            ("다녀온 후기를 쓰는 양식을 알려드립니다", ()),
            ("다녀온 후기를 쓰는 절차를 알려드립니다", ()),
            ("다녀온 후기를 쓰는 순서를 알려드립니다", ()),
        ))

    def test_without_a_how_to_word_the_same_report_word_is_a_violation(self):
        self.check((
            ("직접 다녀온 길을 알려드립니다", (VISIT,)),
            ("다녀온 소감을 알려드립니다", (VISIT,)),
            ("다녀온 후기를 알려드립니다", (VISIT,)),
            ("직접 다녀온 방법을 알려드립니다", (VISIT,)),               # c2-fix: 꾸미는 말('온'·'한')만으로는 방법 안내가 아니다 — '직접 다녀온 방법' 은 겪은 일을 단정하는 말이다(앞 판은 통과로 박아 두었다)
            ("제가 직접 설치한 방법을 알려드립니다", (USE,)),
        ))

    def test_a_how_to_word_after_a_closed_form_does_not_make_it_a_guide(self):
        self.check((
            ("써 보니 방법이 쉬웠습니다", (USE, EFFECT)),
        ))


class SelfMarkTest(Table):
    """묻는 말 꼴이어도 1인칭·때 표지가 있으면 독자에게 묻는 말이 아니라 자기 경험이다 — 표지마다 그 표지 하나만 든 문장."""

    def test_one_marker_alone_turns_a_question_into_a_claim(self):
        self.check((
            ("제가 써 보니 어떠셨나요?", (USE,)),
            ("어제 써 보니 어떠셨나요?", (USE,)),
            ("실제로 써 보니 어떠셨나요?", (USE,)),
            ("지난주 써 보니 어떠셨나요?", (USE,)),
            ("방금 써 보니 어떠셨나요?", (USE,)),
        ))

    def test_the_same_questions_without_a_marker_pass(self):
        self.check((
            ("써 보니 어떠셨나요?", ()),
            ("써 보니 어땠어요?", ()),
        ))


class SurveyTest(Table):
    """조사에 응한 사람들의 대답을 옮기는 말은 글쓴이가 겪은 대화가 아니다 — 조사 표지마다 하나만 든 문장."""

    def test_each_survey_marker_alone_lets_a_quoted_answer_pass(self):
        self.check((
            ("설문에서 많은 분들이 만족한다고 답했습니다", ()),
            ("통계상 많은 분들이 만족한다고 답했습니다", ()),
            ("열 명 중 아홉 명이 만족한다고 답했습니다", ()),
            ("응답했던 분들이 만족한다고 답했습니다", ()),
            ("80%가 만족한다고 답했습니다", ()),
        ))

    def test_without_a_survey_marker_the_same_answer_is_a_dialogue(self):
        self.check((
            ("많은 분들이 만족한다고 답했습니다", (DIALOGUE,)),
            ("친구들이 만족한다고 답했습니다", (DIALOGUE,)),
        ))


class QuestionShapeTest(Table):
    """묻는 말인지 — 물음표가 없어도 묻는 어미로 끝나면 묻는 말이고, 전각 물음표·닫는 괄호도 따진다. 과거형 서술이 들어 있으면 묻는 꼴로 위장한 선언이다."""

    def test_a_question_ending_without_a_question_mark_is_a_question(self):
        self.check((
            ("써 보니 만족하실까요", ()),                                 # 까요
            ("써 보니 어떻습니까", ()),                                  # 니까
            ("써 보니 어때요", ()),                                      # 어때요
            ("써 보니 어떠세요", ()),                                    # 어떠세요
        ))

    def test_a_statement_that_only_ends_alike_is_not_a_question(self):
        self.check((
            ("써 보니 좋습니다", (USE,)),
            ("써 보니 괜찮아요", (USE,)),
        ))

    def test_a_fullwidth_question_mark_and_a_closing_bracket_count(self):
        self.check((
            ("써 보니 어땠어요？", ()),
            ("(써 보니 어땠어요?)", ()),
            ("써 보니 어땠어요?」", ()),
        ))

    def test_a_past_statement_with_only_a_question_mark_is_still_a_claim(self):
        self.check((
            ("써 보니 편했지요?", (USE, EFFECT)),
            ("써 보니 편했잖아요?", (USE, EFFECT)),
            ("써 보니 편했거든요?", (USE, EFFECT)),
            ("써 보니 편했구나?", (USE, EFFECT)),
            ("써 보니 편했는걸요?", (USE, EFFECT)),
            ("써 보니 편했더라구요?", (USE, EFFECT, DIALOGUE)),
        ))

    def test_a_question_about_the_time_passes_even_when_a_soft_word_is_in_it(self):
        self.check((
            ("다녀와서 어떠셨어요?", ()),
            ("다녀와서 푹 쉬었습니다", (VISIT, USE)),
        ))


class WordStartTest(Table):
    """1인칭 표지는 낱말이 시작하는 자리에서만 센다 — '끝나는' 속의 '나는' 은 글쓴이가 아니고, 띄어쓰기가 여러 번 앞에 있어도 문장 맨 앞이어도 '저는' 은 글쓴이다."""

    def test_a_first_person_word_inside_another_word_is_not_the_writer(self):
        self.check((
            ("일이 끝나는 대로 서류를 제출했습니다", ()),
            ("저는 오늘 서류를 제출했습니다", (USE,)),
            ("어제 비가 와서 집에서 저는 서류를 제출했습니다", (USE,)),
            ("아이가 떠나는 날 서류를 제출했습니다", ()),
        ))


class GuardWindowTest(Table):
    """'하지 않은 일' 표지는 걸린 낱말 바로 뒤 14글자 안에서만 찾는다 — 12글자 뒤에서 끝나는 '으면' 은 보이고 13글자 뒤에서 시작하는 것은 보이지 않는다."""

    def test_a_guard_ending_exactly_at_the_window_edge_is_seen(self):
        self.check((
            ("방문했습니다" + "가" * 12 + "으면", ()),
            ("방문했습니다" + "가" * 13 + "으면", (VISIT,)),
            ("방문했습니다" + "가" * 11 + "으면", ()),
            ("방문했습니다" + "가" * 20 + "으면", (VISIT,)),
        ))

    def test_the_question_tail_is_taken_out_before_the_window_is_cut(self):
        self.check((
            ("방문했습니다 아닌가요 " + "가" * 12 + "으면", ()),
            ("방문했습니다 아닌가요 " + "가" * 13 + "으면", (VISIT,)),
            ("방문했습니다 아닌가요", (VISIT,)),
        ))


class WindowLengthTest(Table):
    """창 길이 — 1인칭 표지와 과거형 서술 사이는 14글자까지, '직접' 과 '사용했' 사이는 10글자까지만 이어서 본다."""

    def test_the_first_person_gap_is_fourteen_characters(self):
        for gap, expected in ((0, (USE,)), (13, (USE,)), (14, (USE,)), (15, ()), (16, ())):
            text = "저는 " + "가" * gap + "했습니다"
            with self.subTest(gap=gap):
                self.assertEqual(kinds(text), expected)

    def test_the_use_gap_after_direct_is_ten_characters(self):
        for gap, expected in ((0, (USE,)), (9, (USE,)), (10, (USE,)), (11, ()), (12, ())):
            text = "직접" + "가" * gap + "사용했습니다"
            with self.subTest(gap=gap):
                self.assertEqual(kinds(text), expected)


class GuardWordsTest(Table):
    """걸린 낱말 바로 뒤의 말이 '하지 않은 일'·'꾸미는 말'이면 지나간다 — 가드 낱말마다 그 낱말 하나만 이유가 되는 문장."""

    def test_a_modifier_form_of_an_introduced_person_passes(self):
        self.check((
            ("지인이 알려 준 정보입니다", ()),
            ("지인이 알려 주던 정보입니다", ()),
            ("지인이 알려 주는 정보입니다", ()),
            ("지인이 알려 줄 정보입니다", ()),
            ("친구가 추천해 준 곳입니다", ()),
            ("동료가 권해 준 방법입니다", ()),
            ("언니가 소개해 준 가게입니다", ()),
            ("지인이 알려 줬습니다", (DIALOGUE,)),
        ))

    def test_a_thing_made_for_the_post_is_not_an_experience(self):
        self.check((
            ("내용을 표로 만들어 보았습니다", ()),
            ("수치를 그래프로 만들어 보았습니다", ()),
            ("경험을 글로 만들어 보았습니다", ()),
            ("다른 방식으로 만들어 보았습니다", ()),
            ("내용을 만들어 보았습니다", (USE,)),
        ))

    def test_a_condition_or_a_person_after_a_modifier_ending_passes(self):
        self.check((
            ("직접 다녀온 경우에만 후기를 씁니다", ()),
            ("직접 사용한 사람은 많지 않습니다", ()),
            ("직접 사용한 이용자는 많지 않습니다", ()),
            ("직접 사용한 길이 많지 않습니다", (USE,)),
        ))

    def test_a_not_yet_guard_inside_the_window_passes(self):
        self.check((
            ("써 봤다고 해봐야 소용없습니다", ()),
            ("써 봤다고 해도 믿기 어렵습니다", ()),
            ("써 봤다고 하여도 소용없습니다", ()),
            ("써 보니 별로라고 하시면 환불해 드립니다", ()),
            ("써 보니 방문하실 때 필요한 것입니다", ()),
            ("써 보니 구매하기 전에 알아야 할 점입니다", ()),
            ("써 보니 좋을지라도 비쌉니다", ()),
            ("써 보니 쓸 일이 있을때만 켭니다", ()),
            ("열어 봤자 소용없습니다", ()),
            ("써 봤자 달라질 것은 없습니다", ()),
        ))

    def test_a_guard_word_right_after_the_word_passes(self):
        self.check((
            ("방문했다고 해서 달라지는 건 없습니다", ()),
            ("방문했다고 해도 소용없습니다", ()),
            ("방문했다고 하여도 소용없습니다", ()),
            ("방문했다고 해봐야 소용없습니다", ()),
            ("실제 사례처럼 쓰지 않습니다", ()),
            ("직접 써본 듯이 쓰지 않습니다", ()),
            ("직접 써본 척 하지 않습니다", ()),
            ("직접 방문했다면 알려 주세요", ()),
            ("직접 방문했습니다", (VISIT,)),
        ))


class NeutralVerbsTest(Table):
    """알아보거나 따져 본 일('비교해 봤다'·'알아봤다')은 겪은 일이 아니다 — 낱말마다 그 낱말 하나만 이유가 되는 문장."""

    def test_a_neutral_verb_before_tried_passes(self):
        self.check((
            ("여러 제품을 비교해 봤습니다", ()),
            ("사실을 확인해 봤습니다", ()),
            ("가격을 검색해 봤습니다", ()),
            ("비용을 계산해 봤습니다", ()),
            ("원인을 분석해 봤습니다", ()),
            ("시간을 추정해 봤습니다", ()),
            ("무게를 측정해 봤습니다", ()),
        ))

    def test_a_cognitive_verb_before_looked_passes(self):
        self.check((
            ("가격을 알아봤습니다", ()),
            ("가격을 찾아봤습니다", ()),
            ("내용을 살펴봤습니다", ()),
            ("주변을 둘러봤습니다", ()),
            ("안을 들여다봤습니다", ()),
            ("숫자를 세어 봤습니다", ()),
            ("직접 알아봤습니다", ()),
            ("어제 가격을 찾아봤습니다", ()),
            ("직접 살펴봤습니다", ()),
        ))

    def test_other_verbs_before_tried_are_experiences(self):
        self.check((
            ("이 길을 걸어 봤습니다", (USE,)),
            ("이 설정을 해 본 결과 달라진 점은 없습니다", (USE,)),
            ("직접 이 길을 봤습니다", (USE,)),
            ("요즘 이 앱을 사용 중이에요", (USE,)),
        ))


class PlainDailyVerbsTest(Table):
    """표지 없이도 일상을 겪은 말로만 읽히는 과거형 서술은 걸리고, 해요체는 1인칭·때 표지가 있을 때만 걸린다."""

    def test_each_daily_verb_alone_is_a_claim(self):
        self.check((
            ("공원을 걸었습니다", (USE,)),
            ("한강변을 달렸습니다", (USE,)),
            ("친구와 놀았습니다", (USE,)),
            ("푹 잤습니다", (USE,)),
            ("버스를 탔습니다", (USE,)),
            ("크게 웃었습니다", (USE,)),
            ("손을 씻었습니다", (USE,)),
        ))

    def test_a_polite_past_needs_a_personal_signal(self):
        self.check((
            ("오늘 방이 환해졌어요", (USE,)),
            ("어제 방이 환해졌어요", (USE,)),
            ("정말 방이 환해졌어요", (USE,)),
            ("진짜 방이 환해졌어요", (USE,)),
            ("너무 방이 환해졌어요", (USE,)),
            ("가족 덕분에 방이 환해졌어요", (USE,)),
            ("친구 덕분에 방이 환해졌어요", (USE,)),
            ("확실히 방이 환해졌어요", (USE,)),
            ("오늘 방이 환했는데요", (USE,)),
            ("방이 환해졌어요", ()),
            ("설정이 바뀌었어요", ()),
            # c2-fix: 이번·지난·처음·그날 같은 때 표지와 훨씬·완전·꽤 같은 정도 낱말은 기사·정보 글(…이번 개정으로 수수료가 낮아졌어요)에도 흔해 그것만으로는 겪은 일로 읽지 않는다(앞 판은 이 말들을 신호로 박아 두었다)
            ("이번에 방이 환해졌어요", ()),
            ("처음에는 방이 환해졌어요", ()),
            ("지난달부터 방이 환해졌어요", ()),
            ("그날 방이 환해졌어요", ()),
            ("훨씬 방이 환해졌어요", ()),
            ("완전 방이 환해졌어요", ()),
            ("꽤 방이 환해졌어요", ()),
            ("엄청 방이 환해졌어요", ()),
            ("생각보다 방이 환해졌어요", ()),
            ("가족 요금제가 바뀌었어요", ()),
            ("친구 추천 이벤트가 끝났어요", ()),
        ))

    def test_every_remaining_signal_word_alone_makes_a_polite_past_an_experience(self):
        for word in ("제가", "저는", "저도", "저희", "제경우", "내가", "나는", "우리", "오늘", "어제", "아침", "점심", "저녁", "밤새", "새벽", "주말", "퇴근", "출근", "방금", "아까", "드디어", "결국", "역시", "정말",
                     "진짜", "너무", "기대보다", "막상", "확실히", "솔직히", "다행히", "아직도", "여전히"):
            text = f"{word} 방이 환해졌어요"
            with self.subTest(text=text):
                self.assertEqual(kinds(text), (USE,), text)

    def test_a_kinship_word_is_a_signal_only_when_it_is_a_person_with_a_particle(self):
        for particle in ("은", "는", "이", "가", "와", "과", "랑", "도", "를", "을", "에게", "한테", "께", " 덕분에"):
            for kin in ("가족", "남편", "아내", "엄마", "아빠", "아이", "친구", "부모", "동생", "언니", "오빠", "누나"):
                text = f"{kin}{particle} 방이 환해졌어요"
                with self.subTest(text=text):
                    self.assertEqual(kinds(text), (USE,), text)

    def test_a_signal_word_must_start_a_word(self):
        self.assertEqual(kinds("새 요금제가 바뀌었어요"), (), "'요금제가' 속 '제가' 는 글쓴이가 아니다")
        self.assertEqual(kinds("끝나는 날에 방이 환해졌어요"), (), "'끝나는' 속 '나는' 은 글쓴이가 아니다")
        self.assertEqual(kinds("나는 방이 환해졌어요"), (USE,))
        self.assertEqual(kinds("공기가 차가워서 정신이 번쩍 들었어요"), (EFFECT,), "'정신이 번쩍' 은 '이번' 이 든 글이 아니라 정신이 번쩍 든 체감이다")

    def test_a_word_about_a_report_just_before_the_verb_or_a_quoted_speech_after_it_passes(self):
        self.check((
            ("발표 후 쉬었습니다", ()),
            ("오늘 정말 맛있게 먹었어요라고 말하더라고요", (DIALOGUE,)),
            ("오늘 정말 맛있게 먹었어요", (USE,)),
        ))

    def test_a_question_to_the_reader_with_a_daily_verb_passes(self):
        self.check((
            ("푹 잤고 만족하셨나요?", ()),
            ("Have I used it before?", ()),
            ("I have used it before.", (USE,)),
        ))


class NarrativeKindTest(Table):
    """표지 뒤 과거형 서술은 문장 속 낱말로 분류가 갈리고, 글 쓰는 일·생각·바람을 말하는 낱말이 들어 있으면 지나간다."""

    def test_the_kind_follows_the_word_in_the_sentence(self):
        self.check((
            ("저는 부산으로 여행을 떠났어요", (VISIT,)),
            ("저는 새벽에 집에 도착했어요", (VISIT,)),
            ("저는 택배를 맡겼어요", (BUY,)),
            ("저는 월급을 털었어요", (INCOME,)),
            ("저는 어제 가족에게 답장을 보냈어요", (DIALOGUE,)),
            ("저는 달라졌어요", (EFFECT,)),
            ("저는 서류를 제출했습니다", (USE,)),
        ))

    def test_a_word_about_writing_or_thinking_lets_it_pass(self):
        self.check((
            ("저는 오늘 그 내용을 정리했습니다", ()),
            ("저는 오늘 보고서를 작성했습니다", ()),
            ("저는 오늘 사실을 확인했습니다", ()),
            ("저는 먼저 말씀드렸습니다", ()),
            ("저는 이번 주제를 정했습니다", ()),
            ("저는 이유를 밝혔습니다", ()),
            ("저는 그 사실을 알았습니다", ()),
            ("저는 가 보지는 못했습니다", ()),
        ))


class MoreRulesTest(Table):
    """폭넓게 잡는 규칙의 갈래마다 그 갈래 하나만 걸리는 문장."""

    def test_visit_branches(self):
        self.check((
            ("맛있게 먹고 왔습니다", (VISIT,)),
            ("전시를 관람했습니다", (VISIT,)),
            ("박물관에 입장했습니다", (VISIT,)),
            ("공항에 도착했습니다", (VISIT,)),
            ("다녀와서 푹 쉬었습니다", (VISIT, USE)),
        ))

    def test_buy_branches(self):
        self.check((
            ("환불을 받았습니다", (BUY,)),
            ("쿠폰을 받았습니다", (BUY,)),
            ("장바구니에 담았습니다", (BUY,)),
            ("택배가 도착했습니다", (BUY,)),
        ))

    def test_income_branches(self):
        self.check((
            ("이 제품을 득템했습니다", (INCOME,)),
            ("받은 용돈을 모두 저금했습니다", (INCOME,)),
            ("첫 주문이 들어왔습니다", (INCOME,)),
        ))

    def test_effect_branches(self):
        self.check((
            ("불편하지 않았습니다", (EFFECT,)),
            ("기분이 좋아졌습니다", (EFFECT,)),
            ("압도적이었습니다", (EFFECT,)),
            ("밤새 책을 읽었습니다", (EFFECT,)),
            ("기대 이상의 결과였습니다", (EFFECT,)),
            ("체중이 줄었습니다", (EFFECT,)),
            ("산미가 은은했습니다", (EFFECT,)),
            ("신선했습니다", (EFFECT,)),
        ))

    def test_dialogue_and_case_branches(self):
        self.check((
            ("강의를 들었습니다", (DIALOGUE,)),
            ("직원님과 연락처를 교환했습니다", (DIALOGUE,)),
            ("직원이 정중하게 응대했습니다", (DIALOGUE,)),
            ("후기에 답글을 달아드렸습니다", (DIALOGUE,)),
            ("동생 민수군은 매일 이 가게에 갑니다", (CASE,)),
            ("한 손님은 일찍 도착하셨습니다", (CASE,)),
            ("이웃집이 이사했습니다", (CASE,)),
        ))

    def test_a_soft_use_word_followed_by_a_past_statement(self):
        self.check((
            ("설거지를 하고 나니 어느새 저녁이었습니다", (USE,)),
        ))


class ReviewBranchesTest(unittest.TestCase):
    """확인 권장 — 갈래마다 그 갈래 하나만 걸리는 문장(숫자 없는 말은 미리 거르는 낱말도 함께)."""

    def check(self, rows):
        for text, expected in rows:
            with self.subTest(text=text):
                self.assertEqual(review_kinds(text), expected)

    def test_time_branches(self):
        self.check((
            ("저녁 7시 이후에는 닫습니다", (cl.TIME,)),
            ("약 3일입니다", (cl.TIME,)),
            ("하루 만에 끝났습니다", (cl.TIME,)),
            ("다섯 시간 반 걸립니다", (cl.TIME,)),
            ("5분 거리입니다", (cl.TIME,)),
            ("유효기간은 12개월입니다", (cl.TIME,)),
            ("3일간 진행합니다", (cl.TIME,)),
            ("걸리는 시간은 15분", (cl.TIME,)),
            ("30분 남짓입니다", (cl.TIME,)),
            ("보름 안에 끝납니다", (cl.TIME,)),
            ("반년 안에 끝납니다", (cl.TIME,)),
            ("한 시간 걸립니다", (cl.TIME,)),
        ))

    def test_stat_branches(self):
        self.check((
            ("참가자가 120명이 넘었습니다", (cl.STAT,)),
            ("자료를 보면 어렵습니다", (cl.STAT,)),
            ("5점 만점에 4점입니다", (cl.STAT,)),
            ("평점은 4점입니다", (cl.STAT,)),
            ("발표에 따라 달라집니다", (cl.STAT,)),
            ("세 배로 늘었습니다", (cl.STAT,)),
            ("두 배로 늘었습니다", (cl.STAT,)),
            ("3위를 차지했습니다", (cl.STAT,)),
            ("시장 점유율이 높습니다", (cl.STAT,)),
        ))

    def test_date_branches(self):
        self.check((
            ("3월 중순에 출시됩니다", (cl.DATE,)),
            ("첫째 주에 열립니다", (cl.DATE,)),
            ("마지막 주에 열립니다", (cl.DATE,)),
            ("다음 달 5일 출시 예정입니다", (cl.DATE,)),
            ("5일에 열립니다", (cl.DATE,)),
            ("상반기에 출시됩니다", (cl.DATE,)),
            ("상순에 열립니다", (cl.DATE,)),
            ("3분기에 출시됩니다", (cl.DATE,)),
            ("연말에 공개합니다", (cl.DATE,)),
            ("올해 3월에 공개합니다", (cl.DATE,)),
        ))


if __name__ == "__main__":
    unittest.main()
