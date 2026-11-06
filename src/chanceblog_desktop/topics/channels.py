"""채널 프로필 — 다섯 채널(GitHub Pages·Blogger 한글·Blogger 영문·네이버 A·B)이 '주제를 어떻게 고를지' 정하는 값과, 채널과 상관없는 공통 상수(순수 자료·검증).

① 채널 이름은 코드의 다섯 키(`content.status.PLATFORMS`)를 **그대로** 쓴다. 전략 문서의 Blogger A(한글)·B(영문)는 `CHANNEL_ALIAS` 로만 받는 입력 별칭이고 저장하는 값은 늘 코드 키다.
② 프로필의 숫자는 **기본값**이다(운영자가 고칠 수 있다): 여섯 항목 가중치(합 100)·지속형/실시간 비율(합 100)·채널당 보여 줄 후보 수·같은 주제 묶음 상한·글 소제목 최소 수·중복 판정 기준·관심도(Trend) 사용 정도.
③ '후보 생성'(`generation_enabled`)과 '이력 읽기·중복 검사용 정규화'(`history_enabled`)는 따로 켠다 — 지금은 네이버 A·B 만 후보 생성을 켜고, 나머지 세 채널은 프로필과 이력 읽기만 한다.
④ 사람이 고치는 JSON 파일을 읽고 쓰는 일은 서비스(`service/topic_files.py`)의 몫이다. 여기서는 사전(dict) 변환(`profiles_to_dict`·`profiles_from_dict`)까지만 하고, 모르는 칸·합 불일치·범위 밖은 기존 오류 체계(`CONTENT_INVALID`)로 거절한다(고쳐 받지 않는다).
⑤ **판 2(P3b-1)**: 저장 모양을 2 로 올려 쓰고 1·2 를 모두 읽는다(판 1 은 새 칸을 빈 기본값으로 채우고 파일은 다시 쓰지 않는다 — 더 새로운 판은 거절). 새 칸 열여섯 개는 모두 **선택 칸(기본값 비어 있음)** 이고 프로필 입력 화면(P4b)이 쓸 것이다:
   블로그 ID 또는 URL(`blog_ref`)·별명(`alias`)·채널 역할(`channel_role`)·주요 주제(`main_topics`)·대상 독자(`audience`)·문체(`tone`)·카테고리(`categories`)·소개글(`intro`)·색 프리셋(`color_preset` — 없음이거나 `warm_lifestyle`·`cool_technology`)·
   프로필 이미지 경로(`profile_image`)·커버 이미지 경로(`cover_image` — 경로 글만, 파일이 있는지 보지 않는다)·우선 키워드(`priority_keywords`)·제외 키워드(`exclude_keywords`)·선호 글 유형(`preferred_post_types`)·상시 이동권 지역(`home_regions`)·당일 이동권 지역(`day_trip_regions`).
   협찬 가능 분야는 새로 만들지 않고 이미 있는 `monetization_focus` 를 쓴다. **실제 블로그 이름·아이디·주소·별명·지역은 이 저장소 어디에도 없다** — 이 PC 사용자 데이터(`channel_profiles.json`)에만 두는 값이다(기본 프로필은 빈 값). 길이·개수 상한은 `docs/TOPIC_ENGINE_PLAN.md` 의 표와 같다.
순수 계산이다 — 파일·네트워크·시계·난수를 쓰지 않는다.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import NamedTuple

from ..content.profiles import POST_TYPES
from ..content.profiles import _invalid as _base_invalid
from ..content.profiles import _no_markup, _number, _text, _words
from ..content.status import PLATFORMS
from ..errors import AppError
from . import wording

SCHEMA = 2                                            # 쓰는 판 — 1 도 읽는다(`SCHEMAS`)
SCHEMAS = (1, 2)


def invalid_in(subject, item, detail="", *, dev=""):
    """`subject`(예: '채널 프로필'·'씨앗 목록'·'캘린더'·'보류함')의 칸 오류(`CONTENT_INVALID`). 안내 문구의 「항목」 자리에 어느 칸이 왜 안 되는지를 함께 담는다 — 칸 이름만 있으면 무엇이 틀렸는지 알 수 없다
    (새 오류 코드는 만들지 않고 이 자리에 쉬운 말로 적는다 — P2a, 독립 검증 L5). 안내 틀(`docs/TROUBLESHOOTING.md` 의 `CONTENT_INVALID` 행)은 P2b 에서 '원고의 …·제목은 200자 이하…' 대신
    원고와 주제 엔진이 함께 쓸 수 있는 말('다음 칸의 값이 올바르지 않습니다: 「항목」')로 바꿨다(독립 검증 M7). 개발자용 세부(`detail`)는 그대로 남긴다.
    P2b 보완(D-57): `dev` 는 개발자용 메모(원시 값·칸 이름 목록)로 **`AppError.detail` 에만** 이어 붙고(`detail | dev`) 「항목」 글에는 들어가지 않는다 — 화면 글은 쉬운 말 도우미(`wording`)로만 만든다.
    만든 오류에는 속성 둘이 달린다: `reason`(「항목」 에 들어간 쉬운 말 이유)·`dev`(개발자 메모) — `at_entry` 가 이것으로 오류를 다시 만들어 메모가 화면 글로 새지 않는다."""
    shown = item if item.startswith(subject) else f"{subject}의 {item}"
    error = _base_invalid(f"{shown} — {detail}" if detail else shown, detail=f"{detail} | {dev}" if detail and dev else (detail or dev))
    error.explained = True
    error.reason = detail
    error.dev = dev
    return error


def explain(subject, error):
    """칸 검사 도구(`content.profiles`)가 칸 이름만 담아 낸 오류를 `invalid_in` 과 같은 모양으로 바꾼다. 이미 풀어 쓴 오류·다른 코드의 오류는 그대로 둔다."""
    if getattr(error, "explained", False) or error.requested_code != "CONTENT_INVALID":
        return error
    return invalid_in(subject, str(error.slots.get("항목", "")), error.detail or "모양이나 길이가 맞지 않습니다")


def at_entry(subject, number, error):
    """목록의 `number`번째 항목에서 난 오류(`explain`·`invalid_in` 으로 만든 것)를 '`number`번째 `subject`' 이름이 붙은 오류로 바꾼다 — 사람이 고치는 JSON 에서 어느 항목인지 알 수 있게 한다."""
    if getattr(error, "explained", False) is not True or error.requested_code != "CONTENT_INVALID":
        return error
    item = str(error.slots.get("항목", "")).split(" — ", 1)[0]
    item = item[len(subject) + 2:] if item.startswith(subject + "의 ") else item          # '씨앗의 ' 를 떼고 칸 이름만 남긴다
    return invalid_in(f"{number}번째 {subject}", item, getattr(error, "reason", error.detail), dev=getattr(error, "dev", ""))          # 쉬운 말 이유와 개발자 메모를 따로 다시 넣는다


def _invalid(item, detail="", *, dev=""):
    return invalid_in("채널 프로필", item, detail, dev=dev)


def _explained(error):
    return explain("채널 프로필", error)

# ---- 채널 이름 ------------------------------------------------------------------------------------------------------------------
CHANNELS = PLATFORMS                                  # 코드의 다섯 키(순서 포함): github_pages·blogger_en·blogger_ko·naver_a·naver_b
CHANNEL_ALIAS = MappingProxyType({"blogger_a": "blogger_ko", "blogger_b": "blogger_en"})      # 전략 문서의 이름 → 코드 키(입력 별칭 — 저장하지 않는다)


def canonical(name):
    """채널 이름(코드 키 또는 입력 별칭) → 코드 키. 모르는 이름은 `CONTENT_INVALID` 로 거절한다(대소문자·공백을 고쳐 받지 않는다)."""
    if isinstance(name, str):
        if name in CHANNELS:
            return name
        if name in CHANNEL_ALIAS:
            return CHANNEL_ALIAS[name]
    raise _invalid("채널 이름", detail=f"아는 채널 이름이 아닙니다: {wording.quote(str(name), 40)} — " + wording.one_of(CHANNELS, wording.CHANNEL_KO), dev="코드의 채널 이름: " + ", ".join(CHANNELS))


# ---- 점수 여섯 항목(채널마다 가중치가 다르다) ----------------------------------------------------------------------------------------
FACTOR_NAMES = ("channel_fit", "feasibility", "differentiation", "timing", "evidence", "monetization")
FACTOR_LABELS = MappingProxyType({
    "channel_fit": "채널 적합도", "feasibility": "작성 가능성", "differentiation": "차별성", "timing": "시기", "evidence": "근거", "monetization": "수익화",
})

LANGUAGES = ("ko", "en")
# 관심도(Trend) 사용 정도 — 시기 항목 계산에서 `none` 만 다르게 다룬다(관심도를 아예 쓰지 않는다). 나머지 셋의 차이는 채널의 시기 가중치로 드러난다.
USE_PRIMARY, USE_SUPPORTING, USE_REFERENCE, USE_NONE = "primary", "supporting", "reference", "none"
TREND_USES = (USE_PRIMARY, USE_SUPPORTING, USE_REFERENCE, USE_NONE)

# ---- 채널과 상관없는 공통 상수 --------------------------------------------------------------------------------------------------------
SOURCE_MIX = MappingProxyType({"seed": 30, "follow_up": 20, "seasonal": 20, "realtime": 15, "sponsor": 15})      # 후보가 생기는 경로의 비율(%)


class SeedQuota(NamedTuple):
    first: int                                        # 씨앗 하나에서 처음 만들 후보의 최대 수
    keep: int                                         # 검증 뒤 남길 후보의 최대 수


PER_SEED = MappingProxyType({
    "general": SeedQuota(3, 2), "priority": SeedQuota(5, 3), "seasonal": SeedQuota(5, 3), "realtime": SeedQuota(5, 3), "sponsorable": SeedQuota(5, 3),
})
GRADE_CUTOFFS = (80, 65, 50)                          # 점수 구간 경계: 80 이상 우선 추천·65 이상 일반·50 이상 보류·그 아래 제외(`score.band_of`)
HOLD_DAYS = 90                                        # 보류 구간(50~64점) 후보를 보관하는 날수
FOLLOW_UP_PER_POST = 3                                # 기존 글 한 편에서 만들 후속 후보의 최대 수
MAX_CHANNELS_PER_TOPIC = 2                            # 같은 원천 주제를 쓸 수 있는 채널의 최대 수

# ---- 한도 -----------------------------------------------------------------------------------------------------------------------
MAX_NAME = 30
MAX_TOP_N = 20
MAX_CLUSTER_CAP = 20
MAX_SUBHEADING_MIN = 20
MAX_CLUSTERS = 30
MAX_DIRECTIONS = 20
MAX_FOCUS = 10
# 판 2 의 새 칸 한도(P3b-1) — P4b 프로필 입력 화면이 같은 상한을 쓴다(표는 `docs/TOPIC_ENGINE_PLAN.md`)
MAX_BLOG_REF, MAX_ALIAS, MAX_ROLE, MAX_AUDIENCE, MAX_TONE, MAX_INTRO, MAX_IMAGE_PATH = 200, 30, 60, 120, 120, 300, 260
MAX_MAIN_TOPICS, MAX_TOPIC_WORD, MAX_CATEGORIES, MAX_CATEGORY_WORD, MAX_KEYWORDS, MAX_KEYWORD_WORD, MAX_REGIONS, MAX_REGION_WORD = 10, 30, 30, 40, 20, 30, 20, 30
COLOR_PRESETS = ("warm_lifestyle", "cool_technology")   # 색 프리셋 — 값은 이 둘뿐이다(색 값 표는 화면 쪽 몫, 색 직접 입력은 없다)
_BLOG_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_BLOG_URL = re.compile(r"https://(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}(?::[0-9]{1,5})?(?:/[^\s#]*)?")      # https://주소 — 계정 정보(`사용자@`)·# 뒤 글·공백이 없다
SLUG_MAX = 60                                         # 주제 묶음·관점 식별자(영문 소문자·숫자·붙임표)의 최대 길이
TAG_MAX = 40                                          # 수익화 태그(영문 소문자·숫자·밑줄)의 최대 길이
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_TAG = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")


def is_slug(value, high=SLUG_MAX):
    """영문 소문자·숫자와 붙임표(-)로 된 식별자(`local-ai`)인가."""
    return isinstance(value, str) and len(value) <= high and _SLUG.fullmatch(value) is not None


def is_tag(value, high=TAG_MAX):
    """영문 소문자·숫자와 밑줄(_)로 된 태그(`pc_parts`)인가."""
    return isinstance(value, str) and len(value) <= high and _TAG.fullmatch(value) is not None


def _flag(value, item):
    if not isinstance(value, bool):
        raise _invalid(item, detail="예·아니오(true·false) 중 하나여야 한다")
    return value


class Weights(Mapping):
    """여섯 항목의 가중치 — **읽기 전용** 이다(P2b, 독립 검증 M1). 사전(`dict`)이 아니라 `collections.abc.Mapping` 을 이어받고 값은 안쪽의 읽기 전용 보기에 숨겨 둔다 —
    `w[k] = v`·`update`·`pop`·`|=` 는 물론 `dict.update(w, …)`·`dict.__setitem__(w, …)` 처럼 사전 부품을 직접 불러도, `w.__init__(…)` 으로 다시 채우려 해도, 속성을 바꾸려 해도 `TypeError` 다.
    P2a 의 `dict` 하위 클래스는 그런 직접 호출을 막지 못했고 `default_profiles()` 가 돌려주는 공유 객체가 한 번 바뀌면 프로세스 전체의 기본 가중치가 오염됐다.
    `copy.copy`·`copy.deepcopy`·`pickle`·`dataclasses.asdict`·`astuple` 은 `__reduce__` 덕분에 그대로 된다(독립 검증 L3). 단 `asdict` 가 돌려주는 가중치는 `Weights` 로 남는다 — JSON 글로 쓸 때는 `to_dict()` 를 쓴다.
    (파이썬에서 `object.__setattr__` 로 작정하고 우회하는 것까지는 막지 못한다 — 실수 방지와 오염 방지가 목적이다.)"""
    __slots__ = ("_data",)

    def __init__(self, data=()):
        if hasattr(self, "_data"):
            raise TypeError("가중치는 읽기 전용이다 — 이미 만들어진 가중치를 다시 채울 수 없다")
        object.__setattr__(self, "_data", MappingProxyType(dict(data)))

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def _blocked(self, *args, **kwargs):
        raise TypeError("가중치는 읽기 전용이다 — 바꾸려면 `dataclasses.replace` 로 새 채널 프로필을 만든다")

    # 고치려는 모든 보통 시도(`[]=`·`del`·`update`·`pop`·`|=` …)는 TypeError 다(P1·P2a 의 약속 그대로) — 사전이 아니므로 `dict.update(w, …)` 같은 직접 호출도 TypeError 다
    __setitem__ = __delitem__ = __ior__ = __setattr__ = __delattr__ = clear = pop = popitem = setdefault = update = _blocked

    def __repr__(self):
        return f"Weights({dict(self._data)!r})"

    def __reduce__(self):
        return (Weights, (dict(self._data),))


def _weights(value):
    item = "항목별 가중치"
    if not isinstance(value, Mapping) or set(value) != set(FACTOR_NAMES):
        raise _invalid(item, detail="가중치는 여섯 항목(" + wording.quoted(FACTOR_NAMES, names=FACTOR_LABELS) + ")이 모두 있어야 하고 다른 이름은 쓸 수 없습니다", dev="항목 이름: " + ", ".join(FACTOR_NAMES))
    checked = {name: _number(value[name], item, 0, 100) for name in FACTOR_NAMES}
    total = sum(checked.values())
    if total != 100:
        raise _invalid(item, detail=f"가중치의 합은 100 이어야 하는데 {total} 이다")
    return Weights(checked)


def _cutoffs(value):
    item = "중복 판정 기준"
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise _invalid(item, detail="유사도(%) 기준 세 개(예: 40, 60, 75)여야 한다")
    cutoffs = tuple(_number(number, item, 1, 99) for number in value)
    if not cutoffs[0] < cutoffs[1] < cutoffs[2]:
        raise _invalid(item, detail="세 기준은 앞에서 뒤로 갈수록 커야 한다")
    return cutoffs


def _identifiers(values, item, *, count, check, shape):
    if not isinstance(values, (list, tuple)) or len(values) > count:
        raise _invalid(item, detail=f"목록(여러 개)이고 {count}개까지여야 한다")
    names = tuple(values)
    if not all(check(name) for name in names):
        raise _invalid(item, detail=f"각 낱말은 {shape}여야 한다")
    if len(set(names)) != len(names):
        raise _invalid(item, detail="같은 낱말이 두 번 들어 있다")
    return names


def _blog_ref(value):
    """블로그 ID(영문·숫자·`._-` 64자까지) 또는 https 주소(200자까지, 공백·계정 정보·바탕 글 없는 모양). 비워 둘 수 있다."""
    item = PROFILE_FIELD_KO["blog_ref"]
    if value == "":
        return ""
    if not isinstance(value, str) or len(value) > MAX_BLOG_REF or any(char.isspace() for char in value):
        raise _invalid(item, detail=f"공백 없이 {MAX_BLOG_REF}자까지 쓰는 블로그 ID 나 https 주소여야 한다")
    _no_markup(value, item)
    if value.lower().startswith("http"):
        if _BLOG_URL.fullmatch(value) is None:
            raise _invalid(item, detail="https://블로그주소 모양이어야 한다(계정 정보나 # 뒤 글은 쓸 수 없다)")
        return value
    if _BLOG_ID.fullmatch(value) is None:
        raise _invalid(item, detail="블로그 ID 는 영문·숫자와 . _ - 만 쓰는 64자까지의 글이고 주소는 https:// 로 시작해야 한다")
    return value


def _image_path(value, item):
    """이미지 경로 글 — 한 줄·260자까지·제어 문자 없음·`data:` 같은 내용 직접 넣기와 위험한 표기가 없다. **파일이 있는지는 보지 않는다**(경로 글만 저장한다 — 이미지 내용을 담지 않는다)."""
    if not isinstance(value, str):
        raise _invalid(item, detail="경로 글이어야 한다")
    text = _no_markup(_text(value, item, low=0, high=MAX_IMAGE_PATH), item)
    if text.lower().startswith(("data:", "javascript:", "vbscript:")):
        raise _invalid(item, detail="이미지 내용을 직접 넣을 수 없다 — 파일 경로만 적는다")
    return text


_KEYS_V1 = ("key", "display_name", "language", "generation_enabled", "history_enabled", "evergreen_pct", "realtime_pct", "weights", "top_n", "cluster_cap", "subheading_min",
            "trend_use", "dup_cutoffs", "topic_clusters", "expansion_directions", "monetization_focus")
_NEW_KEYS = ("blog_ref", "alias", "channel_role", "main_topics", "audience", "tone", "categories", "intro", "color_preset", "profile_image", "cover_image", "priority_keywords", "exclude_keywords",
             "preferred_post_types", "home_regions", "day_trip_regions")
_KEYS = _KEYS_V1 + _NEW_KEYS                          # 지금 판(2)의 칸 — 판 1 은 앞의 열여섯 칸이다
PROFILE_FIELD_KO = MappingProxyType({"key": "채널 이름", "display_name": "표시 이름", "language": "언어", "generation_enabled": "후보 생성 켜기", "history_enabled": "이력 읽기 켜기",
                                     "evergreen_pct": "지속형 비율", "realtime_pct": "실시간 비율", "weights": "항목별 가중치", "top_n": "채널당 후보 수", "cluster_cap": "주제 묶음 상한",
                                     "subheading_min": "소제목 최소 수", "trend_use": "관심도 사용 정도", "dup_cutoffs": "중복 판정 기준", "topic_clusters": "주제 묶음",
                                     "expansion_directions": "확장 방향", "monetization_focus": "우선 수익화 분야", "blog_ref": "블로그 ID 또는 주소", "alias": "별명", "channel_role": "채널 역할",
                                     "main_topics": "주요 주제", "audience": "대상 독자", "tone": "문체", "categories": "카테고리", "intro": "소개글", "color_preset": "색 프리셋", "profile_image": "프로필 이미지 경로",
                                     "cover_image": "커버 이미지 경로", "priority_keywords": "우선 키워드", "exclude_keywords": "제외 키워드", "preferred_post_types": "선호 글 유형", "home_regions": "상시 이동권 지역",
                                     "day_trip_regions": "당일 이동권 지역"})        # 칸 이름 → 쉬운 한국어(오류 안내용)


@dataclass(frozen=True)
class ChannelProfile:
    key: str                                          # 채널 코드 키
    display_name: str                                 # 화면에 보일 한국어 이름
    language: str                                     # ko·en
    generation_enabled: bool                          # 후보를 만드는가(지금은 네이버 A·B 만 켠다)
    history_enabled: bool                             # 기존 글 이력을 읽고 중복 검사용으로 정규화하는가
    evergreen_pct: int                                # 지속형 글의 비율(%)
    realtime_pct: int                                 # 실시간·시의성 글의 비율(%) — 지속형과 합 100
    weights: Mapping = field(hash=False)              # 여섯 항목 이름 → 가중치(정수, 합 100) — 읽기 전용
    top_n: int = 5                                    # 채널마다 기본 화면에 보일 우수 후보 수
    cluster_cap: int = 2                              # 우수 후보 안에서 같은 주제 묶음의 최대 수
    subheading_min: int = 4                           # 글 소제목의 최소 수
    trend_use: str = USE_PRIMARY                      # 관심도(Trend) 사용 정도: primary·supporting·reference·none
    dup_cutoffs: tuple = (40, 60, 75)                 # 중복 판정 유사도(%) 기준 세 개
    topic_clusters: tuple = ()                        # 이 채널이 다루는 주제 묶음(영문 소문자-붙임표 식별자)
    expansion_directions: tuple = ()                  # 이 채널의 후보 확장 방향 낱말
    monetization_focus: tuple = ()                    # 우선 수익화 분야 태그(영문 소문자-밑줄) — 협찬 가능 분야는 새로 만들지 않고 이 칸을 쓴다
    # ---- 판 2 에서 더한 선택 칸(모두 기본값이 비어 있다 — P4b 프로필 입력 화면이 쓴다) ----
    blog_ref: str = ""                                # 블로그 ID 또는 https 주소(비워 둘 수 있다)
    alias: str = ""                                   # 별명(30자까지)
    channel_role: str = ""                            # 채널 역할(60자까지)
    main_topics: tuple = ()                           # 주요 주제 낱말(10개까지)
    audience: str = ""                                # 대상 독자(120자까지)
    tone: str = ""                                    # 문체(120자까지)
    categories: tuple = ()                            # 카테고리 낱말(30개까지)
    intro: str = ""                                   # 소개글(300자까지 한 줄)
    color_preset: str | None = None                   # 색 프리셋: None·warm_lifestyle·cool_technology
    profile_image: str = ""                           # 프로필 이미지 경로 글(파일이 있는지 보지 않는다)
    cover_image: str = ""                             # 커버 이미지 경로 글
    priority_keywords: tuple = ()                     # 우선 키워드(20개까지)
    exclude_keywords: tuple = ()                      # 제외 키워드(20개까지)
    preferred_post_types: tuple = ()                  # 선호 글 유형(`content.profiles.POST_TYPES` 중 — 중복 없이)
    home_regions: tuple = ()                          # 상시 이동권 지역 낱말(`{기준 지역}` 씨앗의 자리를 채운다 — 실제 값은 저장소에 없다)
    day_trip_regions: tuple = ()                      # 당일 이동권 지역 낱말

    def __post_init__(self):
        try:
            self._check()
        except AppError as error:
            raise _explained(error) from None

    def _check(self):
        def put(name, value):
            object.__setattr__(self, name, value)

        if not isinstance(self.key, str) or self.key not in CHANNELS:
            raise _invalid("채널 이름", detail="다음 채널 중 하나여야 합니다: " + wording.quoted(CHANNELS, names=wording.CHANNEL_KO), dev="코드의 채널 이름: " + ", ".join(CHANNELS))
        put("display_name", _no_markup(_text(self.display_name, "표시 이름", low=1, high=MAX_NAME), "표시 이름"))
        if not isinstance(self.language, str) or self.language not in LANGUAGES:
            raise _invalid("언어", detail=wording.one_of(LANGUAGES, wording.LANGUAGE_KO), dev="값: " + ", ".join(LANGUAGES))
        _flag(self.generation_enabled, "후보 생성 켜기")
        _flag(self.history_enabled, "이력 읽기 켜기")
        evergreen = _number(self.evergreen_pct, "지속형 비율", 0, 100)
        realtime = _number(self.realtime_pct, "실시간 비율", 0, 100)
        if evergreen + realtime != 100:
            raise _invalid("지속형·실시간 비율", detail=f"두 비율의 합은 100 이어야 하는데 {evergreen + realtime} 이다")
        put("weights", _weights(self.weights))
        _number(self.top_n, "채널당 후보 수", 1, MAX_TOP_N)
        _number(self.cluster_cap, "주제 묶음 상한", 1, MAX_CLUSTER_CAP)
        _number(self.subheading_min, "소제목 최소 수", 1, MAX_SUBHEADING_MIN)
        if not isinstance(self.trend_use, str) or self.trend_use not in TREND_USES:
            raise _invalid("관심도 사용 정도", detail=wording.one_of(TREND_USES, wording.TREND_USE_KO), dev="값: " + ", ".join(TREND_USES))
        put("dup_cutoffs", _cutoffs(self.dup_cutoffs))
        put("topic_clusters", _identifiers(self.topic_clusters, "주제 묶음", count=MAX_CLUSTERS, check=is_slug, shape="영문 소문자·숫자·붙임표(-)로 된 식별자"))
        put("expansion_directions", _words(self.expansion_directions, "확장 방향", count=MAX_DIRECTIONS, high=40, sequence_only=True, markup_free=True))
        put("monetization_focus", _identifiers(self.monetization_focus, "우선 수익화 분야", count=MAX_FOCUS, check=is_tag, shape="영문 소문자·숫자·밑줄(_)로 된 태그"))
        self._check_v2(put)

    def _check_v2(self, put):
        def line(name, limit):
            label = PROFILE_FIELD_KO[name]
            put(name, _no_markup(_text(getattr(self, name), label, low=0, high=limit), label))

        def words(name, count, high):
            put(name, _words(getattr(self, name), PROFILE_FIELD_KO[name], count=count, high=high, sequence_only=True, markup_free=True))

        put("blog_ref", _blog_ref(self.blog_ref))
        for name, limit in (("alias", MAX_ALIAS), ("channel_role", MAX_ROLE), ("audience", MAX_AUDIENCE), ("tone", MAX_TONE), ("intro", MAX_INTRO)):
            line(name, limit)
        for name, count, high in (("main_topics", MAX_MAIN_TOPICS, MAX_TOPIC_WORD), ("categories", MAX_CATEGORIES, MAX_CATEGORY_WORD), ("priority_keywords", MAX_KEYWORDS, MAX_KEYWORD_WORD),
                                  ("exclude_keywords", MAX_KEYWORDS, MAX_KEYWORD_WORD), ("home_regions", MAX_REGIONS, MAX_REGION_WORD), ("day_trip_regions", MAX_REGIONS, MAX_REGION_WORD)):
            words(name, count, high)
        if {item.casefold() for item in self.priority_keywords} & {item.casefold() for item in self.exclude_keywords}:
            raise _invalid("우선 키워드", detail="제외 키워드에 있는 낱말은 우선 키워드로 쓸 수 없다")
        if self.color_preset is not None and (not isinstance(self.color_preset, str) or self.color_preset not in COLOR_PRESETS):
            raise _invalid(PROFILE_FIELD_KO["color_preset"], detail=wording.one_of(COLOR_PRESETS, wording.COLOR_PRESET_KO) + " — 비워 둘 수도 있습니다", dev="값: " + ", ".join(COLOR_PRESETS))
        for name in ("profile_image", "cover_image"):
            put(name, _image_path(getattr(self, name), PROFILE_FIELD_KO[name]))
        kinds = self.preferred_post_types
        if not isinstance(kinds, (list, tuple)) or len(kinds) > len(POST_TYPES) or not all(isinstance(item, str) and item in POST_TYPES for item in kinds) or len(set(kinds)) != len(kinds):
            raise _invalid(PROFILE_FIELD_KO["preferred_post_types"], detail="다음 글 유형 중에서 한 번씩만 고를 수 있습니다: " + wording.quoted(POST_TYPES))
        put("preferred_post_types", tuple(kinds))

    def to_dict(self):
        return {
            "key": self.key, "display_name": self.display_name, "language": self.language, "generation_enabled": self.generation_enabled, "history_enabled": self.history_enabled,
            "evergreen_pct": self.evergreen_pct, "realtime_pct": self.realtime_pct, "weights": {name: self.weights[name] for name in FACTOR_NAMES}, "top_n": self.top_n,
            "cluster_cap": self.cluster_cap, "subheading_min": self.subheading_min, "trend_use": self.trend_use, "dup_cutoffs": list(self.dup_cutoffs),
            "topic_clusters": list(self.topic_clusters), "expansion_directions": list(self.expansion_directions), "monetization_focus": list(self.monetization_focus),
            "blog_ref": self.blog_ref, "alias": self.alias, "channel_role": self.channel_role, "main_topics": list(self.main_topics), "audience": self.audience, "tone": self.tone,
            "categories": list(self.categories), "intro": self.intro, "color_preset": self.color_preset, "profile_image": self.profile_image, "cover_image": self.cover_image,
            "priority_keywords": list(self.priority_keywords), "exclude_keywords": list(self.exclude_keywords), "preferred_post_types": list(self.preferred_post_types),
            "home_regions": list(self.home_regions), "day_trip_regions": list(self.day_trip_regions),
        }

    @classmethod
    def from_dict(cls, data, *, schema=None):
        """저장된 모양을 엄격하게 읽는다 — 정확히 이 칸들이어야 하고(모르는 칸·빠진 칸 거절) 값은 `__post_init__` 이 검사한다. `schema` 를 주면 그 판의 칸(1 은 열여섯 칸·2 는 서른두 칸)이어야 하고,
        안 주면 둘 중 하나의 모양이면 된다(판 1 칸 묶음은 새 칸이 빈 기본값이다)."""
        if not isinstance(data, dict):
            raise _invalid("채널 프로필", detail="칸이 있는 묶음(JSON 객체)이어야 한다")
        keys = set(data)
        expected = _KEYS_V1 if schema == 1 else _KEYS if schema == 2 else (_KEYS_V1 if keys <= set(_KEYS_V1) else _KEYS)
        unknown, missing = sorted(map(str, keys - set(expected))), sorted(set(expected) - keys)
        if unknown or missing:
            raise _invalid("채널 프로필", detail=wording.unknown_and_missing(unknown, missing, PROFILE_FIELD_KO), dev=f"모르는 칸 {unknown}, 빠진 칸 {missing}")
        return cls(**data)


# ---- 기본값 5개 -----------------------------------------------------------------------------------------------------------------
# 가중치 순서는 FACTOR_NAMES 와 같다: 채널 적합도·작성 가능성·차별성·시기·근거·수익화. 숫자는 전략 문서의 초기 운영값이고 채널 성과가 쌓인 뒤 다시 정한다.
# 표시 이름은 `service/format.py` 의 `PLATFORM_KO` 와 같다(시험이 둘을 비교한다 — 서비스 층을 가져오지는 않는다).
DEFAULT_PROFILES = (
    ChannelProfile(
        key="github_pages", display_name="GitHub Pages", language="ko", generation_enabled=False, history_enabled=True, evergreen_pct=40, realtime_pct=60,
        weights=dict(zip(FACTOR_NAMES, (20, 15, 15, 15, 25, 10), strict=True)), trend_use=USE_SUPPORTING,
        topic_clusters=("industry-impact", "ai-and-compute", "energy-and-infrastructure", "privacy-and-data", "platform-policy", "api-transition"),
        expansion_directions=("변화", "영향", "배경", "산업·경제·사회적 맥락", "분야 연결"), monetization_focus=()),
    ChannelProfile(
        key="blogger_en", display_name="Blogger 영문", language="en", generation_enabled=False, history_enabled=True, evergreen_pct=90, realtime_pct=10,
        weights=dict(zip(FACTOR_NAMES, (30, 25, 20, 5, 10, 10), strict=True)), trend_use=USE_NONE,
        topic_clusters=("simple-habits", "daily-routines", "meal-planning", "home-organization", "personal-productivity", "digital-wellbeing", "weekly-reset", "evening-routine"),
        expansion_directions=("simple routine", "gentle reset", "low-pressure habit", "everyday checklist"), monetization_focus=()),
    ChannelProfile(
        key="blogger_ko", display_name="Blogger 한글", language="ko", generation_enabled=False, history_enabled=True, evergreen_pct=85, realtime_pct=15,
        weights=dict(zip(FACTOR_NAMES, (25, 25, 20, 10, 10, 10), strict=True)), trend_use=USE_REFERENCE,
        topic_clusters=("digital-organization", "schedule-management", "memo-and-information", "smartphone-settings", "shopping-habits", "time-management", "household-budget",
                        "personal-productivity"),
        expansion_directions=("정리", "습관", "반복 관리", "정보 관리", "생활 부담 줄이기"), monetization_focus=()),
    ChannelProfile(
        key="naver_a", display_name="네이버 A", language="ko", generation_enabled=True, history_enabled=True, evergreen_pct=70, realtime_pct=30,
        weights=dict(zip(FACTOR_NAMES, (25, 15, 10, 15, 10, 25), strict=True)), trend_use=USE_PRIMARY,
        topic_clusters=("small-appliances", "pc-peripherals", "lodging-and-travel", "local-places", "daily-problem-solving"),
        expansion_directions=("구매 기준", "제품 비교", "방문 전 확인", "지역·계절 체험", "관리 방법"), monetization_focus=("small_appliance", "pc_peripheral", "lodging_travel")),
    ChannelProfile(
        key="naver_b", display_name="네이버 B", language="ko", generation_enabled=True, history_enabled=True, evergreen_pct=50, realtime_pct=50,
        weights=dict(zip(FACTOR_NAMES, (25, 15, 10, 20, 10, 20), strict=True)), trend_use=USE_PRIMARY,
        topic_clusters=("ai-services", "api-and-limits", "github-and-deploy", "local-ai", "pc-parts", "work-automation", "desktop-app-log"),
        expansion_directions=("설치", "설정", "API 연동", "성능", "호환성", "오류 해결", "자동화 사례"), monetization_focus=("ai_service", "pc_parts", "work_automation")),
)


def default_profiles():
    """기본 채널 프로필 다섯 개(코드의 채널 순서) — 바꿀 수 없는 값(frozen)이라 고치려면 `dataclasses.replace` 로 새로 만든다."""
    return DEFAULT_PROFILES


def _ordered(profiles):
    """프로필 묶음 → 코드의 채널 순서로 정렬한 튜플. 다섯 채널이 하나씩 정확히 있어야 한다."""
    items = tuple(profiles)
    if not all(isinstance(item, ChannelProfile) for item in items):
        raise _invalid("채널 프로필", detail="채널 프로필(ChannelProfile)만 들어 있어야 한다")
    keys = [item.key for item in items]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise _invalid("채널 프로필", detail="같은 채널이 두 번 들어 있습니다: " + wording.quoted(duplicated, names=wording.CHANNEL_KO), dev=f"겹친 채널: {duplicated}")
    absent = [key for key in CHANNELS if key not in keys]
    if absent:
        raise _invalid("채널 프로필", detail="빠진 채널이 있습니다: " + wording.quoted(absent, names=wording.CHANNEL_KO) + " — 다섯 채널이 모두 있어야 합니다", dev=f"빠진 채널: {absent}")
    return tuple(sorted(items, key=lambda item: CHANNELS.index(item.key)))


def profiles_to_dict(profiles):
    """채널 프로필 다섯 개 → 저장 모양(`schema` 2). 다시 `profiles_from_dict` 로 읽으면 같은 프로필이 된다."""
    return {"schema": SCHEMA, "profiles": [item.to_dict() for item in _ordered(profiles)]}


def profiles_from_dict(data):
    """저장된 모양 → 채널 프로필 다섯 개(코드의 채널 순서). `schema`(1 이나 2)·정확한 칸을 요구하고 모르는 칸·빠진 채널·겹친 채널·틀린 값은 `CONTENT_INVALID` 로 거절한다. 판 1 은 새 칸이 빈 기본값으로 채워진다(파일은 바뀌지 않는다).
    더 새로운 판(3 이상)은 이 프로그램이 읽을 수 없어 거절한다."""
    version = data.get("schema") if isinstance(data, dict) else None
    if not isinstance(data, dict) or type(version) is not int or version not in SCHEMAS:
        newer = isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA
        raise _invalid("채널 프로필 저장 형식", detail=f"{wording.FILE_KEY_KO['schema']}가 1이나 2인 채널 프로필 파일이 아닙니다" + (" — 더 새로운 프로그램이 만든 파일이면 프로그램을 업데이트하세요" if newer else ""),
                       dev="저장된 채널 프로필의 모양(schema 1·2)이 아니다")
    if set(data) != {"schema", "profiles"}:
        raise _invalid("채널 프로필 저장 형식", detail=wording.quoted(("schema", "profiles"), names=wording.FILE_KEY_KO) + " 두 칸만 있어야 합니다", dev="schema 와 profiles 두 칸만 있어야 한다")
    items = data["profiles"]
    if not isinstance(items, list):
        raise _invalid("채널 프로필 저장 형식", detail=f"{wording.quote(wording.FILE_KEY_KO['profiles'])} 은 여러 개를 담는 목록이어야 합니다", dev="profiles 는 목록이어야 한다")
    return _ordered(ChannelProfile.from_dict(item, schema=version) for item in items)


__all__ = [
    "CHANNELS", "CHANNEL_ALIAS", "COLOR_PRESETS", "ChannelProfile", "DEFAULT_PROFILES", "FACTOR_LABELS", "FACTOR_NAMES", "FOLLOW_UP_PER_POST", "GRADE_CUTOFFS", "HOLD_DAYS", "LANGUAGES", "MAX_CHANNELS_PER_TOPIC",
    "PER_SEED", "PROFILE_FIELD_KO", "SCHEMA", "SCHEMAS", "SOURCE_MIX", "SeedQuota", "TREND_USES", "USE_NONE", "USE_PRIMARY", "USE_REFERENCE", "USE_SUPPORTING", "Weights", "at_entry", "canonical", "default_profiles", "explain", "invalid_in",
    "is_slug", "is_tag",
    "profiles_from_dict", "profiles_to_dict",
]
