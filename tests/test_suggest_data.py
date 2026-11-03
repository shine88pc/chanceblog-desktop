"""제안이 쓰는 순수 자료(`content/suggest_data.py` — 계절·시기 표와 글 유형별 틀) 시험.

지키는 것:
  1) 계절표는 12개월 전수이고 월마다 8~15개이며 각 항목에 이유가 있다. 숫자(연도·가격·통계)를 한 글자도 쓰지 않는다 — 해마다 되풀이되는 일반 시기 주제뿐이다.
  2) 모든 틀 × 여러 받침의 씨앗 × 모든 시기 항목을 실제로 조합해 보아 ① 경험을 전제한 말(후기·방문·체험·써 봤다 …) ② 결과를 약속하는 표현·위험한 표기 ③ 조사 오류 ④ 같은 낱말의 되풀이 ⑤ 남은 `{}` 자리 ⑥ 후보로 저장할 수 없는 모양이 **하나도 없다**
     (첫 조합만 보고 멈추지 않는다 — 모든 조합을 본다). 조사의 기대값은 글자 분해(NFD)로 시험이 따로 구한다.
  3) 글 유형 다섯 모두에 틀이 있고, 시기 틀에만 `{계절}` 이 있으며, 틀의 이름은 겹치지 않는다.
"""
import re
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content import suggest_data as data  # noqa: E402
from chanceblog_desktop.content import suggest_text as tx  # noqa: E402
from chanceblog_desktop.content.profiles import POST_TYPES, find_markup  # noqa: E402

# 경험을 전제한 말 — 시험이 따로 가진 목록(자료에서 복사하지 않는다)
EXPERIENCE = ("후기", "방문기", "방문 후", "다녀", "체험", "사용기", "써봤", "써 봤", "해봤", "해 봤", "직접 써", "직접 해", "리뷰", "솔직", "내돈", "느낀", "경험담", "먹어봤", "가봤", "가 봤", "다녀온", "사용해 본", "써본")
SLOT = re.compile(r"\{(주제|계절)(?::([^{}]*))?\}")
SEEDS = ["카드", "보험", "서울 맛집", "보일러", "공부2", "공부7", "공부10", "AI", "LED", "SNS", "MBTI", "CNN", "C++", "가계부", "난방비", "겨울 난방 관리", "다이어트 식단", "자동차 보험"]
ENTRY_WORDS = [item.word for entries in data.SEASONS.values() for item in entries]


def expected_particle(word, kind):
    """시험이 따로 아는 조사 — 한글은 글자 분해(NFD)로, 숫자·영문은 읽는 소리 표로."""
    last = [char for char in unicodedata.normalize("NFKC", word) if char.isalnum()][-1]
    if "가" <= last <= "힣":
        parts = unicodedata.normalize("NFD", last)
        tail = "" if len(parts) < 3 else "ㄹ" if parts[2] == "ᆯ" else "x"
    elif last.isdigit():
        tail = {"0": "x", "1": "ㄹ", "2": "", "3": "x", "4": "", "5": "", "6": "x", "7": "ㄹ", "8": "ㄹ", "9": ""}[last]
    else:
        tail = {"l": "ㄹ", "r": "ㄹ", "m": "x", "n": "x"}.get(last.casefold(), "")
    if kind == "으로":
        return "로" if tail in ("", "ㄹ") else "으로"
    with_final, without = {"을": ("을", "를"), "이": ("이", "가"), "은": ("은", "는"), "과": ("과", "와")}[kind]
    return without if tail == "" else with_final


def expected_text(template, slots):
    def fill(found):
        value = slots[found.group(1)]
        return value if found.group(2) is None else value + expected_particle(value, found.group(2))

    return " ".join(SLOT.sub(fill, template).split())


class SeasonTableTest(unittest.TestCase):
    def test_every_month_is_there_with_eight_to_fifteen_items(self):
        self.assertEqual(sorted(data.SEASONS), list(range(1, 13)))
        for month, entries in data.SEASONS.items():
            with self.subTest(month=month):
                self.assertTrue(8 <= len(entries) <= 15, len(entries))
        self.assertEqual(sorted(data.MONTH_NAMES), list(range(1, 13)))
        self.assertEqual(data.MONTH_NAMES[11], "11월")

    def test_each_item_has_a_word_a_one_line_reason_and_related_words_without_digits_or_prices(self):
        for month, entries in data.SEASONS.items():
            words = [item.word for item in entries]
            self.assertEqual(len(set(words)), len(words), f"{month}월에 같은 시기 낱말이 둘이다")
            for item in entries:
                with self.subTest(month=month, word=item.word):
                    self.assertTrue(item.word.strip() and item.reason.strip())
                    self.assertEqual(item.word, " ".join(item.word.split()))
                    self.assertEqual(item.reason, " ".join(item.reason.split()), "한 줄이어야 한다")
                    self.assertTrue(item.reason.endswith("입니다"), item.reason)
                    self.assertTrue(len(item.reason) <= 80)
                    self.assertGreaterEqual(len(item.related), 3)
                    self.assertEqual(len(set(item.related)), len(item.related), "이어지는 낱말이 겹친다")
                    for text in (item.word, item.reason, *item.related):
                        self.assertIsNone(re.search(r"[0-9０-９%％￦₩$]|[0-9]+원|통계|조사 결과|평균|배 늘|\bvs\b", text), f"수치·연도·통계가 있다: {text}")
                    for word in item.related:
                        self.assertGreaterEqual(len(word), 2, "이어지는 낱말은 두 글자 이상이다(한 글자는 아무 글에나 걸린다)")

    def test_the_usual_yearly_topics_the_brief_names_are_in_the_table(self):
        for wanted in ("환절기", "김장", "난방", "연말정산", "수능", "개학", "장마", "폭염", "휴가", "명절", "새해 계획", "미세먼지", "꽃가루", "단풍", "크리스마스"):
            self.assertTrue(any(wanted in word for word in ENTRY_WORDS), wanted)
        by_month = {month: [item.word for item in entries] for month, entries in data.SEASONS.items()}
        for month, wanted in ((11, "김장"), (11, "수능"), (7, "폭염"), (7, "장마"), (12, "크리스마스"), (3, "미세먼지"), (1, "연말정산"), (1, "설 명절"), (5, "가정의 달"), (9, "추석 명절"), (10, "단풍"),
                              (8, "태풍"), (2, "졸업"), (4, "벚꽃"), (6, "장마")):
            self.assertIn(wanted, by_month[month], f"{month}월")

    def test_the_table_text_carries_no_promise_or_markup(self):
        for entries in data.SEASONS.values():
            for item in entries:
                for text in (item.word, item.reason, *item.related):
                    self.assertIsNone(cd.forbidden_claim(text), text)
                    self.assertIsNone(find_markup(text), text)
                for text in (item.word, item.reason):                 # 이어지는 낱말(related)은 글에 나오지 않고 맞춰 보는 데만 쓰므로 경험 낱말 검사는 글에 나오는 것만 본다
                    self.assertFalse([word for word in EXPERIENCE if word in text], text)


class FrameTableTest(unittest.TestCase):
    def test_all_five_post_types_have_frames_and_the_names_are_unique(self):
        ids = [frame.frame_id for frame in data.FRAMES]
        self.assertEqual(len(set(ids)), len(ids))
        for kind in POST_TYPES:
            plain = [frame for frame in data.FRAMES if frame.post_type == kind and not frame.seasonal]
            seasonal = [frame for frame in data.FRAMES if frame.post_type == kind and frame.seasonal]
            self.assertGreaterEqual(len(plain), 3, kind)
            self.assertGreaterEqual(len(seasonal), 1, kind)
        self.assertTrue(all(frame.post_type in POST_TYPES for frame in data.FRAMES))
        self.assertEqual((data.INFO, data.COMPARE, data.PROBLEM, data.PRODUCT, data.PLACE), POST_TYPES)

    def test_only_the_seasonal_frames_have_the_season_slot_and_every_frame_has_the_topic_slot(self):
        for frame in data.FRAMES:
            with self.subTest(frame=frame.frame_id):
                texts = (frame.topic, frame.keyword, *frame.subs)
                self.assertTrue(all("{주제" in text for text in texts[:2]), "제목·핵심 키워드에 씨앗 자리가 있다")
                self.assertEqual(any("{계절" in text for text in texts), frame.seasonal)
                if frame.seasonal:
                    self.assertTrue("{계절" in frame.topic and "{계절" in frame.keyword)
                self.assertGreaterEqual(len(frame.subs), 2)
                self.assertTrue(frame.reason.endswith("글입니다.") or frame.reason.endswith("."), frame.reason)
                for text in texts:
                    for found in SLOT.finditer(text):
                        self.assertIn(found.group(2), (None, *tx.PARTICLES), text)
                    self.assertEqual(SLOT.sub("", text).count("{"), 0, text)
                    self.assertEqual(SLOT.sub("", text).count("}"), 0, text)

    def test_the_particle_kinds_the_frames_use_cover_all_five(self):
        used = {found.group(2) for frame in data.FRAMES for text in (frame.topic, frame.keyword, *frame.subs) for found in SLOT.finditer(text) if found.group(2)}
        self.assertEqual(used, set(tx.PARTICLES))

    def test_no_frame_text_has_digits_experience_words_promises_or_markup(self):
        for frame in data.FRAMES:
            for text in (frame.topic, frame.keyword, *frame.subs, frame.reason):
                with self.subTest(frame=frame.frame_id, text=text):
                    self.assertIsNone(re.search(r"[0-9]", text))
                    self.assertFalse([word for word in EXPERIENCE if word in text])
                    stripped = SLOT.sub("가", text)
                    self.assertIsNone(cd.forbidden_claim(stripped))
                    self.assertIsNone(find_markup(stripped))

    def test_the_filler_words_are_plain_nouns_without_spaces(self):
        self.assertTrue(data.FILLER_WORDS)
        self.assertTrue(all(word == word.strip() and " " not in word for word in data.FILLER_WORDS))


class EveryCombinationTest(unittest.TestCase):
    """모든 틀 × 여러 씨앗 × (시기 틀이면) 모든 달의 모든 시기 항목을 실제로 조합해 본다 — 첫 조합만 보고 멈추지 않는다."""

    def combinations(self):
        for frame in data.FRAMES:
            for seed in SEEDS:
                if not frame.seasonal:
                    yield frame, {"주제": seed}
                    continue
                for entries in data.SEASONS.values():
                    for entry in entries:
                        yield frame, {"주제": seed, "계절": entry.word}

    def test_every_rendered_text_matches_the_independent_expectation_and_has_no_defect(self):
        problems, checked = [], 0
        for frame, slots in self.combinations():
            for kind, template in (("topic", frame.topic), ("keyword", frame.keyword), *[("sub", item) for item in frame.subs]):
                got = tx.render(template, slots)
                want = expected_text(template, slots)
                folded = tx.fold_repeats(want)
                checked += 1
                if got != folded:
                    problems.append(("기대와 다름", frame.frame_id, kind, slots, got, folded))
                if "{" in got or "}" in got or "  " in got or got != got.strip():
                    problems.append(("자리·공백", frame.frame_id, got))
                words = got.split()
                if any(tx.stem(left) == tx.stem(right) for left, right in zip(words, words[1:], strict=False)):
                    problems.append(("같은 낱말 이어짐", frame.frame_id, got))
                if [word for word in EXPERIENCE if word in got]:
                    problems.append(("경험 전제", frame.frame_id, got))
                if cd.forbidden_claim(got) or find_markup(got):
                    problems.append(("약속·표기", frame.frame_id, got))
        self.assertGreater(checked, 50_000)
        self.assertEqual(problems, [], problems[:5])

    def test_every_frame_combination_can_be_saved_as_a_candidate(self):
        problems = []
        for frame in data.FRAMES:
            for seed in SEEDS:
                entries = [None] if not frame.seasonal else [item for entries in data.SEASONS.values() for item in entries][::7]
                for entry in entries:
                    slots = {"주제": seed} if entry is None else {"주제": seed, "계절": entry.word}
                    topic, keyword = tx.render(frame.topic, slots), tx.render(frame.keyword, slots)
                    subs = []
                    for template in frame.subs:
                        sub = tx.render(template, slots)
                        if cd.keyword_key(sub) not in {cd.keyword_key(keyword), *map(cd.keyword_key, subs)}:
                            subs.append(sub)
                    try:
                        cd.Candidate.new(topic, keyword, ("naver_a",), candidate_id="x", now="2026-11-03T00:00:00Z", sub_keywords=subs, post_type=frame.post_type,
                                         reason="프로필 제안 — " + frame.reason + ("" if entry is None else f" 이번 달(11월) '{entry.word}' 시기에 맞춘 글입니다 — {entry.reason}."))
                    except Exception as error:                  # noqa: BLE001 — 어떤 오류든 모아서 보인다
                        problems.append((frame.frame_id, seed, entry and entry.word, type(error).__name__, getattr(error, "slots", "")))
        self.assertEqual(problems, [], problems[:5])

    def test_the_seed_ending_sounds_the_check_covers_include_every_kind(self):
        sounds = {tx.final_sound(seed) for seed in SEEDS}
        self.assertEqual(sounds, {tx.NONE, tx.PLAIN, tx.RIEUL_SOUND})


if __name__ == "__main__":
    unittest.main()
