"""글 검토 화면의 가짜 공급자 — `--sample`·시험·사진이 쓴다. **메모리에서만** 일한다: 파일·보관소·서비스를 부르지 않으므로 가져오기·검토·승인을 해도 이 PC 에 아무것도 남지 않는다. 글·이름은 모두 지어낸 예시다.

글의 상태 규칙은 서비스와 같은 `ContentProject`(`content/model.py` — 순수 자료)가 심판이다(승인은 현재 판의 렌더링에만, 고치면 풀림). 검사 결과의 비밀 모양·건강 효과 단정은 실제 어댑터와 **같은 함수**(`post_rules`)를 쓴다.
발행 전 검사(관문)만은 서비스의 `service/gate.py` 를 가져올 수 없어(화면 층은 서비스를 모른다) 작은 흉내다: 본문 분량·HTML 태그·이 PC 의 폴더 경로 세 가지만 본다. 시험이 이 흉내가 실제 서비스와 같은 코드를 내는지 견준다.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from ...content import status as st
from ...content.model import ContentProject
from ...errors import AppError
from ...render.markdown import html_to_markdown
from . import post_rules as rules
from .jobs import JobCancelled
from .posts import (KINDS, NAVER_PLATFORMS, PAGES, PLATFORMS, PlatformStatus, PostDetail, PostFailure, PostOutcome, PostRow, PostsData, PostsProvider, ReviewReport, SimilarityInfo)
from .text import T

SCENARIOS = ("normal", "empty", "error", "many", "partial", "offline")
BASE = datetime(2026, 11, 2, 1, 30, 12, tzinfo=timezone.utc)         # 예시의 '처음 시각' — 쓰기마다 1초씩 늦어진다(시계를 읽지 않는다)
LENGTH_MIN = {"ko": 1000, "en": 1500}                               # 서비스 관문의 본문 분량 기준(시험이 같은지 견준다)
SENTENCE = "에너지 절약은 작은 습관에서 시작되며 매일 조금씩 실천하면 생활비와 환경 모두에 도움이 됩니다. "
_HTML = re.compile(r"<(/?[A-Za-z][A-Za-z0-9-]{0,40})(?=[\s/>])[^<>]{0,2000}>|<[!?]")
_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]", re.IGNORECASE)


def sample_text(chars=1500):
    """분량 기준을 넘는 예시 본문(소제목·문단·목록 포함)."""
    paragraphs = ["## 작은 습관부터", (SENTENCE * (chars // len(SENTENCE) + 1)).strip(), "- 쓰지 않는 전등 끄기\n- 대기 전력 줄이기", "### 마무리", SENTENCE.strip()]
    return "\n\n".join(paragraphs)


def fake_gates(markdown, lang):
    """서비스 관문의 흉내 — 본문 분량(`LEN_BODY`)·HTML 태그(`RAW_HTML`)·이 PC 의 폴더 경로(`LOCAL_PATH`) → (사유 줄들, 참고 줄들). 줄 모양은 서비스와 같은 `[코드] 설명` 이다."""
    reasons = []
    readable = len(re.sub(r"\s+", "", re.sub(r"[`*_>#|\x7e-]", " ", markdown)))
    if readable < LENGTH_MIN.get(lang, 1000):
        reasons.append(f"[LEN_BODY] 본문 {readable}자 (최소 {LENGTH_MIN.get(lang, 1000)}자)")
    if _HTML.search(markdown):
        reasons.append("[RAW_HTML] 원고에 HTML 태그가 있다")
    if _PATH.search(markdown):
        reasons.append("[LOCAL_PATH] 글에 이 PC 의 폴더 경로가 들어 있다")
    return tuple(reasons), ()


def _pause(seconds, cancelled):
    end = time.monotonic() + seconds
    while seconds and time.monotonic() < end:
        if cancelled():
            raise JobCancelled()
        time.sleep(min(0.02, max(0.0, end - time.monotonic())))


def _stamp(tick):
    return (BASE + timedelta(seconds=tick)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _newest_first(rows):
    return sorted(rows, key=lambda row: (str(row.updated_at), row.project_id), reverse=True)


class FakePostsProvider(PostsProvider):
    """메모리에서만 일하는 가짜 공급자 — 가져오기·검토·승인·승인 취소도 메모리 안에서만 바뀐다. `fail` 은 이름(메서드)마다 그대로 던질 실패(시험), `profiles` 는 네이버 프로필이 있는 블로그들이다."""
    sample = True

    def __init__(self, scenario="normal", delay=0.0, *, profiles=NAVER_PLATFORMS, fail=None):
        if scenario not in SCENARIOS:
            raise ValueError(scenario)
        self.scenario, self.delay, self.profiles, self.fail = scenario, delay, tuple(profiles), dict(fail or {})
        self.calls = []
        self.projects = {}
        self.tick = 0
        self.counter = 0
        self.stored = {}                                                   # (글 번호, 플랫폼) → 검토 때 저장한 렌더링 글(실제 서비스의 `rendered`)
        self._seed()

    # ---- 예시 만들기 ----
    def _next_stamp(self):
        self.tick += 1
        return _stamp(self.tick)

    def _new_id(self):
        self.counter += 1
        return f"exm{self.counter:05d}"

    def add_post(self, title, markdown, *, references=(), assets=()):
        """예시·시험이 글을 하나 더한다(검사 없이 — 키 모양이 든 글도 만들 수 있다). 글 번호를 돌려준다."""
        project = ContentProject.new(title, markdown, tuple(references), tuple(assets), project_id=self._new_id(), now=self._next_stamp())
        self.projects[project.project_id] = project
        return project.project_id

    def _seed(self):
        if self.scenario in ("empty", "error"):
            return
        count = 130 if self.scenario == "many" else 4
        for number in range(count):
            self.add_post(f"예시 글 {number + 1:03d}" if self.scenario == "many" else f"예시 글 {'가나다라'[number]}", sample_text() if number % 4 != 1 else "## 짧은 글\n\n아주 짧은 예시 글이에요.")
        if self.scenario != "many":
            ids = list(self.projects)
            self.projects[ids[0]].set_rendered(PAGES, "예시 글 파일", now=self._next_stamp())
            self.projects[ids[0]].transition(PAGES, st.REVIEW_REQUIRED, now=self._next_stamp())

    def edit(self, project_id, **changes):
        """바깥(명령줄·다른 창)에서 글이 고쳐진 것을 흉내 낸다 — 판이 오르고 승인·검토가 풀린다."""
        project = self.projects[project_id]
        return project.edit(now=self._next_stamp(), **changes)

    # ---- 읽기 ----
    def _enter(self, name, cancelled):
        self.calls.append(name)
        _pause(self.delay, cancelled)
        if name in self.fail:
            raise self.fail[name]

    def _rows(self):
        rows = [PostRow(project.project_id, project.title, project.revision, project.updated_at, tuple((key, project.variants[key].status) for key in PLATFORMS), "") for project in self.projects.values()]
        if self.scenario == "partial":
            rows.append(PostRow("exmbroken", "", 1, "2026-11-01T00:00:00Z", (), "STORE_CORRUPT"))
        return tuple(_newest_first(rows))

    def load_posts(self, progress, cancelled):
        self._enter("load_posts", cancelled)
        if self.scenario == "error":
            raise PostFailure(T["post_error_desc"], code="SAMPLE_POSTS_UNREADABLE", kind="corrupt")
        return PostsData(self._rows(), tuple(self.profiles), "ok", True, self.scenario == "offline")

    def _detail(self, project):
        platforms = tuple(PlatformStatus(key, project.variants[key].status, project.variants[key].rendered_revision, bool(project.variants[key].rendered), project.variants[key].error_code or "")
                          for key in PLATFORMS)
        return PostDetail(project.project_id, project.title, project.revision, project.created_at, project.updated_at, platforms,
                          rules.build_preview(project.source_content, refs=len(project.references), assets=len(project.assets)), True)

    def _project(self, project_id):
        project = self.projects.get(project_id)
        if project is None:
            raise PostFailure(T["post_fail_notfound"], code="CONTENT_NOT_FOUND", kind="notfound")
        return project

    def load_post(self, project_id, progress, cancelled):
        self._enter("load_post", cancelled)
        return self._detail(self._project(project_id))

    def read_import_file(self, path, progress, cancelled):
        """가짜 파일 읽기 — 파일을 열지 않는다. 이름이 `.bad` 로 끝나면 거절, `cp949` 가 들어 있으면 CP949 로 읽은 것처럼 알린다."""
        from .posts import ImportFile
        self._enter("read_import_file", cancelled)
        name = str(path)
        if name.endswith(".bad"):
            raise PostFailure(T["post_fail_file"].format(why="글 파일이 아닌 것 같아요"), code="CONTENT_INVALID", kind="file")
        text = sample_text()
        return PostOutcome("file", file=ImportFile(rules.title_of(name), text, len(text), "cp949" if "cp949" in name else "utf-8"))

    # ---- 쓰기 ----
    def import_post(self, request, progress, cancelled):
        self._enter("import_post", cancelled)
        if request.kind not in KINDS:
            raise PostFailure(T["post_fail_input_plain"], code="CONTENT_INVALID", kind="input")
        title, body = request.title.strip(), request.body
        if not title or not body.strip():
            raise PostFailure(T["post_fail_input"].format(field=T["post_im_title_label"] if not title else T["post_im_body_label"]), code="CONTENT_INVALID", kind="input")
        spots = rules.secret_spots(title, body)
        if spots:
            raise PostFailure(T["post_fail_secret"].format(where=f"{spots[0][0]} {spots[0][1]}번째 줄", kinds=spots[0][2]), code="SECRET_SHAPE_FOUND", kind="secret")
        markdown = html_to_markdown(body) if request.kind == "html" else body
        if not markdown.strip():
            raise PostFailure(T["post_fail_input"].format(field=T["post_im_body_label"]), code="CONTENT_INVALID", kind="input")
        project_id = self.add_post(title, markdown)
        return PostOutcome("imported", self._detail(self.projects[project_id]))

    def _guard_platform(self, platform):
        if platform not in PLATFORMS:
            raise PostFailure(T["post_fail_input_plain"], code="CONTENT_INVALID", kind="input")
        if platform in NAVER_PLATFORMS and platform not in self.profiles:
            raise PostFailure(T["post_fail_profile"], code="NAVER_PROFILE_MISSING", kind="profile")

    def review_post(self, request, progress, cancelled):
        self._enter("review_post", cancelled)
        project, platform = self._project(request.project_id), request.platform
        self._guard_platform(platform)
        lang = request.pages.lang if platform == PAGES and request.pages is not None else "ko"
        if platform == PAGES and request.pages is None:
            raise PostFailure(T["post_fail_input_plain"], code="CONTENT_INVALID", kind="input")
        variant = project.variant(platform)
        try:
            now = self._next_stamp()
            if variant.status == st.COPY_COMPLETED:
                project.transition(platform, st.READY_TO_COPY, now=now)
            if variant.status in (st.APPROVED, st.READY_TO_COPY):
                project.transition(platform, st.REVIEW_REQUIRED, now=now)
            rendering = f"{platform}:{project.revision}:{project.source_content}"
            project.set_rendered(platform, rendering, now=now)
            project.transition(platform, st.REVIEW_REQUIRED, now=now)
        except AppError:
            raise PostFailure(T["post_fail_state"], code="STATUS_TRANSITION_INVALID", kind="state") from None
        self.stored[(project.project_id, platform)] = lang
        reasons, warnings = fake_gates(project.source_content, lang) if platform == PAGES else ((), ())
        similarity = self._similarity(project, platform)
        summary = (T["post_summary_pages"].format(category=rules.shown(request.pages.category, 60), lang=T["post_lang_" + lang], kb=max(1, len(project.source_content.encode("utf-8")) // 1024)),) if platform == PAGES             else (T["post_summary_naver"].format(title=rules.shown(project.title, 60), chars=f"{len(project.source_content):,}", paragraphs=project.source_content.count(chr(10) * 2) + 1),)
        report = ReviewReport(project.project_id, platform, project.revision, project.variants[platform].status, not reasons, rules.unique_codes(reasons), tuple(rules.shown(item, 400) for item in reasons),
                              warnings, summary, similarity, rules.health_of(project.title, project.source_content), rules.secret_spots(project.title, project.source_content, project.references, project.assets), True)
        return PostOutcome("reviewed", self._detail(project), report)

    def _similarity(self, project, platform):
        """네이버 두 블로그에 같은 글이 있으면 '많이 비슷함'(흉내) — 서로 다른 글이면 충분히 다름. 다른 블로그의 검토가 없으면 None."""
        if platform not in NAVER_PLATFORMS:
            return None
        other = NAVER_PLATFORMS[1] if platform == NAVER_PLATFORMS[0] else NAVER_PLATFORMS[0]
        if not project.variants[other].rendered:
            return None
        same = project.variants[other].rendered.split(":", 2)[-1] == project.source_content
        return SimilarityInfo("high" if same else "ok", 1.0 if same else 0.1, ("제목·본문 유사도 100%",) if same else ())

    def approve_post(self, request, progress, cancelled):
        self._enter("approve_post", cancelled)
        project, platform = self._project(request.project_id), request.platform
        self._guard_platform(platform)
        if project.revision != request.revision:
            raise PostFailure(T["post_fail_stale"], code="STALE", kind="stale")
        variant = project.variant(platform)
        if variant.status != st.REVIEW_REQUIRED:
            raise PostFailure(T["post_fail_state"], code="STATUS_TRANSITION_INVALID", kind="state")
        if rules.text_blocks(project.title, project.source_content, project.references, project.assets):
            raise PostFailure(T["post_fail_blocked"], code="REVIEW_BLOCKED", kind="gate")
        lang = self.stored.get((project.project_id, platform), "ko")
        if platform == PAGES and fake_gates(project.source_content, lang)[0]:
            raise PostFailure(T["post_fail_gate"], code="CHECK_FAILED", kind="gate")
        similarity = self._similarity(project, platform)
        if similarity is not None and similarity.blocks:
            raise PostFailure(T["post_fail_similarity"], code="NAVER_SIMILARITY_HIGH", kind="similarity")
        try:
            project.transition(platform, st.APPROVED if platform == PAGES else st.READY_TO_COPY, now=self._next_stamp())
        except AppError:
            raise PostFailure(T["post_fail_state"], code="STATUS_TRANSITION_INVALID", kind="state") from None
        return PostOutcome("approved", self._detail(project))

    def revoke_post(self, request, progress, cancelled):
        self._enter("revoke_post", cancelled)
        project, platform = self._project(request.project_id), request.platform
        self._guard_platform(platform)
        try:
            project.transition(platform, st.REVIEW_REQUIRED, now=self._next_stamp())
        except AppError:
            raise PostFailure(T["post_fail_state"], code="STATUS_TRANSITION_INVALID", kind="state") from None
        return PostOutcome("revoked", self._detail(project))


__all__ = ["FakePostsProvider", "SCENARIOS", "fake_gates", "sample_text"]
