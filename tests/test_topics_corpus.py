"""안전 표시 말뭉치 시험(P2b 보완 K1~K3) — 지어낸 일반 문장 수백 개로 '정상 주제는 표시·알림이 0' 과 '위험 주제는 단계별로 정확히' 를 못박는다.

지키는 것:
  K1) 정상 말뭉치(252 — 네이버 B·A·Blogger 한글·영어·낱말 조각이 겹치는 함정·브랜드 단독·협찬 약속 경계·**띄어쓴 두 낱말의 끝과 처음이 이어 붙는 낱말 경계 함정 55(보완 1차, D-58)**)는 표시도 알림도 없다 — 근거 점수 감점도 없다.
      **증상 낱말이 든 평범한 문장 27 은 여기서 `NOTE_SYMPTOM_WORDS` 로 옮겼다(WP-B, D-105 — 운영자 2026-11-06: 증상 낱말 하나만으로는 차단·감점하지 않고 '표시만')**: 표시 하나·알림 `HEALTH_TOPIC`·감점 0·중지 아님(K1b).
  K2) 위험 말뭉치 85(건강 단정 위험 17·근거 확인 필요 10·표시만 13·결과 약속 6·협찬 추정 22·경험 단정 17)는 단계별로 맞다 — 단계가 한 칸이라도 어긋나면 실패한다(옛 '확인 필요' 5개는 단정 위험으로 올라갔다).
  K3) 엔진이 만드는 모양(씨앗 57 × 방향 23 = 1,311개)은 표시 0, 증상 씨앗 10 × 23 = 230개는 모두 '표시만'(감점 0·중지 0), 건강 씨앗 12 × 23 = 276개는 '표시만' 또는 '근거 확인 필요'(중지 0).
말뭉치는 `topics_corpus.py` 에 있다(모두 지어낸 문장 — 실제 씨앗·블로그 글 제목이 아니다). 네트워크·파일·실제 시계·난수 없이 돈다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_corpus as corpus  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import concepts as cn  # noqa: E402
from chanceblog_desktop.topics import expand as ex  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402

NORMAL = (corpus.NORMAL_NAVER_B, corpus.NORMAL_TRAPS, corpus.NORMAL_BRAND_AND_MASK_EDGES, corpus.NORMAL_NAVER_A, corpus.NORMAL_KO_HABIT, corpus.NORMAL_EN, corpus.NORMAL_BORDER, corpus.NORMAL_BOUNDARY)
EXAMPLE_KEYWORD = "예시 키워드"


def engine_texts(seed, direction):
    direction_row = ex.direction_of(direction)
    topic = gn.TOPIC_TEMPLATES_KO[direction_row.content_type].format(kw=seed, dir=direction)
    return [topic, f"{seed} {direction}", seed]


class NormalCorpusTest(unittest.TestCase):
    def test_the_normal_corpus_has_the_documented_size_and_no_duplicates_inside_a_group(self):
        # 의도적 갱신(WP-B, D-105): 증상 낱말이 든 27문장이 `NOTE_SYMPTOM_WORDS` 로 옮겨 가서 [63, 30, 20, 34, 24, 39, 13, 56] = 279 에서 줄었다(문장은 지우지 않았다)
        self.assertEqual([len(group) for group in NORMAL], [58, 29, 18, 32, 10, 37, 13, 55])
        self.assertEqual(sum(len(group) for group in NORMAL), 252)
        for group in NORMAL:
            self.assertEqual(len(group), len(set(group)))
        everything = [text for group in NORMAL for text in group]
        self.assertEqual(len(everything), len(set(everything)), "다른 묶음과 겹치는 문장이 없다")

    def test_every_normal_text_gets_no_flag_and_no_notice_and_no_result_promise(self):
        for group in NORMAL:
            for text in group:
                with self.subTest(text=text):
                    report = sf.check_text([text])
                    self.assertEqual((report.flags, report.findings, report.health, report.relationship), ((), (), "general", "none"), text)
                    self.assertFalse(report.stop)

    def test_the_whole_corpus_in_one_call_and_as_candidates_also_gets_nothing(self):
        for text in [text for group in NORMAL for text in group][:50]:
            made = ts.make(topic=text, content_type="explainer", primary_keyword=EXAMPLE_KEYWORD)
            with self.subTest(text=text):
                if "result_promise" not in sf.check_text([text]).flags:
                    self.assertEqual(sf.assess(made).flags, ())


class SymptomWordCorpusTest(unittest.TestCase):                                                                # K1b (WP-B, D-105)
    def test_the_moved_sentences_are_the_documented_27_with_no_duplicates_and_none_is_left_in_the_normal_corpus(self):
        self.assertEqual(len(corpus.NOTE_SYMPTOM_WORDS), 27)
        self.assertEqual(len(corpus.NOTE_SYMPTOM_WORDS), len(set(corpus.NOTE_SYMPTOM_WORDS)))
        self.assertEqual(set(corpus.NOTE_SYMPTOM_WORDS) & {text for group in NORMAL for text in group}, set())

    def test_a_symptom_word_alone_gives_one_mark_and_one_warning_and_neither_a_stop_nor_a_cut(self):
        for text in corpus.NOTE_SYMPTOM_WORDS:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.health, report.flags, report.level, report.stop), ("mark", "check", ("health_check",), "WARNING", False), text)
                self.assertEqual([finding.code for finding in report.findings], ["HEALTH_TOPIC"], text)
                made = ts.make(topic=text, content_type="explainer", primary_keyword=EXAMPLE_KEYWORD)
                self.assertEqual(sf.assess(made).stage, "mark")
                self.assertEqual(gn._evidence(made, report.flags, gn._Extra(), report.stage), gn.EVIDENCE_BASE["explainer"], "표시만(A)은 근거 점수를 깎지 않는다")
                self.assertEqual(gn._evidence(made, (), gn._Extra()), gn.EVIDENCE_BASE["explainer"], "건강 표시가 없는 같은 후보와 근거 점수가 같다")


class RiskCorpusTest(unittest.TestCase):
    def test_the_risk_corpus_has_the_documented_size(self):
        # 의도적 갱신(WP-B, D-105): 옛 (12, 28, …) — 옛 '확인 필요' 28 중 5개(증상 + 효과 + 단정)가 단정 위험으로 올라가 중지 17·확인 필요 23(근거 확인 필요 10 + 표시만 13)이 되었다
        self.assertEqual((len(corpus.RISK_HEALTH_STOP), len(corpus.RISK_HEALTH_CHECK), len(corpus.RISK_PROMISE), len(corpus.RISK_SPONSOR), len(corpus.RISK_EXPERIENCE)), (17, 23, 6, 22, 17))
        self.assertEqual((len(corpus.RISK_HEALTH_EVIDENCE), len(corpus.RISK_HEALTH_MARK)), (17, 6), "의도적 갱신(D-134): 질환 낱말만 든 글 7개가 표시만에서 근거 확인 필요로 옮김 — 옛 (10, 13)")
        self.assertEqual(corpus.RISK_HEALTH_CHECK, corpus.RISK_HEALTH_EVIDENCE + corpus.RISK_HEALTH_MARK)
        everything = corpus.RISK_HEALTH_STOP + corpus.RISK_HEALTH_EVIDENCE + corpus.RISK_HEALTH_MARK
        self.assertEqual(len(everything), len(set(everything)), "세 단계에 겹치는 문장이 없다")

    def test_a_medical_or_effect_assertion_stops_the_automatic_draft(self):
        for text in corpus.RISK_HEALTH_STOP:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.health, report.stage), ("stop", "stop"), text)
                self.assertTrue(report.stop)
                self.assertIn("health_check", report.flags)
                self.assertEqual(report.level, "ERROR")
                self.assertEqual([finding.code for finding in report.findings if finding.flag == "health_check"], ["HEALTH_STOP"])

    def test_a_health_topic_that_needs_evidence_is_a_warning_and_never_a_stop(self):
        for text in corpus.RISK_HEALTH_EVIDENCE:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.health, report.stage), ("check", "evidence"), text)
                self.assertIn("health_check", report.flags)
                self.assertFalse(report.stop)
                self.assertEqual([finding.code for finding in report.findings], ["HEALTH_EFFECT"])

    def test_a_health_topic_with_only_a_health_word_is_a_mark_and_never_a_stop(self):
        for text in corpus.RISK_HEALTH_MARK:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.health, report.stage), ("check", "mark"), text)
                self.assertIn("health_check", report.flags)
                self.assertFalse(report.stop)
                self.assertEqual([finding.code for finding in report.findings], ["HEALTH_TOPIC"])

    def test_a_promise_of_results_is_found_by_the_existing_judgement(self):
        for text in corpus.RISK_PROMISE:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertIn("result_promise", report.flags, text)
                self.assertTrue(report.stop)

    def test_a_sponsor_expression_in_the_text_is_only_suspected_and_never_confirmed(self):
        for text in corpus.RISK_SPONSOR:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual(report.relationship, "suspected", text)
                self.assertIn("sponsor_disclosure", report.flags)
                self.assertEqual(report.benefits, ())

    def test_a_claim_of_first_hand_experience_is_marked(self):
        for text in corpus.RISK_EXPERIENCE:
            with self.subTest(text=text):
                self.assertIn("experience_claim", sf.check_text([text]).flags, text)

    def test_the_not_yet_promise_list_is_not_pinned_either_way(self):
        for text in corpus.NOT_YET_PROMISE:
            sf.check_text([text])                                        # 어느 쪽으로도 못박지 않는다(다음 몫 후보) — 불러도 오류가 없으면 된다


class EngineShapedTest(unittest.TestCase):
    def test_the_engine_makes_57_normal_seeds_by_23_directions_with_no_flag(self):
        # 의도적 갱신(WP-B, D-105): 증상 낱말이 든 씨앗 10개는 `ENGINE_SYMPTOM_SEEDS` 로 옮겨(67 → 57) 아래 '표시만' 시험으로 못박는다
        self.assertEqual((len(corpus.ENGINE_NORMAL_SEEDS), len(corpus.ENGINE_DIRECTIONS), len(corpus.ENGINE_HEALTH_SEEDS), len(corpus.ENGINE_SYMPTOM_SEEDS)), (57, 23, 12, 10))
        count = 0
        for seed in corpus.ENGINE_NORMAL_SEEDS:
            for direction in corpus.ENGINE_DIRECTIONS:
                count += 1
                texts = engine_texts(seed, direction)
                self.assertEqual(sf.check_text(texts).flags, (), texts)
        self.assertEqual(count, 1311)

    def test_every_symptom_seed_is_a_mark_only_in_every_direction_and_never_stops_or_cuts_the_evidence(self):
        count = 0
        for seed in corpus.ENGINE_SYMPTOM_SEEDS:
            for direction in corpus.ENGINE_DIRECTIONS:
                count += 1
                report = sf.check_text(engine_texts(seed, direction))
                self.assertEqual((report.stage, report.flags, report.stop), ("mark", ("health_check",), False), (seed, direction))
        self.assertEqual(count, 230)

    def test_the_directions_are_the_ones_the_expansion_table_and_the_channel_profiles_know(self):
        known = {ex.direction_of(word).known for word in corpus.ENGINE_DIRECTIONS}
        self.assertEqual(known, {True})

    def test_every_health_seed_needs_a_check_in_every_direction_and_none_stops(self):
        count = 0
        for seed in corpus.ENGINE_HEALTH_SEEDS:
            for direction in corpus.ENGINE_DIRECTIONS:
                count += 1
                report = sf.check_text(engine_texts(seed, direction))
                self.assertEqual((report.health, report.stop), ("check", False), (seed, direction))
                # WP-B(D-105): 건강 씨앗만으로는 '표시만(A)' 이고, 방향 낱말이 효과 낱말('생활 부담 줄이기' 의 ‘줄이’)을 더하면 '근거 확인 필요(B)' 다 — 어느 쪽도 중지가 아니다
                # D-134(운영자 ③) 의도적 갱신: 질환 낱말이 든 씨앗(당뇨·고혈압·탈모·불면증·콜레스테롤·관절염·치매)은 어느 방향이든 근거 확인 필요다 — 질환 단독 = B
                self.assertEqual(report.stage, "evidence" if direction == "생활 부담 줄이기" or cn.health_signals([seed]).disease else "mark", (seed, direction))
        self.assertEqual(count, 276)


class BoundaryTrapTest(unittest.TestCase):                                                                     # K4 (보완 1차, D-58)
    STOP_LOOKALIKES = ("통신비 만원 바로 줄이는 방법", "에어컨 설치 매뉴얼을 완전히 개선하는 방법", "개인정보 약관 보안을 확실히 강화하는 방법", "고객 이탈 모델 정확도를 확실히 높이는 방법",
                       "거래처 방문 일정을 즉시 줄이는 방법", "지방 간 택배 비용을 바로 줄이는 방법", "필요한 약관 확인 시간을 즉시 줄이는 방법")
    SEEDS = ("에어컨 설치 매뉴얼", "개인정보 약관 정리", "고객 이탈 모델", "지방 간 택배", "거래처 방문 정리", "통신비 만원 줄이기", "에어컨 설치 매뉴얼 완전히 개선", "필요한 약관 정리")

    def test_a_normal_topic_with_effect_and_assertion_words_is_not_stopped_by_words_that_only_touch_across_a_space(self):
        for text in self.STOP_LOOKALIKES:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.flags, report.findings, report.health, report.stop, report.level), ((), (), "general", False, None), text)

    def test_a_seed_with_such_words_makes_candidates_with_no_flag_no_health_reason_and_no_evidence_penalty(self):
        for number, keyword in enumerate(self.SEEDS):
            seed = ts.example_seed(seed_id=f"bt-{number}", major="생활", minor="소형가전", keyword=keyword)
            found = gn.generate(ts.PROFILES["naver_a"], [seed], (), (), "2026-11-05", created_at="2026-11-05T09:00:00Z", target=200)
            self.assertGreaterEqual(len(found.candidates), 2, keyword)
            for candidate in found.candidates:
                with self.subTest(seed=keyword, candidate=candidate.topic):
                    self.assertEqual(candidate.safety_flags, ())
                    self.assertEqual(candidate.scores.factors.evidence, gn.EVIDENCE_BASE[candidate.content_type], "근거 점수에서 건강 감점(20)이 빠지지 않았다")
                    self.assertFalse(sf.assess(candidate).stop)
                    self.assertFalse([line for line in candidate.selection_reasons if "건강" in line or "의료" in line or "단정" in line], candidate.selection_reasons)


if __name__ == "__main__":
    unittest.main()
