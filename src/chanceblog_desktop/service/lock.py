"""글 하나를 올리는 동안 잡는 잠금(글 잠금)과, 연결한 저장소를 쓰는 동안 잡는 잠금(저장소 잠금) — 같은 글을 올리는(또는 되돌리는·공개 확인하는) 명령이 두 개 동시에 돌지 못하게 하고,
**서로 다른 두 글이 같은 저장소에 동시에 commit·push 하지 못하게** 한다.

왜 필요한가: 두 번째 명령이 '올리기 전 점검'을 마친 뒤 첫 명령이 올리기를 끝내 버리면, 두 번째는 이미 낡은 점검을 믿고 움직인다. 그 결과 첫 명령의 발행 기록을 지우거나 덮어써서
글은 올라갔는데 앱은 그 사실을 잊는 일이 생길 수 있다. 그래서 점검보다 먼저 이 잠금을 잡고, 못 잡으면 **아무것도 바꾸지 않고** `PUBLISH_IN_PROGRESS` 로 멈춘다(AGENTS.md 규칙 4: 의심스러우면 하지 않는다).
글 잠금은 글마다라서 서로 다른 두 글을 거의 동시에 올리면 둘 다 '최신 받기 → commit' 을 같은 저장소에서 하게 된다 — 둘 다 commit 만 하고 올리지 못해(올리지 않은 commit 이 둘) 서로를 막았다.
그래서 저장소 잠금을 하나 더 둔다: commit·push·되돌리기를 하는 구간은 연결한 저장소마다 한 번에 하나만 돌고, 다른 작업은 짧게 기다리다(`Context.lock_wait` 초) 못 잡으면 **아무것도 바꾸지 않고**
`PUBLISH_REPO_BUSY` 로 물러난다(같은 명령을 다시 실행하면 된다). 저장소 잠금은 공개 확인을 기다리기 전에 풀어 다른 글이 그동안 올라갈 수 있다.

방식: 사용자 데이터 폴더의 `publish/<글번호>.lock`(저장소 잠금은 `publish/repo-<저장소 폴더 이름의 해시>.lock`) 파일을 `O_CREAT|O_EXCL`(이미 있으면 실패)로 만들고 프로세스 번호·시작 시각·**실행 번호(무작위)** 를 적는다.
 · 풀 때는 **자기 실행 번호인 잠금만** 지운다(낡은 것으로 보고 다른 실행이 넘겨받은 잠금을 지우지 않는다). 정상 종료·예외·Ctrl+C 모두 `finally` 에서 푼다.
 · 낡은 잠금은 PC 가 갑자기 꺼지거나 창을 닫아 작업이 죽은 흔적으로 보고 넘겨받는다(넘겨받았다는 사실은 알린다): ① 잠금을 남긴 **프로세스가 같은 PC 에서 이미 끝났으면 바로**(`service/liveness.py` — 읽기만 한다.
   Windows 에서 `os.kill(pid, 0)` 은 프로세스를 끝내 버리므로 쓰지 않는다. 프로세스 번호는 재사용되므로 잠금을 잡은 뒤에 시작한 프로세스는 다른 프로세스로 본다) ② 알 수 없으면 시작한 지
   `max(30분, 기다리는 시간 + 15분)` 이 지난 뒤에. 살아 있는지 확신이 없으면 넘겨받지 않는다. 넘겨받을 때는 낡은 파일을 먼저 다른 이름으로 옮겨(한 곳만 성공) 그것이 읽었던 그 잠금인지 확인한다.
 · 내용을 읽을 수 없는 잠금(만들다 멈춤)은 파일 수정 시각으로 같은 기준을 쓴다.
미리 보기(dry run)는 잠그지 않는다 — 아무것도 쓰지 않는다는 약속이 먼저다.
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import platform
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..errors import AppError
from .liveness import process_alive

LOCK_SUFFIX = ".lock"
REPO_PREFIX = "repo-"           # 연결한 저장소 하나의 잠금 파일 이름 앞머리(`repo-<16자리>.lock`) — 글 번호(uuid)와 겹치지 않는다
STALE_SECONDS = 1800            # 이보다 오래된 잠금은 낡은 것으로 본다(기다리는 시간이 길면 그 시간 + 15분)
STALE_MARGIN = 900
SCHEMA = 1
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RUN = re.compile(r"^[0-9a-f]{32}$")
_KEYS = {"schema", "project_id", "pid", "started", "max_seconds", "run"}          # + 선택 칸 host(잠금을 잡은 PC 이름 — 같은 PC 에서 시작한 잠금만 프로세스 생존을 본다)
_STAMP = "%Y-%m-%dT%H:%M:%SZ"
_KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class Holder:
    pid: int
    started: datetime
    max_seconds: int
    run: str
    host: str = ""

    def started_text(self):
        return self.started.astimezone(_KST).strftime("%Y-%m-%d %H:%M:%S") + " 한국 시각"


def lock_seconds(deadline):
    """이 만큼 지난 잠금은 낡은 것으로 본다 — 공개 확인을 오래 기다리는 사용자는 그 시간만큼 더."""
    return max(STALE_SECONDS, int(deadline or 0) + STALE_MARGIN)


class PublishLock:
    """글 하나의 잠금 파일. `acquire()` 로 잡고(못 잡으면 PUBLISH_IN_PROGRESS) `release()` 로 푼다 — 보통은 `publish_lock()` 으로 쓴다."""

    busy_code = "PUBLISH_IN_PROGRESS"          # 못 잡았을 때의 오류 코드 — 저장소 잠금은 PUBLISH_REPO_BUSY
    what = "같은 글을 올리다"                    # 낡은 잠금을 넘겨받았다고 알릴 때 쓰는 말('이전에 … 멈춘 흔적')

    def __init__(self, folder, project_id, *, now, deadline=0, alive=None):
        if not isinstance(project_id, str) or not _ID.match(project_id):
            raise AppError("CONTENT_INVALID", {"항목": "프로젝트 번호"})
        self.path = os.path.join(os.fspath(folder), project_id + LOCK_SUFFIX)
        self.folder = os.fspath(folder)
        self.project_id = project_id
        self.now = now
        self.max_seconds = lock_seconds(deadline)
        self.run = secrets.token_hex(16)
        self.host = platform.node()
        self.alive = alive or (lambda holder: process_alive(holder.pid, holder.started))        # 잠금을 남긴 프로세스가 살아 있는가(True·False·None=모름) — 시험에서 바꿔 끼운다
        self.why_stale = ""          # 넘겨받을 때의 이유: old(시간이 지남)·gone(프로세스가 이미 끝남)
        self.taken_over = ""        # 낡은 잠금을 넘겨받았다면 그 사실(화면에 알린다)
        self.release_note = ""      # 풀지 못했다면 그 사실
        self.waited = 0.0           # 다른 작업이 놓기를 기다린 시간(초) — `acquire_waiting` 이 적는다
        self.held = False

    # ---- 읽기 ---------------------------------------------------------------------------------------------------------
    @staticmethod
    def _parse(raw):
        """잠금 파일 내용 → Holder. 모양이 올바르지 않으면 None."""
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or set(data) - {"host"} != _KEYS or data["schema"] != SCHEMA or not isinstance(data.get("host", ""), str):
                return None
            pid, seconds, run = data["pid"], data["max_seconds"], data["run"]
            if (isinstance(pid, bool) or not isinstance(pid, int) or isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0
                    or not isinstance(run, str) or not _RUN.match(run) or not isinstance(data["started"], str)):
                return None
            started = datetime.strptime(data["started"], _STAMP).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, KeyError):
            return None
        return Holder(pid, started, seconds, run, data.get("host", ""))

    def _read(self, path=None):
        """(Holder 또는 None, 읽었다는 뜻). 파일이 없으면 (None, False)."""
        try:
            raw = Path(path or self.path).read_bytes()[:4096].decode("utf-8")
        except FileNotFoundError:
            return None, False
        except (OSError, UnicodeDecodeError):
            return None, True               # 있는데 읽을 수 없다 — 만들다 멈췄거나 다른 곳에서 쓰는 중
        return self._parse(raw), True

    def _is_stale(self, holder):
        if holder is not None:
            age = (self.now() - holder.started).total_seconds()
            if abs(age) > holder.max_seconds:             # 시계가 크게 뒤로 가 있어도(음수) 같은 기준
                self.why_stale = "old"
                return True
            if holder.host in ("", self.host) and self.alive(holder) is False:          # 같은 PC 에서 시작했고 그 프로세스가 이미 없다 — 기다릴 이유가 없다
                self.why_stale = "gone"
                return True
            return False
        try:
            age = time.time() - os.stat(self.path).st_mtime
        except FileNotFoundError:
            return True                                   # 읽고 난 사이 잠금이 사라졌다 — 넘겨받을 것도 없으니(`_take_over` 가 곧바로 True) 바로 다시 잡아 본다
        except OSError:
            return False                                  # 시각을 알 수 없으면(권한·다른 프로세스가 쥐고 있음 …) 낡았다고 보지 않는다(막는 쪽)
        return abs(age) > self.max_seconds

    # ---- 잡기 ---------------------------------------------------------------------------------------------------------
    def _payload(self):
        return {"schema": SCHEMA, "project_id": self.project_id, "pid": os.getpid(), "started": self.now().strftime(_STAMP), "max_seconds": self.max_seconds, "run": self.run, "host": self.host}

    def _create(self):
        """잠금 파일을 새로 만든다 — 이미 있으면 FileExistsError. 쓰다 실패하면 만든 파일을 치우고 오류."""
        data = (json.dumps(self._payload(), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
        try:
            os.write(fd, data)
        except OSError as error:
            os.close(fd)
            self._remove_file(self.path)
            raise self._write_problem(error) from None
        os.close(fd)

    def _write_problem(self, error):
        code = "DISK_FULL" if getattr(error, "errno", None) == errno.ENOSPC else "FILE_WRITE_FAILED"
        return AppError(code, {"경로": self.path}, detail=f"{type(error).__name__}: 잠금 파일을 만들지 못했다")

    @staticmethod
    def _remove_file(path):
        """파일을 지운다. 지우지 못했으면 이유(예외 이름), 잘 지웠거나 원래 없었으면 ''."""
        problem = ""
        for attempt in range(5):                         # 다른 프로세스가 읽는 짧은 순간(Windows 공유 위반)에는 잠깐 뒤 다시
            try:
                os.unlink(path)
                return ""
            except FileNotFoundError:
                return ""
            except OSError as error:
                problem = type(error).__name__
                if attempt < 4:
                    time.sleep(0.1)
        return problem

    def _busy(self, holder, *, unreadable=False):
        if holder is not None:
            shown = f"{holder.started_text()} (프로세스 {holder.pid})"
            detail = f"잠금 파일 {os.path.basename(self.path)}: 시작 {holder.started.strftime(_STAMP)}, 프로세스 {holder.pid}, 최대 {holder.max_seconds}초"
        else:
            shown = "시작 시각을 알 수 없음"
            detail = f"잠금 파일 {os.path.basename(self.path)} 을 읽을 수 없거나 만드는 중이다" if unreadable else f"잠금 파일 {os.path.basename(self.path)} 의 내용이 올바르지 않다"
        return AppError(self.busy_code, {"시작": shown}, detail=detail)

    def _take_over(self, seen):
        """낡은 잠금을 다른 이름으로 옮겨(한 곳만 성공) 읽었던 그 잠금이 맞는지 확인한다. 맞으면 치우고 True, 그 사이 누가 이미 치웠으면 "gone"(넘겨받을 것도 없다 — 곧바로 다시 잡아 본다),
        아니면(그 사이 다른 작업이 새로 잡은 것) 되돌려 놓고 False."""
        aside = f"{self.path}.stale-{secrets.token_hex(6)}"
        try:
            os.replace(self.path, aside)
        except FileNotFoundError:
            return "gone"                                # 그 사이 누군가 이미 치웠다 — 다시 잡아 본다
        except OSError:
            return False                                 # 열려 있는 등 지금은 옮길 수 없다 — 넘겨받지 않는다
        moved, _ = self._read(aside)
        if (seen is None and moved is None) or (seen is not None and moved is not None and moved.run == seen.run):
            self._remove_file(aside)
            return True
        try:
            os.link(aside, self.path)                    # 새로 잡힌 잠금이었다 — 제자리로(이미 다른 것이 있으면 실패한다)
        except OSError as error:
            self.release_note = f"다른 작업의 잠금을 되돌려 놓지 못했다({type(error).__name__}): {os.path.basename(aside)}"
        self._remove_file(aside)
        return False

    def acquire(self):
        """잠금을 잡는다. 같은 글을 올리는 다른 작업이 있으면 PUBLISH_IN_PROGRESS — 그때 아무것도 바꾸지 않는다. 낡은 잠금을 넘겨받았으면 그 사실을 `taken_over` 에 둔다."""
        try:
            Path(self.folder).mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise self._write_problem(error) from None
        for attempt in range(3):
            try:
                self._create()
            except FileExistsError:
                holder, readable = self._read()
                if not readable:
                    continue                                     # 그 사이 풀렸다 — 다시 잡아 본다
                if not self._is_stale(holder):
                    raise self._busy(holder, unreadable=holder is None) from None
                taken = self._take_over(holder)
                if not taken:
                    raise self._busy(holder, unreadable=holder is None) from None
                if taken == "gone":
                    continue                                     # 읽고 난 사이 잠금이 풀렸다 — 넘겨받은 것이 아니므로 알리지 않고 다시 잡아 본다
                reason = "그 프로세스는 이미 끝나 있음" if self.why_stale == "gone" else "오래된 잠금"
                self.taken_over = (f"이전에 {self.what} 멈춘 흔적({reason})을 넘겨받았습니다"
                                   + (f": {holder.started_text()} 에 시작, 프로세스 {holder.pid}." if holder is not None else "."))
                continue
            except PermissionError as error:                     # Windows: 방금 지운 파일이 아직 '지우는 중' 이거나 다른 프로세스가 읽는 중 — 잠깐 뒤 다시
                if attempt < 2:
                    time.sleep(0.1)
                    continue
                raise self._write_problem(error) from None
            except OSError as error:
                raise self._write_problem(error) from None
            self.held = True
            return self
        raise self._busy(None, unreadable=True)                  # 세 번을 해도 잡지 못했다 — 다른 작업이 계속 잡고 푼다

    def acquire_waiting(self, wait_seconds, *, progress=None, interval=0.5):
        """잠금을 잡는다 — 다른 작업이 쥐고 있으면 최대 `wait_seconds` 초 동안 `interval` 초마다 다시 해 보고, 끝내 못 잡으면 `acquire` 와 같은 오류(아무것도 바꾸지 않았다).
        기다리기 시작할 때 한 번 `progress(글)` 로 알린다(알릴 곳이 없으면 조용히). 기다린 시간은 `waited` 에 남는다. 잠금 파일을 만들지 못하는 등 '쥐고 있어서' 가 아닌 오류는 기다리지 않고 바로 낸다."""
        started = time.monotonic()
        slept = False
        while True:
            try:
                self.acquire()
                break
            except AppError as error:
                left = float(wait_seconds or 0) - (time.monotonic() - started)
                if error.code != self.busy_code or left <= 0:
                    raise
                if not slept and progress is not None:
                    progress(f"다른 글을 올리는 작업이 끝나기를 기다립니다(최대 {int(wait_seconds)}초) — {error.slots['시작']}")
                slept = True
                time.sleep(min(interval, left))
        self.waited = time.monotonic() - started if slept else 0.0
        return self

    # ---- 풀기 ---------------------------------------------------------------------------------------------------------
    def release(self):
        """자기 실행 번호인 잠금만 지운다. 예외를 내지 않는다(실패는 `release_note` 에 적는다)."""
        if not self.held:
            return
        self.held = False
        holder, readable = self._read()
        if not readable:
            return                                           # 이미 없다
        if holder is None or holder.run != self.run:
            self.release_note = "내 잠금이 아니어서(낡은 것으로 보고 다른 작업이 넘겨받음) 지우지 않았습니다."
            return
        problem = self._remove_file(self.path)
        if problem:
            self.release_note = f"잠금 파일을 지우지 못했습니다({problem}) — 30분이 지나면 낡은 것으로 보고 넘겨받습니다: {os.path.basename(self.path)}"


def repo_lock_name(repo):
    """연결한 저장소 폴더 → 저장소 잠금 이름(`repo-<16자리>`). 같은 폴더면 어떤 경로 표기(상대 경로·`..`·링크·정션·Windows 의 대소문자)로 불러도 같은 이름이다."""
    real = os.path.normcase(os.path.realpath(os.fspath(repo)))
    return REPO_PREFIX + hashlib.sha256(real.encode("utf-8", "surrogatepass")).hexdigest()[:16]


class RepoLock(PublishLock):
    """연결한 저장소 하나의 잠금 — 그 저장소에 commit·push·되돌리기를 하는 구간을 한 번에 한 작업만 한다(글이 달라도). 못 잡으면 PUBLISH_REPO_BUSY."""

    busy_code = "PUBLISH_REPO_BUSY"
    what = "이 저장소에 글을 올리다"

    def __init__(self, folder, repo, *, now, alive=None):
        super().__init__(folder, repo_lock_name(repo), now=now, alive=alive)


@contextlib.contextmanager
def publish_lock(ctx, project_id, *, deadline=0):
    """`with publish_lock(ctx, 글번호) as lock:` — 블록 안에서만 그 글을 올리는 다른 작업이 없다. 어떻게 끝나도(예외·Ctrl+C 포함) 푼다."""
    if isinstance(project_id, str) and project_id.startswith(REPO_PREFIX):
        raise AppError("CONTENT_INVALID", {"항목": "프로젝트 번호"}, detail="저장소 잠금 이름과 같은 앞머리는 쓰지 않는다")
    lock = PublishLock(ctx.workspace.journal_dir, project_id, now=ctx.now, deadline=deadline)
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()


@contextlib.contextmanager
def repo_lock(ctx, repo, *, wait=None, progress=None):
    """`with repo_lock(ctx, 저장소 폴더) as lock:` — 블록 안에서만 그 저장소에 글을 올리는(commit·push·되돌리는) 다른 작업이 없다. 다른 작업이 쥐고 있으면 최대 `wait`(기본 `ctx.lock_wait`)초 기다리고
    그래도 못 잡으면 PUBLISH_REPO_BUSY(아무것도 바꾸지 않았다). 어떻게 끝나도(예외·Ctrl+C 포함) 푼다."""
    lock = RepoLock(ctx.workspace.journal_dir, repo, now=ctx.now)
    lock.acquire_waiting(ctx.lock_wait if wait is None else wait, progress=progress)
    try:
        yield lock
    finally:
        lock.release()
