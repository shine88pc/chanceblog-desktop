"""글자 읽기에 보낼 사진 한 장을 메모리에서 읽고 줄이는 `ui/qt/ocr_input.py`(결정 D-513, 설계서 3-4·2-7, 시험 계획 T-H)의 PySide6 시험 — 합성 이미지로 픽셀 값까지 본다. **PySide6 가 없으면 통째로 건너뛴다.**

지키는 것:
  1) 4000x3000 JPG·PNG·WebP 가 긴 변 960(크게 읽기 1600)으로 줄고, RGB 순서·줄마다의 패딩 제거·길이(`너비 x 높이 x 3`)가 맞다. 작은 사진은 늘리지 않는다.
  2) 휴대폰 회전(EXIF) — 세로 사진이 눕지 않고 픽셀 방향이 맞다(여섯·여덟·세 방향). 투명 PNG 는 흰 바탕에 올라가 글자가 검게 사라지지 않는다.
  3) 큰 사진 — 긴 변 12,000px 넘는 JPG·WebP 는 줄여서 읽고, PNG 는 가로x세로 6천만 화소 경계에서 읽기 **전에** 거절한다(`OCR_TOO_BIG`). 읽다 실패하면 `OCR_FAILED` 이고 오류에 경로·파일 이름이 없다.
  4) 한글 폴더·파일 이름의 사진이 읽힌다. 사진 아닌 파일·지원하지 않는 형식(HEIC)은 읽히지 않고, 내려받지 않은 클라우드 사진·HEIC 는 기존 규칙이 사진 정리에 넣기 전에 거절한다.
  5) 원본은 읽기만 한다 — 파일 바이트·폴더 목록이 그대로이고 디스크에 아무것도 쓰지 않는다.
"""
import hashlib
import importlib.util
import os
import struct
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    import ui_image_check as table
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from chanceblog_desktop.errors import AppError
    from chanceblog_desktop.ui import photo_adapter
    from chanceblog_desktop.ui.core import photo_rules as rules
    from chanceblog_desktop.ui.core import photo_view as pv
    from chanceblog_desktop.ui.core.text import T
    from chanceblog_desktop.ui.qt import ocr_input


def png_header_only(width, height):
    """헤더(IHDR)와 빈 그림 조각(IDAT)·끝(IEND)뿐인 PNG — 읽기 도구는 크기를 알지만 그림은 풀 수 없다(헤더만 있고 끝이 없으면 Qt 가 크기도 못 읽는다). 읽기 전에 거절하는지 보는 데 쓴다 — 큰 그림을 정말 만들지 않는다."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    return bytes.fromhex("89504e470d0a1a0a") + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", bytes.fromhex("789c030000000001")) + chunk(b"IEND", b"")


def pixel(data, width, x, y):
    start = (y * width + x) * 3
    return tuple(data[start:start + 3])


def near(actual, wanted, slack=40):
    return all(abs(a - b) <= slack for a, b in zip(actual, wanted))


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class InputBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QApplication(["ocr-input"])                # 앱 개체를 새로 만들 때는 위젯용(QApplication)으로 — 순서상 이 모듈이 먼저 돌아도 뒤의 위젯 시험이 setUpClass 에서 깨지지 않는다(독립 검증 Q QP-7)

    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="사진 폴더 가나다 ")
        self.addCleanup(holder.cleanup)
        self.tmp = Path(os.path.realpath(holder.name))

    def halves(self, width, height):
        """왼쪽 절반 빨강·오른쪽 절반 파랑인 그림 — 색 순서(RGB)와 회전 방향을 픽셀로 볼 수 있다."""
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor(255, 0, 0))
        painter = QPainter(image)
        painter.fillRect(width // 2, 0, width - width // 2, height, QColor(0, 0, 255))
        painter.end()
        return image

    def save(self, image, name, quality=-1):
        path = self.tmp / name
        self.assertTrue(image.save(str(path), None, quality), name)
        return str(path)


class SizeAndColorTest(InputBase):
    def test_a_4000_by_3000_photo_comes_out_at_960_by_720_in_rgb_order_for_every_format(self):
        image = self.halves(4000, 3000)
        for ext in ("jpg", "png", "webp"):
            with self.subTest(ext=ext):
                path = self.save(image, f"메뉴판.{ext}")
                width, height, data = ocr_input.prepare(path, "960")
                self.assertEqual((width, height, len(data)), (960, 720, 960 * 720 * 3))
                self.assertIsInstance(data, bytes)
                self.assertTrue(near(pixel(data, width, 20, 20), (255, 0, 0)), pixel(data, width, 20, 20))
                self.assertTrue(near(pixel(data, width, width - 20, 20), (0, 0, 255)), pixel(data, width, width - 20, 20))
                self.assertTrue(near(pixel(data, width, 20, height - 20), (255, 0, 0)))

    def test_reading_bigger_gives_1600_and_a_small_photo_is_never_enlarged(self):
        path = self.save(self.halves(4000, 3000), "큰.jpg")
        self.assertEqual(ocr_input.prepare(path, "1600")[:2], (1600, 1200))
        self.assertEqual(ocr_input.prepare(path, "모르는 이름")[:2], (960, 720), "모르는 이름은 기본 크기다")
        small = self.save(self.halves(100, 50), "작은.png")
        self.assertEqual(ocr_input.prepare(small, "1600")[:2], (100, 50))
        exact = self.save(self.halves(960, 540), "딱.png")
        self.assertEqual(ocr_input.prepare(exact, "960")[:2], (960, 540))
        self.assertEqual(ocr_input.long_side("960"), 960)
        self.assertEqual(ocr_input.long_side("1600"), 1600)

    def test_the_padding_of_each_qt_row_is_taken_out_so_the_length_is_exactly_width_times_height_times_three(self):
        for width, height in ((101, 33), (3, 5), (7, 7), (960, 2)):
            image = QImage(width, height, QImage.Format_RGB32)
            image.fill(QColor(10, 20, 30))
            image.setPixelColor(width - 1, height - 1, QColor(200, 100, 50))
            path = self.save(image, f"{width}x{height}.png")
            got_width, got_height, data = ocr_input.prepare(path)
            self.assertEqual((got_width, got_height, len(data)), (width, height, width * height * 3))
            self.assertEqual(pixel(data, width, 0, 0), (10, 20, 30))
            self.assertEqual(pixel(data, width, width - 1, height - 1), (200, 100, 50), "마지막 줄 마지막 픽셀이 밀리지 않았다")
            self.assertEqual(pixel(data, width, width - 1, 0), (10, 20, 30), "줄 끝의 패딩 바이트가 다음 줄로 새지 않았다")

    def test_a_long_side_over_twelve_thousand_is_read_scaled_down_not_refused(self):
        for ext in ("jpg", "webp"):
            with self.subTest(ext=ext):
                path = self.save(self.halves(12_001, 300), f"긴.{ext}")
                width, height, data = ocr_input.prepare(path)
                self.assertEqual((width, len(data) == width * height * 3, height <= 25), (960, True, True))
                self.assertTrue(near(pixel(data, width, 10, 1), (255, 0, 0)) and near(pixel(data, width, width - 10, 1), (0, 0, 255)))

    def test_jpeg_and_webp_are_reduced_while_they_are_read_and_png_and_small_pictures_are_not(self):
        """독립 검증 Q QP-9(MQ9) — JPG·WebP 는 읽는 도중 줄인다(`setScaledSize` — 큰 사진을 통째로 읽지 않아 메모리를 아낀다). PNG 는 그런 길이 없어 부르지 않고(읽은 뒤에 줄인다) 작은 사진은 줄이지 않는다."""
        calls = []

        class Recording(ocr_input.QImageReader):
            def setScaledSize(self, size):
                calls.append((size.width(), size.height()))
                return super().setScaledSize(size)

        image = self.halves(4000, 3000)
        with mock.patch.object(ocr_input, "QImageReader", Recording):
            for ext in ("jpg", "webp"):
                calls.clear()
                width, height, _data = ocr_input.prepare(self.save(image, f"큰.{ext}"), "960")
                self.assertEqual((calls, (width, height)), ([(960, 720)], (960, 720)), ext)
            calls.clear()
            self.assertEqual(ocr_input.prepare(self.save(image, "큰.png"), "960")[:2], (960, 720))
            self.assertEqual(calls, [], "PNG 는 읽은 뒤에 줄인다")
            ocr_input.prepare(self.save(self.halves(500, 300), "작은.jpg"), "960")
            self.assertEqual(calls, [], "작은 사진은 줄이지 않는다")

    def test_a_large_jpeg_is_reduced_while_it_is_read_and_it_is_quick(self):
        path = self.save(self.halves(4000, 3000), "빠른.jpg")
        started = time.perf_counter()
        ocr_input.prepare(path)
        self.assertLess(time.perf_counter() - started, 5, "4000x3000 한 장을 읽고 줄이는 데 몇 초 걸리지 않는다")


class RotationAndAlphaTest(InputBase):
    def jpeg_with_orientation(self, name, orientation, width=40, height=20):
        raw = table._jpeg_bytes(self.halves(width, height))
        path = self.tmp / name
        path.write_bytes(table.exif_orientation(raw, orientation) if orientation else raw)
        return str(path)

    def test_a_phone_portrait_photo_stays_standing(self):
        raw = table._jpeg_bytes(self.halves(4000, 3000))
        path = self.tmp / "세로 사진.jpg"
        path.write_bytes(table.exif_orientation(raw, 6))
        width, height, data = ocr_input.prepare(str(path))
        self.assertEqual((width, height), (720, 960), "눕지 않고 세로로 선다")
        self.assertEqual(len(data), 720 * 960 * 3)

    def test_the_pixels_are_turned_the_right_way_for_every_turning_direction(self):
        """왼쪽 빨강·오른쪽 파랑으로 저장한 그림 — 방향 6(시계 방향 90°)이면 빨강이 위, 8 이면 빨강이 아래, 3 이면 좌우가 뒤바뀐다."""
        cases = {0: ((40, 20), (2, 10), (37, 10)), 6: ((20, 40), (10, 2), (10, 37)), 8: ((20, 40), (10, 37), (10, 2)), 3: ((40, 20), (37, 10), (2, 10))}
        for orientation, (size, red_at, blue_at) in cases.items():
            with self.subTest(orientation=orientation):
                width, height, data = ocr_input.prepare(self.jpeg_with_orientation(f"o{orientation}.jpg", orientation))
                self.assertEqual((width, height), size)
                self.assertTrue(near(pixel(data, width, *red_at), (255, 0, 0), 70), (pixel(data, width, *red_at), "빨강이 있어야 할 자리"))
                self.assertTrue(near(pixel(data, width, *blue_at), (0, 0, 255), 70), (pixel(data, width, *blue_at), "파랑이 있어야 할 자리"))

    def test_a_transparent_png_is_put_on_white_so_dark_text_does_not_vanish(self):
        image = QImage(200, 100, QImage.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        painter.fillRect(20, 20, 30, 30, QColor(0, 0, 0, 255))                              # 검은 글자 조각
        painter.fillRect(100, 20, 30, 30, QColor(255, 0, 0, 128))                            # 반투명 빨강
        painter.end()
        width, height, data = ocr_input.prepare(self.save(image, "투명.png"))
        self.assertEqual((width, height), (200, 100))
        self.assertEqual(pixel(data, width, 5, 5), (255, 255, 255), "투명한 곳은 흰색이다(검게 변하지 않는다)")
        self.assertEqual(pixel(data, width, 30, 30), (0, 0, 0), "검은 글자는 그대로 검다")
        mixed = pixel(data, width, 110, 30)
        self.assertTrue(mixed[0] >= 250 and 90 <= mixed[1] <= 160 and 90 <= mixed[2] <= 160, mixed)

    def test_an_opaque_picture_is_not_touched_by_the_white_background_step(self):
        image = QImage(50, 50, QImage.Format_RGB32)
        image.fill(QColor(30, 60, 90))
        data = ocr_input.prepare(self.save(image, "불투명.png"))[2]
        self.assertEqual(pixel(data, 50, 25, 25), (30, 60, 90))


class LimitsAndFailuresTest(InputBase):
    def test_a_png_over_sixty_million_pixels_is_refused_before_it_is_read_and_the_edge_is_the_same_as_the_preview_rule(self):
        over = self.tmp / "육천만넘음.png"
        over.write_bytes(png_header_only(7746, 7746))                                       # 60,000,516 화소 — 한도(60,000,000) 초과
        edge = self.tmp / "육천만안쪽.png"
        edge.write_bytes(png_header_only(7745, 7745))                                       # 59,985,025 화소 — 한도 안쪽(헤더뿐이라 읽기는 실패한다)
        self.assertTrue(rules.preview_blocked("png", 7746, 7746))
        self.assertFalse(rules.preview_blocked("png", 7745, 7745), "미리보기를 막는 기존 규칙과 같은 경계다")
        reads = []

        class CountingReader(ocr_input.QImageReader):
            def read(self):
                reads.append(1)
                return super().read()

        with mock.patch.object(ocr_input, "QImageReader", CountingReader):
            with self.assertRaises(AppError) as caught:
                ocr_input.prepare(str(over))
            self.assertEqual((caught.exception.code, reads), ("OCR_TOO_BIG", []), "읽기 전에 거절했다")
            with self.assertRaises(AppError) as caught:
                ocr_input.prepare(str(edge))
            self.assertEqual((caught.exception.code, len(reads)), ("OCR_FAILED", 1), "한도 안쪽은 읽어 보고, 풀지 못하면 일반 실패다")

    def test_an_absurdly_large_jpeg_header_is_refused_before_it_is_decoded(self):
        raw = bytearray(table._jpeg_bytes(self.halves(8, 8)))
        sof = raw.index(b"\xff\xc0")
        raw[sof + 5:sof + 9] = struct.pack(">HH", 20000, 20000)                              # 4억 화소(3억 한도 초과) — 헤더만 고쳤다
        path = self.tmp / "엄청.jpg"
        path.write_bytes(bytes(raw))
        with self.assertRaises(AppError) as caught:
            ocr_input.prepare(str(path))
        self.assertEqual(caught.exception.code, "OCR_TOO_BIG")
        self.assertEqual(ocr_input.READ_PIXEL_LIMIT, 300_000_000)

    def test_a_file_that_is_not_a_picture_or_not_a_supported_format_fails_without_naming_itself(self):
        for name, data in (("메뉴판.jpg", "사진이 아니에요".encode("utf-8") * 30), ("사진.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64), ("빈 파일.png", b"")):
            with self.subTest(name=name):
                path = self.tmp / name
                path.write_bytes(data)
                with self.assertRaises(AppError) as caught:
                    ocr_input.prepare(str(path))
                error = caught.exception
                self.assertEqual(error.code, "OCR_FAILED")
                shown = f"{error} {error.rendered().message} {error.rendered().action} {error.slots} {error.detail} {error.log_line()}"
                for fragment in (name, "사진 폴더", str(self.tmp), os.sep + "사진"):
                    self.assertNotIn(fragment, shown)

    def test_the_name_and_the_real_format_are_checked_again_when_reading_so_a_renamed_picture_of_another_format_is_never_read(self):
        """독립 검증 S SP-4 — 사진을 넣을 때 거른 것(확장자·크기·실제 형식 JPG·PNG·WebP)을 읽을 때도 다시 본다. 이름만 .jpg·.png 인 BMP·GIF 와 이름이 .bmp 인 진짜 그림은 읽지 않고 일반 실패로 알린다."""
        bmp = self.tmp / "원본.bmp"
        self.assertTrue(self.halves(40, 20).save(str(bmp), "BMP"))
        gif = self.tmp / "움직이는 그림.png"
        gif.write_bytes(table.GIF_1X1)
        renamed = self.tmp / "이름만 사진.jpg"
        renamed.write_bytes(bmp.read_bytes())
        reads = []

        class CountingReader(ocr_input.QImageReader):
            def read(self):
                reads.append(1)
                return super().read()

        with mock.patch.object(ocr_input, "QImageReader", CountingReader):
            for path in (bmp, gif, renamed):
                with self.subTest(suffix=path.suffix, size=path.stat().st_size):
                    with self.assertRaises(AppError) as caught:
                        ocr_input.prepare(str(path))
                    self.assertEqual(caught.exception.code, "OCR_FAILED")
            self.assertEqual(reads, [], "읽기 전에 거절했다")
            good = self.save(self.halves(40, 20), "같은 그림.png")
            self.assertEqual((ocr_input.prepare(good)[:2], len(reads)), ((40, 20), 1), "같은 그림도 지원하는 이름·형식이면 읽는다")

    def test_a_missing_file_fails_the_same_way(self):
        with self.assertRaises(AppError) as caught:
            ocr_input.prepare(str(self.tmp / "없는 사진.jpg"))
        self.assertEqual(caught.exception.code, "OCR_FAILED")

    def test_a_korean_folder_and_file_name_are_read_and_the_name_is_nowhere_in_the_result(self):
        path = self.save(self.halves(300, 200), "한글 사진 이름.png")
        self.assertIn("사진 폴더 가나다", path)
        width, height, data = ocr_input.prepare(path)
        self.assertEqual((width, height, len(data)), (300, 200, 300 * 200 * 3))
        self.assertNotIn("가나다".encode("utf-8"), data)

    def test_heic_and_not_downloaded_cloud_photos_are_refused_by_the_existing_rules_before_the_reader_could_see_them(self):
        heic = self.tmp / "아이폰 사진.heic"
        heic.write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64)
        board = pv.PhotoBoard(photo_adapter.ServicePhotoProvider())
        self.assertEqual(board.add_paths([str(heic)]), (0, 1))
        self.assertTrue(board.rejected[0].reason.startswith(T["pho_file_unsupported"]), board.rejected[0].reason)
        cloud = str(self.tmp / "클라우드.jpg")
        fake = pv.PhotoBoard(pv.FakePhotoProvider(states={cloud: "cloud"}))
        self.assertEqual(fake.add_paths([cloud]), (0, 1))
        self.assertEqual(fake.rejected[0].reason, T["pho_file_cloud"])
        self.assertEqual(fake.count, 0)


class NothingIsWrittenTest(InputBase):
    def snapshot(self):
        return {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in sorted(self.tmp.iterdir()) if item.is_file()}

    def test_the_original_photo_and_its_folder_are_exactly_as_before_and_nothing_is_written(self):
        paths = [self.save(self.halves(800, 600), "하나.jpg"), self.save(self.halves(800, 600), "둘.png"), self.save(self.halves(800, 600), "셋.webp")]
        before = self.snapshot()
        stats = [os.stat(path).st_mtime_ns for path in paths]
        written = []
        real_open = open

        def watching(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                written.append(str(file))
            return real_open(file, mode, *args, **kwargs)

        with mock.patch("builtins.open", watching):
            for path in paths:
                ocr_input.prepare(path, "960")
                ocr_input.prepare(path, "1600")
        self.assertEqual((self.snapshot(), [os.stat(path).st_mtime_ns for path in paths], written), (before, stats, []))

    def test_the_module_has_no_file_writing_network_or_process_calls_and_never_repeats_the_path(self):
        import ast
        source = (ROOT / "src" / "chanceblog_desktop" / "ui" / "qt" / "ocr_input.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0] or "." * node.level)
        self.assertFalse(imported & {"os", "pathlib", "subprocess", "socket", "urllib", "http", "shutil", "tempfile", "json", "logging", "traceback", "ctypes", "sys"}, imported)
        names = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "") for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertFalse(names & {"open", "print", "write", "save", "unlink", "mkdir", "rename", "copy", "copyfile", "move", "exec", "eval"}, names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                self.assertEqual([ast.unparse(arg) for arg in node.exc.args][1:], [], "오류에 경로·파일 이름을 담지 않는다(코드뿐)")


if __name__ == "__main__":
    unittest.main()
