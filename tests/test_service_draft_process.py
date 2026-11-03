"""명령줄 `draft plan` 진짜 프로세스 시험 — `python -m chanceblog_desktop` 을 실제로 띄워 종료 코드·표준 출력·표준 오류·`--json` 을 본다.

지키는 것:
  1) 진입점에서 한글 출력·종료 코드(0 정상·1 처리된 오류·2 사용법 오류)가 맞고 스택 추적이 나오지 않는다.
  2) **읽기만 한다** — 계획을 만든 뒤에도 데이터 폴더의 파일 목록과 내용(SHA-256)이 그대로이고, 보관함이 없으면 폴더도 만들지 않는다. 여러 프로세스가 동시에 읽어도 모두 정상이고 파일은 그대로다.
  3) 같은 입력은 PYTHONHASHSEED 가 달라도 같은 출력이다(무작위·집합 순서에 기대지 않는다).
  4) 선택 입력이 하나도 없어도 종료 코드 0, 틀린 값은 1, 키 모양 문자열은 진짜 출력에서도 가려진다.
시험은 경로·`os.name`·콘솔에 기대지 않는다(파이프로 출력을 받는다).
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

STATUS_CODES = re.compile(r"\b(?:NEW|REVIEW|SELECTED|HOLD|REJECTED)\b")
LONG_ID = re.compile(r"\b[0-9a-f]{32}\b")


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
        done = subprocess.run(self.command(*argv), capture_output=True, env=env or self.env, cwd=self.tmp, timeout=180)
        out, err = done.stdout.decode("utf-8"), done.stderr.decode("utf-8")
        self.assertNotIn("Traceback", err)
        return done.returncode, out, err

    def ok(self, *argv, env=None):
        code, out, err = self.run_module(*argv, env=env)
        self.assertEqual((code, err), (0, ""), (argv, out, err))
        return out

    def add(self, topic, keyword, *blogs, extra=()):
        flags = [item for blog in blogs for item in ("--blog", blog)]
        return self.ok("candidates", "add", "--topic", topic, "--keyword", keyword, *flags, *extra)

    def fingerprint(self):
        """데이터 폴더의 (상대 경로 → SHA-256) — 폴더가 없으면 None."""
        if not self.data.exists():
            return None
        return {path.relative_to(self.data).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(self.data.rglob("*")) if path.is_file()}


class PlanProcessTest(Base):
    def test_a_plan_from_a_real_process_is_korean_complete_and_leaves_the_data_untouched(self):
        self.add("겨울 보일러 점검 순서", "보일러 점검", "naver_a", "naver_b", extra=("--sub-keywords", "보일러 청소,난방비"))
        before = self.fingerprint()
        self.assertEqual(set(before), {"chanceblog.db"})
        out = self.ok("draft", "plan", "1", "--blog", "naver_a")
        for needle in ("작성 기반 — 후보 [1] 겨울 보일러 점검 순서 · 네이버 A 용", "제목 후보:", "본문 작성 방향:", "권장 목차와 소제목:", "포함할 핵심 내용:", "주의사항:", "추천 태그:", "확인 권장(있어도 계획은 이대로 쓸 수 있습니다):",
                       "아무것도 저장하지 않았습니다", "다른 네이버 블로그(네이버 B) 용 계획과 견줘 봤습니다."):
            self.assertIn(needle, out)
        self.assertNotRegex(out, STATUS_CODES)
        self.assertNotRegex(out, LONG_ID)
        self.assertEqual(self.fingerprint(), before)

    def test_json_from_a_real_process(self):
        self.add("노트북 추천 비교", "노트북 비교", "naver_a", extra=("--post-type", "비교형"))
        before = self.fingerprint()
        payload = json.loads(self.ok("--json", "draft", "plan", "1"))
        self.assertEqual((payload["ok"], payload["command"]), (True, "draft plan"))
        plan = payload["data"]["plan"]
        self.assertEqual((plan["blog"], plan["post_type"], plan["outline"][0]), ("naver_a", "비교형", "비교 목적"))
        self.assertEqual(len(plan["titles"]), 3)
        self.assertTrue(plan["complete"])
        self.assertTrue(payload["data"]["read_only"])
        self.assertEqual(self.fingerprint(), before)

    def test_all_options_in_a_real_process_and_the_data_is_still_untouched(self):
        self.add("서울 한강 야경 명소", "한강 야경", "naver_a", extra=("--post-type", "장소·업체 정보형"))
        before = self.fingerprint()
        out = self.ok("draft", "plan", "1", "--experience", "지난 주말에 갔고 사람이 많지 않았습니다.", "--message", "야경 사진 팁도 넣고 싶습니다", "--opinion", "저녁 시간대를 추천합니다", "--must-include", "한강공원 이용 시간을 확인하세요",
                      "--exclude", "광고,협찬", "--audience", "처음 가는 사람", "--length", "1800-2200", "--title-direction", "질문형", "--url", "https://example.com/guide", "--price-date", "입장료는 무료", "--conclusion", "가기 전에 확인하세요")
        self.assertIn("방문 경험", out)
        self.assertIn("실제 경험(입력): 지난 주말에 갔고 사람이 많지 않았습니다.", out)
        self.assertIn("  - https://example.com/guide", out)
        self.assertIn("1,800~2,200자", out)
        self.assertEqual(self.fingerprint(), before)

    def test_a_missing_store_is_a_handled_error_and_creates_nothing(self):
        code, out, err = self.run_module("draft", "plan", "1")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("CANDIDATE_NOT_FOUND", err)
        self.assertFalse(self.data.exists())
        code, out, err = self.run_module("--json", "draft", "plan", "1")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["error"]["code"], "CANDIDATE_NOT_FOUND")
        self.assertFalse(self.data.exists())

    def test_exit_codes_for_wrong_values_and_wrong_usage(self):
        self.add("가 주제", "가 키워드", "naver_a")
        before = self.fingerprint()
        code, out, err = self.run_module("draft", "plan", "1", "--url", "http://example.com")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("DRAFT_OPTION_INVALID", err)
        self.assertIn("참고 URL", err)
        for argv in (("draft",), ("draft", "plan"), ("draft", "plan", "1", "--nope"), ("draft", "plan", "1", "--exp", "x"), ("draft", "plan", "1", "--blog", "tistory")):
            with self.subTest(argv=argv):
                code, out, err = self.run_module(*argv)
                self.assertEqual((code, out), (2, ""), err)
                self.assertIn("사용법 오류", err)
        self.assertEqual(self.fingerprint(), before)

    def test_help_in_a_real_process_is_korean(self):
        for argv in (("draft", "--help"), ("draft", "plan", "--help")):
            code, out, err = self.run_module(*argv)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("사용법:", out)
            self.assertIn("이 도움말을 보여 주고 끝냅니다", out)
            self.assertNotIn("usage:", out)

    def test_secret_shaped_text_is_refused_and_never_printed_by_the_real_process(self):
        self.add("가 주제", "가 키워드", "naver_a")
        for argv in (("draft", "plan", "1", "--message", f"비밀 {ss.KEY}"), ("--json", "draft", "plan", "1", "--conclusion", f"결론 {ss.KEY}"), ("draft", "plan", "1", "--length", ss.KEY)):
            code, out, err = self.run_module(*argv)
            self.assertEqual(code, 1, argv)
            self.assertNotIn(ss.KEY, out + err)
            self.assertNotIn(ss.KEY[:12], out + err)
            self.assertIn("DRAFT_OPTION_INVALID", out + err)

    def test_the_output_does_not_depend_on_the_hash_seed(self):
        self.add("겨울 보일러 점검 순서", "보일러 점검", "naver_a", "naver_b", extra=("--sub-keywords", "보일러 청소,난방비,점검 주기"))
        outputs = set()
        for seed in ("0", "1", "777"):
            outputs.add(self.ok("draft", "plan", "1", "--blog", "naver_b", "--exclude", "가격,광고", "--must-include", "문장 하나", "--must-include", "문장 둘", env={**self.env, "PYTHONHASHSEED": seed}))
        self.assertEqual(len(outputs), 1)

    def test_several_processes_can_read_at_the_same_time(self):
        self.add("겨울 보일러 점검 순서", "보일러 점검", "naver_a", "naver_b")
        before = self.fingerprint()
        processes = [subprocess.Popen(self.command("draft", "plan", "1", "--blog", blog), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=self.tmp) for blog in ("naver_a", "naver_b", "naver_a", "naver_b")]
        for process in processes:
            out, err = process.communicate(timeout=180)
            self.assertEqual((process.returncode, err.decode("utf-8")), (0, ""))
            self.assertIn("작성 기반", out.decode("utf-8"))
        self.assertEqual(self.fingerprint(), before)

    def test_a_plan_can_be_made_while_another_process_holds_the_store_for_reading(self):
        self.add("가 주제", "가 키워드", "naver_a")
        first = subprocess.Popen(self.command("draft", "plan", "1"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=self.tmp)
        out = self.ok("candidates", "list")
        self.assertIn("가 주제", out)
        self.assertEqual(first.communicate(timeout=180)[0].decode("utf-8").count("작성 기반"), 1)


if __name__ == "__main__":
    unittest.main()
