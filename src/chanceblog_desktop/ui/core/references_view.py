"""'참고 글 보관함' 대화상자의 화면 쪽 규칙(결정 D-490) — 목록·선택·편집 중(저장 안 한 변경 표시)·지우기 확인(두 단계)·낡은 결과 버리기(세대 번호)·뷰모델. PySide6·파일·서비스를 모른다(그래서 CI 에서 시험한다).

**글(제목·본문)은 이 파일의 어떤 상태·오류·뷰모델에도 담기지 않는다.** 글은 보관함 파일과 대화상자의 편집 칸에만 있고, 이 파일이 쥐는 것은 글 번호·목록 줄(제목·글자 수·고친 때)·열린 글의 **지문**(저장 안 한 변경이 있는지 견주는 해시)뿐이다.
편집 칸의 글은 `edited`·`save` 를 부를 때 값으로만 넘어오고 이 객체가 따로 쥐지 않는다. 목록 줄의 제목은 화면에 나가기 전에 가려진다(`display_text` — 키 모양 가리기가 먼저, 줄이기가 나중).
  · **세대 번호**: 대화상자를 열 때·닫을 때·일을 시작할 때마다 번호가 오른다(`begin`). 도착한 결과의 번호가 지금 번호와 같을 때만 한 번 받고 아니면 버린다(닫은 뒤·다른 글을 연 뒤에 늦게 온 결과가 보이지 않게).
    번호는 이 객체(앱이 사는 동안 하나)가 이어 오르므로 닫았다 다시 열어도 옛 결과가 새 창에 섞이지 않는다. 서비스 호출은 빠른 파일 읽기·쓰기라 화면은 곧바로 부르고 곧바로 받지만, 규칙은 늦게 온 결과를 버릴 수 있게 되어 있다.
  · **저장 안 한 변경**: 열린 글의 지문과 지금 편집 칸의 지문이 다르면 `dirty`. 다른 글을 열거나 새 글로 바꿀 때 `dirty` 면 버리겠다는 확인(`discard=True`)이 있어야 한다 — 없으면 `dirty` 를 돌려주고 아무것도 바꾸지 않는다.
  · **지우기 확인은 두 단계**: `ask_delete`(1단계 — 이 글을 지울까요?) → `advance_delete`(2단계 — 정말 지울까요? 되돌릴 수 없어요) → 한 번 더 `advance_delete` 가 지운다. `cancel_delete` 는 언제든 그만둔다.
  · 이 파일은 파일·네트워크·로그·시계를 쓰지 않는다. 오류 문장은 공급자가 준 고정 문장이고, 경로·번호·글은 어디에도 되풀이하지 않는다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .text import T, display_text

MAX_REFERENCES = 50                                # 보관 개수 상한 — 서비스 `references.MAX_REFERENCES` 와 같은 값(시험이 견준다)
TITLE_MAX, BODY_MAX = 80, 100_000                  # 제목·본문 글자 수 상한 — 서비스와 같은 값(시험이 견준다)
FILE_SUFFIXES = (".txt", ".md")                    # 파일 선택 창이 보이는 형식(읽기 기반이 받는 것과 같다)
KST = timedelta(hours=9)                           # 한국 시각 = UTC + 9


class ReferencesRefusal(Exception):
    """공급자가 일을 거절·실패로 돌려보낼 때 — `message` 는 고정 문장이다(경로·번호·글은 없다). 이 예외에는 앞 오류가 따라붙지 않는다."""

    def __init__(self, message):
        super().__init__("")
        self.message = str(message)


@dataclass(frozen=True)
class RefRow:
    """목록 한 줄 — 번호·제목·글자 수·고친 때(UTC 글). 제목은 `repr` 에 나오지 않는다."""
    ref_id: str
    title: str = field(repr=False)
    chars: int
    updated_at: str


@dataclass(frozen=True)
class RefListing:
    """목록 읽기의 결과 — 줄들(고친 때가 늦은 것부터)과 읽을 수 없어 건너뛴 파일의 개수."""
    rows: tuple
    skipped: int = 0


@dataclass(frozen=True)
class OpenedRef:
    """열린 글 — 번호·제목·본문(화면의 편집 칸에 채워 넣고 버린다). 제목·본문은 `repr` 에 나오지 않는다."""
    ref_id: str
    title: str = field(repr=False)
    body: str = field(repr=False)


class ReferencesProvider:
    """공급자 틀 — 실제는 `ui/references_adapter.py`(서비스 `service/references.py`), 시험·사진은 가짜. 모든 거절은 `ReferencesRefusal`(고정 문장)이다."""
    sample = False

    def list_rows(self):
        """보관한 글 목록 → `RefListing`."""
        raise NotImplementedError

    def open(self, ref_id):
        """글 하나 → `OpenedRef`."""
        raise NotImplementedError

    def add(self, title, body):
        """붙여 넣은 글을 보관 → `RefRow`."""
        raise NotImplementedError

    def add_file(self, path, title):
        """파일 하나를 보관(제목이 비면 파일 이름에서) → `(RefRow, CP949 로 읽었는지)`."""
        raise NotImplementedError

    def save(self, ref_id, title, body):
        """글의 제목·본문을 덮어쓰기 → `RefRow`."""
        raise NotImplementedError

    def delete(self, ref_id):
        """글 하나를 지운다(화면이 두 단계 확인을 마친 뒤에만 부른다)."""
        raise NotImplementedError

    def folder_text(self):
        """보관함 폴더 위치 글(화면 안내용)."""
        raise NotImplementedError


class FakeReferencesProvider(ReferencesProvider):
    """시험·사진용 — 메모리에 든 글(`items`: {번호: [제목, 본문, 고친 때]})을 다룬다. `refuse` 안에 든 일 이름은 거절하고 `calls` 에 부른 일이 남는다. 글자 수·개수 한도는 진짜 규칙과 같다."""
    sample = True

    def __init__(self, items=None, refuse=(), folder="가짜 보관함 폴더", skipped=0):
        self.items = {key: list(value) for key, value in (items or {}).items()}
        self.refuse, self.folder, self.skipped, self.calls, self.counter = tuple(refuse), folder, skipped, [], 0

    def _gate(self, name):
        self.calls.append(name)
        if name in self.refuse:
            raise ReferencesRefusal("가짜 공급자의 고정 거절 문장이에요")

    def _row(self, ref_id):
        title, body, when = self.items[ref_id]
        return RefRow(ref_id, title, len(body), when)

    def list_rows(self):
        self._gate("list")
        rows = sorted((self._row(key) for key in self.items), key=lambda row: (row.updated_at, row.ref_id), reverse=True)
        return RefListing(tuple(rows), self.skipped)

    def open(self, ref_id):
        self._gate("open")
        if ref_id not in self.items:
            raise ReferencesRefusal("가짜 공급자의 고정 거절 문장이에요")
        title, body, _when = self.items[ref_id]
        return OpenedRef(ref_id, title, body)

    def _check(self, title, body):
        if not str(title).strip() or len(str(title).strip()) > TITLE_MAX or not str(body).strip() or len(str(body)) > BODY_MAX:
            raise ReferencesRefusal("가짜 공급자의 고정 거절 문장이에요")

    def add(self, title, body):
        self._gate("add")
        self._check(title, body)
        if len(self.items) >= MAX_REFERENCES:
            raise ReferencesRefusal("가짜 공급자의 고정 거절 문장이에요")
        self.counter += 1
        ref_id = f"fake{self.counter:04d}"
        self.items[ref_id] = [str(title).strip(), str(body), f"2026-11-15T13:{self.counter % 60:02d}:00Z"]
        return self._row(ref_id)

    def add_file(self, path, title):
        self._gate("add_file")
        return self.add(title or "가져온 글", f"파일 {len(str(path))}자 경로의 글"), False

    def save(self, ref_id, title, body):
        self._gate("save")
        self._check(title, body)
        if ref_id not in self.items:
            raise ReferencesRefusal("가짜 공급자의 고정 거절 문장이에요")
        self.counter += 1
        self.items[ref_id] = [str(title).strip(), str(body), f"2026-11-15T14:{self.counter % 60:02d}:00Z"]
        return self._row(ref_id)

    def delete(self, ref_id):
        self._gate("delete")
        if ref_id not in self.items:
            raise ReferencesRefusal("가짜 공급자의 고정 거절 문장이에요")
        del self.items[ref_id]

    def folder_text(self):
        return self.folder


def digest(title, body):
    """편집 칸 글의 지문 — 저장 안 한 변경이 있는지 견주는 값(글은 남지 않는다)."""
    return hashlib.sha256(f"{len(title)}:{title}\n{body}".encode("utf-8", "surrogatepass")).hexdigest()


def when_text(stamp):
    """보관함의 UTC 시각 글(`2026-11-15T13:00:00Z`) → 한국 시각 `2026-11-15 22:00`. 읽을 수 없는 모양이면 빈 글."""
    try:
        moment = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ") + KST
    except ValueError:
        return ""
    return f"{moment:%Y-%m-%d %H:%M}"


class ReferenceLibrary:
    """대화상자 하나의 상태 — 목록 줄·열린 글 번호와 지문·지우기 확인 단계·세대 번호·마지막 안내. Qt 도 파일도 모르는 순수 논리다."""

    def __init__(self, provider):
        self.provider = provider
        self.generation = 0
        self.is_open = False
        self._clear()

    def _clear(self):
        self.rows, self.skipped = (), 0
        self.mode = "new"                           # new = 새 글 올리기, edit = 열린 글 고치기
        self.current = None                         # 열린 글의 번호(새 글이면 None)
        self.baseline = digest("", "")              # 열릴 때(저장했을 때)의 지문 — 지금 편집 칸의 지문과 견준다
        self.dirty = False
        self.delete_step, self.delete_target = 0, None
        self.pending = None                         # 저장 안 한 변경 확인이 기다리는 일 — `("select", 번호)`·`("new",)`·`("close",)`·`("quit",)`(없으면 None)
        self.loaded = False
        self.message, self.notice = "", ""          # 마지막 안내(거절·실패)의 고정 문장 / 덧붙임(CP949 안내 등)
        self.folder = ""

    # ---- 열고 닫기 · 세대 ----
    def begin(self):
        """일을 시작한다 — 세대 번호를 올리고 돌려준다(이 번호가 아닌 결과는 버려진다)."""
        self.generation += 1
        return self.generation

    def open(self):
        """대화상자를 연다 — 이전 것은 모두 버리고 새 세대로 시작해 목록을 읽는다."""
        self.generation += 1
        self._clear()
        self.is_open = True
        self.folder = self._folder()
        return self.refresh()

    def close(self):
        """어느 길로든 닫는다 — 늦게 오는 결과는 받지 않고(세대가 달라진다) 목록·열린 글 번호·지문을 모두 지운다."""
        self.generation += 1
        self._clear()
        self.is_open = False

    def shutdown(self):
        self.close()

    def _folder(self):
        message, text = None, ""
        try:
            text = str(self.provider.folder_text())
        except ReferencesRefusal as refusal:
            message = refusal.message
        if message is not None:
            text = ""
        return text

    # ---- 목록 ----
    def refresh(self):
        """목록을 다시 읽는다 → `closed`·`loaded`·`failed`(`message`)."""
        if not self.is_open:
            return "closed"
        ticket = self.begin()
        listing, message = None, None
        try:
            listing = self.provider.list_rows()
        except ReferencesRefusal as refusal:
            message = refusal.message
        if message is not None:                     # `except` 밖에서 처리 — 거절 예외를 붙들지 않는다
            return "failed" if self.apply_failed(ticket, message) else "stale"
        return "loaded" if self.apply_list(ticket, listing) else "stale"

    def apply_list(self, ticket, listing):
        """목록이 왔다 → 받았으면 True. 세대가 다르면(닫음·다시 읽음) 버린다."""
        if not self.is_open or ticket != self.generation:
            return False
        self.rows, self.skipped, self.loaded = tuple(listing.rows), int(listing.skipped), True
        if self.current is not None and all(row.ref_id != self.current for row in self.rows):
            self.current, self.mode, self.dirty = None, "new", False        # 열려 있던 글이 사라졌다(다른 곳에서 지움) — 새 글 모습으로
            self.baseline = digest("", "")
        return True

    def apply_failed(self, ticket, message):
        """일이 실패했다 → 지금 일의 실패였으면 True(고정 문장만 보인다)."""
        if not self.is_open or ticket != self.generation:
            return False
        self.message, self.notice = str(message) or T["ref_fail_other"], ""        # 앞 일의 안내('저장했어요' 같은 것)는 이 거절과 함께 남기지 않는다
        return True

    # ---- 열기 · 새 글 ----
    def select(self, ref_id, *, discard=False):
        """목록의 글 하나를 연다 → `(상태, OpenedRef 또는 None)`: `closed`·`dirty`(저장 안 한 변경이 있고 `discard` 가 아니다 — 아무것도 바꾸지 않는다)·`failed`(`message`)·`opened`. 열린 글은 화면이 편집 칸에 채우고 버린다."""
        if not self.is_open:
            return "closed", None
        if self.dirty and not discard:
            self.pending, self.message, self.notice = ("select", str(ref_id)), "", ""      # 버릴지 묻는 중 — 화면이 확인 줄을 보인다(번호만 쥔다). 앞 일의 안내는 거둔다
            return "dirty", None
        ticket = self.begin()
        opened, message = None, None
        try:
            opened = self.provider.open(ref_id)
        except ReferencesRefusal as refusal:
            message = refusal.message
        if message is not None:
            return ("failed" if self.apply_failed(ticket, message) else "stale"), None
        if not self.apply_opened(ticket, opened):
            return "stale", None
        return "opened", opened

    def apply_opened(self, ticket, opened):
        """열린 글이 왔다 → 받았으면 True(고치는 모습으로 바뀌고 지문이 기준이 된다)."""
        if not self.is_open or ticket != self.generation:
            return False
        self.mode, self.current, self.dirty = "edit", opened.ref_id, False
        self.baseline = digest(opened.title, opened.body)
        self.delete_step, self.delete_target, self.pending = 0, None, None
        self.message = self.notice = ""
        return True

    def new_post(self, *, discard=False):
        """`새 글` — 편집 칸을 비우고 새 글 모습으로 → `closed`·`dirty`(저장 안 한 변경이 있고 `discard` 가 아니다)·`ready`."""
        if not self.is_open:
            return "closed"
        if self.dirty and not discard:
            self.pending, self.message, self.notice = ("new",), "", ""
            return "dirty"
        self.begin()
        self.mode, self.current, self.dirty = "new", None, False
        self.baseline = digest("", "")
        self.delete_step, self.delete_target, self.pending = 0, None, None
        self.message = self.notice = ""
        return "ready"

    # ---- 닫기 · Esc · 저장 안 한 변경 확인 ----
    def leave(self, kind="close"):
        """대화상자(또는 프로그램)를 닫으려 한다 → `closed`(이미 닫혀 있다)·`go`(바로 닫아도 된다 — 저장 안 한 변경이 없다)·`ask`(저장 안 한 변경이 있다 — 버릴지 묻는다, `pending` 이 `(kind,)` 가 된다).
        `kind` 는 `close`(닫기 단추·Esc)나 `quit`(창 닫기·Alt+F4 — 프로그램을 닫는 길). 어느 길이든 같은 확인을 거친다."""
        if not self.is_open:
            return "closed"
        if self.dirty:
            self.pending, self.message, self.notice = (kind,), "", ""
            return "ask"
        return "go"

    def keep_editing(self):
        """`계속 고치기` — 기다리던 일을 그만두고 편집을 잇는다 → 기다리던 일이 있었으면 True."""
        had = self.pending is not None
        self.pending = None
        return had

    def take_pending(self):
        """`버리고 …` — 기다리던 일을 돌려주고 비운다(`("select", 번호)`·`("new",)`·`("close",)`·`("quit",)` 또는 None). 변경을 버리고 하는 일은 부른 쪽(화면)이 `discard=True` 로 한다."""
        pending, self.pending = self.pending, None
        return pending

    def escape(self):
        """Esc 가 눌렸다 → 화면이 할 일: `closed`(열려 있지 않다)·`cancel_delete`(지우기 확인을 그만둔다)·`keep_editing`(버릴지 묻는 중이었다 — 계속 고친다)·`ask_close`(저장 안 한 변경이 있어 닫기 전에 묻는다)·`close`(바로 닫는다).
        지우기 확인이 먼저고, 그다음 버릴지 묻는 중인지, 그다음 저장 안 한 변경이다 — Esc 는 닫기 단추와 같은 확인을 거친다(변경을 조용히 버리지 않는다)."""
        if not self.is_open:
            return "closed"
        if self.delete_step:
            return "cancel_delete"
        if self.pending is not None:
            return "keep_editing"
        return "ask_close" if self.leave("close") == "ask" else "close"

    # ---- 편집 ----
    def edited(self, title, body):
        """편집 칸이 바뀌었다 — 지문만 견주어 저장 안 한 변경 표시를 정한다(글은 쥐지 않는다) → `dirty`."""
        if not self.is_open:
            return False
        self.dirty = digest(title if isinstance(title, str) else "", body if isinstance(body, str) else "") != self.baseline
        return self.dirty

    def save(self, title, body):
        """`저장` — 새 글이면 보관, 열린 글이면 덮어쓰기 → `closed`·`refused`(`message` — 한도·빈 글 등, 편집 칸은 그대로)·`saved`. 저장하면 목록을 다시 읽고 그 글이 열린 글이 된다."""
        if not self.is_open:
            return "closed"
        ticket = self.begin()
        row, message = None, None
        try:
            row = self.provider.add(title, body) if self.mode == "new" or self.current is None else self.provider.save(self.current, title, body)
        except ReferencesRefusal as refusal:
            message = refusal.message
        fresh = digest(title if isinstance(title, str) else "", body if isinstance(body, str) else "")
        title = body = None                          # 이 틀이 쥔 글을 놓는다
        if message is not None:
            return "refused" if self.apply_failed(ticket, message) else "stale"
        if ticket != self.generation:
            return "stale"
        self.mode, self.current, self.dirty, self.baseline = "edit", row.ref_id, False, fresh
        self.message, self.notice, self.delete_step, self.delete_target, self.pending = "", T["ref_done_saved"], 0, None, None
        self.refresh()
        return "saved"

    def add_file(self, path, title=""):
        """파일에서 올리기 — 파일 선택 창이 준 위치 하나를 보관한다(빈 위치는 `cancelled` — 공급자를 부르지 않는다) → `closed`·`cancelled`·`refused`·`added`. 새 글은 열린 글이 되지 않고 목록에 더해진다."""
        if not self.is_open:
            return "closed"
        if not path:
            return "cancelled"
        ticket = self.begin()
        row, cp949, message = None, False, None
        try:
            row, cp949 = self.provider.add_file(str(path), str(title or "").strip())
        except ReferencesRefusal as refusal:
            message = refusal.message
        path = None
        if message is not None:
            return "refused" if self.apply_failed(ticket, message) else "stale"
        if ticket != self.generation:
            return "stale"
        self.message = ""
        self.notice = T["ref_done_file"] + (" " + T["ref_note_cp949"] if cp949 else "")
        self.refresh()
        return "added"

    # ---- 지우기(두 단계 확인) ----
    def ask_delete(self):
        """`지우기` — 열려 있는 글을 지우려 한다(1단계 확인을 보인다) → `closed`·`none`(열린 글이 없다)·`step1`."""
        if not self.is_open:
            return "closed"
        if self.current is None:
            self.message = T["ref_none_selected"]
            return "none"
        self.delete_step, self.delete_target, self.message, self.notice = 1, self.current, "", ""
        return "step1"

    def advance_delete(self):
        """확인의 `계속`·`지우기` — 1단계면 2단계로, 2단계면 지운다 → `closed`·`idle`·`step2`·`refused`(`message`)·`deleted`."""
        if not self.is_open or self.delete_step == 0 or self.delete_target is None:
            return "closed" if not self.is_open else "idle"
        if self.delete_step == 1:
            self.delete_step = 2
            return "step2"
        target = self.delete_target
        ticket = self.begin()
        message = None
        try:
            self.provider.delete(target)
        except ReferencesRefusal as refusal:
            message = refusal.message
        target = None
        self.delete_step, self.delete_target = 0, None
        if message is not None:
            return "refused" if self.apply_failed(ticket, message) else "stale"
        if ticket != self.generation:
            return "stale"
        self.mode, self.current, self.dirty, self.baseline, self.pending = "new", None, False, digest("", ""), None
        self.message, self.notice = "", T["ref_done_deleted"]
        self.refresh()
        return "deleted"

    def cancel_delete(self):
        """지우기를 그만둔다(어느 단계에서든) → 그만뒀으면 True."""
        stopped = self.delete_step != 0
        self.delete_step, self.delete_target = 0, None
        return stopped

    # ---- 뷰모델 ----
    def view(self, body_chars=0):
        """대화상자를 그리는 데 필요한 모든 글·숫자·단추 상태. `body_chars` 는 편집 칸 본문의 글자 수(글 자체는 받지 않는다)."""
        rows = []
        for row in self.rows:
            title = display_text(row.title, TITLE_MAX)
            fields = {"title": title, "chars": f"{row.chars:,}", "when": when_text(row.updated_at)}
            selected = row.ref_id == self.current
            rows.append({"id": row.ref_id, "label": T["ref_row"].format(**fields), "selected": selected,
                         "a11y": T["ref_row_selected_a11y" if selected else "ref_row_a11y"].format(**fields),
                         "open": {"text": T["ref_open"], "a11y": T["ref_open_a11y"].format(title=title)}})
        editing = self.mode == "edit" and self.current is not None
        step = self.delete_step
        free = step == 0 and self.pending is None                    # 확인이 열려 있는 동안에는 저장·새 글·파일 올리기·지우기가 꺼진다(닫기만 남는다)
        kind = self.pending[0] if self.pending is not None else ""
        return {
            "title": T["ref_title"], "intro": T["ref_intro"], "limits": T["ref_limits"].format(n=MAX_REFERENCES, title=TITLE_MAX, body=f"{BODY_MAX:,}"),
            "list": {"title": T["ref_list_title"], "a11y": T["ref_list_a11y"], "rows": rows, "count": T["ref_count"].format(n=len(self.rows)),
                     "empty": T["ref_list_empty"] if self.loaded and not rows else "", "loading": T["ref_list_loading"] if not self.loaded else "",
                     "skipped": T["ref_skipped"].format(n=self.skipped) if self.skipped else ""},
            "editor": {"mode": self.mode, "heading": T["ref_editor_edit" if editing else "ref_editor_new"], "title_label": T["ref_title_label"], "title_a11y": T["ref_title_a11y"], "title_hint": T["ref_title_hint"],
                       "body_label": T["ref_body_label"], "body_a11y": T["ref_body_a11y"], "body_hint": T["ref_body_hint"], "count": T["ref_body_count"].format(n=body_chars),
                       "count_a11y": T["ref_body_count_a11y"].format(n=body_chars), "dirty": self.dirty, "state": T["ref_dirty"] if self.dirty else (T["ref_clean"] if editing else "")},
            "buttons": {"save": {"text": T["ref_save"], "a11y": T["ref_save_a11y"], "enabled": free}, "new": {"text": T["ref_new"], "a11y": T["ref_new_a11y"], "enabled": free},
                        "pick": {"text": T["ref_pick"], "a11y": T["ref_pick_a11y"], "enabled": free}, "delete": {"text": T["ref_delete"], "a11y": T["ref_delete_a11y"], "enabled": editing and free},
                        "close": {"text": T["ref_close"], "a11y": T["ref_close_a11y"], "enabled": True}},
            "delete": {"step": step, "question": T["ref_delete_q1"] if step == 1 else T["ref_delete_q2"] if step == 2 else "",
                       "next": {"text": T["ref_delete_next"] if step == 1 else T["ref_delete_yes"], "a11y": T["ref_delete_next_a11y"] if step == 1 else T["ref_delete_yes_a11y"]},
                       "cancel": {"text": T["ref_delete_no"], "a11y": T["ref_delete_no_a11y"]}},
            "discard": {"open": self.pending is not None, "kind": kind, "question": T["ref_discard_q_" + kind] if kind else "", "yes": T["ref_discard_yes_" + kind] if kind else "", "no": T["ref_discard_no"],
                        "yes_a11y": T["ref_discard_yes_a11y_" + kind] if kind else "", "no_a11y": T["ref_discard_no_a11y"]},
            "folder": {"label": T["ref_folder_label"], "text": self.folder, "note": T["ref_folder_note"]},
            "message": self.message, "notice": self.notice, "pick_title": T["ref_pick_title"], "pick_filter": T["ref_pick_filter"],
        }


__all__ = ["BODY_MAX", "FILE_SUFFIXES", "FakeReferencesProvider", "MAX_REFERENCES", "OpenedRef", "RefListing", "RefRow", "ReferenceLibrary", "ReferencesProvider", "ReferencesRefusal", "TITLE_MAX", "digest", "when_text"]
