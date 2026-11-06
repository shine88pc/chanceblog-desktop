"""건강 판정 보완 시험(WP-B, D-105·D-106) — 운영자 2026-11-06 결정: 건강 표시를 세 단계(A 표시만 / B 근거 확인 필요 / C 의료·효과 단정 위험)로 다시 정하고, 근거 점수 감점은
'근거가 필요한 주장에 실제 근거가 없을 때'로 좁힌다. 건강 낱말 목록(`concepts.py` 표)은 바꾸지 않았다 — 판정 단계와 감점 조건만 바뀌었다.

지키는 것:
  H1) 운영자 예시 네 개가 정확히 그 단계다(생활 습관 → 일반 / 수면 환경 점검 → 표시만 / 불면을 확실히 치료 → 단정 위험 / 영양제로 피로가 완전히 회복 → 자동 초안 중지).
  H2) **영양제 세 단계** — 단독은 표시만(감점 0) / 효능·증상 표현이 붙으면 근거 확인 필요(근거가 없으면 −20, 공식 출처가 있으면 0) / 치료·완치·보장·단정이 붙으면 단정 위험(중지).
  H3) **증상 낱말 단독**(피로·불면·통증·자세·체중) — 앞뒤가 평범한 말이면 표시만·감점 0·중지 아님(근거 점수가 건강 표시 없는 같은 후보와 같다).
  H4) **전체 64칸 조합표** — 손으로 쓴 표·식·고정 기준 ①~⑤·단조성(낱말을 더하면 단계가 내려가지 않는다)·칸마다 낱말을 조합한 한국어·영어 대표 글. H5) 일반 낱말만 있는 주제는 일반 H6) 마스크 낱말은 신호 아님.
  H7) 알림 문장: 코드 이름 목록 불변·새 문장에 파이썬 목록 꼴·영문 값 이름 없음. H8) `SAFETY_FLAGS`·표시 칸 모양 불변, 점수는 근거 한 항목만 바뀜. H9) 영어 문장. H10) 실시간 이슈(공식 출처 있음)는 B 이어도 감점 0.
  H11) 근거 점수 함수 `_evidence` 의 단계 인자·`needs_evidence`. H12) 제품·기기 이름 속 조각(`치료제` 속 ‘치료’)은 따로 세지 않는다 — 제품 표 항목 하나하나가 단독이면 표시만이다. **질환 이름 속 낱말은 센다**(수정 1차 —
      `암 예방 100% 보장` 은 질환 + 효과 + 단정이라 중지) — 옛 코드 차분에서 '옛 중지 → 새 중지 아님' 0. H13) 문서(D-105·D-106)·머리말 정정. H14) 알림 문장이 단계 뜻에 맞다·단조성의 예외 목록(수정 1차).
  H15) **건강 판정 문맥 구분(D-130~D-135, 운영자 2026-11-06 ~19:55 결정 ①②③)으로 의도적으로 갱신한 시험** — 이유는 각 시험의 주석에 있다: 64칸 표의 질환 두 줄(질환 단독 = 근거 확인 필요·질환 + 단정 = 단정 위험)·단정 칸이 '낱말이 있다' 가 아니라
      '효과 결과를 꾸민다' 로 바뀐 데 따른 칸 대표 글·질환 항목 전수의 기대·영양제 + 바로·즉시 시험. 새 시험은 `test_topics_health_context.py` 에 있다.
네트워크·파일·실제 시계·난수 없이 돈다. 시험 글은 모두 지어낸 일반 문장이다.
"""
import dataclasses
import itertools
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import concepts as cn  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402
from chanceblog_desktop.topics import notice as nt  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402
from chanceblog_desktop.topics import score as sc  # noqa: E402

A, B = ts.PROFILES["naver_a"], ts.PROFILES["naver_b"]
TODAY = "2026-11-10"
GENERAL, MARK, EVIDENCE, STOP = "general", "mark", "evidence", "stop"
RANK = {GENERAL: 0, MARK: 1, EVIDENCE: 2, STOP: 3}
CODE = {MARK: "HEALTH_TOPIC", EVIDENCE: "HEALTH_EFFECT", STOP: "HEALTH_STOP"}
BASE_EXPLAINER = gn.EVIDENCE_BASE["explainer"]            # 70


def stage(text):
    return sf.check_text([text]).stage


def codes(text):
    return [finding.code for finding in sf.check_text([text]).findings if finding.flag == "health_check"]


def candidate_evidence(text, *, extra=None, content_type="explainer"):
    """글 하나를 후보의 주제로 놓고 안전 표시 → 근거 점수까지 — `generate._finish` 가 하는 계산과 같은 호출이다."""
    made = ts.make(topic=text, content_type=content_type, primary_keyword="예시 키워드")
    report = sf.assess(made)
    return gn._evidence(made, report.flags, extra or gn._Extra(), report.stage)


def seed(**changes):
    return ts.example_seed(**{"seed_id": "s1", "keyword": "예시 로봇청소기", "major": "가전", "minor": "소형가전", **changes})


def run(profile=A, seeds=(), **options):
    return gn.generate(profile, seeds, (), (), TODAY, **options)


# 손으로 쓴 전체 조합표 — 한 줄 = 건강 대상 (증상 S, 질환 D, 제품 P, 의료 효능어 M), 네 칸 = (효과 E, 단정 A) = 0·0 / 0·1 / 1·0 / 1·1 일 때의 단계(코드의 표와 따로 적었다).
G_, A_, B_, C_ = GENERAL, MARK, EVIDENCE, STOP
HAND_TABLE = {
    (0, 0, 0, 0): (G_, G_, G_, G_),
    (1, 0, 0, 0): (A_, A_, A_, C_),
    (0, 1, 0, 0): (B_, C_, B_, C_),                 # D-134 의도적 갱신 — 질환 단독 = 근거 확인 필요, 질환 + 단정 = 단정 위험(운영자 ③, 옛: A_, A_, B_, C_)
    (1, 1, 0, 0): (B_, C_, B_, C_),                 # 같은 이유(증상 + 질환도 질환이 있으므로)
    (0, 0, 1, 0): (A_, C_, B_, C_),
    (1, 0, 1, 0): (B_, C_, B_, C_),
    (0, 1, 1, 0): (B_, C_, B_, C_),
    (1, 1, 1, 0): (B_, C_, B_, C_),
    (0, 0, 0, 1): (A_, C_, B_, C_),
    (1, 0, 0, 1): (B_, C_, B_, C_),
    (0, 1, 0, 1): (B_, C_, B_, C_),
    (1, 1, 0, 1): (B_, C_, B_, C_),
    (0, 0, 1, 1): (C_, C_, C_, C_),
    (1, 0, 1, 1): (C_, C_, C_, C_),
    (0, 1, 1, 1): (C_, C_, C_, C_),
    (1, 1, 1, 1): (C_, C_, C_, C_),
}
EFFECT_ASSERT = ((0, 0), (0, 1), (1, 0), (1, 1))
ALL_KEYS = tuple(itertools.product((0, 1), repeat=6))


def rule_stage(s, d, p, m, e, a):
    """운영자 결정 + 내 제안(⑥)을 식으로 다시 쓴 것 — 코드의 표와 따로 쓴 두 번째 기준이다."""
    if not (s or d or p or m):
        return GENERAL                                              # ① 건강 대상이 없으면 일반(효능·단정·일반 낱말만 있어도)
    if (p and (m or a)) or (e and a) or (m and a) or (d and a):    # ④ P + (M 또는 A) · ⑤ (대상) + E + A · M + A(치료를 단정 — 옛 16칸 표에서도 중지) · D + A(D-134 ③: 질환 + 강한 단정은 효과 동사가 없어도)
        return STOP
    if (p and (e or s or d)) or (m and (s or d or e)) or d:        # ③ P + (E 또는 S) (+ D) · S+M·D+M·M+E(⑥ 내 제안) · **D 하나라도 있으면 근거 확인 필요**(D-134 ② 정정: 옛 ② 는 D 단독도 표시만, D+E 만 근거 확인 필요)
        return EVIDENCE
    return MARK                                                      # ② S·P·M 하나만 · S+E·S+A(⑥)


# 단정 칸(A)의 한국어 낱말 — 의도적 갱신(D-130): '확실히' 는 뒤에서 꾸미는 서술어가 없으면 단정으로 세지 않으므로(범위 낱말) 늘 단정인 '100% 보장' 으로 바꿨다
KO_WORDS = {"s": "피로", "d": "당뇨", "p": "영양제", "m": "치료", "e": "개선", "a": "100% 보장"}
EN_WORDS = {"s": "fatigue", "d": "diabetes", "p": "supplements", "m": "treatment", "e": "relief", "a": "guaranteed"}


def sentence(key, words, neutral, prefix):
    """칸의 낱말을 S D P M E A 순서로 이어 만든 글 — 낱말이 하나도 없으면 `neutral`."""
    chosen = [words[name] for name, bit in zip("sdpmea", key, strict=True) if bit]
    return prefix + " ".join(chosen) if chosen else neutral


class OperatorExamplesTest(unittest.TestCase):                                                                  # H1
    ROWS = (
        ("잠들기 전 화면 사용을 줄이는 생활 습관", GENERAL, (), ""),
        ("잠이 잘 오지 않을 때 수면 환경을 점검하는 방법", MARK, ("health_check",), "HEALTH_TOPIC"),
        ("불면을 확실히 치료하는 방법", STOP, ("health_check",), "HEALTH_STOP"),
        ("영양제로 피로가 완전히 회복됩니다", STOP, ("health_check",), "HEALTH_STOP"),
    )

    def test_the_four_examples_land_exactly_where_the_operator_put_them(self):
        for text, expected, flags, code in self.ROWS:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.flags), (expected, flags))
                self.assertEqual([finding.code for finding in report.findings], [code] if code else [])

    def test_the_levels_and_the_automatic_draft_stop_follow_the_stage(self):
        general, mark, stop_one, stop_two = (sf.check_text([row[0]]) for row in self.ROWS)
        self.assertEqual((general.level, general.stop, general.health), (None, False, "general"))
        self.assertEqual((mark.level, mark.stop, mark.health), ("WARNING", False, "check"))
        self.assertEqual((stop_one.level, stop_one.stop, stop_one.health), ("ERROR", True, "stop"))
        self.assertEqual((stop_two.level, stop_two.stop, stop_two.health), ("ERROR", True, "stop"), "영양제로 피로가 완전히 회복됩니다 → 자동 초안 생성 중지")

    def test_a_candidate_with_the_same_text_gets_the_same_stage_through_assess_and_mark(self):
        for text, expected, flags, _code in self.ROWS:
            with self.subTest(text=text):
                made = ts.make(topic=text, content_type="explainer", primary_keyword="예시 키워드")
                self.assertEqual(sf.assess(made).stage, expected)
                self.assertEqual(sf.mark(made).safety_flags, flags)


class NutritionSupplementStagesTest(unittest.TestCase):                                                         # H2
    ALONE = ("영양제 구매 기준", "영양제 고르는 법", "영양제 복용 시간 정리", "영양제 가격 비교", "영양제 보관 방법 정리", "비타민 영양제 브랜드 추천", "영양제 순위 보는 법")
    EFFECT_OR_SYMPTOM = ("영양제 효능 정리", "영양제로 피로 개선하는 방법", "영양제가 숙면에 도움이 되는지 알아보기", "영양제 먹고 붓기 완화하기", "영양제 복용 후 집중력이 좋아지는 이유",
                         "영양제 피로 정리", "영양제 스트레스 관리")
    TREAT_OR_ASSERT = ("영양제로 불면증을 치료합니다", "영양제 효과 보장", "영양제로 완치된다는 소식", "이 영양제만 먹으면 무조건 좋아집니다", "영양제 100% 효과", "영양제 먹으면 피로가 즉시 풀립니다")

    def test_the_supplement_alone_is_only_marked_and_costs_no_evidence_points(self):
        for text in self.ALONE:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.flags, report.stop, codes(text)), (MARK, ("health_check",), False, ["HEALTH_TOPIC"]))
                self.assertEqual(candidate_evidence(text), BASE_EXPLAINER, "표시는 붙지만 근거 점수는 깎지 않는다")

    def test_the_supplement_with_an_effect_or_a_symptom_needs_evidence_and_loses_twenty_points_without_it(self):
        for text in self.EFFECT_OR_SYMPTOM:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.stop, codes(text)), (EVIDENCE, False, ["HEALTH_EFFECT"]))
                self.assertEqual(candidate_evidence(text), BASE_EXPLAINER - 20, "근거가 필요한 주장인데 근거가 없다")
                self.assertEqual(candidate_evidence(text, extra=gn._Extra(official=1)), gn.EVIDENCE_OFFICIAL, "공식 출처가 있으면 감점이 없다")
                self.assertEqual(candidate_evidence(text, extra=gn._Extra(independent=2)), gn.EVIDENCE_INDEPENDENT, "서로 독립인 출처 둘이 있어도 감점이 없다")
                self.assertEqual(candidate_evidence(text, extra=gn._Extra(independent=1)), BASE_EXPLAINER - 20, "독립 출처 하나는 근거가 아니다")

    def test_the_supplement_with_a_treatment_or_an_assertion_is_a_danger_that_stops_the_draft(self):
        for text in self.TREAT_OR_ASSERT:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.health, report.stop, report.level, codes(text)), (STOP, "stop", True, "ERROR", ["HEALTH_STOP"]))
                self.assertEqual(candidate_evidence(text), BASE_EXPLAINER - 20, "단정 위험도 근거가 없으면 −20 이다(어차피 자동 초안은 중지)")

    def test_the_three_stages_only_differ_by_the_claim_words_not_by_the_supplement_word(self):
        self.assertEqual([stage(text) for text in ("영양제", "영양제 효능", "영양제 효능 보장")], [MARK, EVIDENCE, STOP])
        self.assertEqual([stage(text) for text in ("영양제 피로", "영양제 피로 개선", "영양제 피로 개선 확실히")], [EVIDENCE, EVIDENCE, STOP])


class EffectAssertionSentenceTest(unittest.TestCase):                                                           # H2b
    def test_a_sentence_that_asserts_an_effect_counts_as_an_effect_and_an_assertion_at_once(self):
        # '사라집니다'·'없어진다'·'낫게' 같은 효과 단정 서술은 효과 낱말 표에는 없고(`assert_effect`) 효과(E)와 단정(A)을 함께 뜻한다 — 증상·질환과 만나면 단정 위험이다
        for text in ("피로가 사라집니다", "통증이 사라진다", "불면이 없어집니다", "체중이 없어진다", "당뇨가 사라진다", "자세가 낫게"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).concept_key()[4:], (1, 1), "효과(E)와 단정(A)이 함께 켜진다")
                self.assertEqual(stage(text), STOP)
        for text in ("오류가 사라집니다", "알림이 사라진다", "버그가 없어진다"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), GENERAL, "건강 대상이 없으면 효과 단정 서술만으로는 일반이다")

    def test_a_light_assertion_word_counts_only_when_it_modifies_an_effect_result_and_a_warning_word_turns_it_off(self):
        # 의도적 갱신(D-130·D-132, 운영자 2026-11-06 ~19:55 ①②): '즉시·바로' 는 제품·질환이 곁에 있다는 이유가 아니라 **효과 결과 서술어를 꾸밀 때** 단정이다 — 증상 + 즉시 + 효과 결과 = 단정 위험(옛: 표시만),
        # 영양제 + 행동 순서 바로 = 표시만(옛: 중지), 질환 단독은 근거 확인 필요(옛: 표시만). 경고 낱말(과장·허위·속지 …)이 있으면 모든 단정이 꺼진다는 규칙은 그대로다.
        self.assertEqual(stage("피로가 즉시 풀리는 방법"), STOP)
        self.assertEqual(stage("영양제 바로 먹는 법"), MARK)
        self.assertEqual(stage("당뇨 식단 바로 시작하기"), EVIDENCE)
        self.assertEqual(stage("즉시 적용하는 단축키 모음"), GENERAL)
        self.assertEqual(stage("영양제 효과를 보장한다는 광고"), STOP)
        self.assertEqual(stage("영양제 효과를 보장한다는 광고에 속지 않는 법"), EVIDENCE, "경고 낱말이 단정을 끈다 — 효과 낱말만 남아 근거 확인 필요")


class SymptomWordAloneTest(unittest.TestCase):                                                                  # H3
    WORDS = ("피로", "불면", "통증", "자세", "체중")
    FRAMES = ("{} 기록 앱 만들기", "주말에 {} 이야기 정리하기", "{} 관련 자료 모아 보기", "오늘 할 일과 {} 메모")

    def test_a_symptom_word_alone_in_an_ordinary_sentence_is_only_marked_and_never_stops(self):
        for word in self.WORDS:
            for frame in self.FRAMES:
                text = frame.format(word)
                with self.subTest(text=text):
                    report = sf.check_text([text])
                    self.assertEqual((report.stage, report.health, report.flags, report.stop, report.level), (MARK, "check", ("health_check",), False, "WARNING"))
                    self.assertEqual(codes(text), ["HEALTH_TOPIC"])

    def test_the_evidence_score_is_the_same_as_the_same_candidate_without_the_health_flag(self):
        for word in self.WORDS:
            for frame in self.FRAMES:
                text = frame.format(word)
                with self.subTest(text=text):
                    self.assertEqual(candidate_evidence(text), candidate_evidence("오늘 할 일 정리하기"), "건강 표시가 없는 같은 후보와 같다")
                    for content_type, base in gn.EVIDENCE_BASE.items():
                        self.assertEqual(candidate_evidence(text, content_type=content_type), base)

    def test_a_seed_made_of_a_symptom_word_makes_candidates_that_keep_the_plain_evidence_and_are_not_stopped(self):
        plain = run(A, [seed(keyword="예시 로봇청소기", seed_type="priority", priority=True)], target=100)
        for word in self.WORDS:
            found = run(A, [seed(keyword=f"예시 {word}", seed_type="priority", priority=True)], target=100)
            self.assertEqual(len(found.candidates), len(plain.candidates), word)
            for candidate in found.candidates:
                with self.subTest(word=word, topic=candidate.topic):
                    self.assertEqual(candidate.safety_flags[0], "health_check")
                    self.assertEqual((sf.assess(candidate).stage, sf.assess(candidate).stop), (MARK, False))
                    self.assertEqual(candidate.scores.factors.evidence, gn.EVIDENCE_BASE[candidate.content_type])
            self.assertEqual(sorted(c.scores.final for c in found.candidates), sorted(c.scores.final for c in plain.candidates), "점수가 건강 표시 없는 씨앗과 같다")


class CombinationTableTest(unittest.TestCase):                                                                  # H4
    def test_the_matrix_equals_the_hand_written_table_cell_by_cell(self):
        expected = {(*targets, effect, assertion): stages[number] for targets, stages in HAND_TABLE.items() for number, (effect, assertion) in enumerate(EFFECT_ASSERT)}
        self.assertEqual(len(expected), 64)
        self.assertEqual(dict(sf.HEALTH_MATRIX), expected)
        self.assertTrue(all(len(key) == 6 and set(key) <= {0, 1} for key in sf.HEALTH_MATRIX), "키는 (S, D, P, M, E, A) 여섯 값이다")

    def test_the_matrix_equals_the_written_rules_for_all_64_cells(self):
        for key in ALL_KEYS:
            with self.subTest(key=key):
                self.assertEqual(sf.HEALTH_MATRIX[key], rule_stage(*key))

    def test_the_stage_counts_are_what_the_operator_would_expect_to_see_at_a_glance(self):
        counts = {name: sum(1 for value in sf.HEALTH_MATRIX.values() if value == name) for name in sf.HEALTH_STAGES}
        self.assertEqual(sum(counts.values()), 64)
        self.assertEqual(counts, {GENERAL: 4, MARK: 5, EVIDENCE: 18, STOP: 37}, "건강 대상이 없는 4칸만 일반이다 — 의도적 갱신(D-134): 질환 두 줄의 표시만 4칸이 근거 확인 필요 2·단정 위험 2 로 올랐다(옛 일반 4·표시만 9·근거 확인 필요 16·단정 위험 35)")

    def test_the_fixed_criteria_hold_in_every_cell(self):
        for s, d, p, m, e, a in ALL_KEYS:
            key = (s, d, p, m, e, a)
            result = sf.HEALTH_MATRIX[key]
            with self.subTest(key=key):
                if not (s or d or p or m):
                    self.assertEqual(result, GENERAL, "① 건강 대상 낱말이 없으면 일반 — 효능·단정 낱말만 있어도")
                if (s, d, p, m, e, a) in ((1, 0, 0, 0, 0, 0), (0, 0, 1, 0, 0, 0), (0, 0, 0, 1, 0, 0)):
                    self.assertEqual(result, MARK, "② 증상·제품·의료 효능어 단독은 표시만")
                if (s, d, p, m, e, a) == (0, 1, 0, 0, 0, 0):
                    self.assertEqual(result, EVIDENCE, "② 정정(D-134, 운영자 ③): 질환 단독은 근거 확인 필요")
                if d and a and not (s or p or m or e):
                    self.assertEqual(result, STOP, "⑦ 질환 + 강한 단정은 효과 동사가 없어도 단정 위험(D-134, 운영자 ③)")
                if p and not m and not a and (e or s):
                    self.assertEqual(result, EVIDENCE, "③ 영양제 + (효능 또는 증상) → 근거 확인 필요")
                if p and (m or a):
                    self.assertEqual(result, STOP, "④ 영양제 + (치료 또는 단정) → 단정 위험")
                if (s or d or p or m) and e and a:
                    self.assertEqual(result, STOP, "⑤ (증상·질환·제품·의료) + 효과 + 단정 → 단정 위험")

    def test_the_unspecified_combinations_follow_the_documented_proposal(self):
        for key, expected in (((1, 0, 0, 1, 0, 0), EVIDENCE), ((0, 1, 0, 0, 1, 0), EVIDENCE), ((0, 1, 0, 1, 0, 0), EVIDENCE), ((1, 0, 0, 0, 1, 0), MARK), ((1, 0, 0, 0, 0, 1), MARK),
                              ((0, 1, 0, 0, 0, 1), STOP), ((0, 0, 0, 1, 1, 0), EVIDENCE), ((0, 0, 0, 1, 0, 1), STOP), ((0, 1, 1, 0, 0, 0), EVIDENCE)):         # D+A 는 의도적 갱신(D-134 — 옛 MARK)
            with self.subTest(key=key):
                self.assertEqual(sf.HEALTH_MATRIX[key], expected)

    def test_adding_an_effect_a_treatment_or_an_assertion_never_lowers_the_stage(self):
        for low, high in itertools.product(ALL_KEYS, repeat=2):
            if all(a <= b for a, b in zip(low, high, strict=True)):
                with self.subTest(low=low, high=high):
                    self.assertLessEqual(RANK[sf.HEALTH_MATRIX[low]], RANK[sf.HEALTH_MATRIX[high]])

    def test_every_cell_has_a_korean_and_an_english_sentence_made_of_its_words_that_lands_in_it(self):
        for key in ALL_KEYS:
            for words, neutral, prefix in ((KO_WORDS, "예시 일반 문장", "예시 "), (EN_WORDS, "notes on everyday planning", "notes on ")):
                text = sentence(key, words, neutral, prefix)
                with self.subTest(key=key, text=text):
                    self.assertEqual(cn.health_signals([text]).concept_key(), key)
                    report = sf.check_text([text])
                    self.assertEqual(report.stage, sf.HEALTH_MATRIX[key])
                    self.assertEqual(report.health, sf.HEALTH_STAGE_STATE[report.stage])
                    self.assertEqual(report.stop, report.stage == STOP)
                    self.assertEqual(codes(text), [CODE[report.stage]] if report.stage != GENERAL else [])
                    self.assertEqual(report.flags, ("health_check",) if report.stage != GENERAL else ())

    def test_the_stage_names_codes_and_states_are_the_documented_ones(self):
        self.assertEqual(sf.HEALTH_STAGES, (GENERAL, MARK, EVIDENCE, STOP))
        self.assertEqual(dict(sf.HEALTH_STAGE_CODE), CODE)
        self.assertEqual(dict(sf.HEALTH_STAGE_STATE), {GENERAL: "general", MARK: "check", EVIDENCE: "check", STOP: "stop"})
        self.assertEqual(dict(sf.HEALTH_STAGE_KO), {GENERAL: "일반 생활정보", MARK: "건강 정보 확인 필요(표시만)", EVIDENCE: "근거 확인 필요", STOP: "의료·효과 단정 위험"})
        self.assertTrue(set(sf.HEALTH_STAGE_CODE.values()) <= set(nt.CODES))
        self.assertNotIn("HEALTH_CLAIM", sf.HEALTH_STAGE_CODE.values(), "HEALTH_CLAIM 은 새 단계표에서 쓰이는 곳이 없다")

    def test_the_report_gives_the_korean_name_of_its_stage_for_the_screen(self):
        # 수정 1차: 쓰이지 않던 `HEALTH_STAGE_KO` 를 보고서의 `stage_name` 이 쓴다(화면용 한국어 이름표)
        for text, name in (("잠들기 전 화면 사용을 줄이는 생활 습관", "일반 생활정보"), ("영양제 구매 기준", "건강 정보 확인 필요(표시만)"), ("영양제 효능 정리", "근거 확인 필요"),
                           ("불면을 확실히 치료하는 방법", "의료·효과 단정 위험")):
            with self.subTest(text=text):
                self.assertEqual(sf.check_text([text]).stage_name, name)
        self.assertEqual(sf.SafetyReport((), ()).stage_name, "일반 생활정보")
        self.assertEqual({sf.SafetyReport((), (), stage=name).stage_name for name in sf.HEALTH_STAGES}, set(sf.HEALTH_STAGE_KO.values()))

    # 단조성의 **명시적 예외**(D-105 정정, 수정 1차). 단조성은 64칸 표의 성질이고(효과·치료·단정이 켜지면 단계가 내려가지 않는다), 글에 낱말을 더하는 시험에서는 `key()` 의 단정 계산이 가진
    # 세 가지 '단정 끄기' 규칙이 단계를 내릴 수 있다 — ① 경고 낱말이 글 **어디에 있든** 모든 단정을 끈다 ② 단정 낱말 **바로 뒤** 의 부정·의문 꼬리(`확실하지 않다`·`있을까`)가 그 단정을 끈다 ③ 의무꼴(`반드시 ~해야`).
    WARNING_WORDS = ("속지 않는 법", "과장 광고", "허위", "사기")
    TAIL_WORDS = ("하지 않다", "을까", "해야 한다")

    def test_adding_words_to_a_sentence_never_lowers_its_stage_except_where_an_assertion_is_switched_off(self):
        bases = ("영양제 구매 기준", "피로 기록 앱", "당뇨 환자 식단 정리", "치료 방법 정리", "일반 업무 정리", "supplements guide", "stress notes",
                 "영양제 확실", "영양제 효과가 있", "영양제 반드시", "치료 100% 보장", "피로를 확실히 줄이는")
        additions = ("개선", "효능", "도움", "치료", "완치", "확실히", "보장", "무조건", "피로", "당뇨", "영양제", "improve", "cure", "guaranteed") + self.WARNING_WORDS + self.TAIL_WORDS
        lowered = set()
        for base in bases:
            for word in additions:
                for text, suffix in ((f"{base} {word}", True), (f"{word} {base}", False)):
                    if RANK[stage(text)] < RANK[stage(base)]:
                        lowered.add((base, word, suffix))
        self.assertTrue(lowered)
        for base, word, suffix in lowered:
            with self.subTest(base=base, word=word, suffix=suffix):
                self.assertTrue(word in self.WARNING_WORDS or (word in self.TAIL_WORDS and suffix), "예외 목록 밖에서 단계가 내려갔다")
        for word in self.WARNING_WORDS + self.TAIL_WORDS:
            with self.subTest(exception=word):
                self.assertTrue(any(item[1] == word for item in lowered), "예외 목록에 실제로는 내려가지 않는 낡은 항목이 있다")

    def test_the_assertion_switch_off_examples_lower_the_stage_exactly_as_documented(self):
        for before, after, first, second in (("영양제 확실", "영양제 확실하지 않다", STOP, MARK), ("영양제 효과가 있다", "영양제 효과가 있을까", STOP, EVIDENCE), ("영양제 반드시", "영양제 반드시 확인해야 할 것", STOP, MARK),
                                             ("영양제 효과를 보장한다는 광고", "영양제 효과를 보장한다는 광고에 속지 않는 법", STOP, EVIDENCE)):
            with self.subTest(before=before):
                self.assertEqual((stage(before), stage(after)), (first, second))


class GeneralWordsAndMasksTest(unittest.TestCase):                                                              # H5·H6
    def test_ordinary_words_alone_or_with_an_effect_and_an_assertion_are_still_general(self):
        for word in cn.GENERAL_WORDS:
            for text in (f"예시 {word} 글", f"예시 {word} 개선 확실히", f"예시 {word} 방법을 완전히 정리"):
                with self.subTest(text=text):
                    self.assertEqual(stage(text), GENERAL)
        for text in ("AI 모델 비교", "PC 부품 추천 기준", "노트북 선택 가이드", "업무 자동화 도구 비교", "후기 쓰는 법", "가격 비교 확실히 하는 방법", "추천 모델 성능을 즉시 개선하는 방법"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), sf.check_text([text]).flags), (GENERAL, ()))

    def test_an_effect_or_an_assertion_without_any_health_target_is_general(self):
        for text in ("성능 개선을 위한 캐시 설정", "확실히 개선되는 설정 모음", "에어컨 설치 매뉴얼을 완전히 개선하는 방법", "API 호출 설정을 완전히 정리하는 방법", "즉시 적용할 수 있는 단축키 모음", "효과가 있는지 확인하는 방법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), GENERAL)

    def test_a_mask_word_is_still_not_a_signal_even_with_effect_and_assertion_words(self):
        for table in ("HEALTH_MASKS_KO", "HEALTH_MASKS_EN"):
            for entry in getattr(cn, table):
                with self.subTest(table=table, entry=entry):
                    self.assertEqual(stage(f"예시 {entry} 글"), GENERAL)
        for text in ("알림 피로", "피로도 줄이기", "스트레스 테스트 결과 확실히 개선", "자세히 알아보는 방법", "혈압계 추천 기준", "체중계 고르는 법", "소화기 점검 주기", "알림 피로를 확실히 줄이는 설정", "처방전 PDF 정리"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), GENERAL)

    def test_a_mask_does_not_hide_a_real_signal_next_to_it(self):
        self.assertEqual(stage("알림 피로와 수면 기록"), MARK, "마스크 밖의 수면은 증상이다")
        self.assertEqual(stage("스트레스 테스트와 영양제 구매 기준"), MARK)


class NoticeWordingTest(unittest.TestCase):                                                                     # H7
    def test_the_catalog_keeps_every_code_name_in_the_same_order_and_the_health_levels(self):
        # 합친 판(WP-A '전략 맞춤 1차' 위)의 의도적 갱신: 알림 코드가 29 → 30 개다 — WP-A 가 `ECONOMIC_CONFLICT`(저장된 상태 '없음' 과 글의 협찬 추정이 충돌) 하나를 더했다. 건강 네 코드의 이름·순서·수준은 그대로다.
        self.assertEqual(len(nt.CODES), 30)
        self.assertIn("ECONOMIC_CONFLICT", nt.CODES)
        self.assertEqual(len(set(nt.CODES) - {"ECONOMIC_CONFLICT"}), 29, "WP-B 가 만들거나 지운 코드는 없다 — 나머지는 옛 29개 그대로")
        self.assertEqual(nt.CODES[:4], ("HEALTH_TOPIC", "HEALTH_EFFECT", "HEALTH_CLAIM", "HEALTH_STOP"))
        self.assertEqual([nt.level_of(code) for code in nt.CODES[:4]], ["WARNING", "WARNING", "WARNING", "ERROR"])

    def test_the_three_stage_sentences_are_these_and_the_unused_claim_sentence_is_kept(self):
        # 수정 1차(독립 검증 낮음 2): 문장을 단계 뜻에 맞췄다 — A 건강 대상(증상·질환·건강 제품·의료 용어)이 든 주제 / B 건강에 도움이 된다고 읽힐 수 있어 근거 확인이 필요한 표현 / C 효과·치료를 단정
        self.assertEqual(nt.CATALOG["HEALTH_TOPIC"], ("WARNING", "건강 정보 확인 필요", "증상·질환·건강 제품이나 치료 같은 의료 용어가 들어 있는 주제입니다.", "공식 근거를 확인하고, 효과를 단정하지 않는 표현으로 써 주세요."))
        # 의도적 갱신(D-134): B 문장 한 줄 — 질환 단독과 복용 허용 질문도 B 가 되어 '질환이나 복용을 다루거나' 를 앞에 더했다(옛: '건강에 도움이 된다고 읽힐 수 있는 표현이 있어 …')
        self.assertEqual(nt.CATALOG["HEALTH_EFFECT"], ("WARNING", "건강 정보 확인 필요", "질환이나 복용을 다루거나 건강에 도움이 된다고 읽힐 수 있는 표현이 있어 근거 확인이 필요합니다.", "공식 근거를 확인하고, 효과를 단정하지 않는 표현으로 써 주세요."))
        self.assertEqual(nt.CATALOG["HEALTH_STOP"], ("ERROR", "의료·효과 단정 위험", "건강 효과나 치료를 단정하는 표현이 있어 자동 초안을 만들지 않습니다.", "표현을 바꾸거나 공식 근거를 확인한 뒤 직접 검토해 주세요."))
        self.assertEqual(nt.CATALOG["HEALTH_CLAIM"], ("WARNING", "건강 정보 확인 필요", "효과를 단정하는 표현이 포함되어 있습니다.", "공식 근거를 확인하거나 일반 생활정보 표현으로 수정해 주세요."))
        source = Path(nt.__file__).read_text(encoding="utf-8")
        self.assertIn("HEALTH_CLAIM 은 이 단계표에서 쓰이는 곳이 없다", source, "쓰임이 없다는 주석")

    def test_the_stage_sentences_have_no_python_list_shape_and_no_english_value_name(self):
        for code in ("HEALTH_TOPIC", "HEALTH_EFFECT", "HEALTH_CLAIM", "HEALTH_STOP"):
            level, title, message, action = nt.CATALOG[code]
            for part in (title, message, action):
                with self.subTest(code=code, part=part):
                    self.assertEqual(nt.leaks(part), ())
        samples = {MARK: "영양제 구매 기준", EVIDENCE: "영양제 효능 정리", STOP: "영양제로 피로가 완전히 회복됩니다"}
        for name, text in samples.items():
            card = nt.cards(nt.from_report(sf.check_text([text])))
            with self.subTest(stage=name):
                self.assertEqual(nt.leaks(card), ())
                for forbidden in ("mark", "evidence", "stop", "general", "check", "health_check", "HEALTH_", "stage", "['", "{'"):
                    self.assertNotIn(forbidden, card)

    def test_the_card_of_each_stage_is_its_catalog_sentence_with_the_concept_groups_as_bullets(self):
        for text, code in (("영양제 구매 기준", "HEALTH_TOPIC"), ("영양제 효능 정리", "HEALTH_EFFECT"), ("불면을 확실히 치료하는 방법", "HEALTH_STOP")):
            notices = nt.from_report(sf.check_text([text]))
            with self.subTest(text=text):
                self.assertEqual([item.code for item in notices], [code])
                _level, title, message, action = nt.CATALOG[code]
                self.assertEqual(notices[0].lines()[:4], (title, "", message, action))
                self.assertTrue(all(line.startswith("- ") for line in notices[0].lines()[5:]))

    def test_a_selection_reason_line_for_each_stage_starts_with_the_title(self):
        lines = {name: sf.notes(sf.check_text([text])) for name, text in ((MARK, "영양제 구매 기준"), (EVIDENCE, "영양제 효능 정리"), (STOP, "불면을 확실히 치료하는 방법"))}
        self.assertTrue(lines[MARK][0].startswith("건강 정보 확인 필요 — 증상·질환·건강 제품이나 치료 같은 의료 용어가 들어 있는 주제입니다."))
        self.assertTrue(lines[EVIDENCE][0].startswith("건강 정보 확인 필요 — 질환이나 복용을 다루거나 건강에 도움이 된다고 읽힐 수 있는 표현이 있어 근거 확인이 필요합니다."))
        self.assertTrue(lines[STOP][0].startswith("의료·효과 단정 위험 — 건강 효과나 치료를 단정하는 표현이 있어 자동 초안을 만들지 않습니다."))

    def test_each_sentence_fits_the_cells_of_its_stage_including_the_ones_that_used_to_fit_badly(self):
        # 수정 1차: 문장은 단계 뜻을 말한다 — 옛 문장이 어긋났던 카드(의료 용어만 / 제품 + 증상 / 증상만으로 단정 위험)로 확인한다
        topic, evidence, danger = (nt.CATALOG[code][2] for code in ("HEALTH_TOPIC", "HEALTH_EFFECT", "HEALTH_STOP"))
        for word in ("증상", "질환", "건강 제품", "의료 용어"):
            self.assertIn(word, topic, "A 는 건강 대상 네 가지를 모두 말한다")
        self.assertIn("근거 확인", evidence)
        self.assertIn("도움", evidence)
        self.assertNotIn("효과를 말하는", evidence, "B 에는 효과 낱말 없는 제품 + 증상도 들어 있어 '효과를 말하는' 이라고만 하지 않는다")
        for word in ("효과", "치료", "단정"):
            self.assertIn(word, danger)
        self.assertNotIn("건강 제품이나 질환", danger, "C 에는 증상·의료 낱말만으로 올라온 글도 들어 있어 '제품이나 질환' 에 가두지 않는다")
        for text, code in (("시술 후 일정 관리 달력", "HEALTH_TOPIC"), ("유산균 장 건강 관리 요령", "HEALTH_EFFECT"), ("스트레스를 확실히 줄이는 시간 관리법", "HEALTH_STOP")):
            with self.subTest(text=text):
                self.assertEqual(codes(text), [code])


class ShapeUnchangedTest(unittest.TestCase):                                                                    # H8
    def test_the_flag_values_and_their_order_and_the_candidate_field_are_unchanged(self):
        self.assertEqual(md.SAFETY_FLAGS, ("health_check", "product_brand", "experience_claim", "sponsor_disclosure", "result_promise"))
        self.assertEqual((sf.FLAG_HEALTH, sf.FLAG_PRODUCT, sf.FLAG_EXPERIENCE, sf.FLAG_SPONSOR, sf.FLAG_PROMISE), md.SAFETY_FLAGS)
        field = next(item for item in dataclasses.fields(md.TopicCandidate) if item.name == "safety_flags")
        self.assertEqual(field.default, ())
        for text, expected in (("영양제 구매 기준", ("health_check",)), ("영양제 효능 정리", ("health_check",)), ("영양제로 피로가 완전히 회복됩니다", ("health_check",)), ("일반 업무 정리", ())):
            self.assertEqual(sf.assess(ts.make(topic=text, content_type="explainer", primary_keyword="예시 키워드")).flags, expected, text)
            self.assertEqual(sf.mark(ts.make(topic=text, content_type="explainer", primary_keyword="예시 키워드")).safety_flags, expected, text)

    def test_the_report_keeps_its_first_six_fields_and_adds_one_stage_field_that_defaults_to_general(self):
        # 합친 판(WP-A 위)의 의도적 갱신: WP-A 가 `benefits` 뒤에 `interests`(확인된 경제적 이해관계 유형, 기본 `("UNKNOWN",)`)를 끼워 넣었다 — 칸 순서는 benefits → interests → stage 이고 `stage` 는 맨 끝이다.
        self.assertEqual(sf.SafetyReport._fields, ("flags", "findings", "health", "relationship", "opportunity", "benefits", "interests", "stage"))
        self.assertEqual(sf.SafetyReport((), ()), sf.SafetyReport((), (), "general", "none", "none", (), ("UNKNOWN",), "general"))
        self.assertEqual(sf.SafetyReport._field_defaults["stage"], "general")
        self.assertEqual(sf.SafetyReport((), ()).stage, "general")
        self.assertEqual(sf.check_text(["일반 업무 정리"]).stage, "general")
        self.assertEqual(sf.check_text([]).stage, "general")

    def test_the_stop_is_still_computed_from_the_error_level_and_a_mark_only_changes_the_flag_field(self):
        report = sf.check_text(["영양제로 피로가 완전히 회복됩니다"])
        self.assertEqual(report.stop, any(finding.level == "ERROR" for finding in report.findings))
        base = ts.rated(70, topic="영양제 효능 정리", content_type="explainer", work_status="REVIEW", review_expires_at=None)
        marked = sf.mark(base)
        self.assertEqual(marked.safety_flags, ("health_check",))
        for name in ("scores", "recommendation_band", "work_status", "topic", "primary_keyword", "candidate_id", "review_expires_at", "channel", "duplicate_status", "monetization_tags"):
            self.assertEqual(getattr(marked, name), getattr(base, name), name)

    def test_only_the_evidence_item_of_the_score_changes_between_the_stages_and_the_thresholds_are_the_same(self):
        mark = run(A, [seed(keyword="예시 영양제", seed_type="priority", priority=True)], target=100)
        evidence = run(A, [seed(keyword="예시 영양제 효능", seed_type="priority", priority=True)], target=100)
        by_direction = lambda found: {c.topic.split(", ")[0].split(" ", 2)[-1].replace("효능 ", ""): c for c in found.candidates}                      # noqa: E731
        first, second = by_direction(mark), by_direction(evidence)
        self.assertEqual(set(first), set(second))
        for direction in first:
            with self.subTest(direction=direction):
                a, b = first[direction].scores.factors, second[direction].scores.factors
                for name in ("channel_fit", "feasibility", "differentiation", "timing", "monetization"):
                    self.assertEqual(getattr(a, name), getattr(b, name), name)
                self.assertEqual(b.evidence, a.evidence - 20)
                self.assertEqual(second[direction].scores.final, sc.score(A, b).final)
        self.assertEqual((sc.band_of(80), sc.band_of(79), sc.band_of(65), sc.band_of(64), sc.band_of(50), sc.band_of(49)), ("RECOMMENDED", "GENERAL", "GENERAL", "HOLD", "HOLD", "EXCLUDED"))

    def test_the_evidence_penalty_table_and_amounts_are_unchanged(self):
        self.assertEqual(dict(gn.EVIDENCE_PENALTY), {"health_check": 20, "experience_claim": 10})
        explainer = ts.make(content_type="explainer")
        self.assertEqual(gn._evidence(explainer, ("experience_claim",), gn._Extra(), "mark"), 60, "경험 단정 −10 은 그대로다")
        self.assertEqual(gn._evidence(explainer, ("experience_claim", "health_check"), gn._Extra(), "evidence"), 40)


class EnglishStagesTest(unittest.TestCase):                                                                     # H9
    def test_english_sentences_follow_the_same_stages(self):
        for text, expected in (("This supplement will cure diabetes", STOP), ("vitamin D guaranteed to cure fatigue", STOP), ("supplements for better sleep", EVIDENCE), ("supplements guide for beginners", MARK),
                               ("How to relieve stress and improve sleep", MARK), ("sleep tips for beginners", MARK), ("diabetes diet notes", EVIDENCE), ("how to relieve diabetes symptoms", EVIDENCE),
                               ("stress test results for servers", GENERAL), ("the weight of the box", GENERAL), ("best laptop for programming", GENERAL), ("improve your python skills", GENERAL),
                               ("guaranteed delivery tracking", GENERAL), ("Handling remediation steps in the security backlog", GENERAL)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)

    def test_everyday_english_words_are_a_mark_and_never_a_stop_or_a_cut_a_known_side_effect(self):
        for word in ("sleep", "stress", "weight", "focus", "diet"):
            text = f"notes about {word} for beginners"
            with self.subTest(word=word):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.stop), (MARK, False))
                self.assertEqual(candidate_evidence(text), BASE_EXPLAINER)

    def test_a_product_name_that_contains_a_symptom_word_is_one_product_in_english_too(self):
        for text in ("diet pills review", "weight loss pills guide", "posture corrector buying guide"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), MARK)
        self.assertEqual(stage("diet pills for weight loss"), EVIDENCE, "이름 밖의 ‘weight loss’ 는 따로 센다")


class RealtimeIssueTest(unittest.TestCase):                                                                     # H10
    @staticmethod
    def item(topic, keyword, sources):
        return gn.RealtimeItem(channel="naver_a", topic=topic, primary_keyword=keyword, topic_cluster="small-appliances", topic_angle="what-changed", search_intent="context_explainer",
                               content_type="news_analysis", first_reported_at="2026-11-07T00:00:00Z", sources=sources)

    def issue_candidates(self, topic, keyword, sources):
        found = gn.generate(A, (), (), (), TODAY, realtime=[self.item(topic, keyword, sources)], target=40)
        return [c for c in found.candidates if c.source_type == "realtime"]

    def test_an_issue_with_an_official_source_keeps_ninety_even_when_the_claim_needs_evidence_or_stops(self):
        official = (gn.Source(url="https://a.example.org/x", official=True),)
        for topic, keyword, expected_stage in (("예시 영양제 효능이 알려졌다", "예시 영양제 효능", EVIDENCE), ("예시 영양제로 피로가 완전히 회복된다는 소식", "예시 영양제 회복 소식", STOP), ("예시 영양제 구매 소식", "예시 영양제 소식", MARK)):
            made = self.issue_candidates(topic, keyword, official)
            self.assertEqual(len(made), 1, topic)
            with self.subTest(topic=topic):
                self.assertEqual(sf.assess(made[0]).stage, expected_stage)
                self.assertEqual(made[0].scores.factors.evidence, 90, "근거 있음 — 단계와 상관없이 감점하지 않는다(지금 그대로)")
                self.assertEqual(sf.assess(made[0]).stop, expected_stage == STOP, "중지는 감점과 따로 계산한다")

    def test_an_issue_with_two_independent_sources_keeps_seventy_five(self):
        independent = (gn.Source(url="https://a.example.org/x"), gn.Source(url="https://b.example.net/y"))
        made = self.issue_candidates("예시 영양제 효능이 알려졌다", "예시 영양제 효능", independent)
        self.assertEqual(len(made), 1)
        self.assertEqual((sf.assess(made[0]).stage, made[0].scores.factors.evidence), (EVIDENCE, 75))

    def test_the_same_issue_without_a_health_word_gets_the_same_numbers(self):
        official = (gn.Source(url="https://a.example.org/x", official=True),)
        plain = self.issue_candidates("예시 새 소식이 나왔다", "예시 새 소식", official)
        self.assertEqual((plain[0].safety_flags, plain[0].scores.factors.evidence), ((), 90))

    def test_the_other_routes_have_no_evidence_so_a_claim_that_needs_it_is_cut(self):
        seed_made = run(A, [seed(keyword="예시 영양제 효능", seed_type="priority", priority=True)], target=100)
        self.assertTrue(seed_made.candidates)
        for candidate in seed_made.candidates:
            self.assertEqual(candidate.scores.factors.evidence, gn.EVIDENCE_BASE[candidate.content_type] - 20, "씨앗 경로에는 근거 자료 칸이 아직 없다(알려진 한계)")


class EvidenceFunctionTest(unittest.TestCase):                                                                  # H11
    def test_the_stage_argument_decides_whether_the_health_cut_applies(self):
        explainer = ts.make(content_type="explainer")
        for given, expected in ((GENERAL, 70), (MARK, 70), (EVIDENCE, 50), (STOP, 50), (None, 50)):
            with self.subTest(stage=given):
                self.assertEqual(gn._evidence(explainer, ("health_check",), gn._Extra(), given), expected)
        self.assertEqual(gn._evidence(explainer, ("health_check",), gn._Extra()), 50, "단계를 안 주면 옛 호출과 같게 감점한다")
        self.assertEqual(gn._evidence(explainer, (), gn._Extra(), EVIDENCE), 70, "표시가 없으면 단계가 무엇이든 감점하지 않는다")

    def test_a_source_overrides_the_cut_at_every_stage_and_one_independent_source_does_not(self):
        explainer = ts.make(content_type="explainer")
        for given in (MARK, EVIDENCE, STOP, None):
            with self.subTest(stage=given):
                self.assertEqual(gn._evidence(explainer, ("health_check",), gn._Extra(official=1), given), 90)
                self.assertEqual(gn._evidence(explainer, ("health_check",), gn._Extra(independent=2), given), 75)
                self.assertEqual(gn._evidence(explainer, ("health_check",), gn._Extra(independent=1), given), 70 if given == MARK else 50)

    def test_the_cut_adds_with_the_experience_cut_and_the_own_post_bonus_and_never_goes_below_zero(self):
        explainer = ts.make(content_type="explainer")
        self.assertEqual(gn._evidence(explainer, ("health_check", "experience_claim"), gn._Extra(), MARK), 60)
        self.assertEqual(gn._evidence(explainer, ("health_check", "experience_claim"), gn._Extra(), EVIDENCE), 40)
        self.assertEqual(gn._evidence(explainer, ("health_check",), gn._Extra(own_post=True), MARK), 80)
        self.assertEqual(gn._evidence(explainer, ("health_check",), gn._Extra(own_post=True), EVIDENCE), 60)
        news = ts.make(content_type="news_analysis")
        self.assertEqual(gn._evidence(news, ("health_check", "experience_claim"), gn._Extra(), STOP), 20)

    def test_needs_evidence_is_true_for_the_evidence_and_stop_stages_and_for_an_unknown_stage_value_none(self):
        self.assertEqual([sf.needs_evidence(name) for name in (GENERAL, MARK, EVIDENCE, STOP)], [False, False, True, True])
        self.assertTrue(sf.needs_evidence(None))
        for bad in ("zzz", "", 3, ("mark",), "check"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    sf.needs_evidence(bad)

    def test_the_documented_source_condition_is_one_official_or_two_independent(self):
        self.assertEqual((gn.MIN_OFFICIAL, gn.MIN_INDEPENDENT, gn.EVIDENCE_OFFICIAL, gn.EVIDENCE_INDEPENDENT), (1, 2, 90, 75))


class NamesInsideNamesTest(unittest.TestCase):                                                                  # H12
    def test_a_word_that_only_lives_inside_a_product_or_device_name_is_not_counted_on_its_own(self):
        for text, field, word in (("치료제 추천", "medical", "치료"), ("운동 처방 방법", "medical", "처방"), ("수면제 추천", "symptom", "수면"), ("다이어트 제품 비교", "symptom", "다이어트"),
                                  ("자세교정기 추천", "symptom", "자세"), ("자세교정기 구매 기준", "effect", "교정"), ("diet pills review", "symptom", "diet")):
            with self.subTest(text=text, word=word):
                signals = cn.health_signals([text])
                self.assertIn(word, getattr(signals, field), "원시 신호에는 그대로 있다(표는 바뀌지 않았다)")
                self.assertNotIn(word, signals.counted(field))
                self.assertIn((field, word), signals.inside)
                self.assertEqual(stage(text), MARK, "제품 이름 하나는 한 개념군 하나다")

    def test_the_same_word_outside_the_name_is_counted_again(self):
        self.assertEqual(stage("치료제 추천과 치료 후기 정리"), STOP, "이름 밖의 ‘치료’ 는 의료 효능어로 센다 → 제품 + 의료 효능어")
        self.assertEqual(stage("수면제 추천과 수면 습관"), EVIDENCE, "이름 밖의 ‘수면’ 은 증상 → 제품 + 증상")
        self.assertEqual(stage("자세교정기 추천과 자세 점검"), EVIDENCE)

    def test_a_word_inside_a_disease_name_is_counted_so_a_disease_with_an_effect_and_an_assertion_stays_a_danger(self):
        # 수정 1차(독립 검증 중간 1): 이름 속 조각 규칙은 제품·기기 이름에만 건다. 질환 표 항목 `암 예방`·`암 수술`·`수술 후유증` 안의 ‘예방’·‘수술’ 은 예전처럼 세므로
        # 질환 + 효과 + 단정은 단정 위험이다(옛 코드의 중지를 느슨하게 만들지 않는다).
        for text in ("암 예방 100% 보장", "암 수술 100% 안전", "수술 후유증 확실히 낫는다", "암 예방 확실한 방법", "수술 후유증 100% 해결", "암 수술 후 회복을 반드시 보장"):
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.stop, codes(text)), (STOP, True, ["HEALTH_STOP"]))
                self.assertEqual(cn.health_signals([text]).inside, (), "질환 이름 속 낱말은 따로 빼지 않는다")
        for text, field, word in (("암 예방 식단", "effect", "예방"), ("암 수술 후 식단", "medical", "수술"), ("수술 후유증 관리", "medical", "수술")):
            with self.subTest(text=text):
                signals = cn.health_signals([text])
                self.assertIn(word, signals.counted(field))
                self.assertEqual(stage(text), EVIDENCE, "질환 + 효과(또는 의료 효능어) → 근거 확인 필요")
        self.assertEqual(stage("치료제 100% 보장"), STOP, "제품 쪽은 제품 + 단정이라 그대로 단정 위험")
        self.assertEqual(stage("자세교정기 확실히 교정"), STOP)
        # 독립 재검증(낮음 2): 제품과 질환 항목이 한 글에 같이 있어도 질환 항목 속 의료 낱말(‘수술’)은 센다 — 제품 + 의료 낱말 = 단정 위험(고정 기준 ④).
        # 이 세 문장은 '질환 이름 속 조각 덮개'를 되살리면 단정 위험에서 근거 확인 필요로 내려간다(구현자가 동치라고 한 변이가 사실은 동치가 아니었다).
        for text in ("영양제 암 수술 후 식단", "영양제 수술 후유증 관리", "치료제 암 수술 후 식단"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP, "제품 + 질환 항목 속 의료 낱말 → 단정 위험")

    def test_every_disease_entry_that_holds_an_effect_or_a_medical_word_is_found_by_program_and_is_judged_like_the_old_rule(self):
        def show(entry):
            return entry + "x" if entry.endswith("*") else entry
        holding = []
        for entry in cn.HEALTH_DISEASE_KO + cn.HEALTH_DISEASE_EN:
            alone = cn.health_signals([f"예시 {show(entry)} 글"])
            inner = bool(alone.effect or alone.medical)            # 항목 하나만 글에 넣었는데 효과·의료 낱말이 걸리면 그 항목은 안쪽에 그런 낱말을 품은 것이다(원시 신호 — 표와 일치 규칙이 정한 값)
            holding += [entry] if inner else []
            with self.subTest(entry=entry, inner=inner):
                self.assertEqual(alone.inside, (), "질환 항목에는 이름 속 조각 규칙을 걸지 않는다")
                self.assertEqual(stage(f"예시 {show(entry)} 글"), EVIDENCE, "질환 단독은 근거 확인 필요 — 의도적 갱신(D-134, 운영자 ③: 질환 단독 = B). 옛: 안쪽의 효과·의료 낱말이 있을 때만 근거 확인 필요, 아니면 표시만")
                self.assertEqual(stage(f"예시 {show(entry)} 100% 보장 글"), STOP, "질환 + 강한 단정은 항목에 상관없이 단정 위험 — 의도적 갱신(D-134, 운영자 ③: 옛: 안쪽의 효과·의료 낱말이 없으면 표시만)")
                self.assertEqual(stage(f"예시 {show(entry)} 확실히 효과 글"), STOP, "질환 + 효과 + 단정은 항목에 상관없이 단정 위험")
        self.assertEqual(sorted(holding), sorted(["암 예방", "암 수술", "수술 후유증"]), "효과·의료 낱말을 품은 질환 항목은 이 셋뿐이다 — 표가 바뀌면 의식적으로 함께 고친다")

    def test_nothing_the_old_rule_stopped_is_eased_and_nothing_it_flagged_becomes_general(self):
        # 수정 1차 — '의도하지 않은 완화 0'. 옛 16칸 규칙을 `key()` 네 값으로 시험 안에서 다시 적고(`key()` 는 이 작업에서 한 글자도 안 바뀌었다) 낱말 표 전체 × 단정 꼬리와 고정 시드 무작위 글에서 새 단계와 견준다.
        def old_state(signals):
            s, e, p, a = signals.key()
            return ("stop" if e and a else "check") if p else ("check" if s and e and a else "general")

        def show(entry):
            return entry + "x" if entry.endswith("*") else entry
        words = [show(word) for name in dir(cn) if name.startswith("HEALTH_") and name.endswith(("_KO", "_EN")) for word in getattr(cn, name)]
        self.assertGreater(len(words), 300)
        tails = ("", " 100% 보장", " 확실히", " 무조건", " 완전히", " will cure", " 반드시 효과가 있다")
        rng = random.Random(20261106)
        filler = ("예시", "방법", "정리", "비교", "추천", "습관", "guide", "notes", "와", "를")
        texts = [f"예시 {word}{tail} 글" for word in words for tail in tails]
        texts += [" ".join(rng.choice(words if rng.random() < 0.6 else filler) for _ in range(rng.randint(1, 6))) for _ in range(2000)]
        stops = flagged = 0
        for text in texts:
            signals = cn.health_signals([text])
            old, new = old_state(signals), sf.check_text([text]).stage          # 의도적 갱신(D-130): 표만이 아니라 실제 판정(옛 중지 바닥 포함)으로 견준다
            if old == "stop":
                stops += 1
                self.assertTrue(new == STOP or signals.relaxed_words(), f"옛 중지가 풀렸다: {text!r}")          # 의도적 갱신(D-137·D-138): 결정으로 푼 곳(영양제·처방약 + 행동 순서, 치료 + 행동 순서)만 예외
            if old != "general":
                flagged += 1
                self.assertNotEqual(new, GENERAL, f"옛 표시가 사라졌다: {text!r}")
        self.assertGreater(stops, 500)
        self.assertGreater(flagged, 1500)

    def test_the_covering_helper_covers_only_strictly_longer_matches_that_contain_every_place(self):
        self.assertEqual(cn._only_inside({"a": [(2, 4)]}, [(0, 6)]), ["a"])
        self.assertEqual(cn._only_inside({"a": [(2, 4)]}, [(2, 4)]), [], "같은 자리는 더 긴 낱말이 아니다")
        self.assertEqual(cn._only_inside({"a": [(2, 4)]}, [(3, 9)]), [], "걸치기만 하면 안이 아니다")
        self.assertEqual(cn._only_inside({"a": [(2, 4), (8, 10)]}, [(0, 6)]), [], "한 자리라도 밖이면 따로 센다")
        self.assertEqual(cn._only_inside({"a": [(2, 4)], "b": [(7, 9)]}, [(0, 6)]), ["a"])
        self.assertEqual(cn._only_inside({}, [(0, 6)]), [])

    def test_the_raw_key_and_the_raw_signals_are_not_changed_by_the_name_rule(self):
        self.assertEqual(cn.health_signals(["치료제 추천"]).key(), (0, 1, 1, 0))
        self.assertEqual(cn.health_signals(["자세교정기 추천"]).key(), (1, 1, 1, 0))
        self.assertEqual(cn.health_signals(["치료제 추천"]).concept_key(), (0, 0, 1, 0, 0, 0))
        self.assertEqual(cn.health_signals(["일반 업무 정리"]).inside, ())

    def test_the_words_shown_in_the_notice_leave_out_the_words_inside_a_name(self):
        finding = sf.check_text(["치료제 추천"]).findings[0]
        self.assertEqual((finding.matched, finding.groups), (("치료제",), ("제품·행위",)))
        finding = sf.check_text(["자세교정기 추천"]).findings[0]
        self.assertEqual((finding.matched, finding.groups), (("자세교정기",), ("제품·행위",)))

    def test_every_table_entry_alone_has_the_stage_its_group_implies(self):
        def show(entry):
            return entry + "x" if entry.endswith("*") else entry
        # 질환 표는 항목 안에 효과·의료 낱말을 품은 셋(`암 예방`·`암 수술`·`수술 후유증`)만 근거 확인 필요(수정 1차 — 위 전수 시험이 프로그램으로 찾아 못박는다), 나머지는 표시만이다
        # 의도적 갱신(D-134): 질환 표 항목은 어느 것이든 단독이면 근거 확인 필요(운영자 ③) — 옛 시험은 안쪽 낱말이 없는 질환 항목을 표시만으로 못박았다
        groups = (("symptom", cn.HEALTH_SYMPTOM_KO + cn.HEALTH_SYMPTOM_EN, MARK), ("disease", tuple(item for item in cn.HEALTH_DISEASE_KO + cn.HEALTH_DISEASE_EN if item not in ("암 예방", "암 수술", "수술 후유증")), EVIDENCE),
                  ("disease_holding", ("암 예방", "암 수술", "수술 후유증"), EVIDENCE), ("product", cn.HEALTH_PRODUCT_KO + cn.HEALTH_PRODUCT_EN, MARK),
                  ("medical", cn.HEALTH_MEDICAL_KO + cn.HEALTH_MEDICAL_EN, MARK), ("effect", cn.HEALTH_EFFECT_KO + cn.HEALTH_EFFECT_EN, GENERAL), ("assert", cn.HEALTH_ASSERT_KO + cn.HEALTH_ASSERT_EN, GENERAL),
                  ("assert_soft", cn.HEALTH_ASSERT_SOFT_KO + cn.HEALTH_ASSERT_SOFT_EN, GENERAL))
        checked = 0
        for name, entries, expected in groups:
            for entry in entries:
                checked += 1
                with self.subTest(group=name, entry=entry):
                    self.assertEqual(stage(f"예시 {show(entry)} 글"), EVIDENCE if entry in ("혈압약", "당뇨약", "항암제") else expected)          # 의도적 갱신(D-137): 이름 속에 질환 낱말이 든 처방약 셋은 옛 코드가 질환 단독(B)으로 읽었으므로 B 를 지킨다(약화 금지)
        medical_assertions = ("치료된다", "치료됩니다", "치료가 된다", "완치된다", "will cure", "guaranteed to cure")
        for entry in cn.HEALTH_ASSERT_EFFECT_KO + cn.HEALTH_ASSERT_EFFECT_EN:
            checked += 1
            with self.subTest(group="assert_effect", entry=entry):
                self.assertEqual(stage(f"예시 {show(entry)} 글"), STOP if entry in medical_assertions else GENERAL)
        self.assertEqual(checked, 54 + 97 + 67 + 17 + 47 + 22 + 12 + 26, "표 항목 전수 — 표 크기가 바뀌면 이 수도 의식적으로 함께 고친다(제품 표 56 → 67: 처방약 낱말 열한 개, D-133·D-137)")


class DocumentsTest(unittest.TestCase):                                                                         # H13
    def test_the_decisions_d105_and_d106_exist_once_after_d58_and_say_what_they_decided(self):
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        found = [line.split(" | ")[0].lstrip("| ") for line in text.splitlines() if line.startswith("| D-")]
        self.assertEqual(found.count("D-105"), 1)
        self.assertEqual(found.count("D-106"), 1)
        self.assertGreater(found.index("D-105"), found.index("D-58"))
        rows = {line.split(" | ")[0].lstrip("| "): line for line in text.splitlines() if line.startswith("| D-10")}
        for needle in ("세 단계", "HEALTH_MATRIX", "64칸", "표시만", "근거 확인 필요", "단정 위험", "HEALTH_TOPIC", "HEALTH_EFFECT", "HEALTH_STOP", "HEALTH_CLAIM", "단조", "치료제", "잠들기 전 화면 사용을 줄이는 생활 습관", "영양제로 피로가 완전히 회복됩니다",
                       "질환 이름에는 적용하지 않는다", "암 예방 100% 보장", "확실하지 않다", "부정·의문 꼬리", "의무꼴"):
            with self.subTest(decision="D-105", needle=needle):
                self.assertIn(needle, rows["D-105"])
        for needle in ("근거가 필요한 주장", "공식 출처 1개", "독립", "−20", "needs_evidence", "알려진 한계", "EVIDENCE_PENALTY", "experience_claim", "씨앗", "실시간"):
            with self.subTest(decision="D-106", needle=needle):
                self.assertIn(needle, rows["D-106"])

    def test_the_changelog_has_one_entry_for_the_health_stages(self):
        log = (ts.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(log.count("**건강 판정 보완**"), 1)
        entry = next(line for line in log.splitlines() if "**건강 판정 보완**" in line)
        for needle in ("D-105", "D-106", "HEALTH_MATRIX", "표시만", "근거 확인 필요", "단정 위험", "SafetyReport.stage", "제품·기기 이름", "질환 이름 속 낱말은 센다"):
            self.assertIn(needle, entry)

    def test_the_two_module_headers_report_the_comparison_with_the_strategy_text_instead_of_saying_it_is_unchecked(self):
        concepts_doc = Path(cn.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
        safety_doc = Path(sf.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
        for doc in (concepts_doc, safety_doc):
            self.assertIn("§21", doc)
            for word in ("피로", "불면", "통증", "자세", "체중", "영양제"):
                self.assertIn(word, doc)
        self.assertNotIn("**표는 모두 초기값 — 전략 원문 확인 전이다.**", concepts_doc)
        self.assertNotIn("**낱말 표는 모두 초기값 — 전략 원문 확인 전이다**", safety_doc)
        self.assertIn("초기값 — 전략 원문 확인 전", concepts_doc, "나머지 낱말은 여전히 원문 확인 전이다(기존 시험이 지키는 문구)")
        for word in ("바꿨다", "표는 바꾸지 않았"):
            self.assertIn(word, concepts_doc)

    def test_the_health_word_tables_are_not_changed_by_this_work(self):
        self.assertEqual((len(cn.HEALTH_SYMPTOM_KO), len(cn.HEALTH_DISEASE_KO), len(cn.HEALTH_PRODUCT_KO), len(cn.HEALTH_MEDICAL_KO), len(cn.HEALTH_EFFECT_KO)), (39, 71, 45, 6, 34), "제품 표만 34 → 45(처방약 낱말 넷 D-133 + 일곱 D-137, 의도적 갱신)")
        for word in ("피로", "불면", "통증", "자세", "체중"):
            self.assertIn(word, cn.HEALTH_SYMPTOM_KO)
        self.assertIn("영양제", cn.HEALTH_PRODUCT_KO)


if __name__ == "__main__":
    unittest.main()
