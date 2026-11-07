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


# ---- 홈 데이터(UI-C1c) — 읽기만 한다 ----------------------------------------------------------------------------------------------------------
# 새 홈(Naver A·B 추천·작성 중 초안·최근 발행·연결 요약)이 쓸 값. **아래 값에는 쓰기 메서드도 월 검색량·문서 수 칸도 없다**(운영자 2026-11-06 확인 요청 004 의 답 — 홈 구성·추천 후보·최근 발행).
# 구역마다 따로 읽어 따로 성공·실패한다 — 한 구역(또는 글 하나)을 읽지 못해도 홈 전체를 막지 않는다. 지금 화면은 이 값을 그리지 않는다(새 홈 모양 UI-C1d 가 그린다).
HOME_LIMIT = 5                                 # 홈의 구역마다 최대 5개 — 채널별 추천(A·B)·작성 중 초안·최근 발행
HOME_CHANNELS = ("A", "B")                     # 홈이 읽는 채널 — 네이버 A·B(코드 안의 채널 이름은 어댑터만 안다)
INTERESTS = ("rising", "flat", "falling")      # 관심도(최근 상대값의 방향) — 영문 값은 내부 이름이고 화면은 문구표로만 말한다. 모르면 None(관심도 데이터 부족)
STAGES = ("generated", "review")               # 작성 중 초안의 단계 — 초안 생성됨 · 검토 필요(둘 다 승인 전)
NO_STORE = ("missing", "old")                  # 주제 엔진 보관함이 아직 없다 · 옛 구조라 읽지 않았다 — 읽기만 하는 화면이라 만들지도 올리지도 않는다


@dataclass(frozen=True)
class RecommendRow:
    """주제 엔진 후보 한 줄. `score` 는 엔진의 최종 점수(정수) 또는 None(점수 계산 전), `prev_score` 는 이전 점수(없으면 None — 변화량을 숨긴다). `id` 는 어댑터가 건네는 내부 번호이고 뷰모델에는 나가지 않는다."""
    id: str
    title: str
    score: object = None
    prev_score: object = None
    interest: object = None           # rising · flat · falling · None(관심도 데이터 부족)
    sample: bool = False              # 가짜(예시) 값인가 — 참이면 줄에 '예시' 표시


@dataclass(frozen=True)
class ChannelRead:
    """홈이 읽은 채널 하나(A·B)의 추천 구역 — 이름·후보 생성 사용 여부·우수 후보 줄들. 구역마다 따로 성공·실패한다."""
    key: str                          # "A" · "B"
    name: str = ""                    # 표시 이름 — 런타임에 채널 프로필에서 읽는다(코드·시험·문서에 실제 이름이 없다)
    enabled: object = None            # 후보 생성이 켜져 있나(True·False, 모르면 None)
    state: str = "ok"                 # ok · unavailable(보관함이 없거나 옛 구조라 읽지 않았다) · failed
    reason: str = ""                  # unavailable 일 때 `NO_STORE` 중 하나
    rows: tuple = ()                  # RecommendRow — 많아야 `HOME_LIMIT` 개(읽는 쪽이 자른다)
    skipped: int = 0                  # 점수를 확인할 수 없어 뺀 후보 수(서비스가 알려 준 만큼)
    failure: object = None            # failed 일 때 ServiceFailure(쉬운 문장 + 진단 코드)


@dataclass(frozen=True)
class DraftRow:
    """작성 중 초안 한 줄(승인 전 — 초안 생성됨·검토 필요)."""
    id: str
    title: str
    stage: str = "generated"          # `STAGES`
    updated: str = ""                 # 마지막으로 고친 때(UTC `YYYY-MM-DDTHH:MM:SSZ`) — 모르면 ""
    sample: bool = False


@dataclass(frozen=True)
class RecentRow:
    """최근 발행 한 줄."""
    id: str
    title: str
    published: object = None          # 발행한 때(UTC `YYYY-MM-DDTHH:MM:SSZ`) — 모르면 None('발행일 확인 불가'). 마지막으로 고친 때(`updated_at`)로 대신하지 않는다
    sample: bool = False


@dataclass(frozen=True)
class ListRead:
    """글 구역(작성 중 초안·최근 발행) 하나를 읽은 결과 — 글 하나를 읽지 못해도 구역은 남고(`skipped`), 구역 전체를 못 읽으면 `failed`."""
    state: str = "ok"                 # ok · failed
    rows: tuple = ()                  # DraftRow 또는 RecentRow — 많아야 `HOME_LIMIT` 개
    skipped: int = 0                  # 읽지 못해 건너뛴 글 수
    failure: object = None            # failed 일 때 ServiceFailure


@dataclass(frozen=True)
class BoardData:
    """홈의 새 구역 데이터 — 채널 둘의 추천·작성 중 초안·최근 발행. 이 값이 없으면(`HomeData.board` 가 None) 그 공급자는 새 구역을 읽지 않는다 = '연결 전'."""
    channels: tuple = ()              # ChannelRead — A, B 순서
    drafts: ListRead = ListRead()
    recent: ListRead = ListRead()
    sample: bool = False              # 가짜(예시) 데이터인가


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
    board: object = None              # BoardData — 새 홈 구역의 값(UI-C1c). None 이면 이 공급자는 읽지 않는다('연결 전')


class HomeProvider:
    """홈 화면 데이터 공급자 공통 모양 — `load_home(progress, cancelled)` 는 작업 스레드에서 불린다(화면 스레드가 아니다)."""
    sample = False

    def load_home(self, progress, cancelled):
        raise NotImplementedError

    def connections_provider(self):
        """이 공급자와 짝인 설정 화면 공급자 — 홈 공급자를 고르면(`--sample`·`--data-dir`) 설정 화면도 같은 쪽을 읽는다(화면 진입점 `run(provider)` 의 모양을 그대로 두려는 연결).
        따로 정하지 않은 공급자는 예시 데이터를 돌려준다(화면에 '예시 데이터' 표시가 붙어서 실제 값으로 오해하지 않는다)."""
        return FakeConnectionsProvider()

    def blogs_provider(self):
        """이 공급자와 짝인 블로그 관리 화면 공급자(P4b) — 홈 공급자를 고르면(`--sample`·`--data-dir`) 블로그 관리도 같은 쪽을 쓴다. 따로 정하지 않은 공급자는 **메모리에서만 일하는 예시**를 돌려준다(저장해도 이 PC 에 아무것도 남지 않는다)."""
        from .blogs import FakeBlogsProvider
        return FakeBlogsProvider()


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


# 가짜 홈 구역(UI-C1c) — 이름·점수·날짜는 모두 예시다(`sample=True` 라 줄마다 '예시' 표시가 붙는다). 점수 없음·관심도 없음·이전 점수 없음·점수가 오르고 내림·발행일 모름이 한 번씩 들어 있다.
_SAMPLE_RECOMMEND = {         # 채널 → ((제목, 점수, 이전 점수, 관심도), …)
    "A": (("자취방 곰팡이 없애는 순서", 92, 88, "rising"), ("전기요금 절약 방법", 84, 84, "flat"), ("노트북 배터리 오래 쓰는 법", 79, 83, "falling"),
          ("겨울철 실내 습도 관리", 71, None, None), ("에어프라이어 세척 순서", None, None, None)),
    "B": (("프리랜서 종합소득세 신고 순서", 88, 80, "rising"), ("에어프라이어 고르는 기준", 80, 80, "flat"), ("무선 이어폰 비교 포인트", 68, 70, "falling"),
          ("주말 근교 조용한 카페 모음", 65, None, "rising")),
}
_SAMPLE_DRAFTS = (("프리랜서 종합소득세 신고 순서", "review", "2026-11-06T02:10:00Z"), ("전기요금 절약 방법", "generated", "2026-11-05T09:30:00Z"), ("노트북 배터리 오래 쓰는 법", "review", "2026-11-04T23:40:00Z"))
_SAMPLE_RECENT = (("자취방 곰팡이 없애는 순서", "2026-11-03T01:00:00Z"), ("에어프라이어 고르는 기준", "2026-10-30T05:20:00Z"), ("겨울철 실내 습도 관리", None))


def sample_board(scenario="normal"):
    """가짜 홈 구역들(같은 입력이면 같은 결과). `empty` 는 채널·글 구역이 모두 정상 빈 상태이고 `partial`(관심도를 못 가져옴)은 모든 줄의 관심도가 비어 있다. 모두 예시라 줄마다 `sample=True`."""
    if scenario not in SCENARIOS:
        raise ValueError(scenario)
    empty, partial = scenario == "empty", scenario == "partial"
    channels = tuple(ChannelRead(key, f"블로그 {key}", True, "ok", "", () if empty else tuple(
        RecommendRow(f"r{key}{number}", title, score, prev, None if partial else interest, True) for number, (title, score, prev, interest) in enumerate(_SAMPLE_RECOMMEND[key], start=1)))
        for key in HOME_CHANNELS)
    drafts = () if empty else tuple(DraftRow(f"d{number}", title, stage, updated, True) for number, (title, stage, updated) in enumerate(_SAMPLE_DRAFTS, start=1))
    recent = () if empty else tuple(RecentRow(f"p{number}", title, published, True) for number, (title, published) in enumerate(_SAMPLE_RECENT, start=1))
    return BoardData(channels, ListRead("ok", drafts), ListRead("ok", recent), True)


class FakeHomeProvider(HomeProvider):
    """네트워크·파일·서비스 층을 부르지 않는 가짜 공급자. `scenario` 로 화면의 여섯 상태를 만든다: normal · empty · error · partial · offline(+ 느린 일은 `delay`).
    `board` 는 새 홈 구역(UI-C1c)의 값 — 기본 `"auto"` 는 시나리오에 맞는 예시(`sample_board`), `None` 이면 새 구역을 읽지 않는 공급자('연결 전'), `BoardData` 면 그대로 쓴다."""
    sample = True

    def __init__(self, scenario="normal", delay=0.0, count=None, board="auto"):
        if scenario not in SCENARIOS:
            raise ValueError(scenario)
        self.scenario, self.delay, self.count, self.board = scenario, delay, count, board
        self.calls = 0

    def load_home(self, progress, cancelled):
        self.calls += 1
        _wait(self.delay, progress, cancelled)
        if self.scenario == "error":
            raise ServiceFailure("후보를 불러오는 중 연결이 끊겼어요.", code="SAMPLE_NETWORK_DOWN")
        topics = () if self.scenario == "empty" else sample_topics(self.count)
        if self.scenario == "partial":
            topics = tuple(Topic(**{**t.__dict__, "trend": None}) for t in topics)
        board = sample_board(self.scenario) if isinstance(self.board, str) and self.board == "auto" else self.board
        return HomeData(topics=topics, blogs=() if self.scenario == "empty" else _BLOGS, done=3, done_week=3, pub=2, pub_week=2, sample=True, fetched="오늘 09:12",
                        offline=self.scenario == "offline", partial=("trend",) if self.scenario == "partial" else (), board=board)


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
