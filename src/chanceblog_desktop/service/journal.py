"""올리는 중인 글의 기록(발행 기록) — 글 하나를 연결한 chanceblog 에 commit 한 뒤 push·배포 확인을 마칠 때까지의 '어디까지 했나'.

상태(COMMITTED·PUSHED)만으로는 글 파일의 경로(`_posts/<분야>/날짜-언어-시각.md`, 시각은 올리는 순간의 한국 시각)를 알 수 없어서, 멈췄다가 이어서 올리거나(`publish-pages`)·공개 확인을 다시 하거나(`check-deploy`)·
올리지 않은 글 기록을 되돌릴 때(`publish-pages --cancel`) 필요한 것을 사용자 데이터 폴더의 작은 JSON 파일에 남긴다. 저장소 상대 경로와 커밋 번호뿐이고 이 PC 의 절대경로·키는 적지 않는다.
파일이 깨졌거나 모양이 틀리면 읽지 않고 SETTINGS_INVALID 로 멈춘다(그 파일은 건드리지 않는다). 이 기록이 틀려도 push 는 안전하다 — `publish.pages.push_commit` 이 올릴 것이 정확히 이 글 하나인지 다시 확인한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..errors import AppError
from ..publish.pages import POST_PATH
from .context import write_json

STAGE_COMMITTED = "committed"      # 이 PC 의 저장소에 기록(commit)했고 아직 올리지 않았다
STAGE_PUSHED = "pushed"            # 원격 main 에 올렸고 공개 주소 확인은 끝나지 않았다
STAGES = (STAGE_COMMITTED, STAGE_PUSHED)
SCHEMA = 1
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HASH = re.compile(r"^[0-9a-f]{40,64}$")
_KEYS = {"schema", "project_id", "path", "commit", "base", "stage"}


@dataclass(frozen=True)
class PublishRecord:
    project_id: str
    path: str            # 저장소 루트 기준 글 경로(/ 구분)
    commit: str          # 글을 담은 커밋(올린 뒤에는 원격 main 에 들어간 것)
    base: str            # 그 커밋의 부모 = 쓰기 직전의 원격 main
    stage: str


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
        except (OSError, ValueError) as error:
            raise bad(f"읽을 수 없다: {type(error).__name__}") from None
        if not isinstance(raw, dict) or set(raw) != _KEYS or raw["schema"] != SCHEMA or raw["project_id"] != project_id:
            raise bad("칸이 올바르지 않다")
        path, commit, base, stage = raw["path"], raw["commit"], raw["base"], raw["stage"]
        if (not isinstance(path, str) or not POST_PATH.fullmatch(path) or not isinstance(commit, str) or not _HASH.match(commit) or not isinstance(base, str)
                or not _HASH.match(base) or stage not in STAGES):
            raise bad("값이 올바르지 않다")
        return PublishRecord(project_id, path, commit, base, stage)

    def write(self, record):
        if not isinstance(record, PublishRecord) or record.stage not in STAGES:
            raise AppError("CONTENT_INVALID", {"항목": "발행 기록"})
        write_json(self._file(record.project_id), {
            "schema": SCHEMA, "project_id": record.project_id, "path": record.path, "commit": record.commit, "base": record.base, "stage": record.stage,
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
