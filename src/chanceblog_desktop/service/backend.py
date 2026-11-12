"""연결한 chanceblog 저장소에 대한 실제 일 — 확인·commit·push·되돌리기·배포 확인을 기존 모듈(`publish/`)에 맡긴다.

서비스 함수들은 이 객체의 메서드만 부른다(`Context.backend`). 시험은 이 객체를 가짜로 바꿔 끼워 git·네트워크 없이 상태 흐름을 확인하고,
진짜 git 시험은 이 객체에 진짜 `git` 실행기와 로컬 bare 저장소를 쓴다. 여기서 직접 쓰는 git 명령은 읽기 전용뿐이다(`rev-parse`·`ls-tree`·`rev-list`·`cat-file`) —
쓰기(commit·push·되돌리기)는 모두 `publish/pages.py` 의 함수가 한다(강제 push 없음·그 글 하나만·훅과 서명 끔).
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime
from pathlib import Path

from .. import capabilities
from ..errors import AppError
from ..publish import deploy, gitrepo, pages
from ..render.pages import KST, post_path

REMOTE_MAIN = "refs/remotes/origin/main"


def _made_by_the_app(path, category, lang):
    """그 경로가 이 글(분야·언어)로 앱이 만드는 모양 그대로인가 — `_posts/<분야 폴더>/날짜-KR|EN-시각.md` 이고 분야 폴더·언어 표시가 이 글의 것이다."""
    found = pages.POST_PATH.fullmatch(path)
    if found is None:
        return False
    year, month, day, hour, minute, second = (int(part) for part in found.groups())
    try:
        stamp = datetime(year, month, day, hour, minute, second, tzinfo=KST)
        return post_path(category, lang, stamp) == path
    except (ValueError, KeyError, AppError):
        return False


class GitPagesBackend:
    def __init__(self, *, git=gitrepo.run_git, expected_origin=gitrepo.EXPECTED_ORIGIN, fetcher=None, sleep=None, monotonic=None):
        self.git = git
        self.expected_origin = expected_origin
        self.fetcher = fetcher
        self.sleep = sleep
        self.monotonic = monotonic
        self.progress = None               # 기다리는 동안 진행을 알리는 함수(글 한 줄을 받는다) — 명령줄이 정한다. 없으면 조용히 기다린다

    # ---- 읽기만 하는 일 --------------------------------------------------------------------------------------------------
    def inspect(self, repo):
        """연결할 수 있는 저장소인가(origin·main·저장하지 않은 변경 없음). 아무것도 바꾸지 않는다."""
        return gitrepo.inspect_repo(repo, self.git, self.expected_origin)

    def check_push_access(self, repo):
        """`git push --dry-run` — 실제로는 올리지 않는다(네트워크를 쓴다)."""
        capabilities.require_external_write("올리기 권한 점검")
        return gitrepo.check_push_access(repo, self.git, self.expected_origin)

    def unpushed_count(self, repo):
        """마지막으로 받아 둔 원격 main 보다 앞선(올리지 않은) 커밋 수. 알 수 없으면 None."""
        done = self.git(Path(repo), ["rev-list", "--count", f"{REMOTE_MAIN}..HEAD"])
        text = done.stdout.strip()
        return int(text) if done.returncode == 0 and text.isdigit() else None

    def unpushed_made_by_app(self, repo):
        """올리지 않은 commit 중 이 앱이 만든 모양(제목이 앱의 글 올리기 commit 제목으로 시작)인 것의 수 — 읽기만 한다(log). 알 수 없으면 0.
        이 데이터 폴더에 기록이 없는데 앱이 만든 모양인 commit 이 있으면 다른 데이터 폴더(`--data-dir`)의 앱이 올리다 멈춘 글일 수 있다(안내를 가르는 데만 쓴다 — 어떤 commit 도 건드리지 않는다)."""
        done = self.git(Path(repo), ["log", "--format=%s", f"{REMOTE_MAIN}..HEAD"])
        if done.returncode != 0:
            return 0
        return sum(1 for line in done.stdout.splitlines() if line.startswith(pages._COMMIT_PREFIX))

    def duplicates(self, repo, post):
        """같은 주소(날짜-언어-시각)의 글 파일 이름들 — 작업 폴더와 마지막으로 받아 둔 원격 main 에서 찾는다(분야 폴더·확장자가 달라도 Jekyll 주소는 같다). 아무것도 쓰지 않는다."""
        root = Path(repo)
        stem = Path(post.path).stem
        found = []
        posts = root / "_posts"
        if posts.is_dir():
            found += sorted(entry.relative_to(root).as_posix() for entry in posts.rglob(stem + ".*"))
        listing = self.git(root, ["ls-tree", "-r", "--name-only", "-z", REMOTE_MAIN, "--", "_posts"])
        if listing.returncode == 0:
            found += [name for name in listing.stdout.split("\0") if name and name.rsplit("/", 1)[-1].startswith(stem + ".") and name not in found]
        return found

    def same_content(self, repo, text):
        """올리려는 글과 **내용이 한 글자도 다르지 않은** 글이 이미 있는 파일 이름들 — 작업 폴더의 `_posts` 와 마지막으로 받아 둔 원격 main 의 `_posts` 를 본다(줄바꿈 변환은 같게 본다). 아무것도 쓰지 않는다.
        백업으로 되돌린 글이 이미 올라간 글을 다시 승인된 모습으로 되살렸을 때 같은 글이 두 번 공개되는 것을 막으려고 쓴다."""
        root = Path(repo)
        wanted = text.replace("\r\n", "\n").encode("utf-8")
        key = hashlib.sha1(b"blob %d\0" % len(wanted) + wanted).hexdigest()
        found = []
        posts = root / "_posts"
        if posts.is_dir():
            sizes = (len(wanted), len(wanted) + wanted.count(b"\n"))
            for entry in sorted(posts.rglob("*")):
                if entry.is_file() and entry.stat().st_size in sizes and entry.read_bytes().replace(b"\r\n", b"\n") == wanted:
                    found.append(entry.relative_to(root).as_posix())
        listing = self.git(root, ["ls-tree", "-r", "-z", REMOTE_MAIN, "--", "_posts"])
        if listing.returncode == 0:
            for item in listing.stdout.split("\0"):
                meta, _tab, name = item.partition("\t")
                parts = meta.split()
                if len(parts) == 3 and parts[1] == "blob" and parts[2] == key and name not in found:
                    found.append(name)
        return found

    def expected_url(self, repo, post, now):
        """글의 공개 주소(네트워크 없이 Jekyll permalink 로 계산). 사이트가 공개하지 않을 글이면 AppError."""
        return deploy.expected_url(repo, post.path, post.text, now=now)

    def _rev(self, repo, ref):
        done = self.git(Path(repo), ["rev-parse", "--verify", "--quiet", ref])
        value = done.stdout.strip()
        if done.returncode != 0 or not value:
            raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail=f"{ref} 를 읽을 수 없다")
        return value

    def current_commit(self, repo, path):
        """지금 HEAD 를 '되돌릴 글 커밋' 으로 본 기록(CommitInfo). 실제로 되돌려도 되는지는 `discard` 가 다시 확인한다."""
        return pages.CommitInfo(path, self._rev(repo, "HEAD"), self._rev(repo, "HEAD^"))

    def post_in_head(self, repo, path):
        """지금 HEAD 가 그 글 파일을 담고 있는가."""
        return self.git(Path(repo), ["cat-file", "-e", f"HEAD:{path}"]).returncode == 0

    def on_remote(self, repo, path):
        """마지막으로 받아 둔 원격 main 이 그 글 파일을 담고 있는가(읽기만 한다) — 이미 올라간 글인지 보려고."""
        return self.git(Path(repo), ["cat-file", "-e", f"{REMOTE_MAIN}:{path}"]).returncode == 0

    def head_commit(self, repo):
        """지금 HEAD 의 커밋 번호(읽을 수 없으면 PAGES_LOCAL_REPO_DIVERGED)."""
        return self._rev(repo, "HEAD")

    def orphan_commit(self, repo, text, category, lang):
        """올리다 commit 직후에 멈춰 발행 기록 없이 남은 이 글의 commit 인가 — 올리지 않은 commit 이 **정확히 하나**이고, 그것이 이 앱이 만든 것(제목 머리말)이며,
        글 파일 **하나만** 더하고(경로는 이 글의 분야·언어로 앱이 만드는 모양), 그 파일의 내용이 승인한 글(text)과 **한 글자도 다르지 않을 때만** CommitInfo, 아니면 None(확신이 없으면 이어받지 않는다).
        읽기 전용 git 명령(rev-list·rev-parse·diff-tree·log·cat-file)만 쓴다."""
        root = Path(repo)
        if self.unpushed_count(root) != 1:
            return None
        head = self.git(root, ["rev-parse", "--verify", "--quiet", "HEAD"])
        base = self.git(root, ["rev-parse", "--verify", "--quiet", "HEAD^"])
        if head.returncode != 0 or base.returncode != 0 or not head.stdout.strip() or not base.stdout.strip():
            return None
        changes = self.git(root, ["diff-tree", "-z", "--no-commit-id", "--name-status", "-r", "HEAD"])
        parts = [item for item in changes.stdout.split("\0") if item] if changes.returncode == 0 else []
        if len(parts) != 2 or parts[0] != "A" or not _made_by_the_app(parts[1], category, lang):
            return None
        path = parts[1]
        subject = self.git(root, ["log", "-1", "--format=%s", "HEAD"])
        if subject.returncode != 0 or not subject.stdout.strip().startswith(pages._COMMIT_PREFIX):
            return None
        content = self.git(root, ["cat-file", "blob", f"HEAD:{path}"])
        if content.returncode != 0 or content.stdout != text:
            return None
        return pages.CommitInfo(path, head.stdout.strip(), base.stdout.strip())

    # ---- 쓰는 일(모두 publish/pages.py 가 한다) ----------------------------------------------------------------------------
    def commit(self, repo, post, title):
        capabilities.require_external_write("글 기록(commit)")
        return pages.commit_post(repo, post, title=title, git=self.git, expected_origin=self.expected_origin)

    def push(self, repo, post):
        capabilities.require_external_write("원격 main 에 올리기")
        return pages.push_commit(repo, post, git=self.git, expected_origin=self.expected_origin)

    def discard(self, repo, info):
        capabilities.require_external_write("올리지 않은 글 기록 되돌리기")
        return pages.discard_commit(repo, info, git=self.git, expected_origin=self.expected_origin)

    # ---- 배포 확인(네트워크) -------------------------------------------------------------------------------------------------
    def _sleeper(self, deadline):
        """기다릴 때마다 진행을 알리는 sleep(알릴 곳이 없으면 정한 sleep 그대로)."""
        if self.progress is None:
            return self.sleep
        base, waited = self.sleep or time.sleep, [0]

        def sleeper(seconds):
            waited[0] += 1
            self.progress(f"공개 주소가 아직 열리지 않았습니다 — {int(seconds)}초 뒤 다시 확인합니다({waited[0]}번째 기다림, 최대 {int(deadline)}초까지 기다립니다). Ctrl+C 로 멈춰도 됩니다 — 나중에 check-deploy 로 확인합니다.")
            base(seconds)

        return sleeper

    def check_deployed(self, repo, post, now, deadline, interval):
        capabilities.require_external_write("공개 주소 확인")
        return deploy.check_deployed(repo, post.path, post.text, deadline=deadline, interval=interval, fetcher=self.fetcher, sleep=self._sleeper(deadline), clock=self.monotonic, now=now)
