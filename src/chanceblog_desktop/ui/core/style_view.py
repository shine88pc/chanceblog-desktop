"""'내 글 문체 참고값 보기' 대화상자의 화면 쪽 규칙(N-3a, 결정 D-330–D-339) — 고른 글·세대 번호·낡은 결과 버리기·결과 표(뷰모델)·숫자 서식. PySide6·파일·서비스를 모른다(그래서 CI 에서 시험한다).

**저장도 AI 도 네트워크도 없고 프로필·설정·보관함을 읽지도 쓰지도 않는다.** 이 파일이 쥐는 것은 고른 파일의 **위치**(화면·로그·오류에 되풀이하지 않는다)와 계산 결과(**숫자만**)뿐이다. 붙여 넣은 글은 대화상자의 입력 칸에 있다가
`계산하기` 를 누를 때 값으로 작업 스레드에 넘어가고 이 파일이 따로 쥐지 않는다. 글(문장)은 어떤 뷰모델·상태·오류에도 담기지 않고, 결과는 창(대화상자)을 닫으면 모두 버려진다.
  · **언제 도나**: `계산하기` 를 눌렀을 때뿐이다. 길 하나 — 작업 스레드(`StyleStudy._work`)에서 공급자(`StyleProvider.compute`)가 파일을 읽고 `content/style_stats` 로 세어 숫자 값(`StyleOutcome`)을 돌려준다.
  · **세대 번호**: 대화상자를 열 때·계산을 시작할 때·다시 할 때·닫을 때마다 번호가 오른다. 도착한 결과의 번호가 지금 도는 계산의 번호와 같을 때만 한 번 받고 아니면 버린다(닫은 뒤·다시 한 뒤에 늦게 온 결과가 보이지 않게).
    번호는 이 객체(앱이 사는 동안 하나)가 이어 오르므로 대화상자를 닫았다 다시 열어도 옛 계산의 결과가 새 창에 섞이지 않는다.
  · **고르기**: 파일은 한 번에 하나씩 고르고(파일 선택 창은 위치만 준다) 붙여 넣은 글과 합쳐 최대 2개다. 고를 때마다 공급자가 읽을 수 있는지만 확인하고(읽은 글은 바로 버린다) 거절 문장은 공급자가 준 고정 문장이다.
    선택 창에서 취소하면(빈 위치) 공급자를 부르지 않는다.
  · **표**: 글 하나면 값 한 칸, 둘이면 글별 값 + 범위(최소–최대) + 합산(문장·문단을 모아 센 값). 글 사이 차이가 크면(`style_stats` 의 네 기준) 합산을 보이지 않고 범위만 보인다. 숫자는 분수로 계산해 반올림이 어긋나지 않는다.
    판정 라벨은 없다 — 항목 이름은 겉모양 그대로(`‘…니다·…니까·…십시오’ 로 끝나는 문장`)이고 알 수 없는 값은 0 이 아니라 `알 수 없음` 이다.
무거운 모듈(`content/style_stats`)은 쓰는 함수 안에서 늦게 가져온다.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .jobs import Job
from .text import T

STYLE_KEY = "style-stats"                          # 계산 작업의 이름
MAX_ITEMS = 2                                      # 파일과 붙여 넣은 글을 합쳐 한 번에 세는 글의 수(운영자 확정 — 읽기 기반 `own_posts.MAX_FILES` 와 같은 값, 시험이 견준다)
RANGE_DASH = "–"
FILE_SUFFIXES = (".txt", ".md")                    # 파일 선택 창이 보이는 형식(읽기 기반이 받는 것과 같다)
PHASES = ("select", "running", "result")           # 대화상자의 세 모습 — 고르기·세는 중·결과

# 화면에 보이는 숫자 항목 — (열쇠, 문구 열쇠, 서식 종류) 순서가 표의 순서다
ROWS = (
    ("sentence_length", "style_row_sentence_length", "tenth_chars"), ("per_paragraph", "style_row_per_paragraph", "tenth_sentences"), ("headings", "style_row_headings", "count"),
    ("end_formal", "style_row_end_formal", "percent"), ("end_polite", "style_row_end_polite", "percent"), ("end_plain", "style_row_end_plain", "percent"), ("end_other", "style_row_end_other", "percent"),
    ("question", "style_row_question", "percent"), ("list", "style_row_list", "percent"),
)


class StyleRefusal(Exception):
    """고른 글을 읽지 않고 돌려보낼 때 — `message` 는 공급자가 준 고정 문장이다(경로·파일 이름·글은 없다). 이 예외에는 앞 오류가 따라붙지 않는다."""

    def __init__(self, message):
        super().__init__("")
        self.message = str(message)


@dataclass(frozen=True)
class StyleOutcome:
    """작업 스레드가 돌려주는 결과 — 어느 계산의 것인지(세대 번호)·숫자 값(`StyleSummary`)·글마다 CP949 로 읽었는지·붙여 넣은 글인지. 글은 없다."""
    generation: int
    summary: object
    cp949: tuple
    pasted: tuple


class StyleProvider:
    """공급자 틀 — 실제는 `ui/style_adapter.py`(읽기 기반 `service/own_posts` + `content/style_stats`), 시험·사진은 가짜."""
    sample = False

    def check_files(self, paths):
        """파일들(위치 목록)을 읽을 수 있는지만 본다 — 읽은 글은 곧바로 버린다. 안 되면 `StyleRefusal`."""
        raise NotImplementedError

    def check_pasted(self, text):
        """붙여 넣은 글을 같은 한도로 검사한다 — 안 되면 `StyleRefusal`."""
        raise NotImplementedError

    def compute(self, paths, pasted_text):
        """파일들을 읽고(없으면 건너뜀) 붙여 넣은 글(빈 글이면 건너뜀)과 함께 세어 `(StyleSummary, cp949 튜플, 붙여넣음 튜플)` 을 돌려준다. 작업 스레드에서 불린다. 거절은 `JobFailure`."""
        raise NotImplementedError


class FakeStyleProvider(StyleProvider):
    """시험·사진용 — 파일 위치마다 정해 둔 글(`files`: {위치: (글, 형식)})을 읽고 위치가 `refuse` 안에 들어 있으면 거절한다. 세는 것은 진짜 규칙(`content/style_stats`)이다."""
    sample = True

    def __init__(self, files=None, refuse=(), pasted_form="pasted"):
        self.files, self.refuse, self.pasted_form = dict(files or {}), tuple(refuse), pasted_form
        self.calls = []

    def check_files(self, paths):
        self.calls.append(("check_files", len(paths)))
        for path in paths:
            if any(word in str(path) for word in self.refuse) or str(path) not in self.files:
                raise StyleRefusal("가짜 공급자의 고정 거절 문장이에요")

    def check_pasted(self, text):
        self.calls.append(("check_pasted", len(text)))
        if not text.strip() or len(text) > 100_000:
            raise StyleRefusal("가짜 공급자의 고정 거절 문장이에요")

    def compute(self, paths, pasted_text):
        from ...content import style_stats
        self.calls.append(("compute", len(paths), bool(pasted_text)))
        items = [self.files[str(path)] for path in paths]
        if pasted_text.strip():
            items.append((pasted_text, self.pasted_form))
        stats = [style_stats.analyze(text, form) for text, form in items]
        return style_stats.summarize(stats), tuple(False for _ in stats), tuple(index >= len(paths) for index in range(len(stats)))


# ---- 숫자 서식(분수 → 글) -----------------------------------------------------------------------------------------------------------
def _rounded(value, scale):
    """분수 → `scale` 배 한 값을 반올림(0.5 는 올림)한 정수."""
    return int((Fraction(value) * scale + Fraction(1, 2)) // 1)


def fmt_tenth(value):
    """분수 → 소수 첫째 자리까지('38.2')."""
    scaled = _rounded(value, 10)
    return f"{scaled // 10}.{scaled % 10}"


def fmt_percent_number(value):
    return str(_rounded(value, 100))


def number_and_unit(kind, value):
    """`(숫자 글, 단위 글)` — 값이 None 이면 `('알 수 없음', '')`."""
    if value is None:
        return T["style_unknown"], ""
    if kind == "tenth_chars":
        return fmt_tenth(value), T["style_unit_chars"]
    if kind == "tenth_sentences":
        return fmt_tenth(value), T["style_unit_sentences"]
    if kind == "count":
        if isinstance(value, Fraction) and value.denominator == 1:
            value = int(value)
        return (str(value) if isinstance(value, int) else fmt_tenth(value)), T["style_unit_count"]
    return fmt_percent_number(value), "%"


def cell_text(kind, value):
    number, unit = number_and_unit(kind, value)
    return number + unit


def range_text(kind, low, high):
    """`38.2–41.0자` — 같은 값이면 한 값만."""
    if low == high:
        return cell_text(kind, low)
    low_number, _unit = number_and_unit(kind, low)
    high_number, unit = number_and_unit(kind, high)
    return f"{low_number}{RANGE_DASH}{high_number}{unit}"


class StyleStudy:
    """대화상자 하나의 상태 — 고른 파일 위치·도는 계산의 세대 번호·결과·마지막 안내 문장. Qt 도 작업 스레드도 모르는 순수 논리다. 앱이 사는 동안 객체 하나가 이어지고 대화상자를 열 때 `open()`, 닫을 때 `close()` 로 모두 비운다."""

    def __init__(self, provider):
        self.provider = provider
        self.generation = 0
        self._job = None
        self.is_open = False
        self._clear()

    def _clear(self):
        self.paths = []                             # 고른 파일의 위치 — 화면·로그·오류에 되풀이하지 않는다
        self.pending = None                         # 지금 도는 계산의 세대 번호(없으면 None)
        self.outcome = None
        self.message = ""                           # 마지막 안내(거절·실패)의 고정 문장

    # ---- 열고 닫기 ----
    def open(self):
        """대화상자를 연다 — 이전 것은 모두 버리고 새 세대로 시작한다."""
        self._drop_job()
        self.generation += 1
        self._clear()
        self.is_open = True

    def close(self):
        """대화상자를 닫는다(어느 길로든 — 단추·Esc·앱 닫기·다른 대화상자로 바뀜) — 도는 계산의 답은 앞으로 받지 않고(세대가 달라진다) 고른 위치·결과를 모두 지운다. 작업자 종료를 기다리지 않는다."""
        self._drop_job()
        self.generation += 1
        self._clear()
        self.is_open = False

    def reset(self):
        """`다른 글로 다시 하기` — 결과와 고른 글을 모두 버리고 고르기 모습으로 돌아간다."""
        self._drop_job()
        self.generation += 1
        self._clear()

    def shutdown(self):
        self.close()

    def _drop_job(self):
        job, self._job = self._job, None
        if job is not None:
            job.cancel()                            # 기다리지 않는다 — 끝난 스레드의 답은 세대가 달라 어디에도 보이지 않는다

    # ---- 상태 ----
    @property
    def running(self):
        return self.pending is not None

    @property
    def phase(self):
        return "running" if self.running else "result" if self.outcome is not None else "select"

    def slots_used(self, pasted_chars=0):
        return len(self.paths) + (1 if pasted_chars > 0 else 0)

    # ---- 고르기 ----
    def add_file(self, path, pasted_chars=0):
        """파일 선택 창이 준 위치 하나를 더한다 → 상태: `closed`·`busy`(세는 중)·`cancelled`(빈 위치 — 공급자를 부르지 않는다)·`full`(이미 2개)·`refused`(공급자가 거절 — `message`)·`added`."""
        if not self.is_open:
            return "closed"
        if self.running or self.outcome is not None:
            return "busy"
        if not path:
            return "cancelled"
        if self.slots_used(pasted_chars) >= MAX_ITEMS:
            self.message = T["style_pick_full"]
            return "full"
        candidate = [*self.paths, str(path)]
        message = None
        try:
            self.provider.check_files(candidate)
        except StyleRefusal as refusal:
            message = refusal.message
        if message is not None:                         # `except` 밖에서 처리 — 거절 예외를 붙들지 않는다
            self.message = message
            return "refused"
        self.paths = candidate
        self.message = ""
        return "added"

    def remove_file(self, index):
        """고른 파일 하나를 뺀다 → 뺐으면 True."""
        if not self.is_open or self.running or self.outcome is not None or not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(self.paths):
            return False
        del self.paths[index]
        self.message = ""
        return True

    # ---- 계산 ----
    def start(self, pasted_text="", on_progress=None, on_done=None, on_error=None, on_cancel=None):
        """`계산하기` — 고른 파일과 붙여 넣은 글을 **작업 스레드**에서 센다(읽기뿐). `(상태, 작업)`: `closed`·`busy`(이미 세는 중이거나 결과가 있다)·`nothing`(고른 글이 없다)·`toomany`(합쳐 3개 이상)·
        `refused`(붙여 넣은 글이 거절됨 — `message`, 입력 칸은 그대로 둔다)·`started`. 붙여 넣은 글은 값으로만 넘어가고 이 객체가 쥐지 않는다."""
        if not self.is_open:
            return "closed", None
        if self.running or self.outcome is not None:
            return "busy", None
        text = pasted_text if isinstance(pasted_text, str) else ""
        has_pasted = bool(text.strip())
        if not self.paths and not has_pasted:
            self.message = T["style_none_yet"]
            return "nothing", None
        if len(self.paths) + int(has_pasted) > MAX_ITEMS:
            self.message = T["style_fail_toomany"]
            return "toomany", None
        message = None
        if has_pasted:
            try:
                self.provider.check_pasted(text)
            except StyleRefusal as refusal:
                message = refusal.message
        if message is not None:
            self.message = message
            return "refused", None
        self.generation += 1
        generation = self.generation
        self.pending, self.outcome, self.message = generation, None, ""
        holder = [tuple(self.paths), text if has_pasted else ""]            # 작업이 읽으면서 비우는 칸 — 닫힘(클로저)이나 호출 흔적이 위치·글을 붙들지 않게 값은 이 칸에만 둔다
        text = None

        def failed(failure, payload):
            failure.generation = payload                # 어느 계산의 실패인지(낡은 계산의 실패가 지금 계산을 실패로 만들지 않게)
            if on_error is not None:
                on_error(failure, payload)

        job = Job(STYLE_KEY, lambda progress, cancelled: self._work(generation, holder), payload=generation, on_done=on_done, on_error=failed, on_cancel=on_cancel)
        self._job = job
        job.start()
        return "started", job

    def _work(self, generation, holder):
        """작업 스레드에서 도는 한 번 — 공급자가 읽고 세어 숫자 값을 돌려준다(파일·시계·전역 상태를 이 파일은 쓰지 않는다). 위치와 붙여 넣은 글은 `holder` 칸에서 꺼내(칸은 비워진다) 부르고, 어느 길로 끝나든(오류 포함)
        이 틀의 지역 변수를 비운다 — 오류의 호출 흔적이 위치·글을 붙들지 않는다."""
        paths, pasted_text = holder.pop(0), holder.pop(0)
        try:
            summary, cp949, pasted = self.provider.compute(paths, pasted_text)
        finally:
            paths = pasted_text = None
        return StyleOutcome(generation, summary, tuple(bool(flag) for flag in cp949), tuple(bool(flag) for flag in pasted))

    def apply(self, outcome):
        """결과가 왔다 → 받았으면 True. 세대 번호가 지금 도는 계산과 다르면(그 사이 닫음·다시 함) 버리고, 이미 받은 번호도 두 번 받지 않는다."""
        if not self.is_open or self.pending is None or getattr(outcome, "generation", None) != self.pending:
            return False
        self.pending, self._job = None, None
        self.outcome, self.message = outcome, ""
        return True

    def apply_failed(self, failure):
        """계산이 실패했다 → 지금 계산의 실패였으면 True(고르기 모습으로 돌아가 `message` 가 이유를 말한다 — 고른 파일은 그대로다). 고정 문장만 화면에 나간다."""
        if not self.is_open or self.pending is None or getattr(failure, "generation", None) != self.pending:
            return False
        self.pending, self._job = None, None
        code = str(getattr(failure, "code", "") or "")
        shown = str(getattr(failure, "user_message", "") or "")
        self.message = shown if code == "CONTENT_INVALID" and shown else T["style_fail_other"]
        return True

    def apply_cancelled(self):
        """취소된 계산의 알림 — 취소는 닫기·다시 하기에서만 일어나고 그때 이미 모두 지웠으므로 할 일이 없다."""
        return False

    def apply_unexpected(self):
        """결과를 그리다 화면 쪽에서 예외가 났다 — 도는 계산도 받은 결과도 없는 것으로 하고 고르기 모습으로 돌아가 쉬운 고정 문장만 보인다(고른 파일은 그대로)."""
        if not self.is_open:
            return False
        self._drop_job()
        self.pending, self.outcome, self.message = None, None, T["style_fail_other"]
        return True

    # ---- 뷰모델 ----
    def view(self, pasted_chars=0):
        """대화상자를 그리는 데 필요한 모든 글·숫자·단추 상태. `pasted_chars` 는 입력 칸에 든 글자 수(글 자체는 받지 않는다)."""
        phase = self.phase
        used = self.slots_used(pasted_chars)
        selecting = phase == "select"
        slots = [{"index": index, "label": T["style_slot"].format(n=index + 1, kind=T["style_kind_file"]), "remove": T["style_remove"], "a11y": T["style_remove_a11y"].format(n=index + 1)} for index in range(len(self.paths))]
        status = T["style_running"] if phase == "running" else ""
        if selecting and not self.message and not slots and pasted_chars == 0:
            status = T["style_none_yet"]
        return {
            "phase": phase, "title": T["style_title"], "intro": T["style_intro"], "only_yours": T["style_only_yours"],
            "slots": slots, "slots_title": T["style_slots_title"], "slots_a11y": T["style_slots_a11y"],
            "pick": {"text": T["style_pick"], "a11y": T["style_pick_a11y"], "enabled": selecting and used < MAX_ITEMS, "hint": T["style_pick_hint"]},
            "paste": {"label": T["style_paste_label"], "a11y": T["style_paste_a11y"], "hint": T["style_paste_hint"], "enabled": selecting and len(self.paths) < MAX_ITEMS,
                      "count": T["style_paste_count"].format(n=pasted_chars), "count_a11y": T["style_paste_count_a11y"].format(n=pasted_chars)},
            "message": self.message, "status": status, "status_a11y": T["style_running_a11y"] if phase == "running" else "",
            "compute": {"text": T["style_compute"], "a11y": T["style_compute_a11y"], "enabled": selecting and used > 0},
            "again": {"text": T["style_again"], "a11y": T["style_again_a11y"]}, "close": {"text": T["style_close"], "a11y": T["style_close_a11y"]},
            "scroll_a11y": T["style_scroll_a11y"],
            "result": self.result_view() if phase == "result" else None,
        }

    def result_view(self):
        """결과 표 — 열(글별·범위·합산), 항목 줄들, 센 개수, 안내. 숫자와 고정 문장뿐이다."""
        from ...content import style_stats
        outcome = self.outcome
        summary = outcome.summary
        items = summary.items
        many = len(items) > 1
        pasted = tuple(outcome.pasted)

        def heading(index):
            """결과 열 머리 — 글이 둘일 때 붙여 넣은 글인 열에 `(붙여 넣음)` 이 붙는다(고르기 모습의 순서와 같다: 파일이 먼저, 붙여 넣은 글이 맨 뒤). 열이 하나뿐이면 구별할 열이 없어 `글 1` 그대로다."""
            marked = many and index < len(pasted) and pasted[index]
            return T["style_col_one_pasted" if marked else "style_col_one"].format(n=index + 1)

        columns = [{"key": f"item{index}", "text": heading(index)} for index in range(len(items))]
        if many:
            columns.append({"key": "range", "text": T["style_col_range"]})
            if not summary.range_only:
                columns.append({"key": "total", "text": T["style_col_total"]})
        rows = []
        for metric, label_key, kind in ROWS:
            label = T[label_key]
            values = [style_stats.value(stats, metric) for stats in items]
            cells = [cell_text(kind, found) for found in values]
            row = {"key": metric, "label": label, "cells": cells, "range": "", "total": ""}
            parts = [T["style_cell_a11y"].format(column=heading(index), value=cells[index]) for index in range(len(cells))] if many else [cells[0]]
            if many:
                found = style_stats.span(items, metric)
                row["range"] = range_text(kind, *found) if found is not None else T["style_unknown"]
                parts.append(T["style_range_a11y"].format(value=row["range"]))
                if not summary.range_only:
                    pooled = summary.pooled.headings
                    if metric == "headings":
                        row["total"] = cell_text(kind, Fraction(pooled, len(items)) if pooled is not None else None)
                    else:
                        row["total"] = cell_text(kind, style_stats.value(summary.pooled, metric))
                    parts.append(T["style_total_a11y"].format(value=row["total"]))
            row["a11y"] = T["style_row_a11y"].format(label=label, cells=", ".join(parts))
            rows.append(row)
        counts = []
        for index, stats in enumerate(items):
            fields = dict(sentences=f"{stats.sentences:,}", paragraphs=f"{stats.paragraphs:,}", lists=f"{stats.list_blocks:,}", chars=f"{stats.chars:,}")
            counts.append(T["style_counts"].format(n=index + 1, **fields) if many else T["style_counts_one"].format(**fields))
        notes = []
        for index, stats in enumerate(items):
            scope = T["style_scope"].format(n=index + 1) if many else ""
            for key in stats.notices():
                notes.append(scope + T["style_notice_" + key])
            if outcome.cp949[index]:
                notes.append(scope + T["style_notice_cp949"])
        return {"title": T["style_result_title"], "a11y": T["style_result_a11y"], "columns": columns, "item_header": T["style_col_item"], "rows": rows, "counts_title": T["style_counts_title"], "counts": counts,
                "range_only": many and summary.range_only, "range_only_note": T["style_range_only"] if many and summary.range_only else "", "total_note": T["style_total_note"] if many and not summary.range_only else "",
                "notes_title": T["style_notes_title"], "notes": notes, "trust": T["style_trust"], "yours": T["style_yours_result"], "rough": T["style_rough"]}


__all__ = ["FILE_SUFFIXES", "FakeStyleProvider", "MAX_ITEMS", "PHASES", "ROWS", "STYLE_KEY", "StyleOutcome", "StyleProvider", "StyleRefusal", "StyleStudy", "cell_text", "fmt_tenth", "range_text"]
