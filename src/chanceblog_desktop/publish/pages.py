"""연결한 chanceblog 저장소에 글 한 편을 쓰고 commit·push 한다(docs/ARCHITECTURE.md §3 '발행').

두 단계로 나눠 부른다 — 중간에 멈춰도 같은 글을 두 번 올리지 않고 이어서 올릴 수 있게:

  commit_post   글 검사(경로·머리말·제어 문자·키 모양 문자열) → 연결 확인·최신 받기 → 같은 글이 이미 있는지 → 파일 쓰기 → 그 파일만 commit.
                여기까지는 내 PC 안에서만 일어난다. 실패하면 우리가 쓴 파일·스테이징·만든 폴더를 치우고 아무것도 남기지 않는다(치우지 못한 것은 오류 세부에 적는다).
  push_commit   올리지 않은 커밋이 '그 글 하나뿐'인지 확인 → push. 막히면(봇이 먼저 올림) 최신을 받아 그 커밋만 옮기고 다시(최대 3번).
                올리기 직전마다 현재 브랜치가 main 인지·올릴 것이 아직 '그 글 하나'인지 다시 확인하고, 올린 뒤 원격 main 에 들어갔는지 확인한다.
                이미 올라가 있으면(올리다가 연결이 끊겼지만 사실은 성공했던 경우) 아무것도 하지 않고 성공으로 돌려준다 — 같은 글을 두 번 올리지 않는다.
  discard_commit  끝내 못 올린 글 커밋(같은 주소의 글이 먼저 올라가 있어 멈춤 등)을 되돌려 저장소를 처음 상태로 돌린다 — 안 그러면 올리지 않은 커밋이 남아 다른 글이 막힌다.

앱은 사용자의 다른 변경·커밋을 건드리지 않는다: 올리지 않은 다른 커밋이 있으면 PAGES_LOCAL_REPO_DIVERGED 로 멈추고, 강제 push(--force)를 하지 않으며,
브랜치를 바꾸지 않고, 사용자의 훅과 서명(gpg) 대화창을 쓰지 않는다(모든 git 호출이 훅·서명을 끈다 — gitrepo.run_git). 이 모듈의 push 는 실제로 chanceblog 의 main 에
올라가므로(T2) 독립 검증을 거치고, 시험은 진짜 git 으로 봇이 끼어드는 경우까지 만든다. 주소 확인(배포 뒤 글이 열리는지)은 deploy.py 다.
"""
from __future__ import annotations

import datetime
import errno
import os
import re
import stat
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..core import use_vendored_core
from ..errors import UNEXPECTED, AppError
from ..render.pages import front_matter_problems
from ..security.mask import _INVISIBLE, _strip_invisible, mask       # 비밀을 눈에 안 보이는 글자로 쪼갠 것도 찾으려고 같은 패키지의 정리 함수를 쓴다
from . import gitrepo
from .gitrepo import EXPECTED_ORIGIN, MAIN, inspect_repo, run_git, sync_latest

use_vendored_core()
from pipeline.secret_patterns import find_secrets  # noqa: E402  (vendor/ 경로를 먼저 올려야 한다)

# 글 파일의 경로: `_posts/<분야 폴더 하나>/YYYY-MM-DD-KR|EN-HHMMSS.md`(render.pages.post_path 가 만드는 모양). 폴더 안 이름에는 경로 구분자·Windows 금지 문자·제어 문자가 없고, 숫자는 ASCII 만이다
POST_PATH = re.compile(r'_posts/[^/\\:*?"<>|\x00-\x1f\x7f]+/(\d{4})-(\d{2})-(\d{2})-(?:KR|EN)-(\d{2})(\d{2})(\d{2})\.md', re.ASCII)
_BAD_TEXT = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\ufffe\uffff]")      # 탭·줄바꿈 말고는 제어 문자(CR 포함: 렌더는 LF 만 낸다. 줄바꿈 변환(autocrlf)이 있는 PC 에서 CR 이 든 글은 commit 뒤 내용이 달라져 영영 못 올린다)
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))})        # Windows 가 파일 이름으로 못 쓰는 이름
_HIDDEN = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp", "Zs"})                    # 폴더 이름에 넣지 않는 글자 범주(보통 공백 한 칸만 허용)
MAX_POST_BYTES = 500_000
MAX_PUSH_ATTEMPTS = 3
_COMMIT_PREFIX = "글 올리기(데스크톱 앱):"
_REMOTE_MAIN = f"refs/remotes/origin/{MAIN}"


@dataclass(frozen=True)
class CommitInfo:
    path: str
    commit: str       # 만든 커밋. push 때 최신 위로 옮겨지면 바뀌므로 push_commit 이 돌려주는 값을 쓴다
    base: str         # 그 커밋의 부모 = 쓰기 직전의 원격 main


@dataclass(frozen=True)
class PushInfo:
    commit: str       # 글을 담은 커밋(원격 main 에 들어가 있다)
    attempts: int     # push 시도 횟수(이미 올라가 있었으면 0)
    already: bool     # 이미 올라가 있어서 할 일이 없었다


def _bad(item, detail=""):
    return AppError("CONTENT_INVALID", {"항목": item}, detail=detail)


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
    secrets = find_secrets(_strip_invisible(text))
    if secrets:
        raise AppError("SECRET_IN_TEXT_BLOCKED", detail="키 모양 문자열: " + ", ".join(sorted({label for label, _ in secrets})))


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
    check_post(post)
    if find_secrets(_strip_invisible(str(title or ""))):
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


def _fetch_main(git, root):
    gitrepo._must(git, root, ["fetch", "--quiet", "origin", f"+refs/heads/{MAIN}:{_REMOTE_MAIN}"], "원격 main 받기")


def _counts(git, root, tip="HEAD"):
    ahead, behind = gitrepo._must(git, root, ["rev-list", "--left-right", "--count", f"{tip}...{_REMOTE_MAIN}"], "원격과 비교").split()
    return int(ahead), int(behind)


def _blob(git, root, spec):
    """`rev:경로` 의 파일 내용(없으면 None)."""
    result = git(root, ["cat-file", "blob", spec])
    return result.stdout if result.returncode == 0 else None


def _stem_clash(git, root, stem, own_path):
    """원격 main 의 `_posts` 아래에 같은 주소(날짜-언어-시각)의 다른 글이 있는가 — 분야 폴더·확장자가 달라도 Jekyll 주소는 같아 한 글이 가려진다."""
    listing = git(root, ["ls-tree", "-r", "--name-only", "-z", _REMOTE_MAIN, "--", "_posts"])
    if listing.returncode != 0:
        return False
    return any(name != own_path and name.rsplit("/", 1)[-1].startswith(stem + ".") for name in listing.stdout.split("\0") if name)


def _pending_state(git, root, post, tip="HEAD"):
    """tip(기본 HEAD)까지 올릴 것이 정확히 '이 글 하나'인지 확인한다. 'pending'(올릴 커밋이 맞다) 또는 'published'(이미 원격 main 에 같은 내용으로 있다). 그 밖에는 AppError."""
    ahead, _behind = _counts(git, root, tip)
    remote = _blob(git, root, f"{_REMOTE_MAIN}:{post.path}")
    if ahead == 0:
        if remote is None:
            raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail="올릴 글 커밋이 없고 원격 main 에도 그 글이 없다")
        if remote != post.text:
            raise AppError("DUPLICATE_SLUG", detail="원격 main 에 같은 이름의 다른 글이 있다")
        return "published"
    if ahead != 1:
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail=f"올리지 않은 커밋이 {ahead}개다(이 글 하나여야 한다)")
    changes = gitrepo._must(git, root, ["diff-tree", "-z", "--no-commit-id", "--name-status", "-r", tip], "올릴 커밋 확인").split("\0")
    if [item for item in changes if item] != ["A", post.path] or _blob(git, root, f"{tip}:{post.path}") != post.text:
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail="올리지 않은 커밋이 이 글이 아니다")
    if remote is not None:
        raise AppError("DUPLICATE_SLUG", detail="원격 main 에 같은 이름의 글이 이미 있다")
    if _stem_clash(git, root, Path(post.path).stem, post.path):
        raise AppError("DUPLICATE_SLUG", detail="원격 main 에 같은 주소(날짜-언어-시각)의 다른 글이 이미 있다")
    return "pending"


def _require_main(git, root):
    """검사 뒤 사용자가 다른 브랜치로 바꿨을 수 있다 — rebase 는 지금 HEAD 에 하므로 main 일 때만 한다."""
    branch = gitrepo._current_branch(git, root)
    if branch != MAIN:
        raise AppError("PAGES_LOCAL_REPO_NOT_MAIN", {"브랜치": branch})


def _rebase(git, root):
    """우리 커밋(글 하나)을 최신 원격 main 위로 옮긴다. 충돌(같은 이름의 글을 봇이 먼저 올림)이면 되돌리고 DUPLICATE_SLUG."""
    _require_main(git, root)                          # rebase 는 지금 HEAD 에 하므로 바로 직전에 main 인지 본다(사용자의 다른 브랜치를 옮기지 않게)
    try:
        result = git(root, ["rebase", "--quiet", _REMOTE_MAIN])
    except BaseException:                             # 시간 초과·중단: 진행 중인 rebase 를 남기지 않는다(저장소가 분리된 HEAD 로 남으면 이후 모든 일이 막힌다)
        gitrepo._clear_stale_index_lock(git, root)
        try:
            git(root, ["rebase", "--abort"])
        except Exception:
            pass
        raise
    if result.returncode == 0:
        return
    git(root, ["rebase", "--abort"])                  # 진행 중인 rebase 를 남기지 않는다(없어서 실패해도 괜찮다)
    raw = result.stderr + result.stdout
    text = raw.lower()
    if "conflict" in text or "could not apply" in text:
        raise AppError("DUPLICATE_SLUG", detail=mask(raw.strip())[-400:])            # 소문자로 바꾼 글이 아니라 원문을 가린다(키 모양은 대소문자를 구분한다)
    raise gitrepo._failure(result, "최신 위로 옮기기", root)


def push_commit(repo_path, post, *, git=run_git, expected_origin=EXPECTED_ORIGIN, attempts=MAX_PUSH_ATTEMPTS):
    """commit_post 가 만든 커밋을 원격 main 에 올린다. 올리지 않은 것이 '이 글 하나'가 아니면 올리지 않고 PAGES_LOCAL_REPO_DIVERGED.
    봇이 먼저 올려 막히면 최신을 받아 그 커밋만 옮기고 다시 올린다(최대 attempts 번). 이미 올라가 있으면 할 일 없이 성공."""
    check_post(post)
    info = inspect_repo(repo_path, git, expected_origin)
    root = info.path
    _fetch_main(git, root)
    if _pending_state(git, root, post) == "published":
        return PushInfo(gitrepo._must(git, root, ["rev-parse", _REMOTE_MAIN], "원격 main 확인"), 0, True)
    used = 0
    while True:
        _require_main(git, root)
        if _counts(git, root)[1]:
            _rebase(git, root)
        tip = gitrepo._must(git, root, ["rev-parse", f"refs/heads/{MAIN}"], "올릴 커밋 확인")       # 올릴 것은 검사한 바로 이 커밋이다 — 브랜치 이름이 아니라 이 번호로 올려, 그 뒤에 사용자가 main 에 커밋을 더해도 같이 올라가지 않는다
        if _pending_state(git, root, post, tip) == "published":        # 올리기 직전에(첫 시도도) 올릴 것이 지금도 '이 글 하나'인지·같은 주소가 원격에 없는지 다시 확인한다
            return PushInfo(gitrepo._must(git, root, ["rev-parse", _REMOTE_MAIN], "원격 main 확인"), used, True)
        used += 1
        result = git(root, ["push", "--porcelain", "--no-verify", "origin", f"{tip}:refs/heads/{MAIN}"])
        if result.returncode == 0:
            break
        error = gitrepo._failure(result, "글 올리기", root)
        if error.code != "GIT_PUSH_REJECTED" or used >= attempts:
            raise error
        _fetch_main(git, root)
        if _pending_state(git, root, post) == "published":        # 봇이 끼어드는 사이 사정이 달라졌을 수 있다 — 올릴 것이 아직 '이 글 하나'인지·같은 주소가 원격에 생기지 않았는지 다시 확인한다
            return PushInfo(gitrepo._must(git, root, ["rev-parse", _REMOTE_MAIN], "원격 main 확인"), used, True)
    _fetch_main(git, root)
    if git(root, ["merge-base", "--is-ancestor", tip, _REMOTE_MAIN]).returncode != 0:
        raise AppError(UNEXPECTED, detail="올렸는데 원격 main 에 그 커밋이 없다")
    return PushInfo(tip, used, False)


def discard_commit(repo_path, info, *, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """끝내 올리지 못한 글 커밋(commit_post 가 돌려준 info)을 되돌린다: 커밋과 글 파일을 치워 저장소를 처음 상태로 돌린다 — 다른 변경은 건드리지 않는다.
    HEAD 가 info.commit 이고 그 부모가 info.base 이며 글 파일 하나만 더한 커밋(제목도 앱이 만든 것)일 때만 하고, 먼저 원격 main 을 받아 이미 올라간 커밋이면 거절한다
    (받지 못하면 낡은 기록으로 판단하지 않고 거절한다). 올리다 최신 위로 옮겨진 뒤에는 info.commit 이 낡아 거절된다 — 그때는 사람이 확인한다."""
    if not isinstance(info.path, str) or not POST_PATH.fullmatch(info.path):         # info 를 그대로 믿지 않는다: 글 경로 모양이 아니면 다른 파일을 지울 수 있다
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail="되돌릴 글 경로가 올바르지 않다")
    repo = inspect_repo(repo_path, git, expected_origin)
    root = repo.path
    _fetch_main(git, root)
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


def publish_post(repo_path, post, *, title="", git=run_git, expected_origin=EXPECTED_ORIGIN):
    """commit_post 와 push_commit 을 이어서. 중간에 실패하면 CommitInfo 를 가진 채 이어 올릴 수 있도록 두 단계를 따로 부르는 쪽이 낫다."""
    commit_post(repo_path, post, title=title, git=git, expected_origin=expected_origin)
    return push_commit(repo_path, post, git=git, expected_origin=expected_origin)
