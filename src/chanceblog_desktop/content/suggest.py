"""자동 후보 제안 — 블로그 프로필·기존 글·최근 선택·달력처럼 **이미 가진 정보만으로** 주제 후보를 먼저 만들어 보여 준다(`candidates suggest`, 요구서 v0.3.1 우선순위 2 의 '키 없이 가능한 부분').
규칙 기반이고 결정적이다 — 무작위·현재 시각·집합 순서에 기대지 않고(날짜는 `today` 로 받는다) 같은 입력은 같은 순서를 낸다. 네트워크·AI·파일은 쓰지 않는다. 자료의 모양은 `suggest_data.py`, 점수 계산은 `suggest_score.py`.

흐름: ① 씨앗 — 프로필의 주제·카테고리·기본 태그에서 낱말(구)을 뽑는다(없으면 멈추지 않고 '프로필에 주제를 적어 달라' 안내와 빈 목록) → ② 씨앗 × 글 유형 틀 × (그 달의 시기 낱말) 로 제목·키워드를 조합한다 → ③ **한 곳의 마지막 관문**(`_gate`)을 모든 조합이 거친다
→ ④ 남은 것을 점수(콘텐츠 작성 우선도)로 매기고 → ⑤ 같은 씨앗·같은 틀·같은 글 유형이 위쪽을 독점하지 않게, 비슷한 키워드가 겹쳐 오르지 않게 고른다(`_diversify`).

관문 순서(첫 번째로 걸린 이유 하나만 센다): 글자 수·낱말 수 한도 → 제외어 → 금지 표현(프로필 금지 표현·결과를 약속하는 표현·위험한 표기) → 형식(후보로 저장할 수 있는 모양인가) → 최근 선택 → 보관함에 이미 있음 → 기존 글과 비슷함.
**막는 쪽은 실패 열림이 없다**: 모든 조합을 끝까지 검사하고(개수 상한으로 검사를 건너뛰지 않는다) 검사 중 예외는 통과로 처리하지 않고 그대로 낸다.
'최근 선택'과 '보관함에 이미 있음' 은 걸러 내지 않고 **숨기되 번호(순번)는 그대로 둔다** — 방금 넣은 제안이 목록에서 사라지며 뒤의 번호가 당겨져, 같은 `--add 1,2` 를 다시 실행하면 다른 제안이 들어가는 일을 막으려는 것이다.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import NamedTuple

from ..check import claims
from ..errors import AppError
from ..security.mask import mask
from . import candidates as cd
from . import status as st
from . import suggest_score as sc
from . import suggest_text as tx
from .profiles import DEFAULT_POST_TYPE, DEFAULT_TOPIC_REUSE_DAYS, POST_TYPES, find_markup
from .suggest_data import FILLER_WORDS, FRAMES, MONTH_NAMES

SOURCE_MARK = "프로필 제안"                        # 보관함에 넣을 때 추천 이유 앞에 붙는 출처 표시(보관함 스키마는 바꾸지 않는다)
DEFAULT_COUNT = 10
MAX_COUNT = 50
MAX_SEEDS = 24                                    # 프로필에서 쓰는 씨앗의 최대 수(주제 → 카테고리 → 기본 태그 순으로 앞에서부터)
MAX_SEED_CHARS = 24
MAX_SEED_WORDS = 3                                # 한 구가 이 낱말 수 이하이면 구 하나가 씨앗, 넘으면 낱말마다 씨앗
MAX_FIELD_CHARS = 2000                            # 프로필 글칸에서 씨앗을 찾는 앞부분의 길이(아주 긴 글에서 오래 걸리지 않게)
MAX_TITLE_CHARS = 300                             # 기존 글 제목을 견줄 때 보는 앞부분의 길이
TOPIC_MAX_CHARS, TOPIC_MAX_WORDS = 70, 14         # 제안 제목의 한도(글자·낱말)
KEYWORD_MAX_CHARS, KEYWORD_MAX_WORDS = 40, 6      # 핵심·보조 키워드의 한도
KEYWORD_SIMILAR = 0.7                             # 같은 목록 안에서 두 키워드 낱말 집합이 이만큼(0~1) 이상 겹치면 비슷한 키워드(뒤의 것을 건너뛴다)
SEED_SHARE, FRAME_SHARE, TYPE_SHARE = 0.4, 0.2, 0.4    # 요청한 개수 중 한 씨앗·한 틀·한 글 유형이 차지할 수 있는 몫(올림) — 모자라면 마지막에 풀어서 채운다
LIMITS, EXCLUDED, FORBIDDEN, FORM, RECENT, VAULT, SIMILAR = "limits", "excluded", "forbidden", "form", "recent", "vault", "similar"
GATE_ORDER = (LIMITS, EXCLUDED, FORBIDDEN, FORM, RECENT, VAULT, SIMILAR)
GATE_LABELS = {LIMITS: "글자 수·낱말 수 한도", EXCLUDED: "제외어", FORBIDDEN: "금지 표현", FORM: "형식 위반", RECENT: "최근 선택", VAULT: "보관함에 이미 있음", SIMILAR: "비슷한 글 있음"}
HIDDEN = frozenset({RECENT, VAULT})               # 걸러 내지 않고 숨기되 번호는 그대로 두는 이유
GUIDANCE = ("이 블로그 프로필에 제안의 씨앗이 될 주제가 없습니다. 프로필에 주제를 적어 주세요 — 쉼표로 나눠 적으면 더 정확합니다"
            "(예: `naver-profile set naver_a --topic \"생활 절약, 난방, 가계부\"`). 카테고리 매핑(`--category-map`)과 기본 태그(`--tags`)도 제안에 쓰입니다.")
_SPLIT = re.compile(r"[,，、;；/／|｜·ㆍ•\n\r]+|\s+(?:및|그리고|&)\s+")
_EDGE = "()[]{}<>\"'“”‘’.:!?~*"


def _invalid(item, reason):
    return AppError("CANDIDATE_INVALID", {"항목": item, "이유": reason})


# ---- 입력 --------------------------------------------------------------------------------------------------------------------------
class Seed(NamedTuple):
    text: str
    source: str                   # 주제 · 카테고리 · 태그
    strength: int                 # sc.SEED_STRENGTH
    stems: frozenset


@dataclass(frozen=True)
class ProfileView:
    """제안이 읽는 프로필의 모양 — 네이버 프로필(`NaverProfile`)이든 같은 이름의 칸을 가진 다른 값이든 같다. 칸이 없으면 비어 있는 것으로 본다."""
    name: str = ""
    topic: str = ""
    audience: str = ""
    categories: tuple = ()
    tags: tuple = ()
    excluded: tuple = ()          # 비교용으로 정리한(`squash`) 비지 않은 제외어
    forbidden: tuple = ()         # 비교용으로 정리한 프로필의 금지 표현
    reuse_days: int = DEFAULT_TOPIC_REUSE_DAYS
    post_type: str = DEFAULT_POST_TYPE


def _squashed(values):
    return tuple(found for found in (tx.squash(item) for item in (values or ())) if found)      # 비어 있는 제외어는 모든 글에 들어 있는 것으로 읽히므로 뺀다


def view_of(profile):
    if profile is None:
        return ProfileView()
    days = getattr(profile, "topic_reuse_days", DEFAULT_TOPIC_REUSE_DAYS)
    kind = getattr(profile, "post_type", DEFAULT_POST_TYPE)
    return ProfileView(str(getattr(profile, "display_name", "") or ""), str(getattr(profile, "topic", "") or ""), str(getattr(profile, "audience", "") or ""),
                       tuple(tuple(pair) for pair in (getattr(profile, "categories", ()) or ())), tuple(str(tag) for tag in (getattr(profile, "default_tags", ()) or ())),
                       _squashed(getattr(profile, "excluded_topics", ())), _squashed(getattr(profile, "forbidden_phrases", ())),
                       days if isinstance(days, int) and not isinstance(days, bool) and days >= 0 else DEFAULT_TOPIC_REUSE_DAYS, kind if kind in POST_TYPES else DEFAULT_POST_TYPE)


def _seed_texts(raw):
    """프로필 글 → 씨앗 글들. 쉼표·가운뎃점·슬래시 같은 구분 글자(와 '및'·'그리고')로 구를 나누고, 군더더기 낱말을 버린 뒤 구가 세 낱말 이하면 구 하나, 더 길면 낱말마다 씨앗으로 한다."""
    found = []
    for phrase in _SPLIT.split(str(raw or "")[:MAX_FIELD_CHARS]):
        tokens = [token.strip(_EDGE) for token in phrase.split()]
        tokens = [token for token in tokens if token and token not in FILLER_WORDS and tx.stem(token) not in FILLER_WORDS]
        if tokens:
            found += [" ".join(tokens)] if len(tokens) <= MAX_SEED_WORDS else tokens
    return found


# 직접 겪은 일이나 결과·수익의 보장을 뜻하는 낱말 — 이런 말이 든 씨앗은 쓰지 않는다(제안 제목에 그대로 얹혀 겪지 않은 일을 지어낸 글감이 되지 않게). 띄어쓰기를 지운 글에 건다.
_RISKY = re.compile("후기|리뷰|내돈내산|써본|써봤|사용기|체험단|체험기|방문기|다녀온|다녀왔|직접써|직접해|해본|해봤|먹어본|가본|사용해본|100%|백프로|백퍼|100퍼|무조건|최저가|원금보장|합격보장|수익보장|확정수익|월천|천만원|억대|대박")


def is_secret_shaped(text):
    """가림 규칙(`security.mask`)이 눈에 안 보이는 글자를 지우는 것 말고도 바꾸는 글 — 비밀 모양이다(보이지 않는 글자만 든 글은 형식 검사가 따로 거른다)."""
    plain = "".join(char for char in text if unicodedata.category(char) not in ("Cc", "Cf"))
    return mask(text) != plain


def is_risky(text):
    """겪은 일을 전제하거나 결과를 보장하는 말이 든 글인가 — 낱말 목록·결과를 약속하는 표현(`forbidden_claim`)·경험을 단정하는 문장(`check/claims.py`)."""
    return bool(_RISKY.search(tx.squash(text))) or cd.forbidden_claim(text) is not None or bool(claims.find_violations(text))


def extract_seeds(view):
    """프로필 → (씨앗들, 찾은 씨앗의 전체 수). 주제 → 카테고리(네이버 카테고리 이름, 다르면 원고 분류도) → 기본 태그 순이고 같은 키워드는 먼저 나온(더 강한) 쪽만 남기며 `MAX_SEEDS` 개까지 쓴다.
    비밀 모양이거나 겪은 일·결과 보장을 뜻하는 말이 든 씨앗은 처음부터 버린다."""
    seeds, total, _secret, _risky = seed_report(view)
    return seeds, total


def seed_report(view):
    """`extract_seeds` 와 같되 버린 씨앗의 수도 돌려준다 → (씨앗들, 전체 수, 비밀 모양이라 버린 수, 겪은 일·보장을 뜻해 버린 수)."""
    sources = [("주제", [view.topic])]
    sources.append(("카테고리", [name for pair in view.categories for name in reversed(pair[:2])]))
    sources.append(("태그", list(view.tags)))
    seen, seeds, total, secret, risky = set(), [], 0, 0, 0
    for source, raws in sources:
        for raw in raws:
            for phrase in _SPLIT.split(str(raw or "")[:MAX_FIELD_CHARS]):
                if claims.find_violations(phrase):                                      # '직접 사용해 보니 …' 처럼 겪은 일을 단정하는 구는 통째로 버린다(낱말로 쪼개면 문장이 안 보인다)
                    risky += 1
                    continue
                for seed_text in _seed_texts(phrase):
                    key = cd.keyword_key(seed_text)
                    if not key or key in seen or not 2 <= len(seed_text) <= MAX_SEED_CHARS:
                        continue
                    if is_secret_shaped(seed_text):
                        secret += 1
                        continue
                    if is_risky(seed_text):
                        risky += 1
                        continue
                    seen.add(key)
                    total += 1
                    if len(seeds) < MAX_SEEDS:
                        seeds.append(Seed(seed_text, source, sc.SEED_STRENGTH[source], tx.stem_set(seed_text)))
    return tuple(seeds), total, secret, risky


class TitleIndex:
    """기존 글 제목들의 낱말 집합 — 낱말마다 어느 제목에 있는지 찾아 두어 제목이 많아도 겹치는 것만 견준다(같은 낱말 집합의 제목은 하나로 센다)."""

    def __init__(self, titles=()):
        seen, self._sets, self._index = set(), [], {}
        for title in titles:
            found = tx.stem_set(str(title)[:MAX_TITLE_CHARS])
            if not found or found in seen:
                continue
            seen.add(found)
            for word in found:
                self._index.setdefault(word, []).append(len(self._sets))
            self._sets.append(found)

    def __len__(self):
        return len(self._sets)

    def similarity(self, topic_stems, keyword_stems, skip=(), anchor=None):
        """제안(제목·키워드)과 가장 닮은 기존 글 제목의 닮은 정도(0~1) — 제목은 낱말 집합의 겹침(Jaccard), 키워드는 낱말이 두 개 이상이고 한 제목에 모두 들어 있으면 1. `skip` 의 낱말 집합과 같은 제목은 자기 자신이라 뺀다.
        `anchor`(제안의 씨앗 낱말)를 주면 그 낱말을 **모두 담은 제목만** 견준다 — 틀의 고정된 말('처음 알아볼 때 꼭 짚어 둘 기본 정리')이 제목 대부분을 차지해, 다른 씨앗으로 같은 틀에서 나온 글이 비슷하다고 잘못 걸리는 것을 막는다."""
        if anchor:
            near = set.intersection(*(set(self._index.get(word, ())) for word in anchor))
        else:
            near = set()
            for word in topic_stems | keyword_stems:
                near.update(self._index.get(word, ()))
        best = 0.0
        for position in near:
            title = self._sets[position]
            if title in skip:
                continue
            best = max(best, tx.jaccard(topic_stems, title), 1.0 if len(keyword_stems) >= 2 and keyword_stems <= title else 0.0)
        return best

    def covered(self, seed_stems):
        """그 씨앗의 낱말을 모두 담은 기존 글이 몇 편인가."""
        if not seed_stems:
            return 0
        return len(set.intersection(*(set(self._index.get(word, ())) for word in seed_stems)))


class External(NamedTuple):
    """키워드 하나의 외부 지표(조회한 값). 모두 선택 — 없으면 None('데이터 없음')."""
    search_demand: object = None
    related_blog_results: object = None
    trend: object = None
    mobile_share: object = None
    seasonality: object = None
    data_date: object = None

    def has_any(self):
        return any(item is not None for item in self[:5])


def external_from(candidates):
    """보관함의 후보들에서 키워드마다 가장 늦게 조회한 외부 지표를 모은다(CSV 가져오기로 들어온 값 — 키워드는 블로그와 상관없이 같은 값을 쓴다). 키는 `keyword_key`."""
    best = {}
    for item in candidates:
        found = External(item.search_demand, item.related_blog_results, item.trend, item.mobile_share, item.seasonality, item.data_date)
        if not found.has_any():
            continue
        key, stamp = cd.keyword_key(item.keyword), (item.data_date or "", item.candidate_id)
        if key and (key not in best or stamp > best[key][0]):
            best[key] = (stamp, found)
    return {key: value[1] for key, value in best.items()}


# ---- 조합 --------------------------------------------------------------------------------------------------------------------------
class Raw(NamedTuple):
    order: tuple                  # (씨앗 번호, 틀 번호, 시기 번호) — 같은 점수일 때의 정렬 열쇠
    seed: Seed
    frame: object
    season: object                # 글에 쓰는 시기 항목(시기 틀) 또는 None
    note: object                  # 추천 이유에 쓸 시기 항목 — 시기 틀이면 season 과 같고, 일반 틀이면 씨앗과 이어지는 첫 항목 또는 None
    topic: str
    keyword: str
    subs: tuple
    base: str                     # 추천 이유(틀의 이유 + 시기 이유) — 점수 설명은 아직 붙기 전


def _season_sentence(item, month, plain):
    head = f"이번 달({MONTH_NAMES[month]}) '{item.word}' 시기와 이어지는 주제입니다" if plain else f"이번 달({MONTH_NAMES[month]}) '{item.word}' 시기에 맞춘 글입니다"
    return f"{head} — {item.reason}."


def audience_phrase(view):
    """대상 독자 글에서 쓸 구 하나(첫 구, 씨앗 규칙과 같다) — 없으면 ''. 제안의 보조 키워드('대상 독자 + 씨앗')에 쓴다."""
    found = _seed_texts(view.audience)
    return found[0] if found and 2 <= len(found[0]) <= MAX_SEED_CHARS and not is_secret_shaped(found[0]) and not is_risky(found[0]) else ""


def _compose(order, seed, frame, season, note, month, audience=""):
    slots = {"주제": seed.text}
    if season is not None:
        slots["계절"] = season.word
    topic, keyword = tx.render(frame.topic, slots), tx.render(frame.keyword, slots)
    subs, seen = [], {cd.keyword_key(keyword)}
    for template in frame.subs:
        sub = tx.render(template, slots)
        key = cd.keyword_key(sub)
        if key and key not in seen:
            seen.add(key)
            subs.append(sub)
    if audience:                                                  # 대상 독자 + 씨앗('사회초년생 보험') — 한도를 넘으면 붙이지 않는다(한도 때문에 제안 전체가 걸러지지 않게)
        sub = tx.fold_repeats(f"{audience} {seed.text}")
        key = cd.keyword_key(sub)
        if key and key not in seen and len(sub) <= KEYWORD_MAX_CHARS and len(sub.split()) <= KEYWORD_MAX_WORDS:
            subs.append(sub)
    base = frame.reason + ("" if note is None else " " + _season_sentence(note, month, season is None))
    return Raw(order, seed, frame, season, note, topic, keyword, tuple(subs), base)


def generate(seeds, month, post_type=None, audience=""):
    """모든 씨앗 × 모든 틀(시기 틀은 그 달의 시기 항목과 이어지는 씨앗에만, 이어지는 항목마다) 조합 — 걸러내기 전의 날것. `post_type` 을 주면 그 글 유형의 틀만(틀 번호는 그대로), `audience` 를 주면 보조 키워드에 '대상 독자 + 씨앗' 을 더한다."""
    items = []
    for seed_number, seed in enumerate(seeds):
        related = sc.related_items(seed.text, month)
        spoken = [entry for entry in related if tx.contains_all(seed.stems, tx.stem_set(entry.word))]       # 씨앗이 이미 그 시기 낱말을 말하고 있다('난방' 이 든 씨앗에 '난방' 시기 틀을 또 붙이지 않는다)
        open_entries = [entry for entry in related if entry not in spoken]
        note = (spoken or list(related) or [None])[0]
        for frame_number, frame in enumerate(FRAMES):
            if post_type is not None and frame.post_type != post_type:
                continue
            if not frame.seasonal:
                items.append(_compose((seed_number, frame_number, -1), seed, frame, None, note, month, audience))
                continue
            for season_number, entry in enumerate(open_entries):
                items.append(_compose((seed_number, frame_number, season_number), seed, frame, entry, entry, month, audience))
    return items


def stored_reason(base):
    """보관함에 넣을 추천 이유 — 출처 표시 + 틀·시기 이유(점수 설명은 빼고, 한 줄)."""
    return f"{SOURCE_MARK} — {base}"


# ---- 한 곳의 마지막 관문 ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class _Env:
    view: ProfileView
    blog: str
    stamp: str                    # 오늘 0시(UTC 표기) — 형식 검사용
    recent: dict                  # keyword_key → 가장 최근에 고른 날로부터 며칠(한국 달력)
    vault: frozenset              # 이 블로그용으로 보관함에 이미 있는 keyword_key
    titles: TitleIndex


def _too_long(raw):
    texts = (raw.keyword, *raw.subs)
    return (not raw.keyword or len(raw.topic) > TOPIC_MAX_CHARS or len(raw.topic.split()) > TOPIC_MAX_WORDS
            or any(len(item) > KEYWORD_MAX_CHARS or len(item.split()) > KEYWORD_MAX_WORDS for item in texts))


def _gate(raw, env):
    """조합 하나가 나갈 수 있는가 → None(나간다) 또는 걸린 첫 이유(`GATE_ORDER`). **모든 제안이 이 한 함수만 거친다** — 개수 상한도 예외 삼키기도 없다(예외는 그대로 낸다)."""
    if _too_long(raw):
        return LIMITS
    fields = (raw.topic, raw.keyword, *raw.subs, raw.base)
    squashed = [tx.squash(item) for item in fields]
    if any(word in item for word in env.view.excluded for item in squashed):
        return EXCLUDED
    if any(word in item for word in env.view.forbidden for item in squashed) or any(cd.forbidden_claim(item) or find_markup(item) for item in fields):
        return FORBIDDEN
    try:
        cd.Candidate.new(raw.topic, raw.keyword, (env.blog,), candidate_id="suggest-trial", now=env.stamp, sub_keywords=raw.subs, post_type=raw.frame.post_type, reason=stored_reason(raw.base))
    except AppError as error:
        if error.code != "CANDIDATE_INVALID":
            raise
        return FORM
    key = cd.keyword_key(raw.keyword)
    if env.view.reuse_days > 0 and env.recent.get(key, env.view.reuse_days + 1) <= env.view.reuse_days:
        return RECENT
    if key in env.vault:
        return VAULT
    if env.titles.similarity(tx.stem_set(raw.topic), tx.stem_set(raw.keyword), anchor=raw.seed.stems) >= sc.SIMILAR_FROM:
        return SIMILAR
    return None


# ---- 날짜·기록 ---------------------------------------------------------------------------------------------------------------------------
def _check_today(today):
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date) or today.year < cd.MIN_YEAR:
        raise _invalid("오늘 날짜", f"{cd.MIN_YEAR}년 이후의 날짜(date)여야 합니다")
    return today


def kst_date(stamp):
    """저장된 시각(UTC `2026-11-02T03:04:05Z`) → 한국 시간(+9)의 날짜."""
    return (cd.parse_stamp(stamp) + timedelta(hours=9)).date()


def recent_days(candidates, selections, blog, today):
    """같은 블로그용으로 고른 기록 → keyword_key 마다 가장 최근에 고른 날로부터 며칠(한국 달력, 0 아래로 내려가지 않는다). 지금 '선택됨' 인 후보만 센다(물린 것은 쓰지 않기로 한 것) —
    선택 기록이 하나도 없는 '선택됨' 후보는 마지막으로 고친 시각에 추천 블로그 모두로 고른 것으로 본다(`Store.recent_selections` 와 같다). `selections` 는 (키워드, 블로그, 시각) 기록을 직접 더할 때."""
    records = list(selections)
    for item in candidates:
        if item.status != cd.SELECTED:
            continue
        records += [(item.keyword, name, stamp) for name, stamp in item.selections]
        if not item.selections and blog in item.blogs:
            records.append((item.keyword, blog, item.updated_at))
    best = {}
    for keyword, name, stamp in records:
        key = cd.keyword_key(keyword)
        if name != blog or not key:
            continue
        days = max((today - kst_date(stamp)).days, 0)
        best[key] = min(best.get(key, days), days)
    return best


def vault_keys(candidates, blog):
    return frozenset(cd.keyword_key(item.keyword) for item in candidates if blog in item.blogs)


# ---- 점수 ---------------------------------------------------------------------------------------------------------------------------------
class Metrics(NamedTuple):
    """키워드의 외부 지표 — 값이 없으면 None('데이터 없음')."""
    search_demand: object = None
    related_blog_results: object = None
    trend: object = None
    seasonality: object = None
    mobile_share: object = None

    def has_any(self):
        return any(item is not None for item in self)

    def to_dict(self):
        return {"search_demand": self.search_demand, "related_blog_results": self.related_blog_results, "trend": self.trend,
                "seasonality": None if self.seasonality is None else list(self.seasonality), "mobile_share": self.mobile_share}


class SeasonNote(NamedTuple):
    word: str
    reason: str

    def to_dict(self):
        return {"word": self.word, "reason": self.reason}


class _Scored(NamedTuple):
    raw: Raw
    hidden: object                # None · RECENT · VAULT
    priority: object
    parts: tuple
    fit: int
    external: object              # External 또는 None
    similar: float


def _score(raw, hidden, env, month, external):
    key = cd.keyword_key(raw.keyword)
    found = external.get(key)
    fit = sc.fit_score(raw.seed.strength, raw.frame.post_type == env.view.post_type)
    if found is not None and found.seasonality is not None:
        season = sc.SEASON_MATCH if month in found.seasonality else sc.SEASON_OFF
    else:
        season = sc.season_fit(raw.seed.text + ("" if raw.season is None else " " + raw.season.word), month)[0]
    similar = env.titles.similarity(tx.stem_set(raw.topic), tx.stem_set(raw.keyword), anchor=raw.seed.stems)
    opportunity = None if found is None else sc.opportunity(found.search_demand, found.related_blog_results, found.trend)
    priority, parts = sc.combine({"fit": fit, "season": season, "freshness": sc.freshness_score(similar), "balance": sc.balance_score(env.titles.covered(raw.seed.stems)),
                                  "opportunity": opportunity})
    return _Scored(raw, hidden, priority, parts, fit, found, similar)


def _diversify(scored, count):
    """점수 순(같으면 조합 순서)으로 훑으며 고른다 — ① 같은 키워드·낱말 집합이 `KEYWORD_SIMILAR` 이상 겹치는 키워드는 건너뛰고 ② 같은 씨앗·같은 틀·같은 글 유형이 요청 개수의 `SEED_SHARE`·`FRAME_SHARE`·`TYPE_SHARE`(올림)를
    넘지 않게 한 뒤 ③ 개수가 모자라면 ②의 상한만 풀어 점수 순으로 채운다. 번호(순위)는 이 목록의 자리다 — 숨길 제안(최근 선택·보관함에 있음)도 같은 자리를 차지한다."""
    caps = {"seed": max(1, math.ceil(count * SEED_SHARE)), "frame": max(1, math.ceil(count * FRAME_SHARE)), "type": max(1, math.ceil(count * TYPE_SHARE))}
    used = {"seed": Counter(), "frame": Counter(), "type": Counter()}
    chosen, skipped, keys, taken = [], [], set(), []

    def fits(item):
        key = cd.keyword_key(item.raw.keyword)
        stems = tx.stem_set(item.raw.keyword)
        return key not in keys and all(tx.jaccard(stems, other) < KEYWORD_SIMILAR for other in taken)

    def take(item):
        chosen.append(item)
        keys.add(cd.keyword_key(item.raw.keyword))
        taken.append(tx.stem_set(item.raw.keyword))
        for name, value in (("seed", item.raw.seed.text), ("frame", item.raw.frame.frame_id), ("type", item.raw.frame.post_type)):
            used[name][value] += 1

    for item in scored:
        if not fits(item):
            continue
        over = (used["seed"][item.raw.seed.text] >= caps["seed"] or used["frame"][item.raw.frame.frame_id] >= caps["frame"] or used["type"][item.raw.frame.post_type] >= caps["type"])
        if over:
            skipped.append(item)
        else:
            take(item)
    visible = sum(1 for item in chosen if item.hidden is None)
    for item in skipped:
        if visible >= count:
            break
        if fits(item):
            take(item)
            visible += item.hidden is None
    return chosen


def num(value):
    """점수를 읽기 쉽게 — 정수로 떨어지면 정수, 아니면 소수 한 자리."""
    value = round(float(value), 1)
    return str(int(value)) if value == int(value) else f"{value:.1f}"


def explain(base, parts, priority):
    """추천 이유 — 틀·시기 이유 뒤에 각 요인의 점수와 비중, 그리고 합친 콘텐츠 작성 우선도. 외부 데이터가 없으면 키워드 기회도를 반영하지 않았다고 밝힌다."""
    pieces = " · ".join(f"{sc.FACTOR_NAMES[part.name]} {num(part.value)}점(비중 {num(part.share * 100)}%)" for part in parts)
    tail = "" if any(part.name == "opportunity" for part in parts) else " 외부 데이터가 없어 키워드 기회도는 반영하지 않았습니다."
    return f"{base} 점수 근거: {pieces} → 콘텐츠 작성 우선도 {num(priority.score)}점.{tail}"


@dataclass(frozen=True)
class Suggestion:
    rank: int                     # 번호(같은 입력이면 같은 번호 — 숨긴 제안의 자리는 비어 있을 수 있다)
    blog: str
    keyword: str
    sub_keywords: tuple
    topic: str
    post_type: str
    reason: str                   # 추천 이유 — 어느 요인이 얼마나 기여했는지(쉬운 문장)
    stored_reason: str            # 보관함에 넣을 때의 추천 이유
    priority: object              # sc.Priority(콘텐츠 작성 우선도 — 높음·보통·낮음 + 0~100)
    fit: int                      # 블로그 프로필 적합도(0~100)
    season: object                # SeasonNote 또는 None — 이번 달 시기와 이어지는 이유
    metrics: Metrics              # 외부 지표(없으면 모두 None = 데이터 없음)
    data_date: object             # 외부 지표를 조회한 날 또는 None
    computed_on: str              # 이 제안을 계산한 날
    data_age: object              # sc.DataAge
    factors: tuple                # sc.Part 들
    seed: str
    seed_source: str
    frame_id: str

    @property
    def data_text(self):
        """조회일 줄 — 외부 지표가 있으면 조회일과 며칠 지났는지(오래됐으면 안내), 없으면 계산일과 '외부 데이터 없음' 을 구분해 보인다."""
        if self.data_date is None:
            return f"계산일 {self.computed_on} — 외부 데이터 없음(월간 검색 수요·관련 블로그 검색 결과 수·최근 관심도 변화는 데이터 없음)"
        return f"계산일 {self.computed_on} · {self.data_age.text()}"

    def to_dict(self):
        return {
            "rank": self.rank, "blog": self.blog, "keyword": self.keyword, "sub_keywords": list(self.sub_keywords), "topic": self.topic, "post_type": self.post_type, "reason": self.reason,
            "priority": self.priority.to_dict(), "profile_fit": self.fit, "season": None if self.season is None else self.season.to_dict(), "metrics": self.metrics.to_dict(),
            "data_date": self.data_date, "computed_on": self.computed_on, "data": self.data_age.to_dict(), "data_text": self.data_text, "seed": self.seed, "seed_source": self.seed_source,
            "frame": self.frame_id, "factors": [{"name": part.name, "label": sc.FACTOR_NAMES[part.name], "value": round(part.value, 1), "weight": part.weight, "share": round(part.share, 4),
                                                  "points": round(part.points, 2)} for part in self.factors],
        }


def _suggestion(rank, item, env, month, today):
    raw, found = item.raw, item.external
    metrics = Metrics() if found is None else Metrics(found.search_demand, found.related_blog_results, found.trend, found.seasonality, found.mobile_share)
    season = None if raw.note is None else SeasonNote(raw.note.word, raw.note.reason)
    data_date = None if found is None or not found.has_any() else found.data_date
    return Suggestion(rank, env.blog, raw.keyword, raw.subs, raw.topic, raw.frame.post_type, explain(raw.base, item.parts, item.priority), stored_reason(raw.base), item.priority, item.fit, season, metrics,
                      data_date, today.isoformat(), sc.data_age(data_date, today), item.parts, raw.seed.text, raw.seed.source, raw.frame.frame_id)


@dataclass(frozen=True)
class Report:
    blog: str
    month: int
    today: str
    count: int
    suggestions: tuple            # Suggestion — 보여 줄 것(번호 순)
    generated: int                # 만든 조합의 수(걸러내기 전)
    filtered: tuple               # ((코드, 이름, 개수, 숨김인가), …) — 개수가 있는 이유만, 관문 순서대로
    hidden_ranks: tuple           # 보여 준 마지막 번호보다 앞서 숨긴 제안의 번호들
    seeds: tuple                  # Seed
    seed_total: int
    guidance: object              # 씨앗이 없을 때의 안내 글 또는 None
    notes: tuple
    post_type: object = None      # 글 유형 필터를 줬으면 그 유형(번호가 이 값에도 달라진다 — 넣을 때 같은 값을 줘야 한다)
    more: tuple = ()              # 보여 주지 않은 나머지 제안들(번호가 있는 것이 먼저, 번호가 없는 것은 rank 0) — 키워드로 넣을 때 찾는 데만 쓰고 JSON 에는 싣지 않는다

    def __iter__(self):                                           # 제안 목록처럼 쓸 수 있다(`for 제안 in 결과`·`len(결과)`·`결과[0]`)
        return iter(self.suggestions)

    def __len__(self):
        return len(self.suggestions)

    def __getitem__(self, index):
        return self.suggestions[index]

    def to_dict(self):
        return {"blog": self.blog, "month": self.month, "today": self.today, "count": self.count, "suggestions": [item.to_dict() for item in self.suggestions], "generated": self.generated,
                "filtered": [{"code": code, "label": label, "count": number, "hidden": hidden} for code, label, number, hidden in self.filtered], "hidden_ranks": list(self.hidden_ranks),
                "seeds": [{"text": seed.text, "source": seed.source, "strength": seed.strength} for seed in self.seeds], "seed_total": self.seed_total, "guidance": self.guidance,
                "notes": list(self.notes), "post_type": self.post_type}


def suggest(profile, *, today, existing_titles=(), candidates=(), blog=None, count=DEFAULT_COUNT, month=None, selections=(), external=None, post_type=None):
    """블로그 프로필에서 주제 후보를 제안한다 → `Report`(보여 줄 제안 `count` 개까지 + 걸러낸 이유별 개수 + 안내). 읽기만 한다(파일·네트워크 없음).
    `today`(date)는 인자로 받는다. `existing_titles` 는 기존 글 제목들, `candidates` 는 보관함의 후보들(같은 키워드·블로그는 숨기고 외부 지표를 키워드로 찾아 쓴다), `selections` 는 (키워드, 블로그, 시각) 선택 기록을
    더 줄 때, `external` 은 {키워드: External} 을 직접 줄 때(없으면 `candidates` 에서 모은다), `month` 는 1~12(없으면 오늘의 달), `post_type` 은 한 글 유형의 틀만 쓸 때. 값이 틀리면 CANDIDATE_INVALID."""
    today = _check_today(today)
    blog = getattr(profile, "key", None) if blog is None else blog
    if not isinstance(blog, str) or blog not in st.PLATFORMS:
        raise _invalid("블로그", "다음 중 하나여야 합니다: " + ", ".join(st.PLATFORMS))
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_COUNT:
        raise _invalid("제안 개수", f"1~{MAX_COUNT} 사이의 정수여야 합니다")
    try:
        month = sc.month_of(today.month if month is None else month)
    except ValueError:
        raise _invalid("달", "1~12 사이의 정수여야 합니다") from None
    if post_type is not None and (not isinstance(post_type, str) or post_type not in POST_TYPES):
        raise _invalid("글 유형", "다음 중 하나여야 합니다: " + ", ".join(POST_TYPES))
    candidates = tuple(candidates)
    view = view_of(profile)
    seeds, total, secret_dropped, risky_dropped = seed_report(view)
    notes = []
    if secret_dropped:
        notes.append(f"비밀 모양의 글이 든 씨앗 {secret_dropped}개는 쓰지 않았습니다(프로필에서 지워 두세요).")
    if risky_dropped:
        notes.append(f"겪은 일이나 결과·수익의 보장을 뜻하는 낱말이 든 씨앗 {risky_dropped}개는 쓰지 않았습니다(직접 겪지 않은 일을 제안 제목으로 지어내지 않기 위해서입니다).")
    stamp = f"{today.isoformat()}T00:00:00Z"
    if not seeds:
        return Report(blog, month, today.isoformat(), count, (), 0, (), (), (), 0, GUIDANCE, tuple(notes), post_type)
    pool = external_from(candidates) if external is None else {cd.keyword_key(key): value for key, value in external.items()}
    env = _Env(view, blog, stamp, recent_days(candidates, selections, blog, today), vault_keys(candidates, blog), TitleIndex(existing_titles))
    raws = generate(seeds, month, post_type, audience_phrase(view))
    counts, kept = Counter(), []
    for raw in raws:
        code = _gate(raw, env)
        if code is not None:
            counts[code] += 1
        if code is None or code in HIDDEN:
            kept.append((raw, code))
    scored = sorted((_score(raw, code, env, month, pool) for raw, code in kept), key=lambda item: (-item.priority.score, item.raw.order))
    order = _diversify(scored, count)
    shown, gaps, more = [], [], []
    for rank, item in enumerate(order, start=1):
        if item.hidden is not None:
            gaps.append(rank)
        elif len(shown) < count:
            shown.append(_suggestion(rank, item, env, month, today))
        else:
            more.append(_suggestion(rank, item, env, month, today))
    placed = {id(item) for item in order}
    named = {cd.keyword_key(item.keyword) for item in (*shown, *more)}
    for item in scored:                                           # 다양성 때문에 목록에 오르지 못했지만 관문을 통과한 제안 — 번호는 없고(rank 0) 키워드로 지정할 때만 찾는다
        key = cd.keyword_key(item.raw.keyword)
        if id(item) not in placed and item.hidden is None and key not in named:
            named.add(key)
            more.append(_suggestion(0, item, env, month, today))
    last = shown[-1].rank if shown else 0
    if total > len(seeds):
        notes.append(f"프로필에서 찾은 씨앗 {total}개 중 앞의 {len(seeds)}개만 썼습니다(주제 → 카테고리 → 기본 태그 순).")
    if not any(item.season is not None for item in raws):
        notes.append(f"이번 달({MONTH_NAMES[month]}) 시기와 이어지는 주제가 프로필에 없어 시기 맞춤 제안은 만들지 못했습니다(상시 주제로만 제안했습니다).")
    if len(shown) < count:
        notes.append(f"조건에 맞는 제안이 {len(shown)}개뿐입니다(요청 {count}개).")
    filtered = tuple((code, GATE_LABELS[code], counts[code], code in HIDDEN) for code in GATE_ORDER if counts[code])
    return Report(blog, month, today.isoformat(), count, tuple(shown), len(raws), filtered, tuple(rank for rank in gaps if rank < last), seeds, total, None, tuple(notes), post_type, tuple(more))


# ---- 보관함의 후보에 같은 계산을 적용 ---------------------------------------------------------------------------------------------------------
class Assessment(NamedTuple):
    priority: object              # sc.Priority 또는 None(계산할 요인이 없다)
    fit: object                   # 블로그 프로필 적합도(0~100) 또는 None(프로필이 없다)
    parts: tuple
    season: object                # SeasonNote 또는 None
    data_age: object              # sc.DataAge
    similar: bool                 # 기존 글과 비슷하다(기준 이상)
    reason: str
    notes: tuple

    def to_dict(self):
        return {"priority": None if self.priority is None else self.priority.to_dict(), "profile_fit": self.fit, "season": None if self.season is None else self.season.to_dict(),
                "data": self.data_age.to_dict(), "similar_post_exists": self.similar, "reason": self.reason, "notes": list(self.notes),
                "factors": [{"name": part.name, "label": sc.FACTOR_NAMES[part.name], "value": round(part.value, 1), "weight": part.weight, "share": round(part.share, 4),
                             "points": round(part.points, 2)} for part in self.parts]}


def assess(candidate, *, profile, today, titles=None, existing_titles=(), own_titles=(), month=None):
    """보관함의 후보 하나에 같은 계산을 적용해 콘텐츠 작성 우선도·프로필 적합도·이유를 만든다(보관함 값은 바꾸지 않는다). `profile` 이 없으면 프로필 적합도는 '데이터 없음'이라 빼고 나머지로 계산한다.
    `titles`(TitleIndex)를 주면 그것을, 아니면 `existing_titles` 로 만든다. `own_titles` 는 이 후보 자신의 글 제목들(같은 낱말 집합의 제목은 자기 자신이라 견주지 않는다)."""
    today = _check_today(today)
    try:
        month = sc.month_of(today.month if month is None else month)
    except ValueError:
        raise _invalid("달", "1~12 사이의 정수여야 합니다") from None
    view = view_of(profile)
    seeds, _total = extract_seeds(view)
    index = TitleIndex(existing_titles) if titles is None else titles
    notes = []
    keyword_stems, topic_stems = tx.stem_set(candidate.keyword), tx.stem_set(candidate.topic)
    whole = keyword_stems | topic_stems | frozenset(stem for item in candidate.sub_keywords for stem in tx.stem_set(item))
    matched = [seed for seed in seeds if seed.stems <= whole]
    best = max(matched, key=lambda seed: seed.strength, default=None)
    if not seeds:
        fit = None
        notes.append("이 블로그의 프로필이 없거나 주제가 비어 있어 블로그 프로필 적합도는 계산하지 않았습니다.")
    elif best is None:
        fit = 0
        notes.append("프로필의 주제·카테고리·기본 태그와 겹치는 낱말이 없어 블로그 프로필 적합도가 0점입니다.")
    else:
        fit = sc.fit_score(best.strength, candidate.post_type == view.post_type)
    if candidate.seasonality is not None:
        season, entry = (sc.SEASON_MATCH if month in candidate.seasonality else sc.SEASON_OFF), None
    else:
        season, entry = sc.season_fit(f"{candidate.keyword} {candidate.topic}", month)
    skip = frozenset(tx.stem_set(title) for title in own_titles) | {topic_stems}
    similar = index.similarity(topic_stems, keyword_stems, skip=skip)
    covered = index.covered(best.stems if best is not None else keyword_stems)
    opportunity = sc.opportunity(candidate.search_demand, candidate.related_blog_results, candidate.trend)
    priority, parts = sc.combine({"fit": fit, "season": season, "freshness": sc.freshness_score(similar), "balance": sc.balance_score(covered), "opportunity": opportunity})
    age = sc.data_age(candidate.data_date if candidate.has_data() else None, today)
    note = None if entry is None else SeasonNote(entry.word, entry.reason)
    if priority is None:
        return Assessment(None, fit, parts, note, age, similar >= sc.SIMILAR_FROM, "", tuple(notes))
    base = "" if entry is None else _season_sentence(entry, month, entry.word not in candidate.keyword)
    return Assessment(priority, fit, parts, note, age, similar >= sc.SIMILAR_FROM, explain(base, parts, priority).strip(), tuple(notes))


__all__ = [
    "Assessment", "DEFAULT_COUNT", "External", "GATE_LABELS", "GATE_ORDER", "GUIDANCE", "HIDDEN", "MAX_COUNT", "Metrics", "ProfileView", "Report", "SOURCE_MARK", "Seed", "SeasonNote",
    "Suggestion", "TitleIndex", "assess", "audience_phrase", "explain", "extract_seeds", "external_from", "generate", "kst_date", "num", "recent_days", "stored_reason", "suggest", "vault_keys", "view_of",
]
