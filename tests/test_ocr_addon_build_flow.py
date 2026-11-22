"""글자 읽기 추가 도구 빌드 스크립트(`ocr_addon/build_ocr_addon.py`, 결정 D-527에서 D-531)의 **흐름** 시험 — PyInstaller·pefile·진짜 모델 없이, 가짜 단계와 작은 가짜 파일로 돈다.

지키는 것: ① 점검(R1–R4)에 걸리면 종료 코드 1 이고 정보 파일·zip 을 만들지 않는다(`info`·`zip` 단계를 따로 불러도 통과한 점검 결과가 없으면 거절)
② 출력 폴더는 비었거나 이 도구가 만든 폴더(표지 파일)일 때만 지운다 ③ 모델·사전은 잠금 크기·SHA-256 과 다르면 멈춘다 ④ 자가 점검이 묶음 폴더나 임시 폴더에 파일을 쓰면 실패
⑤ 시각은 SOURCE_DATE_EPOCH 나 커밋 시각에서 ⑥ 정보 파일은 **앱의 추가 도구 확인(`service/ocr_addon.py`)이 ok 로 읽는 모양**이다 ⑦ zip 은 맨 위 폴더가 `ocr`, 시각·순서 고정(같은 입력이면 같은 바이트),
옆에 SHA256SUMS·PACKAGE_INFO.json 만 둔다.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_build_support as support  # noqa: E402

build = support.load("build_ocr_addon")
rules = support.load("build_rules")
ROOT = support.ROOT
STATE = {"commit": "0123456789abcdef0123456789abcdef01234567", "epoch": 1794873600, "epoch_from": "git commit", "committed_utc": "2026-11-17T00:00:00Z", "clean": True, "dirty_count": 0}
HAVE_GIT = subprocess.run(["git", "--version"], capture_output=True).returncode == 0 if __import__("shutil").which("git") else False
FAKE = {"models/det/inference.onnx": b"det-model", "models/rec/inference.onnx": b"rec-model-bytes", "data/ppocrv5_korean_dict.txt": b"dict\nbytes\n"}
FAKE_EXPECTED = {key: (len(data), hashlib.sha256(data).hexdigest()) for key, data in FAKE.items()}
FAKE_LOCK = {"schema": 1, "files": []}
# 확인 030 ② 의 고지 산출물(notices 단계가 점검 앞에서 묶음 폴더에 만드는 것)을 가짜로 — 진짜 만들기는 test_ocr_addon_notices.py·test_ocr_addon_merged_flow.py 가 본다.
GEOS = {"name": "GEOS", "version": "3.99.9", "license": "LGPL-2.1", "dll_files": ["_internal/Shapely.libs/geos-aaaa.dll"], "license_file": "licenses/shapely/LICENSE_GEOS", "replaceable": True,
        "source_host": "libgeos.org", "source_included": False}
NOTICE_FILES = {"THIRD_PARTY_NOTICES.txt": "제3자 부품 고지 - GEOS LGPL-2.1\n", "licenses/shapely/LICENSE_GEOS": "GNU LESSER GENERAL PUBLIC LICENSE Version 2.1\n", "licenses/numpy/LICENSE.txt": "BSD 3-Clause\n",
                "_internal/Shapely.libs/geos-aaaa.dll": b"geos-dll-bytes"}


def temp():
    folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    return folder, Path(folder.name)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


class StageChainTest(unittest.TestCase):
    """main 이 단계를 부르는 순서와 '점검이 실패하면 거기서 끝' 규칙 — 모든 단계를 가짜로 바꿔 부른 순서를 본다."""

    def setUp(self):
        self.folder, self.root = temp()
        self.addCleanup(self.folder.cleanup)
        self.out = str(self.root / "out")
        self.calls = []

    def run_main(self, argv, *, check_ok=True, state=STATE, fail_at=None, error=None):
        """`fail_at` 단계는 불려 간 기록을 남긴 뒤 `error` 를 던진다(뒤 단계가 이어서 불리지 않는지 보는 자리)."""
        def recorder(name, result=None):
            def call(*args, **kwargs):
                self.calls.append(name)
                if name == fail_at:
                    raise error
                return result
            return call

        patches = [mock.patch.object(build, "log"), mock.patch.object(build, "source_state", return_value=dict(state)), mock.patch.object(build, "freeze", side_effect=recorder("freeze")),
                   mock.patch.object(build, "assemble", side_effect=recorder("assemble")), mock.patch.object(build, "remove_unused", side_effect=recorder("remove")),
                   mock.patch.object(build, "write_notices", side_effect=recorder("notices")),
                   mock.patch.object(build, "check", side_effect=recorder("check", (check_ok, {}))), mock.patch.object(build, "make_info", side_effect=recorder("info", {"name": "x"})),
                   mock.patch.object(build, "make_zip", side_effect=recorder("zip"))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        stderr = []
        with mock.patch.object(sys.stderr, "write", side_effect=stderr.append):
            code = build.main(argv)
        return code, "".join(stderr)

    def test_all_runs_the_seven_stages_in_order_and_the_notices_and_the_check_sit_before_info_and_zip(self):
        """확인 030 ② — 고지 파일 만들기(notices)는 점검 앞이다: 점검(R2 금지 이름·키 모양 훑기)이 고지 파일도 보고, 정보 파일의 파일 목록에 그 파일들이 들어간다."""
        code, _err = self.run_main(["all", "--out-dir", self.out, "--models-dir", str(self.root / "models")])
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["freeze", "assemble", "remove", "notices", "check", "info", "zip"])

    def test_a_failed_check_ends_the_build_with_one_and_makes_neither_info_nor_zip(self):
        code, _err = self.run_main(["all", "--out-dir", self.out, "--models-dir", str(self.root / "models")], check_ok=False)
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, ["freeze", "assemble", "remove", "notices", "check"])

    def test_a_failed_notices_stage_stops_the_build_with_two_before_the_check_and_nothing_after_it_runs(self):
        """GEOS 라이선스 전문·판·별도 GEOS 파일을 못 찾으면 notices 가 BuildError 로 멈춘다 — 조용히 건너뛰고 점검·정보 파일·zip 으로 가는 길이 없다."""
        code, err = self.run_main(["all", "--out-dir", self.out, "--models-dir", str(self.root / "models")], fail_at="notices", error=build.BuildError("GEOS 라이선스 전문(LICENSE_GEOS)을 찾지 못했다"))
        self.assertEqual((code, self.calls), (2, ["freeze", "assemble", "remove", "notices"]))
        self.assertIn("LICENSE_GEOS", err)

    def test_every_stage_that_stops_the_build_ends_it_with_two_and_no_later_stage_runs(self):
        """B1 의 `test_a_failed_freeze_or_assemble_stops_everything_after_it`·`test_a_failed_info_stage_stops_before_the_zip` 를 합친 단계 이름들로 — 어느 단계가 멈추든 뒤는 불리지 않고 종료 코드는 0 이 아니다."""
        order = ["freeze", "assemble", "remove", "notices", "check", "info", "zip"]
        for stage in order:
            with self.subTest(stage=stage):
                self.calls.clear()
                code, err = self.run_main(["all", "--out-dir", self.out, "--models-dir", str(self.root / "models")], fail_at=stage, error=build.BuildError("단계 %s 가 멈췄다" % stage))
                self.assertEqual((code, self.calls), (2, order[:order.index(stage) + 1]))
                self.assertIn("단계 %s 가 멈췄다" % stage, err)

    def test_each_single_stage_runs_only_itself(self):
        """B1 의 단계별 시험(`test_single_stages_run_only_themselves`·`test_the_check_stage_alone_returns_its_own_code`)을 합친 단계 이름들로 — 따로 부른 단계는 자기 일만 한다."""
        for stage in ("freeze", "remove", "notices"):
            with self.subTest(stage=stage):
                self.calls.clear()
                code, _err = self.run_main([stage, "--out-dir", self.out])
                self.assertEqual((code, self.calls), (0, [stage]))
        self.calls.clear()
        code, _err = self.run_main(["assemble", "--out-dir", self.out, "--models-dir", str(self.root / "models")])
        self.assertEqual((code, self.calls), (0, ["assemble"]))
        self.calls.clear()
        code, _err = self.run_main(["check", "--out-dir", self.out])
        self.assertEqual((code, self.calls), (0, ["check"]))
        self.calls.clear()
        code, _err = self.run_main(["check", "--out-dir", self.out], check_ok=False)
        self.assertEqual((code, self.calls), (1, ["check"]), "check 단계만 따로 불러도 실패는 종료 코드 1")

    def test_the_models_folder_is_required_for_all_and_assemble_before_anything_runs(self):
        for stage in ("all", "assemble"):
            with self.subTest(stage=stage):
                self.calls.clear()
                code, err = self.run_main([stage, "--out-dir", self.out])
                self.assertEqual((code, self.calls), (2, []))
                self.assertIn("--models-dir", err)

    def test_require_clean_refuses_a_dirty_source_before_anything_runs(self):
        dirty = dict(STATE, clean=False, dirty_count=3)
        code, err = self.run_main(["all", "--out-dir", self.out, "--models-dir", str(self.root / "m"), "--require-clean"], state=dirty)
        self.assertEqual((code, self.calls), (2, []))
        self.assertIn("커밋되지 않은 변경", err)
        self.calls.clear()
        code, _err = self.run_main(["all", "--out-dir", self.out, "--models-dir", str(self.root / "m")], state=dirty)
        self.assertEqual(code, 0, "깨끗함을 요구하지 않을 때(손으로 돌리는 시험)는 변경이 있어도 만든다")

    def test_info_and_zip_alone_need_a_passed_check_result(self):
        write(Path(self.out) / "dist" / "ocr" / "OCR_INFO.json", "{}")
        for stage in ("info", "zip"):
            for content, label in ((None, "없음"), ({"ok": False}, "실패"), ({}, "빈 값"), ({"ok": "true"}, "글자 true")):
                with self.subTest(stage=stage, check=label):
                    self.calls.clear()
                    result = Path(self.out) / "check_result.json"
                    if result.exists():
                        result.unlink()
                    if content is not None:
                        write(result, json.dumps(content))
                    code, err = self.run_main([stage, "--out-dir", self.out])
                    self.assertEqual((code, self.calls), (2, []))
                    self.assertIn("점검", err)
        write(Path(self.out) / "check_result.json", json.dumps({"ok": True}))
        self.calls.clear()
        self.assertEqual(self.run_main(["zip", "--out-dir", self.out])[0], 0)
        self.assertEqual(self.calls, ["zip"])

    def test_a_stage_that_stops_the_build_ends_it_with_two_and_the_rest_is_skipped(self):
        with mock.patch.object(build, "freeze", side_effect=build.BuildError("PyInstaller 가 실패했다")), mock.patch.object(build, "source_state", return_value=dict(STATE)), \
                mock.patch.object(build, "check") as check, mock.patch.object(build, "log"), mock.patch.object(sys.stderr, "write") as write_err:
            code = build.main(["all", "--out-dir", self.out, "--models-dir", str(self.root / "m")])
        self.assertEqual(code, 2)
        check.assert_not_called()
        self.assertIn("PyInstaller", "".join(call.args[0] for call in write_err.call_args_list))

    def test_the_script_has_no_switch_that_turns_a_check_off(self):
        source = support.read("ocr_addon/build_ocr_addon.py")
        for word in ("--no-selftest", "--no-remove", "--skip-check", "--variant", "--extra-exclude", "--allow-missing"):
            self.assertNotIn(word, source, word)
        self.assertEqual(build.BUNDLE_DIR, "ocr")
        self.assertEqual(build.BUNDLE_NAME, "ocr_addon")


class OutDirTest(unittest.TestCase):
    def setUp(self):
        self.folder, self.root = temp()
        self.addCleanup(self.folder.cleanup)

    def test_a_new_folder_gets_the_marker_and_a_marked_folder_is_cleaned_of_old_results_only(self):
        out = self.root / "out"
        made = build.prepare_out_dir(str(out))
        self.assertEqual(Path(made), out.resolve())
        self.assertTrue((out / build.OUT_MARKER).is_file())
        for name in build.OUT_SUBFOLDERS:
            write(out / name / "old.txt", "old")
        write(out / "check_result.json", "{}")
        write(out / "pe_imports_all.json", "[]")
        build.prepare_out_dir(str(out))
        self.assertEqual(sorted(p.name for p in out.iterdir()), sorted([build.OUT_MARKER, "pe_imports_all.json"]), "이전 하위 폴더·점검 결과는 지우고 표지는 남긴다")

    def test_the_hand_over_files_of_an_earlier_build_including_the_geos_record_do_not_survive_a_new_build(self):
        """단계 사이에 건네는 기록(freeze_meta·removed·check_result·geos)은 새 빌드의 freeze 가 지운다 — 앞선 빌드의 GEOS 기록이 새 빌드의 정보 파일에 새지 않게."""
        out = self.root / "out"
        build.prepare_out_dir(str(out))
        names = ("freeze_meta.json", "removed.json", "check_result.json", build.GEOS_RECORD)
        for name in names:
            write(out / name, "{}")
        build.prepare_out_dir(str(out))
        for name in names:
            self.assertFalse((out / name).exists(), name)
        self.assertTrue((out / build.OUT_MARKER).is_file())

    def test_a_folder_that_is_not_ours_and_not_empty_is_refused_and_nothing_is_deleted(self):
        out = self.root / "mine"
        write(out / "dist" / "keep.txt", "내 파일")
        with self.assertRaises(build.BuildError) as caught:
            build.prepare_out_dir(str(out))
        self.assertIn(build.OUT_MARKER, str(caught.exception))
        self.assertEqual((out / "dist" / "keep.txt").read_bytes(), "내 파일".encode("utf-8"))
        self.assertFalse((out / build.OUT_MARKER).exists())

    def test_an_empty_existing_folder_is_fine_and_a_file_path_is_refused(self):
        empty = self.root / "empty"
        empty.mkdir()
        build.prepare_out_dir(str(empty))
        self.assertTrue((empty / build.OUT_MARKER).is_file())
        write(self.root / "afile", "x")
        with self.assertRaises(build.BuildError):
            build.prepare_out_dir(str(self.root / "afile"))

    def test_the_repository_itself_and_its_parent_are_refused(self):
        for bad in (str(ROOT), str(ROOT.parent)):
            with self.subTest(bad=bad):
                with self.assertRaises(Exception) as caught:
                    build.prepare_out_dir(bad)
                self.assertIn(type(caught.exception).__name__, ("BuildError", "BuildRefused"))


class AssembleTest(unittest.TestCase):
    def setUp(self):
        self.folder, self.root = temp()
        self.addCleanup(self.folder.cleanup)
        self.out, self.models, self.data = self.root / "out", self.root / "models", self.root / "data"
        for key, payload in FAKE.items():
            write((self.models if key.startswith("models/") else self.data) / Path(*key.split("/")[1:]), payload)
        write(self.data / "ppocrv5_korean_dict.info.json", "{}")
        for item in (mock.patch.object(build, "log"), mock.patch.object(build, "load_lock", return_value=(FAKE_LOCK, FAKE_EXPECTED)), mock.patch.object(build, "DATA_DIR", str(self.data))):
            item.start()
            self.addCleanup(item.stop)

    def test_good_files_are_laid_into_the_bundle_with_the_dictionary_info(self):
        build.assemble(str(self.out), str(self.models))
        dist = self.out / "dist" / "ocr"
        for key, payload in FAKE.items():
            self.assertEqual((dist / Path(*key.split("/"))).read_bytes(), payload)
        self.assertTrue((dist / "data" / "ppocrv5_korean_dict.info.json").is_file())

    def test_the_provenance_record_stays_in_the_repository_and_never_enters_the_bundle(self):
        """사전 출처 기록(provenance.json)은 저장소에만 둔다 — 묶음에 들어가면 묶음 바이트가 바뀌고 앱의 폴더 확인이 모르는 파일로 읽을 수 있다."""
        write(self.data / "ppocrv5_korean_dict.provenance.json", "{}")
        build.assemble(str(self.out), str(self.models))
        self.assertEqual(sorted(path.name for path in (self.out / "dist" / "ocr" / "data").iterdir()), ["ppocrv5_korean_dict.info.json", "ppocrv5_korean_dict.txt"])

    def test_a_wrong_size_a_wrong_hash_or_a_missing_file_stops_the_build(self):
        for key in FAKE:
            folder = self.models if key.startswith("models/") else self.data
            path = folder / Path(*key.split("/")[1:])
            original = path.read_bytes()
            for label, payload in (("크기", original + b"x"), ("해시", bytes(len(original))), ("없음", None)):
                with self.subTest(key=key, what=label):
                    if payload is None:
                        path.unlink()
                    else:
                        path.write_bytes(payload)
                    with self.assertRaises(build.BuildError) as caught:
                        build.assemble(str(self.out), str(self.models))
                    self.assertIn(key, str(caught.exception))
                    path.write_bytes(original)


class SelftestRunTest(unittest.TestCase):
    """run_selftest — 가짜 실행 파일(subprocess.run 을 바꿔 끼운다)이 묶음 폴더나 임시 폴더에 쓰면 알아채는가."""

    def setUp(self):
        self.folder, self.root = temp()
        self.addCleanup(self.folder.cleanup)
        self.out = self.root / "out"
        self.dst = self.out / "dist" / "ocr"
        write(self.dst / "ocr_worker.exe", b"exe")
        write(self.dst / "_internal" / "x.pyd", b"pyd")

    def run_with(self, behaviour, stdout=b'{"ok": true, "frozen": true}\n', returncode=0):
        def fake(command, **kwargs):
            behaviour(Path(kwargs["env"]["TEMP"]), kwargs)
            return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=b"")
        with mock.patch.object(subprocess, "run", side_effect=fake) as runner:
            result = build.run_selftest(str(self.out), str(self.dst))
        return result, runner

    def test_a_quiet_run_returns_the_report_and_no_extra_problem(self):
        (code, report, problems, seconds, _tail), runner = self.run_with(lambda tmp, kw: None)
        self.assertEqual((code, report, problems), (0, {"ok": True, "frozen": True}, []))
        self.assertIsInstance(seconds, float)
        command = runner.call_args.args[0]
        self.assertEqual(command[1:], ["--selftest"])
        self.assertEqual(runner.call_args.kwargs["cwd"], str(self.dst))
        limit = runner.call_args.kwargs["timeout"]
        self.assertTrue(isinstance(limit, (int, float)) and 0 < limit <= 600, "멈춘 exe 가 작업 제한 시간(45분)까지 붙잡지 않는다(독립 검증 Q 의 QP-2)")

    def test_the_temporary_folder_is_a_fresh_empty_folder_given_through_both_names(self):
        seen = {}

        def behaviour(tmp, kwargs):
            seen["listing"] = sorted(os.listdir(tmp))
            seen["temp"], seen["tmp"] = kwargs["env"]["TEMP"], kwargs["env"]["TMP"]
        write(self.out / "selftest_tmp" / "stale.txt", "남은 파일")
        self.run_with(behaviour)
        self.assertEqual(seen["listing"], [], "지난번 임시 파일이 남아 있지 않다")
        self.assertEqual(seen["temp"], seen["tmp"])
        self.assertEqual(Path(seen["temp"]), self.out / "selftest_tmp")

    def test_a_file_written_inside_the_bundle_is_a_problem(self):
        for label, action in (("새 파일", lambda tmp, kw: write(self.dst / "new.log", "x")), ("바뀐 파일", lambda tmp, kw: write(self.dst / "_internal" / "x.pyd", b"pyd-changed-longer")),
                              ("지운 파일", lambda tmp, kw: (self.dst / "_internal" / "x.pyd").unlink())):
            with self.subTest(what=label):
                write(self.dst / "_internal" / "x.pyd", b"pyd")
                write(self.dst / "ocr_worker.exe", b"exe")
                if (self.dst / "new.log").exists():
                    (self.dst / "new.log").unlink()
                (_code, _report, problems, _s, _t), _runner = self.run_with(action)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("묶음 폴더 안의 파일을 바꿨다", problems[0])

    def test_a_file_left_in_the_temporary_folder_is_a_problem(self):
        (_code, _report, problems, _s, _t), _runner = self.run_with(lambda tmp, kw: write(tmp / "cache.bin", b"x"))
        self.assertEqual(len(problems), 1)
        self.assertIn("임시 폴더", problems[0])

    def test_unreadable_output_gives_no_report_and_the_exit_code_is_passed_on(self):
        for out in (b"", b"not json\n", b"[1, 2\n"):
            with self.subTest(out=out):
                (code, report, problems, _s, _t), _runner = self.run_with(lambda tmp, kw: None, stdout=out, returncode=6)
                self.assertEqual((code, report, problems), (6, None, []))


class SourceStateTest(unittest.TestCase):
    def setUp(self):
        self.folder, self.root = temp()
        self.addCleanup(self.folder.cleanup)

    def make_repo(self, epoch=1794873600):
        repo = self.root / "repo"
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
                   GIT_AUTHOR_DATE="%d +0000" % epoch, GIT_COMMITTER_DATE="%d +0000" % epoch)
        repo.mkdir()
        write(repo / "ocr_addon" / "a.txt", "a")
        write(repo / "VERSION", "0.1.0-preview.1\n")
        for args in (["init", "-q"], ["add", "-A"], ["-c", "commit.gpgsign=false", "commit", "-q", "-m", "m"]):
            done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=env)
            assert done.returncode == 0, done.stderr
        return repo

    @unittest.skipUnless(HAVE_GIT, "git 이 없다")
    def test_the_time_is_the_commit_time_unless_source_date_epoch_is_given_and_a_dirty_folder_is_noticed(self):
        repo = self.make_repo()
        with mock.patch.object(build, "REPO", str(repo)), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOURCE_DATE_EPOCH", None)
            state = build.source_state()
            self.assertEqual((state["epoch"], state["epoch_from"], state["committed_utc"], state["clean"]), (1794873600, "git commit", "2026-11-17T00:00:00Z", True))
            self.assertRegex(state["commit"], r"^[0-9a-f]{40}$")
            os.environ["SOURCE_DATE_EPOCH"] = "1700000000"
            given = build.source_state()
            self.assertEqual((given["epoch"], given["epoch_from"], given["committed_utc"]), (1700000000, "SOURCE_DATE_EPOCH", "2023-11-14T22:13:20Z"))
            os.environ["SOURCE_DATE_EPOCH"] = "yesterday"
            with self.assertRaises(build.BuildError):
                build.source_state()
            os.environ.pop("SOURCE_DATE_EPOCH")
            write(repo / "ocr_addon" / "new.txt", "새 파일")
            dirty = build.source_state()
            self.assertEqual((dirty["clean"], dirty["dirty_count"]), (False, 1))

    @unittest.skipUnless(HAVE_GIT, "git 이 없다")
    def test_a_changed_version_file_or_a_changed_tracked_file_alone_makes_the_folder_dirty(self):
        """깨끗함 판정의 경로는 ocr_addon 폴더와 VERSION 이다 — VERSION 만 바뀌어도(zip 이름이 바뀐다), 이미 추적 중인 파일만 바뀌어도 더럽다고 읽는다(독립 검증 S 의 SP-3)."""
        repo = self.make_repo()
        with mock.patch.object(build, "REPO", str(repo)), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOURCE_DATE_EPOCH", None)
            self.assertTrue(build.source_state()["clean"])
            write(repo / "VERSION", "0.1.1-preview.1\n")
            only_version = build.source_state()
            self.assertEqual((only_version["clean"], only_version["dirty_count"]), (False, 1))
            subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--", "VERSION"], check=True, capture_output=True)
            self.assertTrue(build.source_state()["clean"])
            write(repo / "ocr_addon" / "a.txt", "바뀐 내용")
            only_tracked = build.source_state()
            self.assertEqual((only_tracked["clean"], only_tracked["dirty_count"]), (False, 1))

    @unittest.skipUnless(HAVE_GIT, "git 이 없다")
    def test_a_folder_that_is_not_a_git_repository_is_refused_in_plain_words(self):
        with mock.patch.object(build, "REPO", str(self.root)):
            with self.assertRaises(build.BuildError):
                build.source_state()

    def test_the_real_version_file_makes_a_valid_zip_name(self):
        self.assertRegex(build.read_version(), r"^\d+\.\d+\.\d+")
        self.assertTrue(rules.zip_name(build.read_version()).startswith("ChanceBlogDesktop-OCR-"))

    def test_a_bad_version_file_is_refused_and_a_bom_and_a_newline_are_tolerated(self):
        with mock.patch.object(build, "REPO", str(self.root)):
            for bad in ("", "1.0", "../x", "v1.2.3", "1.2.3 beta", "1.2.3/x"):
                with self.subTest(bad=bad):
                    write(self.root / "VERSION", bad)
                    with self.assertRaises(ValueError):
                        build.read_version()
            write(self.root / "VERSION", chr(0xFEFF) + "0.2.0-preview.3\r\n")
            self.assertEqual(build.read_version(), "0.2.0-preview.3")


class FreezeTest(unittest.TestCase):
    """freeze — PyInstaller 를 부르는 명령과 환경(좁힌 PATH·고정 시각·해시 씨앗)을 가짜 실행으로 본다."""

    def setUp(self):
        self.folder, self.root = temp()
        self.addCleanup(self.folder.cleanup)
        self.out = self.root / "out"
        self.out.mkdir()

    def freeze_with(self, returncode=0, epoch=1794873600):
        seen = {}

        def fake(command, **kwargs):
            seen["command"], seen["kwargs"] = command, kwargs
            write(Path(kwargs["cwd"]) / "dist" / "ocr_worker" / "ocr_worker.exe", b"exe")
            write(Path(kwargs["cwd"]) / "dist" / "ocr_worker" / "_internal" / "x.pyd", b"pyd")
            return subprocess.CompletedProcess(command, returncode)
        with mock.patch.dict(os.environ, {"PATH": "C:/fake_java/bin;C:/other/tools", "PYTHONPATH": "C:/planted", "PYTHONHOME": "C:/planted_home"}), \
                mock.patch.object(build, "log"), mock.patch.object(subprocess, "run", side_effect=fake):
            build.freeze(str(self.out), epoch)
        return seen

    def test_the_command_freezes_one_folder_without_upx_and_leaves_out_the_network_parts(self):
        seen = self.freeze_with()
        command = seen["command"]
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1:7], ["-s", "-B", "-X", "utf8", "-m", "PyInstaller"])
        for flag in ("--onedir", "--console", "--noupx", "--noconfirm", "--clean"):
            self.assertIn(flag, command)
        excluded = [command[index + 1] for index, item in enumerate(command) if item == "--exclude-module"]
        for name in ("ssl", "_ssl", "_hashlib", "asyncio", "multiprocessing", "_overlapped", "_multiprocessing", "urllib3", "certifi", "idna", "charset_normalizer", "tkinter", "setuptools", "pip"):
            self.assertIn(name, excluded, name)
        stubs = os.path.join(build.HERE, "stubs")
        self.assertIn(stubs, command, "가짜 requests 폴더가 검색 경로에 있다")
        self.assertTrue(command[-1].endswith("worker_main.py"))
        self.assertEqual(seen["kwargs"]["cwd"], str(self.out))
        self.assertGreater(seen["kwargs"]["timeout"], 0)

    def test_pyinstaller_gets_a_narrowed_path_a_fixed_clock_and_a_fixed_hash_seed(self):
        env = self.freeze_with(epoch=1794873600)["kwargs"]["env"]
        self.assertEqual((env["SOURCE_DATE_EPOCH"], env["PYTHONHASHSEED"], env["PYTHONUTF8"], env["PYTHONDONTWRITEBYTECODE"]), ("1794873600", "0", "1", "1"))
        self.assertNotIn("fake_java", env["PATH"], "러너 PATH 의 자바 같은 폴더가 PyInstaller 의 DLL 찾기에 끼어들지 못한다")
        self.assertNotIn("other", env["PATH"])
        for name in ("PYTHONPATH", "PYTHONHOME"):
            self.assertNotIn(name, env)

    def test_the_finished_folder_is_renamed_to_ocr_and_the_run_is_recorded(self):
        self.freeze_with()
        self.assertTrue((self.out / "dist" / "ocr" / "ocr_worker.exe").is_file())
        self.assertFalse((self.out / "dist" / "ocr_worker").exists())
        meta = json.loads((self.out / "freeze_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["path_policy"], "narrow-v1")
        self.assertTrue((self.out / "gen" / "buildinfo.py").is_file())

    def test_a_failed_pyinstaller_stops_the_build_without_leaving_a_half_bundle(self):
        with self.assertRaises(build.BuildError):
            self.freeze_with(returncode=1)
        self.assertFalse((self.out / "dist" / "ocr").exists())


class BundledModulesTest(unittest.TestCase):
    """bundled_modules — R3 의 입력(묶음에 실제 들어간 부품 이름)을 읽는 함수. PyInstaller 가 없는 곳에서도 돌도록 PYZ 보관소 읽기만 모의하고 폴더 목록은 진짜 폴더로 읽는다(독립 검증 S 의 SP-3)."""

    def setUp(self):
        self.folder, self.root = temp()
        self.addCleanup(self.folder.cleanup)
        self.out = self.root / "out"
        write(self.out / "dist" / "ocr" / "ocr_worker.exe", b"x")
        write(self.out / "dist" / "ocr" / "_internal" / "_socket.pyd", b"x")
        write(self.out / "dist" / "ocr" / "_internal" / "certifi" / "cacert.pem", b"x")

    def fake_pyinstaller(self, toc=(), error=None):
        class Reader:
            def __init__(self, path):
                if error is not None:
                    raise error
                self.toc = list(toc)
        readers = types.ModuleType("PyInstaller.archive.readers")
        readers.ZlibArchiveReader = Reader
        return mock.patch.dict(sys.modules, {"PyInstaller": types.ModuleType("PyInstaller"), "PyInstaller.archive": types.ModuleType("PyInstaller.archive"), "PyInstaller.archive.readers": readers})

    def test_the_names_come_from_the_pyz_archive_the_internal_folder_and_the_top_folder(self):
        with self.fake_pyinstaller(toc=["protocol", "pkg.sub.mod", "pkg.other", "requests"]):
            names = build.bundled_modules(str(self.out))
        self.assertEqual(names, {"protocol", "pkg", "requests", "_socket.pyd", "certifi", "ocr_worker.exe", "_internal"})

    def test_an_unreadable_pyz_archive_stops_the_build_instead_of_checking_nothing(self):
        for error in (OSError("no file"), ValueError("bad archive"), ImportError("no pyinstaller")):
            with self.subTest(error=type(error).__name__):
                with self.fake_pyinstaller(error=error):
                    with self.assertRaises(build.BuildError):
                        build.bundled_modules(str(self.out))


class PeRowsTest(unittest.TestCase):
    """pe_rows — R1 의 입력(가져오기 표)을 읽는 함수. pefile 이 없는 앱 CI 에서도 돌도록 가짜 pefile 모듈을 끼워, 정적·지연·묶음 가져오기 표를 모두 읽는지와 어떤 파일을 훑는지를 본다(독립 검증 Q 의 QP-1)."""

    class Entry:
        def __init__(self, dll=None, name=None):
            self.dll, self.name = dll, name

    def setUp(self):
        self.folder, self.root = temp()
        self.addCleanup(self.folder.cleanup)
        self.asked = []

    def fake_pefile(self, table, broken=()):
        asked = self.asked

        class FakePE:
            def __init__(self, path, fast_load=False):
                name = os.path.basename(path)
                if name in broken:
                    raise ValueError("not a PE file")
                for key, value in table.get(name, {}).items():
                    setattr(self, key, value)

            def parse_data_directories(self, directories=None):
                asked.append(sorted(directories))

            def close(self):
                pass
        module = types.ModuleType("pefile")
        module.PE = FakePE
        module.DIRECTORY_ENTRY = {"IMAGE_DIRECTORY_ENTRY_IMPORT": 1, "IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT": 13, "IMAGE_DIRECTORY_ENTRY_BOUND_IMPORT": 11}
        return mock.patch.dict(sys.modules, {"pefile": module})

    def test_static_delay_and_bound_import_tables_all_end_up_in_the_row_lowercased_and_deduplicated(self):
        entry = self.Entry
        table = {"a.pyd": {"DIRECTORY_ENTRY_IMPORT": [entry(dll=b"KERNEL32.dll"), entry(dll=b"kernel32.DLL"), entry(dll=b"WS2_32.dll")], "DIRECTORY_ENTRY_DELAY_IMPORT": [entry(dll=b"WinHTTP.dll")],
                           "DIRECTORY_ENTRY_BOUND_IMPORT": [entry(name=b"WININET.dll")]}, "b.dll": {}}
        for name in ("a.pyd", "b.dll"):
            write(self.root / name, b"x" * (3 if name == "a.pyd" else 5))
        with self.fake_pefile(table):
            rows, errors = build.pe_rows(str(self.root))
        by = {row["path"]: row for row in rows}
        self.assertEqual(errors, [])
        self.assertEqual(sorted(by), ["a.pyd", "b.dll"])
        self.assertEqual((by["a.pyd"]["imports"], by["a.pyd"]["delay"], by["a.pyd"]["bound"], by["a.pyd"]["bytes"]), (["kernel32.dll", "ws2_32.dll"], ["winhttp.dll"], ["wininet.dll"], 3))
        self.assertEqual((by["b.dll"]["imports"], by["b.dll"]["delay"], by["b.dll"]["bound"], by["b.dll"]["bytes"]), ([], [], [], 5))
        self.assertEqual(self.asked, [[1, 11, 13]] * 2, "세 가져오기 표(정적·묶음·지연)를 모두 읽어 달라고 한다")
        for row in rows:
            self.assertEqual(sorted(row), ["bound", "bytes", "delay", "imports", "path"], "규칙 함수가 읽는 줄 모양 그대로다")

    def test_a_network_library_in_a_delay_or_bound_table_reaches_rule_r1(self):
        entry = self.Entry
        table = {"late.pyd": {"DIRECTORY_ENTRY_DELAY_IMPORT": [entry(dll=b"WinHTTP.dll")]}, "tied.pyd": {"DIRECTORY_ENTRY_BOUND_IMPORT": [entry(name=b"WS2_32.dll")]}}
        for name in table:
            write(self.root / name, b"x")
        with self.fake_pefile(table):
            rows, errors = build.pe_rows(str(self.root))
        problems = [item for item in rules.pe_problems(rows, errors) if "허용 예외 밖" in item]
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("late.pyd" in item and "winhttp.dll" in item for item in problems))
        self.assertTrue(any("tied.pyd" in item and "ws2_32.dll" in item for item in problems))

    def test_only_exe_dll_and_pyd_files_are_read_in_any_letter_case_and_depth_and_unreadable_ones_are_reported(self):
        names = ["x.exe", "sub/y.DLL", "sub/deep/z.Pyd", "note.txt", "data.bin", "noext", "sub/readme.dll.txt", "bad.pyd"]
        for name in names:
            write(self.root / Path(*name.split("/")), b"x")
        with self.fake_pefile({}, broken=("bad.pyd",)):
            rows, errors = build.pe_rows(str(self.root))
        self.assertEqual(sorted(row["path"] for row in rows), ["sub/deep/z.Pyd", "sub/y.DLL", "x.exe"])
        self.assertEqual(errors, ["bad.pyd (ValueError)"])


class RemoveUnusedTest(unittest.TestCase):
    """remove_unused — 쓰지 않는 기본 모델 3개·FFmpeg DLL·인증서 파일만 지우고 우리 모델·설정·작업자는 남긴다(독립 검증 Q 의 QP-2: 이 함수를 부르는 시험이 없었다)."""

    def test_default_models_ffmpeg_and_cacert_go_and_our_models_and_settings_stay(self):
        folder, root = temp()
        self.addCleanup(folder.cleanup)
        dist = root / "out" / "dist" / "ocr"
        gone = ["_internal/rapidocr/models/PP-OCRv6_det_small.onnx", "_internal/rapidocr/models/ch_ppocr_mobile_v2.0_cls_mobile.onnx", "_internal/cv2/opencv_videoio_ffmpeg500_64.dll", "_internal/certifi/cacert.pem"]
        kept = ["models/det/inference.onnx", "models/rec/inference.onnx", "data/ppocrv5_korean_dict.txt", "_internal/rapidocr/config.yaml", "_internal/cv2/cv2.pyd", "_internal/certifi/other.txt", "ocr_worker.exe"]
        for name in gone + kept:
            write(dist / Path(*name.split("/")), b"xyz")
        with mock.patch.object(build, "log"):
            build.remove_unused(str(root / "out"))
        for name in gone:
            self.assertFalse((dist / Path(*name.split("/"))).exists(), name)
        for name in kept:
            self.assertTrue((dist / Path(*name.split("/"))).exists(), name)
        removed = json.loads((root / "out" / "removed.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(item["path"] for item in removed), sorted(gone))
        self.assertTrue(all(item["bytes"] == 3 and item["what"] for item in removed))

    def test_nothing_to_remove_leaves_an_empty_record_and_the_bundle_untouched(self):
        folder, root = temp()
        self.addCleanup(folder.cleanup)
        dist = root / "out" / "dist" / "ocr"
        write(dist / "ocr_worker.exe", b"x")
        with mock.patch.object(build, "log"):
            build.remove_unused(str(root / "out"))
        self.assertEqual(json.loads((root / "out" / "removed.json").read_text(encoding="utf-8")), [])
        self.assertTrue((dist / "ocr_worker.exe").is_file())


class NormalizeBaseLibraryTest(unittest.TestCase):
    """normalize_base_library — base_library.zip 의 항목 순서를 이름 순으로 고정하되 내용·시각은 그대로 둔다(재현 빌드의 한 조각 — 독립 검증 Q 의 QP-2)."""

    def test_entries_are_sorted_by_name_and_nothing_is_lost_or_changed(self):
        folder, root = temp()
        self.addCleanup(folder.cleanup)
        path = root / "base_library.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name in ("c.pyc", "a.pyc", "b.pyc"):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 2, 3, 4, 6))
                info.external_attr = 0o600 << 16
                archive.writestr(info, name.encode())
        build.normalize_base_library(str(path))
        with zipfile.ZipFile(path) as archive:
            self.assertEqual([item.filename for item in archive.infolist()], ["a.pyc", "b.pyc", "c.pyc"])
            self.assertEqual({item.filename: archive.read(item) for item in archive.infolist()}, {"a.pyc": b"a.pyc", "b.pyc": b"b.pyc", "c.pyc": b"c.pyc"})
            self.assertEqual({item.date_time for item in archive.infolist()}, {(2026, 1, 2, 3, 4, 6)})
            self.assertEqual({item.external_attr for item in archive.infolist()}, {0o600 << 16})
        self.assertFalse(os.path.exists(str(path) + ".tmp"), "임시 파일이 남지 않는다")

    def test_a_missing_file_is_left_alone_and_the_same_input_gives_the_same_bytes_twice(self):
        folder, root = temp()
        self.addCleanup(folder.cleanup)
        build.normalize_base_library(str(root / "none.zip"))
        self.assertFalse((root / "none.zip").exists())
        first = []
        for order in (("b.pyc", "a.pyc"), ("a.pyc", "b.pyc")):
            path = root / ("base-%s.zip" % "".join(name[0] for name in order))
            with zipfile.ZipFile(path, "w") as archive:
                for name in order:
                    archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 2, 3, 4, 6)), name.encode())
            build.normalize_base_library(str(path))
            first.append(path.read_bytes())
        self.assertEqual(first[0], first[1], "항목 순서가 달랐던 두 압축 파일이 정리 뒤에는 바이트까지 같다")


class BorrowedMainFunctionsTest(unittest.TestCase):
    """이 빌드는 본체 packaging/build_package.py 의 함수 몇 개를 읽기 전용으로 가져다 쓴다 — 본체에서 이름이나 동작이 바뀌면 여기서 알아챈다(본체 코드는 고치지 않는다)."""

    def test_the_borrowed_names_exist_and_the_narrowing_behaves(self):
        bp = build.import_packaging()
        for name in ("safe_out_dir", "pyinstaller_env", "check_binary_origins", "PATH_SEPARATOR", "PATH_POLICY", "pc"):
            self.assertTrue(hasattr(bp, name), name)
        self.assertTrue(callable(bp.pc.forbidden_name))
        self.assertEqual(bp.PATH_POLICY, "narrow-v1")
        env = bp.pyinstaller_env(5, {"PATH": "C:/java/bin;C:/git/bin", "Path": "C:/more", "PYTHONPATH": "C:/p", "SystemRoot": "C:/Windows"})
        self.assertEqual((env["SOURCE_DATE_EPOCH"], env["PYTHONHASHSEED"]), ("5", "0"))
        self.assertNotIn("java", env["PATH"])
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(bp.pc.forbidden_name("_internal/certifi/cacert.pem") != "", True)
        self.assertEqual(bp.pc.forbidden_name("_internal/rapidocr/config.yaml"), "")


class InfoAndZipTest(unittest.TestCase):
    """make_info·make_zip — 가짜 묶음 폴더에서. 정보 파일은 앱의 `service/ocr_addon.py` 가 ok 로 읽어야 한다."""

    def setUp(self):
        self.folder, self.root = temp()
        self.addCleanup(self.folder.cleanup)
        self.out = self.root / "out"
        self.dist = self.out / "dist" / "ocr"
        write(self.dist / "ocr_worker.exe", b"worker-bytes")
        write(self.dist / "_internal" / "base_library.zip", b"base")
        for key, payload in FAKE.items():
            write(self.dist / Path(*key.split("/")), payload)
        for key, payload in NOTICE_FILES.items():                # notices 단계가 점검 앞에서 만들어 둔 고지 산출물과 GEOS 기록(geos.json, 묶음 밖)
            write(self.dist / Path(*key.split("/")), payload)
        write(self.out / build.GEOS_RECORD, json.dumps(GEOS))
        write(self.out / "check_result.json", json.dumps({"ok": True, "problems": [], "pe_files_checked": 3, "selftest": {"ok": True}, "selftest_exit": 0}))
        write(self.out / "removed.json", json.dumps([{"what": "x", "path": "p", "bytes": 1}]))
        pins = rules.parse_lock(support.read("ocr_addon/requirements-ocr.lock"))
        self.patches = [mock.patch.object(build, "log"), mock.patch.object(build, "load_lock", return_value=(FAKE_LOCK, FAKE_EXPECTED)), mock.patch.object(build, "bundled_modules", return_value={"cv2", "numpy", "PIL", "colorama", "requests"}),       # 묶음에는 가짜 requests 한 모듈이 requests 라는 이름으로 든다
                        mock.patch.object(build, "installed_version", side_effect=lambda name: next((pin["version"] for pin in pins if pin["name"] == rules.canon(name)), "9.9")),
                        mock.patch.object(build, "pypi_license", return_value="MIT")]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_the_info_file_lists_every_file_but_itself_and_the_app_reads_the_folder_as_ok(self):
        info = build.make_info(str(self.out), STATE, "0.1.0-preview.1")
        on_disk = json.loads((self.dist / "OCR_INFO.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["files"], info["files"])
        listed = {item["path"] for item in info["files"]}
        self.assertNotIn("OCR_INFO.json", listed)
        self.assertEqual(listed, {"ocr_worker.exe", "_internal/base_library.zip", *FAKE, *NOTICE_FILES})
        self.assertNotIn(build.GEOS_RECORD, listed, "geos.json 은 묶음 밖(out 폴더) 기록이다 — 압축 파일에 들어가지 않는다")
        self.assertTrue(all(len(item["sha256"]) == 64 and item["bytes"] > 0 for item in info["files"]))
        self.assertEqual((on_disk["name"], on_disk["proto"], on_disk["variant"], on_disk["version"]), ("ocr_addon", 1, "inner", "0.1.0-preview.1"))
        sys.path.insert(0, str(ROOT / "src"))
        try:
            from chanceblog_desktop.service import ocr_addon as app_side
        finally:
            sys.path.remove(str(ROOT / "src"))
        with mock.patch.object(app_side, "EMBEDDED_FILES", FAKE_EXPECTED):
            status = app_side.verify(str(self.dist))
        self.assertEqual((status.state, status.problems), ("ok", ()), "앱의 추가 도구 확인이 이 폴더를 ok 로 읽는다")
        self.assertIn("rapidocr 3.10.0", status.version)

    def test_the_info_file_records_the_pins_the_commit_the_checks_and_the_requests_stand_in(self):
        info = build.make_info(str(self.out), STATE, "0.1.0-preview.1")
        packages = {item["name"]: item for item in info["packages"]}
        self.assertEqual(len(packages), 21)
        self.assertTrue(packages["requests"]["replaced_by_offline_stub"])
        self.assertFalse(packages["requests"]["bundled_in_dist"])
        self.assertTrue(packages["numpy"]["bundled_in_dist"])
        self.assertTrue(packages["pillow"]["bundled_in_dist"])
        self.assertFalse(packages["urllib3"]["bundled_in_dist"])
        self.assertEqual(packages["numpy"]["wheel_sha256"], next(pin["hashes"][0] for pin in rules.parse_lock(support.read("ocr_addon/requirements-ocr.lock")) if pin["name"] == "numpy"))
        self.assertGreaterEqual(min(item["age_days_at_build"] for item in info["packages"]), 14)
        self.assertEqual(info["source"], {"commit": STATE["commit"], "committed_utc": STATE["committed_utc"], "clean": True, "time_from": "git commit"})
        self.assertEqual(info["checks"]["rules"], ["R1", "R2", "R3", "R4"])
        self.assertTrue(info["checks"]["ok"])
        self.assertEqual(info["checks"]["pe_exceptions_allowed"], list(rules.PE_EXCEPTIONS))
        self.assertEqual(sorted(info["lock_sha256"]), ["models.lock.json", "requirements-build.txt", "requirements-ocr.lock", "requirements-ocr.meta.json"])
        self.assertIn("공개 배포용이 아닙니다", info["notice"])
        self.assertLess(len(json.dumps(info).encode("utf-8")), 2 * 1024 * 1024, "앱이 읽는 정보 파일의 상한(2MB)")

    def test_the_info_file_text_is_the_same_for_the_same_input(self):
        build.make_info(str(self.out), STATE, "0.1.0-preview.1")
        first = (self.dist / "OCR_INFO.json").read_bytes()
        build.make_info(str(self.out), STATE, "0.1.0-preview.1")
        self.assertEqual((self.dist / "OCR_INFO.json").read_bytes(), first)
        self.assertEqual(first.count(b"\r"), 0, "줄 끝은 LF — 어느 PC 에서 만들어도 같은 바이트")

    def test_the_info_file_carries_the_geos_record_and_lists_the_notice_files_with_the_hashes_of_the_files_that_already_exist(self):
        """B1 의 `test_the_info_stage_writes_the_notice_and_licenses_first_and_lists_them_with_their_hashes` 의 뜻 — 고지 파일은 정보 파일을 만들기 **전에** 있어야 해시가 맞고 목록에 든다."""
        info = build.make_info(str(self.out), STATE, "0.1.0-preview.1")
        on_disk = json.loads((self.dist / "OCR_INFO.json").read_text(encoding="utf-8"))
        self.assertEqual((info["geos"], on_disk["geos"]), (GEOS, GEOS))
        self.assertEqual(on_disk["license_notes"], build.license_notes(GEOS))
        self.assertNotIn("방식 미정", json.dumps(on_disk["license_notes"], ensure_ascii=False))
        by_path = {item["path"]: item for item in on_disk["files"]}
        for key in NOTICE_FILES:
            data = (self.dist / Path(*key.split("/"))).read_bytes()
            self.assertEqual((by_path[key]["bytes"], by_path[key]["sha256"]), (len(data), hashlib.sha256(data).hexdigest()), key)
        self.assertEqual(build.missing_outputs(list(by_path)), [])
        self.assertEqual(on_disk["file_count"], len(by_path))

    def test_the_info_stage_needs_the_geos_record_of_the_notices_stage_and_writes_no_info_file_without_it(self):
        (self.out / build.GEOS_RECORD).unlink()
        with self.assertRaises(build.BuildError) as caught:
            build.make_info(str(self.out), STATE, "0.1.0-preview.1")
        self.assertIn(build.GEOS_RECORD, str(caught.exception))
        self.assertFalse((self.dist / "OCR_INFO.json").exists())

    def test_the_info_stage_refuses_to_write_when_the_listing_lacks_a_required_notice_output(self):
        """B1 의 `test_the_info_stage_refuses_to_write_when_the_listing_lacks_the_required_outputs` 의 뜻 — 산출 목록의 마지막 확인. 고지문·licenses/·GEOS 전문 중 하나라도 없으면 정보 파일을 쓰지 않는다."""
        cases = {"THIRD_PARTY_NOTICES.txt": ["THIRD_PARTY_NOTICES.txt"], "licenses": ["licenses/shapely/LICENSE_GEOS", "licenses/numpy/LICENSE.txt"], "geos license": ["licenses/shapely/LICENSE_GEOS"]}
        for label, names in cases.items():
            with self.subTest(case=label):
                self.setUp()
                for name in names:
                    (self.dist / Path(*name.split("/"))).unlink()
                with self.assertRaises(build.BuildError) as caught:
                    build.make_info(str(self.out), STATE, "0.1.0-preview.1")
                wanted = {"THIRD_PARTY_NOTICES.txt": "THIRD_PARTY_NOTICES.txt", "licenses": "licenses/", "geos license": "licenses/shapely/LICENSE_GEOS"}[label]
                self.assertIn(wanted, str(caught.exception))
                self.assertFalse((self.dist / "OCR_INFO.json").exists())

    def test_the_zip_carries_the_notice_files_and_never_the_geos_record(self):
        info = build.make_info(str(self.out), STATE, "0.1.0-preview.1")
        build.make_zip(str(self.out), "0.1.0-preview.1", info)
        with zipfile.ZipFile(self.out / "release" / "ChanceBlogDesktop-OCR-0.1.0-preview.1-win64.zip") as archive:
            names = set(archive.namelist())
        self.assertTrue({"ocr/" + key for key in NOTICE_FILES} <= names)
        self.assertFalse([name for name in names if name.endswith(build.GEOS_RECORD)], "geos.json 은 묶음에 들어가지 않는다")

    def test_the_zip_has_the_ocr_top_folder_fixed_times_and_the_three_side_files(self):
        info = build.make_info(str(self.out), STATE, "0.1.0-preview.1")
        build.make_zip(str(self.out), "0.1.0-preview.1", info)
        release = self.out / "release"
        self.assertEqual(sorted(p.name for p in release.iterdir()), ["ChanceBlogDesktop-OCR-0.1.0-preview.1-win64.zip", "PACKAGE_INFO.json", "SHA256SUMS"])
        zip_path = release / "ChanceBlogDesktop-OCR-0.1.0-preview.1-win64.zip"
        with zipfile.ZipFile(zip_path) as archive:
            names = [item.filename for item in archive.infolist()]
            self.assertEqual(names, sorted(names), "항목은 이름 순")
            self.assertTrue(all(name.startswith("ocr/") for name in names), "맨 위 폴더는 앱이 본체 옆에서 찾는 ocr")
            self.assertIn("ocr/OCR_INFO.json", names)
            self.assertIn("ocr/ocr_worker.exe", names)
            self.assertEqual({item.date_time for item in archive.infolist()}, {(1980, 1, 1, 0, 0, 0)})
        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        self.assertEqual((release / "SHA256SUMS").read_text(encoding="utf-8"), digest + "  " + zip_path.name + "\n")
        outer = json.loads((release / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
        self.assertEqual((outer["variant"], outer["package"]), ("outer", {"name": zip_path.name, "sha256": digest, "bytes": zip_path.stat().st_size}))
        self.assertEqual(outer["files"], info["files"])

    def test_the_same_bundle_gives_the_same_zip_bytes_twice(self):
        info = build.make_info(str(self.out), STATE, "0.1.0-preview.1")
        build.make_zip(str(self.out), "0.1.0-preview.1", info)
        zip_path = self.out / "release" / "ChanceBlogDesktop-OCR-0.1.0-preview.1-win64.zip"
        first = zip_path.read_bytes()
        zip_path.unlink()
        build.make_zip(str(self.out), "0.1.0-preview.1", info)
        self.assertEqual(zip_path.read_bytes(), first)

    def test_the_zip_name_fits_the_allowed_upload_shape_and_a_bad_version_stops_it(self):
        info = build.make_info(str(self.out), STATE, "0.1.0-preview.1")
        with self.assertRaises(ValueError):
            build.make_zip(str(self.out), "../x", info)


class CheckWiringTest(unittest.TestCase):
    """check() — 규칙 함수들을 **빠짐없이, 맞는 입력으로** 부르는가. 묶음을 읽는 부분(가져오기 표·자가 점검·모듈 목록·DLL 출처)은 가짜로 바꿔 끼우고, 한 부분씩 나쁜 입력을 주면
    check 가 실패(False)하고 그 규칙의 문제 글을 돌려주는지 본다 — 규칙 하나를 빼먹는 배선 실수를 잡는다."""

    ROWS = [{"path": "ocr_worker.exe", "imports": ["kernel32.dll"], "delay": [], "bound": []},
            {"path": "_internal/python312.dll", "imports": ["kernel32.dll", "ws2_32.dll"], "delay": [], "bound": []},
            {"path": "_internal/select.pyd", "imports": ["ws2_32.dll"], "delay": [], "bound": []}]
    REPORT = {"frozen": True, "guard_active": True, "negative_control": [{"blocked_and_counted": True}] * 5, "negative_control_attempts": 5, "negative_control_recent_targets_only_test_addresses": True,
              "loopback_not_counted": True, "files_ok": True, "imports": {"requests": "0+offline-stub"}, "imports_failed": [], "selfcheck_ok": True, "guard_attempts_during_normal_read": 0, "ok": True,
              "imports_optional": {name: "없음(묶이지 않음) x" for name in ("ssl", "urllib3", "certifi", "asyncio", "multiprocessing")}}

    def setUp(self):
        self.folder, self.root = temp()
        self.addCleanup(self.folder.cleanup)
        self.out = self.root / "out"
        self.dist = self.out / "dist" / "ocr"
        write(self.dist / "ocr_worker.exe", b"worker")
        write(self.dist / "_internal" / "python312.dll", b"dll")
        write(self.dist / "_internal" / "rapidocr" / "config.yaml", "Global:\n  use_cls: false\n")
        for key, payload in FAKE.items():
            write(self.dist / Path(*key.split("/")), payload)
        for key, payload in NOTICE_FILES.items():                # notices 단계가 점검 앞에서 만든 고지 산출물 — 점검은 이것들도 본다(없으면 실패)
            write(self.dist / Path(*key.split("/")), payload)
        self.rows, self.report, self.names, self.origin, self.extra, self.stderr =[dict(row) for row in self.ROWS], dict(self.REPORT), {"cv2", "numpy", "requests"}, [], [], ""
        self.versions = {pin["name"]: pin["version"] for pin in rules.parse_lock(support.read("ocr_addon/requirements-ocr.lock"))}
        self.calls = {}
        real = build.import_packaging()
        fake_bp = type("FakeBp", (), {"pc": real.pc, "check_binary_origins": staticmethod(lambda toc: self.calls.setdefault("toc", toc) and list(self.origin))})
        patches = [mock.patch.object(build, "log"), mock.patch.object(build, "load_lock", return_value=(FAKE_LOCK, FAKE_EXPECTED)), mock.patch.object(build, "import_packaging", return_value=fake_bp),
                   mock.patch.object(build, "pe_rows", side_effect=lambda dst: self.calls.setdefault("pe", dst) and (self.rows, [])),
                   mock.patch.object(build, "run_selftest", side_effect=lambda out, dst: (0, self.report, list(self.extra), 1.5, self.stderr)),
                   mock.patch.object(build, "bundled_modules", side_effect=lambda out: self.names), mock.patch.object(build, "installed_version", side_effect=lambda name: self.versions.get(name))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def run_check(self):
        return build.check(str(self.out))

    def problems_of(self, **kwargs):
        ok, res = self.run_check()
        return ok, res["problems"]

    def test_a_clean_bundle_passes_and_every_reader_was_asked_with_the_right_place(self):
        ok, res = self.run_check()
        self.assertEqual((ok, res["problems"], res["ok"]), (True, [], True))
        self.assertEqual(self.calls["pe"], str(self.dist))
        self.assertTrue(self.calls["toc"].replace(chr(92), "/").endswith("build/ocr_worker/COLLECT-00.toc"), "DLL 출처 점검은 PyInstaller 의 묶음 목록 파일을 읽는다")
        saved = json.loads((self.out / "check_result.json").read_text(encoding="utf-8"))
        self.assertTrue(saved["ok"])
        self.assertEqual((saved["pe_files_checked"], saved["selftest_exit"]), (3, 0))
        self.assertTrue((self.out / "pe_imports_all.json").is_file())

    def test_each_kind_of_problem_fails_the_check_with_that_rules_message(self):
        def r1():
            self.rows.append({"path": "_internal/_ssl.pyd", "imports": ["ws2_32.dll"], "delay": [], "bound": []})

        def r2_file():
            write(self.dist / "_internal" / "cv2" / "opencv_videoio_ffmpeg500_64.dll", b"x")

        def r2_hash():
            write(self.dist / "models" / "det" / "inference.onnx", b"DET-MODEL")

        def r3_names():
            self.names = self.names | {"certifi"}

        def r3_requests():
            self.report = {**self.report, "imports": {"requests": "2.34.2"}}

        def r3_runtime():
            self.report = {**self.report, "imports_optional": {**self.report["imports_optional"], "ssl": "3.12.0"}}

        def r4_ok():
            self.report = {**self.report, "ok": False}

        def r4_none():
            self.report = None

        def r4_wrote():
            self.extra = ["R4 --selftest 가 묶음 폴더 안의 파일을 바꿨다(약속: 파일을 쓰지 않는다): ['x']"]

        def origin():
            self.origin = ["api-ms-win-core-console-l1-1-0.dll(출처 C:/hostedtoolcache/Java/bin/x.dll)"]

        def key_shape():
            write(self.dist / "_internal" / "notes.txt", "memo CANARY_" + "AI" + "za" + "A" * 35 + " end")

        def forbidden_name():
            write(self.dist / "settings.json", "{}")

        def no_notice():
            (self.dist / "THIRD_PARTY_NOTICES.txt").unlink()

        def no_licenses():
            for name in ("licenses/shapely/LICENSE_GEOS", "licenses/numpy/LICENSE.txt"):
                (self.dist / Path(*name.split("/"))).unlink()

        def no_geos_license():
            (self.dist / "licenses" / "shapely" / "LICENSE_GEOS").unlink()

        def key_in_notice():
            write(self.dist / "THIRD_PARTY_NOTICES.txt", "고지 CANARY_" + "AI" + "za" + "A" * 35 + " end")

        def key_in_license():
            write(self.dist / "licenses" / "numpy" / "LICENSE.txt", "memo CANARY_" + "AI" + "za" + "A" * 35 + " end")

        def forbidden_in_licenses():
            write(self.dist / "licenses" / "x" / "server.key", "x")

        def old_version():
            self.versions = {**self.versions, "numpy": "2.5.5"}

        def missing_package():
            self.versions = {key: value for key, value in self.versions.items() if key != "pillow"}

        cases = {"R1 가져오기 표": (r1, "R1"), "R2 FFmpeg DLL": (r2_file, "R2"), "R2 모델 해시": (r2_hash, "R2"), "R3 certifi": (r3_names, "R3"), "R3 진짜 requests": (r3_requests, "R3"),
                 "R3 동결본이 ssl 을 가져옴": (r3_runtime, "R3"), "R4 ok 아님": (r4_ok, "R4"), "R4 결과 못 읽음": (r4_none, "R4"), "R4 묶음에 씀": (r4_wrote, "묶음 폴더 안의 파일을 바꿨다"),
                 "DLL 출처": (origin, "출처"), "키 모양": (key_shape, "키 모양"), "금지 이름": (forbidden_name, "묶음에 있으면 안 되는 파일"), "설치 판 차이": (old_version, "설치된 판이 잠금 파일과 다르다"),
                 "패키지 빠짐": (missing_package, "설치된 판이 잠금 파일과 다르다"),
                 "고지문 없음": (no_notice, "라이선스 고지 산출물이 없다: THIRD_PARTY_NOTICES.txt"), "licenses 폴더 비었음": (no_licenses, "라이선스 고지 산출물이 없다: licenses/"),
                 "GEOS 라이선스 전문 없음": (no_geos_license, "라이선스 고지 산출물이 없다: licenses/shapely/LICENSE_GEOS"),
                 "고지문 안 키 모양": (key_in_notice, "키 모양"), "licenses 안 키 모양": (key_in_license, "키 모양"), "licenses 안 금지 파일": (forbidden_in_licenses, "묶음에 있으면 안 되는 파일")}
        for name, (mutate, word) in cases.items():
            with self.subTest(case=name):
                self.setUp()                                     # 매번 깨끗한 묶음에서
                mutate()
                ok, problems = self.problems_of()
                self.assertFalse(ok, name)
                self.assertTrue(any(word in item for item in problems), (name, problems))
                self.assertEqual(json.loads((self.out / "check_result.json").read_text(encoding="utf-8"))["ok"], False)

    def test_a_pin_younger_than_fourteen_days_fails_the_check(self):
        meta = json.loads(support.read("ocr_addon/requirements-ocr.meta.json"))
        meta["packages"]["numpy"]["uploaded"] = "2026-11-10"
        path = self.root / "meta.json"
        write(path, json.dumps(meta))
        with mock.patch.object(build, "PIN_META", str(path)):
            ok, problems = self.problems_of()
        self.assertFalse(ok)
        self.assertTrue(any("PyPI 업로드 후" in item for item in problems), problems)

    def test_the_selftest_error_tail_is_kept_only_when_something_failed(self):
        self.stderr = "Traceback tail"
        self.assertNotIn("selftest_stderr_tail", self.run_check()[1])
        self.report = None
        ok, res = self.run_check()
        self.assertFalse(ok)
        self.assertEqual(res["selftest_stderr_tail"], "Traceback tail")

    def test_the_problem_count_and_each_problem_are_printed_for_the_runner_log(self):
        self.rows.append({"path": "_internal/_ssl.pyd", "imports": ["ws2_32.dll"], "delay": [], "bound": []})
        with mock.patch.object(build, "log") as logger:
            self.run_check()
        lines = [call.args[0] for call in logger.call_args_list]
        self.assertTrue(any("점검 실패" in line and "문제 1건" in line for line in lines), lines)
        self.assertTrue(any(line.startswith("  ★ ") and "_ssl.pyd" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
