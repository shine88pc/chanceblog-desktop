"""서비스 층 시험 도우미(시험이 아니다) — 가짜 시계·가짜 backend(git·네트워크 없음)·Context 만들기·명령줄 실행·진짜 git 시험 저장소.

시험 파일들이 `import service_support` 로 쓴다(`python -m unittest discover -s tests` 는 tests/ 를 import 경로에 올린다).
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.core import load_vendored_script  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402
from chanceblog_desktop.publish.gitrepo import GitResult, RepoInfo  # noqa: E402
from chanceblog_desktop.publish.pages import CommitInfo, PushInfo  # noqa: E402
from chanceblog_desktop.publish.deploy import DeployResult  # noqa: E402
from chanceblog_desktop.service import cli, projects, review  # noqa: E402
from chanceblog_desktop.service.context import Context, Settings, Workspace  # noqa: E402
from chanceblog_desktop.service.previews import PagesParams  # noqa: E402

VERIFY = load_vendored_script("verify_pages_deploy")
KEY = "AI" + "za" + "A" * 35                                      # 구글 API 키 모양의 가짜 값(가림 시험용 — 저장소에는 키 문자열이 없다)
HAVE_GIT = bool(shutil.which("git"))
KO_SENTENCE = "에너지 절약은 작은 습관에서 시작되며 매일 조금씩 실천하면 생활비와 환경 모두에 도움이 됩니다. "
EN_SENTENCE = "Saving energy at home starts with small daily habits that add up over time and lower the monthly bill. "
DIFFERENT = ("오늘 저녁에는 가족과 함께 동네 공원을 천천히 걸으며 계절이 바뀌는 풍경을 둘러보았고 아이들은 낙엽을 주우며 즐거워했습니다. "
             "돌아오는 길에는 작은 가게에서 따뜻한 차를 마시며 하루를 정리했습니다. ") * 8          # ko_text() 와 겹치지 않는 다른 글(네이버 두 블로그를 다르게 쓸 때)
KO_PARAMS = PagesParams("경제·일", "ko", "https://images.example.invalid/a.jpg", ("에너지", "생활"))
EN_PARAMS = PagesParams("Society & Policy", "en", "https://images.example.invalid/b.jpg", ("energy",))
NOW = datetime(2026, 11, 2, 1, 30, 12, tzinfo=timezone.utc)          # 한국 시각 2026-11-02 10:30:12
KO_PATH = "_posts/경제·일/2026-11-02-KR-103012.md"
KO_URL = "https://example.invalid/chanceblog/posts/2026/11/02/KR-103012/"


def ko_text(chars=1500, extra=""):
    """게이트(한글 1000자 이상·한글 비율)를 통과하는 긴 한글 원고."""
    sentences = (KO_SENTENCE * (chars // len(KO_SENTENCE) + 2)).strip().split(". ")
    paragraphs = [". ".join(sentences[i:i + 3]).strip() for i in range(0, len(sentences), 3)]
    return "\n\n".join(item if item.endswith(".") else item + "." for item in paragraphs if item) + (("\n\n" + extra) if extra else "")


def en_text(chars=2000):
    sentences = (EN_SENTENCE * (chars // len(EN_SENTENCE) + 2)).strip().split(". ")
    paragraphs = [". ".join(sentences[i:i + 3]).strip() for i in range(0, len(sentences), 3)]
    return "\n\n".join(item if item.endswith(".") else item + "." for item in paragraphs if item)


def naver_profiles(ctx, both=True):
    """네이버 블로그 프로필(A, 그리고 both 면 B)을 설정에 저장해 둔다."""
    from chanceblog_desktop.content.profiles import NaverProfile
    ctx.settings.save_naver_profile(NaverProfile("naver_a", "블로그 에이", "https://blog.naver.com/exampleaaa", default_tags=("생활",), min_chars=10, max_chars=20000))
    if both:
        ctx.settings.save_naver_profile(NaverProfile("naver_b", "블로그 비", "https://blog.naver.com/examplebbb", default_tags=("정보",), min_chars=10, max_chars=20000))


def code_of(callable_, *args, **kwargs):
    """AppError 가 나야 한다 — 난 오류를 돌려준다."""
    import unittest
    with unittest.TestCase().assertRaises(AppError) as caught:
        callable_(*args, **kwargs)
    return caught.exception


class Clock:
    """가짜 시계 — 고정된 시각을 돌려주고 advance 로만 흐른다."""

    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class FakeBackend:
    """`Context.backend` 의 가짜 — git·네트워크 없이 상태 흐름만 본다. 부른 일은 `calls` 에 (이름, …) 로 남고, 실패는 `*_error` 로 일으킨다."""

    def __init__(self):
        self.calls = []
        self.inspect_error = None
        self.url_error = None
        self.commit_error = None
        self.push_errors = []              # 한 번 부를 때마다 하나씩 꺼내 쓴다(None 이면 성공)
        self.discard_error = None
        self.deploy_errors = []
        self.names_found = []
        self.remote_paths = set()          # 받아 둔 원격 main 에 있는 글 파일 경로들(remote_has_post 와 같이 쓴다)
        self.deployed_at = None            # 공개 확인을 부를 때 받은 시각(글 파일 이름의 시각과 같아야 한다)
        self.taken_stems = set()           # 이 이름(날짜-언어-시각)의 글이 이미 저장소에 있다 — duplicates 가 그 글의 경로를 돌려준다(같은 초에 올라간 글)
        self.unpushed = 0
        self.made_by_app = 0               # 올리지 않은 commit 중 앱이 만든 모양(제목이 앱의 commit 제목)인 것의 수 — 이 데이터 폴더에 기록이 없는 commit 이 다른 앱의 것인지 가르는 데 쓴다
        self.head_has_post = False
        self.push_already = False
        self.push_commit_id = "d" * 40
        self.orphan = None                 # commit 직후에 멈춰 기록 없이 남은 이 글의 commit(CommitInfo) — 있으면 orphan_commit 이 돌려준다
        self.same_content_found = []       # 내용이 똑같은 글이 이미 있는 파일 이름들(백업으로 되살린 글이 이미 올라간 경우)
        self.remote_has_post = False       # 받아 둔 원격 main 에 이 글 파일이 이미 있는가(올리고 나서 멈춘 글을 되돌리려 할 때)
        self.head = "c" * 40               # 지금 HEAD 의 커밋 번호
        self.hooks = {}                    # 이름 → 그 일을 시작할 때 먼저 부르는 함수(그 순간의 상태를 들여다보려고)

    def _enter(self, name, *args):
        self.calls.append((name, *args))
        if name in self.hooks:
            self.hooks[name]()

    def names(self):
        return [call[0] for call in self.calls]

    def count(self, name):
        return self.names().count(name)

    def inspect(self, repo):
        self.calls.append(("inspect", str(repo)))
        if self.inspect_error:
            raise self.inspect_error
        return RepoInfo(Path(repo), "https://github.com/shine88pc/chanceblog.git", "main", "a" * 40)

    def check_push_access(self, repo):
        self.calls.append(("check_push_access", str(repo)))
        return self.inspect(repo)

    def unpushed_count(self, repo):
        self.calls.append(("unpushed_count",))
        return self.unpushed

    def unpushed_made_by_app(self, repo):
        self.calls.append(("unpushed_made_by_app",))
        return self.made_by_app

    def duplicates(self, repo, post):
        self.calls.append(("duplicates", post.path))
        taken = [post.path] if Path(post.path).stem in self.taken_stems else []
        return list(self.names_found) + taken

    def expected_url(self, repo, post, now):
        self.calls.append(("expected_url", post.path))
        if self.url_error:
            raise self.url_error
        stem = Path(post.path).stem                    # 2026-11-02-KR-103012
        year, month, day, rest = stem.split("-", 3)
        return f"https://example.invalid/chanceblog/posts/{year}/{month}/{day}/{rest}/"

    def current_commit(self, repo, path):
        self.calls.append(("current_commit", path))
        return CommitInfo(path, "c" * 40, "b" * 40)

    def post_in_head(self, repo, path):
        self.calls.append(("post_in_head", path))
        return self.head_has_post

    def on_remote(self, repo, path):
        self.calls.append(("on_remote", path))
        return self.remote_has_post or path in self.remote_paths

    def head_commit(self, repo):
        self.calls.append(("head_commit",))
        return self.head

    def orphan_commit(self, repo, text, category, lang):
        self.calls.append(("orphan_commit",))
        return self.orphan

    def same_content(self, repo, text):
        self.calls.append(("same_content",))
        return list(self.same_content_found)

    def commit(self, repo, post, title):
        self._enter("commit", post.path, title, post.text)
        if self.commit_error:
            raise self.commit_error
        return CommitInfo(post.path, "c" * 40, "b" * 40)

    def push(self, repo, post):
        self._enter("push", post.path)
        error = self.push_errors.pop(0) if self.push_errors else None
        if error:
            raise error
        return PushInfo(self.push_commit_id, 0 if self.push_already else 1, self.push_already)

    def discard(self, repo, info):
        self._enter("discard", info.path, info.commit)
        if self.discard_error:
            raise self.discard_error

    def check_deployed(self, repo, post, now, deadline, interval):
        self._enter("check_deployed", post.path, deadline, interval)
        self.deployed_at = now
        error = self.deploy_errors.pop(0) if self.deploy_errors else None
        if error:
            raise error
        year, month, day, rest = Path(post.path).stem.split("-", 3)
        return DeployResult(f"https://example.invalid/chanceblog/posts/{year}/{month}/{day}/{rest}/", "확인 기록")


def fake_git(cwd, args, timeout=0, input_bytes=None):
    """doctor 의 `git --version` 같은 호출용 가짜 git."""
    return GitResult(0, "git version 9.9.9\n", "")


def make_ctx(tmp, *, backend=None, clock=None, repo="chanceblog", git=None):
    """임시 폴더 안의 데이터 폴더·설정으로 Context 를 만든다. 환경 변수는 비워 둔다(진짜 환경의 저장소 설정이 새어 들지 않게)."""
    root = Path(tmp) / "data"
    workspace = Workspace(root)
    settings = Settings(workspace.settings_path)
    if repo:
        settings.save_repo_path(str(Path(tmp) / repo))
        (Path(tmp) / repo / ".git").mkdir(parents=True, exist_ok=True)       # 가짜 저장소 폴더에도 `.git` 폴더가 있다(진짜 clone 처럼) — 저장소 잠금 파일은 그 안에 만들어진다(진짜 git 시험의 저장소는 이미 진짜 `.git` 이 있다)
    return Context(workspace, settings, backend if backend is not None else FakeBackend(), git or fake_git, gitrepo.EXPECTED_ORIGIN, clock or Clock(), "", {})


def make_approved(ctx, *, title="에너지 절약 습관", text=None, params=KO_PARAMS):
    """글을 만들고 검토 요청 → 승인까지 해 둔다(Pages). 프로젝트 번호를 돌려준다."""
    view = projects.new_project(ctx, title, text or ko_text())
    review.request_review(ctx, view.project_id, "github_pages", pages=params)
    review.grant_approval(ctx, view.project_id, "github_pages")
    return view.project_id


def run_cli(ctx, *argv, env=None):
    """명령줄을 같은 프로세스에서 돌린다 → (종료 코드, 표준 출력, 표준 오류)."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), out=out, err=err, ctx=ctx, env=env)
    return code, out.getvalue(), err.getvalue()


def status_of(ctx, project_id, platform="github_pages"):
    return projects.show_project(ctx, project_id).variant(platform).status


# ---- 진짜 git 시험 저장소 --------------------------------------------------------------------------------------------------------
LOCAL_ORIGIN = re.compile(r".*origin\.git/?$")
CONFIG = 'url: "https://example.invalid"\nbaseurl: "/chanceblog"\ntimezone: Asia/Seoul\npermalink: /posts/:year/:month/:day/:title/\n'


def git(cwd, *args):
    done = subprocess.run(["git", "-c", "core.longpaths=true", "-c", "core.quotePath=false", "-C", str(cwd), *args], capture_output=True)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr.decode('utf-8', 'replace')}")
    return done.stdout.decode("utf-8").strip()


def commit_file(repo, name, text, message="x"):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    git(repo, "add", "--", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)


def blob(repo, spec):
    """`rev:경로` 의 파일 내용(바이트 그대로 → 글자). 없으면 None."""
    done = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", spec], capture_output=True)
    return done.stdout.decode("utf-8") if done.returncode == 0 else None


class GitSandbox:
    """로컬 bare 저장소(origin)와 그것을 받은 작업 폴더(work)를 한 번 만들어 두고, 시험마다 복사해 쓴다(진짜 git — 한 번에 몇 초 걸린다)."""

    def __init__(self):
        self.shared = tempfile.TemporaryDirectory()
        self.base = Path(self.shared.name) / "base"
        self.base.mkdir()
        origin = self.base / "origin.git"
        git(self.base, "init", "-q", "--bare", str(origin))
        git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
        git(self.base, "clone", "-q", str(origin), "work")
        work = self.base / "work"
        git(work, "config", "core.autocrlf", "false")
        git(work, "checkout", "-q", "-B", "main")
        commit_file(work, "README.md", "블로그\n")
        commit_file(work, "_posts/2026-10-18-KR-225949.md", "---\nlayout: post\n---\n옛 글\n")
        commit_file(work, "_config.yml", CONFIG)
        git(work, "push", "-q", "-u", "origin", "main")

    def cleanup(self):
        self.shared.cleanup()

    def copy_into(self, tmp):
        """tmp 안에 새 origin·work 를 만든다 → (origin 폴더, work 폴더)."""
        target = Path(tmp) / "t"
        shutil.copytree(self.base, target)
        origin, work = target / "origin.git", target / "work"
        git(work, "remote", "set-url", "origin", str(origin))
        git(work, "config", "user.name", "운영자")
        git(work, "config", "user.email", "operator@example.com")
        git(work, "config", "commit.gpgsign", "false")
        return origin, work


class Spy:
    """진짜 git 을 부르되 호출을 기록하고, 지정한 명령은 가짜로 실패시킨다."""

    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    def __call__(self, cwd, args, timeout=gitrepo.DEFAULT_TIMEOUT, input_bytes=None):
        self.calls.append(list(args))
        if args[0] in self.fail:
            return GitResult(128, "", "fatal: unable to access 'https://github.com/shine88pc/chanceblog.git/': Could not resolve host: github.com")
        return gitrepo.run_git(cwd, args, timeout, input_bytes)

    def commands(self):
        return [call[0] for call in self.calls]


def tree_snapshot(root):
    """폴더 안 모든 파일의 (상대 경로, 바이트) — `.git` 안은 빼고. 앞뒤 비교로 '아무것도 쓰지 않았다' 를 본다."""
    root = Path(root)
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file() and ".git" not in path.relative_to(root).parts}


def fetcher_open(url, limit=0, headers=None):
    return VERIFY.Resp(200, b"", {}, "")


def fetcher_closed(url, limit=0, headers=None):
    return VERIFY.Resp(404, b"", {}, "")


class FakeWorld:
    """가짜 요청기·가짜 시계(배포 확인용) — 글 주소로 가는 요청이 open_after 번째부터 200 을 돌려준다."""

    def __init__(self, open_after=1):
        self.open_after = open_after
        self.requests = []
        self.sleeps = []
        self.now = 0.0

    def fetcher(self, url, limit=0, headers=None):
        self.requests.append(url)
        if url.split("?")[0].endswith("posts.json"):
            return VERIFY.Resp(404, b"", {}, "")
        mine = sum(1 for item in self.requests if "KR-103012" in item)
        return VERIFY.Resp(200 if mine >= self.open_after else 404, b"", {}, "")

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self):
        return self.now


def env_without_repo():
    return {key: value for key, value in os.environ.items() if key not in ("CHANCEBLOG_LOCAL_REPO", "CHANCEBLOG_DESKTOP_DATA")}
