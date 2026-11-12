"""명령줄 `candidates suggest` 진짜 프로세스 시험 — `python -m chanceblog_desktop` 을 실제로 띄워 종료 코드·표준 출력·표준 오류·`--json` 을 본다. 자식 프로세스는 콘솔 창을 띄우지 않는다(`CREATE_NO_WINDOW`).

지키는 것:
  1) 진입점에서 한글 출력·종료 코드(0·1·2)가 맞고 스택 추적이 없다. 제안은 **읽기만** 한다 — 데이터 폴더가 없으면 만들지 않고 있으면 모든 파일이 바이트·수정 시각까지 그대로다.
  2) `--add --yes` 는 진짜로 보관함에 넣고 같은 명령을 되풀이해도 겹치지 않는다. **두 프로세스가 동시에** 같은 제안을 넣어도(같은 번호·겹치는 번호) 같은 키워드의 후보가 둘 생기지 않는다.
  3) 해시 시드가 다른 프로세스에서도 같은 제안·같은 순서다. 키 모양 문자열은 진짜 출력에도 가려진다.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import suggest_support as sp  # noqa: E402

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402

TOPIC = "생활 절약, 보일러 난방, 가계부"


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.data = self.tmp / "데이터"
        self.env = {**ss.env_without_repo(), "PYTHONPATH": str(ss.ROOT / "src"), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}

    def command(self, *argv):
        return [sys.executable, "-X", "utf8", "-m", "chanceblog_desktop", "--data-dir", str(self.data), *argv]

    def run_module(self, *argv, env=None):
        done = subprocess.run(self.command(*argv), capture_output=True, env=env or self.env, cwd=self.tmp, timeout=180, creationflags=sp.NO_WINDOW)
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

    def start(self, *argv):
        return subprocess.Popen(self.command(*argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=self.tmp, creationflags=sp.NO_WINDOW)

    def finish(self, process):
        out, err = process.communicate(timeout=180)
        return process.returncode, out.decode("utf-8"), err.decode("utf-8")

    def profile(self, name="블로그 에이", blog="naver_a", topic=TOPIC, extra=()):
        return self.ok("naver-profile", "set", blog, "--name", name, "--url", f"https://blog.naver.com/example{blog[-1] * 3}", "--topic", topic, "--tags", "절약,보험", *extra)

    def state(self):
        if not self.data.exists():
            return None
        return {path.relative_to(self.data).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(self.data.rglob("*")) if path.is_file()}

    def stored(self):
        with Store.open(self.data / "chanceblog.db", migrate=False) as store:
            return store.list_candidates()


class SessionTest(Base):
    def test_a_whole_session_with_real_exit_codes_no_trace_and_a_read_only_suggest(self):
        code, out, err = self.run_module("candidates", "suggest")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("프로필에 주제를 적어 주세요", out)
        self.assertFalse(self.data.exists(), "읽기만 하는 명령은 데이터 폴더를 만들지 않는다")

        self.profile()
        before = self.state()
        out = self.ok("candidates", "suggest", "--month", "11")
        self.assertIn("네이버 A(블로그 에이) 주제 제안 — 11월 기준", out)
        self.assertEqual(len(re.findall(r"^  \[\d+\] 콘텐츠 작성 우선도 ", out, re.M)), 10)
        self.assertEqual(self.state(), before, "제안은 아무것도 쓰지 않았다")
        self.assertFalse((self.data / "chanceblog.db").exists())

        out = self.ok("candidates", "suggest", "--blog", "naver_a", "--add", "1,2", "--month", "11")
        self.assertIn("제안 넣기 미리 보기", out)
        self.assertEqual(self.state(), before, "--yes 없이는 넣지 않는다")
        out = self.ok("candidates", "suggest", "--blog", "naver_a", "--add", "1,2", "--month", "11", "--yes")
        self.assertIn("제안 2개를 새 후보(출처: 프로필 제안)로 보관함에 넣었습니다", out)
        stored = {item.keyword: item for item in self.stored()}
        self.assertEqual(len(stored), 2)
        again = self.ok("candidates", "suggest", "--blog", "naver_a", "--add", "1,2", "--month", "11", "--yes")
        self.assertIn("넣은 제안이 없습니다", again)
        self.assertEqual(len(self.stored()), 2)
        listing = self.ok("candidates", "list", "--priority")
        self.assertEqual(len(re.findall(r"^  \[\d\] 새 후보 — .+ · 콘텐츠 작성 우선도 (?:높음|보통|낮음) ", listing, re.M)), 2)
        self.assertIn("왜 이 우선도인지", self.ok("candidates", "show", "1"))
        after = self.state()
        self.ok("candidates", "suggest", "--month", "11")
        self.ok("candidates", "list", "--priority")
        self.ok("candidates", "show", "2")
        self.assertEqual(self.state(), after, "읽기 명령들은 보관함 파일을 그대로 두었다")

    def test_usage_errors_and_handled_errors_exit_two_and_one_without_a_stack_trace(self):
        self.profile()
        for argv in (("candidates", "suggest", "--count", "0"), ("candidates", "suggest", "--month", "13"), ("candidates", "suggest", "--yes"), ("candidates", "suggest", "--type", "소설")):
            code, out, err = self.run_module(*argv)
            self.assertEqual((code, out), (2, ""), argv)
            self.assertIn("사용법 오류", err)
        code, out, err = self.run_module("candidates", "suggest", "--blog", "naver_a", "--add", "99", "--yes")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: SUGGESTION_NOT_FOUND", err)
        self.assertFalse((self.data / "chanceblog.db").exists(), "찾지 못하면 보관함도 만들지 않는다")
        code, out, err = self.run_module("--json", "candidates", "suggest", "--blog", "naver_a", "--add", "99")
        payload = json.loads(out)
        self.assertEqual((code, err, payload["ok"], payload["error"]["code"]), (1, "", False, "SUGGESTION_NOT_FOUND"))

    def test_the_help_is_korean_for_real(self):
        code, out, err = self.run_module("candidates", "suggest", "--help")
        self.assertEqual((code, err), (0, ""))
        for needle in ("사용법:", "--add", "--yes", "읽기만 합니다"):
            self.assertIn(needle, out)
        for word in ("usage:", "positional arguments", "options:"):
            self.assertNotIn(word, out)

    def test_a_key_shaped_text_in_the_profile_is_masked_in_the_real_output(self):
        from chanceblog_desktop.content.profiles import NaverProfile
        from chanceblog_desktop.service.context import Settings, Workspace
        workspace = Workspace(self.data)                                 # 옛 버전이 저장한 것처럼 설정 파일에 직접 쓴다 — 명령줄 쓰기 길은 이제 키 모양을 거절한다(PCSEC1 M3)
        workspace.ensure()
        Settings(workspace.settings_path).save_naver_profile(NaverProfile("naver_a", "이름 " + ss.KEY, "https://blog.naver.com/exampleaaa", topic=TOPIC, default_tags=("절약", "보험")))
        for argv in (("candidates", "suggest"), ("--json", "candidates", "suggest"), ("--verbose", "candidates", "suggest"), ("naver-profile", "show")):
            out = self.ok(*argv)
            self.assertNotIn(ss.KEY, out)
        self.assertIn("[가림", self.ok("candidates", "suggest"))


class DeterminismTest(Base):
    def test_processes_with_different_hash_seeds_print_the_same_suggestions_in_the_same_order(self):
        self.profile()
        outputs = {}
        for seed in ("0", "1", "777", "random"):
            env = {**self.env, "PYTHONHASHSEED": seed}
            code, out, err = self.run_module("--json", "candidates", "suggest", "--month", "11", "--count", "30", env=env)
            self.assertEqual((code, err), (0, ""))
            groups = json.loads(out)["data"]["blogs"]
            outputs[seed] = [(item["rank"], item["keyword"], item["topic"], item["priority"], tuple(item["sub_keywords"])) for item in groups[0]["suggestions"]]
        self.assertEqual(len({json.dumps(value, ensure_ascii=False) for value in outputs.values()}), 1)
        self.assertEqual(len(outputs["0"]), 30)


class ConcurrencyTest(Base):
    def duplicates(self):
        keys = [cd.keyword_key(item.keyword) for item in self.stored()]
        return len(keys) - len(set(keys))

    def test_two_processes_adding_the_same_suggestions_at_once_never_make_two_of_the_same_keyword(self):
        self.profile()
        self.ok("candidates", "suggest")                                                       # 보관함이 없을 때도 안전하도록 처음에는 보관함이 없다
        for round_number in range(3):
            first = self.start("candidates", "suggest", "--blog", "naver_a", "--add", "all", "--month", "11", "--yes", "--count", "6")
            second = self.start("candidates", "suggest", "--blog", "naver_a", "--add", "all", "--month", "11", "--yes", "--count", "6")
            results = [self.finish(first), self.finish(second)]
            for code, out, err in results:
                self.assertEqual((code, err), (0, ""), (round_number, out, err))
            self.assertEqual(self.duplicates(), 0, f"{round_number}번째: 같은 키워드의 후보가 둘 생겼다")
            self.assertLessEqual(len(self.stored()), 6, "all 은 번호 1~6 이라 두 프로세스가 합쳐도 6개를 넘지 않는다")
            self.assertGreaterEqual(len(self.stored()), 6)
            for item in self.stored():
                self.assertTrue(item.reason.startswith("프로필 제안 — "))

    def test_two_processes_with_overlapping_numbers_end_with_the_union_once_each(self):
        self.profile()
        first = self.start("candidates", "suggest", "--blog", "naver_a", "--add", "1,2,3", "--month", "11", "--yes")
        second = self.start("candidates", "suggest", "--blog", "naver_a", "--add", "2,3,4", "--month", "11", "--yes")
        for code, out, err in (self.finish(first), self.finish(second)):
            self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.duplicates(), 0)
        self.assertEqual(len(self.stored()), 4, "합치면 1,2,3,4 — 겹친 번호는 한 번씩만")


if __name__ == "__main__":
    unittest.main()
