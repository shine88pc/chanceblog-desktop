"""연결한 `chanceblog` 로컬 저장소를 확인하고, 최신으로 맞추고, 올릴 수 있는지 점검한다(docs/ARCHITECTURE.md §3).

모든 실패는 AppError(오류 코드)로 모인다. 이 모듈은 확인·최신 받기·올리기 점검까지만 한다 — 글을 쓰고 commit·push 하는 일은
발행 묶음에서 한다. 앱은 사용자의 다른 변경을 지우거나 되돌리지 않고, 브랜치를 바꾸지 않는다. git 이 대화창을 띄우거나
영어가 아닌 메시지를 내서 규칙이 어긋나지 않게 `run_git` 이 환경을 고정한다(사용자의 ssh·자격 증명 설정은 건드리지 않는다).
시험에서는 `git` 인자로 바꿔 끼운다.
"""
from __future__ import annotations

import contextlib
import errno
import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ..errors import UNEXPECTED, AppError
from ..security.mask import mask

MAIN = "main"
DEFAULT_TIMEOUT = 90   # 초. 넘으면 git 과 그 손자 프로세스까지 끄고 NETWORK_TIMEOUT
_REMOTE_MAIN = f"refs/remotes/origin/{MAIN}"
# 사용자의 다른 저장소·대화창 설정이 이 앱의 확인을 엉뚱한 곳으로 돌리거나 멈추지 않게 지우는 환경 변수
_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
             "GIT_ASKPASS", "SSH_ASKPASS")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NETWORK_COMMANDS = frozenset({"fetch", "push", "ls-remote", "pull", "clone"})
_SSH_DEFAULT = "ssh -o BatchMode=yes"          # 질문 대신 실패하는 ssh(입력을 기다리며 멈추지 않게) — 사용자가 ssh 명령을 따로 정하지 않았을 때만 쓴다
_LOCK_MAX_AGE = DEFAULT_TIMEOUT + 120          # 방금 끈 git 이 남긴 index.lock 으로 볼 최대 나이(초) — 이보다 오래된 잠금은 다른 프로그램의 것일 수 있어 건드리지 않는다
# re.ASCII: 터키어 ı·긴 s(ſ) 같은 글자가 i·s 와 같게 읽혀 가짜 호스트가 통과하지 않게
EXPECTED_ORIGIN = re.compile(
    r"^(?:https://(?:[^/\s]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)shine88pc/chanceblog(?:\.git)?/?$",
    re.IGNORECASE | re.ASCII,
)
_DETAIL_CHARS = 400
_DETAIL_TAIL = 8000                 # 가리기 전에 끝부분만 남겨 아주 큰 출력을 통째로 가리느라 오래 걸리지 않게
_MAX_STDOUT = 64 * 1024 * 1024      # 이보다 큰 표준 출력은 잘라 쓰면 판단이 틀리므로 오류로 본다
_STDERR_TAIL = 64 * 1024

# git 의 오류 출력(영어로 고정) → 오류 코드. 위에서부터 처음 맞는 것이다. 순서가 뜻이다:
# 커밋 작성자 없음 → 서버가 규칙으로 막음(보호된 브랜치·훅 — 'failed to push some refs' 가 같이 나오므로 거절보다 먼저) → 거절(봇이 먼저 올림) →
# 내 폴더에 파일을 못 씀(다른 프로그램이 쓰는 중 → 그 밖) → SSH 연결 실패·끊김(문구에 '원격 저장소를 읽을 수 없음'이 같이 나오므로 인증보다 먼저)
# → 인증 → 그 밖의 네트워크.
_RULES = (
    ("GIT_IDENTITY_MISSING", ("author identity unknown", "please tell me who you are", "unable to auto-detect email address", "empty ident name")),
    ("GIT_PUSH_AUTH", ("protected branch", "repository rule violations", "hook declined", "refusing to allow", "push declined", "email privacy")),         # GH006(보호된 브랜치)·GH013(규칙 위반)·GH007(이메일 공개 제한) 문구에 이 낱말들이 들어 있다
    ("GIT_PUSH_REJECTED", ("[rejected]", "non-fast-forward", "fetch first", "failed to push some refs")),
    ("DISK_FULL", ("no space left on device",)),
    ("FILE_PATH_TOO_LONG", ("filename too long",)),                  # 'unable to unlink …: Filename too long' 은 다른 프로그램이 쓰는 중이 아니라 경로가 긴 것이다 — FILE_IN_USE 보다 먼저
    ("FILE_IN_USE", ("unable to unlink", "being used by another process", "text file busy", "device or resource busy")),
    ("FILE_WRITE_FAILED", ("unable to create", "unable to write", "cannot lock ref", "index.lock", "cannot open '")),
    ("GIT_PUSH_NETWORK", (
        "ssh: connect to host", "ssh: could not resolve hostname", "kex_exchange_identification", "ssh_exchange_identification",
        "ssh_dispatch_run_fatal", "connection closed by", "closed by remote host", "client_loop", "connection reset by", "software caused connection abort", "broken pipe",
    )),
    ("GIT_PUSH_AUTH", (
        "could not read username", "could not read password", "authentication failed", "invalid username or password",
        "permission denied (publickey", "permission denied (password", "permission denied (keyboard-interactive", "denied to ",
        "terminal prompts disabled", "returned error: 401", "returned error: 403", "repository not found",
        "could not read from remote repository", "access denied",
    )),
    ("GIT_PUSH_NETWORK", (
        "could not resolve host", "failed to connect", "connection timed out", "operation timed out", "network is unreachable",
        "connection reset", "connection refused", "ssl certificate", "ssl connect", "schannel", "early eof",
        "remote end hung up unexpectedly", "temporary failure in name resolution", "unable to access",
    )),
)
_SLOT_PATH_CODES = ("FILE_WRITE_FAILED", "FILE_IN_USE")


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


def _git_env():
    """대화창이 뜨지 않게(GIT_TERMINAL_PROMPT=0·GCM_INTERACTIVE=false) 하고 메시지를 영어로 받는다. 다른 저장소를 가리키는 환경 변수와 대화창 도우미는 지운다.
    사용자의 ssh 설정(core.sshCommand·GIT_SSH·GIT_SSH_COMMAND)은 건드리지 않는다 — 대화창은 입력 장치(stdin)를 막아 두는 것으로 피한다.
    경로 인자는 글자 그대로 읽는다(GIT_LITERAL_PATHSPECS) — `[x].md` 같은 이름이 다른 파일까지 가리키는 글롭 무늬로 읽히지 않게."""
    env = {key: value for key, value in os.environ.items() if key not in _ENV_DROP}
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="false", LC_ALL="C", LANGUAGE="C", GIT_OPTIONAL_LOCKS="0", GIT_LITERAL_PATHSPECS="1",
               GIT_EDITOR="true", GIT_MERGE_AUTOEDIT="no")          # 편집기 창이 뜨지 않게(커밋·병합·rebase 가 메시지를 묻지 않는다)
    return env


def _kill_tree(process):
    """시간 초과 때 git 과 그 손자 프로세스(git-remote-https·ssh)까지 끈다 — 손자가 남아 계속 연결을 붙잡지 않게."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15, creationflags=_NO_WINDOW)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass


def _read_tail(handle, limit):
    """임시 파일의 끝 limit 바이트와 '더 있었는지'."""
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(max(0, size - limit))
    return handle.read(), size > limit


def _spawn_error(error):
    detail = f"{type(error).__name__}: {mask(error.strerror or str(error))}"[:200]
    if getattr(error, "winerror", None) == 206 or error.errno == errno.E2BIG:         # 명령줄이 너무 긺 — git 이 없는 것이 아니다
        return AppError(UNEXPECTED, detail="명령줄이 너무 길다 — " + detail)
    return AppError("GIT_NOT_INSTALLED", detail=detail)                                # git 이 없음·실행 권한 없음·실행할 수 없는 파일(WinError 193)


def run_command(command, *, env=None, timeout=DEFAULT_TIMEOUT, label="명령", input_bytes=None):
    """명령을 돌려 GitResult 로 돌려준다. 시간이 넘으면 프로세스 트리를 끄고 NETWORK_TIMEOUT, 실행할 수 없으면 GIT_NOT_INSTALLED.

    출력은 파이프가 아니라 임시 파일로 받는다 — 명령이 끝났는데 손자 프로세스(ssh 연결 유지 등)가 파이프를 쥐고 있어도 끝을 기다리며 매달리지 않는다.
    입력 장치는 막아 두고(대화창 입력을 기다리며 멈추지 않게, 창 없는 앱에서 입력 핸들이 없어 시작이 실패하지 않게), 꼭 넘겨야 하는 입력(`input_bytes`)은 임시 파일로 준다.
    임시 파일을 못 만들면(임시 폴더가 없거나 가득 참) FILE_WRITE_FAILED.
    """
    options = {"creationflags": _NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with contextlib.ExitStack() as stack:
        try:
            out_file = stack.enter_context(tempfile.TemporaryFile())
            err_file = stack.enter_context(tempfile.TemporaryFile())
            stdin = subprocess.DEVNULL
            if input_bytes is not None:
                stdin = stack.enter_context(tempfile.TemporaryFile())
                stdin.write(input_bytes)
                stdin.flush()
                stdin.seek(0)
        except OSError as error:
            raise AppError("FILE_WRITE_FAILED", {"경로": tempfile.gettempdir()}, detail=f"임시 파일을 만들 수 없다: {type(error).__name__}: {mask(error.strerror or str(error))}"[:200]) from None
        try:
            process = subprocess.Popen(command, stdin=stdin, stdout=out_file, stderr=err_file, env=env, **options)
        except OSError as error:
            raise _spawn_error(error) from None
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(process)
            try:
                process.wait(timeout=5)
            except Exception:
                pass                                 # 끄지 못해도 더는 기다리지 않는다
            raise AppError("NETWORK_TIMEOUT", detail=f"{label} 가 {timeout}초 안에 끝나지 않았다") from None
        except BaseException:
            _kill_tree(process)
            raise
        out, out_cut = _read_tail(out_file, _MAX_STDOUT)
        err, _ = _read_tail(err_file, _STDERR_TAIL)
    if out_cut:
        raise AppError(UNEXPECTED, detail=f"{label} 의 출력이 너무 크다")
    return GitResult(process.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


def _with_ssh_default(cwd, env):
    """받기·올리기에서 ssh 가 질문(처음 보는 서버 확인·암호)을 입력 없이 기다리며 멈추지 않도록, 사용자가 ssh 명령을 따로 정하지 않았을 때만 BatchMode 를 준다.
    사용자의 `core.sshCommand`·`GIT_SSH`·`GIT_SSH_COMMAND` 는 덮어쓰지 않는다(PuTTY·에이전트 같은 설정이 깨지지 않게)."""
    if "GIT_SSH" in env or "GIT_SSH_COMMAND" in env:
        return env
    configured = run_command(["git", "-C", str(cwd), "config", "--get", "core.sshCommand"], env=env, timeout=30, label="git config")
    if configured.returncode == 0 and configured.stdout.strip():
        return env
    return {**env, "GIT_SSH_COMMAND": _SSH_DEFAULT}


def run_git(cwd, args, timeout=DEFAULT_TIMEOUT, input_bytes=None):
    """git 을 cwd 에서 실행한다(사용자의 훅·대화창·다른 저장소 설정에 휘둘리지 않게 환경을 고정한다)."""
    # gc.auto·maintenance.auto: 받기 뒤 git 이 정리(gc)를 시작해 제한 시간 안에 끝나지 않거나 남는 일을 막는다(정리는 사용자가 쓰는 git 이 한다)
    # user.useConfigOnly: 이름·이메일이 설정에 없으면 호스트 이름으로 짐작한 주소를 공개 commit 에 넣지 않고 GIT_IDENTITY_MISSING 으로 멈춘다.
    # core.hooksPath·commit.gpgsign·push.gpgSign: 사용자의 훅(post-merge·reference-transaction·pre-rebase·prepare-commit-msg …)과 서명(gpg 대화창)이 이 앱의 git 호출에 끼어들지 않게 —
    # 훅이 늦거나 실패하면 받기·올리기가 막히거나 멈추고(시간 초과), 서명 설정은 rebase 를 실패시킨다(독립 검증이 훅 9종이 도는 것을 확인했다). 앱은 어떤 훅도 필요로 하지 않는다
    command = ["git", "-C", str(cwd), "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=30", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
               "-c", f"core.hooksPath={os.devnull}", "-c", "commit.gpgsign=false", "-c", "push.gpgSign=false", "-c", "user.useConfigOnly=true",
               "-c", "i18n.commitEncoding=UTF-8", "-c", "i18n.logOutputEncoding=UTF-8", *args]            # 레거시 인코딩(cp949) 설정이 있어도 commit 기록과 git log 출력이 UTF-8 이다
    env = _git_env()
    if args and args[0] in _NETWORK_COMMANDS:
        env = _with_ssh_default(cwd, env)
    return run_command(command, env=env, timeout=timeout, label=f"git {args[0]}", input_bytes=input_bytes)


def hide_credentials(text):
    """주소 속 `사용자:토큰@` 부분과 키·토큰 모양을 가린다(로그·화면에 자격 정보가 나가지 않게 — security.mask 와 같은 규칙)."""
    return mask(text)


def classify_git_failure(output):
    """git 오류 출력 → 오류 코드(규칙 기반). 어느 규칙에도 안 맞으면 UNEXPECTED_ERROR. `warning:` 으로 시작하는 줄은 실패의 이유가 아니라 곁다리 알림이라 보지 않는다."""
    text = "\n".join(line for line in output.lower().splitlines() if not line.lstrip().startswith("warning:"))
    for code, needles in _RULES:
        if any(needle in text for needle in needles):
            return code
    return UNEXPECTED


def _failure(result, what, root=None):
    output = (result.stderr + "\n" + result.stdout).strip()
    detail = f"{what}: {mask(output[-_DETAIL_TAIL:])[-_DETAIL_CHARS:]}"       # 끝부분만 남겨(아주 큰 출력을 통째로 가리지 않게) 로그인 정보·키 모양을 가린 뒤 다시 끝부분만(원인은 보통 끝에 있다)
    code = classify_git_failure(output)
    slots = {"경로": str(root)} if code in _SLOT_PATH_CODES and root is not None else None
    return AppError(code, slots, detail=detail)


def _must(git, root, args, what):
    result = git(root, args)
    if result.returncode != 0:
        raise _failure(result, what, root)
    return result.stdout.strip()


def _names_detail(label, names):
    shown = ", ".join(mask(name)[:80] for name in names[:5]) + (f" 외 {len(names) - 5}개" if len(names) > 5 else "")
    return f"{label} {len(names)}개: {shown}"


def _changed_files(git, root):
    """저장하지 않은 변경이 있는 추적 파일의 이름(새 파일은 세지 않는다). 출력이 이름 목록으로 읽히지 않아도 비어 있지 않으면 '있다' 로 본다."""
    result = git(root, ["status", "--porcelain", "-z", "--untracked-files=no"])
    if result.returncode != 0:
        raise _failure(result, "변경 확인", root)
    names, skip = [], False
    for token in result.stdout.split("\0"):
        if skip:
            skip = False
            continue
        if len(token) > 3 and token[2] == " ":
            names.append(token[3:].strip())
            skip = token[0] in "RC" or token[1] in "RC"               # 이름을 바꾼 항목은 옛 이름이 뒤따른다
    if not names and result.stdout.strip():
        names = [result.stdout.strip()[:80]]
    return names


def _note_left(error, left):
    """되돌리고 난 뒤에도 병합 전과 다른 파일의 이름을 오류의 세부에 덧붙인다 — 사용자가 어느 파일을 봐야 하는지 알 수 있게(어떤 파일도 몰래 두지 않는다)."""
    if left:
        note = _names_detail("받다가 멈춘 뒤에도 병합 전과 다른 파일", left)
        error.detail = f"{error.detail} | {note}" if error.detail else note
    return error


def _merge_finished(git, root, head_before):
    """병합이 사실은 끝났는가: HEAD 가 병합 전과 달라졌고 원격 main 과 같다(시간 초과가 파일 쓰기가 아니라 훅·백신 같은 뒷정리 때문에 난 경우)."""
    try:
        now = git(root, ["rev-parse", "HEAD"])
        remote = git(root, ["rev-parse", _REMOTE_MAIN])
    except Exception:
        return False
    return now.returncode == 0 and remote.returncode == 0 and now.stdout.strip() == remote.stdout.strip() != head_before


def _remote_urls(git, root):
    """origin 의 받는 주소와 올리는 주소를 모두(pushurl·insteadOf·여러 주소 포함). origin 이 없으면 빈 목록."""
    urls = []
    for extra in ([], ["--push"]):
        result = git(root, ["remote", "get-url", *extra, "--all", "origin"])
        if result.returncode != 0:
            return []
        urls += [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return urls


def _current_branch(git, root):
    """현재 브랜치 이름. HEAD 가 분리돼 있으면 '(분리된 HEAD)'. 태그와 이름이 같아도 헷갈리지 않게 전체 ref 로 읽는다."""
    result = git(root, ["symbolic-ref", "-q", "HEAD"])
    ref = result.stdout.strip()
    if result.returncode == 0 and ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    if result.returncode == 1:
        return "(분리된 HEAD)"
    raise _failure(result, "현재 브랜치 확인", root)


def inspect_repo(path, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """폴더가 연결할 수 있는 chanceblog 저장소인지 본다(아무것도 바꾸지 않는다).

    순서: 저장소 폴더인가·origin(받는 주소와 올리는 주소 모두)이 chanceblog 인가(PAGES_LOCAL_REPO_INVALID) → main 인가(PAGES_LOCAL_REPO_NOT_MAIN) →
    저장하지 않은 변경이 없는가(PAGES_LOCAL_REPO_DIRTY). 추적 중인 파일의 변경·스테이징만 '변경'으로 본다(새 파일은 무시).
    """
    if path is None or not str(path).strip():
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="폴더가 지정되지 않았다")
    root = Path(path)
    if not root.is_dir():
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="폴더가 없다")
    top = git(root, ["rev-parse", "--show-toplevel"])
    toplevel = top.stdout.strip()
    try:
        same = top.returncode == 0 and bool(toplevel) and os.path.samefile(toplevel, root)
    except OSError:
        same = False
    if not same:
        why = f": {mask(top.stderr.strip())[-_DETAIL_CHARS:]}" if top.returncode != 0 and top.stderr.strip() else ""     # 예: 'detected dubious ownership'
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="git 저장소의 맨 위 폴더가 아니다" + why)
    urls = _remote_urls(git, root)
    wrong = [url for url in urls if not expected_origin.match(url)]
    if not urls or wrong:
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail=f"origin 이 chanceblog 가 아니다: {mask((wrong or ['(없음)'])[0])[:200]}")
    branch = _current_branch(git, root)
    if branch != MAIN:
        raise AppError("PAGES_LOCAL_REPO_NOT_MAIN", {"브랜치": branch})
    changed = _changed_files(git, root)
    if changed:
        raise AppError("PAGES_LOCAL_REPO_DIRTY", detail=_names_detail("바뀐 파일", changed))
    return RepoInfo(root, mask(urls[0]), branch, _must(git, root, ["rev-parse", "HEAD"], "HEAD 확인"))


@dataclass(frozen=True)
class Change:
    """원격 main 을 받으면 생기는 파일 하나의 변화(이름 바꾸기는 지움 + 새 파일로 본다)."""
    status: str      # A 새 파일 · D 지워짐 · M 내용이 바뀜 · T 종류가 바뀜
    path: str
    old_mode: str
    new_mode: str
    old: str         # HEAD 쪽 내용 번호(blob)
    new: str         # 원격 main 쪽 내용 번호


def _parse_raw(text):
    """`git diff --raw -z --no-abbrev --no-renames` 의 출력 → Change 목록."""
    tokens, changes, index = text.split("\0"), [], 0
    while index < len(tokens) - 1:
        if not tokens[index].startswith(":"):
            index += 1
            continue
        fields = tokens[index][1:].split(" ")
        path = tokens[index + 1]
        if len(fields) >= 5 and path:
            changes.append(Change(fields[4], path, fields[0], fields[1], fields[2], fields[3]))
        index += 2
    return changes


def _incoming_changes(git, root):
    """원격 main 을 받으면 바뀌거나 생기거나 지워질 파일들(이름 바꾸기는 지움 + 새 파일로)."""
    changed = git(root, ["diff", "--raw", "-z", "--no-abbrev", "--no-renames", "HEAD", _REMOTE_MAIN])
    if changed.returncode != 0:
        raise _failure(changed, "받을 파일 확인", root)
    return _parse_raw(changed.stdout)


def _my_files_among(git, root, names):
    """names 중 내 폴더에 이미 있는데 git 이 추적하지 않는 파일(새 파일·.gitignore 로 무시한 파일). git 자신의 목록과 맞춰 본다 —
    대소문자를 구분하지 않는 파일 시스템에서 이름만 바뀐 추적 파일을 내 파일로 잘못 보지 않는다."""
    if not names:
        return []
    listing = git(root, ["ls-files", "-z", "--others"])          # --others 는 .gitignore 한 파일까지 보여 준다(--exclude-standard 를 주지 않는다)
    if listing.returncode != 0:
        raise _failure(listing, "내 파일 확인", root)
    mine = set(listing.stdout.split("\0"))
    return [name for name in names if name in mine]


def _in_the_way(names, detail=""):
    shown = ", ".join(names[:5]) + (f" 외 {len(names) - 5}개" if len(names) > 5 else "")
    return AppError("PAGES_LOCAL_FILE_IN_THE_WAY", {"파일": shown or "(git 이 알려 준 파일)"}, detail=detail or f"받을 파일과 겹치는 내 파일 {len(names)}개: {mask(shown)}")


def _names_in(message):
    """git 이 '다음 파일이 덮어써진다' 며 줄머리에 탭을 붙여 늘어놓은 파일 이름들."""
    return [line.strip() for line in message.splitlines() if line.startswith("\t") and line.strip()]


_DRIVE = re.compile(r"^[A-Za-z]:")


def _safe_name(name):
    """원격이 정한 파일 이름이 저장소 안의 평범한 경로인가. 되돌릴 때 이 이름으로 파일을 지우거나 쓰므로, 위로 올라가는 `..`·절대 경로(맨 앞 `/` — 빈 조각이 된다)·드라이브·역슬래시·줄바꿈·읽을 수 없는 글자·`.git` 이
    든 이름은 건드리지 않는다(원격이 임의의 이름을 내세워 저장소 밖 파일을 지우게 할 수 없다)."""
    if "\ufffd" in name or any(ch in name for ch in ("\\", "\0", "\n", "\r")) or _DRIVE.match(name):
        return False
    return not any(part in ("", ".", "..") or part.lower() == ".git" for part in name.split("/"))


def _inside(root, name):
    """그 이름이 가리키는 곳이 저장소 폴더 안인가(중간 폴더가 링크로 바깥을 가리키지 않는가). 파일 자신이 링크여도 링크 이름만 다루므로 부모 폴더까지만 따라간다."""
    base = os.path.realpath(root)
    parent = os.path.realpath(os.path.join(base, *name.split("/")[:-1]))
    return parent == base or parent.startswith(base + os.sep)


def _plain_file(root, name):
    target = Path(root) / name
    return target.is_file() and not target.is_symlink()


def _git_in_chunks(git, root, prefix, names):
    """이름들을 100개씩 나눠(명령줄이 너무 길어지지 않게) 명령을 돌린다. 덩어리가 실패하면 파일 하나 때문일 수 있어 이름을 하나씩 다시 해 본다."""
    for start in range(0, len(names), 100):
        chunk = names[start:start + 100]
        if git(root, [*prefix, "--", *chunk]).returncode != 0 and len(chunk) > 1:
            for name in chunk:
                git(root, [*prefix, "--", name])


def _hash_chunk(git, root, chunk):
    done = git(root, ["hash-object", "--stdin-paths"], input_bytes=("\n".join(chunk) + "\n").encode("utf-8"))
    lines = [line.strip() for line in done.stdout.split("\n") if line.strip()] if done.returncode == 0 else []
    return dict(zip(chunk, lines)) if len(lines) == len(chunk) else {}


def _hash_files(git, root, names):
    """작업 폴더 파일들의 git 내용 번호(blob) — git 이 저장할 때와 같은 방식(줄바꿈 변환 포함)으로. {이름: 번호}. 읽지 못한 파일은 빠진다.
    덩어리 하나가 실패하면(다른 프로그램이 독점으로 연 파일 하나 때문일 수 있다) 이름을 하나씩 다시 해 본다."""
    found = {}
    for start in range(0, len(names), 500):
        chunk = names[start:start + 500]
        found.update(_hash_chunk(git, root, chunk))
        if len(chunk) > 1 and not all(name in found for name in chunk):
            for name in chunk:
                if name not in found:
                    found.update(_hash_chunk(git, root, [name]))
    return found


def _undo_partial_merge(git, root, changes, head_before):
    """병합이 중간에 멈췄을 때(파일을 다른 프로그램이 쓰는 중·디스크가 가득 참·시간 초과) 병합이 바꿔 놓은 것만 병합 전으로 되돌린다.

    **사용자의 내용은 건드리지 않는다**: 작업 폴더 파일은 '내용이 원격 main 의 것과 똑같을 때'(= 병합이 쓴 것)만 HEAD 의 내용으로 되돌리거나(새 파일이면) 지우고,
    원격이 지운 파일은 지금 없을 때만 되살린다. 내용이 HEAD 와도 원격과도 다르면 사용자가 고친 것(또는 쓰다 만 것)이니 그대로 둔다. 색인은 받을 파일의 항목만 HEAD 로 되돌린다.
    이 함수는 병합이 파일을 쓰다 멈췄을 가능성이 있는 실패에서만 부른다(git 이 사용자의 변경을 지키려고 거절한 경우에는 아무것도 바뀌지 않았으므로 부르지 않고,
    HEAD 가 이미 옮겨졌으면 병합이 끝난 것이라 받은 파일을 되돌리지 않는다). 파일 하나가 안 돼도 나머지는 계속하고, 원래 오류를 가리지 않는다.
    돌려주는 것: 되돌린 뒤에도 병합 전과 다른 파일의 이름들(반쯤 쓰이다 만 파일·지우지 못한 새 파일 …) — 호출한 쪽이 오류 세부에 적는다."""
    left = []
    try:
        moved = git(root, ["rev-parse", "HEAD"])
        if moved.returncode == 0 and moved.stdout.strip() != head_before:
            return left                                      # HEAD 가 옮겨졌다 = 병합은 끝났다. 받은 파일은 되돌릴 것이 아니라 새 상태다
        wanted = [c for c in changes if _safe_name(c.path) and _inside(root, c.path) and "160000" not in (c.old_mode, c.new_mode)]
        if wanted:
            staged = git(root, ["diff", "--cached", "--raw", "-z", "--no-abbrev", "--no-renames", "HEAD"])      # 색인이 HEAD 와 다른 곳 = 병합이 바꿔 둔 곳
            if staged.returncode == 0:
                staged_paths = {c.path for c in _parse_raw(staged.stdout)}
                _git_in_chunks(git, root, ["restore", "--source=HEAD", "--staged"], [c.path for c in wanted if c.path in staged_paths])
            existing = [c for c in wanted if c.status in ("A", "M", "T") and _plain_file(root, c.path)]
            hashes = _hash_files(git, root, [c.path for c in existing])
            wrote = [c for c in existing if hashes.get(c.path) == c.new]                                      # 병합이 쓴 파일(내용이 원격과 똑같다)
            for change in wrote:
                if change.status == "A":
                    try:
                        (Path(root) / change.path).unlink(missing_ok=True)       # 병합이 새로 만든 파일. 대소문자만 바뀐 이름이 대소문자를 구분하지 않는 곳에서 추적 파일 자신이면 잠깐 지워지지만, 아래에서 '지워진 파일' 로 HEAD 에서 되살아난다
                    except OSError:
                        left.append(change.path)                                 # 다른 프로그램이 쥐고 있다 — 못 지운 새 파일은 이름으로 알린다
            restore = [c.path for c in wrote if c.status in ("M", "T")] + [c.path for c in wanted if c.status == "D" and not os.path.lexists(Path(root) / c.path)]
            _git_in_chunks(git, root, ["restore", "--source=HEAD", "--staged", "--worktree"], restore)      # 색인 항목도 함께: 파일을 새로 쓰면 크기(줄바꿈 변환)·시각이 색인에 적힌 것과 달라지고, 크기가 다르면 git 은 내용을 보지 않고 '바뀜' 으로 본다
            left += [c.path for c in existing if c.status == "A" and c.path not in hashes]      # 내용을 읽지 못해 그대로 둔 새 파일
    except Exception:
        pass                                                 # 되돌리다 어긋나도 원래 오류를 가리지 않는다 — 남은 것은 아래에서 이름으로 알린다
    try:
        left += _changed_files(git, root)                    # 추적 파일 중 아직 HEAD 와 다른 것(쓰다 만 파일·되돌리지 못한 파일·내가 방금 고친 파일)
    except Exception:
        pass
    return sorted(dict.fromkeys(left))


def _clear_stale_index_lock(git, root):
    """시간 초과로 끈 git 이 남긴 `.git/index.lock` 을 치운다(방금 만든 것일 때만 — 오래된 잠금은 다른 프로그램의 것일 수 있다)."""
    try:
        done = git(root, ["rev-parse", "--absolute-git-dir"])
        if done.returncode == 0:                         # 실패했는데 빈 글을 경로로 쓰면 앱이 도는 폴더의 index.lock 을 지울 수 있다
            lock = Path(done.stdout.strip()) / "index.lock"
            if time.time() - lock.stat().st_mtime < _LOCK_MAX_AGE:
                lock.unlink()
    except Exception:
        pass


def sync_latest(path, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """연결을 확인한 뒤 원격 main 을 받아 빨리감기로 맞춘다. 로컬 main 이 앞서거나 갈라져 있으면 건드리지 않고 PAGES_LOCAL_REPO_DIVERGED,
    받을 파일과 이름이 같은 내 파일(새 파일·무시한 파일)이 있으면 건드리지 않고 PAGES_LOCAL_FILE_IN_THE_WAY. 병합이 중간에 멈추면 병합 전 상태로
    되돌린다. 맞춘 뒤 HEAD 가 원격 main 과 같은지 다시 확인한다."""
    info = inspect_repo(path, git, expected_origin)
    _must(git, info.path, ["fetch", "--quiet", "origin", f"+refs/heads/{MAIN}:{_REMOTE_MAIN}"], "원격 main 받기")
    counts = _must(git, info.path, ["rev-list", "--left-right", "--count", f"HEAD...{_REMOTE_MAIN}"], "원격과 비교").split()
    ahead, behind = int(counts[0]), int(counts[1])
    if ahead:
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail=f"로컬 main 이 원격보다 {ahead}개 앞선다(갈라짐 {'있음' if behind else '없음'})")
    if behind:
        changes = _incoming_changes(git, info.path)
        mine = _my_files_among(git, info.path, [change.path for change in changes if change.status != "D"])
        if mine:
            raise _in_the_way(mine)
        try:
            merged = git(info.path, ["merge", "--ff-only", "--quiet", _REMOTE_MAIN])
        except AppError as error:                                       # 시간 초과 등으로 병합이 파일을 쓰다 끊겼을 수 있다
            if not _merge_finished(git, info.path, info.head):
                _clear_stale_index_lock(git, info.path)
                _note_left(error, _undo_partial_merge(git, info.path, changes, info.head))
                raise
            merged = GitResult(0, "", "")                               # HEAD 가 이미 원격 main 으로 옮겨졌다 — 병합은 끝났고 훅·백신 같은 뒷정리 때문에 늦었을 뿐이다
        if merged.returncode != 0:
            message = merged.stderr + merged.stdout
            text = message.lower()
            detail = mask(message.strip()[-_DETAIL_TAIL:])[-_DETAIL_CHARS:]
            # git 이 내 파일·변경을 지키려고 **거절한** 경우: 아무것도 바뀌지 않았으니 되돌리지 않는다(되돌리면 내가 고친 것을 지울 수 있다)
            if "untracked working tree file" in text or "would lose untracked files" in text:      # 점검 뒤에 내 파일이 생긴 경우도 내 파일을 지키는 쪽으로
                raise _in_the_way(_names_in(message), detail)
            if "your local changes" in text or "would be overwritten" in text or "not uptodate" in text:
                raise AppError("PAGES_LOCAL_REPO_DIRTY", detail=detail)
            if "not possible to fast-forward" in text or "diverging" in text:
                raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail=detail)
            left = _undo_partial_merge(git, info.path, changes, info.head)               # 그 밖의 실패는 파일을 쓰다 멈춘 것일 수 있다 — 병합이 바꿔 둔 것만 되돌린다
            raise _note_left(_failure(merged, "원격 main 따라잡기", info.path), left)
    head = _must(git, info.path, ["rev-parse", "HEAD"], "HEAD 확인")
    if head != _must(git, info.path, ["rev-parse", _REMOTE_MAIN], "원격 main 확인"):
        raise AppError(UNEXPECTED, detail="따라잡은 뒤에도 HEAD 가 원격 main 과 다르다")
    return RepoInfo(info.path, info.origin, info.branch, head)


def check_push_access(path, git=run_git, expected_origin=EXPECTED_ORIGIN):
    """실제로 올리지 않고 push 가 되는지만 본다(`git push --dry-run`, 사용자의 pre-push 훅은 돌리지 않는다). 인증·네트워크·거절은 각각의 오류 코드로."""
    info = inspect_repo(path, git, expected_origin)
    _must(git, info.path, ["push", "--dry-run", "--porcelain", "--no-verify", "origin", f"HEAD:refs/heads/{MAIN}"], "올리기 점검")
    return info
