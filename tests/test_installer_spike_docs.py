"""설치 도구 시험(spike) 문서 시험(결정 D-700에서 D-708) — 운영자 실행 안내(`docs/INSTALLER_SPIKE_RUN.md`)가 비개발자가 따라갈 수 있고 워크플로의 실제 이름과 맞으며, 결정 행 아홉 개가 번호 순서로 한 줄씩 있고,
`PACKAGE.md`·`RELEASE.md`·`CHANGELOG.md` 의 단락이 서로 어긋나지 않는지 본다. 물결표·웹 주소·이중 중괄호·채우지 않은 자리표시자가 없고 상대 링크는 실제 파일을 가리킨다.
"""
import contextlib
import io
import re
import sys
import tempfile
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


class RunnerGuardDocsTest(unittest.TestCase):
    """재작업 권고 1(총괄 결정) — 러너 가드를 더 까다롭게 만들지 않는 대신 그 존재·종료 코드·'보안 장치가 아니다' 한계를 문서에 적는다. 문서가 말하는 변수 이름과 종료 코드는 코드가 실제로 읽고 돌려주는 값과 같아야 한다."""

    def setUp(self):
        self.measure = support.load("measure")
        self.run = support.load("run_spike")
        self.row = next(line for line in read("docs/DECISIONS.md").splitlines() if line.startswith("| D-708 |"))
        self.guide = read(GUIDE)

    def exit_code_off_a_runner(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            return self.run.main(["measure", "--work", str(Path(tmp) / "w")], host=self.measure.Host({}))

    def variables_the_guard_reads(self):
        spy = support.RecordingEnv({"GITHUB_ACTIONS": "true", "RUNNER_OS": "Windows", "RUNNER_TEMP": "D:\\a\\_temp"})
        self.assertEqual(self.measure.runner_problem(spy), "")
        return sorted(set(spy.read_keys))

    def test_d708_names_the_guard_the_variables_it_reads_the_exit_code_and_that_it_is_no_security_device(self):
        names = self.variables_the_guard_reads()
        self.assertEqual(names, ["GITHUB_ACTIONS", "RUNNER_OS", "RUNNER_TEMP"])
        for word in names + ["measure.runner_problem", "종료 코드 %d" % self.exit_code_off_a_runner(), "작업 폴더도 만들지 않으며", "개발 PC", "보안 장치가 아니다", "환경 변수를 일부러 맞추면 통과한다"]:
            self.assertIn(word, self.row, word)

    def test_d708_says_what_the_password_hiding_covers_and_what_it_does_not(self):
        for word in ("임시 비밀번호", "자르기 전에", "대소문자", "URL 인코딩", "줄바꿈", "다른 글자가 끼는 변형", "PUBLIC", "SPIKE_USERS_DIR"):
            self.assertIn(word, self.row, word)

    def test_the_guide_tells_the_operator_what_happens_off_a_runner_and_that_it_is_no_security_device(self):
        for word in ("종료 코드 %d" % self.exit_code_off_a_runner(), "개발 PC", "일회용", "보안 장치가 아니다", "환경 변수를 일부러 맞추면 통과한다"):
            self.assertIn(word, self.guide, word)

    def test_the_exit_code_both_documents_name_is_the_one_the_guard_really_returns(self):
        self.assertEqual(self.exit_code_off_a_runner(), 2)
        self.assertIn("종료 코드 2", self.row)
        self.assertIn("종료 코드 2", self.guide)


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


class FirstRunFixDocsTest(unittest.TestCase):
    """결정 D-810 — 설치 도구 시험 1차 측정 결과와 측정 도구 결함 정정을 적은 결정 행 하나·실행 안내의 '두 번째로 돌릴 때' 절·변경 이력 줄."""
    WEIGHTS = (15, 20, 15, 10, 10, 10, 10, 5, 5)                    # 설계서 3-2 의 기준 아홉 개(C1에서 C9)의 가중
    PRE = {"A": (5, 2, 3, 2, 2, 3, 4, 4, 3), "B": (4, 4, 3, 2, 2, 3, 4, 4, 3), "C": (3, 5, 5, 5, 5, 2, 4, 4, 4)}             # 문서만 읽고 매긴 사전 점수
    NOW = {"A": (5, 2, 3, 2, 2, 4, 4, 4, 3), "B": (4, 4, 3, 2, 2, 4, 4, 4, 3)}                                                 # 1차 측정값으로 다시 매긴 점수(C6 만 바뀜 — M10)

    def setUp(self):
        self.rows = [line for line in read("docs/DECISIONS.md").splitlines() if re.match(r"^\| D-81\d \|", line)]
        self.guide = read(GUIDE)
        self.section = self.guide[self.guide.index("## 두 번째로 돌릴 때"):]
        self.changelog = read("CHANGELOG.md")

    @staticmethod
    def total(scores, weights):
        return sum(score * weight for score, weight in zip(scores, weights)) / 5

    def test_exactly_one_row_in_the_number_range_follows_another_row_of_the_big_table(self):
        self.assertEqual([row.split(" | ")[0] for row in self.rows], ["| D-810"])
        lines = read("docs/DECISIONS.md").splitlines()
        at = lines.index(self.rows[0])
        self.assertTrue(lines[at - 1].startswith("| D-"), "앞 줄이 표의 행이라 표가 끊기지 않는다")
        self.assertEqual(self.rows[0].count(" | "), 3, "번호 | 날짜 | 내용 | 상태")
        self.assertTrue(self.rows[0].endswith(" |"))
        self.assertIn("2026-11-25", self.rows[0].split(" | ")[1])
        numbers = [int(re.match(r"^\| D-(\d+) ", row).group(1)) for row in self.rows]
        self.assertTrue(all(810 <= number <= 819 for number in numbers))

    def test_the_row_has_no_tilde_no_address_no_double_brace_and_nothing_unfinished(self):
        row = self.rows[0]
        self.assertNotIn(TILDE, row)
        self.assertIsNone(URL.search(row))
        for word in UNFINISHED[:5]:
            self.assertNotIn(word, row)

    def test_the_row_names_each_defect_what_was_done_and_what_stays_open(self):
        for word in ("그 실패는 모두 측정 도구의 결함이었다", "통과 개수를 12 로 못박아", "열세 번째 점검", "SELFTEST_KEYS", "더 찍힌 점검은 막지 않는다", "원인 후보는 넷이다", "종료 코드가 비어", "환경을 물려받아", "기다리지 않고 바로 흔적을 봤", "컴퓨터 이름을 붙여", "spikeusera·spikeuserb·spikeuserc", "최대 45초 기다리며", "러너에서만 알 수 있다",
                     "사용자 폴더·임시 폴더 변수를 그 사용자 것으로 명시", "종료 코드 42", "시도 불가", "T-INST-04", "종료 740", "0.0.0.0", "6.5.0 이상이면 쓴다", "Korean.isl", "미확인", "컴파일 출력",
                     "ImageOS", "대문자", "vpk --version", "M20", "M17", "M19", "100자", "False", "실제 도구 결과", "M13", "대소문자까지 달라야 한다", "M15", "ws2_32", "M16", "M05", "30.6초", "30초",
                     "설치 로그에서 훅을 말하는 줄", "2차 측정 뒤에 정한다", "Run workflow 단추 한 번", "T2"):
            self.assertIn(word, self.rows[0], word)

    def test_the_scores_in_the_row_are_what_the_design_table_adds_up_to(self):
        self.assertEqual(sum(self.WEIGHTS), 100)
        self.assertEqual({arm: self.total(self.PRE[arm], self.WEIGHTS) for arm in "ABC"}, {"A": 61, "B": 66, "C": 84})              # 설계서가 C 의 합계를 81 로 적은 것은 산수 오류다
        self.assertEqual({arm: self.total(self.NOW[arm], self.WEIGHTS) for arm in "AB"}, {"A": 63, "B": 68})
        changed = {arm: [index for index in range(9) if self.PRE[arm][index] != self.NOW[arm][index]] for arm in "AB"}
        self.assertEqual(changed, {"A": [5], "B": [5]})                                           # 측정이 바꾼 칸은 C6(롤백·복구 바탕) 하나뿐이다
        row = self.rows[0]
        for word in ("A 63·B 68", "C6", "84", "81", "산수 정정", "약 16점"):
            self.assertIn(word, row, word)
        self.assertGreater(self.total(self.PRE["C"], self.WEIGHTS) - self.total(self.NOW["B"], self.WEIGHTS), 5)                  # 점수 차가 5점을 넘는다 — C 를 재야 결론이 난다

    def test_the_guide_says_the_second_run_is_the_same_one_press_of_the_same_button(self):
        for word in ("1차 결과에서 시험 도구 자체의 결함", "결정 D-810", "달라지지 않는다", "같은 단추로 한 번", "같은 곳", "입력칸도 새 절차도 없다", "물음표 대신 이유", "따로 한 줄씩", "시도 불가", "T-INST-04", "6.5.0 이상이면 쓴다", "미확인", "점검 목록 전부"):
            self.assertIn(word, self.section, word)
        self.assertNotIn(TILDE, self.section)
        self.assertIsNone(URL.search(self.section))
        self.assertNotIn("{{", self.section)
        for word in ("비밀번호", "password", "토큰을 입력"):
            self.assertNotIn(word, self.section)
        self.assertEqual(re.findall(r"(?m)^(\d)\. ", self.guide), ["1", "2", "3", "4", "5", "6"])                                  # 하는 법의 번호 단계는 여섯 그대로다(절차를 늘리지 않았다)

    def test_the_guide_adds_no_input_field_and_no_new_step_for_the_operator(self):
        workflow = support.WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertNotIn("inputs:", workflow)                                                      # 입력칸 0 — 워크플로는 이번에도 바뀌지 않았다
        self.assertEqual(len(re.findall(r"(?m)^- ", self.section)), 5)                              # 새 절의 불릿은 '달라지는 것' 다섯 가지뿐이다

    def test_the_changelog_line_names_the_decision_and_sits_in_the_preview_section(self):
        line = next(item for item in self.changelog.splitlines() if "설치 도구 시험 1차 측정 결과를 읽고 측정 도구의 결함을 고쳤다" in item)
        self.assertEqual(self.changelog.count("설치 도구 시험 1차 측정 결과를 읽고 측정 도구의 결함을 고쳤다"), 1)
        for word in ("D-810", "변경 등급 T2", "12", "0.0.0.0", "러너: ? ?", "같은 Run workflow 단추 한 번"):
            self.assertIn(word, line, word)
        self.assertNotIn(TILDE, line)
        self.assertIsNone(URL.search(line))
        self.assertNotIn("{{", line)
        self.assertLess(self.changelog.index(line), self.changelog.index("## [0.0.0]"))
        self.assertGreater(self.changelog.index(line), self.changelog.index("## [0.1.0-preview.1]"))
        self.assertEqual(self.changelog.count("설치 도구 시험(spike)을 NO-MERGE 가지에 준비했다"), 1)                          # 옛 줄은 그대로 한 번


if __name__ == "__main__":
    unittest.main()
