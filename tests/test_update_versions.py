"""`update/versions.py` 시험(UPDATE 설계서 5절, v1update U-1) — 버전 비교 규칙.

지키는 것:
  1) 읽는 모양: `pkgcommon.VERSION_PATTERN` 의 부분집합이다 — 이 모듈이 읽는 글은 모두 그 모양이고(무작위 글로 확인), 전각·아라비아 숫자·앞자리 0·빈 토막·너무 긴 글·글이 아닌 값은 읽지 않는다.
  2) 순서: 숫자 셋은 숫자로(`1.10.0` > `1.9.0`, 글자 비교가 아니다), 정식은 같은 숫자의 사전판보다 높고, 사전판은 SemVer 2.0 규칙(`rc.2` < `rc.10`, 숫자 토막 < 글자 토막, 토막이 많은 쪽이 높음), 빌드 표시는 무시한다.
  3) `service/backup_flow.py` 의 `_version_key` 와 같은 순서를 낸다 — 정식·한 자리 숫자 사전판의 모든 쌍에서(그쪽이 글자로 견주는 두 자리 이상 사전판 숫자만 다르고 이 모듈이 옳다).
  4) 읽을 수 없는 글을 견주면 ValueError(틀린 값을 조용히 견주지 않는다). 읽는 함수는 어떤 입력에도 예외를 내지 않는다.
네트워크·실제 시크릿 없이 돈다.
"""
import itertools
import random
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packaging"))

import pkgcommon  # noqa: E402

from chanceblog_desktop.service import backup_flow  # noqa: E402
from chanceblog_desktop.ui.core import version as ui_version  # noqa: E402
from chanceblog_desktop.update import versions  # noqa: E402


def sign_of(left, right):
    return versions.compare(left, right)


class ParseTest(unittest.TestCase):
    GOOD = ("0.0.0", "1.0.0", "10.20.30", "1.0.0-rc.1", "1.0.0-rc.10", "0.1.0-preview.1", "1.0.0+3", "1.0.0-rc.1+build.5", "1.0.0-alpha", "1.0.0-alpha-1", "1.0.0-0", "1.0.0-0.3.7",
            "1.0.0-x.7.z.92", "2.0.0-rc.1", "1.2.3-" + "a" * 31, "999999999.999999999.999999999")
    BAD = ("", "1", "1.0", "1.0.0.0", "01.0.0", "1.00.0", "1.0.00", "1.0.0-", "1.0.0-rc.", "1.0.0-.rc", "1.0.0-rc..1", "1.0.0-rc.01", "1.0.0+", "1.0.0 ", " 1.0.0", "1.0.0\n", "v1.0.0", "1.0.0-rc.1\n",
           "1.0.0-rc_1", "1.0.0-rc.1+", "1.0.0+b+c", "1.0.0--", "-1.0.0", "1.-1.0", "a.b.c", "1.0.0-" + "a" * 32, "1,0,0", "1.0.0-é", "1.0.0-rc.1-é")

    def test_good_texts_are_read(self):
        for text in self.GOOD:
            with self.subTest(text=text):
                found = versions.parse_version(text)
                self.assertIsNotNone(found, text)
                self.assertEqual(found.text, text)
                self.assertTrue(versions.is_valid(text))

    def test_bad_texts_are_not_read_and_never_raise(self):
        for text in self.BAD + (None, 1, 1.5, b"1.0.0", ["1.0.0"], ("1", "0", "0"), object(), True, "٣.٠.٠", "１.０.０", "1.0.0\x00", "1.0.0" + "0" * 100):
            with self.subTest(text=repr(text)[:40]):
                self.assertIsNone(versions.parse_version(text))
                self.assertFalse(versions.is_valid(text))

    def test_unicode_digits_are_not_digits(self):
        for text in ("١.٠.٠", "1.٠.0", "1.0.٠", "１.0.0", "1.0.0-rc.１"):
            self.assertIsNone(versions.parse_version(text), text)

    def test_the_fields_are_split_the_semver_way(self):
        found = versions.parse_version("1.2.3-rc.4+build.5")
        self.assertEqual((found.major, found.minor, found.patch, found.pre), (1, 2, 3, ("rc", "4")))
        self.assertTrue(found.is_prerelease)
        self.assertFalse(versions.parse_version("1.2.3+build.5").is_prerelease)

    def test_everything_this_module_reads_is_in_the_package_and_ui_shapes(self):
        """부분집합 — 무작위 글을 만들어 읽히는 것은 모두 `pkgcommon.VERSION_PATTERN` 과 화면의 `_NUMBER` 에 통째로 맞는다(반대는 아니다: 그쪽이 더 넓다)."""
        rng = random.Random(404)
        alphabet = "0123456789.-+aAzZ_ é٣"
        shapes = ("{n}.{n}.{n}", "{n}.{n}.{n}-{s}", "{n}.{n}.{n}+{s}", "{n}.{n}.{n}-{s}+{s}", "{n}.{n}.{n}{r}")
        read = 0
        for _ in range(6000):
            def piece(size):
                return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, size)))
            text = rng.choice(shapes).format(n=rng.choice(("0", "1", "7", "10", "01", "123")), s=piece(34), r=piece(4))
            found = versions.parse_version(text)
            if found is not None:
                read += 1
                self.assertIsNotNone(re.fullmatch(pkgcommon.VERSION_PATTERN, text), text)
                self.assertIsNotNone(ui_version._NUMBER.fullmatch(text), text)
        self.assertGreater(read, 100, "읽힌 것이 충분했다(빈 실험이 아니다)")

    def test_the_shape_is_the_package_shape_with_ascii_digits(self):
        self.assertEqual(versions._SHAPE.pattern.replace("[0-9]", r"\d"), pkgcommon.VERSION_PATTERN)


class OrderTest(unittest.TestCase):
    ASCENDING = ("0.0.0", "0.1.0-preview.1", "0.1.0-preview.2", "0.1.0", "0.9.0-rc.1", "0.9.0-rc.2", "0.9.0-rc.10", "0.9.0", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
                 "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.0.10", "1.1.0", "1.9.0", "1.10.0", "2.0.0", "10.0.0")

    def test_the_semver_example_order_is_total_and_strict(self):
        for (low_index, low), (high_index, high) in itertools.product(enumerate(self.ASCENDING), repeat=2):
            with self.subTest(low=low, high=high):
                expected = (low_index > high_index) - (low_index < high_index)
                self.assertEqual(sign_of(low, high), expected)
                self.assertEqual(versions.is_newer(low, high), low_index > high_index)

    def test_numbers_are_numbers_not_text(self):
        self.assertEqual(sign_of("1.10.0", "1.9.0"), 1)
        self.assertEqual(sign_of("1.0.10", "1.0.9"), 1)
        self.assertEqual(sign_of("10.0.0", "9.0.0"), 1)
        self.assertEqual(sign_of("1.0.0-rc.10", "1.0.0-rc.2"), 1)

    def test_a_release_is_higher_than_its_own_prerelease_and_a_prerelease_is_lower_than_the_next_release(self):
        self.assertEqual(sign_of("1.0.0", "1.0.0-rc.1"), 1)
        self.assertEqual(sign_of("1.0.0-rc.99", "1.0.0"), -1)
        self.assertEqual(sign_of("1.0.1-rc.1", "1.0.0"), 1)
        self.assertEqual(sign_of("1.0.0-preview.1", "1.0.0"), -1)

    def test_numeric_parts_are_lower_than_text_parts_and_more_parts_are_higher(self):
        self.assertEqual(sign_of("1.0.0-1", "1.0.0-a"), -1)
        self.assertEqual(sign_of("1.0.0-rc", "1.0.0-rc.1"), -1)
        self.assertEqual(sign_of("1.0.0-rc.1.1", "1.0.0-rc.1"), 1)
        self.assertEqual(sign_of("1.0.0-a", "1.0.0-b"), -1)
        self.assertEqual(sign_of("1.0.0-Z", "1.0.0-a"), -1, "ASCII 순서: 대문자가 소문자보다 앞")

    def test_build_metadata_does_not_change_the_order(self):
        self.assertEqual(sign_of("1.0.0+1", "1.0.0+2"), 0)
        self.assertEqual(sign_of("1.0.0", "1.0.0+5"), 0)
        self.assertFalse(versions.is_newer("1.0.0+9", "1.0.0"))
        self.assertEqual(sign_of("1.0.0-rc.1+a", "1.0.0-rc.1"), 0)

    def test_equal_is_not_newer_and_comparing_a_bad_text_raises(self):
        self.assertFalse(versions.is_newer("1.0.0", "1.0.0"))
        for bad in ("", "1.0", None, "v1.0.0"):
            with self.assertRaises(ValueError):
                versions.compare(bad, "1.0.0")
            with self.assertRaises(ValueError):
                versions.compare("1.0.0", bad)
            with self.assertRaises(ValueError):
                versions.is_newer(bad, "1.0.0")


class AgreementWithBackupFlowTest(unittest.TestCase):
    """`backup_flow._version_key` 와 같은 결과 — 두 곳이 '이 버전이 더 새롭다' 를 따로 다르게 말하지 않게 한다."""
    CORPUS = ("0.0.0", "0.1.0-preview.1", "0.1.0-preview.2", "0.1.0-preview.9", "0.1.0", "0.9.0-rc.1", "0.9.0-rc.2", "0.9.0-rc.9", "0.9.0", "1.0.0-alpha", "1.0.0-beta", "1.0.0-rc.1", "1.0.0-rc.5",
              "1.0.0", "1.0.1", "1.0.10", "1.1.0", "1.9.0", "1.10.0", "2.0.0", "10.0.0", "1.0.0+3", "0.1.0-preview.1+7")

    def test_the_two_orders_agree_on_every_pair_of_the_corpus(self):
        for left, right in itertools.product(self.CORPUS, repeat=2):
            one, two = backup_flow._version_key(left), backup_flow._version_key(right)
            legacy = (one > two) - (one < two)
            if left.split("+")[0] == right.split("+")[0] and left != right:
                continue                       # 빌드 표시만 다른 쌍 — 그쪽은 빌드 글을 키에 넣지 않아 같다고 보지만 둘 다 0 이다(아래에서 따로 확인)
            with self.subTest(left=left, right=right):
                self.assertEqual(sign_of(left, right), legacy)

    def test_build_only_differences_are_equal_in_both(self):
        self.assertEqual(backup_flow._version_key("1.0.0+3"), backup_flow._version_key("1.0.0+9"))
        self.assertEqual(sign_of("1.0.0+3", "1.0.0+9"), 0)

    def test_the_shapes_both_read_overlap_on_the_corpus(self):
        for text in self.CORPUS:
            self.assertIsNotNone(backup_flow._version_key(text), text)
            self.assertIsNotNone(versions.parse_version(text), text)


class SourceShapeTest(unittest.TestCase):
    def test_the_module_imports_only_re_dataclasses_and_future(self):
        import ast
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "update" / "versions.py").read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.add(node.module or "")
        self.assertEqual(sorted(found), ["__future__", "dataclasses", "re"])


if __name__ == "__main__":
    unittest.main()
