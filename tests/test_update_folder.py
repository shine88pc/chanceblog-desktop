"""폴더에서 업데이트(UPDATE 설계서 3-11, 질문 Q4 추천 '포함', v1update U-3) 시험 — `check_from_folder`·`stage_update_from_folder`·`UpdateSession.check_folder`/`prepare_from_folder`.

지키는 것:
  1) **접속이 없다**: 접속 스위치(`NET_UPDATE_CHECK`)는 꺼진 채이고 `update` 어댑터는 꽂히지 않았는데도(등록부 비어 있음) 고른 폴더의 서명된 릴리스를 확인·복사·적용 흐름까지 간다. `UPDATE_APPLY` 가 꺼져 있으면 네 진입점
     모두 `UPDATE_DISABLED` 로 아무것도 읽거나 쓰기 전에 끝난다(상태 파일도 임시 폴더도 생기지 않는다).
  2) **온라인과 똑같은 규칙**: 서명·칸 규칙·만료·시계·낮은 판·`seq`·최소 버전·설치 종류·크기·SHA-256 — 후보 채널 `rc` 는 폴더에서만 읽힌다(온라인 확인은 거절).
  3) **고른 폴더는 읽기만**: 이름·내용이 하나도 바뀌지 않고, 링크·폴더·보통 파일이 아닌 것은 따라가지 않고 거절하며, 오류의 이유 이름표에 폴더 경로·파일 이름이 없다.
  4) 파일이 없거나 크기·해시가 다르면 임시 폴더를 남기지 않는다. 디스크가 모자라면 복사 전에 `DISK_FULL`.
  5) 전체 흐름(`check_folder` → `prepare_from_folder` → `apply`)이 온라인과 같은 순서(백업 → `pending` → 어댑터 → `last_seq`)로 간다. 폴더에서 확인한 결과를 `download()` 로 인터넷에서 받으려 하면 거절한다.
네트워크·실제 시크릿 없이 돈다(가짜 어댑터·임시 폴더, `Tripwire` 로 바깥 호출 0 확인).
"""
import ast
import contextlib
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import outgoing_support as og  # noqa: E402
import update_flow_support as fs  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import external, update_flow  # noqa: E402
from chanceblog_desktop.update import health, keys, machine, source, state  # noqa: E402
from chanceblog_desktop.update import manifest as manifest_module  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"


def code_of(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code
    return None


def lay_out(release, target, *, skip=(), replace=None):
    """릴리스의 매니페스트·서명·자산을 한 폴더에 놓는다 — `skip` 은 빼고, `replace` 는 {이름: 다른 본문}."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    files = {"update-manifest.json": release.manifest_bytes, "update-manifest.json.sig": release.signature}
    files.update(release.bodies)
    for name, body in files.items():
        if name not in skip:
            (target / name).write_bytes((replace or {}).get(name, body))
    return target


def snapshot(folder):
    """폴더 안 모든 항목의 (이름, 크기, 해시) — 읽기만 했는지 견주는 지문."""
    found = []
    for path in sorted(Path(folder).rglob("*")):
        found.append((path.relative_to(folder).as_posix(), path.stat().st_size if path.is_file() else -1, hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""))
    return found


class FolderCase(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        self.ctx = fs.make_world(self.tmp)
        self.update = update_flow.update_folder(self.ctx)
        self.release = fs.Release("1.0.1")
        self.chosen = lay_out(self.release, self.tmp / "picked")
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(fs.switches_on("UPDATE_APPLY"))                 # 접속 스위치는 일부러 켜지 않는다
        self.wire = stack.enter_context(og.Tripwire())

    def tearDown(self):
        self.assertEqual(self.wire.calls, [], "진짜 바깥 호출이 일어났다")
        self.assertFalse(capabilities.NET_UPDATE_CHECK)
        self.assertEqual(external.registered_kinds(), (), "폴더에서 업데이트는 접속 어댑터를 꽂지 않는다")

    def check(self, **overrides):
        options = dict(current_version="1.0.0", install_kind="inno", keyring=fs.RING)
        options.update(overrides)
        return update_flow.check_from_folder(self.ctx, self.chosen, **options)

    def staging_runs(self):
        root = health.staging_root(self.update)
        return sorted(path.name for path in root.iterdir()) if root.is_dir() else []


class CheckTest(FolderCase):
    def test_a_signed_release_in_a_folder_is_found_without_any_connection(self):
        result = self.check()
        self.assertEqual((result.status, result.apply_possible, result.source, result.manifest.version, result.current_version), ("AVAILABLE", True, "folder", "1.0.1", "1.0.0"))
        self.assertEqual((result.manifest_bytes, result.signature_bytes), (self.release.manifest_bytes, self.release.signature))
        after = state.read_state(self.update)
        self.assertEqual((after.last_seq, after.last_seen_utc), (0, "2026-12-02T00:00:00Z"))
        self.assertEqual(after.last_check, state.State().last_check, "온라인 확인의 기록(`last_check`)은 건드리지 않는다")
        self.assertIsNone(after.pending)
        self.assertEqual(self.staging_runs(), [], "확인은 아무것도 복사해 두지 않는다")

    def test_a_check_never_raises_last_seq_and_the_same_version_is_up_to_date(self):
        state.write_state(self.update, state.State(last_seq=self.release.dict["seq"]))
        result = self.check(current_version="1.0.1")
        self.assertEqual((result.status, result.apply_possible), ("UP_TO_DATE", False))
        self.assertEqual(state.read_state(self.update).last_seq, self.release.dict["seq"])

    def test_the_release_candidate_channel_is_read_from_a_folder_but_never_online(self):
        candidate = fs.Release("1.0.1-rc.1", channel="rc")
        picked = lay_out(candidate, self.tmp / "rc")
        result = update_flow.check_from_folder(self.ctx, picked, current_version="1.0.0", install_kind="inno", keyring=fs.RING)
        self.assertEqual((result.status, result.manifest.channel, result.manifest.version), ("AVAILABLE", "rc", "1.0.1-rc.1"))
        with self.assertRaises(manifest_module.ManifestError) as caught:
            manifest_module.verify_manifest(candidate.manifest_bytes, candidate.signature, keyring=fs.RING, now=fs.NOW, current_version="1.0.0", install_kind="inno")
        self.assertEqual((caught.exception.code, caught.exception.reason), ("UPDATE_MANIFEST_INVALID", "channel"))

    def test_the_rules_are_the_online_rules(self):
        cases = (("낮은 판", dict(current_version="2.0.0"), "UPDATE_DOWNGRADE_BLOCKED"), ("최소 버전", dict(current_version="0.9.0"), "UPDATE_NEEDS_MANUAL_INSTALL"),
                 ("설치 종류", dict(install_kind="velopack"), "UPDATE_NEEDS_MANUAL_INSTALL"), ("출하 키(비어 있음)", dict(keyring=keys.shipped_keyring()), "UPDATE_SIGNATURE_INVALID"),
                 ("현재 버전이 글이 아님", dict(current_version="not-a-version"), "UPDATE_CHECK_FAILED"))
        for label, overrides, code in cases:
            with self.subTest(label=label):
                self.assertEqual(code_of(self.check, **overrides), code)
        state.write_state(self.update, state.State(last_seq=self.release.dict["seq"]))
        self.assertEqual(code_of(self.check), "UPDATE_DOWNGRADE_BLOCKED", "저장된 시퀀스 이하")
        state.write_state(self.update, state.State())
        self.ctx.clock.advance(days=250)
        self.assertEqual(code_of(self.check), "UPDATE_MANIFEST_EXPIRED")
        self.ctx.clock.now = fs.NOW
        state.write_state(self.update, state.State(last_seen_utc="2026-12-10T00:00:00Z"))
        self.assertEqual(code_of(self.check), "UPDATE_MANIFEST_EXPIRED", "전에 본 시각보다 이틀 넘게 뒤로 간 시계")

    def test_a_changed_manifest_byte_or_signature_byte_is_refused(self):
        data = bytearray(self.release.manifest_bytes)
        data[40] ^= 1
        (self.chosen / "update-manifest.json").write_bytes(bytes(data))
        self.assertEqual(code_of(self.check), "UPDATE_SIGNATURE_INVALID")
        (self.chosen / "update-manifest.json").write_bytes(self.release.manifest_bytes)
        sig = bytearray(self.release.signature)
        sig[3] = ord("A") if sig[3] != ord("A") else ord("B")
        (self.chosen / "update-manifest.json.sig").write_bytes(bytes(sig))
        self.assertEqual(code_of(self.check), "UPDATE_SIGNATURE_INVALID")

    def test_a_missing_or_unusable_folder_and_files_are_refused_without_the_path_in_the_reason(self):
        def reason(path):
            try:
                update_flow.check_from_folder(self.ctx, path, current_version="1.0.0", install_kind="inno", keyring=fs.RING)
            except AppError as error:
                return error.code, str(error.detail)
            return None, ""
        missing_dir, a_file = self.tmp / "nope-folder", self.tmp / "a-file.txt"
        a_file.write_bytes(b"x")
        for label, path, detail in (("없는 폴더", missing_dir, "folder:not_a_folder"), ("폴더가 아니라 파일", a_file, "folder:not_a_folder")):
            with self.subTest(label=label):
                self.assertEqual(reason(path), ("UPDATE_MANIFEST_INVALID", detail))
        for label, skip, detail in (("매니페스트 없음", ("update-manifest.json",), "folder:manifest_missing"), ("서명 없음", ("update-manifest.json.sig",), "folder:signature_missing")):
            with self.subTest(label=label):
                lay = lay_out(self.release, self.tmp / ("skip-" + label), skip=skip)
                self.assertEqual(reason(lay), ("UPDATE_MANIFEST_INVALID", detail))
                self.assertNotIn(str(self.tmp), detail)
        big = lay_out(self.release, self.tmp / "big", replace={"update-manifest.json": b"x" * (manifest_module.MAX_MANIFEST_BYTES + 1)})
        self.assertEqual(reason(big), ("UPDATE_MANIFEST_INVALID", "folder:manifest_too_large"))
        big_sig = lay_out(self.release, self.tmp / "bigsig", replace={"update-manifest.json.sig": b"A" * (source.SIGNATURE_LIMIT + 1)})
        self.assertEqual(reason(big_sig), ("UPDATE_MANIFEST_INVALID", "folder:signature_too_large"))

    def test_a_directory_or_a_link_in_place_of_the_manifest_is_not_followed(self):
        trap = self.tmp / "trap"
        lay_out(self.release, trap, skip=("update-manifest.json",))
        (trap / "update-manifest.json").mkdir()
        self.assertEqual(code_of(update_flow.check_from_folder, self.ctx, trap, current_version="1.0.0", install_kind="inno", keyring=fs.RING), "UPDATE_MANIFEST_INVALID")
        linked = self.tmp / "linked"
        lay_out(self.release, linked, skip=("update-manifest.json",))
        try:
            os.symlink(self.chosen / "update-manifest.json", linked / "update-manifest.json")
        except (OSError, NotImplementedError):
            self.skipTest("이 환경은 링크를 만들 수 없다")
        self.assertEqual(code_of(update_flow.check_from_folder, self.ctx, linked, current_version="1.0.0", install_kind="inno", keyring=fs.RING), "UPDATE_MANIFEST_INVALID", "링크인 매니페스트는 따라가지 않는다")
        try:
            os.symlink(self.chosen, self.tmp / "folder-link", target_is_directory=True)
        except (OSError, NotImplementedError):
            return
        self.assertEqual(code_of(update_flow.check_from_folder, self.ctx, self.tmp / "folder-link", current_version="1.0.0", install_kind="inno", keyring=fs.RING), "UPDATE_MANIFEST_INVALID", "링크인 폴더도 따라가지 않는다")


class StageTest(FolderCase):
    def stage(self, **kwargs):
        check = self.check()
        return update_flow.stage_update_from_folder(self.ctx, check, **kwargs)

    def test_the_needed_files_are_copied_whole_and_verified_and_the_chosen_folder_is_untouched(self):
        before = snapshot(self.chosen)
        staged = self.stage()
        self.assertEqual(sorted(staged.files), ["setup"], "Inno 는 Setup 하나만 복사한다")
        for role, path in staged.files.items():
            entry = staged.manifest.file(role)
            self.assertEqual(Path(path).read_bytes(), self.release.bodies[entry.name])
            self.assertEqual(Path(path).parent, staged.folder)
        self.assertEqual((staged.folder / "update-manifest.json").read_bytes(), self.release.manifest_bytes)
        self.assertEqual((staged.folder / "update-manifest.json.sig").read_bytes(), self.release.signature)
        self.assertEqual(sorted(path.name for path in staged.folder.iterdir() if path.suffix == ".part"), [])
        self.assertEqual(snapshot(self.chosen), before, "고른 폴더는 읽기만 한다 — 이름도 내용도 그대로")
        self.assertEqual(self.staging_runs(), [staged.folder.name])

    def test_progress_is_reported_up_to_the_end(self):
        seen = []
        self.stage(progress=lambda fraction, text: seen.append((round(fraction, 2), text)))
        self.assertEqual(seen[0][0], 0.0)
        self.assertEqual(seen[-1], (1.0, "1/1"))

    def test_a_missing_asset_a_wrong_size_and_a_same_size_change_are_refused_and_leave_nothing(self):
        package = next(name for name in self.release.bodies if name.endswith("-Setup.exe"))          # (변수 이름은 옛 그대로 — 받는 파일은 이제 Setup 하나다)
        cases = (("자산 없음", dict(skip=(package,)), "UPDATE_MANIFEST_INVALID"), ("짧은 파일", dict(replace={package: self.release.bodies[package][:-1]}), "UPDATE_SIGNATURE_INVALID"),
                 ("긴 파일", dict(replace={package: self.release.bodies[package] + b"x"}), "UPDATE_SIGNATURE_INVALID"),
                 ("같은 크기 다른 내용", dict(replace={package: bytes([self.release.bodies[package][0] ^ 1]) + self.release.bodies[package][1:]}), "UPDATE_SIGNATURE_INVALID"))
        for label, options, code in cases:
            with self.subTest(label=label):
                self.chosen = lay_out(self.release, self.tmp / ("case-" + label), **options)
                check = self.check()
                self.assertEqual(code_of(update_flow.stage_update_from_folder, self.ctx, check), code)
                self.assertEqual(self.staging_runs(), [], "실패하면 임시 폴더를 남기지 않는다")

    def test_a_directory_in_place_of_an_asset_is_refused(self):
        package = next(name for name in self.release.bodies if name.endswith("-Setup.exe"))          # (변수 이름은 옛 그대로 — 받는 파일은 이제 Setup 하나다)
        self.chosen = lay_out(self.release, self.tmp / "dir-asset", skip=(package,))
        (self.chosen / package).mkdir()
        check = self.check()
        self.assertEqual(code_of(update_flow.stage_update_from_folder, self.ctx, check), "UPDATE_MANIFEST_INVALID")
        self.assertEqual(self.staging_runs(), [])

    def test_a_file_that_grows_while_it_is_copied_is_refused_and_removed(self):
        package = next(name for name in self.release.bodies if name.endswith("-Setup.exe"))          # (변수 이름은 옛 그대로 — 받는 파일은 이제 Setup 하나다)
        entry = next(item for item in self.release.dict["files"] if item["name"] == package)
        self.chosen = lay_out(self.release, self.tmp / "grown", replace={package: self.release.bodies[package] + b"extra" * 100})
        check = self.check()
        with mock.patch.object(source, "_regular_size", lambda path: entry["size"] if Path(path).name == package else Path(path).stat().st_size):          # 크기 확인은 속이고 복사 때 실제 크기를 만난다
            self.assertEqual(code_of(update_flow.stage_update_from_folder, self.ctx, check), "UPDATE_SIGNATURE_INVALID")
        self.assertEqual(self.staging_runs(), [])

    def test_a_short_disk_is_refused_before_anything_is_copied(self):
        check = self.check()
        self.assertEqual(code_of(update_flow.stage_update_from_folder, self.ctx, check, free_bytes=lambda folder: 10), "DISK_FULL")
        self.assertEqual(self.staging_runs(), [])

    def test_the_reasons_never_carry_the_folder_path_or_file_names(self):
        package = next(name for name in self.release.bodies if name.endswith("-Setup.exe"))          # (변수 이름은 옛 그대로 — 받는 파일은 이제 Setup 하나다)
        self.chosen = lay_out(self.release, self.tmp / "secret-place-name", skip=(package,))
        check = self.check()
        with self.assertRaises(AppError) as caught:
            update_flow.stage_update_from_folder(self.ctx, check)
        shown = f"{caught.exception.detail} {caught.exception.rendered().message} {caught.exception.rendered().action}"
        self.assertNotIn("secret-place-name", shown)
        self.assertNotIn(package, shown)
        self.assertNotIn(str(self.tmp), shown)

    def test_only_a_folder_check_that_is_available_and_installable_can_be_staged(self):
        online = update_flow.CheckResult("AVAILABLE", self.check().manifest, True, "1.0.0")
        self.assertEqual(code_of(update_flow.stage_update_from_folder, self.ctx, online), "UPDATE_CHECK_FAILED")
        same = self.check(current_version="1.0.1")
        self.assertEqual(code_of(update_flow.stage_update_from_folder, self.ctx, same), "UPDATE_CHECK_FAILED")
        portable = self.check(install_kind="portable")
        self.assertEqual(code_of(update_flow.stage_update_from_folder, self.ctx, portable), "UPDATE_NOT_INSTALLED_KIND")
        self.assertEqual(self.staging_runs(), [])


class WholeWalkTest(FolderCase):
    def test_the_session_walks_check_prepare_apply_in_the_same_order_as_online_with_no_connection(self):
        adapter = fs.FakeAdapter(self.update)
        session = update_flow.UpdateSession(self.ctx, install_kind="inno", current_version="1.0.0", keyring=fs.RING, adapter=adapter)
        before = snapshot(self.chosen)
        self.assertEqual(session.check_folder(self.chosen).status, "AVAILABLE")
        self.assertEqual(session.state, machine.AVAILABLE)
        session.prepare_from_folder()
        self.assertEqual(session.state, machine.READY)
        result = session.apply(confirmed=True)
        self.assertEqual(session.state, machine.HANDED_OFF)
        self.assertTrue(result.handed_off)
        self.assertEqual([(roles, old, new, recovery) for roles, old, new, recovery in adapter.calls], [(["setup"], "1.0.0", "1.0.1", False)])
        self.assertEqual((adapter.pending_seen[0].from_version, adapter.pending_seen[0].to_version), ("1.0.0", "1.0.1"), "넘기기 전에 pending 이 적혀 있었다")
        after = state.read_state(self.update)
        self.assertEqual((after.last_seq, after.pending.to_version, after.pending.backup_name == result.backup_name), (self.release.dict["seq"], "1.0.1", True))
        self.assertEqual(snapshot(self.chosen), before, "고른 폴더는 끝까지 그대로")

    def test_a_check_from_a_folder_cannot_be_downloaded_from_the_internet_and_the_machine_does_not_move(self):
        session = update_flow.UpdateSession(self.ctx, install_kind="inno", current_version="1.0.0", keyring=fs.RING, adapter=fs.FakeAdapter(self.update))
        session.check_folder(self.chosen)
        with fs.switches_on("NET_UPDATE_CHECK"):
            with self.assertRaises(AppError) as caught:
                session.download()
        self.assertEqual((caught.exception.code, session.state), ("UPDATE_CHECK_FAILED", machine.AVAILABLE))

    def test_a_failed_folder_check_returns_the_machine_to_the_failed_state_with_the_error_kept(self):
        session = update_flow.UpdateSession(self.ctx, install_kind="inno", current_version="1.0.0", keyring=keys.shipped_keyring())
        with self.assertRaises(AppError):
            session.check_folder(self.chosen)
        self.assertEqual((session.state, session.error.code), (machine.CHECK_FAILED, "UPDATE_SIGNATURE_INVALID"))

    def test_a_failed_copy_returns_the_machine_to_idle(self):
        package = next(name for name in self.release.bodies if name.endswith("-Setup.exe"))          # (변수 이름은 옛 그대로 — 받는 파일은 이제 Setup 하나다)
        self.chosen = lay_out(self.release, self.tmp / "short", replace={package: self.release.bodies[package][:-5]})
        session = update_flow.UpdateSession(self.ctx, install_kind="inno", current_version="1.0.0", keyring=fs.RING)
        session.check_folder(self.chosen)
        with self.assertRaises(AppError):
            session.prepare_from_folder()
        self.assertEqual((session.state, session.error.code), (machine.IDLE, "UPDATE_SIGNATURE_INVALID"))


class SwitchTest(FolderCase):
    def test_with_the_apply_switch_off_every_entry_refuses_before_reading_or_writing_anything(self):
        session = update_flow.UpdateSession(self.ctx, install_kind="inno", current_version="1.0.0", keyring=fs.RING)
        check = update_flow.CheckResult("AVAILABLE", self.check().manifest, True, "1.0.0", source="folder", folder=str(self.chosen))
        state_file = self.update / "state.json"
        if state_file.exists():
            state_file.unlink()
        calls = (lambda: update_flow.check_from_folder(self.ctx, self.chosen, current_version="1.0.0", keyring=fs.RING), lambda: update_flow.stage_update_from_folder(self.ctx, check),
                 lambda: session.check_folder(self.chosen), lambda: session.prepare_from_folder())
        with mock.patch.object(capabilities, "UPDATE_APPLY", False):
            for index, call in enumerate(calls):
                with self.subTest(entry=index):
                    self.assertEqual(code_of(call), "UPDATE_DISABLED")
        self.assertFalse(state_file.exists(), "꺼져 있으면 상태 파일도 만들지 않는다")
        self.assertEqual(self.staging_runs(), [])
        self.assertEqual(session.state, machine.IDLE, "상태 기계도 움직이지 않았다")


class EntryShapeTest(unittest.TestCase):
    def test_the_folder_entries_start_with_the_apply_gate_and_import_nothing_that_connects(self):
        tree = ast.parse((SRC / "service" / "update_flow.py").read_text(encoding="utf-8"))

        def first(function):
            body = [node for node in function.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
            return ast.unparse(body[0])
        top = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(first(top["check_from_folder"]), "capabilities.require_update_apply('폴더에서 업데이트')")
        self.assertEqual(first(top["stage_update_from_folder"]), "capabilities.require_update_apply('업데이트 준비')")
        session = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "UpdateSession")
        methods = {node.name: node for node in session.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(first(methods["check_folder"]), "capabilities.require_update_apply('폴더에서 업데이트')")
        self.assertEqual(first(methods["prepare_from_folder"]), "capabilities.require_update_apply('업데이트 준비')")
        for name in ("check_from_folder", "stage_update_from_folder", "check_folder", "prepare_from_folder"):
            function = top.get(name) or methods[name]
            text = ast.unparse(function)
            self.assertNotIn("require_net", text, f"{name}: 접속 스위치 관문이 아니다 — 접속이 없다")
            self.assertNotIn("_client(", text, f"{name}: 접속 클라이언트를 만들지 않는다")
            self.assertNotIn("external.", text, f"{name}: 접속 등록부를 쓰지 않는다")

    def test_the_source_module_reads_the_folder_without_any_write_into_it(self):
        text = (SRC / "update" / "source.py").read_text(encoding="utf-8")
        body = text[text.index("def read_folder_manifest"):text.index("def find_staged_run")]
        self.assertIn('.open("rb")', body)
        for forbidden in ("write_bytes(folder", "open(\"wb\")", "unlink(", "rename(", "shutil.move", "os.remove"):
            self.assertNotIn(forbidden, body)
        tree = ast.parse(body)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        for call in calls:
            if call.func.attr == "open" and call.args:
                mode = call.args[0]
                self.assertIsInstance(mode, ast.Constant)
                self.assertIn(mode.value, ("rb", "xb"), "고른 폴더의 파일은 'rb' 로만 열고 임시 폴더의 새 파일은 'xb' 로만 연다")


if __name__ == "__main__":
    unittest.main()
