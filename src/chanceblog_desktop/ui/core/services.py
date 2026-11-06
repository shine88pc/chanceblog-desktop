"""화면이 쓰는 서비스의 인터페이스와 가짜 서비스 — 화면은 이 모양만 안다. 실제 서비스 층(`service/`)은 얇은 어댑터(`ui/adapters.py`)가 같은 모양으로 맞춘다.

원칙(운영자 요구): 목업의 숫자·이미지를 실제 데이터처럼 하드코딩하지 않는다 — 가짜 데이터는 `FakeHomeProvider` 안에만 있고 `sample=True` 라서 화면에 '예시 데이터' 표시가 붙는다.
가져올 수 없는 값은 `None` 이고 화면은 그 값을 보이지 않거나 '데이터 없음' 으로 둔다(지어내지 않는다). 네트워크·파일·서비스 층을 부르지 않는다. PySide6 를 모른다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from .jobs import JobCancelled, JobFailure

ServiceFailure = JobFailure                        # 서비스가 실패를 알리는 예외(쉬운 문장 + 진단 코드)

SCENARIOS = ("normal", "empty", "error", "partial", "offline")
PRIORITY_RANK = {"높음": 0, "보통": 1, "낮음": 2}


@dataclass(frozen=True)
class Topic:
    """추천 주제 한 줄. 내부 번호(`id`)와 영문 값(`status`·`trend`)은 화면에 나가지 않는다."""
    id: str
    title: str
    blogs: tuple = ()                 # ("A",) · ("B",) · ("A", "B") · () — A·B 는 네이버 블로그 A·B
    desc: str = ""
    keywords: tuple = ()
    post_type: str = ""
    status: str = "new"               # new · selected · hold
    priority: str = "보통"             # 높음 · 보통 · 낮음
    date: str = ""
    demand: object = None             # 월 검색량(없으면 None)
    docs: object = None               # 관련 블로그 글 수
    trend: object = None              # up · flat · down · None
    mobile: object = None             # 모바일 비중(0~100)
    season: object = None
    written: object = None            # 이미 쓴 글이 있는지(모르면 None)
    icon: str = "t_spark"
    tone: str = "blue"
    reason: str = ""
    category: str = ""                # 분야(아는 경우만 — 비어 있으면 이미지 자리 표시 설명에 분야를 말하지 않는다). 아이콘은 장식이라 분야를 뜻하지 않는다


@dataclass(frozen=True)
class BlogInfo:
    key: str                          # "A" · "B"
    name: str
    category: str = ""
    total: object = None              # 총 글(없으면 None)
    month: object = None              # 이번 달 글
    candidates: object = None         # 후보 수


@dataclass(frozen=True)
class HomeData:
    topics: tuple = ()
    blogs: tuple = ()
    done: object = None               # 작성 완료 글 수(집계할 수 없으면 None)
    done_week: object = None
    pub: object = None
    pub_week: object = None
    sample: bool = False              # 가짜(예시) 데이터인가 — 참이면 화면에 '예시 데이터' 표시
    fetched: str = ""                 # 마지막 조회(사람이 읽는 글)
    offline: bool = False             # 저장해 둔 값으로 보여 주는 중
    partial: tuple = field(default_factory=tuple)      # 못 가져온 지표 이름들(예: ("trend",))


class HomeProvider:
    """홈 화면 데이터 공급자 공통 모양 — `load_home(progress, cancelled)` 는 작업 스레드에서 불린다(화면 스레드가 아니다)."""
    sample = False

    def load_home(self, progress, cancelled):
        raise NotImplementedError

    def connections_provider(self):
        """이 공급자와 짝인 설정 화면 공급자 — 홈 공급자를 고르면(`--sample`·`--data-dir`) 설정 화면도 같은 쪽을 읽는다(화면 진입점 `run(provider)` 의 모양을 그대로 두려는 연결).
        따로 정하지 않은 공급자는 예시 데이터를 돌려준다(화면에 '예시 데이터' 표시가 붙어서 실제 값으로 오해하지 않는다)."""
        return FakeConnectionsProvider()


def _wait(seconds, progress, cancelled):
    end = time.monotonic() + seconds
    while True:
        if cancelled():
            raise JobCancelled()
        left = end - time.monotonic()
        if left <= 0:
            return
        if seconds:
            progress(1 - left / seconds, "")
        time.sleep(min(0.02, left))


# 가짜 후보 — 숫자는 모두 예시다. (제목·설명은 이 프로그램용으로 새로 쓴 글이다)
_SAMPLE = (
    ("자취방 곰팡이 없애는 순서", ("A",), "문제 해결형", "new", "높음", "2026-11-02", "곰팡이가 생긴 곳부터 환기 습관까지, 순서대로 따라 하는 정리", ("곰팡이 제거", "환기 요령", "습기"),
     8600, 4120, "up", 78, "장마철·겨울", False, "t_droplet", "blue", "겨울에 결로가 늘어 찾는 사람이 많아지는 시기이고 아직 쓴 글이 없습니다."),
    ("전기요금 절약 방법", ("A",), "정보형", "new", "높음", "2026-11-01", "집에서 바로 해 볼 수 있는 절약 습관을 모아 정리", ("전기요금", "절약 팁", "대기전력"),
     24300, 17880, "flat", 71, "겨울·여름", False, "t_bolt", "orange", "난방·냉방 철마다 되풀이해서 찾는 주제라 꾸준히 읽힙니다."),
    ("노트북 배터리 오래 쓰는 법", ("A",), "문제 해결형", "selected", "높음", "2026-11-01", "수명을 늘리는 사용 습관과 설정을 한 번에 확인", ("배터리 관리", "충전 습관", "IT 글감"),
     19100, 12450, "up", 66, None, True, "t_laptop", "purple", "독자가 겪는 불편이 분명하고 해결 순서를 나누어 쓰기 좋습니다."),
    ("프리랜서 종합소득세 신고 순서", ("B",), "정보형", "new", "높음", "2026-11-01", "처음 신고하는 분도 따라 할 수 있는 단계별 안내", ("종합소득세", "경비 처리", "신고 준비물"),
     15700, 7360, "up", 62, "5월", False, "t_calc", "green", "해마다 같은 시기에 다시 찾는 주제입니다."),
    ("에어프라이어 고르는 기준", ("B",), "비교형", "new", "보통", "2026-10-31", "용량·세척·소음까지 따져 보는 구매 가이드", ("에어프라이어", "가전 비교", "구매 가이드"),
     11200, 16940, "flat", 80, None, False, "t_box", "blue", "제품을 비교하는 글을 찾는 사람이 많고 표로 정리하기 좋습니다."),
    ("무선 이어폰 비교 포인트", ("B",), "비교형", "new", "보통", "2026-10-31", "구매 전에 기준을 정리해 주는 비교표", ("무선 이어폰", "노이즈 캔슬링", "배터리 시간"),
     None, None, None, None, None, None, "t_headphones", "purple", "구매 전에 기준을 정리해 주는 글이라 비교표가 도움이 됩니다."),
    ("겨울철 실내 습도 관리", ("A",), "정보형", "hold", "보통", "2026-10-30", "가습기 사용법과 결로를 막는 요령", ("실내 습도", "가습기", "결로"),
     6300, 3780, "down", 69, "겨울", True, "t_droplet", "green", "계절성이 있어 시기를 보고 쓰는 편이 좋습니다. 지금은 잠시 미뤄 둡니다."),
    ("주말 근교 조용한 카페 모음", ("B",), "장소·업체 정보형", "hold", "보통", "2026-10-30", "직접 가 본 곳만 골라 사진과 함께 소개", ("근교 카페", "나들이", "주말"),
     None, None, None, None, None, None, "t_coffee", "orange", "직접 가 본 경험이 필요한 주제라 사진과 후기를 모은 뒤에 씁니다."),
)
_FIELDS = ("title", "blogs", "post_type", "status", "priority", "date", "desc", "keywords", "demand", "docs", "trend", "mobile", "season", "written", "icon", "tone", "reason")
SAMPLE_CATEGORY = {"t_droplet": "생활·집", "t_bolt": "생활·에너지", "t_laptop": "IT·기기", "t_calc": "재테크·세금", "t_box": "쇼핑·가전", "t_headphones": "쇼핑·가전", "t_coffee": "장소·맛집", "t_spark": "기타"}      # 예시 후보만 분야를 안다(실제 후보는 분야를 모른다)
_BLOGS = (BlogInfo("A", "블로그 A", "생활 정보", 64, 6, 4), BlogInfo("B", "블로그 B", "IT · 재테크", 41, 4, 4))


def sample_topics(count=None):
    """가짜 후보(같은 입력이면 같은 결과). count 가 8 보다 크면 제목에 번호를 붙여 늘린다(성능 시험용)."""
    wanted = len(_SAMPLE) if count is None else count
    topics = []
    for index in range(wanted):
        values = dict(zip(_FIELDS, _SAMPLE[index % len(_SAMPLE)]))
        if index >= len(_SAMPLE):
            values["title"] = f"{values['title']} {index // len(_SAMPLE) + 1}"
        topics.append(Topic(id=f"s{index + 1}", category=SAMPLE_CATEGORY.get(values["icon"], ""), **values))
    return tuple(topics)


class FakeHomeProvider(HomeProvider):
    """네트워크·파일·서비스 층을 부르지 않는 가짜 공급자. `scenario` 로 화면의 여섯 상태를 만든다: normal · empty · error · partial · offline(+ 느린 일은 `delay`)."""
    sample = True

    def __init__(self, scenario="normal", delay=0.0, count=None):
        if scenario not in SCENARIOS:
            raise ValueError(scenario)
        self.scenario, self.delay, self.count = scenario, delay, count
        self.calls = 0

    def load_home(self, progress, cancelled):
        self.calls += 1
        _wait(self.delay, progress, cancelled)
        if self.scenario == "error":
            raise ServiceFailure("후보를 불러오는 중 연결이 끊겼어요.", code="SAMPLE_NETWORK_DOWN")
        topics = () if self.scenario == "empty" else sample_topics(self.count)
        if self.scenario == "partial":
            topics = tuple(Topic(**{**t.__dict__, "trend": None}) for t in topics)
        return HomeData(topics=topics, blogs=() if self.scenario == "empty" else _BLOGS, done=3, done_week=3, pub=2, pub_week=2, sample=True, fetched="오늘 09:12",
                        offline=self.scenario == "offline", partial=("trend",) if self.scenario == "partial" else ())


# ---- 연결 관리(설정 화면) — 키 값은 어디에도 없다: 이름·상태·사용량 숫자뿐이다 -------------------------------------------------------------
CONN_STATUSES = ("not_connected", "needs_check", "connected", "auth_error", "rate_limited")      # 서비스(`connections.STATUS_TEXT`)가 알려 주는 연결 상태 다섯 가지 — 내부 이름이라 화면은 문구표(`status_*`)로만 말한다
CONN_PROBLEMS = ("auth_error", "rate_limited")                                                       # 접이식 묶음을 처음부터 펼쳐 두는 '문제' 둘
GROUP_ORDER = ("data", "image", "ai", "publish")                                                     # 접이식 네 묶음의 순서
PURPOSE_GROUPS = {"naver_apihub": "data", "naver_searchad": "data", "naver_openapi": "data", "image_provider": "image", "ai_assist": "ai", "blogger": "publish", "github_repo": "publish"}
ON_DEMAND = ("naver_searchad",)                                                                      # 필요할 때만 보이는 용도 — 키 항목이 있거나 실제로 연결돼 있을 때만 카드로 보인다(옛 용도처럼. 운영자 통합 전달서 §34 '검색광고 API, 실제 연결 시에만')
CONN_SCENARIOS = ("normal", "empty", "error", "partial", "offline") + CONN_STATUSES                 # 화면의 여섯 상태 + 연결 상태 다섯 가지를 모든 용도에 입혀 보는 시나리오


@dataclass(frozen=True)
class EntryInfo:
    """저장된 키 항목 하나 — **키 값은 없다**(끝 글자도 없다). 이름은 사용자가 붙인 글이라 화면이 가린 뒤 줄인다."""
    name: str
    state: str = "active"             # active · standby · off — 키 사용 설정(내부 이름: 화면은 문구표로만 말한다)
    key_found: object = None          # 보관소에 이 항목의 키가 있나(True·False) — 확인하지 못했으면 None


@dataclass(frozen=True)
class UsageInfo:
    """한도 줄에 쓸 값. 못 읽은 값은 숫자를 지어내지 않고 `readable=False` 로 알린다."""
    rows: tuple = ()                  # ((기간, 쓴 수, 한도), …) — 기간은 이미 한국어('오늘'·'이번 달'·'최근 60분')
    attempts: bool = False            # 참이면 '시도'(실패한 호출도 센다), 아니면 '요청'
    console_limit: int = 0            # 서비스 콘솔의 월 한도(참고 값) — 0 이면 없음
    stage_text: str = ""              # 한도 단계 안내(70%·80%·90%)
    stop_text: str = ""               # 한도에 실제로 닿아 새 조회를 멈춘 때에만 서비스가 정한 고정 문구(다른 이유로 멈춘 때는 어댑터가 비운다)
    stop_cause: str = ""              # 멈춘 사유(쉬운 한국어 한 줄)
    resume_text: str = ""             # 다시 열리는 때
    readable: bool = True             # 거짓이면 사용량 기록을 못 읽었다
    fail_closed: bool = False         # 못 읽으면 새 조회를 멈추는 용도(NAVER API HUB)


@dataclass(frozen=True)
class PurposeInfo:
    """용도(키를 쓰는 서비스) 하나. `key` 는 묶음·설명 문장을 고르는 데만 쓰고 화면에는 나가지 않는다."""
    key: str
    label: str                        # 서비스 표(`connections.PURPOSES`)가 정한 한국어 이름
    implemented: bool = False         # 실제 호출 코드가 있나 — 없으면 '연결됨' 이 될 수 없다
    takes_keys: bool = True           # 거짓이면 앱이 키를 받지 않는다(GitHub 는 컴퓨터의 Git 로그인을 쓴다)
    max_entries: int = 3              # 키 항목 수 상한 — 1 이면 '예비'·'키 더하기' 가 없다
    rotation: str = "limited"         # never 면 어떤 오류에도 자동으로 다른 키로 넘어가지 않는다
    legacy: bool = False              # 옛 용도 — 새 항목은 더할 수 없다(항목이 남아 있을 때만 보인다)
    status: str = ""                  # 연결 상태 다섯 가지 중 하나 — 키를 받지 않는 용도는 ''
    entries: tuple = ()
    usage: object = None              # UsageInfo 또는 None(한도를 아직 모르는 용도)
    on_demand: bool = False           # 필요할 때만 보이는 용도(`ON_DEMAND`) — 키 항목이 있거나 실제로 연결돼 있을 때만 카드로 보인다


@dataclass(frozen=True)
class ConnectionsData:
    purposes: tuple = ()
    sample: bool = False              # 가짜(예시) 데이터인가 — 참이면 화면에 '예시 데이터' 표시와 숫자 옆 '예시' 꼬리표
    fetched: str = ""                 # 마지막으로 읽은 때(사람이 읽는 글)
    offline: bool = False
    partial: tuple = field(default_factory=tuple)        # 못 읽은 것들: ("keystore",) · ("usage",)


class ConnectionsProvider:
    """설정 화면(연결 관리) 데이터 공급자 공통 모양 — `load_connections(progress, cancelled)` 는 작업 스레드에서 불린다. 읽기만 한다."""
    sample = False

    def load_connections(self, progress, cancelled):
        raise NotImplementedError


# 가짜 용도 표 — 서비스 표(`connections.PURPOSES`)와 같은 열쇠·이름·키 항목 수·전환 규칙이다(시험이 둘을 견준다). 예시에서만 이미지 공급자를 '호출 코드가 있는 용도' 로 두어 '연결됨' 모양을 보인다(실제 서비스는 모두 준비 중이다).
_CONN_TABLE = (           # (열쇠, 이름, 호출 코드, 키를 받나, 항목 수 상한, 전환, 옛 용도)
    ("naver_apihub", "NAVER API HUB 검색어 트렌드", False, True, 1, "never", False),
    ("naver_searchad", "네이버 검색광고 API", False, True, 3, "limited", False),
    ("image_provider", "이미지 공급자", True, True, 3, "never", False),
    ("ai_assist", "AI 보조(선택)", False, True, 3, "limited", False),
    ("blogger", "Blogger", False, True, 3, "limited", False),
    ("github_repo", "GitHub 저장소", False, False, 3, "never", False),
    ("naver_openapi", "옛 항목 — 네이버 오픈 API(검색·데이터랩)", False, True, 3, "limited", True),
)
_CONN_BASE = {            # 열쇠 → (연결 상태, 항목들, 한도 줄) — 'normal' 시나리오(다섯 가지 상태가 한 화면에 섞여 보인다)
    "naver_apihub": ("needs_check", (EntryInfo("예시 키 1", "active", True),), UsageInfo((("오늘", 12, 100), ("이번 달", 340, 27000)), True, 30000, fail_closed=True)),
    "naver_searchad": ("rate_limited", (EntryInfo("예시 키 A", "active", True), EntryInfo("예시 키 B", "standby", True)), UsageInfo(resume_text="오늘 18:00 이후 자동 재개")),
    "image_provider": ("connected", (EntryInfo("예시 키 1", "active", True),), UsageInfo((("최근 60분", 7, 50),))),
    "ai_assist": ("not_connected", (), None),
    "blogger": ("auth_error", (EntryInfo("예시 키 1", "active", True),), None),
    "github_repo": ("", (), None),
}


def sample_connections(scenario="normal"):
    """가짜 용도들(같은 입력이면 같은 결과). `normal` 은 연결 상태 다섯 가지가 섞여 보이고, 상태 이름(`needs_check` …)을 주면 키를 쓰는 모든 용도에 그 상태를 입힌다
    (`connected` 는 호출 코드가 있는 용도에만 — 서비스가 그렇게 돌려준다). `not_connected` 는 키를 하나도 넣지 않은 처음 모습이다."""
    purposes = []
    for key, label, implemented, takes_keys, max_entries, rotation, legacy in _CONN_TABLE:
        status, entries, usage = _CONN_BASE.get(key, ("not_connected", (), None))
        if legacy:
            continue                                                  # 옛 용도는 항목이 남아 있을 때만 보인다 — 예시에는 남은 항목이 없다
        if scenario in CONN_STATUSES and takes_keys:
            if scenario == "not_connected":                           # 키를 하나도 넣지 않은 처음 모습
                status, entries, usage = "not_connected", (), None
            else:
                status = "needs_check" if scenario == "connected" and not implemented else scenario
                entries = entries or (EntryInfo("예시 키 1", "active", True),)
        if usage is not None and usage.resume_text and status != "rate_limited":
            usage = None                                              # 다시 열리는 때는 한도에 닿은 용도에만 있다
        if scenario == "partial":                                     # 키 보관소를 열지 못했다 — 키가 있는지 모르니 '연결됨' 일 수 없고, 사용량 기록도 못 읽은 곳이 있다
            status = "needs_check" if status == "connected" else status
            entries = tuple(replace(item, key_found=None) for item in entries)
            usage = UsageInfo(readable=False, fail_closed=True) if key == "naver_apihub" else usage
        purposes.append(PurposeInfo(key, label, implemented, takes_keys, max_entries, rotation, False, status if takes_keys else "", entries, usage, key in ON_DEMAND))
    return tuple(purposes)


class FakeConnectionsProvider(ConnectionsProvider):
    """네트워크·파일·보관소·서비스 층을 부르지 않는 가짜 공급자. `scenario` 로 화면의 여섯 상태와 연결 상태 다섯 가지를 만든다(`CONN_SCENARIOS`)."""
    sample = True

    def __init__(self, scenario="normal", delay=0.0):
        if scenario not in CONN_SCENARIOS:
            raise ValueError(scenario)
        self.scenario, self.delay = scenario, delay
        self.calls = 0

    def load_connections(self, progress, cancelled):
        self.calls += 1
        _wait(self.delay, progress, cancelled)
        if self.scenario == "error":
            raise ServiceFailure("연결 설정 파일을 열 수 없었어요. 파일은 고치거나 지우지 않았어요.", code="SAMPLE_CONNECTIONS_UNREADABLE")
        purposes = () if self.scenario == "empty" else sample_connections(self.scenario)
        return ConnectionsData(purposes=purposes, sample=True, fetched="오늘 09:12", offline=self.scenario == "offline",
                               partial=("keystore", "usage") if self.scenario == "partial" else ())
