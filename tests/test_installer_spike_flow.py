"""설치 도구 시험(spike) 단계 실행기와 측정 흐름의 통합 시험(결정 D-706) — 설치 도구·윈도·네트워크 없이 **가짜 바깥 세계**(`tests/installer_spike_fakeworld.py`)를 끼워 다섯 단계를 끝까지 돌린다.

지키는 것: ① 다섯 단계(install-tools → build-bundles → pack → measure → report)가 이어지고 상태·기록이 쓰이며 보고서 둘이 나온다 ② 측정 M01–M22 가 모두 기록된다 ③ 도구 하나가 실패해도(vpk 설치·ISCC 판·
PyInstaller·실제 묶음 빌드) 그 갈래만 '없음' 이 되고 나머지는 계속된다 — 값이 모자란 관문은 미정이고 실패로 세지 않는다 ④ 모르는 옵션(--delta 의 끔 값·SDK 앱의 --skipVeloAppCheck)은 후보를 차례로 써 보고 기억한다
⑤ 방화벽 규칙·가짜 자격 증명·켜 둔 앱은 끝에 모두 치워진다 ⑥ 어긋난 결과(반쯤 바뀐 업데이트·데이터 삭제·남은 바로가기·훅 실패)는 해당 항목과 관문을 빨갛게 한다 ⑦ 한 흐름이 터져도 다른 갈래 기록은 남는다 ⑧ 보고서에 경로·사용자 이름이 없다.
이 흉내가 진짜 도구와 같다는 보장은 없다 — 진짜 동작은 병합 뒤 운영자의 수동 실행이 알려 준다.
"""
import contextlib
import hashlib
import io
import json
import os
import secrets
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer_spike_support as support  # noqa: E402
from installer_spike_fakeworld import FakeWorld  # noqa: E402

run = support.load("run_spike")
ALL_IDS = ["M%02d" % number for number in range(1, 23)]


def small_payload(version):
    """판마다 다른 파일을 넷으로 줄인다(진짜는 아홉 — 이 PC 는 새 파일마다 Defender 가 검사해 통합 시험이 느리다). 반쯤 바뀜은 이 넷으로도 알아본다."""
    files = {"VERSION": version + "\n"}
    for number in range(1, 4):
        files["payload/p%d.txt" % number] = "version %s file %d\n" % (version, number)
    return files


def pipeline(tmp, commands=("install-tools", "build-bundles", "pack", "measure", "report"), **switches):
    world = FakeWorld(tmp, **switches)
    work = Path(tmp) / "work"
    codes = []
    with mock.patch.object(run.fetch_tools, "check_file", lambda path, tool: ""), mock.patch.object(run, "payload_files", small_payload), \
            contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        for command in commands:
            codes.append(run.main([command, "--work", str(work)], host=world))
    return world, work, codes


def light_measure(world, work):
    """무거운 흐름(설치·업데이트)은 시간 예산 0 으로 건너뛰고 상태만 읽는 측정(M01–M04·M22 등)과 보고서만 돈다 → (문맥, 보고서 사전)."""
    ctx = run.Context(work, host=world)
    ctx.budget = -1
    with contextlib.redirect_stdout(io.StringIO()):
        run.measure.run_measurements(ctx)
    block, md, data = run.build_report(ctx)
    return ctx, data


def read(work, name):
    return json.loads((Path(work) / name).read_text(encoding="utf-8"))


def find(results, mid, arm=None, target=None):
    return [item for item in results if item["id"] == mid and (arm is None or item["arm"] == arm) and (target is None or item["values"].get("target") == target)]


class WholePipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.world, cls.work, cls.codes = pipeline(cls.tmp.name)
        cls.state, cls.results = read(cls.work, "state.json"), read(cls.work, "results.json")
        cls.report = read(cls.work / "report", "INSTALLER_SPIKE_REPORT.json")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_step_ran_and_the_files_exist(self):
        self.assertEqual(self.codes, [0, 0, 0, 0, 0])
        for name in ("install-tools", "build-bundles", "pack", "measure"):
            self.assertEqual(self.state["steps"][name]["status"], "ok", name)
        self.assertEqual(sorted(path.name for path in (self.work / "report").iterdir()), ["INSTALLER_SPIKE_REPORT.json", "INSTALLER_SPIKE_REPORT.md"])
        self.assertEqual(self.report["schema"], 1)

    def test_all_twenty_two_measurements_are_recorded(self):
        ids = {item["id"] for item in self.results}
        self.assertEqual(sorted(ids), ALL_IDS)

    def test_the_tools_were_installed_from_the_local_source_only_and_the_wheel_by_hash(self):
        calls = self.world.calls
        tool_install = next(call for call in calls if call[:2] == ["dotnet", "tool"])
        config = Path(tool_install[tool_install.index("--configfile") + 1]).read_text(encoding="utf-8")
        self.assertEqual(config.count("<add "), 1)
        self.assertNotIn("nuget.org", config)
        download = next(call for call in calls if "download" in call and "pip" in call)
        self.assertIn("--require-hashes", download)
        installs = [call for call in calls if "pip" in call and "install" in call]
        self.assertTrue(any("--no-index" in call and "--require-hashes" in call for call in installs))
        sdk_python = Path(self.state["tools"]["sdk"]["python"])
        self.assertTrue(sdk_python.parts[-3:-1] == ("venv-sdk", "Scripts"))                      # 휠은 별도 가상환경에만
        self.assertEqual(self.state["tools"]["iscc"]["version"], "6.7.1.0")
        self.assertTrue(self.state["tools"]["iscc"]["version_ok"])
        self.assertEqual(self.state["tools"]["iscc"]["signer"], "Fake Signer B.V.")
        self.assertIn("vpk_pack_help", self.state["help"])
        self.assertIn("update_apply_help", self.state["help"])
        self.assertGreater(self.state["job_deadline"], 1_000_000)

    def test_pack_made_three_small_installers_per_arm_plus_the_real_ones_and_the_id_test(self):
        installers = self.state["installers"]
        for arm in "ABC":
            self.assertEqual(sorted(installers[arm]["tiny"]), ["0.0.1", "0.0.2", "0.0.3"])
        for arm in "BC":
            self.assertTrue(Path(installers[arm]["real"]["setup"]).is_file())
        self.assertTrue(installers["A"]["idtest"]["name"].startswith("ChanceBlogDesktop-"))
        self.assertEqual(self.state["pack_problems"], {})
        self.assertEqual(self.state["steps"]["pack"]["flags"], {"delta": True, "skip_A": False})

    def test_the_basic_flows_pass_for_every_arm(self):
        for mid in ("M04", "M08", "M09", "M12"):
            for arm in "ABC":
                records = find(self.results, mid, arm)
                self.assertTrue(records, (mid, arm))
                self.assertTrue(all(item["status"] == "pass" for item in records), (mid, arm, [item["values"].get("brief") for item in records]))
        for arm in "ABC":
            self.assertEqual(find(self.results, "M05", arm, "tiny")[0]["status"], "pass")
        for arm in "BC":
            for mid in ("M05", "M06", "M12", "M19"):
                self.assertEqual(find(self.results, mid, arm, "real")[0]["status"], "pass", (mid, arm))
        for arm in "AB":
            self.assertEqual(find(self.results, "M07", arm, "tiny")[0]["status"], "pass")
            self.assertEqual(find(self.results, "M21", arm)[0]["status"], "pass")
        self.assertEqual(find(self.results, "M17", "C")[0]["status"], "pass")
        self.assertEqual(find(self.results, "M22")[0]["status"], "pass")

    def test_the_real_bundle_hook_symptom_is_recorded_as_information(self):
        item = find(self.results, "M07", "-", "real")[0]
        self.assertEqual(item["status"], "info")
        self.assertEqual(sum(row["timed_out"] for row in item["values"]["rows"]), 4)
        self.assertEqual(item["values"]["rows"][0]["classes"], ["#32770"])

    def test_the_id_collision_control_matches_the_file_system_it_ran_on(self):
        item = find(self.results, "M13", "A")[0]
        self.assertEqual(item["status"], "info")
        self.assertEqual(item["values"]["same_folder"], os.name == "nt")                          # 윈도(대소문자 구분 없음)에서만 같은 폴더가 된다 — F2
        if os.name == "nt":
            self.assertFalse(item["values"]["sentinel_survived"])

    def test_rollback_and_the_broken_version_are_recorded_without_a_verdict(self):
        for arm in "ABC":
            self.assertEqual(find(self.results, "M10", arm)[0]["status"], "info")
            broken = find(self.results, "M11", arm)[0]
            self.assertEqual(broken["status"], "info")
            self.assertEqual(broken["values"]["new_version_exit"], 3)
            self.assertFalse(broken["values"]["auto_rollback"])
            self.assertEqual(broken["values"]["version_after"], "0.0.3")

    def test_blocked_runs_followed_a_confirmed_firewall_control_and_left_no_rule_behind(self):
        self.assertEqual(self.world.rules, {})
        self.assertGreater(self.world.rules_added, 6)
        for arm in "ABC":
            self.assertEqual(find(self.results, "M14", arm)[0]["status"], "pass")
        control = [item for item in find(self.results, "M14", "-")]
        self.assertTrue(any(item["values"].get("control", {}).get("effective") is True for item in control))

    def test_fake_credentials_and_running_apps_are_cleaned_up(self):
        self.assertEqual(self.world.credentials, set())
        self.assertEqual([proc for proc in self.world.running if proc.alive], [])

    def test_the_standard_user_attempt_is_reported_as_not_possible_not_as_a_failure(self):
        for arm in "ABC":
            item = find(self.results, "M18", arm)[0]
            self.assertEqual(item["status"], "unavailable")

    def test_the_gates_have_no_failure_and_the_missing_pieces_are_unknown(self):
        gates = self.report["gates"]
        for arm in "ABC":
            for gate, row in gates[arm].items():
                self.assertNotEqual(row["status"], "fail", (arm, gate, row))
        self.assertEqual(gates["C"]["G3"]["status"], "n/a")
        for arm in "ABC":
            self.assertEqual(gates[arm]["G2"]["status"], "pass")
            self.assertEqual(gates[arm]["G4"]["status"], "pass")
            self.assertEqual(gates[arm]["G5"]["status"], "pass")
            self.assertEqual(gates[arm]["G6"]["status"], "pass")

    def test_the_report_has_no_path_and_no_user_name(self):
        text = (self.work / "report" / "INSTALLER_SPIKE_REPORT.md").read_text(encoding="utf-8") + (self.work / "report" / "INSTALLER_SPIKE_REPORT.json").read_text(encoding="utf-8")
        for word in ("runneradmin", self.tmp.name, str(self.work), self.tmp.name.replace("\\", "/")):
            self.assertNotIn(word, text, word)
        self.assertIn("=== INSTALLER_SPIKE_RESULT v1 ===", text)

    def test_running_measure_again_starts_the_records_over(self):
        world = self.world
        with contextlib.redirect_stdout(io.StringIO()):
            run.main(["measure", "--work", str(self.work)], host=world)
        again = read(self.work, "results.json")
        self.assertEqual(len(again), len(self.results))


class ToolProblemsTest(unittest.TestCase):
    def run_with(self, **switches):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, work, codes = pipeline(tmp.name, **switches)
        return world, read(work, "state.json"), read(work, "results.json"), read(work / "report", "INSTALLER_SPIKE_REPORT.json"), codes

    def test_a_failing_vpk_install_takes_only_the_velopack_arms_out_and_the_rest_goes_on(self):
        world, state, results, report, codes = self.run_with(dotnet_fail=True)
        self.assertEqual(codes, [0, 0, 0, 0, 0])
        self.assertEqual(state["tools"]["vpk"]["status"], "failed")
        self.assertIn("로컬 원본만", state["tools"]["vpk"]["reason"])
        self.assertIn("A", state["pack_problems"])
        self.assertEqual(find(results, "M01", "A")[0]["status"], "fail")
        for arm in "AB":
            self.assertEqual(find(results, "M05", arm)[0]["status"], "unavailable")
            self.assertNotIn(report["gates"][arm]["G2"]["status"], ("fail", "pass"))
        self.assertEqual(find(results, "M05", "C", "tiny")[0]["status"], "pass")
        self.assertEqual(report["gates"]["C"]["G2"]["status"], "pass")
        self.assertIn("만들기 문제", report["block"])

    def test_missing_nupkg_is_a_failure_reason_not_a_crash(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world = FakeWorld(tmp.name)
        work = Path(tmp.name) / "work"
        with contextlib.redirect_stdout(io.StringIO()):
            run.main(["install-tools", "--work", str(work)], host=world)
        state = read(work, "state.json")
        self.assertEqual(state["tools"]["vpk"]["status"], "failed")
        self.assertIn("파일 대조 실패", state["tools"]["vpk"]["reason"])
        self.assertFalse(any(call[:2] == ["dotnet", "tool"] for call in world.calls))               # 대조 실패면 설치 명령을 부르지 않는다

    def test_unknown_options_are_discovered_by_trying_candidates_and_remembered(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, work, codes = pipeline(tmp.name, commands=("install-tools", "build-bundles", "pack"), delta_ok=False, sdk_needs_skip=True)
        state = read(work, "state.json")
        self.assertEqual(state["steps"]["pack"]["flags"], {"delta": False, "skip_A": True})
        self.assertEqual(state["pack_problems"], {})
        packs = [call for call in world.calls if call[1:2] == ["pack"] and "--packId" in call]
        self.assertGreater(len(packs), 8)
        self.assertTrue(all("--delta" not in call for call in packs[6:]))
        self.assertEqual(sorted(state["installers"]["A"]["tiny"]), ["0.0.1", "0.0.2", "0.0.3"])
        first_sdk = next(call for call in packs if call[call.index("--mainExe") + 1] == "SpikeAppSdk.exe")
        self.assertNotIn("--skipVeloAppCheck", first_sdk)                                              # 처음에는 확인을 끄지 않고 써 본다

    def light_run(self, **switches):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, work, codes = pipeline(tmp.name, commands=("install-tools", "build-bundles", "pack"), **switches)
        ctx, report = light_measure(world, work)
        return world, read(work, "state.json"), ctx.results, report

    def test_an_inno_version_other_than_six_point_seven_stops_only_that_arm(self):
        world, state, results, report = self.light_run(iscc_version="6.8.0.0")
        self.assertFalse(state["tools"]["iscc"]["version_ok"])
        self.assertEqual(find(results, "M01", "C")[0]["status"], "fail")
        self.assertIn("C", state["pack_problems"])
        self.assertEqual(state["installers"]["C"], {})
        self.assertEqual(sorted(state["installers"]["B"]["tiny"]), ["0.0.1", "0.0.2", "0.0.3"])
        self.assertTrue(all(call[0] != str(state["tools"]["iscc"]["path"]) for call in world.calls))          # 판이 다르면 컴파일 명령을 부르지 않는다

    def test_a_missing_inno_is_unavailable_not_failed(self):
        world, state, results, report = self.light_run(iscc_missing=True)
        self.assertEqual(find(results, "M01", "C")[0]["status"], "unavailable")
        self.assertEqual(report["gates"]["C"]["G2"]["status"], "unknown")
        self.assertIn("C", state["pack_problems"])

    def test_an_inno_really_installed_on_the_machine_does_not_leak_into_a_world_that_says_it_is_missing(self):
        """윈도 러너 이미지에는 Inno Setup 이 실제로 깔려 있다 — 정해진 자리를 실제 디스크에서 직접 보면 '없다'는 가짜 세계에도 그것이 보여 위 시험이 러너에서만 빨개졌다(CI 진단 실행). 같은 조건을 어느 PC 에서나 만든다."""
        real = tempfile.TemporaryDirectory()
        self.addCleanup(real.cleanup)
        really_there = Path(real.name) / "ISCC.exe"
        really_there.write_bytes(b"MZ-an-inno-that-really-exists-on-this-machine")
        with mock.patch.object(run, "ISCC_CANDIDATES", (str(really_there),)):
            world, state, results, report = self.light_run(iscc_missing=True)
        self.assertEqual(state["tools"]["iscc"]["status"], "unavailable")
        self.assertEqual(find(results, "M01", "C")[0]["status"], "unavailable")
        self.assertEqual(world.file_checks, [str(really_there)])                                       # 정해진 자리는 바깥 세계 객체를 거쳐 물었다
        self.assertTrue(all(call[0] != str(really_there) for call in world.calls))                      # 실제 파일을 실행하려 들지 않았다

    def test_a_failed_real_build_leaves_the_real_bundle_items_unknown(self):
        world, state, results, report = self.light_run(build_fail=True)
        self.assertEqual(find(results, "M02")[0]["status"], "fail")
        self.assertEqual(find(results, "M03", "B")[0]["status"], "unavailable")
        self.assertEqual(find(results, "M22")[0]["status"], "unavailable")
        for arm in "ABC":
            self.assertEqual(report["gates"][arm]["G7"]["status"], "unknown")
            self.assertEqual(report["gates"][arm]["G8"]["status"], "unknown")
        self.assertEqual(sorted(state["installers"]["B"]["tiny"]), ["0.0.1", "0.0.2", "0.0.3"])               # 작은 앱 쪽은 그대로 만들어졌다

    def test_a_failed_tiny_build_makes_the_arms_unavailable_but_a_report_is_still_made(self):
        world, state, results, report, codes = self.run_with(pyinstaller_fail=True)
        self.assertEqual(codes, [0, 0, 0, 0, 0])
        for arm in "ABC":
            self.assertEqual(find(results, "M05", arm)[0]["status"], "unavailable")
        self.assertTrue(report["block"].startswith("=== INSTALLER_SPIKE_RESULT v1 ==="))


class BadOutcomeTest(unittest.TestCase):
    """어긋난 결과는 해당 항목과 관문을 빨갛게 한다 — 서로 닿지 않는 스위치는 한 번의 통합 실행에 묶어 시간을 줄인다."""

    @classmethod
    def run_group(cls, **switches):
        tmp = tempfile.TemporaryDirectory()
        world, work, codes = pipeline(tmp.name, **switches)
        group = {"tmp": tmp, "world": world, "state": read(work, "state.json"), "results": read(work, "results.json"), "report": read(work / "report", "INSTALLER_SPIKE_REPORT.json")}
        return group

    @classmethod
    def setUpClass(cls):
        cls.messy = cls.run_group(hook_rc=2, keep_shortcut=True, selftest_fail={"qt_plugins"}, defender_status="threats_found", firewall_effective=False, std_user_ok=True, hold_apps_closed_by_inno=False)
        cls.mixed = cls.run_group(mixed_on_running=True, delete_data_on_uninstall=True)
        cls.auto = cls.run_group(autostart=True)
        cls.boom = cls.run_group(raise_on=lambda args: args[0].replace(chr(92), "/").endswith("/run/B/root/Update.exe") and "uninstall" in args)

    @classmethod
    def tearDownClass(cls):
        for group in (cls.messy, cls.mixed, cls.auto, cls.boom):
            group["tmp"].cleanup()

    def test_a_failing_hook_fails_m07_and_g3_for_the_hook_arms(self):
        for arm in "AB":
            self.assertEqual(find(self.messy["results"], "M07", arm, "tiny")[0]["status"], "fail")
            self.assertEqual(self.messy["report"]["gates"][arm]["G3"]["status"], "fail")
        self.assertEqual(self.messy["report"]["gates"]["C"]["G3"]["status"], "n/a")

    def test_a_leftover_shortcut_fails_m12_and_g2(self):
        for arm in "ABC":
            item = find(self.messy["results"], "M12", arm, "tiny")[0]
            self.assertEqual(item["status"], "fail")
            self.assertTrue(item["values"]["shortcuts_left"])
            self.assertEqual(self.messy["report"]["gates"][arm]["G2"]["status"], "fail")

    def test_a_failed_selftest_in_the_installed_real_bundle_fails_m06_and_g8(self):
        for arm in "BC":
            item = find(self.messy["results"], "M06", arm, "real")[0]
            self.assertEqual(item["status"], "fail")
            self.assertEqual(item["values"]["bad"], ["qt_plugins"])
            self.assertEqual(self.messy["report"]["gates"][arm]["G8"]["status"], "fail")

    def test_defender_findings_fail_m16_and_g6(self):
        scanned = [item for item in find(self.messy["results"], "M16") if item["values"].get("tool_status")]
        self.assertTrue(scanned)
        self.assertTrue(all(item["status"] == "fail" for item in scanned))
        self.assertEqual(self.messy["report"]["gates"]["B"]["G6"]["status"], "fail")

    def test_a_firewall_rule_that_does_not_bite_makes_m14_information_and_g5_unknown(self):
        for arm in "ABC":
            self.assertEqual(find(self.messy["results"], "M14", arm)[0]["status"], "info")
            self.assertEqual(self.messy["report"]["gates"][arm]["G5"]["status"], "unknown")
        self.assertEqual(self.messy["world"].rules, {})

    def test_a_standard_user_install_that_works_is_a_pass(self):
        for arm in "ABC":
            self.assertEqual(find(self.messy["results"], "M18", arm)[0]["status"], "pass")

    def test_an_installer_that_cannot_close_the_running_app_fails_cleanly_which_is_allowed(self):
        item = find(self.messy["results"], "M09", "C")[0]
        self.assertEqual(item["values"]["state"], "old")
        self.assertEqual(item["status"], "pass")                                             # 깨끗이 실패(옛 판 그대로)도 허용 — 반쯤 바뀐 상태만 아니면 된다

    def test_a_half_updated_state_while_the_app_runs_fails_m09_and_g4_for_the_velopack_arms_only(self):
        for arm in "AB":
            item = find(self.mixed["results"], "M09", arm)[0]
            self.assertEqual(item["status"], "fail")
            self.assertEqual(item["values"]["state"], "mixed")
            self.assertEqual(self.mixed["report"]["gates"][arm]["G4"]["status"], "fail")
        self.assertEqual(find(self.mixed["results"], "M09", "C")[0]["status"], "pass")
        self.assertEqual(self.mixed["report"]["gates"]["C"]["G4"]["status"], "pass")

    def test_deleted_user_data_fails_m12(self):
        for arm in "ABC":
            item = find(self.mixed["results"], "M12", arm, "tiny")[0]
            self.assertEqual(item["status"], "fail")
            self.assertFalse(item["values"]["data_kept"])

    def test_an_app_that_starts_by_itself_after_a_silent_install_fails_m05(self):
        for arm in "ABC":
            item = find(self.auto["results"], "M05", arm, "tiny")[0]
            self.assertEqual(item["status"], "fail")
            self.assertTrue(item["values"]["autostart"])

    def test_a_flow_that_blows_up_is_recorded_as_an_error_and_the_report_is_still_made(self):
        errors = [item for item in self.boom["results"] if item["status"] == "error"]
        self.assertTrue(errors)
        self.assertTrue(find(self.boom["results"], "M05", "A", "tiny") and find(self.boom["results"], "M05", "C", "tiny"))
        self.assertEqual(self.boom["report"]["block"].count("=== END ==="), 1)
        self.assertEqual(self.boom["state"]["steps"]["measure"]["status"], "ok")


class StandardUserPasswordTest(unittest.TestCase):
    """권고 R2 — 임시 표준 사용자의 임의 비밀번호는 net user 명령줄과 PowerShell 환경 변수로 간다(명령줄에 한 번 들어간다는 점을 숨기지 않는다). 어떤 도구가 되울려도 기록·보고서에 남지 않고, 만든 사용자는 반드시 지운다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.world, cls.work, cls.codes = pipeline(cls.tmp.name, commands=("install-tools", "build-bundles", "pack"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.world.net_user_ok, self.world.std_user_ok, self.world.raise_on = True, False, None

    def attempt(self, arm="A"):
        """M18 만 직접 돌린다 → (문맥, 이번 시도의 net 호출들, 비밀번호 또는 None)."""
        before = len(self.world.net_calls)
        ctx = run.Context(self.work, host=self.world)
        ctx.results = []                                                                            # 앞 시험이 저장한 기록을 이어받지 않는다
        with contextlib.redirect_stdout(io.StringIO()):
            run.measure.m18_standard_user(ctx, arm)
        calls = self.world.net_calls[before:]
        adds = [call for call in calls if "/add" in call]
        return ctx, calls, (adds[0][3] if adds else None)

    def test_the_password_is_new_for_every_attempt_and_long_enough(self):
        first, second = self.attempt()[2], self.attempt()[2]
        self.assertTrue(first and second)
        self.assertNotEqual(first, second)
        for password in (first, second):
            self.assertTrue(password.startswith("Sp1ke!"))
            self.assertGreaterEqual(len(password), 16)

    def test_an_error_text_that_echoes_the_password_does_not_leave_it_in_the_record_the_files_or_the_report(self):
        ctx, calls, password = self.attempt()                                                      # 가짜 PowerShell 이 실패하며 SPIKE_PW 를 되울린다
        items = find(ctx.results, "M18", "A")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "unavailable")
        self.assertIn("<가림>", items[0]["note"])                                                  # 되울린 글이 있었고 가려졌다 — 가린 것이 없다면 이 시험은 아무것도 보지 못한 것이다
        ctx.save()
        block, md, data = run.build_report(ctx)
        everything = block + md + json.dumps(data, ensure_ascii=False) + json.dumps(ctx.results, ensure_ascii=False) + (self.work / "results.json").read_text(encoding="utf-8") + (self.work / "state.json").read_text(encoding="utf-8")
        self.assertNotIn(password, everything)

    def test_the_user_is_added_first_and_deleted_last_and_the_delete_line_has_no_password(self):
        for std_user_ok in (False, True):
            self.world.std_user_ok = std_user_ok
            ctx, calls, password = self.attempt()
            adds = [index for index, call in enumerate(calls) if "/add" in call]
            deletes = [index for index, call in enumerate(calls) if "/delete" in call]
            self.assertEqual((len(adds), len(deletes)), (1, 1), std_user_ok)
            self.assertLess(adds[0], deletes[0])
            self.assertEqual(calls[adds[0]], ["net", "user", run.measure.STD_USER, password, "/add", "/Y"])
            self.assertEqual(calls[deletes[0]], ["net", "user", run.measure.STD_USER, "/delete"])
            self.assertEqual(find(ctx.results, "M18", "A")[0]["status"], "pass" if std_user_ok else "unavailable")

    def test_the_user_is_deleted_even_when_the_install_step_blows_up(self):
        self.world.raise_on = lambda args: args[0] == "powershell" and "PSCredential" in args[-1]
        before = len(self.world.net_calls)
        ctx = run.Context(self.work, host=self.world)
        with self.assertRaises(RuntimeError):
            run.measure.m18_standard_user(ctx, "B")
        calls = self.world.net_calls[before:]
        self.assertEqual([call for call in calls if "/delete" in call], [["net", "user", run.measure.STD_USER, "/delete"]])

    def test_when_the_user_cannot_be_made_the_echoed_password_is_not_recorded_and_nothing_is_deleted(self):
        self.world.net_user_ok = False                                                              # 가짜 net user 가 실패하며 비밀번호를 되울린다
        ctx, calls, password = self.attempt("C")
        item = find(ctx.results, "M18", "C")[0]
        self.assertEqual(item["status"], "unavailable")
        self.assertIn("사용자 만들기 실패", item["values"]["brief"])
        self.assertNotIn(password, json.dumps(ctx.results, ensure_ascii=False))
        self.assertEqual([call for call in calls if "/delete" in call], [])                         # 만들지 못한 사용자는 지울 것이 없다


LIGHT_TOKEN = "Zq9xW3kLm2Vb7TnP"                                                                  # 시험이 고정한 '무작위' 부분 — 우연한 겹침으로 시험이 흔들리지 않게
LIGHT_PASSWORD = "Sp1ke!" + LIGHT_TOKEN


def light_m18(tmp, *, arm="A", environ=None, **switches):
    """무거운 다섯 단계 없이 M18 하나만 가짜 세계에서 돌린다 → (가짜 세계, 문맥). 설치 파일은 가짜 세계가 만든 작은 가짜이고 비밀번호의 무작위 부분은 고정한다. environ 의 값이 None 이면 그 환경 변수를 뺀다."""
    world = FakeWorld(tmp, **switches)
    for key, value in (environ or {}).items():
        if value is None:
            world.environ.pop(key, None)
        else:
            world.environ[key] = value
    setup = Path(tmp) / "fake-setup.exe"
    world.new_setup(setup, {"kind": "velopack", "bundle": Path(tmp), "exe": "SpikeApp.exe", "id": "Fake", "version": "0.0.1"})
    ctx = run.Context(Path(tmp) / "work", host=world)
    ctx.results = []
    ctx.state["installers"] = {key: {"tiny": {"0.0.1": {"setup": str(setup)}}} for key in "ABC"}
    with mock.patch.object(secrets, "token_urlsafe", lambda size: LIGHT_TOKEN), contextlib.redirect_stdout(io.StringIO()):
        run.measure.m18_standard_user(ctx, arm)
    return world, ctx


def everything_left(world, ctx):
    """이 시도가 남긴 모든 글 — 기록·저장한 파일(결과·상태)·따로 도는 report 단계 모양(가릴 낱말을 모르는 새 문맥)이 만든 보고서(md·json·결과 블록)."""
    ctx.save()
    fresh = run.Context(ctx.work, host=world)
    block, md, data = run.build_report(fresh)
    text = "\n".join((json.dumps(ctx.results, ensure_ascii=False), (ctx.work / "results.json").read_text(encoding="utf-8"), (ctx.work / "state.json").read_text(encoding="utf-8"), block, md,
                      json.dumps(data, ensure_ascii=False)))
    folder = str(world.tmp)                                                                                  # 임시 폴더 이름은 무작위라 비밀번호 조각과 우연히 겹칠 수 있다 — 비교 전에 뺀다
    for spelling in (folder, folder.replace("\\", "\\\\"), folder.replace("\\", "/")):
        text = text.replace(spelling, "<폴더>")
    return text


def longest_piece(text, secret, floor=4):
    """secret 의 연속 조각 가운데 text 에 (대소문자를 가리지 않고) 그대로 들어 있는 가장 긴 길이 — floor 글자 미만이면 0."""
    lowered = text.lower()
    for size in range(len(secret), floor - 1, -1):
        for start in range(len(secret) - size + 1):
            if secret[start:start + size].lower() in lowered:
                return size
    return 0


class StandardUserEchoTest(unittest.TestCase):
    """재작업 권고 2·3 — 임시 비밀번호가 어떤 모양으로 되울려도(잘리거나·대소문자가 바뀌거나·URL 인코딩되거나·줄이 나뉘거나·접두어가 빠져도) 기록·저장한 파일·보고서 어디에도 조각이 남지 않는다."""

    def attempt(self, layout):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, ctx = light_m18(tmp.name, echo_layout=layout)
        item = ctx.results[-1]
        self.assertEqual((item["id"], item["status"]), ("M18", "unavailable"))
        return item, everything_left(world, ctx)

    def test_a_password_cut_in_the_middle_by_the_160_character_tail_leaves_no_piece(self):
        layouts = {"뒤 150자": lambda pw: "access denied for " + pw + "y" * 150, "앞 5자": lambda pw: "x" * 5 + pw + "y" * 150, "대문자": lambda pw: "x" * 5 + pw.upper() + "y" * 150,
                   "15글자 조각": lambda pw: "x" + pw + "y" * 145}
        for label, layout in layouts.items():
            with self.subTest(label):
                item, text = self.attempt(layout)
                self.assertIn("<가림>", item["note"])
                self.assertEqual(longest_piece(text, LIGHT_PASSWORD), 0)

    def test_upper_lower_and_swapped_case_echoes_are_hidden(self):
        for label, convert in (("대문자", str.upper), ("소문자", str.lower), ("섞임", str.swapcase)):
            with self.subTest(label):
                item, text = self.attempt(lambda pw, convert=convert: "ACCESS denied for " + convert(pw) + " now")
                self.assertTrue(item["note"].endswith("ACCESS denied for <가림> now"), item["note"])
                self.assertEqual(longest_piece(text, LIGHT_PASSWORD), 0)

    def test_a_url_encoded_echo_is_hidden_as_one_piece_including_the_prefix(self):
        item, text = self.attempt(lambda pw: "GET /login?pw=" + quote(pw, safe="") + " 401")
        self.assertTrue(item["note"].endswith("GET /login?pw=<가림> 401"), item["note"])                  # Sp1ke%21 접두어까지 한 덩어리로 — 인코딩한 모양도 가릴 낱말로 올렸다
        self.assertEqual(longest_piece(text, LIGHT_PASSWORD), 0)

    def test_an_echo_split_over_lines_or_spaced_out_is_hidden(self):
        layouts = (lambda pw: "denied: " + pw[:9] + "\r\n" + pw[9:], lambda pw: "denied: " + pw[:5] + "\n    " + pw[5:], lambda pw: "denied: " + " ".join(pw))
        for number, layout in enumerate(layouts):
            with self.subTest(number):
                item, text = self.attempt(layout)
                self.assertIn("<가림>", item["note"])
                self.assertEqual(longest_piece(text, LIGHT_PASSWORD), 0)

    def test_an_echo_of_only_the_random_part_or_with_the_bang_dropped_or_escaped_is_hidden(self):
        layouts = {"무작위 부분만": (lambda pw: "pw=" + pw[len("Sp1ke!"):], "pw=<가림>"), "느낌표 빠짐": (lambda pw: "pw=" + pw.replace("!", ""), "pw=Sp1ke<가림>"),
                   "느낌표가 %21": (lambda pw: "pw=" + pw.replace("!", "%21"), "pw=<가림>")}
        for label, (layout, expected) in layouts.items():
            with self.subTest(label):
                item, text = self.attempt(layout)
                self.assertTrue(item["note"].endswith(expected), item["note"])                              # 무작위 부분은 한 글자도 남지 않는다(접두어 Sp1ke 는 비밀이 아니라 남는다)
                self.assertEqual(longest_piece(text, LIGHT_TOKEN), 0)

    def test_text_around_the_password_is_kept_so_the_note_still_says_what_happened(self):
        item, text = self.attempt(lambda pw: "access denied for " + pw + " (code 5)")
        self.assertTrue(item["note"].endswith("access denied for <가림> (code 5)"), item["note"])


class StandardUserEnvironmentTest(unittest.TestCase):
    """참고 2 — 환경 변수가 없으면 실제 폴더 이름(공용 사용자 폴더·사용자 폴더)을 짐작해 쓰지 않는다."""

    def test_without_the_public_variable_no_user_is_made_and_nothing_is_run(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, ctx = light_m18(tmp.name, environ={"PUBLIC": None})
        item = ctx.results[-1]
        self.assertEqual((item["id"], item["status"]), ("M18", "unavailable"))
        self.assertIn("환경 변수", item["values"]["brief"])
        self.assertEqual(world.net_calls, [])                                                              # 사용자를 만들지 않았다
        self.assertEqual(world.calls, [])                                                                  # 프로그램을 하나도 돌리지 않았다
        self.assertEqual(ctx.secret_words, [])                                                             # 비밀번호도 만들지 않았다

    def test_with_public_but_without_the_users_variable_the_profile_is_looked_for_above_public(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        public = str(Path(tmp.name) / "users" / "Public")                                                  # 가짜 세계의 사용자 폴더 뿌리 안
        world, ctx = light_m18(tmp.name, environ={"SPIKE_USERS_DIR": None, "PUBLIC": public}, std_user_ok=True)
        item = ctx.results[-1]
        self.assertEqual(item["status"], "pass", item)                                                     # 가짜 PowerShell 이 위 폴더 아래에 남긴 흔적을 찾았다
        self.assertEqual(len([call for call in world.net_calls if "/add" in call]), 1)

    def test_the_users_variable_wins_over_the_folder_above_public(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        public = str(Path(tmp.name) / "somewhere" / "Public")                                              # 위 폴더에는 프로필이 없다 — 기본 SPIKE_USERS_DIR 가 가리키는 곳에 있다
        world, ctx = light_m18(tmp.name, environ={"PUBLIC": public}, std_user_ok=True)
        self.assertEqual(ctx.results[-1]["status"], "pass", ctx.results[-1])

    def test_a_profile_folder_that_has_no_trace_is_not_called_a_pass(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        elsewhere = str(Path(tmp.name) / "elsewhere")
        world, ctx = light_m18(tmp.name, environ={"SPIKE_USERS_DIR": elsewhere}, std_user_ok=True)
        self.assertEqual(ctx.results[-1]["status"], "fail")                                                # 종료 0 인데 찾는 폴더에 설치 흔적이 없다


class IsccLookupTest(unittest.TestCase):
    """재작업 권고 4 — 정해진 자리에서 Inno 를 찾는 성공 길은 가짜 세계가 늘 '없다'고 답해 시험이 없었다. 가짜 세계의 present_files 로 '있다'를 만들되 후보는 임시 실제 파일이라 어느 PC·러너에서나 같다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name) / "candidates"
        self.first, self.second = base / "one" / "ISCC.exe", base / "two" / "ISCC.exe"

    def make(self, path, content, *, korean=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if korean:
            (path.parent / "Languages").mkdir(exist_ok=True)
            (path.parent / "Languages" / "Korean.isl").write_text("x", encoding="utf-8")

    def look(self, *, present=(), which=False):
        world = FakeWorld(self.tmp.name, iscc_missing=not which, present_files={str(item) for item in present})
        ctx = run.Context(Path(self.tmp.name) / "work", host=world)
        with mock.patch.object(run, "ISCC_CANDIDATES", (str(self.first), str(self.second))):
            return world, run.find_iscc(ctx)

    def test_when_only_the_second_place_has_it_that_one_is_used_and_both_places_were_asked_in_order(self):
        self.make(self.second, b"MZ-the-second-one", korean=True)
        world, found = self.look(present=[self.second])
        self.assertEqual(found["status"], "ok")
        self.assertEqual(found["path"], str(self.second))
        self.assertEqual(found["sha256"], hashlib.sha256(b"MZ-the-second-one").hexdigest())
        self.assertIs(found["korean_isl"], True)
        self.assertEqual((found["version"], found["version_ok"]), ("6.7.1.0", True))
        self.assertEqual(world.file_checks, [str(self.first), str(self.second)])

    def test_a_place_without_the_korean_language_file_says_so(self):
        self.make(self.second, b"MZ-without-korean")
        world, found = self.look(present=[self.second])
        self.assertEqual(found["status"], "ok")
        self.assertIs(found["korean_isl"], False)

    def test_when_the_first_place_has_it_the_second_is_not_even_asked(self):
        self.make(self.first, b"MZ-the-first-one", korean=True)
        self.make(self.second, b"MZ-the-second-one", korean=True)
        world, found = self.look(present=[self.first, self.second])
        self.assertEqual(found["path"], str(self.first))
        self.assertEqual(found["sha256"], hashlib.sha256(b"MZ-the-first-one").hexdigest())
        self.assertEqual(world.file_checks, [str(self.first)])

    def test_what_which_finds_comes_before_the_fixed_places(self):
        self.make(self.first, b"MZ-the-first-one", korean=True)
        self.make(self.second, b"MZ-the-second-one", korean=True)
        world, found = self.look(present=[self.first, self.second], which=True)
        self.assertEqual(found["path"], str(world.tmp / "inno" / "ISCC.exe"))
        self.assertEqual(found["sha256"], hashlib.sha256(b"MZ-fake-iscc").hexdigest())
        self.assertEqual(world.file_checks, [])                                                            # 찾았으니 정해진 자리는 묻지 않는다

    def test_when_neither_which_nor_a_place_has_it_both_places_were_asked_and_it_is_unavailable(self):
        world, found = self.look()
        self.assertEqual(found["status"], "unavailable")
        self.assertIn("ISCC.exe", found["reason"])
        self.assertEqual(world.file_checks, [str(self.first), str(self.second)])
        self.assertNotIn("path", found)

    def test_the_fixed_places_are_the_two_program_files_folders_of_inno_setup_six(self):
        self.assertEqual(run.ISCC_CANDIDATES, ("C:/Program Files (x86)/Inno Setup 6/ISCC.exe", "C:/Program Files/Inno Setup 6/ISCC.exe"))


class BudgetTest(unittest.TestCase):
    def test_over_budget_flows_are_skipped_and_recorded_not_dropped(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, work, codes = pipeline(tmp.name, commands=("install-tools", "build-bundles", "pack"))
        ctx = run.Context(work, host=world)
        ctx.budget = -1
        with contextlib.redirect_stdout(io.StringIO()):
            run.measure.run_measurements(ctx)
        skipped = [item for item in ctx.results if item["status"] == "skip"]
        self.assertEqual({item["arm"] for item in skipped if item["id"] == "M05"}, {"A", "B", "C"})
        self.assertTrue(any(item["id"] == "M22" for item in ctx.results))

    def test_the_time_limit_of_a_step_follows_the_time_left_in_the_job(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ctx = run.Context(Path(tmp.name) / "w", host=FakeWorld(tmp.name))
        self.assertEqual(run.capped(ctx, 900), 900)                                                 # 마감이 없으면 그대로
        ctx.state["job_deadline"] = ctx.host.wall() + 400
        self.assertEqual(run.capped(ctx, 900), 310)
        ctx.state["job_deadline"] = ctx.host.wall() + 10
        self.assertEqual(run.capped(ctx, 900), 60)
        self.assertEqual(run.time_left(ctx), 10)

    def test_the_measure_budget_leaves_room_for_the_report_and_the_upload(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world = FakeWorld(tmp.name)
        ctx = run.Context(Path(tmp.name) / "w", host=world)
        ctx.state["job_deadline"] = world.wall() + 1000
        with mock.patch.object(run.measure, "run_measurements", lambda context: None), contextlib.redirect_stdout(io.StringIO()):
            run.cmd_measure(ctx)
        self.assertEqual(ctx.budget, 760)
        self.assertLessEqual(run.measure.BUDGET_SECONDS, 30 * 60)


if __name__ == "__main__":
    unittest.main()
