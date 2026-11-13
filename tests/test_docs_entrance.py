"""입구 문서·시험지가 실제 화면·워크플로·코드와 맞는지 지키는 시험(L1: F031·F084·F085) — 문서만 고치고 끝나지 않게, 고친 문장이 말하는 사실을 코드·워크플로의 값에 묶어 둔다.

지키는 것:
  1) 시험지(`docs/PERSONAL_PC_TEST.md`)의 화면 설명이 실제 배치와 같다 — 블로그 카드 목록은 왼쪽(가장 좁은 창에서는 위쪽), 후보 상세는 오른쪽 상세 창(좁으면 서랍)이고 `이 주제로 만들기` 는 그 맨 아래에 붙어 있으며,
     설정 화면은 '연결 관리' 카드(맨 끝 줄 `정보`) → `백업·복원` 카드 → 맨 아래 `내 글 문체 참고값 보기` 카드 순서다(기본 창 1440 폭·가장 좁은 창 900 폭 — 앱의 `LAYOUT["window"]`·`LAYOUT["window_min"]`).
  2) 입구 문서가 사실과 같다 — README 의 상태 줄은 미리보기 단계이고 문서 표에 모든 문서가 있으며, AGENTS 는 지금 상태를 읽는 곳과 '결정 기록 전체를 읽지 않는다' 를 적고 그 PowerShell 명령이 진짜로 마지막 10행을 낸다.
  3) 설치·릴리스 문서가 사실과 같다 — RELEASE 는 장래 설계라는 배너가 있고, PACKAGE §10 은 병합된 빌드 워크플로의 실제 값(수동 실행·산출물 네 개·보존 14일·꾸러미 이름)을 적으며, 시험지 0-0 은 받는 법·압축 속 압축·14일·빨간 실행일 때 알리는 법을 담는다.
이 시험은 네트워크·키 없이 돈다(PowerShell 시험만 윈도에서 PowerShell 이 있을 때 돈다).
"""
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packaging"))

import build_package  # noqa: E402  (PyInstaller 없이 불러와진다 — 실패 문장을 만드는 함수만 쓴다)
from chanceblog_desktop.ui.core import part_rules  # noqa: E402
from chanceblog_desktop.ui.core import tokens as K  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

TILDE = chr(0x7E)
URL = re.compile(r"(?i)(https?|ftp)://|www[.]")
# README 의 '읽을 문서' 표에 있어야 하는 문서 — 이 시험을 쓴 때(2026-11-13)의 docs 폴더 전부. 나중에 더해지는 문서는 여기에 강제하지 않는다.
README_DOCS = ("ARCHITECTURE", "DECISIONS", "MIGRATION", "P4_REVIEW_ITEMS", "PACKAGE", "PERSONAL_PC_TEST", "PLATFORM_POLICY", "RELEASE", "SECURITY", "TOPIC_ENGINE_PLAN", "TROUBLESHOOTING",
               "UI_COMPONENTS", "UI_DESIGN_SPEC", "UI_ICONS", "UI_IMAGES", "UI_STATES", "UI_VISUAL_QA")
DEV_WORDS = ("python", "pip ", "git ", "PyInstaller", "pyinstaller", "venv")        # 운영자 시험지는 개발 도구 낱말을 쓰지 않는다(test_packaging_docs 와 같은 규칙)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def clean(testcase, text):
    testcase.assertNotIn(TILDE, text)
    testcase.assertIsNone(URL.search(text))


class SheetScreenPlacesTest(unittest.TestCase):
    def setUp(self):
        self.sheet = read("docs/PERSONAL_PC_TEST.md")

    def test_the_blog_cards_are_said_to_be_on_the_left_or_on_top_in_the_narrowest_window_and_the_code_does_that(self):
        step2 = self.sheet.split("## 2단계")[1].split("## 3단계")[0]
        self.assertIn("왼쪽(창이 좁으면 위쪽)에 늘어선 카드들", step2)
        self.assertNotIn("위쪽의 카드들 중", self.sheet)
        side = K.FRAME["sidebar"] + 2 * K.LAYOUT["page_margin"]                         # 본문 폭 = 창 폭 - 사이드바 - 양쪽 여백(스크롤 막대 몇 px 는 아래 여유로 본다)
        self.assertGreaterEqual(K.LAYOUT["window"][0] - side - 40, K.LAYOUT["blogs_beside_min"], "기본 창(1440 폭)에서 카드 목록은 폼 옆(왼쪽)이다")
        self.assertLess(K.LAYOUT["window_min"][0] - side, K.LAYOUT["blogs_beside_min"], "가장 좁은 창(900 폭)에서 카드 목록은 폼 위다")
        code = read("src/chanceblog_desktop/ui/qt/blog_screen.py")
        self.assertIn("setDirection(QBoxLayout.LeftToRight if beside else QBoxLayout.TopToBottom)", code)
        self.assertLess(code.index("self._layout.addWidget(listing, 0)"), code.index("self._layout.addWidget(form, 1)"), "목록이 폼보다 먼저(왼쪽·위쪽)")

    def test_the_candidate_detail_is_a_right_pane_or_a_drawer_and_the_make_button_is_pinned_at_its_bottom(self):
        step2 = self.sheet.split("## 2단계")[1].split("## 3단계")[0]
        self.assertIn("오른쪽에 열리는 상세 창(창이 좁으면 오른쪽에서 밀려 나오는 서랍) **맨 아래에 붙어 있는** `이 주제로 만들기`", step2)
        self.assertNotIn("오른쪽(또는 아래) 상세", self.sheet)
        self.assertEqual(part_rules.detail_layout(K.LAYOUT["window"][0]).mode, "fixed", "기본 창에서는 고정 상세 창")
        self.assertEqual(part_rules.detail_layout(K.LAYOUT["window_min"][0]).mode, "drawer", "가장 좁은 창에서는 서랍")
        self.assertEqual(T["drf_make"], "이 주제로 만들기")
        parts, shell = read("src/chanceblog_desktop/ui/qt/candidate_parts.py"), read("src/chanceblog_desktop/ui/qt/shell.py")
        self.assertIn("def set_content(self, widget, focusable=True, footer=None):", parts)             # 아래 고정 행동 줄을 받는 상세 창·서랍의 내용 자리
        self.assertIn("def _set_footer(self, footer):", parts)
        self.assertGreaterEqual(shell.count("detail_footer(self,"), 2, "고정 상세 창과 서랍이 둘 다 같은 아래 고정 행동 줄을 쓴다")

    def test_the_settings_page_order_is_the_connection_card_with_the_info_row_last_then_the_backup_card_then_the_style_card(self):
        step1 = self.sheet.split("### 1-3.")[1].split("## 2단계")[0]
        self.assertIn("`연결 관리` 카드의 마지막 줄 `정보`", step1)
        self.assertNotIn("설정 화면 맨 아래쪽", self.sheet)
        step4 = self.sheet.split("## 4단계")[1].split("## 5단계")[0]
        for needle in ("`연결 관리` 카드 밑의 **`백업·복원` 카드**", "`내 글 문체 참고값 보기` 카드", "카드 오른쪽 위의 `지금 백업`"):
            self.assertIn(needle, step4, needle)
        self.assertNotIn("이름이 비슷한 카드", self.sheet)
        for key, text in (("backup_title", "백업·복원"), ("backup_now", "지금 백업"), ("style_entry_title", "내 글 문체 참고값 보기")):
            self.assertEqual(T[key], text, key)
        body = read("src/chanceblog_desktop/ui/qt/screens.py").split("def settings_screen(")[1].split("\ndef ")[0]
        order = [body.index(marker) for marker in ('info = vm["info"]', "outer.addWidget(section)", "backup_section(vm", "style_entry_card(shell)")]
        self.assertEqual(order, sorted(order), "코드의 설정 화면 순서가 시험지 설명(정보 줄 → 연결 관리 카드 끝 → 백업·복원 → 맨 아래 내 글 문체)과 다르다")


class EntranceDocsTest(unittest.TestCase):
    def test_the_readme_status_line_says_preview_stage_with_only_the_personal_pc_package(self):
        status = next(line for line in read("README.md").splitlines() if line.startswith("> **상태:"))
        for needle in ("미리보기 단계", "개인 PC 제한 시험용 Package", "미서명", "공개 배포용이 아닙니다", "설치 파일과 자동 업데이트는 아직 없습니다", "docs/PACKAGE.md", "docs/PERSONAL_PC_TEST.md"):
            self.assertIn(needle, status, needle)
        for old in ("설계 단계", "설치할 수 있는 버전이 없습니다"):
            self.assertNotIn(old, status, old)
        self.assertIn("preview", read("VERSION"), "버전이 미리보기가 아니게 되면 이 상태 줄도 함께 고친다")
        clean(self, status)

    def test_the_readme_table_names_every_document_in_the_docs_folder_as_of_this_check(self):
        readme = read("README.md")
        links = set(re.findall(r"\]\((docs/[A-Za-z0-9_]+\.md)\)", readme))
        self.assertEqual([name for name in README_DOCS if f"docs/{name}.md" not in links], [])
        self.assertEqual([name for name in README_DOCS if not (ROOT / "docs" / f"{name}.md").is_file()], [])
        rows = [line for line in readme.splitlines() if "docs/TOPIC_ENGINE_PLAN.md" in line or "docs/P4_REVIEW_ITEMS.md" in line]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row.startswith("| ") and row.rstrip().endswith("|") and row.count(" | ") == 1, row)
            clean(self, row)

    def test_agents_says_where_the_current_status_lives_and_not_to_read_the_whole_decision_log(self):
        agents = read("AGENTS.md")
        for needle in ("인수인계/작업내용.md", "§0-3", "git log --oneline -15", "마지막 10행", "처음부터 끝까지 읽지 않는다", "Select-Object -Last 10", "**전체를 읽지 않는다**"):
            self.assertIn(needle, agents, needle)
        self.assertNotIn("가 아니라 **이 저장소의 `docs/DECISIONS.md` 와 PR 본문**에 적는다", agents, "옛 문장 — 현황을 DECISIONS 와 PR 본문에 적으라는 말이 현황이 사는 곳과 어긋났다")
        step1 = next(line for line in agents.splitlines() if line.startswith("1. 이 문서"))
        self.assertIn("전체를 읽지 않는다", step1)
        added = [line for line in agents.splitlines() if line.startswith(("- **결정과 변경 내용**", "- **지금 상태를 읽는 곳"))]
        self.assertEqual(len(added), 2)
        for line in added:
            clean(self, line)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "PowerShell 이 있는 윈도에서만 돈다")
    def test_the_powershell_command_written_in_agents_really_prints_the_last_ten_decision_rows(self):
        command = re.search(r"PowerShell 에서 `(Select-String [^`]+)`", read("AGENTS.md")).group(1)
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], cwd=str(ROOT), capture_output=True, timeout=180)
        self.assertEqual(done.returncode, 0, done.stderr[:300])
        rows = [line for line in done.stdout.decode("oem", "replace").splitlines() if line.startswith("| D-")]
        wanted = re.findall(r"(?m)^\| (D-\d+) \|", read("docs/DECISIONS.md"))[-10:]
        self.assertEqual([re.match(r"\| (D-\d+) \|", line).group(1) for line in rows], wanted, "마지막 10행이 나온다")
        self.assertLess(len(done.stdout), 10 * 160 * 4 + 400, "한 행이 앞 160자로 잘려 나온다(자르지 않으면 수만 바이트)")


class WorkflowDocsTest(unittest.TestCase):
    def setUp(self):
        self.workflow = read(".github/workflows/package.yml")
        self.package = read("docs/PACKAGE.md")
        self.sheet = read("docs/PERSONAL_PC_TEST.md")
        self.release = read("docs/RELEASE.md")

    def facts(self):
        """워크플로 파일의 실제 값 — 꾸러미 이름·보존 일수·제한 시간·올리는 파일 이름들·워크플로 이름."""
        return {
            "artifact": re.search(r"^\s+name:\s*(ChanceBlogDesktop[\w.-]*)\s*$", self.workflow, re.M).group(1),
            "retention": int(re.search(r"^\s*retention-days:\s*(\d+)\s*$", self.workflow, re.M).group(1)),
            "timeout": int(re.search(r"^\s*timeout-minutes:\s*(\d+)\s*$", self.workflow, re.M).group(1)),
            "files": re.findall(r"\$\{\{ runner\.temp \}\}/package/release/(\S+)", self.workflow),
            "name": re.search(r'^name:\s*"(.+)"\s*$', self.workflow, re.M).group(1),
        }

    def test_the_release_doc_starts_with_the_banner_that_says_future_design_and_points_at_the_real_path(self):
        lines = self.release.splitlines()
        self.assertEqual(lines[0], "# 설치 파일·자동 업데이트·릴리스")
        banner = "\n".join(lines[1:5])
        for needle in ("장래 설계(미구현)", "[`PACKAGE.md`](PACKAGE.md)", "[`PERSONAL_PC_TEST.md`](PERSONAL_PC_TEST.md)", "새 버전은 새로 풀어서 쓴다"):
            self.assertIn(needle, banner, needle)
        self.assertEqual((lines[1], lines[4]), ("", ""), "제목 아래 빈 줄, 배너 두 줄(맨 위), 빈 줄")
        self.assertTrue(lines[2].startswith("> **장래 설계(미구현)") and lines[3].startswith("> 지금의 배포 경로는"), "배너는 두 줄이다")
        for kept in ("## 방식", "## 릴리스 절차", "## 코드 서명", "Velopack"):                       # 설계 내용은 지우지 않고 배너만 더했다
            self.assertIn(kept, self.release, kept)
        clean(self, banner)

    def test_package_section_10_states_the_merged_workflow_facts_that_the_workflow_file_really_has(self):
        facts = self.facts()
        self.assertEqual(sorted(facts["files"]), sorted(["ChanceBlogDesktop-*-win64.zip", "SHA256SUMS", "PACKAGE_INFO.md", "PACKAGE_INFO.json"]), "올리는 파일은 넷")
        section = self.package.split("## 10. 한계와 다음 일")[1].split("\n## ")[0]
        bullet = next(line for line in section.splitlines() if line.startswith("- **빌드 워크플로**"))
        for needle in ("T3 였고 운영자 승인으로 병합돼 지금 main 에 있다", "수동 실행만", "`workflow_dispatch`", "`windows-latest`", "비밀 값 0", "서명 단계 없음", "`Artifacts`", "시험지 0-0",
                       f"`{facts['artifact']}`", f"**{facts['retention']}일**", "`PACKAGE_INFO.md`·`PACKAGE_INFO.json` 네 개만", "`SHA256SUMS`"):
            self.assertIn(needle, bullet, needle)
        for old in ("이 가지에 없다", "별도 가지에 초안만 있고", "병합되면 이 문서의 §2 명령이"):
            self.assertNotIn(old, bullet, old)
        self.assertIn("windows-latest", self.workflow)
        self.assertIn("workflow_dispatch", self.workflow)
        tail = self.package.split("## 빌드는 PATH 를 좁힌다")[1]
        self.assertIn("병합 전 상태였고 지금은 병합된 사실로 고쳐 적었다", tail, "끝의 정정 문장은 §10 의 새 문장과 모순되지 않는다")
        self.assertNotIn("§10 의 '별도 가지에 초안만 있다' 문장은 병합 전 상태다", tail)
        clean(self, bullet)

    def test_the_architecture_doc_no_longer_calls_the_merged_workflow_a_draft_on_another_branch(self):
        architecture = read("docs/ARCHITECTURE.md")
        self.assertNotIn("별도 가지의 초안이다", architecture)
        self.assertIn("빌드 워크플로(`.github/workflows/package.yml`)는 T3 였고 운영자 승인으로 병합돼 있다(수동 실행만).", architecture)

    def test_the_sheet_has_the_download_step_before_0_1_with_the_two_traps_and_the_red_run_instruction(self):
        facts = self.facts()
        step0 = self.sheet.split("## 0단계")[1].split("## 1단계")[0]
        self.assertLess(step0.index("### 0-0."), step0.index("### 0-1."))
        block = step0.split("### 0-0.")[1].split("### 0-1.")[0]
        for needle in ("`Actions`", "`Run workflow`", "`Artifacts`", f"맨 아래로 내리면 `Artifacts` 아래에 `{facts['artifact']}` 가 있습니다", f"`{facts['artifact']}`", f"`{facts['artifact']}.zip`", "압축 속 압축", "겉 꾸러미", "**한 번만** 풀면", "SHA-256 을 확인하기 전에는 풀지 않습니다",
                       f"**{facts['retention']}일만** 보관합니다", f"제한 시간은 {facts['timeout']}분", "**초록 체크**", "빨간 X", "묶음 점검에서 문제가 나왔어요", "`[2/8]`", "AI 와의 대화 창", "이렇게 보이면 통과", "TESTBUILD",
                       "이 칸은 7단계 표에 줄이 없고"):
            self.assertIn(needle, block, needle)
        self.assertIn(facts["name"], block, "워크플로 이름 그대로")
        for name in ("SHA256SUMS", "PACKAGE_INFO.md", "PACKAGE_INFO.json", "ChanceBlogDesktop-0.1.0-preview.1-win64.zip"):
            self.assertIn(name, block, name)
        self.assertGreaterEqual(block.count("- [ ] "), 3, "체크 칸")
        for word in DEV_WORDS:
            self.assertNotIn(word, block, word)
        clean(self, block)
        message = build_package.problem_message(["a.dll(출처 C:/elsewhere/a.dll)"], home="C:/Users/x")
        self.assertTrue(message.startswith("묶음 점검에서 문제가 나왔어요(총 1건): "), "시험지가 복사하라는 줄은 빌드 스크립트가 실제로 내는 문장이다: " + message)
        self.assertIn('say(f"[2/8]', read("packaging/build_package.py"), "복사하라는 [2/8] 줄도 실제로 찍힌다")

    def test_the_sheet_still_has_exactly_the_nine_numbered_steps_and_the_old_download_sentence(self):
        self.assertEqual([number for number, _title in re.findall(r"(?m)^## (\d)단계\. (.+)$", self.sheet)], [str(n) for n in range(9)])
        self.assertIn("받는 곳은 AI 가 알려 드린 곳입니다", self.sheet)                                    # 옛 안내(AI 에게서 받는 길)는 그대로 둔다


if __name__ == "__main__":
    unittest.main()
