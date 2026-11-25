"""올리는 중인 글의 기록(발행 기록) — 글 하나를 연결한 chanceblog 에 commit 한 뒤 push·배포 확인을 마칠 때까지의 '어디까지 했나'.

상태(COMMITTED·PUSHED)만으로는 글 파일의 경로(`_posts/<분야>/날짜-언어-시각.md`, 시각은 올리는 순간의 한국 시각)를 알 수 없어서, 멈췄다가 이어서 올리거나(`publish-pages`)·공개 확인을 다시 하거나(`check-deploy`)·
올리지 않은 글 기록을 되돌릴 때(`publish-pages --cancel`) 필요한 것을 사용자 데이터 폴더의 작은 JSON 파일에 남긴다. 저장소 상대 경로와 커밋 번호뿐이고 이 PC 의 절대경로·키는 적지 않는다.
파일이 깨졌거나 모양이 틀리면 읽지 않고 SETTINGS_INVALID 로 멈춘다(그 파일은 건드리지 않는다). 이 기록이 틀려도 안전하다 — 새 가지에 올리는 `publish.pages.push_branch` 는 올릴 것이 정확히 이 글 하나인지(그 커밋의 변경이 글 파일 하나뿐인지)
다시 확인하고 main 으로는 어떤 경우에도 올리지 않는다.

판 2(PUBPR): 칸 `branch`(올린 가지 이름)와 단계 `built`(가지에 올릴 커밋을 객체로 만들었고 아직 올리지 않았다)·`branch_pushed`(새 가지에 올렸고 병합을 기다린다)를 더했다 — `built` 를 push 전에 적어 두어
push 직후에 앱이 죽어도 다음 실행이 같은 가지의 끝을 보고 이어 간다(같은 일을 두 번 해도 같은 결과). 판 1 기록(칸 6개)은 `branch` 가 빈 글인 것으로 읽는다. 옛 버전 프로그램은 판 2 기록을 SETTINGS_INVALID 로 거절한다(그 파일은 건드리지 않는다).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..errors import AppError
from ..publish.gitrepo import BRANCH_NAME
from ..publish.pages import POST_PATH
from .context import write_json

STAGE_COMMITTED = "committed"      # 이 PC 의 저장소에 기록(commit)했고 아직 올리지 않았다(옛 방식 — 새 흐름은 이 단계를 만들지 않는다)
STAGE_PUSHED = "pushed"            # 원격 main 에 들어갔다(새 흐름: 병합을 확인했다) — 공개 주소 확인은 끝나지 않았다
STAGE_BUILT = "built"              # 새 가지에 올릴 커밋을 객체로 만들었고 아직 올리지 않았다(`branch`·`commit`·`base` 가 있다)
STAGE_BRANCH_PUSHED = "branch_pushed"   # 새 가지에 올렸고 사람이 병합하기를 기다린다
STAGES = (STAGE_COMMITTED, STAGE_PUSHED, STAGE_BUILT, STAGE_BRANCH_PUSHED)
BRANCH_STAGES = (STAGE_BUILT, STAGE_BRANCH_PUSHED)
SCHEMA = 2
LEGACY_SCHEMA = 1                  # 판 1 기록(칸 6개 — `branch` 없음)은 계속 읽는다
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HASH = re.compile(r"^[0-9a-f]{40,64}$")
_LEGACY_KEYS = {"schema", "project_id", "path", "commit", "base", "stage"}
_KEYS = _LEGACY_KEYS | {"branch"}


@dataclass(frozen=True)
class PublishRecord:
    project_id: str
    path: str            # 저장소 루트 기준 글 경로(/ 구분)
    commit: str          # 글을 담은 커밋(올린 뒤에는 원격 main 에 들어간 것 — 가지 단계에서는 가지 끝 커밋)
    base: str            # 그 커밋의 부모 = 쓰기 직전의 원격 main
    stage: str
    branch: str = ""     # 올린 가지 이름(`desktop/post-…`) — 가지 단계에서 필수, 옛 방식 기록은 빈 글


def _branch_ok(stage, branch):
    """가지 칸이 단계와 맞는가 — 가지 단계(`built`·`branch_pushed`)는 가지 이름이 정해진 모양이어야 하고, 옛 방식 단계(`committed`)는 비어 있어야 하며,
    `pushed`(병합을 확인했거나 옛 방식으로 올렸다)는 비어 있거나 정해진 모양이면 된다."""
    if not isinstance(branch, str):
        return False
    if branch == "":
        return stage not in BRANCH_STAGES
    return stage != STAGE_COMMITTED and BRANCH_NAME.fullmatch(branch) is not None


class Journal:
    def __init__(self, folder):
        self.folder = Path(folder)

    def _file(self, project_id):
        if not isinstance(project_id, str) or not _ID.match(project_id):
            raise AppError("CONTENT_INVALID", {"항목": "프로젝트 번호"})
        return self.folder / f"{project_id}.json"

    def read(self, project_id):
        """기록. 없으면 None, 모양이 틀리면 SETTINGS_INVALID."""
        target = self._file(project_id)
        if not target.exists():
            return None

        def bad(why):
            return AppError("SETTINGS_INVALID", {"파일": target.name}, detail=why)

        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError) as error:             # 아주 깊게 겹친 JSON 의 RecursionError 도 같은 쉬운 거절이다(AS-S1 참고-18, D-612 — `context.py` 와 같은 처리)
            raise bad(f"읽을 수 없다: {type(error).__name__}") from None
        legacy = isinstance(raw, dict) and set(raw) == _LEGACY_KEYS and raw["schema"] == LEGACY_SCHEMA and type(raw["schema"]) is int
        if not isinstance(raw, dict) or not (legacy or (set(raw) == _KEYS and raw["schema"] == SCHEMA and type(raw["schema"]) is int)) or raw["project_id"] != project_id:
            raise bad("칸이 올바르지 않다")
        path, commit, base, stage = raw["path"], raw["commit"], raw["base"], raw["stage"]
        branch = "" if legacy else raw["branch"]
        if (not isinstance(path, str) or not POST_PATH.fullmatch(path) or not isinstance(commit, str) or not _HASH.match(commit) or not isinstance(base, str)
                or not _HASH.match(base) or stage not in STAGES or not _branch_ok(stage, branch) or (legacy and stage in BRANCH_STAGES)):
            raise bad("값이 올바르지 않다")
        return PublishRecord(project_id, path, commit, base, stage, branch)

    def missing(self, project_id):
        """그 글의 발행 기록 파일이 없는가. 읽을 수 없는 기록은 '없다' 가 아니라 '있는데 못 읽는다' 라서 False — 그 문제는 읽는 명령이 SETTINGS_INVALID 로 알린다."""
        try:
            return self.read(project_id) is None
        except AppError:
            return False

    def write(self, record):
        if not isinstance(record, PublishRecord) or record.stage not in STAGES or not _branch_ok(record.stage, record.branch):
            raise AppError("CONTENT_INVALID", {"항목": "발행 기록"})
        write_json(self._file(record.project_id), {
            "schema": SCHEMA, "project_id": record.project_id, "path": record.path, "commit": record.commit, "base": record.base, "stage": record.stage, "branch": record.branch,
        })

    def remove(self, project_id, *, only=None):
        """기록을 지운다. 지우지 못했으면 이유 글을, 잘 지웠거나 원래 없었으면 ''(남아 있어도 이미 끝난 글이면 해롭지 않아 오류로 만들지 않고 알린다).

        `only` 를 주면(PublishRecord) **지금 파일의 내용이 그 기록과 똑같을 때만** 지운다 — 이 실행이 쓴 기록만 지우고, 그 사이 다른 실행이 쓴 기록(올라간 글의 '올림' 기록 등)은
        건드리지 않는다(실패한 쪽이 성공한 쪽의 기록을 지워 글은 올라갔는데 앱은 그 사실을 잊는 일을 막는다). 읽을 수 없는 기록도 지우지 않는다."""
        target = self._file(project_id)
        if only is not None:
            try:
                current = self.read(project_id)
            except AppError as error:
                return f"발행 기록 파일을 읽을 수 없어(오류 코드 {error.code}) 지우지 않았다: {target.name}"
            if current is None:
                return ""
            if current != only:
                return f"발행 기록이 이 실행이 쓴 것과 달라(다른 작업이 쓴 기록) 지우지 않았다: {target.name}"
        try:
            target.unlink()
        except FileNotFoundError:
            return ""
        except OSError as error:
            return f"발행 기록 파일을 지우지 못했다({type(error).__name__}): {target.name}"
        return ""
