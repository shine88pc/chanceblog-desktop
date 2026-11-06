"""개념군 표·일치 도구·신호 계산(`topics/concepts.py`) 시험 — P2b 보완 C1~C8.

지키는 것:
  C1) **표는 초기값 — 전략 원문 확인 전이다.** 모든 표의 값·개수를 못박고(`topics_concept_tables.py`) 모듈 머리말이 그 말과 표 이름을 적는다 — 원문에 맞춰 고칠 때 표와 이 시험의 같은 값을 의식적으로 함께 고친다.
  C2) **표 항목 전수 도달** — 표의 항목 하나를 단독으로(약한 표는 짝 표와 함께) 넣으면 자기 신호가 나온다. 죽은 항목(예전 영어 경험 규칙의 `hands-on`·`my experience` 같은)이 하나라도 생기면 실패한다.
  C3) **일반 낱말 금지** — 비교·모델·추천·구매·가격 … 같은 일반 낱말은 어느 단독 신호 표에도 없고, 낱말마다 `예시 {낱말} 글` 로 넣어도 신호가 없다. 약한 표의 낱말도 단독으로는 신호가 아니다.
  C4) 한국어 일치 규칙(정규화·띄어쓰기·하이픈·조사·붙여 쓴 복합어·보이지 않는 글자·한자·퍼센트·마스크) C5) 단정어 보호(의무·부정·질문·경고 말)
  C6) 영어 규칙(축약형·하이픈·구두점·접두 `*`·마스크·부정·`remediation`) C7) 영어 경험 문구 19개 도달·요청서의 탐지·비탐지 예·경계·대소문자·정규화 C8) 요청서가 적은 낱말 전부가 해당 개념군 신호로 잡힌다.
  C9) **낱말 경계 규칙(D-58, 보완 1차)** — 띄어쓰기 없는 표 항목이 띄어쓴 두 낱말에 걸쳐 우연히 이어 붙는 일치(`설치 매뉴얼` 의 ‘치매’)는 읽지 않는다: 두 글자 항목은 낱말 안에서만, 세 글자 이상은 첫 조각이 낱말 처음부터이고 뒤 조각이
      한글 한 글자가 아닐 때만. 표 항목 전수로 돌고, 낱말 단위로 띄어 쓴 이름(`허리 디스크`)·붙여 쓴 복합어·조사·띄어쓰기가 든 항목·받음 표지는 예전처럼 읽는다.
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topics_concept_tables import TABLES  # noqa: E402

from chanceblog_desktop.topics import concepts as cn  # noqa: E402

SINGLE_SIGNAL_TABLES = ("HEALTH_DISEASE_KO", "HEALTH_DISEASE_EN", "HEALTH_MEDICAL_KO", "HEALTH_MEDICAL_EN", "HEALTH_PRODUCT_KO", "HEALTH_PRODUCT_EN", "EXPERIENCE_GENRE_STRONG_KO", "EXPERIENCE_PHRASES_EN",
                        "SPONSOR_STRONG_EN")
MEDICAL_ASSERTIONS = ("치료된다", "치료됩니다", "치료가 된다", "완치된다", "will cure", "guaranteed to cure")                 # 의료 효능어를 품어 그 자체로 고위험+효과+단정인 서술


def show(entry):
    """표 항목 → 시험 글에 넣을 모양 — 끝 `*`(그 글자로 시작) 는 낱말이 되게 글자 하나를 붙인다."""
    return entry + "x" if entry.endswith("*") else entry


def health(entry):
    return cn.health_signals([f"예시 {show(entry)} 글"])


class TableValuesTest(unittest.TestCase):                                                                      # C1
    def test_the_module_says_the_tables_are_initial_values_and_names_them(self):
        doc = Path(cn.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
        self.assertIn("초기값 — 전략 원문 확인 전", doc)
        for name in ("HEALTH_SYMPTOM_KO", "HEALTH_DISEASE_KO", "HEALTH_EFFECT_KO", "HEALTH_MEDICAL_KO", "HEALTH_PRODUCT_KO", "HEALTH_ASSERT_KO", "HEALTH_ASSERT_EFFECT_KO", "HEALTH_ASSERT_SOFT_KO",
                     "HEALTH_MASKS_KO", "HEALTH_WARNING_KO", "SPONSOR_STRONG_KO", "SPONSOR_WEAK_KO", "SPONSOR_MARKERS_KO", "SPONSOR_MASKS_KO", "EXPERIENCE_GENRE_STRONG_KO", "EXPERIENCE_GENRE_WEAK_KO",
                     "EXPERIENCE_MARKERS_KO", "EXPERIENCE_MASKS_KO", "EXPERIENCE_PHRASES_EN", "GENERAL_WORDS"):
            self.assertIn(name, doc)

    def test_every_table_is_exactly_the_pinned_value(self):
        for name, expected in TABLES.items():
            with self.subTest(table=name):
                value = getattr(cn, name)
                if isinstance(expected, dict):
                    self.assertEqual({key: tuple(items) for key, items in value.items()}, expected)
                else:
                    self.assertEqual(tuple(value), expected)

    def test_the_sizes_are_the_documented_ones(self):
        sizes = {"HEALTH_SYMPTOM_KO": 39, "HEALTH_SYMPTOM_EN": 15, "HEALTH_DISEASE_KO": 71, "HEALTH_DISEASE_EN": 26, "HEALTH_EFFECT_KO": 34, "HEALTH_EFFECT_EN": 13, "HEALTH_MEDICAL_KO": 6,
                 "HEALTH_MEDICAL_EN": 11, "HEALTH_PRODUCT_KO": 45, "HEALTH_PRODUCT_EN": 22, "HEALTH_ASSERT_KO": 12, "HEALTH_ASSERT_EN": 10, "HEALTH_ASSERT_EFFECT_KO": 16, "HEALTH_ASSERT_EFFECT_EN": 10,
                 "HEALTH_ASSERT_SOFT_KO": 7, "HEALTH_ASSERT_SOFT_EN": 5, "HEALTH_MASKS_KO": 48, "HEALTH_MASKS_EN": 11, "HEALTH_WARNING_KO": 19, "HEALTH_WARNING_EN": 11, "NEGATION_TOKENS_EN": 5,
                 "SPONSOR_MARKERS_KO": 18, "SPONSOR_MASKS_KO": 15, "SPONSOR_STRONG_EN": 23, "SPONSOR_WEAK_EN": 7, "SPONSOR_MARKERS_EN": 8, "EXPERIENCE_GENRE_STRONG_KO": 7, "EXPERIENCE_GENRE_WEAK_KO": 2,
                 "EXPERIENCE_MARKERS_KO": 11, "EXPERIENCE_MASKS_KO": 13, "EXPERIENCE_PHRASES_EN": 19, "GENERAL_WORDS": 57}
        for name, size in sizes.items():
            with self.subTest(table=name):
                self.assertEqual(len(getattr(cn, name)), size)
        self.assertEqual(sum(len(items) for items in cn.SPONSOR_STRONG_KO.values()), 54)
        self.assertEqual(sum(len(items) for items in cn.SPONSOR_WEAK_KO.values()), 30)
        self.assertEqual(cn.SPONSOR_GROUPS, ("goods", "service", "payment", "affiliate", "reward"))
        self.assertEqual(dict(cn.GROUP_KO), {"symptom": "증상·상태", "effect": "효과·결과", "product": "제품·행위", "assertion": "단정·보장", "goods": "현물 제공", "service": "서비스 제공",
                                             "payment": "금전 제공", "affiliate": "제휴·수수료", "reward": "조건부 보상"})

    def test_a_table_has_no_duplicates_and_no_one_letter_korean_word(self):
        for name in TABLES:
            if name == "GENERAL_WORDS":
                continue
            value = getattr(cn, name)
            entries = [word for words in value.values() for word in words] if isinstance(value, dict) else list(value)
            with self.subTest(table=name):
                self.assertEqual(len(entries), len(set(entries)), "겹친 항목")
                for entry in entries:
                    korean = "".join(char for char in entry if "가" <= char <= "힣")
                    if korean and name.endswith("_KO"):
                        self.assertGreaterEqual(len(entry.replace(" ", "")), 2, f"한 글자 낱말은 표에 넣지 않는다: {entry}")


class EveryEntryIsReachableTest(unittest.TestCase):                                                            # C2
    HEALTH_TABLES = (("HEALTH_SYMPTOM_KO", "symptom"), ("HEALTH_SYMPTOM_EN", "symptom"), ("HEALTH_DISEASE_KO", "disease"), ("HEALTH_DISEASE_EN", "disease"), ("HEALTH_EFFECT_KO", "effect"),
                     ("HEALTH_EFFECT_EN", "effect"), ("HEALTH_MEDICAL_KO", "medical"), ("HEALTH_MEDICAL_EN", "medical"), ("HEALTH_PRODUCT_KO", "product"), ("HEALTH_PRODUCT_EN", "product"),
                     ("HEALTH_ASSERT_KO", "assert_strong"), ("HEALTH_ASSERT_EN", "assert_strong"), ("HEALTH_ASSERT_EFFECT_KO", "assert_effect"), ("HEALTH_ASSERT_EFFECT_EN", "assert_effect"),
                     ("HEALTH_ASSERT_SOFT_KO", "assert_soft"), ("HEALTH_ASSERT_SOFT_EN", "assert_soft"))

    def test_every_health_table_entry_alone_gives_its_own_signal(self):
        for table, field in self.HEALTH_TABLES:
            for entry in getattr(cn, table):
                with self.subTest(table=table, entry=entry):
                    found = getattr(health(entry), field)
                    self.assertTrue(any(item.rstrip("*") == entry.rstrip("*") for item in found), f"{table} 의 ‘{entry}’ 는 도달할 수 없다(죽은 항목) — {found}")

    def test_every_health_mask_hides_what_it_covers_so_the_text_alone_gives_no_signal(self):
        for table in ("HEALTH_MASKS_KO", "HEALTH_MASKS_EN"):
            for entry in getattr(cn, table):
                with self.subTest(table=table, entry=entry):
                    self.assertEqual(health(entry).key(), (0, 0, 0, 0), entry)

    def test_every_health_warning_word_marks_the_text_as_warned(self):
        for table in ("HEALTH_WARNING_KO", "HEALTH_WARNING_EN"):
            for entry in getattr(cn, table):
                with self.subTest(table=table, entry=entry):
                    self.assertTrue(health(entry).warned, entry)

    def test_every_strong_sponsor_entry_alone_is_a_suspicion_with_its_own_group(self):
        for group, words in cn.SPONSOR_STRONG_KO.items():
            for word in words:
                with self.subTest(group=group, word=word):
                    found = cn.sponsor_signals([f"예시 {word} 글"])
                    self.assertTrue(found.suspected, word)
                    self.assertIn(word, found.strong)
                    self.assertIn(group, found.groups)
        for word in cn.SPONSOR_STRONG_EN:
            with self.subTest(english=word):
                found = cn.sponsor_signals([f"about {show(word)} today"])
                self.assertTrue(found.suspected, word)
                self.assertTrue(any(item.rstrip("*") == word.rstrip("*") for item in found.english))

    def test_every_weak_sponsor_entry_is_nothing_alone_and_a_suspicion_with_a_marker(self):
        for group, words in cn.SPONSOR_WEAK_KO.items():
            for word in words:
                with self.subTest(group=group, word=word):
                    self.assertFalse(cn.sponsor_signals([f"예시 {word} 글"]).suspected, f"약한 낱말은 단독으로 신호가 아니다: {word}")
                    together = cn.sponsor_signals([f"예시 {word} 제공받았 글"])
                    self.assertTrue(together.suspected, word)
                    self.assertIn(group, together.groups)
        for word in cn.SPONSOR_WEAK_EN:
            with self.subTest(english=word):
                self.assertFalse(cn.sponsor_signals([f"about {show(word)} today"]).suspected, word)
                self.assertTrue(cn.sponsor_signals([f"{show(word)} received for the post"]).suspected, word)

    def test_every_sponsor_marker_turns_a_weak_word_into_a_suspicion(self):
        for marker in cn.SPONSOR_MARKERS_KO:
            with self.subTest(marker=marker):
                self.assertTrue(cn.sponsor_signals([f"예시 쿠폰 {marker} 글"]).suspected, marker)
        for marker in cn.SPONSOR_MARKERS_EN:
            with self.subTest(marker=marker):
                self.assertTrue(cn.sponsor_signals([f"coupon {show(marker)} here"]).suspected, marker)

    def test_every_sponsor_mask_hides_the_expression_it_covers(self):
        for entry in cn.SPONSOR_MASKS_KO:
            with self.subTest(mask=entry):
                self.assertFalse(cn.sponsor_signals([f"예시 {entry} 제공받음 글"]).suspected, entry)

    def test_every_experience_entry_is_reachable(self):
        for word in cn.EXPERIENCE_GENRE_STRONG_KO:
            with self.subTest(genre=word):
                self.assertIn(word, cn.experience_signals([f"예시 {word} 글"]).genre)
        for marker in cn.EXPERIENCE_MARKERS_KO:
            with self.subTest(marker=marker):
                self.assertTrue(cn.experience_signals([f"예시 후기 {marker} 글"]).marked, marker)
        for word in cn.EXPERIENCE_GENRE_WEAK_KO:
            with self.subTest(weak=word):
                found = cn.experience_signals([f"예시 {word} 글"])
                self.assertEqual((found.genre, found.marked, found.phrases), ((), False, ()), "후기·리뷰 단독은 신호가 아니다")
                self.assertTrue(cn.experience_signals([f"예시 {word} 솔직 글"]).marked)
        for phrase in cn.EXPERIENCE_PHRASES_EN:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, cn.experience_signals([f"Notes: {phrase} the app for a week"]).phrases, f"영어 경험 문구 ‘{phrase}’ 가 도달하지 못한다(죽은 항목)")
        for mask in cn.EXPERIENCE_MASKS_KO:
            with self.subTest(mask=mask):
                found = cn.experience_signals([f"예시 {mask} 글"])
                self.assertEqual((found.genre, found.marked), ((), False), mask)


class GeneralWordsTest(unittest.TestCase):                                                                     # C3
    def test_no_general_word_is_in_a_single_signal_table(self):
        general = {word.casefold() for word in cn.GENERAL_WORDS}
        for name in SINGLE_SIGNAL_TABLES + ("SPONSOR_STRONG_KO",):
            value = getattr(cn, name)
            entries = [word for words in value.values() for word in words] if isinstance(value, dict) else list(value)
            with self.subTest(table=name):
                self.assertEqual({entry.casefold() for entry in entries} & general, set())
                self.assertEqual({entry.casefold().rstrip("*") for entry in entries} & general, set())

    def test_every_general_word_alone_gives_no_signal_of_any_kind(self):
        self.assertEqual(len(cn.GENERAL_WORDS), 57)
        for word in cn.GENERAL_WORDS:
            with self.subTest(word=word):
                text = f"예시 {word} 글"
                self.assertEqual(cn.health_signals([text]).key(), (0, 0, 0, 0), word)
                self.assertFalse(cn.sponsor_signals([text]).suspected, word)
                found = cn.experience_signals([text])
                self.assertEqual((found.genre, found.marked, found.phrases), ((), False, ()), word)

    def test_the_three_words_the_request_names_are_in_the_list_and_nowhere_in_a_table(self):
        for word in ("비교", "모델", "추천"):
            self.assertIn(word, cn.GENERAL_WORDS)
            for name, expected in TABLES.items():
                if name != "GENERAL_WORDS":
                    entries = [item for items in expected.values() for item in items] if isinstance(expected, dict) else expected
                    self.assertNotIn(word, entries, name)

    def test_a_weak_health_word_alone_is_general_and_only_a_medical_assertion_stops_alone(self):
        for table in ("HEALTH_SYMPTOM_KO", "HEALTH_SYMPTOM_EN", "HEALTH_EFFECT_KO", "HEALTH_EFFECT_EN", "HEALTH_ASSERT_KO", "HEALTH_ASSERT_EN", "HEALTH_ASSERT_SOFT_KO", "HEALTH_ASSERT_SOFT_EN"):
            for entry in getattr(cn, table):
                with self.subTest(table=table, entry=entry):
                    s, e, p, a = health(entry).key()
                    self.assertEqual(p, 0)
                    self.assertFalse(s and e and a)
        for entry in cn.HEALTH_ASSERT_EFFECT_KO + cn.HEALTH_ASSERT_EFFECT_EN:
            with self.subTest(assertion=entry):
                s, e, p, a = health(entry).key()
                self.assertEqual((e, a), (1, 1))
                self.assertEqual(p, 1 if entry in MEDICAL_ASSERTIONS else 0, entry)


class KoreanMatchingTest(unittest.TestCase):                                                                   # C4
    def test_fold_removes_invisible_characters_normalizes_width_and_case_and_hanja(self):
        self.assertEqual(cn.fold("ＤＩＥＴ"), "diet")
        self.assertEqual(cn.fold("피" + chr(0x200B) + "로"), "피로")
        self.assertEqual(cn.fold("治療"), "치료")
        self.assertEqual(cn.fold("100%"), "100퍼센트")
        self.assertEqual(cn.fold("100 퍼센트"), "100퍼센트")
        self.assertEqual(cn.fold("100프로"), "100퍼센트")
        self.assertEqual(cn.compact("피로 해소-방법!"), "피로해소방법")

    def test_spacing_hyphens_and_particles_do_not_hide_a_word(self):
        for text in ("피로해소", "피로 해소", "피로-해소", "피로가 해소"):
            with self.subTest(text=text):
                self.assertTrue(cn.health_signals([text]).symptom, text)
                self.assertTrue(cn.health_signals([text]).effect, text)
        for text in ("업체로부터 제품을 제공받음", "제품제공받음", "제품 제공 받음", "제품을 제공받음", "제품은 제공을 받음"):
            with self.subTest(text=text):
                self.assertTrue(cn.sponsor_signals([text]).suspected, text)

    def test_invisible_characters_and_hanja_do_not_hide_a_word(self):
        self.assertEqual(cn.health_signals(["치" + chr(0x200B) + "료 방법"]).medical, ("치료",))
        self.assertEqual(cn.health_signals(["治療 방법"]).medical, ("치료",))
        self.assertEqual(cn.health_signals(["탈" + chr(0x3164) + "모 샴푸"]).disease, ("탈모",), "한글 채움 문자도 지운다")

    def test_a_mask_keeps_a_normal_word_from_being_read_as_a_table_word(self):
        for text in ("혈압계 추천 기준", "소화기 점검 주기 정리", "처방전 PDF 정리하는 앱 만들기", "자세히 알아보는 업무 자동화", "스트레스 테스트 결과 해석", "디지털 디톡스 하는 법", "완전 정복 엑셀 단축키",
                     "보장 범위 비교", "광고 차단 설정하는 방법", "모니터 암 설치 방법", "바로잡는 법"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).key(), (0, 0, 0, 0), text)
                self.assertFalse(cn.sponsor_signals([text]).suspected)

    def test_a_table_word_is_found_inside_a_longer_compound_word(self):
        self.assertTrue(cn.health_signals(["혈당관리 습관"]).disease)
        self.assertTrue(cn.health_signals(["영양제효능 정리"]).product)

    def test_a_word_in_one_text_never_joins_the_next_text(self):
        self.assertEqual(cn.health_signals(["영", "양제"]).product, (), "글 사이에 걸친 낱말은 읽지 않는다")
        self.assertEqual(cn.health_signals(["영양제", "구매"]).product, ("영양제",))
        self.assertFalse(cn.sponsor_signals(["협", "찬"]).suspected)

    def test_the_single_letter_cancer_word_is_not_in_the_table_but_the_phrases_are(self):
        self.assertEqual(cn.health_signals(["모니터 암 거치대", "암호화 설정"]).key(), (0, 0, 0, 0))
        for text in ("암 예방 식단", "유방암 검진", "암 환자 식단"):
            with self.subTest(text=text):
                self.assertTrue(cn.health_signals([text]).disease, text)


class AssertionGuardTest(unittest.TestCase):                                                                   # C5
    def key(self, text):
        return cn.health_signals([text]).key()

    def test_an_obligation_is_not_an_assertion(self):
        self.assertEqual(self.key("영양제는 반드시 알아야 할 것"), (0, 0, 1, 0))
        self.assertEqual(self.key("반드시 알아야 할 백업 설정"), (0, 0, 0, 0))
        self.assertEqual(self.key("영양제 반드시 효과"), (0, 1, 1, 1), "의무 꼴이 아니면 단정이다")

    def test_every_obligation_form_after_the_word_keeps_it_from_being_an_assertion(self):
        forms = ("해야", "야 할", "알아야", "지켜야", "챙겨야", "피해야", "확인해야", "기억해야", "필요", "하세요", "해요", "마세요", "봐야")
        for form in forms:
            with self.subTest(form=form):
                self.assertEqual(cn.health_signals([f"영양제 반드시 {form} 글"]).assert_strong, (), form)
        self.assertEqual(cn.health_signals(["영양제 반드시 효과"]).assert_strong, ("반드시",), "의무 꼴이 아니면 단정이다")

    def test_a_negation_or_a_question_right_after_the_word_is_not_an_assertion(self):
        self.assertEqual(self.key("영양제 효과를 보장하지 않는 이유")[3], 0)
        self.assertEqual(self.key("영양제 효과가 있는지 확인하는 방법")[3], 0)
        self.assertEqual(self.key("영양제 효과가 확실한지 확인")[3], 0)

    def test_a_warning_word_in_the_text_turns_every_assertion_off(self):
        self.assertEqual(self.key("영양제 효과 과장 광고 구별하는 법"), (0, 1, 1, 0))
        self.assertTrue(cn.health_signals(["영양제 효과 과장 광고 구별하는 법"]).warned)
        self.assertEqual(cn.HEALTH_WARNING_KO[0], "과장")

    def test_a_warning_word_cancels_the_assertion_words_in_korean_and_in_english(self):
        warned = cn.health_signals(["영양제 효과를 보장한다는 광고에 속지 않는 법"])
        self.assertTrue(warned.warned)
        self.assertEqual(warned.key()[3], 0)
        self.assertEqual(cn.health_signals(["영양제 효과를 보장한다는 광고"]).key()[3], 1, "경고 말이 없으면 같은 단정이 살아 있다")
        self.assertEqual(cn.health_signals(["beware of scam supplements guaranteed to work"]).key()[3], 0)
        self.assertEqual(cn.health_signals(["supplements guaranteed to work"]).key()[3], 1)

    def test_a_percent_figure_is_an_assertion_only_when_it_is_one_hundred(self):
        self.assertIn("100퍼센트", cn.health_signals(["탈모를 100% 치료하는 샴푸"]).assert_strong)
        self.assertEqual(cn.health_signals(["영양제 50% 할인 소식"]).assert_strong, (), "100 이 아닌 퍼센트는 단정이 아니다")
        self.assertIn("100퍼센트", cn.health_signals(["영양제 100프로 효과"]).assert_strong)

    def test_an_instant_word_counts_as_an_assertion_only_when_a_high_risk_target_is_there(self):
        self.assertEqual(self.key("즉시 적용할 수 있는 단축키 모음")[3], 0)
        self.assertEqual(self.key("혈압을 즉시 낮추는 영양제")[3], 1)


class EnglishMatchingTest(unittest.TestCase):                                                                  # C6
    def test_the_tokens_split_on_hyphens_punctuation_newlines_and_multiple_spaces(self):
        self.assertEqual(cn.english_tokens(cn.fold("Hands-on, my  experience\nwith it!")), ["hands", "on", "my", "experience", "with", "it"])

    def test_contractions_are_expanded(self):
        self.assertEqual(cn.english_tokens(cn.fold("I've used it, I'm sure, we're here, it'll work, I'd say, can't")), ["i", "have", "used", "it", "i", "am", "sure", "we", "are", "here", "it", "will", "work", "i", "would", "say", "ca", "not"])
        self.assertIn("i have used", cn.experience_signals(["I've used this for months"]).phrases)

    def test_a_trailing_star_means_starts_with_and_a_plain_entry_means_the_whole_token(self):
        self.assertEqual(cn.health_signals(["improving sleep"]).effect, ("improv*",))
        self.assertEqual(cn.health_signals(["improv"]).effect, ("improv*",))
        self.assertEqual(cn.health_signals(["the ease of use"]).effect, ("ease",))
        self.assertEqual(cn.health_signals(["increase easement"]).effect, ("increas*",), "‘ease’ 는 낱말 통째로만 맞는다")

    def test_english_masks_keep_normal_phrases_out(self):
        for text in ("pain points of the onboarding flow", "treat yourself to a break", "the economic depression of 1930", "a blood pressure monitor review", "stress test results", "the weight of the box"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).key()[2], 0, text)

    def test_a_negation_in_the_three_tokens_before_an_assertion_cancels_it_but_a_farther_one_does_not(self):
        self.assertEqual(cn.health_signals(["this is not a guaranteed cure for diabetes"]).assert_strong, (), "부정이 두 낱말 앞")
        self.assertEqual(cn.health_signals(["this is not even a guaranteed cure"]).assert_strong, (), "부정이 세 낱말 앞")
        self.assertEqual(cn.health_signals(["not this one is a guaranteed cure"]).assert_strong, ("guaranteed",), "부정이 네 낱말 앞이면 지켜 주지 않는다")

    def test_a_negation_in_the_three_tokens_before_an_assertion_cancels_it(self):
        self.assertEqual(cn.health_signals(["this supplement is not guaranteed to work"]).key()[3], 0)
        self.assertEqual(cn.health_signals(["this supplement is guaranteed to cure"]).key()[3], 1)

    def test_a_security_word_that_starts_like_a_medical_word_is_not_medicine(self):
        self.assertEqual(cn.health_signals(["remediation plan for the build"]).medical, ())
        self.assertEqual(cn.health_signals(["a prescription for the cold"]).medical, ("prescription*",))
        self.assertEqual(cn.health_signals(["secure your account", "discussion board", "painting tips", "treatise on plants"]).key(), (0, 0, 0, 0), "다른 낱말 속의 조각은 걸리지 않는다")


class EnglishExperienceTest(unittest.TestCase):                                                                # C7
    DETECT = ("I used this product for two weeks.", "After using the app, I noticed...", "I visited the hotel last weekend.", "I bought this with my own money.", "In my own use, the battery lasted...")
    NOT_DETECT = ("This guide is used to compare features.", "The model is widely used in automation.", "The hotel can be visited by train.", "This model is widely used in automation.")
    EXTRA_NOT_DETECT = ("tried and true methods", "a hands-on guide to local AI", "firsthand sources explained", "used cars and trucks", "who tested positive", "visited pages report", "the tried approach",
                        "bought out by a large firm", "hands-on tutorial", "my experiences vary")

    def phrases(self, text):
        return cn.experience_signals([text]).phrases

    def test_the_two_dead_old_entries_are_gone_and_every_phrase_is_a_token_run_of_two_to_four(self):
        for old in ("hands-on", "handson", "firsthand", "tried"):
            self.assertNotIn(old, cn.EXPERIENCE_PHRASES_EN)
        for phrase in cn.EXPERIENCE_PHRASES_EN:
            self.assertEqual(phrase, phrase.lower())
            self.assertTrue(2 <= len(phrase.split()) <= 4, phrase)
            self.assertNotIn(phrase, ("used", "tried", "visited"))
        for phrase in ("i used", "i tried", "my experience", "after using", "when i visited", "i visited", "i bought", "i tested", "in my own use"):
            self.assertIn(phrase, cn.EXPERIENCE_PHRASES_EN)

    def test_the_requests_detection_examples_are_detected_and_the_non_detection_examples_are_not(self):
        for text in self.DETECT:
            with self.subTest(text=text):
                self.assertTrue(self.phrases(text), text)
        for text in self.NOT_DETECT + self.EXTRA_NOT_DETECT:
            with self.subTest(text=text):
                self.assertEqual(cn.experience_signals([text]).phrases, (), text)
                self.assertEqual(cn.experience_signals([text]).genre, ())

    def test_every_phrase_is_reached_inside_a_sentence_and_the_word_boundary_is_kept(self):
        for phrase in cn.EXPERIENCE_PHRASES_EN:
            self.assertIn(phrase, self.phrases(f"Honestly, {phrase.upper()} the router."))
        self.assertEqual(self.phrases("I usedx the thing"), ())
        self.assertEqual(self.phrases("Hi used cars"), ())
        self.assertEqual(self.phrases("my experiences with it"), ())

    def test_case_width_hyphen_newline_contraction_and_extra_spaces_do_not_matter(self):
        for text in ("I USED it", "Ｉ" + chr(0x3000) + "ｕｓｅｄ it", "i-used it", "I\nused it", "I   used it", "I  used it", "I've used it"):
            with self.subTest(text=text):
                self.assertTrue(self.phrases(text), text)
        self.assertEqual(self.phrases("my  experience with the router"), ("my experience",), "공백이 둘이어도 같은 문구다(예전 규칙은 놓쳤다)")

    def test_the_phrase_in_a_second_text_is_found_too_and_no_phrase_spans_two_texts(self):
        self.assertTrue(cn.experience_signals(["router notes", "I tested the router"]).phrases)
        self.assertEqual(cn.experience_signals(["I", "used the router"]).phrases, ())


class RequestWordsTest(unittest.TestCase):                                                                     # C8
    def test_every_symptom_effect_product_and_assertion_word_of_the_request_reaches_its_group(self):
        for word in ("피로", "불면", "수면 장애", "통증", "붓기", "두통", "소화", "혈압", "체중", "집중력", "불안", "스트레스"):
            with self.subTest(symptom=word):
                found = cn.health_signals([f"예시 {word} 글"])
                self.assertTrue(found.symptom or found.disease, word)
        for word in ("회복", "개선", "완화", "예방", "치료", "교정", "감량", "증진", "향상", "해소"):
            with self.subTest(effect=word):
                found = cn.health_signals([f"예시 {word} 글"])
                self.assertTrue(found.effect or found.medical, word)
        for word in ("영양제", "건강기능식품", "의료기기", "자세교정기", "다이어트 제품", "운동 처방", "식이요법"):
            with self.subTest(product=word):
                self.assertTrue(cn.health_signals([f"예시 {word} 글"]).product, word)
        for word in ("확실히", "반드시", "즉시", "완전히", "무조건", "효과 있음", "낫는다", "없어진다", "치료된다"):
            with self.subTest(assertion=word):
                found = cn.health_signals([f"예시 {word} 글"])
                self.assertTrue(found.assert_strong or found.assert_effect or found.assert_soft, word)

    def test_the_eight_expressions_the_old_list_missed_are_recognized_as_a_state_or_effect(self):
        for word in ("숙면", "활력", "붓기", "피로 해소", "자세 개선", "체형 관리", "속 편한 습관", "집중력 향상"):
            with self.subTest(word=word):
                found = cn.health_signals([word])
                self.assertTrue(found.symptom, word)
                self.assertEqual(cn.health_signals([word]).key()[2], 0)

    def test_the_thirty_two_sponsor_words_of_the_request_are_twelve_strong_and_twenty_weak(self):
        strong = ("원고료", "원고비", "소정의 대가", "파트너 링크", "제휴 링크", "추천인 코드", "구매 수수료", "성과 수수료", "우수 후기", "후기 이벤트", "추첨 보상", "조건부 보상")
        weak = ("제품 제공", "무료 제공", "샘플 제공", "증정품", "체험 제품", "무상 제공", "숙박권", "식사권", "이용권", "초대권", "체험권", "서비스 제공", "무료 체험", "광고비", "활동비", "제작비",
                "커미션", "리워드", "포인트", "쿠폰")
        self.assertEqual((len(strong), len(weak)), (12, 20))
        for word in strong:
            with self.subTest(strong=word):
                self.assertTrue(cn.sponsor_signals([f"예시 {word} 글"]).suspected, word)
        for word in weak:
            with self.subTest(weak=word):
                self.assertFalse(cn.sponsor_signals([f"예시 {word} 글"]).suspected, word)
                self.assertTrue(cn.sponsor_signals([f"예시 {word} 제공받았 글"]).suspected, word)

    def test_the_hashtags_are_read_from_the_folded_text(self):
        for text in ("#ad this laptop is great", "#Sponsored post", "#gifted by a brand", "＃ａｄ this laptop"):
            with self.subTest(text=text):
                self.assertTrue(cn.sponsor_signals([text]).hashtag, text)
        self.assertFalse(cn.sponsor_signals(["#address book", "radio #ads"]).suspected)


def marked(text):
    return cn.compact_marked([cn.fold(text)])


def hits(table, text):
    joined, starts = marked(text)
    return cn.find_ko(joined, starts, table)


def boundary_tables():
    """띄어쓰기 없는 항목에 낱말 경계 규칙을 거는 표 전부 — (이름, 컴파일된 표, 항목들). 받음 표지(`SPONSOR_MARKERS_KO`)는 일부러 뺀다(예전처럼 찾는다)."""
    rows = [("증상", cn.Tables.s_weak, cn.HEALTH_SYMPTOM_KO), ("질환", cn.Tables.s_strong, cn.HEALTH_DISEASE_KO), ("효과", cn.Tables.e_gen, cn.HEALTH_EFFECT_KO), ("의료", cn.Tables.e_med, cn.HEALTH_MEDICAL_KO),
            ("제품", cn.Tables.p, cn.HEALTH_PRODUCT_KO), ("단정", cn.Tables.a_strong, cn.HEALTH_ASSERT_KO), ("효과 단정", cn.Tables.a_effect, cn.HEALTH_ASSERT_EFFECT_KO),
            ("약한 단정", cn.Tables.a_soft, cn.HEALTH_ASSERT_SOFT_KO), ("경고", cn.Tables.warn, cn.HEALTH_WARNING_KO), ("경험 장르", cn.Tables.g_strong, cn.EXPERIENCE_GENRE_STRONG_KO),
            ("후기·리뷰", cn.Tables.g_weak, cn.EXPERIENCE_GENRE_WEAK_KO), ("경험 표지", cn.Tables.g_mark, cn.EXPERIENCE_MARKERS_KO)]
    rows += [("협찬 강 " + group, cn.Tables.sp_strong[group], words) for group, words in cn.SPONSOR_STRONG_KO.items()]
    rows += [("협찬 약 " + group, cn.Tables.sp_weak[group], words) for group, words in cn.SPONSOR_WEAK_KO.items()]
    return rows


def pure_hangul(entry):
    return all("가" <= char <= "힣" for char in entry)


class WordBoundaryTest(unittest.TestCase):                                                                     # C9
    HEALTH_FIELDS = ("symptom", "disease", "effect", "medical", "product", "assert_strong", "assert_effect", "assert_soft")
    PAIRS = (                                                              # (글, 우연히 걸리면 안 되는 표 낱말) — 앞 낱말의 끝글자와 뒤 낱말의 첫글자가 이어 붙는 정상 글
        ("에어컨 설치 매뉴얼 보는 법", "치매"), ("가구 배치 매뉴얼 만들기", "치매"), ("월 구독비 만원 이하 SaaS 추천", "비만"), ("관리비 만 원 절약 방법", "비만"), ("고객 이탈 모델 만들기", "탈모"),
        ("이탈 모니터링 대시보드 구성", "탈모"), ("필요 산출물 목록 정리", "요산"), ("프로젝트 필요 산정 방법", "요산"), ("지방 간 택배 요금 비교", "지방간"), ("지방 간식 추천", "지방간"),
        ("거래처 방문 일정 정리 방법", "처방"), ("구입처 방식별 장단점", "처방"), ("계약서에 필요한 약관 항목 정리", "한약"), ("간단한 약정 비교", "한약"), ("개인정보 약관 확인하는 방법", "보약"),
        ("위치정보 약관 읽는 법", "보약"), ("수천 식당 데이터 분석 방법", "천식"), ("팀 소통 증진을 위한 확실한 방법", "통증"), ("트래픽 정체 중 우회 경로를 확실히 해소하는 방법", "체중"),
        ("수면 제품 추천 기준", "수면제"), ("영양 제품 비교", "영양제"), ("보충 제외 항목 정리", "보충제"), ("진통 제거 방법 비교", "진통제"), ("유산 균형 잡기", "유산균"),
        ("원고 비용 산정 방법", "원고비"), ("체험 단체 모집 안내", "체험단"), ("협력 업체 위협 찬성 의견", "협찬"), ("정확 실험 결과 정리", "확실"), ("교보 장비 목록 정리", "보장"),
    )

    def everything(self, text):
        found = cn.health_signals([text])
        return [item for name in self.HEALTH_FIELDS for item in getattr(found, name)] + list(cn.sponsor_signals([text]).strong) + list(cn.experience_signals([text]).genre)

    def test_two_words_that_only_touch_across_a_space_are_not_read_as_a_table_word(self):
        for text, word in self.PAIRS:
            with self.subTest(text=text):
                self.assertNotIn(word, self.everything(text), text)
        self.assertEqual(cn.health_signals(["에어컨 설치 매뉴얼을 완전히 개선하는 방법"]).key(), (0, 1, 0, 1), "‘치매’ 가 사라져도 효과·단정 낱말은 그대로 읽는다 — 대상이 없으니 중지가 아니다")

    def test_the_warning_words_follow_the_same_rule(self):
        for text in ("회사 기본 정책 정리", "제작사 기준 확인", "통신사 기본 요금 비교"):
            with self.subTest(text=text):
                self.assertFalse(cn.health_signals([text]).warned, text)
        for text in ("사기 피해 예방", "허위 광고 구별하는 법", "오해와 진실", "함정에 빠지지 않는 법", "소비자 사기 수법"):
            with self.subTest(text=text):
                self.assertTrue(cn.health_signals([text]).warned, text)

    def test_a_mark_or_hyphen_between_words_is_a_word_boundary_like_a_space_but_an_invisible_character_is_not(self):
        for text in ("설치-매뉴얼 보는 법", "설치/매뉴얼 보는 법", "설치·매뉴얼 보는 법", "설치\n매뉴얼 보는 법", "설치_매뉴얼 보는 법", "설치\t매뉴얼 보는 법"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).disease, (), text)
        self.assertEqual(cn.health_signals(["설치" + chr(0x200B) + "매뉴얼"]).disease, ("치매",), "보이지 않는 글자는 지우고 읽는다 — 낱말 경계가 아니다")

    def test_a_two_letter_word_is_read_only_inside_one_word(self):
        checked = 0
        for name, table, entries in boundary_tables():
            for entry in entries:
                if len(entry) != 2 or not pure_hangul(entry):
                    continue
                first, second = entry
                checked += 1
                with self.subTest(table=name, entry=entry):
                    self.assertIn(entry, hits(table, f"예시 {entry} 글"))
                    self.assertIn(entry, hits(table, f"예시 가{entry}나 글"), "붙여 쓴 복합어·조사는 읽는다")
                    for text in (f"예시 {first} {second} 글", f"예시 가{first} {second}나 글", f"예시 {first}-{second} 글", f"예시 가{first} {second} 글"):
                        self.assertNotIn(entry, hits(table, text), text)
        self.assertEqual(checked, 111, "표 항목 전수 — 표 크기가 바뀌면 이 수도 의식적으로 함께 고친다")

    def test_a_longer_word_is_read_across_spaces_only_from_the_start_of_a_word_and_never_ending_in_a_lone_letter(self):
        natural = blocked = 0
        for name, table, entries in boundary_tables():
            for entry in entries:
                if len(entry) < 3 or not pure_hangul(entry):
                    continue
                with self.subTest(table=name, entry=entry):
                    for cut in range(1, len(entry) - 1):                                      # 뒤 조각이 두 글자 이상 — 낱말 단위로 띄어 쓴 것
                        natural += 1
                        self.assertIn(entry, hits(table, f"예시 {entry[:cut]} {entry[cut:]} 글"), (entry, cut))
                        self.assertIn(entry, hits(table, f"예시 {entry[:cut]} {entry[cut:]}나 글"), "뒤 조각에 조사가 붙어도 읽는다")
                    for text in (f"예시 {entry[:-1]} {entry[-1]} 글", f"예시 {entry[:-1]} {entry[-1]}나 글",          # 꼬리가 한 글자(통째 낱말이든 조각이든)
                                 f"예시 가{entry[0]} {entry[1:]} 글"):                                               # 앞 낱말의 끝글자가 걸쳐 있다
                        blocked += 1
                        self.assertNotIn(entry, hits(table, text), text)
        self.assertEqual((natural, blocked), (212, 444), "표 항목 전수 — 표 크기가 바뀌면 이 수도 의식적으로 함께 고친다(제품 표 +11: 처방약 낱말 열한 개 D-133·D-137, 마스크 +7: 기기 암 여섯 D-136 · 보험 보장 하나 D-134 — 옛 (204, 423))")

    def test_names_written_as_whole_words_with_spaces_are_still_read(self):
        for text, field, entry in (("허리 디스크 운동", "disease", "허리디스크"), ("목 디스크 증상", "disease", "목디스크"), ("건강 식품 고르기", "product", "건강식품"), ("건강 기능 식품 고르기", "product", "건강기능식품"),
                                   ("자세 교정기 추천", "product", "자세교정기"), ("오메가 3 효능", "product", "오메가3"), ("의료 기기 구매", "product", "의료기기"), ("고 지혈증 관리", "disease", "고지혈증"),
                                   ("소화 불량 해소", "symptom", "소화불량"), ("공황 장애 극복", "disease", "공황장애"), ("불안 장애 증상", "disease", "불안장애")):
            with self.subTest(text=text):
                self.assertIn(entry, getattr(cn.health_signals([text]), field), text)
        self.assertIn("유료광고", cn.sponsor_signals(["유료 광고 포함 글"]).strong)
        self.assertIn("구매후기", cn.experience_signals(["구매 후기 정리"]).genre)

    def test_compound_words_particles_and_entries_with_their_own_space_are_read_as_before(self):
        self.assertEqual(cn.health_signals(["초기치매 증상"]).disease, ("치매",))
        self.assertEqual(cn.health_signals(["소아비만 관리"]).disease, ("비만",))
        self.assertEqual(cn.health_signals(["치매가 의심될 때"]).disease, ("치매",))
        self.assertIn("수면 장애", cn.health_signals(["수면 장애 개선"]).disease)
        self.assertIn("수면 장애", cn.health_signals(["수면장애 개선"]).disease)
        self.assertIn("어깨 결림", cn.health_signals(["어깨 결림 해소"]).symptom)
        self.assertIn("암 예방", cn.health_signals(["암 예방 식단"]).disease)
        self.assertTrue(cn.sponsor_signals(["제품은 제공을 받음"]).suspected, "띄어쓰기가 든 항목은 낱말 사이에 조사가 끼어도 읽는다")

    def test_the_receiving_markers_keep_the_old_loose_reading_because_their_endings_are_often_spaced_off(self):
        for text, marker in (("예시 제공 받았다 글", "제공받"), ("예시 지원 받아 쓴 글", "지원받"), ("예시 협찬 받은 글", "협찬받"), ("예시 작성 했다 글", "작성했"), ("예시 작성 한 글", "작성한"), ("예시 소 정의 글", "소정의")):
            with self.subTest(text=text):
                self.assertIn(marker, hits(cn.Tables.sp_marker, text), text)
        self.assertTrue(cn.sponsor_signals(["제품 제공 받아 쓴 후기"]).suspected)
        self.assertFalse(any(strict for _entry, _pattern, strict in cn.Tables.sp_marker), "받음 표지 표만 경계 규칙이 없다")

    def test_a_table_marks_every_single_word_entry_as_strict_and_the_others_not(self):
        self.assertEqual([(entry, strict) for entry, _pattern, strict in cn.compile_table(("치매", "수면 장애", "오메가3", "건강기능식품"))], [("치매", True), ("수면 장애", False), ("오메가3", True), ("건강기능식품", True)])
        self.assertEqual([strict for _entry, _pattern, strict in cn.compile_table(("치매", "수면 장애"), loose=True)], [False, False])
        for name, table, entries in boundary_tables():
            with self.subTest(table=name):
                self.assertEqual([entry for entry, _pattern, _strict in table], list(entries))
                for entry, _pattern, strict in table:
                    self.assertEqual(strict, " " not in entry, entry)

    def test_compact_marked_remembers_where_each_word_starts_and_the_text_matches_compact(self):
        joined, starts = cn.compact_marked(["설치 매뉴얼-a", "b c", ""])
        self.assertEqual(joined, "설치매뉴얼a" + cn.SEP + "bc" + cn.SEP)
        self.assertEqual(sorted(starts), [0, 2, 5, 7, 8])
        self.assertEqual(joined.replace(cn.SEP, ""), cn.compact("설치 매뉴얼-a") + cn.compact("b c"))
        self.assertEqual(cn.compact_marked([]), ("", frozenset()))

    def test_reads_as_one_word_looks_at_the_pieces_of_the_match(self):
        text, starts = marked("지방 간 택배")                                          # 지방간택배 — 낱말은 0·2·3 에서 시작한다
        self.assertEqual(starts, frozenset({0, 2, 3}))
        self.assertFalse(cn.reads_as_one_word(text, starts, 0, 3), "꼬리가 한 글자 낱말")
        self.assertTrue(cn.reads_as_one_word(text, starts, 0, 2), "낱말 안")
        self.assertFalse(cn.reads_as_one_word(text, starts, 1, 3), "두 글자는 걸치면 뒤 조각이 한 글자라 읽지 않는다")
        text, starts = marked("허리 디스크")
        self.assertTrue(cn.reads_as_one_word(text, starts, 0, 5))
        self.assertFalse(cn.reads_as_one_word(text, starts, 1, 5), "앞 낱말의 끝글자부터 걸쳤다")
        text, starts = marked("오메가 3")
        self.assertTrue(cn.reads_as_one_word(text, starts, 0, 4), "꼬리가 숫자면 읽는다")
        text, starts = marked("목 디스크")
        self.assertTrue(cn.reads_as_one_word(text, starts, 0, 4), "첫 조각이 한 글자여도 낱말이면 읽는다")
        text, starts = marked("영 양 제")
        self.assertFalse(cn.reads_as_one_word(text, starts, 0, 3), "글자를 하나씩 띄운 것은 읽지 않는다(알려진 한계)")


if __name__ == "__main__":
    unittest.main()
