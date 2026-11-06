"""규칙 기반 안전 표시(`topics/safety.py`) 시험 — P2b 보완(D-50·D-51)으로 다시 썼다: 낱말 하나가 아니라 **개념군 조합**으로 상태·표시·알림을 정한다.

지키는 것(S1~S10):
  S1) 건강은 (증상 S, 질환 D, 제품 P, 의료 효능어 M, 효과 E, 단정 A) 여섯 값의 64칸 표(`HEALTH_MATRIX`)가 네 단계를 정한다(WP-B, D-105) — 일반 생활정보 / A 표시만 / B 근거 확인 필요 / C 의료·효과 단정 위험(자동 초안 중지).
      칸마다 대표 예문이 그 칸으로 판정된다(64칸 전체·고정 기준·단조성·운영자 예시는 `test_topics_health_stages.py`).
  S2) 운영자 요청서의 예문(§2 정상·검토 필요, §3 건강·놓치던 8표현, §11 일반·건강·협찬·영어)이 요청서가 말한 대로 판정된다 — 일반 낱말(비교·모델·추천 …)은 표시도 감점도 없다.
  S3) 생활 습관 표현은 일반으로 남고, 의료적 주장이 붙은 습관 표현은 일반이 아니다.
  S4) 협찬: 태그·경로·유형·제안 중 협찬 정보는 가능성일 뿐이라 표시 없이 INFO 알림, 글 낱말은 추정, 브랜드 이름은 0, 확정된 협찬 정보만 표시를 강제한다. S5) `Campaign` 의 검증·연결·왕복.
  S6) 결과 약속은 기존 판정을 읽는다. S7) 경험 단정. S8) 입력 오류·표시 순서·`mark` 는 표시 칸만 바꿈. S9) `notes` 형식·길이. S10) 표시 값·`product_brand` 예약·`MAX_SHOWN`.
**낱말 표는 구현자 초기값이다 — 전략 원문과 2026-11-06 에 대조했고 원문이 정한 표가 아니다(이해관계 유형만 원문 대조로 정한 값, D-102·D-104).** 낱말 표 값 못박기는 `test_topics_concepts` 가, 이해관계 유형·충돌은 `test_topics_interest` 가 한다. 네트워크·파일·실제 시계·난수 없이 돈다.
"""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_corpus as corpus  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop.check import claims  # noqa: E402
from chanceblog_desktop.content.candidates import forbidden_claim  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import brand as br  # noqa: E402
from chanceblog_desktop.topics import concepts as cn  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402
from chanceblog_desktop.topics import notice as nt  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402

# 의도적 갱신(WP-B, D-105): 예전에는 (증상 s, 효과 e, 고위험 대상 p, 단정 a) 16칸이었다. 이제 열쇠는 (증상 S, 질환 D, 제품 P, 의료 효능어 M, 효과 E, 단정 A) 여섯 값이고 단계는 네 가지다.
# 대표 예문 16개(칸 → (단계, 글)) — 64칸 전부는 `test_topics_health_stages.py` 가 낱말을 조합해 만든 글로 본다.
CELLS = {
    (0, 0, 0, 0, 0, 0): ("general", "잠들기 전 스마트폰 알림을 정리하는 루틴"), (0, 0, 0, 0, 0, 1): ("general", "API 호출 설정을 완전히 정리하는 방법"), (0, 0, 0, 0, 1, 0): ("general", "성능 개선을 위한 캐시 설정"),
    (0, 0, 0, 0, 1, 1): ("general", "확실히 개선되는 설정 모음"), (0, 0, 1, 0, 0, 0): ("mark", "영양제 구매 기준"), (0, 0, 1, 0, 0, 1): ("stop", "영양제 확실한 선택법"),
    (0, 0, 1, 0, 1, 0): ("evidence", "영양제 효능 정리"), (0, 0, 0, 1, 0, 0): ("mark", "치료 방법 비교"), (0, 1, 0, 0, 0, 0): ("mark", "당뇨 환자 식단 정리"),
    (1, 0, 0, 0, 0, 0): ("mark", "수면 환경을 정리하는 생활 습관"), (1, 0, 0, 0, 1, 0): ("mark", "피로 해소를 위한 주말 정리 루틴"), (1, 0, 0, 0, 0, 1): ("mark", "스트레스 받는 날 완전히 비우는 책상 정리"),
    (1, 0, 0, 0, 1, 1): ("stop", "불면을 완화하는 확실한 방법"), (1, 0, 1, 1, 0, 0): ("stop", "불면을 치료하는 영양제 추천"), (0, 0, 1, 0, 1, 1): ("stop", "이 영양제는 반드시 효과가 있습니다"),
    (1, 0, 1, 0, 1, 1): ("stop", "영양제로 피로가 완전히 회복됩니다"),
}
# 요청서 예문 — (글, 건강 상태, 표시, 알림 코드). 알림 코드가 빈 글이면 알림이 없어야 한다.
REQUEST_ROWS = (
    ("AI 모델 비교", "general", (), ""), ("노트북 추천 기준", "general", (), ""), ("PC 부품 선택 가이드", "general", (), ""), ("업무 자동화 도구 추천", "general", (), ""),
    ("무료·유료 SaaS 비교", "general", (), ""), ("소형가전 구매 기준", "general", (), ""), ("PC 부품 추천 기준", "general", (), ""), ("노트북 선택 가이드", "general", (), ""),
    ("업무 자동화 도구 비교", "general", (), ""), ("SaaS 기능 비교", "general", (), ""), ("그래픽카드 모델별 VRAM 비교", "general", (), ""),
    # 의도적 갱신(WP-B, D-105 — 운영자 2026-11-06 세 단계): ① (증상 + 효과 + 단정)·(증상 + 치료 + 제품)은 '확인 필요' 에서 단정 위험(중지)으로 올랐다(불면 완화 확실·불면 치료 영양제·무조건 효과 다이어트).
    # ② 증상 낱말만 있는 문장(수면 환경·숙면·활력·붓기·피로 해소·자세 개선·체형 관리·속 편한 습관·집중력 향상)은 '일반' 에서 '표시만(A)' 이 되었다 — 감점 0·중지 아님.
    ("수익을 보장하는 투자 종목 추천", "general", ("result_promise",), "RESULT_PROMISE"), ("불면을 치료하는 영양제 추천", "stop", ("health_check",), "HEALTH_STOP"),
    ("통증을 완전히 없애는 의료기기 추천", "stop", ("health_check",), "HEALTH_STOP"), ("무조건 효과가 있는 다이어트 방법", "stop", ("health_check",), "HEALTH_STOP"),
    ("한 달 안에 수익을 보장하는 AI 서비스", "general", ("result_promise",), "RESULT_PROMISE"), ("수면 환경을 정리하는 생활 습관", "check", ("health_check",), "HEALTH_TOPIC"),
    ("잠들기 전 화면 사용을 줄이는 루틴", "general", (), ""), ("잠들기 전 스마트폰 알림을 정리하는 루틴", "general", (), ""), ("불면을 완화하는 확실한 방법", "stop", ("health_check",), "HEALTH_STOP"),
    ("영양제로 피로가 완전히 회복됩니다", "stop", ("health_check",), "HEALTH_STOP"), ("숙면", "check", ("health_check",), "HEALTH_TOPIC"), ("활력", "check", ("health_check",), "HEALTH_TOPIC"),
    ("붓기", "check", ("health_check",), "HEALTH_TOPIC"), ("피로 해소", "check", ("health_check",), "HEALTH_TOPIC"),
    ("자세 개선", "check", ("health_check",), "HEALTH_TOPIC"), ("체형 관리", "check", ("health_check",), "HEALTH_TOPIC"), ("속 편한 습관", "check", ("health_check",), "HEALTH_TOPIC"),
    ("집중력 향상", "check", ("health_check",), "HEALTH_TOPIC"),
    ("투자 수익을 보장하는 종목 추천", "general", ("result_promise",), "RESULT_PROMISE"), ("제습기 구매 전 확인 기준", "general", (), ""),
    ("업체로부터 제품을 제공받음", "general", ("sponsor_disclosure",), "ECONOMIC_CHECK"), ("제휴 링크를 통한 수수료 수령", "general", ("sponsor_disclosure",), "ECONOMIC_CHECK"),
    ("I used this product for two weeks.", "general", ("experience_claim",), "EXPERIENCE_CLAIM"), ("This model is widely used in automation.", "general", (), ""),
)
NOT_GENERAL_HABITS = ("불면증 극복하는 수면 루틴", "영양제 먹는 숙면 루틴", "스트레스를 확실히 줄이는 습관", "혈압 낮추는 생활 습관", "당뇨 관리 식단 루틴", "숙면을 돕는 확실한 수면 습관",
                      "피로를 완전히 해소하는 아침 루틴", "탈모 예방 생활 습관")


def flags(texts, **options):
    return sf.check_text(texts, **options).flags


def campaign(**changes):
    values = {"campaign_id": "camp-1", "benefits": ("goods",), "status": "confirmed", "seed_id": "seed-gpu"}
    values.update(changes)
    return sf.Campaign(**values)


class HealthMatrixTest(unittest.TestCase):                                                              # S1
    def test_the_matrix_is_the_sixty_four_cell_table_and_the_old_three_states_are_unchanged(self):
        # 의도적 갱신(WP-B, D-105): 예전 16칸 (s, e, p, a) 표가 64칸 (S, D, P, M, E, A) 표가 되었다 — 칸 값 하나하나와 식은 `test_topics_health_stages.py` 가 손으로 쓴 표와 맞춰 본다
        self.assertEqual(len(sf.HEALTH_MATRIX), 64)
        self.assertEqual(set(sf.HEALTH_MATRIX), {(s, d, p, m, e, a) for s in (0, 1) for d in (0, 1) for p in (0, 1) for m in (0, 1) for e in (0, 1) for a in (0, 1)})
        self.assertEqual(set(sf.HEALTH_MATRIX.values()), set(sf.HEALTH_STAGES))
        self.assertEqual((sf.HEALTH_GENERAL, sf.HEALTH_CHECK, sf.HEALTH_STOP), ("general", "check", "stop"))
        self.assertEqual(dict(sf.HEALTH_STATE_KO), {"general": "일반 생활정보", "check": "건강 정보 확인 필요", "stop": "의료·효과 단정 위험"})

    def test_every_cell_has_a_representative_sentence_that_lands_in_it(self):
        for key, (stage, text) in CELLS.items():
            with self.subTest(cell=key, text=text):
                self.assertEqual(cn.health_signals([text]).concept_key(), key)
                report = sf.check_text([text])
                self.assertEqual(report.stage, stage)
                self.assertEqual(report.health, {"general": "general", "mark": "check", "evidence": "check", "stop": "stop"}[stage])
                self.assertEqual(sf.HEALTH_MATRIX[key], stage)

    def test_a_general_text_has_no_flag_a_check_has_a_warning_and_a_stop_has_an_error_that_stops(self):
        general = sf.check_text(["잠들기 전 화면 사용을 줄이는 생활 습관"])
        self.assertEqual((general.flags, general.findings, general.level, general.stop), ((), (), None, False))
        check = sf.check_text(["영양제 효능 정리"])                                      # 의도적 갱신(D-105): 옛 예문 '불면을 완화하는 확실한 방법' 은 이제 단정 위험이라 경고가 아니라 오류다
        self.assertEqual((check.flags, check.level, check.stop), (("health_check",), "WARNING", False))
        stop = sf.check_text(["영양제로 피로가 완전히 회복됩니다"])
        self.assertEqual((stop.flags, stop.level, stop.stop), (("health_check",), "ERROR", True))

    def test_the_level_of_a_report_is_the_highest_of_its_notices(self):
        self.assertEqual(sf.check_text(["수익 보장 영양제 구매 기준"]).level, "ERROR", "경고와 오류가 함께 있으면 오류")
        self.assertEqual(sf.check_text(["영양제 구매 기준"], opportunity=True).level, "WARNING", "참고와 경고가 함께 있으면 경고")
        self.assertEqual(sf.check_text(["로컬 AI 사양 확인"], opportunity=True).level, "INFO")

    def test_the_alert_code_follows_the_reason_for_the_check(self):
        # 의도적 갱신(D-105): 알림 코드는 단계가 정한다 — A 표시만 HEALTH_TOPIC · B 근거 확인 필요 HEALTH_EFFECT · C 단정 위험 HEALTH_STOP. 옛 HEALTH_CLAIM 은 이 표에서 쓰이지 않는다
        for text, code in (("영양제 구매 기준", "HEALTH_TOPIC"), ("치료 방법 비교", "HEALTH_TOPIC"), ("영양제 효능 정리", "HEALTH_EFFECT"), ("불면을 완화하는 확실한 방법", "HEALTH_STOP"),
                           ("영양제 확실한 선택법", "HEALTH_STOP"), ("당뇨 환자 식단 정리", "HEALTH_TOPIC"), ("영양제로 피로가 완전히 회복됩니다", "HEALTH_STOP")):
            with self.subTest(text=text):
                self.assertEqual([finding.code for finding in sf.check_text([text]).findings], [code])

    def test_the_words_shown_come_one_per_concept_group_in_the_order_symptom_effect_product_assertion(self):
        finding = sf.check_text(["불면을 완화하는 확실한 방법"]).findings[0]
        self.assertEqual((finding.matched, finding.groups), (("불면", "완화", "확실"), ("증상·상태", "효과·결과", "단정·보장")))
        finding = sf.check_text(["영양제로 피로가 완전히 회복됩니다"]).findings[0]
        self.assertEqual(finding.groups, ("증상·상태", "효과·결과", "제품·행위", "단정·보장"))
        self.assertEqual(len(finding.matched), 4)
        self.assertEqual(sf.MAX_SHOWN, 4)

    def test_english_wording_is_judged_the_same_way_and_a_security_word_is_not_medicine(self):
        self.assertEqual(sf.check_text(["This supplement will cure diabetes"]).health, "stop")
        self.assertEqual(sf.check_text(["How to relieve stress and improve sleep"]).stage, "mark", "의도적 갱신(D-105): 증상 낱말(stress·sleep)이 있으면 영어도 표시만(A) 이다 — 옛 '일반' 에서 바뀜")
        self.assertEqual(sf.check_text(["Handling remediation steps in the security backlog"]).health, "general")


class RequestExamplesTest(unittest.TestCase):                                                           # S2
    def test_every_example_the_request_gives_is_judged_as_the_request_says(self):
        for text, state, expected_flags, code in REQUEST_ROWS:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.health, report.flags), (state, expected_flags))
                self.assertEqual([finding.code for finding in report.findings], [code] if code else [])

    def test_the_general_words_alone_never_give_a_flag_even_in_a_candidate(self):
        for text in ("AI 모델 비교", "PC 부품 추천 기준", "노트북 선택 가이드", "업무 자동화 도구 비교", "그래픽카드 모델별 VRAM 비교"):
            for content_type in ("buying_guide", "comparison", "service_intro", "explainer"):
                with self.subTest(text=text, content_type=content_type):
                    self.assertEqual(sf.assess(ts.make(topic=text, content_type=content_type, primary_keyword="예시 키워드")).flags, ())

    def test_the_review_needed_examples_are_at_least_a_warning_or_an_error(self):
        for text in ("수익을 보장하는 투자 종목 추천", "불면을 치료하는 영양제 추천", "통증을 완전히 없애는 의료기기 추천", "무조건 효과가 있는 다이어트 방법", "한 달 안에 수익을 보장하는 AI 서비스"):
            with self.subTest(text=text):
                self.assertIn(sf.check_text([text]).level, ("WARNING", "ERROR"))


class LifeHabitTest(unittest.TestCase):                                                                 # S3
    def test_life_habit_expressions_without_a_symptom_word_stay_general(self):
        # 의도적 갱신(D-105): 증상 낱말(피로·스트레스·수면·집중력·체중·붓기·소화 …)이 든 14문장은 이 목록에서 `NOTE_SYMPTOM_WORDS` 로 옮겨 가 24 → 10 이 되었다
        self.assertEqual(len(corpus.NORMAL_KO_HABIT), 10)
        for text in corpus.NORMAL_KO_HABIT:
            with self.subTest(text=text):
                self.assertEqual(sf.check_text([text]).health, "general")
                self.assertEqual(sf.check_text([text]).flags, ())

    def test_life_habit_expressions_with_a_symptom_word_are_only_marked(self):
        habits = corpus.NOTE_SYMPTOM_WORDS[10:24]                                          # 옛 NORMAL_KO_HABIT 14
        self.assertEqual(len(habits), 14)
        for text in habits:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.flags, report.stop), ("mark", ("health_check",), False))

    def test_a_medical_claim_does_not_become_general_because_the_word_routine_or_habit_is_in_it(self):
        self.assertEqual(len(NOT_GENERAL_HABITS), 8)
        for text in NOT_GENERAL_HABITS:
            with self.subTest(text=text):
                self.assertNotEqual(sf.check_text([text]).health, "general")
                self.assertIn("health_check", sf.check_text([text]).flags)


class SponsorTest(unittest.TestCase):                                                                   # S4
    def test_a_tag_a_sponsor_route_a_prep_kind_and_a_text_without_sponsor_words_only_give_a_possibility(self):
        for changes in ({"source_type": "sponsor"}, {"candidate_type": "sponsor_prep"}, {"monetization_tags": ("pc_parts",)}):
            with self.subTest(changes=changes):
                report = sf.assess(ts.make(content_type="explainer", **changes))
                self.assertEqual((report.flags, report.opportunity, report.relationship), ((), "possible", "none"))
                self.assertEqual([(finding.code, finding.flag, finding.level) for finding in report.findings], [("COLLAB_POSSIBLE", "", "INFO")])
                self.assertFalse(report.stop)
        none = sf.assess(ts.make(content_type="explainer"))
        self.assertEqual((none.findings, none.opportunity), ((), "none"))

    def test_a_sponsor_expression_in_the_text_is_suspected_and_gets_the_flag_but_is_never_confirmed(self):
        report = sf.check_text(["업체로부터 제품을 제공받음"])
        self.assertEqual((report.flags, report.relationship, report.benefits), (("sponsor_disclosure",), "suspected", ()))
        self.assertEqual([(f.code, f.level) for f in report.findings], [("ECONOMIC_CHECK", "WARNING")])
        self.assertEqual(sf.check_text(["제휴 링크를 통한 수수료 수령"]).findings[0].groups, ("제휴·수수료",))
        self.assertEqual(flags(["제습기 구매 전 확인 기준"]), (), "제목 낱말만으로 협찬을 확정하지 않는다")

    def test_a_hashtag_alone_is_a_suspicion_and_is_named_in_the_words_shown(self):
        report = sf.check_text(["#ad this laptop is great"])
        self.assertEqual((report.flags, report.relationship), (("sponsor_disclosure",), "suspected"))
        self.assertIn("해시태그", report.findings[0].matched)

    def test_a_brand_name_is_neither_a_sponsor_signal_nor_a_safety_signal(self):
        names = [hit.display for hit in br.BRANDS] + [key for key, _number in br.ALIASES] + [hit.latin for hit in br.BRANDS if hit.latin]
        self.assertEqual(len(br.BRANDS), 64)
        for name in names:
            with self.subTest(name=name):
                report = sf.check_text([name])
                self.assertEqual((report.flags, report.findings), ((), ()))

    def test_a_confirmed_campaign_forces_the_flag_whatever_the_text_says(self):
        for text in ("제습기 구매 전 확인 기준", "업체로부터 제품을 제공받음"):
            with self.subTest(text=text):
                report = sf.check_text([text], benefits=("goods", "affiliate"))
                # 의도적 갱신(전략 맞춤 1차, D-102): 옛 이름 입력은 그대로 받고, 결과는 새 이름(`PRODUCT_PROVIDED` …)·운영자 표시 이름('제휴 수수료')이다.
                self.assertEqual((report.flags, report.relationship, report.benefits), (("sponsor_disclosure",), "confirmed", ("PRODUCT_PROVIDED", "AFFILIATE_COMMISSION")))
                self.assertEqual([finding.code for finding in report.findings], ["ECONOMIC_CONFIRMED"], "추정 알림을 겹쳐 내지 않는다")
                self.assertEqual(report.findings[0].groups, ("제품 제공", "제휴 수수료"))

    def test_the_possibility_is_kept_beside_the_flag_and_the_confirmed_state_is_not_downgraded(self):
        report = sf.check_text(["업체로부터 제품을 제공받음"], opportunity=True)
        self.assertEqual((report.opportunity, report.relationship), ("possible", "suspected"))
        self.assertEqual([finding.code for finding in report.findings], ["ECONOMIC_CHECK"])

    def test_the_assess_path_uses_campaigns_that_reach_the_candidate(self):
        made = ts.make(content_type="explainer", seed_id="seed-gpu", source_topic_id="src-a")
        confirmed = sf.assess(made, campaigns=(campaign(),))
        self.assertEqual((confirmed.flags, confirmed.relationship, confirmed.benefits), (("sponsor_disclosure",), "confirmed", ("PRODUCT_PROVIDED",)))                   # 의도적 갱신(D-102): 새 이름으로 보관·보고
        proposed = sf.assess(made, campaigns=(campaign(status="proposed"),))
        self.assertEqual((proposed.flags, proposed.opportunity, proposed.relationship), ((), "possible", "none"))
        other = sf.assess(made, campaigns=(campaign(seed_id="other"),))
        self.assertEqual((other.flags, other.opportunity), ((), "none"), "이어지지 않은 협찬 정보는 닿지 않는다")
        self.assertEqual(sf.assess(made).flags, (), "협찬 정보를 안 주면 그 부분만 빠진다")

    def test_a_proposed_campaign_that_does_not_reach_the_candidate_is_not_counted_as_a_possibility(self):
        # 기준부터 있던 줄(독립 검증 V20 — `reaching` 대신 `listed` 로 바꿔도 시험이 못 잡던 빈틈): 후보에 닿지 않는 제안 중 협찬은 협업 가능성이 아니다.
        self.assertEqual(sf.assess(ts.make(seed_id="seed-gpu"), campaigns=(campaign(status="proposed", seed_id="other"),)).opportunity, "none")

    def test_the_module_never_makes_a_disclosure_sentence(self):
        text = Path(sf.__file__).read_text(encoding="utf-8") + Path(nt.__file__).read_text(encoding="utf-8")
        for needle in ("이 글은 광고", "소정의 원고료", "제공받아 작성"):
            self.assertNotIn(needle, text)


class CampaignTest(unittest.TestCase):                                                                  # S5
    def test_a_valid_campaign_keeps_its_values_and_turns_a_list_into_a_tuple(self):
        item = sf.Campaign(campaign_id="camp-1", benefits=["goods", "payment"], status="proposed", source_topic_id="src-a", channel="naver_a")
        # 의도적 갱신(전략 맞춤 1차, D-102): 옛 이름(`goods`·`payment`)으로 만들어도 새 이름으로 보관하고, 이득 종류는 `UNKNOWN`·`NONE` 을 뺀 양성 8개다(운영자 표 — 값은 test_topics_interest 가 못박는다).
        self.assertEqual((item.benefits, item.status, item.channel, item.seed_id), (("PRODUCT_PROVIDED", "HONORARIUM"), "proposed", "naver_a", None))
        self.assertEqual(sf.BENEFIT_KINDS, ("PRODUCT_PROVIDED", "SERVICE_PROVIDED", "VISIT_OR_MEAL_PROVIDED", "HONORARIUM", "DISCOUNT_OR_COUPON", "AFFILIATE_COMMISSION", "CONDITIONAL_REWARD", "OTHER"))
        self.assertEqual(sf.CAMPAIGN_STATUSES, ("confirmed", "proposed"))
        self.assertEqual(sf.MAX_CAMPAIGNS, 200)

    def test_every_kind_of_wrong_value_is_refused_with_the_content_invalid_code_and_plain_words(self):
        bad = ({"campaign_id": ""}, {"campaign_id": "a b"}, {"campaign_id": 3}, {"benefits": ()}, {"benefits": ("zzz",)}, {"benefits": ("goods", "goods")}, {"benefits": "goods"},
               {"benefits": ("goods",) * 6}, {"status": "maybe"}, {"seed_id": "a b"}, {"channel": "blogger_a"}, {"channel": "zzz"}, {"seed_id": None})
        for changes in bad:
            with self.subTest(changes=changes):
                with self.assertRaises(AppError) as caught:
                    campaign(**changes)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                self.assertEqual(nt.leaks(caught.exception.slots["항목"]), (), caught.exception.slots["항목"])

    def test_a_campaign_with_no_link_at_all_is_refused(self):
        with self.assertRaises(AppError):
            sf.Campaign(campaign_id="c1", benefits=("goods",), status="confirmed")

    def test_the_links_work_alone_or_together_and_the_channel_narrows(self):
        made = ts.make(seed_id="seed-gpu", source_topic_id="src-a", candidate_id="cand0001", channel="naver_b")
        self.assertTrue(campaign(seed_id="seed-gpu").applies_to(made))
        self.assertTrue(campaign(seed_id=None, source_topic_id="src-a").applies_to(made))
        self.assertTrue(campaign(seed_id=None, candidate_id="cand0001").applies_to(made))
        self.assertTrue(campaign(seed_id="nope", candidate_id="cand0001").applies_to(made), "하나라도 맞으면 닿는다")
        self.assertFalse(campaign(seed_id="nope").applies_to(made))
        self.assertTrue(campaign(channel="naver_b").applies_to(made))
        self.assertFalse(campaign(channel="naver_a").applies_to(made))

    def test_the_json_round_trip_is_exact_and_strict(self):
        item = campaign(benefits=("goods", "reward"), source_topic_id="src-a", channel="naver_b")
        data = item.to_dict()
        self.assertEqual(sorted(data), sorted(sf.CAMPAIGN_KEYS))
        self.assertEqual(sf.Campaign.from_dict(data), item)
        for broken in ({**data, "zzz": 1}, {key: value for key, value in data.items() if key != "status"}, {**data, "schema": 2}, {**data, "schema": True}, {**data, "benefits": ["zzz"]}, 3, None, []):
            with self.subTest(broken=str(broken)[:40]):
                with self.assertRaises(AppError):
                    sf.Campaign.from_dict(broken)
        with self.assertRaises(AppError) as caught:
            sf.Campaign.from_dict({**data, "zzz": 1})
        self.assertIn("모르는 칸", caught.exception.slots["항목"])
        self.assertEqual(nt.leaks(caught.exception.slots["항목"]), ())


class PromiseTest(unittest.TestCase):                                                                   # S6
    def test_a_promise_of_results_is_found_by_the_same_judgement_as_the_candidate_fields(self):
        for text in ("상위노출 보장 방법", "수익 보장 후기", "검색 1위 가능성 높이기", "guaranteed #1 ranking", "수익을 보장하는 투자 종목 추천"):
            with self.subTest(text=text):
                self.assertIsNotNone(forbidden_claim(text))
                found = sf.check_text([text])
                self.assertIn("result_promise", found.flags)
                self.assertEqual(found.findings[-1].matched, (forbidden_claim(text)[0],))
                self.assertEqual((found.findings[-1].code, found.findings[-1].level), ("RESULT_PROMISE", "ERROR"))
                self.assertTrue(found.stop)

    def test_a_text_that_warns_against_a_promise_or_does_not_promise_goes_through(self):
        for text in ("상위노출 보장 업체 피하는 법", "상위노출을 보장하지 않는 이유", "수익 구조 비교", "원금 보장형 상품 차이 설명", "손실 없는 투자는 없다는 말의 진실", "수익 보장 광고에 속지 않는 법"):
            with self.subTest(text=text):
                self.assertNotIn("result_promise", flags([text]))


class ExperienceTest(unittest.TestCase):                                                                # S7
    def test_a_claim_of_first_hand_experience_is_marked_with_the_name_of_the_existing_check(self):
        found = sf.check_text(["로봇청소기 직접 써본 후기"])
        self.assertIn("experience_claim", found.flags)
        self.assertIn(claims.LABELS[claims.EXPERIENCE_USE], found.findings[0].matched)
        for text, category in (("제주 숙소 다녀왔습니다", claims.EXPERIENCE_VISIT), ("이 제품을 구매했습니다", claims.EXPERIENCE_BUY), ("효과를 체감했습니다", claims.EXPERIENCE_EFFECT)):
            with self.subTest(text=text):
                self.assertIn(claims.LABELS[category], sf.check_text([text]).findings[-1].matched)

    def test_a_review_word_alone_is_not_a_claim_but_a_genre_word_or_a_marker_with_it_is(self):
        for text in ("후기 쓰는 법", "코드 리뷰 체크리스트", "리뷰 보는 법", "후기 믿어도 될까"):
            with self.subTest(text=text):
                self.assertNotIn("experience_claim", flags([text]))
        for text in ("노트북 사용기", "솔직 후기 공유", "한 달 리뷰", "I used this product for two weeks."):
            with self.subTest(text=text):
                self.assertIn("experience_claim", flags([text]))

    def test_how_to_wording_that_only_teaches_is_not_an_experience_claim_and_the_old_claims_check_is_unchanged(self):
        for text in ("로봇청소기 직접 써보는 방법", "로봇청소기 구매 기준", "로컬 AI 사양 확인", "설치 방법 따라 하기", "This guide is used to compare features.", "The hotel can be visited by train."):
            with self.subTest(text=text):
                self.assertNotIn("experience_claim", flags([text]))
        self.assertEqual([claim.category for claim in claims.find_violations(["로봇청소기 직접 써본 후기"])], ["experience_use"])


class CheckInputTest(unittest.TestCase):                                                                # S8
    def test_nothing_found_gives_an_empty_report_that_equals_the_default(self):
        self.assertEqual(sf.check_text(["로컬 AI 사양 확인"]), sf.SafetyReport((), ()))
        self.assertEqual(sf.check_text([]), sf.SafetyReport((), ()))
        self.assertEqual(sf.SafetyReport((), ()), sf.SafetyReport((), (), "general", "none", "none", ()))

    def test_wrong_inputs_are_programming_errors(self):
        for bad in ("글", b"bytes", None, 3, {"글"}, [1], ["글", None], ("글",) + (3,)):
            with self.subTest(texts=repr(bad)[:20]):
                with self.assertRaises(TypeError):
                    sf.check_text(bad)
        for bad in (1, "yes", None):
            with self.assertRaises(TypeError):
                sf.check_text(["글"], opportunity=bad)
        for bad in ("goods", ("zzz",), ("goods", "goods"), 3, None):
            with self.assertRaises(TypeError):
                sf.check_text(["글"], benefits=bad)
        with self.assertRaises(ValueError):
            sf.check_text(["글"] * 51)
        self.assertEqual(sf.check_text(["글"] * 50), sf.SafetyReport((), ()))
        self.assertEqual(sf.check_text(("당뇨",)).flags, ("health_check",), "튜플도 받는다")
        with self.assertRaises(TypeError):
            sf.check_text(["글"], content_type="comparison")                              # 옛 인자는 없어졌다(글 종류는 신호가 아니다)

    def test_the_flags_come_in_the_documented_order_whatever_order_the_checks_found_them_in(self):
        found = sf.check_text(["수익 보장 영양제 확실히 치료 협찬 제공받음 직접 써본 후기"], opportunity=True)
        self.assertEqual(found.flags, tuple(flag for flag in md.SAFETY_FLAGS if flag != "product_brand"))
        self.assertEqual([finding.flag for finding in found.findings], [flag for flag in md.SAFETY_FLAGS if flag in found.flags])
        info = sf.check_text(["로컬 AI 사양 확인"], opportunity=True)
        self.assertEqual(info.findings[-1].flag, "", "표시 없는 INFO 는 맨 뒤다")
        mixed = sf.check_text(["수익 보장 방법"], opportunity=True)
        self.assertEqual([finding.flag for finding in mixed.findings], ["result_promise", ""], "참고(INFO)가 먼저 만들어져도 표시가 있는 알림 뒤로 간다")

    def test_the_input_is_not_changed_and_the_same_text_gives_the_same_report(self):
        texts = ["영양제 후기", "협찬 제공받음"]
        before = list(texts)
        first = sf.check_text(texts)
        self.assertEqual(texts, before)
        self.assertEqual(first, sf.check_text(texts))

    def test_mark_adds_only_the_flag_field_and_keeps_every_other_value(self):
        base = ts.rated(70, topic="당뇨 관리 습관 정리", content_type="explainer", work_status="REVIEW", review_expires_at=None)
        marked = sf.mark(base)
        self.assertEqual(marked.safety_flags, ("health_check",))
        for name in ("scores", "recommendation_band", "work_status", "topic", "primary_keyword", "candidate_id", "review_expires_at", "channel", "duplicate_status", "monetization_tags"):
            self.assertEqual(getattr(marked, name), getattr(base, name), name)
        self.assertEqual((marked.recommendation_band, marked.work_status), ("GENERAL", "REVIEW"), "표시는 구간·작업 상태를 바꾸지 않는다")
        self.assertEqual(base.safety_flags, (), "원래 후보는 바뀌지 않는다")

    def test_mark_keeps_the_flags_that_were_already_there_and_orders_the_union(self):
        base = ts.make(content_type="explainer", topic="당뇨 관리 습관 정리", safety_flags=("sponsor_disclosure",))
        self.assertEqual(sf.mark(base).safety_flags, ("health_check", "sponsor_disclosure"))
        self.assertEqual(sf.mark(sf.mark(base)).safety_flags, ("health_check", "sponsor_disclosure"), "두 번 불러도 같다")
        kept = ts.make(content_type="explainer", safety_flags=("health_check",))
        self.assertIs(sf.mark(kept), kept, "새로 찾은 표시가 없으면 같은 후보를 돌려준다")
        plain = ts.make(content_type="explainer")
        self.assertIs(sf.mark(plain), plain)

    def test_mark_never_removes_a_candidate_and_a_stop_is_only_reported_not_applied(self):
        made = ts.make(topic="영양제로 피로가 완전히 회복됩니다 소개", primary_keyword="영양제 피로 회복")
        marked = sf.mark(made)
        self.assertIsInstance(marked, md.TopicCandidate)
        self.assertEqual(md.TopicCandidate.from_dict(marked.to_dict()), marked)
        self.assertTrue(sf.assess(made).stop)
        self.assertEqual(marked.work_status, made.work_status, "자동 초안 중지는 상태로 저장하지 않는다")

    def test_wrong_kinds_are_programming_errors(self):
        for bad in (None, {"topic": "x"}, "글", ts.make().to_dict()):
            with self.assertRaises(TypeError):
                sf.assess(bad)
            with self.assertRaises(TypeError):
                sf.mark(bad)
        for bad in ("글", ["x"], 3, (None,)):
            with self.assertRaises(TypeError):
                sf.assess(ts.make(), campaigns=bad)

    def test_a_candidates_target_reader_is_not_judged(self):
        self.assertEqual(sf.assess(ts.make(content_type="explainer", target_reader="당뇨 환자 독자")).flags, ())


class NotesTest(unittest.TestCase):                                                                     # S9
    def test_warnings_and_errors_each_get_one_plain_line_and_info_gets_none(self):
        report = sf.check_text(["수익 보장 영양제 확실히 치료 협찬 제공받음 직접 써본 후기"], opportunity=True)
        lines = sf.notes(report)
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith("의료·효과 단정 위험 — "))
        self.assertTrue(any(line.startswith("결과 약속 표현 — ") for line in lines))
        self.assertEqual(sf.notes(sf.check_text(["로컬 AI 사양 확인"], opportunity=True)), (), "참고(INFO)는 선정 이유에 넣지 않는다")
        self.assertEqual(sf.notes(sf.SafetyReport((), ())), ())

    def test_the_promise_line_has_no_words_that_were_found_and_the_others_end_with_them(self):
        lines = sf.notes(sf.check_text(["수익 보장 방법", "영양제 구매 기준"]))
        promise = next(line for line in lines if line.startswith("결과 약속 표현"))
        self.assertNotIn("걸린 말", promise)
        self.assertIn("(걸린 말: 영양제)", sf.notes(sf.check_text(["영양제 구매 기준"]))[0])

    def test_no_line_shows_the_star_of_a_prefix_entry_and_an_english_phrase_reads_plainly(self):
        line = sf.notes(sf.check_text(["this post contains an affiliate link"]))[0]
        self.assertIn("(걸린 말: affiliate link)", line)
        for group in (corpus.RISK_SPONSOR, corpus.RISK_EXPERIENCE, corpus.RISK_HEALTH_CHECK, corpus.RISK_HEALTH_STOP):
            for text in group:
                for shown in sf.notes(sf.check_text([text])):
                    self.assertNotIn("*", shown, text)

    def test_each_line_fits_the_candidates_selection_reason_rules_so_it_can_be_stored_there(self):
        report = sf.check_text(["영양제로 피로가 완전히 회복됩니다 협찬 제공받음 직접 써본 후기"])
        made = ts.make(selection_reasons=sf.notes(report))
        self.assertEqual(len(made.selection_reasons), 3)
        self.assertTrue(all(len(line) <= md.MAX_REASON and nt.is_clean(line) for line in made.selection_reasons))

    def test_the_words_shown_never_repeat_the_input_text(self):
        secret_text = "예시 아주 특별한 글 당뇨"
        for finding in sf.check_text([secret_text]).findings:
            self.assertTrue(all(secret_text not in word for word in finding.matched))
        self.assertTrue(all(secret_text not in line for line in sf.notes(sf.check_text([secret_text]))))

    def test_a_wrong_kind_is_a_programming_error(self):
        for bad in (None, (), [], "글", ("health_check",)):
            with self.assertRaises(TypeError):
                sf.notes(bad)


class PublicNamesTest(unittest.TestCase):                                                               # S10
    def test_the_five_flags_are_the_ones_the_candidate_model_lists_and_product_brand_is_never_made(self):
        self.assertEqual((sf.FLAG_HEALTH, sf.FLAG_PRODUCT, sf.FLAG_EXPERIENCE, sf.FLAG_SPONSOR, sf.FLAG_PROMISE), md.SAFETY_FLAGS)
        self.assertEqual(md.SAFETY_FLAGS, ("health_check", "product_brand", "experience_claim", "sponsor_disclosure", "result_promise"))
        self.assertEqual(dict(sf.FLAG_KO), {"health_check": "건강 표현", "product_brand": "제품·브랜드", "experience_claim": "경험 단정", "sponsor_disclosure": "협찬 고지", "result_promise": "결과 약속 표현"})
        for group in (corpus.NORMAL_NAVER_B, corpus.NORMAL_NAVER_A, corpus.RISK_HEALTH_CHECK, corpus.RISK_SPONSOR, corpus.RISK_EXPERIENCE, corpus.NORMAL_EN):
            for text in group:
                self.assertNotIn("product_brand", flags([text]), text)
                self.assertNotIn("product_brand", sf.assess(ts.make(topic=" ".join(text.split()), content_type="buying_guide", primary_keyword="예시 키워드")).flags)
        self.assertEqual((sf.MAX_TEXTS, sf.MAX_SHOWN), (50, 4))

    def test_the_module_lists_exactly_the_names_it_exports_and_changes_no_candidate_it_is_given(self):
        for name in sf.__all__:
            self.assertTrue(hasattr(sf, name), name)
        self.assertEqual(len(set(sf.__all__)), len(sf.__all__))
        made = ts.full()
        snapshot = made.to_dict()
        sf.assess(made)
        sf.mark(made)
        self.assertEqual(made.to_dict(), snapshot)
        self.assertEqual(dataclasses.replace(made).to_dict(), snapshot)

    def test_the_old_word_tables_are_gone_from_this_module_and_live_in_the_concepts_module(self):
        for name in ("HEALTH_WORDS_KO", "PRODUCT_WORDS_KO", "EXPERIENCE_WORDS_EN", "SPONSOR_WORDS_KO", "PRODUCT_CONTENT_TYPES"):
            self.assertFalse(hasattr(sf, name), name)
        self.assertTrue(hasattr(cn, "HEALTH_PRODUCT_KO"))
        self.assertFalse(hasattr(sf, "stop_flag"))                                         # 자동 초안 중지는 표시 값이 아니다
        self.assertNotIn("draft_stop", md.SAFETY_FLAGS)


if __name__ == "__main__":
    unittest.main()
