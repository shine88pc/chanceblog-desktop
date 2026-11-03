"""명령줄 `candidates` 진짜 프로세스 시험 — `python -m chanceblog_desktop` 을 실제로 띄워 종료 코드·표준 출력·표준 오류·`--json` 을 본다.

지키는 것:
  1) 진입점에서 한글 출력·종료 코드(0 정상·1 처리된 오류·2 사용법 오류)가 맞고 스택 추적이 나오지 않는다. 보기만 하는 명령은 데이터 폴더도 보관함 파일도 만들지 않는다.
  2) CSV(UTF-8·BOM·cp949)를 진짜 파일로 가져오고 다시 가져와도 겹치지 않는다. 거절한 줄이 있으면 종료 코드 1 이지만 나머지는 저장되어 있다.
  3) **동시에 두 프로세스가 같은 후보를 바꿀 때** 서로의 변경을 잃지 않는다 — 다른 블로그를 고르면 둘 다 되고, 표에 없는 이동(고르기와 제외)이 부딪치면 정확히 하나만 되며, 글 연결(불러온 판 `expected_revision`)은 부딪쳐도 다시 읽어 저장해 모두 남는다.
  4) 후보의 글에 키 모양 문자열이 있어도 진짜 출력에는 가려져 나간다.
"""
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

LONG_ID = re.compile(r"\b[0-9a-f]{32}\b")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.data = self.tmp / "데이터"
        self.env = {**ss.env_without_repo(), "PYTHONPATH": str(ss.ROOT / "src"), "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}

    def command(self, *argv):
        return [sys.executable, "-X", "utf8", "-m", "chanceblog_desktop", "--data-dir", str(self.data), *argv]

    def run_module(self, *argv):
        done = subprocess.run(self.command(*argv), capture_output=True, env=self.env, cwd=self.tmp, timeout=180)
        out, err = done.stdout.decode("utf-8"), done.stderr.decode("utf-8")
        self.assertNotIn("Traceback", err)
        return done.returncode, out, err

    def ok(self, *argv):
        code, out, err = self.run_module(*argv)
        self.assertEqual((code, err), (0, ""), (argv, out, err))
        return out

    def data_of(self, *argv):
        payload = json.loads(self.ok("--json", *argv))
        self.assertTrue(payload["ok"])
        return payload["data"]

    def add(self, topic, keyword=None, blog="naver_a", *extra):
        return self.ok("candidates", "add", "--topic", topic, "--keyword", keyword or topic + " 키워드", "--blog", blog, *extra)

    def start(self, *argv):
        return subprocess.Popen(self.command(*argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=self.tmp)

    def finish(self, process):
        out, err = process.communicate(timeout=180)
        return process.returncode, out.decode("utf-8"), err.decode("utf-8")

    def candidate(self, ordinal=1):
        return self.data_of("candidates", "show", str(ordinal))["candidate"]


class SessionTest(Base):
    def test_a_whole_session_with_real_exit_codes_and_no_trace(self):
        code, out, err = self.run_module("candidates", "list")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("아직 후보가 없습니다(쓰는 명령을 처음 실행하면 보관함이 올라갑니다)", out)
        code, out, err = self.run_module("candidates", "show", "1")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: CANDIDATE_NOT_FOUND", err)
        self.assertFalse(self.data.exists(), "보기만 하는 명령은 데이터 폴더를 만들지 않는다")

        out = self.add("겨울 보일러 점검 순서", "보일러 점검", "naver_a,pages", "--search-demand", "12000", "--data-date", "2026-11-01")
        self.assertIn("후보를 추가했습니다.", out)
        self.assertTrue((self.data / "chanceblog.db").exists())
        listing = self.ok("candidates", "list")
        self.assertIn("  [1] 새 후보 — 겨울 보일러 점검 순서 · 핵심 키워드: 보일러 점검 · 대상: 네이버 A, GitHub Pages", listing)
        self.assertIsNone(LONG_ID.search(listing))
        data = self.data_of("candidates", "list")
        self.assertRegex(data["candidates"][0]["candidate_id"], r"^[0-9a-f]{32}$")
        number = data["candidates"][0]["candidate_id"][:8]
        self.assertIn(f" · 번호 {number}", listing, "목록은 번호 앞 8자를 늘 보인다")
        self.assertIn(f"네이버 A 용으로 골랐습니다: [1] 겨울 보일러 점검 순서 (번호 {number}) — 새 후보 → 선택됨", self.ok("candidates", "select", "1", "--blog", "naver_a"))
        code, out, err = self.run_module("candidates", "select", "1", "--blog", "tistory")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("사용법 오류", err)
        code, out, err = self.run_module("candidates", "delete", "1")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: CONFIRMATION_REQUIRED", err)
        self.assertNotIn("CANDIDATE_CONFIRM_REQUIRED", err)
        self.assertEqual(self.candidate()["status"], "SELECTED", "확인 없이는 지워지지 않았다")
        code, out, err = self.run_module("candidates", "delete", "1", "--yes")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: CANDIDATE_DELETE_NEEDS_NUMBER", err)
        self.assertEqual(self.candidate()["status"], "SELECTED", "순번으로는 지워지지 않았다")
        self.assertIn(f"후보를 지웠습니다: [1] 겨울 보일러 점검 순서 (번호 {number})", self.ok("candidates", "delete", number, "--yes"))
        self.assertIn("아직 후보가 없습니다. ", self.ok("candidates", "list"))

    def test_the_common_options_work_after_the_subcommand_too_and_the_environment_variable_picks_the_data_folder(self):
        self.add("가")
        code, out, err = self.run_module("candidates", "list", "--json", "--verbose")
        self.assertEqual((code, err, json.loads(out)["command"]), (0, "", "candidates list"))
        elsewhere = self.tmp / "다른 폴더"
        done = subprocess.run([sys.executable, "-X", "utf8", "-m", "chanceblog_desktop", "candidates", "add", "--topic", "환경 변수로 고른 폴더", "--keyword", "환경 키워드", "--blog", "naver_a"],
                              capture_output=True, env={**self.env, "CHANCEBLOG_DESKTOP_DATA": str(elsewhere)}, cwd=self.tmp, timeout=180)
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertTrue((elsewhere / "chanceblog.db").exists())
        code, out, err = self.run_module("candidates", "list", "--data-dir", str(elsewhere))
        self.assertIn("환경 변수로 고른 폴더", out)
        self.assertNotIn("환경 변수로 고른 폴더", self.ok("candidates", "list"), "--data-dir 이 환경 변수보다 먼저이고 두 폴더는 서로 다르다")

    def test_help_for_real_is_korean_and_a_missing_subcommand_exits_two(self):
        code, out, err = self.run_module("candidates", "--help")
        self.assertEqual((code, err), (0, ""))
        for needle in ("사용법:", "list", "import-csv", "select", "delete", "link"):
            self.assertIn(needle, out)
        for word in ("usage:", "positional arguments", "options:"):
            self.assertNotIn(word, out)
        code, out, err = self.run_module("candidates")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("빠진 항목이 있습니다: 하위명령", err)

    def test_the_json_error_shape_for_real(self):
        code, out, err = self.run_module("--json", "candidates", "select", "9", "--blog", "naver_a")
        payload = json.loads(out)
        self.assertEqual((code, err, payload["ok"], payload["command"], payload["error"]["code"]), (1, "", False, "candidates select", "CANDIDATE_NOT_FOUND"))
        self.assertEqual(sorted(payload["error"]), ["action", "code", "detail", "message", "retry"])

    def test_a_key_shaped_text_is_masked_in_the_real_output(self):
        self.add("키 모양 " + ss.KEY + " 이 든 주제", "키워드 하나")
        for argv in (("candidates", "list"), ("candidates", "show", "1"), ("--json", "candidates", "list"), ("--verbose", "candidates", "list")):
            out = self.ok(*argv)
            self.assertNotIn(ss.KEY, out)
            self.assertIn("[가림", out)
        code, out, err = self.run_module("candidates", "show", ss.KEY)
        self.assertEqual(code, 1)
        self.assertNotIn(ss.KEY, err)


class ImportProcessTest(Base):
    HEAD = "주제,핵심 키워드,대상 블로그,월간 검색 수요,데이터 조회일"

    def test_utf8_bom_and_cp949_files_import_for_real_and_a_second_run_changes_nothing(self):
        rows = "\n".join(f"주제 {n},키워드 {n},네이버 A,\"{n},000\",2026-11-01" for n in range(1, 6))
        text = self.HEAD + "\n" + rows + "\n"
        files = {"utf8.csv": text.encode("utf-8"), "bom.csv": b"\xef\xbb\xbf" + text.encode("utf-8"), "cp949.csv": text.encode("cp949")}
        for name, data in files.items():
            path = self.tmp / name
            path.write_bytes(data)
            first = self.ok("candidates", "import-csv", str(path))
            if name == "utf8.csv":
                self.assertIn("5개 추가·0개 건너뜀·0개 거절", first)
                self.assertIn("  추가한 후보(순번): 1~5", first)
            else:
                self.assertIn("0개 추가·5개 건너뜀·0개 거절", first, f"{name}: 같은 내용이라 모두 건너뛴다")
        data = self.data_of("candidates", "list")
        self.assertEqual([item["topic"] for item in data["candidates"]], [f"주제 {n}" for n in range(1, 6)], "파일의 줄 순서대로 순번이 매겨진다")
        self.assertEqual([item["search_demand"] for item in data["candidates"]], [1000, 2000, 3000, 4000, 5000])

    def test_a_rejected_line_exits_one_while_the_rest_is_saved_and_a_clean_rerun_exits_zero(self):
        path = self.tmp / "섞인.csv"
        path.write_text(self.HEAD + "\n좋은 주제,좋은 키워드,naver_a,10,2026-11-01\n상위노출 보장 글,다른 키워드,naver_a,,\n", encoding="utf-8")
        code, out, err = self.run_module("candidates", "import-csv", str(path))
        self.assertEqual((code, err), (1, ""))
        self.assertIn("1개 추가·0개 건너뜀·1개 거절", out)
        self.assertIn("거절: 줄 3 — 추천 포스팅 주제: ‘상위노출 보장’", out)
        self.assertEqual([item["topic"] for item in self.data_of("candidates", "list")["candidates"]], ["좋은 주제"])
        path.write_text(self.HEAD + "\n좋은 주제,좋은 키워드,naver_a,10,2026-11-01\n", encoding="utf-8")
        code, out, err = self.run_module("candidates", "import-csv", str(path))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("0개 추가·1개 건너뜀·0개 거절", out)
        code, out, err = self.run_module("--json", "candidates", "import-csv", str(path))
        self.assertEqual((code, json.loads(out)["ok"], json.loads(out)["data"]["summary"]), (0, True, "0개 추가·1개 건너뜀·0개 거절"))

    def test_a_file_that_cannot_be_used_exits_one_and_creates_nothing(self):
        path = self.tmp / "빈.csv"
        path.write_bytes(b"")
        code, out, err = self.run_module("candidates", "import-csv", str(path))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: CANDIDATE_CSV_INVALID", err)
        code, out, err = self.run_module("candidates", "import-csv", str(self.tmp / "없는.csv"))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("CANDIDATE_CSV_INVALID", err)
        self.assertFalse(self.data.exists())


class ConcurrentProcessTest(Base):
    def test_two_processes_choosing_different_blogs_for_the_same_candidate_both_succeed_and_both_are_recorded(self):
        for round_number in range(3):
            with self.subTest(round=round_number):
                self.add(f"주제 {round_number}", f"키워드 {round_number}", "naver_a,naver_b")
                ordinal = str(round_number + 1)
                first, second = self.start("candidates", "select", ordinal, "--blog", "naver_a"), self.start("candidates", "select", ordinal, "--blog", "naver_b")
                results = [self.finish(first), self.finish(second)]
                self.assertEqual([(code, err) for code, _out, err in results], [(0, ""), (0, "")], results)
                candidate = self.candidate(round_number + 1)
                self.assertEqual((candidate["status"], sorted(candidate["selections"]), candidate["revision"]), ("SELECTED", ["naver_a", "naver_b"], 3))

    def test_a_choice_and_a_rejection_of_the_same_candidate_at_once_let_exactly_one_win(self):
        wins = set()
        for round_number in range(4):
            with self.subTest(round=round_number):
                self.add(f"충돌 {round_number}", f"충돌 키워드 {round_number}")
                ordinal = str(round_number + 1)
                chooser, rejecter = self.start("candidates", "select", ordinal, "--blog", "naver_a"), self.start("candidates", "reject", ordinal)
                (chose, _o1, chose_err), (rejected, _o2, rejected_err) = self.finish(chooser), self.finish(rejecter)
                self.assertEqual(sorted((chose, rejected)), [0, 1], "정확히 하나만 되고 하나는 표에 없는 이동이라 처리된 오류다")
                loser_err = chose_err if chose == 1 else rejected_err
                self.assertIn("코드: CANDIDATE_TRANSITION_INVALID", loser_err)
                self.assertNotIn("Traceback", loser_err)
                candidate = self.candidate(round_number + 1)
                self.assertEqual(candidate["status"], "SELECTED" if chose == 0 else "REJECTED")
                self.assertEqual(candidate["revision"], 2, "이긴 쪽의 변경 하나만 저장됐다")
                wins.add("선택" if chose == 0 else "제외")
        self.assertTrue(wins <= {"선택", "제외"})

    def test_linking_two_posts_and_choosing_a_blog_at_once_lose_no_change(self):
        ids = []
        for title in ("연결할 글 하나", "연결할 글 둘"):
            out = self.ok("--json", "new", "--title", title, "--text", ss.ko_text())
            ids.append(json.loads(out)["data"]["project"]["project_id"])
        for round_number in range(2):
            with self.subTest(round=round_number):
                self.add(f"연결 {round_number}", f"연결 키워드 {round_number}")
                ordinal = str(round_number + 1)
                processes = [self.start("candidates", "link", ordinal, ids[0]), self.start("candidates", "link", ordinal, ids[1]), self.start("candidates", "select", ordinal, "--blog", "naver_a")]
                results = [self.finish(process) for process in processes]
                self.assertEqual([(code, err) for code, _out, err in results], [(0, "")] * 3, results)
                candidate = self.candidate(round_number + 1)
                self.assertEqual(candidate["status"], "SELECTED", "고른 것도 남았다")
                self.assertIn(candidate["project_id"], ids, "마지막으로 저장한 글 연결이 남았다")
                self.assertEqual(candidate["revision"], 4, "판 번호가 처음 1 에서 변경 셋만큼(3) 올라 4 다 — 어느 것도 잃지 않았다")

    def write_rows(self, count, name="같은.csv"):
        path = self.tmp / name
        path.write_text("주제,핵심 키워드,대상 블로그\n" + "\n".join(f"주제 {n:03d},키워드 {n:03d},naver_a" for n in range(count)) + "\n", encoding="utf-8")
        return path

    def stored_topics(self):
        return [item["topic"] for item in self.data_of("candidates", "list")["candidates"]]

    def test_two_and_three_processes_importing_the_same_file_at_once_end_with_every_line_exactly_once(self):
        """같은 파일을 동시에 가져와도 '이미 있나 확인 → 저장' 이 보관함의 한 쓰기 트랜잭션이라 겹치지 않는다(전에는 2개 동시 100줄이 6/6회 200개였다)."""
        for processes, lines in ((2, 100), (3, 60), (3, 60)):
            with self.subTest(processes=processes, lines=lines):
                self.setUp()
                path = self.write_rows(lines)
                started = [self.start("candidates", "import-csv", str(path), "--json") for _ in range(processes)]
                results = [self.finish(process) for process in started]
                self.assertEqual([(code, err) for code, _out, err in results], [(0, "")] * processes, results)
                added = [json.loads(out)["data"]["summary"] for _code, out, _err in results]
                self.assertEqual(sum(int(text.split("개 추가")[0]) for text in added), lines, f"추가한 줄의 합이 줄 수와 같다: {added}")
                topics = self.stored_topics()
                self.assertEqual(sorted(topics), [f"주제 {n:03d}" for n in range(lines)], "모든 줄이 정확히 한 번씩")
                self.assertEqual(self.ok("candidates", "import-csv", str(path)).splitlines()[1], f"0개 추가·{lines}개 건너뜀·0개 거절")
                code, out, err = self.run_module("--json", "doctor")
                checks = {item["name"]: item for item in json.loads(out)["data"]["checks"]}
                self.assertEqual(checks["글 저장소"]["status"], "ok", checks["글 저장소"])

    def test_two_processes_adding_the_same_candidate_at_once_keep_one(self):
        started = [self.start("candidates", "add", "--topic", "같은 주제 입니다", "--keyword", "같은 키워드", "--blog", "naver_a", "--json") for _ in range(3)]
        results = [self.finish(process) for process in started]
        self.assertEqual([(code, err) for code, _out, err in results], [(0, "")] * 3, results)
        self.assertEqual(sorted(json.loads(out)["data"]["added"] for _code, out, _err in results), [False, False, True], "한 곳만 더했고 나머지는 이미 있다고 알렸다")
        self.assertEqual(self.stored_topics(), ["같은 주제 입니다"])


class DeleteAndSpecialFilesProcessTest(Base):
    def six(self):
        names = ("가", "나", "다", "라", "마", "바")
        for name in names:
            self.add(f"{name} 주제", f"{name} 키워드")
        return [item["candidate_id"] for item in self.data_of("candidates", "list")["candidates"]]

    def test_the_same_delete_command_with_an_ordinal_and_yes_deletes_nothing_however_often_it_is_run_for_real(self):
        """전에는 `delete 3 --yes` 를 세 번 치면 셋째·넷째·다섯째 후보가 차례로 지워졌다(지울 때마다 순번이 당겨져서)."""
        ids = self.six()
        for repeat in range(3):
            code, out, err = self.run_module("candidates", "delete", "3", "--yes")
            self.assertEqual((code, out), (1, ""), repeat)
            self.assertIn("코드: CANDIDATE_DELETE_NEEDS_NUMBER", err)
            self.assertIn(f"candidates delete {ids[2][:8]} --yes", err)
        self.assertEqual([item["candidate_id"] for item in self.data_of("candidates", "list")["candidates"]], ids, "아무것도 지워지지 않았다")
        code, out, err = self.run_module("--json", "candidates", "delete", "3", "--yes")
        self.assertEqual((code, json.loads(out)["error"]["code"]), (1, "CANDIDATE_DELETE_NEEDS_NUMBER"))

    def test_the_number_deletes_one_candidate_once_and_again_it_is_not_found(self):
        ids = self.six()
        number = ids[2][:8]
        self.assertIn(f"후보를 지웠습니다: [3] 다 주제 (번호 {number})", self.ok("candidates", "delete", number, "--yes"))
        for repeat in range(2):
            code, out, err = self.run_module("candidates", "delete", number, "--yes")
            self.assertEqual((code, out), (1, ""))
            self.assertIn("코드: CANDIDATE_NOT_FOUND", err)
        self.assertEqual([item["candidate_id"] for item in self.data_of("candidates", "list")["candidates"]], ids[:2] + ids[3:], "되풀이해도 다른 후보는 그대로다")

    def test_two_processes_deleting_the_same_number_at_once_delete_one_candidate_and_tell_the_other_it_is_gone(self):
        ids = self.six()
        number = ids[1][:8]
        started = [self.start("candidates", "delete", number, "--yes") for _ in range(2)]
        results = [self.finish(process) for process in started]
        self.assertEqual(sorted(code for code, _out, _err in results), [0, 1], results)
        loser = next(err for code, _out, err in results if code == 1)
        self.assertIn("CANDIDATE_NOT_FOUND", loser)
        self.assertEqual([item["candidate_id"] for item in self.data_of("candidates", "list")["candidates"]], ids[:1] + ids[2:])

    def test_a_folder_and_a_device_name_end_at_once_instead_of_waiting_for_input(self):
        """`CON` 을 파일로 읽으면 콘솔 입력을 끝없이 기다렸다 — 읽기 전에 보통 파일인지 본다."""
        names = [str(self.tmp)] + (["CON", "con", "NUL", "\\\\.\\CON"] if sys.platform == "win32" else ["/dev/null"])
        for name in names:
            with self.subTest(name=name):
                done = subprocess.run(self.command("candidates", "import-csv", name), capture_output=True, env=self.env, cwd=self.tmp, timeout=60, stdin=subprocess.DEVNULL)
                err = done.stderr.decode("utf-8")
                self.assertEqual((done.returncode, done.stdout), (1, b""))
                self.assertIn("코드: CANDIDATE_CSV_INVALID", err)
                if name == str(self.tmp):
                    self.assertIn("보통 파일이 아닙니다", err)                    # 폴더는 어디서나 '보통 파일이 아니다'
                else:
                    # 장치 이름은 환경마다 다르다 — 콘솔이 있으면 stat 이 장치로 보여 '보통 파일이 아닙니다', 콘솔이 없는 CI(Windows·Python 3.10)에서는 stat 자체가 실패해
                    # '파일을 읽을 수 없습니다'. 어느 쪽이든 기다리지 않고 바로 끝나는 것(위 timeout)이 약속이다.
                    self.assertTrue("보통 파일이 아닙니다" in err or "파일을 읽을 수 없습니다" in err, err)
        self.assertFalse(self.data.exists(), "아무것도 만들지 않았다")


class RecoveryProcessTest(Base):
    def crash_while_saving(self):
        """저장하다 갑자기 꺼진 보관함을 만든다 — 쓰다 죽은 프로세스가 남긴 저널이 있는 상태."""
        path = self.data / "chanceblog.db"
        with closing(sqlite3.connect(str(path), isolation_level=None)) as db:
            db.execute("BEGIN")
            db.executemany("INSERT OR REPLACE INTO drafts (project_id, text, saved_at) VALUES (?, ?, ?)", [(f"d{number}", "y" * 500, "2026-11-02T03:00:00Z") for number in range(3000)])
            db.execute("COMMIT")
        crash = "\n".join(["import os, sqlite3, sys", "c = sqlite3.connect(sys.argv[1], isolation_level=None)", "c.execute('PRAGMA cache_size = 5')", "c.execute('BEGIN IMMEDIATE')",
                           "for n in range(3000):", "    c.execute('UPDATE drafts SET text = ? WHERE project_id = ?', ('z' * 500, 'd%d' % n))", "os._exit(9)"])
        done = subprocess.run([sys.executable, "-c", crash, str(path)], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 9, done.stderr)
        journal = Path(str(path) + "-journal")
        self.assertTrue(journal.is_file() and journal.stat().st_size > 0, "쓰다 죽어서 끝내지 못한 저장(저널)이 남았다")
        return journal

    def test_after_a_crash_the_reading_commands_say_which_commands_clean_it_up_and_those_commands_really_do(self):
        self.add("가", "가 키워드")
        self.add("나", "나 키워드")
        for cleaner in (("list",), ("candidates", "add", "--topic", "다 주제", "--keyword", "다 키워드", "--blog", "naver_a")):
            with self.subTest(cleaner=cleaner[0:2]):
                journal = self.crash_while_saving()
                for reader in (("candidates", "list"), ("candidates", "show", "1"), ("doctor",)):
                    code, out, err = self.run_module(*reader)
                    if reader[0] == "doctor":
                        self.assertIn("STORE_RECOVERY_PENDING", out + err)
                        continue
                    self.assertEqual((code, out), (1, ""), reader)
                    squeezed = " ".join(err.split())
                    self.assertIn("코드: STORE_RECOVERY_PENDING", squeezed)
                    self.assertIn("`list`", squeezed)
                    self.assertIn("`candidates add", squeezed)
                self.assertTrue(journal.exists(), "읽기만 하는 명령은 저널을 건드리지 않았다")
                code, out, err = self.run_module(*cleaner)
                self.assertEqual((code, err), (0, ""), (cleaner, out, err))
                self.assertFalse(journal.exists(), "안내한 명령이 끝내지 못한 저장을 정리했다")
                self.assertIn("가", self.ok("candidates", "list"), "정리된 뒤에는 후보도 읽힌다")


if __name__ == "__main__":
    unittest.main()
