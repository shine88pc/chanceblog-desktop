"""C-Type 디자인 기초(UI-C0)의 **순수 시험**(PySide6 없이 3.10·3.12 모두 돈다) — 토큰 값 표(손으로 적은 문서 값)·점수 구간과 변화량·구성 막대·사용량 막대·행동 줄·탭 규칙·부품 소스 규칙.

지키는 것:
  1) 토큰: 새 기준 문서의 값을 손으로 적은 표와 한 글자씩 비교(색·의미별 배지 11쌍·점수 구간색·구성 막대 색·글자 단계·모서리·그림자 3종·크기·틀 크기). 새 상태색에 맞춰 다시 만든 `*_text` 가 흰 바탕과 자기 옅은 면에서 대비 4.5 이상.
  2) 점수: 구간 경계 80/65/50 이 **엔진(`topics`)의 점수 구간과 모든 정수 0~100 에서 같다**, 구간 이름 4개, **데이터 부족은 0점이 아니다**(링을 안 그린다), 변화량 글(▲ +12·▼ -5·― 변화 없음), 접근 이름.
  3) 구성 막대·사용량 막대: 길이 비율·고정색·부호 글, 80%/90% 경계(표시한 퍼센트 기준), 숫자와 단위 함께, 모를 때는 `확인할 수 없어요`.
  4) 행동 줄·탭: 주요 1·보조 ≤3·위험 ≤1 규칙, 좁아질 때 접히는 순서(위험·3차 → 보조, 주요는 늘 보임), 탭 키 이동, 배지 글자 줄임.
  5) 소스: 새 파일이 PySide6 를 모르는 곳(`core/`)에서 PySide6 를 불러오지 않고, 색·글꼴 이름·인라인 스타일을 직접 쓰지 않으며, 문구표의 새 글이 모두 쓰인다.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.topics import channels as engine_channels, score as engine_score  # noqa: E402
from chanceblog_desktop.ui.core import gallery_data, gauges, part_rules, text, tokens  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
SOURCES = sorted(UI_DIR.rglob("*.py"))


def read(path):
    return Path(path).read_text(encoding="utf-8")


class DocumentValuesTest(unittest.TestCase):
    """새 기준 문서(C-Type v1.0.0)의 값을 **손으로** 적어 토큰과 한 글자씩 견준다 — 토큰 파일을 고쳐도 표는 따라 바뀌지 않으므로 값이 슬며시 바뀌면 빨개진다."""

    def test_the_theme_colors_equal_the_document(self):
        expected = {"bg_app": "#F4F7FB", "bg_sidebar": "#F7F9FC", "surface": "#FFFFFF", "surface_2": "#F8FAFD", "surface_selected": "#EEF5FF", "surface_hover": "#F4F8FF",
                    "border": "#DCE4F0", "border_strong": "#B8C7DA", "divider": "#E8EDF5", "border_hover": "#AFC7EE", "border_focus": "#2F6FED", "focus_ring": "#9CC2FF", "focus_ring_input": "#C9DDFF",
                    "primary": "#2F6FED", "primary_700": "#245ACC", "primary_pressed": "#1D4FAF", "primary_100": "#EAF2FF", "secondary_border": "#AFC1D8", "secondary_text": "#28456F",
                    "success": "#159A6C", "success_100": "#E9F8F2", "warning": "#E49A19", "warning_100": "#FFF5DE", "danger": "#D94A4A", "danger_100": "#FDECEC", "info": "#2F6FED", "info_100": "#EAF2FF",
                    "disabled_fill": "#C5D0E0", "track": "#E8EDF5", "shadow_base": "#16274A"}
        colors = tokens.palette()
        for key, value in expected.items():
            self.assertEqual(colors[key], value, key)

    def test_the_five_text_colors_did_not_change(self):
        self.assertEqual({key: value for _name, key, value, _use in tokens.TEXT_TOKENS},
                         {"text_strong": "#0B1736", "text_primary": "#14213D", "text_secondary": "#5F6B7A", "text_muted": "#8491A3", "text_disabled": "#AAB4C3"})

    def test_the_eleven_semantic_badge_pairs_equal_the_document(self):
        # 의도적 갱신(UI-C1a, D-170): 추천·가격변화·주의의 **글자 색**은 문서 값(#B36A00·#478327·#A86500)이 아니라 운영자가 정한 접근성 색이다 — 운영자 2026-11-06 확인 요청 004 의 답(대비 4.5 이상).
        # 나머지 8쌍과 11쌍의 배경은 문서 값 그대로다.
        document = (("public_data", "공공데이터", "#DCEBFF", "#1E63C6"), ("recommend", "추천", "#FFF0CA", "#9D5F07"), ("global_compare", "해외비교", "#EEE4FF", "#7545B8"),
                    ("culture_event", "문화행사", "#FFE3E3", "#B93A3A"), ("price_change", "가격변화", "#E8F7DF", "#437B28"), ("travel", "여행", "#E5F1FF", "#2C6FAE"),
                    ("tech", "기술", "#E6EAF2", "#354665"), ("policy", "정책", "#F2E8DE", "#7B573A"), ("life", "생활", "#E4F4FF", "#2F759A"),
                    ("caution", "주의", "#FFF2D6", "#9F6003"), ("blocked", "차단", "#FDE6E6", "#B92F2F"))
        self.assertEqual(tokens.SEMANTIC_BADGES, document)
        self.assertEqual(len(tokens.BADGE_KINDS), 11)
        colors = tokens.palette()
        for kind, label, bg, fg in document:
            self.assertEqual(tokens.badge_colors(colors, kind), (bg, fg), kind)
            self.assertEqual(tokens.badge_label(kind), label)

    def test_badge_text_contrast_is_measured_and_all_eleven_pairs_reach_4_5(self):
        """의도적 갱신(UI-C1a, D-170 — 운영자 2026-11-06 확인 요청 004 의 답: 4.5 이상 접근성 색으로 변경): 문서 값 그대로였을 때는 **추천·가격변화·주의** 세 쌍이 4.5 미만(3.73·4.14·4.18)이라 그 세 쌍만
        4.5 미만임을 못박았다. 운영자가 글자 색을 `#9D5F07`·`#437B28`·`#9F6003` 으로 바꿔 **11쌍 모두 4.5 이상**이다 — 새 단언은 '11쌍 전부 4.5 이상' 이고, 바꾼 세 쌍은 4.56·4.58·4.56 이다.
        누가 값을 고쳐 대비가 4.5 아래로 내려가면 이 시험이 알린다(늘 글자가 함께 있어 색만으로 뜻을 알리지 않는다)."""
        colors = tokens.palette()
        ratios = {}
        for kind in tokens.BADGE_KINDS:
            bg, fg = tokens.badge_colors(colors, kind)
            ratios[kind] = tokens.contrast(fg, bg)
            self.assertGreaterEqual(ratios[kind], 4.5, kind)
        self.assertEqual({kind: round(ratios[kind], 2) for kind in ("recommend", "price_change", "caution")}, {"recommend": 4.56, "price_change": 4.58, "caution": 4.56})

    def test_score_band_colors_and_bar_colors_equal_the_document(self):
        colors = tokens.palette()
        self.assertEqual((colors["score_high"], colors["score_good"], colors["score_mid"], colors["score_low"]), ("#159A6C", "#2F6FED", "#E49A19", "#D94A4A"))
        self.assertEqual((colors["bar_base"], colors["bar_data"], colors["bar_trend"], colors["bar_other"]), ("#8191AA", "#42A5F5", "#21B77A", "#F4C04B"))
        self.assertEqual([band.color_key for band in gauges.BANDS], ["score_high", "score_good", "score_mid", "score_low"])
        self.assertEqual(gauges.BAR_KINDS, ("base", "data", "trend", "other"))

    def test_the_status_text_variants_are_readable_on_white_and_on_their_own_light_surface(self):
        """새 상태색에 맞춰 다시 만든 글자용 변형 — 흰 바탕·앱 바탕·자기 옅은 면에서 모두 4.5 이상(성공·경고·위험·정보·주 색). 값도 손으로 못박는다."""
        colors = tokens.palette()
        self.assertEqual((colors["success_text"], colors["warning_text"], colors["danger_text"], colors["primary_text"], colors["info_text"], colors["purple_text"]),
                         ("#137D60", "#8F5600", "#BA4247", "#245ACC", "#245ACC", "#5B3FD0"))
        for text_key, surface_key in (("success_text", "success_100"), ("warning_text", "warning_100"), ("danger_text", "danger_100"), ("primary_text", "primary_100"), ("info_text", "info_100"), ("purple_text", "purple_100")):
            for ground in ("surface", "bg_app", surface_key):
                self.assertGreaterEqual(tokens.contrast(colors[text_key], colors[ground]), 4.5, f"{text_key} on {ground}")
        for band in gauges.BANDS:                                                       # 구간 이름 글자도 같은 기준
            self.assertGreaterEqual(tokens.contrast(colors[band.text_key], colors["surface"]), 4.5, band.key)
        for kind, key in (("up", "success_text"), ("down", "danger_text"), ("flat", "text_secondary")):
            self.assertGreaterEqual(tokens.contrast(colors[key], colors["surface"]), 4.5, kind)

    def test_the_old_primary_600_name_is_gone_and_the_ladder_follows_the_document(self):
        colors = tokens.palette()
        self.assertNotIn("primary_600", colors)
        self.assertLess(tokens.luminance(colors["primary_pressed"]), tokens.luminance(colors["primary_700"]))
        self.assertLess(tokens.luminance(colors["primary_700"]), tokens.luminance(colors["primary"]))
        self.assertGreaterEqual(tokens.contrast(colors["on_primary"], colors["primary"]), 4.5)

    def test_the_type_scale_equals_the_document(self):
        expected = {"display": (28, 700), "h1": (24, 700), "h2": (20, 700), "h3": (17, 600), "body_lg": (15, 400), "body": (14, 400), "small": (13, 400), "caption": (12, 400), "micro": (11, 500)}
        for role, (size, weight) in expected.items():
            style = tokens.TYPE[role]
            self.assertEqual((style.size, style.weight), (size, weight), role)
        self.assertEqual((tokens.TYPE["h1"].line_height, tokens.TYPE["h2"].line_height, tokens.TYPE["h3"].line_height, tokens.TYPE["caption"].line_height), (1.25, 1.25, 1.35, 1.35))
        for role in ("body_lg", "body", "small"):
            self.assertTrue(1.45 <= tokens.TYPE[role].line_height <= 1.55, role)
        self.assertEqual(tokens.TYPE["micro"].size, 11)                                 # 문서가 허용하는 가장 작은 글씨
        self.assertTrue(all(style.size >= 11 for style in tokens.TYPE.values()))
        self.assertEqual((tokens.TYPE["score_sm"].size, tokens.TYPE["score_lg"].size), (18, 22))      # 점수 링 가운데 숫자(문서 18~22 굵게)
        self.assertTrue(18 <= tokens.TYPE["score_sm"].size <= 22 and 18 <= tokens.TYPE["score_lg"].size <= 22)
        self.assertEqual((tokens.ROLE_TEXT["h3"], tokens.ROLE_TEXT["micro"]), ("text_strong", "text_secondary"))

    def test_radius_values_equal_the_document(self):
        radius = tokens.RADIUS
        self.assertEqual((radius["card"], radius["input"], radius["button"], radius["tooltip"]), (12, 8, 10, 8))
        self.assertTrue(8 <= radius["button"] <= 10 and 15 <= radius["chip"] <= 17)
        self.assertEqual((radius["gauge"], radius["usage"]), (6, 4))
        self.assertTrue(5 <= radius["gauge"] <= 6)

    def test_the_three_shadows_equal_the_document(self):
        shadow = tokens.SHADOW
        self.assertEqual(set(shadow), {"card", "hover", "selected"})
        self.assertEqual((shadow["card"].dx, shadow["card"].dy, shadow["card"].blur, shadow["card"].alpha), (0, 2, 8, 0.06))
        self.assertEqual((shadow["hover"].dx, shadow["hover"].dy, shadow["hover"].blur, shadow["hover"].alpha), (0, 6, 16, 0.10))
        self.assertEqual((shadow["selected"].dx, shadow["selected"].dy, shadow["selected"].blur, shadow["selected"].alpha), (0, 6, 18, 0.14))
        colors = tokens.palette()
        self.assertEqual(tokens.shadow_rgba(colors, "card"), (0, 2, 8, "rgba(22, 39, 74, 0.06)"))
        self.assertEqual(tokens.shadow_rgba(colors, "hover"), (0, 6, 16, "rgba(22, 39, 74, 0.1)"))
        self.assertEqual(tokens.shadow_rgba(colors, "selected"), (0, 6, 18, "rgba(47, 111, 237, 0.14)"))          # 선택은 파란 그림자
        for style in shadow.values():
            self.assertNotEqual(colors[style.color_key].upper(), "#000000")

    def test_the_three_card_states_follow_the_document(self):
        states = tokens.CARD_STATES
        self.assertEqual(states["default"], (1, "border", "card"))
        self.assertEqual(states["hover"], (1, "border_hover", "hover"))
        self.assertEqual(states["selected"], (2, "primary", "selected"))                # 선택은 2px 파란 테두리
        self.assertEqual(tokens.FOCUS_RING_PX, 2)

    def test_the_sizes_equal_the_document(self):
        size = tokens.SIZE
        self.assertEqual((size["control"], size["control_primary"], size["search_h"], size["input_h"]), (40, 44, 40, 40))
        self.assertTrue(30 <= size["chip_h"] <= 34 and 36 <= size["table_head_h"] <= 40 and 44 <= size["table_row_h"] <= 52 and 44 <= size["tab_h"] <= 48 and 42 <= size["menu_h"] <= 46)
        self.assertEqual((size["hit_min"], size["hit_comfort"]), (32, 40))
        self.assertTrue(size["hit_min"] <= size["hit"] <= size["hit_comfort"])
        self.assertTrue(40 <= size["ring_card"] <= 44 and 68 <= size["ring_detail"] <= 80)
        self.assertTrue(10 <= size["gauge_h"] <= 12)
        self.assertEqual(size["usage_h"], 8)
        self.assertTrue(0.10 <= tokens.RING_STROKE_RATIO <= 0.12)

    def test_the_frame_and_card_constants_equal_the_decisions(self):
        # 의도적 갱신(UI-C1a, D-174): 틀 상수(`FRAME`)는 이제 상단 앱 바·사이드바·서랍이 쓴다(옛 이름 '아직 안 쓰는 값' 에서 옮김). 상세 창은 운영자 결정(2026-11-06 확인 요청 004)이 문서 값을 이긴다 —
        # 고정 420~500(문서는 420~520)·좁은 폭 고정 400(문서는 400~440). 카드 규격(`CARD`)은 아직 안 쓴다(주제 후보 화면과 함께).
        frame = tokens.FRAME
        self.assertEqual((frame["app_bar"], frame["app_bar_range"], frame["sidebar_range"], frame["detail_range"], frame["detail_narrow"]), (60, (56, 64), (184, 208), (420, 500), 400))
        self.assertEqual((frame["window_min"], frame["window_default"], frame["fixed_detail_min"], frame["narrow_detail_min"]), ((1180, 720), (1600, 960), 1600, 1366))
        self.assertEqual((frame["detail_max_at"], frame["detail_columns_wide"], frame["detail_columns_narrow"], frame["drawer"], frame["drawer_max_ratio"]), (1920, 3, 2, 420, 0.92))
        self.assertTrue(frame["sidebar_range"][0] <= frame["sidebar"] <= frame["sidebar_range"][1] and frame["detail_range"][0] <= frame["detail"] <= frame["detail_range"][1])
        self.assertEqual((tokens.CARD["pad"], tokens.CARD["gap"], tokens.CARD["gap_narrow"], tokens.CARD["min_w"], tokens.CARD["w_range"], tokens.CARD["h_range"]), (16, 16, 12, 230, (260, 300), (280, 330)))
        self.assertEqual(tokens.LAYOUT["window_min"], (900, 560))                       # 최소 창은 지금 그대로(UI-C1a 지시) — 상단 앱 바·사이드바 크기만 새 틀(`FRAME`)로 옮겼다
        self.assertNotIn("topbar", tokens.LAYOUT)                                       # 새 틀로 옮겨 간 옛 값은 지웠다(죽은 토큰을 두지 않는다)
        self.assertNotIn("sidebar", tokens.LAYOUT)
        self.assertNotIn("drawer", tokens.LAYOUT)

    def test_the_space_scale_is_the_four_pixel_grid(self):
        self.assertEqual(tokens.SPACE["1"], 4)
        self.assertEqual({key: value for key, value in tokens.SPACE.items() if key != "12"}, {"1": 4, "2": 8, "3": 12, "4": 16, "5": 20, "6": 24, "8": 32, "10": 40})
        self.assertTrue(all(value % 4 == 0 for value in tokens.SPACE.values()))

    def test_no_pure_black_and_the_disabled_fill_keeps_the_filled_button_look(self):
        colors = tokens.palette()
        for key, value in colors.items():
            self.assertNotEqual(value.upper(), "#000000", key)
        self.assertEqual((colors["disabled_fill"], colors["on_primary"]), ("#C5D0E0", "#FFFFFF"))          # 꺼진 주·위험 단추: 연한 채움 + 흰 글자(문서 그대로)


class ScoreRulesTest(unittest.TestCase):
    def test_the_band_cutoffs_and_names_are_the_engine_ones_for_every_whole_score(self):
        """구간 경계 80/65/50 과 구간 이름이 엔진과 같다 — 0~100 모든 정수에서 UI 의 구간이 엔진의 `band_of` 와 맞는다(UI 가 따로 지어낸 기준이 아니다)."""
        self.assertEqual(gauges.SCORE_CUTOFFS, tuple(engine_channels.GRADE_CUTOFFS))
        mapping = {"high": engine_score.BAND_RECOMMENDED, "good": engine_score.BAND_GENERAL, "mid": engine_score.BAND_HOLD, "low": engine_score.BAND_EXCLUDED}
        for n in range(0, 101):
            self.assertEqual(mapping[gauges.score_band(n).key], engine_score.band_of(n), n)
        self.assertEqual([band.name for band in gauges.BANDS], ["우선 추천", "일반 후보", "보류", "제외"])
        self.assertEqual(engine_score.BAND_KO[engine_score.BAND_RECOMMENDED], "우선 추천")
        self.assertEqual(engine_score.BAND_KO[engine_score.BAND_GENERAL], "일반 후보")
        self.assertTrue(engine_score.BAND_KO[engine_score.BAND_HOLD].startswith("보류"))
        self.assertEqual(engine_score.BAND_KO[engine_score.BAND_EXCLUDED], "제외")

    def test_the_boundaries_by_hand(self):
        for score, key in ((100, "high"), (80, "high"), (79, "good"), (65, "good"), (64, "mid"), (50, "mid"), (49, "low"), (0, "low")):
            self.assertEqual(gauges.score_band(score).key, key, score)

    def test_missing_or_invalid_data_is_never_drawn_as_zero(self):
        """데이터 부족 — 없음·글자·불리언·NaN·무한대·소수·범위 밖은 모두 링이 없고(`visible` 거짓) 숫자 글도 없다. 실제 0점은 링이 있고 '제외' 구간이다."""
        for bad in (None, "92", "", True, False, float("nan"), float("inf"), -1, 101, 79.5, 100.5, [], {}):
            view = gauges.ring_view(bad)
            self.assertFalse(view.visible, repr(bad))
            self.assertEqual((view.score, view.band, view.sweep, view.text), (None, None, 0.0, ""), repr(bad))
            self.assertIsNone(gauges.clean_score(bad), repr(bad))
            self.assertIsNone(gauges.score_band(bad), repr(bad))
        zero = gauges.ring_view(0)
        self.assertTrue(zero.visible)
        self.assertEqual((zero.score, zero.band.key, zero.sweep, zero.text), (0, "low", 0.0, "0"))
        self.assertEqual(gauges.clean_score(92.0), 92)                                  # 정수인 실수는 정수로

    def test_the_ring_sweep_is_the_score_share_of_a_circle(self):
        self.assertEqual(gauges.ring_view(50).sweep, 180.0)
        self.assertEqual(gauges.ring_view(100).sweep, 360.0)
        self.assertEqual(gauges.ring_view(25).sweep, 90.0)
        self.assertEqual(gauges.ring_view(92).text, "92")                               # 링 안에는 숫자만

    def test_ring_sizes_stay_inside_the_document_ranges(self):
        self.assertTrue(40 <= gauges.ring_pixels("card") <= 44)
        self.assertTrue(68 <= gauges.ring_pixels("detail") <= 80)
        self.assertEqual((gauges.ring_pixels(10), gauges.ring_pixels(500), gauges.ring_pixels(60)), (40, 80, 60))
        for bad in ("huge", None, "44"):
            with self.assertRaises(ValueError):
                gauges.ring_pixels(bad)

    def test_the_delta_text_is_glyph_plus_words_and_colored_green_red_gray(self):
        up, down, flat, none = (gauges.delta_view(value) for value in (12, -5, 0, None))
        self.assertEqual((up.kind, up.text, up.spoken, up.color_key), ("up", "▲ +12", "12 상승", "success_text"))
        self.assertEqual((down.kind, down.text, down.spoken, down.color_key), ("down", "▼ -5", "5 하락", "danger_text"))
        self.assertEqual((flat.kind, flat.text, flat.spoken, flat.color_key), ("flat", "― 변화 없음", "변화 없음", "text_secondary"))
        self.assertEqual((none.kind, none.text, none.spoken), ("none", "", ""))
        for bad in ("12", True, float("nan"), [], object()):
            self.assertEqual(gauges.delta_view(bad).kind, "none", repr(bad))
        self.assertEqual(gauges.delta_view(0.4).kind, "flat")
        self.assertEqual(gauges.delta_view(12.6).text, "▲ +13")
        self.assertEqual(gauges.delta_view(-0.6).text, "▼ -1")

    def test_the_spoken_name_is_score_band_and_change_in_that_order(self):
        self.assertEqual(gauges.score_spoken(92, 12), "점수 92, 우선 추천, 12 상승")
        self.assertEqual(gauges.score_spoken(58, -3), "점수 58, 보류, 3 하락")
        self.assertEqual(gauges.score_spoken(65, 0), "점수 65, 일반 후보, 변화 없음")
        self.assertEqual(gauges.score_spoken(31), "점수 31, 제외")
        self.assertEqual(gauges.score_spoken(None, 7), "점수 데이터 부족")                 # 점수를 모르면 변화량도 말하지 않는다
        self.assertEqual(gauges.score_spoken(0), "점수 0, 제외")

    def test_the_samples_cover_both_sides_of_every_boundary_and_are_marked_as_examples(self):
        scores = [score for score, _delta in gallery_data.SCORE_SAMPLES]
        for edge in (80, 79, 65, 64, 50, 49, 0, None):
            self.assertIn(edge, scores)
        self.assertEqual(gallery_data.SAMPLE_NOTE, "예시")
        for usage in gallery_data.USAGE_SAMPLES:
            self.assertIn("이번 달", usage)
        everything = repr((gallery_data.TAB_SAMPLE, gallery_data.ACTION_SAMPLE, gallery_data.ACTION_MORE_SAMPLE, gallery_data.BAR_SAMPLE))
        self.assertNotRegex(everything, r"https?://|@|\.com|naver|blog\.|github")       # 실제 이름·주소가 없다


class BarRulesTest(unittest.TestCase):
    ITEMS = (("기존 점수", 55, "base"), ("추가 근거", 12, "data"), ("검색 흐름", 10, "trend"), ("기타", 15, "other"))

    def test_lengths_are_shares_of_the_positive_parts_and_colors_are_fixed_by_kind(self):
        view = gauges.bar_view(self.ITEMS)
        self.assertEqual([s.label for s in view.segments], ["기존 점수", "추가 근거", "검색 흐름", "기타"])
        self.assertAlmostEqual(sum(s.fraction for s in view.segments), 1.0)
        self.assertAlmostEqual(view.segments[0].fraction, 55 / 92)
        self.assertEqual([s.color_key for s in view.segments], ["bar_base", "bar_data", "bar_trend", "bar_other"])
        reordered = gauges.bar_view(reversed(self.ITEMS))
        self.assertEqual({s.label: s.color_key for s in reordered.segments}, {s.label: s.color_key for s in view.segments})          # 순서를 바꿔도 색은 그대로
        self.assertFalse(view.empty)

    def test_the_numbers_are_text_the_first_plain_and_the_rest_signed_with_a_total_on_the_right(self):
        view = gauges.bar_view(self.ITEMS)
        self.assertEqual([s.text for s in view.segments], ["55", "+12", "+10", "+15"])
        self.assertEqual((view.total_label, view.total_text), ("최종 점수", "92"))
        self.assertEqual(view.spoken, "점수 구성: 기존 점수 55, 추가 근거 +12, 검색 흐름 +10, 기타 +15, 최종 점수 92")
        explicit = gauges.bar_view(self.ITEMS, total_label="합계", total=90, signed=False)
        self.assertEqual(([s.text for s in explicit.segments], explicit.total_label, explicit.total_text), (["55", "12", "10", "15"], "합계", "90"))

    def test_negative_and_invalid_parts(self):
        view = gauges.bar_view((("기본", 50, "base"), ("감점", -3, "other")))
        self.assertEqual([s.text for s in view.segments], ["50", "-3"])
        self.assertEqual([s.fraction for s in view.segments], [1.0, 0.0])                # 음수는 길이가 없다
        self.assertEqual(view.total_text, "47")
        dropped = gauges.bar_view((("기본", 50, "base"), ("모름", None, "data"), ("글자", "12", "trend")))
        self.assertEqual([s.label for s in dropped.segments], ["기본"])                  # 숫자가 아닌 구성은 그리지 않는다
        for bad_kind in ("blue", "", None, "BASE"):
            with self.assertRaises(ValueError):
                gauges.bar_view((("x", 1, bad_kind),))

    def test_no_parts_means_no_bar_and_a_plain_note(self):
        for empty in ((), (("모름", None, "base"),)):
            view = gauges.bar_view(empty)
            self.assertTrue(view.empty)
            self.assertEqual((view.segments, view.total_text, view.spoken), ((), "", "구성 정보 없음"))

    def test_number_text(self):
        self.assertEqual((gauges.number_text(12), gauges.number_text(12, signed=True), gauges.number_text(-3, signed=True), gauges.number_text(0, signed=True)), ("12", "+12", "-3", "0"))
        self.assertEqual((gauges.number_text(2.5), gauges.number_text(3.0), gauges.number_text(None)), ("2.5", "3", ""))


class UsageRulesTest(unittest.TestCase):
    def view(self, used, limit=27000, **kwargs):
        return gauges.usage_view(used, limit, "회", "이번 달", **kwargs)

    def test_the_document_example(self):
        v = self.view(12400)
        self.assertEqual((v.text, v.percent_text, v.state, v.color_key, v.state_text), ("이번 달 12,400 / 27,000회", "46%", "ok", "primary", ""))
        self.assertAlmostEqual(v.fraction, 12400 / 27000)
        self.assertEqual(v.spoken, "이번 달 12,400 / 27,000회, 46%")

    def test_warning_starts_at_80_percent_and_danger_at_90_by_the_shown_percent(self):
        """상태는 **표시한(반올림한) 퍼센트**로 정한다 — 화면에 80% 로 보이면 경고색이다(79.6% 가 80% 로 보이는데 정상 색이면 어긋난다). 경계 양쪽을 손으로 센 값으로 본다(한도 27,000)."""
        cases = ((21400, 79, "ok"), (21500, 80, "warn"), (21600, 80, "warn"), (24100, 89, "warn"), (24200, 90, "danger"), (24300, 90, "danger"), (27000, 100, "danger"))
        for used, percent, state in cases:
            v = self.view(used)
            self.assertEqual((v.percent, v.state), (percent, state), used)
        warn, danger = self.view(22000), self.view(25000)
        self.assertEqual((warn.color_key, warn.state_text, warn.spoken), ("warning", "주의", "이번 달 22,000 / 27,000회, 81%, 주의"))
        self.assertEqual((danger.color_key, danger.state_text, danger.spoken), ("danger", "위험", "이번 달 25,000 / 27,000회, 93%, 위험"))
        self.assertEqual(self.view(27000).state_text, "위험")                              # 한도에 딱 닿은 것은 '넘음' 이 아니다

    def test_over_the_limit_is_danger_with_its_own_word_and_a_full_bar(self):
        v = self.view(30000)
        self.assertEqual((v.state, v.color_key, v.state_text, v.fraction, v.percent, v.percent_text), ("danger", "danger", "한도 넘음", 1.0, 111, "111%"))
        self.assertIn("30,000 / 27,000회", v.text)

    def test_numbers_always_come_with_the_unit(self):
        self.assertEqual(gauges.usage_view(5, 50, "건", "").text, "5 / 50건")
        for used in (0, 1, 12400, 27000):
            v = self.view(used)
            self.assertRegex(v.text, r"\d / 27,000회$")
            self.assertTrue(v.percent_text.endswith("%"))

    def test_unknown_usage_is_not_drawn_as_empty_or_full(self):
        for used, limit in ((None, 27000), (-1, 27000), (5, 0), (5, None), (5, -1), (True, 10), ("12", 10), (5, "10"), (float("nan"), 10)):
            v = gauges.usage_view(used, limit, "회", "이번 달")
            self.assertEqual((v.known, v.state, v.percent, v.fraction, v.percent_text, v.state_text), (False, "unknown", None, 0.0, "", ""), (used, limit))
            self.assertEqual(v.text, "이번 달 확인할 수 없어요")
        self.assertEqual(gauges.usage_view(None, 10).text, "확인할 수 없어요")
        self.assertEqual(self.view(0).state, "ok")                                       # 0회는 모르는 것이 아니라 실제 0이다
        self.assertTrue(self.view(0).known)

    def test_the_boundaries_are_the_documented_ones(self):
        self.assertEqual((gauges.USAGE_WARN, gauges.USAGE_DANGER), (80, 90))


class PartRulesTest(unittest.TestCase):
    KINDS = ["primary", "secondary", "secondary", "tertiary", "tertiary", "danger"]

    def test_the_action_bar_rules(self):
        self.assertEqual(part_rules.check_actions(self.KINDS), tuple(self.KINDS))
        self.assertEqual(part_rules.check_actions(["primary"]), ("primary",))
        bad = ([], ["secondary"], ["primary", "primary"], ["primary"] + ["secondary"] * 4, ["primary", "danger", "danger"], ["primary", "huge"])
        for kinds in bad:
            with self.assertRaises(ValueError, msg=str(kinds)):
                part_rules.check_actions(kinds)
        self.assertEqual(part_rules.check_actions(["primary"] + ["secondary"] * 3), ("primary",) + ("secondary",) * 3)

    def test_everything_fits_when_there_is_room_and_more_only_shows_when_needed(self):
        widths = [150, 110, 90, 90, 90, 90]
        total = sum(widths) + 8 * 5
        visible, folded, more = part_rules.plan_actions(total, self.KINDS, widths, 8, 36)
        self.assertEqual((visible, folded, more), ((0, 1, 2, 3, 4, 5), (), False))
        self.assertEqual(part_rules.plan_actions(total + 36 + 8, self.KINDS, widths, 8, 36, has_more=True), ((0, 1, 2, 3, 4, 5), (), True))      # 처음부터 더보기 항목이 있으면 ⋮ 가 보이고 자리도 센다
        self.assertEqual(part_rules.plan_actions(total, self.KINDS, widths, 8, 36, has_more=True)[1], (5,))                                    # ⋮ 자리가 모자라면 위험 3차부터 접힌다

    def test_the_fold_order_is_danger_then_tertiary_then_secondary_from_the_back_and_primary_stays(self):
        widths = [150, 110, 90, 90, 90, 90]
        expected = [5, 4, 3, 2, 1]                                                       # 위험 → 3차(뒤에서부터) → 보조(뒤에서부터)
        seen = set()
        for available in range(700, -1, -1):
            visible, folded, _more = part_rules.plan_actions(available, self.KINDS, widths, 8, 36)
            self.assertEqual(set(folded), set(expected[:len(folded)]), available)         # 접힌 것은 언제나 접는 순서의 앞부분이다
            self.assertIn(0, visible, available)                                          # 주요 행동은 폭이 0 이어도 늘 보인다
            seen.add(len(folded))
        self.assertEqual(seen, {0, 1, 2, 3, 4, 5})                                        # 폭을 줄이면 모두 접히는 데까지 간다
        visible, folded, more = part_rules.plan_actions(0, self.KINDS, widths, 8, 36)
        self.assertEqual((visible, folded, more), ((0,), (1, 2, 3, 4, 5), True))

    def test_a_medium_width_keeps_the_primary_and_the_secondaries(self):
        widths = [150, 110, 90, 90, 90, 90]
        visible, folded, more = part_rules.plan_actions(150 + 110 + 90 + 36 + 8 * 3, self.KINDS, widths, 8, 36)
        self.assertEqual((visible, folded, more), ((0, 1, 2), (3, 4, 5), True))

    def test_widths_must_match_the_actions(self):
        with self.assertRaises(ValueError):
            part_rules.plan_actions(500, self.KINDS, [100], 8, 36)

    def test_tab_keys(self):
        self.assertEqual([part_rules.tab_move(0, 4, key) for key in ("left", "right", "home", "end")], [3, 1, 0, 3])
        self.assertEqual([part_rules.tab_move(3, 4, key) for key in ("left", "right", "home", "end")], [2, 0, 0, 3])
        self.assertEqual(part_rules.tab_move(2, 4, "x"), 2)                              # 모르는 키는 그대로
        self.assertEqual(part_rules.tab_move(9, 4, "right"), 0)                          # 범위 밖 번호는 끝으로 맞춘 뒤 옮긴다
        self.assertEqual(part_rules.tab_move(0, 0, "right"), -1)
        self.assertEqual(part_rules.tab_move(0, 1, "right"), 0)

    def test_clip_text_makes_one_line_and_marks_the_cut(self):
        self.assertEqual(part_rules.clip_text("가나다", 16), "가나다")
        self.assertEqual(part_rules.clip_text("가  나\n다", 16), "가 나 다")
        cut = part_rules.clip_text("가" * 40, 16)
        self.assertEqual((len(cut), cut[-1]), (16, "…"))
        self.assertEqual(part_rules.clip_text("가" * 16, 16), "가" * 16)                  # 딱 맞으면 줄이지 않는다
        self.assertEqual(part_rules.clip_text("가" * 17, 16), "가" * 15 + "…")
        self.assertEqual(part_rules.clip_text("abc", 0), "abc")


class SourceRulesTest(unittest.TestCase):
    NEW_CORE = ("gauges.py", "part_rules.py", "gallery_data.py")
    NEW_QT = ("gauges.py", "bars.py")

    def test_the_new_pure_modules_never_import_the_screen_toolkit(self):
        for name in self.NEW_CORE:
            self.assertNotRegex(read(UI_DIR / "core" / name), r"(?m)^\s*(?:import|from)\s+PySide6", name)
        for path in (UI_DIR / "core").glob("*.py"):
            self.assertNotRegex(read(path), r"(?m)^\s*(?:import|from)\s+PySide6", path.name)

    def test_the_new_files_are_scanned_by_the_color_and_font_rules(self):
        scanned = {path.relative_to(UI_DIR).as_posix() for path in SOURCES}
        for name in self.NEW_CORE:
            self.assertIn(f"core/{name}", scanned)
        for name in self.NEW_QT:
            self.assertIn(f"qt/{name}", scanned)
        for path in SOURCES:
            if path.name == "tokens.py":
                continue
            source = read(path)
            self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", source), [], path.name)
            self.assertNotRegex(source, r"QFont\(\s*[\"']", path.name)
        for name in self.NEW_QT:                                                          # 새 부품은 인라인 스타일을 쓰지 않는다(속성만 붙이면 스타일시트가 입힌다)
            self.assertNotIn("setStyleSheet(", read(UI_DIR / "qt" / name), name)

    def test_widgets_never_write_literal_sizes_for_the_new_parts(self):
        """새 부품은 글자 크기·간격·모서리를 숫자로 적지 않고 토큰(`K.SIZE`·`K.SPACE`·`K.RADIUS`·`theme.font_for`)에서 받는다 — `setPixelSize` 는 링 숫자가 안 들어갈 때 한 자씩 줄이는 한 곳뿐."""
        for name in self.NEW_QT:
            source = read(UI_DIR / "qt" / name)
            self.assertNotRegex(source, r"font-size|setPointSize|QFont\(", name)
            bare = re.sub(r'K\.[A-Z_]+\["[^"]+"\]', "TOKEN", source)                      # 토큰 조회(`K.SPACE["3"]`)는 빼고 남은 숫자만 본다
            self.assertNotRegex(bare, r"setSpacing\(\s*[1-9]|setContentsMargins\([^)]*\b[1-9]\d?\b[^)]*\)", name)
        self.assertEqual(read(UI_DIR / "qt" / "gauges.py").count("setPixelSize"), 1)
        self.assertEqual(read(UI_DIR / "qt" / "bars.py").count("setPixelSize"), 0)

    def test_every_new_screen_text_is_used_and_free_of_promises(self):
        used = "\n".join(read(path) for path in list(UI_DIR.rglob("*.py")) + [ROOT / "scripts" / "ui_gallery.py", ROOT / "scripts" / "ui_capture.py"] if path.name != "text.py")
        new_keys = [key for key in text.T if key.startswith("cd_") or key.startswith("band_")]
        self.assertGreaterEqual(len(new_keys), 20)
        for key in new_keys:
            self.assertRegex(used, rf'["\']{key}["\']', key)                              # 죽은 글이 없다
            for word in text.FORBIDDEN:
                self.assertNotIn(word, text.T[key], key)
            self.assertNotRegex(text.T[key], r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", key)

    def test_the_icon_for_the_more_menu_exists_in_the_one_icon_family(self):
        from chanceblog_desktop.ui.core import icons
        self.assertIn("more_vertical", icons.ICONS)
        self.assertNotRegex(icons.ICONS["more_vertical"], r'fill="(?!none)')
        self.assertEqual(icons.ICONS["more_vertical"].count("<circle"), 3)


if __name__ == "__main__":
    unittest.main()
