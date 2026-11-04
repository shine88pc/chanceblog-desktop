"""글(프로젝트) 다루기 — 만들기·기존 HTML 글 불러오기·목록·보기·고치기·지우기·백업·복구(`content/store.py` 위에서).

상태 흐름과 '원고를 고치면 승인이 풀린다' 는 규칙은 `content/model.py`·`status.py` 가 지킨다 — 여기서는 그 규칙을 우회하지 않고 그대로 부른다(잘못된 단계는 STATUS_TRANSITION_INVALID).
지우기·백업으로 되돌리기는 `--yes` 같은 확인(confirmed=True)이 있어야만 하고, 아직 올리지 않은 글 기록(COMMITTED)이 있는 글은 지우지 않는다(연결한 저장소에 주인 없는 커밋이 남지 않게).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from ..content import status as st
from ..content.model import Asset, ContentProject
from ..echo import shown_backup, shown_ref
from ..errors import AppError
from ..render.markdown import html_to_markdown
from .gate import require_clean_title
from .journal import Journal

MIN_PREFIX = 4
MAX_MANUSCRIPT_BYTES = 2 * 1024 * 1024         # 원고(Markdown·가져올 HTML)의 최대 크기
_BACKUP_NAME = re.compile(r"^chanceblog-\d{8}-\d{6}\.db$")


def require_confirmation(confirmed, what):
    """되돌릴 수 없거나 저장소에 올리는 일은 확인(`confirmed is True`)이 있어야만 한다. 아니면 CONFIRMATION_REQUIRED(아무것도 하지 않는다)."""
    if confirmed is not True:
        raise AppError("CONFIRMATION_REQUIRED", {"항목": what})


def resolve_id(store, text):
    """글 번호(전체 또는 앞 4자 이상이 겹치지 않는 앞부분) → 전체 번호. 없는 번호를 쳤을 때 오류 문구는 친 글을 **번호 모양일 때만** 되풀이한다(`echo.shown_ref` — 키를 번호 자리에 잘못 쳐도 문구·`--json`·기록에 남지 않게)."""
    wanted = text.strip() if isinstance(text, str) else ""
    if not wanted:
        raise AppError("CONTENT_INVALID", {"항목": "글 번호"})
    ids = [summary.project_id for summary in store.list()]
    if wanted in ids:
        return wanted
    if len(wanted) < MIN_PREFIX:
        raise AppError("CONTENT_NOT_FOUND", {"항목": shown_ref(wanted)}, detail=f"번호는 전체 또는 앞 {MIN_PREFIX}자 이상으로 적는다")
    matches = [item for item in ids if item.startswith(wanted)]
    if not matches:
        raise AppError("CONTENT_NOT_FOUND", {"항목": shown_ref(wanted)})
    if len(matches) > 1:
        raise AppError("CONTENT_INVALID", {"항목": "글 번호(여러 글과 맞음)"}, detail=f"{len(matches)}개의 글이 이 앞부분으로 시작한다 — 더 길게 적는다")
    return matches[0]


@dataclass(frozen=True)
class VariantView:
    platform: str
    status: str
    rendered_revision: object
    has_rendering: bool
    published_url: object
    published_at: object
    error_code: object

    def to_dict(self):
        return {"platform": self.platform, "status": self.status, "rendered_revision": self.rendered_revision, "has_rendering": self.has_rendering,
                "published_url": self.published_url, "published_at": self.published_at, "error_code": self.error_code}


@dataclass(frozen=True)
class ProjectView:
    project_id: str
    title: str
    revision: int
    created_at: str
    updated_at: str
    references: tuple
    assets: tuple             # Asset
    source_content: str
    variants: tuple           # VariantView

    def variant(self, platform):
        return next(item for item in self.variants if item.platform == platform)

    def to_dict(self, *, with_text=False):
        data = {"project_id": self.project_id, "title": self.title, "revision": self.revision, "created_at": self.created_at, "updated_at": self.updated_at,
                "references": list(self.references), "assets": [asset.to_dict() for asset in self.assets], "source_chars": len(self.source_content),
                "variants": [item.to_dict() for item in self.variants]}
        if with_text:
            data["source_content"] = self.source_content
        return data


def view(project):
    return ProjectView(
        project.project_id, project.title, project.revision, project.created_at, project.updated_at, tuple(project.references), tuple(project.assets), project.source_content,
        tuple(VariantView(name, project.variants[name].status, project.variants[name].rendered_revision, bool(project.variants[name].rendered), project.variants[name].published_url,
                          project.variants[name].published_at, project.variants[name].error_code) for name in st.PLATFORMS))


@dataclass(frozen=True)
class ProjectRow:
    project_id: str
    title: str
    revision: int
    updated_at: str
    statuses: dict            # 플랫폼 → 상태 (글을 읽을 수 없으면 비어 있다)
    error: str                # 읽을 수 없을 때의 오류 코드('' 이면 정상)

    def to_dict(self):
        return {"project_id": self.project_id, "title": self.title, "revision": self.revision, "updated_at": self.updated_at, "statuses": dict(self.statuses), "error": self.error}


@dataclass(frozen=True)
class EditResult:
    project: ProjectView
    changed: bool
    reset_platforms: tuple    # 원고를 고쳐서 상태가 되돌아간(승인이 풀린) 플랫폼

    def to_dict(self):
        return {"changed": self.changed, "reset_platforms": list(self.reset_platforms), "project": self.project.to_dict()}


def check_manuscript(text, what="원고"):
    """원고(또는 가져올 HTML)가 받을 수 있는 모양인가 — NUL 글자(\\x00)가 없고 2MB 이하여야 한다(아니면 CONTENT_INVALID). 아주 큰 입력이 저장소와 검사를 느리게 만들지 못하게."""
    if isinstance(text, str):
        if "\x00" in text:
            raise AppError("CONTENT_INVALID", {"항목": what}, detail="NUL 글자(\\x00)가 들어 있다")
        if len(text) > MAX_MANUSCRIPT_BYTES // 4 and len(text.encode("utf-8", "surrogatepass")) > MAX_MANUSCRIPT_BYTES:
            raise AppError("CONTENT_INVALID", {"항목": what}, detail=f"너무 크다(최대 {MAX_MANUSCRIPT_BYTES // (1024 * 1024)}MB)")


def check_title(title):
    """제목은 글 머리말의 `title` 이 되므로 머리말 값과 같은 검사를 만들 때·고칠 때 미리 한다(줄바꿈·제어 문자·HTML 태그·`{{ }}`·위험한 주소 — 걸리면 CHECK_FAILED). 글자가 아니면 모델이 CONTENT_INVALID 로 거절한다."""
    if isinstance(title, str):
        require_clean_title(title)


def new_project(ctx, title, markdown, *, references=(), assets=()):
    """Markdown 글로 새 프로젝트를 만든다(제목·본문 검사는 모델이 한다 — CONTENT_INVALID). 원고는 NUL 글자가 없고 2MB 이하여야 하고, 제목은 머리말 값 검사(`check_title`)를 통과해야 한다."""
    check_manuscript(markdown)
    check_title(title)
    project = ContentProject.new(title, markdown, tuple(references), tuple(assets), now=ctx.stamp())
    with ctx.store() as store:
        store.save(project)
    return view(project)


def import_html(ctx, title, html, *, references=(), assets=()):
    """기존 글(HTML)을 Markdown 으로 바꿔 새 프로젝트로 불러온다(허용 태그만 남는다 — 스크립트·속성은 사라진다)."""
    check_manuscript(html, "HTML 글")
    markdown = html_to_markdown(html)
    if not markdown.strip():
        raise AppError("CONTENT_INVALID", {"항목": "본문"}, detail="HTML 에서 글자를 찾지 못했다")
    return new_project(ctx, title, markdown, references=references, assets=assets)


def list_projects(ctx):
    rows = []
    with ctx.store() as store:
        for summary in store.list():
            try:
                project = store.load(summary.project_id)
            except AppError as error:
                rows.append(ProjectRow(summary.project_id, summary.title, summary.revision, summary.updated_at, {}, error.code))
                continue
            rows.append(ProjectRow(summary.project_id, summary.title, summary.revision, summary.updated_at, {name: item.status for name, item in project.variants.items()}, ""))
    return rows


def show_project(ctx, text_id):
    with ctx.store() as store:
        return view(store.load(resolve_id(store, text_id)))


def edit_project(ctx, text_id, *, title=None, markdown=None, references=None, assets=None):
    """원고(제목·본문·출처·이미지)를 고친다. 바뀐 것이 있으면 판 번호가 오르고, 검토·승인·복사 중이던 플랫폼은 '글 만듦' 으로 돌아가 처음부터 다시 검토한다(모델의 규칙)."""
    if markdown is not None:
        check_manuscript(markdown)
    if title is not None:
        check_title(title)
    with ctx.store() as store:
        project = store.load(resolve_id(store, text_id))
        before = {name: item.status for name, item in project.variants.items()}
        changed = project.edit(title=title, source_content=markdown, references=references, assets=assets, now=ctx.stamp())
        if changed:
            store.save(project)
        reset = tuple(name for name, item in project.variants.items() if before[name] != item.status)
        return EditResult(view(project), changed, reset)


def _must_finish_first(ctx, project_id, project):
    """지우면 안 되는 글(올리다 만 글)이면 그 이유를 AppError 로 돌려준다 — 아니면 None.
     · 올리지 않은 글 기록(COMMITTED): 연결한 저장소에 주인 없는 commit 이 남는다 — 먼저 올리거나 취소한다.
     · 올렸지만 공개 확인이 끝나지 않은 글(PUSHED): 지우면 발행 기록 파일도 함께 지워져 `check-deploy` 로 이을 수 없게 되고(지웠다가 백업으로 되살려도 기록은 되살아나지 않는다 — 기록 없는 '올림' 글은
       `check-deploy`·`publish-pages`·`--cancel` 이 서로를 가리키며 막힌다), 그러면 지우기 전의 백업으로도 마칠 수 없다 — 먼저 `check-deploy` 로 마친다.
       단 이미 발행 기록이 없는 '올림' 글(백업으로 되돌리다 생긴 것)은 어떻게 해도 이을 수 없으므로 지울 수 있다(잃는 것이 없다). 읽을 수 없는 기록은 SETTINGS_INVALID 로 그대로 알린다."""
    status = project.variant("github_pages").status
    if status == st.COMMITTED:
        return AppError("STATUS_TRANSITION_INVALID", {"현재 상태": st.COMMITTED, "요청 상태": "삭제"}, detail="올리지 않은 글 기록이 남아 있다 — 먼저 올리거나 취소한다")
    if status == st.PUSHED and Journal(ctx.workspace.journal_dir).read(project_id) is not None:
        return AppError("STATUS_TRANSITION_INVALID", {"현재 상태": st.PUSHED, "요청 상태": "삭제"},
                        detail=f"원격 main 에는 올라갔지만 공개 확인이 끝나지 않은 글이다 — 지우면 발행 기록도 함께 지워져 공개 확인을 이어갈 수 없다. 먼저 `check-deploy {project_id[:8]}` 로 공개 확인을 마친 뒤 지운다")
    return None


def delete_project(ctx, text_id, *, confirmed):
    """글을 지운다(되돌릴 수 없다 — confirmed=True 가 있어야 한다). 올리지 않은 글 기록(COMMITTED)이 있으면 먼저 올리거나 취소해야 하고, 올렸지만 공개 확인이 끝나지 않은 글(PUSHED)은 먼저 `check-deploy` 로 마쳐야 한다."""
    require_confirmation(confirmed, "글 지우기")
    with ctx.store() as store:
        project_id = resolve_id(store, text_id)
        try:
            project = store.load(project_id)
        except AppError as error:
            if error.code != "STORE_CORRUPT":
                raise
            project = None                         # 읽을 수 없는 글도 운영자가 지울 수 있어야 한다
        problem = _must_finish_first(ctx, project_id, project) if project is not None else None
        if problem is not None:
            raise problem
        pushed = project is not None and project.variant("github_pages").status in (st.PUSHED, st.PUBLISHED)
        folder = ctx.workspace.backups_dir / "before-delete"
        saved = store.backup(folder, now=_free_moment(ctx, folder, store))             # 지우기 직전 상태를 먼저 백업한다 — 잘못 지웠으면 restore 로 되살릴 수 있다
        store.delete(project_id)
    note = Journal(ctx.workspace.journal_dir).remove(project_id)
    kept = "이 PC 의 글 기록만 지웠습니다 — 이미 올라간 글은 연결한 저장소에 그대로 있습니다(이 앱은 올라간 글을 지우지 않습니다). " if pushed else ""
    return project_id, (note + " | " if note else "") + kept + f"지우기 직전 상태를 백업해 두었습니다(잘못 지웠으면 `restore 그파일 --yes` 로 되살립니다 — 확인 표시가 있어야 합니다): {saved}"


def backup_store(ctx):
    """글 저장소의 점검한 사본을 백업 폴더에 만든다(오래된 것은 최근 10개만 남긴다). 만든 파일 경로를 돌려준다."""
    with ctx.store() as store:
        return store.backup(ctx.workspace.backups_dir, now=ctx.now())


def list_backups(ctx):
    folder = ctx.workspace.backups_dir
    if not folder.is_dir():
        return []
    return sorted((entry for entry in folder.iterdir() if entry.is_file() and _BACKUP_NAME.match(entry.name)), key=lambda entry: entry.name, reverse=True)


def resolve_backup(ctx, backup_path=None, *, latest=False):
    """어느 백업 파일로 되돌릴지(가장 최근 백업이거나 적어 준 파일). 파일을 열지 않고 이름만 정한다 — 지금 쓰고 있는 저장소 파일 자체이거나 고를 백업이 없으면 오류."""
    if latest:
        found = list_backups(ctx)
        if not found:
            raise AppError("CONTENT_NOT_FOUND", {"항목": "백업 파일"}, detail="백업 폴더에 백업이 없다")
        source = found[0]
    elif backup_path:
        source = Path(backup_path)
    else:
        raise AppError("CONTENT_INVALID", {"항목": "백업 파일"})
    if _same_file(source, ctx.workspace.store_path):
        raise AppError("CONTENT_INVALID", {"항목": "백업 파일"}, detail="지금 쓰고 있는 글 저장소 파일 자체는 백업이 아니다 — backups 폴더의 백업을 고른다")
    return source


def restore_store(ctx, backup_path=None, *, latest=False, confirmed):
    """백업 파일의 내용으로 글 저장소를 바꾼다 — 지금 글 저장소의 내용이 통째로 바뀌므로 확인(`confirmed=True`)이 있어야 한다(아니면 CONFIRMATION_REQUIRED, 아무것도 바꾸지 않는다).
    바꾸기 직전 상태는 `backups/before-restore` 에 먼저 백업한다. 온전한 백업이 아니거나 글 내용이 깨진 백업이면 아무것도 바꾸지 않는다."""
    require_confirmation(confirmed, "백업으로 되돌리기")
    source = resolve_backup(ctx, backup_path, latest=latest)
    safety = ctx.workspace.backups_dir / "before-restore"
    with ctx.store() as store:
        saved = store.backup(safety, now=_free_moment(ctx, safety, store))              # 바꾸기 직전 상태 — 같은 초에 두 번 복구해도 앞 사본을 덮어쓰지 않는다
        try:
            store.restore_from(source)
        except AppError as error:
            raise _without_typed_backup(error, source) from None
        problems = store.check()
        if problems:                                                                      # 구조만 멀쩡하고 글 내용이 깨진 백업 — 방금 만든 사본으로 원래대로 돌린다
            store.restore_from(saved)
            raise AppError("STORE_CORRUPT", {"파일": shown_backup(Path(source).name)}, detail="백업의 글 내용이 올바르지 않아 복구하지 않고 원래대로 돌렸다: " + problems[0])
    return source, safety


def _without_typed_backup(error, source):
    """백업 파일을 열다 난 오류(`restore_from`)의 칸에서 사용자가 친 경로·파일 이름을 지운다 — 앱이 만든 백업 이름 모양이면 이름만 남기고, 아니면 `(입력한 파일)`
    (경로 자리에 키를 잘못 쳤을 수 있다). 지금 쓰는 글 저장소 쪽 오류의 칸은 친 값이 아니므로 그대로 둔다."""
    typed = (str(source), Path(source).name)
    for key, value in list(error.slots.items()):
        if value in typed:
            error.slots[key] = shown_backup(Path(source).name)
    return error


def _same_file(first, second):
    try:
        return os.path.samefile(first, second)
    except OSError:
        return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def _free_moment(ctx, folder, store):
    """그 폴더에 아직 없는 사본 이름이 되는 가장 가까운 시각 — 사본 이름이 초 단위라서 같은 초에 두 번 만들면 앞의 것을 덮어쓰기 때문이다."""
    moment = ctx.now()
    stem = store.path.stem
    for _ in range(3600):
        if not (Path(folder) / f"{stem}-{moment.strftime('%Y%m%d-%H%M%S')}.db").exists():
            return moment
        moment += timedelta(seconds=1)
    return moment


def parse_asset(text):
    """`파일이름|설명|문단번호`(설명·번호는 생략 가능) → Asset. 모양이 틀리면 CONTENT_INVALID."""
    parts = [part.strip() for part in str(text).split("|")]
    if not parts[0] or len(parts) > 3:
        raise AppError("CONTENT_INVALID", {"항목": "이미지"}, detail="`파일이름|설명|문단번호` 모양이어야 한다")
    position = 0
    if len(parts) == 3 and parts[2]:
        if not parts[2].isdigit():
            raise AppError("CONTENT_INVALID", {"항목": "이미지 위치"})
        position = int(parts[2])
    return Asset(parts[0], parts[1] if len(parts) > 1 else "", position)
