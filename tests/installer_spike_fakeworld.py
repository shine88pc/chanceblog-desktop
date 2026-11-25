"""설치 도구 시험(spike) 흐름 시험용 가짜 바깥 세계(시험 도우미 — 시험이 아니다, 결정 D-706).

`measure.Host` 를 바꿔 끼워 vpk·ISCC·dotnet·pip·PyInstaller·Velopack Setup·Update.exe·Inno Setup·제거 프로그램·작은 앱·tasklist·reg·cmdkey·netsh 의 동작을 **아주 단순하게** 흉내 낸다.
파일 시스템은 진짜(임시 폴더)이고 프로그램 실행만 가짜다 — 그래서 단계 실행기와 측정 흐름의 순서·분기·기록을 설치 도구 없이 끝까지 돌려 볼 수 있다. 이 흉내가 진짜 도구와 같다는 보장은 없다
(진짜 동작은 병합 뒤 운영자의 수동 실행이 알려 준다) — 시험이 지키는 것은 흐름이 어긋나지 않고 기록이 쓰이며 실패가 갇히는지이다.
스위치(속성)로 실패를 만든다: dotnet_fail·delta_ok·sdk_needs_skip·iscc_version·build_fail·mixed_on_running·hook_rc·autostart·keep_shortcut·std_user_ok 등.
"""
import itertools
import json
import re
import shutil
import zipfile
from pathlib import Path

import installer_spike_support as support

measure = support.load("measure")
SELFTEST_NAMES = ("utf8_mode", "version_file", "package_info", "file_hashes", "licenses", "vendor_core", "capabilities", "uac_manifest", "qt_plugins", "qt_screens", "gui_only_entry", "data_dir_untouched")
REAL_VERSION = (support.ROOT / "VERSION").read_text(encoding="utf-8").strip()          # 진짜 저장소 VERSION — run_spike.build_real 이 읽는 값과 같다


def copy_tree(source, target):
    target.mkdir(parents=True, exist_ok=True)
    for item in Path(source).rglob("*"):
        relative = item.relative_to(source)
        if item.is_dir():
            (target / relative).mkdir(parents=True, exist_ok=True)
        else:
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target / relative)


def arg_after(args, flag):
    return args[args.index(flag) + 1] if flag in args else None


class FakeProc:
    def __init__(self, world, args, cwd):
        self.world, self.args, self.cwd = world, [str(item) for item in args], cwd
        self.pid = next(world.pids)
        self.alive = True
        self.returncode = None

    def poll(self):
        return None if self.alive else (self.returncode or 0)

    def kill(self):
        self.alive = False
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakeWorld(measure.Host):
    def __init__(self, tmp, **switches):
        tmp = Path(tmp)
        environ = {"ImageOS": "win25", "ImageVersion": "20261116.335.1", "GITHUB_SHA": "0123456789abcdef", "USERNAME": "runneradmin", "RUNNER_TEMP": str(tmp / "temp"),
                   "GITHUB_ACTIONS": "true", "RUNNER_OS": "Windows", "APPDATA": str(tmp / "appdata"), "LOCALAPPDATA": str(tmp / "local"), "USERPROFILE": str(tmp / "profile"), "PUBLIC": str(tmp / "public"), "SPIKE_USERS_DIR": str(tmp / "users"),
                   "PATH": ""}
        super().__init__(environ)
        self.tmp = tmp
        self.clock = 0.0
        self.pids = itertools.count(1000)
        self.calls = []
        self.file_checks = []
        self.net_calls = []
        self.running = []
        self.setups, self.packages, self.feeds, self.installs = {}, {}, {}, {}
        self.tokens = itertools.count(1)
        self.keys, self.credentials, self.rules, self.rules_added = set(), set(), {}, 0
        # 스위치
        self.dotnet_fail = False
        self.delta_ok = True
        self.sdk_needs_skip = False
        self.iscc_version = "6.7.1.0"
        self.iscc_missing = False
        self.build_fail = False
        self.pyinstaller_fail = False
        self.mixed_on_running = False
        self.hook_rc = 0
        self.autostart = False
        self.keep_shortcut = False
        self.delete_data_on_uninstall = False
        self.std_user_ok = False
        self.net_user_ok = True
        self.firewall_effective = True
        self.selftest_fail = set()
        self.defender_status = "clean"
        self.fail_calls = set()
        self.raise_on = None
        self.hold_apps_closed_by_inno = True
        self.__dict__.update(switches)
        for key in ("appdata", "local", "profile", "public", "users", "temp"):
            (tmp / key).mkdir(parents=True, exist_ok=True)

    # ---- 시계 ---------------------------------------------------------------------------------------------------------------------------
    def now(self):
        return self.clock

    def wall(self):
        return 1_000_000.0 + self.clock

    def sleep(self, seconds):
        self.clock += seconds

    def which(self, name):
        if name.lower() == "iscc.exe" and not self.iscc_missing:
            path = self.tmp / "inno" / "ISCC.exe"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"MZ-fake-iscc")
            (path.parent / "Languages").mkdir(exist_ok=True)
            (path.parent / "Languages" / "Korean.isl").write_text("x", encoding="utf-8")
            return str(path)
        return None

    def is_file(self, path):
        """정해진 자리 찾기도 가짜 세계 안에서만 — 이 PC·러너에 실제로 깔린 도구(윈도 러너 이미지의 Inno Setup)가 흐름에 끼어들지 않게 늘 '없다'고 답한다(도구가 있는 경우는 which 가 돌려준다)."""
        self.file_checks.append(str(path))
        return False

    # ---- 실행 ---------------------------------------------------------------------------------------------------------------------------
    def run(self, args, *, timeout=120, env=None, cwd=None, drop_env=()):
        args = [str(item) for item in args]
        self.calls.append(args)
        self.clock += 0.5
        if self.raise_on and self.raise_on(args):
            raise RuntimeError("가짜 세계가 일부러 터뜨렸다")
        key = Path(args[0]).name.lower()
        if key.startswith("python") or key == "py.exe":
            key = "python.exe"
        if any(tag in " ".join(args) for tag in self.fail_calls):
            return measure.HostResult(1, 0.5, "", "forced failure")
        info = self.setup_info(args[0])
        if info:
            return self.run_setup(args, info)
        handler = getattr(self, "do_" + key.replace(".", "_").replace("-", "_"), None)
        if handler:
            return handler(args, env or {})
        if key in ("spikeapp.exe", "spikeappsdk.exe", "chanceblogdesktop.exe"):
            return self.run_app(args, env or {})
        return measure.HostResult(0, 0.5, "", "")

    def new_setup(self, path, info):
        """가짜 설치 파일을 쓴다 — 내용에 표지가 있어 이름을 바꿔 복사해도 같은 설치 파일로 알아본다."""
        token = "#SETUP-%d#" % next(self.tokens)
        manifest = b'<requestedExecutionLevel level="asInvoker" uiAccess="false"/>'
        Path(path).write_bytes(b"MZ" + token.encode("ascii") + manifest + b"s" * 200)
        self.setups[token] = info
        return token

    def setup_info(self, path):
        candidate = Path(path)
        if candidate.suffix.lower() != ".exe" or not candidate.is_file() or candidate.stat().st_size > 5000:
            return None
        found = re.search(rb"#SETUP-\d+#", candidate.read_bytes())
        return self.setups.get(found.group(0).decode("ascii")) if found else None

    def ok(self, out="", err=""):
        return measure.HostResult(0, 0.5, out, err)

    def start(self, args, *, env=None, cwd=None):
        proc = FakeProc(self, args, cwd)
        self.running.append(proc)
        return proc

    def kill(self, process):
        if process is not None:
            process.kill()

    def watch(self, args, *, seconds, env=None, cwd=None, peek_after=1.5):
        if Path(str(args[0])).name.lower() == "chanceblogdesktop.exe":
            return {"rc": None, "seconds": float(seconds), "timed_out": True, "windows": ["#32770"]}
        return {"rc": self.hook_rc, "seconds": 0.4, "timed_out": False, "windows": []}

    def defender_scan(self, paths, *, timeout=240):
        return {"status": self.defender_status, "reason": "가짜 검사", "exit_codes": [0], "seconds": 3.0, "engine_version": "1.1", "signature_version": "1.2", "targets": [Path(p).name for p in paths]}

    def reachable(self, host="github.com", port=443, timeout=8):
        return not (self.firewall_effective and any("python" in key for key in self.rules))

    # ---- 윈도 도구들 -------------------------------------------------------------------------------------------------------------------
    def do_tasklist(self, args, env):
        return self.ok("".join('"%s","%d","Console","1","1 K"\n' % (Path(proc.args[0]).name, proc.pid) for proc in self.running if proc.alive))

    def do_reg(self, args, env):
        return self.ok("".join("HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\%s\n" % key for key in sorted(self.keys)))

    def do_cmdkey(self, args, env):
        flag = args[1]
        if flag.startswith("/generic:"):
            self.credentials.add(flag.split(":", 1)[1])
            return self.ok("saved")
        if flag.startswith("/list:"):
            target = flag.split(":", 1)[1]
            return self.ok("Target: %s" % target if target in self.credentials else "none")
        if flag.startswith("/delete:"):
            self.credentials.discard(flag.split(":", 1)[1])
        return self.ok()

    def do_netsh(self, args, env):
        if "add" in args:
            name, program = next(item[5:] for item in args if item.startswith("name=")), next(item[8:] for item in args if item.startswith("program="))
            self.rules[program.lower()] = name
            self.rules_added += 1
        elif "delete" in args:
            name = next(item[5:] for item in args if item.startswith("name="))
            for program in [key for key, value in self.rules.items() if value == name]:
                del self.rules[program]
        return self.ok()

    def do_taskkill(self, args, env):
        for proc in self.running:
            if "/IM" in args and Path(proc.args[0]).name.lower() == args[args.index("/IM") + 1].lower() or "/PID" in args and str(proc.pid) == args[args.index("/PID") + 1]:
                proc.kill()
        return self.ok()

    def do_net(self, args, env):
        """`net user 이름 비밀번호 /add` — 인자를 기록한다. 실패하면 비밀번호를 되울리는 오류 글을 낸다(어떤 도구가 명령줄을 되울려도 기록에서 가려지는지 보려고)."""
        self.net_calls.append(list(args))
        if self.net_user_ok:
            return measure.HostResult(0, 0.5, "The command completed successfully.", "")
        return measure.HostResult(2, 0.5, "", "error: the password " + (args[3] if len(args) > 3 else "") + " does not meet the requirements")

    def do_icacls_exe(self, args, env):
        return self.ok()

    def do_powershell(self, args, env):
        script = args[-1]
        if "Get-MpComputerStatus" in script:
            return self.ok('{"AMServiceEnabled":true,"AntivirusEnabled":true,"RealTimeProtectionEnabled":true}')
        if "FileVersion" in script:
            return self.ok(self.iscc_version + "\n")
        if "Get-AuthenticodeSignature" in script:
            return self.ok("CN=Fake Signer B.V., O=Fake\n")
        if "PSCredential" in script:
            if self.std_user_ok:
                root = Path(env["SPIKE_USERS_DIR"] if "SPIKE_USERS_DIR" in env else self.environ["SPIKE_USERS_DIR"]) / measure.STD_USER / "AppData" / "Local" / "Fake"
                root.mkdir(parents=True, exist_ok=True)
                (root / "VERSION").write_text("0.0.1\n", encoding="utf-8")
                return self.ok()
            return measure.HostResult(1, 0.5, "", "access denied for " + (env or {}).get("SPIKE_PW", ""))
        return self.ok()

    def do_dotnet(self, args, env):
        if args[1:2] == ["--version"]:
            return self.ok("8.0.404\n")
        if self.dotnet_fail:
            return measure.HostResult(1, 0.5, "", "error NU1101: Unable to find package vpk")
        target = Path(arg_after(args, "--tool-path"))
        target.mkdir(parents=True, exist_ok=True)
        (target / "vpk.exe").write_bytes(b"MZ-fake-vpk")
        return self.ok("tool installed")

    def do_vpk_exe(self, args, env):
        if args[1:2] == ["--version"]:
            return self.ok("1.2.161+abcdef\n")
        if args[1:2] == ["--help"] or args[1:3] == ["pack", "--help"]:
            return self.ok("usage: vpk pack --delta <BestSize|BestSpeed|None>\n")
        if args[1] != "pack":
            return self.ok()
        if not self.delta_ok and "--delta" in args:
            return measure.HostResult(1, 0.5, "", "Invalid value for --delta")
        if self.sdk_needs_skip and "--skipVeloAppCheck" not in args and arg_after(args, "--mainExe") == "SpikeAppSdk.exe":
            return measure.HostResult(1, 0.5, "", "mainExe check failed")
        out, pack_id, version = Path(arg_after(args, "--outputDir")), arg_after(args, "--packId"), arg_after(args, "--packVersion")
        pack_dir, exe = Path(arg_after(args, "--packDir")), arg_after(args, "--mainExe")
        out.mkdir(parents=True, exist_ok=True)
        setup, full = out / ("%s-stable-Setup.exe" % pack_id), out / ("%s-%s-full.nupkg" % (pack_id, version))
        full.write_bytes(b"PK" + b"p" * 300)
        (out / "releases.stable.json").write_text("{}", encoding="utf-8")
        self.new_setup(setup, {"kind": "velopack", "bundle": pack_dir, "exe": exe, "id": pack_id, "version": version})
        self.packages[str(full)] = pack_dir
        self.feeds[str(out)] = pack_dir
        return self.ok("packed")

    def do_iscc_exe(self, args, env):
        defines = {item[2:].split("=", 1)[0]: item[2:].split("=", 1)[1] for item in args if item.startswith("/D")}
        out = Path(next(item[2:] for item in args if item.startswith("/O")))
        base = next(item[2:] for item in args if item.startswith("/F"))
        out.mkdir(parents=True, exist_ok=True)
        setup = out / (base + ".exe")
        self.new_setup(setup, {"kind": "inno", "bundle": Path(defines["SourceDir"]), "exe": defines["AppExe"], "id": defines["AppIdText"], "version": defines["AppVersion"], "dir_name": defines["AppDirName"]})
        return self.ok("compiled")

    def do_python_exe(self, args, env):
        joined = " ".join(args)
        if len(args) > 2 and args[1] == "-m" and args[2] == "pip" and args[3] == "download":
            requirement = Path(arg_after(args, "-r")).read_text(encoding="utf-8").split("==")
            folder = Path(arg_after(args, "-d"))
            folder.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(folder / ("%s-%s-cp38-abi3-win_amd64.whl" % (requirement[0], requirement[1].split()[0])), "w") as wheel:
                wheel.writestr("velopack/__init__.py", "x = 1\n")
                wheel.writestr("velopack/_native.pyd", support.build_pe(["kernel32.dll", "ws2_32.dll"]))
            return self.ok("downloaded")
        if args[1:3] == ["-m", "venv"]:
            python = Path(args[3]) / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_bytes(b"MZ-fake-python")
            return self.ok()
        if args[1:3] == ["-m", "PyInstaller"]:
            if self.pyinstaller_fail:
                return measure.HostResult(1, 0.5, "", "PyInstaller failed")
            dist, name = Path(arg_after(args, "--distpath")), arg_after(args, "--name")
            (dist / name / "_internal").mkdir(parents=True, exist_ok=True)
            (dist / name / (name + ".exe")).write_bytes(b"MZ-fake-app-" + name.encode())
            (dist / name / "_internal" / "base.dll").write_bytes(b"MZ-dll")
            return self.ok("built")
        if len(args) > 1 and args[1].endswith("build_package.py"):
            if self.build_fail:
                return measure.HostResult(1, 0.5, "", "묶음 점검 실패")
            out = Path(arg_after(args, "--out-dir"))
            bundle = out / "bundle" / ("ChanceBlogDesktop-" + REAL_VERSION)
            (bundle / "_internal").mkdir(parents=True, exist_ok=True)
            (bundle / "ChanceBlogDesktop.exe").write_bytes(b"MZ-fake-real")
            (bundle / "VERSION").write_text(REAL_VERSION + "\n", encoding="utf-8")
            (bundle / "PACKAGE_INFO.json").write_text(json.dumps({"schema": 1}), encoding="utf-8")
            (out / "release").mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(out / "release" / ("ChanceBlogDesktop-%s-win64.zip" % REAL_VERSION), "w") as archive:
                for item in bundle.rglob("*"):
                    if item.is_file():
                        archive.write(item, "ChanceBlogDesktop-%s/%s" % (REAL_VERSION, item.relative_to(bundle).as_posix()))
            return self.ok("built")
        if "-c" in args:
            return self.ok("fake path")
        return self.ok()

    do_python3_exe = do_python_exe

    # ---- 설치 파일·제거·앱 ---------------------------------------------------------------------------------------------------------------
    def shortcut_path(self, name):
        return Path(self.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / (name + ".lnk")

    def run_setup(self, args, info):
        if info["kind"] == "velopack":
            root = Path(arg_after(args, "--installto") or (Path(self.environ["LOCALAPPDATA"]) / info["id"]))
            current = root / "current"
            if current.exists() and not "--installto" in args:
                shutil.rmtree(current)
            copy_tree(info["bundle"], current)
            (root / "Update.exe").write_bytes(b"MZ-fake-update")
            (root / "packages").mkdir(exist_ok=True)
            (root / info["exe"]).write_bytes(b"MZ-stub")
            link = self.shortcut_path(info["id"])
            key = info["id"]
        else:
            root = Path(next(item[5:] for item in args if item.startswith("/DIR=")))
            if root.exists():
                running = [proc for proc in self.running if proc.alive and str(root) in str(proc.args[0])]
                if running and not self.hold_apps_closed_by_inno:
                    return measure.HostResult(5, 0.5, "", "app in use")
                for proc in running:
                    proc.kill()
                for item in list(root.iterdir()):
                    shutil.rmtree(item) if item.is_dir() else item.unlink()
            copy_tree(info["bundle"], root)
            (root / "unins000.exe").write_bytes(b"MZ-fake-uninstall")
            link = self.shortcut_path("ChanceBlog Spike C")
            key = info["id"] + "_is1"
            log = next((item[5:] for item in args if item.startswith("/LOG=")), None)
            if log:
                Path(log).write_text("Setup log\nSPIKE_LANG=%s\nSPIKE_NEXT=다음(&N) >\n" % ("korean" if "/LANG=korean" in args else "english"), encoding="utf-8")
        link.parent.mkdir(parents=True, exist_ok=True)
        link.write_bytes(b"lnk")
        self.keys.add(key)
        self.installs[str(root).lower()] = {"kind": info["kind"], "link": link, "key": key, "exe": info["exe"]}
        if self.autostart:
            self.running.append(FakeProc(self, [str(root / info["exe"])], root))
        return self.ok("installed")

    def replace_current(self, root, bundle, *, partial=False):
        current = Path(root) / "current"
        if partial:
            files = sorted(path for path in Path(bundle).rglob("*") if path.is_file())
            for path in files[: len(files) // 2]:
                target = current / path.relative_to(bundle)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            return
        shutil.rmtree(current, ignore_errors=True)
        copy_tree(bundle, current)

    def do_update_exe(self, args, env):
        root = Path(args[0]).parent
        running = [proc for proc in self.running if proc.alive and str(root / "current") in str(proc.args[0])]
        if "apply" in args:
            package = arg_after(args, "--package")
            if package not in self.packages:
                return measure.HostResult(1, 0.5, "", "package not found")
            self.replace_current(root, self.packages[package], partial=bool(running) and self.mixed_on_running)
            return self.ok("applied")
        if "uninstall" in args:
            return self.uninstall(root)
        return self.ok("help")

    def do_unins000_exe(self, args, env):
        return self.uninstall(Path(args[0]).parent)

    def uninstall(self, root):
        info = self.installs.pop(str(root).lower(), None)
        for proc in self.running:
            if str(root) in str(proc.args[0]):
                proc.kill()
        shutil.rmtree(root, ignore_errors=True)
        if info:
            if not self.keep_shortcut:
                info["link"].unlink(missing_ok=True)
            self.keys.discard(info["key"])
        if self.delete_data_on_uninstall:
            shutil.rmtree(self.tmp / "work" / "data", ignore_errors=True)
        return self.ok("uninstalled")

    def run_app(self, args, env):
        exe = Path(args[0])
        if "--selftest" in args:
            lines = ["[%s] %s: ok" % ("실패" if name in self.selftest_fail else "통과", name) for name in SELFTEST_NAMES]
            return measure.HostResult(1 if self.selftest_fail else 0, 0.5, "\n".join(lines) + "\n", "")
        if (exe.parent / "BROKEN").exists():
            return measure.HostResult(3, 0.2, "", "")
        if "--update-from" in args:
            feed = arg_after(args, "--update-from")
            if feed not in self.feeds:
                return measure.HostResult(4, 0.5, "", "")
            running = [proc for proc in self.running if proc.alive and str(exe.parent) in str(proc.args[0])]
            self.replace_current(exe.parent.parent, self.feeds[feed], partial=bool(running) and self.mixed_on_running)
            return self.ok()
        return self.ok()
