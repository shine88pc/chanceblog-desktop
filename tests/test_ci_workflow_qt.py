"""정식 CI 의 Qt 칸(`.github/workflows/ci.yml` 의 둘째 잡 `qt`, D-710·D-713, 운영자 확인 037 ① 승인 범위) 구조 시험 — 새 칸이 병합 문턱으로 쓸 만하고 조용히 꺼지지 않으며 아무것도 더 열지 않는다는 것을 지킨다.
`ci.yml` 은 **읽기만** 한다(워크플로 변경은 T3). PyYAML 없이(정식 CI 열두 칸에는 없다) 들여쓰기로 읽는다 — 이 파일의 `[1, 2, 3]` 같은 한 줄 목록은 `workflow_yaml_support` 가 읽지 않아 따로 읽는다.

지키는 것(`qt_problems` 가 문제 글을 모으고, 진짜 파일은 빈 목록이어야 하며, 일부러 틀리게 만든 사본은 모두 걸려야 한다):
  1) 잡은 `test`(오늘 그대로) 다음에 `qt` 하나 — 최상위 키·권한(`contents: read` 한 줄, 잡 권한 없음)·비밀 0.
  2) `qt` 잡: 윈도(`windows-latest`)·파이썬 `'3.12'` 고정(행렬은 조각 하나뿐), `fail-fast: false`, 시간 한도 40분 이상(`test` 잡도), 이름이 `Qt 시험 (` 으로 시작해 기존 이름 시험과 안 부딪히고 조각 총수가 환경 변수와 같다.
  3) 단계 넷: 가져오기·파이썬(둘 다 `test` 잡과 **같은 SHA**, 이 파일의 액션은 그 둘뿐)·`python scripts/ci_qt_setup.py`(환경·옵션 없음)·`python scripts/ci_shard.py`(환경 변수 정확히 다섯: PYTHONUTF8·CI_SHARD·CI_SHARD_TOTAL·CI_REQUIRE_QT=1·QT_QPA_PLATFORM=offscreen).
  4) `test` 잡의 시험 단계에는 `CI_REQUIRE_QT`·`QT_QPA_PLATFORM` 이 없다(열두 칸은 Qt 건너뜀이 정상이다) — 그리고 `if:`·`continue-on-error`·`include:`·`exclude:`·잡·파일 수준 `env:` 가 어디에도 없다.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
EXPECTED_TOP = ["name", "on", "permissions", "concurrency", "jobs"]
ALLOWED_ACTIONS = {"actions/checkout", "actions/setup-python"}
QT_ENV = {"PYTHONUTF8": "'1'", "CI_SHARD": "${{ matrix.shard }}", "CI_REQUIRE_QT": "'1'", "QT_QPA_PLATFORM": "offscreen"}       # CI_SHARD_TOTAL 은 따로(조각 총수)
FORBIDDEN_WORDS = ("if:", "continue-on-error", "include:", "exclude:", "pull_request")


def code_lines(text):
    """주석(줄 전체·줄 끝)과 빈 줄을 뺀 코드 줄 — 들여쓰기는 그대로."""
    lines = []
    for line in text.replace("\r\n", "\n").splitlines():
        stripped = re.sub(r"(^|\s)#.*$", "", line).rstrip()
        if stripped.strip():
            lines.append(stripped)
    return lines


def jobs_of(lines):
    """`jobs:` 아래 잡마다 그 잡의 코드 줄들 → {잡 이름: [줄, ...]}(파일 순서)."""
    jobs, current, inside = {}, None, False
    for line in lines:
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


def job_value(job, key):
    for line in job:
        found = re.match(rf"^    {re.escape(key)}:\s*(.*)$", line)
        if found:
            return found.group(1).strip()
    return None


def job_steps(job):
    steps, current, inside = [], None, False
    for line in job:
        if re.match(r"^    steps:\s*$", line):
            inside = True
        elif inside and re.match(r"^    \S", line):
            break
        elif inside and line.startswith("      - "):
            current = [line]
            steps.append(current)
        elif inside and current is not None:
            current.append(line)
    return steps


def step_value(step, key):
    for line in step:
        found = re.match(rf"^(?:      - |        ){re.escape(key)}:\s*(.*)$", line)
        if found:
            return found.group(1).strip()
    return None


def step_block(step, key):
    """단계 안의 `key:` 아래 한 단계 더 들여쓴 `이름: 값` 들 → {이름: 값}(없으면 None)."""
    block, inside = {}, False
    for line in step:
        if re.match(rf"^        {re.escape(key)}:\s*$", line):
            inside, block = True, {}
        elif inside:
            found = re.match(r"^          ([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
            if not found:
                break
            block[found.group(1)] = found.group(2).strip()
    return block if inside else None


def uses_of(step):
    return step_value(step, "uses")


def strategy_shape(job):
    """`strategy:` 아래 여섯 칸 들여쓴 키들과 그 아래 여덟 칸 들여쓴 키들 → (["fail-fast", "matrix"], ["shard"]) 꼴."""
    level6, level8, inside = [], [], False
    for line in job:
        if re.match(r"^    strategy:\s*$", line):
            inside = True
        elif inside and re.match(r"^    \S", line):
            break
        elif inside:
            found = re.match(r"^( {6}| {8})([A-Za-z0-9_-]+):", line)
            if found:
                (level6 if len(found.group(1)) == 6 else level8).append(found.group(2))
    return level6, level8


def shard_list(job):
    found = re.search(r"^\s+shard:\s*\[([0-9, ]+)\]$", "\n".join(job), re.M)
    return [int(item) for item in found.group(1).replace(" ", "").split(",")] if found else None


def qt_problems(text):
    """`ci.yml` 글이 Qt 칸 규칙을 어기는 곳들의 설명(없으면 빈 목록)."""
    problems = []
    lines = code_lines(text)
    joined = "\n".join(lines)
    top = [line.split(":")[0] for line in lines if not line.startswith(" ")]
    if top != EXPECTED_TOP:
        problems.append(f"최상위 키가 {EXPECTED_TOP} 가 아니다: {top}")
    if "permissions:\n  contents: read" not in joined or joined.count("permissions:") != 1:
        problems.append("권한은 최상위 `permissions:` 의 `contents: read` 한 줄뿐이어야 한다(잡 권한 없음)")
    if re.search(r"secrets|github\.token|GITHUB_TOKEN", joined, re.I):
        problems.append("비밀·토큰 참조가 있다")
    for word in FORBIDDEN_WORDS:
        if [line for line in lines if word in line]:
            problems.append(f"금지된 낱말: {word}")
    if [line for line in lines if re.match(r"^(env|defaults|services|container):", line) or re.match(r"^    (env|defaults|services|container|permissions|needs):", line)]:
        problems.append("파일·잡 수준 env·defaults·services·container·permissions·needs 가 있다")
    jobs = jobs_of(lines)
    if list(jobs) != ["test", "qt"]:
        problems.append(f"잡은 test 다음에 qt 하나여야 한다: {list(jobs)}")
        return problems
    for name, job in jobs.items():
        minutes = job_value(job, "timeout-minutes")
        if not (minutes or "").isdigit() or int(minutes) < 40:
            problems.append(f"{name}: 시간 한도가 40분 이상이어야 한다({minutes})")
        if "      fail-fast: false" not in job:
            problems.append(f"{name}: fail-fast: false 가 없다")
    test, qt = jobs["test"], jobs["qt"]
    test_steps, qt_steps = job_steps(test), job_steps(qt)
    if len(test_steps) != 3:
        problems.append(f"test 잡 단계가 셋이 아니다({len(test_steps)})")
        return problems
    env = step_block(test_steps[2], "env")
    if env is None or sorted(env) != ["CI_SHARD", "CI_SHARD_TOTAL", "PYTHONUTF8"]:
        problems.append(f"test 잡의 시험 단계 환경 변수가 정확히 셋이 아니다(Qt 칸 표시가 열두 칸에 새면 안 된다): {sorted(env or [])}")
    if job_value(qt, "runs-on") != "windows-latest":
        problems.append(f"qt 잡 runs-on 이 windows-latest 가 아니다({job_value(qt, 'runs-on')})")
    if strategy_shape(qt) != (["fail-fast", "matrix"], ["shard"]):
        problems.append(f"qt 잡 strategy 는 fail-fast 와 matrix.shard 뿐이어야 한다(os·python·include 없음): {strategy_shape(qt)}")
    if len(qt_steps) != 4:
        problems.append(f"qt 잡 단계가 넷이 아니다({len(qt_steps)})")
        return problems
    total = (step_block(qt_steps[3], "env") or {}).get("CI_SHARD_TOTAL", "")
    count = int(total.strip("'")) if re.fullmatch(r"'\d+'", total) else 0
    if count < 1 or shard_list(qt) != list(range(1, count + 1)):
        problems.append(f"qt 잡 조각 목록 {shard_list(qt)} 이 1..CI_SHARD_TOTAL({total}) 과 다르다")
    if job_value(qt, "name") != f"Qt 시험 (windows-latest, Python 3.12, 조각 ${{{{ matrix.shard }}}}/{count})":
        problems.append(f"qt 잡 이름이 규칙과 다르다: {job_value(qt, 'name')}")
    if step_value(qt_steps[3], "name") != f"Qt 시험 실행(조각 ${{{{ matrix.shard }}}}/{count})":
        problems.append(f"qt 시험 단계 이름이 규칙과 다르다: {step_value(qt_steps[3], 'name')}")
    if step_value(qt_steps[2], "name") != "PySide6 두 줄만 설치·점검":
        problems.append("qt 설치 단계 이름이 규칙과 다르다")
    actions = {(uses_of(step) or "").split("@")[0] for step in test_steps + qt_steps if uses_of(step)}
    if actions != ALLOWED_ACTIONS:
        problems.append(f"이 파일의 액션은 checkout·setup-python 둘뿐이어야 한다: {sorted(actions)}")
    for index in (0, 1):
        if not uses_of(qt_steps[index]) or uses_of(qt_steps[index]) != uses_of(test_steps[index]):
            problems.append(f"qt 잡 {index + 1}번째 액션({uses_of(qt_steps[index])})이 test 잡({uses_of(test_steps[index])})과 같은 SHA 가 아니다")
        if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", uses_of(qt_steps[index]) or ""):
            problems.append(f"qt 잡 {index + 1}번째 액션이 전체 커밋 SHA 로 고정돼 있지 않다")
    if step_block(qt_steps[0], "with") != {"persist-credentials": "false"}:
        problems.append("가져오기 단계의 with 는 persist-credentials: false 하나뿐이어야 한다")
    if step_block(qt_steps[1], "with") != {"python-version": "'3.12'"}:
        problems.append("파이썬 단계의 with 는 python-version: '3.12' 하나뿐이어야 한다")
    if step_value(qt_steps[2], "run") != "python scripts/ci_qt_setup.py" or step_block(qt_steps[2], "env") is not None or step_block(qt_steps[2], "with") is not None:
        problems.append("설치 단계는 환경·옵션 없이 `run: python scripts/ci_qt_setup.py` 뿐이어야 한다")
    if step_value(qt_steps[3], "run") != "python scripts/ci_shard.py":
        problems.append("시험 단계의 run 이 `python scripts/ci_shard.py` 가 아니다")
    expected_env = dict(QT_ENV, CI_SHARD_TOTAL=total)
    if step_block(qt_steps[3], "env") != expected_env:
        problems.append(f"시험 단계 환경 변수가 정확히 {sorted(expected_env)} 와 값이 같아야 한다: {step_block(qt_steps[3], 'env')}")
    return problems


def mutated(text, old, new, within="qt"):
    """`within` 잡(`qt` 이면 `  qt:` 줄부터 끝까지, `test` 면 그 앞)에서 `old` 를 `new` 로 한 곳만 바꾼 글. 바뀌지 않았으면 시험이 허술한 것이라 실패한다."""
    head, marker, tail = text.partition("\n  qt:\n")
    target, other = (tail, head) if within == "qt" else (head, tail)
    if target.count(old) < 1:
        raise AssertionError(f"변이를 걸 곳이 없다: {old!r}")
    target = target.replace(old, new, 1)
    return (head + marker + target) if within == "qt" else (target + marker + other)


class RealWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = CI.read_text(encoding="utf-8")

    def test_the_real_ci_file_has_no_problem(self):
        self.assertEqual(qt_problems(self.text), [])

    def test_the_two_scripts_the_qt_job_calls_exist(self):
        for name in ("ci_qt_setup.py", "ci_shard.py"):
            self.assertTrue((ROOT / "scripts" / name).is_file(), name)

    def test_the_test_job_is_the_first_job_so_the_layout_test_reads_its_time_limit_first(self):
        self.assertLess(self.text.index("\n  test:\n"), self.text.index("\n  qt:\n"))
        self.assertEqual(re.search(r"^\s+timeout-minutes:\s*(\d+)", self.text, re.M).group(1), "40")

    def test_the_qt_job_reads_the_two_pins_only_from_the_lock_file_and_the_ci_file_names_no_package(self):
        for word in ("PySide6_Essentials", "shiboken6", "pip install", "requirements"):
            self.assertNotIn(word, "\n".join(code_lines(self.text)), word)

    def test_the_workflow_names_the_documentation_it_points_at(self):
        self.assertIn("docs/CI_QT.md", self.text)
        self.assertTrue((ROOT / "docs" / "CI_QT.md").is_file())

    def test_the_shard_total_of_the_qt_job_is_visible_in_both_names_and_the_environment(self):
        lines = code_lines(self.text)
        qt = jobs_of(lines)["qt"]
        total = (step_block(job_steps(qt)[3], "env") or {})["CI_SHARD_TOTAL"].strip("'")
        self.assertEqual(shard_list(qt), list(range(1, int(total) + 1)))
        for line in qt:
            if "조각" in line and "matrix.shard" in line:
                self.assertIn("/" + total, line)

    def test_the_parser_helpers_read_the_real_file_the_way_the_checks_assume(self):
        jobs = jobs_of(code_lines(self.text))
        self.assertEqual(list(jobs), ["test", "qt"])
        self.assertEqual([len(job_steps(job)) for job in jobs.values()], [3, 4])
        self.assertEqual(shard_list(jobs["test"]), [1, 2, 3])
        self.assertEqual(job_value(jobs["qt"], "runs-on"), "windows-latest")
        self.assertEqual(step_block(job_steps(jobs["qt"])[3], "env")["QT_QPA_PLATFORM"], "offscreen")


class MutationTest(unittest.TestCase):
    """일부러 틀리게 만든 사본이 모두 걸리는지 — 살아남는 변이가 있으면 그 검사가 허술한 것이다(설계서 CIQT ⑤ 의 변이 넷 + 더)."""

    def setUp(self):
        self.text = CI.read_text(encoding="utf-8")
        self.assertEqual(qt_problems(self.text), [], "원본은 문제가 없어야 변이 시험이 뜻이 있다")

    def mutations(self):
        text = self.text
        yield "qt 를 우분투에서 돌림", mutated(text, "runs-on: windows-latest", "runs-on: ubuntu-latest")
        yield "qt 를 옛 윈도 이미지로", mutated(text, "runs-on: windows-latest", "runs-on: windows-2019")
        yield "qt 의 파이썬을 3.10 으로", mutated(text, "python-version: '3.12'", "python-version: '3.10'")
        yield "CI_REQUIRE_QT 삭제", mutated(text, "          CI_REQUIRE_QT: '1'\n", "")
        yield "CI_REQUIRE_QT 를 0 으로", mutated(text, "CI_REQUIRE_QT: '1'", "CI_REQUIRE_QT: '0'")
        yield "QT_QPA_PLATFORM 삭제", mutated(text, "          QT_QPA_PLATFORM: offscreen\n", "")
        yield "test 잡(열두 칸)에 CI_REQUIRE_QT 추가", mutated(text, "          CI_SHARD_TOTAL: '3'\n", "          CI_SHARD_TOTAL: '3'\n          CI_REQUIRE_QT: '1'\n", within="test")
        yield "qt 의 가져오기 액션을 태그로", mutated(text, "actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4.4.0", "actions/checkout@v4")
        yield "qt 의 파이썬 액션 SHA 를 다르게", mutated(text, "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", "actions/setup-python@" + "b" * 40)
        yield "qt 시간 한도 10분", mutated(text, "timeout-minutes: 40", "timeout-minutes: 10")
        yield "qt fail-fast 를 켬", mutated(text, "fail-fast: false", "fail-fast: true")
        yield "qt 에 continue-on-error", mutated(text, "    runs-on: windows-latest\n", "    runs-on: windows-latest\n    continue-on-error: true\n")
        yield "qt 단계에 if", mutated(text, "      - name: PySide6 두 줄만 설치·점검\n", "      - name: PySide6 두 줄만 설치·점검\n        if: always()\n")
        yield "qt 조각 목록을 [1, 2] 로", mutated(text, "shard: [1, 2, 3]", "shard: [1, 2]")
        yield "qt 조각 목록에서 총수를 5 로만 바꿈", mutated(text, "CI_SHARD_TOTAL: '3'", "CI_SHARD_TOTAL: '5'")
        yield "qt 이름의 /3 을 /2 로", mutated(text, "조각 ${{ matrix.shard }}/3)\n    runs-on", "조각 ${{ matrix.shard }}/2)\n    runs-on")
        yield "qt 시험 단계 이름의 /3 을 /2 로", mutated(text, "Qt 시험 실행(조각 ${{ matrix.shard }}/3)", "Qt 시험 실행(조각 ${{ matrix.shard }}/2)")
        yield "qt 시험 단계 끝에 || true", mutated(text, "        run: python scripts/ci_shard.py", "        run: python scripts/ci_shard.py || true")
        yield "qt 에 낯선 액션 단계 추가", mutated(text, "      - name: PySide6 두 줄만 설치·점검\n", "      - uses: someone/else@" + "c" * 40 + "\n      - name: PySide6 두 줄만 설치·점검\n")
        yield "qt 설치 단계 삭제", mutated(text, "      - name: PySide6 두 줄만 설치·점검\n        run: python scripts/ci_qt_setup.py\n\n", "")
        yield "qt 설치 단계에 PIP_INDEX_URL 환경 변수", mutated(text, "        run: python scripts/ci_qt_setup.py", "        env:\n          PIP_INDEX_URL: something\n        run: python scripts/ci_qt_setup.py")
        yield "qt 설치 단계가 직접 pip", mutated(text, "run: python scripts/ci_qt_setup.py", "run: python -m pip install PySide6")
        yield "qt 잡에 쓰기 권한", mutated(text, "    runs-on: windows-latest\n", "    runs-on: windows-latest\n    permissions:\n      contents: write\n")
        yield "qt 잡에 비밀 참조", mutated(text, "CI_SHARD_TOTAL: '3'", "CI_SHARD_TOTAL: '3'\n          TOKEN: ${{ secrets.X }}")
        yield "qt 행렬에 os 추가", mutated(text, "        shard: [1, 2, 3]\n    steps:", "        shard: [1, 2, 3]\n        os: [ubuntu-latest]\n    steps:")
        yield "qt 행렬에 include", mutated(text, "      matrix:\n        shard: [1, 2, 3]\n    steps:", "      matrix:\n        shard: [1, 2, 3]\n        include:\n          - shard: 9\n    steps:")
        yield "qt 잡 이름 바꿈", text.replace("\n  qt:\n", "\n  qt2:\n", 1)
        yield "persist-credentials 삭제", mutated(text, "        with:\n          persist-credentials: false\n", "")
        yield "파일 수준 env 추가", text.replace("\njobs:\n", "\nenv:\n  PIP_INDEX_URL: something\n\njobs:\n", 1)
        yield "pull_request 이벤트 추가", text.replace("on:\n  push:\n", "on:\n  pull_request:\n  push:\n", 1)

    def test_every_broken_copy_is_caught(self):
        count = 0
        for label, broken in self.mutations():
            with self.subTest(mutation=label):
                self.assertNotEqual(broken, self.text, "변이가 글을 바꾸지 못했다")
                self.assertTrue(qt_problems(broken), f"살아남은 변이: {label}")
                count += 1
        self.assertGreaterEqual(count, 28)


if __name__ == "__main__":
    unittest.main()
