"""진짜 Qt 로 보는 사진 입력 관문 시험(앱 2차 감사 AS-S2 필수-1, 결정 D-680) — PySide6 가 없으면 통째로 건너뛴다(짝: PySide6 없이 도는 `test_ui_imagegate.py`).

감사가 직접 재현한 길: 이름이 `.jpg` 인 SVG 파일을 사진 정리 창에 넣기만 해도 읽기 도구의 `size()` 가 SVG 를 해석하면서 그 안의 `<image href>` 경로를 앱 프로세스가 열었다(경로가 네트워크 위치면 접속 시도).
이 파일은 세 입구(판정 `imagecheck.judge`·미리보기 `imagecheck.make_thumbnail`·글자 읽기 입력 `ocr_input.prepare`)에 **가짜가 아니라 진짜 위장 SVG** 를 넣고 읽기 도구의 호출 기록으로 본다:
  1) 표지가 없는 파일에는 읽기 도구가 **만들어지지도** 않는다(만들어지면 `size`·`read` 가 한 번이라도 불린 것과 같다고 본다).
  2) 표지가 있는 진짜 JPEG·PNG·WebP 에는 **형식을 못박고 자동 추측을 끈** 읽기 도구만 만들어진다(이름이 다른 형식이어도 파일 속 표지가 이긴다).
  3) 대조: 옛 방식(경로만 주고 만든 읽기 도구)은 같은 파일에서 바깥 파일의 화소를 그려 냈다 — 이 시험이 눈먼 시험이 아님을 보인다.
  4) 크기를 읽지 못한 잘린 사진(머리만 있는 JPEG·서명만 있는 PNG)은 통과하지 않는다(참고-1).
네트워크·윈도 전용 호출 없음 — 바깥 파일은 같은 임시 폴더의 PNG 한 장뿐이다(실제 UNC·이름 있는 파이프 재현은 감사 보고서의 탐침이 한다).
"""
import importlib.util
import os
import sys
import tempfile
import unittest
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
    from PySide6.QtGui import QColor, QImage, QImageReader
    from PySide6.QtWidgets import QApplication
    from chanceblog_desktop.errors import AppError
    from chanceblog_desktop.ui.core import imagerules
    from chanceblog_desktop.ui.qt import imagecheck, ocr_input

SVG_NS = "ht" + "tp://www.w3.org/2000/svg"
XLINK_NS = "ht" + "tp://www.w3.org/1999/xlink"
SENTINEL_COLOR = 0xFF3366CC


def svg_text(href):
    return f'<svg xmlns="{SVG_NS}" xmlns:xlink="{XLINK_NS}" width="64" height="64"><image xlink:href="{href}" width="64" height="64"/></svg>'


def recording(log):
    """`QImageReader` 의 진짜 하위 종류 — 만들 때 받은 것과 읽기 도구가 부른 일(`canRead`·`size`·`read`)을 `log` 에 적는다. 부른 쪽의 코드는 바뀌지 않고 이름만 이 클래스로 바뀐다."""

    class Recording(QImageReader):
        def __init__(self, *args):
            super().__init__(*args)
            log.append(("new", len(args), bytes(args[1]) if len(args) > 1 else b""))

        def canRead(self):
            log.append(("canRead", self.autoDetectImageFormat(), bytes(self.format())))
            return super().canRead()

        def size(self):
            log.append(("size",))
            return super().size()

        def read(self):
            log.append(("read",))
            return super().read()

    return Recording


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class GateBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["image-gate"])                  # 위젯 시험과 한 프로세스에서 돌아도 깨지지 않게 위젯용으로

    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="사진 관문 ")
        self.addCleanup(holder.cleanup)
        self.tmp = Path(os.path.realpath(holder.name))
        self.sentinel = self.tmp / "sentinel.png"
        blue = QImage(64, 64, QImage.Format_RGB32)
        blue.fill(SENTINEL_COLOR)
        self.assertTrue(blue.save(str(self.sentinel)))
        self.log = []
        self.reader_class = recording(self.log)

    def picture(self, width=40, height=30):
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor(120, 160, 220))
        return image

    def real_file(self, name, kind):
        """진짜 JPEG·PNG·WebP 파일(`kind` 형식, 이름은 마음대로)."""
        path = self.tmp / name
        self.assertTrue(self.picture().save(str(path), kind.upper() if kind != "jpeg" else "JPEG"), name)
        return str(path)

    def disguised(self, name, body=None):
        path = self.tmp / name
        path.write_text(body or svg_text("sentinel.png"), encoding="utf-8")
        return str(path)

    def patched(self):
        """세 입구가 쓰는 읽기 도구 이름을 기록용 종류로 바꾼다."""
        return mock.patch.multiple(imagecheck, QImageReader=self.reader_class), mock.patch.multiple(ocr_input, QImageReader=self.reader_class)

    def run_all_entrances(self, path):
        """판정·미리보기·글자 읽기 입력을 차례로 돌린다 → (판정, 미리보기, 글자 읽기 오류 코드)."""
        first, second = self.patched()
        with first, second:
            verdict = imagecheck.judge(path)
            thumbnail = imagecheck.make_thumbnail(path)
            try:
                ocr_input.prepare(path)
                code = None
            except AppError as error:
                code = error.code
        return verdict, thumbnail, code


class DisguisedFilesTest(GateBase):
    def test_a_disguised_svg_is_refused_at_every_entrance_and_no_reader_is_ever_made_for_it(self):
        bodies = {"같은 폴더의 그림": svg_text("sentinel.png"), "실제 있는 바깥 파일의 절대 경로": svg_text(self.sentinel.as_posix()), "없는 절대 경로": svg_text("C:/folder/sentinel.png"),
                  "네트워크 위치": svg_text("\\\\fake-host.invalid\\share\\a.png"), "이름 있는 파이프": svg_text("//./pipe/CANARY_pipe"), "xml 머리말": '<?xml version="1.0"?>\n' + svg_text("sentinel.png")}
        for label, body in bodies.items():
            for name in ("a.jpg", "a.jpeg", "a.png", "a.webp"):
                with self.subTest(label=label, name=name):
                    self.log.clear()
                    verdict, thumbnail, code = self.run_all_entrances(self.disguised(name, body))
                    self.assertEqual((verdict.kind, verdict.format), (imagerules.UNSUPPORTED, "svg"))
                    self.assertIsNone(thumbnail)
                    self.assertEqual(code, "OCR_FAILED")
                    self.assertEqual(self.log, [], "읽기 도구가 만들어지지도(경로를 받지도) 크기를 묻지도 읽지도 않았다")

    def test_other_disguises_are_refused_the_same_way(self):
        gif = table.GIF_1X1
        for label, data, kind in (("GIF", gif, imagerules.UNSUPPORTED), ("글자", "사진이 아니에요".encode("utf-8") * 20, imagerules.NOT_IMAGE), ("빈 파일", b"", imagerules.NOT_IMAGE),
                                  ("PDF", b"%PDF-1.7\n" + b"\x00" * 40, imagerules.UNSUPPORTED), ("TIFF", b"II*\x00" + b"\x08\x00\x00\x00" + b"\x00" * 30, imagerules.UNSUPPORTED),
                                  ("BMP", self.bmp_bytes(), imagerules.UNSUPPORTED)):
            with self.subTest(label=label):
                path = self.tmp / "photo.jpg"
                path.write_bytes(data)
                self.log.clear()
                verdict, thumbnail, code = self.run_all_entrances(str(path))
                self.assertEqual(verdict.kind, kind)
                self.assertIsNone(thumbnail)
                self.assertEqual(code, "OCR_FAILED")
                self.assertEqual(self.log, [])

    def bmp_bytes(self):
        path = self.tmp / "made.bmp"
        self.assertTrue(self.picture(8, 8).save(str(path), "BMP"))
        return path.read_bytes()

    @staticmethod
    def plain_center_pixel(path):
        """옛 방식 — 경로만 주고 읽기 도구를 만들어 한가운데 화소를 읽는다(함수가 끝나면 읽기 도구가 파일을 놓는다 — 윈도에서 임시 폴더가 지워지게)."""
        image = QImageReader(path).read()
        return None if image.isNull() else image.pixel(32, 32) & 0xFFFFFFFF

    def test_the_old_way_of_reading_drew_the_outside_file_which_is_why_this_gate_exists(self):
        """대조(눈먼 시험이 아님을 보인다): 경로만 주고 만든 읽기 도구는 위장 SVG 안의 `<image>` 가 가리킨 바깥 그림의 화소를 그려 낸다. Qt 가 나중에 막으면 이 대조는 건너뛴다."""
        path = self.disguised("old.jpg")
        if self.plain_center_pixel(path) != SENTINEL_COLOR:
            self.skipTest("이 Qt 는 SVG 안의 바깥 그림 참조를 이미 막고 있다 — 관문은 그래도 그대로 둔다")
        self.assertIsNone(imagecheck.make_thumbnail(path), "관문을 지나면 같은 파일이 그림으로 나오지 않는다")
        self.assertEqual(imagecheck.judge(path).kind, imagerules.UNSUPPORTED)

    def test_the_pointed_to_file_is_never_read_through_the_gate_even_when_it_is_a_real_photo(self):
        """바깥 파일이 진짜 사진이어도(`sentinel.png`) 위장 SVG 를 통해서는 한 번도 안 읽힌다 — 기록에 읽기 도구가 하나도 없고 미리보기도 없다."""
        path = self.disguised("trap.png")
        verdict, thumbnail, code = self.run_all_entrances(path)
        self.assertEqual((verdict.ok, thumbnail, code, self.log), (False, None, "OCR_FAILED", []))


class RealFilesTest(GateBase):
    def test_a_real_picture_gets_one_pinned_reader_whatever_its_name_says(self):
        for kind, name, shown in (("jpeg", "a.jpg", b"jpeg"), ("png", "a.png", b"png"), ("webp", "a.webp", b"webp"), ("png", "png_named.jpg", b"png"), ("jpeg", "jpeg_named.webp", b"jpeg"), ("webp", "webp_named.png", b"webp")):
            with self.subTest(name=name):
                path = self.real_file(name, kind)
                self.log.clear()
                first, second = self.patched()
                with first, second:
                    verdict = imagecheck.judge(path)
                    thumbnail = imagecheck.make_thumbnail(path)
                self.assertTrue(verdict.ok, name)
                self.assertEqual((verdict.format, verdict.width, verdict.height), (kind, 40, 30))
                self.assertIsNotNone(thumbnail)
                made = [entry for entry in self.log if entry[0] == "new"]
                self.assertEqual(len(made), 2, "판정 하나·미리보기 하나")
                for entry in made:
                    self.assertEqual(entry[1:], (2, shown), "경로와 함께 파일 속 표지가 말한 형식을 같이 주고 만든다")
                for entry in (item for item in self.log if item[0] == "canRead"):
                    self.assertEqual(entry[1:], (False, shown), "자동 형식 추측을 끈 읽기 도구다")

    def test_the_text_reading_input_makes_a_pinned_reader_too(self):
        for kind, name in (("jpeg", "ocr.jpg"), ("png", "ocr.png"), ("webp", "ocr.webp"), ("png", "ocr_named.jpg")):
            with self.subTest(name=name):
                path = self.real_file(name, kind)
                self.log.clear()
                with mock.patch.multiple(ocr_input, QImageReader=self.reader_class):
                    width, height, data = ocr_input.prepare(path)
                self.assertEqual((width, height, len(data)), (40, 30, 40 * 30 * 3))
                made = [entry for entry in self.log if entry[0] == "new"]
                self.assertEqual(made, [("new", 2, kind.encode("ascii"))], "글자 읽기 입력이 만든 읽기 도구는 하나이고 형식이 못박혀 있다")
                self.assertEqual([entry[1:] for entry in self.log if entry[0] == "canRead"], [])
                self.assertIn(("read",), self.log)

    def test_the_old_check_table_helper_still_works_and_cannot_be_used_to_open_a_disguised_file(self):
        text_file = self.tmp / "fake.png"
        text_file.write_text("사진이 아니에요", encoding="utf-8")
        self.assertFalse(imagecheck._reader(str(text_file)).canRead())
        gif = self.tmp / "fake.jpg"
        gif.write_bytes(table.GIF_1X1)
        reader = imagecheck._reader(str(gif))
        self.assertEqual((reader.canRead(), bytes(reader.format()), reader.size().isValid()), (False, b"", False))
        svg = self.disguised("table.png")
        self.assertEqual((imagecheck._reader(svg).canRead(), imagecheck._reader(svg).size().isValid()), (False, False))
        real = imagecheck._reader(self.real_file("real.png", "png"))
        self.assertEqual((real.canRead(), bytes(real.format()), imagecheck.shown_size(real)), (True, b"png", (40, 30)))

    def test_open_checked_gives_nothing_for_a_missing_file_or_a_folder(self):
        folder = self.tmp / "dir.jpg"
        folder.mkdir()
        for path in (str(folder), str(self.tmp / "none.png"), str(self.tmp / ("널 글자" + chr(0) + ".png"))):
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(imagecheck.open_checked(path), (None, ""))
                self.assertIsNone(imagecheck.make_thumbnail(path))


class TruncatedPictureTest(GateBase):
    def test_a_picture_whose_size_cannot_be_read_is_unreadable_not_ok(self):
        """AS-S2 참고-1: 머리만 있는 JPEG(12바이트)·서명만 있는 PNG(8바이트)는 크기가 -1x-1 인데 OK 로 통과했다."""
        for name, data in (("trunc_header.jpg", bytes.fromhex("ffd8ffe000104a46494600010100")[:12]), ("trunc_png_signature.png", b"\x89PNG\r\n\x1a\n"), ("trunc_webp.webp", b"RIFF\x24\x00\x00\x00WEBPVP8 ")):
            with self.subTest(name=name):
                path = self.tmp / name
                path.write_bytes(data)
                verdict = imagecheck.judge(str(path))
                self.assertEqual((verdict.kind, verdict.message), (imagerules.UNREADABLE, imagerules.T["img_local_unreadable"]))
                self.assertFalse(verdict.ok)

    def test_a_good_picture_of_one_pixel_still_passes(self):
        path = self.tmp / "tiny.png"
        self.assertTrue(self.picture(1, 1).save(str(path)))
        verdict = imagecheck.judge(str(path))
        self.assertEqual((verdict.ok, verdict.width, verdict.height), (True, 1, 1))


if __name__ == "__main__":
    unittest.main()
