"""홈 모양(UI-C1d)의 순수 시험 — 새 홈의 뷰모델 규칙(`ui/core/app_state.py`·`board_view.py`·`part_rules.py`·`text.py`·`tokens.py`)과 '없앤 것이 되살아나지 않음'. PySide6 없이 돈다.

운영자 2026-11-06 확인 요청 004 의 답(홈 구성 5·추천 후보 2·최근 발행 6·상세 창 8)을 손으로 적은 기대값으로 못박는다:
  1) 홈은 제목(24px)·설명·KPI 넷·Naver A 추천(최대 5)·Naver B 추천(최대 5)·작성 중 초안(최대 5)·최근 발행(최대 5)·연결 상태 요약·기존 상세 서랍이다.
  2) 월 검색량·문서 수·`전체 보기`·빠른 작업·활용 팁·`초안 만들기`·빈 상태의 `주제 분석 시작`·미완성 화면으로 가는 길은 없다 — 값도 글도 코드도 없다.
  3) 추천 줄을 누르면 기존 상세 서랍이 열린다(서랍의 칸·동작은 그대로 — 줄이 아는 값만 채우고 모르는 값은 '데이터 없음').
  4) 열 수는 논리 폭에 따른 순수 규칙이다(KPI 4→2→1열, 구역은 두 칸이 들어가면 나란히).
"""
import ast
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import service_support as support  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.ui import adapters  # noqa: E402
from chanceblog_desktop.ui.core import app_state, board_view, icons, part_rules, services, text, tokens  # noqa: E402
from chanceblog_desktop.ui.core.jobs import JobFailure  # noqa: E402
from chanceblog_desktop.ui.core.services import BoardData, ChannelRead, HomeData, ListRead, RecommendRow, Topic  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
BANNED_WORDS = ("월 검색량", "검색량", "문서 수", "블로그 문서 수", "전체 보기", "빠른 작업", "활용 팁", "초안 만들기", "주제 분석 시작", "새 초안 만들기")


def loaded(provider=None):
    provider = provider or services.FakeHomeProvider()
    state = app_state.AppState(provider)
    state.apply_home(provider.load_home(lambda *a: None, lambda: False))
    return state


def texts_of(value):
    """뷰모델 속 모든 글(딕셔너리 키는 빼고 값만). `id` 칸은 서랍에 넘기는 열쇠라 글이 아니다."""
    if isinstance(value, dict):
        return " ".join(texts_of(item) for key, item in value.items() if key != "id")
    if isinstance(value, (list, tuple)):
        return " ".join(texts_of(item) for item in value)
    return "" if value is None else str(value)


def board_of(*channels, drafts=None, recent=None, **fields):
    return HomeData(board=BoardData(tuple(channels), drafts or ListRead(), recent or ListRead()), **fields)


def channel(key="A", rows=(), **fields):
    values = {"name": "예시 이름", "enabled": True}
    values.update(fields)
    return ChannelRead(key, rows=tuple(rows), **values)


class GridColumnsTest(unittest.TestCase):
    def test_the_column_rule_by_hand_written_boundaries(self):
        """한 칸 190·간격 16 이면 4열은 808, 2열은 396 부터다 — 경계에서 1px 모자라면 한 단계 아래 열 수."""
        for width, expected in ((0, 1), (189, 1), (190, 1), (395, 1), (396, 2), (807, 2), (808, 4), (5000, 4)):
            self.assertEqual(part_rules.grid_columns(width, (4, 2, 1), 190, 16), expected, width)
        self.assertEqual(part_rules.grid_columns(-5, (4, 2, 1), 190, 16), 1)                              # 놓이기 전의 폭도 마지막 열 수다
        self.assertEqual(part_rules.grid_columns(10, (3,), 100, 0), 3)                                    # 후보가 하나뿐이면 그것이다
        self.assertEqual(part_rules.grid_columns(300.0, (2, 1), 100, 0), 2)

    def test_the_home_columns_follow_the_token_widths(self):
        """홈 KPI 는 한 칸 190(`kpi_min_col`)·간격 16, 추천 구역은 한 칸 480(`section_min_col`)·글 구역(작성 중 초안·최근 발행)은 한 칸 400(`posts_min_col`)·구역 사이 간격 20 — 값은 토큰에서 온다."""
        self.assertEqual((tokens.LAYOUT["kpi_min_col"], tokens.LAYOUT["section_min_col"], tokens.LAYOUT["posts_min_col"], part_rules.HOME_KPI_GAP, tokens.LAYOUT["gap"]), (190, 480, 400, 16, 20))
        self.assertEqual(part_rules.HOME_KPI_OPTIONS, (4, 2, 1))
        self.assertEqual(part_rules.HOME_SECTION_OPTIONS, (2, 1))
        for width, kpi in ((395, 1), (396, 2), (644, 2), (807, 2), (808, 4), (1110, 4)):
            self.assertEqual(part_rules.home_kpi_columns(width), kpi, width)
        for width, sections in ((644, 1), (821, 1), (924, 1), (979, 1), (980, 2), (1008, 2), (1094, 2), (1264, 2)):  # 두 칸은 2×480+20=980 부터
            self.assertEqual(part_rules.home_section_columns(width), sections, width)
        for width, posts in ((628, 1), (819, 1), (820, 2), (908, 2), (1094, 2)):                                       # 글 구역은 2×400+20=820 부터
            self.assertEqual(part_rules.home_posts_columns(width), posts, width)

    def test_the_widths_the_brief_names_give_the_expected_layout(self):
        """본문 폭(창 폭 − 사이드바 208 − 쪽 여백 24×2 − 세로 막대 16): 1366(100%)→1094 두 칸 · 1536(1920 의 125%)→1264 두 칸 · 1280(1920 의 150%)→1008 두 칸 · 1180(최소 기준)→908 한 칸 · 1093(1366 의 125%)→821 한 칸 · 900(최소 창)→628 한 칸."""
        for window, body, sections, posts in ((1366, 1094, 2, 2), (1536, 1264, 2, 2), (1280, 1008, 2, 2), (1180, 908, 1, 2), (1093, 821, 1, 2), (900, 628, 1, 1)):
            self.assertEqual(window - tokens.FRAME["sidebar"] - 2 * tokens.LAYOUT["page_margin"] - 16, body, window)
            self.assertEqual((part_rules.home_section_columns(body), part_rules.home_posts_columns(body)), (sections, posts), window)

    def test_bad_inputs_are_a_code_mistake_and_say_so(self):
        for width in (True, "800", None, float("nan"), float("inf")):
            with self.assertRaises(ValueError, msg=repr(width)):
                part_rules.grid_columns(width, (2, 1), 100, 10)
        for options in ((), (0, 1), (2, True), (2.5,), ("2",)):
            with self.assertRaises(ValueError, msg=repr(options)):
                part_rules.grid_columns(500, options, 100, 10)
        for min_col, gap in ((0, 10), (-1, 10), (True, 10), (100, -1), (100, True), ("100", 10)):
            with self.assertRaises(ValueError, msg=repr((min_col, gap))):
                part_rules.grid_columns(500, (2, 1), min_col, gap)


class HomeShapeTest(unittest.TestCase):
    def test_the_two_columns_hold_the_two_recommendations_first_then_the_two_lists(self):
        """홈의 구역 순서(위→아래·왼쪽→오른쪽): KPI → Naver A 추천 → Naver B 추천 → 작성 중 초안 → 최근 발행 → 연결 상태 — 뷰모델의 `board` 가 이 순서로 담는다."""
        board = loaded().home_view()["board"]
        self.assertEqual(list(board)[:2], ["state", "sample"])
        self.assertEqual([item["key"] for item in board["kpi"]], ["topics", "done", "pub", "ideas"])
        self.assertEqual([item["key"] for item in board["recommend"]], ["A", "B"])
        self.assertEqual((board["drafts"]["title"], board["recent"]["title"], board["connection"]["title"]), ("작성 중인 초안", "최근 발행", "연결 상태"))

    def test_the_kpi_cards_have_the_icon_and_tone_of_the_old_summary_cards(self):
        """KPI 카드의 아이콘 바탕(아이콘·계열)은 옛 요약 카드와 같다 — 손으로 적은 값(추천 주제 draft·파랑 / 작성 완료 check_circle·초록 / 발행 완료 calendar_check·보라 / 저장된 아이디어 bulb·주황)."""
        kpi = loaded().home_view()["board"]["kpi"]
        self.assertEqual([(item["key"], item["icon"], item["tone"]) for item in kpi], [("topics", "draft", "blue"), ("done", "check_circle", "green"), ("pub", "calendar_check", "purple"), ("ideas", "bulb", "orange")])
        for item in kpi:
            self.assertIn(item["icon"], icons.ICONS)                                                            # 아이콘은 실제로 있는 것
            self.assertIn(item["tone"], tokens.TONES)
        for state_value in ("before_connect", "before_count"):                                                  # 값이 없는 모습에도 같은 아이콘·계열(카드가 흔들리지 않는다)
            shown = board_view.kpi_vm("done", "sum_done", None, state_value, "check_circle", "green")
            self.assertEqual((shown["icon"], shown["tone"]), ("check_circle", "green"))

    def test_a_kpi_that_is_not_connected_or_not_counted_is_never_a_zero(self):
        data = HomeData(topics=(), done=None, pub=None, board=None)
        kpi = {item["key"]: item for item in board_view.kpi_vms(data, None)}
        self.assertEqual((kpi["topics"]["text"], kpi["topics"]["state"]), ("연결 전", "before_connect"))
        self.assertEqual((kpi["done"]["text"], kpi["pub"]["text"]), ("집계 전", "집계 전"))
        self.assertEqual(kpi["ideas"]["text"], "0개")                                                           # 보류가 정말 없으면 진짜 0
        for item in kpi.values():
            self.assertTrue(item["text"] == "0개" or "0" not in item["text"], item["key"])

    def test_the_rows_carry_the_score_ring_facts_and_a_missing_score_has_no_ring(self):
        rows = [row for item in loaded().home_view()["board"]["recommend"] for row in item["rows"]]
        self.assertEqual([(row["score"], row["ring"], row["score_text"], row["band_label"]) for row in rows[:5]],
                         [(92, True, "92", "우선 추천"), (84, True, "84", "우선 추천"), (79, True, "79", "일반 후보"), (71, True, "71", "일반 후보"), (None, False, "점수 계산 전", "")])
        self.assertEqual([row["delta"]["text"] if row["delta"] else None for row in rows[:5]], ["▲ +4", "― 변화 없음", "▼ -4", None, None])       # 이전 점수가 없으면 변화량이 없다
        self.assertTrue(all(row["sample"] and row["sample_tag"] == "예시" for row in rows))
        self.assertEqual(rows[4]["interest"]["label"], "관심도 데이터 부족")
        for row in rows:
            self.assertNotIn("검색량", texts_of(row))


class IdleTextTest(unittest.TestCase):
    def test_a_home_that_was_not_read_says_not_loaded_yet_and_never_says_there_are_no_candidates(self):
        """읽는 중·못 읽음·새 구역을 안 읽는 공급자일 때 구역 자리의 문장은 `후보가 없어요` 가 아니다 — 없는 것이 아니라 못 읽었을 뿐이다(손으로 적은 문장)."""
        state = app_state.AppState(services.FakeHomeProvider(delay=5))                                          # 읽는 중
        failed = app_state.AppState(services.FakeHomeProvider())
        failed.apply_failure(JobFailure("끊겼어요.", code="X"))
        disconnected = loaded(services.FakeHomeProvider(board=None))
        for name, view, sections_state, title in (("읽는 중", state.home_view()["board"], "loading", "아직 불러오지 않았어요."), ("못 읽음", failed.home_view()["board"], "unavailable", "아직 불러오지 않았어요."),
                                                  ("연결 전", disconnected.home_view()["board"], "before_connect", "아직 연결하지 않았어요.")):
            self.assertEqual(view["state"], sections_state, name)
            for section in [*view["recommend"], view["drafts"], view["recent"]]:
                self.assertEqual(section["state"], sections_state, name)
                self.assertEqual(section["empty"]["title"], title, name)
                self.assertNotIn("후보가 없어요", texts_of(section["empty"]), name)
                self.assertEqual(section["rows"], [], name)
        self.assertEqual(failed.home_view()["board"]["recommend"][0]["empty"]["desc"], "다시 불러오면 이 자리에 보여요.")
        self.assertEqual(disconnected.home_view()["board"]["recommend"][0]["empty"]["desc"], "읽을 수 있게 연결되면 이 자리에 보여요.")

    def test_a_normal_empty_section_keeps_its_own_words(self):
        board = loaded(services.FakeHomeProvider("empty")).home_view()["board"]
        for section in [*board["recommend"], board["drafts"], board["recent"]]:
            self.assertEqual(section["state"], "empty")
        self.assertEqual(board["recommend"][0]["empty"]["title"], "아직 추천할 후보가 없어요.")
        self.assertEqual((board["drafts"]["empty"]["title"], board["recent"]["empty"]["title"]), ("작성 중인 초안이 없어요.", "아직 발행한 글이 없어요."))


class InterestAndConnectionLookTest(unittest.TestCase):
    def test_the_interest_picks_its_icon_and_trend_color_by_hand_written_values(self):
        for key, trend, icon, label in (("rising", "up", "trend_up", "관심도 상승"), ("flat", "flat", "trend_flat", "관심도 보통"), ("falling", "down", "trend_down", "관심도 하락"), (None, "none", None, "관심도 데이터 부족")):
            shown = board_view.interest_vm(key)
            self.assertEqual((shown["trend"], shown["icon"], shown["label"]), (trend, icon, label), key)
        for icon in ("trend_up", "trend_flat", "trend_down"):
            self.assertEqual(app_state.TREND_ICON[icon.split("_")[1]], icon)                                    # 아이콘 이름은 옛 추세 칸과 같은 것이다

    def test_the_connection_icon_follows_the_tone_and_always_comes_with_words(self):
        for tone, icon in (("ok", "check_circle"), ("warning", "alert"), ("danger", "alert"), ("muted", "info_circle")):
            self.assertEqual(board_view.CONNECTION_ICONS[tone], icon)
        before = board_view.connection_vm(None, "")
        self.assertEqual((before["tone"], before["icon"], before["text"]), ("muted", "info_circle", "연결 상태를 아직 읽지 않았어요. 설정에서 확인할 수 있어요."))
        error = board_view.connection_vm(None, "error")
        self.assertEqual((error["tone"], error["icon"], error["text"]), ("warning", "alert", "연결 상태를 읽지 못했어요."))
        ready = board_view.connection_vm(services.FakeConnectionsProvider().load_connections(lambda *a: None, lambda: False), "normal")
        self.assertEqual(ready["state"], "ready")
        self.assertIn(ready["icon"], board_view.CONNECTION_ICONS.values())
        self.assertTrue(ready["text"])                                                                          # 색·아이콘만이 아니라 글이 늘 함께 있다


class DrawerOfARowTest(unittest.TestCase):
    """추천 줄을 누르면 **기존 상세 서랍**이 열린다 — 서랍의 칸과 동작은 그대로이고(새 칸 없음) 줄이 아는 값만 채운다."""

    def test_the_drawer_of_a_row_has_the_same_fields_as_an_old_candidates_and_only_known_values(self):
        state = loaded()
        self.assertTrue(state.open_drawer("rA1"))
        shown = state.drawer_view()
        old = loaded()
        old.open_drawer("s1")
        self.assertEqual([field["label"] for field in shown["fields"]], [field["label"] for field in old.drawer_view()["fields"]])        # 칸이 같다(새 칸 없음)
        self.assertEqual(set(shown), set(old.drawer_view()))                                                                               # 키도 같다
        self.assertEqual((shown["topic"], shown["blog_label"], shown["priority"], shown["reason"]), ("자취방 곰팡이 없애는 순서", "블로그 A", "데이터 없음", "데이터 없음"))
        values = {field["label"]: field["value"] for field in shown["fields"]}
        self.assertEqual(values["최근 트렌드"], "상승")                                                                                      # 관심도(상승)가 서랍에 이미 있는 '최근 트렌드' 칸에 들어간다
        for label in ("월간 검색량", "PC·모바일 검색 비중", "관련 블로그 검색 결과 수", "계절성", "기존 작성 여부", "보조 키워드", "데이터 조회일"):
            self.assertEqual(values[label], "데이터 없음", label)                                                                              # 모르는 값은 지어내지 않는다
        self.assertEqual([button["key"] for button in shown["drafts"]], ["A"])
        self.assertTrue(shown["sample"])                                                                                                   # 예시 데이터의 서랍은 예시 표시

    def test_a_row_without_a_known_interest_or_with_the_trend_not_fetched_shows_no_trend(self):
        state = loaded()
        state.open_drawer("rA4")                                                                                                           # 예시: 관심도 없음
        self.assertEqual({field["label"]: field["value"] for field in state.drawer_view()["fields"]}["최근 트렌드"], "데이터 없음")
        data = board_of(channel("A", [RecommendRow("r1", "주제", 80, None, "rising")]), channel("B"), partial=("trend",))
        hidden = app_state.AppState(services.FakeHomeProvider())
        hidden.apply_home(data)
        hidden.open_drawer("r1")
        self.assertEqual({field["label"]: field["value"] for field in hidden.drawer_view()["fields"]}["최근 트렌드"], "데이터 없음")        # 못 가져온 지표로 표시했으면 값이 남아 있어도 보이지 않는다

    def test_only_the_rows_the_home_shows_can_open_a_drawer_and_old_candidates_still_can(self):
        rows = tuple(RecommendRow(f"r{n}", f"주제 {n}", 70, None, None) for n in range(1, 8))
        state = app_state.AppState(services.FakeHomeProvider())
        state.apply_home(HomeData(topics=(Topic(id="old", title="옛 후보", blogs=("B",)),), board=BoardData((channel("A", rows), channel("B")), ListRead(), ListRead())))
        self.assertTrue(state.open_drawer("r5"))
        self.assertFalse(state.open_drawer("r6"))                                                                                          # 여섯째는 홈에 없다
        self.assertEqual(state.drawer_id, "r5")                                                                                            # 열지 못한 시도는 열린 서랍을 건드리지 않는다
        self.assertTrue(state.open_drawer("old"))
        self.assertEqual(state.drawer_view()["blog_label"], "블로그 B")
        self.assertFalse(state.open_drawer("nope"))

    def test_a_row_drawer_masks_a_key_shaped_title_and_never_invents_a_priority(self):
        fake = "AI" + "za" + "K" * 35
        state = app_state.AppState(services.FakeHomeProvider())
        state.apply_home(board_of(channel("A", [RecommendRow("r1", f"제목 {fake}", 90, None, "flat")]), channel("B")))
        state.open_drawer("r1")
        shown = state.drawer_view()
        self.assertNotIn(fake, repr(shown))
        self.assertIn("가림", shown["topic"])
        self.assertEqual(shown["priority"], text.NO_DATA)                                                                                  # 옛 '작성 우선도' 를 엔진 점수로 대신하지 않는다

    def test_the_drawer_topic_of_the_board_is_a_read_only_lookup(self):
        data = loaded().data
        before = repr(data)
        self.assertEqual(board_view.drawer_topic(data, "rB2").blogs, ("B",))
        self.assertIsNone(board_view.drawer_topic(data, "nope"))
        self.assertIsNone(board_view.drawer_topic(None, "rA1"))
        self.assertIsNone(board_view.drawer_topic(HomeData(), "rA1"))                                                                      # 새 구역을 안 읽는 공급자
        self.assertEqual(repr(data), before)


class BannerAndStateTest(unittest.TestCase):
    def test_the_banner_comes_from_the_data_flags_even_when_there_are_no_old_candidates(self):
        offline = app_state.AppState(services.FakeHomeProvider())
        offline.apply_home(board_of(channel("A"), channel("B"), offline=True))
        self.assertEqual((offline.list_state, offline.home_view()["banner"]), ("empty", ("cloud_off", text.T["offline"])))
        partial = app_state.AppState(services.FakeHomeProvider())
        partial.apply_home(board_of(channel("A"), channel("B"), partial=("trend",)))
        self.assertEqual(partial.home_view()["banner"], ("alert", text.T["partial"]))
        both = app_state.AppState(services.FakeHomeProvider())
        both.apply_home(board_of(channel("A"), channel("B"), partial=("trend",), offline=True))
        self.assertEqual(both.home_view()["banner"][0], "cloud_off")                                                                        # 오프라인이 먼저(옛 규칙과 같다)
        self.assertIsNone(loaded().home_view()["banner"])

    def test_loading_and_error_have_no_banner_and_the_error_card_replaces_the_sections(self):
        view = app_state.AppState(services.FakeHomeProvider(delay=5)).home_view()
        self.assertEqual((view["state"], view["banner"], view["board"]["state"]), ("loading", None, "loading"))
        state = loaded(services.FakeHomeProvider("offline"))
        state.apply_failure(JobFailure("끊겼어요.", code="X"))
        view = state.home_view()
        self.assertEqual((view["state"], view["banner"]), ("error", None))                                                                  # 오류에는 띠가 없다(오류 안내가 자기 말을 한다)
        self.assertEqual(view["error"]["button"], "다시 시도")

    def test_a_reload_that_keeps_the_old_data_shows_no_banner_while_it_loads(self):
        # 독립 검증 UI-C1d L2(변이 P20): 다시 읽는 동안(`list_state == "loading"`)에는 옛 데이터가 남아 있어도 띠(오프라인·일부만)를 보이지 않는다 — 읽는 중에는 '읽는 중' 이 말한다.
        state = loaded(services.FakeHomeProvider("offline"))
        self.assertIsNotNone(state.home_view()["banner"])                                                                                  # 읽은 뒤에는 띠가 있다
        state.list_state = "loading"                                                                                                       # start_load 가 하는 일 — 데이터는 그대로 둔 채
        view = state.home_view()
        self.assertEqual((view["state"], view["banner"]), ("loading", None))

    def test_the_refresh_text_and_the_fetched_caption_stay_for_the_working_reload(self):
        view = loaded().home_view()
        self.assertEqual((view["refresh"], view["fetched"]), ("다시 불러오기", "마지막 조회 오늘 09:12"))


class HomeConnectionsReadTest(unittest.TestCase):
    """홈이 열릴 때 설정 정보를 함께 읽는 배선(UI-C1d, D-203 — 리드의 결정: **모든 보관함 상태에서 전후 파일이 바이트까지 같음을 못박을 수 있을 때만** 배선). 셸이 앱이 열릴 때 부르는 길 그대로 —
    `AppState.start_conn_load`(작업 스레드) → 짝 공급자(`ServiceConnectionsProvider`)의 읽기 → 값을 받아 적용 — 을 실제 서비스·임시 폴더의 가짜 보관소(자격 증명 관리자는 안 건드린다)로 돌리고
    넷(없음·옛 구조·깨짐·정상)에서 폴더 안 모든 파일의 바이트와 보관소 내용이 같은지, `.bak`·옮긴 파일·새 폴더가 없는지 본다. 실패는 그 한 줄만 `연결 상태를 읽지 못했어요.` 이고 홈의 나머지는 그대로다."""
    HUB = {"client_id": "hubclient001", "client_secret": "A1b2C3d4E5f6G7h8"}
    IMAGE = {"access_key": "B1c2D3e4F5g6H7i8J9k0"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = support.make_ctx(self.tmp.name, repo="")
        self.provider = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: self.ctx)
        self.state = app_state.AppState(self.provider)
        self.assertIsInstance(self.state.conn_provider, adapters.ServiceConnectionsProvider)                  # 짝 공급자(같은 데이터 폴더)

    def read(self):
        """셸이 하는 것과 같은 길로 한 번 읽는다 → 읽은 값 또는 실패."""
        done, box = threading.Event(), {}
        job = self.state.start_conn_load(on_done=lambda data, payload: (box.update(data=data), done.set()), on_error=lambda failure, payload: (box.update(failure=failure), done.set()))
        self.assertIsNotNone(job)
        self.assertTrue(done.wait(15))
        job.join(2)
        if "data" in box:
            self.state.apply_connections(box["data"])
        else:
            self.state.apply_conn_failure(box["failure"])
        return box

    def snapshot(self):
        return support.tree_snapshot(self.tmp.name), dict(self.ctx.keystore._blobs)

    def unchanged_after_reading(self, times=2):
        before = self.snapshot()
        for _ in range(times):
            self.read()
        self.assertEqual(self.snapshot(), before)                                                             # 폴더 안 모든 파일의 바이트와 보관소 내용이 같다
        added = sorted(set(support.tree_snapshot(self.tmp.name)) - set(before[0]))
        self.assertEqual(added, [])                                                                           # `.bak`·옮긴 파일·잠금 파일이 새로 생기지 않았다(설정할 때 만든 `.bak` 은 이미 앞에 있었다)

    def test_nothing_exists_yet_reading_creates_no_folder_and_no_file(self):
        self.assertFalse(self.ctx.workspace.root.exists())
        self.unchanged_after_reading()
        self.assertFalse(self.ctx.workspace.root.exists(), "데이터 폴더를 만들었다")
        line = self.state.home_view()["board"]["connection"]
        self.assertEqual(line["state"], "ready")
        self.assertIn("준비 중", line["text"])                                                              # 키가 없는 처음 PC — 모두 준비 중·연결 안 됨
        self.assertFalse(line["problem"])

    def test_an_old_structure_file_with_legacy_entries_is_read_as_it_is(self):
        cn.add_entry(self.ctx, "naver_openapi", name="옛 키", fields={"client_id": "oldclient001", "client_secret": "oldsecret0001"}, keystore=self.ctx.keystore, registry=support.generic_registry())
        self.unchanged_after_reading()
        self.assertEqual(self.state.conn_state, "normal")
        self.assertTrue(self.state.home_view()["board"]["connection"]["text"])

    def test_a_broken_connection_file_and_a_broken_usage_record_are_left_exactly_as_they_were(self):
        cn.add_entry(self.ctx, "naver_apihub", name="내 키", fields=self.HUB, keystore=self.ctx.keystore)
        self.ctx.workspace.connections_path.write_text("{ 깨진 연결 설정 ", encoding="utf-8")
        self.ctx.workspace.quota_path.write_text("{ 깨진 사용량 기록", encoding="utf-8")
        self.unchanged_after_reading()
        self.assertEqual((self.state.conn_state, self.state.conn_data), ("error", None))
        line = self.state.home_view()["board"]["connection"]
        self.assertEqual((line["state"], line["text"], line["tone"]), ("error", "연결 상태를 읽지 못했어요.", "warning"))                # 그 한 줄만 — 쉬운 문장
        self.assertNotIn("CONNECTIONS_FILE_INVALID", repr(line))                                              # 코드는 줄에 없다(진단 정보는 설정 화면)

    def test_a_normal_store_with_entries_and_usage_is_read_without_any_write(self):
        cn.add_entry(self.ctx, "naver_apihub", name="내 키", fields=self.HUB, keystore=self.ctx.keystore)
        cn.add_entry(self.ctx, "image_provider", name="이미지 키", fields=self.IMAGE, keystore=self.ctx.keystore)
        self.unchanged_after_reading(times=3)
        line = self.state.home_view()["board"]["connection"]
        self.assertEqual((line["state"], line["sample"]), ("ready", False))                                   # 실제 읽기라 예시가 아니다
        self.assertEqual(self.state.conn_state, "normal")
        self.assertEqual(self.state.conn_load_count, 3)

    def test_the_read_never_asks_for_a_key_value_only_whether_the_store_has_it(self):
        """홈이 열릴 때마다 보관소를 읽으므로 키 **값**을 꺼내지 않음을 한 번 더 못박는다 — 보관소의 `get` 이 불리면 곧바로 실패한다."""
        cn.add_entry(self.ctx, "naver_apihub", name="내 키", fields=self.HUB, keystore=self.ctx.keystore)
        store = self.ctx.keystore
        asked = []
        original_get, original_exists = store.get, store.exists
        store.get = lambda ref: (_ for _ in ()).throw(AssertionError("홈이 키 값을 꺼냈다"))
        store.exists = lambda ref: (asked.append(ref), original_exists(ref))[1]
        try:
            self.read()
        finally:
            store.get, store.exists = original_get, original_exists
        self.assertTrue(asked)
        self.assertEqual(self.state.conn_state, "normal")


class RemovedThingsStayRemovedTest(unittest.TestCase):
    def test_no_home_text_names_a_removed_feature_or_the_banned_numbers(self):
        """모든 시나리오의 홈 뷰모델 글에 월 검색량·문서 수·전체 보기·빠른 작업·활용 팁·초안 만들기·주제 분석 시작이 없다 — 값도 글도."""
        views = [loaded(services.FakeHomeProvider(scenario)).home_view() for scenario in ("normal", "empty", "partial", "offline")]
        views.append(loaded(services.FakeHomeProvider(board=None)).home_view())
        views.append(app_state.AppState(services.FakeHomeProvider(delay=5)).home_view())
        failed = loaded()
        failed.apply_failure(JobFailure("끊겼어요.", code="X"))
        views.append(failed.home_view())
        for view in views:
            flat = texts_of(view)
            for word in BANNED_WORDS:
                self.assertNotIn(word, flat, word)

    def test_the_removed_texts_are_gone_from_the_text_table_and_only_the_drawer_keeps_its_two_legacy_names(self):
        gone = ("sum_topics_sub", "sum_week_sub", "sum_ideas_sub", "sum_none", "rec_title", "rec_desc", "chip_all", "chip_a", "chip_b", "chip_hot", "chip_new", "make_primary", "make_a11y", "detail_a11y",
                "demand", "docs", "tip_demand", "tip_docs", "row_a11y", "rail_blogs", "rail_blogs_sub", "rail_total", "rail_month", "rail_candidates", "rail_unit", "rail_quick", "q_new", "q_new_d",
                "tip_title", "tip_text", "tip_close", "list_count", "empty_title", "empty_desc", "empty_btn", "thumb_label", "thumb_label_plain", "img_state_none")
        self.assertEqual([key for key in gone if key in text.T], [])
        self.assertEqual({key: value for key, value in text.T.items() if "검색량" in value or "문서 수" in value}, {"d_demand": "월간 검색량"})      # 서랍의 항목 이름 하나뿐(서랍은 그대로)
        self.assertEqual(text.T["d_docs"], "관련 블로그 검색 결과 수")

    def test_the_state_and_screen_code_of_the_removed_features_is_gone(self):
        source = (UI_DIR / "core" / "app_state.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))} | {target.id for node in ast.walk(tree) if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
        for gone in ("topic_vm", "HOME_CHIPS", "HOME_ROWS", "STATUS_LABEL", "set_home_filter", "home_rows", "select_topic", "dismiss_tip", "quick", "_live", "_match", "_card"):
            self.assertNotIn(gone, names, gone)
        for word in ("tip_visible", "home_filter", "PRIORITY_RANK", "chip_"):
            self.assertNotIn(word, source, word)
        self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", source), [])

    def test_the_widgets_and_shell_actions_of_the_removed_features_are_gone_from_every_screen_file(self):
        """화면 파일(`ui/qt/*.py`)과 상태 파일에 옛 요약 카드·추천 행·빠른 작업·본문+오른쪽 패널 부품과 칩 거르기·행 선택·팁 닫기·빠른 작업 동작의 이름이 없다(함수·클래스·대입 어디에도).
        변이 점검이 찾은 틈: 셸에 `chip_home` 을 되살려도 시험이 못 잡았다(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5)."""
        banned = {"SummaryCard", "TopicRow", "QuickAction", "ResponsiveBody", "chip_flow", "_rail", "chip_home", "select_topic", "tip_close", "quick", "set_home_filter", "dismiss_tip", "home_rows", "topic_vm"}
        files = sorted((UI_DIR / "qt").glob("*.py")) + [UI_DIR / "core" / "app_state.py", UI_DIR / "core" / "board_view.py"]
        self.assertGreaterEqual(len(files), 10)
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            names |= {target.id for node in ast.walk(tree) if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
            names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)}
            self.assertEqual(sorted(banned & names), [], path.name)

    def test_the_new_text_keys_never_promise_and_name_no_search_volume(self):
        keys = ("board_unavailable_title", "board_unavailable_desc", "board_connect_title", "board_connect_desc", "board_row_hint", "board_section_a11y", "blog_a", "blog_b")
        for key in keys:
            value = text.T[key]
            for word in text.FORBIDDEN + ("검색량", "문서 수", "상대값"):
                self.assertNotIn(word, value, key)
            self.assertNotRegex(value, r"[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+", key)



class DocsTest(unittest.TestCase):
    """결정 기록·UI 문서가 이 묶음의 약속을 말한다 — 위임 규칙 근거·한 가지 상태 낱말·검증 끝/닫음 낱말 없음(독립 검증 전)·번호가 이 묶음 몫(D-200~D-204)이고 앞 묶음 번호 뒤에 온다."""
    ROWS = (("D-200", "FIXING"), ("D-201", "FIXING"), ("D-202", "FIXING"), ("D-203", "FIXING"), ("D-204", "DEFERRED"))
    PHOTOS = ("1366x768_100_home_before_connect.png", "1366x768_100_home_sections.png", "1180x720_100_home.png")

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

    def test_the_numbers_are_this_bundles_own_and_come_after_the_c1c_ones(self):
        numbers = re.findall(r"(?m)^\| (D-\d{3}) \|", self.doc("DECISIONS.md"))
        self.assertEqual([number for number in numbers if number in dict(self.ROWS)], [number for number, _status in self.ROWS])
        self.assertEqual(len(numbers), len(set(numbers)), "같은 번호가 두 번 나온다")
        self.assertGreater(numbers.index("D-200"), numbers.index("D-194"))

    def test_the_decisions_say_what_they_decided(self):
        expected = {"D-200": ("포커스가 이긴다", "`:focus`", "`set_card_state`", "정적인 카드", "운영자 PC 확인"),
                    "D-201": ("`board`", "열한 개 키", "`drawer_topic`", "`topics`", "데이터 없음", "되살아나지 않음"),
                    "D-202": ("`점수 계산 전`", "`연결 전`", "`집계 전`", "480", "400", "190", "1250", "1090", "1078"),
                    "D-203": ("바이트", "`autoload`", "`다시 불러오기`", "HomeConnectionsReadTest", "한 번"),
                    "D-204": ("92개", "T2", "7.6초", "운영자 PC", "`UI_VISUAL_QA.md`")}
        for number, words in expected.items():
            row = self.row(number)
            for word in words:
                self.assertIn(word, row, f"{number}: {word}")
        for number, _status in self.ROWS:
            row = self.row(number)
            self.assertIsNone(re.search("[A-Za-z]:" + re.escape(chr(92)) + "|/Users/|/home/", row), f"{number}: 개인 경로가 없다")

    def test_the_ui_docs_describe_the_drawn_home_and_not_the_old_one(self):
        states, spec, components = self.doc("UI_STATES.md"), self.doc("UI_DESIGN_SPEC.md"), self.doc("UI_COMPONENTS.md")
        self.assertIn("## 7. 홈의 새 구역의 상태 — 읽어서 그린다(데이터 UI-C1c · 모양 UI-C1d)", states)
        for word in ("정상 빈 상태", "쓰기 단추 없음", "발행일 확인 불가", "연결 전", "집계 전", "KPI 넷 + Naver A·B 추천"):
            self.assertIn(word, states, word)
        self.assertNotIn("안내만 — 아직 없는 기능", states)                                               # 옛 빈 상태의 `주제 분석 시작`(안내만)이 문서에 남지 않았다
        self.assertNotIn("필터 칩 5개 + 추천 행 5개", states)
        for word in ("KPI 카드 4개", "오른쪽 패널은 없다", "홈 데이터(UI-C1c — 읽기만)와 모양(UI-C1d)", "창 폭 1250"):
            self.assertIn(word, spec, word)
        self.assertNotIn("**맞춤 주제 추천**(필터 칩", spec)
        for word in ("`ui/qt/board.py`", "`KpiCard`", "`Pressable`", "`BoardRow`"):
            self.assertIn(word, components, word)
        for gone in ("`SummaryCard`·", "`TopicRow`(목록 행)", "`QuickAction` |", "`ResponsiveBody`)"):
            self.assertNotIn(gone, components, gone)
        self.assertNotIn("요약 카드·맞춤 주제 추천", (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_the_visual_qa_names_the_new_photos_and_they_exist(self):
        qa = self.doc("UI_VISUAL_QA.md")
        self.assertIn("## 11. UI-C1d", qa)
        for name in self.PHOTOS:
            self.assertTrue((ROOT / "docs" / "images" / "ui" / name).is_file(), name)
            self.assertIn(f"images/ui/{name}", qa, name)
        for word in ("같은 것 17·달라진 것 0", "1366×768/100% 에서 핵심 행동이 첫 화면에 보이는가 — 예."):
            self.assertIn(word, qa, word)

    def test_the_changelog_has_the_one_entry_and_names_the_decisions(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(changelog.count("화면 'UI-C1d'"), 1)
        self.assertIn("D-200~D-204", changelog)


if __name__ == "__main__":
    unittest.main()
