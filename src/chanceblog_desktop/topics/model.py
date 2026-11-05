"""엔진 후보 `TopicCandidate` — 5채널 주제 엔진이 만드는 후보 한 건의 자료 모양과 검증(순수 계산 — 저장·화면·네트워크·시계·난수 없음).

기존 `content.candidates.Candidate`(사람이 고르는 주제 후보)와 **나란히 두는 별개 자료**다. 기존 후보를 바꾸지 않고, 엔진 후보를 기존 후보로 옮기는 일(투영)은 다음 묶음이다.
규칙: ① 한 줄 규칙·위험한 표기 거절·결과를 약속하는 표현 금지는 기존 후보와 **같은 도구**(`content.candidates` 의 `_line`·`_keyword`·`forbidden_claim`)를 쓴다 — 주제·키워드·이유·오류·관심도 글칸 전부에.
② 채널은 후보 한 건에 **하나**다(`channel`, 코드의 채널 키 — 입력 별칭은 저장하지 않는다). 같은 주제를 두 채널에서 쓰는 것은 후보 여러 건이 같은 `source_topic_id` 를 갖거나 `similar_post_ids` 로 서로를 가리키는 것으로 표현한다.
③ **상태 축이 둘이다**: `work_status`(사람의 작업 흐름 — 기존 후보의 NEW·REVIEW·SELECTED·HOLD·REJECTED 를 그대로 쓴다)와 `recommendation_band`(추천 구간 — 점수에서 계산하는 값이라 저장하지 않는다). 하나의 status 로 합치지 않는다.
④ **관심도(Trend)와 실제 검색 횟수는 다른 칸이다**: 관심도는 상대값(`trend_ratio` 0~100)과 그 기준(`trend_period`·`trend_compared_group`·`trend_queried_on`), 실제 검색 횟수(`search_demand_count`)는 횟수를 주는 출처가 있을 때만(`search_demand_source` 필수)이며
점수 계산은 이 칸을 읽지 않는다. 상대값은 어떤 경우에도 횟수 칸으로 흘러가지 않고, 관심도 서비스를 출처로 적은 횟수는 거절한다. '월 검색량'·'조회수' 같은 이름은 칸 이름·저장 키·화면 이름 어디에도 쓰지 않는다.
⑤ 모르는 값은 0 이 아니라 `None`(점수·관심도·횟수) 이다. 후보는 바꿀 수 없는 값이고(frozen) 고치려면 `dataclasses.replace` 로 새로 만든다(그때 다시 검증한다).
저장 모양은 `schema` 1 의 엄격한 JSON 이다 — 모르는 칸·빠진 필수 칸은 거절하고 다른 칸은 기본값이다. 모든 검증 실패는 `CANDIDATE_INVALID`(어느 칸이 왜 안 되는지)로 낸다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType

from ..content.candidates import MAX_REASON, MAX_SUB_KEYWORDS, MAX_TOPIC, NEW, STATUSES, _day, _ID, _invalid, _keyword, _line, _lines, keyword_key, parse_stamp
from .channels import CHANNEL_ALIAS, CHANNELS, LANGUAGES, is_slug, is_tag
from .score import DATA_INSUFFICIENT, DATA_STATUSES, DETERMINATE_TRENDS, TREND_INSUFFICIENT, TREND_STATUSES, Factors, ScoreCard, band_of

SCHEMA = 1

# ---- 닫힌 목록 ------------------------------------------------------------------------------------------------------------------
SOURCE_TYPES = ("seed", "follow_up", "seasonal", "realtime", "sponsor")                  # 후보가 생긴 경로(비율은 `channels.SOURCE_MIX`)
CANDIDATE_TYPES = ("evergreen", "seasonal", "realtime", "follow_up", "sponsor_prep")
DUPLICATE_STATUSES = ("different_topic", "similar_elements", "different_angle_needed", "duplicate_or_update")      # 비어 있으면(None) 아직 중복 확인 전
SEARCH_INTENTS = ("information", "how_to", "problem_solving", "selection_guide", "comparison", "local_info", "context_explainer", "routine_building")
CONTENT_TYPES = ("explainer", "how_to_guide", "checklist", "troubleshooting", "buying_guide", "comparison", "place_guide", "news_analysis", "routine_plan", "dev_log", "service_intro")
# 엔진의 글 종류 → 기존 글 유형 다섯 개(`content.profiles.POST_TYPES`). 대응은 초기 판단이고 운영자가 바꿀 수 있다 — 모든 글 종류에 대응이 있고 다섯 유형이 모두 쓰인다(시험).
CONTENT_TO_POST_TYPE = MappingProxyType({
    "explainer": "정보형", "how_to_guide": "정보형", "checklist": "정보형", "news_analysis": "정보형", "routine_plan": "정보형",
    "troubleshooting": "문제 해결형", "dev_log": "문제 해결형",
    "buying_guide": "비교형", "comparison": "비교형",
    "service_intro": "제품·서비스 소개형",
    "place_guide": "장소·업체 정보형",
})

# ---- 한도 -----------------------------------------------------------------------------------------------------------------------
MAX_TARGET_READER = 120
MAX_PERIOD = 60
MAX_COMPARED = 10
MAX_SIMILAR = 20
MAX_TAGS = 10
MAX_REASONS = 10
MAX_ERRORS = 10
MAX_SEARCH_COUNT = 1_000_000_000
MAX_SEQUENCE = 9999
KST = timedelta(hours=9)                                                                  # 화면 표시는 한국 시간(+9) 고정 — 저장은 UTC
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}")
# 관심도(상대값)를 주는 서비스를 '실제 검색 횟수의 출처' 로 적을 수 없다 — 글자·숫자만 남긴 소문자 글에 이 낱말이 있으면 거절한다
_TREND_SOURCE_WORDS = ("trend", "datalab", "트렌드", "데이터랩", "관심도", "상대지수", "상대값")

LABELS = MappingProxyType({
    "candidate_id": "후보 번호", "source_topic_id": "원천 주제 번호", "seed_id": "씨앗 번호", "source_type": "후보가 생긴 경로", "candidate_type": "후보 종류", "channel": "채널", "language": "언어",
    "topic": "추천 포스팅 주제", "primary_keyword": "핵심 키워드", "secondary_keywords": "보조 키워드", "search_intent": "검색 의도", "content_type": "글 종류", "topic_cluster": "주제 묶음",
    "topic_angle": "관점", "target_reader": "대상 독자", "scores": "점수", "trend_status": "최근 관심도 변화", "trend_ratio": "최근 관심도(상대값)", "trend_period": "관심도 비교 기간",
    "trend_compared_group": "관심도 비교 키워드 그룹", "trend_queried_on": "관심도 조회일", "search_demand_count": "실제 검색 횟수", "search_demand_source": "검색 횟수 출처",
    "data_status": "자료 상태", "duplicate_status": "중복 판정", "similar_post_ids": "비슷한 글", "monetization_tags": "협업 가능 유형", "selection_reasons": "선정 이유",
    "processing_errors": "처리 중 문제", "work_status": "작업 상태", "recommendation_band": "추천 구간", "created_at": "만든 시각", "review_expires_at": "검토 기한",
})

_KEYS = ("schema", "candidate_id", "source_topic_id", "seed_id", "source_type", "candidate_type", "channel", "language", "topic", "primary_keyword", "secondary_keywords", "search_intent",
         "content_type", "topic_cluster", "topic_angle", "target_reader", "scores", "trend_status", "trend_ratio", "trend_period", "trend_compared_group", "trend_queried_on",
         "search_demand_count", "search_demand_source", "data_status", "duplicate_status", "similar_post_ids", "monetization_tags", "selection_reasons", "processing_errors",
         "work_status", "created_at", "review_expires_at")
_REQUIRED = frozenset({"schema", "candidate_id", "source_type", "candidate_type", "channel", "language", "topic", "primary_keyword", "search_intent", "content_type", "topic_cluster",
                       "topic_angle", "target_reader", "created_at"})


def _choice(value, allowed, item):
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(item, "다음 중 하나여야 합니다: " + ", ".join(allowed))
    return value


def _optional_id(value, item):
    if value is not None and (not isinstance(value, str) or not _ID.fullmatch(value)):
        raise _invalid(item, "영문·숫자·밑줄(_)·붙임표(-) 1~64자이거나 비워 두어야 합니다")
    return value


def _channel(value):
    """채널은 코드의 채널 키 하나여야 한다 — 전략 문서의 입력 별칭(blogger_a·blogger_b)은 저장하지 않는다."""
    if not isinstance(value, str) or value not in CHANNELS:
        alias = f" — ‘{value}’ 은(는) 입력 별칭이라 저장하지 않습니다(‘{CHANNEL_ALIAS[value]}’ 를 쓰세요)" if isinstance(value, str) and value in CHANNEL_ALIAS else ""
        raise _invalid(LABELS["channel"], "다음 중 하나여야 합니다: " + ", ".join(CHANNELS) + alias)
    return value


def _tokens(values, item, *, count, ok, shape):
    """list·tuple 만 받는다 — 각 낱말은 `ok` 를 통과해야 하고 겹칠 수 없다."""
    names = _lines(values, item, count=count)
    if not all(ok(name) for name in names):
        raise _invalid(item, f"각 낱말은 {shape}여야 합니다")
    if len(set(names)) != len(names):
        raise _invalid(item, "같은 낱말이 두 번 들어 있습니다")
    return names


def _texts(values, item, *, count):
    """한 줄 글의 목록(선정 이유·처리 중 문제) — 각 글은 후보의 다른 글칸과 같은 규칙으로 검사한다."""
    return tuple(_line(text, item, low=1, high=MAX_REASON) for text in _lines(values, item, count=count))


def _compared(values):
    item = LABELS["trend_compared_group"]
    names, seen = [], set()
    for word in _lines(values, item, count=MAX_COMPARED):
        text = _keyword(word, item)
        if keyword_key(text) in seen:
            raise _invalid(item, f"‘{text}’ 이(가) 겹칩니다")
        seen.add(keyword_key(text))
        names.append(text)
    return tuple(names)


def check_trend(status, ratio, period, group, queried_on):
    """관심도(Trend) 다섯 칸을 함께 검사해 (상태, 상대값, 비교 기간, 비교 키워드 그룹, 조회일) 로 돌려준다. 후보와 출처 스냅샷이 같은 규칙을 쓴다.
    상대값에는 비교 기간·비교 키워드 그룹이 함께 있어야 하고, 관심도 값이 하나라도 있으면 조회일도 있어야 하며, 상승·보통·하락은 상대값이 있을 때만 쓸 수 있다."""
    _choice(status, TREND_STATUSES, LABELS["trend_status"])
    if ratio is not None and (not isinstance(ratio, int) or isinstance(ratio, bool) or not 0 <= ratio <= 100):
        raise _invalid(LABELS["trend_ratio"], "0~100 사이의 정수이거나 비워 두어야 합니다")
    period = None if period is None else _line(period, LABELS["trend_period"], low=1, high=MAX_PERIOD)
    names = _compared(group)
    if queried_on is not None:
        _day(queried_on, LABELS["trend_queried_on"])
    if ratio is not None and (period is None or not names):
        raise _invalid(LABELS["trend_ratio"], "상대값에는 비교 기간과 비교 키워드 그룹이 함께 있어야 합니다")
    if (ratio is not None or period is not None or names) and queried_on is None:
        raise _invalid(LABELS["trend_queried_on"], "관심도 값이 있으면 조회일도 있어야 합니다")
    if status in DETERMINATE_TRENDS and ratio is None:
        raise _invalid(LABELS["trend_status"], "상승·보통·하락은 상대값이 있을 때만 쓸 수 있습니다")
    return status, ratio, period, names, queried_on


def _flat(text):
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def check_search_demand(count, source):
    """실제 검색 횟수와 그 출처. 값이 있으면 출처도 필수이고, 출처만 있어도 안 되며, 관심도(상대값)를 주는 서비스는 출처가 될 수 없다."""
    if count is not None and (not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= MAX_SEARCH_COUNT):
        raise _invalid(LABELS["search_demand_count"], f"0~{MAX_SEARCH_COUNT:,} 사이의 정수이거나 비워 두어야 합니다")
    source = None if source is None else _line(source, LABELS["search_demand_source"], low=1, high=MAX_PERIOD)
    if count is not None and source is None:
        raise _invalid(LABELS["search_demand_source"], "실제 검색 횟수에는 횟수를 준 출처의 이름이 있어야 합니다")
    if source is not None and count is None:
        raise _invalid(LABELS["search_demand_count"], "출처만 있고 횟수가 없습니다")
    if source is not None and any(word in _flat(source) for word in _TREND_SOURCE_WORDS):
        raise _invalid(LABELS["search_demand_source"], "관심도(상대값)를 주는 서비스는 실제 검색 횟수의 출처가 될 수 없습니다")
    return count, source


def to_post_type(content_type):
    """엔진의 글 종류 → 기존 글 유형(`content.profiles.POST_TYPES` 중 하나)."""
    if not isinstance(content_type, str) or content_type not in CONTENT_TO_POST_TYPE:
        raise _invalid(LABELS["content_type"], "다음 중 하나여야 합니다: " + ", ".join(CONTENT_TYPES))
    return CONTENT_TO_POST_TYPE[content_type]


def display_id(created_at, sequence):
    """화면에 보일 번호 `candidate-YYYYMMDD-NNN` — 저장 번호로는 쓰지 않는다(앞 글자가 모두 같아 번호 앞부분으로 고를 수 없다). 날짜는 한국 시간 기준이고 순번은 부르는 쪽이 정한다."""
    moment = parse_stamp(created_at, LABELS["created_at"])
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not 1 <= sequence <= MAX_SEQUENCE:
        raise _invalid("표시 번호의 순번", f"1~{MAX_SEQUENCE} 사이의 정수여야 합니다")
    return f"candidate-{moment + KST:%Y%m%d}-{sequence:03d}"


@dataclass(frozen=True, kw_only=True)
class TopicCandidate:
    candidate_id: str                                   # 내부 번호(uuid 16진수 같은 [A-Za-z0-9_-] 1~64자) — 만드는 쪽이 정한다(여기서 난수를 쓰지 않는다)
    source_type: str                                    # 후보가 생긴 경로: seed·follow_up·seasonal·realtime·sponsor
    candidate_type: str                                 # evergreen·seasonal·realtime·follow_up·sponsor_prep
    channel: str                                        # 채널 코드 키 하나
    language: str                                       # ko·en
    topic: str                                          # 추천 포스팅 주제(발행 제목이 아니다)
    primary_keyword: str
    search_intent: str                                  # `SEARCH_INTENTS` 중 하나
    content_type: str                                   # `CONTENT_TYPES` 중 하나(`to_post_type` 으로 기존 글 유형에 대응)
    topic_cluster: str                                  # 주제 묶음(영문 소문자-붙임표 식별자)
    topic_angle: str                                    # 관점(같은 식별자 모양)
    target_reader: str
    created_at: str                                     # 만든 시각(UTC `YYYY-MM-DDTHH:MM:SSZ`) — 시계는 부르는 쪽이 준다
    source_topic_id: str | None = None                  # 같은 원천 주제에서 나온 후보끼리 묶는 번호
    seed_id: str | None = None                          # 씨앗 번호(씨앗에서 나오지 않은 후보는 None)
    secondary_keywords: tuple = ()
    scores: ScoreCard = ScoreCard()                     # 여섯 항목 + 최종 점수 — 비어 있으면 '점수 없음'
    trend_status: str = TREND_INSUFFICIENT              # rising·flat·falling·insufficient(데이터 부족)
    trend_ratio: int | None = None                      # NAVER Search Trend 상대지수(0~100) — 실제 검색 횟수가 아니다
    trend_period: str | None = None                     # 상대값의 비교 기간(한 줄 글)
    trend_compared_group: tuple = ()                    # 상대값의 비교 키워드 그룹
    trend_queried_on: str | None = None                 # 관심도 조회일(YYYY-MM-DD)
    search_demand_count: int | None = None              # 실제 검색 횟수 — 횟수를 주는 출처가 있을 때만(점수 계산은 읽지 않는다)
    search_demand_source: str | None = None             # 그 횟수의 출처 이름(횟수가 있으면 필수)
    data_status: str = DATA_INSUFFICIENT                # sufficient·partial·insufficient(모자람)·unavailable(조회 불가 — 장애·한도)
    duplicate_status: str | None = None                 # None 이면 아직 중복 확인 전
    similar_post_ids: tuple = ()
    monetization_tags: tuple = ()
    selection_reasons: tuple = ()                       # 왜 골랐나
    processing_errors: tuple = ()                       # 처리 중에 생긴 문제(선정 이유와 분리)
    work_status: str = NEW                              # 작업 흐름(`content.candidates.STATUSES`) — 추천 구간과 다른 축이다
    review_expires_at: str | None = None                # 다시 볼 기한(보류 구간 후보의 보관 기한 등)

    def __post_init__(self):
        def put(name, value):
            object.__setattr__(self, name, value)

        if not isinstance(self.candidate_id, str) or not _ID.fullmatch(self.candidate_id):
            raise _invalid(LABELS["candidate_id"], "영문·숫자·밑줄(_)·붙임표(-) 1~64자여야 합니다")
        _optional_id(self.source_topic_id, LABELS["source_topic_id"])
        _optional_id(self.seed_id, LABELS["seed_id"])
        _choice(self.source_type, SOURCE_TYPES, LABELS["source_type"])
        _choice(self.candidate_type, CANDIDATE_TYPES, LABELS["candidate_type"])
        _channel(self.channel)
        _choice(self.language, LANGUAGES, LABELS["language"])
        put("topic", _line(self.topic, LABELS["topic"], low=1, high=MAX_TOPIC))
        put("primary_keyword", _keyword(self.primary_keyword, LABELS["primary_keyword"]))
        subs, seen = [], {keyword_key(self.primary_keyword)}
        for word in _lines(self.secondary_keywords, LABELS["secondary_keywords"], count=MAX_SUB_KEYWORDS):
            text = _keyword(word, LABELS["secondary_keywords"])
            if keyword_key(text) in seen:
                raise _invalid(LABELS["secondary_keywords"], f"‘{text}’ 이(가) 핵심 키워드나 다른 보조 키워드와 같습니다")
            seen.add(keyword_key(text))
            subs.append(text)
        put("secondary_keywords", tuple(subs))
        _choice(self.search_intent, SEARCH_INTENTS, LABELS["search_intent"])
        _choice(self.content_type, CONTENT_TYPES, LABELS["content_type"])
        for name in ("topic_cluster", "topic_angle"):
            if not is_slug(getattr(self, name)):
                raise _invalid(LABELS[name], "영문 소문자·숫자·붙임표(-)로 된 식별자(예: local-ai)여야 합니다")
        put("target_reader", _line(self.target_reader, LABELS["target_reader"], low=1, high=MAX_TARGET_READER))
        if not isinstance(self.scores, ScoreCard):
            raise _invalid(LABELS["scores"], "점수 묶음(ScoreCard)이어야 합니다")
        _status, _ratio, period, group, _queried = check_trend(self.trend_status, self.trend_ratio, self.trend_period, self.trend_compared_group, self.trend_queried_on)
        put("trend_period", period)
        put("trend_compared_group", group)
        _count, source = check_search_demand(self.search_demand_count, self.search_demand_source)
        put("search_demand_source", source)
        _choice(self.data_status, DATA_STATUSES, LABELS["data_status"])
        if self.duplicate_status is not None:
            _choice(self.duplicate_status, DUPLICATE_STATUSES, LABELS["duplicate_status"])
        put("similar_post_ids", _tokens(self.similar_post_ids, LABELS["similar_post_ids"], count=MAX_SIMILAR, ok=lambda name: isinstance(name, str) and _REF.fullmatch(name) is not None,
                                        shape="영문·숫자로 시작하는 글 번호(영문·숫자·._:- 120자까지)"))
        put("monetization_tags", _tokens(self.monetization_tags, LABELS["monetization_tags"], count=MAX_TAGS, ok=is_tag, shape="영문 소문자·숫자·밑줄(_)로 된 태그"))
        put("selection_reasons", _texts(self.selection_reasons, LABELS["selection_reasons"], count=MAX_REASONS))
        put("processing_errors", _texts(self.processing_errors, LABELS["processing_errors"], count=MAX_ERRORS))
        _choice(self.work_status, STATUSES, LABELS["work_status"])
        created = parse_stamp(self.created_at, LABELS["created_at"])
        if self.review_expires_at is not None and parse_stamp(self.review_expires_at, LABELS["review_expires_at"]) < created:
            raise _invalid(LABELS["review_expires_at"], "만든 시각보다 앞설 수 없습니다")

    @property
    def recommendation_band(self):
        """추천 구간(RECOMMENDED·GENERAL·HOLD·EXCLUDED·UNRATED) — 최종 점수에서 계산하고 저장하지 않는다. 작업 상태(`work_status`)와 다른 축이다."""
        return band_of(self.scores.final)

    def to_dict(self):
        return {
            "schema": SCHEMA, "candidate_id": self.candidate_id, "source_topic_id": self.source_topic_id, "seed_id": self.seed_id, "source_type": self.source_type,
            "candidate_type": self.candidate_type, "channel": self.channel, "language": self.language, "topic": self.topic, "primary_keyword": self.primary_keyword,
            "secondary_keywords": list(self.secondary_keywords), "search_intent": self.search_intent, "content_type": self.content_type, "topic_cluster": self.topic_cluster,
            "topic_angle": self.topic_angle, "target_reader": self.target_reader, "scores": self.scores.to_dict(), "trend_status": self.trend_status, "trend_ratio": self.trend_ratio,
            "trend_period": self.trend_period, "trend_compared_group": list(self.trend_compared_group), "trend_queried_on": self.trend_queried_on,
            "search_demand_count": self.search_demand_count, "search_demand_source": self.search_demand_source, "data_status": self.data_status, "duplicate_status": self.duplicate_status,
            "similar_post_ids": list(self.similar_post_ids), "monetization_tags": list(self.monetization_tags), "selection_reasons": list(self.selection_reasons),
            "processing_errors": list(self.processing_errors), "work_status": self.work_status, "created_at": self.created_at, "review_expires_at": self.review_expires_at,
        }

    @classmethod
    def from_dict(cls, data):
        """저장된 모양을 엄격하게 읽는다 — 모르는 칸·빠진 필수 칸·어긋난 값은 CANDIDATE_INVALID 로 거절한다. 필수가 아닌 칸이 빠져 있으면 기본값이다."""
        if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != SCHEMA:
            raise _invalid("엔진 후보 저장 형식", "저장된 엔진 후보의 모양(schema 1)이 아닙니다")
        keys = set(data)
        unknown, missing = sorted(map(str, keys - set(_KEYS))), sorted(_REQUIRED - keys)
        if unknown or missing:
            raise _invalid("엔진 후보 저장 형식", "저장된 엔진 후보에 모르는 칸이 있거나 꼭 있어야 하는 칸이 없습니다", detail=f"모르는 칸 {unknown}, 빠진 칸 {missing}")
        values = {name: value for name, value in data.items() if name != "schema"}
        if "scores" in values:
            values["scores"] = ScoreCard.from_dict(values["scores"])
        return cls(**values)


__all__ = [
    "CANDIDATE_TYPES", "CONTENT_TO_POST_TYPE", "CONTENT_TYPES", "DUPLICATE_STATUSES", "Factors", "LABELS", "SCHEMA", "SEARCH_INTENTS", "SOURCE_TYPES", "ScoreCard", "TopicCandidate",
    "check_search_demand", "check_trend", "display_id", "to_post_type",
]
