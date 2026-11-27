"""`scripts/update_manifest.py`(릴리스 매니페스트 도구 — `verify-candidate`·`build`, RELEASE 설계서 3-3 서명 잡 단계 4·5, V1REL12·R-1) 시험.

지키는 것:
  1) `verify-candidate`: 자산 파일을 **다시 해시해** `release_candidate.json` 과 대조한다 — 한 바이트 바꾼 파일·크기가 다른 파일·알 수 없는 파일·빠진 파일·이름 오타·링크·깨진 기록·`VERSION` 과 다른 버전·크기 상한을 거절한다.
  2) `build`: 만든 매니페스트를 **앱의 엄격 읽기**(`read_structure`·`validate_fields`)가 받아들인다 — 칸 열네 개·`seq` = 발행 시각 숫자·만료 = 발행 + 180일·`min_version`·`key_id`·`commit`·설치 도구·`notes.summary`(변경 이력 `### 요약` 그대로)·
     파일 표(설치 파일·휴대용 압축 파일의 실제 이름·크기·해시). 같은 입력은 같은 바이트이고(시각은 주입) 정식은 온라인·후보(`rc`)는 오프라인 채널에서만 읽힌다.
  3) 사슬이 틀린 후보(해시 불일치·변경 이력 맨 위 절 불일치·노트 모양)로는 매니페스트를 만들지 않고, 앱이 거절할 값은 쓰지 않는다. `min_version` 은 꼭 주고 버전 이하여야 한다.
  4) 끝에서 끝: 모으기 → 후보 검증 → 매니페스트 → 서명 → 해시 목록 → 서명 뒤 사슬 확인 → 앱의 검증기가 받아들인다. 서명한 매니페스트의 바이트를 하나씩 바꾸면 앱이 거절한다.
  5) 재작업 1(안전 검증 S): 발행 시각은 허용 범위(2020년 이후·2100년 전·시계보다 24시간 넘게 앞서지 않음) 안이어야 하고 밖이거나 시계를 쓸 수 없으면 고정 문장·종료 코드 2·파일 없음(S-2) —
     그래서 고정 발행 시각을 쓰는 시험은 시계도 함께 고정한다(`clock_for`). 매니페스트 파일은 `O_EXCL` 로 만든다(참고 N-1).
네트워크·실제 시크릿 없이 돈다(키는 모두 시험 안의 임시 값).
"""
import ast
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import release_tools_support as rts
import update_support as us

from chanceblog_desktop.update import keys, manifest

import release_chain as rc
import update_manifest as um
import update_sign

ROOT = rts.ROOT
SCRIPT = ROOT / "scripts" / "update_manifest.py"
STABLE, RC = "1.0.0", "1.0.0-rc.1"
ISSUED = "2026-12-01T03:00:00Z"
KEY_ID = "0123456789abcdef"
run_tool = rts.Capture(um.main)
FIELD_ORDER = ["schema", "product", "channel", "version", "tag", "seq", "issued_utc", "expires_utc", "min_version", "key_id", "commit", "installer", "notes", "files"]


def clock_for(issued, hours=1):
    """`--issued-utc` 로 준 시각의 `hours` 시간 뒤를 '지금' 으로 돌려주는 시계. 발행 시각은 지금 시계 기준 범위 안(미래는 24시간 이내)이어야 하므로(재작업 1·S-2)
    고정 시각을 쓰는 시험은 시계도 함께 고정한다 — 진짜 시계에 기대면 날짜가 지나면서 결과가 바뀐다. 읽을 수 없는 시각이면 고정한 날을 쓴다."""
    moment = manifest.parse_time(issued) if isinstance(issued, str) else None
    stamp = (moment or datetime(2026, 12, 2, 4, 0, 0, tzinfo=timezone.utc)) + timedelta(hours=hours)
    return lambda: stamp


class World:
    """가짜 후보 폴더(`release/`)와 `VERSION`·`CHANGELOG.md` 파일이 든 임시 폴더."""

    def __init__(self, case, version=STABLE, **notes):
        holder = rts.temp_dir()
        case.addCleanup(holder.cleanup)
        self.base = Path(holder.name)
        self.version = version
        self.release = rts.fake_release(self.base / "release", version)
        rts.write(self.base / "VERSION", version + "\n")
        self.changelog_text = rts.changelog_text(version, **notes)
        rts.write(self.base / "CHANGELOG.md", self.changelog_text)

    @property
    def common(self):
        return ["--dir", str(self.release), "--version-file", str(self.base / "VERSION")]

    def build_args(self, *extra, min_version="0.0.0", issued=ISSUED, key_id=KEY_ID):
        args = ["build", *self.common, "--changelog", str(self.base / "CHANGELOG.md"), "--min-version", min_version]
        if issued is not None:
            args += ["--issued-utc", issued]
        if key_id is not None:
            args += ["--key-id", key_id]
        return args + list(extra)

    def build(self, *extra, now=None, **kwargs):
        return run_tool(self.build_args(*extra, **kwargs), now=now if now is not None else clock_for(kwargs.get("issued", ISSUED)))

    def manifest_bytes(self):
        return (self.release / "update-manifest.json").read_bytes()


def app_read(data, channels=manifest.CHANNELS_OFFLINE):
    return manifest.validate_fields(manifest.read_structure(data), hashlib.sha256(data).hexdigest(), channels=channels)


class VerifyCandidateTest(unittest.TestCase):
    def verify(self, world):
        return run_tool(["verify-candidate", *world.common])

    def test_a_consistent_folder_is_confirmed_and_every_asset_is_listed_with_its_hash(self):
        world = World(self)
        code, out, err = self.verify(world)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith("후보가 맞다: 버전 1.0.0 · 태그 v1.0.0 · 커밋 0123456 · 자산 5개를 다시 해시해 기록과 대조했다\n"))
        for name in rc.asset_names(STABLE).values():
            digest = hashlib.sha256((world.release / name).read_bytes()).hexdigest()
            self.assertIn(f"- {name} {(world.release / name).stat().st_size}바이트 {digest}\n", out)

    def test_a_changed_byte_a_changed_size_an_unknown_file_a_missing_file_and_a_typo_are_each_refused(self):
        def flip(world):
            path = world.release / rc.setup_name(STABLE)
            data = bytearray(path.read_bytes())
            data[10] ^= 1
            path.write_bytes(bytes(data))

        def grow(world):
            with open(world.release / rc.portable_name(STABLE), "ab") as handle:
                handle.write(b"x")

        def stray(world):
            rts.write(world.release / "stray.txt", b"x")

        def missing(world):
            (world.release / "PACKAGE_INFO.md").unlink()

        def typo(world):
            (world.release / rc.setup_name(STABLE)).rename(world.release / "ChanceBlogDesktop-1.0.0-Setpu.exe")

        for label, change, expected in (("flip", flip, "asset_hash_differs — ChanceBlogDesktop-1.0.0-Setup.exe"), ("grow", grow, "asset_size_differs — ChanceBlogDesktop-1.0.0-win64.zip"),
                                        ("stray", stray, "file_unexpected — stray.txt"), ("missing", missing, "file_missing — PACKAGE_INFO.md"),
                                        ("typo", typo, "file_unexpected — ChanceBlogDesktop-1.0.0-Setpu.exe")):
            with self.subTest(label=label):
                world = World(self)
                change(world)
                code, out, err = self.verify(world)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("후보 폴더에 문제가 있다.\n", err)
                self.assertIn("문제: " + expected + "\n", err)

    def test_the_comparison_uses_the_files_bytes_not_the_sums_file(self):
        world = World(self)
        path = world.release / rc.setup_name(STABLE)
        path.write_bytes(b"x" * len(path.read_bytes()))                      # 크기는 그대로 — 해시만 다르다
        rts.write(world.release / "SHA256SUMS", rts.sums_text([(item.name, hashlib.sha256(item.read_bytes()).hexdigest()) for item in world.release.iterdir()
                                                                if item.name not in ("SHA256SUMS", "release_candidate.json")]))       # 해시 목록을 새 파일에 맞춰도
        code, _out, err = self.verify(world)
        self.assertEqual(code, 1)
        self.assertIn("문제: asset_hash_differs — " + rc.setup_name(STABLE), err)

    def test_a_subfolder_a_link_a_broken_record_and_another_version_are_refused(self):
        world = World(self)
        (world.release / "sub").mkdir()
        self.assertIn("file_not_regular — sub", self.verify(world)[2])
        world = World(self)
        (world.release / "release_candidate.json").write_bytes(b"{broken")
        self.assertIn("candidate_json", self.verify(world)[2])
        world = World(self)
        rts.write(world.base / "VERSION", "1.0.1\n")
        self.assertIn("version_mismatch — VERSION", self.verify(world)[2])
        link_world = World(self)
        try:
            os.symlink(str(link_world.release / rc.setup_name(STABLE)), str(link_world.release / "link.bin"))
        except (OSError, NotImplementedError):
            self.skipTest("건너뜀: 이 PC 는 심볼릭 링크를 만들 수 없다 — 링크 거절 확인은 못 했다(Q 의 참고 N2: 조용히 초록이 되지 않게)")
        self.assertIn("file_not_regular — link.bin", self.verify(link_world)[2])

    def test_the_size_caps_are_the_apps_and_follow_the_limits_argument(self):
        world = World(self)
        self.assertEqual(um.verify_folder(world.release, STABLE)[1], [])
        small = rc.Limits(file=10, total=rc.DEFAULT_LIMITS.total, support=rc.DEFAULT_LIMITS.support)
        self.assertIn("asset_size", [item.code for item in um.verify_folder(world.release, STABLE, limits=small)[1]])
        self.assertEqual((rc.DEFAULT_LIMITS.file, rc.DEFAULT_LIMITS.total), (manifest.MAX_FILE_BYTES, manifest.MAX_TOTAL_BYTES))

    def test_an_unreadable_version_file_or_wrong_arguments_stop_with_fixed_sentences(self):
        world = World(self)
        rts.write(world.base / "VERSION", "0.1.0-preview.1\n")
        self.assertEqual(self.verify(world), (2, "", "읽지 못했다: VERSION 을 읽지 못했거나 버전 글이 정식(X.Y.Z)·후보(X.Y.Z-rc.N) 모양이 아니다.\n"))
        for argv in ([], ["bogus"], ["verify-candidate"], ["build"], ["build", "--dir", "x"], ["verify-candidate", "--dir"]):
            code, out, err = run_tool(argv)
            self.assertEqual((code, out), (2, ""), argv)
            self.assertTrue(err.startswith("사용법 오류: verify-candidate --dir 폴더"), argv)


class BuildTest(unittest.TestCase):
    def test_the_built_manifest_is_accepted_by_the_apps_strict_reader_with_every_field_as_expected(self):
        world = World(self)
        code, out, err = world.build()
        self.assertEqual((code, err), (0, ""))
        data = world.manifest_bytes()
        found = app_read(data)
        record = json.loads((world.release / "release_candidate.json").read_text(encoding="utf-8"))
        wanted = {item["role"]: item for item in record["assets"]}
        self.assertEqual((found.channel, found.version, found.tag), ("stable", "1.0.0", "v1.0.0"))
        self.assertEqual((found.seq, found.issued, found.expires), (20261201030000, datetime(2026, 12, 1, 3, 0, 0, tzinfo=timezone.utc), datetime(2027, 5, 30, 3, 0, 0, tzinfo=timezone.utc)))
        self.assertEqual((found.min_version, found.key_id, found.commit), ("0.0.0", KEY_ID, rts.FAKE_COMMIT))
        self.assertEqual((found.installer_kind, found.pack_id), ("inno", "ChanceBlogDesktop"))
        self.assertEqual(found.summary, "- 첫 정식 판이에요.\n- 글 목록이 빨라졌어요.\n- 백업이 더 안전해졌어요.")
        self.assertEqual([(item.role, item.name, item.size, item.sha256) for item in found.files],
                         [("setup", rc.setup_name(STABLE), wanted["setup"]["size"], wanted["setup"]["sha256"]), ("portable", rc.portable_name(STABLE), wanted["portable"]["size"], wanted["portable"]["sha256"])])
        self.assertEqual(found.files[0].sha256, hashlib.sha256(rts.SETUP_BYTES).hexdigest())
        self.assertEqual(found.files[1].size, len(rts.ZIP_BYTES))
        self.assertIn("매니페스트를 만들었다: update-manifest.json · 버전 1.0.0 · 태그 v1.0.0 · 채널 stable · seq 20261201030000\n", out)
        self.assertIn("서명은 scripts/update_sign.py 가 한다", out)

    def test_the_bytes_are_utf8_without_bom_lf_only_one_final_newline_small_and_in_the_design_field_order(self):
        world = World(self)
        world.build()
        data = world.manifest_bytes()
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", data)
        self.assertTrue(data.endswith(b"}\n") and not data.endswith(b"\n\n"))
        self.assertLess(len(data), manifest.MAX_MANIFEST_BYTES)
        text = data.decode("utf-8")
        self.assertEqual(list(json.loads(text)), FIELD_ORDER)
        self.assertIn("첫 정식 판이에요.".encode("utf-8"), data, "한글은 이스케이프하지 않고 UTF-8 글자 그대로 둔다")
        self.assertEqual(data, (json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n").encode("utf-8"), "정해진 모양 그대로(다시 쓰면 같은 바이트)")

    def test_seq_is_the_issue_time_digits_and_the_expiry_is_exactly_180_days_later(self):
        for issued, seq, expires in (("2026-12-01T03:00:00Z", 20261201030000, "2027-05-30T03:00:00Z"), ("2026-12-31T23:59:59Z", 20261231235959, "2027-06-29T23:59:59Z"),
                                     ("2027-09-01T00:00:01Z", 20270901000001, "2028-02-28T00:00:01Z"), ("2028-01-01T00:00:00Z", 20280101000000, "2028-06-29T00:00:00Z"),
                                     ("2026-01-01T00:00:00Z", 20260101000000, "2026-06-30T00:00:00Z")):
            with self.subTest(issued=issued):
                world = World(self)
                self.assertEqual(world.build(issued=issued)[0], 0)
                found = app_read(world.manifest_bytes())
                self.assertEqual((found.seq, found.expires), (seq, manifest.parse_time(expires)))
                self.assertEqual(found.expires - found.issued, timedelta(days=180))
                self.assertLessEqual(found.expires - found.issued, timedelta(days=manifest.MAX_VALID_DAYS))
                self.assertEqual(found.seq, int(found.issued.strftime("%Y%m%d%H%M%S")))

    def test_the_pure_helpers(self):
        moment = datetime(2026, 12, 1, 3, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(um.seq_of(moment), 20261201030000)
        self.assertEqual(um.expiry_of(moment), datetime(2027, 5, 30, 3, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(um.time_text(moment), "2026-12-01T03:00:00Z")
        self.assertEqual(um.VALID_DAYS, 180)
        self.assertLess(um.VALID_DAYS, manifest.MAX_VALID_DAYS, "앱은 200일까지 받아들이고 도구는 설계의 180일로 서명한다(여유 20일)")
        self.assertEqual(um.SCHEMA, manifest.SCHEMA)

    def test_the_same_inputs_give_the_same_bytes_and_a_later_issue_time_gives_a_higher_seq(self):
        first, second = World(self), World(self)
        first.build()
        second.build()
        self.assertEqual(first.manifest_bytes(), second.manifest_bytes())
        later = World(self)
        later.build(issued="2026-12-01T03:00:01Z")
        self.assertGreater(app_read(later.manifest_bytes()).seq, app_read(first.manifest_bytes()).seq)
        self.assertNotEqual(later.manifest_bytes(), first.manifest_bytes())

    def test_the_clock_is_used_only_when_no_time_is_given_and_is_cut_to_whole_seconds(self):
        world = World(self)
        stamp = datetime(2026, 12, 2, 4, 5, 6, 789000, tzinfo=timezone.utc)
        code, _out, err = run_tool(world.build_args(issued=None), now=lambda: stamp)
        self.assertEqual((code, err), (0, ""))
        found = app_read(world.manifest_bytes())
        self.assertEqual((found.issued, found.seq), (datetime(2026, 12, 2, 4, 5, 6, tzinfo=timezone.utc), 20261202040506))
        other = World(self)
        run_tool(other.build_args(issued=ISSUED), now=lambda: stamp)
        self.assertEqual(app_read(other.manifest_bytes()).seq, 20261201030000, "시각을 주면 시계를 보지 않는다")
        zone = World(self)
        kst = datetime(2026, 12, 2, 13, 5, 6, tzinfo=timezone(timedelta(hours=9)))
        run_tool(zone.build_args(issued=None), now=lambda: kst)
        self.assertEqual(app_read(zone.manifest_bytes()).seq, 20261202040506, "다른 시간대의 시계도 UTC 로 바꾼다")

    def test_a_candidate_is_the_rc_channel_readable_only_by_the_offline_path(self):
        world = World(self, RC)
        self.assertEqual(world.build(min_version="0.0.0")[0], 0)
        data = world.manifest_bytes()
        found = app_read(data)
        self.assertEqual((found.channel, found.version, found.tag), ("rc", RC, "v" + RC))
        self.assertEqual([item.name for item in found.files], [rc.setup_name(RC), rc.portable_name(RC)])
        with self.assertRaises(manifest.ManifestError) as raised:
            app_read(data, manifest.CHANNELS_ONLINE)
        self.assertEqual(raised.exception.reason, "channel")

    def test_min_version_is_required_a_version_and_not_above_this_one(self):
        world = World(self)
        for bad in ("", "abc", "1.0", "1.0.1", "2.0.0", "01.0.0"):
            with self.subTest(min_version=bad):
                code, out, err = world.build(min_version=bad)
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(err, "만들지 않았다: --min-version 은 버전 글이어야 하고 이번 버전 이하여야 한다.\n")
        self.assertFalse((world.release / "update-manifest.json").exists())
        for fine in ("0.0.0", "0.9.0", "1.0.0", "1.0.0-rc.1"):
            with self.subTest(min_version=fine):
                other = World(self)
                self.assertEqual(other.build(min_version=fine)[0], 0)
                self.assertEqual(app_read(other.manifest_bytes()).min_version, fine)
        code, _out, err = run_tool([item for item in world.build_args() if item not in ("--min-version", "0.0.0")])
        self.assertEqual(code, 2, "꼭 주는 인자다")
        rc_world = World(self, RC)
        self.assertEqual(rc_world.build(min_version="1.0.0")[0], 2, "후보의 최소 버전이 정식이면 앱이 거절할 값이다")

    def test_key_id_must_be_16_lowercase_hex(self):
        world = World(self)
        for bad in ("0123456789ABCDEF", "0123456789abcde", "0123456789abcdef0", "zzzzzzzzzzzzzzzz", " 0123456789abcdef"):
            with self.subTest(key_id=bad):
                code, _out, err = world.build(key_id=bad)
                self.assertEqual((code, err), (2, "만들지 않았다: key_id 는 소문자 16진수 16글자(서명 키의 지문)여야 한다.\n"))

    def test_without_a_key_id_the_apps_current_shipped_key_is_used_and_an_empty_list_refuses(self):
        world = World(self)
        with mock.patch.object(um.app_keys, "shipped_keyring", return_value=keys.Keyring()):         # 진짜 출하 목록이 비어 있음에 기대지 않는다 — 운영자가 T3 로 진짜 키를 넣는 날에도 이 시험은 그대로다(Q 의 R4)
            code, _out, err = world.build(key_id=None)
        self.assertEqual((code, err), (2, "만들지 않았다: 앱에 내장된 현재 키가 없어 key_id 를 정할 수 없다 — 서명 키의 지문을 --key-id 로 준다.\n"))
        current, spare = us.public_key(rts.canary_seed("um-cur")), us.public_key(rts.canary_seed("um-spare"))
        both = keys.Keyring([(keys.ROLE_CURRENT, current), (keys.ROLE_SPARE, spare)])
        with mock.patch.object(um.app_keys, "shipped_keyring", return_value=both):
            self.assertEqual(world.build(key_id=None)[0], 0)
        self.assertEqual(app_read(world.manifest_bytes()).key_id, rts.key_id(current))
        only_spare = World(self)
        with mock.patch.object(um.app_keys, "shipped_keyring", return_value=keys.Keyring([(keys.ROLE_SPARE, spare)])):
            self.assertEqual(only_spare.build(key_id=None)[0], 2)
        explicit = World(self)
        with mock.patch.object(um.app_keys, "shipped_keyring", return_value=both):
            self.assertEqual(explicit.build(key_id=rts.key_id(spare))[0], 0)
        self.assertEqual(app_read(explicit.manifest_bytes()).key_id, rts.key_id(spare), "예비 키로 서명할 때는 지문을 직접 준다")

    def test_the_key_id_tests_do_not_depend_on_the_real_shipped_list(self):
        """재작업 1(Q 의 R4) — 진짜 출하 목록(`SHIPPED_KEYS`)에 키가 들어 있어도(운영자가 T3 로 넣는 날) '내장 키가 없으면 거절' 시험이 그대로 통과한다."""
        entries = (("current", base64.b64encode(us.public_key(rts.canary_seed("um-shipped"))).decode("ascii")),)
        with mock.patch.object(keys, "SHIPPED_KEYS", entries):
            self.assertEqual(len(keys.shipped_keyring()), 1, "가짜 출하 목록이 실제로 끼어 들었다")
            result = unittest.TestResult()
            unittest.TestSuite([BuildTest("test_without_a_key_id_the_apps_current_shipped_key_is_used_and_an_empty_list_refuses")]).run(result)
        self.assertTrue(result.wasSuccessful(), [text for _case, text in result.failures + result.errors])

    def test_a_bad_issue_time_is_refused(self):
        world = World(self)
        for bad in ("2026-12-01 03:00:00", "2026-13-01T00:00:00Z", "2026-12-01T03:00:00", "2026-12-01T03:00:00z", "2026-02-30T00:00:00Z", "", "yesterday", "2026-12-01T03:00:00+09:00"):
            with self.subTest(issued=bad):
                code, _out, err = world.build(issued=bad)
                self.assertEqual((code, err), (2, "만들지 않았다: --issued-utc 는 YYYY-MM-DDThh:mm:ssZ 꼴의 실제 있는 시각이어야 한다.\n"))
        self.assertFalse((world.release / "update-manifest.json").exists())

    def test_an_existing_manifest_is_never_overwritten_and_out_can_write_elsewhere_without_touching_the_folder(self):
        world = World(self)
        elsewhere = world.base / "elsewhere.json"
        self.assertEqual(world.build("--out", str(elsewhere))[0], 0)
        self.assertTrue(elsewhere.is_file())
        self.assertEqual(sorted(item.name for item in world.release.iterdir()), sorted(list(rc.asset_names(STABLE).values()) + ["release_candidate.json"]), "다른 파일을 더하지 않는다(임시 파일 포함)")
        before = elsewhere.read_bytes()
        code, out, err = world.build("--out", str(elsewhere), issued="2026-12-02T00:00:00Z")
        self.assertEqual((code, out, err), (2, "", "만들지 않았다: 매니페스트 파일이 이미 있다 — 후보 폴더를 새로 모아 다시 만든다.\n"))
        self.assertEqual(elsewhere.read_bytes(), before)
        self.assertEqual(world.build()[0], 0)
        first = world.manifest_bytes()
        code, _out, err = world.build(issued="2026-12-02T00:00:00Z")
        self.assertEqual((code, err), (2, "만들지 않았다: 매니페스트 파일이 이미 있다 — 후보 폴더를 새로 모아 다시 만든다.\n"))
        self.assertEqual(world.manifest_bytes(), first)
        self.assertEqual(app_read(first).seq, 20261201030000, "거절한 두 번째 시도가 첫 매니페스트를 바꾸지 않았다")

    def test_a_manifest_already_in_the_folder_makes_the_candidate_phase_chain_refuse_it_as_unexpected(self):
        world = World(self)
        self.assertEqual(world.build()[0], 0)
        code, _out, err = world.build("--out", str(world.base / "again.json"))
        self.assertEqual(code, 1)
        self.assertIn("문제: file_unexpected — update-manifest.json", err)
        self.assertFalse((world.base / "again.json").exists())

    def test_a_dangling_link_at_the_target_counts_as_existing(self):
        world = World(self)
        target = world.release / "update-manifest.json"
        try:
            os.symlink(str(world.base / "nowhere.json"), str(target))
        except (OSError, NotImplementedError):
            self.skipTest("건너뜀: 이 PC 는 심볼릭 링크를 만들 수 없다")
        self.assertEqual(world.build()[0], 2)

    def test_the_chain_must_hold_before_a_manifest_is_made(self):
        def flip(world):
            path = world.release / rc.setup_name(STABLE)
            data = bytearray(path.read_bytes())
            data[3] ^= 1
            path.write_bytes(bytes(data))
        cases = {
            "changed asset": (lambda world: flip(world), "asset_hash_differs"),
            "changelog top is another version": (lambda world: rts.write(world.base / "CHANGELOG.md", rts.changelog_text("1.0.1")), "changelog_top"),
            "note without summary lines": (lambda world: rts.write(world.base / "CHANGELOG.md", rts.changelog_text(STABLE, summary=("- 하나",))), "summary_lines"),
            "stray file": (lambda world: rts.write(world.release / "stray.txt", b"x"), "file_unexpected"),
            "package info of another commit": (lambda world: (_edit_info(world, git={"commit": rts.OTHER_COMMIT}), rc.write_sums(world.release),
                                                              rts.write_candidate(world.release, STABLE)), "info_commit"),
        }
        for label, (change, expected) in cases.items():
            with self.subTest(label=label):
                world = World(self)
                change(world)
                code, out, err = world.build()
                self.assertEqual((code, out), (1, ""), err)
                self.assertIn("사슬 확인에서 문제가 있어 매니페스트를 만들지 않았다.\n", err)
                self.assertIn("문제: " + expected, err)
                self.assertFalse((world.release / "update-manifest.json").exists())

    def test_a_version_file_that_differs_from_the_candidate_stops_the_build(self):
        world = World(self)
        rts.write(world.base / "VERSION", "1.0.1\n")
        code, _out, err = world.build()
        self.assertEqual(code, 1)
        self.assertIn("version_mismatch", err)

    def test_what_the_app_would_refuse_is_never_written_and_reports_the_apps_reason(self):
        world = World(self)
        real = um.build_manifest

        def wrong_seq(*args, **kwargs):
            data = real(*args, **kwargs)
            data["seq"] = 1
            return data
        with mock.patch.object(um, "build_manifest", wrong_seq):
            code, out, err = world.build()
        self.assertEqual((code, out, err), (4, "", "만들지 않았다: 앱이 받아들이지 않을 매니페스트다(이유 이름표: seq).\n"))
        self.assertFalse((world.release / "update-manifest.json").exists())

    def test_the_summary_that_the_app_refuses_is_stopped_before_writing(self):
        world = World(self, summary=("- 가" + chr(0x200D) + "나", "- 둘", "- 셋"))
        code, _out, err = world.build()
        self.assertEqual(code, 1)
        self.assertIn("summary_chars", err)
        self.assertFalse((world.release / "update-manifest.json").exists())

    def test_the_tool_never_touches_the_signing_key(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("UPDATE_SIGNING_KEY", text)
        self.assertNotIn("environ", text, "환경 변수를 읽지 않는다")
        tree = ast.parse(text)
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imported & {"socket", "urllib", "http", "ssl", "subprocess", "requests", "logging", "update_sign", "base64"}, imported)
        self.assertNotIn("print", [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)])


ISSUED_RANGE_MESSAGE = ("만들지 않았다: 발행 시각이 허용 범위를 벗어났다 — 2020년 1월 1일 이후 2100년 1월 1일 전이어야 하고 이 PC 시계보다 하루 넘게 앞서면 안 된다"
                        "(PC 시계나 --issued-utc 를 확인한다).\n")


class IssueTimeRangeTest(unittest.TestCase):
    """재작업 1(S-2) — 발행 시각(`seq` 가 이 시각의 숫자 열네 자리)에 상·하한이 있다. 앱은 `last_seq` 를 높게 영구 기록하므로 미래 시각으로 서명하면 이후 정상 릴리스가 막힌다.
    허용 범위: 2020년 1월 1일 이후·2100년 1월 1일 전·지금(주입한 시계)보다 24시간 넘게 앞서지 않음. 밖이면 고정 문장·종료 코드 2·파일 없음, 예외 글은 새지 않는다."""

    NOW = datetime(2026, 12, 2, 4, 5, 6, tzinfo=timezone.utc)

    def build_at(self, issued, now):
        world = World(self)
        code, out, err = run_tool(world.build_args(issued=issued), now=lambda: now)
        return world, code, out, err

    def test_the_pure_range_check_has_exact_boundaries(self):
        now, slack = self.NOW, timedelta(hours=24)
        self.assertEqual(um.FUTURE_SLACK, slack)
        self.assertEqual((um.EARLIEST_ISSUED, um.LATEST_ISSUED), (datetime(2020, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc)))
        inside = {"now": now, "a day ahead exactly": now + slack, "a second ago": now - timedelta(seconds=1), "just before the clock": now - timedelta(days=170), "the earliest": um.EARLIEST_ISSUED}
        outside = {"a day and a second ahead": now + slack + timedelta(seconds=1), "ten days ahead": now + timedelta(days=10), "a second before the earliest": um.EARLIEST_ISSUED - timedelta(seconds=1),
                   "1970": datetime(1970, 1, 1, tzinfo=timezone.utc), "year 1": datetime(1, 1, 1, tzinfo=timezone.utc), "year 9999": datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
                   "year 2999": datetime(2999, 12, 31, 23, 59, 59, tzinfo=timezone.utc), "naive": datetime(2026, 12, 2, 4, 5, 6), "none": None, "text": "2026-12-02T04:05:06Z"}
        for label, issued in inside.items():
            with self.subTest(inside=label):
                self.assertTrue(um.issued_in_range(issued, now))
        for label, issued in outside.items():
            with self.subTest(outside=label):
                self.assertFalse(um.issued_in_range(issued, now))

    def test_the_ceiling_holds_even_when_the_clock_is_just_below_it_and_an_unusable_clock_refuses_everything(self):
        late = datetime(2099, 12, 31, 23, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(um.issued_in_range(datetime(2099, 12, 31, 23, 59, 59, tzinfo=timezone.utc), late))
        self.assertFalse(um.issued_in_range(datetime(2100, 1, 1, 0, 0, 0, tzinfo=timezone.utc), late), "시계가 아직 2100년 전이어도 2100년 1월 1일 이후는 안 된다")
        for label, clock in {"max": datetime.max.replace(tzinfo=timezone.utc), "naive": datetime(2026, 12, 2), "none": None}.items():
            with self.subTest(clock=label):
                self.assertFalse(um.issued_in_range(datetime(2026, 12, 1, tzinfo=timezone.utc), clock), "쓸 수 없는 시계로는 아무 시각도 허용하지 않는다(의심스러우면 거절)")

    def test_far_future_far_past_and_overflowing_times_are_refused_with_the_fixed_sentence_and_no_file(self):
        samples = ("2999-12-31T23:59:59Z", "9999-12-31T23:59:59Z", "9999-07-05T00:00:00Z", "1970-01-01T00:00:00Z", "0001-01-01T00:00:00Z", "2019-12-31T23:59:59Z",
                   "2100-01-01T00:00:00Z", "2026-12-03T04:05:07Z", "2026-12-12T04:05:06Z", "2027-12-02T04:05:06Z")
        for issued in samples:
            with self.subTest(issued=issued):
                world, code, out, err = self.build_at(issued, self.NOW)
                self.assertEqual((code, out, err), (2, "", ISSUED_RANGE_MESSAGE))
                self.assertFalse((world.release / "update-manifest.json").exists())
                for word in ("Traceback", "OverflowError", "ValueError", "date value"):
                    self.assertNotIn(word, err)

    def test_times_just_inside_the_range_make_a_manifest_the_app_accepts(self):
        for issued in ("2026-12-03T04:05:06Z", "2026-12-02T04:05:06Z", "2026-12-02T04:05:05Z", "2026-06-15T00:00:00Z", "2020-01-01T00:00:00Z"):
            with self.subTest(issued=issued):
                world, code, _out, err = self.build_at(issued, self.NOW)
                self.assertEqual((code, err), (0, ""))
                found = app_read(world.manifest_bytes())
                self.assertEqual(found.issued, manifest.parse_time(issued))
                self.assertEqual(found.seq, int(found.issued.strftime("%Y%m%d%H%M%S")))

    def test_a_clock_far_off_refuses_even_without_an_explicit_time(self):
        for label, now in {"year 2999": datetime(2999, 1, 1, tzinfo=timezone.utc), "year 9999": datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc), "1970": datetime(1970, 1, 1, tzinfo=timezone.utc),
                           "2100": datetime(2100, 1, 1, tzinfo=timezone.utc), "before 2020": datetime(2019, 12, 31, 23, 59, 59, tzinfo=timezone.utc)}.items():
            with self.subTest(clock=label):
                world = World(self)
                code, out, err = run_tool(world.build_args(issued=None), now=lambda now=now: now)
                self.assertEqual((code, out, err), (2, "", ISSUED_RANGE_MESSAGE))
                self.assertFalse((world.release / "update-manifest.json").exists())
        world = World(self)
        code, _out, err = run_tool(world.build_args(issued=None), now=lambda: datetime(2020, 1, 1, tzinfo=timezone.utc))
        self.assertEqual((code, err), (0, ""), "허용 범위의 맨 아래 시계는 된다")

    def test_a_clock_that_overflows_when_turned_to_utc_or_cannot_take_a_day_more_refuses_without_a_traceback(self):
        far_west = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(-timedelta(hours=12)))                # UTC 로 바꾸면 9999년을 넘는다
        for label, now in {"overflows on conversion": far_west, "max in utc": datetime.max.replace(tzinfo=timezone.utc)}.items():
            for issued in (None, "2026-12-01T03:00:00Z"):
                with self.subTest(clock=label, issued=issued):
                    world = World(self)
                    code, out, err = run_tool(world.build_args(issued=issued), now=lambda now=now: now)
                    self.assertEqual((code, out, err), (2, "", ISSUED_RANGE_MESSAGE))
                    self.assertFalse((world.release / "update-manifest.json").exists())

    def test_the_order_of_the_refusals_is_unchanged_a_malformed_time_is_still_the_format_message(self):
        world = World(self)
        code, _out, err = run_tool(world.build_args(issued="yesterday"), now=lambda: self.NOW)
        self.assertEqual((code, err), (2, "만들지 않았다: --issued-utc 는 YYYY-MM-DDThh:mm:ssZ 꼴의 실제 있는 시각이어야 한다.\n"))

    def test_the_clock_only_bounds_an_explicit_time_it_never_replaces_it(self):
        world = World(self)
        run_tool(world.build_args(issued="2026-12-01T03:00:00Z"), now=lambda: self.NOW)
        self.assertEqual(app_read(world.manifest_bytes()).seq, 20261201030000)


class DefaultArgumentsTest(unittest.TestCase):
    """재작업 1(시험 렌즈 Q 의 R7) — R-3 워크플로가 `--version-file`·`--changelog` 없이(기본값으로) 부르는 길: 기본값이 저장소 맨 위 폴더의 `VERSION`·`CHANGELOG.md` 이고 그 값으로 부른 결과가 실제로 맞다."""

    def test_the_parser_defaults_are_the_repository_root_files(self):
        parser = um._build_parser()
        parsed = parser.parse_args(["build", "--dir", "x", "--min-version", "0.0.0"])
        self.assertEqual((parsed.version_file, parsed.changelog), (str(um.ROOT / "VERSION"), str(um.ROOT / "CHANGELOG.md")))
        self.assertEqual(parser.parse_args(["verify-candidate", "--dir", "x"]).version_file, str(um.ROOT / "VERSION"))
        self.assertEqual(parsed.issued_utc, None, "시각을 안 주면 시계를 쓴다")
        self.assertEqual((parsed.key_id, parsed.out), (None, None))

    def test_calling_without_the_path_arguments_works_from_a_root_folder(self):
        world = World(self)
        with mock.patch.object(um, "ROOT", world.base):
            code, _out, err = run_tool(["verify-candidate", "--dir", str(world.release)])
            self.assertEqual((code, err), (0, ""))
            code, _out, err = run_tool(["build", "--dir", str(world.release), "--min-version", "0.0.0", "--key-id", KEY_ID, "--issued-utc", ISSUED], now=clock_for(ISSUED))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(app_read(world.manifest_bytes()).version, STABLE)


class ExclusiveManifestFileTest(unittest.TestCase):
    """재작업 1(참고 N-1) — 매니페스트 파일은 **배타적으로**(`O_EXCL`) 만든다: 검사(`lexists`)와 쓰기 사이에 파일이 생겨도 덮어쓰지 않고, 쓰다 실패하면 반쯤 쓴 파일이나 임시 파일이 남지 않는다."""

    def test_a_file_that_appears_after_the_existence_check_is_never_overwritten(self):
        world = World(self)
        elsewhere = world.base / "elsewhere.json"
        elsewhere.write_bytes(b"written first by someone else\n")
        with mock.patch("os.path.lexists", return_value=False):                       # 검사가 지나간 것처럼 — 그 사이에 파일이 생긴 경쟁
            code, out, err = world.build("--out", str(elsewhere))
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "만들지 않았다: 매니페스트 파일이 이미 있다 — 후보 폴더를 새로 모아 다시 만든다.\n")
        self.assertEqual(elsewhere.read_bytes(), b"written first by someone else\n")
        self.assertEqual(sorted(item.name for item in world.base.iterdir()), ["CHANGELOG.md", "VERSION", "elsewhere.json", "release"])

    def test_a_failed_write_leaves_no_half_written_file_and_no_temp_file(self):
        world = World(self)
        elsewhere = world.base / "elsewhere.json"
        with mock.patch("os.fsync", side_effect=OSError("disk full")):
            code, out, err = world.build("--out", str(elsewhere))
        self.assertEqual((code, out, err), (2, "", "만들지 못했다: 매니페스트 파일을 쓰지 못했다.\n"))
        self.assertEqual(sorted(item.name for item in world.base.iterdir()), ["CHANGELOG.md", "VERSION", "release"], "반쯤 쓴 파일이나 임시 파일을 남기지 않는다")
        self.assertEqual(world.build("--out", str(elsewhere))[0], 0, "실패한 뒤 다시 만들 수 있다")


def _edit_info(world, **updates):
    path = world.release / "PACKAGE_INFO.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(updates)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


class PipelineTest(unittest.TestCase):
    """서명 잡이 하는 일을 처음부터 끝까지 — 모으기 → 후보 검증 → 매니페스트 → 서명 → 해시 목록 → 서명 뒤 사슬 확인 → 앱의 검증기."""

    def run_pipeline(self, version):
        holder = rts.temp_dir()
        self.addCleanup(holder.cleanup)
        base = Path(holder.name)
        source = rts.fake_release(base / "package", version, with_candidate=False)
        (source / "SHA256SUMS").unlink()
        rts.write(base / "VERSION", version + "\n")
        rts.write(base / "CHANGELOG.md", rts.changelog_text(version))
        common = ["--version-file", str(base / "VERSION")]
        release = base / "release"
        seed = rts.canary_seed("pipe-" + version)
        public = us.public_key(seed)
        steps = {}
        steps["assemble"] = rts.Capture(rc.main)(["assemble", "--source", str(source), "--out", str(release), "--commit", rts.FAKE_COMMIT, "--changelog", str(base / "CHANGELOG.md")] + common)
        steps["verify"] = run_tool(["verify-candidate", "--dir", str(release)] + common)
        steps["build"] = run_tool(["build", "--dir", str(release), "--min-version", "0.0.0", "--key-id", rts.key_id(public), "--issued-utc", ISSUED, "--changelog", str(base / "CHANGELOG.md")] + common, now=clock_for(ISSUED))
        steps["sign"] = rts.Capture(update_sign.main)(["--manifest", str(release / "update-manifest.json")], environ={"UPDATE_SIGNING_KEY": rts.seed_b64(seed)}, which=lambda name: None)
        steps["sums"] = rts.Capture(rc.main)(["sums", "--dir", str(release)])
        steps["check"] = rts.Capture(rc.main)(["check", "--dir", str(release), "--phase", "final", "--commit", rts.FAKE_COMMIT, "--changelog", str(base / "CHANGELOG.md")] + common)
        return base, release, seed, public, steps

    def test_the_whole_signing_job_flow_works_for_a_stable_and_a_candidate_version(self):
        for version in (STABLE, RC):
            with self.subTest(version=version):
                base, release, seed, public, steps = self.run_pipeline(version)
                for name, (code, out, err) in steps.items():
                    self.assertEqual((name, code, err), (name, 0, ""), out)
                data, signature = (release / "update-manifest.json").read_bytes(), (release / "update-manifest.json.sig").read_bytes()
                ring = keys.Keyring([(keys.ROLE_CURRENT, public)])
                verdict = manifest.verify_manifest(data, signature, keyring=ring, now=datetime(2026, 12, 2, tzinfo=timezone.utc), current_version="0.0.1", last_seq=0, install_kind="inno", channels=manifest.CHANNELS_OFFLINE)
                self.assertEqual((verdict.status, verdict.apply_possible, verdict.manifest.version), ("AVAILABLE", True, version))
                if version == STABLE:
                    online = manifest.verify_manifest(data, signature, keyring=ring, now=datetime(2026, 12, 2, tzinfo=timezone.utc), current_version="0.0.1", install_kind="inno")
                    self.assertEqual(online.status, "AVAILABLE", "정식은 온라인 확인 길에서도 읽힌다")
                else:
                    with self.assertRaises(manifest.ManifestError):
                        manifest.verify_manifest(data, signature, keyring=ring, now=datetime(2026, 12, 2, tzinfo=timezone.utc), current_version="0.0.1", install_kind="inno")
                sums = (release / "SHA256SUMS").read_text(encoding="utf-8")
                self.assertIn("  update-manifest.json\n", sums)
                self.assertIn("  update-manifest.json.sig\n", sums)
                self.assertNotIn("release_candidate.json", sums)

    def test_the_signature_is_the_one_the_independent_reference_signer_makes(self):
        base, release, seed, public, steps = self.run_pipeline(STABLE)
        data = (release / "update-manifest.json").read_bytes()
        self.assertEqual((release / "update-manifest.json.sig").read_bytes(), us.signature_file(seed, data))

    def test_any_changed_byte_of_the_signed_manifest_is_refused_by_the_app(self):
        _base, release, _seed, public, _steps = self.run_pipeline(STABLE)
        data, signature = (release / "update-manifest.json").read_bytes(), (release / "update-manifest.json.sig").read_bytes()
        ring = keys.Keyring([(keys.ROLE_CURRENT, public)])
        manifest.read_and_verify(data, signature, keyring=ring, channels=manifest.CHANNELS_OFFLINE)
        step = max(1, len(data) // 60)
        for index in list(range(0, len(data), step)) + [len(data) - 1]:
            changed = bytearray(data)
            changed[index] ^= 0x01
            with self.subTest(index=index):
                with self.assertRaises(manifest.ManifestError):
                    manifest.read_and_verify(bytes(changed), signature, keyring=ring, channels=manifest.CHANNELS_OFFLINE)
        changed_signature = bytearray(base64_decode(signature))
        changed_signature[0] ^= 1
        with self.assertRaises(manifest.ManifestError):
            manifest.read_and_verify(data, signature_file_of(changed_signature), keyring=ring, channels=manifest.CHANNELS_OFFLINE)

    def test_a_file_swapped_after_the_candidate_was_made_is_caught_before_any_manifest_exists(self):
        holder = rts.temp_dir()
        self.addCleanup(holder.cleanup)
        world = World(self)
        path = world.release / rc.portable_name(STABLE)
        data = bytearray(path.read_bytes())
        data[5] ^= 1
        path.write_bytes(bytes(data))
        code, _out, err = run_tool(["verify-candidate", *world.common])
        self.assertEqual(code, 1)
        self.assertIn("asset_hash_differs", err)
        self.assertEqual(world.build()[0], 1)
        self.assertFalse((world.release / "update-manifest.json").exists())


def base64_decode(signature_file_bytes):
    import base64
    return base64.b64decode(signature_file_bytes.strip())


def signature_file_of(raw):
    import base64
    return base64.b64encode(bytes(raw)) + b"\n"


class ScriptFileTest(unittest.TestCase):
    def test_the_script_file_runs_as_a_program_for_verify_and_build(self):
        world = World(self)
        environ = {key: value for key, value in os.environ.items() if not key.startswith("UPDATE_")}
        environ.pop("PYTHONPATH", None)
        environ["PYTHONUTF8"] = "1"
        environ["PYTHONIOENCODING"] = "utf-8"            # 부모 환경(예: cp949)에 흔들리지 않게 자식의 입출력 인코딩을 못박는다(Q 의 R3)
        done = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "verify-candidate", *world.common], capture_output=True, env=environ, timeout=300)
        self.assertEqual((done.returncode, done.stderr), (0, b""), done.stdout)
        recent = um.time_text(datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2))      # 진짜 하위 프로세스는 진짜 시계를 쓰므로 발행 시각도 지금 가까이로 준다(재작업 1·S-2)
        done = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), *world.build_args(issued=recent)], capture_output=True, env=environ, timeout=300)
        self.assertEqual((done.returncode, done.stderr), (0, b""), done.stdout)
        self.assertEqual(app_read(world.manifest_bytes()).version, STABLE)
        self.assertEqual(app_read(world.manifest_bytes()).seq, int(recent.replace("-", "").replace("T", "").replace(":", "").replace("Z", "")))
        self.assertEqual(world.manifest_bytes().count(b"\r"), 0)

    def test_the_script_file_refuses_a_far_future_time_with_the_fixed_sentence_and_no_traceback(self):
        world = World(self)
        environ = {key: value for key, value in os.environ.items() if not key.startswith("UPDATE_")}
        environ.pop("PYTHONPATH", None)
        environ["PYTHONUTF8"] = "1"
        environ["PYTHONIOENCODING"] = "utf-8"            # 부모 환경(예: cp949)에 흔들리지 않게 자식의 입출력 인코딩을 못박는다(Q 의 R3)
        for issued in ("2999-12-31T23:59:59Z", "9999-12-31T23:59:59Z"):
            with self.subTest(issued=issued):
                done = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), *world.build_args(issued=issued)], capture_output=True, env=environ, timeout=300)
                self.assertEqual(done.returncode, 2)
                self.assertNotIn(b"Traceback", done.stderr)
                self.assertNotIn(b"OverflowError", done.stderr)
                self.assertIn("발행 시각이 허용 범위를 벗어났다".encode("utf-8"), done.stderr)
                self.assertFalse((world.release / "update-manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
