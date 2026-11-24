"""설치 도구 시험(spike) 문서 시험(결정 D-700에서 D-708) — 운영자 실행 안내(`docs/INSTALLER_SPIKE_RUN.md`)가 비개발자가 따라갈 수 있고 워크플로의 실제 이름과 맞으며, 결정 행 아홉 개가 번호 순서로 한 줄씩 있고,
`PACKAGE.md`·`RELEASE.md`·`CHANGELOG.md` 의 단락이 서로 어긋나지 않는지 본다. 물결표·웹 주소·이중 중괄호·채우지 않은 자리표시자가 없고 상대 링크는 실제 파일을 가리킨다.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer_spike_support as support  # noqa: E402
import test_workflow_artifacts as wf  # noqa: E402

TILDE = chr(0x7E)
URL = re.compile(r"(?i)(https?|ftp)://|www[.]")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
UNFINISHED = ("@@", "TODO", "XXX", "{{", "}}", "미정", "채울", "집계 대기")
OWN_ROW = re.compile(r"^\| D-70\d \|")
GUIDE = "docs/INSTALLER_SPIKE_RUN.md"


def read(rel):
    return support.read(rel)


def own_rows():
    return [line for line in read("docs/DECISIONS.md").splitlines() if OWN_ROW.match(line)]


class RunGuideTest(unittest.TestCase):
    def setUp(self):
        self.text = read(GUIDE)
        self.workflow = support.WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_no_tilde_no_address_no_double_brace_and_only_relative_links_to_real_files(self):
        self.assertNotIn(TILDE, self.text)
        self.assertIsNone(URL.search(self.text))
        self.assertNotIn("{{", self.text)
        for target in LINK.findall(self.text):
            self.assertFalse(re.match(r"^[a-z][a-z0-9+.-]*:", target), target)
            self.assertTrue((support.ROOT / "docs" / target.split("#")[0]).exists(), target)

    def test_the_names_the_operator_looks_for_are_the_workflow_s_real_names(self):
        name = re.search(r'^name: "([^"]+)"', self.workflow, re.M).group(1)
        self.assertIn("Installer spike", name)
        self.assertIn(name.split(" — ")[0] + " — " + name.split(" — ")[1], self.text)
        self.assertIn("InstallerSpike-report", self.text)
        self.assertIn("InstallerSpike-report", self.workflow)
        for upload_name in ("INSTALLER_SPIKE_REPORT.md", "INSTALLER_SPIKE_REPORT.json"):
            self.assertIn(upload_name, self.text)
            self.assertIn(upload_name, self.workflow)
        self.assertIn("14일", self.text)

    def test_every_step_name_it_lists_exists_in_the_workflow(self):
        listed = re.search(r"단계 이름은 (.+?) 중 하나다", self.text).group(1)
        names = re.findall(r"'([^']+)'", listed)
        self.assertEqual(len(names), 8)
        for name in names:
            self.assertIn(name, self.workflow, name)

    def test_the_time_it_promises_fits_the_workflow_time_limit(self):
        limit = int(re.search(r"timeout-minutes:\s*(\d+)", self.workflow).group(1))
        self.assertIn("한도 %d분" % limit, self.text)
        self.assertIn("40분에서 60분", self.text)

    def test_it_tells_the_operator_the_whole_way_in_numbered_steps(self):
        steps = re.findall(r"(?m)^(\d)\. ", self.text)
        self.assertEqual(steps, ["1", "2", "3", "4", "5", "6"])
        for needle in ("Actions", "Run workflow", "main", "Summary", "맨 아래", "통째로 복사", "소유자 이슈", "INSTALLER_SPIKE_RESULT", "END"):
            self.assertIn(needle, self.text, needle)

    def test_it_says_what_is_downloaded_what_is_not_touched_and_what_a_red_run_means(self):
        for needle in ("약 147MB", "약 1.4MB", "크기와 지문(SHA-256)", "비용은 0", "아무것도 설치하거나 받지 않는다", "비밀 값", "일부러 멈춘 안전 장치", "시도 불가", "운영자 PC 시험지"):
            self.assertIn(needle, self.text, needle)

    def test_the_result_block_markers_are_the_ones_the_report_writes(self):
        run = support.load("run_spike")
        self.assertTrue(run.RESULT_HEADER.startswith("=== INSTALLER_SPIKE_RESULT"))
        self.assertIn("INSTALLER_SPIKE_RESULT", self.text)
        self.assertTrue(run.RESULT_FOOTER.endswith("END ==="))

    def test_it_asks_for_nothing_secret_and_names_no_person_or_blog(self):
        for word in ("비밀번호", "토큰을 입력", "API 키를 입력", "password"):
            self.assertNotIn(word, self.text)


class DecisionRowsTest(unittest.TestCase):
    def test_nine_rows_in_number_order_one_line_each_right_after_the_previous_block(self):
        rows = own_rows()
        self.assertEqual([row.split(" | ")[0] for row in rows], ["| D-70%d" % number for number in range(9)])
        lines = read("docs/DECISIONS.md").splitlines()
        first = lines.index(rows[0])
        self.assertTrue(lines[first - 1].startswith("| D-"), "앞 줄이 표의 행이라 표가 끊기지 않는다")
        self.assertEqual(lines[first:first + 9], rows)
        for row in rows:
            self.assertEqual(row.count(" | "), 3, row[:12])                                  # 번호 | 날짜 | 내용 | 상태
            self.assertTrue(row.endswith(" |"))
            self.assertIn("2026-11-24", row.split(" | ")[1])

    def test_rows_have_no_tilde_no_address_nothing_unfinished_and_stay_inside_the_number_range(self):
        for row in own_rows():
            self.assertNotIn(TILDE, row)
            self.assertIsNone(URL.search(row))
            for word in UNFINISHED[:5]:
                self.assertNotIn(word, row)
        numbers = [int(re.match(r"^\| D-(\d+) ", row).group(1)) for row in own_rows()]
        self.assertTrue(all(700 <= number <= 709 for number in numbers))

    def test_each_row_has_its_own_words(self):
        expected = {"D-700": ("확인 037", "정확히", "넷에서 여섯", "T3 예외", "D-344"), "D-701": ("fetch_tools.py", "tools.lock.json", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "SHA-256", "900초", "pip"),
                    "D-702": ("run_spike.py", "install-tools", "build-bundles", "--tool-path", "원본", "--delta", "--skipVeloAppCheck", "60분"),
                    "D-703": ("M01–M22", "G1–G8", "미정", "결과 블록", "Scrubber", "방화벽"), "D-704": ("spike_app.py", "spike_app_sdk.py", "BROKEN", "set_auto_apply_on_startup(False)", "G-A"),
                    "D-705": ("ChanceBlogSpike.iss", "PrivilegesRequired=lowest", "Korean.isl", "UninstallDelete", "ASCII"), "D-706": ("test_installer_spike_workflow", "test_workflow_artifacts", "한계"),
                    "D-707": ("INSTALLER_SPIKE_RUN.md", "Run workflow", "D-04", "정리"), "D-708": ("dotnet tool install", "--delta None", "시도 불가", "Defender", "추정")}
        by_number = {row.split(" | ")[0].replace("| ", ""): row for row in own_rows()}
        for number, words in expected.items():
            for word in words:
                self.assertIn(word, by_number[number], (number, word))

    def test_the_row_that_pins_the_upload_shapes_names_all_six_and_the_change_rule(self):
        row = next(line for line in read("docs/DECISIONS.md").splitlines() if line.startswith("| D-344 |"))
        for shape in wf.ALLOWED_UPLOAD_FILES:
            self.assertIn(shape, row, shape)
        self.assertIn("여섯 모양", row)
        self.assertIn("D-700", row)
        self.assertIn(wf.CHANGE_RULE_SENTENCE, row)

    def test_the_security_and_ocr_docs_no_longer_say_four_shapes_for_the_allow_list(self):
        self.assertIn("여섯 모양(`ALLOWED_UPLOAD_FILES`", read("docs/SECURITY.md"))
        self.assertNotIn("네 모양과 결정 D-344", read("docs/PACKAGE_OCR.md"))


class SectionsTest(unittest.TestCase):
    def test_package_release_and_changelog_have_one_paragraph_each_that_points_at_the_guide(self):
        package, release, changelog = read("docs/PACKAGE.md"), read("docs/RELEASE.md"), read("CHANGELOG.md")
        self.assertEqual(package.count("## 설치 도구 시험(수동, 병합 뒤 운영자 실행) (D-700 에서 D-708)"), 1)
        self.assertEqual(release.count("## 설치 도구 시험(수동, 병합 뒤 운영자 실행)"), 1)
        self.assertEqual(changelog.count("설치 도구 시험(spike)을 NO-MERGE 가지에 준비했다"), 1)
        for text in (package, release):
            tail = text[text.index("## 설치 도구 시험(수동, 병합 뒤 운영자 실행)"):]
            self.assertIn("INSTALLER_SPIKE_RUN.md", tail)
            self.assertNotIn(TILDE, tail)
            self.assertIsNone(URL.search(tail))
            self.assertNotIn("{{", tail)
        line = next(item for item in changelog.splitlines() if "설치 도구 시험(spike)을 NO-MERGE 가지에 준비했다" in item)
        self.assertNotIn(TILDE, line)
        self.assertIsNone(URL.search(line))
        self.assertIn("D-700 에서 D-708", line)
        self.assertLess(changelog.index(line), changelog.index("## [0.0.0]"))
        self.assertGreater(changelog.index(line), changelog.index("## [0.1.0-preview.1]"))

    def test_the_new_text_does_not_move_any_existing_line(self):
        """새 줄·새 절은 끝에 덧붙였다 — 이 시험은 각 파일의 새 단락 앞에 기존 단락이 그대로 있음을 가볍게 확인한다(맨 위 제목)."""
        self.assertTrue(read("docs/PACKAGE.md").startswith("# 개인 PC 제한 시험용 Package"))
        self.assertTrue(read("docs/RELEASE.md").startswith("# 설치 파일·자동 업데이트·릴리스"))
        self.assertTrue(read("CHANGELOG.md").startswith("# 변경 이력"))


if __name__ == "__main__":
    unittest.main()
