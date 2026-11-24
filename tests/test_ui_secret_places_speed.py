"""복사 전 관문의 키·토큰 자리 찾기가 큰 글에서 제곱 시간이 걸리지 않는다(앱 2차 감사 AS-S2 권고-4, 결정 D-681) — PySide6 없이 돈다(CI 와 같은 조건).

감사 재현: 같은 24자 토큰이 되풀이되는 글에서 `secret_places` 가 2천 자 0.07초 → 4천 자 0.26초 → 8천 자 0.99초 → 1만 6천 자 3.79초(두 배마다 3.8배)였다 — 저장 한도(15만 자)까지 같은 모양이면 약 5분이라
복사 단추(화면 스레드)를 누르면 앱이 멈춘 듯 보인다. 원인 둘: ① 막은 자리마다 글 **전체**를 검사기로 다시 훑었다(그 결과는 이미 `front` 한 줄이 정하는 값과 같아서 쓸모가 없었다) ② 검사기 자리를 더할 때 자리마다 앞의 모든 자리와 하나씩 견줬다.

이 파일이 못박는 것:
  1) **판정은 옛 방식과 같다** — 옛 `secret_spots`·`_place`·`secret_places` 를 시험 도구 `tests/draft_gate_oracle.py` 에 그대로 옮겨 두고, 서로 다른 입력 수천 개(정상 글·주소·파일 이름·키 모양·같은 토큰 되풀이·검사기가 찾는 모양·겹치는 자리)에서 결과가 한 글자도 다르지 않다.
  2) 자리를 합치는 함수(`_add_free_spans`)는 옛 '앞의 모든 자리와 견주기' 와 무작위 구간 수천 개에서 같다(길이 0인 자리·같은 시작·같은 끝·이웃한 자리 포함).
  3) 검사기는 글 하나에 **한 번만** 돈다(막은 자리가 수백 개여도) — 호출 횟수로 못박는다(시간 비율은 흔들려서 보조로만 본다).
  4) 병적인 입력(같은 토큰·검사기 모양·정상 주소·긴 덩어리·줄바꿈 가득)의 2만 자가 몇 초 안에 끝나고, 길이 열 배에 시간이 열 배 안쪽(여유를 둔 스무 배 미만)으로만 늘어난다.
"""
import random
import re
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_gate_oracle import old_merge, old_place, old_secret_places, old_secret_spots  # noqa: E402,F401  (옛 방식 사본 — 시험 도구)
from draft_samples import NORMAL_ADDRESSES, NORMAL_FILE_NAMES, NORMAL_MORE, SECRET_ADDRESSES, hexed, mixed  # noqa: E402

from chanceblog_desktop.ui.core import draft_rules as rules  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
NAMED_VALUE = re.compile(r"(?i)(?:password|passwd|secret|token|credential|session_?id|key)s?[\"']?[ 	]*[:=]")        # 이름 붙은 값(D-682)은 이 파일의 비교 대상이 아니다 — 입력에 `이름:`·`이름=` 꼴이 없게 만든다


# ---- 입력 만들기 --------------------------------------------------------------------------------------------------------------------------------
SENTENCES = ("예시 청소기 고르는 기준을 한 줄로 정리해요.", "2026년 11월 5일 오후 3시", "A1B2", "가나다라마바사아자차카타파하", "(괄호) 안의 글과 [대괄호] 글", "첫째, 둘째; 셋째 — 넷째.", "상품번호는 AB1234567890123456789012345 입니다",
             "d41d8cd98f00b204e9800998ecf8427e", "ABC-1234-DEFG-5678-HIJK-9012-LMNO", "Hello world 12345 and again", "가격은 12,900원 입니다", "줄\t바꿈\r\n과 탭")
SCANNER_SHAPES = (KEY_SHAPED, "gh" + "p_" + mixed("old1", 36), "AI" + "za" + mixed("old2", 35, "_-"), "ya" + "29." + mixed("old3", 40, "_-"), "AKIA" + "ABCDEFGH12345678", "xox" + "b-" + "1234567890-" + mixed("old4", 24),
                  "Bea" + "rer " + mixed("old5", 30), "-----BEGIN " + "PRIVATE KEY-----\n" + "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n" + "-----END " + "PRIVATE KEY-----")
TOKENS = tuple(mixed(f"old-token-{number}", size) for number, size in enumerate((10, 12, 20, 23, 24, 25, 30, 40, 64)))
ADDRESSES = tuple(NORMAL_ADDRESSES) + tuple(NORMAL_FILE_NAMES) + tuple(NORMAL_MORE[:30]) + tuple(address for _name, address, _secret in SECRET_ADDRESSES)
GLUE = (" ", "  ", "\n", "\n\n", " — ", "·", ", ", "\t", "")


def make_text(rng, heavy=False):
    pieces = []
    for _ in range(rng.randint(1, 10)):
        kind = rng.random()
        if kind < 0.28:
            pieces.append(rng.choice(SENTENCES))
        elif kind < 0.46:
            pieces.append(rng.choice(TOKENS))
        elif kind < 0.62:
            pieces.append(rng.choice(SCANNER_SHAPES))
        elif kind < 0.84:
            pieces.append(rng.choice(ADDRESSES))
        elif kind < 0.92:
            token = rng.choice(TOKENS + SCANNER_SHAPES)
            pieces.append((rng.choice(GLUE[:3]) or " ").join([token] * rng.randint(2, 5 if not heavy else 9)))
        else:
            pieces.append(rng.choice(("가" * rng.randint(1, 30), "x" * rng.randint(1, 40), "9" * rng.randint(1, 40))))
        pieces.append(rng.choice(GLUE))
    return "".join(pieces)


class SameAnswersTest(unittest.TestCase):
    """판정은 옛 방식과 같다 — 같은 입력이면 걸린 자리도 미리보기도 한 글자 다르지 않다."""

    def test_the_pieces_outside_addresses_never_contain_a_name_word_so_only_the_speed_changes(self):
        """이름 붙은 값(D-682)은 이 파일의 비교 대상이 아니다 — 주소 밖의 조각에는 이름 낱말이 없게 만든다(주소 안은 이름 붙은 값 규칙이 보지 않는다)."""
        for piece in (*SENTENCES, *TOKENS, *SCANNER_SHAPES):
            self.assertIsNone(NAMED_VALUE.search(piece), piece[:30])

    def test_spots_and_places_equal_the_old_ones_on_thousands_of_different_inputs(self):
        rng = random.Random(680)
        different, with_spots, with_scanner, checked = [], 0, 0, 0
        for number in range(2400):
            text = make_text(rng, heavy=number % 6 == 0)
            title = make_text(rng)[:80]
            new_spots = rules.secret_spots(text)
            if new_spots != old_secret_spots(text):
                different.append(("spots", text[:60]))
            if rules.secret_places(("본문", text), ("제목", title)) != old_secret_places(("본문", text), ("제목", title)):
                different.append(("places", text[:60]))
            checked += 1
            with_spots += bool(new_spots)
            with_scanner += bool(rules._scanner_spans(text))
        self.assertEqual(different, [], "옛 방식과 다른 입력이 있다")
        self.assertEqual(checked, 2400)
        self.assertGreater(with_spots, 800, "(전제) 걸린 글이 충분히 섞여 있다")
        self.assertGreater(with_scanner, 300, "(전제) 검사기가 찾는 모양이 든 글이 충분히 섞여 있다")

    def test_special_inputs_equal_the_old_ones(self):
        for text in ("", " ", "정상 글입니다.", KEY_SHAPED, KEY_SHAPED * 3, (KEY_SHAPED + " ") * 40, "앞 글 " + KEY_SHAPED + " 뒤 글", 123, None, ["a"], "가" * 100_001, "x" * 100_000, "-----BEGIN " + "PRIVATE KEY-----" * 3,
                     "https://example.com/?k=" + KEY_SHAPED, KEY_SHAPED + ".jpg", "Bea" + "rer " + mixed("sp", 30) + " " + KEY_SHAPED):
            with self.subTest(text=repr(text)[:30]):
                self.assertEqual(rules.secret_spots(text), old_secret_spots(text))
                self.assertEqual(rules.secret_places(("본문", text)), old_secret_places(("본문", text)))
        many = [("본문", f"문장 {number} {chr(65 + number)}1b2C3d4E5f6G7h8I9j0K1l2M3n4") for number in range(9)]
        self.assertEqual(rules.secret_places(*many), old_secret_places(*many))
        self.assertEqual(len(rules.secret_places(*many)), rules.SPOT_LIMIT)


class AddFreeSpansTest(unittest.TestCase):
    """겹침 판정은 옛 '앞의 모든 자리와 하나씩 견주기' 와 똑같다 — 길이 0인 자리·같은 시작·같은 끝·이웃한 자리·서로 겹치는 기존 자리까지."""

    def test_the_rule_in_plain_cases(self):
        add = rules._add_free_spans
        self.assertEqual(sorted(add([], [(0, 5), (5, 9)])), [(0, 5), (5, 9)], "이웃한 자리는 겹치지 않는다")
        self.assertEqual(sorted(add([], [(0, 5), (4, 9)])), [(0, 5)], "겹치면 먼저 온 쪽이 이긴다")
        self.assertEqual(sorted(add([], [(4, 9), (0, 5)])), [(4, 9)], "순서가 결과를 정한다")
        self.assertEqual(sorted(add([(2, 3)], [(0, 5)])), [(2, 3)], "이미 있는 자리가 안에 있으면 검사기 자리는 물러난다")
        self.assertEqual(sorted(add([(0, 5)], [(5, 8), (8, 9)])), [(0, 5), (5, 8), (8, 9)])
        self.assertEqual(sorted(add([(3, 3)], [(0, 5), (3, 4)])), [(3, 3), (3, 4)], "길이 0인 자리가 안쪽에 있으면 겹치고(0–5), 가장자리에 닿기만 하면 겹치지 않는다(3–4)")
        self.assertEqual(sorted(add([(3, 3)], [(3, 5), (0, 3)])), [(0, 3), (3, 3), (3, 5)], "길이 0인 자리가 가장자리에 있으면 겹치지 않는다")
        self.assertEqual(add([(0, 1)], []), [(0, 1)])
        self.assertEqual(add([], []), [])
        spots = [(5, 9), (1, 2)]
        add(spots, [(0, 1)])
        self.assertEqual(spots, [(5, 9), (1, 2)], "받은 목록은 바꾸지 않는다")

    def test_equal_to_the_old_way_on_thousands_of_random_interval_sets(self):
        rng = random.Random(682)
        for number in range(6000):
            limit = rng.choice((6, 12, 40, 400))
            spots = [self.interval(rng, limit) for _ in range(rng.randint(0, 8))]
            spans = [self.interval(rng, limit) for _ in range(rng.randint(0, 25))]
            self.assertEqual(sorted(rules._add_free_spans(spots, spans)), sorted(old_merge(spots, spans)), f"{number}: {spots} + {spans}")

    @staticmethod
    def interval(rng, limit):
        start = rng.randint(0, limit)
        return (start, start + (0 if rng.random() < 0.12 else rng.randint(1, max(1, limit // 3))))

    def test_thousands_of_spans_are_merged_fast(self):
        spans = [(index * 25, index * 25 + 20) for index in range(8000)]
        started = time.perf_counter()
        self.assertEqual(len(rules._add_free_spans([(index * 25 + 21, index * 25 + 22) for index in range(0, 8000, 2)], spans)), 8000 + 4000)
        self.assertLess(time.perf_counter() - started, 1.0)


class FewScannerRunsTest(unittest.TestCase):
    """검사기는 글 하나에 한 번만 돈다 — 막은 자리가 수백 개여도(호출 횟수는 시간과 달리 흔들리지 않는다)."""

    def counting(self):
        return mock.patch.object(rules, "_scanner_spans", wraps=rules._scanner_spans)

    def test_the_same_token_repeated_hundreds_of_times_runs_the_scanner_once_per_field(self):
        body = "Zq8xK2mP9vL4nR7tY1wE5uI3 " * 400
        with self.counting() as spy:
            places = rules.secret_places(("본문", body))
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(places, old_secret_places(("본문", body)), "미리보기는 옛 방식과 같다")
        self.assertLessEqual(len(places), 2, "같은 미리보기는 한 번만 보인다(맨 앞 자리만 앞 글이 없어 하나 더)")
        with self.counting() as spy:
            rules.secret_places(("제목", "짧은 제목"), ("본문", body), ("키워드", "예시 낱말"))
        self.assertEqual(spy.call_count, 3, "칸마다 한 번 — 막은 자리 수와 상관없다")

    def test_scanner_shapes_repeated_run_it_once_too(self):
        body = (KEY_SHAPED + " ") * 300
        with self.counting() as spy:
            spots = rules.secret_spots(body)
        self.assertEqual((len(spots), spy.call_count), (300, 1))
        with self.counting() as spy:
            places = rules.secret_places(("본문", body))
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(places, old_secret_places(("본문", body)))

    def test_inspect_text_and_has_secret_use_the_same_single_pass(self):
        body = "정상 문장입니다. " + ("gh" + "p_" + mixed("one", 36) + " ") * 120
        with self.counting() as spy:
            self.assertTrue(rules.has_secret(body))
            inspection = rules.inspect_text("제목", body)
        self.assertTrue(inspection.secret)
        self.assertEqual(spy.call_count, 3, "has_secret 한 번(본문) + inspect_text 의 secret_places 두 칸(제목·본문)")


class PathologicalInputsTest(unittest.TestCase):
    """병적인 입력(같은 모양이 수천 번)이 몇 초 안에 끝나고, 길이에 비례해서만 늘어난다."""
    LARGE, SMALL = 20_000, 2_000
    SHAPES = {
        "같은 24자 토큰": lambda n: "Zq8xK2mP9vL4nR7tY1wE5uI3 " * (n // 25),
        "검사기 모양(AKIA)": lambda n: (KEY_SHAPED + " ") * (n // 17),
        "GitHub 토큰": lambda n: ("gh" + "p_" + mixed("path", 36) + " ") * (n // 41),
        "정상 주소 되풀이": lambda n: "참고 https://blog.naver.com/exampleaaa/223012345678 입니다. " * (n // 56),
        "긴 영숫자 한 덩어리": lambda n: "a1" * (n // 2),
        "줄바꿈 가득": lambda n: "\n" * n,
        "서로 다른 토큰": lambda n: " ".join(mixed(f"distinct{number}", 24) for number in range(n // 25)),
    }

    @staticmethod
    def best(call, *, times=3):
        best = None
        for _ in range(times):
            started = time.perf_counter()
            call()
            spent = time.perf_counter() - started
            best = spent if best is None or spent < best else best
        return best

    def test_twenty_thousand_characters_finish_in_seconds(self):
        for label, make in self.SHAPES.items():
            text = make(self.LARGE)
            with self.subTest(label=label):
                started = time.perf_counter()
                places = rules.secret_places(("본문", text))
                spots = rules.secret_spots(text)
                spent = time.perf_counter() - started
                self.assertLess(spent, 3.0, f"{label}: {spent:.2f}초")
                self.assertLessEqual(len(places), rules.SPOT_LIMIT)
                self.assertEqual(bool(spots), bool(places))

    def test_ten_times_the_length_costs_less_than_twenty_times_the_time(self):
        """제곱이면 약 100배, 선형이면 약 10배다 — 흔들림을 위해 스무 배 미만으로 본다(가장 빠른 세 번 중 하나로 잰다)."""
        for label in ("같은 24자 토큰", "검사기 모양(AKIA)", "GitHub 토큰", "정상 주소 되풀이"):
            make = self.SHAPES[label]
            small, large = make(self.SMALL), make(self.LARGE)
            with self.subTest(label=label):
                fast = max(self.best(lambda: rules.secret_places(("본문", small))), 0.01)
                slow = self.best(lambda: rules.secret_places(("본문", large)))
                self.assertLess(slow / fast, 20, f"{label}: {self.SMALL}자 {fast:.3f}초 → {self.LARGE}자 {slow:.3f}초")


if __name__ == "__main__":
    unittest.main()
