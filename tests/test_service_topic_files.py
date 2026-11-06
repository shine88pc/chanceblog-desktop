"""주제 엔진 설정 파일 셋(`service/topic_files.py` — `channel_profiles.json`·`seeds.json`·`calendar.json`) 시험(P3, D-59). 네트워크·실제 시계 없이 돈다.

지키는 것:
  1) 파일이 없으면 기본값(프로필 다섯 개·빈 씨앗·빈 캘린더)으로 읽고 **파일도 폴더도 만들지 않는다**. 만드는 일은 `init_files` 뿐이고 없는 파일만 만든다.
  2) 파일마다 `schema` 숫자와 정확한 칸 집합을 요구하고 모르는 칸·틀린 값·겹친 번호는 읽지 않고 오류로 멈춘다(고쳐 읽거나 덮어쓰지 않는다). 글자나 JSON 이 아니면 TOPIC_FILE_INVALID, 칸의 값이 틀리면 CONTENT_INVALID.
  3) 읽기·쓰기는 `topics/` 의 to_dict·from_dict 와 `context.write_json` 만 거친다(왕복하면 같은 값).
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.topics import channels, layout, schedule, seeds  # noqa: E402


def code_of(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code
    return None


def tree(root):
    return sorted(str(path.relative_to(root)) for path in Path(root).rglob("*"))


class PathsTest(unittest.TestCase):
    def test_the_four_files_live_under_a_topic_engine_folder_with_the_names_from_the_layout_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp)
            paths = tf.topic_paths(ctx.workspace)
            self.assertEqual(paths.folder, ctx.workspace.root / "topic_engine")
            self.assertEqual([path.name for path in (paths.database, paths.profiles, paths.seeds, paths.calendar)], [layout.ENGINE_DB_FILE, layout.CHANNEL_PROFILES_FILE, layout.SEEDS_FILE, layout.CALENDAR_FILE])
            self.assertEqual([name for name, _path in paths.json_files()], list(layout.JSON_FILES))
            self.assertEqual(paths.database.parent, paths.folder)


class MissingFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = ss.make_ctx(self.tmp.name)
        self.paths = tf.topic_paths(self.ctx.workspace)

    def test_a_missing_file_reads_as_the_default_and_nothing_is_created(self):
        before = tree(self.tmp.name)
        profiles, found_seeds, calendar = tf.load_profiles(self.paths), tf.load_seeds(self.paths), tf.load_calendar(self.paths)
        self.assertEqual((profiles.state, found_seeds.state, calendar.state), (tf.STATE_MISSING,) * 3)
        self.assertEqual(profiles.value, channels.default_profiles())
        self.assertEqual((found_seeds.value, calendar.value), ((), ()))
        self.assertEqual(tf.missing_files(self.paths), layout.JSON_FILES)
        self.assertEqual(tree(self.tmp.name), before, "읽기는 파일도 폴더도 만들지 않는다")
        self.assertFalse(self.paths.folder.exists())

    def test_init_creates_only_the_missing_files_with_the_default_content_and_keeps_the_rest(self):
        made, kept = tf.init_files(self.paths)
        self.assertEqual((made, kept), (layout.JSON_FILES, ()))
        self.assertEqual(sorted(os.listdir(self.paths.folder)), sorted(layout.JSON_FILES))
        self.assertEqual(tf.load_profiles(self.paths).value, channels.default_profiles())
        self.assertEqual((tf.load_seeds(self.paths).value, tf.load_calendar(self.paths).state), ((), tf.STATE_OK))
        self.assertEqual(json.loads(self.paths.seeds.read_text(encoding="utf-8")), {"schema": 1, "seeds": []})
        self.assertEqual(json.loads(self.paths.calendar.read_text(encoding="utf-8")), {"schema": 1, "entries": []})
        self.assertEqual(json.loads(self.paths.profiles.read_text(encoding="utf-8"))["schema"], 1)
        self.paths.seeds.write_text(json.dumps(seeds.seeds_to_dict([ts.example_seed()])), encoding="utf-8")
        my_seeds = self.paths.seeds.read_bytes()
        self.assertEqual(tf.init_files(self.paths), ((), layout.JSON_FILES))
        self.assertEqual(self.paths.seeds.read_bytes(), my_seeds, "이미 있는 파일은 건드리지 않는다")
        self.paths.calendar.unlink()
        self.assertEqual(tf.init_files(self.paths), ((layout.CALENDAR_FILE,), (layout.CHANNEL_PROFILES_FILE, layout.SEEDS_FILE)))

    def test_an_unreadable_existing_file_is_neither_replaced_nor_fixed_by_init(self):
        self.paths.folder.mkdir(parents=True)
        self.paths.seeds.write_bytes(b"{broken")
        made, kept = tf.init_files(self.paths)
        self.assertEqual((made, kept), ((layout.CHANNEL_PROFILES_FILE, layout.CALENDAR_FILE), (layout.SEEDS_FILE,)))
        self.assertEqual(self.paths.seeds.read_bytes(), b"{broken")

    def test_the_files_are_written_with_write_json_and_nothing_else(self):
        calls = []
        real = tf.write_json
        tf.write_json = lambda path, data: (calls.append((Path(path).name, sorted(data))), real(path, data))
        self.addCleanup(setattr, tf, "write_json", real)
        tf.init_files(self.paths)
        self.assertEqual(calls, [(layout.CHANNEL_PROFILES_FILE, ["profiles", "schema"]), (layout.SEEDS_FILE, ["schema", "seeds"]), (layout.CALENDAR_FILE, ["entries", "schema"])])
        text = self.paths.seeds.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n") and '"schema": 1' in text, "write_json 의 모양(들여쓰기·끝 줄바꿈)")
        self.assertEqual(sorted(name for name in os.listdir(self.paths.folder) if name.endswith(".tmp")), [], "임시 파일을 남기지 않는다")


class StrictReadingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = tf.topic_paths(ss.make_ctx(self.tmp.name).workspace)
        self.paths.folder.mkdir(parents=True)

    def put(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_good_files_round_trip_to_the_same_values(self):
        pool = (ts.example_seed(), ts.example_seed(seed_id="ex-seed-002", keyword="예시 씨앗 둘"))
        entries = (ts.example_entry(),)
        tweaked = tuple(profile if profile.key != "naver_a" else __import__("dataclasses").replace(profile, top_n=7) for profile in channels.default_profiles())
        self.put(self.paths.seeds, seeds.seeds_to_dict(pool))
        self.put(self.paths.calendar, schedule.entries_to_dict(entries))
        self.put(self.paths.profiles, channels.profiles_to_dict(tweaked))
        self.assertEqual((tf.load_seeds(self.paths).value, tf.load_calendar(self.paths).value, tf.load_profiles(self.paths).value), (pool, entries, tweaked))
        self.assertEqual(tf.load_seeds(self.paths).state, tf.STATE_OK)

    def test_text_that_is_not_utf8_json_is_a_file_error_and_a_value_error_is_a_content_error(self):
        cases = (
            (b"\xff\xfe\x00broken", "TOPIC_FILE_INVALID"), (b"{not json", "TOPIC_FILE_INVALID"), (b"", "TOPIC_FILE_INVALID"), (b"[1, 2, 3]", "CONTENT_INVALID"), (b"{}", "CONTENT_INVALID"),
            (json.dumps({"schema": 2, "seeds": []}).encode(), "CONTENT_INVALID"), (json.dumps({"schema": 1, "seeds": [], "extra": 1}).encode(), "CONTENT_INVALID"),
            (json.dumps({"schema": "1", "seeds": []}).encode(), "CONTENT_INVALID"), (json.dumps({"schema": 1, "seeds": "none"}).encode(), "CONTENT_INVALID"),
            (json.dumps({"schema": 1, "seeds": [{"seed_id": "x"}]}).encode(), "CONTENT_INVALID"),
            (json.dumps({"schema": 1, "seeds": [{**ts.example_seed().to_dict(), "unknown": 1}]}).encode(), "CONTENT_INVALID"),
            (json.dumps(seeds.seeds_to_dict([ts.example_seed()]) | {"seeds": [ts.example_seed().to_dict(), ts.example_seed().to_dict()]}).encode(), "CONTENT_INVALID"),
        )
        for raw, code in cases:
            with self.subTest(raw=raw[:30], code=code):
                self.paths.seeds.write_bytes(raw)
                self.assertEqual(code_of(tf.load_seeds, self.paths), code)
                self.assertEqual(self.paths.seeds.read_bytes(), raw, "틀린 파일은 읽지만 고치거나 덮어쓰지 않는다")

    def test_profiles_and_calendar_are_just_as_strict(self):
        good = channels.profiles_to_dict(channels.default_profiles())
        missing_channel = {**good, "profiles": good["profiles"][:-1]}
        extra_field = {**good, "profiles": [{**good["profiles"][0], "sneaky": 1}, *good["profiles"][1:]]}
        wrong_sum = {**good, "profiles": [{**good["profiles"][0], "evergreen_pct": 10}, *good["profiles"][1:]]}
        for name, data in (("채널이 빠짐", missing_channel), ("모르는 칸", extra_field), ("비율의 합이 100 이 아님", wrong_sum), ("schema 가 다름", {**good, "schema": 9})):
            with self.subTest(case=name):
                self.put(self.paths.profiles, data)
                self.assertEqual(code_of(tf.load_profiles, self.paths), "CONTENT_INVALID")
        for name, data in (("schema 가 다름", {"schema": 2, "entries": []}), ("모르는 칸", {"schema": 1, "entries": [], "x": 1}), ("항목의 칸이 틀림", {"schema": 1, "entries": [{"entry_id": "a"}]})):
            with self.subTest(case=name):
                self.put(self.paths.calendar, data)
                self.assertEqual(code_of(tf.load_calendar, self.paths), "CONTENT_INVALID")

    def test_a_folder_in_place_of_a_file_and_a_huge_file_are_refused(self):
        self.paths.seeds.mkdir()
        self.assertEqual(code_of(tf.load_seeds, self.paths), "TOPIC_FILE_INVALID")
        self.paths.seeds.rmdir()
        real = tf.MAX_FILE_BYTES
        tf.MAX_FILE_BYTES = 10
        self.addCleanup(setattr, tf, "MAX_FILE_BYTES", real)
        self.put(self.paths.seeds, seeds.seeds_to_dict([ts.example_seed()]))
        self.assertEqual(code_of(tf.load_seeds, self.paths), "TOPIC_FILE_INVALID")

    def test_the_error_names_the_file_but_not_the_content(self):
        secret_like = "AI" + "za" + "C" * 35
        self.paths.seeds.write_text('{"schema": 1, "seeds": [{"seed_id": "x", "major": "' + secret_like + '"}]}', encoding="utf-8")
        try:
            tf.load_seeds(self.paths)
        except AppError as error:
            self.assertEqual(error.code, "CONTENT_INVALID")
            self.assertNotIn(secret_like, str(error.slots))
        else:
            self.fail("틀린 씨앗 파일을 읽었다")


if __name__ == "__main__":
    unittest.main()
