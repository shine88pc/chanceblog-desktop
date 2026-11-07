"""규칙 기반 본문의 문단 틀 모음(`content/body_library.py`·`body_lib_*.py`·`body_blocks.py`)과 분야별 확인할 항목(`body_bank.py`) 시험.

지키는 것:
  1) **구조**: 글 유형 5종 모두 소제목 단계가 빠짐없이 있고 단계마다 문단 틀 셋·문단마다 문장 칸 둘에서 넷, 라이브러리에 쓰이지 않는 단계가 없다. 소제목이 되는 단계는 `post_types` 의 틀이나 더하는 단계에 있다.
  2) **틀 위생(모든 문장 틀)**: 한 문장이고 `.`·`?` 로 끝나며 숫자·백슬래시·겹친 공백이 없고, 자리 이름은 아는 것뿐이며, 해요체 서술어는 합니다체로 모두 바뀐다(`~요.` 로 남는 끝은 `~세요`·`~까요` 뿐). 같은 글 유형 안에서 같은 문장이 두 번 나오지 않는다.
  3) **지어내지 않는다**: 어떤 분야·말투·키워드로 채워도 `check/claims.py` 의 `find_claims`(위반 7가지 + 확인 권장 4가지)가 0건이고, 최상급·효능·평가·협찬·1인칭 체험·시점 낱말이 틀 어디에도 없다. 분야별 확인할 항목도 같다.
  4) **분야 읽기**: 낱말에서 분야를 읽고(긴 낱말이 무겁다·영문은 낱말 단위·한글도 낱말 경계로만), 못 읽거나 둘 이상이 비슷하게 읽히면 일반, 협찬 가능 분야 태그와 맞는지, 건강·금융·법률 낱말(넓힌 목록)과 단정·최상급·효과 낱말을 찾는다.
  5) **틀은 분야 중립**(독립 검증 M1): 틀의 고정 글에는 기기·숙소 같은 한 분야 전용 낱말이 없고 분야별 목록(`bb.BANKS`)에만 있다. 목록·틀·소제목·꼬리·태그에 영문·숫자·브랜드(고유명사)가 없다. 시험의 금지 낱말은 예방·완화·누구나·절대·best·복용·투자·제휴 같은 낱말까지 넓혔다.
네트워크·파일 없이 돈다.
"""
import itertools
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.check import claims  # noqa: E402
from chanceblog_desktop.content import body_bank as bb  # noqa: E402
from chanceblog_desktop.content import body_blocks as blk  # noqa: E402
from chanceblog_desktop.content import body_lang as bl  # noqa: E402
from chanceblog_desktop.content import body_library as lib  # noqa: E402
from chanceblog_desktop.content import post_types as pt  # noqa: E402

TYPES = pt.POST_TYPES if hasattr(pt, "POST_TYPES") else (pt.INFO, pt.COMPARE, pt.TROUBLE, pt.PRODUCT, pt.PLACE)
TYPES = (pt.INFO, pt.COMPARE, pt.TROUBLE, pt.PRODUCT, pt.PLACE)
SLOT_NAMES = {"kw", "sub1", "sub2", "aud", "thing", "N", "C", "K", "M", "Z", "W", "P", "I", "F", "B"} | {f"{role}{number}" for role in "bcmzwpig" for number in range(1, 5)} | {"f1", "f2", "f3"}
# 틀 어디에도 없어야 하는 낱말 — 최상급·효능·평가·협찬·1인칭 체험·시점·시장 낱말
BANNED = ("가장", "최고", "최저", "최상", "최대", "최신", "제일", "1위", "완벽", "압도", "역대", "무조건", "반드시", "확실", "완전", "즉시", "효과", "효능", "치료", "치유", "개선", "완치", "보장", "저렴", "가성비", "비싼",
          "할인", "협찬", "제공받", "원고료", "체험단", "광고", "지원받", "소정의", "써 보니", "써봤", "써 봤", "사용해 보니", "다녀왔", "구매했", "샀어요", "직접 써", "직접 사용",
          "직접 먹", "직접 가", "올해", "작년", "내년", "지난해", "어제", "오늘", "요즘", "다양한", "다양하게", "솔직", "추천", "인기", "유명",
          # 독립 검증 M5 로 더한 낱말 — 효능(예방·완화·호전·회복·해소)·단정(누구나·항상·언제나·전혀·결코·절대)·순위(best·top·베스트·넘버원)·의료·금융·법률 행위(복용·섭취·투자·수익·소송)·제휴(제휴·수수료)
          "예방", "완화", "호전", "회복", "해소", "누구나", "항상", "언제나", "전혀", "결코", "절대", "best", "top", "베스트", "넘버원", "복용", "섭취", "투자", "수익", "소송", "제휴", "수수료")
# 틀의 고정 글에 없어야 하는 분야 전용 낱말 — 기기(화면·백업·전원·내부 부품·눌러 보기·중요한 자료·검색창)·제품(어디에 쓰는지)·숙소(체크인·체크아웃·결제 전)·수리(개조·분해) 같은 한 분야에서만 맞는 말은
# 분야별 목록(`bb.BANKS`)의 항목으로만 들어간다(독립 검증 M1 — 문제 해결형·정보형·장소형 글이 곰팡이·도서관 글에도 같은 기기·숙소 문장을 되풀이했다).
DOMAIN_ONLY = ("화면", "눌러", "백업", "전원", "내부 부품", "중요한 자료", "검색창", "어디에 쓰는지", "쓰는 사람", "체크인", "체크아웃", "결제 전", "개조", "열어 보", "분해나", "분해해")
# 분야 목록·틀·소제목·꼬리·태그에 없어야 하는 고유명사(브랜드·상호) — 낱말 목록과 글자 부류(영문·숫자 없음)를 함께 본다
BRAND_WORDS = ("삼성", "엘지", "애플", "구글", "네이버", "카카오", "쿠팡", "아마존", "마이크로소프트", "다이소", "이케아", "나이키", "현대", "롯데", "신세계", "당근", "배민", "한화", "주식회사", "닷컴", "코리아")
FIRST_PERSON = re.compile("(?<![가-힣])(?:제가|저는|저도|저희|우리는|우리가|내가)")                 # 낱말 앞머리의 1인칭 — '문제가'·'주제가' 속의 '제가' 는 1인칭이 아니다
NEUTRAL_END = ("세요", "까요")
KEYWORDS = ("무선 청소기", "노트북", "로컬 AI 그래픽카드", "제주 숙소 예약", "곰팡이 제거 방법", "Notion 템플릿", "GitHub", "영양제 고르는 기준", "독서 습관", "AI")


def variants_of(slot):
    return (slot,) if isinstance(slot, str) else tuple(slot)


def paragraphs_of(type_name):
    """그 글 유형의 모든 문단 틀(소제목 단계 + 도입·주의사항·마무리·한 줄 요약) → [(이름, 문단 틀)]."""
    found = []
    for key, paragraphs in lib.LIBRARY[type_name].items():
        found += [(f"{type_name}/{key}/P{number}", paragraph) for number, paragraph in enumerate(paragraphs, 1)]
    for style, slots in blk.INTRO_FIRST[type_name].items():
        found.append((f"{type_name}/intro1/{style}", slots))
    found.append((f"{type_name}/intro2", (blk.INTRO_SECOND[0], *blk.INTRO_SECOND[1].values(), blk.INTRO_SECOND[2])))
    found += [(f"{type_name}/cautions/P{number}", paragraph) for number, paragraph in enumerate(blk.CAUTIONS[type_name], 1)]
    found.append((f"{type_name}/closing1", blk.CLOSING_FIRST[type_name]))
    found += [(f"{type_name}/closing2/{style}", slots) for style, slots in blk.CLOSING_SECOND.items()]
    found += [(f"{type_name}/sensitive/{kind}", slots) for kind, slots in blk.SENSITIVE.items()]
    found.append((f"{type_name}/summary", (blk.SUMMARY[type_name],)))
    return found


def templates_of(type_name):
    return [(name, template) for name, paragraph in paragraphs_of(type_name) for slot in paragraph for template in variants_of(slot)]


def all_templates():
    seen = set()
    for type_name in TYPES:
        for name, template in templates_of(type_name):
            if template not in seen:
                seen.add(template)
                yield name, template


def sample_values(domain, keyword, offset):
    bank = bb.BANKS[domain]
    values = {"kw": keyword, "sub1": "보조 주제", "sub2": "둘째 주제", "aud": "이 주제를 처음 접하는 일반 사용자", "thing": bb.THING[domain], "N": "핵심 개념, 확인할 기준, 활용 방법"}
    for role, prefix, count in (("C", "c", 4), ("M", "m", 3), ("Z", "z", 3), ("W", "w", 3), ("P", "p", 3), ("I", "i", 3), ("B", "b", 3)):
        chosen = bb.pick(bank[role], offset, count)
        for number, text in enumerate(chosen, 1):
            values[f"{prefix}{number}"] = text
        values[role] = bl.listing(chosen[:3])
    for number, (situation, criterion) in enumerate(bb.pick(bank["F"], offset, 3), 1):
        values[f"f{number}"], values[f"g{number}"] = situation, criterion
    values["K"] = bl.listing(bb.pick(bank["C"], offset + 1, 4))
    return values


class StructureTest(unittest.TestCase):
    def test_every_type_has_every_body_step_with_three_paragraphs_of_two_to_four_slots(self):
        for type_name in TYPES:
            self.assertEqual(set(lib.LIBRARY[type_name]), set(lib.BODY_STEPS[type_name]), type_name)
            for key in lib.BODY_STEPS[type_name]:
                paragraphs = lib.section_texts(type_name, key)
                with self.subTest(type=type_name, step=key):
                    self.assertEqual(len(paragraphs), 3)
                    for paragraph in paragraphs:
                        self.assertTrue(2 <= len(paragraph) <= 4, paragraph)
                        for slot in paragraph:
                            self.assertTrue(all(isinstance(text, str) and text for text in variants_of(slot)))

    def test_body_step_counts_are_in_the_four_to_six_range_and_the_experience_step_keeps_them_in_it(self):
        for type_name in TYPES:
            count = len(lib.BODY_STEPS[type_name])
            self.assertTrue(lib.MIN_SECTIONS <= count <= lib.MAX_SECTIONS, type_name)
            with_experience = count + 1 - (1 if type_name in lib.DROPPED_FOR_EXPERIENCE else 0)
            self.assertLessEqual(with_experience, lib.MAX_SECTIONS, type_name)
            if type_name in lib.DROPPED_FOR_EXPERIENCE:
                self.assertIn(lib.DROPPED_FOR_EXPERIENCE[type_name], lib.BODY_STEPS[type_name])

    def test_every_step_is_in_the_post_type_template_or_the_extra_steps_and_has_headings_with_the_keyword(self):
        for type_name in TYPES:
            for key in lib.BODY_STEPS[type_name]:
                step = lib.step_of(type_name, key)
                with self.subTest(type=type_name, step=key):
                    self.assertEqual(step.key, key)
                    self.assertTrue(all("{kw}" in head for head in step.heads))
        self.assertEqual(lib.caution_step().key, "caution")
        for type_name in TYPES:
            self.assertEqual(lib.closing_step(type_name).key, "summary")
        with self.assertRaises(KeyError):
            lib.step_of(pt.INFO, "없는단계")

    def test_the_closing_step_is_the_types_own_summary_when_it_has_one(self):
        self.assertIs(lib.closing_step(pt.COMPARE), pt.TEMPLATES[pt.COMPARE][-1])
        self.assertIs(lib.closing_step(pt.PRODUCT), pt.TEMPLATES[pt.PRODUCT][-1])
        self.assertIs(lib.closing_step(pt.INFO), pt.TEMPLATES[pt.INFO][-1])
        self.assertIs(lib.closing_step(pt.TROUBLE), pt.TEMPLATES[pt.INFO][-1])           # 문제 해결형·장소 정보형은 '정리' 단계가 없어 정보형의 것을 쓴다
        self.assertIs(lib.closing_step(pt.PLACE), pt.TEMPLATES[pt.INFO][-1])

    def test_every_block_pool_covers_all_five_types_and_all_intro_ending_styles(self):
        for table in (blk.INTRO_FIRST, blk.CAUTIONS, blk.CLOSING_FIRST, blk.SUMMARY, blk.KEYWORD_TAILS, blk.GENERIC_TAGS):
            self.assertEqual(set(table), set(TYPES))
        for styles in blk.INTRO_FIRST.values():
            self.assertEqual(set(styles), {"problem", "purpose", "context"})
        self.assertEqual(set(blk.INTRO_SECOND[1]), {"beginner", "practical", "expert"})
        self.assertEqual(set(blk.CLOSING_SECOND), {"summary", "checklist", "next"})
        self.assertEqual(set(blk.SENSITIVE), {"health", "finance", "legal"})
        for type_name in TYPES:
            self.assertEqual(len(blk.CAUTIONS[type_name]), 3)
            self.assertGreaterEqual(len(blk.SUMMARY[type_name]), 2)
            self.assertGreaterEqual(len(blk.GENERIC_TAGS[type_name]), 3)
            self.assertGreaterEqual(len(blk.KEYWORD_TAILS[type_name]), 4)

    def test_the_plan_style_names_the_library_uses_are_the_ones_the_plan_knows(self):
        from chanceblog_desktop.content import draft_plan as dp
        self.assertEqual({name for name, _words in dp.INTRO_STYLES}, set(blk.INTRO_FIRST[pt.INFO]))
        self.assertEqual({name for name, _words in dp.DIFFICULTY_STYLES}, set(blk.INTRO_SECOND[1]))
        self.assertEqual({name for name, _words in dp.ENDING_STYLES}, set(blk.CLOSING_SECOND))


class HygieneTest(unittest.TestCase):
    def test_every_template_is_one_sentence_ending_with_a_period_or_a_question_mark(self):
        count = 0
        for name, template in all_templates():
            with self.subTest(where=name, template=template):
                self.assertTrue(template.endswith((".", "?")))
                self.assertEqual(len(claims.split_sentences(template)), 1)
                self.assertEqual(template, template.strip())
                self.assertNotIn("  ", template)
            count += 1
        self.assertGreaterEqual(count, 330)

    def test_slot_names_are_known_and_n_is_only_in_the_intro_and_k_only_where_the_values_have_it(self):
        for type_name in TYPES:
            for name, template in templates_of(type_name):
                names = set(bl.slots_of(template))
                with self.subTest(where=name, template=template):
                    self.assertLessEqual(names, SLOT_NAMES)
                    if "N" in names:
                        self.assertIn("/intro2", name)
                    self.assertFalse(names & {"g4", "f4"})

    def test_no_digit_no_backslash_no_banned_word_in_any_template(self):
        digit = re.compile("[0-9]")
        for name, template in all_templates():
            fixed = bl.skeleton(template)                                              # 자리 이름(`{c1}`)의 숫자는 글이 아니다
            with self.subTest(where=name, template=template):
                self.assertIsNone(digit.search(fixed))
                self.assertNotIn(chr(92), template)
                for word in BANNED:
                    self.assertNotIn(word, fixed, word)
                self.assertIsNone(FIRST_PERSON.search(fixed))

    def test_no_template_uses_the_clipped_geo_ending_that_turns_into_a_broken_hapsyo(self):
        """'~한 거예요' 는 합니다체로 바꾸면 '~한 거입니다' 가 되어 어색하다 — 틀 어디에도 줄임 '거' 꼴(거예요·거에요·거입니다·거죠)이 없고, 풀어 쓴 '것이에요'·'글이에요' 는 합니다체에서 '것입니다'·'글입니다' 가 된다."""
        clipped = re.compile("(?:^| )거(?:예요|에요|입니다|죠|지요)")
        count = 0
        for name, template in all_templates():
            sample = bl.fill(template, {slot: "표본" for slot in bl.slots_of(template)})
            with self.subTest(where=name, template=template):
                for text in (template, sample, bl.to_hapsyo(sample)):
                    self.assertIsNone(clipped.search(text), text)
            count += 1
        self.assertGreaterEqual(count, 330)
        self.assertEqual(bl.to_hapsyo("순서를 정리한 글이에요."), "순서를 정리한 글입니다.")
        self.assertEqual(bl.to_hapsyo("기준을 먼저 세우는 것이에요."), "기준을 먼저 세우는 것입니다.")
        self.assertIsNotNone(clipped.search(bl.to_hapsyo("정리한 거예요.")))                  # 시험이 잡으려는 꼴이 실제로 그렇게 바뀐다는 근거

    def test_every_haeyo_ending_converts_to_hapsyo_and_only_the_neutral_endings_stay(self):
        count = 0
        for name, template in all_templates():
            values = {slot: "표본" for slot in bl.slots_of(template)}
            sample = bl.fill(template, values)
            converted = bl.to_hapsyo(sample)
            body, punct = bl.split_ending(converted)
            with self.subTest(where=name, template=template):
                if body.endswith("요"):
                    self.assertTrue(body.endswith(NEUTRAL_END), f"합니다체로 바뀌지 않는 끝: {body[-6:]}")
                self.assertTrue(punct in (".", "?"))
            count += 1
        self.assertGreaterEqual(count, 330)

    def test_the_converted_sentences_have_no_leftover_haeyo_inside_a_sentence(self):
        for name, template in all_templates():
            sample = bl.to_hapsyo(bl.fill(template, {slot: "표본" for slot in bl.slots_of(template)}))
            with self.subTest(where=name, template=template):
                self.assertIsNone(re.search("(?:어요|아요|해요|예요|에요|돼요|져요)[ ,]", sample), sample)

    def test_no_sentence_repeats_inside_one_post_type_pool(self):
        for type_name in TYPES:
            texts = [template for _name, template in templates_of(type_name)]
            duplicated = sorted({text for text in texts if texts.count(text) > 1})
            self.assertEqual(duplicated, [], type_name)

    def test_the_sentences_of_one_type_are_not_all_the_same_frame(self):
        """문장 틀 다양성: 한 글 유형의 문장 틀 가운데 같은 첫 두 낱말로 시작하는 것이 전체의 12% 를 넘지 않는다(같은 문장 틀을 되풀이하지 않는다)."""
        for type_name in TYPES:
            starts = [" ".join(template.split(" ")[:2]) for _name, template in templates_of(type_name)]
            worst = max(starts.count(start) for start in set(starts))
            with self.subTest(type=type_name):
                self.assertLessEqual(worst / len(starts), 0.12, max(set(starts), key=starts.count))


class CollapseTest(unittest.TestCase):
    def test_no_template_filled_with_a_bank_item_loses_a_word_to_the_repeated_word_folding(self):
        """같은 낱말을 하나로 접는 도우미(`collapse`)는 키워드가 틀의 낱말과 겹칠 때를 위한 것이다 — 분야 목록의 항목이 틀의 앞 낱말과 겹쳐 문장이 바뀌면 안 된다
        ('예를 들어' + '들어가는 비용과 시간' → '예를 들어가는 …', '설치 공간이, 공간이 좁은 집이라면' → '설치 공간이 좁은 집이라면'). 겹치지 않는 키워드로 모든 틀 × 분야 × 항목 자리를 채워 본다."""
        checked = changed = 0
        for name, template in all_templates():
            for domain in bb.DOMAINS:
                for offset in range(9):
                    values = sample_values(domain, "무선 청소기", offset)
                    if not all(values.get(slot) for slot in bl.slots_of(template)):
                        continue
                    filled = " ".join(bl.fill(template, values).split())
                    checked += 1
                    if bl.collapse(filled) != filled:
                        changed += 1
                        self.fail(f"{name} · {domain} · {offset}: {filled} → {bl.collapse(filled)}")
        self.assertGreater(checked, 3000)
        self.assertEqual(changed, 0)


class NoFabricationTest(unittest.TestCase):
    def test_every_template_filled_for_every_domain_style_and_keyword_has_zero_findings(self):
        total = 0
        for index, (name, template) in enumerate(all_templates()):
            for domain_index, domain in enumerate(bb.DOMAINS):
                for keyword in KEYWORDS[index % 4::4]:                                # 틀마다 키워드 두세 개씩 돌려 가며(전체 조합은 생성기 시험이 본다)
                    values = sample_values(domain, keyword, offset=index + domain_index)
                    for style in bl.STYLES:
                        text = bl.tidy(bl.in_style(bl.collapse(bl.fill(template, values)), style))
                        found = claims.find_claims([text])
                        total += 1
                        if found:
                            self.fail(f"{name} · {domain} · {style} · {keyword}: {found} | {text}")
        self.assertGreater(total, 10000)

    def test_every_template_has_zero_findings_with_the_same_text_as_one_paragraph(self):
        """문장을 문단으로 이어 붙여도(앞뒤 문장과 만나서 생기는 뜻밖의 걸림 — 띄어쓰기를 지우면 낱말이 이어진다) 걸리지 않는다."""
        for type_name in TYPES:
            for name, paragraph in paragraphs_of(type_name):
                for domain in ("appliance", "software", "generic"):
                    values = sample_values(domain, "무선 청소기", 2)
                    sentences = []
                    for slot in paragraph:
                        for template in variants_of(slot):
                            if all(values.get(item) for item in bl.slots_of(template)):
                                sentences.append(bl.tidy(bl.collapse(bl.fill(template, values))))
                                break
                    with self.subTest(where=name, domain=domain):
                        self.assertEqual(claims.find_claims(" ".join(sentences)), ())

    def test_the_headings_of_every_step_are_clean_for_both_voices(self):
        for type_name in TYPES:
            steps = [lib.step_of(type_name, key) for key in lib.BODY_STEPS[type_name]] + [lib.caution_step(), lib.closing_step(type_name), pt.EXPERIENCE_STEPS[type_name]]
            for step in steps:
                for voice in (0, 1):
                    for keyword in KEYWORDS:
                        text = bl.collapse(step.heads[voice].replace("{kw}", keyword))
                        with self.subTest(type=type_name, step=step.key, voice=voice, keyword=keyword):
                            self.assertEqual(claims.find_claims([text]), ())


class BankTest(unittest.TestCase):
    def test_every_bank_has_all_eight_lists_with_unique_clean_items(self):
        digit = re.compile("[0-9]")
        for domain, banks in bb.BANKS.items():
            self.assertEqual(set(banks), {"C", "M", "Z", "W", "P", "F", "I", "B"}, domain)
            for role, items in banks.items():
                with self.subTest(domain=domain, role=role):
                    self.assertGreaterEqual(len(items), 3)
                    flat = [part for item in items for part in (item if isinstance(item, tuple) else (item,))]
                    self.assertEqual(len(flat), len(set(flat)))
                    for text in flat:
                        self.assertEqual(text, text.strip())
                        self.assertIsNone(digit.search(text))
                        self.assertNotIn(chr(92), text)
                        self.assertLessEqual(len(text), 40)
                        for word in BANNED:
                            self.assertNotIn(word, text, word)
                        self.assertIsNone(FIRST_PERSON.search(text))
                        self.assertEqual(claims.find_claims([text]), (), text)

    def test_the_situation_criterion_pairs_are_pairs_of_two_texts(self):
        for domain, banks in bb.BANKS.items():
            for pair in banks["F"]:
                with self.subTest(domain=domain, pair=pair):
                    self.assertEqual(len(pair), 2)
                    self.assertTrue(all(isinstance(text, str) and text for text in pair))

    def test_a_bank_item_fits_inside_every_slot_frame_it_is_used_in(self):
        """항목을 문장에 넣었을 때 조사가 맞고(받침에 따라) 위반이 없다 — 항목 × 조사 틀."""
        frames = ("{x:은/는} 확인해요.", "{x:을/를} 확인해요.", "{x:이/가} 있어요.", "{x:이에요/예요}.", "{x:과/와} 비교해요.", "{x:으로/로} 정리해요.", "{x:이라면/라면} 좋아요.")
        for domain, banks in bb.BANKS.items():
            for role, items in banks.items():
                for item in items:
                    for text in (item if isinstance(item, tuple) else (item,)):
                        for frame in frames:
                            sentence = bl.fill(frame, {"x": text})
                            with self.subTest(domain=domain, item=text, frame=frame):
                                self.assertEqual(claims.find_claims([sentence]), ())
                                self.assertNotIn("(", sentence)

    def test_pick_takes_distinct_items_from_a_start_position_and_wraps(self):
        items = ("가", "나", "다", "라")
        self.assertEqual(bb.pick(items, 0, 3), ("가", "나", "다"))
        self.assertEqual(bb.pick(items, 3, 3), ("라", "가", "나"))
        self.assertEqual(bb.pick(items, 10, 2), ("다", "라"))
        self.assertEqual(bb.pick(items, 1, 9), ("나", "다", "라", "가"))

    def test_every_domain_has_a_thing_noun_and_a_name_and_focus_tags(self):
        self.assertEqual(set(bb.THING), set(bb.DOMAINS))
        self.assertEqual(set(bb.DOMAIN_KO), set(bb.DOMAINS))
        self.assertEqual(set(bb.FOCUS_TAGS), set(bb.DOMAINS))
        self.assertEqual(bb.DOMAINS[-1], bb.GENERIC)


class DomainTest(unittest.TestCase):
    def test_keywords_are_read_into_their_domain(self):
        cases = (("무선 청소기", "appliance"), ("제습기 선택", "appliance"), ("에어프라이어", "appliance"), ("보일러 점검", "appliance"), ("노트북", "pc_hw"), ("로컬 AI 그래픽카드", "pc_hw"), ("모니터 암", "pc_hw"),
                 ("SSD 교체", "pc_hw"), ("RTX 4060", "generic"), ("ChatGPT 요금제", "software"), ("업무 자동화", "software"), ("GitHub Actions", "software"), ("Notion", "software"), ("Python 설치", "software"),
                 ("제주 숙소", "travel"), ("당일치기 여행", "travel"), ("곰팡이 제거", "life"), ("겨울 난방비", "life"), ("독서 습관", "generic"), ("시간 관리", "generic"), ("이 주제", "generic"))
        for text, domain in cases:
            with self.subTest(text=text):
                self.assertEqual(bb.domain_of((text,)), domain)

    def test_a_longer_word_weighs_more_so_the_graphic_card_beats_ai(self):
        self.assertEqual(bb.domain_of(("로컬 AI 그래픽카드",)), "pc_hw")
        self.assertEqual(bb.domain_of(("AI 서비스 요금제",)), "software")

    def test_english_words_count_only_as_whole_words(self):
        self.assertEqual(bb.domain_of(("email 정리",)), "generic")             # 'ai' 가 email 속에 든 것은 신호가 아니다
        self.assertEqual(bb.domain_of(("maintain 방법",)), "generic")
        self.assertEqual(bb.domain_of(("AI 정리",)), "software")
        self.assertEqual(bb.domain_of(("pc 점검",)), "pc_hw")
        # 독립 검증 H1 로 의도적 갱신: 이전에는 '프로그램' 을 소프트웨어 낱말로 읽었으나 '운동 프로그램' 같은 글을 소프트웨어 틀로 읽어 엉뚱한 문장이 나왔다 — 뜻이 둘로 갈리는 낱말은 이제 신호가 아니다
        self.assertEqual(bb.domain_of(("프로그램 사용법",)), "generic")
        self.assertNotEqual(bb.domain_of(("프로그램 사용법",)), "pc_hw")                # '램' 이 프로그램 속에 든 것은 신호가 아니다

    def test_the_domain_is_read_from_the_candidates_words_only_never_from_other_texts(self):
        """독립 검증 H1 로 의도적 갱신: 이전 시험(`…fallback_texts_are_read_only_when_the_keyword_says_nothing`)은 키워드가 아무 말도 안 하면 프로필의 주제·역할 글로 분야를 짐작하게 했다 — 그 짐작이 건강 글에 가전 문장을
        쓰게 만들었으므로 이제 후보 밖의 글은 분야를 정하지 못하고(함수가 그런 인자를 받지 않는다), 못 읽으면 일반이다."""
        self.assertEqual(bb.domain_of(("독서 습관",)), "generic")
        self.assertEqual(bb.domain_of(()), "generic")
        self.assertEqual(bb.domain_of(("",)), "generic")
        with self.assertRaises(TypeError):
            bb.domain_of(("독서 습관",), ("가전 제품 소개",))
        self.assertEqual(bb.domain_of(("노트북",)), "pc_hw")

    def test_focus_tags_match_the_channel_profile_values(self):
        self.assertTrue(bb.focus_hit("appliance", ("small_appliance",)))
        self.assertTrue(bb.focus_hit("pc_hw", ("pc_parts",)))
        self.assertTrue(bb.focus_hit("pc_hw", ("pc_peripheral", "lodging_travel")))
        self.assertTrue(bb.focus_hit("software", ("work_automation",)))
        self.assertTrue(bb.focus_hit("travel", ("lodging_travel",)))
        self.assertFalse(bb.focus_hit("appliance", ("pc_parts",)))
        self.assertFalse(bb.focus_hit("life", ("small_appliance", "pc_parts", "ai_service")))
        self.assertFalse(bb.focus_hit("generic", ("small_appliance",)))
        self.assertFalse(bb.focus_hit("appliance", ()))
        self.assertFalse(bb.focus_hit("appliance", None))

    def test_sensitive_words_are_found_by_kind(self):
        for text, kind in (("영양제 고르는 기준", "health"), ("두통 관리", "health"), ("주식 투자 기초", "finance"), ("대출 비교", "finance"), ("전세 계약서 확인", "legal"), ("저작권 안내", "legal"),
                           ("무선 청소기", None), ("노트북 추천", None), ("", None)):
            with self.subTest(text=text):
                self.assertEqual(bb.sensitive_kind((text,)), kind)
        self.assertEqual(bb.sensitive_kind(("보험 대출 영양제",)), "finance")          # 낱말이 가장 많은 쪽(동점이면 건강 → 금융 → 법률)
        self.assertEqual(bb.sensitive_kind(("영양제 대출",)), "health")

    def test_the_domain_tables_have_every_domain_and_no_empty_trigger(self):
        for table in (bb.TRIGGERS_KO, bb.TRIGGERS_EN):
            self.assertLessEqual(set(table), set(bb.DOMAINS))
            for words in table.values():
                self.assertTrue(all(word and word == word.strip() for word in words))
        for word in itertools.chain(*bb.TRIGGERS_EN.values()):
            self.assertEqual(word, word.lower())


def flat_items(banks):
    """분야 하나의 목록들에 든 모든 글(상황·기준 쌍은 두 글 모두)."""
    return [text for items in banks.values() for item in items for text in (item if isinstance(item, tuple) else (item,))]


class DomainNeutralTest(unittest.TestCase):
    """독립 검증 M1 — 틀의 고정 글은 어느 분야의 글에도 맞는 중립 문장이고, 기기·숙소 같은 한 분야 전용 낱말은 분야별 목록의 항목으로만 들어간다."""
    DEVICE_WORDS = ("백업", "전원", "화면", "운영체제", "드라이버", "펌웨어", "컴퓨터", "계정", "접속", "소비전력", "연결 단자", "플러그", "설정")

    def test_no_template_has_a_domain_only_word(self):
        count = 0
        for name, template in all_templates():
            fixed = bl.skeleton(template)
            count += 1
            with self.subTest(where=name, template=template):
                for word in DOMAIN_ONLY:
                    self.assertNotIn(word, fixed, word)
        self.assertGreaterEqual(count, 330)

    def test_the_device_words_moved_into_the_device_banks_and_the_other_banks_have_none(self):
        """전용 문장이 없어진 것이 아니라 자리를 옮겼다 — 기기 분야의 '손대기 전에 챙길 것' 목록에는 백업이 있고, 기기가 아닌 분야의 목록 어디에도 기기 낱말이 없다."""
        for domain in ("pc_hw", "software"):
            self.assertTrue(any("백업" in text for text in bb.BANKS[domain]["B"]), domain)
        self.assertTrue(any("전원" in text for text in bb.BANKS["appliance"]["B"]))
        for domain in ("travel", "life", "generic"):
            for text in flat_items(bb.BANKS[domain]):
                with self.subTest(domain=domain, text=text):
                    for word in self.DEVICE_WORDS:
                        self.assertNotIn(word, text, word)
        for text in flat_items(bb.BANKS["travel"]):
            for word in ("체크인", "체크아웃", "결제"):
                self.assertNotIn(word, text, word)                                      # 숙소가 아닌 장소(도서관·공원)의 글에 숙소 문장이 나오지 않게

    def test_pick_ordered_returns_the_same_items_as_pick_in_list_order(self):
        items = ("가", "나", "다", "라", "마", "바")
        for start in range(12):
            for count in (1, 2, 3, 6, 9):
                picked, ordered = bb.pick(items, start, count), bb.pick_ordered(items, start, count)
                with self.subTest(start=start, count=count):
                    self.assertEqual(set(picked), set(ordered))
                    self.assertEqual([items.index(item) for item in ordered], sorted(items.index(item) for item in ordered))
        self.assertEqual(bb.pick(items, 5, 3), ("바", "가", "나"))                      # pick 은 끝에서 돌아 앞뒤가 뒤바뀐다
        self.assertEqual(bb.pick_ordered(items, 5, 3), ("가", "나", "바"))

    def test_the_causes_are_listed_from_easy_to_hard_in_every_bank_so_the_order_sentence_is_true(self):
        """'확인은 쉬운 것에서 어려운 것 순으로 해요' 문단은 원인 후보(Z)를 목록 순서대로 늘어놓는다 — 목록의 마지막이 가장 어려운 항목이어야 한다(기기 분야는 부품 자체의 불량이 끝)."""
        self.assertEqual(bb.BANKS["pc_hw"]["Z"][-1], "부품 자체의 불량")
        self.assertEqual(bb.BANKS["appliance"]["Z"][-1], "내부 부품의 이상")
        self.assertEqual(bb.BANKS["pc_hw"]["Z"][0], "연결 단자나 케이블 상태")


class NoBrandTest(unittest.TestCase):
    """독립 검증 M5 — 분야 목록·틀·소제목·꼬리·태그에는 고유명사(브랜드·상호)가 없다. 분야 목록에 브랜드를 끼워 넣어도(변이) 이 시험이 잡는다."""
    LATIN_OR_DIGIT = re.compile("[A-Za-z0-9]")

    def static_texts(self):
        """글을 만드는 데 쓰이는 고정 글 전부 — (어디, 글). 틀은 자리(`{…}`)를 뺀 글이다."""
        found = [(name, bl.skeleton(template)) for name, template in all_templates()]
        found += [(f"bank/{domain}", text) for domain, banks in bb.BANKS.items() for text in flat_items(banks)]
        for type_name in TYPES:
            steps = [lib.step_of(type_name, key) for key in lib.BODY_STEPS[type_name]] + [lib.caution_step(), lib.closing_step(type_name), pt.EXPERIENCE_STEPS[type_name]]
            found += [(f"heading/{type_name}/{step.key}", text.replace("{kw}", "")) for step in steps for text in (*step.heads, step.name)]
        found += [("thing", text) for text in bb.THING.values()]
        found += [("tails", text) for table in (*blk.KEYWORD_TAILS.values(), *blk.GENERIC_TAGS.values(), blk.SENSITIVE_TAILS, blk.SENSITIVE_TAGS) for text in table]
        return found

    def test_no_latin_letter_digit_or_brand_word_in_any_static_text(self):
        texts = self.static_texts()
        self.assertGreater(len(texts), 700)
        for where, text in texts:
            with self.subTest(where=where, text=text):
                self.assertIsNone(self.LATIN_OR_DIGIT.search(text))
                for word in BRAND_WORDS:
                    self.assertNotIn(word, text, word)

    def test_the_banned_words_also_hold_for_the_headings_the_tails_and_the_tags(self):
        for where, text in self.static_texts():
            if where.startswith(("heading/", "tails")):
                with self.subTest(where=where, text=text):
                    for word in BANNED:
                        self.assertNotIn(word, text, word)

    def test_the_brand_check_really_catches_a_brand_in_a_bank_item(self):
        """시험이 빈 껍데기가 아님을 보인다 — 분야 목록에 브랜드를 끼운 것(검증자의 변이 M57 꼴)을 같은 검사에 넣으면 걸린다."""
        self.assertTrue(any(word in "삼성전자 공식 누리집" for word in BRAND_WORDS))
        self.assertIsNotNone(self.LATIN_OR_DIGIT.search("LG 공식 누리집"))
        self.assertFalse(any(word in "제조사 공식 누리집" for word in BRAND_WORDS))


class DomainReadingTest(unittest.TestCase):
    """독립 검증 H1 — 한글 낱말도 낱말 경계로만 읽고, 뜻이 둘로 갈리는 낱말은 신호가 아니며, 둘 이상이 비슷하게 읽히면 일반이다."""
    AMBIGUOUS = ("프로그램", "설정", "설치", "한도", "업데이트", "오류", "코드", "계정", "구독", "요금제", "토큰", "연동", "개발", "배포", "저장소", "카페", "동네", "절약", "부품", "거치대", "쿨러", "믹서", "블렌더", "스팀", "스크립트", "방한", "배수")

    def test_a_word_is_read_at_its_own_boundaries_not_inside_other_words(self):
        for text in ("한 도시 여행", "한도시 여행"):
            self.assertEqual(bb.domain_of((text,)), "travel", text)
            self.assertEqual(bb._scores((text,))["software"], 0, text)                          # '한도시' 속의 '한도' 는 낱말이 아니다
        for text in ("모니터링 도구", "마우스피스 고르기", "여행자 보험", "청소기추천", "노트북스"):
            with self.subTest(text=text):
                self.assertEqual(bb.domain_of((text,)), "generic")

    def test_a_particle_or_a_compound_ending_still_reads_as_the_word(self):
        cases = (("청소기를 고르는 법", "appliance"), ("무선청소기", "appliance"), ("그래픽 카드를 고를 때", "pc_hw"), ("로봇청소기의 기능", "appliance"), ("수학여행 일정", "travel"), ("층간소음 줄이기", "life"),
                 ("냉장고에서 나는 냄새", "appliance"), ("제습기", "appliance"), ("제습기를", "appliance"))
        for text, domain in cases:
            with self.subTest(text=text):
                self.assertEqual(bb.domain_of((text,)), domain)

    def test_a_long_word_and_the_word_at_its_end_count_once(self):
        """'제습기' 의 끝 '습기' 를 따로 세어 생활 문제로 읽지 않는다(겹치면 긴 쪽만)."""
        self.assertEqual({domain: score for domain, score in bb._scores(("제습기",)).items() if score}, {"appliance": 3})
        self.assertEqual({domain: score for domain, score in bb._scores(("가습기를 고를 때",)).items() if score}, {"appliance": 3})
        self.assertEqual({domain: score for domain, score in bb._scores(("층간소음",)).items() if score}, {"life": 4})

    def test_ambiguous_words_are_not_signals_alone_or_together(self):
        for word in self.AMBIGUOUS:
            with self.subTest(word=word):
                self.assertEqual(bb.domain_of((word,)), "generic")
                self.assertEqual(bb.domain_of((f"{word} 방법",)), "generic")
        self.assertEqual(bb.domain_of((" ".join(self.AMBIGUOUS),)), "generic")
        for domain, words in bb.TRIGGERS_KO.items():
            for word in self.AMBIGUOUS:
                self.assertNotIn(word, words, (domain, word))

    def test_two_domains_read_about_equally_are_not_read_at_all(self):
        for text in ("곰팡이 제습기", "에어컨 곰팡이 청소", "냉장고 정리정돈"):
            with self.subTest(text=text):
                scores = sorted((score for domain, score in bb._scores((text,)).items() if domain != "generic"), reverse=True)
                self.assertLess(scores[0], bb.DOMINANCE * scores[1], scores)
                self.assertEqual(bb.domain_of((text,)), "generic")
        self.assertEqual(bb.domain_of(("노트북 소음",)), "pc_hw")                                # 3 대 2 는 읽는다
        self.assertEqual(bb.domain_of(("에어컨 소음",)), "appliance")
        self.assertEqual(bb.domain_of(("로컬 AI 그래픽카드", "GPU VRAM", "로컬 LLM")), "pc_hw")     # 같은 분야의 여러 낱말이 이긴다

    def test_the_trigger_lists_have_only_hangul_words_and_no_duplicates(self):
        seen = {}
        for table in (bb.TRIGGERS_KO, bb.SENSITIVE_WORDS):
            for domain, words in table.items():
                with self.subTest(domain=domain):
                    self.assertEqual(len(words), len(set(words)))
                    for word in words:
                        self.assertTrue(re.fullmatch("[가-힣]+(?: [가-힣]+)*", word), word)
        for domain, words in bb.TRIGGERS_KO.items():
            for word in words:
                self.assertNotIn(word, seen, (word, seen.get(word), domain))                         # 한 낱말이 두 분야에 있지 않다
                seen[word] = domain


class SensitiveAndAssertionWordsTest(unittest.TestCase):
    """독립 검증 M4 — 건강·금융·법률 낱말을 넓혔다. 단정·최상급·효과 낱말은 고정 표에서 찾는다."""
    CASES = (("당뇨", "health"), ("당뇨 관리", "health"), ("비염", "health"), ("아토피", "health"), ("관절", "health"), ("콜레스테롤", "health"), ("우울감", "health"), ("우울증 극복 방법", "health"), ("ADHD 약 대신", "health"),
             ("암 예방 식품", "health"), ("콜레스테롤 약 없이 낮추기", "health"), ("ETF", "finance"), ("etf 비교", "finance"), ("금리", "finance"), ("연말정산", "finance"), ("카드 혜택", "finance"), ("전세", "legal"),
             ("월세 계약", "legal"), ("이혼", "legal"), ("해고", "legal"), ("합의금", "legal"), ("퇴직금", "legal"), ("개인정보 처리", "legal"), ("전세 계약서 확인", "legal"))

    def test_the_words_the_verifier_found_missing_are_now_read_into_their_kind(self):
        for text, kind in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(bb.sensitive_kind((text,)), kind)

    def test_one_character_and_english_words_need_word_boundaries(self):
        for text in ("암호 관리", "암튼 정리", "netflix 요금", "isabel 안내", "물 마시기", "집 정리"):
            with self.subTest(text=text):
                self.assertIsNone(bb.sensitive_kind((text,)))
        self.assertEqual(bb.sensitive_kind(("암",)), "health")
        self.assertEqual(bb.sensitive_kind(("암을 이기는 법",)), "health")
        self.assertEqual(bb.sensitive_kind(("ISA 계좌",)), "finance")

    def test_each_kind_has_its_own_words_and_the_short_and_english_tables_match_the_kinds(self):
        self.assertEqual(set(bb.SENSITIVE_WORDS), {"health", "finance", "legal"})
        self.assertEqual(set(bb.SENSITIVE_SHORT), set(bb.SENSITIVE_WORDS))
        self.assertEqual(set(bb.SENSITIVE_EN), set(bb.SENSITIVE_WORDS))
        for kind, words in bb.SENSITIVE_WORDS.items():
            self.assertGreaterEqual(len(words), 40, kind)
            self.assertTrue(all(len(word) >= 2 for word in words), kind)                             # 한 글자 낱말은 따로(낱말 경계로만)
        for words in bb.SENSITIVE_SHORT.values():
            self.assertTrue(all(len(word) == 1 for word in words))
        for words in bb.SENSITIVE_EN.values():
            self.assertTrue(all(word == word.lower() and word.isascii() for word in words))

    def test_assertion_words_are_found_from_the_fixed_table_and_only_by_boundary_where_needed(self):
        cases = (("최고의 청소기", ("최고",)), ("가장 좋은 선택", ("가장",)), ("가장자리 정리", ()), ("청소기 1위 비교", ("1위",)), ("11위 정리", ()), ("TOP 10 노트북", ("top",)), ("베스트 제습기", ("베스트",)),
                 ("무조건 성공하는 주식", ("무조건",)), ("다이어트 즉시 효과", ("즉시", "효과")), ("무선 청소기 비교", ()), ("청소기 추천", ()), ("엑셀 완전 정복", ()), ("topology 입문", ()))
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(bb.assertion_hits((text,)), expected)
        found = bb.assertion_hits(("최고 최상 압도 완벽 역대",))
        self.assertEqual(len(found), bb.MAX_ASSERTION_SHOWN)
        self.assertTrue(set(found) <= set(bb.ASSERTION_WORDS))                                      # 입력한 글이 아니라 고정 표의 낱말이다
        self.assertEqual(bb.assertion_hits(("", "")), ())


if __name__ == "__main__":
    unittest.main()
