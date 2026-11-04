"""화면 상태와 뷰모델 — 순수 파이썬(화면 도구를 모른다). Qt 화면은 여기서 만든 값(딕셔너리)을 그리기만 한다: 목록을 거르거나 문구를 만들거나 어떤 상태인지 정하는 일은 여기서 한다.

계층: View(`ui/qt/`) → AppState(이 파일: 뷰모델·화면 동작) → HomeProvider(`services.py`: 가짜 서비스 또는 실제 서비스 어댑터) / JobRunner(`jobs.py`: 작업 스레드).
화면 상태 여섯: loading · normal · empty · error · partial · offline. 영문 값(상태·추세 코드)과 내부 번호는 뷰모델에 담기지 않는다 — 오류 코드는 `diagnostic_text` 에만.
"""
from __future__ import annotations

import datetime
import re
import sys

from .jobs import JobFailure, JobRunner
from .notify import ToastPolicy
from .services import PRIORITY_RANK, FakeHomeProvider
from .text import NO_DATA, T, date_text, fmt_demand, fmt_docs

NAV = (("home", "nav_home", "home"), ("topics", "nav_topics", "search"), ("draft", "nav_draft", "draft"), ("history", "nav_history", "history"),
       ("blogs", "nav_blogs", "blogs"), ("settings", "nav_settings", "settings"))
MAX_NAV = 6                                                          # 사이드바 메뉴는 6개를 넘기지 않는다(운영자 기준)
LIST_STATES = ("loading", "normal", "empty", "error", "partial", "offline")
HOME_CHIPS = (("all", "chip_all"), ("a", "chip_a"), ("b", "chip_b"), ("hot", "chip_hot"), ("new", "chip_new"))
HOME_ROWS = 5                                                        # 홈의 추천 행은 다섯 개까지
LOAD_KEY = "home-load"
BLOG_NAMES = {"A": "블로그 A", "B": "블로그 B"}
STATUS_LABEL = {"new": "새 후보", "selected": "선택됨", "hold": "보류"}
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


def topic_vm(topic, selected=False):
    category = shown(topic.category, 40)                                            # 분야를 아는 후보만 — 모르면 분야를 말하지 않는다(아이콘은 장식이라 분야가 아니다)
    blogs =[{"key": key, "label": BLOG_NAMES[key]} for key in topic.blogs if key in BLOG_NAMES]
    first = blogs[0] if blogs else {"key": "", "label": ""}
    return {
        "id": topic.id, "title": shown(topic.title, 200), "desc": shown(topic.desc), "keywords": [shown(word, 80) for word in topic.keywords[:3]], "blogs": blogs, "blog": first["key"], "blog_label": first["label"],
        "demand": fmt_demand(topic.demand), "docs": fmt_docs(topic.docs), "demand_missing": topic.demand is None, "docs_missing": topic.docs is None,
        "trend": trend_vm(topic), "icon": topic.icon, "tone": topic.tone, "priority": topic.priority, "status": STATUS_LABEL.get(topic.status, ""),
        "reason": shown(topic.reason), "post_type": shown(topic.post_type, 40), "hold": topic.status == "hold", "selected": selected,
        "thumb": {"icon": topic.icon, "tone": topic.tone, "label": T["thumb_label"].format(category=category) if category else T["thumb_label_plain"], "category": category, "state_text": T["img_state_none"]},
        "a11y": T["row_a11y"].format(title=shown(topic.title, 200), blog=first["label"] or "블로그 미정", priority=topic.priority or NO_DATA),
    }


class AppState:
    def __init__(self, provider=None, *, today=None, runner=None):
        self.provider = provider or FakeHomeProvider()
        self.runner = runner or JobRunner()
        self.today = today                                           # 시험에서 날짜를 고정할 때
        self.toasts = ToastPolicy()
        self.page = "home"
        self.list_state = "loading"
        self.data = None
        self.failure = None
        self.failed_at = None
        self.home_filter = "all"
        self.selected = None
        self.tip_visible = True
        self.drawer_id = None
        self.load_count = 0                                          # 불러오기를 시작한 횟수(시험·진단용)

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
        live = self._live()
        self.selected = live[0].id if live else None
        self.home_filter = "all"

    def apply_failure(self, failure, when=None):
        """불러오기가 실패했다 — 이전에 보이던 데이터는 지우지 않는다(다시 시도하면 이어서 쓸 수 있다). 상태에는 **비밀 모양을 가린 글**만 남긴다(키·입력한 글이 상태·화면에 남지 않게)."""
        self.failure, self.failed_at = clean_failure(failure), when
        self.list_state = "error"

    def apply_unexpected(self, error, when=None):
        """화면 스레드의 슬롯 안에서 예상하지 못한 예외가 났다(예: 이상한 데이터로 목록을 만들다가) — '불러오는 중' 에 멈추지 않고 오류 상태로 바꾼다.
        받아 둔 값이 이상해서 난 것일 수 있어 버리고(다시 불러오면 새로 받는다), 쉬운 문장 + 예외 이름(진단 정보용)만 남긴다 — 예외의 내용(값·경로)은 남기지 않는다."""
        self.data, self.selected, self.drawer_id = None, None, None
        self.failure, self.failed_at = clean_failure(JobFailure(T["job_failed"], code=type(error).__name__)), when
        self.list_state = "error"

    def apply_cancelled(self):
        """불러오기를 취소했다 — 이미 받은 데이터가 있으면 그 모습으로 돌아가고, 없으면 '비어 있음'."""
        self.list_state = self._state_for(self.data)

    # ---- 홈 거르기 ----
    def _topics(self):
        return list(self.data.topics) if self.data else []

    def _live(self):
        live = [topic for topic in self._topics() if topic.status != "hold"]
        live.sort(key=lambda topic: topic.date, reverse=True)
        live.sort(key=lambda topic: PRIORITY_RANK.get(topic.priority, 9))
        return live

    @staticmethod
    def _match(topic, key):
        return {"all": True, "a": "A" in topic.blogs, "b": "B" in topic.blogs, "hot": topic.trend == "up", "new": topic.status == "new"}[key]

    def home_rows(self):
        return [topic for topic in self._live() if self._match(topic, self.home_filter)]

    def by_id(self, topic_id):
        return next((topic for topic in self._topics() if topic.id == topic_id), None)

    def set_home_filter(self, key):
        if key not in dict(HOME_CHIPS):
            return False
        self.home_filter = key
        rows = self.home_rows()[:HOME_ROWS]
        if not any(topic.id == self.selected for topic in rows):
            self.selected = rows[0].id if rows else None
        return True

    def select_topic(self, topic_id):
        if self.by_id(topic_id) is None:
            return False
        self.selected = topic_id
        return True

    def dismiss_tip(self):
        self.tip_visible = False

    # ---- 뷰모델 ----
    def _card(self, key, icon, tone, label, value, sub, go):
        text = T["sum_none"] if value is None else f"{value}개"
        return {"key": key, "icon": icon, "tone": tone, "label": label, "value": text, "sub": sub, "go": go, "missing": value is None, "a11y": f"{label} {text if value is not None else NO_DATA}"}

    def home_view(self):
        data = self.data
        live = self._live()
        held = [topic for topic in self._topics() if topic.status == "hold"]
        new = sum(1 for topic in live if topic.status == "new")
        done, pub = (data.done, data.pub) if data else (None, None)

        def week(total, week_value):
            if total is None:
                return T["sum_unavailable"]
            return "" if week_value is None else T["sum_week_sub"].format(n=week_value)

        cards = [
            self._card("topics", "draft", "blue", T["sum_topics"], len(live) if data else None, T["sum_topics_sub"].format(n=new) if data else T["sum_unavailable"], "topics"),
            self._card("done", "check_circle", "green", T["sum_done"], done, week(done, data.done_week if data else None), None),
            self._card("pub", "calendar_check", "purple", T["sum_pub"], pub, week(pub, data.pub_week if data else None), None),
            self._card("ideas", "bulb", "orange", T["sum_ideas"], len(held) if data else None, T["sum_ideas_sub"] if data else T["sum_unavailable"], "topics"),
        ]
        count = lambda key: sum(1 for topic in live if self._match(topic, key))        # noqa: E731
        chips = [{"key": key, "label": T[label], "count": count(key), "active": key == self.home_filter} for key, label in HOME_CHIPS]
        rows = self.home_rows()[:HOME_ROWS]
        selected = self.selected if any(topic.id == self.selected for topic in rows) else (rows[0].id if rows else None)
        state = self.list_state
        partial = state == "partial"
        views = []
        for topic in rows:
            view = topic_vm(topic, topic.id == selected)
            if partial and "trend" in (data.partial if data else ()):
                view["trend"] = {"key": "none", "label": NO_DATA, "icon": None}
            views.append(view)
        banner = {"partial": ("alert", T["partial"]), "offline": ("cloud_off", T["offline"])}.get(state)
        blogs = [{"key": blog.key, "name": shown(blog.name, 40), "category": shown(blog.category, 40), "total": blog.total, "month": blog.month, "candidates": blog.candidates,
                  "total_text": NO_DATA if blog.total is None else f"{blog.total:,}", "month_text": NO_DATA if blog.month is None else f"{blog.month:,}",
                  "candidates_text": "" if blog.candidates is None else f"{blog.candidates:,}"} for blog in (data.blogs if data else ())]
        quick = [
            {"key": "new", "icon": "plus", "title": T["q_new"], "desc": T["q_new_d"], "primary": True},
            {"key": "saved", "icon": "folder", "title": T["q_saved"], "desc": T["q_saved_d"], "primary": False},
            {"key": "history", "icon": "history", "title": T["q_hist"], "desc": T["q_hist_d"], "primary": False},
            {"key": "blogs", "icon": "settings", "title": T["q_set"], "desc": T["q_set_d"], "primary": False},
        ]
        return {
            "title": T["home_title"], "sub": T["home_sub"], "date": date_text(self.today), "sample": bool(data and data.sample), "sample_tag": T["sample_tag"], "state": state,
            "fetched": T["last_fetch"].format(when=data.fetched) if data and data.fetched else "", "cards": cards, "chips": chips,
            "section": {"title": T["rec_title"], "desc": T["rec_desc"], "all": T["rec_all"], "refresh": T["refresh"]}, "rows": views, "selected": selected, "banner": banner,
            "loading": {"text": T["loading"], "cancel": T["load_cancel"], "a11y": T["loading_a11y"]},
            "empty": {"title": T["empty_title"], "desc": T["empty_desc"], "button": T["empty_btn"]},
            "error": {"title": T["error_title"], "desc": T["error_desc"], "button": T["retry"], "diag": diagnostic_text(self.failure, self.failed_at) if self.failure else "",
                      "user": getattr(self.failure, "user_message", "") if self.failure else ""},
            "rail": {"blogs_title": T["rail_blogs"], "blogs_sub": T["rail_blogs_sub"].format(n=len(blogs)), "blogs": blogs, "quick_title": T["rail_quick"], "quick": quick,
                     "tip": {"visible": self.tip_visible, "title": T["tip_title"], "text": T["tip_text"], "close": T["tip_close"]}},
        }

    def drawer_view(self):
        topic = self.by_id(self.drawer_id) if self.drawer_id else None
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
        if self.by_id(topic_id) is None:
            return False
        self.drawer_id = topic_id
        return True

    def close_drawer(self):
        opened, self.drawer_id = self.drawer_id, None
        return opened

    def page_view(self):
        """홈이 아닌 화면 — 아직 만들지 않은 화면은 솔직하게 '만들고 있어요' 라고 알린다."""
        names = {key: T[label] for key, label, _icon in NAV}
        return {"key": self.page, "name": names.get(self.page, ""), "title": T["soon_title"], "desc": T["soon_desc"], "button": T["soon_btn"]}

    # ---- 눌림 → 안내 문구 ----
    def soon(self, name):
        """아직 만들지 않은 기능 — 동작하는 척하지 않고 안내만 한다."""
        return T["soon_toast"].format(name=name)

    def quick(self, key):
        """빠른 작업 — 화면 이동이면 이동하고 문구는 비운다, 만들지 않은 기능이면 안내 문구를 돌려준다."""
        target = {"saved": "topics", "history": "history", "blogs": "blogs"}.get(key)
        if target:
            self.nav(target)
            return ""
        return self.soon(T["q_new"])

    def draft_requested(self, topic_id, blog):
        topic = self.by_id(topic_id)
        return self.soon(T["make_small"]) if topic is not None else ""
