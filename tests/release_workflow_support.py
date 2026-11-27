# -*- coding: utf-8 -*-
"""릴리스 워크플로 `.github/workflows/release.yml` 의 규칙 검사기(시험 도우미 — 시험이 아니다) — 설계서 RELEASE 3-7 의 W-1에서 W-16, 운영자 확인 048 ①, 결정 D-880에서 D-891(D-886에서 D-891 은 독립 검증 S·Q 지적을 닫은 재작업 1).

글을 낱말 찾기가 아니라 **구조로 읽는다**(`workflow_yaml_support.load` — 흐름식·앵커·겹친 키·보이지 않는 글자 같은 표기는 읽을 수 없다고 거절하고, 값 자리의 정확히 `{}`·`[]` 만 빈 매핑·빈 목록으로 읽는다).
`release_violations(text)` 는 어긴 규칙의 목록(없으면 빈 목록)을 돌려주고 모든 문장은 규칙 이름표(`W-1: …` … `W-16: …`)나 `구조: …` 로 시작한다 — 시험이 '어느 규칙이 잡았는가' 를 이름표로 확인한다.
세 겹이다(1차 방어는 ② 의 정확한 글 목록이고 ①·①' 의 규칙은 그 목록을 같이 고친 변경에서도 위험한 글이 지나가지 못하게 하는 2차 그물이다 — 규칙만으로도 걸리게 하는 것이 재작업 1 의 일이다): ① **규칙 W-1에서 W-16** 은 글 전체를 훑는 일반 규칙이고(서로 따로 동작한다 — 어느 하나를 빼도 다른 규칙이 엉뚱하게 대신 잡는 일이 없도록 시험이 이름표를 본다)
①' **더한 규칙 X-1·X-2·X-3**(서명 단계는 명령 하나에 `--require-shipped-key`·`--require-openssl` 이 있고, sign-and-draft 는 받기 → 후보 검증 → 매니페스트 → 서명 → 초안 순서이며, 뼈대에 흐름 키·겹친 이름이 없다)가 설계서가 말로만 적은 안전 장치를 구조로 못박고
② **구조 허용 목록**(`EXPECTED_*`)은 잡·단계의 이름·순서·액션·`with`·`env`·`run` 글을 글자 그대로 못박는다 — 규칙이 못 보는 변경(예: 서명 단계의 인자 하나)도 운영자 눈에 띄게 한다(`workflow_golden`·`installer_spike_support` 와 같은 방식).
이 워크플로를 바꾸려면 이 목록과 시험을 같이 고친다. 이 파일은 `.github/` 를 읽기만 한다. 네트워크·GitHub·PyYAML 없이 앱 CI 네 칸에서 같은 방식으로 돈다.

`sign-and-draft`(W-8)와 `build`(W-15)의 `run` 은 작은 bash 읽개(`shell_commands` — 명령마다 낱말·방향 바꾸기·앞의 연결·변수 확장을 남긴다)로 읽어 **실제 파일의 줄 모양**만 허용한다(`_shell_shape_problems`):
명령 치환·백틱·프로세스 치환·여기 문서·묶음·백그라운드는 읽지 않고(거절), 실패를 삼키는 연결(`&&`·`|`·정해진 둘 밖의 `||`·`;`)·`!`·앞 대입·따옴표 없는 변수·정해진 것 밖의 명령줄은 거절하며,
파이썬은 정해진 저장소 스크립트의 정해진 명령줄(`SIGN_PYTHON`·`BUILD_PYTHON`), `gh` 는 옵션 표로 읽은 `release create`(`--draft` 가 옵션 자리에 있어야 한다)와 읽기 전용 `api`(옵션은 `--jq`·`--paginate` 뿐)만 부를 수 있다.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_workflow_artifacts as wf  # noqa: E402  (업로드 허용 목록·비밀 출력 규칙 — 기존 시험 도우미)
import workflow_golden as golden  # noqa: E402  (승인된 액션 목록 — 새 액션 하나는 RELEASE_ONLY_ACTIONS)
import workflow_yaml_support as yamlsub  # noqa: E402  (글을 구조로 읽는 작은 읽개)

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

WORKFLOW_NAME = "Release — 릴리스 초안 만들기(수동)"
BUILD, SIGN = "build", "sign-and-draft"
JOB_ORDER = (BUILD, SIGN)
ACTIONS = {**golden.ACTIONS, **golden.RELEASE_ONLY_ACTIONS}                    # 액션 넷 — `소유자/저장소` → 전체 커밋 SHA(태그는 주석에만)
OWNER = "actions"
ARTIFACT_NAME = "release-candidate"
RELEASE_DIR = "${{ runner.temp }}/release"
UPLOAD_LEAVES = ("ChanceBlogDesktop-*-Setup.exe", "ChanceBlogDesktop-*-win64.zip", "SHA256SUMS", "PACKAGE_INFO.json", "PACKAGE_INFO.md", "release_candidate.json")     # release_chain.py 가 모으는 폴더의 파일 여섯(후보 기록 + 자산 다섯)
UPLOAD_PATH = "".join(RELEASE_DIR + "/" + leaf + "\n" for leaf in UPLOAD_LEAVES)
SECRET_NAME = "UPDATE_SIGNING_KEY"
SECRET_VALUE = "${{ secrets.UPDATE_SIGNING_KEY }}"
TOKEN_ENV = {"GH_TOKEN": "${{ github.token }}"}
EXPRESSION_ENV = {"GH_TOKEN": "${{ github.token }}", "TARGET_SHA": "${{ github.sha }}", SECRET_NAME: SECRET_VALUE}     # 달러 두 중괄호 식이 들어갈 수 있는 env 칸과 그 칸의 식 하나(W-4)
RUNNER_TEMP_EXPRESSION = "${{ runner.temp }}"                                      # 올리기·받기의 with.path 안에서만 쓰는 식
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)
TIMEOUT_LIMITS = {BUILD: 45, SIGN: 15}
PERMISSIONS = {BUILD: {"contents": "read", "actions": "read"}, SIGN: {"contents": "write"}}
RUNNERS = {BUILD: "windows-latest", SIGN: "ubuntu-latest"}
JOB_NAMES = {BUILD: "빌드 — 설치 파일·휴대용 압축 파일·후보 목록 (Windows, 비밀 없음)", SIGN: "서명과 초안 만들기 — 환경 승인 뒤에 시작 (Ubuntu, 서드파티 내려받기 없음)"}      # 잡 표시 이름도 글자 그대로(승인하는 사람이 보는 이름)
JOB_ENV = {"PYTHONUTF8": "1"}
DOWNLOAD_STEP_NAME = "빌드 도구 설치(바깥에서 받는 유일한 단계)"
DOWNLOAD_COMMAND = "python -m pip install -r packaging/requirements-package.txt"
STEP_KEYS = {"name", "uses", "with", "run", "env"}
FLOW_KEYS = ("if", "continue-on-error", "strategy", "matrix", "container", "services", "outputs", "secrets")      # 실패한 단계를 건너뛰어 초록으로 끝나거나 실행 모양을 바꾸는 키 — 잡·단계 어디에도 못 쓴다
JOB_KEYS = {BUILD: {"name", "runs-on", "timeout-minutes", "permissions", "env", "steps"}, SIGN: {"name", "needs", "runs-on", "timeout-minutes", "environment", "permissions", "env", "steps"}}
TOP_KEYS = ("name", "on", "permissions", "concurrency", "defaults", "jobs")
EXPECTED_TOP = {"name": WORKFLOW_NAME, "on": {"workflow_dispatch": None}, "permissions": {}, "concurrency": {"group": "release", "cancel-in-progress": "false"}, "defaults": {"run": {"shell": "bash"}}}
MIN_VERSION = "0.0.0"                                                          # 매니페스트 최소 버전 — 첫 정식 릴리스는 모든 판에서 바로 올릴 수 있다(중간 판이 필요해지면 이 값을 바꾸는 T3 변경)
ASSET_COUNT = 7                                                                # 초안에 붙는 자산: 설치 파일·압축 파일·PACKAGE_INFO 둘·SHA256SUMS·매니페스트·서명 파일


def _lines(*lines):
    return "\n".join(lines)


BUILD_SUMMARY = _lines('{',
                       '  echo "### 릴리스 후보 - 승인 전에 이름·크기·SHA-256 을 눈으로 확인한다"',
                       "  echo '```json'",
                       '  cat "$RUNNER_TEMP/release/release_candidate.json"',
                       "  echo '```'",
                       '} >> "$GITHUB_STEP_SUMMARY"')
ASSET_ARGS = "ChanceBlogDesktop-*-Setup.exe ChanceBlogDesktop-*-win64.zip PACKAGE_INFO.json PACKAGE_INFO.md SHA256SUMS update-manifest.json update-manifest.json.sig"


def _create(extra):
    return ('  gh release create "v${version}" --repo "$GITHUB_REPOSITORY" --draft' + extra + ' --target "$TARGET_SHA" --title "ChanceBlog Desktop ${version}" --notes-file "$RUNNER_TEMP/release-notes.md" ' + ASSET_ARGS)


VERSION_LINES = ("read -r version < VERSION || [[ -n \"$version\" ]]",
                 "re='^[0-9]+[.][0-9]+[.][0-9]+(-rc[.][0-9]+)?$'",
                 '[[ "$version" =~ $re ]] || exit 1')                         # VERSION 읽기 — 끝 줄바꿈이 없어도 멈추지 않고, 버전 글 모양(정식·후보)을 jq·gh 에 끼우기 전에 확인한다
DRAFT_STEP = _lines(*VERSION_LINES,
                    'cd "$RUNNER_TEMP/release"',
                    'if [[ "$version" == *-rc.* ]]; then',
                    _create(" --prerelease"),
                    "else",
                    _create(""),
                    "fi")
POST_STEP = _lines(*VERSION_LINES,
                   """gh api "repos/${GITHUB_REPOSITORY}/git/matching-refs/tags/v${version}" --paginate --jq '.[] | select(.ref == "refs/tags/v'"${version}"'") | error("태그가 이미 있다 - 초안이 태그를 만들었을 수 있다. 공개하지 말고 운영자에게 알린다")'""",
                   """gh api "repos/${GITHUB_REPOSITORY}/releases?per_page=100" --jq 'map(select(.draft and .tag_name == "v'"${version}"'")) | if length == 1 and (.[0].assets | length) == 7 then .[0].assets[] | "\\(.name) \\(.size)" else error("초안이 정확히 하나가 아니거나 자산이 일곱 개가 아니다") end'""")
SIGN_SUMMARY = _lines('cd "$RUNNER_TEMP/release"',
                      'echo "### 공개 전 확인 목록" >> "$GITHUB_STEP_SUMMARY"',
                      'echo "- 릴리스 목록에 초안이 한 개 있고 태그 목록은 그대로(태그 없음)" >> "$GITHUB_STEP_SUMMARY"',
                      'echo "- 자산 이름과 개수(일곱), 본문(릴리스 노트·SHA-256 확인법)을 눈으로 본다" >> "$GITHUB_STEP_SUMMARY"',
                      'echo "- 어긋나면 초안을 지우고 운영자에게 알린다. 후보(rc)는 공개하지 않고 시험 뒤 지운다" >> "$GITHUB_STEP_SUMMARY"',
                      "echo '```' >> \"$GITHUB_STEP_SUMMARY\"",
                      "sha256sum " + ASSET_ARGS + ' >> "$GITHUB_STEP_SUMMARY"',
                      "echo '```' >> \"$GITHUB_STEP_SUMMARY\"")

# 구조 허용 목록 — (이름, 종류, 액션 또는 run 글, with, env). 단계를 더하거나 빼거나 바꾸려면 이 목록과 시험을 같이 고친다.
EXPECTED_STEPS = {
    BUILD: (
        ("가져오기", "uses", "actions/checkout", {"persist-credentials": "false"}, None),
        ("사전 점검", "run", "python scripts/release_preflight.py", None, TOKEN_ENV),
        ("파이썬 3.12", "uses", "actions/setup-python", {"python-version": "3.12"}, None),
        (DOWNLOAD_STEP_NAME, "run", DOWNLOAD_COMMAND, None, None),
        ("묶음과 휴대용 압축 파일 만들기", "run", 'python packaging/build_package.py --out-dir "$RUNNER_TEMP/package"', None, None),
        ("설치 파일 만들기(Inno Setup 판 확인·기록 포함)", "run", 'python packaging/build_installer.py --out-dir "$RUNNER_TEMP/package"', None, None),
        ("후보 목록 만들기(버전 사슬 확인)", "run", 'python packaging/release_chain.py assemble --source "$RUNNER_TEMP/package/release" --out "$RUNNER_TEMP/release"', None, None),
        ("올리기(후보 파일 여섯, 1일)", "uses", "actions/upload-artifact", {"name": ARTIFACT_NAME, "path": UPLOAD_PATH, "retention-days": "1", "if-no-files-found": "error"}, None),
        ("작업 요약(승인 전에 눈으로 확인)", "run", BUILD_SUMMARY, None, None),
    ),
    SIGN: (
        ("가져오기", "uses", "actions/checkout", {"persist-credentials": "false"}, None),
        ("파이썬 3.12", "uses", "actions/setup-python", {"python-version": "3.12"}, None),
        ("사전 점검 다시(초안까지 보이는 쓰기 권한 잡에서)", "run", "python scripts/release_preflight.py", None, TOKEN_ENV),
        ("후보 받기", "uses", "actions/download-artifact", {"name": ARTIFACT_NAME, "path": RELEASE_DIR}, None),
        ("후보 검증(자산을 다시 해시해 후보 목록과 대조)", "run", 'python scripts/update_manifest.py verify-candidate --dir "$RUNNER_TEMP/release"', None, None),
        ("매니페스트 만들기", "run", 'python scripts/update_manifest.py build --dir "$RUNNER_TEMP/release" --min-version ' + MIN_VERSION, None, None),
        ("서명과 자체 검증(비밀은 이 단계에만)", "run", 'python scripts/update_sign.py --manifest "$RUNNER_TEMP/release/update-manifest.json" --require-shipped-key --require-openssl', None, {SECRET_NAME: SECRET_VALUE}),
        ("해시 목록 만들기", "run", 'python packaging/release_chain.py sums --dir "$RUNNER_TEMP/release"', None, None),
        ("사슬 다시 확인(서명 뒤)", "run", 'python packaging/release_chain.py check --dir "$RUNNER_TEMP/release" --phase final', None, None),
        ("릴리스 본문 만들기", "run", 'python packaging/release_chain.py notes --out "$RUNNER_TEMP/release-notes.md"', None, None),
        ("초안 만들기(공개하지 않는다)", "run", DRAFT_STEP, None, {"GH_TOKEN": "${{ github.token }}", "TARGET_SHA": "${{ github.sha }}"}),
        ("사후 점검(초안이 있고 태그는 아직 없다)", "run", POST_STEP, None, TOKEN_ENV),
        ("작업 요약(공개 전 확인 목록)", "run", SIGN_SUMMARY, None, None),
    ),
}
JOB_ACTIONS = {BUILD: {"actions/checkout", "actions/setup-python", "actions/upload-artifact"}, SIGN: {"actions/checkout", "actions/setup-python", "actions/download-artifact"}}

# W-8 — sign-and-draft 잡의 run 에 나올 수 있는 명령 낱말(설계서 3-3 의 허용 목록에서 openssl 은 뺐다: 독립 확인은 update_sign.py 가 안에서 한다 — 워크플로가 직접 부를 일이 없다.
# 해시 목록·릴리스 본문은 release_chain.py 가 만들어 `mkdir`·`cp`·`ls`·`test` 도 쓰지 않는다).
SIGN_ALLOWED_COMMANDS = ("python", "gh", "sha256sum", "[[", "cd", "echo", "read", "exit")
CONTROL_WORDS = frozenset({"if", "then", "elif", "else", "fi", "do", "done", "while", "until", "for", "in", "case", "esac", "!", "{", "}", "time"})
# W-15 — 바깥에서 내려받을 수 있는 명령(낱말 하나씩 + 두 낱말 짝). build 잡에서는 이름이 붙은 한 단계(DOWNLOAD_STEP_NAME)에만, sign-and-draft 잡에서는 어디에도 나오면 안 된다.
DOWNLOAD_WORDS = ("pip", "pip3", "npm", "npx", "yarn", "pnpm", "curl", "wget", "nuget", "choco", "winget", "scoop", "dotnet", "brew", "apt", "apt-get", "Invoke-WebRequest", "Invoke-RestMethod", "iwr", "irm",
                  "Start-BitsTransfer", "bitsadmin", "certutil", "pwsh", "powershell", "docker", "cargo",
                  "nc", "ncat", "netcat", "aria2c", "ssh", "scp", "sftp", "rsync", "ftp", "telnet", "perl", "msiexec", "uvx", "pipx", "easy_install", "conda", "mamba", "gem")      # 뒤쪽 열여덟은 독립 검증 S 의 R-4 가 든 목록 밖의 내려받기 길
DOWNLOAD_LOWER = frozenset(word.lower() for word in DOWNLOAD_WORDS)                # 윈도 러너는 실행 파일 이름의 대소문자를 가리지 않는다(`CURL`·`PIP`) — 낱말 비교는 대소문자 무시
DOWNLOAD_PHRASES = (re.compile(r"python[0-9.]*(?:[.]exe)?\s+-m\s+(?:pip|ensurepip)(?![\w-])", re.IGNORECASE), re.compile(r"git\s+(?:clone|fetch|pull|submodule|remote|ls-remote|lfs)(?![\w-])", re.IGNORECASE),
                    re.compile(r"gh\s+(?:extension|release\s+download|run\s+download|repo\s+clone|auth)(?![\w-])", re.IGNORECASE), re.compile(r"openssl\s+s_client(?![\w-])", re.IGNORECASE))
SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")                         # test_repo_layout.WorkflowPinningTest 와 같은 모양
WORD_SECRETS = re.compile(r"(?<![\w-])secrets(?![\w-])", re.IGNORECASE)                       # GitHub 식의 컨텍스트 이름·함수 이름은 대소문자를 가리지 않는다(`SECRETS.X`·`toJson`) — 독립 검증 S 의 R-3
TOKEN_WORDS = re.compile(r"github\s*\.\s*token|GITHUB_TOKEN|github\s*\[|toJSON|fromJSON", re.IGNORECASE)
FORBIDDEN_TEXT = ("--publish", "--draft=false", "--draft =", "release edit", "release upload", "release delete", "release download")

# 셸 줄 모양(W-8·W-15 의 둘째 그물 — 독립 검증 S 의 R-1·R-2·R-4): 구조 허용 목록이 글자 그대로 못박은 명령줄 가운데 규칙이 따로 허용하는 모양만 적는다.
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
RELEASE_ENV = "$RUNNER_TEMP/release"                                                # 셸에서 본 후보 폴더·꾸러미 폴더·릴리스 본문 파일(env 로 받은 러너 임시 폴더 아래)
PACKAGE_ENV = "$RUNNER_TEMP/package"
NOTES_ENV = "$RUNNER_TEMP/release-notes.md"
ASSET_NAMES = tuple(ASSET_ARGS.split())                                              # 초안에 붙는 자산 일곱의 이름과 순서(gh release create 의 위치 인자·sha256sum 의 인자)
VERSION_RE_WORD = VERSION_LINES[1].replace("'", "")                                  # `re='…'` 줄을 읽개가 푼 낱말 — 앞 대입으로 허용되는 것은 이것 하나
SHELL_VARIABLES = frozenset({"RUNNER_TEMP", "GITHUB_REPOSITORY", "GITHUB_STEP_SUMMARY", "TARGET_SHA", "version", "re"})      # 셸 줄에서 읽을 수 있는 변수 이름(따옴표 없는 확장은 `[[ … =~ $re ]]` 의 re 뿐)
SUMMARY_REDIRECT = (">>", "$GITHUB_STEP_SUMMARY")
VERSION_REDIRECT = ("<", "VERSION")
SIGN_TESTS = (("[[", "$version", "==", "*-rc.*", "]]"), ("[[", "-n", "$version", "]]"), ("[[", "$version", "=~", "$re", "]]"))      # `[[ … ]]` 의 세 모양(후보 판별·비어 있지 않은지·버전 글 모양 확인)
BUILD_ALLOWED_COMMANDS = ("python", "echo", "cat")                                   # build 잡의 명령 낱말(바깥 내려받기 단계는 이름 붙은 한 단계가 따로 있다)
SIGN_PYTHON = (("python", "scripts/release_preflight.py"),
               ("python", "scripts/update_manifest.py", "verify-candidate", "--dir", RELEASE_ENV),
               ("python", "scripts/update_manifest.py", "build", "--dir", RELEASE_ENV, "--min-version", MIN_VERSION),
               ("python", "scripts/update_sign.py", "--manifest", RELEASE_ENV + "/update-manifest.json", "--require-shipped-key", "--require-openssl"),
               ("python", "packaging/release_chain.py", "sums", "--dir", RELEASE_ENV),
               ("python", "packaging/release_chain.py", "check", "--dir", RELEASE_ENV, "--phase", "final"),
               ("python", "packaging/release_chain.py", "notes", "--out", NOTES_ENV))      # sign-and-draft 가 부를 수 있는 python 명령줄 일곱(스크립트 이름과 인자까지)
BUILD_PYTHON = (("python", "scripts/release_preflight.py"),
                ("python", "packaging/build_package.py", "--out-dir", PACKAGE_ENV),
                ("python", "packaging/build_installer.py", "--out-dir", PACKAGE_ENV),
                ("python", "packaging/release_chain.py", "assemble", "--source", PACKAGE_ENV + "/release", "--out", RELEASE_ENV))      # build 가 부를 수 있는 python 명령줄 넷(빌드 도구 설치는 따로)
GH_CREATE_FLAGS = ("--draft", "--prerelease")                                        # gh release create 의 옵션 표 — 값 없는 옵션
GH_CREATE_VALUES = ("--repo", "--target", "--title", "--notes-file")                 # 값을 받는 옵션(다음 낱말을 무엇이든 값으로 먹는다)
REPOSITORY_WORDS = ("$GITHUB_REPOSITORY", "${GITHUB_REPOSITORY}")
GH_CREATE_TAG = "v${version}"
GH_API_PATH = re.compile(r"repos/\$\{GITHUB_REPOSITORY\}/[A-Za-z0-9_.${}/?=&-]+")     # gh api 의 호출 경로 — 이 저장소 아래만(`..` 은 따로 거절)


class ShellUnsafe(ValueError):
    """이 읽개가 읽지 않는 bash 표기(명령 치환·백틱·프로세스 치환·여기 문서·묶음·백그라운드·읽지 않는 매개변수 확장)."""


def shell_commands(body):
    """bash 본문 → 명령 목록 `[{"words": [...], "redirects": [(연산자, 대상)]}]`. 따옴표·`\\` 를 풀고 `;`·`&&`·`||`·`|`·줄 바꿈으로 명령을 나눈다. 주석은 버린다.
    읽을 수 없는 표기는 ShellUnsafe 로 거절한다: `$(`·백틱·`<(`·`>(`·`<<`(여기 문서와 여기 문자열)·묶는 괄호·`&` 한 글자(백그라운드)·`${이름}` 이 아닌 매개변수 확장.
    낱말의 `$이름`·`${이름}` 은 풀지 않고 글자 그대로 둔다."""
    text = body.replace("\r\n", "\n")
    commands, words, redirects, expansions = [], [], [], []
    state = {"word": None, "pending": None, "sep": "plain"}                          # sep: 이 명령 앞의 연결 — plain(처음·줄 바꿈)·;·&&·||·|

    def push_word():
        if state["word"] is None:
            return
        word = "".join(state["word"])
        state["word"] = None
        if state["pending"] is not None:
            redirects.append((state["pending"], word))
            state["pending"] = None
        else:
            words.append(word)

    def push_command(next_sep="plain"):
        nonlocal words, redirects, expansions
        push_word()
        if state["pending"] is not None:
            raise ShellUnsafe("방향 바꾸기 뒤에 대상이 없다")
        if words or redirects:
            commands.append({"words": words, "redirects": redirects, "sep": state["sep"], "expansions": expansions})
            state["sep"] = next_sep
        elif not (next_sep == "plain" and state["sep"] in ("&&", "||", "|")):
            state["sep"] = next_sep                                                 # 연산자 뒤에서 줄을 바꿔도 잇기는 이어진다
        words, redirects, expansions = [], [], []

    def add(text_piece):
        if state["word"] is None:
            state["word"] = []
        state["word"].append(text_piece)

    def parameter(index, quoted):
        """`$` 에서 시작하는 확장 하나를 읽어 (글, 다음 위치) — `$이름`·`${이름}`·`$?` 만. 읽은 확장은 명령마다 (글, 따옴표 안인가) 로 모은다."""
        piece, following_index = parameter_text(index)
        if piece != "$":
            expansions.append((piece, quoted))
        return piece, following_index

    def parameter_text(index):
        following = text[index + 1:index + 2]
        if following == "(":
            raise ShellUnsafe("명령 치환 $( 는 읽지 않는다")
        if following == "{":
            end = text.find("}", index)
            name = text[index + 2:end] if end > 0 else ""
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ShellUnsafe("${이름} 모양이 아닌 매개변수 확장은 읽지 않는다")
            return text[index:end + 1], end + 1
        match = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9?#]").match(text, index + 1)
        if match:
            return text[index:match.end()], match.end()
        return "$", index + 1

    i, size, quote = 0, len(text), ""
    while i < size:
        char = text[i]
        if quote == "'":
            if char == "'":
                quote = ""
            else:
                add(char)
            i += 1
        elif quote == '"':
            if char == '"':
                quote = ""
                i += 1
            elif char == "\\" and text[i + 1:i + 2] in ('"', "\\", "$", "`", "\n"):
                if text[i + 1] != "\n":
                    add(text[i + 1])
                i += 2
            elif char == "`":
                raise ShellUnsafe("백틱 명령 치환은 읽지 않는다")
            elif char == "$":
                piece, i = parameter(i, True)
                add(piece)
            else:
                add(char)
                i += 1
        elif char in " \t":
            push_word()
            i += 1
        elif char in "\n;":
            push_command("plain" if char == "\n" else ";")
            i += 1
        elif char == "&":
            if text[i + 1:i + 2] == "&":
                push_command("&&")
                i += 2
            elif state["pending"] is None and state["word"] is None and text[i + 1:i + 2] == ">":
                raise ShellUnsafe("& 로 시작하는 방향 바꾸기는 읽지 않는다")
            else:
                raise ShellUnsafe("백그라운드 실행(&)은 읽지 않는다")
        elif char == "|":
            doubled = text[i + 1:i + 2] == "|"
            push_command("||" if doubled else "|")
            i += 2 if doubled else 1
        elif char in "<>":
            if text[i:i + 2] in ("<(", ">(") or text[i:i + 2] == "<<":
                raise ShellUnsafe("프로세스 치환·여기 문서·여기 문자열은 읽지 않는다")
            if state["word"] is not None and "".join(state["word"]).isdigit():
                state["word"] = None                                              # `2>` 의 파일 번호는 연산자의 일부다
            else:
                push_word()
            if text[i:i + 2] == ">>":
                operator, i = ">>", i + 2
            elif text[i:i + 2] == ">&":
                operator, i = ">&", i + 2
            else:
                operator, i = char, i + 1
            if state["pending"] is not None:
                raise ShellUnsafe("방향 바꾸기가 연달아 있다")
            state["pending"] = operator
        elif char in "()":
            raise ShellUnsafe("묶는 괄호(부분 셸)는 읽지 않는다")
        elif char == "`":
            raise ShellUnsafe("백틱 명령 치환은 읽지 않는다")
        elif char == "#" and state["word"] is None:
            while i < size and text[i] != "\n":
                i += 1
        elif char == "\\":
            if text[i + 1:i + 2] == "\n":
                i += 2
            else:
                add(text[i + 1:i + 2])
                i += 2
        elif char in "'\"":
            quote = char
            if state["word"] is None:
                state["word"] = []
            i += 1
        elif char == "$":
            piece, i = parameter(i, False)
            add(piece)
        else:
            add(char)
            i += 1
    if quote:
        raise ShellUnsafe("따옴표가 닫히지 않았다")
    push_command()
    return commands


def command_words(command):
    """한 명령의 낱말 목록에서 맨 앞의 제어 낱말(`if`·`then`·`!` …)과 `이름=값` 대입을 걷어 낸 것(비면 명령이 아니다)."""
    words = list(command["words"])
    while words and (words[0] in CONTROL_WORDS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0])):
        words.pop(0)
    return words


def run_bodies(job):
    """잡의 단계 → [(단계 번호(1부터), 단계 이름, run 글)] — run 이 글이 아니면 건너뛴다(구조 검사가 따로 잡는다)."""
    found = []
    for position, step in enumerate(job.get("steps") or [], 1):
        if isinstance(step, dict) and isinstance(step.get("run"), str):
            found.append((position, step.get("name"), step["run"]))
    return found


def _jobs(tree):
    jobs = tree.get("jobs") if isinstance(tree, dict) else None
    return {name: job for name, job in jobs.items() if isinstance(job, dict)} if isinstance(jobs, dict) else {}


def _steps(job):
    return [(position, step) for position, step in enumerate(job.get("steps") or [], 1) if isinstance(step, dict)] if isinstance(job.get("steps"), list) else []


def _walk(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                yield path + (key,), "키", key
            yield from _walk(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, path + (index,))
    elif isinstance(node, str):
        yield path, "값", node


def _where(path):
    return "/".join(str(part) for part in path)


# ---- 규칙 W-1에서 W-16 --------------------------------------------------------------------------------------------------------------------------------

def w1(tree):
    """on 은 workflow_dispatch 하나이고 inputs(입력칸)가 없다."""
    on = tree.get("on")
    if not isinstance(on, dict):
        return [f"W-1: on 이 매핑이 아니다(workflow_dispatch 하나여야 한다): {on!r}"]
    problems = []
    if set(on) != {"workflow_dispatch"}:
        problems.append(f"W-1: on 은 workflow_dispatch 하나여야 한다 — 다른 이벤트가 있다: {sorted(on)}")
    if on.get("workflow_dispatch") is not None:
        problems.append(f"W-1: workflow_dispatch 에 입력칸(inputs)이나 설정이 있다 — 입력은 받지 않는다: {on.get('workflow_dispatch')!r}")
    return problems


def w2(tree):
    """최상위 permissions 는 빈 매핑이다(전부 차단)."""
    return [] if tree.get("permissions") == {} and isinstance(tree.get("permissions"), dict) else [f"W-2: 최상위 permissions 는 빈 매핑({{}})이어야 한다: {tree.get('permissions')!r}"]


def w3(tree):
    """잡마다 permissions 가 있고 허용 조합뿐이다 — build = contents 읽기 + actions 읽기, sign-and-draft = contents 쓰기. 쓰기는 sign-and-draft 한 곳뿐이고 그 밖의 권한 이름은 없다."""
    problems = []
    jobs = _jobs(tree)
    if tuple(jobs) != JOB_ORDER:
        problems.append(f"W-3: 잡은 {list(JOB_ORDER)} 둘이어야 한다: {list(jobs)}")
    for name, job in jobs.items():
        permissions = job.get("permissions")
        if name not in PERMISSIONS:
            problems.append(f"W-3: 정해지지 않은 잡 {name} — 권한 조합을 알 수 없다")
        elif permissions != PERMISSIONS[name]:
            problems.append(f"W-3: {name} 잡의 permissions 가 허용 조합 {PERMISSIONS[name]} 이 아니다: {permissions!r}")
        if isinstance(permissions, dict) and name != SIGN and any(value == "write" for value in permissions.values()):
            problems.append(f"W-3: 쓰기 권한은 {SIGN} 한 곳에만 있어야 한다: {name}")
    for path, kind, text in _walk(tree):
        if path and path[-1] == "permissions" and kind == "키" and len(path) not in (1, 3):
            problems.append(f"W-3: permissions 는 최상위와 잡 수준에만 있어야 한다(단계·그 밖의 자리에 못 둔다): {_where(path)}")
    return problems


def _expression_site_ok(path, kind, text):
    """달러 두 중괄호 식이 들어갈 수 있는 자리 — 단계 env 의 GH_TOKEN·TARGET_SHA·UPDATE_SIGNING_KEY 값(정해진 식 하나와 정확히 같을 때)과 단계 with.path 안의 runner.temp 식뿐이다."""
    if kind != "값" or len(path) != 6 or path[0] != "jobs" or path[2] != "steps":
        return False
    if path[4] == "env":
        return EXPRESSION_ENV.get(path[5]) == text
    if path[4:] == ("with", "path"):
        rest = EXPRESSION.sub("", text)
        return "${{" not in rest and "}}" not in rest and all(found == RUNNER_TEMP_EXPRESSION for found in EXPRESSION.findall(text))
    return False


def w4(tree):
    """secrets 참조는 UPDATE_SIGNING_KEY 하나이고 environment release 가 있는 잡의 서명 단계 env 에만 있다. 자동 토큰은 env GH_TOKEN 에 github.token 을 넘기는 모양뿐이다.
    더해서 달러 두 중괄호 식은 정해진 자리의 정해진 식뿐이다(`_expression_site_ok`) — 낱말 목록(secrets·github.token·toJSON)이 못 보는 다른 맥락(vars·env·github.event·format·join)과
    대소문자·간격을 바꾼 식을 통째로 막는 둘째 그물(독립 검증 S 의 R-3·EX12·EX13·EX16·YML34·YML35)."""
    problems = []
    jobs = _jobs(tree)
    hits = [(path, kind, text) for path, kind, text in _walk(tree) if WORD_SECRETS.search(text)]
    allowed_at = None
    sign = jobs.get(SIGN) or {}
    for position, step in _steps(sign):
        env = step.get("env")
        if isinstance(env, dict) and env.get(SECRET_NAME) == SECRET_VALUE:
            allowed_at = ("jobs", SIGN, "steps", position - 1, "env", SECRET_NAME)
    if len([hit for hit in hits if hit[0] == allowed_at and hit[1] == "값"]) != 1 or allowed_at is None:
        problems.append(f"W-4: {SECRET_VALUE} 가 {SIGN} 잡의 한 단계 env 의 {SECRET_NAME} 값으로 정확히 한 번 있어야 한다")
    if sign.get("environment") != "release":
        problems.append("W-4: 비밀을 받는 잡에는 environment: release 가 있어야 한다(필수 검토자 승인 뒤에만 시작)")
    for path, kind, text in hits:
        if path != allowed_at:
            problems.append(f"W-4: 허용된 자리(서명 단계의 env {SECRET_NAME}) 밖에서 secrets 를 쓴다 — {_where(path)}({kind}): {text[:60]!r}")
    for path, kind, text in _walk(tree):
        if kind == "값" and re.search(r"(?i:secrets\s*\.\s*)(?!UPDATE_SIGNING_KEY(?![\w-]))", text):                   # 컨텍스트 이름은 대소문자 무시, 허용된 비밀 이름은 정확한 철자만(독립 검증 S 의 R-3)
            problems.append(f"W-4: UPDATE_SIGNING_KEY 가 아닌 비밀을 참조한다 — {_where(path)}: {text[:60]!r}")
    token_ok = {}
    for name, job in jobs.items():
        for position, step in _steps(job):
            env = step.get("env")
            if isinstance(env, dict) and env.get("GH_TOKEN") == TOKEN_ENV["GH_TOKEN"]:
                token_ok[("jobs", name, "steps", position - 1, "env", "GH_TOKEN")] = True
    for path, kind, text in _walk(tree):
        if TOKEN_WORDS.search(text) and not (token_ok.get(path) and kind == "값" and text == TOKEN_ENV["GH_TOKEN"]):
            problems.append(f"W-4: 자동 토큰은 env GH_TOKEN 에 github.token 을 넘기는 모양뿐이다(다른 이름·with·run·잡 env 로 못 쓴다) — {_where(path)}({kind}): {text[:60]!r}")
    for name, job in jobs.items():
        env = job.get("env")
        if isinstance(env, dict) and (SECRET_NAME in env or "GH_TOKEN" in env or "GITHUB_TOKEN" in env):
            problems.append(f"W-4: 잡 수준 env 에 비밀·토큰을 둘 수 없다(모든 단계가 받는다): {name}")
    build = jobs.get(BUILD) or {}
    for position, step in _steps(build):
        env = step.get("env")
        if isinstance(env, dict) and SECRET_NAME in env:
            problems.append(f"W-4: {BUILD} 잡은 비밀이 없어야 한다 — 단계 {position} 의 env 에 {SECRET_NAME} 가 있다")
    for path, kind, text in _walk(tree):
        if "${{" in text and not _expression_site_ok(path, kind, text):
            problems.append(f"W-4: 달러 두 중괄호 식이 허용된 자리 밖에 있다(허용: env 의 GH_TOKEN·TARGET_SHA·{SECRET_NAME} 값, 올리기·받기의 path 안 runner.temp) — {_where(path)}({kind}): {text[:60]!r}")
    return problems


def w5(tree):
    """모든 uses 는 40자리 SHA 이고 허용 네 개(저장소 주인 actions) 안에 있다. docker://·./·잡 수준 uses(재사용 워크플로) 없음."""
    problems = []
    for name, job in _jobs(tree).items():
        if "uses" in job:
            problems.append(f"W-5: 잡 수준 uses(재사용 워크플로)는 쓰지 않는다: {name}")
        for position, step in _steps(job):
            ref = step.get("uses")
            if ref is None:
                continue
            if not isinstance(ref, str) or ref.startswith(("docker://", "./", "../", "/")) or "@" not in ref:
                problems.append(f"W-5: 액션 참조가 저장소의 `소유자/저장소@커밋` 모양이 아니다({name} 단계 {position}): {ref!r}")
                continue
            action, _, pin = ref.partition("@")
            if not re.fullmatch(r"[0-9a-f]{40}", pin):
                problems.append(f"W-5: 액션이 전체 커밋 SHA(40자리)로 고정되지 않았다({name} 단계 {position}): {ref}")
            if action.split("/")[0] != OWNER or action not in ACTIONS:
                problems.append(f"W-5: 허용 목록(actions 의 {sorted(ACTIONS)})에 없는 액션이다({name} 단계 {position}): {action}")
            elif pin != ACTIONS[action]:
                problems.append(f"W-5: 승인된 SHA 가 아니다({name} 단계 {position}): {ref}")
    return problems


def w6(tree):
    """액션의 with 는 정해진 키뿐이다 — checkout 은 persist-credentials: false 하나, setup-python 은 python-version(3.숫자) 하나, download-artifact 는 name(release-candidate)과 path(runner.temp 아래 release) 둘이다.
    올리기(upload-artifact)의 with 는 W-11 이 본다. 구조 허용 목록이 이미 못박고 있어도, 목록을 같이 고친 변경에서 `run-id`·`repository`·`pattern`·`cache`·`check-latest` 같은 키가 끼어들지 못하게 하는 둘째 그물(독립 검증 S 의 R-5)."""
    problems = []
    for name, job in _jobs(tree).items():
        for position, step in _steps(job):
            ref = step.get("uses")
            if not isinstance(ref, str):
                continue
            action, with_, where = ref.split("@")[0], step.get("with"), f"{name} 단계 {position}"
            if action == "actions/checkout":
                if with_ != {"persist-credentials": "false"}:
                    problems.append(f"W-6: checkout 의 with 가 persist-credentials: false 하나뿐이 아니다({where}): {with_!r}")
            elif action == "actions/setup-python":
                version = with_.get("python-version") if isinstance(with_, dict) else None
                if not (isinstance(with_, dict) and set(with_) == {"python-version"} and isinstance(version, str) and re.fullmatch(r"3[.][0-9]{1,2}", version)):
                    problems.append(f"W-6: setup-python 의 with 가 python-version(3.숫자) 하나뿐이 아니다 — cache·check-latest·python-version-file 같은 키를 못 쓴다({where}): {with_!r}")
            elif action == "actions/download-artifact":
                if not (isinstance(with_, dict) and set(with_) == {"name", "path"}):
                    problems.append(f"W-6: download-artifact 의 with 가 name·path 둘뿐이 아니다 — run-id·repository·pattern·github-token·merge-multiple 같은 키를 못 쓴다(같은 실행의 산출물만 받는다, {where}): {with_!r}")
                else:
                    if with_["name"] != ARTIFACT_NAME:
                        problems.append(f"W-6: download-artifact 의 name 은 {ARTIFACT_NAME} 여야 한다({where}): {with_['name']!r}")
                    if with_["path"] != RELEASE_DIR:
                        problems.append(f"W-6: download-artifact 의 path 는 {RELEASE_DIR} 여야 한다(runner.temp 밖·위쪽으로 받지 못한다, {where}): {with_['path']!r}")
    return problems


def w7(tree, text):
    """run 본문에 달러 두 중괄호 식이 하나도 없다(값은 env 로만). set -x·env·printenv·export -p·비밀을 담은 변수를 내는 줄 없음(기존 secret_output_problems 재사용)."""
    problems = []
    for name, job in _jobs(tree).items():
        for position, step_name, body in run_bodies(job):
            if "${{" in body:
                problems.append(f"W-7: run 안에 달러 두 중괄호 식이 있다(주입 길 — 값은 env 로만 넘긴다): {name} 단계 {position}({step_name})")
            for secret in (SECRET_NAME, "GH_TOKEN", "GITHUB_TOKEN"):
                if re.search(r"(?<![\w-])" + secret + r"(?![\w-])", body, re.IGNORECASE):                 # 윈도 러너의 환경 변수 이름은 대소문자를 가리지 않는다
                    problems.append(f"W-7: run 안에서 비밀·토큰 환경 변수 {secret} 를 이름으로 부른다: {name} 단계 {position}({step_name})")
    for number, reason in wf.secret_output_problems(text):
        problems.append(f"W-7: {number}번째 줄 — {reason}")
    return problems


def _split_lead(command):
    """명령의 낱말에서 앞의 제어 낱말(`if`·`then`·`!`·`{` …)과 `이름=값` 대입을 떼어 (떼어 낸 것, 나머지)를 돌려준다 — `command_words` 와 같은 규칙인데 무엇을 걷었는지 남긴다."""
    words, lead = list(command["words"]), []
    while words and (words[0] in CONTROL_WORDS or ASSIGNMENT.fullmatch(words[0])):
        lead.append(words.pop(0))
    return lead, words


def _allowed_or(previous, command):
    """`||` 로 이어 붙을 수 있는 두 자리 — VERSION 읽기 줄 뒤의 `[[ -n "$version" ]]`(끝 줄바꿈이 없는 파일 대비)와 버전 모양 확인 줄 뒤의 `exit 1`."""
    if previous is None:
        return False
    return ((previous["words"] == ["read", "-r", "version"] and command["words"] == ["[[", "-n", "$version", "]]"])
            or (previous["words"] == ["[[", "$version", "=~", "$re", "]]"] and command["words"] == ["exit", "1"]))


def _shell_shape_problems(label, where, commands, job):
    """한 run 의 명령들이 실제 파일의 줄 모양뿐인지 본다(독립 검증 S 의 R-1·R-4) — 연결(`||`·`&&`·`|`·`;`)·앞 대입·제어 낱말·따옴표 없는 변수·명령 낱말과 그 인자 모양.
    sign-and-draft(W-8)와 build(W-15)가 같은 틀을 쓰고 허용 목록만 다르다. 실패를 삼키는 구문·환경을 바꾸는 대입·옵션을 변수에 담기·정해진 것 밖의 스크립트를 한꺼번에 막는다."""
    problems = []
    sign = job == SIGN
    allowed_first = SIGN_ALLOWED_COMMANDS if sign else BUILD_ALLOWED_COMMANDS
    here = f"{label}: {where}"
    for index, command in enumerate(commands):
        previous = commands[index - 1] if index else None
        lead, words = _split_lead(command)
        sep, redirects = command["sep"], command["redirects"]
        if sep in ("&&", "|"):
            problems.append(f"{here} 에 명령을 잇는 {sep} 가 있다 — 앞 명령의 실패를 삼키거나 출력을 다른 명령으로 넘길 수 있어 허용하지 않는다")
        elif sep == "||" and not (sign and _allowed_or(previous, command)):
            problems.append(here + ' 에 허용되지 않은 || 가 있다 — 실패를 삼킬 수 있다(허용: VERSION 읽기 줄 끝의 `|| [[ -n "$version" ]]` 와 버전 모양 확인 줄 끝의 `|| exit 1`, sign-and-draft 안에서만)')
        elif sep == ";" and not (sign and lead == ["then"] and not words):
            problems.append(here + " 에 허용되지 않은 ; 가 있다(허용: `if [[ … ]]; then` 틀의 then 앞 하나뿐)")
        if lead:
            allowed_lead = ((sign and lead == ["if"] and words[:1] == ["[["]) or (sign and lead in (["then"], ["else"], ["fi"]) and not words)
                            or (sign and lead == [VERSION_RE_WORD] and not words) or (not sign and lead in (["{"], ["}"]) and not words))
            if not allowed_lead:
                problems.append(f"{here} 에 허용되지 않은 앞 낱말(제어 낱말·`이름=값` 대입)이 있다: {' '.join(lead)} — 환경(PATH·PYTHONPATH·BASH_ENV·IFS·GITHUB_STEP_SUMMARY …)을 바꾸거나 실패를 삼키는 틀을 막는다")
        for piece, quoted in command["expansions"]:
            variable = piece.replace("$", "").replace("{", "").replace("}", "")
            if variable not in SHELL_VARIABLES:
                problems.append(f"{here} 에서 허용되지 않은 변수를 쓴다: {piece}(허용: {', '.join(sorted(SHELL_VARIABLES))})")
            elif not quoted and not (variable == "re" and words[:1] == ["[["]):
                problems.append(f"{here} 에 따옴표 없는 변수 확장이 있다: {piece} — 낱말 나눔·글자 패턴 확장으로 인자가 늘거나 바뀐다(`[[ … =~ $re ]]` 의 $re 만 예외)")
        first = words[0] if words else None
        if first is None:
            allowed_redirects = ([], [SUMMARY_REDIRECT]) if (not sign and lead == ["}"]) else ([],)                 # 묶음 끝의 `} >> 요약`
        elif sign and first in ("echo", "sha256sum"):
            allowed_redirects = ([SUMMARY_REDIRECT],)
        elif sign and first == "read":
            allowed_redirects = ([VERSION_REDIRECT],)
        else:
            allowed_redirects = ([],)
        if redirects not in allowed_redirects:
            problems.append(f"{here} 에 허용되지 않은 방향 바꾸기가 있다: {redirects!r} — 허용되는 것은 요약 파일에 덧붙이기(>> $GITHUB_STEP_SUMMARY)와 VERSION 읽기뿐이고 명령마다 정해져 있다")
        if first is None:
            continue
        if first not in allowed_first:
            problems.append(f"{here} 에서 허용 목록 밖의 명령을 부른다: {first}")
            continue
        shape = tuple(words)
        if first == "python":
            if shape not in (SIGN_PYTHON if sign else BUILD_PYTHON):
                problems.append(f"{here} 의 python 은 정해진 저장소 스크립트의 정해진 명령줄만 부를 수 있다(이름과 인자까지): {' '.join(words[:4])}")
        elif first == "gh":
            problems += _gh_problems(where, words)
        elif first == "[[":
            if shape not in SIGN_TESTS:
                problems.append(f"{here} 의 [[ … ]] 는 정해진 세 모양뿐이다(후보 판별·비어 있지 않은지·버전 글 모양 확인): {' '.join(words)}")
        elif first == "cd":
            if words != ["cd", RELEASE_ENV]:
                problems.append(f"{here} 의 cd 는 {RELEASE_ENV} 로만 갈 수 있다: {' '.join(words)}")
        elif first == "read":
            if words != ["read", "-r", "version"]:
                problems.append(f"{here} 의 read 는 `read -r version` 하나뿐이다: {' '.join(words)}")
        elif first == "exit":
            if words != ["exit", "1"]:
                problems.append(f"{here} 의 exit 는 `exit 1` 하나뿐이다: {' '.join(words)}")
        elif first == "sha256sum":
            if shape[1:] != ASSET_NAMES:
                problems.append(f"{here} 의 sha256sum 은 정해진 자산 일곱 이름만 받는다: {' '.join(words[:4])}")
        elif first == "cat":
            if words != ["cat", RELEASE_ENV + "/release_candidate.json"]:
                problems.append(f"{here} 의 cat 은 후보 목록 하나만 읽는다: {' '.join(words)}")
        elif first == "echo":
            pass                                                                    # echo 의 방향 바꾸기는 위에서 명령마다 정해 두었다
        else:
            problems.append(f"{here} 의 {first} 는 허용 낱말 목록에는 있으나 줄 모양이 정해지지 않았다 — 목록에 낱말을 더하면 그 낱말의 모양 검사도 같이 더한다(독립 검증 Q 의 K23)")
    return problems


def w8(tree):
    """sign-and-draft 의 run 에는 실제 파일의 줄 모양만 있다 — 허용 명령(저장소 스크립트를 정해진 명령줄로 부르는 python·gh release create 와 읽기 전용 gh api·sha256sum·cd·echo·read·exit·`[[`)뿐이고
    pip·npm·curl·wget·dotnet·choco·winget·bash -c 로 다시 해석하는 모양·명령 치환·실패를 삼키는 연결(`||`·`&&`·`;`·`!`)·앞 대입·따옴표 없는 변수 확장이 없다(독립 검증 S 의 R-1·R-2)."""
    problems = []
    sign = _jobs(tree).get(SIGN) or {}
    for position, step_name, body in run_bodies(sign):
        where = f"{SIGN} 단계 {position}({step_name})"
        try:
            commands = shell_commands(body)
        except ShellUnsafe as error:
            problems.append(f"W-8: {where} 의 run 을 읽을 수 없다 — {error}")
            continue
        problems += _shell_shape_problems("W-8", where, commands, SIGN)
    return problems


def _gh_create_parse(words):
    """`gh release create …` 의 낱말을 옵션과 위치 인자로 읽는다 → (옵션 목록 [(이름, 값 또는 None)], 위치 인자 목록, 모르는 옵션 목록). 값을 받는 옵션은 다음 낱말을 무엇이든(`--draft` 라도) 값으로 먹는다(gh 의 flag 읽기와 같다) —
    그래서 `--title --draft` 의 `--draft` 는 값이지 옵션이 아니다. 알려진 옵션은 여섯뿐이고 `=` 로 붙인 꼴·짧은 옵션은 모두 '모르는 옵션'이다."""
    options, positionals, unknown, i = [], [], [], 3
    while i < len(words):
        word = words[i]
        if word in GH_CREATE_FLAGS:
            options.append((word, None))
        elif word in GH_CREATE_VALUES:
            options.append((word, words[i + 1] if i + 1 < len(words) else None))
            i += 1
        elif word.startswith("-") and len(word) > 1:
            unknown.append(word)
        else:
            positionals.append(word)
        i += 1
    return options, positionals, unknown


def _gh_create_repo_problems(where, words):
    """gh release create 의 --repo 와 위치 인자(태그와 자산 일곱) — 다른 저장소·추가 자산 경로를 못 넣는다(독립 검증 S 의 R-2)."""
    options, positionals, _unknown = _gh_create_parse(words)
    problems = []
    repos = [value for option, value in options if option == "--repo"]
    if len(repos) != 1 or repos[0] not in REPOSITORY_WORDS:
        problems.append(f'W-8: {where} 의 gh release create 는 --repo 가 이 저장소("$GITHUB_REPOSITORY") 하나여야 한다: {repos!r}')
    if positionals != [GH_CREATE_TAG, *ASSET_NAMES]:
        problems.append(f"W-8: {where} 의 gh release create 의 위치 인자는 태그와 정해진 자산 일곱 이름(순서까지)뿐이어야 한다 — 다른 파일·경로를 못 붙인다: {positionals!r}")
    return problems


def _gh_api_problems(where, words):
    """gh api — 읽기 전용: 호출 경로는 이 저장소 아래의 하나이고 `..` 이 없으며 옵션은 `--jq 식`·`--paginate` 뿐이다. 쓰는 옵션(`-X`·`-f`·`-F`·`--field`·`--input`·`--method`·붙은 꼴 `-fdraft=false` 까지)과
    다른 호스트·머리글(`--hostname`·`-H`)은 모두 `-` 로 시작하는 낱말이라 한꺼번에 막힌다(독립 검증 S 의 R-2). 옵션이 경로 앞에 와도 같다.
    같은 옵션을 두 번 주지 못한다 — `--jq`·`--paginate` 는 각각 한 번까지다. gh 는 같은 옵션이 둘이면 뒤의 값이 이기므로 뒤의 `--jq .` 가 앞의 `error(...)`(사후 점검을 실패로 끝내는 식)를 지운다(구현자 보충 확인)."""
    problems, positionals, seen, i = [], [], {"--jq": 0, "--paginate": 0}, 2
    while i < len(words):
        word = words[i]
        if word == "--paginate":
            seen[word] += 1
        elif word == "--jq":
            seen[word] += 1
            if i + 1 >= len(words):
                problems.append(f"W-8: {where} 의 gh api --jq 에 식이 없다")
            i += 1
        elif word.startswith("-") and len(word) > 1:
            problems.append(f"W-9: {where} 의 gh api 에 허용되지 않은 옵션이 있다({word}) — 읽기 전용 호출이라 옵션은 --jq·--paginate 둘뿐이다(쓰는 옵션·다른 호스트·머리글은 공개·수정으로 이어질 수 있다)")
        else:
            positionals.append(word)
        i += 1
    for option, count in seen.items():
        if count > 1:
            problems.append(f"W-9: {where} 의 gh api 에 {option} 가 {count}번 있다 — 같은 옵션은 한 번까지다(gh 는 같은 옵션이 둘이면 뒤의 값이 이긴다 — 뒤의 `--jq .` 가 앞의 error 식을 지운다)")
    if len(positionals) != 1:
        problems.append(f"W-8: {where} 의 gh api 에는 호출 경로가 정확히 하나여야 한다: {positionals!r}")
    elif GH_API_PATH.fullmatch(positionals[0]) is None or ".." in positionals[0]:
        problems.append(f"W-8: {where} 의 gh api 는 이 저장소(repos/${{GITHUB_REPOSITORY}}/…)의 경로만 부를 수 있고 `..` 이 없어야 한다: {positionals[0]}")
    return problems


def _gh_problems(where, words):
    if words[1:3] == ["release", "create"]:
        return _gh_create_repo_problems(where, words)                           # `--draft`·`--target`·옵션 모양은 W-9·W-10 이 따로 본다
    if words[1:2] == ["api"]:
        return _gh_api_problems(where, words)
    return [f"W-8: {where} 에서 허용되지 않은 gh 하위 명령: {' '.join(words[:3])}"]


def w9(tree, text):
    """모든 gh release create 에 --draft 가 옵션 자리에 있다. --draft=false·--publish·gh release edit·upload·delete·download 가 파일 어디에도 없다.
    gh release create 는 옵션 표(알려진 옵션 여섯, 값을 받는 옵션은 다음 낱말을 값으로 먹는다)로 읽는다 — 값으로만 있는 --draft·붙은 꼴·모르는 옵션(--latest·--discussion-category …)이 통과하지 못한다(독립 검증 S 의 R-2)."""
    problems = []
    code = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("#"))
    for needle in FORBIDDEN_TEXT:
        if needle in code:
            problems.append(f"W-9: 공개·수정·받기로 이어지는 글이 있다: {needle}")
    for name, job in _jobs(tree).items():
        for position, step_name, body in run_bodies(job):
            where = f"{name} 단계 {position}({step_name})"
            if name != SIGN and re.search(r"(?<![\w-])gh(?![\w-])", body):
                problems.append(f"W-9: {where} — gh 는 {SIGN} 잡에서만 부른다")
            try:
                commands = shell_commands(body)
            except ShellUnsafe:
                continue                                                         # 읽을 수 없는 글은 W-8 이 이미 잡는다(sign 잡) — 다른 잡은 구조 허용 목록이 잡는다
            for command in commands:
                words = command_words(command)
                if words[:1] != ["gh"] or words[1:2] != ["release"]:
                    continue
                if words[2:3] != ["create"]:
                    problems.append(f"W-9: gh release 는 create 만 부를 수 있다({where}): {' '.join(words[:3])}")
                    continue
                options, _positionals, unknown = _gh_create_parse(words)
                names = [option for option, _value in options]
                values = dict(options)
                for word in unknown:
                    problems.append(f"W-9: 허용되지 않은 gh release create 옵션({where}): {word} — 알려진 옵션은 --draft·--prerelease·--repo·--target·--title·--notes-file 여섯뿐이고 `=` 로 붙인 꼴과 짧은 옵션은 못 쓴다")
                if names.count("--draft") != 1:
                    problems.append(f"W-9: gh release create 에 --draft 가 옵션 자리에 정확히 하나여야 한다({where}) — 다른 옵션의 값으로 먹힌 --draft 는 세지 않는다")
                if names.count("--prerelease") > 1:
                    problems.append(f"W-9: gh release create 에 --prerelease 가 둘 이상이다({where})")
                for option in ("--title", "--notes-file"):
                    if names.count(option) != 1:
                        problems.append(f"W-9: gh release create 에 {option} 이 정확히 하나여야 한다({where})")
                if values.get("--notes-file") not in (None, NOTES_ENV):
                    problems.append(f"W-9: gh release create 의 --notes-file 은 {NOTES_ENV} 여야 한다({where}): {values.get('--notes-file')!r}")
                if isinstance(values.get("--title"), str) and values["--title"].startswith("-"):
                    problems.append(f"W-9: gh release create 의 --title 값이 `-` 로 시작한다({where}) — 다른 옵션을 값으로 먹은 모양이다: {values['--title']!r}")
    return problems


def w10(tree):
    """gh release create 의 --target 은 옵션 자리에 정확히 하나이고 값은 env 로 받은 전체 커밋 SHA(github.sha)이며 가지 이름이 아니다. 다른 옵션의 값으로 먹힌 `--target`(`--title --target …`)은 옵션이 아니다(독립 검증 S 의 R-2)."""
    problems = []
    for name, job in _jobs(tree).items():
        for position, step in _steps(job):
            body = step.get("run")
            if not isinstance(body, str):
                continue
            try:
                commands = shell_commands(body)
            except ShellUnsafe:
                continue
            for command in commands:
                words = command_words(command)
                if words[:3] != ["gh", "release", "create"]:
                    continue
                where = f"{name} 단계 {position}"
                options, _positionals, _unknown = _gh_create_parse(words)
                targets = [value for option, value in options if option == "--target"]
                if len(targets) != 1:
                    problems.append(f"W-10: gh release create 에 --target 이 옵션 자리에 정확히 하나여야 한다({where}) — 다른 옵션의 값으로 먹힌 낱말은 세지 않는다")
                    continue
                value = targets[0] or ""
                match = re.fullmatch(r"\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value)
                variable = (match.group(1) or match.group(2)) if match else None
                env = step.get("env") if isinstance(step.get("env"), dict) else {}
                if variable is None or env.get(variable) != "${{ github.sha }}":
                    problems.append(f"W-10: --target 값은 env 로 받은 전체 커밋 SHA(github.sha)여야 한다 — 가지 이름·다른 값이 아니다({where}): {value!r}")
    return problems


def w11(tree):
    """upload-artifact: build 잡에 정확히 하나, 산출물 이름은 release-candidate(받는 쪽과 같다), 경로는 허용 상수의 모양뿐, retention-days 는 1, 없으면 실패. 로그·시험 폴더·*.log 0."""
    problems = []
    uploads = {}
    for name, job in _jobs(tree).items():
        for position, step in _steps(job):
            ref = step.get("uses")
            if not (isinstance(ref, str) and wf.UPLOAD_ACTION.search(ref.split("@")[0])):
                continue
            where = f"{name} 단계 {position}"
            uploads[name] = uploads.get(name, 0) + 1
            with_ = step.get("with") if isinstance(step.get("with"), dict) else {}
            if set(with_) != {"name", "path", "retention-days", "if-no-files-found"}:
                problems.append(f"W-11: upload-artifact 의 with 키가 name·path·retention-days·if-no-files-found 넷이 아니다({where}): {sorted(with_)}")
            if with_.get("name") != ARTIFACT_NAME:
                problems.append(f"W-11: upload-artifact 의 name 은 {ARTIFACT_NAME} 여야 한다(받는 쪽 download-artifact 와 이름이 같아야 한다, {where}): {with_.get('name')!r}")
            if with_.get("retention-days") != "1":
                problems.append(f"W-11: retention-days 는 1 이어야 한다(잡 사이 전달용 — 보존 1일, {where}): {with_.get('retention-days')!r}")
            if with_.get("if-no-files-found") != "error":
                problems.append(f"W-11: if-no-files-found 는 error 여야 한다(빈 업로드가 초록으로 끝나지 않게, {where}): {with_.get('if-no-files-found')!r}")
            paths = [line.strip(" ") for line in str(with_.get("path") or "").split("\n") if line.strip(" ")]                  # ASCII 공백만 자른다(유니코드 공백은 경로의 일부다 — 독립 검증 S 의 S-1)
            if not paths:
                problems.append(f"W-11: upload-artifact 에 path 가 없다({where})")
            for path in paths:
                reason = wf.path_problem(path)
                if reason:
                    problems.append(f"W-11: 올리는 경로가 허용 상수(ALLOWED_UPLOAD_FILES)의 모양이 아니다({where}): {path} — {reason}")
                elif not path.startswith(RELEASE_DIR + "/") or path[len(RELEASE_DIR) + 1:] not in UPLOAD_LEAVES:
                    problems.append(f"W-11: 올리는 경로가 이 워크플로의 후보 파일 여섯({list(UPLOAD_LEAVES)}) 밖이다({where}): {path}")
    for name in _jobs(tree):
        if (name == BUILD and uploads.get(name, 0) != 1) or (name != BUILD and uploads.get(name, 0)):
            problems.append(f"W-11: upload-artifact 는 {BUILD} 잡에 정확히 하나여야 하고 다른 잡에는 없어야 한다 — {name} 에 {uploads.get(name, 0)}개")
    return problems


def w12(tree):
    """모든 잡에 timeout-minutes 가 있다 — build 45 이하, sign-and-draft 15 이하."""
    problems = []
    for name, job in _jobs(tree).items():
        value = job.get("timeout-minutes")
        if not (isinstance(value, str) and value.isascii() and value.isdigit() and 1 <= int(value) <= TIMEOUT_LIMITS.get(name, 0)):          # isascii: 전각 숫자(15)도 isdigit 이고 int 가 되지만 GitHub 가 정수로 읽는다는 보장이 없다(독립 검증 S 의 R-6)
            problems.append(f"W-12: {name} 잡의 timeout-minutes 가 1에서 {TIMEOUT_LIMITS.get(name, 0)} 사이의 정수가 아니다: {value!r}")
    return problems


def w13(tree):
    """concurrency.group 은 release 이고 cancel-in-progress 는 false 다."""
    value = tree.get("concurrency")
    return [] if value == EXPECTED_TOP["concurrency"] else [f"W-13: concurrency 는 group: release·cancel-in-progress: false 여야 한다: {value!r}"]


def w14(tree):
    """environment 는 sign-and-draft 에만 있고 값은 release 다."""
    problems = []
    for name, job in _jobs(tree).items():
        if name == SIGN:
            if job.get("environment") != "release":
                problems.append(f"W-14: {SIGN} 잡의 environment 는 release 여야 한다: {job.get('environment')!r}")
        elif "environment" in job:
            problems.append(f"W-14: environment 는 {SIGN} 에만 있어야 한다: {name}")
    return problems


def _download_hits(body):
    found = []
    try:
        for command in shell_commands(body):
            words = command_words(command)
            if words and words[0].lower() in DOWNLOAD_LOWER:
                found.append(words[0])
    except ShellUnsafe:
        found.append("(읽을 수 없는 글)")
    flat = " ".join(body.split())
    for pattern in DOWNLOAD_PHRASES:
        found += [match.group(0) for match in pattern.finditer(flat)]
    for word in DOWNLOAD_WORDS:
        if re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", flat, re.IGNORECASE) and word not in found:
            found.append(word)
    return found


def w15(tree):
    """바깥 내려받기 명령은 build 잡의 이름이 붙은 정해진 한 단계(빌드 도구 설치)에만 있다. sign-and-draft 에는 어디에도 없다.
    build 잡의 나머지 단계는 sign 잡처럼 허용 명령 목록(정해진 저장소 스크립트의 정해진 명령줄·echo·cat)으로 읽는다 — 낱말 목록(deny-list)에 없는 내려받기(`python -c urllib`·`nc`·`git ls-remote` …)와
    대문자 `CURL`·`PIP` 가 지나가지 못한다(독립 검증 S 의 R-4)."""
    problems = []
    named = 0
    for name, job in _jobs(tree).items():
        for position, step_name, body in run_bodies(job):
            where = f"{name} 단계 {position}({step_name})"
            if name == BUILD and step_name == DOWNLOAD_STEP_NAME and body.rstrip("\n") == DOWNLOAD_COMMAND:
                named += 1
                continue
            hits = _download_hits(body)
            if hits:
                problems.append(f"W-15: 바깥에서 내려받을 수 있는 명령이 정해진 단계({DOWNLOAD_STEP_NAME}) 밖에 있다 — {where}: {sorted(set(hits))}")
            if name == BUILD:
                try:
                    commands = shell_commands(body)
                except ShellUnsafe as error:
                    problems.append(f"W-15: {where} 의 run 을 읽을 수 없다 — {error}")
                    continue
                problems += _shell_shape_problems("W-15", where, commands, BUILD)
    if named != 1:
        problems.append(f"W-15: 빌드 도구 설치 단계({DOWNLOAD_STEP_NAME} — {DOWNLOAD_COMMAND})가 {BUILD} 잡에 정확히 하나여야 한다(지금 {named}개)")
    return problems


def w16(text):
    """같은 글을 기존 규칙(비밀 출력·산출물 허용 목록·액션 고정·승인된 액션 쌍)도 통과한다."""
    problems = [f"W-16: 비밀 출력 규칙(secret_output_problems) — {number}번째 줄: {reason}" for number, reason in wf.secret_output_problems(text)]
    problems += [f"W-16: 산출물 허용 목록 규칙(artifact_problems) — 단계 {number}: {path or '(path 없음)'} {reason}" for number, path, reason in wf.artifact_problems(text)]
    problems += [f"W-16: 액션 고정 규칙(WorkflowPinningTest)에 걸린다: {ref}" for ref in golden.all_action_refs(text) if not SHA_PIN.match(ref)]
    problems += [f"W-16: 승인된 액션 쌍 규칙(workflow_golden)에 걸린다 — {problem}" for problem in golden.action_problems(text)]
    return problems


# ---- 구조 허용 목록 --------------------------------------------------------------------------------------------------------------------------------

def _step_problems(job, position, step, expected):
    name, kind, target, with_, env = expected
    where = f"{job} 단계 {position}"
    problems = []
    extra = sorted(set(step) - STEP_KEYS)
    if extra:
        problems.append(f"구조: 단계 키 — {where} 에 허용되지 않은 키가 있다(if·shell·continue-on-error·working-directory 같은 키를 못 끼운다): {extra}")
    if step.get("name") != name:
        problems.append(f"구조: 단계 이름 — {where} 의 이름이 정해진 것({name})과 다르다: {step.get('name')!r}")
    if kind == "uses":
        if "run" in step or step.get("uses") != f"{target}@{ACTIONS[target]}":
            problems.append(f"구조: 액션 — {where} 는 {target}@{ACTIONS[target]} 를 쓰는 uses 단계여야 한다: {step.get('uses')!r}")
        if step.get("with") != with_:
            problems.append(f"구조: with — {where} 의 with 가 정해진 것과 다르다(키 하나도 더하거나 바꾸지 못한다): {step.get('with')!r}")
        if "env" in step:
            problems.append(f"구조: env — {where} 는 액션 단계라 env 를 못 끼운다")
    else:
        run = step.get("run")
        if "uses" in step or "with" in step or not isinstance(run, str) or run.rstrip("\n") != target:
            problems.append(f"구조: run — {where} 의 run 이 정해진 글과 다르다: {str(run)[:100]!r}")
        if step.get("env") != env:
            problems.append(f"구조: env — {where} 의 env 가 정해진 것과 다르다(환경 변수 하나도 더하거나 바꾸지 못한다): {step.get('env')!r}")
    return problems


def structure(tree):
    problems = []
    if not isinstance(tree, dict) or set(tree) != set(TOP_KEYS):
        return [f"구조: 최상위 키가 정해진 여섯({list(TOP_KEYS)})과 다르다: {sorted(tree) if isinstance(tree, dict) else type(tree).__name__}"]
    for key in ("name", "defaults"):
        if tree[key] != EXPECTED_TOP[key]:
            problems.append(f"구조: {key} — 정해진 값({EXPECTED_TOP[key]!r})이 아니다: {tree[key]!r}")
    jobs = _jobs(tree)
    if tuple(jobs) != JOB_ORDER:
        return problems + [f"구조: 잡 — {list(JOB_ORDER)} 순서의 둘이어야 한다: {list(jobs)}"]
    for name in JOB_ORDER:
        job = jobs[name]
        if set(job) != JOB_KEYS[name]:
            problems.append(f"구조: 잡 키 — {name} 의 키가 정해진 것({sorted(JOB_KEYS[name])})과 다르다(if·strategy·container·services·defaults·outputs·secrets 같은 키를 못 끼운다): {sorted(job)}")
        if job.get("runs-on") != RUNNERS[name]:
            problems.append(f"구조: 러너 — {name} 은 {RUNNERS[name]} 여야 한다: {job.get('runs-on')!r}")
        if job.get("env") != JOB_ENV:
            problems.append(f"구조: 잡 env — {name} 의 env 는 {JOB_ENV} 뿐이어야 한다(PIP_INDEX_URL·프록시·경로 변수를 못 끼운다): {job.get('env')!r}")
        if job.get("name") != JOB_NAMES[name]:
            problems.append(f"구조: 잡 이름 — {name} 의 표시 이름이 정해진 글({JOB_NAMES[name]!r})과 다르다(승인 화면에 보이는 이름이라 식이나 다른 글을 못 넣는다 — 독립 검증 S 의 I-12): {job.get('name')!r}")
        steps = job.get("steps")
        expected = EXPECTED_STEPS[name]
        if not isinstance(steps, list) or len(steps) != len(expected):
            problems.append(f"구조: 단계 목록 — {name} 이 정해진 {len(expected)} 단계와 다르다({len(steps) if isinstance(steps, list) else type(steps).__name__}) — 단계를 더하거나 빼려면 이 목록과 시험을 같이 고친다")
            continue
        for position, (step, wanted) in enumerate(zip(steps, expected), 1):
            problems += _step_problems(name, position, step, wanted) if isinstance(step, dict) else [f"구조: 단계 — {name} 단계 {position} 가 매핑이 아니다"]
        used = {str(step.get("uses")).split("@")[0] for step in steps if isinstance(step, dict) and step.get("uses")}
        if used != JOB_ACTIONS[name]:
            problems.append(f"구조: 액션 — {name} 이 쓰는 액션이 정해진 셋({sorted(JOB_ACTIONS[name])})이 아니다: {sorted(used)}")
    if jobs[SIGN].get("needs") != BUILD:
        problems.append(f"구조: needs — {SIGN} 은 {BUILD} 가 끝난 뒤에만 시작해야 한다: {jobs[SIGN].get('needs')!r}")
    if jobs[BUILD].get("needs") is not None:
        problems.append(f"구조: needs — {BUILD} 는 먼저 도는 잡이다")
    for path, kind, text in _walk(tree):
        if kind == "키" and path[-1] in FLOW_KEYS:
            problems.append(f"구조: 실패를 건너뛰거나 흐름을 바꾸는 키({path[-1]})는 어디에도 못 쓴다 — {_where(path)}")
    return problems


def x1(tree):
    """서명 단계(env 에 UPDATE_SIGNING_KEY 가 있는 단계)는 명령 하나뿐이고 `update_sign.py --manifest …` 에 `--require-shipped-key` 와 `--require-openssl` 을 준다 —
    자체 검증이 경고만 하고 건너뛰어져 앱이 받지 않을 서명이 초안에 오르는 길(설계서 위협 W10)과, 비밀을 받은 단계에 다른 명령이 끼는 길을 막는다."""
    problems = []
    sign = _jobs(tree).get(SIGN) or {}
    steps = [(position, step) for position, step in _steps(sign) if isinstance(step.get("env"), dict) and SECRET_NAME in step["env"]]
    if len(steps) != 1:
        return [f"X-1: 서명 비밀을 받는 단계가 {SIGN} 에 정확히 하나여야 한다(지금 {len(steps)}개)"]
    position, step = steps[0]
    try:
        commands = shell_commands(step["run"]) if isinstance(step.get("run"), str) else []
    except ShellUnsafe:
        commands = []
    if len(commands) != 1:
        return [f"X-1: 서명 비밀을 받는 단계(단계 {position})의 run 은 명령 하나뿐이어야 한다(비밀이 다른 명령에 노출되지 않게)"]
    words = command_words(commands[0])
    if words[:2] != ["python", "scripts/update_sign.py"]:
        problems.append(f"X-1: 서명 단계(단계 {position})는 python scripts/update_sign.py 하나만 불러야 한다: {' '.join(words[:3])}")
    if commands[0]["words"][:1] != ["python"] or commands[0]["sep"] != "plain" or commands[0]["redirects"]:
        problems.append(f"X-1: 서명 단계(단계 {position})의 명령 앞에 제어 낱말·대입(`!`·`if`·`이름=값` …)이나 연결이, 뒤에 방향 바꾸기가 있다 — 서명 명령은 맨 앞에 그대로 있어야 한다(`!` 가 붙으면 실패해도 단계가 초록이 된다)")
    for flag in ("--manifest", "--require-shipped-key", "--require-openssl"):
        if flag not in words:
            problems.append(f"X-1: 서명 단계(단계 {position})에 {flag} 가 없다 — 자체 검증이 건너뛰어지면 앱이 받지 않을 서명이 초안에 오를 수 있다")
    return problems


def x2(tree):
    """sign-and-draft 의 순서 — 받기 → 후보 검증(verify-candidate) → 매니페스트 만들기(build) → 서명 → 해시 목록(sums) → 사슬 다시 확인(check --phase final) → 초안 만들기(gh release create), 릴리스 본문(notes)은 초안보다 앞.
    후보 대조를 건너뛰고 서명하거나, 서명 전에 초안을 만들거나, 서명 뒤 해시 목록·사슬 확인 없이 초안을 만드는 길이 없다."""
    sign = _jobs(tree).get(SIGN) or {}
    marks = {"받기": [], "후보 검증": [], "매니페스트": [], "서명": [], "해시 목록": [], "사슬 확인": [], "본문": [], "초안": []}
    for position, step in _steps(sign):
        if isinstance(step.get("uses"), str) and step["uses"].split("@")[0] == "actions/download-artifact":
            marks["받기"].append(position)
        if isinstance(step.get("run"), str):
            try:
                commands = shell_commands(step["run"])
            except ShellUnsafe:
                continue
            for command in commands:
                words = command_words(command)
                if words[:2] == ["python", "scripts/update_manifest.py"] and words[2:3] == ["verify-candidate"]:
                    marks["후보 검증"].append(position)
                elif words[:2] == ["python", "scripts/update_manifest.py"] and words[2:3] == ["build"]:
                    marks["매니페스트"].append(position)
                elif words[:2] == ["python", "scripts/update_sign.py"]:
                    marks["서명"].append(position)
                elif words[:2] == ["python", "packaging/release_chain.py"] and words[2:3] == ["sums"]:
                    marks["해시 목록"].append(position)
                elif words[:2] == ["python", "packaging/release_chain.py"] and words[2:3] == ["check"] and "--phase" in words and words[words.index("--phase") + 1:words.index("--phase") + 2] == ["final"]:
                    marks["사슬 확인"].append(position)
                elif words[:2] == ["python", "packaging/release_chain.py"] and words[2:3] == ["notes"]:
                    marks["본문"].append(position)
                elif words[:3] == ["gh", "release", "create"]:
                    marks["초안"].append(position)
    problems = [f"X-2: {SIGN} 에 '{label}' 단계가 정확히 하나여야 한다(지금 {len(found)}개)" for label, found in marks.items() if label != "초안" and len(found) != 1]
    if not marks["초안"]:
        problems.append(f"X-2: {SIGN} 에 초안을 만드는 gh release create 단계가 없다")
    if not problems:
        order = [marks["받기"][0], marks["후보 검증"][0], marks["매니페스트"][0], marks["서명"][0], marks["해시 목록"][0], marks["사슬 확인"][0], min(marks["초안"])]
        if order != sorted(order) or len(set(order)) != len(order):
            problems.append(f"X-2: 순서가 받기 → 후보 검증 → 매니페스트 만들기 → 서명 → 해시 목록 → 사슬 확인(final) → 초안 만들기가 아니다(단계 번호 {order})")
        if marks["본문"][0] > min(marks["초안"]):
            problems.append("X-2: 릴리스 본문 만들기는 초안 만들기보다 앞이어야 한다")
    return problems


def x3(tree):
    """뼈대를 규칙으로도 지킨다 — 최상위 키는 정해진 여섯뿐이고(대소문자만 다른 `Permissions`·`env` 같은 키가 없다), 잡의 키는 정해진 것뿐이며, 어디에도 실패를 건너뛰거나 흐름을 바꾸는 키(`if`·`continue-on-error`·`strategy` …)가 없고,
    단계는 모두 매핑이며 키가 정해진 다섯뿐이고 이름이 있으며 잡 안에서 서로 다르다. 구조 허용 목록이 이미 글자 그대로 못박고 있어도, 목록을 같이 고친 변경에서 이 뼈대가 무너지지 않게 하는 둘째 그물(독립 검증 S 의 YML07·YML53·YML62·YML68)."""
    problems = []
    if not isinstance(tree, dict) or set(tree) != set(TOP_KEYS):
        problems.append(f"X-3: 최상위 키가 정해진 여섯({list(TOP_KEYS)})이 아니다 — 다른 키(env·대소문자만 다른 permissions 등)를 못 둔다: {sorted(tree) if isinstance(tree, dict) else type(tree).__name__}")
    for path, kind, _text in _walk(tree):
        if kind == "키" and path[-1] in FLOW_KEYS:
            problems.append(f"X-3: 실패를 건너뛰거나 흐름을 바꾸는 키({path[-1]})는 어디에도 못 쓴다 — {_where(path)}")
    for name, job in _jobs(tree).items():
        if name in JOB_KEYS and set(job) != JOB_KEYS[name]:
            problems.append(f"X-3: {name} 잡의 키가 정해진 것({sorted(JOB_KEYS[name])})과 다르다: {sorted(job)}")
        steps = job.get("steps")
        if not isinstance(steps, list):
            problems.append(f"X-3: {name} 잡의 steps 가 목록이 아니다")
            continue
        names = []
        for position, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                problems.append(f"X-3: {name} 단계 {position} 가 매핑이 아니다 — 단계는 키와 값을 가진 매핑이어야 한다")
                continue
            extra = sorted(set(step) - STEP_KEYS)
            if extra:
                problems.append(f"X-3: {name} 단계 {position} 에 허용되지 않은 키가 있다(if·shell·continue-on-error·working-directory·id 같은 키를 못 끼운다): {extra}")
            if not (isinstance(step.get("name"), str) and step["name"].strip()):
                problems.append(f"X-3: {name} 단계 {position} 에 이름이 없다(단계마다 이름을 붙여 로그가 갈리게 한다)")
            names.append(step.get("name"))
        repeated = sorted({item for item in names if isinstance(item, str) and names.count(item) > 1})
        if repeated:
            problems.append(f"X-3: {name} 잡에 같은 이름의 단계가 둘 이상이다(로그가 갈리지 않는다): {repeated}")
    return problems


CHECKS = (("W-1", w1), ("W-2", w2), ("W-3", w3), ("W-4", w4), ("W-5", w5), ("W-6", w6), ("W-8", w8), ("W-10", w10), ("W-11", w11), ("W-12", w12), ("W-13", w13), ("W-14", w14), ("W-15", w15), ("X-1", x1), ("X-2", x2), ("X-3", x3))


def release_violations(text):
    """워크플로 글이 어긴 규칙의 목록(없으면 빈 목록). 읽을 수 없는 표기는 구조 문제 하나로 돌려준다(예외를 내지 않는다)."""
    text = text.replace("\r\n", "\n")
    try:
        tree = yamlsub.load(text)
    except yamlsub.YamlSubsetError as error:
        return [f"구조: 읽을 수 없는 표기 — {error}"]
    if not isinstance(tree, dict) or not isinstance(tree.get("jobs"), dict):
        return [f"구조: 최상위가 매핑이 아니거나 jobs 가 없다: {type(tree).__name__}"]
    problems = []
    runs = [(label, lambda check=check: check(tree)) for label, check in CHECKS]
    runs += [("W-7", lambda: w7(tree, text)), ("W-9", lambda: w9(tree, text)), ("W-16", lambda: w16(text)), ("구조", lambda: structure(tree))]
    for label, run in runs:
        try:
            problems += run()
        except Exception as error:                                              # 검사기가 모르는 모양을 만나도 통과로 넘기지 않는다
            problems.append(f"{label}: 검사 중 예외 {type(error).__name__} — 읽을 수 없는 모양이다")
    return problems
