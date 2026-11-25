"""GitHub Pages 에 올리기 — 이 앱에서 가장 조심해야 하는 흐름(연결한 chanceblog 의 **새 가지**에 올린다 — 원격 `main` 에는 올리지 않는다, 변경 등급 T3, PUBPR).

사람이 GitHub 에서 PR 로 검토·병합하고, 앱은 사용자가 '병합 확인' 을 누를 때만 원격 main 에 같은 글이 들어갔는지 읽는다. 흐름: APPROVED → MERGE_PENDING(새 가지에 올림) → PUSHED(병합을 확인함) → PUBLISHED(공개 주소 확인).

지키는 것(하나씩 일부러 어겨 보는 변이 점검으로도 확인한다):
  1) **확인 없이는 올리지 않는다**(AGENTS.md 규칙 7): `plan_pages_publish`/`preview_publish` 는 아무것도 쓰지 않는 미리 보기(dry run)이고, `run_pages_publish` 는 `confirmed=True` 가 없으면 CONFIRMATION_REQUIRED 로
     아무것도 하지 않는다. 글 커밋 만들기도 새 가지 올리기도 그 뒤에만 한다.
  2) **승인된 글만, 승인한 그대로**: 상태가 APPROVED 이고 승인한 렌더링이 현재 원고의 판과 같을 때만 새로 올린다. 올리는 내용은 다시 만든 것이 아니라 승인한 렌더링(`variant.rendered`) 그대로다.
  3) **검사를 통과해야 한다**(fail closed): 게이트(`service/gate.py` — 파일 모양·키 모양 문자열·핵심 코드 검사·로컬 경로)와 연결한 저장소 확인(`inspect_repo`)과 같은 주소(slug)·같은 내용 글 확인을 미리 한다.
  4) **main 에 올리지 않는다**: 이 모듈에도 어댑터(`publish/pages.py`)에도 원격 main 으로 가는 올리기 인자를 만드는 코드가 없다. 앱은 `desktop/post-…` 모양의 새 가지 하나만 만들고, 연결한 폴더의 작업 폴더·색인·가지·HEAD 는 바꾸지 않는다
     (받은 원격 main 위에 글 하나를 더한 커밋을 **객체로만** 만든다). 병합은 사람이 한다 — 앱은 PR 을 만들지도 병합하지도 않고 비교 화면 주소를 **글자로만** 보여 준다.
  5) **상태는 사실을 따라간다**: APPROVED → MERGE_PENDING(새 가지에 올림) → PUSHED(병합 확인) → PUBLISHED(공개 주소가 열림을 확인). 한 단계를 마칠 때마다 바로 저장하고, 멈춘 곳에서 같은 명령으로 이어간다.
     가지를 올리기 전에 발행 기록에 `built`(가지·커밋)를 적어 두므로 올린 직후에 프로그램이 죽어도 다음 실행이 같은 가지의 끝을 보고 이어 간다(같은 일을 두 번 해도 같은 결과 — 두 번째 push 를 하지 않는다).
     공개 주소가 아직 안 열리면(`PAGES_DEPLOY_NOT_VISIBLE`) 상태는 PUSHED(병합 확인·공개 확인 대기)로 두고 `check-deploy` 로 다시 확인한다 — 상태를 망가뜨리지 않는다.
  6) **같은 글을 두 곳에서 동시에 올리지 못한다**: 올리기·병합 확인·되돌리기·공개 확인은 글마다 잠금(`service/lock.py`)을 먼저 잡고, 못 잡으면 아무것도 바꾸지 않고 PUBLISH_IN_PROGRESS 로 멈춘다.
     실패 경로가 발행 기록을 지울 때는 **이 실행이 쓴 기록과 똑같을 때만** 지운다(다른 실행이 쓴 기록을 지워 올라간 글을 잊는 일이 없게).
  7) **병합 기다리는 글은 한꺼번에 세 개까지**: 가지·PR 이 쌓여 병합 순서와 날짜가 엉키지 않게 같은 저장소에 `MERGE_PENDING` 글이 이미 셋이면 새 글을 올리지 않고 PAGES_MERGE_LIMIT.
  8) **병합 확인은 사용자가 누를 때만**(시작 때·주기 없음): 원격 main 에 그 경로로 **한 글자도 다르지 않은** 글이 있을 때만 PUSHED 로 간다(일반 병합·squash·rebase 가리지 않는다). 글이 다르면 PAGES_MERGE_DIFFERENT 로 멈추고 공개 확인을 하지 않는다.
  9) **두 글이 같은 저장소를 동시에 바꾸지 못한다**: 받기·가지 올리기·병합 확인 구간은 연결한 저장소마다 한 번에 한 작업(저장소 잠금 — 글 잠금을 잡은 다음에 잡는다, 순서 고정이라 서로 기다리며 멈추지 않는다)이고,
     다른 작업이 쥐고 있으면 `Context.lock_wait` 초 기다리다 PUBLISH_REPO_BUSY 로 물러난다(아무것도 바꾸지 않는다 — 같은 명령을 다시 실행하면 된다). 공개 확인을 기다리는 동안에는 저장소 잠금을 쥐지 않는다.
 10) **같은 초의 파일 이름을 피한다**: 새 글의 파일 이름은 올리는 순간의 초로 정해지는데 바로 앞 글이 같은 초에 올라갔으면(저장소에 이미 있거나 올리는 중인 글이 쓰는 이름) 점검 단계에서 다음 초의 이름으로 정한다(최대 5번, 읽기만 한다).
옛 방식(main 에 곧바로 commit·push)이 남긴 `COMMITTED` 글은 **읽기만** 한다 — 이어서 올리는 길은 없고 `--cancel --yes` 로 이 PC 의 글 기록만 되돌릴 수 있다(되돌린 뒤 글을 다시 만들어 승인한다).
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
from ..publish import pages as publish_pages
from ..render.pages import PagesPost, post_path
from . import unpushed
from .gate import require_gates, split_post
from .journal import STAGE_BRANCH_PUSHED, STAGE_BUILT, STAGE_PUSHED, Journal, PublishRecord
from .lock import publish_lock, repo_lock
from .previews import PLATFORM_PAGES
from .projects import require_confirmation, resolve_id

STAGE_BRANCH, STAGE_MERGE, STAGE_VERIFY, STAGE_DONE = "branch", "merge_check", "verify", "done"
DEFAULT_DEADLINE = 720          # 공개 확인을 기다리는 최대 시간(초) — 배포 확인 모듈의 기본값과 같다
DEFAULT_INTERVAL = 10
MAX_SECOND_PROBES = 5           # 파일 이름의 초가 이미 쓰였을 때 다음 초로 밀어 보는 최대 횟수(바로 앞 글이 같은 초에 올라간 경우)
MERGE_PENDING_LIMIT = 3         # 같은 저장소에 병합을 기다리는 글이 이만큼이면 새 글을 올리지 않는다
_STAGE_OF = {st.APPROVED: STAGE_BRANCH, st.MERGE_PENDING: STAGE_MERGE, st.PUSHED: STAGE_VERIFY, st.PUBLISHED: STAGE_DONE}


@dataclass(frozen=True)
class PagesPlan:
    """올리기 전에 확인한 것과 앞으로 할 일. 미리 보기(dry run)가 이것을 그대로 보여 준다."""
    project_id: str
    title: str
    status: str            # 시작할 때의 Pages 상태
    stage: str             # branch(새 가지에 올림) · merge_check(병합을 기다리는 중 — 확인은 merge-check) · verify(공개 확인만) · done(이미 공개됨)
    path: str              # 만들(또는 이미 만든) 글 파일 경로
    category: str
    lang: str
    text: str
    size_bytes: int
    expected_url: str
    repo: str              # 연결한 폴더(화면에만 보인다 — 어디에도 저장하지 않는다)
    gates: object          # GateReport 또는 None(검사하지 않는 단계)
    actions: tuple         # 이 단계에서 할 일(쉬운 한국어)
    resumed: object = None  # 가지 단계에서 이어받을 발행 기록(PublishRecord — 올리기 전에 멈춘 앞선 실행이 남긴 것)
    now: object = None      # 파일 이름의 시각을 정한 때(같은 초의 이름을 피해 다음 초로 밀었으면 그 시각) — 공개 주소 계산에 같은 시각을 쓴다
    branch: str = ""        # 올릴(또는 올린) 가지 이름 — 사용자 글에서 온 글자가 없는 정해진 모양
    link: str = ""          # GitHub 비교 화면 주소(글자로만 보여 준다 — 앱이 열지 않는다)
    record: object = None   # 병합 기다리는 글·병합을 확인한 글의 발행 기록(파일이 없으면 보관함의 식별자에서 다시 만든 것)

    @property
    def post(self):
        return PagesPost(self.path, self.text, self.category, self.lang)

    def to_dict(self, *, with_text=False):
        data = {"project_id": self.project_id, "title": self.title, "status": self.status, "stage": self.stage, "path": self.path, "category": self.category, "lang": self.lang,
                "size_bytes": self.size_bytes, "expected_url": self.expected_url, "repo": self.repo, "gates": self.gates.to_dict() if self.gates else None, "actions": list(self.actions),
                "branch": self.branch, "link": self.link}
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
    pending_verification: bool   # 병합 확인·공개 확인이 끝나지 않았다(merge-check 또는 check-deploy 로 이어 간다)
    next_steps: tuple
    notes: tuple = ()
    link: str = ""               # GitHub 비교 화면 주소(병합을 기다리는 동안 다시 보여 준다 — 글자로만, 앱이 열지 않는다)
    branch: str = ""             # 올린 가지 이름

    def to_dict(self, *, with_text=False):
        return {"project_id": self.project_id, "dry_run": self.dry_run, "status": self.status, "steps": list(self.steps), "url": self.url, "verified": self.verified,
                "pending_verification": self.pending_verification, "next_steps": list(self.next_steps), "notes": list(self.notes), "link": self.link, "branch": self.branch,
                "plan": self.plan.to_dict(with_text=with_text)}


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
    """연결한 저장소를 읽고(받기) 쓰는(객체 만들기·가지 올리기) 구간의 저장소 잠금. 다른 글이 같은 저장소를 쓰는 중이면 기다리다 물러난다(PUBLISH_REPO_BUSY — 아무것도 바꾸지 않았다).
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


def _missing_record(project_id, stage):
    """공개 확인을 이어갈(PUSHED) 글인데 발행 기록 파일이 없고 식별자로도 다시 만들 수 없다 → SETTINGS_INVALID(세부에 왜 이렇게 됐고 어떻게 하는지).
    옛 방식으로 올린 글의 글 파일 이름(올린 순간의 시각)은 기록에만 있어서다. 지웠다가 백업으로 되살리거나 오래된 백업으로 되돌릴 때 생긴다(발행 기록은 백업에 들어 있지 않다).
    어느 명령도 서로를 가리키지 않게 '지운다' 는 한 가지 출구를 말한다(올라간 글은 저장소에 그대로 있고 이 앱은 지우지 않는다)."""
    short = project_id[:8]
    if stage == STAGE_VERIFY:
        return AppError("SETTINGS_INVALID", {"파일": f"{project_id}.json"},
                        detail=("올림(PUSHED) 상태인데 공개 확인을 이어갈 발행 기록 파일이 없다 — 글을 지웠다가 백업으로 되살렸거나 오래된 백업으로 되돌렸을 때 생긴다. 앱은 올라간 글의 파일 이름을 기록으로만 알아서 "
                                f"공개 확인을 이어갈 수 없다(올라간 글은 저장소에 그대로 있다 — 공개 주소는 사이트에서 직접 확인한다). 이 글의 기록이 필요 없으면 `delete {short} --yes` 로 지운다"))
    return AppError("SETTINGS_INVALID", {"파일": f"{project_id}.json"}, detail="이어서 할 발행 기록 파일이 없다")


def _rebuilt_record(project_id, variant, header, stage):
    """발행 기록 파일이 없을 때(백업을 되돌린 뒤) 보관함의 식별자(`가지@커밋`)와 승인한 글의 머리말(분야·언어)로 기록을 다시 만든다 — 가지 이름의 시각이 글 파일 이름의 시각이다. 만들 수 없으면 None."""
    split = st.split_remote_id(variant.remote_id)
    if split is None:
        return None
    branch, commit = split
    path = publish_pages.post_path_for_branch(branch, header["category"], header["lang"])
    if path is None:
        return None
    return PublishRecord(project_id, path, commit, commit, stage, branch)


def _tidy_finished_record(journal, project_id):
    """공개된 글(PUBLISHED)에 발행 기록이 남아 있으면(기록을 지우기 직전에 프로그램이 멈춘 흔적 — 해롭지 않다) 그 기록만 지운다 → 알릴 말('' 이면 할 일 없었다). 읽을 수 없는 기록은 건드리지 않는다."""
    try:
        leftover = journal.read(project_id)
    except AppError:
        return ""
    if leftover is None:
        return ""
    return journal.remove(project_id, only=leftover) or "공개된 글에 남아 있던 발행 기록(지우기 직전에 멈춘 흔적)을 정리했습니다."


def _holds_name(variant, record):
    """그 글이 파일 이름(날짜-언어-시각)을 쥐고 있는가 — 병합을 기다리거나(MERGE_PENDING)·병합을 확인했거나(PUSHED)·옛 방식으로 기록했거나(COMMITTED), 승인됨인데 가지를 올리다 멈춘 기록(`built`·`branch_pushed`)이 있다."""
    if variant.status in (st.COMMITTED, st.MERGE_PENDING, st.PUSHED):
        return True
    return variant.status == st.APPROVED and record is not None and record.stage in (STAGE_BUILT, STAGE_BRANCH_PUSHED)


def _check_claims(store, journal, stem, url, own_id):
    """다른 글이 같은 공개 주소를 이미 쓰고 있지 않은가 — 이미 공개된 글의 주소, 그리고 올리는 중인 글의 파일 이름(날짜-언어-시각).
    새로 올리려는 글 자신(own_id)은 승인됨(APPROVED) 상태라 발행 주소도 기록도 없으므로 여기에 걸리지 않는다."""
    for summary in store.list():
        try:
            other = store.load(summary.project_id)
        except AppError:
            continue                # 읽을 수 없는 다른 글은 여기서 판단하지 않는다 — 같은 주소 글은 저장소(git) 쪽 확인이 다시 막는다
        variant = other.variant(PLATFORM_PAGES)
        if url and variant.published_url == url:
            raise AppError("DUPLICATE_SLUG", detail="다른 글이 같은 공개 주소로 이미 공개되어 있다")
        if summary.project_id != own_id and variant.status in (st.COMMITTED, st.MERGE_PENDING, st.PUSHED, st.APPROVED):
            try:
                record = journal.read(summary.project_id)
            except AppError:
                continue                                                        # 읽을 수 없는 다른 글의 기록은 여기서 판단하지 않는다(그 글이 알린다)
            if _holds_name(variant, record) and record is not None and Path(record.path).stem == stem:
                raise AppError("DUPLICATE_SLUG", detail="올리는 중인 다른 글이 같은 주소(날짜-언어-시각)를 쓴다")


def _count_pending(store, own_id):
    """같은 저장소에 병합을 기다리는(MERGE_PENDING) 다른 글의 수 — 읽을 수 없는 글은 세지 않는다(그 글의 문제는 그 글이 알린다)."""
    count = 0
    for summary in store.list():
        if summary.project_id == own_id:
            continue
        try:
            if store.load(summary.project_id).variant(PLATFORM_PAGES).status == st.MERGE_PENDING:
                count += 1
        except AppError:
            continue
    return count


def _describe(stage, path, url, deadline, branch="", link=""):
    wait = f"최대 {max(deadline // 60, 1)}분"
    if stage == STAGE_BRANCH:
        return (f"연결한 chanceblog 저장소에 새 가지 `{branch}` 를 만들어 글 파일 1개({path})를 올립니다 — main 에는 올리지 않습니다.",
                "내 컴퓨터의 작업 폴더·작업 중인 가지·HEAD 는 바꾸지 않습니다(받은 원격 main 위에 글 하나를 더한 기록(commit)을 저장소 안쪽에 만들 뿐입니다).",
                "올린 뒤 GitHub 의 비교 화면 주소를 글자로 알려 드립니다 — 앱이 열지 않으니 복사해 브라우저에서 PR 을 만들고 검사가 초록인지 본 뒤 병합해 주세요(앱은 PR 을 만들지도 병합하지도 않습니다).",
                f"병합한 뒤 `merge-check` 로 병합을 확인하고, 그다음 `check-deploy` 로 {url} 이 열리는지 확인합니다({wait}까지 기다립니다).",
                "파일 이름의 시각은 실제로 올리는 순간의 한국 시각으로 정해집니다(내용은 승인한 그대로입니다) — 병합이 늦으면 글 날짜가 병합한 날보다 앞설 수 있습니다.")
    if stage == STAGE_MERGE:
        return (f"이 글은 새 가지 `{branch}` 에 올라가 병합을 기다리는 중입니다(파일: {path}). 병합은 GitHub 에서 사람이 합니다 — 앱은 하지 않습니다.",
                "병합했으면 `merge-check` 로 원격 main 에 같은 글이 들어갔는지 확인합니다(누를 때만 확인합니다 — 시작할 때나 주기로는 확인하지 않습니다).",
                "병합하지 않기로 했으면 `abandon` 으로 정리합니다 — 올려 둔 가지는 GitHub 에 남으니 필요 없으면 직접 지웁니다.")
    if stage == STAGE_VERIFY:
        return (f"병합을 확인한 글입니다. 공개 주소가 열리는지만 확인합니다: {url}",)
    return ("이미 공개된 글입니다 — 할 일이 없습니다.",)


def _outdated(variant, project):
    """승인한 뒤에 원고가 바뀌었는가 — 그렇다면 승인했던 옛 글을 몰래 올리지 않고 멈춘다(fail closed)."""
    if variant.rendered_revision != project.revision:
        return AppError("PUBLISH_CONTENT_CHANGED", {"현재 상태": variant.status},
                        detail=f"승인한 때의 원고 판은 {variant.rendered_revision}, 지금 원고는 판 {project.revision} 이다 — 이미 올라간 글은 승인한 옛 내용이다")
    return None


def _legacy_committed(project_id, status):
    """옛 방식으로 이 PC 에 기록(commit)해 둔 글(COMMITTED) — 이어서 올리는 길이 없어졌다(main 으로 올리는 코드가 없다). 이 PC 의 기록만 되돌릴 수 있다."""
    short = project_id[:8]
    return AppError("STATUS_TRANSITION_INVALID", {"현재 상태": status, "요청 상태": st.MERGE_PENDING},
                    detail=f"옛 방식(main 에 올리던 시절)으로 이 PC 에 기록해 둔 글이다 — 이어서 올리는 길은 없어졌다. `publish-pages {short} --cancel --yes` 로 이 PC 의 글 기록만 되돌린 뒤 글을 다시 만들어(review) 승인한다")


def _plan_record(record_or_none):
    """가지 단계에서 이어받을 수 있는 앞선 실행의 기록 — `built`·`branch_pushed` 만(옛 방식 기록은 이어받을 것이 없다)."""
    if record_or_none is not None and record_or_none.stage in (STAGE_BUILT, STAGE_BRANCH_PUSHED):
        return record_or_none
    return None


def plan_pages_publish(ctx, text_id, *, now=None, deadline=DEFAULT_DEADLINE):
    """올리기 전 점검(아무것도 쓰지 않는다 — 연결한 저장소·데이터 폴더·네트워크 모두). 올릴 수 없으면 이유를 AppError 로 낸다.

    새로 올릴 글(APPROVED)은 승인이 현재 판과 같은지·게이트·저장소 확인·병합 기다리는 글 수(최대 3)·같은 주소(slug)·같은 내용 확인·공개 주소 계산까지 하고, 병합을 기다리는 글(MERGE_PENDING)은 무엇을 기다리는지만 알리며,
    병합을 확인한 글(PUSHED)은 공개 주소 계산까지만 한다. 이미 공개된 글(PUBLISHED)은 할 일이 없다. 옛 방식으로 이 PC 에 기록해 둔 글(COMMITTED)과 그 밖의 상태(승인 전·실패·다른 플랫폼 상태)는 STATUS_TRANSITION_INVALID.
    새 가지에 올리기 전에 멈춘 앞선 실행(발행 기록 `built`·`branch_pushed`)이 있으면 그 파일 이름·가지를 이어받는다(같은 일을 두 번 해도 같은 결과)."""
    capabilities.require_external_write("GitHub Pages 올리기 점검")           # 외부 Write 관문 — 이 시험 버전은 꺼져 있어 하위 프로세스·네트워크 전에 거절한다
    now = ctx.now() if now is None else now
    journal = Journal(ctx.workspace.journal_dir)
    with ctx.store() as store:
        project_id = resolve_id(store, text_id)
        project = store.load(project_id)
        variant = project.variant(PLATFORM_PAGES)
        if variant.status == st.COMMITTED:
            raise _legacy_committed(project_id, variant.status)
        stage = _STAGE_OF.get(variant.status)
        if stage is None:
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.MERGE_PENDING}, detail="승인(APPROVED)한 글만 올린다")
        if stage == STAGE_DONE:
            return PagesPlan(project_id, project.title, variant.status, stage, "", "", "", "", 0, variant.published_url or "", "", None, _describe(stage, "", "", 0))
        text = variant.rendered
        if stage == STAGE_BRANCH and (not text or variant.rendered_revision != project.revision):
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.MERGE_PENDING}, detail="승인한 글이 현재 원고의 판과 다르다 — 다시 만들어 검토·승인한다")
        header, _body = split_post(text)
        category, lang = header["category"], header["lang"]
        record = journal.read(project_id)
        if stage != STAGE_BRANCH:
            if record is None:
                record = _rebuilt_record(project_id, variant, header, STAGE_BRANCH_PUSHED if stage == STAGE_MERGE else STAGE_PUSHED)
            if record is None:
                raise _missing_record(project_id, stage)
        repo = ctx.repo_path()
        gates = None
        if stage == STAGE_BRANCH:
            gates = require_gates(text, local_paths=ctx.local_paths())          # 걸리면 CHECK_FAILED(또는 키 모양 문자열 등 그 코드) — 올리지 않는다
            ctx.backend.inspect(repo)                                           # 연결한 저장소가 올바른지(origin·main·저장하지 않은 변경 없음)
            if _count_pending(store, project_id) >= MERGE_PENDING_LIMIT:
                raise AppError("PAGES_MERGE_LIMIT")
        elif stage == STAGE_MERGE:
            ctx.backend.inspect(repo)
        resumed = _plan_record(record) if stage == STAGE_BRANCH else None
        if resumed is not None and resumed.branch != publish_pages.branch_name(PagesPost(resumed.path, text, category, lang)):
            resumed = None                                                      # 앞선 실행이 올리려던 글이 지금 승인한 글과 다르다(그 사이 고쳐 다시 승인했다) — 가지 이름이 글 내용의 해시를 담고 있어 알아본다. 낡은 기록은 새 기록이 덮는다
        fresh = resumed is None                                                 # 파일 이름(시각)을 이번에 정한다 — 같은 초의 이름이 이미 있으면 다음 초로 피한다(방금 다른 글이 올라간 경우)
        probes = 0
        while True:
            if stage == STAGE_BRANCH:
                path = resumed.path if resumed is not None else post_path(category, lang, now)
            else:
                path = record.path
            post = PagesPost(path, text, category, lang)
            clash = None
            if stage == STAGE_BRANCH and fresh:
                names = ctx.backend.duplicates(repo, post)
                if names:
                    clash = AppError("DUPLICATE_SLUG", detail="같은 주소의 글이 이미 있다: " + ", ".join(names[:3]))
                else:
                    twins = ctx.backend.same_content(repo, text)
                    if twins:                                                   # 백업으로 되돌린 글이 이미 올라간 글을 다시 승인된 모습으로 되살린 경우 등 — 같은 글을 두 번 공개하지 않는다
                        raise AppError("DUPLICATE_CONTENT", {"파일": twins[0]}, detail="내용이 똑같은 글이 이미 있다: " + ", ".join(twins[:3]))
            if clash is None:
                url = ctx.backend.expected_url(repo, post, now)                 # 사이트가 공개하지 않을 글(published: false·미래 날짜)이면 여기서 AppError
                if stage == STAGE_BRANCH:
                    try:
                        _check_claims(store, journal, Path(path).stem, url, project_id)
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
    branch = (resumed.branch if resumed is not None else publish_pages.branch_name(post)) if stage == STAGE_BRANCH else (record.branch or "")
    if stage in (STAGE_BRANCH, STAGE_MERGE) and branch:
        link = publish_pages.compare_link(branch, project.title)
    else:
        link = ""
    return PagesPlan(project_id, project.title, variant.status, stage, path, category, lang, text, len(text.encode("utf-8")), url, str(repo), gates, _describe(stage, path, url, deadline, branch, link), resumed, now, branch, link,
                     record if stage != STAGE_BRANCH else None)


def preview_publish(ctx, text_id, *, deadline=DEFAULT_DEADLINE):
    """미리 보기(dry run): 무엇을 만들고 어디에 올릴지 보여 줄 뿐 아무것도 하지 않는다."""
    capabilities.require_external_write("GitHub Pages 올리기 미리 보기")
    plan = plan_pages_publish(ctx, text_id, deadline=deadline)
    hint = {STAGE_BRANCH: "실제로 올리려면 같은 명령에 --yes 를 붙입니다.", STAGE_MERGE: "병합했으면 merge-check 로 확인합니다(병합하지 않기로 했으면 abandon).",
            STAGE_VERIFY: "공개 확인은 check-deploy 로 합니다.", STAGE_DONE: ""}[plan.stage]
    return PublishReport(plan.project_id, True, plan, plan.status, (), plan.expected_url, plan.stage == STAGE_DONE, False, (hint,) if hint else (), ("아직 아무것도 하지 않았습니다.",) if plan.stage != STAGE_DONE else (),
                         plan.link, plan.branch)


def _mark_failed(ctx, project_id, code):
    with ctx.store() as store:
        project = store.load(project_id)
        project.transition(PLATFORM_PAGES, st.PUBLISH_FAILED, error_code=code, now=ctx.stamp())
        store.save(project)


def _undo_commit(ctx, repo, path):
    """옛 방식으로 이 PC 에 기록한 글 커밋을 되돌린다(`discard_commit` 이 허락할 때만 — 다른 변경이 섞였거나 이미 올라갔거나 앱이 만든 커밋이 아니면 거절한다).
    이미 되돌려진 뒤(기록도 파일도 없다)라면 할 일이 없는 것으로 본다."""
    info = ctx.backend.current_commit(repo, path)
    try:
        ctx.backend.discard(repo, info)
    except AppError as error:
        if error.code == "PAGES_LOCAL_REPO_DIVERGED" and not ctx.backend.post_in_head(repo, path) and not (Path(repo) / path).exists():
            return
        raise


def _ensure_unchanged(ctx, project_id):
    """가지를 올리기 바로 앞에서 한 번 더 — 승인한 뒤에 원고가 바뀌지 않았는가. 바뀌었으면 PUBLISH_CONTENT_CHANGED(올리지 않는다)."""
    with ctx.store() as store:
        project = store.load(project_id)
        problem = _outdated(project.variant(PLATFORM_PAGES), project)
    if problem is not None:
        raise problem


def _record_built(journal, project_id, built):
    """가지를 올리기 **전에** 가지·커밋을 발행 기록(`built`)에 적는다 → 이 실행이 쓴 기록. 올린 직후 앱이 죽어도 다음 실행이 같은 가지의 끝을 보고 이어 간다."""
    record = PublishRecord(project_id, built.path, built.commit, built.base, STAGE_BUILT, built.branch)
    journal.write(record)
    return record


def _record_branch_pushed(ctx, journal, project_id, built):
    """'새 가지에 올림' 을 발행 기록(`branch_pushed`)과 상태(MERGE_PENDING + 식별자 `가지@커밋`)로 남긴다 → 이 실행이 쓴 발행 기록."""
    with _noting("글은 이미 새 가지에 올라갔다 — 같은 명령을 다시 실행하면 기록을 마친다"):
        record = PublishRecord(project_id, built.path, built.commit, built.base, STAGE_BRANCH_PUSHED, built.branch)
        journal.write(record)
        with ctx.store() as store:
            project = store.load(project_id)
            project.transition(PLATFORM_PAGES, st.MERGE_PENDING, remote_id=f"{built.branch}@{built.commit}", now=ctx.stamp())
            store.save(project)
    return record


def _branch_stage(ctx, repo, journal, plan, steps):
    """가지 단계: 객체로 글 커밋을 만들고(앞선 실행이 만든 것이 있으면 그것을 이어받고) → `built` 를 적고 → 새 가지에 올리고 → `branch_pushed`·MERGE_PENDING 을 남긴다."""
    post, project_id = plan.post, plan.project_id
    built = None
    if plan.resumed is not None:
        built = publish_pages.BranchCommit(plan.resumed.path, plan.resumed.branch, plan.resumed.commit, plan.resumed.base)
        steps.append(f"앞서 올리다 멈춘 이 글의 가지({built.branch})를 이어받았습니다.")
    mine = None
    for attempt in range(2):
        if built is None:
            built = ctx.backend.build_branch_commit(repo, post, plan.title)               # 실패하면 연결한 저장소는 처음 그대로다(만든 객체는 어떤 참조에도 묶이지 않는다)
            steps.append(f"받은 원격 main 위에 글 파일 하나({post.path})를 더한 기록(commit)을 만들었습니다 — 내 작업 폴더는 바꾸지 않았습니다.")
            mine = _record_built(journal, project_id, built)
        elif plan.resumed is not None and mine is None:
            mine = plan.resumed
        _ensure_unchanged(ctx, project_id)
        try:
            pushed = ctx.backend.push_branch(repo, built, post)
            break
        except AppError as error:
            if error.code == UNEXPECTED and attempt == 0 and plan.resumed is not None and "다시 만든다" in str(error.detail):
                journal.remove(project_id, only=mine)                                      # 만들어 둔 커밋이 사라졌다(정리됨) — 한 번만 처음부터 다시 만든다
                built, mine = None, None
                continue
            if error.code == "PAGES_PUSH_REFUSED":                                        # 앱의 안전 규칙이 막았다 — 같은 글로 다시 해도 같다. 실패로 남기고 기록을 치운다(새 글로 다시 승인한다)
                _fail_after_refusal(ctx, journal, project_id, mine, error)
            else:
                _annotate(error, "글은 아직 올라가지 않았다(원격 main 은 건드리지 않았다) — 해결한 뒤 같은 명령을 다시 실행하면 이어서 한다")
            raise
    steps.append("원격(origin)에 새 가지 하나를 만들어 올렸습니다 — main 에는 올리지 않았습니다." if not pushed.already else "같은 가지가 이미 원격에 같은 끝으로 올라가 있어 다시 올리지 않았습니다.")
    _record_branch_pushed(ctx, journal, project_id, built)
    return built


def _fail_after_refusal(ctx, journal, project_id, mine, error):
    try:
        _mark_failed(ctx, project_id, error.code)
    except AppError as problem:
        _annotate(error, f"상태를 갱신하지 못했다({problem.code}) — 글은 승인됨 그대로다")
        return
    removed = journal.remove(project_id, only=mine) if mine is not None else ""
    _annotate(error, "글을 다시 만들어(review) 검토·승인한 뒤 다시 올린다" + (f" ({removed})" if removed else ""))


def _verify_hint(project_id):
    return (f"공개 확인은 나중에 다시 할 수 있습니다: python -m chanceblog_desktop check-deploy {project_id}",)


def _merge_hint(project_id):
    return (f"GitHub 에서 PR 을 병합했으면 이 명령으로 확인합니다: python -m chanceblog_desktop merge-check {project_id[:8]}",
            f"병합하지 않기로 했으면: python -m chanceblog_desktop abandon {project_id[:8]} --yes")


def run_pages_publish(ctx, text_id, *, confirmed, wait=True, deadline=DEFAULT_DEADLINE, interval=DEFAULT_INTERVAL):
    """확인(`confirmed=True`)을 받아 실제로 올린다. 글의 잠금을 먼저 잡고(다른 작업이 같은 글을 올리는 중이면 PUBLISH_IN_PROGRESS — 아무것도 바꾸지 않는다) 점검(`plan_pages_publish`)을 다시 하고
    → 글 커밋 만들기(객체만) → 새 가지 올리기 순서로, 한 단계마다 기록한다. **병합은 사람이 하므로 여기서 끝난다** — 상태는 MERGE_PENDING(병합 기다리는 중)이고 비교 화면 주소를 글자로 알린다.
    이미 병합을 기다리는 글(MERGE_PENDING)은 아무것도 하지 않고 안내만 하며(병합 확인은 `merge-check`), 병합을 확인한 글(PUSHED)은 공개 주소 확인만 한다. 이미 공개된 글은 아무것도 하지 않는다.
    `wait`·`deadline` 은 PUSHED 글의 공개 확인에만 쓰인다."""
    capabilities.require_external_write("GitHub Pages 에 올리기")        # 외부 Write 관문 — 확인(`--yes`)보다 먼저: 꺼져 있으면 `--yes` 가 있어도 아무것도 하지 않는다
    require_confirmation(confirmed, "GitHub Pages 에 올리기")           # 이것이 글 커밋 만들기·가지 올리기 앞의 유일한 문 — 확인이 없으면 아무것도 하지 않는다
    capabilities.require_net("pages_branch", "GitHub Pages 새 가지에 올리기")      # 셋째 문장: 좁은 스위치도 함께(D-736)
    with ctx.store() as store:
        project_id = resolve_id(store, text_id)
    with publish_lock(ctx, project_id, deadline=deadline) as lock:     # 점검보다 먼저 — 못 잡으면 여기서 멈춘다
        with _repo_section(ctx, ctx.repo_path_or_none()) as rlock:     # 그다음 저장소 잠금(순서 고정) — 다른 글이 같은 저장소를 쓰는 중이면 기다리다 물러난다
            lead = _lead(lock, rlock)
            now = ctx.now()
            plan = plan_pages_publish(ctx, project_id, now=now, deadline=deadline)
            now = plan.now or now                                       # 바로 앞 글이 같은 초에 올라가 파일 이름의 초를 밀었으면 그 시각으로(공개 주소 계산도 같은 시각)
            if plan.stage == STAGE_DONE:
                tidied = _tidy_finished_record(Journal(ctx.workspace.journal_dir), plan.project_id)
                return PublishReport(plan.project_id, False, plan, plan.status, ("이미 공개된 글입니다 — 할 일이 없었습니다.",), plan.expected_url, True, False, (), lead + ((tidied,) if tidied else ()))
            if plan.stage == STAGE_MERGE:
                return PublishReport(plan.project_id, False, plan, plan.status, ("이미 새 가지에 올라가 병합을 기다리는 글입니다 — 할 일이 없었습니다.",), plan.expected_url, False, True, _merge_hint(plan.project_id), lead,
                                     plan.link, plan.branch)
            repo = ctx.repo_path()
            journal = Journal(ctx.workspace.journal_dir)
            project_id, steps, status = plan.project_id, [], plan.status
            mine = journal.read(project_id) if plan.stage == STAGE_VERIFY else None          # 이 실행이 이어받은 기록(없으면 아래에서 새로 쓴다)
            if plan.stage == STAGE_BRANCH:
                built = _branch_stage(ctx, repo, journal, plan, steps)
                link = publish_pages.compare_link(built.branch, plan.title)
                return PublishReport(project_id, False, plan, st.MERGE_PENDING, tuple(steps), plan.expected_url, False, True, _merge_hint(project_id), lead, link, built.branch)
        # 저장소 잠금은 여기서 풀렸다 — 공개 확인을 기다리는 동안(최대 12분) 다른 글이 같은 저장소를 쓸 수 있다(글 잠금은 그대로 쥔다)
        if not wait:
            steps.append("공개 확인은 하지 않았습니다(--no-wait).")
            return PublishReport(project_id, False, plan, status, tuple(steps), plan.expected_url, False, True, _verify_hint(project_id), lead)
        return _finish(ctx, repo, journal, plan, tuple(steps), now, deadline, interval, mine, lead)


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


def _finish(ctx, repo, journal, plan, steps, now, deadline, interval, mine, lead=()):
    project_id = plan.project_id
    result, waiting = _verify(ctx, repo, journal, project_id, plan.post, now, deadline, interval)
    if result is None:
        record = " ".join(re.sub(r"[#`*|>]+", " ", str(waiting.detail or "")).split())[:300]            # 확인 코드가 남긴 기록(어떤 요청이 어떤 답을 받았나)에서 Markdown 표시(###·`·**)를 걷는다 — 화면에 나갈 때 비밀 모양은 가려진다
        reason = ("공개 주소가 아직 열리지 않습니다 — 배포 직후에는 몇 분 늦을 수 있습니다.",) + ((f"확인 기록: {record}",) if record else ())
        return PublishReport(project_id, False, plan, st.PUSHED, steps + ("공개 주소가 열리는지 기다렸지만 아직 열리지 않았습니다. 글은 병합되어 있습니다.",), plan.expected_url, False, True,
                             _verify_hint(project_id), lead + reason)
    note = journal.remove(project_id, only=mine)
    return PublishReport(project_id, False, plan, st.PUBLISHED, steps + (f"공개 주소가 열리는 것을 확인했습니다: {result.url}",), result.url, True, False, (), lead + ((note,) if note else ()))


def check_pages_deploy(ctx, text_id, *, deadline=DEFAULT_DEADLINE, interval=DEFAULT_INTERVAL):
    """병합을 확인한 글(PUSHED)의 공개 주소가 열리는지 확인하고 열리면 PUBLISHED 로 기록한다. 아직 안 열리면 상태는 그대로 두고 확인 대기로 보고한다(다시 실행하면 된다).
    올리는 명령과 같은 글의 잠금을 쓴다(다른 작업이 그 글을 올리는 중이면 PUBLISH_IN_PROGRESS)."""
    capabilities.require_external_write("올린 글의 공개 주소 확인")
    capabilities.require_net("pages_site", "올린 글의 공개 주소 확인")             # 둘째 문장: 좁은 스위치도 함께(NET 설계서 3.3)
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
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": plan.status, "요청 상태": st.PUBLISHED},
                           detail="병합을 확인한 글(PUSHED)만 공개 확인을 한다" + (f" — 먼저 GitHub 에서 병합한 뒤 `merge-check {plan.project_id[:8]}` 로 병합을 확인한다" if plan.stage == STAGE_MERGE else ""))
        journal = Journal(ctx.workspace.journal_dir)
        return _finish(ctx, ctx.repo_path(), journal, plan, (), now, deadline, interval, journal.read(project_id), lead)


def _record_merged(ctx, journal, project_id, record, main_commit):
    """병합을 확인했다 → 발행 기록(`pushed`: 글을 처음 담은 main 커밋)과 상태(PUSHED)로 남긴다 → 이 실행이 쓴 기록."""
    with _noting("글은 이미 원격 main 에 들어가 있다 — 같은 명령(merge-check)을 다시 실행하면 기록을 마친다"):
        written = PublishRecord(project_id, record.path, main_commit, record.base if record.base else main_commit, STAGE_PUSHED, record.branch)
        journal.write(written)
        with ctx.store() as store:
            project = store.load(project_id)
            project.transition(PLATFORM_PAGES, st.PUSHED, now=ctx.stamp())                  # 식별자(가지@커밋)는 그대로 둔다 — 발행 기록이 없어져도 글 파일 경로를 다시 만들 수 있게
            store.save(project)
    return written


def merge_check_pages(ctx, text_id):
    """병합 확인 — **사용자가 누를 때만**(시작 때·주기·화면을 열 때 하지 않는다). 원격 main 을 받아 그 경로로 **한 글자도 다르지 않은** 글이 들어갔는지 읽고(병합 방식은 가리지 않는다), 들어갔으면 PUSHED 로 바꾼다.
    아직이면 상태를 그대로 두고 안내한다(가지가 원격에 아직 있는지도 알린다 — 없으면 PR 이 닫히고 가지가 지워졌을 수 있다). 같은 경로에 다른 글이 있으면 PAGES_MERGE_DIFFERENT 로 멈추고 공개 확인을 하지 않는다."""
    capabilities.require_external_write("병합 확인(merge-check)")
    capabilities.require_net("pages_branch", "병합 확인(merge-check)")                  # 둘째 문장: 좁은 스위치도 함께(D-736)
    with ctx.store() as store:
        project_id = resolve_id(store, text_id)
    with publish_lock(ctx, project_id) as lock:
        with _repo_section(ctx, ctx.repo_path_or_none()) as rlock:
            lead = _lead(lock, rlock)
            with ctx.store() as store:
                project = store.load(project_id)
                variant = project.variant(PLATFORM_PAGES)
            if variant.status == st.MERGE_PENDING and variant.rendered_revision != project.revision:
                lead = lead + ("원고를 고쳤어요 — 병합되는 글은 승인했던 옛 내용이에요(병합 확인은 승인한 글과 견줍니다).",)
            if variant.status == st.MERGE_PENDING:
                pass
            elif variant.status in (st.PUSHED, st.PUBLISHED):
                plan = plan_pages_publish(ctx, project_id)
                return PublishReport(project_id, False, plan, variant.status, ("이미 병합을 확인한 글입니다 — 할 일이 없었습니다.",), plan.expected_url, variant.status == st.PUBLISHED, variant.status == st.PUSHED,
                                     _verify_hint(project_id) if variant.status == st.PUSHED else (), lead)
            else:
                raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.PUSHED}, detail="새 가지에 올려 병합을 기다리는 글(MERGE_PENDING)만 병합 확인을 한다")
            journal = Journal(ctx.workspace.journal_dir)
            plan = plan_pages_publish(ctx, project_id)                                 # 기록 읽기(없으면 식별자로 다시 만들기)·저장소 확인·공개 주소 계산 — 아무것도 쓰지 않는다
            repo = ctx.repo_path()
            record = plan.record
            if record is None or record.branch == "":
                raise _missing_record(project_id, STAGE_MERGE)
            result = ctx.backend.post_on_main(repo, plan.post)
            if result.state == "different":
                raise AppError("PAGES_MERGE_DIFFERENT", {"파일": plan.path}, detail="병합 전에 글이 고쳐졌거나 같은 이름의 다른 글이 들어갔을 수 있다 — 공개 확인은 하지 않는다")
            if result.state == "merged":
                _record_merged(ctx, journal, project_id, record, result.commit)
                return PublishReport(project_id, False, plan, st.PUSHED, ("원격 main 에 같은 글이 들어간 것(병합)을 확인했습니다 — 내용이 승인한 글과 한 글자도 다르지 않습니다.",), plan.expected_url, False, True,
                                     (f"이제 공개 주소를 확인합니다: python -m chanceblog_desktop check-deploy {project_id[:8]}",), lead, "", plan.branch)
            notes = ["아직 병합되지 않았어요 — GitHub 에서 PR 을 만들었는지·병합했는지 확인해 주세요(앱은 PR 을 만들지도 병합하지도 않아요)."]
            if result.moved_to:
                notes.append(f"같은 내용의 글이 다른 파일 이름으로 들어가 있어요: {result.moved_to} — 앱은 이름이 바뀐 글을 이어받지 않아요. 같은 이름으로 병합해 주세요.")
            try:
                tip = ctx.backend.branch_on_remote(repo, plan.branch)
            except AppError as error:
                tip = None
                notes.append(f"올려 둔 가지가 원격에 아직 있는지는 확인하지 못했어요({error.code}).")
            else:
                if tip is None:
                    notes.append("올려 둔 가지가 원격에 없어요 — PR 이 닫히고 가지가 지워졌을 수 있어요. 병합하지 않기로 했다면 `abandon` 으로 정리해 주세요(앱이 자동으로 바꾸지 않아요).")
            return PublishReport(project_id, False, plan, st.MERGE_PENDING, ("원격 main 을 받아 확인했습니다 — 아직 병합되지 않았습니다.",), plan.expected_url, False, True, _merge_hint(project_id), lead + tuple(notes), plan.link, plan.branch)


@dataclass(frozen=True)
class CancelReport:
    project_id: str
    status: str
    steps: tuple

    def to_dict(self):
        return {"project_id": self.project_id, "status": self.status, "steps": list(self.steps)}


def abandon_pages_publish(ctx, text_id, *, confirmed):
    """'병합하지 않기로 했어요' — 병합을 기다리는 글(MERGE_PENDING)을 실패(PUBLISH_FAILED, 오류 코드 PAGES_MERGE_ABANDONED)로 정리한다. **아무것도 지우지 않는다**(원격 가지도·글 파일도) — 발행 기록만 치운다.
    정리한 뒤 다시 올리려면 글을 다시 만들어(review) 검토·승인한다. 확인이 있어야 하고 올리는 명령과 같은 글의 잠금을 쓴다."""
    capabilities.require_external_write("병합하지 않기로 하고 정리하기(abandon)")
    capabilities.require_net("pages_branch", "병합하지 않기로 하고 정리하기(abandon)")        # 둘째 문장: 좁은 스위치도 함께(D-736)
    require_confirmation(confirmed, "병합하지 않기로 하고 정리하기")
    journal = Journal(ctx.workspace.journal_dir)
    with ctx.store() as store:
        project_id = resolve_id(store, text_id)
    with publish_lock(ctx, project_id) as lock:
        lead = (lock.taken_over,) if lock.taken_over else ()
        with ctx.store() as store:
            variant = store.load(project_id).variant(PLATFORM_PAGES)
        if variant.status != st.MERGE_PENDING:
            raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.PUBLISH_FAILED}, detail="병합을 기다리는 글(MERGE_PENDING)만 '병합하지 않기로 했어요' 로 정리한다")
        split = st.split_remote_id(variant.remote_id)
        _mark_failed(ctx, project_id, "PAGES_MERGE_ABANDONED")
        try:
            stale = journal.read(project_id)
            note = journal.remove(project_id, only=stale) if stale is not None else ""
        except AppError as error:
            note = f"읽을 수 없는 발행 기록 파일은 그대로 두었습니다({error.code}): {project_id}.json"
        left = f"올려 둔 가지({split[0]})는 GitHub 에 그대로 남아 있습니다 — 필요 없으면 GitHub 에서 직접 지워 주세요(앱은 올라간 것을 지우지 않습니다)." if split else "올려 둔 가지는 GitHub 에 그대로 남아 있습니다 — 필요 없으면 직접 지워 주세요."
        steps = ("병합하지 않기로 하고 이 글을 정리했습니다 — 글은 공개되지 않았습니다.", left, "상태를 '실패(PUBLISH_FAILED)' 로 바꿨습니다 — 다시 올리려면 글을 다시 만들어(review) 검토·승인합니다.") + ((note,) if note else ())
        return CancelReport(project_id, st.PUBLISH_FAILED, lead + steps)


def _cancel_unrecorded(ctx, project_id, variant, journal, lead):
    """승인됨(APPROVED)인데 이 글의 commit 이 기록 없이 남은 경우(옛 방식으로 올리다 commit 직후에 멈춘 흔적) — `discard_commit` 이 허락할 때만 그 commit 을 되돌리고 PUBLISH_FAILED(PUBLISH_CANCELLED)로 남긴다.
    이 글의 승인한 렌더링과 한 글자도 다르지 않은 앱의 commit 하나뿐일 때만 이 글의 것으로 본다 — 아니면 STATUS_TRANSITION_INVALID(아무것도 바꾸지 않는다)."""
    wrong = AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.PUBLISH_FAILED},
                     detail="옛 방식으로 이 PC 에 기록해 둔 글(COMMITTED)이거나, 옛 방식으로 올리다 commit 직후에 멈춰 이 글의 commit 이 기록 없이 남은 승인된 글만 이 명령으로 되돌린다")
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
    steps = ("옛 방식으로 올리다 기록 직후에 멈춰 남은 이 글의 commit 을 되돌리고 글 파일을 치웠습니다.", "상태를 '실패(PUBLISH_FAILED)' 로 바꿨습니다 — 다시 올리려면 글을 다시 만들어(review) 검토·승인합니다.") + ((note,) if note else ())
    return CancelReport(project_id, st.PUBLISH_FAILED, lead + steps)


def cancel_pages_publish(ctx, text_id, *, confirmed):
    """**옛 방식**으로 이 PC 에 기록해 둔 글 기록(COMMITTED)을 되돌리고 PUBLISH_FAILED(PUBLISH_CANCELLED)로 남긴다 — 이 PC 안의 일뿐이다(네트워크 없음). 확인이 있어야 하고, `discard_commit` 이 허락할 때만 되돌린다.
    옛 방식으로 올리다 commit 직후에 멈춘 승인된 글(APPROVED)의 commit 도 같은 조건으로 되돌린다. 새 가지에 올려 병합을 기다리는 글은 이 명령이 아니라 `abandon` 으로 정리한다. 올리는 명령과 같은 글의 잠금을 쓴다."""
    capabilities.require_external_write("올리지 않은 글 기록 되돌리기")        # 저장소를 바꾸는 올리기 흐름의 일부 — 이 시험 버전에서는 올리기 자체가 꺼져 있다
    require_confirmation(confirmed, "올리지 않은 글 기록 되돌리기")
    journal = Journal(ctx.workspace.journal_dir)
    with ctx.store() as store:
        project_id = resolve_id(store, text_id)
    with publish_lock(ctx, project_id) as lock:
        with _repo_section(ctx, ctx.repo_path_or_none()) as rlock:     # 되돌리기도 저장소를 바꾼다 — 다른 글이 같은 저장소를 쓰는 중이면 기다리다 물러난다
            lead = _lead(lock, rlock)
            with ctx.store() as store:
                variant = store.load(project_id).variant(PLATFORM_PAGES)
            if variant.status == st.APPROVED:
                return _cancel_unrecorded(ctx, project_id, variant, journal, lead)
            if variant.status == st.MERGE_PENDING:
                raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.PUBLISH_FAILED},
                               detail=f"새 가지에 올려 병합을 기다리는 글이다 — 병합하지 않기로 했으면 `abandon {project_id[:8]} --yes` 로 정리한다(앱은 올라간 가지를 지우지 않는다)")
            if variant.status in (st.PUSHED, st.PUBLISHED):
                raise _already_pushed(project_id, variant.status, lost_record=variant.status == st.PUSHED and journal.missing(project_id))
            if variant.status != st.COMMITTED:
                raise AppError("STATUS_TRANSITION_INVALID", {"현재 상태": variant.status, "요청 상태": st.PUBLISH_FAILED}, detail="옛 방식으로 이 PC 에 기록해 둔 글(COMMITTED)만 되돌린다")
            record = journal.read(project_id)
            if record is None:
                raise AppError("SETTINGS_INVALID", {"파일": f"{project_id}.json"}, detail="되돌릴 발행 기록 파일이 없다")
            repo = ctx.repo_path()
            try:
                _undo_commit(ctx, repo, record.path)
            except AppError as error:
                if error.code == UNEXPECTED and ctx.backend.on_remote(repo, record.path):          # 이미 원격 main 에 들어간 글은 되돌리지 않는다
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
        how = f"상태는 아직 '이 PC 에 기록함(COMMITTED)' 이지만 원격 main 에 이미 올라가 있다 — 올라간 글은 되돌리지 않는다. 글은 이 앱이 아니라 저장소에서 확인한다(`delete {short} --yes` 로 이 글의 기록만 지울 수 있다)"
    elif status == st.PUSHED and lost_record:
        how = (f"상태는 '올림(PUSHED)' 인데 발행 기록 파일이 없어 `check-deploy` 로 공개 확인을 이어갈 수 없다 — 올라간 글은 되돌리지 않는다(공개 주소는 사이트에서 직접 확인한다). "
               f"이 글의 기록이 필요 없으면 `delete {short} --yes` 로 지운다")
    elif status == st.PUSHED:
        how = f"상태가 '올림(PUSHED)' 이다 — `check-deploy {short}` 로 공개 확인을 마친다"
    else:
        how = "이미 공개된(PUBLISHED) 글이다 — 공개한 글을 내리려면 chanceblog 저장소에서 사람이 한다"
    return AppError("PUBLISH_ALREADY_PUSHED", {"파일": path or "이 글"}, detail=how)
