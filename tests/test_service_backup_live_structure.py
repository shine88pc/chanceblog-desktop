"""복원을 시작할 때 '지금 보관함' 도 구조를 본다 — 복원 직전 사본으로 되돌릴 수 없는 보관함이면 바꾸기 전에 멈춘다(`service/backup_flow.py` 의 `_refuse_if_undo_impossible`, L8b, 결정 D-570).
L8 독립 검증 Q 의 QP-1 · S 의 SP-5.

문제: 복원 직전 안전 사본은 지금 파일을 그대로 담는다. 사용자가 앱 밖의 도구로 지금 보관함에 뷰·색인·트리거 같은 앱이 만들지 않는 개체를 두었다면 그 사본에도 있고, 복원은 그런 백업을 거절하므로(D-554)
확인창이 약속한 '잘못 복원했다면 그 사본으로 다시 복원하면 돼요' 가 거짓이 된다(복원은 경고 없이 끝나고 되돌리기만 거절됐다).

지키는 것:
  1) 지금 보관함(글 보관함·주제 엔진 보관함)에 앱이 만들지 않는 개체가 하나라도 있으면 복원은 **시작하지 않는다** — `RESTORE_FAILED`(이유 `live_structure`), 지금 데이터·안전 사본 폴더·복원 중 표지·잠금·임시 파일이 모두 그대로이고
     아무것도 쓰지 않는다(안전 사본을 만들기 전에 읽기만 해서 본다 — 지금 보관함을 여는 연결이 읽기 전용 주소이고 그 주소가 쓰기를 거절한다, `ReadOnlyTest`). 개체 종류 여덟(트리거·파괴 트리거·뷰·모르는 표·유일 색인·일부 색인·숨은 열·가상 표) × 보관함 둘을 모두 본다.
  2) 그 개체를 지우면 복원이 되고, 그 복원의 안전 사본으로 되돌리기도 된다 — 확인창의 약속이 시작한 복원마다 지켜진다. 검사 없이 시작했다면 되돌리기가 거절됐음도(문제의 재현) 보인다.
  3) 이 복원이 바꾸지 않을 것은 보지 않는다 — 백업에 없는 보관함, 깨져서 옆으로 옮길 지금 파일, 읽을 수 없는 지금 파일. 앱이 스스로 만드는 정상 모양(옛 판 보관함·`ANALYZE` 통계 표)은 걸리지 않는다.
  4) 거절 문구와 오류 세부에는 고정된 낱말뿐이고 지금 보관함의 개체 이름·SQL 글이 없다(카나리아).
네트워크·실제 시계·실제 자격 증명 관리자 없이 돈다. 가짜 개체 이름은 `CANARY_` 로 시작한다.
"""
import contextlib
import inspect
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import store_v1  # noqa: E402
import test_service_backup_restore as tr  # noqa: E402
import test_service_backup_structure as tsb  # noqa: E402

from chanceblog_desktop.content import schema_guard  # noqa: E402
from chanceblog_desktop.content.model import ContentProject  # noqa: E402
from chanceblog_desktop.content.store import _read_only_uri  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.topicdb.store import open_for_write  # noqa: E402

DBS = tsb.DBS
STORE, ENGINE = DBS
CANARY = tsb.CANARY


def fts5_available():
    """이 SQLite 에 전문 검색(fts5)이 들어 있는가 — 없으면 가상 표 개체는 훑지 않는다(순수 검사 시험이 같은 까닭으로 건너뛴다)."""
    try:
        with contextlib.closing(sqlite3.connect(":memory:")) as database:
            database.execute("CREATE VIRTUAL TABLE probe USING fts5(x)")
        return True
    except sqlite3.Error:
        return False


def tampering(name):
    """지금 보관함 `name` 에 사용자가 앱 밖에서 더했다고 보는 개체들 — {종류 이름: [SQL, …]}. 모두 열 이름·행 내용은 그대로라 앱이 평소처럼 열린다."""
    found = {label: statements for label, statements in tsb.tampering(name).items() if label != "view posing as a table"}
    found["hidden column"] = [f"ALTER TABLE {tsb.TARGET[name][0]} ADD COLUMN {CANARY}_g TEXT AS (1)"]                # `table_info` 가 보여 주지 않는 생성 열 — 독립 검증 Q 의 QL-3
    if fts5_available():
        found["virtual table"] = [f"CREATE VIRTUAL TABLE {CANARY}_fts USING fts5(body)"]                            # 가상 표와 그 그림자 표들
    return found


class Base(tr.Base):
    def setUp(self):
        super().setUp()
        self.outcome = self.world.backup()                                        # 앱이 만든 깨끗한 백업
        tr.change_everything(self.world)                                          # 백업 뒤에 데이터를 바꿔 둔다 — 복원하면 되돌려질 것이 있다
        self.clean = {name: self.world.path(name).read_bytes() for name in DBS}

    def tamper_live(self, name, *statements):
        with contextlib.closing(sqlite3.connect(str(self.world.path(name)))) as database:
            for statement in statements:
                database.execute(statement)
            database.commit()

    def reset_live(self):
        for name, data in self.clean.items():
            self.world.path(name).write_bytes(data)

    def attempt(self):
        return bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)

    def assert_stopped_before_anything(self, error, before):
        self.assertIsNotNone(error, "복원은 시작하지 않아야 한다")
        self.assertEqual((error.code, error.reason), ("RESTORE_FAILED", bf.LIVE_STRUCTURE), error.detail)
        self.assert_untouched(before)                                              # 지금 데이터 그대로·잠금·임시 파일·안전 사본 폴더 없음
        self.assertFalse(bf._marker_path(self.ctx).exists(), "복원 중 표지도 만들지 않았다 — 바꾸기 시작하기 전에 멈췄다")
        self.assertEqual(error.notes, (), "바꾼 것이 없으니 되돌리지 못한 것도 없다")
        self.assertNotIn(CANARY, str(error) + error.log_line() + error.detail, "지금 보관함의 개체 이름은 되풀이하지 않는다")


class StartCheckTest(Base):
    def test_every_kind_of_foreign_object_in_either_live_database_stops_the_restore_before_anything_changes(self):
        for name in DBS:
            for label, statements in tampering(name).items():
                with self.subTest(database=name, kind=label):
                    try:
                        self.tamper_live(name, *statements)
                        before = tr.state_of(self.world)
                        raw = self.world.path(name).read_bytes()
                        error = self.attempt()
                        self.assert_stopped_before_anything(error, before)
                        self.assertEqual(self.world.path(name).read_bytes(), raw, "지금 보관함 파일은 한 바이트도 바뀌지 않았다")
                        self.assertIn(name, error.detail)
                    finally:
                        self.reset_live()

    def test_a_view_posing_as_a_table_in_the_live_store_is_stopped_too(self):
        self.tamper_live(STORE, *tsb.tampering(STORE)["view posing as a table"])
        before = tr.state_of(self.world)
        self.assert_stopped_before_anything(self.attempt(), before)

    def test_the_refusal_names_only_fixed_words_for_what_it_found(self):
        self.tamper_live(STORE, *tampering(STORE)["trigger"], *tampering(STORE)["view"])
        error = self.attempt()
        self.assertEqual(error.detail, "지금 보관함에 앱이 만들지 않는 구조가 있다 — chanceblog.db: " + schema_guard.describe(("trigger", "view")))
        self.assertIn("트리거·뷰", error.detail)

    def test_both_live_databases_are_looked_at_and_both_are_named(self):
        self.tamper_live(STORE, *tampering(STORE)["view"])
        self.tamper_live(ENGINE, *tampering(ENGINE)["unique index"])
        error = self.attempt()
        self.assertIn(f"chanceblog.db: {schema_guard.KIND_TEXT['view']}", error.detail)
        self.assertIn(f"{ENGINE}: {schema_guard.KIND_TEXT['index']}", error.detail)

    def test_a_foreign_object_in_only_the_engine_database_stops_it_while_the_content_store_is_clean(self):
        self.tamper_live(ENGINE, *tampering(ENGINE)["view"])
        before = tr.state_of(self.world)
        error = self.attempt()
        self.assert_stopped_before_anything(error, before)
        self.assertNotIn("chanceblog.db", error.detail)

    def test_the_message_says_it_did_not_start_and_why_in_fixed_words(self):
        self.tamper_live(STORE, *tampering(STORE)["view"])
        error = self.attempt()
        for word in ("시작하지 않았어요", "복원 직전 사본", "앱이 만들지 않는 구조"):
            self.assertIn(word, str(error))
        self.assertEqual(bf.LIVE_STRUCTURE, "live_structure")
        self.assertEqual(error.slots["이유"], bf.LIVE_STRUCTURE_TEXT)

    def test_it_stops_before_any_write_the_safety_copy_the_marker_or_the_database_swap(self):
        self.tamper_live(STORE, *tampering(STORE)["view"])
        with contextlib.ExitStack() as stack:
            for name in ("_build", "_write_marker", "_restore_database", "_write_durably", "_swap_in", "_move_aside"):
                stack.enter_context(mock.patch.object(bf, name, side_effect=AssertionError(f"{name} 이 불렸다")))
            error = self.attempt()
        self.assertEqual((error.code, error.reason), ("RESTORE_FAILED", bf.LIVE_STRUCTURE))

    def test_the_check_only_reads_the_live_files(self):
        """앱이 만드는 보관함(삭제 저널 방식)에서는 파일 바이트와 짝 파일이 전후 같다. 외부 도구가 쓰기 먼저 기록(WAL) 방식으로 바꾼 보관함은 SQLite 가 읽기 연결에서도 짝 파일을 만들 수 있다(독립 검증 S 의 SP-3 — 앱은 그렇게 만들지 않는다)."""
        self.tamper_live(STORE, *tampering(STORE)["view"])
        raw = {name: self.world.path(name).read_bytes() for name in DBS}
        live = {component.name: "ok" for component in bf.COMPONENTS}
        with self.assertRaises(bf.FlowError):
            bf._refuse_if_undo_impossible(self.ctx, bf.COMPONENTS, live)
        self.assertEqual({name: self.world.path(name).read_bytes() for name in DBS}, raw)
        siblings = sorted(path.name for path in self.world.path(STORE).parent.iterdir() if path.name.startswith("chanceblog.db"))
        self.assertEqual(siblings, ["chanceblog.db"], "짝 파일(-journal·-wal)도 남기지 않는다(앱이 만드는 삭제 저널 방식의 보관함에서)")

    def test_the_json_and_settings_files_are_never_opened_as_databases(self):
        looked = []
        real = bf._foreign_in

        def spy(component, path, **kwargs):
            looked.append(component.name)
            return real(component, path, **kwargs)
        live = {component.name: "ok" for component in bf.COMPONENTS}
        with mock.patch.object(bf, "_foreign_in", spy):
            bf._refuse_if_undo_impossible(self.ctx, bf.COMPONENTS, live)
        self.assertEqual(sorted(looked), sorted(DBS))


class ReadOnlyTest(Base):
    """독립 검증 Q 의 QL-1 — 시작 검사가 지금 보관함을 '읽기 전용으로만' 연다는 약속(코드 설명·D-570·보안 문서)을 시험이 센다. 옛 시험은 파일 바이트와 짝 파일만 봐서, SELECT 만 하는 읽기·쓰기 연결(변이 M15)은
    그 둘을 바꾸지 않으므로 통과했다 — 이제 연 연결의 주소와 그 주소가 정말 쓰기를 거절하는지를 센다."""

    def addresses(self, *, with_view):
        """시작 검사를 한 번 돌리며 `sqlite3.connect` 를 감싸 파일 연결의 (첫 인자, 키워드)를 적는다 — 메모리 연결(정본 개체 목록 만들기)은 거른다."""
        if with_view:
            self.tamper_live(STORE, *tampering(STORE)["view"])
        real, seen = sqlite3.connect, []

        def spy(target, *args, **kwargs):
            seen.append((str(target), kwargs))
            return real(target, *args, **kwargs)
        live = {component.name: "ok" for component in bf.COMPONENTS}
        with mock.patch.object(bf.sqlite3, "connect", spy):
            try:
                bf._refuse_if_undo_impossible(self.ctx, bf.COMPONENTS, live)
            except bf.FlowError:
                self.assertTrue(with_view, "뷰가 없는데 시작 검사가 멈췄다")
        return [(target, kwargs) for target, kwargs in seen if target != ":memory:"]

    def test_every_connection_the_check_opens_on_a_live_file_is_the_projects_read_only_address(self):
        for with_view in (False, True):
            with self.subTest(refused=with_view):
                opened = self.addresses(with_view=with_view)
                self.assertEqual(sorted(target for target, _kwargs in opened), sorted(_read_only_uri(self.world.path(name)) for name in DBS), "두 보관함을 한 번씩, 프로젝트의 읽기 전용 주소로만 연다")
                for target, kwargs in opened:
                    self.assertIn("mode=ro", target)
                    self.assertIs(kwargs.get("uri"), True)
                self.reset_live()

    def test_those_addresses_really_refuse_a_write_when_opened_again(self):
        opened = self.addresses(with_view=False)
        self.assertEqual(len(opened), len(DBS), "시험의 전제 — 보관함마다 연결이 하나 열렸다")
        for target, _kwargs in opened:
            with self.subTest(address=target[-30:]):
                with contextlib.closing(sqlite3.connect(target, uri=True)) as database:
                    with self.assertRaises(sqlite3.OperationalError):
                        database.execute("CREATE TABLE writes_must_fail (x)")


class PromiseTest(Base):
    """확인창의 약속 — '잘못 복원했다면 그 사본으로 다시 복원하면 돼요' 가 시작한 복원마다 지켜진다."""

    def test_without_the_start_check_the_undo_was_refused_which_is_the_problem_the_check_prevents(self):
        """문제의 재현(검증자의 탐침) — 시작 검사를 없애면 복원은 경고 없이 끝나고 복원 직전 사본으로 되돌리기만 구조 검사에 걸려 거절된다."""
        self.tamper_live(STORE, *tampering(STORE)["view"])
        with mock.patch.object(bf, "_refuse_if_undo_impossible"):
            done = bf.restore_full_backup(self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual(done.status, bf.STATUS_COMPLETE)
        again = bs.code_of(bf.restore_full_backup, self.ctx, done.safety, confirmed=True)
        self.assertEqual((again.code, again.reason), ("FULL_BACKUP_INVALID", "structure"), "복원 직전 사본으로 되돌리기가 거절됐다 — 확인창의 약속이 거짓이 되던 경우")

    def test_a_failure_in_the_middle_could_not_be_rolled_back_either_which_is_the_second_reason_the_restore_must_not_start(self):
        """L8 보고서 '남은 위험' 의 셋째 — 복원이 도중에 실패해 안전 사본으로 되돌릴 때도 같은 구조 검사를 받아, 지금 파일에 그런 개체가 있었다면 자동으로 되돌리지 못하고 '원래 내용은 안전 사본에 있어요' 라고만 알렸다.
        시작 검사 없이 마지막 확인을 실패시켜 그 모습을 보이고, 검사가 있으면 시작하지 않아 되돌릴 일이 없음을 본다."""
        self.tamper_live(STORE, *tampering(STORE)["view"])

        def fail_after_check(ctx, component, manifest):
            raise AppError("STORE_CORRUPT", {"파일": component.name}, detail="일부러 낸 실패")
        with mock.patch.object(bf, "_refuse_if_undo_impossible"), mock.patch.object(bf, "_after_check", fail_after_check):
            midway = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual((midway.code, midway.reason), ("RESTORE_FAILED", "corrupt"))
        self.assertTrue(midway.notes, "검사 없이 시작했다면 글 보관함을 원래대로 돌리지 못했다고 알려야 했다")
        self.assertTrue(any("원래대로 돌리지 못했어요" in note for note in midway.notes), midway.notes)
        self.reset_live()
        self.tamper_live(STORE, *tampering(STORE)["view"])
        before = tr.state_of(self.world)
        with mock.patch.object(bf, "_after_check", fail_after_check):
            stopped = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual((stopped.code, stopped.reason), ("RESTORE_FAILED", bf.LIVE_STRUCTURE), "검사가 있으면 시작하지 않으므로 도중에 실패할 일도, 되돌리지 못한 것도 없다")
        self.assertEqual(stopped.notes, ())
        self.assertEqual(tr.state_of(self.world), before)

    def test_after_the_foreign_object_is_removed_the_restore_goes_through_and_its_safety_copy_restores_back(self):
        self.tamper_live(STORE, *tampering(STORE)["view"])
        self.assertIsNotNone(self.attempt())
        self.reset_live()                                                          # 사용자가 그 개체를 지웠다
        before = tr.state_of(self.world)
        done = self.restore(self.outcome.row.name)
        self.assertEqual(done.status, bf.STATUS_COMPLETE)
        self.assertNotEqual(tr.state_of(self.world), before, "복원이 지금 데이터를 바꿨다")
        self.restore(done.safety)
        self.assertEqual(tr.state_of(self.world), before, "복원 직전 사본으로 되돌리면 복원하기 전 모습이다")

    def test_the_safety_copy_of_every_restore_that_starts_passes_the_same_check_a_restore_of_it_would_get(self):
        done = self.restore(self.outcome.row.name)
        safety = self.safety_root() / done.safety
        manifest = bf._verify_backup(safety)                                        # 되돌릴 때와 같은 확인(구조·키 모양·내용)을 통과한다 — 거절하면 FlowError
        self.assertTrue({STORE, ENGINE} <= set(manifest["files"]))

    def test_the_refusal_leaves_a_clean_restore_possible_right_afterwards_with_nothing_left_behind(self):
        self.tamper_live(STORE, *tampering(STORE)["trigger"])
        self.assertIsNotNone(self.attempt())
        self.reset_live()
        done = self.restore(self.outcome.row.name)
        self.assertEqual(done.status, bf.STATUS_COMPLETE)
        safety = [entry.name for entry in self.safety_root().iterdir()]
        self.assertEqual(len(safety), 1, "멈춘 시도는 안전 사본을 남기지 않았고 시작한 복원 하나만 남겼다")


class NotLookedAtTest(Base):
    """이 복원이 바꾸지 않을 것·안전 사본에 담지 않을 것은 보지 않는다."""

    def test_a_database_the_backup_does_not_contain_is_not_looked_at(self):
        """백업에 주제 엔진 보관함이 없으면 이 복원은 그 보관함을 바꾸지도 안전 사본에 담지도 않는다 — 거기 뷰가 있어도 복원은 된다."""
        with tempfile.TemporaryDirectory() as tmp:
            world = bs.World(tmp, engine=False)
            outcome = world.backup()
            self.assertNotIn(ENGINE, bf._verify_folder(world.folder(outcome))["files"], "시험의 전제 — 이 백업에는 주제 엔진 보관함이 없다")
            with open_for_write(world.paths.database):
                pass
            with contextlib.closing(sqlite3.connect(str(world.paths.database))) as database:
                database.execute("CREATE VIEW user_made_view AS SELECT 1")
                database.commit()
            result = bf.restore_full_backup(world.ctx, outcome.row.name, confirmed=True)
            self.assertEqual(result.status, bf.STATUS_COMPLETE)
            with contextlib.closing(sqlite3.connect(str(world.paths.database))) as database:
                self.assertTrue(database.execute("SELECT 1 FROM sqlite_master WHERE name = 'user_made_view'").fetchone(), "바뀌지 않은 보관함의 개체는 그대로 있다")

    def test_a_live_database_that_is_damaged_is_moved_aside_as_before_even_with_a_foreign_object(self):
        """깨진(점검이 문제를 찾는) 지금 파일은 안전 사본에 담지 않고 지우지도 않고 옆으로 옮긴다 — 그 파일의 구조는 되돌리기 약속과 상관없다."""
        live = self.world.path(STORE)
        with contextlib.closing(sqlite3.connect(str(live))) as database:
            database.execute("UPDATE projects SET title = '목록 열만 바뀐 제목'")
            database.execute(tampering(STORE)["view"][0])
            database.commit()
        damaged = live.read_bytes()
        self.assertEqual(bf._live_state(self.ctx, bf.BY_NAME[STORE]), "damaged", "시험의 전제 — 점검이 문제를 찾는다")
        self.assertEqual(bf._foreign_in(bf.BY_NAME[STORE], live, defer_newer=True), ("view",), "시험의 전제 — 구조 검사는 그 뷰를 본다")
        self.ctx.clock.advance(seconds=30)
        result = self.restore(self.outcome.row.name)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        aside = sorted(live.parent.glob("chanceblog.db.bad-*"))
        self.assertEqual(len(aside), 1)
        self.assertEqual(aside[0].read_bytes(), damaged, "깨진 지금 파일은 그대로 옆에 남았다")

    def test_a_live_database_that_cannot_be_read_by_the_check_does_not_stop_the_restore_here(self):
        """읽을 수 없으면 건너뛴다 — 안전 사본을 만드는 다음 단계가 같은 파일을 읽다가 멈추거나(잠금이면 '다른 곳에서 쓰는 중') 통과한다."""
        self.tamper_live(STORE, *tampering(STORE)["view"])
        real = bf._foreign_in
        live_paths = {str(self.world.path(name)) for name in DBS}

        def unreadable(component, path, **kwargs):
            if kwargs.get("defer_newer") and str(path) in live_paths:                     # 시작 검사의 읽기만 실패한다(바꾼 뒤 확인은 `defer_newer` 없이 같은 파일을 읽는다)
                raise AppError("STORE_CORRUPT", {"파일": component.name}, detail="읽을 수 없다")
            return real(component, path, **kwargs)
        with mock.patch.object(bf, "_foreign_in", unreadable):
            done = bf.restore_full_backup(self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual(done.status, bf.STATUS_COMPLETE, "읽을 수 없는 검사는 복원을 막지 않는다(막는 것은 읽어서 찾은 개체뿐이다)")

    def test_a_missing_or_blank_live_database_does_not_break_the_check(self):
        for state in ("missing", "blank"):
            for name in DBS:
                with self.subTest(database=name, state=state):
                    try:
                        if state == "missing":
                            self.world.path(name).unlink()
                        else:
                            self.world.path(name).write_bytes(b"")
                        self.assertEqual(self.restore(self.outcome.row.name).status, bf.STATUS_COMPLETE)
                    finally:
                        self.reset_live()

    def test_a_newer_version_live_store_is_reported_as_newer_not_as_a_foreign_object(self):
        self.tamper_live(STORE, "CREATE TABLE brand_new_table (x TEXT)", "PRAGMA user_version = 99")
        error = self.attempt()
        self.assertEqual((error.code, error.reason), ("STORE_VERSION_UNSUPPORTED", "newer"), error.detail)

    def test_the_check_itself_leaves_a_newer_version_file_to_the_version_check(self):
        """지금 파일 상태 확인(`_live_state`)이 이미 '더 새로운 프로그램' 으로 멈추지만, 이 검사를 따로 불러도 새 판이 더한 표를 '앱이 만들지 않는 구조' 라고 잘못 말하지 않는다(들어오는 백업의 확인과 같은 규칙)."""
        self.tamper_live(STORE, "CREATE TABLE brand_new_table (x TEXT)", "PRAGMA user_version = 99")
        live = {component.name: "ok" for component in bf.COMPONENTS}
        self.assertIsNone(bf._refuse_if_undo_impossible(self.ctx, bf.COMPONENTS, live))


class NormalShapesAreNotFlaggedTest(Base):
    """앱이 스스로 만드는 모양은 걸리지 않는다 — 걸리면 정상 사용자의 복원이 막힌다."""

    def test_a_live_database_with_the_planner_statistics_table_still_restores_and_can_be_undone(self):
        with contextlib.closing(sqlite3.connect(str(self.world.path(STORE)))) as database:
            database.execute("ANALYZE")
            database.commit()
            self.assertTrue(database.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_stat1'").fetchone(), "시험의 전제 — 통계 표가 정말 생겼다")
        done = self.restore(self.outcome.row.name)
        self.assertEqual(done.status, bf.STATUS_COMPLETE)
        again = self.restore(done.safety)
        self.assertEqual(again.status, bf.STATUS_COMPLETE, "통계 표가 든 안전 사본도 되돌려진다")

    def test_a_first_version_live_store_is_not_flagged(self):
        """아직 올리지 않은 옛 판(판 1) 글 보관함이 지금 파일이어도 정본의 부분집합이라 걸리지 않는다."""
        old = Path(self.tmp.name) / "v1.db"
        store_v1.make_v1_file(old, [ContentProject.new("옛 판의 글", "옛 판의 본문", project_id="legacy-1")])
        self.world.path(STORE).write_bytes(old.read_bytes())
        self.assertEqual(bf._foreign_in(bf.BY_NAME[STORE], self.world.path(STORE), defer_newer=True), ())
        done = self.restore(self.outcome.row.name)
        self.assertEqual(done.status, bf.STATUS_COMPLETE)

    def test_the_untouched_app_files_pass_the_start_check_in_the_normal_flow(self):
        before = tr.state_of(self.world)
        done = self.restore(self.outcome.row.name)
        self.assertEqual(done.status, bf.STATUS_COMPLETE)
        self.assertNotEqual(tr.state_of(self.world), before)


class RulesTest(unittest.TestCase):
    def test_no_new_error_code_and_no_switch_to_skip_the_check(self):
        self.assertEqual(list(inspect.signature(bf._refuse_if_undo_impossible).parameters), ["ctx", "names", "live"])
        self.assertEqual(list(inspect.signature(bf.restore_full_backup).parameters), ["ctx", "source", "confirmed", "step"], "복원 함수에 검사를 건너뛰는 인자가 없다")
        error = bf.FlowError("RESTORE_FAILED", {"이유": bf.LIVE_STRUCTURE_TEXT}, detail="x", reason=bf.LIVE_STRUCTURE)
        self.assertEqual(error.code, "RESTORE_FAILED", "새 오류 코드를 만들지 않고 있던 코드를 쓴다")

    def test_the_fixed_text_has_no_hostile_names_and_is_in_easy_words(self):
        for word in ("앱이 만들지 않는 구조", "트리거", "뷰", "복원 직전 사본", "시작하지 않았어요"):
            self.assertIn(word, bf.LIVE_STRUCTURE_TEXT)
        for forbidden in ("SELECT", "CREATE", "sqlite", "Traceback", chr(126), "http"):
            self.assertNotIn(forbidden, bf.LIVE_STRUCTURE_TEXT)


if __name__ == "__main__":
    unittest.main()
