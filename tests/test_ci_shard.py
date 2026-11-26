"""CI 시험 조각 나누기(`scripts/ci_shard.py`, D-220) 시험 — 조각 나누기가 시험 파일을 빠뜨리거나 겹치지 않고, 같은 입력에 같은 결과를 내고, 실패를 삼키지 않고,
`ci.yml` 의 조각 수와 맞는다는 것을 지킨다. 이것이 깨지면 CI 가 일부 시험을 안 돌리고도 초록이 될 수 있다.

지키는 것:
  1) 시험 파일 전부(100개가 넘는다)가 조각 1~6개 어느 쪽으로 나눠도 정확히 한 조각에만 들어가고, 조각이 비지 않는다. 입력 순서와 상관없이 같은 결과다.
  2) 무게로 나눈 조각들의 차이가 가장 무거운 파일 하나를 넘지 않는다. 가장 무거운 세 파일은 세 조각에 하나씩 들어간다. 표에 없는 새 파일도 조각에 들어간다. 표에는 없어진 파일 이름이 없다.
  3) 잘못된 인자(0번·범위 밖·정수 아님·모르는 옵션 …)는 종료 코드 2, 비어 있는 조각은 1 — 아무것도 안 돌고 초록이 되지 않는다.
  4) 작은 가짜 시험 폴더로 실제 실행: 조각마다 자기 파일만 돌고, 실패하는 파일과 불러오기에 실패하는 파일이 그 조각을 빨갛게 만든다.
  5) `ci.yml` 의 조각 목록(`shard: [1, 2, 3]`)과 `CI_SHARD_TOTAL` 이 같고, `run:` 안에 `${{ }}` 가 없고, `fail-fast: false` 가 그대로다.
     (D-713) 둘째 잡 `qt` 가 생긴 뒤로는 이것을 `test`·`qt` 잡마다 본다(조각 목록·총수·이름 둘·`run:` 줄의 정확한 목록·`fail-fast`·`qt` 는 윈도와 3.12 하나뿐).
     (D-717·D-718) `qt` 잡은 조각 열둘이고 `CI_WEIGHTS: qt` 를 주며 작업 수준 `if` 한 줄(병합 가지·main 에서만)이 있다 — 파일 전체의 `if` 는 그 한 줄뿐이고 그 줄은 줄 끝 주석·뒤 공백 없이 줄 전체가 글자 그대로다(재작업 2).
  6) (D-712) Qt 칸의 건너뜀 가드 `CI_REQUIRE_QT`: 1 만 켬(0·없음은 끔, 그 밖은 종료 코드 2)·PySide6 를 못 찾으면 시험 전에 종료 코드 3·PySide6 이유로 건너뛴 시험이 하나라도 있으면 종료 코드 1(대소문자 무시,
     `setUpClass`·파일 불러오기 건너뜀 포함)·다른 이유의 건너뜀은 알림만·시험 파일별 걸린 시간 표와 오래 걸린 파일의 즉시 알림, 그리고 Qt 깃발(`HAVE`)로 건너뛰는 모든 시험이 이유에 PySide6 낱말을 쓰는지 정적 확인.
  7) (D-717) Qt 칸 전용 무게 표 `QT_WEIGHTS`·`QT_DEFAULT_WEIGHT` 와 환경 변수 `CI_WEIGHTS`: 없음·빈 값은 기본 표(열두 칸 — 표·기본 무게·나누기 결과를 옛 코드에서 뽑은 고정 값으로 못박는다), `qt` 는 Qt 표,
     그 밖의 값은 종료 코드 2 · `assign` 은 표와 기본 무게를 인자로 받는 순수 함수 · Qt 표의 키는 모두 진짜 시험 파일이고 값은 측정값(3차·4차 두 실행의 평균) ·
     표 자체 점검: 표의 숫자로 나눈 조각이 표 안에서 고르고(가장 무거운 조각이 이상의 1.15배 이하) 빈 조각이 없다 — 실제 러너 시간이 고르다는 뜻은 아니다(표가 실제와 어긋나도 이 점검은 초록이다 — 4차 진단이 실증) ·
     계획 줄의 합계와 기본 무게(표 밖 파일)를 못박고(재작업 2) 표의 숫자·시간 한도가 문서·결정·주석에 같게 적혀 있는지 본다.
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
    env.pop("CI_WEIGHTS", None)                             # Qt 칸의 무게 표 고르기(D-717)도 마찬가지 — 이 칸에서 돌 때 기본 표 시험이 Qt 표로 바뀌지 않게
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


QT_IF_LINE_TEXT = "    if: github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/ai/claude/M')"          # D-718 — 코드 줄의 글자 그대로(줄 끝 주석·뒤 공백 없이)


def qt_if_problems(ci):
    """`ci.yml` 글(줄 끝 그대로)의 `if:` 줄 문제 목록(없으면 빈 목록): 파일 전체에서 `qt` 잡 수준의 정해진 한 줄뿐이고, 그 줄은 줄 끝 주석·뒤 공백 없이 줄 전체가 글자 그대로이며, `test` 잡에는 `if` 가 없다.
    재작업 2(독립 검증 Q 권고-5): 줄 끝 주석에 시험들이 다르게 반응하던 것을(골든·`qt_problems`·이 묶음은 통과, `test_repo_layout` 의 한 시험만 거절) 엄격한 쪽으로 맞췄다."""
    lines = ci.replace("\r\n", "\n").split("\n")
    found = [line for line in lines if re.match(r"^\s*(?:-\s+)?if:", line)]
    problems = []
    if found != [QT_IF_LINE_TEXT]:
        problems.append(f"if 줄이 승인된 한 줄 그대로가 아니다: {found!r}")
    head, marker, tail = "\n".join(lines).partition("\n  qt:\n")
    if not marker or [line for line in tail.split("\n") if line.startswith("    if:")] != [QT_IF_LINE_TEXT]:
        problems.append("qt 잡 수준의 if 줄이 정해진 한 줄이 아니다")
    if [line for line in head.split("\n") if re.match(r"^\s*(?:-\s+)?if:", line)]:
        problems.append("test 잡(열두 칸)에 if 가 있다")
    return problems


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

    QT_IF_LINE = "    if: github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/ai/claude/M')"          # D-718 — 코드 줄(주석 뺀)의 글자 그대로

    def test_nothing_can_exclude_skip_or_forgive_a_shard(self):
        # 독립 검증 Y11~Y13: matrix exclude(조각을 통째로 뺌)·continue-on-error(실패를 용서)·if(단계를 건너뜀)가 들어와도 CI 가 초록일 수 있다.
        # D-718: `qt` 잡에 작업 수준 `if` 가 정확히 한 줄 생겼다(병합 가지·main 에서만 돈다). 금지가 풀린 것이 아니라 '그 한 줄만' 으로 좁혀졌다 —
        # 그 한 줄이 글자 그대로가 아니거나 다른 곳(test 잡·단계)에 if 가 하나라도 있으면 빨갛다(열두 칸은 모든 가지에서 돈다).
        for forbidden in ("exclude:", "include:", "continue-on-error"):
            self.assertEqual([line for line in self.code if forbidden in line], [], forbidden)
        self.assertEqual([line for line in self.code if "if:" in line], [self.QT_IF_LINE], "파일 전체의 if 는 qt 잡 수준의 정해진 한 줄뿐이다")
        self.assertEqual([line for line in self.jobs["qt"] if "if:" in line], [self.QT_IF_LINE.strip()])
        self.assertEqual([line for line in self.jobs["test"] if "if:" in line], [], "test 잡(열두 칸)에는 if 가 없다")
        self.assertEqual(qt_if_problems(self.ci), [], "if 줄은 줄 끝 주석·뒤 공백 없이 줄 전체가 글자 그대로다(재작업 2)")
        for job, lines in self.jobs.items():
            with self.subTest(job=job):
                self.assertIn("fail-fast: false", lines)
        for needle in ("windows-latest", "ubuntu-latest", "'3.10'", "'3.12'"):
            self.assertIn(needle, self.text)
        self.assertIn("runs-on: windows-latest", self.jobs["qt"])
        self.assertIn("python-version: '3.12'", self.jobs["qt"])
        for needle in ("ubuntu-latest", "'3.10'", "matrix.os", "matrix.python"):
            self.assertNotIn(needle, self.job_text["qt"], f"qt 잡은 윈도·3.12 하나뿐이다: {needle}")

    def test_the_if_line_is_whole_line_exact_and_an_end_of_line_comment_or_space_is_refused(self):
        """독립 검증 Q 권고-5(재작업 2): `if` 줄에 줄 끝 주석을 달면 골든·`qt_problems`·이 묶음은 통과시키고 `test_repo_layout` 의 한 시험만 거절하던 어긋남을 엄격한 쪽으로 맞췄다 — 이 묶음도 이제 줄 전체를 글자 그대로 견준다."""
        self.assertEqual(self.QT_IF_LINE, QT_IF_LINE_TEXT)
        self.assertEqual(qt_if_problems(self.ci), [])
        self.assertEqual(qt_if_problems(self.ci.replace("\n", "\r\n")), [], "윈도 줄 끝은 덧붙임이 아니다")
        variants = {
            "줄 끝 주석(값은 같다)": self.ci.replace(QT_IF_LINE_TEXT, QT_IF_LINE_TEXT + "  # CANARY 줄 끝 주석", 1),
            "줄 끝 주석(공백 하나)": self.ci.replace(QT_IF_LINE_TEXT, QT_IF_LINE_TEXT + " # CANARY", 1),
            "줄 끝 공백": self.ci.replace(QT_IF_LINE_TEXT, QT_IF_LINE_TEXT + " ", 1),
            "if 줄 삭제": self.ci.replace(QT_IF_LINE_TEXT + "\n", "", 1),
            "if 를 true 로": self.ci.replace(QT_IF_LINE_TEXT, "    if: true", 1),
            "if 줄을 하나 더": self.ci.replace(QT_IF_LINE_TEXT + "\n", QT_IF_LINE_TEXT + "\n" + QT_IF_LINE_TEXT + "\n", 1),
            "test 잡에 if": self.ci.replace("    timeout-minutes: 40\n", "    timeout-minutes: 40\n    if: github.ref == 'refs/heads/main'\n", 1),
            "단계 수준 if": self.ci.replace("      - name: PySide6 두 줄만 설치·점검\n", "      - name: PySide6 두 줄만 설치·점검\n        if: always()\n", 1),
        }
        for label, broken in variants.items():
            with self.subTest(variant=label):
                self.assertNotEqual(broken, self.ci, "변이가 글을 바꾸지 못했다")
                self.assertTrue(qt_if_problems(broken), "if 줄 변이가 통과했다")

    def test_only_the_qt_job_asks_for_the_qt_weight_table_and_it_has_twelve_shards(self):
        # D-717: `CI_WEIGHTS: qt` 는 qt 잡의 시험 단계에만 있고(열두 칸은 기본 무게 표), 조각 수는 열둘이다 — 목록·총수·이름이 모두 12(위 시험들이 서로 맞는지 본다).
        self.assertIn("CI_WEIGHTS: qt", self.jobs["qt"])
        self.assertNotIn("CI_WEIGHTS", self.job_text["test"])
        self.assertEqual((self.total("qt"), self.total("test")), (12, 3))
        self.assertEqual([line for line in self.stripped if line.startswith("CI_WEIGHTS")], ["CI_WEIGHTS: qt"], "파일 전체에서 CI_WEIGHTS 줄은 이 하나뿐")

    def test_the_whole_workflow_is_exactly_the_approved_structure(self):
        # AS-S2 권고-7(D-693): 위 시험들은 낱말·정규식이라 작업 단위 permissions·env·matrix 의 self-hosted·액션의 소유자·SHA·persist-credentials: true 를 못 봤다(감사의 살아남은 변이 여섯).
        # 글을 구조로 읽어 최상위·작업·단계 키와 with·env·run 값과 matrix, 액션의 `소유자/저장소@커밋` 쌍을 승인된 목록과 글자 그대로 견준다(`tests/workflow_golden.py`).
        # D-716: 작업이 둘(test·qt)이 된 뒤에도 같다 — 작업의 이름·순서·개수와 작업마다의 승인값을 견준다.
        self.assertEqual(golden.ci_problems(self.ci), [])


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


def run_driver(installed, *args, flag=None, weights=None):
    env = dict(os.environ, PYTHONUTF8="1")
    for name in ("CI_SHARD", "CI_SHARD_TOTAL", "CI_REQUIRE_QT", "CI_WEIGHTS"):
        env.pop(name, None)
    if flag is not None:
        env["CI_REQUIRE_QT"] = flag
    if weights is not None:
        env["CI_WEIGHTS"] = weights
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
        env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "CI_SHARD", "CI_SHARD_TOTAL", "CI_WEIGHTS")}
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


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Qt 칸 전용 무게 표(`QT_WEIGHTS`)와 환경 변수 `CI_WEIGHTS=qt`(D-717) — 표를 인자로 받는 순수한 `assign`·표 고르기·표의 모양과 값·정식 CI 열두 칸(기본 표)은 그대로임을 못박는다.
# ---------------------------------------------------------------------------------------------------------------------------------------------
OLD_WEIGHTS = {                       # 이번 변경(D-717) 앞의 기본 표 — 열두 칸은 한 글자도 안 바뀌었다는 증거로 글자 그대로 둔다
    "test_pages_publish": 780, "test_service_recovery": 460, "test_service_repolock": 430, "test_pages_repo": 265, "test_service_unpushed": 225,
    "test_service_candidates_process": 180, "test_service_echo": 135, "test_service_pages_git": 130, "test_auto_pr_workflow": 100, "test_vendor_core": 90,
    "test_service_keys_cli": 75, "test_service_suggest_process": 55, "test_service_draft_process": 40, "test_content_migration": 40, "test_service_pushed_post": 40,
    "test_topics_generate": 30, "test_service_lock": 25, "test_topicdb_backup": 25,
}
FILLERS = [f"test_filler_{index:02d}" for index in range(30)]
# 옛 코드(이번 변경 앞의 `assign`)에서 뽑은 값: 표의 열여덟 파일 + 기본 무게 파일 서른둘을 세 조각으로 나눈 결과
FROZEN_THREE = {
    "test_auto_pr_workflow": 3, "test_content_migration": 2, "test_pages_publish": 1, "test_pages_repo": 3, "test_service_candidates_process": 2, "test_service_draft_process": 1,
    "test_service_echo": 3, "test_service_keys_cli": 1, "test_service_lock": 1, "test_service_pages_git": 1, "test_service_pushed_post": 3, "test_service_recovery": 2,
    "test_service_repolock": 3, "test_service_suggest_process": 3, "test_service_unpushed": 2, "test_topicdb_backup": 2, "test_topics_generate": 2, "test_vendor_core": 2,
    "test_a_brand_new_module": 3, "test_zeta": 1,
}
FROZEN_FILLERS_THREE = [3, 3, 3, 3, 3, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3]
FROZEN_TWO = {"test_pages_publish": 1, "test_pages_repo": 1, "test_service_recovery": 2, "test_service_repolock": 2, "test_service_echo": 2, "test_vendor_core": 2}
QT_MEASURED_TOP = {                   # 3차(실행 45720452621)·4차(실행 45746502211) 진단의 모듈별 평균(max(1, round(평균)), 시험 파일 354개 전부)으로 만든 표의 가장 큰 일곱 — 총괄 지시서(재작업 2)의 숫자와 같다
    "test_ui_qt_seeds": 656, "test_ui_qt_photo_ocr": 600, "test_ui_qt_drafts": 468, "test_ui_qt_photo": 463, "test_ui_qt_settings": 455, "test_ui_qt_polish1": 445, "test_ui_qt_polish2": 408,
}


def ci_total(job):
    """`ci.yml` 의 `job`(`test` 또는 `qt`) 잡이 시험 단계에 주는 CI_SHARD_TOTAL(조각 수) — 표를 시험할 때 조각 수를 시험이 따로 정하지 않고 CI 가 정한 값을 따른다."""
    code = jobs_of(code_lines((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")))
    found = re.search(r"^\s+CI_SHARD_TOTAL:\s*'(\d+)'$", "\n".join(code[job]), re.M)
    assert found, f"ci.yml 의 {job} 잡에 CI_SHARD_TOTAL 이 없다"
    return int(found.group(1))


def loads_of(table, total, weights, default):
    loads = [0] * total
    for name, index in table.items():
        loads[index - 1] += ci_shard.weight_of(name, weights, default)
    return loads


class DefaultTableUnchangedTest(unittest.TestCase):
    """정식 CI 열두 칸이 쓰는 기본 표의 동작은 이번 변경(D-717, Qt 칸 전용 표)으로 한 글자도 바뀌지 않았다 — 표·기본 무게·나누기 결과를 옛 코드에서 뽑은 고정 값으로 못박는다."""

    NAMES = sorted(OLD_WEIGHTS) + FILLERS + ["test_a_brand_new_module", "test_zeta"]

    def test_the_default_table_and_the_default_weight_are_exactly_the_old_values(self):
        self.assertEqual(ci_shard.WEIGHTS, OLD_WEIGHTS)
        self.assertEqual(ci_shard.DEFAULT_WEIGHT, 4)
        self.assertEqual((ci_shard.weight_of("test_pages_publish"), ci_shard.weight_of("test_not_in_any_table")), (780, 4))

    def test_the_split_of_a_fixed_input_into_three_shards_is_the_old_split(self):
        table = ci_shard.assign(self.NAMES, 3)
        self.assertEqual({name: table[name] for name in FROZEN_THREE}, FROZEN_THREE)
        self.assertEqual([table[name] for name in FILLERS], FROZEN_FILLERS_THREE)
        self.assertEqual(sorted(table), sorted(self.NAMES))

    def test_the_split_into_two_shards_is_the_old_split_too(self):
        table = ci_shard.assign(self.NAMES, 2)
        self.assertEqual({name: table[name] for name in FROZEN_TWO}, FROZEN_TWO)

    def test_passing_the_default_table_explicitly_gives_the_same_split(self):
        for total in (1, 2, 3, 5):
            self.assertEqual(ci_shard.assign(self.NAMES, total, ci_shard.WEIGHTS, ci_shard.DEFAULT_WEIGHT), ci_shard.assign(self.NAMES, total), total)

    def test_without_a_table_the_module_tables_are_read_when_assign_runs(self):
        with mock.patch.object(ci_shard, "WEIGHTS", {"test_x": 100}), mock.patch.object(ci_shard, "DEFAULT_WEIGHT", 1):
            self.assertEqual(ci_shard.assign(["test_x", "test_y", "test_z"], 2), {"test_x": 1, "test_y": 2, "test_z": 2})


class AssignWithATableTest(unittest.TestCase):
    """`assign` 는 표(와 그 기본 무게)를 인자로 받는 순수 함수다 — 주면 그 표만 쓰고 모듈의 표·환경 변수에 기대지 않는다."""

    NAMES = ["test_a", "test_b", "test_c", "test_d", "test_pages_publish"]
    WEIGHTS = {"test_a": 10, "test_b": 7}

    def test_a_given_table_and_its_default_are_the_only_weights_used(self):
        # test_pages_publish 는 기본 표에서는 780 이지만 준 표에 없으니 준 기본 무게 3 이다 — 무거운 순 a(10) b(7) 다음 나머지는 3 씩(이름 순)
        table = ci_shard.assign(self.NAMES, 2, self.WEIGHTS, 3)
        self.assertEqual(table, {"test_a": 1, "test_b": 2, "test_c": 2, "test_d": 1, "test_pages_publish": 2})
        self.assertEqual(ci_shard.weight_of("test_pages_publish", self.WEIGHTS, 3), 3)
        self.assertEqual(ci_shard.weight_of("test_a", self.WEIGHTS, 3), 10)

    def test_the_default_of_a_given_table_is_not_the_default_tables(self):
        # 기본 무게를 바꾸면 결과가 달라진다(표에 없는 파일의 무게는 준 기본 무게에서 온다)
        loads_three = loads_of(ci_shard.assign(self.NAMES, 2, self.WEIGHTS, 3), 2, self.WEIGHTS, 3)
        loads_nine = loads_of(ci_shard.assign(self.NAMES, 2, self.WEIGHTS, 9), 2, self.WEIGHTS, 9)
        self.assertEqual(sum(loads_three), 10 + 7 + 3 * 3)
        self.assertEqual(sum(loads_nine), 10 + 7 + 3 * 9)
        self.assertEqual(ci_shard.weight_of("test_c", {}, 7), 7, "빈 표도 표다 — 기본 표로 돌아가지 않는다")
        self.assertEqual(ci_shard.weight_of("test_pages_publish", {}, 7), 7, "빈 표를 '표 없음' 으로 읽으면 기본 표의 780 이 나온다 — 기본 표에 든 이름으로 견준다(독립 검증 Q 의 변이 Q15)")

    def test_a_given_table_ignores_the_module_tables_and_the_environment(self):
        expected = ci_shard.assign(self.NAMES, 3, self.WEIGHTS, 2)
        with mock.patch.dict(os.environ, {"CI_WEIGHTS": "qt", "CI_REQUIRE_QT": "1"}), mock.patch.object(ci_shard, "WEIGHTS", {"test_a": 999}), \
                mock.patch.object(ci_shard, "DEFAULT_WEIGHT", 77), mock.patch.object(ci_shard, "QT_WEIGHTS", {"test_b": 888}), mock.patch.object(ci_shard, "QT_DEFAULT_WEIGHT", 66):
            self.assertEqual(ci_shard.assign(self.NAMES, 3, self.WEIGHTS, 2), expected)

    def test_a_given_table_keeps_the_rules_of_the_split(self):
        names = real_names()
        first = ci_shard.assign(names, 5, ci_shard.QT_WEIGHTS, ci_shard.QT_DEFAULT_WEIGHT)
        self.assertEqual(first, ci_shard.assign(list(reversed(names)), 5, ci_shard.QT_WEIGHTS, ci_shard.QT_DEFAULT_WEIGHT), "입력 순서와 상관없이 같은 결과")
        self.assertEqual(sorted(first), names)
        for index in range(1, 6):
            self.assertTrue([name for name in names if first[name] == index], f"{index}번 조각이 비었다")


class WeightsFlagTest(unittest.TestCase):
    """환경 변수 `CI_WEIGHTS` — 없음·빈 값은 기본 표, `qt` 는 Qt 칸 전용 표, 그 밖의 값은 거절(오타로 기본 표를 쓴 채 조각이 쏠려 시간 한도에 걸리지 않게)."""

    def test_nothing_or_an_empty_value_means_the_default_table(self):
        for env in ({}, {"CI_WEIGHTS": ""}):
            with self.subTest(env=env):
                name, weights, default = ci_shard.weights_table(env)
                self.assertEqual(name, "")
                self.assertIs(weights, ci_shard.WEIGHTS)
                self.assertEqual(default, ci_shard.DEFAULT_WEIGHT)

    def test_qt_means_the_qt_table_and_its_own_default(self):
        name, weights, default = ci_shard.weights_table({"CI_WEIGHTS": "qt"})
        self.assertEqual(name, "qt")
        self.assertIs(weights, ci_shard.QT_WEIGHTS)
        self.assertEqual(default, ci_shard.QT_DEFAULT_WEIGHT)

    def test_any_other_value_is_refused_so_a_typo_cannot_fall_back_to_the_default_table(self):
        for value in ("QT", "Qt", "qt ", " qt", "default", "test", "0", "1", "true", "on", "qt,qt", "qtt", "q", "ㅂㅅ", "-qt"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ci_shard.weights_table({"CI_WEIGHTS": value})

    def test_the_flag_name_is_the_documented_one(self):
        self.assertEqual(ci_shard.WEIGHTS_FLAG, "CI_WEIGHTS")


class QtWeightsTableTest(unittest.TestCase):
    """Qt 칸 전용 무게 표 — 이름이 모두 진짜 시험 파일이고 값이 측정값이다. 그리고 **표 자체 점검**: 표의 숫자로 나눈 조각이 표 안에서 고르고 빈 조각이 없다.
    이 점검은 표의 숫자로만 계산하므로 표가 실제 러너 시간과 어긋나도 초록이다 — 3차 한 번의 값으로 만든 표는 이 시험을 통과했지만 4차 진단의 실제 가장 느린 조각은 이상의 약 2배였다(독립 검증 Q 권고-2).
    실제와의 견줌은 진단 실행의 계획 줄·실제 합계 견주기(docs/CI_QT.md 5·7절)가 한다."""

    def test_every_key_is_a_test_file_that_exists_so_no_stale_name_piles_up(self):
        names = set(real_names())
        stale = sorted(name for name in ci_shard.QT_WEIGHTS if name not in names)
        self.assertEqual(stale, [], "없어졌거나 이름이 바뀐 시험 파일이 Qt 무게표에 남아 있다 — 표를 다시 재거나 이름을 고친다(docs/CI_QT.md)")

    def test_every_value_is_a_positive_whole_number_of_seconds(self):
        for name, value in ci_shard.QT_WEIGHTS.items():
            with self.subTest(name=name):
                self.assertIs(type(value), int)
                self.assertGreater(value, 0, "무게 0 은 가장 가벼운 조각이 늘 같아 한 조각에 몰린다")

    def test_the_two_run_average_of_the_third_and_fourth_diagnosis_is_what_the_table_holds(self):
        # 표를 다시 재면(docs/CI_QT.md) 이 숫자와 결정(D-717)을 함께 고친다 — 슬쩍 바꾸면 여기서 빨개진다. 3차(실행 45720452621)·4차(실행 45746502211) 진단의 시험 파일 354개 전부, 값은 두 실행의 모듈별 평균의 max(1, round(평균))
        for name, seconds in QT_MEASURED_TOP.items():
            self.assertEqual(ci_shard.QT_WEIGHTS[name], seconds, name)
        self.assertEqual(sorted(ci_shard.QT_WEIGHTS.values(), reverse=True)[:7], sorted(QT_MEASURED_TOP.values(), reverse=True))
        self.assertEqual((len(ci_shard.QT_WEIGHTS), sum(ci_shard.QT_WEIGHTS.values())), (354, 10956))
        self.assertEqual((ci_shard.QT_WEIGHTS["test_pages_publish"], ci_shard.QT_WEIGHTS["test_service_recovery"], ci_shard.QT_WEIGHTS["test_service_repolock"]), (157, 96, 97))

    # 옛 이름 둘(2차·3차 진단 때의 이름) — 시험 id 가 사라지지 않게 같은 시험을 별칭으로 둔다(이름이 말하는 '2차'·'3차' 는 낡았다: 위 시험이 3차·4차 두 실행의 평균을 지킨다)
    test_the_numbers_of_the_third_diagnosis_are_what_the_table_holds = test_the_two_run_average_of_the_third_and_fourth_diagnosis_is_what_the_table_holds
    test_the_numbers_of_the_second_diagnosis_are_what_the_table_holds = test_the_two_run_average_of_the_third_and_fourth_diagnosis_is_what_the_table_holds

    def test_the_default_weight_is_a_small_value_and_not_the_default_tables(self):
        self.assertEqual(ci_shard.QT_DEFAULT_WEIGHT, 3)
        self.assertNotEqual(ci_shard.QT_DEFAULT_WEIGHT, ci_shard.DEFAULT_WEIGHT, "같으면 기본 무게를 잘못 집어도 시험이 모른다")
        self.assertEqual(ci_shard.weight_of("test_a_brand_new_module", ci_shard.QT_WEIGHTS, ci_shard.QT_DEFAULT_WEIGHT), 3)
        self.assertLess(ci_shard.QT_DEFAULT_WEIGHT, min(ci_shard.QT_WEIGHTS["test_ui_qt_references"], 100))

    def test_the_qt_table_is_its_own_table_measured_on_the_runner(self):
        self.assertIsNot(ci_shard.QT_WEIGHTS, ci_shard.WEIGHTS)
        self.assertNotIn("test_ui_qt_references", ci_shard.WEIGHTS)
        self.assertNotEqual(ci_shard.QT_WEIGHTS["test_pages_publish"], ci_shard.WEIGHTS["test_pages_publish"], "열두 칸 표는 개발 PC 값(780), Qt 칸 표는 러너 값(157)이다")

    def test_the_qt_split_covers_every_test_file_once_and_leaves_no_shard_empty(self):
        names, total = real_names(), ci_total("qt")
        self.assertGreaterEqual(total, 2)
        table = ci_shard.assign(names, total, ci_shard.QT_WEIGHTS, ci_shard.QT_DEFAULT_WEIGHT)
        self.assertEqual(sorted(table), names)
        self.assertTrue(all(1 <= index <= total for index in table.values()))
        for index in range(1, total + 1):
            self.assertTrue([name for name in names if table[name] == index], f"Qt 조각 {index}/{total} 이 비었다")

    def test_the_heaviest_shard_of_the_qt_split_is_within_fifteen_percent_of_the_ideal(self):
        # 표 자체 점검이다(실제 러너 시간이 아니다 — 표가 실제와 어긋나도 초록이다, 4차 진단이 실증). 이 값이 깨지면 표를 다시 재라는 신호는 맞지만 안 깨졌다고 실제 조각이 고르다는 뜻은 아니다(docs/CI_QT.md 7절).
        # 표로 나눈 가장 무거운 조각이 이상적 합계(전체 무게 ÷ 조각 수)의 1.15배 이하
        names, total = real_names(), ci_total("qt")
        loads = loads_of(ci_shard.assign(names, total, ci_shard.QT_WEIGHTS, ci_shard.QT_DEFAULT_WEIGHT), total, ci_shard.QT_WEIGHTS, ci_shard.QT_DEFAULT_WEIGHT)
        ideal = sum(loads) / total
        self.assertLessEqual(max(loads), 1.15 * ideal, f"가장 무거운 조각 {max(loads)}초, 이상 {ideal:.0f}초 — {loads}")
        self.assertGreaterEqual(min(loads), 0.85 * ideal, f"가장 가벼운 조각 {min(loads)}초, 이상 {ideal:.0f}초 — {loads}")

    def test_the_heaviest_files_each_get_a_shard_of_their_own(self):
        # 표 자체 점검이다(표의 숫자로 나눈 결과 — 실제 시간이 아니다, 위 시험의 설명과 같다)
        names, total = real_names(), ci_total("qt")
        table = ci_shard.assign(names, total, ci_shard.QT_WEIGHTS, ci_shard.QT_DEFAULT_WEIGHT)
        heaviest = sorted(ci_shard.QT_WEIGHTS, key=lambda name: (-ci_shard.QT_WEIGHTS[name], name))[:total]
        self.assertEqual(len({table[name] for name in heaviest}), total, "가장 무거운 파일들이 한 조각에 몰렸다")

    def test_the_qt_split_is_not_the_default_split(self):
        names = real_names()
        self.assertNotEqual(ci_shard.assign(names, 12, ci_shard.QT_WEIGHTS, ci_shard.QT_DEFAULT_WEIGHT), ci_shard.assign(names, 12))


def qt_limit_minutes():
    """`ci.yml` 의 `qt` 잡 `timeout-minutes`(정수) — 시험이 한도를 따로 정하지 않고 CI 가 정한 값을 따른다."""
    code = jobs_of(code_lines((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")))
    found = re.search(r"^    timeout-minutes:\s*(\d+)\s*$", "\n".join(code["qt"]), re.M)
    assert found, "ci.yml 의 qt 잡에 timeout-minutes 가 없다"
    return int(found.group(1))


def table_numbers():
    """문서·결정·주석이 적어야 하는 표의 숫자를 표와 `ci.yml` 에서 읽는다 → 개수·합계·조각 계획·상위 일곱·기본 무게·시간 한도."""
    weights, default = ci_shard.QT_WEIGHTS, ci_shard.QT_DEFAULT_WEIGHT
    names, total = real_names(), ci_total("qt")
    loads = sorted(set(loads_of(ci_shard.assign(names, total, weights, default), total, weights, default)))
    plan = f"{loads[0]:,}초" if len(loads) == 1 else f"{loads[0]:,}–{loads[-1]:,}초"
    top = sorted(weights.items(), key=lambda item: (-item[1], item[0]))[:7]
    return {"count": f"{len(weights)}개", "total": f"{sum(weights.values()):,}초", "plan": plan, "top": top, "default": default, "limit": qt_limit_minutes(), "shards": total}


def missing_numbers(label, text, numbers, count=True, total=True, plan=True, top=True, default=True, limit=True, shards=True):
    """`text`(문서·결정 행·주석)에 적혀 있어야 할 숫자 중 빠진 것들의 설명(없으면 빈 목록). 상위 일곱은 '이름 뒤 열두 글자 안에 그 값'(숫자 아닌 글자만 사이에)으로 읽는다."""
    missing = []
    if count and numbers["count"] not in text:
        missing.append(f"{label}: 표의 시험 파일 개수 {numbers['count']}")
    if total and numbers["total"] not in text:
        missing.append(f"{label}: 표의 합계 {numbers['total']}")
    if plan and numbers["plan"] not in text:
        missing.append(f"{label}: 조각마다의 표 기준 계획 {numbers['plan']}")
    if top:
        for name, value in numbers["top"]:
            if not re.search(re.escape(name) + r"[^0-9]{0,12}" + str(value) + r"(?![0-9])", text):
                missing.append(f"{label}: 상위 일곱의 {name} {value}")
    if default and not re.search(r"기본 무게[^0-9]{0,24}" + str(numbers["default"]) + "초", text):
        missing.append(f"{label}: 기본 무게 {numbers['default']}초")
    if limit and not re.search(r"한도[^0-9]{0,12}" + str(numbers["limit"]) + "분", text):
        missing.append(f"{label}: qt 잡의 시간 한도 {numbers['limit']}분")
    if shards and not re.search(r"/" + str(numbers["shards"]) + r"(?![0-9])", text):
        missing.append(f"{label}: qt 잡의 조각 수 /{numbers['shards']}(조각 N/{numbers['shards']}·두 이름의 /{numbers['shards']})")
    return missing


def decision_row(number):
    rows = [line for line in (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines() if line.startswith(f"| D-{number} |")]
    assert len(rows) == 1, f"D-{number} 행이 {len(rows)}개"
    return rows[0]


def shard_comment_block():
    """`scripts/ci_shard.py` 의 Qt 표 바로 위 설명 주석(첫 줄부터 `QT_DEFAULT_WEIGHT = ` 앞까지)."""
    source = (ROOT / "scripts" / "ci_shard.py").read_text(encoding="utf-8")
    start = source.index("# Qt 칸(`ci.yml` 의 `qt` 잡")
    return source[start:source.index("QT_DEFAULT_WEIGHT = ", start)]


def ci_qt_comment_block():
    """`ci.yml` 의 `qt` 잡과 그 위의 설명 주석(`# Qt 칸 — ` 부터 끝까지)."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    start = text.index("  # Qt 칸 — ")
    return text[start:]


class TableNumbersAreWrittenDownTest(unittest.TestCase):
    """표의 숫자(개수·합계·조각 계획·상위 일곱·기본 무게)와 `qt` 잡의 시간 한도가 `docs/CI_QT.md`·결정 D-717·`scripts/ci_shard.py` 의 표 위 주석·`ci.yml` 의 `qt` 잡 주석에 같게 적혀 있다.
    표를 다시 재면서 한 곳을 빠뜨리면(독립 검증 Q 의 변이 D01 — D-717 의 합계를 한 글자 고쳐도 어떤 시험도 몰랐다) 여기서 빨개지고 어느 곳에 무슨 숫자가 없는지 알려 준다. 값은 표와 `ci.yml` 에서 읽으므로 이 시험은 숫자를 따로 못박지 않는다(못박는 곳은 위 `QtWeightsTableTest`)."""

    def test_the_numbers_of_the_table_and_the_time_limit_are_written_the_same_in_every_place(self):
        numbers = table_numbers()
        places = {
            "docs/CI_QT.md": ((ROOT / "docs" / "CI_QT.md").read_text(encoding="utf-8"), {}),
            "docs/DECISIONS.md D-717": (decision_row(717), {}),
            "scripts/ci_shard.py 의 표 위 주석": (shard_comment_block(), {"top": False, "default": False, "shards": False}),
            ".github/workflows/ci.yml 의 qt 잡 주석": (ci_qt_comment_block(), {"count": False, "total": False, "top": False, "default": False, "shards": False}),
        }
        problems = []
        for label, (text, skip) in places.items():
            problems += missing_numbers(label, text, numbers, **skip)
        self.assertEqual(problems, [], "표의 숫자가 이 곳들에 같게 적혀 있어야 한다 — 표를 다시 쟀거나 시간 한도를 바꿨으면 문서·결정·주석을 같은 변경에서 고친다(docs/CI_QT.md 7절 5단계)")

    def test_the_numbers_come_from_the_table_and_the_workflow_and_are_the_ones_the_documents_describe(self):
        numbers = table_numbers()
        self.assertEqual((numbers["count"], numbers["total"], numbers["plan"], numbers["default"], numbers["limit"], numbers["shards"]), ("354개", "10,956초", "913초", 3, 60, 12))
        self.assertEqual([name for name, _ in numbers["top"]], ["test_ui_qt_seeds", "test_ui_qt_photo_ocr", "test_ui_qt_drafts", "test_ui_qt_photo", "test_ui_qt_settings", "test_ui_qt_polish1", "test_ui_qt_polish2"])

    def test_a_missing_or_changed_number_is_noticed_in_each_place(self):
        numbers = table_numbers()
        sources = {
            "docs": (self.read_doc(), {}),
            "decision": (decision_row(717), {}),
            "shard": (shard_comment_block(), {"top": False, "default": False, "shards": False}),
            "workflow": (ci_qt_comment_block(), {"count": False, "total": False, "top": False, "default": False, "shards": False}),
        }
        top_name, top_value = numbers["top"][0]
        edits = {
            "개수": (lambda text: text.replace(numbers["count"], "353개"), "count"),
            "합계": (lambda text: text.replace(numbers["total"], "10,955초"), "total"),
            "조각 계획": (lambda text: text.replace(numbers["plan"], "914초"), "plan"),
            "상위 일곱": (lambda text: re.sub("(" + re.escape(top_name) + "[^0-9]{0,12})" + str(top_value) + "(?![0-9])", lambda found: found.group(1) + str(top_value + 1), text), "top"),
            "기본 무게": (lambda text: re.sub(r"(기본 무게[^0-9]{0,24})" + str(numbers["default"]) + "초", lambda found: found.group(1) + "4초", text), "default"),
            "시간 한도": (lambda text: re.sub(r"(한도[^0-9]{0,12})" + str(numbers["limit"]) + "분", lambda found: found.group(1) + "61분", text), "limit"),
            "조각 수": (lambda text: re.sub(r"/" + str(numbers["shards"]) + r"(?![0-9])", "/13", text), "shards"),
        }
        for place, (text, skip) in sources.items():
            self.assertEqual(missing_numbers(place, text, numbers, **skip), [], place)
            for label, (edit, key) in edits.items():
                if skip.get(key) is False:
                    continue                                    # 그 곳이 적지 않는 숫자(예: 주석에는 상위 일곱이 없다)
                with self.subTest(place=place, number=label):
                    changed = edit(text)
                    self.assertNotEqual(changed, text, "변이가 글을 바꾸지 못했다")
                    self.assertTrue(missing_numbers(place, changed, numbers, **skip), "숫자를 바꿨는데 시험이 몰랐다")

    @staticmethod
    def read_doc():
        return (ROOT / "docs" / "CI_QT.md").read_text(encoding="utf-8")


class WeightsFlagRunTest(unittest.TestCase):
    """작은 가짜 시험 폴더로 진짜 `ci_shard.py` 를 자식 프로세스에서 돌려 `CI_WEIGHTS` 가 조각 나누기까지 이어지는지 본다(진짜 시험 폴더는 느려서 쓰지 않는다 — 표 자체는 위에서 진짜 이름으로 본다)."""

    def folder(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for name in ("test_a_light", "test_ui_qt_references", "test_ui_qt_seeds"):
            (Path(temp.name) / f"{name}.py").write_text(PASSING_MODULE, encoding="utf-8")
        return f"--tests-dir={temp.name}"

    def test_the_default_table_splits_by_name_because_every_file_weighs_the_same(self):
        folder = self.folder()
        self.assertEqual(run_script("1", "2", "--list", folder).stdout.split(), ["test_a_light", "test_ui_qt_seeds"])
        self.assertEqual(run_script("2", "2", "--list", folder).stdout.split(), ["test_ui_qt_references"])

    def test_the_qt_table_splits_by_the_measured_seconds(self):
        folder = self.folder()
        first = run_script("1", "2", "--list", folder, env_extra={"CI_WEIGHTS": "qt"})
        second = run_script("2", "2", "--list", folder, env_extra={"CI_WEIGHTS": "qt"})
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stderr + second.stderr)
        self.assertEqual(first.stdout.split(), ["test_ui_qt_seeds"])
        self.assertEqual(second.stdout.split(), ["test_a_light", "test_ui_qt_references"])

    def test_an_empty_value_is_the_default_table_and_a_typo_exits_two_before_anything_runs(self):
        folder = self.folder()
        self.assertEqual(run_script("1", "2", "--list", folder, env_extra={"CI_WEIGHTS": ""}).stdout.split(), ["test_a_light", "test_ui_qt_seeds"])
        for value in ("QT", "default", "1", "qt "):
            with self.subTest(value=value):
                done = run_script("1", "2", folder, env_extra={"CI_WEIGHTS": value})
                self.assertEqual(done.returncode, 2, done.stderr[-300:])
                self.assertIn("CI_WEIGHTS", done.stderr)
                self.assertNotIn("Ran ", done.stderr)
                self.assertNotIn("조각 1/2", done.stdout)

    def test_the_qt_table_prints_the_plan_of_the_shard_and_the_default_table_prints_nothing_new(self):
        folder = self.folder()
        qt = run_script("1", "2", folder, env_extra={"CI_WEIGHTS": "qt"})
        self.assertEqual(qt.returncode, 0, qt.stderr[-300:])
        self.assertIn("조각 1/2: 시험 파일 1개·시험 1개 (전체 3개 파일·3개 시험) — 무게 표 qt: 이 조각 656초", qt.stdout)
        plain = run_script("1", "2", folder)
        self.assertEqual(plain.returncode, 0, plain.stderr[-300:])
        self.assertIn("조각 1/2: 시험 파일 2개·시험 2개 (전체 3개 파일·3개 시험)\n", plain.stdout)
        self.assertNotIn("무게 표", plain.stdout)

    def outside_folder(self, table_files, outside):
        """표 안 파일 `table_files` 와 표 밖 파일 `outside` 개(이름 test_zz_outside_NN — 표에 없다)를 가진 가짜 시험 폴더."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for name in [*table_files, *[f"test_zz_outside_{index:02d}" for index in range(outside)]]:
            (Path(temp.name) / f"{name}.py").write_text(PASSING_MODULE, encoding="utf-8")
        return f"--tests-dir={temp.name}"

    def test_the_plan_line_adds_up_every_file_of_the_shard_and_counts_a_file_outside_the_table_at_the_default_weight(self):
        """독립 검증 Q 의 변이 Q25·Q26(재작업 2): 조각 하나(`1 1`)에 표 안 파일 둘(283초·656초)과 표 밖 파일 하나(기본 무게 3초)가 들면 계획 줄은 합계 942초다 —
        합 대신 최댓값(656)으로 계산하거나 표 밖 파일을 기본 표의 기본 무게(4초 → 943)로 치면 빨개진다."""
        done = run_script("1", "1", self.outside_folder(["test_ui_qt_references", "test_ui_qt_seeds"], 1), env_extra={"CI_WEIGHTS": "qt"})
        self.assertEqual(done.returncode, 0, done.stderr[-300:])
        self.assertIn("조각 1/1: 시험 파일 3개·시험 3개 (전체 3개 파일·3개 시험) — 무게 표 qt: 이 조각 942초", done.stdout)

    def test_the_default_weight_of_the_qt_table_decides_how_files_outside_the_table_are_split(self):
        """독립 검증 Q 의 변이 Q18(재작업 2): 표 밖 파일 80개는 3초씩이면 합 240초가 표 안 파일(283초)보다 작아 모두 한 조각에 모이고, 4초씩(열두 칸의 기본 무게)이면 합 320초가 283초보다 커서
        일부가 표 안 파일의 조각으로 간다 — `main` 이 Qt 표의 기본 무게를 `assign` 에 넘기지 않으면 빨개진다."""
        folder = self.outside_folder(["test_ui_qt_references"], 80)
        first = run_script("1", "2", "--list", folder, env_extra={"CI_WEIGHTS": "qt"})
        second = run_script("2", "2", "--list", folder, env_extra={"CI_WEIGHTS": "qt"})
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stderr + second.stderr)
        self.assertEqual(first.stdout.split(), ["test_ui_qt_references"])
        self.assertEqual(second.stdout.split(), [f"test_zz_outside_{index:02d}" for index in range(80)])
        plain = run_script("1", "2", "--list", folder)
        self.assertNotEqual(plain.stdout.split(), ["test_ui_qt_references"], "기본 표(모든 파일이 4초)로는 표 밖 파일 일부가 첫 조각에 든다 — 표를 고르는 환경 변수가 나누기를 바꾼다")

    def test_the_weights_flag_and_the_qt_guard_work_together_and_independently(self):
        folder = self.folder()
        both = run_driver(True, "1", "2", folder, flag="1", weights="qt")
        self.assertEqual(both.returncode, 0, both.stderr[-300:])
        self.assertIn("무게 표 qt", both.stdout)
        self.assertIn("시험 파일별 걸린 시간", both.stdout)
        guard_only = run_driver(True, "1", "2", folder, flag="1")
        self.assertNotIn("무게 표", guard_only.stdout)
        self.assertIn("시험 파일별 걸린 시간", guard_only.stdout)
        weights_only = run_driver(True, "1", "2", folder, weights="qt")
        self.assertIn("무게 표 qt", weights_only.stdout)
        self.assertNotIn("시험 파일별 걸린 시간", weights_only.stdout)

    def test_list_mode_follows_the_table_too_so_a_developer_can_preview_a_qt_shard(self):
        done = run_script("1", "2", "--list", self.folder(), env_extra={"CI_WEIGHTS": "qt", "CI_REQUIRE_QT": "1"})
        self.assertEqual((done.returncode, done.stdout.split()), (0, ["test_ui_qt_seeds"]), done.stderr[-300:])


if __name__ == "__main__":
    unittest.main()
