"""`context.write_json` 시험 — 설정·연결·사용량·발행 기록 파일이 함께 쓰는 '임시 파일에 쓰고 → 디스크에 내려보내고(`fsync`) → 이름을 바꾸는' 저장.

지키는 것:
  1) 순서: 열기 → 쓰기(짧게 끊겨도 끝까지) → fsync → 닫기 → 이름 바꾸기. 이름을 바꾸는 순간 임시 파일에는 완전한 새 내용이 있고 옛 파일은 그대로다.
  2) 실패(쓰기·fsync·닫기·이름 바꾸기·열기)는 쉬운 오류가 되고 옛 파일은 한 바이트도 안 바뀌며 임시 파일은 남지 않는다. 디스크가 가득 찬 오류는 따로 알린다. 열어 둔 파일은 늘 닫는다.
  3) 강제 종료 흉내(쓰는 도중·이름을 바꾸기 직전에 프로그램이 죽음): 옛 파일이 그대로이고 새 파일은 비어 있는 채로 자리를 차지하지 않으며, 다음 저장이 남은 임시 파일을 치운다.
  4) 줄바꿈은 어떤 운영체제에서도 LF 이고 글자는 UTF-8 이며 파일 이름은 한글이어도 된다. 설정·연결·사용량 저장이 모두 이 경로를 지난다.
이 시험은 진짜 `os.fsync` 를 부르되 전원을 끊지는 못하므로 '디스크에 닿았는지'가 아니라 '이름을 바꾸기 전에 fsync 를 불렀는지'를 지킨다.
"""
import errno
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.service import context  # noqa: E402
from chanceblog_desktop.service import quota as q  # noqa: E402

DATA = {"가": "한글 값", "b": [1, 2, {"c": None}], "a": "x" * 5000}
OLD = {"옛": "내용"}
REAL = {name: getattr(os, name) for name in ("open", "write", "fsync", "close", "replace")}


def expected_bytes(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


class WriteJsonCase(unittest.TestCase):
    """os 의 열기·쓰기·fsync·닫기·이름 바꾸기를 진짜로 부르면서 순서를 기록하고, 원하는 곳에서 실패나 '강제 종료'를 끼워 넣는다."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "설정 파일.json"
        self.temp = self.path.with_name(self.path.name + ".tmp")
        self.log = []
        self.hooks = {}                                   # 이름 → 부를 때마다 먼저 실행할 함수(예외를 내면 그 호출은 실패한다)
        self.short = 0                                    # 0 보다 크면 한 번에 이만큼만 쓴다(짧은 쓰기)
        self.at_replace = []
        self.opened, self.closed, self.fsynced = [], [], []
        for name in REAL:
            self.patch(name)

    def patch(self, name):
        real = REAL[name]

        def run(*args, **kwargs):
            self.log.append(name)
            hook = self.hooks.get(name)
            if hook is not None:
                hook(len(self.log))
            if name == "write" and self.short and len(args[1]) > self.short:
                return real(args[0], bytes(args[1][:self.short]))
            if name == "fsync":
                self.fsynced.append(args[0])
            if name == "replace":
                self.at_replace.append((self.temp.read_bytes() if self.temp.exists() else None, self.path.read_bytes() if self.path.exists() else None))
            result = real(*args, **kwargs)
            if name == "open":
                self.opened.append(result)
            if name == "close":
                self.closed.append(args[0])
            return result

        setattr(os, name, run)
        self.addCleanup(setattr, os, name, real)

    def put_old(self):
        self.path.write_bytes(expected_bytes(OLD))

    def fail_with(self, name, error):
        def hook(_count):
            raise error
        self.hooks[name] = hook

    def close_leaked(self):
        """시험이 일부러 막은 닫기 때문에 열린 채 남은 파일을 진짜로 닫아 둔다(Windows 는 열린 파일이 있는 폴더를 못 지운다)."""
        for fd in self.opened:
            if fd not in self.closed:
                REAL["close"](fd)


class OrderTest(WriteJsonCase):
    def test_the_bytes_are_utf8_with_lf_and_sorted_keys(self):
        context.write_json(self.path, DATA)
        self.assertEqual(self.path.read_bytes(), expected_bytes(DATA))
        self.assertNotIn(b"\r", self.path.read_bytes())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), DATA)
        self.assertFalse(self.temp.exists(), "임시 파일은 이름을 바꾸면서 사라진다")

    def test_it_opens_writes_flushes_to_disk_closes_and_only_then_renames(self):
        self.put_old()
        context.write_json(self.path, DATA)
        self.assertEqual(self.log[0], "open")
        self.assertEqual(self.log[-3:], ["fsync", "close", "replace"])
        self.assertEqual(set(self.log[1:-3]), {"write"})
        self.assertGreaterEqual(len(self.log), 5)

    def test_at_the_moment_of_the_rename_the_temp_file_is_complete_and_the_old_file_is_untouched(self):
        self.put_old()
        context.write_json(self.path, DATA)
        self.assertEqual(self.at_replace, [(expected_bytes(DATA), expected_bytes(OLD))])

    def test_the_flush_is_on_the_descriptor_that_was_written_and_it_is_closed_exactly_once(self):
        context.write_json(self.path, DATA)
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(self.fsynced, self.opened)
        self.assertEqual(self.closed, self.opened)

    def test_a_short_write_is_continued_until_every_byte_is_written(self):
        self.short = 7
        context.write_json(self.path, DATA)
        self.assertEqual(self.path.read_bytes(), expected_bytes(DATA))
        self.assertGreater(self.log.count("write"), 100)
        self.assertEqual(self.log.count("fsync"), 1, "다 쓴 뒤에 한 번만 내려보낸다")

    def test_the_folder_is_created_and_a_new_file_needs_no_old_one(self):
        deep = self.dir / "없는 폴더" / "안쪽" / "x.json"
        context.write_json(deep, OLD)
        self.assertEqual(deep.read_bytes(), expected_bytes(OLD))

    def test_an_existing_stale_temp_file_is_overwritten_from_the_start(self):
        self.temp.write_bytes(b"x" * 100000)                      # 지난번 강제 종료가 남긴 긴 임시 파일
        context.write_json(self.path, OLD)
        self.assertEqual(self.path.read_bytes(), expected_bytes(OLD))
        self.assertFalse(self.temp.exists())

    def test_the_settings_the_connections_and_the_usage_files_all_take_this_path(self):
        ctx = ss.make_ctx(self.dir)
        self.log.clear()
        ctx.settings.save_repo_path(str(self.dir / "다른 저장소"))                       # 설정
        self.assertEqual(self.log.count("fsync"), 1)
        cn.add_entry(ctx, "naver_openapi", name="키", fields={"client_id": "abcdefgh12345", "client_secret": "tinysecret1"}, project="앱")      # 연결
        self.assertGreaterEqual(self.log.count("fsync"), 2)
        before = self.log.count("fsync")
        guard = q.QuotaGuard(ctx, lock_wait=0)
        self.assertIsInstance(guard.acquire("naver_openapi"), q.Lease)                    # 사용량
        self.assertGreater(self.log.count("fsync"), before)
        for path in (ctx.workspace.settings_path, ctx.workspace.connections_path, ctx.workspace.quota_path):
            self.assertTrue(path.exists())
            self.assertFalse(path.with_name(path.name + ".tmp").exists())


class FailureTest(WriteJsonCase):
    def assertUnchanged(self):
        self.assertEqual(self.path.read_bytes(), expected_bytes(OLD))
        self.assertFalse(self.temp.exists(), "실패한 저장이 임시 파일을 남기지 않는다")
        self.assertEqual(self.closed, self.opened, "열어 둔 파일은 늘 닫는다")

    def test_a_flush_failure_is_a_plain_error_and_the_old_file_stays_and_no_rename_happens(self):
        self.put_old()
        self.fail_with("fsync", OSError(errno.EIO, "입출력 오류"))
        with self.assertRaises(AppError) as caught:
            context.write_json(self.path, DATA)
        self.assertEqual(caught.exception.code, "FILE_WRITE_FAILED")
        self.assertIn("OSError", caught.exception.detail)
        self.assertNotIn("replace", self.log)
        self.assertUnchanged()

    def test_a_write_failure_in_the_middle_keeps_the_old_file(self):
        self.put_old()
        self.short = 50

        def second_write_fails(_count):
            if self.log.count("write") == 2:
                raise OSError(errno.EIO, "입출력 오류")

        self.hooks["write"] = second_write_fails
        with self.assertRaises(AppError) as caught:
            context.write_json(self.path, DATA)
        self.assertEqual(caught.exception.code, "FILE_WRITE_FAILED")
        self.assertEqual(self.log.count("write"), 2)
        self.assertNotIn("fsync", self.log)
        self.assertUnchanged()

    def test_a_full_disk_is_reported_as_a_full_disk_at_any_step(self):
        for name in ("write", "fsync", "replace"):
            with self.subTest(step=name):
                self.setUp()
                self.put_old()
                self.fail_with(name, OSError(errno.ENOSPC, "No space left on device"))
                with self.assertRaises(AppError) as caught:
                    context.write_json(self.path, DATA)
                self.assertEqual(caught.exception.code, "DISK_FULL")
                self.assertUnchanged()

    def test_a_failed_rename_keeps_the_old_file_and_removes_the_temp_file(self):
        self.put_old()
        self.fail_with("replace", PermissionError(errno.EACCES, "접근할 수 없음"))
        with self.assertRaises(AppError) as caught:
            context.write_json(self.path, DATA)
        self.assertEqual(caught.exception.code, "FILE_WRITE_FAILED")
        self.assertIn("PermissionError", caught.exception.detail)
        self.assertUnchanged()

    def test_a_failure_to_open_the_temp_file_is_a_plain_error(self):
        self.put_old()
        self.fail_with("open", PermissionError(errno.EACCES, "접근할 수 없음"))
        with self.assertRaises(AppError) as caught:
            context.write_json(self.path, DATA)
        self.assertEqual(caught.exception.code, "FILE_WRITE_FAILED")
        self.assertEqual(self.path.read_bytes(), expected_bytes(OLD))
        self.assertFalse(self.temp.exists())

    def test_a_failure_to_close_is_still_reported_and_keeps_the_old_file(self):
        self.put_old()
        self.fail_with("close", OSError(errno.EIO, "입출력 오류"))
        with self.assertRaises(AppError) as caught:
            context.write_json(self.path, DATA)
        self.assertEqual(caught.exception.code, "FILE_WRITE_FAILED")
        self.assertNotIn("replace", self.log)
        self.assertEqual(self.path.read_bytes(), expected_bytes(OLD))
        self.close_leaked()

    def test_the_error_never_carries_the_content_that_was_being_saved(self):
        self.put_old()
        secret_looking = {"text": "SECRET-LOOKING-" + "z" * 40}
        self.fail_with("fsync", OSError(errno.EIO, "입출력 오류"))
        with self.assertRaises(AppError) as caught:
            context.write_json(self.path, secret_looking)
        text = " ".join([str(caught.exception), caught.exception.detail, repr(caught.exception), str(caught.exception.args)])
        self.assertNotIn("SECRET-LOOKING", text)


class CrashTest(WriteJsonCase):
    """강제 종료 흉내 — `SystemExit`·`KeyboardInterrupt` 같은 '오류가 아닌 끝남'을 쓰는 도중이나 이름을 바꾸기 직전에 낸다."""

    def test_a_crash_right_before_the_rename_keeps_the_old_file_and_leaves_a_complete_new_one_beside_it(self):
        self.put_old()
        self.fail_with("replace", SystemExit("강제 종료 흉내"))
        with self.assertRaises(SystemExit):
            context.write_json(self.path, DATA)
        self.assertEqual(self.path.read_bytes(), expected_bytes(OLD))
        self.assertEqual(self.temp.read_bytes(), expected_bytes(DATA), "fsync 를 마친 뒤였으니 임시 파일에는 완전한 새 내용이 있다")
        self.assertEqual(self.closed, self.opened)
        self.hooks.clear()
        context.write_json(self.path, {"다음": 1})                                          # 다음 저장이 남은 임시 파일을 치운다
        self.assertEqual(self.path.read_bytes(), expected_bytes({"다음": 1}))
        self.assertFalse(self.temp.exists())

    def test_a_crash_in_the_middle_of_writing_never_shows_a_half_written_file(self):
        self.put_old()
        self.short = 40

        def die(count):
            if self.log.count("write") == 3:
                raise KeyboardInterrupt()

        self.hooks["write"] = die
        with self.assertRaises(KeyboardInterrupt):
            context.write_json(self.path, DATA)
        self.assertEqual(self.path.read_bytes(), expected_bytes(OLD), "원래 파일은 그대로다")
        self.assertLess(self.temp.stat().st_size, len(expected_bytes(DATA)), "반쯤 쓴 것은 임시 파일에만 있다")
        self.assertNotIn("fsync", self.log)
        self.assertNotIn("replace", self.log)
        self.assertEqual(self.closed, self.opened)
        self.hooks.clear()
        self.short = 0
        context.write_json(self.path, DATA)
        self.assertEqual(self.path.read_bytes(), expected_bytes(DATA))
        self.assertFalse(self.temp.exists())

    def test_a_crash_while_saving_a_file_that_did_not_exist_leaves_no_file_at_all_not_an_empty_one(self):
        self.fail_with("replace", SystemExit("강제 종료 흉내"))
        with self.assertRaises(SystemExit):
            context.write_json(self.path, DATA)
        self.assertFalse(self.path.exists(), "새 파일이 비어 있는 채로 자리를 차지하지 않는다")
        self.assertEqual(self.temp.read_bytes(), expected_bytes(DATA))

    def test_a_crash_at_every_step_never_leaves_the_target_empty_or_partial(self):
        for name in ("open", "write", "fsync", "close", "replace"):
            for existing in (False, True):
                with self.subTest(step=name, existing=existing):
                    self.setUp()
                    if existing:
                        self.put_old()
                    self.fail_with(name, SystemExit("강제 종료 흉내"))
                    with self.assertRaises(SystemExit):
                        context.write_json(self.path, DATA)
                    if existing:
                        self.assertEqual(self.path.read_bytes(), expected_bytes(OLD))
                    else:
                        self.assertFalse(self.path.exists())
                    if name == "close":
                        self.close_leaked()
                    else:
                        self.assertEqual(self.closed, self.opened)


if __name__ == "__main__":
    unittest.main()
