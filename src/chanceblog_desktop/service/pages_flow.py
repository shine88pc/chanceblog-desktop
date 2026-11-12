"""GitHub Pages 에 올리기 — 이 앱에서 가장 조심해야 하는 흐름(연결한 chanceblog 의 `main` 에 실제로 올라간다 — 변경 등급 T2).

지키는 것(하나씩 일부러 어겨 보는 변이 점검으로도 확인한다):
  1) **확인 없이는 올리지 않는다**(AGENTS.md 규칙 7): `plan_pages_publish`/`preview_publish` 는 아무것도 쓰지 않는 미리 보기(dry run)이고, `run_pages_publish` 는 `confirmed=True` 가 없으면 CONFIRMATION_REQUIRED 로
     아무것도 하지 않는다. commit 도 push 도 그 뒤에만 한다.
  2) **승인된 글만, 승인한 그대로**: 상태가 APPROVED 이고 승인한 렌더링이 현재 원고의 판과 같을 때만 새로 올린다. 올리는 내용은 다시 만든 것이 아니라 승인한 렌더링(`variant.rendered`) 그대로다.
  3) **검사를 통과해야 한다**(fail closed): 게이트(`service/gate.py` — 파일 모양·키 모양 문자열·핵심 코드 검사·로컬 경로)와 연결한 저장소 확인(`inspect_repo`)과 같은 주소(slug) 글 확인을 미리 한다.
  4) **상태는 사실을 따라간다**: APPROVED → COMMITTED(이 PC 에 기록) → PUSHED(원격 main 에 올림) → PUBLISHED(공개 주소가 열림을 확인). 한 단계를 마칠 때마다 바로 저장하고,
     멈춘 곳에서 같은 명령으로 이어간다. 공개 주소가 아직 안 열리면(`PAGES_DEPLOY_NOT_VISIBLE`) 상태는 PUSHED(올림·공개 확인 대기)로 두고 `check-deploy` 로 다시 확인한다 — 상태를 망가뜨리지 않는다.
  5) **실패해도 일관되고 되돌릴 수 있다**: commit 전에 막히면 저장소는 처음 그대로(commit_post 가 치운다). push 가 막히면 COMMITTED 로 남겨 이어서 올리게 하거나 `cancel_pages_publish` 로 글 기록을 되돌린다
     (같은 주소의 글이 먼저 올라가 있으면 되돌릴 수밖에 없어 자동으로 되돌리고 PUBLISH_FAILED 로 남긴다). 되돌릴 때는 `discard_commit` 이 허락하는 경우에만 한다(허락하지 않으면 그대로 두고 알린다).
     commit 뒤에 상태를 저장하지 못하면 방금 만든 commit 을 되돌린다(저장소와 상태가 어긋난 채 남지 않게).
  6) **같은 글을 두 곳에서 동시에 올리지 못한다**: 올리기·되돌리기·공개 확인은 글마다 잠금(`service/lock.py`)을 먼저 잡고, 못 잡으면 아무것도 바꾸지 않고 PUBLISH_IN_PROGRESS 로 멈춘다.
     실패 경로가 발행 기록을 지울 때는 **이 실행이 쓴 기록과 똑같을 때만** 지운다(다른 실행이 쓴 기록을 지워 올라간 글을 잊는 일이 없게).
  7) **commit 직후에 멈춰도 도구로 복구된다**: commit 은 했는데 발행 기록·COMMITTED 를 저장하기 전에 프로그램이 죽으면 '승인됨 + 올리지 않은 commit 하나 + 기록 없음' 이 남는다. 그 commit 이 **이 글의 승인한 렌더링을 그대로 더한 앱의 commit 하나뿐**이면
     같은 명령이 그것을 이어받아(기록을 만들고 COMMITTED 로 이어서 push) 올리거나, `--cancel --yes` 가 `discard_commit` 의 조건 안에서 되돌린다. 조금이라도 다르면 아무것도 하지 않는다(새 commit 은 PAGES_LOCAL_REPO_DIVERGED 로 멈춘다).
  8) **승인한 글만 올라간다**: commit 한 뒤 push 하기 전에 원고를 고쳤으면(승인은 풀렸는데 commit 은 남아 있다) push 하지 않고 PUBLISH_CONTENT_CHANGED 로 멈춘다 — `--cancel --yes` 로 되돌린 뒤 다시 승인한다.
  9) **서로 다른 두 글이 같은 저장소에 동시에 올라가지 못한다**: commit·push·되돌리기 구간은 연결한 저장소마다 한 번에 한 작업(저장소 잠금 — 글 잠금을 잡은 다음에 잡는다, 순서 고정이라 서로 기다리며 멈추지 않는다)이고,
     다른 작업이 쥐고 있으면 `Context.lock_wait` 초 기다리다 PUBLISH_REPO_BUSY 로 물러난다(아무것도 바꾸지 않는다 — 같은 명령을 다시 실행하면 된다). 공개 확인을 기다리는 동안에는 저장소 잠금을 쥐지 않는다.
     저장소 잠금 파일은 그 저장소의 `.git` 안에 있어서 `--data-dir` 을 다르게 준 앱끼리도 서로를 안다. `.git` 에 잠금 파일을 만들 수 없으면 데이터 폴더로 물러서지 않고 올리지 않는다(FILE_WRITE_FAILED).
 10) **올리지 않은 commit 이 있으면 새 글을 올리지 않고 무엇을 해야 하는지 말한다**: 이어받기·두 글 겹침·앱이 모르는 commit 을 가려(`service/unpushed.py`) 정확한 안내 한 가지를 오류 세부에 싣는다(미리 보기도 같다).
 11) **같은 초의 파일 이름을 피한다**: 새 글의 파일 이름은 올리는 순간의 초로 정해지는데 바로 앞 글이 같은 초에 올라갔으면(저장소에 이미 있거나 올리는 중인 글이 쓰는 이름) 점검 단계에서 다음 초의 이름으로 정한다(최대 5번, 읽기만 한다).
이 모듈은 git 을 직접 쓰지 않는다 — `Context.backend`(기존 `publish/` 모듈)에 맡긴다. 강제 push 는 없다.
"""
from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from .. import capabilities
from ..content import status as st
from ..errors import UNEXPECTED, AppError
from ..render.pages import PagesPost, post_path
from . import unpushed
from .gate import require_gates, split_post
from .journal import STAGE_COMMITTED, STAGE_PUSHED, Journal, PublishRecord
from .lock import publish_lock, repo_lock
from .previews import PLATFORM_PAGES
from .projects import require_confirmation, resolve_id

STAGE_COMMIT, STAGE_ADOPT, STAGE_PUSH, STAGE_VERIFY, STAGE_DONE = "commit", "adopt", "push", "verify", "done"
DEFAULT_DEADLINE = 720          # 공개 확인을 기다리는 최대 시간(초) — 배포 확인 모듈의 기본값과 같다
DEFAULT_INTERVAL = 10
MAX_SECOND_PROBES = 5           # 파일 이름의 초가 이미 쓰였을 때 다음 초로 밀어 보는 최대 횟수(바로 앞 글이 같은 초에 올라간 경우)
_STAGE_OF = {st.APPROVED: STAGE_COMMIT, st.COMMITTED: STAGE_PUSH, st.PUSHED: STAGE_VERIFY, st.PUBLISHED: STAGE_DONE}


@dataclass(frozen=True)
class PagesPlan:
    """올리기 전에 확인한 것과 앞으로 할 일. 미리 보기(dry run)가 이것을 그대로 보여 준다."""
    project_id: str
    title: str
    status: str            # 시작할 때의 Pages 상태
    stage: str             # commit(새로 올림) · adopt(commit 직후 멈춘 것을 이어받음) · push(이어서 올림) · verify(공개 확인만) · done(이미 공개됨)
    path: str              # 만들(또는 이미 만든) 글 파일 경로
    category: str
    lang: str
    text: str
    size_bytes: int
    expected_url: str
    repo: str              # 연결한 폴더(화면에만 보인다 — 어디에도 저장하지 않는다)
    gates: object          # GateReport 또는 None(검사하지 않는 단계)
    actions: tuple         # 이 단계에서 할 일(쉬운 한국어)
    adopted: object = None  # adopt 단계에서 이어받을 commit(CommitInfo)
    now: object = None      # 파일 이름의 시각을 정한 때(같은 초의 이름을 피해 다음 초로 밀었으면 그 시각) — 공개 주소 계산에 같은 시각을 쓴다

    @property
    def post(self):
        return PagesPost(self.path, self.text, self.category, self.lang)

    def to_dict(self, *, with_text=False):
        data = {"project_id": self.project_id, "title": self.title, "status": self.status, "stage": self.stage, "path": self.path, "category": self.category, "lang": self.lang,
                "size_bytes": self.size_bytes, "expected_url": self.expected_url, "repo": self.repo, "gates": self.gates.to_dict() if self.gates else None, "actions": list(self.actions)}
        if with_text:
            data["text"] = self.text
        return data


@dataclass(frozen=True)
class PublishReport:
    project_id: str
    dry_run: bool
    plan: object                 # PagesPlan
    status: str                  # 끝났을 때의 Pages 상태
    steps: tuple                 # 실제로 한 일(쉬운 한국어)
    url: str                     # 공개를 확인한 주소(확인 전이면 예상 주소)
    verified: bool               # 공개 주소가 열리는 것을 확인했다
    pending_verification: bool   # 올렸지만 공개 확인이 끝나지 않았다(check-deploy 로 다시 확인)
    next_steps: tuple
    notes: tuple = ()

    def to_dict(self, *, with_text=False):
        return {"project_id": self.project_id, "dry_run": self.dry_run, "status": self.status, "steps": list(self.steps), "url": self.url, "verified": self.verified,
                "pending_verification": self.pending_verification, "next_steps": list(self.next_steps), "notes": list(self.notes), "plan": self.plan.to_dict(with_text=with_text)}


def _annotate(error, note):
    """오류의 세부(detail)에 '지금 어떤 상태인가' 를 덧붙인다 — 다음에 무엇을 해야 하는지 알 수 있게."""
    if note:
        error.detail = f"{error.detail} | {note}" if error.detail else note
    return error


@contextlib.contextmanager
def _noting(note):
    try:
        yield
    except AppError as error:
        _annotate(error, note)
        raise


@contextlib.contextmanager
def _repo_section(ctx, repo):
    """연결한 저장소에 쓰는(commit·push·되돌리는) 구간의 저장소 잠금. 다른 글이 같은 저장소에 올라가는 중이면 기다리다 물러난다(PUBLISH_REPO_BUSY — 아무것도 바꾸지 않았다).
    연결한 저장소가 없으면(repo 가 None) 잠글 것이 없다 — 이어지는 점검이 PAGES_LOCAL_REPO_INVALID 로 멈춘다."""
    if repo is None:
        yield None
        return
    with repo_lock(ctx, repo, progress=getattr(ctx.backend, "progress", None)) as lock:
        yield lock


def _lead(lock, rlock):
    """화면에 알릴 잠금 이야기 — 낡은 잠금을 넘겨받았다는 것(글 잠금과 저장소 잠금이 같은 멈춤의 흔적이면 한 번만)과, 다른 글이 끝나기를 기다렸다는 것."""
    notes = []
    taken = lock.taken_over or (rlock.taken_over if rlock is not None else "")
    if taken:
        notes.append(taken)
    if rlock is not None and rlock.waited >= 1:
        notes.append(f"다른 글을 올리는 작업이 끝나기를 {round(rlock.waited)}초 기다린 뒤 올렸습니다.")
    return tuple(notes)


def _stack_note(ctx, repo):
    """올리지 않은 commit 이 있을 때 해야 할 일의 정확한 안내(없거나 읽을 수 없으면 '' — 원래 오류가 그대로 나간다). 읽기만 한다."""
    try:
        return unpushed.action_text(unpushed.describe(ctx, repo))
    except AppError:
        return ""


def _refuse_unpushed(ctx, repo, *, stage):
    """새 글을 올리기 전(미리 보기 포함)에 앱이 올리다 멈춘 commit 이나 다른 commit 이 올리지 않은 채 있는지 본다 — 있으면 PAGES_LOCAL_REPO_DIVERGED 와 상황에 맞는 안내(읽기만 한다).
    이어서 올릴 글(push 단계)은 자기 commit 하나가 있는 것이 정상이라 둘 이상 쌓였을 때만 막는다."""
    situation = unpushed.describe(ctx, repo)
    if situation.ahead and (stage != STAGE_PUSH or situation.ahead >= 2):
        raise AppError("PAGES_LOCAL_REPO_DIVERGED", detail=f"올리지 않은 commit 이 {situation.ahead}개 있어 올리지 않는다 — {unpushed.action_text(situation)}")


def _missing_record(project_id, stage):
    """이어서 올리거나(COMMITTED)·공개 확인을 이어갈(PUSHED) 글인데 발행 기록 파일이 없다 → SETTINGS_INVALID(세부에 왜 이렇게 됐고 어떻게 하는지).
    올림(PUSHED)인데 기록이 없는 글은 `check-deploy`·`publish-pages`·`--cancel` 어느 쪽도 이을 수 없다 — 글 파일의 이름(올린 순간의 시각)은 기록에만 있어서다. 지웠다가 백업으로 되살리거나 오래된 백업으로
    되돌릴 때 생긴다(발행 기록은 백업에 들어 있지 않다). 어느 명령도 서로를 가리키지 않게 '지운다' 는 한 가지 출구를 말한다(올라간 글은 저장소에 그대로 있고 이 앱은 지우지 않는다)."""
    short = project_id[:8]
    if stage == STAGE_VERIFY:
        return AppError("SETTINGS_INVALID", {"파일": f"{project_id}.json"},
                        detail=("올림(PUSHED) 상태인데 공개 확인을 이어갈 발행 기록 파일이 없다 — 글을 지웠다가 백업으로 되살렸거나 오래된 백업으로 되돌렸을 때 생긴다. 앱은 올라간 글의 파일 이름을 기록으로만 알아서 "
                                f"공개 확인을 이어갈 수 없다(올라간 글은 저장소에 그대로 있다 — 공개 주소는 사이트에서 직접 확인한다). 이 글의 기록이 필요 없으면 `delete {short} --yes` 로 지운다"))
    return AppError("SETTINGS_INVALID", {"파일": f"{project_id}.json"}, detail="이어서 올릴 발행 기록 파일이 없다")


def _tidy_finished_record(journal, project_id):
    """공개된 글(PUBLISHED)에 발행 기록이 남아 있으면(기록을 지우기 직전에 프로그램이 멈춘 흔적 — 해롭지 않다) 그 기록만 지운다 → 알릴 말('' 이면 할 일 없었다). 읽을 수 없는 기록은 건드리지 않는다."""
    try:
        leftover = journal.read(project_id)
    except AppError:
        return ""
    if leftover is None:
        return ""
    return journal.remove(project_id, only=leftover) or "공개된 글에 남아 있던 발행 기록(지우기 직전에 멈춘 흔적)을 정리했습니다."


def _check_claims(store, journal, stem, url):
    """다른 글이 같은 공개 주소를 이미 쓰고 있지 않은가 — 이미 공개된 글의 주소, 그리고 올리는 중인 글의 파일 이름(날짜-언어-시각).
    새로 올리려는 글 자신은 승인됨(APPROVED) 상태라 발행 주소도 발행 기록도 없으므로 여기에 걸리지 않는다."""
    for summary in store.list():
        try:
            other = store.load(summary.project_id)
        except AppError:
            continue                # 읽을 수 없는 다른 글은 여기서 판단하지 않는다 — 같은 주소 글은 저장소(git) 쪽 확인이 다시 막는다
        variant = other.variant(PLATFORM_PAGES)
        if url and variant.published_url == url:
            raise AppError("DUPLICATE_SLUG", detail="다른 글이 같은 공개 주소로 이미 공개되어 있다")
        if variant.status in (st.COMMITTED, st.PUSHED):
            record = journal.read(summary.project_id)
            if record is not None and Path(record.path).stem == stem:
                raise AppError("DUPLICATE_SLUG", detail="올리는 중인 다른 글이 같은 주소(날짜-언어-시각)를 쓴다")


def _describe(stage, path, url, deadline):
    wait = f"최대 {max(deadline // 60, 1)}분"
    if stage == STAGE_COMMIT:
        return (f"연결한 chanceblog 저장소에 글 파일 1개를 만듭니다: {path}", "그 파일 하나만 기록(commit)합니다 — 다른 파일과 다른 변경은 건드리지 않습니다.",
                "원격(origin)의 main 에 올립니다(push) — 강제로 올리지 않고, 올리기 직전에 올릴 것이 이 글 하나뿐인지 다시 확인합니다.",
                f"올린 뒤 사이트에 반영되어 {url} 이 열리는지 확인합니다({wait}까지 기다립니다).", "파일 이름의 시각은 실제로 올리는 순간의 한국 시각으로 정해집니다(내용은 승인한 그대로입니다).")
    if stage == STAGE_ADOPT:
        return (f"이 PC 의 저장소에 이미 기록(commit)되어 있는 이 글({path})을 이어받습니다 — 앞서 올리다 기록 직후에 멈춘 것으로, 승인한 글과 내용이 똑같은 기록 하나뿐임을 확인했습니다. 새로 쓰거나 다시 기록하지 않습니다.",
                "이어받은 기록을 발행 기록 파일에 적고 '이 PC 에 기록함(COMMITTED)' 으로 바꾼 뒤, 원격(origin)의 main 에 올립니다(push) — 강제로 올리지 않고, 올리기 직전에 올릴 것이 이 글 하나뿐인지 다시 확인합니다.",
                f"올린 뒤 {url} 이 열리는지 확인합니다({wait}까지 기다립니다).")
    if stage == STAGE_PUSH:
        return (f"이 PC 의 저장소에 이미 기록해 둔 글({path})을 원격(origin)의 main 에 올립니다(push) — 새로 쓰거나 기록하지 않고, 강제로 올리지도 않습니다.",
                f"올린 뒤 {url} 이 열리는지 확인합니다({wait}까지 기다립니다).")
    if stage == STAGE_VERIFY:
        return (f"이미 올라간 글입니다. 공개 주소가 열리는지만 확인합니다: {url}",)
    return ("이미 공개된 글입니다 — 할 일이 없습니다.",)


def _outdated(variant, project):
    """commit 한 뒤(승인은 풀렸는데 commit 은 남은 상태)에 원고가 바뀌었는가 — 그렇다면 승인했던 옛 글을 몰래 올리지 않고 멈춘다(fail closed)."""
    if variant.rendered_revision != project.revision:
        return AppError("PUBLISH_CONTENT_CHANGED", {"현재 상태": variant.status},
                        detail=f"승인한 때의 원고 판은 {variant.rendered_revision}, 지금 원고는 판 {project.revision} 이다 — 이 PC 에 기록한 글(commit)은 승인한 옛 내용이다")
    return None


def plan_pages_publish(ctx, text_id, *, now=None, deadline=DEFAULT_DEADLINE):
    """올리기 전 점검(아무것도 쓰지 않는다 — 연결한 저장소·데이터 폴더·네트워크 모두). 올릴 수 없으면 이유를 AppError 로 낸다.

    새로 올릴 글(APPROVED)은 승인이 현재 판과 같은지·게이트·저장소 확인·같은 주소(slug) 확인·공개 주소 계산까지 하고, 이어서 올릴 글(COMMITTED)은 게이트·저장소 확인을 다시 하고(원고가 승인 뒤에 바뀌었으면 멈춘다),
    올라간 글(PUSHED)은 공개 주소 계산까지만 한다. 이미 공개된 글(PUBLISHED)은 할 일이 없다. 그 밖의 상태(승인 전·실패·다른 플랫폼 상태)는 STATUS_TRANSITION_INVALID.
    승인된 글인데 이 글의 commit 이 기록 없이 남아 있으면(commit 직후에 프로그램이 멈춤) 새로 올리지 않고 그것을 이어받는 단계(adopt)가 된다.
    """
    capabilities.require_external_write("GitHub Pages 올리기 점검(원격 받기 포함)")           # 외부 Write 관문 — 이 시험 버전은 꺼져 있어 하위 프로세스·네트워크 전에 거절한다
    now = ctx.now() if now is None else now
    journal = Journal(ctx.workspace.journal_dir)
    with ctx.store() as store:
        project_id = resolve_id(store, text_id)
        project = store.load(project_id)
        variant = project.variant(PLATFORM_PAGES)
        stage = _STAGE_OF.get(variant.status)
        if stage is None:
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.COMMITTED}, detail="승인(APPROVED)한 글만 올린다")
        if stage == STAGE_DONE:
            return PagesPlan(project_id, project.title, variant.status, stage, "", "", "", "", 0, variant.published_url or "", "", None, _describe(stage, "", "", 0))
        text = variant.rendered
        if stage == STAGE_COMMIT and (not text or variant.rendered_revision != project.revision):
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.COMMITTED}, detail="승인한 글이 현재 원고의 판과 다르다 — 다시 만들어 검토·승인한다")
        header, _body = split_post(text)
        category, lang = header["category"], header["lang"]
        record = None
        if stage != STAGE_COMMIT:
            record = journal.read(project_id)
            if record is None:
                raise _missing_record(project_id, stage)
        if stage == STAGE_PUSH:
            problem = _outdated(variant, project)
            if problem is not None:
                raise problem
        repo = ctx.repo_path()
        gates = adopted = None
        if stage != STAGE_VERIFY:
            gates = require_gates(text, local_paths=ctx.local_paths())          # 걸리면 CHECK_FAILED(또는 키 모양 문자열 등 그 코드) — 올리지 않는다
            ctx.backend.inspect(repo)                                           # 연결한 저장소가 올바른지(origin·main·저장하지 않은 변경 없음)
        if stage == STAGE_COMMIT:
            adopted = ctx.backend.orphan_commit(repo, text, category, lang)     # 올리다 commit 직후에 멈춘 이 글의 commit 이 기록 없이 남아 있는가
            if adopted is not None:
                stage = STAGE_ADOPT
            else:
                _refuse_unpushed(ctx, repo, stage=stage)                        # 다른 올리지 않은 commit 이 있으면 새 글을 올리지 않는다 — 무엇을 해야 하는지 말한다
        elif stage == STAGE_PUSH:
            _refuse_unpushed(ctx, repo, stage=stage)                            # 이 글의 commit 위에 다른 commit 이 쌓였으면 올릴 수 없다
        fresh = record is None and adopted is None                              # 파일 이름(시각)을 이번에 정한다 — 같은 초의 이름이 이미 있으면 다음 초로 피한다(방금 다른 글이 올라간 경우)
        probes = 0
        while True:
            path = record.path if record is not None else adopted.path if adopted is not None else post_path(category, lang, now)
            post = PagesPost(path, text, category, lang)
            clash = None
            if stage in (STAGE_COMMIT, STAGE_ADOPT):
                names = [name for name in ctx.backend.duplicates(repo, post) if adopted is None or name != adopted.path]
                if names:
                    clash = AppError("DUPLICATE_SLUG", detail="같은 주소의 글이 이미 있다: " + ", ".join(names[:3]))
                else:
                    twins = [name for name in ctx.backend.same_content(repo, text) if adopted is None or name != adopted.path]
                    if twins:                                                   # 백업으로 되돌린 글이 이미 올라간 글을 다시 승인된 모습으로 되살린 경우 등 — 같은 글을 두 번 공개하지 않는다
                        raise AppError("DUPLICATE_CONTENT", {"파일": twins[0]}, detail="내용이 똑같은 글이 이미 있다: " + ", ".join(twins[:3]))
            if clash is None:
                url = ctx.backend.expected_url(repo, post, now)                 # 사이트가 공개하지 않을 글(published: false·미래 날짜)이면 여기서 AppError
                if stage in (STAGE_COMMIT, STAGE_ADOPT):
                    try:
                        _check_claims(store, journal, Path(path).stem, url)
                    except AppError as error:
                        if error.code != "DUPLICATE_SLUG":
                            raise
                        clash = error
            if clash is None:
                break
            if not fresh or probes >= MAX_SECOND_PROBES:
                raise clash
            probes += 1
            now = now + timedelta(seconds=1)                                    # 같은 주소(날짜-언어-시각의 초)가 이미 있다 — 다음 초의 이름으로 다시 본다
    return PagesPlan(project_id, project.title, variant.status, stage, path, category, lang, text, len(text.encode("utf-8")), url, str(repo), gates, _describe(stage, path, url, deadline), adopted, now)


def preview_publish(ctx, text_id, *, deadline=DEFAULT_DEADLINE):
    """미리 보기(dry run): 무엇을 만들고 어디에 올릴지 보여 줄 뿐 아무것도 하지 않는다."""
    capabilities.require_external_write("GitHub Pages 올리기 미리 보기")
    plan = plan_pages_publish(ctx, text_id, deadline=deadline)
    hint = {STAGE_COMMIT: "실제로 올리려면 같은 명령에 --yes 를 붙입니다.", STAGE_PUSH: "이어서 올리려면 같은 명령에 --yes 를 붙입니다.",
            STAGE_ADOPT: "이어받아 올리려면 같은 명령에 --yes 를 붙입니다(올리지 않고 되돌리려면 --cancel --yes).",
            STAGE_VERIFY: "공개 확인은 check-deploy 로 합니다.", STAGE_DONE: ""}[plan.stage]
    return PublishReport(plan.project_id, True, plan, plan.status, (), plan.expected_url, plan.stage == STAGE_DONE, False, (hint,) if hint else (), ("아직 아무것도 하지 않았습니다.",) if plan.stage != STAGE_DONE else ())


def _mark_failed(ctx, project_id, code):
    with ctx.store() as store:
        project = store.load(project_id)
        project.transition(PLATFORM_PAGES, st.PUBLISH_FAILED, error_code=code, now=ctx.stamp())
        store.save(project)


def _undo_commit(ctx, repo, path):
    """이 PC 에 기록한 글 커밋을 되돌린다(`discard_commit` 이 허락할 때만 — 다른 변경이 섞였거나 이미 올라갔거나 앱이 만든 커밋이 아니면 거절한다).
    이미 되돌려진 뒤(기록도 파일도 없다)라면 할 일이 없는 것으로 본다."""
    info = ctx.backend.current_commit(repo, path)
    try:
        ctx.backend.discard(repo, info)
    except AppError as error:
        if error.code == "PAGES_LOCAL_REPO_DIVERGED" and not ctx.backend.post_in_head(repo, path) and not (Path(repo) / path).exists():
            return
        raise


def _record_committed(ctx, repo, journal, project_id, post, info, *, undo_on_failure=True):
    """commit 을 발행 기록(COMMITTED)과 상태(COMMITTED)로 남긴다 → 이 실행이 쓴 발행 기록(PublishRecord). 못 남기면 방금 만든 commit 을 되돌린다(`undo_on_failure`).
    이어받은 commit(`undo_on_failure=False`)은 이번 실행이 만든 것이 아니므로 실패해도 건드리지 않는다 — 있는 그대로 두면 같은 명령이 다시 이어받는다."""
    record = PublishRecord(project_id, post.path, info.commit, info.base, STAGE_COMMITTED)
    try:
        journal.write(record)
        with ctx.store() as store:
            project = store.load(project_id)
            project.transition(PLATFORM_PAGES, st.COMMITTED, now=ctx.stamp())
            store.save(project)
    except BaseException as problem:
        if not undo_on_failure:
            if isinstance(problem, AppError):
                _annotate(problem, "이어받으려던 글 기록(commit)은 그대로 두었다 — 해결한 뒤 같은 명령을 다시 실행하면 다시 이어받는다(올리지 않고 되돌리려면 --cancel --yes)")
            raise
        # 저장소에는 글 기록이 생겼는데 상태를 못 남겼다 — 어긋난 채 두지 않고 방금 만든 기록을 되돌린다
        try:
            ctx.backend.discard(repo, info)
            removed = journal.remove(project_id, only=record)
            note = "이 PC 의 글 기록(commit)은 되돌렸다 — 저장소는 처음 상태다" + (f" ({removed})" if removed else "")
        except AppError as undo:
            note = f"글 기록(commit)을 되돌리지 못했다({undo.code}) — 연결한 저장소에 올리지 않은 글 기록이 남아 있을 수 있다"
        if isinstance(problem, AppError):
            _annotate(problem, note)
        raise
    return record


def _give_up(ctx, repo, journal, project_id, path, error, mine):
    """같은 주소의 글이 이미 올라가 있어 다시 해도 올릴 수 없다 — 이 PC 의 글 기록을 되돌리고 실패(PUBLISH_FAILED)로 남긴다(안 그러면 올리지 않은 커밋이 남아 다른 글이 막힌다)."""
    try:
        _undo_commit(ctx, repo, path)
    except AppError as undo:
        _annotate(error, f"글 기록(commit)을 되돌리지 못했다({undo.code}) — 상태는 COMMITTED 로 그대로 두었다. 저장소를 확인한 뒤 --cancel --yes 로 다시 시도한다")
        return
    try:
        _mark_failed(ctx, project_id, error.code)
    except AppError as problem:
        _annotate(error, f"글 기록(commit)은 되돌렸지만 상태를 갱신하지 못했다({problem.code}) — --cancel --yes 로 정리한다")
        return
    removed = journal.remove(project_id, only=mine)
    _annotate(error, "이 PC 의 글 기록(commit)을 되돌렸다. 글을 다시 만들어(review) 검토·승인한 뒤 다시 올린다" + (f" ({removed})" if removed else ""))


def _ensure_unchanged(ctx, project_id):
    """push 하기 바로 앞에서 한 번 더 — 승인한 뒤에 원고가 바뀌지 않았는가. 바뀌었으면 PUBLISH_CONTENT_CHANGED(올리지 않는다)."""
    with ctx.store() as store:
        project = store.load(project_id)
        problem = _outdated(project.variant(PLATFORM_PAGES), project)
    if problem is not None:
        raise problem


def _push(ctx, repo, journal, project_id, post, mine):
    _ensure_unchanged(ctx, project_id)
    try:
        return ctx.backend.push(repo, post)
    except AppError as error:
        if error.code == "DUPLICATE_SLUG":
            _give_up(ctx, repo, journal, project_id, post.path, error, mine)
        else:
            _annotate(error, "글은 이 PC 의 저장소에 기록(commit)되어 있고 아직 올라가지 않았다 — 해결한 뒤 같은 명령을 다시 실행하면 이어서 올린다(올리지 않고 되돌리려면 --cancel --yes)")
            if error.code == "PAGES_LOCAL_REPO_DIVERGED":
                _annotate(error, _stack_note(ctx, repo))                      # 다른 글의 기록이 같이 쌓여 있다면 어느 글부터 되돌려야 하는지
        raise


def _record_pushed(ctx, journal, project_id, post, pushed):
    """'올림' 을 발행 기록과 상태로 남긴다 → 이 실행이 쓴 발행 기록(PublishRecord)."""
    with _noting("글은 이미 원격 main 에 올라갔다 — 같은 명령을 다시 실행하면 기록을 마친다"):
        record = journal.read(project_id)
        base = record.base if record is not None else pushed.commit
        written = PublishRecord(project_id, post.path, pushed.commit, base, STAGE_PUSHED)
        journal.write(written)
        with ctx.store() as store:
            project = store.load(project_id)
            project.transition(PLATFORM_PAGES, st.PUSHED, remote_id=pushed.commit, now=ctx.stamp())
            store.save(project)
    return written


def _verify(ctx, repo, journal, project_id, post, now, deadline, interval):
    """공개 주소가 열리는지 확인하고 열리면 PUBLISHED 로 기록한다. 아직 안 열리면 (None, 오류)를 돌려준다 — 상태는 PUSHED 그대로다."""
    try:
        result = ctx.backend.check_deployed(repo, post, now, deadline, interval)
    except AppError as error:
        if error.code == "PAGES_DEPLOY_NOT_VISIBLE":
            return None, error
        _annotate(error, "글은 이미 올라갔고 공개 확인만 남았다 — 원인을 해결한 뒤 check-deploy 로 다시 확인한다")
        raise
    with _noting("공개 주소가 열리는 것은 확인했지만 상태를 기록하지 못했다 — check-deploy 를 다시 실행하면 기록을 마친다"):
        with ctx.store() as store:
            project = store.load(project_id)
            project.transition(PLATFORM_PAGES, st.PUBLISHED, published_url=result.url, now=ctx.stamp())
            store.save(project)
    return result, None


def _verify_hint(project_id):
    return (f"공개 확인은 나중에 다시 할 수 있습니다: python -m chanceblog_desktop check-deploy {project_id}",)


def run_pages_publish(ctx, text_id, *, confirmed, wait=True, deadline=DEFAULT_DEADLINE, interval=DEFAULT_INTERVAL):
    """확인(`confirmed=True`)을 받아 실제로 올린다. 글의 잠금을 먼저 잡고(다른 작업이 같은 글을 올리는 중이면 PUBLISH_IN_PROGRESS — 아무것도 바꾸지 않는다) 점검(`plan_pages_publish`)을 다시 하고
    → commit(또는 commit 직후에 멈춘 것을 이어받기) → push → 공개 확인 순서로, 한 단계마다 상태를 저장한다. 멈춘 곳(COMMITTED·PUSHED)에서 이어서 하고, 이미 공개된 글은 아무것도 하지 않는다.
    공개 확인이 끝나지 않은 채 끝나면(wait=False 이거나 아직 안 열림) 올렸지만 확인 대기로 보고한다."""
    capabilities.require_external_write("GitHub Pages 에 올리기")        # 외부 Write 관문 — 확인(`--yes`)보다 먼저: 꺼져 있으면 `--yes` 가 있어도 아무것도 하지 않는다
    require_confirmation(confirmed, "GitHub Pages 에 올리기")           # 이것이 commit·push 앞의 유일한 문 — 확인이 없으면 아무것도 하지 않는다
    with ctx.store() as store:
        project_id = resolve_id(store, text_id)
    with publish_lock(ctx, project_id, deadline=deadline) as lock:     # 점검보다 먼저 — 못 잡으면 여기서 멈춘다
        with _repo_section(ctx, ctx.repo_path_or_none()) as rlock:     # 그다음 저장소 잠금(순서 고정) — 다른 글이 같은 저장소에 올라가는 중이면 기다리다 물러난다
            lead = _lead(lock, rlock)
            now = ctx.now()
            plan = plan_pages_publish(ctx, project_id, now=now, deadline=deadline)
            now = plan.now or now                                       # 바로 앞 글이 같은 초에 올라가 파일 이름의 초를 밀었으면 그 시각으로(공개 주소 계산도 같은 시각)
            if plan.stage == STAGE_DONE:
                tidied = _tidy_finished_record(Journal(ctx.workspace.journal_dir), plan.project_id)
                return PublishReport(plan.project_id, False, plan, plan.status, ("이미 공개된 글입니다 — 할 일이 없었습니다.",), plan.expected_url, True, False, (), lead + ((tidied,) if tidied else ()))
            repo = ctx.repo_path()
            journal = Journal(ctx.workspace.journal_dir)
            project_id, post, steps, status = plan.project_id, plan.post, [], plan.status
            mine = journal.read(project_id) if plan.stage in (STAGE_PUSH, STAGE_VERIFY) else None          # 이 실행이 이어받은 기록(없으면 아래에서 새로 쓴다)
            if plan.stage in (STAGE_COMMIT, STAGE_ADOPT):
                if plan.stage == STAGE_COMMIT:
                    try:
                        info = ctx.backend.commit(repo, post, plan.title)   # 실패하면 commit_post 가 쓴 것을 치우고 오류를 낸다(상태는 APPROVED 그대로)
                    except AppError as error:
                        if error.code == "PAGES_LOCAL_REPO_DIVERGED":
                            _annotate(error, _stack_note(ctx, repo))        # 올리지 않은 commit 이 있어서 멈췄다 — 어느 글을 어떻게 해야 하는지
                        raise
                    steps.append(f"이 PC 의 chanceblog 저장소에 글 파일을 만들고 그 파일만 기록(commit)했습니다: {post.path}")
                else:
                    info = plan.adopted
                    steps.append(f"이 PC 의 저장소에 이미 기록(commit)되어 있던 이 글을 이어받았습니다(앞서 올리다 기록 직후에 멈춘 것): {post.path}")
                mine = _record_committed(ctx, repo, journal, project_id, post, info, undo_on_failure=plan.stage == STAGE_COMMIT)
                status = st.COMMITTED
            if plan.stage in (STAGE_COMMIT, STAGE_ADOPT, STAGE_PUSH):
                pushed = _push(ctx, repo, journal, project_id, post, mine)
                steps.append("이미 원격 main 에 올라가 있어 다시 올리지 않았습니다." if pushed.already else "원격(origin)의 main 에 올렸습니다.")
                mine = _record_pushed(ctx, journal, project_id, post, pushed)
                status = st.PUSHED
        # 저장소 잠금은 여기서 풀렸다 — 공개 확인을 기다리는 동안(최대 12분) 다른 글이 같은 저장소에 올라갈 수 있다(글 잠금은 그대로 쥔다)
        if not wait:
            steps.append("공개 확인은 하지 않았습니다(--no-wait).")
            return PublishReport(project_id, False, plan, status, tuple(steps), plan.expected_url, False, True, _verify_hint(project_id), lead)
        return _finish(ctx, repo, journal, plan, tuple(steps), now, deadline, interval, mine, lead)


def _finish(ctx, repo, journal, plan, steps, now, deadline, interval, mine, lead=()):
    project_id = plan.project_id
    result, waiting = _verify(ctx, repo, journal, project_id, plan.post, now, deadline, interval)
    if result is None:
        record = " ".join(re.sub(r"[#`*|>]+", " ", str(waiting.detail or "")).split())[:300]            # 확인 코드가 남긴 기록(어떤 요청이 어떤 답을 받았나)에서 Markdown 표시(###·`·**)를 걷는다 — 화면에 나갈 때 비밀 모양은 가려진다
        reason = ("공개 주소가 아직 열리지 않습니다 — 배포 직후에는 몇 분 늦을 수 있습니다.",) + ((f"확인 기록: {record}",) if record else ())
        return PublishReport(project_id, False, plan, st.PUSHED, steps + ("공개 주소가 열리는지 기다렸지만 아직 열리지 않았습니다. 글은 올라가 있습니다.",), plan.expected_url, False, True,
                             _verify_hint(project_id), lead + reason)
    note = journal.remove(project_id, only=mine)
    return PublishReport(project_id, False, plan, st.PUBLISHED, steps + (f"공개 주소가 열리는 것을 확인했습니다: {result.url}",), result.url, True, False, (), lead + ((note,) if note else ()))


def check_pages_deploy(ctx, text_id, *, deadline=DEFAULT_DEADLINE, interval=DEFAULT_INTERVAL):
    """올라간 글(PUSHED)의 공개 주소가 열리는지 확인하고 열리면 PUBLISHED 로 기록한다. 아직 안 열리면 상태는 그대로 두고 확인 대기로 보고한다(다시 실행하면 된다).
    올리는 명령과 같은 글의 잠금을 쓴다(다른 작업이 그 글을 올리는 중이면 PUBLISH_IN_PROGRESS)."""
    capabilities.require_external_write("올린 글의 공개 주소 확인")
    with ctx.store() as store:
        project_id = resolve_id(store, text_id)
    with publish_lock(ctx, project_id, deadline=deadline) as lock:
        lead = (lock.taken_over,) if lock.taken_over else ()
        now = ctx.now()
        plan = plan_pages_publish(ctx, project_id, now=now, deadline=deadline)
        if plan.stage == STAGE_DONE:
            tidied = _tidy_finished_record(Journal(ctx.workspace.journal_dir), plan.project_id)
            return PublishReport(plan.project_id, False, plan, plan.status, ("이미 공개된 글입니다 — 할 일이 없었습니다.",), plan.expected_url, True, False, (), lead + ((tidied,) if tidied else ()))
        if plan.stage != STAGE_VERIFY:
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": plan.status, "요청 상태": st.PUBLISHED}, detail="원격에 올라간 글(PUSHED)만 공개 확인을 한다")
        journal = Journal(ctx.workspace.journal_dir)
        return _finish(ctx, ctx.repo_path(), journal, plan, (), now, deadline, interval, journal.read(project_id), lead)


@dataclass(frozen=True)
class CancelReport:
    project_id: str
    status: str
    steps: tuple

    def to_dict(self):
        return {"project_id": self.project_id, "status": self.status, "steps": list(self.steps)}


def _cancel_unrecorded(ctx, project_id, variant, journal, lead):
    """승인됨(APPROVED)인데 이 글의 commit 이 기록 없이 남은 경우(commit 직후에 프로그램이 멈춤) — `discard_commit` 이 허락할 때만 그 commit 을 되돌리고 PUBLISH_FAILED(PUBLISH_CANCELLED)로 남긴다.
    이 글의 승인한 렌더링과 한 글자도 다르지 않은 앱의 commit 하나뿐일 때만 이 글의 것으로 본다 — 아니면 STATUS_TRANSITION_INVALID(아무것도 바꾸지 않는다)."""
    wrong = AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.PUBLISH_FAILED},
                     detail="올리지 않은 글 기록(COMMITTED)이거나, 올리다 commit 직후에 멈춰 이 글의 commit 이 기록 없이 남은 승인된 글만 취소한다")
    if not variant.rendered:
        raise wrong
    header, _body = split_post(variant.rendered)
    repo = ctx.repo_path()
    ctx.backend.inspect(repo)
    orphan = ctx.backend.orphan_commit(repo, variant.rendered, header["category"], header["lang"])
    if orphan is None:
        raise wrong
    _undo_commit(ctx, repo, orphan.path)
    _mark_failed(ctx, project_id, "PUBLISH_CANCELLED")
    try:
        stale = journal.read(project_id)                          # 승인됨인데 남은 낡은 기록이 있으면 같이 치운다(읽을 수 없는 기록은 건드리지 않고 알린다 — 이미 되돌린 뒤라 여기서 멈추면 안 된다)
        note = journal.remove(project_id, only=stale) if stale is not None else ""
    except AppError as error:
        note = f"읽을 수 없는 발행 기록 파일은 그대로 두었습니다({error.code}): {project_id}.json"
    steps = ("올리다 기록 직후에 멈춰 남은 이 글의 commit 을 되돌리고 글 파일을 치웠습니다.", "상태를 '실패(PUBLISH_FAILED)' 로 바꿨습니다 — 다시 올리려면 글을 다시 만들어(review) 검토·승인합니다.") + ((note,) if note else ())
    return CancelReport(project_id, st.PUBLISH_FAILED, lead + steps)


def cancel_pages_publish(ctx, text_id, *, confirmed):
    """올리지 않은 글 기록(COMMITTED)을 되돌리고 PUBLISH_FAILED(PUBLISH_CANCELLED)로 남긴다. 확인이 있어야 하고, `discard_commit` 이 허락할 때만 되돌린다 — 이미 올라간 글은 되돌리지 않는다.
    승인됨(APPROVED)인데 이 글의 commit 이 기록 없이 남아 있으면(commit 직후에 멈춤) 그것도 같은 조건으로 되돌린다. 올리는 명령과 같은 글의 잠금을 쓴다."""
    capabilities.require_external_write("올리지 않은 글 기록 되돌리기")        # 저장소를 바꾸는 올리기 흐름의 일부 — 이 시험 버전에서는 올리기 자체가 꺼져 있다
    require_confirmation(confirmed, "올리지 않은 글 기록 되돌리기")
    journal = Journal(ctx.workspace.journal_dir)
    with ctx.store() as store:
        project_id = resolve_id(store, text_id)
    with publish_lock(ctx, project_id) as lock:
        with _repo_section(ctx, ctx.repo_path_or_none()) as rlock:     # 되돌리기도 저장소를 바꾼다 — 다른 글이 올라가는 중이면 기다리다 물러난다
            lead = _lead(lock, rlock)
            with ctx.store() as store:
                variant = store.load(project_id).variant(PLATFORM_PAGES)
            if variant.status == st.APPROVED:
                return _cancel_unrecorded(ctx, project_id, variant, journal, lead)
            if variant.status in (st.PUSHED, st.PUBLISHED):
                raise _already_pushed(project_id, variant.status, lost_record=variant.status == st.PUSHED and journal.missing(project_id))
            if variant.status != st.COMMITTED:
                raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.PUBLISH_FAILED}, detail="올리지 않은 글 기록(COMMITTED)만 취소한다")
            record = journal.read(project_id)
            if record is None:
                raise AppError("SETTINGS_INVALID", {"파일": f"{project_id}.json"}, detail="되돌릴 발행 기록 파일이 없다")
            repo = ctx.repo_path()
            try:
                _undo_commit(ctx, repo, record.path)
            except AppError as error:
                if error.code == UNEXPECTED and ctx.backend.on_remote(repo, record.path):          # 올리고 나서(기록을 마치기 전에) 멈췄다 — 이미 올라간 글은 되돌리지 않는다
                    raise _already_pushed(project_id, st.COMMITTED, record.path) from None
                if error.code == "PAGES_LOCAL_REPO_DIVERGED":
                    _annotate(error, _stack_note(ctx, repo))                # 다른 글의 기록이 위에 쌓여 있으면 그 글부터
                raise
            _mark_failed(ctx, project_id, "PUBLISH_CANCELLED")
            note = journal.remove(project_id, only=record)
            steps = ("이 PC 의 저장소에 기록해 둔 글(commit)을 되돌리고 글 파일을 치웠습니다.", "상태를 '실패(PUBLISH_FAILED)' 로 바꿨습니다 — 다시 올리려면 글을 다시 만들어(review) 검토·승인합니다.") + ((note,) if note else ())
            return CancelReport(project_id, st.PUBLISH_FAILED, lead + steps)


def _already_pushed(project_id, status, path="", *, lost_record=False):
    """이미 원격 main 에 올라간 글을 되돌리려 했다 — 되돌리지 않고(앱은 올라간 글을 지우지 않는다) 상태에 맞는 다음 일을 알린다.
    올림(PUSHED)인데 발행 기록이 없으면(`lost_record`) `check-deploy` 로 이을 수 없으니(서로를 가리키는 순환이 된다) 그렇게 말하지 않고 지우는 길을 알린다."""
    short = project_id[:8]
    if status == st.COMMITTED:
        how = f"상태는 아직 '이 PC 에 기록함(COMMITTED)' 이지만 원격 main 에 이미 올라가 있다 — `--cancel` 없이 같은 명령 `publish-pages {short} --yes` 를 실행하면 올림 기록을 마치고 공개 확인까지 한다"
    elif status == st.PUSHED and lost_record:
        how = (f"상태는 '올림(PUSHED)' 인데 발행 기록 파일이 없어 `check-deploy` 로 공개 확인을 이어갈 수 없다 — 올라간 글은 되돌리지 않는다(공개 주소는 사이트에서 직접 확인한다). "
               f"이 글의 기록이 필요 없으면 `delete {short} --yes` 로 지운다")
    elif status == st.PUSHED:
        how = f"상태가 '올림(PUSHED)' 이다 — `check-deploy {short}` 로 공개 확인을 마친다"
    else:
        how = "이미 공개된(PUBLISHED) 글이다 — 공개한 글을 내리려면 chanceblog 저장소에서 사람이 한다"
    return AppError("PUBLISH_ALREADY_PUSHED", {"파일": path or "이 글"}, detail=how)
