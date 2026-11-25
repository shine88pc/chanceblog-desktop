"""설치 도구 시험(spike) 수동 워크플로 `.github/workflows/installer-spike.yml`(T3 — 운영자 확인 037 ① 승인 범위: 수동 실행·읽기 권한·비밀 0·액션 SHA 고정·보고서 둘만 올리기, 병합과 실행은 운영자만)의 규칙 시험(결정 D-700).

글만 읽는다(네트워크·GitHub 없이, PyYAML 없이 — 앱 CI 네 칸에서 같은 방식으로 돈다). 본체 `package.yml`·`package-ocr.yml` 의 시험과 같은 모양이다. 지키는 것:
  트리거는 `workflow_dispatch` 하나이고 입력칸이 없다 · `permissions` 는 최상위 `contents: read` 하나 · `secrets.`·토큰 0 · 모든 `uses:` 가 40자리 SHA 이고 `package.yml` 이 쓰는 것과 같은 것뿐(새 액션 0, 태그 고정 0) ·
  `run:` 안에 달러 중괄호 식이 하나도 없음 · `run:` 한 단계에 명령 하나 · pip 설치는 잠금 파일 한 줄뿐 · 도구 받기는 `fetch_tools.py --dest` 한 단계(잠금 바꿔 끼우기 없음, 호스트는 스크립트 안에서 고정) · 올리는 것은 보고서 둘뿐
  (이름·보존 14일·없으면 실패) · 단계 순서(받기, 설치, 묶음, 설치 파일, 측정, 보고, 올리기) · `if`·`continue-on-error` 없음.
그 위에 **글을 구조로 읽는 허용 목록 규칙**(`tests/workflow_yaml_support.py` 의 작은 읽개 — 흐름식·앵커·겹친 키 같은 다른 표기는 읽을 수 없다고 거절): 최상위·작업·단계 키와 액션별 `with` 키, 작업 `env`, 열 단계의 명령이 정해진 글과 같다.
이 규칙 검사 자체도 좋은 글·나쁜 글로 시험한다(어기는 변형 45가지 안팎이 실제로 걸리는지). 이 워크플로가 GitHub 러너에서 실제로 도는지는 여기서 확인할 수 없다(병합 뒤 운영자가 수동 실행).
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer_spike_support as support  # noqa: E402
import test_workflow_artifacts as wf  # noqa: E402

ROOT = support.ROOT
WORKFLOW = support.WORKFLOW
REAL = WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n") if WORKFLOW.exists() else ""
REFS = set(support.uses_refs(support.REFERENCE.read_text(encoding="utf-8"))) if support.REFERENCE.exists() else set()
CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
SETUP = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
UPLOAD = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"
FETCH_LINE = '        run: python packaging/spike/fetch_tools.py --dest "$env:RUNNER_TEMP/spike/tools"\n'
MEASURE_LINE = '        run: python packaging/spike/run_spike.py measure --work "$env:RUNNER_TEMP/spike"\n'
PACK_LINE = '        run: python packaging/spike/run_spike.py pack --work "$env:RUNNER_TEMP/spike"\n'
REPORT_PATH_MD = "            ${{ runner.temp }}/spike/report/INSTALLER_SPIKE_REPORT.md\n"


def mutate(old, new, count=1):
    assert REAL.count(old) == count, (old, REAL.count(old))
    return REAL.replace(old, new)


class RealWorkflowTest(unittest.TestCase):
    def test_the_files_exist_and_the_reference_workflow_pins_three_actions(self):
        self.assertTrue(WORKFLOW.is_file(), "installer-spike.yml 이 있어야 한다(NO-MERGE 가지의 준비물)")
        self.assertTrue(support.REFERENCE.is_file(), "기준 package.yml 이 있어야 한다 — 없으면 새 액션 0 을 견줄 수 없다")
        self.assertEqual({ref.split("@")[0] for ref in REFS}, support.ACTION_NAMES)
        self.assertEqual(len(REFS), 3)
        self.assertEqual(REFS, {CHECKOUT, SETUP, UPLOAD})

    def test_the_workflow_follows_every_rule(self):
        self.assertEqual(support.violations(REAL, REFS), [])

    def test_every_action_is_the_very_same_pinned_reference_package_yml_uses(self):
        refs = support.uses_refs(REAL)
        self.assertEqual(sorted(refs), sorted(REFS))
        for ref in refs:
            self.assertRegex(ref, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")            # test_repo_layout 의 SHA 고정 시험과 같은 모양

    def test_the_other_existing_guards_accept_it_too(self):
        self.assertEqual(wf.artifact_problems(REAL), [])
        self.assertEqual(wf.secret_output_problems(REAL), [])
        self.assertEqual(wf.main_upload_notes({"installer-spike.yml": REAL}), [], "새 워크플로 파일의 업로드는 알림 대상이 아니다")
        self.assertIn("installer-spike.yml", wf.workflow_texts())

    def test_there_is_exactly_one_upload_and_its_two_files_fit_the_allowed_shapes(self):
        uploads = wf.upload_steps(REAL)
        self.assertEqual(len(uploads), 1)
        paths = wf.upload_paths(uploads[0][1])
        self.assertEqual(len(paths), 2)
        for path in paths:
            self.assertEqual(wf.path_problem(path), "", path)
        self.assertEqual(sorted(path.rsplit("/", 1)[1] for path in paths), ["INSTALLER_SPIKE_REPORT.json", "INSTALLER_SPIKE_REPORT.md"])
        self.assertTrue(set(path.rsplit("/", 1)[1] for path in paths) <= set(wf.ALLOWED_UPLOAD_FILES))

    def test_the_trigger_is_manual_only_with_no_input_and_nothing_else_can_start_it(self):
        code = support.code_of(REAL)
        self.assertEqual([line for line in support.top_block(code, "on") if line.strip()], ["  workflow_dispatch:"])
        for word in ("push", "pull_request", "pull_request_target", "schedule", "workflow_run", "workflow_call", "repository_dispatch", "inputs", "release:"):
            self.assertNotIn(word, "\n".join(support.top_block(code, "on")), word)
        self.assertNotIn("${{ inputs.", REAL)
        self.assertNotIn("github.event", REAL)

    def test_the_permissions_are_read_only_once_at_the_top_and_no_secret_or_token_appears_anywhere(self):
        code = support.code_of(REAL)
        self.assertEqual([line for line in support.top_block(code, "permissions") if line.strip()], ["  contents: read"])
        self.assertEqual(len(re.findall(r"(?m)^\s*permissions:", code)), 1)
        for word in ("secrets", "GITHUB_TOKEN", "github.token", "write", "id-token", "environment:"):
            self.assertNotIn(word, code, word)

    def test_run_lines_have_no_expression_and_each_step_runs_one_command(self):
        bodies = support.run_bodies(REAL)
        self.assertEqual(len(bodies), 7)
        for body in bodies:
            self.assertNotIn("${{", body)
            lines = [line for line in body.splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            self.assertTrue(support.one_command(lines[0]), lines[0])

    def test_the_scripts_the_workflow_runs_exist_and_know_the_five_commands(self):
        for name in ("fetch_tools.py", "run_spike.py"):
            self.assertTrue((support.SPIKE / name).is_file(), name)
        source = (support.SPIKE / "run_spike.py").read_text(encoding="utf-8")
        for command in support.SPIKE_COMMANDS:
            self.assertIn(f'"{command}"', source, command)

    def test_the_download_step_uses_only_the_script_with_the_fixed_hosts_and_the_lock_default(self):
        fetch = support.load("fetch_tools")
        self.assertEqual(fetch.FIXED_HOSTS, ("github.com",))
        self.assertEqual(fetch.REDIRECT_HOSTS, ("release-assets.githubusercontent.com", "objects.githubusercontent.com"))
        self.assertEqual(Path(fetch.DEFAULT_LOCK), support.SPIKE / "tools.lock.json")
        joined = "\n".join(support.run_bodies(REAL))
        self.assertEqual(joined.count("fetch_tools.py"), 1)
        for tool in support.NETWORK_TOOLS:
            self.assertNotIn(tool, joined, tool)

    def test_the_comment_header_has_no_address_scheme_tilde_or_double_brace_and_names_the_approval(self):
        comments = "\n".join(line for line in REAL.splitlines() if line.lstrip().startswith("#"))
        self.assertIsNone(re.search(r"(?i)(https?|ftp)://|www[.]", comments))
        self.assertNotIn(chr(0x7E), comments)
        self.assertNotIn("{{", comments)
        for needle in ("확인 037", "T3", "NO-MERGE", "수동 실행", "docs/INSTALLER_SPIKE_RUN.md"):
            self.assertIn(needle, comments, needle)

    def test_the_artifact_and_job_names_are_what_the_run_guide_tells_the_operator_to_look_for(self):
        self.assertIn('name: "Installer spike', REAL)
        self.assertIn("InstallerSpike-report", REAL)
        guide = support.ROOT / "docs" / "INSTALLER_SPIKE_RUN.md"
        if guide.exists():
            text = guide.read_text(encoding="utf-8")
            self.assertIn("Installer spike", text)
            self.assertIn("InstallerSpike-report", text)


class RuleSelfTest(unittest.TestCase):
    """규칙이 실제로 걸리는지 — 어기는 변형은 빨개지고 진짜 글은 통과한다(설계서 5절의 변이 다섯 — push 추가·write 권한·태그 고정·로그 업로드·secrets 참조 — 와 그 밖의 변형)."""

    def variants(self):
        step_after_python = f"      - uses: {SETUP}  # v5.6.0\n        with:\n          python-version: '3.12'\n"
        return {
            # 설계서 5절의 변이 다섯
            "① push 추가": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  push:\n"),
            "② write 권한": mutate("permissions:\n  contents: read\n", "permissions:\n  contents: write\n"),
            "③ 태그로 고정": mutate(CHECKOUT, "actions/checkout@v4"),
            "④ 로그 업로드": mutate(REPORT_PATH_MD, REPORT_PATH_MD + "            ${{ runner.temp }}/spike/logs/build.log\n"),
            "⑤ secrets 참조": mutate(FETCH_LINE, FETCH_LINE.rstrip("\n") + " ${{ secrets.KEY }}\n"),
            # 트리거
            "pull_request 추가": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  pull_request:\n"),
            "schedule 추가": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  schedule:\n    - cron: '0 0 * * *'\n"),
            "workflow_run 으로 바꿈": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_run:\n    workflows: ['x']\n"),
            "workflow_call 추가": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  workflow_call:\n"),
            "입력칸 추가": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n    inputs:\n      note:\n        type: string\n"),
            "한 줄 흐름식 on": mutate("on:\n  workflow_dispatch:\n", "on: [push, workflow_dispatch]\n"),
            "on 없음": mutate("on:\n  workflow_dispatch:\n", ""),
            # 권한
            "id-token 권한 추가": mutate("permissions:\n  contents: read\n", "permissions:\n  contents: read\n  id-token: write\n"),
            "권한 블록 없음": mutate("permissions:\n  contents: read\n\n", ""),
            "read-all 로 바꿈": mutate("permissions:\n  contents: read\n", "permissions: read-all\n"),
            "작업 단위 권한 추가": mutate("    timeout-minutes: 60\n", "    timeout-minutes: 60\n    permissions:\n      contents: read\n"),
            "github.token 사용": mutate(FETCH_LINE, FETCH_LINE.rstrip("\n") + " ${{ github.token }}\n"),
            "GITHUB_TOKEN 환경 변수": mutate("      DOTNET_NOLOGO: '1'\n", "      DOTNET_NOLOGO: '1'\n      GITHUB_TOKEN: x\n"),
            # 러너·파이썬·시간
            "ubuntu 러너": mutate("windows-latest", "ubuntu-latest"),
            "파이썬 3.11": mutate("'3.12'", "'3.11'"),
            "시간 한도 61": mutate("timeout-minutes: 60", "timeout-minutes: 61"),
            "둘째 작업": mutate("\n      # checkout·setup-python", "\n  other:\n    runs-on: windows-latest\n    steps:\n      - run: echo hi\n\n    # checkout·setup-python"),
            # 액션
            "짧은 SHA": mutate(SETUP, "actions/setup-python@0123456"),
            "다른 SHA": mutate(CHECKOUT, "actions/checkout@" + OTHER_SHA),
            "새 액션(cache)": mutate(step_after_python, step_after_python + f"\n      - uses: actions/cache@{OTHER_SHA}\n        with:\n          path: x\n          key: y\n"),
            "persist-credentials 꺼짐 아님": mutate("persist-credentials: false", "persist-credentials: true"),
            # 올리기
            "설치 파일 업로드": mutate(REPORT_PATH_MD, REPORT_PATH_MD + "            ${{ runner.temp }}/spike/out/ChanceBlogSpike-0.0.1-Setup.exe\n"),
            "와일드카드 폴더 업로드": mutate(REPORT_PATH_MD, "            ${{ runner.temp }}/spike/**/INSTALLER_SPIKE_REPORT.md\n"),
            "보고서 하나만": mutate(REPORT_PATH_MD, ""),
            "보존 30일": mutate("retention-days: 14", "retention-days: 30"),
            "보존 칸 없음": mutate("          retention-days: 14\n", ""),
            "없어도 경고만": mutate("if-no-files-found: error", "if-no-files-found: warn"),
            "산출물 이름 바꿈": mutate("name: InstallerSpike-report", "name: everything"),
            "업로드 둘": mutate("          if-no-files-found: error\n", "          if-no-files-found: error\n\n      - uses: " + UPLOAD + "\n        with:\n          name: again\n          path: ${{ runner.temp }}/spike/report/INSTALLER_SPIKE_REPORT.md\n          retention-days: 14\n          if-no-files-found: error\n"),
            # 단계에 끼워 넣기
            "단계에 if": mutate(MEASURE_LINE, "        if: always()\n" + MEASURE_LINE),
            "단계에 continue-on-error": mutate(MEASURE_LINE, "        continue-on-error: true\n" + MEASURE_LINE),
            "단계에 env": mutate(MEASURE_LINE, "        env:\n          X: '1'\n" + MEASURE_LINE),
            "단계에 shell": mutate(MEASURE_LINE, "        shell: cmd\n" + MEASURE_LINE),
            "단계에 working-directory": mutate(MEASURE_LINE, "        working-directory: packaging\n" + MEASURE_LINE),
            "run 에 명령 둘": mutate(MEASURE_LINE, MEASURE_LINE.rstrip("\n") + "; python x.py\n"),
            "run 에 달러 중괄호 식": mutate(MEASURE_LINE, MEASURE_LINE.rstrip("\n") + " ${{ github.sha }}\n"),
            "curl 사용": mutate(MEASURE_LINE, '        run: curl -O "$env:X"\n'),
            "pip 색인 바꿈": mutate("run: python -m pip install -r packaging/requirements-package.txt", "run: python -m pip install --index-url x -r packaging/requirements-package.txt"),
            "pip 다른 패키지": mutate("run: python -m pip install -r packaging/requirements-package.txt", "run: python -m pip install velopack"),
            "도구 받기 잠금 바꿔 끼움": mutate(FETCH_LINE, FETCH_LINE.rstrip("\n") + " --lock other.json\n"),
            "도구 받기 폴더 바꿈": mutate('--dest "$env:RUNNER_TEMP/spike/tools"', '--dest "C:/tools"'),
            "작업 폴더 바꿈": mutate(MEASURE_LINE, '        run: python packaging/spike/run_spike.py measure --work "C:/spike"\n'),
            "다른 스크립트 실행": mutate(MEASURE_LINE, MEASURE_LINE.replace("run_spike.py", "other.py")),
            "단계 이름 없음": mutate("      - name: 보고서와 작업 요약 결과 블록 만들기\n        run:", "      - run:"),
            # 구조(허용 목록)
            "측정 단계 삭제": mutate("      - name: 측정(M01에서 M22, 바깥 접속 차단 규칙을 넣은 채)\n" + MEASURE_LINE + "\n", ""),
            "단계 순서 바꿈": REAL.replace(PACK_LINE, "@@PACK@@").replace(MEASURE_LINE, PACK_LINE).replace("@@PACK@@", MEASURE_LINE),
            "작업 env 에 색인 추가": mutate("      DOTNET_NOLOGO: '1'\n", "      DOTNET_NOLOGO: '1'\n      PIP_INDEX_URL: x\n"),
            "작업에 environment": mutate("    timeout-minutes: 60\n", "    timeout-minutes: 60\n    environment: release\n"),
            "최상위 env 추가": mutate("jobs:\n", "env:\n  X: '1'\n\njobs:\n"),
            "동시 실행 취소 켬": mutate("cancel-in-progress: false", "cancel-in-progress: true"),
            "보이지 않는 글자": mutate("# 수동 실행(workflow_dispatch)만이다", "# 수동 실행(workflow_dispatch)만이다" + chr(0x2028) + "  push:"),
        }

    def test_the_real_text_is_clean_and_every_variant_is_caught(self):
        self.assertEqual(support.violations(REAL, REFS), [])
        variants = self.variants()
        self.assertGreaterEqual(len(variants), 45)
        for name, text in variants.items():
            with self.subTest(variant=name):
                self.assertNotEqual(text, REAL, name + ": 변형이 글을 바꾸지 않았다")
                self.assertNotEqual(support.violations(text, REFS), [], name + " 는 걸려야 한다")

    def test_crlf_line_endings_do_not_change_the_verdict(self):
        self.assertEqual(support.violations(REAL.replace("\n", "\r\n"), REFS), [])

    def test_comments_do_not_count_as_secrets_write_or_triggers(self):
        text = REAL.replace("# T3(.github 변경)", "# secrets.TOKEN write push pull_request schedule: 낱말은 주석이라 센 것이 아니다 T3(.github 변경)")
        self.assertIn("# secrets.TOKEN write push", text)
        self.assertEqual(support.violations(text, REFS), [])

    def test_the_messages_name_the_rule_that_was_broken(self):
        self.assertIn("workflow_dispatch", " ".join(support.violations(mutate("on:\n  workflow_dispatch:\n", "on:\n  push:\n"), REFS)))
        self.assertIn("retention-days", " ".join(support.violations(mutate("retention-days: 14", "retention-days: 30"), REFS)))
        self.assertIn("SHA", " ".join(support.violations(mutate(CHECKOUT, "actions/checkout@v4"), REFS)))
        self.assertIn("허용 목록", " ".join(support.violations(mutate(REPORT_PATH_MD, REPORT_PATH_MD + "            ${{ runner.temp }}/spike/logs/build.log\n"), REFS)))
        self.assertIn("순서", " ".join(support.violations(REAL.replace(PACK_LINE, "@@PACK@@").replace(MEASURE_LINE, PACK_LINE).replace("@@PACK@@", MEASURE_LINE), REFS)))

    def test_one_command_reads_powershell_joiners(self):
        for good in ('python packaging/spike/run_spike.py pack --work "$env:RUNNER_TEMP/spike"', "python -m pip install -r packaging/requirements-package.txt", "& python x.py a b"):
            self.assertTrue(support.one_command(good), good)
        for bad in ("python a.py; python b.py", "python a.py && python b.py", "python a.py | tee x", "python a.py & python b.py", "python `a.py", "python $(whoami)", "python a.py || exit 1"):
            self.assertFalse(support.one_command(bad), bad)

    def test_a_workflow_with_nothing_wrong_in_a_different_but_equal_spelling_still_passes(self):
        reordered_comments = REAL.replace("# 수동 실행(workflow_dispatch)만이다", "# 주석 줄을 앞에 하나 더 둔다\n# 수동 실행(workflow_dispatch)만이다")
        self.assertEqual(support.violations(reordered_comments, REFS), [])


if __name__ == "__main__":
    unittest.main()
