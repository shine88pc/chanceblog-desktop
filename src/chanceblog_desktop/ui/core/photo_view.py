"""'사진 정리' 창의 화면 쪽 규칙(사진 연동 초안 2단계, 결정 D-499) — 사진 목록 다루기·종류·장소 분위기·들어갈 곳·자리·글자 수·확인(확정)·'모두 확인했어요' 의 확인 줄·순서 ↑↓·지우기와 한 번 되돌리기·못 넣은 파일 목록·30장 한도·파일 상태 배지·
미리보기를 만들지 말아야 하는 큰 PNG 판정·뷰모델. PySide6·파일·서비스를 모른다(그래서 CI 에서 시험한다). 사진 정보의 규칙(한도·경로·번호·확정)은 `content/photo_manifest.py`(1단계)가 정하고 이 파일은 그것을 부르기만 한다.

**저장하지 않는다** — 사진 목록(`PhotoManifest`)은 이 컨트롤러의 메모리에만 있다. 초안을 저장하거나 불러오는 일과 이어지는 것은 3단계다(초안 저장 코드·스키마·`draft_store` 는 건드리지 않았다). 새 초안·화면 떠남·저장한 초안 열기에서 비워진다(`clear` — `DraftsController._clear_draft` 가 부른다).
**글(대상·메모·설명 글)은 이 파일의 어떤 상태·오류·뷰모델 값에도 되풀이되지 않는다** — 입력 칸이 쥐고 있다가 `set_text` 로 값으로만 넘어오고, 검사에 걸린 글은 이유 문장만 남기고 이 객체가 따로 쥐지 않는다(입력 칸이 그대로 보인다). 파일 **경로**는 어떤 뷰모델에도 없다 —
목록 줄에는 파일 이름(폴더 없이, 비밀 모양을 가린 한 줄)만 보이고 못 넣은 파일도 이름과 고정 이유 문장만 있다. 이 파일은 파일·네트워크·로그·시계를 쓰지 않는다. 사진 파일을 읽는 일(판정·상태 확인)은 공급자가 한다(어댑터가 `imagecheck`·서비스를 부른다).

규칙 요약(모두 시험이 못박는다):
  · 사진을 넣을 때마다 `provider.judge` 로 파일을 판정한다(JPG·PNG·WebP 만·실제 형식·20MB). 못 넣은 파일은 이유와 함께 `rejected` 에 모은다(이름만 — 경로 없음). 30장이 차면 나머지는 '30장까지만' 으로 거절한다.
  · 사진의 내용(종류·장소 분위기·대상·메모·들어갈 곳·자리·설명 글)을 실제로 고치면 **확정(확인했어요)이 풀리고** 줄에 한 번 안내가 뜬다(1단계 규칙 그대로). 한도를 넘거나 검사에 걸린 글은 반영하지 않고 이유 문장을 칸 아래에 보인다.
  · 종류를 바꾸면 '들어갈 곳' 이 **사용자가 따로 고르지 않았을 때만** 새 종류의 기본값으로 바뀐다(간판·건물 외관 → 도입, 메뉴판·대표 메뉴·음식·반찬 → 내용 소제목, 인테리어 → 분위기 소제목, 지도 캡처·기타 → 자동).
  · '모두 확인했어요' 는 **확인 줄을 먼저 보이고**(확인할 사진 수) 한 번 더 눌러야 표시한다. 그만두면 아무것도 바뀌지 않는다.
  · 지우기는 사진 정보만 목록에서 뺀다(파일은 그대로) — 방금 지운 한 장은 되돌릴 수 있고 다른 일을 하면 되돌리기가 사라진다.
  · 미리보기는 **PNG 이고 가로×세로가 1억 화소를 넘으면** 만들지 않고 안내한다(사진은 그대로 쓴다 — `photo_rules.preview_blocked`).
  · 종류·장소 분위기 목록은 이 창에서 더하고 지울 수 있다(사진이 쓰는 이름·`기타` 는 못 지운다). 앱을 닫으면 처음 목록으로 돌아간다(새 설정 칸을 만들지 않았다).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...content import photo_manifest as pm
from ...errors import AppError
from . import imagerules as R
from . import photo_rules as rules
from .text import T

CLOSE_WARNED = "close_warned"


@dataclass(frozen=True)
class FileState:
    """사진 파일 하나를 읽기만 해서 본 결과 — 번호·상태(`ok`·`missing`·`link`·`not_file`·`cloud`·`unsupported`·`not_image`·`too_big`·`unreadable`·`unknown`)·고정 문장·경고·크기·형식. 경로는 없다."""
    photo_id: str
    state: str = rules.STATE_UNKNOWN
    message: str = field(default="", repr=False)
    warning: str = field(default="", repr=False)
    width: int = 0
    height: int = 0
    format: str = ""
    verified: bool = False

    @property
    def ok(self):
        return self.state == R.OK

    @property
    def preview_blocked(self):
        return rules.preview_blocked(self.format, self.width, self.height)


@dataclass(frozen=True)
class Rejected:
    """넣지 못한 파일 하나 — 화면에 보일 파일 이름(폴더 없음)과 고정 이유 문장. 이름은 `repr` 에 나오지 않는다."""
    name: str = field(repr=False)
    reason: str = field(repr=False)


class PhotoProvider:
    """공급자 틀 — 실제는 `ui/photo_adapter.py`(`imagecheck` 와 서비스 `check_files`), 시험·사진은 가짜. 사진 파일을 읽기만 한다(쓰지 않는다)."""
    sample = False

    def judge(self, path):
        """파일 하나의 판정 → `imagerules.Verdict`."""
        raise NotImplementedError

    def check(self, manifest):
        """목록의 사진 파일이 아직 그 자리에 있는지 → `(FileState, …)`(사진 순서대로)."""
        raise NotImplementedError


class FakePhotoProvider(PhotoProvider):
    """시험·사진용 — 파일을 읽지 않는다. `verdicts`(경로 → `Verdict`)에 없으면 지원 확장자는 640×480 JPEG 로 통과하고 그 밖은 '지원하지 않는 형식' 이다.
    `states`(경로 → 상태 이름)로 `check` 의 결과를 정한다(없으면 `ok`). `calls` 에는 부른 일의 이름만 남는다(경로 없음)."""
    sample = True

    def __init__(self, verdicts=None, states=None, fail=()):
        self.verdicts, self.states, self.fail = dict(verdicts or {}), dict(states or {}), set(fail)
        self.calls = []

    def judge(self, path):
        self.calls.append("judge")
        if "judge" in self.fail:
            raise RuntimeError("가짜 판정 실패")
        if path in self.verdicts:
            return self.verdicts[path]
        if R.has_supported_extension(path):
            return R.Verdict(R.OK, "", "", 640, 480, "jpeg")
        return R.Verdict(R.UNSUPPORTED, T["img_local_unsupported"])

    def check(self, manifest):
        self.calls.append("check")
        if "check" in self.fail:
            raise RuntimeError("가짜 확인 실패")
        found = []
        for photo in manifest.photos:
            state = self.states.get(photo.local_path, R.OK)
            verdict = self.verdicts.get(photo.local_path)
            found.append(FileState(photo.photo_id, state, "" if state == R.OK else T[rules.BADGE_KEY.get(state, "pho_file_unknown")], getattr(verdict, "warning", "") or "",
                                   getattr(verdict, "width", 640) or 640, getattr(verdict, "height", 480) or 480, getattr(verdict, "format", "jpeg") or "jpeg", verified=True))
        return tuple(found)


def _reason_of(error):
    """사진 정보 규칙(`content/photo_manifest.py`)이 낸 `CONTENT_INVALID` 의 이유 문장(고정 해요체 — 글·경로·파일 이름이 없다). 그 밖의 오류는 고정 안내문이다."""
    item = str(error.slots.get("항목", "")) if error.code == "CONTENT_INVALID" else ""
    head, separator, reason = item.partition(" — ")
    return reason if separator and head.startswith("사진") and reason else T["pho_fail_other"]


class PhotoBoard:
    """한 초안의 사진 목록을 다루는 화면 규칙(저장하지 않는다) + '사진 정리' 창이 열려 있는지. 모든 일은 값을 받아 상태를 바꾸고 짧은 상태 이름(`ok`·`unchanged`·`invalid`·`refused` …)을 돌려준다."""

    def __init__(self, provider=None):
        self.provider = provider if provider is not None else FakePhotoProvider()
        self.is_open = False
        self.generation = 0
        self.types = list(rules.TYPES)
        self.settings = list(rules.SETTINGS)
        self.lists_notice = None
        self.clear()

    def clear(self):
        """새 초안·화면 떠남·저장한 초안 열기 — 사진 목록과 모든 임시 상태를 비운다(종류·장소 분위기 목록의 고침은 앱이 사는 동안 그대로다). 창은 닫힌다."""
        self.manifest = pm.empty_manifest()
        self.states = {}
        self.rejected = ()
        self.errors = {}                                    # (사진 번호, 칸) → 고정 이유 문장 — 글은 담지 않는다
        self.notes = {}                                     # 사진 번호 → 한 번 보이는 안내('확인 표시를 풀었어요')
        self.undo = None                                    # 방금 지운 한 장을 되돌릴 목록(지운 직후에만 — 다른 어떤 고침이 있으면 사라진다)
        self.confirm_all_asked = 0                          # 0 이 아니면 '모두 확인했어요' 확인 줄을 보이는 중 — 확인할 사진 수
        self.notice = None                                  # (수준, 글)
        self.close_warned = False
        self.is_open = False
        self.generation += 1

    # ---- 읽기 ----
    @property
    def count(self):
        return len(self.manifest.photos)

    @property
    def confirmed_count(self):
        return sum(1 for photo in self.manifest.photos if photo.confirmed_by_user)

    @property
    def full(self):
        return self.count >= pm.MAX_PHOTOS

    def photo(self, photo_id):
        found = [item for item in self.manifest.photos if item.photo_id == photo_id]
        return found[0] if found else None

    def local_path(self, photo_id):
        """미리보기를 읽을 때만 쓰는 파일 위치(없으면 빈 글) — **뷰모델에는 없다.** 화면 층이 이미지 읽기 도구(`imagecheck`)에 넘기려고 부르고 화면에 보이지도 어디에 적지도 않는다."""
        photo = self.photo(photo_id)
        return photo.local_path if photo is not None else ""

    def shutdown(self):
        """대화상자가 어느 길로든 닫힌다 — 경고 없이 닫고(한도를 넘긴 글은 버린다) 임시 상태를 비운다. 여러 번 불러도 같다."""
        self.errors = {}                                    # 한도를 넘긴 글을 버리면 닫기가 경고할 이유가 없다
        return self.close()

    def _flag(self, level, text):
        self.notice = (level, text)

    def _refuse(self, key="pho_bad_value"):
        self._flag("error", T[key])
        return "refused"

    # ---- 창 열고 닫기 ----
    def open(self):
        """창을 연다 — 사진 파일이 아직 있는지 다시 읽어 상태를 맞춘다."""
        self.is_open = True
        self.generation += 1
        self.close_warned = False
        self.refresh_files()
        return self.generation

    def close(self):
        """창을 닫는다 — 한도를 넘겨 반영하지 못한 글이 칸에 남아 있으면 처음 한 번은 닫지 않고 알린다(`close_warned`, 한 번 더 누르면 그 글은 버리고 닫는다). 닫으면 못 넣은 파일 목록·확인 줄·되돌리기가 사라진다(사진 목록은 남는다)."""
        if self.errors and not self.close_warned:
            self.close_warned = True
            self._flag("warn", T["pho_over_close"])
            return CLOSE_WARNED
        self.is_open = False
        self.generation += 1
        self.rejected, self.undo, self.confirm_all_asked, self.notice, self.close_warned = (), None, 0, None, False
        self.errors = {}
        return "closed"

    def refresh_files(self):
        """사진 파일이 아직 그 자리에 있는지 읽기만 해서 상태를 맞춘다. 공급자가 실패하면 상태를 '아직 확인하지 않았어요' 로 두고 안내한다."""
        failed = False
        try:
            self.states = {state.photo_id: state for state in self.provider.check(self.manifest)}
        except Exception:                                   # 읽기 도구가 터져도 창이 멈추지 않는다 — 아래에서 안내
            failed = True
            self.states = {}
        if failed:
            self._flag("error", T["pho_fail_other"])
        return "failed" if failed else "ok"

    # ---- 사진 넣기·바꾸기·지우기 ----
    def _default_type(self):
        return pm.DEFAULT_TYPE if pm.DEFAULT_TYPE in self.types else self.types[0]

    def _try_add(self, path):
        """파일 하나를 넣어 보고 못 넣으면 고정 이유 문장, 넣었으면 빈 글을 돌려준다."""
        if self.full:
            return T["pho_rejected_full"].format(n=pm.MAX_PHOTOS)
        problem = pm.path_problem(path)
        if problem is not None:
            return problem
        if pm.path_key(path) in {pm.path_key(item.local_path) for item in self.manifest.photos}:
            return T["pho_rejected_dup"]
        try:
            verdict = self.provider.judge(path)
        except Exception:                                   # 읽기 도구가 터져도 이 파일만 못 넣는다
            return T["img_local_unreadable"]
        if not verdict.ok:
            return verdict.message or T["img_local_unreadable"]
        reason = ""
        try:
            self.manifest, photo_id = pm.add_photo(self.manifest, path, photo_type=self._default_type())
        except AppError as error:
            reason = _reason_of(error)
            error.__traceback__ = None
        if reason:
            return reason
        self.states[photo_id] = FileState(photo_id, R.OK, "", verdict.warning, verdict.width, verdict.height, verdict.format, verified=True)
        return ""

    def add_paths(self, paths):
        """파일 선택 창에서 고른 파일들을 하나씩 넣는다 → `(넣은 수, 못 넣은 수)`. 못 넣은 파일은 이름과 이유만 `rejected` 에 새로 모은다(앞 목록은 이 선택으로 바뀐다). 고르지 않았으면(빈 값) 아무것도 하지 않는다."""
        chosen = [path for path in (paths or ()) if isinstance(path, str) and path]
        if not chosen:
            return 0, 0
        added, rejected = 0, []
        for path in chosen:
            reason = self._try_add(path)
            if reason:
                rejected.append(Rejected(rules.short_name(path), reason))
            else:
                added += 1
        if added:
            self.undo, self.confirm_all_asked = None, 0
        self.rejected = tuple(rejected)
        if added:
            self._flag("info", T["pho_added"].format(n=added))
        elif rejected:
            self.notice = None
        return added, len(rejected)

    def clear_rejected(self):
        self.rejected = ()

    def _apply(self, photo_id, **changes):
        """사진 한 장의 내용을 1단계 규칙(`update_photo`)으로 고친다 → `ok`·`unchanged`·`invalid`. 내용이 바뀌어 확정이 풀리면 줄에 한 번 안내를 남긴다."""
        before = self.photo(photo_id)
        if before is None:
            return self._refuse("pho_bad_photo")
        reason = ""
        updated = None
        try:
            updated = pm.update_photo(self.manifest, photo_id, photo_types=self.types, **changes)
        except AppError as error:
            reason = _reason_of(error)
            error.__traceback__ = None
        if reason:
            self._flag("error", reason)
            return "invalid"
        if updated == self.manifest:
            return "unchanged"
        lost = pm.lost_confirmation(self.manifest, updated)        # 확정이 풀린 사진 번호(1단계 규칙이 알려 준다)
        self.manifest = updated
        self.undo, self.confirm_all_asked = None, 0
        for number in lost:
            self.notes[pm.photo_id_of(number)] = T["pho_unconfirmed_note"]
        return "ok"

    def set_type(self, photo_id, label):
        photo = self.photo(photo_id)
        if photo is None:
            return self._refuse("pho_bad_photo")
        if label not in self.types:
            return self._refuse()
        changes = {"photo_type": label}
        if photo.preferred_section == rules.default_section(photo.photo_type):          # 사용자가 따로 고르지 않았으면 새 종류의 기본 들어갈 곳으로
            changes["preferred_section"] = rules.default_section(label)
        return self._apply(photo_id, **changes)

    def set_setting(self, photo_id, label):
        photo = self.photo(photo_id)
        if photo is None:
            return self._refuse("pho_bad_photo")
        if label and label not in self.settings and label != photo.setting:
            return self._refuse()
        return self._apply(photo_id, setting=label or "")

    def set_text(self, photo_id, name, text):
        """대상·메모·설명 글 — 1단계 글칸 검사(`check_text`)를 통과하면 반영하고, 걸리면 반영하지 않고 이유 문장만 남긴다(칸 아래에 보인다). 글은 이 객체가 쥐지 않는다."""
        if name not in rules.TEXT_FIELDS:
            return self._refuse()
        if self.photo(photo_id) is None:
            return self._refuse("pho_bad_photo")
        clean, reason = pm.check_text(name, text)
        if reason is not None:
            self.errors[(photo_id, name)] = reason
            return "invalid"
        self.errors.pop((photo_id, name), None)
        return self._apply(photo_id, **{name: clean})

    def error_of(self, photo_id, name):
        return self.errors.get((photo_id, name), "")

    def set_section(self, photo_id, value):
        photo = self.photo(photo_id)
        if photo is None:
            return self._refuse("pho_bad_photo")
        if value not in rules.SECTION_CHOICES and value != photo.preferred_section:
            return self._refuse()
        return self._apply(photo_id, preferred_section=value)

    def set_placement(self, photo_id, kind, nth=None):
        """자리 — 문단 뒤·문장 사이만 '몇 번째' 를 받는다(주지 않으면 지금 값, 지금 값도 없으면 1)."""
        photo = self.photo(photo_id)
        if photo is None:
            return self._refuse("pho_bad_photo")
        if kind not in rules.PLACEMENT_KINDS:
            return self._refuse()
        if rules.needs_nth(kind):
            nth = nth if isinstance(nth, int) and not isinstance(nth, bool) else (photo.placement.nth or 1)
            nth = max(1, min(pm.MAX_NTH, nth))
        else:
            nth = 0
        return self._apply(photo_id, placement=pm.Placement(kind, nth))

    def step_nth(self, photo_id, delta):
        """'몇 번째' 를 하나 늘리거나 줄인다(1–50)."""
        photo = self.photo(photo_id)
        if photo is None:
            return self._refuse("pho_bad_photo")
        if not rules.needs_nth(photo.placement.kind) or delta not in (-1, 1):
            return self._refuse()
        return self.set_placement(photo_id, photo.placement.kind, max(1, min(pm.MAX_NTH, photo.placement.nth + delta)))

    # ---- 확인(확정) ----
    def confirm(self, photo_id, on):
        """한 장을 '확인했어요' 로 표시하거나 푼다."""
        if self.photo(photo_id) is None:
            return self._refuse("pho_bad_photo")
        if not isinstance(on, bool):
            return self._refuse()
        before = self.manifest
        self.manifest = pm.set_confirmed(self.manifest, photo_id, on)
        self.notes.pop(photo_id, None)
        self.confirm_all_asked = 0
        if self.manifest == before:
            return "unchanged"
        self.undo = None                                    # 되돌리기는 목록 전체를 되돌리므로 다른 고침이 생기면 쓸 수 없다
        return "ok"

    def ask_confirm_all(self):
        """'모두 확인했어요' 1단계 — 확인하지 않은 사진 수를 확인 줄에 보인다(바꾸지 않는다). 없으면 안내만."""
        waiting = sum(1 for photo in self.manifest.photos if not photo.confirmed_by_user)
        if not waiting:
            self.confirm_all_asked = 0
            self._flag("info", T["pho_all_none"])
            return "none"
        self.confirm_all_asked = waiting
        return "ask"

    def confirm_all(self):
        """2단계 — 확인 줄에서 눌렀을 때만 확인하지 않은 사진을 모두 '확인했어요' 로 표시한다(1단계를 건너뛰고 부르면 아무것도 하지 않는다)."""
        if not self.confirm_all_asked:
            return "refused"
        done = 0
        for photo in self.manifest.photos:
            if not photo.confirmed_by_user:
                self.manifest = pm.set_confirmed(self.manifest, photo.photo_id, True)
                self.notes.pop(photo.photo_id, None)
                done += 1
        self.confirm_all_asked = 0
        self.undo = None
        self._flag("info", T["pho_all_done"].format(n=done))
        return "ok"

    def cancel_confirm_all(self):
        self.confirm_all_asked = 0

    # ---- 순서·지우기·다시 찾기 ----
    def move(self, photo_id, delta):
        """한 칸 위(-1)·아래(+1)로 옮긴다 — 번호는 그대로이고 순서만 바뀐다. 끝이면 `edge`."""
        photo = self.photo(photo_id)
        if photo is None:
            return self._refuse("pho_bad_photo")
        target = photo.display_order + delta
        if delta not in (-1, 1) or not 1 <= target <= self.count:
            self._flag("info", T["pho_bad_order"])
            return "edge"
        self.manifest = pm.move_photo(self.manifest, photo_id, target)
        self.undo, self.confirm_all_asked = None, 0
        return "ok"

    def remove(self, photo_id):
        """사진 정보를 목록에서 뺀다(파일은 그대로) — 방금 지운 이 한 장은 `undo_remove` 로 되돌릴 수 있다."""
        photo = self.photo(photo_id)
        if photo is None:
            return self._refuse("pho_bad_photo")
        snapshot, number = self.manifest, photo.number
        self.manifest = pm.remove_photo(self.manifest, photo_id)
        self.states.pop(photo_id, None)
        for key in [key for key in self.errors if key[0] == photo_id]:
            self.errors.pop(key)
        self.notes.pop(photo_id, None)
        self.confirm_all_asked = 0
        self.undo = snapshot
        self._flag("info", T["pho_removed"].format(n=number))
        return "ok"

    def undo_remove(self):
        if self.undo is None:
            return "refused"
        self.manifest, self.undo = self.undo, None
        self.refresh_files()
        self._flag("info", T["pho_restored"])
        return "ok"

    def relink(self, photo_id, path):
        """`다시 찾기` — 다른 파일(또는 옮긴 파일)로 이어 붙인다. 같은 검사(위치 모양·중복·파일 판정)를 거치고, 바뀌면 확인 표시와 분석 결과가 풀린다(1단계 규칙)."""
        if self.photo(photo_id) is None:
            return self._refuse("pho_bad_photo")
        if not isinstance(path, str) or not path:
            return "cancelled"
        problem = pm.path_problem(path)
        if problem is None and pm.path_key(path) in {pm.path_key(item.local_path) for item in self.manifest.photos if item.photo_id != photo_id}:
            problem = T["pho_rejected_dup"]
        verdict = None
        if problem is None:
            try:
                verdict = self.provider.judge(path)
            except Exception:
                problem = T["img_local_unreadable"]
        if problem is None and not verdict.ok:
            problem = verdict.message or T["img_local_unreadable"]
        if problem is not None:
            self._flag("error", problem)
            return "refused"
        status = self._apply(photo_id, local_path=path)
        if status in ("ok", "unchanged"):
            self.states[photo_id] = FileState(photo_id, R.OK, "", verdict.warning, verdict.width, verdict.height, verdict.format, verified=True)
            self._flag("info", T["pho_relinked"])
        return status

    # ---- 종류·장소 분위기 목록 고치기(앱이 사는 동안만) ----
    def _list_notice(self, level, key, **values):
        self.lists_notice = (level, T[key].format(**values) if values else T[key])

    def _add_label(self, items, field_name, label):
        clean, reason = pm.check_text(field_name, label if isinstance(label, str) else "")
        if reason is not None or not clean:
            self.lists_notice = ("error", reason or T["pho_bad_value"])
            return "invalid"
        if clean.casefold() in {item.casefold() for item in items}:
            self._list_notice("error", "pho_lists_dup")
            return "invalid"
        if len(items) >= rules.MAX_LIST_ITEMS:
            self._list_notice("error", "pho_lists_full", n=rules.MAX_LIST_ITEMS)
            return "invalid"
        items.append(clean)
        self._list_notice("info", "pho_lists_added")
        return "ok"

    def add_type(self, label):
        return self._add_label(self.types, "photo_type", label)

    def add_setting(self, label):
        return self._add_label(self.settings, "setting", label)

    def remove_type(self, label):
        if label == rules.PROTECTED_TYPE:
            self._list_notice("error", "pho_lists_keep")
            return "refused"
        if label not in self.types:
            return self._refuse()
        if any(photo.photo_type == label for photo in self.manifest.photos):
            self._list_notice("error", "pho_lists_in_use")
            return "refused"
        self.types.remove(label)
        self._list_notice("info", "pho_lists_removed")
        return "ok"

    def remove_setting(self, label):
        if label not in self.settings:
            return self._refuse()
        if any(photo.setting == label for photo in self.manifest.photos):
            self._list_notice("error", "pho_lists_in_use")
            return "refused"
        self.settings.remove(label)
        self._list_notice("info", "pho_lists_removed")
        return "ok"

    # ---- 뷰모델 ----
    def card(self):
        """초안 작성 화면의 '사진' 카드 — 장수·확인 수·단추. 사진 정보가 저장한 초안에 함께 담기지 않는다는 안내(3단계 전)를 사진이 있을 때 보인다."""
        count, confirmed = self.count, self.confirmed_count
        return {"title": T["pho_card_title"], "has": count > 0, "count": T["pho_card_count"].format(n=count, c=confirmed) if count else T["pho_card_none"],
                "a11y": T["pho_card_count_a11y"].format(n=count, c=confirmed) if count else T["pho_card_none"], "hint": T["pho_card_hint"], "unsaved": T["pho_card_unsaved"] if count else "",
                "button": T["pho_card_open"] if count else T["pho_card_add"], "button_a11y": T["pho_card_open_a11y"] if count else T["pho_card_add_a11y"],
                "row_title": T["pho_row_title"], "row_desc": T["pho_row_desc"]}

    def _file_vm(self, photo):
        state = self.states.get(photo.photo_id) or FileState(photo.photo_id)
        text = rules.badge(state.state, state.width, state.height)
        return {"state": state.state, "badge": text, "tone": rules.tone_of(state.state), "warning": state.warning, "a11y": T["pho_file_a11y"].format(n=photo.number, status=text),
                "relink": state.state in rules.RELINKABLE, "relink_text": T["pho_relink"], "relink_a11y": T["pho_relink_a11y"].format(n=photo.number), "message": state.message}

    def _text_vm(self, photo, name, label_key, a11y_key, example):
        value = getattr(photo, name)
        limit = rules.FIELD_LIMITS[name]
        return {"name": name, "label": T[label_key], "a11y": T[a11y_key].format(n=photo.number), "value": value, "example": example, "limit": limit, "count": rules.count_text(len(value), limit),
                "error": self.error_of(photo.photo_id, name)}

    def _row(self, photo, index):
        state = self.states.get(photo.photo_id) or FileState(photo.photo_id)
        number = photo.number
        types = list(self.types) + ([photo.photo_type] if photo.photo_type not in self.types else [])
        settings = [("", T["pho_setting_none"])] + [(item, item) for item in self.settings] + ([(photo.setting, photo.setting)] if photo.setting and photo.setting not in self.settings else [])
        placement = photo.placement
        opened = bool(photo.preferred_section or placement.kind != "auto" or photo.caption)
        confirm_text = T["pho_row_confirmed"] if photo.confirmed_by_user else T["pho_row_unconfirmed"]
        return {
            "photo_id": photo.photo_id, "number": number, "label": T["pho_row_label"].format(n=number), "file_name": rules.short_name(photo.local_path), "a11y": T["pho_row_a11y"].format(n=number, type=photo.photo_type, confirm=confirm_text),
            "type": {"label": T["pho_type"], "a11y": T["pho_type_a11y"].format(n=number), "value": photo.photo_type, "choices": types},
            "setting": {"label": T["pho_setting"], "a11y": T["pho_setting_a11y"].format(n=number), "value": photo.setting, "choices": settings},
            "subject": self._text_vm(photo, "user_subject", "pho_subject", "pho_subject_a11y", T["pho_subject_example"].format(example=rules.example_for(photo.photo_type))),
            "note": self._text_vm(photo, "user_note", "pho_note", "pho_note_a11y", T["pho_note_example"]),
            "caption": self._text_vm(photo, "caption", "pho_caption", "pho_caption_a11y", T["pho_caption_example"]),
            "place": {"open": opened, "open_text": T["pho_place_open"], "close_text": T["pho_place_close"], "a11y": T["pho_place_a11y"].format(n=number),
                      "section": {"label": T["pho_section"], "a11y": T["pho_section_a11y"].format(n=number), "value": photo.preferred_section, "choices": rules.section_choices(photo.preferred_section)},
                      "kind": {"label": T["pho_place"], "a11y": T["pho_place_kind_a11y"].format(n=number), "value": placement.kind, "choices": rules.placement_choices()},
                      "nth": {"visible": rules.needs_nth(placement.kind), "label": T["pho_nth"], "value": placement.nth, "text": T["pho_nth_value"].format(k=placement.nth) if placement.nth else "",
                              "less": T["pho_nth_less"], "less_a11y": T["pho_nth_less_a11y"].format(n=number), "more": T["pho_nth_more"], "more_a11y": T["pho_nth_more_a11y"].format(n=number)}},
            "confirmed": photo.confirmed_by_user, "confirm": {"text": T["pho_confirm"], "a11y": T["pho_confirm_a11y"].format(n=number), "status": confirm_text}, "changed_note": self.notes.get(photo.photo_id, ""),
            "file": self._file_vm(photo),
            "preview": {"blocked": state.preview_blocked, "blocked_text": T["pho_preview_blocked"], "a11y": T["pho_preview_a11y"].format(n=number), "wait_text": T["pho_preview_wait"], "failed_text": T["pho_preview_failed"]},
            "up": {"text": T["pho_up"], "a11y": T["pho_up_a11y"].format(n=number), "enabled": index > 0}, "down": {"text": T["pho_down"], "a11y": T["pho_down_a11y"].format(n=number), "enabled": index < self.count - 1},
            "remove": {"text": T["pho_remove"], "a11y": T["pho_remove_a11y"].format(n=number)},
        }

    def _lists_vm(self):
        in_use = {photo.photo_type for photo in self.manifest.photos}, {photo.setting for photo in self.manifest.photos}
        return {"open_text": T["pho_lists_open"], "close_text": T["pho_lists_close"], "a11y": T["pho_lists_a11y"], "note": T["pho_lists_note"],
                "types": {"title": T["pho_lists_type_title"], "items": [{"name": name, "a11y": T["pho_lists_remove_a11y"].format(name=name), "removable": name != rules.PROTECTED_TYPE and name not in in_use[0]} for name in self.types],
                          "new_label": T["pho_lists_new_type"], "new_a11y": T["pho_lists_new_type_a11y"], "add": T["pho_lists_add_type"], "add_a11y": T["pho_lists_add_type_a11y"]},
                "settings": {"title": T["pho_lists_setting_title"], "items": [{"name": name, "a11y": T["pho_lists_remove_a11y"].format(name=name), "removable": name not in in_use[1]} for name in self.settings],
                             "new_label": T["pho_lists_new_setting"], "new_a11y": T["pho_lists_new_setting_a11y"], "add": T["pho_lists_add_setting"], "add_a11y": T["pho_lists_add_setting_a11y"]},
                "notice": {"level": self.lists_notice[0], "text": self.lists_notice[1]} if self.lists_notice else None}

    def view(self):
        """창의 뷰모델 — 규칙은 모두 여기서 정하고 화면은 그리기만 한다. 글(대상·메모·설명 글)은 사진 줄의 값 칸에만 있고 경로는 어디에도 없다."""
        count, confirmed = self.count, self.confirmed_count
        waiting = count - confirmed
        asked = self.confirm_all_asked
        return {
            "open": self.is_open, "title": T["pho_title"], "intro": T["pho_intro"], "limits": T["pho_limits"].format(n=pm.MAX_PHOTOS, subject=pm.MAX_SUBJECT, note=pm.MAX_NOTE, caption=pm.MAX_CAPTION),
            "count": {"text": T["pho_count"].format(n=count, c=confirmed), "a11y": T["pho_count_a11y"].format(n=count, c=confirmed)},
            "empty": T["pho_empty"] if not count else "", "full": T["pho_full"].format(n=pm.MAX_PHOTOS) if self.full else "",
            "add": {"text": T["pho_add"], "a11y": T["pho_add_a11y"], "enabled": not self.full, "title": T["pho_pick_title"], "filter": T["pho_pick_filter"]},
            "confirm_all": {"text": T["pho_confirm_all"], "a11y": T["pho_confirm_all_a11y"], "enabled": waiting > 0 and not asked},
            "confirm_ask": {"text": T["pho_all_ask"].format(n=asked), "yes": T["pho_all_yes"].format(n=asked), "yes_a11y": T["pho_all_yes_a11y"].format(n=asked), "no": T["pho_all_no"], "no_a11y": T["pho_all_no_a11y"]} if asked else None,
            "undo": {"text": T["pho_undo"], "a11y": T["pho_undo_a11y"]} if self.undo is not None else None,
            "notice": {"level": self.notice[0], "text": self.notice[1]} if self.notice else None,
            "rejected": {"title": T["pho_rejected_title"], "rows": [{"text": T["pho_rejected_row"].format(name=item.name, reason=item.reason), "a11y": T["pho_rejected_row"].format(name=item.name, reason=item.reason)} for item in self.rejected],
                         "clear": T["pho_rejected_clear"], "clear_a11y": T["pho_rejected_clear_a11y"]} if self.rejected else None,
            "rows": [self._row(photo, index) for index, photo in enumerate(self.manifest.photos)], "lists": self._lists_vm(),
            "close": {"text": T["pho_close"], "a11y": T["pho_close_a11y"]},
        }


__all__ = ["CLOSE_WARNED", "FakePhotoProvider", "FileState", "PhotoBoard", "PhotoProvider", "Rejected"]
