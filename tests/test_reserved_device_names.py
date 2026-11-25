"""윈도 장치 이름(예약 이름) 표 시험 — AS-S2 권고-8 의 M10 틈(결정 D-694).

틈(감사 변이 M10): 사진 경로의 예약 이름 목록(`content/photo_manifest.py::_RESERVED`)에서 `PRN`·`AUX`·`CONOUT$` 를 지워도 시험 156개가 통과했다 — 시험이 `CON`·`NUL`·`COM1`·`LPT9`·`CONIN$` 다섯 이름만 봤다.
윈도는 `CON`·`PRN`·`AUX`·`NUL`·`CONIN$`·`CONOUT$`·`COM1`–`COM9`·`LPT1`–`LPT9`(위첨자 `COM¹²³`·`LPT¹²³` 포함)를 확장자가 붙어도 파일이 아닌 장치로 연다 — 사진 경로·읽을 글 경로(`service/own_posts.py`)가 이 이름을 거절하는 것이 안전 장치이고,
한 이름만 빠져도 그 이름의 '사진' 이 장치 열기로 이어진다(예: `CON` 은 콘솔을 읽다 멈춘다).

지키는 것:
  1) 두 목록(사진 경로·읽을 글 경로)이 정해진 서른 개와 **정확히 같다**(집합 비교 + 크기 못박기) — 하나라도 빼거나 더하면 빨개진다. 쓰는 곳이 둘이라 둘 다 같은 표를 쓴다는 것도 함께 못박는다.
  2) 표의 모든 이름이 두 길에서 실제로 거절된다 — 확장자(`.jpg`·`.png`·`.webp` / `.txt`·`.md`)를 붙인 것·소문자·이름 뒤 공백·확장자 뒤에 또 점(`NUL.tar.jpg`)까지, 모든 운영체제에서 같은 결과다(모양 검사라 운영체제를 묻지 않는다).
  3) 장치 이름처럼 보이기만 하는 평범한 이름(`console`·`com0`·`lpt10`·`comm`·`icon`)은 거절하지 않는다 — 표를 넓혀 평범한 사진을 막는 변경도 잡는다.
  4) 폴더 이름용 표(`publish/pages.py::_RESERVED` — `CONIN$`·`CONOUT$` 와 위첨자가 없는 윈도 폴더 이름 규칙)도 정해진 스물두 개로 못박는다.
네트워크·파일 접근 없이 돈다(경로 글만 본다).
"""
import os
import sys
import unittest
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import pages  # noqa: E402
from chanceblog_desktop.service import own_posts as op  # noqa: E402

BASIC = ("CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$")
NUMBERED = tuple(f"{name}{digit}" for name in ("COM", "LPT") for digit in "123456789\u00b9\u00b2\u00b3")      # COM¹²³·LPT¹²³ 는 윈도가 장치로 읽는 위첨자 번호
EXPECTED = frozenset(BASIC + NUMBERED)
# `service/own_posts.py::_shape` 는 운영체제의 `Path` 로 절대 경로를 따진다 — 윈도 경로 글(`C:\\Notes\\…`)은 리눅스에서 절대 경로가 아니라서 우분투 칸에서 예약 이름 사유가 아닌 '경로 모양' 사유가 나온다.
# 그래서 글 경로 시험은 그 운영체제의 절대 경로 모양을 쓴다(사진 쪽은 `posix=False` 로 윈도 규칙을 고정한다).
NOTES = "C:\\Notes\\" if os.name == "nt" else "/notes/"
FOLDER_EXPECTED = frozenset(("CON", "PRN", "AUX", "NUL") + tuple(f"{name}{digit}" for name in ("COM", "LPT") for digit in "123456789"))
ORDINARY = ("console", "com0", "lpt10", "comm", "icon", "aux2", "nulls", "prn_a", "concat", "com", "lpt")
Post = namedtuple("Post", "path text")
KO_TEXT = (ROOT / "tests" / "fixtures" / "chance_post_ko.md").read_text(encoding="utf-8")


def variants(name, suffixes):
    """같은 장치 이름의 여러 모양 — 대문자·소문자·이름 뒤 공백·확장자 뒤의 또 다른 점."""
    for suffix in suffixes:
        yield f"{name}{suffix}"
        yield f"{name.lower()}{suffix}"
        yield f"{name} {suffix}"
        yield f"{name}.tar{suffix}"


class TheTablesAreExactlyTheApprovedOnesTest(unittest.TestCase):
    def test_the_expected_table_itself_has_thirty_names(self):
        self.assertEqual(len(EXPECTED), 30)
        self.assertEqual(len(BASIC), 6)
        self.assertEqual(len(NUMBERED), 24)

    def test_the_photo_path_list_and_the_text_path_list_are_exactly_the_approved_thirty(self):
        for label, table in (("사진 경로(content/photo_manifest.py)", pm._RESERVED), ("읽을 글 경로(service/own_posts.py)", op._RESERVED)):
            with self.subTest(table=label):
                self.assertEqual(table, EXPECTED)
                self.assertEqual(len(table), 30, "표에서 이름이 빠졌거나 낯선 이름이 끼었다")
                self.assertEqual(sorted(EXPECTED - table), [], "표에서 빠진 이름")
                self.assertEqual(sorted(table - EXPECTED), [], "표에 더해진 이름")

    def test_the_two_lists_are_the_same_table_so_one_cannot_drift_from_the_other(self):
        self.assertEqual(pm._RESERVED, op._RESERVED)

    def test_the_folder_name_list_is_exactly_the_approved_twenty_two(self):
        self.assertEqual(pages._RESERVED, FOLDER_EXPECTED)
        self.assertEqual(len(pages._RESERVED), 22)


class EveryNameIsRefusedTest(unittest.TestCase):
    def test_every_reserved_name_is_refused_as_a_photo_whatever_its_shape(self):
        refused = 0
        for name in sorted(EXPECTED):
            for file_name in variants(name, (".jpg", ".png", ".webp")):
                with self.subTest(photo=file_name):
                    self.assertEqual(pm.path_problem("C:\\Pictures\\" + file_name, posix=False), pm._P_RESERVED)
                    self.assertEqual(pm.path_problem("C:/x/y/" + file_name, posix=False), pm._P_RESERVED)
                    refused += 1
        self.assertEqual(refused, 30 * 12, "표의 이름마다 열두 모양을 모두 돌렸다")

    def test_every_reserved_name_is_refused_as_a_text_file_whatever_its_shape(self):
        refused = 0
        for name in sorted(EXPECTED):
            for file_name in variants(name, (".txt", ".md")):
                with self.subTest(text=file_name):
                    pure, reason = op._shape(NOTES + file_name)
                    self.assertIsNone(pure)
                    self.assertEqual(reason, op._R_RESERVED)
                    refused += 1
        self.assertEqual(refused, 30 * 8)

    def test_the_post_folder_check_refuses_every_name_of_its_table_and_still_accepts_ordinary_folders(self):
        for name in sorted(FOLDER_EXPECTED):
            for folder in (name, name.lower(), name + ".txt"):
                with self.subTest(folder=folder):
                    with self.assertRaises(AppError) as caught:
                        pages.check_post(Post(f"_posts/{folder}/2026-10-29-KR-101652.md", KO_TEXT))
                    self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        for folder in ("console", "com0", "lpt10", "컨"):
            with self.subTest(ordinary=folder):
                pages.check_post(Post(f"_posts/{folder}/2026-10-29-KR-101652.md", KO_TEXT))

    def test_names_that_only_look_like_device_names_are_ordinary_photos_and_texts(self):
        for name in ORDINARY:
            with self.subTest(name=name):
                self.assertIsNone(pm.path_problem(f"C:\\Pictures\\{name}.jpg", posix=False))
                pure, reason = op._shape(f"{NOTES}{name}.txt")
                self.assertIsNone(reason)
                self.assertIsNotNone(pure)


if __name__ == "__main__":
    unittest.main()
