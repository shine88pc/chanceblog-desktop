"""본문 속 Secret 형태가 있으면 저장·백업을 멈추는 공통 거절의 적용 시험(PCSEC1 M3 — 운영자 결정 2026-11-11 4항).

스캐너(`security/scan.py`)는 다른 묶음이 만들었고 시험도 따로 있다. 여기서는 **적용 위치**를 본다 — 여섯 유형(Google API 키·GitHub 토큰·Bearer 토큰·OAuth 토큰·AWS 액세스 키·개인 키)이
  1) 옛 명령줄 쓰기 길(원고 제목·본문·출처·이미지, 가져온 HTML, 후보 주제·키워드·이유, 네이버 프로필 글칸, 후보 CSV 한 줄)에서 **쓰기 전에** 멈추고(아무것도 안 쓴다) 위치(칸·줄)와 유형만 알린다.
  2) 글 보관함 백업(`backup`)이 만들기 전에 글·옛 판·초안·후보를 훑어 멈춘다(지우기·되돌리기 직전의 안전 사본은 막지 않는다).
  3) 주제 엔진 백업이 같은 종류를 막고 위치(파일·줄 / 표·행)와 유형을 말한다. 읽기·화면 저장(블로그 프로필·씨앗)은 같은 함수(`scan_key_shape`)라 같은 종류를 막는다.
  4) 초안 화면의 복사 관문이 같은 종류를 막고 글자를 한 자도 되풀이하지 않는다.
  5) '무시하고 저장' 길이 어디에도 없다(함수 인자·명령줄 옵션·환경 변수·설정 — 소스에서 못박는다). 정상 글은 통과하고 10만 자도 빠르다.
가짜 비밀은 전부 실행할 때 조각을 이어 만든다(`scan_samples`). 출력에 비밀이 샌 흔적은 `secret_support.assert_no_secret`(실패 메시지에도 값이 없다)으로 본다. 네트워크 없이 돈다.
"""
import ast
import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scan_samples as S  # noqa: E402
import secret_support as sec  # noqa: E402
import service_support as ss  # noqa: E402
import test_service_seed_manage as tsm  # noqa: E402
import topics_support as ts  # noqa: E402
from test_service_blog_profiles import form as profile_form  # noqa: E402
from test_topicdb_backup import World, put_json  # noqa: E402

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content.model import Asset  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import refuse, scan  # noqa: E402
from chanceblog_desktop.security.mask import has_key_shape  # noqa: E402
from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.service import candidates as cs  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service import naver_flow, projects, review  # noqa: E402
from chanceblog_desktop.service import seed_manage as sm  # noqa: E402
from chanceblog_desktop.topicdb import backup as bk  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore  # noqa: E402
from chanceblog_desktop.topics import layout, seeds  # noqa: E402
from chanceblog_desktop.ui.core import draft_rules  # noqa: E402

SRC = ss.ROOT / "src" / "chanceblog_desktop"
KIND_LINES = {kind: S.sample(kind) for kind in S.KINDS}                     # 유형 → (비밀 글, 그 글을 담은 한 줄)
SCANNER_ONLY = {"github_pat": S.github_pat(), "refresh": "token " + S.refresh(), "access_token=": S.named("access_token"), "refresh_token:": S.named("refresh_token", sep=": ")}
FINDER_WORDS = re.compile(r"(?i)ignore|bypass|override|skip|force|unsafe|secret|scan|insecure|no-?check|anyway")
BAD_PARAMETER = re.compile(r"(?i)ignore|bypass|override|skip|force|unsafe|anyway|allow|confirm|yes|save_|disable|off$|enable")
NORMAL = (
    "오늘은 겨울철 보일러 사용법을 정리합니다. 난방비를 줄이는 방법 다섯 가지를 소개해요.",
    "Bearer authentication is a scheme where the client sends an opaque token in a header.",
    "access token 과 refresh token 의 차이를 설명합니다. access_token 은 짧게 쓰는 이름입니다.",
    "깃 해시 3f2a9c1d8b7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a 는 비밀이 아닙니다.",
    "주소 https://example.com/posts/2026/11/11/how-to-save-electricity-at-home?utm_source=blog 를 참고하세요.",
    "번호 3f2504e0-4f89-41d3-9a0c-0305e82c3301 모양은 UUID 입니다.",
    "AKIA 는 아마존 키 앞부분의 이름일 뿐이라는 설명 글",
    "ghp 로 시작한다는 설명은 흔하지만 실제 값은 쓰지 않습니다",
    "PRIVATE KEY 라는 말이 들어간 보안 설명 글(BEGIN 도 END 도 줄에 없다)",
    "ya29 는 구글 토큰 이야기이고 eyJ 로 시작하는 JWT 설명도 있다",
    "Authorization 헤더에 Bearer 를 붙인다 — 값은 여기에 적지 않는다",
    "1//0 이라는 접두어 설명, 그리고 GOCSPX 라는 낱말만",
)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(tmp.name, repo="")
        self.root = Path(self.ctx.workspace.root)

    def run_cli(self, *argv):
        return ss.run_cli(self.ctx, *argv)

    def tree(self):
        return ss.tree_snapshot(self.root) if self.root.exists() else {}

    def refused(self, call, *args, **kwargs):
        """호출이 SECRET_SHAPE_FOUND 로 멈춘다 → 그 오류."""
        with self.assertRaises(AppError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, "SECRET_SHAPE_FOUND")
        return caught.exception

    def assert_clean_error(self, error, token):
        """오류의 어디에도(문구·세부·기록 한 줄·참고 줄·발견 목록 글) 비밀이 없다."""
        everything = " | ".join([str(error), error.detail or "", error.log_line(), *getattr(error, "notes", ()), repr(error.findings), repr(error.slots), error.rendered().message])
        sec.assert_no_secret(self, token, everything, "오류")


# ======================================================================================================================================================
# 1) 옛 명령줄 쓰기 길
# ======================================================================================================================================================
class OldCommandLinePathsTest(Base):
    def test_a_new_manuscript_with_any_of_the_six_kinds_is_refused_with_its_place_and_type_and_nothing_is_written(self):
        for kind, (token, line) in KIND_LINES.items():
            with self.subTest(kind=kind):
                code, out, err = self.run_cli("new", "--title", "정상 제목", "--text", "첫 줄은 정상입니다\n" + line + "\n마지막 줄도 정상")
                self.assertEqual((code, out), (1, ""))
                self.assertIn("SECRET_SHAPE_FOUND", err)
                self.assertIn("본문 2번째 줄", err)
                self.assertIn(scan.KIND_LABELS[kind], err)
                self.assertIn("지운 뒤 다시 저장해 주세요", err)
                sec.assert_no_secret(self, token, out + err, "명령줄 출력")
                self.assertEqual(self.tree(), {}, "아무것도 쓰지 않았다(데이터 폴더도 만들지 않았다)")
                self.assertFalse(self.root.exists())

    def test_the_json_output_has_the_code_the_place_and_the_type_and_never_the_token(self):
        token, line = KIND_LINES["github_token"]
        code, out, err = self.run_cli("--json", "new", "--title", "정상 제목", "--text", line)
        self.assertEqual((code, err), (1, ""))
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "SECRET_SHAPE_FOUND")
        self.assertIn("본문 1번째 줄", payload["error"]["message"])
        self.assertIn("GitHub 토큰", payload["error"]["message"])
        sec.assert_no_secret(self, token, out, "JSON 출력")

    def test_the_title_the_references_the_image_names_and_the_imported_html_are_checked_too(self):
        token = S.github()
        for label, call in (("제목", lambda: projects.new_project(self.ctx, "제목 " + token, "본문")),
                            ("출처", lambda: projects.new_project(self.ctx, "제목", "본문", references=("https://example.com/p?access_token=" + S.body(30, S.B64URL, 8),))),
                            ("이미지", lambda: projects.new_project(self.ctx, "제목", "본문", assets=(Asset("a.png", alt="그림 " + token),))),
                            ("본문", lambda: projects.import_html(self.ctx, "제목", "<p>정상 문단</p><p>" + token + "</p>"))):
            with self.subTest(field=label):
                error = self.refused(call)
                self.assertIn(label, error.slots["위치"])
                self.assert_clean_error(error, token)
                self.assertEqual(self.tree(), {})

    def test_an_edit_checks_only_what_it_changes_and_refuses_before_saving(self):
        token = S.google()
        view = projects.new_project(self.ctx, "정상 제목", "정상 본문입니다")
        before = self.tree()
        error = self.refused(projects.edit_project, self.ctx, view.project_id, markdown="바뀐 본문\n" + token)
        self.assertEqual(error.slots["위치"], "본문 2번째 줄")
        self.assert_clean_error(error, token)
        self.assertEqual(self.tree(), before, "저장 전에 멈췄다")
        with self.ctx.store() as store:
            saved = store.load(view.project_id)
        self.assertEqual((saved.revision, saved.source_content), (1, "정상 본문입니다"))
        self.refused(projects.edit_project, self.ctx, view.project_id, title="새 제목 " + token)
        self.refused(projects.edit_project, self.ctx, view.project_id, assets=[Asset("b.png", alt=token)])
        changed = projects.edit_project(self.ctx, view.project_id, title="깨끗한 새 제목")                       # 비밀이 없는 고침은 그대로 된다
        self.assertTrue(changed.changed)

    def test_editing_one_field_does_not_rescan_an_old_secret_in_a_field_it_does_not_touch(self):
        """옛 버전이 저장한 글에 이미 있는 비밀 모양은 '바꾸지 않는 칸' 이면 이 검사가 막지 않는다 — 막는 곳은 백업 전 검사다(알려 둔 한계)."""
        token = S.github()
        view = projects.new_project(self.ctx, "정상 제목", "정상 본문")
        with self.ctx.store() as store:
            project = store.load(view.project_id)
            project.source_content = "옛 본문 " + token
            project.revision += 1
            store.save(project)
        done = projects.edit_project(self.ctx, view.project_id, title="제목만 고침")
        self.assertTrue(done.changed)
        error = self.refused(projects.backup_store, self.ctx)
        self.assertIn("본문", error.slots["위치"])

    def test_a_candidate_with_a_secret_in_any_text_field_is_refused_and_names_the_field(self):
        token = S.github()
        blogs = ("naver_a",)
        cases = {"추천 포스팅 주제": dict(topic="주제 " + token, keyword="키워드"), "핵심 키워드": dict(topic="주제", keyword="키워드 " + token),
                 "보조 키워드": dict(topic="주제", keyword="키워드", sub_keywords=("가", token)), "추천 이유": dict(topic="주제", keyword="키워드", reason="이유 " + token)}
        for label, fields in cases.items():
            with self.subTest(field=label):
                error = self.refused(cs.add_candidate, self.ctx, blogs=blogs, **fields)
                self.assertIn(label, error.slots["위치"])
                self.assertEqual(error.slots["유형"], "GitHub 토큰")
                self.assert_clean_error(error, token)
                self.assertEqual(self.tree(), {})

    def test_the_candidate_command_refuses_before_the_value_check(self):
        token, line = KIND_LINES["aws_access_key"]
        code, out, err = self.run_cli("candidates", "add", "--topic", "주제 " + line, "--keyword", "키워드", "--blog", "naver_a")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("SECRET_SHAPE_FOUND", err)
        self.assertIn("AWS 액세스 키", err)
        sec.assert_no_secret(self, token, err, "명령줄 출력")
        self.assertEqual(self.tree(), {})

    def test_a_naver_profile_with_a_secret_in_any_text_field_is_refused_and_names_the_field(self):
        token = S.github()
        for name, label in naver_flow.PROFILE_TEXT_LABELS.items():
            value = [["분류", token]] if name == "categories" else [token] if name in ("default_tags", "forbidden_phrases", "excluded_topics") else "값 " + token
            with self.subTest(field=name):
                error = self.refused(naver_flow.set_profile, self.ctx.settings, "naver_a", {name: value})
                self.assertIn(label, error.slots["위치"])
                self.assert_clean_error(error, token)
                self.assertEqual(self.tree(), {}, "프로필 파일을 만들지 않았다")

    def test_the_profile_command_refuses_and_a_clean_profile_is_still_saved(self):
        token = S.github()
        code, out, err = self.run_cli("naver-profile", "set", "naver_a", "--name", "표시명", "--url", "https://blog.naver.com/abc", "--tone", "말투 " + token)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("SECRET_SHAPE_FOUND", err)
        sec.assert_no_secret(self, token, err, "명령줄 출력")
        self.assertEqual(self.tree(), {})
        code, out, err = self.run_cli("naver-profile", "set", "naver_a", "--name", "표시명", "--url", "https://blog.naver.com/abc", "--tone", "친절한 말투")
        self.assertEqual((code, err), (0, ""))

    def test_a_csv_line_with_a_secret_is_rejected_by_itself_and_the_other_lines_are_saved(self):
        token = S.github()
        path = self.tmp / "후보.csv"
        path.write_text("주제,핵심 키워드,대상 블로그\n겨울 보일러,보일러 청소,naver_a\n주제 " + token + ",위험 키워드,naver_a\n여름 선풍기,선풍기 청소,naver_a\n", encoding="utf-8")
        result = cs.import_csv(self.ctx, path)
        self.assertEqual((len(result.added), len(result.rejected)), (2, 1))
        note = result.rejected[0]
        self.assertEqual(note.line, 3)
        self.assertIn("추천 포스팅 주제", note.reason)
        self.assertIn("GitHub 토큰", note.reason)
        sec.assert_no_secret(self, token, json.dumps(result.to_dict(), ensure_ascii=False), "가져오기 결과")
        with self.ctx.store() as store:
            stored = " ".join(item.topic for item in store.list_candidates())
        sec.assert_no_secret(self, token, stored, "보관함의 후보 주제")
        code, out, err = self.run_cli("candidates", "import-csv", str(path))
        sec.assert_no_secret(self, token, out + err, "명령줄 출력")


# ======================================================================================================================================================
# 2) 글 보관함 백업 전 검사
# ======================================================================================================================================================
class StoreBackupTest(Base):
    def put_project(self, body="정상 본문", title="정상 제목"):
        view = projects.new_project(self.ctx, title, body)
        return view.project_id

    def backups(self):
        folder = self.ctx.workspace.backups_dir
        return sorted(item.name for item in folder.iterdir()) if folder.exists() else []

    def test_a_clean_store_is_backed_up(self):
        self.put_project()
        saved = projects.backup_store(self.ctx)
        self.assertTrue(Path(saved).is_file())
        self.assertEqual(len(self.backups()), 1)

    def test_a_secret_anywhere_in_the_store_stops_the_backup_before_it_is_made_and_names_the_place(self):
        token = S.github()

        def current_body(ctx, pid, store):
            project = store.load(pid)
            project.source_content = "본문 " + token
            project.revision += 1
            store.save(project)

        def old_revision(ctx, pid, store):
            project = store.load(pid)
            project.source_content = "옛 본문 " + token
            project.revision += 1
            store.save(project)
            project = store.load(pid)
            project.source_content = "새 정상 본문"
            project.revision += 1
            store.save(project)

        def draft(ctx, pid, store):
            store.save_draft(pid, "임시 저장한 글 " + token)

        def candidate(ctx, pid, store):
            store.add_candidates(lambda existing: [cd.Candidate.new("주제 " + token, "키워드", ("naver_a",), now="2026-11-11T00:00:00Z")])

        def rendered(ctx, pid, store):
            project = store.load(pid)
            project.set_rendered("github_pages", "렌더링 " + token)
            store.save(project)

        for label, place, inject in (("현재 본문", "본문", current_body), ("옛 판 기록", "판 본문", old_revision), ("자동 저장 초안", "초안", draft), ("후보", "주제", candidate),
                                     ("플랫폼별 렌더링", "렌더링", rendered)):
            with self.subTest(where=label):
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as other:
                    self.ctx = ss.make_ctx(other, repo="")
                    pid = self.put_project()
                    with self.ctx.store() as store:
                        inject(self.ctx, pid, store)
                    error = self.refused(projects.backup_store, self.ctx)
                    self.assertIn(place, error.slots["위치"], error.slots)
                    self.assertEqual(error.slots["유형"], "GitHub 토큰")
                    self.assert_clean_error(error, token)
                    self.assertEqual(self.backups(), [], "백업 파일(임시 파일 포함)을 만들지 않았다")

    def test_all_six_kinds_stop_the_store_backup(self):
        for kind, (token, line) in KIND_LINES.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as other:
                self.ctx = ss.make_ctx(other, repo="")
                pid = self.put_project()
                with self.ctx.store() as store:
                    project = store.load(pid)
                    project.source_content = "정상 줄\n" + line
                    project.revision += 1
                    store.save(project)
                error = self.refused(projects.backup_store, self.ctx)
                self.assertEqual(error.slots["유형"], scan.KIND_LABELS[kind])
                self.assertIn("본문 2번째 줄", error.slots["위치"])
                self.assert_clean_error(error, token)
                self.assertEqual(self.backups(), [])

    def test_the_command_line_backup_stops_with_the_place_and_type_and_makes_no_file(self):
        token = S.github()
        pid = self.put_project()
        with self.ctx.store() as store:
            project = store.load(pid)
            project.source_content = "본문 " + token
            project.revision += 1
            store.save(project)
        code, out, err = self.run_cli("backup")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("SECRET_SHAPE_FOUND", err)
        self.assertIn("글 " + pid[:8] + " 본문", err)
        self.assertIn("다시 백업해 주세요", err)
        sec.assert_no_secret(self, token, err, "명령줄 출력")
        self.assertEqual(self.backups(), [])
        code, out, err = self.run_cli("--json", "backup")
        self.assertEqual(json.loads(out)["error"]["code"], "SECRET_SHAPE_FOUND")
        sec.assert_no_secret(self, token, out, "JSON 출력")

    def test_the_safety_copies_before_a_delete_or_a_restore_are_not_blocked_so_the_problem_can_be_fixed(self):
        token = S.github()
        pid = self.put_project()
        with self.ctx.store() as store:
            project = store.load(pid)
            project.source_content = "본문 " + token
            project.revision += 1
            store.save(project)
        self.refused(projects.backup_store, self.ctx)
        done, note = projects.delete_project(self.ctx, pid, confirmed=True)                        # 문제의 글을 지울 수 있어야 문제가 풀린다
        self.assertEqual(done, pid)
        self.assertTrue((self.ctx.workspace.backups_dir / "before-delete").is_dir())
        self.assertEqual(projects.list_projects(self.ctx), [])
        projects.backup_store(self.ctx)                                                               # 글이 없어지면 백업도 된다

    def test_a_store_that_cannot_be_read_in_part_does_not_make_the_check_crash(self):
        import contextlib
        import sqlite3
        self.put_project()
        pid = self.put_project("둘째 본문", "둘째 제목")
        with contextlib.closing(sqlite3.connect(str(self.ctx.workspace.store_path))) as connection:
            with connection:
                connection.execute("UPDATE projects SET data = '{}' WHERE project_id = ?", (pid,))
        with self.ctx.store() as store:
            self.assertEqual(refuse.store_findings(store), ())                                          # 읽을 수 없는 글은 건너뛴다(백업 자체의 점검이 따로 막는다)


# ======================================================================================================================================================
# 3) 주제 엔진 백업과 같은 종류의 읽기·화면 저장
# ======================================================================================================================================================
class TopicBackupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def blocked(self, world):
        with self.assertRaises(AppError) as caught:
            world.backup()
        self.assertEqual(caught.exception.code, "TOPIC_BACKUP_BLOCKED")
        self.assertFalse(world.backups.exists() and any(world.backups.iterdir()), "백업(임시 폴더 포함)을 만들지 않았다")
        return caught.exception

    def test_a_secret_in_a_json_file_blocks_the_backup_and_the_reason_names_the_file_the_line_and_the_type(self):
        for kind in S.KINDS:
            token = KIND_LINES[kind][0]
            payload = "Bearer " + token if kind == "bearer_token" else token                 # Bearer 는 낱말 + 값이 한 모양이다
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as other:
                world = World(other)
                put_json(world.data / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed(keyword="예시 " + payload)]))
                error = self.blocked(world)
                reason = error.slots["이유"]
                self.assertIn(layout.SEEDS_FILE, reason)
                self.assertRegex(reason, r"\d+번째 줄")
                self.assertIn(scan.KIND_LABELS[kind], reason)
                sec.assert_no_secret(self, token, reason + (error.detail or "") + error.log_line(), "오류")

    def test_a_secret_in_the_database_blocks_the_backup_and_the_reason_names_the_table_the_row_and_the_type(self):
        for kind in S.KINDS:
            token = KIND_LINES[kind][0]
            payload = "Bearer " + token if kind == "bearer_token" else token
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as other:
                world = World(other)
                with TopicStore.open(world.data / layout.ENGINE_DB_FILE) as store:
                    store.add_candidates(lambda existing: [ts.rated(70, candidate_id="cid-099", channel="naver_a", topic=f"예시 {payload} 모음", created_at="2026-11-06T00:00:00Z")], now="2026-11-06T00:00:00Z")
                error = self.blocked(world)
                reason = error.slots["이유"]
                self.assertIn("주제 엔진 보관함의 후보", reason)
                self.assertRegex(reason, r"\d+번째 행")
                self.assertIn(scan.KIND_LABELS[kind], reason)
                sec.assert_no_secret(self, token, reason + (error.detail or "") + error.log_line(), "오류")

    def test_a_shape_only_the_old_pattern_knows_is_still_blocked_with_the_plain_sentence(self):
        legacy = "예시 Bearer " + S.bearer_value(19)
        self.assertTrue(has_key_shape(legacy) and not scan.has_secret(legacy), "표본이 옛 패턴만 아는 모양이다")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as other:
            world = World(other)
            put_json(world.data / layout.SEEDS_FILE, seeds.seeds_to_dict([ts.example_seed(keyword=legacy)]))
            reason = self.blocked(world).slots["이유"]
            self.assertIn("키·토큰처럼 보이는 글이 있어 백업하지 않았습니다", reason)
            self.assertNotIn("번째 줄", reason)

    def test_the_common_check_knows_all_six_kinds_and_five_that_only_the_scanner_knows(self):
        for kind, (token, line) in KIND_LINES.items():
            self.assertTrue(bk.scan_key_shape("예시 " + line), kind)
        for name, text in SCANNER_ONLY.items():
            with self.subTest(shape=name):
                self.assertFalse(has_key_shape(text), "이 표본은 옛 패턴이 모르는 모양이다")
                self.assertTrue(bk.scan_key_shape(text))
                self.assertTrue(bk.scan_key_shape("정상 글 " * 40000 + text + " 끝"), "겹친 창으로 끝까지 훑는다")

    def test_normal_text_is_no_more_blocked_than_before(self):
        for text in NORMAL:
            self.assertEqual(bk.scan_key_shape(text), has_key_shape(text), text[:20])
        self.assertFalse(bk.scan_key_shape("예시 문장입니다. " * 60_000))


class ScreenSavePathsTest(tsm.Base):
    """화면 쓰기 길(블로그 프로필·씨앗)도 같은 종류를 막는다 — 읽기·백업과 같은 함수를 쓰므로 옛 패턴이 모르는 모양도 걸린다."""

    def edit(self, seed_id, fields):
        return sm.edit_seed(self.ctx, seed_id, fields, expected_version=self.snap().version)

    def test_a_blog_profile_with_a_shape_only_the_scanner_knows_is_refused_before_anything_is_written(self):
        before = self.tree()
        snap = bp.read_snapshot(self.ctx)
        for name, text in SCANNER_ONLY.items():
            with self.subTest(shape=name):
                with self.assertRaises(bp.ProfileProblems) as caught:
                    bp.save_slot(self.ctx, "naver_a", profile_form(intro="소개 " + text), expected_version=snap.version)
                self.assertEqual(caught.exception.problems, {"intro": "key_shape"})
                sec.assert_no_secret(self, text.split()[-1], repr(caught.exception.problems) + str(caught.exception) + caught.exception.detail + caught.exception.log_line(), "오류")
        self.assertEqual(self.tree(), before)

    def test_a_seed_edit_with_a_shape_only_the_scanner_knows_is_refused_and_names_the_field(self):
        self.put(tsm.three())
        before = self.tree()
        for name, text in SCANNER_ONLY.items():
            with self.subTest(shape=name), self.assertRaises(sm.SeedProblems) as caught:
                self.edit("ex-1", {"reason": "이유 " + text})
            self.assertEqual(caught.exception.problems, {"reason": "key_shape"})
            sec.assert_no_secret(self, text.split()[-1], repr(caught.exception.problems) + str(caught.exception) + caught.exception.detail + caught.exception.log_line(), "오류")
        self.assertEqual(self.tree(), before)


# ======================================================================================================================================================
# 4) 초안 화면의 복사 관문
# ======================================================================================================================================================
class DraftCopyGateTest(unittest.TestCase):
    def test_the_gate_blocks_all_six_kinds_and_the_scanner_only_shapes(self):
        for kind, (token, line) in KIND_LINES.items():
            with self.subTest(kind=kind):
                self.assertTrue(draft_rules.has_secret("정상 줄\n" + line + "\n끝"))
        for name, text in SCANNER_ONLY.items():
            with self.subTest(shape=name):
                self.assertTrue(draft_rules.has_secret("정상 줄\n" + text + "\n끝"))

    def test_the_places_name_where_and_show_no_character_of_what_the_scanner_found(self):
        for name, text in {**{kind: line for kind, (_token, line) in KIND_LINES.items()}, **SCANNER_ONLY}.items():
            token = scan.scan_secrets(text)
            self.assertTrue(token, name)
            found = text[token[0].col_start - 1:token[0].col_end]
            with self.subTest(shape=name):
                places = draft_rules.secret_places(("본문", "정상 줄\n" + text + "\n끝"))
                self.assertTrue(places and places[0].startswith("본문"))
                sec.assert_no_secret(self, found, " ".join(places), "복사 관문 미리보기")

    def test_spots_use_the_original_offsets_so_the_garbage_check_masks_them(self):
        token = S.github()
        text = "앞 글\r\n둘째 줄 " + token + " 끝\n셋째"
        spots = draft_rules.secret_spots(text)
        self.assertTrue(any(text[start:end] == token for start, end in spots), spots)

    def test_normal_text_passes_the_gate(self):
        for text in NORMAL:
            self.assertEqual(draft_rules._scanner_spans(text), (), text[:20])                    # 검사기를 부르는 부분이 정상 글에 아무 자리도 더하지 않는다
            self.assertFalse(scan.has_secret(text), text[:20])


# ======================================================================================================================================================
# 5) 길이 · 성능 · 우회 길이 없음
# ======================================================================================================================================================
class NormalTextAndSpeedTest(Base):
    def test_normal_texts_pass_every_application_point(self):
        for text in NORMAL:
            with self.subTest(text=text[:24]):
                refuse.refuse_secret_shapes({"본문": text, "제목": text[:20]})
                projects.check_no_secret_shape("정상 제목", text)
                self.assertIsNone(refuse.secret_reason({"추천 포스팅 주제": text}))
        view = projects.new_project(self.ctx, "정상 제목", "\n\n".join(NORMAL))
        self.assertTrue(view.project_id)
        self.assertTrue(Path(projects.backup_store(self.ctx)).is_file())                              # 정상 글이 든 보관함은 백업된다

    def test_a_hundred_thousand_characters_are_checked_quickly(self):
        paragraph = "겨울철 난방비를 줄이는 방법을 정리했어요. Boiler maintenance tips: check the pressure, bleed the radiators. 3f2a9c1d8b7e6f5a 해시 같은 글도 있어요.\n"
        text = (paragraph * (100_000 // len(paragraph) + 1))[:100_000]
        started = time.perf_counter()
        projects.check_no_secret_shape("정상 제목", text, ("https://example.com/a",), ())
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.5, f"10만 자 검사에 {elapsed:.2f}초(검사기 자체는 0.5초 안 — 부하가 큰 PC 의 여유를 둔다)")
        hostile = ("a1" * 50_000)
        started = time.perf_counter()
        refuse.refuse_secret_shapes({"본문": hostile})
        self.assertLess(time.perf_counter() - started, 1.5)


class NoBypassTest(unittest.TestCase):
    """'무시하고 저장' 선택지가 코드 어디에도 없다 — 건너뛰는 인자·명령줄 옵션·환경 변수·설정."""

    APPLICATION = {"security/refuse.py": ("secret_shape_error", "refuse_secret_shapes", "secret_reason", "refuse_store_secret_shapes", "store_findings", "locate"),
                   "service/projects.py": ("check_no_secret_shape", "backup_store", "new_project", "edit_project", "import_html"),
                   "service/naver_flow.py": ("set_profile",), "topicdb/backup.py": ("_shaped", "scan_key_shape", "_scan_json", "_scan_database")}

    def functions(self, relative):
        tree = ast.parse((SRC / relative).read_text(encoding="utf-8"))
        return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

    def test_no_function_that_applies_the_check_has_a_parameter_that_could_skip_it(self):
        for relative, names in self.APPLICATION.items():
            found = self.functions(relative)
            for name in names:
                node = found[name]
                parameters = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)] + [item.arg for item in (node.args.vararg, node.args.kwarg) if item]
                for parameter in parameters:
                    if parameter in ("ctx", "settings", "store"):
                        continue
                    self.assertIsNone(BAD_PARAMETER.search(parameter), f"{relative}::{name}({parameter}) — 검사를 건너뛸 수 있는 인자처럼 보인다")
        for name in ("scan_secrets", "scan_fields", "has_secret", "describe", "summarize"):
            node = self.functions("security/scan.py")[name]
            for arg in (*node.args.args, *node.args.kwonlyargs):
                self.assertIsNone(BAD_PARAMETER.search(arg.arg) if arg.arg != "action" else None, f"scan.{name}({arg.arg})")

    def test_the_command_line_has_no_option_or_command_that_skips_the_check(self):
        options, commands = set(), set()
        stack = [cli.build_parser()]
        while stack:
            current = stack.pop()
            for action in current._actions:
                options.update(action.option_strings)
                choices = getattr(action, "choices", None)
                if isinstance(choices, dict):
                    for name, child in choices.items():
                        commands.add(name)
                        stack.append(child)
        for word in options | commands:
            self.assertIsNone(FINDER_WORDS.search(word), f"검사를 건너뛰는 길처럼 보이는 명령·옵션: {word}")

    def test_the_check_reads_no_environment_variable_no_settings_file_and_no_clock(self):
        for relative in ("security/refuse.py", "security/scan.py"):
            text = (SRC / relative).read_text(encoding="utf-8")
            code = "\n".join(ast.unparse(node) for node in ast.parse(text).body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)))
            for word in ("environ", "getenv", "Settings", "settings", "open(", "time.", "random", "argparse", "sys.argv"):
                self.assertNotIn(word, code, f"{relative}: {word}")

    def test_every_application_point_calls_the_check_before_it_writes(self):
        """호출 위치를 소스에서 못박는다 — 쓰기 함수가 검사 호출보다 앞서 있지 않다."""
        expectations = {"service/projects.py": {"new_project": ("check_no_secret_shape", "ContentProject.new"), "edit_project": ("check_no_secret_shape", "store.save"),
                                                "backup_store": ("refuse_store_secret_shapes", "store.backup")},
                        "service/candidates.py": {"add_candidate": ("refuse_secret_shapes", "store.add_candidates")},
                        "service/naver_flow.py": {"set_profile": ("refuse_secret_shapes", "settings.save_naver_profile")}}
        for relative, table in expectations.items():
            found = self.functions(relative)
            for name, (check, write) in table.items():
                calls = [(node.lineno, ast.unparse(node.func)) for node in ast.walk(found[name]) if isinstance(node, ast.Call)]
                first_check = min(line for line, text in calls if text.endswith(check))
                first_write = min(line for line, text in calls if text.endswith(write))
                self.assertLess(first_check, first_write, f"{relative}::{name} — 검사({check})가 쓰기({write})보다 앞서야 한다")

    def test_the_scanner_is_called_only_through_the_application_modules(self):
        """모양을 알아보는 규칙은 `security/scan.py` 한 곳 — 적용 위치는 그 함수를 부르기만 하고 자기 정규식을 만들지 않는다."""
        for relative in ("security/refuse.py",):
            text = (SRC / relative).read_text(encoding="utf-8")
            self.assertNotIn("re.compile(r\"(?i)bearer", text)
            self.assertEqual(len(re.findall(r"re\.compile", text)), 1, "표 이름 모양 하나뿐이다(비밀 모양 규칙이 아니다)")
        for relative in ("service/projects.py", "service/candidates.py", "service/naver_flow.py"):
            text = (SRC / relative).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"AIza|ghp_|AKIA|BEGIN[ A-Z]*PRIVATE KEY", relative)


class ReviewParamsTest(Base):
    """PCSEC1V D3 — 검토 요청의 매개변수와 네이버 발행 주소도 **쓰기 전에** 비밀 형태를 거절한다(위치는 칸 이름, 유형 이름뿐 — 글·일부·길이 없음, 보관함 변화 0).
    GitHub Pages `review` 의 `--category`·`--image-url`·`--tags`·`--description`·`--source-name`·`--source-url`·`--source-title`, 네이버 검토 선택 항목(제목·본문 파일·태그·분야), `naver-done --url`."""
    PAGES = {"--category": "경제·일", "--lang": "ko", "--image-url": "https://images.example.invalid/a.jpg", "--tags": "에너지,생활"}

    def setUp(self):
        super().setUp()
        self.ctx = ss.make_ctx(self.tmp)                                         # 가짜 저장소 폴더가 있는 보통 Context(검토는 공개 주소를 계산한다)
        self.root = Path(self.ctx.workspace.root)
        self.pid = projects.new_project(self.ctx, "에너지 절약 습관", ss.ko_text()).project_id
        self.token = KIND_LINES["github_token"][0]
        self.label = scan.KIND_LABELS["github_token"]

    def review_pages(self, **extra):
        argv = ["review", self.pid, "--platform", "pages"]
        for key, value in {**self.PAGES, **extra}.items():
            argv += [key, value]
        return self.run_cli(*argv)

    def test_every_github_pages_review_parameter_with_a_key_shape_is_refused_before_anything_is_written(self):
        token = self.token
        cases = {"한 줄 설명": {"--description": "설명 " + token}, "태그": {"--tags": "에너지," + token}, "분야": {"--category": "경제 " + token},
                 "대표 이미지 주소": {"--image-url": "https://images.example.invalid/a.jpg?k=" + token},
                 "출처 이름": {"--source-name": "이름 " + token, "--source-url": "https://example.com/a"},
                 "출처 주소": {"--source-name": "출처", "--source-url": "https://example.com/a?k=" + token},
                 "출처 글 제목": {"--source-name": "출처", "--source-url": "https://example.com/a", "--source-title": "제목 " + token}}
        for where, extra in cases.items():
            with self.subTest(field=where):
                before = self.tree()
                code, out, err = self.review_pages(**extra)
                self.assertEqual((code, out), (1, ""), err)
                self.assertIn("SECRET_SHAPE_FOUND", err)
                self.assertIn(where, err)
                self.assertIn(self.label, err)
                sec.assert_no_secret(self, token, out + err, "명령줄 출력")
                self.assertEqual(self.tree(), before, "아무것도 쓰지 않았다(보관함도 바뀌지 않았다)")

    def test_the_json_error_has_the_code_and_the_place_and_never_the_token_and_normal_values_still_pass(self):
        argv = ["--json", "review", self.pid, "--platform", "pages", *[item for pair in self.PAGES.items() for item in pair], "--description", "설명 " + self.token]
        code, out, err = self.run_cli(*argv)
        self.assertEqual((code, err), (1, ""))
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], "SECRET_SHAPE_FOUND")
        self.assertIn("한 줄 설명", payload["error"]["message"])
        sec.assert_no_secret(self, self.token, out, "JSON 출력")
        code, out, err = self.review_pages(**{"--description": "정상 설명입니다", "--source-name": "출처", "--source-url": "https://example.com/a", "--source-title": "정상 제목"})
        self.assertEqual((code, err), (0, ""), out)

    def test_the_naver_review_options_are_checked_too(self):
        ss.naver_profiles(self.ctx)
        token, options = self.token, naver_flow.NaverOptions
        cases = {"제목": options(title="제목 " + token), "본문 파일": options(body="본문 " + token), "태그": options(tags=("정상", token)), "분야": options(category="분류 " + token)}
        for where, given in cases.items():
            with self.subTest(field=where):
                before = self.tree()
                error = self.refused(review.request_review, self.ctx, self.pid, "naver_a", naver_options=given)
                self.assertIn(where, error.slots["위치"])
                self.assert_clean_error(error, token)
                self.assertEqual(self.tree(), before)

    def test_the_published_address_of_naver_done_is_checked_too(self):
        before = self.tree()
        code, out, err = self.run_cli("naver-done", self.pid, "--blog", "naver_a", "--url", "https://blog.naver.com/examplea/223000000001?k=" + self.token)
        self.assertEqual((code, out), (1, ""), err)
        self.assertIn("SECRET_SHAPE_FOUND", err)
        self.assertIn("발행 주소", err)
        sec.assert_no_secret(self, self.token, out + err, "명령줄 출력")
        self.assertEqual(self.tree(), before)


if __name__ == "__main__":
    unittest.main()
