"""화면 층의 순수 파이썬 부분 시험(PySide6 없이 돈다) — 디자인 토큰·아이콘·문구·안내 규칙·사진 출처·내 사진 규칙·작업 스레드·가짜 서비스·뷰모델.

지키는 것:
  1) 토큰: 운영자가 정한 Text Token 5개의 이름·값, 순수 검정(#000000)을 어디에도 쓰지 않음, 밝은 테마만(테마 선택 없음), 색·글꼴 이름·배율 값을 코드에 직접 쓰지 않음, 글자 대비.
  2) 아이콘: 한 벌의 선 굵기(1.75~2)·눈금·채움 없음, 의미 표가 실제 아이콘을 가리킴.
  3) 문구: 결과를 약속하는 표현 없음, 영문 오류 코드·스택 트레이스가 기본 문구에 없음.
  4) 안내(토스트): 3~4초, 같은 안내는 쌓지 않고 시간만 늘림.
  5) 사진 출처: 두 줄(둘째 줄은 사진 페이지 주소 + UTM), 사진 페이지·작가 프로필 주소를 따로 저장, Unsplash 가 아닌 주소 거절.
  6) 내 사진 규칙: JPG·JPEG·PNG·WebP 만, 확장자만 믿지 않음, 20MB 초과 거절, 긴 변 12,000px 초과 경고, 원본 불변.
  7) 작업 스레드: 중복 시작 막기·취소·실패해도 입력 보존·콜백 안에서 다시 시작 가능·기술 문구를 내보내지 않음.
  8) 뷰모델: 홈의 여섯 상태, 거르기, 선택, 서랍, 진단 정보(코드·시각만), 지어내지 않기(없는 값은 '데이터 없음').
키 모양 문자열·네트워크 없이 돈다.
"""
import ast
import contextlib
import datetime
import hashlib
import io
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.ui.core import app_state, attribution, icons, imagerules, jobs, notify, services, text, tokens  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
SOURCES = sorted(UI_DIR.rglob("*.py"))


def source_of(path):
    return path.read_text(encoding="utf-8")


def load(provider=None, **kwargs):
    provider = provider or services.FakeHomeProvider()
    state = app_state.AppState(provider, today=__import__("datetime").date(2026, 11, 3), **kwargs)
    state.apply_home(provider.load_home(lambda *a: None, lambda: False))
    return state


class TokensTest(unittest.TestCase):
    def test_text_tokens_are_the_five_operator_values(self):
        got = {name: value for name, _key, value, _use in tokens.TEXT_TOKENS}
        self.assertEqual(got, {"Text/Strong": "#0B1736", "Text/Primary": "#14213D", "Text/Secondary": "#5F6B7A", "Text/Muted": "#8491A3", "Text/Disabled": "#AAB4C3"})
        colors = tokens.palette()
        for _name, key, value, _use in tokens.TEXT_TOKENS:
            self.assertEqual(colors[key], value)

    def test_every_text_role_uses_a_text_token_or_a_tone_and_none_is_pure_black(self):
        colors = tokens.palette()
        for role, key in tokens.ROLE_TEXT.items():
            self.assertIn(key, tokens.TEXT_KEYS, role)
        for key, value in colors.items():
            self.assertNotIn(value.upper(), ("#000000", "#000"), key)

    def test_pure_black_is_not_written_anywhere_in_the_ui_code(self):
        pattern = re.compile(r"#000000|#000\b|['\"]black['\"]|QColor\(\s*0\s*,\s*0\s*,\s*0|rgba?\(\s*0\s*,\s*0\s*,\s*0|Qt\.black|Qt\.GlobalColor\.black", re.I)
        hits = [path.name for path in SOURCES if pattern.search(source_of(path))]
        self.assertEqual(hits, [])

    def test_only_the_light_theme_exists_and_no_theme_choice_is_shown(self):
        self.assertEqual(set(tokens.THEMES), {"light"})
        self.assertEqual(tokens.DEFAULT_THEME, "light")
        with self.assertRaises(KeyError):
            tokens.palette("dark")
        for value in text.T.values():
            self.assertNotRegex(value, r"테마|다크|Dark|어두운", value)

    def test_colors_live_in_tokens_only(self):
        """색 값(#rrggbb)은 tokens.py 에만 있다 — 화면 코드·부품·스타일시트 만들기에 직접 쓰지 않는다(Theme Token 으로 중앙 관리)."""
        hits = {path.name: re.findall(r"#[0-9A-Fa-f]{6}\b", source_of(path)) for path in SOURCES if path.name != "tokens.py"}
        self.assertEqual({name: found for name, found in hits.items() if found}, {})

    def test_no_font_family_name_is_written_in_the_app_code(self):
        """글꼴 Family 는 시스템 글꼴을 따른다 — 특정 이름(Segoe·맑은 고딕·Pretendard·Arial …)을 코드에 강제하지 않는다."""
        pattern = re.compile(r"Segoe|Malgun|맑은\s*고딕|Pretendard|Arial|Consolas|Courier|Noto|Roboto|Helvetica|Gulim|Dotum|Batang|font-family", re.I)
        hits = {path.name: pattern.findall(source_of(path)) for path in SOURCES if pattern.search(source_of(path))}
        self.assertEqual(hits, {})

    def test_the_screen_scale_is_never_multiplied_or_fixed_in_the_app_code(self):
        """High DPI 는 Qt6 가 자동 처리한다 — 배율 환경 변수·배율 곱셈·고정 값이 앱 코드에 없다."""
        pattern = re.compile(r"QT_SCALE_FACTOR|QT_FONT_DPI|QT_ENABLE_HIGHDPI|AA_EnableHighDpiScaling|AA_UseHighDpiPixmaps|HighDpiScaleFactorRoundingPolicy|setScaleFactor|RENDER_SCALE"
                             r"|devicePixelRatio\w*\s*\*|\*\s*[\w.()]*devicePixelRatio|logicalDotsPerInch|physicalDotsPerInch|\bdpi\s*=", re.I)
        hits = {path.name: pattern.findall(source_of(path)) for path in SOURCES if pattern.search(source_of(path))}
        self.assertEqual(hits, {})

    def test_typography_tokens_have_size_weight_and_line_height(self):
        self.assertTrue({"display", "h1", "h2", "body_lg", "body", "small", "caption", "button", "metric", "mono"} <= set(tokens.TYPE))
        for name, style in tokens.TYPE.items():
            self.assertTrue(10 <= style.size <= 32, name)
            self.assertIn(style.weight, (400, 500, 600, 700), name)
            self.assertTrue(1.1 <= style.line_height <= 1.7, name)
        self.assertEqual(tokens.type_style("sub"), tokens.TYPE["body"])

    def test_the_contrast_formula_gives_the_published_wcag_values(self):
        """대비 계산식 자체를 알려진 값으로 — 식이 조금 틀리면(계수 한 자리) 위의 '4.5 이상' 시험은 그대로 통과한다."""
        self.assertAlmostEqual(tokens.contrast("#FFFFFF", "#000000"), 21.0, places=6)
        self.assertAlmostEqual(tokens.contrast("#000000", "#FFFFFF"), 21.0, places=6)
        self.assertAlmostEqual(tokens.contrast("#FFFFFF", "#FFFFFF"), 1.0, places=6)
        self.assertAlmostEqual(tokens.contrast("#767676", "#FFFFFF"), 4.54, places=2)      # 흰 바탕에서 4.5 를 겨우 넘는 가장 연한 회색으로 잘 알려진 값
        self.assertAlmostEqual(tokens.luminance("#FF0000"), 0.2126, places=4)
        self.assertAlmostEqual(tokens.luminance("#00FF00"), 0.7152, places=4)
        self.assertAlmostEqual(tokens.luminance("#0000FF"), 0.0722, places=4)

    def test_text_contrast_is_readable_where_it_must_be(self):
        """본문·제목·보조 글자는 흰 바탕·앱 바탕에서 4.5 이상, 힌트(Muted)는 3 이상(보조 정보에만), 꺼진 글자(Disabled)는 Muted 보다 옅다(꺼진 것에만 쓴다)."""
        c = tokens.palette()
        for key in ("text_strong", "text_primary", "text_secondary"):
            for ground in ("surface", "bg_app", "surface_2"):
                self.assertGreaterEqual(tokens.contrast(c[key], c[ground]), 4.5, f"{key} on {ground}")
        self.assertGreaterEqual(tokens.contrast(c["text_muted"], c["surface"]), 3.0)
        self.assertLess(tokens.contrast(c["text_disabled"], c["surface"]), tokens.contrast(c["text_muted"], c["surface"]))
        for tone_key in ("success_text", "warning_text", "danger_text", "purple_text", "primary_text"):
            self.assertGreaterEqual(tokens.contrast(c[tone_key], c["surface"]), 4.5, tone_key)
        self.assertGreaterEqual(tokens.contrast(c["on_primary"], c["primary"]), 4.5)
        self.assertGreaterEqual(tokens.contrast(c["blog_a_text"], c["blog_a_bg"]), 4.5)
        self.assertGreaterEqual(tokens.contrast(c["blog_b_text"], c["blog_b_bg"]), 4.5)
        self.assertGreaterEqual(tokens.contrast(c["inverse_text"], c["inverse_bg"]), 4.5)

    def test_one_token_changes_everything_that_uses_it(self):
        changed = tokens.palette(overrides={"primary": "#123456"})
        self.assertEqual(changed["primary"], "#123456")
        with self.assertRaises(KeyError):
            tokens.palette(overrides={"no_such_key": "#123456"})

    def test_sizes_follow_the_operator_rules(self):
        self.assertGreaterEqual(tokens.SIZE["hit"], 36)
        self.assertEqual(tokens.SIZE["control_primary"], 44)
        self.assertTrue(40 <= tokens.SIZE["control"] <= 44)
        self.assertEqual(tokens.LAYOUT["window"], (1440, 900))
        self.assertLessEqual(tokens.LAYOUT["window_min"][0], 1280)
        self.assertEqual(icons.STROKE, 1.75)

    def test_the_tokens_nobody_uses_yet_are_the_documented_ones(self):
        """문서(UI_DESIGN_SPEC §2)가 '안 쓰는 값' 이라고 적은 토큰을 화면 코드가 정말 쓰지 않는지 — 쓰기 시작하면 이 시험이 문서를 고치라고 알린다. 쓰는 토큰은 반대로 쓰이고 있어야 한다(죽은 토큰이 아니다)."""
        others = "\n".join(source_of(path) for path in SOURCES if path.name != "tokens.py")
        for name in ("SPACE", "SHADOW", "SHADOW_COLOR_KEY", "COPY_FEEDBACK_MS"):
            self.assertNotRegex(others, rf"\b(?:K|tokens)\.{name}\b", name)
        self.assertNotRegex(others, r"MOTION_MS\[[\"'](?:hover|page)[\"']\]")
        for name in ("MOTION_MS", "TOAST_MS", "SCRIM_ALPHA", "RADIUS", "SIZE", "ICON", "LAYOUT", "TYPE", "TONES"):
            self.assertRegex(others, rf"\b{name}\b", name)
        documented = (ROOT / "docs" / "UI_DESIGN_SPEC.md").read_text(encoding="utf-8")
        for word in ("SPACE", "SHADOW", "COPY_FEEDBACK_MS", "안 쓰는 값"):
            self.assertIn(word, documented, word)

    def test_the_frame_sizes_stay_inside_the_ranges_the_operator_gave(self):
        """앱 틀의 크기는 명세가 정한 범위 안이다(손으로 적은 범위 — 값이 슬며시 바뀌지 않게): 사이드바 200~220·오른쪽 패널 280~320·위 막대 64~72·모서리 10~14·말풍선 모서리 8."""
        self.assertTrue(200 <= tokens.LAYOUT["sidebar"] <= 220, tokens.LAYOUT["sidebar"])
        self.assertTrue(280 <= tokens.LAYOUT["rail"] <= 320, tokens.LAYOUT["rail"])
        self.assertTrue(64 <= tokens.LAYOUT["topbar"] <= 72, tokens.LAYOUT["topbar"])
        for name in ("button", "input", "card", "badge", "thumb", "row"):
            self.assertTrue(10 <= tokens.RADIUS[name] <= 14, (name, tokens.RADIUS[name]))
        self.assertEqual(tokens.RADIUS["tooltip"], 8)
        self.assertEqual((tokens.SIZE["menu_h"], tokens.SIZE["badge_h"], tokens.SIZE["icon_button"], tokens.SIZE["chip_h"]), (44, 24, 36, 34))
        self.assertTrue(0.3 <= tokens.SCRIM_ALPHA <= 0.5, tokens.SCRIM_ALPHA)                 # 뒤를 덮는 막 — 뒤가 비쳐 보이는 어둠
        self.assertEqual((tokens.TOAST_MS, tokens.MOTION_MS["panel"]), (3500, 200))
        self.assertTrue(1500 <= tokens.COPY_FEEDBACK_MS <= 2000, tokens.COPY_FEEDBACK_MS)      # 복사 표시 1.5~2초(아직 안 쓰는 값이어도 정한 값은 지킨다)

    def test_every_text_role_keeps_its_agreed_size_weight_and_text_token(self):
        """글자 역할 하나하나의 크기·굵기·글자 색(Text Token)을 손으로 적은 표로 고정한다 — 한 글자 역할의 값이 바뀌면 화면 전체의 위계가 달라진다."""
        agreed = {"display": (28, 700, "text_strong"), "h1": (22, 700, "text_strong"), "h2": (18, 700, "text_strong"), "metric": (28, 700, "text_strong"),
                  "body_lg": (15, 600, "text_primary"), "body": (14, 400, "text_primary"), "button": (14, 600, "text_primary"), "mono": (13, 400, "text_primary"),
                  "small": (13, 400, "text_secondary"), "caption": (12, 400, "text_secondary"), "sub": (14, 400, "text_secondary"), "muted": (14, 400, "text_muted")}
        self.assertEqual(set(agreed), set(tokens.ROLE_TEXT))
        for role, (size, weight, key) in agreed.items():
            style = tokens.type_style(role)
            self.assertEqual((style.size, style.weight, tokens.ROLE_TEXT[role]), (size, weight, key), role)


class IconsTest(unittest.TestCase):
    def test_every_icon_is_a_valid_outline_svg_on_the_same_grid(self):
        self.assertEqual(icons.STROKE_RANGE, (1.75, 2.0))
        self.assertTrue(icons.STROKE_RANGE[0] <= icons.STROKE <= icons.STROKE_RANGE[1])
        for name in icons.ICONS:
            root = ET.fromstring(icons.svg(name, 20, "#112233"))
            self.assertTrue(root.tag.endswith("svg"), name)
            self.assertEqual(root.get("viewBox"), "0 0 24 24", name)
            self.assertEqual(root.get("fill"), "none", name)
            self.assertEqual(float(root.get("stroke-width")), icons.STROKE, name)
            self.assertEqual((root.get("stroke-linecap"), root.get("stroke-linejoin")), ("round", "round"), name)
            self.assertNotRegex(icons.ICONS[name], r'fill="(?!none)', name)             # 채운 아이콘을 섞지 않는다

    def test_the_meaning_table_and_menus_point_at_real_icons(self):
        for feature, (name, tone) in icons.MEANING.items():
            self.assertIn(name, icons.ICONS, feature)
            self.assertIn(tone, tokens.TONES, feature)                                     # 색 계열도 토큰에 있는 것만
        for key, _label, name in app_state.NAV:
            self.assertIn(name, icons.ICONS, key)
        for key in ("home", "topics", "draft", "history", "blogs", "settings"):
            self.assertIn(key, icons.MEANING)

    def test_icon_sizes_follow_the_size_rules(self):
        self.assertEqual((tokens.ICON["nav"], tokens.ICON["card"], tokens.ICON["button"], tokens.ICON["button_sm"]), (18, 22, 18, 16))
        self.assertEqual(tokens.ICON["box"], 40)

    def test_every_icon_name_used_in_the_ui_code_exists(self):
        names = set()
        for path in SOURCES:
            if path.name == "icons.py":
                continue
            names |= set(re.findall(r'(?:icon_name|"icon"|icon=|IconWidget\(|IconButton\(|NavButton\(|ToneSwatch\(|StateCard\()\s*[:=(]?\s*"([a-z_]+)"', source_of(path)))
        self.assertEqual(sorted(name for name in names if name not in icons.ICONS), [])


class TextTest(unittest.TestCase):
    def test_no_promise_words_and_no_english_codes_in_the_screen_text(self):
        for key, value in text.T.items():
            for word in text.FORBIDDEN:
                self.assertNotIn(word, value, key)
            self.assertNotRegex(value, r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", key)       # 영문 오류 코드(NETWORK_TIMEOUT …)
            self.assertNotRegex(value, r"Traceback|Exception|Error\b", key)

    def test_formatters_never_invent_values(self):
        self.assertEqual(text.fmt_demand(None), text.NO_DATA)
        self.assertEqual(text.fmt_docs(None), text.NO_DATA)
        self.assertEqual(text.fmt_demand(8600), "8,600회")
        self.assertEqual(text.fmt_int(None), text.NO_DATA)
        self.assertEqual(text.date_text(__import__("datetime").date(2026, 11, 3)), "2026년 11월 3일 (화)")


class NotifyTest(unittest.TestCase):
    def test_a_toast_lasts_three_to_four_seconds_and_same_text_extends_instead_of_stacking(self):
        policy = notify.ToastPolicy()
        self.assertTrue(3000 <= policy.duration_ms <= 4000)
        with self.assertRaises(ValueError):
            notify.ToastPolicy(2000)
        with self.assertRaises(ValueError):
            notify.ToastPolicy(5000)
        self.assertEqual(policy.offer("복사했어요")[0], "show")
        self.assertEqual(policy.offer("복사했어요")[0], "extend")
        self.assertEqual(policy.offer("  복사했어요 ")[0], "extend")
        self.assertEqual(policy.shown, 1)
        self.assertEqual(policy.offer("다른 안내")[0], "show")                          # 다른 안내는 그 자리를 바꾼다(쌓지 않는다)
        self.assertEqual(policy.shown, 2)
        policy.expire()
        self.assertEqual(policy.offer("다른 안내")[0], "show")
        self.assertEqual(policy.offer("")[0], "ignore")
        self.assertEqual(policy.offer(None)[0], "ignore")

    def test_a_very_long_toast_is_shortened(self):
        action, shown = notify.ToastPolicy().offer("가" * 500)
        self.assertEqual(action, "show")
        self.assertLessEqual(len(shown), notify.MAX_CHARS)

    def test_a_toast_is_cut_after_exactly_120_characters_by_hand_written_values(self):
        """위 시험은 구현 상수(`MAX_CHARS`)와 비교해서 상수를 1,200 으로 키워도 통과한다 — 손으로 적은 값으로 경계를 본다."""
        self.assertEqual(notify.ToastPolicy().offer("가" * 119), ("show", "가" * 119))
        self.assertEqual(notify.ToastPolicy().offer("가" * 120), ("show", "가" * 120))
        self.assertEqual(notify.ToastPolicy().offer("가" * 121), ("show", "가" * 119 + "…"))
        self.assertEqual(notify.ToastPolicy().offer("나 " * 300)[1], ("나 " * 60).strip()[:119] + "…")
        policy = notify.ToastPolicy()
        self.assertEqual(policy.offer("가" * 400)[0], "show")
        self.assertEqual(policy.offer("가" * 401)[0], "extend")                                  # 잘라 놓고 보면 같은 안내라 쌓이지 않는다


class AttributionTest(unittest.TestCase):
    PHOTO = "https://unsplash.com/photos/abc123"
    PROFILE = "https://unsplash.com/@sample"

    def credit(self, name="샘플 작가"):
        return attribution.PhotoCredit(name, self.PHOTO, self.PROFILE)

    def test_copy_is_two_lines_the_second_is_the_photo_page_with_utm_not_the_profile(self):
        lines = self.credit().copy_text().split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "Photo by 샘플 작가 on Unsplash")
        self.assertEqual(lines[1], self.PHOTO + "?utm_source=chanceblog_desktop&utm_medium=referral")
        self.assertNotIn("@sample", lines[1])

    def test_photo_page_and_profile_urls_are_kept_apart_in_the_metadata(self):
        meta = self.credit().metadata()
        self.assertEqual(meta["photo_page_url"], self.PHOTO)
        self.assertEqual(meta["photographer_profile_url"], self.PROFILE)
        self.assertNotEqual(meta["photo_page_url"], meta["photographer_profile_url"])
        self.assertIn("utm_source=", self.credit().profile_link())

    def test_utm_replaces_old_utm_values_and_keeps_other_arguments(self):
        link = attribution.with_utm("https://unsplash.com/photos/x?utm_source=old&ixid=1")
        self.assertIn("ixid=1", link)
        self.assertEqual(link.count("utm_source"), 1)
        self.assertIn("utm_source=chanceblog_desktop", link)

    def test_only_unsplash_https_addresses_are_accepted(self):
        for bad in ("http://unsplash.com/photos/x", "https://evil.example/photos/x", "https://unsplash.com.evil.example/x", "https://user:pw@unsplash.com/x", "javascript:alert(1)",
                    "https://unsplash.com/ x", "", None, "https://unsplash.com:8443/x"):
            with self.assertRaises(attribution.CreditError, msg=str(bad)):
                attribution.check_url(bad)
        with self.assertRaises(attribution.CreditError):
            attribution.PhotoCredit("이름", "https://evil.example/p", self.PROFILE)
        attribution.check_url("https://www.unsplash.com/photos/x")

    def test_the_name_is_cleaned_and_never_empty(self):
        self.assertEqual(self.credit("  가\u202e나\n다 ").photographer_name, "가 나 다")
        self.assertEqual(len(self.credit("가" * 300).photographer_name), attribution.MAX_NAME)
        with self.assertRaises(attribution.CreditError):
            self.credit("   ")


class ImageRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def file(self, name, size=100):
        path = Path(self.tmp.name) / name
        path.write_bytes(b"\xff" * size)
        return str(path)

    @staticmethod
    def seen(can_read=True, fmt="jpeg", width=800, height=600):
        return lambda _path: imagerules.Probe(can_read, fmt, width, height)

    def test_only_jpg_jpeg_png_webp_extensions_pass_the_first_check(self):
        self.assertEqual(imagerules.SUPPORTED_EXTENSIONS, (".jpg", ".jpeg", ".png", ".webp"))
        for name in ("a.jpg", "a.JPEG", "a.png", "a.webP"):
            self.assertTrue(imagerules.has_supported_extension(name), name)
        for name in ("a.gif", "a.bmp", "a.tiff", "a.svg", "a.txt", "a", "a.jpg.exe"):
            self.assertFalse(imagerules.has_supported_extension(name), name)
            verdict = imagerules.judge(self.file(name.replace("/", "_")), self.seen())
            self.assertEqual(verdict.kind, imagerules.UNSUPPORTED, name)
            self.assertIn("JPG·PNG·WebP", verdict.message)

    def test_a_real_image_passes_and_a_fake_one_is_refused_even_with_a_good_name(self):
        ok = imagerules.judge(self.file("a.jpg"), self.seen())
        self.assertTrue(ok.ok)
        self.assertEqual((ok.width, ok.height, ok.format, ok.warning), (800, 600, "jpeg", ""))
        fake = imagerules.judge(self.file("b.png"), self.seen(can_read=False))
        self.assertEqual(fake.kind, imagerules.NOT_IMAGE)
        self.assertEqual(fake.message, text.T["img_local_not_image"])

    def test_a_gif_renamed_to_jpg_is_refused_by_its_real_format(self):
        verdict = imagerules.judge(self.file("c.jpg"), self.seen(fmt="gif"))
        self.assertEqual((verdict.kind, verdict.format), (imagerules.UNSUPPORTED, "gif"))

    def test_the_size_limit_is_twenty_megabytes(self):
        self.assertEqual(imagerules.MAX_BYTES, 20 * 1024 * 1024)
        path = Path(self.tmp.name) / "big.jpg"
        with open(path, "wb") as handle:
            handle.truncate(imagerules.MAX_BYTES + 1)
        self.assertEqual(imagerules.judge(str(path), self.seen()).kind, imagerules.TOO_BIG)
        with open(path, "wb") as handle:
            handle.truncate(imagerules.MAX_BYTES)
        self.assertTrue(imagerules.judge(str(path), self.seen()).ok)

    def test_a_very_long_side_is_a_warning_not_a_refusal(self):
        self.assertEqual(imagerules.LONG_SIDE_WARN, 12_000)
        self.assertEqual(imagerules.judge(self.file("d.png"), self.seen(fmt="png", width=12_000, height=100)).warning, "")
        wide = imagerules.judge(self.file("e.png"), self.seen(fmt="png", width=12_001, height=100))
        self.assertTrue(wide.ok)
        self.assertEqual(wide.warning, text.T["img_local_long_side"])
        tall = imagerules.judge(self.file("f.webp"), self.seen(fmt="webp", width=100, height=13_000))
        self.assertTrue(tall.ok and tall.warning)

    def test_a_missing_file_and_a_reader_that_crashes_are_explained_without_stopping(self):
        self.assertEqual(imagerules.judge(str(Path(self.tmp.name) / "nope.jpg"), self.seen()).kind, imagerules.MISSING)

        def boom(_path):
            raise RuntimeError("secret internal text")

        verdict = imagerules.judge(self.file("g.jpg"), boom)
        self.assertEqual(verdict.kind, imagerules.UNREADABLE)
        self.assertNotIn("secret", verdict.message)

    def test_judging_never_changes_the_original_file(self):
        path = self.file("h.jpg", 5000)
        before = hashlib.sha256(Path(path).read_bytes()).hexdigest(), Path(path).stat().st_mtime_ns
        for probe in (self.seen(), self.seen(can_read=False), self.seen(fmt="gif")):
            imagerules.judge(path, probe)
        after = hashlib.sha256(Path(path).read_bytes()).hexdigest(), Path(path).stat().st_mtime_ns
        self.assertEqual(before, after)

    def test_judging_leaves_an_old_modification_time_alone(self):
        """방금 만든 파일은 수정 시각이 '지금' 이라 `utime(지금)` 으로 바꿔도 구별이 안 된다(윈도 시각 해상도) — 과거 시각으로 맞춘 파일로 본다."""
        path = self.file("old.jpg", 5000)
        os.utime(path, ns=(1_500_000_000 * 10**9, 1_500_000_000 * 10**9))                    # 2017-07 — 지금과 한참 다르다
        before = Path(path).stat().st_mtime_ns
        self.assertEqual(before, 1_500_000_000 * 10**9)
        for probe in (self.seen(), self.seen(can_read=False), self.seen(fmt="gif"), self.seen(width=20_000)):
            imagerules.judge(path, probe)
        imagerules.judge(path, lambda _path: (_ for _ in ()).throw(RuntimeError("읽기 실패")))
        self.assertEqual(Path(path).stat().st_mtime_ns, before)
        self.assertEqual(Path(path).stat().st_size, 5000)

    def test_every_refusal_has_its_own_message_and_none_is_technical(self):
        big = Path(self.tmp.name) / "big.jpg"
        with open(big, "wb") as handle:
            handle.truncate(imagerules.MAX_BYTES + 1)
        cases = (("img_local_unsupported", imagerules.judge(self.file("a.gif"), self.seen())), ("img_local_not_image", imagerules.judge(self.file("b.png"), self.seen(can_read=False))),
                 ("img_local_missing", imagerules.judge(str(Path(self.tmp.name) / "none.jpg"), self.seen())), ("img_local_too_big", imagerules.judge(str(big), self.seen())),
                 ("img_local_unreadable", imagerules.judge(self.file("c.jpg"), lambda _path: (_ for _ in ()).throw(RuntimeError("x")))))
        for key, verdict in cases:
            self.assertEqual(verdict.message, text.T[key], key)
            self.assertFalse(verdict.ok)
        self.assertEqual(len({verdict.message for _key, verdict in cases}), 5)                # 거절 이유마다 말이 다르다
        self.assertIn("20MB", cases[3][1].message)
        self.assertNotRegex(" ".join(verdict.message for _key, verdict in cases), r"Error|Exception|Traceback|[A-Z]{3,}_")


class JobsTest(unittest.TestCase):
    def run_job(self, work, **extra):
        events, done = [], threading.Event()

        def record(name):
            def callback(*args):
                events.append((name, args))
                if name in ("done", "error", "cancel"):
                    done.set()
            return callback

        runner = jobs.JobRunner()
        job = runner.start("k", work, payload={"입력": "그대로"}, on_progress=record("progress"), on_done=record("done"), on_error=record("error"), on_cancel=record("cancel"), **extra)
        self.assertIsNotNone(job)
        self.assertTrue(done.wait(5))
        job.join(2)
        return runner, job, events

    def test_a_job_reports_progress_then_the_result_and_returns_the_payload(self):
        def work(progress, cancelled):
            progress(0.5, "절반")
            return 42

        _runner, job, events = self.run_job(work)
        names = [name for name, _ in events]
        self.assertEqual(names, ["progress", "done"])
        self.assertEqual(events[-1][1], (42, {"입력": "그대로"}))
        self.assertEqual(job.state, jobs.Job.DONE)

    def test_a_failure_gives_back_the_input_unchanged_and_a_friendly_message(self):
        def work(progress, cancelled):
            raise jobs.JobFailure("연결이 끊겼어요.", code="NETWORK_DOWN")

        _runner, job, events = self.run_job(work)
        failure, payload = events[-1][1]
        self.assertEqual(events[-1][0], "error")
        self.assertEqual((failure.user_message, failure.code), ("연결이 끊겼어요.", "NETWORK_DOWN"))
        self.assertEqual(payload, {"입력": "그대로"})                                   # 입력 보존

    def test_an_unexpected_error_never_leaks_its_text(self):
        def work(progress, cancelled):
            raise ValueError("내부 경로 C:\\비밀\\값 과 입력한 글")

        _runner, _job, events = self.run_job(work)
        failure, _payload = events[-1][1]
        self.assertEqual(failure.user_message, text.T["job_failed"])
        self.assertEqual(failure.code, "ValueError")
        self.assertNotIn("비밀", failure.user_message + failure.code)

    def test_a_second_start_with_the_same_key_is_refused_while_it_runs(self):
        release = threading.Event()
        runner = jobs.JobRunner()
        first = runner.start("same", lambda progress, cancelled: release.wait(5))
        self.assertIsNotNone(first)
        self.assertTrue(runner.running("same"))
        self.assertIsNone(runner.start("same", lambda progress, cancelled: None))
        self.assertIsNotNone(runner.start("other", lambda progress, cancelled: None))
        release.set()
        first.join(2)
        self.assertFalse(runner.running("same"))
        self.assertIsNotNone(runner.start("same", lambda progress, cancelled: None))              # 끝난 뒤에는 다시 시작할 수 있다

    def test_cancel_stops_a_polite_job_and_discards_a_result_that_arrived_anyway(self):
        started = threading.Event()

        def polite(progress, cancelled):
            started.set()
            while not cancelled():
                time.sleep(0.005)
            raise jobs.JobCancelled()

        runner = jobs.JobRunner()
        events = []
        done = threading.Event()
        job = runner.start("c", polite, payload="P", on_cancel=lambda payload: (events.append(payload), done.set()))
        self.assertTrue(started.wait(2))
        runner.cancel("c")
        self.assertTrue(done.wait(2))
        self.assertEqual(events, ["P"])
        self.assertEqual(job.state, jobs.Job.CANCELLED)

        gate = threading.Event()
        late = runner.start("late", lambda progress, cancelled: (gate.wait(2), "결과")[1], on_done=lambda *a: events.append("done"), on_cancel=lambda p: events.append("cancelled"))
        runner.cancel("late")
        gate.set()
        late.join(2)
        self.assertEqual(events[-1], "cancelled")                                   # 취소를 눌렀으면 늦게 온 결과는 버린다

    def test_progress_stops_after_cancel_and_callbacks_may_restart_the_job(self):
        runner = jobs.JobRunner()
        restarted = []

        def again(result, payload):
            restarted.append(runner.start("loop", lambda progress, cancelled: None))     # 콜백 안에서는 이미 '끝남' 이라 다시 시작할 수 있다

        first = runner.start("loop", lambda progress, cancelled: 1, on_done=again)
        first.join(2)
        time.sleep(0.05)
        self.assertEqual(len(restarted), 1)
        self.assertIsNotNone(restarted[0])

    def test_a_crashing_callback_does_not_kill_the_job_and_only_its_class_name_is_kept(self):
        def bad(*args):
            raise KeyError("입력한 글")

        runner = jobs.JobRunner()
        job = runner.start("b", lambda progress, cancelled: 1, on_done=bad)
        job.join(2)
        self.assertEqual(job.callback_error, "KeyError")
        self.assertEqual(job.state, jobs.Job.DONE)

    def test_one_job_object_runs_only_once_even_if_it_is_started_twice(self):
        calls = []
        job = jobs.Job("once", lambda progress, cancelled: calls.append(1))
        self.assertTrue(job.start())
        self.assertFalse(job.start())                                                   # 같은 작업을 또 시작하지 않는다
        job.join(2)
        self.assertFalse(job.start())                                                   # 끝난 뒤에도(다시 돌리려면 새 작업)
        self.assertEqual(calls, [1])

    def test_cancel_all_and_join_all(self):
        runner = jobs.JobRunner()
        for name in "ab":
            runner.start(name, lambda progress, cancelled: [time.sleep(0.01) for _ in range(500) if not cancelled()])
        runner.cancel_all()
        self.assertTrue(runner.join_all(2))
        self.assertFalse(runner.running())

    def test_a_job_that_ends_with_system_exit_or_a_keyboard_interrupt_is_a_failure_not_forever_running(self):
        """`SystemExit` 는 `Exception` 이 아니라서 예전에는 작업이 영원히 running 으로 남아 다시 불러오기가 막혔다(검증 M-6)."""
        for stop in (SystemExit(3), SystemExit(), KeyboardInterrupt()):
            def work(progress, cancelled, stop=stop):
                raise stop

            runner, job, events = self.run_job(work)
            failure, payload = events[-1][1]
            self.assertEqual(events[-1][0], "error", repr(stop))
            self.assertEqual((failure.user_message, failure.code), (text.T["job_failed"], type(stop).__name__))
            self.assertEqual(payload, {"입력": "그대로"})                                      # 입력 보존
            self.assertEqual(job.state, jobs.Job.FAILED)
            self.assertFalse(runner.running("k"))
            self.assertIsNotNone(runner.start("k", lambda progress, cancelled: None))          # 다시 시작할 수 있다


class ServicesAndStateTest(unittest.TestCase):
    def test_the_fake_service_marks_itself_as_sample_and_has_missing_values_as_none(self):
        data = services.FakeHomeProvider().load_home(lambda *a: None, lambda: False)
        self.assertTrue(data.sample)
        self.assertTrue(services.FakeHomeProvider.sample)
        self.assertTrue(any(topic.demand is None for topic in data.topics))

    def test_each_scenario_gives_its_own_screen_state(self):
        expected = {"normal": "normal", "empty": "empty", "partial": "partial", "offline": "offline"}
        for scenario, state in expected.items():
            self.assertEqual(load(services.FakeHomeProvider(scenario)).list_state, state, scenario)
        failing = services.FakeHomeProvider("error")
        with self.assertRaises(jobs.JobFailure):
            failing.load_home(lambda *a: None, lambda: False)
        with self.assertRaises(ValueError):
            services.FakeHomeProvider("nope")

    def test_the_menu_has_exactly_six_entries_in_the_operator_order(self):
        self.assertLessEqual(len(app_state.NAV), app_state.MAX_NAV)
        self.assertEqual([text.T[label] for _key, label, _icon in app_state.NAV], ["홈", "주제 후보", "초안 작성", "발행 기록", "블로그 관리", "설정"])
        state = load()
        self.assertFalse(state.nav("home"))                                           # 지금 화면은 다시 안 간다
        self.assertTrue(state.nav("topics"))
        self.assertFalse(state.nav("nope"))
        self.assertEqual(state.page_view()["button"], text.T["soon_btn"])

    def test_home_view_has_four_cards_five_rows_and_five_chips(self):
        view = load().home_view()
        self.assertEqual([card["label"] for card in view["cards"]], ["추천 주제", "작성 완료", "발행 완료", "저장된 아이디어"])
        self.assertEqual(len(view["rows"]), 5)
        self.assertEqual([chip["label"] for chip in view["chips"]], ["전체", "블로그 A", "블로그 B", "트렌드 급상승", "신규 키워드"])
        self.assertTrue(view["sample"])
        self.assertEqual([row["selected"] for row in view["rows"]], [True, False, False, False, False])
        self.assertEqual(view["date"], "2026년 11월 3일 (화)")

    def test_chips_filter_rows_and_keep_a_valid_selection(self):
        state = load()
        self.assertTrue(state.set_home_filter("b"))
        self.assertTrue(all("B" in topic.blogs for topic in state.home_rows()))
        self.assertIn(state.selected, [topic.id for topic in state.home_rows()])
        state.set_home_filter("hot")
        self.assertTrue(all(topic.trend == "up" for topic in state.home_rows()))
        self.assertFalse(state.set_home_filter("nope"))
        self.assertEqual(state.home_filter, "hot")
        state.set_home_filter("all")
        self.assertTrue(state.select_topic("s3"))
        self.assertFalse(state.select_topic("zzz"))

    def test_held_topics_are_not_recommended_but_counted_as_saved_ideas(self):
        state = load()
        view = state.home_view()
        self.assertEqual(view["cards"][3]["value"], "2개")
        self.assertEqual(view["cards"][0]["value"], "6개")                                # 추천 주제는 보류를 뺀 수(전체 8개 중 6개)
        self.assertEqual(view["chips"][0]["count"], 6)
        self.assertTrue(all(topic.status != "hold" for topic in state.home_rows()))      # 다섯 줄만 그리지만 걸러내는 일은 전체에 한다
        self.assertTrue(all(not row["hold"] for row in view["rows"]))

    def test_missing_values_are_shown_as_no_data_never_invented(self):
        state = load()
        state.set_home_filter("b")
        rows = {row["title"]: row for row in state.home_view()["rows"]}
        earphones = rows["무선 이어폰 비교 포인트"]
        self.assertEqual((earphones["demand"], earphones["docs"], earphones["trend"]["label"]), (text.NO_DATA, text.NO_DATA, text.NO_DATA))
        self.assertTrue(earphones["demand_missing"] and earphones["docs_missing"])
        data = services.HomeData(topics=state.data.topics)                              # 집계하지 못한 값
        state.apply_home(data)
        cards = state.home_view()["cards"]
        self.assertEqual((cards[1]["value"], cards[1]["sub"], cards[1]["missing"]), ("–", text.T["sum_unavailable"], True))
        self.assertIn(text.NO_DATA, cards[2]["a11y"])

    def test_partial_hides_the_trend_and_offline_says_so(self):
        partial = load(services.FakeHomeProvider("partial")).home_view()
        self.assertEqual(partial["banner"][1], text.T["partial"])
        self.assertTrue(all(row["trend"]["key"] == "none" for row in partial["rows"]))
        state = app_state.AppState(services.FakeHomeProvider())                          # 값이 남아 있어도 '못 가져온 지표' 로 표시했으면 화면은 그 값을 보이지 않는다(뷰모델의 규칙)
        state.apply_home(services.HomeData(topics=services.sample_topics(), partial=("trend",), sample=True))
        self.assertEqual(state.list_state, "partial")
        self.assertTrue(any(topic.trend for topic in state.data.topics))
        self.assertTrue(all(row["trend"]["key"] == "none" for row in state.home_view()["rows"]))
        offline = load(services.FakeHomeProvider("offline")).home_view()
        self.assertEqual(offline["banner"], ("cloud_off", text.T["offline"]))
        self.assertIsNone(load().home_view()["banner"])

    def test_the_error_state_keeps_old_data_and_shows_codes_only_in_the_diagnostic_text(self):
        state = load()
        failure = jobs.JobFailure("연결이 끊겼어요.", code="NETWORK_DOWN")
        state.apply_failure(failure, __import__("datetime").datetime(2026, 11, 3, 10, 0, 0))
        view = state.home_view()
        self.assertEqual(view["state"], "error")
        self.assertIsNotNone(state.data)                                                # 이전 데이터는 지우지 않는다
        self.assertEqual(view["error"]["user"], "연결이 끊겼어요.")
        self.assertIn("NETWORK_DOWN", view["error"]["diag"])
        self.assertIn("2026-11-03 10:00:00", view["error"]["diag"])
        visible = [view["title"], view["sub"], view["error"]["title"], view["error"]["desc"], view["error"]["user"], view["error"]["button"]] + [card["sub"] for card in view["cards"]]
        for shown in visible:
            self.assertNotIn("NETWORK_DOWN", shown)

    def test_the_diagnostic_text_holds_only_the_code_and_the_time_and_masks_secret_shapes(self):
        fake_key = "AI" + "za" + "B" * 35
        shown = app_state.diagnostic_text(jobs.JobFailure("x", code=f"KEY_{fake_key}"), __import__("datetime").datetime(2026, 1, 2, 3, 4, 5))
        self.assertNotIn(fake_key, shown)
        self.assertEqual(len(shown.splitlines()), 2)
        self.assertNotIn("Traceback", app_state.diagnostic_text(jobs.JobFailure("x", code="")))

    def test_cancelled_loading_returns_to_the_previous_picture(self):
        state = load()
        state.list_state = "loading"
        state.apply_cancelled()
        self.assertEqual(state.list_state, "normal")
        empty = app_state.AppState(services.FakeHomeProvider())
        empty.apply_cancelled()
        self.assertEqual(empty.list_state, "empty")

    def test_loading_in_a_thread_ends_with_the_data_and_a_second_start_is_refused(self):
        provider = services.FakeHomeProvider(delay=0.3)
        state = app_state.AppState(provider)
        done, results = threading.Event(), []
        job = state.start_load(on_done=lambda data, payload: (results.append(data), done.set()))
        self.assertIsNotNone(job)
        self.assertEqual(state.list_state, "loading")
        self.assertTrue(state.loading)
        self.assertIsNone(state.start_load())                                           # 중복 클릭
        self.assertEqual(state.load_count, 1)
        self.assertTrue(done.wait(5))
        job.join(2)
        state.apply_home(results[0])
        self.assertEqual(state.list_state, "normal")
        self.assertFalse(state.loading)

    def test_cancelling_a_slow_load_calls_the_cancel_callback(self):
        state = app_state.AppState(services.FakeHomeProvider(delay=5))
        done = threading.Event()
        job = state.start_load(on_cancel=lambda payload: done.set())
        state.cancel_load()
        self.assertTrue(done.wait(3))
        job.join(2)
        self.assertEqual(job.state, jobs.Job.CANCELLED)

    def test_the_drawer_shows_details_and_no_internal_ids(self):
        state = load()
        self.assertTrue(state.open_drawer("s2"))
        view = state.drawer_view()
        self.assertEqual(view["topic"], "전기요금 절약 방법")
        labels = [field["label"] for field in view["fields"]]
        self.assertEqual(labels, ["월간 검색량", "PC·모바일 검색 비중", "관련 블로그 검색 결과 수", "최근 트렌드", "계절성", "기존 작성 여부", "보조 키워드", "데이터 조회일"])
        self.assertEqual(state.close_drawer(), "s2")
        self.assertIsNone(state.drawer_view())
        self.assertFalse(state.open_drawer("nope"))
        for shown in [view["topic"], view["reason"]] + [f"{f['label']} {f['value']}" for f in view["fields"]]:
            self.assertNotRegex(shown, r"\bs\d+\b")

    def test_the_home_list_is_ordered_by_priority_then_newest_with_hand_written_expectations(self):
        def topic(name, priority, date):
            return services.Topic(id=name, title=name, blogs=("A",), priority=priority, date=date)

        data = services.HomeData(topics=(topic("낮음 최신", "낮음", "2026-11-04"), topic("보통 옛날", "보통", "2026-10-01"), topic("높음 옛날", "높음", "2026-10-02"), topic("높음 최신", "높음", "2026-11-03"),
                                         topic("우선도 모름", "", "2026-11-04"), topic("보통 최신", "보통", "2026-11-02")))
        state = app_state.AppState(services.FakeHomeProvider())
        state.apply_home(data)
        view = state.home_view()
        self.assertEqual([row["title"] for row in view["rows"]], ["높음 최신", "높음 옛날", "보통 최신", "보통 옛날", "낮음 최신"])      # 우선도를 모르는 후보는 맨 뒤(여섯 번째라 홈에는 안 나온다)
        self.assertEqual(view["selected"], "높음 최신")
        self.assertEqual(view["cards"][0]["value"], "6개")
        small = app_state.AppState(services.FakeHomeProvider())
        small.apply_home(services.HomeData(topics=(topic("가", "낮음", "2026-11-01"), topic("나", "높음", "2026-11-01"), topic("다", "보통", "2026-11-01"))))
        self.assertEqual((small.selected, small.home_view()["selected"], [row["title"] for row in small.home_view()["rows"]]), ("나", "나", ["나", "다", "가"]))       # 처음 선택은 맨 위(가장 먼저 보이는) 행
        sample = [row["title"] for row in load().home_view()["rows"]]
        self.assertEqual(sample, ["자취방 곰팡이 없애는 순서", "전기요금 절약 방법", "노트북 배터리 오래 쓰는 법", "프리랜서 종합소득세 신고 순서", "에어프라이어 고르는 기준"])     # 예시 데이터: 높음 넷(날짜 순) → 보통 하나

    def test_only_fake_data_is_marked_as_an_example(self):
        """`예시 데이터` 표시는 가짜(예시) 데이터에만 — 실제 데이터를 예시라고 하거나(거짓 경고) 예시를 실제처럼 보이면 안 된다."""
        sample = load()
        self.assertTrue(sample.home_view()["sample"])
        sample.open_drawer("s1")
        self.assertTrue(sample.drawer_view()["sample"])
        real = app_state.AppState(services.FakeHomeProvider())
        real.apply_home(services.HomeData(topics=services.sample_topics(3), sample=False))
        self.assertFalse(real.home_view()["sample"])
        real.open_drawer("s1")
        self.assertFalse(real.drawer_view()["sample"])
        self.assertFalse(app_state.AppState(services.FakeHomeProvider()).home_view()["sample"])          # 아직 아무것도 못 받았을 때

    def test_the_drawer_split_is_pc_and_mobile_adding_up_to_one_hundred(self):
        state = load()
        state.open_drawer("s1")                                                         # 예시 후보 1: 모바일 78
        fields = {field["label"]: field["value"] for field in state.drawer_view()["fields"]}
        self.assertEqual(fields["PC·모바일 검색 비중"], "PC 22% · 모바일 78%")
        for mobile, expected in ((0, "PC 100% · 모바일 0%"), (45, "PC 55% · 모바일 45%"), (100, "PC 0% · 모바일 100%"), (None, "데이터 없음")):
            state.apply_home(services.HomeData(topics=(services.Topic(id="m", title="비중", blogs=("A",), mobile=mobile, date="2026-11-01"),)))
            state.open_drawer("m")
            shown = {field["label"]: field["value"] for field in state.drawer_view()["fields"]}
            self.assertEqual(shown["PC·모바일 검색 비중"], expected, mobile)

    def test_unbuilt_features_only_say_so(self):
        state = load()
        self.assertIn("다음 단계", state.draft_requested("s1", "A"))
        self.assertEqual(state.draft_requested("zzz", "A"), "")
        self.assertIn("다음 단계", state.quick("new"))
        self.assertEqual(state.quick("history"), "")
        self.assertEqual(state.page, "history")
        for key, page in (("saved", "topics"), ("history", "history"), ("blogs", "blogs")):                  # 빠른 작업마다 가는 곳이 다르다
            moved = load()
            self.assertEqual((moved.quick(key), moved.page), ("", page), key)

    def test_a_key_shaped_text_in_a_candidate_is_masked_everywhere_it_is_shown(self):
        fake = "AI" + "za" + "D" * 35                                                    # 구글 키 모양의 가짜 값(조각을 이어 만들어 저장소에는 키 문자열이 없다)
        topic = services.Topic(id="k1", title=f"제목 {fake}", desc=f"설명 {fake}", keywords=(fake, "평범한 키워드"), reason=f"이유 {fake}", season=f"계절 {fake}", blogs=("A",), date="2026-11-01")
        state = app_state.AppState(services.FakeHomeProvider())
        state.apply_home(services.HomeData(topics=(topic,), blogs=(services.BlogInfo("A", f"블로그 {fake}"),)))
        state.open_drawer("k1")
        shown = repr(state.home_view()) + repr(state.drawer_view())
        self.assertNotIn(fake, shown)
        self.assertIn("가림", state.home_view()["rows"][0]["title"])
        self.assertIn("평범한 키워드", shown)

    def test_the_view_model_never_contains_internal_ids_or_english_status_codes(self):
        view = load().home_view()
        for row in view["rows"]:
            self.assertIn(row["status"], app_state.STATUS_LABEL.values())
            self.assertNotIn(row["status"], ("new", "selected", "hold"))
            self.assertNotRegex(row["a11y"], r"\bs\d+\b")

    def test_an_unexpected_exception_becomes_an_error_state_with_only_the_exception_name(self):
        """화면 스레드 슬롯에서 난 예외가 '불러오는 중' 에 멈추지 않고 오류 상태가 된다(검증 M-6). 예외의 내용(값·경로·키)은 상태·화면에 남지 않는다."""
        fake_key = "AI" + "za" + "E" * 35
        state = load()
        state.open_drawer("s1")
        state.apply_unexpected(ValueError(f"내부 경로 C:\\비밀\\값 {fake_key}"), datetime.datetime(2026, 11, 3, 10, 0, 0))
        view = state.home_view()
        self.assertEqual((view["state"], state.list_state), ("error", "error"))
        self.assertIsNone(state.data)                                                    # 이상한 값 때문에 난 오류일 수 있어 버린다
        self.assertIsNone(state.drawer_view())
        self.assertEqual(view["error"]["user"], text.T["job_failed"])
        self.assertIn("ValueError", view["error"]["diag"])
        self.assertIn("2026-11-03 10:00:00", view["error"]["diag"])
        shown = repr(view) + repr(vars(state.failure))
        for piece in (fake_key, "비밀", "C:\\", "내부 경로"):
            self.assertNotIn(piece, shown)
        state.apply_home(services.FakeHomeProvider().load_home(lambda *a: None, lambda: False))        # 다시 불러오면 회복한다
        self.assertEqual((state.list_state, state.failure), ("normal", None))

    def test_the_image_placeholder_names_a_field_only_when_the_field_is_known(self):
        """실제 후보의 분야는 모른다 — 장식 아이콘을 돌려 쓰면서 '생활·에너지 주제' 라고 설명하면 지어낸 값이다."""
        known = app_state.topic_vm(services.sample_topics(1)[0])["thumb"]
        self.assertEqual((known["category"], known["label"]), ("생활·집", "생활·집 주제의 이미지 자리 표시"))
        self.assertTrue(all(topic.category for topic in services.sample_topics()))        # 예시 후보는 모두 분야를 안다
        for icon in ("t_bolt", "t_laptop", "t_spark", "t_droplet"):
            unknown = app_state.topic_vm(services.Topic(id="x", title="분야를 모르는 후보", icon=icon, date="2026-11-01"))["thumb"]
            self.assertEqual((unknown["category"], unknown["label"]), ("", text.T["thumb_label_plain"]), icon)
            for word in ("생활", "에너지", "IT", "재테크", "쇼핑", "장소", "기타", "주제"):
                self.assertNotIn(word, unknown["label"])


class UnexpectedLineTest(unittest.TestCase):
    """처리하지 못한 예외를 표준 오류에 남기는 한 줄 — 예외 이름과 비밀을 가리고 경로를 지운 짧은 글뿐이다(추적에는 경로·값이 들어 있다)."""
    KEY = "AI" + "za" + "F" * 35

    def test_the_line_has_the_exception_name_and_no_secret_no_path_and_one_line(self):
        prefix = text.T["unexpected_line"] + " (KeyError)"
        for message in (f"키 {self.KEY} 가 들어 있음", "C:\\Users\\홍길동\\Desktop\\비밀.txt 를 열 수 없음", "\\\\서버\\공유\\폴더\\파일 접근 거부", "D:/폴더/하위/파일.md 오류", "줄\n바꿈\r\n있는 글", "평범한 문장"):
            line = app_state.unexpected_line(KeyError, message)
            self.assertTrue(line.startswith(prefix), line)
            self.assertNotIn("\n", line)
            self.assertLessEqual(len(line), len(prefix) + 2 + 120)
            for piece in (self.KEY, self.KEY[:12], "홍길동", "비밀.txt", "서버", "공유", "D:/", "Traceback"):
                self.assertNotIn(piece, line)
        self.assertIn("가림", app_state.unexpected_line(KeyError, f"키 {self.KEY}"))
        self.assertIn("(경로)", app_state.unexpected_line(OSError, "C:\\Users\\a\\b.txt 를 열 수 없음"))
        self.assertTrue(app_state.unexpected_line(KeyError, "평범한 문장").endswith("평범한 문장"))

    def test_a_key_that_straddles_the_cut_is_masked_first(self):
        for lead in range(60, 125):
            line = app_state.unexpected_line(RuntimeError, "가" * lead + " " + self.KEY)
            self.assertEqual([piece for piece in {self.KEY[i:i + 6] for i in range(len(self.KEY) - 5)} if piece in line], [], lead)

    def test_reporting_writes_one_line_to_the_stream_and_never_raises(self):
        stream = io.StringIO()
        self.assertTrue(app_state.report_unexpected(KeyError, f"키 {self.KEY} C:\\Users\\a\\b.txt", stream))
        line = stream.getvalue()
        self.assertEqual(len(line.splitlines()), 1)
        self.assertIn("(KeyError)", line)
        for piece in (self.KEY, self.KEY[:12], "a\\b.txt"):
            self.assertNotIn(piece, line)
        with contextlib.redirect_stderr(io.StringIO()) as default_stream:                    # 흐름을 안 주면 표준 오류
            self.assertTrue(app_state.report_unexpected(ValueError, "기본 흐름"))
        self.assertIn("(ValueError): 기본 흐름", default_stream.getvalue())
        self.assertFalse(app_state.report_unexpected(ValueError, "x", object()))             # 쓸 수 없는 흐름 — 예외 없이 False

    def test_any_value_is_survivable(self):
        class Unprintable:
            def __str__(self):
                raise RuntimeError("출력 못 함")

        self.assertTrue(app_state.unexpected_line(RuntimeError, Unprintable()).endswith("(RuntimeError)"))
        self.assertIn("(Exception)", app_state.unexpected_line(None, "x"))
        self.assertIn("(Exception)", app_state.unexpected_line(object(), "x"))
        self.assertIn("(ValueError)", app_state.unexpected_line(ValueError, None))
        self.assertLess(len(app_state.unexpected_line(ValueError, "x" * 300_000)), 400)                # 가리기 상한(20만 자)을 넘는 글도 짧은 한 줄


class PackageBoundaryTest(unittest.TestCase):
    def test_ui_core_adapters_and_launcher_never_import_pyside6_at_module_level(self):
        files = list((UI_DIR / "core").glob("*.py")) + [UI_DIR / "adapters.py", UI_DIR / "launcher.py", UI_DIR / "__init__.py"]
        for path in files:
            for node in ast.walk(ast.parse(source_of(path))):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                for name in names:
                    self.assertFalse(name.split(".")[0] in ("PySide6", "shiboken6", "PyQt5", "PyQt6"), f"{path.name}: {name}")

    def test_the_qt_layer_only_depends_on_pyside6_and_the_standard_library(self):
        """PySide6 외 새 의존성 금지 — 서드파티는 PySide6(와 shiboken)뿐이다."""
        allowed_top = set(sys.stdlib_module_names) | {"PySide6", "chanceblog_desktop"} if hasattr(sys, "stdlib_module_names") else None
        if allowed_top is None:
            self.skipTest("표준 라이브러리 목록은 파이썬 3.10 부터")
        found = set()
        for path in SOURCES:
            for node in ast.walk(ast.parse(source_of(path))):
                if isinstance(node, ast.Import):
                    found |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])
        self.assertEqual(sorted(found - allowed_top), [])


if __name__ == "__main__":
    unittest.main()
