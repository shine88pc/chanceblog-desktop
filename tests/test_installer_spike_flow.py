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
import installer_spike_fakeworld as fakeworld  # noqa: E402
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
        self.assertIn("대소문자를 무시하고 비교해도 다른 이름이어야 한다(대소문자만 다르면 같은 폴더)", item["note"])      # 재작업 S-R5 — 규칙 문장이 거꾸로 읽히지 않게('대소문자까지 달라야' 는 대소문자만 달라도 된다는 뜻으로 읽힌다)
        self.assertNotIn("대소문자까지", item["note"])

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
        """결정 D-810 이후 문은 6.5.0 이다 — 6.7 줄이 아니어도 6.5.0 이상이면 이어서 진행한다(아래 새 시험). 이 시험은 문 아래의 판(6.4.3)이 갈래 C 만 멈추는지 지킨다."""
        world, state, results, report = self.light_run(iscc_version="6.4.3.0")
        self.assertFalse(state["tools"]["iscc"]["version_ok"])
        self.assertEqual(find(results, "M01", "C")[0]["status"], "fail")
        self.assertIn("C", state["pack_problems"])
        self.assertEqual(state["installers"]["C"], {})
        self.assertEqual(sorted(state["installers"]["B"]["tiny"]), ["0.0.1", "0.0.2", "0.0.3"])
        self.assertTrue(all(call[0] != str(state["tools"]["iscc"]["path"]) or call[1:] == ["/?"] for call in world.calls))          # 판이 낮으면 컴파일 명령을 부르지 않는다(판을 읽으려고 사용법만 부른다 — D-810)
        self.assertEqual(world.compile_calls, 0)                                                                                     # 컴파일러는 한 번도 컴파일하지 않았다

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
            self.assertEqual(calls[adds[0]], ["net", "user", run.measure.std_user_name("A"), password, "/add", "/Y"])
            self.assertEqual(calls[deletes[0]], ["net", "user", run.measure.std_user_name("A"), "/delete"])
            self.assertEqual(find(ctx.results, "M18", "A")[0]["status"], "pass" if std_user_ok else "unavailable")

    def test_the_user_is_deleted_even_when_the_install_step_blows_up(self):
        self.world.raise_on = lambda args: args[0] == "powershell" and "PSCredential" in args[-1]
        before = len(self.world.net_calls)
        ctx = run.Context(self.work, host=self.world)
        with self.assertRaises(RuntimeError):
            run.measure.m18_standard_user(ctx, "B")
        calls = self.world.net_calls[before:]
        self.assertEqual([call for call in calls if "/delete" in call], [["net", "user", run.measure.std_user_name("B"), "/delete"]])

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
        item = ctx.results[-1]
        self.assertEqual(item["status"], "unavailable")                                                    # 결정 D-810 — 종료 0 인데 흔적이 없는 것은 실패가 아니라 '시도 불가'(운영자 실기로)다. 통과도 아니다
        self.assertNotIn(item["status"], ("pass", "fail"))
        self.assertIn("종료 0 인데 설치 흔적 없음", item["values"]["brief"])                                  # 이유가 상자에 보인다
        self.assertIn("운영자 실기", item["values"]["brief"])


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


def fakeworld_names():
    """가짜 세계가 `--selftest` 로 찍는 점검 이름들 — 앱의 목록에서 읽은 것이다."""
    return tuple(fakeworld.SELFTEST_NAMES)


def block_lines(report):
    return report["block"].splitlines()


def line_of(lines, prefix):
    found = [line for line in lines if line.startswith(prefix)]
    assert len(found) == 1, (prefix, found)
    return found[0]


class FirstRunDefectsTest(unittest.TestCase):
    """결정 D-810 — 1차 측정 결과 상자가 보여 준 도구 결함(점검 개수 12 못박기·'러너: ? ?'·잘린 M20 줄·한 줄에 이어 붙인 두 결과·표준 사용자)이 기본 가짜 세계(앱의 점검 목록 전부·윈도처럼 대문자인 환경 이름)에서 맞게 판정되는지 본다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.world, cls.work, cls.codes = pipeline(cls.tmp.name)
        cls.state, cls.results = read(cls.work, "state.json"), read(cls.work, "results.json")
        cls.report = read(cls.work / "report", "INSTALLER_SPIKE_REPORT.json")
        cls.lines = block_lines(cls.report)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_fake_world_keeps_environment_names_the_way_windows_does(self):
        self.assertIn("IMAGEOS", self.world.environ)
        self.assertNotIn("ImageOS", self.world.environ)                                              # 이 모양에서 이름을 그대로 찾으면 못 찾는다 — 1차 측정이 '러너: ? ?' 로 나온 이유

    def test_the_header_names_the_runner_and_the_image(self):
        self.assertTrue(self.lines[1].startswith("러너: Windows win25 20261116.335.1 · "), self.lines[1])
        self.assertNotIn("?", self.lines[1])
        self.assertIn("vpk 1.2.161 · ", self.lines[1])
        self.assertTrue(self.lines[1].endswith("커밋 0123456"), self.lines[1])

    def test_the_apps_whole_list_of_checks_passes_the_installed_and_the_portable_selftest(self):
        names = fakeworld_names()
        self.assertGreater(len(names), run.measure.MIN_SELFTEST_PASSED, "이 시험이 흉내 내는 1차 측정의 상황은 앱의 점검이 12 개보다 많을 때다")
        for arm in "BC":
            item = find(self.results, "M06", arm, "real")[0]
            self.assertEqual(item["status"], "pass", arm)
            self.assertEqual((item["values"]["passed"], item["values"]["failed"], item["values"]["skipped"], item["values"]["expected"]), (len(names), 0, 0, len(names)))
            self.assertEqual(item["values"]["missing"], [])
            self.assertIn("통과 %d 실패 0 건너뜀 0" % len(names), item["values"]["brief"])
            self.assertIn("앱 점검 목록 %d개와 같다" % len(names), item["values"]["brief"])
        portable = find(self.results, "M22")[0]
        self.assertEqual(portable["status"], "pass")
        self.assertEqual(portable["values"]["passed"], len(names))
        for arm in "ABC":
            self.assertEqual(self.report["gates"][arm]["G8"]["status"], "pass", arm)

    def test_results_for_the_small_app_and_for_the_real_bundle_are_on_separate_lines(self):
        for number, title in (("M05", "무음 설치"), ("M06", "설치 결과"), ("M12", "제거"), ("M19", "긴·한글 경로")):
            small, real = line_of(self.lines, "%s %s(작은 앱)" % (number, title)), line_of(self.lines, "%s %s(실제 묶음)" % (number, title))
            self.assertIn("| A ", small, number)
            self.assertNotIn("| A ", real, number)                                                     # 갈래 A 는 실제 묶음을 따로 재지 않는다
            self.assertNotIn(" / ", small + real, number)

    def test_the_sizes_line_lists_every_step_time_and_is_not_cut(self):
        line = line_of(self.lines, "M20 ")
        for step in ("install-tools", "build-bundles", "pack"):
            self.assertRegex(line, step + r" [0-9.]+s")
        self.assertFalse(line.endswith("…"))

    def test_the_standard_user_gate_passes_with_the_note_that_the_real_check_is_handed_over(self):
        for arm in "ABC":
            self.assertEqual(find(self.results, "M18", arm)[0]["status"], "unavailable")
            self.assertEqual(self.report["gates"][arm]["G1"]["status"], "pass")
        g1 = line_of(self.lines, "G1 ")
        self.assertEqual(g1.count("(표준 사용자는 운영자 실기)"), 3)

    def test_the_long_path_install_reaches_the_length_the_design_asks_for(self):
        for item in find(self.results, "M19"):
            self.assertGreaterEqual(item["values"]["path_chars"], run.measure.LONG_PATH_CHARS, item["arm"])
            self.assertIn("경로 %d자" % item["values"]["path_chars"], item["values"]["brief"])

    def test_a_quick_install_gets_no_note_about_the_hook_time_limit(self):
        for item in find(self.results, "M05"):
            self.assertFalse(item["values"].get("near_hook_limit"), item["arm"])
            self.assertNotIn("훅 한도", item["values"]["brief"])

    def test_the_defender_status_is_told_in_words(self):
        status = [item for item in find(self.results, "M16") if item["values"].get("target") == "status"][0]
        self.assertEqual(status["values"]["brief"], "실시간 보호 켜짐")
        self.assertIn("M16 Defender(러너 상태) | 기록 실시간 보호 켜짐", self.report["block"])

class VelopackHookLogFlowTest(unittest.TestCase):
    """결정 D-810 — Velopack 설치 로그의 훅 줄을 M05 실제 묶음 기록에 인용한다(설계서 F1 을 직접 확인하려고 — 1차 측정은 이 로그를 읽지 않았다)."""
    LOG = "Setup start\nRunning post-install hook: ChanceBlogDesktop.exe --veloapp-install 0.1.0\nhook timed out after 30 seconds, killing process\nSetup done\n"

    def full(self, **switches):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, work, codes = pipeline(tmp.name, **switches)
        return read(work, "results.json"), read(work / "report", "INSTALLER_SPIKE_REPORT.json")

    def test_the_hook_lines_are_quoted_for_the_velopack_real_install_and_the_brief_counts_them(self):
        results, report = self.full(velopack_log_text=self.LOG)
        item = find(results, "M05", "B", "real")[0]
        self.assertEqual(item["status"], "pass")
        self.assertEqual(item["values"]["hook_log_count"], 2)
        self.assertEqual(len(item["values"]["hook_log"]), 2)
        self.assertIn("timed out after 30 seconds", item["values"]["hook_log"][1])
        self.assertIn("설치 로그에 훅 줄 2개", item["values"]["brief"])
        self.assertIn("설치 로그의 훅 줄:", item["note"])
        self.assertIn("M05 무음 설치(실제 묶음) | B 통과 종료 0 0.5초 앱 안 뜸 · 설치 로그에 훅 줄 2개", report["block"])
        self.assertEqual(find(results, "M05", "C", "real")[0]["values"]["hook_log_count"], 0)              # Inno 는 훅이 없다 — 로그를 읽지 않는다

    def test_without_a_log_text_nothing_is_added(self):
        results, report = self.full()
        item = find(results, "M05", "B", "real")[0]
        self.assertEqual((item["values"]["hook_log"], item["values"]["hook_log_count"]), ([], 0))
        self.assertNotIn("설치 로그에 훅", item["values"]["brief"])
        self.assertNotIn("설치 로그의 훅 줄", item["note"])


class RealBundleHookProbeWordsTest(unittest.TestCase):
    """결정 D-810 — M07 실제 묶음 훅 줄은 탐침이 표준 입출력을 NUL 로 쥐여 줘 앱의 메시지 상자 길을 보지 못한다는 한계를 줄에 적는다(1차 측정은 종료 코드 2·창 0·멈춤 0 만 적어 문제가 없는 것처럼 읽혔다)."""

    def test_the_line_and_the_note_name_the_limit_of_the_probe(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, work, codes = pipeline(tmp.name, commands=("install-tools", "build-bundles", "pack"))
        ctx, report = light_measure(world, work)
        item = [entry for entry in find(ctx.results, "M07", "-") if entry["values"].get("target") == "real"][0]
        self.assertEqual(item["status"], "info")
        self.assertIn("표준 입출력을 NUL 로 쥐여 준 탐침", item["values"]["brief"])
        self.assertIn("Velopack 이 직접 부를 때와 다를 수 있다", item["values"]["brief"])
        self.assertIn("gui_entry.say", item["note"])
        self.assertIn("M05 실제 묶음 설치 시간", item["note"])


class MissingInstallerWordsTest(unittest.TestCase):
    """결정 D-810 — 1차 측정 상자의 'C 시도 불가 없음' 은 무엇이 없는지 알 수 없었다."""

    def test_a_missing_arm_is_described_in_the_lines_that_need_its_installer(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, work, codes = pipeline(tmp.name, iscc_missing=True)
        report = read(work / "report", "INSTALLER_SPIKE_REPORT.json")
        lines = block_lines(report)
        for prefix in ("M04 관리자 요구", "M14 접속 차단", "M18 표준 사용자", "M05 무음 설치(작은 앱)", "M05 무음 설치(실제 묶음)"):
            line = line_of(lines, prefix)
            self.assertIn("C 시도 불가 설치 파일 없음(앞 단계에서 이 갈래를 만들지 못했다)", line, prefix)
        self.assertNotIn("시도 불가 없음", report["block"])
        self.assertIn("만들기 문제: C=", report["block"])
        self.assertIn("Inno 없음(", lines[1])


class SelftestShapesTest(unittest.TestCase):
    """결정 D-810 — 설치본·휴대용 `--selftest` 가 찍는 점검의 여러 모양."""

    def full(self, **switches):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, work, codes = pipeline(tmp.name, **switches)
        return read(work, "results.json"), read(work / "report", "INSTALLER_SPIKE_REPORT.json")

    def verdicts(self, results):
        return [find(results, "M06", arm, "real")[0] for arm in "BC"] + find(results, "M22")

    def test_the_twelve_checks_of_the_old_world_are_now_short_of_the_apps_list(self):
        everything = fakeworld_names()
        names = [name for name in everything if name != "tls"]                                  # 1차 측정이 가정한 열두 점검 — 앱은 그 사이 tls 를 더했다
        self.assertEqual(len(names), len(everything) - 1)                                       # 개수를 못박지 않고 계산한다 — 다른 갈래가 점검을 더하거나 빼도(같은 상수를 두 갈래가 고쳐도) 합친 나무에서 깨지지 않는다
        self.assertIn("tls", everything)
        results, report = self.full(selftest_names=names)
        for item in self.verdicts(results):
            self.assertEqual(item["status"], "fail")
            self.assertEqual(item["values"]["missing"], ["tls"])
            self.assertIn("tls", item["values"]["brief"])
        for arm in "ABC":
            self.assertEqual(report["gates"][arm]["G8"]["status"], "fail", arm)

    def test_a_check_the_app_added_later_does_not_fail_the_bundle(self):
        results, report = self.full(selftest_names=list(fakeworld_names()) + ["brand_new_check"])
        for item in self.verdicts(results):
            self.assertEqual(item["status"], "pass")
            self.assertEqual(item["values"]["extra"], ["brand_new_check"])
            self.assertIn("brand_new_check", item["values"]["brief"])
        for arm in "ABC":
            self.assertEqual(report["gates"][arm]["G8"]["status"], "pass")

    def test_a_failed_check_still_fails_even_when_the_list_is_complete(self):
        results, report = self.full(selftest_fail={"qt_screens"})
        for item in self.verdicts(results):
            self.assertEqual(item["status"], "fail")
            self.assertEqual(item["values"]["bad"], ["qt_screens"])
            self.assertEqual(item["values"]["missing"], ["qt_screens"])                       # 점검 줄은 찍혔지만 통과 줄이 아니다

    def test_without_the_apps_list_the_floor_of_twelve_decides(self):
        with mock.patch.object(run.measure, "app_selftest_keys", lambda repo=None: ()):
            results, report = self.full()
            for item in self.verdicts(results):
                self.assertEqual(item["status"], "pass")                                       # 열세 줄도 통과(1차 측정은 여기서 실패로 적었다)
                self.assertIn("목록을 읽지 못해 통과 12개 이상으로 본다", item["values"]["brief"])

    def test_a_nonzero_exit_after_every_check_line_passed_still_fails_and_the_box_says_why(self):
        """재작업 S-R4 — 점검 줄이 모두 통과로 찍혀도 종료 코드가 0 이 아니면 통과가 아니다. 상자가 '통과 13 실패 0 건너뜀 0 · 앱 점검 목록 13개와 같다' 만 말하면 왜 실패인지 알 수 없다(1차 측정의 G8 실패처럼)."""
        names = fakeworld_names()
        results, report = self.full(selftest_rc=3)
        for item in self.verdicts(results):
            self.assertEqual(item["status"], "fail")
            self.assertEqual((item["values"]["passed"], item["values"]["failed"], item["values"]["skipped"], item["values"]["missing"]), (len(names), 0, 0, []))     # 점검 줄은 모두 통과였다
            self.assertEqual(item["values"]["rc"], 3)
            self.assertIn("통과 %d 실패 0 건너뜀 0 · 앱 점검 목록 %d개와 같다" % (len(names), len(names)), item["values"]["brief"])
            self.assertIn("깨끗하지 않음: 종료 코드 3", item["values"]["brief"])
        for arm in "ABC":
            self.assertEqual(report["gates"][arm]["G8"]["status"], "fail", arm)
        self.assertEqual(report["block"].count("깨끗하지 않음: 종료 코드 3"), 3)                    # 상자의 세 칸 — M06 실제 묶음 B·C 와 M22 휴대용

    def test_a_selftest_that_timed_out_after_every_check_line_is_named_in_the_counts_and_fails(self):
        for label, switches, word in (("시간 초과", {"selftest_timed_out": True}, "시간 초과"), ("종료 코드", {"selftest_rc": 7}, "종료 코드 7")):
            with self.subTest(label):
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                world = FakeWorld(tmp.name, **switches)
                exe = Path(tmp.name) / "app" / "ChanceBlogDesktop.exe"
                exe.parent.mkdir()
                exe.write_bytes(b"MZ")
                counts = run.measure.real_selftest(run.Context(Path(tmp.name) / "work", host=world), exe)
                self.assertFalse(counts["ok"])
                self.assertEqual((counts["failed"], counts["skipped"], counts["missing"]), (0, 0, []))
                self.assertEqual(counts["passed"], len(fakeworld_names()))
                self.assertIs(counts["timed_out"], label == "시간 초과")
                self.assertIs(counts["judged"], True)                                          # 빌드 판정은 점검 줄만 보므로 통과다 — 그래서 종료 코드·시간 초과를 따로 근거에 적는다
                self.assertIn("깨끗하지 않음: " + word, counts["basis"])
                self.assertIn(word, run.measure.selftest_brief("설치본", counts))


class InnoShapesTest(unittest.TestCase):
    """결정 D-810 — Inno Setup 판을 여러 방법으로 읽고 6.5.0 이상이면 쓴다. 읽지 못하면 '미확인' 으로 계속 진행한다."""
    REGISTRY_671 = ["Inno Setup version 6.7.1|6.7.1|"]

    def light(self, **switches):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, work, codes = pipeline(tmp.name, commands=("install-tools", "build-bundles", "pack"), **switches)
        ctx, report = light_measure(world, work)
        state = read(work, "state.json")
        return world, state, ctx.results, report

    def built(self, state):
        return sorted(state["installers"]["C"].get("tiny", {})) == ["0.0.1", "0.0.2", "0.0.3"]

    def test_a_blank_file_version_is_replaced_by_the_registry_entry(self):
        world, state, results, report = self.light(iscc_version="0.0.0.0", iscc_registry=self.REGISTRY_671)
        iscc = state["tools"]["iscc"]
        self.assertEqual((iscc["version"], iscc["version_source"], iscc["version_ok"], iscc["design_line"]), ("6.7.1", "레지스트리", True, True))
        self.assertEqual(iscc["version_reads"], {"usage": "", "registry": "6.7.1", "product": "0.0.0.0", "file": "0.0.0.0"})
        self.assertTrue(self.built(state))
        self.assertEqual(state["pack_problems"], {})
        self.assertEqual(find(results, "M01", "C")[0]["status"], "pass")
        self.assertIn("Inno 6.7.1(레지스트리)", block_lines(report)[1])

    def test_when_nothing_can_be_read_the_work_goes_on_and_the_box_says_unconfirmed_with_the_reason(self):
        world, state, results, report = self.light(iscc_version="0.0.0.0")
        iscc = state["tools"]["iscc"]
        self.assertEqual((iscc["status"], iscc["version"], iscc["version_ok"], iscc["version_source"]), ("ok", "", None, ""))
        self.assertIn("파일 판 빈 값 0.0.0.0", iscc["version_reason"])
        self.assertTrue(self.built(state))                                                       # 1차 측정은 여기서 멈췄다
        self.assertEqual(state["pack_problems"], {})
        item = find(results, "M01", "C")[0]
        self.assertEqual(item["status"], "info")
        self.assertIn("Inno 판 미확인(", item["values"]["brief"])
        self.assertIn("계속 진행", item["values"]["brief"])
        header = block_lines(report)[1]
        self.assertIn("Inno 판 미확인(", header)
        self.assertNotIn("만들기 문제", report["block"])

    def test_a_version_the_compiler_prints_while_compiling_fills_in_what_could_not_be_read_before(self):
        world, state, results, report = self.light(iscc_version="0.0.0.0", iscc_compile_banner="Compiler engine version: Inno Setup 6.7.1")
        iscc = state["tools"]["iscc"]
        self.assertEqual((iscc["version"], iscc["version_source"], iscc["version_ok"], iscc["design_line"]), ("6.7.1", "컴파일 출력", True, True))
        self.assertEqual(iscc["compile_version"], "6.7.1")
        self.assertTrue(self.built(state))
        self.assertIn("Inno 6.7.1(컴파일 출력)", block_lines(report)[1])
        self.assertEqual(find(results, "M01", "C")[0]["status"], "pass")

    def test_a_low_version_found_only_after_compiling_is_recorded_without_undoing_the_work(self):
        world, state, results, report = self.light(iscc_version="0.0.0.0", iscc_compile_banner="Compiler engine version: Inno Setup 6.3.0")
        iscc = state["tools"]["iscc"]
        self.assertEqual((iscc["version"], iscc["version_ok"]), ("6.3.0", False))
        self.assertTrue(self.built(state))
        item = find(results, "M01", "C")[0]
        self.assertEqual(item["status"], "fail")
        self.assertIn("6.5.0 보다 낮아 쓰지 않는다", item["values"]["brief"])

    def test_the_banner_does_not_overrule_a_version_that_was_read_before(self):
        world, state, results, report = self.light(iscc_version="6.7.1.0", iscc_compile_banner="Compiler engine version: Inno Setup 6.9.9")
        iscc = state["tools"]["iscc"]
        self.assertEqual((iscc["version"], iscc["compile_version"]), ("6.7.1.0", "6.9.9"))

    def test_the_compilers_own_usage_text_comes_first_then_the_registry_then_the_file_resources(self):
        world, state, results, report = self.light(iscc_version="6.5.0.0", iscc_product_version="6.6.0.0", iscc_registry=self.REGISTRY_671, iscc_usage_text="Compiler engine version: Inno Setup 6.8.2\n")
        self.assertEqual((state["tools"]["iscc"]["version"], state["tools"]["iscc"]["version_source"]), ("6.8.2", "컴파일러 출력"))
        world, state, results, report = self.light(iscc_version="6.5.0.0", iscc_product_version="6.6.0.0", iscc_registry=self.REGISTRY_671)
        self.assertEqual((state["tools"]["iscc"]["version"], state["tools"]["iscc"]["version_source"]), ("6.7.1", "레지스트리"))
        world, state, results, report = self.light(iscc_version="6.5.0.0", iscc_product_version="6.6.0.0")
        self.assertEqual((state["tools"]["iscc"]["version"], state["tools"]["iscc"]["version_source"]), ("6.6.0.0", "파일 제품 판"))
        world, state, results, report = self.light(iscc_version="6.5.0.0", iscc_product_version="0.0.0.0")
        self.assertEqual((state["tools"]["iscc"]["version"], state["tools"]["iscc"]["version_source"]), ("6.5.0.0", "파일 판"))

    def test_the_gate_is_six_point_five_and_a_version_off_the_design_line_is_only_noted(self):
        cases = (("6.5.0.0", True, True, False), ("6.4.9.9", False, False, False), ("7.1.1.0", True, True, False), ("6.8.0.0", True, True, False), ("6.7.1.0", True, True, True), ("6.5.4.0", True, True, False))
        for version, version_ok, built, design_line in cases:
            with self.subTest(version):
                world, state, results, report = self.light(iscc_version=version)
                iscc = state["tools"]["iscc"]
                self.assertEqual((iscc["version_ok"], self.built(state), iscc["design_line"]), (version_ok, built, design_line), version)
                self.assertEqual(("C" in state["pack_problems"]), not built)
                self.assertEqual(find(results, "M01", "C")[0]["status"], "pass" if version_ok else "fail")
                if version_ok and not design_line:
                    self.assertIn("설계서의 6.7 줄이 아님", find(results, "M01", "C")[0]["values"]["brief"])
                if not version_ok:
                    self.assertIn("Inno Setup 을 쓸 수 없다", state["pack_problems"]["C"])
                    self.assertIn("6.5.0 보다 낮다", state["pack_problems"]["C"])
                    self.assertEqual(world.compile_calls, 0)

    def test_unreadable_file_versions_of_every_shape_mean_unconfirmed_not_refused(self):
        for version in ("0.0.0.0", "", "garbage", "0.0", "6"):
            with self.subTest(version):
                world, state, results, report = self.light(iscc_version=version)
                self.assertIsNone(state["tools"]["iscc"]["version_ok"], version)
                self.assertTrue(self.built(state), version)

    def test_reading_the_version_only_reads_it_never_writes_to_the_registry_or_compiles(self):
        world, state, results, report = self.light(iscc_version="0.0.0.0")
        scripts = [call[-1] for call in world.calls if call[0] == "powershell"]
        self.assertTrue(any("Get-ItemProperty" in script for script in scripts))
        for script in scripts:
            for word in ("Set-ItemProperty", "New-ItemProperty", "Remove-Item", "New-Item", "reg add", "reg delete", "Set-Content"):
                self.assertNotIn(word, script)
        usage_calls = [call for call in world.calls if call[0].endswith("ISCC.exe") and call[1:] == ["/?"]]
        self.assertEqual(len(usage_calls), 1)

    def test_a_registry_with_two_inno_versions_is_read_for_the_one_that_holds_the_compiler(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        inno_folder = str(Path(tmp.name) / "inno")                                                 # 가짜 세계의 which 가 돌려주는 ISCC 의 폴더
        registry = ["Inno Setup version 6.7.1|6.7.1|C:\\Elsewhere\\", "Inno Setup version 6.5.4|6.5.4|" + inno_folder + "\\"]
        world, work, codes = pipeline(tmp.name, commands=("install-tools",), iscc_version="0.0.0.0", iscc_registry=registry)
        self.assertEqual(read(work, "state.json")["tools"]["iscc"]["version"], "6.5.4")           # 폴더가 맞는 항목이 먼저다(첫 항목이 아니라)
        tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(tmp2.cleanup)
        world, work, codes = pipeline(tmp2.name, commands=("install-tools",), iscc_version="0.0.0.0", iscc_registry=["Inno Setup version 6.7.1|6.7.1|C:\\Elsewhere\\", "Inno Setup version 6.5.4|6.5.4|C:\\Else\\"])
        self.assertEqual(read(work, "state.json")["tools"]["iscc"]["version"], "6.7.1")           # 어느 항목의 폴더도 안 맞으면 첫 항목


class VpkVersionShapesTest(unittest.TestCase):
    """결정 D-810 — vpk 판을 읽는 방법(1차 측정은 `vpk --version` 출력에서 판을 못 읽어 머리 칸이 비었는데도 M01 을 통과로 적었다)."""

    def installed(self, **switches):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, work, codes = pipeline(tmp.name, commands=("install-tools",), **switches)
        ctx = run.Context(work, host=world)
        ctx.results = []
        run.measure.m01_tools(ctx)
        return read(work, "state.json")["tools"]["vpk"], ctx

    def test_the_tools_own_output_is_read_first(self):
        vpk, ctx = self.installed()
        self.assertEqual((vpk["version"], vpk["version_source"], vpk["version_ok"]), ("1.2.161", "vpk --version", True))
        item = find(ctx.results, "M01", "A")[0]
        self.assertEqual((item["status"], item["values"]["brief"]), ("pass", "vpk 1.2.161"))

    def test_when_the_output_has_no_version_the_tool_list_is_read(self):
        vpk, ctx = self.installed(vpk_version_text="")
        self.assertEqual((vpk["version"], vpk["version_source"], vpk["version_ok"]), ("1.2.161", "dotnet tool list", True))
        for arm in "AB":
            item = find(ctx.results, "M01", arm)[0]
            self.assertEqual((item["status"], item["values"]["brief"]), ("pass", "vpk 1.2.161(dotnet tool list)"))

    def test_when_neither_says_the_version_the_locked_value_fills_the_box_and_says_where_it_came_from(self):
        vpk, ctx = self.installed(vpk_version_text="", vpk_tool_list=False)
        self.assertEqual(vpk["version"], "1.2.161")
        self.assertIn("잠금 파일", vpk["version_source"])
        item = find(ctx.results, "M01", "B")[0]
        self.assertEqual(item["status"], "pass")
        self.assertIn("vpk 1.2.161(잠금 파일", item["values"]["brief"])
        self.assertEqual(item["values"]["version_source"], vpk["version_source"])

    def test_a_tool_that_names_another_version_than_the_locked_one_fails_the_check(self):
        vpk, ctx = self.installed(vpk_version_text="vpk 1.2.999\n")
        self.assertEqual((vpk["version"], vpk["version_ok"]), ("1.2.999", False))
        for arm in "AB":
            self.assertEqual(find(ctx.results, "M01", arm)[0]["status"], "fail")

    def test_the_list_reader_finds_the_vpk_row_and_nothing_else(self):
        self.assertEqual(run.vpk_listed_version("Package Id      Version      Commands\n----\nvpk             1.2.161      vpk\n"), "1.2.161")
        self.assertEqual(run.vpk_listed_version("VPK 1.2.161.4 vpk"), "1.2.161.4")
        for text in ("", None, "Package Id Version Commands\n-----\n", "other-tool   1.2.161   x\n", "xvpk 1.2.161"):
            self.assertEqual(run.vpk_listed_version(text), "", text)


class StandardUserOutcomeTest(unittest.TestCase):
    """결정 D-810 — 표준 사용자 시험(M18)의 결과 가르기: 확인한 것만 통과·실패, 확인하지 못한 것은(1차 측정이 '실패' 로 적은 '종료 0 인데 흔적 없음' 포함) 이유를 적은 '시도 불가'."""

    def attempt(self, arm="A", **switches):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, ctx = light_m18(tmp.name, arm=arm, **switches)
        return world, ctx, ctx.results[-1]

    def test_exit_zero_without_any_trace_is_handed_over_with_the_reason(self):
        world, ctx, item = self.attempt(std_silent=True)
        self.assertEqual(item["status"], "unavailable")
        self.assertEqual(item["values"]["brief"], "종료 0 인데 설치 흔적 없음 — 운영자 실기로")
        self.assertEqual((item["values"]["exit_kind"], item["values"]["exit_code"], item["values"]["traces"]), ("code", 0, []))
        self.assertEqual(item["values"]["probe"], {"launched": True, "exit_code_readable": True, "kind": "code"})
        self.assertIn("T-INST-04", item["note"])

    def test_an_exit_code_that_could_not_be_read_is_not_taken_for_zero(self):
        world, ctx, item = self.attempt(std_silent=True, std_exit_readable=False)
        self.assertEqual(item["status"], "unavailable")
        self.assertEqual(item["values"]["brief"], "종료 코드를 읽지 못했고 설치 흔적도 없음 — 운영자 실기로")
        self.assertEqual((item["values"]["exit_kind"], item["values"]["exit_code"]), ("none", None))
        self.assertFalse(item["values"]["probe"]["exit_code_readable"])

    def test_a_trace_makes_it_a_pass_even_when_the_exit_code_could_not_be_read(self):
        world, ctx, item = self.attempt(std_user_ok=True, std_exit_readable=False)
        self.assertEqual(item["status"], "pass")
        self.assertIn("(종료 코드는 못 읽음)", item["values"]["brief"])
        self.assertTrue(item["values"]["traces"])

    def test_a_trace_with_exit_zero_is_a_plain_pass(self):
        world, ctx, item = self.attempt(std_user_ok=True)
        self.assertEqual(item["status"], "pass")
        self.assertEqual(item["values"]["brief"], "표준 사용자 설치 성공 0.5초")

    def test_a_trace_that_appears_only_after_the_installer_returned_is_waited_for(self):
        """1차 측정은 설치 도구가 돌아온 바로 뒤에 흔적을 봤다 — 작은 앱 설치는 0.4초 만에 끝났는데 흔적은 그 뒤에 생길 수 있다(M05 는 60초까지 기다린다)."""
        for delay in (3, 12, 40):
            with self.subTest(delay):
                world, ctx, item = self.attempt(std_user_ok=True, std_trace_delay=delay)
                self.assertEqual(item["status"], "pass", delay)
                self.assertTrue(item["values"]["traces"])
        self.assertGreaterEqual(run.measure.STD_WAIT_SECONDS, 40)

    def test_a_trace_that_never_comes_in_time_is_handed_over_not_failed(self):
        world, ctx, item = self.attempt(std_user_ok=True, std_trace_delay=run.measure.STD_WAIT_SECONDS + 30)
        self.assertEqual(item["status"], "unavailable")
        self.assertEqual(item["values"]["brief"], "종료 0 인데 설치 흔적 없음 — 운영자 실기로")

    def test_an_install_that_does_not_finish_in_time_is_handed_over_even_when_a_trace_is_there(self):
        """재작업 Q-R2 — 합격 조건 '시간 안에 끝남': 설치 도구 호출이 시간 안에 끝나지 않았는데 흔적이 보인다고 통과로 적으면 끝나지 않은(반쯤 한) 설치를 통과로 센다. 흔적이 있어도 '시도 불가' 다."""
        for label, switches in (("흔적 있음", {"std_user_ok": True}), ("흔적 없음", {"std_silent": True})):
            with self.subTest(label):
                world, ctx, item = self.attempt(std_timeout=True, **switches)
                self.assertEqual(item["status"], "unavailable")
                self.assertEqual(item["values"]["brief"], "시간 안에 끝나지 않음 — 운영자 실기로")
                self.assertEqual(bool(item["values"]["traces"]), "std_user_ok" in switches)                # 흔적은 있었지만 통과가 아니다
                self.assertIsNone(item["values"]["rc"])
                self.assertLess(world.clock, 20, "시간이 지난 호출은 흔적을 기다리지도 않는다")

    def test_it_does_not_wait_when_the_install_could_not_even_start_or_failed_for_certain(self):
        for switches in ({"std_launch_ok": False}, {"std_silent": True, "std_exit_code": 740}, {"std_silent": True, "std_exit_code": 5}):
            with self.subTest(switches):
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                world, ctx = light_m18(tmp.name, **switches)
                self.assertLess(world.clock, 20, "흔적을 기다리지 않았다(기다렸다면 시계가 STD_WAIT_SECONDS 만큼 흘렀다)")

    def test_every_arm_uses_its_own_user_so_a_new_user_never_meets_a_profile_folder_the_last_one_left(self):
        """같은 이름의 사용자를 지웠다 다시 만들면 윈도는 남은 사용자 폴더 때문에 새 프로필 폴더에 컴퓨터 이름을 붙이고(우리가 찾는 곳이 어긋난다) 남은 폴더의 권한은 옛 사용자만 갖는다 — 1차 측정은 갈래마다 같은 이름을 다시 썼다."""
        layouts = {"A": "velopack", "B": "fake", "C": "inno"}
        names = set()
        for arm in "ABC":
            world, ctx, item = self.attempt(arm, std_user_ok=True, std_layout=layouts[arm])
            name = run.measure.std_user_name(arm)
            adds = [call for call in world.net_calls if "/add" in call]
            self.assertEqual([call[2] for call in adds], [name])
            self.assertEqual(world.ps_calls[1][1]["SPIKE_USER"], name)
            self.assertTrue(world.ps_calls[1][1]["SPIKE_PROFILE"].endswith(name))
            self.assertEqual(item["status"], "pass", arm)
            names.add(name)
        self.assertEqual(len(names), 3)

    def test_a_trace_another_arm_left_in_its_own_user_folder_is_not_taken_for_this_arms(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        first_world, first_ctx = light_m18(tmp.name, arm="A", std_user_ok=True, std_layout="velopack")
        self.assertEqual(first_ctx.results[-1]["status"], "pass")
        left_behind = first_world.users_root / run.measure.std_user_name("A") / "AppData" / "Local" / "ChanceBlogSpikeA" / "current" / "VERSION"
        self.assertTrue(left_behind.is_file())                                                      # 같은 임시 폴더에 갈래 A 의 흔적이 남아 있다
        world, ctx = light_m18(tmp.name, arm="B", std_silent=True)                                  # 갈래 B 는 종료 0 이지만 자기 폴더에는 아무것도 없다
        item = ctx.results[-1]
        self.assertEqual(item["status"], "unavailable")
        self.assertEqual(item["values"]["traces"], [])

    def test_when_the_program_cannot_be_started_as_that_user_the_install_is_not_even_tried(self):
        world, ctx, item = self.attempt(std_launch_ok=False)
        self.assertEqual(item["status"], "unavailable")
        self.assertEqual(item["values"]["brief"], "다른 계정으로 프로그램을 띄우지 못함(The user name or password is incorrect.) — 운영자 실기로")    # 재작업 S-R1 — 형식 이름(띄우기 실패는 늘 같다)이 아니라 윈도의 오류 문장이 이유로 보인다
        self.assertEqual(item["values"]["start_error"], "InvalidOperationException")                       # 형식 이름은 값에 그대로 남는다
        self.assertFalse(item["values"]["probe"]["launched"])
        self.assertEqual(len(world.ps_calls), 1)                                                   # 탐침 하나뿐 — 설치 파일은 돌리지 않았다
        self.assertEqual(world.ps_calls[0][1]["SPIKE_SETUP"], "cmd.exe")

    def test_an_installer_that_demands_an_administrator_fails_the_check(self):
        world, ctx, item = self.attempt(std_silent=True, std_exit_code=740)
        self.assertEqual(item["status"], "fail")
        self.assertEqual(item["values"]["brief"], "설치 도구가 관리자 권한을 요구했다(종료 740)")
        self.assertEqual(item["values"]["exit_code"], 740)

    def test_another_exit_code_without_a_trace_is_handed_over_with_the_code_in_the_reason(self):
        for code in (1, 5, 3010, -1073741502):
            with self.subTest(code):
                world, ctx, item = self.attempt(std_silent=True, std_exit_code=code)
                self.assertEqual(item["status"], "unavailable")
                self.assertEqual(item["values"]["brief"], "종료 %d·설치 흔적 없음 — 운영자 실기로" % code)

    def test_the_traces_each_tool_really_leaves_are_found_wherever_they_are_under_the_users_local_folder(self):
        for arm, layout, expected in (("A", "velopack", "ChanceBlogSpikeA/current/VERSION"), ("C", "inno", "Programs/ChanceBlogSpikeC/VERSION"), ("B", "fake", "Fake/VERSION")):
            with self.subTest(arm):
                world, ctx, item = self.attempt(arm, std_user_ok=True, std_layout=layout)
                self.assertEqual(item["status"], "pass")
                self.assertEqual(item["values"]["traces"], [expected])

    def test_the_probe_runs_first_and_the_install_second_with_a_log_the_user_can_write(self):
        for arm, log_flag in (("A", '--log "'), ("B", '--log "'), ("C", '/LOG="')):
            with self.subTest(arm):
                world, ctx, item = self.attempt(arm, std_silent=True)
                self.assertEqual(len(world.ps_calls), 2)
                probe, install = world.ps_calls[0][1], world.ps_calls[1][1]
                self.assertEqual((probe["SPIKE_SETUP"], probe["SPIKE_ARGS"]), ("cmd.exe", "/d /c exit 42"))
                self.assertTrue(install["SPIKE_SETUP"].endswith("setup-%s.exe" % arm))
                self.assertIn(log_flag, install["SPIKE_ARGS"])
                self.assertIn("std-%s.log" % arm, install["SPIKE_ARGS"])
                self.assertEqual(("--silent" in install["SPIKE_ARGS"]), arm != "C")
                self.assertEqual(("/VERYSILENT" in install["SPIKE_ARGS"]), arm == "C")
                grants = [index for index, call in enumerate(world.calls) if call[0] == "icacls"]
                self.assertEqual(len(grants), 1)
                self.assertEqual(world.calls[grants[0]][2:], ["/grant", run.measure.std_user_name(arm) + ":(OI)(CI)M"])         # 그 임시 사용자가 로그·임시 파일을 쓰려면 읽기만으로는 모자라고, 그 사용자 하나에게만 준다(Users 모두가 아니다)
                self.assertNotIn("Users:", " ".join(world.calls[grants[0]]))

    def test_the_new_users_folders_are_passed_as_explicit_values_and_the_scripts_set_them_before_starting(self):
        world, ctx, item = self.attempt(std_silent=True)
        public = Path(world.environ["PUBLIC"]) / "spike_std"
        for script, env in world.ps_calls:
            self.assertEqual(env["SPIKE_USER"], run.measure.std_user_name("A"))
            self.assertEqual(env["SPIKE_PROFILE"], str(world.users_root / run.measure.std_user_name("A")))     # 러너 계정의 사용자 폴더가 아니다
            self.assertEqual(env["SPIKE_TMP"], str(public / "tmp"))
            self.assertEqual(env["SPIKE_CWD"], str(public))
            self.assertLess(script.index("$env:LOCALAPPDATA = $env:SPIKE_PROFILE"), script.index("Start-Process"))
            self.assertNotIn(world.environ["USERPROFILE"], script)                                     # 러너 계정의 사용자 폴더는 어디에도 쓰지 않는다
            for value in env.values():
                self.assertNotIn(world.environ["USERPROFILE"], value)
                self.assertNotIn(world.environ["LOCALAPPDATA"], value)

    def test_the_installers_own_log_tail_joins_the_reason_with_the_password_hidden(self):
        world, ctx, item = self.attempt(std_silent=True, std_log_text=lambda password: "Setup log\nuser pw " + password + "\nerror 0x5 access denied\n")
        self.assertEqual(item["status"], "unavailable")
        self.assertIn("설치 도구 로그 끝:", item["note"])
        self.assertIn("error 0x5 access denied", item["note"])
        self.assertEqual(longest_piece(everything_left(world, ctx), LIGHT_PASSWORD), 0)

    def test_a_log_tail_that_cuts_the_password_in_the_middle_leaves_no_piece_because_the_hiding_comes_first(self):
        """재작업 S-R8·Q-R4 — 설치 도구 로그 끝(120자)은 '가린 뒤에 자른다'. 로그가 120자보다 짧거나 꼬리가 비밀번호를 가르지 않으면 이 순서가 지켜지는지 알 수 없다 — 꼬리가 비밀번호 한가운데에서 시작하게 만든다
        (StandardUserEchoTest 의 160자 꼬리 시험과 같은 모양)."""
        def log_text(password):
            return "x" * 100 + password + "y" * 110
        raw_tail = run.measure.tail(log_text(LIGHT_PASSWORD), 120)
        self.assertGreaterEqual(longest_piece(raw_tail, LIGHT_PASSWORD), 4)                      # 사전 확인: 자르기만 하면 비밀번호 조각이 꼬리에 남는다
        self.assertNotIn(LIGHT_PASSWORD, raw_tail)
        world, ctx, item = self.attempt(std_silent=True, std_log_text=log_text)
        self.assertIn("설치 도구 로그 끝:", item["note"])
        self.assertIn("<가림>", item["note"])
        self.assertEqual(longest_piece(everything_left(world, ctx), LIGHT_PASSWORD), 0)

    def test_no_log_means_no_log_sentence(self):
        world, ctx, item = self.attempt(std_silent=True)
        self.assertNotIn("설치 도구 로그 끝", item["note"])
        self.assertEqual(item["values"]["log_chars"], 0)

    def test_the_user_and_the_work_folder_are_removed_in_every_outcome(self):
        outcomes = ({"std_silent": True}, {"std_user_ok": True}, {"std_launch_ok": False}, {"std_silent": True, "std_exit_code": 740}, {})
        for switches in outcomes:
            with self.subTest(switches):
                world, ctx, item = self.attempt(**switches)
                self.assertEqual([call for call in world.net_calls if "/delete" in call], [["net", "user", run.measure.std_user_name("A"), "/delete"]])
                self.assertFalse((Path(world.environ["PUBLIC"]) / "spike_std").exists())

    def test_the_two_early_stops_do_not_say_try_failed_either(self):
        first, second = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.addCleanup(first.cleanup)
        self.addCleanup(second.cleanup)
        world, ctx = light_m18(first.name, environ={"PUBLIC": None})
        self.assertEqual(ctx.results[-1]["values"]["brief"], "환경 변수 PUBLIC 없음(임시 사용자를 만들지 않았다) — 운영자 실기로")
        world, ctx = light_m18(second.name, net_user_ok=False)
        self.assertEqual(ctx.results[-1]["values"]["brief"], "임시 사용자 만들기 실패 — 운영자 실기로")
        self.assertEqual(ctx.results[-1]["status"], "unavailable")


class StandardUserLaunchMessageTest(unittest.TestCase):
    """독립 검증 재작업 권고 S-R1 — 다른 계정으로 띄우지 못했을 때 형식 이름(`Start-Process` 의 띄우기 실패는 모두 `InvalidOperationException`)만 남기면 로그온 거부·서비스 꺼짐·권한 상승 필요를 가를 수 없어
    2차 상자에서 원인을 또 모른다. 스크립트가 윈도의 오류 문장을 한 줄(`SPIKE_START_MESSAGE=`)로 더 찍고, 도구가 비밀번호를 가린 **뒤에** 잘라 상자·기록에 싣는다. 설치 도구가 관리자 권한을 요구해 띄우는 단계에서 막히면
    (종료 740 이 아니라 이 오류로 막힌다) 실패(관리자 요구)이고, 아무것도 안 하는 탐침이 그렇게 막히는 것은 설치 도구의 탓이 아니므로 시도 불가다."""
    ELEVATION = "This command cannot be run due to the error: The requested operation requires elevation."
    WRONG_PASSWORD = "This command cannot be run due to the error: The user name or password is incorrect."

    def attempt(self, arm="A", **switches):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world, ctx = light_m18(tmp.name, arm=arm, **switches)
        return world, ctx, ctx.results[-1]

    def test_the_windows_sentence_is_the_reason_in_the_box_the_note_and_the_values(self):
        world, ctx, item = self.attempt(std_launch_ok=False)                                                # 가짜 세계의 기본 문장: 로그온 거부
        self.assertEqual(item["status"], "unavailable")
        self.assertEqual(item["values"]["brief"], "다른 계정으로 프로그램을 띄우지 못함(The user name or password is incorrect.) — 운영자 실기로")
        self.assertEqual((item["values"]["start_error"], item["values"]["start_message"]), ("InvalidOperationException", self.WRONG_PASSWORD))
        self.assertEqual(item["values"]["probe"]["message"], self.WRONG_PASSWORD)
        self.assertIn("윈도 오류 문장(InvalidOperationException): " + self.WRONG_PASSWORD, item["note"])
        line = run.measurement_lines(ctx.results, "M18")[0]
        self.assertTrue(line.endswith(item["values"]["brief"]), line)                                      # 상자의 한 칸이 이유를 자르지 않고 그대로 싣는다

    def test_without_a_message_line_the_type_name_alone_is_shown_as_it_was_before(self):
        world, ctx, item = self.attempt(std_launch_ok=False, std_launch_message="")
        self.assertEqual(item["values"]["brief"], "다른 계정으로 프로그램을 띄우지 못함(InvalidOperationException) — 운영자 실기로")
        self.assertEqual((item["values"]["start_error"], item["values"]["start_message"]), ("InvalidOperationException", ""))
        self.assertNotIn("message", item["values"]["probe"])
        self.assertNotIn("윈도 오류 문장", item["note"])

    def test_an_installer_that_cannot_be_started_after_a_good_probe_says_why_and_the_probe_stayed_clean(self):
        world, ctx, item = self.attempt(std_install_launch_ok=False)
        self.assertEqual(item["status"], "unavailable")
        self.assertEqual(item["values"]["brief"], "다른 계정으로 설치 프로그램을 띄우지 못함(The user name or password is incorrect.) — 운영자 실기로")
        self.assertEqual((item["values"]["start_error"], item["values"]["start_message"]), ("InvalidOperationException", self.WRONG_PASSWORD))
        self.assertEqual(item["values"]["probe"], {"launched": True, "exit_code_readable": True, "kind": "code"})      # 탐침은 띄워졌다 — 탐침 칸에는 오류 문장이 없다
        self.assertEqual(len(world.ps_calls), 2)
        self.assertIn("윈도 오류 문장(InvalidOperationException): " + self.WRONG_PASSWORD, item["note"])

    def test_an_installer_the_system_refuses_to_start_without_elevation_fails_the_check_and_the_gate(self):
        world, ctx, item = self.attempt(std_install_launch_ok=False, std_launch_message=self.ELEVATION)
        self.assertEqual(item["status"], "fail")
        self.assertTrue(item["values"]["brief"].startswith("설치 도구가 관리자 권한을 요구했다(띄우기 단계에서 막힘: "), item["values"]["brief"])
        self.assertIn("The requested operation requires elevation.", item["values"]["brief"])
        self.assertNotIn("종료 740", item["values"]["brief"])                                               # 종료 코드로 끝난 것이 아니라 띄우기 자체가 막혔다
        self.assertEqual((item["values"]["start_error"], item["values"]["start_message"]), ("InvalidOperationException", self.ELEVATION))
        self.assertIn("종료 코드(740)로 끝난 것이 아니라", item["note"])
        gates = run.judge([run.record("M04", "A", "pass", brief="수준 asInvoker"), item])
        self.assertEqual(gates["A"]["G1"]["status"], "fail")                                               # 관문 G1 도 실패 — 매니페스트가 통과여도 표준 사용자 설치가 관리자 권한을 요구하면 탈락
        self.assertNotIn("open", gates["A"]["G1"])

    def test_the_probe_that_is_stopped_for_elevation_is_not_the_installers_fault(self):
        world, ctx, item = self.attempt(std_launch_ok=False, std_launch_message=self.ELEVATION)
        self.assertEqual(item["status"], "unavailable")                                                     # 아무것도 안 하는 프로그램이 막힌 것은 설치 도구가 관리자 권한을 요구한 것이 아니다
        self.assertEqual(len(world.ps_calls), 1)
        self.assertIn("The requested operation requires elevation.", item["values"]["brief"])

    def test_other_words_for_the_need_of_elevation_are_recognized_and_lookalikes_are_not(self):
        measure = run.measure
        for text in ("The requested operation requires elevation.", "ELEVATION is required", "요청한 작업을 수행하려면 권한 상승이 필요합니다.", "오류 740", "error 740: x", "(Win32 740)", "code=740"):
            self.assertTrue(measure.std_needs_elevation(text), text)
        for text in ("", None, "The user name or password is incorrect.", "Access is denied.", "spike740user", "error 7400", "1740", "7401", "The system cannot find the file specified."):
            self.assertFalse(measure.std_needs_elevation(text), text)

    def test_the_sentence_is_cut_after_the_password_is_hidden_so_no_piece_of_the_password_is_left(self):
        """가린 뒤에 자른다 — 자른 뒤에 가리면 비밀번호 한가운데가 잘려 가릴 낱말 전체가 안 맞고 조각이 남는다(설치 도구 로그 꼬리와 같은 규칙)."""
        cut_in_the_sentence = "q" * 20 + LIGHT_PASSWORD + "z" * 190                                            # 200자 꼬리가 비밀번호의 열두 번째 글자에서 시작한다(문장을 싣는 자리)
        cut_in_the_note_tail = "q" * 20 + LIGHT_PASSWORD + "z" * 150                                       # 문장은 200자 안이지만 메모의 160자 꼬리(표지 줄 포함 원문 끝)가 비밀번호를 가른다
        self.assertEqual(longest_piece(cut_in_the_sentence[-run.measure.STD_MESSAGE_LIMIT:], LIGHT_PASSWORD), len(LIGHT_PASSWORD) - 12)       # 사전 확인: 자르기만 하면 조각이 남는다
        raw_text = "SPIKE_START_ERROR=InvalidOperationException\r\nSPIKE_START_MESSAGE=" + cut_in_the_note_tail + "\r\n"
        self.assertEqual(longest_piece(raw_text.strip()[-160:], LIGHT_PASSWORD), len(LIGHT_PASSWORD) - 12)                    # 사전 확인: 160자 꼬리가 비밀번호의 열두 번째 글자에서 시작한다
        self.assertNotIn(LIGHT_PASSWORD, raw_text.strip()[-160:])
        self.assertLessEqual(len(cut_in_the_note_tail), run.measure.STD_MESSAGE_LIMIT)                                         # 문장 자리의 200자 자르기는 이 경우를 자르지 않는다 — 메모 꼬리만 시험한다
        for label, sentence in (("문장 자리", cut_in_the_sentence), ("메모 꼬리", cut_in_the_note_tail)):
            for switches in ({"std_launch_ok": False}, {"std_install_launch_ok": False}):
                with self.subTest((label, tuple(switches))):
                    world, ctx, item = self.attempt(std_launch_message=sentence, **switches)
                    self.assertIn("<가림>", item["note"])
                    self.assertEqual(longest_piece(everything_left(world, ctx), LIGHT_PASSWORD), 0)

    def test_a_long_or_many_line_sentence_is_folded_to_one_line_and_the_reason_fits_the_box_cell(self):
        measure = run.measure
        self.assertEqual(measure.parse_std_message("앞\r\nSPIKE_START_MESSAGE=가   나\t다  \r\n뒤\r\n"), "가 나 다")
        self.assertEqual(measure.parse_std_message("SPIKE_START_ERROR=X\r\nSPIKE_START_MESSAGE=\r\n"), "")
        self.assertEqual(measure.parse_std_message("앞 SPIKE_START_MESSAGE=표지가 아니다\r\n"), "")                      # 줄 맨 앞의 표지만 인정한다
        self.assertEqual(measure.parse_std_message(None), "")
        long_sentence = "This command cannot be run due to the error: " + " ".join("word%03d" % number for number in range(200))
        for switches in ({"std_launch_ok": False}, {"std_install_launch_ok": False}):
            with self.subTest(switches):
                world, ctx, item = self.attempt(std_launch_message=long_sentence, **switches)
                brief = item["values"]["brief"]
                self.assertLessEqual(len(brief), run.CELL_LIMIT, brief)                                      # 상자 한 칸이 110자에서 자르기 전에 이유가 들어간다
                self.assertTrue(brief.endswith(") — 운영자 실기로"), brief)
                self.assertLessEqual(len(item["values"]["start_message"]), measure.STD_MESSAGE_LIMIT + 1)
                self.assertNotIn("\n", item["values"]["start_message"])
                self.assertTrue(run.measurement_lines(ctx.results, "M18")[0].endswith(brief))
        world, ctx, item = self.attempt(std_install_launch_ok=False, std_launch_message=self.ELEVATION.replace("The requested", "x" * 400 + " The requested"))
        self.assertEqual(item["status"], "fail")
        self.assertLessEqual(len(item["values"]["brief"]), run.CELL_LIMIT)

    def test_the_reason_words_drop_only_the_boilerplate_and_keep_the_end_of_the_sentence(self):
        measure = run.measure
        self.assertEqual(measure.std_reason_words(self.ELEVATION), "The requested operation requires elevation.")
        self.assertEqual(measure.std_reason_words("This command cannot be run due to the error:"), "This command cannot be run due to the error:")         # 머리말뿐이면 그대로(빈 이유를 만들지 않는다)
        self.assertEqual(measure.std_reason_words("Access is denied."), "Access is denied.")
        self.assertEqual(measure.std_reason_words("가" * 300, 10), "…" + "가" * 10)
        self.assertEqual(measure.std_reason_words(None), "")


class LongPathAndHooksFlowTest(unittest.TestCase):
    """결정 D-810 — 실제 묶음 설치가 Velopack 훅 한도(30초) 가까이 걸리면 그 사실을 적는다(설계서 F1, 1차 측정의 M05 실제 묶음이 30.6초였다)."""

    def test_the_hook_note_only_applies_to_velopack_arms_and_only_near_the_limit(self):
        measure = run.measure
        for arm in "AB":
            self.assertEqual(measure.hook_wait_note(arm, 24.9), "")
            self.assertIn("훅 한도 30초 가까이 걸림", measure.hook_wait_note(arm, 25.0))
            self.assertIn("추정", measure.hook_wait_note(arm, 30.6))
        for seconds in (0.4, 30.6, 400):
            self.assertEqual(measure.hook_wait_note("C", seconds), "")

    def test_a_slow_real_install_is_noted_in_the_box_for_the_velopack_arm_only(self):
        class SlowSetup(FakeWorld):
            def run_setup(self, args, info):
                done = super().run_setup(args, info)
                if info["kind"] == "velopack" and info["exe"] == "ChanceBlogDesktop.exe":
                    return measure_result(done, 30.6)
                return done

        measure_result = lambda done, seconds: run.measure.HostResult(done.rc, seconds, done.out, done.err)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world = SlowSetup(tmp.name)
        work = Path(tmp.name) / "work"
        with mock.patch.object(run.fetch_tools, "check_file", lambda path, tool: ""), mock.patch.object(run, "payload_files", small_payload), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for command in ("install-tools", "build-bundles", "pack", "measure", "report"):
                run.main([command, "--work", str(work)], host=world)
        results = read(work, "results.json")
        slow = find(results, "M05", "B", "real")[0]
        self.assertTrue(slow["values"]["near_hook_limit"])
        self.assertIn("훅 한도 30초 가까이 걸림", slow["values"]["brief"])
        self.assertFalse(find(results, "M05", "C", "real")[0]["values"]["near_hook_limit"])
        self.assertFalse(find(results, "M05", "B", "tiny")[0]["values"]["near_hook_limit"])


class DefenderStatusWordsTest(unittest.TestCase):
    """결정 D-810 — 1차 측정 상자의 '실시간 보호 False' 는 파이썬 값이 그대로 보였다."""

    def status(self, realtime):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ctx = run.Context(Path(tmp.name) / "w", host=FakeWorld(tmp.name, defender_realtime=realtime))
        ctx.results = []
        run.measure.m16_status(ctx)
        return ctx.results[-1]["values"]["brief"]

    def test_on_off_and_unreadable_are_said_in_words(self):
        self.assertEqual(self.status(True), "실시간 보호 켜짐")
        self.assertEqual(self.status(None), "실시간 보호 읽지 못함")
        off = self.status(False)
        self.assertTrue(off.startswith("실시간 보호 꺼짐"), off)
        self.assertIn("요청한 검사는 그대로 돈다", off)
        for text in (self.status(True), self.status(None), off):
            self.assertNotIn("False", text)
            self.assertNotIn("True", text)


class KoreanTextRegionsFlowTest(unittest.TestCase):
    """결정 D-810 — M17: 설치 파일의 한글 글을 본체 구간과 덧붙은 구간으로 나눠 적는다(1차 측정의 '한글 글 UTF-8 479' 는 해석할 수 없었다)."""
    KOREAN = "설치마법사".encode("utf-8")

    def m17(self, setup_bytes_by_arm):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ctx = run.Context(Path(tmp.name) / "w", host=FakeWorld(tmp.name))
        ctx.results = []
        ctx.state["installers"] = {}
        for arm, data in setup_bytes_by_arm.items():
            path = Path(tmp.name) / ("setup-%s.exe" % arm)
            path.write_bytes(data)
            ctx.state["installers"][arm] = {"tiny": {"0.0.1": {"setup": str(path)}}}
        run.measure.m17_korean(ctx)
        return {item["arm"]: item for item in ctx.results}

    def test_korean_in_the_appended_chunk_is_not_called_the_installers_own_text(self):
        pe = support.build_pe(["kernel32.dll"])
        found = self.m17({"A": pe + b"\x00\x01" + self.KOREAN * 40, "B": pe})
        brief = found["A"]["values"]["brief"]
        self.assertIn("본체 구간 한글 글 UTF-8 0·UTF-16 0", brief)
        self.assertRegex(brief, r"덧붙은 구간\(앱 묶음 자리\) UTF-8 [1-9]")
        self.assertEqual(found["A"]["values"]["regions"]["split"], True)
        self.assertEqual(found["B"]["values"]["brief"].split(" / ")[1], "덧붙은 구간(앱 묶음 자리) UTF-8 0·UTF-16 0(추정)")

    def test_a_file_whose_layout_cannot_be_read_gets_only_the_whole_value_with_a_warning(self):
        found = self.m17({"A": b"\x01" + self.KOREAN * 5})
        brief = found["A"]["values"]["brief"]
        self.assertIn("구간을 못 나눈 전체 값", brief)
        self.assertIn("해석하지 않는다", brief)
        self.assertEqual(found["A"]["values"]["regions"], {"image": None, "overlay": None, "split": False})


if __name__ == "__main__":
    unittest.main()
