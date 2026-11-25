"""설치 도구 시험(spike)의 측정 부품(`packaging/spike/measure.py`)과 단계 실행기의 순수한 부분(`run_spike.py` — 명령 만들기·관문 판정·결과 블록·보고서)의 시험(결정 D-702·D-703) — 설치 도구·윈도 없이 돈다.

지키는 것: ① PE 읽기(실행 수준 매니페스트·가져오기 표·깨진 입력은 오류 없이 빈 값) ② 폴더 지문 비교(옛 판·새 판·반쯤 섞임·빈 폴더) ③ 글 가리기(경로·사용자 이름·저장소 이름·키 모양) ④ 명령 만들기(vpk·ISCC·dotnet·pip — 로컬 원본만·해시 검사·
접속 우회 옵션 없음) ⑤ 관문 판정(실패는 그 갈래만 탈락, 값이 모자라면 미정이고 실패로 세지 않음, 갈래 A 의 G7·G8 은 B 값) ⑥ 결과 블록(60줄 안팎·숫자와 통과/실패뿐·경로와 사용자 이름 없음)과 보고서 md·json.
"""
import contextlib
import io
import json
import os
import random
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer_spike_support as support  # noqa: E402

measure = support.load("measure")
run = support.load("run_spike")
ROOT = support.ROOT
CANARY_TOKEN = "gh" + "p_" + "A" * 36
RUNNER_ENV = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "Windows", "RUNNER_TEMP": "D:\\a\\_temp"}              # 러너 안임을 알리는 환경 — 시험은 이 값을 가짜 환경에 넣어서만 러너 전용 장치(R1)를 지난다


from installer_spike_support import build_pe  # noqa: E402,F401  (합성 PE 만들기 — 시험 도우미)


class PeReadingTest(unittest.TestCase):
    def test_imports_are_read_in_order_and_lowercased(self):
        names = ["KERNEL32.dll", "WS2_32.dll", "winhttp.dll", "USER32.dll"]
        self.assertEqual(measure.pe_imports(build_pe(names)), [name.lower() for name in names])

    def test_the_32_bit_layout_and_the_delay_import_table_are_read_too(self):
        self.assertEqual(measure.pe_imports(build_pe(["a.dll", "b.dll"], plus=False)), ["a.dll", "b.dll"])
        self.assertEqual(measure.pe_imports(build_pe(["a.dll"], delay=["wininet.dll"])), ["a.dll", "wininet.dll"])

    def test_no_table_means_an_empty_list_and_duplicates_are_listed_once(self):
        self.assertEqual(measure.pe_imports(build_pe([])), [])
        self.assertEqual(measure.pe_imports(build_pe(["a.dll", "A.DLL"])), ["a.dll"])

    def test_broken_input_never_raises(self):
        valid = build_pe(["kernel32.dll", "winhttp.dll"])
        generator = random.Random(7)
        samples = [b"", b"MZ", b"not a pe file" * 40, valid[:0x3C], valid[:0x80], valid[:0x90], valid[:0x150], valid[:0x420], bytes(generator.randrange(256) for _ in range(5000))]
        for cut in range(0, len(valid), 97):
            samples.append(valid[:cut])
        for sample in samples:
            self.assertIsInstance(measure.pe_imports(sample), list)
            self.assertIsInstance(measure.manifest_level(sample) or "", str)
        corrupted = bytearray(valid)
        struct.pack_into("<I", corrupted, 0x3C, 0xFFFFFF)
        self.assertEqual(measure.pe_imports(bytes(corrupted)), [])

    def test_net_imports_name_only_the_web_capable_dlls(self):
        self.assertEqual(measure.net_imports(["kernel32.dll", "WinHttp.dll", "ws2_32.dll", "user32.dll", "wininet.dll"]), ["WinHttp.dll", "ws2_32.dll", "wininet.dll"])
        self.assertEqual(measure.net_imports(["kernel32.dll"]), [])

    def test_the_import_count_is_bounded(self):
        names = ["lib%03d.dll" % number for number in range(30)]
        self.assertEqual(len(measure.pe_imports(build_pe(names))), 30)
        self.assertLessEqual(measure.MAX_IMPORTS, 400)

    def test_manifest_levels(self):
        for level in ("asInvoker", "requireAdministrator", "highestAvailable"):
            manifest = ('<requestedExecutionLevel level="%s" uiAccess="false"/>' % level).encode("utf-8")
            self.assertEqual(measure.manifest_level(build_pe([], manifest=manifest)), level)
            self.assertEqual(measure.manifest_level(manifest.decode("ascii").encode("utf-16le")), level)
        self.assertIsNone(measure.manifest_level(build_pe([])))
        self.assertIsNone(measure.manifest_level(b'requestedExecutionLevel level="9bad"'))

    def test_the_real_python_executable_is_read_when_this_is_windows(self):
        if os.name != "nt":
            self.skipTest("윈도의 python.exe 로만 확인한다")
        data = Path(sys.executable).read_bytes()
        imports = measure.pe_imports(data)
        self.assertTrue(any(name.startswith(("kernel32", "python")) or name.startswith("api-ms-win") for name in imports), imports)

    def test_hangul_runs_are_found_in_utf8_and_utf16_and_random_bytes_do_not_look_like_korean(self):
        utf8 = b"\x00\x01" + "설치마법사".encode("utf-8") + b"\xff"
        self.assertGreaterEqual(measure.hangul_samples(utf8)["utf8"], 1)
        utf16 = "Setup 설치를 시작합니다".encode("utf-16le")
        found = measure.hangul_samples(b"\x00\x00" + utf16 + b"\x00\x00")
        self.assertGreaterEqual(found["utf16"], 1)
        self.assertIn("설치", " ".join(found["samples"]))
        self.assertEqual(measure.hangul_samples(b"plain ascii only " * 50), {"utf8": 0, "utf16": 0, "samples": []})
        generator = random.Random(11)
        noise = bytes(generator.randrange(256) for _ in range(600000))
        self.assertEqual(measure.hangul_samples(noise)["utf8"], 0)

    def test_wheel_inventory_lists_files_and_reads_the_binaries_inside(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x-1.0-cp38-abi3-win_amd64.whl"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("velopack/__init__.py", "x = 1\n")
                archive.writestr("velopack/_native.pyd", build_pe(["kernel32.dll", "winhttp.dll"]))
                archive.writestr("x-1.0.dist-info/METADATA", "Name: x\n")
            inventory = measure.wheel_inventory(path)
        self.assertEqual(len(inventory["files"]), 3)
        self.assertEqual(inventory["binaries"][0]["net"], ["winhttp.dll"])
        self.assertEqual(inventory["binaries"][0]["imports"], ["kernel32.dll", "winhttp.dll"])


class TreeTest(unittest.TestCase):
    def make(self, root, files):
        for relative, text in files.items():
            path = Path(root) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def test_tree_hashes_use_slash_paths_and_skip_by_file_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"a.txt": "1", "sub/b.txt": "2", "unins000.exe": "x"})
            found = measure.tree_hashes(tmp, skip=("UNINS000.EXE",))
            self.assertEqual(sorted(found), ["a.txt", "sub/b.txt"])
            self.assertEqual(found["a.txt"], measure.sha256_file(Path(tmp) / "a.txt"))
        self.assertEqual(measure.tree_hashes(Path(tmp) / "no-such-folder"), {})

    def test_state_matrix(self):
        old = {"VERSION": "o", "p1": "o1", "p2": "o2", "same": "s"}
        new = {"VERSION": "n", "p1": "n1", "p2": "n2", "same": "s"}
        self.assertEqual(measure.tree_state(dict(old), old, new), "old")
        self.assertEqual(measure.tree_state(dict(new), old, new), "new")
        self.assertEqual(measure.tree_state({"VERSION": "n", "p1": "o1", "p2": "o2", "same": "s"}, old, new), "mixed")
        self.assertEqual(measure.tree_state({"VERSION": "n", "p1": "n1", "p2": "o2", "same": "s"}, old, new), "mixed")
        self.assertEqual(measure.tree_state({}, old, new), "empty")
        self.assertEqual(measure.tree_state({"VERSION": "zzz", "p1": "zzz", "p2": "zzz"}, old, new), "other")
        self.assertEqual(measure.tree_state({"VERSION": "o", "p1": "o1"}, old, new), "other")
        self.assertEqual(measure.tree_state({"VERSION": "o", "p1": "o1", "p2": "o2", "same": "s", "extra": "added by the tool"}, old, new), "old")
        self.assertEqual(measure.tree_state({"a": "1"}, {"a": "1"}, {"a": "1"}), "same")

    def test_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, {"a": "12345", "d/b": "123"})
            self.assertEqual(measure.dir_size(tmp), 8)
            self.assertEqual(measure.file_count(tmp), 2)
        self.assertEqual(measure.mb(1572864), 1.5)


class ScrubberTest(unittest.TestCase):
    ENV = {"USERNAME": "runneradmin", "COMPUTERNAME": "FV-AZ123-456", "RUNNER_TEMP": "D:\\a\\_temp", "GITHUB_REPOSITORY": "someowner/some-repo", "TEMP": "C:\\Users\\RUNNER~1\\AppData\\Local\\Temp", "SHORT": "ab", "USER": "xy"}

    def setUp(self):
        self.scrub = measure.Scrubber(self.ENV, extra=["D:\\a\\work"])

    def test_environment_values_and_paths_are_hidden(self):
        text = "user runneradmin on FV-AZ123-456 repo someowner/some-repo wrote D:\\a\\_temp\\spike\\out.log and C:\\Users\\runneradmin\\AppData\\x and //srv/x and \\\\host\\share\\f"
        out = self.scrub(text)
        for word in ("runneradmin", "FV-AZ123-456", "someowner", "some-repo", "D:\\a", "C:\\Users", "\\\\host"):
            self.assertNotIn(word, out)
        self.assertIn("<가림>", out)

    def test_it_is_case_insensitive_and_idempotent(self):
        once = self.scrub("RunnerAdmin and fv-az123-456")
        self.assertNotIn("unneradmin", once.lower().replace("<가림>", ""))
        self.assertEqual(self.scrub(once), once)

    def test_short_values_are_not_replaced_so_ordinary_words_survive(self):
        self.assertEqual(self.scrub("ab xy absolutely"), "ab xy absolutely")

    def test_token_shapes_are_hidden(self):
        self.assertNotIn(CANARY_TOKEN, self.scrub("token " + CANARY_TOKEN + " end"))
        self.assertIn("<키 모양 가림>", self.scrub(CANARY_TOKEN))
        self.assertIn("<키 모양 가림>", self.scrub("-----BEGIN " + "RSA PRIVATE" + " KEY-----"))                  # 조합해서 만든 값 — 저장소에는 키 모양 글자가 없다

    def test_deep_hides_in_nested_values_and_leaves_numbers_alone(self):
        value = {"a": ["runneradmin", {"b": "D:\\a\\_temp\\x", "n": 5, "t": True, "z": None}], "runneradmin": 1}
        out = self.scrub.deep(value)
        self.assertEqual(out["a"][1]["n"], 5)
        self.assertIs(out["a"][1]["t"], True)
        self.assertNotIn("runneradmin", json.dumps(out, ensure_ascii=False))

    def test_the_default_environment_values_are_read_from_os_environ(self):
        old = os.environ.get("USERNAME")
        os.environ["USERNAME"] = "someuniquename"
        try:
            self.assertNotIn("someuniquename", measure.Scrubber()("a someuniquename b"))
        finally:
            if old is None:
                os.environ.pop("USERNAME", None)
            else:
                os.environ["USERNAME"] = old


class SmallPartsTest(unittest.TestCase):
    def test_record_checks_status_and_arm(self):
        item = measure.record("M05", "A", "pass", note="n", brief="b", rc=0)
        self.assertEqual(item, {"id": "M05", "arm": "A", "status": "pass", "values": {"brief": "b", "rc": 0}, "note": "n"})
        with self.assertRaises(ValueError):
            measure.record("M05", "A", "great")
        with self.assertRaises(ValueError):
            measure.record("M05", "Z", "pass")
        self.assertIn("pass", measure.STATUSES)

    def test_firewall_commands_block_outbound_for_one_program_only(self):
        args = measure.firewall_add_args("rule1", "C:/x/y.exe")
        self.assertEqual(args[:5], ["netsh", "advfirewall", "firewall", "add", "rule"])
        for needle in ("name=rule1", "dir=out", "action=block", "program=C:/x/y.exe", "enable=yes"):
            self.assertIn(needle, args)
        self.assertNotIn("dir=in", args)
        self.assertEqual(measure.firewall_delete_args("rule1"), ["netsh", "advfirewall", "firewall", "delete", "rule", "name=rule1"])
        self.assertEqual(measure.rule_name(7), "installer-spike-block-007")
        self.assertNotEqual(measure.rule_name(1), measure.rule_name(2))

    def test_tasklist_names_and_versions(self):
        text = '"System Idle Process","0","Services","0","8 K"\n"SpikeApp.exe","123","Console","1","9,000 K"\ngarbage\n'
        self.assertEqual(measure.tasklist_names(text), ["system idle process", "spikeapp.exe"])
        self.assertEqual(measure.version_numbers("Inno Setup 6.7.1.0 build"), (6, 7, 1, 0))
        self.assertEqual(measure.version_numbers("6.7"), (6, 7))
        self.assertIsNone(measure.version_numbers("no digits"))
        self.assertTrue(measure.inno_version_ok((6, 7, 1)))
        self.assertTrue(measure.inno_version_ok((6, 7)))
        for numbers in ((6, 5, 4), (7, 1, 1), (6,), None, ()):
            self.assertFalse(measure.inno_version_ok(numbers))

    def test_read_text_guess_handles_utf8_bom_utf16_and_cp949(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = {"u8.txt": "SPIKE_NEXT=다음".encode("utf-8-sig"), "u16.txt": "SPIKE_NEXT=다음".encode("utf-16"), "cp.txt": "SPIKE_NEXT=다음".encode("cp949")}
            for name, data in cases.items():
                (Path(tmp) / name).write_bytes(data)
                self.assertIn("다음", measure.read_text_guess(Path(tmp) / name), name)
            self.assertEqual(measure.read_text_guess(Path(tmp) / "none.txt"), "")

    def test_tail_keeps_the_end_of_long_text(self):
        self.assertEqual(measure.tail("abc"), "abc")
        self.assertEqual(measure.tail("x" * 1000, 10), "…" + "x" * 10)
        self.assertEqual(measure.tail(None), "")

    def test_the_host_runs_real_processes_with_timeouts_and_environment_control(self):
        host = measure.Host({"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "KEEP": "1", "DROPME": "1"})
        done = host.run([sys.executable, "-c", "import os; print(os.environ.get('KEEP'), os.environ.get('DROPME'), os.environ.get('ADDED'))"], env={"ADDED": "yes"}, drop_env=("DROPME",))
        self.assertTrue(done.ok)
        self.assertEqual(done.out.split(), ["1", "None", "yes"])
        slow = host.run([sys.executable, "-c", "import time; time.sleep(90)"], timeout=1)
        self.assertTrue(slow.timed_out)
        self.assertFalse(slow.ok)
        self.assertLess(slow.seconds, 60)                         # 90초 자는 자식을 1초 제한으로 끊었다 — 바쁜 공용 PC 에서도 한참 못 미친다
        missing = host.run(["definitely-not-a-program-xyz"], timeout=5)
        self.assertEqual((missing.rc, bool(missing.error)), (-1, True))
        watched = host.watch([sys.executable, "-c", "pass"], seconds=20)
        self.assertEqual((watched["rc"], watched["timed_out"]), (0, False))
        hung = host.watch([sys.executable, "-c", "import time; time.sleep(90)"], seconds=1.2)
        self.assertTrue(hung["timed_out"])
        self.assertLess(hung["seconds"], 60)

    def test_a_decode_that_is_not_utf8_falls_back_instead_of_raising(self):
        self.assertEqual(measure.decode_bytes("그림".encode("cp949")), "그림")
        self.assertEqual(measure.decode_bytes(b""), "")
        self.assertIsInstance(measure.decode_bytes(b"\xff\xfe\xfd"), str)


class CommandBuildersTest(unittest.TestCase):
    def test_vpk_pack_arguments(self):
        args = run.vpk_pack_args("vpk.exe", pack_id="ChanceBlogSpikeB", version="0.0.1", pack_dir="dir", main_exe="SpikeApp.exe", title="T", out_dir="out", skip_check=True, delta_none=True)
        self.assertEqual(args[:2], ["vpk.exe", "pack"])
        for flag, value in (("--packId", "ChanceBlogSpikeB"), ("--packVersion", "0.0.1"), ("--packDir", "dir"), ("--mainExe", "SpikeApp.exe"), ("--channel", "stable"), ("--outputDir", "out"), ("--delta", "None")):
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertIn("--noPortable", args)
        self.assertIn("--skipVeloAppCheck", args)
        plain = run.vpk_pack_args("vpk.exe", pack_id="x", version="1.0.0", pack_dir="d", main_exe="e.exe", title="T", out_dir="o", skip_check=False, delta_none=False)
        self.assertNotIn("--skipVeloAppCheck", plain)
        self.assertNotIn("--delta", plain)
        for forbidden in ("--signParams", "--publish", "--upload", "--msi", "--noInst"):
            self.assertNotIn(forbidden, args)

    def test_the_nuget_config_allows_only_the_one_local_folder(self):
        text = run.nuget_config_text("C:/tools")
        self.assertIn("<clear />", text)
        self.assertEqual(text.count("<add "), 1)
        self.assertIn('value="C:/tools"', text)
        for word in ("nuget.org", "api.nuget", "http", "packageSourceCredentials"):
            self.assertNotIn(word, text)

    def test_the_dotnet_tool_install_uses_the_config_and_a_tool_path_and_nothing_global(self):
        args = run.dotnet_tool_args("tp", "1.2.161", "cfg")
        self.assertEqual(args[:4], ["dotnet", "tool", "install", "vpk"])
        self.assertEqual(args[args.index("--version") + 1], "1.2.161")
        self.assertEqual(args[args.index("--configfile") + 1], "cfg")
        self.assertEqual(args[args.index("--tool-path") + 1], "tp")
        for forbidden in ("--add-source", "-g", "--global", "--source", "--interactive"):
            self.assertNotIn(forbidden, args)

    def test_the_pip_commands_check_hashes_and_never_change_the_index(self):
        for args in (run.pip_download_args("py", "req.txt", "wheels"), run.pip_install_local_args("py", "req.txt", "wheels")):
            self.assertIn("--require-hashes", args)
            self.assertIn("--only-binary=:all:", args)
            self.assertEqual(args[args.index("-r") + 1], "req.txt")
            for forbidden in ("--index-url", "-i", "--extra-index-url", "--trusted-host", "--no-verify", "--no-deps-check", "--pre", "--break-system-packages"):
                self.assertNotIn(forbidden, args)
        self.assertIn("--no-deps", run.pip_download_args("py", "r", "w"))
        local = run.pip_install_local_args("py", "r", "w")
        self.assertIn("--no-index", local)
        self.assertEqual(local[local.index("--find-links") + 1], "w")

    def test_the_requirement_line_pins_the_exact_version_and_hash(self):
        tool = json.loads((support.SPIKE / "tools.lock.json").read_text(encoding="utf-8"))["tools"][1]
        self.assertEqual(run.requirements_line(tool), "velopack==1.2.161 --hash=sha256:3a85b4a39c7644d06dafa44bd197d1e88d429f3f05ead57031552cf17ffcf36e\n")

    def test_only_the_build_tools_are_asked_for_in_the_sdk_environment(self):
        lines = run.build_requirement_lines((ROOT / "packaging" / "requirements-package.txt").read_text(encoding="utf-8"))
        names = sorted(line.split("==")[0].lower() for line in lines)
        self.assertEqual(names, ["altgraph", "packaging", "pefile", "pyinstaller", "pyinstaller-hooks-contrib", "pywin32-ctypes", "setuptools"])
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][0-9.]*\n", line) for line in lines))

    def test_payload_differs_in_every_file_between_versions_so_a_half_updated_state_is_visible(self):
        one, two = run.payload_files("0.0.1"), run.payload_files("0.0.2")
        self.assertEqual(sorted(one), sorted(two))
        self.assertEqual(len(one), 9)
        self.assertTrue(all(one[key] != two[key] for key in one))
        self.assertEqual(one["VERSION"], "0.0.1\n")

    def test_misc_command_parts(self):
        self.assertEqual(run.core_version("0.1.0-preview.1"), "0.1.0")
        self.assertEqual(run.core_version("1.2.3"), "1.2.3")
        args = run.pyinstaller_args("py", name="SpikeApp", entry="e.py", dist="d", work="w", spec="s", extra=("--collect-all", "velopack"))
        for flag in ("--onedir", "--windowed", "--noupx", "--noconfirm", "--clean", "--collect-all"):
            self.assertIn(flag, args)
        self.assertEqual(args[:3], ["py", "-m", "PyInstaller"])
        self.assertEqual(run.version_text("vpk 1.2.161+abcdef"), "1.2.161")
        self.assertEqual(run.version_text("nothing"), "")

    def test_the_arm_commands_for_install_and_uninstall(self):
        self.assertEqual(measure.install_args("A", "S.exe", "root", "log")[1:], ["--silent", "--installto", "root", "--log", "log"])
        inno = measure.install_args("C", "S.exe", "root", "log", korean=True)
        for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=root", "/LOG=log", "/LANG=korean"):
            self.assertIn(flag, inno)
        self.assertNotIn("/LANG=korean", measure.install_args("C", "S.exe", "root", "log"))
        self.assertEqual(measure.uninstall_variants("C", "root")[0][1:], ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        self.assertEqual(len(measure.uninstall_variants("B", "root")), 2)
        self.assertEqual(measure.apply_args("root", "pkg")[1:], ["apply", "--package", "pkg", "--norestart"])
        self.assertEqual(measure.app_dir("B", "root"), Path("root") / "current")
        self.assertEqual(measure.app_dir("C", "root"), Path("root"))


def rec(mid, arm, status, **values):
    return measure.record(mid, arm, status, **values)


def passing_results():
    items = []
    for arm in "ABC":
        proxy = arm
        items += [rec("M04", arm, "pass", brief="수준 asInvoker"), rec("M05", arm, "pass", brief="종료 0", target="tiny"), rec("M12", arm, "pass", brief="제거 ok", target="tiny"),
                  rec("M08", arm, "pass", brief="0.0.1 -> 0.0.2"), rec("M09", arm, "pass", brief="켜 둔 채"), rec("M14", arm, "pass", brief="막은 채"), rec("M16", arm, "pass", brief="Defender clean"),
                  rec("M18", arm, "pass", brief="표준 사용자"), rec("M06", arm, "pass", brief="selftest 12", target="tiny")]
        if arm != "A":
            items += [rec("M03", proxy, "pass", brief="40 MB", target="real"), rec("M06", proxy, "pass", brief="통과 12", target="real")]
        if arm != "C":
            items.append(rec("M07", arm, "pass", brief="훅 4/4", target="tiny"))
    items.append(rec("M22", "-", "pass", brief="휴대용 selftest 통과 12"))
    return items


class JudgeTest(unittest.TestCase):
    def test_everything_passing_passes_every_gate_and_the_hookless_arm_has_no_g3(self):
        gates = run.judge(passing_results())
        for arm in "ABC":
            for gate, _title in run.GATES:
                expected = "n/a" if (arm == "C" and gate == "G3") else "pass"
                self.assertEqual(gates[arm][gate]["status"], expected, (arm, gate))

    def test_a_failure_drops_only_that_arm_and_that_gate(self):
        items = passing_results()
        items = [item for item in items if not (item["id"] == "M12" and item["arm"] == "B")] + [rec("M12", "B", "fail", brief="폴더 남음", target="tiny")]
        gates = run.judge(items)
        self.assertEqual(gates["B"]["G2"]["status"], "fail")
        self.assertEqual(gates["A"]["G2"]["status"], "pass")
        self.assertEqual(gates["C"]["G2"]["status"], "pass")
        self.assertEqual(gates["B"]["G1"]["status"], "pass")

    def test_missing_values_are_unknown_and_never_counted_as_failures(self):
        gates = run.judge([])
        for arm in "ABC":
            for gate, _title in run.GATES:
                self.assertIn(gates[arm][gate]["status"], ("unknown", "n/a"), (arm, gate))
        items = [item for item in passing_results() if item["id"] != "M16"] + [rec("M16", "B", "unavailable", brief="not_run")]
        self.assertEqual(run.judge(items)["B"]["G6"]["status"], "unknown")

    def test_a_blocked_run_whose_firewall_rule_was_not_confirmed_is_not_a_pass(self):
        items = [item for item in passing_results() if not (item["id"] == "M14" and item["arm"] == "C")] + [rec("M14", "C", "info", brief="규칙 효과 미확인")]
        self.assertEqual(run.judge(items)["C"]["G5"]["status"], "unknown")

    def test_standard_user_trouble_is_handed_to_the_operator_not_failed(self):
        items = [item for item in passing_results() if not (item["id"] == "M18" and item["arm"] == "A")] + [rec("M18", "A", "unavailable", brief="시도 불가")]
        self.assertEqual(run.judge(items)["A"]["G1"]["status"], "pass")
        items = [item for item in passing_results() if not (item["id"] == "M04" and item["arm"] == "A")] + [rec("M04", "A", "fail", brief="수준 requireAdministrator")]
        self.assertEqual(run.judge(items)["A"]["G1"]["status"], "fail")
        items = [item for item in passing_results() if not (item["id"] == "M18" and item["arm"] == "C")] + [rec("M18", "C", "fail", brief="설치 실패")]
        self.assertEqual(run.judge(items)["C"]["G1"]["status"], "fail")

    def test_arm_a_reads_g7_and_g8_from_the_same_real_bundle_as_b(self):
        items = [item for item in passing_results() if not (item["id"] == "M03" and item["arm"] == "B")] + [rec("M03", "B", "fail", brief="90 MB", target="real")]
        gates = run.judge(items)
        self.assertEqual(gates["B"]["G7"]["status"], "fail")
        self.assertEqual(gates["A"]["G7"]["status"], "fail")
        self.assertIn("추정", gates["A"]["G7"]["why"])
        self.assertEqual(gates["C"]["G7"]["status"], "pass")

    def test_g8_needs_both_the_installed_selftest_and_the_portable_one(self):
        items = [item for item in passing_results() if item["id"] != "M22"] + [rec("M22", "-", "fail", brief="휴대용 실패")]
        gates = run.judge(items)
        for arm in "ABC":
            self.assertEqual(gates[arm]["G8"]["status"], "fail")

    def test_rollup_rules(self):
        self.assertEqual(run.rollup([rec("M05", "A", "pass"), rec("M05", "A", "fail")]), "fail")
        self.assertEqual(run.rollup([rec("M05", "A", "pass"), rec("M05", "A", "info")]), "pass")
        self.assertEqual(run.rollup([rec("M05", "A", "pass"), rec("M05", "A", "error")]), "unknown")
        self.assertEqual(run.rollup([]), "unknown")
        self.assertEqual(run.both("pass", "pass"), "pass")
        self.assertEqual(run.both("pass", "unknown"), "unknown")
        self.assertEqual(run.both("fail", "unknown"), "fail")


class FakeEnvContext(measure.Context):
    pass


def make_context(tmp, environ=None, results=None, state=None):
    host = measure.Host(environ if environ is not None else {"ImageOS": "win25", "ImageVersion": "20261116.335.1", "GITHUB_SHA": "0123456789abcdef", "USERNAME": "runneradmin", "RUNNER_TEMP": str(Path(tmp) / "temp")})
    ctx = measure.Context(Path(tmp) / "work", host=host)
    ctx.results = results if results is not None else passing_results()
    if state:
        ctx.state.update(state)
    return ctx


class ReportTest(unittest.TestCase):
    def build(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(tmp, **kwargs)
            return run.build_report(ctx), ctx

    def test_the_result_block_has_every_measurement_and_gate_line_in_sixty_lines_or_so(self):
        (block, md, data), ctx = self.build(state={"tools": {"vpk": {"version": "1.2.161"}, "iscc": {"version": "6.7.1"}, "python": {"version": "3.12.10"}, "dotnet": {"version": "8.0.404"}},
                                                    "steps": {name: {"status": "ok", "seconds": 5} for name in run.COMMANDS[:4]}})
        lines = block.splitlines()
        self.assertEqual(lines[0], run.RESULT_HEADER)
        self.assertEqual(lines[-1], run.RESULT_FOOTER)
        self.assertGreaterEqual(len(lines), 35)
        self.assertLessEqual(len(lines), 70)
        for number in range(1, 23):
            self.assertTrue(any(line.startswith("M%02d " % number) for line in lines), number)
        for gate, _title in run.GATES:
            self.assertTrue(any(line.startswith(gate + " ") for line in lines), gate)
        self.assertIn("win25 20261116.335.1", lines[1])
        self.assertIn("커밋 0123456", lines[1])
        self.assertIn("vpk 1.2.161", lines[1])
        self.assertIn("Inno 6.7.1", lines[1])
        for line in lines:
            self.assertLessEqual(len(line), 500, line[:60])
        self.assertIn("요약:", block)

    def test_the_block_and_reports_contain_no_path_no_user_name_and_no_token(self):
        items = passing_results() + [rec("M05", "A", "fail", brief="폴더 C:\\Users\\runneradmin\\AppData\\x 와 %s" % CANARY_TOKEN, note="D:\\a\\_temp\\spike\\out runneradmin", target="tiny")]
        (block, md, data), ctx = self.build(results=items)
        text = block + md + json.dumps(data, ensure_ascii=False)
        for word in ("runneradmin", "C:\\Users", "D:\\a", CANARY_TOKEN, "\\\\"):
            self.assertNotIn(word, text, word)
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]", text))

    def test_the_markdown_has_the_block_in_a_fence_the_table_and_the_help_section(self):
        (block, md, data), ctx = self.build(state={"help": {"vpk_pack_help": "usage: vpk pack ... --delta <BestSize|BestSpeed|None>"}})
        self.assertIn("```text\n" + block + "\n```", md)
        self.assertIn("| 번호 | 갈래 | 상태 | 대상 | 요약 | 메모 |", md)
        self.assertIn("### vpk_pack_help", md)
        self.assertIn("BestSize", md)
        self.assertNotIn("~", md.replace("<가림>", ""))

    def test_the_json_has_the_schema_gates_results_and_block(self):
        (block, md, data), ctx = self.build()
        self.assertEqual(data["schema"], 1)
        self.assertEqual(sorted(data["gates"]), ["A", "B", "C"])
        self.assertEqual(data["block"], block)
        self.assertEqual(len(data["results"]), len(passing_results()))
        json.dumps(data, ensure_ascii=False)

    def test_a_run_with_nothing_measured_still_makes_a_report(self):
        (block, md, data), ctx = self.build(results=[])
        self.assertIn("기록 없음", block)
        self.assertIn("미정", block)
        self.assertEqual(data["results"], [])

    def test_pipes_in_cells_cannot_break_the_table(self):
        (block, md, data), ctx = self.build(results=[rec("M05", "A", "fail", brief="a|b", note="c|d\ne", target="tiny")])
        row = next(line for line in md.splitlines() if line.startswith("| M05 |"))
        self.assertEqual(row.count("|"), 7)

    def test_the_report_command_writes_both_files_and_appends_the_summary_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.md"
            environ = {"ImageOS": "win25", "GITHUB_SHA": "abcdef0123", "GITHUB_STEP_SUMMARY": str(summary)}
            ctx = make_context(tmp, environ=environ)
            with contextlib.redirect_stdout(io.StringIO()):
                run.cmd_report(ctx)
            report = Path(tmp) / "work" / "report"
            self.assertEqual(sorted(path.name for path in report.iterdir()), ["INSTALLER_SPIKE_REPORT.json", "INSTALLER_SPIKE_REPORT.md"])
            self.assertEqual(json.loads((report / "INSTALLER_SPIKE_REPORT.json").read_text(encoding="utf-8"))["schema"], 1)
            text = summary.read_text(encoding="utf-8")
            self.assertTrue(text.rstrip().endswith("```"))
            self.assertIn(run.RESULT_HEADER, text)
            self.assertLess(text.index(run.RESULT_HEADER), text.index(run.RESULT_FOOTER))

    def test_main_reports_the_command_names_and_returns_zero_for_a_broken_middle_step_but_one_for_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Exploding(measure.Host):
                def run(self, *args, **kwargs):
                    raise RuntimeError("부서졌다")

            self.assertEqual(run.main(["measure", "--work", str(Path(tmp) / "w1")], host=Exploding(dict(RUNNER_ENV))), 0)
            state = json.loads((Path(tmp) / "w1" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["steps"]["measure"]["status"], "crashed")
            self.assertIn("RuntimeError", state["steps"]["measure"]["error"])
        self.assertEqual(sorted(run.HANDLERS), sorted(run.COMMANDS))
        with self.assertRaises(SystemExit):
            run.main(["no-such-command", "--work", "x"])


class RunnerGuardTest(unittest.TestCase):
    """권고 R1 — 이 도구는 방화벽 규칙·가짜 자격 증명·임시 사용자 만들기·프로그램 이름으로 끝내기를 하므로 GitHub 의 일회용 윈도 러너가 아니면 시작 전에 멈춘다."""

    def test_runner_problem_names_the_first_wrong_variable_and_is_empty_only_on_a_runner(self):
        self.assertEqual(measure.runner_problem(dict(RUNNER_ENV)), "")
        self.assertEqual(measure.runner_problem({}), "GITHUB_ACTIONS")
        for wrong in ("false", "TRUE", "True", "1", "", " true"):
            self.assertEqual(measure.runner_problem(dict(RUNNER_ENV, GITHUB_ACTIONS=wrong)), "GITHUB_ACTIONS", wrong)
        for wrong in ("Linux", "macOS", "windows", ""):
            self.assertEqual(measure.runner_problem(dict(RUNNER_ENV, RUNNER_OS=wrong)), "RUNNER_OS", wrong)
        self.assertEqual(measure.runner_problem({key: value for key, value in RUNNER_ENV.items() if key != "RUNNER_TEMP"}), "RUNNER_TEMP")
        self.assertEqual(measure.runner_problem(dict(RUNNER_ENV, RUNNER_TEMP="")), "RUNNER_TEMP")

    def test_every_command_refuses_off_a_runner_before_touching_anything(self):
        class Untouchable(measure.Host):
            def run(self, *args, **kwargs):
                raise AssertionError("러너가 아닌데 프로그램을 돌렸다")

            def start(self, *args, **kwargs):
                raise AssertionError("러너가 아닌데 프로그램을 띄웠다")

        wrong_environments = (({}, "GITHUB_ACTIONS"), ({"GITHUB_ACTIONS": "true"}, "RUNNER_OS"), ({"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux", "RUNNER_TEMP": "/tmp/x"}, "RUNNER_OS"),
                              ({"GITHUB_ACTIONS": CANARY_TOKEN}, "GITHUB_ACTIONS"))
        for environ, expected in wrong_environments:
            for command in run.COMMANDS:
                with tempfile.TemporaryDirectory() as tmp:
                    work = Path(tmp) / "w"
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                        code = run.main([command, "--work", str(work)], host=Untouchable(environ))
                    self.assertEqual(code, 2, (command, environ))
                    self.assertFalse(work.exists(), command)                                   # 작업 폴더도 만들지 않는다
                    self.assertIn("러너", err.getvalue())
                    self.assertIn("어긋난 조건: " + expected, err.getvalue())
                    self.assertNotIn(CANARY_TOKEN, err.getvalue())                          # 변수 이름만 적고 값은 적지 않는다

    def test_without_a_host_the_real_environment_decides_and_a_development_pc_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "w"
            with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run.main(["measure", "--work", str(work)]), 2)
            self.assertFalse(work.exists())

    def test_kill_images_by_name_only_runs_on_a_runner(self):
        calls = []

        class Recorder(measure.Host):
            def run(self, args, **kwargs):
                calls.append(list(args))
                return measure.HostResult(0, 0.1)

        names = ["ChanceBlogDesktop.exe", "spike_app.exe"]
        with tempfile.TemporaryDirectory() as tmp:
            measure.kill_images(measure.Context(Path(tmp) / "a", host=Recorder({})), names)
            measure.kill_images(measure.Context(Path(tmp) / "b", host=Recorder({"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux", "RUNNER_TEMP": "x"})), names)
            self.assertEqual(calls, [])
            measure.kill_images(measure.Context(Path(tmp) / "c", host=Recorder(dict(RUNNER_ENV))), names)
        self.assertEqual(calls, [["taskkill", "/F", "/T", "/IM", name] for name in names])

    def test_the_guard_reads_exactly_three_variables_and_no_more(self):
        """총괄 결정(재작업 권고 1) — 가드를 더 까다롭게 만들지 않는다: 첫 실제 러너 실행에서 잘못 거절될 위험을 시험으로 막을 수 없다. 읽는 변수가 늘면 문서(D-708)도 같이 고쳐야 하므로 이 시험이 먼저 빨개진다."""
        spy = support.RecordingEnv(RUNNER_ENV)
        self.assertEqual(measure.runner_problem(spy), "")
        self.assertEqual(sorted(set(spy.read_keys)), ["GITHUB_ACTIONS", "RUNNER_OS", "RUNNER_TEMP"])


class HiddenWordsTest(unittest.TestCase):
    """권고 R2 — 임시 사용자의 임의 비밀번호는 net user 명령줄에 들어간다. 어떤 도구가 그 줄을 되울려도 기록·보고서에는 남지 않아야 한다."""
    WORD = "Sp1ke!" + "Zq9xW3kLm2"

    def test_hide_words_hides_in_texts_lists_dicts_and_keys_and_the_longer_word_goes_first(self):
        value = {"note": "앞 " + self.WORD + " 뒤", "list": [self.WORD, ("x", self.WORD + "tail")], "키 " + self.WORD: 3, "n": 5, "t": True, "z": None}
        out = measure.hide_words(value, [self.WORD, self.WORD + "tail"])
        text = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(self.WORD, text)
        self.assertNotIn("tail", text)
        self.assertEqual(out["note"], "앞 <가림> 뒤")
        self.assertEqual(out["list"], ["<가림>", ["x", "<가림>"]])
        self.assertEqual((out["n"], out["t"], out["z"], out["키 <가림>"]), (5, True, None, 3))

    def test_short_or_odd_words_are_ignored_and_no_words_means_the_same_object(self):
        value = {"a": "abc abcd"}
        self.assertIs(measure.hide_words(value, []), value)
        self.assertIs(measure.hide_words(value, ["abc", "", None, 5]), value)
        self.assertEqual(measure.hide_words(value, ["abcd"]), {"a": "abc <가림>"})

    def test_a_context_hides_a_word_from_the_moment_a_record_is_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(tmp, results=[])
            known_late = ctx.add(rec("M18", "A", "unavailable", note="앞 " + self.WORD))
            self.assertIn(self.WORD, known_late["note"])                                         # 아직 모르는 낱말은 가릴 수 없다 — 그래서 만들자마자 hide 한다
            for word in (self.WORD, self.WORD, "ab", "", None):
                ctx.hide(word)
            self.assertEqual(ctx.secret_words, [self.WORD])
            after = ctx.add(rec("M18", "B", "unavailable", note="뒤 " + self.WORD, rows=[{"err": "x " + self.WORD}], brief=self.WORD))
            self.assertEqual(after["note"], "뒤 <가림>")
            self.assertEqual(ctx.results[-1], after)
            self.assertNotIn(self.WORD, json.dumps(ctx.results[1:], ensure_ascii=False))
            ctx.save()
            self.assertEqual((Path(tmp) / "work" / "results.json").read_text(encoding="utf-8").count(self.WORD), 1)       # 낱말을 알기 전에 더한 한 건에만 남는다

    def test_the_report_also_hides_the_words_of_the_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            items = passing_results() + [rec("M18", "A", "unavailable", note="접근 거부 " + self.WORD, brief="시도 불가 " + self.WORD, target="tiny")]
            ctx = make_context(tmp, results=items)
            ctx.hide(self.WORD)
            block, md, data = run.build_report(ctx)
            self.assertNotIn(self.WORD, block + md + json.dumps(data, ensure_ascii=False))
            self.assertIn("<가림>", md)

    def test_hide_words_ignores_upper_and_lower_case_in_both_directions(self):
        """재작업 권고 3 — 되울림이 대문자나 소문자로 바뀌어도 가린다(등록한 낱말이 대문자여도 마찬가지)."""
        for text in (self.WORD.upper(), self.WORD.lower(), self.WORD.swapcase()):
            self.assertEqual(measure.hide_words("앞 " + text + " 뒤", [self.WORD]), "앞 <가림> 뒤", text)
        self.assertEqual(measure.hide_words("앞 " + self.WORD.lower() + " 뒤", [self.WORD.upper()]), "앞 <가림> 뒤")

    def test_hide_words_hides_a_word_that_a_line_break_or_spaces_split(self):
        """재작업 권고 3 — 되울림이 줄이 나뉘어 나와 낱말 한가운데에 줄바꿈·들여쓰기·공백이 끼어도 가린다."""
        for glue in ("\r\n", "\n", "\n    ", " ", "\t", "\r\n  \r\n"):
            for cut in (1, 6, 9, len(self.WORD) - 1):
                text = "앞 " + self.WORD[:cut] + glue + self.WORD[cut:] + " 뒤"
                self.assertEqual(measure.hide_words(text, [self.WORD]), "앞 <가림> 뒤", (glue, cut))
        self.assertEqual(measure.hide_words("앞 " + " ".join(self.WORD) + " 뒤", [self.WORD]), "앞 <가림> 뒤")
        self.assertEqual(measure.hide_words({"a": "x\n" + self.WORD[:8] + "\n" + self.WORD[8:]}, [self.WORD]), {"a": "x\n<가림>"})

    def test_hide_words_keeps_the_text_around_the_word_and_leaves_other_text_alone(self):
        self.assertEqual(measure.hide_words("앞  " + self.WORD + "  뒤\n", [self.WORD]), "앞  <가림>  뒤\n")                      # 낱말 둘레의 공백·줄바꿈은 그대로
        ordinary = "접근 거부 — 비밀번호가 틀렸다 access denied for user Sp1ke! 접두어만"
        self.assertEqual(measure.hide_words(ordinary, [self.WORD]), ordinary)                                                # 접두어만 있는 글·평범한 글은 그대로
        once = measure.hide_words("x " + self.WORD + "\n" + self.WORD.upper(), [self.WORD])
        self.assertEqual(once, "x <가림>\n<가림>")
        self.assertEqual(measure.hide_words(once, [self.WORD]), once)                                                       # 두 번 가려도 같다

    def test_hide_words_takes_the_word_literally_even_when_it_has_characters_a_pattern_would_read(self):
        """가릴 낱말은 글자 그대로 찾는다 — 점·더하기·괄호가 있어도 정규식으로 읽히지 않는다(임의 비밀번호에 올 수 있는 글자)."""
        word = "a.b+c(d)e*f?"
        self.assertEqual(measure.hide_words("앞 " + word + " 뒤", [word]), "앞 <가림> 뒤")
        self.assertEqual(measure.hide_words("앞 aXb+c(d)e*f? 뒤", [word]), "앞 aXb+c(d)e*f? 뒤")                           # 점이 아무 글자나 뜻하지 않는다
        self.assertEqual(measure.hide_words("앞 abbbbc 뒤", ["ab+c"]), "앞 abbbbc 뒤")                                       # 더하기가 되풀이를 뜻하지 않는다

    def test_a_context_masks_before_the_caller_cuts_because_cutting_first_leaves_a_piece(self):
        """재작업 권고 2 — 글을 자른 뒤에 가리면 낱말 전체가 안 맞아 조각이 남는다. Context.mask 는 자르기 전에 부르는 용도다."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(tmp, results=[])
            long_text = "xxx" + self.WORD + "y" * 150
            self.assertEqual(ctx.mask(long_text), long_text)                                                                 # 아직 모르는 낱말은 못 가린다
            ctx.hide(self.WORD)
            cut_first = measure.tail(long_text, 160)
            self.assertIn(self.WORD[-10:], cut_first)                                                                        # 이 시험의 전제 — 자르고 나서 가리면 뒤 10글자가 남는다
            self.assertNotIn(self.WORD, cut_first)
            self.assertEqual(measure.hide_words(cut_first, ctx.secret_words), cut_first)
            self.assertEqual(measure.tail(ctx.mask(long_text), 160), "xxx<가림>" + "y" * 150)                               # 먼저 가리고 자르면 남는 것이 없다
            self.assertIsNone(ctx.mask(None))
            self.assertEqual(ctx.mask("평범한 글"), "평범한 글")

    def test_guard_hides_the_secret_before_it_cuts_the_error_text(self):
        """재작업 권고 2 — 측정 하나가 비밀 낱말이 든 오류 글로 죽어도(글이 200자를 넘어 한가운데가 잘릴 길이) 기록에 조각이 남지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(tmp, results=[])
            ctx.hide(self.WORD)

            def boom():
                raise RuntimeError("앞 " + self.WORD + "z" * 190)

            ctx.guard("M18", "A", boom)
            item = ctx.results[-1]
            self.assertEqual(item["status"], "error")
            self.assertEqual(item["note"], "RuntimeError: 앞 <가림>" + "z" * 190)
            self.assertNotIn(self.WORD[-10:], json.dumps(ctx.results, ensure_ascii=False))


class HostFileLookupTest(unittest.TestCase):
    """재작업 권고 4 — 정해진 자리에서 도구를 찾는 진짜 Host.is_file 은 흐름 시험이 가짜로 바꿔 끼워 직접 불린 적이 없었다. 임시 실제 파일·없는 파일·폴더로 직접 본다."""

    def test_a_real_file_is_found_by_text_and_by_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "ISCC.exe"
            target.write_bytes(b"MZ-test")
            host = measure.Host({})
            self.assertIs(host.is_file(str(target)), True)
            self.assertIs(host.is_file(target), True)

    def test_a_missing_file_and_a_folder_are_not_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "Inno Setup 6"
            folder.mkdir()
            host = measure.Host({})
            self.assertIs(host.is_file(str(Path(tmp) / "nothing.exe")), False)
            self.assertIs(host.is_file(str(folder)), False)                                                                  # 폴더는 파일이 아니다
            self.assertIs(host.is_file(str(Path(tmp) / "no-folder" / "ISCC.exe")), False)


class StandardUserFoldersTest(unittest.TestCase):
    """참고 2 — 표준 사용자 시험이 건드리는 폴더는 환경 변수에서만 나온다. 없으면 실제 폴더 이름을 짐작해 쓰지 않는다."""

    def folders(self, environ):
        with tempfile.TemporaryDirectory() as tmp:
            return measure.std_user_folders(make_context(tmp, environ=environ))

    def test_without_the_public_variable_there_are_no_folders_even_when_the_users_variable_is_set(self):
        self.assertIsNone(self.folders({}))
        self.assertIsNone(self.folders({"PUBLIC": ""}))
        self.assertIsNone(self.folders({"SPIKE_USERS_DIR": "D:/profiles"}))

    def test_the_profile_root_is_the_users_variable_or_the_folder_above_public(self):
        public, profile = self.folders({"PUBLIC": "D:/Users/Public", "SPIKE_USERS_DIR": "E:/profiles"})
        self.assertEqual(public, Path("D:/Users/Public") / "spike_std")
        self.assertEqual(profile, Path("E:/profiles") / measure.STD_USER / "AppData" / "Local")
        public, profile = self.folders({"PUBLIC": "D:/Users/Public"})
        self.assertEqual(public, Path("D:/Users/Public") / "spike_std")
        self.assertEqual(profile, Path("D:/Users") / measure.STD_USER / "AppData" / "Local")


if __name__ == "__main__":
    unittest.main()
