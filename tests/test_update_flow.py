"""`service/update_flow.py` 시험(UPDATE 설계서 3-4·3-5·3-6·3-9, v1update U-3) — 확인 → 내려받기 → 적용 → 복구, 가짜 릴리스 서버 위에서 앱의 **진짜 접속 틀**로.

지키는 것:
  1) 확인: 요청은 고정 주소 읽기뿐이고(최신 릴리스 → 태그 길 → 자산 호스트로 이동) 서명이 맞아야 값을 믿는다. 모든 실패는 `UPDATE_*` 코드(꺼짐·시계·쉬는 중·디스크는 그대로)이고 마지막 확인 결과가 상태 파일에 남는다. **확인은 `last_seq` 를 올리지 않는다.**
     서명 불일치는 한 번만 다시 받는다(릴리스가 공개되는 순간의 두 파일 어긋남). 스위치가 꺼졌거나 어댑터가 꽂히지 않았으면 접속 전에 끝난다.
  2) 내려받기: 필요한 파일만(Velopack 은 패키지·피드), 크기·해시를 서명된 값과 정확히 맞춘다 — 틀리면 폴더째 지우고 `UPDATE_SIGNATURE_INVALID`, 끊김·크기 초과·이동 거절은 `UPDATE_DOWNLOAD_FAILED`, 디스크 모자람은 받기 전 `DISK_FULL`.
  3) 적용: 확인 표시 → 잠금 → 다시 해시 → **백업이 완료일 때만** → `pending` 기록 → 설치 도구에 넘기기 → `last_seq` 올리기. 넘기기가 실패하면 `pending` 을 지우고 지금 판 그대로. 어느 자리에서 프로세스가 죽어도 다음 시작이 이어간다(각 자리에서 죽여 본다).
  4) 복구: 사용자가 '복구' 를 눌렀을 때만, 보관한 이전 판(없으면 이전 릴리스를 다시 받아)으로 — 낮은 판은 `pending.from` 하나뿐, 서명은 같게 확인하고 만료는 보지 않는다.
  5) `UpdateSession` 은 순서가 틀린 호출을 아무것도 하지 않고 거절한다.
네트워크는 한 번도 열리지 않는다(가짜 소켓, `Tripwire` 로 바깥 호출 0 을 확인).
"""
import ast
import contextlib
import dataclasses
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

import net_support as ns  # noqa: E402
import outgoing_support as og  # noqa: E402
import update_flow_support as fs  # noqa: E402
import update_support as us  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow, external, update_flow  # noqa: E402
from chanceblog_desktop.update import apply, health, keys, machine, recovery, source, state  # noqa: E402
from chanceblog_desktop.update import manifest as manifest_module  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"


def code_of(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code
    return None


class FlowCase(unittest.TestCase):
    switches = ("NET_UPDATE_CHECK",)

    def setUp(self):
        holder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        self.ctx = fs.make_world(self.tmp)
        self.folder = update_flow.update_folder(self.ctx)
        self.server = fs.ReleaseServer()
        self.release = fs.Release("1.0.1")
        self.release.install(self.server)
        self.harness = fs.FlowHarness(self, self.server, switches=self.switches)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(self.harness)
        stack.enter_context(self.harness.plugged())
        self.wire = stack.enter_context(og.Tripwire())

    def tearDown(self):
        self.assertEqual(self.wire.calls, [], "진짜 바깥 호출이 일어났다")

    def check(self, **overrides):
        options = dict(current_version="1.0.0", install_kind="velopack", keyring=fs.RING)
        options.update(overrides)
        return update_flow.check_for_update(self.ctx, **options)

    def state(self):
        return state.read_state(self.folder)

    def staging_runs(self):
        root = health.staging_root(self.folder)
        return sorted(path.name for path in root.iterdir()) if root.is_dir() else []


class CheckTest(FlowCase):
    def test_an_available_release_is_found_through_the_fixed_requests_only(self):
        result = self.check()
        self.assertEqual((result.status, result.apply_possible, result.manifest.version, result.current_version), ("AVAILABLE", True, "1.0.1", "1.0.0"))
        self.assertEqual(self.server.hosts(), ["github.com", fs.CDN_HOST])
        self.assertEqual(len(self.server.requests), 6, "매니페스트와 서명 각각 최신 길 → 태그 길 → 자산 호스트")
        for host, method, target, head in self.server.requests:
            lines = head.split("\r\n")[1:]
            self.assertEqual(method, "GET")
            self.assertEqual([line.split(":", 1)[0] for line in lines], ["Host", "User-Agent", "Accept", "Accept-Encoding", "Connection"])
            self.assertEqual(lines[1:], ["User-Agent: ChanceBlogDesktop", "Accept: */*", "Accept-Encoding: identity", "Connection: close"])
            self.assertEqual(lines[0], f"Host: {host}")
        after = self.state()
        self.assertEqual((after.last_seq, after.last_check.result, after.last_check.version, after.last_check.code, after.last_seen_utc), (0, "AVAILABLE", "1.0.1", "", "2026-12-02T00:00:00Z"))
        self.assertIsNone(after.pending)
        self.assertEqual(result.manifest_bytes, self.release.manifest_bytes)
        self.assertEqual(self.staging_runs(), [], "확인은 아무것도 내려받아 두지 않는다")

    def test_a_check_never_raises_last_seq(self):
        state.write_state(self.folder, state.State(last_seq=5))
        self.check()
        self.assertEqual(self.state().last_seq, 5)

    def test_the_same_version_is_up_to_date_even_when_the_stored_seq_equals_its_own(self):
        state.write_state(self.folder, state.State(last_seq=self.release.dict["seq"]))
        result = self.check(current_version="1.0.1")
        self.assertEqual((result.status, result.apply_possible), ("UP_TO_DATE", False))
        self.assertEqual(self.state().last_check.result, "UP_TO_DATE")

    def test_refusals_carry_the_documented_codes_and_the_last_check_is_recorded(self):
        cases = (("낮은 판", dict(current_version="2.0.0"), "UPDATE_DOWNGRADE_BLOCKED"), ("최소 버전", dict(current_version="0.9.0"), "UPDATE_NEEDS_MANUAL_INSTALL"),
                 ("설치 종류", dict(install_kind="inno"), "UPDATE_NEEDS_MANUAL_INSTALL"), ("출하 키(비어 있음)", dict(keyring=keys.shipped_keyring()), "UPDATE_SIGNATURE_INVALID"))
        for label, overrides, code in cases:
            with self.subTest(label=label):
                self.assertEqual(code_of(self.check, **overrides), code)
                self.assertEqual((self.state().last_check.result, self.state().last_check.code), ("CHECK_FAILED", code))
        release = fs.Release("1.0.2", min_version="1.0.0")
        state.write_state(self.folder, state.State(last_seq=release.dict["seq"]))
        release.install(self.server)
        self.assertEqual(code_of(self.check), "UPDATE_DOWNGRADE_BLOCKED", "저장된 시퀀스 이하")

    def test_an_expired_manifest_and_a_clock_far_behind_are_refused(self):
        self.ctx.clock.advance(days=250)
        self.assertEqual(code_of(self.check), "UPDATE_MANIFEST_EXPIRED")
        self.ctx.clock.now = fs.NOW
        state.write_state(self.folder, state.State(last_seen_utc="2026-12-10T00:00:00Z"))
        self.assertEqual(code_of(self.check), "UPDATE_MANIFEST_EXPIRED", "전에 본 시각보다 이틀 넘게 뒤로 간 시계")
        state.write_state(self.folder, state.State(last_seen_utc="2026-12-03T00:00:00Z"))
        self.assertEqual(self.check().status, "AVAILABLE")

    def test_the_seen_time_never_goes_backwards(self):
        state.write_state(self.folder, state.State(last_seen_utc="2026-12-03T00:00:00Z"))
        self.check()
        self.assertEqual(self.state().last_seen_utc, "2026-12-03T00:00:00Z")

    def test_net_failures_become_the_check_failed_code_and_cooldown_and_tls_pass_through(self):
        down = fs.FlowHarness(self, self.server, dial_error=OSError("no route"))
        with down, external.registered(external.KIND_UPDATE, down.factory):
            self.assertEqual(code_of(self.check), "UPDATE_CHECK_FAILED")
        self.assertEqual((self.state().last_check.result, self.state().last_check.code), ("CHECK_FAILED", "UPDATE_CHECK_FAILED"))
        empty = fs.ReleaseServer()
        missing = fs.FlowHarness(self, empty)
        with missing, external.registered(external.KIND_UPDATE, missing.factory):
            self.assertEqual(code_of(self.check), "UPDATE_CHECK_FAILED", "404")
            with mock.patch.object(update_flow.source, "fetch_manifest", side_effect=AppError("NET_COOLDOWN", {"재시도 가능 시각": "10:00"})):
                self.assertEqual(code_of(self.check), "NET_COOLDOWN")
            with mock.patch.object(update_flow.source, "fetch_manifest", side_effect=AppError("NET_TLS_FAILED")):
                self.assertEqual(code_of(self.check), "NET_TLS_FAILED")

    def test_the_failure_detail_carries_codes_not_server_text(self):
        canary = "CANARY_" + "SERVER_" + "TEXT"
        body = ns.http_response(500, "Server Error", body=canary.encode())
        server = fs.ReleaseServer()
        server.respond = lambda host, method, target, head: body
        broken = fs.FlowHarness(self, server)
        with broken, external.registered(external.KIND_UPDATE, broken.factory):
            try:
                self.check()
            except AppError as error:
                for shown in (str(error), error.detail, error.log_line(), error.rendered().message, error.rendered().action, repr(error.slots)):
                    self.assertNotIn(canary, shown)
                self.assertEqual(error.code, "UPDATE_CHECK_FAILED")
            else:
                self.fail("거절돼야 한다")

    def test_a_signature_that_does_not_match_is_retried_once_for_the_publishing_race_and_no_more(self):
        other = fs.Release("1.0.2")
        sig_cdn = fs.cdn_path("update-manifest.json.sig")
        manifest_cdn = fs.cdn_path("update-manifest.json")
        self.server.put(fs.CDN_HOST, sig_cdn, other.signature)                         # 첫 시도: 서명 파일이 다른 릴리스의 것
        seen = []

        def heal():
            seen.append(1)
            if len(seen) == 2:                                                         # 두 번째 시도의 매니페스트 요청에서 서버가 일치하게 된다
                self.server.put(fs.CDN_HOST, sig_cdn, self.release.signature)
        self.server.hooks[(fs.CDN_HOST, manifest_cdn)] = heal
        self.assertEqual(self.check().status, "AVAILABLE")
        self.assertEqual(len(self.server.requests), 12)
        self.server.requests.clear()
        self.server.put(fs.CDN_HOST, sig_cdn, other.signature)                         # 계속 어긋난다
        self.server.hooks.clear()
        self.assertEqual(code_of(self.check), "UPDATE_SIGNATURE_INVALID")
        self.assertEqual(len(self.server.requests), 12, "정확히 두 번까지만 받는다")

    def test_other_refusals_are_not_retried(self):
        state.write_state(self.folder, state.State(last_seq=self.release.dict["seq"]))
        self.assertEqual(code_of(self.check), "UPDATE_DOWNGRADE_BLOCKED")
        self.assertEqual(len(self.server.requests), 6)

    def test_a_bad_current_version_or_state_stops_before_any_request(self):
        for bad in ("", "x", "1.0"):
            self.assertEqual(code_of(self.check, current_version=bad), "UPDATE_CHECK_FAILED", bad)
        self.assertEqual(self.server.requests, [])
        self.folder.mkdir(parents=True)
        (self.folder / "state.json").write_bytes(b"{broken")
        self.assertEqual(self.check().status, "AVAILABLE")
        self.assertEqual((self.folder / "state.json.bak").read_bytes(), b"{broken")
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("x")):
            self.server.requests.clear()
            self.assertEqual(code_of(self.check), "UPDATE_CHECK_FAILED")
        self.assertEqual(self.server.requests, [])

    def test_old_leftover_download_folders_are_swept_and_fresh_ones_are_kept(self):
        old, fresh = health.staging_root(self.folder) / "oldrun", health.staging_root(self.folder) / "freshrun"
        for run in (old, fresh):
            run.mkdir(parents=True)
            (run / "x.part").write_bytes(b"x")
        past, recent = fs.NOW.timestamp() - 2 * 86400, fs.NOW.timestamp() - 3600            # 시험 시계(맥락 시계)는 2026-12-02 — 파일의 고친 때도 그 시계에 맞춘다
        os.utime(old, (past, past))
        os.utime(fresh, (recent, recent))
        self.check()
        self.assertEqual(self.staging_runs(), ["freshrun"])

    def test_the_manifest_text_and_signature_are_kept_for_the_download(self):
        result = self.check()
        self.assertEqual((result.manifest_bytes, result.signature_bytes), (self.release.manifest_bytes, self.release.signature))


class GateOffTest(unittest.TestCase):
    """스위치가 꺼졌거나 어댑터가 꽂히지 않았을 때 — 접속 전에 끝나고 아무것도 만들지 않는다."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(holder.cleanup)
        self.ctx = fs.make_world(Path(holder.name))
        self.folder = update_flow.update_folder(self.ctx)

    def test_every_public_entry_refuses_before_touching_anything_when_its_switch_is_off(self):
        release = fs.Release("1.0.1")
        check = update_flow.CheckResult("AVAILABLE", manifest_module.read_and_verify(release.manifest_bytes, release.signature, keyring=fs.RING), True, "1.0.0", release.manifest_bytes, release.signature)
        staged = source.StagedUpdate(Path(self.ctx.workspace.root) / "x", {}, check.manifest)
        calls = {"check": lambda: update_flow.check_for_update(self.ctx, current_version="1.0.0"), "download": lambda: update_flow.download_update(self.ctx, check),
                 "apply": lambda: update_flow.apply_update(self.ctx, check, staged, confirmed=True), "recover": lambda: update_flow.recover_update(self.ctx, confirmed=True)}
        expected = {"check": "NETWORK_DISABLED", "download": "NETWORK_DISABLED", "apply": "UPDATE_DISABLED", "recover": "UPDATE_DISABLED"}
        with og.Tripwire() as wire:
            for name, call in calls.items():
                with self.subTest(entry=name):
                    self.assertEqual(code_of(call), expected[name])
        self.assertEqual(wire.calls, [])
        self.assertFalse(self.folder.exists(), "아무것도 만들지 않았다")
        self.assertEqual(list(self.ctx.workspace.root.glob("backups")), [])

    def test_with_the_check_switch_on_but_no_adapter_plugged_nothing_connects(self):
        with fs.switches_on("NET_UPDATE_CHECK"), og.Tripwire() as wire:
            self.assertEqual(code_of(update_flow.check_for_update, self.ctx, current_version="1.0.0", keyring=fs.RING), "NETWORK_DISABLED")
        self.assertEqual(wire.calls, [])
        self.assertEqual(self.ctx.stamp(), "2026-12-02T00:00:00Z")

    def test_the_registered_factory_is_the_wiring_one_when_the_switch_is_on_and_absent_when_off(self):
        from chanceblog_desktop.service import wiring
        external.unregister(external.KIND_UPDATE)
        self.assertEqual(wiring.register_enabled(), ())
        with fs.switches_on("NET_UPDATE_CHECK"):
            self.assertEqual(wiring.register_enabled(), ("update",))
            self.assertIs(external.adapter_factory(external.KIND_UPDATE), wiring._update_factory)
        external.unregister(external.KIND_UPDATE)
        self.assertIsNone(external.adapter_factory(external.KIND_UPDATE))


class DownloadTest(FlowCase):
    switches = ("NET_UPDATE_CHECK",)

    def downloaded(self, **kwargs):
        result = self.check()
        return result, update_flow.download_update(self.ctx, result, **kwargs)

    def test_only_the_needed_files_are_fetched_whole_and_verified_and_the_proof_is_kept_beside_them(self):
        result, staged = self.downloaded()
        self.assertEqual(sorted(staged.files), ["feed", "package"], "Velopack 은 패키지와 피드만")
        run = staged.folder
        self.assertEqual(sorted(path.name for path in run.iterdir()), sorted([f"ChanceBlogDesktopApp-1.0.1-stable-full.nupkg", "releases.stable.json", "update-manifest.json", "update-manifest.json.sig"]))
        for role, path in staged.files.items():
            entry = result.manifest.file(role)
            self.assertEqual((path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()), (entry.size, entry.sha256))
        self.assertEqual((run / "update-manifest.json").read_bytes(), self.release.manifest_bytes)
        self.assertEqual((run / "update-manifest.json.sig").read_bytes(), self.release.signature)
        self.assertEqual(run.parent, health.staging_root(self.folder))
        self.assertNotIn(f"ChanceBlogDesktop-1.0.1-Setup.exe", [request[2] for request in self.server.requests])
        self.assertTrue(source.verify_staged(staged))

    def test_the_requests_for_files_are_the_tag_route_and_never_the_latest_pointer(self):
        self.downloaded()
        targets = [request[2] for request in self.server.requests[6:]]
        self.assertTrue(all(f"/download/v1.0.1/" in target or target.startswith("/github-production-release-asset/") for target in targets), targets)
        self.assertFalse([target for target in targets if "/latest/" in target])

    def test_a_tampered_file_of_the_same_size_is_refused_and_the_folder_is_removed(self):
        name = "ChanceBlogDesktopApp-1.0.1-stable-full.nupkg"
        body = bytearray(self.release.bodies[name])
        body[10] ^= 1
        self.release.install(self.server, tamper={name: bytes(body)})
        result = self.check()
        self.assertEqual(code_of(update_flow.download_update, self.ctx, result), "UPDATE_SIGNATURE_INVALID")
        self.assertEqual(self.staging_runs(), [])

    def test_a_shorter_or_longer_body_is_refused_and_the_folder_is_removed(self):
        name = "releases.stable.json"
        for label, body, code in (("짧음", self.release.bodies[name][:-1], "UPDATE_SIGNATURE_INVALID"), ("김", self.release.bodies[name] + b"x", "UPDATE_DOWNLOAD_FAILED")):
            with self.subTest(label=label):
                self.release.install(self.server, tamper={name: body})
                result = self.check()
                self.assertEqual(code_of(update_flow.download_update, self.ctx, result), code)
                self.assertEqual(self.staging_runs(), [])

    def test_a_missing_asset_and_an_unlisted_redirect_host_fail_the_download_and_leave_nothing(self):
        result = self.check()
        self.server.routes.pop((fs.CDN_HOST, fs.cdn_path("releases.stable.json")))
        self.assertEqual(code_of(update_flow.download_update, self.ctx, result), "UPDATE_DOWNLOAD_FAILED")
        self.assertEqual(self.staging_runs(), [])
        self.server.redirect("github.com", f"{fs.BASE}/download/v1.0.1/releases.stable.json", "https://evil.example.test/x")
        self.assertEqual(code_of(update_flow.download_update, self.ctx, result), "UPDATE_DOWNLOAD_FAILED")
        self.assertEqual(self.staging_runs(), [])
        self.assertNotIn("evil.example.test", [host for host, _address in self.harness.dials], "표 밖 호스트로는 연결하지 않았다")

    def test_a_short_disk_is_refused_before_anything_is_fetched_and_the_boundary_passes(self):
        result = self.check()
        sizes = [result.manifest.file(role).size for role in ("package", "feed")]
        backup = update_flow.estimate_backup_bytes(self.ctx)
        needed = sum(sizes) * source.DISK_MULTIPLIER + backup
        before = len(self.server.requests)
        self.assertEqual(code_of(update_flow.download_update, self.ctx, result, free_bytes=lambda folder: needed - 1), "DISK_FULL")
        self.assertEqual((len(self.server.requests), self.staging_runs()), (before, []), "받기 전에 거절 — 요청 0·폴더 0")
        staged = update_flow.download_update(self.ctx, result, free_bytes=lambda folder: needed)
        self.assertEqual(sorted(staged.files), ["feed", "package"])
        self.assertGreater(backup, 0, "백업 예상 크기가 실제로 더해진다(빈 실험이 아니다)")

    def test_a_portable_build_an_up_to_date_result_and_a_missing_role_never_download(self):
        portable = self.check(install_kind="portable")
        before = len(self.server.requests)
        self.assertEqual(code_of(update_flow.download_update, self.ctx, portable), "UPDATE_NOT_INSTALLED_KIND")
        up = self.check(current_version="1.0.1")
        self.assertEqual(code_of(update_flow.download_update, self.ctx, up), "UPDATE_CHECK_FAILED")
        self.assertEqual(len(self.server.requests), before + 6, "내려받기 요청은 없었다(확인 요청만 늘었다)")
        thin = fs.Release("1.0.2")
        thin.dict["files"] = [entry for entry in thin.dict["files"] if entry["role"] != "feed"]
        thin.manifest_bytes = us.encode_manifest(thin.dict)
        thin.signature = us.signature_file(thin.seed, thin.manifest_bytes)
        thin.install(self.server)
        result = self.check()
        self.assertEqual(code_of(update_flow.download_update, self.ctx, result), "UPDATE_MANIFEST_INVALID")

    def test_progress_is_reported_up_to_the_end(self):
        seen = []
        self.downloaded(progress=lambda fraction, text: seen.append(fraction))
        self.assertEqual((seen[0], seen[-1]), (0.0, 1.0))
        self.assertEqual(seen, sorted(seen))


class ApplyCase(FlowCase):
    switches = ("NET_UPDATE_CHECK", "UPDATE_APPLY")

    def setUp(self):
        super().setUp()
        self.result = self.check()
        self.staged = update_flow.download_update(self.ctx, self.result)
        self.adapter = fs.FakeAdapter(self.folder)

    def apply(self, **overrides):
        options = dict(adapter=self.adapter, confirmed=True)
        options.update(overrides)
        return update_flow.apply_update(self.ctx, self.result, self.staged, **options)

    def backups(self):
        root = self.ctx.workspace.backups_dir
        return sorted(path.name for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


class ApplyTest(ApplyCase):
    def test_the_order_is_confirm_verify_backup_pending_handoff_last_seq(self):
        done = self.apply()
        self.assertEqual((done.handed_off, done.to_version), (True, "1.0.1"))
        self.assertEqual(self.adapter.calls, [(["feed", "package"], "1.0.0", "1.0.1", False)])
        seen = self.adapter.pending_seen[0]
        self.assertEqual((seen.from_version, seen.to_version, seen.seq, seen.boot_attempts, seen.kind), ("1.0.0", "1.0.1", self.release.dict["seq"], 0, "velopack"), "넘기는 순간 pending 은 이미 디스크에 있었다")
        self.assertEqual(seen.backup_name, done.backup_name)
        self.assertEqual(self.backups(), [done.backup_name], "넘기기 전에 백업이 완료돼 있었다")
        after = self.state()
        self.assertEqual((after.last_seq, after.pending), (self.release.dict["seq"], seen), "넘김이 성공한 뒤에 seq 를 올렸다")

    def test_without_the_confirmation_nothing_at_all_happens(self):
        for value in (False, None, 0, "yes"):
            with self.subTest(value=value):
                self.assertEqual(code_of(self.apply, confirmed=value), "CONFIRMATION_REQUIRED")
        self.assertEqual((self.adapter.calls, self.backups(), self.state().pending), ([], [], None))

    def test_a_file_changed_after_the_download_is_refused_before_the_backup(self):
        path = self.staged.files["package"]
        path.write_bytes(path.read_bytes()[:-1] + b"X")
        self.assertEqual(code_of(self.apply), "UPDATE_SIGNATURE_INVALID")
        self.assertEqual((self.adapter.calls, self.backups(), self.state().pending), ([], [], None))
        path.unlink()
        self.assertEqual(code_of(self.apply), "UPDATE_SIGNATURE_INVALID", "사라진 파일도 같다")

    def outcome(self, status):
        row = backup_flow.BackupRow("full-20261202-000000", "backup", "2026-12-02T00:00:00Z", status, 1, (), False)
        return backup_flow.BackupOutcome(row)

    def test_a_partial_or_broken_backup_never_lets_the_update_start(self):
        for status in ("partial", "broken"):
            with self.subTest(status=status), mock.patch.object(backup_flow, "create_full_backup", return_value=self.outcome(status)):
                self.assertEqual(code_of(self.apply), "UPDATE_BACKUP_FAILED")
                self.assertEqual((self.adapter.calls, self.state().pending, self.state().last_seq), ([], None, 0))

    def test_a_failing_backup_is_the_backup_failed_code_and_a_full_disk_passes_through(self):
        for raised, code in ((AppError("BACKUP_IN_PROGRESS", {"시작": "방금"}), "UPDATE_BACKUP_FAILED"), (AppError("CONTENT_NOT_FOUND", {"항목": "백업할 데이터"}), "UPDATE_BACKUP_FAILED"),
                             (AppError("FULL_BACKUP_BLOCKED", {"위치": "x"}), "UPDATE_BACKUP_FAILED"), (AppError("DISK_FULL", {"경로": "x"}), "DISK_FULL")):
            with self.subTest(raised=raised.code), mock.patch.object(backup_flow, "create_full_backup", side_effect=raised):
                self.assertEqual(code_of(self.apply), code)
                self.assertEqual((self.adapter.calls, self.state().pending), ([], None))

    def test_a_failed_hand_off_clears_the_marker_keeps_the_seq_and_reports_the_apply_failure(self):
        for raised, code in ((RuntimeError("boom C:/Users/someone"), "UPDATE_APPLY_FAILED"), (AppError("UPDATE_APPLY_FAILED", detail="exit:5"), "UPDATE_APPLY_FAILED"), (AppError("DISK_FULL"), "DISK_FULL")):
            with self.subTest(raised=type(raised).__name__):
                self.adapter = fs.FakeAdapter(self.folder, fail=raised)
                try:
                    self.apply()
                except AppError as error:
                    self.assertEqual(error.code, code)
                    for shown in (str(error), error.detail, error.log_line()):
                        self.assertNotIn("someone", shown)
                after = self.state()
                self.assertEqual((after.pending, after.last_seq), (None, 0), "지금 판 그대로")
                self.assertEqual(len(self.adapter.calls), 1)

    def test_a_missing_adapter_for_an_installed_kind_refuses_without_running_anything(self):
        self.assertEqual(code_of(update_flow.apply_update, self.ctx, self.result, self.staged, confirmed=True), "UPDATE_APPLY_FAILED")
        self.assertEqual((self.state().pending, self.state().last_seq), (None, 0))

    def test_a_second_update_or_recovery_is_refused_while_the_lock_is_held(self):
        lock = update_flow._UpdateLock(self.ctx.workspace.locks_dir, update_flow.LOCK_NAME, now=self.ctx.now, host="")
        lock.acquire()
        try:
            self.assertEqual(code_of(self.apply), "UPDATE_IN_PROGRESS")
            self.assertEqual((self.adapter.calls, self.backups(), self.state().pending), ([], [], None))
        finally:
            lock.release()
        self.assertEqual(self.apply().handed_off, True)
        self.assertFalse((self.ctx.workspace.locks_dir / "update.lock").exists(), "끝나면 잠금을 푼다")

    def test_the_lock_is_released_after_every_kind_of_failure(self):
        for patch in (mock.patch.object(backup_flow, "create_full_backup", side_effect=AppError("DISK_FULL")), contextlib.nullcontext()):
            with patch:
                self.adapter = fs.FakeAdapter(self.folder, fail=RuntimeError("x"))
                code_of(self.apply)
            self.assertFalse((self.ctx.workspace.locks_dir / "update.lock").exists())

    def test_apply_does_not_touch_the_network_at_all(self):
        before = len(self.server.requests)
        self.apply()
        self.assertEqual(len(self.server.requests), before)


class CrashTest(ApplyCase):
    """각 자리에서 프로세스가 죽었다고 치고(`Killed` — 어떤 `except Exception` 도 삼키지 못한다) 다음 시작이 어떻게 이어가는지 본다."""

    def next_boot(self, version):
        with fs.switches_on("UPDATE_APPLY"):
            return state.note_boot(version=version, folder=self.folder)

    def test_killed_inside_the_backup_leaves_no_marker_and_the_next_start_has_nothing_to_do(self):
        with mock.patch.object(backup_flow, "create_full_backup", side_effect=fs.Killed()):
            with self.assertRaises(fs.Killed):
                self.apply()
        self.assertFalse((self.ctx.workspace.locks_dir / "update.lock").exists(), "죽어도 finally 가 잠금을 푼다(진짜 죽음이면 낡은 잠금을 다음이 넘겨받는다)")
        self.assertEqual(self.next_boot("1.0.0").action, "none")

    def test_killed_after_the_marker_but_before_the_hand_off_is_seen_as_not_applied_by_the_old_version(self):
        self.adapter = fs.FakeAdapter(self.folder, kill=fs.Killed())
        with self.assertRaises(fs.Killed):
            self.apply()
        left = self.state()
        self.assertEqual((left.pending.to_version, left.last_seq), ("1.0.1", 0), "표식은 남았고 seq 는 아직이다")
        note = self.next_boot("1.0.0")
        self.assertEqual(note.action, "not_applied")
        after = self.state()
        self.assertEqual((after.pending, after.notice), (None, "not_applied"))

    def test_killed_after_a_successful_hand_off_but_before_the_seq_is_written_still_counts_the_new_version(self):
        real = state.write_state
        calls = []

        def die_on_second(folder, new_state):
            calls.append(1)
            if len(calls) == 2:
                raise fs.Killed()
            return real(folder, new_state)
        with mock.patch.object(state, "write_state", die_on_second):
            with self.assertRaises(fs.Killed):
                self.apply()
        self.assertEqual(len(self.adapter.calls), 1, "넘김은 끝났다")
        self.assertEqual((self.state().pending.to_version, self.state().last_seq), ("1.0.1", 0))
        self.assertEqual(self.next_boot("1.0.1").action, "first_boot")
        health.mark_healthy(self.folder)
        self.assertEqual(self.state().last_seq, self.release.dict["seq"], "정상 표식이 seq 를 확정한다")

    def test_three_unhealthy_starts_of_the_new_version_offer_the_recovery(self):
        self.apply()
        actions = [self.next_boot("1.0.1").action for _ in range(3)]
        self.assertEqual(actions, ["first_boot", "first_boot", "recovery_offered"])
        self.assertEqual(self.state().pending.boot_attempts, 2)

    def test_a_healthy_start_in_between_clears_everything_and_the_count_starts_over(self):
        self.apply()
        self.assertEqual(self.next_boot("1.0.1").action, "first_boot")
        health.mark_healthy(self.folder)
        self.assertEqual(self.next_boot("1.0.1").action, "none")

    def test_every_hand_off_failure_point_leaves_a_state_the_next_start_can_read(self):
        points = ("verify", "backup", "pending", "adapter", "seq")
        for point in points:
            with self.subTest(point=point):
                self.setUp() if point != points[0] else None
                self.adapter = fs.FakeAdapter(self.folder)
                patches = {"verify": mock.patch.object(source, "verify_staged", side_effect=fs.Killed()), "backup": mock.patch.object(backup_flow, "create_full_backup", side_effect=fs.Killed()),
                           "pending": mock.patch.object(state, "write_state", side_effect=fs.Killed()), "adapter": contextlib.nullcontext(), "seq": contextlib.nullcontext()}
                if point == "adapter":
                    self.adapter = fs.FakeAdapter(self.folder, kill=fs.Killed())
                with patches[point]:
                    try:
                        self.apply()
                    except fs.Killed:
                        pass
                note = self.next_boot("1.0.0")
                self.assertIsNotNone(note, "상태 파일은 읽힌다(깨진 반쪽 파일이 아니다)")
                self.assertIn(note.action, ("none", "not_applied"))


class SessionTest(FlowCase):
    switches = ("NET_UPDATE_CHECK", "UPDATE_APPLY")

    def session(self, **kwargs):
        options = dict(install_kind="velopack", current_version="1.0.0", keyring=fs.RING, adapter=fs.FakeAdapter(self.folder))
        options.update(kwargs)
        return update_flow.UpdateSession(self.ctx, **options)

    def test_the_whole_walk_follows_the_machine_and_ends_handed_off(self):
        session = self.session()
        self.assertEqual(session.state, "IDLE")
        session.check()
        self.assertEqual(session.state, "AVAILABLE")
        session.download()
        self.assertEqual(session.state, "READY")
        done = session.apply(confirmed=True)
        self.assertEqual((session.state, done.handed_off), ("HANDED_OFF", True))
        self.assertEqual(session.machine.history, ["IDLE", "CHECKING", "AVAILABLE", "DOWNLOADING", "VERIFYING", "READY", "BACKING_UP", "APPLYING", "HANDED_OFF"])

    def test_calls_out_of_order_do_nothing_and_raise(self):
        session = self.session()
        for call in (session.download, lambda: session.apply(confirmed=True)):
            before = len(self.server.requests)
            with self.assertRaises(machine.IllegalTransition):
                call()
            self.assertEqual((session.state, len(self.server.requests), self.staging_runs()), ("IDLE", before, []))
        session.check()
        with self.assertRaises(machine.IllegalTransition):
            session.apply(confirmed=True)                                # 내려받기 전에 적용
        with self.assertRaises(machine.IllegalTransition):
            session.check()                                              # 새 버전을 보고 있을 때 다시 확인 단추는 없다
        self.assertEqual(session.state, "AVAILABLE")
        self.assertEqual(self.backups_exist(), False)

    def backups_exist(self):
        root = self.ctx.workspace.backups_dir
        return root.is_dir() and any(root.iterdir())

    def test_failures_return_to_idle_or_check_failed_and_the_error_is_kept(self):
        session = self.session(current_version="2.0.0")
        with self.assertRaises(AppError):
            session.check()
        self.assertEqual((session.state, session.error.code), ("CHECK_FAILED", "UPDATE_DOWNGRADE_BLOCKED"))
        session.current_version = "1.0.0"
        session.check()                                                   # 실패한 뒤에는 다시 확인할 수 있다
        self.assertEqual(session.state, "AVAILABLE")
        self.server.routes.pop((fs.CDN_HOST, fs.cdn_path("releases.stable.json")))
        with self.assertRaises(AppError):
            session.download()
        self.assertEqual((session.state, session.error.code), ("IDLE", "UPDATE_DOWNLOAD_FAILED"))

    def test_a_partial_backup_returns_to_idle_without_handing_off(self):
        session = self.session()
        session.check()
        session.download()
        row = backup_flow.BackupRow("full-20261202-000000", "backup", "2026-12-02T00:00:00Z", "partial", 1, (), False)
        with mock.patch.object(backup_flow, "create_full_backup", return_value=backup_flow.BackupOutcome(row)):
            with self.assertRaises(AppError):
                session.apply(confirmed=True)
        self.assertEqual((session.state, session.error.code, session.adapter.calls), ("IDLE", "UPDATE_BACKUP_FAILED", []))

    def test_a_failed_hand_off_returns_to_idle_after_the_backup_was_done(self):
        session = self.session(adapter=fs.FakeAdapter(self.folder, fail=RuntimeError("x")))
        session.check()
        session.download()
        with self.assertRaises(AppError):
            session.apply(confirmed=True)
        self.assertEqual((session.state, session.error.code), ("IDLE", "UPDATE_APPLY_FAILED"))
        self.assertIn("APPLYING", session.machine.history)

    def test_cancel_is_possible_until_the_hand_off_starts(self):
        session = self.session()
        session.check()
        session.download()
        self.assertEqual(session.cancel(), "IDLE")
        with self.assertRaises(machine.IllegalTransition):
            session.cancel()

    def test_the_boot_note_moves_the_machine_and_a_healthy_report_cleans_up_and_keeps_the_installer(self):
        session = self.session()
        session.check()
        session.download()
        session.apply(confirmed=True)
        run = session.staged.folder
        with fs.switches_on("UPDATE_APPLY"):
            note = state.note_boot(version="1.0.1", folder=self.folder)
        fresh = self.session()
        self.assertEqual(fresh.on_boot(note), "POST_UPDATE_BOOT")
        self.assertEqual(fresh.report_health(True), "HEALTHY")
        after = self.state()
        self.assertEqual((after.pending, after.last_good, after.last_seq), (None, "1.0.1", self.release.dict["seq"]))
        kept = health.keep_dir(self.folder, "1.0.1")
        self.assertTrue((kept / "update-manifest.json").is_file() and (kept / "update-manifest.json.sig").is_file())
        self.assertTrue((kept / "releases.stable.json").is_file())
        self.assertFalse(run.exists())
        self.assertEqual(self.staging_runs(), [])

    def test_an_unhealthy_report_offers_the_recovery_and_changes_nothing_on_disk(self):
        session = self.session()
        session.check()
        session.download()
        session.apply(confirmed=True)
        with fs.switches_on("UPDATE_APPLY"):
            note = state.note_boot(version="1.0.1", folder=self.folder)
        fresh = self.session()
        fresh.on_boot(note)
        before = (self.folder / "state.json").read_bytes()
        self.assertEqual(fresh.report_health(False), "RECOVERY_OFFERED")
        self.assertEqual((self.folder / "state.json").read_bytes(), before, "사용자가 누르기 전에는 아무것도 바뀌지 않는다")

    def test_the_boot_hook_results_map_to_the_documented_states(self):
        for action, target in (("first_boot", "POST_UPDATE_BOOT"), ("recovery_offered", "RECOVERY_OFFERED"), ("not_applied", "IDLE"), ("none", "IDLE")):
            session = self.session()
            self.assertEqual(session.on_boot(state.BootNote(action, None)), target, action)
        self.assertEqual(self.session().on_boot(None), "IDLE")


class RecoveryTest(ApplyCase):
    """복구 — 새 판(1.0.1)이 두 번 켜지지 않은 뒤 사용자가 '복구' 를 누른 경우. 이전 판(1.0.0)의 검증된 설치 파일은 보관해 두었거나 다시 받는다."""

    def setUp(self):
        super().setUp()
        self.previous = fs.Release("1.0.0", min_version="0.9.0", issued="2026-06-01T03:00:00Z", expires="2026-11-28T03:00:00Z")      # 이미 만료된 이전 릴리스(복구는 만료를 보지 않는다)
        self.apply()
        with fs.switches_on("UPDATE_APPLY"):
            for _ in range(3):
                state.note_boot(version="1.0.1", folder=self.folder)
        self.pending = self.state().pending                                                       # 정상 표식 없이 세 번 켜진 뒤의 기록(횟수 2)
        self.restores = []
        original = backup_flow.restore_full_backup

        def record(ctx, name, *, confirmed, step=None):
            self.restores.append((name, confirmed))
        patcher = mock.patch.object(backup_flow, "restore_full_backup", record)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.original_restore = original
        self.adapter = fs.FakeAdapter(self.folder)

    def keep_previous(self):
        keep = health.keep_dir(self.folder, "1.0.0")
        keep.mkdir(parents=True)
        (keep / "update-manifest.json").write_bytes(self.previous.manifest_bytes)
        (keep / "update-manifest.json.sig").write_bytes(self.previous.signature)
        for name in ("ChanceBlogDesktopApp-1.0.0-stable-full.nupkg", "releases.stable.json"):
            (keep / name).write_bytes(self.previous.bodies[name])
        return keep

    def recover(self, **overrides):
        options = dict(adapter=self.adapter, confirmed=True, keyring=fs.RING)
        options.update(overrides)
        return update_flow.recover_update(self.ctx, **options)

    def test_with_a_kept_installer_the_recovery_is_offline_restores_the_data_and_installs_the_old_version(self):
        self.keep_previous()
        before = len(self.server.requests)
        outcome = self.recover()
        self.assertEqual(len(self.server.requests), before, "보관해 둔 이전 판이면 접속하지 않는다")
        self.assertEqual((outcome.restored_data, outcome.steps), (True, ("lock", "data", "installer", "apply", "record")))
        self.assertEqual(self.restores, [(self.pending.backup_name, True)])
        self.assertEqual(self.adapter.calls, [(["feed", "package"], "1.0.1", "1.0.0", True)], "낮은 판 설치는 복구 표시(recovery)와 함께")
        after = self.state()
        self.assertEqual((after.pending, after.notice, after.last_good), (None, "rolled_back", "1.0.0"))
        self.assertFalse((self.ctx.workspace.locks_dir / "update.lock").exists())

    def test_without_a_kept_installer_the_previous_release_is_downloaded_by_its_tag_and_verified_the_same_way(self):
        self.previous.install(self.server, latest=False)
        outcome = self.recover()
        self.assertEqual(outcome.steps[-1], "record")
        tags = {request[2].split("/")[5] for request in self.server.requests if "/download/" in request[2] and request[0] == "github.com"}
        self.assertIn("v1.0.0", tags)
        self.assertEqual(self.adapter.calls[0][2], "1.0.0")

    def test_a_tampered_kept_installer_falls_back_to_the_download_and_a_missing_network_fails_at_the_installer_step(self):
        keep = self.keep_previous()
        path = keep / "releases.stable.json"
        path.write_bytes(path.read_bytes()[:-1] + b"X")
        with self.assertRaises(recovery.RollbackFailure) as caught:
            with mock.patch.object(update_flow.capabilities, "NET_UPDATE_CHECK", False):
                self.recover()
        self.assertEqual((caught.exception.step, caught.exception.cause_code), ("installer", "NETWORK_DISABLED"))
        self.assertEqual(self.adapter.calls, [])
        self.previous.install(self.server, latest=False)
        self.assertEqual(self.recover().steps[-1], "record")

    def test_the_previous_release_must_be_exactly_the_version_before_the_update(self):
        wrong = fs.Release("0.9.0", min_version="0.8.0")
        wrong.tag = "v1.0.0"
        wrong.install(self.server, latest=False)
        with self.assertRaises(recovery.RollbackFailure) as caught:
            self.recover()
        self.assertEqual((caught.exception.step, caught.exception.cause_code), ("installer", "UPDATE_DOWNGRADE_BLOCKED"))

    def test_a_forged_signature_or_a_stranger_key_is_refused_even_in_recovery(self):
        stranger = fs.Release("1.0.0", seed=us.seed_for("stranger"), min_version="0.9.0")
        stranger.install(self.server, latest=False)
        with self.assertRaises(recovery.RollbackFailure) as caught:
            self.recover()
        self.assertEqual((caught.exception.step, caught.exception.cause_code), ("installer", "UPDATE_SIGNATURE_INVALID"))

    def test_an_adapter_failure_stops_there_records_the_notice_and_keeps_the_marker_for_a_retry(self):
        self.keep_previous()
        self.adapter = fs.FakeAdapter(self.folder, fail=AppError("UPDATE_APPLY_FAILED", detail="exit:3"))
        with self.assertRaises(recovery.RollbackFailure) as caught:
            self.recover()
        self.assertEqual((caught.exception.step, caught.exception.cause_code, caught.exception.code), ("apply", "UPDATE_APPLY_FAILED", "UPDATE_ROLLBACK_FAILED"))
        after = self.state()
        self.assertEqual((after.pending, after.notice), (self.pending, "rollback_failed"))
        self.assertEqual(len(self.restores), 1, "데이터 복원은 이미 끝났다")

    def test_the_data_step_failing_stops_before_any_installer_work(self):
        self.keep_previous()
        with mock.patch.object(backup_flow, "restore_full_backup", side_effect=AppError("FULL_BACKUP_INVALID", {"파일": "x"})):
            with self.assertRaises(recovery.RollbackFailure) as caught:
                self.recover()
        self.assertEqual((caught.exception.step, caught.exception.cause_code), ("data", "FULL_BACKUP_INVALID"))
        self.assertEqual(self.adapter.calls, [])

    def test_confirmation_a_pending_record_and_the_switch_are_required(self):
        self.keep_previous()
        self.assertEqual(code_of(self.recover, confirmed=False), "CONFIRMATION_REQUIRED")
        self.assertEqual((self.restores, self.adapter.calls), ([], []))
        health.mark_healthy(self.folder)
        with self.assertRaises(recovery.RollbackFailure):
            self.recover()
        with mock.patch.object(update_flow.capabilities, "UPDATE_APPLY", False):
            self.assertEqual(code_of(self.recover), "UPDATE_DISABLED")

    def test_a_held_lock_refuses_the_recovery_with_the_in_progress_code_and_starts_nothing(self):
        self.keep_previous()
        lock = update_flow._UpdateLock(self.ctx.workspace.locks_dir, update_flow.LOCK_NAME, now=self.ctx.now, host="")
        lock.acquire()
        try:
            self.assertEqual(code_of(self.recover), "UPDATE_IN_PROGRESS")
        finally:
            lock.release()
        self.assertEqual((self.restores, self.adapter.calls), ([], []))

    def test_the_session_drives_the_recovery_through_the_machine(self):
        self.keep_previous()
        session = update_flow.UpdateSession(self.ctx, install_kind="velopack", current_version="1.0.1", keyring=fs.RING, adapter=self.adapter)
        with fs.switches_on("UPDATE_APPLY"):
            note = state.note_boot(version="1.0.1", folder=self.folder)
        self.assertEqual(note.action, "recovery_offered")
        self.assertEqual(session.on_boot(note), "RECOVERY_OFFERED")
        session.recover(confirmed=True)
        self.assertEqual(session.state, "ROLLED_BACK")
        self.assertEqual(session.machine.send("ack"), "IDLE")

    def test_a_failed_session_recovery_ends_in_rollback_failed(self):
        session = update_flow.UpdateSession(self.ctx, install_kind="velopack", current_version="1.0.1", keyring=fs.RING, adapter=self.adapter)
        session.machine = machine.Machine("RECOVERY_OFFERED")
        with self.assertRaises(recovery.RollbackFailure):
            session.recover(confirmed=True)                                # 보관한 것도 없고 서버에도 이전 릴리스가 없다
        self.assertEqual((session.state, session.error.code), ("ROLLBACK_FAILED", "UPDATE_ROLLBACK_FAILED"))


class EntryPointShapeTest(unittest.TestCase):
    def tree(self):
        return ast.parse((SRC / "service" / "update_flow.py").read_text(encoding="utf-8"))

    def first(self, function):
        body = [node for node in function.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        return ast.unparse(body[0])

    def test_every_public_entry_starts_with_its_gate(self):
        tree = self.tree()
        top = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name, gate in (("check_for_update", "capabilities.require_net('update_check', '업데이트 확인')"), ("download_update", "capabilities.require_net('update_check', '업데이트 내려받기')"),
                           ("apply_update", "capabilities.require_update_apply('업데이트 설치')"), ("recover_update", "capabilities.require_update_apply('업데이트 복구')"),
                           ("check_from_folder", "capabilities.require_update_apply('폴더에서 업데이트')"), ("stage_update_from_folder", "capabilities.require_update_apply('업데이트 준비')")):
            self.assertEqual(self.first(top[name]), gate, name)
        session = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "UpdateSession")
        methods = {node.name: node for node in session.body if isinstance(node, ast.FunctionDef)}
        for name, gate in (("check", "capabilities.require_net('update_check', '업데이트 확인')"), ("download", "capabilities.require_net('update_check', '업데이트 내려받기')"),
                           ("apply", "capabilities.require_update_apply('업데이트 설치')"), ("recover", "capabilities.require_update_apply('업데이트 복구')"),
                           ("report_health", "capabilities.require_update_apply('업데이트 점검')"), ("check_folder", "capabilities.require_update_apply('폴더에서 업데이트')"),
                           ("prepare_from_folder", "capabilities.require_update_apply('업데이트 준비')")):
            self.assertEqual(self.first(methods[name]), gate, name)

    def test_the_service_imports_nothing_that_connects_or_launches(self):
        tree = self.tree()
        names = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
        self.assertFalse(names & {"http", "ssl", "socket", "subprocess", "urllib", "ctypes", "webbrowser", "requests"}, names)

    def test_the_error_codes_the_flow_can_raise_all_exist_in_the_catalog(self):
        from chanceblog_desktop.errors import CATALOG
        text = (SRC / "service" / "update_flow.py").read_text(encoding="utf-8")
        import re
        for code in set(re.findall(r'"(UPDATE_[A-Z_]+|DISK_FULL|NETWORK_DISABLED)"', text)):
            self.assertIn(code, CATALOG, code)


if __name__ == "__main__":
    unittest.main()
