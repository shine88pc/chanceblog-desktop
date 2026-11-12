"""외부 어댑터 등록부와 이 빌드의 기본 backend(PCSEC1 H3 — 외부 Write 완전 비활성의 둘째 겹, docs/DECISIONS.md).

외부에 쓰는 어댑터(원격 git 으로 올리는 것·Blogger·네이버 자동화 …)는 이 등록부에 **꽂아야만** 쓰인다. **이 빌드는 아무것도 꽂지 않는다** — `register` 를 부르는
코드가 `src/` 어디에도 없다(시험이 소스에서 확인한다). 그래서 `Context` 의 기본 backend 는 언제나 `LocalOnlyBackend` 이고, 기본 git 실행기는 `refusing_git` 이다:

  · `LocalOnlyBackend` — 연결한 chanceblog 폴더를 **파일로만** 읽는다(`.git` 폴더의 설정 파일에서 origin 주소를, `HEAD` 파일에서 브랜치를 읽는다 — git 을 부르지 않는다).
    원격에 닿거나 하위 프로세스를 띄우는 메서드(올리기·commit·되돌리기·공개 확인·올리기 점검)는 `EXTERNAL_WRITE_DISABLED` 로 거절한다.
  · `refusing_git` — 어떤 git 호출도 하위 프로세스를 띄우기 전에 거절한다. 이 PC 에 git 이 설치돼 있고 기존 Git 로그인이 있어도 이 앱은 그것을 쓸 수 없다.

켜는 길은 이 빌드에 없다(`capabilities.EXTERNAL_WRITE` 소스 상수·이 등록부·시험 — 켜려면 docs/DECISIONS.md D-343 의 PUBPR 제안 절차와 별도 검증). 시험은 `registered(...)` 로
임시로만 어댑터를 꽂는다.
"""
from __future__ import annotations

import contextlib
import re
from pathlib import Path

from ..errors import AppError
from ..publish import deploy
from ..publish.gitrepo import EXPECTED_ORIGIN, MAIN, RepoInfo
from ..security.mask import mask

KIND_PAGES_GIT = "pages_git"                  # 연결한 chanceblog 저장소에 git 으로 올리는 어댑터(`service/backend.py` 의 `GitPagesBackend`)
KIND_BLOGGER = "blogger"                      # Blogger API 어댑터(없다 — 이 빌드에는 호출 코드가 없다)
KIND_NAVER_PUBLISH = "naver_publish"          # 네이버 자동 로그인·게시 어댑터(만들지 않는다 — 네이버는 사람이 직접 글쓰기 페이지에서 올린다)
KINDS = (KIND_PAGES_GIT, KIND_BLOGGER, KIND_NAVER_PUBLISH)
_ADAPTERS = {}


def disabled(operation):
    """'이 시험 버전에서는 꺼져 있다' 는 거절 오류(오류 코드 EXTERNAL_WRITE_DISABLED)."""
    return AppError("EXTERNAL_WRITE_DISABLED", {"작업": operation})


def refusing_git(cwd=None, args=(), timeout=None, input_bytes=None):
    """`Context.git` 의 기본값 — 어떤 git 호출도 하위 프로세스를 띄우기 전에 거절한다(읽기 전용 명령도 마찬가지다)."""
    raise disabled("git 실행")


def register(kind, factory):
    """어댑터를 꽂는다. **이 빌드의 어느 코드도 부르지 않는다**(시험이 `src/` 에 이 호출이 없음을 못박는다) — 시험은 `registered` 를 쓴다."""
    if kind not in KINDS:
        raise ValueError(f"모르는 어댑터 종류: {kind!r}")
    if not callable(factory):
        raise ValueError("어댑터는 부를 수 있는 공장 함수여야 한다")
    _ADAPTERS[kind] = factory


def unregister(kind):
    _ADAPTERS.pop(kind, None)


@contextlib.contextmanager
def registered(kind, factory):
    """시험용 — `with` 안에서만 어댑터를 꽂고 나올 때 원래대로 돌린다."""
    before = _ADAPTERS.get(kind)
    register(kind, factory)
    try:
        yield
    finally:
        if before is None:
            unregister(kind)
        else:
            _ADAPTERS[kind] = before


def registered_kinds():
    """지금 꽂힌 어댑터 종류들(이 빌드는 늘 빈 목록)."""
    return tuple(sorted(_ADAPTERS))


def pages_backend(*, git=None, expected_origin=None, fetcher=None, sleep=None, monotonic=None):
    """`Context.backend` 의 기본값 — 꽂힌 `pages_git` 어댑터가 없으면(이 빌드는 늘 없다) `LocalOnlyBackend`."""
    origin = expected_origin or EXPECTED_ORIGIN
    factory = _ADAPTERS.get(KIND_PAGES_GIT)
    if factory is None:
        return LocalOnlyBackend(expected_origin=origin)
    return factory(git=git, expected_origin=origin, fetcher=fetcher, sleep=sleep, monotonic=monotonic)


# ---- 파일로만 읽는 점검 ---------------------------------------------------------------------------------------------------
_REMOTE_ORIGIN = re.compile(r'^\s*\[\s*remote\s+"origin"\s*\]\s*$', re.IGNORECASE)
_ANY_SECTION = re.compile(r"^\s*\[")
_URL_LINE = re.compile(r"^\s*(?:push)?url\s*=\s*(.+?)\s*$", re.IGNORECASE)
_HEAD_REF = re.compile(r"^ref:\s*refs/heads/(.+?)\s*$")
_MAX_CONFIG_BYTES = 1_000_000


def _origin_urls(config_text):
    """`.git/config` 의 `[remote "origin"]` 절에 있는 받는 주소·올리는 주소(git 을 부르지 않고 글자로 읽는다)."""
    urls, inside = [], False
    for line in config_text.splitlines():
        if _REMOTE_ORIGIN.match(line):
            inside = True
            continue
        if _ANY_SECTION.match(line):
            inside = False
            continue
        if inside:
            found = _URL_LINE.match(line)
            if found:
                urls.append(found.group(1).strip().strip('"'))
    return urls


def _read_small(path):
    try:
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            raise AppError("PAGES_LOCAL_REPO_INVALID", detail="git 설정 파일이 너무 크다")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="git 설정 파일을 읽을 수 없다") from None


def inspect_folder(path, expected_origin=EXPECTED_ORIGIN):
    """폴더가 연결할 수 있는 chanceblog 저장소인지 **파일만 읽어** 본다(git 을 부르지 않는다 — 하위 프로세스 0·원격 0).
    순서: 저장소 폴더인가(`.git` 폴더) → origin 이 chanceblog 인가(PAGES_LOCAL_REPO_INVALID) → main 브랜치인가(PAGES_LOCAL_REPO_NOT_MAIN).
    저장하지 않은 변경은 확인하지 않는다(git 이 있어야 알 수 있다 — 이 빌드는 글을 올리지 않으므로 연결한 폴더는 읽기만 한다)."""
    if path is None or not str(path).strip():
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="폴더가 지정되지 않았다")
    root = Path(path)
    if not root.is_dir():
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="폴더가 없다")
    git_dir = root / ".git"
    if not git_dir.is_dir():
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail="git 저장소의 맨 위 폴더가 아니다(.git 폴더가 없다 — 작업 트리 형태는 이 시험 버전이 확인하지 않는다)")
    urls = _origin_urls(_read_small(git_dir / "config"))
    wrong = [url for url in urls if not expected_origin.match(url)]
    if not urls or wrong:
        raise AppError("PAGES_LOCAL_REPO_INVALID", detail=f"origin 이 chanceblog 가 아니다: {mask((wrong or ['(없음)'])[0])[:200]}")
    head = _read_small(git_dir / "HEAD").strip()
    found = _HEAD_REF.match(head)
    branch = found.group(1) if found else "(분리된 HEAD)"
    if branch != MAIN:
        raise AppError("PAGES_LOCAL_REPO_NOT_MAIN", {"브랜치": branch})
    return RepoInfo(root, mask(urls[0]), branch, "")


def _local_duplicates(repo, post):
    root = Path(repo)
    stem = Path(post.path).stem
    posts = root / "_posts"
    if not posts.is_dir():
        return []
    return sorted(entry.relative_to(root).as_posix() for entry in posts.rglob(stem + ".*"))


def _local_same_content(repo, text):
    root = Path(repo)
    wanted = text.replace("\r\n", "\n").encode("utf-8")
    posts = root / "_posts"
    found = []
    if posts.is_dir():
        sizes = (len(wanted), len(wanted) + wanted.count(b"\n"))
        for entry in sorted(posts.rglob("*")):
            if entry.is_file() and entry.stat().st_size in sizes and entry.read_bytes().replace(b"\r\n", b"\n") == wanted:
                found.append(entry.relative_to(root).as_posix())
    return found


class LocalOnlyBackend:
    """`Context.backend` 의 기본값 — 파일만 읽고, 원격에 닿거나 하위 프로세스를 띄우는 일은 모두 거절한다(`GitPagesBackend` 와 같은 메서드 이름)."""

    def __init__(self, *, expected_origin=EXPECTED_ORIGIN):
        self.expected_origin = expected_origin
        self.git = refusing_git
        self.progress = None               # 명령줄이 진행 알림 함수를 달아 두는 자리(이 backend 는 기다릴 일이 없다)

    # ---- 파일로만 읽는 일 ------------------------------------------------------------------------------------------------
    def inspect(self, repo):
        return inspect_folder(repo, self.expected_origin)

    def expected_url(self, repo, post, now):
        """글의 공개 주소(네트워크 없이 Jekyll permalink 로 계산 — `_config.yml` 파일만 읽는다)."""
        return deploy.expected_url(repo, post.path, post.text, now=now)

    def duplicates(self, repo, post):
        return _local_duplicates(repo, post)

    def same_content(self, repo, text):
        return _local_same_content(repo, text)

    # ---- git 이 있어야 알 수 있는 것은 '알 수 없음' 으로 답한다(읽기 전용 질문이 하위 프로세스를 띄우지 않는다) ------------------------------------------
    def unpushed_count(self, repo):
        return None

    def unpushed_made_by_app(self, repo):
        return 0

    def on_remote(self, repo, path):
        return False

    def post_in_head(self, repo, path):
        return False

    def orphan_commit(self, repo, text, category, lang):
        return None

    # ---- 거절 ---------------------------------------------------------------------------------------------------------------
    def head_commit(self, repo):
        raise disabled("저장소 HEAD 읽기")

    def current_commit(self, repo, path):
        raise disabled("저장소 HEAD 읽기")

    def check_push_access(self, repo):
        raise disabled("올리기 권한 점검")

    def commit(self, repo, post, title):
        raise disabled("글 기록(commit)")

    def push(self, repo, post):
        raise disabled("원격 main 에 올리기")

    def discard(self, repo, info):
        raise disabled("올리지 않은 글 기록 되돌리기")

    def check_deployed(self, repo, post, now, deadline, interval):
        raise disabled("공개 주소 확인")
