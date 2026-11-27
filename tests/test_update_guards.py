"""`service/update_flow.py` 의 R3·R4 고침 시험(독립 검증 S 의 R3·R4, 'U-5 배선 전에 고칠 것' — v1update4 U-4, 결정 D-850 이상).

  R4) `download_update` 가 **폴더에서 확인한 결과**(`source != "online"`, 후보 채널 `rc` 포함)를 거절한다 — 인터넷 요청·연결·임시 폴더 0. 예전에는 거절이 `UpdateSession.download` 에만 있어 이 공개 함수를 직접 부르면 요청이 나갔다.
  R3) `apply_update` 가 **받은 파일(`staged`)과 확인 결과(`check`)의 일치**를 적용 직전에(백업·잠금·`pending` 이전에) 다시 확인한다: 확인 결과가 새 판이고 바꿀 수 있는 설치 종류이며, 두 매니페스트가 똑같고(버전·`seq`·역할·크기·해시·`digest`),
      확인 결과가 든 서명된 바이트가 그 매니페스트의 것이고, 새 버전이 지금 버전보다 높고, 필요한 역할이 모두 있다. 어긋나면 어댑터·백업·표식·시퀀스 모두 0 으로 거절한다. 예전에는 공개 함수 `source.download_files` 로 받은 낮은 판의 서명된 파일을
      높은 판의 확인 결과와 함께 넘기면 어댑터에 낮은 판이 넘어갔다(검증자 증거 S9).
시험은 가짜 릴리스 서버(진짜 접속 틀 위, 접속 0)와 가짜 어댑터만 쓴다.

재작업 1(독립 검증 S R3 의 완전성·Q R1):
  R3 완전성) 받은 파일의 경로(폴더·이름)와 값 모양 어긋남(폴더가 None·숫자, `files['setup']` 이 None·숫자·바이트·널 문자, 다른 폴더·다른 이름, `CheckResult.manifest_bytes` 가 글·숫자)도 **백업을 만들기 전에** 같은 거절 코드로 막는다
      — 예전에는 백업과 표식을 남긴 뒤에야 어댑터에서 걸리거나 `verify_staged`·`hashlib` 에서 생 예외가 샜다.
  Q R1) Velopack 이 사라져 흐름이 받는 파일이 하나가 된 뒤에도 받기·복사·재해시가 파일마다 돌고(둘째·셋째 파일까지) 큰 파일을 덩어리마다 끝까지 해시한다 — `source.CHUNK` 를 줄여 작은 파일로 여러 덩어리를 돈다.
"""
import dataclasses
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import test_update_flow as tf  # noqa: E402
import update_flow_support as fs  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow, update_flow  # noqa: E402
from chanceblog_desktop.update import apply, source, state  # noqa: E402
from chanceblog_desktop.update import manifest as manifest_module  # noqa: E402

SETUP_101 = "ChanceBlogDesktop-1.0.1-Setup.exe"


def reason_of(call, *args, **kwargs):
    """(오류 코드, 이유 이름) — 오류가 없으면 (None, None)."""
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code, error.detail
    return None, None


class DownloadRefusesFolderChecksTest(tf.FlowCase):
    """R4 — 인터넷으로 받는 공개 함수가 폴더에서 확인한 결과를 직접 거절한다."""
    switches = ("NET_UPDATE_CHECK",)

    def test_a_check_result_from_a_folder_never_causes_an_internet_request(self):
        online = self.check()
        for source_name in ("folder", "usb", "", "Online", "ONLINE", None):
            with self.subTest(source=source_name):
                claimed = dataclasses.replace(online, source=source_name, folder="C:/picked" if source_name else "")
                requests, dials = len(self.server.requests), len(self.harness.dials)
                self.assertEqual(reason_of(update_flow.download_update, self.ctx, claimed), ("UPDATE_CHECK_FAILED", "download:folder_source"))
                self.assertEqual((len(self.server.requests), len(self.harness.dials), self.staging_runs()), (requests, dials, []), "요청 0·연결 0·임시 폴더 0")

    def test_the_release_candidate_checked_from_a_folder_is_refused_too_with_no_request(self):
        candidate = fs.Release("1.0.1-rc.1", channel="rc")
        verified = manifest_module.read_and_verify(candidate.manifest_bytes, candidate.signature, keyring=fs.RING, channels=manifest_module.CHANNELS_OFFLINE)
        claimed = update_flow.CheckResult("AVAILABLE", verified, True, "1.0.0", candidate.manifest_bytes, candidate.signature, "folder", "C:/picked")
        requests = len(self.server.requests)
        self.assertEqual(reason_of(update_flow.download_update, self.ctx, claimed), ("UPDATE_CHECK_FAILED", "download:folder_source"))
        self.assertEqual((len(self.server.requests), self.staging_runs()), (requests, []))

    def test_an_online_check_still_downloads_and_the_session_refusal_is_unchanged(self):
        online = self.check()
        self.assertEqual(online.source, "online")
        staged = update_flow.download_update(self.ctx, online)
        self.assertEqual(sorted(staged.files), ["setup"])
        session = update_flow.UpdateSession(self.ctx, install_kind="inno", current_version="1.0.0", keyring=fs.RING)
        session.check()
        session.check_result = dataclasses.replace(session.check_result, source="folder", folder="C:/picked")
        with self.assertRaises(AppError) as caught:
            session.download()
        self.assertEqual((caught.exception.code, caught.exception.detail, session.state), ("UPDATE_CHECK_FAILED", "download:folder_source", "AVAILABLE"), "세션의 옛 거절은 그대로다(상태 기계도 움직이지 않는다)")

    def test_the_refusal_comes_after_the_switch_gate_and_before_everything_else(self):
        online = self.check()
        claimed = dataclasses.replace(online, source="folder", status="UP_TO_DATE", apply_possible=False)
        self.assertEqual(reason_of(update_flow.download_update, self.ctx, claimed), ("UPDATE_CHECK_FAILED", "download:folder_source"), "출처 거절이 상태·설치 종류 거절보다 먼저다")
        with mock.patch.object(update_flow.capabilities, "NET_UPDATE_CHECK", False):
            self.assertEqual(reason_of(update_flow.download_update, self.ctx, claimed)[0], "NETWORK_DISABLED", "관문이 맨 앞이다")


class ApplyRefusesMismatchTest(tf.ApplyCase):
    """R3 — 받은 파일과 확인 결과가 어긋나면 백업·잠금·`pending` 이전에 거절한다."""

    def setUp(self):
        super().setUp()
        self.real_backup = backup_flow.create_full_backup
        patcher = mock.patch.object(backup_flow, "create_full_backup", side_effect=AssertionError("거절은 백업을 만들기 전에 끝나야 한다"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def refused(self, label, reason, **overrides):
        check = overrides.pop("check", self.result)
        staged = overrides.pop("staged", self.staged)
        before = self.state()
        self.assertEqual(reason_of(self.apply_with, check, staged, **overrides), reason, label)
        self.assertEqual((self.adapter.calls, self.state()), ([], before), f"{label}: 어댑터·표식·시퀀스 모두 그대로")
        self.assertFalse((self.ctx.workspace.locks_dir / "update.lock").exists(), f"{label}: 잠금도 잡지 않았다")

    def apply_with(self, check, staged, **kwargs):
        options = dict(adapter=self.adapter, confirmed=True)
        options.update(kwargs)
        return update_flow.apply_update(self.ctx, check, staged, **options)

    def lower_release_files(self):
        """공개 함수로 받은 **낮은 판**(0.9.0)의 서명된 파일 — 검증자 증거 S9 의 재현."""
        low = fs.Release("0.9.0", min_version="0.8.0")
        low.install(self.server, latest=False)
        verified = manifest_module.read_and_verify(low.manifest_bytes, low.signature, keyring=fs.RING)
        client = update_flow._client("1.0.0")
        return source.download_files(client, verified, low.manifest_bytes, low.signature, self.folder, roles=("setup",))

    def test_the_signed_files_of_a_lower_release_are_not_handed_over_with_the_check_of_a_higher_one(self):
        staged = self.lower_release_files()
        self.assertEqual(staged.manifest.version, "0.9.0")
        self.refused("낮은 판의 파일", ("UPDATE_SIGNATURE_INVALID", "apply:manifest"), staged=staged)

    def test_a_manifest_that_differs_in_any_one_field_is_refused(self):
        manifest = self.staged.manifest
        entry = manifest.file("setup")
        changes = (("seq", dict(seq=manifest.seq + 1)), ("버전", dict(version="1.0.2")), ("해시가 다른 역할", dict(files=tuple(dataclasses.replace(item, sha256="0" * 64) if item.role == "setup" else item for item in manifest.files))),
                   ("크기가 다른 역할", dict(files=tuple(dataclasses.replace(item, size=entry.size + 1) if item.role == "setup" else item for item in manifest.files))),
                   ("설치 종류", dict(installer_kind="velopack")), ("채널", dict(channel="rc")), ("digest", dict(digest="f" * 64)), ("서명 키", dict(key_id="ffffffffffffffff")))
        for label, changed in changes:
            with self.subTest(label=label):
                altered = dataclasses.replace(manifest, **changed)
                self.refused(label, ("UPDATE_SIGNATURE_INVALID", "apply:manifest"), staged=dataclasses.replace(self.staged, manifest=altered))
                self.assertEqual(self.backups(), [])

    def test_the_check_must_be_a_new_version_the_app_can_replace(self):
        self.refused("같은 버전(최신)", ("UPDATE_CHECK_FAILED", "apply:not_available"), check=dataclasses.replace(self.result, status="UP_TO_DATE"))
        self.refused("모르는 상태", ("UPDATE_CHECK_FAILED", "apply:not_available"), check=dataclasses.replace(self.result, status=""))
        self.refused("바꿀 수 없는 설치 종류(휴대용 등)", ("UPDATE_NOT_INSTALLED_KIND", "apply"), check=dataclasses.replace(self.result, apply_possible=False))

    def test_the_signed_bytes_carried_by_the_check_must_be_the_ones_of_the_manifest(self):
        self.refused("서명된 바이트 없음", ("UPDATE_SIGNATURE_INVALID", "apply:signed_data"), check=dataclasses.replace(self.result, manifest_bytes=b""))
        self.refused("다른 바이트", ("UPDATE_SIGNATURE_INVALID", "apply:signed_data"), check=dataclasses.replace(self.result, manifest_bytes=self.result.manifest_bytes + b" "))
        other = fs.Release("1.0.2")
        self.refused("다른 릴리스의 바이트", ("UPDATE_SIGNATURE_INVALID", "apply:signed_data"), check=dataclasses.replace(self.result, manifest_bytes=other.manifest_bytes))

    def test_the_new_version_must_be_higher_than_the_version_at_check_time(self):
        for current in ("1.0.1", "1.0.2", "2.0.0"):
            self.refused(f"지금 버전 {current}", ("UPDATE_DOWNGRADE_BLOCKED", "apply:version"), check=dataclasses.replace(self.result, current_version=current))
        for bad in ("", "x", "1.0", None, 5):
            self.refused(f"읽을 수 없는 지금 버전 {bad!r}", ("UPDATE_CHECK_FAILED", "apply:current_version"), check=dataclasses.replace(self.result, current_version=bad))

    def test_a_missing_role_in_the_files_or_in_the_manifest_is_refused(self):
        self.refused("받은 파일에 역할이 없다", ("UPDATE_SIGNATURE_INVALID", "apply:role:setup"), staged=dataclasses.replace(self.staged, files={}))
        thin = dataclasses.replace(self.result.manifest, files=tuple(item for item in self.result.manifest.files if item.role != "setup"))
        self.refused("매니페스트에 역할이 없다", ("UPDATE_MANIFEST_INVALID", "manifest:missing_role"), check=dataclasses.replace(self.result, manifest=thin), staged=dataclasses.replace(self.staged, manifest=thin))

    def test_a_value_that_is_not_a_staged_update_closes_to_a_refusal_without_an_exception(self):
        for junk in (None, object(), {}, "x", 5, mock.Mock()):
            with self.subTest(junk=type(junk).__name__):
                self.refused("엉뚱한 값", ("UPDATE_SIGNATURE_INVALID", "apply:staged"), staged=junk)
        self.refused("files 가 사전이 아님", ("UPDATE_SIGNATURE_INVALID", "apply:staged"), staged=dataclasses.replace(self.staged, files=["setup"]))
        for junk in (None, object(), {}, "x", 5, mock.Mock()):
            with self.subTest(check=type(junk).__name__):
                self.refused("엉뚱한 확인 결과", ("UPDATE_CHECK_FAILED", "apply:check"), check=junk)
        self.refused("확인 결과의 매니페스트 칸이 엉뚱함", ("UPDATE_CHECK_FAILED", "apply:check"), check=dataclasses.replace(self.result, manifest=None))

    def test_a_received_file_with_a_wrong_path_or_value_shape_is_refused_before_the_backup_by_the_adapters_own_reasons(self):
        """독립 검증 S R3 — 받은 파일의 경로(폴더·이름)와 값 모양 어긋남은 예전에 백업과 표식을 남긴 뒤에야 어댑터에서 걸리거나(`staged_invalid`·`setup_missing`·`setup_path`) `verify_staged` 에서 생 예외로 샜다(`files['setup']` 이 5·바이트·널 문자).
        이제 흐름이 같은 함수(`apply.setup_for`)를 백업 앞에서 불러 **같은 거절 코드·이유**로 막는다 — 어댑터·백업·표식·시퀀스·잠금 0."""
        path = self.staged.files["setup"]
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / path.name).write_bytes(path.read_bytes())
        path.with_name("renamed-copy.exe").write_bytes(path.read_bytes())
        files = self.staged.files
        shapes = (
            ("받은 폴더가 None", dataclasses.replace(self.staged, folder=None), "staged_invalid"),
            ("받은 폴더가 숫자", dataclasses.replace(self.staged, folder=5), "staged_invalid"),
            ("받은 폴더가 바이트", dataclasses.replace(self.staged, folder=b"folder"), "staged_invalid"),
            ("Setup 값이 None", dataclasses.replace(self.staged, files={"setup": None}), "setup_missing"),
            ("Setup 값이 숫자", dataclasses.replace(self.staged, files={"setup": 5}), "setup_path"),
            ("Setup 값이 바이트", dataclasses.replace(self.staged, files={"setup": b"x"}), "setup_path"),
            ("Setup 값이 목록", dataclasses.replace(self.staged, files={"setup": [str(path)]}), "setup_path"),
            ("Setup 값이 빈 글", dataclasses.replace(self.staged, files={"setup": ""}), "setup_path"),
            ("Setup 값이 널 문자", dataclasses.replace(self.staged, files={"setup": "a" + chr(0) + "b"}), "setup_path"),
            ("Setup 경로 끝에 널 문자", dataclasses.replace(self.staged, files={"setup": str(path) + chr(0)}), "setup_path"),
            ("다른 폴더의 같은 이름·같은 바이트", dataclasses.replace(self.staged, files={"setup": elsewhere / path.name}), "setup_path"),
            ("같은 폴더의 다른 이름·같은 바이트", dataclasses.replace(self.staged, files={"setup": path.with_name("renamed-copy.exe")}), "setup_path"),
            ("받은 폴더가 네트워크(UNC) 꼴", dataclasses.replace(self.staged, folder="//fileserver/share/run", files={"setup": "//fileserver/share/run/" + path.name}), "path_unc"),
            ("받은 폴더가 역슬래시 UNC 꼴", dataclasses.replace(self.staged, folder=chr(92) * 2 + "fileserver" + chr(92) + "share" + chr(92) + "run", files={"setup": chr(92) * 2 + "fileserver" + chr(92) + "share" + chr(92) + "run/" + path.name}), "path_unc"),
            ("다른 역할의 값이 숫자", dataclasses.replace(self.staged, files={**files, "package": 5}), "staged_invalid"),
            ("다른 역할의 값이 널 문자", dataclasses.replace(self.staged, files={**files, "feed": "x" + chr(0)}), "staged_invalid"),
        )
        trap = mock.patch.object(source, "verify_staged", side_effect=AssertionError("모양이 어긋난 값은 재해시(파일 시스템)까지 가면 안 된다 — 네트워크 꼴 경로는 네트워크에 닿는다"))
        for label, shape, reason in shapes:
            with self.subTest(label=label), trap:
                self.refused(label, ("UPDATE_APPLY_FAILED", reason), staged=shape)
                self.assertEqual(self.backups(), [], f"{label}: 백업 폴더가 생기지 않았다")
                self.assertEqual(reason_of(apply.adapter_for("inno").apply, shape, from_version="1.0.0", to_version="1.0.1"), ("UPDATE_APPLY_FAILED", reason), f"{label}: 같은 값을 어댑터에 직접 넣으면 나중에 같은 거절이 난다 — 흐름이 그 거절을 앞당겼다")

    def test_signed_bytes_that_are_not_bytes_are_refused_without_a_raw_exception(self):
        """독립 검증 S R3 — `CheckResult.manifest_bytes` 가 글·숫자·목록이면 예전에는 `hashlib.sha256` 에서 생 `TypeError` 가 새어 나갔다(데이터 폴더는 그대로였다). 이제 바이트가 아닌 값은 예외 대신 거절한다."""
        text = self.result.manifest_bytes.decode("utf-8")
        for label, junk in (("같은 내용의 글", text), ("숫자", 5), ("목록", [b"a"]), ("None", None), ("object", object()), ("사전", {"a": 1})):
            with self.subTest(label=label):
                self.refused(label, ("UPDATE_SIGNATURE_INVALID", "apply:signed_data"), check=dataclasses.replace(self.result, manifest_bytes=junk))
                self.assertEqual(self.backups(), [])

    def test_the_matching_pair_still_goes_through_and_the_order_is_unchanged(self):
        with mock.patch.object(backup_flow, "create_full_backup", self.real_backup):
            done = self.apply_with(self.result, self.staged)
        self.assertEqual((done.handed_off, done.to_version, self.adapter.calls), (True, "1.0.1", [(["setup"], "1.0.0", "1.0.1", False)]))
        after = self.state()
        self.assertEqual((after.pending.to_version, after.last_seq), ("1.0.1", self.release.dict["seq"]))

    def test_the_checks_come_after_the_confirmation_and_the_gate_and_before_the_lock(self):
        mismatched = dataclasses.replace(self.result, status="UP_TO_DATE")
        self.assertEqual(reason_of(self.apply_with, mismatched, self.staged, confirmed=False)[0], "CONFIRMATION_REQUIRED", "확인창 확인이 먼저다")
        with mock.patch.object(update_flow.capabilities, "UPDATE_APPLY", False):
            self.assertEqual(reason_of(self.apply_with, mismatched, self.staged)[0], "UPDATE_DISABLED", "스위치 관문이 맨 앞이다")
        lock = update_flow._UpdateLock(self.ctx.workspace.locks_dir, update_flow.LOCK_NAME, now=self.ctx.now, host="")
        lock.acquire()
        try:
            self.assertEqual(reason_of(self.apply_with, mismatched, self.staged)[0], "UPDATE_CHECK_FAILED", "잠금이 잡혀 있어도 어긋남 거절은 잠금보다 먼저다")
        finally:
            lock.release()


class EveryFileAndEveryChunkTest(tf.FlowCase):
    """독립 검증 Q R1(변이 Q20·Q65·Q66·Q67) — Velopack 이 사라져 흐름 시험이 받는 파일이 하나(3000바이트)가 된 뒤 '파일마다 도는 반복'과 '큰 파일의 덩어리 반복'을 도는 시험이 하나도 남지 않았다.
    가짜 릴리스는 Setup·꾸러미·목록 셋을 올려 두므로 그 셋을 모두 골라 받기·복사·재해시에 통과시키고, 덩어리를 64바이트로 줄여(`source.CHUNK`) 작은 파일로 여러 덩어리를 돈다."""
    ALL = ("setup", "package", "feed")

    def picked_folder(self):
        folder = self.tmp / "picked"
        folder.mkdir()
        (folder / "update-manifest.json").write_bytes(self.release.manifest_bytes)
        (folder / "update-manifest.json.sig").write_bytes(self.release.signature)
        for name, body in self.release.bodies.items():
            (folder / name).write_bytes(body)
        return folder

    def flip_last_byte(self, path):
        original = Path(path).read_bytes()
        Path(path).write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        return original

    def test_downloading_several_files_gets_every_one_and_the_last_second_hash_reads_every_one_to_the_end(self):
        result = self.check()
        client = update_flow._client("1.0.0")
        with mock.patch.object(source, "CHUNK", 64):
            staged = source.download_files(client, result.manifest, result.manifest_bytes, result.signature_bytes, self.folder, roles=self.ALL)
            self.assertEqual(sorted(staged.files), sorted(self.ALL), "고른 파일이 모두 받아졌다")
            for role, path in staged.files.items():
                entry = result.manifest.file(role)
                self.assertEqual((path.name, path.read_bytes()), (entry.name, self.release.bodies[entry.name]), role)
            self.assertTrue(source.verify_staged(staged), "작은 덩어리(64바이트)로 여러 번 읽어도 모든 파일이 서명된 값과 같다")
            for role in self.ALL:
                original = self.flip_last_byte(staged.files[role])                  # 파일마다 마지막 바이트 하나만 — 뒤 파일과 마지막 덩어리까지 읽어야 걸린다
                with self.subTest(role=role):
                    with self.assertRaises(AppError) as caught:
                        source.verify_staged(staged)
                    self.assertEqual((caught.exception.code, caught.exception.detail), ("UPDATE_SIGNATURE_INVALID", f"restage:{role}"))
                staged.files[role].write_bytes(original)
            self.assertTrue(source.verify_staged(staged), "되돌리면 다시 같다")

    def test_copying_from_a_folder_copies_and_checks_every_chosen_file_in_every_chunk(self):
        result = self.check()
        folder = self.picked_folder()
        with mock.patch.object(source, "CHUNK", 64):
            staged = source.stage_from_folder(folder, result.manifest, result.manifest_bytes, result.signature_bytes, self.folder, roles=self.ALL)
            self.assertEqual(sorted(staged.files), sorted(self.ALL), "고른 파일이 모두 복사됐다")
            for role, path in staged.files.items():
                entry = result.manifest.file(role)
                self.assertEqual((path.name, path.read_bytes()), (entry.name, self.release.bodies[entry.name]), role)
            self.assertTrue(source.verify_staged(staged))
            runs = len(self.staging_runs())
            for role in self.ALL:
                entry = result.manifest.file(role)
                original = self.flip_last_byte(folder / entry.name)                 # 크기는 같고 마지막 바이트만 다르다
                with self.subTest(role=role):
                    with self.assertRaises(AppError) as caught:
                        source.stage_from_folder(folder, result.manifest, result.manifest_bytes, result.signature_bytes, self.folder, roles=self.ALL)
                    self.assertEqual((caught.exception.code, caught.exception.detail), ("UPDATE_SIGNATURE_INVALID", f"folder:{role}:mismatch"))
                    self.assertEqual(len(self.staging_runs()), runs, "틀리면 그 폴더를 지운다 — 새 임시 폴더가 남지 않았다")
                (folder / entry.name).write_bytes(original)


if __name__ == "__main__":
    unittest.main()
