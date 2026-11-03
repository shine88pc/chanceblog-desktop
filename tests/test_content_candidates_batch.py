"""보관함의 후보 묶음 저장(`Store.add_candidates`)과 번호 목록(`Store.candidate_ids`) 시험 — 후보 명령줄 묶음(b)이 더한 두 함수다('a' 묶음의 후보 저장 규칙은 그대로이고 그 시험도 그대로다).

지키는 것:
  1) `add_candidates` 는 쓰기 잠금을 잡은 **뒤** 지금 있는 후보들을 읽어 `plan` 에 넘기고, 그것이 돌려준 새 후보들을 **한 트랜잭션**으로 저장한다 —
     읽는 것과 저장하는 것 사이에 다른 프로세스가 끼어들 수 없고(같은 후보를 두 곳에서 동시에 더해도 겹치지 않는다), 하나라도 안 되면 하나도 저장되지 않는다.
  2) 새 후보만 더한다(이미 있는 번호는 STORE_CONFLICT), 후보가 아닌 것·값이 틀린 것은 CANDIDATE_INVALID, 깨진 후보가 있으면 CANDIDATE_CORRUPT(`list_candidates` 와 같다),
     읽기 전용으로 연 보관함은 거절한다. 거절·실패한 뒤에도 보관함은 다음 일을 받을 수 있다(열린 트랜잭션이 남지 않는다).
  3) `candidate_ids` 는 자료를 읽지 않고 모든 후보의 번호를 오름차순으로 준다 — 깨져서 목록을 막는 후보도 나온다(그 후보를 번호 앞부분으로 찾아 지울 때).
네트워크 없이 임시 폴더에서 돈다.
"""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chanceblog_desktop.content import Candidate  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from store_v1 import make_v1_file  # noqa: E402

NOW = "2026-11-02T03:00:00Z"


def cand(candidate_id, topic="겨울철 보일러 점검 방법", keyword="보일러 점검"):
    return Candidate.new(topic, keyword, ("naver_a",), candidate_id=candidate_id, now=NOW)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "chanceblog.db"
        self.store = Store.open(self.path)
        self.addCleanup(self.store.close)

    def refused(self, code, callable_, *args):
        with self.assertRaises(AppError) as caught:
            callable_(*args)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        return caught.exception

    def ids(self):
        return [item.candidate_id for item in self.store.list_candidates()]

    def break_row(self, candidate_id):
        with closing(sqlite3.connect(str(self.path), isolation_level=None)) as db:
            db.execute("UPDATE candidates SET data = '{\"손\": 1}' WHERE candidate_id = ?", (candidate_id,))


class AddCandidatesTest(Base):
    def test_the_new_candidates_are_all_saved_in_the_order_given_and_returned(self):
        saved = self.store.add_candidates(lambda existing: [cand("n1", "첫째 주제", "키워드 하나"), cand("n2", "둘째 주제", "키워드 둘")])
        self.assertEqual([item.candidate_id for item in saved], ["n1", "n2"])
        self.assertIsInstance(saved, tuple)
        self.assertEqual(sorted(self.ids()), ["n1", "n2"])
        self.assertEqual(self.store.load_candidate("n2").topic, "둘째 주제")
        self.assertEqual(self.store.check(), [])

    def test_the_plan_is_given_the_candidates_that_are_there_already_as_candidates(self):
        self.store.save_candidate(cand("old1", "이미 있는 주제", "이미 키워드"))
        seen = []
        self.store.add_candidates(lambda existing: seen.append(existing) or [])
        self.assertEqual(len(seen), 1)
        self.assertEqual([(item.candidate_id, item.topic) for item in seen[0]], [("old1", "이미 있는 주제")])
        self.assertIsInstance(seen[0][0], Candidate)

    def test_an_empty_plan_saves_nothing_and_returns_an_empty_tuple(self):
        self.assertEqual(self.store.add_candidates(lambda existing: ()), ())
        self.assertEqual(self.ids(), [])
        self.store.save_candidate(cand("after1"))                                          # 잠금이 남지 않았다
        self.assertEqual(self.ids(), ["after1"])

    def test_the_plan_runs_while_the_write_lock_is_held_so_nobody_can_slip_in_between_the_check_and_the_save(self):
        outcomes = []

        def plan(existing):
            with closing(sqlite3.connect(str(self.path), timeout=0, isolation_level=None)) as other:
                try:
                    other.execute("BEGIN IMMEDIATE")
                    outcomes.append("다른 연결이 쓰기 잠금을 잡았다")
                    other.execute("ROLLBACK")
                except sqlite3.OperationalError as error:
                    outcomes.append(str(error))
            return [cand("n1")]

        self.store.add_candidates(plan)
        self.assertEqual(outcomes, ["database is locked"], "계획을 세우는 동안 다른 연결은 쓰지 못한다")
        self.assertEqual(self.ids(), ["n1"])

    def test_one_bad_candidate_among_good_ones_saves_none_of_them(self):
        for bad in (object(), {"candidate_id": "x"}, "후보"):
            with self.subTest(bad=type(bad).__name__):
                error = self.refused("CANDIDATE_INVALID", self.store.add_candidates, lambda existing, bad=bad: [cand("good1"), bad, cand("good2", "다른 주제", "다른 키워드")])
                self.assertIn("후보", error.slots["항목"])
                self.assertEqual(self.ids(), [], "앞의 좋은 후보도 저장되지 않았다")
        self.store.save_candidate(cand("after1"))
        self.assertEqual(self.ids(), ["after1"], "거절된 뒤에도 보관함은 다음 일을 받는다")

    def test_a_number_that_is_already_there_is_refused_and_nothing_else_is_saved(self):
        self.store.save_candidate(cand("same1", "원래 주제", "원래 키워드"))
        error = self.refused("STORE_CONFLICT", self.store.add_candidates, lambda existing: [cand("new1", "새 주제", "새 키워드"), cand("same1", "덮어쓸 주제", "덮어쓸 키워드")])
        self.assertIn("같은 번호", error.detail)
        self.assertEqual(self.ids(), ["same1"], "새 후보도 저장되지 않았다")
        self.assertEqual(self.store.load_candidate("same1").topic, "원래 주제", "있던 후보는 덮어쓰이지 않았다")

    def test_the_same_number_twice_in_one_plan_is_refused_too(self):
        self.refused("STORE_CONFLICT", self.store.add_candidates, lambda existing: [cand("twin1"), cand("twin1", "다른 주제", "다른 키워드")])
        self.assertEqual(self.ids(), [])

    def test_an_error_inside_the_plan_rolls_everything_back_and_leaves_no_transaction_open(self):
        with self.assertRaises(ZeroDivisionError):
            self.store.add_candidates(lambda existing: 1 / 0)
        self.assertEqual(self.ids(), [])
        self.store.save_candidate(cand("after1"))
        self.assertEqual(self.ids(), ["after1"])

    def test_a_plan_that_fails_after_some_were_taken_from_an_iterator_still_saves_nothing(self):
        def plan(existing):
            yield cand("n1")
            yield cand("n2", "둘째 주제", "키워드 둘")
            raise AppError("DISK_FULL", detail="시험용")

        self.refused("DISK_FULL", self.store.add_candidates, plan)
        self.assertEqual(self.ids(), [])

    def test_a_corrupt_candidate_blocks_the_batch_like_the_list_and_the_plan_is_not_asked(self):
        self.store.save_candidate(cand("bad1", "깨질 후보", "키워드 하나"))
        self.break_row("bad1")
        asked = []
        error = self.refused("CANDIDATE_CORRUPT", self.store.add_candidates, lambda existing: asked.append(existing) or [cand("n1", "새 주제", "새 키워드")])
        self.assertEqual((error.slots["번호"], asked), ("bad1", []))
        self.assertEqual(self.store.candidate_ids(), ("bad1",))

    def test_a_store_opened_read_only_refuses_without_asking_the_plan(self):
        self.store.save_candidate(cand("old1"))
        asked = []
        with Store.open(self.path, migrate=False) as reading:
            self.refused("UNEXPECTED_ERROR", reading.add_candidates, lambda existing: asked.append(existing) or [cand("n1", "새 주제", "새 키워드")])
        self.assertEqual((asked, self.ids()), ([], ["old1"]))

    def test_each_new_candidate_is_checked_once_more_before_it_goes_in(self):
        broken = cand("n2", "둘째 주제", "키워드 둘")
        object.__setattr__(broken, "topic", "")                                              # 만든 뒤 망가진 후보(고정된 자료를 억지로 고쳤다)
        self.refused("CANDIDATE_INVALID", self.store.add_candidates, lambda existing: [cand("n1"), broken])
        self.assertEqual(self.ids(), [])


class CandidateIdsTest(Base):
    def test_every_number_comes_sorted_and_without_reading_the_data(self):
        self.assertEqual(self.store.candidate_ids(), ())
        for candidate_id in ("ccc1", "aaa1", "bbb1"):
            self.store.save_candidate(cand(candidate_id, f"주제 {candidate_id}", f"키워드 {candidate_id}"))
        self.assertEqual(self.store.candidate_ids(), ("aaa1", "bbb1", "ccc1"))
        self.assertIsInstance(self.store.candidate_ids(), tuple)

    def test_a_corrupt_candidate_that_blocks_the_list_still_has_its_number_listed(self):
        for candidate_id in ("aaa1", "bbb1"):
            self.store.save_candidate(cand(candidate_id, f"주제 {candidate_id}", f"키워드 {candidate_id}"))
        self.break_row("bbb1")
        self.refused("CANDIDATE_CORRUPT", self.store.list_candidates)
        self.assertEqual(self.store.candidate_ids(), ("aaa1", "bbb1"))

    def test_a_read_only_old_structure_file_has_no_candidates_to_list(self):
        old = self.dir / "old.db"
        make_v1_file(old)
        with Store.open(old, migrate=False) as reading:
            self.assertTrue(reading.needs_migration)
            self.assertEqual(reading.candidate_ids(), ())


if __name__ == "__main__":
    unittest.main()
