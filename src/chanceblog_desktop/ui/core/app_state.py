"""화면 상태와 뷰모델 — 순수 파이썬(화면 도구를 모른다). Qt 화면은 여기서 만든 값(딕셔너리)을 그리기만 한다: 목록을 거르거나 문구를 만들거나 어떤 상태인지 정하는 일은 여기서 한다.

계층: View(`ui/qt/`) → AppState(이 파일: 뷰모델·화면 동작) → HomeProvider(`services.py`: 가짜 서비스 또는 실제 서비스 어댑터) / JobRunner(`jobs.py`: 작업 스레드).
화면 상태 여섯: loading · normal · empty · error · partial · offline. 영문 값(상태·추세 코드)과 내부 번호는 뷰모델의 **글**에 없다 — 오류 코드는 `diagnostic_text` 에만(`id` 같은 열쇠는 눌렀을 때 서랍에 넘기는 값이지 글이 아니다).
홈(UI-C1d, D-201)은 KPI 넷·Naver A 추천·Naver B 추천·작성 중 초안·최근 발행·연결 요약을 그린다(`board_view.py` 가 만든 `board`) — 옛 요약 카드·추천 목록(칩·선택)·오른쪽 패널(내 블로그 현황·빠른 작업·활용 팁)은 없어졌고 그 값을 만들던 코드도 지웠다.
"""
from __future__ import annotations

import datetime
import re
import sys

from . import board_view as bv
from . import settings_view as sv
from .jobs import JobFailure, JobRunner
from .notify import ToastPolicy
from .services import GROUP_ORDER, FakeConnectionsProvider, FakeHomeProvider
from .text import NO_DATA, T, fmt_demand, fmt_docs

# 실제 Navigation — **완성된 화면만** 둔다(홈·설정). 열 수 있는 화면은 모두 여기 있고 `screens.SCREEN_BUILDERS` 에 만드는 함수가 있다(시험이 같은 열쇠인지 지킨다).
# 화면이 완성되면 메뉴 한 줄 + 화면 한 줄을 같이 더한다 — 메뉴 개수 상한은 두지 않는다(옛 `MAX_NAV = 6` 은 UI-C1a 에서 없앴다: 운영자 2026-11-06 확인 요청 004 · D-155 ⑤).
NAV = (("home", "nav_home", "home"), ("settings", "nav_settings", "settings"))
# 묶음(핵심 작업 / 데이터·관리 / 시스템) — (묶음 열쇠, 이름 문구 열쇠, 그 묶음의 실제 메뉴 열쇠들). **묶음 이름은 그 묶음에 실제 메뉴가 있을 때만 보인다**(`nav_groups`).
NAV_GROUPS = (("core", "nav_group_core", ("home",)), ("data", "nav_group_data", ()), ("system", "nav_group_system", ("settings",)))
# '다음 단계' 목록 — 아직 만들지 않은 화면의 **이름만**(열 수 없다: 메뉴·화면 이동·단추가 없다). 화면이 완성되면 여기서 빼고 NAV 에 더한다. (열쇠, 이름 문구 열쇠, 아이콘)
NEXT_STEPS = (("topics", "nav_topics", "search"), ("draft", "nav_draft", "draft"), ("history", "nav_history", "calendar_check"), ("seed", "nav_seed", "sprout"), ("blogs", "nav_blogs", "book"))
LIST_STATES = ("loading", "normal", "empty", "error", "partial", "offline")


def nav_groups():
    """보이는 메뉴 묶음 — 실제 메뉴가 하나라도 있는 묶음만 `[(묶음 열쇠, 이름 문구 열쇠, [(메뉴 열쇠, 이름 문구 열쇠, 아이콘), …]), …]`. 비어 있는 묶음은 이름도 보이지 않는다."""
    items = {item[0]: item for item in NAV}
    return [(key, label, [items[menu] for menu in menus]) for key, label, menus in NAV_GROUPS if menus]
LOAD_KEY = "home-load"
CONN_KEY = "settings-load"                                           # 설정 화면(연결 관리)을 읽는 작업의 이름 — 홈 불러오기와 따로 돈다
BLOG_NAMES = {"A": "블로그 A", "B": "블로그 B"}
TREND_ICON = {"up": "trend_up", "flat": "trend_flat", "down": "trend_down"}
# 오류 한 줄에서 지울 경로의 시작 모양 넷 — ① 드라이브 경로(`C:\`·`C:/`; 앞이 영숫자면 `https:/` 같은 주소의 한 조각이라 아니다) ② 네트워크 경로(`\\서버\공유`)
# ③ 유닉스식·사용자 폴더 경로(`/home/…`·`경로:/home/…`·`//서버/…`·`~/…`; 앞이 낱말 글자·`./\~<>-` 이면 날짜(`11/04`)·`a/b`·닫는 태그(`</p>`)지 경로가 아니고, `//` 앞이 `:` 이면 주소(`https://…`)다) ④ `file:///home/…`(유닉스식 파일 주소 — 주소 머리 `file://`(대소문자 무관) 바로 뒤의 세 번째 `/` 가 경로의 시작이다; 윈도 `file:///C:/…` 는 ① 이 이미 잡는다)
_PATH_START = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\|(?<![\w.:/\\~<>-])//|(?<![\w./\\~<>-])(?:~[\\/]|/(?=[\w.~-]))|(?<=(?<![A-Za-z0-9])(?i:file)://)/(?=[\w.~-])")
_LINE_BREAKS = "\r\n\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"                      # `str.splitlines()` 가 줄을 가르는 글자 — 경로 안에는 있을 수 없다
_PATH_END = {quote: re.compile((re.escape(quote) + "(?![A-Za-z0-9])|" if quote else "") + "[" + _LINE_BREAKS + "]") for quote in ("", "'", '"', "`")}     # 따옴표 뒤가 영숫자면(`O'Brien`) 닫는 따옴표가 아니다


def shown(value, limit=300):
    """화면에 나가는 외부 글(후보 제목·설명·키워드 …)에서 비밀 모양을 가리고 한 줄로 줄인다 — 명령줄 출력과 같은 규칙(`security/mask.py`)."""
    from ...security.mask import safe_detail
    return safe_detail(value, limit)


def clean_failure(failure):
    """실패의 문장·코드에서 비밀 모양을 가리고 길이를 줄인 사본 — 어떤 값이 와도 예외를 내지 않는다."""
    from ...security.mask import safe_detail
    return JobFailure(safe_detail(getattr(failure, "user_message", "") or T["job_failed"], 200), code=safe_detail(getattr(failure, "code", "") or "", 80),
                      retryable=bool(getattr(failure, "retryable", True)))


def diagnostic_text(failure, when=None):
    """오류 상태의 '진단 정보'(기본 화면에는 안 보이고 펼칠 때만) — 오류 코드와 시각뿐이다. 입력한 글·키는 담지 않고 비밀 모양은 가린다."""
    from ...security.mask import safe_detail
    stamp = (when or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    code = safe_detail(getattr(failure, "code", "") or "UNKNOWN", 80)
    return f"{T['diag_code']}: {code}\n{T['diag_when']}: {stamp}"


def erase_paths(text):
    """글 속 절대 경로를 `(경로)` 로 바꾼다(드라이브·네트워크·유닉스식·`~` 경로). **경로에는 공백이 들어 있을 수 있어**(사용자 이름 `Jane Doe` 나 `Program Files` 폴더처럼) 공백에서 끊으면 이름 조각(`Doe`)이 남는다 —
    따옴표로 연 경로는 짝이 되는 따옴표 앞까지, 아니면 그 줄 끝까지 지운다(어디서 끝나는지 알 수 없을 때는 더 많이 지우는 쪽이 안전하다). 같은 글에 경로가 여럿이어도 한 번 훑는다(글 길이에 선형)."""
    pieces, pos = [], 0
    while True:
        found = _PATH_START.search(text, pos)
        if found is None:
            break
        start = found.start()
        quote = text[start - 1] if start and text[start - 1] in "'\"`" else ""
        end = _PATH_END[quote].search(text, found.end())
        pieces += [text[pos:start], "(경로)"]
        pos = end.start() if end else len(text)
    pieces.append(text[pos:])
    return "".join(pieces)


def unexpected_line(kind, value):
    """처리하지 못한 예외 하나를 표준 오류에 남길 **한 줄**로 — 예외 이름 + 비밀 모양을 가리고 경로를 지운 짧은 글. 추적(traceback)은 내지 않는다(경로·값이 들어 있다). 어떤 값이 와도 예외를 내지 않는다."""
    name = getattr(kind, "__name__", "") or "Exception"
    try:
        from ...security.mask import _strip_invisible                                  # 경로 시작을 보이지 않는 글자로 쪼개 지우기를 피하는 것을 막는다(`C:\u200b\Users\…`)
        text = str(value)
        for separator in _LINE_BREAKS:                                            # 줄을 가르는 글자는 경로가 끝나는 곳 — 보이지 않는 글자 지우기(이 중 일부도 지운다)보다 먼저 줄바꿈 하나로 통일한다
            text = text.replace(separator, "\n")
        detail = shown(erase_paths(_strip_invisible(text)), 120)                              # 경로를 지운 뒤 가리고(→) 줄인다 — 가리기가 자르기보다 먼저(줄 끝까지 지우므로 줄바꿈이 한 칸으로 합쳐지기 전에 지운다)
    except Exception:
        detail = ""
    return f"{T['unexpected_line']} ({name})" + (f": {detail}" if detail else "")


def report_unexpected(kind, value, stream=None):
    """처리하지 못한 예외를 `unexpected_line` 한 줄로 표준 오류에 남긴다(조용한 실패 금지 — 원인이 어디에도 안 남지 않게). 남겼으면 True. 표준 오류를 쓸 수 없어도 예외를 내지 않는다(이 함수는 오류를 처리하는 중에 불린다).
    **표준 오류가 없는 실행**(`pythonw`·창 없는 exe — `sys.stderr` 가 None)에서는 남길 곳이 없어 False 를 돌려준다(`print(file=None)` 은 표준 출력으로 가므로 그대로 두면 아무것도 안 남았는데 True 가 된다) — 이 묶음은 파일을 쓰지 않는다(읽기 전용);
    로그 파일은 설치 파일 묶음에서 정한다."""
    target = stream if stream is not None else sys.stderr
    if target is None:
        return False
    try:
        print(unexpected_line(kind, value), file=target)
        return True
    except Exception:
        return False


def trend_vm(topic):
    if topic.trend not in TREND_ICON:
        return {"key": "none", "label": NO_DATA, "icon": None}
    return {"key": topic.trend, "label": T["trend_" + topic.trend], "icon": TREND_ICON[topic.trend]}


class AppState:
    def __init__(self, provider=None, *, runner=None, connections=None, version=None):
        self.provider = provider or FakeHomeProvider()
        self.runner = runner or JobRunner()
        self.version = version                                       # 앱이 이미 읽어 둔 버전(`VersionInfo`) — 설정 화면의 '정보' 묶음이 보인다. 이 순수 상태는 파일을 읽지 않는다(못 받으면 '개발 버전')
        self.toasts = ToastPolicy()
        self.page = "home"
        self.list_state = "loading"
        self.data = None
        self.failure = None
        self.failed_at = None
        self.drawer_id = None
        self.load_count = 0                                          # 불러오기를 시작한 횟수(시험·진단용)
        # 설정 화면(연결 관리) — 홈과 따로 읽고 따로 상태를 가진다(같은 여섯 상태 틀)
        paired = getattr(self.provider, "connections_provider", None)
        self.conn_provider = connections if connections is not None else (paired() if paired else FakeConnectionsProvider())
        self.conn_state = "loading"
        self.conn_data = None
        self.conn_failure = None
        self.conn_failed_at = None
        self.conn_loaded_at = None
        self.conn_open = None                                        # 펼친 묶음 이름들 — None 이면 아직 정하지 않았다(처음 받은 데이터로 정한다). 화면을 껐다 켜도 기억할 뿐 파일에는 쓰지 않는다
        self.conn_load_count = 0

    # ---- 메뉴 ----
    def nav(self, key):
        if key not in {item[0] for item in NAV} or key == self.page:
            return False
        self.page = key
        self.drawer_id = None
        return True

    # ---- 불러오기(작업 스레드) ----
    @property
    def loading(self):
        return self.runner.running(LOAD_KEY)

    def start_load(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """홈 데이터를 작업 스레드에서 불러온다. 이미 불러오는 중이면(중복 클릭) None 을 돌려주고 아무것도 하지 않는다. 콜백은 **작업 스레드에서** 불린다 — 화면은 시그널로 받아 `apply_*` 를 부른다."""
        job = self.runner.start(LOAD_KEY, self.provider.load_home, on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return None
        self.load_count += 1
        self.list_state = "loading"
        return job

    def cancel_load(self):
        self.runner.cancel(LOAD_KEY)

    @staticmethod
    def _state_for(data):
        if data is None or not data.topics:
            return "empty"
        return "offline" if data.offline else "partial" if data.partial else "normal"

    def apply_home(self, data):
        """불러온 데이터를 받아 상태를 정한다(화면 스레드에서 부른다)."""
        self.data, self.failure = data, None
        self.list_state = self._state_for(data)

    def apply_failure(self, failure, when=None):
        """불러오기가 실패했다 — 이전에 보이던 데이터는 지우지 않는다(다시 시도하면 이어서 쓸 수 있다). 상태에는 **비밀 모양을 가린 글**만 남긴다(키·입력한 글이 상태·화면에 남지 않게)."""
        self.failure, self.failed_at = clean_failure(failure), when
        self.list_state = "error"

    def apply_unexpected(self, error, when=None):
        """화면 스레드의 슬롯 안에서 예상하지 못한 예외가 났다(예: 이상한 데이터로 목록을 만들다가) — '불러오는 중' 에 멈추지 않고 오류 상태로 바꾼다.
        받아 둔 값이 이상해서 난 것일 수 있어 버리고(다시 불러오면 새로 받는다), 쉬운 문장 + 예외 이름(진단 정보용)만 남긴다 — 예외의 내용(값·경로)은 남기지 않는다."""
        self.data, self.drawer_id = None, None
        self.failure, self.failed_at = clean_failure(JobFailure(T["job_failed"], code=type(error).__name__)), when
        self.list_state = "error"

    def apply_cancelled(self):
        """불러오기를 취소했다 — 이미 받은 데이터가 있으면 그 모습으로 돌아가고, 없으면 '비어 있음'."""
        self.list_state = self._state_for(self.data)

    # ---- 홈 ----
    def _topics(self):
        return list(self.data.topics) if self.data else []

    def by_id(self, topic_id):
        """옛 후보 저장소의 후보 하나(번호로) — 없으면 None."""
        return next((topic for topic in self._topics() if topic.id == topic_id), None)

    def drawer_topic(self, topic_id):
        """상세 서랍이 그릴 후보 — 옛 후보 저장소의 후보이거나, 홈의 **추천 줄**(주제 엔진 후보 — `board_view.drawer_topic` 이 서랍의 기존 칸에 맞춰 이 줄이 아는 값만 채운다). 둘 다 아니면 None."""
        topic = self.by_id(topic_id)
        return topic if topic is not None else bv.drawer_topic(self.data, topic_id)

    @staticmethod
    def _banner(data, state):
        """홈 위쪽 안내 띠 — 오프라인·일부 지표 없음. 읽는 중·오류에는 띠가 없고(그 상태가 자기 안내를 가진다), 옛 후보가 하나도 없어도(`empty`) 띠는 데이터가 말하는 대로 보인다(추천 구역은 옛 후보와 별개다)."""
        if data is None or state in ("loading", "error"):
            return None
        if data.offline:
            return ("cloud_off", T["offline"])
        if data.partial:
            return ("alert", T["partial"])
        return None

    def home_view(self):
        """홈 뷰모델 — 제목·설명·상태·안내 띠·읽는 중·오류·다시 불러오기와 새 구역(`board`: KPI 넷·추천 둘·작성 중 초안·최근 발행·연결 요약). 구역마다 따로 상태를 가진다(`board_view.py`)."""
        data, state = self.data, self.list_state
        return {
            "title": T["home_title"], "sub": T["home_sub"], "sample": bool(data and data.sample), "sample_tag": T["sample_tag"], "state": state,
            "fetched": T["last_fetch"].format(when=data.fetched) if data and data.fetched else "", "refresh": T["refresh"], "banner": self._banner(data, state),
            "loading": {"text": T["loading"], "cancel": T["load_cancel"], "a11y": T["loading_a11y"]},
            "error": {"title": T["error_title"], "desc": T["error_desc"], "button": T["retry"], "diag": diagnostic_text(self.failure, self.failed_at) if self.failure else "",
                      "user": getattr(self.failure, "user_message", "") if self.failure else ""},
            "board": bv.build_board_view(data, state, conn_data=self.conn_data, conn_state=self.conn_state, conn_loading=self.conn_loading),
        }

    def drawer_view(self):
        topic = self.drawer_topic(self.drawer_id) if self.drawer_id else None
        if topic is None:
            return None
        split = NO_DATA if topic.mobile is None else T["split_value"].format(pc=100 - topic.mobile, mobile=topic.mobile)
        written = None if topic.written is None else (T["written_yes"] if topic.written else T["written_no"])
        trend = trend_vm(topic)
        fields = [(T["d_demand"], fmt_demand(topic.demand)), (T["d_split"], split), (T["d_docs"], fmt_docs(topic.docs)), (T["d_trend"], trend["label"]),
                  (T["d_season"], shown(topic.season, 80) if topic.season else NO_DATA), (T["d_written"], written or NO_DATA), (T["d_sub"], shown(", ".join(topic.keywords)) or NO_DATA),
                  (T["d_date"], shown(topic.date, 40) or NO_DATA)]
        blogs = [{"key": key, "label": T["draft_a"] if key == "A" else T["draft_b"]} for key in topic.blogs if key in BLOG_NAMES]
        return {"id": topic.id, "title": T["drawer_title"], "topic": shown(topic.title, 200), "blog_label": BLOG_NAMES.get(topic.blogs[0], "") if topic.blogs else "", "priority": topic.priority or NO_DATA,
                "reason_title": T["d_reason"], "reason": shown(topic.reason) or NO_DATA, "fields": [{"label": a, "value": b, "missing": b == NO_DATA} for a, b in fields],
                "drafts": blogs, "hold": T["hold"], "more": T["more"], "close": T["drawer_close"], "sample": bool(self.data and self.data.sample), "sample_tag": T["sample_tag"]}

    def open_drawer(self, topic_id):
        if self.drawer_topic(topic_id) is None:
            return False
        self.drawer_id = topic_id
        return True

    def close_drawer(self):
        opened, self.drawer_id = self.drawer_id, None
        return opened

    # ---- 설정 화면(연결 관리) — 읽기만 한다 ----
    @property
    def conn_loading(self):
        return self.runner.running(CONN_KEY)

    def start_conn_load(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """연결 정보(키 항목의 이름·상태, 사용량 기록)를 작업 스레드에서 읽는다 — 보관소 읽기도 여기서 한다(화면 스레드를 막지 않는다). 이미 읽는 중이면(중복 클릭) None 을 돌려주고 아무것도 하지 않는다.
        처음이거나 오류 뒤에는 '읽는 중' 모습이 되고, 이미 보이는 내용이 있으면 그대로 둔 채 새 값이 오면 바꾼다. 콜백은 **작업 스레드에서** 불린다."""
        job = self.runner.start(CONN_KEY, self.conn_provider.load_connections, on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return None
        self.conn_load_count += 1
        if self.conn_data is None or self.conn_state == "error":
            self.conn_state = "loading"
        return job

    @staticmethod
    def _conn_state_for(data):
        if data is None or not data.purposes:
            return "empty"
        return "offline" if data.offline else "partial" if data.partial else "normal"

    def apply_connections(self, data, when=None):
        """읽은 연결 정보를 받아 상태를 정한다(화면 스레드에서 부른다). 처음 받을 때 처음 펼칠 묶음(문제가 있는 첫 묶음, 없으면 '데이터')을 정하고, 그 뒤에는 사용자가 펴고 접은 대로 둔다."""
        self.conn_data, self.conn_failure, self.conn_loaded_at = data, None, when
        self.conn_state = self._conn_state_for(data)
        if self.conn_open is None:
            self.conn_open = {sv.default_open(data.purposes)}

    def apply_conn_failure(self, failure, when=None):
        """읽기가 실패했다 — 이전에 보이던 정보는 지우지 않는다. 상태에는 **비밀 모양을 가린 글**만 남긴다."""
        self.conn_failure, self.conn_failed_at = clean_failure(failure), when
        self.conn_state = "error"

    def apply_conn_unexpected(self, error, when=None):
        """화면 스레드의 슬롯 안에서 예상하지 못한 예외가 났다 — 받아 둔 값을 버리고 오류 상태로(쉬운 문장 + 예외 이름만 진단 정보에)."""
        self.conn_data = None
        self.conn_failure, self.conn_failed_at = clean_failure(JobFailure(T["job_failed"], code=type(error).__name__)), when
        self.conn_state = "error"

    def apply_conn_cancelled(self):
        self.conn_state = self._conn_state_for(self.conn_data)

    def set_group_open(self, key, opened):
        """접이식 묶음을 펴거나 접는다(기억만 하고 파일에는 쓰지 않는다 — 읽기 전용). 묶음은 용도 묶음 넷과 '정보'(`sv.INFO_GROUP`) 다섯이고, 모르는 묶음 이름은 False."""
        if key not in GROUP_ORDER and key != sv.INFO_GROUP:
            return False
        keep = set(self.conn_open or ())
        if opened:
            keep.add(key)
        else:
            keep.discard(key)
        self.conn_open = keep
        return True

    def settings_view(self):
        """설정 화면 뷰모델 — 만드는 일은 `settings_view.py`(순수)가 한다. 오류 상태의 진단 정보는 홈과 같은 규칙(오류 코드·시각뿐)이다."""
        diag = diagnostic_text(self.conn_failure, self.conn_failed_at) if self.conn_failure else ""
        return sv.build_settings_view(self.conn_data, self.conn_state, failure=self.conn_failure, error_diag=diag, loaded_at=self.conn_loaded_at, open_groups=self.conn_open, version=self.version)

    # ---- 눌림 → 안내 문구 ----
    def soon(self, name):
        """아직 만들지 않은 기능 — 동작하는 척하지 않고 안내만 한다."""
        return T["soon_toast"].format(name=name)

    def draft_requested(self, topic_id, blog):
        """상세 서랍의 초안 단추 — 아직 만들지 않은 기능이라 안내 문구만 돌려준다(없는 후보면 빈 글)."""
        return self.soon(T["make_small"]) if self.drawer_topic(topic_id) is not None else ""
