"""확장자만 사진인 파일을 읽기 도구가 **형식을 확인하기 전에** 해석하지 않는다(앱 2차 감사 AS-S2 필수-1, 결정 D-680) — PySide6 없이 돈다(CI 와 같은 조건).

배경: 이름이 `.jpg` 인 SVG 파일은 읽기 도구의 `size()` 한 번만으로 통째로 해석되고, 그 안의 `<image href>` 경로를 앱 프로세스가 직접 열었다(경로가 네트워크 위치면 접속이 일어난다).
형식 검사는 그 **뒤에** 거절했지만 이미 열린 뒤였다. 고친 순서: ① 파일 앞 12바이트(JPEG·PNG·WebP 표지)를 직접 본다 → ② 표지가 맞을 때만 형식을 못박은 읽기 도구를 만든다 →
③ 읽기 도구가 말한 형식이 지원 형식일 때만 `size()` 를 부른다. 이 파일은 그 순서를 **가짜 읽기 객체의 호출 기록**으로 못박는다(진짜 Qt 로 보는 짝은 `test_ui_qt_imagegate.py`).

지키는 것:
  1) 표지 읽기(`sniff_format`)는 JPEG·PNG·WebP 세 가지뿐이고, 불완전하거나 앞이 어긋난 표지·다른 형식·이상한 입력은 모두 빈 글이다. 지원 형식 집합은 글자 그대로 못박는다(`svg` 만 더해도 시험이 빨개진다).
  2) 형식을 알아보는 말(`other_format`)은 안내 문구를 가르는 데만 쓴다 — 읽기 도구를 만들지 않는다.
  3) 읽기 도구가 지원하지 않는 형식을 말하면 **`size()` 를 부르지 않는다**(호출 기록).
  4) 표지가 없는 파일(SVG·GIF·BMP·TIFF·PDF·글자·빈 파일)에는 읽기 도구를 **만들지도 않는다**.
  5) 크기를 읽지 못한 잘린 사진은 통과하지 않고 '읽지 못했어요' 로 안내한다(AS-S2 참고-1).
  6) 소스 규칙: `QImageReader(...)` 를 직접 만드는 곳은 없다(형식을 못박는 한 곳을 지난다).
"""
import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from chanceblog_desktop.ui.core import imagerules as R  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"
SVG_NS = "ht" + "tp://www.w3.org/2000/svg"                    # 소스에 주소 글자가 그대로 보이지 않게 이어 붙인다
XLINK_NS = "ht" + "tp://www.w3.org/1999/xlink"

JPEG = bytes.fromhex("ffd8ffe000104a46494600010100") + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + bytes.fromhex("0000000d49484452") + b"\x00" * 24
WEBP = b"RIFF" + (36).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 24
GIF = b"GIF89a" + b"\x01\x00\x01\x00\x80\x00\x00" + b"\x00" * 24
GIF87 = b"GIF87a" + b"\x01\x00\x01\x00\x80\x00\x00" + b"\x00" * 24
BMP = b"BM" + (66).to_bytes(4, "little") + b"\x00\x00\x00\x00" + (54).to_bytes(4, "little") + b"\x00" * 40
TIFF_LE = b"II*\x00" + (8).to_bytes(4, "little") + b"\x00" * 24
TIFF_BE = b"MM\x00*" + (8).to_bytes(4, "big") + b"\x00" * 24
ICO = bytes.fromhex("00000100") + b"\x01\x00\x10\x10" + b"\x00" * 24
PDF = b"%PDF-1.7\n" + b"\x00" * 24
GZIP = bytes.fromhex("1f8b0800") + b"\x00" * 24


def svg(href, prolog=""):
    return (prolog + f'<svg xmlns="{SVG_NS}" xmlns:xlink="{XLINK_NS}" width="64" height="64"><image xlink:href="{href}" width="64" height="64"/></svg>').encode("utf-8")


SVG_FILES = {
    "상대 경로": svg("sentinel.png"),
    "절대 경로": svg("C:/folder/sentinel.png"),
    "네트워크 위치": svg("\\\\fake-host.invalid\\share\\a.png"),
    "이름 있는 파이프": svg("//./pipe/CANARY_pipe"),
    "xml 머리말": svg("sentinel.png", prolog='<?xml version="1.0" encoding="UTF-8"?>\n'),
    "BOM 과 빈 줄": b"\xef\xbb\xbf\n\n  " + svg("sentinel.png"),
    "주석 먼저": svg("sentinel.png", prolog="<!-- 설명 -->"),
    "대문자 태그": svg("sentinel.png").replace(b"<svg", b"<SVG").replace(b"</svg>", b"</SVG>"),
}


class FakeReader:
    """`QImageReader` 처럼 보이는 가짜 — 불린 것을 순서대로 `log` 에 적는다. 읽기 도구가 말하는 형식과 읽을 수 있는지를 정한다."""

    def __init__(self, log, readable=True, shown="png"):
        self.log, self.readable, self.shown = log, readable, shown

    def canRead(self):
        self.log.append("canRead")
        return self.readable

    def format(self):
        self.log.append("format")
        return self.shown.encode("ascii") if isinstance(self.shown, str) else self.shown


class Rig:
    """`probe_file` 에 끼우는 가짜 읽기 도구 만들기·크기 재기 — 부른 기록을 모은다."""

    def __init__(self, readable=True, size=(64, 48), shown=None):
        self.log, self.opened, self.readable, self.size, self.shown = [], [], readable, size, shown

    def open_reader(self, path, kind):
        self.opened.append((os.path.basename(str(path)), kind))
        self.log.append("open")
        return FakeReader(self.log, self.readable, self.shown or kind)

    def measure(self, reader):
        self.log.append("size")
        return self.size

    def probe(self, path):
        return R.probe_file(path, self.open_reader, self.measure)


class SniffTest(unittest.TestCase):
    def test_the_three_real_signatures_are_found(self):
        self.assertEqual(R.sniff_format(JPEG), "jpeg")
        self.assertEqual(R.sniff_format(bytes.fromhex("ffd8ffe1") + b"\x00" * 16), "jpeg")            # EXIF 가 붙은 JPEG
        self.assertEqual(R.sniff_format(bytes.fromhex("ffd8ffdb")), "jpeg")                              # 바로 표(DQT)가 오는 JPEG — 네 바이트만 있어도 표지는 있다
        self.assertEqual(R.sniff_format(PNG), "png")
        self.assertEqual(R.sniff_format(b"\x89PNG\r\n\x1a\n"), "png")                                    # 서명 여덟 바이트뿐인 잘린 PNG 도 표지는 맞다(크기를 못 읽는 것은 아래에서 따로 거른다)
        self.assertEqual(R.sniff_format(WEBP), "webp")
        self.assertEqual(R.sniff_format(bytearray(WEBP)), "webp")

    def test_a_signature_must_be_complete_and_at_the_very_start(self):
        for label, head in (("JPEG 앞 두 바이트만", b"\xff\xd8"), ("JPEG 표지가 한 바이트 뒤에", b"\x00" + JPEG), ("JPEG 인데 세 번째가 FF 가 아님", b"\xff\xd8\x00\xe0" + b"\x00" * 16),
                            ("PNG 서명 일곱 바이트", PNG[:7]), ("PNG 서명 끝 바이트가 다름", PNG[:7] + b"\x0b" + PNG[8:]), ("PNG 서명 앞에 글자", b"x" + PNG),
                            ("WebP 인데 RIFF 가 아님", b"RIFX" + WEBP[4:]), ("WebP 인데 WEBP 가 아니라 WAVE", b"RIFF" + WEBP[4:8] + b"WAVE" + b"\x00" * 16), ("WebP 표지가 열한 바이트에서 끊김", WEBP[:11]),
                            ("RIFF 만", b"RIFF"), ("빈 바이트", b""), ("0 으로 가득", b"\x00" * 64)):
            with self.subTest(label=label):
                self.assertEqual(R.sniff_format(head), "")

    def test_every_other_format_and_odd_input_gives_nothing(self):
        for label, head in (("GIF", GIF), ("BMP", BMP), ("TIFF", TIFF_LE), ("ICO", ICO), ("PDF", PDF), ("gzip", GZIP), *((f"SVG {name}", body) for name, body in SVG_FILES.items()), ("글자", "사진이 아니에요".encode("utf-8") * 8)):
            with self.subTest(label=label):
                self.assertEqual(R.sniff_format(head), "")
        for odd in (None, "ffd8ff", 12, ["ffd8ff"], object()):
            with self.subTest(odd=repr(odd)[:12]):
                self.assertEqual(R.sniff_format(odd), "")

    def test_only_the_first_twelve_bytes_count(self):
        self.assertEqual(R.sniff_format(JPEG[:12]), "jpeg")
        self.assertEqual(R.sniff_format(PNG[:12]), "png")
        self.assertEqual(R.sniff_format(WEBP[:12]), "webp")
        self.assertEqual(R.sniff_format(b"\x00" * 12 + JPEG), "", "표지는 맨 앞에 있어야 한다 — 뒤쪽에 숨은 표지는 보지 않는다")

    def test_the_supported_names_are_written_down_literally_and_cover_the_signatures(self):
        """감사 변이 M11b: `SUPPORTED_FORMATS` 에 `svg` 만 더해도 시험 177개가 통과했다 — 집합을 손으로 적은 글자와 견주고, 표지 세 가지가 모두 그 안에 있음을 본다."""
        self.assertEqual(R.SUPPORTED_FORMATS, frozenset({"jpeg", "jpg", "png", "webp"}))
        self.assertEqual(R.SUPPORTED_EXTENSIONS, (".jpg", ".jpeg", ".png", ".webp"))
        self.assertEqual(R.MAGIC_FORMATS, ("jpeg", "png", "webp"))
        self.assertTrue(set(R.MAGIC_FORMATS) <= R.SUPPORTED_FORMATS)
        self.assertEqual({R.sniff_format(head) for head in (JPEG, PNG, WEBP)}, set(R.MAGIC_FORMATS))
        self.assertEqual(R.HEAD_BYTES, 64)
        self.assertGreaterEqual(R.HEAD_BYTES, 12)


class OtherFormatTest(unittest.TestCase):
    def test_the_common_unsupported_formats_are_named_so_the_message_can_be_chosen(self):
        for label, head, name in (("GIF89a", GIF, "gif"), ("GIF87a", GIF87, "gif"), ("BMP", BMP, "bmp"), ("TIFF 리틀엔디언", TIFF_LE, "tiff"), ("TIFF 빅엔디언", TIFF_BE, "tiff"), ("ICO", ICO, "ico"),
                                  ("CUR", bytes.fromhex("00000200") + b"\x00" * 16, "cur"), ("ICNS", b"icns" + b"\x00" * 16, "icns"), ("PDF", PDF, "pdf"), ("gzip(SVGZ 같은 것)", GZIP, "gzip")):
            with self.subTest(label=label):
                self.assertEqual(R.other_format(head), name)

    def test_svg_in_every_shape_is_named_svg(self):
        for label, body in SVG_FILES.items():
            with self.subTest(label=label):
                self.assertEqual(R.other_format(body[:R.HEAD_BYTES]), "svg")
        self.assertEqual(R.other_format(b"<?xml version='1.0'?>"), "svg", "xml 머리말도 SVG 로 본다(Qt 도 같다)")

    def test_the_supported_signatures_and_plain_text_are_nothing_special(self):
        for label, head in (("JPEG", JPEG), ("PNG", PNG), ("WebP", WEBP), ("글자", "사진이 아니에요".encode("utf-8") * 8), ("빈 바이트", b""), ("0 으로 가득", b"\x00" * 64), ("BM 으로 시작하는 글자", b"BMW is a car maker. Not a bitmap."),
                            ("짧은 BM", b"BM")):
            with self.subTest(label=label):
                self.assertEqual(R.other_format(head), "")
        for odd in (None, "GIF89a", 5):
            self.assertEqual(R.other_format(odd), "")


class ProbeReaderTest(unittest.TestCase):
    """읽기 도구가 말한 형식을 먼저 보고, 지원하는 형식일 때만 크기를 잰다 — 순서가 안전이다."""

    def run_probe(self, readable=True, shown="png", size=(64, 48)):
        rig = Rig(readable=readable, size=size)
        reader = FakeReader(rig.log, readable, shown)
        return R.probe_reader(reader, rig.measure), rig.log

    def test_a_reader_that_cannot_read_is_never_asked_for_a_format_or_a_size(self):
        seen, log = self.run_probe(readable=False)
        self.assertEqual((seen, log), (R.Probe(False), ["canRead"]))

    def test_an_unsupported_format_is_refused_before_the_size_is_asked_for(self):
        """필수-1 의 핵심: 크기를 묻는 일(`size()`)이 SVG 해석기를 돌려 경로를 연다 — 지원하지 않는 형식이면 부르지 않는다."""
        for shown in ("svg", "svgz", "gif", "bmp", "tiff", "tif", "ico", "cur", "icns", "tga", "wbmp", "xpm", "xbm", "ppm", "pgm", "pbm", "pdf", "", "SVG"):
            with self.subTest(shown=shown):
                seen, log = self.run_probe(shown=shown)
                self.assertEqual(log, ["canRead", "format"], "크기를 묻지 않았다")
                self.assertEqual((seen.can_read, seen.format, seen.width, seen.height), (True, shown.lower(), 0, 0))

    def test_a_supported_format_is_measured_exactly_once_after_it_was_named(self):
        for shown in ("jpeg", "jpg", "png", "webp", "PNG"):
            with self.subTest(shown=shown):
                seen, log = self.run_probe(shown=shown)
                self.assertEqual(log, ["canRead", "format", "size"])
                self.assertEqual((seen.can_read, seen.format, seen.width, seen.height), (True, shown.lower(), 64, 48))

    def test_a_format_name_that_is_not_text_is_read_safely(self):
        seen, log = self.run_probe(shown=b"svg")
        self.assertEqual((seen.format, log), ("svg", ["canRead", "format"]))
        seen, log = self.run_probe(shown=bytearray(b"jpeg"))
        self.assertEqual((seen.format, log[-1]), ("jpeg", "size"))

    def test_a_picture_whose_size_cannot_be_read_is_not_let_through(self):
        """AS-S2 참고-1: 머리만 있는 잘린 JPEG·PNG 는 크기가 -1x-1 인데 통과했다 — 이제 읽기 도구가 예외를 내고 판정은 '읽지 못했어요' 가 된다."""
        for size in ((-1, -1), (0, 0), (64, 0), (0, 48), (-1, 48), (64, -1)):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    self.run_probe(size=size)
        rig = Rig(size=(-1, -1))
        path = write_file(self, "truncated.png", PNG[:8])
        verdict = R.judge(path, rig.probe)
        self.assertEqual((verdict.kind, verdict.message), (R.UNREADABLE, R.T["img_local_unreadable"]))
        self.assertTrue(R.judge(write_file(self, "fine.png", PNG), Rig(size=(1, 1)).probe).ok, "1x1 은 쓸 수 있다")


def write_file(case, name, data, folder=None):
    """시험 한 건의 임시 폴더에 파일 하나를 쓴다 → 경로(글)."""
    if folder is None:
        holder = getattr(case, "_gate_tmp", None)
        if holder is None:
            holder = case._gate_tmp = tempfile.TemporaryDirectory()
            case.addCleanup(holder.cleanup)
        folder = holder.name
    path = Path(folder) / name
    path.write_bytes(data)
    return str(path)


class ProbeFileTest(unittest.TestCase):
    """실제 파일로 — 표지가 없는 파일에는 읽기 도구를 만들지도 않고, 있는 파일에만 형식을 못박아 만든다."""

    def test_a_disguised_svg_is_refused_and_no_reader_is_ever_made(self):
        for label, body in SVG_FILES.items():
            for name in ("a.jpg", "a.jpeg", "a.png", "a.webp", "A.JPG", "한글 이름.png"):
                with self.subTest(label=label, name=name):
                    rig = Rig()
                    verdict = R.judge(write_file(self, name, body), rig.probe)
                    self.assertEqual((verdict.kind, verdict.format), (R.UNSUPPORTED, "svg"))
                    self.assertEqual(rig.log, [], "읽기 도구를 만들지도 크기를 묻지도 않았다")
                    self.assertEqual(verdict.message, R.T["img_local_unsupported"])

    def test_other_formats_named_like_a_photo_are_refused_by_their_real_format_without_a_reader(self):
        for label, body, name in (("GIF", GIF, "gif"), ("BMP", BMP, "bmp"), ("TIFF", TIFF_LE, "tiff"), ("ICO", ICO, "ico"), ("PDF", PDF, "pdf"), ("gzip", GZIP, "gzip")):
            with self.subTest(label=label):
                rig = Rig()
                verdict = R.judge(write_file(self, "photo.jpg", body), rig.probe)
                self.assertEqual((verdict.kind, verdict.format), (R.UNSUPPORTED, name))
                self.assertEqual(rig.log, [])

    def test_text_and_empty_files_are_not_images_and_get_no_reader(self):
        for label, body in (("글자", "사진이 아니에요".encode("utf-8") * 20), ("빈 파일", b""), ("0 으로 가득", b"\x00" * 200), ("JPEG 표지가 잘린 두 바이트", b"\xff\xd8"), ("RIFF 만", b"RIFF" + b"\x00" * 30)):
            with self.subTest(label=label):
                rig = Rig()
                verdict = R.judge(write_file(self, "memo.png", body), rig.probe)
                self.assertEqual(verdict.kind, R.NOT_IMAGE)
                self.assertEqual(rig.log, [])

    def test_a_real_signature_gets_one_pinned_reader_and_the_format_comes_from_the_file_not_the_name(self):
        for label, body, name, kind in (("JPEG", JPEG, "a.jpg", "jpeg"), ("PNG", PNG, "a.png", "png"), ("WebP", WEBP, "a.webp", "webp"), ("PNG 를 .jpg 로", PNG, "named.jpg", "png"), ("WebP 를 .png 로", WEBP, "named.png", "webp"),
                                        ("JPEG 를 .webp 로", JPEG, "named.webp", "jpeg")):
            with self.subTest(label=label):
                rig = Rig()
                verdict = R.judge(write_file(self, name, body), rig.probe)
                self.assertTrue(verdict.ok, label)
                self.assertEqual((verdict.format, verdict.width, verdict.height), (kind, 64, 48))
                self.assertEqual(rig.opened, [(name, kind)], "표지가 말한 형식으로 한 번만 만들었다")
                self.assertEqual(rig.log, ["open", "canRead", "format", "size"])

    def test_a_reader_that_says_it_cannot_read_a_signed_file_gives_not_an_image(self):
        rig = Rig(readable=False)
        verdict = R.judge(write_file(self, "bad.png", PNG), rig.probe)
        self.assertEqual(verdict.kind, R.NOT_IMAGE)
        self.assertEqual(rig.log, ["open", "canRead"])

    def test_a_reader_that_names_another_format_than_the_signature_is_not_trusted_for_the_size(self):
        """표지는 PNG 인데 읽기 도구가 SVG 라고 하면(일어나서는 안 되는 일) 크기를 묻지 않고 지원하지 않는 형식으로 거절한다."""
        rig = Rig(shown="svg")
        verdict = R.judge(write_file(self, "odd.png", PNG), rig.probe)
        self.assertEqual((verdict.kind, verdict.format), (R.UNSUPPORTED, "svg"))
        self.assertEqual(rig.log, ["open", "canRead", "format"])

    def test_a_folder_or_a_missing_file_gives_an_easy_message_not_a_crash(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        folder = Path(holder.name) / "dir.jpg"
        folder.mkdir()
        rig = Rig()
        self.assertEqual(R.judge(str(folder), rig.probe).kind, R.UNREADABLE)
        self.assertEqual(R.judge(str(Path(holder.name) / "none.jpg"), rig.probe).kind, R.MISSING)
        self.assertEqual(rig.log, [])

    def test_reading_the_head_touches_only_the_first_bytes_and_never_writes(self):
        path = write_file(self, "big.jpg", JPEG + b"\x01" * 200_000)
        before = (Path(path).read_bytes(), os.stat(path).st_mtime_ns)
        head = R.read_head(path)
        self.assertEqual(len(head), R.HEAD_BYTES)
        self.assertEqual(head, JPEG[:14] + b"\x00" * 32 + b"\x01" * (R.HEAD_BYTES - 46))
        self.assertEqual(R.read_head(path, 4), JPEG[:4])
        self.assertEqual((Path(path).read_bytes(), os.stat(path).st_mtime_ns), before, "읽기만 한다")
        modes = []
        real_path_open = Path.open

        def watching(self, mode="r", *args, **kwargs):
            modes.append(mode)
            return real_path_open(self, mode, *args, **kwargs)

        def forbidden(*args, **kwargs):
            raise AssertionError("내장 open 을 부르면 안 된다 — 화면 층 소스 규칙 시험이 막는다(Path.open 을 쓴다)")

        # `Path.open` 자체를 관찰한다 — 3.11 이상은 호출 때마다 `io.open` 을 찾지만 3.10 은 클래스 속성에 붙잡아 둔 원래 함수를 불러 `io.open` 을 가짜로 바꿔서는 안 걸린다(독립 확인 필수-1)
        with mock.patch.object(Path, "open", watching), mock.patch("builtins.open", forbidden):
            R.read_head(path)
        self.assertEqual(modes, ["rb"])

    def test_the_head_is_read_before_any_reader_is_made(self):
        """순서를 못박는다 — 파일을 읽을 수 없으면 읽기 도구를 만들기 전에 멈춘다."""
        rig = Rig()
        with mock.patch.object(R, "read_head", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                R.probe_file("whatever.jpg", rig.open_reader, rig.measure)
        self.assertEqual(rig.log, [])


class _CallFinder(ast.NodeVisitor):
    """파일 안의 호출을 (이름, 가장 안쪽 함수 이름, 인자 수) 로 모은다 — 함수 밖(모듈 바닥)이면 함수 이름은 `<모듈>`."""

    def __init__(self):
        self.stack, self.calls = [], []

    def _function(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def visit_Call(self, node):
        name = getattr(node.func, "id", getattr(node.func, "attr", ""))
        self.calls.append((name, self.stack[-1] if self.stack else "<모듈>", len(node.args) + len(node.keywords), node))
        self.generic_visit(node)


def calls_of(tree):
    finder = _CallFinder()
    finder.visit(tree)
    return finder.calls


def function_named(tree, name):
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


class SourceRulesTest(unittest.TestCase):
    """소스 규칙(PySide6 없이 돈다) — 사진 파일을 여는 읽기 도구는 형식을 못박는 한 곳을 지나야 한다."""

    def test_no_code_makes_an_image_reader_straight_from_a_path(self):
        """`QImageReader(경로)` 를 직접 만드는 곳이 없다 — 있다면 형식을 자동으로 추측해 SVG 해석기가 골라질 수 있다. 허용은 `_reader` 의 빈 읽기 도구(인자 없음) 하나뿐이다."""
        allowed = {("ui/qt/imagecheck.py", "_reader", 0)}
        seen = set()
        for path in sorted(SRC.rglob("*.py")):
            for name, function, count, _node in calls_of(ast.parse(path.read_text(encoding="utf-8"))):
                if name in ("QImageReader", "QMovie", "QImageIOHandler"):
                    seen.add((path.relative_to(SRC).as_posix(), function, count))
        self.assertEqual(seen, allowed, "읽기 도구를 직접 만드는 곳: " + repr(sorted(seen - allowed)))

    def test_no_picture_or_icon_is_loaded_from_a_path_string(self):
        """`QImage(경로)`·`QPixmap(경로)`·`QIcon(경로)`·`QPixmap.load(경로)` 도 같은 해석기를 쓴다 — 이 앱에는 그런 호출이 없어야 한다(크기만 주는 `QImage(너비, 높이, 형식)`·`QPixmap(크기)` 는 괜찮다)."""
        for path in sorted(SRC.rglob("*.py")):
            for name, function, _count, node in calls_of(ast.parse(path.read_text(encoding="utf-8"))):
                where = f"{path.relative_to(SRC).as_posix()}:{node.lineno}({function})"
                if name in ("QImage", "QPixmap", "QIcon") and node.args:
                    first = node.args[0]
                    textual = isinstance(first, ast.JoinedStr) or (isinstance(first, ast.Constant) and isinstance(first.value, str)) \
                        or (isinstance(first, ast.Call) and getattr(first.func, "id", "") == "str") or (isinstance(first, ast.Name) and first.id in ("path", "file", "filename", "name"))
                    self.assertFalse(textual, f"{where} — 경로 글로 그림을 연다")
                if name in ("fromData", "loadFromData", "load") and isinstance(node.func, ast.Attribute):
                    owner = ast.unparse(node.func.value)
                    self.assertFalse(owner.split(".")[-1] in ("QImage", "QPixmap", "QIcon", "image", "pixmap", "icon"), f"{where} — 그림을 파일이나 바이트에서 불러온다")

    def test_the_photo_reading_ways_all_go_through_the_signature_check(self):
        """`probe`(판정)·`make_thumbnail`(미리보기)·`_reader`(점검표)·글자 읽기 입력(`ocr_input.prepare`)이 모두 표지 확인 한 곳(`open_checked`·`probe_file`)을 지난다."""
        check = ast.parse((SRC / "ui" / "qt" / "imagecheck.py").read_text(encoding="utf-8"))
        ocr = ast.parse((SRC / "ui" / "qt" / "ocr_input.py").read_text(encoding="utf-8"))

        def called(tree, function, wanted):
            return wanted in {name for name, owner, _count, _node in calls_of(tree) if owner == function}

        self.assertTrue(called(check, "probe", "probe_file"))
        self.assertTrue(called(check, "make_thumbnail", "open_checked"))
        self.assertTrue(called(check, "_reader", "open_checked"))
        self.assertTrue(called(check, "open_checked", "sniff_format"))
        self.assertTrue(called(check, "open_checked", "pinned_reader"))
        self.assertTrue(called(ocr, "prepare", "open_checked"))
        self.assertFalse(called(ocr, "prepare", "QImageReader"), "글자 읽기 입력은 읽기 도구를 직접 만들지 않는다")
        source = ast.unparse(function_named(check, "pinned_reader"))
        for needle in ("setAutoDetectImageFormat(False)", "setAutoTransform(True)", "kind.encode('ascii')"):
            self.assertIn(needle, source)

    def test_the_pure_rules_file_still_knows_no_screen_tool(self):
        tree = ast.parse((SRC / "ui" / "core" / "imagerules.py").read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
        self.assertFalse(imported & {"PySide6", "shiboken6", "subprocess", "socket", "urllib", "http", "ctypes", "logging", "tempfile", "shutil"}, imported)
        banned = {name for name, _function, _count, _node in calls_of(tree)} & {"print", "exec", "eval", "write", "write_text", "write_bytes", "unlink", "rename", "replace", "remove"}
        self.assertFalse(banned, banned)
        opens = [(function, ast.unparse(node.args[0]) if isinstance(node.func, ast.Attribute) and node.args else ((ast.unparse(node.args[1]) if len(node.args) > 1 else "")))
                 for name, function, _count, node in calls_of(tree) if name == "open"]
        self.assertEqual(opens, [("read_head", "'rb'")], "파일을 여는 곳은 앞부분을 읽는 한 곳뿐이고 읽기 전용이다")
        self.assertFalse([node.lineno for name, _function, _count, node in calls_of(tree) if name == "open" and isinstance(node.func, ast.Name)], "내장 open 은 화면 층 소스 규칙 시험이 막는다 — Path.open 을 쓴다")


    def test_no_screen_layer_code_opens_a_file_for_writing_by_any_spelling(self):
        """화면 층 소스 규칙 시험(`test_ui_keys_adapter` 외)은 내장 `open` 호출만 막는다 — `Path.open`·`io.open`·`os.open` 으로 쓰기 모드를 여는 것은 그 시험이 못 잡는다. 여기서 철자를 가리지 않고 막는다:
        `ui/core`·`ui/qt` 안에서 글자 모드(`wax+` 가 든)로 여는 호출이 없고, `os.open` 이 없고, 글자 모드를 주는 `.open(...)` 은 `imagerules.read_head` 의 읽기 전용 'rb' 한 곳뿐이다."""
        reads = []
        for folder in ("core", "qt"):
            for path in sorted((SRC / "ui" / folder).glob("*.py")):
                relative = path.relative_to(SRC).as_posix()
                for name, function, _count, node in calls_of(ast.parse(path.read_text(encoding="utf-8"))):
                    if name != "open":
                        continue
                    owner = ast.unparse(node.func.value) if isinstance(node.func, ast.Attribute) else ""
                    self.assertNotEqual(owner, "os", f"{relative}:{node.lineno} os.open")
                    self.assertNotIsInstance(node.func, ast.Name, f"{relative}:{node.lineno} 내장 open")
                    modes = [arg.value for arg in node.args[:2] if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
                    modes += [keyword.value.value for keyword in node.keywords if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant)]
                    for mode in modes:
                        self.assertFalse(set(mode) & set("wax+"), f"{relative}:{node.lineno} 쓰기 모드 {mode!r}")
                        reads.append((relative, function, mode))
        self.assertEqual(reads, [("ui/core/imagerules.py", "read_head", "rb")], "글자 모드로 여는 곳은 사진 앞부분을 읽는 한 곳뿐이다")


if __name__ == "__main__":
    unittest.main()
