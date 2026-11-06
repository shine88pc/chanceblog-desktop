"""경제적 이해관계 유형 `UNKNOWN` + 9종(`topics/safety.py`) 시험 — 전략 맞춤 1차(D-102): 운영자가 2026-11-06 전략 원문 대조에서 정한 값·표시·의미와 옛 5종 이름 호환, 충돌 경고를 못박는다.

지키는 것(I1~I9):
  I1) 내부 값 10개·사용자 표시 10개·순서가 운영자 표와 글자 그대로 같다(이 시험이 손으로 쓴 표). 이득 종류(`BENEFIT_KINDS`)는 거기서 `UNKNOWN`·`NONE` 을 뺀 양성 8개이고 표시 이름과 서로 맞는다.
  I2) 옛 5종 이름 → 새 이름 5개. `Campaign`·`check_text` 는 옛·새 이름을 모두 받고 **새 이름으로 보관·내보낸다**(읽기 호환이다 — 저장된 자료를 바꾸지 않는다).
  I3) `Campaign.benefits` 는 양성 1~8개이거나 확정 상태의 정확히 `("NONE",)` 이다 — 중복(옛·새 이름이 같은 뜻이어도)·빈 목록·모르는 값·`UNKNOWN`·`NONE` 섞기·제안 중 `NONE` 은 거절하고 오류 글에는 한국어 이름만 나온다.
  I4) `SafetyReport.interests` — 기본 `("UNKNOWN",)`, 확정 양성이면 그 유형들(`INTEREST_TYPES` 순서), 명시 `NONE` 확인뿐이면 `("NONE",)`, 양성과 `NONE` 이 같이 닿으면 양성이 이긴다.
  I5) 글 낱말 추정(`suspected`)·협업 가능성·낱말 탐지는 저장된 상태를 바꾸지 못한다 — 확인해야 `NONE`·유형이 된다.
  I6) 저장된 상태가 `NONE` 인데 글에서 협찬이 추정되면 충돌이다: 추정 알림(`ECONOMIC_CHECK`) 대신 `ECONOMIC_CONFLICT` 하나만 나오고 표시는 같이 붙는다. 충돌이 아닌 네 경우(미확인+표현·확정 유형+표현 없음·확정 유형+`NONE`·`NONE`+표현 없음)도 못박는다.
  I7) 사용자에게 보이는 글(오류·알림·선정 이유)에는 영문 값 이름·목록 꼴이 없다 — 한국어 이름만. I8) 추정용 개념군(`concepts.SPONSOR_GROUPS` 5개)은 이번 묶음이 바꾸지 않았다. I9) 후보를 만드는 한 번의 실행(`generate`)에서도 같다.
네트워크·파일·실제 시계·난수 없이 돈다. 시험 자료는 모두 지어낸 예시다.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_corpus as corpus  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.errors.render import MAX_SLOT_CHARS  # noqa: E402
from chanceblog_desktop.topics import concepts as cn  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import notice as nt  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402

# 운영자 표(2026-11-06 채팅 — 전략 원문 §22.3 의 '없음' 포함 9종 + 아직 확인하지 않은 `UNKNOWN`) — 이 시험이 손으로 쓴 값이다. (내부 값, 사용자 표시) 순서 그대로.
OPERATOR_TABLE = (
    ("UNKNOWN", "미확인"), ("NONE", "없음"), ("PRODUCT_PROVIDED", "제품 제공"), ("SERVICE_PROVIDED", "서비스 제공"), ("VISIT_OR_MEAL_PROVIDED", "방문·식사 제공"), ("HONORARIUM", "원고료"),
    ("DISCOUNT_OR_COUPON", "할인·쿠폰"), ("AFFILIATE_COMMISSION", "제휴 수수료"), ("CONDITIONAL_REWARD", "조건부 보상"), ("OTHER", "기타"),
)
POSITIVE = ("PRODUCT_PROVIDED", "SERVICE_PROVIDED", "VISIT_OR_MEAL_PROVIDED", "HONORARIUM", "DISCOUNT_OR_COUPON", "AFFILIATE_COMMISSION", "CONDITIONAL_REWARD", "OTHER")
LABELS = tuple(label for _value, label in OPERATOR_TABLE[2:])
LEGACY = (("goods", "PRODUCT_PROVIDED"), ("service", "SERVICE_PROVIDED"), ("payment", "HONORARIUM"), ("affiliate", "AFFILIATE_COMMISSION"), ("reward", "CONDITIONAL_REWARD"))
RAW_NAMES = tuple(value for value, _label in OPERATOR_TABLE) + tuple(old for old, _new in LEGACY)
SUSPECT_TEXT = "업체로부터 제품을 제공받음"                                                                    # 글 낱말로 협찬이 추정되는 지어낸 글(`ECONOMIC_CHECK` 의 기준 예문)
PLAIN_TEXT = "로컬 AI 사양 확인"                                                                             # 협찬 표현이 없는 글
RAW_WORD = re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(RAW_NAMES) + r")(?![A-Za-z0-9_])")
A = ts.PROFILES["naver_a"]


def campaign(**changes):
    values = {"campaign_id": "camp-1", "benefits": ("PRODUCT_PROVIDED",), "status": "confirmed", "seed_id": "seed-gpu"}
    values.update(changes)
    return sf.Campaign(**values)


def refused(test, **changes):
    """거절 오류를 받아 **사용자에게 실제 보이는 글**(렌더링·자르기를 거친 `rendered().message`)을 돌려준다. 잘리기 전 슬롯만 검사하면 160자 한도(`MAX_SLOT_CHARS`)에서 문장이 잘려도 못 잡는다(독립 검증 낮음 2·3)."""
    with test.assertRaises(AppError) as caught:
        campaign(**changes)
    error = caught.exception
    test.assertEqual(error.code, "CONTENT_INVALID")
    shown = error.rendered().message
    test.assertLessEqual(len(error.slots["항목"]), MAX_SLOT_CHARS, "「항목」 글이 화면 한도보다 길다")
    test.assertNotIn("…", shown, "화면 글이 길이 한도에서 잘렸다 — " + shown)
    test.assertIn(error.slots["항목"], shown, "화면 글에 문장이 통째로 들어 있어야 한다")
    return shown


def codes(report):
    return [finding.code for finding in report.findings]


def shows_only_korean_names(test, text):
    test.assertEqual(nt.leaks(text), (), text)
    test.assertIsNone(RAW_WORD.search(text), text)


class ValuesTest(unittest.TestCase):                                                                            # I1
    def test_the_ten_values_and_their_display_names_are_exactly_the_operator_table_in_the_same_order(self):
        self.assertEqual(sf.INTEREST_TYPES, tuple(value for value, _label in OPERATOR_TABLE))
        self.assertEqual(list(sf.INTEREST_KO.items()), list(OPERATOR_TABLE))
        self.assertEqual((sf.INTEREST_UNKNOWN, sf.INTEREST_NONE), ("UNKNOWN", "NONE"))
        self.assertEqual(len(sf.INTEREST_TYPES), 10)

    def test_the_benefit_kinds_are_the_eight_positive_ones_and_match_the_display_names(self):
        self.assertEqual(sf.BENEFIT_KINDS, POSITIVE)
        self.assertEqual(tuple(sf.BENEFIT_KO), POSITIVE)
        self.assertEqual(tuple(sf.BENEFIT_KO.values()), LABELS)
        self.assertEqual(LABELS, ("제품 제공", "서비스 제공", "방문·식사 제공", "원고료", "할인·쿠폰", "제휴 수수료", "조건부 보상", "기타"))

    def test_the_three_constants_agree_with_one_another(self):
        self.assertEqual(len(sf.BENEFIT_KINDS), len(sf.INTEREST_TYPES) - 2)
        self.assertEqual(set(sf.BENEFIT_KINDS), set(sf.INTEREST_TYPES) - {"UNKNOWN", "NONE"})
        self.assertEqual(sf.BENEFIT_KINDS, tuple(kind for kind in sf.INTEREST_TYPES if kind in sf.BENEFIT_KINDS), "순서도 같다")
        self.assertEqual(set(sf.INTEREST_KO), set(sf.INTEREST_TYPES))
        self.assertEqual(set(sf.BENEFIT_KO), set(sf.BENEFIT_KINDS))
        for kind in sf.BENEFIT_KINDS:
            self.assertEqual(sf.BENEFIT_KO[kind], sf.INTEREST_KO[kind], kind)
        self.assertEqual(len(set(sf.INTEREST_TYPES)), 10)
        self.assertEqual(len(set(sf.INTEREST_KO.values())), 10, "표시 이름이 겹치지 않는다")

    def test_the_display_names_are_plain_korean_and_pass_the_leak_check(self):
        for value, label in sf.INTEREST_KO.items():
            with self.subTest(value=value):
                self.assertIsNone(re.search("[A-Za-z]", label), label)
                self.assertEqual(nt.leaks(label), ())
                self.assertNotIn(label, sf.INTEREST_TYPES)

    def test_the_legacy_names_map_to_the_new_ones_and_only_five(self):
        self.assertEqual(dict(sf.LEGACY_BENEFIT_NAMES), dict(LEGACY))
        self.assertEqual(len(sf.LEGACY_BENEFIT_NAMES), 5)
        for old, new in LEGACY:
            self.assertIn(new, sf.BENEFIT_KINDS)
            self.assertEqual(old, old.lower())
            self.assertNotIn(old, sf.INTEREST_TYPES)
        self.assertEqual(len(set(sf.LEGACY_BENEFIT_NAMES.values())), 5, "옛 이름 둘이 같은 새 이름으로 가지 않는다")


class CampaignTest(unittest.TestCase):                                                                          # I2 · I3
    def test_every_new_name_is_accepted_alone_and_all_eight_together_and_the_order_is_kept(self):
        for kind in POSITIVE:
            with self.subTest(kind=kind):
                self.assertEqual(campaign(benefits=(kind,)).benefits, (kind,))
        self.assertEqual(campaign(benefits=POSITIVE).benefits, POSITIVE)
        self.assertEqual(campaign(benefits=list(reversed(POSITIVE))).benefits, tuple(reversed(POSITIVE)), "받은 순서 그대로 보관한다")
        self.assertEqual(len(POSITIVE), len(sf.BENEFIT_KINDS))

    def test_the_old_names_are_accepted_and_kept_and_exported_as_the_new_names(self):
        for old, new in LEGACY:
            with self.subTest(old=old):
                item = campaign(benefits=(old,))
                self.assertEqual(item.benefits, (new,))
                self.assertEqual(item.to_dict()["benefits"], [new])
                self.assertEqual(item, campaign(benefits=(new,)), "옛 이름으로 만들어도 새 이름으로 만든 것과 같은 협찬 정보다")
        mixed = campaign(benefits=("goods", "HONORARIUM", "affiliate", "OTHER"))
        self.assertEqual(mixed.benefits, ("PRODUCT_PROVIDED", "HONORARIUM", "AFFILIATE_COMMISSION", "OTHER"))
        self.assertEqual(sf.Campaign.from_dict(mixed.to_dict()), mixed)

    def test_reading_a_campaign_stored_with_the_old_names_gives_the_new_names_without_touching_the_stored_data(self):
        stored = {**campaign().to_dict(), "benefits": ["goods", "payment"]}
        before = {**stored, "benefits": list(stored["benefits"])}
        item = sf.Campaign.from_dict(stored)
        self.assertEqual(item.benefits, ("PRODUCT_PROVIDED", "HONORARIUM"))
        self.assertEqual(stored, before, "읽기만 한다 — 받은 자료를 바꾸지 않는다(읽기 호환이지 저장 변환이 아니다)")
        self.assertEqual(item.to_dict()["benefits"], ["PRODUCT_PROVIDED", "HONORARIUM"])
        self.assertEqual(sf.Campaign.from_dict(item.to_dict()), item)

    def test_the_same_kind_twice_is_refused_even_when_one_is_the_old_spelling(self):
        for benefits in (("PRODUCT_PROVIDED", "PRODUCT_PROVIDED"), ("goods", "goods"), ("goods", "PRODUCT_PROVIDED"), ("PRODUCT_PROVIDED", "goods"), ("payment", "OTHER", "HONORARIUM")):
            with self.subTest(benefits=benefits):
                self.assertIn("두 번", refused(self, benefits=benefits))

    def test_none_is_accepted_only_alone_and_only_when_confirmed(self):
        item = campaign(benefits=("NONE",))
        self.assertEqual((item.benefits, item.status), (("NONE",), "confirmed"))
        self.assertEqual(campaign(benefits=["NONE"]).benefits, ("NONE",))
        self.assertEqual(item.to_dict()["benefits"], ["NONE"])
        self.assertEqual(sf.Campaign.from_dict(item.to_dict()), item)
        for benefits in (("NONE", "OTHER"), ("OTHER", "NONE"), ("NONE", "goods"), ("HONORARIUM", "NONE", "OTHER")):
            with self.subTest(mixed=benefits):
                self.assertIn("다른 종류와 함께", refused(self, benefits=benefits))
        self.assertIn("두 번", refused(self, benefits=("NONE", "NONE")))
        self.assertIn("확정", refused(self, benefits=("NONE",), status="proposed"))
        self.assertEqual(campaign(benefits=("OTHER",), status="proposed").benefits, ("OTHER",), "양성 유형은 제안·협의 중에도 적을 수 있다")

    def test_unknown_is_only_the_default_state_so_it_cannot_be_written_into_a_campaign(self):
        for benefits in (("UNKNOWN",), ("UNKNOWN", "OTHER"), ("OTHER", "UNKNOWN"), ("UNKNOWN", "NONE")):
            with self.subTest(benefits=benefits):
                shown = refused(self, benefits=benefits)                                  # 화면에 실제로 나가는 글(잘리지 않았는지도 refused 가 본다)
                self.assertIn("‘미확인’은 아직 확인하지 않은 기본 상태라 협찬 정보에 적을 수 없습니다", shown)
                self.assertIn("‘없음’ 하나만 적어 주세요", shown, "끝의 안내가 잘리지 않고 남아 있다")
                self.assertEqual(shown.count("미확인"), 1, "미확인은 거절한 값으로만 한 번 나오고 고를 선택지로 되풀이되지 않는다")
                self.assertNotIn("‘제품 제공’", shown, "이 문장은 선택지 목록을 되풀이하지 않는다(되풀이하면 160자에서 잘렸다)")

    def test_an_empty_list_a_wrong_kind_an_unknown_value_and_too_many_are_refused(self):
        too_many = POSITIVE + ("NONE",)
        for benefits in ((), [], ("zzz",), "goods", "PRODUCT_PROVIDED", None, 3, (3,), (None,), (["goods"],), ("Goods",), ("honorarium",), ("goods", "zzz"), too_many, ("goods",) * 9):
            with self.subTest(benefits=repr(benefits)[:40]):
                refused(self, benefits=benefits)
        self.assertIn(f"1~{len(sf.BENEFIT_KINDS)}개", refused(self, benefits=()), "오류 글의 '1~N개' 는 이득 종류의 수를 따라간다")
        self.assertIn("1~8개", refused(self, benefits=too_many))

    def test_the_error_sentences_name_the_choices_in_korean_and_never_in_english(self):
        for benefits in ((), ("zzz",), ("UNKNOWN",), ("NONE", "OTHER"), ("goods", "goods"), too_many()):
            with self.subTest(benefits=repr(benefits)[:40]):
                text = refused(self, benefits=benefits)
                shows_only_korean_names(self, text)
        text = refused(self, benefits=("zzz",))
        for label in LABELS + ("없음",):
            self.assertIn(f"‘{label}’", text)
        self.assertIn("‘없음’", refused(self, benefits=("NONE",), status="proposed"))
        shows_only_korean_names(self, refused(self, benefits=("NONE",), status="proposed"))

    def test_the_choices_a_campaign_error_offers_never_include_unknown(self):
        # 독립 검증 V27: 선택지 목록이 양성 8개가 아니라 `INTEREST_TYPES` 전체(미확인·없음 포함)를 보이는 변이를 잡는다 — '미확인' 은 고를 값이 아니다.
        for benefits in ((), [], ("zzz",), ("goods", "zzz"), too_many(), ("goods",) * 9, "goods", None):
            with self.subTest(benefits=repr(benefits)[:40]):
                shown = refused(self, benefits=benefits)
                self.assertNotIn("미확인", shown)
                self.assertNotIn(sf.INTEREST_KO["UNKNOWN"], shown)
                self.assertEqual(shown.count("‘없음’"), 1, "'없음' 은 단독으로 적는다는 안내로만 한 번 나온다")
                for label in LABELS:
                    self.assertEqual(shown.count(f"‘{label}’"), 1, label)

    def test_no_error_sentence_of_a_campaign_is_cut_by_the_screens_length_limit(self):
        # 이 묶음이 새로 만들거나 바꾼 `Campaign` 거절 문장 전수 — 사용자에게 실제 보이는 글이 160자 한도에서 잘리지 않는다(`refused` 가 렌더링된 글로 검사한다).
        cases = ((), [], ("zzz",), ("UNKNOWN",), ("UNKNOWN", "OTHER"), ("NONE", "OTHER"), ("OTHER", "NONE"), ("goods", "goods"), ("goods", "PRODUCT_PROVIDED"), too_many(), ("goods",) * 9, "goods", None, (3,))
        widest = 0
        for benefits in cases:
            with self.subTest(benefits=repr(benefits)[:40]):
                widest = max(widest, len(refused(self, benefits=benefits)))
        refused(self, benefits=("NONE",), status="proposed")
        for changes in ({"status": "maybe"}, {"campaign_id": "a b"}, {"channel": "blogger_a"}, {"seed_id": None}):
            refused(self, benefits=("OTHER",), **changes)
        self.assertGreater(widest, 100, "가장 긴 문장도 한도 안에서 잘리지 않고 통째로 나온다")

    def test_the_other_checks_of_a_campaign_still_work_with_the_new_kinds(self):
        for changes in ({"campaign_id": ""}, {"campaign_id": "a b"}, {"status": "maybe"}, {"seed_id": None}, {"channel": "blogger_a"}):
            with self.subTest(changes=changes):
                refused(self, benefits=("VISIT_OR_MEAL_PROVIDED",), **changes)
        self.assertTrue(campaign(benefits=("DISCOUNT_OR_COUPON",), channel="naver_a").applies_to(ts.make(seed_id="seed-gpu", channel="naver_a")))


def too_many():
    return POSITIVE + ("NONE",)


class ReportStateTest(unittest.TestCase):                                                                       # I4 · I5
    def test_the_default_state_is_unknown_for_a_report_nobody_confirmed(self):
        self.assertEqual(sf.SafetyReport((), ()).interests, ("UNKNOWN",))
        self.assertEqual(sf.check_text([PLAIN_TEXT]).interests, ("UNKNOWN",))
        self.assertEqual(sf.check_text([]).interests, ("UNKNOWN",))
        self.assertEqual(sf.check_text([PLAIN_TEXT]), sf.SafetyReport((), ()), "아무것도 안 걸리면 기본 보고서와 같다")
        self.assertEqual(sf.assess(ts.make()).interests, ("UNKNOWN",))

    def test_confirmed_positive_kinds_are_reported_in_the_table_order_whatever_the_input_order(self):
        for given, expected in ((("OTHER", "PRODUCT_PROVIDED", "HONORARIUM"), ("PRODUCT_PROVIDED", "HONORARIUM", "OTHER")), (("reward", "goods"), ("PRODUCT_PROVIDED", "CONDITIONAL_REWARD")),
                                (tuple(reversed(POSITIVE)), POSITIVE), (("VISIT_OR_MEAL_PROVIDED",), ("VISIT_OR_MEAL_PROVIDED",))):
            with self.subTest(given=given):
                report = sf.check_text([PLAIN_TEXT], benefits=given)
                self.assertEqual((report.interests, report.benefits), (expected, expected))
                self.assertEqual((report.flags, report.relationship, codes(report)), (("sponsor_disclosure",), "confirmed", ["ECONOMIC_CONFIRMED"]))
        self.assertEqual(sf.INTEREST_TYPES[2:], POSITIVE)

    def test_an_explicit_none_confirmation_alone_is_recorded_without_any_flag_or_benefit(self):
        report = sf.check_text([PLAIN_TEXT], none_confirmed=True)
        self.assertEqual((report.interests, report.benefits, report.flags, report.findings, report.relationship), (("NONE",), (), (), (), "none"))
        self.assertNotIn("NONE", report.benefits, "이득 종류에는 양성만 들어간다")

    def test_a_confirmed_kind_wins_over_none_in_check_text(self):
        report = sf.check_text([PLAIN_TEXT], benefits=("OTHER",), none_confirmed=True)
        self.assertEqual((report.interests, report.benefits, report.flags, codes(report)), (("OTHER",), ("OTHER",), ("sponsor_disclosure",), ["ECONOMIC_CONFIRMED"]))

    def test_a_confirmed_kind_wins_over_none_through_assess_with_two_campaigns_in_either_order(self):
        made = ts.make(seed_id="seed-gpu", source_topic_id="src-a")
        none = campaign(campaign_id="c-none", benefits=("NONE",))
        kind = campaign(campaign_id="c-kind", benefits=("DISCOUNT_OR_COUPON",), seed_id=None, source_topic_id="src-a")
        for order in ((none, kind), (kind, none)):
            with self.subTest(order=[item.campaign_id for item in order]):
                report = sf.assess(made, campaigns=order)
                self.assertEqual((report.interests, report.benefits, codes(report)), (("DISCOUNT_OR_COUPON",), ("DISCOUNT_OR_COUPON",), ["ECONOMIC_CONFIRMED"]))
        only_none = sf.assess(made, campaigns=(none,))
        self.assertEqual((only_none.interests, only_none.benefits, only_none.flags, only_none.findings), (("NONE",), (), (), ()))

    def test_a_none_campaign_counts_only_when_it_reaches_the_candidate_and_only_when_confirmed(self):
        made = ts.make(seed_id="seed-gpu", channel="naver_b")
        self.assertEqual(sf.assess(made, campaigns=(campaign(benefits=("NONE",), seed_id="other"),)).interests, ("UNKNOWN",), "이어지지 않은 확인은 닿지 않는다")
        self.assertEqual(sf.assess(made, campaigns=(campaign(benefits=("NONE",), channel="naver_a"),)).interests, ("UNKNOWN",), "다른 채널용 확인은 닿지 않는다")
        self.assertEqual(sf.assess(made, campaigns=(campaign(benefits=("NONE",), channel="naver_b"),)).interests, ("NONE",))
        proposed = sf.assess(made, campaigns=(campaign(benefits=("OTHER",), status="proposed"), campaign(campaign_id="c2", benefits=("NONE",))))
        self.assertEqual((proposed.interests, proposed.benefits, proposed.flags, codes(proposed), proposed.opportunity), (("NONE",), (), (), ["COLLAB_POSSIBLE"], "possible"),
                         "제안 중인 협찬은 확정이 아니다 — 확정된 '없음' 이 그대로 남고 협업 가능성만 참고로 알린다")

    def test_suspicion_and_possibility_never_change_the_unknown_state(self):
        for text in corpus.RISK_SPONSOR:
            with self.subTest(text=text):
                report = sf.check_text([text], opportunity=True)
                self.assertEqual((report.relationship, report.interests, report.benefits), ("suspected", ("UNKNOWN",), ()))
        for changes in ({"source_type": "sponsor"}, {"candidate_type": "sponsor_prep"}, {"monetization_tags": ("pc_parts",)}, {"topic": SUSPECT_TEXT, "monetization_tags": ("pc_parts",)}):
            with self.subTest(changes=changes):
                report = sf.assess(ts.make(content_type="explainer", **changes))
                self.assertEqual((report.interests, report.benefits), (("UNKNOWN",), ()))
                self.assertEqual(sf.assess(ts.make(content_type="explainer", **changes), campaigns=(campaign(seed_id="other"),)).interests, ("UNKNOWN",))
        proposed = sf.assess(ts.make(seed_id="seed-gpu"), campaigns=(campaign(status="proposed"),))
        self.assertEqual((proposed.opportunity, proposed.interests), ("possible", ("UNKNOWN",)), "제안·협의 중도 미확인을 바꾸지 못한다")

    def test_the_detection_in_the_text_never_changes_the_stored_state_whichever_state_it_is(self):
        stored = {"unknown": {}, "none": {"none_confirmed": True}, "kinds": {"benefits": ("HONORARIUM", "OTHER")}}
        expected = {"unknown": ("UNKNOWN",), "none": ("NONE",), "kinds": ("HONORARIUM", "OTHER")}
        for name, options in stored.items():
            plain = sf.check_text([PLAIN_TEXT], **options)
            for text in (SUSPECT_TEXT, *corpus.RISK_SPONSOR):
                with self.subTest(state=name, text=text):
                    found = sf.check_text([text], **options)
                    self.assertEqual((found.interests, found.benefits), (plain.interests, plain.benefits), "탐지가 있든 없든 저장된 상태는 같다")
                    self.assertEqual(found.interests, expected[name])
        self.assertEqual(sf.check_text([SUSPECT_TEXT]).relationship, "suspected")
        self.assertEqual(sf.check_text([SUSPECT_TEXT]).interests, ("UNKNOWN",), "추정은 추정일 뿐 미확인을 '있음' 으로 바꾸지 않는다")

    def test_check_text_checks_its_new_inputs(self):
        for bad in ("goods", ("zzz",), ("goods", "goods"), ("goods", "PRODUCT_PROVIDED"), ("NONE",), ("UNKNOWN",), 3, None, b"x", ("Goods",)):
            with self.subTest(benefits=repr(bad)):
                with self.assertRaises(TypeError):
                    sf.check_text([PLAIN_TEXT], benefits=bad)
        for bad in (1, "yes", None, 0):
            with self.subTest(none_confirmed=bad):
                with self.assertRaises(TypeError):
                    sf.check_text([PLAIN_TEXT], none_confirmed=bad)
        self.assertEqual(sf.check_text([PLAIN_TEXT], benefits=("goods", "OTHER")).benefits, ("PRODUCT_PROVIDED", "OTHER"), "옛 이름도 받는다")


class ConflictTest(unittest.TestCase):                                                                          # I6
    def test_none_plus_a_sponsor_expression_gives_exactly_one_conflict_warning_and_the_flag(self):
        report = sf.check_text([SUSPECT_TEXT], none_confirmed=True)
        self.assertEqual(codes(report), ["ECONOMIC_CONFLICT"])
        self.assertEqual((report.flags, report.relationship, report.interests, report.benefits), (("sponsor_disclosure",), "suspected", ("NONE",), ()))
        self.assertEqual((report.findings[0].level, report.findings[0].flag, report.level, report.stop), ("WARNING", "sponsor_disclosure", "WARNING", False))
        self.assertTrue(report.findings[0].matched and report.findings[0].groups, "걸린 말과 개념군 이름은 추정 알림과 같은 방식으로 담긴다")
        check = sf.check_text([SUSPECT_TEXT]).findings[0]
        self.assertEqual((report.findings[0].matched, report.findings[0].groups), (check.matched, check.groups))

    def test_the_conflict_is_found_through_assess_for_a_candidate_that_a_none_campaign_reaches(self):
        made = ts.make(seed_id="seed-gpu", topic="협찬 안내 확인 방법", primary_keyword="협찬 안내")
        report = sf.assess(made, campaigns=(campaign(benefits=("NONE",)),))
        self.assertEqual((codes(report), report.flags, report.interests), (["ECONOMIC_CONFLICT"], ("sponsor_disclosure",), ("NONE",)))
        self.assertEqual(sf.mark(made, campaigns=(campaign(benefits=("NONE",)),)).safety_flags, ("sponsor_disclosure",))
        self.assertEqual(codes(sf.assess(made)), ["ECONOMIC_CHECK"], "저장된 상태가 없으면 지금까지처럼 추정 알림이다")

    def test_the_four_cases_that_are_not_a_conflict(self):
        unknown_with_text = sf.check_text([SUSPECT_TEXT])
        self.assertEqual((codes(unknown_with_text), unknown_with_text.interests), (["ECONOMIC_CHECK"], ("UNKNOWN",)), "미확인 + 표현 = 지금 그대로(추정)")
        kind_without_text = sf.check_text([PLAIN_TEXT], benefits=("HONORARIUM",))
        self.assertEqual((codes(kind_without_text), kind_without_text.flags), (["ECONOMIC_CONFIRMED"], ("sponsor_disclosure",)), "확정 유형 + 표현 없음 = 확정이 표시를 강제하는 지금 동작")
        for text in (PLAIN_TEXT, SUSPECT_TEXT):
            both = sf.check_text([text], benefits=("HONORARIUM",), none_confirmed=True)
            self.assertEqual((codes(both), both.interests), (["ECONOMIC_CONFIRMED"], ("HONORARIUM",)), "확정 유형이 닿으면 '없음' 은 무시한다 — 충돌도 따지지 않는다")
        none_without_text = sf.check_text([PLAIN_TEXT], none_confirmed=True)
        self.assertEqual((codes(none_without_text), none_without_text.flags, none_without_text.interests), ([], (), ("NONE",)), "없음 + 표현 없음 = 조용하다")

    def test_the_conflict_alert_replaces_the_check_alert_and_the_two_never_appear_together(self):
        for text in (SUSPECT_TEXT, *corpus.RISK_SPONSOR, PLAIN_TEXT):
            for none_confirmed in (False, True):
                for benefits in ((), ("OTHER",)):
                    for opportunity in (False, True):
                        found = codes(sf.check_text([text], opportunity=opportunity, benefits=benefits, none_confirmed=none_confirmed))
                        with self.subTest(text=text, none=none_confirmed, kinds=benefits, opportunity=opportunity):
                            self.assertFalse("ECONOMIC_CHECK" in found and "ECONOMIC_CONFLICT" in found)
                            if "ECONOMIC_CONFLICT" in found:
                                self.assertTrue(none_confirmed and not benefits and text != PLAIN_TEXT)
                                self.assertEqual(len([code for code in found if code.startswith("ECONOMIC_")]), 1)
        for text in corpus.RISK_SPONSOR:
            self.assertEqual(codes(sf.check_text([text], none_confirmed=True)), ["ECONOMIC_CONFLICT"], text)
            self.assertEqual(codes(sf.check_text([text])), ["ECONOMIC_CHECK"], text)

    def test_the_possibility_of_a_collaboration_has_nothing_to_do_with_the_conflict(self):
        with_text = sf.check_text([SUSPECT_TEXT], opportunity=True, none_confirmed=True)
        self.assertEqual((codes(with_text), with_text.opportunity, with_text.relationship), (["ECONOMIC_CONFLICT"], "possible", "suspected"))
        without_text = sf.check_text([PLAIN_TEXT], opportunity=True, none_confirmed=True)
        self.assertEqual((codes(without_text), without_text.flags, without_text.interests), (["COLLAB_POSSIBLE"], (), ("NONE",)), "표현이 없으면 충돌이 아니다 — 가능성은 참고로만 알린다")

    def test_the_conflict_notice_is_one_fixed_warning_sentence_without_developer_shapes(self):
        level, title, message, action = nt.CATALOG["ECONOMIC_CONFLICT"]
        self.assertEqual((level, title), ("WARNING", "경제적 이해관계 확인 필요"))
        self.assertIn(f"‘{sf.INTEREST_KO['NONE']}’", message, "문장의 '없음' 이 표시 이름 표와 같다")
        self.assertIn("협찬", message)
        self.assertTrue(message.endswith(".") and action.endswith("."))
        notice = nt.make("ECONOMIC_CONFLICT")
        shows_only_korean_names(self, notice.text())
        self.assertNotEqual(notice.message, nt.CATALOG["ECONOMIC_CHECK"][2])
        report = sf.check_text([SUSPECT_TEXT], none_confirmed=True)
        notices = nt.from_report(report)
        self.assertEqual([item.code for item in notices], ["ECONOMIC_CONFLICT"])
        self.assertEqual((notices[0].level, notices[0].details), ("WARNING", tuple(dict.fromkeys(report.findings[0].groups))))
        lines = nt.notes(report)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("경제적 이해관계 확인 필요 — 저장된 상태는 ‘없음’인데 "), lines[0])
        shows_only_korean_names(self, lines[0])
        self.assertEqual(ts.make(selection_reasons=(lines[0],)).selection_reasons, (lines[0],), "후보의 선정 이유 규칙을 통과한다")
        for line in notices[0].lines():
            shows_only_korean_names(self, line)


class DisplayTest(unittest.TestCase):                                                                           # I7
    def test_every_confirmed_kind_is_shown_by_its_korean_name_only_in_the_notice_and_the_selection_reason(self):
        for kind, label in zip(POSITIVE, LABELS, strict=True):
            with self.subTest(kind=kind):
                report = sf.check_text(["예시 주제"], benefits=(kind,))
                notice = nt.from_report(report)[0]
                self.assertEqual((notice.code, notice.details), ("ECONOMIC_CONFIRMED", (label,)))
                line = nt.notes(report)[0]
                self.assertTrue(line.endswith(f"(걸린 말: {label})"), line)
                for text in (notice.text(), line):
                    shows_only_korean_names(self, text)
        every = sf.check_text(["예시 주제"], benefits=sf.BENEFIT_KINDS)
        self.assertEqual(nt.from_report(every)[0].details, LABELS, "8종이 모두 확정이면 이름 8개가 다 나온다(수정 1차 — 예전엔 4개까지만)")
        shows_only_korean_names(self, nt.cards(nt.from_report(every)))
        shows_only_korean_names(self, nt.notes(every)[0])

    def test_every_confirmed_name_is_shown_up_to_all_eight_in_the_table_order(self):
        # 독립 검증 낮음 1·V23: 확정 유형이 8종까지 가능하니 이름을 4개에서 자르지 않는다. 건강·경험 알림의 걸린 말 한도(`MAX_SHOWN`)는 그대로다.
        self.assertEqual((sf.MAX_SHOWN, sf.MAX_SHOWN_BENEFITS, len(sf.BENEFIT_KINDS)), (4, 8, 8))
        for count in range(1, 9):
            given = tuple(reversed(POSITIVE[:count]))                      # 받은 순서가 뒤집혀 있어도
            expected = LABELS[:count]                                      # 이름은 표(`BENEFIT_KINDS`)의 순서로 전부 나온다
            with self.subTest(count=count):
                report = sf.check_text(["예시 주제"], benefits=given)
                self.assertEqual(report.benefits, POSITIVE[:count])
                self.assertEqual(report.findings[0].groups, expected)
                self.assertEqual(nt.from_report(report)[0].details, expected)
                self.assertTrue(nt.notes(report)[0].endswith("(걸린 말: " + ", ".join(expected) + ")"), nt.notes(report)[0])
        two_campaigns = (campaign(campaign_id="c-a", benefits=POSITIVE[:4]), campaign(campaign_id="c-b", benefits=POSITIVE[4:]))
        report = sf.assess(ts.make(seed_id="seed-gpu"), campaigns=two_campaigns)
        self.assertEqual((report.benefits, report.findings[0].groups), (POSITIVE, LABELS), "여러 협찬 정보가 모여 8종이 되어도 이름이 다 나온다")
        self.assertEqual(len(sf.check_text(["영양제로 피로가 완전히 회복됩니다"]).findings[0].matched), 4, "건강 알림의 걸린 말은 여전히 최대 4개다")

    def test_the_labels_that_changed_from_the_old_five_are_the_operators_names(self):
        report = sf.check_text(["예시 주제"], benefits=("payment", "affiliate", "reward"))                    # 옛 이름으로 넣어도 새 표시 이름이 나온다
        self.assertEqual(nt.from_report(report)[0].details, ("원고료", "제휴 수수료", "조건부 보상"))
        for old_label in ("금전 제공(원고료 등)", "제휴·수수료", "조건부 보상(후기 이벤트 등)"):
            self.assertNotIn(old_label, nt.cards(nt.from_report(report)))
            self.assertNotIn(old_label, nt.notes(report)[0])

    def test_no_sentence_the_module_can_say_about_a_campaign_leaks_a_value_name(self):
        seen = 0
        for benefits in (("NONE",), POSITIVE, ("OTHER",), ("goods",)):
            for status in ("confirmed", "proposed"):
                try:
                    item = campaign(benefits=benefits, status=status)
                except AppError as error:
                    shows_only_korean_names(self, error.slots["항목"])
                    shows_only_korean_names(self, error.rendered().message)
                    seen += 1
                    continue
                for text in (PLAIN_TEXT, SUSPECT_TEXT):
                    report = sf.assess(ts.make(seed_id="seed-gpu", topic=text), campaigns=(item,))
                    for notice in nt.from_report(report):
                        shows_only_korean_names(self, notice.text())
                        seen += 1
                    for line in nt.notes(report):
                        shows_only_korean_names(self, line)
                        seen += 1
        self.assertGreater(seen, 10)


class SuspicionTablesUntouchedTest(unittest.TestCase):                                                          # I8
    def test_the_five_groups_that_suspect_a_sponsor_from_words_are_still_the_old_names_and_not_the_interest_types(self):
        # 이번 묶음은 낱말 탐지 표(`concepts.py`)를 건드리지 않았다 — 추정(낱말)과 사람이 확인한 값(유형)은 다른 표다(D-102).
        self.assertEqual(cn.SPONSOR_GROUPS, ("goods", "service", "payment", "affiliate", "reward"))
        self.assertEqual(set(cn.SPONSOR_STRONG_KO), {"goods", "service", "payment", "affiliate", "reward", "general"})
        self.assertEqual(set(cn.SPONSOR_WEAK_KO), {"goods", "service", "payment", "affiliate", "reward"})
        self.assertEqual((sum(len(words) for words in cn.SPONSOR_STRONG_KO.values()), sum(len(words) for words in cn.SPONSOR_WEAK_KO.values())), (54, 30))
        self.assertEqual({key: cn.GROUP_KO[key] for key in cn.SPONSOR_GROUPS}, {"goods": "현물 제공", "service": "서비스 제공", "payment": "금전 제공", "affiliate": "제휴·수수료", "reward": "조건부 보상"})
        self.assertTrue(set(cn.SPONSOR_GROUPS).isdisjoint(sf.INTEREST_TYPES))
        self.assertEqual(sf.check_text(["제휴 링크를 통한 수수료 수령"]).findings[0].groups, ("제휴·수수료",), "추정 알림은 개념군 이름 그대로다 — 확정 알림의 표시 이름('제휴 수수료')과 일부러 다르다")


class GenerateTest(unittest.TestCase):                                                                          # I9
    def run_with(self, campaigns, keyword="예시 협찬 안내"):
        seed = sd.Seed(seed_id="s1", major="가전", minor="소형가전", keyword=keyword, seed_type="general", scope="common", registered_on="2026-05-01", state="active")
        return gn.generate(A, [seed], [], (), "2026-11-10", target=100, campaigns=campaigns)

    def test_a_none_campaign_turns_the_suspicion_of_a_whole_run_into_the_conflict_line(self):
        found = self.run_with([sf.Campaign(campaign_id="camp-none", benefits=("NONE",), status="confirmed", seed_id="s1")])
        self.assertTrue(found.candidates)
        for candidate in found.candidates:
            self.assertEqual(candidate.safety_flags, ("sponsor_disclosure",), candidate.topic)
            self.assertTrue(candidate.selection_reasons[1].startswith("경제적 이해관계 확인 필요 — 저장된 상태는 ‘없음’인데 "), candidate.selection_reasons[1])
            self.assertEqual(sum(1 for reason in candidate.selection_reasons if reason.startswith("경제적 이해관계")), 1, "추정 줄과 충돌 줄이 같이 나오지 않는다")
            for reason in candidate.selection_reasons:
                shows_only_korean_names(self, reason)

    def test_without_a_stored_state_the_same_run_gives_the_suspicion_line_as_before(self):
        found = self.run_with([])
        self.assertTrue(found.candidates)
        for candidate in found.candidates:
            self.assertEqual(candidate.safety_flags, ("sponsor_disclosure",))
            self.assertTrue(candidate.selection_reasons[1].startswith("경제적 이해관계 확인 필요 — 제품·서비스 제공 또는 제휴 보상이 있는지"), candidate.selection_reasons[1])

    def test_all_eight_confirmed_kinds_fit_in_the_selection_reason_line_of_every_candidate(self):
        # 이름을 전부 보이게 해도 선정 이유 한 줄(한도 `notice.MAX_LINE`)이 후보 규칙에 걸려 후보가 버려지지 않는다.
        found = self.run_with([sf.Campaign(campaign_id="camp-all", benefits=sf.BENEFIT_KINDS, status="confirmed", seed_id="s1")], keyword="예시 로봇청소기")
        self.assertTrue(found.candidates)
        self.assertEqual([row for row in found.dropped if row.reason == "invalid"], [])
        for candidate in found.candidates:
            line = candidate.selection_reasons[1]
            self.assertTrue(line.endswith("(걸린 말: " + ", ".join(LABELS) + ")"), line)
            self.assertLessEqual(len(line), nt.MAX_LINE)
            shows_only_korean_names(self, line)

    def test_a_confirmed_kind_in_a_run_shows_the_operators_name(self):
        found = self.run_with([sf.Campaign(campaign_id="camp-kind", benefits=("VISIT_OR_MEAL_PROVIDED", "DISCOUNT_OR_COUPON"), status="confirmed", seed_id="s1")], keyword="예시 로봇청소기")
        self.assertTrue(found.candidates)
        for candidate in found.candidates:
            self.assertEqual(candidate.safety_flags, ("sponsor_disclosure",))
            self.assertIn("(걸린 말: 방문·식사 제공, 할인·쿠폰)", candidate.selection_reasons[1])
            shows_only_korean_names(self, candidate.selection_reasons[1])


class DecisionRecordTest(unittest.TestCase):
    """결정 기록(`docs/DECISIONS.md`)에 이 묶음의 세 결정이 있고 각각 운영자 승인(날짜·시각)과 변경 등급 T1 이 적혀 있다 — 결정 **번호가 아니라 내용**으로 찾는다(병합 때 번호가 더 큰 쪽으로 밀려도 시험은 그대로다)."""

    def decision_rows(self):
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        return [line for line in text.splitlines() if line.startswith("| D-")]

    def only_row(self, needle):
        found = [row for row in self.decision_rows() if needle in row]
        self.assertEqual(len(found), 1, needle)
        return found[0]

    def test_each_of_the_three_decisions_exists_once_with_the_approval_and_the_grade(self):
        for needle in ("경제적 이해관계 유형을 `UNKNOWN` + 9종으로 늘린다", "계절형 Seed 는 180일 '쉬게 할까요' 제안에서 제외", "'전략 원문 확인 전' 표기를 사실대로 바로잡는다"):
            with self.subTest(needle=needle):
                row = self.only_row(needle)
                self.assertTrue(row.startswith("| D-1"), row[:12])
                self.assertIn("운영자 승인 2026-11-06 ~16:20(전략 원문 대조 결정 — 이해관계 UNKNOWN+9종·계절 Seed 제외·표기 정정)", row)
                self.assertIn("T1", row)

    def test_the_interest_decision_names_every_value_the_legacy_table_the_conflict_alert_and_the_no_migration_fact(self):
        row = self.only_row("경제적 이해관계 유형을 `UNKNOWN` + 9종으로 늘린다")
        for needle in (*sf.INTEREST_TYPES, *(label for _value, label in OPERATOR_TABLE), "LEGACY_BENEFIT_NAMES", "ECONOMIC_CONFLICT", "본문 낱말 탐지는 저장된 상태를 바꾸지 않고", "확정 유형이 우선", "Migration",
                       "`concepts.SPONSOR_GROUPS`", "원고료", "제휴 수수료", "조건부 보상"):
            with self.subTest(needle=needle):
                self.assertIn(needle, row)

    def test_the_seasonal_and_the_wording_decisions_name_what_they_leave_for_later(self):
        seasonal = self.only_row("계절형 Seed 는 180일 '쉬게 할까요' 제안에서 제외")
        for needle in ("P3b-1", "seasonal_priority_state", "prepare_from", "publish_until", "idle_proposals", "usable_seeds"):
            with self.subTest(needle=needle):
                self.assertIn(needle, seasonal)
        wording_row = self.only_row("'전략 원문 확인 전' 표기를 사실대로 바로잡는다")
        for needle in ("7단계", "작성 기반 부족", "88조합 중 0", "규칙 기반 초안 본문 생성기", "BASE_OUTLINES", "한 글자도 바뀌지 않았다", "TOPIC_ENGINE_PLAN.md"):
            with self.subTest(needle=needle):
                self.assertIn(needle, wording_row)

    def test_the_plan_no_longer_carries_the_stale_sentences_this_bundle_corrected(self):
        plan = (ts.ROOT / "docs" / "TOPIC_ENGINE_PLAN.md").read_text(encoding="utf-8")
        for stale in ("전략 원문은 이 PC 에 없어 P1~P2b 숫자와 표는 요약·계획과만 대조했고", "(순서·소제목 표는 초기값 — 전략 원문 확인 전)", "표는 모두 초기값(전략 원문 확인 전) | T1 |"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, plan)
        self.assertIn("전략 원문은 2026-11-06 에 다시 받아 비교자 2명이 독립 대조했다", plan)
        self.assertIn("원문 §16 은 성격이 다른 7단계", plan)


if __name__ == "__main__":
    unittest.main()
