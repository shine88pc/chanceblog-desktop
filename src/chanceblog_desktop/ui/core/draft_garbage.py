"""'글 모양 점검' 카드의 화면 쪽 규칙(N-2) — 위치 문구·보이는 조각 가리기·무시 기억·세대 번호로 낡은 결과 가르기·카드 뷰모델. PySide6·파일·서비스를 모른다.

**경고만 한다.** 글을 고치거나 지우거나 바꿔 쓰지 않고, 복사를 막거나 확인창을 띄우지도 않는다 — 이 파일은 복사 관문(`draft_rules.py`)의 결과를 읽지도 쓰지도 않고(관문은 이 파일을 모른다) 건강·출처·안전 점검과 다른 결과 칸·다른 색(안내 파랑과 흐린 회색뿐)을 쓴다.
규칙 자체는 `check/garbage.py`(순수 규칙)이고 이 파일은 그 결과를 사람이 읽는 말로 바꾼다:
  · **언제 돌리나**: `검사하기` 를 눌렀을 때뿐이다. 글을 치는 동안·복사할 때는 부르지 않는다(운영자 2026-11-10). 길 하나 — 작업 스레드(`run`)에서 글의 **불변 복사본**(문자열)만 받아 규칙을 돌려 **값**(`GarbageResult`, 걸린 글 없음)을 돌려준다.
  · **세대 번호**(`GarbageTracker`): 검사를 시작할 때마다·새 초안이나 화면 떠남으로 초기화할 때마다 번호가 오른다. 도착한 결과의 번호가 지금 도는 검사의 번호와 같을 때만 받고 아니면 버린다(늦게 온 낡은 결과가 새 글의 결과인 척하지 않게, 한 번만 받는다).
  · **본문이 변경됨**: 결과는 지우지 않고 보여 주되, 검사한 글의 지문(해시)과 지금 글이 다르면 그 말을 덧붙인다(위치는 검사했을 때의 글 기준이다).
  · **무시**: 걸린 것의 지문(종류 + 걸린 글의 모양을 해시한 값)을 **이 화면의 메모리에만** 기억한다 — 위치로 기억하면 글을 고칠 때 밀린다. 새 초안·화면 떠남·앱 닫기에서 모두 지운다. 저장하는 곳은 없다.
  · **위치 문구**: `본문 3문단 2번째 줄 앞에서 12번째 글자` — 문단은 빈 줄로 가른 덩어리다. 앞 글은 8자, 걸린 글은 12자까지만 자르고 키 모양이 걸치면 그 자리를 가린다(키가 곁에 있어도 되풀이하지 않는다).
  · **한 종류의 상세는 최대 10건**(`DETAIL_MAX`)이고 나머지는 `외 N건` 으로 개수만 보인다. 같은 글자(보이지 않는 글자)·같은 표시(코드 블록 표시)는 한 건으로 묶인다.
무거운 모듈(`check/garbage`)은 쓰는 함수 안에서 늦게 가져온다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .draft_rules import secret_spots, shown
from .text import T

DETAIL_MAX = 10                                               # 한 종류의 상세(위치·이유)는 이만큼까지, 나머지는 개수만(운영자 2026-11-10)
BEFORE_CHARS = 8                                              # 위치에 붙이는 앞 글 글자 수
CAUGHT_CHARS = 12                                             # 걸린 글을 보일 때 자르는 글자 수
MASK_WINDOW = 64                                              # 보일 조각 곁의 이만큼 글자까지 보고 키 모양을 찾는다(조각이 키의 가운데를 자르지 않게)
SHOWN_LIMIT = 4 * (BEFORE_CHARS + CAUGHT_CHARS) + 40          # 가린 조각이 길어져도 다시 잘리지 않을 만큼의 한도
GARBAGE_KEY = "drafts-garbage"                                # 검사 작업의 이름
STALE_NONE, STALE_BODY, STALE_TITLE = "", "body", "title"
DOT = " · "                                              # 위치·조각·이유를 잇는 점
BOX = chr(0x25A1)                                             # 화면에 안 보이거나 깨져 보일 글자 대신 보이는 네모

# 보이지 않는 글자의 이름(글 열쇠) — (처음 코드, 끝 코드, 글 열쇠). 이 표에 없는 글자는 이름 없이 코드만 보인다.
INVISIBLE_NAMES = (
    (0x00AD, 0x00AD, "drf_g_n_00ad"), (0x034F, 0x034F, "drf_g_n_034f"), (0x061C, 0x061C, "drf_g_n_061c"), (0x115F, 0x115F, "drf_g_n_115f"), (0x1160, 0x1160, "drf_g_n_1160"), (0x180B, 0x180E, "drf_g_n_180b"),
    (0x200B, 0x200B, "drf_g_n_200b"), (0x200C, 0x200C, "drf_g_n_200c"), (0x200D, 0x200D, "drf_g_n_200d"), (0x200E, 0x200E, "drf_g_n_200e"), (0x200F, 0x200F, "drf_g_n_200f"), (0x2060, 0x2060, "drf_g_n_2060"),
    (0x2061, 0x2064, "drf_g_n_2061"), (0x206A, 0x206F, "drf_g_n_206a"), (0x3164, 0x3164, "drf_g_n_3164"), (0xFE00, 0xFE0F, "drf_g_n_fe00"), (0xFEFF, 0xFEFF, "drf_g_n_feff"), (0xFFA0, 0xFFA0, "drf_g_n_ffa0"),
    (0xE0001, 0xE0001, "drf_g_n_e0001"), (0xE0020, 0xE007F, "drf_g_n_e0020"),
)
CONTROL_NAMES = ((0x0000, "drf_g_c_0000"), (0x000C, "drf_g_c_000c"), (0x001B, "drf_g_c_001b"))        # 이름이 알려진 제어 문자 — 나머지는 코드만 보인다


# ---- 결과 값(작업 스레드가 돌려준다) -----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class GarbageResult:
    """한 번의 검사 결과 — 규칙의 `Report`(위치·종류·지문뿐, 걸린 글 없음)와 검사한 글의 지문. 세대 번호는 이 결과가 어느 검사의 것인지 알린다."""
    generation: int
    title_digest: str
    body_digest: str
    report: object


def digest_of(text):
    """글의 지문(SHA-256 앞 16자) — 검사한 뒤 글이 바뀌었는지 견주려는 값이다. 글 자체는 담지 않는다."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def run(generation, title, body):
    """작업 스레드에서 도는 검사 한 번 — 글(바뀌지 않는 문자열)을 받아 규칙을 돌리고 값을 돌려준다. 파일·시계·전역 상태를 쓰지 않아 스레드에 안전하다."""
    from ...check import garbage
    return GarbageResult(generation, digest_of(title), digest_of(body), garbage.scan(title, body))


# ---- 보이는 글 만들기 --------------------------------------------------------------------------------------------------------------------
def _plain(piece):
    """한 줄로 줄이고 눈에 안 보이는 글자·제어 문자는 네모로 바꾼다 — 보일 조각이 화면에서 사라지거나 깨져 보이지 않게."""
    from ...check import garbage
    return " ".join(garbage.HIDDEN.sub(BOX, piece).split())


def _safe(text, start, end):
    """`text[start:end]` 를 화면에 보일 조각으로 — 키 모양이 걸치면 그 자리를 가리고(곁 글자까지 보고 찾는다), 보이지 않는 글자는 네모로, 공백은 한 칸으로 바꾼 뒤 한 번 더 가린다."""
    low, high = max(0, start - MASK_WINDOW), min(len(text), end + MASK_WINDOW)
    window = text[low:high]
    first, last = start - low, end - low
    parts, cursor = [], first
    for spot_start, spot_end in secret_spots(window):
        spot_start, spot_end = max(spot_start, first), min(spot_end, last)
        if spot_end <= spot_start or spot_end <= cursor:
            continue
        parts += [window[cursor:spot_start], T["drf_spot_hidden"]]
        cursor = spot_end
    parts.append(window[cursor:last])
    return shown(_plain("".join(parts)), SHOWN_LIMIT)


def _caught(text, start, end):
    """걸린 글 — `CAUGHT_CHARS` 자까지만 자르고 더 있으면 …"""
    cut = min(end, start + CAUGHT_CHARS)
    return _safe(text, start, cut) + ("…" if end > cut else "")


class _Place:
    """칸(제목·본문) 하나의 글과 줄 구조 — 위치 문구와 앞 글을 만든다."""

    def __init__(self, field, text):
        from ...check import garbage
        self.field, self.text = field, text
        self.lines = garbage.LineIndex(text) if field == "body" else None

    def where(self, index):
        if self.field == "title":
            return T["drf_g_at_title"].format(c=index + 1)
        paragraph, number, column = self.lines.locate(index)
        if number == 0:
            return T["drf_g_at_blank"].format(p=paragraph, c=column) if paragraph else T["drf_g_at_blank_first"].format(c=column)
        return T["drf_g_at_body"].format(p=paragraph, l=number, c=column)

    def line_where(self, index, short=False):
        paragraph, number, _column = self.lines.locate(index)
        return T["drf_g_and_line" if short else "drf_g_at_line"].format(p=paragraph, l=max(number, 1))

    def after(self, index):
        """`‘앞 글’ 바로 뒤` — 줄 맨 앞이면 그 말."""
        floor = self.lines.line_start(index) if self.lines is not None else 0
        start = max(floor, index - BEFORE_CHARS)
        piece = _safe(self.text, start, index)
        if not piece:
            return T["drf_g_line_start" if self.field == "body" else "drf_g_title_start"]
        return T["drf_g_after"].format(text=("…" if start > floor else "") + piece)


def invisible_name(code):
    for low, high, key in INVISIBLE_NAMES:
        if low <= code <= high:
            return T[key]
    return T["drf_g_n_other"]


def _control_name(code):
    for number, key in CONTROL_NAMES:
        if number == code:
            return T["drf_g_ctrl_named"].format(name=T[key], code=f"U+{code:04X}")
    return T["drf_g_ctrl_plain"].format(code=f"U+{code:04X}")


def _broken_name(sub, code, size):
    if sub == "replacement":
        name = T["drf_g_b_replacement"]
    elif sub == "private_use":
        name = T["drf_g_b_private"].format(code=f"U+{code:04X}")
    elif sub == "noncharacter":
        name = T["drf_g_b_surrogate" if 0xD800 <= code <= 0xDFFF else "drf_g_b_nonchar"].format(code=f"U+{code:04X}")
    else:
        return T["drf_g_b_jamo"].format(n=size)
    return T["drf_g_times"].format(name=name, n=size) if size > 1 else name


def _describe(finding, places):
    """한 건의 보이는 줄 — `위치 · 보이는 조각 · 이유 이름`. 걸린 글은 앞 글 8자·걸린 글 12자까지만 자르고 가린다."""
    spans = finding.spans
    field, start, end = spans[0]
    place = places[field]
    size = len(spans)
    kind = finding.kind
    where = place.line_where(start) if kind == "dup_sentence" else place.where(start)
    if size > 1 and kind != "dup_sentence":
        where = T["drf_g_rest"].format(where=where, n=size - 1)
    if kind == "broken":
        if finding.sub == "mojibake":
            what = T["drf_g_b_mojibake"].format(text=_caught(place.text, start, end))
        else:
            what = place.after(start) + DOT + _broken_name(finding.sub, ord(place.text[start]), end - start)
    elif kind == "invisible":
        what = place.after(start) + DOT + T["drf_g_times"].format(name=f"{invisible_name(int(finding.sub[2:], 16))}({finding.sub})", n=size)
    elif kind == "control":
        name = _control_name(int(finding.sub[2:], 16))
        what = place.after(start) + DOT + (T["drf_g_times"].format(name=name, n=end - start) if end - start > 1 else name)
    elif kind == "fence":
        what = T["drf_g_f_backtick" if finding.sub == "backtick" else "drf_g_f_tilde"].format(n=size)
    elif kind == "dup_word":
        what = T["drf_g_dw"].format(text=_caught(place.text, start, end), n=finding.repeats)
    elif kind == "dup_sentence":
        second = places[spans[1][0]]
        paragraph, number, _column = second.lines.locate(spans[1][1])
        if place.lines.locate(start)[:2] == (paragraph, number):                        # 같은 줄에 두 번 — 글자 번호로 가른다(`1문단 1번째 줄과 1문단 1번째 줄` 은 어느 쪽이 어느 쪽인지 알 수 없다)
            where = T["drf_g_pair_col"].format(where=place.where(start), c=second.lines.locate(spans[1][1])[2])
        else:
            where = T["drf_g_pair"].format(a=where, b=second.line_where(spans[1][1], short=True))
        if size > 2:
            where = T["drf_g_rest"].format(where=where, n=size - 2)
        what = T["drf_g_ds"].format(text=_caught(place.text, start, end), n=size)
    else:                                                       # entity·placeholder — 걸린 글 자체가 이유다
        what = T["drf_g_quote"].format(text=_caught(place.text, start, end))
    return where + DOT + what


# ---- 세대 번호·무시 기억·카드 ------------------------------------------------------------------------------------------------------------
def _changed(current, snapshot, digest):
    """같은 문자열 객체거나 글자 수·지문이 같으면 안 바뀐 것이다(해시는 글자 수가 같을 때만 계산한다)."""
    if current is snapshot:
        return False
    return len(current) != len(snapshot) or digest_of(current) != digest


class GarbageTracker:
    """검사 한 줄기의 상태 — 지금 도는 검사·받아들인 결과·무시한 지문. Qt 를 모른다(그래서 CI 에서 시험한다). 새 초안·화면 떠남은 `reset()`, 검사 시작은 `begin()`, 도착은 `deliver()` 와 `fail()` 이다."""

    def __init__(self):
        self.generation = 0
        self.reset()

    def reset(self):
        """새 초안·화면 떠남·앱 닫기 — 도는 검사의 답은 앞으로 받지 않고(세대가 달라진다) 결과·무시 기억·검사한 글을 모두 지운다."""
        self.generation += 1
        self.pending = None                                     # 지금 도는 검사의 세대 번호(없으면 None)
        self.result = None
        self.failed = False
        self.ignored = set()
        self._asked = None
        self._snapshot = None
        self._stamp = None
        self._visible = ()
        self._ignored_count = 0
        self._groups_cache = None

    @property
    def running(self):
        return self.pending is not None

    def begin(self, title, body):
        """새 검사를 시작한다 → 세대 번호. 이미 도는 검사가 있으면 None(중복 실행 방지)."""
        if self.pending is not None:
            return None
        self.generation += 1
        self.pending = self.generation
        self._asked = (title, body)
        self.failed = False
        return self.generation

    def deliver(self, result):
        """도착한 결과를 받는다 → 받았으면 True. 세대 번호가 지금 도는 검사와 다르면(그 사이 새 초안·떠남) 버리고, 이미 받은 번호도 두 번 받지 않는다."""
        if self.pending is None or getattr(result, "generation", None) != self.pending:
            return False
        self.pending = None
        self.result, self._snapshot, self._asked = result, self._asked, None
        self.ignored &= {finding.fingerprint for finding in result.report.findings}          # 없어진 것의 무시는 조용히 지운다 — 새로 생긴 것은 새 항목으로 보인다
        self._stamp = None
        return True

    def fail(self, generation):
        """검사가 끝내 실패했다(규칙의 버그) → 받았으면 True. 다른 세대의 실패는 버린다."""
        if self.pending is None or generation != self.pending:
            return False
        self.pending, self._asked, self.failed = None, None, True
        return True

    def abandon(self):
        """결과를 화면에 그리다 예외가 났다 — 도는 검사도 받은 결과도 없는 것으로 하고 `점검을 끝내지 못했어요` 로 둔다(무시 기억은 그대로).
        `fail()` 은 '도는 검사가 있을 때 그 실패' 만 받는데 이 길은 결과를 받은 **뒤**(`deliver()` 가 이미 `pending` 을 지운 뒤)라 따로 둔다 — 그렇지 않으면 그리기가 계속 실패할 때 카드가 `검사 중…` 으로 남는다."""
        self.pending, self._asked = None, None
        self.result, self._snapshot = None, None                     # 글 복사본도 놓는다(다음 `deliver()` 가 `_stamp` 를 새로 잡으므로 가림 캐시는 따로 지울 필요가 없다)
        self.failed = True

    # ---- 낡았는가 ----
    def stale(self, title, body):
        """검사한 뒤 글이 바뀌었나 → `''`·`'body'`(본문이 변경됨)·`'title'`. 지문(해시)을 견준다 — 글자 수가 다르면 해시를 계산하지 않고 바뀐 것이다."""
        result = self.result
        if result is None:
            return STALE_NONE
        if _changed(body, self._snapshot[1], result.body_digest):
            return STALE_BODY
        return STALE_TITLE if _changed(title, self._snapshot[0], result.title_digest) else STALE_NONE

    # ---- 보이는 항목 ----
    def _refresh(self):
        """무시하지 않은 항목들과 무시한 건수 — 결과나 무시 기억이 바뀔 때만 다시 센다."""
        stamp = (self.result.generation, frozenset(self.ignored))
        if self._stamp != stamp:
            findings = self.result.report.findings
            self._visible = tuple(finding for finding in findings if finding.fingerprint not in self.ignored)
            self._ignored_count = len(findings) - len(self._visible)
            self._stamp, self._groups_cache = stamp, None

    def visible(self):
        """무시하지 않은 것들(보이는 순서 그대로, 종류마다 앞 10건만이 아니라 전부)."""
        if self.result is None:
            return ()
        self._refresh()
        return self._visible

    def ignored_count(self):
        if self.result is None:
            return 0
        self._refresh()
        return self._ignored_count

    def _fingerprint_of(self, key):
        if self.result is None or not isinstance(key, str):
            return None
        head, _dot, tail = key.partition(".")
        visible = self.visible()
        if head != str(self.result.generation) or not tail.isdigit() or int(tail) >= len(visible):
            return None
        return visible[int(tail)].fingerprint

    def ignore(self, key):
        """항목 하나를 무시한다(같은 지문은 모두) → 바뀌었으면 True."""
        fingerprint = self._fingerprint_of(key)
        if fingerprint is None:
            return False
        self.ignored.add(fingerprint)
        return True

    def ignore_all(self):
        """지금 보이는 것을 모두 무시한다(10건을 넘어 개수로만 보이던 것도) → 바뀌었으면 True."""
        fingerprints = {finding.fingerprint for finding in self.visible()}
        if not fingerprints:
            return False
        self.ignored |= fingerprints
        return True

    def restore(self):
        """무시한 것을 모두 되살린다 → 바뀌었으면 True."""
        if not self.ignored:
            return False
        self.ignored = set()
        return True

    # ---- 카드 뷰모델 ----
    def _groups(self):
        """종류별 묶음 — 만드는 데 드는 글 가공(위치·가림)은 결과·무시 기억이 바뀔 때만 한다(글을 칠 때마다 다시 하지 않는다)."""
        self._refresh()
        if self._groups_cache is not None:
            return self._groups_cache
        from ...check import garbage
        title, body = self._snapshot
        places = {"title": _Place("title", title), "body": _Place("body", body)}
        numbered = list(enumerate(self._visible))
        groups = []
        for kind in garbage.KINDS:
            items = [(number, finding) for number, finding in numbered if finding.kind == kind]
            if not items:
                continue
            name = T["drf_g_kind_" + kind]
            rows = [{"key": f"{self.result.generation}.{number}", "text": _describe(finding, places), "button": T["drf_g_ignore"], "a11y": T["drf_g_ignore_a11y"].format(kind=name, n=rank + 1)}
                    for rank, (number, finding) in enumerate(items[:DETAIL_MAX])]
            reason = T["drf_g_why_" + kind] + (T["drf_g_why_jamo"] if any(finding.sub == "jamo_run" for _number, finding in items) else "")
            groups.append({"kind": kind, "title": name, "chip": T["drf_g_chip"].format(n=len(items)), "reason": reason, "rows": rows, "more": T["drf_g_more"].format(n=len(items) - DETAIL_MAX) if len(items) > DETAIL_MAX else ""})
        self._groups_cache = groups
        return groups

    def card(self, title, body):
        """카드의 글 — 상태(`before`·`running`·`failed`·`skipped`·`clean`·`found`)·톤(안내 `info` 와 흐림 `muted` 뿐)·상태 줄·종류별 묶음과 항목·`본문이 변경됨`·무시 단추들. 글을 칠 때마다 불러도 가볍다."""
        busy = self.running
        card = {"title": T["drf_g_title"], "note": T["drf_g_note"], "hint": T["drf_g_hint"], "busy": busy, "stale": STALE_NONE, "stale_text": "", "groups": [],
                "button": {"text": T["drf_g_busy" if busy else "drf_inspect_btn"], "a11y": T["drf_g_busy_a11y" if busy else "drf_inspect_btn_a11y"], "enabled": not busy},
                "ignore_all": {"text": "", "a11y": "", "visible": False}, "restore": {"text": "", "a11y": "", "visible": False}}
        if busy:
            return {**card, "state": "running", "tone": "muted", "status": T["drf_g_running"]}
        if self.failed:
            return {**card, "state": "failed", "tone": "muted", "status": T["drf_g_failed"]}
        if self.result is None:
            return {**card, "state": "before", "tone": "muted", "status": T["drf_g_before"]}
        stale = self.stale(title, body)
        card["stale"] = stale
        card["stale_text"] = {STALE_BODY: T["drf_g_stale_body"], STALE_TITLE: T["drf_g_stale_title"]}.get(stale, "")
        if self.result.report.skipped:
            return {**card, "state": "skipped", "tone": "muted", "status": T["drf_g_skipped"]}
        visible, ignored = self.visible(), self.ignored_count()
        if ignored:
            card["restore"] = {"text": T["drf_g_restore"].format(n=ignored), "a11y": T["drf_g_restore_a11y"].format(n=ignored), "visible": True}
        if not visible:
            return {**card, "state": "clean", "tone": "muted", "status": T["drf_g_clean_ignored"].format(n=ignored) if ignored else T["drf_g_clean"]}
        if len(visible) >= 2:                                                                                              # 숨은 건(10건을 넘어 개수로만 보이던 것)까지 무시되므로 단추에 건수를 적는다 — 보이는 줄만 무시하는 것이 아니다
            card["ignore_all"] = {"text": T["drf_g_ignore_all"].format(n=len(visible)), "a11y": T["drf_g_ignore_all_a11y"].format(n=len(visible)), "visible": True}
        return {**card, "state": "found", "tone": "info", "status": T["drf_g_found"].format(n=len(visible)), "groups": self._groups()}
