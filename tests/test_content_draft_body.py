"""규칙 기반 초안 본문 생성기(`content/draft_body.py` 의 `build_body`) 시험 — 순수 함수라 네트워크·파일 없이 돈다.

지키는 것(작업 지시서의 ① ~ ⑩):
  ① 구조: 후보 14개 × 블로그 프로필(없음·기본·자세히) × 네이버 A·B × 글 유형 5종에서 최소 구성 13가지가 채워지고 소제목은 4~6개·문단은 2~3개이며 분량이 공백 뺀 1,800자 이상·공백 포함 2,800자 이하다.
  ② 결정성: 같은 입력 두 번은 글자까지 같고, 해시 시드가 다른 프로세스에서도 같다(문장 변형을 `zlib.crc32` 로 돌려 고른다).
  ③ 지어내지 않음: 금지 낱말·패턴(1인칭 체험·가격·기간·수치·효능·최상급·협찬 단정·시점)이 0건, 블로그 이름·ID·별명이 새지 않고, 사용자가 입력한 글(경험·의견·전하고 싶은 내용·반드시 넣을 문장·결론·가격·날짜·주소)은 그대로 쓰인다.
  ④ `check/` 통과: 모든 조합의 본문이 `find_claims`(위반 + 확인 권장) 0건이다(키워드에 숫자가 있으면 위반 0건). 사용자 글만 예외.
  ⑤ 조사: 받침 있는/없는 키워드 240개로 만든 초안에서 키워드 바로 뒤의 조사가 모두 맞다(틀린 이형태 0건·`은(는)` 꼴 0건).
  ⑥ 평문: 마크다운·HTML 기호가 없고 소제목·문단은 빈 줄 하나로만 나뉘며 앞뒤에 빈 줄이 없다. 항목별 글(제목·본문·태그)도 같다.
  ⑦ 순수: 파일·네트워크·프로세스 호출(감사 훅)·시계·난수 호출이 0이고 소스가 그런 모듈을 가져오지 않는다.
  ⑧ 입력 오류: 후보 글에 키 모양·채널 프로필 모양 오류·모르는 블로그·글 유형·날짜는 쉬운 오류, 1,000자 경험·이모지·긴 키워드는 만들어진다.
  ⑨ 문장 틀 다양성: 한 초안에 같은 문장이 없고 문단 첫 문장이 모두 다르며 같은 첫 낱말로 시작하는 문단이 너무 많지 않다.
  ⑩ 작성 기반은 그대로: `build_plan` 의 결과를 바꾸지 않고 같은 값을 쓴다(제목·태그·안전 대체).
  독립 검증 수정(H1·H2·M1·M3·M4·M5):
  ⑪ 분야 오판 없음: 채널 프로필의 주제로 분야를 짐작하지 않고(못 읽으면 일반 틀), 한글 낱말은 낱말 경계로만 읽고, 틀은 분야 중립이다(곰팡이·도서관·독서 글에 기기·숙소 문장이 없다).
  ⑫ 안전 판정: 자동 초안 중지는 거절(입력을 되풀이하지 않는다), 근거 확인 필요·협찬 낱말 추정·단정 낱말은 확인 권장 맨 위의 경고, 민감 낱말 목록은 넓혔다.
  ⑬ 키 모양 11종은 후보·채널 프로필·선택 입력 모든 칸에서 거절된다. 후보의 마크다운·HTML 엔티티는 걷어 낸다.
  ⑭ 결정성은 여러 후보(보조 키워드·태그·선택 입력 포함)와 해시 시드가 다른 여러 프로세스로 본다. 같은 후보를 두 블로그로 만든 글·같은 유형의 다른 후보 글의 유사도는 지금 수준을 넘지 않는다.
"""
import contextlib
import dataclasses
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.check import claims  # noqa: E402
from chanceblog_desktop.content import body_bank as bb  # noqa: E402
from chanceblog_desktop.content import body_blocks as blk  # noqa: E402
from chanceblog_desktop.content import body_lang as bl  # noqa: E402
from chanceblog_desktop.content import body_library as lib  # noqa: E402
from chanceblog_desktop.content import draft_body as db  # noqa: E402
from chanceblog_desktop.content import draft_plan as dp  # noqa: E402
from chanceblog_desktop.content import post_types as pt  # noqa: E402
from chanceblog_desktop.content.candidates import Candidate  # noqa: E402
from chanceblog_desktop.content.draft_options import DraftOptions  # noqa: E402
from chanceblog_desktop.content.profiles import POST_TYPES, NaverProfile  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import channels, safety  # noqa: E402

TODAY = "2026-11-07"
NOW = "2026-11-02T03:00:00Z"
INFO, COMPARE, TROUBLE, PRODUCT, PLACE = POST_TYPES
KEY = "AI" + "za" + "A" * 35                                              # 구글 키 모양의 가짜 값(저장소에 키 문자열을 두지 않는다)
CANDIDATES = (
    ("겨울 보일러 점검 순서", "보일러 점검", ("보일러 청소", "난방비"), INFO), ("무선 청소기 선택 기준", "무선 청소기", ("청소기 추천",), COMPARE), ("로컬 AI 그래픽카드를 고를 때", "로컬 AI 그래픽카드", ("GPU VRAM", "로컬 LLM"), COMPARE),
    ("노트북 전원이 안 켜질 때", "노트북 전원", ("전원 문제",), TROUBLE), ("곰팡이 제거 방법", "곰팡이 제거", (), TROUBLE), ("로봇청소기 기능 정리", "로봇청소기", ("스마트 가전",), PRODUCT),
    ("ChatGPT 요금제 선택", "ChatGPT 요금제", ("AI 서비스",), PRODUCT), ("제주 숙소 예약 안내", "제주 숙소", ("여행",), PLACE), ("동네 도서관 이용 안내", "동네 도서관", (), PLACE),
    ("업무 자동화 도구", "업무 자동화", ("매크로",), INFO), ("독서 습관 만들기", "독서 습관", (), INFO), ("영양제 고르는 기준", "영양제 고르는 기준", (), INFO),
    ("서울 맛집 방문 후기", "맛집 방문 후기", ("서울 맛집",), PLACE), ("노트북 사용 후기", "노트북 사용후기", (), PRODUCT),
)
PREMISE_KEYWORDS = ("맛집 방문 후기", "노트북 사용후기")
# 틀 어디에도 없어야 하는 낱말(라이브러리 시험과 같은 기준) — 최상급·효능·평가·협찬·1인칭 체험·시점·시장 낱말
BANNED = ("가장", "최고", "최저", "최상", "최대", "최신", "제일", "완벽", "압도", "역대", "무조건", "반드시", "확실", "완전", "즉시", "효과", "효능", "치료", "치유", "개선", "완치", "보장", "저렴", "가성비", "비싼", "할인",
          "협찬", "제공받", "원고료", "체험단", "광고", "지원받", "소정의", "써 보니", "써봤", "써 봤", "사용해 보니", "다녀왔", "구매했", "샀어요", "직접 써", "직접 사용", "직접 먹", "직접 가", "올해", "작년", "내년",
          "지난해", "어제", "오늘", "요즘", "다양한", "다양하게", "솔직", "추천", "인기", "유명",
          # 독립 검증 M5 로 더한 낱말 — 효능(예방·완화·호전·회복·해소)·단정(누구나·항상·언제나·전혀·결코·절대)·순위(best·top·베스트·넘버원)·의료·금융·법률 행위(복용·섭취·투자·수익·소송)·제휴(제휴·수수료)
          "예방", "완화", "호전", "회복", "해소", "누구나", "항상", "언제나", "전혀", "결코", "절대", "best", "top", "베스트", "넘버원", "복용", "섭취", "투자", "수익", "소송", "제휴", "수수료")
SPONSOR_WORDS = ("협찬", "제공받", "원고료", "체험단", "광고비", "지원받", "소정의", "광고")
FIRST_PERSON = re.compile("(?<![가-힣])(?:제가|저는|저도|저희|우리는|우리가|내가)")
MARKDOWN_LINE = re.compile("^(?:[#>*+-]|[0-9]+[.)] |```)")
HTML_OR_MARKDOWN = re.compile("<[A-Za-z/!]|[*][*]|^#|```|[|][-]|[]][(]", re.M)


def make(topic, keyword, subs, post_type, blogs=("naver_a", "naver_b"), **fields):
    return Candidate.new(topic, keyword, blogs, sub_keywords=subs, post_type=post_type, now=NOW, **fields)


def profile(key="naver_a", **changes):
    base = {"naver_a": ("블로그 에이", "https://blog.naver.com/exampleaaa"), "naver_b": ("블로그 비", "https://blog.naver.com/examplebbb")}[key]
    return NaverProfile(key, base[0], base[1], **changes)


def channel(key="naver_a", **changes):
    base = next(item for item in channels.default_profiles() if item.key == key)
    return dataclasses.replace(base, **changes)


PROFILE_MAKERS = {
    "없음": lambda key: None, "기본": lambda key: profile(key),
    "자세히": lambda key: profile(key, tone="전문적이고 정중한 합니다체", audience="업무에 도입을 고민하는 실무자", intro_style="독자의 고민으로 시작", difficulty="실무 중심", ending_style="체크리스트로 마무리", default_tags=("정보", "생활")),
}


def body_of(candidate=None, prof=None, options=None, blog="naver_a", **kwargs):
    return db.build_body(candidate or make(*CANDIDATES[0]), prof, options, today=TODAY, blog=blog, **kwargs)


@functools.lru_cache(maxsize=1)
def matrix():
    """후보 × 프로필 × 블로그의 모든 초안 — {(후보 번호, 프로필 이름, 블로그): DraftBody}."""
    found = {}
    for number, (topic, keyword, subs, post_type) in enumerate(CANDIDATES):
        for name, maker in PROFILE_MAKERS.items():
            for blog in ("naver_a", "naver_b"):
                found[(number, name, blog)] = body_of(make(topic, keyword, subs, post_type), maker(blog), None, blog)
    return found


def expect_error(test, work, code):
    with test.assertRaises(AppError) as caught:
        work()
    test.assertEqual(caught.exception.code, code)
    return caught.exception


def words_without_inputs(body):
    """생성한 글에서 후보의 낱말(키워드·보조 키워드·대상 독자)을 뺀 것 — 낱말 검사는 틀이 만든 글에만 건다."""
    text = "".join(body.generated_texts())
    for word in sorted({body.keyword, body.topic, body.audience, *body.sub_keywords}, key=lambda word: (-len(word), word)):
        text = text.replace(word, "")
    return text


# ---- ⑤ 도우미 — 한글 낱말의 받침을 유니코드 분해로(코드의 `% 28` 식과 다른 방법) -----------------------------------------------------------------------------
def last_syllable(word):
    return [ch for ch in unicodedata.normalize("NFC", word) if "가" <= ch <= "힣"][-1]


def oracle_final(word):
    return len(unicodedata.normalize("NFD", last_syllable(word))) == 3


def oracle_rieul(word):
    decomposed = unicodedata.normalize("NFD", last_syllable(word))
    return len(decomposed) == 3 and decomposed[2] == chr(0x11AF)


ALLOMORPHS = (("은", "는"), ("이", "가"), ("을", "를"), ("과", "와"), ("으로", "로"), ("이라도", "라도"), ("이라면", "라면"), ("이에요", "예요"))


def particle_errors(text, keyword):
    """키워드 바로 뒤에 틀린 이형태 조사(받침 있는데 `는`, 없는데 `은` …)나 `은(는)` 꼴이 붙은 곳 — 없어야 한다."""
    final, rieul = oracle_final(keyword), oracle_rieul(keyword)
    errors = []
    for with_final, without_final in ALLOMORPHS:
        right = without_final if (not final or (with_final == "으로" and rieul)) else with_final
        wrong = with_final if right == without_final else without_final
        if re.search(re.escape(keyword + wrong) + "(?=[ .,?!]|$)", text):
            errors.append(f"{keyword}{wrong} (맞는 것: {right})")
        if keyword + with_final + "(" in text:
            errors.append(f"{keyword}{with_final}(…) 꼴")
    return errors


class StructureTest(unittest.TestCase):
    def test_the_thirteen_parts_are_filled_in_every_combination(self):
        self.assertEqual(len(matrix()), len(CANDIDATES) * 3 * 2)
        for key, body in matrix().items():
            with self.subTest(key=key):
                self.assertEqual(len(body.titles), 3)
                self.assertEqual(len(set(body.titles)), 3)
                self.assertIn(body.selected_title, body.titles)
                self.assertGreaterEqual(len(body.intro.paragraphs), 2)
                self.assertTrue(all(body.intro.paragraphs))
                self.assertTrue(4 <= len(body.sections) <= 6, len(body.sections))
                for section in body.sections:
                    self.assertTrue(section.heading)
                    self.assertTrue(2 <= len(section.paragraphs) <= 3, (section.heading, len(section.paragraphs)))
                self.assertGreaterEqual(len(body.cautions.paragraphs), 2)
                self.assertTrue(body.cautions.heading)
                self.assertGreaterEqual(len(body.closing.paragraphs), 2)
                self.assertTrue(body.closing.heading)
                self.assertEqual(body.core_keywords, (body.keyword,))
                self.assertTrue(body.sub_keywords)
                self.assertGreaterEqual(len(body.tags), 5)
                self.assertTrue(body.summary.endswith((".", "?")))
                self.assertTrue(body.checks)
                self.assertIsInstance(body.category, str)

    def test_the_length_is_between_1800_and_2800_characters_in_every_combination(self):
        for key, body in matrix().items():
            with self.subTest(key=key):
                self.assertGreaterEqual(body.chars, 1800)
                self.assertLessEqual(body.chars_with_spaces, 2800)
                self.assertGreaterEqual(body.chars_with_spaces, 1800)
                self.assertEqual(body.chars, len("".join(body.body_text.split())))
                self.assertEqual(body.chars_with_spaces, len(body.body_text.replace(chr(10), "")))

    def test_all_five_post_types_and_both_blogs_are_covered(self):
        self.assertEqual({body.post_type for body in matrix().values()}, set(POST_TYPES))
        self.assertEqual({body.blog for body in matrix().values()}, {"naver_a", "naver_b"})
        self.assertEqual({body.domain for body in matrix().values()} - {"generic"}, {"appliance", "pc_hw", "software", "travel", "life"})

    def test_headings_inside_one_draft_are_all_different_and_follow_the_plan_step_headings(self):
        for key, body in matrix().items():
            headings = [block.heading for block in body.blocks if block.heading]
            with self.subTest(key=key):
                self.assertEqual(len(headings), len(set(headings)))
                self.assertEqual(body.blocks[0].heading, "")
                self.assertEqual([block.kind for block in body.blocks][0], db.INTRO)
                self.assertEqual([block.kind for block in body.blocks][-2:], [db.CAUTIONS, db.CLOSING])
        number = 1                                                                             # 무선 청소기 비교형 — 소제목은 틀의 단계 머리말 그대로다
        body = matrix()[(number, "기본", "naver_a")]
        steps = [lib_step for lib_step in pt.TEMPLATES[COMPARE][:5]]
        self.assertEqual([section.heading for section in body.sections], [step.heads[0].replace("{kw}", body.keyword) for step in steps])

    def test_the_blocks_are_in_order_and_the_texts_are_built_from_them(self):
        body = matrix()[(0, "기본", "naver_a")]
        self.assertEqual(db.render_body(body.blocks), body.body_text)
        self.assertEqual(body.plain_text, body.selected_title + chr(10) * 2 + body.body_text)
        self.assertEqual(body.title_text, body.selected_title)
        self.assertEqual(body.tags_text, " ".join("#" + tag for tag in body.tags))
        self.assertEqual(body.sections, tuple(block for block in body.blocks if block.kind == db.SECTION))
        self.assertEqual((body.cautions.kind, body.closing.kind), (db.CAUTIONS, db.CLOSING))

    def test_a_body_is_a_frozen_value_and_to_dict_is_json_that_round_trips(self):
        body = matrix()[(0, "기본", "naver_a")]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            body.keyword = "다른 말"
        data = json.loads(json.dumps(body.to_dict(), ensure_ascii=False))
        self.assertEqual(data["plain_text"], body.plain_text)
        self.assertEqual(data["titles"], list(body.titles))
        self.assertEqual(len(data["blocks"]), len(body.blocks))
        self.assertEqual(set(data), {"blog", "keyword", "topic", "post_type", "style", "domain", "audience", "titles", "selected_title", "blocks", "core_keywords", "sub_keywords", "tags", "category", "summary", "checks",
                                     "title_text", "body_text", "plain_text", "tags_text", "chars", "chars_with_spaces", "used", "sponsor_slot", "sensitive", "dropped", "replaced"})

    def test_titles_tags_and_the_safe_replacement_are_the_plans(self):
        for number, (topic, keyword, subs, post_type) in enumerate(CANDIDATES):
            plan = dp.build_plan(make(topic, keyword, subs, post_type), None, None, today=TODAY, blog="naver_a")
            body = matrix()[(number, "없음", "naver_a")]
            with self.subTest(keyword=keyword):
                self.assertEqual(body.titles, plan.titles)
                self.assertEqual(body.post_type, plan.post_type)
                self.assertEqual(body.keyword, plan.keyword)
                self.assertEqual(body.replaced, plan.replaced)
                self.assertEqual(body.tags[:len(plan.tags)], plan.tags)
                for text in plan.checks:
                    if not text.startswith(db.PLAN_GENERIC_CHECKS):
                        self.assertIn(text, body.checks)

    def test_building_a_body_does_not_change_what_the_plan_returns(self):
        candidate = make(*CANDIDATES[1])
        before = dp.build_plan(candidate, profile(), None, today=TODAY, blog="naver_a").to_dict()
        body_of(candidate, profile())
        self.assertEqual(dp.build_plan(candidate, profile(), None, today=TODAY, blog="naver_a").to_dict(), before)


class DeterminismTest(unittest.TestCase):
    def test_the_same_input_twice_is_the_same_body_down_to_the_character(self):
        for number in (0, 3, 6, 9, 12):
            topic, keyword, subs, post_type = CANDIDATES[number]
            first = body_of(make(topic, keyword, subs, post_type), profile())
            second = body_of(make(topic, keyword, subs, post_type), profile())
            with self.subTest(keyword=keyword):
                self.assertEqual(first, second)
                self.assertEqual(first.plain_text, second.plain_text)

    def test_different_keywords_pick_different_variants_so_two_posts_do_not_read_the_same(self):
        first = body_of(make("A 주제", "무선 청소기", (), INFO)).body_text.replace("무선 청소기", "◇")
        second = body_of(make("B 주제", "제습기", (), INFO)).body_text.replace("제습기", "◇")
        self.assertNotEqual(first, second)

    def test_two_blogs_get_different_text_for_the_same_candidate(self):
        for number in (0, 1, 5, 7):
            topic, keyword, subs, post_type = CANDIDATES[number]
            a = matrix()[(number, "없음", "naver_a")]
            b = matrix()[(number, "없음", "naver_b")]
            with self.subTest(keyword=keyword):
                self.assertNotEqual(a.body_text, b.body_text)
                self.assertNotEqual(a.titles, b.titles)

    def test_the_result_does_not_depend_on_the_python_hash_seed(self):
        lines = ("import sys, hashlib", "sys.path.insert(0, sys.argv[1])", "from chanceblog_desktop.content import draft_body as db", "from chanceblog_desktop.content.candidates import Candidate",
                 "c = Candidate('abcd', '보일러 점검 순서', '보일러 점검', ('naver_a',), sub_keywords=('난방비', '보일러 청소'), created_at='2026-11-02T03:00:00Z', updated_at='2026-11-02T03:00:00Z')",
                 "b = db.build_body(c, None, None, today='2026-11-07', blog='naver_a')", "print(hashlib.sha256((b.plain_text + b.tags_text + ''.join(b.checks)).encode('utf-8')).hexdigest())")
        code = chr(10).join(lines)
        hashes = set()
        for seed in ("0", "1", "424242"):
            env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
            done = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(ROOT / "src")], capture_output=True, text=True, env=env, timeout=120, encoding="utf-8")
            self.assertEqual(done.returncode, 0, done.stderr[-500:])
            hashes.add(done.stdout.strip())
        self.assertEqual(len(hashes), 1, hashes)


class NoFabricationTest(unittest.TestCase):
    def test_check_finds_nothing_in_any_combination(self):
        for key, body in matrix().items():
            with self.subTest(key=key):
                self.assertEqual(claims.find_claims(body.plain_text), ())
                self.assertEqual(claims.find_claims(list(body.generated_texts())), ())

    def test_check_finds_no_violation_even_when_the_keyword_has_digits_or_latin_letters(self):
        for keyword in ("RTX 4060", "Windows 11 설치", "GPT-4o", "C++", "Wi-Fi 6E 공유기", "2026 겨울 난방", "AI"):
            for post_type in POST_TYPES:
                for blog in ("naver_a", "naver_b"):
                    body = body_of(make(f"{keyword} 정리", keyword, (), post_type, blogs=("naver_a", "naver_b")), None, None, blog)
                    with self.subTest(keyword=keyword, type=post_type, blog=blog):
                        self.assertEqual([item for item in claims.find_claims(body.plain_text) if claims.is_violation(item.category)], [])
                        self.assertTrue(body.chars_with_spaces <= 2800 and body.chars >= 1800)

    def test_no_banned_word_pattern_digit_or_first_person_in_the_text_the_templates_wrote(self):
        digit = re.compile("[0-9]")
        for key, body in matrix().items():
            text = words_without_inputs(body)
            with self.subTest(key=key):
                self.assertIsNone(digit.search(text))
                self.assertIsNone(FIRST_PERSON.search(text))
                for word in BANNED:
                    self.assertNotIn(word, text, word)
                self.assertNotIn(chr(92), body.plain_text)

    def test_no_sponsor_word_in_the_body_even_for_a_sponsor_candidate(self):
        for number in (1, 2, 5, 6, 7):
            topic, keyword, subs, post_type = CANDIDATES[number]
            for focus in (("small_appliance",), ("pc_parts", "pc_peripheral"), ("ai_service",), ("lodging_travel",), ("small_appliance", "pc_parts", "ai_service", "lodging_travel", "work_automation")):
                for blog in ("naver_a", "naver_b"):
                    body = body_of(make(topic, keyword, subs, post_type), None, None, blog, channel=channel(blog, monetization_focus=focus))
                    text = words_without_inputs(body) + body.body_text
                    with self.subTest(keyword=keyword, focus=focus, blog=blog):
                        for word in SPONSOR_WORDS:
                            self.assertNotIn(word, text, word)

    def test_a_sponsor_candidate_gets_only_a_place_to_say_so_in_the_checks(self):
        body = body_of(make(*CANDIDATES[1]), None, None, "naver_a", channel=channel("naver_a", monetization_focus=("small_appliance",)))
        self.assertTrue(body.sponsor_slot)
        self.assertEqual(body.domain, "appliance")
        notes = [text for text in body.checks if "협찬" in text]
        self.assertEqual(len(notes), 1)
        self.assertIn("넣지 않았고", notes[0])
        self.assertNotIn("협찬", body.plain_text)
        same = body_of(make(*CANDIDATES[1]), None, None, "naver_a", channel=channel("naver_a", monetization_focus=("pc_parts",)))        # 후보의 분야가 협찬 가능 분야에 없으면 안내도 없다
        self.assertFalse(same.sponsor_slot)
        self.assertEqual([text for text in same.checks if "협찬" in text], [])
        none = body_of(make(*CANDIDATES[1]), None, None, "naver_a", channel=channel("naver_a", monetization_focus=()))
        self.assertFalse(none.sponsor_slot)
        self.assertFalse(body_of(make(*CANDIDATES[1])).sponsor_slot)

    def test_a_sensitive_topic_gets_the_expert_paragraph_and_the_check_and_no_advice(self):
        for keyword, kind in (("영양제 고르는 기준", "health"), ("주식 투자 기초", "finance"), ("전세 계약서 확인", "legal")):
            body = body_of(make(f"{keyword} 안내", keyword, (), INFO))
            with self.subTest(keyword=keyword):
                self.assertEqual(body.sensitive, kind)
                self.assertTrue(any("전문가" in paragraph or "기관" in paragraph for paragraph in body.cautions.paragraphs))
                self.assertTrue(any("일반 정보만 다뤘습니다" in text for text in body.checks))
                self.assertEqual(claims.find_claims(body.plain_text), ())
                for word in ("효과", "효능", "치료", "수익", "확정", "승소"):
                    self.assertNotIn(word, words_without_inputs(body))
        normal = body_of(make(*CANDIDATES[10]))
        self.assertIsNone(normal.sensitive)
        self.assertFalse(any("일반 정보만 다뤘습니다" in text for text in normal.checks))

    def test_the_text_has_no_blog_name_id_alias_or_blog_ref_from_either_profile(self):
        tokens = ("표시이름토큰", "별칭토큰", "refidtoken1", "역할토큰", "소개토큰", "exampleaaa", "블로그 에이", "블로그 비")
        for blog in ("naver_a", "naver_b"):
            other = "naver_b" if blog == "naver_a" else "naver_a"
            chan = channel(blog, display_name="표시이름토큰", alias="별칭토큰", blog_ref="refidtoken1", channel_role="역할토큰", intro="소개토큰 한 줄 소개", main_topics=("주제토큰",), tone="친근한", audience="채널 독자")
            body = body_of(make(*CANDIDATES[1], blogs=("naver_a", "naver_b")), profile(blog, topic="주제토큰 설명"), None, blog, channel=chan)
            dump = json.dumps(body.to_dict(), ensure_ascii=False)
            with self.subTest(blog=blog):
                for token in tokens:
                    self.assertNotIn(token, dump, token)
                self.assertNotIn(other, dump)

    def test_the_experience_words_never_appear_without_an_experience_input_even_for_review_candidates(self):
        for number, (topic, keyword, subs, post_type) in enumerate(CANDIDATES):
            for name in PROFILE_MAKERS:
                body = matrix()[(number, name, "naver_a")]
                with self.subTest(keyword=keyword, profile=name):
                    self.assertNotIn(db.EXPERIENCE, [block.kind for block in body.blocks])
                    self.assertEqual(body.used, ())
                    if keyword in PREMISE_KEYWORDS:
                        self.assertIsNotNone(body.replaced)
                        for word in ("후기", "체험", "방문기", "써봤", "사용기"):
                            self.assertNotIn(word, body.plain_text)
                            self.assertNotIn(word, body.keyword)


class GuardLayerTest(unittest.TestCase):
    """지어내지 않기는 겹겹이다 — ① 문장마다 검사(위반이면 다른 변형으로, 없으면 뺀다) ② 마지막 관문(글 전체의 `find_violations` — 걸리면 만들지 않는다) ③ 비밀 모양 관문. 서로 가려 주는 겹이라 평소 글만 보면 한 겹이
    꺼져도 티가 나지 않는다(변이 점검에서 드러났다) — 그래서 겹마다 따로 시험한다. 마무리 틀(`body_blocks.CLOSING_FIRST`)을 시험하는 동안만 바꿔 일부러 나쁜 문장을 끼워 본다."""
    BAD = "직접 써 보니 아주 좋았어요."
    GOOD = "{kw:은/는} 이 순서로 확인하면 돼요."
    LAST = "마지막 확인은 공식 안내로 해 주세요."
    KEYWORDS = tuple(f"{head} {tail}" for head in ("제습기", "공유기", "정수기", "노트북 거치대", "책상 조명", "캠핑 의자") for tail in ("고르기", "관리법", "비교", "점검"))

    def closing(self, slots):
        return mock.patch.dict(blk.CLOSING_FIRST, {INFO: slots})

    def build(self, keyword):
        return body_of(make(f"{keyword} 정리", keyword, (), INFO))

    def test_the_bad_sentence_really_is_a_violation_and_the_good_one_is_clean(self):
        self.assertTrue(claims.find_violations([self.BAD]))
        self.assertEqual(claims.find_claims([bl.fill(self.GOOD, {"kw": "제습기"})]), ())

    def test_a_violating_variant_is_never_chosen_while_another_variant_is_usable(self):
        with self.closing(((self.BAD, self.GOOD), self.LAST)):
            for keyword in self.KEYWORDS:
                body = self.build(keyword)
                with self.subTest(keyword=keyword):
                    self.assertNotIn(self.BAD, body.plain_text)
                    self.assertIn(bl.fill(self.GOOD, {"kw": body.keyword}), body.closing.paragraphs[0])
                    self.assertEqual(body.dropped, 0)

    def test_when_every_variant_of_a_sentence_is_bad_the_sentence_is_left_out_and_the_checks_say_so(self):
        with self.closing(((self.BAD,), self.LAST)):
            body = self.build("제습기 고르기")
        self.assertNotIn(self.BAD, body.plain_text)
        self.assertGreaterEqual(body.dropped, 1)
        self.assertTrue(any("쓰지 못했습니다" in text for text in body.checks))
        self.assertIn(self.LAST, body.closing.paragraphs[0])

    def test_the_last_gate_stops_a_violation_the_sentence_check_let_through(self):
        with mock.patch.object(db._Writer, "passes", lambda self, text: True), self.closing(((self.BAD,),)):
            error = expect_error(self, lambda: self.build("제습기 고르기"), "CONTENT_INVALID")
        self.assertNotIn(self.BAD, str(error))

    def test_the_last_gate_also_stops_a_secret_shaped_text_in_the_body_and_never_repeats_it(self):
        with self.closing((("접근 값은 " + KEY + " 입니다.",),)):
            error = expect_error(self, lambda: self.build("제습기 고르기"), "CONTENT_INVALID")
        self.assertNotIn(KEY, str(error))
        self.assertNotIn(KEY, error.detail)

    def test_the_gate_function_itself_accepts_a_normal_body_and_rejects_a_bad_summary_and_a_leaked_secret(self):
        body = body_of()
        self.assertIsNone(db._final_guard(body))
        expect_error(self, lambda: db._final_guard(dataclasses.replace(body, summary=self.BAD)), "CONTENT_INVALID")
        expect_error(self, lambda: db._final_guard(dataclasses.replace(body, plain_text=body.plain_text + " " + KEY)), "CONTENT_INVALID")

    def test_the_gate_runs_once_for_every_body_and_gets_the_returned_body(self):
        with mock.patch.object(db, "_final_guard", wraps=db._final_guard) as spy:
            body = body_of()
        spy.assert_called_once()
        self.assertIs(spy.call_args.args[0], body)

    def test_an_audience_that_itself_says_what_the_writer_did_is_left_out_of_its_sentence_and_the_body_is_still_built(self):
        """입력한 독자 문구가 경험을 단정하는 말이면(예: '이미 구매했다고 말한 분') 그 문장만 빼고 글은 만든다 — 문장 검사의 '위반은 언제나 막는다' 를 입력의 낱말이 든 문장에서도 확인한다
        (검증자의 변이 M01 — 위반 거절을 지워도 평소 글에서는 결과가 같아 살아남았다. 거절이 꺼지면 그 문장이 들어가고 마지막 관문이 글 전체를 거절한다)."""
        body = body_of(make(*CANDIDATES[1]), None, DraftOptions(audience="이미 구매했다고 말한 분"))
        self.assertNotIn("구매했다", body.plain_text)
        self.assertGreaterEqual(body.dropped, 1)
        self.assertTrue(any("쓰지 못했습니다" in text for text in body.checks))
        self.assertEqual(claims.find_violations(list(body.generated_texts())), ())
        fine = body_of(make(*CANDIDATES[1]), None, DraftOptions(audience="가격 비교가 필요한 분"))
        self.assertIn("가격 비교가 필요한 분", fine.plain_text)                                        # 걸리지 않는 독자 문구는 그대로 쓰인다

    def test_a_digit_keyword_does_not_run_into_the_next_word_and_make_a_price_date_or_statistic_claim(self):
        """'RTX 4060' 뒤에 '원인' 이 오면 띄어쓰기를 지운 글에서 '4060원' 으로 읽혀 가격 주장이 된다 — 틀로 만든 소제목·문단·한 줄 요약에는 후보의 글에서 온 낱말 말고는 확인 권장 낱말도 없다(제목은 작성 기반의 것이라 뺀다)."""
        for keyword in ("RTX 4060", "Windows 11 설치", "GPT-4o", "Wi-Fi 6E 공유기", "2026 겨울 난방", "아이폰 15 케이스", "24시간 편의점", "에어컨 2대"):
            for post_type in POST_TYPES:
                for blog in ("naver_a", "naver_b"):                                    # 소제목 틀은 블로그마다 말씨가 달라 '…: RTX 4060 원인' 꼴은 네이버 B 에만 나온다
                    body = body_of(make(f"{keyword} 정리", keyword, (), post_type), None, None, blog)
                    own = claims.flat(" ".join((body.keyword, body.topic, body.audience)))                 # 후보가 준 글만(보조 키워드는 생성기가 키워드 + 꼬리로 만든 것이라 뺀다)
                    texts = [text for block in body.blocks for text in (block.heading, *block.paragraphs) if text] + [body.summary]
                    with self.subTest(keyword=keyword, type=post_type, blog=blog):
                        for text in texts:
                            for sentence in claims.split_sentences(text):
                                for claim in claims.find_claims([sentence]):
                                    self.assertIn(claim.word, own, sentence)


class UserInputTest(unittest.TestCase):
    FULL = DraftOptions(message="전하고 싶은 말은 이거예요. 구체적으로는 두 가지랍니다.", experience="지난달부터 써 왔고 배터리는 하루 종일 갔습니다. 소음은 조용했어요.", opinion="개인적으로는 필터 관리가 가장 중요하다고 생각해요.",
                        must_include=("반드시 넣을 첫 문장입니다.", "두 번째 문장도 넣어 주세요."), exclude=("광고",), audience="신혼부부", title_direction="질문형으로", urls=("https://example.com/a", "https://example.com/b"),
                        price_date=("2026-11-01 기준 12만 원", "다음 달 말까지"), conclusion="결론은 필터부터 확인하라는 것입니다.")

    def build(self, options=None, **kwargs):
        return body_of(make(*CANDIDATES[1]), None, options or self.FULL, "naver_a", **kwargs)

    def test_every_user_text_appears_in_the_body_verbatim(self):
        body = self.build()
        text = body.body_text
        for given in (self.FULL.message, self.FULL.experience, self.FULL.opinion, self.FULL.conclusion, *self.FULL.must_include, *self.FULL.urls):
            self.assertIn(given, text, given)
        for item in self.FULL.price_date:
            self.assertIn(item, text)
        self.assertEqual(set(body.used), {"message", "experience", "opinion", "must_include", "price_date", "conclusion", "urls"})
        self.assertTrue(body.user_paragraphs())

    def test_user_texts_come_first_in_their_blocks_and_the_experience_has_its_own_section(self):
        body = self.build()
        experience = next(block for block in body.blocks if block.kind == db.EXPERIENCE)
        self.assertEqual(experience.paragraphs, (self.FULL.experience,))
        self.assertEqual(experience.generated, (False,))
        self.assertTrue(experience.heading)
        self.assertGreaterEqual(len(body.sections), 4)
        self.assertLessEqual(len(body.sections), 6)
        closing = body.closing
        self.assertEqual(closing.paragraphs[:2], (self.FULL.opinion, self.FULL.conclusion))
        self.assertEqual(closing.generated[:2], (False, False))
        intro = body.intro
        self.assertEqual(intro.paragraphs[-1], self.FULL.message)
        self.assertEqual(body.blocks[-1].kind, db.REFERENCES)
        self.assertEqual(body.blocks[-1].paragraphs, self.FULL.urls)

    def test_the_audience_the_user_gave_beats_the_channel_the_profile_and_the_default(self):
        chan = channel("naver_a", audience="채널 독자")
        prof = profile("naver_a", audience="프로필 독자")
        cases = ((DraftOptions(audience="입력 독자"), chan, prof, "입력 독자"), (DraftOptions(), chan, prof, "채널 독자"), (DraftOptions(), None, prof, "프로필 독자"),
                 (DraftOptions(), None, None, dp.build_plan(make(*CANDIDATES[1]), None, None, today=TODAY, blog="naver_a").audience))
        for options, channel_profile, naver, wanted in cases:
            body = body_of(make(*CANDIDATES[1]), naver, options, "naver_a", channel=channel_profile)
            with self.subTest(wanted=wanted):
                self.assertEqual(body.audience, wanted)
        given = body_of(make(*CANDIDATES[1]), prof, DraftOptions(audience="입력 독자"), "naver_a", channel=chan)
        self.assertTrue(any("입력 독자" in paragraph for paragraph in given.intro.paragraphs))                 # 사용자가 입력한 독자는 도입부에 꼭 들어간다

    def test_the_audience_sentence_the_user_gave_stays_when_the_user_text_is_already_long_enough_to_need_no_optional_sentence(self):
        """사용자가 쓴 독자 문장은 필수 문장이라 사용자 글이 길어 선택 문장이 하나도 켜지지 않는 글에서도 남는다(설명 난이도 문장은 길이가 모자랄 때만 켜진다)."""
        long_inputs = DraftOptions(audience="신혼부부", message=("전하고 싶은 내용을 길게 적은 문장이에요. " * 20).strip()[:490],
                                   must_include=tuple(f"{number}번째 문장입니다. " + ("확인한 내용을 그대로 적은 문장이에요. " * 8).strip() for number in range(1, 11)))
        # 사용자 글만으로 공백 뺀 2,000자쯤 — 틀 문장을 보태지 않아도 하한(1,880자)을 넘는다(같은 문장은 입력 단계에서 하나로 합쳐지므로 서로 다르게 쓴다)
        for topic, keyword, subs, post_type in CANDIDATES:
            body = body_of(make(topic, keyword, subs, post_type), None, long_inputs)
            with self.subTest(keyword=keyword):
                self.assertGreaterEqual(body.chars, 1800 + 100)                   # 선택 문장을 켜서 채운 것이 아니라 사용자 글이 길어서 넘는다
                self.assertIn("신혼부부", " ".join(body.intro.paragraphs))

    def test_a_user_experience_adds_one_section_and_keeps_the_count_within_six_for_every_type(self):
        for number in (0, 1, 3, 5, 7):
            topic, keyword, subs, post_type = CANDIDATES[number]
            plain = body_of(make(topic, keyword, subs, post_type))
            with_experience = body_of(make(topic, keyword, subs, post_type), None, DraftOptions(experience="지난달부터 이용했어요."))
            with self.subTest(keyword=keyword):
                self.assertEqual(len([b for b in with_experience.blocks if b.kind == db.EXPERIENCE]), 1)
                self.assertTrue(4 <= len(with_experience.sections) <= 6)
                self.assertLessEqual(len(with_experience.sections), max(len(plain.sections), 6))

    def test_the_check_finds_a_violation_only_in_the_users_own_sentences_and_none_when_they_are_exempted(self):
        body = self.build()
        user = " ".join(self.FULL.user_texts())
        found = claims.find_violations(body.plain_text, experience_given=True, user_sentences=user)
        self.assertEqual(found, ())
        raw = claims.find_violations(body.plain_text)
        self.assertTrue(raw)                                                                          # 사용자 글(경험)이 걸리는 것은 맞다 — 예외를 주면 사라진다
        generated = claims.find_violations(list(body.generated_texts()))
        self.assertEqual(generated, ())                                                              # 틀로 만든 글은 예외 없이도 0건

    def test_without_an_experience_input_the_same_text_is_not_exempted_and_the_checks_say_so(self):
        options = DraftOptions(message="지난달에 직접 써 봤더니 좋았어요.")
        body = self.build(options)
        self.assertIn(options.message, body.body_text)
        self.assertTrue(any("직접 겪은 일을 말하는 표현" in text for text in body.checks))
        self.assertEqual(claims.find_violations(list(body.generated_texts())), ())

    def test_long_user_texts_are_split_at_sentence_ends_and_nothing_is_lost(self):
        sentence = "이 문장은 사용자가 입력한 경험을 설명하는 한 줄이에요."
        experience = " ".join([sentence] * 18)[:1000]
        body = self.build(DraftOptions(experience=experience))
        block = next(item for item in body.blocks if item.kind == db.EXPERIENCE)
        self.assertGreater(len(block.paragraphs), 1)
        self.assertTrue(all(len(text) <= db.MAX_PARAGRAPH for text in block.paragraphs))
        self.assertEqual(" ".join(block.paragraphs), experience.strip())

    def test_the_price_and_date_paragraph_keeps_each_given_item_and_a_reminder(self):
        body = self.build(DraftOptions(price_date=("값 하나", "날짜 하나.")))
        paragraph = next(text for block in body.blocks for text in block.paragraphs if "값 하나" in text)
        self.assertIn("값 하나.", paragraph)
        self.assertIn("날짜 하나.", paragraph)
        self.assertIn("한 번 더 확인해 주세요", paragraph)

    def test_a_length_the_user_asked_for_does_not_make_the_text_longer_but_the_checks_say_so(self):
        long = self.build(DraftOptions(length="4000+"))
        short = self.build(DraftOptions(length="800-1000"))
        plain = self.build(DraftOptions())
        self.assertEqual(long.body_text, plain.body_text)
        self.assertTrue(any("보다 짧은 기본 글" in text for text in long.checks))
        self.assertTrue(any("보다 깁니다" in text for text in short.checks))
        self.assertFalse(any("원하시는 글 길이" in text for text in plain.checks))
        profile_long = body_of(make(*CANDIDATES[1]), profile("naver_a", min_chars=3000, max_chars=4000), None, "naver_a")
        self.assertTrue(any("보다 짧은 기본 글" in text for text in profile_long.checks))

    def test_the_title_direction_and_the_conclusion_shape_the_titles_like_the_plan(self):
        body = self.build(DraftOptions(title_direction="질문형으로"))
        plan = dp.build_plan(make(*CANDIDATES[1]), None, DraftOptions(title_direction="질문형으로"), today=TODAY, blog="naver_a")
        self.assertEqual(body.titles, plan.titles)


class ExclusionTest(unittest.TestCase):
    def test_excluded_words_never_appear_in_what_the_templates_wrote_and_the_count_is_in_the_checks(self):
        for words in (("가격",), ("공식",), ("순서", "메모"), ("목적", "표시")):
            body = body_of(make(*CANDIDATES[0]), None, DraftOptions(exclude=words))
            text = words_without_inputs(body)
            with self.subTest(words=words):
                for word in words:
                    self.assertNotIn(word, text, word)
                self.assertEqual(claims.find_claims(body.plain_text), ())
                if body.dropped:
                    self.assertTrue(any(f"문장 {body.dropped}개" in note for note in body.checks))
                self.assertGreaterEqual(len(body.sections), 4)

    def test_the_profile_excluded_topics_and_the_forbidden_phrases_work_like_the_users_exclusions(self):
        cases = (dict(prof=profile("naver_a", excluded_topics=("공식",)), word="공식"), dict(prof=profile("naver_a", forbidden_phrases=("공식",)), word="공식"))
        for case in cases:
            body = body_of(make(*CANDIDATES[0]), case["prof"], None, "naver_a")
            with self.subTest(case=case["word"]):
                self.assertNotIn(case["word"], words_without_inputs(body))
                self.assertGreater(body.dropped, 0)

    def test_the_channel_exclude_keywords_field_is_not_read_because_the_screen_says_it_is_saved_only(self):
        """채널 프로필의 제외 키워드 칸은 화면이 '지금은 저장만 된다' 고 말하는 칸이다(D-241·`test_ui_blogs_topic`) — 본문 생성기는 그 칸을 읽지 않는다. 읽게 하려면 화면 문구와 이 시험을 함께 고친다(D-262·D-269)."""
        plain = body_of(make(*CANDIDATES[0]), None, None, "naver_a", channel=channel("naver_a"))
        with_field = body_of(make(*CANDIDATES[0]), None, None, "naver_a", channel=channel("naver_a", exclude_keywords=("공식",)))
        self.assertIn("공식", with_field.body_text)
        self.assertEqual(with_field.plain_text, plain.plain_text)
        self.assertEqual(with_field.dropped, 0)

    def test_a_blocked_step_name_removes_the_whole_section(self):
        plain = body_of(make(*CANDIDATES[1]))
        blocked = body_of(make(*CANDIDATES[1]), None, DraftOptions(exclude=("공통 기준",)))
        self.assertEqual(len(blocked.sections), len(plain.sections) - 1)
        self.assertTrue(all("공통 기준" not in block.heading for block in blocked.blocks))

    def test_a_word_only_a_heading_template_has_can_be_excluded_and_then_no_heading_has_it(self):
        """소제목 틀에만 있는 낱말(단계 이름에는 없는 낱말)을 제외하면 그 소제목 틀은 쓰이지 않고 다른 틀이나 단계 이름이 쓰인다."""
        tokens = set()
        for post_type in POST_TYPES:
            for key in lib.BODY_STEPS[post_type]:
                step = lib.step_of(post_type, key)
                for head in step.heads:
                    words = [word for word in re.sub("[,:?]", " ", head.replace("{kw}", "")).split() if word not in step.name]
                    if words:
                        tokens.add((post_type, words[0]))
        self.assertGreaterEqual(len(tokens), 35)
        keywords = {INFO: CANDIDATES[0], COMPARE: CANDIDATES[1], TROUBLE: CANDIDATES[3], PRODUCT: CANDIDATES[5], PLACE: CANDIDATES[7]}
        for post_type, token in sorted(tokens):
            topic, keyword, subs, _kind = keywords[post_type]
            for blog in ("naver_a", "naver_b"):
                body = body_of(make(topic, keyword, subs, post_type), None, DraftOptions(exclude=(token,)), blog)
                with self.subTest(type=post_type, word=token, blog=blog):
                    self.assertNotIn(token, " ".join(block.heading for block in body.blocks))

    def test_when_every_form_of_a_heading_is_excluded_the_keyword_stands_in_and_the_checks_say_so(self):
        """마무리 소제목은 두 틀과 이름('핵심 정리')이 모두 '정리' 를 가지고 있다 — 그 낱말을 제외하면 소제목에도 남지 않아야 하므로 키워드로 대신하고 확인 권장에 알린다."""
        body = body_of(make(*CANDIDATES[0]), None, DraftOptions(exclude=("정리",)))
        self.assertEqual(body.closing.heading, body.keyword)
        self.assertTrue(any("소제목 1개를 키워드로 대신했습니다" in text for text in body.checks))
        plain = body_of(make(*CANDIDATES[0]))
        self.assertIn("정리", plain.closing.heading)
        self.assertFalse(any("키워드로 대신" in text for text in plain.checks))

    def test_the_fixed_price_sentences_and_the_references_heading_follow_the_exclusion_too(self):
        body = body_of(make(*CANDIDATES[0]), None, DraftOptions(exclude=("확인한", "확인해", "자료"), urls=("https://example.com/a",), price_date=("12만 원",)))
        self.assertEqual(next(block for block in body.blocks if block.kind == db.REFERENCES).heading, body.keyword)
        self.assertEqual(next(text for text in body.user_paragraphs() if "12만 원" in text), "12만 원.")
        plain = body_of(make(*CANDIDATES[0]), None, DraftOptions(urls=("https://example.com/a",), price_date=("12만 원",)))
        self.assertEqual(next(block for block in plain.blocks if block.kind == db.REFERENCES).heading, db.REFERENCES_HEADING)
        price = next(text for text in plain.user_paragraphs() if "12만 원" in text)
        self.assertTrue(price.startswith(db.PRICE_LEAD) and price.endswith(db.PRICE_TAIL), price)

    def test_the_one_line_summary_falls_back_to_the_keyword_alone_when_its_templates_and_the_fallback_word_are_excluded(self):
        with mock.patch.dict(blk.SUMMARY, {INFO: ("{kw:은/는} 정리가 핵심이에요.", "{kw:은/는} 정리부터 시작해요.")}):
            plain = body_of(make(*CANDIDATES[0]))
            blocked = body_of(make(*CANDIDATES[0]), None, DraftOptions(exclude=("정리",)))
        self.assertIn("정리", plain.summary)
        self.assertEqual(blocked.summary, f"{blocked.keyword}.")

    def test_an_extreme_exclusion_still_returns_a_short_body_and_says_so(self):
        body = body_of(make(*CANDIDATES[1]), None, DraftOptions(exclude=("비교", "기준", "확인", "정보", "항목")))
        self.assertTrue(body.plain_text)
        self.assertLess(body.chars, 1800)
        self.assertTrue(any("소제목이" in note and "뿐입니다" in note for note in body.checks))
        self.assertEqual(claims.find_violations(list(body.generated_texts())), ())


class ParticleTest(unittest.TestCase):
    NOUNS = ("책상", "의자", "노트북", "키보드", "마우스", "모니터", "제습기", "청소기", "공기청정기", "에어프라이어", "로봇청소기", "냉장고", "세탁기", "건조기", "선풍기", "전기장판", "보일러", "숙소", "펜션",
             "호텔", "캠핑", "카페", "맛집", "도서관", "공원", "여행", "독서", "습관", "분리수거", "수납", "청소", "환기", "곰팡이", "결로", "누수", "배수", "절약", "난방", "요금제", "구독", "계정", "자동화", "매크로",
             "설치", "설정", "업데이트", "백업", "보안", "연동", "저장소", "메모", "일정", "시간", "예산", "생활비", "운동", "수면", "식단", "비타민", "영양제", "보험", "대출", "계약", "특허", "이사", "인테리어",
             "조명", "커튼", "침대", "소파", "서랍", "신발", "가방", "지갑", "시계", "안경", "우산", "텀블러", "물병", "도시락", "간식")
    PREFIXES = ("", "무선 ", "소형 ", "가정용 ")
    SUFFIXES = ("방법", "정리", "비교", "가이드", "선택", "안내")

    def keywords(self):
        """낱말 78개 × (그대로 · 앞말 · 뒷말 · 앞말 + 뒷말) — 뒷말이 받침 있는 것(방법·선택)과 없는 것(정리·비교·가이드·안내)을 돌려 가며 붙여 끝 글자의 받침이 골고루 나온다."""
        found = []
        for index, noun in enumerate(self.NOUNS):
            found += [noun, f"{self.PREFIXES[index % 4]}{noun}".strip(), f"{noun} {self.SUFFIXES[index % 6]}", f"{self.PREFIXES[(index + 1) % 4]}{noun} {self.SUFFIXES[(index + 3) % 6]}".strip()]
        return list(dict.fromkeys(found))

    def test_the_corpus_has_over_a_hundred_words_with_and_without_a_final_consonant(self):
        words = self.keywords()
        self.assertGreaterEqual(len(words), 240)
        self.assertGreaterEqual(len([word for word in words if oracle_final(word)]), 100)
        self.assertGreaterEqual(len([word for word in words if not oracle_final(word)]), 100)

    def test_every_keyword_mention_in_240_drafts_has_the_right_particle(self):
        corpus = self.keywords()
        finals = [oracle_final(word) for word in corpus]
        picked = [word for word, final in zip(corpus, finals) if final][:120] + [word for word, final in zip(corpus, finals) if not final][:120]
        self.assertEqual(len(picked), 240)
        for index, keyword in enumerate(picked):
            post_type = POST_TYPES[index % 5]
            body = body_of(make(f"{keyword} 안내", keyword, (), post_type, blogs=("naver_a", "naver_b")), None, None, ("naver_a", "naver_b")[index % 2])
            with self.subTest(keyword=keyword, type=post_type):
                self.assertEqual(particle_errors(body.plain_text, body.keyword), [])
                self.assertIn(body.keyword, body.plain_text)

    def test_an_unreadable_end_gets_the_both_forms_never_a_wrong_one(self):
        body = body_of(make("C++ 안내", "C++", (), PRODUCT))
        self.assertNotIn("C++는", body.plain_text)
        self.assertNotIn("C++가", body.plain_text)
        self.assertIn("C++을(를)", body.plain_text)

    def test_digits_and_latin_ends_get_the_right_particle_too(self):
        for keyword, final in (("아이폰 15", False), ("RTX 4060", True), ("Windows 11", True), ("GPU", False), ("LLM", True), ("Notion", True), ("Gemini", False), ("Git", True)):
            body = body_of(make(f"{keyword} 안내", keyword, (), PRODUCT))
            with self.subTest(keyword=keyword):
                self.assertIn(keyword + ("을" if final else "를"), body.plain_text)
                self.assertNotIn(keyword + ("를" if final else "을") + " ", body.plain_text)

    def test_the_audience_and_the_sub_keywords_get_the_right_particle_too(self):
        body = body_of(make("주제", "노트북", ("메모", "독서"), COMPARE), None, DraftOptions(audience="신혼부부"))
        self.assertIn("신혼부부를", body.plain_text)
        body2 = body_of(make("주제", "노트북", ("메모", "독서"), COMPARE), None, DraftOptions(audience="초보 운전자"))
        self.assertIn("초보 운전자를", body2.plain_text)
        body3 = body_of(make("주제", "노트북", (), COMPARE), None, DraftOptions(audience="업무 담당자"))
        self.assertIn("업무 담당자를", body3.plain_text)
        body4 = body_of(make("주제", "노트북", (), COMPARE), None, DraftOptions(audience="학생"))
        self.assertIn("학생을", body4.plain_text)


class PlainTextTest(unittest.TestCase):
    def test_no_markdown_or_html_marks_and_one_blank_line_between_blocks(self):
        for key, body in matrix().items():
            lines = body.plain_text.split(chr(10))
            with self.subTest(key=key):
                self.assertFalse(body.plain_text.startswith((chr(10), " ")))
                self.assertFalse(body.plain_text.endswith((chr(10), " ")))
                self.assertNotIn(chr(10) * 3, body.plain_text)
                self.assertNotIn("  ", body.plain_text)
                self.assertNotIn(chr(9), body.plain_text)
                self.assertNotIn(chr(13), body.plain_text)
                self.assertIsNone(HTML_OR_MARKDOWN.search(body.plain_text))
                for number, line in enumerate(lines):
                    self.assertEqual(line, line.strip())
                    self.assertIsNone(MARKDOWN_LINE.match(line), line)
                    if number % 2 == 1:
                        self.assertEqual(line, "", "블록 사이에는 빈 줄 하나뿐이다")
                    else:
                        self.assertTrue(line)

    def test_the_items_are_copyable_on_their_own(self):
        for key, body in matrix().items():
            with self.subTest(key=key):
                self.assertNotIn(chr(10), body.title_text)
                self.assertNotIn(body.selected_title + chr(10) * 2, body.body_text)
                self.assertTrue(body.body_text.startswith(body.intro.paragraphs[0]))
                self.assertNotIn(chr(10), body.tags_text)
                self.assertEqual(len(body.tags_text.split(" ")), len(body.tags))
                for tag in body.tags:
                    self.assertTrue(0 < len(tag) <= db.MAX_TAG)
                    self.assertNotIn(" ", tag)
                    self.assertNotIn("#", tag)
                self.assertEqual(len(set(body.tags)), len(body.tags))
                self.assertTrue(body.summary and chr(10) not in body.summary)

    def test_headings_are_short_single_lines_and_paragraphs_end_with_a_sentence_mark(self):
        for key, body in matrix().items():
            with self.subTest(key=key):
                for block in body.blocks:
                    if block.heading:
                        self.assertLessEqual(len(block.heading), 60)
                    for text in block.paragraphs:
                        self.assertTrue(text.endswith((".", "?", "!")), text[-12:])

    def test_hapsyo_text_has_no_haeyo_ending_left(self):
        body = matrix()[(1, "자세히", "naver_a")]
        self.assertEqual(body.style, bl.STYLE_HAPSYO)
        for block in body.blocks:
            for text in block.paragraphs:
                for sentence in claims.split_sentences(text):
                    stripped = sentence.rstrip(".?!")
                    if stripped.endswith("요"):
                        self.assertTrue(stripped.endswith(("세요", "까요")), sentence)
        self.assertIn("합니다", body.body_text)

    def test_the_default_style_is_haeyo_and_only_a_formal_tone_changes_it(self):
        self.assertEqual(matrix()[(1, "없음", "naver_a")].style, bl.STYLE_HAEYO)
        self.assertEqual(matrix()[(1, "기본", "naver_a")].style, bl.STYLE_HAEYO)
        self.assertEqual(matrix()[(1, "자세히", "naver_a")].style, bl.STYLE_HAPSYO)
        self.assertEqual(body_of(make(*CANDIDATES[1]), None, None, "naver_a", channel=channel("naver_a", tone="격식 있는 문체")).style, bl.STYLE_HAPSYO)
        self.assertEqual(body_of(make(*CANDIDATES[1]), profile("naver_a", tone="정중한 말투"), None, "naver_a", channel=channel("naver_a", tone="친근한 말투")).style, bl.STYLE_HAEYO)
        self.assertIn("해요", matrix()[(1, "없음", "naver_a")].body_text)


class PurityTest(unittest.TestCase):
    NEW_MODULES = ("draft_body.py", "body_lang.py", "body_bank.py", "body_blocks.py", "body_library.py", "body_lib_info.py", "body_lib_compare.py", "body_lib_trouble.py", "body_lib_product.py", "body_lib_place.py")
    FORBIDDEN = {"time", "random", "datetime", "os", "pathlib", "socket", "subprocess", "shutil", "tempfile", "uuid", "secrets", "io", "urllib", "http", "ssl", "ctypes", "threading", "asyncio", "sqlite3", "json", "webbrowser"}

    def test_the_new_modules_import_nothing_that_touches_files_the_network_the_clock_or_randomness(self):
        import ast
        for name in self.NEW_MODULES:
            tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "content" / name).read_text(encoding="utf-8"))
            imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
            imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
            with self.subTest(module=name):
                self.assertFalse(imported & self.FORBIDDEN, imported & self.FORBIDDEN)
                names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
                self.assertFalse(names & {"open", "print", "input", "exec", "eval", "compile", "__import__"}, names & {"open", "print", "input", "exec", "eval", "compile", "__import__"})

    def test_building_a_body_calls_no_clock_no_randomness_and_opens_no_file_or_connection(self):
        events = []

        def hook(event, args):
            if event in ("open", "socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system", "os.remove", "os.rename", "os.mkdir", "os.rmdir", "shutil.copyfile", "shutil.rmtree"):
                events.append(event)

        candidates = [make(*CANDIDATES[number]) for number in (0, 4, 7)]                              # 후보를 만드는 일(번호는 난수)은 보호 구역 밖에서
        prof, options, chan = profile(), DraftOptions(experience="경험이에요.", urls=("https://example.com/a",)), channel("naver_a", monetization_focus=("small_appliance",))
        body_of(candidates[0], prof, options, channel=chan)                                           # 처음 부를 때의 지연 가져오기(가리기 모듈)를 먼저 끝낸다
        guards = [mock.patch("time.time", side_effect=AssertionError("시계")), mock.patch("time.monotonic", side_effect=AssertionError("시계")), mock.patch("time.perf_counter", side_effect=AssertionError("시계")),
                  mock.patch("random.random", side_effect=AssertionError("난수")), mock.patch("random.randrange", side_effect=AssertionError("난수")), mock.patch("random.choice", side_effect=AssertionError("난수")),
                  mock.patch("os.urandom", side_effect=AssertionError("난수")), mock.patch("uuid.uuid4", side_effect=AssertionError("난수"))]
        sys.addaudithook(hook)
        with contextlib.ExitStack() as stack:
            for guard in guards:
                stack.enter_context(guard)
            events.clear()
            for candidate in candidates:
                body_of(candidate, prof, options, channel=chan)
        self.assertEqual(events, [])

    def test_the_inputs_are_not_changed(self):
        candidate = make(*CANDIDATES[1])
        options = DraftOptions(message="전하는 말", must_include=("문장 하나",), exclude=("가격",))
        prof = profile()
        chan = channel("naver_a", categories=("가전",))
        snapshot = (candidate, options, prof, chan, dict(vars(options)), json.dumps(candidate.to_dict(), sort_keys=True))
        body_of(candidate, prof, options, channel=chan)
        self.assertEqual((candidate, options, prof, chan, dict(vars(options)), json.dumps(candidate.to_dict(), sort_keys=True)), snapshot)


class InputErrorTest(unittest.TestCase):
    def test_wrong_types_and_values_are_easy_errors(self):
        candidate = make(*CANDIDATES[1])
        expect_error(self, lambda: db.build_body("후보", None, None, today=TODAY), "CONTENT_INVALID")
        expect_error(self, lambda: db.build_body(candidate, "프로필", None, today=TODAY, blog="naver_a"), "CONTENT_INVALID")
        expect_error(self, lambda: db.build_body(candidate, None, "입력", today=TODAY, blog="naver_a"), "CONTENT_INVALID")
        expect_error(self, lambda: db.build_body(candidate, None, None, today=TODAY, blog="없는블로그"), "DRAFT_OPTION_INVALID")
        expect_error(self, lambda: db.build_body(candidate, None, None, today=TODAY, blog="naver_a", post_type="없는 유형"), "DRAFT_OPTION_INVALID")
        for bad in ("내일", "2026-13-40", "", None, 20261107):
            expect_error(self, lambda bad=bad: db.build_body(candidate, None, None, today=bad, blog="naver_a"), "DRAFT_OPTION_INVALID")
        expect_error(self, lambda: db.build_body(candidate, profile("naver_b"), None, today=TODAY, blog="naver_a"), "DRAFT_OPTION_INVALID")

    def test_a_key_shape_in_the_candidate_or_the_channel_profile_stops_the_body_and_is_not_repeated(self):
        for what, work in (("핵심 키워드", lambda: body_of(make("주제", KEY, (), INFO))), ("보조 키워드", lambda: body_of(make("주제", "정상 키워드", (KEY,), INFO))),
                           ("주제", lambda: body_of(make("주제 " + KEY, "정상 키워드", (), INFO))), ("채널 대상 독자", lambda: body_of(make(*CANDIDATES[0]), None, None, "naver_a", channel=channel("naver_a", audience="독자 " + KEY))),
                           ("채널 카테고리", lambda: body_of(make(*CANDIDATES[0]), None, None, "naver_a", channel=channel("naver_a", categories=(KEY,))))):
            with self.subTest(what=what):
                error = expect_error(self, work, "CONTENT_INVALID")
                self.assertNotIn(KEY, str(error))
                self.assertNotIn(KEY, error.detail)

    def test_a_wrong_shaped_channel_profile_is_an_easy_error(self):
        candidate = make(*CANDIDATES[1], blogs=("naver_a", "naver_b"))
        for channel_like in (type("C", (), {"tone": 5})(), type("C", (), {"categories": "문자열"})(), type("C", (), {"main_topics": (1, 2)})(), type("C", (), {"monetization_focus": None})(),
                             channel("naver_b")):
            with self.subTest(channel=type(channel_like).__name__):
                expect_error(self, lambda channel_like=channel_like: body_of(candidate, None, None, "naver_a", channel=channel_like), "CONTENT_INVALID")

    def test_user_text_limits_come_from_the_options_and_a_full_experience_is_built(self):
        expect_error(self, lambda: DraftOptions(message="가" * 1000), "DRAFT_OPTION_INVALID")
        experience = ("실제로 사용한 내용을 적은 한 문장이에요. " * 30)[:1000].strip()
        body = body_of(make(*CANDIDATES[0]), None, DraftOptions(experience=experience))
        self.assertEqual(len(experience), len(experience.strip()))
        self.assertIn(experience.split(". ")[0], body.body_text)

    def test_emoji_and_symbols_are_kept_and_the_body_is_still_built(self):
        for keyword in ("😀 이벤트 정리", "별점★ 보는 법", "가격(할인) 비교", "A/B 테스트", "메모 & 일정"):
            body = body_of(make("주제", keyword, ("😀 메모",), INFO))
            with self.subTest(keyword=keyword):
                self.assertIn(body.keyword, body.plain_text)
                self.assertGreaterEqual(body.chars, 1800)

    def test_a_sixty_character_keyword_is_built_and_keeps_the_structure_and_the_length(self):
        keyword = "가" * 30 + " " + "나" * 29
        for post_type in POST_TYPES:
            for blog in ("naver_a", "naver_b"):
                body = body_of(make("주제", keyword, (), post_type), None, None, blog)
                with self.subTest(type=post_type, blog=blog):
                    self.assertTrue(4 <= len(body.sections) <= 6)
                    self.assertTrue(1800 <= body.chars and body.chars_with_spaces <= 2800, (body.chars, body.chars_with_spaces))
                    self.assertEqual([item for item in claims.find_claims(body.plain_text) if claims.is_violation(item.category)], [])

    def test_a_one_character_keyword_still_reaches_the_lower_length_limit_for_every_type(self):
        for keyword in ("차", "집", "C", "AI", "TV", "8", "물", "밤", "길", "책", "불", "1", "3D", "a", "10"):
            for post_type in POST_TYPES:
                for blog in ("naver_a", "naver_b"):
                    body = body_of(make("주제", keyword, (), post_type), None, None, blog)
                    with self.subTest(keyword=keyword, type=post_type, blog=blog):
                        self.assertTrue(1800 <= body.chars and body.chars_with_spaces <= 2800, (body.chars, body.chars_with_spaces))

    def test_the_shortest_keywords_reach_the_lower_length_limit_with_every_profile_shape_too(self):
        """독립 검증 낮음 — 키워드 `8` 이 1,799자였다. 프로필이 있어 소제목 말씨·분야 항목이 달라지는 조합(분야를 못 읽는 일반 틀이 가장 짧다)에서도 하한을 지킨다."""
        for keyword in ("8", "물", "1"):
            for post_type in POST_TYPES:
                for name, maker in PROFILE_MAKERS.items():
                    for blog in ("naver_a", "naver_b"):
                        body = body_of(make("주제", keyword, (), post_type), maker(blog), None, blog, channel=channel(blog))
                        with self.subTest(keyword=keyword, type=post_type, profile=name, blog=blog):
                            self.assertTrue(1800 <= body.chars and body.chars_with_spaces <= 2800, (body.chars, body.chars_with_spaces))

    def test_unknown_text_in_the_profile_is_never_copied_into_the_body(self):
        body = body_of(make(*CANDIDATES[1]), profile("naver_a", tone="톤토큰", audience="독자토큰", intro_style="도입토큰", difficulty="난이도토큰", ending_style="마무리토큰", disclosure="고지토큰"))
        for token in ("톤토큰", "도입토큰", "난이도토큰", "마무리토큰", "고지토큰"):
            self.assertNotIn(token, body.plain_text)
        self.assertIn("독자토큰", body.plain_text)                                     # 대상 독자만 본문에 쓰인다


class RepetitionTest(unittest.TestCase):
    def test_no_sentence_repeats_and_every_paragraph_starts_with_a_different_sentence(self):
        for key, body in matrix().items():
            sentences, firsts = [], []
            for block in body.blocks:
                for text in block.paragraphs:
                    parts = claims.split_sentences(text)
                    firsts.append(parts[0])
                    sentences += parts
            with self.subTest(key=key):
                self.assertEqual(len(sentences), len(set(sentences)))
                self.assertEqual(len(firsts), len(set(firsts)))

    def test_not_too_many_paragraphs_start_with_the_same_word(self):
        worst = 0
        for key, body in matrix().items():
            starts = [claims.split_sentences(text)[0].split(" ")[0] for block in body.blocks for text in block.paragraphs]
            counts = {start: starts.count(start) for start in set(starts)}
            top = max(counts, key=counts.get)
            worst = max(worst, counts[top])
            with self.subTest(key=key):
                self.assertLessEqual(counts[top], 6, (top, counts[top]))
        self.assertLessEqual(worst, 6)

    def test_the_first_sentence_of_the_four_to_six_sections_is_never_the_same_frame_twice_in_a_row(self):
        for key, body in matrix().items():
            frames = [" ".join(claims.split_sentences(section.paragraphs[0])[0].split(" ")[:2]) for section in body.sections]
            with self.subTest(key=key):
                for before, after in zip(frames, frames[1:]):
                    self.assertNotEqual(before, after)


class FitTest(unittest.TestCase):
    """분량 맞추기(`_fit`)를 꾸민 재료로 직접 시험한다 — 실제 글에서는 하한·상한·문단 길이 상한이 서로 가려서 한 가지가 꺼져도 티가 나지 않는다(변이 점검에서 드러났다)."""

    def part(self, *items):
        return [db._Part(db.SECTION, "k", "", list(items))]                                # 소제목 없이 — 글자 수를 문단만으로 센다

    def measure(self, parts):
        return db.count_chars(db.render_body([part.block() for part in parts]))

    def test_optional_sentences_are_switched_on_until_the_lower_target_is_reached(self):
        parts = self.part(db._Item(["가" * 300], [], False), *[db._Item([], ["나" * 300], False) for _ in range(8)])
        self.assertEqual(self.measure(parts)[0], 300)
        db._fit(parts, 10 ** 6)
        chars, spaced = self.measure(parts)
        self.assertGreaterEqual(chars, 1800)
        self.assertLess(chars, 1800 + 300 + 300)                                  # 하한에 닿으면 멈춘다(마지막 선택 문장 하나만큼만 넘는다)
        self.assertLessEqual(spaced, 2800)

    def test_over_the_upper_limit_the_texts_switched_on_last_are_trimmed_back(self):
        word = "가 "                                                              # 공백이 절반인 글 — 공백 뺀 글자 수가 하한에 닿기 전에 공백 포함 글자 수가 상한을 넘는다
        parts = self.part(db._Item([(word * 600).strip()], [], False), *[db._Item([], [(word * 600).strip()], False) for _ in range(4)])
        db._fit(parts, 10 ** 6)
        chars, spaced = self.measure(parts)
        self.assertLessEqual(spaced, 2800)
        self.assertGreater(chars, 600)                                            # 다 걷어 내지는 않고 상한 안에서 가장 많이

    def test_an_optional_sentence_that_would_make_the_paragraph_longer_than_the_limit_stays_off(self):
        parts = self.part(*[db._Item(["가" * 100], ["나" * 300], False) for _ in range(12)])
        db._fit(parts, 200)
        self.assertEqual(self.measure(parts)[0], 1200)                            # 선택 문장은 켜자마자 문단 길이 상한 때문에 꺼졌다
        longer = self.part(*[db._Item(["가" * 100], ["나" * 300], False) for _ in range(12)])
        db._fit(longer, 10 ** 6)
        self.assertGreaterEqual(self.measure(longer)[0], 1800)                    # 상한이 넉넉하면 켜진다

    def test_optional_paragraphs_are_switched_on_before_optional_sentences_and_only_when_needed(self):
        parts = self.part(*[db._Item(["가" * 300], [], False) for _ in range(5)], db._Item(["나" * 300], [], True), db._Item(["다" * 300], [], True))
        self.assertEqual(self.measure(parts)[0], 1500)                            # 셋째 문단(`group`)은 처음에 꺼져 있다
        db._fit(parts, 10 ** 6)
        self.assertEqual(self.measure(parts)[0], 2100)
        enough = self.part(*[db._Item(["가" * 400], [], False) for _ in range(5)], db._Item(["나" * 300], [], True))
        db._fit(enough, 10 ** 6)
        self.assertEqual(self.measure(enough)[0], 2000)                           # 이미 하한을 넘었으면 켜지 않는다


class FitLimitsTest(unittest.TestCase):
    """독립 검증 M5: 길이 하한·상한 시험은 소스의 상수 대신 숫자를 직접 적는다 — 상한 상수를 올리는 변이(2,740 → 3,500)는 평소 글이 상한에 닿지 않아 가려지므로 상한에 닿는 재료로 직접 본다."""

    def measure(self, parts):
        return db.count_chars(db.render_body([part.block() for part in parts]))

    def test_the_constants_keep_their_margin_inside_the_test_limits(self):
        self.assertGreaterEqual(db.LOW_CHARS, 1800)
        self.assertLessEqual(db.LOW_CHARS, 1900)
        self.assertLessEqual(db.HIGH_SPACED, 2800)
        self.assertGreaterEqual(db.HIGH_SPACED, 2700)

    def test_a_text_that_reaches_the_lower_target_with_too_many_spaces_is_trimmed_below_2800_spaced_characters(self):
        word = "가가 "                                                              # 세 글자 가운데 둘만 글자라 하한(1,880)에 닿을 때 공백 포함 글자 수가 2,800 을 넘는다(3,151 — 상한 상수가 3,500 이면 걷어 내지 못한다)
        parts = [db._Part(db.SECTION, "k", "", [db._Item([(word * 350).strip()], [], False), *[db._Item([], [(word * 350).strip()], False) for _ in range(4)]])]
        db._fit(parts, 10 ** 6)
        chars, spaced = self.measure(parts)
        self.assertLessEqual(spaced, 2800)
        self.assertEqual(chars, 1400)                                             # 상한 안에서 가장 많이 — 마지막에 켠 선택 문장 하나만 걷어 내고 멈춘다


class SpareCapacityTest(unittest.TestCase):
    """독립 검증 낮음 — 분량 목표(1,880자)에 못 미치던 777편(대부분 제품 소개형)을 고치려고 문단마다 선택 문장을 더했다. 한 글자 키워드(글자가 가장 적게 쓰이는 입력)로도 선택 문장을 모두 켜면 목표보다 70자 넘게 남는 틀이어야
    분량 맞추기가 언제나 목표에 닿는다 — 틀을 줄이다가 여유가 사라지는 것을 막는다."""

    def potential(self, keyword, post_type, blog):
        candidate = make("주제", keyword, (), post_type)
        plan = dp.build_plan(candidate, None, None, today=TODAY, blog=blog)
        parts = db._Writer(candidate, None, None, DraftOptions(), plan).parts()
        for part in parts:
            for item in part.items:
                item.use_group = item.use_optional = True
        return db.count_chars(db.render_body([part.block() for part in parts]))[0]

    def test_every_post_type_has_seventy_characters_of_spare_text_even_for_a_one_character_keyword(self):
        for keyword in ("8", "물"):
            for post_type in POST_TYPES:
                for blog in ("naver_a", "naver_b"):
                    with self.subTest(keyword=keyword, type=post_type, blog=blog):
                        self.assertGreaterEqual(self.potential(keyword, post_type, blog), 1950)


class VariantChoiceTest(unittest.TestCase):
    """같은 문장을 두 번 쓰지 않고 바로 앞 문단과 같은 두 낱말로 시작하지 않는 장치 — 실제 틀에서는 겹치는 문장이 없어 일어나지 않으므로(그것이 목표) 일부러 겹치는 틀을 끼워 시험한다(변이 점검에서 드러났다)."""
    KEYWORDS = GuardLayerTest.KEYWORDS

    def build(self, keyword):
        return body_of(make(f"{keyword} 정리", keyword, (), INFO))

    def test_a_sentence_already_written_is_not_written_twice_when_another_variant_exists(self):
        same, other = "마지막 점검은 공식 안내를 기준으로 해 주세요.", "{kw:은/는} 이 순서면 충분해요."
        with mock.patch.dict(blk.CLOSING_FIRST, {INFO: ((same,), (same, other))}):
            for keyword in self.KEYWORDS:
                body = self.build(keyword)
                with self.subTest(keyword=keyword):
                    self.assertEqual(body.plain_text.count(same), 1)
                    self.assertIn(bl.fill(other, {"kw": body.keyword}), body.closing.paragraphs[0])

    def test_a_paragraph_does_not_start_with_the_same_two_words_as_the_one_before_when_another_variant_exists(self):
        first, same_start, other = "마지막 점검은 공식 안내로 해 주세요.", "마지막 점검은 한 번 더 훑어보면 실수가 줄어요.", "{kw:은/는} 한 번 더 훑어보면 실수가 줄어요."
        with mock.patch.dict(blk.CLOSING_FIRST, {INFO: ((first,),)}), mock.patch.dict(blk.CLOSING_SECOND, {"summary": ((same_start, other),)}):
            for keyword in self.KEYWORDS:
                body = self.build(keyword)
                with self.subTest(keyword=keyword):
                    self.assertEqual(len(body.closing.paragraphs), 2)
                    self.assertTrue(body.closing.paragraphs[0].startswith("마지막 점검은"))
                    self.assertFalse(body.closing.paragraphs[1].startswith("마지막 점검은"), body.closing.paragraphs[1])


class OtherFieldsTest(unittest.TestCase):
    def test_the_category_comes_from_the_profile_mapping_then_the_channel_names_then_a_single_name(self):
        base = make(*CANDIDATES[1])
        mapped = body_of(base, profile("naver_a", categories={"무선 청소기": "가전 리뷰"}), None, "naver_a")
        self.assertEqual(mapped.category, "가전 리뷰")
        by_name = body_of(base, None, None, "naver_a", channel=channel("naver_a", categories=("가전 고르기", "디지털 기기")))
        self.assertEqual(by_name.category, "가전 고르기")
        single = body_of(base, None, None, "naver_a", channel=channel("naver_a", categories=("그냥 하나",)))
        self.assertEqual(single.category, "그냥 하나")
        two = body_of(base, None, None, "naver_a", channel=channel("naver_a", categories=("여행 기록", "독서 기록")))
        self.assertEqual(two.category, "")
        self.assertTrue(any("카테고리를 정하지 못했습니다" in text for text in two.checks))
        contained = body_of(make("주제", "무선 청소기", (), INFO), None, None, "naver_a", channel=channel("naver_a", categories=("여행", "무선 청소기 리뷰모음", "독서")))
        self.assertEqual(contained.category, "무선 청소기 리뷰모음")                # 이름에 분야 낱말(청소기)이 든 카테고리
        inside = body_of(make("주제", "무선 청소기 관리", (), INFO), None, None, "naver_a", channel=channel("naver_a", categories=("여행", "청소기", "독서")))
        self.assertEqual(inside.category, "청소기")
        by_text = body_of(make("주제", "독서 습관 만들기", (), INFO), None, None, "naver_a", channel=channel("naver_a", categories=("여행", "독서", "재테크")))
        self.assertEqual(by_text.category, "독서")                                 # 이름이 후보의 글에 들어 있으면 분야 낱말이 없어도 고른다(여럿 가운데서도)

    def test_the_tags_are_the_plans_then_filled_up_without_going_over_the_profile_limit(self):
        body = matrix()[(1, "기본", "naver_a")]
        plan = dp.build_plan(make(*CANDIDATES[1]), profile(), None, today=TODAY, blog="naver_a")
        self.assertEqual(body.tags[:len(plan.tags)], plan.tags)
        self.assertLessEqual(len(body.tags), 8)
        limited = body_of(make(*CANDIDATES[1]), profile("naver_a", max_tags=3), None, "naver_a")
        self.assertLessEqual(len(limited.tags), 3)
        self.assertEqual(limited.tags, dp.build_plan(make(*CANDIDATES[1]), profile("naver_a", max_tags=3), None, today=TODAY, blog="naver_a").tags[:3])

    def test_the_sub_keywords_are_the_candidates_then_filled_with_the_keyword_and_a_tail(self):
        body = body_of(make("주제", "무선 청소기", ("청소기 추천",), COMPARE))
        self.assertEqual(body.sub_keywords[0], "청소기 추천")
        self.assertGreaterEqual(len(body.sub_keywords), 3)
        self.assertLessEqual(len(body.sub_keywords), db.MAX_AUX_KEYWORDS)
        self.assertEqual(len(set(body.sub_keywords)), len(body.sub_keywords))
        self.assertNotIn(body.keyword, body.sub_keywords)
        self.assertTrue(all(text for text in body.sub_keywords))
        many = body_of(make("주제", "노트북", ("가", "나", "다", "라", "마", "바", "사"), INFO))
        self.assertEqual(len(many.sub_keywords), db.MAX_AUX_KEYWORDS)
        same = body_of(make("주제", "노트북", ("노트북 비교", "노트북 차이"), COMPARE))
        plain = ["".join(text.split()) for text in same.sub_keywords]
        self.assertEqual(len(set(plain)), len(plain))                              # 후보의 보조 키워드와 같은 꼴은 더하지 않는다
        blocked = body_of(make("주제", "노트북", (), COMPARE), None, DraftOptions(exclude=("비교", "차이")))
        self.assertEqual([text for text in blocked.sub_keywords if "비교" in text or "차이" in text], [])      # 제외할 낱말이 든 꼬리는 더하지 않는다
        self.assertGreaterEqual(len(blocked.sub_keywords), 1)

    def test_a_tag_is_never_longer_than_thirty_characters_and_the_selected_title_starts_with_the_keyword_when_a_title_does(self):
        body = body_of(make("주제", "정리 키워드", ("아주긴보조키워드를" * 4,), INFO))
        self.assertTrue(all(len(tag) <= 30 for tag in body.tags), body.tags)
        started = 0
        for key, drafted in matrix().items():
            starts = [title for title in drafted.titles if title.startswith(drafted.keyword)]
            with self.subTest(key=key):
                self.assertIn(drafted.selected_title, drafted.titles)
                if starts:
                    self.assertEqual(drafted.selected_title, starts[0])
                    started += 1 if drafted.titles[0] != starts[0] else 0
        self.assertGreater(started, 0)                                              # 첫째 제목이 키워드로 시작하지 않는 초안이 실제로 있다(시험이 빈 껍데기가 아니다)

    def test_the_checks_have_the_basic_note_the_plans_notes_and_no_duplicates(self):
        for key, body in matrix().items():
            with self.subTest(key=key):
                self.assertIn("본문은 입력하신 내용과 일반적인 확인 순서만으로 만든 기본 글입니다", body.checks[0])
                self.assertEqual(len(body.checks), len(set(body.checks)))
                for text in body.checks:
                    self.assertEqual(claims.find_violations([text]), ())
        self.assertTrue(any("프로필이 아직 없어" in text for text in matrix()[(1, "없음", "naver_a")].checks))
        self.assertFalse(any("프로필이 아직 없어" in text for text in matrix()[(1, "기본", "naver_a")].checks))

    def test_the_plans_generic_notes_are_rewritten_in_body_words_and_the_plan_still_has_them(self):
        body = matrix()[(1, "없음", "naver_a")]
        plan = dp.build_plan(make(*CANDIDATES[1]), None, None, today=TODAY, blog="naver_a")
        for start in ("직접 겪은 경험이 있으면", "가격·날짜 같은 수치는 계획에 넣지 않았습니다", "참고 자료를 입력하지 않았습니다"):
            self.assertTrue(any(text.startswith(start) for text in plan.checks), f"작성 기반의 안내 문구가 바뀌었다 — db.PLAN_GENERIC_CHECKS 를 맞춘다: {start}")
        product = dp.build_plan(make(*CANDIDATES[5]), None, None, today=TODAY, blog="naver_a")
        self.assertTrue(any(text.startswith("이 제품을 직접 이용해 본 경험이 있다면") for text in product.checks), "제품 소개형의 안내 문구가 바뀌었다")
        for number in range(len(CANDIDATES)):
            for text in matrix()[(number, "없음", "naver_a")].checks:
                self.assertNotIn("계획", text)
        self.assertTrue(any("경험은 본문에 넣지 않았습니다" in text for text in body.checks))
        self.assertTrue(any("가격·날짜·수치는 본문에 넣지 않았습니다" in text for text in body.checks))
        self.assertTrue(any("참고 자료를 입력하지 않았습니다" in text and "글 끝에" in text for text in body.checks))
        given = body_of(make(*CANDIDATES[1]), None, DraftOptions(experience="경험이에요.", price_date=("값 하나",), urls=("https://example.com/a",)))
        self.assertFalse(any("경험은 본문에 넣지 않았습니다" in text for text in given.checks))
        self.assertFalse(any("가격·날짜·수치는 본문에 넣지 않았습니다" in text for text in given.checks))
        self.assertFalse(any("참고 자료를 입력하지 않았습니다" in text for text in given.checks))
        self.assertTrue(any("입력하신 가격·날짜는 그대로 넣었습니다" in text for text in given.checks))

    def test_a_profile_subheading_range_that_differs_from_the_count_is_noted(self):
        body = body_of(make(*CANDIDATES[1]), profile("naver_a", subheading_min=1, subheading_max=3), None, "naver_a")
        self.assertTrue(any("소제목 수(1~3개)와 다릅니다" in text for text in body.checks))
        fine = body_of(make(*CANDIDATES[1]), profile("naver_a", subheading_min=4, subheading_max=8), None, "naver_a")
        self.assertFalse(any("소제목 수" in text for text in fine.checks))

    def test_profile_intro_difficulty_and_ending_styles_change_the_text_like_the_plan_reads_them(self):
        base = body_of(make(*CANDIDATES[0]), profile("naver_a"), None, "naver_a")
        styled = body_of(make(*CANDIDATES[0]), profile("naver_a", intro_style="독자의 고민으로 시작", difficulty="전문 용어까지 자세히", ending_style="체크리스트로 마무리"), None, "naver_a")
        self.assertNotEqual(base.intro.paragraphs, styled.intro.paragraphs)
        self.assertNotEqual(base.closing.paragraphs, styled.closing.paragraphs)
        self.assertIn("기준의 근거가 되는 항목까지 자세히 짚어요", styled.intro.paragraphs[1])
        self.assertIn("확인 항목은", styled.closing.paragraphs[1])
        intros = {style: body_of(make(*CANDIDATES[0]), profile("naver_a", intro_style=style), None, "naver_a").intro.paragraphs[0] for style in ("독자의 고민으로 시작", "핵심부터 먼저", "배경과 상황으로 시작")}
        self.assertEqual(len(set(intros.values())), 3)                              # 도입부 방식만 달라도 도입 첫 문단이 다르다
        context = body_of(make(*CANDIDATES[0]), profile("naver_a", intro_style="배경과 상황으로 시작", ending_style="다음 글 예고"), None, "naver_a")
        self.assertIn("이어서", context.closing.paragraphs[1] + " ".join(context.closing.paragraphs))

    def test_the_domain_comes_from_the_keyword_only_and_the_profile_and_channel_texts_never_decide_it(self):
        """독립 검증 H1 로 의도적 갱신: 이전 시험(`…falls_back_to_the_profile_and_channel_texts`)은 키워드가 아무 말도 안 할 때 프로필의 주제·채널 역할로 분야를 짐작하게 했다 —
        그 짐작이 건강 글에 가전 문장을 쓰게 만들었으므로 이제 못 읽으면 일반이다(프로필·채널의 글은 협찬 가능 분야·말투·독자 같은 다른 용도로만 쓰인다)."""
        self.assertEqual(body_of(make("주제", "독서 습관", (), INFO)).domain, "generic")
        self.assertEqual(body_of(make("주제", "독서 습관", (), INFO), profile("naver_a", topic="생활가전 소개"), None, "naver_a").domain, "generic")
        self.assertEqual(body_of(make("주제", "독서 습관", (), INFO), None, None, "naver_a", channel=channel("naver_a", channel_role="여행·숙박", main_topics=("생활가전", "여행"))).domain, "generic")
        self.assertEqual(body_of(make("주제", "노트북", (), INFO), profile("naver_a", topic="여행 소개"), None, "naver_a").domain, "pc_hw")

    def test_building_for_github_pages_or_blogger_also_works_for_a_candidate_that_targets_them(self):
        for blog in ("github_pages", "blogger_ko"):
            body = body_of(make("주제", "무선 청소기", (), INFO, blogs=(blog,)), None, None, blog)
            with self.subTest(blog=blog):
                self.assertEqual(body.blog, blog)
                self.assertEqual(claims.find_claims(body.plain_text), ())


def bank_texts(domain):
    """분야 하나의 목록들에 든 모든 글(상황·기준 쌍은 두 글 모두)."""
    return {part for items in bb.BANKS[domain].values() for item in items for part in (item if isinstance(item, tuple) else (item,))}


def device_only_items():
    """기기 분야(가전·PC·소프트웨어)의 목록에만 있고 일반·생활·여행 목록에는 없는 항목 — 이 낱말이 기기 분야가 아닌 글에 나오면 분야 오판이다."""
    neutral = bank_texts("generic") | bank_texts("life") | bank_texts("travel")
    return sorted(text for domain in ("appliance", "pc_hw", "software") for text in bank_texts(domain) - neutral)


DEVICE_MARKERS = ("화면", "눌러", "백업", "전원", "내부 부품", "중요한 자료", "검색창", "어디에 쓰는지", "체크인", "체크아웃", "결제 전")


class DomainMisreadTest(unittest.TestCase):
    """독립 검증 H1·M1 — 분야는 후보의 낱말에서 확실히 읽을 때만 읽고, 못 읽으면 일반 틀만 쓴다. 틀은 분야 중립이라 기기가 아닌 글에 기기·숙소 문장이 나오지 않는다.
    검증자의 재현 입력(`ver_db_findings.md` H1)을 그대로 넣는다."""

    def chan(self, blog):
        if blog == "naver_a":
            return channel(blog, main_topics=("생활가전", "집 관리"), channel_role="생활 정보 안내", monetization_focus=("small_appliance", "lodging_travel"))
        return channel(blog, main_topics=("AI", "PC 하드웨어"), channel_role="IT 도구 안내", monetization_focus=("ai_service", "pc_parts", "work_automation", "pc_peripheral"))

    def made(self, keyword, post_type, blog="naver_a", topic_profile=True, **fields):
        prof = profile(blog, topic="생활가전 소개" if blog == "naver_a" else "AI 도구 소개") if topic_profile else None
        return body_of(make(f"{keyword} 정리", keyword, (), post_type, blogs=("naver_a", "naver_b"), **fields), prof, None, blog, channel=self.chan(blog))

    def test_a_blogs_main_topic_never_makes_a_health_post_a_device_post(self):
        items = device_only_items()
        self.assertGreater(len(items), 80)
        for keyword, post_type, blog in (("다이어트", COMPARE, "naver_a"), ("영양제", INFO, "naver_b"), ("영양제", COMPARE, "naver_b"), ("당뇨", INFO, "naver_b"), ("다이어트", TROUBLE, "naver_a"), ("영양제", PRODUCT, "naver_a")):
            body = self.made(keyword, post_type, blog)
            with self.subTest(keyword=keyword, type=post_type, blog=blog):
                self.assertEqual(body.domain, "generic")
                self.assertFalse(body.sponsor_slot)                                  # 분야를 못 읽으면 협찬 가능 분야에도 해당하지 않는다(협찬 안내는 읽은 분야에서만)
                for item in items:
                    self.assertNotIn(item, body.body_text, item)

    def test_the_verifiers_exact_sentences_are_gone(self):
        body = self.made("다이어트", COMPARE, "naver_a")
        for phrase in ("다이어트를 견줄 때 쓰는 기준에는 놓을 자리와 설치 공간", "소비전력 표기", "놓을 자리와 설치 공간"):
            self.assertNotIn(phrase, body.body_text)
        body = self.made("영양제", INFO, "naver_b")
        for phrase in ("연결 단자와 규격의 호환", "내 컴퓨터의 사양과 운영체제", "전원과 소비전력"):
            self.assertNotIn(phrase, body.body_text)

    def test_words_that_only_look_like_software_do_not_get_software_sentences(self):
        items = device_only_items()
        for keyword, domain in (("운동 프로그램", "generic"), ("한 도시 여행", "travel"), ("목표 설정 방법", "generic"), ("가구 설치", "generic")):
            for post_type in POST_TYPES:
                for blog in ("naver_a", "naver_b"):
                    body = self.made(keyword, post_type, blog)
                    with self.subTest(keyword=keyword, type=post_type, blog=blog):
                        self.assertEqual(body.domain, domain)
                        for item in items:
                            self.assertNotIn(item, body.body_text, item)

    def test_a_keyword_that_names_its_domain_still_gets_that_domains_items(self):
        for keyword, domain, post_type in (("무선 청소기", "appliance", INFO), ("그래픽카드", "pc_hw", COMPARE), ("노션", "software", INFO), ("제주 숙소", "travel", PLACE), ("곰팡이 제거", "life", TROUBLE)):
            body = self.made(keyword, post_type, "naver_a")
            own = [text for text in bank_texts(domain) if text in body.body_text]
            with self.subTest(keyword=keyword):
                self.assertEqual(body.domain, domain)
                self.assertGreaterEqual(len(own), 3, own)

    def test_posts_that_are_not_about_devices_have_no_device_or_lodging_sentence_in_any_type(self):
        """검증자의 `mismatch_scan` 과 같은 점검 — 곰팡이·독서·도서관·건강 글 5종 유형에 화면·눌러 보기·백업·전원·내부 부품·검색창·어디에 쓰는지·체크인·결제 전이 없다(160편 중 154편에 있었다)."""
        keywords = ("곰팡이 제거", "결로", "층간소음", "독서 습관", "시간 관리", "글쓰기", "다이어트", "영양제", "당뇨", "제주 숙소", "동네 도서관", "박물관", "운동 프로그램", "목표 설정 방법", "가구 설치", "한 도시 여행")
        count = 0
        for keyword in keywords:
            for post_type in POST_TYPES:
                for blog in ("naver_a", "naver_b"):
                    body = self.made(keyword, post_type, blog)
                    count += 1
                    with self.subTest(keyword=keyword, type=post_type, blog=blog):
                        for marker in DEVICE_MARKERS:
                            self.assertNotIn(marker, body.body_text, marker)
        self.assertEqual(count, 160)

    def test_device_posts_still_mention_the_backup_where_it_belongs(self):
        found = 0
        for keyword in ("노트북 전원", "SSD 교체", "공유기", "모니터", "ChatGPT 요금제", "깃허브", "엑셀", "노션"):
            for blog in ("naver_a", "naver_b"):
                body = self.made(keyword, TROUBLE, blog)
                self.assertIn(body.domain, ("pc_hw", "software"))
                found += "백업" in body.body_text
        self.assertGreaterEqual(found, 3)                                            # 전용 문장이 사라진 것이 아니라 기기 분야 목록의 항목으로 옮겼다

    def test_trouble_posts_name_what_to_prepare_before_starting_from_their_own_domains_list(self):
        """'손대기 전에 먼저 챙길 것' 문장은 그 분야의 B 목록 항목으로 쓴다(기기는 백업·안전 안내, 생활은 작업 전 사진 …) — 이 자리를 값 자리에서 빼면 문장이 말없이 사라지므로 따로 본다."""
        for keyword, domain in (("노트북 전원", "pc_hw"), ("무선 청소기", "appliance"), ("노션", "software"), ("제주 숙소", "travel"), ("곰팡이 제거", "life"), ("독서 습관", "generic")):
            for blog in ("naver_a", "naver_b"):
                body = self.made(keyword, TROUBLE, blog)
                sentences = [one for one in claims.split_sentences(body.body_text) if "먼저 챙겨 두세요" in one]
                with self.subTest(keyword=keyword, blog=blog):
                    self.assertEqual(body.domain, domain)
                    self.assertEqual(len(sentences), 2, sentences)
                    for sentence in sentences:
                        self.assertTrue(any(item in sentence for item in bb.BANKS[domain]["B"]), sentence)

    def test_the_order_sentence_lists_the_causes_from_easy_to_hard_for_every_blog_and_keyword(self):
        """'확인은 쉬운 것에서 어려운 것 순으로 해요' 문단의 원인 셋은 목록의 쉬운 순서 그대로다 — 이전에는 끝에서 돌아 '부품 자체의 불량' 이 '연결 단자 확인' 보다 앞에 나왔다."""
        causes = bb.BANKS["pc_hw"]["Z"]
        checked = 0
        for keyword in ("노트북 전원", "노트북", "SSD 교체", "공유기", "모니터", "키보드", "마우스", "웹캠", "헤드셋", "충전기", "스마트폰", "프린터", "컴퓨터", "하드웨어", "메모리", "태블릿"):
            for blog in ("naver_a", "naver_b"):
                body = self.made(keyword, TROUBLE, blog)
                sentence = next((one for one in claims.split_sentences(body.body_text) if "그다음" in one and "마지막으로" in one), "")
                found = sorted((sentence.index(cause), number) for number, cause in enumerate(causes) if cause in sentence)
                with self.subTest(keyword=keyword, blog=blog):
                    self.assertEqual(len(found), 3, sentence)
                    self.assertEqual([number for _position, number in found], sorted(number for _position, number in found), sentence)
                    checked += 1
        self.assertEqual(checked, 32)

    def test_a_heading_never_mixes_a_formal_ending_into_a_haeyo_post_or_the_other_way(self):
        count = 0
        for key, body in matrix().items():
            for block in body.blocks:
                if block.heading:
                    count += 1
                    with self.subTest(key=key, heading=block.heading):
                        self.assertFalse(bl.clashes_with_style(block.heading, body.style), block.heading)
        self.assertGreater(count, 500)
        formal = lib.step_of(INFO, "usage")
        self.assertTrue(formal.heads[1].endswith("활용합니다"))                         # 네이버 B 의 소제목 틀 가운데 합니다체 끝이 실제로 있다(시험이 빈 껍데기가 아니다)
        body = body_of(make("정보 정리", "독서 습관", (), INFO), None, None, "naver_b")
        self.assertEqual(body.style, bl.STYLE_HAEYO)
        self.assertFalse(any(block.heading.endswith("니다") for block in body.blocks))
        hapsyo = body_of(make("정보 정리", "독서 습관", (), INFO), None, None, "naver_b", channel=channel("naver_b", tone="격식 있는 정중한 문체"))
        self.assertEqual(hapsyo.style, bl.STYLE_HAPSYO)
        self.assertTrue(any(block.heading.endswith("활용합니다") for block in hapsyo.blocks))     # 합니다체 글에는 합니다체 소제목이 그대로 남는다


class ValueRotationTest(unittest.TestCase):
    """소제목마다 목록의 시작 자리를 달리해 같은 항목이 모든 소제목에 되풀이되지 않는다(검증자의 변이 M50 — 이 장치를 지워도 평소 시험은 통과했다)."""

    def writer(self, keyword, post_type=INFO):
        candidate = make("주제", keyword, (), post_type)
        return db._Writer(candidate, None, None, DraftOptions(), dp.build_plan(candidate, None, None, today=TODAY, blog="naver_a"))

    def test_every_section_starts_its_item_lists_at_a_different_place(self):
        for keyword in ("무선 청소기", "노트북", "노션", "제주 숙소", "곰팡이 제거", "독서 습관"):
            writer = self.writer(keyword)
            with self.subTest(keyword=keyword):
                firsts = [writer.values(number)["c1"] for number in range(1, 5)]
                self.assertGreaterEqual(len(set(firsts)), 3, firsts)
                lists = [writer.values(number)["C"] for number in range(1, 5)]
                self.assertGreaterEqual(len(set(lists)), 3, lists)                      # 목록이 여섯 개인 분야는 4번째 소제목이 첫 소제목과 같은 자리로 돌아온다

    def test_the_same_section_number_gives_the_same_values_and_the_cause_list_keeps_the_banks_easy_to_hard_order(self):
        writer = self.writer("노트북 전원", TROUBLE)
        self.assertEqual(writer.values(3), writer.values(3))
        causes = bb.BANKS["pc_hw"]["Z"]
        for number in range(0, 12):
            picked = [writer.values(number)[f"z{index}"] for index in (1, 2, 3)]
            self.assertEqual([causes.index(text) for text in picked], sorted(causes.index(text) for text in picked), picked)


class FakeSafety:
    """주제 엔진의 안전 판정 결과(`topics.safety.SafetyReport`)처럼 속성 `stop`·`stage`·`relationship` 만 가진 값."""
    def __init__(self, stage="general", stop=False, relationship="none"):
        self.stage, self.stop, self.relationship = stage, stop, relationship


class SafetyWarningTest(unittest.TestCase):
    """독립 검증 H2·M4 — 자동 초안 중지는 거절하고(입력을 되풀이하지 않는다), 근거 확인 필요·협찬 낱말 추정·단정 낱말은 확인 권장 맨 위의 경고로 알린다."""
    STOPPED = ("당뇨 완치 영양제", "다이어트 즉시 효과", "아토피 확실한 치료", "체중 감량 무조건 성공")

    def test_the_constants_match_the_engines_stage_and_relation_names(self):
        self.assertEqual((db.STAGE_STOP, db.STAGE_EVIDENCE, db.STAGE_MARK), (safety.STAGE_STOP, safety.STAGE_EVIDENCE, safety.STAGE_MARK))
        self.assertEqual(db.RELATION_SUSPECTED, safety.RELATION_SUSPECTED)

    def test_the_four_stopped_inputs_are_stopped_by_the_real_engine_and_the_body_refuses_them(self):
        for keyword in self.STOPPED:
            report = safety.check_text([f"{keyword} 정리", keyword])
            with self.subTest(keyword=keyword):
                self.assertTrue(report.stop)
                error = expect_error(self, lambda report=report, keyword=keyword: body_of(make(f"{keyword} 정리", keyword, (), INFO), safety=report), "CONTENT_INVALID")
                shown = " ".join((str(error), error.detail, error.rendered().message, error.rendered().action))
                for word in keyword.split():
                    self.assertNotIn(word, shown)                                    # 입력한 글을 되풀이하지 않는다
                self.assertIn("자동 초안 중지", error.rendered().message)
                self.assertIn("후보 보기", error.rendered().message)

    def test_a_stopped_report_refuses_before_anything_else_is_built(self):
        with mock.patch.object(dp, "build_plan", side_effect=AssertionError("계획을 만들기 전에 거절해야 한다")):
            expect_error(self, lambda: body_of(make(*CANDIDATES[0]), safety=FakeSafety("stop", True)), "CONTENT_INVALID")

    def test_the_evidence_stage_adds_one_warning_on_top_and_the_health_paragraph_even_without_a_health_word(self):
        plain = body_of(make("주제", "독서 습관", (), INFO))
        warned = body_of(make("주제", "독서 습관", (), INFO), safety=FakeSafety("evidence"))
        self.assertEqual(warned.checks[0], db.EVIDENCE_NOTE)
        self.assertIn("본문은 입력하신 내용과 일반적인 확인 순서만으로 만든 기본 글입니다", warned.checks[1])
        self.assertEqual(warned.sensitive, "health")                                 # 엔진이 건강 주제로 판정했으면 낱말 목록에 없어도 건강
        self.assertTrue(any("전문가" in paragraph or "기관" in paragraph for paragraph in warned.cautions.paragraphs))
        self.assertIsNone(plain.sensitive)
        self.assertEqual(len([text for text in warned.checks if text == db.EVIDENCE_NOTE]), 1)
        self.assertEqual(claims.find_violations([db.EVIDENCE_NOTE]), ())

    def test_the_mark_stage_only_marks_the_topic_as_health_and_adds_no_top_warning(self):
        marked = body_of(make("주제", "독서 습관", (), INFO), safety=FakeSafety("mark"))
        self.assertEqual(marked.sensitive, "health")
        self.assertIn("본문은 입력하신 내용", marked.checks[0])
        general = body_of(make("주제", "독서 습관", (), INFO), safety=FakeSafety("general"))
        self.assertIsNone(general.sensitive)
        self.assertIn("본문은 입력하신 내용", general.checks[0])

    def test_a_suspected_sponsor_word_in_the_candidate_adds_a_warning_on_top(self):
        body = body_of(make("주제", "협찬 청소기", (), INFO), safety=FakeSafety("general", False, "suspected"))
        self.assertEqual(body.checks[0], db.SPONSOR_WORD_NOTE)
        self.assertIn("협찬", db.SPONSOR_WORD_NOTE)
        none = body_of(make("주제", "협찬 청소기", (), INFO), safety=FakeSafety("general", False, "none"))
        self.assertNotIn(db.SPONSOR_WORD_NOTE, none.checks)

    def test_assertion_words_in_the_candidate_get_one_top_warning_that_lists_only_table_words(self):
        for keyword, word in (("최고의 청소기", "최고"), ("무조건 성공하는 주식", "무조건"), ("가장 좋은 선택", "가장"), ("청소기 1위", "1위"), ("TOP 청소기", "top"), ("효과 좋은 비타민", "효과")):
            body = body_of(make(f"{keyword} 정리", keyword, (), INFO))
            with self.subTest(keyword=keyword):
                self.assertIn(f"‘{word}’", body.checks[0])
                self.assertIn("본문 곳곳에 그대로 되풀이됩니다", body.checks[0])
                self.assertIn("본문은 입력하신 내용", body.checks[1])
                for piece in keyword.split():
                    if piece != word:
                        self.assertNotIn(piece, body.checks[0])                      # 입력한 글이 아니라 고정 표의 낱말만 보인다
                self.assertEqual(claims.find_violations([body.checks[0]]), ())
        quiet = body_of(make("무선 청소기 정리", "무선 청소기", (), INFO))
        self.assertNotIn("단정·최상급·효과를 말하는 표현", " ".join(quiet.checks))
        self.assertIn("본문은 입력하신 내용", quiet.checks[0])

    def test_the_warnings_come_in_a_fixed_order_and_each_appears_once(self):
        body = body_of(make("주제", "협찬 최고 청소기", (), INFO), safety=FakeSafety("evidence", False, "suspected"))
        self.assertEqual(body.checks[0], db.EVIDENCE_NOTE)
        self.assertEqual(body.checks[1], db.SPONSOR_WORD_NOTE)
        self.assertIn("단정·최상급·효과를 말하는 표현", body.checks[2])
        self.assertIn("본문은 입력하신 내용", body.checks[3])
        self.assertEqual(len(body.checks), len(set(body.checks)))

    def test_the_widened_sensitive_words_add_the_expert_paragraph_and_the_check_line(self):
        for keyword, kind in (("당뇨", "health"), ("비염", "health"), ("ETF", "finance"), ("금리", "finance"), ("전세", "legal"), ("이혼", "legal"), ("해고", "legal"), ("암 예방 식품", "health")):
            body = body_of(make(f"{keyword} 안내", keyword, (), INFO))
            with self.subTest(keyword=keyword):
                self.assertEqual(body.sensitive, kind)
                self.assertTrue(any("전문가" in paragraph or "기관" in paragraph for paragraph in body.cautions.paragraphs))
                self.assertTrue(any("일반 정보만 다뤘습니다" in text for text in body.checks))
                self.assertEqual(claims.find_claims(body.plain_text), ())

    def test_a_sensitive_keyword_gets_neither_the_cure_tails_nor_the_cure_tags(self):
        for keyword in ("영양제", "주식", "이혼", "당뇨"):
            body = body_of(make(f"{keyword} 안내", keyword, (), TROUBLE))
            with self.subTest(keyword=keyword):
                for text in (*body.sub_keywords, *body.tags):
                    self.assertFalse(text.endswith(("해결", "해결 방법", "해결방법", "예방")), text)
                self.assertTrue(set(body.sub_keywords) & {f"{keyword} {tail}" for tail in blk.SENSITIVE_TAILS})
        normal = body_of(make("곰팡이 제거 안내", "곰팡이 제거", (), TROUBLE))
        self.assertTrue(any(text.endswith("해결 방법") for text in normal.sub_keywords))      # 민감하지 않은 글은 그대로


class KeyShapeTest(unittest.TestCase):
    """독립 검증 M3 — 키 모양 11종은 후보·채널 프로필·선택 입력의 모든 칸에서 거절되고 오류 어디에도 되풀이되지 않는다. 가짜 키 형식 문자열은 실행 중 조각을 이어 붙여 만든다(저장소에 키 모양 글자를 두지 않는다)."""
    SHAPES = {
        "구글형": "AI" + "za" + "B" * 35, "AQ형": "AQ" + "." + "C" * 20, "GOCSPX형": "GOC" + "SPX-" + "D" * 20, "1//0형": "1/" + "/0" + "E" * 20, "ya29형": "ya" + "29." + "F" * 20,
        "gh형": "gh" + "p_" + "G" * 36, "깃허브세분화형": "github" + "_pat_" + "H" * 30, "slack형": "xo" + "xb-" + "1234567890-" + "I" * 10, "AWS형": "AK" + "IA" + "J" * 16, "sk형": "s" + "k-" + "K" * 40,
        "해시32형": "a1b2" * 8,
    }
    CANDIDATE_FIELDS = ("keyword", "topic", "sub")
    CHANNEL_FIELDS = ("audience", "categories")
    OPTION_TEXTS = ("message", "experience", "opinion", "conclusion", "audience", "title_direction")
    OPTION_LISTS = ("must_include", "price_date", "exclude")

    def attempt(self, field_kind, field, shape):
        """칸 하나에 모양을 넣어 만든다 — (None 이면 만들어졌다, 아니면 거절한 AppError). 후보·선택 입력을 만들 때 거절해도 거절이다."""
        keyword, topic, subs, chan, options = "정상 키워드", "정상 주제", (), None, None
        if field_kind == "candidate":
            keyword, topic, subs = (shape, topic, subs) if field == "keyword" else (keyword, shape, subs) if field == "topic" else (keyword, topic, (shape,))
        try:
            candidate = make(topic, keyword, subs, INFO)
            if field_kind == "channel":
                chan = channel("naver_a", **({"audience": shape} if field == "audience" else {"categories": (shape,)}))
            if field_kind == "option":
                options = DraftOptions(**{field: (shape,) if field in self.OPTION_LISTS else shape})
            body = body_of(candidate, None, options, "naver_a", channel=chan)
        except AppError as error:
            return error, None
        return None, body

    def run_matrix(self):
        done = 0
        for name, shape in self.SHAPES.items():
            run = max(set(shape), key=shape.count) * 8
            for field_kind, fields in (("candidate", self.CANDIDATE_FIELDS), ("channel", self.CHANNEL_FIELDS), ("option", (*self.OPTION_TEXTS, *self.OPTION_LISTS))):
                for field in fields:
                    error, body = self.attempt(field_kind, field, shape)
                    done += 1
                    with self.subTest(shape=name, kind=field_kind, field=field):
                        self.assertIsNotNone(error, "키 모양이 거절되지 않고 본문이 만들어졌다")
                        shown = " ".join((str(error), error.detail, error.rendered().message, error.rendered().action))
                        self.assertNotIn(shape, shown)
                        self.assertNotIn(run, shown)
        return done

    def test_all_eleven_shapes_are_refused_in_every_candidate_channel_and_option_field(self):
        self.assertEqual(len(self.SHAPES), 11)
        self.assertEqual(self.run_matrix(), 11 * (3 + 2 + 9))

    def test_the_shape_check_function_and_the_mask_each_cover_shapes_the_other_misses(self):
        """`security.mask` 는 6종을 가리고 `security.shape.looks_secret` 은 11종 모두 찾는다 — 둘을 함께 써야 11종이 모두 걸린다(검증자가 찾은 틈)."""
        from chanceblog_desktop.security.mask import mask
        from chanceblog_desktop.security.shape import looks_secret
        self.assertTrue(all(looks_secret(shape) for shape in self.SHAPES.values()))
        self.assertLess(sum(mask(shape) != shape for shape in self.SHAPES.values()), 11)
        self.assertEqual(sum(mask(shape) != shape or looks_secret(shape) for shape in self.SHAPES.values()), 11)

    def test_a_shape_only_the_mask_knows_is_refused_too(self):
        """`security.shape.looks_secret` 이 못 찾고 `security.mask` 만 가리는 모양(영문자만 이어진 Bearer 값)도 거절한다 — 둘을 함께 써야 한쪽이 놓치는 모양까지 걸린다."""
        from chanceblog_desktop.security.mask import mask
        from chanceblog_desktop.security.shape import looks_secret
        shape = "Bear" + "er " + "abcdefghijklmnopqrstuv"
        self.assertNotEqual(mask(shape), shape)
        self.assertFalse(looks_secret(shape))
        for field_kind, field in (("candidate", "keyword"), ("candidate", "topic"), ("candidate", "sub"), ("channel", "audience"), ("option", "message")):
            error, body = self.attempt(field_kind, field, shape)
            with self.subTest(kind=field_kind, field=field):
                self.assertIsNotNone(error)
                self.assertNotIn("abcdefghijklmnop", " ".join((str(error), error.detail, error.rendered().message)))

    def test_a_shape_that_only_appears_after_the_marks_are_removed_is_refused_too(self):
        """마크다운 표시를 걷어 내면 조각이 이어 붙어 키 모양이 되는 글('…**…')도 거절한다 — 걷어 낸 뒤의 글로도 한 번 더 검사한다(걷어 내기 전 글에는 모양이 없다)."""
        from chanceblog_desktop.security.mask import mask
        from chanceblog_desktop.security.shape import looks_secret
        for joint in ("**", "`", "~~"):                                              # '__' 는 키에 쓰이는 글자라 걷어 내기 전에도 가려진다
            shape = "AI" + "za" + joint + "B" * 35
            self.assertEqual(mask(shape), shape)
            self.assertFalse(looks_secret(shape))                                    # 걷어 내기 전에는 어느 검사에도 안 걸린다
            for field_kind, field in (("candidate", "keyword"), ("candidate", "topic"), ("candidate", "sub")):
                error, body = self.attempt(field_kind, field, shape)
                with self.subTest(joint=joint, field=field):
                    self.assertIsNotNone(error, "걷어 낸 뒤 키 모양이 되는 글이 거절되지 않고 본문이 만들어졌다")
                    self.assertEqual(error.code, "CONTENT_INVALID")
                    self.assertNotIn("B" * 8, " ".join((str(error), error.detail, error.rendered().message)))

    def test_all_eleven_shapes_inside_a_reference_url_are_refused_and_never_printed(self):
        """참고 주소 칸에는 영숫자 덩어리 규칙을 쓸 수 없어(정상 주소도 길다) 키 접두사만 본다 — 주소 모양을 거르는 `DraftOptions` 가 6종을, 본문 생성기가 나머지 5종을 거절해 11종이 모두 걸린다(검증자의 `shape_cli` 가 `--url` 칸에서 5종이 그대로 나온다고 보였다)."""
        refused_at_input = refused_at_body = 0
        for name, shape in self.SHAPES.items():
            for url in ("https://example.com/" + shape, "https://example.com/a?key=" + shape + "&x=1"):
                try:
                    options = DraftOptions(urls=(url,))
                except AppError as error:
                    refused_at_input += 1
                    error_text = " ".join((str(error), error.detail, error.rendered().message))
                else:
                    with self.assertRaises(AppError, msg=name) as caught:
                        body_of(make(*CANDIDATES[1]), None, options)
                    refused_at_body += 1
                    error_text = " ".join((str(caught.exception), caught.exception.detail, caught.exception.rendered().message))
                    self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                with self.subTest(shape=name, url=url[:30]):
                    self.assertNotIn(shape, error_text)
        self.assertEqual(refused_at_input + refused_at_body, 22)
        self.assertGreater(refused_at_body, 0)                                       # 본문 생성기가 따로 막는 주소가 실제로 있다(시험이 빈 껍데기가 아니다)

    def test_ordinary_long_urls_are_not_taken_for_keys(self):
        """정상 주소는 길고 글자·숫자가 섞여 있다 — 'task-management'·'disk-cleanup' 속의 'sk-' 나 숫자만 긴 번호는 키가 아니다."""
        urls = ("https://example.com/products/2026/new-vacuum-cleaner-guide", "https://blog.naver.com/exampleaaa/223456789012", "https://example.com/task-management-desk-setup-guide-2026",
                "https://example.com/risk-assessment-disk-cleanup-tips", "https://example.com/a/1234567890123456789012345678901", "https://example.com/post/0123456789abcdef0123456789abcde")
        body = body_of(make(*CANDIDATES[1]), None, DraftOptions(urls=urls))
        for url in urls:
            self.assertIn(url, body.body_text)
            self.assertIsNone(db.URL_KEY_SHAPES.search(url))

    def test_a_normal_url_in_the_url_field_is_still_accepted_and_ordinary_korean_text_is_never_taken_for_a_key(self):
        options = DraftOptions(urls=("https://example.com/products/2026/new-vacuum-cleaner-guide",), message="전하고 싶은 말은 이거예요.")
        body = body_of(make(*CANDIDATES[1]), None, options)
        self.assertIn("https://example.com/products/2026/new-vacuum-cleaner-guide", body.body_text)
        for keyword in ("무선 청소기 선택 기준과 관리 방법 총정리", "RTX 4060 그래픽카드", "Windows 11 설치 방법"):
            self.assertEqual(body_of(make(f"{keyword} 안내", keyword, (), INFO)).keyword, keyword)


class TidyInputTest(unittest.TestCase):
    """독립 검증 낮음 — 후보의 마크다운 표시와 HTML 엔티티는 제목·소제목·문단에 되풀이되기 전에 걷어 낸다(풀지 않고 지운다)."""
    MARKS = ("**", "&lt;", "&gt;", "&amp;", "&#", "`", "](", "~~", "__", "lt;", "gt;", "amp;")                 # 'lt;'·'gt;'·'amp;' 는 엔티티를 반쯤 지우고 남기는 찌꺼기다

    def test_markdown_marks_and_entities_never_reach_a_title_a_heading_or_a_paragraph(self):
        for keyword in ("**굵은** 키워드", "A &lt; B 비교", "&amp;lt; 비교", "`코드` 키워드", "[링크](http://example.com) 설명", "__밑줄__ 글", "~~취소~~ 글", "- 목록 키워드", "# 제목 키워드"):
            body = body_of(make(f"{keyword} 정리", keyword, (f"{keyword} 선택",), INFO))
            dump = chr(10).join((body.plain_text, *body.titles, body.summary, body.keyword, body.topic, body.tags_text, " ".join(body.sub_keywords), body.category))       # 확인 권장의 안내 글(명령 이름의 백틱 따위)은 후보의 글이 아니라서 뺀다
            with self.subTest(keyword=keyword):
                for mark in self.MARKS:
                    self.assertNotIn(mark, dump, mark)
                self.assertFalse(body.plain_text.startswith(("#", "-", ">")))
                self.assertFalse(any(line.startswith(("#", "- ", "> ")) for line in body.plain_text.split(chr(10))))
                self.assertEqual(claims.find_claims(body.plain_text), ())

    def test_a_clean_candidate_is_used_as_it_is(self):
        candidate = make(*CANDIDATES[1])
        self.assertIs(db._tidy_candidate(candidate), candidate)
        self.assertEqual(body_of(candidate).keyword, candidate.keyword)
        self.assertEqual(db._tidy_candidate("후보"), "후보")                            # 후보가 아닌 값은 그대로 두어 계획 만들기가 같은 오류로 거절한다

    def test_a_keyword_that_is_only_marks_is_refused_with_an_easy_error_that_does_not_repeat_it(self):
        for keyword in ("&lt;", "**", "&amp;"):
            try:
                candidate = make("주제", keyword, (), INFO)
            except AppError:
                continue                                                             # 후보를 만들 때 이미 거절한 모양은 거기서 끝이다
            with self.assertRaises(AppError) as caught:
                body_of(candidate)
            self.assertIn(caught.exception.code, ("CANDIDATE_INVALID", "CONTENT_INVALID"))
            self.assertNotIn(keyword, str(caught.exception) + caught.exception.detail)
        self.assertEqual(bl.plain_text("R&D 와 Q&A 정리"), "R&D 와 Q&A 정리")      # 엔티티가 아닌 & 는 그대로
        self.assertEqual(bl.plain_text("A &amp; B 비교"), "A & B 비교")               # '&amp;' 만 '&' 로
        self.assertEqual(bl.plain_text("&amp;lt; 비교 &AMP;amp;gt;"), "비교")          # 겹쳐 쓴 엔티티는 찌꺼기 없이 지운다


class WideDeterminismTest(unittest.TestCase):
    """독립 검증 M5 — 결정성은 여러 후보(보조 키워드·태그를 채우는 입력과 선택 입력 포함)와 해시 시드가 다른 여러 프로세스로 본다. 태그·보조 키워드를 만들 때 집합·딕셔너리 순서에 기대는 코드(검증자의 변이 M18)는
    후보 하나·태그를 안 채우는 입력으로는 드러나지 않았다."""
    SPECS = (CANDIDATES[0], CANDIDATES[1], CANDIDATES[3], CANDIDATES[5], CANDIDATES[7], CANDIDATES[9],
             ("노트북 주변기기 정리", "노트북 거치대", ("거치대 추천", "노트북 스탠드", "높이 조절", "각도 조절", "접이식"), INFO), ("당뇨 관리 안내", "당뇨 관리", ("혈당 기록", "식단 관리"), INFO),
             ("한 도시 여행 코스", "한 도시 여행", ("당일치기", "여행 준비"), PLACE), ("겨울철 곰팡이 제거 순서", "곰팡이 제거", ("결로 관리", "환기 방법", "습기 제거", "벽지 관리"), TROUBLE),
             ("가" * 20, "가" * 20, ("나" * 10, "다" * 10, "라" * 10), COMPARE), ("최고의 청소기 비교", "최고의 청소기", ("청소기 1위",), COMPARE))
    LINES = ("import sys, json, hashlib", "sys.path.insert(0, sys.argv[1])", "from chanceblog_desktop.content import draft_body as db", "from chanceblog_desktop.content.candidates import Candidate",
             "from chanceblog_desktop.content.draft_options import DraftOptions", "from chanceblog_desktop.topics import channels", "specs = json.loads(sys.argv[2])",
             "options = [None, DraftOptions(price_date=('값 하나',), urls=('https://example.com/a',), message='전하는 말이에요.', must_include=('문장 하나예요.',), exclude=('광고',))]",
             "digest = hashlib.sha256()", "for topic, keyword, subs, ptype in specs:", "    for blog in ('naver_a', 'naver_b'):", "        chan = next(p for p in channels.default_profiles() if p.key == blog)",
             "        for opts in options:", "            c = Candidate.new(topic, keyword, ('naver_a', 'naver_b'), sub_keywords=tuple(subs), post_type=ptype, now='2026-11-02T03:00:00Z')",
             "            b = db.build_body(c, None, opts, today='2026-11-07', blog=blog, channel=chan)", "            digest.update(json.dumps(b.to_dict(), sort_keys=True, ensure_ascii=False).encode('utf-8'))",
             "print(digest.hexdigest())")

    def digest_here(self):
        digest = hashlib.sha256()
        options = [None, DraftOptions(price_date=("값 하나",), urls=("https://example.com/a",), message="전하는 말이에요.", must_include=("문장 하나예요.",), exclude=("광고",))]
        for topic, keyword, subs, post_type in self.SPECS:
            for blog in ("naver_a", "naver_b"):
                chan = next(item for item in channels.default_profiles() if item.key == blog)
                for opts in options:
                    body = db.build_body(make(topic, keyword, subs, post_type), None, opts, today=TODAY, blog=blog, channel=chan)
                    digest.update(json.dumps(body.to_dict(), sort_keys=True, ensure_ascii=False).encode("utf-8"))
        return digest.hexdigest()

    def test_twelve_candidates_with_tags_and_options_give_the_same_text_in_processes_with_different_hash_seeds(self):
        specs = json.dumps([[topic, keyword, list(subs), post_type] for topic, keyword, subs, post_type in self.SPECS], ensure_ascii=False)
        hashes = {"이 프로세스": self.digest_here()}
        for seed in ("0", "1", "31337", "424242"):
            env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
            done = subprocess.run([sys.executable, "-X", "utf8", "-c", chr(10).join(self.LINES), str(ROOT / "src"), specs], capture_output=True, text=True, env=env, timeout=240, encoding="utf-8")
            self.assertEqual(done.returncode, 0, done.stderr[-500:])
            hashes[f"시드 {seed}"] = done.stdout.strip()
        self.assertEqual(len(set(hashes.values())), 1, hashes)

    def test_the_tags_and_sub_keywords_are_built_in_a_fixed_order_from_ordered_sources(self):
        """집합 순서 의존의 직접 증거 — 태그·보조 키워드를 만드는 함수가 같은 입력에서 늘 같은 순서를 돌려준다(여러 번·집합 순서를 뒤집어도)."""
        body_one = body_of(make("노트북 주변기기 정리", "노트북 거치대", ("거치대 추천", "노트북 스탠드", "높이 조절", "각도 조절", "접이식"), INFO))
        orders = {tuple(body_of(make("노트북 주변기기 정리", "노트북 거치대", ("거치대 추천", "노트북 스탠드", "높이 조절", "각도 조절", "접이식"), INFO)).tags) for _ in range(5)}
        self.assertEqual(orders, {tuple(body_one.tags)})
        self.assertGreaterEqual(len(body_one.tags), 5)
        self.assertEqual(body_one.sub_keywords[:5], ("거치대 추천", "노트북 스탠드", "높이 조절", "각도 조절", "접이식"))      # 후보가 준 순서 그대로


class SimilarityGuardTest(unittest.TestCase):
    """독립 검증 M2 — 틀로 만든 글은 같은 후보를 두 블로그로 만든 글이나 같은 블로그의 같은 유형 다른 후보 글과 서로 닮는다(`check/similarity` 가 모두 '높음'). 지금 수준을 회귀 방지 상한으로 못박는다 —
    상한은 측정값 바로 위이고, 틀의 변형을 늘려 더 낮추면 이 상한을 함께 낮춘다(D-269 한계: 초안 화면 묶음에서 기존 글과 유사도 경고)."""
    KEYWORDS = ("청소기", "공기청정기", "노트북", "키보드", "공유기", "노션", "챗봇", "파이썬", "제주 숙소", "도서관", "박물관", "곰팡이 제거", "결로", "독서 습관", "시간 관리", "글쓰기", "다이어트", "영양제")
    MAX_SAME_CANDIDATE_TWO_BLOGS, MAX_SAME_CANDIDATE_PEAK = 0.78, 0.90                      # 측정값: 평균 0.775·최대 0.889 (90쌍)
    MAX_SAME_BLOG_OTHER_CANDIDATES, MAX_OTHER_PEAK = 0.83, 0.97                             # 측정값: 평균 0.826·최대 0.966 (45쌍)

    @staticmethod
    def comparable(body):
        from chanceblog_desktop.check import similarity as sim
        intro = body.blocks[0].paragraphs[0] if body.blocks and body.blocks[0].paragraphs else ""
        return sim.Comparable(body.selected_title, body.body_text, tuple(body.tags), (), "", intro)

    def measure(self):
        from chanceblog_desktop.check import similarity as sim
        same, other = [], []
        by_type = {post_type: [] for post_type in POST_TYPES}
        for keyword in self.KEYWORDS:
            for post_type in POST_TYPES:
                candidate = make(f"{keyword} 정리", keyword, (), post_type)
                first = body_of(candidate, profile("naver_a"), None, "naver_a", channel=channel("naver_a"))
                second = body_of(candidate, profile("naver_b"), None, "naver_b", channel=channel("naver_b"))
                same.append(sim.compare(self.comparable(first), self.comparable(second)).body)
                by_type[post_type].append(first)
        for bodies in by_type.values():
            for index in range(0, len(bodies) - 1, 2):
                other.append(sim.compare(self.comparable(bodies[index]), self.comparable(bodies[index + 1])).body)
        return same, other

    def test_the_body_similarity_does_not_get_looser_than_it_is_now(self):
        same, other = self.measure()
        self.assertEqual((len(same), len(other)), (90, 45))
        with self.subTest("같은 후보를 두 블로그로"):
            self.assertLessEqual(sum(same) / len(same), self.MAX_SAME_CANDIDATE_TWO_BLOGS, sum(same) / len(same))
            self.assertLessEqual(max(same), self.MAX_SAME_CANDIDATE_PEAK, max(same))
        with self.subTest("같은 블로그·같은 유형의 다른 후보"):
            self.assertLessEqual(sum(other) / len(other), self.MAX_SAME_BLOG_OTHER_CANDIDATES, sum(other) / len(other))
            self.assertLessEqual(max(other), self.MAX_OTHER_PEAK, max(other))
        with self.subTest("글자까지 같은 글은 없다"):
            self.assertLess(max(same), 0.999)
            self.assertLess(max(other), 0.999)


if __name__ == "__main__":
    unittest.main()
