"""CI 시험 조각 나누기(`scripts/ci_shard.py`, D-220) 시험 — 조각 나누기가 시험 파일을 빠뜨리거나 겹치지 않고, 같은 입력에 같은 결과를 내고, 실패를 삼키지 않고,
`ci.yml` 의 조각 수와 맞는다는 것을 지킨다. 이것이 깨지면 CI 가 일부 시험을 안 돌리고도 초록이 될 수 있다.

지키는 것:
  1) 시험 파일 전부(100개가 넘는다)가 조각 1~6개 어느 쪽으로 나눠도 정확히 한 조각에만 들어가고, 조각이 비지 않는다. 입력 순서와 상관없이 같은 결과다.
  2) 무게로 나눈 조각들의 차이가 가장 무거운 파일 하나를 넘지 않는다. 가장 무거운 세 파일은 세 조각에 하나씩 들어간다. 표에 없는 새 파일도 조각에 들어간다. 표에는 없어진 파일 이름이 없다.
  3) 잘못된 인자(0번·범위 밖·정수 아님·모르는 옵션 …)는 종료 코드 2, 비어 있는 조각은 1 — 아무것도 안 돌고 초록이 되지 않는다.
  4) 작은 가짜 시험 폴더로 실제 실행: 조각마다 자기 파일만 돌고, 실패하는 파일과 불러오기에 실패하는 파일이 그 조각을 빨갛게 만든다.
  5) `ci.yml` 의 조각 목록(`shard: [1, 2, 3]`)과 `CI_SHARD_TOTAL` 이 같고, `run:` 안에 `${{ }}` 가 없고, `fail-fast: false` 가 그대로다.
"""
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci_shard.py"
sys.path.insert(0, str(ROOT / "scripts"))
import ci_shard  # noqa: E402


def real_names():
    return sorted(path.stem for path in (ROOT / "tests").glob("test*.py"))


def run_script(*args, env_extra=None):
    env = dict(os.environ, PYTHONUTF8="1")
    env.pop("CI_SHARD", None)
    env.pop("CI_SHARD_TOTAL", None)
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


class CiWorkflowShardTest(unittest.TestCase):
    def setUp(self):
        self.ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.code = code_lines(self.ci)
        self.text = "\n".join(self.code)
        self.stripped = [line.strip() for line in self.code]

    def total(self):
        found = re.search(r"^\s+CI_SHARD_TOTAL:\s*'(\d+)'$", self.text, re.M)
        self.assertIsNotNone(found, "ci.yml 에 CI_SHARD_TOTAL 이 없다")
        return int(found.group(1))

    def test_the_matrix_shards_and_the_total_agree(self):
        found = re.search(r"^\s+shard:\s*\[([0-9, ]+)\]$", self.text, re.M)
        self.assertIsNotNone(found, "ci.yml 의 matrix 에 shard 목록이 없다")
        shards = [int(item) for item in found.group(1).replace(" ", "").split(",")]
        self.assertEqual(shards, list(range(1, self.total() + 1)), "shard 목록은 1..CI_SHARD_TOTAL 이어야 한다 — 어긋나면 일부 시험이 안 돈다")

    def test_the_shard_number_comes_from_the_matrix_in_a_real_code_line(self):
        # 독립 검증 Y07b: `CI_SHARD: '1'  # CI_SHARD: ${{ matrix.shard }}` 처럼 주석에 원문을 남기고 값을 고정하면 모든 작업이 1번 조각만 돌고도 초록이 된다.
        self.assertIn("CI_SHARD: ${{ matrix.shard }}", self.stripped)
        self.assertIn("PYTHONUTF8: '1'", self.stripped)

    def test_the_job_and_step_names_show_the_same_total_as_the_environment(self):
        # 독립 검증 Y09: 이름의 '/3' 이 어긋나도 CI 는 도는 표시 문제지만 PR 화면에서 조각이 몇 개인지 잘못 읽게 된다.
        needle = "조각 ${{ matrix.shard }}/" + str(self.total())
        names = [line for line in self.stripped if line.startswith(("name: 시험 (", "- name: 시험 실행("))]
        self.assertEqual(len(names), 2, names)
        for line in names:
            self.assertIn(needle, line)

    def test_the_test_step_calls_the_shard_script_without_putting_expressions_in_run(self):
        runs = [line for line in self.stripped if line.startswith("run:")]
        self.assertEqual(runs, ["run: python scripts/ci_shard.py"])
        self.assertFalse([line for line in runs if "${{" in line])

    def test_nothing_can_exclude_skip_or_forgive_a_shard(self):
        # 독립 검증 Y11~Y13: matrix exclude(조각을 통째로 뺌)·continue-on-error(실패를 용서)·if(단계를 건너뜀)가 들어와도 CI 가 초록일 수 있다.
        for forbidden in ("exclude:", "include:", "continue-on-error", "if:"):
            self.assertEqual([line for line in self.code if forbidden in line], [], forbidden)
        self.assertIn("fail-fast: false", self.stripped)
        for needle in ("windows-latest", "ubuntu-latest", "'3.10'", "'3.12'"):
            self.assertIn(needle, self.text)


if __name__ == "__main__":
    unittest.main()
