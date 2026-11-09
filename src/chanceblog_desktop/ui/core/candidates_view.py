"""주제 후보 화면의 상태·동작·뷰모델 — 순수 파이썬(화면 도구를 모른다). Qt 화면은 `view()`·`detail_view()` 가 만든 딕셔너리를 그리기만 한다: 어떤 후보를 보일지·어느 단추를 켤지·어떤 문장을 보일지는 여기서 정한다.

흐름과 규칙:
  · **읽기와 쓰기를 가른다**: 화면을 열고(`start_load`) 거르고 찾고 고르고 상세를 열고 창 크기를 바꾸는 것은 파일에 닿지 않는다. 파일에 쓰는 일은 `start_make` 하나뿐이고 확인창에서 `만들기` 를 눌렀을 때만 불린다(공급자의 `make_candidates` — 작업 스레드에서).
    만들 후보를 미리 보는 `start_preview` 는 읽기뿐이다. **자동 실행은 없다**: 화면을 열 때·앱을 열 때 후보를 만들지 않는다.
  · **확인창이 먼저다**: `make_dialog` 를 부르지 않고(= 확인창을 보이지 않고) `start_make` 를 부르면 아무것도 하지 않는다(`unconfirmed`). 새 후보가 하나도 없으면(`can_make` 가 거짓) 확인창도 쓰기 길도 없고 무엇이 모자란지 `prep` 카드가 말한다.
    취소·Esc 로 확인창을 닫으면 '확인창을 보였다' 표시도 거둔다. 만드는 중에 또 눌러도 새로 시작하지 않는다(`busy`).
  · 실패하면(다른 창이 씀·디스크 가득·쓰기 실패·더 새 판·깨진 보관함·설정 파일) 종류별 쉬운 문장을 보이고 **후보 목록은 그대로**다(서비스가 한 트랜잭션이라 쓰기 전 상태 그대로).
  · 선택은 컨트롤러가 들고 있어 상세 창 방식(고정 ↔ 서랍)이 바뀌어도 유지된다. 서랍 방식으로 줄 때 서랍이 저절로 열리지는 않는다. 닫기·Esc 는 선택을 푼다.
  · 점수·구간은 홈과 같은 규칙(`candidate_rules`)이고, 점수를 확인할 수 없어 뺀 후보는 개수로만 알린다. 후보가 수백 개여도 한 번에 `PAGE` 장만 그린다. 오류 문장은 쉬운 말뿐이다(파이썬 목록·내부 예외·오류 코드·경로 없음).
실제 후보 제목·키워드·블로그 이름은 이 코드에 없다(저장된 값을 보이기만 하고, 보일 때는 비밀 모양을 가린 뒤 줄인다).
"""
from __future__ import annotations

import re

from . import candidate_rules as rules
from . import gauges as G
from .candidates import CandidateFailure
from .draft_rules import BLOG_NAMES
from .drafts import DraftTarget
from .jobs import JobFailure
from .text import T

LOAD_KEY = "candidates-load"                                 # 후보를 읽는 작업의 이름(홈·설정·Seed 읽기와 따로 돈다)
WRITE_KEY = "candidates-write"                               # 미리 보기·후보 만들기 작업 — 한 번에 하나(중복 클릭은 거절)
LAYOUT_MODES = ("fixed", "drawer")
FAILURE_TEXT = {"busy": "cand_fail_busy", "disk": "cand_fail_disk", "io": "cand_fail_io", "newer": "cand_fail_newer", "corrupt": "cand_fail_corrupt", "invalid": "cand_fail_invalid", "other": "cand_fail_other"}
LACK_TEXT = {"no_channel": "cand_prep_no_channel", "no_seed": "cand_prep_no_seed", "full": "cand_prep_full", "none": "cand_prep_none"}
HEX_ID = re.compile(r"tc-[a-z_]+-[a-z_]+-([0-9a-f]{16})")    # 엔진이 만드는 후보 번호의 모양 — 앞 8자만 화면에 보인다(`service/topics.py::short_ref` 와 같은 규칙 — 시험이 견준다)


def short_number(candidate_id):
    """화면에 보일 짧은 번호 — 엔진 번호의 16진수 부분 앞 8자(모양이 다르면 번호 앞 8자). 번호 전체·내부 번호는 화면에 나가지 않는다."""
    found = HEX_ID.fullmatch(candidate_id)
    return found.group(1)[:8] if found else candidate_id[:8]


class CandidatesController:
    def __init__(self, provider, runner):
        self.provider, self.runner = provider, runner
        self.state = "loading"
        self.data = None
        self.failure = None
        self.failed_at = None
        self.channel, self.status, self.band, self.cluster, self.query = "all", "all", "all", "all", ""
        self.limit = rules.PAGE
        self.more_filters = False
        self.selected = None                                 # 고른 후보 번호(내부 열쇠 — 글이 아니다)
        self.opened = False                                  # 서랍 방식에서 서랍이 열려 있나(고정 방식에서는 고른 후보가 늘 보인다)
        self.mode = "fixed"                                  # 상세 창 방식 — 셸이 창 폭으로 정해 알려 준다(`set_layout`)
        self.notice = None                                   # (수준, 글) — 마지막 동작의 결과
        self.pending = None                                  # 돌고 있는 일: {"kind": "plan"|"make"}
        self.preview = None                                  # 읽어 본 미리 보기(`MakePreview`) — 확인창을 보이고 나서야 만든다
        self.make_asked = False
        self.load_count = 0
        self._index = {}
        self._notices = {}

    # ---- 읽기(파일·폴더를 만들지 않는다) ----
    @property
    def loading(self):
        return self.runner.running(LOAD_KEY)

    @property
    def busy(self):
        return self.runner.running(WRITE_KEY)

    def start_load(self, on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """후보를 작업 스레드에서 읽는다 — 이미 읽는 중이거나 미리 보기·만들기가 도는 중이면 None. 처음이거나 오류 뒤에는 '읽는 중' 모습이 되고, 보이는 내용이 있으면 그대로 둔 채 새 값이 오면 바꾼다."""
        if self.busy:
            return None
        job = self.runner.start(LOAD_KEY, self.provider.load_candidates, on_progress=on_progress, on_done=on_done, on_error=on_error, on_cancel=on_cancel)
        if job is None:
            return None
        self.load_count += 1
        if self.data is None or self.state == "error":
            self.state = "loading"
        return job

    def apply_loaded(self, data):
        self.data, self.failure = data, None
        self.state = "normal"
        self._index = {row.candidate.candidate_id: row for row in data.rows}
        self._notices = {}
        if self.selected is not None and self.selected not in self._index:
            self.selected, self.opened = None, False
        if self.channel != "all" and self.channel not in {item.key for item in self._channels_shown()}:
            self.channel = "all"
        if self.cluster != "all" and self.cluster not in rules.cluster_keys(data.rows):
            self.cluster = "all"
        return True

    def apply_load_failed(self, failure, when=None):
        """읽기가 실패했다 — 이전에 보이던 내용은 지우지 않는다(다시 읽으면 이어서 쓴다). 상태에는 비밀 모양을 가린 글만 남긴다."""
        from .app_state import clean_failure
        self.failure, self.failed_at = clean_failure(failure), when
        self.state = "error"

    def apply_unexpected(self, error, when=None):
        """화면 스레드의 슬롯에서 예상하지 못한 예외가 났다 — 받아 둔 값을 버리고 오류 상태로(쉬운 문장 + 예외 이름만 진단 정보에)."""
        from .app_state import clean_failure
        self.data, self.pending, self.preview, self.make_asked, self.selected, self.opened = None, None, None, False, None, False
        self._index, self._notices = {}, {}
        self.failure, self.failed_at = clean_failure(JobFailure(T["job_failed"], code=type(error).__name__)), when
        self.state = "error"

    def apply_cancelled(self):
        self.state = "normal" if self.data is not None else "error"

    # ---- 값 ----
    def rows(self):
        return self.data.rows if self.data is not None else ()

    def by_id(self):
        return self._index

    def _channels_shown(self):
        """채널 칩에 보이는 채널 — 후보가 있거나 후보 생성이 켜진 채널."""
        if self.data is None:
            return ()
        have = {row.candidate.channel for row in self.data.rows}
        return tuple(item for item in self.data.channels if item.key in have or item.enabled is True)

    def channel_info(self, key):
        """채널 하나의 표시 정보 — 프로필을 읽지 못한 채널은 이름이 비어 있으므로 서비스의 채널 이름으로 대신한다."""
        from ...topics import wording
        found = self.data.channel_map().get(key) if self.data is not None else None
        name = rules.shown(found.name, 30) if found is not None and found.name else ""
        return {"key": key, "name": name or wording.CHANNEL_KO.get(key, key), "preset": found.preset if found is not None else None, "weights": found.weights if found is not None else ()}

    def notices_of(self, row):
        """후보 하나의 안내들(안전 표시) — 보이는 카드·열린 상세에서만 부르고 기억한다(안전 평가가 후보 하나에 1~2ms)."""
        key = row.candidate.candidate_id
        if key not in self._notices:
            self._notices[key] = rules.notices_of(row.candidate)
        return self._notices[key]

    # ---- 거르기·찾기·더 보기(파일에 닿지 않는다) ----
    def _reset_page(self):
        self.limit = rules.PAGE

    def set_channel(self, key):
        if key != "all" and key not in {item.key for item in self._channels_shown()}:
            return False
        self.channel = key
        self._reset_page()
        return True

    def set_status(self, key):
        if key not in rules.STATUS_KEYS:
            return False
        self.status = key
        self._reset_page()
        return True

    def set_band(self, key):
        if key != "all" and key not in rules.BAND_KEYS:
            return False
        self.band = key
        self._reset_page()
        return True

    def set_cluster(self, key):
        if key != "all" and key not in rules.cluster_keys(self.rows()):
            return False
        self.cluster = key
        self._reset_page()
        return True

    def set_query(self, text):
        """검색 글 — 메모리에만 있다(파일·로그·표준 출력에 남기지 않는다)."""
        self.query = text if isinstance(text, str) else ""
        self._reset_page()
        return True

    def toggle_more_filters(self):
        self.more_filters = not self.more_filters
        return True

    def reset_filters(self):
        self.channel, self.status, self.band, self.cluster, self.query = "all", "all", "all", "all", ""
        self._reset_page()
        return True

    def filters_active(self):
        return (self.channel, self.status, self.band, self.cluster, bool(rules.query_words(self.query))) != ("all", "all", "all", "all", False)

    def show_more(self):
        self.limit += rules.PAGE
        return True

    def found(self):
        """거르기 조건에 맞는 후보들 — 점수가 높은 것부터."""
        words = rules.query_words(self.query)
        return rules.sort_rows([row for row in self.rows() if rules.matches(row, self.channel, self.status, self.band, self.cluster, words)])

    # ---- 고르기·상세(파일에 닿지 않는다) ----
    def select(self, candidate_id):
        """카드를 눌렀다 — 그 후보를 고르고 상세를 연다(서랍 방식이면 서랍이 열린다). 같은 후보를 다시 눌러도 열린 채다."""
        if candidate_id not in self._index:
            return False
        self.selected, self.opened = candidate_id, True
        if not self.busy:                                    # 마지막 동작의 결과 줄은 다음 동작 때 사라진다(만드는 중이라는 안내는 일이 끝날 때까지 둔다)
            self.notice = None
        return True

    def close_detail(self):
        """상세를 닫는다(고정 창이든 서랍이든) — 고른 것도 푼다. 닫은 후보의 번호(열쇠)를 돌려준다(열려 있지 않았으면 None)."""
        closed, self.selected, self.opened = self.selected, None, False
        return closed

    def hide_detail(self):
        """서랍을 닫는다(화면을 옮길 때) — 고른 후보는 그대로 둔다."""
        self.opened = False

    def set_layout(self, mode):
        """상세 창 방식(`fixed`·`drawer`)을 알린다 — 고른 후보는 방식이 바뀌어도 유지된다. 고정에서 서랍으로 바뀔 때 서랍이 저절로 열리지는 않는다(다시 누르면 열린다)."""
        if mode not in LAYOUT_MODES:
            return False
        if mode == "drawer" and self.mode == "fixed":
            self.opened = False
        self.mode = mode
        return True

    def selected_row(self):
        return self._index.get(self.selected) if self.selected is not None else None

    def drawer_wanted(self):
        """서랍 방식에서 서랍이 열려 있어야 하나 — 고른 후보가 있고 사용자가 열어 둔 때."""
        return self.mode == "drawer" and self.opened and self.selected_row() is not None

    # ---- 후보 만들기(미리 보기는 읽기뿐, 쓰기는 `start_make` 하나) ----
    def _start(self, kind, payload, work, callbacks):
        job = self.runner.start(WRITE_KEY, work, **callbacks)
        if job is None:
            return "busy", None
        self.pending = {"kind": kind, **payload}
        return "started", job

    def make_info(self):
        """`후보 만들기` 단추 `(켤 수 있나, 못 켜는 까닭)` — 후보를 읽은 뒤에만, 읽거나 만드는 중에는 안 된다."""
        if self.state == "loading" or self.loading:
            return False, T["cand_make_why_loading"]
        if self.state == "error" or self.data is None:
            return False, T["cand_make_why_error"]
        if self.busy:
            return False, T["cand_make_why_busy"]
        return True, ""

    def start_preview(self, **callbacks):
        """만들 후보를 미리 본다(읽기뿐 — 아무것도 쓰지 않는다). `(상태, 작업)`: `unavailable`(아직 못 읽음)·`busy`·`started`."""
        if not self.make_info()[0]:
            return ("busy" if self.busy or self.loading else "unavailable"), None
        provider = self.provider
        self.preview, self.make_asked = None, False
        started = self._start("plan", {}, lambda progress, cancelled: provider.preview_make(progress, cancelled), callbacks)
        if started[0] == "started":
            self.notice = ("info", T["cand_plan_working"])
        return started

    def make_dialog(self):
        """확인창의 글 — 새 후보 수·채널별 수·쓰는 Seed·건너뛰는 것·후보는 지워지지 않고 더해진다는 것·보관함을 처음 만들거나 옛 구조를 올리는 단계·키·네트워크를 쓰지 않는다는 것. 보인 뒤에만 `start_make` 가 쓴다. 만들 후보가 없으면 None."""
        preview = self.preview
        if preview is None or not preview.can_make:
            return None
        self.make_asked = True
        rows = " · ".join(T["cand_make_row"].format(name=rules.shown(item.name, 30), n=item.new) for item in preview.channels if item.new)
        lines = [T["cand_make_counts"].format(total=preview.total_new, rows=rows)]
        lines.append(T["cand_make_seeds"].format(used=preview.seeds_used, proposed=preview.seeds_proposed) if preview.seeds_proposed else T["cand_make_seeds_none_proposed"].format(used=preview.seeds_used))
        skips = list(dict.fromkeys(reason for item in preview.channels for reason in item.reasons))
        parts = [T["cand_make_skip_dup"].format(n=preview.duplicates)] if preview.duplicates else []
        shown_reasons = skips[:4]
        if shown_reasons or parts:
            more = [T["cand_make_skip_more"].format(n=len(skips) - 4)] if len(skips) > 4 else []
            lines.append(T["cand_make_skips"].format(items=", ".join([*parts, *shown_reasons, *more])))
        lines.append(T["cand_make_adds"])
        store_text = {"missing": "cand_make_store_missing", "empty": "cand_make_store_empty", "old_structure": "cand_make_store_old"}.get(preview.store)
        if store_text:
            lines.append(T[store_text])
        lines.append(T["cand_make_nokey"])
        return {"title": T["cand_make_title"].format(n=preview.total_new), "body": "\n".join(lines), "ok": T["cand_make_ok"], "cancel": T["cand_make_cancel"], "count": preview.total_new}

    def discard_make(self):
        """확인창을 확인 없이 닫았다(취소·Esc) — '확인창을 보였다' 표시를 거둔다."""
        self.make_asked = False

    def close_preview(self):
        """준비 안내 카드를 닫는다."""
        self.preview, self.make_asked = None, False
        return True

    def start_make(self, **callbacks):
        """확인창에서 `만들기` 를 눌렀을 때만 — 확인창을 보이지 않았거나 만들 후보가 없으면 아무것도 하지 않는다(`unconfirmed`·`unavailable`). 이미 도는 중이면 새로 시작하지 않는다(`busy`)."""
        preview = self.preview
        if self.data is None or preview is None or not preview.can_make:
            return "unavailable", None
        if self.busy:
            return "busy", None
        if not self.make_asked:
            return "unconfirmed", None
        self.make_asked = False
        provider = self.provider
        started = self._start("make", {"count": preview.total_new}, lambda progress, cancelled: provider.make_candidates(preview, progress, cancelled), callbacks)
        if started[0] == "started":
            self.notice = ("info", T["cand_make_working"])
        return started

    def apply_write_ok(self, result):
        """미리 보기나 만들기가 끝났다 — 미리 보기는 받아 두고, 만든 뒤에는 결과 알림 줄을 정한다(목록은 셸이 다시 읽는다)."""
        work, self.pending = self.pending or {"kind": "plan"}, None
        if work["kind"] == "plan":
            self.preview, self.make_asked, self.notice = result, False, None
            return
        self.preview, self.make_asked = None, False
        made = getattr(result, "made", 0)
        parts = [T["cand_made"].format(n=made) if made else T["cand_made_none"]]
        if getattr(result, "duplicates", 0):
            parts.append(T["cand_made_dup"].format(n=result.duplicates))
        if getattr(result, "withheld", 0):
            parts.append(T["cand_made_withheld"].format(n=result.withheld))
        self.notice = ("ok", " ".join(parts))

    def apply_write_failed(self, failure):
        """미리 보기나 만들기가 실패했다 — 후보 목록은 그대로다. 문장은 종류별로 정해진 쉬운 말뿐이다."""
        work, self.pending = self.pending or {"kind": "make"}, None
        kind = failure.kind if isinstance(failure, CandidateFailure) else "other"
        self.preview, self.make_asked = None, False
        if work["kind"] == "plan":
            self.notice = ("error", T["cand_plan_failed"] if kind in ("other", "invalid", "corrupt") else T[FAILURE_TEXT.get(kind, "cand_fail_other")])
        else:
            self.notice = ("error", T[FAILURE_TEXT.get(kind, "cand_fail_other")])
        return kind

    def apply_write_unexpected(self, error):
        self.pending, self.preview, self.make_asked = None, None, False
        self.notice = ("error", T["cand_fail_other"])

    # ---- 뷰모델 ----
    def _channel_vm(self, key):
        info = self.channel_info(key)
        return {"key": key, "name": info["name"], "avatar": rules.avatar_text(key, info["name"]), "preset": info["preset"]}

    def _card(self, row, sample):
        item = row.candidate
        info = self._channel_vm(item.channel)
        score, band = rules.score_of(item), G.score_band(rules.score_of(item))
        notices = self.notices_of(row)
        title = rules.shown(item.topic, rules.TITLE_LIMIT)
        chips, more = rules.keyword_chips(item)
        text = rules.summary(item)
        icon, tone = rules.topic_icon(item.topic_cluster)
        badges = rules.card_badges(item, row.stop, notices)
        spoken = T["cand_card_a11y"].format(title=title, channel=info["name"], score=score, band=band.name) if score is not None else T["cand_card_a11y_none"].format(title=title, channel=info["name"])
        hint = ", ".join([T["cand_card_state"].format(status=rules.status_name(item.work_status)), *[badge["text"] for badge in badges[1:]], T["cand_card_hint"]])
        selected = item.candidate_id == self.selected
        return {"id": item.candidate_id, "title": title, "summary": text or T["cand_summary_none"], "summary_missing": not text, "keywords": chips, "more": more, "more_text": T["cand_more_keywords"].format(n=more) if more else "",
                "badges": badges, "channel": info, "score": score, "ring": score is not None, "band": band.key if band else None, "band_label": band.name if band else "", "score_text": str(score) if score is not None else T["cand_score_none"],
                "icon": icon, "tone": tone, "image_state": T["cand_image_state"], "sample": sample, "sample_tag": T["cand_card_sample"] if sample else "", "selected": selected,
                "a11y": spoken + (", " + T["cand_card_sample"] if sample else ""), "desc": hint + (", " + T["cand_card_selected"] if selected else "")}

    def _chips(self, keys, labels, counts, current, a11y_key):
        return [{"key": key, "label": labels[key], "count": counts[key], "active": key == current, "a11y": T[a11y_key].format(name=labels[key], n=counts[key])} for key in keys]

    def _filters(self, data, found):
        rows = data.rows
        channels = self._channels_shown()
        channel_counts = rules.counts_by(rows, lambda item: item.channel, [item.key for item in channels])
        channel_labels = {"all": T["cand_all"], **{item.key: self.channel_info(item.key)["name"] for item in channels}}
        status_counts = rules.counts_by(rows, lambda item: item.work_status, rules.STATUS_KEYS[1:])
        status_labels = {"all": T["cand_all"], **{key: rules.status_name(key) for key in rules.STATUS_KEYS[1:]}}
        band_counts = rules.counts_by(rows, rules.band_key, rules.BAND_KEYS)
        band_labels = {"all": T["cand_all"], **{key: rules.band_name(key) for key in rules.BAND_KEYS}}
        clusters = rules.cluster_keys(rows)
        cluster_counts = rules.counts_by(rows, lambda item: item.topic_cluster, clusters)
        cluster_labels = {"all": T["cand_all"], **{key: rules.shown(rules.cluster_name(key), 30) for key in clusters}}
        more_open = self.more_filters or self.cluster != "all" or self.band != "all"                    # 점수 구간·주제 묶음 칩은 `더 거르기` 뒤에 있고 조건이 걸려 있으면 열린 채다(첫 화면에서 카드가 더 보이게 — 1366×768)
        shown = min(len(found), self.limit)
        return {"a11y": T["cand_filter_a11y"],
                "channel_title": T["cand_filter_channel"], "channel": self._chips(("all", *[item.key for item in channels]), channel_labels, channel_counts, self.channel, "cand_filter_channel_a11y"),
                "status_title": T["cand_filter_status"], "status": self._chips(rules.STATUS_KEYS, status_labels, status_counts, self.status, "cand_filter_status_a11y"),
                "band_title": T["cand_filter_band"], "band": self._chips(("all", *rules.BAND_KEYS), band_labels, band_counts, self.band, "cand_filter_band_a11y"),
                "cluster_title": T["cand_filter_cluster"], "cluster": self._chips(("all", *clusters), cluster_labels, cluster_counts, self.cluster, "cand_filter_cluster_a11y"),
                "query": {"label": T["cand_search_label"], "placeholder": T["cand_search_placeholder"], "value": self.query},
                "more": {"text": T["cand_filter_less" if more_open else "cand_filter_more"], "open": more_open, "available": bool(rows)},
                "result": T["cand_filter_result"].format(shown=shown, found=len(found), total=len(rows)), "active": self.filters_active(), "reset": T["cand_filter_reset"]}

    def _empty(self, data, found):
        """빈 화면 — 서로 다른 안내(보관함 없음·옛 구조·후보 없음·점수를 못 믿어 모두 뺌·거른 결과 없음). 쓰기 단추는 없다(만들기는 머리의 `후보 만들기` 하나)."""
        if data.store in ("missing", "empty"):
            return {"kind": "nostore", "title": T["cand_empty_nostore_title"], "desc": T["cand_empty_nostore_desc"], "reset": False}
        if data.store == "old_structure":
            return {"kind": "old", "title": T["cand_empty_old_title"], "desc": T["cand_empty_old_desc"], "reset": False}
        if not data.rows:
            if data.skipped:
                return {"kind": "skipped", "title": T["cand_empty_skipped_title"], "desc": T["cand_empty_skipped_desc"], "reset": False}
            return {"kind": "none", "title": T["cand_empty_none_title"], "desc": T["cand_empty_none_desc"], "reset": False}
        if not found:
            return {"kind": "filtered", "title": T["cand_none_found"], "desc": "", "reset": True}
        return None

    def _prep(self):
        """후보를 만들 수 없을 때의 안내 카드 — 무엇이 모자란지와 이미 있는 화면(Seed 관리·블로그 관리)으로 가는 단추. 쓰기 단추는 없다."""
        preview = self.preview
        if preview is None or preview.can_make:
            return None
        lines = [T[LACK_TEXT[key]] for key in preview.lacks if key in LACK_TEXT] or [T[LACK_TEXT["none"]]]
        if "no_seed" in preview.lacks and preview.seeds_proposed:
            lines.append(T["cand_prep_proposed"].format(n=preview.seeds_proposed))
        buttons = [{"key": "seed", "text": T["cand_prep_seed"]}, {"key": "blogs", "text": T["cand_prep_blogs"]}, {"key": "close", "text": T["cand_prep_close"]}]
        return {"title": T["cand_prep_title"], "lead": T["cand_prep_lead"], "lines": lines, "buttons": buttons, "a11y": T["cand_prep_a11y"], "sample": bool(preview.sample), "sample_tag": T["sample_tag"]}

    def view(self, diag_text=""):
        data, state = self.data, self.state
        normal = state == "normal" and data is not None
        found = self.found() if normal else []
        shown_rows = found[:self.limit]
        rest = len(found) - len(shown_rows)
        sample = bool(data and data.sample)
        banners = []
        if normal and data.store in ("missing", "empty") and not sample:
            banners.append(("info", T["cand_store_missing_note"]))
        if normal and data.skipped:
            banners.append(("warning", T["cand_skipped_note"].format(n=data.skipped)))
        ok, reason = self.make_info()
        return {
            "title": T["cand_title"], "sub": T["cand_sub"], "refresh": T["cand_refresh"], "make": {"text": T["cand_make"], "tip": T["cand_make_tip"], "enabled": ok, "reason": reason},
            "sample": sample, "sample_tag": T["sample_tag"], "sample_tip": T["cand_sample_tip"], "state": state, "busy": self.busy, "loading": {"text": T["cand_loading"], "a11y": T["cand_loading_a11y"]},
            "error": {"title": T["cand_error_title"], "desc": T["cand_error_desc"], "button": T["cand_error_btn"], "diag": diag_text, "user": getattr(self.failure, "user_message", "") if self.failure else ""},
            "banners": banners, "notice": {"level": self.notice[0], "text": self.notice[1]} if self.notice else None, "prep": self._prep() if normal else None,
            "filters": self._filters(data, found) if normal and data.rows else None,                       # 후보가 하나도 없으면 거를 것이 없다 — 거르기 카드 없이 빈 안내만
            "grid": {"a11y": T["cand_grid_a11y"], "cards": [self._card(row, sample) for row in shown_rows], "empty": self._empty(data, found) if normal else None, "found": len(found), "total": len(data.rows) if data is not None else 0,
                     "more": {"text": T["cand_more"].format(n=min(rest, rules.PAGE)), "a11y": T["cand_more_a11y"].format(n=min(rest, rules.PAGE))} if rest > 0 else None},
        }

    def detail_view(self):
        """고른 후보의 상세 — 고른 것이 없거나 읽은 내용이 없으면 None. 후보의 모든 값을 있는 그대로 보인다(새 점수를 만들지 않는다)."""
        row = self.selected_row()
        if row is None or self.data is None or self.state != "normal":
            return None
        item = row.candidate
        info = self._channel_vm(item.channel)
        channel = self.channel_info(item.channel)
        score = rules.score_of(item)
        band = G.score_band(score)
        notices = self.notices_of(row)
        sample = bool(self.data.sample)
        icon, tone = rules.topic_icon(item.topic_cluster)
        ref = short_number(item.candidate_id)
        title = rules.shown(item.topic, rules.TITLE_LIMIT)
        badges = [*rules.card_badges(item, row.stop, notices)]
        if rules.type_name(item):
            badges.append({"kind": "type", "tone": "muted", "text": rules.type_name(item)})                 # 상세에는 후보 종류 배지도 하나 더 보인다(카드의 배지 수 상한 둘은 카드 몫이다)
        trend_rows, trend_note = rules.trend_rows(item)
        seed = self.data.seed_map().get(item.seed_id) if item.seed_id else None
        cards, stop_text = rules.safety_cards(notices, row.stop)
        main, _safe = rules.reason_lines(item)
        reasons = [rules.shown(line, 300) for line in main]
        reasons = [line for line in reasons if line]
        factors = rules.factor_rows(item, channel["weights"])
        has_factors = any(not entry["missing"] for entry in factors)
        words = [rules.shown(word, 40) for word in (item.primary_keyword, *item.secondary_keywords)]
        tags = rules.tag_names(item)
        return {"id": item.candidate_id, "title": T["cand_detail_title"], "a11y": T["cand_detail_a11y"], "close": T["cand_detail_close"], "heading": title, "badges": badges, "channel": info, "image": {"icon": icon, "tone": tone, "state_text": T["cand_image_state"]},
                "score": score, "ring": score is not None, "band": band.key if band else None, "band_label": band.name if band else "", "missing_text": T["cand_score_none"],
                "score_a11y": G.score_spoken(score) if score is not None else T["cand_score_none"], "final_text": T["cand_score_final"].format(n=score) if score is not None else "",
                "number": {"ref": ref, "text": T["cand_number"].format(ref=ref), "copy": T["cand_copy"], "a11y": T["cand_copy_a11y"].format(ref=ref), "copied": T["cand_copied"], "failed": T["cand_copy_failed"]},
                "keywords": {"title": T["cand_sec_keywords"], "items": words}, "tags": {"title": T["cand_sec_tags"], "items": tags} if tags else None,
                "factors": {"title": T["cand_sec_score"], "rows": factors if has_factors else [], "note": T["cand_factor_note"] if has_factors and any(entry["missing"] for entry in factors) else "", "empty": "" if has_factors else T["cand_factor_none"]},
                "reason": {"title": T["cand_sec_reason"], "lines": reasons, "empty": "" if reasons else T["cand_reason_none"]},
                "trend": {"title": T["cand_sec_trend"], "rows": [{"label": label, "value": value, "missing": missing} for label, value, missing in trend_rows], "note": trend_note},
                "seed": {"title": T["cand_sec_seed"], "rows": [{"label": label, "value": value, "missing": missing} for label, value, missing in rules.seed_rows(item, seed)]},
                "safety": {"title": T["cand_sec_safety"], "cards": cards, "stop": stop_text, "none": "" if cards or stop_text else T["cand_safety_none"]},
                "hold": rules.hold_row(item), "info": {"title": T["cand_sec_info"], "rows": rules.info_rows(item, channel["name"])}, "sample": sample, "sample_tag": T["sample_tag"],
                "draft": self.draft_vm(row)}

    def draft_vm(self, row):
        """상세 아래 고정 행동 줄의 `이 주제로 만들기`(P4e) — 켤 수 있나와 못 켜는 까닭. **안전 판정이 '자동 초안 중지' 인 후보·네이버가 아닌 채널의 후보는 꺼 두고 까닭을 보인다**(동작하지 않는 단추는 만들지 않는다 — 보류·제외·Seed 등록은 없다)."""
        if self.busy:
            why = T["drf_make_why_wait"]
        elif row.stop:
            why = T["drf_make_why_stop"]
        elif row.candidate.channel not in BLOG_NAMES:
            why = T["drf_make_why_channel"]
        else:
            why = ""
        return {"text": T["drf_make"], "enabled": not why, "reason": why, "tip": why or T["drf_make_tip"], "a11y": T["drf_make_a11y"], "bar_a11y": T["drf_detail_actions_a11y"]}

    def draft_target(self):
        """고른 후보로 초안을 만들 때 넘길 값 — 후보 번호(엔진 번호 전체)와 보이는 값뿐이다(초안 내용은 서비스가 번호로 다시 읽어 만든다). 고른 후보가 없거나 읽은 내용이 없으면 None. 이 함수는 아무것도 바꾸지 않는다."""
        row = self.selected_row()
        if row is None or self.data is None or self.state != "normal":
            return None
        item = row.candidate
        return DraftTarget(item.candidate_id, rules.shown(item.topic, rules.TITLE_LIMIT), item.channel, self._channel_vm(item.channel)["name"], bool(row.stop), bool(self.data.sample))

    def pane_empty(self):
        """고정 상세 창에서 아무것도 안 골랐을 때의 안내."""
        return {"title": T["cand_detail_empty_title"], "desc": T["cand_detail_empty_desc"]}

    def pane_visible(self):
        """고정 상세 창을 보일까 — 후보를 읽었고 고를 후보가 하나라도 있을 때만(읽는 중·읽기 오류·후보가 하나도 없을 때는 창이 아니라 본문이 넓게 안내한다)."""
        return self.state == "normal" and self.data is not None and bool(self.data.rows)
