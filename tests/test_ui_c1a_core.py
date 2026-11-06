"""UI-C1a(틀 Shell)의 **순수 시험**(PySide6 없이 3.10·3.12 모두 돈다) — 접근성 색 값·대비, 상세 창 규칙(`detail_layout`), 상단 앱 바의 시계·좁은 폭 규칙, 버전 읽기 규칙, 시계 주입.

지키는 것:
  1) 접근성 색(운영자 2026-11-06 확인 요청 004 의 답): 의미 배지 글자 추천 #9D5F07·가격변화 #437B28·주의 #9F6003, 위험 단추 배경 #CE4646·글자 #FFFFFF — 값과 대비 4.5 이상, 위험 단추의 기본·가리킴·눌림·꺼짐 색표.
  2) 상세 창 규칙: 논리 폭 ≥1600 고정 420~500·3열 / 1366~1599 고정 400·2열 / <1366 서랍·2열 — 경계·범위·단조성·배율 예(물리 해상도가 아니라 Qt 논리 폭).
  3) 시계: 날짜·시간 글 세 단계·분 경계까지 남은 시간·좁은 폭에서 소개 문구를 먼저 숨기고 날짜를 줄이는 순서·시계 주입(가짜 시계).
  4) 버전: `v0.0.0` 꼴·못 읽으면 `개발 버전`·Release 판정(묶음 실행 파일 또는 환경 변수 1)·Release 에서 못 읽으면 쉬운 한국어 오류.
"""
import ast
import contextlib
import datetime
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.ui import launcher  # noqa: E402
from chanceblog_desktop.ui.core import app_state, clock, part_rules, services, text, tokens, version  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"


class AccessibilityColorsTest(unittest.TestCase):
    """운영자 결정 값 — 손으로 적은 표(토큰 파일을 고쳐도 표는 따라 바뀌지 않는다)."""

    def test_the_operator_colors_are_exactly_these(self):
        colors = tokens.palette()
        self.assertEqual({kind: tokens.badge_colors(colors, kind)[1] for kind in ("recommend", "price_change", "caution")}, {"recommend": "#9D5F07", "price_change": "#437B28", "caution": "#9F6003"})
        self.assertEqual((colors["danger_fill"], colors["on_primary"]), ("#CE4646", "#FFFFFF"))
        self.assertEqual(tokens.badge_label("recommend"), "추천")                         # 글자(이름)는 그대로 — 색만 바뀌었다
        self.assertEqual((tokens.badge_label("price_change"), tokens.badge_label("caution")), ("가격변화", "주의"))

    def test_the_backgrounds_of_those_badges_and_the_status_colors_stay_as_the_document_says(self):
        colors = tokens.palette()
        self.assertEqual({kind: tokens.badge_colors(colors, kind)[0] for kind in ("recommend", "price_change", "caution")}, {"recommend": "#FFF0CA", "price_change": "#E8F7DF", "caution": "#FFF2D6"})
        self.assertEqual(colors["danger"], "#D94A4A")                                    # 상태색(아이콘·사용량 막대·점수 구간)은 문서 값 그대로 — 위험 '단추' 배경만 새 토큰
        self.assertEqual(colors["score_low"], "#D94A4A")
        self.assertNotEqual(colors["danger_fill"], colors["danger"])

    def test_every_changed_pair_reaches_4_5_on_its_own_background_and_on_white(self):
        colors = tokens.palette()
        for kind in ("recommend", "price_change", "caution"):
            bg, fg = tokens.badge_colors(colors, kind)
            self.assertGreaterEqual(tokens.contrast(fg, bg), 4.5, kind)
            self.assertGreaterEqual(tokens.contrast(fg, colors["surface"]), 4.5, kind)
        self.assertGreaterEqual(tokens.contrast(colors["on_primary"], colors["danger_fill"]), 4.5)

    def test_the_danger_button_state_table_by_hand(self):
        """위험 단추의 상태별 (배경, 글자) — 기본·가리킴·눌림·꺼짐. 꺼짐은 대비 제외 항목이지만 값은 못박고 '글자가 바탕과 구별됨'(1.5 이상)만 확인한다 — 글자는 흰색, 꺼진 채움은 연한 파랑 회색."""
        colors = tokens.palette()
        table = {"default": (colors["danger_fill"], colors["on_primary"]), "hover": (colors["danger_text"], colors["on_primary"]), "pressed": (colors["danger_text"], colors["on_primary"]),
                 "disabled": (colors["disabled_fill"], colors["on_primary"])}
        self.assertEqual(table, {"default": ("#CE4646", "#FFFFFF"), "hover": ("#BA4247", "#FFFFFF"), "pressed": ("#BA4247", "#FFFFFF"), "disabled": ("#C5D0E0", "#FFFFFF")})
        for state in ("default", "hover", "pressed"):
            self.assertGreaterEqual(tokens.contrast(table[state][1], table[state][0]), 4.5, state)
        self.assertGreaterEqual(tokens.contrast(table["disabled"][1], table["disabled"][0]), 1.5)     # 꺼짐: 4.5 제외 항목 — 구별은 됨(실제 1.56)
        self.assertNotEqual(table["disabled"][0].upper(), table["default"][0].upper())

    def test_the_danger_ghost_text_stays_readable_in_every_state(self):
        """위험 '고스트' 단추(배경 없는 빨간 글자): 기본은 흰 바탕, 가리키면 옅은 위험 면(`danger_100`) 위의 `danger_text` — 둘 다 4.5 이상."""
        colors = tokens.palette()
        for ground in ("surface", "danger_100"):
            self.assertGreaterEqual(tokens.contrast(colors["danger_text"], colors[ground]), 4.5, ground)

    def test_the_next_steps_color_is_the_55_percent_mix_token_and_its_opacity_is_inside_50_to_60(self):
        colors = tokens.palette()
        self.assertEqual(colors["soon_text"], "#A3ABB4")
        self.assertEqual(tokens.mix(colors["bg_sidebar"], colors["text_secondary"], tokens.SOON_OPACITY), colors["soon_text"])      # 글자 색 55% + 바탕 45%
        self.assertEqual(tokens.SOON_OPACITY, 0.55)
        self.assertTrue(0.50 <= tokens.SOON_OPACITY <= 0.60)                                           # 운영자의 50~60%
        self.assertNotEqual(colors["soon_text"], colors["text_secondary"])
        self.assertNotEqual(colors["soon_text"], colors["bg_sidebar"])

    def test_new_sidebar_colors_are_the_document_values_and_the_current_menu_is_readable(self):
        colors = tokens.palette()
        self.assertEqual((colors["nav_current_bg"], colors["nav_current_text"], colors["sidebar_border"]), ("#DCEAFF", "#1F61BC", "#E3E9F2"))
        self.assertGreaterEqual(tokens.contrast(colors["nav_current_text"], colors["nav_current_bg"]), 4.5)
        self.assertGreaterEqual(tokens.contrast(colors["nav_current_text"], colors["bg_sidebar"]), 4.5)


class DetailLayoutTest(unittest.TestCase):
    """상세 창 규칙 — 운영자 결정 값을 손으로 적은 표로: 논리 폭 ≥1600 고정 420~500·3열 / 1366~1599 고정 400·2열 / 1366 미만 서랍·2열."""

    def layout(self, width):
        found = part_rules.detail_layout(width)
        return found.mode, found.detail_width, found.columns

    def test_the_four_boundaries(self):
        self.assertEqual(self.layout(1365), ("drawer", 0, 2))
        self.assertEqual(self.layout(1366), ("fixed", 400, 2))
        self.assertEqual(self.layout(1599), ("fixed", 400, 2))
        self.assertEqual(self.layout(1600), ("fixed", 420, 3))

    def test_the_fixed_width_grows_from_420_to_500_and_stops(self):
        self.assertEqual([self.layout(width)[1] for width in (1600, 1680, 1760, 1840, 1920)], [420, 440, 460, 480, 500])
        self.assertEqual([self.layout(width)[1] for width in (2000, 2560, 3840, 10000)], [500, 500, 500, 500])
        self.assertEqual(self.layout(1920), ("fixed", 500, 3))
        self.assertEqual(self.layout(1600.0), ("fixed", 420, 3))                       # 실수 폭도 받는다

    def test_the_width_never_leaves_420_to_500_and_never_shrinks_as_the_window_grows(self):
        previous = 0
        for width in range(1600, 4001):
            fixed = part_rules.detail_layout(width)
            self.assertTrue(420 <= fixed.detail_width <= 500, width)
            self.assertGreaterEqual(fixed.detail_width, previous, width)
            self.assertEqual((fixed.mode, fixed.columns), ("fixed", 3), width)
            previous = fixed.detail_width

    def test_below_1366_it_is_a_drawer_with_two_columns_down_to_the_smallest_window(self):
        for width in (1, 600, 900, 1093, 1180, 1280, 1365):
            self.assertEqual(self.layout(width), ("drawer", 0, 2), width)

    def test_the_logical_width_decides_not_the_physical_resolution(self):
        """윈도 배율이 클수록 같은 물리 해상도라도 논리 폭이 작다 — 규칙에는 논리 폭(`QWidget.width()`)을 넣는다. 아래 논리 폭은 `물리 ÷ 배율` 을 반올림한 값이다."""
        cases = ((1920, 1.00, 1920, ("fixed", 500, 3)), (1920, 1.25, 1536, ("fixed", 400, 2)), (1920, 1.50, 1280, ("drawer", 0, 2)),
                 (1366, 1.00, 1366, ("fixed", 400, 2)), (1366, 1.25, 1093, ("drawer", 0, 2)), (1366, 1.50, 911, ("drawer", 0, 2)), (2560, 1.25, 2048, ("fixed", 500, 3)))
        for physical, scale, logical, expected in cases:
            with self.subTest(physical=physical, scale=scale):
                self.assertEqual(round(physical / scale), logical)
                self.assertEqual(self.layout(logical), expected)
        self.assertNotEqual(self.layout(1920), self.layout(round(1920 / 1.25)))        # 1920 물리 125% 를 1920 으로 읽으면 틀린다(고정 500·3열이 아니라 고정 400·2열)

    def test_a_wrong_width_is_a_code_mistake_and_raises(self):
        for bad in (True, False, None, "1600", [], 0, -1, -1600.5, float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                part_rules.detail_layout(bad)

    def test_the_drawer_width_is_420_but_at_most_92_percent_of_the_window(self):
        for window, expected in ((2000, 420), (1366, 420), (900, 420), (456, 419), (450, 414), (400, 368), (100, 92)):
            self.assertEqual(part_rules.drawer_width(window), expected, window)

    def test_the_rule_reads_the_tokens_and_the_tokens_hold_the_decision(self):
        frame = tokens.FRAME
        self.assertEqual((frame["fixed_detail_min"], frame["narrow_detail_min"], frame["detail_range"], frame["detail_narrow"], frame["detail_max_at"]), (1600, 1366, (420, 500), 400, 1920))
        self.assertEqual((frame["detail_columns_wide"], frame["detail_columns_narrow"]), (3, 2))
        source = (UI_DIR / "core" / "part_rules.py").read_text(encoding="utf-8")
        for name in ("fixed_detail_min", "narrow_detail_min", "detail_range", "detail_narrow", "detail_max_at", "detail_columns_wide", "detail_columns_narrow"):
            self.assertIn(f'"{name}"', source, name)                                    # 숫자를 규칙 코드에 따로 적지 않고 토큰에서 읽는다


class ClockTextTest(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 6, 20, 10, 5, 250000)                           # 2026-11-06 은 금요일

    def test_the_three_levels_for_a_friday_evening(self):
        self.assertEqual(clock.date_levels(self.NOW), ("2026년 11월 6일 (금) 20:10", "11월 6일 (금) 20:10", "11/6 20:10"))

    def test_every_weekday_is_a_korean_letter_and_numbers_are_not_padded_except_the_time(self):
        week = {0: "월", 1: "화", 2: "수", 3: "목", 4: "금", 5: "토", 6: "일"}
        for offset in range(7):
            day = datetime.datetime(2026, 11, 2 + offset, 9, 3)                        # 2026-11-02 는 월요일
            self.assertEqual(clock.date_levels(day)[0], f"2026년 11월 {2 + offset}일 ({week[offset]}) 09:03")
        self.assertEqual(clock.date_levels(datetime.datetime(2027, 1, 5, 0, 5)), ("2027년 1월 5일 (화) 00:05", "1월 5일 (화) 00:05", "1/5 00:05"))
        self.assertEqual(clock.date_levels(datetime.datetime(2026, 12, 31, 23, 59))[2], "12/31 23:59")

    def test_the_text_is_built_by_hand_not_with_strftime(self):
        """한글 서식을 `strftime` 에 넘기면 영문 윈도 파이썬 3.10 에서 UnicodeEncodeError 가 난 적이 있다 — 소스에 `strftime` 이 없어야 한다."""
        source = (UI_DIR / "core" / "clock.py").read_text(encoding="utf-8")
        self.assertNotRegex(re.sub(r'""".*?"""', "", source, flags=re.S), r"strftime")

    def test_the_levels_get_shorter(self):
        for now in (self.NOW, datetime.datetime(2026, 12, 31, 23, 59), datetime.datetime(2027, 1, 1, 0, 0)):
            first, second, third = clock.date_levels(now)
            self.assertEqual(len(clock.date_levels(now)), clock.DATE_LEVELS)            # 단계 수 상수와 실제 단계가 같다
            self.assertGreater(len(first), len(second))
            self.assertGreater(len(second), len(third))
            self.assertTrue(first.endswith(third[-5:]), "마지막 시간 부분은 세 단계가 같다")

    def test_the_minute_boundary_countdown(self):
        zero = datetime.datetime(2026, 11, 6, 20, 10, 0, 0)
        self.assertEqual(clock.ms_until_next_minute(zero), 60000)                       # 정각이면 한 분 뒤
        self.assertEqual(clock.ms_until_next_minute(zero.replace(second=30, microsecond=500000)), 29500)
        self.assertEqual(clock.ms_until_next_minute(zero.replace(second=59, microsecond=999999)), 1)
        self.assertEqual(clock.ms_until_next_minute(zero.replace(second=59, microsecond=0)), 1000)
        for second in range(60):
            for micro in (0, 1, 999, 1000, 500000, 999999):
                found = clock.ms_until_next_minute(zero.replace(second=second, microsecond=micro))
                self.assertTrue(1 <= found <= 60000, (second, micro, found))
                after = zero.replace(second=second, microsecond=micro) + datetime.timedelta(milliseconds=found)
                self.assertEqual((after.second, after.microsecond // 1000), (0, 0), "남은 시간만큼 지나면 정확히 다음 분이다")

    def test_the_tick_margin_is_small_and_positive(self):
        self.assertTrue(0 < clock.TICK_MARGIN_MS <= 100)


class FixedClockTest(unittest.TestCase):
    def test_a_fixed_clock_only_moves_when_told(self):
        fake = clock.FixedClock(datetime.datetime(2026, 11, 6, 20, 10, 0))
        self.assertEqual(fake.now(), datetime.datetime(2026, 11, 6, 20, 10, 0))
        self.assertEqual(fake.now(), fake.now())
        fake.advance(60)
        self.assertEqual(fake.now(), datetime.datetime(2026, 11, 6, 20, 11, 0))
        fake.advance(-120)
        self.assertEqual(fake.now(), datetime.datetime(2026, 11, 6, 20, 9, 0))
        fake.set(datetime.datetime(2027, 1, 1))
        self.assertEqual(fake.now().year, 2027)

    def test_a_non_datetime_is_refused(self):
        for bad in (None, "2026-11-06", datetime.date(2026, 11, 6), 5):
            with self.assertRaises(ValueError):
                clock.FixedClock(bad)
        with self.assertRaises(ValueError):
            clock.FixedClock(datetime.datetime(2026, 1, 1)).set("x")

    def test_the_system_clock_gives_a_naive_datetime_close_to_now(self):
        found = clock.SystemClock().now()
        self.assertIsInstance(found, datetime.datetime)
        self.assertLess(abs((datetime.datetime.now() - found).total_seconds()), 5)


class TopbarPlanTest(unittest.TestCase):
    TAGLINE, GAP, DATES = 200, 24, (180, 120, 70)

    def plan(self, available):
        found = clock.plan_topbar(available, self.TAGLINE, self.DATES, self.GAP)
        return found.show_tagline, found.level

    def test_enough_room_shows_everything(self):
        self.assertEqual(self.plan(404), (True, 0))                                    # 200 + 24 + 180 — 딱 맞음
        self.assertEqual(self.plan(10000), (True, 0))

    def test_the_tagline_goes_first_and_only_then_the_date_shrinks(self):
        self.assertEqual(self.plan(403), (False, 0))                                   # 한 칸 모자라면 소개 문구만 숨는다
        self.assertEqual(self.plan(180), (False, 0))
        self.assertEqual(self.plan(179), (False, 1))                                   # 그다음에야 날짜가 줄어든다
        self.assertEqual(self.plan(120), (False, 1))
        self.assertEqual(self.plan(119), (False, 2))
        self.assertEqual(self.plan(70), (False, 2))
        self.assertEqual(self.plan(0), (False, 2))                                     # 어느 것도 안 들어가도 날짜를 없애지 않는다(가장 짧은 것)

    def test_the_order_never_skips_a_step_and_never_gets_longer_when_the_room_shrinks(self):
        order = []
        for available in range(700, -1, -1):
            shown, level = self.plan(available)
            self.assertTrue(not (shown and level > 0), "소개 문구가 보이는 채로 날짜가 줄지 않는다")
            step = 0 if shown else 1 + level
            order.append(step)
        self.assertEqual(order, sorted(order), "공간이 줄면 단계는 늘기만 한다")
        self.assertEqual(sorted(set(order)), [0, 1, 2, 3], "소개 숨김 → 날짜 단계 1 → 2 를 하나씩 거친다")

    def test_a_plan_needs_at_least_one_date_width(self):
        with self.assertRaises(ValueError):
            clock.plan_topbar(100, 50, (), 8)

    def test_a_single_level_never_hides_the_date(self):
        self.assertEqual(clock.plan_topbar(10, 50, (80,), 8), clock.TopbarPlan(False, 0))


class VersionTest(unittest.TestCase):
    def test_a_real_number_becomes_v_form(self):
        for raw, shown in (("0.0.0", "v0.0.0"), (" 0.1.0\n", "v0.1.0"), ("1.2.3\r\n", "v1.2.3"), ("10.20.30", "v10.20.30"), ("0.9.0-beta", "v0.9.0-beta"), ("1.0.0+3", "v1.0.0+3"),
                           ("\ufeff0.0.0\r\n", "v0.0.0"), ("\ufeff 1.2.3 ", "v1.2.3")):          # 메모장이 맨 앞에 붙이는 UTF-8 BOM 은 있어도 없어도 같다
            info = version.read_version("VERSION", reader=lambda _p, raw=raw: raw)
            self.assertEqual((info.text, info.source, info.known), (shown, "file", True), raw)

    def test_anything_else_is_the_dev_label_and_never_an_exception(self):
        def failing(error):
            def reader(_path):
                raise error
            return reader
        for raw in ("", "   ", "abc", "0.0", "v0.0.0", "0.0.0\n1.2.3", "0.0.0 beta", "0.0.0\x00", "1.0.0\ufeff", "1.\ufeff0.0", "\ufeff", "-1.0.0", "1.0.0-", "1.0.0-" + "x" * 80, "<b>1.0.0</b>", None, b"0.0.0", 5):
            info = version.read_version("VERSION", reader=lambda _p, raw=raw: raw)
            self.assertEqual((info.text, info.source, info.known), ("개발 버전", "dev", False), repr(raw))
        for error in (FileNotFoundError("x"), PermissionError("x"), OSError("x"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"), ValueError("x")):
            info = version.read_version("VERSION", reader=failing(error))
            self.assertEqual((info.text, info.source), ("개발 버전", "dev"), repr(error))

    def test_real_files(self):
        with tempfile.TemporaryDirectory() as folder:
            good, missing, binary = Path(folder, "VERSION"), Path(folder, "NOPE"), Path(folder, "BIN")
            good.write_text("2.3.4\n", encoding="utf-8")
            binary.write_bytes(b"\xff\xfe\x00")
            with_bom = Path(folder, "VERSION_BOM")
            with_bom.write_bytes(b"\xef\xbb\xbf2.3.4\r\n")                                # 메모장 '저장' 이 붙이는 UTF-8 BOM + CRLF
            self.assertEqual(version.read_version(with_bom), version.read_version(good))      # 같은 번호·같은 출처
            self.assertEqual(version.read_version(with_bom).text, "v2.3.4")
            self.assertEqual(version.read_version(good).text, "v2.3.4")
            self.assertEqual(version.read_version(str(good)).text, "v2.3.4")             # 글자 경로도 받는다
            self.assertEqual(version.read_version(missing).source, "dev")
            self.assertEqual(version.read_version(binary).source, "dev")
            self.assertEqual(version.read_version(Path(folder)).source, "dev")             # 폴더를 가리켜도 예외 없이

    def test_the_repository_version_file_is_readable(self):
        info = version.read_version()
        raw = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertTrue(info.known)
        self.assertEqual(info.text, "v" + raw)
        self.assertEqual(version.default_path(), ROOT / "VERSION")

    def test_the_dev_label_text(self):
        self.assertEqual(text.T["dev_version"], "개발 버전")

    def test_release_is_a_frozen_bundle_or_the_environment_variable_exactly_1(self):
        self.assertFalse(version.is_release({}, False))
        self.assertTrue(version.is_release({}, True))
        self.assertTrue(version.is_release({"CHANCEBLOG_RELEASE": "1"}, False))
        for other in ("0", "true", "yes", "", " 1", "1 ", "2"):
            self.assertFalse(version.is_release({"CHANCEBLOG_RELEASE": other}, False), repr(other))
        self.assertTrue(version.is_release({"CHANCEBLOG_RELEASE": "0"}, True))          # 묶음 실행 파일이면 환경 변수와 관계없이 Release
        self.assertEqual(version.RELEASE_ENV, "CHANCEBLOG_RELEASE")

    def test_release_reads_sys_frozen_and_the_real_environment_by_default(self):
        with mock.patch.dict(os.environ, {"CHANCEBLOG_RELEASE": "1"}):
            self.assertTrue(version.is_release())
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHANCEBLOG_RELEASE", None)
            with mock.patch.object(sys, "frozen", True, create=True):
                self.assertTrue(version.is_release())
            if not getattr(sys, "frozen", False):
                self.assertFalse(version.is_release())

    def test_an_unreadable_version_is_an_easy_korean_error_only_in_release(self):
        dev = version.VersionInfo("개발 버전", "dev")
        known = version.VersionInfo("v0.0.0", "file")
        problem = version.release_problem(dev, True)
        self.assertEqual(problem, text.T["version_release_error"])
        self.assertIn("버전", problem)
        self.assertNotRegex(problem, r"Traceback|Exception|Error\b|[A-Z]{3,}_[A-Z]{3,}")        # 영문 코드·추적 없음 — 새 오류 코드를 만들지 않았다
        self.assertIsNone(version.release_problem(dev, False))                         # 개발 화면은 `개발 버전` 으로 계속
        self.assertIsNone(version.release_problem(known, True))
        self.assertIsNone(version.release_problem(known, False))


class LauncherReleaseTest(unittest.TestCase):
    """앱 시작(`gui` 명령)의 Release 검사 — Release 인데 버전을 못 읽으면 쉬운 한국어 안내로 끝내고(종료 코드 1, 새 오류 코드 없음), 개발 화면은 `개발 버전` 으로 계속 간다."""

    def run_main(self, version_file, release, pyside6=False):
        out = io.StringIO()
        env = {"CHANCEBLOG_RELEASE": "1"} if release else {}
        seen = []
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, env))
            if not release:
                os.environ.pop("CHANCEBLOG_RELEASE", None)
            stack.enter_context(mock.patch.object(sys, "frozen", False, create=True))
            stack.enter_context(mock.patch.object(version, "default_path", lambda: version_file))
            stack.enter_context(mock.patch.object(launcher, "has_pyside6", lambda: (seen.append("pyside6-checked"), pyside6)[1]))
            code = launcher.main([], out=out)
        return code, out.getvalue(), seen

    def test_release_with_an_unreadable_version_stops_with_the_easy_message_before_anything_else(self):
        with tempfile.TemporaryDirectory() as folder:
            code, shown, seen = self.run_main(Path(folder, "NOPE"), release=True)
        self.assertEqual(code, 1)
        self.assertIn(text.T["version_release_error"], shown)
        self.assertEqual(seen, [], "버전을 못 읽으면 PySide6 확인보다 먼저 끝낸다")
        self.assertNotRegex(shown, r"Traceback|Exception|[A-Z]{3,}_[A-Z]{3,}")

    def test_release_with_a_readable_version_goes_on(self):
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder, "VERSION")
            good.write_text("1.2.3\n", encoding="utf-8")
            code, shown, seen = self.run_main(good, release=True)
        self.assertEqual((code, seen), (1, ["pyside6-checked"]))                         # PySide6 가 없다고 흉내 냈으므로 그 안내로 끝난다 — 버전 오류가 아니다
        self.assertEqual(shown.strip(), launcher.NEEDS_PYSIDE6.strip())

    def test_a_dev_run_with_an_unreadable_version_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            code, shown, seen = self.run_main(Path(folder, "NOPE"), release=False)
        self.assertEqual(seen, ["pyside6-checked"])
        self.assertNotIn(text.T["version_release_error"], shown)

    def test_a_frozen_bundle_is_release_even_without_the_environment_variable(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {}))
            os.environ.pop("CHANCEBLOG_RELEASE", None)
            stack.enter_context(mock.patch.object(sys, "frozen", True, create=True))
            stack.enter_context(mock.patch.object(version, "default_path", lambda: Path(folder, "NOPE")))
            code = launcher.main([], out=out)
        self.assertEqual(code, 1)
        self.assertIn(text.T["version_release_error"], out.getvalue())


class NoNavigationTest(unittest.TestCase):
    """홈의 동작은 어느 것도 `AppState.nav` 를 부르지 않는다 — 화면으로 가는 길이 사이드바 하나라는 것을 뷰모델 쪽에서도 못박는다(빠른 작업이 이미 없는 화면 이름으로 `nav` 를 불러도 아무 일이 없어서 결과만 보면 못 잡는 변이를 잡는다)."""

    def spy(self):
        state = app_state.AppState(services.FakeHomeProvider())
        state.apply_home(services.FakeHomeProvider().load_home(lambda *a: None, lambda: False))
        calls = []
        real = state.nav
        state.nav = lambda key: (calls.append(key), real(key))[1]
        return state, calls

    def test_quick_actions_and_draft_requests_never_ask_for_a_screen(self):
        state, calls = self.spy()
        for key in ("new", "saved", "history", "blogs", "nope"):
            state.quick(key)
        state.draft_requested("s1", "A")
        self.assertEqual(calls, [])
        self.assertEqual(state.page, "home")

    def test_the_drawer_and_the_filters_never_ask_for_a_screen_either(self):
        state, calls = self.spy()
        state.open_drawer("s1")
        state.set_home_filter("b")
        state.select_topic("s1")
        state.close_drawer()
        self.assertEqual(calls, [])
        self.assertEqual({card["go"] for card in state.home_view()["cards"]}, {None})              # 요약 카드는 가는 곳이 없다
        self.assertEqual(state.home_view()["rail"]["quick"][0]["key"], "new")


class SourceRulesTest(unittest.TestCase):
    NEW = ("clock.py", "version.py")

    def test_the_new_pure_modules_never_import_the_screen_toolkit_and_never_read_the_system_time_directly_in_the_clock_rules(self):
        for name in self.NEW:
            source = (UI_DIR / "core" / name).read_text(encoding="utf-8")
            self.assertNotRegex(source, r"(?m)^\s*(?:import|from)\s+PySide6", name)
        clock_source = (UI_DIR / "core" / "clock.py").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"datetime\.datetime\.now\(", clock_source)), 1, "시스템 시계를 부르는 곳은 `SystemClock.now` 하나뿐이다")

    def test_the_widgets_never_call_the_system_time_themselves(self):
        """위젯(`ui/qt/`)이 `datetime.now()` 를 직접 부르지 않는다 — 시계는 주입받는다(`clock.now()`)."""
        for path in sorted((UI_DIR / "qt").glob("*.py")):
            calls = [node.func.attr for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                     and node.func.attr in ("now", "today", "utcnow") and isinstance(node.func.value, (ast.Name, ast.Attribute)) and "date" in ast.unparse(node.func.value)]
            self.assertEqual(calls, [], path.name)                                      # 글(문서·주석)이 아니라 실제 호출만 본다


if __name__ == "__main__":
    unittest.main()
