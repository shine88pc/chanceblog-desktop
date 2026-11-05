"""규칙 기반 안전 표시 — 후보의 글(주제·핵심 키워드·보조 키워드)과 출처를 **개념군 조합**으로 훑어 '확인 필요' 표시와 사용자 알림을 정한다(P2b 보완, D-50·D-51 — 순수 계산: 파일·네트워크·시계·난수·AI 없음, 같은 입력은 늘 같은 결과).

표시는 다섯 가지이고(`model.SAFETY_FLAGS` — 값·순서 불변) **표시만 한다 — 후보를 지우거나 점수·구간·작업 상태를 바꾸지 않는다**(지울지는 운영자가 정한다). 낱말 표는 `concepts.py` 한 곳에 있고 이 파일은 **신호 → 상태·표시·알림** 만 정한다:
  · `health_check` — 건강: 증상·효과·고위험 대상(제품·질환·의료 효능어)·단정 네 값의 16칸 표(`HEALTH_MATRIX`)가 세 상태를 정한다 — 일반 생활정보(표시 없음) / 건강 정보 확인 필요(표시 + 경고) / 의료·효과 단정 위험(표시 + 오류 — 자동 초안 중지).
    '자동 초안 중지' 는 저장하지 않고 `SafetyReport.stop` 으로 계산한다(`mark` 는 표시를 더하기만 해서 낡은 '중지' 가 남지 않게).
  · `product_brand` — **예약 값**이다. 일반 낱말('추천'·'비교'·'모델' …)과 글 종류는 신호가 아니라서 이 표시는 자동으로 붙지 않는다(이름은 화면에 '제품·브랜드' 그대로).
  · `experience_claim` — 직접 겪은 일을 단정하는 말: `check/claims.py` 의 `find_violations`(읽기만 한다) ∪ 경험 장르 낱말('사용기'·'체험기' …) ∪ '후기'·'리뷰' 와 경험 표지 ∪ 영어 문구('I used' …).
  · `sponsor_disclosure` — 경제적 이해관계: 협업 **가능성**(`monetization_opportunity` — 협찬 태그·협찬 경로·협찬 준비형·제안 중 협찬 정보)은 표시가 아니고 INFO 알림뿐이다. 글에 협찬 표현이 있으면 **추정**(`economic_relationship` = suspected,
    '확인 필요'), **확정된 협찬 정보(`Campaign`)** 가 있을 때만 표시를 강제한다(confirmed). 브랜드·회사 이름은 어느 표에도 없다. **본문 고지 문구는 만들지 않는다**(다음 단계 P6).
  · `result_promise` — 결과를 약속하는 표현('상위노출 보장'·'수익 보장' …, 기존 `content.candidates.forbidden_claim` 과 같은 판정 — 읽기만 한다): 후보의 글칸은 처음부터 이것을 거절하므로 후보를 만들기 **전의 글**을 검사할 때 쓴다.
걸린 말은 고정 표의 낱말이나 기존 검사의 분류 이름이라서 입력한 글을 되풀이하지 않는다.

**낱말 표는 모두 초기값 — 전략 원문 확인 전이다**(표는 `concepts.py`·`wording.py`·`notice.py` 에 있고 `Campaign` 의 모양도 초기값이다).
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

HEALTH_GENERAL, HEALTH_CHECK, HEALTH_STOP = "general", "check", "stop"
HEALTH_STATE_KO = MappingProxyType({HEALTH_GENERAL: "일반 생활정보", HEALTH_CHECK: "건강 정보 확인 필요", HEALTH_STOP: "의료·효과 단정 위험"})
# (증상 s, 효과 e, 고위험 대상 p, 단정 a) → 상태 — 손으로 푼 16칸(초기값). 식: p 가 1 이면 확인 필요(e·a 가 모두 1 이면 중지), p 가 0 이면 s·e·a 가 모두 1 일 때만 확인 필요 아니면 일반.
HEALTH_MATRIX = MappingProxyType({
    (0, 0, 0, 0): HEALTH_GENERAL, (0, 0, 0, 1): HEALTH_GENERAL, (0, 0, 1, 0): HEALTH_CHECK, (0, 0, 1, 1): HEALTH_CHECK,
    (0, 1, 0, 0): HEALTH_GENERAL, (0, 1, 0, 1): HEALTH_GENERAL, (0, 1, 1, 0): HEALTH_CHECK, (0, 1, 1, 1): HEALTH_STOP,
    (1, 0, 0, 0): HEALTH_GENERAL, (1, 0, 0, 1): HEALTH_GENERAL, (1, 0, 1, 0): HEALTH_CHECK, (1, 0, 1, 1): HEALTH_CHECK,
    (1, 1, 0, 0): HEALTH_GENERAL, (1, 1, 0, 1): HEALTH_CHECK, (1, 1, 1, 0): HEALTH_CHECK, (1, 1, 1, 1): HEALTH_STOP,
})
OPPORTUNITY_NONE, OPPORTUNITY_POSSIBLE = "none", "possible"
RELATION_NONE, RELATION_SUSPECTED, RELATION_CONFIRMED = "none", "suspected", "confirmed"
MAX_TEXTS, MAX_SHOWN = 50, 4                                                       # MAX_SHOWN: 한 알림에 보여 줄 걸린 말의 최대 수(건강은 증상·효과·제품·단정에서 하나씩)

BENEFIT_KINDS = ("goods", "service", "payment", "affiliate", "reward")             # 현물·서비스·금전·제휴·조건부 보상 — `concepts` 의 협찬 개념군과 같다
BENEFIT_KO = MappingProxyType({"goods": "제품 제공", "service": "서비스 제공", "payment": "금전 제공(원고료 등)", "affiliate": "제휴·수수료", "reward": "조건부 보상(후기 이벤트 등)"})
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


@dataclasses.dataclass(frozen=True, kw_only=True)
class Campaign:
    """실제 Campaign Metadata — 어떤 씨앗·원천 주제·후보가 실제로 제품·서비스·대가·제휴 수수료·조건부 보상과 이어져 있는지 **명시적으로** 적는 순수 자료형(저장·화면·파일 없음, 초기값 모양 — 운영 자료가 오면 P3·P6 에서 고친다).
    글에 브랜드·제품 이름이 있다는 이유만으로는 이어 주지 않는다. `status` 가 `confirmed` 일 때만 경제적 이해관계 표시를 강제하고 `proposed`(제안·협의 중)는 협업 가능성일 뿐이다."""
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
            raise _campaign_invalid("이득 종류", f"1~{len(BENEFIT_KINDS)}개를 목록으로 적어야 합니다 — " + wording.one_of(BENEFIT_KINDS, BENEFIT_KO))
        if not all(isinstance(kind, str) and kind in BENEFIT_KINDS for kind in self.benefits):
            raise _campaign_invalid("이득 종류", wording.one_of(BENEFIT_KINDS, BENEFIT_KO))
        if len(set(self.benefits)) != len(self.benefits):
            raise _campaign_invalid("이득 종류", "같은 종류가 두 번 들어 있습니다")
        object.__setattr__(self, "benefits", tuple(self.benefits))
        if not isinstance(self.status, str) or self.status not in CAMPAIGN_STATUSES:
            raise _campaign_invalid("협찬 상태", wording.one_of(CAMPAIGN_STATUSES, CAMPAIGN_STATUS_KO))
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
    health: str = HEALTH_GENERAL                    # 건강 상태: general·check·stop
    relationship: str = RELATION_NONE               # 경제적 이해관계: none·suspected·confirmed
    opportunity: str = OPPORTUNITY_NONE             # 협업 가능성: none·possible
    benefits: tuple = ()                            # 확정된 협찬 정보의 이득 종류(`BENEFIT_KINDS` 순서)

    @property
    def level(self):
        """알림 중 가장 높은 수준(없으면 None)."""
        levels = [finding.level for finding in self.findings]
        return max(levels, key=notice.LEVELS.index) if levels else None

    @property
    def stop(self):
        """수준이 ERROR 인 알림이 하나라도 있으면 True — 자동 초안 중지. 저장하지 않는 계산값이다."""
        return any(finding.level == notice.LEVEL_ERROR for finding in self.findings)


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
    rows = ((concepts.GROUP_KO["symptom"], _first(signals.symptom, signals.disease)), (concepts.GROUP_KO["effect"], _first(signals.effect, signals.medical)),
            (concepts.GROUP_KO["product"], _first(signals.product)), (concepts.GROUP_KO["assertion"], _first(signals.assert_strong, signals.assert_effect, signals.assert_soft)))
    found = [(group, word.rstrip("*")) for group, word in rows if word]
    return tuple(word for _group, word in found)[:MAX_SHOWN], tuple(group for group, _word in found)[:MAX_SHOWN]


def _health_finding(pieces):
    signals = concepts.health_signals(pieces)
    key = signals.key()
    state = HEALTH_MATRIX[key]
    if state == HEALTH_GENERAL:
        return state, None
    _s, effect, _p, asserting = key
    code = "HEALTH_STOP" if state == HEALTH_STOP else "HEALTH_CLAIM" if asserting else "HEALTH_EFFECT" if effect else "HEALTH_TOPIC"
    matched, groups = _health_shown(signals)
    return state, Finding(FLAG_HEALTH, code, notice.level_of(code), matched, groups)


def _experience_finding(pieces):
    labels = [CLAIM_LABELS[claim.category] for claim in find_violations(list(pieces))]
    signals = concepts.experience_signals(pieces)
    shown = [*dict.fromkeys(labels), *signals.genre, *(["후기·리뷰와 경험 표지"] if signals.marked else []), *dict.fromkeys(signals.phrases)]
    if not shown:
        return None
    return Finding(FLAG_EXPERIENCE, "EXPERIENCE_CLAIM", notice.level_of("EXPERIENCE_CLAIM"), tuple(shown)[:MAX_SHOWN])


def _sponsor_finding(pieces, opportunity, benefits):
    """(관계, 알림). 확정된 협찬 정보가 있으면 글 낱말과 상관없이 확정, 글 낱말만이면 추정, 둘 다 아니고 가능성이면 표시 없는 참고."""
    if benefits:
        names = tuple(BENEFIT_KO[kind] for kind in benefits)[:MAX_SHOWN]
        return RELATION_CONFIRMED, Finding(FLAG_SPONSOR, "ECONOMIC_CONFIRMED", notice.level_of("ECONOMIC_CONFIRMED"), (), names)
    signals = concepts.sponsor_signals(pieces)
    if signals.suspected:
        shown = [*signals.strong, *signals.english, *([_HASHTAG_KO] if signals.hashtag else []), *(signals.marker if not signals.strong and not signals.english else ())]
        groups = tuple(_SPONSOR_GROUP_KO[group] for group in signals.groups if group in _SPONSOR_GROUP_KO)
        return RELATION_SUSPECTED, Finding(FLAG_SPONSOR, "ECONOMIC_CHECK", notice.level_of("ECONOMIC_CHECK"), tuple(dict.fromkeys(shown))[:MAX_SHOWN], tuple(dict.fromkeys(groups)))
    if opportunity:
        return RELATION_NONE, Finding("", "COLLAB_POSSIBLE", notice.level_of("COLLAB_POSSIBLE"), ())
    return RELATION_NONE, None


def check_text(texts, *, opportunity=False, benefits=()):
    """글의 목록(주제·핵심 키워드 같은 글 몇 개)에서 안전 표시와 알림을 찾는다. 후보를 만들기 전의 글에도 쓸 수 있다(그래서 결과를 약속하는 표현도 본다). 입력은 바꾸지 않는다.
    `opportunity` 가 참이면 협업 가능성(표시 없음·INFO 알림)이고, `benefits`(`BENEFIT_KINDS` 값의 목록)가 있으면 확정된 협찬 정보가 있는 것이라 협찬 표시를 강제한다."""
    pieces = _normalize(texts)
    if not isinstance(opportunity, bool):
        raise TypeError("opportunity 는 참·거짓이어야 한다")
    if isinstance(benefits, (str, bytes)) or not isinstance(benefits, (list, tuple)) or not all(isinstance(kind, str) and kind in BENEFIT_KINDS for kind in benefits) or len(set(benefits)) != len(benefits):
        raise TypeError("benefits 는 이득 종류(" + ", ".join(BENEFIT_KINDS) + ")의 중복 없는 목록이어야 한다")
    confirmed = tuple(kind for kind in BENEFIT_KINDS if kind in benefits)
    found = []
    state, health = _health_finding(pieces)
    if health is not None:
        found.append(health)
    experience = _experience_finding(pieces)
    if experience is not None:
        found.append(experience)
    relation, sponsor = _sponsor_finding(pieces, opportunity, confirmed)
    if sponsor is not None:
        found.append(sponsor)
    promises = tuple(dict.fromkeys(claim[0] for claim in (forbidden_claim(piece) for piece in pieces) if claim))
    if promises:
        found.append(Finding(FLAG_PROMISE, "RESULT_PROMISE", notice.level_of("RESULT_PROMISE"), promises[:MAX_SHOWN]))
    ordered = tuple(sorted(found, key=lambda finding: SAFETY_FLAGS.index(finding.flag) if finding.flag else len(SAFETY_FLAGS)))
    flags = tuple(flag for flag in SAFETY_FLAGS if any(finding.flag == flag for finding in ordered))
    return SafetyReport(flags, ordered, state, relation, OPPORTUNITY_POSSIBLE if opportunity else OPPORTUNITY_NONE, confirmed)


def assess(candidate, *, campaigns=()):
    """엔진 후보의 안전 표시 — 주제·핵심 키워드·보조 키워드(대상 독자 칸은 보지 않는다)를 검사한다. 협업 가능성은 협찬 경로·협찬 준비형·협업 태그·**제안 중** 협찬 정보에서, 확정된 이득은 후보에 닿는 **확정** 협찬 정보의 합집합에서 온다.
    `campaigns` 를 안 주면 협찬 정보가 필요한 부분만 빠진다."""
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
    return check_text([candidate.topic, candidate.primary_keyword, *candidate.secondary_keywords], opportunity=opportunity, benefits=benefits)


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
    "HEALTH_GENERAL", "HEALTH_MATRIX", "HEALTH_STATE_KO", "HEALTH_STOP", "MAX_CAMPAIGNS", "MAX_SHOWN", "MAX_TEXTS", "OPPORTUNITY_NONE", "OPPORTUNITY_POSSIBLE", "RELATION_CONFIRMED", "RELATION_NONE",
    "RELATION_SUSPECTED", "SafetyReport", "assess", "check_text", "mark", "notes",
]
