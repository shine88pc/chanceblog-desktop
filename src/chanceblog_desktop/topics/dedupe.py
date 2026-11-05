"""중복 판정 — 후보가 기존 글·다른 후보와 얼마나 겹치는지 재고, 그 숫자를 채널의 기준(`dup_cutoffs`, 기본 40·60·75)으로 **네 구간**으로 바꾼다. 순수 계산(파일·네트워크·시계·난수 없음, 같은 입력은 늘 같은 결과).

구간(P1 `model.DUPLICATE_STATUSES` 네 값): 다른 주제(기준 1 미만) · 비슷한 요소 있음 · 다른 관점이 필요 · 중복 또는 기존 글 업데이트 후보(기준 3 이상). 기준과 같은 숫자는 위 구간에 든다(40 은 '비슷한 요소 있음', 75 는 '중복…').
**숫자만으로 아무것도 지우거나 제외하지 않는다** — 이 모듈은 후보의 표시 칸(`duplicate_status`·`similar_post_ids`)에 쓸 값을 돌려줄 뿐이고 작업 상태(`work_status`)·점수는 건드리지 않는다. 유사도에 핵심 키워드·검색 의도·주제 묶음·관점·대상 독자가
같은지를 보조 신호(`Signals`)로 함께 돌려주어 운영자가 '같은 글을 고쳐 쓸지, 관점을 달리해 따로 쓸지' 스스로 정하게 한다.

유사도 계산은 단순하고 설명할 수 있다(기존 `check/similarity.py`·`content/suggest*` 의 판정과 별개이고 그것을 바꾸지 않는다):
  ① 제목(후보는 주제)을 NFKC·소문자로 정리하고 글자 종류별(한글·영문·숫자)로 끊어 낱말을 만든다 — 한글 낱말 끝의 조사(은·는·이·가·을·를·의·에서·으로 …)를 떼고, 조사만 남은 낱말과 흔한 군더더기 낱말(방법·정리·가이드·guide·tips …)은 뺀다.
  ② **낱말 겹침** = 두 낱말 집합의 공통 ÷ 합집합. **글자 조각 겹침** = 낱말마다 두 글자씩 끊은 조각(한 글자 낱말은 그대로)의 공통 ÷ 합집합 — 붙여 쓴 말(노트북추천)과 띄어 쓴 말(노트북 추천)의 차이를 메운다.
  ③ 제목 점수 = 낱말 겹침 40 : 글자 조각 겹침 30 의 가중 평균(둘 다 없으면 모름). 핵심 키워드 겹침(키워드 집합의 공통 ÷ 합집합)이 **있고** 제목 점수보다 높으면 둘의 평균으로 올린다 — 키워드가 달라도 제목 점수를 내리지 않는다.
  ④ 최종 유사도(%)는 정수이고 소수점 첫째 자리에서 0.5 를 올린다(`score.round_half_up`). 비교할 글자가 하나도 없으면 0 이 아니라 '모름'(`None`)이고 구간도 None(확인 전)이다.
채널 사이: 같은 원천 주제(`source_topic_id`)는 **최대 2채널**까지이고(`channels.MAX_CHANNELS_PER_TOPIC`), 두 채널에 쓰려면 대상 독자·언어·검색 의도·관점·목차·채널 고유 정보·수익 목적의 일곱 항목 중 `MIN_DIFFERENT_ITEMS`(4)개 이상이 달라야 한다.
목차·채널 고유 정보는 후보 모델에 없어서 호출하는 쪽이 `PairExtras` 로 알려 줄 때만 달라진 것으로 센다(모르면 '모름' — 달라진 것으로도 같은 것으로도 세지 않는다).
"""
from __future__ import annotations

import dataclasses
import itertools
import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from typing import NamedTuple

from ..content.candidates import keyword_key
from .channels import DEFAULT_PROFILES, MAX_CHANNELS_PER_TOPIC, ChannelProfile
from .history import HistoryRecord
from .model import DUPLICATE_STATUSES, MAX_SIMILAR, TopicCandidate
from .score import round_half_up

DIFFERENT_TOPIC, SIMILAR_ELEMENTS, ANGLE_NEEDED, DUPLICATE_OR_UPDATE = DUPLICATE_STATUSES
DEFAULT_CUTOFFS = (40, 60, 75)                                  # 채널 프로필의 기본값과 같다(시험이 확인한다)
STATUS_KO = MappingProxyType({DIFFERENT_TOPIC: "다른 주제", SIMILAR_ELEMENTS: "비슷한 요소 있음", ANGLE_NEEDED: "다른 관점이 필요", DUPLICATE_OR_UPDATE: "중복 또는 기존 글 업데이트 후보"})
WEIGHT_WORDS, WEIGHT_GRAMS = 40, 30                             # 제목 점수에서 낱말 겹침과 글자 조각 겹침의 비율
MAX_MATCHES = MAX_SIMILAR                                       # 한 번에 돌려줄 비슷한 글의 상한 — 후보의 `similar_post_ids` 한도와 같다
_CHANNEL_NAME = {profile.key: profile.display_name for profile in DEFAULT_PROFILES}      # 안내 글에 보일 채널 이름(기본 이름)

_TOKEN = re.compile(r"[a-z0-9]+|[가-힣]+|[^\W\d_a-z가-힣]+")
_HANGUL = re.compile(r"[가-힣]+")
# 한글 낱말 끝의 조사 — 긴 것부터 맞춘다. 떼고 남는 글자가 둘 이상일 때만 뗀다('아이가' → '아이' 는 떼지 않는다: 남는 글자가 하나라 낱말이 아닌 것으로 본다)
_TAILS = tuple(sorted(("은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만", "으로", "에서", "에는", "에도", "에서는", "에서도", "으로는", "로는", "까지", "부터", "보다", "처럼",
                       "하고", "이나", "이랑", "에게", "한테", "라도"), key=len, reverse=True))
PARTICLES = frozenset(_TAILS)                                    # 조사만 남은 낱말은 비교에서 뺀다
FILLERS = frozenset({"방법", "하는", "하기", "정리", "총정리", "가이드", "팁", "꿀팁", "추천", "정보", "알아보기", "알아보는", "관련", "대한", "위한", "있는", "없는", "쉽게", "간단", "간단한", "완벽",
                     "a", "an", "the", "to", "of", "for", "and", "or", "in", "on", "with", "how", "what", "why", "your", "you", "is", "are", "vs", "by", "from", "at", "as", "it", "this", "that",
                     "guide", "tips", "tip", "best", "easy", "simple"})


# ---- 낱말·조각 ------------------------------------------------------------------------------------------------------------------------
def _strip_tail(word):
    for tail in _TAILS:
        if word.endswith(tail) and len(word) - len(tail) >= 2:
            return word[: -len(tail)]
    return word


def words_of(text, *, filtered=True):
    """글 → 비교용 낱말 목록. `filtered` 이면 조사만 남은 낱말과 군더더기 낱말을 뺀다(모두 빠지면 빈 목록)."""
    out = []
    for token in _TOKEN.findall(unicodedata.normalize("NFKC", text).casefold()):
        if _HANGUL.fullmatch(token):
            token = _strip_tail(token)
        if filtered and (token in PARTICLES or token in FILLERS):
            continue
        out.append(token)
    return out


def grams_of(words):
    """낱말마다 두 글자씩 끊은 조각의 집합(한 글자 낱말은 그대로)."""
    grams = set()
    for word in words:
        if len(word) > 1:
            grams.update(word[index:index + 2] for index in range(len(word) - 1))
        else:
            grams.add(word)
    return grams


def _jaccard(left, right):
    union = left | right
    return Fraction(len(left & right), len(union)) if union else None


def _percent(fraction):
    return None if fraction is None else round_half_up(fraction.numerator * 100, fraction.denominator)


# ---- 유사도 ---------------------------------------------------------------------------------------------------------------------------
class Signature(NamedTuple):
    text: str                                       # 후보의 주제 또는 기존 글의 제목(원천 주제)
    keywords: tuple = ()                            # 핵심 키워드들(없으면 빈 튜플)


class Similarity(NamedTuple):
    percent: int | None                             # 최종 유사도(0~100) — 비교할 글자가 없으면 None(모름)
    title: int | None                               # 제목 점수(낱말 겹침 40 : 글자 조각 겹침 30)
    words: int | None                               # 낱말 겹침(%)
    grams: int | None                               # 글자 조각 겹침(%)
    keywords: int | None                            # 핵심 키워드 겹침(%) — 양쪽에 키워드가 없으면 None


def signature_of(item):
    """후보(`TopicCandidate`)는 주제와 핵심·보조 키워드, 기존 글(`HistoryRecord`)은 제목과 키워드."""
    if isinstance(item, TopicCandidate):
        return Signature(item.topic, (item.primary_keyword, *item.secondary_keywords))
    if isinstance(item, HistoryRecord):
        return Signature(item.title, item.keywords)
    raise TypeError("후보(TopicCandidate)나 기존 글(HistoryRecord)이어야 한다")


def similarity(left, right):
    """두 `Signature` 의 유사도 — 대칭이다(순서를 바꿔도 같다). 계산 방식은 모듈 설명의 ①~④."""
    if not isinstance(left, Signature) or not isinstance(right, Signature):
        raise TypeError("similarity(Signature, Signature) 로 불러야 한다")
    left_words, right_words = words_of(left.text), words_of(right.text)
    if not left_words or not right_words:                           # 군더더기·조사뿐인 제목은 걸러 내지 않은 낱말로 비교한다
        left_words, right_words = words_of(left.text, filtered=False), words_of(right.text, filtered=False)
    word_part = _jaccard(set(left_words), set(right_words)) if left_words and right_words else None
    gram_part = _jaccard(grams_of(left_words), grams_of(right_words)) if left_words and right_words else None
    left_keys, right_keys = ({key for key in map(keyword_key, side.keywords) if key} for side in (left, right))
    keyword_part = _jaccard(left_keys, right_keys) if left_keys and right_keys else None            # 한쪽에 키워드가 없으면 모름(0 이 아니다)
    parts = [(WEIGHT_WORDS, word_part), (WEIGHT_GRAMS, gram_part)]
    present = [(weight, part) for weight, part in parts if part is not None]
    title = sum(weight * part for weight, part in present) / sum(weight for weight, _part in present) if present else None
    if title is None:
        final = keyword_part
    elif keyword_part is not None and keyword_part > title:
        final = (title + keyword_part) / 2
    else:
        final = title
    return Similarity(_percent(final), _percent(title), _percent(word_part), _percent(gram_part), _percent(keyword_part))


# ---- 구간 -----------------------------------------------------------------------------------------------------------------------------
def _cutoffs_of(cutoffs):
    if isinstance(cutoffs, ChannelProfile):
        return cutoffs.dup_cutoffs
    if (not isinstance(cutoffs, (tuple, list)) or len(cutoffs) != 3 or not all(isinstance(number, int) and not isinstance(number, bool) and 1 <= number <= 99 for number in cutoffs)
            or not cutoffs[0] < cutoffs[1] < cutoffs[2]):
        raise ValueError("중복 판정 기준은 앞에서 뒤로 커지는 1~99 정수 세 개(예: 40, 60, 75)나 채널 프로필이어야 한다")
    return tuple(cutoffs)


def status_of(percent, cutoffs=DEFAULT_CUTOFFS):
    """유사도(%) → 네 구간 중 하나(`model.DUPLICATE_STATUSES` 의 값). `cutoffs` 는 기준 세 개 또는 채널 프로필(`dup_cutoffs`). 유사도를 모르면(None) 구간도 None(확인 전)이다.
    기준과 같은 숫자는 위 구간이다 — 기본값이면 0~39 다른 주제 · 40~59 비슷한 요소 · 60~74 다른 관점 필요 · 75 이상 중복 또는 업데이트 후보."""
    first, second, third = _cutoffs_of(cutoffs)
    if percent is None:
        return None
    if not isinstance(percent, int) or isinstance(percent, bool) or not 0 <= percent <= 100:
        raise ValueError("유사도는 0~100 사이의 정수이거나 None 이어야 한다")
    if percent >= third:
        return DUPLICATE_OR_UPDATE
    if percent >= second:
        return ANGLE_NEEDED
    if percent >= first:
        return SIMILAR_ELEMENTS
    return DIFFERENT_TOPIC


# ---- 보조 신호와 판정 ------------------------------------------------------------------------------------------------------------------
class Signals(NamedTuple):
    """같은지를 말해 주는 보조 신호 — True 같다·False 다르다·None 모름(비교할 쪽에 그 값이 없다). 구간을 바꾸지 않고 표시에만 쓴다."""
    keyword: bool | None = None                     # 핵심 키워드가 같은가(기존 글은 키워드 목록 안에 있는가)
    intent: bool | None = None                      # 검색 의도
    cluster: bool | None = None                     # 주제 묶음
    angle: bool | None = None                       # 관점
    reader: bool | None = None                      # 대상 독자


SIGNAL_KO = MappingProxyType({"keyword": "핵심 키워드", "intent": "검색 의도", "cluster": "주제 묶음", "angle": "관점", "reader": "대상 독자"})


def _same_text(left, right):
    return keyword_key(left) == keyword_key(right) if keyword_key(left) and keyword_key(right) else left == right


def signals_of(candidate, other):
    """후보와 다른 후보(또는 기존 글)의 보조 신호. 기존 글에는 검색 의도·주제 묶음·관점·대상 독자가 없어 그 칸들은 모름(None)이다."""
    if not isinstance(candidate, TopicCandidate):
        raise TypeError("첫째는 후보(TopicCandidate)여야 한다")
    if isinstance(other, TopicCandidate):
        return Signals(keyword=_same_text(candidate.primary_keyword, other.primary_keyword), intent=candidate.search_intent == other.search_intent,
                       cluster=candidate.topic_cluster == other.topic_cluster, angle=candidate.topic_angle == other.topic_angle, reader=_same_text(candidate.target_reader, other.target_reader))
    if isinstance(other, HistoryRecord):
        keys = {key for key in map(keyword_key, other.keywords) if key}
        return Signals(keyword=keyword_key(candidate.primary_keyword) in keys if keys else None)
    raise TypeError("둘째는 후보(TopicCandidate)나 기존 글(HistoryRecord)이어야 한다")


@dataclass(frozen=True)
class Comparison:
    """한 쌍의 판정 — 유사도·구간·보조 신호. **표시일 뿐이다**: 이 값으로 후보를 지우거나 제외하지 않는다."""
    similarity: Similarity
    status: str | None                              # 네 구간 중 하나(유사도를 모르면 None)
    signals: Signals

    @property
    def percent(self):
        return self.similarity.percent

    def hint(self):
        """화면에 보일 쉬운 한국어 한 줄 — 구간 이름과 유사도, 같은 신호, 다음에 할 일(삭제가 아니라 사람이 정하는 일)."""
        if self.status is None:
            return "비교할 글자가 없어 중복을 확인하지 못했습니다"
        same = [SIGNAL_KO[name] for name, value in self.signals._asdict().items() if value is True]
        text = f"{STATUS_KO[self.status]}({self.percent}%)" + (f" — {', '.join(same)}이(가) 같습니다" if same else "")
        if self.status == DUPLICATE_OR_UPDATE:
            return text + ". 지우지 않고 표시만 합니다 — 기존 글을 고쳐 쓸지 새 관점으로 쓸지는 직접 정합니다"
        if self.status == ANGLE_NEEDED:
            return text + ". 관점이나 대상 독자를 달리하면 따로 쓸 수 있습니다"
        return text


def compare(candidate, other, cutoffs=DEFAULT_CUTOFFS):
    """후보와 다른 후보(또는 기존 글)를 견주어 `Comparison` 으로 돌려준다. `cutoffs` 는 기준 세 개 또는 후보 채널의 프로필."""
    found = similarity(signature_of(candidate), signature_of(other))
    return Comparison(found, status_of(found.percent, cutoffs), signals_of(candidate, other))


def _best(candidate, record, cutoffs):
    """기존 글은 제목과 원천 주제(있으면) 둘 다로 견주어 더 비슷한 쪽을 쓴다."""
    own = signature_of(candidate)
    options = [similarity(own, signature_of(record))]
    if record.topic:
        options.append(similarity(own, Signature(record.topic, record.keywords)))
    best = max(options, key=lambda found: -1 if found.percent is None else found.percent)
    return Comparison(best, status_of(best.percent, cutoffs), signals_of(candidate, record))


class Match(NamedTuple):
    record: HistoryRecord
    comparison: Comparison


def find_matches(candidate, records, profile, *, limit=3):
    """후보와 **같은 채널**의 기존 글 중 '다른 주제' 보다 비슷한 것을 비슷한 순으로(같으면 최근 날짜·제목·글 번호 순) 최대 `limit` 개 돌려준다. 입력은 바꾸지 않는다."""
    if not isinstance(candidate, TopicCandidate) or not isinstance(profile, ChannelProfile):
        raise TypeError("find_matches(후보, 기존 글 묶음, 채널 프로필) 로 불러야 한다")
    if profile.key != candidate.channel:
        raise ValueError(f"후보의 채널({candidate.channel})과 채널 프로필({profile.key})이 달라 중복 기준을 정할 수 없다")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_MATCHES:
        raise ValueError(f"limit 은 1~{MAX_MATCHES} 사이의 정수여야 한다")
    pool = tuple(records)
    if not all(isinstance(record, HistoryRecord) for record in pool):
        raise TypeError("기존 글(HistoryRecord)만 넘길 수 있다")
    found = [Match(record, _best(candidate, record, profile.dup_cutoffs)) for record in pool if record.channel == candidate.channel]
    kept = [match for match in found if match.comparison.status not in (None, DIFFERENT_TOPIC)]
    ordered = sorted(kept, key=lambda match: (-match.comparison.percent, -(int(match.record.date.replace("-", "")) if match.record.date else 0), match.record.title, match.record.ref or ""))
    return tuple(ordered[:limit])


def marked(candidate, matches):
    """비슷한 글(`find_matches` 의 결과)을 후보의 **표시 칸에만** 적은 새 후보를 돌려준다 — 가장 비슷한 글의 구간을 `duplicate_status` 로(비슷한 글이 없으면 `different_topic`),
    글 번호가 있는 것은 `similar_post_ids` 로. 작업 상태(`work_status`)·점수·추천 구간은 건드리지 않는다(숫자만으로 제외하지 않는다). 원래 후보는 바뀌지 않는다."""
    if not isinstance(candidate, TopicCandidate):
        raise TypeError("marked(후보, 비슷한 글 묶음) 로 불러야 한다")
    pool = tuple(matches)
    if not all(isinstance(match, Match) for match in pool):
        raise TypeError("비슷한 글(Match)만 넘길 수 있다")
    worst = max(pool, key=lambda match: -1 if match.comparison.percent is None else match.comparison.percent, default=None)
    status = worst.comparison.status if worst is not None else DIFFERENT_TOPIC
    refs = tuple(dict.fromkeys(match.record.ref for match in pool if match.record.ref))[:MAX_MATCHES]
    return dataclasses.replace(candidate, duplicate_status=status, similar_post_ids=refs)


# ---- 채널 사이 ------------------------------------------------------------------------------------------------------------------------
CROSS_ITEMS = ("reader", "language", "intent", "angle", "outline", "channel_info", "monetization")
CROSS_ITEM_KO = MappingProxyType({"reader": "대상 독자", "language": "언어", "intent": "검색 의도", "angle": "관점", "outline": "목차", "channel_info": "채널 고유 정보", "monetization": "수익 목적"})
MIN_DIFFERENT_ITEMS = 4                                         # 일곱 항목 중 이만큼 이상 달라야 두 채널에 쓸 수 있다(초기값 — 운영자가 바꿀 수 있다)


class PairExtras(NamedTuple):
    """후보 모델에 없는 두 항목 — 호출하는 쪽이 알 때만 True(다르다)·False(같다)를 적고, 모르면 None."""
    outline_differs: bool | None = None
    channel_info_differs: bool | None = None


NO_EXTRAS = PairExtras()                                        # 목차·채널 고유 정보를 모를 때(둘 다 모름)


class PairVerdict(NamedTuple):
    first: str                                      # 후보 번호
    second: str
    channels: tuple                                 # (첫째 채널, 둘째 채널)
    differing: tuple                                # 달라진 항목(`CROSS_ITEMS` 순서)
    same: tuple                                     # 같은 항목
    unknown: tuple                                  # 모르는 항목(목차·채널 고유 정보를 알려 주지 않았을 때)
    enough: bool                                    # 충분히 다른가(달라진 항목이 `min_different` 이상)


def _monetization_differs(left, right):
    return set(left.monetization_tags) != set(right.monetization_tags)


def compare_across_channels(first, second, *, extras=NO_EXTRAS, min_different=MIN_DIFFERENT_ITEMS):
    """같은 원천 주제에서 나온 두 후보(서로 **다른 채널**)가 충분히 다른지 일곱 항목으로 본다. 같은 채널이면 `ValueError`."""
    if not isinstance(first, TopicCandidate) or not isinstance(second, TopicCandidate) or not isinstance(extras, PairExtras):
        raise TypeError("compare_across_channels(후보, 후보, extras=PairExtras()) 로 불러야 한다")
    if first.channel == second.channel:
        raise ValueError("서로 다른 채널의 후보를 견주는 함수다")
    if not isinstance(min_different, int) or isinstance(min_different, bool) or not 1 <= min_different <= len(CROSS_ITEMS):
        raise ValueError(f"min_different 는 1~{len(CROSS_ITEMS)} 사이의 정수여야 한다")
    answers = {
        "reader": not _same_text(first.target_reader, second.target_reader), "language": first.language != second.language, "intent": first.search_intent != second.search_intent,
        "angle": first.topic_angle != second.topic_angle, "outline": extras.outline_differs, "channel_info": extras.channel_info_differs, "monetization": _monetization_differs(first, second),
    }
    differing = tuple(name for name in CROSS_ITEMS if answers[name] is True)
    unknown = tuple(name for name in CROSS_ITEMS if answers[name] is None)
    same = tuple(name for name in CROSS_ITEMS if answers[name] is False)
    return PairVerdict(first.candidate_id, second.candidate_id, (first.channel, second.channel), differing, same, unknown, len(differing) >= min_different)


class TopicSpread(NamedTuple):
    source_topic_id: str
    channels: tuple                                 # 이 원천 주제를 쓰는 채널(코드 키, 이름순)
    too_many: bool                                  # 채널이 `MAX_CHANNELS_PER_TOPIC`(2) 를 넘는다
    pairs: tuple                                    # 서로 다른 채널 후보 쌍마다의 `PairVerdict`
    allowed: bool                                   # 채널이 2 이하이고 모든 쌍이 충분히 다르다
    problems: tuple                                 # 허용되지 않는 쉬운 한국어 이유


def check_topic_spread(candidates, *, extras=None, min_different=MIN_DIFFERENT_ITEMS):
    """후보들을 원천 주제(`source_topic_id`)별로 묶어 그 주제를 쓰는 채널이 2개 이하인지, 두 채널에 쓰는 후보끼리 충분히 다른지 본다 — 원천 주제 번호가 없는 후보는 건너뛴다.
    `extras` 는 `{(후보 번호 둘을 정렬한 튜플): PairExtras}` 이다(없으면 목차·채널 고유 정보는 모름). 결과는 원천 주제 번호순이다. 입력은 바꾸지 않는다."""
    pool = tuple(candidates)
    if not all(isinstance(item, TopicCandidate) for item in pool):
        raise TypeError("후보(TopicCandidate)만 넘길 수 있다")
    extras = {} if extras is None else extras
    groups = {}
    for item in sorted(pool, key=lambda item: item.candidate_id):
        if item.source_topic_id is not None:
            groups.setdefault(item.source_topic_id, []).append(item)
    spreads = []
    for topic_id in sorted(groups):
        members = groups[topic_id]
        channels = tuple(sorted({item.channel for item in members}))
        pairs = tuple(compare_across_channels(left, right, extras=extras.get(tuple(sorted((left.candidate_id, right.candidate_id))), PairExtras()), min_different=min_different)
                      for left, right in itertools.combinations(members, 2) if left.channel != right.channel)
        problems = []
        if len(channels) > MAX_CHANNELS_PER_TOPIC:
            problems.append(f"같은 주제를 {len(channels)}개 채널에 쓰려 합니다 — 최대 {MAX_CHANNELS_PER_TOPIC}개 채널까지입니다")
        for pair in pairs:
            if not pair.enough:
                names = [_CHANNEL_NAME.get(key, key) for key in pair.channels]
                problems.append(f"{names[0]} 과 {names[1]} 의 후보는 일곱 항목 중 {len(pair.differing)}개만 달라 충분하지 않습니다(최소 {min_different}개)")
        spreads.append(TopicSpread(topic_id, channels, len(channels) > MAX_CHANNELS_PER_TOPIC, pairs, not problems, tuple(problems)))
    return tuple(spreads)


__all__ = [
    "ANGLE_NEEDED", "CROSS_ITEMS", "CROSS_ITEM_KO", "Comparison", "DEFAULT_CUTOFFS", "DIFFERENT_TOPIC", "DUPLICATE_OR_UPDATE", "FILLERS", "MAX_MATCHES", "MIN_DIFFERENT_ITEMS", "Match", "NO_EXTRAS",
    "PARTICLES", "PairExtras", "PairVerdict", "SIGNAL_KO", "SIMILAR_ELEMENTS", "STATUS_KO", "Signals", "Signature", "Similarity", "TopicSpread", "WEIGHT_GRAMS", "WEIGHT_WORDS", "check_topic_spread", "compare",
    "compare_across_channels", "find_matches", "grams_of", "marked", "signals_of", "signature_of", "similarity", "status_of", "words_of",
]
