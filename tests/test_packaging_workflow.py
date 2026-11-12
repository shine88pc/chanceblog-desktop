"""빌드 워크플로 초안(`.github/workflows/package.yml` — T3, 운영자 승인 전에는 병합하지 않는다)의 규칙 시험.

초안은 이 가지에 없고(별도 가지 `ai/claude/NO-MERGE-pckit-workflow` 에만 있다) 이 시험은 두 가지를 한다:
  ① **규칙 검사 자체**를 좋은 글·나쁜 글로 시험한다(`tests/packaging_support.py` 의 `workflow_violations`) — 수동 실행만·읽기 권한만·windows-latest·Python 3.12·전체 SHA 고정·비밀 값 0·서명 단계 0·
     올리는 산출물은 압축 파일·SHA256SUMS·PACKAGE_INFO.* 뿐(보존 14일·없으면 실패)·시험 빌드 옵션 없음.
  ② `.github/workflows/package.yml` 이 **있으면**(승인 뒤 병합되면, 또는 초안 가지에서) 그 파일이 규칙을 지켜야 한다 — 없으면 건너뛴다.
네트워크·GitHub 없이 글만 읽는다.
"""
import re
import unittest

import packaging_support as ps

SHA = "0123456789abcdef0123456789abcdef01234567"
GOOD = f"""name: "Package"
# 주석 안의 secrets.TOKEN 이나 write 낱말은 센 것이 아니다
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  package:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@{SHA}  # v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@{SHA}  # v5
        with:
          python-version: '3.12'
      - run: python -m pip install -r packaging/requirements-package.txt
      - run: python packaging/build_package.py --out-dir "$env:RUNNER_TEMP/package"
      - uses: actions/upload-artifact@{SHA}  # v4
        with:
          name: ChanceBlogDesktop-preview
          path: |
            ${{{{ runner.temp }}}}/package/release/ChanceBlogDesktop-*-win64.zip
            ${{{{ runner.temp }}}}/package/release/SHA256SUMS
            ${{{{ runner.temp }}}}/package/release/PACKAGE_INFO.md
            ${{{{ runner.temp }}}}/package/release/PACKAGE_INFO.json
          retention-days: 14
          if-no-files-found: error
"""


def mutate(old, new, count=1):
    assert GOOD.count(old) == count, (old, GOOD.count(old))
    return GOOD.replace(old, new)


class RuleCheckerTest(unittest.TestCase):
    def test_the_good_sample_has_no_violation(self):
        self.assertEqual(ps.workflow_violations(GOOD), [])

    def test_crlf_line_endings_do_not_change_the_verdict(self):
        self.assertEqual(ps.workflow_violations(GOOD.replace("\n", "\r\n")), [])

    def test_each_bad_variant_is_caught(self):
        bad = {
            "push trigger": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  push:\n"),
            "pull_request trigger": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  pull_request:\n"),
            "schedule trigger": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  schedule:\n    - cron: '0 0 * * *'\n"),
            "workflow_run trigger": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_run:\n    workflows: ['x']\n"),
            "push only": mutate("on:\n  workflow_dispatch:\n", "on:\n  push:\n"),
            "inline on list": mutate("on:\n  workflow_dispatch:\n", "on: [push, workflow_dispatch]\n"),
            "no on": mutate("on:\n  workflow_dispatch:\n", ""),
            "write permission": mutate("contents: read", "contents: write"),
            "extra permission": mutate("  contents: read\n", "  contents: read\n  id-token: write\n"),
            "no permissions": mutate("permissions:\n  contents: read\n", ""),
            "read-all": mutate("permissions:\n  contents: read\n", "permissions: read-all\n"),
            "ubuntu runner": mutate("windows-latest", "ubuntu-latest"),
            "two runners": mutate("    runs-on: windows-latest\n", "    runs-on: windows-latest\n  other:\n    runs-on: ubuntu-latest\n"),
            "python 3.11": mutate("'3.12'", "'3.11'"),
            "unpinned action": mutate(f"actions/checkout@{SHA}", "actions/checkout@v4"),
            "short sha": mutate(f"actions/setup-python@{SHA}", "actions/setup-python@0123456"),
            "secret value": mutate("      - run: python -m pip install -r", "      - env:\n          K: ${{ secrets.KEY }}\n        run: python -m pip install -r"),
            "github token": mutate("persist-credentials: false", "persist-credentials: false\n          token: ${{ github.token }}"),
            "signing step": mutate("      - uses: actions/upload-artifact", "      - run: signtool sign /f x.pfx ChanceBlogDesktop.exe\n      - uses: actions/upload-artifact"),
            "azure signing": mutate("      - uses: actions/upload-artifact", "      - uses: azure/trusted-signing-action@" + SHA + "\n      - uses: actions/upload-artifact"),
            "log upload": mutate("PACKAGE_INFO.json\n", "PACKAGE_INFO.json\n            ${{ runner.temp }}/package/build.log\n"),
            "wildcard upload": mutate("ChanceBlogDesktop-*-win64.zip", "*"),
            "work folder upload": mutate("package/release/SHA256SUMS", "package/work/SHA256SUMS"),
            "data folder upload": mutate("package/release/PACKAGE_INFO.md", "package/release/ChanceblogDesktop/chanceblog.db"),
            "outside release folder": mutate("package/release/PACKAGE_INFO.md", "package/PACKAGE_INFO.md"),
            "retention 30": mutate("retention-days: 14", "retention-days: 30"),
            "retention 1": mutate("retention-days: 14", "retention-days: 1"),
            "no retention": mutate("          retention-days: 14\n", ""),
            "no error on empty": mutate("if-no-files-found: error", "if-no-files-found: warn"),
            "no empty check": mutate("          if-no-files-found: error\n", ""),
            "no upload": GOOD[:GOOD.index("      - uses: actions/upload-artifact")],
            "no build script": mutate("python packaging/build_package.py", "python -c pass"),
            "trial flag": mutate('build_package.py --out-dir', "build_package.py --allow-missing-gate --out-dir"),
        }
        for name, text in bad.items():
            with self.subTest(name=name):
                self.assertNotEqual(ps.workflow_violations(text), [], name)

    def test_a_single_path_upload_is_checked_too(self):
        single = mutate("path: |\n            ${{ runner.temp }}/package/release/ChanceBlogDesktop-*-win64.zip\n            ${{ runner.temp }}/package/release/SHA256SUMS\n            ${{ runner.temp }}/package/release/PACKAGE_INFO.md\n            ${{ runner.temp }}/package/release/PACKAGE_INFO.json\n",
                        "path: ${{ runner.temp }}/package/release/SHA256SUMS\n")
        self.assertEqual(ps.workflow_violations(single), [])
        self.assertNotEqual(ps.workflow_violations(single.replace("release/SHA256SUMS", "release/other.log")), [])

    def test_backslash_paths_are_read_the_same_way(self):
        backslash = GOOD.replace("/package/release/", chr(92) + "package" + chr(92) + "release" + chr(92))
        self.assertEqual(ps.workflow_violations(backslash), [])

    def test_the_messages_name_the_rule_that_was_broken(self):
        self.assertIn("workflow_dispatch", " ".join(ps.workflow_violations(mutate("on:\n  workflow_dispatch:\n", "on:\n  push:\n"))))
        self.assertIn("retention-days", " ".join(ps.workflow_violations(mutate("retention-days: 14", "retention-days: 30"))))
        self.assertIn("허용 목록", " ".join(ps.workflow_violations(mutate("ChanceBlogDesktop-*-win64.zip", "everything.zip"))))
        self.assertIn("SHA", " ".join(ps.workflow_violations(mutate(f"actions/checkout@{SHA}", "actions/checkout@v4"))))

    def test_comments_do_not_count_as_secrets_or_write_permissions(self):
        self.assertIn("# 주석 안의 secrets.TOKEN", GOOD)
        self.assertEqual(ps.workflow_violations(GOOD), [])


class RealWorkflowTest(unittest.TestCase):
    """초안이 `.github/workflows/package.yml` 로 있으면 규칙을 지켜야 한다(이 가지에는 없다 — 있어야 하는 곳은 초안 가지와 승인 뒤의 병합 가지)."""

    def test_the_workflow_file_if_present_follows_every_rule(self):
        path = ps.ROOT / ".github" / "workflows" / "package.yml"
        if not path.exists():
            self.skipTest("package.yml 이 이 가지에 없다(T3 초안은 별도 가지에 있다)")
        text = path.read_text(encoding="utf-8")
        self.assertEqual(ps.workflow_violations(text), [])
        self.assertNotIn("${{ inputs.", text)                                         # 입력칸이 없다 — 글을 받아 명령에 넣는 길이 없다
        self.assertIsNone(re.search(r"(?m)^\s+-\s*run:.*\$\{\{\s*github\.event", text))

    def test_the_other_workflows_are_not_asked_to_follow_these_rules_and_still_exist(self):
        for name in ("ci.yml", "auto-pr.yml"):
            self.assertTrue((ps.ROOT / ".github" / "workflows" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
