"""캘린더 — 해마다(또는 한 번) 돌아오는 시기의 준비 시작·발행 기간·피크·반복 규칙·마지막 평가일과 `calendar.json` 모양, 그리고 후보의 **시기 상태**(`due`·`out_of_range`·`unknown`) 계산
(순수 계산 — 파일·네트워크·시계·난수 없음. 날짜는 늘 인자로 받는다).

캘린더 항목 하나 = 이름 + 이 시기와 이어지는 낱말들 + 준비 시작 + 발행 기간(시작·끝, 끝날도 포함) + 피크(있으면) + 반복(`yearly` 매년·`once` 한 해만) + 마지막 평가일 + 적용 채널(비면 모든 채널).
  · 날짜는 `MM-DD`(예: `11-15`)다. 2월 29일은 쓰지 않는다(해마다 같은 날이 있도록). 발행 기간의 끝이 시작보다 앞서면 해를 넘기는 기간이다(`12-20` → `01-10`).
  · 준비 시작은 발행 시작보다 `MAX_LEAD_DAYS`(180)일 이내로 앞서고(같은 날도 된다), 발행 기간은 `MAX_WINDOW_DAYS`(183)일을 넘지 않으며, 피크는 발행 기간 안이어야 한다.
    준비 시작일도 발행 시작·끝·피크처럼 **달력의 `MM-DD` 날짜 그대로**다(윤년에도 같은 달·일 — P2b, 독립 검증 L2 가 '윤년에 하루 어긋남' 을 고쳤다). 180일·183일 한도만 평년(2월 28일까지) 날수로 잰다 — 윤년에는 실제 날수가 하루 더 길 수 있다.
  · `once` 항목은 `year`(발행 기간이 시작하는 해)가 꼭 있고 그 한 번만 돈다. `yearly` 항목에는 `year` 가 없다.
**시기 상태**(P1 `score.timing_score` 의 첫 입력 `calendar`): 후보의 글(주제·핵심 키워드·보조 키워드)에 항목의 낱말이 있으면 그 항목이 후보에 해당한다 —
  해당하는 항목의 발행 기간 안이면 `due`, 해당 항목은 있지만 모두 발행 기간 밖이면(준비 중이거나 지난·아직 안 온 시기) `out_of_range`, 해당하는 항목이 하나도 없으면 `unknown`(캘린더에 없음 — 0 이 아니라 '모름').
  낱말은 **낱말 통째**로만 맞춘다(한글 낱말 끝의 조사만 떼고 — `dedupe.words_of` 와 같은 규칙, 띄어 쓴 구문은 낱말이 나란히 있어야 한다): '카드' 는 '그래픽카드'·'카드뮴' 에 걸리지 않는다(D-42 의 교훈).
기존 월별 시기 표(`content/suggest_data.py` 의 `SEASONS`)는 그대로 두고 읽지도 않는다 — 이 캘린더는 같은 시기 낱말에 준비 시작·발행 기간·피크·반복·평가일을 더해 날짜 단위로 `due` 를 계산하며, 낱말이 겹칠 수 있다(표는 기존 5요인 우선도에만, 캘린더는 새 시기 항목에만 쓰인다).
읽고 쓰기는 사전(dict)까지만이고(`entries_to_dict`·`entries_from_dict`, `schema` 1, 엄격 — 모르는 칸·잘못된 타입·같은 번호 두 번은 `CONTENT_INVALID`) 파일은 다음 묶음의 몫이다. 실제 캘린더는 저장소에 두지 않는다.

P3b-1(2026-11-06 운영자 결정 4·6)이 이 모듈에 더한 것 둘 — 둘 다 순수 계산이고 시계를 읽지 않는다(날짜는 부르는 쪽이 넘긴다):
  · **점검 주기 상수 넷과 '다음 점검일'**(`SEASONAL_CALENDAR_REVIEW_DAYS` 7 · `LONG_TERM_SEED_REVIEW_DAYS` 30 · `HOLD_CANDIDATE_REVIEW_DAYS` 30 · `SEED_INACTIVE_REVIEW_DAYS` 180, `review_due`·`review_dues`). 예전 `EVALUATION_DAYS`(30)는
    '계절 캘린더 점검' 과 '장기 씨앗 재평가' 를 겸했다 — 이름은 호환용으로 남기고 값은 `LONG_TERM_SEED_REVIEW_DAYS` 와 같다. 자동 실행은 없다: 점검일은 사용자가 주제 분석(`topics generate --yes`)을 실행할 때만 기록된다.
  · **계절·월별 씨앗의 일정과 그날의 계절 상태**(`season_problem`·`season_state`·`seasonal_state`) — 씨앗이 직접 가진 준비 시작일·발행 시작일·발행 종료일(해를 넘길 수 있다, 2월 29일 없음)로 오늘이 시즌 밖(`off_season` — 활성은 그대로 두고 우선순위만 낮춤)·
    준비 중(`preparing` — 일반 우선순위)·발행 기간(`publishing` — 관심도와 함께 우선 추천 평가)인지 계산한다. 반복은 매년(`yearly`, `MM-DD`)과 매월(`monthly`, 날짜 `DD` — 1~28일)이다. 시즌 밖이라고 씨앗을 비활성화하거나 후보 생성에서 빼지 않는다.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import NamedTuple

from ..content.candidates import _ID, forbidden_claim
from ..content.profiles import _no_markup, _text, _words
from ..errors import AppError
from . import wording
from .channels import CHANNELS, at_entry, explain, invalid_in
from .dedupe import words_of
from .history import valid_day
from .model import TopicCandidate
from .score import CALENDAR_DUE, CALENDAR_OUT_OF_RANGE, CALENDAR_UNKNOWN

SCHEMA = 1
SUBJECT = "캘린더"

REPEAT_YEARLY, REPEAT_ONCE = "yearly", "once"
REPEATS = (REPEAT_YEARLY, REPEAT_ONCE)
REPEAT_KO = MappingProxyType({REPEAT_YEARLY: "매년", REPEAT_ONCE: "한 번만"})
PHASE_PREPARING, PHASE_PUBLISHING, PHASE_OUTSIDE = "preparing", "publishing", "outside"      # 준비 중·발행 기간 안·그 밖(아직 안 왔거나 지났다)
PHASES = (PHASE_PREPARING, PHASE_PUBLISHING, PHASE_OUTSIDE)

MAX_LEAD_DAYS = 180
MAX_WINDOW_DAYS = 183
# 점검 주기 넷(2026-11-06 운영자 결정 4 — 원문 §27 의 자동 실행 주기 표를 값으로만 옮겼다. 자동으로 돌지 않고 사용자가 주제 분석을 시작할 때만 점검일이 기록된다)
SEASONAL_CALENDAR_REVIEW_DAYS = 7                       # 계절 캘린더 점검 — 원문 '주 1회'
LONG_TERM_SEED_REVIEW_DAYS = 30                         # 장기 씨앗 재평가 — 원문 '월 1회'
HOLD_CANDIDATE_REVIEW_DAYS = 30                         # 보류 후보 재평가 — 원문 '월 1회'
SEED_INACTIVE_REVIEW_DAYS = 180                         # 씨앗 비활성 검토 — 원문 '180일'(`seeds.IDLE_DAYS` 가 이 값을 그대로 쓴다 — 숫자가 두 곳에 흩어지지 않게)
EVALUATION_DAYS = LONG_TERM_SEED_REVIEW_DAYS            # 호환 이름(옛 '월 재평가' 30일 — 계절 캘린더 점검과 장기 씨앗 재평가를 겸했다). 새 코드는 위 넷 중 알맞은 것을 쓴다
MAX_ENTRIES = 500
MAX_KEYWORDS = 10
MAX_KEYWORD = 30
MAX_NAME = 30
MIN_YEAR, MAX_YEAR = 2000, 2200

_KEYS = ("entry_id", "name", "keywords", "prep_start", "publish_from", "publish_to", "peak", "repeat", "year", "last_evaluated_on", "channels")
ENTRY_FIELD_KO = MappingProxyType({"entry_id": "항목 번호", "name": "이름", "keywords": "시기 낱말", "prep_start": "준비 시작", "publish_from": "발행 기간 시작", "publish_to": "발행 기간 끝",
                                   "peak": "피크", "repeat": "반복", "year": "해", "last_evaluated_on": "마지막 평가일", "channels": "적용 채널"})        # 칸 이름 → 쉬운 한국어(오류 안내용)


def _invalid(item, detail="", *, dev=""):
    return invalid_in(SUBJECT, item, detail, dev=dev)


class MonthDay(NamedTuple):
    month: int
    day: int


def parse_month_day(text):
    """`MM-DD`(두 자리씩, 2월 29일은 없다) → `MonthDay`. 아니면 None."""
    if not isinstance(text, str) or len(text) != 5 or text[2] != "-" or not (text[:2] + text[3:]).isascii() or not (text[:2] + text[3:]).isdigit():
        return None
    try:
        date(2001, int(text[:2]), int(text[3:]))
    except ValueError:
        return None
    return MonthDay(int(text[:2]), int(text[3:]))


def _month_day(value, item, *, optional=False):
    if value is None and optional:
        return None
    found = parse_month_day(value)
    if found is None:
        raise _invalid(item, "11-15 같은 월-일 모양이어야 한다(2월 29일은 쓰지 않는다)")
    return found


def _span(first, last):
    """같은 달력(2001·2002)에서 `first` 부터 `last` 까지의 날수(끝날 포함) — `last` 가 앞서면 해를 넘기는 기간이다."""
    start = date(2001, first.month, first.day)
    end = date(2001 if last >= first else 2002, last.month, last.day)
    return (end - start).days + 1


@dataclass(frozen=True, kw_only=True)
class CalendarEntry:
    entry_id: str                                   # 항목 번호(영문·숫자·밑줄·붙임표 1~64자) — 만드는 쪽이 정한다
    name: str                                       # 이름(화면에 보일 한 줄, 1~30자)
    keywords: tuple                                 # 이 시기와 이어지는 낱말들(1~10개) — 후보의 글과 낱말 통째로 맞춘다
    prep_start: str                                 # 준비 시작 MM-DD
    publish_from: str                               # 발행 기간 시작 MM-DD
    publish_to: str                                 # 발행 기간 끝 MM-DD(끝날 포함, 시작보다 앞서면 해를 넘긴다)
    repeat: str                                     # yearly·once
    peak: str | None = None                         # 피크 MM-DD(발행 기간 안)
    year: int | None = None                         # once 일 때 발행 기간이 시작하는 해(필수) — yearly 면 None
    last_evaluated_on: str | None = None            # 마지막 평가일 YYYY-MM-DD
    channels: tuple = ()                            # 적용 채널(코드 키) — 비면 모든 채널

    def __post_init__(self):
        try:
            self._check()
        except AppError as error:
            raise explain(SUBJECT, error) from None

    def _check(self):
        def put(name, value):
            object.__setattr__(self, name, value)

        if not isinstance(self.entry_id, str) or not _ID.fullmatch(self.entry_id):
            raise _invalid("항목 번호", "영문·숫자·밑줄(_)·붙임표(-) 1~64자여야 한다")
        put("name", _no_markup(_text(self.name, "이름", low=1, high=MAX_NAME), "이름"))
        words = _words(self.keywords, "시기 낱말", count=MAX_KEYWORDS, high=MAX_KEYWORD, sequence_only=True, markup_free=True)
        if not words or not all(words_of(word, filtered=False) for word in words):
            raise _invalid("시기 낱말", "글자나 숫자가 있는 낱말이 1개 이상 있어야 한다")
        for label, shown in (("이름", self.name), *(("시기 낱말", word) for word in words)):
            claim = forbidden_claim(shown)
            if claim:
                raise _invalid(label, f"‘{claim[0]}’ 같은 결과를 약속하는 표현은 쓸 수 없다")
        put("keywords", words)
        prep, first, last = (_month_day(getattr(self, name), label) for name, label in (("prep_start", "준비 시작"), ("publish_from", "발행 기간 시작"), ("publish_to", "발행 기간 끝")))
        lead = (date(2001, first.month, first.day) - date(2001, prep.month, prep.day)).days % 365
        if lead > MAX_LEAD_DAYS:
            raise _invalid("준비 시작", f"발행 기간 시작보다 앞서야 하고 {MAX_LEAD_DAYS}일을 넘게 앞설 수 없다(지금은 {lead}일 앞)")
        length = _span(first, last)
        if length > MAX_WINDOW_DAYS:
            raise _invalid("발행 기간", f"{MAX_WINDOW_DAYS}일을 넘을 수 없다(지금은 {length}일)")
        peak = _month_day(self.peak, "피크", optional=True)
        if peak is not None and _span(first, peak) > length:
            raise _invalid("피크", "발행 기간 안이어야 한다")
        if not isinstance(self.repeat, str) or self.repeat not in REPEATS:
            raise _invalid("반복", wording.one_of(REPEATS, REPEAT_KO), dev="값: " + ", ".join(REPEATS))
        if self.repeat == REPEAT_ONCE:
            if not isinstance(self.year, int) or isinstance(self.year, bool) or not MIN_YEAR <= self.year <= MAX_YEAR:
                raise _invalid("해", f"한 번만 도는 항목은 {MIN_YEAR}~{MAX_YEAR} 사이의 해(정수)가 꼭 있어야 한다")
        elif self.year is not None:
            raise _invalid("해", "매년 도는 항목에는 해를 적지 않는다")
        if self.last_evaluated_on is not None and (valid_day(self.last_evaluated_on) is None or int(self.last_evaluated_on[:4]) > MAX_YEAR):
            raise _invalid("마지막 평가일", f"2026-11-05 같은 모양의 달력에 있는 날짜({MIN_YEAR}~{MAX_YEAR}년)이거나 비워 두어야 한다")
        if not isinstance(self.channels, (list, tuple)):
            raise _invalid("적용 채널", "목록이어야 한다")
        codes = tuple(self.channels)
        if not all(isinstance(code, str) and code in CHANNELS for code in codes) or len(set(codes)) != len(codes):
            raise _invalid("적용 채널", "채널은 " + wording.quoted(CHANNELS, names=wording.CHANNEL_KO) + " 중에서 한 번씩만 쓸 수 있습니다", dev="코드의 채널 이름: " + ", ".join(CHANNELS))
        put("channels", codes)

    def to_dict(self):
        return {"entry_id": self.entry_id, "name": self.name, "keywords": list(self.keywords), "prep_start": self.prep_start, "publish_from": self.publish_from, "publish_to": self.publish_to,
                "peak": self.peak, "repeat": self.repeat, "year": self.year, "last_evaluated_on": self.last_evaluated_on, "channels": list(self.channels)}

    @classmethod
    def from_dict(cls, data):
        """저장된 모양을 엄격하게 읽는다 — 정확히 이 칸들이어야 하고(모르는 칸·빠진 칸 거절) 값은 `__post_init__` 이 검사한다."""
        if not isinstance(data, dict):
            raise _invalid("모양", "칸이 있는 묶음(JSON 객체)이어야 한다")
        unknown, missing = sorted(map(str, set(data) - set(_KEYS))), sorted(set(_KEYS) - set(data))
        if unknown or missing:
            raise _invalid("모양", wording.unknown_and_missing(unknown, missing, ENTRY_FIELD_KO), dev=f"모르는 칸 {unknown}, 빠진 칸 {missing}")
        return cls(**data)

    def applies_to(self, channel):
        """이 항목이 `channel`(코드 키) 에 적용되는가 — 적용 채널이 비어 있으면 모든 채널."""
        return not self.channels or channel in self.channels


# ---- 날짜 계산 ------------------------------------------------------------------------------------------------------------------------
class Cycle(NamedTuple):
    prep_start: str                                 # 준비 시작일(YYYY-MM-DD)
    start: str                                      # 발행 기간 시작일
    end: str                                        # 발행 기간 끝일(포함)
    peak: str | None                                # 피크일


def _day_of(text, item="날짜"):
    if valid_day(text) is None:
        raise _invalid(item, "2026-11-05 같은 모양의 달력에 있는 날짜(2000년 이후)여야 한다")
    found = date.fromisoformat(text)
    if found.year > MAX_YEAR:
        raise _invalid(item, f"{MAX_YEAR}년 이전이어야 한다")
    return found


def _dates(entry, start_year):
    first, last = parse_month_day(entry.publish_from), parse_month_day(entry.publish_to)
    start = date(start_year, first.month, first.day)
    end = date(start_year if last >= first else start_year + 1, last.month, last.day)
    prep = parse_month_day(entry.prep_start)
    prep_day = date(start_year if prep <= first else start_year - 1, prep.month, prep.day)         # 준비 시작도 달력 날짜 그대로(발행 시작보다 앞서면 지난해)
    peak = parse_month_day(entry.peak) if entry.peak is not None else None
    peak_day = None if peak is None else date(start_year if peak >= first else start_year + 1, peak.month, peak.day)
    return prep_day, start, end, peak_day


def cycle_of(entry, year):
    """발행 기간이 `year` 년에 **시작하는** 주기의 날짜들(`Cycle`). `once` 항목은 자기 해에만 있고 다른 해는 None 이다."""
    if not isinstance(entry, CalendarEntry):
        raise TypeError("캘린더 항목(CalendarEntry)이어야 한다")
    if not isinstance(year, int) or isinstance(year, bool) or not MIN_YEAR <= year <= MAX_YEAR:
        raise _invalid("해", f"{MIN_YEAR}~{MAX_YEAR} 사이의 정수여야 한다")
    if entry.repeat == REPEAT_ONCE and entry.year != year:
        return None
    prep, start, end, peak = _dates(entry, year)
    return Cycle(prep.isoformat(), start.isoformat(), end.isoformat(), None if peak is None else peak.isoformat())


def phase_of(entry, on):
    """`on`(YYYY-MM-DD)이 이 항목의 어느 단계인가 — 발행 기간 안(`publishing`, 시작·끝날 포함)·준비 중(`preparing`, 준비 시작일부터 발행 시작 전날까지)·그 밖(`outside`).
    `once` 항목은 자기 해의 주기만 본다. 시계를 읽지 않는다."""
    if not isinstance(entry, CalendarEntry):
        raise TypeError("캘린더 항목(CalendarEntry)이어야 한다")
    today = _day_of(on, "오늘 날짜")
    years = (entry.year,) if entry.repeat == REPEAT_ONCE else range(today.year - 1, today.year + 2)
    for year in years:
        prep, start, end, _peak = _dates(entry, year)
        if start <= today <= end:
            return PHASE_PUBLISHING
        if prep <= today < start:
            return PHASE_PREPARING
    return PHASE_OUTSIDE


# ---- 후보의 시기 상태 ---------------------------------------------------------------------------------------------------------------
class EntryPhase(NamedTuple):
    entry_id: str
    name: str
    phase: str


class CalendarState(NamedTuple):
    state: str                                      # `score.CALENDAR_STATES` 중 하나: due·out_of_range·unknown — `score.timing_score` 의 첫 입력으로 그대로 넘긴다
    matched: tuple                                  # 후보에 해당한 항목들(`EntryPhase`, 항목 번호순)


def _mentions(token_lists, keyword):
    """글마다 나눈 낱말 목록(`token_lists`) 중 하나라도 `keyword`(낱말이나 띄어 쓴 구문)가 낱말 통째로 나란히 들어 있으면 True."""
    need = words_of(keyword, filtered=False)
    if not need:
        return False
    for have in token_lists:
        if any(have[index:index + len(need)] == need for index in range(len(have) - len(need) + 1)):
            return True
    return False


def calendar_state(entries, texts, on, channel=None):
    """후보의 글(`texts` — 주제·핵심 키워드·보조 키워드 같은 글 몇 개)과 오늘(`on`)로 시기 상태를 구한다. 항목의 낱말이 글에 낱말 통째로 있으면 그 항목이 해당한다(`channel` 을 주면 그 채널에 적용되는 항목만).
    해당 항목 중 하나라도 발행 기간 안이면 `due`, 해당 항목은 있지만 모두 밖이면 `out_of_range`, 해당 항목이 없으면 `unknown`(캘린더에 없음 — 0 이 아니다)."""
    pool = tuple(entries)
    if not all(isinstance(entry, CalendarEntry) for entry in pool):
        raise TypeError("캘린더 항목(CalendarEntry)만 넘길 수 있다")
    if isinstance(texts, (str, bytes)) or not hasattr(texts, "__iter__"):
        raise TypeError("texts 는 글의 목록이어야 한다")
    pieces = tuple(texts)
    if not all(isinstance(piece, str) for piece in pieces):
        raise TypeError("texts 에는 글만 들어 있어야 한다")
    if channel is not None and (not isinstance(channel, str) or channel not in CHANNELS):
        raise ValueError("channel 은 코드의 채널 이름이거나 None 이어야 한다: " + ", ".join(CHANNELS))
    _day_of(on, "오늘 날짜")
    token_lists = [words_of(piece, filtered=False) for piece in pieces]                  # 글마다 한 번만 나눈다
    matched = [EntryPhase(entry.entry_id, entry.name, phase_of(entry, on)) for entry in sorted(pool, key=lambda item: item.entry_id)
               if (channel is None or entry.applies_to(channel)) and any(_mentions(token_lists, keyword) for keyword in entry.keywords)]
    if not matched:
        return CalendarState(CALENDAR_UNKNOWN, ())
    due = any(item.phase == PHASE_PUBLISHING for item in matched)
    return CalendarState(CALENDAR_DUE if due else CALENDAR_OUT_OF_RANGE, tuple(matched))


def state_of(candidate, entries, on):
    """엔진 후보의 시기 상태 — 후보의 주제·핵심 키워드·보조 키워드와 채널로 `calendar_state` 를 부른다."""
    if not isinstance(candidate, TopicCandidate):
        raise TypeError("엔진 후보(TopicCandidate)여야 한다")
    return calendar_state(entries, (candidate.topic, candidate.primary_keyword, *candidate.secondary_keywords), on, candidate.channel)


# ---- 마지막 평가일 ---------------------------------------------------------------------------------------------------------------
def evaluation_age(entry, today):
    """마지막 평가일로부터 `today` 까지의 날수. 한 번도 평가하지 않았으면 None(모름 — 0 이 아니다). 평가일이 오늘보다 뒤이면 0 이다."""
    if not isinstance(entry, CalendarEntry):
        raise TypeError("캘린더 항목(CalendarEntry)이어야 한다")
    now = _day_of(today, "오늘 날짜")
    if entry.last_evaluated_on is None:
        return None
    return max(0, (now - date.fromisoformat(entry.last_evaluated_on)).days)


def needs_evaluation(entry, today, max_age_days=EVALUATION_DAYS):
    """다시 평가할 때인가 — 한 번도 평가하지 않았거나 마지막 평가일로부터 `max_age_days`일(기본 30, 포함) 이상 지났다."""
    if not isinstance(max_age_days, int) or isinstance(max_age_days, bool) or not 1 <= max_age_days <= 3650:
        raise _invalid("재평가 간격", "1~3650 사이의 정수여야 한다")
    age = evaluation_age(entry, today)
    return age is None or age >= max_age_days


# ---- 점검 주기와 다음 점검일(P3b-1) --------------------------------------------------------------------------------------------------------
REVIEW_KINDS = ("seasonal_calendar", "long_term_seed", "hold_candidate", "seed_inactive")        # 점검 종류 넷 — 순서가 화면·상태 출력의 순서다
REVIEW_DAYS = MappingProxyType({"seasonal_calendar": SEASONAL_CALENDAR_REVIEW_DAYS, "long_term_seed": LONG_TERM_SEED_REVIEW_DAYS, "hold_candidate": HOLD_CANDIDATE_REVIEW_DAYS,
                                "seed_inactive": SEED_INACTIVE_REVIEW_DAYS})
REVIEW_NEVER, REVIEW_SCHEDULED, REVIEW_DUE, REVIEW_OVERDUE = "never", "scheduled", "due", "overdue"      # 한 번도 안 함·아직 안 됨·오늘이 점검일·기한이 지남
REVIEW_STATES = (REVIEW_NEVER, REVIEW_SCHEDULED, REVIEW_DUE, REVIEW_OVERDUE)
REVIEW_STATE_KO = MappingProxyType({REVIEW_NEVER: "지금 점검할 수 있음(아직 점검한 적이 없음)", REVIEW_SCHEDULED: "아직 점검할 때가 아님", REVIEW_DUE: "오늘이 점검일", REVIEW_OVERDUE: "점검 기한이 지남"})


class ReviewDue(NamedTuple):
    kind: str                                       # `REVIEW_KINDS` 중 하나
    period_days: int                                # 점검 주기(날)
    last_run_on: str | None                         # 마지막 점검일(없으면 None — 한 번도 점검한 적이 없다)
    next_due_on: str | None                         # 다음 점검일 = 마지막 점검일 + 주기(한 번도 안 했으면 None)
    state: str                                      # `REVIEW_STATES` 중 하나
    days_left: int | None                           # 남은 날수(오늘이 점검일이면 0·지났으면 음수·한 번도 안 했으면 None)


def review_due(kind, last_run_on, today):
    """점검 하나의 다음 점검일 — `last_run_on`(마지막 점검일 YYYY-MM-DD 또는 None) + 그 점검의 주기. 한 번도 점검하지 않았으면 '지금 점검할 수 있음'(`never`), 오늘이 점검일이면 `due`, 지났으면 `overdue`(**표시만 한다** —
    아무것도 자동으로 하지 않고 지우거나 바꾸지도 않는다). 기록이 오늘보다 뒤인 날짜(시계가 틀렸던 흔적)여도 그대로 더해 `scheduled` 로 보인다. 오늘을 읽지 않고 부르는 쪽이 `today` 를 넘긴다."""
    if not isinstance(kind, str) or kind not in REVIEW_DAYS:
        raise ValueError("점검 종류는 다음 중 하나여야 한다: " + ", ".join(REVIEW_KINDS))
    now = _day_of(today, "오늘 날짜")
    days = REVIEW_DAYS[kind]
    if last_run_on is None:
        return ReviewDue(kind, days, None, None, REVIEW_NEVER, None)
    last = _day_of(last_run_on, "마지막 점검일")
    try:
        due = last + timedelta(days=days)
    except OverflowError:
        raise _invalid("마지막 점검일", "너무 먼 미래라 다음 점검일을 계산할 수 없습니다") from None
    left = (due - now).days
    state = REVIEW_OVERDUE if left < 0 else REVIEW_DUE if left == 0 else REVIEW_SCHEDULED
    return ReviewDue(kind, days, last_run_on, due.isoformat(), state, left)


def review_dues(log, today):
    """네 점검의 다음 점검일(`REVIEW_KINDS` 순서) — `log` 는 {점검 종류: 마지막 점검일} 사전이다(없는 종류는 한 번도 안 한 것). 모르는 종류가 들어 있으면 ValueError."""
    if not isinstance(log, dict) or not set(log) <= set(REVIEW_KINDS):
        raise ValueError("점검 기록은 {점검 종류: 마지막 점검일} 사전이어야 한다(종류: " + ", ".join(REVIEW_KINDS) + ")")
    return tuple(review_due(kind, log.get(kind), today) for kind in REVIEW_KINDS)


# ---- 계절·월별 씨앗의 일정과 그날의 상태(P3b-1) ----------------------------------------------------------------------------------------------
RECURRENCE_YEARLY, RECURRENCE_MONTHLY = "yearly", "monthly"          # 매년(`MM-DD`)·매월(`DD`) — 원문 '월별'(§8.1·§11)은 매월 반복이 맡는다
RECURRENCES = (RECURRENCE_YEARLY, RECURRENCE_MONTHLY)
SEASON_OFF, SEASON_PREPARING, SEASON_PUBLISHING = "off_season", "preparing", "publishing"
SEASON_STATES = (SEASON_OFF, SEASON_PREPARING, SEASON_PUBLISHING)       # 시즌 밖(활성 유지·우선순위만 낮춤)·준비 중(일반 우선순위)·발행 기간(우선 추천 평가)
MONTH_DAY_MAX = 28                                      # 매월 반복의 날짜는 1~28일 — 어느 달에도 있는 날(2월 29일을 쓰지 않는 것과 같은 까닭이다)
MAX_MONTHLY_WINDOW = 28


def parse_day_of_month(text):
    """`DD`(두 자리, 01~28 — 어느 달에도 있는 날) → 정수. 아니면 None."""
    if not isinstance(text, str) or len(text) != 2 or not text.isascii() or not text.isdigit() or not 1 <= int(text) <= MONTH_DAY_MAX:
        return None
    return int(text)


def _next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _prev_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _monthly_offset(first, day):
    """매월 반복에서 발행 시작일(`first`)부터 `day` 까지의 날수(끝날 포함) — `day` 가 앞서면 다음 달로 넘어간 것으로 보고 한 달을 28일로 센다(어느 달에도 있는 날만 쓰므로 근사가 아니라 약속이다)."""
    return (day - first + 1) if day >= first else (MONTH_DAY_MAX - first + 1) + day


def season_problem(recurrence, prepare_from, publish_from, publish_until, peak_period=None):
    """씨앗이 가진 계절 일정이 규칙에 맞는가 — 맞으면 None, 아니면 (칸 이름, 쉬운 말 이유). 매년은 캘린더 항목과 같은 규칙이다(준비 시작은 발행 시작보다 180일 이내로 앞서고·발행 기간은 183일 이하·피크는 발행 기간 안, 2월 29일 없음).
    매월은 날짜 `DD`(01~28)이고 발행 종료일이 시작일보다 앞서면 다음 달로 넘어가는 기간이다(준비 시작일이 발행 시작일보다 크면 앞선 달의 날이다). 피크(`peak_period` = (시작, 끝))는 있으면 발행 기간 안이어야 한다."""
    names = (("준비 시작일", prepare_from), ("발행 시작일", publish_from), ("발행 종료일", publish_until))
    if recurrence == RECURRENCE_YEARLY:
        parsed = [parse_month_day(value) for _label, value in names]
        for (label, _value), found in zip(names, parsed, strict=True):
            if found is None:
                return label, "11-15 같은 월-일 모양이어야 한다(2월 29일은 쓰지 않는다)"
        prep, first, last = parsed
        lead = (date(2001, first.month, first.day) - date(2001, prep.month, prep.day)).days % 365
        if lead > MAX_LEAD_DAYS:
            return "준비 시작일", f"발행 시작일보다 앞서야 하고 {MAX_LEAD_DAYS}일을 넘게 앞설 수 없다(지금은 {lead}일 앞)"
        length = _span(first, last)
        if length > MAX_WINDOW_DAYS:
            return "발행 기간", f"{MAX_WINDOW_DAYS}일을 넘을 수 없다(지금은 {length}일)"
        if peak_period is not None:
            ends = [parse_month_day(value) for value in peak_period]
            if None in ends:
                return "피크 기간", "11-15 같은 월-일 두 개(시작·끝)여야 한다(2월 29일은 쓰지 않는다)"
            starts, finishes = _span(first, ends[0]), _span(first, ends[1])
            if starts > length or finishes > length or starts > finishes:
                return "피크 기간", "발행 기간 안이어야 하고 끝이 시작보다 앞설 수 없다"
        return None
    if recurrence == RECURRENCE_MONTHLY:
        parsed = [parse_day_of_month(value) for _label, value in names]
        for (label, _value), found in zip(names, parsed, strict=True):
            if found is None:
                return label, f"15 같은 두 자리 날짜(01~{MONTH_DAY_MAX}일)여야 한다"
        _prep, first, last = parsed
        length = _monthly_offset(first, last)
        if length > MAX_MONTHLY_WINDOW:
            return "발행 기간", f"{MAX_MONTHLY_WINDOW}일을 넘을 수 없다(지금은 {length}일)"
        if peak_period is not None:
            ends = [parse_day_of_month(value) for value in peak_period]
            if None in ends:
                return "피크 기간", f"15 같은 두 자리 날짜 두 개(시작·끝, 01~{MONTH_DAY_MAX}일)여야 한다"
            starts, finishes = _monthly_offset(first, ends[0]), _monthly_offset(first, ends[1])
            if starts > length or finishes > length or starts > finishes:
                return "피크 기간", "발행 기간 안이어야 하고 끝이 시작보다 앞설 수 없다"
        return None
    return "반복", "매년(yearly)이거나 매월(monthly)이어야 한다"


def _season_cycles(recurrence, prepare_from, publish_from, publish_until, today):
    """오늘 둘레의 주기들(앞뒤 하나씩 더) → [(준비 시작일, 발행 시작일, 발행 종료일)]. 매년은 발행 기간이 시작하는 해, 매월은 발행 기간이 시작하는 달로 주기를 나눈다."""
    cycles = []
    if recurrence == RECURRENCE_YEARLY:
        prep, first, last = (parse_month_day(value) for value in (prepare_from, publish_from, publish_until))
        for year in range(today.year - 1, today.year + 2):
            start = date(year, first.month, first.day)
            end = date(year if last >= first else year + 1, last.month, last.day)
            prep_day = date(year if prep <= first else year - 1, prep.month, prep.day)
            cycles.append((prep_day, start, end))
        return cycles
    prep, first, last = (parse_day_of_month(value) for value in (prepare_from, publish_from, publish_until))
    year, month = _prev_month(today.year, today.month)
    for _round in range(3):
        start = date(year, month, first)
        end_year, end_month = (year, month) if last >= first else _next_month(year, month)
        prep_year, prep_month = (year, month) if prep <= first else _prev_month(year, month)
        cycles.append((date(prep_year, prep_month, prep), start, date(end_year, end_month, last)))
        year, month = _next_month(year, month)
    return cycles


def season_state(recurrence, prepare_from, publish_from, publish_until, today):
    """그날(`today` — `YYYY-MM-DD`)의 계절 상태: 발행 기간 안(시작·끝날 포함)이면 `publishing`, 준비 시작일부터 발행 시작 전날까지면 `preparing`, 그 밖(아직 안 왔거나 시즌이 끝났다)이면 `off_season`.
    일정은 `season_problem` 이 None 이어야 한다(아니면 ValueError). 시계를 읽지 않는다."""
    if season_problem(recurrence, prepare_from, publish_from, publish_until) is not None:
        raise ValueError("계절 일정이 규칙에 맞지 않는다")
    now = _day_of(today, "오늘 날짜")
    for prep, start, end in _season_cycles(recurrence, prepare_from, publish_from, publish_until, now):
        if start <= now <= end:
            return SEASON_PUBLISHING
        if prep <= now < start:
            return SEASON_PREPARING
    return SEASON_OFF


def seasonal_state(seed, today):
    """씨앗(`seeds.Seed`)의 그날 계절 상태 — 계절 일정(준비 시작일·발행 시작일·발행 종료일·반복)이 없는 씨앗(판 1 의 계절 씨앗·계절이 아닌 씨앗)은 None 이다(옛 규칙 — 캘린더 항목으로만 시기를 본다).
    **'시즌 밖' 이어도 씨앗을 쉬게 하거나 후보 생성에서 빼지 않는다** — 활성은 그대로이고 현재 우선순위만 낮다(운영자 결정 6). 사용자가 직접 쉬게 한 씨앗만 후보 생성에서 빠진다."""
    if getattr(seed, "recurrence", None) is None or getattr(seed, "publish_from", None) is None:
        return None
    return season_state(seed.recurrence, seed.prepare_from, seed.publish_from, seed.publish_until, today)


# ---- calendar.json 모양 ----------------------------------------------------------------------------------------------------------------
def entries_to_dict(entries):
    """캘린더 항목들 → 저장 모양(`schema` 1, 입력 순서 그대로). 빈 목록이 '빈 틀' 이다."""
    pool = tuple(entries)
    _check_all(pool)
    return {"schema": SCHEMA, "entries": [entry.to_dict() for entry in pool]}


def entries_from_dict(data):
    """저장된 모양 → 캘린더 항목들(파일 순서). `schema`·정확한 칸을 요구하고 모르는 칸·틀린 값·같은 번호 두 번·`MAX_ENTRIES` 초과는 `CONTENT_INVALID` 로 거절한다."""
    item = "캘린더 저장 형식"
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != SCHEMA:
        raise _invalid(item, f"{wording.FILE_KEY_KO['schema']}가 {SCHEMA}인 캘린더 파일이 아닙니다", dev="저장된 캘린더의 모양(schema 1)이 아니다")
    if set(data) != {"schema", "entries"}:
        raise _invalid(item, wording.quoted(("schema", "entries"), names=wording.FILE_KEY_KO) + " 두 칸만 있어야 합니다", dev="schema 와 entries 두 칸만 있어야 한다")
    raw = data["entries"]
    if not isinstance(raw, list):
        raise _invalid(item, f"{wording.quote(wording.FILE_KEY_KO['entries'])} 은 여러 개를 담는 목록이어야 합니다", dev="entries 는 목록이어야 한다")
    if len(raw) > MAX_ENTRIES:
        raise _invalid(item, f"항목은 {MAX_ENTRIES}개까지다")
    made = []
    for number, entry in enumerate(raw, start=1):
        try:
            made.append(CalendarEntry.from_dict(entry))
        except AppError as error:
            raise at_entry(SUBJECT, number, error) from None
    pool = tuple(made)
    _check_all(pool)
    return pool


def _check_all(pool):
    if not all(isinstance(entry, CalendarEntry) for entry in pool):
        raise _invalid("캘린더 목록", "캘린더 항목(CalendarEntry)만 들어 있어야 한다")
    if len(pool) > MAX_ENTRIES:
        raise _invalid("캘린더 목록", f"항목은 {MAX_ENTRIES}개까지다")
    twice = sorted(name for name, count in Counter(entry.entry_id for entry in pool).items() if count > 1)
    if twice:
        raise _invalid("캘린더 목록", "같은 항목 번호가 두 번 들어 있습니다: " + wording.quoted(twice), dev=f"겹친 번호: {twice}")


__all__ = [
    "CalendarEntry", "CalendarState", "Cycle", "EVALUATION_DAYS", "EntryPhase", "HOLD_CANDIDATE_REVIEW_DAYS", "LONG_TERM_SEED_REVIEW_DAYS", "MAX_ENTRIES", "MAX_LEAD_DAYS", "MAX_WINDOW_DAYS", "MONTH_DAY_MAX", "MonthDay",
    "PHASES", "PHASE_OUTSIDE", "PHASE_PREPARING", "ENTRY_FIELD_KO", "PHASE_PUBLISHING", "RECURRENCES", "RECURRENCE_MONTHLY", "RECURRENCE_YEARLY", "REPEATS", "REPEAT_KO", "REPEAT_ONCE", "REPEAT_YEARLY", "REVIEW_DAYS",
    "REVIEW_DUE", "REVIEW_KINDS", "REVIEW_NEVER", "REVIEW_OVERDUE", "REVIEW_SCHEDULED", "REVIEW_STATES", "REVIEW_STATE_KO", "ReviewDue", "SCHEMA", "SEASONAL_CALENDAR_REVIEW_DAYS", "SEASON_OFF", "SEASON_PREPARING",
    "SEASON_PUBLISHING", "SEASON_STATES", "SEED_INACTIVE_REVIEW_DAYS", "calendar_state", "cycle_of", "entries_from_dict", "entries_to_dict", "evaluation_age", "needs_evaluation", "parse_day_of_month", "parse_month_day",
    "phase_of", "review_due", "review_dues", "season_problem", "season_state", "seasonal_state", "state_of",
]
