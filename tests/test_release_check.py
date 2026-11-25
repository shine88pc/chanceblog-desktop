"""릴리스 후보 점검 스크립트(`scripts/release_check.py`, D-670–D-675) 시험 — 열두 항목마다 PASS·FAIL·수동·아직 길을 가짜 저장소 사본(임시 폴더)으로 지나 본다.

지키는 것:
  1) 표 모양: 항목 열두 개가 번호 순으로 나오고, 상태는 넷 중 하나이며 근거는 한 줄이다. FAIL 이 있어야만 종료 코드가 1 이다.
  2) 항목마다 길: 1 새 clone 준비물 · 2 문서와 결정 색인 · 3 D-18 표 · 4 기본 설정의 유료 호출 · 5 Pages · 6 Blogger · 7 네이버 · 8 티스토리 · 9 업데이트 · 10 키 모양 훑기 · 11 자가 점검 · 12 버전.
     점검이 읽는 파일 목록·개수는 시험에 글자 그대로 적는다(소스의 상수를 되풀이해 돌면 목록에서 항목을 빼도 초록이다). 7·9·11번은 이름만 같은 빈 껍데기가 수동으로 오르지 않는다(import 문·함수가 든 파일·설치 정의 파일만).
  3) 읽기 전용: 하위 프로세스·접속을 부르면 시험이 알리고, 점검 전후 폴더의 바이트 지문이 같다. 소스에 쓰기 호출·밖으로 나가는 모듈이 없다. 건너뜀 이유에 화면 부품 이름이 없다(정식 CI 의 Qt 칸 가드).
  4) 실제 저장소: 점검이 끝까지 돌고(예상 못 한 오류 0) 안전 항목(1·4·8·12)이 FAIL 이 아니다. 다른 갈래가 병합돼 바뀔 수 있는 항목(2·3·5–7·9–11)의 상태는 못박지 않는다 — 끝에서 끝 시험의 종료 코드도 표의 exit_code 와 견줄 뿐 0 을 못박지 않는다.
  5) 문서: 결정 D-670–D-675(D-675 는 독립 검증 재작업 결정)와 변경 이력·구조 문서가 이 도구를 적고, 겹침·놓치지 않는 길이·알려 둔 한계의 숫자와 이름이 스크립트와 같다.
후보 폴더 훑기는 `test_release_check_scan.py` 가 지킨다. 네트워크·실제 비밀 없이 돈다.
"""
import ast
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import release_check_support as rs
from release_check_support import APP, rc

ROOT = rs.ROOT
SCRIPT = ROOT / "scripts" / "release_check.py"
TILDE, ADDRESS, BRACES = chr(126), "ht" + "tp", chr(123) * 2
PASS, FAIL, MANUAL, NOT_YET = rc.STATUS_PASS, rc.STATUS_FAIL, rc.STATUS_MANUAL, rc.STATUS_NOT_YET
BASELINE = {1: MANUAL, 2: NOT_YET, 3: NOT_YET, 4: PASS, 5: NOT_YET, 6: NOT_YET, 7: NOT_YET, 8: PASS, 9: NOT_YET, 10: MANUAL, 11: NOT_YET, 12: MANUAL}


class RepoCase(unittest.TestCase):
    """기준 사본을 만들고 점검을 돌리는 도우미가 붙은 시험 틀.

    기준 사본은 시험 묶음(클래스)마다 한 번만 만들고, 시험은 `build(drop=…, extra=…)` 로 파일 몇 개만 지우거나 바꾼다(끝나면 모두 되돌린다 — 파일 수십 개를 시험마다 새로 쓰면 윈도에서 느리다).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._base_temp = rs.temp_dir()
        cls.root = Path(cls._base_temp.name)
        rs.build_repo(cls.root)
        cls.base_files = {path.relative_to(cls.root).as_posix(): path.read_bytes() for path in cls.root.rglob("*") if path.is_file()}
        cls.base_dirs = {path.relative_to(cls.root).as_posix() for path in cls.root.rglob("*") if path.is_dir()}

    @classmethod
    def tearDownClass(cls):
        cls._base_temp.cleanup()
        super().tearDownClass()

    def setUp(self):
        self._touched = set()
        self.addCleanup(self._restore)

    def _restore(self):
        """이 시험이 바꾸거나 더하거나 지운 파일을 기준 사본대로 되돌리고, 시험이 만든 빈 폴더는 치운다."""
        for rel in sorted(self._touched):
            path = self.root.joinpath(*rel.split("/"))
            if rel in self.base_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self.base_files[rel])
                continue
            if path.is_file():
                path.unlink()
            parent = path.parent
            while parent != self.root and parent.relative_to(self.root).as_posix() not in self.base_dirs and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        self._touched.clear()

    def build(self, *, drop=(), extra=None):
        """기준 사본에서 시작해(앞의 변경은 되돌린다) `drop` 의 파일을 지우고 `extra`({경로: 글 또는 바이트}) 를 더하거나 바꾼다."""
        self._restore()
        for rel in drop:
            if rel not in self.base_files:
                raise KeyError(rel)
            self._touched.add(rel)
            self.root.joinpath(*rel.split("/")).unlink()
        for rel, text in (extra or {}).items():
            self.put(rel, text)
        return self.root

    def rows(self, **kwargs):
        selftest = kwargs.pop("selftest", rs.selftest_ok)
        return rs.rows_of(self.root, selftest=selftest, **kwargs)

    def row_after(self, number, **kwargs):
        """`build(drop=…, extra=…)` 한 뒤 그 번호의 줄."""
        self.build(drop=kwargs.pop("drop", ()), extra=kwargs.pop("extra", None))
        return self.rows(**kwargs)[number]

    def status(self, number, **kwargs):
        return self.rows(**kwargs)[number].status

    def basis(self, number, **kwargs):
        return self.rows(**kwargs)[number].basis

    def edit(self, rel, old, new):
        path = self.root.joinpath(*rel.split("/"))
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, f"{rel}: 바꿀 글이 정확히 한 번 나오지 않는다")
        self._touched.add(rel)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def put(self, rel, text):
        self._touched.add(rel)
        rs.write_files(self.root, {rel: text})


class TableShapeTest(RepoCase):
    def test_the_baseline_copy_gives_the_expected_status_for_every_item(self):
        self.build()
        self.assertEqual({number: row.status for number, row in self.rows().items()}, BASELINE)

    def test_twelve_rows_come_out_in_order_with_the_criteria_titles(self):
        self.build()
        rows = rc.run_checks(self.root, selftest_runner=rs.selftest_ok)
        self.assertEqual([row.number for row in rows], list(range(1, 13)))
        self.assertEqual([row.title for row in rows], [rc.TITLES[number] for number in range(1, 13)])
        self.assertEqual(len(set(row.title for row in rows)), 12)

    def test_every_status_is_one_of_the_four_names_and_every_basis_is_one_nonempty_line(self):
        self.build()
        for row in rc.run_checks(self.root, selftest_runner=rs.selftest_ok):
            self.assertIn(row.status, (PASS, FAIL, MANUAL, NOT_YET), row.number)
            self.assertTrue(row.basis.strip(), row.number)
            self.assertNotIn("\n", row.basis, row.number)

    def test_the_four_status_names_are_exactly_the_agreed_words(self):
        self.assertEqual(rc.STATUSES, ("PASS", "FAIL", "수동(운영자)", "아직(미구현)"))

    def test_exit_code_is_one_only_when_a_row_is_fail(self):
        self.build()
        self.assertEqual(rc.exit_code(rc.run_checks(self.root, selftest_runner=rs.selftest_ok)), 0)
        self.build(drop=["docs/MIGRATION.md"])
        rows = rc.run_checks(self.root, selftest_runner=rs.selftest_ok)
        self.assertIn(FAIL, [row.status for row in rows])
        self.assertEqual(rc.exit_code(rows), 1)

    def test_not_yet_and_manual_rows_alone_never_make_the_exit_code_nonzero(self):
        rows = [rc.Row(number, rc.TITLES[number], MANUAL if number % 2 else NOT_YET, "근거") for number in range(1, 13)]
        self.assertEqual(rc.exit_code(rows), 0)
        rows[5] = rc.Row(6, rc.TITLES[6], FAIL, "근거")
        self.assertEqual(rc.exit_code(rows), 1)

    def test_a_single_failing_check_is_shown_as_that_rows_fail_and_the_others_still_run(self):
        self.build()
        with mock.patch.object(rc, "check_5", side_effect=RuntimeError("가짜 오류")):
            statuses = {number: row.status for number, row in self.rows().items()}
        self.assertEqual(statuses[5], FAIL)
        self.assertEqual({number: status for number, status in statuses.items() if number != 5}, {number: status for number, status in BASELINE.items() if number != 5})

    def test_an_unexpected_error_text_names_only_the_error_kind(self):
        self.build()
        with mock.patch.object(rc, "check_5", side_effect=RuntimeError("비밀같은글 C:/Users/누군가/x")):
            basis = self.basis(5)
        self.assertIn("RuntimeError", basis)
        self.assertNotIn("비밀같은글", basis)
        self.assertNotIn("누군가", basis)

    def test_counts_add_up_to_twelve(self):
        self.build()
        tally = rc.counts(rc.run_checks(self.root, selftest_runner=rs.selftest_ok))
        self.assertEqual(sum(tally.values()), 12)
        self.assertEqual(tally, {PASS: 2, FAIL: 0, MANUAL: 3, NOT_YET: 7})

    def test_the_table_is_markdown_with_a_header_a_divider_and_twelve_rows_and_pipes_in_a_basis_do_not_break_it(self):
        self.build()
        rows = rc.run_checks(self.root, selftest_runner=rs.selftest_ok)
        rows[0] = rc.Row(1, rows[0].title, rows[0].status, "앞|뒤\n둘째 줄")
        lines = rc.render_table(rows).splitlines()
        self.assertEqual(len(lines), 14)
        self.assertTrue(lines[0].startswith("| 번호 |") and lines[1].startswith("|---|"))
        self.assertTrue(all(line.count("|") == 5 for line in lines))


class ExpectedListsTest(unittest.TestCase):
    """점검이 읽는 목록과 개수를 시험에 글자 그대로 적어 둔다 — 시험이 소스의 상수를 되풀이해 돌면 목록에서 항목을 빼도 모두 초록이다(독립 검증 Q R1).
    개수는 결정 D-671 ② 가 적은 것(준비물 다섯·문서 열한·Pages 여섯·네이버 네·보안 네·유료 호출을 막는 파일 셋)과 같다."""

    LISTS = (("CLONE_PREREQUISITES", rs.EXPECTED_PREREQUISITES, 5), ("REQUIRED_DOCS", rs.EXPECTED_DOCS, 11), ("PAGES_FILES", rs.EXPECTED_PAGES_FILES, 6),
             ("NAVER_FILES", rs.EXPECTED_NAVER_FILES, 4), ("SECURITY_FILES", rs.EXPECTED_SECURITY_FILES, 4), ("PAID_GUARD_FILES", rs.EXPECTED_PAID_GUARD_FILES, 3),
             ("TISTORY_DIRS", rs.EXPECTED_TISTORY_DIRS, 4), ("CAPABILITY_NAMES", rs.EXPECTED_CAPABILITY_NAMES, 3), ("PURPOSE_FIELDS", rs.EXPECTED_PURPOSE_FIELDS, 3))

    def test_every_list_the_check_reads_is_exactly_the_one_written_out_in_the_support_file(self):
        for name, expected, count in self.LISTS:
            with self.subTest(name=name):
                self.assertEqual(getattr(rc, name), expected)
                self.assertEqual(len(getattr(rc, name)), count)
                self.assertEqual(len(set(expected)), count)                      # 겹치는 항목 없음

    def test_the_twelve_titles_are_exactly_the_ones_written_out(self):
        self.assertEqual(rc.TITLES, rs.EXPECTED_TITLES)

    def test_the_backup_file_is_the_one_written_out(self):
        self.assertEqual(rc.BACKUP_FILE, rs.EXPECTED_BACKUP_FILE)

    def test_the_counts_are_the_numbers_the_decision_text_gives(self):
        row = next(line for line in (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines() if line.startswith("| D-671 |"))
        for phrase in ("준비물 다섯 파일", "열한 개", "Pages 올리기 코드 여섯 파일", "네이버 코드 네 파일", "보안 코드 네 파일", "유료 호출을 막는 쪽 파일 셋"):
            self.assertIn(phrase, row)

    def test_the_fake_repository_is_made_from_the_written_out_lists(self):
        files = rs.base_files()
        for rel in rs.EXPECTED_PREREQUISITES + rs.EXPECTED_DOCS:
            self.assertIn(rel, files, rel)
        for group in (rs.EXPECTED_PAGES_FILES, rs.EXPECTED_NAVER_FILES, rs.EXPECTED_SECURITY_FILES, (rs.EXPECTED_BACKUP_FILE,)):
            for rel in group:
                self.assertIn(f"{APP}/{rel}", files, rel)
        for rel in rs.EXPECTED_PAID_GUARD_FILES:
            self.assertIn(rel, files, rel)


class Item1Test(RepoCase):
    def test_every_missing_prerequisite_is_a_fail_naming_it(self):
        for rel in rs.EXPECTED_PREREQUISITES:
            with self.subTest(rel=rel):
                row = self.row_after(1, drop=[rel])
                self.assertEqual(row.status, FAIL)
                self.assertIn(rel, row.basis)

    def test_with_everything_in_place_it_is_manual_because_only_the_operator_can_try_a_fresh_clone(self):
        self.build()
        row = self.rows()[1]
        self.assertEqual(row.status, MANUAL)
        self.assertIn("운영자", row.basis)


class Item2Test(RepoCase):
    def index_text(self, numbers, style="plain"):
        cells = {"plain": "D-{n}", "bold": "**D-{n}**", "link": "[D-{n}](DECISIONS.md)", "code": "`D-{n}`"}[style]
        return "# 결정 색인\n\n| 번호 | 요약 |\n|---|---|\n" + "".join(f"| {cells.format(n=number)} | 요약 {number} |\n" for number in numbers) + rs.filler("색인")

    def test_a_missing_or_empty_entrance_doc_is_a_fail(self):
        for rel in rs.EXPECTED_DOCS:
            with self.subTest(rel=rel, kind="missing"):
                row = self.row_after(2, drop=[rel])
                self.assertEqual(row.status, FAIL)
                self.assertIn(rel, row.basis)
        for text in ("", "   \n\n  ", "짧은 글", "x" * 199):
            with self.subTest(text=len(text)):
                row = self.row_after(2, extra={"docs/SECURITY.md": text})
                self.assertEqual(row.status, FAIL)
                self.assertIn("docs/SECURITY.md", row.basis)

    def test_a_document_just_over_the_size_floor_counts_as_present(self):
        self.build(extra={"docs/SECURITY.md": "x" * 200})
        self.assertEqual(self.status(2), NOT_YET)

    def test_without_a_decision_index_the_item_is_not_yet_and_says_which_file(self):
        self.build()
        row = self.rows()[2]
        self.assertEqual(row.status, NOT_YET)
        self.assertIn(rc.DECISION_INDEX, row.basis)

    def test_an_index_that_matches_the_decision_log_makes_it_manual_for_the_blank_ai_test(self):
        for style in ("plain", "bold", "link", "code"):
            with self.subTest(style=style):
                row = self.row_after(2, extra={rc.DECISION_INDEX: self.index_text([1, 18, 19], style)})
                self.assertEqual(row.status, MANUAL)
                self.assertIn("3개", row.basis)

    def test_an_index_with_an_extra_number_is_a_fail(self):
        self.build(extra={rc.DECISION_INDEX: self.index_text([1, 18, 19, 20])})
        row = self.rows()[2]
        self.assertEqual(row.status, FAIL)
        self.assertIn("D-20", row.basis)
        self.assertIn("색인에만", row.basis)

    def test_an_index_missing_a_number_is_a_fail(self):
        self.build(extra={rc.DECISION_INDEX: self.index_text([1, 18])})
        row = self.rows()[2]
        self.assertEqual(row.status, FAIL)
        self.assertIn("D-19", row.basis)
        self.assertIn("결정 기록에만", row.basis)

    def test_an_index_with_no_decision_numbers_is_a_fail(self):
        self.build(extra={rc.DECISION_INDEX: "# 색인\n\n" + rs.filler("번호 없음")})
        self.assertEqual(self.status(2), FAIL)

    def test_a_decision_added_after_the_index_was_made_is_noticed(self):
        self.build(extra={rc.DECISION_INDEX: self.index_text([1, 18, 19])})
        self.assertEqual(self.status(2), MANUAL)
        self.edit("docs/DECISIONS.md", "| D-19 |", "| D-20 | 2026-11-24 | **새 결정** | 확정 |\n| D-19 |")
        self.assertEqual(self.status(2), FAIL)

    def test_a_missing_doc_wins_over_a_good_index(self):
        self.build(drop=["docs/RELEASE.md"], extra={rc.DECISION_INDEX: self.index_text([1, 18, 19])})
        self.assertEqual(self.status(2), FAIL)

    def test_decision_and_index_number_readers(self):
        self.assertEqual(rc.decision_numbers("| D-01 | a |\n| D-130 | b |\n본문 D-99 는 아니다\n| D-130 | c |\n"), {1, 130})
        self.assertEqual(rc.index_numbers("| **D-5** | x |\n| [D-7](a.md) | y |\n| D-100 | z |\n| 번호 | x |\n설명 D-9\n| `D-11` | w |\n"), {5, 7, 11, 100})
        self.assertEqual(rc.index_numbers("| D-1000 | x |\n"), {1000})


class Item3Test(RepoCase):
    MATRIX = "# 글 흐름 화면\n\nD-18 기능을 화면과 시험에 잇는 표.\n\n| 기능 | 화면 | 시험 |\n|---|---|---|\n| 가져오기 | 가져오기 화면 | `tests/test_exists.py` |\n| 검토 | 검토 카드 | `test_exists.py` |\n"

    def test_a_missing_architecture_section_or_feature_is_a_fail(self):
        self.build(extra={"docs/ARCHITECTURE.md": "# 구조\n\n" + rs.filler("구조")})
        self.assertEqual(self.status(3), FAIL)
        for name in rc.NO_AI_FEATURES:
            with self.subTest(name=name):
                row = self.row_after(3, extra={"docs/ARCHITECTURE.md": rs.ARCH_TEXT.replace(name, "빠진 기능")})
                self.assertEqual(row.status, FAIL)
                self.assertIn(name, row.basis)

    def test_the_section_heading_may_carry_a_number_or_not(self):
        self.build(extra={"docs/ARCHITECTURE.md": rs.ARCH_TEXT.replace("## 8. AI 없이", "## AI 없이")})
        self.assertEqual(self.status(3), NOT_YET)

    def test_a_feature_named_only_after_the_section_does_not_count(self):
        text = rs.ARCH_TEXT.replace(" · ".join(rc.NO_AI_FEATURES), "다른 글") + "\n\n## 10. 끝\n\n" + " · ".join(rc.NO_AI_FEATURES)
        self.build(extra={"docs/ARCHITECTURE.md": text})
        self.assertEqual(self.status(3), FAIL)

    def test_without_the_matrix_file_it_is_not_yet(self):
        self.build()
        row = self.rows()[3]
        self.assertEqual(row.status, NOT_YET)
        self.assertIn(rc.MATRIX_DOC, row.basis)

    def test_a_matrix_with_a_table_and_existing_tests_is_manual(self):
        self.build(extra={rc.MATRIX_DOC: self.MATRIX, "tests/test_exists.py": "# 시험(가짜)\n"})
        row = self.rows()[3]
        self.assertEqual(row.status, MANUAL)
        self.assertIn("표 2행", row.basis)
        self.assertIn("시험 파일 1개", row.basis)

    def test_a_matrix_pointing_at_a_test_file_that_does_not_exist_yet_is_not_yet(self):
        self.build(extra={rc.MATRIX_DOC: self.MATRIX})
        row = self.rows()[3]
        self.assertEqual(row.status, NOT_YET)
        self.assertIn("test_exists", row.basis)

    def test_a_matrix_without_d18_or_without_data_rows_is_not_yet(self):
        for label, text in (("D-18 없음", self.MATRIX.replace("D-18", "D-19")), ("표 없음", "# 글 흐름\n\nD-18 기능 설명만 있다.\n"),
                            ("머리만 있는 표", "# 글 흐름\n\nD-18\n\n| 기능 | 화면 |\n|---|---|\n")):
            with self.subTest(label=label):
                self.assertEqual(self.row_after(3, extra={rc.MATRIX_DOC: text, "tests/test_exists.py": "# x\n"}).status, NOT_YET)

    def test_a_matrix_without_any_test_names_is_still_manual_once_it_has_rows(self):
        self.build(extra={rc.MATRIX_DOC: "D-18\n\n| 기능 | 화면 |\n|---|---|\n| 가져오기 | 화면 |\n"})
        self.assertEqual(self.status(3), MANUAL)

    def test_the_architecture_check_comes_first(self):
        self.build(extra={rc.MATRIX_DOC: self.MATRIX, "tests/test_exists.py": "# x\n", "docs/ARCHITECTURE.md": "# 구조\n\n" + rs.filler("구조")})
        self.assertEqual(self.status(3), FAIL)

    def test_the_feature_list_is_the_same_as_the_repo_layout_test(self):
        import test_repo_layout
        self.assertEqual(rc.NO_AI_FEATURES, test_repo_layout.NO_AI_FEATURES)

    def test_table_row_counter(self):
        text = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n글\n\n| c |\n|:--|\n| 5 |\n\n| 줄만 |\n"
        self.assertEqual(rc.markdown_data_rows(text), 3)
        self.assertEqual(rc.markdown_data_rows("| a | b |\n|---|---|\n"), 0)
        self.assertEqual(rc.markdown_data_rows("표 없음"), 0)
        self.assertEqual(rc.markdown_data_rows("| a |\n| - |\n| 1 |\n"), 1)

    def test_test_file_name_finder(self):
        text = "`tests/test_a.py` `test_b.py` `tests/test_c` `test_d` `tests/test_a.py` `test_e.py::Kind::method` `tests/test_f.py:12` `x.py` `tests/other.py`"
        self.assertEqual(rc.named_test_files(text), ["test_a", "test_b", "test_c", "test_e", "test_f"])

    def test_section_finder(self):
        text = "# 문서\n\n## 7. 앞\n\n앞 글\n\n## 8. 찾는 절 (덧붙임)\n\n본문\n\n## 9. 뒤\n\n뒤 글\n"
        self.assertEqual(rc.find_section(text, "찾는 절").strip().split("\n")[-1], "본문")
        self.assertNotIn("뒤 글", rc.find_section(text, "찾는 절"))
        self.assertIsNone(rc.find_section(text, "없는 절"))


class Item4Test(RepoCase):
    def caps(self, **values):
        base = {"EXTERNAL_WRITE": "False", "BLOGGER_OAUTH_INPUT": "False", "LOCAL_OCR": "False"}
        base.update(values)
        return "".join(f"{name} = {value}\n" for name, value in base.items())

    def test_the_baseline_passes_and_the_basis_shows_the_gate_state_and_the_purpose_count(self):
        self.build()
        row = self.rows()[4]
        self.assertEqual(row.status, PASS)
        self.assertIn("EXTERNAL_WRITE=꺼짐", row.basis)
        self.assertIn("용도 3개", row.basis)
        self.assertIn("호출 코드가 있는 용도 0개", row.basis)

    def test_the_pass_basis_says_it_only_read_the_source_and_where_the_real_zero_calls_are_checked(self):
        """독립 검증 S 권고-2(총괄 결정): 4번 PASS 는 정적 읽기만이다 — 실제 0 호출은 다른 시험이 본다고 근거 글에 적는다(관문이 켜져도 PASS 인 설계는 그대로)."""
        for caps in (rs.CAPABILITIES_TEXT, rs.CAPABILITIES_TEXT.replace("EXTERNAL_WRITE = False", "EXTERNAL_WRITE = True")):
            self.build(extra={f"{APP}/capabilities.py": caps})
            row = rc.check_4(rc.Repo(self.root))
            self.assertEqual(row.status, PASS)
            self.assertIn("정적 읽기(상수·용도 기본값)만", row.basis)
            self.assertIn("실제 0 호출은 기본 설정 시험(네트워크 갈래)으로 확인", row.basis)

    def test_an_open_external_write_gate_is_shown_but_is_not_a_paid_call_so_it_still_passes(self):
        self.build(extra={f"{APP}/capabilities.py": self.caps(EXTERNAL_WRITE="True")})
        row = self.rows()[4]
        self.assertEqual(row.status, PASS)
        self.assertIn("EXTERNAL_WRITE=켜짐", row.basis)

    def test_missing_files_are_a_fail(self):
        for rel in rs.EXPECTED_PAID_GUARD_FILES:
            with self.subTest(rel=rel):
                self.assertEqual(self.row_after(4, drop=[rel]).status, FAIL)

    def test_constants_that_are_not_plain_true_or_false_are_a_fail(self):
        for label, text in (("정수", self.caps(EXTERNAL_WRITE="1")), ("글", self.caps(BLOGGER_OAUTH_INPUT="'no'")), ("계산식", self.caps(EXTERNAL_WRITE="bool(0)")),
                            ("없음", "EXTERNAL_WRITE = False\n"), ("OCR 정수", self.caps(LOCAL_OCR="0")), ("깨진 구문", "EXTERNAL_WRITE = (\n")):
            with self.subTest(label=label):
                self.assertEqual(self.row_after(4, extra={f"{APP}/capabilities.py": text}).status, FAIL)

    def test_the_constants_are_read_from_the_source_without_importing_it(self):
        self.build(extra={f"{APP}/capabilities.py": "raise RuntimeError('가져오면 안 된다')\nEXTERNAL_WRITE = False\nBLOGGER_OAUTH_INPUT = False\nLOCAL_OCR = False\n"})
        self.assertEqual(self.status(4), PASS)

    def test_a_typed_constant_assignment_is_read_too(self):
        self.build(extra={f"{APP}/capabilities.py": "EXTERNAL_WRITE: bool = False\nBLOGGER_OAUTH_INPUT: bool = False\nLOCAL_OCR: bool = False\n"})
        self.assertEqual(self.status(4), PASS)

    def test_unsafe_purpose_defaults_are_a_fail(self):
        for label, old, new in (("키 없이 동작 아님", "works_without_key: bool = True", "works_without_key: bool = False"),
                                ("자동 전환 기본", "fallback_providers: tuple = ()", "fallback_providers: tuple = ('x',)"),
                                ("호출 코드 있음 기본", "implemented: bool = False", "implemented: bool = True")):
            with self.subTest(label=label):
                row = self.row_after(4, extra={f"{APP}/service/connections.py": rs.CONNECTIONS_TEXT.replace(old, new)})
                self.assertEqual(row.status, FAIL, label)
                self.assertIn("기본값", row.basis)

    def test_unsafe_purpose_overrides_are_a_fail_naming_the_purpose(self):
        for label, old, new in (("키 필요", 'Purpose("beta", "비", implemented=False)', 'Purpose("beta", "비", works_without_key=False)'),
                                ("자동 전환", 'Purpose("gamma", "씨")', 'Purpose("gamma", "씨", fallback_providers=("a", "b"))'),
                                ("계산한 값", 'Purpose("gamma", "씨")', 'Purpose("gamma", "씨", works_without_key=compute())')):
            with self.subTest(label=label):
                row = self.row_after(4, extra={f"{APP}/service/connections.py": rs.CONNECTIONS_TEXT.replace(old, new)})
                self.assertEqual(row.status, FAIL, label)

    def test_a_purpose_with_call_code_is_counted_but_stays_a_pass_when_it_works_without_a_key(self):
        self.build(extra={f"{APP}/service/connections.py": rs.CONNECTIONS_TEXT.replace('Purpose("gamma", "씨")', 'Purpose("gamma", "씨", implemented=True)')})
        row = self.rows()[4]
        self.assertEqual(row.status, PASS)
        self.assertIn("호출 코드가 있는 용도 1개", row.basis)

    def test_a_purpose_table_that_cannot_be_read_is_a_fail(self):
        for text in ("def _purposes():\n    return ()\n", "class Purpose:\n    pass\n", "깨진 구문 (\n"):
            with self.subTest(text=text[:12]):
                row = self.row_after(4, extra={f"{APP}/service/connections.py": text})
                self.assertEqual(row.status, FAIL)
                self.assertIn("연결 용도 표", row.basis)                 # 다른 길(예상 못 한 오류·기본값 불일치)로 우연히 FAIL 이 된 것이 아니라 '표를 못 읽었다' 고 말해야 한다
                self.assertIn("읽지 못했다", row.basis)
                self.assertNotIn("예상하지 못한 오류", row.basis)

    def test_a_purpose_class_without_one_of_its_defaults_is_a_fail_naming_the_field(self):
        """기본값이 아예 없는 길(독립 검증 Q R1): 읽은 값이 None 이면 '안전한 값이 아님' 으로 FAIL 이어야 한다(`is not False` 가 `is True` 로 바뀌어도 초록이 되지 않게)."""
        for field, line in (("works_without_key", "    works_without_key: bool = True\n"), ("fallback_providers", "    fallback_providers: tuple = ()\n"),
                            ("implemented", "    implemented: bool = False\n")):
            with self.subTest(field=field):
                self.assertEqual(rs.CONNECTIONS_TEXT.count(line), 1)
                self.build(extra={f"{APP}/service/connections.py": rs.CONNECTIONS_TEXT.replace(line, "")})
                row = rc.check_4(rc.Repo(self.root))                                  # 4번 점검만 부른다(열두 항목을 모두 돌리지 않는다)
                self.assertEqual(row.status, FAIL)
                self.assertIn("기본값", row.basis)
                self.assertIn(field, row.basis)

    def test_a_purpose_default_that_is_a_calculation_is_a_fail_too(self):
        for old, new in (("implemented: bool = False", "implemented: bool = flag()"), ("works_without_key: bool = True", "works_without_key: bool = flag()"),
                         ("fallback_providers: tuple = ()", "fallback_providers: tuple = tuple()")):
            with self.subTest(new=new):
                self.build(extra={f"{APP}/service/connections.py": rs.CONNECTIONS_TEXT.replace(old, new)})
                row = rc.check_4(rc.Repo(self.root))
                self.assertEqual(row.status, FAIL)
                self.assertIn("기본값", row.basis)

    def test_the_real_capabilities_file_is_read_to_the_same_values_as_importing_it(self):
        from chanceblog_desktop import capabilities
        caps = rc.read_capabilities(rc.Repo(ROOT))
        for name in rc.CAPABILITY_NAMES:
            self.assertIs(caps[name], getattr(capabilities, name), name)


class Item5Test(RepoCase):
    def test_a_closed_gate_is_not_yet(self):
        self.build()
        row = self.rows()[5]
        self.assertEqual(row.status, NOT_YET)
        self.assertIn("EXTERNAL_WRITE=False", row.basis)

    def test_an_open_gate_is_manual(self):
        self.build(extra={f"{APP}/capabilities.py": rs.CAPABILITIES_TEXT.replace("EXTERNAL_WRITE = False", "EXTERNAL_WRITE = True")})
        self.assertEqual(self.status(5), MANUAL)

    def test_every_missing_pages_file_is_a_fail(self):
        for rel in rs.EXPECTED_PAGES_FILES:
            with self.subTest(rel=rel):
                row = self.row_after(5, drop=[f"{APP}/{rel}"])
                self.assertEqual(row.status, FAIL)
                self.assertIn(rel, row.basis)

    def test_an_unreadable_gate_is_a_fail(self):
        self.build(extra={f"{APP}/capabilities.py": "EXTERNAL_WRITE = 'no'\n"})
        self.assertEqual(self.status(5), FAIL)
        self.build(drop=[f"{APP}/capabilities.py"])
        self.assertEqual(self.status(5), FAIL)


class Item6Test(RepoCase):
    def test_no_blogger_code_and_a_closed_input_gate_is_not_yet(self):
        self.build()
        self.assertEqual(self.status(6), NOT_YET)

    def test_blogger_code_with_a_closed_input_gate_is_still_not_yet(self):
        self.build(extra={f"{APP}/publish/blogger_draft.py": "# Blogger(가짜)\n"})
        row = self.rows()[6]
        self.assertEqual(row.status, NOT_YET)
        self.assertIn("꺼져 있다", row.basis)

    def test_blogger_code_with_an_open_input_gate_is_manual(self):
        self.build(extra={f"{APP}/service/Blogger_flow.py": "# Blogger(가짜)\n", f"{APP}/capabilities.py": rs.CAPABILITIES_TEXT.replace("BLOGGER_OAUTH_INPUT = False", "BLOGGER_OAUTH_INPUT = True")})
        self.assertEqual(self.status(6), MANUAL)

    def test_an_open_input_gate_without_blogger_code_is_a_fail(self):
        self.build(extra={f"{APP}/capabilities.py": rs.CAPABILITIES_TEXT.replace("BLOGGER_OAUTH_INPUT = False", "BLOGGER_OAUTH_INPUT = True")})
        row = self.rows()[6]
        self.assertEqual(row.status, FAIL)
        self.assertIn("Blogger", row.basis)

    def test_only_the_adapter_folders_count_not_the_screen_folder_and_only_python_files(self):
        self.build(extra={f"{APP}/ui/blogger_screen.py": "# 화면\n", f"{APP}/service/blogger_notes.txt": "글\n"})
        self.assertEqual(self.status(6), NOT_YET)

    def test_an_unreadable_gate_is_a_fail(self):
        self.build(extra={f"{APP}/capabilities.py": "BLOGGER_OAUTH_INPUT = 0\n"})
        self.assertEqual(self.status(6), FAIL)


class Item7Test(RepoCase):
    def test_the_service_without_a_screen_that_calls_it_is_not_yet(self):
        self.build()
        self.assertEqual(self.status(7), NOT_YET)

    def test_a_screen_module_that_mentions_the_naver_flow_makes_it_manual(self):
        self.build(extra={f"{APP}/ui/adapters.py": "from ..service import naver_flow\n"})
        self.assertEqual(self.status(7), MANUAL)
        self.build(extra={f"{APP}/ui/qt/deep/screen.py": "from ....service import naver_flow\n\nnaver_flow.make()\n"})
        self.assertEqual(self.status(7), MANUAL)

    def test_a_mention_outside_the_screen_folder_or_in_a_non_python_file_does_not_count(self):
        self.build(extra={f"{APP}/service/other.py": "naver_flow\n", f"{APP}/ui/notes.md": "naver_flow\n"})
        self.assertEqual(self.status(7), NOT_YET)

    def seven(self, extra):
        self.build(extra=extra)
        return rc.check_7(rc.Repo(self.root))

    def test_every_form_of_import_counts_as_the_connection(self):
        for label, text in (("import 점 경로", "import chanceblog_desktop.service.naver_flow\n"), ("from 가져와 별칭", "from chanceblog_desktop.service import naver_flow as flow\n"),
                            ("그 모듈에서 이름 가져오기", "from ..service.naver_flow import build_package\n"), ("함수 안 늦은 import", "def open_screen():\n    from ..service import naver_flow\n    return naver_flow\n"),
                            ("한 줄에 여럿", "import os, chanceblog_desktop.service.naver_flow, sys\n")):
            with self.subTest(label=label):
                self.assertEqual(self.seven({f"{APP}/ui/posts_adapter.py": text}).status, MANUAL, label)

    def test_a_mention_that_is_not_an_import_is_not_a_connection(self):
        """독립 검증 Q R9: GUI 갈래의 독스트링 한 줄('naver_flow 는 가져오지도 않는다')이 7번을 거짓 수동으로 올렸다 — 독스트링·주석·글자·가져오지 않은 속성 사용·비슷한 이름·깨진 구문은 연결이 아니다."""
        for label, text in (("독스트링", '"""글 흐름 어댑터 — `naver_flow` 는 가져오지도 않는다."""\n'), ("주석", "# naver_flow 를 부른다\n"), ("글자 상수", 'NAME = "naver_flow"\n'),
                            ("가져오지 않은 속성 사용", "naver_flow.make()\n"), ("비슷한 이름 import", "from ..service import naver_flow_helper\nimport naver_flow_view\n"),
                            ("함수 독스트링", 'def f():\n    """naver_flow 로 이어진다."""\n    return 1\n'), ("깨진 구문 속 낱말", "naver_flow = (\n"),
                            ("이름 끝이 같은 다른 모듈", "from ..service import other\nfrom . import not_naver_flow\n")):
            with self.subTest(label=label):
                self.assertEqual(self.seven({f"{APP}/ui/posts_adapter.py": text}).status, NOT_YET, label)

    def test_every_missing_naver_file_is_a_fail(self):
        for rel in rs.EXPECTED_NAVER_FILES:
            with self.subTest(rel=rel):
                row = self.row_after(7, drop=[f"{APP}/{rel}"])
                self.assertEqual(row.status, FAIL)
                self.assertIn(rel, row.basis)


class Item8Test(RepoCase):
    def test_the_baseline_passes_and_counts_the_files_it_read(self):
        self.build()
        row = self.rows()[8]
        self.assertEqual(row.status, PASS)
        self.assertRegex(row.basis, r"파일 [0-9]+개")

    def test_the_word_in_any_spelling_in_the_screen_or_build_folders_is_a_fail(self):
        for spelling in ("tistory", "Tistory", "TISTORY", "티스토리", "tIsToRy", "my티스토리글"):
            for rel in (f"{APP}/ui/screen.py", f"{APP}/content/model.py", "packaging/notes.txt", ".github/workflows/package.yml", "ocr_addon/readme.md", f"{APP}/sub/noext"):
                with self.subTest(spelling=spelling, rel=rel):
                    row = self.row_after(8, extra={rel: f"앞 글\n{spelling}\n"})
                    self.assertEqual(row.status, FAIL)
                    self.assertIn(rel.rsplit("/", 1)[-1], row.basis)
                    self.assertIn(":2", row.basis)

    def test_the_word_in_docs_or_tests_is_fine(self):
        self.build(extra={"docs/NOTES.md": "티스토리 tistory\n", "tests/test_x.py": "tistory\n", "README.md": rs.filler("README") + "티스토리\n"})
        self.assertEqual(self.status(8), PASS)

    def test_a_binary_file_with_the_word_inside_is_found_too(self):
        self.build(extra={f"{APP}/ui/blob.bin": b"\x00\x01\xff tistory \x00"})
        self.assertEqual(self.status(8), FAIL)

    def test_the_decision_and_policy_rows_must_say_excluded_and_isolated(self):
        self.build()
        self.edit("docs/DECISIONS.md", "제외·격리", "제외")
        row = self.rows()[8]
        self.assertEqual(row.status, FAIL)
        self.assertIn("D-01", row.basis)
        self.build(extra={"docs/DECISIONS.md": rs.DECISIONS_TEXT})
        self.edit("docs/PLATFORM_POLICY.md", "**제외·격리**(D-01)", "**제외**(D-01)")
        row = self.rows()[8]
        self.assertEqual(row.status, FAIL)
        self.assertIn("플랫폼 정책", row.basis)

    def test_a_missing_decision_row_or_policy_row_is_a_fail(self):
        self.build(extra={"docs/DECISIONS.md": rs.DECISIONS_TEXT.replace("| D-01 |", "| D-02 |")})
        self.assertEqual(self.status(8), FAIL)
        self.build(extra={"docs/DECISIONS.md": rs.DECISIONS_TEXT, "docs/PLATFORM_POLICY.md": "# 정책\n\n" + rs.filler("정책")})
        self.assertEqual(self.status(8), FAIL)
        self.build(drop=["docs/PLATFORM_POLICY.md"], extra={})
        self.assertEqual(self.status(8), FAIL)

    def test_with_no_file_to_read_at_all_it_is_a_fail_not_a_vacuous_pass(self):
        with rs.temp_dir() as other:
            rs.write_files(other, {"docs/DECISIONS.md": rs.DECISIONS_TEXT, "docs/PLATFORM_POLICY.md": rs.POLICY_TEXT})
            row = rs.rows_of(other)[8]
        self.assertEqual(row.status, FAIL)
        self.assertIn("하나도 없다", row.basis)

    def test_an_unreadable_file_is_a_fail_not_a_skip(self):
        self.build()
        target = self.root.joinpath(*f"{APP}/ui/screen.py".split("/"))
        real = Path.read_bytes

        def fake(self_path):
            if self_path == target:
                raise PermissionError("가짜 잠김")
            return real(self_path)
        with mock.patch.object(Path, "read_bytes", fake):
            row = self.rows()[8]
        self.assertEqual(row.status, FAIL)
        self.assertIn("읽지 못한", row.basis)

    def test_cache_folders_are_not_read(self):
        self.build(extra={f"{APP}/__pycache__/x.pyc": "tistory"})
        self.assertEqual(self.status(8), PASS)


class Item9Test(RepoCase):
    def test_without_an_update_path_it_is_not_yet(self):
        self.build()
        row = self.rows()[9]
        self.assertEqual(row.status, NOT_YET)
        self.assertIn("업데이트", row.basis)

    def test_an_update_module_or_package_makes_it_manual(self):
        for rel in (f"{APP}/service/update_check.py", f"{APP}/update/__init__.py", f"{APP}/Updater.py"):
            with self.subTest(rel=rel):
                self.assertEqual(self.row_after(9, extra={rel: "def check():\n    return None\n"}).status, MANUAL)

    def test_a_name_that_only_contains_update_does_not_count(self):
        self.build(extra={f"{APP}/service/last_update_note.py": "def note():\n    return 1\n"})
        self.assertEqual(self.status(9), NOT_YET)

    def nine(self, extra):
        self.build(extra=extra)
        return rc.check_9(rc.Repo(self.root))

    def test_an_update_file_that_defines_a_function_in_any_shape_counts(self):
        for label, text in (("함수", "def check():\n    return None\n"), ("비동기 함수", "async def check():\n    return None\n"), ("클래스 안 메서드", "class Updater:\n    def run(self):\n        return 1\n"),
                            ("함수 안 함수", "def outer():\n    def inner():\n        return 1\n    return inner\n")):
            with self.subTest(label=label):
                self.assertEqual(self.nine({f"{APP}/service/update_flow.py": text}).status, MANUAL, label)

    def test_a_package_named_update_counts_through_the_files_inside_it_that_define_functions(self):
        self.assertEqual(self.nine({f"{APP}/update/__init__.py": "", f"{APP}/update/manifest.py": "def read():\n    return 1\n"}).status, MANUAL)
        self.assertEqual(self.nine({f"{APP}/update/__init__.py": "", f"{APP}/update/notes.txt": "def read(): pass\n"}).status, NOT_YET)
        self.assertEqual(self.nine({f"{APP}/update/__init__.py": "# 아직 비어 있다\n"}).status, NOT_YET)

    def test_an_empty_shell_with_the_right_name_stays_not_yet(self):
        """독립 검증 S 권고-3: 이름만 맞는 빈 껍데기(주석 한 줄·상수·메서드 없는 클래스·람다·깨진 구문·파이썬이 아닌 파일)는 수동으로 오르지 않는다 — 이름이 맞으면 오르고 이름이 다르면 머문다."""
        for label, rel, text in (("주석 한 줄", f"{APP}/update_banner.py", "# 업데이트 안내(나중에)\n"), ("상수만", f"{APP}/update_flow.py", "CHANNEL = 'stable'\nVERSION_URL = None\n"),
                                 ("메서드 없는 클래스", f"{APP}/update_flow.py", "class Updater:\n    channel = 'stable'\n"), ("람다만", f"{APP}/update_flow.py", "check = lambda: None\n"),
                                 ("깨진 구문", f"{APP}/update_flow.py", "def check(\n"), ("파이썬이 아닌 파일", f"{APP}/update_notes.md", "def check(): pass\n"),
                                 ("이름이 update 로 시작하지 않는 파일", f"{APP}/service/last_update.py", "def check():\n    return 1\n")):
            with self.subTest(label=label):
                row = self.nine({rel: text})
                self.assertEqual(row.status, NOT_YET, label)
                self.assertIn("함수가 든", row.basis)

    def test_missing_backup_code_is_a_fail(self):
        self.build(drop=[f"{APP}/{rs.EXPECTED_BACKUP_FILE}"])
        self.assertEqual(self.status(9), FAIL)


class Item10StaticTest(RepoCase):
    def test_without_a_folder_it_is_manual_and_says_how_to_give_one(self):
        self.build()
        row = self.rows()[10]
        self.assertEqual(row.status, MANUAL)
        self.assertIn("--scan-dir", row.basis)

    def test_every_missing_security_file_is_a_fail(self):
        for rel in rs.EXPECTED_SECURITY_FILES:
            with self.subTest(rel=rel):
                row = self.row_after(10, drop=[f"{APP}/{rel}"])
                self.assertEqual(row.status, FAIL)
                self.assertIn(rel, row.basis)

    def clean(self, label="폴더 1", files=3, size=1024):
        return rc.FolderScan(label, files_read=files, bytes_read=size)

    def test_clean_scans_pass_and_the_basis_has_the_counts(self):
        self.build()
        row = self.rows(scans=[self.clean(files=3), self.clean("폴더 2", files=4)])[10]
        self.assertEqual(row.status, PASS)
        self.assertIn("폴더 2개", row.basis)
        self.assertIn("훑은 파일 7개", row.basis)
        self.assertIn("발견 0건", row.basis)
        self.assertIn("읽지 못함 0개", row.basis)

    def test_the_pass_basis_names_what_was_looked_at_and_what_was_not(self):
        """독립 검증 S 권고-4: PASS 근거 글에 본 것(기존 여섯 모양·넘겨 준 폴더만)과 못 보는 것(다른 서비스의 키 모양)이 있다 — 표 제목은 '키·토큰이 남지 않음' 이라 그 범위를 숨기면 거짓 안심이 된다."""
        self.build()
        row = self.rows(scans=[self.clean()])[10]
        self.assertEqual(row.status, PASS)
        self.assertIn("본 것: 기존 여섯 모양(Google API 키·GitHub 토큰·Bearer·OAuth 토큰·AWS 키·PEM)만, 넘겨 준 폴더만", row.basis)
        self.assertIn("못 보는 것: 다른 서비스의 키 모양", row.basis)
        self.assertNotIn("\n", row.basis)
        scanner = rc._scan_module()
        self.assertEqual(len(scanner.KINDS), 6)                                                # '여섯 모양' 이 스캐너가 아는 모양 수와 같다 — 스캐너가 모양을 더하면 이 글도 고친다
        labels = " ".join(scanner.KIND_LABELS.values())
        for name in ("Google", "GitHub", "Bearer", "OAuth", "AWS", "PEM"):
            self.assertIn(name, labels)

    def test_a_fail_row_does_not_carry_the_scope_note(self):
        self.build()
        dirty = self.clean()
        dirty.findings.append(rc.Finding("a.txt", "GitHub 토큰", 3))
        self.assertNotIn("본 것:", self.rows(scans=[dirty])[10].basis)                          # 범위 글은 PASS 근거에만 — 틀린 줄은 무엇이 틀렸는지만 말한다

    def test_one_finding_in_any_folder_is_a_fail(self):
        self.build()
        dirty = self.clean("폴더 2")
        dirty.findings.append(rc.Finding("a.txt", "GitHub 토큰", 3))
        row = self.rows(scans=[self.clean(), dirty])[10]
        self.assertEqual(row.status, FAIL)
        self.assertIn("키·토큰 모양 1건", row.basis)

    def test_one_unread_file_is_a_fail_because_zero_cannot_be_claimed(self):
        self.build()
        shaky = self.clean()
        shaky.unread.append(rc.Unread("a.dll", "os_error"))
        row = self.rows(scans=[shaky])[10]
        self.assertEqual(row.status, FAIL)
        self.assertIn("읽지 못한 파일 1개", row.basis)
        self.assertIn("읽지 못함 1개", row.basis)

    def test_a_folder_that_could_not_be_opened_is_a_fail(self):
        self.build()
        closed = rc.FolderScan("폴더 1", openable=False)
        row = self.rows(scans=[closed])[10]
        self.assertEqual(row.status, FAIL)
        self.assertIn("열 수 없는 폴더 1개", row.basis)

    def test_zero_files_read_is_a_fail_not_a_vacuous_pass(self):
        self.build()
        row = self.rows(scans=[self.clean(files=0, size=0)])[10]
        self.assertEqual(row.status, FAIL)
        self.assertIn("0개", row.basis)

    def test_the_counts_in_the_basis_are_the_sums_of_all_folders(self):
        self.build()
        first, second = self.clean(files=2, size=3 * 1024 * 1024), self.clean("폴더 2", files=5, size=2 * 1024 * 1024)
        second.findings.extend([rc.Finding("a", "GitHub 토큰", 1), rc.Finding("b", "AWS 액세스 키", 2)])
        second.unread.extend([rc.Unread("c", "link")] * 3)
        row = self.rows(scans=[first, second])[10]
        self.assertIn("훑은 파일 7개", row.basis)
        self.assertIn("5.0MB", row.basis)
        self.assertIn("발견 2건", row.basis)
        self.assertIn("읽지 못함 3개", row.basis)


class Item11Test(RepoCase):
    def results(self, **changes):
        return [rs.SelfResult(key, changes.get(key, "ok"), "가짜") for key in rc.SELFTEST_KEYS if changes.get(key) != "gone"]

    def test_a_clean_source_run_without_installer_code_is_not_yet(self):
        self.build()
        row = self.rows()[11]
        self.assertEqual(row.status, NOT_YET)
        self.assertIn(f"통과 {len(rc.SELFTEST_KEYS) - len(rs.SOURCE_ONLY_SKIPS)}", row.basis)        # 열세 점검 중 소스 실행에서 건너뛰는 여섯을 뺀 일곱(개수는 목록에서 나온다)
        self.assertIn(f"건너뜀 {len(rs.SOURCE_ONLY_SKIPS)}", row.basis)
        self.assertIn("실패 0", row.basis)

    def test_installer_code_in_packaging_makes_it_manual(self):
        for rel in ("packaging/setup.iss", "packaging/Installer/make.iss"):
            with self.subTest(rel=rel):
                self.assertEqual(self.row_after(11, extra={rel: "; 설치 도구(가짜)\n"}).status, MANUAL)

    def eleven(self, extra):
        self.build(extra=extra)
        return rc.check_11(rc.Repo(self.root), rs.selftest_ok)

    def test_every_installer_definition_extension_counts_in_any_case(self):
        for rel in ("packaging/setup.iss", "packaging/Installer/ChanceBlog.ISS", "packaging/app.nsi", "packaging/win/app.wxs", "packaging/ChanceBlog.nuspec"):
            with self.subTest(rel=rel):
                self.assertEqual(self.eleven({rel: "; 설치 정의(가짜)\n"}).status, MANUAL, rel)

    def test_files_that_only_look_like_installer_code_by_name_do_not_count(self):
        """독립 검증 S 권고-3·Q R9: 이름에 install·velopack·vpk 가 들었거나 설치 메모일 뿐인 파일은 설치 정의 파일이 아니다 — 이름이 맞으면 수동으로 오르고 이름이 다르면 아직에 머문다."""
        for rel in ("packaging/build_installer.py", "packaging/Installer/make.py", "packaging/velopack_pack.py", "packaging/run_vpk.py", "packaging/install_notes.txt", "packaging/INSTALL.md", "packaging/vpk.json"):
            with self.subTest(rel=rel):
                row = self.eleven({rel: "# 설치 도구(가짜)\n"})
                self.assertEqual(row.status, NOT_YET, rel)
                self.assertIn("설치 정의 파일", row.basis)

    def test_the_installer_spike_files_are_not_installer_code(self):
        """설치 도구 시험(spike) 갈래가 병합돼도 시험용 파일이 11번을 수동으로 올리지 않는다(Q R9: packaging/spike/ChanceBlogSpike.iss) — 이름에 spike 가 든 경로는 어느 마디든 뺀다."""
        for rel in ("packaging/spike/ChanceBlogSpike.iss", "packaging/installer_spike/app.iss", "packaging/Spike.iss", "packaging/SPIKE/app.nsi", "packaging/tools/spike_app.wxs"):
            with self.subTest(rel=rel):
                self.assertEqual(self.eleven({rel: "; 시험용\n"}).status, NOT_YET, rel)
        row = self.eleven({"packaging/spike/ChanceBlogSpike.iss": "; 시험용\n", "packaging/ChanceBlog.iss": "; 진짜\n"})
        self.assertEqual(row.status, MANUAL)
        self.assertIn("설치 정의 파일(1곳)", row.basis)

    def test_installer_looking_files_outside_packaging_do_not_count(self):
        self.build(extra={"docs/INSTALL.md": rs.filler("설치"), ".github/workflows/installer.yml": "name: x\n", "scripts/install_notes.py": "# x\n"})
        self.assertEqual(self.status(11), NOT_YET)

    def test_a_failed_check_is_a_fail_naming_it(self):
        self.build()
        row = self.rows(selftest=lambda: self.results(vendor_core="fail"))[11]
        self.assertEqual(row.status, FAIL)
        self.assertIn("vendor_core", row.basis)

    def test_an_extra_failed_key_such_as_app_import_is_a_fail(self):
        self.build()
        results = self.results() + [rs.SelfResult("app_import", "fail", "가짜")]
        row = self.rows(selftest=lambda: results)[11]
        self.assertEqual(row.status, FAIL)
        self.assertIn("app_import", row.basis)

    def test_a_missing_check_in_the_results_is_a_fail(self):
        self.build()
        row = self.rows(selftest=lambda: self.results(capabilities="gone"))[11]
        self.assertEqual(row.status, FAIL)
        self.assertIn("capabilities", row.basis)
        self.assertIn("결과에 없는", row.basis)

    def test_an_empty_result_is_a_fail(self):
        self.build()
        self.assertEqual(self.status(11, selftest=lambda: []), FAIL)

    def test_a_raising_runner_is_a_fail_with_only_the_error_kind(self):
        self.build()

        def boom():
            raise ImportError("C:/Users/누군가/비밀 경로")
        row = self.rows(selftest=boom)[11]
        self.assertEqual(row.status, FAIL)
        self.assertIn("ImportError", row.basis)
        self.assertNotIn("누군가", row.basis)

    def test_skips_alone_are_not_a_fail(self):
        self.build()
        row = self.rows(selftest=lambda: self.results(**{key: "skip" for key in rc.SELFTEST_KEYS}))[11]
        self.assertEqual(row.status, NOT_YET)
        self.assertIn(f"건너뜀 {len(rc.SELFTEST_KEYS)}", row.basis)

    def test_the_selftest_is_not_run_by_other_rows_and_is_run_exactly_once(self):
        self.build()
        calls = []
        self.rows(selftest=lambda: calls.append(1) or rs.selftest_ok())
        self.assertEqual(len(calls), 1)

    def test_selftest_summary(self):
        failed, absent, passed, skipped = rc.summarize_selftest(self.results(utf8_mode="fail", licenses="skip", file_hashes="gone"))
        self.assertEqual((failed, absent, passed, skipped), (["utf8_mode"], ["file_hashes"], len(rc.SELFTEST_KEYS) - 3, 1))        # 실패 하나·건너뜀 하나·빠진 하나를 뺀 나머지가 통과다

    def test_the_twelve_names_are_the_ones_the_build_requires(self):
        """점검 목록은 묶음 시험 도우미의 목록과 **정확히** 같다(빼거나 더한 쪽이 있으면 빨갛다). 이름의 '열두' 는 처음 이름이다 — NET 갈래가 `tls` 를 더해 지금은 열세 점검이고, 시험 이름은 번호(id)가 바뀌지 않게 그대로 둔다."""
        import packaging_support as ps
        self.assertEqual(rc.SELFTEST_KEYS, ps.SELFTEST_KEYS)

    def test_the_default_runner_loads_the_entry_file_by_path_and_leaves_sys_path_and_bytecode_flag_alone(self):
        before_path, previous, prefix = list(sys.path), sys.dont_write_bytecode, sys.pycache_prefix
        sys.dont_write_bytecode, sys.pycache_prefix = False, None     # 보통 파이썬처럼 .pyc 를 소스 옆에 쓰는 상태에서도 쓰지 않는지 본다(다른 시험이 앱을 가져와 prefix 를 정해 두었어도)
        self.addCleanup(setattr, sys, "dont_write_bytecode", previous)
        self.addCleanup(setattr, sys, "pycache_prefix", prefix)
        with rs.temp_dir() as other:
            rs.write_files(other, {"packaging/gui_entry.py": "def run_selftest():\n    return ['가짜 결과']\n"})
            self.assertEqual(rc.run_repo_selftest(other), ["가짜 결과"])
            self.assertFalse((Path(other) / "packaging" / "__pycache__").exists())
        self.assertEqual(sys.path, before_path)
        self.assertFalse(sys.dont_write_bytecode)                    # 불러오는 동안만 껐다가 되돌린다


class Item12Test(RepoCase):
    def set_version(self, version, top=None, raw=None):
        self.build(extra={"VERSION": raw if raw is not None else version + "\n", "CHANGELOG.md": f"# 변경 이력\n\n## [{top or version}] — 2026-11-24\n\n- 줄\n\n## [0.0.0]\n"})

    def test_the_baseline_is_manual_because_the_release_page_cannot_be_checked_offline(self):
        self.build()
        row = self.rows()[12]
        self.assertEqual(row.status, MANUAL)
        self.assertIn("GitHub Release", row.basis)
        self.assertIn("0.1.0-preview.1", row.basis)

    def test_the_basis_claims_no_more_than_the_word_check_on_the_screen_version_code(self):
        """독립 검증 S 참고-7: 화면 버전 표시 코드는 VERSION 낱말이 있는지만 본다 — '화면이 읽는 번호(자동 확인)' 라고 말하지 않는다."""
        self.build()
        basis = self.rows()[12].basis
        self.assertIn("화면의 버전 표시 코드가 VERSION 낱말을 쓴다(낱말만 보는 확인)", basis)
        self.assertNotIn("화면이 읽는 번호", basis)
        self.assertNotIn("자동 확인", basis)

    def test_valid_semver_numbers_that_match_the_changelog_are_accepted(self):
        for version in ("1.0.0", "0.1.0-preview.1", "1.0.0-rc.1", "2.10.3-alpha", "1.0.0+build.5", "1.0.0-beta.2+exp.sha.5114f85", "10.20.30", "1.0.0-0A.is.legal"):
            with self.subTest(version=version):
                self.set_version(version)
                self.assertEqual(self.status(12), MANUAL)

    def test_numbers_that_are_not_semver_are_a_fail(self):
        for version in ("1.0", "v1.0.0", "01.0.0", "1.00.0", "1.0.0-", "1.0.0-01", "1.0.0+", "latest", "1.0.0 beta", "1.0.0.0", "1.0.0-rc..1", "일.영.영"):
            with self.subTest(version=version):
                self.set_version(version)
                row = self.rows()[12]
                self.assertEqual(row.status, FAIL, version)
                self.assertIn("SemVer", row.basis)

    def test_a_version_that_differs_from_the_top_changelog_section_is_a_fail_showing_both(self):
        self.set_version("1.0.0", top="0.9.0")
        row = self.rows()[12]
        self.assertEqual(row.status, FAIL)
        self.assertIn("1.0.0", row.basis)
        self.assertIn("0.9.0", row.basis)

    def test_only_the_top_section_counts(self):
        self.build(extra={"VERSION": "1.0.0\n", "CHANGELOG.md": "# 변경 이력\n\n## [0.9.0]\n\n## [1.0.0]\n"})
        self.assertEqual(self.status(12), FAIL)

    def test_an_unreleased_heading_on_top_is_a_fail(self):
        self.build(extra={"CHANGELOG.md": "# 변경 이력\n\n## [Unreleased]\n\n## [0.1.0-preview.1]\n"})
        self.assertEqual(self.status(12), FAIL)

    def test_a_changelog_without_a_numbered_section_or_without_a_file_is_a_fail(self):
        self.build(extra={"CHANGELOG.md": "# 변경 이력\n\n설명만 있다.\n"})
        self.assertEqual(self.status(12), FAIL)
        self.build(drop=["CHANGELOG.md"])
        self.assertEqual(self.status(12), FAIL)

    def test_a_missing_version_file_is_a_fail(self):
        self.build(drop=["VERSION"])
        row = self.rows()[12]
        self.assertEqual(row.status, FAIL)
        self.assertIn("VERSION", row.basis)

    def test_a_bom_and_surrounding_whitespace_in_the_version_file_are_tolerated(self):
        for raw in (chr(0xFEFF) + "0.1.0-preview.1\n", "  0.1.0-preview.1\r\n\r\n", "0.1.0-preview.1"):
            with self.subTest(raw=raw):
                self.build(extra={"VERSION": raw})
                self.assertEqual(self.status(12), MANUAL)

    def test_the_screen_version_reader_must_exist_and_mention_the_version_file(self):
        self.build(drop=[f"{APP}/ui/core/version.py"])
        self.assertEqual(self.status(12), FAIL)
        self.build(extra={f"{APP}/ui/core/version.py": '"""화면(가짜)."""\nNAME = "다른 곳"\n'})
        row = self.rows()[12]
        self.assertEqual(row.status, FAIL)
        self.assertIn("ui/core/version.py", row.basis)

    def test_a_very_long_bad_version_is_shown_shortened_and_plain(self):
        self.set_version("1.0.0", raw="가" * 500 + "\x07\n")
        row = self.rows()[12]
        self.assertEqual(row.status, FAIL)
        self.assertLess(len(row.basis), 200)
        self.assertNotIn("\x07", row.basis)


class CommandLineTest(RepoCase):
    def run_main(self, *args):
        out = io.StringIO()
        code = rc.main(list(args), out=out, selftest_runner=rs.selftest_ok)
        return code, out.getvalue()

    def test_the_text_report_has_the_table_the_summary_and_the_lists_for_the_operator(self):
        self.build()
        code, text = self.run_main("--root", str(self.root))
        self.assertEqual(code, 0)
        for number, title in rc.TITLES.items():
            self.assertIn(f"| {number} | {title} |", text)
        self.assertIn("요약: PASS 2 · FAIL 0 · 수동(운영자) 3 · 아직(미구현) 7", text)
        self.assertIn("운영자가 직접 해 봐야 하는 항목(수동): 1, 10, 12", text)
        self.assertIn("아직 만들어지지 않아 판정할 수 없는 항목(아직): 2, 3, 5, 6, 7, 9, 11", text)
        self.assertIn("틀린 항목(FAIL): 없음", text)
        self.assertIn("v1.0 을 선언하지 않습니다", text)
        self.assertIn("종료 코드: 0", text)

    def test_a_fail_makes_the_command_return_one_and_the_report_says_which_item(self):
        self.build(drop=["docs/MIGRATION.md"])
        code, text = self.run_main("--root", str(self.root))
        self.assertEqual(code, 1)
        self.assertIn("틀린 항목(FAIL): 1, 2", text)
        self.assertIn("요약: PASS 2 · FAIL 2 · 수동(운영자) 2 · 아직(미구현) 6", text)
        self.assertIn("종료 코드: 1", text)
        _, as_json = self.run_main("--root", str(self.root), "--json")
        self.assertEqual(json.loads(as_json)["summary"], {PASS: 2, FAIL: 2, MANUAL: 2, NOT_YET: 6})
        self.assertEqual(json.loads(as_json)["exit_code"], 1)

    def test_the_json_output_has_rows_summary_exit_code_and_scans(self):
        self.build()
        code, text = self.run_main("--root", str(self.root), "--json")
        data = json.loads(text)
        self.assertEqual(code, data["exit_code"])
        self.assertEqual(data["version"], "0.1.0-preview.1")
        self.assertEqual([row["number"] for row in data["rows"]], list(range(1, 13)))
        self.assertEqual({row["number"]: row["status"] for row in data["rows"]}, BASELINE)
        self.assertEqual(data["summary"], {PASS: 2, FAIL: 0, MANUAL: 3, NOT_YET: 7})
        self.assertEqual(data["scans"], [])
        self.assertIn("개인 PC", text)                                       # 한글이 이스케이프되지 않는다

    def test_scan_dir_can_be_given_more_than_once_and_feeds_item_ten(self):
        self.build()
        with rs.temp_dir() as first, rs.temp_dir() as second:
            rs.write_files(first, {"a.log": "문제 없는 글\n"})
            rs.write_files(second, {"b/c.txt": "또 문제 없는 글\n", ".hidden": "숨은 파일\n"})
            code, text = self.run_main("--root", str(self.root), "--scan-dir", first, "--scan-dir", second, "--json")
        data = json.loads(text)
        self.assertEqual(code, 0)
        self.assertEqual([scan["label"] for scan in data["scans"]], ["폴더 1", "폴더 2"])
        self.assertEqual([scan["files_read"] for scan in data["scans"]], [1, 2])
        self.assertEqual(data["rows"][9]["status"], PASS)

    def test_a_scan_dir_with_a_key_makes_the_whole_command_fail_and_the_report_never_prints_the_key(self):
        import scan_samples as S
        import secret_support
        self.build()
        secret = S.github()
        with rs.temp_dir() as folder:
            rs.write_files(folder, {"logs/app.log": f"앞 줄\n토큰 {secret}\n"})
            code, text = self.run_main("--root", str(self.root), "--scan-dir", folder)
            _, as_json = self.run_main("--root", str(self.root), "--scan-dir", folder, "--json")
            folder_text = str(folder)
        self.assertEqual(code, 1)
        self.assertIn("logs/app.log:2 GitHub 토큰", text)
        self.assertIn("틀린 항목(FAIL): 10", text)
        secret_support.assert_no_secret(self, secret, text, what="점검 표")
        secret_support.assert_no_secret(self, secret, as_json, what="JSON")
        self.assertNotIn(folder_text, text)                                    # 이 PC 의 폴더 경로(사용자 이름이 들어 있을 수 있다)를 내지 않는다
        self.assertNotIn(folder_text, as_json)

    def test_the_json_lists_every_finding_and_every_unread_file_with_path_kind_line_and_reason(self):
        import scan_samples as S
        self.build()
        with rs.temp_dir() as folder:
            rs.write_files(folder, {"logs/app.log": f"앞 줄\n{S.github()}\n", "bundle.gz": b"\x1f\x8b\x08\x00" + "압축 흉내".encode("utf-8"), "clean.txt": "깨끗한 글\n"})
            code, text = self.run_main("--root", str(self.root), "--scan-dir", folder, "--json")
        scan = json.loads(text)["scans"][0]
        self.assertEqual(code, 1)
        self.assertEqual(scan["findings"], [{"path": "logs/app.log", "kind": "GitHub 토큰", "line": 2}])
        self.assertEqual(scan["unread"], [{"path": "bundle.gz", "reason": "other_archive"}])
        self.assertEqual((scan["files_read"], scan["archives_opened"], scan["openable"]), (2, 0, True))
        self.assertEqual(scan["bytes_read"], len(f"앞 줄\n{S.github()}\n".encode("utf-8")) + len("깨끗한 글\n".encode("utf-8")))

    def test_a_missing_scan_dir_is_a_fail_for_item_ten(self):
        self.build()
        code, text = self.run_main("--root", str(self.root), "--scan-dir", str(self.root / "없는 폴더"))
        self.assertEqual(code, 1)
        self.assertIn("열 수 없는 폴더 1개", text)

    def test_a_scan_dir_that_is_a_file_is_a_fail(self):
        self.build()
        code, text = self.run_main("--root", str(self.root), "--scan-dir", str(self.root / "VERSION"))
        self.assertEqual(code, 1)

    def test_unknown_options_are_a_usage_error_with_exit_code_two(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as caught:
                rc.main(["--모르는-옵션"], selftest_runner=rs.selftest_ok)
        self.assertEqual(caught.exception.code, 2)

    def test_the_report_header_names_the_repository_version_and_never_the_absolute_path(self):
        self.build()
        _, text = self.run_main("--root", str(self.root))
        self.assertIn("저장소 버전 0.1.0-preview.1", text)
        self.assertNotIn(str(self.root), text)

    def test_the_report_header_shows_the_version_of_the_checked_repository_not_the_one_the_script_lives_in(self):
        self.build(extra={"VERSION": "9.9.9\n", "CHANGELOG.md": "# 변경 이력\n\n## [9.9.9] — 2026-11-25\n\n- 줄\n"})
        _, text = self.run_main("--root", str(self.root))
        self.assertIn("저장소 버전 9.9.9", text)
        _, as_json = self.run_main("--root", str(self.root), "--json")
        self.assertEqual(json.loads(as_json)["version"], "9.9.9")

    def test_the_default_root_is_the_repository_that_holds_the_script(self):
        self.assertEqual(rc.ROOT, ROOT)

    def test_main_prints_to_stdout_by_default(self):
        self.build()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = rc.main(["--root", str(self.root)], selftest_runner=rs.selftest_ok)
        self.assertEqual(code, 0)
        self.assertIn("| 12 |", buffer.getvalue())


class NoBytecodeTest(RepoCase):
    """공개 함수(`scan_folder`·`run_checks`·`main`)는 부르는 동안 .pyc 를 어디에도 쓰지 않고(앱의 `core` 가 `sys.pycache_prefix` 를 사용자 폴더로 돌려 놓으므로 늦게 가져오는 표준 모듈의 .pyc 가 거기 생길 수 있다)
    끝나면(예외·종료로 끝나도) 원래 값으로 되돌린다."""

    def setUp(self):
        super().setUp()
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = False                              # 보통 파이썬처럼 .pyc 를 쓰는 상태에서 시작한다
        self.addCleanup(setattr, sys, "dont_write_bytecode", previous)
        self.seen = []

    def spy(self, function):
        def wrapper(*args, **kwargs):
            self.seen.append(sys.dont_write_bytecode)
            return function(*args, **kwargs)
        return wrapper

    def test_scan_folder_runs_with_bytecode_writing_off_and_restores_it(self):
        with rs.temp_dir() as folder:
            rs.write_files(folder, {"a.txt": "글\n", "z.zip": b"PK\x03\x04bad"})
            with mock.patch.object(rc, "scan_stream", self.spy(rc.scan_stream)), mock.patch.object(rc, "_archive_kind", self.spy(rc._archive_kind)):
                rc.scan_folder(folder)
        self.assertTrue(self.seen and all(self.seen), self.seen)
        self.assertFalse(sys.dont_write_bytecode)

    def test_run_checks_runs_with_bytecode_writing_off_and_restores_it(self):
        self.build()
        rows = rc.run_checks(self.root, selftest_runner=self.spy(rs.selftest_ok))
        self.assertEqual(len(rows), 12)
        self.assertEqual(self.seen, [True])
        self.assertFalse(sys.dont_write_bytecode)

    def test_main_runs_with_bytecode_writing_off_and_restores_it_even_when_it_ends_by_exit(self):
        self.build()
        out = io.StringIO()
        real_parser = rc.build_parser

        def spied_parser():                                          # 명령줄을 읽는 일(argparse 가 늦게 가져오는 모듈 포함)도 .pyc 쓰기를 끈 안에서 한다 — scan_folder·run_checks 의 감싸개와 따로 main 의 감싸개를 본다
            parser = real_parser()
            parse = parser.parse_args

            def watching(argv=None):
                self.seen.append(("parse", sys.dont_write_bytecode))
                return parse(argv)
            parser.parse_args = watching
            return parser
        with rs.temp_dir() as folder:
            rs.write_files(folder, {"a.txt": "글\n"})
            with mock.patch.object(rc, "scan_stream", self.spy(rc.scan_stream)), mock.patch.object(rc, "build_parser", spied_parser):
                rc.main(["--root", str(self.root), "--scan-dir", folder], out=out, selftest_runner=self.spy(rs.selftest_ok))
        self.assertEqual(self.seen[0], ("parse", True), self.seen)
        self.assertTrue(len(self.seen) >= 3 and all(item is True for item in self.seen[1:]), self.seen)
        self.assertFalse(sys.dont_write_bytecode)
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                rc.main(["--모르는-옵션"])
        self.assertFalse(sys.dont_write_bytecode)

    def test_the_default_selftest_loader_also_keeps_it_off_while_running_the_selftest_function(self):
        with rs.temp_dir() as other:
            rs.write_files(other, {"packaging/gui_entry.py": "import sys\n\n\ndef run_selftest():\n    return [sys.dont_write_bytecode]\n"})
            self.assertEqual(rc.run_repo_selftest(other), [True])
        self.assertFalse(sys.dont_write_bytecode)


class EndToEndTest(unittest.TestCase):
    """진짜 스크립트를 **새 프로세스**로 돌린다 — 열세 점검(`--selftest`)은 그 프로세스 안에서 함수로 불린다. 시험 프로세스에는 앱의 명령줄 모듈이 이미 불려 있을 수 있고
    열세 점검의 '명령줄 모듈을 불러오지 않았다' 확인이 그것을 실패로 보므로, 진짜 자가 점검은 같은 프로세스에서 돌리지 않는다."""

    def run_script(self, *args, cwd=None):
        """스크립트를 새 프로세스로 돌린다. 사용자 데이터·캐시 폴더(`LOCALAPPDATA`·`HOME` 등)와 임시 폴더는 빈 폴더로 돌려 두고, 끝난 뒤에도 비어 있어야 한다(앱의 .pyc 캐시·자가 점검의 임시 폴더가 남지 않는다)."""
        env = {key: value for key, value in os.environ.items() if key.upper() not in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}       # .pyc 를 쓰는 보통 환경 — 스크립트가 스스로 안 쓰는지 본다
        with rs.temp_dir() as home, rs.temp_dir() as scratch:
            env.update(PYTHONUTF8="1", LOCALAPPDATA=home, APPDATA=home, HOME=home, USERPROFILE=home, XDG_CACHE_HOME=home, XDG_DATA_HOME=home, TEMP=scratch, TMP=scratch, TMPDIR=scratch)
            done = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8", env=env, cwd=cwd, timeout=240)
            self.assertEqual(os.listdir(home), [], "사용자 데이터·캐시 폴더에 아무것도 만들지 않는다(.pyc 캐시 포함)")
            self.assertEqual(os.listdir(scratch), [], "임시 폴더에 아무것도 남기지 않는다(자가 점검의 임시 폴더는 지운다)")
        return done

    def watched(self):
        return tuple(rs.tree_fingerprint(ROOT / name) for name in ("packaging", "scripts", "src", "docs"))

    @unittest.skipUnless(sys.platform == "win32", "윈도 실행 파일의 자가 점검 — 앱이 쓰는 환경에서만 진짜로 돌려 본다")
    @unittest.skipIf(importlib.util.find_spec("PySide6") is not None, "화면(Qt) 부품이 깔려 있으면 자가 점검이 오프스크린 창을 만든다 — 화면 시험 환경에서는 건너뛴다")
    def test_the_real_script_in_its_own_process_runs_the_real_selftest_exits_zero_and_leaves_no_trace(self):
        before = self.watched()
        with rs.temp_dir() as elsewhere:
            done = self.run_script("--json", cwd=elsewhere)
            leftovers = os.listdir(elsewhere)
        self.assertIn(done.returncode, (0, 1), done.stderr[-600:])                  # 끝까지 돌았다(예외로 끝나거나 사용법 오류 2 가 아니다) — 실제 저장소의 항목별 상태(FAIL 이 있는지)는 못박지 않는다(D-671 ④, 독립 검증 Q R7)
        data = json.loads(done.stdout)
        self.assertEqual(done.returncode, data["exit_code"])                        # 종료 코드는 표가 말하는 값과 같고
        self.assertEqual(done.returncode == 1, any(item["status"] == FAIL for item in data["rows"]))        # FAIL 이 있을 때만 1 이다(이름의 exits_zero 는 옛 이름 — 시험 id 를 지키려고 그대로 둔다)
        self.assertEqual([row["number"] for row in data["rows"]], list(range(1, 13)))
        row = data["rows"][10]
        self.assertIn(row["status"], (NOT_YET, MANUAL), row["basis"])
        self.assertIn("실패 0", row["basis"])
        self.assertEqual(leftovers, [], "실행한 폴더에 아무것도 만들지 않는다")
        self.assertEqual(self.watched(), before, "저장소의 packaging·scripts·src·docs 는 한 바이트도 바뀌지 않는다(.pyc 도 안 쓴다)")

    @unittest.skipIf(importlib.util.find_spec("PySide6") is not None, "화면(Qt) 부품이 깔려 있으면 자가 점검이 오프스크린 창을 만든다(Qt 공용 잠금 밖에서는 띄우지 않는다)")
    def test_a_candidate_folder_with_a_key_makes_the_real_process_exit_one_and_print_no_key(self):
        import scan_samples as S
        import secret_support
        secret = S.github()
        with rs.temp_dir() as folder:
            rs.write_files(folder, {"logs/app.log": f"앞\n{secret}\n", "ok.txt": "글\n"})
            done = self.run_script("--scan-dir", folder)
            folder_text = str(folder)
        self.assertEqual(done.returncode, 1, done.stderr[-600:])
        self.assertIn("logs/app.log:2 GitHub 토큰", done.stdout)
        self.assertIn("종료 코드: 1", done.stdout)
        secret_support.assert_no_secret(self, secret, done.stdout, what="표준 출력")
        secret_support.assert_no_secret(self, secret, done.stderr, what="표준 오류")
        self.assertNotIn(folder_text, done.stdout + done.stderr)

    def test_a_candidate_scan_with_json_prints_one_valid_json_document_alone_on_stdout_and_the_progress_note_on_stderr(self):
        """독립 검증 Q R6: 진행 안내가 표준 출력에 섞이면 `--json` 출력이 깨진다 — 새 프로세스로 `--scan-dir 폴더 --json` 을 돌려 표준 출력 전체가 JSON 하나인지, 안내는 표준 오류에 있는지 본다.
        점검할 저장소는 가짜 사본(`--root`)이라 진짜 자가 점검을 돌리지 않는다(그래서 화면 부품이 깔린 환경에서도 건너뛰지 않는다)."""
        import scan_samples as S
        import secret_support
        secret = S.github()
        entry = ("from collections import namedtuple\n\nResult = namedtuple('Result', 'key status text')\n\n\ndef run_selftest():\n"
                 "    return [Result(key, 'ok', 'fake') for key in " + repr(rc.SELFTEST_KEYS) + "]\n")
        with rs.temp_dir() as repo, rs.temp_dir() as folder:
            rs.build_repo(repo, extra={"packaging/gui_entry.py": entry})
            rs.write_files(folder, {"logs/app.log": f"앞\n{secret}\n", "ok.txt": "글\n"})
            done = self.run_script("--root", str(repo), "--scan-dir", str(folder), "--json")
            folder_text = str(folder)
        self.assertEqual(done.returncode, 1, done.stderr[-600:])
        data = json.loads(done.stdout)                                            # 표준 출력 전체가 JSON 하나다 — 안내 글이 섞이면 여기서 깨진다
        self.assertEqual(data["exit_code"], 1)
        self.assertEqual(data["rows"][9]["status"], FAIL)
        self.assertEqual(data["scans"][0]["findings"], [{"path": "logs/app.log", "kind": "GitHub 토큰", "line": 2}])
        self.assertIn("훑는 중", done.stderr)
        self.assertNotIn("훑는 중", done.stdout)
        self.assertTrue(done.stdout.lstrip().startswith("{") and done.stdout.rstrip().endswith("}"))
        secret_support.assert_no_secret(self, secret, done.stdout, what="표준 출력")
        secret_support.assert_no_secret(self, secret, done.stderr, what="표준 오류")
        self.assertNotIn(folder_text, done.stdout + done.stderr)

    def test_an_unknown_option_is_a_usage_error_exit_code_two_from_the_real_process(self):
        done = self.run_script("--모르는-옵션")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertIn("release_check.py", done.stderr)


class SkipReasonTest(unittest.TestCase):
    """건너뜀 이유에 화면 부품 이름(PySide6)을 쓰지 않는다 — 정식 CI 의 Qt 칸(`CI_REQUIRE_QT=1`, 아직 병합 전인 CI-QT 갈래의 `scripts/ci_shard.py`)은 건너뜀 이유에 그 낱말(대소문자 무시)이 든 시험을
    '화면 부품이 없어 건너뜀' 으로 세어 그 칸을 빨갛게 한다. 이 도구의 끝에서 끝 시험 둘은 그 부품이 **있을** 때 건너뛰므로(자가 점검이 오프스크린 창을 만든다) 이유에 그 낱말을 쓰면 Qt 칸이 영구히 빨개진다(독립 검증 Q 필수 M1)."""

    FILES = ("test_release_check.py", "test_release_check_scan.py", "release_check_support.py")
    WORD = "pyside6"                                  # 대소문자 무시로 찾는다 — CI-QT 갈래 가드의 QT_WORD 와 같다

    def skip_reasons(self, source):
        """소스 안의 건너뜀 호출(`skip`·`skipIf`·`skipUnless`·`skipTest`·`SkipTest`)의 이유 글들 — 이유가 글자 그대로가 아니면 `None`."""
        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
            if name not in ("skip", "skipIf", "skipUnless", "skipTest", "SkipTest"):
                continue
            index = 1 if name in ("skipIf", "skipUnless") else 0
            reason = node.args[index] if len(node.args) > index else next((kw.value for kw in node.keywords if kw.arg == "reason"), None)
            found.append(reason.value if isinstance(reason, ast.Constant) and isinstance(reason.value, str) else None)
        return found

    def test_no_skip_reason_in_this_tool_s_tests_names_the_screen_toolkit(self):
        total, bad = 0, []
        for name in self.FILES:
            for reason in self.skip_reasons((ROOT / "tests" / name).read_text(encoding="utf-8")):
                total += 1
                if reason is None or self.WORD in reason.casefold():
                    bad.append(name)
        self.assertGreaterEqual(total, 5, "건너뜀 호출을 실제로 훑는다(훑기가 깨져 아무것도 안 본 채 통과하지 않게)")
        self.assertEqual(bad, [])

    def test_the_reader_catches_a_reason_with_the_word_in_any_case_or_a_reason_that_is_not_plain_text(self):
        source = ("import unittest\n@unittest.skipIf(HAVE, 'PySide6 가 있으면')\nclass A(unittest.TestCase):\n"
                  "    @unittest.skip('pyside6 가 없다')\n    def test_a(self):\n        self.skipTest(REASON)\n"
                  "    def test_b(self):\n        self.skipTest('괜찮은 이유')\n    @unittest.skipUnless(HAVE, '화면 도구 PYSIDE6 설치 필요')\n    def test_c(self):\n        pass\n")
        reasons = self.skip_reasons(source)
        self.assertEqual(len(reasons), 5)
        self.assertEqual(sum(1 for item in reasons if item is None or self.WORD in item.casefold()), 4)           # 세 가지 대소문자와 글자 그대로가 아닌 이유


class ReadOnlyTest(RepoCase):
    FORBIDDEN_IMPORTS = {"subprocess", "socket", "ssl", ADDRESS[:4], "urllib", "ftplib", "smtplib", "asyncio", "requests", "multiprocessing", "ctypes", "webbrowser", "shutil", "tempfile", "sqlite3"}
    WRITE_CALLS = {"write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir", "rename", "symlink_to", "chmod", "truncate", "makedirs", "removedirs", "rmtree", "copyfile", "copytree", "mkstemp", "mkdtemp"}
    OS_WRITE_CALLS = {"remove", "replace", "rename", "unlink", "rmdir", "mkdir", "makedirs", "symlink", "link", "truncate", "chmod", "utime", "system", "popen", "startfile"}

    def source_tree(self):
        return ast.parse(SCRIPT.read_text(encoding="utf-8"))

    def test_the_script_imports_nothing_that_reaches_outside_or_writes_files(self):
        imported = set()
        for node in ast.walk(self.source_tree()):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(sorted(imported & self.FORBIDDEN_IMPORTS), [])

    def test_the_script_never_opens_a_file_for_writing_and_calls_no_write_helper(self):
        for node in ast.walk(self.source_tree()):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else "r"
                    self.assertEqual(mode, "rb", f"{node.lineno}행: 읽기 모드 rb 만 쓴다")
                if isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, self.WRITE_CALLS, f"{node.lineno}행")
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                        self.assertNotIn(node.func.attr, self.OS_WRITE_CALLS, f"{node.lineno}행: os.{node.func.attr}")

    def test_a_whole_run_never_starts_a_process_or_touches_the_network_and_leaves_every_file_unchanged(self):
        self.build()
        with rs.temp_dir() as folder:
            rs.write_files(folder, {"a.txt": "글\n", "b/c.log": "또 글\n", "z.zip": b"PK\x03\x04garbage"})
            before = (rs.tree_fingerprint(self.root), rs.tree_fingerprint(folder))
            blocked = AssertionError("점검이 하면 안 되는 일을 했다")
            with mock.patch("subprocess.Popen", side_effect=blocked), mock.patch("subprocess.run", side_effect=blocked), mock.patch("os.system", side_effect=blocked), \
                    mock.patch("socket.socket.connect", side_effect=blocked), mock.patch("socket.getaddrinfo", side_effect=blocked):
                buffer = io.StringIO()
                rc.main(["--root", str(self.root), "--scan-dir", folder], out=buffer, selftest_runner=rs.selftest_ok)
            after = (rs.tree_fingerprint(self.root), rs.tree_fingerprint(folder))
        self.assertEqual(before, after)

    def test_importing_the_script_does_not_change_the_bytecode_flag(self):
        before = sys.dont_write_bytecode
        spec = importlib.util.spec_from_file_location("release_check_again", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules["release_check_again"] = module                  # dataclass 가 자기 모듈을 이름으로 찾는다
        try:
            spec.loader.exec_module(module)
        finally:
            del sys.modules["release_check_again"]
        self.assertEqual(sys.dont_write_bytecode, before)

    def test_the_script_has_no_key_shaped_literal_and_builds_no_pattern_of_its_own_for_keys(self):
        text = SCRIPT.read_text(encoding="utf-8")
        for part in ("AI" + "za", "gh" + "p_", "AK" + "IA", "BEGIN " + "RSA", "ya" + "29.", "GOC" + "SPX", "e" + "yJ", "sk" + "-"):
            self.assertNotIn(part, text, "키 모양 조각을 소스에 쓰지 않는다 — 검사는 security/scan.py 만 부른다")

    def test_the_script_and_the_tests_have_no_tilde_no_address_word_and_no_doubled_brace(self):
        for path in (SCRIPT, ROOT / "tests" / "test_release_check.py", ROOT / "tests" / "test_release_check_scan.py", ROOT / "tests" / "release_check_support.py"):
            text = path.read_text(encoding="utf-8")
            for needle in (TILDE, ADDRESS, BRACES):
                self.assertNotIn(needle, text, f"{path.name}: {needle!r}")


class RealRepositoryTest(unittest.TestCase):
    def test_the_check_runs_to_the_end_on_this_repository_without_an_unexpected_error(self):
        rows = rc.run_checks(ROOT, selftest_runner=rs.selftest_ok)
        self.assertEqual([row.number for row in rows], list(range(1, 13)))
        for row in rows:
            self.assertIn(row.status, rc.STATUSES, row.number)
            self.assertNotIn("예상하지 못한 오류", row.basis, f"{row.number}번: {row.basis}")

    def test_the_safety_items_are_not_a_fail_here(self):
        rows = {row.number: row for row in rc.run_checks(ROOT, selftest_runner=rs.selftest_ok)}
        for number in (1, 4, 8, 12):
            self.assertNotEqual(rows[number].status, FAIL, f"{number}번: {rows[number].basis}")

    def test_two_runs_give_the_same_table(self):
        first = rc.run_checks(ROOT, selftest_runner=rs.selftest_ok)
        second = rc.run_checks(ROOT, selftest_runner=rs.selftest_ok)
        self.assertEqual(first, second)

    def test_the_twelve_titles_follow_the_completion_criteria_paragraph_in_the_decision_log(self):
        text = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        start = text.index("## 1.0.0 완료 기준")
        paragraph = next(line for line in text[start:].splitlines()[1:] if line.strip())
        items = [item.strip() for item in paragraph.rstrip(".").split(" · ")]
        self.assertEqual(len(items), 12)
        keywords = ("clone", "문서만으로", "AI 없이", "유료 호출", "GitHub Pages", "Blogger", "네이버 A/B", "티스토리", "백업", "키·토큰", "설치형", "Release")
        for number, (item, keyword) in enumerate(zip(items, keywords), 1):
            self.assertIn(keyword, item, f"{number}번 항목")
            self.assertIn(keyword, rc.TITLES[number], f"{number}번 제목")

    def test_the_line_counting_rule_is_the_same_as_the_scanner_modules(self):
        from chanceblog_desktop.security import scan
        self.assertEqual(rc._NEWLINE.pattern, scan._NEWLINE.pattern)


class DocumentationTest(unittest.TestCase):
    def text(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_decisions_d670_to_d674_exist_once_each_and_name_the_tool(self):
        log = self.text("docs/DECISIONS.md")
        for number in range(670, 676):                                    # 이름은 옛 것(D-670–D-674)대로 둔다 — 재작업이 D-675 를 더했고 시험 id 를 지키려고 이름은 그대로다
            self.assertEqual(len(re.findall(rf"^\| D-{number} \|", log, re.M)), 1, f"D-{number}")
        mine = [line for line in log.splitlines() if re.match(r"\| D-67[0-5] \|", line)]            # 이 갈래의 번호만 센다(다른 갈래가 같은 구간의 번호를 쓰거나 더 더해도 빨개지지 않게 — 독립 검증 Q P9)
        self.assertEqual(len(mine), 6)
        self.assertIn("scripts/release_check.py", mine[0])

    def test_the_overlap_and_safe_length_numbers_in_the_docs_are_the_ones_in_the_script(self):
        """D-672 ②·구조 문서 절·스크립트 머리말이 적은 겹침·'놓치지 않는 길이' 숫자가 상수와 같다 — 문서가 '놓치지 않는다' 고 거짓말하지 않게(독립 검증 S 필수-1)."""
        row = next(line for line in self.text("docs/DECISIONS.md").splitlines() if line.startswith("| D-672 |"))
        section = rc.find_section(self.text("docs/ARCHITECTURE.md"), "릴리스 후보 점검") or ""
        for label, text in (("D-672", row), ("구조 문서 절", section), ("스크립트 머리말", rc.__doc__)):
            self.assertIn(f"{rc.OVERLAP_CHARS:,} 글자", text, label)
            self.assertIn(f"{rc.SAFE_KEY_CHARS:,} 글자", text, label)

    def test_the_name_guess_sentence_says_which_way_a_wrong_name_leans_and_what_each_item_counts(self):
        """독립 검증 S 권고-3: 옛 문장 '틀리면 아직 쪽으로 기운다' 는 한쪽만 맞았다 — 이름이 맞으면 수동으로 오르고 이름이 다르면 아직에 머문다. 7·9·11번이 무엇만 세는지도 같은 글에 있다."""
        sentence = "이름이 맞으면 수동으로 오르고 이름이 다르면 아직에 머문다"
        row = next(line for line in self.text("docs/DECISIONS.md").splitlines() if line.startswith("| D-671 |"))
        row_674 = next(line for line in self.text("docs/DECISIONS.md").splitlines() if line.startswith("| D-674 |"))
        section = rc.find_section(self.text("docs/ARCHITECTURE.md"), "릴리스 후보 점검") or ""
        for label, text in (("스크립트 머리말", " ".join(rc.__doc__.split())), ("D-671", row), ("D-674", row_674), ("구조 문서 절", section)):
            self.assertIn(sentence, text, label)
            if label != "D-671":
                self.assertNotIn("기운다", text, label)
        self.assertEqual(row.count("기운다"), 1)                                            # D-671 은 옛 문장을 '옛 문장' 으로 한 번 인용할 뿐이다
        self.assertIn("옛 문장 '틀리면 아직 쪽으로 기운다'", row)
        for label, text in (("D-671", row), ("스크립트 머리말", " ".join(rc.__doc__.split()))):
            for needle in ("import", "함수(def)", ".iss", "spike"):
                self.assertIn(needle, text, f"{label}: {needle}")

    def test_the_things_that_read_as_read_but_are_not_seen_are_named_in_the_decision_the_architecture_doc_and_the_script(self):
        """독립 검증 S 권고-1: 훑기가 못 보는데 읽음으로 세는 것(표지 없는 UTF-16·UTF-32·대체 데이터 스트림·목록 밖 압축·PYZ 안쪽)을 이름으로 적고, 압축 표지를 읽지 못함으로 세지 않는 이유도 적는다."""
        row = next(line for line in self.text("docs/DECISIONS.md").splitlines() if line.startswith("| D-672 |"))
        section = rc.find_section(self.text("docs/ARCHITECTURE.md"), "릴리스 후보 점검") or ""
        for label, text in (("D-672", row), ("구조 문서 절", section), ("스크립트 머리말", " ".join(rc.__doc__.split()))):
            for name in ("표지 없는 UTF-16·UTF-32", "대체 데이터 스트림", "zstd·lz4", "OLE/MSI", "묶음의 PYZ", "읽지 못함으로 세지는 않는다", "10번이 영원히 PASS"):         # 목록 항목 자리의 글(이유 문장에 같은 낱말이 또 나와도 그 항목이 빠지면 빨개진다)
                self.assertIn(name, text, f"{label}: {name}")

    def test_item_four_text_says_it_is_a_static_reading_and_why_an_open_gate_still_passes(self):
        """독립 검증 S 권고-2(총괄 결정): 4번은 정적 읽기만 하고 실제 0 호출은 기본 설정 시험(네트워크 갈래)이 본다 — 결정과 구조 문서가 같은 말을 한다."""
        row = next(line for line in self.text("docs/DECISIONS.md").splitlines() if line.startswith("| D-671 |"))
        section = rc.find_section(self.text("docs/ARCHITECTURE.md"), "릴리스 후보 점검") or ""
        self.assertIn("정적 읽기(상수·용도 기본값)만이다", row)
        self.assertIn("실제 0 호출은 기본 설정 시험(네트워크 갈래)으로 확인한다", row)
        self.assertIn("'꺼짐일 때만 PASS' 로 하면 서로 양립하지 않는다", row)
        self.assertIn("실제 0 호출은 기본 설정 시험(네트워크 갈래)이 본다", section)

    def test_item_ten_text_says_what_a_pass_looked_at_and_what_it_did_not(self):
        """독립 검증 S 권고-4: D-671 ②10 과 구조 문서가 PASS 근거 글의 본 것·못 보는 것을 적는다."""
        row = next(line for line in self.text("docs/DECISIONS.md").splitlines() if line.startswith("| D-671 |"))
        section = rc.find_section(self.text("docs/ARCHITECTURE.md"), "릴리스 후보 점검") or ""
        for label, text in (("D-671", row), ("구조 문서 절", section)):
            self.assertIn("본 것: 기존 여섯 모양·넘겨 준 폴더만", text, label)
            self.assertIn("못 보는 것: 다른 서비스의 키 모양", text, label)

    def test_decision_d675_names_what_was_fixed_what_was_left_on_purpose_and_what_to_do_when_merging(self):
        """재작업 결정 행: 고친 것·일부러 고치지 않은 것(총괄 결정과 이유)·합칠 때 알아 둘 것이 한 곳에 있다. 큰 결정 표 안(D-674 바로 뒤)에 있어야 한다."""
        lines = self.text("docs/DECISIONS.md").splitlines()
        index = next(number for number, line in enumerate(lines) if line.startswith("| D-675 |"))
        self.assertTrue(lines[index - 1].startswith("| D-674 |"))
        self.assertTrue(lines[index + 1] == "" or lines[index + 1].startswith("| D-"), lines[index + 1][:60])        # 같은 표 안이다 — 다음 줄이 빈 줄(표 끝)이거나 다른 갈래가 뒤에 더한 결정 행(새 표나 문단이 아니다)
        row = lines[index]
        for needle in ("고친 것", "일부러 하지 않은 것", "총괄 결정", "읽지 못함으로 세지 않는다", "꼬리를 늘려 붙이는", "다른 갈래와 합칠 때", "SELFTEST_KEYS", "결정 색인"):
            self.assertIn(needle, row, needle)

    def test_the_other_named_limits_and_the_usage_notes_are_written_down(self):
        """독립 검증 S 참고: 8번·4번·12번·훑기 비용의 한계를 이름으로, --root·임시 폴더·출력의 파일 이름에 관한 쓸 때 알아 둘 것을 적었다."""
        log = self.text("docs/DECISIONS.md")
        row_674 = next(line for line in log.splitlines() if line.startswith("| D-674 |"))
        section = rc.find_section(self.text("docs/ARCHITECTURE.md"), "릴리스 후보 점검") or ""
        for label, text in (("D-674", row_674), ("구조 문서 절", section)):
            for needle in ("8번은 파일 내용의 낱말만 본다", "별칭으로 부르거나", "`VERSION` 낱말이 있는지만 본다", "발견 수 상한이 없고"):
                self.assertIn(needle, text, f"{label}: {needle}")
        for needle in ("믿는 사본에만 쓴다", "임시 폴더에 빈 폴더를 잠깐", "그대로 붙이지 않는다"):
            self.assertIn(needle, section, needle)
        self.assertIn("그대로 붙이지 않는다", " ".join(rc.__doc__.split()))

    def test_the_changelog_and_the_architecture_doc_describe_the_tool(self):
        self.assertIn("scripts/release_check.py", self.text("CHANGELOG.md"))
        arch = self.text("docs/ARCHITECTURE.md")
        section = rc.find_section(arch, "릴리스 후보 점검")
        self.assertIsNotNone(section)
        for needle in ("scripts/release_check.py", "--scan-dir", "PASS", "FAIL", "수동(운영자)", "아직(미구현)", "security/scan.py", "D-670"):
            self.assertIn(needle, section, needle)

    def test_the_new_docs_text_has_no_tilde_address_word_or_doubled_brace(self):
        log = self.text("docs/DECISIONS.md")
        mine = "\n".join(line for line in log.splitlines() if re.match(r"\| D-67[0-5] \|", line))
        section = rc.find_section(self.text("docs/ARCHITECTURE.md"), "릴리스 후보 점검") or ""
        changelog_line = next((line for line in self.text("CHANGELOG.md").splitlines() if "release_check" in line), "")
        for label, text in (("결정", mine), ("구조 문서 절", section), ("변경 이력 줄", changelog_line)):
            for needle in (TILDE, ADDRESS, BRACES):
                self.assertNotIn(needle, text, f"{label}: {needle!r}")


if __name__ == "__main__":
    unittest.main()
