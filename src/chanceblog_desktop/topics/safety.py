"""규칙 기반 안전 표시 — 후보의 글(주제·핵심 키워드·보조 키워드)과 출처를 **개념군 조합**으로 훑어 '확인 필요' 표시와 사용자 알림을 정한다(P2b 보완, D-50·D-51·D-105 — 순수 계산: 파일·네트워크·시계·난수·AI 없음, 같은 입력은 늘 같은 결과).

표시는 다섯 가지이고(`model.SAFETY_FLAGS` — 값·순서 불변) **표시만 한다 — 후보를 지우거나 점수·구간·작업 상태를 바꾸지 않는다**(지울지는 운영자가 정한다). 낱말 표는 `concepts.py` 한 곳에 있고 이 파일은 **신호 → 상태·표시·알림** 만 정한다:
  · `health_check` — 건강(D-105): 증상 S·질환 D·건강 제품 P·의료 효능어 M(= 건강 대상)과 효과 E·단정 A 여섯 값의 64칸 표(`HEALTH_MATRIX`)가 **네 단계**를 정한다 — 일반 생활정보(표시 없음) /
    **A 표시만**(알림 `HEALTH_TOPIC` — 확인 필요 표시, 감점 0·차단 0) / **B 근거 확인 필요**(`HEALTH_EFFECT` — 표시 + 근거가 없으면 근거 점수 조건부 감점, 차단 0) / **C 의료·효과 단정 위험**(`HEALTH_STOP` — 표시 + 오류, 자동 초안 중지).
    '자동 초안 중지' 는 저장하지 않고 `SafetyReport.stop` 으로 계산한다(`mark` 는 표시를 더하기만 해서 낡은 '중지' 가 남지 않게). 단계는 `SafetyReport.stage`, 옛 세 상태는 `SafetyReport.health`(A·B 모두 '확인 필요')에 그대로 있다.
    감점은 건강 낱말 자체가 아니라 **근거가 필요한 주장(B·C)에 근거가 없을 때만** 한다 — 그 계산은 `generate.py`(`needs_evidence`)가 한다.
  · `product_brand` — **예약 값**이다. 일반 낱말('추천'·'비교'·'모델' …)과 글 종류는 신호가 아니라서 이 표시는 자동으로 붙지 않는다(이름은 화면에 '제품·브랜드' 그대로).
  · `experience_claim` — 직접 겪은 일을 단정하는 말: `check/claims.py` 의 `find_violations`(읽기만 한다) ∪ 경험 장르 낱말('사용기'·'체험기' …) ∪ '후기'·'리뷰' 와 경험 표지 ∪ 영어 문구('I used' …).
  · `sponsor_disclosure` — 경제적 이해관계: 협업 **가능성**(`monetization_opportunity` — 협찬 태그·협찬 경로·협찬 준비형·제안 중 협찬 정보)은 표시가 아니고 INFO 알림뿐이다. 글에 협찬 표현이 있으면 **추정**(`economic_relationship` = suspected,
    '확인 필요'), **확정된 협찬 정보(`Campaign`)** 가 있을 때만 표시를 강제한다(confirmed). 브랜드·회사 이름은 어느 표에도 없다. **본문 고지 문구는 만들지 않는다**(다음 단계 P6).
    확인된 이해관계의 **유형**은 `UNKNOWN`(아직 확인 안 함 — 기본값)·`NONE`(사용자가 '없다'고 확인)·양성 8종(`INTEREST_TYPES`)이고 `SafetyReport.interests` 가 말한다 — 추정(`suspected`)과 협업 가능성은 `UNKNOWN` 을 바꾸지 못한다(글 낱말 탐지는 저장된 상태를 바꾸지 않는다).
    저장된 상태가 `NONE` 인데 글에서 협찬이 추정되면(충돌) 추정 알림 대신 확인 경고 `ECONOMIC_CONFLICT` 하나를 낸다(표시는 추정과 같이 붙는다). 확정된 양성 유형이 닿으면 `NONE` 은 무시하고 충돌도 따지지 않는다.
  · `result_promise` — 결과를 약속하는 표현('상위노출 보장'·'수익 보장' …, 기존 `content.candidates.forbidden_claim` 과 같은 판정 — 읽기만 한다): 후보의 글칸은 처음부터 이것을 거절하므로 후보를 만들기 **전의 글**을 검사할 때 쓴다.
걸린 말은 고정 표의 낱말이나 기존 검사의 분류 이름이라서 입력한 글을 되풀이하지 않는다.

**경제적 이해관계 유형(`INTEREST_TYPES` — `UNKNOWN` + 9종)은 2026-11-06 전략 원문 대조로 정한 값이다**(D-102 — 옛 5종 이름은 `LEGACY_BENEFIT_NAMES` 로 읽는다). **글에서 협찬을 '추정'하는 낱말 표(`concepts.py`)·알림 문장(`notice.py`)·`Campaign` 의
모양은 여전히 구현자 초기값이다** — 운영자 요청서의 개념군 낱말을 시작 목록으로 넓힌 것이라 원문 표와 대조할 값이 아니고, 추정(낱말)과 사람이 확인한 값(유형)은 일부러 다른 표로 둔다.

**건강 판정(D-105·D-106)은 2026-11-06 운영자 결정이다** — 전략 원문 §21 의 여섯 낱말(피로·불면·통증·자세·체중·영양제)은 이미 증상 표·제품 표에 있어 낱말 표는 그대로이고, 세 단계와 근거 점수 감점 조건만 새로 적용했다.
건강의 나머지 낱말과 경험 낱말 표는 여전히 구현자 초기값이다.
"""
from __future__ import annotations

import dataclasses
import re
from types import MappingProxyType
from typing import NamedTuple

from ..check.claims import LABELS as CLAIM_LABELS
from ..check.claims import find_violations
from ..content.candidates import forbidden_claim
from . import concepts, notice, wording
from .channels import CHANNELS, invalid_in
from .model import SAFETY_FLAGS, TopicCandidate

FLAG_HEALTH, FLAG_PRODUCT, FLAG_EXPERIENCE, FLAG_SPONSOR, FLAG_PROMISE = SAFETY_FLAGS
FLAG_KO = wording.SAFETY_FLAG_KO

HEALTH_GENERAL, HEALTH_CHECK, HEALTH_STOP = "general", "check", "stop"             # `SafetyReport.health` — 옛 세 상태(D-50). A·B 는 둘 다 `check`
HEALTH_STATE_KO = MappingProxyType({HEALTH_GENERAL: "일반 생활정보", HEALTH_CHECK: "건강 정보 확인 필요", HEALTH_STOP: "의료·효과 단정 위험"})

# 판정 단계 넷(D-105, 운영자 2026-11-06) — 낮은 단계 → 높은 단계 순서. `SafetyReport.stage` 의 값이다.
STAGE_GENERAL, STAGE_MARK, STAGE_EVIDENCE, STAGE_STOP = "general", "mark", "evidence", "stop"
HEALTH_STAGES = (STAGE_GENERAL, STAGE_MARK, STAGE_EVIDENCE, STAGE_STOP)
HEALTH_STAGE_KO = MappingProxyType({STAGE_GENERAL: "일반 생활정보", STAGE_MARK: "건강 정보 확인 필요(표시만)", STAGE_EVIDENCE: "근거 확인 필요", STAGE_STOP: "의료·효과 단정 위험"})
HEALTH_STAGE_CODE = MappingProxyType({STAGE_MARK: "HEALTH_TOPIC", STAGE_EVIDENCE: "HEALTH_EFFECT", STAGE_STOP: "HEALTH_STOP"})       # 단계 → 알림 코드. `HEALTH_CLAIM` 은 이 표에서 쓰이는 곳이 없다
HEALTH_STAGE_STATE = MappingProxyType({STAGE_GENERAL: HEALTH_GENERAL, STAGE_MARK: HEALTH_CHECK, STAGE_EVIDENCE: HEALTH_CHECK, STAGE_STOP: HEALTH_STOP})        # 단계 → `SafetyReport.health`
_G, _A, _B, _C = STAGE_GENERAL, STAGE_MARK, STAGE_EVIDENCE, STAGE_STOP
# 전체 조합표 — 열쇠 (증상 S, 질환 D, 제품 P, 의료 효능어 M, 효과 E, 단정 A) 64칸을 **손으로 푼** 초기값이다. 한 줄 = 건강 대상 네 값(S·D·P·M) 하나, 네 칸 = 효과·단정 (E·A) = 0·0 / 0·1 / 1·0 / 1·1 일 때의 단계.
# 식(시험이 이 표와 같은지, 그리고 효능·치료·단정 낱말이 더해지면 단계가 내려가지 않는지 본다):
#   ① 건강 대상(S·D·P·M)이 하나도 없으면 일반 — 일반 낱말·효능·단정 낱말만 있어도 일반 / ② S·D·P·M 하나만 있으면 A(표시만)
#   ③ P + (E 또는 S 또는 D) → B / ④ P + (M 또는 A) → C / ⑤ (S·D·P·M 하나 이상) + E + A → C(운영자 예시 3·4)
#   ⑥ 운영자가 정하지 않은 조합 — 덜 개입하는 쪽, 단 '의료·효과를 단정하는 말'이 들어가면 올린다: S+M·D+M·D+E·M+E → B, M+A → C, S+E·S+A·D+A → A.
#   ('M+A → C' 는 옛 16칸 표에서도 중지였다 — 치료를 단정하면 대상이 하나뿐이어도 중지. 'D 가 P 와 함께 → B' 는 ③ 의 증상에 질환을 포함시킨 것.)
_ROWS = (
    ((0, 0, 0, 0), (_G, _G, _G, _G)),
    ((1, 0, 0, 0), (_A, _A, _A, _C)),
    ((0, 1, 0, 0), (_A, _A, _B, _C)),
    ((1, 1, 0, 0), (_A, _A, _B, _C)),
    ((0, 0, 1, 0), (_A, _C, _B, _C)),
    ((1, 0, 1, 0), (_B, _C, _B, _C)),
    ((0, 1, 1, 0), (_B, _C, _B, _C)),
    ((1, 1, 1, 0), (_B, _C, _B, _C)),
    ((0, 0, 0, 1), (_A, _C, _B, _C)),
    ((1, 0, 0, 1), (_B, _C, _B, _C)),
    ((0, 1, 0, 1), (_B, _C, _B, _C)),
    ((1, 1, 0, 1), (_B, _C, _B, _C)),
    ((0, 0, 1, 1), (_C, _C, _C, _C)),
    ((1, 0, 1, 1), (_C, _C, _C, _C)),
    ((0, 1, 1, 1), (_C, _C, _C, _C)),
    ((1, 1, 1, 1), (_C, _C, _C, _C)),
)
HEALTH_MATRIX = MappingProxyType({(*targets, effect, assertion): stage for targets, stages in _ROWS for (effect, assertion), stage in zip(((0, 0), (0, 1), (1, 0), (1, 1)), stages, strict=True)})
OPPORTUNITY_NONE, OPPORTUNITY_POSSIBLE = "none", "possible"
RELATION_NONE, RELATION_SUSPECTED, RELATION_CONFIRMED = "none", "suspected", "confirmed"
MAX_TEXTS, MAX_SHOWN = 50, 4                                                       # MAX_SHOWN: 한 알림에 보여 줄 걸린 말의 최대 수(건강은 증상·효과·제품·단정에서 하나씩)


# 경제적 이해관계 유형 — `UNKNOWN` + 9종(2026-11-06 전략 원문 대조에서 운영자가 정한 값, D-102). 내부 값(영문 대문자)은 화면에 내지 않고 `INTEREST_KO` 의 한국어 이름만 보인다.
#   UNKNOWN = 아직 확인하지 않음(기본값) / NONE = 사용자가 '경제적 이해관계가 없다'고 확인한 명시적 상태(Null·빈 목록이 아니다) / 나머지 8개 = 확정된 이해관계 유형(양성).
#   UNKNOWN·NONE 은 다른 유형과 섞이지 않는다. 협업 가능성·글 낱말 추정(`suspected`)은 UNKNOWN 을 바꾸지 못한다 — 사용자가 확인해야 NONE·유형이 된다.
INTEREST_UNKNOWN, INTEREST_NONE = "UNKNOWN", "NONE"
INTEREST_TYPES = ("UNKNOWN", "NONE", "PRODUCT_PROVIDED", "SERVICE_PROVIDED", "VISIT_OR_MEAL_PROVIDED", "HONORARIUM", "DISCOUNT_OR_COUPON", "AFFILIATE_COMMISSION", "CONDITIONAL_REWARD", "OTHER")
INTEREST_KO = MappingProxyType({"UNKNOWN": "미확인", "NONE": "없음", "PRODUCT_PROVIDED": "제품 제공", "SERVICE_PROVIDED": "서비스 제공", "VISIT_OR_MEAL_PROVIDED": "방문·식사 제공", "HONORARIUM": "원고료",
                                "DISCOUNT_OR_COUPON": "할인·쿠폰", "AFFILIATE_COMMISSION": "제휴 수수료", "CONDITIONAL_REWARD": "조건부 보상", "OTHER": "기타"})
# 확정된 협찬 정보(`Campaign.benefits`)에 적을 수 있는 이득 종류 = 위에서 UNKNOWN·NONE 을 뺀 양성 8개(같은 순서). **글 낱말로 협찬을 '추정'하는 `concepts` 의 개념군 5개(goods·service·payment·affiliate·reward — 추정용)와는
# 다른 값이다** — 추정은 낱말 표가 하고 확인은 사람이 한다(둘을 같은 표로 합치지 않는다, D-102).
BENEFIT_KINDS = tuple(kind for kind in INTEREST_TYPES if kind not in (INTEREST_UNKNOWN, INTEREST_NONE))
BENEFIT_KO = MappingProxyType({kind: INTEREST_KO[kind] for kind in BENEFIT_KINDS})
MAX_SHOWN_BENEFITS = len(BENEFIT_KINDS)                                              # 확정된 이득 종류의 이름은 전부 보인다(최대 8개) — 건강·경험 같은 다른 알림의 걸린 말 한도 `MAX_SHOWN`(4)과 따로 둔다
# 옛 5종 이름(소문자) → 새 이름. `Campaign`·`check_text` 가 옛 이름을 읽을 때만 쓰고(읽기 호환) 보관·내보내기(`to_dict`)는 늘 새 이름이다. 저장된 자료를 바꾸지 않는다.
LEGACY_BENEFIT_NAMES = MappingProxyType({"goods": "PRODUCT_PROVIDED", "service": "SERVICE_PROVIDED", "payment": "HONORARIUM", "affiliate": "AFFILIATE_COMMISSION", "reward": "CONDITIONAL_REWARD"})
CAMPAIGN_STATUSES = ("confirmed", "proposed")                                       # 확정(받았거나 받기로 확정) / 제안·협의 중(가능성일 뿐)
CAMPAIGN_STATUS_KO = MappingProxyType({"confirmed": "확정", "proposed": "제안·협의 중"})
MAX_CAMPAIGNS = 200
CAMPAIGN_SCHEMA = 1
CAMPAIGN_SUBJECT = "협찬 정보"
CAMPAIGN_KEYS = ("schema", "campaign_id", "benefits", "status", "seed_id", "source_topic_id", "candidate_id", "channel")
CAMPAIGN_FIELD_KO = MappingProxyType({"schema": "저장 형식 번호", "campaign_id": "협찬 번호", "benefits": "이득 종류", "status": "협찬 상태", "seed_id": "씨앗 번호", "source_topic_id": "원천 주제 번호",
                                      "candidate_id": "후보 번호", "channel": "채널"})
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SPONSOR_GROUP_KO = MappingProxyType({**concepts.GROUP_KO, "general": "협찬·광고 표현"})
_HASHTAG_KO = "해시태그"


def _campaign_invalid(item, detail=""):
    return invalid_in(CAMPAIGN_SUBJECT, item, detail)


def _canonical(kind):
    """옛 소문자 이름(`goods` …)이면 새 이름, 아니면 받은 그대로(모양이 틀린 값도 그대로 두어 뒤의 검사가 거절한다)."""
    return LEGACY_BENEFIT_NAMES.get(kind, kind) if isinstance(kind, str) else kind


def _kind_choices():
    """고를 수 있는 값 안내(한국어 이름만) — 양성 8개와, 이해관계가 없다고 확인한 경우의 '없음' 하나."""
    return wording.one_of(BENEFIT_KINDS, BENEFIT_KO) + f"(이해관계가 없다고 확인했다면 {wording.quote(INTEREST_KO[INTEREST_NONE])} 하나만 적습니다)"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Campaign:
    """실제 Campaign Metadata — 어떤 씨앗·원천 주제·후보가 실제로 제품·서비스·방문·식사·원고료·할인·제휴 수수료·조건부 보상 같은 이해관계와 이어져 있는지 **명시적으로** 적는 순수 자료형(저장·화면·파일 없음, 초기값 모양 — 운영 자료가 오면 P3·P6 에서 고친다).
    글에 브랜드·제품 이름이 있다는 이유만으로는 이어 주지 않는다. `status` 가 `confirmed` 일 때만 경제적 이해관계 표시를 강제하고 `proposed`(제안·협의 중)는 협업 가능성일 뿐이다.
    `benefits` 는 양성 유형(`BENEFIT_KINDS` 8개) 1개 이상이거나, 사용자가 '이해관계가 없다'고 확인한 경우의 정확히 `("NONE",)` 하나다(확정 상태에서만 — 제안·협의 중에는 거절, `UNKNOWN` 은 기본 상태일 뿐이라 적을 수 없다).
    옛 소문자 이름(`goods` 등 5종)도 받되 **새 이름으로 바꿔 보관**한다(읽기 호환 — `to_dict` 는 새 이름이다)."""
    campaign_id: str
    benefits: tuple
    status: str
    seed_id: str | None = None
    source_topic_id: str | None = None
    candidate_id: str | None = None
    channel: str | None = None

    def __post_init__(self):
        if not isinstance(self.campaign_id, str) or not _ID.fullmatch(self.campaign_id):
            raise _campaign_invalid("협찬 번호", "영문·숫자·밑줄(_)·붙임표(-) 1~64자여야 합니다")
        if not isinstance(self.benefits, (list, tuple)) or not 1 <= len(self.benefits) <= len(BENEFIT_KINDS):
            raise _campaign_invalid("이득 종류", f"1~{len(BENEFIT_KINDS)}개를 목록으로 적어야 합니다 — " + _kind_choices())
        kinds = tuple(_canonical(kind) for kind in self.benefits)                      # 옛 이름은 새 이름으로 바꿔 보관한다(중복·섞임 검사는 바꾼 뒤의 이름으로 한다)
        if not all(isinstance(kind, str) and kind in INTEREST_TYPES for kind in kinds):
            raise _campaign_invalid("이득 종류", _kind_choices())
        if INTEREST_UNKNOWN in kinds:
            none_name = wording.quote(INTEREST_KO[INTEREST_NONE])                      # 선택지 목록을 되풀이하면 화면의 160자 한도(`errors.render.MAX_SLOT_CHARS`)에서 잘린다 — 짧게 쓴다
            raise _campaign_invalid("이득 종류", f"{wording.quote(INTEREST_KO[INTEREST_UNKNOWN])}은 아직 확인하지 않은 기본 상태라 협찬 정보에 적을 수 없습니다 — 확인한 종류를 적거나, 이해관계가 없다고 확인했다면 {none_name} 하나만 적어 주세요")
        if len(set(kinds)) != len(kinds):
            raise _campaign_invalid("이득 종류", "같은 종류가 두 번 들어 있습니다")
        if INTEREST_NONE in kinds and len(kinds) != 1:
            none_name = wording.quote(INTEREST_KO[INTEREST_NONE])
            raise _campaign_invalid("이득 종류", f"{none_name}은 다른 종류와 함께 적을 수 없습니다 — 이해관계가 없다고 확인했다면 {none_name} 하나만 적어 주세요")
        object.__setattr__(self, "benefits", kinds)
        if not isinstance(self.status, str) or self.status not in CAMPAIGN_STATUSES:
            raise _campaign_invalid("협찬 상태", wording.one_of(CAMPAIGN_STATUSES, CAMPAIGN_STATUS_KO))
        if kinds == (INTEREST_NONE,) and self.status != "confirmed":
            raise _campaign_invalid("이득 종류", f"{wording.quote(INTEREST_KO[INTEREST_NONE])}은 협찬 상태가 {wording.quote(CAMPAIGN_STATUS_KO['confirmed'])}일 때만 쓸 수 있습니다 — 제안·협의 중인 협찬 정보에는 적을 수 없습니다")
        for name, label in (("seed_id", "씨앗 번호"), ("source_topic_id", "원천 주제 번호"), ("candidate_id", "후보 번호")):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not _ID.fullmatch(value)):
                raise _campaign_invalid(label, "영문·숫자·밑줄(_)·붙임표(-) 1~64자이거나 비워 두어야 합니다")
        if self.channel is not None and (not isinstance(self.channel, str) or self.channel not in CHANNELS):
            raise _campaign_invalid("채널", wording.one_of(CHANNELS, wording.CHANNEL_KO) + "(비워 두면 모든 채널)")
        if self.seed_id is None and self.source_topic_id is None and self.candidate_id is None:
            raise _campaign_invalid("연결 대상", "씨앗 번호·원천 주제 번호·후보 번호 중 하나는 있어야 합니다(어디에도 이어지지 않는 협찬 정보는 쓸 곳이 없습니다)")

    def applies_to(self, candidate):
        """이 협찬 정보가 후보에 닿는가 — 값이 있는 연결 칸(씨앗·원천 주제·후보 번호) 가운데 **하나라도** 후보의 같은 칸과 같고, `channel` 이 있으면 후보의 채널과도 같아야 한다."""
        links = ((self.seed_id, candidate.seed_id), (self.source_topic_id, candidate.source_topic_id), (self.candidate_id, candidate.candidate_id))
        return any(mine is not None and mine == theirs for mine, theirs in links) and (self.channel is None or self.channel == candidate.channel)

    def to_dict(self):
        return {"schema": CAMPAIGN_SCHEMA, "campaign_id": self.campaign_id, "benefits": list(self.benefits), "status": self.status, "seed_id": self.seed_id, "source_topic_id": self.source_topic_id,
                "candidate_id": self.candidate_id, "channel": self.channel}

    @classmethod
    def from_dict(cls, data):
        """저장된 모양을 엄격하게 읽는다 — 정확히 이 칸들이어야 하고(모르는 칸·빠진 칸 거절) 값은 `__post_init__` 이 검사한다."""
        if not isinstance(data, dict):
            raise _campaign_invalid("모양", "칸이 있는 묶음(JSON 객체)이어야 합니다")
        unknown, missing = sorted(map(str, set(data) - set(CAMPAIGN_KEYS))), [key for key in CAMPAIGN_KEYS if key not in data]
        if unknown or missing:
            raise _campaign_invalid("모양", wording.unknown_and_missing(unknown, missing, CAMPAIGN_FIELD_KO))
        if type(data["schema"]) is not int or data["schema"] != CAMPAIGN_SCHEMA:
            raise _campaign_invalid("저장 형식 번호", f"저장 형식 번호가 {CAMPAIGN_SCHEMA}인 협찬 정보가 아닙니다")
        return cls(**{key: data[key] for key in CAMPAIGN_KEYS if key != "schema"})


class Finding(NamedTuple):
    flag: str                                       # `SAFETY_FLAGS` 중 하나. 표시를 붙이지 않는 참고(INFO)는 ""
    code: str                                       # 알림 코드(내부) — `notice.CATALOG` 의 열쇠. 화면에 내지 않는다
    level: str                                      # INFO·WARNING·ERROR
    matched: tuple                                  # 걸린 말 — 고정 표의 낱말이나 기존 검사의 분류 이름(입력 글이 아니다), 최대 `MAX_SHOWN`
    groups: tuple = ()                              # 개념군 한국어 이름(건강은 `matched` 와 같은 길이로 짝지음), 협찬 확정이면 이득 종류 이름


class SafetyReport(NamedTuple):
    flags: tuple                                    # 붙일 표시 — `SAFETY_FLAGS` 순서
    findings: tuple                                 # `Finding` — 표시·알림마다 하나(표시 없는 INFO 는 맨 뒤)
    health: str = HEALTH_GENERAL                    # 건강 상태: general·check·stop (표시만·근거 확인 필요는 둘 다 check)
    relationship: str = RELATION_NONE               # 경제적 이해관계: none·suspected·confirmed
    opportunity: str = OPPORTUNITY_NONE             # 협업 가능성: none·possible
    benefits: tuple = ()                            # 확정된 협찬 정보의 이득 종류(`BENEFIT_KINDS` 순서 — 양성만, `NONE`·`UNKNOWN` 은 들어가지 않는다)
    interests: tuple = (INTEREST_UNKNOWN,)          # 확인된 경제적 이해관계 유형(`INTEREST_TYPES` 순서): 기본 ('UNKNOWN',)=아직 확인 안 함 / 확정된 양성 유형이 있으면 그 유형들(`benefits` 와 같다) / 사용자가 '없다'고만 확인했으면 ('NONE',)
    stage: str = STAGE_GENERAL                      # 건강 판정 단계(D-105): general·mark(A 표시만)·evidence(B 근거 확인 필요)·stop(C 의료·효과 단정 위험) — 근거 점수 감점이 이것을 본다

    @property
    def level(self):
        """알림 중 가장 높은 수준(없으면 None)."""
        levels = [finding.level for finding in self.findings]
        return max(levels, key=notice.LEVELS.index) if levels else None

    @property
    def stop(self):
        """수준이 ERROR 인 알림이 하나라도 있으면 True — 자동 초안 중지. 저장하지 않는 계산값이다."""
        return any(finding.level == notice.LEVEL_ERROR for finding in self.findings)

    @property
    def stage_name(self):
        """건강 판정 단계의 한국어 이름(화면용 이름표 `HEALTH_STAGE_KO` — 일반 생활정보 / 건강 정보 확인 필요(표시만) / 근거 확인 필요 / 의료·효과 단정 위험)."""
        return HEALTH_STAGE_KO[self.stage]


def _normalize(texts):
    if isinstance(texts, (str, bytes)) or not isinstance(texts, (list, tuple)) or not all(isinstance(text, str) for text in texts):
        raise TypeError("texts 는 글(문자열)의 목록이어야 한다")
    if len(texts) > MAX_TEXTS:
        raise ValueError(f"글은 {MAX_TEXTS}개까지 검사한다")
    return tuple(texts)


def _first(*groups):
    for group in groups:
        if group:
            return group[0]
    return None


def _health_shown(signals):
    """개념군마다 첫 낱말을 증상 → 효과 → 제품 → 단정 순서로 모은다(최대 `MAX_SHOWN`) — (낱말들, 개념군 이름들)."""
    rows = ((concepts.GROUP_KO["symptom"], _first(signals.counted("symptom"), signals.disease)), (concepts.GROUP_KO["effect"], _first(signals.counted("effect"), signals.counted("medical"))),
            (concepts.GROUP_KO["product"], _first(signals.product)), (concepts.GROUP_KO["assertion"], _first(signals.assert_strong, signals.assert_effect, signals.assert_soft)))
    found = [(group, word.rstrip("*")) for group, word in rows if word]
    return tuple(word for _group, word in found)[:MAX_SHOWN], tuple(group for group, _word in found)[:MAX_SHOWN]


def needs_evidence(stage):
    """근거가 필요한 주장인가 — '근거 확인 필요'(B)와 '의료·효과 단정 위험'(C) 단계다(D-106). '표시만'(A)과 일반은 아니다. 단계를 모르면(`None`) 건강 표시가 붙은 것으로 보고 필요하다고 본다(옛 호출과 같은 동작)."""
    if stage is None:
        return True
    if not isinstance(stage, str) or stage not in HEALTH_STAGES:
        raise ValueError("모르는 건강 판정 단계다")
    return stage in (STAGE_EVIDENCE, STAGE_STOP)


def _health_finding(pieces):
    """(단계, 알림). 단계는 `HEALTH_MATRIX` 가 정하고 알림 코드는 단계가 정한다(A → HEALTH_TOPIC · B → HEALTH_EFFECT · C → HEALTH_STOP)."""
    signals = concepts.health_signals(pieces)
    stage = HEALTH_MATRIX[signals.concept_key()]
    if stage == STAGE_GENERAL:
        return stage, None
    code = HEALTH_STAGE_CODE[stage]
    matched, groups = _health_shown(signals)
    return stage, Finding(FLAG_HEALTH, code, notice.level_of(code), matched, groups)


def _experience_finding(pieces):
    labels = [CLAIM_LABELS[claim.category] for claim in find_violations(list(pieces))]
    signals = concepts.experience_signals(pieces)
    shown = [*dict.fromkeys(labels), *signals.genre, *(["후기·리뷰와 경험 표지"] if signals.marked else []), *dict.fromkeys(signals.phrases)]
    if not shown:
        return None
    return Finding(FLAG_EXPERIENCE, "EXPERIENCE_CLAIM", notice.level_of("EXPERIENCE_CLAIM"), tuple(shown)[:MAX_SHOWN])


def _sponsor_finding(pieces, opportunity, benefits, none_confirmed=False):
    """(관계, 알림). 확정된 협찬 정보가 있으면 글 낱말과 상관없이 확정, 글 낱말만이면 추정, 둘 다 아니고 가능성이면 표시 없는 참고.
    저장된 상태가 명시 '없음'(`none_confirmed` — 확정 양성 유형이 없을 때만 의미가 있다)인데 글에서 협찬이 추정되면 둘이 충돌하는 것이라 **추정 알림 대신 확인 경고 하나**(`ECONOMIC_CONFLICT`)를 낸다 — 표시는 추정과 같이 붙는다.
    글 낱말 탐지는 저장된 상태(`UNKNOWN`·`NONE`·유형)를 바꾸지 않는다(D-102)."""
    if benefits:
        names = tuple(BENEFIT_KO[kind] for kind in benefits)[:MAX_SHOWN_BENEFITS]
        return RELATION_CONFIRMED, Finding(FLAG_SPONSOR, "ECONOMIC_CONFIRMED", notice.level_of("ECONOMIC_CONFIRMED"), (), names)
    signals = concepts.sponsor_signals(pieces)
    if signals.suspected:
        shown = [*signals.strong, *signals.english, *([_HASHTAG_KO] if signals.hashtag else []), *(signals.marker if not signals.strong and not signals.english else ())]
        groups = tuple(_SPONSOR_GROUP_KO[group] for group in signals.groups if group in _SPONSOR_GROUP_KO)
        code = "ECONOMIC_CONFLICT" if none_confirmed else "ECONOMIC_CHECK"
        return RELATION_SUSPECTED, Finding(FLAG_SPONSOR, code, notice.level_of(code), tuple(dict.fromkeys(shown))[:MAX_SHOWN], tuple(dict.fromkeys(groups)))
    if opportunity:
        return RELATION_NONE, Finding("", "COLLAB_POSSIBLE", notice.level_of("COLLAB_POSSIBLE"), ())
    return RELATION_NONE, None


def check_text(texts, *, opportunity=False, benefits=(), none_confirmed=False):
    """글의 목록(주제·핵심 키워드 같은 글 몇 개)에서 안전 표시와 알림을 찾는다. 후보를 만들기 전의 글에도 쓸 수 있다(그래서 결과를 약속하는 표현도 본다). 입력은 바꾸지 않는다.
    `opportunity` 가 참이면 협업 가능성(표시 없음·INFO 알림)이고, `benefits`(`BENEFIT_KINDS` 값의 목록 — 옛 5종 이름도 받는다)가 있으면 확정된 협찬 정보가 있는 것이라 협찬 표시를 강제한다.
    `none_confirmed` 가 참이면 사용자가 '경제적 이해관계가 없다'고 확인한 것이다 — `SafetyReport.interests` 가 `("NONE",)` 이 될 뿐 표시·알림은 줄지 않고(글 낱말 추정은 그대로 남는다), 확정된 이득 종류가 하나라도 있으면 무시한다(안전한 쪽)."""
    pieces = _normalize(texts)
    if not isinstance(opportunity, bool):
        raise TypeError("opportunity 는 참·거짓이어야 한다")
    if not isinstance(none_confirmed, bool):
        raise TypeError("none_confirmed 는 참·거짓이어야 한다")
    kinds = tuple(_canonical(kind) for kind in benefits) if isinstance(benefits, (list, tuple)) else None
    if kinds is None or not all(isinstance(kind, str) and kind in BENEFIT_KINDS for kind in kinds) or len(set(kinds)) != len(kinds):
        raise TypeError("benefits 는 이득 종류(" + ", ".join(BENEFIT_KINDS) + ")의 중복 없는 목록이어야 한다 — 이해관계가 없다고 확인한 경우는 none_confirmed=True")
    confirmed = tuple(kind for kind in BENEFIT_KINDS if kind in kinds)
    interests = confirmed or ((INTEREST_NONE,) if none_confirmed else (INTEREST_UNKNOWN,))
    found = []
    stage, health = _health_finding(pieces)
    if health is not None:
        found.append(health)
    experience = _experience_finding(pieces)
    if experience is not None:
        found.append(experience)
    relation, sponsor = _sponsor_finding(pieces, opportunity, confirmed, none_confirmed)
    if sponsor is not None:
        found.append(sponsor)
    promises = tuple(dict.fromkeys(claim[0] for claim in (forbidden_claim(piece) for piece in pieces) if claim))
    if promises:
        found.append(Finding(FLAG_PROMISE, "RESULT_PROMISE", notice.level_of("RESULT_PROMISE"), promises[:MAX_SHOWN]))
    ordered = tuple(sorted(found, key=lambda finding: SAFETY_FLAGS.index(finding.flag) if finding.flag else len(SAFETY_FLAGS)))
    flags = tuple(flag for flag in SAFETY_FLAGS if any(finding.flag == flag for finding in ordered))
    return SafetyReport(flags, ordered, HEALTH_STAGE_STATE[stage], relation, OPPORTUNITY_POSSIBLE if opportunity else OPPORTUNITY_NONE, confirmed, interests, stage)


def assess(candidate, *, campaigns=()):
    """엔진 후보의 안전 표시 — 주제·핵심 키워드·보조 키워드(대상 독자 칸은 보지 않는다)를 검사한다. 협업 가능성은 협찬 경로·협찬 준비형·협업 태그·**제안 중** 협찬 정보에서, 확정된 이득은 후보에 닿는 **확정** 협찬 정보의 합집합에서 온다.
    확정 협찬 정보가 '없음'(`("NONE",)`)만 닿으면 `interests` 가 `("NONE",)` 이고, 양성 유형이 함께 닿으면 양성이 이긴다. `campaigns` 를 안 주면 협찬 정보가 필요한 부분만 빠진다(`interests` 는 `("UNKNOWN",)`)."""
    if not isinstance(candidate, TopicCandidate):
        raise TypeError("assess(엔진 후보) 로 불러야 한다")
    if isinstance(campaigns, (str, bytes)) or not hasattr(campaigns, "__iter__"):
        raise TypeError("campaigns 는 Campaign 의 목록이어야 한다")
    listed = tuple(campaigns)
    if not all(isinstance(item, Campaign) for item in listed):
        raise TypeError("campaigns 는 Campaign 의 목록이어야 한다")
    reaching = [item for item in listed if item.applies_to(candidate)]
    opportunity = candidate.source_type == "sponsor" or candidate.candidate_type == "sponsor_prep" or bool(candidate.monetization_tags) or any(item.status == "proposed" for item in reaching)
    benefits = tuple(kind for kind in BENEFIT_KINDS if any(kind in item.benefits for item in reaching if item.status == "confirmed"))
    none_confirmed = any(item.benefits == (INTEREST_NONE,) for item in reaching if item.status == "confirmed")                  # 양성 유형이 하나라도 닿으면 `check_text` 가 이 확인을 무시한다
    return check_text([candidate.topic, candidate.primary_keyword, *candidate.secondary_keywords], opportunity=opportunity, benefits=benefits, none_confirmed=none_confirmed)


def mark(candidate, *, campaigns=()):
    """후보에 안전 표시를 더한 새 후보 — 이미 붙어 있던 표시는 그대로 두고 새로 찾은 것을 더한다(`SAFETY_FLAGS` 순서). **표시 칸(`safety_flags`)만 바뀌고** 점수·구간·작업 상태·다른 칸은 그대로다.
    표시가 없으면 같은 후보를 돌려준다. 후보를 지우거나 막지 않는다(자동 초안 중지는 `assess(후보).stop` 으로 계산한다)."""
    report = assess(candidate, campaigns=campaigns)
    merged = tuple(flag for flag in SAFETY_FLAGS if flag in candidate.safety_flags or flag in report.flags)
    if merged == candidate.safety_flags:
        return candidate
    return dataclasses.replace(candidate, safety_flags=merged)


def notes(report):
    """선정 이유용 한 줄들('제목 — 설명 행동(걸린 말: …)') — 후보의 선정 이유 옆에 보일 안내다. 경고·오류 알림만 담고 참고(INFO)는 화면 알림으로만 나간다. 결과 약속 줄에는 걸린 말을 붙이지 않는다."""
    if not isinstance(report, SafetyReport):
        raise TypeError("notes(안전 표시 결과) 로 불러야 한다")
    return notice.notes(report)


__all__ = [
    "BENEFIT_KINDS", "BENEFIT_KO", "CAMPAIGN_STATUSES", "Campaign", "FLAG_EXPERIENCE", "FLAG_HEALTH", "FLAG_KO", "FLAG_PRODUCT", "FLAG_PROMISE", "FLAG_SPONSOR", "Finding", "HEALTH_CHECK",
    "HEALTH_GENERAL", "HEALTH_MATRIX", "HEALTH_STAGES", "HEALTH_STAGE_CODE", "HEALTH_STAGE_KO", "HEALTH_STAGE_STATE", "HEALTH_STATE_KO", "HEALTH_STOP", "INTEREST_KO", "INTEREST_NONE",
    "INTEREST_TYPES", "INTEREST_UNKNOWN", "LEGACY_BENEFIT_NAMES", "MAX_CAMPAIGNS", "MAX_SHOWN", "MAX_SHOWN_BENEFITS", "MAX_TEXTS", "OPPORTUNITY_NONE", "OPPORTUNITY_POSSIBLE",
    "RELATION_CONFIRMED", "RELATION_NONE", "RELATION_SUSPECTED", "STAGE_EVIDENCE", "STAGE_GENERAL", "STAGE_MARK", "STAGE_STOP", "SafetyReport", "assess", "check_text", "mark",
    "needs_evidence", "notes",
]
