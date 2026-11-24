"""v1.0 준비 문서 시험(V1DOCS) — 새 clone 시작 안내(`docs/MIGRATION.md` §6·README)·낡은 문장 목록(`docs/V1_RELEASE_CHECKLIST.md`)·릴리스 노트 규칙(`docs/RELEASE.md` 끝 절)·
v1.0 시험지 초안(`docs/PERSONAL_PC_TEST_V1_DRAFT.md`)·이관 노트 틀(`docs/MIGRATION_NOTES_TEMPLATE.md`)이 **사실과 어긋나지 않고 문서 규칙을 지키는지** 본다. 네트워크·키 없이 돈다.
(결정 색인과 그 생성기는 `tests/test_decision_index.py` 가 따로 지킨다.)

지키는 것:
  1) 새 문서와 새로 덧붙인 절에 물결표·웹 주소·이중 중괄호가 없고, 운영자 시험지 초안에는 개발 도구 낱말이 없고, 상대 링크가 실제 파일을 가리키고, README 문서 표에 새 문서가 한 줄씩 있다.
  2) 새 clone 안내가 적은 명령·옵션·파일이 실제 소스에 있다(`--sample`·`--data-dir`·`--check`·`--list`·`--selftest`·`--out-dir`·`--skip-scan`·`--allow-missing-gate`·잠금 파일의 두 줄·도구 표의 파일), 앱 코드가 쓰는 바깥 패키지는 PySide6 하나뿐이다.
  3) 낡은 문장 표가 스스로 맞다 — 줄 모양·번호·상태 낱말·담당 이름이 틀리지 않고, 파일이 있고, `대기`·`고치지 않음` 행의 찾는 조각이 그 파일에 지금도 있고 `고침` 행의 조각은 없으며, 같이 볼 시험 모듈이 실제로 있다.
  4) 릴리스 노트 규칙의 참고 구현(절 고르기)이 실제 CHANGELOG 의 모든 머리 줄을 읽을 수 있고 규칙대로 거절한다. 규칙이 '아직 없다' 고 쓴 스크립트는 정말 없다(생기면 문서를 고치게 한다).
  5) 시험지 초안이 단계·체크 칸·보고 표를 갖추고, 앱 화면 글자와 같은 단추 이름을 부르고, 가짜 키만 쓰고, 승인 전 두 단계를 승인 뒤에만 하라고 적는다.
  6) 이관 노트 틀의 사실이 코드와 같다 — 구조 번호(글 보관함 2·주제 엔진 보관함 2)·오류 이름·백업이 담는/담지 않는 파일.
"""
import ast
import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import store as content_store  # noqa: E402
from chanceblog_desktop.errors import CATALOG  # noqa: E402
from chanceblog_desktop.security import shape  # noqa: E402
from chanceblog_desktop.service import backup_flow, connections  # noqa: E402
from chanceblog_desktop.topicdb import store as topic_store  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

TILDE = chr(0x7E)
DOUBLE_OPEN, DOUBLE_CLOSE = "{" * 2, "}" * 2
URL = re.compile(r"(?i)(https?|ftp)://|www[.]")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
DEV_WORDS = ("python", "pip ", "git ", "PyInstaller", "pyinstaller", "venv")          # 운영자 시험지는 개발 도구 낱말을 쓰지 않는다(test_packaging_docs 와 같은 규칙)

NEW_DOCS = ("docs/DECISIONS_INDEX.md", "docs/V1_RELEASE_CHECKLIST.md", "docs/PERSONAL_PC_TEST_V1_DRAFT.md", "docs/MIGRATION_NOTES_TEMPLATE.md")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


NEXT_SECTION = chr(10) + "## "                            # 다음 `## ` 절의 머리(앞 줄바꿈 포함)


def part(text, start, end=None):
    """`start` 로 시작하는 줄부터 `end` 로 시작하는 다음 줄 앞(또는 끝)까지. 없으면 시험이 실패한다.
    `end` 가 NEXT_SECTION 이면 다음 `## ` 절 앞까지이고 그런 절이 없으면 문서 끝까지다 — 이 묶음이 끝에 덧붙인 절을 읽을 때 쓴다(다른 갈래가 그 뒤에 새 절을 덧붙여도 그 글은 읽지 않는다)."""
    first = text.index(start)
    if end == NEXT_SECTION:
        lines = text[first:].split(chr(10))
        fenced = False
        for index, line in enumerate(lines):
            if line.lstrip().startswith("```"):                     # 코드 블록 안의 `## ` 줄(틀의 예)은 절의 머리가 아니다
                fenced = not fenced
            elif index > 0 and not fenced and line.startswith("## "):
                return chr(10).join(lines[:index]) + chr(10)
        return text[first:]
    last = text.index(end, first + len(start)) if end else len(text)
    return text[first:last]


def clean(testcase, text, name=""):
    testcase.assertNotIn(TILDE, text, f"{name}: 물결표")
    testcase.assertIsNone(URL.search(text), f"{name}: 웹 주소")
    testcase.assertNotIn(DOUBLE_OPEN, text, f"{name}: 이중 중괄호")
    testcase.assertNotIn(DOUBLE_CLOSE, text, f"{name}: 이중 중괄호")


class HygieneTest(unittest.TestCase):
    ADDED = {
        "README.md 새 PC 절": ("README.md", "## 새 PC 에서 처음부터 — 개발자 시작 순서", NEXT_SECTION),
        "MIGRATION.md §6": ("docs/MIGRATION.md", "## 6. 새 clone 에서 처음부터", NEXT_SECTION),
        "RELEASE.md 릴리스 노트 규칙": ("docs/RELEASE.md", "## 릴리스 노트 규칙", NEXT_SECTION),
    }

    def test_the_new_documents_and_the_added_sections_have_no_tilde_no_web_address_and_no_double_braces(self):
        for rel in NEW_DOCS:
            clean(self, read(rel), rel)
        for label, (rel, start, end) in self.ADDED.items():
            clean(self, part(read(rel), start, end), label)

    def test_relative_links_in_the_new_documents_and_sections_point_at_real_files(self):
        sources = [(rel, read(rel)) for rel in NEW_DOCS] + [(label, part(read(rel), start, end)) for label, (rel, start, end) in self.ADDED.items()]
        base = {label: ROOT / Path(rel).parent for label, (rel, _s, _e) in self.ADDED.items()}
        for name, text in sources:
            folder = base.get(name, ROOT / Path(name).parent)
            for target in LINK.findall(text):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                    continue
                with self.subTest(source=name, link=target):
                    self.assertTrue((folder / target.split("#", 1)[0]).resolve().exists())

    def test_the_readme_documents_table_has_one_well_formed_row_for_each_new_document(self):
        rows = read("README.md").splitlines()
        for rel in NEW_DOCS:
            found = [line for line in rows if f"]({rel})" in line and line.startswith("| ")]
            with self.subTest(doc=rel):
                self.assertEqual(len(found), 1)
                self.assertTrue(found[0].rstrip().endswith("|") and found[0].count(" | ") == 1, found[0])
                self.assertTrue((ROOT / rel).is_file())

    def test_the_operator_sheet_draft_uses_no_developer_tool_words(self):
        text = read("docs/PERSONAL_PC_TEST_V1_DRAFT.md")
        for word in DEV_WORDS:
            self.assertNotIn(word, text, word)
        text = read("docs/MIGRATION_NOTES_TEMPLATE.md")
        for word in DEV_WORDS:
            self.assertNotIn(word, text, word)


class NewCloneGuideTest(unittest.TestCase):
    def setUp(self):
        self.guide = part(read("docs/MIGRATION.md"), "## 6. 새 clone 에서 처음부터", NEXT_SECTION)

    def test_the_guide_has_the_five_subsections_and_says_honestly_what_was_not_checked(self):
        for heading in ("### 6-1. 준비물", "### 6-2. 순서", "### 6-3. 지금 상태", "### 6-4. 도구 표", "### 6-5. 막혔을 때"):
            self.assertIn(heading, self.guide, heading)
        for needle in ("이 절을 어떻게 확인했나", "PYTHONPATH", "저장소 **밖**"):               # 확인 상태의 문장 자체('아직 없다'·'확인 못 함')는 점검표 A15·A16 이 고칠 때 바뀌므로 못박지 않는다
            self.assertIn(needle, self.guide, needle)

    def test_every_command_and_option_the_guide_names_exists_in_the_sources(self):
        launcher = read("src/chanceblog_desktop/ui/launcher.py")
        build = read("packaging/build_package.py")
        for option in ("--sample", "--data-dir"):
            self.assertIn(option, launcher)
            self.assertIn(option, self.guide)
        for option in ("--out-dir", "--skip-scan", "--allow-missing-gate"):
            self.assertIn(f'"{option}"', build)
            self.assertIn(option, self.guide)
        self.assertIn("--check", read("scripts/sync_errors.py"))
        self.assertIn("--check", read("scripts/sync_core.py"))
        self.assertIn("--list", read("scripts/ci_shard.py"))
        self.assertIn("--selftest", read("packaging/gui_entry.py"))
        for rel in ("scripts/ci_shard.py", "scripts/sync_errors.py", "scripts/sync_core.py", "scripts/gen_decision_index.py", "scripts/ui_capture.py", "scripts/ui_gallery.py",
                    "scripts/ui_image_check.py", "scripts/ui_bench.py", "scripts/ui_offscreen.py", "packaging/build_package.py", "packaging/gui_entry.py", "packaging/requirements-package.txt"):
            with self.subTest(file=rel):
                self.assertTrue((ROOT / rel).is_file())
                self.assertIn(Path(rel).name, self.guide, "도구 표나 순서에 이 파일 이름이 있어야 한다")

    def test_every_option_word_in_the_guide_and_the_readme_summary_is_a_real_option_of_this_repository_or_of_a_named_outside_tool(self):
        sources = "".join(read(rel) for rel in ("src/chanceblog_desktop/ui/launcher.py", "packaging/build_package.py", "scripts/ci_shard.py", "scripts/sync_errors.py", "scripts/sync_core.py",
                                                  "packaging/gui_entry.py", "scripts/gen_decision_index.py"))
        known = set(re.findall(r'"(--[a-z][a-z-]+)"', sources))
        outside = {"--help", "--require-hashes", "--dry-run", "--short"}          # 이 저장소의 도구가 아니라 pip·git 의 옵션이거나 모든 명령의 도움말
        readme = part(read("README.md"), "## 새 PC 에서 처음부터 — 개발자 시작 순서", NEXT_SECTION)
        for name, text in (("MIGRATION §6", self.guide), ("README 새 PC 절", readme)):
            used = set(re.findall(r"--[a-z][a-z-]+", text))
            self.assertEqual(used - known - outside, set(), f"{name}: 소스에 없는 옵션 이름 — 오타이거나 옵션이 바뀌었다")
        self.assertTrue({"--sample", "--data-dir", "--check", "--list", "--selftest", "--out-dir", "--skip-scan", "--allow-missing-gate"} <= known)

    def test_the_lock_file_has_the_two_runtime_lines_the_guide_names(self):
        lock = read("packaging/requirements-package.txt")
        for line in ("PySide6_Essentials==6.12.0", "shiboken6==6.12.0"):
            self.assertIn(line, lock)
            self.assertIn(line.replace("==", " "), self.guide, "안내가 잠금 파일의 버전을 그대로 적는다")
        self.assertFalse((ROOT / "requirements-dev.txt").exists(), "가이드가 '없다' 고 적은 파일이 생겼다 — 안내를 고친다")
        self.assertIn("`requirements-dev.txt` 가 **없다**", self.guide)

    def test_the_only_outside_package_the_app_code_imports_is_pyside6(self):
        std = set(sys.stdlib_module_names)
        local = {"chanceblog_desktop", "pipeline"}
        found = set()
        for path in (ROOT / "src").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 10))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                found |= {name for name in names if name not in std and name not in local}
        self.assertEqual(found, {"PySide6"}, "앱 코드가 쓰는 바깥 패키지가 달라졌다 — 새 의존성은 T3 이다. 안내(README·MIGRATION §6)도 함께 고친다")
        self.assertIn("앱 코드가 쓰는 바깥 패키지는 PySide6 하나뿐", self.guide)

    def test_the_readme_summary_runs_the_same_steps_as_the_guide(self):
        readme = part(read("README.md"), "## 새 PC 에서 처음부터 — 개발자 시작 순서", NEXT_SECTION)
        for command in ("git clone", "python -m venv ..\\chanceblog-venv", "-m pip install -r packaging/requirements-package.txt", "chanceblog_desktop --help", "scripts/ci_shard.py 1 3",
                        "chanceblog_desktop gui --sample", "packaging/build_package.py"):
            self.assertIn(command, readme, command)
        self.assertIn("docs/MIGRATION.md", readme)


class ChecklistTest(unittest.TestCase):
    ROW = re.compile(r"^\| ([A-F]\d\d) \| `([^`:]+):(\d+)` \| `([^`]+)` \| (.+) \| ([^|]+) \| ([^|]+) \| (대기|고침|고치지 않음) \|$")
    OWNERS = {"DOCS(b)", "FINAL", "GUI", "NET", "PUBPR", "BLOGGER", "UPDATE", "INSTALLER", "RELEASE", "총괄", "—"}
    GROUPS = {"A": "### 2-1.", "B": "### 2-2.", "C": "### 2-3.", "D": "### 2-4.", "E": "### 2-5.", "F": "### 2-6."}

    @classmethod
    def setUpClass(cls):
        cls.text = read("docs/V1_RELEASE_CHECKLIST.md")
        cls.rows = []
        for number, line in enumerate(cls.text.splitlines(), 1):
            if re.match(r"^\| [A-F]\d\d \|", line):
                match = cls.ROW.match(line)
                if not match:
                    raise AssertionError(f"점검표 {number}번째 줄의 모양이 틀렸다(8칸: 번호·파일:줄·찾는 조각·바꿀 문장·같이 볼 시험·담당·상태): {line[:80]!r}")
                cls.rows.append((number, *match.groups()))

    def test_the_table_has_the_six_groups_with_numbered_rows_in_order(self):
        self.assertGreaterEqual(len(self.rows), 40)
        ids = [row[1] for row in self.rows]
        self.assertEqual(len(ids), len(set(ids)), "번호가 겹친다")
        for letter, heading in self.GROUPS.items():
            mine = [row for row in self.rows if row[1][0] == letter]
            self.assertGreaterEqual(len(mine), 3, letter)
            self.assertEqual([row[1] for row in mine], [f"{letter}{n:02d}" for n in range(1, len(mine) + 1)], f"{letter} 번호는 01 부터 빈틈없이")
            section = part(self.text, heading, "\n### " if letter != "F" else "\n## 3.")
            for row in mine:
                self.assertIn(f"| {row[1]} |", section, f"{row[1]} 는 {heading} 절 안에 있어야 한다")

    def test_every_row_points_at_a_real_file_and_its_fragment_matches_the_status(self):
        for number, label, rel, line_no, fragment, _draft, _tests, _owner, status in self.rows:
            with self.subTest(row=label):
                path = ROOT / rel
                self.assertTrue(path.is_file(), f"{label}: 파일이 없다 {rel}")
                self.assertGreaterEqual(int(line_no), 1)
                body = path.read_text(encoding="utf-8")
                if status == "고침":
                    self.assertNotIn(fragment, body, f"{label}: '고침' 인데 조각이 {rel} 에 아직 있다")
                else:
                    self.assertIn(fragment, body, f"{label}: 조각이 {rel} 에서 사라졌다 — 그 문장을 고쳤다면 이 표의 {label} 상태를 '고침' 으로 바꾼다(그 뒤 조각은 없어야 한다)")

    def test_the_status_words_the_owners_and_the_test_modules_are_real(self):
        for _number, label, _rel, _line, _fragment, _draft, tests, owner, status in self.rows:
            with self.subTest(row=label):
                self.assertIn(status, ("대기", "고침", "고치지 않음"))
                for name in re.findall(r"[·\s(]*test_[a-z0-9_]+", tests):
                    module = name.strip(" ·(")
                    self.assertTrue((ROOT / "tests" / f"{module}.py").is_file(), f"{label}: 같이 볼 시험 {module} 이 없다")
                for name in owner.strip().split("·"):
                    self.assertIn(name.strip(), self.OWNERS, f"{label}: 담당 이름 {name!r}")
        for _number, label, _rel, _line, _fragment, draft, _tests, _owner, status in self.rows:
            if status == "고치지 않음":
                self.assertTrue(any(word in draft for word in ("고치지 않는다", "고치지 않는", "그대로 둔다", "고치지 않음")), f"{label}: 고치지 않는 이유가 적혀야 한다")

    def test_the_non_sentence_table_lists_ten_checks_and_names_a_tool_that_does_not_exist_yet_honestly(self):
        table = part(self.text, "## 3. 문장이 아닌 점검", "## 4.")
        rows = re.findall(r"(?m)^\| (G\d\d) \| (.+) \| (.+) \| (.+) \|$", table)
        self.assertEqual([row[0] for row in rows], [f"G{n:02d}" for n in range(1, 11)])
        exists = (ROOT / "scripts" / "release_check.py").exists()
        says_missing = "`scripts/release_check.py` — 아직 없다" in self.text
        self.assertEqual(exists, not says_missing, "scripts/release_check.py 가 생겼거나 없어졌는데 점검표의 '아직 없다' 문장이 그대로다")

    def test_the_version_facts_the_checklist_relies_on_are_true(self):
        self.assertIn("preview", read("VERSION"), "VERSION 이 미리보기 버전이 아니게 됐다 — 점검표 B01 을 '고침' 으로")
        packaging_support = read("tests/packaging_support.py")
        self.assertIn('VERSION = "0.1.0-preview.1"', packaging_support, "B01 이 말한 시험 상수가 달라졌다")
        changelog_head = re.search(r"^## \[([^\]]+)\]", read("CHANGELOG.md"), re.M).group(1)
        self.assertEqual(changelog_head, read("VERSION").strip())


def release_section(changelog, version):
    """CHANGELOG 글에서 `version` 의 절을 (머리 줄, 본문)으로 돌려준다 — `docs/RELEASE.md` 의 '릴리스 노트 규칙' 3 의 1·2 를 글자 그대로 옮긴 참고 구현이다(릴리스 갈래가 `scripts/` 로 옮긴다).
    머리 줄은 `## [버전] — YYYY-MM-DD` 이고(옛 절은 뒤에 괄호 설명이 붙는다) 같은 버전이 정확히 하나여야 하며, 절은 다음 `## [` 줄 앞까지다. 본문은 머리 줄을 뺀 글의 앞뒤 빈 줄을 지운 것이다."""
    heading = re.compile(r"^## \[([^\]]+)\] — (\d{4}-\d{2}-\d{2})(?: \(.+\))?$")
    lines = changelog.replace("\r\n", "\n").split("\n")
    heads = [index for index, line in enumerate(lines) if heading.match(line) and heading.match(line).group(1) == version]
    if len(heads) != 1:
        raise ValueError(f"머리 줄이 정확히 하나여야 한다(버전 {version}, 찾은 수 {len(heads)})")
    start = heads[0]
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## [")), len(lines))
    return lines[start], "\n".join(lines[start + 1:end]).strip("\n")


SAMPLE_CHANGELOG = """# 변경 이력

## [1.0.0-rc.1] — 2026-12-01

### 요약
- 다음 후보.

## [1.0.0] — 2026-12-10

### 요약
- 첫 정식 판.

### 자세히
- 둘째 줄.

## [0.9.0] — 2026-11-30 (옛 모양의 괄호 설명)

- 옛 절이다.

## [0.8.0] 날짜가 없는 머리 줄

- 읽지 않는다.

## [0.7.0] — 2026-10-01

## [0.7.0] — 2026-10-02
"""


class ReleaseNotesRuleTest(unittest.TestCase):
    def setUp(self):
        self.rule = part(read("docs/RELEASE.md"), "## 릴리스 노트 규칙", NEXT_SECTION)

    def test_the_reference_implementation_picks_the_section_the_rule_describes(self):
        head, body = release_section(SAMPLE_CHANGELOG, "1.0.0")
        self.assertEqual(head, "## [1.0.0] — 2026-12-10")
        self.assertEqual(body, "### 요약\n- 첫 정식 판.\n\n### 자세히\n- 둘째 줄.", "머리 줄을 빼고 앞뒤 빈 줄을 지운다 — 소제목(###)에서는 끝나지 않는다")
        self.assertEqual(release_section(SAMPLE_CHANGELOG, "1.0.0-rc.1")[1], "### 요약\n- 다음 후보.", "시험판 이름은 1.0.0 과 따로다")
        self.assertEqual(release_section(SAMPLE_CHANGELOG, "0.9.0")[1], "- 옛 절이다.", "옛 모양(괄호 설명)도 읽는다")
        self.assertEqual(release_section(SAMPLE_CHANGELOG.replace("\n", "\r\n"), "1.0.0")[0], "## [1.0.0] — 2026-12-10", "줄 끝이 CRLF 여도 같다")

    def test_the_reference_implementation_refuses_missing_duplicate_and_dateless_headings(self):
        for version in ("9.9.9", "0.8.0", "0.7.0"):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    release_section(SAMPLE_CHANGELOG, version)
        self.assertEqual(release_section("## [1.0.0] — 2026-12-10\n", "1.0.0")[1], "", "내용이 빈 절도 하나로 읽힌다(모양 검사가 따로 거절한다)")

    def test_every_heading_of_the_real_changelog_can_be_read_by_the_rule_and_the_top_one_by_version(self):
        changelog = read("CHANGELOG.md")
        headings = [line for line in changelog.splitlines() if line.startswith("## [")]
        self.assertGreaterEqual(len(headings), 2)
        readable = re.compile(r"^## \[[^\]]+\] — \d{4}-\d{2}-\d{2}(?: \(.+\))?$")
        for line in headings:
            self.assertRegex(line, readable, "릴리스 노트 규칙이 읽지 못하는 머리 줄이 생겼다")
        head, body = release_section(changelog, read("VERSION").strip())
        self.assertTrue(head.startswith(f"## [{read('VERSION').strip()}] — "))
        self.assertGreater(len(body), 0)

    def test_the_section_states_the_rule_and_marks_every_outside_tool_fact_as_needing_confirmation(self):
        for needle in ("정본은 `CHANGELOG.md` 의 `## [X.Y.Z] — 날짜` 절이다", "### 요약", "### 자세히", "### 이관 노트", "20,000자", "정확히 하나", "**20,000자 이하**", "다음 `## [` 줄 앞까지",
                       "글자 그대로 같아야 한다", "초안 릴리스", "Publish release", "`vX.Y.Z`", "확인 C", "MIGRATION_NOTES_TEMPLATE.md", "V1_RELEASE_CHECKLIST.md"):
            self.assertIn(needle, self.rule, needle)
        self.assertIn("| `VERSION` = `CHANGELOG.md` 맨 위 절의 버전 |", self.rule)

    def test_every_line_that_states_an_outside_tool_fact_says_it_is_not_confirmed(self):
        keywords = ("본문 한도", "본문 길이 한도", "--notes-file", "태그 생성 시점", "불변 릴리스", "자동 생성")
        lines = [line for line in self.rule.splitlines() if any(word in line for word in keywords)]
        self.assertGreaterEqual(len(lines), 5)
        for line in lines:
            self.assertTrue("확인 필요" in line or "원문 대조 필요" in line, f"바깥 도구의 사실을 확인 필요 표시 없이 적었다: {line[:60]}")

    def test_the_four_things_that_must_match_are_either_tested_today_or_marked_as_missing(self):
        table = part(self.rule, "### 4. 같아야 하는 것들", "### 5.")
        rows = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith("| 같아야")]
        self.assertEqual(len(rows), 6)
        for row in rows:
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            self.assertEqual(len(cells), 3, row)
            if "**없음**" in cells[2]:
                self.assertIn("갈래", cells[2], "아직 없는 것은 어느 갈래의 몫인지 적는다")
        self.assertGreaterEqual(len([row for row in rows if "있음" in row]), 1)
        tag_row = next(row for row in rows if "태그 이름" in row)
        notes_row = next(row for row in rows if "Release 본문" in row)
        check_row = next(row for row in rows if "후보 빌드" in row)
        workflows = [path.name.lower() for path in (ROOT / ".github" / "workflows").glob("*.y*ml")]
        self.assertEqual("**없음**" in tag_row, not any("release" in name for name in workflows), "릴리스 워크플로가 생겼거나 없어졌는데 표의 태그 줄이 그대로다")
        self.assertEqual("**없음**" in notes_row, not (ROOT / "scripts" / "release_notes.py").exists(), "본문 만드는 스크립트가 생겼거나 없어졌는데 표의 본문 줄이 그대로다")
        self.assertEqual("**없음**" in check_row, not (ROOT / "scripts" / "release_check.py").exists(), "종합 점검 스크립트가 생겼거나 없어졌는데 표의 점검 줄이 그대로다")
        self.assertIn("VersionTest", table)
        self.assertTrue((ROOT / "tests" / "test_repo_layout.py").is_file() and "class VersionTest" in read("tests/test_repo_layout.py"))

    def test_the_scripts_the_rule_says_do_not_exist_yet_really_do_not_exist(self):
        exists = (ROOT / "scripts" / "release_notes.py").exists()
        says_missing = "`scripts/release_notes.py` — **아직 없다**" in self.rule
        self.assertEqual(exists, not says_missing, "scripts/release_notes.py 가 생겼거나 없어졌는데 RELEASE.md 의 '아직 없다' 문장이 그대로다")
        exists = (ROOT / "scripts" / "release_check.py").exists()
        says_missing = "`scripts/release_check.py`)가 한 번에 견준다 | **없음**" in self.rule
        self.assertEqual(exists, not says_missing, "scripts/release_check.py 가 생겼거나 없어졌는데 RELEASE.md 의 표가 그대로다")

    def test_the_existing_release_document_still_starts_with_its_banner_and_keeps_its_old_sections(self):
        text = read("docs/RELEASE.md")
        self.assertTrue(text.startswith("# 설치 파일·자동 업데이트·릴리스"))
        for kept in ("## 방식", "## 릴리스 절차", "## 코드 서명", "Velopack", "장래 설계(미구현)"):
            self.assertIn(kept, text, kept)
        self.assertEqual(text.count("## 릴리스 노트 규칙"), 1)


class PersonalPcTestDraftTest(unittest.TestCase):
    ROW_IDS = ("0-1", "0-2", "0-3", "1-1", "1-2", "1-3", "1-4", "2", "3", "4-1", "4-3", "4-4", "4-5", "4-6", "5-1", "5-2", "5-3", "6-3", "6-4", "6-5", "7-2", "7-4", "7-5",
               "8-1", "8-2", "8-3", "9-4", "9-6", "9-7", "10-1", "10-4", "10-5", "10-6")

    def setUp(self):
        self.text = read("docs/PERSONAL_PC_TEST_V1_DRAFT.md")

    def test_title_and_the_draft_notice_come_first_and_the_old_sheet_is_not_touched(self):
        lines = [line for line in self.text.splitlines() if line.strip()]
        self.assertEqual(lines[0], "# 개인 PC 시험 안내서 — ChanceBlog Desktop 1.0 (초안)")
        self.assertTrue(lines[1].startswith("**초안입니다 —") and "〔확인 필요〕" in lines[1])
        self.assertEqual(self.text.count("〔"), self.text.count("〕"), "〔확인 필요〕 표시의 괄호가 짝이 맞아야 한다(채우면서 지우다 반쪽이 남지 않게)")
        old = read("docs/PERSONAL_PC_TEST.md")
        self.assertTrue(old.startswith("# 개인 PC 제한 시험 안내서 — ChanceBlog Desktop 0.1.0-preview.1"), "기존 시험지는 고치지 않는다")
        self.assertEqual([number for number, _t in re.findall(r"(?m)^## (\d)단계\. (.+)$", old)], [str(n) for n in range(9)])

    def test_the_thirteen_numbered_steps_are_there_in_order_with_the_new_flows(self):
        headings = re.findall(r"(?m)^## (\d+)단계\. (.+)$", self.text)
        self.assertEqual([number for number, _title in headings], [str(n) for n in range(13)])
        for _number, title in headings:
            self.assertGreaterEqual(len(title.strip()), 4)
        titles = {number: title for number, title in headings}
        for number, word in (("1", "설치"), ("4", "업데이트"), ("5", "되돌리기"), ("6", "제거"), ("7", "휴대용"), ("9", "Pages 시험 글"), ("10", "Blogger 초안"), ("11", "결과 보고"), ("12", "지우기")):
            self.assertIn(word, titles[number], number)
        self.assertIn("## 막혔을 때", self.text)
        self.assertIn("## 읽고 시작해 주세요", self.text)
        self.assertIn("**멈추고 바로 알릴 일**", self.text)

    def test_every_step_has_check_boxes_and_the_pass_lines_the_operator_needs(self):
        self.assertGreaterEqual(self.text.count("- [ ] "), 50)
        self.assertGreaterEqual(self.text.count("**통과**") + self.text.count("이렇게 보이면 통과"), 40)
        for step in re.split(r"(?m)^## ", self.text):
            if re.match(r"\d+단계", step) and not step.startswith(("11단계", "12단계")):
                with self.subTest(step=step.splitlines()[0]):
                    self.assertIn("[ ]", step)
                    self.assertTrue("통과" in step)

    def test_the_report_table_has_a_row_for_the_key_checks_and_four_cells_each(self):
        table = part(self.text, "## 11단계. 결과 보고", "## 12단계")
        rows = [line for line in table.splitlines() if re.match(r"^\| (\d+)(-\d+)? \|", line)]
        self.assertEqual([row.split("|")[1].strip() for row in rows], list(self.ROW_IDS))
        for row in rows:
            self.assertEqual(row.count("|"), 5, row)
        self.assertIn("| 번호 | 확인한 것 | 결과 | 적어 둘 말 |", table)
        for needle in ("통과", "실패", "해당 없음", "승인 전", "실패(권한 없음)", "Windows 버전", "화면 배율", "스마트 앱 컨트롤", "Windows` 키 + `Shift` + `S"):
            self.assertIn(needle, table, needle)
        for label in re.findall(r"\*\*(\d+-\d+)\.", self.text):
            self.assertRegex(label, r"^\d+-\d+$")
        for row_id in self.ROW_IDS:
            if "-" in row_id:
                self.assertIn(f"**{row_id}.", self.text, f"보고 표의 {row_id} 에 해당하는 단계 글이 없다")

    def test_the_two_real_service_steps_wait_for_approval_and_login_goes_only_into_the_companys_own_window(self):
        for needle in ("0단계의 릴리스 화면(GitHub", "9단계(GitHub)·10단계(Google)뿐", "번호 있는 요청에서 승인한 뒤에만", "승인 전", "그 회사의 로그인 창에만", "앱·이 시험지·보고·사진·AI 대화창 어디에도 적지 않습니다"):
            self.assertIn(needle, self.text, needle)
        step9 = part(self.text, "## 9단계.", "## 10단계.")
        step10 = part(self.text, "## 10단계.", "## 11단계.")
        for needle in ("운영자가 승인한 뒤에만", "`main` 에 **직접 올리지 않고 별도의 가지에만**", "운영자가 GitHub 화면에서 직접", "제목에 `시험`", "에 직접 올라가지 않았는지", "병합 대기"):
            self.assertIn(needle, step9, needle)
        for needle in ("운영자가 승인한 뒤에만", "초안으로만", "공개하지 않습니다", "브라우저에 뜬 구글의 창에서만", "연결 끊기", "진단 정보 복사"):
            self.assertIn(needle, step10, needle)

    def test_the_update_and_rollback_steps_cover_backup_before_update_data_kept_and_the_newer_data_notice(self):
        step4 = part(self.text, "## 4단계.", "## 5단계.")
        step5 = part(self.text, "## 5단계.", "## 6단계.")
        for needle in ("업데이트 전 백업", "사용자가 단추를 눌렀을 때만", "내 데이터가 그대로인지", "관리자 권한 요구 창이 한 번도 안 뜹니다"):
            self.assertIn(needle, step4, needle)
        for needle in ("앱이 스스로 되돌리는 경우", "사람이 직접 되돌리는 경우", "올리기 전 백업", "더 새로운 버전의 프로그램이 만든", "다시 업데이트"):
            self.assertIn(needle, step5, needle)

    def test_the_removal_and_portable_steps_keep_user_data_and_name_the_decision_they_wait_for(self):
        step6 = part(self.text, "## 6단계.", "## 7단계.")
        step7 = part(self.text, "## 7단계.", "## 8단계.")
        for needle in ("`ChanceblogDesktop` 폴더가 **그대로 있고**", "기본 보존", "다시 설치하면 데이터가 그대로", "자격 증명", "확인 C"):
            self.assertIn(needle, step6, needle)
        for needle in ("`ChanceBlogTest`", "Program Files", "OneDrive", "100글자", "설치형과 데이터 폴더가 같은지", "이미 열려 있거나 열리는 중이에요", "시작 메뉴·레지스트리"):
            self.assertIn(needle, step7, needle)

    def test_the_screen_words_the_draft_tells_the_operator_to_press_are_the_real_app_words(self):
        real = {value for value in T.values() if isinstance(value, str)}
        labels = ("홈", "주제 후보", "초안 작성", "Seed 관리", "블로그 관리", "설정", "새 Seed 등록", "승인하기", "후보 만들기", "만들기", "이 주제로 만들기", "키 등록", "삭제", "저장", "정보",
                  "다음", "표시 이름", "블로그 ID 또는 주소", "Seed 낱말", "대분류", "중분류", "중요도", "대상 유형", "소속", "승인 전으로 등록", "AI 보조", "별칭", "저장된 키", "지금 백업",
                  "복원", "복원하기", "Credential 제외됨", "백업·복원", "연결 관리", "저장한 초안", "계속 고치기", "진단 정보 복사", "네이버 블로그",
                  "연결 안 됨 — 키 없이도 쓸 수 있어요")
        for label in labels:
            with self.subTest(label=label):
                self.assertIn(label, real, f"시험지 초안이 부르는 '{label}' 이 앱의 화면 글자에 없다")
                self.assertIn(label, self.text, label)
        purpose = connections.PURPOSES["ai_assist"]
        self.assertEqual(purpose.label, "AI 보조(선택)")
        self.assertEqual([field.label for field in purpose.fields], ["API 키"])
        self.assertEqual(connections.PURPOSES["naver_apihub"].label, "NAVER API HUB 검색어 트렌드")
        for needle in ("`AI 보조(선택)` 카드", "`API 키`", "NAVER API HUB 검색어 트렌드"):
            self.assertIn(needle, self.text, needle)
        self.assertIn("이미 열려 있거나 열리는 중이에요", read("src/chanceblog_desktop/ui/single_instance.py") + read("src/chanceblog_desktop/ui/launcher.py") + "".join(real))

    def test_the_only_fake_key_is_the_agreed_text_and_the_app_accepts_it(self):
        self.assertEqual(set(re.findall(r"TEST-KEY-NOT-REAL(?:-TEST-KEY-NOT-REAL)?", self.text)), {"TEST-KEY-NOT-REAL", "TEST-KEY-NOT-REAL-TEST-KEY-NOT-REAL"})
        for value in ("TEST-KEY-NOT-REAL", "TEST-KEY-NOT-REAL-TEST-KEY-NOT-REAL"):
            self.assertEqual(shape.value_problem(value, min_len=16, max_len=256), "", value)
            self.assertFalse(shape.looks_secret(value), value)
        pattern = re.compile(r"AIza[0-9A-Za-z_-]{35}|(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-[A-Za-z0-9]{32,}")
        self.assertIsNone(pattern.search(self.text))

    def test_it_sends_trial_builds_away_and_does_not_allow_not_applicable_for_required_lines(self):
        head = part(self.text, "# 개인 PC", "## 읽고 시작해 주세요")
        for needle in ("후보 빌드", "TESTBUILD" if "TESTBUILD" in head else "시험 빌드", "이 시험지로 시험하지 말고"):
            self.assertIn(needle, head + self.text, needle)
        for line in self.text.splitlines():
            if "해당 없음" in line:
                self.assertTrue(any(word in line for word in ("(선택)", "쓸 수 없", "아니라", "경우에만", "않았을 때만")), line)


class MigrationNotesTemplateTest(unittest.TestCase):
    def setUp(self):
        self.text = read("docs/MIGRATION_NOTES_TEMPLATE.md")

    def test_title_sections_and_the_form_with_all_its_sub_headings(self):
        self.assertTrue(self.text.startswith("# 이관 노트(MIGRATION_NOTES) 틀"))
        for heading in ("## 1. 언제 쓰나", "## 2. 파일의 모양", "## 3. 절의 틀", "## 4. 쓰는 규칙", "## 5. 사용자 데이터가 어디에 있나", "## 6. 사실을 읽는 곳", "## 7. 이 틀이 아직 정하지 못한 것"):
            self.assertIn(heading, self.text, heading)
        form = part(self.text, "```text", "```\n\n## 4.")
        for sub in ("### 한눈에", "### 올리기 전에", "### 데이터가 바뀌는 곳", "### 직접 해야 할 일", "### 올린 뒤에 확인할 것", "### 문제가 생기면", "### 되돌리기", "### 알려 둔 한계", "### 근거"):
            self.assertIn(sub, form, sub)
        self.assertIn("## [「X.Y.Z」] — 「YYYY-MM-DD」", form)
        self.assertEqual(self.text.count("```"), 2, "코드 블록은 틀 하나뿐이다")

    def test_the_schema_numbers_the_template_states_are_the_code_values(self):
        rows = [line for line in part(self.text, "## 5. 사용자 데이터가 어디에 있나", "## 6.").splitlines() if line.startswith("| ")]
        store_row = next(row for row in rows if "`chanceblog.db`" in row)
        engine_row = next(row for row in rows if "`topic_engine/topic_engine.db`" in row)
        for label, row, version in (("글 보관함", store_row, content_store.SCHEMA_VERSION), ("주제 엔진 보관함", engine_row, topic_store.SCHEMA_VERSION)):
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            self.assertEqual(cells[3], str(version), f"{label}: 이관 노트 틀 §5 표의 '지금 판' 이 코드의 구조 번호와 다르다 — 표를 고친다")
        self.assertEqual((content_store.SCHEMA_VERSION, topic_store.SCHEMA_VERSION), (2, 2))

    def test_the_error_names_exist_in_the_error_catalog_and_the_troubleshooting_table(self):
        trouble = read("docs/TROUBLESHOOTING.md")
        for code in ("MIGRATION_FAILED", "MIGRATION_BLOCKED", "STORE_VERSION_UNSUPPORTED", "STORE_CORRUPT"):
            self.assertIn(code, self.text, code)
            self.assertIn(code, CATALOG, code)
            self.assertIn(f"| `{code}` |", trouble, code)

    def test_every_error_like_name_in_the_template_is_a_real_error_code_or_a_known_file_or_constant_name(self):
        names = set(re.findall(r"(?<![A-Za-z0-9_])[A-Z]{2,}(?:_[A-Z0-9]+)+(?![A-Za-z0-9_])", self.text))
        other = {"MIGRATION_NOTES", "DECISIONS_INDEX", "SCHEMA_VERSION"}            # 파일 이름·소스 상수 이름(오류 코드가 아니다)
        self.assertEqual({name for name in names if name not in other and name not in CATALOG}, set(), "오류 이름의 오타이거나 없어진 코드")
        self.assertTrue({"MIGRATION_FAILED", "MIGRATION_BLOCKED", "STORE_VERSION_UNSUPPORTED", "STORE_CORRUPT"} <= names)

    def test_what_the_template_says_the_full_backup_keeps_and_leaves_out_is_what_the_backup_code_does(self):
        table = part(self.text, "## 5. 사용자 데이터가 어디에 있나", "## 6.")
        kept = {component.name for component in backup_flow.COMPONENTS}
        kept_in_table, left_out_in_table = set(), set()
        for row in table.splitlines():
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            if not row.startswith("| ") or len(cells) != 6 or cells[0] in ("데이터", "---"):
                continue
            names = {match for match in re.findall(r"`(?:[^`/]*/)?([^`/]+\.(?:db|json))`", cells[1])}
            if cells[5].startswith("담는다"):
                kept_in_table |= names
            elif cells[5].startswith("담지 않는다"):
                left_out_in_table |= names
        self.assertEqual(kept_in_table, kept, "표가 '담는다' 로 적은 파일이 백업 코드의 목록(COMPONENTS)과 다르다")
        self.assertEqual(left_out_in_table & kept, set(), "표가 '담지 않는다' 로 적은 파일을 백업이 담고 있다")
        for name in ("connections.json", "quota_state.json"):
            self.assertIn(name, left_out_in_table, name)
        self.assertIn("`references/`", self.text)
        self.assertNotIn("references", kept)

    def test_it_says_that_a_lower_version_does_not_open_newer_data_and_that_keys_live_outside_the_data(self):
        for needle in ("낮은 버전이 열지 않는다", "올리기 전에 만든 백업을 복원", "Windows 자격 증명 관리자", "Credential 제외됨", "한 바이트도 바꾸지 않는다", "같은 사실"):
            self.assertIn(needle, self.text, needle)
        self.assertIn("STORE_VERSION_UNSUPPORTED", self.text)


if __name__ == "__main__":
    unittest.main()
