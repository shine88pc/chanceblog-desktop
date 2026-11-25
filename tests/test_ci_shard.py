"""CI 시험 조각 나누기(`scripts/ci_shard.py`, D-220) 시험 — 조각 나누기가 시험 파일을 빠뜨리거나 겹치지 않고, 같은 입력에 같은 결과를 내고, 실패를 삼키지 않고,
`ci.yml` 의 조각 수와 맞는다는 것을 지킨다. 이것이 깨지면 CI 가 일부 시험을 안 돌리고도 초록이 될 수 있다.

지키는 것:
  1) 시험 파일 전부(100개가 넘는다)가 조각 1~6개 어느 쪽으로 나눠도 정확히 한 조각에만 들어가고, 조각이 비지 않는다. 입력 순서와 상관없이 같은 결과다.
  2) 무게로 나눈 조각들의 차이가 가장 무거운 파일 하나를 넘지 않는다. 가장 무거운 세 파일은 세 조각에 하나씩 들어간다. 표에 없는 새 파일도 조각에 들어간다. 표에는 없어진 파일 이름이 없다.
  3) 잘못된 인자(0번·범위 밖·정수 아님·모르는 옵션 …)는 종료 코드 2, 비어 있는 조각은 1 — 아무것도 안 돌고 초록이 되지 않는다.
  4) 작은 가짜 시험 폴더로 실제 실행: 조각마다 자기 파일만 돌고, 실패하는 파일과 불러오기에 실패하는 파일이 그 조각을 빨갛게 만든다.
  5) `ci.yml` 의 조각 목록(`shard: [1, 2, 3]`)과 `CI_SHARD_TOTAL` 이 같고, `run:` 안에 `${{ }}` 가 없고, `fail-fast: false` 가 그대로다.
     (D-713) 둘째 잡 `qt` 가 생긴 뒤로는 이것을 `test`·`qt` 잡마다 본다(조각 목록·총수·이름 둘·`run:` 줄의 정확한 목록·`fail-fast`·`qt` 는 윈도와 3.12 하나뿐).
  6) (D-712) Qt 칸의 건너뜀 가드 `CI_REQUIRE_QT`: 1 만 켬(0·없음은 끔, 그 밖은 종료 코드 2)·PySide6 를 못 찾으면 시험 전에 종료 코드 3·PySide6 이유로 건너뛴 시험이 하나라도 있으면 종료 코드 1(대소문자 무시,
     `setUpClass`·파일 불러오기 건너뜀 포함)·다른 이유의 건너뜀은 알림만·시험 파일별 걸린 시간 표와 오래 걸린 파일의 즉시 알림, 그리고 Qt 깃발(`HAVE`)로 건너뛰는 모든 시험이 이유에 PySide6 낱말을 쓰는지 정적 확인.
"""
import ast
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci_shard.py"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_shard  # noqa: E402
import workflow_golden as golden  # noqa: E402  (ci.yml·package.yml 을 구조로 읽는 허용 목록 규칙 — AS-S2 권고-7, D-693)


def real_names():
    return sorted(path.stem for path in (ROOT / "tests").glob("test*.py"))


def run_script(*args, env_extra=None):
    env = dict(os.environ, PYTHONUTF8="1")
    env.pop("CI_SHARD", None)
    env.pop("CI_SHARD_TOTAL", None)
    env.pop("CI_REQUIRE_QT", None)                          # Qt 칸(D-713)의 환경 변수가 이 시험의 자식 프로세스에 새어 들어가 가짜 시험 폴더에서 가드가 켜지는 일이 없게
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT), timeout=300)


class AssignTest(unittest.TestCase):
    def test_every_test_file_goes_to_exactly_one_shard_for_one_to_six_shards(self):
        names = real_names()
        self.assertGreater(len(names), 100)
        for total in range(1, 7):
            table = ci_shard.assign(names, total)
            self.assertEqual(sorted(table), names, f"{total}조각")
            self.assertTrue(all(1 <= index <= total for index in table.values()), f"{total}조각")
            for index in range(1, total + 1):
                self.assertTrue([name for name in names if table[name] == index], f"{total}조각 중 {index}번이 비었다")

    def test_the_split_is_deterministic_and_ignores_the_input_order(self):
        names = real_names()
        for total in (2, 3, 4):
            first = ci_shard.assign(names, total)
            self.assertEqual(first, ci_shard.assign(list(reversed(names)), total))
            self.assertEqual(first, ci_shard.assign(names, total))

    def test_shards_are_balanced_by_weight_within_the_heaviest_single_file(self):
        names = real_names()
        heaviest = max(ci_shard.weight_of(name) for name in names)
        for total in (2, 3, 4, 5):
            table = ci_shard.assign(names, total)
            loads = [sum(ci_shard.weight_of(name) for name in names if table[name] == index) for index in range(1, total + 1)]
            self.assertLessEqual(max(loads) - min(loads), heaviest, f"{total}조각 무게 {loads}")

    def test_the_three_heaviest_files_land_in_three_different_shards(self):
        names = real_names()
        table = ci_shard.assign(names, 3)
        heaviest = sorted(names, key=lambda name: (-ci_shard.weight_of(name), name))[:3]
        self.assertEqual(sorted(table[name] for name in heaviest), [1, 2, 3], heaviest)

    def test_a_new_file_missing_from_the_weight_table_still_gets_a_shard(self):
        names = real_names() + ["test_a_brand_new_module"]
        table = ci_shard.assign(names, 3)
        self.assertIn(table["test_a_brand_new_module"], (1, 2, 3))
        self.assertEqual(ci_shard.weight_of("test_a_brand_new_module"), ci_shard.DEFAULT_WEIGHT)

    def test_the_weight_table_names_only_files_that_exist(self):
        names = set(real_names())
        stale = [name for name in ci_shard.WEIGHTS if name not in names]
        self.assertEqual(stale, [], "없어졌거나 이름이 바뀐 시험 파일이 무게표에 남아 있다")
        self.assertTrue(all(isinstance(value, int) and value > ci_shard.DEFAULT_WEIGHT for value in ci_shard.WEIGHTS.values()))


    def test_the_known_heavy_files_spread_over_the_shards_by_name(self):
        # 독립 검증 M04·M14: 무게를 자기 함수로만 견주면 무게가 사라져도 통과한다 — 이름으로 못박는다.
        names = real_names()
        heavy = ["test_pages_publish", "test_service_recovery", "test_service_repolock"]
        for name in heavy:
            self.assertIn(name, names)
        self.assertEqual(sorted(ci_shard.assign(names, 3)[name] for name in heavy), [1, 2, 3])
        two = ci_shard.assign(names, 2)
        self.assertNotEqual(two["test_pages_publish"], two["test_service_recovery"])
        self.assertGreaterEqual(ci_shard.WEIGHTS["test_pages_publish"], 500)


class ParseTest(unittest.TestCase):
    def test_arguments_environment_and_the_default_of_one_shard(self):
        self.assertEqual(ci_shard.parse(["2", "3"], {}), (2, 3, {}))
        self.assertEqual(ci_shard.parse([], {"CI_SHARD": "2", "CI_SHARD_TOTAL": "3"}), (2, 3, {}))
        self.assertEqual(ci_shard.parse([], {}), (1, 1, {}))
        self.assertEqual(ci_shard.parse(["1", "3", "--list"], {})[2], {"--list": True})
        self.assertEqual(ci_shard.parse(["1", "3", "--tests-dir=abc"], {})[2], {"--tests-dir": "abc"})

    def test_bad_input_is_rejected(self):
        bad = [(["0", "3"], {}), (["4", "3"], {}), (["a", "3"], {}), (["1"], {}), (["1", "2", "3"], {}), (["1", "100"], {}), (["1", "0"], {}),
               (["--bogus"], {}), (["1", "3", "--list=1"], {}), (["1", "3", "--tests-dir"], {}), (["1", "3", "--tests-dir="], {}),
               ([], {"CI_SHARD": "1"}), ([], {"CI_SHARD_TOTAL": "3"}), ([], {"CI_SHARD": "x", "CI_SHARD_TOTAL": "3"})]
        for argv, env in bad:
            with self.assertRaises(ValueError, msg=repr((argv, env))):
                ci_shard.parse(argv, env)


class RunTest(unittest.TestCase):
    """작은 가짜 시험 폴더(통과 a·실패 b·불러오기 실패 c)로 실제 실행한다."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        (folder / "test_a.py").write_text(textwrap.dedent('''
            import unittest
            class A(unittest.TestCase):
                def test_ok(self):
                    self.assertTrue(True)
        '''), encoding="utf-8")
        (folder / "test_b.py").write_text(textwrap.dedent('''
            import unittest
            class B(unittest.TestCase):
                def test_bad(self):
                    self.fail("일부러 실패")
        '''), encoding="utf-8")
        (folder / "test_c.py").write_text("import a_module_that_does_not_exist_for_this_test\n", encoding="utf-8")
        self.folder = folder

    def shard(self, index, total):
        return run_script(str(index), str(total), f"--tests-dir={self.folder}")

    def test_every_shard_runs_only_its_own_files_and_failures_are_not_swallowed(self):
        results = {index: self.shard(index, 3) for index in (1, 2, 3)}
        self.assertEqual(results[1].returncode, 0, results[1].stderr[-600:])
        self.assertIn("test_ok", results[1].stderr)
        self.assertNotIn("test_bad", results[1].stderr)
        self.assertEqual(results[2].returncode, 1)
        self.assertIn("일부러 실패", results[2].stderr)
        self.assertNotIn("test_ok", results[2].stderr)
        self.assertEqual(results[3].returncode, 1, "불러오기에 실패한 파일이 조각을 빨갛게 만들지 않았다")
        self.assertIn("a_module_that_does_not_exist_for_this_test", results[3].stderr)

    def test_the_lists_of_all_shards_together_are_exactly_the_files(self):
        listed = []
        for index in (1, 2, 3):
            done = run_script(str(index), "3", "--list", f"--tests-dir={self.folder}")
            self.assertEqual(done.returncode, 0, done.stderr)
            listed += done.stdout.split()
        self.assertEqual(sorted(listed), ["test_a", "test_b", "test_c"])

    def test_one_shard_runs_everything_like_discover_does(self):
        done = run_script("1", "1", f"--tests-dir={self.folder}")
        self.assertEqual(done.returncode, 1)
        for needle in ("test_ok", "일부러 실패", "a_module_that_does_not_exist_for_this_test"):
            self.assertIn(needle, done.stderr)

    def test_an_empty_shard_fails_instead_of_passing_without_running_anything(self):
        done = self.shard(4, 4)
        self.assertEqual(done.returncode, 1)
        self.assertIn("조각 수를 줄여라", done.stderr)

    def test_bad_arguments_exit_with_two_and_run_nothing(self):
        for args in (("0", "3"), ("4", "3"), ("x", "3"), ("1",), ("--bogus",)):
            done = run_script(*args, f"--tests-dir={self.folder}")
            self.assertEqual(done.returncode, 2, args)
            self.assertNotIn("Ran ", done.stderr, args)

    def test_the_environment_variables_work_like_the_arguments(self):
        done = run_script("--list", f"--tests-dir={self.folder}", env_extra={"CI_SHARD": "1", "CI_SHARD_TOTAL": "3"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.split(), ["test_a"])


class RealFolderTest(unittest.TestCase):
    def test_the_real_tests_folder_splits_into_three_shards_that_cover_every_file(self):
        # 독립 검증 L: 실제 시험 폴더를 실제 스크립트로 나눠 합집합이 시험 파일 전부인지 — CI 가 일부 시험을 안 돌리고 초록이 되는 일을 막는 마지막 안전망(약 10초).
        listed = []
        for index in (1, 2, 3):
            done = run_script(str(index), "3", "--list")
            self.assertEqual(done.returncode, 0, done.stderr[-300:])
            part = done.stdout.split()
            self.assertTrue(part, f"조각 {index} 이 비었다")
            listed += part
        self.assertEqual(len(listed), len(set(listed)), "조각 사이에 겹치는 시험 파일이 있다")
        self.assertEqual(sorted(listed), real_names())


def code_lines(text):
    """주석(줄 전체·줄 끝)을 뺀 코드 줄 — 주석에 원문을 남긴 채 값만 바꾸는 변경을 가리지 못하게."""
    lines = []
    for line in text.replace("\r\n", "\n").splitlines():
        stripped = re.sub(r"(^|\s)#.*$", "", line).rstrip()
        if stripped.strip():
            lines.append(stripped)
    return lines


def jobs_of(code):
    """주석을 뺀 코드 줄들을 `jobs:` 아래 잡마다 나눈다 → {잡 이름: [줄, ...]}(파일 순서, 들여쓰기 그대로). `ci.yml` 에 잡이 둘(`test`·`qt`)이라 '파일에서 하나' 를 찾던 시험들이 잡마다 보게 한다(D-713)."""
    jobs, current, inside = {}, None, False
    for line in code:
        if not line.startswith(" "):
            inside, current = line.strip() == "jobs:", None
            continue
        if not inside:
            continue
        header = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if header:
            current = header.group(1)
            jobs[current] = []
        elif current is not None:
            jobs[current].append(line)
    return jobs


class CiWorkflowShardTest(unittest.TestCase):
    # 잡마다 이름 접두어와 `run:` 줄의 정확한 목록 — `qt` 잡 이름은 기존 두 접두어(`시험 (`·`시험 실행(`)로 시작하지 않아 안 부딪힌다.
    NAME_PREFIXES = {"test": ("name: 시험 (", "- name: 시험 실행("), "qt": ("name: Qt 시험 (", "- name: Qt 시험 실행(")}
    RUNS = {"test": ["run: python scripts/ci_shard.py"], "qt": ["run: python scripts/ci_qt_setup.py", "run: python scripts/ci_shard.py"]}

    def setUp(self):
        self.ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.code = code_lines(self.ci)
        self.text = "\n".join(self.code)
        self.stripped = [line.strip() for line in self.code]
        raw_jobs = jobs_of(self.code)
        self.job_text = {name: "\n".join(lines) for name, lines in raw_jobs.items()}
        self.jobs = {name: [line.strip() for line in lines] for name, lines in raw_jobs.items()}
        self.assertEqual(sorted(self.jobs), ["qt", "test"], "ci.yml 의 잡은 test 와 qt 둘이다(D-713)")

    def total(self, job):
        found = re.search(r"^\s+CI_SHARD_TOTAL:\s*'(\d+)'$", self.job_text[job], re.M)
        self.assertIsNotNone(found, f"ci.yml 의 {job} 잡에 CI_SHARD_TOTAL 이 없다")
        return int(found.group(1))

    def test_the_matrix_shards_and_the_total_agree(self):
        for job in self.jobs:
            with self.subTest(job=job):
                found = re.search(r"^\s+shard:\s*\[([0-9, ]+)\]$", self.job_text[job], re.M)
                self.assertIsNotNone(found, f"ci.yml 의 {job} 잡 matrix 에 shard 목록이 없다")
                shards = [int(item) for item in found.group(1).replace(" ", "").split(",")]
                self.assertEqual(shards, list(range(1, self.total(job) + 1)), "shard 목록은 1..CI_SHARD_TOTAL 이어야 한다 — 어긋나면 일부 시험이 안 돈다")

    def test_the_shard_number_comes_from_the_matrix_in_a_real_code_line(self):
        # 독립 검증 Y07b: `CI_SHARD: '1'  # CI_SHARD: ${{ matrix.shard }}` 처럼 주석에 원문을 남기고 값을 고정하면 모든 작업이 1번 조각만 돌고도 초록이 된다.
        for job, lines in self.jobs.items():
            with self.subTest(job=job):
                self.assertIn("CI_SHARD: ${{ matrix.shard }}", lines)
                self.assertIn("PYTHONUTF8: '1'", lines)

    def test_the_job_and_step_names_show_the_same_total_as_the_environment(self):
        # 독립 검증 Y09: 이름의 '/3' 이 어긋나도 CI 는 도는 표시 문제지만 PR 화면에서 조각이 몇 개인지 잘못 읽게 된다.
        for job, prefixes in self.NAME_PREFIXES.items():
            with self.subTest(job=job):
                needle = "조각 ${{ matrix.shard }}/" + str(self.total(job))
                names = [line for line in self.jobs[job] if line.startswith(prefixes)]
                self.assertEqual(len(names), 2, names)
                for line in names:
                    self.assertIn(needle, line)

    def test_the_test_step_calls_the_shard_script_without_putting_expressions_in_run(self):
        for job, expected in self.RUNS.items():
            with self.subTest(job=job):
                self.assertEqual([line for line in self.jobs[job] if line.startswith("run:")], expected)
        runs = [line for line in self.stripped if line.startswith("run:")]
        self.assertEqual(runs, self.RUNS["test"] + self.RUNS["qt"], "파일 전체의 run 줄은 잡마다 정해 둔 것의 합이다")
        self.assertFalse([line for line in runs if "${{" in line])

    def test_nothing_can_exclude_skip_or_forgive_a_shard(self):
        # 독립 검증 Y11~Y13: matrix exclude(조각을 통째로 뺌)·continue-on-error(실패를 용서)·if(단계를 건너뜀)가 들어와도 CI 가 초록일 수 있다.
        for forbidden in ("exclude:", "include:", "continue-on-error", "if:"):
            self.assertEqual([line for line in self.code if forbidden in line], [], forbidden)
        for job, lines in self.jobs.items():
            with self.subTest(job=job):
                self.assertIn("fail-fast: false", lines)
        for needle in ("windows-latest", "ubuntu-latest", "'3.10'", "'3.12'"):
            self.assertIn(needle, self.text)
        self.assertIn("runs-on: windows-latest", self.jobs["qt"])
        self.assertIn("python-version: '3.12'", self.jobs["qt"])
        for needle in ("ubuntu-latest", "'3.10'", "matrix.os", "matrix.python"):
            self.assertNotIn(needle, self.job_text["qt"], f"qt 잡은 윈도·3.12 하나뿐이다: {needle}")


# ---------------------------------------------------------------------------------------------------------------------------------------------
# 정식 CI 의 Qt 칸(`ci.yml` 의 `qt` 잡, D-710–D-713): `CI_REQUIRE_QT=1` 이면 PySide6 가 없어 건너뛰어졌는데 초록이 되는 일이 없다 — 가드 시험.
# ---------------------------------------------------------------------------------------------------------------------------------------------
PASSING_MODULE = "import unittest\nclass P(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
FAILING_MODULE = "import unittest\nclass F(unittest.TestCase):\n    def test_bad(self):\n        self.fail('일부러 실패')\n"
SLOW_MODULE = "import time\nimport unittest\nclass W(unittest.TestCase):\n    def test_slow(self):\n        time.sleep(0.8)\n"


def skipping_module(reason, count=2):
    """클래스 전체를 `reason` 으로 건너뛰는 가짜 시험 파일(시험 `count` 개)."""
    methods = "".join(f"    def test_{index}(self):\n        pass\n" for index in range(count))
    return f"import unittest\n@unittest.skip({reason!r})\nclass S(unittest.TestCase):\n{methods}"


SET_UP_CLASS_SKIP = "import unittest\nclass S(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls):\n        raise unittest.SkipTest('PySide6 가 없다')\n    def test_a(self):\n        pass\n"
MODULE_SKIP = "import unittest\nraise unittest.SkipTest('PySide6 가 없다')\n"

DRIVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import ci_shard
    installed = sys.argv[2] == "yes"
    ci_shard.qt_installed = lambda: installed        # PySide6 가 깔렸는지를 환경과 상관없이 정한다 — 나머지(가드·러너)는 진짜 코드다
    sys.exit(ci_shard.main(sys.argv[3:]))
''')


def run_driver(installed, *args, flag=None):
    env = dict(os.environ, PYTHONUTF8="1")
    for name in ("CI_SHARD", "CI_SHARD_TOTAL", "CI_REQUIRE_QT"):
        env.pop(name, None)
    if flag is not None:
        env["CI_REQUIRE_QT"] = flag
    return subprocess.run([sys.executable, "-X", "utf8", "-c", DRIVER, str(ROOT / "scripts"), "yes" if installed else "no", *args],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT), timeout=300)


class QtFlagTest(unittest.TestCase):
    def test_only_one_turns_the_guard_on_and_zero_or_nothing_turns_it_off(self):
        self.assertIs(ci_shard.qt_required({"CI_REQUIRE_QT": "1"}), True)
        for off in ({}, {"CI_REQUIRE_QT": ""}, {"CI_REQUIRE_QT": "0"}):
            self.assertIs(ci_shard.qt_required(off), False, off)

    def test_any_other_value_is_refused_so_a_typo_cannot_switch_the_guard_off_silently(self):
        for value in ("true", "yes", "on", "2", " 1", "1 ", "01", "True", "ㅣ", "-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ci_shard.qt_required({"CI_REQUIRE_QT": value})

    def test_the_flag_name_and_the_word_are_the_documented_ones(self):
        self.assertEqual((ci_shard.QT_FLAG, ci_shard.QT_WORD), ("CI_REQUIRE_QT", "pyside6"))

    def test_qt_installed_asks_the_same_question_the_qt_test_files_ask(self):
        with mock.patch.object(ci_shard.importlib.util, "find_spec", return_value=None) as asked:
            self.assertIs(ci_shard.qt_installed(), False)
            asked.assert_called_once_with("PySide6")
        with mock.patch.object(ci_shard.importlib.util, "find_spec", return_value=object()):
            self.assertIs(ci_shard.qt_installed(), True)


class QtSkipReportTest(unittest.TestCase):
    """진짜 `unittest` 가 만든 `result.skipped` 로 — 시험 파일을 찾아 PySide6 이유와 그 밖의 이유를 가른다."""

    def skips(self):
        class Plain(unittest.TestCase):
            @unittest.skip("PySide6 가 설치되어 있지 않다")
            def test_a(self):
                pass

            @unittest.skip("git 이 필요하다")
            def test_b(self):
                pass

        class Shout(unittest.TestCase):
            @unittest.skip("PYSIDE6 NOT INSTALLED")
            def test_c(self):
                pass

            @unittest.skip("pyside6\n가 없다")
            def test_d(self):
                pass

        class SetUp(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise unittest.SkipTest("PySide6 가 없다")

            def test_e(self):
                pass

        suite = unittest.TestSuite([Plain("test_a"), Plain("test_b"), Shout("test_c"), Shout("test_d"), SetUp("test_e")])
        return unittest.TextTestRunner(stream=io.StringIO()).run(suite).skipped

    def test_pyside6_reasons_are_counted_per_file_in_any_case_and_other_reasons_are_grouped(self):
        qt, other = ci_shard.qt_skip_report(self.skips())
        self.assertEqual(qt, {__name__: 4}, "대문자·소문자·줄바꿈이 낀 이유·setUpClass 에서 건너뛴 것까지 모두 이 파일 것으로 센다")
        self.assertEqual(other, {"git 이 필요하다": 1})

    def test_a_class_level_skip_is_found_in_its_file_even_when_the_class_name_has_odd_characters(self):
        holders = [test for test, _reason in self.skips() if type(test).__name__ == "_ErrorHolder"]
        self.assertEqual(len(holders), 1, "setUpClass 에서 건너뛴 것은 시험 자리 표시(_ErrorHolder)로 온다")
        self.assertEqual(ci_shard.skipped_module(holders[0]), __name__)

    def test_a_skip_without_the_word_is_not_a_qt_skip(self):
        qt, other = ci_shard.qt_skip_report([(unittest.FunctionTestCase(lambda: None), "관리자(root)는 읽기 전용 파일도 쓸 수 있다")])
        self.assertEqual((qt, sum(other.values())), ({}, 1))

    def test_nothing_skipped_is_an_empty_report(self):
        self.assertEqual(ci_shard.qt_skip_report([]), ({}, {}))


class TimedResultTest(unittest.TestCase):
    """`timed` — 시험 파일마다 걸린 시간을 세고, 오래 걸린 파일은 끝나는 즉시 한 줄 알린다(첫 실행이 시간 한도에 잘려도 로그에 남게)."""

    def run_two_modules(self):
        class First(unittest.TestCase):
            def test_slow(self):
                time.sleep(0.05)

        class Second(unittest.TestCase):
            def test_fast(self):
                pass

        First.__module__, Second.__module__ = "fake_module_first", "fake_module_second"
        runner = unittest.TextTestRunner(stream=io.StringIO(), resultclass=ci_shard.timed(unittest.TextTestResult))
        started = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result = runner.run(unittest.TestSuite([First("test_slow"), Second("test_fast")]))
        return result, out.getvalue(), time.perf_counter() - started

    def test_seconds_are_summed_per_test_file_never_exceed_the_run_and_the_results_stay_the_same(self):
        result, _out, elapsed = self.run_two_modules()
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(sorted(result.module_seconds), ["fake_module_first", "fake_module_second"])
        self.assertGreaterEqual(result.module_seconds["fake_module_first"], 0.05)
        self.assertLessEqual(sum(result.module_seconds.values()), elapsed, "파일별 시간의 합은 실행 시간을 넘지 않는다(앞 시험이 끝난 때부터 이어 붙여 센다)")

    def test_a_slow_file_is_announced_as_soon_as_the_next_file_starts_and_the_last_one_is_left_to_the_table(self):
        with mock.patch.object(ci_shard, "PROGRESS_SECONDS", 0.01):
            _result, out, _elapsed = self.run_two_modules()
        self.assertIn("[걸린 시간] fake_module_first ", out)
        self.assertNotIn("[걸린 시간] fake_module_second", out)

    def test_a_fast_file_is_not_announced(self):
        with mock.patch.object(ci_shard, "PROGRESS_SECONDS", 60):
            _result, out, _elapsed = self.run_two_modules()
        self.assertNotIn("[걸린 시간]", out)

    def test_the_default_threshold_is_five_seconds(self):
        self.assertEqual(ci_shard.PROGRESS_SECONDS, 5)


class QtGuardRunTest(unittest.TestCase):
    """작은 가짜 시험 폴더로 진짜 `ci_shard.main` 을 자식 프로세스에서 돌린다(PySide6 가 깔렸는지만 환경과 상관없이 정한다)."""

    def folder(self, **modules):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for name, source in modules.items():
            (Path(temp.name) / f"{name}.py").write_text(source, encoding="utf-8")
        return f"--tests-dir={temp.name}"

    def test_without_the_flag_qt_skips_stay_a_normal_green_and_nothing_extra_is_printed(self):
        folder = self.folder(test_pass=PASSING_MODULE, test_qt_skip=skipping_module("PySide6 가 설치되어 있지 않다"))
        for installed in (False, True):
            done = run_driver(installed, "1", "1", folder)
            self.assertEqual(done.returncode, 0, done.stderr[-400:])
            self.assertNotIn("Qt 칸", done.stderr)
            self.assertNotIn("건너뛴 시험", done.stdout)
            self.assertNotIn("걸린 시간", done.stdout)

    def test_zero_and_an_empty_value_also_leave_the_guard_off(self):
        folder = self.folder(test_qt_skip=skipping_module("PySide6 가 설치되어 있지 않다"))
        for flag in ("0", ""):
            self.assertEqual(run_driver(False, "1", "1", folder, flag=flag).returncode, 0, repr(flag))

    def test_the_flag_without_pyside6_exits_three_before_any_test_runs(self):
        done = run_driver(False, "1", "1", self.folder(test_pass=PASSING_MODULE), flag="1")
        self.assertEqual(done.returncode, 3, done.stderr[-400:])
        self.assertIn("PySide6", done.stderr)
        self.assertNotIn("Ran ", done.stderr)
        self.assertNotIn("조각 1/1", done.stdout)

    def test_the_flag_with_pyside6_and_no_pyside6_skips_passes_and_prints_the_information(self):
        folder = self.folder(test_pass=PASSING_MODULE, test_git=skipping_module("git 이 필요하다", count=3))
        done = run_driver(True, "1", "1", folder, flag="1")
        self.assertEqual(done.returncode, 0, done.stderr[-400:])
        self.assertIn("PySide6 이유 0개", done.stdout)
        self.assertIn("3개  git 이 필요하다", done.stdout)
        self.assertIn("시험 파일별 걸린 시간", done.stdout)
        self.assertIn("test_git", done.stdout)
        self.assertNotIn("Qt 칸:", done.stderr)

    def test_a_pyside6_skip_exits_one_and_names_the_file_and_the_count(self):
        folder = self.folder(test_pass=PASSING_MODULE, test_qt_skip=skipping_module("PySide6 가 설치되어 있지 않다", count=2))
        done = run_driver(True, "1", "1", folder, flag="1")
        self.assertEqual(done.returncode, 1, done.stderr[-400:])
        self.assertIn("test_qt_skip: 2개", done.stderr)
        self.assertNotIn("test_pass:", done.stderr)
        self.assertIn("PySide6 이유 2개", done.stdout)
        self.assertIn("OK", done.stderr, "시험 자체는 모두 통과했다 — 가드가 따로 빨갛게 만든 것이다")

    def test_the_word_is_matched_in_any_case_and_inside_a_longer_sentence(self):
        for reason in ("pyside6 가 없다", "PYSIDE6", "Pyside6", "화면 도구 PySide6 설치가 필요하다 — 이 칸에는 없다"):
            with self.subTest(reason=reason):
                done = run_driver(True, "1", "1", self.folder(test_x=skipping_module(reason, count=1)), flag="1")
                self.assertEqual(done.returncode, 1, done.stderr[-300:])
                self.assertIn("test_x: 1개", done.stderr)

    def test_a_skip_inside_set_up_class_and_a_skip_when_the_file_is_loaded_are_caught_too(self):
        done = run_driver(True, "1", "1", self.folder(test_set_up=SET_UP_CLASS_SKIP), flag="1")
        self.assertEqual(done.returncode, 1, done.stderr[-300:])
        self.assertIn("test_set_up: 1개", done.stderr)
        done = run_driver(True, "1", "1", self.folder(test_module_skip=MODULE_SKIP), flag="1")
        self.assertEqual(done.returncode, 1, done.stderr[-300:])
        self.assertIn("test_module_skip: 1개", done.stderr)

    def test_other_reasons_are_only_information_and_do_not_fail_the_chamber(self):
        folder = self.folder(test_pass=PASSING_MODULE, test_a=skipping_module("이 환경에서는 링크를 만들 수 없다", count=2), test_b=skipping_module("git 이 필요하다", count=1))
        done = run_driver(True, "1", "1", folder, flag="1")
        self.assertEqual(done.returncode, 0, done.stderr[-300:])
        self.assertIn("그 밖의 이유 3개", done.stdout)
        self.assertIn("2개  이 환경에서는 링크를 만들 수 없다", done.stdout)

    def test_a_real_failure_still_fails_and_the_information_is_still_printed(self):
        done = run_driver(True, "1", "1", self.folder(test_bad=FAILING_MODULE, test_git=skipping_module("git 이 필요하다", count=1)), flag="1")
        self.assertEqual(done.returncode, 1)
        self.assertIn("일부러 실패", done.stderr)
        self.assertIn("건너뛴 시험", done.stdout)

    def test_a_failure_and_a_pyside6_skip_together_still_exit_one_and_report_both(self):
        done = run_driver(True, "1", "1", self.folder(test_bad=FAILING_MODULE, test_qt_skip=skipping_module("PySide6 가 없다", count=1)), flag="1")
        self.assertEqual(done.returncode, 1)
        self.assertIn("일부러 실패", done.stderr)
        self.assertIn("test_qt_skip: 1개", done.stderr)

    def test_an_unknown_flag_value_exits_two_and_runs_nothing(self):
        folder = self.folder(test_pass=PASSING_MODULE)
        for flag in ("true", "yes", "2", " 1", "on"):
            with self.subTest(flag=flag):
                done = run_driver(True, "1", "1", folder, flag=flag)
                self.assertEqual(done.returncode, 2, done.stderr[-300:])
                self.assertNotIn("Ran ", done.stderr)
                self.assertIn("CI_REQUIRE_QT", done.stderr)

    def test_list_mode_ignores_the_requirement_because_nothing_runs(self):
        done = run_driver(False, "1", "1", "--list", self.folder(test_pass=PASSING_MODULE), flag="1")
        self.assertEqual(done.returncode, 0, done.stderr[-300:])
        self.assertEqual(done.stdout.split(), ["test_pass"])

    def test_the_slowest_file_is_listed_first_in_the_time_table(self):
        done = run_driver(True, "1", "1", self.folder(test_a_fast=PASSING_MODULE, test_z_slow=SLOW_MODULE), flag="1")
        self.assertEqual(done.returncode, 0, done.stderr[-300:])
        table = done.stdout.split("시험 파일별 걸린 시간", 1)[1]
        self.assertLess(table.index("test_z_slow"), table.index("test_a_fast"), table)

    def test_the_real_script_without_pyside6_on_its_path_exits_three(self):
        # 가짜 대신 진짜 `qt_installed()`: `-S` 로 site-packages 를 빼면 환경이 어떻든 PySide6 를 못 찾는다.
        folder = self.folder(test_pass=PASSING_MODULE)
        env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "CI_SHARD", "CI_SHARD_TOTAL")}
        env.update(PYTHONUTF8="1", CI_REQUIRE_QT="1")
        done = subprocess.run([sys.executable, "-S", "-X", "utf8", str(SCRIPT), "1", "1", folder], capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT), timeout=300)
        self.assertEqual(done.returncode, 3, done.stderr[-400:])
        self.assertNotIn("Ran ", done.stderr)


def qt_flag_names(tree):
    """이 파일에서 `find_spec("PySide6")` 로 정해지는 이름들(보통 HAVE) + 다른 시험 파일에서 가져오는 `HAVE`."""
    names = {"HAVE"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and "PySide6" in ast.unparse(node.value):
            names |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        elif isinstance(node, ast.ImportFrom):
            names |= {alias.asname for alias in node.names if alias.name == "HAVE" and alias.asname}          # `from test_ui_qt import HAVE as 다른이름`
    return names


def qt_skip_problems(source):
    """한 시험 파일 소스에서 Qt 깃발(`HAVE` 등)을 조건으로 건너뛰는 `skipUnless`·`skipIf` 를 찾아 → (찾은 개수, 이유에 PySide6 가 없는 곳들의 설명)."""
    if "skipUnless" not in source and "skipIf" not in source:
        return 0, []                                                        # 건너뜀 낱말이 없는 파일은 파싱하지 않는다(시험 파일이 300개가 넘는다)
    tree = ast.parse(source)
    names = "|".join(re.escape(name) for name in sorted(qt_flag_names(tree)))
    flag = re.compile(r"(?<![A-Za-z_0-9])(?:[A-Za-z_][A-Za-z_0-9]*\.)?(?:" + names + r")(?![A-Za-z_0-9])")
    found, problems = 0, []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name)) and node.args):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        if name not in ("skipUnless", "skipIf"):
            continue
        condition = ast.unparse(node.args[0])
        if not flag.search(condition):
            continue
        found += 1
        reason = node.args[1] if len(node.args) > 1 else None
        if isinstance(reason, ast.Constant) and isinstance(reason.value, str):
            text = reason.value
        elif isinstance(reason, ast.JoinedStr):
            text = "".join(part.value for part in reason.values if isinstance(part, ast.Constant))
        else:
            problems.append(f"{node.lineno}줄: 건너뜀 이유가 글자 그대로가 아니다")
            continue
        if "pyside6" not in text.casefold():
            problems.append(f"{node.lineno}줄: 건너뜀 이유에 PySide6 낱말이 없다({text[:30]!r})")
    return found, problems


class QtSkipWordRuleTest(unittest.TestCase):
    """Qt 칸의 가드는 건너뜀 이유의 PySide6 낱말로 '못 돌았다' 를 알아본다 — 새 Qt 시험 파일이 다른 문구로 건너뛰어 가드를 피해 가지 못하게 정적으로 지킨다(설계서 CIQT 3-3)."""

    GOOD = "import importlib.util, unittest\nHAVE = importlib.util.find_spec('PySide6') is not None\n@unittest.skipUnless(HAVE, 'PySide6 가 설치되어 있지 않다')\nclass A(unittest.TestCase):\n    pass\n"

    def test_every_qt_skip_in_the_real_tests_names_pyside6_in_its_reason(self):
        total, problems = 0, []
        for path in sorted((ROOT / "tests").glob("test*.py")):
            found, bad = qt_skip_problems(path.read_text(encoding="utf-8"))
            total += found
            problems += [f"{path.name} {item}" for item in bad]
        self.assertGreater(total, 60, "Qt 깃발로 건너뛰는 곳을 실제로 훑는다(훑기가 깨지면 이 시험이 아무것도 안 본 채 통과하지 않게)")
        self.assertEqual(problems, [])

    def test_the_scanner_accepts_the_good_shape_and_ignores_other_skips(self):
        self.assertEqual(qt_skip_problems(self.GOOD), (1, []))
        other = "import unittest, shutil\nHAVE_GIT = shutil.which('git')\n@unittest.skipUnless(HAVE_GIT, 'git 이 필요하다')\nclass A(unittest.TestCase):\n    pass\n"
        self.assertEqual(qt_skip_problems(other), (0, []))

    def test_the_scanner_catches_a_reason_without_the_word_or_a_non_literal_reason(self):
        bad_word = self.GOOD.replace("PySide6 가 설치되어 있지 않다", "화면 도구가 없다")
        self.assertEqual(qt_skip_problems(bad_word)[0], 1)
        self.assertEqual(len(qt_skip_problems(bad_word)[1]), 1)
        dynamic = self.GOOD.replace("'PySide6 가 설치되어 있지 않다'", "REASON")
        self.assertEqual(len(qt_skip_problems(dynamic)[1]), 1)
        no_reason = self.GOOD.replace(", 'PySide6 가 설치되어 있지 않다'", "")
        self.assertEqual(len(qt_skip_problems(no_reason)[1]), 1)

    def test_the_scanner_follows_flag_names_other_than_have_and_flags_taken_from_other_modules(self):
        renamed = "import importlib.util, unittest\nQT_OK = importlib.util.find_spec('PySide6') is not None\n@unittest.skipIf(not QT_OK, '없다')\nclass A(unittest.TestCase):\n    pass\n"
        self.assertEqual(len(qt_skip_problems(renamed)[1]), 1)
        imported = "import unittest\nimport test_ui_qt as tq\n@unittest.skipUnless(tq.HAVE, '없다')\nclass A(unittest.TestCase):\n    pass\n"
        self.assertEqual(len(qt_skip_problems(imported)[1]), 1)
        aliased = "import unittest\nfrom test_ui_qt import HAVE as QT_READY\n@unittest.skipUnless(QT_READY, '없다')\nclass A(unittest.TestCase):\n    pass\n"
        self.assertEqual(len(qt_skip_problems(aliased)[1]), 1)
        combined = "import unittest\nfrom x import HAVE\nimport os\n@unittest.skipUnless(HAVE and os.name == 'nt', '윈도 글꼴이 있어야 한다')\nclass A(unittest.TestCase):\n    pass\n"
        self.assertEqual(len(qt_skip_problems(combined)[1]), 1)

    def test_the_whole_workflow_is_exactly_the_approved_structure(self):
        # AS-S2 권고-7(D-693): 위 시험들은 낱말·정규식이라 작업 단위 permissions·env·matrix 의 self-hosted·액션의 소유자·SHA·persist-credentials: true 를 못 봤다(감사의 살아남은 변이 여섯).
        # 글을 구조로 읽어 최상위·작업·단계 키와 with·env·run 값과 matrix, 액션의 `소유자/저장소@커밋` 쌍을 승인된 목록과 글자 그대로 견준다(`tests/workflow_golden.py`).
        self.assertEqual(golden.ci_problems(self.ci), [])


if __name__ == "__main__":
    unittest.main()
