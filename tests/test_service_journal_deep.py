"""글 올리기 기록(`service/journal.py`)을 읽다가 깊이 겹친 JSON 의 `RecursionError` 가 그대로 새지 않는 것을 지키는 시험 — AS-S1 참고-18(결정 D-612).

감사: `Journal.read` 는 `(OSError, ValueError)` 만 잡아 아주 깊게 겹친 JSON 에서 `RecursionError` 가 원시 예외로 새어 나갔다(같은 부류의 `context.py:204`·`connections.py:351` 는 이미 잡는다). 이 기록은 앱만 쓰는 파일이고
백업 대상도 아니라 조작 경로는 없지만, 읽기가 거절하는 방식은 한 가지여야 한다 — 쉬운 `SETTINGS_INVALID`(어느 파일인지 이름만, 내용 없음).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import journal  # noqa: E402


class DeepJournalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.journal = journal.Journal(self.folder)

    def put(self, raw):
        (self.folder / "p1.json").write_bytes(raw)

    def test_a_deeply_nested_record_is_refused_as_a_plain_settings_error_without_the_text(self):
        for label, raw in {"리스트 10만 단": b"[" * 100_000 + b"]" * 100_000, "딕셔너리 10만 단": b'{"a":' * 100_000 + b"1" + b"}" * 100_000, "리스트 1100 단": b"[" * 1100 + b"]" * 1100}.items():
            with self.subTest(label=label):
                self.put(raw)
                with self.assertRaises(AppError) as caught:
                    self.journal.read("p1")
                self.assertEqual(caught.exception.code, "SETTINGS_INVALID")
                self.assertEqual(caught.exception.slots, {"파일": "p1.json"})

    def test_a_recursion_error_from_the_reader_itself_is_handled_the_same_way(self):
        self.put(b"{}")
        with mock.patch.object(journal.json, "loads", side_effect=RecursionError("maximum recursion depth exceeded")):
            with self.assertRaises(AppError) as caught:
                self.journal.read("p1")
        self.assertEqual(caught.exception.code, "SETTINGS_INVALID")
        self.assertIn("RecursionError", caught.exception.detail)

    def test_missing_unreadable_and_good_records_behave_as_before(self):
        self.assertIsNone(self.journal.read("p1"))
        self.put(b"not json")
        with self.assertRaises(AppError) as caught:
            self.journal.read("p1")
        self.assertEqual(caught.exception.code, "SETTINGS_INVALID")
        self.assertFalse(self.journal.missing("p1"), "읽을 수 없는 기록은 '없다' 가 아니라 '있는데 못 읽는다'")
        record = journal.PublishRecord("p1", ss.KO_PATH, "a" * 40, "b" * 40, journal.STAGES[0])
        self.journal.write(record)
        self.assertEqual(self.journal.read("p1"), record)
        self.assertEqual(json.loads((self.folder / "p1.json").read_text(encoding="utf-8"))["project_id"], "p1")


if __name__ == "__main__":
    unittest.main()
