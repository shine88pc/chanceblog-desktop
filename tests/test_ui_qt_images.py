"""내 사진(로컬 이미지) 형식별 로딩 시험 — `QImageReader.canRead()` 로 진짜 이미지인지 보고 JPG·JPEG·PNG·WebP 만 받는다(확장자만 믿지 않음). PySide6 가 없으면 건너뛴다.

지키는 것: 형식별 판정표(`scripts/ui_image_check.py` 의 사례와 같다) · 지원하지 않는 형식(GIF·BMP)·확장자만 바꾼 가짜·20MB 초과·긴 변 12,000px 초과(경고)·EXIF 회전(가로·세로가 바뀜) ·
**원본 파일은 읽기만 한다(해시·수정 시각 불변, 폴더에 새 파일 없음)** · 썸네일은 메모리에서 따로 만든다 · 이 PySide6 설치가 JPEG·PNG·WebP 를 읽을 수 있다(플러그인 파일 포함).
"""
import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    import ui_image_check as table
    from PySide6.QtGui import QGuiApplication
    from chanceblog_desktop.ui.core import imagerules
    from chanceblog_desktop.ui.qt import imagecheck


def fingerprint(path):
    stat = Path(path).stat()
    if stat.st_size > 5_000_000:
        return stat.st_size, stat.st_mtime_ns
    return hashlib.sha256(Path(path).read_bytes()).hexdigest(), stat.st_mtime_ns


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ImageLoadingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication(["images"])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cases = table.build_cases(self.tmp.name)

    def case(self, label_start):
        return next(case for case in self.cases if case[0].startswith(label_start))

    def test_every_format_case_gets_the_expected_verdict(self):
        self.assertGreaterEqual(len(self.cases), 14)
        for label, path, expected, _note in self.cases:
            self.assertEqual(imagecheck.judge(path).kind, expected, label)

    def test_the_four_supported_formats_load_and_report_their_real_format(self):
        names = {"JPG": "jpeg", "JPEG": "jpeg", "PNG": "png", "WebP": "webp"}
        for label, expected_format in names.items():
            _label, path, _kind, _note = self.case(label)
            verdict = imagecheck.judge(path)
            self.assertTrue(verdict.ok, label)
            self.assertEqual((verdict.format, verdict.width, verdict.height), (expected_format, 64, 48), label)
            self.assertIsNotNone(imagecheck.make_thumbnail(path), label)

    def test_unsupported_formats_get_the_easy_message_and_nothing_technical(self):
        for label in ("GIF", "BMP"):
            verdict = imagecheck.judge(self.case(label)[1])
            self.assertEqual(verdict.kind, imagerules.UNSUPPORTED)
            self.assertEqual(verdict.message, "지원하지 않는 파일이에요. JPG·PNG·WebP 사진만 쓸 수 있어요.")
        for label in ("가짜(글자", "가짜(GIF"):
            verdict = imagecheck.judge(self.case(label)[1])
            self.assertFalse(verdict.ok)
            self.assertNotRegex(verdict.message, r"QImage|canRead|Error|Exception")

    def test_a_good_name_does_not_make_a_text_file_an_image_but_a_real_png_may_have_a_jpg_name(self):
        _l, text_path, _k, _n = self.case("가짜(글자")
        reader_ok = imagecheck._reader(text_path).canRead()
        self.assertFalse(reader_ok)
        self.assertEqual(imagecheck.judge(text_path).kind, imagerules.NOT_IMAGE)
        _l, png_path, _k, _n = self.case("PNG 를 .jpg")
        self.assertTrue(imagecheck.judge(png_path).ok)                                    # 진짜 형식이 허용 형식이면 이름이 달라도 쓴다
        self.assertEqual(imagecheck.judge(png_path).format, "png")

    def test_a_file_over_twenty_megabytes_is_refused_without_reading_it(self):
        _l, path, _k, _n = self.case("20MB")
        self.assertGreater(os.path.getsize(path), 20 * 1024 * 1024)
        self.assertEqual(imagecheck.judge(path).kind, imagerules.TOO_BIG)
        self.assertEqual(imagecheck.judge(path, max_bytes=os.path.getsize(path)).kind, imagerules.NOT_IMAGE)        # 크기 한도를 넘기면 내용을 보고(가짜라서) 거절한다

    def test_a_very_long_side_is_a_warning_only(self):
        for label, size in (("긴 변 12,001", (12001, 8)), ("긴 변 13,000", (8, 13000))):
            verdict = imagecheck.judge(self.case(label)[1])
            self.assertTrue(verdict.ok, label)
            self.assertEqual((verdict.width, verdict.height), size)
            self.assertIn("12,000px", verdict.warning)

    def test_exif_rotation_is_applied_to_the_size_and_the_thumbnail(self):
        plain = imagecheck.judge(self.case("EXIF 회전 없음")[1])
        rotated = imagecheck.judge(self.case("EXIF 회전 6")[1])
        self.assertEqual((plain.width, plain.height), (40, 20))
        self.assertEqual((rotated.width, rotated.height), (20, 40))                      # 90° 회전 → 가로·세로가 바뀐다
        thumb = imagecheck.make_thumbnail(self.case("EXIF 회전 6")[1])
        self.assertEqual((thumb.width(), thumb.height()), (20, 40))
        self.assertEqual((imagecheck.make_thumbnail(self.case("EXIF 회전 없음")[1]).width()), 40)

    def test_originals_are_never_modified_and_no_file_appears_next_to_them(self):
        before = {path: fingerprint(path) for _l, path, _k, _n in self.cases}
        listing = sorted(os.listdir(self.tmp.name))
        for _label, path, _kind, _note in self.cases:
            imagecheck.judge(path)
            imagecheck.make_thumbnail(path)
        self.assertEqual({path: fingerprint(path) for path in before}, before)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), listing)

    def test_the_thumbnail_is_a_separate_small_image_in_memory(self):
        from PySide6.QtGui import QColor, QImage
        big = Path(self.tmp.name) / "big.png"
        image = QImage(3000, 2000, QImage.Format_RGB32)
        image.fill(QColor(10, 120, 200))
        self.assertTrue(image.save(str(big)))
        before = fingerprint(big)
        thumb = imagecheck.make_thumbnail(str(big))
        self.assertEqual(imagerules.THUMB_MAX_SIDE, 640)                                  # 손으로 적은 값 — 구현 상수끼리 비교하면 상수가 바뀌어도 통과한다
        self.assertEqual(max(thumb.width(), thumb.height()), 640)
        self.assertAlmostEqual(thumb.width() / thumb.height(), 1.5, places=1)
        self.assertEqual(fingerprint(big), before)
        self.assertIsNone(imagecheck.make_thumbnail(self.case("가짜(글자")[1]))
        self.assertIsNone(imagecheck.make_thumbnail(str(Path(self.tmp.name) / "none.png")))

    def test_this_pyside6_install_reads_jpeg_png_and_webp_and_ships_their_plugins(self):
        formats = imagecheck.supported_formats()
        for needed in ("jpeg", "png", "webp"):
            self.assertIn(needed, formats)
        self.assertEqual(imagecheck.missing_required_formats(), [])
        files = " ".join(table.plugin_files()).lower()
        self.assertIn("qjpeg", files)                                                    # JPEG·WebP 읽기는 플러그인(PNG 는 Qt 본체) — 설치 파일에 같이 들어가야 한다
        self.assertIn("qwebp", files)


if __name__ == "__main__":
    unittest.main()
