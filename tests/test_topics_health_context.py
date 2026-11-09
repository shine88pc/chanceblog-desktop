"""건강 판정 문맥 구분 시험(WP-B 2차, D-130~D-135) — 운영자 2026-11-06 ~19:55 채팅이 확인 요청 002 의 기본값을 바꾼 세 결정:
  ① 영양제 + '바로·즉시' — 일괄 C 가 아니라 문맥에 따라(단순 시간·순서 = A / 증상·효능 주장·복용 허용 질문 = B / 즉각적 효능·치료·완치·보장 = C)
  ② 증상 + 즉각적 효과 표현 = C (즉시·바로·완전히·확실히·무조건 + 줄인다·없앤다·해소한다·교정한다·치료한다) — 단, '바로 확인한다' 같은 행동 순서 수식은 C 가 아니다
  ③ 질환 + 단정·보장 = C(효과 동사가 생략돼도) — 질환만 있는 글은 B
**원칙: 단어가 존재한다는 이유만으로 판정하지 않고 단정 표현이 '행동 순서'를 꾸미는지 '효과 결과'를 꾸미는지 가른다.** 운영자 예시 16개는 이 시험의 고정 기준이다.

지키는 것:
  X1) 운영자 예시 16개가 정확히 그 단계다(단계·알림 코드·중지·근거 점수 감점) X2) 기존 16개 판정 표본이 달라지지 않았다
  X3) 단정 낱말의 **범위** — 행동 순서를 꾸미는 말 12개 이상은 단정이 아니고 효과 결과를 꾸미는 말 12개 이상은 단정이다. 같은 낱말이 어순만 바뀌어도 판정이 갈리고(`scope_of`), 조사·띄어쓰기·붙여 쓰기·어미 변형·
      부정·의문·의무·경고 낱말·마스크와 기존 규칙(D-58)이 그대로 맞물린다. 효과 서술어의 대상이 건강 낱말이 아니면 단정이 아니다
  X4) 표(영양제·처방약 하위 종류·복용 질문·범위 낱말·결과/행동 서술어 조각)의 모양 X5) 영양제 세 단계와 복용 허용 질문 X6) 처방약 하위 종류와 단정 규칙 X7) 질환 + 단정·질환 단독
  X8) **옛 중지 바닥** — 옛 코드(`d5dcb8c`)가 중지하던 글은 영양제 + 행동 순서 `바로·즉시` 하나를 빼고 그대로 중지이고(차분), 새로 중지가 된 글은 전부 운영자 결정 ②③ 때문이다
  X9) 평범한 생활 문장 66개(앞 독립 검증자의 표본) — 단계가 달라진 것은 운영자 결정 ② 꼴 둘뿐이고 과탐이 없다 X10) 알림에 보이는 낱말·문장 X11) 영어 X12) 문서(D-130~D-135·CHANGELOG)
네트워크·파일·실제 시계·난수(고정 시드 말고는) 없이 돈다. 시험 글은 모두 지어낸 일반 문장이다.
"""
import itertools
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_health_expected as he  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import concepts as cn  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import notice as nt  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402

GENERAL, MARK, EVIDENCE, STOP = "general", "mark", "evidence", "stop"
G_, A_, B_, C_ = GENERAL, MARK, EVIDENCE, STOP
SHORT = {"G": GENERAL, "A": MARK, "B": EVIDENCE, "C": STOP}
SHORT_TO_STAGE = SHORT
RANK = {GENERAL: 0, MARK: 1, EVIDENCE: 2, STOP: 3}
CODE = {MARK: "HEALTH_TOPIC", EVIDENCE: "HEALTH_EFFECT", STOP: "HEALTH_STOP"}
BASE_EXPLAINER = gn.EVIDENCE_BASE["explainer"]            # 70


def stage(text):
    return sf.check_text([text]).stage


def health_codes(text):
    return [finding.code for finding in sf.check_text([text]).findings if finding.flag == "health_check"]


def evidence(text, extra=None):
    """글 하나를 후보의 주제로 놓고 안전 표시 → 근거 점수까지 — `generate._finish` 가 하는 계산과 같은 호출이다."""
    made = ts.make(topic=text, content_type="explainer", primary_keyword="예시 키워드")
    report = sf.assess(made)
    return gn._evidence(made, report.flags, extra or gn._Extra(), report.stage)


def scope(text, word):
    """글에서 단정 낱말 `word` 가 무엇을 꾸미는지 — `concepts.scope_of` 를 글 하나에 직접 부른다."""
    joined, starts = cn.compact_marked([cn.fold(text)])
    target = cn.compact(cn.fold(word))
    return cn.scope_of(joined, starts, joined.index(target) + len(target))


# 운영자 예시 16개(2026-11-06 ~19:55 채팅) — (글, 단계, 근거 점수(근거 없음), 알림 코드). 시험의 고정 기준이다.
OPERATOR_EXAMPLES = (
    ("영양제 바로 알기", A_, 70, "HEALTH_TOPIC"),
    ("영양제를 식후 바로 먹어도 될까", B_, 50, "HEALTH_EFFECT"),
    ("피로 회복 영양제를 비교하는 기준", B_, 50, "HEALTH_EFFECT"),
    ("이 영양제는 피로를 즉시 없애줍니다", C_, 50, "HEALTH_STOP"),
    ("영양제로 불면이 바로 치료됩니다", C_, 50, "HEALTH_STOP"),
    ("수면제 바로 끊어도 될까", C_, 50, "HEALTH_STOP"),
    ("피로할 때 작업환경을 점검하는 방법", A_, 70, "HEALTH_TOPIC"),
    ("자세가 불편할 때 책상 높이를 확인하는 기준", A_, 70, "HEALTH_TOPIC"),
    ("피로를 즉시 줄이는 방법", C_, 50, "HEALTH_STOP"),
    ("자세를 바로 교정하는 책상 설정", C_, 50, "HEALTH_STOP"),
    ("통증을 완전히 없애는 의자 선택법", C_, 50, "HEALTH_STOP"),
    ("당뇨 관련 공식 표시사항 확인하기", B_, 50, "HEALTH_EFFECT"),
    ("당뇨 환자의 식품 라벨 확인 기준", B_, 50, "HEALTH_EFFECT"),
    ("당뇨 100% 보장", C_, 50, "HEALTH_STOP"),
    ("당뇨를 무조건 개선하는 식품", C_, 50, "HEALTH_STOP"),
    ("암 완치 보장", C_, 50, "HEALTH_STOP"),
)
# 기존 16개 판정 표본(운영자용 표본 파일의 표) — (글, 단계, 근거 점수). 이번 묶음 전후로 같다.
OLD_SAMPLES = (
    ("잠들기 전 화면 사용을 줄이는 생활 습관", G_, 70), ("잠이 잘 오지 않을 때 수면 환경을 점검하는 방법", A_, 70), ("불면을 확실히 치료하는 방법", C_, 50), ("영양제로 피로가 완전히 회복됩니다", C_, 50),
    ("암 예방 100% 보장", C_, 50), ("암 수술 100% 안전", C_, 50), ("수술 후유증 100% 해결", C_, 50), ("암 예방 식단", B_, 50), ("암 수술 후 식단", B_, 50), ("수술 후유증 관리", B_, 50),
    ("치료제 추천", A_, 70), ("자세교정기 구매 기준", A_, 70), ("불면증 극복하는 수면 루틴", B_, 50), ("유산균 장 건강 관리 요령", B_, 50), ("영양제 복용 시간 알림 앱 만들기", A_, 70),
    ("스트레스를 확실히 줄이는 시간 관리법", C_, 50),
)
# 옛 단계표(D-105, `d5dcb8c`) 64칸 — 옛 중지 바닥의 기준이다. 한 줄 = (S, D, P, M), 네 칸 = (E, A) = 0·0 / 0·1 / 1·0 / 1·1.
OLD_ROWS = {
    (0, 0, 0, 0): (G_, G_, G_, G_), (1, 0, 0, 0): (A_, A_, A_, C_), (0, 1, 0, 0): (A_, A_, B_, C_), (1, 1, 0, 0): (A_, A_, B_, C_), (0, 0, 1, 0): (A_, C_, B_, C_), (1, 0, 1, 0): (B_, C_, B_, C_),
    (0, 1, 1, 0): (B_, C_, B_, C_), (1, 1, 1, 0): (B_, C_, B_, C_), (0, 0, 0, 1): (A_, C_, B_, C_), (1, 0, 0, 1): (B_, C_, B_, C_), (0, 1, 0, 1): (B_, C_, B_, C_), (1, 1, 0, 1): (B_, C_, B_, C_),
    (0, 0, 1, 1): (C_, C_, C_, C_), (1, 0, 1, 1): (C_, C_, C_, C_), (0, 1, 1, 1): (C_, C_, C_, C_), (1, 1, 1, 1): (C_, C_, C_, C_),
}
OLD_MATRIX = {(*targets, effect, assertion): value for targets, values in OLD_ROWS.items() for (effect, assertion), value in zip(((0, 0), (0, 1), (1, 0), (1, 1)), values, strict=True)}
# 행동 순서를 꾸미는 단정 낱말 문장 — 건강 대상이 증상일 때(행동 순서면 단정이 아니라 표시만) 단계 A
ACTION_ORDER_MARK = (
    "피로할 때 바로 확인하는 체크리스트", "통증이 있을 때 즉시 병원 예약하는 방법", "자세 알림을 바로 설정하는 방법", "수면 기록을 즉시 저장하는 앱 만들기", "불면일 때 바로 점검할 것",
    "스트레스 일기를 당장 정리하는 요령", "체중 변화를 바로 기록하는 습관", "집중력 타이머를 즉시 시작하는 방법", "두통 증상을 바로 메모하는 법", "피로 점검표를 확실히 작성하는 법",
    "수면 시간을 무조건 확보하는 일정", "체중 기록을 완전히 자동화하는 방법", "스트레스 점검표를 즉각 확인하는 순서", "불안 일기를 바로 읽어 보는 법",
)
# 같은 낱말이 효과 결과를 꾸미는 문장 — 증상(또는 질환)이 그 대상이면 단정 위험 C
EFFECT_RESULT_STOP = (
    "피로를 즉시 줄이는 방법", "자세를 바로 교정하는 책상 설정", "통증을 완전히 없애는 의자 선택법", "두통을 즉각 완화하는 습관", "불면을 확실히 해소하는 루틴", "체중을 무조건 감량하는 식단",
    "스트레스를 당장 풀어주는 방법", "붓기를 순식간에 빼는 마사지", "집중력을 즉시 높이는 환경", "번아웃을 바로 극복하는 방법", "불안을 단숨에 낮추는 호흡법", "거북목을 바로 교정하는 스트레칭",
    "속쓰림이 즉시 사라지는 식단", "당뇨를 무조건 개선하는 식품", "혈압을 즉시 낮추는 식단", "피로를 아침에 즉시 줄이는 방법", "즉시 피로를 없애는 방법",
)
# 평범한 생활 문장 66개(앞 독립 검증자의 표본) — (글, 옛 단계 `d5dcb8c`, 새 단계). 단계가 달라진 둘은 운영자 결정 ②(증상 + 즉시·바로 + 효과 결과) 꼴이다.
ORDINARY_66 = (
    ("잠자리에 들기 전 십 분 정리 루틴 만들기", "G", "G"), ("수면 시간을 기록하는 간단한 표 만들기", "A", "A"), ("숙면을 위한 침실 온도와 조명 정하는 법", "A", "A"), ("주말 늦잠 때문에 흐트러진 생활 리듬 되돌리기", "G", "G"),
    ("스트레스 받는 날 책상 위부터 치우는 습관", "A", "A"), ("업무 스트레스를 줄이는 회의 정리 요령", "A", "A"), ("스트레스 없이 시작하는 월요일 체크리스트", "A", "A"), ("스트레스 테스트용 서버 부하 설정", "G", "G"),
    ("체중 변화를 그래프로 그리는 엑셀 서식", "A", "A"), ("체중 기록 앱 기능 비교", "A", "A"), ("체중계 보관 위치 정하기", "G", "G"), ("다이어트 도시락 일주일 계획표", "A", "A"),
    ("다이어트 앱 비교 정리", "A", "A"), ("바른 자세로 앉는 모니터 높이 맞추기", "A", "A"), ("자세 알림 앱 설정 방법", "A", "A"), ("자세히 보기 버튼 눌렀을 때 화면 구성", "G", "G"),
    ("집중력이 흐트러질 때 쓰는 타이머 설정", "A", "A"), ("집중력 높이는 작업 공간 정리", "A", "A"), ("집중력 기르는 독서 습관", "A", "A"), ("피로가 쌓인 날 저녁 일정 줄이기", "A", "A"),
    ("피로 없이 쓰는 눈 편한 화면 설정", "A", "A"), ("알림 피로를 줄이는 스마트폰 설정", "G", "G"), ("피로도 낮은 앱 화면 구성하기", "G", "G"), ("아침 컨디션 체크 메모 쓰는 법", "A", "A"),
    ("컨디션 좋은 날 일정 몰아 넣기", "A", "A"), ("활력 있는 아침을 만드는 루틴 설계", "A", "A"), ("소화가 편한 저녁 식사 시간 정하기", "A", "A"), ("속 편한 아침 메뉴 일주일 계획", "A", "A"),
    ("장 건강 식단 일지 양식", "A", "A"), ("기억력 메모 습관 만들기", "A", "A"), ("불안한 마음을 적는 저녁 일기 습관", "A", "A"), ("두통 기록 노트 양식", "A", "A"),
    ("번아웃 예방 업무 루틴 만들기", "A", "A"), ("번아웃 신호 체크리스트", "A", "A"), ("무기력한 날 작게 시작하는 요령", "A", "A"), ("통증 일지 쓰는 법", "A", "A"),
    ("허리가 불편한 날 쓰는 의자 높이 설정", "G", "G"), ("어깨 결림이 있을 때 작업 자세 점검", "A", "A"), ("거북목 방지 스트레칭 알림 앱", "A", "A"), ("목 자세를 바로잡는 책상 배치", "A", "A"),
    ("여드름 흉터 가리는 메이크업 도구 정리", "A", "A"), ("피부 트러블 기록 앱", "A", "A"), ("안구건조 걱정 없는 모니터 밝기 설정", "A", "A"), ("입냄새 걱정 줄이는 양치 루틴", "A", "A"),
    ("붓기 빠지는 아침 스트레칭", "A", "A"), ("겨울철 불면 대비 침실 보온 설정", "A", "A"), ("불면의 밤 읽기 좋은 책", "A", "A"), ("변비 걱정 없는 여행 짐 챙기기", "A", "A"),
    ("비타민 보관 케이스 정리", "A", "A"), ("영양제 복용 시간 알림 앱 만들기", "A", "A"), ("유산균 보관 냉장 위치", "A", "A"), ("건강기능식품 구입 영수증 보관", "A", "A"),
    ("운동 기록 앱 비교", "G", "G"), ("러닝 기록 정리 엑셀", "G", "G"), ("걷기 목표 설정 앱", "G", "G"), ("식단 사진 정리 폴더 이름 규칙", "G", "G"),
    ("업무 효율을 확실히 높이는 시간 관리법", "G", "G"), ("생산성을 완전히 바꾸는 아침 루틴", "G", "G"), ("집중력을 확실히 높이는 작업 환경", "C", "C"), ("스트레스를 확실히 줄이는 시간 관리법", "C", "C"),
    ("수면 시간을 무조건 확보하는 일정 짜기", "A", "A"), ("체중 기록을 완전히 자동화하는 방법", "A", "A"), ("피로를 즉시 줄이는 작업 환경", "A", "C"), ("번아웃을 확실히 예방하는 루틴", "C", "C"),
    ("자세를 바로 교정하는 책상 설정", "A", "C"), ("집중력을 되찾는 업무 환경 만들기", "A", "A"),
)


class OperatorExamplesContextTest(unittest.TestCase):                                                           # X1·X2
    def test_the_sixteen_operator_examples_land_exactly_where_the_operator_put_them(self):
        self.assertEqual(len(OPERATOR_EXAMPLES), 16)
        for text, expected, points, code in OPERATOR_EXAMPLES:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual(report.stage, expected)
                self.assertEqual(health_codes(text), [code])
                self.assertEqual(report.stop, expected == STOP, "자동 초안 중지는 C 단계일 때만")
                self.assertEqual(evidence(text), points, "근거 점수 — A 는 감점 0, B·C 는 근거가 없으면 −20")

    def test_a_cut_only_follows_the_claims_that_need_evidence(self):
        for text, expected, _points, _code in OPERATOR_EXAMPLES:
            with self.subTest(text=text):
                if expected in (EVIDENCE, STOP):
                    self.assertEqual(evidence(text, gn._Extra(official=1)), gn.EVIDENCE_OFFICIAL, "공식 출처 1개면 감점이 없다")
                    self.assertEqual(evidence(text, gn._Extra(independent=2)), gn.EVIDENCE_INDEPENDENT)
                else:
                    self.assertEqual(evidence(text), BASE_EXPLAINER)

    def test_the_earlier_sixteen_samples_are_not_changed_by_this_work(self):
        self.assertEqual(len(OLD_SAMPLES), 16)
        for text, expected, points in OLD_SAMPLES:
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)
                self.assertEqual(evidence(text), points)

    def test_a_candidate_with_the_same_text_gets_the_same_stage_through_assess(self):
        for text, expected, _points, _code in OPERATOR_EXAMPLES:
            with self.subTest(text=text):
                self.assertEqual(sf.assess(ts.make(topic=text, content_type="explainer", primary_keyword="예시 키워드")).stage, expected)


class ScopeBoundaryTest(unittest.TestCase):                                                                     # X3
    def test_an_assertion_word_that_modifies_an_action_order_is_not_an_assertion(self):
        self.assertGreaterEqual(len(ACTION_ORDER_MARK), 12)
        for text in ACTION_ORDER_MARK:
            with self.subTest(text=text):
                self.assertEqual(stage(text), MARK, "행동 순서를 꾸미는 단정 낱말 — 증상만 있으니 표시만")
                self.assertEqual(cn.health_signals([text]).concept_key()[5], 0, "단정(A)으로 세지 않는다")
        for text in ("바로 확인한다", "바로 알기", "무조건 기록하는 습관", "즉시 알림을 받는 앱", "확실히 저장하는 방법", "완전히 자동화하는 설정", "당장 시작하는 체크리스트"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), GENERAL, "건강 낱말이 없으면 행동 순서든 아니든 일반")

    def test_an_assertion_word_that_modifies_an_effect_result_is_an_assertion_when_a_health_word_is_its_object(self):
        self.assertGreaterEqual(len(EFFECT_RESULT_STOP), 12)
        for text in EFFECT_RESULT_STOP:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.stop, health_codes(text)), (STOP, True, ["HEALTH_STOP"]))
                key = cn.health_signals([text]).concept_key()
                self.assertEqual((key[4], key[5]), (1, 1), "효과(E)와 단정(A)이 함께 켜진다")

    def test_the_same_words_in_another_order_are_judged_by_what_the_assertion_word_modifies(self):
        for result, action in (("피로를 즉시 줄이는 방법", "피로를 줄이는 방법을 즉시 확인하기"), ("자세를 바로 교정하는 책상 설정", "자세 교정 책상 설정을 바로 확인하기"),
                               ("통증을 즉각 완화하는 습관", "통증 완화 습관을 즉각 기록하기"), ("두통을 바로 해소하는 법", "두통 해소 방법을 바로 저장하는 법")):
            with self.subTest(result=result):
                self.assertEqual((stage(result), stage(action)), (STOP, MARK), "낱말은 같고 꾸미는 것이 다르다")

    def test_scope_of_reads_the_word_right_after_and_skips_one_object_word(self):
        for text, word, expected in (("피로를 즉시 줄이는 방법", "즉시", "effect"), ("바로 확인하기", "바로", "action"), ("완전히 회복되는 습관", "완전", "effect"), ("확실한 효과 정리", "확실", "effect"),
                                     ("무조건적으로 기록하는 습관", "무조건", "action"), ("즉시 피로를 없애는 법", "즉시", "effect"), ("즉시 요란하게 줄이는 법", "즉시", "none"), ("바로 이거 하기", "바로", "none"),
                                     ("바로 효과를 보는 법", "바로", "effect"), ("즉시 알림을 받는 앱", "즉시", "action"), ("당장 먹어도 될까", "당장", "dose"), ("순식간에 사라지는 증상", "순식간", "effect"),
                                     ("피로를즉시줄이는방법", "즉시", "effect"), ("바로먹는법", "바로", "dose"), ("즉시", "즉시", "none"), ("단숨에 낮추는 방법", "단숨에", "effect")):
            with self.subTest(text=text):
                self.assertEqual(scope(text, word), expected)

    def test_two_words_after_are_the_limit_so_a_far_predicate_is_not_attached(self):
        self.assertEqual(scope("즉시 피로를 조용히 줄이는 방법", "즉시"), "none", "건너뛰는 낱말은 목적어 꼴과 부사 표의 낱말뿐 — 표에 없는 부사가 끼면 읽지 않는다")
        self.assertEqual(scope("바로 시도하는 방법을 소개하며 피로를 줄이는 법", "바로"), "action")
        self.assertEqual(scope("즉시 이 방법으로 피로를 줄이는 법", "즉시"), "none", "건너뛰기는 최대 두 낱말(셋째 낱말이 서술어여야 한다)")
        self.assertEqual(scope("즉시 피로를 크게 줄이는 법", "즉시"), "effect", "목적어 + 부사 — 두 낱말을 건너뛴다")
        self.assertEqual(scope("바로 같이 먹어도 될까", "바로"), "dose", "복용·중단 행동은 범위 dose(D-137) — 영양제는 행동 순서와 같게, 처방약은 C 로 읽는다")
        self.assertEqual(scope("바로 더 크게 줄이는 법", "바로"), "effect")

    def test_the_object_of_an_effect_predicate_has_to_be_a_health_word_near_the_assertion_word(self):
        for text in ("다이어트 앱 로딩 속도를 바로 줄이는 방법", "스트레스 관리 앱 UI를 즉시 개선하는 방법", "체중 기록 서버 응답 시간을 즉시 줄이는 설정", "피로도 알림 개수를 바로 줄이는 방법"):
            with self.subTest(text=text):
                self.assertNotEqual(stage(text), STOP, "효과 서술어의 대상이 건강 낱말이 아니라 소프트웨어다")
        self.assertEqual(stage("다이어트 앱 로딩 속도를 바로 줄이는 방법"), MARK)
        for text in ("피로를 즉시 줄이는 앱", "스트레스를 바로 풀어주는 앱"):
            self.assertEqual(stage(text), STOP, "대상이 건강 낱말이면 앱 이야기여도 효과 단정 꼴이다 — 알려진 한계(보고서 ⑧)")

    def test_inserting_words_the_scope_reading_needs_untouched_can_lower_the_stage_as_documented(self):
        # 글 쪽 단조성의 새 예외(D-134 ②): 꾸밈을 읽는 규칙은 단정 낱말 바로 뒤와 앞 세 낱말 안만 보므로 사이에 낱말이 끼면 단정이 안 읽힌다 — 기존 예외(경고 낱말·부정·의문·의무꼴)와 별개다
        for before, after in (("피로를 즉시 줄이는 방법", "피로를 즉시 요란하게 줄이는 방법"), ("피로를 즉시 줄이는 방법", "피로를 아침 점심 저녁 즉시 줄이는 방법"), ("영양제 바로 먹는 법 100% 보장", "영양제 바로 먹는 법")):
            with self.subTest(before=before):
                self.assertGreater(RANK[stage(before)], RANK[stage(after)])
        self.assertEqual((stage("피로를 즉시 줄이는 방법"), stage("피로를 즉시 요란하게 줄이는 방법"), stage("피로를 아침 점심 저녁 즉시 줄이는 방법")), (STOP, MARK, MARK))

    def test_attached_endings_and_particles_and_spacing_do_not_hide_the_assertion(self):
        for text in ("피로를즉시줄이는방법", "피로를 즉시줄이는 방법", "피로를 즉시 줄이는방법", "피로가 즉시 해소됩니다", "피로는 즉시 풀리는 방법", "피로를 즉시 줄여 주는 방법", "피로를 즉시 줄인다는 말", "피로를 즉시 줄입니다"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
        for text in ("피로를 즉 시 줄이는 방법", "피 로를 즉시 줄이는 방법"):
            with self.subTest(text=text):
                self.assertNotEqual(stage(text), STOP, "글자를 띄운 우회는 읽지 않는다(D-58, 기존 규칙 그대로)")

    def test_a_negation_a_question_an_obligation_a_warning_word_and_a_mask_keep_switching_the_assertion_off(self):
        for text in ("피로를 즉시 줄이지 않는 법", "피로를 즉시 줄일까", "피로를 즉시 줄이지는 않습니다"):
            with self.subTest(text=text):
                self.assertNotEqual(stage(text), STOP, "부정·의문 꼬리가 단정을 끈다(기존 규칙)")
        self.assertEqual(stage("피로를 즉시 줄인다는 광고에 속지 않는 법"), MARK, "경고 낱말이 단정을 끈다(기존 규칙)")
        self.assertEqual(stage("반드시 알아야 할 피로 회복법"), MARK, "의무 꼴 ‘반드시 ~해야’ 는 단정이 아니다")
        self.assertEqual(stage("피로를 반드시 개선해야 합니다"), MARK, "효과 서술어를 꾸며도 의무 꼴이면 단정이 아니다")
        self.assertEqual(stage("당뇨 환자는 반드시 치료해야 합니다"), EVIDENCE, "질환 + 의무 꼴은 질환 단독이다")
        for text in ("바로가기 아이콘 정리하는 요령", "바로잡는 습관", "완전 정복 가이드", "알림 피로를 즉시 줄이는 설정", "피로도를 바로 줄이는 화면 구성"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), GENERAL, "마스크 낱말은 신호가 아니다(기존 규칙)")

    def test_an_assertion_word_inside_another_word_or_hidden_by_invisible_characters_follows_the_old_word_rules(self):
        self.assertEqual(stage("피로를 즉" + chr(0x200B) + "시 줄이는 방법"), STOP, "보이지 않는 글자는 지우고 읽는다(기존 규칙)")
        self.assertEqual(stage("피로를 ＳＵＢ 즉시 줄이는 방법"), STOP, "NFKC 정규화")
        self.assertEqual(scope("바로미터를 확인하는 법", "바로"), "action")
        self.assertEqual(stage("바로미터 점검 습관"), GENERAL, "바로미터는 마스크")

    def test_every_scoped_word_is_found_in_every_form_and_kept_apart_from_the_always_assertion_words(self):
        soft, strong = cn.ASSERT_SCOPED_KO["soft"], cn.ASSERT_SCOPED_KO["strong"]
        for word in soft + strong:
            with self.subTest(word=word):
                adverb = word + "히" if word in strong else word
                self.assertEqual(stage(f"피로를 {adverb} 줄이는 방법"), STOP)
                self.assertEqual(stage(f"피로를 {adverb} 확인하는 방법"), MARK, "행동 순서 — 증상만 있고 효과가 없으니 표시만(strong 낱말도 효과 낱말이 없으면 옛 규칙으로도 표시만)")
        for word in ("100%", "100퍼센트", "백퍼센트", "보장", "보증", "장담", "단언", "틀림없", "즉효", "완치"):
            with self.subTest(always=word):
                self.assertEqual(stage(f"당뇨 {word}"), STOP, "범위와 상관없이 항상 단정")


class TablesTest(unittest.TestCase):                                                                            # X4
    def test_the_two_subkinds_are_words_of_the_product_table_and_do_not_overlap(self):
        product = set(cn.HEALTH_PRODUCT_KO + cn.HEALTH_PRODUCT_EN)
        for name, words in (("영양제", cn.HEALTH_SUPPLEMENT_KO + cn.HEALTH_SUPPLEMENT_EN), ("처방약", cn.HEALTH_MEDICINE_KO + cn.HEALTH_MEDICINE_EN)):
            self.assertTrue(set(words) <= product, name)
        self.assertEqual(cn.SUPPLEMENT_SET & cn.MEDICINE_SET, frozenset())
        self.assertEqual((len(cn.HEALTH_SUPPLEMENT_KO), len(cn.HEALTH_SUPPLEMENT_EN), len(cn.HEALTH_MEDICINE_KO), len(cn.HEALTH_MEDICINE_EN)), (13, 9, 16, 5))          # 의도적 갱신(D-137): 처방약 낱말 아홉 → 열여섯(혈압약·당뇨약·인슐린·항암제·피임약·항응고제·스타틴)
        for word in ("의료기기", "자세교정기", "한약", "보약", "운동 처방", "식이요법", "민간요법", "자연치유", "다이어트 약"):
            self.assertIn(word, cn.HEALTH_PRODUCT_KO)
            self.assertNotIn(word, cn.SUPPLEMENT_SET | cn.MEDICINE_SET, "그 밖의 제품 — 영양제 예외가 없다")
        self.assertEqual(len(cn.HEALTH_PRODUCT_KO), 45)
        for word in ("해열제", "스테로이드", "처방약", "항우울제"):
            self.assertIn(word, cn.HEALTH_PRODUCT_KO)
            self.assertIn(word, cn.HEALTH_MEDICINE_KO)

    def test_the_scoped_words_split_the_assertion_tables_and_the_rest_are_always_assertions(self):
        soft, strong = cn.ASSERT_SCOPED_KO["soft"], cn.ASSERT_SCOPED_KO["strong"]
        self.assertEqual((soft, strong), (("즉시", "즉각", "바로", "단숨에", "순식간", "당장"), ("확실", "완전", "무조건", "반드시")))
        self.assertTrue(set(soft) <= set(cn.HEALTH_ASSERT_SOFT_KO) and set(strong) <= set(cn.HEALTH_ASSERT_KO))
        self.assertEqual(set(cn.HEALTH_ASSERT_SOFT_KO) - set(soft), set(cn.ASSERT_ALWAYS_SOFT_KO))
        self.assertEqual(set(cn.HEALTH_ASSERT_KO) - set(strong), {"100퍼센트", "백퍼센트", "백프로", "틀림없", "장담", "보장", "보증", "단언"})

    def test_the_scope_tables_are_clean(self):
        for name in ("HEALTH_RESULT_SCOPE_KO", "HEALTH_ACTION_SCOPE_KO", "SCOPE_PARTICLES_KO", "SCOPE_ADVERB_SUFFIX_KO", "SCOPE_SKIP_WORDS_KO", "HEALTH_ASK_STEMS_KO", "HEALTH_ASK_TAILS_KO"):
            words = getattr(cn, name)
            with self.subTest(table=name):
                self.assertEqual(len(words), len(set(words)), "중복 없음")
                self.assertTrue(all(cn.compact(cn.fold(word)) == word for word in words), "정규화해도 그대로인 낱말(띄어쓰기·기호 없음)")
        result, action = cn.HEALTH_RESULT_SCOPE_KO, cn.HEALTH_ACTION_SCOPE_KO
        self.assertEqual((len(result), len(action), len(cn.HEALTH_ASK_STEMS_KO), len(cn.HEALTH_ASK_TAILS_KO), len(cn.SCOPE_SKIP_WORDS_KO)), (368, 234, 11, 19, 23))          # 의도적 갱신(D-299, WP-B5 수정 라운드): 결과 338 → 368(명사 `탈출` × 어미 13 + 효과 동사 17) · 의도적 갱신(D-136): 결과 322 → 338·행동 218 → 234·복용 질문 어간 6 → 11·꼬리 8 → 19
        self.assertEqual([word for word in cn.SCOPE_SKIP_WORDS_KO if cn.Tables.result_start.match(word) or cn.Tables.action_start.match(word)], [], "건너뛰는 부사는 서술어 조각이 아니다")
        self.assertEqual(len(cn._RESULT_NOUNS_KO) * len(cn._RESULT_ENDINGS_KO), 221)
        self.assertEqual([(x, y) for x in result for y in action if x.startswith(y) or y.startswith(x)], [], "결과와 행동 조각이 서로의 앞부분이 되지 않는다")
        for noun in ("높이", "교정기", "예방접종", "치료 시기", "강화도", "올리브", "도움말"):
            for text in (noun, noun.replace(" ", "")):
                joined, starts = cn.compact_marked([cn.fold("즉시 " + text)])
                self.assertNotEqual(cn.scope_of(joined, starts, 2), "effect", f"{noun} — 명사로도 쓰이는 낱말은 서술어로 읽지 않는다")

    def test_every_result_and_action_stem_is_read_as_its_kind(self):
        for stem in cn.HEALTH_RESULT_SCOPE_KO:
            joined, starts = cn.compact_marked([cn.fold(f"즉시 {stem}")])
            self.assertEqual(cn.scope_of(joined, starts, 2), "effect", stem)
        for stem in cn.HEALTH_ACTION_SCOPE_KO:
            joined, starts = cn.compact_marked([cn.fold(f"바로 {stem}")])
            self.assertEqual(cn.scope_of(joined, starts, 2), "dose" if stem in cn.HEALTH_DOSE_SCOPE_KO else "action", stem)          # 의도적 갱신(D-137): 복용·중단 어간은 범위 dose

    def test_the_effect_and_medical_tables_are_read_as_result_stems_with_an_ending_and_the_bare_nouns_are_the_listed_ones(self):
        # 효과·의료 낱말 표 40개 가운데 **낱말만(어미 없이)** 서술어로 읽히지 않는 것은 아래 8개뿐이다 — 명사·어간으로도 쓰여(`높이`·`도움`·`수술`) 서술어 꼴(어미 포함)만 결과 조각 표에 두었기 때문이다. 결과 명사 13개(회복·개선·완화·예방·교정·감량·증진·향상·해소·강화·극복·치료·완치)는 의도적 갱신(D-299, WP-B5 수정 라운드)으로 **글이 거기서 끝날 때**(`통증 즉시 완화`) 낱말만으로도 읽는다
        bare_unread = ("도움", "높이", "올리", "키우", "처방", "시술", "수술", "투약")
        not_read = [entry for entry in cn.HEALTH_EFFECT_KO + cn.HEALTH_MEDICAL_KO if scope(f"즉시 {entry}", "즉시") != "effect"]
        self.assertEqual(sorted(not_read), sorted(bare_unread))
        self.assertEqual(len(cn.HEALTH_EFFECT_KO + cn.HEALTH_MEDICAL_KO) - len(not_read), 32, "나머지 32개는 낱말만으로도 서술어로 읽는다 — 그 가운데 13개는 결과 명사가 글 끝에 올 때(D-299)")
        for noun in ("회복", "개선", "완화", "예방", "교정", "감량", "증진", "향상", "해소", "강화", "극복", "치료", "완치"):
            for ending in ("하는", "되는", "합니다", "됩니다", "해요"):
                self.assertEqual(scope(f"즉시 {noun}{ending}", "즉시"), "effect", f"{noun}{ending}")
        for form in ("도움이 되는", "도움을 주는", "높이는", "올리는", "키우는"):
            self.assertEqual(scope(f"즉시 {form}", "즉시"), "effect", form)
        for noun in ("처방", "시술", "수술", "투약"):
            self.assertNotEqual(scope(f"즉시 {noun}받는", "즉시"), "effect", f"{noun} — 의료 행위를 받는 일은 결과 서술어가 아니다")


class SupplementContextTest(unittest.TestCase):                                                                 # X5
    ORDER_ONLY = ("영양제 바로 알기", "영양제 바로 먹는 법", "유산균 바로 고르는 기준", "비타민 즉시 확인하는 방법", "건강기능식품 바로 구매하는 법", "홍삼 당장 시작하는 습관", "오메가3 즉시 기록하는 앱",
                  "콜라겐 바로 알아보는 순서", "루테인 즉각 정리하는 방법", "프로바이오틱스 바로 챙기는 습관", "밀크씨슬 즉시 저장하는 앱", "크레아틴 바로 시작하는 법", "보충제 바로 사용하는 방법", "건강식품 즉시 비교하는 기준")

    def test_a_supplement_with_a_plain_order_word_is_only_marked_and_costs_nothing(self):
        for text in self.ORDER_ONLY:
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.stop, health_codes(text)), (MARK, False, ["HEALTH_TOPIC"]))
                self.assertEqual(evidence(text), BASE_EXPLAINER)

    def test_a_supplement_with_a_claim_or_a_taking_question_needs_evidence(self):
        for text in ("영양제를 식후 바로 먹어도 될까", "비타민 즉시 먹어도 될까", "영양제 안 먹어도 될까", "유산균 복용해도 되나요", "홍삼 섭취해도 괜찮을까", "영양제 먹어도 되는 시간 정리", "영양제 끊어도 될지 고민", "피로 회복 영양제를 비교하는 기준",
                     "영양제 효능 정리", "영양제 피로 개선"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), health_codes(text)), (EVIDENCE, ["HEALTH_EFFECT"]))
                self.assertEqual(evidence(text), BASE_EXPLAINER - 20)

    def test_a_supplement_with_an_instant_effect_a_cure_or_a_guarantee_stops_the_draft(self):
        for text in ("이 영양제는 피로를 즉시 없애줍니다", "영양제로 불면이 바로 치료됩니다", "영양제 바로 효과를 보는 법", "영양제로 통증이 즉각 사라집니다", "영양제 바로 먹는 방법 100% 보장", "영양제 즉시 효과", "영양제로 당장 완치됩니다"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), sf.check_text([text]).stop), (STOP, True))

    def test_a_software_or_life_sentence_about_supplements_is_not_a_question_and_stays_a_mark(self):
        for text in ("영양제 복용 시간 알림 앱 만들기", "영양제 섭취 기록 앱 설계", "영양제 먹는 순서 정리표", "영양제 구매 영수증 보관", "비타민 보관 케이스 정리", "영양제 복용 알림 시간 설정"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), evidence(text)), (MARK, BASE_EXPLAINER))
                self.assertEqual(cn.health_signals([text]).ask, (), "허용 질문 꼴이 아니다")

    def test_the_taking_question_counts_as_an_effect_only_beside_a_health_product(self):
        for text in ("먹어도 될까", "커피 마셔도 되나요", "오늘 일찍 끊어도 될지 고민", "앱 알림을 꺼도 되나요"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), GENERAL, "건강 제품이 없으면 질문 꼴만으로 판정하지 않는다")
        for text in ("수술 후 음식 먹어도 될까", "치료 중에 마셔도 되나요", "시술 뒤 끊어도 될지 고민"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), MARK, "의료 효능어만 있고 건강 제품이 없으면 질문 꼴이 효과로 세어지지 않는다(표시만)")
        self.assertEqual(cn.health_signals(["영양제 먹어도 될까"]).ask, ("먹어도",))
        self.assertEqual(cn.health_signals(["영양제 먹어도 될까"]).concept_key(), (0, 0, 1, 0, 1, 0))
        for stem in cn.HEALTH_ASK_STEMS_KO:
            for tail in cn.HEALTH_ASK_TAILS_KO:
                with self.subTest(stem=stem, tail=tail):
                    self.assertEqual(stage(f"영양제 {stem} {tail}"), EVIDENCE)

    def test_the_exception_needs_every_soft_word_to_modify_an_action_and_only_supplements_among_the_products(self):
        self.assertEqual(stage("영양제 바로 알기"), MARK)
        self.assertEqual(stage("영양제 바로 알기 즉시 효과"), STOP, "한 자리라도 효과 꾸밈이면 예외가 아니다")
        self.assertEqual(stage("영양제 즉시 흡수되는 시간"), STOP, "꾸밈을 모르면(none) 옛 규칙 그대로 — 영양제 예외는 행동 순서가 분명할 때만")
        self.assertEqual(stage("영양제 바로 요란하게 먹는 법"), STOP, "사이에 표에 없는 낱말이 끼어 꾸밈을 못 읽으면 예외가 아니다")
        self.assertEqual(stage("영양제 바로 알기 바로 요란하게 먹는 법"), STOP, "같은 낱말이 두 번 나와 한 자리라도 꾸밈을 모르면 예외가 아니다")
        self.assertEqual(stage("영양제 바로 알기 바로 확인하기"), MARK, "두 자리 모두 행동 서술어면 예외다")
        self.assertEqual(stage("영양제 바로 같이 먹는 법"), MARK, "자주 끼는 부사(같이·함께·꼭 …)는 건너뛰고 읽는다")
        for text in ("영양제 즉시 할인 쿠폰", "영양제 바로 메모하는 방법", "비타민 즉시 적립 이벤트", "홍삼 바로 활용하는 요리", "유산균 즉시 발송 업체 비교"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), MARK, "효능 주장이 아닌 시간·행동 표현(할인·적립·메모·활용·발송)도 영양제 + 단순 시간·순서다")
        self.assertEqual(stage("영양제 구독을 바로 해지하는 방법"), MARK, "목적어 꼴을 건너뛰고 행동 서술어(해지)를 읽는다")
        for text in ("영양제와 수면제 바로 같이 먹어도 될까", "영양제 한약 바로 먹는 법", "영양제 의료기기 바로 알기", "영양제 치료 바로 알기"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP, "영양제 말고 다른 제품·의료 낱말이 있으면 옛 규칙 그대로")
        signals = cn.health_signals(["영양제 바로 알기"])
        self.assertEqual((signals.relaxed_soft(), signals.supplements(), signals.medicines()), (frozenset({"바로"}), ("영양제",), ()))
        self.assertEqual(cn.health_signals(["수면제 바로 알기"]).relaxed_soft(), frozenset({"바로"}), "의도적 갱신(D-137 A-8): 처방약 + 행동 순서(알기)도 푼다 — 복용·중단은 풀지 않는다")
        self.assertEqual(cn.health_signals(["수면제 바로 끊어도 될까"]).relaxed_soft(), frozenset(), "복용·중단·용량 행동은 처방약에서 풀지 않는다")


class MedicineContextTest(unittest.TestCase):                                                                   # X6
    def test_a_medicine_word_alone_is_marked_as_before(self):
        for word in cn.HEALTH_MEDICINE_KO:
            with self.subTest(word=word):
                self.assertEqual(stage(f"예시 {word} 글"), EVIDENCE if word in ("혈압약", "당뇨약", "항암제") else MARK, "처방약 단독은 지금대로(변경 없음 — 운영자가 안 정했다). 이름 속에 질환 낱말(혈압·당뇨·암)이 든 셋은 옛 코드가 질환 단독(B)으로 읽었으므로 B 를 지킨다(D-137 — 약화 금지)")
        for text in ("수면제 없이 잠드는 방법", "진통제 복용 시간 기록 앱", "처방약 보관함 정리", "해열제 보관 위치", "항우울제 이름 정리표", "스테로이드 연고 구매 영수증"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), evidence(text)), (MARK, BASE_EXPLAINER))

    def test_a_medicine_with_an_instant_or_strong_word_stops_even_when_it_modifies_an_action(self):
        for text in ("수면제 바로 끊어도 될까", "해열제 바로 먹어도 될까", "스테로이드 즉시 끊어도 될까", "진통제 당장 먹는 법", "항생제 무조건 먹는 법", "항생제 즉시 복용하는 순서", "수면제 바로 줄이는 방법", "항우울제 즉시 중단하는 법", "혈압약 무조건 끊어도 되나요"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), sf.check_text([text]).stop), (STOP, True), "복용·중단·용량 변경을 말하는 행동은 C 유지(D-137 A-8)")
        for text in ("수면제 바로 알기", "항우울제 바로 알기", "처방약 즉시 확인하기", "의약품 확실한 선택법", "처방약 영수증 즉시 정리하는 방법", "처방약 무조건 챙겨 두는 서류", "진통제 바로 보관하는 방법"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), sf.check_text([text]).stop), (MARK, False), "의도적 갱신(D-137 A-8): 처방약 + 복용이 아닌 행동 순서(알기·확인·정리·챙기기·보관) = A")
        self.assertEqual(cn.health_signals(["수면제 바로 끊어도 될까"]).counted_assert(), ("바로",))

    def test_a_medicine_taking_question_alone_needs_evidence(self):
        for text in ("수면제 먹어도 될까", "항생제 끊어도 되나요", "해열제 먹어도 괜찮을까"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), evidence(text)), (EVIDENCE, BASE_EXPLAINER - 20))


class DiseaseContextTest(unittest.TestCase):                                                                    # X7
    def test_a_disease_word_alone_needs_evidence_and_a_disease_with_a_strong_assertion_stops(self):
        for text in ("당뇨 관련 공식 표시사항 확인하기", "당뇨 환자의 식품 라벨 확인 기준", "고혈압 수치 기록 앱", "탈모 샴푸 성분표 읽는 법", "치매 예방 퍼즐 후기", "당뇨 환자 식단 일지 양식"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), health_codes(text), evidence(text)), (EVIDENCE, ["HEALTH_EFFECT"], BASE_EXPLAINER - 20))
        for text in ("당뇨 100% 보장", "고혈압 완치 보장", "탈모 백퍼센트 장담", "비염 틀림없이 해결", "당뇨를 무조건 개선하는 식품", "혈압을 즉시 낮추는 식단", "암 완치 보장", "당뇨 보증"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), sf.check_text([text]).stop), (STOP, True))

    def test_a_cure_word_beside_a_disease_is_a_strong_assertion_even_without_an_effect_verb(self):
        for text in ("당뇨 완치 방법", "고혈압 완치법", "유방암 완치 가능성", "치매 완치", "탈모 완치 비법", "고혈압 완치됩니다", "당뇨 완치 효과", "암 완치 가능", "유방암 완치 보장"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), sf.check_text([text]).stop), (STOP, True))
                self.assertIn("완치", cn.health_signals([text]).counted_assert())
        for text in ("고혈압 완치 사례", "유방암 완치 후 식단", "당뇨 완치율 통계 확인하기", "당뇨 완치 판정 기준", "당뇨 완치 통계", "고혈압 완치 기준 정리", "당뇨 완치 여부 확인"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), sf.check_text([text]).stop, cn.health_signals([text]).counted_assert()), (EVIDENCE, False, ()), "의도적 갱신(D-136 A-9): 완치 후·율·판정·사례·기준·통계·여부는 단정이 아니다 — 질환 단독 B")
        self.assertEqual(stage("불면 완치 방법"), EVIDENCE, "증상 + 완치 는 옛대로(증상 + 의료 효능어) 근거 확인 필요 — 질환 곁의 완치만 강한 단정")
        self.assertEqual(stage("완치 후기 모음"), MARK, "질환 없는 의료 효능어 단독은 옛대로 표시만")
        self.assertEqual(stage("영양제 완치"), STOP, "제품 + 의료 효능어는 옛대로 단정 위험")

    def test_an_assertion_word_that_modifies_an_action_beside_a_disease_does_not_stop(self):
        for text in ("당뇨 검사 결과를 바로 확인하는 방법", "당뇨 식단을 즉시 시작하는 방법", "고혈압 수치를 무조건 기록하는 습관", "혈당 기록을 완전히 자동화하는 방법", "당뇨 환자 식단 일지를 당장 정리하는 법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), EVIDENCE, "질환 단독 = 근거 확인 필요, 행동 순서를 꾸미는 단정은 세지 않는다")
        self.assertEqual(stage("당뇨 무조건 알아야 할 것"), EVIDENCE, "의무 꼴·행동 서술어 꾸밈")
        self.assertEqual(cn.health_signals(["당뇨 무조건 성공"]).counted_assert(), ("무조건",), "꾸밈을 모르는 ‘무조건’ 이 질환 곁에 있으면 단정")
        self.assertEqual(stage("당뇨 즉시 성공"), EVIDENCE, "‘즉시’ 는 효과 결과를 꾸밀 때만 단정")

    def test_insurance_words_around_a_disease_are_not_a_guarantee(self):
        for text in ("당뇨 보험 보장 한도 비교", "당뇨 보험 보장 금액 정리", "당뇨 환자 보험 보장 범위", "당뇨 보험 보장 기간 확인", "당뇨 보험 보장 항목 비교", "당뇨 보험 보장 내용 비교", "당뇨 보험 보장 혜택 정리"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), EVIDENCE, "`보험 보장` 은 마스크 — 질환 단독(B)")
        self.assertEqual(stage("당뇨 보험 100% 보장"), STOP)
        self.assertIn("보험 보장", cn.HEALTH_MASKS_KO)
        for entry in ("보장 한도", "보장 금액", "보장 기간", "보장 항목", "보장 혜택"):
            self.assertNotIn(entry, cn.HEALTH_MASKS_KO, "의도적 변경(D-138): 보험 낱말 없이 쓰인 `보장 …` 마스크는 옛 중지를 풀어 지웠다 — 질환 + 보장 은 C")
        self.assertEqual(len(cn.HEALTH_MASKS_KO), 64)          # 의도적 갱신(D-307, WP-B5 3차 수정): 66 → 64(한 낱말 마스크 `한눈에`·`첫눈에` 를 지움 — 마스크가 글을 갈라 기준이 중지로 읽던 글을 낮췄다) · 의도적 갱신(D-298, WP-B5 수정 라운드): 56 → 66(낱말 처음에서만 읽는 증상 낱말 덕에 필요 없어진 마스크 다섯을 지우고 띄어 쓴 일상 구절 열다섯을 더함) · 의도적 갱신(D-140): 33 + 보험 보장 1(D-138) + 기기 암 6(D-136) + ARM·게임·장비 문맥 암 8(D-140) · 의도적 갱신(D-291, WP-B5): + 새 증상 낱말이 일상어에서 걸리지 않게 8(머리 감기·착 감기·빨리감기·되감기·경기침체·이명박·건설사·한눈에)
        for text in ("체중 감량 보장 기간 3개월", "다이어트 효과 보장 기간 안내", "피로 회복 효과 보장 기간", "통증 완화 보장 기간 안내", "치료비 보장 한도 비교", "영양제 효과 보장 혜택 받는 법", "당뇨 보장 혜택 정리"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP, "옛 중지는 보험 마스크가 풀지 않는다(둘째 검증 높음 1) — `건강기능식품 보장 기간 확인하기` 같은 중립 문장이 C 로 남는 것은 알려진 한계(DEFERRED)")


class LegacyStopFloorTest(unittest.TestCase):                                                                   # X8
    def test_the_floor_table_is_exactly_the_stop_cells_of_the_old_matrix(self):
        self.assertEqual(sf.LEGACY_STOP_KEYS, frozenset(key for key, value in OLD_MATRIX.items() if value == STOP))
        self.assertEqual(len(sf.LEGACY_STOP_KEYS), 35)

    def test_only_the_two_disease_rows_changed_in_the_matrix_and_only_upward(self):
        changed = {key for key in sf.HEALTH_MATRIX if sf.HEALTH_MATRIX[key] != OLD_MATRIX[key]}
        self.assertEqual(changed, {(0, 1, 0, 0, 0, 0), (0, 1, 0, 0, 0, 1), (1, 1, 0, 0, 0, 0), (1, 1, 0, 0, 0, 1)})
        for key in changed:
            self.assertGreater(RANK[sf.HEALTH_MATRIX[key]], RANK[OLD_MATRIX[key]])
        self.assertEqual([sf.HEALTH_MATRIX[key] for key in sorted(changed)], [EVIDENCE, STOP, EVIDENCE, STOP])

    def test_a_text_the_old_rule_stopped_stays_stopped_even_when_the_new_rule_does_not_count_its_assertion(self):
        for text in ("치료 확실한 선택법", "한약 확실한 선택법", "피로 줄이려고 무조건 기록하는 습관", "한약 바로 먹는 법", "영양제 즉시 흡수되는 시간", "체중 감량 기록을 완전히 자동화하는 방법",
                     "다이어트 약 바로 알기", "의료기기 즉시 사용하는 방법", "자세교정기 확실히 착용하는 법"):
            with self.subTest(text=text):
                signals = cn.health_signals([text])
                self.assertEqual(sf.check_text([text]).stage, STOP)
                self.assertLess(RANK[sf.HEALTH_MATRIX[signals.concept_key()]], RANK[STOP], "새 열쇠만으로는 중지가 아니다 — 옛 바닥이 지킨다")
                self.assertIn(signals.floor_key(), sf.LEGACY_STOP_KEYS)

    def test_the_only_exception_is_a_supplement_with_a_soft_word_that_modifies_an_action(self):
        for text, expected in (("영양제 바로 알기", MARK), ("영양제를 식후 바로 먹어도 될까", EVIDENCE), ("유산균 바로 고르는 기준", MARK), ("당뇨 환자가 영양제 바로 먹기", EVIDENCE)):
            with self.subTest(text=text):
                signals = cn.health_signals([text])
                self.assertEqual(stage(text), expected)
                self.assertNotIn(signals.floor_key(), sf.LEGACY_STOP_KEYS)
                self.assertIn(signals.legacy_concept_key(), sf.LEGACY_STOP_KEYS, "옛 코드는 중지였다")

    def test_the_legacy_key_is_what_the_old_code_computed(self):
        for text, key in (("영양제 바로 알기", (0, 0, 1, 0, 0, 1)), ("피로를 즉시 줄이는 방법", (1, 0, 0, 0, 1, 0)), ("당뇨 100% 보장", (0, 1, 0, 0, 0, 1)), ("치료제 추천", (0, 0, 1, 0, 0, 0))):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).legacy_concept_key(), key)
        self.assertEqual(cn.health_signals(["치료제 추천"]).key(), (0, 1, 1, 0), "key() 는 한 글자도 안 바뀌었다")

    def test_old_stops_are_not_eased_across_the_word_tables_and_random_texts_and_every_new_stop_has_a_reason(self):
        original = ("SYMPTOM", "DISEASE", "EFFECT", "MEDICAL", "PRODUCT", "ASSERT", "ASSERT_EFFECT", "ASSERT_SOFT", "MASKS", "WARNING")
        words = [entry.rstrip("*") for name in original for suffix in ("_KO", "_EN") for entry in getattr(cn, f"HEALTH_{name}{suffix}")]
        tails = ("", " 100% 보장", " 바로 알기", " 즉시 효과", " 무조건 개선", " 확실히 확인", " 즉시 먹어도 될까", " immediately")
        rng = random.Random(20261106)
        filler = ("예시", "방법", "정리", "비교", "추천", "습관", "guide", "notes", "와", "를", "앱", "기록", "설정")
        texts = [f"예시 {word}{tail} 글" for word in words for tail in tails]
        texts += [" ".join(rng.choice(words if rng.random() < 0.6 else filler) + rng.choice(("", "", "를", "이", "은")) for _ in range(rng.randint(1, 6))) for _ in range(800)]
        eased = {"old_stop": 0, "relaxed": 0}
        reasons = {"②": 0, "③": 0, "처방약 낱말": 0}
        for text in texts:
            signals = cn.health_signals([text])
            old = OLD_MATRIX[signals.legacy_concept_key()]
            new = sf.check_text([text]).stage
            if old == STOP:
                eased["old_stop"] += 1
                if new != STOP:
                    eased["relaxed"] += 1
                    self.assertTrue(signals.relaxed_words(), f"결정으로 푼 곳(영양제·처방약 + 행동 순서, 치료 + 바로·즉시 + 행동 순서) 밖에서 옛 중지가 풀렸다: {text!r}")          # 의도적 갱신(D-137·D-138)
            elif new == STOP:
                key = signals.concept_key()
                if (key[1] and key[5] and not (key[2] or key[4])) or (key[1] and "완치" in signals.counted_assert()):
                    reasons["③"] += 1                                      # 질환 + 강한 단정(효과 서술어·제품 없이, 또는 질환 곁의 완치) — 표의 새 칸과 질환 + 완치
                elif any(entry in cn.NEW_PRODUCT_SET for entry in signals.product) and (key[5] or key[3]):
                    reasons["처방약 낱말"] += 1                            # 옛 제품 표에 없던 처방약 낱말(해열제·혈압약 …) + 단정 또는 의료 효능어 — 옛 코드는 제품이 아니라 몰랐고 옛 제품 낱말(`수면제 처방`)처럼 제품 + 단정·의료 효능어 = C 가 된다(의도적 — D-133·D-137, 의도적 갱신 D-140)
                else:
                    self.assertTrue(key[4] and key[5] and any(where == "effect" for _entry, _kind, where in signals.scoped), f"새 중지의 이유가 ② 도 ③ 도 아니다: {text!r} {key}")
                    reasons["②"] += 1                                      # 효과 결과를 꾸미는 단정 낱말 + 건강 대상
            self.assertGreaterEqual(RANK[new], RANK[old] if old != STOP else 0)
        self.assertGreater(eased["old_stop"], 800)
        self.assertGreater(eased["relaxed"], 20, "예외 경로가 실제로 지나간다")
        self.assertGreater(reasons["②"], 20)
        self.assertGreater(reasons["③"], 20)

    def test_no_text_with_a_stage_goes_down_to_general_and_other_flags_are_untouched(self):
        for text in ("영양제 바로 알기", "당뇨 100% 보장", "수면제 바로 끊어도 될까"):
            report = sf.check_text([text])
            self.assertEqual(report.flags, ("health_check",))
            self.assertEqual([finding.flag for finding in report.findings], ["health_check"])


class OrdinarySentencesTest(unittest.TestCase):                                                                 # X9
    def test_the_sixty_six_ordinary_sentences_changed_only_where_the_operator_decision_two_says(self):
        self.assertEqual(len(ORDINARY_66), 66)
        self.assertEqual(len({text for text, _old, _new in ORDINARY_66}), 66)
        changed = []
        for text, old, new in ORDINARY_66:
            with self.subTest(text=text):
                self.assertEqual(stage(text), SHORT[new])
            if old != new:
                changed.append((text, old, new))
        self.assertEqual(changed, [("피로를 즉시 줄이는 작업 환경", "A", "C"), ("자세를 바로 교정하는 책상 설정", "A", "C")], "의도: 운영자 결정 ②(증상 + 즉시·바로 + 효과 결과 서술어). 그 밖의 새 B·C 는 과탐이다")

    def test_an_ordinary_sentence_is_never_b_and_the_old_c_ones_are_exactly_the_three_the_operator_rule_names(self):
        counts = {name: sum(1 for _text, _old, new in ORDINARY_66 if new == name) for name in "GABC"}
        self.assertEqual(counts, {"G": 14, "A": 47, "B": 0, "C": 5})
        self.assertEqual([text for text, _old, new in ORDINARY_66 if new == "C"], ["집중력을 확실히 높이는 작업 환경", "스트레스를 확실히 줄이는 시간 관리법", "피로를 즉시 줄이는 작업 환경", "번아웃을 확실히 예방하는 루틴", "자세를 바로 교정하는 책상 설정"])

    def test_symptom_words_in_ordinary_frames_stay_a_mark_with_no_cut_and_no_stop(self):
        words = ("피로", "불면", "통증", "자세", "체중", "스트레스", "수면", "집중력")
        frames = ("{} 기록 앱 만들기", "{} 때문에 미루던 일정 정리하는 요령", "{} 체크 표 양식 공유", "주말에 {} 점검하는 시간 갖기", "{} 관련 앱 설정 가이드", "{} 알림을 바로 확인하는 화면", "{}을 즉시 기록하는 앱", "{} 일지를 무조건 저장하는 습관")
        for word, frame in itertools.product(words, frames):
            text = frame.format(word)
            with self.subTest(text=text):
                report = sf.check_text([text])
                self.assertEqual((report.stage, report.stop, health_codes(text), evidence(text)), (MARK, False, ["HEALTH_TOPIC"], BASE_EXPLAINER))


class NoticeContextTest(unittest.TestCase):                                                                     # X10
    def test_the_card_shows_only_the_assertion_words_that_were_counted(self):
        self.assertEqual(sf.check_text(["영양제 바로 알기"]).findings[0].matched, ("영양제",), "세지 않은 ‘바로’ 는 보이지 않는다")
        self.assertEqual(sf.check_text(["영양제를 식후 바로 먹어도 될까"]).findings[0].matched, ("영양제",))
        self.assertEqual(sf.check_text(["수면 시간을 무조건 확보하는 일정"]).findings[0].matched, ("수면",))
        finding = sf.check_text(["피로를 즉시 줄이는 방법"]).findings[0]
        self.assertEqual((finding.matched, finding.groups), (("피로", "줄이", "즉시"), ("증상·상태", "효과·결과", "단정·보장")))
        finding = sf.check_text(["당뇨 100% 보장"]).findings[0]
        self.assertEqual((finding.matched[0], finding.groups[0], finding.groups[-1]), ("당뇨", "증상·상태", "단정·보장"))

    def test_a_stop_that_only_the_old_floor_keeps_still_names_the_old_assertion_word(self):
        self.assertEqual(sf.check_text(["치료 확실한 선택법"]).findings[0].matched, ("치료", "확실"))          # 의도적 갱신(D-138): 옛 예 둘(영양제 확실한 선택법·치료 바로 시작하기)은 이제 푼 곳이라 남은 바닥 예로 바꾼다
        self.assertEqual(sf.check_text(["한약 바로 먹는 법"]).findings[0].matched, ("한약", "바로"))
        self.assertEqual(sf.check_text(["영양제 즉시 흡수되는 시간"]).findings[0].matched, ("영양제", "즉시"))
        self.assertEqual(sf.check_text(["영양제 치료 바로 알기"]).findings[0].matched, ("치료", "영양제"), "제품 + 의료 낱말은 표만으로 중지 — 예외로 뺀 ‘바로’ 는 보이지 않는다")

    def test_the_evidence_sentence_names_the_diseases_and_the_taking_questions_it_now_covers(self):
        message = nt.CATALOG["HEALTH_EFFECT"][2]
        for word in ("질환", "복용", "근거 확인", "도움"):
            self.assertIn(word, message)
        self.assertEqual(nt.leaks(message), ())
        for text in ("당뇨 환자의 식품 라벨 확인 기준", "영양제를 식후 바로 먹어도 될까"):
            self.assertEqual(health_codes(text), ["HEALTH_EFFECT"])
            notices = nt.from_report(sf.check_text([text]))
            self.assertEqual(nt.leaks(nt.cards(notices)), ())
            self.assertTrue(sf.notes(sf.check_text([text]))[0].startswith("건강 정보 확인 필요 — 질환이나 복용을"))

    def test_no_new_alert_code_and_the_four_health_codes_are_unchanged(self):
        self.assertEqual(len(nt.CODES), 30)
        self.assertEqual(nt.CODES[:4], ("HEALTH_TOPIC", "HEALTH_EFFECT", "HEALTH_CLAIM", "HEALTH_STOP"))
        self.assertEqual(dict(sf.HEALTH_STAGE_CODE), CODE)


class EnglishContextTest(unittest.TestCase):                                                                    # X11
    def test_english_follows_the_matrix_and_the_old_stop_floor(self):
        for text, expected in (("diabetes diet notes", EVIDENCE), ("diabetes guaranteed", STOP), ("cholesterol guaranteed", STOP), ("blood pressure monitor guide", GENERAL), ("how to relieve diabetes symptoms", EVIDENCE),
                               ("supplements immediately", STOP), ("take supplements immediately after meals", STOP), ("supplements guide for beginners", MARK), ("sleep tips for beginners", MARK)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)

    def test_an_english_light_word_is_an_assertion_when_an_effect_word_follows_it_in_three_words(self):
        self.assertEqual(cn.health_signals(["relieve fatigue instantly"]).scoped, (("instantly", "soft", "none"),), "효과 낱말이 낱말 **뒤** 세 낱말 안에 있을 때만 effect — 앞에 있으면 none")
        self.assertEqual(cn.health_signals(["instantly relieve fatigue"]).scoped, (("instantly", "soft", "effect"),))
        self.assertEqual(cn.health_signals(["instantly check your sleep log"]).scoped, (("instantly", "soft", "none"),))
        self.assertEqual(cn.health_signals(["not instantly relieve fatigue"]).scoped, (), "부정이 세 낱말 앞이면 지켜 준다(기존 규칙)")
        self.assertEqual(stage("instantly relieve fatigue"), STOP)
        self.assertEqual(stage("instantly check your sleep log"), MARK)


class ShapeContextTest(unittest.TestCase):                                                                      # X4·X12
    def test_the_signal_record_only_gained_two_fields_at_the_end_and_the_old_ones_are_untouched(self):
        self.assertEqual(cn.HealthSignals._fields[:10], ("symptom", "disease", "effect", "medical", "product", "assert_strong", "assert_effect", "assert_soft", "warned", "inside"))
        self.assertEqual(cn.HealthSignals._fields[10:], ("scoped", "cure", "ask", "legacy_inside", "quit", "stopping", "resolve"))          # 의도적 갱신(D-136·D-140): 질환 곁 완치 신호 `cure` 를 scoped 와 ask 사이에 두고, 옛 제품 표 기준 이름 속 조각 `legacy_inside` 를 끝에 더한다 · 의도적 갱신(D-294, WP-B5): 처방약 복용 중단 단정 `quit` 을 맨 끝에 더한다(기본값 `()` — 앞의 열 넷은 그대로) · 의도적 갱신(D-308, WP-B5 3차 수정): 처방약 낱말이 든 글의 복용 중단 표현 `stopping` 을 `resolve` 앞에 더한다(기본값 `()`)
        self.assertEqual(cn.HealthSignals._field_defaults["quit"], ())
        self.assertEqual(cn.HealthSignals._field_defaults["stopping"], ())
        self.assertEqual(cn.HealthSignals._field_defaults["resolve"], ())          # 의도적 갱신(D-298, WP-B5 수정 라운드): 늘 단정 낱말 곁 결과 서술어 `resolve` 를 끝에 더한다 — 이름 없이 만들던 호출은 그대로 돈다
        self.assertEqual(cn.HealthSignals._field_defaults["scoped"], ())
        signals = cn.health_signals(["피로를 즉시 줄이는 방법"])
        self.assertEqual(signals.assert_soft, ("즉시",), "원시 신호는 낱말이 있으면 그대로 나온다")
        self.assertEqual(signals.key(), (1, 1, 0, 0), "key() 는 옛 계산 그대로(범위를 보지 않는다)")
        for text in ("피로를 즉시 줄이는 방법", "영양제 바로 알기", "당뇨 100% 보장", "일반 업무 정리"):
            for entry, kind, where in cn.health_signals([text]).scoped:
                self.assertIn(kind, ("soft", "strong"))
                self.assertIn(where, ("effect", "action", "none"))
                self.assertTrue(entry in cn.ASSERT_SCOPED_KO[kind] or entry in cn.HEALTH_ASSERT_SOFT_EN)

    def test_the_flags_the_report_shape_and_the_score_items_are_unchanged(self):
        self.assertEqual(sf.SafetyReport._fields, ("flags", "findings", "health", "relationship", "opportunity", "benefits", "interests", "stage"))
        self.assertEqual(dict(gn.EVIDENCE_PENALTY), {"health_check": 20, "experience_claim": 10})
        made = ts.make(topic="영양제를 식후 바로 먹어도 될까", content_type="explainer", primary_keyword="예시 키워드")
        plain = ts.make(topic="예시 일정 정리하는 요령", content_type="explainer", primary_keyword="예시 키워드")
        self.assertEqual(evidence(made.topic), evidence(plain.topic) - 20)


class DocumentsContextTest(unittest.TestCase):                                                                  # X12
    def rows(self):
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        return {line.split(" | ")[0].lstrip("| "): line for line in text.splitlines() if line.startswith("| D-")}

    def test_the_decisions_d130_to_d135_exist_once_after_d106_and_say_what_they_decided(self):
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        found = [line.split(" | ")[0].lstrip("| ") for line in text.splitlines() if line.startswith("| D-")]
        rows = self.rows()
        needles = {
            "D-130": ("범위", "행동 순서", "효과 결과", "scope_of", "100%", "무조건", "즉시", "바닥", "LEGACY_STOP_KEYS", "초기값"),
            "D-131": ("영양제", "복용", "먹어도 될까", "HEALTH_ASK", "영양제 복용 시간 알림 앱 만들기"),
            "D-132": ("증상", "즉시 줄이는 방법", "자세를 바로 교정하는 책상 설정", "바로 확인한다", "건강 낱말"),
            "D-133": ("처방약", "수면제 바로 끊어도 될까", "해열제", "스테로이드", "처방약 단독"),
            "D-134": ("질환", "당뇨 100% 보장", "근거 확인 필요", "HEALTH_MATRIX", "단조", "보장 한도", "HEALTH_EFFECT"),
            "D-135": ("정정", "D-105", "D-106", "질환 단독", "영양제 바로"),
            "D-136": ("운영자 직접 기준", "HEALTH_ASSERT_FORMS_KO", "줄여 줍니다", "줄일 수 있습니다", "당뇨 환자가 무조건 피해야 할 음식", "암 관련 공식 정보 확인하기", "암호화 방식을 바로 바꾸는 방법", "VERIFIED", "위임 규칙 근거"),
            "D-137": ("혈압약", "인슐린 100% 안전", "수면제 바로 알기", "복용·중단", "치료 바로 시작하기", "즉효", "결정 ② 문면에 없는", "VERIFIED", "위임 규칙 근거"),
            "D-138": ("보험 보장", "보장 한도·금액·기간·항목·혜택", "완치율", "topics_health_expected", "옛 코드", "VERIFIED", "위임 규칙 근거"),
            "D-139": ("DEFERRED", "A-11", "A-12", "A-13", "A-15", "통풍", "74초", "340문장", "위임 규칙 근거"),
        }
        for number, words in needles.items():
            with self.subTest(decision=number):
                self.assertEqual(found.count(number), 1)
                self.assertGreater(found.index(number), found.index("D-106"))
                for word in words:
                    self.assertIn(word, rows[number])
        self.assertEqual([item for item in found if item.startswith("D-13") and len(item) == 5], list(needles), "세 자리 번호 D-130~D-139 가 이 묶음의 열 행이다(옛 D-13 은 따로 있다) — D-136~D-139 는 1라운드 수정의 몫(의도적 갱신)")
        for number in ("D-136", "D-137", "D-138", "D-139"):
            status = rows[number].rsplit(" | ", 1)[1]
            self.assertEqual([word for word in ("FIXING", "DECISION_REQUIRED", "DEFERRED", "VERIFIED", "CLOSED") if word in status], ["DEFERRED"] if number == "D-139" else ["VERIFIED"], "상태 낱말은 하나 — 의도적 갱신(병합 직전): 2라운드 독립 검증과 재확인이 확인한 D-136~D-138 은 FIXING → VERIFIED, 알려진 한계 D-139 는 DEFERRED(CLOSED 는 병합 뒤)")

    def test_the_rule_table_of_d130_is_in_the_decisions_document_after_the_decision_rows(self):
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("**D-130 범위 규칙표**"), 1)
        table = text.split("**D-130 범위 규칙표**", 1)[1]
        rows = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith("| 범위 낱말 종류")]
        self.assertEqual(len(rows), 8, "낱말 종류 × 꾸미는 말 여덟 줄")
        for needle in ("soft", "strong", "행동 서술어", "효과 결과 서술어", "처방약", "모름", "100퍼센트", "당뇨 무조건 성공", "수면제 바로 끊어도 될까"):
            self.assertIn(needle, table)
        self.assertGreater(text.index("**D-130 범위 규칙표**"), text.index("| D-135 |"))

    def test_the_changelog_has_one_entry_and_the_module_headers_name_the_new_rule(self):
        log = (ts.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(log.count("**건강 판정 문맥 구분**"), 1)
        entry = next(line for line in log.splitlines() if "**건강 판정 문맥 구분**" in line)
        for needle in ("D-130", "D-135", "행동 순서", "효과 결과", "영양제", "질환", "처방약", "옛 중지"):
            self.assertIn(needle, entry)
        for module in (cn, sf):
            header = Path(module.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
            self.assertIn("D-130", header)
            self.assertIn("행동 순서", header)


class OperatorDirectCriteriaTest(unittest.TestCase):                                                            # X13 — 운영자 직접 기준(2026-11-06 ~22:2x, D-136) 네 가지
    OBJECTS = ("피로를", "통증을", "불면을", "두통을", "근육통을")
    NOUNS = ("완화", "개선", "교정", "치료", "회복", "예방", "감량", "해소", "극복")

    def test_effect_verbs_are_checked_as_conjugated_phrases_beside_an_instant_word(self):
        # 기준 ①② — 줄인다·줄이는·줄일 수 있다·줄여 준다 …(띄어쓰기 변형 포함)과 없애·낮추·풀·완화·개선·교정·치료·회복·예방·감량 계열
        verbs = ("줄인다", "줄이는 방법", "줄일 수 있습니다", "줄일 수 있다", "줄여 줍니다", "줄여줍니다", "줄여 준다", "줄여요", "줄였다", "줄였습니다", "줄여 주는 앱", "없앤다", "없애는 법", "없앨 수 있습니다",
                 "없애 줍니다", "없애줍니다", "없애 준다", "낮출 수 있습니다", "낮춰 줍니다", "풀어 줍니다", "풀어줘요", "풀어줍니다")
        for obj in self.OBJECTS:
            for verb in verbs:
                for word in ("즉시", "바로"):
                    text = f"{obj} {word} {verb}"
                    with self.subTest(text=text):
                        self.assertEqual(stage(text), STOP)
            for noun in self.NOUNS:
                for tail in ("합니다", "한다", "하는"):
                    with self.subTest(obj=obj, noun=noun, tail=tail):
                        self.assertEqual(stage(f"{obj} 즉시 {noun}{tail}"), STOP)

    def test_declarative_forms_are_assertions_even_without_any_assertion_word(self):
        for obj in self.OBJECTS:
            for form in ("줄일 수 있습니다", "줄일 수 있다", "줄여 줍니다", "줄여줍니다", "줄여 준다", "줄일수있습니다", "줄일 수있습니다", "없앨 수 있습니다", "없애 줍니다", "낮춰 줍니다", "풀어 줍니다"):
                with self.subTest(text=f"{obj} {form}"):
                    self.assertEqual(stage(f"{obj} {form}"), STOP)
            for noun in self.NOUNS:
                for ending in ("할 수 있다", "할 수 있습니다", "해 줍니다", "해줍니다", "해 준다", "해줘요", "시켜 줍니다"):
                    with self.subTest(text=f"{obj} {noun}{ending}"):
                        self.assertEqual(stage(f"{obj} {noun}{ending}"), STOP)
        for text in ("피로를 줄여 줍니다", "피로를 줄여줍니다", "피로를 줄일 수 있습니다"):
            self.assertEqual((stage(text), sf.check_text([text]).stop), (STOP, True), "운영자 예시")
        for text, expected in (("피로를 줄일 수도 있다", MARK), ("피로를 줄이는 방법", MARK), ("피로를 줄인다", MARK), ("로딩 시간을 줄일 수 있습니다", GENERAL), ("광고 노출을 줄여 줍니다", GENERAL), ("비용을 줄여 줍니다", GENERAL), ("스트레스 앱 로딩 시간을 줄일 수 있습니다", MARK)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected, "어림 꼴(`줄일 수도 있다`)·부사 없는 평서·건강 대상이 아닌 줄임은 단정이 아니다")
        self.assertEqual(len(cn.HEALTH_ASSERT_FORMS_KO), 102)
        self.assertEqual(len(set(cn.HEALTH_ASSERT_FORMS_KO)), 102)
        self.assertTrue(all(cn.compact(cn.fold(entry)) == entry for entry in cn.HEALTH_ASSERT_FORMS_KO), "정규화해도 그대로(띄어쓰기 없는 꼴)")

    def test_a_disease_with_a_strong_word_on_a_caution_or_a_check_is_evidence_and_only_an_effect_claim_stops(self):
        # 기준 ③ — 생활상 주의·확인 표현은 B, 치료·완치·개선 효과를 강하게 단정할 때만 C
        for text in ("당뇨 환자가 무조건 피해야 할 음식", "당뇨 환자는 무조건 피해야 할 간식 목록", "고혈압 환자가 무조건 확인해야 할 수치", "당뇨 환자 무조건 지켜야 할 생활 수칙"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), sf.check_text([text]).stop), (EVIDENCE, False))
        for text in ("당뇨를 무조건 개선하는 식품", "당뇨 무조건 완치", "당뇨 무조건 낫는다", "당뇨 무조건 좋아지는 음식"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)

    def test_a_one_letter_disease_is_read_by_word_boundary_and_a_password_is_not_a_health_topic(self):
        # 기준 ④ — `암` 은 낱말 단독이거나 조사가 붙을 때만 질환(공식 정보 = B), 암호·암호화·암기·암벽·암시·암컷은 건강 판정 없음
        for text in ("암 관련 공식 정보 확인하기", "암 즉시 확인하는 방법", "암에 좋은 음식", "암의 종류"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), EVIDENCE)
        for text in ("암 100% 보장", "암을 무조건 이기는 식품", "암이 즉시 낫는 방법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
        for text in ("암호화 방식을 바로 바꾸는 방법", "암호 관리자를 바로 설치하는 방법", "암기 시간을 완전히 확보하는 공부법", "암벽 등반 장비를 즉시 점검하는 방법", "암시적 표현을 바로 찾는 법",
                     "암컷 고양이 돌보기", "모니터 암 높이 조절", "암호화폐 100% 보장", "암호화 100% 보장"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), health_codes(text)), (GENERAL, []), "건강 판정 없음")
        self.assertEqual(cn.HEALTH_DISEASE_BARE_KO, ("암",))
        for word in ("모니터 암", "모니터암", "로봇 암", "로봇암", "암 거치대", "암거치대"):
            self.assertIn(word, cn.HEALTH_MASKS_KO)


class FixRoundDecisionsTest(unittest.TestCase):                                                                 # X14 — 1라운드 수정(D-136~D-138)이 못박는 결정
    def check(self, cases, why):
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected, why)

    def test_a_supplement_with_an_instant_word_on_more_action_verbs_is_still_an_order_of_actions(self):
        self.check((("영양제 바로 사는 방법", MARK), ("영양제 즉시 담는 법", MARK), ("영양제 바로 피하는 습관", MARK), ("영양제 즉시 설명해 주는 앱", MARK), ("영양제 바로 꺼내 먹기", MARK), ("비타민 바로 넣는 방법", MARK), ("영양제 바로 듣는 강의", MARK)),
                   "A-4: 영양제 + 바로·즉시 + 행동 동사 = A(옛 C)")

    def test_more_taking_questions_need_evidence(self):
        self.check((("영양제 먹어도 돼요", EVIDENCE), ("영양제 먹어도 되죠", EVIDENCE), ("영양제 먹어도 됩니까", EVIDENCE), ("영양제 먹어도 안전한가", EVIDENCE), ("영양제 먹어도 문제없나", EVIDENCE), ("영양제 먹어도 될는지", EVIDENCE),
                    ("영양제 복용해도 될까", EVIDENCE), ("영양제 끊어도 될까", EVIDENCE), ("영양제 먹어야 하나요", EVIDENCE), ("비타민 같이 먹어도 안전한가요", EVIDENCE)), "A-7: 복용 허용 질문 꼬리 보강 = B")

    def test_seven_more_prescription_drug_names_and_the_dose_or_order_split(self):
        self.check((("혈압약 무조건 끊어도 되나요", STOP), ("인슐린 100% 안전", STOP), ("항암제 즉시 중단하는 법", STOP), ("피임약 바로 끊어도 될까", STOP), ("항응고제 무조건 먹는 법", STOP), ("스타틴 확실히 줄이는 방법", STOP), ("당뇨약 즉시 증량하는 방법", STOP)),
                   "A-6: 처방약 낱말 + 복용·중단·용량 = C")
        self.check((("인슐린", MARK), ("스타틴 알기", MARK), ("혈압약", EVIDENCE)), "처방약 단독 = A, 이름 속 질환 낱말이 든 셋은 옛 B 를 지킨다")
        self.check((("수면제 바로 끊어도 될까", STOP), ("항생제 즉시 복용하는 순서", STOP), ("스테로이드 즉시 바꾸는 방법", STOP), ("항우울제 바로 멈추는 방법", STOP)), "A-8: 복용·중단·용량 변경 행동 = C 유지")
        self.check((("수면제 바로 알기", MARK), ("수면제 바로 알아보는 방법", MARK), ("처방약 영수증 즉시 정리하는 방법", MARK), ("처방약 무조건 챙겨 두는 서류", MARK), ("처방약 확실히 보관하는 법", MARK)), "A-8: 그 밖의 행동 순서 = A")

    def test_two_old_stops_are_released_and_nothing_else_around_them(self):
        self.check((("영양제 확실히 확인하기", MARK), ("영양제 완전히 정리하는 방법", MARK), ("영양제 무조건 챙겨 두는 서류 정리법", MARK), ("치료 바로 시작하기", MARK), ("치료 즉시 확인하는 방법", MARK), ("통증 치료 바로 시작하기", EVIDENCE)),
                   "A-10: 영양제 + 확실히·완전히·무조건 + 행동 순서, 치료 + 바로·즉시 + 행동 순서만 푼다")
        self.check((("치료 확실히 시작하기", STOP), ("치료 완전히 끝내기", STOP), ("치료 바로 끊어도 될까", STOP), ("치료 바로 먹어도 될까", STOP), ("한약 바로 먹는 법", STOP), ("영양제 즉시 흡수되는 시간", STOP)), "나머지 옛 중지 바닥은 의도적 보수 — 풀지 않는다")

    def test_english_light_assertion_reads_only_three_tokens_after_it(self):
        for text, expected in (("immediately reduce fatigue", STOP), ("immediately do it reduce fatigue", STOP), ("immediately do it now reduce fatigue", MARK), ("instantly improve your task list", GENERAL)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected, "A34: 영어 가벼운 단정 뒤 세 낱말 안에 효과 결과 낱말이 있으면 효과 꾸밈, 넷째 낱말부터는 읽지 않는다")
        self.assertEqual(cn.health_signals(["immediately do it reduce fatigue"]).scoped, (("immediately", "soft", "effect"),))
        self.assertEqual(cn.health_signals(["immediately do it now reduce fatigue"]).scoped, (("immediately", "soft", "none"),))

    def test_an_unknown_modifier_of_the_strong_word_counts_only_beside_a_disease(self):
        self.check((("당뇨 무조건 성공", STOP), ("당뇨 환자 무조건 성공 사례", EVIDENCE), ("피로 무조건 성공", MARK), ("통증 무조건 성공", MARK)),
                   "D-136: 꾸밈을 모르는 `무조건` 은 질환 낱말 바로 뒤일 때만 단정이다(질환 없는 증상 곁이나 질환에서 떨어진 자리는 세지 않는다 — 옛 영양제 낱말 곁 `영양제 무조건 성공` C 는 옛 중지 바닥)")
        self.check((("영양제 무조건 성공", STOP),), "옛 중지 바닥이 지킨다")
        self.assertEqual(cn.health_signals(["당뇨 무조건 성공"]).counted_assert(), ("무조건",))
        self.assertEqual(cn.health_signals(["피로 무조건 성공"]).counted_assert(), (), "질환이 없으면 꾸밈을 모르는 무조건은 단정으로 세지 않는다(변이 N13)")
        self.assertEqual(cn.health_signals(["당뇨 환자 무조건 성공 사례"]).counted_assert(), (), "질환 낱말 바로 뒤가 아니면 세지 않는다")

    def test_the_notice_does_not_name_an_assertion_word_the_decisions_released(self):
        for text, shown in (("영양제 확실히 확인하기", ("영양제",)), ("수면제 바로 알기", ("수면제",)), ("치료 바로 시작하기", ("치료",)), ("영양제 바로 알기", ("영양제",))):
            with self.subTest(text=text):
                self.assertEqual(sf.check_text([text]).findings[0].matched, shown, "푼 단정 낱말(strong 포함·처방약 포함)은 알림에 보이지 않는다")

    def test_the_health_object_window_is_two_words_before_the_assertion_word(self):
        self.assertEqual(stage("피로 앱 즉시 줄이는 방법"), STOP)
        self.assertEqual(stage("피로 앱 광고 즉시 줄이는 방법"), MARK, "E3b: 대상 창은 단정 낱말 앞 두 낱말 — 셋째 낱말 앞의 건강 낱말은 대상이 아니다")
        self.assertEqual(stage("피로 앱 광고 알림을 즉시 줄이는 방법"), MARK)
        self.assertEqual(stage("스트레스 앱 로딩 시간을 줄일 수 있습니다"), MARK, "활용형 Phrase 도 같은 창으로 대상을 본다(창 밖의 건강 낱말은 대상이 아니다)")

    def test_the_health_object_of_an_effect_verb_must_be_in_the_same_text_piece(self):
        self.assertEqual(stage("피로를 즉시 줄이는 방법"), STOP)
        self.assertEqual(sf.check_text(["피로", "즉시 줄이는 방법"]).stage, MARK, "A42: 건강 낱말이 앞 글 조각에 있으면 대상으로 읽지 않는다(조각 경계를 넘지 않는다)")
        self.assertEqual(sf.check_text(["피로를 줄이는 방법", "즉시 시작하기"]).stage, MARK)
        self.assertEqual(sf.check_text(["즉시 줄이는 피로 해소법", "피로를 즉시 줄이는 방법"]).stage, STOP, "같은 조각 안의 대상은 그대로 읽는다")


class ExpectedSampleTest(unittest.TestCase):                                                                    # X15 — 독립 문장 표본 고정(D-139)과 옛 중지 고정 표
    HEALTHLESS = {"e", "t6", "en"}

    def accepted(self, label, group):
        if label == "A":
            return {GENERAL, MARK} if group in self.HEALTHLESS else {MARK}
        return {"AB": {GENERAL, MARK, EVIDENCE}, "B": {EVIDENCE}, "BC": {EVIDENCE, STOP}, "C": {STOP}, "ABC": {GENERAL, MARK, EVIDENCE, STOP}}[label]

    def test_the_confident_independent_sentences_keep_their_stage(self):
        self.assertGreaterEqual(len(he.SAME_AS_OLD) + len(he.CHANGED_BY_DECISION), 150)
        self.assertEqual((len(he.SAME_AS_OLD), len(he.CHANGED_BY_DECISION)), (261, 79))
        seen = set()
        for sentence, label, group, new in he.SAME_AS_OLD:
            with self.subTest(sentence=sentence):
                self.assertEqual(stage(sentence), SHORT_TO_STAGE[new])
                self.assertIn(SHORT_TO_STAGE[new], self.accepted(label, group))
            seen.add(sentence)
        for sentence, label, group, old, new in he.CHANGED_BY_DECISION:
            with self.subTest(sentence=sentence):
                self.assertEqual(stage(sentence), SHORT_TO_STAGE[new])
                self.assertIn(SHORT_TO_STAGE[new], self.accepted(label, group))
                self.assertNotEqual(old, new, "결정으로 달라진 문장만 이 표에 있다")
                if old == "C":
                    self.assertIn(new, ("A", "B"), "옛 중지가 풀린 것은 영양제 결정 ① 같은 의도 목록뿐이다")
                else:
                    self.assertGreaterEqual(RANK[SHORT_TO_STAGE[new]], RANK[SHORT_TO_STAGE[old]], "옛 표시·근거는 내려가지 않는다 — 올라가기만 한다")
            seen.add(sentence)
        self.assertGreaterEqual(len(seen), 300, "같은 문장이 여러 줄에 실려도 한 번만 센다 — 고유 문장 수")

    def test_the_old_stop_table_is_still_stopped_except_the_released_kinds(self):
        self.assertEqual((len(he.OLD_STOPS_KEPT), len(he.OLD_STOPS_RELEASED)), (192, 54))          # 의도적 갱신(D-140): 1라운드 165 + N-2 같은 틀 18 + 보험 구절 9
        self.assertEqual(len(set(he.OLD_STOPS_KEPT)), len(he.OLD_STOPS_KEPT))
        for sentence in he.OLD_STOPS_KEPT:
            with self.subTest(sentence=sentence):
                self.assertEqual(stage(sentence), STOP, "옛 코드가 중지로 읽던 글(옛 단계는 미리 계산해 박은 표)을 새 코드가 풀지 않는다")
        kinds = {"영양제": cn.SUPPLEMENT_SET, "처방약": cn.MEDICINE_SET}
        for sentence, kind, new in he.OLD_STOPS_RELEASED:
            with self.subTest(sentence=sentence):
                self.assertEqual(stage(sentence), SHORT_TO_STAGE[new])
                self.assertNotEqual(stage(sentence), STOP)
                low = sentence.lower()
                if kind == "치료":
                    self.assertIn("치료", sentence)
                else:
                    self.assertTrue(any(word.lower() in low for word in kinds[kind]) or "probiotic" in low or "supplement" in low, f"푼 이유({kind}) 낱말이 글에 있다")
        self.assertEqual({kind for _s, kind, _n in he.OLD_STOPS_RELEASED}, {"영양제", "처방약", "치료"}, "푼 이유는 결정 세 가지뿐 — 보험 마스크는 이유가 아니다(D-138)")


class SecondFixRoundTest(unittest.TestCase):                                                                    # X16 — 2라운드 수정(D-140, 렌즈 A2 중간 N-1·N-2와 낮음)
    def check(self, cases, why):
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected, why)

    def test_the_old_stop_floor_counts_a_prescription_word_inside_the_new_drug_names_as_the_old_code_did(self):
        # N-2 — `처방약` 이 제품 표 낱말이 되면서 이름 속 `처방`(의료 효능어) 조각이 세어지지 않아 옛 중지가 풀렸다 — 바닥 열쇠는 옛 제품 표 기준으로 센다
        self.check((("영양제로 처방약 대체 가능한 방법", STOP), ("처방약과 영양제 같이 먹어도 될까", STOP), ("처방약 복용 중 비타민 먹어도 될까", STOP), ("처방약 대신 영양제로 치료", STOP), ("처방약 효과 확실한 영양제", STOP),
                    ("처방약 영양제 병행 100% 안전", STOP), ("해열제 대신 영양제로 치료", STOP), ("스테로이드 효과 확실한 영양제", STOP)), "옛 코드가 C 로 읽던 글은 새 처방약 낱말이 끼어도 C")
        self.check((("예시 처방약 글", MARK), ("처방약 보관함 정리", MARK), ("처방약 영수증 즉시 정리하는 방법", MARK), ("처방약 바로 알기", MARK), ("혈압약 영양제 같이 먹어도 될까", EVIDENCE)), "결정으로 푼 곳(처방약 + 행동 순서)·옛 B 는 그대로")
        signals = cn.health_signals(["영양제로 처방약 대체 가능한 방법"])
        self.assertEqual(signals.legacy_product(), ("영양제",), "옛 제품 표에는 처방약이 없었다")
        self.assertEqual(signals.legacy_concept_key(), (0, 0, 1, 1, 0, 0), "영양제(제품) + 처방(의료 효능어) — 옛 코드의 열쇠")
        self.assertIn(("medical", "처방"), signals.inside, "새 계산은 처방약 이름 속 조각이라 따로 세지 않는다")
        self.assertNotIn(("medical", "처방"), signals.legacy_inside, "옛 계산은 센다")
        self.assertEqual(signals.floor_key(), (0, 0, 1, 1, 0, 0))
        self.assertIn(signals.floor_key(), sf.LEGACY_STOP_KEYS)

    def test_the_new_product_words_are_exactly_the_eleven_the_old_table_did_not_have(self):
        self.assertEqual(len(cn.NEW_PRODUCT_KO), 11)
        self.assertEqual(len(cn.HEALTH_PRODUCT_KO) - len(cn.NEW_PRODUCT_KO), 34, "옛 제품 표는 34개였다(d5dcb8c)")
        self.assertTrue(set(cn.NEW_PRODUCT_KO) <= set(cn.HEALTH_PRODUCT_KO))
        self.assertEqual(set(cn.NEW_PRODUCT_KO), {"해열제", "스테로이드", "처방약", "항우울제", "혈압약", "당뇨약", "인슐린", "항암제", "피임약", "항응고제", "스타틴"})
        self.assertTrue(set(cn.NEW_PRODUCT_KO) <= set(cn.HEALTH_MEDICINE_KO), "새 제품 낱말은 전부 처방약 하위 종류다")
        for word in ("수면제", "항생제", "진통제", "의약품", "치료제"):
            self.assertIn(word, cn.HEALTH_PRODUCT_KO)
            self.assertNotIn(word, cn.NEW_PRODUCT_SET, "옛 제품 낱말은 새 낱말이 아니다")

    def test_one_letter_disease_is_not_raised_by_arm_game_and_gear_sentences(self):
        # N-1 — ARM(프로세서)·서버·게임 레벨·클라이밍·모양·로봇 팔 문맥의 `암` 은 건강 판정이 없다. 질환 이름 속 `암` 은 그대로(마스크는 낱말 처음에서 시작할 때만)
        for text in ("암 프로세서 성능 비교", "암프로세서 성능 비교", "암 기반 맥북 vs 인텔 맥북", "암 서버 도입 후기", "애플 실리콘 암 아키텍처 설명", "암 모양 구름 사진 찍는 법", "암 클라이밍 장비 고르기",
                     "로봇 팔 암 구조 설명", "암 레벨을 올리는 방법", "스크린 암 거치대 설치 방법", "모니터 암 높이 조절", "화강암 샘플 정리", "암호화폐 시세 보기"):
            with self.subTest(text=text):
                self.assertEqual((stage(text), health_codes(text)), (GENERAL, []), "건강 판정 없음")
        for text in ("유방암 모양 변화 확인하기", "대장암 서버 기록", "폐암 레벨 분류", "위암 기반 연구 정리", "갑상선암 모양 변화", "유방암 거치대 후기", "암 환자 서버 접속", "암 치료 기반 식단"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), EVIDENCE, "질환 이름 속·질환 곁의 암은 그대로 B")
        self.check((("암 관련 공식 정보 확인하기", EVIDENCE), ("암 100% 보장", STOP), ("암호화 방식을 바로 바꾸는 방법", GENERAL), ("암 즉시 확인하는 방법", EVIDENCE)), "기존 기준은 그대로")
        for word in ("암 프로세서", "암 기반", "암 아키텍처", "암 서버", "암 레벨", "암 클라이밍", "암 모양", "로봇 팔 암"):
            self.assertIn(word, cn.HEALTH_MASKS_KO)
        self.assertEqual(len(cn.Tables.mask_start), len([word for word in cn.HEALTH_MASKS_KO if word.startswith("암")]), "암으로 시작하는 마스크는 낱말 처음 검사를 거친다")
        self.assertFalse([word for word in cn.HEALTH_MASKS_KO if word.startswith("암")][len(cn.Tables.mask_start):], "모두 거친다")

    def test_the_advice_forms_the_chunks_and_the_disease_gaps_stay_pinned(self):
        # 낮음 1 — `줄여야·늘려야` 권고 꼴과 `화강암`·`암호화폐`·질환 곁 `치료` 가 시험 밖이었다
        self.check((("당뇨 환자가 무조건 줄여야 하는 음식", EVIDENCE), ("고혈압 환자는 소금을 즉시 줄여야 합니다", EVIDENCE), ("당뇨 환자가 무조건 늘려야 하는 운동량", EVIDENCE)), "권고 꼴(줄여야·늘려야)은 효과 결과가 아니다 — 질환 단독 B")
        self.check((("당뇨 치료 바로 시작하기", STOP), ("암 치료 즉시 시작하기", STOP)), "질환 곁의 `치료` 는 풀지 않는다(결정은 `치료` 단독만) — 옛 중지 유지")
        self.check((("당뇨 환자 수면제 무조건 성공 사례", STOP), ("당뇨 환자는 수면제 무조건 끊어도 될까", STOP), ("당뇨 환자 수면제 무조건 정리 서류", EVIDENCE)), "처방약 곁의 꾸밈 모르는 무조건(`far`)은 센다, 행동 순서는 안 센다")
        self.check((("영양제 바로 증량하는 방법", MARK), ("영양제 즉시 투여하는 방법", MARK), ("당뇨약 즉시 증량하는 방법", STOP)), "증량·투여는 복용 행동 — 영양제는 행동 순서, 처방약은 C")
        self.assertEqual(len(cn.HEALTH_DOSE_SCOPE_KO), 41)
        self.assertEqual([word for word in cn.HEALTH_DOSE_SCOPE_KO if word not in cn.HEALTH_ACTION_SCOPE_KO], ["투여", "증량"], "복용 행동 표는 행동 표의 부분집합이 아니다 — 두 낱말만 행동 표에 없다(복용 행동을 먼저 읽는다)")

    def test_the_numbers_in_the_decisions_document_equal_the_table_sizes_in_the_code(self):
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        rows = {line.split(" | ")[0].lstrip("| "): line for line in text.splitlines() if line.startswith("| D-")}
        sizes = (f"결과 서술어 조각 {len(cn.HEALTH_RESULT_SCOPE_KO)}·행동 서술어 조각 {len(cn.HEALTH_ACTION_SCOPE_KO)}·복용 질문 어간 {len(cn.HEALTH_ASK_STEMS_KO)}·꼬리 {len(cn.HEALTH_ASK_TAILS_KO)}·"
                 f"단정 종결 Phrase {len(cn.HEALTH_ASSERT_FORMS_KO)}·제품 {len(cn.HEALTH_PRODUCT_KO)}(처방약 {len(cn.HEALTH_MEDICINE_KO)})·건강 마스크 {len(cn.HEALTH_MASKS_KO)}")
        self.assertIn(sizes, text, "문서의 '표 크기' 줄 숫자 여덟 개가 코드 표 크기와 같다")
        for number, needles in (("D-136", ("결과 조각 322 → 338", f"행동 서술어 218 → {len(cn.HEALTH_ACTION_SCOPE_KO)}", f"`HEALTH_ASSERT_FORMS_KO` {len(cn.HEALTH_ASSERT_FORMS_KO)}개",
                                          f"복용 질문 어간 6 → {len(cn.HEALTH_ASK_STEMS_KO)}·꼬리 8 → {len(cn.HEALTH_ASK_TAILS_KO)}")),
                                ("D-137", (f"제품 표 38 → {len(cn.HEALTH_PRODUCT_KO)}, 처방약 9 → {len(cn.HEALTH_MEDICINE_KO)}",)),
                                ("D-138", (f"옛 중지 유지 {len(he.OLD_STOPS_KEPT)}", f"푼 {len(he.OLD_STOPS_RELEASED)}")),
                                ("D-139", (f"{len(he.SAME_AS_OLD) + len(he.CHANGED_BY_DECISION)}문장", f"옛과 같음 {len(he.SAME_AS_OLD)}·결정으로 달라짐 {len(he.CHANGED_BY_DECISION)}")),
                                ("D-140", (f"옛 제품 표 {len(cn.HEALTH_PRODUCT_KO) - len(cn.NEW_PRODUCT_KO)}개", f"새 제품 낱말 {len(cn.NEW_PRODUCT_KO)}개", "건강 마스크 48"))):          # 의도적 갱신(D-299, WP-B5 수정 라운드): D-136 행은 그때의 결과 조각 수 338 을 말한다 — 지금(368)은 맨 아래 '표 크기' 줄과 D-299 행이 말한다 · 의도적 갱신(D-291, WP-B5): D-140 행은 그때의 마스크 크기 48 을 말한다 — 그 뒤에 늘어난 크기는 아래 '표 크기' 줄(`sizes`)이 코드와 맞춘다
            for needle in needles:
                with self.subTest(decision=number, needle=needle):
                    self.assertIn(needle, rows[number])
        for number in ("D-139", "D-140"):
            status = rows[number].rsplit(" | ", 1)[1]
            self.assertEqual([word for word in ("FIXING", "DECISION_REQUIRED", "DEFERRED", "VERIFIED", "CLOSED") if word in status], ["DEFERRED"] if number == "D-139" else ["VERIFIED"])
        for needle in ("글자 하나씩 띄운", "컴퓨터 바이러스를 완전히 치료하는 방법", "인용형", "항응고제 즉시 먹지 않는 방법", "암 치료 즉시 시작하기", "`암 ` 5천 자"):
            self.assertIn(needle, rows["D-139"])
        self.assertNotIn("1,000글자 1ms 대 시험은 유지", rows["D-139"], "근거 없는 성능 시험 문구는 지웠다(1천 자 6~9ms 는 실측이고 자동 시험은 없다)")
        self.assertIn("그 길이를 재는 자동 시험은 없다", rows["D-139"])


if __name__ == "__main__":
    unittest.main()
