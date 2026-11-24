"""복사 전 관문 `secret_spots` 의 두 보강 분기가 **각각 필요하다**는 것을 시험으로 못박는다(앱 2차 감사 AS-S2 참고-21, 결정 D-684) — PySide6 없이 돈다(CI 와 같은 조건).

감사의 변이 M13(검사기 여섯 유형 병합을 지움)·M14(여러 덩어리에 걸친 정본 패턴 분기 `has_key_shape` 를 지움)는 둘 다 시험 227개가 모두 통과했다 — 그 분기만 잡는 입력이 시험에 없었기 때문이다.
이 분기들은 서로 겹치는 방어가 아니라 **서로 다른 입력을 잡는다**: 아래 입력은 다른 규칙(접두사 모양·긴 영숫자 덩어리·주소 규칙·이름 붙은 값)이 한 글자도 못 잡고 그 분기만 잡는다.
  · 검사기 분기(`_scanner_spans`): ① 이름이 붙은 OAuth 값(`access_token=…`)은 값이 **글자뿐**이어도 19자 넘으면 걸린다(긴 영숫자 덩어리 규칙은 영문자와 숫자가 모두 있어야 한다) ② 검사기는 전각 영문·숫자를 먼저 영문·숫자로 접어서 보지만(`scan._fold`) 다른 규칙은 접지 않는다.
  · 정본 패턴 분기(`has_key_shape`): 글자 사이에 공백이 든 모양(`Bearer 값`)·알려진 접두사 모양(`sk_live_…`)인데 값이 **글자뿐**이라 긴 영숫자 덩어리 규칙이 못 본다.
각 입력은 ① 지금은 걸리고 ② 그 분기를 없앤 것처럼(검사기 자리를 빈 목록으로·`has_key_shape` 를 거짓으로) 하면 아무것도 안 걸린다 — 분기를 지우면 이 시험이 빨개진다.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_samples as S  # noqa: E402

from chanceblog_desktop.ui.core import draft_rules as rules  # noqa: E402


def fullwidth(text):
    """ASCII 글자·숫자·기호를 전각으로 — 검사기만 접어서 본다."""
    return "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= chr(0x7E) else ch for ch in text)


SCANNER_ONLY = (
    "access_token=" + "abcdefghijklmnopqrstuvwxyz",
    "refresh-token: " + "abcdefghijklmnopqrstuvwx",
    fullwidth(S.google()),
    fullwidth(S.github()),
    "앞 글 " + fullwidth(S.aws()) + " 뒤 글",
)
SHAPE_ONLY = (
    "sk" + "_live_" + "abcdefghijklmnopqrstuvwx",
    "앞 글 " + "sk" + "_live_" + "abcdefghijklmnopqrstuvwx" + " 뒤 글",
    "Bea" + "rer " + "abcdefghijklmnopq",
    "Bea" + "rer\t" + "abcdefghijklmnopq",
)


class BranchPinTest(unittest.TestCase):
    def test_the_scanner_branch_is_needed_for_each_of_these_inputs(self):
        for text in SCANNER_ONLY:
            with self.subTest(text=text[:24]):
                self.assertTrue(rules.secret_spots(text), "(전제) 지금은 걸린다")
                with mock.patch.object(rules, "_scanner_spans", return_value=()):
                    self.assertEqual(rules.secret_spots(text), (), "검사기 분기를 지우면 이 입력은 아무 규칙에도 안 걸린다")

    def test_the_multi_chunk_key_shape_branch_is_needed_for_each_of_these_inputs(self):
        for text in SHAPE_ONLY:
            with self.subTest(text=text[:24]):
                self.assertTrue(rules.secret_spots(text), "(전제) 지금은 걸린다")
                with mock.patch("chanceblog_desktop.security.mask.has_key_shape", return_value=False):
                    self.assertEqual(rules.secret_spots(text), (), "정본 패턴 분기를 지우면 이 입력은 아무 규칙에도 안 걸린다")

    def test_each_input_depends_only_on_its_own_branch(self):
        """두 분기는 서로 겹치는 방어가 아니라 다른 입력을 잡는다 — 검사기 입력은 정본 패턴 분기를, 정본 패턴 입력은 검사기를 없애도 그대로 걸린다."""
        for text in SCANNER_ONLY:
            with mock.patch("chanceblog_desktop.security.mask.has_key_shape", return_value=False):
                self.assertTrue(rules.secret_spots(text), text[:24])
        for text in SHAPE_ONLY:
            with mock.patch.object(rules, "_scanner_spans", return_value=()):
                self.assertTrue(rules.secret_spots(text), text[:24])

    def test_ordinary_text_next_to_these_shapes_is_still_not_blocked(self):
        for text in ("access_token 은 로그인 뒤에 받는 값을 말해요", "Bearer 방식은 헤더에 값을 넣는 방법이에요", "sk_live 는 결제 서비스가 쓰는 접두사 이름이에요", "전각 글자 ＡＢＣ ｄｅｆ 도 일반 글이에요"):
            with self.subTest(text=text[:20]):
                self.assertEqual(rules.secret_spots(text), ())


if __name__ == "__main__":
    unittest.main()
