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
        # 결정 D-810 — 6.7 줄만이던 문을 6.5.0 이상으로 넓혔다(한글 안내 파일이 들어 있는 첫 판). 예전에 거짓이던 6.5.4·7.1.1 은 이제 참이고, 경계는 아래 새 시험이 촘촘히 지킨다
        for numbers in ((6, 5, 4), (7, 1, 1)):
            self.assertIs(measure.inno_version_ok(numbers), True)
        for numbers in ((6,), None, ()):
            self.assertFalse(measure.inno_version_ok(numbers))                          # 읽지 못한 값은 여전히 '참' 이 아니다(이제는 None — 아래 새 시험)

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

    def test_g8_fails_when_only_the_installed_real_bundle_selftest_failed_and_the_portable_one_passed(self):
        """재작업 Q-R1 — 위 시험은 휴대용(M22)만 실패하는 경우뿐이었다. 설치본(M06 실제 묶음)만 실패해도(M22 통과) 관문 G8 은 실패다 — 관문이 설치본을 안 보면 설치된 앱의 점검 실패가 통과로 흐른다.
        갈래 A 는 B 의 설치본 값을 따라가므로(추정) B 가 실패하면 A·B 가, C 가 실패하면 C 만 실패하고, 둘 다 실패하면 세 갈래 모두 실패다."""
        def failing(*arms):
            kept = [item for item in passing_results() if not (item["id"] == "M06" and item["values"].get("target") == "real" and item["arm"] in arms)]
            return run.judge(kept + [rec("M06", arm, "fail", brief="설치본 selftest 실패", target="real") for arm in arms])
        for arms, failed in ((("B", "C"), "ABC"), (("B",), "AB"), (("C",), "C")):
            gates = failing(*arms)
            for arm in "ABC":
                self.assertEqual(gates[arm]["G8"]["status"], "fail" if arm in failed else "pass", (arms, arm))
        self.assertEqual(run.judge(passing_results())["B"]["G8"]["status"], "pass")                  # 같은 입력에서 설치본이 통과면 통과다 — 위 실패가 설치본 때문임을 보인다

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
        """재작업 S-R7·Q-R7 — 호스트를 안 주면 진짜 환경이 정한다. 가드가 깨지면 이 시험 자체가 진짜 `measure`(방화벽 규칙·Defender 검사·임시 사용자)를 돌릴 수 있었다 — 이 PC·CI 윈도 러너는 관리자 권한이다.
        그래서 진짜 `Host` 자리에 '아무것도 못 하는' 가짜(`Untouchable`)를 끼운다: 환경을 읽는 모양은 그대로이고, 가드가 깨지면 일을 하지 않고 빨개지기만 한다."""
        untouchable = support.untouchable_host_class()
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "w"
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(run.measure, "Host", untouchable), contextlib.redirect_stderr(io.StringIO()):
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


class EnvironmentNamesTest(unittest.TestCase):
    """결정 D-810 — 1차 측정의 '러너: ? ?' 의 원인: 윈도는 환경 변수 이름의 대소문자를 가리지 않고 파이썬이 `os.environ` 의 이름을 모두 대문자로 올려 두므로, 사전으로 옮겨 온 환경에서 `ImageOS` 를 그대로 찾으면 못 찾는다."""

    def test_names_are_found_whatever_the_case_and_an_exact_name_wins(self):
        environ = {"IMAGEOS": "win25", "imageversion": "20261116.335.1", "Exact": "one", "EXACT": "two", "EMPTY": ""}
        self.assertEqual(measure.env_value(environ, "ImageOS"), "win25")
        self.assertEqual(measure.env_value(environ, "ImageVersion"), "20261116.335.1")
        self.assertEqual(measure.env_value(environ, "Exact"), "one")                        # 이름이 그대로 있으면 그것
        self.assertEqual(measure.env_value(environ, "Empty"), "")                           # 빈 값도 값이다(기본값으로 바꾸지 않는다)
        self.assertEqual(measure.env_value(environ, "Missing"), "")
        self.assertEqual(measure.env_value(environ, "Missing", "기본"), "기본")
        self.assertEqual(measure.env_value({}, "ImageOS", None), None)

    def test_a_dict_copied_from_the_real_environment_is_found_even_where_the_names_are_made_upper_case(self):
        with mock.patch.dict(os.environ, {"ImageOS": "win99", "ImageVersion": "2026.1"}):
            host = measure.Host()
        self.assertEqual(measure.env_value(host.environ, "ImageOS"), "win99")
        self.assertEqual(measure.env_value(host.environ, "ImageVersion"), "2026.1")
        if os.name == "nt":                                                                  # 윈도에서는 사전의 이름이 대문자로 바뀌어 있어 그대로 찾으면 못 찾는다 — 이것이 1차 측정의 원인이었다
            self.assertIsNone(host.environ.get("ImageOS"))
            self.assertEqual(host.environ.get("IMAGEOS"), "win99")

    def test_the_context_reads_environment_values_the_same_way(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(tmp, environ={"IMAGEVERSION": "7", "PUBLIC": "D:/Users/Public"})
            self.assertEqual(ctx.env("ImageVersion"), "7")
            self.assertEqual(ctx.env("public"), "D:/Users/Public")
            self.assertEqual(ctx.env("nothing", "x"), "x")


class InnoVersionTest(unittest.TestCase):
    """결정 D-810 — Inno Setup 은 6.5.0 이상이면 쓴다. 1차 측정은 6.7 줄만 허용했고 러너 이미지의 파일 버전 자원이 0.0.0.0 이라 갈래 C 를 통째로 못 쟀다."""

    def test_the_gate_is_six_point_five_zero_and_the_boundary_is_exact(self):
        for numbers in ((6, 5, 0), (6, 5), (6, 5, 0, 0), (6, 5, 4), (6, 7, 1, 0), (6, 8, 0), (7, 0, 0), (7, 1, 1), (10, 0, 0)):
            self.assertIs(measure.inno_version_ok(numbers), True, numbers)
        for numbers in ((6, 4, 9), (6, 4, 9, 9), (6, 4), (6, 0, 0), (5, 6, 9), (1, 0)):
            self.assertIs(measure.inno_version_ok(numbers), False, numbers)

    def test_an_unreadable_version_is_unknown_not_wrong_and_all_zero_means_unreadable(self):
        for numbers in (None, (), (6,), (0, 0, 0, 0), (0, 0), (0, 0, 0)):
            self.assertIsNone(measure.inno_version_ok(numbers), numbers)
            self.assertIsNone(measure.real_version(numbers), numbers)
        self.assertEqual(measure.real_version((0, 0, 0, 1)), (0, 0, 0, 1))
        self.assertEqual(measure.real_version([6, 7, 1]), (6, 7, 1))

    def test_the_design_line_is_only_a_note(self):
        for numbers in ((6, 7, 1), (6, 7), (6, 7, 1, 0)):
            self.assertTrue(measure.inno_on_design_line(numbers), numbers)
        for numbers in ((6, 8, 0), (6, 6, 9), (7, 7, 1), (0, 0, 0, 0), None, ()):
            self.assertFalse(measure.inno_on_design_line(numbers), numbers)

    def test_the_compiler_text_gives_the_engine_version_but_a_major_number_alone_is_not_a_version(self):
        self.assertEqual(measure.inno_text_version("Inno Setup 6 Command-Line Compiler\nCompiler engine version: Inno Setup 6.7.1\n"), (6, 7, 1))
        self.assertEqual(measure.inno_text_version("compiler ENGINE VERSION:   inno setup 7.1"), (7, 1))
        self.assertEqual(measure.inno_text_version("Inno Setup version 6.2.2 (u)"), (6, 2, 2))
        self.assertEqual(measure.inno_text_version("Inno Setup 6.5.0 Command-Line Compiler"), (6, 5, 0))
        self.assertEqual(measure.inno_text_version("Note: Inno Setup 5.6.1 script syntax\nCompiler engine version: Inno Setup 6.7.1\n"), (6, 7, 1))            # 컴파일러가 스스로 밝힌 줄이 글 속의 다른 'Inno Setup 숫자' 보다 앞선다
        for text in ("Inno Setup 6 Command-Line Compiler\nCopyright (C) 1997-2025 Jordan Russell.", "", None, "no version here 1.2.3", "Inno Setup 0.0.0.0"):
            self.assertIsNone(measure.inno_text_version(text), text)

    def test_the_registry_text_gives_the_installed_version_and_prefers_the_entry_whose_folder_holds_the_compiler(self):
        text = "Inno Setup version 6.7.1|6.7.1|C:\\Program Files (x86)\\Inno Setup 6\\\r\nInno Setup version 7.0.0|7.0.0|C:\\Program Files\\Inno Setup 7\\\r\n"
        self.assertEqual(measure.inno_registry_version(text, "C:\\Program Files\\Inno Setup 7\\ISCC.exe"), (7, 0, 0))
        self.assertEqual(measure.inno_registry_version(text, "c:/program files (x86)/inno setup 6/iscc.exe"), (6, 7, 1))
        self.assertEqual(measure.inno_registry_version(text, "D:\\elsewhere\\ISCC.exe"), (6, 7, 1))                         # 어느 폴더도 안 맞으면 첫 항목
        self.assertEqual(measure.inno_registry_version(text), (6, 7, 1))
        for bad in ("", None, "Something else|1.2.3|C:\\x", "Inno Setup version 6.7.1", "Inno Setup|0.0.0.0|C:\\x", "garbage"):
            self.assertIsNone(measure.inno_registry_version(bad, "C:\\x\\ISCC.exe"), bad)

    def test_all_the_ways_of_reading_are_tried_in_a_fixed_order_and_the_first_real_value_wins(self):
        class Stub:
            def __init__(self, usage="", registry="", file_text="FILE=0.0.0.0\r\nPRODUCT=0.0.0.0\r\n"):
                self.usage, self.registry, self.file_text, self.calls = usage, registry, file_text, []

            def run(self, args, *, timeout=120, env=None, cwd=None, drop_env=()):
                self.calls.append(list(args))
                if list(args)[1:] == ["/?"]:
                    return measure.HostResult(0, 0.1, self.usage, "")
                if "DisplayVersion" in args[-1]:
                    return measure.HostResult(0, 0.1, self.registry, "")
                return measure.HostResult(0, 0.1, self.file_text, "")

        usage, registry, both = "Compiler engine version: Inno Setup 6.9.0", "Inno Setup version 6.7.1|6.7.1|C:\\Inno\\", "FILE=6.5.0.0\r\nPRODUCT=6.6.0.0\r\n"
        found = measure.read_inno_version(Stub(usage, registry, both), "C:\\Inno\\ISCC.exe")
        self.assertEqual((found["numbers"], found["source"]), ((6, 9, 0), "컴파일러 출력"))
        self.assertEqual(found["reads"], {"usage": "6.9.0", "registry": "6.7.1", "product": "6.6.0.0", "file": "6.5.0.0"})            # 읽은 값은 전부 남긴다
        found = measure.read_inno_version(Stub("Inno Setup 6 Command-Line Compiler", registry, both), "C:\\Inno\\ISCC.exe")
        self.assertEqual((found["numbers"], found["source"]), ((6, 7, 1), "레지스트리"))
        found = measure.read_inno_version(Stub("", "", both), "C:\\Inno\\ISCC.exe")
        self.assertEqual((found["numbers"], found["source"]), ((6, 6, 0, 0), "파일 제품 판"))
        found = measure.read_inno_version(Stub("", "", "FILE=6.5.0.0\r\nPRODUCT=0.0.0.0\r\n"), "C:\\Inno\\ISCC.exe")
        self.assertEqual((found["numbers"], found["source"]), ((6, 5, 0, 0), "파일 판"))

    def test_when_nothing_can_be_read_the_reason_names_every_way_and_what_each_gave(self):
        class Silent:
            def run(self, args, **kwargs):
                if "DisplayVersion" in args[-1]:
                    return measure.HostResult(0, 0.1, "", "")
                if list(args)[1:] == ["/?"]:
                    return measure.HostResult(0, 0.1, "Inno Setup 6 Command-Line Compiler\r\n", "")
                return measure.HostResult(0, 0.1, "FILE=0.0.0.0\r\nPRODUCT=0.0.0.0\r\n", "")

        found = measure.read_inno_version(Silent(), "C:\\Inno\\ISCC.exe")
        self.assertIsNone(found["numbers"])
        self.assertEqual(found["source"], "")
        for word in ("컴파일러 출력 읽히지 않음", "레지스트리 읽히지 않음", "파일 제품 판 빈 값 0.0.0.0", "파일 판 빈 값 0.0.0.0"):
            self.assertIn(word, found["reason"])
        self.assertIsNone(measure.inno_version_ok(found["numbers"]))

    def test_a_program_that_cannot_even_start_is_just_unreadable(self):
        class Broken:
            def run(self, args, **kwargs):
                return measure.HostResult(-1, 0.0, error="OSError")

        found = measure.read_inno_version(Broken(), "C:\\nowhere\\ISCC.exe")
        self.assertIsNone(found["numbers"])
        self.assertTrue(found["reason"])


class SelftestVerdictTest(unittest.TestCase):
    """결정 D-810 — 1차 측정은 설치본·휴대용 `--selftest` 의 통과 개수가 12 인지를 봤다. 앱이 점검을 열세 개로 늘린 뒤에도(M129) 그대로라 통과 13·실패 0·건너뜀 0 이 실패로 적혔다(M06·M22, 관문 G8)."""
    NAMES = ("utf8_mode", "version_file", "package_info", "file_hashes", "licenses", "vendor_core", "capabilities", "tls", "uac_manifest", "qt_plugins", "qt_screens", "gui_only_entry", "data_dir_untouched")

    def counts(self, names=None, **changes):
        names = list(self.NAMES if names is None else names)
        base = {"passed": len(names), "failed": 0, "skipped": 0, "failed_names": [], "passed_names": names, "rc": 0, "judged": True}
        base.update(changes)
        return base

    def test_the_real_app_list_is_read_without_importing_the_file_and_agrees_with_the_test_helper_list(self):
        keys = measure.app_selftest_keys(ROOT)
        self.assertEqual(keys, support.app_selftest_names())                                 # 다른 방법(정규식)으로 읽은 목록과 같다
        self.assertGreaterEqual(len(keys), measure.MIN_SELFTEST_PASSED)
        self.assertIn("tls", keys)
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(measure.app_selftest_keys(), keys)                                   # 저장소 위치를 안 줘도 이 도구 파일 위치에서 찾는다

    def test_the_test_helpers_reader_is_not_fooled_by_parentheses_in_comments_or_strings_inside_the_tuple(self):
        """재작업 Q-R6(다) — 가짜 세계가 쓰는 점검 이름 읽개(글자 단위)는 튜플 안 주석이나 글 속의 괄호에서 일찍 끊기지 않는다. 다른 갈래가 점검 이름 줄 끝에 '(M129)' 같은 주석을 달면 정규식 읽개는 거기서 끊겨
        가짜 세계의 점검 목록이 잘리고 흐름 시험이 줄줄이 빨개질 뻔했다. 두 읽개(이 읽개와 `ast` 로 읽는 `measure.app_selftest_keys`)가 같은 답을 내는지도 본다."""
        source = ('X = 1\nSELFTEST_KEYS = ("utf8_mode",  # 첫째 (M129 에서 더함)\n                 "tls",   # TLS 점검 (접속 부품) 끝\n                 "a_b", "c_d",  # 글 속 괄호 ")" 와 # 와 \' 따옴표\n'
                  '                 "e_f",\n                 )   # 끝 (끝)\nOTHER = ("zzz",)\n')
        self.assertEqual(support.app_selftest_names(source), ("utf8_mode", "tls", "a_b", "c_d", "e_f"))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "scripts").mkdir()
            (Path(tmp) / "scripts" / "release_check.py").write_text(source, encoding="utf-8")
            self.assertEqual(measure.app_selftest_keys(tmp), support.app_selftest_names(source))                  # 다른 방법(ast)으로 읽어도 같다
        for text, expected in (("", ()), ("SELFTEST_KEYS = (", ()), ("OTHER = ('a',)\n", ()), ('SELFTEST_KEYS = ("a", "b")\n', ("a", "b")), ('  SELFTEST_KEYS = ("a",)\n', ())):
            self.assertEqual(support.app_selftest_names(text), expected, text)

    def test_the_list_reader_accepts_a_tuple_or_a_list_and_gives_up_quietly_on_anything_else(self):
        cases = {"튜플": ('SELFTEST_KEYS = ("a", "b",\n                 "c")   # 주석\n', ("a", "b", "c")), "목록": ("SELFTEST_KEYS = ['a', 'b']\n", ("a", "b")),
                 "다른 이름": ("OTHER_KEYS = ('a', 'b')\n", ()), "빈 튜플": ("SELFTEST_KEYS = ()\n", ()), "겹침": ("SELFTEST_KEYS = ('a', 'a')\n", ()), "글 아님": ("SELFTEST_KEYS = ('a', 1)\n", ()),
                 "빈 글": ("SELFTEST_KEYS = ('a', '')\n", ()), "계산식": ("SELFTEST_KEYS = tuple(name for name in ('a', 'b'))\n", ()), "문법 오류": ("SELFTEST_KEYS = (\n", ()), "숫자": ("SELFTEST_KEYS = 5\n", ())}
        for label, (source, expected) in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "scripts").mkdir()
                (Path(tmp) / "scripts" / "release_check.py").write_text(source, encoding="utf-8")
                self.assertEqual(measure.app_selftest_keys(tmp), expected)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(measure.app_selftest_keys(tmp), ())                              # 파일이 없다

    def test_the_reader_never_runs_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "scripts").mkdir()
            marker = Path(tmp) / "ran.txt"
            (Path(tmp) / "scripts" / "release_check.py").write_text("open(%r, 'w').write('ran')\nSELFTEST_KEYS = ('a', 'b')\n" % str(marker), encoding="utf-8")
            self.assertEqual(measure.app_selftest_keys(tmp), ("a", "b"))
            self.assertFalse(marker.exists())

    def test_thirteen_passed_lines_that_equal_the_apps_list_pass_where_the_old_count_of_twelve_failed(self):
        verdict = measure.selftest_verdict(self.counts(), self.NAMES)
        self.assertTrue(verdict["ok"])
        self.assertEqual((verdict["expected"], verdict["missing"], verdict["extra"]), (13, [], []))
        self.assertIn("13개와 같다", verdict["basis"])

    def test_a_check_missing_from_the_passed_lines_fails_and_is_named(self):
        verdict = measure.selftest_verdict(self.counts([name for name in self.NAMES if name != "tls"]), self.NAMES)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["missing"], ["tls"])
        self.assertIn("tls", verdict["basis"])

    def test_a_passed_line_with_another_name_does_not_fill_the_place_of_a_check(self):
        """재작업 Q-R1 — 이름 비교는 정확히 같은 글자여야 한다: 부분 일치(tls_old)·대소문자만 다름(TLS)·공백이 붙음(tls )·앞에 글자가 붙음(xtls)으로 점검 하나를 '찍힌 것' 으로 치지 않는다.
        통과 줄의 수는 그대로 열세 개라 개수만 보는 옛 판정은 이 넷을 모두 통과로 읽었을 것이다."""
        for fake in ("tls_old", "TLS", "tls ", "xtls", "tls2", "Tls"):
            with self.subTest(fake):
                names = [fake if name == "tls" else name for name in self.NAMES]
                self.assertEqual(len(names), len(self.NAMES))
                verdict = measure.selftest_verdict(self.counts(names), self.NAMES)
                self.assertFalse(verdict["ok"])
                self.assertEqual(verdict["missing"], ["tls"])
                self.assertEqual(verdict["extra"], [fake])
                self.assertIn("tls 가 통과로 찍히지 않았다", verdict["basis"])

    def test_the_basis_names_why_the_run_was_not_clean_even_when_every_check_line_passed(self):
        """재작업 S-R4 — 점검 줄이 모두 통과여도 종료 코드가 0 이 아니거나 시간 초과이거나 빌드 판정이 거절이면 통과가 아니다. 근거 문구가 '앱 점검 목록 13개와 같다' 만 말하면 1차 상자처럼 왜 실패인지 알 수 없다."""
        clean = measure.selftest_verdict(self.counts(), self.NAMES)
        self.assertTrue(clean["ok"])
        self.assertEqual(clean["basis"], "앱 점검 목록 13개와 같다")
        self.assertNotIn("깨끗하지 않음", clean["basis"])
        cases = (("종료 코드 3", {"rc": 3}, "깨끗하지 않음: 종료 코드 3"), ("종료 코드 음수", {"rc": -1073741502}, "깨끗하지 않음: 종료 코드 -1073741502"), ("종료 코드 없음", {"rc": None}, "깨끗하지 않음: 시간 초과"),
                 ("시간 초과 표시", {"timed_out": True, "rc": None}, "깨끗하지 않음: 시간 초과"), ("빌드 판정", {"judged": False}, "깨끗하지 않음: 빌드 판정 거절"),
                 ("둘 다", {"rc": 2, "judged": False}, "깨끗하지 않음: 종료 코드 2·빌드 판정 거절"), ("실패 건너뜀", {"failed": 2, "skipped": 1}, "깨끗하지 않음: 실패 2·건너뜀 1"))
        for label, change, expected in cases:
            with self.subTest(label):
                verdict = measure.selftest_verdict(self.counts(**change), self.NAMES)
                self.assertFalse(verdict["ok"])
                self.assertEqual(verdict["missing"], [])                                               # 점검 이름은 모두 통과 줄로 찍혔다 — 그래도 불통과이고 이유가 근거에 있다
                self.assertTrue(verdict["basis"].startswith("앱 점검 목록 13개와 같다"), verdict["basis"])
                self.assertTrue(verdict["basis"].endswith(expected), verdict["basis"])
        floor = measure.selftest_verdict(self.counts(rc=4), ())
        self.assertFalse(floor["ok"])
        self.assertTrue(floor["basis"].endswith("깨끗하지 않음: 종료 코드 4"), floor["basis"])
        extra = measure.selftest_verdict(self.counts(list(self.NAMES) + ["more"], rc=5), self.NAMES)
        self.assertIn("목록에 없는 점검 1개가 더 찍힘: more", extra["basis"])
        self.assertTrue(extra["basis"].endswith("깨끗하지 않음: 종료 코드 5"), extra["basis"])
        counts = self.counts()
        del counts["rc"]
        self.assertFalse(measure.selftest_verdict(counts, self.NAMES)["ok"])                          # 종료 코드를 모르면 깨끗하다고 보지 않는다
        self.assertTrue(measure.selftest_verdict(counts, self.NAMES)["basis"].endswith("깨끗하지 않음: 종료 코드 모름"))

    def test_the_box_cell_carries_the_exit_code_and_the_reasons_and_nothing_extra_when_clean(self):
        """상자 한 칸(brief) — 센 개수 뒤에 근거가 붙는다. 깨끗하지 않으면 종료 코드·시간 초과·빌드 판정 거절이 칸에 보이고, 깨끗하면 덧붙는 말이 없다."""
        for change, words in (({"rc": 3}, ("종료 코드 3",)), ({"rc": None, "timed_out": True}, ("시간 초과",)), ({"judged": False}, ("빌드 판정 거절",)), ({"rc": 3, "judged": False}, ("종료 코드 3", "빌드 판정 거절"))):
            counts = self.counts(**change)
            brief = measure.selftest_brief("설치본", dict(counts, basis=measure.selftest_verdict(counts, self.NAMES)["basis"]))
            self.assertTrue(brief.startswith("설치본 selftest 통과 13 실패 0 건너뜀 0 · 앱 점검 목록 13개와 같다"), brief)
            for word in words:
                self.assertIn(word, brief)
            self.assertLessEqual(len(brief), run.CELL_LIMIT, brief)                                      # 상자 칸(110자)이 이유를 자르기 전에 들어간다
        counts = self.counts()
        self.assertEqual(measure.selftest_brief("휴대용", dict(counts, basis=measure.selftest_verdict(counts, self.NAMES)["basis"])), "휴대용 selftest 통과 13 실패 0 건너뜀 0 · 앱 점검 목록 13개와 같다")

    def test_extra_checks_the_list_does_not_know_do_not_fail_and_are_noted(self):
        verdict = measure.selftest_verdict(self.counts(list(self.NAMES) + ["brand_new_check"]), self.NAMES)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["extra"], ["brand_new_check"])
        self.assertIn("brand_new_check", verdict["basis"])

    def test_any_failed_skipped_or_nonzero_exit_or_rejected_judgement_fails_even_with_every_name_present(self):
        for label, change in (("실패", {"failed": 1}), ("건너뜀", {"skipped": 1}), ("종료 코드", {"rc": 1}), ("종료 코드 없음", {"rc": None}), ("빌드 판정", {"judged": False})):
            with self.subTest(label):
                self.assertFalse(measure.selftest_verdict(self.counts(**change), self.NAMES)["ok"])

    def test_without_the_apps_list_the_floor_of_twelve_applies_and_thirteen_still_passes(self):
        for passed, expected in ((12, True), (13, True), (14, True), (11, False), (0, False)):
            names = ["check_%02d" % number for number in range(passed)]
            verdict = measure.selftest_verdict(self.counts(names), ())
            self.assertEqual(verdict["ok"], expected, passed)
            self.assertIsNone(verdict["expected"])
            self.assertIn("목록을 읽지 못해", verdict["basis"])
        self.assertFalse(measure.selftest_verdict(self.counts(["check"] * 12, failed=1), ())["ok"])
        self.assertTrue(measure.selftest_verdict(self.counts(), None)["ok"])

    def test_the_verdict_leaves_the_counts_alone_and_the_brief_prints_the_counts_as_they_are(self):
        counts = self.counts()
        before = json.dumps(counts, sort_keys=True)
        verdict = measure.selftest_verdict(counts, self.NAMES)
        self.assertEqual(json.dumps(counts, sort_keys=True), before)
        brief = measure.selftest_brief("설치본", dict(counts, basis=verdict["basis"]))
        self.assertTrue(brief.startswith("설치본 selftest 통과 13 실패 0 건너뜀 0 · "), brief)
        self.assertIn("앱 점검 목록 13개와 같다", brief)

    def test_the_counts_keep_the_passed_names_in_order(self):
        parsed = {"passed": ["a", "b"], "failed": ["c"], "skipped": ["d"], "failed_text": {}}
        counts = measure.parse_selftest_counts(parsed)
        self.assertEqual((counts["passed"], counts["failed"], counts["skipped"]), (2, 1, 1))
        self.assertEqual(counts["passed_names"], ["a", "b"])
        self.assertEqual(counts["failed_names"], ["c"])


class StandardUserParsingTest(unittest.TestCase):
    """결정 D-810 — 표준 사용자 시험의 출력 읽기와 설치 흔적 찾기."""

    def test_the_exit_marker_is_read_in_every_shape_the_script_can_print(self):
        cases = (("SPIKE_EXIT=0\r\n", 0, ("code", 0)), ("SPIKE_EXIT=42\n", 1, ("code", 42)), ("SPIKE_EXIT=-1073741502\r\n", 1, ("code", -1073741502)), ("앞 글\r\nSPIKE_EXIT=740\r\n", 0, ("code", 740)),
                 ("SPIKE_EXIT=none\r\n", 0, ("none", None)), ("SPIKE_EXIT=\r\n", 0, ("none", None)), ("SPIKE_EXIT=abc\r\n", 0, ("none", None)),
                 ("SPIKE_START_ERROR=InvalidOperationException\r\n", 1, ("error", "InvalidOperationException")), ("", 0, ("plain", 0)), ("아무 표지 없음", 7, ("plain", 7)), (None, 3, ("plain", 3)))
        for text, rc, expected in cases:
            self.assertEqual(measure.parse_std_exit(text, rc), expected, text)

    def test_a_launch_error_wins_over_an_exit_marker_and_a_marker_inside_a_line_is_not_a_marker(self):
        self.assertEqual(measure.parse_std_exit("SPIKE_EXIT=0\r\nSPIKE_START_ERROR=Win32Exception\r\n", 1), ("error", "Win32Exception"))
        self.assertEqual(measure.parse_std_exit("echo SPIKE_EXIT=0 은 표지가 아니다\r\n", 5), ("plain", 5))

    def test_traces_are_found_by_file_name_anywhere_under_the_local_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "Local"
            for relative in ("ChanceBlogSpikeA/current/VERSION", "ChanceBlogSpikeA/Update.exe", "Programs/ChanceBlogSpikeC/unins000.exe", "Microsoft/Windows/other.txt"):
                path = local / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
            found = measure.std_user_traces(local, limit=10)
            self.assertEqual(sorted(found), ["ChanceBlogSpikeA/Update.exe", "ChanceBlogSpikeA/current/VERSION", "Programs/ChanceBlogSpikeC/unins000.exe"])
            self.assertEqual(len(measure.std_user_traces(local, limit=2)), 2)
            self.assertEqual(measure.std_user_traces(local / "nothing"), [])
            (local / "empty").mkdir()
            self.assertEqual(measure.std_user_traces(local / "empty"), [])

    def test_a_lookalike_file_name_is_not_a_trace_and_the_name_match_ignores_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp)
            (local / "VERSION.txt").write_bytes(b"x")
            (local / "my-version").write_bytes(b"x")
            self.assertEqual(measure.std_user_traces(local), [])
            (local / "Update.EXE").write_bytes(b"x")
            self.assertEqual(measure.std_user_traces(local), ["Update.EXE"])

    def test_the_script_sets_the_new_users_variables_before_it_starts_the_program_and_reads_the_exit_code_without_trusting_it(self):
        script = measure.std_user_script()
        for variable in ("$env:USERNAME =", "$env:USERPROFILE =", "$env:LOCALAPPDATA =", "$env:APPDATA =", "$env:TEMP =", "$env:TMP ="):
            self.assertIn(variable, script, variable)
            self.assertLess(script.index(variable), script.index("Start-Process"), variable)                                   # 띄우기 전에 정한다
        for word in ("PSCredential", "-Credential", "-LoadUserProfile", "-Wait", "-PassThru", "SPIKE_EXIT=", "SPIKE_START_ERROR=", "$null -eq $code"):
            self.assertIn(word, script, word)
        for word in ("-ErrorAction Stop", "WaitForExit()", "catch {", "SPIKE_START_MESSAGE=", "$_.Exception.Message", "-replace '\\s+', ' '", "$m.Length -gt 300", "$m.Substring(0, 300)"):   # 재작업 S-R3·Q-R3 — 1차 M18 결함의 핵심 수정(띄우기 실패를 잡아 종료 0 으로 흐르지 않게)과 종료 코드를 읽기 전에 기다리는 줄, 오류 문장을 한 줄로 접고 300자까지만 찍는 줄
            self.assertIn(word, script, word)
        order = [script.index(word) for word in ("Start-Process", "-ErrorAction Stop", "catch {", "SPIKE_START_ERROR=", "SPIKE_START_MESSAGE=", "WaitForExit()", "$p.ExitCode", "$null -eq $code", "SPIKE_EXIT=")]
        self.assertEqual(order, sorted(order))                                                                                 # 띄우기 → 실패를 잡아 오류·문장을 찍고 끝냄 → 기다림 → 종료 코드 읽기 → 표지 찍기
        self.assertLess(script.index("-ErrorAction Stop"), script.index("catch {"))
        self.assertEqual(script.count("-ErrorAction Stop"), 1)
        self.assertNotIn("-UseNewEnvironment", script)                                                                         # 현재 사용자의 환경을 불러오는 것으로 알려져 믿지 않는다 — 변수를 명시한다
        self.assertNotIn("SPIKE_PW'", script)                                                                                  # 비밀번호는 환경 변수 이름으로만 쓰고 글로 박지 않는다

    @unittest.skipUnless(os.name == "nt", "윈도 PowerShell 에서만 도는 시험")
    def test_the_script_run_for_real_without_the_credential_arguments_reads_the_exit_code_and_the_launch_error(self):
        """재작업 S-R3·Q-R3 — 스크립트는 가짜 세계에서 돌지 않는다(가짜는 출력 약속만 흉내 낸다). 그래서 `-ErrorAction Stop` 한 줄이 사라져도 다른 시험은 모른다 — 1차 M18 의 '종료 0 인데 설치 흔적 없음' 이 바로 그 줄이 없을 때
        생기는 증상이다(띄우기 실패가 화면 오류로만 나오고 `$p` 가 비어 종료 코드 0). 진짜 PowerShell 로 같은 스크립트에서 `-Credential $cred -LoadUserProfile` 두 인자만 지운 사본을 돌려 '띄운 뒤' 의 논리를 확인한다 —
        다른 사용자로 로그온하지 않고 `cmd.exe /d /c exit N` 만 띄운다(가짜 비밀번호는 조립한 시험용 값)."""
        script = measure.std_user_script()
        plain = script.replace(" -Credential $cred -LoadUserProfile", "")
        self.assertNotEqual(plain, script)                                                                                     # 정말 두 인자가 지워졌다 — 아니면 이 시험은 다른 사용자로 띄우려 들 것이다
        self.assertNotIn("-Credential $cred", plain)
        self.assertNotIn("-LoadUserProfile", plain)
        host = measure.Host()
        with tempfile.TemporaryDirectory() as tmp:
            def attempt(program, arguments):
                env = {"SPIKE_PW": "CANARY_" + "not_a_secret", "SPIKE_USER": "spikeuserx", "SPIKE_SETUP": program, "SPIKE_ARGS": arguments, "SPIKE_CWD": tmp, "SPIKE_PROFILE": str(Path(tmp) / "profile"), "SPIKE_TMP": str(Path(tmp) / "tmp")}
                result = host.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", plain], timeout=120, env=env)
                kind, value = measure.parse_std_exit(result.text(), result.rc)
                return result, kind, value

            for code in (42, 0, 740):
                with self.subTest(code):
                    result, kind, value = attempt("cmd.exe", "/d /c exit %d" % code)
                    self.assertEqual((kind, value, result.rc), ("code", code, code), result.text())                              # 종료 코드를 줄로 읽었고 스크립트의 종료 코드도 같다
                    self.assertEqual(measure.parse_std_message(result.text()), "")
            with self.subTest("없는 프로그램"):
                result, kind, value = attempt(str(Path(tmp) / "no_such_folder" / "none.exe"), "/d /c exit 1")
                self.assertEqual((kind, value, result.rc), ("error", "InvalidOperationException", 1), result.text())          # 띄우기 실패가 종료 0 으로 흐르지 않고 잡혔다
                message = measure.parse_std_message(result.text())
                self.assertTrue(message, result.text())                                                                        # 오류 문장(윈도의 언어로)도 함께 찍힌다
                self.assertNotIn("\n", message)
                self.assertLessEqual(len(message), 300)

    def test_the_launch_message_line_is_read_only_at_the_start_of_a_line_and_folded(self):
        for text, expected in (("SPIKE_START_ERROR=X\r\nSPIKE_START_MESSAGE=가   나\t다  \r\n", "가 나 다"), ("SPIKE_START_MESSAGE=\r\n", ""), ("앞 SPIKE_START_MESSAGE=표지가 아니다\r\n", ""), ("", ""), (None, ""),
                               ("SPIKE_START_MESSAGE=첫째\r\nSPIKE_START_MESSAGE=둘째\r\n", "첫째"), ("SPIKE_EXIT=0\r\n", "")):
            self.assertEqual(measure.parse_std_message(text), expected, text)
        self.assertEqual(measure.parse_std_exit("SPIKE_START_ERROR=InvalidOperationException\r\nSPIKE_START_MESSAGE=SPIKE_EXIT=0\r\n", 1), ("error", "InvalidOperationException"))      # 문장 속의 표지 모양은 표지가 아니다
        self.assertEqual(measure.parse_std_exit("SPIKE_START_MESSAGE=SPIKE_EXIT=0\r\n", 5), ("plain", 5))


class StandardUserNameTest(unittest.TestCase):
    """결정 D-810 — 갈래마다 다른 임시 사용자 이름(같은 이름을 지웠다 다시 만들면 윈도가 새 프로필 폴더에 컴퓨터 이름을 붙여 흔적을 찾는 곳이 어긋난다)."""

    def test_each_arm_gets_its_own_short_alphanumeric_name_and_its_own_profile_folder(self):
        names = {arm: measure.std_user_name(arm) for arm in "ABC"}
        self.assertEqual(names, {"A": "spikeusera", "B": "spikeuserb", "C": "spikeuserc"})
        for name in names.values():
            self.assertTrue(name.startswith(measure.STD_USER))
            self.assertTrue(name.isalnum())
            self.assertLessEqual(len(name), 20)                                                     # 윈도 사용자 이름은 스무 글자까지
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(tmp, environ={"PUBLIC": "D:/Users/Public"})
            profiles = {name: measure.std_user_folders(ctx, name)[1] for name in names.values()}
            self.assertEqual(len(set(profiles.values())), 3)
            for name, profile in profiles.items():
                self.assertEqual(profile, Path("D:/Users") / name / "AppData" / "Local")
            self.assertEqual(measure.std_user_folders(ctx)[1], Path("D:/Users") / measure.STD_USER / "AppData" / "Local")        # 이름을 안 주면 예전 그대로


class HookLogLinesTest(unittest.TestCase):
    """결정 D-810 — 설치 도구 로그의 훅 줄(설치가 훅 한도 30초를 기다렸는지 로그에서 직접 보려는 것 — 1차 측정은 이 로그를 읽지 않았다)."""

    def lines(self, text, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup.log"
            path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
            return measure.hook_log_lines(path, **kwargs)

    def test_only_the_lines_that_talk_about_hooks_are_picked_in_order_and_counted(self):
        found, count = self.lines("start\nRunning post-install HOOK now\nunrelated\nargs --veloapp-install 0.1.0\nHook timed out after 30s\nend\n")
        self.assertEqual(found, ["Running post-install HOOK now", "args --veloapp-install 0.1.0", "Hook timed out after 30s"])
        self.assertEqual(count, 3)

    def test_the_list_is_cut_at_the_limit_but_the_count_is_not(self):
        found, count = self.lines("\n".join("hook line %d" % number for number in range(10)), limit=4)
        self.assertEqual((len(found), count), (4, 10))
        self.assertEqual(found[0], "hook line 0")

    def test_a_missing_empty_or_hookless_log_gives_nothing(self):
        self.assertEqual(measure.hook_log_lines(Path("no/such/file.log")), ([], 0))
        self.assertEqual(measure.hook_log_lines(None), ([], 0))
        self.assertEqual(self.lines(""), ([], 0))
        self.assertEqual(self.lines("only ordinary lines\nhere\n"), ([], 0))

    def test_utf16_and_cp949_logs_are_read_too(self):
        self.assertEqual(self.lines("설치 시작\nhook 실행\n".encode("utf-16"))[1], 1)
        self.assertEqual(self.lines("설치 시작\nhook 실행\n".encode("cp949"))[1], 1)


class PeRegionsTest(unittest.TestCase):
    """결정 D-810 — M17: 1차 측정의 '한글 글 UTF-8 479' 는 실행 파일 전체를 한 번에 세어, 설치 도구가 안에 붙인 앱 묶음의 글자와 설치 도구 자신의 화면 글자를 가르지 못했다."""
    KOREAN = "설치마법사".encode("utf-8")

    def pe(self, put_at=None, extra=b""):
        data = bytearray(build_pe(["kernel32.dll"]))
        if put_at is not None:
            data[put_at:put_at + len(self.KOREAN)] = self.KOREAN
        return bytes(data) + extra

    def test_the_end_of_the_sections_is_where_the_appended_chunk_begins(self):
        self.assertEqual(measure.pe_image_end(self.pe()), 0xC00)                                      # 합성 PE 의 구역은 0x400 에서 0x800 바이트
        self.assertIsNone(measure.pe_image_end(b"not a pe file" * 50))
        self.assertIsNone(measure.pe_image_end(b""))
        self.assertIsNone(measure.pe_image_end(build_pe([])[:0x100]))

    def test_korean_text_inside_the_sections_and_in_the_appended_chunk_are_counted_apart(self):
        inside = measure.hangul_regions(self.pe(put_at=0xA00))
        self.assertTrue(inside["split"])
        self.assertGreaterEqual(inside["image"]["utf8"], 1)
        self.assertEqual(inside["overlay"], {"utf8": 0, "utf16": 0})
        appended = measure.hangul_regions(self.pe(extra=b"\x00\x01" + self.KOREAN * 40))
        self.assertTrue(appended["split"])
        self.assertEqual(appended["image"], {"utf8": 0, "utf16": 0})
        self.assertGreaterEqual(appended["overlay"]["utf8"], 1)
        self.assertEqual(appended["utf8"], appended["image"]["utf8"] + appended["overlay"]["utf8"])        # 전체 값은 두 구간의 합과 같다

    def test_a_file_that_is_not_a_pe_gets_only_the_whole_value_and_says_it_could_not_split(self):
        found = measure.hangul_regions(b"\x01" + self.KOREAN * 3)
        self.assertFalse(found["split"])
        self.assertIsNone(found["image"])
        self.assertIsNone(found["overlay"])
        self.assertGreaterEqual(found["utf8"], 1)
        self.assertEqual(measure.hangul_regions(b"plain ascii only " * 50)["utf8"], 0)

    def test_the_old_whole_file_function_still_counts_the_same(self):
        data = self.pe(put_at=0xA00, extra=self.KOREAN * 5)
        whole = measure.hangul_samples(data)
        split = measure.hangul_regions(data)
        self.assertEqual((split["utf8"], split["utf16"]), (whole["utf8"], whole["utf16"]))


class LongPathTest(unittest.TestCase):
    """결정 D-810 — M19: 1차 측정의 설치 경로는 75자였다(설계서는 한글·공백이 든 100자 경로)."""

    def test_the_path_is_at_least_a_hundred_characters_with_korean_and_spaces_for_any_work_folder(self):
        for work in ("D:\\a\\_temp\\spike", "C:\\x", "C:\\Users\\Someone\\AppData\\Local\\Temp\\spike-work-folder-with-a-long-name"):
            with tempfile.TemporaryDirectory() as tmp:
                ctx = make_context(tmp)
                ctx.work = Path(work)
                for arm in "ABC":
                    base = measure.long_path_base(ctx, arm)
                    for leaf in ("tiny", "real"):
                        self.assertGreaterEqual(len(str(base / leaf)), measure.LONG_PATH_CHARS, (work, arm, leaf))
                    self.assertTrue(any("가" <= char <= "힣" for char in base.name))
                    self.assertIn(" ", base.name)
                    self.assertEqual(base.parent, Path(work) / "run" / arm)

    def test_the_length_is_the_design_value_and_not_something_a_run_could_lower(self):
        self.assertEqual(measure.LONG_PATH_CHARS, 100)                                                  # 설계서 3-1(f) M19: 한글·공백이 든 100자 경로

    def test_an_already_long_work_folder_is_not_padded_further_than_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(tmp)
            ctx.work = Path("C:\\" + "w" * 120)
            self.assertEqual(measure.long_path_base(ctx, "A").name, "한글 공백")


WINDOWS_ENV = {"IMAGEOS": "win25", "IMAGEVERSION": "20261116.335.1", "RUNNER_OS": "Windows", "GITHUB_SHA": "0123456789abcdef", "USERNAME": "runneradmin"}            # 윈도에서 `dict(os.environ)` 이 만드는 모양(이름이 모두 대문자)
ALL_TOOLS = {"python": {"version": "3.12.10"}, "dotnet": {"version": "11.0.100"}, "vpk": {"status": "ok", "version": "1.2.161", "version_source": "vpk --version"},
             "iscc": {"status": "ok", "version": "6.7.1", "version_source": "레지스트리", "version_ok": True, "design_line": True}}


class BlockShapeTest(unittest.TestCase):
    """결정 D-810 — 1차 측정 결과 상자의 모양: 머리 줄의 빈 칸, 한 줄에 '/' 로 이어 붙인 두 결과, 중간에 잘린 M20 줄, 통과로 보이지만 단서가 있는 관문."""

    def block(self, results=None, state=None, environ=None):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(tmp, environ=environ, results=results, state=state)
            block, md, data = run.build_report(ctx)
        return block.splitlines(), md, data

    def test_the_header_names_the_runner_and_the_image_even_when_the_environment_names_are_upper_case(self):
        lines, _md, _data = self.block(environ=WINDOWS_ENV, state={"tools": ALL_TOOLS})
        self.assertEqual(lines[1], "러너: Windows win25 20261116.335.1 · 파이썬 3.12.10 · dotnet 11.0.100 · vpk 1.2.161 · Inno 6.7.1(레지스트리) · 커밋 0123456")
        self.assertNotIn("?", lines[1])

    def test_a_header_field_that_cannot_be_read_gives_the_reason_not_a_question_mark(self):
        lines, _md, _data = self.block(environ={}, state={"tools": {}})
        header = lines[1]
        for word in ("OS 못 읽음(RUNNER_OS 없음)", "이미지 이름 못 읽음(ImageOS 없음)", "이미지 판 못 읽음(ImageVersion 없음)", "파이썬 못 읽음", "dotnet 못 읽음", "vpk 없음", "Inno 없음", "커밋 못 읽음(GITHUB_SHA 없음)"):
            self.assertIn(word, header, word)
        self.assertNotIn("?", header)

    def test_the_commit_is_cut_to_seven_characters_only_when_it_was_read(self):
        lines, _md, _data = self.block(environ=dict(WINDOWS_ENV, GITHUB_SHA="d2ab446abcdef"), state={"tools": ALL_TOOLS})
        self.assertTrue(lines[1].endswith("커밋 d2ab446"), lines[1])

    def test_the_vpk_label_says_where_the_version_came_from_unless_it_came_from_the_tool_itself(self):
        self.assertEqual(run.vpk_label({"status": "ok", "version": "1.2.161", "version_source": "vpk --version"}), "vpk 1.2.161")
        self.assertEqual(run.vpk_label({"version": "1.2.161"}), "vpk 1.2.161")
        self.assertEqual(run.vpk_label({"status": "ok", "version": "1.2.161", "version_source": "dotnet tool list"}), "vpk 1.2.161(dotnet tool list)")
        self.assertIn("잠금 파일", run.vpk_label({"status": "ok", "version": "1.2.161", "version_source": "잠금 파일 값 — vpk 출력에서 판을 읽지 못함"}))
        self.assertEqual(run.vpk_label({"status": "ok", "version": ""}), "vpk 판 못 읽음")
        self.assertEqual(run.vpk_label({"status": "failed", "reason": "dotnet tool install 실패"}), "vpk 없음(dotnet tool install 실패)")
        self.assertEqual(run.vpk_label(None), "vpk 없음")

    def test_the_inno_label_covers_found_low_off_the_design_line_unknown_and_missing(self):
        self.assertEqual(run.inno_label({"status": "ok", "version": "6.7.1", "version_source": "레지스트리", "version_ok": True, "design_line": True}), "Inno 6.7.1(레지스트리)")
        self.assertEqual(run.inno_label({"version": "6.7.1"}), "Inno 6.7.1")
        self.assertIn("설계서의 6.7 줄이 아님", run.inno_label({"status": "ok", "version": "6.8.0", "version_source": "파일 판", "version_ok": True, "design_line": False}))
        self.assertIn("6.5.0 보다 낮아 쓰지 않음", run.inno_label({"status": "ok", "version": "6.4.3", "version_source": "파일 판", "version_ok": False, "design_line": False}))
        unknown = run.inno_label({"status": "ok", "version": "", "version_ok": None, "version_reason": "파일 판 빈 값 0.0.0.0 · 레지스트리 읽히지 않음"})
        self.assertIn("Inno 판 미확인(파일 판 빈 값 0.0.0.0", unknown)
        self.assertIn("계속 진행", unknown)
        self.assertEqual(run.inno_label({"status": "unavailable", "reason": "ISCC.exe 를 찾지 못했다"}), "Inno 없음(ISCC.exe 를 찾지 못했다)")
        self.assertEqual(run.inno_label(None), "Inno 없음")

    def test_a_measurement_with_two_targets_is_two_lines_one_per_target_with_the_small_app_first(self):
        results = [rec("M05", "B", "pass", brief="종료 0 30.6초", target="real"), rec("M05", "A", "pass", brief="종료 0 0.4초", target="tiny"), rec("M05", "B", "pass", brief="종료 0 0.4초", target="tiny"),
                   rec("M05", "C", "unavailable", brief="설치 파일 없음", target="tiny"), rec("M05", "C", "unavailable", brief="설치 파일 없음", target="real")]
        lines = run.measurement_lines(results, "M05")
        self.assertEqual(lines, ["M05 무음 설치(작은 앱) | A 통과 종료 0 0.4초 | B 통과 종료 0 0.4초 | C 시도 불가 설치 파일 없음", "M05 무음 설치(실제 묶음) | B 통과 종료 0 30.6초 | C 시도 불가 설치 파일 없음"])
        for line in lines:
            self.assertNotIn(" / ", line)                                                      # 두 결과를 '/' 로 잇지 않는다

    def test_a_measurement_with_one_target_or_none_stays_one_line_without_a_suffix(self):
        self.assertEqual(run.measurement_lines([rec("M08", "A", "pass", brief="x", target="tiny"), rec("M08", "B", "pass", brief="y", target="tiny")], "M08"), ["M08 업데이트 | A 통과 x | B 통과 y"])
        self.assertEqual(run.measurement_lines([rec("M14", "A", "pass", brief="x")], "M14"), ["M14 접속 차단 | A 통과 x"])
        self.assertEqual(run.measurement_lines([], "M14"), ["M14 접속 차단 | 기록 없음"])

    def test_a_record_without_a_target_joins_the_first_line_and_a_common_record_joins_its_own_targets_line(self):
        results = [rec("M07", "A", "pass", brief="훅 4/4", target="tiny"), rec("M07", "B", "pass", brief="훅 4/4"), rec("M07", "-", "info", brief="실제 묶음 훅: 종료 코드 2/2/2/2", target="real")]
        self.assertEqual(run.measurement_lines(results, "M07"), ["M07 훅(작은 앱) | A 통과 훅 4/4 | B 통과 훅 4/4", "M07 훅(실제 묶음) | 기록 실제 묶음 훅: 종료 코드 2/2/2/2"])

    def test_three_or_more_targets_and_an_unknown_target_name_each_get_a_line(self):
        results = [rec("M15", "A", "info", brief="휠 2.8 MB", target="wheel"), rec("M15", "A", "info", brief="더 큼", target="bundle-delta"), rec("M15", "A", "info", brief="가져오기 14개", target="setup"), rec("M15", "B", "info", brief="가져오기 14개", target="setup"),
                   rec("M15", "A", "info", brief="새 대상", target="brand-new")]
        lines = run.measurement_lines(results, "M15")
        self.assertEqual([line.split(" | ")[0] for line in lines], ["M15 네이티브 부품(휠)", "M15 네이티브 부품(묶음 크기 차이)", "M15 네이티브 부품(설치 파일)", "M15 네이티브 부품(brand-new)"])
        self.assertIn("B 기록 가져오기 14개", lines[2])

    def test_the_sizes_line_is_not_cut_in_the_middle_but_an_ordinary_long_brief_is(self):
        steps = ",".join("step%d %ds" % (number, number * 11) for number in range(1, 15))
        results = [rec("M20", "-", "info", brief="실제 묶음 95.8 MB zip 39.0 MB, 단계 시간 " + steps), rec("M05", "A", "pass", brief="x" * 300, target="tiny")]
        sizes = run.measurement_lines(results, "M20")[0]
        self.assertIn("step14 154s", sizes)                                                    # 1차 측정은 '단계 시간 install-tools 28.4s,build-bundles 73…' 에서 잘렸다
        self.assertFalse(sizes.endswith("…"))
        ordinary = run.measurement_lines(results, "M05")[0]
        self.assertTrue(ordinary.endswith("…"))
        self.assertLessEqual(len(ordinary), len("M05 무음 설치 | A 통과 ") + run.CELL_LIMIT)

    def test_no_line_of_the_block_is_longer_than_the_limit_even_for_absurd_briefs(self):
        results = passing_results() + [rec("M%02d" % number, arm, "info", brief="가" * 5000, target="tiny") for number in range(1, 23) for arm in "ABC"] + [rec("M20", "-", "info", brief="나" * 9000)]
        lines, _md, _data = self.block(results=results)
        self.assertTrue(lines)
        for line in lines:
            self.assertLessEqual(len(line), run.LINE_LIMIT, line[:40])
        self.assertEqual((lines[0], lines[-1]), (run.RESULT_HEADER, run.RESULT_FOOTER))

    def test_a_gate_that_passed_only_because_the_standard_user_check_was_handed_over_says_so(self):
        items = [item for item in passing_results() if not (item["id"] == "M18" and item["arm"] in "AB")] + [rec("M18", "A", "unavailable", brief="시도 불가"), rec("M18", "B", "unavailable", brief="시도 불가")]
        gates = run.judge(items)
        for arm in "AB":
            self.assertEqual(gates[arm]["G1"]["status"], "pass")
            self.assertIn("운영자 실기", gates[arm]["G1"]["open"])
        self.assertNotIn("open", gates["C"]["G1"])                                               # 표준 사용자 시험이 통과인 갈래에는 단서가 없다
        lines, _md, data = self.block(results=items)
        g1 = next(line for line in lines if line.startswith("G1 "))
        self.assertIn("A 통과(표준 사용자는 운영자 실기)", g1)
        self.assertIn("B 통과(표준 사용자는 운영자 실기)", g1)
        self.assertIn("C 통과 ", g1 + " ")
        self.assertNotIn("(", g1.split("C 통과")[-1])
        self.assertIn("open", data["gates"]["A"]["G1"])

    def test_a_failed_or_unknown_gate_gets_no_hand_over_note(self):
        items = [item for item in passing_results() if not (item["id"] == "M18" and item["arm"] == "A")] + [rec("M18", "A", "fail", brief="설치 도구가 관리자 권한을 요구했다")]
        self.assertEqual(run.judge(items)["A"]["G1"]["status"], "fail")
        self.assertNotIn("open", run.judge(items)["A"]["G1"])
        for arm in "ABC":
            self.assertNotIn("open", run.judge([])[arm]["G1"])

    def test_one_line_that_cannot_be_made_does_not_take_the_whole_box_with_it(self):
        """첫 실행에서 최대한 많은 값을 얻는 도구의 원칙 — 한 줄을 못 만들어도 나머지 줄과 관문은 나온다(상자를 못 만들면 그 실행은 통째로 헛것이 된다)."""
        original = run.measurement_lines

        def broken(results, mid):
            if mid == "M05":
                raise KeyError("boom")
            return original(results, mid)

        with mock.patch.object(run, "measurement_lines", broken):
            lines, md, data = self.block()
        self.assertEqual(next(item for item in lines if item.startswith("M05 ")), "M05 무음 설치 | 줄을 만들지 못했다(KeyError)")
        for number in (4, 6, 22):
            self.assertTrue(any(item.startswith("M%02d " % number) for item in lines), number)
        self.assertTrue(any(item.startswith("G8 ") for item in lines))
        self.assertEqual((lines[0], lines[-1]), (run.RESULT_HEADER, run.RESULT_FOOTER))
        self.assertIn("줄을 만들지 못했다(KeyError)", data["block"])
        self.assertIn(data["block"], md)

    def test_a_header_that_cannot_be_made_says_so_and_the_box_goes_on(self):
        with mock.patch.object(run, "header_line", side_effect=ValueError("boom")):
            lines, _md, _data = self.block()
        self.assertEqual(lines[1], "러너: 머리 줄을 만들지 못했다(ValueError)")
        self.assertTrue(lines[2].startswith("단계: "))
        self.assertTrue(any(item.startswith("G1 ") for item in lines))
        self.assertEqual(lines[-1], run.RESULT_FOOTER)

    def test_the_eighth_gate_no_longer_names_a_count_of_twelve(self):
        self.assertEqual(dict(run.GATES)["G8"], "설치본 selftest 앱 점검 전부")
        lines, _md, _data = self.block()
        self.assertNotIn("열두", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
