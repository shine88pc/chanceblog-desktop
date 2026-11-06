"""홈 데이터(UI-C1c)의 순수 시험 — 새 홈 구역(Naver A·B 추천·작성 중 초안·최근 발행·KPI·연결 요약)의 뷰모델(`ui/core/board_view.py`)과 예시 데이터(`ui/core/services.py`). PySide6 없이 돈다.

운영자 2026-11-06 확인 요청 004 의 답(홈 구성 5·최근 발행 6·추천 후보 2)을 손으로 적은 기대값으로 못박는다:
  1) 추천은 채널마다 최대 5개, 줄은 제목·점수(정수만)·구간(80/65/50)·관심도 라벨뿐 — **월 검색량·문서 수는 칸도 글도 없다**.
  2) 점수 없음 → 링 없이 '점수 계산 전'(0점 아님) · 관심도 없음 → '관심도 데이터 부족' · 이전 점수 없음 → 변화량 숨김 · 예시 값에는 '예시' 꼬리표 · 후보 없음은 정상 빈 상태(쓰기 단추 없음).
  3) 구역마다 따로 상태를 가진다(한 구역의 읽기 실패가 다른 구역·홈 전체를 막지 않는다) · 내부 번호·영문 상태 이름·비밀 모양은 뷰모델의 글에 없다.
  4) 최근 발행의 날짜는 발행한 때뿐('발행일 확인 불가') · KPI 는 연결·집계 전이면 0 이 아니라 '연결 전'·'집계 전'.
"""
import ast
import dataclasses
import re
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.ui.core import app_state, board_view, services, text, timed  # noqa: E402
from chanceblog_desktop.ui.core import settings_view as sv  # noqa: E402
from chanceblog_desktop.ui.core.jobs import JobFailure  # noqa: E402
from chanceblog_desktop.ui.core.services import (BoardData, ChannelRead, DraftRow, HomeData, ListRead, RecentRow, RecommendRow, Topic)  # noqa: E402

KEY = "AI" + "za" + "R" * 35                       # 구글 키 모양의 가짜 값(조각을 이어 만들어 저장소에는 키 문자열이 없다)
KEY_B = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
NONE_OF = chr(0x200B)                              # 보이지 않는 글자(편집 도구가 이스케이프를 진짜 글자로 바꾸지 않게 코드 번호로 만든다)


def leaks(shown, key=KEY, size=6):
    """shown 에 key 의 연속된 size 글자 조각이 남아 있으면 그 조각들(반쪽으로 잘린 키도 잡는다). 비어 있어야 한다."""
    return sorted({key[i:i + size] for i in range(len(key) - size + 1) if key[i:i + size] in shown})


def texts_of(value):
    """뷰모델 속 모든 글(딕셔너리 키는 빼고 값만) — 접근 이름·꼬리표까지 한 줄로 이어 붙인다."""
    if isinstance(value, dict):
        return " ".join(texts_of(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(texts_of(item) for item in value)
    return "" if value is None else str(value)


def rec(title="주제", score=80, prev=None, interest="flat", sample=False, id_="r1"):
    return RecommendRow(id_, title, score, prev, interest, sample)


def channel(key="A", rows=(), **fields):
    values = {"name": "예시 이름", "enabled": True}
    values.update(fields)
    return ChannelRead(key, rows=tuple(rows), **values)


def board(channels=None, drafts=None, recent=None, sample=False):
    return BoardData(tuple(channels) if channels is not None else (channel("A"), channel("B")), drafts or ListRead(), recent or ListRead(), sample)


def data_with(board_value, **fields):
    return HomeData(topics=(Topic(id="t1", title="옛 후보", blogs=("A",), date="2026-11-01"),), done=3, pub=2, board=board_value, **fields)


def view_of(data, state="normal", **kwargs):
    return board_view.build_board_view(data, state, **kwargs)


class SampleDataTest(unittest.TestCase):
    def test_the_row_shapes_have_no_search_volume_and_no_document_count_field_at_all(self):
        """월 검색량·문서 수는 가져오지도 보이지도 않는다(운영자 결정 2) — 값 모양에 그 칸이 아예 없다."""
        names = {field.name for cls in (RecommendRow, ChannelRead, DraftRow, RecentRow, ListRead, BoardData) for field in dataclasses.fields(cls)}
        self.assertEqual({field.name for field in dataclasses.fields(RecommendRow)}, {"id", "title", "score", "prev_score", "interest", "sample"})
        for word in ("demand", "docs", "volume", "search", "count", "ratio"):
            self.assertEqual([name for name in names if word in name], [], word)

    def test_the_limits_and_the_channels_are_the_operator_values(self):
        self.assertEqual((services.HOME_LIMIT, services.HOME_CHANNELS), (5, ("A", "B")))
        self.assertEqual(services.INTERESTS, ("rising", "flat", "falling"))
        self.assertEqual(services.STAGES, ("generated", "review"))
        self.assertEqual(services.NO_STORE, ("missing", "old"))

    def test_the_example_board_is_all_marked_as_example_and_covers_every_state_once(self):
        sample = services.sample_board()
        self.assertTrue(sample.sample)
        rows = [row for item in sample.channels for row in item.rows]
        self.assertEqual([len(item.rows) for item in sample.channels], [5, 4])
        self.assertTrue(rows and all(row.sample for row in rows))
        self.assertTrue(all(row.sample for row in sample.drafts.rows + sample.recent.rows))
        self.assertTrue(any(row.score is None for row in rows) and any(row.interest is None for row in rows) and any(row.prev_score is None for row in rows))      # 점수 없음·관심도 없음·이전 점수 없음
        self.assertEqual({row.interest for row in rows if row.interest}, {"rising", "flat", "falling"})
        self.assertIsNone(sample.recent.rows[-1].published)                                                  # 발행일을 모르는 예시
        for row in rows:                                                                                     # 점수는 정수이거나 None
            self.assertTrue(row.score is None or (isinstance(row.score, int) and 0 <= row.score <= 100), row)
        self.assertEqual(services.sample_board("normal"), services.sample_board("normal"))                 # 같은 입력이면 같은 결과

    def test_example_scenarios_empty_partial_and_the_unknown_one(self):
        empty = services.sample_board("empty")
        self.assertEqual(([item.rows for item in empty.channels], empty.drafts.rows, empty.recent.rows), ([(), ()], (), ()))
        self.assertTrue(all(item.state == "ok" and item.enabled for item in empty.channels))                 # 비어 있어도 오류가 아니다
        partial = services.sample_board("partial")
        self.assertTrue(all(row.interest is None for item in partial.channels for row in item.rows))        # 관심도를 못 가져온 시나리오
        self.assertEqual(services.sample_board("offline"), services.sample_board("normal"))
        with self.assertRaises(ValueError):
            services.sample_board("nope")

    def test_the_fake_provider_carries_the_board_and_can_leave_it_out(self):
        load = lambda provider: provider.load_home(lambda *a: None, lambda: False)       # noqa: E731
        self.assertEqual(load(services.FakeHomeProvider()).board, services.sample_board("normal"))
        self.assertEqual(load(services.FakeHomeProvider("empty")).board, services.sample_board("empty"))
        self.assertEqual(load(services.FakeHomeProvider("partial")).board, services.sample_board("partial"))
        self.assertIsNone(load(services.FakeHomeProvider(board=None)).board)                                 # 새 구역을 읽지 않는 공급자('연결 전')
        mine = board()
        self.assertIs(load(services.FakeHomeProvider(board=mine)).board, mine)
        with self.assertRaises(JobFailure):
            load(services.FakeHomeProvider("error"))                                                         # 오류 시나리오는 예전처럼 홈 전체가 오류
        self.assertIsNone(HomeData().board)                                                                 # 새 칸의 기본값은 '읽지 않음'


class TimeTextTest(unittest.TestCase):
    def test_utc_stamps_become_korean_time_by_hand_written_values(self):
        for stamp, shown, day in (("2026-11-06T02:10:00Z", "2026-11-06 11:10", "2026-11-06"), ("2026-11-06T14:59:59Z", "2026-11-06 23:59", "2026-11-06"),
                                  ("2026-11-06T15:00:00Z", "2026-11-07 00:00", "2026-11-07"), ("2026-12-31T15:00:00Z", "2027-01-01 00:00", "2027-01-01"),
                                  ("2024-02-28T15:00:00Z", "2024-02-29 00:00", "2024-02-29"), ("2026-02-28T15:00:00Z", "2026-03-01 00:00", "2026-03-01")):
            self.assertEqual((board_view.time_text(stamp), board_view.date_text(stamp)), (shown, day), stamp)

    def test_anything_that_is_not_an_exact_utc_stamp_is_shown_as_nothing(self):
        for bad in ("", "2026-11-06", "2026-11-06T02:10:00", "2026-11-06T02:10:00+00:00", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z", "2026-11-06T24:00:00Z", "2026-11-06T02:61:00Z",
                    "9999-12-31T23:59:59Z", "0000-01-01T00:00:00Z", " 2026-11-06T02:10:00Z", "2026-11-06T02:10:00Z\n", None, 5, 2026.11, b"2026-11-06T02:10:00Z", ["2026-11-06T02:10:00Z"]):
            self.assertEqual((board_view.time_text(bad), board_view.date_text(bad)), ("", ""), repr(bad))


class RowViewTest(unittest.TestCase):
    def test_the_score_bands_follow_80_65_50_by_hand_written_values(self):
        for score, band, label in ((100, "high", "우선 추천"), (80, "high", "우선 추천"), (79, "good", "일반 후보"), (65, "good", "일반 후보"), (64, "mid", "보류"), (50, "mid", "보류"),
                                   (49, "low", "제외"), (1, "low", "제외"), (0, "low", "제외")):
            row = board_view.row_vm(rec(score=score), 1)
            self.assertEqual((row["score"], row["score_text"], row["ring"], row["band"], row["band_label"]), (score, str(score), True, band, label), score)

    def test_only_whole_scores_from_zero_to_one_hundred_get_a_ring_everything_else_is_score_not_computed_yet(self):
        for bad in (None, 101, -1, 92.5, True, False, "92", float("nan"), float("inf"), [92], {}):
            row = board_view.row_vm(rec(score=bad), 1)
            self.assertEqual((row["score"], row["score_text"], row["ring"], row["band"], row["band_label"]), (None, "점수 계산 전", False, None, ""), repr(bad))
            self.assertIn("점수 계산 전", row["a11y"])
            self.assertNotIn("0점", row["a11y"] + row["score_text"])                                       # 0점으로 그리지 않는다
        self.assertEqual(board_view.row_vm(rec(score=92.0), 1)["score"], 92)                                # 정수인 실수는 그 정수다

    def test_the_interest_label_says_data_missing_when_unknown_or_when_the_trend_was_not_fetched(self):
        for value, label in (("rising", "관심도 상승"), ("flat", "관심도 보통"), ("falling", "관심도 하락"), (None, "관심도 데이터 부족"), ("insufficient", "관심도 데이터 부족"),
                             ("상승", "관심도 데이터 부족"), ("", "관심도 데이터 부족"), (5, "관심도 데이터 부족")):
            row = board_view.row_vm(rec(interest=value), 1)
            self.assertEqual(row["interest"]["label"], label, repr(value))
            self.assertIn(label, row["a11y"])
        shown = board_view.row_vm(rec(interest="rising"), 1, trend_hidden=True)
        self.assertEqual(shown["interest"], {"key": "none", "label": "관심도 데이터 부족"})              # 못 가져온 지표로 표시했으면 값이 남아 있어도 보이지 않는다

    def test_the_change_is_hidden_without_a_previous_score_and_shows_up_down_or_flat_with_text_not_only_colour(self):
        for score, previous in ((80, None), (None, 80), (None, None), (80, 79.5), (80, True), (80, "79"), (80, 101), (80, -1), (80, float("nan"))):
            self.assertIsNone(board_view.row_vm(rec(score=score, prev=previous), 1)["delta"], (score, previous))
        up, down, flat = (board_view.row_vm(rec(score=score, prev=previous), 1) for score, previous in ((84, 80), (79, 83), (84, 84)))
        self.assertEqual((up["delta"]["kind"], up["delta"]["text"], up["delta"]["value"]), ("up", "▲ +4", 4))
        self.assertEqual((down["delta"]["kind"], down["delta"]["text"], down["delta"]["value"]), ("down", "▼ -4", -4))
        self.assertEqual((flat["delta"]["kind"], flat["delta"]["text"], flat["delta"]["value"]), ("flat", "― 변화 없음", 0))
        self.assertIn("4 상승", up["a11y"])
        self.assertIn("4 하락", down["a11y"])
        self.assertIn("변화 없음", flat["a11y"])

    def test_a_row_has_exactly_these_keys_no_volume_no_document_count_no_internal_number(self):
        row = board_view.row_vm(rec(id_="tc-naver_a-seed-aaaa000000000001"), 3)
        self.assertEqual(set(row), {"rank", "channel", "title", "score", "score_text", "ring", "band", "band_label", "delta", "interest", "sample", "sample_tag", "a11y"})
        self.assertEqual((row["rank"], row["channel"]), (3, ""))                                            # 채널은 `channel_vm` 이 열쇠(A·B)를 넘긴다 — 직접 부르면 비어 있다
        self.assertNotIn("tc-naver_a", repr(row))                                                           # 내부 번호는 뷰모델에 없다

    def test_example_values_carry_the_example_tag_and_real_values_do_not(self):
        shown, real = board_view.row_vm(rec(sample=True), 1), board_view.row_vm(rec(sample=False), 1)
        self.assertEqual((shown["sample"], shown["sample_tag"], real["sample"], real["sample_tag"]), (True, "예시", False, ""))
        self.assertIn("예시", shown["a11y"])
        self.assertNotIn("예시", real["a11y"])

    def test_a_key_in_a_title_is_masked_before_it_is_cut_and_never_survives_anywhere(self):
        for lead in range(0, 220, 7):
            row = board_view.row_vm(rec(title="가" * lead + " " + KEY), 1)
            self.assertEqual(leaks(row["title"] + row["a11y"], KEY, 5), [], lead)
            self.assertLessEqual(len(row["title"]), board_view.TITLE_LIMIT)
        self.assertEqual(board_view.row_vm(rec(title=NONE_OF + "진짜 제목" + NONE_OF), 1)["title"], "진짜 제목")


class ChannelViewTest(unittest.TestCase):
    def test_a_channel_with_rows_is_normal_and_counts_them(self):
        view = board_view.channel_vm(channel("A", [rec("하나", 90, id_="a"), rec("둘", 70, id_="b")], name="예시 이름 에이"))
        self.assertEqual((view["key"], view["name"], view["title"], view["state"], view["count"], view["count_text"]), ("A", "예시 이름 에이", "예시 이름 에이 추천", "normal", 2, "후보 2개"))
        self.assertEqual([(row["rank"], row["channel"], row["title"]) for row in view["rows"]], [(1, "A", "하나"), (2, "A", "둘")])
        self.assertEqual({row["channel"] for row in board_view.channel_vm(channel("B", [rec(id_="x")]))["rows"]}, {"B"})
        self.assertEqual((view["enabled"], view["enabled_text"], view["note"], view["error"]), (True, "켜짐", "", None))

    def test_no_candidates_is_a_normal_empty_state_not_an_error_and_has_no_write_button(self):
        view = board_view.channel_vm(channel("B"))
        self.assertEqual((view["state"], view["count"], view["rows"], view["error"]), ("empty", 0, [], None))
        self.assertEqual(view["empty"], {"title": "아직 추천할 후보가 없어요.", "desc": "후보가 만들어지면 점수가 높은 순서로 여기에 보여요."})
        self.assertNotIn("button", view)
        self.assertNotIn("button", view["empty"])
        for word in ("주제 분석", "분석 시작", "만들기", "저장", "발행하기"):
            self.assertNotIn(word, texts_of(view), word)                                                    # 쓰기 동작(후보 저장·초안 만들기·발행) 글이 없다

    def test_a_missing_or_old_store_is_a_normal_empty_state_with_an_easy_note(self):
        missing = board_view.channel_vm(channel("A", state="unavailable", reason="missing"))
        old = board_view.channel_vm(channel("A", state="unavailable", reason="old"))
        other = board_view.channel_vm(channel("A", state="unavailable", reason="???"))
        self.assertEqual([view["state"] for view in (missing, old, other)], ["empty", "empty", "empty"])
        self.assertEqual(missing["empty"]["desc"], "후보를 보관하는 파일이 아직 없어요. 이 화면은 읽기만 해서 새로 만들지 않았어요.")
        self.assertEqual(old["empty"]["desc"], "후보 보관함이 옛 구조라 읽지 않았어요. 이 화면은 읽기만 해서 바꾸지 않았어요.")
        self.assertEqual(other["empty"]["desc"], text.T["board_rec_empty_desc"])
        self.assertTrue(all(view["error"] is None for view in (missing, old, other)))

    def test_a_channel_with_generation_turned_off_says_so_and_unknown_is_not_off(self):
        off = board_view.channel_vm(channel("A", enabled=False))
        self.assertEqual((off["state"], off["enabled"], off["enabled_text"], off["off"]), ("off", False, "꺼짐", "이 채널은 후보 생성이 꺼져 있어요."))
        unknown = board_view.channel_vm(channel("A", [rec()], enabled=None))
        self.assertEqual((unknown["state"], unknown["enabled"], unknown["enabled_text"]), ("normal", None, ""))

    def test_a_failed_channel_shows_an_easy_sentence_and_one_code_line_only(self):
        failure = JobFailure("후보 보관함을 열지 못했어요. 파일은 바꾸지 않았어요.", code="TOPIC_STORE_CORRUPT")
        view = board_view.channel_vm(channel("A", state="failed", failure=failure))
        self.assertEqual(view["state"], "error")
        self.assertEqual(view["error"], {"title": "추천 후보를 읽지 못했어요.", "desc": "후보 보관함을 열지 못했어요. 파일은 바꾸지 않았어요.", "diag": "code: TOPIC_STORE_CORRUPT"})
        self.assertEqual(view["rows"], [])
        secret = board_view.channel_vm(channel("A", state="failed", failure=JobFailure("읽지 못했어요 " + KEY, code="X_" + KEY)))
        self.assertEqual(leaks(texts_of(secret), KEY, 5), [])
        lost = board_view.channel_vm(channel("A", state="failed", failure=None))
        self.assertEqual((lost["error"]["desc"], lost["error"]["diag"]), (text.T["job_failed"], "code: UNKNOWN"))

    def test_the_name_is_masked_then_cut_and_falls_back_to_the_plain_blog_label(self):
        for lead in range(0, 90, 5):
            shown = board_view.channel_vm(channel("A", name="가" * lead + " " + KEY))
            self.assertEqual(leaks(shown["name"] + shown["title"], KEY, 5), [], lead)
            self.assertLessEqual(len(shown["name"]), board_view.NAME_LIMIT)
        self.assertEqual([board_view.channel_vm(channel(key, name=name))["name"] for key, name in (("A", ""), ("B", "   "), ("A", NONE_OF * 3))], ["블로그 A", "블로그 B", "블로그 A"])

    def test_at_most_five_rows_are_taken_from_a_thousand_and_the_rest_are_never_touched(self):
        class Counting:
            """천 개를 하나씩 내어 주는 목록 — 몇 개를 꺼내 갔는지 센다(전부 읽어서 자르면 1000 이 된다)."""

            def __init__(self, total):
                self.total, self.taken = total, 0

            def __iter__(self):
                for number in range(1, self.total + 1):
                    self.taken += 1
                    yield rec(f"주제 {number}", 100 - number % 30, id_=f"r{number}")

        source = Counting(1000)
        view = board_view.channel_vm(dataclasses.replace(channel("A"), rows=source))
        self.assertEqual((view["count"], [row["rank"] for row in view["rows"]], [row["title"] for row in view["rows"]]), (5, [1, 2, 3, 4, 5], [f"주제 {n}" for n in range(1, 6)]))
        self.assertLessEqual(source.taken, services.HOME_LIMIT)

    def test_unreadable_candidates_left_out_by_the_service_are_told_in_one_easy_line(self):
        view = board_view.channel_vm(channel("A", [rec()], skipped=2))
        self.assertEqual(view["note"], "점수를 확인할 수 없어 뺀 후보가 2개 있어요.")
        for bad in (0, -1, None, True, "2", 1.5):
            self.assertEqual(board_view.channel_vm(channel("A", [rec()], skipped=bad))["note"], "", repr(bad))


class ListViewTest(unittest.TestCase):
    def drafts(self, *rows, **fields):
        return view_of(data_with(board(drafts=ListRead("ok", tuple(rows), **fields))))["drafts"]

    def recent(self, *rows, **fields):
        return view_of(data_with(board(recent=ListRead("ok", tuple(rows), **fields))))["recent"]

    def test_drafts_show_title_stage_and_korean_time_and_the_two_stages_have_their_own_words(self):
        shown = self.drafts(DraftRow("d1", "첫 초안", "review", "2026-11-06T02:10:00Z"), DraftRow("d2", "둘째 초안", "generated", "2026-11-06T15:00:00Z"))
        self.assertEqual(shown["state"], "normal")
        self.assertEqual([(row["rank"], row["title"], row["stage"], row["stage_label"], row["time"]) for row in shown["rows"]],
                         [(1, "첫 초안", "review", "검토 필요", "2026-11-06 11:10"), (2, "둘째 초안", "generated", "초안 생성됨", "2026-11-07 00:00")])
        self.assertEqual(shown["rows"][0]["a11y"], "첫 초안, 검토 필요, 2026-11-06 11:10")
        self.assertNotIn("d1", repr(shown))                                                                 # 내부 번호는 뷰모델에 없다

    def test_a_draft_with_an_unknown_stage_or_an_unreadable_time_hides_those_parts_and_invents_nothing(self):
        row = self.drafts(DraftRow("d1", "제목만", "approved", "어제"))["rows"][0]
        self.assertEqual((row["stage"], row["stage_label"], row["time"], row["a11y"]), ("", "", "", "제목만"))

    def test_recent_posts_show_the_published_date_and_say_unknown_when_it_is_unknown(self):
        shown = self.recent(RecentRow("p1", "발행 글", "2026-11-03T01:00:00Z"), RecentRow("p2", "날짜 모름", None), RecentRow("p3", "깨진 날짜", "2026-11-03"))
        self.assertEqual([(row["title"], row["date"], row["date_text"], row["known"]) for row in shown["rows"]],
                         [("발행 글", "2026-11-03", "2026-11-03", True), ("날짜 모름", "", "발행일 확인 불가", False), ("깨진 날짜", "", "발행일 확인 불가", False)])
        self.assertEqual(shown["rows"][1]["a11y"], "날짜 모름, 발행일 확인 불가")

    def test_the_recent_row_has_no_last_edited_field_so_it_cannot_stand_in_for_the_published_date(self):
        self.assertEqual({field.name for field in dataclasses.fields(RecentRow)}, {"id", "title", "published", "sample"})
        self.assertEqual(set(board_view.recent_vm(RecentRow("p", "글", None), 1)), {"rank", "title", "date", "date_text", "known", "sample", "sample_tag", "a11y"})

    def test_a_published_time_close_to_midnight_rolls_the_korean_date(self):
        row = self.recent(RecentRow("p1", "밤에 발행", "2026-11-06T15:30:00Z"))["rows"][0]
        self.assertEqual(row["date"], "2026-11-07")

    def test_each_list_has_at_most_five_rows_and_empty_or_failed_states(self):
        many = [DraftRow(f"d{n}", f"초안 {n}", "review", "2026-11-06T00:00:00Z") for n in range(1, 40)]
        self.assertEqual([row["title"] for row in self.drafts(*many)["rows"]], [f"초안 {n}" for n in range(1, 6)])
        many_recent = [RecentRow(f"p{n}", f"글 {n}", "2026-11-06T00:00:00Z") for n in range(1, 40)]
        self.assertEqual(len(self.recent(*many_recent)["rows"]), 5)
        empty_drafts, empty_recent = self.drafts(), self.recent()
        self.assertEqual((empty_drafts["state"], empty_drafts["rows"], empty_drafts["error"]), ("empty", [], None))
        self.assertEqual((empty_drafts["empty"]["title"], empty_drafts["empty"]["desc"]), ("작성 중인 초안이 없어요.", "초안을 만들면 여기에서 이어서 볼 수 있어요."))
        self.assertEqual((empty_recent["state"], empty_recent["empty"]["title"], empty_recent["empty"]["desc"]), ("empty", "아직 발행한 글이 없어요.", "글을 발행하면 여기에 날짜와 함께 보여요."))
        failed = view_of(data_with(board(drafts=ListRead("failed", (), 0, JobFailure("글 보관함을 열지 못했어요.", code="CONTENT_STORE_BUSY")))))["drafts"]
        self.assertEqual((failed["state"], failed["rows"], failed["error"]["desc"], failed["error"]["diag"]), ("error", [], "글 보관함을 열지 못했어요.", "code: CONTENT_STORE_BUSY"))
        self.assertEqual(failed["error"]["title"], "작성 중인 초안을 읽지 못했어요.")

    def test_skipped_posts_are_told_and_a_failed_list_never_blocks_the_other_sections(self):
        shown = self.drafts(DraftRow("d1", "초안", "review", ""), skipped=3)
        self.assertEqual(shown["note"], "읽지 못해 건너뛴 글이 3개 있어요.")
        mixed = view_of(data_with(board(drafts=ListRead("failed", (), 0, JobFailure("x", code="A")), recent=ListRead("ok", (RecentRow("p", "발행 글", "2026-11-03T01:00:00Z"),)),
                                        channels=(channel("A", [rec()]), channel("B", state="failed", failure=JobFailure("y", code="B"))))))
        self.assertEqual((mixed["drafts"]["state"], mixed["recent"]["state"], [item["state"] for item in mixed["recommend"]]), ("error", "normal", ["normal", "error"]))
        self.assertEqual(mixed["state"], "ready")                                                          # 구역 하나가 실패해도 홈은 그대로다

    def test_keys_in_titles_are_masked_in_both_lists(self):
        draft = self.drafts(DraftRow("d", "가" * 150 + " " + KEY, "review", ""))["rows"][0]
        recent = self.recent(RecentRow("p", "나" * 150 + " " + KEY_B, None))["rows"][0]
        self.assertEqual(leaks(draft["title"] + draft["a11y"], KEY, 5), [])
        self.assertEqual(leaks(recent["title"] + recent["a11y"], KEY_B, 5), [])


class KpiViewTest(unittest.TestCase):
    def kpi(self, data):
        return {item["key"]: item for item in view_of(data)["kpi"]}

    def test_the_four_kpis_keep_the_old_card_names_and_order(self):
        shown = view_of(data_with(board()))["kpi"]
        self.assertEqual([(item["key"], item["label"]) for item in shown], [("topics", "추천 주제"), ("done", "작성 완료"), ("pub", "발행 완료"), ("ideas", "저장된 아이디어")])

    def test_known_numbers_show_as_counts_and_a_real_zero_is_a_zero(self):
        data = HomeData(topics=(Topic(id="h", title="보류", blogs=("A",), status="hold"),), done=0, pub=7, board=board([channel("A", [rec(id_="a1"), rec(id_="a2")]), channel("B", [rec(id_="b1")])]))
        kpis = self.kpi(data)
        self.assertEqual([(kpis[key]["text"], kpis[key]["value"], kpis[key]["state"]) for key in ("topics", "done", "pub", "ideas")],
                         [("3개", 3, "value"), ("0개", 0, "value"), ("7개", 7, "value"), ("1개", 1, "value")])
        self.assertEqual(kpis["done"]["a11y"], "작성 완료 0개")
        self.assertEqual(kpis["topics"]["sub"], "")

    def test_a_count_that_is_not_known_is_never_shown_as_zero(self):
        data = HomeData(topics=(), done=None, pub=None, board=board())
        kpis = self.kpi(data)
        for key in ("done", "pub"):
            self.assertEqual((kpis[key]["text"], kpis[key]["value"], kpis[key]["state"], kpis[key]["sub"]), ("집계 전", None, "before_count", "아직 집계하지 않아요"), key)
            self.assertNotIn("0", kpis[key]["text"] + kpis[key]["a11y"])
        for bad in (-1, True, "3", 2.5, float("nan")):
            shown = self.kpi(HomeData(done=bad, pub=bad, board=board()))
            self.assertEqual((shown["done"]["state"], shown["pub"]["state"]), ("before_count", "before_count"), repr(bad))

    def test_before_the_home_data_arrives_every_kpi_is_not_counted_yet(self):
        for state in ("loading", "empty", "error"):
            shown = view_of(None, state)["kpi"]
            self.assertEqual([(item["text"], item["state"], item["value"]) for item in shown], [("집계 전", "before_count", None)] * 4, state)

    def test_a_provider_without_the_new_sections_leaves_the_recommended_count_not_connected_but_counts_the_rest(self):
        kpis = self.kpi(HomeData(topics=(), done=4, pub=1, board=None))
        self.assertEqual((kpis["topics"]["text"], kpis["topics"]["state"], kpis["topics"]["sub"], kpis["topics"]["value"]), ("연결 전", "before_connect", "아직 연결하지 않았어요", None))
        self.assertEqual((kpis["done"]["text"], kpis["pub"]["text"], kpis["ideas"]["text"]), ("4개", "1개", "0개"))
        self.assertEqual(kpis["topics"]["a11y"], "추천 주제 연결 전")

    def test_the_recommended_count_needs_every_channel_to_be_readable_and_waits_for_a_store(self):
        failure = JobFailure("x", code="Z")
        self.assertEqual(self.kpi(data_with(board([channel("A", [rec()]), channel("B", state="failed", failure=failure)])))["topics"]["state"], "before_count")   # 일부만 센 수를 합계로 내지 않는다
        gone = board([channel("A", state="unavailable", reason="missing"), channel("B", state="unavailable", reason="missing")])
        self.assertEqual(self.kpi(data_with(gone))["topics"]["state"], "before_connect")                         # 보관함이 아직 없다 — 0 이라고 하지 않는다
        none = self.kpi(data_with(board([channel("A"), channel("B")])))["topics"]
        self.assertEqual((none["text"], none["state"], none["value"]), ("0개", "value", 0))                      # 보관함은 있고 후보가 없다 — 진짜 0
        alone = self.kpi(data_with(board([channel("A", [rec()])])))["topics"]                                  # 공급자가 B 를 빠뜨려도 센다
        self.assertEqual((alone["text"], alone["state"]), ("1개", "value"))

    def test_the_recommended_count_never_counts_more_than_five_per_channel(self):
        many = [rec(f"주제 {n}", id_=f"r{n}") for n in range(1, 30)]
        self.assertEqual(self.kpi(data_with(board([channel("A", many), channel("B", many[:2])])))["topics"]["text"], "7개")

    def test_the_weekly_plus_n_text_of_the_old_cards_is_not_carried_over(self):
        shown = view_of(data_with(board()))
        self.assertNotIn("이번 주", texts_of(shown["kpi"]))


class ConnectionViewTest(unittest.TestCase):
    def test_before_the_settings_are_read_it_says_so_and_never_invents_a_status(self):
        shown = board_view.connection_vm(None)
        self.assertEqual((shown["state"], shown["text"], shown["tone"], shown["problem"]), ("before", "연결 상태를 아직 읽지 않았어요. 설정에서 확인할 수 있어요.", "muted", False))
        self.assertEqual(board_view.connection_vm(None, loading=True)["state"], "loading")
        self.assertEqual((board_view.connection_vm(None, "error")["state"], board_view.connection_vm(None, "error")["text"]), ("error", "연결 상태를 읽지 못했어요."))
        self.assertEqual(board_view.connection_vm(None, "error", loading=True)["state"], "loading")          # 다시 읽는 중이면 읽는 중

    def purposes(self, *specs):
        out = []
        for key, status, implemented, entries in specs:
            out.append(services.PurposeInfo(key, "용도 " + key, implemented, True, 3, "limited", False, status, tuple(services.EntryInfo(name, "active", True) for name in entries), None))
        return tuple(out)

    def test_the_summary_is_the_same_chips_the_settings_group_headers_show_on_one_line(self):
        data = services.ConnectionsData(self.purposes(("naver_apihub", "auth_error", False, ("예시 키",)), ("image_provider", "connected", True, ("예시 키",)), ("ai_assist", "not_connected", False, ()),
                                                      ("blogger", "needs_check", False, ("예시 키",))))
        shown = board_view.connection_vm(data, "normal")
        self.assertEqual(shown["text"], "준비 중 3 · 인증 정보 오류 1 · 연결 확인 필요 1 · 연결됨 1")            # 준비 중 먼저, 이어서 문제가 되는 것부터(설정 묶음 머리와 같은 순서)
        self.assertEqual((shown["state"], shown["tone"], shown["problem"], shown["sample"], shown["sample_tag"]), ("ready", "danger", True, False, ""))
        self.assertEqual(shown["a11y"], "연결 상태, 준비 중 3 · 인증 정보 오류 1 · 연결 확인 필요 1 · 연결됨 1")

    def test_the_tone_follows_the_worst_status_and_an_example_is_tagged(self):
        for specs, tone in ((( ("a", "rate_limited", False, ("k",)), ), "warning"), (( ("a", "connected", True, ("k",)), ), "ok"), (( ("a", "not_connected", True, ()), ), "muted")):
            self.assertEqual(board_view.connection_vm(services.ConnectionsData(self.purposes(*specs)))["tone"], tone, specs)
        sample = board_view.connection_vm(services.ConnectionsData((), sample=True))
        self.assertEqual((sample["sample"], sample["sample_tag"], sample["text"]), (True, "예시", "연결된 서비스가 아직 없어요."))
        self.assertTrue(sample["a11y"].endswith("예시"))

    def test_the_home_summary_is_the_sum_of_the_settings_group_headers_for_every_example_status(self):
        """홈의 한 줄은 설정 화면의 묶음 머리 칩을 모두 더한 것이다 — 같은 정보를 새로 읽지 않고 그대로 쓴다."""
        for scenario in services.CONN_SCENARIOS:
            data = services.FakeConnectionsProvider(scenario).load_connections(lambda *a: None, lambda: False) if scenario != "error" else None
            if data is None:
                continue
            view = sv.build_settings_view(data, "normal", open_groups=set())
            counted = {}
            for group in view["groups"]:
                for chip in group["chips"]:
                    label, number = chip["text"].rsplit(" ", 1)
                    counted[label] = counted.get(label, 0) + int(number)
            home = board_view.connection_vm(data, "normal")["text"]
            shown = {}
            for part in (home.split(" · ") if counted else []):
                label, number = part.rsplit(" ", 1)
                shown[label] = int(number)
            self.assertEqual(shown, counted, scenario)

    def test_the_example_settings_data_is_summarised_without_any_key_name_or_number_from_the_cards(self):
        data = services.FakeConnectionsProvider().load_connections(lambda *a: None, lambda: False)
        shown = board_view.connection_vm(data, "normal")
        self.assertTrue(shown["sample"] and shown["problem"])
        for entry in ("예시 키 1", "예시 키 A", "예시 키 B"):
            self.assertNotIn(entry, texts_of(shown))
        self.assertNotRegex(shown["text"], r"\d{2,}")                                                       # 사용량 숫자는 요약에 없다


class BoardViewTest(unittest.TestCase):
    def test_the_state_says_whether_the_home_data_is_loading_missing_or_from_a_provider_without_the_new_sections(self):
        loading = view_of(None, "loading")
        gone = view_of(None, "error")
        before = view_of(HomeData(done=1, board=None))
        ready = view_of(data_with(board()))
        self.assertEqual([item["state"] for item in (loading, gone, before, ready)], ["loading", "unavailable", "before_connect", "ready"])
        for shown in (loading, gone, before):                                                               # 읽기 전에도 구역은 늘 같은 모양으로 있다
            self.assertEqual([item["key"] for item in shown["recommend"]], ["A", "B"])
            self.assertEqual([item["state"] for item in shown["recommend"]], [shown["state"]] * 2)
            self.assertEqual((shown["drafts"]["state"], shown["recent"]["state"]), (shown["state"], shown["state"]))
            self.assertTrue(all(not item["rows"] for item in shown["recommend"]) and not shown["drafts"]["rows"] and not shown["recent"]["rows"])
        self.assertEqual(set(ready), {"state", "sample", "sample_tag", "kpi", "recommend", "drafts", "recent", "connection"})
        self.assertEqual(set(loading), set(ready))

    def test_the_two_channels_always_come_in_a_then_b_order_whatever_the_provider_sent(self):
        swapped = view_of(data_with(board([channel("B", [rec("비")], name="비 이름"), channel("A", [rec("에이")], name="에이 이름")])))
        self.assertEqual([(item["key"], item["name"], item["rows"][0]["title"]) for item in swapped["recommend"]], [("A", "에이 이름", "에이"), ("B", "비 이름", "비")])
        only_a = view_of(data_with(board([channel("A", [rec()])])))
        self.assertEqual([(item["key"], item["state"]) for item in only_a["recommend"]], [("A", "normal"), ("B", "empty")])
        extra = view_of(data_with(board([channel("A"), channel("B"), channel("C", [rec()])])))
        self.assertEqual([item["key"] for item in extra["recommend"]], ["A", "B"])                          # 홈은 A·B 만 본다

    def test_the_trend_that_was_not_fetched_hides_every_interest_even_when_values_are_left(self):
        rows = [rec(interest="rising"), rec(interest="falling")]
        shown = view_of(data_with(board([channel("A", rows)]), partial=("trend",)))
        self.assertEqual([row["interest"]["label"] for row in shown["recommend"][0]["rows"]], ["관심도 데이터 부족"] * 2)
        normal = view_of(data_with(board([channel("A", rows)])))
        self.assertEqual([row["interest"]["label"] for row in normal["recommend"][0]["rows"]], ["관심도 상승", "관심도 하락"])

    def test_nothing_in_the_board_is_a_write_action_and_nothing_names_a_search_volume_or_a_document_count(self):
        shown = view_of(data_with(services.sample_board()))
        flat = texts_of(shown)
        for word in ("월 검색량", "검색량", "문서 수", "블로그 문서", "주제 분석 시작", "초안 만들기", "발행하기", "저장하기", "전체 보기", "빠른 작업", "활용 팁"):
            self.assertNotIn(word, flat, word)

        def keys(value):
            if isinstance(value, dict):
                return set(value) | {inner for item in value.values() for inner in keys(item)}
            if isinstance(value, (list, tuple)):
                return {inner for item in value for inner in keys(item)}
            return set()
        for word in ("demand", "docs", "button", "action", "go", "id", "ids"):
            self.assertNotIn(word, keys(shown), word)

    def test_no_internal_number_or_english_state_name_reaches_any_text(self):
        hidden_ids = board([channel("A", [rec(id_="tc-naver_a-seed-aaaa000000000001")]), channel("B")], ListRead("ok", (DraftRow("proj-123456", "초안", "review", ""),)),
                           ListRead("ok", (RecentRow("proj-654321", "발행", None),)))
        flat = texts_of(view_of(data_with(hidden_ids)))
        for piece in ("tc-naver_a", "proj-123456", "proj-654321", "naver_a", "REVIEW_REQUIRED", "rising", "falling", "generated", "unavailable", "failed"):
            self.assertNotIn(piece, flat, piece)

    def test_the_example_board_is_marked_as_example_everywhere_and_a_real_one_never_is(self):
        shown = view_of(data_with(services.sample_board()))
        self.assertTrue(shown["sample"])
        rows = [row for item in shown["recommend"] for row in item["rows"]] + shown["drafts"]["rows"] + shown["recent"]["rows"]
        self.assertTrue(rows and all(row["sample"] and row["sample_tag"] == "예시" for row in rows))
        real = view_of(data_with(board([channel("A", [rec(sample=False)])], ListRead("ok", (DraftRow("d", "초안", "review", ""),)), ListRead("ok", (RecentRow("p", "발행", None),)))))
        self.assertFalse(real["sample"])
        self.assertTrue(all(not row["sample"] and row["sample_tag"] == "" for row in [row for item in real["recommend"] for row in item["rows"]] + real["drafts"]["rows"] + real["recent"]["rows"]))

    def test_a_key_in_any_text_never_survives_anywhere_in_the_board(self):
        dirty = board([channel("A", [rec("가" * 100 + KEY)], name="이름 " + KEY), channel("B", state="failed", failure=JobFailure("실패 " + KEY, code="C_" + KEY))],
                      ListRead("ok", (DraftRow("d", "초안 " + KEY, "review", ""),)), ListRead("ok", (RecentRow("p", "발행 " + KEY, None),)))
        flat = repr(view_of(data_with(dirty)))
        self.assertEqual(leaks(flat, KEY, 5), [])
        self.assertIn("가림", flat)


class HomeViewIntegrationTest(unittest.TestCase):
    def loaded(self, provider):
        state = app_state.AppState(provider)
        state.apply_home(provider.load_home(lambda *a: None, lambda: False))
        return state

    def test_home_view_carries_the_board_under_one_new_key_and_the_old_keys_stay(self):
        view = self.loaded(services.FakeHomeProvider()).home_view()
        self.assertEqual(set(view), {"title", "sub", "sample", "sample_tag", "state", "fetched", "cards", "chips", "section", "rows", "selected", "banner", "loading", "empty", "error", "rail", "board"})
        self.assertEqual(view["board"]["state"], "ready")
        self.assertEqual([card["key"] for card in view["cards"]], ["topics", "done", "pub", "ideas"])         # 옛 요약 카드는 그대로 있다(화면은 UI-C1d 까지 그대로)
        self.assertEqual(len(view["rows"]), 5)

    def test_the_board_follows_the_load_state_of_the_home(self):
        state = app_state.AppState(services.FakeHomeProvider(delay=5))
        self.assertEqual((state.list_state, state.home_view()["board"]["state"]), ("loading", "loading"))    # 만들자마자는 옛 홈과 같이 '읽는 중' 모습이다
        state.apply_failure(JobFailure("끊겼어요.", code="X"))
        self.assertEqual(state.home_view()["board"]["state"], "unavailable")                                 # 홈 전체를 못 읽었다
        self.assertEqual(self.loaded(services.FakeHomeProvider(board=None)).home_view()["board"]["state"], "before_connect")
        failing = self.loaded(services.FakeHomeProvider())
        failing.apply_failure(JobFailure("끊겼어요.", code="X"))                                           # 오류 뒤에도 받아 둔 데이터는 남아 새 구역도 그대로 있다
        self.assertEqual(failing.home_view()["board"]["state"], "ready")

    def test_each_scenario_gives_its_own_board_states(self):
        empty = self.loaded(services.FakeHomeProvider("empty")).home_view()["board"]
        self.assertEqual([item["state"] for item in empty["recommend"]] + [empty["drafts"]["state"], empty["recent"]["state"]], ["empty"] * 4)
        partial = self.loaded(services.FakeHomeProvider("partial")).home_view()["board"]
        self.assertTrue(all(row["interest"]["key"] == "none" for item in partial["recommend"] for row in item["rows"]))
        self.assertEqual(self.loaded(services.FakeHomeProvider("offline")).home_view()["board"]["state"], "ready")

    def test_the_connection_summary_reads_what_the_settings_already_read_and_reads_nothing_itself(self):
        state = self.loaded(services.FakeHomeProvider())
        before = state.home_view()["board"]["connection"]
        self.assertEqual((before["state"], state.conn_load_count), ("before", 0))                            # 홈을 그리는 것만으로는 설정을 읽지 않는다
        data = services.FakeConnectionsProvider().load_connections(lambda *a: None, lambda: False)
        state.apply_connections(data)
        after = state.home_view()["board"]["connection"]
        self.assertEqual((after["state"], after["sample"], state.conn_load_count), ("ready", True, 0))
        state.apply_conn_failure(JobFailure("x", code="Y"))
        self.assertEqual(state.home_view()["board"]["connection"]["state"], "ready")                         # 이미 읽은 값이 남아 있으면 그것을 쓴다
        fresh = app_state.AppState(services.FakeHomeProvider())
        fresh.apply_conn_failure(JobFailure("x", code="Y"))
        self.assertEqual(fresh.home_view()["board"]["connection"]["state"], "error")

    def test_the_old_view_model_keys_are_untouched_by_the_board(self):
        """옛 키(`board` 를 뺀 나머지)는 보드가 있든 없든 똑같다 — 새 구역은 새 키 하나로만 들어간다."""
        with_board = self.loaded(services.FakeHomeProvider()).home_view()
        without = self.loaded(services.FakeHomeProvider(board=None)).home_view()
        self.assertEqual({key: value for key, value in with_board.items() if key != "board"}, {key: value for key, value in without.items() if key != "board"})

    def test_a_secret_shape_anywhere_in_the_board_never_survives_the_whole_home_view_model(self):
        provider = services.FakeHomeProvider(board=board([channel("A", [rec("가" * 90 + KEY)], name="이름 " + KEY_B)], ListRead("ok", (DraftRow("d", KEY, "review", ""),)),
                                                          ListRead("ok", (RecentRow("p", KEY_B, None),))))
        state = self.loaded(provider)
        flat = repr(state.home_view())
        self.assertEqual((leaks(flat, KEY, 5), leaks(flat, KEY_B, 5)), ([], []))

    def test_the_board_never_calls_anything_but_the_providers_load_method(self):
        class Spy(services.HomeProvider):
            sample = False

            def __init__(self):
                self.calls = []

            def load_home(self, progress, cancelled):
                self.calls.append("load_home")
                return HomeData(board=services.sample_board())

            def connections_provider(self):
                self.calls.append("connections_provider")
                return services.FakeConnectionsProvider()

        spy = Spy()
        state = app_state.AppState(spy)
        state.apply_home(spy.load_home(lambda *a: None, lambda: False))
        for _ in range(3):
            state.home_view()
            state.drawer_view()
        self.assertEqual(spy.calls, ["connections_provider", "load_home"])                                  # 만들 때 짝 공급자를 받고, 불러올 때 읽는다 — 뷰모델을 만드는 일은 아무것도 부르지 않는다

    def test_the_state_takes_no_dead_today_argument_in_the_pure_part_too(self):
        """독립 검증 L1 — `today` 인자가 없다는 단언이 Qt 전용 시험에만 있으면 CI(PySide6 없음)에서 죽은 인자가 되살아나도 안 잡힌다 — 순수 시험에도 둔다."""
        with self.assertRaises(TypeError):
            app_state.AppState(services.FakeHomeProvider(), today="2026-11-03")


class TimedCallTest(unittest.TestCase):
    def test_a_read_that_finishes_in_time_gives_its_value_and_an_error_is_handed_back_as_it_was(self):
        self.assertEqual(timed.call_within(1, lambda a, b: a + b, 2, 3), 5)
        problem = ValueError("원래 오류")

        def broken():
            raise problem

        with self.assertRaises(ValueError) as caught:
            timed.call_within(1, broken)
        self.assertIs(caught.exception, problem)

    def test_a_read_that_takes_too_long_is_given_up_without_waiting_for_it(self):
        started = time.monotonic()
        with self.assertRaises(timed.ReadTimeout):
            timed.call_within(0.05, time.sleep, 2.0)
        self.assertLess(time.monotonic() - started, 1.2)
        for _ in range(3):                                                                                  # 여러 번 넘겨도 쌓여 막히지 않는다
            with self.assertRaises(timed.ReadTimeout):
                timed.call_within(0.02, time.sleep, 0.3)

    def test_no_time_left_means_the_work_is_not_even_started(self):
        ran = []
        for bad in (0, -1, -0.5, float("nan")):
            with self.assertRaises(timed.ReadTimeout):
                timed.call_within(bad, lambda: ran.append(1))
        self.assertEqual(ran, [])

    def test_the_thread_it_leaves_behind_cannot_keep_the_app_from_closing(self):
        names = []

        def slow():
            names.append(threading.current_thread())
            time.sleep(0.3)

        with self.assertRaises(timed.ReadTimeout):
            timed.call_within(0.02, slow)
        time.sleep(0.05)
        self.assertTrue(names and names[0].daemon)

    def test_the_helper_is_used_only_for_reads(self):
        source = (ROOT / "src" / "chanceblog_desktop" / "ui" / "adapters.py").read_text(encoding="utf-8")
        calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "call_within"]
        self.assertEqual([ast.unparse(node) for node in calls], ["call_within(min(self._item_timeout, left), show, ctx.reading_only(), project_id)"])      # 쓰는 일에는 쓰지 않는다 — 글 하나를 읽는 곳뿐


class DocsTest(unittest.TestCase):
    """결정 기록·UI 문서가 이 묶음의 약속을 말한다 — 위임 규칙 근거·한 가지 상태 낱말·검증 끝/닫음 낱말 없음(독립 검증 전)·옛 가지 번호와 안 겹침."""
    ROWS = (("D-190", "FIXING"), ("D-191", "FIXING"), ("D-192", "FIXING"), ("D-193", "FIXING"), ("D-194", "DEFERRED"))

    @staticmethod
    def doc(name):
        return (ROOT / "docs" / name).read_text(encoding="utf-8")

    def row(self, number):
        found = re.findall(rf"(?m)^\| {number} \|.*$", self.doc("DECISIONS.md"))
        self.assertEqual(len(found), 1, f"{number} 줄이 한 번만 있어야 한다")
        return found[0]

    def test_each_decision_has_a_delegation_basis_and_exactly_one_allowed_status_word(self):
        allowed = ("FIXING", "DECISION_REQUIRED", "DEFERRED", "VERIFIED", "CLOSED")
        for number, status in self.ROWS:
            row = self.row(number)
            self.assertIn("위임 규칙 근거", row, number)
            self.assertEqual([word for word in allowed if re.search(rf"상태: {word}\b", row)], [status], number)
            self.assertEqual([word for word in allowed if word in row], [status], f"{number}: 줄 안에 상태 낱말이 그 하나뿐이다(본문에서 다른 상태 낱말을 말하지 않는다)")
            self.assertEqual([word for word in ("VERIFIED", "CLOSED") if word in row], [], f"{number}: 독립 검증 전이라 검증 끝·닫음 상태는 쓰지 않는다")
            self.assertEqual(row.count(" | "), 3, f"{number}: 표의 칸은 넷이다(글 속에 세로줄이 없다)")
            self.assertTrue(row.rstrip().endswith("|"), number)

    def test_the_numbers_are_this_bundles_own_and_come_after_the_c1a_ones(self):
        numbers = re.findall(r"(?m)^\| (D-\d{3}) \|", self.doc("DECISIONS.md"))
        self.assertEqual([number for number in numbers if number in dict(self.ROWS)], [number for number, _status in self.ROWS])
        self.assertEqual(len(numbers), len(set(numbers)), "같은 번호가 두 번 나온다")
        self.assertGreater(numbers.index("D-190"), numbers.index("D-174"))

    def test_the_decisions_name_the_deferred_service_work_and_the_unseen_speed(self):
        deferred = self.row("D-194")
        for word in ("이전 점수", "채널 전체 후보 수", "엔진 읽기 속도", "최근 발행", "T2", "못 봤다"):
            self.assertIn(word, deferred, word)
        recent = self.row("D-192")
        for word in ("updated_at", "발행일 확인 불가", "1.5초", "4초", "못 봤다"):
            self.assertIn(word, recent, word)
        self.assertIn("`today`", self.row("D-193"))

    def test_the_ui_docs_say_the_new_sections_are_not_drawn_yet_and_the_changelog_has_the_entry(self):
        states, spec = self.doc("UI_STATES.md"), self.doc("UI_DESIGN_SPEC.md")
        self.assertIn("## 7. 홈의 새 구역(UI-C1c)", states)
        for word in ("그리지 않는다", "정상 빈 상태", "쓰기 단추 없음", "발행일 확인 불가", "연결 전", "집계 전"):
            self.assertIn(word, states, word)
        self.assertIn("홈 데이터(UI-C1c", spec)
        self.assertIn("board_view.py", self.doc("UI_COMPONENTS.md"))
        self.assertIn("UI-C1c", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIn("## 11. UI-C1c", self.doc("UI_VISUAL_QA.md"))


class SourceRulesTest(unittest.TestCase):
    CORE = ROOT / "src" / "chanceblog_desktop" / "ui" / "core"

    def test_the_view_model_file_has_no_writer_no_clock_read_and_no_qt(self):
        source = (self.CORE / "board_view.py").read_text(encoding="utf-8")
        for forbidden in ("datetime.now(", "datetime.datetime.now(", "date.today(", "utcnow(", "time.time(", "PySide6", "open(", "write_text", "write_json", "import requests", "urllib", "socket"):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", source), [])

    def test_the_new_texts_never_promise_and_name_no_search_volume(self):
        keys = [key for key in text.T if key.startswith("board_")]
        self.assertGreater(len(keys), 30)
        for key in keys:
            value = text.T[key]
            for word in text.FORBIDDEN + ("검색량", "문서 수"):
                self.assertNotIn(word, value, key)
            self.assertNotRegex(value, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", key)
            self.assertNotRegex(value, r"Traceback|Exception|Error\b|상대값", key)


if __name__ == "__main__":
    unittest.main()
