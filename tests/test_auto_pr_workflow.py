"""병합 부탁 PR 자동 만들기(`.github/workflows/auto-pr.yml`, 운영자 확인 003 의 '② PR 만들기만 자동화', 2026-11-06, D-175) 시험 — `chanceblog` 저장소의 같은 이름 워크플로와 같은 규칙.

AI 가 `ai/claude/M번호-이름` 가지(main 위 한 커밋)를 push 하면 그 커밋의 검사(`ci.yml`, 네 칸)가 모두 초록이 된 뒤 PR 을 대신 만든다. **병합은 하지 않는다.** 이 시험은 다음을 고정한다.
 1. 모양 — 스크립트 앞의 설정 부분은 정해진 줄 목록과 글자 그대로 같아야 하고(트리거는 push 하나·가지 필터 둘, 권한은 셋뿐, 단계 하나), 스크립트에는 `uses:`·시크릿·`${{ }}`·병합·승인·라벨·코멘트 호출이
    없고 `gh` 는 정해진 호출만 한다. PyYAML 이 없는 CI(`ci.yml` 은 의존성을 설치하지 않는다)에서도 돌도록 YAML 라이브러리 없이 글자·줄 단위로 읽는다.
    같은 검사를 일부러 틀리게 만든 사본 19개에 돌려 시험이 정말 잡는지도 본다(살아남는 변이가 없어야 한다).
 2. 가지 필터(GitHub 글로브)와 스크립트의 정규식이 같은 가지를 가려낸다(필터가 더 넓고 정규식이 더 엄격할 수는 있다 — 정규식이 받은 가지는 필터도 받아야 한다).
 3. 동작 — `run:` 의 bash 를 그대로 꺼내 **가짜 `gh`**(셸 함수 — 호출 인자를 기록하고 미리 정한 값을 돌려준다)로 돌려 사례별 결과를 본다: 정상·제목이 번호로 시작하지 않음·가지 이름이 규칙 밖·
    이미 PR 있음·검사 실패/취소·가지 끝이 바뀜·앞선 커밋이 끼어 있다가 사라짐·검사 진행 중·기다림 시간 초과·권한 오류(경고 뒤 성공 종료)·제목·본문에 셸 문자가 있어도 그대로 전달.
    bash 를 못 찾으면 이 부분만 건너뛴다(Actions 의 ubuntu 에는 있고, Windows 칸은 러너에 설치된 Git Bash 를 찾아 쓴다). 네트워크·실제 GitHub 는 쓰지 않는다.
 4. 결정 기록·변경 이력·보안 문서가 같은 말을 한다.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WORKFLOW = ROOT / ".github" / "workflows" / "auto-pr.yml"
NAME = "[공통] 병합 부탁 PR 자동 만들기"
CI_WORKFLOW = "ci.yml"
FILTERS = ["ai/claude/M[0-9][0-9][0-9]-*", "ai/claude/M[0-9][0-9][0-9][0-9]-*"]
# 스크립트 앞(트리거·권한·동시 실행·job·단계 env)의 코드 줄 — 주석·빈 줄을 뺀 것이 이 목록과 글자 그대로 같아야 한다
EXPECTED_HEAD = [
    'name: "[공통] 병합 부탁 PR 자동 만들기"',
    "on:",
    "  push:",
    "    branches:",
    "      - 'ai/claude/M[0-9][0-9][0-9]-*'",
    "      - 'ai/claude/M[0-9][0-9][0-9][0-9]-*'",
    "permissions:",
    "  contents: read",
    "  pull-requests: write",
    "  actions: read",
    "concurrency:",
    "  group: auto-pr-${{ github.ref }}",
    "  cancel-in-progress: true",
    "jobs:",
    "  create-pr:",
    "    name: 검사가 초록이면 PR 만들기",
    "    runs-on: ubuntu-latest",
    "    timeout-minutes: 45",
    "    steps:",
    "      - name: 병합 부탁 PR 만들기(병합은 하지 않음)",
    "        env:",
    "          GH_TOKEN: ${{ github.token }}",
    "          REPO: ${{ github.repository }}",
    "          BRANCH: ${{ github.ref_name }}",
    "          SHA: ${{ github.sha }}",
    "          BASE: ${{ github.event.repository.default_branch }}",
    "          CI_WORKFLOW: ci.yml",
    "          AUTOPR_POLL_SECONDS: '30'",
    "          AUTOPR_MAX_WAIT_SECONDS: '2400'",
    "        run: |",
]
RUN_MARKER = "        run: |\n"
ENDPOINTS = [                         # 스크립트가 부르는 `gh api` 주소 — 이 다섯 가지뿐(맨 끝은 POST)
    "repos/${REPO}/git/commits/${SHA}",
    "repos/${REPO}/git/ref/heads/${BRANCH}",
    "repos/${REPO}/actions/workflows/${CI_WORKFLOW}/runs?head_sha=${SHA}&event=push&per_page=5",
    "repos/${REPO}/compare/${BASE}...${SHA}",
    "repos/${REPO}/pulls",
]
RUNS_JQ = '(.workflow_runs[0].status // "none") + ":" + (.workflow_runs[0].conclusion // "none")'
# 코드 줄(주석 뺀 글)에 있으면 안 되는 것: (이유, 정규식)
FORBIDDEN = [
    ("다른 트리거", re.compile(r"\b(?:pull_request_target|pull_request|workflow_run|issue_comment|schedule|workflow_dispatch|workflow_call|repository_dispatch)\b|^\s*issues:|^\s*create:|^\s*release:", re.M)),
    ("외부 액션", re.compile(r"\buses\s*:")),
    ("시크릿", re.compile(r"secrets\s*[.\[]|TELEGRAM|_KEY\b|_TOKEN\b(?<!GH_TOKEN)")),
    ("병합 호출", re.compile(r"merge|--admin|auto_merge|enable_auto", re.I)),
    ("승인·리뷰", re.compile(r"/reviews|\bgh\s+pr\s+review|event=APPROVE|--approve", re.I)),
    ("셸이 글을 해석하는 길", re.compile(r"\beval\b|\bbash\s+-c\b|\bsh\s+-c\b|\bsource\b|`")),
    ("git 명령", re.compile(r"\bgit\s+(push|commit|checkout|clone|fetch|config|remote|merge|rebase|reset|tag|branch|switch|restore)\b")),
    ("다른 프로그램", re.compile(r"\b(curl|wget|python3?|pip3?|perl|ruby|php|npm|npx|node)\b")),
    ("환경·출력 파일 쓰기", re.compile(r"GITHUB_ENV|GITHUB_OUTPUT|GITHUB_PATH|set-output|add-mask")),
    ("다른 HTTP 동사", re.compile(r"-X\s+(PUT|PATCH|DELETE|GET)\b|--method\b", re.I)),
    ("셸 안전장치 약화(`set +e`·`|| true`·`trap`)", re.compile(r"\bset\s+\+[a-zA-Z]|\|\|\s*(?:true\b|:(?=\s|$))|\btrap\b")),
]
# 스크립트에 있어야 하는 줄(글자 그대로) — 지워지거나 약해지면 이 시험이 잡는다(독립 검증이 변이로 찾은 틈: 앵커·숫자 확인·간격·기본값·로캘·본문 한도·검사 결론)
RE_LINES = ["re_repo='^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'", "re_base='^[A-Za-z0-9._/-]{1,100}$'", "re_workflow='^[A-Za-z0-9._-]+\\.ya?ml$'",
            "re_sha='^[0-9a-f]{40}$'", "re_zero='^0+$'", "re_branch='^ai/claude/(M[0-9]{3,4})-[A-Za-z0-9._-]{1,80}$'"]


def workflow_text():
    return WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")


def code_text(text):
    """주석만 있는 줄을 뺀 글(헤더 설명과 스크립트 속 `#` 주석은 규칙 설명을 담는다)."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def code_lines(text):
    return [line for line in text.split("\n") if line.strip() and not line.lstrip().startswith("#")]


def split_workflow(text):
    """(스크립트 앞의 글 — `run: |` 줄까지, 스크립트 글). `run: |` 은 파일의 마지막 키라 그 뒤는 모두 스크립트다(들여쓰기 10칸을 뗀다). 표식이 하나가 아니면 스크립트는 빈 글."""
    if text.count(RUN_MARKER) != 1:
        return text, ""
    head, block = text.split(RUN_MARKER, 1)
    script = "\n".join(line[10:] if line.startswith(" " * 10) else line for line in block.split("\n"))
    return head + RUN_MARKER, script


def script_of(text=None):
    return split_workflow(text if text is not None else workflow_text())[1]


def block(text, key):
    """최상위 키(`on`·`permissions` …) 아래의 코드 줄(주석·빈 줄 제외)."""
    lines = text.split("\n")
    start = lines.index(key + ":")
    out = []
    for line in lines[start + 1:]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        if line.strip() and not line.lstrip().startswith("#"):
            out.append(line)
    return out


def script_problems(run):
    """스크립트(`run:` 본문, 들여쓰기를 뗀 글)가 글자 그대로 지켜야 하는 줄·순서의 위반 목록(없으면 빈 목록). 독립 검증이 변이로 찾은 시험 틈(2026-11-07)을 메운다 —
    동작 시험이 잡지 못하던 줄(앵커·숫자 확인·쉬는 줄·기본값·로캘·본문 한도·검사 결론 패턴·CR 제거·엄격 모드)을 정적으로도 못박는다."""
    problems = []
    lines = run.split("\n")
    # 엄격 모드: 첫 줄이 `set -euo pipefail` 이고 `set` 명령은 그 하나뿐(약화·해제 금지)
    if lines[0] != "set -euo pipefail" or len(re.findall(r"^\s*set\s+[-+]", run, re.M)) != 1:
        problems.append("스크립트 첫 줄이 `set -euo pipefail` 이 아니거나 set 명령이 더 있음")
    # 로캘: 글자 수 세기(`${#title}`)·`[[:cntrl:]]` 가 실행 환경의 로캘에 기대지 않게 UTF-8 로 고정 — 제목 검사보다 앞, 한 줄로, 이 한 곳에만
    if run.count("LC_ALL") != 1 or "export LC_ALL=C.UTF-8" not in [line.strip() for line in lines] or run.index("LC_ALL") > run.index('[ "${#title}"'):
        problems.append("`export LC_ALL=C.UTF-8` 가 제목 검사보다 앞에 한 줄로 있어야 함")
    # 입력 모양 정규식 여섯 줄은 글자 그대로 — 앞 `^`·끝 `$` 가 있어야 bash 의 `=~`(검색)가 값 전체를 본다
    if re.findall(r"^re_\w+='[^']*'$", run, re.M) != RE_LINES:
        problems.append("입력 모양 정규식 여섯 줄이 정해진 것과 다름(앵커 포함)")
    # 숫자 확인: 기존 PR 수·main 과의 거리(`ahead_by`)는 숫자 모양일 때만 비교한다(아니면 읽기 실패로 센다)
    for name in ("existing", "ahead"):
        if f'[[ ! "${name}" =~ ^[0-9]+$ ]]' not in run:
            problems.append(f"{name} 의 숫자 모양 확인이 없음")
    # 검사 결론: 성공(`completed:success`)만 통과, 그 밖의 `completed:*` 는 모두 거절, 아직 안 끝난 것은 기다림 — case 패턴이 정확히 이 셋
    if re.findall(r"^\s+(completed:[^)\s]*|\*)\)\s*$", run, re.M) != ["completed:success", "completed:*", "*"]:
        problems.append("검사 결론 case 패턴이 completed:success · completed:* · * 셋이 아님")
    # 기다림: 반복마다 poll 초 쉰다(반복문 맨 끝 한 번), 값이 숫자가 아니면 기본값 30초·2400초
    if run.count('sleep "$poll"') != 1 or '\n  sleep "$poll"\ndone\n' not in run or len(re.findall(r"\bsleep\b", code_text(run))) != 1:
        problems.append('반복문 끝의 `sleep "$poll"` 한 줄이 없거나 다른 sleep 이 있음')
    for wanted in ('poll="${AUTOPR_POLL_SECONDS:-30}"', 'limit="${AUTOPR_MAX_WAIT_SECONDS:-2400}"',
                   '[[ "$poll" =~ ^[0-9]{1,4}$ ]] || poll=30', '[[ "$limit" =~ ^[0-9]{1,5}$ ]] || limit=2400'):
        if wanted not in lines:
            problems.append(f"기다림 간격·한도의 기본값 줄이 정해진 것과 다름: {wanted}")
    # 제목·본문 한도: 제목은 접두사만이면 거절·200자(글자) 초과 거절·제어 문자 거절, 본문은 6만 바이트(`wc -c`) 초과면 비움
    if 'if [ "${#title}" -le "${#prefix}" ] || [ "${#title}" -gt 200 ] || [[ "$title" == *[[:cntrl:]]* ]]; then' not in lines:
        problems.append("제목 검사 줄(접두사만·200자 초과·제어 문자)이 정해진 것과 다름")
    if 'if [ "$(wc -c < "$body")" -gt 60000 ]; then' not in lines:
        problems.append("본문 6만 바이트 한도 줄이 정해진 것과 다름")
    # 윈도의 Git Bash 는 명령 치환에서 CR 을 스스로 지워 동작 시험이 이 줄을 못 지키므로 글자로 못박는다
    if "tr -d '\\r' < \"$msg\" > \"$lf\"" not in lines:
        problems.append("커밋 메시지의 CR 제거 줄이 없음")
    return problems


def static_problems(text, ci_workflow=CI_WORKFLOW):
    """워크플로 글의 모양이 규칙과 다른 곳의 목록(없으면 빈 목록). 아래 시험이 진짜 파일에는 빈 목록을, 일부러 망가뜨린 사본에는 비어 있지 않은 목록을 기대한다."""
    problems = []
    head, run = split_workflow(text)
    wanted = [line.replace("CI_WORKFLOW: ci.yml", "CI_WORKFLOW: " + ci_workflow) for line in EXPECTED_HEAD]
    got = code_lines(head)
    if got != wanted:
        extra = [line for line in got if line not in wanted]
        missing = [line for line in wanted if line not in got]
        problems.append(f"스크립트 앞 설정이 정해진 줄과 다름: 더해진 줄 {extra[:3]} 빠진 줄 {missing[:3]}" if extra or missing else "스크립트 앞 설정의 줄 순서가 다름")
    if not run:
        problems.append("run 스크립트(`run: |` 한 곳)를 찾지 못함")
        return problems
    if "${{" in run:
        problems.append("run 안에 ${{ }} 가 있음")
    code = code_text(text)
    for reason, rx in FORBIDDEN:
        found = rx.search(code)
        if found:
            problems.append(f"{reason}: {found.group(0)!r}")
    verbs = re.findall(r"\bgh\s+([a-z-]+)", run)
    if set(verbs) != {"api", "pr"}:
        problems.append(f"gh 하위 명령이 api·pr 뿐이 아님: {sorted(set(verbs))}")
    if re.findall(r"\bgh\s+pr\s+([a-z-]+)", run) != ["list"]:
        problems.append("gh pr 는 list 한 번뿐이어야 함")
    # 기존 PR 확인(`check_no_pr`)은 기다리기 전과 PR 만들기 바로 앞, 두 번 부른다(기다리는 사이 운영자가 직접 PR 을 만들었을 수 있다)
    calls = [index for index, line in enumerate(run.splitlines()) if line.strip() == "check_no_pr"]
    if len(calls) != 2 or run.count("check_no_pr()") != 1:
        problems.append("check_no_pr 는 정의 한 번·호출 두 번이어야 함")
    elif not (run.index("\ndone\n") < run.rindex("\ncheck_no_pr\n") < run.index("-X POST")):
        problems.append("두 번째 check_no_pr 호출이 기다림 반복문 뒤·PR 만들기 앞에 있어야 함")
    if re.findall(r'\bgh\s+api\s+(?:-X\s+POST\s+)?"([^"]+)"', run) != ENDPOINTS:
        problems.append("gh api 주소가 정해진 다섯 가지(순서까지)와 다름")
    if len(re.findall(r"\bgh\s+api\b", run)) != 5 or len(re.findall(r"-X\s+POST\b", run)) != 1 or len(re.findall(r"-X\b", run)) != 1:
        problems.append("gh api 호출이 다섯 번(그중 POST 하나)이 아님")
    if not re.search(r'-X POST "repos/\$\{REPO\}/pulls" -f "title=\$\{title\}" -f "head=\$\{BRANCH\}" -f "base=\$\{BASE\}" -F "body=@\$\{body\}" --jq \.number', run):
        problems.append("PR 만들기 호출의 모양이 정해진 것과 다름")
    problems += script_problems(run)
    return problems


class WorkflowShapeTest(unittest.TestCase):
    def setUp(self):
        self.text = workflow_text()

    def test_the_real_file_has_no_static_problem(self):
        self.assertEqual(static_problems(self.text), [])

    def test_the_part_before_the_script_is_exactly_the_expected_lines(self):
        head, run = split_workflow(self.text)
        self.assertEqual(code_lines(head), EXPECTED_HEAD)
        self.assertTrue(run.startswith("set -euo pipefail\n"))

    def test_the_trigger_is_one_push_with_exactly_the_two_merge_branch_filters(self):
        self.assertEqual(block(self.text, "on"), ["  push:", "    branches:", "      - 'ai/claude/M[0-9][0-9][0-9]-*'", "      - 'ai/claude/M[0-9][0-9][0-9][0-9]-*'"])
        for forbidden in ("pull_request", "pull_request_target", "workflow_run", "issue_comment", "schedule", "workflow_dispatch", "issues", "release", "create"):
            self.assertNotIn(forbidden + ":", "\n".join(block(self.text, "on")), forbidden)

    def test_permissions_are_the_three_and_there_is_no_write_to_contents(self):
        self.assertEqual(block(self.text, "permissions"), ["  contents: read", "  pull-requests: write", "  actions: read"])
        self.assertEqual(block(self.text, "concurrency"), ["  group: auto-pr-${{ github.ref }}", "  cancel-in-progress: true"])
        self.assertEqual(len(re.findall(r"^\s*permissions:", code_text(self.text), re.M)), 1)      # 잡이 더 넓은 권한을 달라고 하지 않는다
        self.assertIn("    timeout-minutes: 45", self.text)

    def test_names_are_korean_and_the_workflow_has_no_run_name(self):
        self.assertIn(f'name: "{NAME}"', self.text)
        self.assertRegex(self.text, r"\n    name: [^\n]*[가-힣]")
        self.assertRegex(self.text, r"\n      - name: [^\n]*[가-힣]")
        self.assertNotIn("run-name:", code_text(self.text))

    def test_there_is_no_uses_at_all_so_the_pinning_test_has_nothing_to_catch(self):
        """`tests/test_repo_layout.py` 의 고정 시험이 쓰는 찾기 규칙으로 봐도 `uses:` 가 하나도 없다(체크아웃도 없다)."""
        self.assertEqual(re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", self.text, re.M), [])
        self.assertNotIn("checkout", code_text(self.text))

    def test_every_dollar_brace_expression_is_in_the_env_or_the_concurrency_group_only(self):
        expressions = re.findall(r"\$\{\{.*?\}\}", code_text(self.text))
        self.assertEqual(sorted(expressions), sorted(["${{ github.ref }}", "${{ github.token }}", "${{ github.repository }}", "${{ github.ref_name }}", "${{ github.sha }}",
                                                      "${{ github.event.repository.default_branch }}"]))
        self.assertNotIn("${{", script_of(self.text))

    def test_the_script_never_prints_the_branch_title_body_or_api_answers(self):
        """echo·printf 로 찍는 것은 고정 문장·PR 번호·검사 상태 낱말(`num`·`ahead` 는 모양을 확인한 숫자·번호)뿐 — 제목·본문·가지 이름·응답 원문 변수는 출력에 쓰지 않는다."""
        run = script_of(self.text)
        printed = [line for line in run.splitlines() if re.match(r"\s*(note|warn|summary|finish)\b", line)]
        self.assertGreaterEqual(len(printed), 20)
        for line in printed:
            for name in ("title", "body", "BRANCH", "head_now", "run_state", "msg", "lf", "err", "GH_TOKEN"):
                self.assertNotRegex(line, rf"\$\{{?{name}\b", line)
        self.assertNotRegex(run, r"\bcat\b[^\n]*\$(\{?)(msg|lf|body|err)\b")        # 글 파일을 그대로 찍지 않는다
        self.assertNotRegex(run, r"set -x|xtrace")

    def test_each_value_is_checked_before_use_and_every_gh_call_has_its_jq(self):
        run = script_of(self.text)
        self.assertEqual(re.findall(r"--jq (\S+)", run), [".message", "length", ".object.sha", '"$runs_jq"', ".ahead_by", ".number"])
        self.assertIn(f"runs_jq='{RUNS_JQ}'", run)
        self.assertIn("gh pr list --repo \"$REPO\" --head \"$BRANCH\" --state all --json number --jq length", run)
        for rx in ("re_repo", "re_base", "re_workflow", "re_sha", "re_zero", "re_branch"):
            self.assertIn(rx + "=", run)
        self.assertLess(run.index("re_branch="), run.index("gh api"))                  # 값 확인(1단계)이 첫 gh 호출보다 앞선다
        self.assertLess(run.index("re_sha="), run.index("gh api"))

    def test_the_other_workflow_is_not_touched_by_this_change_in_the_ways_the_layout_test_cares_about(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(block(ci, "on"), ["  push:", "  workflow_dispatch:"])                # D-28: ci.yml 은 push·수동뿐(이 워크플로를 더해도 그대로)
        self.assertEqual(block(ci, "concurrency")[0], "  group: ci-${{ github.event_name }}-${{ github.ref }}")
        self.assertNotEqual(block(ci, "concurrency")[0], block(self.text, "concurrency")[0])   # 서로를 취소하거나 기다리게 하지 않는다


class MutationTest(unittest.TestCase):
    """같은 모양 검사를 일부러 틀리게 만든 사본에 돌려 모두 잡는지 본다(살아남는 변이가 있으면 그 검사가 허술한 것)."""

    def mutations(self):
        text = workflow_text()
        yield "pull_request_target 트리거 추가", text.replace("on:\n  push:", "on:\n  pull_request_target:\n  push:", 1)
        yield "schedule 트리거 추가", text.replace("on:\n  push:", "on:\n  schedule:\n    - cron: '0 * * * *'\n  push:", 1)
        yield "workflow_run 트리거 추가", text.replace("on:\n  push:", "on:\n  workflow_run:\n    workflows: ['x']\n  push:", 1)
        yield "가지 필터를 넓힘", text.replace("      - 'ai/claude/M[0-9][0-9][0-9]-*'\n", "      - 'ai/claude/**'\n", 1)
        yield "contents 쓰기 권한", text.replace("  contents: read\n", "  contents: write\n", 1)
        yield "issues 쓰기 권한 추가", text.replace("  actions: read\n", "  actions: read\n  issues: write\n", 1)
        yield "동시 실행 취소 끔", text.replace("cancel-in-progress: true", "cancel-in-progress: false", 1)
        yield "시간 제한 삭제", text.replace("    timeout-minutes: 45\n", "", 1)
        yield "외부 액션 단계 추가", text.replace("    steps:\n", "    steps:\n      - uses: actions/checkout@v6\n", 1)
        yield "시크릿 사용", text.replace("GH_TOKEN: ${{ github.token }}", "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}", 1)
        yield "run 안에 이벤트 값 보간", text.replace("          set -euo pipefail\n", "          set -euo pipefail\n          echo \"${{ github.event.head_commit.message }}\"\n", 1)
        yield "병합 호출 추가", text.rstrip("\n") + "\n          gh pr merge \"$number\" --squash\n"
        yield "병합 방식 필드 추가", text.replace('-F "body=@${body}"', '-F "body=@${body}" -f merge_method=squash', 1)
        yield "다른 HTTP 호출 추가", text.rstrip("\n") + "\n          gh api -X PUT \"repos/${REPO}/pulls/1/merge\"\n"
        yield "검사 워크플로 이름 바꿈", text.replace("CI_WORKFLOW: ci.yml", "CI_WORKFLOW: evil.yml", 1)
        yield "eval 로 제목 실행", text.rstrip("\n") + "\n          eval \"$title\"\n"
        yield "다른 gh 하위 명령(코멘트)", text.rstrip("\n") + "\n          gh pr comment 1 --body-file \"$body\"\n"
        yield "단계에 if 추가", text.replace("      - name: 병합 부탁 PR 만들기(병합은 하지 않음)\n", "      - name: 병합 부탁 PR 만들기(병합은 하지 않음)\n        if: always()\n", 1)
        yield "PR 만들기 앞의 두 번째 기존 PR 확인 삭제", text.replace("          check_no_pr\n          if number=", "          if number=", 1)

    def test_every_mutation_is_caught(self):
        original = workflow_text()
        self.assertEqual(static_problems(original), [])
        count = 0
        for label, mutated in self.mutations():
            count += 1
            with self.subTest(label):
                self.assertNotEqual(mutated, original, f"변이가 글을 바꾸지 못했다: {label}")
                self.assertTrue(static_problems(mutated), f"살아남은 변이: {label}")
        self.assertEqual(count, 19)

    def added_mutations(self):
        """독립 검증(2026-11-07)이 변이로 찾아낸 시험 틈을 메운 뒤의 추가 변이 — 앵커·숫자 확인·쉬는 줄·기본값·로캘·본문 한도·검사 결론·엄격 모드·deny-list(`perl`)."""
        text = workflow_text()
        cr = "tr -d '\\r' < \"$msg\" > \"$lf\""
        yield "perl 로 제목 실행", text.rstrip("\n") + "\n          perl -e 'system($ENV{TITLE})'\n"
        yield "엄격 모드 약화(-e 뺌)", text.replace("          set -euo pipefail\n", "          set -uo pipefail\n", 1)
        yield "set +e 추가", text.replace("          set -euo pipefail\n", "          set -euo pipefail\n          set +e\n", 1)
        yield "오류를 `|| true` 로 삼킴", text.replace(cr, cr + " || true", 1)
        yield "trap 추가", text.replace("          note() { echo", "          trap 'exit 0' ERR\n          note() { echo", 1)
        yield "로캘 고정 삭제", text.replace("          export LC_ALL=C.UTF-8\n", "", 1)
        yield "로캘을 C 로 고정", text.replace("export LC_ALL=C.UTF-8", "export LC_ALL=C", 1)
        yield "기다림 반복문의 sleep 삭제", text.replace('            sleep "$poll"\n', "", 1)
        yield "sleep 간격을 1초로 고정", text.replace('sleep "$poll"', "sleep 1", 1)
        yield "기본 간격 30 → 0", text.replace("|| poll=30", "|| poll=0", 1)
        yield "기본 한도 2400 → 240000", text.replace("|| limit=2400", "|| limit=240000", 1)
        yield "가지 정규식 앞 ^ 삭제", text.replace("re_branch='^ai/claude/", "re_branch='ai/claude/", 1)
        yield "가지 정규식 끝 $ 삭제", text.replace("{1,80}$'", "{1,80}'", 1)
        yield "SHA 정규식 앞 ^ 삭제", text.replace("re_sha='^[0-9a-f]{40}$'", "re_sha='[0-9a-f]{40}$'", 1)
        yield "SHA 정규식 끝 $ 삭제", text.replace("re_sha='^[0-9a-f]{40}$'", "re_sha='^[0-9a-f]{40}'", 1)
        yield "ahead_by 숫자 확인 삭제", text.replace(' || [[ ! "$ahead" =~ ^[0-9]+$ ]]', "", 1)
        yield "기존 PR 수 숫자 확인 삭제", text.replace(' || [[ ! "$existing" =~ ^[0-9]+$ ]]', "", 1)
        yield "neutral 을 성공으로", text.replace("                completed:success)\n", "                completed:success|completed:neutral)\n", 1)
        yield "skipped 를 성공으로", text.replace("                completed:success)\n", "                completed:success|completed:skipped)\n", 1)
        yield "본문 6만 바이트 한도 삭제", text.replace('[ "$(wc -c < "$body")" -gt 60000 ]', "false", 1)
        yield "본문 한도 6천만 바이트로", text.replace("-gt 60000 ]", "-gt 60000000 ]", 1)
        yield "CR 제거 삭제", text.replace(cr, 'cp "$msg" "$lf"', 1)

    def test_every_added_mutation_is_caught(self):
        original = workflow_text()
        self.assertEqual(static_problems(original), [])
        count = 0
        for label, mutated in self.added_mutations():
            count += 1
            with self.subTest(label):
                self.assertNotEqual(mutated, original, f"변이가 글을 바꾸지 못했다: {label}")
                self.assertTrue(static_problems(mutated), f"살아남은 변이: {label}")
        self.assertEqual(count, 22)


# ----------------------------------------------------------------------------
# 가지 필터(GitHub 글로브) ↔ 스크립트의 정규식
# ----------------------------------------------------------------------------
def glob_to_regex(pattern):
    """GitHub 브랜치 필터 글로브를 정규식으로: `*` 은 `/` 를 넘지 않고 `**` 는 넘으며 `[0-9]` 같은 문자 범위(a-z·A-Z·0-9)를 쓴다. `?`·`+` 는 이 시험이 계산하지 않는다."""
    assert "?" not in pattern and "+" not in pattern and not pattern.startswith("!"), pattern
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        char = pattern[i]
        if char == "*":
            out.append("[^/]*")
        elif char == "[":
            end = pattern.index("]", i)
            out.append(pattern[i:end + 1])
            i = end
        else:
            out.append(re.escape(char))
        i += 1
    return "".join(out)


def script_branch_regex():
    found = re.search(r"^re_branch='([^']+)'$", script_of(), re.M)
    assert found, "스크립트에서 re_branch 를 찾지 못했다"
    return re.compile(found.group(1))


class BranchSelectionTest(unittest.TestCase):
    #  (가지 이름, 필터가 받는가, 스크립트 정규식이 받는가)
    CASES = [
        ("ai/claude/M004-health-fit-2", True, True),
        ("ai/claude/M0045-x", True, True),
        ("ai/claude/M123-a.b_c-d", True, True),
        ("ai/claude/M999-x", True, True),
        ("ai/claude/M004-" + "a" * 80, True, True),
        ("ai/claude/M004-" + "a" * 81, True, False),                 # 정규식이 더 엄격(이름 80자 상한)
        ("ai/claude/M004-", True, False),                            # 이름이 비면 정규식이 거절
        ("ai/claude/M004-한글", True, False),                        # 영문·숫자·`.`·`_`·`-` 밖의 글자는 정규식이 거절
        ("ai/claude/M004-x;touch", True, False),                     # 필터의 `*` 은 `;`·공백도 받지만 정규식은 거절(끝 `$` 가 값 전체를 보게 한다)
        ("ai/claude/M004-x y", True, False),
        ("xai/claude/M004-x", False, False),                         # 앞에 글자가 붙은 이름은 필터도 정규식(앞 `^`)도 거절
        ("ai/claude/M004-x/y", False, False),                        # `*` 은 `/` 를 넘지 못한다
        ("ai/claude/M04-short", False, False),
        ("ai/claude/M00045-x", False, False),
        ("ai/claude/M004", False, False),
        ("ai/claude/M004_x", False, False),
        ("ai/claude/m004-x", False, False),
        ("ai/claude/NO-MERGE-operator-requests", False, False),
        ("ai/claude/R-001-x", False, False),
        ("ai/claude/blog-ci-precheck", False, False),
        ("ai/claude/x/M004-y", False, False),
        ("ai/codex/M004-x", False, False),
        ("ai/draft/M004-x", False, False),
        ("copilot/M004-x", False, False),
        ("issue-edit/M004-x", False, False),
        ("main", False, False),
    ]

    def test_the_filter_and_the_regex_pick_the_same_branches_and_the_regex_is_never_wider(self):
        filters = [re.compile(glob_to_regex(pattern)) for pattern in FILTERS]
        regex = script_branch_regex()
        for name, by_filter, by_regex in self.CASES:
            with self.subTest(name[:40]):
                self.assertEqual(any(rx.fullmatch(name) for rx in filters), by_filter)
                self.assertEqual(regex.search(name) is not None, by_regex)       # bash 의 `=~` 처럼 '검색'으로 본다 — 앵커가 없으면 부분만 맞아도 통과해 이 줄이 빨개진다
                if by_regex:
                    self.assertTrue(by_filter)                       # 정규식이 받은 가지는 반드시 필터도 받아 이 워크플로가 시작한 것이다

    def test_the_regex_extracts_the_number_and_nothing_else(self):
        regex = script_branch_regex()
        self.assertEqual(regex.search("ai/claude/M004-x").group(1), "M004")
        self.assertEqual(regex.search("ai/claude/M1234-x").group(1), "M1234")
        self.assertEqual(regex.groups, 1)
        self.assertTrue(regex.pattern.startswith("^") and regex.pattern.endswith("$"))        # 값 전체를 보는 앵커

    def test_this_workflow_starts_only_for_merge_branches(self):
        """AI 브랜치 push 에 반응하는 이 워크플로는 병합 가지에만 시작하고, 요청 전용 가지(`NO-MERGE-…`)·그 밖의 `ai/claude/…` 에는 시작하지 않는다(`ci.yml` 은 모든 가지에서 돈다 — D-28)."""
        filters = [re.compile(glob_to_regex(pattern)) for pattern in FILTERS]
        self.assertTrue(any(rx.fullmatch("ai/claude/M004-health-fit-2") for rx in filters))
        for request_branch in ("ai/claude/NO-MERGE-operator-requests", "ai/claude/operator-requests-2", "ai/claude/blog-ci-precheck", "ai/claude/M04-short"):
            self.assertFalse(any(rx.fullmatch(request_branch) for rx in filters), request_branch)


# ----------------------------------------------------------------------------
# 동작 — 진짜 bash 로 `run:` 을 돌린다(가짜 gh 는 셸 함수)
# ----------------------------------------------------------------------------
def find_bash():
    if os.name != "nt":
        return shutil.which("bash")
    candidates = []
    git = shutil.which("git")
    if git:
        top = Path(git).resolve().parent.parent
        candidates += [top / "bin" / "bash.exe", top / "usr" / "bin" / "bash.exe"]
    for name in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(name):
            candidates.append(Path(os.environ[name]) / "Git" / "bin" / "bash.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


BASH = find_bash()
needs_bash = unittest.skipUnless(BASH, "bash 가 없어 단계의 셸 스크립트를 돌려 보지 못했다(Actions 의 ubuntu 에는 있다)")

# 가짜 gh: 셸 함수라 PATH·실행 비트·윈도 경로 문제가 없다. 부른 인자를 `calls.log` 에 한 줄씩(`CALL`, 이어서 인자마다 `ARG …`) 남기고,
# 응답은 `$FAKE_DIR` 의 파일이 정한다: `*.seq`(부를 때마다 한 줄씩, 모자라면 마지막 줄, `FAIL` 이면 실패), `message.txt`, `post_mode.txt`.
FAKE_GH = r'''
# 가짜 sleep: 실제로 쉬지 않고 쉰 초를 `sleeps.log` 에 남기며 bash 의 시계(SECONDS)만 가상 시계(FAKE_CLOCK)만큼 앞으로 돌린다 — 기다림 반복문의 간격·한도를 시간 걸리지 않게,
# 이 PC 의 느린 프로세스 생성 시간(실제 흐른 시간)에 흔들리지 않게 시험한다(첫 호출 때 현재 SECONDS 에서 시작해 부를 때마다 받은 초만 더한다).
sleep() {
  printf '%s\n' "$1" >> "$FAKE_DIR/sleeps.log"
  FAKE_CLOCK=$(( ${FAKE_CLOCK:-$SECONDS} + $1 ))
  SECONDS=$FAKE_CLOCK
}
fake_next() {
  local file="$FAKE_DIR/$1.count" n=0
  if [ -f "$file" ]; then read -r n < "$file"; fi
  n=$((n + 1))
  echo "$n" > "$file"
  FAKE_N="$n"
}
fake_pick() {
  local line last="" i=0
  fake_next "$1"
  while IFS= read -r line || [ -n "$line" ]; do
    i=$((i + 1))
    last="$line"
    if [ "$i" -eq "$FAKE_N" ]; then break; fi
  done < "$FAKE_DIR/$1.seq"
  if [ "$last" = FAIL ]; then return 1; fi
  printf '%s\n' "$last"
}
gh() {
  local arg mode
  { echo CALL; for arg in "$@"; do printf 'ARG %s\n' "$arg"; done; } >> "$FAKE_DIR/calls.log"
  case "$1" in
    pr) fake_pick prlist ;;
    api)
      case "$2" in
        -X)
          for arg in "$@"; do
            case "$arg" in body=@*) cp "${arg#body=@}" "$FAKE_DIR/posted_body.txt" ;; esac
          done
          read -r mode < "$FAKE_DIR/post_mode.txt"
          case "$mode" in
            ok) echo 77 ;;
            weird) echo "not-a-number" ;;
            forbidden) echo "gh: GitHub Actions is not permitted to create or approve pull requests. (HTTP 403)" >&2; return 1 ;;
            exists) echo "gh: Validation Failed: A pull request already exists for x:y. (HTTP 422)" >&2; return 1 ;;
            *) echo "gh: Server Error (HTTP 500)" >&2; return 1 ;;
          esac
          ;;
        repos/*/git/commits/*)
          if [ -f "$FAKE_DIR/message_fail" ]; then return 1; fi
          cat "$FAKE_DIR/message.txt"
          ;;
        repos/*/git/ref/heads/*) fake_pick head ;;
        repos/*/actions/workflows/*) fake_pick runs ;;
        repos/*/compare/*) fake_pick ahead ;;
        *) echo "unexpected gh api: $2" >&2; return 99 ;;
      esac
      ;;
    *) echo "unexpected gh: $1" >&2; return 99 ;;
  esac
}
'''

REPO = "octo/desktop"
BRANCH = "ai/claude/M004-health-fit-2"
SHA = "a" * 39 + "1"
OTHER_SHA = "b" * 39 + "2"
TITLE = "[M004] 건강 조합 규칙 보완 [대상: 공통]"
BODY = "바꾼 곳\n- 하나\n- 둘\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>\n"
MESSAGE = TITLE + "\n\n" + BODY


class Result:
    def __init__(self, code, out, folder):
        self.code, self.out, self.folder = code, out, Path(folder)
        raw = (self.folder / "calls.log").read_bytes().decode("utf-8", "replace") if (self.folder / "calls.log").exists() else ""
        self.calls, current = [], None
        for line in raw.splitlines():
            if line == "CALL":
                current = []
                self.calls.append(current)
            elif line.startswith("ARG ") and current is not None:
                current.append(line[4:])
        posted = self.folder / "posted_body.txt"
        self.posted_body = posted.read_bytes().decode("utf-8") if posted.exists() else None
        summary = self.folder / "summary.md"
        self.summary = summary.read_bytes().decode("utf-8", "replace") if summary.exists() else ""
        sleeps = self.folder / "sleeps.log"
        self.sleeps = sleeps.read_bytes().decode("utf-8").split() if sleeps.exists() else []     # 가짜 sleep 이 받은 초(문자열) 목록
        self.kinds = [self.kind(call) for call in self.calls]

    @staticmethod
    def kind(call):
        if call[0] == "pr":
            return "pr_list"
        path = call[1]
        for needle, name in (("/git/commits/", "commits"), ("/git/ref/heads/", "ref"), ("/actions/workflows/", "runs"), ("/compare/", "compare")):
            if needle in path:
                return name
        return "post" if path == "-X" else "other"

    def count(self, kind):
        return self.kinds.count(kind)

    def warnings(self):
        return [line for line in self.out.splitlines() if line.startswith("::warning::")]

    def post(self):
        return next(call for call in self.calls if self.kind(call) == "post")

    def posted_title(self):
        return next(arg for arg in self.post() if arg.startswith("title="))


def to_text(value):
    return value if isinstance(value, str) else "\n".join(value) + "\n"


@needs_bash
class BehaviorTest(unittest.TestCase):
    """사례마다 진짜 bash 로 스크립트를 한 번 돌린다(이 PC 에서는 프로세스 하나가 수백 ms 라 사례당 몇 초). 같은 사례는 클래스에서 한 번만 돌려 여러 시험이 읽는다."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.tmp = Path(cls._tmp.name)
        cls.script = script_of().replace("\r\n", "\n")
        cls.cache, cls.serial = {}, 0

    def run_case(self, key, message=MESSAGE, branch=BRANCH, sha=SHA, prlist="0", head=None, runs=("completed:success",), ahead=("1",), post="ok",
                 poll="1", wait="60", message_fail=False, extra=None, drop=(), locale="C"):
        cache = type(self).cache
        if key in cache:
            return cache[key]
        type(self).serial += 1
        folder = self.tmp / f"case{self.serial}"
        runner, work = folder / "runner", folder / "work"
        for path in (folder, runner, work):
            path.mkdir(parents=True)
        (folder / "message.txt").write_bytes(message.encode("utf-8"))
        (folder / "prlist.seq").write_bytes(to_text([prlist] if isinstance(prlist, str) else prlist).encode("utf-8"))
        (folder / "head.seq").write_bytes(to_text(head or [sha]).encode("utf-8"))
        (folder / "runs.seq").write_bytes(to_text(runs).encode("utf-8"))
        (folder / "ahead.seq").write_bytes(to_text(ahead).encode("utf-8"))
        (folder / "post_mode.txt").write_bytes((post + "\n").encode("utf-8"))
        if message_fail:
            (folder / "message_fail").write_bytes(b"")
        step = folder / "step.sh"
        step.write_bytes((FAKE_GH + self.script).replace("\r\n", "\n").encode("utf-8"))
        env = dict(os.environ)
        for name in list(env):
            if name.startswith(("GITHUB_", "RUNNER_", "AUTOPR_", "INPUT_", "FAKE_", "LC_")) or name in ("LANG", "LANGUAGE", "GH_TOKEN", "GH_REPO", "REPO", "BRANCH", "SHA", "BASE", "CI_WORKFLOW"):
                del env[name]                                   # 이 시험을 Actions 안에서 돌려도 러너의 값(로캘 포함)이 새어 들지 않게
        env.update(GH_TOKEN="not-a-real-token", REPO=REPO, BRANCH=branch, SHA=sha, BASE="main", CI_WORKFLOW=CI_WORKFLOW,
                   AUTOPR_POLL_SECONDS=poll, AUTOPR_MAX_WAIT_SECONDS=wait, RUNNER_TEMP=runner.as_posix(),
                   GITHUB_STEP_SUMMARY=(folder / "summary.md").as_posix(), FAKE_DIR=folder.as_posix())
        if locale is not None:
            env["LC_ALL"] = env["LANG"] = locale                # 기본은 바이트로 세는 가장 불리한 로캘(`C`) — 스크립트가 스스로 UTF-8 로 고정해야 통과한다. None 이면 로캘 변수를 아예 주지 않는다(환경 기본값)
        for name, value in (extra or {}).items():
            env[name] = value
        for name in drop:
            env.pop(name, None)
        proc = subprocess.run([BASH, step.as_posix()], cwd=work, env=env, capture_output=True, timeout=180, stdin=subprocess.DEVNULL)
        out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
        result = Result(proc.returncode, out, folder)
        result.work = work
        cache[key] = result
        return result

    # ---- 정상 --------------------------------------------------------------
    def test_normal_case_creates_exactly_one_pull_request_and_nothing_else(self):
        r = self.run_case("normal")
        self.assertEqual(r.code, 0, r.out)
        self.assertEqual(r.kinds, ["commits", "pr_list", "ref", "runs", "compare", "pr_list", "post"])      # 기존 PR 확인은 기다리기 전과 PR 만들기 바로 앞, 두 번
        self.assertEqual(r.calls[0], ["api", f"repos/{REPO}/git/commits/{SHA}", "--jq", ".message"])
        self.assertEqual(r.calls[1], ["pr", "list", "--repo", REPO, "--head", BRANCH, "--state", "all", "--json", "number", "--jq", "length"])
        self.assertEqual(r.calls[2], ["api", f"repos/{REPO}/git/ref/heads/{BRANCH}", "--jq", ".object.sha"])
        self.assertEqual(r.calls[3], ["api", f"repos/{REPO}/actions/workflows/{CI_WORKFLOW}/runs?head_sha={SHA}&event=push&per_page=5", "--jq", RUNS_JQ])
        self.assertEqual(r.calls[4], ["api", f"repos/{REPO}/compare/main...{SHA}", "--jq", ".ahead_by"])
        self.assertEqual(r.calls[5], r.calls[1])
        post = r.post()
        self.assertEqual(post[:4], ["api", "-X", "POST", f"repos/{REPO}/pulls"])
        self.assertEqual(post[4:12], ["-f", "title=" + TITLE, "-f", f"head={BRANCH}", "-f", "base=main", "-F", post[11]])
        self.assertRegex(post[11], r"^body=@.*autopr-body\.txt$")
        self.assertEqual(post[12:], ["--jq", ".number"])
        self.assertEqual(r.posted_body, BODY)                                  # 본문은 커밋 본문 그대로(맨 앞 빈 줄만 뗀다)
        self.assertIn("PR #77", r.out)
        self.assertIn("PR #77", r.summary)
        self.assertEqual(r.warnings(), [])

    def test_nothing_that_is_not_a_pull_request_creation_is_ever_called_and_the_log_stays_clean(self):
        r = self.run_case("normal")
        for call in r.calls:
            self.assertIn(call[0], ("api", "pr"))
        self.assertEqual(r.count("post"), 1)
        for needle in ("not-a-real-token", TITLE, "Co-Authored-By", "건강 조합"):
            self.assertNotIn(needle, r.out)                                    # 토큰·제목·본문은 로그에 찍지 않는다
            self.assertNotIn(needle, r.summary)
        self.assertFalse(any(path.is_file() for path in r.work.iterdir()), "작업 폴더에 파일을 만들었다")

    # ---- 글을 셸이 해석하지 않는다 ---------------------------------------------
    def test_title_and_body_with_shell_characters_are_passed_through_verbatim(self):
        title = "[M004] 제목 $(touch PWNED1) `touch PWNED2` \"큰\" '작은' ; touch PWNED3 && echo x | cat > PWNED4 \\ * ? {a,b} ${HOME} %PATH% <&> #끝"
        body = ("본문 첫 줄 $(touch PWNED5)\n`touch PWNED6`\n\"인용\" '따옴표' ; & | > < \\ \\n $HOME ${HOME}\n::warning::가짜 경고\n::error::가짜 오류\n"
                "##[group]가짜\n$((1+1)) $'x' ~ * [a-z]* !! \\$HOME\n\nCo-Authored-By: X <x@example.com>\n")
        r = self.run_case("shell_chars", message=title + "\n\n" + body)
        self.assertEqual(r.code, 0, r.out)
        self.assertEqual(r.posted_title(), "title=" + title)                    # 한 글자도 바뀌지 않았다
        self.assertEqual(r.posted_body, body)
        for folder in (r.work, r.folder, r.folder / "runner"):
            self.assertEqual([p.name for p in folder.iterdir() if p.name.startswith("PWNED")], [], folder)
        for needle in ("가짜 경고", "가짜 오류", "가짜", "PWNED", "touch"):
            self.assertNotIn(needle, r.out)                                    # 글이 워크플로 명령 줄이 되지도 않는다
        self.assertEqual(r.warnings(), [])

    def test_crlf_message_with_blank_lines_up_front_gives_a_clean_title_and_body(self):
        # 한계: Windows 의 Git Bash(cygwin 계열)는 명령 치환과 awk 에서 CR 을 스스로 지워 스크립트의 `tr -d '\r'` 가 없어도 이 시험이 통과한다(변이로 확인).
        # 리눅스(Actions 의 ubuntu)에서는 CR 이 남아 제목이 제어 문자 검사에 걸리므로 이 시험이 `tr` 를 지키는 쪽은 리눅스다.
        r = self.run_case("crlf", message=TITLE + "\r\n\r\n\r\n본문 하나\r\n\r\n본문 둘\r\n")
        self.assertEqual(r.code, 0, r.out)
        self.assertEqual(r.posted_title(), "title=" + TITLE)                    # 제목 끝에 \r 이 남지 않는다
        self.assertEqual(r.posted_body, "본문 하나\n\n본문 둘\n")

    def test_a_one_line_message_posts_an_empty_body(self):
        r = self.run_case("one_line", message=TITLE + "\n")
        self.assertEqual(r.code, 0, r.out)
        self.assertEqual(r.count("post"), 1)
        self.assertEqual(r.posted_body, "")

    def test_a_title_of_exactly_200_characters_is_allowed_and_201_is_not(self):
        ok = "[M004] " + "x" * (200 - len("[M004] "))
        too_long = ok + "x"
        r200 = self.run_case("t200", message=ok + "\n\n본문\n")
        self.assertEqual((r200.code, r200.count("post")), (0, 1), r200.out)
        r201 = self.run_case("t201", message=too_long + "\n\n본문\n")
        self.assertEqual((r201.code, r201.count("post")), (0, 0), r201.out)
        self.assertEqual(len(r201.warnings()), 1)

    def test_a_long_korean_title_is_counted_in_characters_whatever_the_locale_of_the_runner(self):
        """제목 길이는 글자 수로 센다(한도 200자). 바이트로 세는 로캘(`C`·`POSIX`·로캘 변수 없음)에서도 결과가 같아야 한다 — 스크립트가 스스로 UTF-8 로 고정한다
        (한국어는 글자당 3바이트라 실제 병합 제목도 바이트로는 200 을 넘는다: R-172 193바이트·M006 208바이트). 이 시험은 실행 환경의 로캘을 일부러 불리하게 준다."""
        long_title = "[M004] " + "병합 표기 규칙을 바꾸는 긴 제목 " * 6 + "[대상: 공통]"
        korean_200 = "[M004] " + "한" * 193
        korean_201 = "[M004] " + "한" * 194
        self.assertEqual((len(long_title), len(long_title.encode("utf-8"))), (129, 293))              # 글자로는 200 이내, 바이트로는 200 을 넘는 제목
        self.assertEqual((len(korean_200), len(korean_201)), (200, 201))
        for locale in ("C", "POSIX", None, "C.UTF-8"):
            for name, title, created in (("long", long_title, True), ("k200", korean_200, True), ("k201", korean_201, False)):
                if locale == "C.UTF-8" and name != "long":
                    continue
                with self.subTest(locale=locale, title=name):
                    r = self.run_case(f"locale_{locale}_{name}", message=title + "\n\n본문\n", locale=locale)
                    self.assertEqual(r.code, 0, r.out)
                    if created:
                        self.assertEqual(r.count("post"), 1, r.out)
                        self.assertEqual(r.posted_title(), "title=" + title)
                    else:
                        self.assertEqual((r.count("post"), len(r.warnings())), (0, 1), r.out)

    def test_a_body_over_60000_bytes_is_left_empty_and_exactly_60000_is_kept(self):
        """본문 한도는 글자가 아니라 바이트(`wc -c`)다. 줄 끝 개행까지 센다: `x`×59999 + 개행 = 60000바이트는 그대로, 한 바이트만 넘으면 본문을 비운다(제목은 그대로 PR 이 만들어진다)."""
        cases = (("body_exact", "x" * 59999 + "\n", True), ("body_over", "x" * 60000 + "\n", False), ("body_huge", "y" * 70000 + "\n", False),
                 ("body_korean", "한" * 20000 + "\n", False))              # 글자로는 20001 이라 글자로 세면 남는다 — 바이트로 60001
        for key, body, kept in cases:
            with self.subTest(key):
                r = self.run_case(key, message=TITLE + "\n\n" + body)
                self.assertEqual((r.code, r.count("post")), (0, 1), r.out)
                self.assertEqual(r.posted_title(), "title=" + TITLE)
                self.assertEqual(r.posted_body, body if kept else "")
                self.assertEqual("커밋 본문이 너무 길어" in r.out, not kept)
                self.assertEqual(r.warnings(), [])

    # ---- 만들지 않는 경우 ---------------------------------------------------------
    def test_a_title_that_does_not_start_with_the_branch_number_makes_no_pull_request(self):
        for key, title in (("no_number", "그냥 제목"), ("other_number", "[M005] 다른 번호"), ("no_space", "[M004]붙어 있음")):
            with self.subTest(key):
                r = self.run_case(key, message=title + "\n\n본문\n")
                self.assertEqual(r.code, 0, r.out)                             # 실패(빨강)가 아니다
                self.assertEqual(r.kinds, ["commits"])                         # 제목을 읽은 직후 멈춘다
                self.assertEqual(len(r.warnings()), 1)
                self.assertIn("[M004]", r.warnings()[0])

    def test_an_empty_or_control_character_title_makes_no_pull_request(self):
        for key, title in (("empty_after", "[M004] "), ("control", "[M004] 제목\x01숨은")):
            with self.subTest(key):
                r = self.run_case(key, message=title + "\n\n본문\n")
                self.assertEqual((r.code, r.count("post")), (0, 0), r.out)
                self.assertEqual(len(r.warnings()), 1)

    def test_a_branch_name_outside_the_rule_never_reaches_github(self):
        for key, branch in (("request_branch", "ai/claude/NO-MERGE-operator-requests"), ("short_number", "ai/claude/M04-short"), ("empty_slug", "ai/claude/M004-")):
            with self.subTest(key):
                r = self.run_case(key, branch=branch)
                self.assertEqual(r.code, 0, r.out)
                self.assertEqual(r.calls, [])                                  # 이름을 거르는 것이 첫 일이라 gh 를 한 번도 부르지 않는다
                self.assertEqual(len(r.warnings()), 1)
                self.assertIn("병합 가지 규칙", r.warnings()[0])
                self.assertNotIn(branch, r.out)                                # 이름 자체는 찍지 않는다

    def test_a_branch_name_is_matched_as_a_whole_and_not_by_a_part_of_it(self):
        """bash 의 `=~` 는 값의 한 부분만 맞아도 통과시킨다(검색). 앞 `^`·끝 `$` 가 있어야 값 전체를 본다 — 앞에 글자가 붙거나 뒤에 셸 문자·공백·줄이 붙은 이름은 `gh` 를 한 번도 부르지 않고 거절한다.
        (앵커가 지워져도 모든 사용이 따옴표 친 변수라 악용은 어렵지만 입력 모양 방어의 한 겹이다.)"""
        for key, branch in (("lead_x", "xai/claude/M001-foo"), ("tail_semicolon", "ai/claude/M001-foo;touch PWNED"), ("tail_space", "ai/claude/M001-foo bar"),
                            ("tail_slash", "ai/claude/M001-foo/bar"), ("tail_newline", "ai/claude/M001-foo\nPWNED")):
            with self.subTest(key):
                r = self.run_case("anchor_" + key, branch=branch, message="[M001] 제목\n\n본문\n")
                self.assertEqual((r.code, r.calls), (0, []), r.out)
                self.assertEqual(len(r.warnings()), 1)
                self.assertEqual([p.name for p in r.folder.iterdir() if p.name.startswith("PWNED")] + [p.name for p in r.work.iterdir()], [])
        ok = self.run_case("anchor_ok", branch="ai/claude/M001-foo", message="[M001] 제목\n\n본문\n")             # 같은 모양의 규칙 안 이름은 통과한다
        self.assertEqual((ok.code, ok.count("post")), (0, 1), ok.out)

    def test_odd_repository_commit_or_base_values_never_reach_github(self):
        for key, kwargs in (("zero_sha", {"sha": "0" * 40}), ("short_sha", {"sha": "abc123"}), ("upper_sha", {"sha": "A" * 40}),
                            ("lead_junk_sha", {"sha": "g" + "a" * 40}), ("tail_junk_sha", {"sha": "a" * 40 + "g"}), ("long_sha", {"sha": "a" * 41}),
                            ("bad_repo", {"extra": {"REPO": "octo/blog extra"}}), ("bad_base", {"extra": {"BASE": "main;x"}}), ("bad_workflow", {"extra": {"CI_WORKFLOW": "x y.yml"}})):
            with self.subTest(key):
                r = self.run_case(key, **kwargs)
                self.assertEqual((r.code, r.calls), (0, []), r.out)
                self.assertEqual(len(r.warnings()), 1)

    def test_an_existing_pull_request_stops_the_run_even_if_it_is_closed_or_merged(self):
        r = self.run_case("exists", prlist="1")
        self.assertEqual((r.code, r.kinds), (0, ["commits", "pr_list"]), r.out)
        self.assertEqual(r.warnings(), [])
        self.assertIn("PR 이 이미 있음", r.summary)
        self.assertEqual(r.calls[1][r.calls[1].index("--state") + 1], "all")        # 닫힌 것·병합된 것도 센다(다시 실행해도 같은 가지의 PR 을 또 만들지 않는다)

    def test_when_the_existing_pull_request_cannot_be_checked_nothing_is_created(self):
        r = self.run_case("prlist_fail", prlist="FAIL")
        self.assertEqual((r.code, r.kinds), (0, ["commits", "pr_list"]), r.out)
        self.assertEqual(len(r.warnings()), 1)
        r2 = self.run_case("prlist_weird", prlist="many")
        self.assertEqual((r2.code, r2.count("post")), (0, 0), r2.out)

    def test_a_pull_request_opened_by_hand_while_waiting_stops_the_run_just_before_creating(self):
        r = self.run_case("made_while_waiting", prlist=["0", "1"])
        self.assertEqual((r.code, r.kinds), (0, ["commits", "pr_list", "ref", "runs", "compare", "pr_list"]), r.out)
        self.assertEqual(r.warnings(), [])
        self.assertIn("PR 이 이미 있음", r.summary)
        r2 = self.run_case("second_check_fails", prlist=["0", "FAIL"])
        self.assertEqual((r2.code, r2.count("post")), (0, 0), r2.out)
        self.assertEqual(len(r2.warnings()), 1)

    def test_when_the_commit_message_cannot_be_read_nothing_else_is_called(self):
        r = self.run_case("message_fail", message_fail=True)
        self.assertEqual((r.code, r.kinds), (0, ["commits"]), r.out)
        self.assertEqual(len(r.warnings()), 1)

    def test_a_failed_cancelled_or_otherwise_not_green_check_makes_no_pull_request(self):
        for conclusion in ("failure", "cancelled", "timed_out"):
            with self.subTest(conclusion):
                r = self.run_case("check_" + conclusion, runs=[f"completed:{conclusion}"])
                self.assertEqual(r.code, 0, r.out)
                self.assertEqual(r.kinds, ["commits", "pr_list", "ref", "runs"])   # 초록이 아니면 main 과의 거리도 보지 않고 끝낸다
                self.assertEqual(len(r.warnings()), 1)

    def test_only_a_completed_success_lets_a_pull_request_through(self):
        """검사 결론 중 `success` 만 통과한다 — `skipped`(실제 응답에 흔하다: 작업 전체가 건너뛰어진 실행)·`neutral`·`action_required`·`stale`·`startup_failure`·결론 없음(`null`)은 모두 거절한다."""
        for conclusion in ("skipped", "neutral", "action_required", "stale", "startup_failure", "none"):
            with self.subTest(conclusion):
                r = self.run_case("conclusion_" + conclusion, runs=[f"completed:{conclusion}"])
                self.assertEqual((r.code, r.count("post")), (0, 0), r.out)
                self.assertEqual(r.kinds, ["commits", "pr_list", "ref", "runs"])
                self.assertEqual(len(r.warnings()), 1)
        r = self.run_case("conclusion_success", runs=["completed:success"])
        self.assertEqual((r.code, r.count("post")), (0, 1), r.out)

    def test_a_check_that_has_not_run_or_not_finished_is_waited_for_and_never_counted_as_green(self):
        """실행이 0개(`none:none` — 검사가 아직 안 만들어짐)·`queued`·`waiting`·`requested`·`pending`·`in_progress` 는 끝나지 않은 것이라 기다린다(PR 을 만들지 않는다).
        가짜 sleep 이 시계를 앞으로 돌리므로 간격 100초·한도 300초면 확인은 정확히 네 번(0·100·200·300초)이고 쉬는 것은 세 번이다."""
        for state in ("none:none", "queued:none", "waiting:none", "requested:none", "pending:none", "in_progress:none"):
            with self.subTest(state):
                r = self.run_case("unfinished_" + state.split(":")[0], runs=[state], poll="100", wait="300")
                self.assertEqual((r.code, r.count("post"), r.count("compare")), (0, 0, 0), r.out)
                self.assertEqual((r.count("runs"), r.sleeps), (4, ["100", "100", "100"]))
                self.assertEqual(len(r.warnings()), 1)
                self.assertIn("40분", r.warnings()[0])

    def test_the_wait_loop_rests_the_poll_interval_between_checks(self):
        r = self.run_case("rest_seven", runs=["none:none", "in_progress:none", "completed:success"], poll="7", wait="600")
        self.assertEqual((r.code, r.count("post")), (0, 1), r.out)
        self.assertEqual(r.sleeps, ["7", "7"])                                   # 검사를 볼 때마다 poll 초(여기서는 7)를 쉬고 바로 다음을 부르지 않는다
        self.assertEqual(r.count("runs"), 3)

    def test_the_defaults_are_thirty_seconds_and_forty_minutes_when_the_timing_values_are_not_numbers(self):
        r = self.run_case("default_timing", runs=["in_progress:none"], extra={"AUTOPR_POLL_SECONDS": "abc", "AUTOPR_MAX_WAIT_SECONDS": "-5"})
        self.assertEqual((r.code, r.count("post")), (0, 0), r.out)
        self.assertEqual(r.sleeps, ["30"] * 80)                                  # 30초 간격으로 2400초(40분)
        self.assertEqual(r.count("runs"), 81)
        self.assertEqual(len(r.warnings()), 1)
        self.assertIn("40분", r.warnings()[0])

    def test_an_answer_for_main_distance_that_is_not_a_number_counts_as_unreadable_and_is_never_printed(self):
        for key, value in (("ahead_abc", "abc"), ("ahead_empty", ""), ("ahead_two_words", "1 2"), ("ahead_minus", "-1")):
            with self.subTest(key):
                r = self.run_case(key, ahead=[value])
                self.assertEqual((r.code, r.count("post")), (0, 0), r.out)
                self.assertEqual((r.count("compare"), len(r.warnings())), (5, 1), r.out)     # 숫자가 아니면 읽기 실패로 세어 정확히 다섯 번째에서 그만둔다
                self.assertNotRegex(r.out, r"abc|1 2|-1")                                    # 응답 글자를 로그에 찍지 않는다

    def test_a_new_commit_on_the_branch_ends_this_run(self):
        r = self.run_case("head_changed", head=[OTHER_SHA])
        self.assertEqual((r.code, r.kinds), (0, ["commits", "pr_list", "ref"]), r.out)
        self.assertIn("가지 끝이 바뀌어", r.summary)

    def test_a_commit_already_in_main_makes_no_pull_request(self):
        r = self.run_case("ahead_zero", ahead=["0"])
        self.assertEqual((r.code, r.count("post")), (0, 0), r.out)
        self.assertEqual(r.count("compare"), 1)

    # ---- 기다림 ---------------------------------------------------------------
    def test_it_waits_while_the_check_is_running_and_creates_the_pull_request_once_it_is_green(self):
        r = self.run_case("running", runs=["none:none", "queued:none", "in_progress:none", "completed:success"])
        self.assertEqual(r.code, 0, r.out)
        self.assertEqual((r.count("ref"), r.count("runs"), r.count("compare"), r.count("post")), (4, 4, 1, 1))   # 검사가 끝난 뒤에야 main 과의 거리를 본다
        self.assertEqual(r.out.count("검사가 아직 끝나지 않았습니다"), 3)

    def test_it_waits_for_the_earlier_merge_when_there_are_more_commits_on_top_of_main_then_goes_ahead(self):
        r = self.run_case("ahead_two_then_one", ahead=["2", "3", "1"])
        self.assertEqual(r.code, 0, r.out)
        self.assertEqual((r.count("compare"), r.count("post")), (3, 1))
        self.assertEqual(r.out.count("앞의 병합을 기다립니다"), 2)

    def test_it_gives_up_with_a_warning_when_the_wait_time_is_over_and_never_fails_the_run(self):
        r = self.run_case("timeout", runs=["in_progress:none"], wait="0")
        self.assertEqual((r.code, r.kinds), (0, ["commits", "pr_list", "ref", "runs"]), r.out)
        self.assertEqual(len(r.warnings()), 1)
        self.assertIn("40분", r.warnings()[0])
        r2 = self.run_case("timeout_ahead", ahead=["2"], wait="0")
        self.assertEqual((r2.code, r2.count("post")), (0, 0), r2.out)
        self.assertEqual((len(r2.warnings()), r2.count("compare")), (1, 1))

    def test_five_unreadable_answers_in_a_row_end_the_run_with_a_warning(self):
        for key, kwargs in (("ref_fail", {"head": ["FAIL"]}), ("runs_fail", {"runs": ["FAIL"]}), ("compare_fail", {"ahead": ["FAIL"]})):
            with self.subTest(key):
                r = self.run_case(key, **kwargs)
                self.assertEqual((r.code, r.count("post")), (0, 0), r.out)
                self.assertEqual(len(r.warnings()), 1)
                self.assertEqual(r.count("ref"), 5)                              # 정확히 다섯 번째에서 그만둔다
        r = self.run_case("flaky", head=["FAIL", "FAIL", SHA])
        self.assertEqual((r.code, r.count("post")), (0, 1), r.out)               # 가끔 못 읽는 것은 넘긴다

    def test_the_timing_values_that_are_not_numbers_fall_back_to_the_defaults_without_failing(self):
        r = self.run_case("bad_timing", extra={"AUTOPR_POLL_SECONDS": "abc", "AUTOPR_MAX_WAIT_SECONDS": "-5"})
        self.assertEqual((r.code, r.count("post")), (0, 1), r.out)               # 기본값(30초·2400초)이어도 첫 확인에서 바로 만들 수 있으면 기다리지 않는다

    # ---- PR 만들기 응답 ----------------------------------------------------------
    def test_a_permission_error_becomes_a_warning_with_the_setting_path_and_a_successful_run(self):
        r = self.run_case("forbidden", post="forbidden")
        self.assertEqual(r.code, 0, r.out)                                       # 빨간 실행이 아니다
        warnings = r.warnings()
        self.assertEqual(len(warnings), 1)
        for needle in ("Allow GitHub Actions to create and approve pull requests", "Settings", "Actions", "General", "Workflow permissions", "노란", "Compare & pull request"):
            self.assertIn(needle, warnings[0])
        self.assertEqual(r.count("post"), 1)
        self.assertNotIn("HTTP 403", r.out)                                      # GitHub 의 응답 원문은 찍지 않는다

    def test_other_refusals_are_also_warnings_not_failures_and_a_duplicate_is_not_a_warning(self):
        r = self.run_case("server_error", post="server")
        self.assertEqual((r.code, len(r.warnings())), (0, 1), r.out)
        self.assertNotIn("Allow GitHub Actions", r.warnings()[0])
        self.assertNotIn("HTTP 500", r.out)
        r2 = self.run_case("duplicate", post="exists")
        self.assertEqual((r2.code, r2.warnings()), (0, []), r2.out)
        self.assertIn("그사이", r2.out)

    def test_a_pull_request_number_that_is_not_a_number_is_not_printed(self):
        r = self.run_case("weird_number", post="weird")
        self.assertEqual(r.code, 0, r.out)
        self.assertNotIn("not-a-number", r.out)
        self.assertNotIn("not-a-number", r.summary)
        self.assertIn("번호는 읽지 못함", r.summary)


# ----------------------------------------------------------------------------
# 문서
# ----------------------------------------------------------------------------
def doc(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class DocumentedBehaviorTest(unittest.TestCase):
    def test_the_header_comment_states_the_rules_and_the_limits(self):
        header = workflow_text().split("\non:\n")[0]
        for needle in ("병합하지 않는다", "D-175", "pull_request_target", "workflow_run", "issue_comment", "schedule", "contents 쓰기", "uses:", "env", "최대 40분",
                       "Allow GitHub Actions to create and approve pull requests", "노란 `Compare & pull request` 배너", "T3", "ci.yml", "네 칸",
                       "AGENTS.md 3 표에서는 T2",                                          # 워크플로는 표의 T2 인데 이 변경은 보안 영역이라 T3 로 다룬다(인용을 표와 맞게)
                       "그대로 공개된다", "`@이름` 멘션", "처음 push 때의 커밋 제목·본문", "포크에서 올라오는 PR 에서는 돌지 않는다", "일시 오류에 다시 시도하지 않고"):
            self.assertIn(needle, header, needle)
        self.assertNotIn("D-160", header)                                                 # 결정 번호는 D-175 (UI-C0 가 D-150~D-162, UI-C1a 가 D-170~D-174)

    def test_the_decision_log_the_changelog_and_the_security_doc_carry_the_change(self):
        decisions = doc("docs/DECISIONS.md")
        row = next(line for line in decisions.splitlines() if line.startswith("| D-175 |"))
        for needle in ("auto-pr.yml", "push", "`ai/claude/M###-*`", "pull-requests: write", "병합", "`uses:`", "env", "ci.yml", "tests/test_auto_pr_workflow.py", "T3",
                       "Allow GitHub Actions to create and approve pull requests",
                       "`AGENTS.md` 3 표의 T2", "그대로 공개", "`@이름`", "포크에서 올라오는 PR 에는 돌지 않는다", "첫 push 때의 커밋 제목·본문으로 고정", "LC_ALL=C.UTF-8", "다시 시도하지 않고"):
            self.assertIn(needle, row, needle)
        self.assertLess(decisions.index("| D-106 |"), decisions.index("| D-175 |"))              # 번호 순서(D-160 부터는 병합 가지끼리 번호가 겹치지 않게 띄워 쓴다)
        changelog = doc("CHANGELOG.md")
        self.assertIn("병합 부탁 PR 자동 만들기", changelog)
        self.assertIn("D-175", [line for line in changelog.splitlines() if "병합 부탁 PR 자동 만들기 준비" in line][0])
        security = doc("docs/SECURITY.md")
        self.assertIn("auto-pr.yml", security)
        self.assertIn("병합하지", security)
        self.assertIn("D-175", security)
        for needle in ("`AGENTS.md` 3 표의 T2", "그대로 공개", "`@이름`", "포크에서 올라오는 PR 에는 돌지 않는다"):
            self.assertIn(needle, security, needle)


if __name__ == "__main__":
    unittest.main()
