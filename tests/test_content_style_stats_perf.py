"""'내 글 문체 참고값'(N-3a) 순수 계산의 **시간** 시험 — 10만 자 둘이 **어떤 입력에서도 2초 이내**다(목표 0.5초, 보통 글은 0.05초 안팎).

N-2 에서 문장 지문 정규화가 병적 입력(결합 글자 10만 개)에서 19초 걸린 교훈(D-322)을 이 모듈에도 적용했다 — 정규식은 선형만, NFC 는 공백 자리에서 512자 조각으로.
병적 입력(결합 글자·같은 글자 반복·긴 한 줄·줄바꿈만·꺾쇠만·열린 표시·열린 코드 울타리·열린 링크·표 구분 줄 …)을 마크다운·텍스트 두 형식으로 모두 돌린다.
시험 기계가 느려도 흔들리지 않게 한계는 2초로 두었고 실제 값은 이 PC 에서 두 글 합쳐 최대 0.5초 안이다(3.12 0.45초·3.10 0.49초 — 줄마다 한 글자뿐인 입력이 가장 느리다. 측정은 결정 기록).
소스·시험에는 물결 글자와 웹 주소를 날것으로 쓰지 않는다.
"""
import sys
import time
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import style_stats as S  # noqa: E402

N = S.MAX_CHARS
LIMIT = 2.0                                        # 한 글 둘(10만 자 × 2)에 허용하는 시간(초)
SCHEME = "https" + "://"
FIXTURE = (ROOT / "tests" / "fixtures" / "chance_post_ko.md").read_text(encoding="utf-8")


def fill(unit, size=N):
    """`unit` 을 되풀이해 정확히 `size` 글자로."""
    return (unit * (size // len(unit) + 1))[:size]


def cases():
    normal = fill(FIXTURE)
    return {
        "정상 글(실제 글 되풀이)": normal,
        "정상 글 줄바꿈 60칸": "\n".join(normal[index:index + 60] for index in range(0, N, 60)),
        "결합 글자 U+0F73 10만 개": fill(chr(0x0F73)),
        "결합 글자 U+0301 10만 개": "a" + chr(0x0301) * (N - 1),
        "결합 글자 U+0344 10만 개": fill(chr(0x0344)),
        "분리형 한글 10만": unicodedata.normalize("NFD", "한") * (N // 3),
        "분리형 한글 + 공백": unicodedata.normalize("NFD", "한글 ") * (N // 7),
        "한 글자 반복": fill("가"),
        "끝 부호와 공백만": fill(". "),
        "끝 부호만": fill("."),
        "닫는 따옴표 이음": fill(".\""),
        "마침표 없는 한 줄(공백 많음)": fill("가나다 "),
        "줄바꿈만": fill("\n"),
        "빈 줄만": fill("\n\n"),
        "줄바꿈과 한 글자": fill("가\n"),
        "CRLF 한 글자 줄": fill("가\r\n"),
        "꺾쇠(인용) 줄": fill("> 가\n"),
        "꺾쇠만": fill(">"),
        "열린 대괄호": fill("["),
        "열린 링크 시작": fill("[a]("),
        "닫는 대괄호와 괄호": fill("]("),
        "그림 시작 반복": fill("![a]("),
        "그림 대괄호 반복": fill("![a]["),
        "대괄호 안의 긴 글": "[" + "가" * (N - 2) + "]",
        "열린 꺾쇠 태그": fill("<p "),
        "열린 꺾쇠": fill("<"),
        "주석 시작 반복": fill("<!--"),
        "코드 울타리 열림만": "```\n" + fill("가 "),
        "울타리 줄 반복": fill("```\n"),
        "울타리 한 줄 가득": fill("`"),
        "역따옴표 사이 글": fill("`가`"),
        "인터넷 주소 반복": fill(SCHEME + "a "),
        "인터넷 주소 붙은 긴 줄": SCHEME * (N // 8),
        "꺾쇠 주소 반복": "<" + fill(SCHEME + "a>"),
        "표 줄 반복": fill("| a | b |\n"),
        "표 구분 줄 반복": fill("|---|---|\n"),
        "표 구분 줄 모양의 긴 줄(끝이 틀림)": "|-" * (N // 2 - 1) + "x",
        "표 구분 줄 공백 모양의 긴 줄(끝이 틀림)": "| - " * (N // 4 - 1) + "x",
        "첫 | 없는 표": fill("a | b\n--|--\n"),
        "목록 줄 반복": fill("- 가나다\n"),
        "한 줄 안 목록 표시": fill("- "),
        "숫자 목록 표시": fill("1. "),
        "머리말 열림만": "---\n" + fill("layout: x\n"),
        "머리말 닫힘 반복": fill("---\nlayout: x\n---\n"),
        "해시태그 줄": fill("#가 #나 #다\n"),
        "제목 줄 반복": fill("## 가\n"),
        "제목 표시만": fill("#"),
        "한 줄 100자 문장": fill("가나다라마바사아자차 " * 10 + ".\n"),
        "하드랩 40칸": fill("가나다 라마바 사아자 차카타 파하\n"),
        "이모지": fill("😊"),
        "이모지 문장": fill("좋아요😊. "),
        "ZWJ 이음 이모지": "👨" + chr(0x200D) + "👩" + chr(0x200D) + fill("👧"),
        "보이지 않는 글자만": fill(chr(0x200B)),
        "제어 문자만": fill(chr(0x1B)),
        "영문 긴 글": fill("word "),
        "영문 문장 반복": fill("This is a sentence. "),
        "물음표 문장 반복": fill("정말요? "),
        "하이픈 줄 끝": fill("abc-\n"),
        "공백과 탭만": fill(" \t"),
        "강조 표시 반복": fill("*"),
        "밑줄 표시 반복": fill("_"),
    }


class PerfTest(unittest.TestCase):
    def time_two(self, text, form):
        start = time.perf_counter()
        first = S.analyze(text, form)
        second = S.analyze(text, form)
        S.summarize([first, second])
        return time.perf_counter() - start

    def test_a_hundred_thousand_characters_twice_stays_under_two_seconds_for_every_input_in_both_forms(self):
        worst = (0.0, "")
        for name, text in cases().items():
            text = text[:N]
            self.assertLessEqual(len(text), N, name)
            for form in ("md", "txt"):
                with self.subTest(case=name, form=form):
                    seconds = self.time_two(text, form)
                    worst = max(worst, (seconds, f"{name} {form}"))
                    self.assertLess(seconds, LIMIT, f"{name} {form}: {seconds:.2f}초")
        self.assertLess(worst[0], LIMIT)

    def test_the_cases_cover_enough_kinds_and_every_one_is_full_length(self):
        found = cases()
        self.assertGreaterEqual(len(found), 50)
        for name, text in found.items():
            self.assertGreaterEqual(len(text), N - 20, f"{name}: 글이 너무 짧다 {len(text)}")

    def test_every_case_returns_a_value_without_an_error(self):
        for name, text in cases().items():
            for form in ("md", "txt", "pasted"):
                with self.subTest(case=name, form=form):
                    stats = S.analyze(text[:N], form)
                    self.assertGreaterEqual(stats.sentences, 0)

    def test_the_time_grows_roughly_in_step_with_the_length_for_a_normal_text(self):
        """선형 확인 — 열 배 긴 보통 글이 열 배의 서너 배 넘게 걸리지 않는다(제곱 시간이면 백 배)."""
        text = (FIXTURE * 200)[:N]
        small = text[: N // 10]
        for form in ("md", "txt"):
            start = time.perf_counter()
            for _ in range(10):
                S.analyze(small, form)
            ten_small = time.perf_counter() - start
            start = time.perf_counter()
            S.analyze(text, form)
            one_big = time.perf_counter() - start
            self.assertLess(one_big, max(ten_small * 4, 0.05), f"{form}: {one_big:.3f} vs {ten_small:.3f}")

    def test_the_combining_character_flood_is_chunked_so_it_is_not_quadratic(self):
        """N-2 의 교훈 — 결합 글자 10만 개를 한 번에 정규화하면 19초였다. 조각으로 나눠 부르므로 훨씬 짧다."""
        start = time.perf_counter()
        S.analyze(fill(chr(0x0F73)), "md")
        self.assertLess(time.perf_counter() - start, 1.0)


if __name__ == "__main__":
    unittest.main()
