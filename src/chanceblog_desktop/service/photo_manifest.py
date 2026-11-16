"""사진 Manifest 보관(사진 연동 초안 1단계, 결정 D-496) — 초안 하나의 사진 목록(`content/photo_manifest.py`)을 사용자 데이터 폴더 안 `photo-manifests/` 폴더에 **초안 하나당 JSON 파일 하나**로 보관하고
읽고 지우고, 사진 파일이 아직 그 자리에 있는지 **읽기만** 해서 알려 주는 서비스(화면 없음). 원본 사진은 복사·저장하지 않고 그 안에 사진의 내용(바이트)·EXIF 가 들어가지 않는다. AI·네트워크·하위 프로세스·표준 출력 0.

규칙(모두 fail closed — 의심스러우면 쓰지도 읽지도 않고 고정 문장으로 거절한다):
  · **위치** — `ctx.workspace.root`(= 사용자 데이터 폴더) 아래 `photo-manifests/<초안 번호>.json`. 초안 번호는 저장한 초안의 번호(`dd-` + 16진수 20자, `saved_draft.is_draft_id`)일 때만 파일 이름이 된다 —
    **사용자가 준 글자는 어떤 경우에도 파일 이름이나 경로가 되지 않는다**(`../`·구분자·긴 글·대문자 모두 거절). 저장하지 않은 초안은 번호가 없어 목록이 메모리에만 있다(저장할 때 이 함수로 함께 쓴다). 읽기만 하는 길은 폴더가 없으면
    '사진 없음' 이고 아무것도 만들지 않는다.
  · **저장은 원자적이다** — `context.write_json`(임시 파일에 다 쓰고 디스크에 내려보낸 뒤 이름을 바꿔 넣는다 — 참고 글 보관함과 같다). 임시 파일 이름은 쓸 때마다 다르다(`unique_temp=True`). 쓰기 실패 문장에는 실제 경로 대신 고정 이름
    `사진 정보 폴더` 를 쓴다. 파일 내용은 `PhotoManifest.to_text` 와 같은 글자다(키 정렬·UTF-8·BOM 없음). **분석 결과(읽은 글자·관찰한 대상)는 기본으로 쓰지 않는다**(`persist_analysis=False`).
  · **저장 직전에 키·토큰 모양을 검사한다**(`security/scan.py` — 초안 저장·백업과 같은 검사기, 경로·모든 글칸). 찾으면 **아무것도 쓰지 않고** `CONTENT_INVALID` 로 멈춘다 — 위치(사진 번호·칸)와 종류만 알리고 찾은 글은 다시 보이지 않는다.
  · **깨진 파일은 건드리지 않는다** — 읽을 수 없는 파일(JSON 불량·칸 모양·한도·512KB 초과·파일 이름과 초안 번호가 다름·링크·폴더)은 `broken` 으로 알리고 열지 않는다. 그 위에 새로 저장하려면 `replace_broken=True` 를 줘야 하고,
    그때도 깨진 파일은 지우지 않고 `.bak` 으로 옮겨 둔다(`context.keep_bad_copy`). 보관함 폴더가 링크(윈도의 정션 포함)이거나 폴더가 아니면 모든 길이 거절한다.
  · **지우기는 파일 하나만 정확히 지운다** — 확인(`confirmed=True`)이 있어야 하고(아니면 `CONFIRMATION_REQUIRED`), 번호가 정한 파일 하나와 그 번호의 임시 파일의 `unlink` 뿐이다. 되돌릴 수 없다(전체 백업에는 아직 담지 않는다 — 결정 D-496).
    초안을 지울 때 사진 정보를 함께 지우는 연결은 3단계에서 한다(1단계는 기존 코드를 바꾸지 않는다) — 그 사이에 남은 파일은 `orphans` 로 찾을 수 있다.
  · **사진 파일은 읽기만 본다**(`check_files`) — 경로 위의 폴더까지 링크가 아닌지·보통 파일인지·이 PC 에 내려받은 파일인지(클라우드 '오프라인' 표시면 읽으면 내려받기가 일어나므로 거절)를 `lstat` 으로 보고, 확장자·크기(20MB)·실제 형식·긴 변
    경고는 `ui/core/imagerules.judge` 에 맡긴다(규칙을 새로 만들지 않았다). 이미지 읽기 도구(`probe` — Qt 의 `imagecheck.probe`)를 주지 않으면 확장자만 믿은 점검이라 `verified` 가 거짓이다. 파일을 열거나 쓰거나 바꾸지 않고 복사·썸네일도 만들지 않는다.
  · 오류는 기존 오류 체계의 `CONTENT_INVALID`·`CONTENT_NOT_FOUND`·`CONFIRMATION_REQUIRED`·`FILE_WRITE_FAILED`·`DISK_FULL` 이고 문장은 고정이다 — **글·경로·사진 파일 이름을 오류·로그·`repr` 에 되풀이하지 않는다**.
알려 둔 한계: 목록은 암호화하지 않는다(이 PC 의 사용자 데이터 폴더에 평문 JSON 이다 — 경로에 윈도 사용자 이름이 들어 있을 수 있다). 같은 초안의 동시 저장을 막는 잠금은 없다(앱은 한 번에 하나만 열린다 — 마지막 쓰기가 이기고 파일이 깨지지는 않는다).
저장한 초안을 백업에서 되돌려도 이 파일들은 되돌리지 않는다(전체 백업의 담는 것 목록을 바꾸지 않았다) — 초안과 어긋난 사진 정보는 본문의 자리표시자와 견주는 `placeholder_report` 가 알린다.
"""
from __future__ import annotations

import dataclasses
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from ..content import photo_manifest as pm
from ..content import saved_draft as sd
from ..errors import AppError
from ..security import scan
from . import own_posts
from .context import keep_bad_copy, write_json
from .projects import require_confirmation

SUBJECT = "사진 정보"
FOLDER = "photo-manifests"                               # 사용자 데이터 폴더 아래 폴더 이름
FILE_SUFFIX = ".json"
MAX_FILE_BYTES = pm.MAX_TEXT_BYTES
STATES = ("none", "ok", "broken")
OK, MISSING, LINK, NOT_FILE, CLOUD = "ok", "missing", "link", "not_file", "cloud"

_NAME = re.compile(r"(dd-[0-9a-f]{20})\.json")
_TEMP = re.compile(r"(dd-[0-9a-f]{20})\.json\.(?:\d+-[0-9a-f]{8}\.)?tmp")
_WHERE = "사진 정보 폴더"                                  # 쓰기 실패 문장에 실제 경로 대신 쓰는 고정 이름

_R_ID = "초안 번호가 올바르지 않아요"
_R_FOLDER = "사진 정보 폴더가 올바르지 않아요. 바로 가기나 파일이 아닌 폴더여야 해요"
_R_FOLDER_READ = "사진 정보 폴더를 읽을 수 없어요"
_R_BROKEN = "보관된 사진 정보 파일이 올바르지 않아 열지 않았어요"
_R_SECRET = "그 부분을 지운 뒤 다시 저장해 주세요 — 앱은 글을 자동으로 지우거나 바꾸지 않아요"          # 앞에 위치와 유형(`scan.describe` — 칸·줄·종류뿐 글 내용 없음)이 붙는다
_R_FORM = "사진 정보의 모양이 올바르지 않아요"
_NOT_FOUND = "사진 정보"
_C_LINK = "바로 가기나 링크로 연결된 사진은 쓰지 않아요. 원래 파일을 직접 골라 주세요"
_C_NOT_FILE = "사진 파일이 아니에요. 폴더나 장치가 아니라 파일이어야 해요"
_C_CLOUD = "이 PC 에 내려받지 않은 파일이에요. 먼저 내려받은 뒤 다시 골라 주세요"


@dataclass(frozen=True)
class Loaded:
    """파일에서 읽은 결과 — `state`: `none`(파일 없음 — 빈 목록) · `ok` · `broken`(읽을 수 없음 — 빈 목록, 파일은 그대로)."""
    manifest: object
    state: str


@dataclass(frozen=True)
class FileCheck:
    """사진 파일 하나를 읽기만 해서 본 결과 — 상태(`ok`·`missing`·`link`·`not_file`·`cloud` 와 `imagerules` 의 `unsupported`·`not_image`·`too_big`·`unreadable`)·사용자에게 보일 안내·경고·크기·형식.
    경로는 담지 않는다."""
    photo_id: str
    state: str
    message: str = ""
    warning: str = ""
    width: int = 0
    height: int = 0
    format: str = ""
    verified: bool = False                                  # 진짜 이미지인지 읽기 도구(`probe`)로 확인했는가 — 거짓이면 확장자·크기만 본 점검이다

    @property
    def ok(self):
        return self.state == OK


@dataclass(frozen=True)
class Listing:
    """보관한 사진 정보들의 초안 번호(정렬) + 읽을 수 없어 건너뛴 파일 수."""
    draft_ids: tuple
    skipped: int = 0


def _refuse(reason):
    """기존 오류 체계(`CONTENT_INVALID`)의 고정 문장 오류 — 글·경로·파일 이름은 문장에도 세부에도 없다."""
    return AppError("CONTENT_INVALID", {"항목": f"{SUBJECT} — {reason}"}, detail=reason)


def _not_found():
    return AppError("CONTENT_NOT_FOUND", {"항목": _NOT_FOUND}, detail="없는 사진 정보")


def is_draft_id(draft_id):
    """파일 이름이 되어도 되는 초안 번호(`dd-` + 16진수 20자)인가."""
    return sd.is_draft_id(draft_id)


def folder_path(ctx):
    """사진 정보 폴더의 위치(`<사용자 데이터 폴더>/photo-manifests`) — 폴더를 만들지도 읽지도 않는다."""
    return ctx.workspace.root / FOLDER


def _file_of(ctx, draft_id):
    """초안 번호(`is_draft_id` 를 통과한 것만 — 부르는 쪽이 먼저 확인한다) → 파일 위치."""
    return folder_path(ctx) / f"{draft_id}{FILE_SUFFIX}"


def _lstat(path):
    """링크를 따라가지 않는 상태 정보 또는 None(없음·권한·잘못된 글자 …). OS 오류의 글에는 경로가 들어 있으므로 버린다."""
    try:
        return os.lstat(path)
    except (OSError, ValueError):
        return None


def _folder_problem(folder):
    """폴더가 링크(윈도의 정션 포함)이거나 폴더가 아니면 **아직 내지 않은** 오류 객체, 아니면 None(폴더가 아직 없어도 None). 모든 길이 이 검사를 먼저 한다."""
    info = _lstat(folder)
    if info is not None and (not stat.S_ISDIR(info.st_mode) or own_posts._link_like(info)):
        return _refuse(_R_FOLDER)
    return None


def _scan_names(folder):
    """폴더 안에서 정확한 이름 모양(`<초안 번호>.json`)인 파일들의 초안 번호(정렬) → `(번호들, None)` 또는 `(None, 오류 객체)` — 폴더가 없으면 빈 목록이다."""
    problem = _folder_problem(folder)
    if problem is not None:
        return None, problem
    if _lstat(folder) is None:
        return [], None
    names = None
    try:
        with os.scandir(folder) as entries:
            names = [entry.name for entry in entries]
    except OSError:
        names = None
    if names is None:                                      # `except` 밖에서 만든다 — OS 오류(경로가 든 글)가 따라붙지 않게
        return None, _refuse(_R_FOLDER_READ)
    return sorted(found.group(1) for found in (_NAME.fullmatch(name) for name in names) if found), None


def _read_file(path, draft_id):
    """파일 하나를 읽는다 → `(PhotoManifest, "ok")` · `(None, "none")`(없다) · `(None, "broken")`(읽을 수 없다 — 모양·크기·링크·글자·칸·이름과 초안 번호가 다름 어느 것이든)."""
    info = _lstat(path)
    if info is None:
        return None, "none"
    if not stat.S_ISREG(info.st_mode) or own_posts._link_like(info) or info.st_size > MAX_FILE_BYTES:
        return None, "broken"
    data, reason = own_posts._read_prefix(path, MAX_FILE_BYTES + 1, info)       # 읽기 전용 `rb` 로 상한 + 1 바이트까지만(`own_posts` 의 읽기 규칙 그대로)
    if reason is not None or len(data) > MAX_FILE_BYTES:
        return None, "broken"
    manifest = None
    try:
        manifest = pm.PhotoManifest.from_text(data.decode("utf-8"))
    except (AppError, UnicodeDecodeError):
        manifest = None
    if manifest is None or manifest.draft_id != draft_id:
        return None, "broken"
    return manifest, "ok"


def load_manifest(ctx, draft_id):
    """저장한 초안의 사진 목록을 읽는다(읽기만) → `Loaded(목록, 상태)`. 파일이 없으면 빈 목록(`none`), 읽을 수 없으면 빈 목록(`broken` — 파일은 그대로)이다. 초안 번호 모양이 틀리면 `CONTENT_INVALID`."""
    if not is_draft_id(draft_id):
        raise _refuse(_R_ID)
    problem = _folder_problem(folder_path(ctx))
    if problem is not None:
        raise problem
    manifest, state = _read_file(_file_of(ctx, draft_id), draft_id)
    return Loaded(manifest if manifest is not None else pm.empty_manifest(draft_id), state)


def _secret_reason(manifest, persist_analysis):
    """저장할 모든 글(경로·글칸·남기는 분석 항목)에 키·토큰 모양이 있으면 위치·종류 문장, 없으면 None."""
    fields = {}
    for photo in manifest.photos:
        label = f"사진 {photo.number}"
        for name, text in (("파일 위치", photo.local_path), ("종류", photo.photo_type), ("장소 분위기", photo.setting), ("대상", photo.user_subject), ("메모", photo.user_note),
                           ("들어갈 위치", photo.preferred_section), ("설명 글", photo.caption)):
            fields[f"{label} {name}"] = text
        if persist_analysis:
            for name, items in (("관찰한 대상", photo.observed_objects), ("읽은 글자", photo.visible_text)):
                fields[f"{label} {name}"] = "\n".join(item.text for item in items)
    found = scan.scan_fields(fields)
    return f"{scan.describe(found[0])}. {_R_SECRET}" if found else None


def _save_failure(error_code):
    """쓰기 실패 → 경로 없는 고정 이름의 오류 객체(내는 일은 부른 쪽이 `except` 밖에서 한다)."""
    return AppError("DISK_FULL" if error_code == "DISK_FULL" else "FILE_WRITE_FAILED", {"경로": _WHERE}, detail="사진 정보 파일을 쓰지 못했다")


def save_manifest(ctx, draft_id, manifest, *, persist_analysis=False, replace_broken=False):
    """초안의 사진 목록을 원자적으로 쓴다 → 쓴 목록(`draft_id` 가 이 초안 번호로 채워진다). 키·토큰 모양이 있으면 아무것도 쓰지 않고 `CONTENT_INVALID`. 바뀐 것이 없으면 쓰지 않고, 사진이 없는 목록은 파일이 없을 때 파일을 만들지 않는다.
    분석 결과는 `persist_analysis=True` 일 때만 쓴다(기본은 빈 목록으로 쓴다). 깨진 파일이 있으면 `replace_broken=True` 가 아닌 한 거절하고, 그때도 깨진 파일은 `.bak` 으로 옮겨 둔다."""
    if not is_draft_id(draft_id):
        raise _refuse(_R_ID)
    if not isinstance(manifest, pm.PhotoManifest):
        raise _refuse(_R_FORM)
    manifest = dataclasses.replace(manifest, draft_id=draft_id)
    reason = _secret_reason(manifest, persist_analysis)
    if reason is not None:
        raise _refuse(reason)
    problem = _folder_problem(folder_path(ctx))
    if problem is not None:
        raise problem
    path = _file_of(ctx, draft_id)
    old, state = _read_file(path, draft_id)
    if state == "broken" and not replace_broken:
        raise _refuse(_R_BROKEN)
    if state == "none" and not manifest.photos:
        return manifest
    if state == "ok" and old.to_text(True) == manifest.to_text(persist_analysis):
        return manifest                                    # 바뀐 것이 없다(파일에 든 분석 결과까지 같다) — 쓰지 않는다. 분석 결과를 안 쓰기로 했는데 파일에 남아 있으면 같지 않아 다시 쓴다
    failure = None
    try:
        if state == "broken":
            keep_bad_copy(path)                            # 깨진 파일은 지우지 않고 `.bak` 으로 옮겨 둔다(못 옮기면 쓰지 않는다)
        write_json(path, manifest.to_dict(persist_analysis), unique_temp=True)
    except AppError as error:
        failure = error.code
        error.__traceback__ = None                         # 호출 흔적이 붙드는 경로를 놓는다
    if failure is not None:
        raise _save_failure(failure)
    return manifest


def _leftovers(folder, draft_id):
    """이 초안 번호의 임시 파일들(쓰다 프로세스가 죽어 남은 것) — 정확한 이름 모양이고 링크가 아닌 보통 파일인 것만 → 위치 목록."""
    with os.scandir(folder) as entries:
        return [Path(entry.path) for entry in entries if (found := _TEMP.fullmatch(entry.name)) and found.group(1) == draft_id and entry.is_file(follow_symlinks=False)]


def delete_manifest(ctx, draft_id, *, confirmed):
    """초안의 사진 정보 파일 하나를 지운다 — 번호가 정한 **파일 하나만** 정확히 지운다(확인 `confirmed=True` 가 있어야 하고, 아니면 아무것도 하지 않고 `CONFIRMATION_REQUIRED`). 없으면 `CONTENT_NOT_FOUND`.
    파일이 아닌 것(링크·폴더)은 지우지 않고 거절한다. 읽을 수 없는(깨진) 파일도 지울 수 있다. 되돌릴 수 없다."""
    require_confirmation(confirmed, "사진 정보 지우기")
    if not is_draft_id(draft_id):
        raise _refuse(_R_ID)
    folder = folder_path(ctx)
    problem = _folder_problem(folder)
    if problem is not None:
        raise problem
    path = _file_of(ctx, draft_id)
    info = _lstat(path)
    if info is None:
        raise _not_found()
    if not stat.S_ISREG(info.st_mode) or own_posts._link_like(info):
        raise _refuse(_R_BROKEN)
    state = "gone"
    try:
        for temp in _leftovers(folder, draft_id):          # 쓰다 프로세스가 죽어 남은 임시 파일도 함께 지운다 — 목록만 지우고 사본이 남지 않게
            temp.unlink(missing_ok=True)
        path.unlink()
        state = "done"
    except FileNotFoundError:
        state = "gone"
    except OSError:
        state = "failed"
    if state == "gone":                                    # `except` 밖에서 낸다
        raise _not_found()
    if state == "failed":
        raise AppError("FILE_WRITE_FAILED", {"경로": _WHERE}, detail="사진 정보 파일을 지우지 못했다")


def list_manifests(ctx):
    """보관한 사진 정보들의 초안 번호(정렬) — 읽기만 한다. 읽을 수 없는 파일은 건너뛰고 개수만 `skipped` 로 알린다. 폴더가 없으면 빈 목록이고 아무것도 만들지 않는다."""
    found, problem = _scan_names(folder_path(ctx))
    if problem is not None:
        raise problem
    ids, skipped = [], 0
    for draft_id in found:
        manifest, state = _read_file(_file_of(ctx, draft_id), draft_id)
        if state == "ok":
            ids.append(draft_id)
        else:
            skipped += 1
    return Listing(tuple(ids), skipped)


def orphans(ctx, known_draft_ids):
    """사진 정보 파일은 있는데 `known_draft_ids`(지금 저장돼 있는 초안 번호들)에 없는 초안 번호들 — 읽기만 한다(파일을 열지 않고 이름만 본다). 지우는 일은 `delete_manifest`(확인 필요)로 따로 한다."""
    known = {draft_id for draft_id in known_draft_ids if is_draft_id(draft_id)}
    found, problem = _scan_names(folder_path(ctx))
    if problem is not None:
        raise problem
    return tuple(draft_id for draft_id in found if draft_id not in known)


# ---- 사진 파일 보기(읽기만) ------------------------------------------------------------------------------------------------------------------
def _extension_probe(path):
    """읽기 도구 없이 쓰는 대신 — 확장자만 믿는 `Probe`(진짜 이미지인지는 모른다)."""
    from ..ui.core import imagerules
    return imagerules.Probe(True, os.path.splitext(str(path))[1].lower().lstrip("."), 0, 0)


def _inspect_photo(path):
    """경로 위의 모든 폴더가 링크가 아니고 마지막이 보통 파일이며 이 PC 에 내려받은 파일인지 본다(`lstat` 만 — 읽지 않는다) → 상태 이름(`ok`·`missing`·`link`·`not_file`·`cloud`)."""
    pure = Path(path)
    current, info = Path(pure.parts[0]), None
    for part in pure.parts[1:]:
        current = current / part
        info = _lstat(current)
        if info is None:
            return MISSING
        if own_posts._link_like(info):
            return LINK
    if info is None:
        return MISSING
    if not stat.S_ISREG(info.st_mode):
        return NOT_FILE
    if getattr(info, "st_file_attributes", 0) & own_posts._NOT_LOCAL:
        return CLOUD
    return OK


def check_files(manifest, *, probe=None):
    """목록의 사진 파일이 아직 그 자리에 있는지 읽기만 해서 본다 → `(FileCheck, …)`(사진 순서대로). 파일이 사라졌으면 `missing`(화면이 '파일 없음' 으로 보인다).
    `probe` 는 이미지 읽기 도구(`imagerules.Probe` 를 돌려주는 함수 — 화면 층의 `imagecheck.probe`)이고, 주지 않으면 확장자·크기만 본다(`verified=False`)."""
    from ..ui.core import imagerules
    if not isinstance(manifest, pm.PhotoManifest):
        raise _refuse(_R_FORM)
    results = []
    for photo in manifest.photos:
        place = _inspect_photo(photo.local_path)
        if place != OK:
            message = {MISSING: imagerules.T[imagerules.MESSAGES[imagerules.MISSING]], LINK: _C_LINK, NOT_FILE: _C_NOT_FILE, CLOUD: _C_CLOUD}[place]
            results.append(FileCheck(photo.photo_id, place, message))
            continue
        verdict = imagerules.judge(photo.local_path, probe if probe is not None else _extension_probe)
        results.append(FileCheck(photo.photo_id, verdict.kind, verdict.message, verdict.warning, verdict.width, verdict.height, verdict.format, verified=probe is not None))
    return tuple(results)


__all__ = ["FileCheck", "Listing", "Loaded", "check_files", "delete_manifest", "folder_path", "is_draft_id", "list_manifests", "load_manifest", "orphans", "save_manifest"]
