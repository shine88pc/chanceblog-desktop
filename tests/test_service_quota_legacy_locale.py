"""한글이 든 날짜 서식을 `strftime` 에 넘기지 않는다 — 윈도 파이썬 3.10 은 `datetime.strftime` 의 서식을 PC 의 로캘 인코딩으로 바꿔 쓴다.

한국어 윈도(cp949)에서는 한글이 그대로 들어가 문제가 안 보이지만 영문 윈도(cp1252)·GitHub 의 윈도 칸에서는 `UnicodeEncodeError` 로 깨진다(R-091 의 자동 검사에서 윈도·3.10 칸이
이 일로 68개 시험이 깨져 빨갛게 끝났다). 개발 PC 가 한국어 윈도라서 로컬 시험으로는 안 보였다. 그래서 두 가지를 지킨다:
  1) 소스(`src/`)에서 `strftime`·`strptime` 에 한글 같은 ASCII 밖 글자가 든 서식을 넘기는 곳이 없다(한글은 서식 밖에서 f-문자열로 붙인다).
  2) 한도 안전장치 시험을 `time.strftime` 이 서식을 cp1252 로 바꾸는 것처럼(한글이 있으면 `UnicodeEncodeError`) 다시 돌려도 모두 통과한다 —
     어느 PC 에서든 구형 로캘의 깨짐을 그대로 흉내 내므로 이 시험은 고치기 전 코드에서는 실패한다.
"""
import ast
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support  # noqa: E402,F401  (시험 경로 설정)
import test_service_quota as base  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src"
FORMAT_CALLS = frozenset({"strftime", "strptime"})
DATE_LETTERS = frozenset("YymdHIMSfzZaAbBjUWwpcxX")


def legacy_locale_strftime():
    """영문 윈도 파이썬 3.10 의 `time.strftime` 흉내: 서식을 시스템 로캘 인코딩(cp1252)으로 바꾸는데 한글이 있으면 `UnicodeEncodeError`."""
    real = time.strftime

    def strftime(fmt, *args):
        fmt.encode("cp1252")
        return real(fmt, *args)

    return strftime


class NoNonAsciiDateFormatTest(unittest.TestCase):
    def test_no_source_file_passes_a_non_ascii_format_to_strftime_or_strptime(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in FORMAT_CALLS and node.args:
                    for part in ast.walk(node.args[0]):
                        if isinstance(part, ast.Constant) and isinstance(part.value, str) and not part.value.isascii():
                            offenders.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
        self.assertEqual(offenders, [], "한글이 든 서식을 strftime·strptime 에 넘기면 영문 윈도 파이썬 3.10 에서 깨진다 — 한글은 서식 밖에서 붙이세요")

    def test_no_module_level_date_format_constant_has_non_ascii_letters(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    text = node.value.value
                    if "%" in text and not text.isascii() and any(text[i + 1] in DATE_LETTERS for i in range(len(text) - 1) if text[i] == "%"):
                        offenders.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_the_legacy_locale_stand_in_really_breaks_a_korean_format(self):
        """흉내 자체가 제구실을 하는지: 한글 서식은 깨지고 ASCII 서식은 정상이다(이게 안 깨지면 아래 시험이 아무것도 못 지킨다)."""
        from datetime import datetime, timezone
        moment = datetime(2026, 11, 5, 9, 7, tzinfo=timezone.utc)
        with mock.patch("time.strftime", legacy_locale_strftime()):
            self.assertEqual(moment.strftime("%m-%d %H:%M"), "11-05 09:07")
            with self.assertRaises(UnicodeEncodeError):
                moment.strftime("%m월 %d일")


def _legacy_variant(cls):
    class Variant(cls):
        def setUp(self):
            patcher = mock.patch("time.strftime", legacy_locale_strftime())
            patcher.start()
            self.addCleanup(patcher.stop)
            super().setUp()

    Variant.__name__ = Variant.__qualname__ = "LegacyLocale" + cls.__name__
    Variant.__doc__ = f"`{cls.__name__}` 의 시험을 구형 로캘(cp1252 서식 인코딩)에서 그대로 다시 돌린다."
    return Variant


# 같은 시험을 구형 로캘 흉내 아래에서 다시 돌린다. 진짜 두 프로세스를 띄우는 `ProcessRaceTest` 는 제외한다(자식 프로세스에는 흉내가 닿지 않는다).
for _name in ("BudgetTest", "SwitchRulesTest", "BackoffTest", "RetryAfterFormatTest", "HeaderSyncTest", "StateFileTest", "AvailabilityTest", "SecretTest"):
    globals()["LegacyLocale" + _name] = _legacy_variant(getattr(base, _name))
del _name


if __name__ == "__main__":
    unittest.main()
