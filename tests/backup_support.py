"""전체 백업·복원(`service/backup_flow.py`) 시험 도우미(시험이 아니다) — 임시 데이터 폴더에 글·초안·후보·주제 엔진·설정을 채우는 `World`, 키 모양 글 만들기(실행할 때 조각을 이어 붙인다), 폴더 지문·보관함 덤프 같은 비교 도구.

시험 파일들이 `import backup_support as bs` 로 쓴다. 네트워크·실제 시계·실제 자격 증명 관리자 없이 돈다(`service_support.make_ctx` 는 가짜 보관소와 가짜 시계를 쓴다).
"""
import atexit
import contextlib
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scan_samples as S  # noqa: E402
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop.content.store import _read_only_uri  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.service import candidates, projects  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.service.context import write_json  # noqa: E402
from chanceblog_desktop.topicdb.store import open_for_write  # noqa: E402
from chanceblog_desktop.topics import layout, schedule  # noqa: E402

STAMP = "2026-11-11T05:00:00Z"
KINDS = S.KINDS


def secret_text(kind):
    """유형 하나의 키 모양 글 한 줄(앞에 낱말이 붙은 모양) — 저장소에는 완성된 키 모양이 없고 실행할 때 만들어진다."""
    return S.sample(kind)[1]


def secret_token(kind):
    """그 유형의 키 모양 글 중 '발견 자리' 글(토큰 본문) — 출력에 새는지 볼 때 쓴다."""
    return S.sample(kind)[0]


def plant_post(world, text, title="키가 든 글"):
    """글 한 편을 만들고 본문에 키 모양 글을 보관함에 **직접** 쓴다 — 앱의 쓰기 함수는 쓰기 단계에서 키 모양을 거절한다(PCSEC1 M3). 거절이 생기기 전에 쓴 옛 데이터를 흉내 낸다(열과 자료는 그대로라 점검은 통과한다)."""
    view = projects.new_project(world.ctx, title, "평범한 본문")
    with contextlib.closing(sqlite3.connect(str(world.path("chanceblog.db")))) as connection:
        connection.execute("UPDATE projects SET data = json_set(data, '$.source_content', ?) WHERE project_id = ?", (text, view.project_id))
        connection.commit()
    return view


def plant_draft(world, text):
    """저장한 초안 하나에 키 모양 글을 보관함에 직접 쓴다(`plant_post` 와 같은 까닭)."""
    with contextlib.closing(sqlite3.connect(str(world.path("chanceblog.db")))) as connection:
        connection.execute("INSERT INTO drafts (project_id, text, saved_at) VALUES (?, ?, ?) ON CONFLICT (project_id) DO UPDATE SET text = excluded.text", (world.ids[0], text, "2026-11-11T00:00:00Z"))
        connection.commit()


def three_lines(kind):
    """3번째 줄에 키 모양이 든 세 줄 글."""
    return "첫째 줄은 평범한 글이에요\n둘째 줄도 평범해요\n" + secret_text(kind) + "\n마지막 줄"


def digests(root, *, skip=("backups", "locks")):
    """폴더 안 모든 파일의 {상대 경로(as_posix): sha256} — `skip` 에 든 이름의 하위 폴더는 뺀다."""
    root = Path(root)
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not (set(path.relative_to(root).parts[:1]) & set(skip)):
            found[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def dump(path):
    """보관함 파일의 논리적 내용(SQL 덤프 줄들) — 두 파일이 '논리적으로 같은가' 를 견주는 데 쓴다."""
    with contextlib.closing(sqlite3.connect(_read_only_uri(Path(path)), uri=True)) as connection:
        return list(connection.iterdump())


def all_bytes(folder):
    """폴더 안 모든 파일의 바이트를 이어 붙인 것."""
    return b"".join(path.read_bytes() for path in sorted(Path(folder).rglob("*")) if path.is_file())


def encodings(text):
    """글 하나의 여러 모습(utf-8·utf-16·16진수·base64·퍼센트 인코딩) — 백업 파일의 모든 바이트에서 이 모습이 하나라도 있는지 본다."""
    import base64
    import urllib.parse
    raw = text.encode("utf-8")
    return {"utf-8": raw, "utf-16le": text.encode("utf-16-le"), "utf-16be": text.encode("utf-16-be"), "hex": raw.hex().encode("ascii"), "hex-upper": raw.hex().upper().encode("ascii"),
            "base64": base64.b64encode(raw), "base64-url": base64.urlsafe_b64encode(raw), "percent": urllib.parse.quote(text, safe="").encode("ascii")}


def code_of(call, *args, **kwargs):
    """AppError 가 나야 한다 — 난 오류를 돌려준다(안 나면 None)."""
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error
    return None


class World:
    """임시 폴더 안의 데이터 폴더 — 글·판 기록·저장한 초안·주제 후보(글 보관함), 주제 엔진 보관함과 JSON 셋, 설정(연결한 폴더·네이버 프로필 둘)을 채운다. 보관소는 가짜(`MemoryStore`)다."""

    def __init__(self, tmp, *, posts=2, drafts=1, candidates_count=1, engine=True, profiles=True, seeds=True, calendar=True, settings=True, clock=None, body=None):
        self.tmp = Path(tmp)
        self.ctx = ss.make_ctx(tmp, clock=clock, repo="chanceblog" if settings else None)
        if settings:
            ss.naver_profiles(self.ctx)
        self.root = self.ctx.workspace.root
        self.ctx.workspace.ensure()
        self.paths = tf.topic_paths(self.ctx.workspace)
        self.ids = []
        for number in range(posts):
            self.ids.append(projects.new_project(self.ctx, f"예시 글 {number + 1}", body or f"예시 본문 {number + 1}\n\n둘째 문단이에요.").project_id)
        if drafts and self.ids:
            with self.ctx.store() as store:
                for number in range(drafts):
                    store.save_draft(self.ids[number % len(self.ids)] if number < len(self.ids) else f"draft{number}", f"저장한 초안 {number + 1}\n둘째 줄")
        for number in range(candidates_count):
            candidates.add_candidate(self.ctx, topic=f"예시 주제 {number + 1}", keyword=f"예시키워드{number + 1}", blogs=("naver_a",), reason="예시 이유")
        if profiles or seeds or calendar:
            tf.init_files(self.paths)
        if seeds:
            tf.save_seeds(self.paths, [ts.example_seed()])
        if calendar:
            write_json(self.paths.calendar, schedule.entries_to_dict([ts.example_entry()]))
        if engine:
            with open_for_write(self.paths.database) as store:
                store.add_candidates(lambda existing: [ts.rated(70, candidate_id="cid-001", channel="naver_a"), ts.rated(66, candidate_id="cid-002", channel="naver_a", cluster="other")], now=STAMP)
        if not profiles:
            self.paths.profiles.unlink(missing_ok=True)

    @classmethod
    def cached(cls, tmp, **kwargs):
        """같은 모양의 World 를 매번 새로 채우지 않고(채우는 데 0.5초 걸린다) 처음 한 번 만든 본을 복사한다 — 많은 칸을 도는 시험이 빨라진다. 본은 시험이 끝날 때 지워진다."""
        key = tuple(sorted(kwargs.items()))
        template = _TEMPLATES.get(key)
        if template is None:
            holder = tempfile.mkdtemp(prefix="bs-template-")
            atexit.register(shutil.rmtree, holder, True)
            template = _TEMPLATES[key] = cls(holder, **kwargs)
        world = cls.__new__(cls)
        world.tmp = Path(tmp)
        world.ctx = ss.make_ctx(tmp, repo=None)
        world.root = world.ctx.workspace.root
        shutil.copytree(template.root, world.root)
        world.paths = tf.topic_paths(world.ctx.workspace)
        world.ids = list(template.ids)
        return world

    # 파일 위치
    def path(self, name):
        return bf._component_path(self.ctx, bf.BY_NAME[name])

    def backup(self, **kwargs):
        return bf.create_full_backup(self.ctx, **kwargs)

    def folder(self, outcome):
        return self.ctx.workspace.backups_dir / outcome.row.name

    def data_digests(self):
        return digests(self.root)

    def dumps(self):
        return {name: dump(self.path(name)) for name in ("chanceblog.db", layout.ENGINE_DB_FILE) if self.path(name).is_file()}

    def manifest(self, outcome):
        return json.loads((self.folder(outcome) / bf.MANIFEST_NAME).read_text(encoding="utf-8"))


_TEMPLATES = {}


def write_manifest(folder, manifest):
    Path(folder, bf.MANIFEST_NAME).write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
