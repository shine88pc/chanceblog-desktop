"""주제 후보 보관함 시험 — 후보 저장·불러오기·목록·상태 이동·확인 있는 삭제·같은 블로그 재선택 조회, 스키마 판 2 로 올리기(진짜 SQLite 파일), 손상 점검.

지키는 것:
  1) 저장한 후보가 글자 하나 안 틀리고 돌아오고, 낮은 판(또는 같은 판의 다른 내용)으로는 덮어쓰지 못하며, 거절된 일은 아무것도 바꾸지 않고 열린 트랜잭션도 남기지 않는다.
  2) 상태 이동은 표(`TRANSITIONS`)대로만 되고 읽고 바꾸고 쓰는 것이 한 트랜잭션이라 동시에 해도 서로의 변경을 잃지 않는다. 삭제는 확인(`confirm=True`)이 있어야만 한다.
  3) 같은 핵심 키워드(띄어쓰기·기호 무시)를 같은 블로그용으로 기준 일수 안에 '선택'해 둔 후보를 찾아 준다 — 블로그마다 따로, '선택됨' 인 후보만, 경계는 정확히 기준 일수째까지.
  4) 연결한 글을 지우면 후보는 남고 연결만 끊긴다. 없는 글에는 연결할 수 없다.
  5) 옛 판(1) 파일은 사본을 두고 한 트랜잭션으로 올라가고 중간에 실패하면 원래대로다. 더 새로운 파일은 한 바이트도 바꾸지 않고 거절한다.
  6) 사람이 고치거나 깨진 행은 믿지 않고 STORE_CORRUPT 로 알리며 전체 점검이 짚어 낸다.
네트워크 없이 임시 폴더에서 돈다.
"""
import dataclasses
import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))             # tests/store_v1.py

from chanceblog_desktop.content import Candidate, ContentProject  # noqa: E402
from chanceblog_desktop.content import store as store_module  # noqa: E402
from chanceblog_desktop.content.candidates import STATUS_KO, STATUSES, TRANSITIONS  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.content.status import PLATFORMS  # noqa: E402
from chanceblog_desktop.content.store import APPLICATION_ID, SCHEMA_VERSION, Store  # noqa: E402
from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.errors.render import UNKNOWN_SLOT  # noqa: E402
from store_v1 import make_v1_file  # noqa: E402

BASE = datetime(2026, 11, 2, 3, 0, 0)
NOW = "2026-11-02T03:00:00Z"
DAY = "2026-11-01"
FULL = dict(sub_keywords=("보일러 에러", "난방비 절약"), blogs=("naver_a", "naver_b", "github_pages"), post_type="문제 해결형", search_demand=12000, related_blog_results=34500,
            trend="상승", mobile_share=72.5, seasonality=(11, 12, 1, 2), duplicate=False, profile_fit=81, priority=76.5, keyword_opportunity=64,
            reason="겨울 전에 찾는 사람이 늘고 관련 글이 많지 않습니다.", data_date=DAY)


def at(**delta):
    """기준 시각(2026-11-02 03:00 UTC)에서 얼마 뒤(또는 앞)인지로 시각 글을 만든다."""
    return (BASE + timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def cand(candidate_id="c1", **changes):
    base = {"topic": "겨울철 보일러 점검 방법", "keyword": "보일러 점검", "blogs": ("naver_a",), "now": NOW}
    base.update(changes)
    return Candidate.new(base.pop("topic"), base.pop("keyword"), base.pop("blogs"), candidate_id=candidate_id, **base)


def project(project_id="p1"):
    return ContentProject.new("주제가 분명한 제목", "본문 첫 문단입니다.\n\n둘째 문단입니다.", project_id=project_id, now=NOW)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CandidateStoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)                    # 나중에 등록한 것(저장소 닫기)이 먼저 돈다
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "data" / "chanceblog.db"

    def open(self, path=None, **kwargs):
        store = Store.open(self.path if path is None else path, **kwargs)
        self.addCleanup(store.close)
        return store

    def refuses(self, code, callable_, *args, **kwargs):
        """AppError 의 코드를 확인하고, 사용자 문구의 자리표시자가 모두 채워지는지(알 수 없음 없이)도 본다."""
        with self.assertRaises(AppError) as caught:
            callable_(*args, **kwargs)
        error = caught.exception
        self.assertEqual(error.code, code, error.detail)
        shown = error.rendered()
        self.assertNotIn(UNKNOWN_SLOT, shown.message + shown.action, f"{code}: 자리표시자가 비었다")
        return error

    def raw(self, path=None):
        connection = sqlite3.connect(str(self.path if path is None else path), isolation_level=None)
        self.addCleanup(connection.close)
        return connection

    def select(self, store, candidate_id, blog, when):
        return store.set_candidate_status(candidate_id, "SELECTED", blog=blog, now=when)


class SaveLoadTest(CandidateStoreCase):
    def test_every_field_survives_the_trip_and_a_reopen(self):
        store = self.open()
        store.save(project("p1"))
        item = cand(project_id="p1", **FULL).moved("SELECTED", blog="naver_a", now=at(hours=1))
        store.save_candidate(item)
        loaded = store.load_candidate("c1")
        self.assertEqual(loaded, item)
        self.assertEqual(loaded.to_dict(), item.to_dict())
        self.assertIsNot(loaded, item)
        store.close()
        with Store.open(self.path) as again:
            self.assertEqual(again.load_candidate("c1"), item)
            self.assertEqual(again.check(), [])

    def test_saving_again_updates_in_place_and_keeps_one_row(self):
        store = self.open()
        item = cand()
        store.save_candidate(item)
        edited = item.edited(search_demand=500, data_date=DAY, now=at(hours=1))
        store.save_candidate(edited)
        self.assertEqual(self.raw().execute("SELECT COUNT(*), MAX(revision), MAX(updated_at) FROM candidates").fetchone(), (1, 2, at(hours=1)))
        self.assertEqual(store.load_candidate("c1").search_demand, 500)
        self.assertEqual(store.check(), [])

    def test_the_row_has_the_columns_the_list_uses_and_the_project_link_only_in_its_column(self):
        store = self.open()
        store.save(project("p1"))
        store.save_candidate(cand(keyword="Boiler 점검!", project_id="p1").moved("HOLD", now=at(hours=2)))
        row = self.raw().execute("SELECT candidate_id, keyword_key, status, project_id, revision, created_at, updated_at, data FROM candidates").fetchone()
        self.assertEqual(row[:7], ("c1", "boiler점검", "HOLD", "p1", 2, NOW, at(hours=2)))
        data = json.loads(row[7])
        self.assertNotIn("project_id", data, "연결한 글은 열이 기준이다 — 자료에 또 적지 않는다")
        self.assertEqual(data["status"], "HOLD")
        self.assertIn("겨울철 보일러 점검 방법", row[7], "한글은 \\uXXXX 로 풀지 않고 그대로 저장한다")

    def test_the_list_is_newest_first_then_by_id(self):
        store = self.open()
        for candidate_id, when in (("b", at(hours=1)), ("a", at(hours=1)), ("c", at(hours=2)), ("d", NOW)):
            store.save_candidate(cand(candidate_id, now=when))
        self.assertEqual([item.candidate_id for item in store.list_candidates()], ["c", "a", "b", "d"])

    def test_the_list_can_be_filtered_by_status(self):
        store = self.open()
        for number, status in enumerate(STATUSES):
            store.save_candidate(cand(f"c{number}", keyword=f"키워드{number}", status=status))
        store.save_candidate(cand("extra", keyword="키워드 하나 더", status="HOLD"))
        self.assertEqual(len(store.list_candidates()), 6)
        for status in STATUSES:
            with self.subTest(status=status):
                found = store.list_candidates(status=status)
                self.assertTrue(found and all(item.status == status for item in found))
                self.assertEqual(len(found), 2 if status == "HOLD" else 1)
        for bad in ("DRAFTING", "new", "", 5, ["NEW"]):
            with self.subTest(bad=repr(bad)):
                self.refuses("CANDIDATE_INVALID", store.list_candidates, status=bad)

    def test_the_list_can_be_filtered_by_recommended_blog_and_by_both(self):
        store = self.open()
        store.save_candidate(cand("a", keyword="가", blogs=("naver_a",)))
        store.save_candidate(cand("ab", keyword="나", blogs=("naver_a", "naver_b"), status="HOLD"))
        store.save_candidate(cand("g", keyword="다", blogs=("github_pages", "blogger_ko")))
        self.assertEqual(sorted(item.candidate_id for item in store.list_candidates(blog="naver_a")), ["a", "ab"])
        self.assertEqual([item.candidate_id for item in store.list_candidates(blog="naver_b")], ["ab"])
        self.assertEqual(sorted(item.candidate_id for item in store.list_candidates(blog="github_pages")), ["g"])
        self.assertEqual(store.list_candidates(blog="blogger_en"), [])
        self.assertEqual([item.candidate_id for item in store.list_candidates(status="HOLD", blog="naver_a")], ["ab"])
        self.assertEqual(store.list_candidates(status="NEW", blog="naver_b"), [])
        for bad in ("naver_c", "", "NAVER_A", 5, ["naver_a"]):
            with self.subTest(bad=repr(bad)):
                self.refuses("CANDIDATE_INVALID", store.list_candidates, blog=bad)

    def test_an_empty_store_lists_nothing_and_a_missing_candidate_is_reported_by_number(self):
        store = self.open()
        self.assertEqual(store.list_candidates(), [])
        error = self.refuses("CANDIDATE_NOT_FOUND", store.load_candidate, "nope")
        self.assertIn("nope", error.rendered().message)
        self.refuses("CANDIDATE_NOT_FOUND", store.set_candidate_status, "nope", "REVIEW")
        self.refuses("CANDIDATE_NOT_FOUND", store.delete_candidate, "nope", confirm=True)
        store.save_candidate(cand("c9"))                                    # 거절된 일들이 열린 트랜잭션을 남기지 않는다
        self.assertEqual([item.candidate_id for item in store.list_candidates()], ["c9"])

    def test_bad_numbers_are_refused_by_every_entry_point_before_touching_the_file(self):
        store = self.open()
        for bad in ("", "../x", "a b", "x" * 65, "한글", "c1; DROP TABLE candidates", "c1\n", None, 5, b"c1"):
            for call in (store.load_candidate, store.delete_candidate):
                with self.subTest(call=call.__name__, bad=repr(bad)):
                    self.refuses("CANDIDATE_INVALID", call, bad)
            with self.subTest(call="set_candidate_status", bad=repr(bad)):
                self.refuses("CANDIDATE_INVALID", store.set_candidate_status, bad, "REVIEW")
        self.assertEqual(store.list_candidates(), [])

    def test_text_that_looks_like_sql_is_just_text(self):
        store = self.open()
        evil = "x'); DROP TABLE candidates; --"
        store.save_candidate(cand(topic=evil, keyword="' OR '1'='1", reason=evil))
        loaded = store.load_candidate("c1")
        self.assertEqual((loaded.topic, loaded.keyword, loaded.reason), (evil, "' OR '1'='1", evil))
        self.assertEqual(len(store.list_candidates()), 1)

    def test_a_save_that_is_refused_leaves_the_stored_copy_untouched(self):
        store = self.open()
        store.save_candidate(cand())
        before = store.load_candidate("c1")
        tampered = cand("c1")
        object.__setattr__(tampered, "status", "NOPE")                       # 생성 뒤에 몰래 값을 망가뜨려도 저장 직전에 다시 검사한다
        for bad in (tampered, {"candidate_id": "c1"}, None, project(), "c1"):
            with self.subTest(bad=type(bad).__name__):
                self.refuses("CANDIDATE_INVALID", store.save_candidate, bad)
        self.assertEqual(store.load_candidate("c1"), before)
        self.assertEqual(self.raw().execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 1)

    def test_a_candidate_of_every_status_comes_back_the_same(self):
        store = self.open()
        for number, status in enumerate(STATUSES):
            item = cand(f"c{number}", keyword=f"키워드{number}", status=status, **FULL)
            store.save_candidate(item)
            self.assertEqual(store.load_candidate(f"c{number}"), item, status)

    def test_a_hundred_and_fifty_candidates_round_trip(self):
        store = self.open()
        for number in range(150):
            store.save_candidate(cand(f"c{number}", keyword=f"키워드 {number}", topic=f"주제 {number}", now=at(minutes=number)))
        listed = store.list_candidates()
        self.assertEqual((len(listed), listed[0].candidate_id, listed[-1].candidate_id), (150, "c149", "c0"))
        self.assertEqual(store.load_candidate("c75").topic, "주제 75")
        self.assertEqual(store.check(), [])

    def test_several_threads_can_share_one_store(self):
        store = self.open()
        errors = []

        def work(number):
            try:
                item = cand(f"t{number}", keyword=f"키워드 {number}", topic=f"주제 {number}")
                for step in range(10):
                    item = item.edited(search_demand=step, data_date=DAY, now=at(minutes=step))      # 한 번 고칠 때마다 판이 오른다
                    store.save_candidate(item)
                    store.list_candidates()
            except BaseException as error:                      # noqa: BLE001 — 스레드 안의 어떤 실패도 모은다
                errors.append(error)

        threads = [threading.Thread(target=work, args=(number,)) for number in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(item.candidate_id for item in store.list_candidates()), [f"t{number}" for number in range(4)])
        self.assertEqual({item.revision for item in store.list_candidates()}, {11})
        self.assertEqual(store.check(), [])


class ConflictTest(CandidateStoreCase):
    def test_an_older_revision_cannot_overwrite_a_newer_one(self):
        store = self.open()
        first = cand()
        store.save_candidate(first)
        stale = store.load_candidate("c1").edited(reason="오래된 화면에서 고침", now=at(hours=1))                      # 판 2 — 한 번 고친 사본
        second = first.edited(reason="다른 화면에서 고침", now=at(hours=1))                                          # 다른 화면이 먼저 판 2 로 저장하고
        store.save_candidate(second)
        newer = second.edited(reason="한 번 더 고침", now=at(hours=2))                                               # 판 3 까지 저장했다
        store.save_candidate(newer)
        error = self.refuses("STORE_CONFLICT", store.save_candidate, stale)
        self.assertIn(stale.topic, error.rendered().message)
        self.assertEqual(store.load_candidate("c1").reason, "한 번 더 고침")
        store.save_candidate(cand("c2", keyword="다른"))                      # 거절된 저장이 열린 트랜잭션을 남기지 않는다

    def test_the_same_revision_with_other_content_is_a_conflict_but_the_identical_one_is_fine(self):
        store = self.open()
        item = cand()
        store.save_candidate(item)
        store.save_candidate(item)                                           # 같은 것을 다시 저장해도 된다(연결이 끊겨 다시 시도한 경우 등)
        sibling = item.edited(reason="내가 고침", now=at(hours=1))
        other = item.edited(reason="남이 고침", now=at(hours=1))              # 같은 판 2, 다른 내용
        store.save_candidate(sibling)
        store.save_candidate(sibling)
        error = self.refuses("STORE_CONFLICT", store.save_candidate, other)
        self.assertIn(other.topic, error.rendered().message, "같은 판의 충돌 문구에도 어느 후보인지(주제)가 보인다")
        self.assertEqual(store.load_candidate("c1").reason, "내가 고침")

    def test_only_the_very_next_revision_is_accepted_a_jump_is_a_conflict(self):
        """판은 한 번에 한 판씩만 오른다 — 낡은 복사본이 로컬에서 여러 번 고쳐 판이 더 높아져도 저장된 것을 덮어쓰지 못한다(예전에는 '더 높으면 받는다' 였다)."""
        store = self.open()
        item = cand()
        store.save_candidate(item)
        jumped = item.edited(reason="여러 번 고침", now=at(hours=1)).edited(reason="또 고침", now=at(hours=2)).edited(reason="마지막", now=at(hours=3))
        self.assertEqual(jumped.revision, 4)
        for steps in (2, 3):
            skipping = item
            for number in range(steps):
                skipping = skipping.edited(reason=f"건너뛴 고침 {number}", now=at(hours=number + 1))
            self.refuses("STORE_CONFLICT", store.save_candidate, skipping)
        self.refuses("STORE_CONFLICT", store.save_candidate, jumped)
        self.assertEqual((store.load_candidate("c1").revision, store.load_candidate("c1").reason), (1, ""), "거절된 저장은 아무것도 바꾸지 않았다")
        next_one = item.edited(reason="한 번 고침", now=at(hours=1))
        store.save_candidate(next_one)
        self.assertEqual(store.load_candidate("c1").revision, 2)
        store.save_candidate(next_one.edited(reason="또 한 번", now=at(hours=2)))
        self.assertEqual(store.load_candidate("c1").revision, 3)

    def test_a_stale_copy_that_was_edited_twice_locally_cannot_overwrite_a_change_made_elsewhere(self):
        """검증자가 재현한 틈 — 다른 곳이 HOLD 로 옮긴(판 2) 뒤, 낡은 복사본이 로컬에서 두 번 고쳐 판 3 이 되면 충돌 없이 덮어썼다."""
        store = self.open()
        store.save_candidate(cand())
        stale = store.load_candidate("c1")
        store.set_candidate_status("c1", "HOLD", now=at(hours=1))                            # 다른 곳: 판 2, 보류
        mine = stale.edited(topic="내 수정 하나", now=at(hours=2)).edited(topic="내 수정 둘", now=at(hours=3))
        self.assertEqual(mine.revision, 3)
        self.refuses("CANDIDATE_TRANSITION_INVALID", store.save_candidate, mine)               # 판 번호만 보면 '다음 판' 이지만 보류 → 새 후보 는 표에 없다
        self.refuses("STORE_CONFLICT", store.save_candidate, mine, expected_revision=1)        # 내가 고치기 시작한 판(1)과 저장된 판(2)이 다르다 — 이쪽이 정확한 이유다
        kept = store.load_candidate("c1")
        self.assertEqual((kept.status, kept.revision, kept.topic), ("HOLD", 2, "겨울철 보일러 점검 방법"))

    def test_the_expected_revision_closes_the_gap_a_next_number_alone_leaves_when_the_other_side_only_edited_text(self):
        store = self.open()
        store.save_candidate(cand())
        stale = store.load_candidate("c1")                                                   # 내가 불러온 판 1
        store.save_candidate(store.load_candidate("c1").edited(reason="다른 곳에서 이유만 고침", now=at(hours=1)))        # 다른 곳: 판 2
        mine = stale.edited(topic="내 수정 하나", now=at(hours=2)).edited(topic="내 수정 둘", now=at(hours=3))              # 판 3
        self.refuses("STORE_CONFLICT", store.save_candidate, mine, expected_revision=1)
        self.assertEqual((store.load_candidate("c1").reason, store.load_candidate("c1").topic), ("다른 곳에서 이유만 고침", "겨울철 보일러 점검 방법"), "다른 쪽의 변경이 남아 있다")
        fresh = store.load_candidate("c1")
        store.save_candidate(fresh.edited(topic="이번엔 최신에서 고침", now=at(hours=2)).edited(reason="두 번 고침", now=at(hours=3)), expected_revision=fresh.revision)      # 최신에서 시작했으면 두 번 고쳐도 된다
        self.assertEqual((store.load_candidate("c1").revision, store.load_candidate("c1").topic), (4, "이번엔 최신에서 고침"))

    def test_a_bad_expected_revision_or_a_candidate_deleted_since_loading_is_refused(self):
        store = self.open()
        item = cand()
        store.save_candidate(item)
        edited = item.edited(reason="고침", now=at(hours=1))
        for bad in (0, -1, 2, 3, True, 1.0, "1"):
            with self.subTest(bad=repr(bad)):
                self.refuses("CANDIDATE_INVALID", store.save_candidate, edited, expected_revision=bad)
        store.delete_candidate("c1", confirm=True)
        self.refuses("CANDIDATE_NOT_FOUND", store.save_candidate, edited, expected_revision=1)        # 불러온 뒤 지워졌다 — 되살리지 않는다
        self.assertEqual(store.list_candidates(), [])
        store.save_candidate(edited)                                                           # 불러온 판을 말하지 않고 새로 만드는 것은 된다(가져오기 같은 일)
        self.assertEqual(store.load_candidate("c1").revision, 2)

    def test_a_new_candidate_can_be_created_at_any_revision_but_an_existing_one_only_moves_one_step(self):
        store = self.open()
        store.save_candidate(cand("c1").edited(reason="처음부터 판 2", now=at(hours=1)))        # 가져온 후보가 판 2 로 처음 저장되는 일은 막지 않는다
        self.assertEqual(store.load_candidate("c1").revision, 2)
        self.refuses("STORE_CONFLICT", store.save_candidate, cand("c1").edited(reason="a", now=at(hours=1)).edited(reason="b", now=at(hours=2)).edited(reason="c", now=at(hours=3)))

    def test_a_stale_copy_cannot_undo_a_status_change_made_elsewhere(self):
        store = self.open()
        item = cand()
        store.save_candidate(item)
        stale = item.edited(reason="오래된 화면에서 고친 이유", now=at(hours=2))                # 판 2
        store.set_candidate_status("c1", "REJECTED", now=at(hours=1))                          # 다른 곳에서 먼저 — 역시 판 2, '제외'
        self.refuses("STORE_CONFLICT", store.save_candidate, stale)                            # 같은 판인데 내용이 다르다
        store.set_candidate_status("c1", "REVIEW", now=at(hours=3))                            # 판 3
        self.refuses("STORE_CONFLICT", store.save_candidate, stale)                            # 이제는 낮은 판이다
        self.assertEqual((store.load_candidate("c1").status, store.load_candidate("c1").reason), ("REVIEW", ""))


class StatusChangeTest(CandidateStoreCase):
    def test_the_whole_life_of_a_candidate_follows_the_table_and_is_stored_each_time(self):
        store = self.open()
        store.save_candidate(cand())
        path = (("REVIEW", 2), ("SELECTED", 3), ("HOLD", 4), ("REVIEW", 5), ("REJECTED", 6), ("REVIEW", 7), ("HOLD", 8), ("SELECTED", 9), ("REVIEW", 10))
        for number, (status, revision) in enumerate(path, start=1):
            moved = store.set_candidate_status("c1", status, now=at(hours=number))
            self.assertEqual((moved.status, moved.revision, moved.updated_at), (status, revision, at(hours=number)))
            self.assertEqual(store.load_candidate("c1"), moved)
        self.assertEqual(store.check(), [])

    def test_all_25_pairs_follow_the_table_through_the_store_and_a_refused_move_changes_nothing(self):
        store = self.open()
        raw = self.raw()
        for current in STATUSES:
            for requested in STATUSES:
                with self.subTest(current=current, requested=requested):
                    candidate_id = f"{current}-{requested}".lower().replace("_", "-")
                    store.save_candidate(cand(candidate_id, keyword=candidate_id, status=current))
                    before = store.load_candidate(candidate_id)
                    if requested in TRANSITIONS[current]:
                        moved = store.set_candidate_status(candidate_id, requested, now=at(hours=1))
                        self.assertEqual((moved.status, moved.revision), (requested, 2))
                        self.assertEqual(store.load_candidate(candidate_id), moved)
                    else:
                        self.refuses("CANDIDATE_TRANSITION_INVALID", store.set_candidate_status, candidate_id, requested, now=at(hours=1))
                        self.assertEqual(store.load_candidate(candidate_id), before)
                        self.assertEqual(raw.execute("SELECT status, revision FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone(), (current, 1))
        self.assertEqual(store.check(), [])

    def test_a_status_that_is_not_a_candidate_status_is_refused(self):
        store = self.open()
        store.save_candidate(cand())
        for bad in ("DRAFTING", "COPIED", "", "new", None, 5):
            with self.subTest(bad=repr(bad)):
                self.refuses("CANDIDATE_INVALID", store.set_candidate_status, "c1", bad)
        self.assertEqual(store.load_candidate("c1").status, "NEW")

    def test_selecting_records_the_blog_and_the_moment_and_more_blogs_can_be_added(self):
        store = self.open()
        store.save_candidate(cand(blogs=("naver_a", "naver_b")))
        first = self.select(store, "c1", "naver_a", at(hours=1))
        self.assertEqual((first.status, first.selections), ("SELECTED", (("naver_a", at(hours=1)),)))
        second = self.select(store, "c1", "naver_b", at(hours=2))
        self.assertEqual((second.status, second.selections, second.revision), ("SELECTED", (("naver_a", at(hours=1)), ("naver_b", at(hours=2))), 3))
        self.assertEqual(store.load_candidate("c1"), second)
        again = self.select(store, "c1", "naver_a", at(hours=3))
        self.assertEqual(again.selections, (("naver_a", at(hours=3)), ("naver_b", at(hours=2))))
        everything = store.set_candidate_status("c1", "HOLD", now=at(hours=4))
        self.assertEqual(everything.selections, again.selections, "보류로 물려도 선택 기록은 남는다")

    def test_selecting_without_a_blog_picks_every_recommended_blog(self):
        store = self.open()
        store.save_candidate(cand(blogs=("naver_a", "github_pages")))
        picked = store.set_candidate_status("c1", "SELECTED", now=at(hours=1))
        self.assertEqual(picked.selections, (("github_pages", at(hours=1)), ("naver_a", at(hours=1))))
        self.refuses("CANDIDATE_TRANSITION_INVALID", store.set_candidate_status, "c1", "SELECTED", now=at(hours=2))
        self.refuses("CANDIDATE_INVALID", store.set_candidate_status, "c1", "HOLD", blog="naver_a")
        self.assertEqual(store.load_candidate("c1"), picked)

    def test_the_time_defaults_to_now(self):
        store = self.open()
        store.save_candidate(cand())
        moved = store.set_candidate_status("c1", "REVIEW")
        self.assertRegex(moved.updated_at, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(store.load_candidate("c1").updated_at, moved.updated_at)

    def test_two_people_selecting_different_blogs_at_the_same_time_both_get_recorded(self):
        first, second = self.open(busy_seconds=30), self.open(busy_seconds=30)
        first.save_candidate(cand(blogs=("naver_a", "naver_b"), status="REVIEW"))
        gate, errors = threading.Barrier(2), []

        def work(store, blog):
            try:
                gate.wait(10)
                for _ in range(5):
                    store.set_candidate_status("c1", "SELECTED", blog=blog, now=at(hours=1))
            except BaseException as error:                      # noqa: BLE001
                errors.append(error)

        threads = [threading.Thread(target=work, args=(first, "naver_a")), threading.Thread(target=work, args=(second, "naver_b"))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        result = first.load_candidate("c1")
        self.assertEqual(result.selected_blogs, ("naver_a", "naver_b"))
        self.assertEqual(result.revision, 1 + 10, "열 번의 이동이 하나도 사라지지 않았다")
        self.assertEqual(first.check(), [])


class DeleteTest(CandidateStoreCase):
    def test_nothing_is_deleted_without_the_explicit_confirmation(self):
        store = self.open()
        store.save_candidate(cand())
        error = self.refuses("CANDIDATE_CONFIRM_REQUIRED", store.delete_candidate, "c1")
        self.assertIn("c1", error.rendered().message)
        for bad in (False, None, 1, 0, "yes", "True", "true", [], [True], 1.0):
            with self.subTest(confirm=repr(bad)):
                self.refuses("CANDIDATE_CONFIRM_REQUIRED", store.delete_candidate, "c1", confirm=bad)
        self.assertEqual([item.candidate_id for item in store.list_candidates()], ["c1"])

    def test_with_the_confirmation_the_candidate_is_gone_and_the_others_are_not_touched(self):
        store = self.open()
        for candidate_id in ("c1", "c10", "c1x"):
            store.save_candidate(cand(candidate_id, keyword=f"키워드 {candidate_id}"))
        store.delete_candidate("c1", confirm=True)
        self.assertEqual(sorted(item.candidate_id for item in store.list_candidates()), ["c10", "c1x"])
        self.refuses("CANDIDATE_NOT_FOUND", store.load_candidate, "c1")
        self.refuses("CANDIDATE_NOT_FOUND", store.delete_candidate, "c1", confirm=True)
        store.save_candidate(cand("c2", keyword="다른"))                      # 열린 트랜잭션이 남지 않았다

    def test_a_deleted_candidate_no_longer_counts_for_the_reuse_warning(self):
        store = self.open()
        store.save_candidate(cand())
        self.select(store, "c1", "naver_a", NOW)
        self.assertEqual(len(store.recent_selections("보일러 점검", "naver_a", 90, now=at(days=1))), 1)
        store.delete_candidate("c1", confirm=True)
        self.assertEqual(store.recent_selections("보일러 점검", "naver_a", 90, now=at(days=1)), [])

    def test_deleting_a_candidate_leaves_its_project_with_the_history_and_the_draft(self):
        store = self.open()
        store.save(project("p1"))
        store.save_draft("p1", "초안 글")
        store.save_candidate(cand(project_id="p1"))
        store.delete_candidate("c1", confirm=True)
        self.assertEqual(store.load("p1").project_id, "p1")
        self.assertEqual(store.history("p1"), [(1, NOW)])
        self.assertEqual(store.load_draft("p1").text, "초안 글")


class ProjectLinkTest(CandidateStoreCase):
    def test_a_candidate_can_be_linked_to_a_project_that_exists(self):
        store = self.open()
        store.save(project("p1"))
        store.save_candidate(cand(project_id="p1"))
        self.assertEqual(store.load_candidate("c1").project_id, "p1")
        store.save_candidate(cand("c2", keyword="다른 키워드", project_id="p1"))
        self.assertEqual({item.candidate_id for item in store.list_candidates() if item.project_id == "p1"}, {"c1", "c2"}, "한 글에 여러 후보가 이어질 수 있다")

    def test_linking_to_a_missing_project_is_refused_and_nothing_is_stored(self):
        store = self.open()
        error = self.refuses("CONTENT_NOT_FOUND", store.save_candidate, cand(project_id="nope"))
        self.assertNotIn("nope", error.rendered().message, "번호 모양(16진수 8자 이하)이 아닌 글 번호는 오류 문구에 되풀이하지 않는다")
        self.assertIn("「(입력한 번호)」", error.rendered().message)
        self.assertIn("「ab12cd34」", self.refuses("CONTENT_NOT_FOUND", store.save_candidate, cand("c9", keyword="다른 키워드", project_id="ab12cd34")).rendered().message, "번호 모양이면 그대로 알린다")
        self.assertEqual(store.list_candidates(), [])
        store.save_candidate(cand())
        self.refuses("CONTENT_NOT_FOUND", store.save_candidate, store.load_candidate("c1").edited(project_id="nope", now=at(hours=1)))
        self.assertIsNone(store.load_candidate("c1").project_id)
        self.assertEqual(store.load_candidate("c1").revision, 1)

    def test_deleting_the_project_cuts_the_link_but_keeps_the_candidate_exactly_as_it_was(self):
        store = self.open()
        store.save(project("p1"))
        store.save(project("p2"))
        store.save_candidate(cand("c1", project_id="p1", keyword="가"))
        store.save_candidate(cand("c2", project_id="p1", keyword="나"))
        store.save_candidate(cand("c3", project_id="p2", keyword="다"))
        picked = self.select(store, "c1", "naver_a", at(hours=1))
        store.delete("p1")
        after = store.load_candidate("c1")
        self.assertIsNone(after.project_id)
        self.assertEqual(dict(after.to_dict(), project_id="p1"), picked.to_dict(), "연결 말고는 아무것도 달라지지 않았다(상태·선택 기록·판 번호)")
        self.assertIsNone(store.load_candidate("c2").project_id)
        self.assertEqual(store.load_candidate("c3").project_id, "p2", "다른 글의 후보는 그대로다")
        self.assertEqual(store.check(), [])

    def test_a_stale_copy_that_still_holds_the_deleted_link_cannot_bring_it_back(self):
        store = self.open()
        store.save(project("p1"))
        store.save_candidate(cand(project_id="p1"))
        stale = store.load_candidate("c1")
        store.delete("p1")
        self.refuses("STORE_CONFLICT", store.save_candidate, stale)
        self.assertIsNone(store.load_candidate("c1").project_id)

    def test_the_link_can_be_made_again_after_the_project_comes_back(self):
        store = self.open()
        store.save(project("p1"))
        store.save_candidate(cand(project_id="p1"))
        store.delete("p1")
        store.save(project("p1"))
        relinked = store.load_candidate("c1").edited(project_id="p1", now=at(hours=1))
        store.save_candidate(relinked)
        self.assertEqual(store.load_candidate("c1"), relinked)
        self.assertEqual(relinked.revision, 2)

    def test_the_foreign_key_is_enforced_by_the_file_itself(self):
        store = self.open()
        store.save(project("p1"))
        store.save_candidate(cand(project_id="p1"))
        with self.assertRaises(sqlite3.IntegrityError):
            store._db.execute("UPDATE candidates SET project_id = 'ghost'")
        rows = {row[2]: row for row in store._db.execute("PRAGMA foreign_key_list(candidates)")}
        self.assertEqual(rows["projects"][3:7], ("project_id", "project_id", "NO ACTION", "SET NULL"))


class ReuseWarningTest(CandidateStoreCase):
    def prepare(self, store, *, keyword="보일러 점검", blogs=("naver_a",), blog="naver_a", when=NOW, candidate_id="c1"):
        store.save_candidate(cand(candidate_id, keyword=keyword, blogs=blogs, now=min(when, NOW)))          # 고친 시각이 만든 시각보다 앞설 수 없으니 옛날에 고른 것은 옛날에 만든 후보다
        return self.select(store, candidate_id, blog, when)

    def found(self, store, days, *, now, keyword="보일러 점검", blog="naver_a", **kwargs):
        return [item.candidate_id for item in store.recent_selections(keyword, blog, days, now=now, **kwargs)]

    def test_the_same_keyword_for_the_same_blog_inside_the_window_is_found(self):
        store = self.open()
        self.prepare(store)
        self.assertEqual(self.found(store, 90, now=at(days=30)), ["c1"])
        self.assertEqual(self.found(store, 90, now=at(seconds=1)), ["c1"])
        item = store.recent_selections("보일러 점검", "naver_a", 90, now=at(days=1))[0]
        self.assertEqual((item.candidate_id, item.selected_time("naver_a")), ("c1", NOW))

    def test_the_window_edge_is_exactly_the_given_number_of_days(self):
        store = self.open()
        self.prepare(store)
        self.assertEqual(self.found(store, 90, now=at(days=89, hours=23, minutes=59, seconds=59)), ["c1"])
        self.assertEqual(self.found(store, 90, now=at(days=90)), ["c1"], "정확히 90일째까지는 안에 든다")
        self.assertEqual(self.found(store, 90, now=at(days=90, seconds=1)), [])
        self.assertEqual(self.found(store, 30, now=at(days=30)), ["c1"])
        self.assertEqual(self.found(store, 30, now=at(days=30, seconds=1)), [])
        self.assertEqual(self.found(store, 1, now=at(days=1)), ["c1"])
        self.assertEqual(self.found(store, 3650, now=at(days=3650)), ["c1"])

    def test_zero_days_means_no_warning_at_all(self):
        store = self.open()
        self.prepare(store)
        self.assertEqual(self.found(store, 0, now=NOW), [])
        self.assertEqual(self.found(store, 0, now=at(seconds=1)), [])

    def test_the_window_follows_the_blog_profile_setting(self):
        store = self.open()
        self.prepare(store)
        for days, expected in ((NaverProfile("naver_a", "A", "https://blog.naver.com/a").topic_reuse_days, ["c1"]), (30, []), (45, ["c1"])):
            with self.subTest(days=days):
                profile = NaverProfile("naver_a", "A", "https://blog.naver.com/a", topic_reuse_days=days)
                self.assertEqual(self.found(store, profile.topic_reuse_days, now=at(days=40)), expected)

    def test_another_blog_or_another_keyword_is_not_a_repeat(self):
        store = self.open()
        self.prepare(store)
        self.assertEqual(self.found(store, 90, now=at(days=1), blog="naver_b"), [])
        self.assertEqual(self.found(store, 90, now=at(days=1), blog="github_pages"), [])
        self.assertEqual(self.found(store, 90, now=at(days=1), keyword="보일러 수리"), [])
        self.assertEqual(self.found(store, 90, now=at(days=1), keyword="보일러"), [])

    def test_spacing_case_width_and_punctuation_do_not_hide_a_repeat(self):
        store = self.open()
        self.prepare(store, keyword="iPhone 15 케이스")
        for same in ("iphone15케이스", "ＩＰＨＯＮＥ １５ 케이스", "iPhone-15 케이스!", "  IPHONE   15   케이스 "):
            with self.subTest(same=same):
                self.assertEqual(self.found(store, 90, now=at(days=1), keyword=same), ["c1"])
        self.assertEqual(self.found(store, 90, now=at(days=1), keyword="iPhone 14 케이스"), [])

    def test_only_candidates_that_are_selected_right_now_count(self):
        store = self.open()
        self.prepare(store)
        for status in ("HOLD", "REVIEW"):
            with self.subTest(status=status):
                store.set_candidate_status("c1", status, now=at(hours=1))
                self.assertEqual(self.found(store, 90, now=at(days=1)), [], "쓰지 않기로 물린 것은 세지 않는다")
                store.set_candidate_status("c1", "SELECTED", blog="naver_a", now=at(days=2))
                self.assertEqual(self.found(store, 90, now=at(days=3)), ["c1"], "다시 고르면 다시 센다")
        store.set_candidate_status("c1", "HOLD", now=at(days=4))
        store.set_candidate_status("c1", "REJECTED", now=at(days=5))
        self.assertEqual(self.found(store, 90, now=at(days=6)), [])
        for status in ("REVIEW", "HOLD", "REJECTED"):                    # 새 후보에는 선택 기록이 있을 수 없다 — 나머지 물린 상태들만
            store.save_candidate(cand(f"x-{status}", keyword="보일러 점검", status=status, selections=[("naver_a", at(hours=2))]))
        self.assertEqual(self.found(store, 90, now=at(days=1)), [], "선택됨이 아니면 선택 기록이 남아 있어도 세지 않는다")

    def test_the_candidate_being_chosen_now_is_left_out_of_its_own_warning(self):
        store = self.open()
        self.prepare(store)
        self.assertEqual(self.found(store, 90, now=at(days=1), exclude="c1"), [])
        self.prepare(store, candidate_id="c2", when=at(hours=5))
        self.assertEqual(sorted(self.found(store, 90, now=at(days=1))), ["c1", "c2"])
        self.assertEqual(self.found(store, 90, now=at(days=1), exclude="c1"), ["c2"])

    def test_the_blog_is_judged_by_where_it_was_chosen_not_by_where_it_was_recommended(self):
        store = self.open()
        self.prepare(store, blogs=("naver_a", "naver_b"), blog="naver_a")
        self.assertEqual(self.found(store, 90, now=at(days=1), blog="naver_b"), [], "추천만 되고 고르지 않은 블로그는 쓴 것이 아니다")
        self.select(store, "c1", "naver_b", at(days=5))
        self.assertEqual(self.found(store, 90, now=at(days=6), blog="naver_b"), ["c1"])
        self.assertEqual(self.found(store, 4, now=at(days=6), blog="naver_a"), [], "첫 선택은 4일보다 오래됐다 — 블로그마다 시각이 따로다")
        self.assertEqual(self.found(store, 4, now=at(days=6), blog="naver_b"), ["c1"])

    def test_a_blog_that_was_not_recommended_but_was_chosen_counts(self):
        store = self.open()
        self.prepare(store, blogs=("naver_a",), blog="blogger_en")
        self.assertEqual(self.found(store, 90, now=at(days=1), blog="blogger_en"), ["c1"])
        self.assertEqual(self.found(store, 90, now=at(days=1), blog="naver_a"), [])

    def test_a_selected_candidate_with_no_selection_record_counts_from_its_last_change_for_every_recommended_blog(self):
        store = self.open()
        store.save_candidate(cand("c1", blogs=("naver_a", "naver_b"), status="SELECTED", now=NOW))        # 상태만 적어 들여온 후보 — 선택 기록이 없다
        self.assertEqual(self.found(store, 90, now=at(days=30)), ["c1"])
        self.assertEqual(self.found(store, 90, now=at(days=30), blog="naver_b"), ["c1"])
        self.assertEqual(self.found(store, 90, now=at(days=30), blog="github_pages"), [], "추천하지 않은 블로그는 아니다")
        self.assertEqual(self.found(store, 90, now=at(days=91)), [])
        store.save_candidate(cand("c2", keyword="다른 키워드", blogs=("naver_a", "naver_b"), status="SELECTED", selections=[("naver_a", NOW)]))
        self.assertEqual(self.found(store, 90, now=at(days=1), keyword="다른 키워드", blog="naver_a"), ["c2"])
        self.assertEqual(self.found(store, 90, now=at(days=1), keyword="다른 키워드", blog="naver_b"), [], "선택 기록이 있으면 그 기록만 믿는다")

    def test_choosing_again_renews_the_time_and_the_newest_choice_comes_first(self):
        store = self.open()
        self.prepare(store, when=at(days=-100))
        self.assertEqual(self.found(store, 90, now=NOW), [], "100일 전에 고른 것은 지났다")
        self.select(store, "c1", "naver_a", at(days=-10))
        self.assertEqual(self.found(store, 90, now=NOW), ["c1"], "다시 고르면 그 시각부터 센다")
        self.prepare(store, candidate_id="c2", when=at(days=-5))
        self.prepare(store, candidate_id="c3", when=at(days=-5))
        self.prepare(store, candidate_id="c4", when=at(days=-20))
        self.assertEqual(self.found(store, 90, now=NOW), ["c2", "c3", "c1", "c4"], "방금 고른 것이 먼저, 같은 시각이면 번호 순")

    def test_a_choice_dated_after_the_reference_time_still_counts(self):
        store = self.open()
        self.prepare(store, when=at(days=3))
        self.assertEqual(self.found(store, 90, now=NOW), ["c1"])

    def test_a_changed_keyword_is_searched_under_its_new_spelling_only(self):
        store = self.open()
        self.prepare(store)
        store.save_candidate(store.load_candidate("c1").edited(keyword="보일러 청소", now=at(hours=3)))
        self.assertEqual(self.found(store, 90, now=at(days=1), keyword="보일러 청소"), ["c1"])
        self.assertEqual(self.found(store, 90, now=at(days=1), keyword="보일러 점검"), [])

    def test_the_current_time_is_the_default_reference(self):
        store = self.open()
        store.save_candidate(cand())
        store.set_candidate_status("c1", "SELECTED", blog="naver_a")
        self.assertEqual([item.candidate_id for item in store.recent_selections("보일러 점검", "naver_a", 1)], ["c1"])

    def test_wrong_arguments_are_refused_and_not_guessed(self):
        store = self.open()
        self.prepare(store)
        base = dict(keyword="보일러 점검", blog="naver_a", days=90)
        for name, bad in (("keyword", ""), ("keyword", "?!"), ("keyword", None), ("keyword", 5), ("blog", "naver_c"), ("blog", ""), ("blog", None), ("days", -1), ("days", 3651),
                          ("days", True), ("days", "90"), ("days", 90.0), ("days", None)):
            with self.subTest(name=name, bad=repr(bad)):
                args = {**base, name: bad}
                self.refuses("CANDIDATE_INVALID", store.recent_selections, args["keyword"], args["blog"], args["days"], now=at(days=1))
        for bad in ("", "a b", "x" * 65, 5):
            with self.subTest(exclude=repr(bad)):
                self.refuses("CANDIDATE_INVALID", store.recent_selections, "보일러 점검", "naver_a", 90, now=at(days=1), exclude=bad)
        for bad in ("어제", "2026-11-02", "", 5):
            with self.subTest(now=repr(bad)):
                self.refuses("CANDIDATE_INVALID", store.recent_selections, "보일러 점검", "naver_a", 90, now=bad)


class TransitionBypassTest(CandidateStoreCase):
    """검증자가 찾은 틈 — 전이표가 `set_candidate_status` 에서만 지켜지고 `save_candidate(dataclasses.replace(…))` 로는 새던 것."""

    def forged(self, store, current, requested, **extra):
        store.save_candidate(cand(f"{current}-{requested}".lower().replace("_", "-"), keyword=f"{current}{requested}", status=current))
        loaded = store.load_candidate(f"{current}-{requested}".lower().replace("_", "-"))
        return loaded, dataclasses.replace(loaded, status=requested, revision=loaded.revision + 1, updated_at=at(hours=1), **extra)

    def test_all_25_pairs_follow_the_table_through_save_candidate_too(self):
        store = self.open()
        for current in STATUSES:
            for requested in STATUSES:
                with self.subTest(current=current, requested=requested):
                    loaded, forged = self.forged(store, current, requested)
                    if requested == current or requested in TRANSITIONS[current]:
                        store.save_candidate(forged)
                        self.assertEqual(store.load_candidate(loaded.candidate_id), forged)
                    else:
                        error = self.refuses("CANDIDATE_TRANSITION_INVALID", store.save_candidate, forged)
                        self.assertEqual(error.slots, {"현재 상태": STATUS_KO[current], "요청 상태": STATUS_KO[requested]})
                        self.assertEqual(store.load_candidate(loaded.candidate_id), loaded, "거절된 저장은 아무것도 바꾸지 않았다")
        self.assertEqual(store.check(), [])

    def test_a_rejected_candidate_cannot_be_forced_to_selected(self):
        store = self.open()
        store.save_candidate(cand())
        store.set_candidate_status("c1", "REJECTED", now=at(hours=1))
        rejected = store.load_candidate("c1")
        forced = dataclasses.replace(rejected, status="SELECTED", revision=rejected.revision + 1, updated_at=at(hours=2))
        error = self.refuses("CANDIDATE_TRANSITION_INVALID", store.save_candidate, forced)
        self.assertIn("제외", error.rendered().message)
        self.assertEqual(store.load_candidate("c1").status, "REJECTED")
        store.set_candidate_status("c1", "REVIEW", now=at(hours=3))                          # 정식 길(제외 → 검토 중 → 선택됨)은 열려 있다
        store.set_candidate_status("c1", "SELECTED", now=at(hours=4))

    def test_the_stored_state_decides_not_the_state_the_caller_thinks_it_had(self):
        """저장된 상태가 이미 바뀐 뒤 낡은 복사본의 상태에서 가는 길을 따라 저장하려 하면 막힌다."""
        store = self.open()
        store.save_candidate(cand())
        stale = store.load_candidate("c1")                                                   # 새 후보
        store.set_candidate_status("c1", "REJECTED", now=at(hours=1))                        # 다른 곳: 제외
        to_selected = stale.moved("SELECTED", now=at(hours=2))                               # 낡은 복사본 기준으로는 새 후보 → 선택됨 이 표에 있다
        self.refuses("STORE_CONFLICT", store.save_candidate, to_selected)                    # 판은 같고(2) 내용이 다르다
        store.set_candidate_status("c1", "REVIEW", now=at(hours=3))
        self.assertEqual(store.load_candidate("c1").status, "REVIEW")

    def test_keeping_the_same_state_is_allowed_for_every_state_so_edits_and_extra_blog_choices_work(self):
        store = self.open()
        for status in STATUSES:
            with self.subTest(status=status):
                item = cand(f"keep-{status}".lower(), keyword=f"유지 {status}", status=status)
                store.save_candidate(item)
                store.save_candidate(item.edited(reason="이유만 고침", now=at(hours=1)))
                self.assertEqual(store.load_candidate(item.candidate_id).status, status)


class MessagesTest(CandidateStoreCase):
    """사람이 읽는 문구 — 32자 내부 번호를 그대로 보이지 않고, 깨진 후보 하나는 그 후보만 지울 수 있다고 알린다."""

    UUID = "0123456789abcdef0123456789abcdef"

    def test_a_missing_candidate_is_named_by_a_short_number_not_the_whole_uuid(self):
        store = self.open()
        for call in (lambda: store.load_candidate(self.UUID), lambda: store.set_candidate_status(self.UUID, "REVIEW"), lambda: store.delete_candidate(self.UUID, confirm=True),
                     lambda: store.delete_candidate(self.UUID)):
            error = self.refuses("CANDIDATE_NOT_FOUND", call)
            shown = error.rendered().message
            self.assertIn("01234567", shown)
            self.assertNotIn(self.UUID, shown)
            self.assertNotIn("89abcdef0123456789abcdef", shown)
        self.assertEqual(self.refuses("CANDIDATE_NOT_FOUND", store.load_candidate, "c1").rendered().message, "주제 후보를 찾을 수 없습니다: 「c1」.")

    def test_the_confirmation_message_shows_the_topic_and_a_short_number(self):
        store = self.open()
        item = cand(self.UUID, topic="겨울철 보일러 점검 방법")
        store.save_candidate(item)
        shown = self.refuses("CANDIDATE_CONFIRM_REQUIRED", store.delete_candidate, self.UUID).rendered().message
        self.assertIn("겨울철 보일러 점검 방법", shown)
        self.assertIn("번호 01234567", shown)
        self.assertNotIn(self.UUID, shown)
        long_topic = cand("long", keyword="긴 주제", topic="가" * 150)
        store.save_candidate(long_topic)
        shown = self.refuses("CANDIDATE_CONFIRM_REQUIRED", store.delete_candidate, "long").rendered().message
        self.assertIn("가" * 40, shown)
        self.assertNotIn("가" * 41, shown, "긴 주제는 앞 40자만 보인다")
        self.assertEqual({item.candidate_id for item in store.list_candidates()}, {self.UUID, "long"}, "확인이 없어서 아무것도 지워지지 않았다")

    def test_the_confirmation_message_for_an_unreadable_row_still_names_the_number(self):
        store = self.open()
        store.save_candidate(cand(self.UUID))
        self.raw().execute("UPDATE candidates SET data = 'not json'")
        shown = self.refuses("CANDIDATE_CONFIRM_REQUIRED", store.delete_candidate, self.UUID).rendered().message
        self.assertIn("번호 01234567", shown)
        store.delete_candidate(self.UUID, confirm=True)                                      # 깨진 후보도 그 후보만 지울 수 있다
        self.assertEqual(store.list_candidates(), [])
        self.assertEqual(store.check(), [])

    def test_a_corrupt_candidate_is_named_by_a_short_number_not_the_whole_uuid(self):
        store = self.open()
        store.save_candidate(cand(self.UUID))
        self.raw().execute("UPDATE candidates SET data = '[]'")
        for call in (lambda: store.load_candidate(self.UUID), store.list_candidates, lambda: store.set_candidate_status(self.UUID, "REVIEW")):
            shown = self.refuses("CANDIDATE_CORRUPT", call).rendered().message
            self.assertIn("01234567", shown)
            self.assertNotIn(self.UUID, shown)
            self.assertNotIn("89abcdef0123456789abcdef", shown)
            self.assertEqual(shown.count("01234567"), 1, "번호가 문구에 한 번만 나온다(앞에 '후보 c3: 후보 c3:' 처럼 겹치지 않는다)")

    def test_a_corrupt_candidate_blocks_the_list_but_can_be_deleted_alone_and_the_others_stay(self):
        store = self.open()
        for number in range(3):
            store.save_candidate(cand(f"c{number}", keyword=f"키워드 {number}"))
        self.raw().execute("UPDATE candidates SET data = '[]' WHERE candidate_id = 'c1'")
        error = self.refuses("CANDIDATE_CORRUPT", store.list_candidates)
        self.assertIn("c1", error.rendered().message)
        self.assertEqual(store.load_candidate("c0").candidate_id, "c0", "다른 후보는 그대로 읽힌다")
        self.refuses("CANDIDATE_CORRUPT", store.list_candidates, status="NEW")
        self.refuses("CANDIDATE_CORRUPT", store.list_candidates, blog="naver_a")
        store.delete_candidate("c1", confirm=True)
        self.assertEqual([item.candidate_id for item in store.list_candidates()], ["c0", "c2"])
        shown = CATALOG["CANDIDATE_CORRUPT"]
        self.assertIn("그 후보만 삭제", shown.action)
        self.assertEqual(set(shown.slots), {"번호"})

    def test_a_rejected_value_names_the_field_and_the_reason_in_the_message_the_user_reads(self):
        store = self.open()
        for call, field, reason in ((lambda: store.list_candidates(status="DRAFTING"), "상태", "새 후보, 검토 중, 선택됨, 보류, 제외"), (lambda: store.list_candidates(blog="naver_c"), "블로그", "naver_a"),
                                    (lambda: store.load_candidate("a b"), "후보 번호", "1~64자"), (lambda: store.recent_selections("?!", "naver_a", 90), "핵심 키워드", "글자나 숫자"),
                                    (lambda: store.recent_selections("가", "naver_a", 99999), "같은 주제 재사용 기준", "3650")):
            shown = self.refuses("CANDIDATE_INVALID", call).rendered()
            self.assertIn(field, shown.message)
            self.assertIn(reason, shown.message)
            self.assertNotIn("원고", shown.message, "원고용 문구가 아니다")
            self.assertNotIn("제목은 200자", shown.action, "원고용 하실 일이 아니다")


class ReselectionTest(CandidateStoreCase):
    """보류·검토 중으로 물렸다가 한 블로그만 다시 고르면, 물리기 전에 고른 다른 블로그의 기록이 재선택 경고에 되살아나지 않는다."""

    def test_a_blog_chosen_before_the_hold_is_not_revived_by_choosing_only_another_blog_afterwards(self):
        store = self.open()
        store.save_candidate(cand(blogs=("naver_a", "naver_b")))
        store.set_candidate_status("c1", "SELECTED", now=at(hours=1))                          # 두 블로그 모두 선택
        for blog in ("naver_a", "naver_b"):
            self.assertEqual(len(store.recent_selections("보일러 점검", blog, 90, now=at(days=1))), 1)
        store.set_candidate_status("c1", "HOLD", now=at(hours=2))
        self.assertEqual(store.load_candidate("c1").selected_blogs, ("naver_a", "naver_b"), "물려 있는 동안에는 기록이 남아 있다")
        store.set_candidate_status("c1", "SELECTED", blog="naver_a", now=at(hours=3))          # 다시 고를 때는 naver_a 만
        self.assertEqual(store.load_candidate("c1").selections, (("naver_a", at(hours=3)),))
        self.assertEqual(len(store.recent_selections("보일러 점검", "naver_a", 90, now=at(days=1))), 1)
        self.assertEqual(store.recent_selections("보일러 점검", "naver_b", 90, now=at(days=1)), [], "naver_b 의 옛 선택이 경고에 되살아나지 않는다")

    def test_choosing_more_blogs_while_selected_still_adds_and_choosing_after_review_starts_fresh(self):
        store = self.open()
        store.save_candidate(cand(blogs=("naver_a", "naver_b")))
        store.set_candidate_status("c1", "SELECTED", blog="naver_a", now=at(hours=1))
        store.set_candidate_status("c1", "SELECTED", blog="naver_b", now=at(hours=2))
        self.assertEqual(store.load_candidate("c1").selected_blogs, ("naver_a", "naver_b"))
        store.set_candidate_status("c1", "REVIEW", now=at(hours=3))
        store.set_candidate_status("c1", "SELECTED", blog="naver_b", now=at(hours=4))
        self.assertEqual(store.load_candidate("c1").selections, (("naver_b", at(hours=4)),))


class MigrationTest(CandidateStoreCase):
    def old_file(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        make_v1_file(self.path, [project("p1"), project("p2")], [("p1", "초안 글", NOW)])

    def dump(self, path):
        with closing(sqlite3.connect(str(path))) as db:
            return list(db.iterdump())

    def test_a_version_1_file_is_upgraded_in_one_step_with_a_copy_and_nothing_lost(self):
        self.old_file()
        before = self.dump(self.path)
        store = self.open()
        db = self.raw()
        self.assertEqual((db.execute("PRAGMA user_version").fetchone()[0], db.execute("PRAGMA application_id").fetchone()[0]), (SCHEMA_VERSION, APPLICATION_ID))
        self.assertEqual(SCHEMA_VERSION, 2)
        self.assertEqual({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}, {"projects", "revisions", "drafts", "candidates"})
        self.assertEqual({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'candidates_%'")}, {"candidates_status", "candidates_keyword"})
        self.assertEqual([item.project_id for item in store.list()], ["p1", "p2"])
        self.assertEqual(store.load_draft("p1").text, "초안 글")
        self.assertEqual(store.history("p1"), [(1, NOW)])
        self.assertEqual(store.list_candidates(), [])
        store.save_candidate(cand(project_id="p1"))                           # 올라간 파일에 바로 후보를 쓸 수 있다
        self.assertEqual(store.load_candidate("c1").project_id, "p1")
        self.assertEqual(store.check(), [])
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        copy = self.path.with_name(self.path.name + ".v1.bak")
        self.assertTrue(copy.is_file())
        self.assertEqual(self.dump(copy), before, "사본은 올리기 전 파일 그대로다")
        with closing(sqlite3.connect(str(copy))) as old:
            self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(old.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'candidates'").fetchone()[0], 0)

    def test_an_upgraded_file_is_left_alone_when_opened_again(self):
        self.old_file()
        self.open().close()
        copy = self.path.with_name(self.path.name + ".v1.bak")
        copy_before, file_before = digest(copy), digest(self.path)
        self.open().close()
        self.assertEqual((digest(copy), digest(self.path)), (copy_before, file_before), "이미 올린 파일을 다시 열어도 아무것도 바뀌지 않는다")
        self.assertEqual(sorted(entry.name for entry in self.path.parent.iterdir()), [self.path.name, copy.name])

    def test_a_new_file_is_made_directly_in_the_new_shape(self):
        store = self.open()
        db = self.raw()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}, {"projects", "revisions", "drafts", "candidates"})
        self.assertEqual([entry.name for entry in self.path.parent.iterdir()], [self.path.name], "새 파일은 올릴 것이 없으니 사본도 없다")
        self.assertEqual(store.check(), [])
        columns = [row[1] for row in db.execute("PRAGMA table_info(candidates)")]
        self.assertEqual(columns, ["candidate_id", "keyword_key", "status", "project_id", "revision", "created_at", "updated_at", "data"])

    def test_the_table_the_upgrade_adds_is_the_same_as_the_one_a_new_file_gets(self):
        self.old_file()
        self.open().close()
        fresh_path = self.dir / "fresh.db"
        Store.open(fresh_path).close()
        found = []
        for path in (self.path, fresh_path):
            with closing(sqlite3.connect(str(path))) as db:
                found.append({row[0]: row[1] for row in db.execute("SELECT name, sql FROM sqlite_master WHERE name LIKE 'candidates%'")})
        upgraded, fresh = found
        self.assertEqual(upgraded, fresh)
        self.assertEqual(set(fresh), {"candidates", "candidates_status", "candidates_keyword"})

    def test_a_failure_in_the_middle_puts_everything_back_as_it_was(self):
        self.old_file()
        with closing(sqlite3.connect(str(self.path), isolation_level=None)) as db:
            db.execute("CREATE INDEX candidates_keyword ON projects (title)")       # 마지막 문장이 겹쳐서 실패하게 — 앞의 표 만들기는 이미 실행된 뒤다
        before = self.dump(self.path)
        error = self.refuses("MIGRATION_FAILED", Store.open, self.path)
        self.assertIn("candidates_keyword", error.detail)
        db = self.raw()
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'candidates'").fetchone()[0], 0, "만들던 표가 반쯤 남지 않았다")
        self.assertEqual(self.dump(self.path), before, "파일 안의 모든 표·자료가 그대로다")
        self.assertTrue(self.path.with_name(self.path.name + ".v1.bak").is_file(), "사본은 올리기 전에 이미 만들어 두었다")
        db.execute("DROP INDEX candidates_keyword")                          # 원인을 치우면 같은 파일이 이번에는 올라간다
        store = self.open()
        self.assertEqual(store.list_candidates(), [])
        self.assertEqual([item.project_id for item in store.list()], ["p1", "p2"])

    def test_a_failure_on_the_last_statement_undoes_the_earlier_ones_too(self):
        self.old_file()
        before = self.dump(self.path)
        broken = store_module._V2_CANDIDATES + ("CREATE TABLE candidates_extra (id INTEGER, id INTEGER)",)
        with mock.patch.object(store_module, "_V2_CANDIDATES", broken):
            self.refuses("MIGRATION_FAILED", Store.open, self.path)
        self.assertEqual(self.dump(self.path), before)
        self.assertEqual(self.raw().execute("PRAGMA user_version").fetchone()[0], 1)

    def test_a_copy_that_cannot_be_made_stops_the_upgrade_before_it_starts(self):
        self.old_file()
        before = self.dump(self.path)
        with mock.patch.object(Store, "_snapshot", side_effect=sqlite3.OperationalError("unable to open database file")):      # 사본을 둘 폴더에 쓸 수 없다
            error = self.refuses("MIGRATION_BLOCKED", Store.open, self.path)
        self.assertIn("원래 그대로", error.rendered().message)
        self.assertEqual(self.dump(self.path), before)
        self.assertEqual(self.raw().execute("PRAGMA user_version").fetchone()[0], 1)

    def test_a_file_from_a_newer_version_is_refused_and_left_alone_byte_for_byte(self):
        self.open().close()
        with closing(sqlite3.connect(str(self.path))) as db:
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        before = digest(self.path)
        error = self.refuses("STORE_VERSION_UNSUPPORTED", Store.open, self.path)
        self.assertIn(self.path.name, error.rendered().message)
        self.assertEqual(digest(self.path), before)

    def test_the_old_program_cannot_open_the_new_file_and_overwrite_it(self):
        with Store.open(self.path) as store:
            store.save_candidate(cand())
        before = digest(self.path)
        with mock.patch.object(store_module, "SCHEMA_VERSION", 1):             # 후보 표를 모르는 옛 프로그램인 척
            self.refuses("STORE_VERSION_UNSUPPORTED", Store.open, self.path)
        self.assertEqual(digest(self.path), before)
        with Store.open(self.path) as store:
            self.assertEqual(store.load_candidate("c1").topic, "겨울철 보일러 점검 방법")

    def test_a_damaged_version_1_file_is_refused_and_left_alone(self):
        self.old_file()
        data = self.path.read_bytes()
        self.path.write_bytes(data[:len(data) // 2])
        before = digest(self.path)
        self.refuses("STORE_CORRUPT", Store.open, self.path)
        self.assertEqual(digest(self.path), before)
        self.assertFalse(self.path.with_name(self.path.name + ".v1.bak").exists())

    def test_restoring_a_version_1_backup_brings_the_store_up_to_date(self):
        store = self.open()
        store.save_candidate(cand())
        backup = self.dir / "backups" / "old-20261030-060000.db"
        backup.parent.mkdir()
        make_v1_file(backup, [project("p7")])
        store.restore_from(backup)
        self.assertEqual([item.project_id for item in store.list()], ["p7"])
        self.assertEqual(store.list_candidates(), [], "백업 시점에는 후보 표가 없었으니 비어 있다")
        self.assertEqual(self.raw().execute("PRAGMA user_version").fetchone()[0], 2)
        store.save_candidate(cand("c9", keyword="새 후보"))
        self.assertEqual(store.check(), [])

    def test_restoring_a_current_backup_brings_the_candidates_back(self):
        store = self.open()
        store.save(project("p1"))
        store.save_candidate(self.select_all(cand(project_id="p1", **FULL)))
        made = store.backup(self.dir / "backups")
        store.delete_candidate("c1", confirm=True)
        store.save_candidate(cand("c2", keyword="그 뒤에 만든 후보"))
        store.restore_from(made)
        self.assertEqual([item.candidate_id for item in store.list_candidates()], ["c1"])
        self.assertEqual(store.load_candidate("c1").project_id, "p1")
        self.assertEqual(store.check(), [])

    @staticmethod
    def select_all(item):
        return item.moved("SELECTED", now=at(hours=1))

    def test_the_helper_really_makes_a_whole_version_1_file(self):
        self.old_file()
        db = self.raw()
        self.assertEqual((db.execute("PRAGMA user_version").fetchone()[0], db.execute("PRAGMA application_id").fetchone()[0], db.execute("PRAGMA integrity_check").fetchone()[0]), (1, APPLICATION_ID, "ok"))
        self.assertEqual({row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%'")}, {"projects", "projects_updated", "revisions", "drafts"})
        self.assertEqual(db.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 2)


class TamperTest(CandidateStoreCase):
    def stored(self):
        return self.raw().execute("SELECT data FROM candidates WHERE candidate_id = 'c1'").fetchone()[0]

    def test_a_healthy_store_has_no_problems(self):
        store = self.open()
        self.assertEqual(store.check(), [])
        store.save(project("p1"))
        store.save_candidate(cand(project_id="p1", **FULL))
        store.save_candidate(cand("c2", keyword="다른 키워드"))
        self.assertEqual(store.check(), [])

    def test_rows_that_were_edited_by_hand_or_damaged_are_reported_and_not_trusted(self):
        store = self.open()
        store.save_candidate(cand())
        good = self.stored()
        extra, other_id, with_link, wrong_type = json.loads(good), json.loads(good), json.loads(good), json.loads(good)
        extra["비밀"] = "x"
        other_id["candidate_id"] = "c9"
        with_link["project_id"] = "p1"
        wrong_type["blogs"] = "naver_a"
        wrong_status = json.loads(good)
        wrong_status["status"] = "DRAFTING"
        for name, bad in (("깨진 글", "not json"), ("빈 글", ""), ("목록", "[]"), ("모르는 칸", json.dumps(extra)), ("번호가 다름", json.dumps(other_id)), ("자료 안의 연결", json.dumps(with_link)),
                          ("모양 틀림", json.dumps(wrong_type)), ("모르는 상태", json.dumps(wrong_status)), ("깊은 중첩", "[" * 100000), ("글이 아닌 값", 5)):
            with self.subTest(name):
                self.raw().execute("UPDATE candidates SET data = ?", (bad,))
                error = self.refuses("CANDIDATE_CORRUPT", store.load_candidate, "c1")
                self.assertIn("c1", error.detail)
                shown = error.rendered()
                self.assertIn("후보 번호 「c1」", shown.message)
                self.assertIn("그 후보만 삭제", shown.action, "깨진 후보 하나만 지울 수 있다고 알린다")
                self.refuses("CANDIDATE_CORRUPT", store.list_candidates)
                self.refuses("CANDIDATE_CORRUPT", store.set_candidate_status, "c1", "REVIEW")
                problems = store.check()
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("후보 c1", problems[0])
                self.assertEqual(problems[0].count("후보 c1"), 1, "번호 접두를 두 번 붙이지 않는다(후보 c1: 후보 c1: …)")
        self.raw().execute("UPDATE candidates SET data = ?", (good,))
        self.assertEqual(store.check(), [])

    def test_a_list_column_that_disagrees_with_the_stored_candidate_is_reported(self):
        store = self.open()
        store.save_candidate(cand())
        for change in ("status = 'HOLD'", "revision = 5", f"created_at = '{at(days=1)}'", f"updated_at = '{at(days=1)}'", "keyword_key = '다른열쇠'"):
            with self.subTest(change):
                self.raw().execute(f"UPDATE candidates SET {change}")
                problems = store.check()
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("열과 자료가 다르다", problems[0])
                self.raw().execute("UPDATE candidates SET status = 'NEW', revision = 1, created_at = ?, updated_at = ?, keyword_key = '보일러점검'", (NOW, NOW))
                self.assertEqual(store.check(), [])

    def test_a_link_to_a_project_that_is_gone_is_reported(self):
        store = self.open()
        store.save(project("p1"))
        store.save_candidate(cand(project_id="p1"))
        raw = self.raw()
        raw.execute("DELETE FROM projects WHERE project_id = 'p1'")            # 외래 키를 끈 연결로 몰래 지웠다(앱은 이렇게 하지 않는다)
        problems = store.check()
        self.assertEqual(problems, ["후보 c1: 없는 글(p1)에 연결돼 있다"])

    def test_a_missing_candidates_table_is_damage_not_an_unexpected_error(self):
        store = self.open()
        store.save_candidate(cand())
        self.raw().execute("DROP TABLE candidates")
        self.refuses("STORE_CORRUPT", store.load_candidate, "c1")
        self.refuses("STORE_CORRUPT", store.list_candidates)
        self.refuses("STORE_CORRUPT", store.save_candidate, cand("c2"))
        self.refuses("STORE_CORRUPT", store.recent_selections, "보일러 점검", "naver_a", 90, now=at(days=1))


class ProjectsStillWorkTest(CandidateStoreCase):
    def test_projects_history_and_drafts_behave_as_before_with_candidates_in_the_file(self):
        store = self.open()
        for candidate_id in ("c1", "c2"):
            store.save_candidate(cand(candidate_id, keyword=f"키워드 {candidate_id}"))
        item = project("p1")
        store.save(item)
        item.edit(title="둘째 제목", now=at(hours=1))
        store.save(item)
        store.save_draft("p1", "초안")
        self.assertEqual([entry.project_id for entry in store.list()], ["p1"])
        self.assertEqual(store.history("p1"), [(2, at(hours=1)), (1, NOW)])
        self.assertEqual(store.load_draft("p1").text, "초안")
        store.delete("p1")
        self.refuses("CONTENT_NOT_FOUND", store.load, "p1")
        self.refuses("CONTENT_NOT_FOUND", store.delete, "p1")
        self.assertEqual(sorted(entry.candidate_id for entry in store.list_candidates()), ["c1", "c2"])
        self.assertEqual(store.check(), [])

    def test_a_backup_carries_the_candidates_and_opens_like_the_original(self):
        store = self.open()
        store.save_candidate(cand(**FULL))
        made = store.backup(self.dir / "backups")
        with Store.open(made) as copy:
            self.assertEqual(copy.load_candidate("c1"), store.load_candidate("c1"))
            self.assertEqual(copy.check(), [])

    def test_the_new_error_codes_render_with_their_own_values(self):
        for code, slots, needle in (("CANDIDATE_NOT_FOUND", {"항목": "c1"}, "c1"), ("CANDIDATE_CONFIRM_REQUIRED", {"항목": "c1"}, "c1"),
                                    ("CANDIDATE_TRANSITION_INVALID", {"현재 상태": "제외", "요청 상태": "선택됨"}, "선택됨"), ("CANDIDATE_CORRUPT", {"번호": "c1"}, "c1"),
                                    ("CANDIDATE_INVALID", {"항목": "추천 이유", "이유": "300자 이하여야 합니다"}, "300자 이하여야 합니다")):
            with self.subTest(code):
                shown = AppError(code, slots).rendered()
                self.assertIn(needle, shown.message)
                self.assertNotIn(UNKNOWN_SLOT, shown.message + shown.action)
                self.assertEqual(shown.code, code)
                self.assertIn(code, CATALOG)

    def test_every_platform_name_the_candidates_use_is_a_platform_of_the_content_model(self):
        self.assertEqual(PLATFORMS, ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"))


if __name__ == "__main__":
    unittest.main()
