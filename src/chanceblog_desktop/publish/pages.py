"""연결한 chanceblog 저장소에 글 한 편을 **새 가지에만** 올린다(docs/ARCHITECTURE.md §3 '발행', PUBPR — 원격 main 으로 가는 길은 이 모듈에도 `src/` 어디에도 없다).

사람이 GitHub 에서 PR 로 검토·병합하고 앱은 병합을 '확인'만 한다. 세 단계로 나눠 부른다 — 중간에 멈춰도 같은 글을 두 번 올리지 않고 이어서 할 수 있게:

  build_branch_commit  글 검사(경로·머리말·제어 문자·키 모양 문자열) → 연결 확인 → 원격 main 받기(원격 추적 참조만 바뀐다) → 같은 글이 이미 있는지 → **객체만** 만든다
                (`hash-object`·`mktree`·`commit-tree`). 작업 폴더의 파일·색인·로컬 가지·HEAD 는 한 바이트도 바뀌지 않는다. 만든 커밋은 받은 원격 main 위에 글 파일 하나를 더한 것이다.
  push_branch          그 커밋을 `desktop/post-…` 모양의 **새 가지 하나**에 올린다. 올리기 직전에 원격 main 을 다시 받아(읽기) 만든 커밋의 부모가 거기서 닿는지 본다 — main 의 이력이 다시 쓰여 닿지 않으면 보내지 않는다(지운 옛 이력이 새 공개 가지로
                되살아나는 길). 같은 가지가 이미 원격에 있고 끝이 같으면 아무것도 보내지 않고 이어 간다(멱등), 끝이 다르면 덮어쓰지 않고 거절한다.
  post_on_main         병합 확인 — 원격 main 에 그 경로로 **한 글자도 다르지 않은** 글이 있는지만 읽는다(병합 방식은 가리지 않는다).
  compare_link         GitHub 비교 화면 주소(글자로만 보여 주고 앱은 열지 않는다).

옛 방식(main 에 곧바로 commit·push)의 `commit_post`·`discard_commit` 은 옛 `COMMITTED` 글을 읽고 되돌리기 위해서만 남아 있다 — 새 흐름은 부르지 못한다. `push_commit`·`publish_post` 는 없앴다.
앱은 사용자의 다른 변경·커밋을 건드리지 않고 강제 push(--force)·삭제·태그 push 를 하지 않으며 브랜치를 바꾸지 않고 사용자의 훅과 서명(gpg) 대화창을 쓰지 않는다(모든 git 호출이 훅·서명을 끄고 네트워크 명령은
`gitrepo.network_shape` 의 정해진 모양만 지난다 — gitrepo.run_git). 주소 확인(배포 뒤 글이 열리는지)은 deploy.py 다.
"""
from __future__ import annotations

import datetime
import errno
import hashlib
import os
import re
import stat
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .. import capabilities
from ..core import use_vendored_core
from ..errors import UNEXPECTED, AppError
from ..render.pages import KST, front_matter_problems, post_path
from ..security import scan
from ..security.mask import _INVISIBLE, _strip_invisible, has_key_shape_anywhere, mask       # 비밀을 눈에 안 보이는 글자로 쪼갠 것도 찾으려고 같은 패키지의 정리 함수를 쓴다
from . import gitrepo
from .gitrepo import BRANCH_NAME, BRANCH_PREFIX, EXPECTED_ORIGIN, EXPECTED_OWNER, EXPECTED_REPO, MAIN, inspect_repo, run_git, sync_latest

use_vendored_core()
from pipeline.secret_patterns import find_secrets  # noqa: E402  (vendor/ 경로를 먼저 올려야 한다)

# 글 파일의 경로: `_posts/<분야 폴더 하나>/YYYY-MM-DD-KR|EN-HHMMSS.md`(render.pages.post_path 가 만드는 모양). 폴더 안 이름에는 경로 구분자·Windows 금지 문자·제어 문자가 없고, 숫자는 ASCII 만이다
POST_PATH = re.compile(r'_posts/[^/\\:*?"<>|\x00-\x1f\x7f]+/(\d{4})-(\d{2})-(\d{2})-(?:KR|EN)-(\d{2})(\d{2})(\d{2})\.md', re.ASCII)
_BAD_TEXT = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\ufffe\uffff]")      # 탭·줄바꿈 말고는 제어 문자(CR 포함: 렌더는 LF 만 낸다. 줄바꿈 변환(autocrlf)이 있는 PC 에서 CR 이 든 글은 commit 뒤 내용이 달라져 영영 못 올린다)
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))})        # Windows 가 파일 이름으로 못 쓰는 이름
_HIDDEN = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp", "Zs"})                    # 폴더 이름에 넣지 않는 글자 범주(보통 공백 한 칸만 허용)
MAX_POST_BYTES = 500_000
_COMMIT_PREFIX = "글 올리기(데스크톱 앱):"
_REMOTE_MAIN = f"refs/remotes/origin/{MAIN}"


@dataclass(frozen=True)
class CommitInfo:
    path: str
    commit: str       # 만든 커밋. push 때 최신 위로 옮겨지면 바뀌므로 push_commit 이 돌려주는 값을 쓴다
    base: str         # 그 커밋의 부모 = 쓰기 직전의 원격 main


@dataclass(frozen=True)
class BranchCommit:
    """`build_branch_commit` 이 만든 커밋 — 아직 올리지 않았다(객체만 있다)."""
    path: str         # 글 파일 경로
    branch: str       # 올릴 가지 이름(`desktop/post-…` — 상수 접두사와 숫자·16진수뿐)
    commit: str       # 만든 커밋(40자)
    base: str         # 그 커밋의 부모 = 받은 원격 main


@dataclass(frozen=True)
class BranchPush:
    """`push_branch` 의 결과."""
    branch: str
    commit: str       # 가지 끝 커밋(원격에서 확인했다)
    already: bool     # 이미 같은 가지가 같은 끝으로 올라가 있어 아무것도 보내지 않았다


@dataclass(frozen=True)
class MainCheck:
    """`post_on_main` 의 판정 — `merged`(같은 경로에 한 글자도 다르지 않은 글이 있다)·`different`(같은 경로에 다른 글이 있다)·`not_yet`(그 경로에 글이 없다)."""
    state: str
    commit: str = ""  # merged 일 때 글을 처음 담은 main 커밋(40자)
    moved_to: str = ""  # not_yet 인데 같은 내용이 다른 경로에 있을 때 그 경로(자동으로 이어받지 않는다 — 알리기만)


def _bad(item, detail=""):
    return AppError("CONTENT_INVALID", {"항목": item}, detail=detail)


def secret_labels(text):
    """글 속 키·토큰 모양의 이름들(중복 없이, 없으면 빈 집합) — 올리기 직전 마지막 관문이 앱의 **모든** 모양 목록을 본다(L8 F069, 결정 D-556): ① 정본(vendor/)의 이름 있는 패턴 ② 본문 속 비밀 형태 검사기의 여섯 유형(`security/scan.py`)
    ③ 앱의 가리기 목록(`security/mask.has_key_shape` — `sk-proj-`·Anthropic·npm·JWT·Bearer·Slack 웹훅·개인 키 머리말과 최근에 생긴 접두사 모양)을 글 끝까지. 예전에는 ①만 봐서 복사 관문·저장 관문이 막는 모양을 이 관문이 놓쳤다.
    값은 돌려주지 않는다 — 이름뿐이다. 눈에 안 보이는 글자로 쪼갠 키도 같은 방식으로 찾는다."""
    view = _strip_invisible(text)
    found = {label for label, _preview in find_secrets(view)}
    found.update(scan.KIND_LABELS[item.kind] for item in scan.scan_secrets(view))
    if not found and has_key_shape_anywhere(view):
        found.add("키·토큰 모양")
    return found


def check_post(post):
    """글(경로·내용)이 올려도 되는 모양인지. 아니면 AppError. 파일·저장소는 건드리지 않는다."""
    path = getattr(post, "path", None)
    text = getattr(post, "text", None)
    found = POST_PATH.fullmatch(path) if isinstance(path, str) else None
    if not found:
        raise _bad("글 경로", detail="_posts/<분야>/YYYY-MM-DD-KR|EN-HHMMSS.md 모양이 아니다")
    year, month, day, hour, minute, second = (int(part) for part in found.groups())
    try:
        datetime.date(year, month, day)
    except ValueError:
        raise _bad("글 경로", detail="날짜가 올바르지 않다") from None
    if hour > 23 or minute > 59 or second > 59:
        raise _bad("글 경로", detail="시각이 올바르지 않다")
    folder = path.split("/")[1]
    if folder != folder.strip(" .") or folder.split(".")[0].strip().upper() in _RESERVED or any(ch != " " and unicodedata.category(ch) in _HIDDEN for ch in folder) or _INVISIBLE.search(folder):
        raise _bad("글 경로", detail="분야 폴더 이름이 올바르지 않다")      # `.`·`..`·끝에 점·공백(Windows 에서 사라지거나 위쪽 폴더를 가리킨다)·예약 이름·보이지 않는 글자
    if not isinstance(text, str):                     # 빈 글·공백뿐인 글은 아래 머리말 검사가 걸러 낸다
        raise _bad("글 내용")
    if _BAD_TEXT.search(text):
        raise _bad("글 내용", detail="제어 문자가 들어 있다")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise _bad("글 내용", detail="올바르지 않은 글자가 들어 있다") from None
    if size > MAX_POST_BYTES:
        raise _bad("글 내용", detail="너무 크다")
    problems = front_matter_problems(text)
    if problems:
        raise _bad("머리말", detail="; ".join(problems))
    secrets = secret_labels(text)
    if secrets:
        raise AppError("SECRET_IN_TEXT_BLOCKED", detail="키 모양 문자열: " + ", ".join(sorted(secrets)))


def _inside(root, target):
    """쓸 곳이 저장소 안인지(저장소 안 링크·정션이 밖을 가리켜도 밖에 쓰지 않게 실제 경로로 비교한다)."""
    try:
        return Path(os.path.realpath(target.parent)).is_relative_to(Path(os.path.realpath(root)))
    except (OSError, ValueError):
        return False


def _file_error(error, target):
    number = getattr(error, "errno", None)
    if number == errno.ENOSPC:
        code = "DISK_FULL"
    elif number == errno.ENAMETOOLONG or getattr(error, "winerror", None) == 206:
        code = "FILE_PATH_TOO_LONG"
    else:
        code = "FILE_WRITE_FAILED"
    return AppError(code, {"경로": str(target)}, detail=f"{type(error).__name__}: {mask(error.strerror or str(error))}"[:300])


def _commit_message(path, title):
    name = " ".join(str(title or "").split())[:80] or Path(path).name
    return f"{_COMMIT_PREFIX} {name}\n\n파일: {path}\n"


def _note_left(error, left):
    """치우지 못한 것의 이름을 오류의 세부에 덧붙인다 — 다음에 무엇을 봐야 하는지 알 수 있게(조용히 남기지 않는다)."""
    if left and isinstance(error, AppError):
        note = "치우지 못한 것: " + ", ".join(mask(name)[:80] for name in left[:5])
        error.detail = f"{error.detail} | {note}" if error.detail else note
    return error


def _unstage(git, root, path):
    """스테이징을 취소한다(reset, 안 먹으면 색인에서 직접 뺀다 — 단 HEAD 에 이미 있는 글이면 빼지 않는다: 커밋이 만들어진 뒤라면 삭제가 스테이징된다).
    돌려주는 것: 못 한 것의 이름들."""
    left = []
    try:
        git(root, ["reset", "--quiet", "--", path])
        if git(root, ["ls-files", "--error-unmatch", "--", path]).returncode == 0:            # 색인에 아직 남아 있다(reset 이 안 먹었다) — 색인에서 뺀다
            if git(root, ["cat-file", "-e", f"HEAD:{path}"]).returncode != 0:                 # HEAD 에 있는 글이면 이미 커밋된 것이다 — 빼지 않는다
                git(root, ["rm", "--cached", "--quiet", "--ignore-unmatch", "--", path])
                if git(root, ["ls-files", "--error-unmatch", "--", path]).returncode == 0:
                    left.append(f"{path}(스테이징)")
    except Exception:
        left.append(f"{path}(스테이징)")
    return left


def _discard(git, root, path, target, created_folder):
    """커밋까지 가지 못했을 때 우리가 만든 것만 치운다: 스테이징 취소 → 파일 삭제 → (우리가 만든) 빈 폴더 삭제. 치우다 실패해도 원래 오류를 가리지 않는다.
    돌려주는 것: 치우지 못한 것의 이름들."""
    left = _unstage(git, root, path)
    for attempt in range(3):                              # 백신·색인기가 잠깐 쥐고 있을 수 있다
        try:
            target.unlink(missing_ok=True)
            break
        except OSError:
            if attempt < 2:
                time.sleep(0.2)
            else:
                left.append(path)
    if created_folder:
        try:
            target.parent.rmdir()
        except OSError:
            pass
    return left


def _head(git, root):
    """지금 HEAD 의 커밋 번호. 못 읽으면 ''. 시간 초과 직후라 git 이 잠깐 바쁠 수 있어 세 번까지 다시 읽는다(읽기 자체가 시간 초과로 멈췄으면 더 기다리지 않는다)."""
    for attempt in range(3):
        try:
            done = git(root, ["rev-parse", "HEAD"])
        except AppError as error:
            if error.code == "NETWORK_TIMEOUT":
                return ""
            done = None
        except Exception:
            done = None
        if done is not None and done.returncode == 0:
            return done.stdout.strip()
        if attempt < 2:
            time.sleep(0.3)
    return ""


def _is_my_plain_copy(path, expected):
    """그 경로가 링크가 아닌 일반 파일이고(하드 링크도 아니다) 크기와 내용이 expected 와 같은가 — 링크는 따라가지 않는다(밖의 파일을 가리키는 링크를 내 파일로 오인하지 않게)."""
    try:
        found = os.lstat(path)
        if not stat.S_ISREG(found.st_mode) or found.st_nlink != 1 or found.st_size != len(expected):
            return False
        return Path(path).read_bytes() == expected
    except OSError:
        return False


def _head_has(git, root, path):
    """지금 HEAD 가 그 경로의 파일을 이미 갖고 있는가(알 수 없으면 갖고 있다고 본다 — 지우는 쪽이 더 나쁘다)."""
    try:
        return git(root, ["cat-file", "-e", f"HEAD:{path}"]).returncode == 0
    except Exception:
        return True


def _clear_my_staged_leftover(git, root, post):
    """지난번 실패가 남긴 '이 글 하나만 스테이징된' 상태(HEAD 를 못 읽어 치우지 못한 경우 등)면 그 스테이징만 취소해 다음 시도가 막히지 않게 한다.
    스테이징된 것이 정확히 이 글 하나이고 파일 내용이 글과 같을 때만 — 그 밖의 변경이 하나라도 있으면 아무것도 하지 않는다. 치웠으면 True."""
    done = git(root, ["status", "--porcelain", "-z", "--untracked-files=no"])
    if done.returncode != 0 or [entry for entry in done.stdout.split("\0") if entry] != [f"A  {post.path}"]:
        return False
    if not _is_my_plain_copy(Path(root) / post.path, post.text.encode("utf-8")):
        return False
    return not _unstage(git, root, post.path)


def _is_own_leftover(git, root, existing, target, post):
    """같은 이름의 글이 '내가 올리려던 바로 그 파일이 지난번 실패 뒤 못 지워진 채' 남은 것인가 — 그 파일 하나뿐이고(이름이 대소문자까지 같고), 링크가 아닌 일반 파일이며,
    git 이 추적하지 않고, 내용이 같다."""
    if len(existing) != 1 or existing[0].name != target.name or existing[0].parent != target.parent:
        return False
    if git(root, ["ls-files", "--error-unmatch", "--", post.path]).returncode == 0:      # git 이 이미 추적한다 = 남은 파일이 아니라 올라온 글
        return False
    return _is_my_plain_copy(existing[0], post.text.encode("utf-8"))        # 링크는 따라가지 않는다: 밖의 파일을 가리키는 링크·다른 이름이 같은 파일인 하드 링크는 내 파일이 아니다


def commit_post(repo_path, post, *, title="", git=run_git, expected_origin=EXPECTED_ORIGIN):
    """연결한 저장소를 최신으로 맞추고 글 파일을 써서 그 파일만 commit 한다(올리지는 않는다). 같은 글(주소)이 이미 있으면 DUPLICATE_SLUG."""
    capabilities.require_external_write("글 파일 기록(commit)")      # 외부 Write 관문 — 이 시험 버전은 꺼져 있어 git 을 부르기 전에 거절한다
    check_post(post)
    if secret_labels(str(title or "")):
        raise AppError("SECRET_IN_TEXT_BLOCKED", detail="commit 제목에 키 모양 문자열이 있다")           # 제목은 공개 저장소의 commit 기록에 그대로 남는다
    try:
        info = sync_latest(repo_path, git, expected_origin)
    except AppError as error:
        if error.code != "PAGES_LOCAL_REPO_DIRTY" or not _clear_my_staged_leftover(git, Path(repo_path), post):
            raise
        info = sync_latest(repo_path, git, expected_origin)          # 바뀐 것이 지난번에 내가 스테이징해 둔 이 글 하나뿐이었다 — 치웠으니 다시
    root = info.path
    stem = Path(post.path).stem                       # YYYY-MM-DD-KR-HHMMSS — Jekyll 주소는 분야 폴더와 무관하게 이 이름으로 정해진다
    posts_dir = root / "_posts"
    folder = post.path.split("/")[1]
    if posts_dir.is_dir():
        clash = sorted(entry.name for entry in posts_dir.iterdir() if entry.name != folder and entry.name.casefold() == folder.casefold())
        if clash:                                     # 대소문자를 구분하지 않는 곳에서는 git 이 기존 이름으로 기록해 우리 경로와 어긋나 commit 이 실패한다
            raise _bad("글 경로", detail=f"분야 폴더가 이미 있는 폴더와 대소문자만 다르다: {clash[0]}")
    target = root / post.path
    if not _inside(root, target):
        raise _bad("글 경로", detail="저장소 밖을 가리킨다")
    existing = sorted(posts_dir.rglob(stem + ".*")) if posts_dir.is_dir() else []
    reuse = False
    if existing:
        if not _is_own_leftover(git, root, existing, target, post):
            raise AppError("DUPLICATE_SLUG", detail=f"같은 이름의 글이 이미 있다: {stem}")
        reuse = True                                  # 지난번 실패 뒤 못 지운 내 파일 — 다시 쓰지 않고 그대로 이어 간다
    _require_main(git, root)                          # 검사 뒤 사용자가 다른 브랜치로 바꿨으면 그 브랜치에 글 커밋을 얹지 않는다(쓰기 바로 앞에서 본다 — 쓰기부터 add 까지는 git 호출이 없다)
    created_folder = not target.parent.exists()
    try:
        if not reuse:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "xb") as handle:
                handle.write(post.text.encode("utf-8"))
    except FileExistsError:
        raise AppError("DUPLICATE_SLUG", detail=f"같은 이름의 글이 이미 있다: {stem}") from None
    except OSError as error:
        raise _note_left(_file_error(error, target), _discard(git, root, post.path, target, created_folder)) from None
    committed = False
    try:
        gitrepo._must(git, root, ["add", "--", post.path], "글 파일 추가")
        _require_main(git, root)                      # add 가 오래 걸리는 사이 사용자가 브랜치를 바꿨을 수 있다 — commit 바로 앞에서 한 번 더 본다
        with tempfile.TemporaryDirectory() as tmp:
            message = Path(tmp) / "message.txt"
            message.write_text(_commit_message(post.path, title), encoding="utf-8", newline="\n")
            gitrepo._must(git, root, ["commit", "--only", "--no-verify", "--quiet", "-F", str(message), "--", post.path], "글 기록")
        committed = True
        commit = gitrepo._must(git, root, ["rev-parse", "HEAD"], "기록 확인")
        changes = gitrepo._must(git, root, ["diff-tree", "-z", "--no-commit-id", "--name-status", "-r", "HEAD"], "기록 내용 확인").split("\0")
        if [item for item in changes if item] != ["A", post.path]:
            raise AppError(UNEXPECTED, detail="만든 커밋에 글 파일 하나 말고 다른 변경이 있다")
    except BaseException as error:
        # commit 이 만들어진 뒤에 시간 초과 같은 예외가 났을 수 있다 — HEAD 가 옮겨졌으면 글과 커밋은 그대로 두고(이어서 올릴 수 있다) 알리기만 한다
        if isinstance(error, AppError) and error.code == "NETWORK_TIMEOUT":
            gitrepo._clear_stale_index_lock(git, root)            # 시간 초과로 끈 git 이 남긴 잠금 — 두면 다음 시도가 영영 막힌다
        now = _head(git, root)
        if not committed and (now == info.head or (isinstance(error, AppError) and error.code == "PAGES_LOCAL_REPO_NOT_MAIN")):         # main 이 아니라서 멈춘 것도 '커밋이 안 만들어졌다' 는 뜻이다
            # 이번에 우리가 쓴 것만 치운다: 지난번에 남은 내 파일을 이어 쓰던 중이었으면 그 파일은 지우지 않는다
            keep_file = reuse or (isinstance(error, AppError) and error.code == "PAGES_LOCAL_REPO_NOT_MAIN" and _head_has(git, root, post.path))      # 다른 브랜치가 그 경로를 이미 추적하면 그 브랜치의 파일이다
            _note_left(error, _unstage(git, root, post.path) if keep_file else _discard(git, root, post.path, target, created_folder))
        elif not committed and not now:
            _note_left(error, [f"{post.path}(HEAD 를 읽지 못해 그대로 둠)"])      # 커밋이 만들어졌는지 알 수 없으면 지우지 않는다
        raise
    return CommitInfo(post.path, commit, info.head)


def _require_main(git, root):
    """검사 뒤 사용자가 다른 브랜치로 바꿨을 수 있다 — rebase 는 지금 HEAD 에 하므로 main 일 때만 한다."""
    branch = gitrepo._current_branch(git, root)
    if branch != MAIN:
        raise AppError("PAGES_LOCAL_REPO_NOT_MAIN", {"브랜치": branch})


def discard_commit(repo_path, info, *, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """끝내 올리지 못한 글 커밋(commit_post 가 돌려준 info)을 되돌린다: 커밋과 글 파일을 치워 저장소를 처음 상태로 돌린다 — 다른 변경은 건드리지 않는다.
    HEAD 가 info.commit 이고 그 부모가 info.base 이며 글 파일 하나만 더한 커밋(제목도 앱이 만든 것)일 때만 하고, 마지막으로 받아 둔 원격 main 에 이미 들어 있는 커밋이면 거절한다.
    **이 PC 안의 일뿐이다**(PUBPR — 옛 방식의 `COMMITTED` 글을 되돌리는 길만 남겼다. 원격 main 을 새로 받는 네트워크 확인은 뺐다 — 새 흐름은 이 상태를 만들지 않고 main 으로 올리는 코드는 없다).
    올리다 최신 위로 옮겨진 뒤에는 info.commit 이 낡아 거절된다 — 그때는 사람이 확인한다."""
    capabilities.require_external_write("올리지 않은 글 기록 되돌리기")
    if not isinstance(info.path, str) or not POST_PATH.fullmatch(info.path):         # info 를 그대로 믿지 않는다: 글 경로 모양이 아니면 다른 파일을 지울 수 있다
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail="되돌릴 글 경로가 올바르지 않다")
    repo = inspect_repo(repo_path, git, expected_origin)
    root = repo.path
    if repo.head != info.commit or gitrepo._must(git, root, ["rev-parse", "HEAD^"], "부모 확인") != info.base:
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail="지금 HEAD 가 되돌릴 글 커밋이 아니다")
    changes = gitrepo._must(git, root, ["diff-tree", "-z", "--no-commit-id", "--name-status", "-r", "HEAD"], "올릴 커밋 확인").split("\0")
    if [item for item in changes if item] != ["A", info.path]:
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail="되돌릴 커밋이 글 하나만 더한 것이 아니다")
    subject = gitrepo._must(git, root, ["log", "-1", "--format=%s", "HEAD"], "커밋 제목 확인")
    if not subject.startswith(_COMMIT_PREFIX):
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail="되돌릴 커밋이 앱이 만든 글 커밋이 아니다")
    if git(root, ["merge-base", "--is-ancestor", info.commit, _REMOTE_MAIN]).returncode == 0:
        raise AppError(UNEXPECTED, detail="이미 원격 main 에 올라간 커밋이라 되돌리지 않는다")
    try:
        gitrepo._must(git, root, ["reset", "--soft", info.base], "글 커밋 되돌리기")
    except AppError as error:
        if error.code == "NETWORK_TIMEOUT":
            gitrepo._clear_stale_index_lock(git, root)
        raise
    left = _discard(git, root, info.path, root / info.path, False)
    if left:
        raise _note_left(AppError("FILE_WRITE_FAILED", {"경로": str(root / info.path)}, detail="커밋은 되돌렸지만 파일을 다 치우지 못했다"), left)


# ---- PUBPR: 새 가지에만 올린다(객체만 만들기 · 가지 올리기 · 병합 확인 · 비교 링크) ------------------------------------------------------------------------------
COMPARE_MAX_CHARS = 1500       # 비교 링크의 길이 상한(문서에 414 한도가 있다고만 적혀 있어 보수적으로 잡았다)
COMPARE_TITLE_CHARS = 120
_COMMIT_ID = re.compile(r"[0-9a-f]{40}", re.ASCII)


def branch_name(post):
    """글 하나가 올라갈 가지 이름: `desktop/post-<YYYYMMDD>-<HHMMSS>-<8자 16진수>` — 앞 두 토막은 글 파일 이름과 같은 한국 시각이고 끝은 `sha256(글 경로 + 줄바꿈 + 승인한 글)` 의 앞 8자리다(이름 겹침 방지·멱등).
    **제목·분야·태그 같은 사용자 글에서 온 글자는 한 글자도 들어가지 않는다**(가지 이름의 금지 글자가 들어갈 길이 없다)."""
    found = POST_PATH.fullmatch(post.path) if isinstance(getattr(post, "path", None), str) else None
    if not found or not isinstance(getattr(post, "text", None), str):
        raise _bad("글 경로", detail="_posts/<분야>/YYYY-MM-DD-KR|EN-HHMMSS.md 모양이 아니다")
    year, month, day, hour, minute, second = found.groups()
    digest = hashlib.sha256((post.path + "\n" + post.text).encode("utf-8")).hexdigest()[:8]
    name = f"{BRANCH_PREFIX}{year}{month}{day}-{hour}{minute}{second}-{digest}"
    if BRANCH_NAME.fullmatch(name) is None:                                           # 닿을 수 없는 길 — 그래도 이름 규칙은 한 곳에서만 만든다
        raise AppError(UNEXPECTED, detail="가지 이름이 정해진 모양이 아니다")
    return name


def post_path_for_branch(branch, category, lang):
    """가지 이름의 시각과 글 머리말의 분야·언어로 글 파일 경로를 다시 만든다(`render.pages.post_path` 와 같은 함수) — 발행 기록 파일이 없어도(백업을 되돌린 뒤) 병합 확인을 이어 가려고 쓴다. 모양이 틀리면 None."""
    found = re.fullmatch(r"desktop/post-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-[0-9a-f]{8}", branch, re.ASCII) if isinstance(branch, str) else None
    if not found:
        return None
    try:
        stamp = datetime.datetime(*(int(part) for part in found.groups()), tzinfo=KST)
        path = post_path(category, lang, stamp)
    except (ValueError, KeyError, AppError):
        return None
    return path if POST_PATH.fullmatch(path) else None


def _read_tree(git, root, treeish):
    """`git ls-tree -z <커밋 또는 트리>` → [(모드, 종류, 번호, 이름)]. 읽을 수 없는 글자가 든 이름이 있으면 거절한다(그대로 되쓰면 이름이 바뀐다)."""
    done = git(root, ["ls-tree", "-z", treeish])
    if done.returncode != 0:
        raise gitrepo._failure(done, "저장소 목록 읽기", root)
    entries = []
    for item in done.stdout.split("\0"):
        if not item:
            continue
        meta, tab, name = item.partition(chr(9))
        parts = meta.split(" ")
        if not tab or len(parts) != 3 or not name or "�" in name:
            raise AppError(UNEXPECTED, detail="저장소 목록의 모양이 이상하거나 읽을 수 없는 이름이 있어 올리지 않았다")
        entries.append((parts[0], parts[1], parts[2], name))
    return entries


def _make_tree(git, root, entries):
    """항목들로 트리 객체를 만든다(`git mktree -z --missing` — 항목 순서는 git 이 가다듬는다. 이미 있던 항목을 그대로 다시 쓰는 것이라 `--missing` 으로 내려받지 않은 파일이 있는 저장소도 된다) → 트리 번호."""
    data = b"".join(f"{mode} {kind} {number}\t{name}\0".encode("utf-8") for mode, kind, number, name in entries)
    made = git(root, ["mktree", "-z", "--missing"], input_bytes=data)
    if made.returncode != 0:
        raise gitrepo._failure(made, "글을 담을 목록 만들기", root)
    number = made.stdout.strip()
    if _COMMIT_ID.fullmatch(number) is None:
        raise AppError(UNEXPECTED, detail="만든 목록의 번호를 읽지 못했다")
    return number


def _blob_number(git, root, text, *, write):
    """승인한 글의 UTF-8 바이트를 **변환 없이**(`--no-filters`: 줄바꿈 변환(autocrlf)·필터가 없다) 내용 번호(blob)로 만든다. `write=False` 면 저장하지 않고 번호만 계산한다."""
    args = ["hash-object", "--no-filters", "--stdin"] + (["-w"] if write else [])
    done = git(root, args, input_bytes=text.encode("utf-8"))
    if done.returncode != 0:
        raise gitrepo._failure(done, "글 내용 번호 만들기", root)
    number = done.stdout.strip()
    if _COMMIT_ID.fullmatch(number) is None:
        raise AppError(UNEXPECTED, detail="글 내용 번호를 읽지 못했다")
    return number


def _main_tip(git, root):
    done = git(root, ["rev-parse", "--verify", "--quiet", _REMOTE_MAIN + "^{commit}"])
    number = done.stdout.strip()
    if done.returncode != 0 or _COMMIT_ID.fullmatch(number) is None:
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail="받아 둔 원격 main 을 읽을 수 없다")
    return number


def base_reaches_main(repo_path, base, *, git=run_git):
    """이어받을 글 커밋의 부모(`base`)가 이 PC 에 **마지막으로 받아 둔** 원격 main 에서 닿는가 — `git merge-base --is-ancestor <base> refs/remotes/origin/main` 이 0 이면 닿는다(읽기만 한다 — 받지는 않는다).
    main 의 이력이 다시 쓰여(비밀 제거 같은 이유) 그 부모가 main 에서 닿지 않게 됐다면, 올리다 막혀 남은 글 커밋을 이어받아 올리는 순간 **지운 옛 이력이 새 공개 가지로 되살아난다** — 그래서 이어받기 전에 이것을 본다
    (`push_branch` 는 원격 main 을 새로 받은 뒤 같은 확인을 한다 — 거기가 마지막 문이다). 부모 모양이 아니거나 부모 객체가 없거나 git 이 실패하면 닿지 않는 것으로 본다(닿는다고 믿지 않는다)."""
    if not isinstance(base, str) or _COMMIT_ID.fullmatch(base) is None:
        return False
    return git(Path(repo_path), ["merge-base", "--is-ancestor", base, _REMOTE_MAIN]).returncode == 0


def _check_not_on_main(git, root, base, post, blob):
    """받은 원격 main 의 `_posts` 아래에 같은 주소(날짜-언어-시각)의 글이나 내용이 한 글자도 다르지 않은 글이 있는지 — 있으면 DUPLICATE_SLUG·DUPLICATE_CONTENT."""
    listing = git(root, ["ls-tree", "-r", "-z", base, "--", "_posts"])
    if listing.returncode != 0:
        raise gitrepo._failure(listing, "원격 main 의 글 목록 읽기", root)
    stem = Path(post.path).stem
    for item in listing.stdout.split("\0"):
        meta, tab, name = item.partition(chr(9))
        parts = meta.split()
        if not tab or len(parts) != 3 or parts[1] != "blob":
            continue
        if name.rsplit("/", 1)[-1].startswith(stem + "."):
            raise AppError("DUPLICATE_SLUG", detail=f"원격 main 에 같은 주소(날짜-언어-시각)의 글이 이미 있다: {mask(name)[:120]}")
        if parts[2] == blob:
            raise AppError("DUPLICATE_CONTENT", {"파일": name}, detail="내용이 똑같은 글이 원격 main 에 이미 있다: " + mask(name)[:120])


def build_branch_commit(repo_path, post, *, title="", git=run_git, expected_origin=EXPECTED_ORIGIN):
    """받은 원격 main 위에 글 파일 하나를 더한 **커밋 한 개를 객체로만** 만든다(작업 폴더·색인·로컬 가지·HEAD 는 그대로 — 올리지도 않는다). 같은 글(주소·내용)이 원격 main 에 이미 있으면 DUPLICATE_SLUG·DUPLICATE_CONTENT.
    순서: 글 검사 → 연결 확인(깨끗한 main 요구는 그대로) → 원격 main 받기(읽기) → 중복 점검 → `hash-object -w --no-filters` → 트리 세 단계(`mktree`) → `commit-tree` → 만든 커밋이 정확히 글 하나만 더했는지 확인."""
    capabilities.require_external_write("새 가지에 올릴 글 커밋 만들기")
    capabilities.require_net("pages_branch", "새 가지에 올릴 글 커밋 만들기")           # 둘째 문장: 좁은 스위치도 함께(D-736)
    check_post(post)
    if secret_labels(str(title or "")):
        raise AppError("SECRET_IN_TEXT_BLOCKED", detail="commit 제목에 키 모양 문자열이 있다")           # 제목은 공개 저장소의 commit 기록에 그대로 남는다
    branch = branch_name(post)
    info = inspect_repo(repo_path, git, expected_origin)
    root = info.path
    gitrepo.fetch_main(root, git, expected_origin)                                      # 받기가 성공해야 시작한다 — 낡은 기준으로 커밋을 만들지 않는다
    base = _main_tip(git, root)
    blob = _blob_number(git, root, post.text, write=False)
    _check_not_on_main(git, root, base, post, blob)
    blob = _blob_number(git, root, post.text, write=True)
    category, filename = post.path.split("/")[1], post.path.rsplit("/", 1)[-1]
    root_entries = _read_tree(git, root, base)
    posts_entry = next((item for item in root_entries if item[3] == "_posts"), None)
    if posts_entry is not None and posts_entry[1] != "tree":
        raise _bad("글 경로", detail="원격 main 의 `_posts` 가 폴더가 아니다")
    posts_entries = _read_tree(git, root, posts_entry[2]) if posts_entry is not None else []
    clash = sorted(item[3] for item in posts_entries if item[3] != category and item[3].casefold() == category.casefold())
    if clash:                                                                           # 대소문자를 구분하지 않는 곳에서는 git 이 기존 이름으로 기록해 우리 경로와 어긋난다
        raise _bad("글 경로", detail=f"분야 폴더가 이미 있는 폴더와 대소문자만 다르다: {clash[0]}")
    category_entry = next((item for item in posts_entries if item[3] == category), None)
    if category_entry is not None and category_entry[1] != "tree":
        raise _bad("글 경로", detail="분야 폴더 이름이 폴더가 아닌 파일과 같다")
    category_entries = _read_tree(git, root, category_entry[2]) if category_entry is not None else []
    if any(item[3] == filename for item in category_entries):
        raise AppError("DUPLICATE_SLUG", detail=f"같은 이름의 글이 이미 있다: {Path(post.path).stem}")
    category_tree = _make_tree(git, root, category_entries + [("100644", "blob", blob, filename)])
    posts_tree = _make_tree(git, root, [item for item in posts_entries if item[3] != category] + [("040000", "tree", category_tree, category)])
    root_tree = _make_tree(git, root, [item for item in root_entries if item[3] != "_posts"] + [("040000", "tree", posts_tree, "_posts")])
    made = git(root, ["commit-tree", root_tree, "-p", base, "-F", "-"], input_bytes=_commit_message(post.path, title).encode("utf-8"))
    if made.returncode != 0:
        raise gitrepo._failure(made, "글 커밋 만들기", root)
    commit = made.stdout.strip()
    if _COMMIT_ID.fullmatch(commit) is None:
        raise AppError(UNEXPECTED, detail="만든 커밋 번호를 읽지 못했다")
    built = BranchCommit(post.path, branch, commit, base)
    _verify_commit(git, root, built, post, blob)
    return built


def _verify_commit(git, root, built, post, blob=None):
    """그 커밋이 이 저장소에 있고, 부모 하나 위에 **글 파일 하나만 더한 것**이며(`A` + 경로), 그 파일의 내용이 승인한 글과 한 글자도 다르지 않은가."""
    present = git(root, ["cat-file", "-e", f"{built.commit}^{{commit}}"])
    if present.returncode != 0:
        raise AppError(UNEXPECTED, detail="만들어 둔 글 커밋이 이 저장소에 없다 — 다시 만든다")
    changes = gitrepo._must(git, root, ["diff-tree", "-z", "--no-commit-id", "--name-status", "-r", built.commit], "만든 커밋 내용 확인").split("\0")
    if [item for item in changes if item] != ["A", post.path]:
        raise AppError(UNEXPECTED, detail="만든 커밋에 글 파일 하나 말고 다른 변경이 있다")
    parent = gitrepo._must(git, root, ["rev-parse", f"{built.commit}^"], "부모 확인")
    if parent != built.base:
        raise AppError(UNEXPECTED, detail="만든 커밋의 부모가 받은 원격 main 이 아니다")
    expected = blob if blob is not None else _blob_number(git, root, post.text, write=False)
    if gitrepo._must(git, root, ["rev-parse", f"{built.commit}:{post.path}"], "글 내용 확인") != expected:
        raise AppError(UNEXPECTED, detail="만든 커밋 속 글이 승인한 글과 다르다")


def branch_on_remote(repo_path, branch, *, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """원격에 그 가지가 있으면 끝 커밋(40자), 없으면 None — `ls-remote` 로 읽기만 한다."""
    capabilities.require_external_write("올린 가지 확인")
    capabilities.require_net("pages_branch", "올린 가지 확인")
    return gitrepo.remote_branch_tip(repo_path, branch, git, expected_origin)


def push_branch(repo_path, built, post, *, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """`build_branch_commit` 이 만든 커밋을 **새 가지 하나**에 올린다(강제 push 없음 — 인자는 정해진 한 모양뿐이고 main 은 시도하지 않는다). 같은 일을 두 번 해도 같은 결과다:
    원격에 그 가지가 이미 있고 끝이 이 커밋이면 아무것도 보내지 않고 이어 가며(`already`), 끝이 다르면 덮어쓰지 않고 PAGES_PUSH_REFUSED(이름 충돌). 올린 뒤 다시 `ls-remote` 로 확인한 뒤에만 성공이다.
    올렸는데 응답이 끊겼으면(시간 초과·연결 실패) 가지를 한 번 더 읽어 보고, 이미 올라갔으면 두 번째 push 를 하지 않는다.
    **올리기 전에 원격 main 을 다시 받고**(읽기 — 원격 추적 참조만 바뀐다) 만든 커밋의 부모(`built.base`)가 거기서 닿는지 본다: 올리다 막혀 남은 커밋을 이어받는 사이 main 의 이력이 다시 쓰였다면(비밀을 지우려고 이력을 고친 경우 등) 그 커밋을 올리는 것이
    지운 옛 이력을 새 공개 가지로 되살리는 일이므로 보내지 않고 UNEXPECTED(세부에 '다시 만든다')로 멈춘다 — 호출한 쪽(`pages_flow._branch_stage`)이 기록을 치우고 지금의 main 위에서 한 번 새로 만든다. 같은 가지가 이미 올라가 있어도(`already`) 이 확인이 먼저다."""
    capabilities.require_external_write("새 가지에 올리기(push)")
    capabilities.require_net("pages_branch", "새 가지에 올리기(push)")                  # 둘째 문장: 좁은 스위치도 함께(D-736)
    check_post(post)
    if (not isinstance(built, BranchCommit) or built.path != post.path or BRANCH_NAME.fullmatch(str(built.branch)) is None or built.branch != branch_name(post)
            or _COMMIT_ID.fullmatch(str(built.commit)) is None or _COMMIT_ID.fullmatch(str(built.base)) is None):
        raise AppError("PAGES_PUSH_REFUSED", detail="올릴 가지·커밋 정보가 정해진 모양이 아니다")
    info = inspect_repo(repo_path, git, expected_origin)
    root = info.path
    _verify_commit(git, root, built, post)                                              # 올리기 직전에도 '글 하나만 더한 커밋' 이 맞는지 다시 본다
    gitrepo.fetch_main(root, git, expected_origin)                                      # 이어받은 낡은 커밋이 이력이 다시 쓰인 main 의 옛 부모를 공개 가지에 되살리지 않게 — 지금의 원격 main 을 받아(읽기) 견준다
    if not base_reaches_main(root, built.base, git=git):
        raise AppError(UNEXPECTED, detail="만들어 둔 글 커밋의 부모가 지금의 원격 main 에서 닿지 않는다(main 의 이력이 다시 쓰였을 수 있다) — 다시 만든다")
    tip = gitrepo.remote_branch_tip(root, built.branch, git, expected_origin)
    if tip == built.commit:
        return BranchPush(built.branch, built.commit, True)
    if tip is not None:
        raise AppError("PAGES_PUSH_REFUSED", detail="같은 이름의 가지가 다른 내용으로 이미 원격에 있어 덮어쓰지 않고 멈췄다")
    gitrepo.recheck_origin(git, root, expected_origin)
    try:
        result = git(root, ["push", "--porcelain", "--no-verify", "origin", f"{built.commit}:refs/heads/{built.branch}"])
        failure = None if result.returncode == 0 else gitrepo._failure(result, "새 가지에 올리기", root)
    except AppError as error:
        failure = error
    if failure is not None:
        if failure.code in ("NETWORK_TIMEOUT", "GIT_PUSH_NETWORK"):
            try:
                if gitrepo.remote_branch_tip(root, built.branch, git, expected_origin) == built.commit:      # 올라갔는데 응답만 끊겼다
                    return BranchPush(built.branch, built.commit, False)
            except AppError:
                pass                                                                    # 확인도 못 했다 — 처음 오류를 그대로 알린다(다시 하면 위의 `ls-remote` 가 이어 준다)
        raise failure
    if gitrepo.remote_branch_tip(root, built.branch, git, expected_origin) != built.commit:
        raise AppError(UNEXPECTED, detail="올렸는데 원격에 그 가지가 없다")
    return BranchPush(built.branch, built.commit, False)


def post_on_main(repo_path, post, *, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """병합 확인 — 원격 main 을 받아(읽기) 그 경로에 **한 글자도 다르지 않은** 글이 있는지만 본다(`merged`). 일반 병합·squash·rebase 가리지 않는다. 그 경로에 다른 글이 있으면 `different`, 글이 없으면 `not_yet`
    (같은 내용이 다른 경로에 있으면 `moved_to` 에 그 경로만 알린다 — 자동으로 이어받지 않는다). 병합됐으면 그 글을 처음 담은 main 커밋을 함께 돌려준다. 아무것도 쓰지 않는다."""
    capabilities.require_external_write("병합 확인(원격 main 읽기)")
    capabilities.require_net("pages_branch", "병합 확인(원격 main 읽기)")                # 둘째 문장: 좁은 스위치도 함께(D-736)
    check_post(post)
    info = inspect_repo(repo_path, git, expected_origin)
    root = info.path
    gitrepo.fetch_main(root, git, expected_origin)
    base = _main_tip(git, root)
    wanted = _blob_number(git, root, post.text, write=False)
    found = git(root, ["rev-parse", "--verify", "--quiet", f"{base}:{post.path}"])
    there = found.stdout.strip()
    if found.returncode == 0 and _COMMIT_ID.fullmatch(there):
        if there != wanted:
            return MainCheck("different")
        added = git(root, ["log", "--diff-filter=A", "-1", "--format=%H", base, "--", post.path])
        first = added.stdout.strip() if added.returncode == 0 else ""
        return MainCheck("merged", commit=first if _COMMIT_ID.fullmatch(first) else base)
    listing = git(root, ["ls-tree", "-r", "-z", base, "--", "_posts"])
    if listing.returncode == 0:
        for item in listing.stdout.split("\0"):
            meta, tab, name = item.partition(chr(9))
            parts = meta.split()
            if tab and len(parts) == 3 and parts[1] == "blob" and parts[2] == wanted:
                return MainCheck("not_yet", moved_to=name)
    return MainCheck("not_yet")


def compare_link(branch, title=""):
    """GitHub 비교 화면 주소(PR 을 만드는 화면) — 기준은 `main`, 머리는 가지. **글자로만 보여 주고 앱은 열지 않는다.** 소유자·저장소는 `EXPECTED_OWNER`·`EXPECTED_REPO` 상수에서 만든다(연결한 폴더의 origin 글자에서 읽지 않는다).
    제목은 모든 특수 문자를 퍼센트 부호로 바꿔(`quote(safe="")`) 120자로 줄이고(`&body=`·`#`·줄바꿈 주입 방지) 본문은 넣지 않으며(PR 본문은 공개된다) 전체가 1,500자를 넘으면 제목을 더 줄인다."""
    if not isinstance(branch, str) or BRANCH_NAME.fullmatch(branch) is None:
        raise AppError("PAGES_PUSH_REFUSED", detail="가지 이름이 정해진 모양이 아니다")
    head = f"https://github.com/{EXPECTED_OWNER}/{EXPECTED_REPO}/compare/{MAIN}...{branch}?quick_pull=1&title="
    text = " ".join(str(title or "").split())[:COMPARE_TITLE_CHARS]
    link = head + quote(text, safe="")
    while len(link) > COMPARE_MAX_CHARS and text:
        text = text[:max(len(text) - 10, 0)]
        link = head + quote(text, safe="")
    return link
