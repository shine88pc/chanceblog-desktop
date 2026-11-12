"""전체 백업의 'Secret 0' 증명 시험 — 백업 직전에 키·토큰 모양을 훑고, 백업 폴더에는 자격 증명이 한 바이트도 없다(BACKUPUI, 운영자 결정 2026-11-11 4·7항).

지키는 것:
  1) **여섯 유형 × 아홉 곳**: Google API 키·GitHub 토큰·Bearer 토큰·OAuth 토큰·AWS 액세스 키·개인 키(PEM)가 원고 본문·제목·저장한 초안·글 보관함 후보·주제 보관함 후보·프로필·Seed·캘린더·`settings.json` 어디에 있어도
     **백업을 만들지 않는다**(`FULL_BACKUP_BLOCKED`). 폴더가 부분으로도 남지 않고, 지금 데이터는 한 바이트도 바뀌지 않고, 잠금은 풀린다.
  2) 알림에는 **위치(어느 칸·몇 번째 줄)와 유형만** 있다 — 오류의 문구·칸·세부·위치 목록·요약·`repr` 어디에도 키 글자(연속한 4글자)가 없다. 자동으로 지우거나 바꾸지 않고, '무시하고 백업' 은 코드에도 없다.
  3) 키를 등록한 채 백업해도 백업 폴더의 모든 바이트에 카나리가 없다(utf-8·utf-16·16진수·base64·퍼센트 인코딩) — 찾는 도구가 정말 찾는지는 양성 대조로 확인한다.
  4) 엄격한 읽기가 키 모양 글을 '틀린 모양' 으로 거절하는 JSON 도 '조용히 빠진 부분 백업' 이 아니라 '키 모양이 있어 백업하지 않음' 이다. 읽을 수 없는 파일은 담기지 않으므로 그 안의 글도 백업에 없다.
  5) 되돌릴 때도 같다: 백업 안에 키 모양이 있으면 쓰지 않고(앱이 고칠 수 없다고 말한다), 지금 데이터에 있으면 안전 사본을 못 남기므로 시작하지 않는다 — 어느 쪽이든 아무것도 바뀌지 않는다.
네트워크·실제 비밀·실제 자격 증명 관리자 없이 돈다. 키 모양은 `scan_samples` 가 실행할 때 조각을 이어 붙여 만든다.
"""
import contextlib
import dataclasses
import hashlib
import inspect
import json
import pickle
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.service import candidates, connections, projects  # noqa: E402
from chanceblog_desktop.service.context import write_json  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

S = bs.S
KINDS = bs.KINDS
AREAS = {"원고 본문": "글 보관함", "원고 제목": "글 보관함", "저장한 초안": "글 보관함", "글 보관함 후보": "글 보관함", "주제 보관함 후보": "주제 보관함", "채널 프로필": "채널 프로필", "Seed": "Seed",
         "캘린더": "캘린더", "설정": "설정"}


def sql(path, statement, params=()):
    with contextlib.closing(sqlite3.connect(str(path))) as connection:
        connection.execute(statement, params)
        connection.commit()


def patch_first(value, key, text):
    """JSON 값 안에서 `key` 칸이 처음 나오는 곳에 `text` 를 넣는다 → 넣었는가."""
    if isinstance(value, dict):
        if key in value:
            value[key] = text
            return True
        return any(patch_first(item, key, text) for item in value.values())
    if isinstance(value, list):
        return any(patch_first(item, key, text) for item in value)
    return False


def patch_json_file(path, key, text):
    """JSON 파일의 `key` 칸에 키 모양 글을 **파일에 직접** 쓴다 — 앱의 쓰기 함수는 쓰기 단계에서 키 모양을 거절한다(PCSEC1 M3). 옛 데이터(거절이 생기기 전에 쓴 파일)를 흉내 낸다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert patch_first(data, key, text), key
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def inject(world, where, kind, text):
    """한 곳에 키 모양 글을 앱이 거절하지 않는 길(보관함·파일에 직접 쓰기)로 넣는다 — 앱의 쓰기 길 검사(쓰기 단계 거절)와 따로 '백업 직전 검사' 만 시험한다. 보관함 행은 열과 자료가 서로 맞게(점검을 통과하게) 고친다."""
    ctx, store_path = world.ctx, world.path("chanceblog.db")
    if where == "원고 본문":
        bs.plant_post(world, text)
    elif where == "원고 제목":
        view = projects.new_project(ctx, "키가 든 제목", "평범한 본문")
        title = "키가 든 제목 " + text.replace("\n", " ")
        sql(store_path, "UPDATE projects SET title = ?, data = json_set(data, '$.title', ?) WHERE project_id = ?", (title, title, view.project_id))
    elif where == "저장한 초안":
        bs.plant_draft(world, text)
    elif where == "글 보관함 후보":
        candidates.add_candidate(ctx, topic="평범한 주제", keyword="평범한키워드", blogs=("naver_a",), reason="평범한 이유")
        sql(store_path, "UPDATE candidates SET data = json_set(data, '$.reason', ?) WHERE keyword_key = ?", (text.replace("\n", " "), "평범한키워드"))
    elif where == "주제 보관함 후보":
        import json as j
        with contextlib.closing(sqlite3.connect(str(world.path(layout.ENGINE_DB_FILE)))) as connection:
            data = j.loads(connection.execute("SELECT data FROM candidates WHERE candidate_id = 'cid-001'").fetchone()[0])
            data["topic"] = text.replace("\n", " ")
            connection.execute("UPDATE candidates SET data = ? WHERE candidate_id = 'cid-001'", (j.dumps(data, ensure_ascii=False),))
            connection.commit()
    elif where == "채널 프로필":
        patch_json_file(world.path(layout.CHANNEL_PROFILES_FILE), "intro", text)
    elif where == "Seed":
        patch_json_file(world.path(layout.SEEDS_FILE), "keyword", text.replace("\n", " "))
    elif where == "캘린더":
        patch_json_file(world.path(layout.CALENDAR_FILE), "name", text.replace("\n", " "))
    elif where == "설정":
        patch_json_file(world.path("settings.json"), "display_name", text.replace("\n", " "))
    else:
        raise AssertionError(where)


def surfaces(error):
    """오류 하나가 사용자에게 갈 수 있는 모든 글(문구·칸·세부·위치 목록·요약·repr·피클) — 키 글자가 새는지 보는 데 쓴다."""
    parts = [str(error), repr(error), error.log_line(), error.rendered().message, error.rendered().action, error.detail, error.summary, " ".join(f"{key}={value}" for key, value in error.slots.items()), error.reason,
             repr(error.findings), repr([dataclasses.asdict(item) for item in error.findings]), str(error.notes)]
    parts += [repr(pickle.loads(pickle.dumps(item))) for item in error.findings]
    return "\n".join(parts)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = bs.World(self.tmp.name)
        self.ctx = self.world.ctx

    def assert_refused(self, error, token=None):
        self.assertIsNotNone(error, "백업이 거절돼야 한다")
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_BLOCKED", "blocked"))
        if token is not None:
            self.assertFalse(S.leaked(surfaces(error), token), "오류 글에 키 글자가 새었다")

    def assert_no_folder_and_lock(self):
        backups = self.ctx.workspace.backups_dir
        self.assertEqual(list(backups.iterdir()) if backups.is_dir() else [], [], "부분 폴더를 남기지 않는다")
        self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()), [])


class MatrixTest(Base):
    def test_every_kind_in_every_place_stops_the_backup_and_leaves_nothing(self):
        count = 0
        for where in AREAS:
            for kind in KINDS:
                with self.subTest(where=where, kind=kind):
                    with tempfile.TemporaryDirectory() as tmp:
                        world = bs.World.cached(tmp)
                        inject(world, where, kind, bs.three_lines(kind))
                        before = world.data_digests()
                        error = bs.code_of(world.backup)
                        self.assertIsNotNone(error, "백업이 거절돼야 한다")
                        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_BLOCKED", "blocked"))
                        self.assertIn(kind, {item.kind for item in error.findings}, "유형을 알린다")
                        self.assertTrue(all(item.where.startswith(AREAS[where]) for item in error.findings), [item.where for item in error.findings])
                        self.assertFalse(S.leaked(surfaces(error), bs.secret_token(kind)), "오류 글에 키 글자가 새었다")
                        self.assertEqual(world.data_digests(), before, "지금 데이터는 한 바이트도 바뀌지 않는다")
                        backups = world.ctx.workspace.backups_dir
                        self.assertEqual(list(backups.iterdir()) if backups.is_dir() else [], [])
                        self.assertEqual(list(world.ctx.workspace.locks_dir.iterdir()), [])
                        count += 1
        self.assertEqual(count, len(AREAS) * len(KINDS), "54칸을 모두 돌았다")

    def test_the_line_number_of_a_body_finding_is_the_line_inside_the_text(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    world = bs.World(tmp, posts=0, drafts=0)
                    inject(world, "원고 본문", kind, bs.three_lines(kind))
                    error = bs.code_of(world.backup)
                    self.assertTrue(error.findings)
                    self.assertEqual({item.line for item in error.findings}, {3})
                    self.assertIn("3번째 줄", error.summary)

    def test_a_finding_names_the_table_the_column_and_a_short_row_number_but_never_the_text(self):
        inject(self.world, "원고 본문", "github_token", bs.three_lines("github_token"))
        error = bs.code_of(self.world.backup)
        wheres = {item.where for item in error.findings}
        self.assertTrue(any(where.startswith("글 보관함 · 원고 · 본문 · 글 ") for where in wheres), wheres)
        for where in wheres:
            self.assertLessEqual(len(where), bf.MAX_WHERE_CHARS)
        self.assertIn("GitHub 토큰", error.summary)
        self.assertIn("앱은 자동으로 지우거나 바꾸지 않아요", error.summary)

    def test_a_secret_in_the_older_revision_history_is_found_too(self):
        project_id = self.world.ids[0]
        projects.edit_project(self.ctx, project_id, markdown="판 기록에 남을 평범한 본문")
        projects.edit_project(self.ctx, project_id, markdown="이제 깨끗한 본문")
        sql(self.world.path("chanceblog.db"), "UPDATE revisions SET data = json_set(data, '$.source_content', ?) WHERE project_id = ? AND revision = (SELECT MIN(revision) FROM revisions WHERE project_id = ?)",
            (bs.three_lines("aws_access_key"), project_id, project_id))                       # 옛 판 하나에 키 모양 글을 직접 쓴다 — 앱의 쓰기 함수는 쓰기 단계에서 거절한다(PCSEC1 M3)
        error = bs.code_of(self.world.backup)
        self.assertIsNotNone(error, "현재 본문은 깨끗해도 판 기록에 남아 있으면 백업에 들어간다")
        self.assertTrue(any("판 기록" in item.where for item in error.findings), [item.where for item in error.findings])

    def test_after_the_text_is_removed_the_backup_works_again(self):
        inject(self.world, "저장한 초안", "google_api_key", bs.three_lines("google_api_key"))
        self.assert_refused(bs.code_of(self.world.backup))
        with self.ctx.store() as store:
            store.save_draft(self.world.ids[0], "이제 깨끗한 초안")
        self.assertEqual(self.world.backup().row.status, bf.STATUS_COMPLETE)

    def test_two_kinds_in_two_places_are_all_reported_and_the_summary_names_each_place(self):
        inject(self.world, "원고 본문", "google_api_key", bs.three_lines("google_api_key"))
        inject(self.world, "Seed", "pem_private_key", bs.three_lines("pem_private_key"))
        error = bs.code_of(self.world.backup)
        kinds = {item.kind for item in error.findings}
        self.assertEqual(kinds, {"google_api_key", "pem_private_key"})
        self.assertIn("Google API 키", error.summary)
        self.assertIn("개인 키(PEM)", error.summary)
        self.assertTrue(any(item.where.startswith("Seed") for item in error.findings))


class NoRepeatTest(Base):
    def test_no_surface_of_the_error_repeats_a_piece_of_the_key(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    world = bs.World(tmp)
                    inject(world, "원고 본문", kind, bs.three_lines(kind))
                    error = bs.code_of(world.backup)
                    token = bs.secret_token(kind)
                    self.assertFalse(S.leaked(surfaces(error), token))
                    self.assertFalse(S.leaked(error.summary, token))
                    self.assertFalse(S.leaked(json.dumps([item.where for item in error.findings], ensure_ascii=False), token))

    def test_the_backup_function_has_no_way_to_ignore_the_finding(self):
        parameters = inspect.signature(bf.create_full_backup).parameters
        self.assertEqual(list(parameters), ["ctx", "step"])
        self.assertEqual(list(inspect.signature(bf.restore_full_backup).parameters), ["ctx", "source", "confirmed", "step"])
        import ast
        tree = ast.parse(Path(bf.__file__).read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
        names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {node.arg for node in ast.walk(tree) if isinstance(node, ast.keyword) and node.arg}
        names |= {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        for word in ("ignore", "force", "skip_scan", "bypass", "override", "allow_secret", "unsafe", "dangerous"):
            self.assertFalse([name for name in names if word in name.lower()], word)

    def test_a_secret_never_changes_the_live_data_even_after_many_tries(self):
        inject(self.world, "원고 본문", "oauth_token", bs.three_lines("oauth_token"))
        before = self.world.data_digests()
        for _ in range(3):
            self.assert_refused(bs.code_of(self.world.backup))
        self.assertEqual(self.world.data_digests(), before)
        self.assert_no_folder_and_lock()

    def test_the_findings_are_frozen_values_without_any_text(self):
        inject(self.world, "원고 본문", "bearer_token", bs.three_lines("bearer_token"))
        error = bs.code_of(self.world.backup)
        item = error.findings[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            item.line = 9
        self.assertEqual(sorted(dataclasses.asdict(item)), ["col_end", "col_start", "kind", "line", "where"])


class ManyPlacesTest(Base):
    def test_a_long_list_of_places_is_cut_to_fifteen_with_the_rest_counted(self):
        for number in range(40):
            bs.plant_post(self.world, bs.three_lines("github_token"), title=f"키 글 {number}")
        error = bs.code_of(self.world.backup)
        self.assert_refused(error, bs.secret_token("github_token"))
        places = {item.where for item in error.findings}
        self.assertEqual(len(places), bf.MAX_SHOWN_PLACES)
        self.assertGreater(error.more, 20)
        self.assertIn(f"그 밖에 {error.more}곳에서도 찾았어요", error.summary)
        self.assertEqual(error.summary.split("\n")[-1].split(" — ")[0], "해당 줄을 각 칸에서 지운 뒤 다시 백업해 주세요")
        self.assert_no_folder_and_lock()

    def test_scanning_a_few_thousand_rows_stays_fast(self):
        import time
        from chanceblog_desktop.content import store as store_module
        from chanceblog_desktop.content.model import ContentProject
        with tempfile.TemporaryDirectory() as tmp:
            world = bs.World(tmp, posts=1, drafts=0, candidates_count=0)
            body = "보통의 글 문단이에요. 키 모양은 없어요. " * 60
            rows = []
            for number in range(1500):
                project = ContentProject.new(f"느린지 보는 글 {number}", body, now="2026-11-02T01:30:12Z", project_id=f"{number:032x}")
                rows.append((project.project_id, project.title, project.revision, project.created_at, project.updated_at, store_module._dump(project.to_dict())))
            with contextlib.closing(sqlite3.connect(str(world.path("chanceblog.db")))) as connection:
                connection.executemany("INSERT INTO projects (project_id, title, revision, created_at, updated_at, data) VALUES (?, ?, ?, ?, ?, ?)", rows)
                connection.commit()
            started = time.monotonic()
            found = bf.scan_folder(world.root, ["chanceblog.db"])
            seconds = time.monotonic() - started
            self.assertEqual(found, [])
            self.assertLess(seconds, 25, f"{seconds:.1f}초")


class CanaryProofTest(Base):
    """키를 등록한 채 백업해도 백업 폴더에 카나리가 없다 — 여러 인코딩으로 모든 바이트를 찾는다."""

    CANARY = "CANARY_" + "9Zq" + "7Lm2Xp4Rt8Vw" + "1Bn6Cd3Fg5Hj"

    def register_key(self):
        connections.add_entry(self.ctx, "image_provider", name="내 이미지 키", fields={"access_key": self.CANARY}, provider="unsplash", keystore=self.ctx.keystore)

    def test_the_finder_really_finds_every_encoding_of_the_canary(self):
        """양성 대조 — 폴더에 카나리를 인코딩해 심으면 찾는 도구가 모두 찾는다(찾는 도구가 먹통이면 아래 증명이 아무 뜻도 없다)."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, data in bs.encodings(self.CANARY).items():
                (folder / f"planted-{name}.bin").write_bytes("앞 ".encode("utf-8") + data + " 뒤".encode("utf-8"))
            blob = bs.all_bytes(folder)
            for name, data in bs.encodings(self.CANARY).items():
                self.assertIn(data, blob, name)

    def test_the_canary_is_in_the_fake_store_but_in_no_file_of_the_data_folder(self):
        self.register_key()
        in_store = [blob for blob in self.ctx.keystore._blobs.values() if bs.encodings(self.CANARY)["utf-16le"] in blob]
        self.assertEqual(len(in_store), 1, "키는 가짜 보관소(메모리)에만 있다")
        blob = bs.all_bytes(self.world.root)
        for name, data in bs.encodings(self.CANARY).items():
            self.assertNotIn(data, blob, f"데이터 폴더에 {name} 모습의 카나리가 있다")
        self.assertTrue((self.world.root / "connections.json").is_file(), "연결 설정 파일은 있다(키 이름·상태뿐)")

    def test_a_backup_made_with_a_registered_key_holds_the_canary_in_no_encoding(self):
        self.register_key()
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
        folder = self.world.folder(outcome)
        blob = bs.all_bytes(folder)
        self.assertGreater(len(blob), 50_000)
        for name, data in bs.encodings(self.CANARY).items():
            self.assertNotIn(data, blob, f"백업에 {name} 모습의 카나리가 있다")
        self.assertNotIn(b"connections.json", b"".join(path.name.encode() for path in folder.iterdir()))
        self.assertFalse((folder / "connections.json").exists())
        self.assertFalse((folder / "quota_state.json").exists())

    def test_the_listing_the_manifest_and_the_error_texts_never_hold_the_canary(self):
        self.register_key()
        outcome = self.world.backup()
        texts = [json.dumps(self.world.manifest(outcome), ensure_ascii=False), repr(bf.list_full_backups(self.ctx)), repr(outcome)]
        for text in texts:
            for name, data in bs.encodings(self.CANARY).items():
                self.assertNotIn(data.decode("latin-1") if name.startswith("utf-16") else data.decode("utf-8", "replace"), text, name)

    def test_the_manifest_hash_list_matches_what_is_in_the_folder_and_nothing_else_is_there(self):
        self.register_key()
        outcome = self.world.backup()
        folder = self.world.folder(outcome)
        manifest = self.world.manifest(outcome)
        self.assertEqual(sorted(path.name for path in folder.iterdir()), sorted([*manifest["files"], bf.MANIFEST_NAME]))
        for name, info in manifest["files"].items():
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), info["sha256"], name)

    def test_the_safety_copy_made_before_a_restore_holds_no_canary_either(self):
        self.register_key()
        first = self.world.backup()
        result = bf.restore_full_backup(self.ctx, first.row.name, confirmed=True)
        safety = self.ctx.workspace.backups_dir / bf.SAFETY_FOLDER / result.safety
        blob = bs.all_bytes(safety)
        for name, data in bs.encodings(self.CANARY).items():
            self.assertNotIn(data, blob, name)


class LedgerExemptionTest(Base):
    def test_a_key_shape_in_the_published_history_ledger_is_not_scanned_but_the_same_text_elsewhere_is(self):
        """이미 공개된 블로그 글을 읽어 둔 발행 이력 장부는 훑지 않는다(D-75 — 지울 길이 없어 거기서 막히면 백업이 영구히 막힌다). 같은 글이 다른 표에 있으면 막힌다."""
        text = bs.secret_text("google_api_key")
        sql(self.world.path(layout.ENGINE_DB_FILE), "INSERT INTO history_ledger (channel, record_key, title, keywords, date, url, language, topic, ref, origin, first_seen_at, last_seen_at)"
                                                    " VALUES ('naver_a', 'k1', ?, '[]', NULL, NULL, NULL, NULL, 'p1', 'naver_items', '2026-11-06T00:00:00Z', '2026-11-06T00:00:00Z')", (text,))
        self.assertEqual(self.world.backup().row.status, bf.STATUS_COMPLETE)
        sql(self.world.path(layout.ENGINE_DB_FILE), "INSERT INTO review_log (kind, last_run_on) VALUES (?, '2026-11-06')", (text,))
        error = bs.code_of(self.world.backup)
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED")
        self.assertTrue(all("review_log" in item.where for item in error.findings), [item.where for item in error.findings])


class StrictLoaderOrderTest(Base):
    def test_a_json_file_the_strict_reader_rejects_for_its_key_shape_is_blocked_not_silently_left_out(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    world = bs.World(tmp)
                    inject(world, "채널 프로필", kind, bs.three_lines(kind))
                    error = bs.code_of(world.backup)
                    self.assertIsNotNone(error)
                    self.assertEqual(error.code, "FULL_BACKUP_BLOCKED", "부분 백업으로 끝나면 안 된다")

    def test_an_unknown_json_field_whose_name_is_a_key_is_scanned_without_showing_the_name(self):
        key_token, value_token = bs.secret_token("aws_access_key"), bs.secret_token("google_api_key")
        path = self.world.path(layout.SEEDS_FILE)
        data = json.loads(path.read_text(encoding="utf-8"))
        data[key_token] = bs.secret_text("google_api_key")
        write_json(path, data)
        error = bs.code_of(self.world.backup)
        self.assert_refused(error, key_token)
        self.assertFalse(S.leaked(surfaces(error), value_token))
        self.assertEqual({item.kind for item in error.findings}, {"aws_access_key", "google_api_key"})
        self.assertEqual({item.where for item in error.findings}, {"Seed · 칸 이름", "Seed"}, "칸 이름이 키처럼 보이면 그 이름을 칸 이름표로 쓰지 않고 고정 이름으로 알린다")

    def test_a_json_file_that_cannot_be_parsed_is_left_out_and_its_text_is_not_in_the_backup(self):
        token = bs.secret_token("github_token")
        self.world.path(layout.SEEDS_FILE).write_text("{ 깨졌어요 " + token, encoding="utf-8")
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_PARTIAL)
        blob = bs.all_bytes(self.world.folder(outcome))
        self.assertNotIn(token.encode("utf-8"), blob)
        self.assertEqual(self.world.manifest(outcome)["skipped"], {layout.SEEDS_FILE: "TOPIC_FILE_INVALID"})

    def test_a_damaged_settings_file_with_a_key_shape_is_blocked_too(self):
        token = bs.secret_token("aws_access_key")
        path = self.world.path("settings.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["모르는 칸"] = token
        write_json(path, data)
        error = bs.code_of(self.world.backup)
        self.assert_refused(error, token)

    def test_a_damaged_store_is_skipped_and_the_copy_that_was_scanned_is_not_kept(self):
        self.world.path("chanceblog.db").write_bytes(b"not a database " + bs.secret_token("github_token").encode())
        outcome = self.world.backup()
        self.assertEqual(outcome.row.status, bf.STATUS_PARTIAL)
        self.assertFalse((self.world.folder(outcome) / "chanceblog.db").exists())
        self.assertNotIn(bs.secret_token("github_token").encode(), bs.all_bytes(self.world.folder(outcome)))


class RestoreTimeTest(Base):
    def rehash(self, folder):
        manifest = json.loads((folder / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
        for name, info in manifest["files"].items():
            data = (folder / name).read_bytes()
            info["size"], info["sha256"] = len(data), hashlib.sha256(data).hexdigest()
        bs.write_manifest(folder, manifest)

    def test_a_backup_that_holds_a_key_shape_is_not_restored_and_says_it_cannot_be_fixed_by_the_app(self):
        for where, name in (("seeds", layout.SEEDS_FILE), ("calendar", layout.CALENDAR_FILE), ("settings", "settings.json")):
            with self.subTest(where=where):
                with tempfile.TemporaryDirectory() as tmp:
                    world = bs.World(tmp)
                    outcome = world.backup()
                    folder = world.folder(outcome)
                    key = {"seeds": "keyword", "calendar": "name", "settings": "display_name"}[where]
                    patch_json_file(folder / name, key, bs.secret_text("google_api_key"))
                    self.rehash(folder)
                    before = world.data_digests()
                    error = bs.code_of(bf.restore_full_backup, world.ctx, outcome.row.name, confirmed=True)
                    self.assertEqual(error.code, "FULL_BACKUP_BLOCKED")
                    self.assertIn("이 백업 안의 글이라 앱이 고치지 않아요", error.summary)
                    self.assertFalse(S.leaked(surfaces(error), bs.secret_token("google_api_key")))
                    self.assertEqual(world.data_digests(), before)
                    self.assertFalse((world.ctx.workspace.backups_dir / bf.SAFETY_FOLDER).exists(), "아무것도 시작하지 않았다")

    def test_a_backup_whose_store_holds_a_key_shape_is_not_restored(self):
        outcome = self.world.backup()
        folder = self.world.folder(outcome)
        sql(folder / "chanceblog.db", "UPDATE projects SET title = ?", (bs.secret_text("github_token"),))
        self.rehash(folder)
        before = self.world.data_digests()
        error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_BLOCKED", "blocked"))
        self.assertEqual(self.world.data_digests(), before)

    def test_a_key_shape_in_the_current_data_stops_the_restore_before_anything_changes(self):
        outcome = self.world.backup()
        inject(self.world, "원고 본문", "bearer_token", bs.three_lines("bearer_token"))
        before = self.world.data_digests()
        error = bs.code_of(bf.restore_full_backup, self.ctx, outcome.row.name, confirmed=True)
        self.assertEqual(error.code, "FULL_BACKUP_BLOCKED")
        self.assertIn("다시 복원해 주세요", error.summary, "지금 데이터의 글이니 지운 뒤 다시 하라고 말한다")
        self.assertFalse(S.leaked(surfaces(error), bs.secret_token("bearer_token")))
        self.assertEqual(self.world.data_digests(), before)
        self.assertEqual(list((self.ctx.workspace.backups_dir / bf.SAFETY_FOLDER).iterdir()) if (self.ctx.workspace.backups_dir / bf.SAFETY_FOLDER).exists() else [], [])
        self.assertEqual(list(self.ctx.workspace.locks_dir.iterdir()), [])


class RemnantTest(Base):
    """지운 글의 조각 — 앱의 보관함은 지울 때 덮어쓰지만(`secure_delete`) 앱 밖의 도구가 쓴 파일이나 옛 파일은 지운 글이 파일의 빈 쪽에 그대로 남을 수 있다. 키 모양 글을 지운 뒤 다시 백업하라고 안내하므로
    그 조각이 백업에 실려 가면 안 된다 — 백업 사본은 만든 뒤 정리한다(D-398)."""
    FILLER = "앞의 글이에요 " * 3000

    def make_remnant(self, world, kind):
        """앱 밖의 도구가 쓴 것처럼(지울 때 덮어쓰지 않는 연결로) 큰 초안에 키 모양 글을 넣었다가 깨끗한 글로 바꾼다 → 키 글자(조각을 찾을 토큰)."""
        path = world.path("chanceblog.db")
        with contextlib.closing(sqlite3.connect(str(path))) as connection:
            if connection.execute("PRAGMA secure_delete").fetchone()[0]:
                self.skipTest("이 SQLite 는 기본으로 지울 때 덮어쓴다 — 지운 글의 조각이 파일에 남지 않으니 확인할 일이 없다")
            connection.execute("UPDATE drafts SET text = ? WHERE project_id = ?", (self.FILLER + bs.three_lines(kind), world.ids[0]))
            connection.commit()
            connection.execute("UPDATE drafts SET text = ? WHERE project_id = ?", ("지운 뒤의 깨끗한 초안", world.ids[0]))
            connection.commit()
        token = bs.secret_token(kind)
        self.assertIn(token.encode("utf-8"), path.read_bytes(), "먼저 확인: 지금 파일의 빈 쪽에는 지운 키 모양 글이 남아 있다(이 시험의 전제)")
        return token

    def has_piece(self, blob, token):
        pieces = [token] + [token[index:index + 8] for index in range(0, max(len(token) - 8, 1))]
        return any(piece.encode("utf-8") in blob for piece in pieces)

    def test_text_deleted_before_the_backup_is_in_no_byte_of_the_backup_and_the_restore_and_the_safety_copy_drop_it_too(self):
        for kind in KINDS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                world = bs.World.cached(tmp)
                token = self.make_remnant(world, kind)
                outcome = world.backup()
                self.assertEqual(outcome.row.status, "complete", "논리적 내용은 깨끗하니 키 모양 발견이 아니다")
                folder = world.folder(outcome)
                self.assertFalse(self.has_piece(bs.all_bytes(folder), token), "백업의 어떤 바이트에도 지운 키 모양 글의 조각이 없다")
                for encoded in bs.encodings(token).values():
                    self.assertNotIn(encoded, bs.all_bytes(folder))
                self.assertEqual(world.path("chanceblog.db").read_bytes().count(token.encode("utf-8")) > 0, True, "지금 파일은 건드리지 않았다(조각이 그대로 있다)")
                restored = bf.restore_full_backup(world.ctx, outcome.row.name, confirmed=True)
                safety = world.ctx.workspace.backups_dir / bf.SAFETY_FOLDER / restored.safety
                self.assertFalse(self.has_piece(bs.all_bytes(safety), token), "복원 직전 사본에도 조각이 없다")
                self.assertFalse(self.has_piece(world.path("chanceblog.db").read_bytes(), token), "복원하면 지금 파일의 빈 쪽 조각도 사라진다(백업의 쪽으로 통째로 바뀐다)")

    def test_the_cleaned_copy_keeps_the_label_the_version_and_every_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = bs.World.cached(tmp)
            self.make_remnant(world, "github_token")
            before = bs.dump(world.path("chanceblog.db"))
            outcome = world.backup()
            copy = world.folder(outcome) / "chanceblog.db"
            with contextlib.closing(sqlite3.connect(str(world.path("chanceblog.db")))) as live, contextlib.closing(sqlite3.connect(str(copy))) as saved:
                for pragma in ("application_id", "user_version"):
                    self.assertEqual(saved.execute(f"PRAGMA {pragma}").fetchone(), live.execute(f"PRAGMA {pragma}").fetchone(), pragma)
            self.assertEqual(bs.dump(copy), before, "정리해도 행의 내용은 한 글자도 다르지 않다")


if __name__ == "__main__":
    unittest.main()
