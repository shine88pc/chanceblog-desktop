"""연결한 `chanceblog` 로컬 저장소를 확인하고, 최신으로 맞추고, 올릴 수 있는지 점검한다(docs/ARCHITECTURE.md §3).

모든 실패는 AppError(오류 코드)로 모인다. 이 모듈은 확인·최신 받기·올리기 점검까지만 한다 — 글을 쓰고 commit·push 하는 일은
발행 묶음에서 한다. 앱은 사용자의 다른 변경을 지우거나 되돌리지 않고, 브랜치를 바꾸지 않는다. git 이 대화창을 띄우거나
영어가 아닌 메시지를 내서 규칙이 어긋나지 않게 `run_git` 이 환경을 고정한다. 시험에서는 `git` 인자로 바꿔 끼운다.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import UNEXPECTED, AppError

MAIN = "main"
DEFAULT_TIMEOUT = 90   # 초. 넘으면 NETWORK_TIMEOUT
EXPECTED_ORIGIN = re.compile(
    r"^(?:https://(?:[^/@]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)shine88pc/chanceblog(?:\.git)?/?$",
    re.IGNORECASE,
)
_USERINFO = re.compile(r"(?<=//)[^/@\s]+@")
_DETAIL_CHARS = 400

# git 의 오류 출력(영어로 고정) → 오류 코드. 위에서부터 처음 맞는 것. 인증 거절의 'unable to access … 403' 이 네트워크로 잘못 가지 않게 인증을 먼저 본다.
_RULES = (
    ("GIT_PUSH_REJECTED", ("[rejected]", "non-fast-forward", "fetch first", "failed to push some refs")),
    ("GIT_PUSH_AUTH", (
        "could not read username", "could not read password", "authentication failed", "invalid username or password",
        "permission denied", "terminal prompts disabled", "returned error: 401", "returned error: 403",
        "repository not found", "could not read from remote repository", "access denied",
    )),
    ("GIT_PUSH_NETWORK", (
        "could not resolve host", "failed to connect", "connection timed out", "operation timed out", "network is unreachable",
        "connection reset", "connection refused", "ssl certificate", "ssl connect", "schannel", "early eof",
        "remote end hung up unexpectedly", "temporary failure in name resolution", "unable to access",
    )),
)


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class RepoInfo:
    path: Path
    origin: str      # 자격 정보를 가린 주소
    branch: str
    head: str


def run_git(cwd, args, timeout=DEFAULT_TIMEOUT):
    """git 을 cwd 에서 실행한다. 대화창이 뜨지 않게(GIT_TERMINAL_PROMPT=0·GCM_INTERACTIVE=false) 하고 메시지를 영어로 받는다."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="false", LC_ALL="C", LANGUAGE="C", GIT_OPTIONAL_LOCKS="0")
    try:
        done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, timeout=timeout, env=env)
    except FileNotFoundError:
        raise AppError("GIT_NOT_INSTALLED") from None
    except subprocess.TimeoutExpired:
        raise AppError("NETWORK_TIMEOUT", detail=f"git {args[0]} 가 {timeout}초 안에 끝나지 않았다") from None
    return GitResult(done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace"))


def hide_credentials(text):
    """주소 속 `사용자:토큰@` 부분을 가린다(로그·화면에 자격 정보가 나가지 않게)."""
    return _USERINFO.sub("***@", text)


def classify_git_failure(output):
    """git 오류 출력 → 오류 코드(규칙 기반). 어느 규칙에도 안 맞으면 UNEXPECTED_ERROR."""
    text = output.lower()
    for code, needles in _RULES:
        if any(needle in text for needle in needles):
            return code
    return UNEXPECTED


def _failure(result, what):
    output = (result.stderr + "\n" + result.stdout).strip()
    detail = f"{what}: {hide_credentials(output)[-_DETAIL_CHARS:]}"
    return AppError(classify_git_failure(output), detail=detail)


def _must(git, root, args, what):
    result = git(root, args)
    if result.returncode != 0:
        raise _failure(result, what)
    return result.stdout.strip()


def inspect_repo(path, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """폴더가 연결할 수 있는 chanceblog 저장소인지 본다(아무것도 바꾸지 않는다).

    순서: 저장소 폴더인가·origin 이 chanceblog 인가(PAGES_LOCAL_REPO_INVALID) → main 인가(PAGES_LOCAL_REPO_NOT_MAIN) →
    저장하지 않은 변경이 없는가(PAGES_LOCAL_REPO_DIRTY). 추적 중인 파일의 변경·스테이징만 '변경'으로 본다(새 파일은 무시).
    """
    root = Path(path)
    if not root.is_dir():
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="폴더가 없다")
    top = git(root, ["rev-parse", "--show-toplevel"])
    if top.returncode != 0 or not top.stdout.strip() or not os.path.samefile(top.stdout.strip(), root):
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="git 저장소의 맨 위 폴더가 아니다")
    origin = git(root, ["remote", "get-url", "origin"])
    url = origin.stdout.strip()
    if origin.returncode != 0 or not expected_origin.match(url):
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail=f"origin 이 chanceblog 가 아니다: {hide_credentials(url)[:200] or '(없음)'}")
    branch = _must(git, root, ["rev-parse", "--abbrev-ref", "HEAD"], "현재 브랜치 확인")
    if branch != MAIN:
        raise AppError("PAGES_LOCAL_REPO_NOT_MAIN", {"브랜치": branch})
    if _must(git, root, ["status", "--porcelain", "--untracked-files=no"], "변경 확인"):
        raise AppError("PAGES_LOCAL_REPO_DIRTY")
    return RepoInfo(root, hide_credentials(url), branch, _must(git, root, ["rev-parse", "HEAD"], "HEAD 확인"))


def sync_latest(path, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """연결을 확인한 뒤 원격 main 을 받아 빨리감기로 맞춘다. 로컬 main 이 앞서거나 갈라져 있으면 건드리지 않고 PAGES_LOCAL_REPO_DIVERGED."""
    info = inspect_repo(path, git, expected_origin)
    _must(git, info.path, ["fetch", "--quiet", "origin", MAIN], "원격 main 받기")
    counts = _must(git, info.path, ["rev-list", "--left-right", "--count", f"HEAD...origin/{MAIN}"], "원격과 비교").split()
    ahead, behind = int(counts[0]), int(counts[1])
    if ahead:
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail=f"로컬 main 이 원격보다 {ahead}개 앞선다(갈라짐 {'있음' if behind else '없음'})")
    if behind:
        merged = git(info.path, ["merge", "--ff-only", "--quiet", f"origin/{MAIN}"])
        if merged.returncode != 0:
            raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail=hide_credentials(merged.stderr.strip())[-_DETAIL_CHARS:])
    return RepoInfo(info.path, info.origin, info.branch, _must(git, info.path, ["rev-parse", "HEAD"], "HEAD 확인"))


def check_push_access(path, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """실제로 올리지 않고 push 가 되는지만 본다(`git push --dry-run`). 인증·네트워크·거절은 각각의 오류 코드로."""
    info = inspect_repo(path, git, expected_origin)
    _must(git, info.path, ["push", "--dry-run", "--porcelain", "origin", f"HEAD:refs/heads/{MAIN}"], "올리기 점검")
    return info
