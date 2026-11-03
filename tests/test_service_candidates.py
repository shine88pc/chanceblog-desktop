"""서비스 층 — 주제 후보 다루기(`service/candidates.py`) 시험. 목록·보기(읽기 전용)·추가·선택(재선택 경고)·보류·제외·되살리기·검토·지우기(확인)·글 연결·CSV 가져오기.

지키는 것:
  1) 순번은 만든 시각 순(같으면 번호 순)이고 새 후보가 뒤에 붙어도 앞의 순번은 안 바뀐다. 번호는 순번(1~999)·번호 전체·앞 4자 이상의 고유한 앞부분으로 고르고, 겹치면 CANDIDATE_AMBIGUOUS 로 어느 후보들인지 알린다.
  2) `list`·`show` 는 보관함을 읽기 전용으로 열어 파일을 만들지도 옛 구조를 올리지도 않고 한 바이트도 안 바꾼다. 쓰는 명령은 옛 구조를 사본과 함께 올린다.
  3) 상태 이동은 후보 자료의 이동 표(`TRANSITIONS`)와 같다 — 모든 (지금 상태, 요청) 짝에서 표대로 되고 안 되면 CANDIDATE_TRANSITION_INVALID 로 저장된 것은 그대로다.
  4) 선택은 블로그마다 기록하고, 같은 핵심 키워드를 같은 블로그용으로 그 블로그 프로필의 기준 일수(없으면 90일) 안에 이미 골랐으면 경고하되 막지 않는다 — 경계는 정확히 기준 일수째까지.
  5) 지우기는 서비스가 먼저 CONFIRMATION_REQUIRED 로 막고(확인 없이는 저장소의 지우기를 부르지도 않는다), 저장 계층의 CANDIDATE_CONFIRM_REQUIRED 는 이중 방어로만 남는다. 깨진 후보 하나는 번호 전체로 그 후보만 지울 수 있다.
  6) 글 연결은 없는 글이면 거절하고, 저장하다 다른 명령과 부딪치면(STORE_CONFLICT) 최신 후보를 다시 읽어 3번까지 다시 한다 — 다른 명령의 변경을 잃지 않는다.
  7) CSV 가져오기는 다시 가져와도 겹치지 않고(멱등), 잘못된 줄은 그 줄만 거절하며, 파일 전체가 안 되면 아무것도 저장하지 않는다(보관함 파일도 만들지 않는다).
네트워크 없이 임시 폴더에서 돈다.
"""
import hashlib
import os
import random
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import test_candidate_csv as pure  # noqa: E402  (무작위 입력의 조각 목록만 빌려 쓴다 — 시험 클래스를 가져오지는 않는다)
from store_v1 import make_v1_file  # noqa: E402

from chanceblog_desktop.content import Candidate, ContentProject  # noqa: E402
from chanceblog_desktop.content import candidate_csv as csvmod  # noqa: E402
from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import candidates as svc  # noqa: E402
from chanceblog_desktop.service import format as fmt  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402

ZWSP = chr(0x200B)
HEAD = "주제,핵심 키워드,대상 블로그"
LONG = "겨울 난방비를 줄이는 방법"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.fresh()

    def fresh(self):
        """아무것도 없는 새 작업 공간으로 바꾼다(한 시험 안에서 여러 경우를 따로 돌릴 때)."""
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, repo="")          # 설정 파일을 만들지 않아 데이터 폴더가 처음에는 없다
        self.clock = self.ctx.clock
        self.root = self.ctx.workspace.root
        self.store_path = self.ctx.workspace.store_path

    def add(self, topic, keyword=None, blogs=("naver_a",), **fields):
        """후보를 더한다 — 만든 시각이 서로 다르도록 시계를 1초 앞으로 보낸다(순번이 만든 시각 순이므로)."""
        self.clock.advance(seconds=1)
        return svc.add_candidate(self.ctx, topic=topic, keyword=keyword or topic + " 키워드", blogs=blogs, **fields)

    def seed(self, candidate_id, topic="주제", keyword="키워드", blogs=("naver_a",), **fields):
        with self.ctx.store() as store:
            candidate = Candidate.new(topic, keyword, blogs, candidate_id=candidate_id, now=self.ctx.stamp(), **fields)
            store.save_candidate(candidate)
        return candidate

    def stored(self):
        with self.ctx.store() as store:
            return svc.numbered(store.list_candidates())

    def one(self, ordinal):
        return self.stored()[ordinal - 1].candidate

    def number(self, ordinal):
        """그 순번 후보의 번호 앞 8자 — 지울 때는 순번이 아니라 이것으로 정한다."""
        return cd.short_id(self.one(ordinal).candidate_id)

    def six(self):
        """번호를 정해 둔 후보 여섯(앞 4자가 서로 다르다 — 무작위 번호가 우연히 겹쳐 시험이 흔들리지 않게). 번호 목록을 돌려준다."""
        for index, name in enumerate(("가", "나", "다", "라", "마", "바")):
            self.clock.advance(seconds=1)
            self.seed(f"{'abcdef'[index]}{index}f{index}e" + "0" * 24, name, f"키워드 {name}")
        return [row.candidate.candidate_id for row in self.stored()]

    def code(self, callable_, *args, **kwargs):
        error = ss.code_of(callable_, *args, **kwargs)
        shown = error.rendered()
        self.assertNotIn("알 수 없음", shown.message + shown.action, f"{error.code}: 자리표시자가 비었다")
        return error

    def csv_file(self, text, name="후보.csv", encoding="utf-8"):
        path = self.tmp / name
        path.write_bytes(text if isinstance(text, bytes) else text.encode(encoding))
        return path

    def import_text(self, text, **kwargs):
        return svc.import_csv(self.ctx, self.csv_file(text), **kwargs)

    def project(self, title="연결할 글", project_id=None):
        if project_id:
            with self.ctx.store() as store:
                store.save(ContentProject.new(title, "본문 첫 문단입니다.", project_id=project_id, now=self.ctx.stamp()))
            return project_id
        return projects.new_project(self.ctx, title, ss.ko_text()).project_id


# ---- 번호 ---------------------------------------------------------------------------------------------------------------------
class NumberingTest(Base):
    def test_the_order_is_creation_time_and_later_candidates_never_move_earlier_ones(self):
        results = [self.add(name) for name in ("가", "나", "다")]
        self.assertEqual([result.row.ordinal for result in results], [1, 2, 3])
        self.assertEqual([row.candidate.topic for row in self.stored()], ["가", "나", "다"])
        self.assertEqual(self.add("라").row.ordinal, 4)
        self.assertEqual([(row.ordinal, row.candidate.topic) for row in self.stored()], [(1, "가"), (2, "나"), (3, "다"), (4, "라")])

    def test_candidates_made_in_the_same_second_are_ordered_by_their_number(self):
        for candidate_id in ("zzzz0001", "aaaa0001", "mmmm0001"):
            self.seed(candidate_id, topic=candidate_id)
        self.assertEqual([row.candidate.candidate_id for row in self.stored()], ["aaaa0001", "mmmm0001", "zzzz0001"])

    def test_changing_a_status_does_not_reorder_the_list(self):
        for name in ("가", "나", "다"):
            self.add(name)
        self.clock.advance(minutes=5)
        svc.move_candidate(self.ctx, "1", cd.HOLD)
        svc.select_candidate(self.ctx, "3", "naver_a")
        self.assertEqual([row.candidate.topic for row in self.stored()], ["가", "나", "다"])

    def test_candidates_made_one_after_another_in_the_same_second_still_get_later_times_and_keep_their_order(self):
        """시계가 움직이지 않아도(같은 초에 연달아) 새 후보의 만든 시각은 이미 있는 것보다 1초 뒤다 — 무작위 번호가 순번을 뒤섞거나 이미 본 순번을 바꾸지 못한다."""
        seen = []
        for number in range(6):
            result = svc.add_candidate(self.ctx, topic=f"주제 {number}", keyword=f"키워드 {number}", blogs=("naver_a",))
            self.assertEqual(result.row.ordinal, number + 1)
            seen.append(result.row.candidate.topic)
            self.assertEqual([row.candidate.topic for row in self.stored()], seen, "이미 보인 순번은 그대로다")
        start = self.ctx.clock.now
        self.assertEqual([row.candidate.created_at for row in self.stored()], [(start + timedelta(seconds=n)).strftime("%Y-%m-%dT%H:%M:%SZ") for n in range(6)])

    def test_a_clock_that_went_backwards_does_not_put_a_new_candidate_before_older_ones(self):
        self.add("가")
        self.clock.advance(hours=-3)
        result = svc.add_candidate(self.ctx, topic="나", keyword="나 키워드", blogs=("naver_a",))
        first, second = self.stored()
        self.assertEqual((result.row.ordinal, second.candidate.created_at > first.candidate.created_at), (2, True))
        self.assertEqual(cd.parse_stamp(second.candidate.created_at) - cd.parse_stamp(first.candidate.created_at), timedelta(seconds=1))

    def test_a_later_clock_is_used_as_it_is_without_a_gap(self):
        self.add("가")
        self.clock.advance(minutes=5)
        row = svc.add_candidate(self.ctx, topic="나", keyword="나 키워드", blogs=("naver_a",)).row
        self.assertEqual(row.candidate.created_at, self.ctx.stamp())

    def test_a_file_imported_in_the_same_second_as_an_earlier_candidate_lands_after_it_in_the_files_order(self):
        for attempt in range(4):                              # 번호가 무작위이므로 여러 번 — 순서가 우연이 아니라는 것을 본다
            self.fresh()
            first = svc.add_candidate(self.ctx, topic="먼저 만든", keyword="먼저 키워드", blogs=("naver_a",)).row
            result = self.import_text(HEAD + "\n나중 하나,나중 키워드 하나,naver_a\n나중 둘,나중 키워드 둘,naver_a\n나중 셋,나중 키워드 셋,naver_a\n")
            self.assertEqual((first.ordinal, [row.ordinal for row in result.added]), (1, [2, 3, 4]), attempt)
            self.assertEqual([row.candidate.topic for row in self.stored()], ["먼저 만든", "나중 하나", "나중 둘", "나중 셋"])

    def test_the_same_creation_time_is_broken_by_the_number_whatever_order_the_store_hands_them_over(self):
        """보관함은 최근에 고친 것이 먼저로 내어 준다 — 같은 시각에 만든 후보는 번호가 순서를 정해야 순번이 상태를 바꿀 때마다 돌지 않는다."""
        items = [Candidate.new(f"주제{name}", f"키워드{name}", ("naver_a",), candidate_id=name, now="2026-11-02T00:00:00Z") for name in ("c333", "a111", "b222")]
        for order in (items, items[::-1], [items[1], items[2], items[0]], [items[2], items[0], items[1]]):
            with self.subTest(order=[item.candidate_id for item in order]):
                self.assertEqual([(row.ordinal, row.candidate.candidate_id) for row in svc.numbered(order)], [(1, "a111"), (2, "b222"), (3, "c333")])

    def test_a_file_imported_in_one_go_keeps_its_order_when_a_later_one_changes_its_state(self):
        result = self.import_text(HEAD + "\n" + "\n".join(f"주제 {n},키워드 {n},naver_a" for n in range(1, 6)) + "\n")
        original = [row.candidate.topic for row in self.stored()]
        self.assertEqual(original, [f"주제 {n}" for n in range(1, 6)])
        self.assertEqual(len({row.candidate.created_at for row in self.stored()}), 1, "한 번에 가져온 후보는 만든 시각이 모두 같다")
        for text, status in (("4", cd.HOLD), ("2", cd.REJECTED), ("5", cd.HOLD)):
            self.clock.advance(minutes=1)
            svc.move_candidate(self.ctx, text, status)
            self.assertEqual([row.candidate.topic for row in self.stored()], original, f"{text}번을 옮겨도 순번이 돌지 않는다")
        self.assertEqual([row.ordinal for row in result.added], [1, 2, 3, 4, 5])

    def test_a_candidate_just_made_in_the_same_second_can_be_chosen_moved_and_linked_right_away(self):
        """시계가 움직이지 않아도 새 후보의 만든·고친 시각은 1초씩 뒤로 적힌다 — 그 후보를 바로 고르거나 옮겨도 '고친 시각이 거꾸로 간다' 며 거절되지 않는다."""
        project_id = self.project()
        for number in range(4):
            svc.add_candidate(self.ctx, topic=f"주제 {number}", keyword=f"키워드 {number}", blogs=("naver_a",))                  # 시계를 움직이지 않는다
        self.assertGreater(self.one(4).updated_at, self.ctx.stamp(), "마지막 후보의 시각은 시계보다 앞서 있다")
        self.assertEqual(svc.select_candidate(self.ctx, "4", "naver_a").row.candidate.status, cd.SELECTED)
        self.assertEqual(svc.move_candidate(self.ctx, "3", cd.HOLD).row.candidate.status, cd.HOLD)
        self.assertEqual(svc.move_candidate(self.ctx, "2", cd.REJECTED).row.candidate.status, cd.REJECTED)
        self.assertEqual(svc.restore_candidate(self.ctx, "2").row.candidate.status, cd.REVIEW)
        self.assertEqual(svc.link_candidate(self.ctx, "4", project_id).row.candidate.project_id, project_id)
        self.assertGreaterEqual(self.one(4).updated_at, self.one(4).created_at, "고친 시각은 만든 시각보다 앞서지 않는다")

    def test_deleting_one_pulls_the_later_ones_up_by_one(self):
        for name in ("가", "나", "다"):
            self.add(name)
        svc.delete_candidate(self.ctx, self.number(2), confirmed=True)
        self.assertEqual([(row.ordinal, row.candidate.topic) for row in self.stored()], [(1, "가"), (2, "다")])


class ResolveTest(unittest.TestCase):
    IDS = ("abcd1111aaaa", "abcd2222bbbb", "ef012345cccc", "1234567890ab")

    def rows(self, ids=IDS):
        return svc.numbered([Candidate.new(f"주제{index}", f"키워드{index}", ("naver_a",), candidate_id=candidate_id, now=f"2026-11-02T00:00:{index:02d}Z")
                             for index, candidate_id in enumerate(ids, start=1)])

    def refuses(self, code, text, rows=None):
        error = ss.code_of(svc.resolve, self.rows() if rows is None else rows, text)
        self.assertEqual(error.code, code, error.detail)
        shown = error.rendered()
        self.assertNotIn("알 수 없음", shown.message + shown.action)
        return error

    def test_an_ordinal_picks_by_position_and_surrounding_spaces_are_ignored(self):
        rows = self.rows()
        for text, position in (("1", 1), ("2", 2), (" 3 ", 3), ("4", 4)):
            with self.subTest(text=text):
                self.assertIs(svc.resolve(rows, text), rows[position - 1])

    def test_an_ordinal_past_the_end_or_not_an_ordinal_at_all_is_not_found(self):
        for text in ("5", "999", "0", "00", "01", "-1", "+1", "1.0", "", "   ", "١"):
            with self.subTest(text=text):
                self.refuses("CANDIDATE_NOT_FOUND", text)
        self.refuses("CANDIDATE_NOT_FOUND", None)
        self.assertIn("4개뿐", self.refuses("CANDIDATE_NOT_FOUND", "5").detail)

    def test_four_or_more_characters_of_the_number_pick_the_one_candidate_they_start(self):
        rows = self.rows()
        for text, position in (("ef01", 3), ("EF01", 3), ("ef012345cccc", 3), ("abcd1", 1), ("abcd22", 2), ("1234", 4), ("1234567890ab", 4)):
            with self.subTest(text=text):
                self.assertIs(svc.resolve(rows, text), rows[position - 1])

    def test_a_short_or_unknown_beginning_is_not_found_and_says_how_to_write_one(self):
        for text in ("abc", "ef0", "ab", "qqqq", "abce", "9999"):
            with self.subTest(text=text):
                error = self.refuses("CANDIDATE_NOT_FOUND", text)
                self.assertEqual(error.slots["항목"], text)
        self.assertIn("앞 4자", self.refuses("CANDIDATE_NOT_FOUND", "abc").detail)

    def test_a_beginning_shared_by_several_candidates_is_ambiguous_and_lists_them(self):
        error = self.refuses("CANDIDATE_AMBIGUOUS", "abcd")
        self.assertEqual(error.slots["항목"], "abcd")
        self.assertIn("후보 번호가 여러 개와 겹칩니다", error.rendered().message)
        for needle in ("2개", "순번 1 주제1", "순번 2 주제2"):
            self.assertIn(needle, error.detail)
        self.assertNotIn("주제3", error.detail)

    def test_the_list_of_overlapping_candidates_also_shows_each_ones_eight_character_number(self):
        error = self.refuses("CANDIDATE_AMBIGUOUS", "abcd")
        self.assertIn("순번 1 주제1(번호 abcd1111)", error.detail)
        self.assertIn("순번 2 주제2(번호 abcd2222)", error.detail)

    def test_a_long_topic_is_cut_with_an_ellipsis_in_that_list(self):
        long = "겨울철 난방비를 줄이는 아주 긴 주제의 후보입니다 정말로"
        rows = svc.numbered([Candidate.new(long, "키워드 하나", ("naver_a",), candidate_id="zzzz0001", now="2026-11-02T00:00:01Z"),
                             Candidate.new("다른 " + long, "키워드 둘", ("naver_a",), candidate_id="zzzz0002", now="2026-11-02T00:00:02Z")])
        detail = self.refuses("CANDIDATE_AMBIGUOUS", "zzzz", rows).detail
        self.assertIn(f"순번 1 {long[:23]}…(번호 zzzz0001)", detail)
        self.assertNotIn(long, detail)
        self.assertEqual(svc._short("가" * 24), "가" * 24, "딱 24자는 그대로")
        self.assertEqual(svc._short("가" * 25), "가" * 23 + "…")
        self.assertEqual(svc._short("가  나\n다"), "가 나 다", "공백은 하나로 접는다")

    def test_digits_only_that_match_no_number_say_that_ordinals_stop_at_999_and_to_use_the_number(self):
        """`list` 에 보이는 1000번 이상의 순번을 그대로 치면 '번호 앞부분' 으로 읽혀 이유 없이 없다고 나오던 것."""
        for text in ("1000", "1202", "99999", "7654321"):
            with self.subTest(text=text):
                error = self.refuses("CANDIDATE_NOT_FOUND", text)
                self.assertIn("1000번 이상은 순번으로 고를 수 없습니다", error.detail)
                self.assertIn("번호 앞 8자로 고르세요", error.detail)
        for text in ("87654321", "987654321098", "abcd9999", "99x9"):                     # 8자 이상이거나 숫자만이 아니면 순번을 친 것이 아니다
            with self.subTest(text=text):
                self.assertNotIn("1000번 이상", self.refuses("CANDIDATE_NOT_FOUND", text).detail)
        rows = self.rows(("1000aaaa0000", "zzzz00000000"))
        self.assertIs(svc.resolve(rows, "1000"), rows[0], "맞는 번호가 있으면 번호로 읽는다")

    def test_a_full_number_wins_over_a_longer_number_it_begins(self):
        rows = self.rows(("wxyz", "wxyz9999", "other0001", "other0002"))
        self.assertIs(svc.resolve(rows, "wxyz"), rows[0])
        self.assertIs(svc.resolve(rows, "wxyz9"), rows[1])
        self.refuses("CANDIDATE_AMBIGUOUS", "other", rows)

    def test_the_list_of_overlapping_candidates_is_cut_at_eight_and_counts_the_rest(self):
        rows = self.rows(tuple(f"zzzz{index:04d}" for index in range(10)))
        error = self.refuses("CANDIDATE_AMBIGUOUS", "zzzz", rows)
        self.assertIn("10개", error.detail)
        self.assertIn("순번 8 ", error.detail)
        self.assertNotIn("순번 9 ", error.detail)
        self.assertIn("외 2개", error.detail)

    def test_an_exact_number_shorter_than_four_characters_still_matches_when_it_is_not_an_ordinal(self):
        rows = self.rows(("c1", "c2", "ab"))
        self.assertIs(svc.resolve(rows, "c2"), rows[1])
        self.assertIs(svc.resolve(rows, "ab"), rows[2])
        self.refuses("CANDIDATE_NOT_FOUND", "c", rows)


# ---- 읽기 전용 ----------------------------------------------------------------------------------------------------------------------
class ReadOnlyTest(Base):
    def test_list_and_show_on_a_missing_data_folder_create_nothing(self):
        result = svc.list_candidates(self.ctx)
        self.assertEqual((result.rows, result.total, result.store_state), ((), 0, "missing"))
        self.assertEqual(self.code(svc.show_candidate, self.ctx, "1").code, "CANDIDATE_NOT_FOUND")
        self.assertFalse(self.root.exists(), "보기만 하는 명령은 데이터 폴더도 보관함 파일도 만들지 않는다")
        self.assertEqual(self.code(svc.show_candidate, self.ctx, "abcd").code, "CANDIDATE_NOT_FOUND")
        self.assertFalse(self.root.exists())

    def test_an_empty_store_file_is_treated_like_a_missing_one(self):
        self.root.mkdir()
        self.store_path.write_bytes(b"")
        self.assertEqual(svc.list_candidates(self.ctx).store_state, "missing")
        self.assertEqual(self.store_path.read_bytes(), b"")

    def test_an_old_structure_file_lists_as_empty_and_stays_byte_for_byte_the_same_until_a_writing_command_raises_it(self):
        self.root.mkdir()
        make_v1_file(self.store_path, projects=[ContentProject.new("옛 글", "본문입니다.", project_id="p1", now="2026-11-02T00:00:00Z")])
        before = digest(self.store_path)
        result = svc.list_candidates(self.ctx)
        self.assertEqual((result.rows, result.store_state), ((), "old_structure"))
        self.assertEqual(self.code(svc.show_candidate, self.ctx, "1").code, "CANDIDATE_NOT_FOUND")
        self.assertEqual(digest(self.store_path), before)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["chanceblog.db"], "사본(.bak)도 임시 파일도 남기지 않는다")
        self.add("가")                                                   # 쓰는 명령 — 구조를 올린다
        self.assertTrue((self.root / "chanceblog.db.v1.bak").exists())
        after = svc.list_candidates(self.ctx)
        self.assertEqual((after.store_state, len(after.rows)), ("ready", 1))
        self.assertEqual([item.project_id for item in projects.list_projects(self.ctx)], ["p1"], "원고는 그대로다")

    def test_reading_a_current_file_changes_neither_its_bytes_nor_its_time(self):
        self.add("가")
        self.add("나")
        before = (digest(self.store_path), os.stat(self.store_path).st_mtime_ns, sorted(path.name for path in self.root.iterdir()))
        svc.list_candidates(self.ctx)
        svc.list_candidates(self.ctx, status=cd.NEW, blog="naver_a")
        svc.show_candidate(self.ctx, "1")
        svc.show_candidate(self.ctx, "2")
        self.assertEqual((digest(self.store_path), os.stat(self.store_path).st_mtime_ns, sorted(path.name for path in self.root.iterdir())), before)

    def test_the_reading_commands_open_the_store_read_only_and_the_writing_ones_do_not(self):
        calls = []
        original = Store.open.__func__

        def spy(cls, path, **kwargs):
            calls.append(kwargs.get("migrate", True))
            return original(cls, path, **kwargs)

        self.add("가")
        with mock.patch.object(Store, "open", classmethod(spy)):
            svc.list_candidates(self.ctx)
            svc.show_candidate(self.ctx, "1")
            self.assertEqual(calls, [False, False])
            svc.add_candidate(self.ctx, topic="나", keyword="나 키워드", blogs=("naver_a",))
            svc.select_candidate(self.ctx, "1", "naver_a")
            svc.move_candidate(self.ctx, "2", cd.HOLD)
            self.assertEqual(calls[2:], [True, True, True])

    def test_filters_keep_the_whole_list_ordinals_and_refuse_unknown_values(self):
        for name, blogs in (("가", ("naver_a",)), ("나", ("naver_a",)), ("다", ("naver_b",)), ("라", ("naver_a", "naver_b"))):
            self.add(name, blogs=blogs)
        svc.move_candidate(self.ctx, "2", cd.REJECTED)
        by_status = svc.list_candidates(self.ctx, status=cd.REJECTED)
        self.assertEqual(([row.ordinal for row in by_status.rows], by_status.total), ([2], 4))
        self.assertEqual([row.ordinal for row in svc.list_candidates(self.ctx, blog="naver_b").rows], [3, 4])
        self.assertEqual([row.ordinal for row in svc.list_candidates(self.ctx, status=cd.NEW, blog="naver_a").rows], [1, 4])
        for kwargs in ({"status": "SELECTD"}, {"status": "선택됨"}, {"blog": "tistory"}, {"blog": "naver_c"}, {"status": 1}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.code(svc.list_candidates, self.ctx, **kwargs).code, "CANDIDATE_INVALID")

    def test_show_reads_the_linked_project_and_survives_one_it_cannot_read(self):
        project_id = self.project("연결한 글")
        self.add("가")
        svc.link_candidate(self.ctx, "1", project_id)
        shown = svc.show_candidate(self.ctx, "1")
        self.assertEqual((shown.project.title, shown.project.error, shown.project.statuses), ("연결한 글", "", ()))
        with closing(sqlite3.connect(str(self.store_path), isolation_level=None)) as db:
            db.execute("UPDATE projects SET data = '깨짐' WHERE project_id = ?", (project_id,))
        broken = svc.show_candidate(self.ctx, "1").project
        self.assertEqual((broken.error, broken.title), ("STORE_CORRUPT", ""))


# ---- 추가 ---------------------------------------------------------------------------------------------------------------------------
class AddTest(Base):
    def test_a_new_candidate_has_the_defaults_and_is_numbered_one(self):
        result = self.add("겨울 보일러 점검 순서", "보일러 점검", ("naver_a", "github_pages"))
        candidate = result.row.candidate
        self.assertEqual((result.row.ordinal, result.twin), (1, None))
        self.assertEqual((candidate.status, candidate.revision, candidate.post_type, candidate.project_id, candidate.selections), (cd.NEW, 1, "정보형", None, ()))
        self.assertEqual((candidate.created_at, candidate.updated_at), (self.ctx.stamp(), self.ctx.stamp()))
        self.assertEqual(len(candidate.candidate_id), 32, "번호는 uuid 이다")
        self.assertEqual(self.one(1), candidate)

    def test_every_field_can_be_given(self):
        result = self.add("주제", "키워드", ("naver_b",), sub_keywords=("보조 하나", "보조 둘"), post_type="비교형", reason="찾는 사람이 늘고 있습니다", data_date="2026-11-01", search_demand=1200,
                          related_blog_results=3400, trend="상승", mobile_share=65.5, seasonality=(11, 12), duplicate=False, profile_fit=80, priority=70, keyword_opportunity=60)
        candidate = result.row.candidate
        self.assertEqual((candidate.sub_keywords, candidate.post_type, candidate.search_demand, candidate.seasonality, candidate.duplicate, candidate.keyword_opportunity),
                         (("보조 하나", "보조 둘"), "비교형", 1200, (11, 12), False, 60))
        data = result.to_dict()
        self.assertEqual((data["added"], data["duplicate_of"], data["candidate"]["ordinal"], data["candidate"]["status_name"]), (True, None, 1, "새 후보"))

    def test_a_same_candidate_is_not_added_twice_and_the_message_names_the_first(self):
        first = self.add("겨울 보일러 점검", "보일러 점검", ("naver_a", "naver_b")).row
        for label, topic, keyword, blogs in (("똑같이", "겨울 보일러 점검", "보일러 점검", ("naver_a", "naver_b")), ("키워드 띄어쓰기", "겨울 보일러 점검", "보일러점검", ("naver_a", "naver_b")),
                                             ("키워드 기호·대소문자", "겨울 보일러 점검", "보일러-점검", ("naver_b",)), ("주제 끝 공백", "겨울 보일러 점검 ", "보일러 점검", ("naver_a",)),
                                             ("블로그가 일부", "겨울 보일러 점검", "보일러 점검", ("naver_b",))):
            with self.subTest(label=label):
                again = self.add(topic, keyword, blogs)
                self.assertEqual((again.row, again.twin.ordinal), (None, first.ordinal))
                self.assertFalse(again.to_dict()["added"])
        self.assertEqual(len(self.stored()), 1)

    def test_the_topic_is_compared_without_case_or_width_differences_and_the_keyword_without_symbols(self):
        first = self.add("Winter Boiler Check Guide", "Boiler Check", ("naver_a",)).row
        for topic, keyword in (("winter boiler check guide", "boiler check"), ("WINTER BOILER CHECK GUIDE", "BOILER-CHECK"), ("Ｗinter Ｂoiler Ｃheck Ｇuide", "Boiler Check"),
                               ("Winter Boiler Check Guide", "boilercheck")):
            with self.subTest(topic=topic, keyword=keyword):
                again = self.add(topic, keyword, ("naver_a",))
                self.assertEqual((again.row, again.twin.ordinal), (None, first.ordinal))
        self.assertIsNotNone(self.add("Winter Boiler Check Tips", "Boiler Check", ("naver_a",)).row)

    def test_a_candidate_that_differs_in_topic_keyword_or_blogs_is_new(self):
        self.add("겨울 보일러 점검", "보일러 점검", ("naver_a",))
        for label, topic, keyword, blogs in (("블로그가 더 많음", "겨울 보일러 점검", "보일러 점검", ("naver_a", "naver_b")), ("다른 블로그", "겨울 보일러 점검", "보일러 점검", ("github_pages",)),
                                             ("다른 주제", "겨울 보일러 고르는 법", "보일러 점검", ("naver_a",)), ("다른 키워드", "겨울 보일러 점검", "보일러 교체", ("naver_a",)),
                                             ("C++ 와 C#", "프로그래밍 입문", "C++", ("naver_a",)), ("C# 은 다르다", "프로그래밍 입문", "C#", ("naver_a",))):
            with self.subTest(label=label):
                self.assertIsNotNone(self.add(topic, keyword, blogs).row, label)

    def days_from_now(self, days):
        return (cd.parse_stamp(self.ctx.stamp()) + timedelta(days=days)).strftime("%Y-%m-%d")

    def test_a_data_date_up_to_one_day_after_today_is_taken_and_a_later_one_is_refused_before_anything_is_saved(self):
        """오늘(UTC)보다 하루 뒤까지(지역 시간대 차이)만 받는다 — 먼 미래의 조회일은 실수다."""
        for days, accepted in ((-400, True), (-1, True), (0, True), (1, True), (2, False), (30, False)):
            with self.subTest(days=days):
                self.fresh()
                day = self.days_from_now(days)
                if accepted:
                    self.assertEqual(self.add("가", search_demand=5, data_date=day).row.candidate.data_date, day)
                else:
                    error = self.code(svc.add_candidate, self.ctx, topic="가", keyword="키워드", blogs=("naver_a",), search_demand=5, data_date=day)
                    self.assertEqual(error.code, "CANDIDATE_INVALID")
                    self.assertEqual(error.slots["항목"], cd.LABELS["data_date"])
                    self.assertIn("오늘보다 뒤의 날짜", error.slots["이유"])
                    self.assertIn(self.days_from_now(1), error.slots["이유"], "받는 가장 먼 날을 알려 준다")
                    self.assertFalse(self.root.exists(), "거절된 후보는 보관함도 만들지 않는다")
        self.fresh()
        self.assertEqual(self.code(svc.add_candidate, self.ctx, topic="가", keyword="키워드", blogs=("naver_a",), search_demand=5, data_date="2099-01-01").code, "CANDIDATE_INVALID")

    def test_a_data_date_of_the_wrong_shape_is_still_refused_by_the_candidate_rules_not_called_a_future_date(self):
        for day in ("내일", "2026/11/02", "2026-13-40", "1999-01-01", "9999-99-99", 5):
            with self.subTest(day=day):
                error = self.code(svc.add_candidate, self.ctx, topic="가", keyword="키워드", blogs=("naver_a",), search_demand=5, data_date=day)
                self.assertEqual(error.code, "CANDIDATE_INVALID")
                self.assertNotIn("오늘보다 뒤의 날짜", error.slots["이유"])
        self.assertEqual(self.code(svc.add_candidate, self.ctx, topic="가", keyword="키워드", blogs=("naver_a",), search_demand=5).code, "CANDIDATE_INVALID", "조회일이 없는 지표")

    def test_a_refused_value_saves_nothing_and_does_not_even_create_the_data_folder(self):
        for fields in ({"topic": "상위노출 보장 방법"}, {"keyword": ""}, {"blogs": ()}, {"blogs": ("tistory",)}, {"search_demand": 5}, {"reason": "수익 보장"}, {"trend": "폭등"}):
            with self.subTest(fields=fields):
                arguments = {"topic": "주제", "keyword": "키워드", "blogs": ("naver_a",), **fields}
                self.assertEqual(self.code(svc.add_candidate, self.ctx, **arguments).code, "CANDIDATE_INVALID")
        self.assertFalse(self.root.exists())

    def test_a_number_without_a_date_says_which_column_is_missing(self):
        error = self.code(svc.add_candidate, self.ctx, topic="주제", keyword="키워드", blogs=("naver_a",), search_demand=5)
        self.assertEqual(error.slots["항목"], cd.LABELS["data_date"])

    def test_a_corrupt_candidate_blocks_adding_and_says_which_one(self):
        self.seed("bad00000000000000000000000000001", "깨질 후보", "키워드 하나")
        self.seed("good0000000000000000000000000002", "멀쩡한 후보", "키워드 둘")
        with closing(sqlite3.connect(str(self.store_path), isolation_level=None)) as db:
            db.execute("UPDATE candidates SET data = '{}' WHERE candidate_id = ?", ("bad00000000000000000000000000001",))
        error = self.code(svc.add_candidate, self.ctx, topic="새 주제", keyword="새 키워드", blogs=("naver_a",))
        self.assertEqual(error.code, "CANDIDATE_CORRUPT")
        self.assertIn("bad00000000000000000000000000001", error.detail)


# ---- 상태 옮기기 ----------------------------------------------------------------------------------------------------------------------
class TransitionTableTest(Base):
    """모든 (지금 상태, 요청) 짝에서 후보 자료의 이동 표(`TRANSITIONS`)와 같게 되고, 안 되는 것은 저장된 것을 안 바꾼다."""

    def candidate_in(self, status, index):
        """그 상태의 후보 하나(순번 index)를 만든다."""
        self.add(f"주제 {status} {index}", f"키워드 {status} {index}")
        path = {cd.NEW: (), cd.REVIEW: (cd.REVIEW,), cd.HOLD: (cd.HOLD,), cd.REJECTED: (cd.REJECTED,), cd.SELECTED: (cd.SELECTED,)}[status]
        for step in path:
            if step == cd.SELECTED:
                svc.select_candidate(self.ctx, str(index), "naver_a")
            else:
                svc.move_candidate(self.ctx, str(index), step)
        self.assertEqual(self.one(index).status, status)

    def test_move_hold_reject_review_and_select_follow_the_table_for_every_pair(self):
        checked = 0
        for source in cd.STATUSES:
            for target in (cd.HOLD, cd.REJECTED, cd.REVIEW, cd.SELECTED):
                with self.subTest(source=source, target=target):
                    index = len(self.stored()) + 1
                    self.candidate_in(source, index)
                    before = self.one(index)
                    allowed = cd.can_transition(source, target)
                    run = (lambda: svc.select_candidate(self.ctx, str(index), "naver_b")) if target == cd.SELECTED else (lambda: svc.move_candidate(self.ctx, str(index), target))
                    if target == cd.SELECTED and source == cd.SELECTED:
                        allowed = True                                    # 이미 선택됨인 후보에 블로그를 더 고르는 것은 상태 이동이 아니다
                    if allowed:
                        result = run()
                        self.assertEqual((result.row.candidate.status, result.before, self.one(index).status), (target, source, target))
                        self.assertEqual(self.one(index).revision, before.revision + 1)
                    else:
                        error = self.code(run)
                        self.assertEqual(error.code, "CANDIDATE_TRANSITION_INVALID")
                        self.assertEqual((error.slots["현재 상태"], error.slots["요청 상태"]), (cd.STATUS_KO[source], cd.STATUS_KO[target]))
                        self.assertEqual(self.one(index), before, "거절된 이동은 저장된 것을 한 글자도 바꾸지 않는다")
                    checked += 1
        self.assertEqual(checked, 20)

    def test_restore_works_only_on_a_rejected_candidate_and_lands_in_review(self):
        for source in cd.STATUSES:
            with self.subTest(source=source):
                index = len(self.stored()) + 1
                self.candidate_in(source, index)
                before = self.one(index)
                if source == cd.REJECTED:
                    result = svc.restore_candidate(self.ctx, str(index))
                    self.assertEqual((result.before, self.one(index).status), (cd.REJECTED, cd.REVIEW))
                else:
                    error = self.code(svc.restore_candidate, self.ctx, str(index))
                    self.assertEqual((error.code, error.slots["현재 상태"]), ("CANDIDATE_TRANSITION_INVALID", cd.STATUS_KO[source]))
                    self.assertEqual(self.one(index), before)

    def test_the_table_the_commands_follow_is_the_documented_one(self):
        self.assertEqual({source: tuple(sorted(targets)) for source, targets in cd.TRANSITIONS.items()},
                         {cd.NEW: (cd.HOLD, cd.REJECTED, cd.REVIEW, cd.SELECTED), cd.REVIEW: (cd.HOLD, cd.REJECTED, cd.SELECTED), cd.HOLD: (cd.REJECTED, cd.REVIEW, cd.SELECTED),
                          cd.REJECTED: (cd.REVIEW,), cd.SELECTED: (cd.HOLD, cd.REVIEW)})

    def test_move_refuses_select_and_unknown_states_because_choosing_needs_a_blog(self):
        self.add("가")
        for status in (cd.SELECTED, cd.NEW, "DRAFTING", "", None):
            with self.subTest(status=status):
                self.assertEqual(self.code(svc.move_candidate, self.ctx, "1", status).code, "CANDIDATE_INVALID")
        self.assertEqual(self.one(1).status, cd.NEW)

    def test_a_clock_that_went_backwards_never_makes_the_edit_time_go_backwards(self):
        self.add("가")
        self.clock.advance(seconds=10)
        svc.move_candidate(self.ctx, "1", cd.HOLD)
        stamp = self.one(1).updated_at
        self.clock.advance(minutes=-5)                                    # 만든 시각보다도 앞선 시계
        svc.move_candidate(self.ctx, "1", cd.REVIEW)
        self.assertEqual(self.one(1).updated_at, stamp)
        self.assertEqual(self.one(1).status, cd.REVIEW)


# ---- 선택 -----------------------------------------------------------------------------------------------------------------------------
class SelectTest(Base):
    def profile(self, blog="naver_a", **options):
        self.ctx.settings.save_naver_profile(NaverProfile(blog, "블로그 에이" if blog == "naver_a" else "블로그 비", f"https://blog.naver.com/example{blog[-1] * 3}", **options))

    def pair(self, days_apart, blog="naver_a", second_blog=None, **second):
        """같은 핵심 키워드의 후보 둘을 만들어 첫째를 고르고 `days_apart` 일 뒤 둘째를 고른 결과."""
        self.add("주제 하나", "같은 키워드", (blog,))
        self.add("주제 둘", "같은 키워드", (second_blog or blog,), **second)
        svc.select_candidate(self.ctx, "1", blog)
        self.clock.advance(days=days_apart)
        return svc.select_candidate(self.ctx, "2", second_blog or blog)

    def test_choosing_records_the_blog_and_the_time_and_moves_to_selected(self):
        self.add("가")
        result = svc.select_candidate(self.ctx, "1", "naver_a")
        candidate = result.row.candidate
        self.assertEqual((candidate.status, candidate.selections, result.before, result.blog, result.again, result.outside), (cd.SELECTED, (("naver_a", self.ctx.stamp()),), cd.NEW, "naver_a", False, False))
        self.assertEqual((result.warnings, candidate.revision), ((), 2))
        self.assertEqual(self.one(1), candidate)

    def test_a_second_blog_adds_a_record_without_a_state_move_and_a_non_recommended_blog_is_noted(self):
        self.add("가", blogs=("naver_a",))
        svc.select_candidate(self.ctx, "1", "naver_a")
        self.clock.advance(hours=1)
        result = svc.select_candidate(self.ctx, "1", "github_pages")
        self.assertEqual((result.again, result.outside, result.before), (True, True, cd.SELECTED))
        self.assertEqual([blog for blog, _stamp in self.one(1).selections], ["github_pages", "naver_a"], "선택 기록은 플랫폼 순서로 둔다")
        self.assertEqual(self.one(1).selected_time("github_pages"), self.ctx.stamp())
        self.assertEqual(self.one(1).revision, 3)

    def test_the_warning_counts_the_days_from_when_it_was_chosen_not_from_when_it_was_last_edited(self):
        self.profile(topic_reuse_days=30)
        project_id = self.project()
        self.add("주제 하나", "같은 키워드")
        self.add("주제 둘", "같은 키워드")
        svc.select_candidate(self.ctx, "1", "naver_a")
        chosen_at = self.ctx.stamp()
        self.clock.advance(days=5)
        svc.link_candidate(self.ctx, "1", project_id)                                  # 고른 뒤 다른 일로 고친 시각만 달라졌다
        self.assertGreater(self.one(1).updated_at, chosen_at)
        self.assertEqual(self.one(1).selected_time("naver_a"), chosen_at)
        self.clock.advance(days=7)
        warning = svc.select_candidate(self.ctx, "2", "naver_a").warnings[0]
        self.assertEqual((warning.days_ago, warning.picked_at), (12, chosen_at), "고른 날(12일 전)이지 마지막으로 고친 날(7일 전)이 아니다")

    def two_choices(self, first, second):
        """같은 키워드의 후보 둘 — 시계를 `first`(협정세계시)에 두고 첫째를, `second` 에 두고 둘째를 고른 결과."""
        self.profile(topic_reuse_days=30)
        self.add("주제 하나", "같은 키워드")
        self.add("주제 둘", "같은 키워드")
        self.clock.now = first
        svc.select_candidate(self.ctx, "1", "naver_a")
        self.clock.now = second
        return svc.select_candidate(self.ctx, "2", "naver_a")

    def test_the_days_ago_are_counted_on_the_korean_calendar_not_in_24_hour_steps(self):
        """어젯밤(한국 시간 23:00)에 고른 것을 오늘 새벽(01:00)에 다시 고르면 2시간 지났어도 '1일 전' 이다."""
        warning = self.two_choices(datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc), datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)).warnings[0]
        self.assertEqual(warning.days_ago, 1)
        self.fresh()
        warning = self.two_choices(datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc), datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc)).warnings[0]
        self.assertEqual(warning.days_ago, 0, "같은 한국 날짜(11월 3일 10:00 과 23:00)면 0일 전이다")

    def test_the_date_in_the_warning_is_the_korean_date_and_the_times_are_shown_in_korean_time(self):
        first = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)                      # 한국 시간으로는 11월 3일 01:00 — 협정세계시 날짜와 다르다
        result = self.two_choices(first, datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc))
        warning = result.warnings[0]
        self.assertEqual((warning.days_ago, warning.picked_at), (0, "2026-11-02T16:00:00Z"), "저장하는 시각은 협정세계시 그대로다")
        self.assertIn("0일 전(2026-11-03)에 이미 골랐습니다", fmt.candidate_select_lines(result)[1])
        self.assertEqual(fmt.local_time("2026-11-02T16:00:00Z"), "2026-11-03 01:00")
        self.assertEqual(fmt.local_time("2026-11-02T14:59:59Z"), "2026-11-02 23:59")
        self.assertEqual(fmt.local_time("2026-12-31T15:00:00Z"), "2027-01-01 00:00")
        self.assertEqual(svc.kst("2026-11-02T00:00:00Z").utcoffset(), timedelta(hours=9))

    def test_a_clock_that_went_backwards_never_gives_a_negative_number_of_days(self):
        self.profile(topic_reuse_days=30)
        self.add("주제 하나", "같은 키워드")
        self.add("주제 둘", "같은 키워드")
        self.clock.now = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)
        svc.select_candidate(self.ctx, "1", "naver_a")
        self.clock.now = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(svc.select_candidate(self.ctx, "2", "naver_a").warnings[0].days_ago, 0, "시계가 뒤로 가서 '앞으로 고른' 것이 되어도 음수가 아니라 0일 전이다")
        self.assertEqual(svc._day_gap("2026-11-03T03:00:00Z", "2026-11-05T03:00:00Z"), 0)

    def test_a_blog_that_is_not_one_of_the_five_is_refused_and_a_missing_candidate_is_not_found(self):
        self.add("가")
        for blog in ("tistory", "", None, "NAVER_A", "pages"):
            with self.subTest(blog=blog):
                self.assertEqual(self.code(svc.select_candidate, self.ctx, "1", blog).code, "CANDIDATE_INVALID")
        self.assertEqual(self.one(1).status, cd.NEW)
        self.assertEqual(self.code(svc.select_candidate, self.ctx, "2", "naver_a").code, "CANDIDATE_NOT_FOUND")

    def test_the_warning_window_ends_exactly_on_the_reuse_day_of_the_blog_profile(self):
        for days, warned in ((0, True), (29, True), (30, True), (31, False), (90, False)):
            with self.subTest(days=days):
                self.fresh()
                self.profile(topic_reuse_days=30)
                result = self.pair(days)
                self.assertEqual(bool(result.warnings), warned, days)
                if warned:
                    warning = result.warnings[0]
                    self.assertEqual((warning.days_ago, warning.days, warning.blog, warning.other.ordinal, warning.other.candidate.topic), (days, 30, "naver_a", 1, "주제 하나"))
                self.assertEqual(result.row.candidate.status, cd.SELECTED, "경고는 막지 않는다 — 선택은 기록된다")
                self.assertEqual(self.one(2).selections[0][0], "naver_a")

    def test_a_short_window_from_the_profile_is_honoured(self):
        for days, warned in ((10, True), (11, False)):
            with self.subTest(days=days):
                self.fresh()
                self.profile(topic_reuse_days=10)
                self.assertEqual(bool(self.pair(days).warnings), warned)

    def test_a_blog_without_a_profile_uses_ninety_days(self):
        for blog in ("naver_a", "github_pages", "blogger_ko"):
            for days, warned in ((90, True), (91, False)):
                with self.subTest(blog=blog, days=days):
                    self.fresh()
                    result = self.pair(days, blog)
                    self.assertEqual(bool(result.warnings), warned)
                    if warned:
                        self.assertEqual(result.warnings[0].days, 90)

    def test_zero_reuse_days_never_warns(self):
        self.profile(topic_reuse_days=0)
        self.assertEqual(self.pair(0).warnings, ())

    def test_each_blog_has_its_own_window_and_another_blog_never_warns(self):
        self.profile("naver_a", topic_reuse_days=10)
        self.profile("naver_b", topic_reuse_days=100)
        self.add("주제 하나", "같은 키워드", ("naver_a", "naver_b"))
        self.add("주제 둘", "같은 키워드", ("naver_a", "naver_b"))
        svc.select_candidate(self.ctx, "1", "naver_a")
        svc.select_candidate(self.ctx, "1", "naver_b")
        self.clock.advance(days=50)
        self.assertEqual(svc.select_candidate(self.ctx, "2", "naver_a").warnings, (), "네이버 A 는 10일이 지났다")
        warned = svc.select_candidate(self.ctx, "2", "naver_b").warnings
        self.assertEqual([(item.blog, item.days) for item in warned], [("naver_b", 100)])
        self.assertEqual(svc.select_candidate(self.ctx, "2", "github_pages").warnings, (), "다른 블로그용으로는 고른 적이 없다")

    def test_an_earlier_candidate_that_was_put_back_or_rejected_does_not_count(self):
        for step, path in ((cd.HOLD, (cd.HOLD,)), (cd.REVIEW, (cd.REVIEW,)), (cd.REJECTED, (cd.HOLD, cd.REJECTED))):
            with self.subTest(step=step):
                self.fresh()
                self.add("주제 하나", "같은 키워드")
                self.add("주제 둘", "같은 키워드")
                svc.select_candidate(self.ctx, "1", "naver_a")
                for move in path:
                    svc.move_candidate(self.ctx, "1", move)
                self.assertEqual(self.one(1).status, step)
                self.assertEqual(svc.select_candidate(self.ctx, "2", "naver_a").warnings, ())

    def test_choosing_the_same_candidate_for_the_same_blog_again_never_warns_about_itself(self):
        self.add("가")
        svc.select_candidate(self.ctx, "1", "naver_a")
        again = svc.select_candidate(self.ctx, "1", "naver_a")
        self.assertEqual((again.again, again.warnings), (True, ()))

    def test_the_keyword_is_compared_without_spacing_and_the_newest_choice_comes_first(self):
        self.add("주제 하나", "보일러 점검")
        self.add("주제 둘", "보일러점검")
        self.add("주제 셋", "보일러-점검")
        svc.select_candidate(self.ctx, "1", "naver_a")
        self.clock.advance(days=1)
        svc.select_candidate(self.ctx, "2", "naver_a")
        self.clock.advance(days=1)
        warnings = svc.select_candidate(self.ctx, "3", "naver_a").warnings
        self.assertEqual([(item.other.ordinal, item.days_ago) for item in warnings], [(2, 1), (1, 2)])
        self.assertEqual([item["other_topic"] for item in (item.to_dict() for item in warnings)], ["주제 둘", "주제 하나"])

    def test_a_broken_settings_file_stops_the_choice_before_anything_is_recorded(self):
        self.add("가")
        self.ctx.workspace.settings_path.write_text("이건 설정이 아니다", encoding="utf-8")
        self.assertEqual(self.code(svc.select_candidate, self.ctx, "1", "naver_a").code, "SETTINGS_INVALID")
        self.assertEqual((self.one(1).status, self.one(1).revision), (cd.NEW, 1))
        self.assertEqual(svc.select_candidate(self.ctx, "1", "github_pages").row.candidate.status, cd.SELECTED, "프로필을 읽지 않는 블로그는 그대로 된다")

    def test_a_candidate_another_command_added_or_deleted_while_checking_does_not_break_a_choice_that_is_already_recorded(self):
        self.add("주제 하나", "같은 키워드")
        self.add("주제 둘", "같은 키워드")
        svc.select_candidate(self.ctx, "1", "naver_a")
        original, path = Store.recent_selections, self.store_path

        def sneaky(store, keyword, blog, within_days, **kwargs):
            found = original(store, keyword, blog, within_days, **kwargs)
            self.clock.advance(seconds=1)
            with Store.open(path) as other:                                  # 확인한 바로 뒤에 다른 명령이 같은 키워드의 후보를 더하고 골랐다
                other.save_candidate(Candidate.new("끼어든 후보", keyword, ("naver_a",), candidate_id="zzzz0001", now=self.ctx.stamp()))
                intruder = other.set_candidate_status("zzzz0001", cd.SELECTED, blog="naver_a", now=self.ctx.stamp())
            ghost = Candidate.new("이미 지워진 후보", keyword, ("naver_a",), candidate_id="gone0001", now=self.ctx.stamp())          # 확인할 때는 있었지만 지금은 없다
            return found + [intruder, ghost]

        with mock.patch.object(Store, "recent_selections", autospec=True, side_effect=sneaky):
            result = svc.select_candidate(self.ctx, "2", "naver_a")
        self.assertEqual([(item.other.ordinal, item.other.candidate.topic) for item in result.warnings], [(1, "주제 하나"), (3, "끼어든 후보")], "지워진 후보는 경고에서 빠진다")
        self.assertEqual((result.row.ordinal, result.row.candidate.status), (2, cd.SELECTED))
        self.assertEqual(self.one(2).selections[0][0], "naver_a", "고른 것은 기록돼 있다")

    def test_a_warning_turns_into_plain_data(self):
        result = self.pair(5)
        self.assertEqual(sorted(result.warnings[0].to_dict()), ["blog", "days_ago", "other_ordinal", "other_topic", "picked_at", "reuse_days"])
        self.assertEqual(result.to_dict()["warnings"][0]["days_ago"], 5)


# ---- 지우기 ---------------------------------------------------------------------------------------------------------------------------
class DeleteTest(Base):
    def test_the_service_stops_without_confirmation_before_the_store_is_asked_to_delete(self):
        self.add("지울 후보")
        number = self.number(1)
        original = Store.delete_candidate
        with mock.patch.object(Store, "delete_candidate", autospec=True, side_effect=original) as spy:
            for confirmed in (False, None, "yes", 1, "True", 0):
                for text in ("1", number):
                    with self.subTest(confirmed=confirmed, text=text):
                        error = self.code(svc.delete_candidate, self.ctx, text, confirmed=confirmed)
                        self.assertEqual(error.code, "CONFIRMATION_REQUIRED")
                        self.assertIn("지울 후보", error.slots["항목"])
                        self.assertIn("순번 1", error.slots["항목"])
                        self.assertIn(f"번호 {number}", error.slots["항목"])
                        self.assertIn("새 후보", error.slots["항목"])
                        self.assertIn("--yes", error.detail)
                        self.assertIn(f"candidates delete {number} --yes", error.detail, "지울 정확한 명령(번호 앞 8자)을 알려 준다 — 순번이 아니다")
            self.assertEqual(spy.call_count, 0, "확인이 없으면 저장소의 지우기를 부르지도 않는다")
            self.assertEqual(len(self.stored()), 1)
            result = svc.delete_candidate(self.ctx, number, confirmed=True)
            self.assertEqual(spy.call_count, 1)
            self.assertIs(spy.call_args.kwargs["confirm"], True)
        self.assertEqual((result.ordinal, result.topic), (1, "지울 후보"))
        self.assertEqual(self.stored(), [])

    def test_what_the_user_sees_is_the_services_code_and_the_stores_own_code_stays_as_the_second_defense(self):
        self.add("지울 후보")
        error = self.code(svc.delete_candidate, self.ctx, "1", confirmed=False)
        self.assertEqual(error.code, "CONFIRMATION_REQUIRED")
        self.assertNotEqual(error.code, "CANDIDATE_CONFIRM_REQUIRED")
        candidate_id = self.one(1).candidate_id
        with self.ctx.store() as store:
            second = self.code(store.delete_candidate, candidate_id)                      # 저장소를 직접 쓰는 쪽이 확인을 빠뜨린 경우
            self.assertEqual(second.code, "CANDIDATE_CONFIRM_REQUIRED")
            self.assertIn("지울 후보", second.slots["항목"])
            self.assertEqual(len(store.list_candidates()), 1)

    def test_an_ordinal_or_a_short_beginning_with_the_confirmation_deletes_nothing_and_names_the_command_to_run(self):
        before = self.six()
        third = before[2]
        original = Store.delete_candidate
        with mock.patch.object(Store, "delete_candidate", autospec=True, side_effect=original) as spy:
            for repeat in range(3):                                                        # 같은 명령을 되풀이해도 다른 후보가 지워지지 않는다
                for text in ("3", " 3 ", third[:4], third[:5], third[:7], third[:4].upper()):
                    with self.subTest(repeat=repeat, text=text):
                        error = self.code(svc.delete_candidate, self.ctx, text, confirmed=True)
                        self.assertEqual(error.code, "CANDIDATE_DELETE_NEEDS_NUMBER")
                        self.assertIn("다", error.slots["항목"])
                        self.assertIn("순번 3", error.slots["항목"])
                        self.assertIn(f"번호 {third[:8]}", error.slots["항목"])
                        self.assertIn(f"candidates delete {third[:8]} --yes", error.detail)
                        self.assertIn("아무것도 지우지 않았습니다", error.detail)
            self.assertEqual(spy.call_count, 0, "순번으로는 저장소의 지우기를 부르지도 않는다")
        self.assertEqual([row.candidate.candidate_id for row in self.stored()], before)

    def test_a_missing_ordinal_or_beginning_with_the_confirmation_is_not_found_not_a_request_for_the_number(self):
        self.add("가")
        for text in ("2", "999", "qqqq", "no" + "such0000"):
            with self.subTest(text=text):
                self.assertEqual(self.code(svc.delete_candidate, self.ctx, text, confirmed=True).code, "CANDIDATE_NOT_FOUND")
        self.assertEqual(len(self.stored()), 1)

    def test_the_number_deletes_exactly_that_candidate_and_the_same_command_again_is_not_found_instead_of_hitting_another(self):
        self.six()
        number = self.number(3)
        self.assertEqual(svc.delete_candidate(self.ctx, number, confirmed=True).topic, "다")
        self.assertEqual([row.candidate.topic for row in self.stored()], ["가", "나", "라", "마", "바"])
        for repeat in range(3):                                                            # 순번 3 은 이제 '라' 지만 번호 앞 8자는 더는 아무 후보도 가리키지 않는다
            error = self.code(svc.delete_candidate, self.ctx, number, confirmed=True)
            self.assertEqual(error.code, "CANDIDATE_NOT_FOUND", repeat)
        self.assertEqual([row.candidate.topic for row in self.stored()], ["가", "나", "라", "마", "바"], "되풀이해도 다른 후보는 그대로다")

    def test_a_longer_beginning_the_whole_number_and_capital_letters_delete_the_same_candidate(self):
        for name in ("가", "나", "다", "라"):
            self.add(name)
        for ordinal, spell in ((2, lambda text: text[:12]), (1, lambda text: text), (1, lambda text: text[:8].upper())):
            with self.subTest(ordinal=ordinal):
                candidate = self.one(ordinal)
                self.assertEqual(svc.delete_candidate(self.ctx, spell(candidate.candidate_id), confirmed=True).candidate_id, candidate.candidate_id)
        self.assertEqual([row.candidate.topic for row in self.stored()], ["라"], "세 번 지웠으니 하나가 남는다 — 각 번호는 자기 후보만 지웠다")

    def test_a_number_shorter_than_eight_characters_deletes_by_its_whole_number_only(self):
        self.seed("abc1", "짧은 번호", "키워드 하나")
        self.clock.advance(seconds=1)
        self.seed("abc2", "다른 짧은 번호", "키워드 둘")
        for text in ("abc", "1", "2"):
            with self.subTest(text=text):
                self.assertIn(self.code(svc.delete_candidate, self.ctx, text, confirmed=True).code, ("CANDIDATE_DELETE_NEEDS_NUMBER", "CANDIDATE_NOT_FOUND"))
        self.assertEqual(len(self.stored()), 2)
        self.assertEqual(svc.delete_candidate(self.ctx, "abc2", confirmed=True).candidate_id, "abc2")
        self.assertEqual([row.candidate.candidate_id for row in self.stored()], ["abc1"])

    def test_a_beginning_shared_by_two_candidates_is_ambiguous_for_deleting_too(self):
        self.seed("samepref" + "a" * 24, "첫째", "키워드 하나")
        self.clock.advance(seconds=1)
        self.seed("samepref" + "b" * 24, "둘째", "키워드 둘")
        error = self.code(svc.delete_candidate, self.ctx, "samepref", confirmed=True)
        self.assertEqual(error.code, "CANDIDATE_AMBIGUOUS")
        self.assertEqual(len(self.stored()), 2)
        self.assertEqual(svc.delete_candidate(self.ctx, "samepref" + "b", confirmed=True).topic, "둘째")

    def test_the_linked_post_stays(self):
        project_id = self.project()
        self.add("가")
        svc.link_candidate(self.ctx, "1", project_id)
        svc.delete_candidate(self.ctx, self.number(1), confirmed=True)
        self.assertEqual([item.project_id for item in projects.list_projects(self.ctx)], [project_id])

    def corrupt_pair(self):
        bad, good = "bad00000000000000000000000000001", "good0000000000000000000000000002"
        self.seed(bad, "깨질 후보", "키워드 하나")
        self.clock.advance(seconds=1)
        self.seed(good, "멀쩡한 후보", "키워드 둘")
        with closing(sqlite3.connect(str(self.store_path), isolation_level=None)) as db:
            db.execute("UPDATE candidates SET data = '{\"손\": 1}' WHERE candidate_id = ?", (bad,))
        return bad, good

    def test_one_corrupt_candidate_blocks_the_list_but_can_be_deleted_alone_by_the_eight_characters_the_error_shows(self):
        bad, good = self.corrupt_pair()
        blocked = self.code(svc.list_candidates, self.ctx)
        self.assertEqual(blocked.code, "CANDIDATE_CORRUPT")
        self.assertIn(bad, blocked.detail, "오류 세부에 번호 전체가 나온다")
        self.assertEqual(blocked.slots["번호"], bad[:8], "오류 문구에는 번호 앞 8자가 나온다")
        for text in ("1", "2", bad[:4], bad[:7], "nosuch000"):                              # 순번이나 짧은 앞부분이나 없는 번호는 아무것도 지우지 않고 원래 깨짐 안내가 나온다
            for confirmed in (True, False):
                with self.subTest(text=text, confirmed=confirmed):
                    self.assertEqual(self.code(svc.delete_candidate, self.ctx, text, confirmed=confirmed).code, "CANDIDATE_CORRUPT")
        for text in (bad[:8], bad[:8].upper(), bad[:12], bad):                               # 번호 앞 8자·더 긴 앞부분·번호 전체는 확인 전에는 미리 보기만 보인다
            with self.subTest(text=text):
                preview = self.code(svc.delete_candidate, self.ctx, text, confirmed=False)
                self.assertEqual(preview.code, "CONFIRMATION_REQUIRED")
                self.assertIn("깨진 후보", preview.slots["항목"])
                self.assertIn(f"candidates delete {bad[:8]} --yes", preview.detail)
        self.assertEqual(self.code(svc.list_candidates, self.ctx).code, "CANDIDATE_CORRUPT", "미리 보기는 아무것도 지우지 않았다")
        result = svc.delete_candidate(self.ctx, bad[:8], confirmed=True)
        self.assertEqual((result.candidate_id, result.ordinal, result.topic), (bad, None, ""))
        self.assertEqual([row.candidate.candidate_id for row in self.stored()], [good], "멀쩡한 후보는 그대로다")
        self.assertEqual(self.code(svc.delete_candidate, self.ctx, "no" + "such0000", confirmed=True).code, "CANDIDATE_NOT_FOUND")

    def test_a_corrupt_candidate_is_also_deleted_by_a_longer_beginning_or_the_whole_number(self):
        for spell in (lambda text: text[:12], lambda text: text, lambda text: text[:8].upper()):
            self.fresh()
            bad, good = self.corrupt_pair()
            self.assertEqual(svc.delete_candidate(self.ctx, spell(bad), confirmed=True).candidate_id, bad)
            self.assertEqual([row.candidate.candidate_id for row in self.stored()], [good])

    def test_two_candidates_that_share_the_beginning_are_ambiguous_while_the_list_is_blocked_too(self):
        first, second = "samepref" + "a" * 24, "samepref" + "b" * 24
        self.seed(first, "첫째", "키워드 하나")
        self.clock.advance(seconds=1)
        self.seed(second, "둘째", "키워드 둘")
        with closing(sqlite3.connect(str(self.store_path), isolation_level=None)) as db:
            db.execute("UPDATE candidates SET data = '{\"손\": 1}' WHERE candidate_id = ?", (first,))
        error = self.code(svc.delete_candidate, self.ctx, "samepref", confirmed=True)
        self.assertEqual(error.code, "CANDIDATE_AMBIGUOUS")
        self.assertIn("2개", error.detail)
        self.assertIn(first[:12], error.detail)
        self.assertIn(second[:12], error.detail)
        with self.ctx.store() as store:
            self.assertEqual(sorted(store.candidate_ids()), [first, second], "아무것도 지우지 않았다")
        self.assertEqual(svc.delete_candidate(self.ctx, first[:12], confirmed=True).candidate_id, first)


# ---- 글 연결 --------------------------------------------------------------------------------------------------------------------------
class LinkTest(Base):
    def test_a_candidate_is_linked_by_the_whole_number_or_a_beginning_of_the_post(self):
        project_id = self.project()
        self.add("가")
        self.add("나")
        result = svc.link_candidate(self.ctx, "1", project_id)
        self.assertEqual((result.changed, result.previous, result.project.title, result.project.error), (True, None, "연결할 글", ""))
        self.assertEqual((self.one(1).project_id, self.one(1).revision), (project_id, 2))
        second = svc.link_candidate(self.ctx, "2", project_id[:4])
        self.assertEqual((second.row.candidate.project_id, second.changed), (project_id, True))

    def test_linking_the_same_post_again_changes_nothing(self):
        project_id = self.project()
        self.add("가")
        svc.link_candidate(self.ctx, "1", project_id)
        before = self.one(1)
        again = svc.link_candidate(self.ctx, "1", project_id)
        self.assertEqual((again.changed, again.previous), (False, project_id))
        self.assertEqual(self.one(1), before, "판 번호도 오르지 않는다")

    def test_linking_another_post_replaces_the_link_and_tells_which_one_it_replaced(self):
        first, second = self.project("첫 글"), self.project("둘째 글")
        self.add("가")
        svc.link_candidate(self.ctx, "1", first)
        result = svc.link_candidate(self.ctx, "1", second)
        self.assertEqual((result.changed, result.previous, self.one(1).project_id), (True, first, second))

    def test_a_post_that_does_not_exist_is_refused_and_the_candidate_is_untouched(self):
        self.project("있는 글")
        self.add("가")
        before = self.one(1)
        for text in ("ffffffff", "zzzz", "ab", "", "../x"):
            with self.subTest(text=text):
                self.assertIn(self.code(svc.link_candidate, self.ctx, "1", text).code, ("CONTENT_NOT_FOUND", "CONTENT_INVALID"))
        self.assertEqual(self.one(1), before)

    def test_a_beginning_shared_by_two_posts_is_refused(self):
        self.project("첫", project_id="proj0001")
        self.project("둘", project_id="proj0002")
        self.add("가")
        self.assertEqual(self.code(svc.link_candidate, self.ctx, "1", "proj").code, "CONTENT_INVALID")
        self.assertEqual(svc.link_candidate(self.ctx, "1", "proj0002").row.candidate.project_id, "proj0002")

    def test_unlinking_cuts_the_link_only_and_a_second_time_changes_nothing(self):
        project_id = self.project()
        self.add("가")
        svc.link_candidate(self.ctx, "1", project_id)
        result = svc.unlink_candidate(self.ctx, "1")
        self.assertEqual((result.changed, result.previous, self.one(1).project_id), (True, project_id, None))
        self.assertEqual([item.project_id for item in projects.list_projects(self.ctx)], [project_id])
        again = svc.unlink_candidate(self.ctx, "1")
        self.assertEqual((again.changed, again.previous), (False, None))

    def test_deleting_the_post_leaves_the_candidate_with_no_link(self):
        project_id = self.project()
        self.add("가")
        svc.link_candidate(self.ctx, "1", project_id)
        projects.delete_project(self.ctx, project_id, confirmed=True)
        self.assertEqual((self.one(1).project_id, svc.show_candidate(self.ctx, "1").project), (None, None))

    def test_a_change_made_meanwhile_by_another_command_is_kept_and_the_link_is_saved_on_top_of_it(self):
        project_id = self.project()
        self.add("가")
        original, path, calls = Store.save_candidate, self.store_path, []

        def sneaky(store, candidate, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                with Store.open(path) as other:                                    # 그 사이 다른 명령이 같은 후보를 보류로 옮겼다
                    other.set_candidate_status(candidate.candidate_id, cd.HOLD, now=self.ctx.stamp())
            return original(store, candidate, **kwargs)

        with mock.patch.object(Store, "save_candidate", autospec=True, side_effect=sneaky):
            result = svc.link_candidate(self.ctx, "1", project_id)
        self.assertEqual(len(calls), 2, "처음 저장은 부딪쳐 거절됐고 최신 후보를 다시 읽어 한 번 더 저장했다")
        self.assertEqual([call["expected_revision"] for call in calls], [1, 2])
        self.assertEqual((result.changed, result.row.candidate.status, result.row.candidate.project_id, result.row.candidate.revision), (True, cd.HOLD, project_id, 3))
        self.assertEqual(self.one(1), result.row.candidate, "다른 명령의 보류도, 연결도 모두 남았다")

    def test_a_clash_that_never_clears_stops_after_three_tries_and_leaves_the_candidate_alone(self):
        project_id = self.project()
        self.add("가")
        before = self.one(1)
        clash = AppError("STORE_CONFLICT", {"항목": "주제 후보 가"}, detail="시험용 충돌")
        with mock.patch.object(Store, "save_candidate", autospec=True, side_effect=clash) as spy:
            error = self.code(svc.link_candidate, self.ctx, "1", project_id)
        self.assertEqual((error.code, spy.call_count, svc.RETRIES), ("STORE_CONFLICT", 3, 3))
        self.assertEqual(self.one(1), before)

    def test_only_a_clash_is_retried(self):
        project_id = self.project()
        self.add("가")
        broken = AppError("DISK_FULL", detail="시험용")
        with mock.patch.object(Store, "save_candidate", autospec=True, side_effect=broken) as spy:
            self.assertEqual(self.code(svc.link_candidate, self.ctx, "1", project_id).code, "DISK_FULL")
        self.assertEqual(spy.call_count, 1)

    def test_a_candidate_that_vanished_between_reading_and_saving_is_not_found(self):
        project_id = self.project()
        self.add("가")
        original = Store.save_candidate

        def gone(store, candidate, **kwargs):
            with Store.open(self.store_path) as other:
                other.delete_candidate(candidate.candidate_id, confirm=True)
            return original(store, candidate, **kwargs)

        with mock.patch.object(Store, "save_candidate", autospec=True, side_effect=gone):
            self.assertEqual(self.code(svc.link_candidate, self.ctx, "1", project_id).code, "CANDIDATE_NOT_FOUND")


# ---- CSV 가져오기 ---------------------------------------------------------------------------------------------------------------------------
class ImportTest(Base):
    def test_rows_are_added_and_the_summary_counts_add_skip_and_reject(self):
        result = self.import_text(HEAD + "\n겨울 보일러,보일러 점검,네이버 A\n전기장판,전기장판,naver_b\n겨울 보일러,보일러 점검,naver_a\n상위노출 보장 글,아무거나,naver_a\n")
        self.assertEqual((len(result.added), len(result.skipped), len(result.rejected)), (2, 1, 1))
        self.assertEqual(result.summary(), "2개 추가·1개 건너뜀·1개 거절")
        self.assertEqual((result.rows, result.file, result.blank_lines, result.unknown_columns), (4, "후보.csv", 0, ()))
        self.assertEqual([(row.ordinal, row.candidate.topic, row.candidate.blogs) for row in result.added], [(1, "겨울 보일러", ("naver_a",)), (2, "전기장판", ("naver_b",))])
        self.assertEqual((result.skipped[0].line, result.rejected[0].line), (4, 5))
        self.assertEqual(result.skipped[0].reason, "같은 핵심 키워드·주제·블로그의 후보가 이미 있습니다(이 파일의 줄 2)")
        self.assertTrue(result.rejected[0].reason.startswith(cd.LABELS["topic"] + ":"), result.rejected[0].reason)

    def test_importing_the_same_file_again_adds_nothing_and_changes_nothing(self):
        text = HEAD + ",월간 검색 수요,데이터 조회일\n가,키워드 가,naver_a,100,2026-11-01\n나,키워드 나,\"naver_a, naver_b\",,\n다,키워드 다,github_pages,,\n"
        first = self.import_text(text)
        stored = self.stored()
        for run in range(3):
            with self.subTest(run=run):
                again = self.import_text(text)
                self.assertEqual((again.summary(), [note.line for note in again.skipped]), ("0개 추가·3개 건너뜀·0개 거절", [2, 3, 4]))
                self.assertEqual(self.stored(), stored, "번호·판·시각까지 그대로다")
        self.assertEqual(first.summary(), "3개 추가·0개 건너뜀·0개 거절")
        self.assertTrue(all(note.reason.startswith("같은 핵심 키워드·주제·블로그의 후보가 이미 있습니다(순번 ") for note in again.skipped))

    def test_the_same_row_twice_in_one_file_is_added_once_and_the_second_names_the_first_line(self):
        result = self.import_text(HEAD + "\n가,키워드 가,naver_a\n나,키워드 나,naver_a\n가,키워드 가,naver_a\n가,키워드가,naver_a\n")
        self.assertEqual(result.summary(), "2개 추가·2개 건너뜀·0개 거절")
        self.assertEqual([note.reason for note in result.skipped], ["같은 핵심 키워드·주제·블로그의 후보가 이미 있습니다(이 파일의 줄 2)"] * 2)

    def test_a_candidate_added_by_hand_is_not_added_again_by_the_file(self):
        self.add("겨울 보일러", "보일러 점검", ("naver_a", "naver_b"))
        result = self.import_text(HEAD + "\n겨울 보일러,보일러 점검,naver_a\n겨울 보일러,보일러 점검,\"naver_a,naver_b\"\n겨울 보일러,보일러 점검,\"naver_a,github_pages\"\n")
        self.assertEqual(result.summary(), "1개 추가·2개 건너뜀·0개 거절", "블로그가 더 많은 줄은 새 후보다")
        self.assertEqual(result.skipped[0].reason, "같은 핵심 키워드·주제·블로그의 후보가 이미 있습니다(순번 1)")

    def test_a_rejected_row_never_stops_the_others_and_each_reason_names_its_column(self):
        text = (HEAD + ",월간 검색 수요,데이터 조회일\n"
                "정상 하나,키워드 하나,naver_a,5,2026-11-01\n"
                "상위노출 보장 글,키워드 둘,naver_a,,\n"
                "키워드가 비었다,,naver_a,,\n"
                "블로그가 틀렸다,키워드 셋,티스토리,,\n"
                "숫자가 아니다,키워드 넷,naver_a,많음,2026-11-01\n"
                "날짜가 없다,키워드 다섯,naver_a,5,\n"
                "날짜 모양이 틀렸다,키워드 여섯,naver_a,5,2026/11/01\n"
                "정상 둘,키워드 일곱,naver_b,,\n")
        result = self.import_text(text)
        self.assertEqual(result.summary(), "2개 추가·0개 건너뜀·6개 거절")
        reasons = {note.line: note.reason for note in result.rejected}
        self.assertEqual(sorted(reasons), [3, 4, 5, 6, 7, 8])
        for line, column in ((3, cd.LABELS["topic"]), (4, cd.LABELS["keyword"]), (5, cd.LABELS["blogs"]), (6, cd.LABELS["search_demand"]), (7, cd.LABELS["data_date"]), (8, cd.LABELS["data_date"])):
            self.assertTrue(reasons[line].startswith(column + ":"), (line, reasons[line]))
        self.assertIn("--data-date", reasons[7])
        self.assertEqual([row.candidate.topic for row in self.stored()], ["정상 하나", "정상 둘"])

    def test_line_numbers_count_the_lines_inside_a_quoted_cell(self):
        text = HEAD + '\n"둘로\n나뉜 주제",키워드 하나,naver_a\n상위노출 보장 글,키워드 둘,naver_a\n\n"또\n\n나뉜",,naver_a\n'
        result = self.import_text(text)
        self.assertEqual([row.candidate.topic for row in result.added], ["둘로 나뉜 주제"])
        self.assertEqual([note.line for note in result.rejected], [4, 6], "둘째 줄(2~3)이 두 줄을 차지해 다음 줄이 4 번이고, 빈 줄(5) 다음의 세 줄짜리(6~8)는 6 번에서 시작한다")
        self.assertNotIn("줄에 걸쳐", result.rejected[0].reason)
        self.assertIn("파일의 3줄에 걸쳐", result.rejected[1].reason)
        self.assertEqual(result.blank_lines, 1)

    def test_a_date_and_blogs_given_to_the_command_fill_the_empty_cells_only(self):
        text = "주제,핵심 키워드,대상 블로그,월간 검색 수요,데이터 조회일\n가,키워드 가,,5,\n나,키워드 나,naver_b,5,2026-10-30\n"
        before = self.import_text(text)
        self.assertEqual(before.summary(), "1개 추가·0개 건너뜀·1개 거절", "블로그가 빈 첫 줄은 --blog 가 없으면 거절, 둘째 줄은 날짜도 블로그도 있어 된다")
        result = self.import_text(text, blogs=("naver_a",), data_date="2026-11-01")
        self.assertEqual(result.summary(), "1개 추가·1개 건너뜀·0개 거절")
        added = result.added[0].candidate
        self.assertEqual((added.topic, added.blogs, added.data_date), ("가", ("naver_a",), "2026-11-01"))
        second = [row.candidate for row in self.stored() if row.candidate.topic == "나"][0]
        self.assertEqual((second.blogs, second.data_date), (("naver_b",), "2026-10-30"), "줄에 적힌 것이 먼저다")

    def test_a_blog_column_is_not_needed_when_a_default_blog_is_given(self):
        result = self.import_text("주제,핵심 키워드\n가,키워드 가\n나,키워드 나\n", blogs=("naver_b", "github_pages"))
        self.assertEqual([row.candidate.blogs for row in result.added], [("naver_b", "github_pages")] * 2)
        error = self.code(svc.import_csv, self.ctx, self.csv_file("주제,핵심 키워드\n가,키워드 가\n"))
        self.assertEqual(error.code, "CANDIDATE_CSV_INVALID")

    def test_a_bad_default_date_or_blog_is_refused_before_the_file_is_read(self):
        path = self.csv_file(HEAD + "\n가,키워드,naver_a\n")
        for kwargs in ({"data_date": "2026/11/01"}, {"data_date": "2026-13-01"}, {"data_date": ""}, {"blogs": ("tistory",)}, {"blogs": ("naver_a", "x")}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.code(svc.import_csv, self.ctx, path, **kwargs).code, "CANDIDATE_INVALID")
        self.assertFalse(self.root.exists())

    def test_utf8_a_byte_order_mark_and_cp949_give_the_same_candidates(self):
        text = HEAD + "\n겨울 보일러 점검,보일러 점검,네이버 A\n"
        results = []
        for label, data in (("utf-8", text.encode("utf-8")), ("bom", b"\xef\xbb\xbf" + text.encode("utf-8")), ("cp949", text.encode("cp949"))):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as other:
                ctx = ss.make_ctx(other, repo="")
                path = Path(other) / "x.csv"
                path.write_bytes(data)
                added = svc.import_csv(ctx, path).added
                results.append([(row.candidate.topic, row.candidate.keyword, row.candidate.blogs) for row in added])
        self.assertEqual(results, [[("겨울 보일러 점검", "보일러 점검", ("naver_a",))]] * 3)

    def test_a_file_that_cannot_be_used_at_all_stores_nothing_and_does_not_create_the_store(self):
        big = b"a" * (csvmod.MAX_CSV_BYTES + 1)
        many = HEAD + "\n" + "\n".join(f"주제{n},키워드{n},naver_a" for n in range(csvmod.MAX_CSV_ROWS + 1)) + "\n"
        cases = {"UTF-16": "a,b\n".encode("utf-16"), "NUL": b"a,b\n1\x002\n", "깨진 글자": b"\xff\xff\xff\xff,\x81\x20\n", "빈 파일": b"", "머리줄 없음": "겨울,보일러,naver_a\n".encode("utf-8"),
                 "필요한 열 없음": "메모,번호\n1,2\n".encode("utf-8"), "같은 뜻의 열": (HEAD + ",주제\n").encode("utf-8"), "5MB 초과": big, "2000줄 초과": many.encode("utf-8"),
                 "머리줄만 있고 따옴표가 안 닫힘": ('"' + "가" * 200_000 + HEAD + "\n").encode("utf-8")}
        for label, data in cases.items():
            with self.subTest(label=label):
                error = self.code(svc.import_csv, self.ctx, self.csv_file(data))
                self.assertEqual(error.code, "CANDIDATE_CSV_INVALID", label)
                self.assertFalse(self.root.exists(), f"{label}: 보관함이 만들어졌다")
        for label, path in (("없는 파일", self.tmp / "없는.csv"), ("폴더", self.tmp)):
            with self.subTest(label=label):
                self.assertEqual(self.code(svc.import_csv, self.ctx, path).code, "CANDIDATE_CSV_INVALID")
                self.assertFalse(self.root.exists())

    def test_a_file_of_exactly_five_megabytes_is_read_and_one_byte_more_is_refused_before_reading(self):
        count = csvmod.MAX_CSV_ROWS                                                                   # 핵심 키워드가 비어 모두 거절되므로 저장은 하나도 하지 않는다(빠르다)
        head = (HEAD + ",메모\n").encode("utf-8")
        spare = csvmod.MAX_CSV_BYTES - len(head) - sum(len(f"주제 {n},,naver_a,".encode("utf-8")) + 1 for n in range(count))
        base, extra = divmod(spare, count)                                                           # 남은 바이트를 메모 칸들에 고르게 나눠 정확히 5MB 로 맞춘다
        rows = [f"주제 {n},,naver_a," + "x" * (base + (1 if n < extra else 0)) for n in range(count)]
        text = head + "\n".join(rows).encode("utf-8") + b"\n"
        self.assertEqual(len(text), csvmod.MAX_CSV_BYTES)
        result = svc.import_csv(self.ctx, self.csv_file(text))
        self.assertEqual(result.summary(), f"0개 추가·0개 건너뜀·{csvmod.MAX_CSV_ROWS}개 거절")
        error = self.code(svc.import_csv, self.ctx, self.csv_file(text + b"x"))
        self.assertEqual(error.code, "CANDIDATE_CSV_INVALID")
        self.assertIn("5MB", error.slots["이유"])

    def test_a_file_with_only_a_header_stores_nothing_and_does_not_open_the_store(self):
        result = self.import_text(HEAD + "\n\n\n")
        self.assertEqual((result.summary(), result.rows, result.blank_lines), ("0개 추가·0개 건너뜀·0개 거절", 0, 2))
        self.assertFalse(self.root.exists())

    def test_the_candidates_get_numbers_in_the_order_of_the_file_even_when_made_in_the_same_second(self):
        topics = [f"주제 {index:02d}" for index in range(30)]
        for attempt in range(3):
            with self.subTest(attempt=attempt), tempfile.TemporaryDirectory() as other:
                ctx = ss.make_ctx(other, repo="")
                path = Path(other) / "x.csv"
                path.write_text(HEAD + "\n" + "\n".join(f"{topic},키워드 {index},naver_a" for index, topic in enumerate(reversed(topics))) + "\n", encoding="utf-8")
                result = svc.import_csv(ctx, path)
                self.assertEqual([row.ordinal for row in result.added], list(range(1, 31)))
                with ctx.store() as store:
                    listed = svc.numbered(store.list_candidates())
                self.assertEqual([row.candidate.topic for row in listed], list(reversed(topics)), "파일의 줄 순서 그대로")
                self.assertEqual({row.candidate.created_at for row in listed}, {ctx.stamp()}, "한 번 가져온 후보는 같은 시각이다")

    def test_a_data_date_after_tomorrow_costs_its_own_line_and_a_default_date_after_tomorrow_stops_the_command_before_the_file_is_read(self):
        today, tomorrow = self.ctx.stamp()[:10], (cd.parse_stamp(self.ctx.stamp()) + timedelta(days=1)).strftime("%Y-%m-%d")
        text = HEAD + ",월간 검색 수요,데이터 조회일\n오늘 줄,키워드 하나,naver_a,100," + today + "\n내일 줄,키워드 둘,naver_a,100," + tomorrow + "\n먼 미래 줄,키워드 셋,naver_a,100,2099-01-01\n날짜 없는 줄,키워드 넷,naver_a,,\n"
        result = self.import_text(text)
        self.assertEqual((result.summary(), [note.line for note in result.rejected]), ("3개 추가·0개 건너뜀·1개 거절", [4]))
        self.assertIn("오늘보다 뒤의 날짜", result.rejected[0].reason)
        self.assertIn(cd.LABELS["data_date"], result.rejected[0].reason)
        self.assertEqual([row.candidate.topic for row in self.stored()], ["오늘 줄", "내일 줄", "날짜 없는 줄"])
        self.fresh()
        path = self.csv_file(HEAD + "\n가,키워드 가,naver_a\n")
        for day in ("2099-01-01", (cd.parse_stamp(self.ctx.stamp()) + timedelta(days=2)).strftime("%Y-%m-%d")):
            with self.subTest(day=day):
                error = self.code(svc.import_csv, self.ctx, path, data_date=day)
                self.assertEqual((error.code, error.slots["항목"]), ("CANDIDATE_INVALID", cd.LABELS["data_date"]))
                self.assertIn("오늘보다 뒤의 날짜", error.slots["이유"])
        self.assertFalse(self.root.exists())
        self.assertEqual(svc.import_csv(self.ctx, path, data_date=tomorrow).summary(), "1개 추가·0개 건너뜀·0개 거절")

    def test_only_a_regular_file_is_read_not_a_folder_or_a_device_name(self):
        """`CON` 같은 장치 이름은 읽으면 끝없이 기다린다 — 읽기 전에 보통 파일인지 본다."""
        targets = [self.tmp, os.devnull]
        if sys.platform == "win32":
            targets += ["CON", "NUL", "con", "\\\\.\\NUL"]
        for target in targets:
            with self.subTest(target=str(target)):
                error = self.code(svc.import_csv, self.ctx, target)
                self.assertEqual(error.code, "CANDIDATE_CSV_INVALID")
                self.assertIn("보통 파일이 아닙니다", error.slots["이유"])
        self.assertFalse(self.root.exists())
        for missing in (self.tmp / "없는 파일.csv", self.tmp / "없는 폴더" / "후보.csv"):
            with self.subTest(missing=missing.name):
                error = self.code(svc.import_csv, self.ctx, missing)
                self.assertEqual(error.code, "CANDIDATE_CSV_INVALID")
                self.assertIn("파일을 읽을 수 없습니다", error.slots["이유"])

    def test_a_cell_that_cannot_be_read_in_a_line_of_several_physical_lines_says_how_many_lines_it_covers(self):
        result = self.import_text(HEAD + '\n주제 하나,키워드 하나,"naver_a\nnaver_zzz"\n정상,키워드 둘,naver_a\n')
        self.assertEqual((result.summary(), result.rejected[0].line), ("1개 추가·0개 건너뜀·1개 거절", 2))
        self.assertIn("알 수 없는 블로그", result.rejected[0].reason)
        self.assertIn("이 줄은 파일의 2줄에 걸쳐 있습니다", result.rejected[0].reason)
        plain = self.import_text(HEAD + "\n주제 둘,키워드 셋,naver_zzz\n")
        self.assertNotIn("걸쳐 있습니다", plain.rejected[0].reason, "한 줄짜리에는 붙이지 않는다")

    def test_a_giant_cell_and_an_overlong_topic_only_cost_their_own_lines(self):
        giant, long_topic = "가" * 200_000, "나" * 100_000
        text = HEAD + f'\n"{giant}",키워드 하나,naver_a\n{long_topic},키워드 둘,naver_a\n정상,키워드 셋,naver_a\n'
        result = self.import_text(text)
        self.assertEqual((result.summary(), [note.line for note in result.rejected]), ("1개 추가·0개 건너뜀·2개 거절", [2, 3]))
        self.assertIn("200자", result.rejected[0].reason, "읽기 도구의 칸 한도(128KB)를 넘은 칸도 칸 규칙(주제 200자)이 그 줄만 거절한다")
        self.assertIn("200자", result.rejected[1].reason)

    def test_a_quoted_cell_of_many_lines_beyond_the_reader_limit_leaves_no_phantom_candidate(self):
        """큰따옴표 속 여러 줄이 읽기 도구의 칸 크기 한도(128KB)를 넘어도 그 속의 줄이 '새 후보'로 들어가지 않는다 — 그 줄만 거절되고 뒤의 진짜 줄은 가져온다."""
        filler = "\n".join("x" * 100 for _ in range(1500))
        text = HEAD + ",추천 이유\n" + '진짜 첫 줄 주제,kw1,naver_a,"' + filler + '\n유령 줄 주제,ghostkw,naver_a,내용\n끝 따옴표 뒤"\n진짜 마지막 줄 주제,kw3,naver_a,ok\n'
        result = self.import_text(text)
        self.assertEqual((result.summary(), [note.line for note in result.rejected]), ("1개 추가·0개 건너뜀·1개 거절", [2]))
        self.assertIn("300자", result.rejected[0].reason)
        self.assertIn("1502줄에 걸쳐", result.rejected[0].reason, "여러 줄에 걸친 칸이라고 알린다")
        self.assertEqual([row.candidate.topic for row in self.stored()], ["진짜 마지막 줄 주제"], "유령 줄 주제는 들어가지 않았다")

    def test_hidden_characters_are_removed_but_look_alike_blanks_are_refused(self):
        text = HEAD + f"\n겨울{ZWSP} 보일러﻿,보일러{ZWSP}점검,naver_a\n빈칸처럼 보이는ㅤ글자,키워드 둘,naver_a\n탭\t과 줄바꿈이 든 주제,키워드 셋,naver_a\n"
        result = self.import_text(text)
        self.assertEqual([row.candidate.topic for row in result.added], ["겨울 보일러", "탭 과 줄바꿈이 든 주제"])
        self.assertEqual(result.added[0].candidate.keyword, "보일러점검")
        self.assertEqual((len(result.rejected), result.rejected[0].line), (1, 3))
        self.assertIn("눈에 보이지 않거나", result.rejected[0].reason)

    def test_a_comma_or_a_quote_inside_a_cell_is_kept_when_quoted_and_a_line_with_too_many_cells_is_refused(self):
        result = self.import_text(HEAD + '\n"겨울, 보일러 ""점검""",키워드 하나,naver_a\n겨울, 보일러,키워드 둘,naver_a\n')
        self.assertEqual([row.candidate.topic for row in result.added], ['겨울, 보일러 "점검"'])
        self.assertEqual((result.rejected[0].line, result.rejected[0].reason.startswith("열 수:")), (3, True))

    def test_numbers_and_words_in_the_metric_cells_are_read_in_their_common_spellings(self):
        text = ("주제,핵심 키워드,블로그,검색량,블로그 검색 결과 수,추세,모바일 비중,계절성,중복 여부,적합도,우선도,기회도,보조 키워드,글 유형,이유,조회일\n"
                '가,키워드,pages,"12,000","34,500.0",UP,72.5%,"11월,12월",아니오,81,"76.5",64,"키워드, 보조 하나, 보조 둘",비교,좋은 이유,2026-11-01\n')
        candidate = self.import_text(text).added[0].candidate
        self.assertEqual((candidate.search_demand, candidate.related_blog_results, candidate.trend, candidate.mobile_share, candidate.seasonality, candidate.duplicate),
                         (12000, 34500, "상승", 72.5, (11, 12), False))
        self.assertEqual((candidate.profile_fit, candidate.priority, candidate.keyword_opportunity, candidate.sub_keywords, candidate.post_type, candidate.reason, candidate.data_date),
                         (81, 76.5, 64, ("보조 하나", "보조 둘"), "비교형", "좋은 이유", "2026-11-01"))
        self.assertEqual(candidate.blogs, ("github_pages",))

    def test_unknown_columns_and_blank_lines_are_reported_and_ignored(self):
        result = self.import_text("번호,주제,핵심 키워드,대상 블로그,메모\n1,가,키워드 가,naver_a,x\n\n,,,,\n2,나,키워드 나,naver_a,y\n")
        self.assertEqual((result.summary(), result.unknown_columns, result.blank_lines, result.rows), ("2개 추가·0개 건너뜀·0개 거절", ("번호", "메모"), 2, 2))

    def test_a_store_error_in_the_middle_of_the_save_stores_nothing_and_the_same_command_does_the_whole_job(self):
        """가져오기는 한 트랜잭션이다 — 다섯 줄을 저장하다 셋째에서 멈추면 하나도 저장되지 않고(반쯤 들어간 상태가 없다) 같은 명령을 다시 하면 전부 들어간다."""
        text = HEAD + "\n" + "\n".join(f"주제{n},키워드{n},naver_a" for n in range(1, 6)) + "\n"
        path = self.csv_file(text)
        original, calls = Store._put_candidate, []

        def flaky(store, db, candidate, *args, **kwargs):
            calls.append(candidate.topic)
            if len(calls) == 3:
                raise AppError("DISK_FULL", detail="시험용 디스크 가득")
            return original(store, db, candidate, *args, **kwargs)

        with mock.patch.object(Store, "_put_candidate", autospec=True, side_effect=flaky):
            error = self.code(svc.import_csv, self.ctx, path)
        self.assertEqual((error.code, calls), ("DISK_FULL", ["주제1", "주제2", "주제3"]))
        self.assertIn("아무것도 저장하지 않았습니다", error.detail)
        self.assertIn("같은 명령을 다시 실행", error.detail)
        self.assertIn("시험용 디스크 가득", error.detail)
        self.assertEqual(self.stored(), [], "앞의 두 줄도 저장되지 않았다")
        with closing(sqlite3.connect(str(self.store_path))) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        again = svc.import_csv(self.ctx, path)
        self.assertEqual(again.summary(), "5개 추가·0개 건너뜀·0개 거절")
        self.assertEqual([row.candidate.topic for row in self.stored()], [f"주제{n}" for n in range(1, 6)])

    def test_a_locked_store_says_nothing_was_saved_and_a_broken_candidate_does_not_say_to_just_retry(self):
        path = self.csv_file(HEAD + "\n주제 하나,키워드 하나,naver_a\n")
        with mock.patch.object(Store, "add_candidates", autospec=True, side_effect=AppError("STORE_LOCKED", detail="시험용 잠김")):
            error = self.code(svc.import_csv, self.ctx, path)
        self.assertEqual(error.code, "STORE_LOCKED")
        self.assertIn("아무것도 저장하지 않았습니다", error.detail)
        self.assertIn("시험용 잠김", error.detail)
        for code in ("CANDIDATE_CORRUPT", "STORE_CONFLICT", "CANDIDATE_INVALID"):
            with self.subTest(code=code):
                slots = {"번호": "x"} if code == "CANDIDATE_CORRUPT" else ({"항목": "x"} if code == "STORE_CONFLICT" else {"항목": "x", "이유": "y"})
                with mock.patch.object(Store, "add_candidates", autospec=True, side_effect=AppError(code, slots, detail="시험용")):
                    error = self.code(svc.import_csv, self.ctx, path)
                self.assertNotIn("아무것도 저장하지 않았습니다", error.detail, "다시 실행해도 되는 오류가 아니면 그렇게 말하지 않는다")

    def test_the_check_for_an_existing_candidate_is_made_after_the_write_lock_is_taken(self):
        """'이미 있나 확인' 이 쓰기 잠금을 잡은 **뒤**에 있다는 것을 본다 — 잠금을 잡기 직전에 다른 프로세스가 같은 후보를 먼저 저장한 경우(두 곳에서 같은 파일을 동시에 가져올 때)를 흉내 낸다.
        확인을 잠금 밖에서 하면 이 후보를 못 보고 겹쳐 저장한다."""
        self.add("기존 후보")                                                  # 보관함 파일을 미리 만들어 둔다(열기가 잠금을 쓰지 않게)
        path = self.csv_file(HEAD + "\n겹칠 주제,겹칠 키워드,naver_a\n새 주제,새 키워드,naver_a\n")
        self.clock.advance(seconds=1)                                          # 먼저 저장된 후보는 기존 후보보다 늦게 만든 것이다(같은 초면 무작위 번호가 순서를 정한다)
        rival = Candidate.new("겹칠 주제", "겹칠 키워드", ("naver_a",), now=self.ctx.stamp())
        original, state = Store._begin, {"done": False}

        def begin(store):
            if not state["done"]:
                state["done"] = True
                with Store.open(self.store_path) as other:                  # 다른 프로세스가 같은 줄을 먼저 저장했다
                    other.save_candidate(rival)
            return original(store)

        with mock.patch.object(Store, "_begin", autospec=True, side_effect=begin):
            result = svc.import_csv(self.ctx, path)
        self.assertEqual(result.summary(), "1개 추가·1개 건너뜀·0개 거절")
        self.assertIn("순번 2", result.skipped[0].reason, "먼저 저장된 후보(순번 2)와 같다고 알린다")
        self.assertEqual(sorted(row.candidate.topic for row in self.stored()), ["겹칠 주제", "기존 후보", "새 주제"], "겹쳐 저장되지 않았다")

    def test_adding_the_same_candidate_from_two_places_at_once_keeps_one(self):
        """`add` 도 마찬가지다 — 잠금을 잡기 직전에 같은 후보가 다른 곳에서 저장됐으면 더하지 않고 그 후보를 알려 준다."""
        self.add("기존 후보")
        self.clock.advance(seconds=1)                                          # 먼저 저장된 후보는 기존 후보보다 늦게 만든 것이다(같은 초면 무작위 번호가 순서를 정한다)
        rival = Candidate.new("겹칠 주제", "겹칠 키워드", ("naver_a",), now=self.ctx.stamp())
        original, state = Store._begin, {"done": False}

        def begin(store):
            if not state["done"]:
                state["done"] = True
                with Store.open(self.store_path) as other:
                    other.save_candidate(rival)
            return original(store)

        with mock.patch.object(Store, "_begin", autospec=True, side_effect=begin):
            result = svc.add_candidate(self.ctx, topic="겹칠 주제", keyword="겹칠 키워드", blogs=("naver_a",))
        self.assertIsNone(result.row)
        self.assertEqual((result.twin.ordinal, result.twin.candidate.candidate_id), (2, rival.candidate_id))
        self.assertEqual(sorted(row.candidate.topic for row in self.stored()), ["겹칠 주제", "기존 후보"])

    def test_the_result_turns_into_plain_data(self):
        result = self.import_text(HEAD + "\n가,키워드 가,naver_a\n가,키워드 가,naver_a\n상위노출 보장,키워드,naver_a\n")
        data = result.to_dict()
        self.assertEqual((data["summary"], data["rows"], len(data["added"]), data["skipped"][0]["line"], data["rejected"][0]["line"]), ("1개 추가·1개 건너뜀·1개 거절", 3, 1, 3, 4))
        self.assertEqual(data["added"][0]["ordinal"], 1)

    def test_sub_keywords_equal_to_the_main_keyword_are_dropped_instead_of_refusing_the_row(self):
        result = self.import_text("주제,핵심 키워드,보조 키워드,대상 블로그\n가,보일러 점검,\"보일러 점검, 난방비, 난방비\",naver_a\n")
        self.assertEqual(result.added[0].candidate.sub_keywords, ("난방비",))

    def test_random_files_through_the_whole_import_never_raise_anything_unexpected(self):
        """무작위 파일(제어 글자·따옴표·NUL·이상한 열 …) 80개를 끝까지 가져와 본다 — 결과가 나오거나 CANDIDATE_CSV_INVALID 말고는 어떤 예외도 나오지 않는다(고정한 씨앗)."""
        rng, seen = random.Random(20261104), {"읽음": 0, "거절": 0}
        for _ in range(80):
            header = rng.choice([HEAD, HEAD + ",월간 검색 수요,데이터 조회일,모르는 열", "topic,keyword,blog", ""])
            rows = ["".join(rng.choice(pure.FuzzTest.PIECES) for _ in range(rng.randint(0, 12))) for _ in range(rng.randint(0, 6))]
            path = self.csv_file("\n".join([header, *rows]).encode("utf-8"))
            try:
                result = svc.import_csv(self.ctx, path, blogs=("naver_a",), data_date="2026-11-01")
            except AppError as error:
                self.assertEqual(error.code, "CANDIDATE_CSV_INVALID")
                seen["거절"] += 1
            else:
                self.assertEqual(len(result.added) + len(result.skipped) + len(result.rejected), result.rows)
                seen["읽음"] += 1
        self.assertGreater(seen["읽음"], 5)
        self.assertGreater(seen["거절"], 5)
        self.assertEqual(svc.list_candidates(self.ctx).total, len(self.stored()), "그 뒤에도 보관함은 멀쩡히 읽힌다")
        with self.ctx.store() as store:
            self.assertEqual(store.check(), [], "저장된 후보가 하나도 깨지지 않았다")

    def test_every_row_of_a_big_file_is_checked_for_a_duplicate_against_the_whole_store(self):
        self.add("가", "키워드 가")
        rows = "\n".join(f"주제{n},키워드{n},naver_a" for n in range(40))
        result = self.import_text(HEAD + "\n가,키워드 가,naver_a\n" + rows + "\n")
        self.assertEqual((len(result.added), len(result.skipped)), (40, 1))
        self.assertEqual(len(self.stored()), 41)


# ---- 화면에 쓰는 작은 도우미 --------------------------------------------------------------------------------------------------------------
class ClockAheadOfTheRealOneTest(Base):
    """맥락의 시계가 진짜 시각보다 앞서 있을 때(PC 시계를 잘못 맞춘 경우) — 명령이 '지금' 으로 진짜 시각이 아니라 맥락의 시계를 쓰는지 본다. 진짜 시각을 쓰면 고친 시각이 그 후보의 마지막 고친 시각보다 앞서 거절된다."""

    def setUp(self):
        super().setUp()
        self.clock.now = datetime(2099, 1, 1, tzinfo=timezone.utc)

    def test_every_command_that_changes_a_candidate_stamps_it_with_the_context_clock(self):
        """고친 시각이 '그 순간 맥락의 시계' 인지 — 진짜 시각을 쓰면(`now=None`) 모델이 '진짜 시각과 그 후보의 마지막 고친 시각 중 늦은 것' 을 써서 값이 달라진다."""
        project_id = self.project()
        for name in ("가", "나", "다", "라"):
            self.add(name)
        steps = (("고르기", lambda: svc.select_candidate(self.ctx, "1", "naver_a").row), ("보류", lambda: svc.move_candidate(self.ctx, "2", cd.HOLD).row),
                 ("제외", lambda: svc.move_candidate(self.ctx, "3", cd.REJECTED).row), ("되살리기", lambda: svc.restore_candidate(self.ctx, "3").row),
                 ("글 잇기", lambda: svc.link_candidate(self.ctx, "4", project_id).row), ("글 끊기", lambda: svc.unlink_candidate(self.ctx, "4").row))
        for name, step in steps:
            self.clock.advance(seconds=30)
            row = step()
            self.assertEqual(row.candidate.updated_at, self.ctx.stamp(), name)
            self.assertTrue(row.candidate.updated_at.startswith("2099"), name)
        self.assertEqual((self.one(1).status, self.one(2).status, self.one(3).status, self.one(4).project_id), (cd.SELECTED, cd.HOLD, cd.REVIEW, None))


class GuardsTest(Base):
    def test_a_blog_that_is_not_one_of_the_five_is_refused_before_the_store_is_asked_anything(self):
        self.add("가")
        with mock.patch.object(Store, "set_candidate_status", autospec=True) as moved, mock.patch.object(Store, "recent_selections", autospec=True) as recent:
            for blog in ("tistory", "", None, 5):
                with self.subTest(blog=blog):
                    self.assertEqual(self.code(svc.select_candidate, self.ctx, "1", blog).code, "CANDIDATE_INVALID")
        self.assertEqual((moved.call_count, recent.call_count), (0, 0), "보관함에 아무것도 묻지 않고 거절한다")
        self.assertEqual(self.one(1).status, cd.NEW)

    def test_an_error_that_is_not_about_the_line_is_not_swallowed_as_a_rejected_line(self):
        path = self.csv_file(HEAD + "\n가,키워드 가,naver_a\n")
        with mock.patch.object(Candidate, "new", side_effect=AppError("UNEXPECTED_ERROR", detail="시험용")):
            error = self.code(svc.import_csv, self.ctx, path)
        self.assertEqual(error.code, "UNEXPECTED_ERROR")
        self.assertFalse(self.root.exists(), "줄을 만들다 멈췄으니 보관함은 열지도 않았다")


class RangesTest(unittest.TestCase):
    def test_numbers_are_folded_into_ranges(self):
        for numbers, text in (([12, 13, 14, 17], "12~14, 17"), ([1], "1"), ([3, 1, 2], "1~3"), ([], ""), ([1, 3, 5], "1, 3, 5"), ([5, 6], "5~6"), ([9, 10, 11, 20, 21], "9~11, 20~21")):
            with self.subTest(numbers=numbers):
                self.assertEqual(fmt._ranges(numbers), text)


if __name__ == "__main__":
    unittest.main()
