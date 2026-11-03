"""자동 후보 제안(`content/suggest.py`) 시험 — 씨앗·한 곳의 마지막 관문·다양성·번호 안정·결정성·점수 연결.

지키는 것:
  1) 씨앗: 프로필의 주제·카테고리·기본 태그에서 낱말(구)을 뽑고(구분 글자·군더더기 낱말·세 낱말 규칙·중복·글자 수) 프로필이 비어 있으면 멈추지 않고 안내와 빈 목록을 준다.
  2) **관문은 한 곳**(`_gate`)이다 — 글자·낱말 한도 → 제외어 → 금지 표현 → 형식 → 최근 선택 → 보관함에 있음 → 기존 글과 비슷함 순으로 첫 번째 이유 하나만 세고, 경계(정확히 N일·N-1·N+1, 기준 정확히 같은 닮은 정도)를 모두 본다.
     막는 쪽은 **실패 열림이 없다**: 예외는 통과가 아니라 그대로 나고, 개수를 1개만 요청해도 맨 위 제안이 위반이 아니며, 24번째 씨앗의 위반도 놓치지 않는다. 보여 준 제안은 시험이 **밖에서 다시** 검사한다.
  3) 최근 선택·보관함에 이미 있는 제안은 걸러 내지 않고 숨기되 **번호는 그대로**다(같은 `--add` 를 되풀이해도 다른 제안이 들어가지 않는다).
  4) 같은 입력이면 같은 순서(해시 시드가 달라도), 같은 씨앗·틀·글 유형이 위쪽을 독점하지 않고 비슷한 키워드가 겹쳐 오르지 않는다. 개수가 모자라면 상한을 풀어 채운다.
  5) 점수: 외부 지표가 없으면 기회도 요인을 빼고 다시 나누며(0점 아님), 있으면 수요↑ 기회도↑·경쟁↑ 기회도↓·상승 > 보합 > 하락이고, 조회일과 경과일(오래된 데이터)을 보인다.
"""
import json
import os
import subprocess
import sys
import time
import unittest
from datetime import date, datetime
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import suggest_support as sp  # noqa: E402

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content import suggest as sg  # noqa: E402
from chanceblog_desktop.content import suggest_score as sc  # noqa: E402
from chanceblog_desktop.content import suggest_text as tx  # noqa: E402
from chanceblog_desktop.content.suggest_data import FRAMES  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402

PLAIN = [frame for frame in FRAMES if not frame.seasonal]


def ns(**fields):
    """프로필과 같은 칸을 가진 값 — `NaverProfile` 이 받지 않는 아주 긴 글·줄바꿈도 담을 수 있다(제안은 어떤 값이 와도 견뎌야 한다)."""
    base = dict(key="naver_a", display_name="블로그 에이", topic="", audience="", categories=(), default_tags=(), excluded_topics=(), forbidden_phrases=(), topic_reuse_days=90, post_type="정보형")
    base.update(fields)
    return SimpleNamespace(**base)


def view_env(prof, **parts):
    """관문을 직접 부르는 시험용 환경."""
    defaults = dict(blog="naver_a", stamp="2026-11-03T00:00:00Z", recent={}, vault=frozenset(), titles=sg.TitleIndex())
    defaults.update(parts)
    return sg._Env(sg.view_of(prof), **defaults)


def raw_from_text(text, month=11):
    """씨앗 글을 그대로 받은 첫 조합(씨앗 거르기를 거치지 않는다 — 관문이 혼자서도 막는지 볼 때)."""
    return sg.generate((sg.Seed(text, "주제", 90, tx.stem_set(text)),), month)[0]


def raw_of(prof, wanted_keyword, month=11):
    """프로필의 씨앗으로 조합을 만들어 핵심 키워드가 `wanted_keyword` 인 첫 조합."""
    seeds, _total = sg.extract_seeds(sg.view_of(prof))
    found = [item for item in sg.generate(seeds, month) if item.keyword == wanted_keyword]
    assert found, (wanted_keyword, [item.keyword for item in sg.generate(seeds, month)][:10])
    return found[0]


class SeedTest(unittest.TestCase):
    def seeds(self, **fields):
        return sg.extract_seeds(sg.view_of(ns(**fields)))

    def test_seeds_come_from_the_topic_then_the_categories_then_the_tags_each_with_its_strength(self):
        seeds, total = self.seeds(topic="생활 절약, 난방", categories=(("경제·일", "재테크"),), default_tags=("절약", "보험"))
        self.assertEqual([(seed.text, seed.source, seed.strength) for seed in seeds],
                         [("생활 절약", "주제", 90), ("난방", "주제", 90), ("재테크", "카테고리", 75), ("경제", "카테고리", 75), ("절약", "태그", 60), ("보험", "태그", 60)])
        self.assertEqual(total, 6)
        self.assertEqual(seeds[0].stems, frozenset({"생활", "절약"}))

    def test_the_same_keyword_keeps_only_the_strongest_source_and_spacing_or_case_is_the_same_keyword(self):
        seeds, total = self.seeds(topic="재테크, AI 도구", categories=(("x", "재테크"), ("y", "ai-도구")), default_tags=("재 테크",))
        self.assertEqual([(seed.text, seed.source) for seed in seeds], [("재테크", "주제"), ("AI 도구", "주제")])
        self.assertEqual(total, 2)

    def test_the_separators_the_filler_words_and_the_three_word_rule(self):
        seeds, _ = self.seeds(topic="가나다, 라마바；사아자/차카타·파하갸|거너더\n고노도 및 로모보 그리고 소수수 & 두투뚜")
        self.assertEqual([seed.text for seed in seeds], ["가나다", "라마바", "사아자", "차카타", "파하갸", "거너더", "고노도", "로모보", "소수수", "두투뚜"])
        seeds, _ = self.seeds(topic="생활 정보 공유 블로그")
        self.assertEqual([seed.text for seed in seeds], ["생활"], "군더더기 낱말(정보·공유·블로그)은 버린다")
        seeds, _ = self.seeds(topic="겨울 난방 관리")
        self.assertEqual([seed.text for seed in seeds], ["겨울 난방 관리"], "세 낱말 이하는 구 하나")
        seeds, _ = self.seeds(topic="겨울 난방 관리 요령")
        self.assertEqual([seed.text for seed in seeds], ["겨울", "난방", "관리", "요령"], "네 낱말 이상이면 낱말마다")
        seeds, _ = self.seeds(topic="정보를 공유합니다")
        self.assertEqual([seed.text for seed in seeds], ["공유합니다"], "조사가 붙은 군더더기('정보를')도 버린다")

    def test_a_seed_must_be_two_to_twenty_four_letters(self):
        seeds, total = self.seeds(topic="가, 나나, " + "다" * 24 + ", " + "라" * 25)
        self.assertEqual([seed.text for seed in seeds], ["나나", "다" * 24])
        self.assertEqual(total, 2)

    def test_at_most_twenty_four_seeds_are_used_and_the_total_is_reported(self):
        tags = tuple(f"태그{number:02d}" for number in range(40))
        seeds, total = self.seeds(default_tags=tags[:30])
        self.assertEqual((len(seeds), total), (sg.MAX_SEEDS, 30))
        self.assertEqual([seed.text for seed in seeds], [f"태그{number:02d}" for number in range(24)])

    def test_an_empty_or_missing_profile_has_no_seeds(self):
        self.assertEqual(sg.extract_seeds(sg.view_of(None)), ((), 0))
        self.assertEqual(sg.extract_seeds(sg.view_of(sp.profile())), ((), 0))
        self.assertEqual(sg.extract_seeds(sg.view_of(ns(topic="  ,  ; /\n "))), ((), 0))

    def test_only_the_first_part_of_a_huge_field_is_read(self):
        seeds, total = self.seeds(topic="가나, " + "x" * 2100 + ", 다라")
        self.assertEqual(([seed.text for seed in seeds], total), (["가나"], 1), "앞 2000자만 읽으므로 뒤의 '다라' 는 없다(긴 덩어리는 씨앗이 못 된다)")
        seeds, total = self.seeds(topic="x" * 1993 + ", 다라, 마바")
        self.assertEqual([seed.text for seed in seeds], ["다라"], "2000자 경계 — '마바' 는 잘리고 '다라' 는 읽힌다")

    def test_the_profile_view_takes_any_object_with_the_same_fields_and_repairs_odd_values(self):
        view = sg.view_of(SimpleNamespace(topic="가나", excluded_topics=("주식", " ", ""), forbidden_phrases=("ＡＩ 툴",), topic_reuse_days=-5, post_type="없는유형"))
        self.assertEqual((view.topic, view.excluded, view.forbidden, view.reuse_days, view.post_type), ("가나", ("주식",), ("ai툴",), 90, "정보형"))
        view = sg.view_of(SimpleNamespace(topic_reuse_days=True))
        self.assertEqual(view.reuse_days, 90)
        view = sg.view_of(sp.profile(topic_reuse_days=0, post_type="비교형"))
        self.assertEqual((view.reuse_days, view.post_type, view.name), (0, "비교형", "블로그 에이"))


class GuidanceTest(unittest.TestCase):
    def test_an_empty_profile_gives_a_guidance_and_an_empty_list_not_an_error(self):
        for prof in (sp.profile(), None):
            report = sg.suggest(prof, today=sp.TODAY, blog="naver_a")
            self.assertEqual((report.suggestions, report.generated, report.filtered, report.seeds, report.guidance), ((), 0, (), (), sg.GUIDANCE))
            self.assertIn("프로필에 주제를 적어", sg.GUIDANCE)
            self.assertIn("naver-profile set", sg.GUIDANCE)
            self.assertEqual((report.blog, report.month, report.today, report.count), ("naver_a", 11, "2026-11-03", 10))
            self.assertEqual(report.to_dict()["guidance"], sg.GUIDANCE)

    def test_only_tags_or_only_categories_are_enough_to_suggest(self):
        self.assertIsNone(sp.run(sp.profile(default_tags=("보험",))).guidance)
        self.assertTrue(sp.run(sp.profile(categories=(("a", "재테크"),))).suggestions)

    def test_the_blog_comes_from_the_profile_unless_given(self):
        self.assertEqual(sg.suggest(sp.rich(), today=sp.TODAY).blog, "naver_a")
        self.assertEqual(sg.suggest(sp.rich("naver_b"), today=sp.TODAY).blog, "naver_b")
        self.assertEqual(sg.suggest(sp.rich(), today=sp.TODAY, blog="github_pages").blog, "github_pages")


class ValidationTest(unittest.TestCase):
    def refused(self, **kwargs):
        with self.assertRaises(AppError) as caught:
            sp.run(**kwargs)
        self.assertEqual(caught.exception.code, "CANDIDATE_INVALID", kwargs)
        return caught.exception

    def test_wrong_arguments_are_refused_with_a_candidate_invalid_error(self):
        for bad in ("2026-11-03", None, 20261103, date(1999, 12, 31)):
            self.refused(today=bad)
        for bad in (0, 51, -1, True, "3", 2.5, None):
            self.refused(count=bad)
        for bad in (0, 13, "11", True, 1.5):
            self.refused(month=bad)
        for bad in ("tistory", "", 3):
            self.refused(blog=bad)
        self.refused(post_type="소설형")
        self.refused(post_type=7)
        with self.assertRaises(AppError):
            sg.suggest(SimpleNamespace(topic="가나"), today=sp.TODAY)              # 블로그를 알 수 없다

    def test_the_error_names_the_field_and_does_not_echo_a_secret_looking_value(self):
        error = self.refused(blog="AIza" + "A" * 35)
        self.assertNotIn("AIzaAAAA", error.rendered().message + str(error.detail))

    def test_a_datetime_today_is_taken_as_its_date_and_the_valid_edges_are_accepted(self):
        self.assertEqual(sp.run(today=datetime(2026, 11, 3, 23, 59)).today, "2026-11-03")
        for edge in (1, 50):
            self.assertLessEqual(len(sp.run(count=edge).suggestions), edge)
        self.assertEqual(sp.run(month=1).month, 1)
        self.assertEqual(sp.run(month=12).month, 12)
        self.assertEqual(sp.run(today=date(2000, 1, 1)).month, 1)

def fake(keyword, seed="씨앗", frame="틀", kind="정보형", hidden=None):
    """`_diversify` 가 읽는 칸만 가진 가짜 조합(점수 순서대로 줄 세워 넘긴다 — 이 함수는 순서를 정하지 않고 고르기만 한다)."""
    return SimpleNamespace(raw=SimpleNamespace(keyword=keyword, seed=SimpleNamespace(text=seed), frame=SimpleNamespace(frame_id=frame, post_type=kind)), hidden=hidden)


KINDS = ("정보형", "비교형", "문제 해결형", "제품·서비스 소개형", "장소·업체 정보형")
WORDS = ["가나", "다라", "마바", "사아", "자차", "카타", "파하", "거너", "고노", "도로", "모보", "소수", "오조", "초코", "토포", "호후"]


def names(chosen):
    return [item.raw.keyword for item in chosen]


class DiversifyUnitTest(unittest.TestCase):
    """`_diversify` — 점수 순으로 훑으며 상한을 지키고 모자라면 상한만 풀어 채운다. 가짜 조합으로 **어느 것이 앞에 오는지** 정확히 본다(올림·'이상'·'미만' 경계가 한 칸만 어긋나도 순서가 달라진다)."""

    def test_the_seed_cap_is_the_count_times_forty_percent_rounded_up_and_the_overflow_comes_after(self):
        items = [fake(WORDS[0], "A", "f1", KINDS[0]), fake(WORDS[1], "A", "f2", KINDS[1]), fake(WORDS[2], "A", "f3", KINDS[2]), fake(WORDS[3], "A", "f4", KINDS[3]), fake(WORDS[4], "B", "f5", KINDS[4])]
        self.assertEqual(names(sg._diversify(items, 7)), [WORDS[0], WORDS[1], WORDS[2], WORDS[4], WORDS[3]], "7 × 0.4 = 2.8 → 올림 3 — 넷째 A 는 뒤로")
        self.assertEqual(names(sg._diversify(items, 10)), [WORDS[0], WORDS[1], WORDS[2], WORDS[3], WORDS[4]], "10 × 0.4 = 4 — 넷째 A 까지 앞")
        self.assertEqual(names(sg._diversify(items, 3)), [WORDS[0], WORDS[1], WORDS[4]], "3 × 0.4 = 1.2 → 올림 2 — 상한 안에서 셋이 차서 넘친 것은 붙지 않는다")

    def test_the_frame_cap_is_twenty_percent_rounded_up(self):
        items = [fake(WORDS[0], "S1", "같은틀", KINDS[0]), fake(WORDS[1], "S2", "같은틀", KINDS[1]), fake(WORDS[2], "S3", "같은틀", KINDS[2]), fake(WORDS[3], "S4", "다른틀", KINDS[3])]
        self.assertEqual(names(sg._diversify(items, 7)), [WORDS[0], WORDS[1], WORDS[3], WORDS[2]], "7 × 0.2 = 1.4 → 올림 2")
        self.assertEqual(names(sg._diversify(items, 10)), [WORDS[0], WORDS[1], WORDS[3], WORDS[2]], "10 × 0.2 = 2")
        self.assertEqual(names(sg._diversify(items, 15)), [WORDS[0], WORDS[1], WORDS[2], WORDS[3]], "15 × 0.2 = 3 — 셋째까지 앞")
        self.assertEqual(names(sg._diversify(items, 1)), [WORDS[0], WORDS[3]], "상한은 최소 1 — 같은 틀의 둘째는 넘친 것이고 이미 개수가 찼으니 붙지 않는다")

    def test_the_post_type_cap_is_forty_percent_rounded_up(self):
        items = [fake(WORDS[number], f"S{number}", f"f{number}", KINDS[0]) for number in range(4)] + [fake(WORDS[4], "S4", "f4", KINDS[1])]
        self.assertEqual(names(sg._diversify(items, 7)), [WORDS[0], WORDS[1], WORDS[2], WORDS[4], WORDS[3]])
        self.assertEqual(names(sg._diversify(items, 10)), [WORDS[0], WORDS[1], WORDS[2], WORDS[3], WORDS[4]])

    def test_a_keyword_that_overlaps_exactly_seventy_percent_is_skipped_and_a_little_less_is_kept(self):
        shared = " ".join(WORDS[:7])
        first = shared + " " + WORDS[7]                                   # 8 낱말
        exactly = shared + " " + WORDS[8] + " " + WORDS[9]                # 공통 7 / 합 10 = 0.7
        a_little_less = shared + " " + " ".join(WORDS[10:13])             # 공통 7 / 합 11 = 0.636
        self.assertEqual(tx.jaccard(tx.stem_set(first), tx.stem_set(exactly)), 0.7)
        self.assertLess(tx.jaccard(tx.stem_set(first), tx.stem_set(a_little_less)), 0.7)
        items = [fake(first, "A", "f1", KINDS[0]), fake(exactly, "B", "f2", KINDS[1]), fake(a_little_less, "C", "f3", KINDS[2])]
        self.assertEqual(names(sg._diversify(items, 10)), [first, a_little_less], "0.7 은 비슷한 것이라 한 번도 뽑히지 않는다")

    def test_the_same_keyword_written_differently_is_picked_once(self):
        items = [fake("가나 다라", "A", "f1", KINDS[0]), fake("가나-다라", "B", "f2", KINDS[1]), fake("가나, 다라!", "C", "f3", KINDS[2]), fake("마바", "D", "f4", KINDS[3])]
        self.assertEqual(names(sg._diversify(items, 10)), ["가나 다라", "마바"])

    def test_hidden_items_keep_their_place_but_do_not_count_toward_the_requested_count(self):
        items = [fake(WORDS[0], "A", "f1", KINDS[0], hidden=sg.VAULT), fake(WORDS[1], "A", "f2", KINDS[1]), fake(WORDS[2], "A", "f3", KINDS[2], hidden=sg.RECENT), fake(WORDS[3], "A", "f4", KINDS[3]),
                 fake(WORDS[4], "A", "f5", KINDS[4]), fake(WORDS[5], "A", "f6", KINDS[0])]
        chosen = sg._diversify(items, 3)
        self.assertEqual(names(chosen), [WORDS[0], WORDS[1], WORDS[2], WORDS[3], WORDS[4]])
        self.assertEqual(len([item for item in chosen if item.hidden is None]), 3, "보이는 것이 개수만큼 채워질 때까지 이어서 고른다")

    def test_once_enough_are_visible_the_fill_stops(self):
        items = [fake(WORDS[number], "A", f"f{number}", KINDS[number % 5]) for number in range(8)]
        self.assertEqual(len(sg._diversify(items, 5)), 5)
        self.assertEqual(len(sg._diversify(items, 1)), 1)

    def test_nothing_in_nothing_out(self):
        self.assertEqual(sg._diversify([], 10), [])


class GenerateTest(unittest.TestCase):
    def test_a_seed_that_already_says_the_season_word_gets_no_season_frame_for_it(self):
        prof = sp.profile(topic="보일러 난방")
        seeds, _ = sg.extract_seeds(sg.view_of(prof))
        raws = sg.generate(seeds, 11)
        self.assertEqual([item for item in raws if item.season is not None and item.season.word == "난방"], [], "씨앗이 '난방' 을 말하는데 '난방 시기' 틀을 또 붙이지 않는다")
        self.assertTrue([item for item in raws if item.season is not None and item.season.word == "월동 준비"], "씨앗이 말하지 않은 시기는 붙는다")
        for item in raws:
            stems = tx.stems(item.keyword)
            self.assertEqual(len(stems), len(set(stems)), item.keyword)
        plain = [item for item in raws if item.season is None]
        self.assertTrue(plain)
        self.assertTrue(all("'난방' 시기와 이어지는 주제입니다" in item.base for item in plain), "일반 틀은 이미 말한 시기를 추천 이유에 적는다")

    def test_the_combinations_follow_the_table_for_a_seed_with_no_season_and_one_with_two(self):
        none = sg.generate(sg.extract_seeds(sg.view_of(sp.profile(topic="자전거")))[0], 11)
        self.assertEqual(len(none), len(PLAIN))
        self.assertTrue(all(item.season is None and item.note is None for item in none))
        two = sg.generate(sg.extract_seeds(sg.view_of(sp.profile(topic="보일러")))[0], 11)
        seasonal = [frame for frame in FRAMES if frame.seasonal]
        related = sc.related_items("보일러", 11)
        self.assertEqual(len(two), len(PLAIN) + len(seasonal) * len(related))
        self.assertEqual([item.order for item in two], sorted(item.order for item in two), "조합은 씨앗·틀·시기 순서로 늘어선다")

    def test_the_post_type_filter_keeps_the_frame_numbers(self):
        seeds = sg.extract_seeds(sg.view_of(sp.profile(topic="보일러")))[0]
        everything = {(item.order, item.keyword) for item in sg.generate(seeds, 11)}
        compare = sg.generate(seeds, 11, "비교형")
        self.assertTrue(compare)
        self.assertTrue({(item.order, item.keyword) for item in compare} <= everything)
        self.assertEqual({item.frame.post_type for item in compare}, {"비교형"})


class ComposeTest(unittest.TestCase):
    def test_a_sub_keyword_that_repeats_the_keyword_or_an_earlier_sub_keyword_is_dropped(self):
        from chanceblog_desktop.content.suggest_data import Frame
        frame = Frame("x-test", "정보형", "{주제} 제목", "{주제} 키", ("{주제} 키", "{주제} 보조", "{주제}-보조", "{주제}", "{주제} 보조!"), "이유입니다.", False)
        raw = sg._compose((0, 0, -1), sg.Seed("가나다", "주제", 90, tx.stem_set("가나다")), frame, None, None, 11)
        self.assertEqual((raw.topic, raw.keyword, raw.subs), ("가나다 제목", "가나다 키", ("가나다 보조", "가나다")))
        self.assertEqual(raw.base, "이유입니다.")

    def test_a_season_sentence_is_added_to_the_reason_only_when_there_is_a_season_note(self):
        from chanceblog_desktop.content.suggest_data import SEASONS
        entry = SEASONS[11][0]
        seed = sg.Seed("보일러", "주제", 90, tx.stem_set("보일러"))
        plain = sg._compose((0, 0, -1), seed, PLAIN[0], None, entry, 11)
        seasonal = sg._compose((0, 4, 0), seed, [frame for frame in FRAMES if frame.seasonal][0], entry, entry, 11)
        bare = sg._compose((0, 0, -1), seed, PLAIN[0], None, None, 11)
        self.assertEqual(bare.base, PLAIN[0].reason)
        self.assertIn("시기와 이어지는 주제입니다", plain.base)
        self.assertIn("시기에 맞춘 글입니다", seasonal.base)
        self.assertIn(entry.reason, plain.base)
        self.assertIn("(11월)", plain.base)


class SeedFilterTest(unittest.TestCase):
    def report_of(self, topic, **fields):
        return sg.seed_report(sg.view_of(ns(topic=topic, **fields)))

    def test_a_secret_shaped_seed_is_dropped_even_with_a_korean_particle_stuck_to_it(self):
        for topic in ("AKIAIOSFODNN7EXAMPLE, 가계부", "AKIAIOSFODNN7EXAMPLE를, 가계부", "AKIAIOSFODNN7EXAMPLE으로, 가계부"):
            seeds, _total, secret, risky = self.report_of(topic)
            self.assertEqual(([seed.text for seed in seeds], secret, risky), (["가계부"], 1, 0), topic)
        for fields in ({"default_tags": ("AKIAIOSFODNN7EXAMPLE를",)}, {"categories": (("분류", "AKIAIOSFODNN7EXAMPLE를"),)}):
            seeds, _total, secret, _risky = self.report_of("가계부", **fields)
            self.assertEqual(secret, 1, fields)
            self.assertEqual([seed.text for seed in seeds if "AKIA" in seed.text], [], fields)
            self.assertIn("가계부", [seed.text for seed in seeds])

    def test_no_output_carries_a_secret_shaped_seed(self):
        for topic in ("AKIAIOSFODNN7EXAMPLE를, 가계부", "ghp_" + "a1" * 18 + "를, 가계부"):
            report = sg.suggest(ns(topic=topic), today=sp.TODAY, count=20)
            self.assertTrue(report.suggestions)
            blob = json.dumps(report.to_dict(), ensure_ascii=False)
            for token in ("AKIA", "ghp_"):
                self.assertNotIn(token, blob, topic)
        report = sg.suggest(ns(topic="AKIAIOSFODNN7EXAMPLE를, 가계부"), today=sp.TODAY, count=20)
        self.assertTrue(any("비밀 모양의 글이 든 씨앗 1개는 쓰지 않았습니다" in note for note in report.notes), report.notes)
        only = sg.suggest(ns(topic="AKIAIOSFODNN7EXAMPLE를"), today=sp.TODAY)
        self.assertEqual((only.suggestions, only.guidance), ((), sg.GUIDANCE))
        self.assertTrue(only.notes)

    def test_seeds_that_assume_an_experience_or_promise_a_result_are_dropped_with_a_plain_note(self):
        topic = "맛집 후기, 써본 제품, 내돈내산 청소기, 100% 보장 투자, 최저가 보장, 월 천만원 수익, 무조건 합격, 가계부"
        seeds, total, secret, risky = self.report_of(topic)
        self.assertEqual(([seed.text for seed in seeds], total, secret, risky), (["가계부"], 1, 0, 7))
        report = sg.suggest(ns(topic=topic), today=sp.TODAY, count=20)
        self.assertTrue(report.suggestions)
        self.assertTrue(all(item.seed == "가계부" for item in report.suggestions))
        self.assertTrue(any("겪은 일이나 결과·수익의 보장을 뜻하는 낱말이 든 씨앗 7개는 쓰지 않았습니다" in note for note in report.notes), report.notes)
        blob = json.dumps(report.to_dict(), ensure_ascii=False)
        for word in ("후기", "내돈내산", "100%", "최저가", "천만원", "무조건", "써본"):
            self.assertNotIn(word, blob)

    def test_words_that_only_look_alike_stay(self):
        seeds, _total, secret, risky = self.report_of("보험 보장 범위, 가계부 수익 정리, 후견인 제도")
        self.assertEqual(([seed.text for seed in seeds], secret, risky), (["보험 보장 범위", "가계부 수익 정리", "후견인 제도"], 0, 0))
        self.assertEqual([seed.text for seed in self.report_of("사용해 보세요, 가계부")[0]], ["사용해 보세요", "가계부"], "권유는 겪은 일을 단정하는 말이 아니다")

    def test_a_sentence_that_states_an_experience_is_dropped_but_the_other_phrases_of_the_field_stay(self):
        seeds, _total, _secret, risky = self.report_of("직접 사용해 보니 좋았습니다, 가계부")
        self.assertEqual(([seed.text for seed in seeds], risky), (["가계부"], 1))

    def test_the_audience_is_checked_the_same_way(self):
        for audience in ("내돈내산 구매자", "AKIAIOSFODNN7EXAMPLE를", "100% 보장 투자자"):
            self.assertEqual(sg.audience_phrase(sg.view_of(ns(audience=audience))), "", audience)
        self.assertEqual(sg.audience_phrase(sg.view_of(ns(audience="사회초년생"))), "사회초년생")

    def test_the_checks_do_not_mistake_an_invisible_letter_for_a_secret_and_say_yes_to_real_ones(self):
        self.assertFalse(sg.is_secret_shaped("보일러\u200b난방"))
        self.assertTrue(sg.is_secret_shaped("AKIAIOSFODNN7EXAMPLE를"))
        self.assertFalse(sg.is_secret_shaped("보일러 난방"))
        self.assertFalse(sg.is_risky("보일러 난방"))
        self.assertTrue(sg.is_risky("상위노출 보장 비법"))
        self.assertTrue(sg.is_risky("써봤더니 좋았어요"))

    def test_every_word_of_the_experience_and_guarantee_list_is_pinned_by_a_test(self):
        """낱말 목록 32개 중 시험이 지키던 것은 5개뿐이었다(독립 검증 2차 — 26개를 한꺼번에 지워도 시험이 모두 통과했다). 목록을 통째로 못박고 낱말마다 그 낱말이 든 씨앗이 버려지는지 본다."""
        pinned = ("후기", "리뷰", "내돈내산", "써본", "써봤", "사용기", "체험단", "체험기", "방문기", "다녀온", "다녀왔", "직접써", "직접해", "해본", "해봤", "먹어본", "가본", "사용해본",
                  "100%", "백프로", "백퍼", "100퍼", "무조건", "최저가", "원금보장", "합격보장", "수익보장", "확정수익", "월천", "천만원", "억대", "대박")
        self.assertEqual((len(pinned), len(set(pinned))), (32, 32))
        self.assertEqual(sorted(sg._RISKY.pattern.split("|")), sorted(pinned), "낱말 목록이 바뀌었다 — 이 시험의 목록도 같은 변경에서 고친다")
        for word in pinned:
            sample = f"가을 {word} 정리"
            self.assertTrue(sg._RISKY.search(tx.squash(sample)), word)
            seeds, _total, _secret, risky = self.report_of(f"{sample}, 가계부")
            self.assertEqual(([seed.text for seed in seeds], risky), (["가계부"], 1), word)


class StuckParticleTest(unittest.TestCase):
    def test_a_seed_written_with_its_particle_does_not_get_it_twice(self):
        report = sg.suggest(ns(topic="김장을, 가계부"), today=sp.TODAY, count=40)
        text = " ".join(f"{item.topic} {item.keyword} {item.reason}" for item in (*report.suggestions, *report.more))
        self.assertIn("김장", text)
        self.assertNotIn("김장을을", text)
        self.assertNotIn("김장을를", text)


class BoundaryGapTest(unittest.TestCase):
    """검증에서 짚은 시험 공백 — 안내 문장이 '정확히 맞는 경계' 에서 나오지 않는지, 가장자리 글자·밑줄·300자 경계."""

    TWENTY_FOUR = ["가계", "난방", "김장", "절약", "보험", "적금", "청약", "연말", "정산", "환급", "대출", "이자",
                   "월세", "전세", "관리비", "냉방", "제습", "곰팡이", "환기", "청소", "정리", "수납", "요리", "도시락"]

    def test_the_only_n_note_appears_only_when_the_list_is_short(self):
        full = sg.suggest(ns(topic="가계부"), today=sp.TODAY, count=sg.MAX_COUNT)
        found = len(full.suggestions)
        self.assertTrue(0 < found < sg.MAX_COUNT, found)
        self.assertTrue(any(f"조건에 맞는 제안이 {found}개뿐입니다(요청 {sg.MAX_COUNT}개)" in note for note in full.notes), full.notes)
        exact = sg.suggest(ns(topic="가계부"), today=sp.TODAY, count=found)
        self.assertEqual(len(exact.suggestions), found)
        self.assertFalse(any("개뿐" in note for note in exact.notes), exact.notes)
        one_more = sg.suggest(ns(topic="가계부"), today=sp.TODAY, count=found + 1)
        self.assertTrue(any(f"조건에 맞는 제안이 {found}개뿐입니다(요청 {found + 1}개)" in note for note in one_more.notes), one_more.notes)

    def test_the_first_twenty_four_note_appears_from_the_twenty_fifth_seed_only(self):
        self.assertEqual(len(self.TWENTY_FOUR), sg.MAX_SEEDS)
        exactly = sg.suggest(ns(topic=", ".join(self.TWENTY_FOUR)), today=sp.TODAY, count=10)
        self.assertEqual((len(exactly.seeds), exactly.seed_total), (sg.MAX_SEEDS, sg.MAX_SEEDS))
        self.assertFalse(any("앞의" in note for note in exactly.notes), exactly.notes)
        over = sg.suggest(ns(topic=", ".join([*self.TWENTY_FOUR, "냉장고"])), today=sp.TODAY, count=10)
        self.assertEqual((len(over.seeds), over.seed_total), (sg.MAX_SEEDS, sg.MAX_SEEDS + 1))
        self.assertTrue(any(f"프로필에서 찾은 씨앗 {sg.MAX_SEEDS + 1}개 중 앞의 {sg.MAX_SEEDS}개만 썼습니다" in note for note in over.notes), over.notes)

    def test_an_audience_that_repeats_the_seed_is_folded_in_the_sub_keyword(self):
        report = sg.suggest(ns(topic="가계부", audience="가계부"), today=sp.TODAY, count=30)
        subs = [sub for item in report.suggestions for sub in item.sub_keywords]
        self.assertTrue(subs)
        self.assertFalse([sub for sub in subs if "가계부 가계부" in sub], subs)
        self.assertTrue(any("가계부" in sub for sub in subs))

    def test_a_season_word_in_the_seed_outranks_a_related_topic_and_both_outrank_a_plain_one(self):
        report = sg.suggest(ns(topic="김장, 난방, 가계부"), today=sp.TODAY, count=50, month=11)
        by_seed = {}
        for item in (*report.suggestions, *report.more):
            parts = {part.name: part.value for part in item.factors}
            by_seed.setdefault(item.seed, set()).add(parts.get("season"))
        spoken = max(score for score in by_seed["김장"] if score is not None)
        related = max(score for score in by_seed["난방"] if score is not None)
        plain = max(score for score in by_seed["가계부"] if score is not None)
        self.assertGreaterEqual(spoken, related)
        self.assertGreater(related, plain)
        self.assertEqual(plain, 50)

    def test_underscore_splits_words_but_a_seed_with_an_underscore_still_works(self):
        self.assertEqual(tx.words("snake_case 가계부_정리"), ["snake", "case", "가계부", "정리"])
        self.assertEqual(tx.stem_set("가계부_정리"), tx.stem_set("가계부 정리"))
        report = sg.suggest(ns(topic="가계부_정리"), today=sp.TODAY, count=5)
        self.assertTrue(report.suggestions)
        self.assertTrue(all("가계부" in item.keyword for item in report.suggestions))

    def test_an_exclamation_mark_at_the_edge_of_a_seed_is_trimmed(self):
        seeds, _total = sg.extract_seeds(sg.view_of(ns(topic="!!가계부!, 난방!?, (보험)")))
        self.assertEqual([seed.text for seed in seeds], ["가계부", "난방", "보험"])

    def test_an_existing_title_is_compared_only_by_its_first_three_hundred_characters(self):
        first = sg.suggest(ns(topic="가계부"), today=sp.TODAY, count=sg.MAX_COUNT)
        keyword = next(item.keyword for item in first.suggestions if len(item.keyword.split()) >= 2)
        end = sg.MAX_TITLE_CHARS
        inside = "가" * (end - len(keyword) - 1) + " " + keyword                   # 키워드가 300자 안에 끝난다
        outside = "가" * (end - len(keyword)) + " " + keyword                     # 키워드의 끝이 300자를 넘는다
        self.assertEqual((len(inside), len(outside)), (end, end + 1))
        for title, hidden in ((inside, True), (outside, False)):
            report = sg.suggest(ns(topic="가계부"), today=sp.TODAY, count=50, existing_titles=[title])
            shown = [item.keyword for item in (*report.suggestions, *report.more)]
            self.assertEqual(keyword not in shown, hidden, (len(title), keyword))


class AudienceTest(unittest.TestCase):
    def raws(self, audience, topic="보험, 보일러 난방"):
        view = sg.view_of(ns(topic=topic, audience=audience))
        seeds, _ = sg.extract_seeds(view)
        return sg.generate(seeds, 11, None, sg.audience_phrase(view))

    def test_the_audience_is_added_as_a_sub_keyword_with_the_seed(self):
        raws = self.raws("사회초년생")
        self.assertTrue(raws)
        for item in raws:
            self.assertEqual(item.subs[-1], f"사회초년생 {item.seed.text}", item.keyword)
        self.assertTrue(all("사회초년생" not in sub for item in self.raws("") for sub in item.subs))

    def test_the_audience_phrase_is_the_first_phrase_within_the_seed_length_rules(self):
        self.assertEqual(sg.audience_phrase(sg.view_of(ns(audience="20~30대 사회초년생, 직장인"))), "20~30대 사회초년생")
        self.assertEqual(sg.audience_phrase(sg.view_of(ns(audience="사회초년생 및 직장인"))), "사회초년생")
        self.assertEqual(sg.audience_phrase(sg.view_of(ns(audience="가" * 25))), "")
        self.assertEqual(sg.audience_phrase(sg.view_of(ns(audience="가"))), "", "한 글자는 씨앗이 못 되듯 대상 독자로도 쓰지 않는다")
        self.assertEqual(sg.audience_phrase(sg.view_of(ns(audience="정보 블로그"))), "")
        self.assertEqual(sg.audience_phrase(sg.view_of(ns(audience=""))), "")
        self.assertEqual(sg.audience_phrase(sg.view_of(None)), "")

    def test_a_sub_keyword_that_would_pass_the_limit_is_left_out_instead_of_blocking_the_suggestion(self):
        audience, seed = "가" * 24, "나" * 24
        raws = self.raws(audience, topic=seed)
        self.assertTrue(raws)
        self.assertTrue(all(all(sub != f"{audience} {seed}" for sub in item.subs) for item in raws))
        prof = ns(topic=seed, audience=audience)
        view = sg.view_of(prof)
        self.assertIsNone(sg._gate(raws[0], sg._Env(view, "naver_a", "2026-11-03T00:00:00Z", {}, frozenset(), sg.TitleIndex())), "한도 때문에 제안 전체가 걸러지지 않는다")
        fits = self.raws("사회초년생", topic="가" * 14)
        self.assertEqual(fits[0].subs[-1], "사회초년생 " + "가" * 14)
        exact = self.raws("가" * 15, topic="나" * 24)
        self.assertEqual(exact[0].subs[-1], "가" * 15 + " " + "나" * 24, "정확히 40자는 붙는다")
        self.assertEqual(len(exact[0].subs[-1]), sg.KEYWORD_MAX_CHARS)
        over = self.raws("가" * 16, topic="나" * 24)
        self.assertTrue(all(len(sub) <= sg.KEYWORD_MAX_CHARS for item in over for sub in item.subs))
        self.assertTrue(all(sub != "가" * 16 + " " + "나" * 24 for item in over for sub in item.subs), "41자는 붙지 않는다")
        six = self.raws("가나 다라 마바", topic="사아 자차 카타")
        self.assertEqual(six[0].subs[-1], "가나 다라 마바 사아 자차 카타", "정확히 여섯 낱말은 붙는다")

    def test_an_audience_equal_to_the_seed_adds_nothing_and_no_duplicate_sub_keyword_appears(self):
        for item in self.raws("보험", topic="보험"):
            keys = [cd.keyword_key(sub) for sub in item.subs]
            self.assertEqual(len(keys), len(set(keys)), item.subs)
            self.assertNotIn(cd.keyword_key(item.keyword), keys)

    def test_an_audience_with_an_excluded_word_blocks_every_suggestion_fail_closed(self):
        prof = ns(topic="보험, 가계부", audience="주식 투자자", excluded_topics=("주식",))
        report = sg.suggest(prof, today=sp.TODAY, count=20)
        self.assertEqual(report.suggestions, ())
        self.assertEqual({code for code, _label, _number, _hidden in report.filtered}, {sg.EXCLUDED})
        self.assertEqual(sg.suggest(ns(topic="보험, 가계부", audience="사회초년생", excluded_topics=("주식",)), today=sp.TODAY, count=20).filtered, ())

    def test_every_shown_suggestion_carries_the_audience_and_still_passes_the_outside_check(self):
        prof = sp.rich(audience="사회초년생")
        report = sp.run(prof, count=30)
        self.assertTrue(report.suggestions)
        for item in report.suggestions:
            self.assertEqual(item.sub_keywords[-1], f"사회초년생 {item.seed}")
        self.assertEqual(sp.independent_problems(report, prof), [])


class MorePoolTest(unittest.TestCase):
    def test_the_rest_pool_holds_only_visible_suggestions_that_passed_the_gate_and_were_not_shown(self):
        prof = sp.rich(excluded_topics=("보험",))
        vault_keyword = sp.run(prof, count=5).suggestions[0].keyword
        report = sp.run(prof, count=5, candidates=[sp.make(vault_keyword, number=1)])
        shown_keys = [cd.keyword_key(item.keyword) for item in report.suggestions]
        more_keys = [cd.keyword_key(item.keyword) for item in report.more]
        self.assertTrue(report.more)
        self.assertEqual(set(shown_keys) & set(more_keys), set(), "보여 준 것은 다시 담지 않는다")
        self.assertEqual(len(set(more_keys)), len(more_keys), "같은 키워드는 한 번만")
        self.assertNotIn(cd.keyword_key(vault_keyword), more_keys, "숨긴 제안(보관함에 있음)은 담지 않는다")
        self.assertEqual(sp.independent_problems(SimpleNamespace(suggestions=report.more), prof), [], "나머지도 같은 관문을 통과한 것이다")
        ranked = [item.rank for item in report.more if item.rank]
        self.assertEqual(ranked, sorted(ranked))
        self.assertTrue(all(rank > report.suggestions[-1].rank for rank in ranked), "번호가 있는 나머지는 보여 준 마지막 번호 뒤에 이어진다")
        self.assertTrue([item for item in report.more if item.rank == 0], "다양성 때문에 목록에 오르지 못한 제안은 번호 없이(rank 0) 담긴다")
        self.assertNotIn("more", report.to_dict())

    def test_the_same_keyword_made_twice_enters_the_pool_once(self):
        prof = sp.rich()
        seeds, _ = sg.extract_seeds(sg.view_of(prof))
        raws = sg.generate(seeds, 11)
        with mock.patch.object(sg, "generate", return_value=raws + raws):
            report = sp.run(prof, count=5)
        keys = [cd.keyword_key(item.keyword) for item in (*report.suggestions, *report.more)]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(report.suggestions), 5)

    def test_every_gated_visible_keyword_is_in_either_the_shown_list_or_the_pool(self):
        prof = sp.rich()
        wide = sp.run(prof, count=50)
        narrow = sp.run(prof, count=3)
        everything = {cd.keyword_key(item.keyword) for item in (*narrow.suggestions, *narrow.more)}
        self.assertTrue({cd.keyword_key(item.keyword) for item in wide.suggestions} <= everything)


class ReportListTest(unittest.TestCase):
    def test_the_report_can_be_used_like_the_list_of_suggestions(self):
        report = sp.run(sp.rich(), count=5)
        self.assertEqual(len(report), 5)
        self.assertEqual(list(report), list(report.suggestions))
        self.assertIs(report[0], report.suggestions[0])
        self.assertEqual(report[-1].rank, report.suggestions[-1].rank)
        self.assertEqual([item.keyword for item in report[1:3]], [item.keyword for item in report.suggestions[1:3]])
        self.assertTrue(report)
        empty = sp.run(sp.profile())
        self.assertEqual((len(empty), list(empty), bool(empty)), (0, [], False))
        self.assertEqual([item.rank for item in report], sorted(item.rank for item in report))


class GateTest(unittest.TestCase):
    """`_gate` 한 함수 — 이유마다, 경계마다, 순서까지."""

    def test_a_clean_combination_passes(self):
        prof = sp.profile(topic="보일러 난방")
        self.assertIsNone(sg._gate(raw_of(prof, "보일러 난방"), view_env(prof)))

    def test_the_text_limits_are_exact_at_the_boundary(self):
        prof = sp.profile(topic="보일러 난방")
        raw = raw_of(prof, "보일러 난방")
        env = view_env(prof)
        for name, size in (("TOPIC_MAX_CHARS", len(raw.topic)), ("TOPIC_MAX_WORDS", len(raw.topic.split())), ("KEYWORD_MAX_CHARS", max(len(raw.keyword), *(len(sub) for sub in raw.subs))),
                           ("KEYWORD_MAX_WORDS", max(len(raw.keyword.split()), *(len(sub.split()) for sub in raw.subs)))):
            with self.subTest(limit=name):
                with mock.patch.object(sg, name, size):
                    self.assertIsNone(sg._gate(raw, env), f"{name} == 실제 크기 {size} 는 통과")
                with mock.patch.object(sg, name, size - 1):
                    self.assertEqual(sg._gate(raw, env), sg.LIMITS, f"{name} == {size - 1} 은 걸린다")

    def test_each_sub_keyword_counts_for_the_limit_not_just_the_first(self):
        prof = sp.profile(topic="보일러 난방")
        raw = raw_of(prof, "보일러 난방")
        longest = max(range(len(raw.subs)), key=lambda number: len(raw.subs[number]))
        spare = [sub for number, sub in enumerate(raw.subs) if number != longest]
        with mock.patch.object(sg, "KEYWORD_MAX_CHARS", max([len(raw.keyword)] + [len(sub) for sub in spare])):
            self.assertEqual(sg._gate(raw, view_env(prof)), sg.LIMITS if len(raw.subs[longest]) > max([len(raw.keyword)] + [len(sub) for sub in spare]) else None)

    def test_an_excluded_topic_blocks_in_any_field_with_width_and_spacing_variants(self):
        prof = sp.profile(topic="가상 자산")
        raw = raw_of(prof, "가상 자산")
        for excluded in ("가상자산", "가상 자산", "가 상 자 산", "자산"):
            with self.subTest(excluded=excluded):
                self.assertEqual(sg._gate(raw, view_env(sp.profile(topic="가상 자산", excluded_topics=(excluded,)))), sg.EXCLUDED)
        self.assertIsNone(sg._gate(raw, view_env(sp.profile(topic="가상 자산", excluded_topics=("주식",)))))
        fullwidth = sp.profile(topic="AI 도구", excluded_topics=("ＡＩ",))
        self.assertEqual(sg._gate(raw_of(fullwidth, "AI 도구"), view_env(fullwidth)), sg.EXCLUDED)

    def test_an_excluded_word_that_is_only_in_a_sub_keyword_or_the_reason_still_blocks(self):
        prof = sp.profile(topic="보일러 난방")
        raw = raw_of(prof, "보일러 난방")
        self.assertIn("보일러 난방 기본", raw.subs)
        only_sub = sp.profile(topic="보일러 난방", excluded_topics=("난방 기본",))
        self.assertNotIn(tx.squash("난방기본"), tx.squash(raw.topic) + tx.squash(raw.keyword))
        self.assertEqual(sg._gate(raw, view_env(only_sub)), sg.EXCLUDED, "보조 키워드에만 있어도")
        self.assertIn("관리비", raw.base)
        only_reason = sp.profile(topic="보일러 난방", excluded_topics=("관리비",))
        self.assertNotIn("관리비", raw.topic + raw.keyword + "".join(raw.subs))
        self.assertEqual(sg._gate(raw, view_env(only_reason)), sg.EXCLUDED, "추천 이유에만 있어도")

    def test_the_profile_forbidden_phrases_a_promise_and_markup_all_block_as_forbidden(self):
        prof = sp.profile(topic="보일러 난방")
        raw = raw_of(prof, "보일러 난방")
        self.assertEqual(sg._gate(raw, view_env(sp.profile(topic="보일러 난방", forbidden_phrases=("처음 알아볼",)))), sg.FORBIDDEN)
        self.assertEqual(sg._gate(raw, view_env(sp.profile(topic="보일러 난방", forbidden_phrases=("ＢＯＩＬＥＲ",)))), None)
        frame = PLAIN[0]
        for text in ("상위노출 보장 비법", "검색 1위 가능성", "수익 보장 방법", "guaranteed #1 ranking", "<script>alert(1)</script>", "javascript:alert(1)", "{% include x %}", "onclick=alert(1)", "<b>굵게</b>"):
            with self.subTest(text=text):
                bad = sg._compose((0, 0, -1), sg.Seed(text, "태그", 60, tx.stem_set(text)), frame, None, None, 11)
                self.assertEqual(sg._gate(bad, view_env(prof)), sg.FORBIDDEN, text)
        for text in ("보험 상위노출 보장 업체 피하는 법", "보장하지 않습니다"):
            clean = sg._compose((0, 0, -1), sg.Seed(text, "태그", 60, tx.stem_set(text)), frame, None, None, 11)
            self.assertNotEqual(sg._gate(clean, view_env(prof)), sg.FORBIDDEN, f"경계하는 글은 약속이 아니다: {text}")

    def test_a_seed_with_an_invisible_letter_fails_the_form_check_not_the_others(self):
        prof = ns(topic="보일러​난방")
        seeds, _ = sg.extract_seeds(sg.view_of(prof))
        raws = sg.generate(seeds, 11)
        self.assertTrue(raws)
        self.assertEqual({sg._gate(item, view_env(prof)) for item in raws}, {sg.FORM})

    def test_a_non_candidate_error_from_the_form_check_is_not_swallowed(self):
        prof = sp.profile(topic="보일러 난방")
        raw = raw_of(prof, "보일러 난방")
        with mock.patch.object(cd.Candidate, "new", side_effect=AppError("STORE_LOCKED")):
            with self.assertRaises(AppError) as caught:
                sg._gate(raw, view_env(prof))
        self.assertEqual(caught.exception.code, "STORE_LOCKED")
        with mock.patch.object(cd.Candidate, "new", side_effect=RuntimeError("뜻밖")):
            with self.assertRaises(RuntimeError):
                sg._gate(raw, view_env(prof))

    def test_an_exception_inside_a_check_is_never_a_pass(self):
        prof = sp.profile(topic="보일러 난방")
        for target in ("forbidden_claim", "find_markup"):
            owner = cd if target == "forbidden_claim" else sg
            with self.subTest(check=target), mock.patch.object(owner, target, side_effect=RuntimeError("검사 중 오류")):
                with self.assertRaises(RuntimeError):
                    sp.run(prof)
        with mock.patch.object(tx, "squash", side_effect=RuntimeError("검사 중 오류")):
            with self.assertRaises(RuntimeError):
                sp.run(prof)
        with mock.patch.object(sg.TitleIndex, "similarity", side_effect=RuntimeError("검사 중 오류")):
            with self.assertRaises(RuntimeError):
                sp.run(prof, existing_titles=["보일러"])

    def test_recent_selection_boundary_is_exact_days_in_the_korean_calendar(self):
        prof = sp.profile(topic="보일러 난방", topic_reuse_days=30)
        raw = raw_of(prof, "보일러 난방")
        for days, expected in ((0, sg.RECENT), (1, sg.RECENT), (29, sg.RECENT), (30, sg.RECENT), (31, None), (32, None), (400, None)):
            with self.subTest(days_ago=days):
                recent = sg.recent_days([], [("보일러 난방", "naver_a", sp.kst_stamp(days))], "naver_a", sp.TODAY)
                self.assertEqual(sg._gate(raw, view_env(prof, recent=recent)), expected)
        around_midnight = {"2026-10-04T15:30:00Z": sg.RECENT, "2026-10-04T14:59:59Z": sg.RECENT, "2026-10-03T14:59:59Z": None, "2026-10-03T15:00:00Z": sg.RECENT}
        for stamp, expected in around_midnight.items():
            with self.subTest(stamp=stamp):
                recent = sg.recent_days([], [("보일러 난방", "naver_a", stamp)], "naver_a", sp.TODAY)
                self.assertEqual(sg._gate(raw, view_env(prof, recent=recent)), expected, f"{stamp} → 한국 날짜 {sg.kst_date(stamp)}")

    def test_the_recent_check_follows_the_profile_days_and_zero_turns_it_off(self):
        prof90 = sp.profile(topic="보일러 난방")
        raw = raw_of(prof90, "보일러 난방")
        recent = sg.recent_days([], [("보일러 난방", "naver_a", sp.kst_stamp(90))], "naver_a", sp.TODAY)
        self.assertEqual(sg._gate(raw, view_env(prof90, recent=recent)), sg.RECENT)
        recent = sg.recent_days([], [("보일러 난방", "naver_a", sp.kst_stamp(91))], "naver_a", sp.TODAY)
        self.assertIsNone(sg._gate(raw, view_env(prof90, recent=recent)))
        off = sp.profile(topic="보일러 난방", topic_reuse_days=0)
        recent = sg.recent_days([], [("보일러 난방", "naver_a", sp.kst_stamp(0))], "naver_a", sp.TODAY)
        self.assertIsNone(sg._gate(raw, view_env(off, recent=recent)))

    def test_recent_days_looks_only_at_the_same_blog_and_the_same_keyword_and_the_newest_pick(self):
        picks = [("보일러 난방", "naver_a", sp.kst_stamp(40)), ("보일러-난방", "naver_a", sp.kst_stamp(5)), ("보일러 난방", "naver_b", sp.kst_stamp(0)), ("다른 키워드", "naver_a", sp.kst_stamp(0)), ("   ", "naver_a", sp.kst_stamp(0))]
        self.assertEqual(sg.recent_days([], picks, "naver_a", sp.TODAY), {cd.keyword_key("보일러 난방"): 5, cd.keyword_key("다른 키워드"): 0})
        self.assertEqual(sg.recent_days([], picks, "naver_b", sp.TODAY), {cd.keyword_key("보일러 난방"): 0})
        future = [("가나", "naver_a", sp.kst_stamp(-3))]
        self.assertEqual(sg.recent_days([], future, "naver_a", sp.TODAY), {cd.keyword_key("가나"): 0}, "시계가 거꾸로 가도 0 아래로 내려가지 않는다")

    def test_recent_days_reads_selected_candidates_but_not_ones_moved_back_or_never_picked(self):
        picked = sp.make("보일러 난방", picked={"naver_a": sp.kst_stamp(3)}, number=1)
        moved_back = sp.make("가계부", picked={"naver_a": sp.kst_stamp(1)}, number=2).moved(cd.HOLD, now="2026-11-02T00:00:00Z")
        never = sp.make("재테크", number=3)
        no_record = cd.Candidate.new("t", "기록 없는 선택", ("naver_a", "naver_b"), candidate_id="cand0004", now="2026-10-30T00:00:00Z").moved(cd.SELECTED, now="2026-10-30T00:00:00Z")
        self.assertEqual(no_record.selections[0][0], "naver_a", "선택 기록은 추천 블로그 모두로 남는다")
        found = sg.recent_days([picked, moved_back, never, no_record], [], "naver_a", sp.TODAY)
        self.assertEqual(found, {cd.keyword_key("보일러 난방"): 3, cd.keyword_key("기록 없는 선택"): 4})
        import dataclasses
        bare = dataclasses.replace(no_record, selections=())
        self.assertEqual(sg.recent_days([bare], [], "naver_b", sp.TODAY), {cd.keyword_key("기록 없는 선택"): 4}, "기록 없는 '선택됨' 은 마지막 고친 날로 본다")
        self.assertEqual(sg.recent_days([bare], [], "github_pages", sp.TODAY), {}, "추천 블로그가 아니면 세지 않는다")

    def test_a_keyword_already_in_the_vault_is_found_by_keyword_not_by_number_and_only_for_that_blog(self):
        prof = sp.profile(topic="보일러 난방")
        raw = raw_of(prof, "보일러 난방")
        for spelling in ("보일러 난방", "보일러-난방", "보일러 난방!", "보일러난방", "보일러 · 난방"):
            vault = sg.vault_keys([sp.make(spelling, number=7)], "naver_a")
            self.assertEqual(sg._gate(raw, view_env(prof, vault=vault)), sg.VAULT, spelling)
        for status in (cd.NEW, cd.REVIEW, cd.HOLD, cd.REJECTED, cd.SELECTED):
            vault = sg.vault_keys([sp.make("보일러 난방", status=status)], "naver_a")
            self.assertEqual(sg._gate(raw, view_env(prof, vault=vault)), sg.VAULT, status)
        self.assertEqual(sg.vault_keys([sp.make("보일러 난방", ("naver_b",))], "naver_a"), frozenset())
        self.assertEqual(sg.vault_keys([sp.make("보일러 난방", ("naver_a", "naver_b"))], "naver_b"), frozenset({cd.keyword_key("보일러 난방")}))
        self.assertIsNone(sg._gate(raw, view_env(prof, vault=sg.vault_keys([sp.make("다른 키워드")], "naver_a"))))

    def test_a_similar_existing_title_blocks_exactly_at_the_threshold(self):
        prof = sp.profile(topic="보일러 난방")
        raw = raw_of(prof, "보일러 난방")
        topic, keyword = tx.stem_set(raw.topic), tx.stem_set(raw.keyword)
        for title in (raw.topic, raw.topic + " 더하기", "겨울철 " + raw.keyword + " 점검", "보일러 난방 점검 방법 비교 순서 확인 요령 정리"):
            index = sg.TitleIndex([title])
            similar = index.similarity(topic, keyword)
            self.assertGreater(similar, 0, title)
            with mock.patch.object(sc, "SIMILAR_FROM", similar):
                self.assertEqual(sg._gate(raw, view_env(prof, titles=index)), sg.SIMILAR, f"기준 == 닮은 정도({similar}) 는 걸린다")
            with mock.patch.object(sc, "SIMILAR_FROM", similar + 1e-9):
                self.assertIsNone(sg._gate(raw, view_env(prof, titles=index)), "기준이 조금이라도 높으면 통과")

    def test_a_title_made_from_the_same_frame_but_another_seed_is_not_similar(self):
        prof = sp.profile(topic="보일러 난방, 자전거")
        bike = raw_of(prof, "자전거")
        other = raw_of(prof, "보일러 난방")
        titles = sg.TitleIndex([bike.topic])
        self.assertEqual(sg._gate(bike, view_env(prof, titles=titles)), sg.SIMILAR, "같은 씨앗·같은 틀의 제목은 비슷하다")
        self.assertIsNone(sg._gate(other, view_env(prof, titles=titles)), "틀의 고정된 말이 같아도 씨앗이 다르면 비슷하지 않다")
        for frame_keyword in ("자전거 체크리스트", "자전거 비교"):
            self.assertIsNone(sg._gate(raw_of(prof, frame_keyword), view_env(prof, titles=titles)), "같은 씨앗의 다른 틀도 비슷하지 않다")

    def test_the_anchor_limits_the_comparison_to_titles_that_hold_every_seed_word(self):
        index = sg.TitleIndex(["가나 다라 기본 정리", "마바 기본 정리", "가나 마바 사아"])
        topic, keyword = frozenset({"가나", "다라", "기본", "정리"}), frozenset({"가나", "다라"})
        self.assertAlmostEqual(index.similarity(topic, keyword), 1.0)
        self.assertAlmostEqual(index.similarity(frozenset({"마바", "기본", "정리"}), frozenset({"마바"}), anchor=frozenset({"가나"})), 2 / 5, msg="씨앗(가나)을 담은 두 제목만 본다 — '가나 다라 기본 정리' 와 2/5")
        self.assertAlmostEqual(index.similarity(frozenset({"마바", "기본", "정리"}), frozenset({"마바"})), 1.0, msg="앵커 없이는 '마바 기본 정리' 와 같다")
        self.assertAlmostEqual(index.similarity(frozenset({"마바", "기본", "정리"}), frozenset({"마바"}), anchor=frozenset({"마바"})), 1.0)
        self.assertEqual(index.similarity(frozenset({"x1"}), frozenset(), anchor=frozenset({"없는"})), 0.0)
        self.assertEqual(index.similarity(frozenset({"가나"}), frozenset(), anchor=frozenset({"가나", "마바"})), tx.jaccard(frozenset({"가나"}), frozenset({"가나", "마바", "사아"})))

    def test_title_similarity_is_a_word_set_overlap_and_a_two_word_keyword_inside_a_title_counts(self):
        index = sg.TitleIndex(["가나 다라 마바 자차"])
        self.assertAlmostEqual(index.similarity(frozenset({"가나", "다라", "마바", "사아"}), frozenset()), 3 / 5)
        self.assertAlmostEqual(index.similarity(frozenset({"가나", "다라", "마바", "자차", "x1", "y1", "z1"}), frozenset()), 4 / 7)
        self.assertEqual(index.similarity(frozenset({"하하"}), frozenset()), 0.0)
        self.assertEqual(index.similarity(frozenset({"가나"}), frozenset({"가나", "다라"})), 1.0, "키워드의 두 낱말이 모두 한 제목에 있다")
        self.assertEqual(index.similarity(frozenset({"가나", "x2"}), frozenset({"가나"})), 1 / 5, "낱말이 하나뿐인 키워드는 포함으로 치지 않는다")
        self.assertEqual(index.similarity(frozenset({"하하"}), frozenset({"가나", "하하"})), 0.0, "키워드의 낱말 하나가 제목에 없으면 포함이 아니다")
        self.assertEqual(index.similarity(frozenset({"가나", "다라", "마바", "자차"}), frozenset(), skip=frozenset({frozenset({"가나", "다라", "마바", "자차"})})), 0.0, "자기 자신은 뺀다")
        self.assertEqual(len(sg.TitleIndex(["가나 다라", "다라 가나", "가나 다라를", "", "...", "가나 다라 마바"])), 2, "같은 낱말 집합·빈 제목은 하나로 센다")
        self.assertEqual(sg.TitleIndex().similarity(frozenset({"가나"}), frozenset({"가나", "다라"})), 0.0)

    def test_title_index_counts_how_many_existing_posts_cover_a_seed(self):
        index = sg.TitleIndex(["보일러 난방 점검", "겨울 보일러 난방", "보일러만", "난방비 줄이기", "보일러 난방"])
        self.assertEqual(index.covered(frozenset({"보일러", "난방"})), 3)
        self.assertEqual(index.covered(frozenset({"보일러"})), 4)
        self.assertEqual(index.covered(frozenset({"없는낱말"})), 0)
        self.assertEqual(index.covered(frozenset()), 0)

    def test_the_first_failing_reason_is_the_one_counted(self):
        prof_all = sp.profile(topic="보일러 난방", excluded_topics=("비법",))
        raw = raw_from_text("상위노출 보장 비법")
        env = view_env(prof_all, recent={cd.keyword_key(raw.keyword): 0}, vault=frozenset({cd.keyword_key(raw.keyword)}), titles=sg.TitleIndex([raw.topic]))
        self.assertEqual(sg._gate(raw, env), sg.EXCLUDED, "제외어·금지 표현·최근 선택·보관함·비슷한 글이 모두 맞아도 제외어가 먼저")
        prof_claim = sp.profile(topic="보일러 난방")
        raw = raw_from_text("상위노출 보장 비법")
        env = view_env(prof_claim, recent={cd.keyword_key(raw.keyword): 0}, vault=frozenset({cd.keyword_key(raw.keyword)}), titles=sg.TitleIndex([raw.topic]))
        self.assertEqual(sg._gate(raw, env), sg.FORBIDDEN)
        prof = sp.profile(topic="보일러 난방")
        raw = raw_of(prof, "보일러 난방")
        key = cd.keyword_key(raw.keyword)
        both = view_env(prof, recent={key: 0}, vault=frozenset({key}), titles=sg.TitleIndex([raw.topic]))
        self.assertEqual(sg._gate(raw, both), sg.RECENT, "최근 선택이 보관함보다 먼저")
        no_recent = view_env(prof, vault=frozenset({key}), titles=sg.TitleIndex([raw.topic]))
        self.assertEqual(sg._gate(raw, no_recent), sg.VAULT, "보관함이 비슷한 글보다 먼저")
        self.assertEqual(sg._gate(raw, view_env(prof, titles=sg.TitleIndex([raw.topic]))), sg.SIMILAR)
        self.assertEqual(sg.GATE_ORDER, (sg.LIMITS, sg.EXCLUDED, sg.FORBIDDEN, sg.FORM, sg.RECENT, sg.VAULT, sg.SIMILAR))
        self.assertEqual(sg.HIDDEN, {sg.RECENT, sg.VAULT})
        self.assertEqual(set(sg.GATE_LABELS), set(sg.GATE_ORDER))


class CountingTest(unittest.TestCase):
    def counts(self, report):
        return {code: (number, hidden) for code, _label, number, hidden in report.filtered}

    def test_every_combination_is_gated_so_the_counts_add_up_to_what_was_generated(self):
        report = sp.run(sp.profile(topic="보험, 보일러 난방, 자전거", excluded_topics=("보험",)), existing_titles=["자전거 처음 알아볼 때 꼭 짚어 둘 기본 정리"], count=50)
        seeds, _ = sg.extract_seeds(sg.view_of(sp.profile(topic="보험, 보일러 난방, 자전거")))
        raws = sg.generate(seeds, 11)
        self.assertEqual(report.generated, len(raws))
        counts = self.counts(report)
        insurance = [item for item in raws if item.seed.text == "보험"]
        self.assertEqual(counts[sg.EXCLUDED], (len(insurance), False))
        self.assertEqual(counts[sg.SIMILAR][0], 1)
        removed = sum(number for code, (number, hidden) in counts.items() if not hidden)
        self.assertLessEqual(removed, report.generated)

    def test_the_twenty_fourth_seed_is_gated_as_hard_as_the_first(self):
        tags = tuple(f"태그{number:02d}" for number in range(24))
        prof = sp.profile(default_tags=tags, forbidden_phrases=("태그23",))
        report = sp.run(prof, count=50)
        seeds, total = sg.extract_seeds(sg.view_of(prof))
        self.assertEqual((len(seeds), total), (24, 24))
        self.assertEqual(self.counts(report)[sg.FORBIDDEN], (len(PLAIN), False))
        self.assertEqual(sp.independent_problems(report, prof), [])

    def test_asking_for_one_suggestion_never_lets_a_violation_through_even_if_it_would_rank_first(self):
        prof = sp.profile(topic="상위노출 보장 비법, 가계부, 수익 보장 방법", excluded_topics=("가계",))
        for count in (1, 2, 5):
            report = sp.run(prof, count=count)
            self.assertEqual(sp.independent_problems(report, prof), [])
            self.assertEqual([item for item in report.suggestions if "상위노출" in item.topic or "수익 보장" in item.topic or "가계" in item.topic], [])
        everything_blocked = sp.run(sp.profile(topic="상위노출 보장 비법"), count=1)
        self.assertEqual((everything_blocked.suggestions, everything_blocked.guidance), ((), sg.GUIDANCE), "결과를 약속하는 씨앗은 씨앗 단계에서 버려지고 안내만 남는다")
        self.assertTrue(any("뜻하는 낱말이 든 씨앗 1개는 쓰지 않았습니다" in note for note in everything_blocked.notes), everything_blocked.notes)

    def test_the_label_text_names_each_reason_in_korean(self):
        self.assertEqual([sg.GATE_LABELS[code] for code in sg.GATE_ORDER], ["글자 수·낱말 수 한도", "제외어", "금지 표현", "형식 위반", "최근 선택", "보관함에 이미 있음", "비슷한 글 있음"])

    def test_a_clean_profile_has_no_violation_of_any_kind(self):
        report = sp.run(sp.rich(), count=50)
        self.assertEqual(report.filtered, ())
        self.assertEqual(sp.independent_problems(report, sp.rich()), [])


class RankStabilityTest(unittest.TestCase):
    def test_a_suggestion_added_to_the_vault_is_hidden_but_every_other_number_stays(self):
        prof = sp.rich()
        first = sp.run(prof)
        by_rank = {item.rank: item.keyword for item in first.suggestions}
        added = [sp.make(item.keyword, topic=item.topic, number=number) for number, item in enumerate(first.suggestions[:2], start=1)]
        second = sp.run(prof, candidates=added)
        self.assertEqual([item.rank for item in second.suggestions][:3], [item.rank for item in first.suggestions][2:5])
        for item in second.suggestions:
            if item.rank in by_rank:
                self.assertEqual(item.keyword, by_rank[item.rank], f"번호 {item.rank} 는 그대로")
        self.assertEqual(second.hidden_ranks, (first.suggestions[0].rank, first.suggestions[1].rank))
        self.assertTrue(set(keywords(second := second)) .isdisjoint({item.keyword for item in first.suggestions[:2]}))
        self.assertEqual({code: (number, hidden) for code, _label, number, hidden in second.filtered}[sg.VAULT], (2, True))
        self.assertEqual(len(second.suggestions), 10, "보이는 것은 다시 10개로 채운다")

    def test_the_same_numbers_added_twice_never_pull_in_other_suggestions(self):
        prof = sp.rich()
        first = sp.run(prof)
        wanted = {item.rank: item for item in first.suggestions[:3]}
        vault = [sp.make(item.keyword, topic=item.topic, number=number) for number, item in enumerate(wanted.values(), start=1)]
        again = sp.run(prof, candidates=vault)
        self.assertTrue(set(wanted).isdisjoint({item.rank for item in again.suggestions}), "같은 번호는 이제 보이지 않는다")
        self.assertEqual({rank for rank in wanted}, set(again.hidden_ranks))

    def test_a_recent_selection_hides_with_the_number_kept_too(self):
        prof = sp.rich()
        first = sp.run(prof)
        target = first.suggestions[1]
        second = sp.run(prof, selections=[(target.keyword, "naver_a", sp.kst_stamp(2))])
        self.assertNotIn(target.rank, [item.rank for item in second.suggestions])
        self.assertIn(target.rank, second.hidden_ranks)
        self.assertEqual({code: hidden for code, _label, _number, hidden in second.filtered}[sg.RECENT], True)
        for item in second.suggestions:
            if item.rank in {other.rank for other in first.suggestions}:
                self.assertEqual(item.keyword, {other.rank: other.keyword for other in first.suggestions}[item.rank])

    def test_hidden_numbers_after_the_last_shown_one_are_not_reported(self):
        prof = sp.rich()
        report = sp.run(prof, count=3)
        last = report.suggestions[-1].rank
        self.assertTrue(all(rank < last for rank in report.hidden_ranks))


def keywords(report):
    return [item.keyword for item in report.suggestions]


class DiversityTest(unittest.TestCase):
    def test_no_seed_frame_or_post_type_takes_over_the_top_ten(self):
        report = sp.run(sp.rich())
        self.assertEqual(len(report.suggestions), 10)
        seeds, frames, types = {}, {}, {}
        for item in report.suggestions:
            seeds[item.seed] = seeds.get(item.seed, 0) + 1
            frames[item.frame_id] = frames.get(item.frame_id, 0) + 1
            types[item.post_type] = types.get(item.post_type, 0) + 1
        self.assertLessEqual(max(seeds.values()), 4, seeds)
        self.assertLessEqual(max(frames.values()), 2, frames)
        self.assertLessEqual(max(types.values()), 4, types)
        self.assertGreaterEqual(len(types), 3)

    def test_the_caps_follow_the_requested_count_rounded_up(self):
        for count, cap_seed, cap_frame, cap_type in ((10, 4, 2, 4), (5, 2, 1, 2), (20, 8, 4, 8), (1, 1, 1, 1), (50, 20, 10, 20)):
            report = sp.run(sp.rich(), count=count)
            with self.subTest(count=count):
                for name, cap, attr in (("seed", cap_seed, "seed"), ("frame", cap_frame, "frame_id"), ("type", cap_type, "post_type")):
                    counts = {}
                    for item in report.suggestions:
                        counts[getattr(item, attr)] = counts.get(getattr(item, attr), 0) + 1
                    self.assertLessEqual(max(counts.values(), default=0), cap, (name, counts))

    def test_every_keyword_is_unique_and_no_two_are_too_alike(self):
        report = sp.run(sp.rich(), count=50)
        sets = [tx.stem_set(item.keyword) for item in report.suggestions]
        self.assertEqual(len({cd.keyword_key(item.keyword) for item in report.suggestions}), len(report.suggestions))
        for (left, first), (right, second) in combinations(zip(keywords(report), sets, strict=True), 2):
            self.assertLess(tx.jaccard(first, second), sg.KEYWORD_SIMILAR, (left, right))

    def test_ranks_run_up_in_order_and_the_pass_one_picks_come_before_the_relaxed_ones(self):
        report = sp.run(sp.rich(), count=50)
        ranks = [item.rank for item in report.suggestions]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(len(set(ranks)), len(ranks))
        self.assertEqual(ranks[0], 1)

    def test_when_the_caps_leave_too_few_they_are_relaxed_to_fill_the_requested_count(self):
        report = sp.run(sp.profile(topic="난방"), count=10)
        self.assertEqual(len(report.suggestions), 10)
        per_seed = {}
        for item in report.suggestions:
            per_seed[item.seed] = per_seed.get(item.seed, 0) + 1
        self.assertEqual(per_seed, {"난방": 10}, "씨앗이 하나뿐이면 한 씨앗 상한(4)을 풀어 채운다")
        self.assertEqual(sp.independent_problems(report, sp.profile(topic="난방")), [])

    def test_fewer_unique_suggestions_than_asked_is_said_plainly(self):
        report = sp.run(sp.profile(topic="난방"), count=50)
        self.assertLess(len(report.suggestions), 50)
        self.assertTrue(any(f"{len(report.suggestions)}개뿐" in note for note in report.notes), report.notes)

    def test_the_post_type_filter_uses_only_that_types_frames(self):
        for kind in ("정보형", "비교형", "문제 해결형", "제품·서비스 소개형", "장소·업체 정보형"):
            report = sp.run(sp.rich(), post_type=kind, count=30)
            with self.subTest(kind=kind):
                self.assertTrue(report.suggestions)
                self.assertEqual({item.post_type for item in report.suggestions}, {kind})

    def test_the_month_changes_the_season_sentence_and_the_seasonal_titles(self):
        prof = sp.profile(topic="에어컨, 가계부")
        july = sp.run(prof, month=7, count=30)
        november = sp.run(prof, month=11, count=30)
        self.assertNotEqual(keywords(july), keywords(november))
        self.assertTrue(any(item.season is not None and item.season.word in ("에어컨", "냉방비", "여름 건강", "폭염") for item in july.suggestions))
        self.assertTrue(all("7월" in item.reason for item in july.suggestions if item.season is not None))
        self.assertEqual(sp.run(prof, month=7).month, 7)

    def test_a_profile_with_nothing_for_this_month_says_so_and_still_suggests(self):
        report = sp.run(sp.profile(topic="자전거"), count=5)
        self.assertTrue(report.suggestions)
        self.assertTrue(all(item.season is None for item in report.suggestions))
        self.assertTrue(any("시기 맞춤 제안은 만들지 못했습니다" in note for note in report.notes), report.notes)


class DeterminismTest(unittest.TestCase):
    SCRIPT = (
        "import json, sys\n"
        "from datetime import date\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from chanceblog_desktop.content.profiles import NaverProfile\n"
        "from chanceblog_desktop.content import suggest as sg\n"
        "p = NaverProfile('naver_a', '블로그 에이', 'https://blog.naver.com/exampleaaa', topic='생활 절약, 보일러 난방, 가계부', categories=(('경제·일', '재테크'),), default_tags=('절약', '보험'), excluded_topics=('주식',))\n"
        "r = sg.suggest(p, today=date(2026, 11, 3), existing_titles=['보일러 점검 순서', '가계부 쓰는 법'], count=30)\n"
        "print(json.dumps(r.to_dict(), ensure_ascii=False, sort_keys=True))\n")

    def test_the_same_input_gives_the_same_report_every_time(self):
        first = [sp.run(sp.rich(), existing_titles=["보일러 점검 순서"], count=30).to_dict() for _ in range(3)]
        self.assertEqual(first[0], first[1])
        self.assertEqual(first[1], first[2])

    def test_the_input_order_of_titles_and_candidates_does_not_change_the_result(self):
        titles = ["보일러 난방 점검", "가계부 쓰는 법", "절약 습관 만들기", "보험 비교"]
        candidates = [sp.make("가나다 키워드", number=1, search_demand=100, data_date="2026-11-01"), sp.make("가나다 키워드", ("naver_b",), number=2, search_demand=900, data_date="2026-11-01")]
        base = sp.run(sp.rich(), existing_titles=titles, candidates=candidates, count=30).to_dict()
        self.assertEqual(sp.run(sp.rich(), existing_titles=list(reversed(titles)), candidates=list(reversed(candidates)), count=30).to_dict(), base)

    def test_the_result_does_not_depend_on_the_python_hash_seed_or_the_process(self):
        outputs = {}
        for seed in ("0", "1", "4242", "random"):
            env = {key: value for key, value in os.environ.items() if key != "PYTHONHASHSEED"}
            env.update({"PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
            done = subprocess.run([sys.executable, "-X", "utf8", "-c", self.SCRIPT, str(sp.ROOT / "src")], capture_output=True, env=env, timeout=180, creationflags=sp.NO_WINDOW)
            self.assertEqual((done.returncode, done.stderr), (0, b""), done.stderr.decode("utf-8", "replace"))
            outputs[seed] = done.stdout
        self.assertEqual(len(set(outputs.values())), 1, {seed: len(value) for seed, value in outputs.items()})
        self.assertEqual(json.loads(outputs["0"].decode("utf-8"))["blog"], "naver_a")


class ScoreIntegrationTest(unittest.TestCase):
    def test_without_external_data_the_opportunity_factor_is_absent_and_the_rest_are_renormalised(self):
        report = sp.run(sp.rich(), count=20)
        for item in report.suggestions:
            with self.subTest(keyword=item.keyword):
                self.assertEqual([part.name for part in item.factors], ["fit", "season", "freshness", "balance"])
                self.assertAlmostEqual(sum(part.share for part in item.factors), 1.0)
                self.assertEqual([round(part.share, 6) for part in item.factors], [round(weight / 85, 6) for weight in (30, 20, 20, 15)])
                self.assertAlmostEqual(item.priority.score, round(sum(part.value * part.share for part in item.factors), 1), places=1)
                self.assertEqual(item.metrics, sg.Metrics())
                self.assertFalse(item.metrics.has_any())
                self.assertIsNone(item.data_date)
                self.assertTrue(item.data_text.startswith(f"계산일 {sp.TODAY.isoformat()} — 외부 데이터 없음"), item.data_text)
                self.assertEqual((item.computed_on, item.data_age.days, item.data_age.stale), ("2026-11-03", None, False))
                self.assertIn("키워드 기회도는 반영하지 않았습니다", item.reason)
                self.assertEqual(item.priority.level, sc.level_of(item.priority.score))

    def test_the_fit_follows_where_the_seed_came_from_and_the_post_type(self):
        report = sp.run(sp.rich(), count=50)
        base = {"주제": 90, "카테고리": 75, "태그": 60}
        for item in report.suggestions:
            with self.subTest(keyword=item.keyword):
                self.assertEqual(item.fit, base[item.seed_source] + (10 if item.post_type == "정보형" else 0))
        self.assertEqual({item.fit for item in report.suggestions}, {60, 70, 75, 85, 90, 100})
        self.assertEqual({item.fit for item in sp.run(sp.rich(post_type="비교형"), count=50).suggestions if item.post_type == "비교형"}, {70, 85, 100})

    def test_the_season_factor_is_a_match_a_relation_or_neutral(self):
        report = sp.run(sp.profile(topic="김장, 보일러, 자전거"), count=50)
        value = {item.keyword: {part.name: part.value for part in item.factors}["season"] for item in report.suggestions}
        by_seed = {}
        for item in report.suggestions:
            by_seed.setdefault(item.seed, set()).add({part.name: part.value for part in item.factors}["season"])
        self.assertEqual(by_seed["김장"], {100})
        self.assertEqual(by_seed["자전거"], {50})
        self.assertEqual(by_seed["보일러"], {70, 100}, "일반 틀은 이어지는 주제(70)이고 시기 틀은 글에 시기 낱말이 든다(100)")
        for item in report.suggestions:
            if item.seed == "보일러":
                self.assertEqual(value[item.keyword], 100 if item.season is not None and item.frame_id.endswith(("season", "season-care")) or item.keyword.startswith(("난방 ", "월동")) else 70, item.keyword)

    def test_freshness_and_balance_follow_the_existing_posts(self):
        prof = sp.profile(topic="보일러 난방")
        clean = sp.run(prof, count=50)
        titles = ["보일러 난방 점검 요령", "겨울 보일러 난방 관리", "보일러 난방 고장 대처"]
        busy = sp.run(prof, existing_titles=titles, count=50)
        got = {item.keyword: {part.name: part.value for part in item.factors} for item in busy.suggestions}
        before = {item.keyword: {part.name: part.value for part in item.factors} for item in clean.suggestions}
        common = set(got) & set(before)
        self.assertTrue(common)
        for keyword in common:
            self.assertEqual(before[keyword]["balance"], 100)
            self.assertEqual(got[keyword]["balance"], 40, "같은 씨앗을 다룬 글이 셋이면 100 - 3×20")
            self.assertLessEqual(got[keyword]["freshness"], before[keyword]["freshness"])
        partly = sg.TitleIndex(titles)
        for item in busy.suggestions:
            similar = partly.similarity(tx.stem_set(item.topic), tx.stem_set(item.keyword))
            self.assertAlmostEqual({part.name: part.value for part in item.factors}["freshness"], max(0.0, min(100.0, 100.0 * (1 - similar / sc.SIMILAR_FROM))))

    def metric_run(self, **metrics):
        prof = sp.profile(topic="보험")
        keyword = "보험 비교"
        report = sp.run(prof, count=50, external={keyword: sg.External(data_date="2026-11-01", **metrics)})
        match = [item for item in report.suggestions if item.keyword == keyword]
        self.assertEqual(len(match), 1, keywords(report))
        return match[0]

    def test_external_data_adds_the_opportunity_factor_with_its_published_weight(self):
        item = self.metric_run(search_demand=5000, related_blog_results=40000, trend="상승")
        parts = {part.name: part for part in item.factors}
        self.assertEqual(list(parts), ["fit", "season", "freshness", "balance", "opportunity"])
        self.assertEqual([part.share for part in item.factors], [0.3, 0.2, 0.2, 0.15, 0.15])
        self.assertAlmostEqual(parts["opportunity"].value, sc.opportunity(5000, 40000, "상승"))
        self.assertTrue(item.metrics.has_any())
        self.assertEqual((item.metrics.search_demand, item.metrics.related_blog_results, item.metrics.trend), (5000, 40000, "상승"))
        self.assertIn("키워드 기회도", item.reason)
        self.assertNotIn("반영하지 않았습니다", item.reason)

    def test_more_demand_never_lowers_the_priority_and_below_the_cap_raises_it(self):
        scores = [self.metric_run(search_demand=value, related_blog_results=50_000, trend="보합").priority.score for value in (0, 10, 100, 1000, 10_000, 100_000)]
        self.assertEqual(scores, sorted(scores))
        self.assertTrue(all(left < right for left, right in zip(scores, scores[1:], strict=False)), scores)

    def test_more_blog_results_lowers_the_priority(self):
        scores = [self.metric_run(search_demand=5000, related_blog_results=value, trend="보합").priority.score for value in (0, 100, 10_000, 1_000_000, 10_000_000)]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(left > right for left, right in zip(scores, scores[1:], strict=False)), scores)

    def test_a_rising_trend_beats_flat_beats_falling(self):
        up, flat, down = (self.metric_run(search_demand=5000, related_blog_results=50_000, trend=item).priority.score for item in ("상승", "보합", "하락"))
        self.assertTrue(up > flat > down, (up, flat, down))

    def test_data_that_has_only_a_mobile_share_or_months_shows_the_date_but_adds_no_opportunity(self):
        item = self.metric_run(mobile_share=70.0)
        self.assertEqual([part.name for part in item.factors], ["fit", "season", "freshness", "balance"])
        self.assertEqual(item.data_date, "2026-11-01")
        self.assertIn("조회일 2026-11-01(2일 전 조회)", item.data_text)
        self.assertEqual(item.metrics.mobile_share, 70.0)

    def test_external_months_decide_the_season_factor_when_given(self):
        include = {part.name: part.value for part in self.metric_run(seasonality=(11, 12)).factors}["season"]
        exclude = {part.name: part.value for part in self.metric_run(seasonality=(6, 7)).factors}["season"]
        self.assertEqual((include, exclude), (100, 30))

    def test_the_data_date_age_and_the_stale_note(self):
        fresh = self.metric_run(search_demand=100)
        self.assertEqual((fresh.data_age.days, fresh.data_age.stale), (2, False))
        prof = sp.profile(topic="보험")
        old = sp.run(prof, count=50, external={"보험 비교": sg.External(search_demand=100, data_date="2026-10-01")})
        item = [found for found in old.suggestions if found.keyword == "보험 비교"][0]
        self.assertEqual((item.data_age.days, item.data_age.stale), (33, True))
        self.assertIn("33일 전 조회", item.data_text)
        self.assertIn("오래된 데이터", item.data_text)
        self.assertEqual(item.to_dict()["data"], {"data_date": "2026-10-01", "days_ago": 33, "stale": True, "future": False})

    def test_vault_candidates_with_csv_metrics_feed_the_same_keyword_for_another_blog(self):
        other = sp.make("보험 비교", ("naver_b",), number=1, search_demand=20000, related_blog_results=1000, trend="상승", data_date="2026-11-02")
        report = sp.run(sp.profile(topic="보험"), candidates=[other], count=50)
        item = [found for found in report.suggestions if found.keyword == "보험 비교"][0]
        self.assertEqual(item.data_date, "2026-11-02")
        self.assertEqual(item.metrics.search_demand, 20000)
        self.assertIn("opportunity", [part.name for part in item.factors])
        same_blog = sp.run(sp.profile(topic="보험"), candidates=[sp.make("보험 비교", ("naver_a",), number=1, search_demand=20000, data_date="2026-11-02")], count=50)
        self.assertNotIn("보험 비교", keywords(same_blog), "같은 블로그의 후보가 이미 있으면 숨긴다")

    def test_external_from_keeps_the_latest_date_per_keyword_and_skips_candidates_without_data(self):
        old = sp.make("보험 비교", number=1, search_demand=100, data_date="2026-10-01")
        new = sp.make("보험-비교", ("naver_b",), number=2, search_demand=900, trend="상승", data_date="2026-11-01")
        none = sp.make("가계부", number=3)
        found = sg.external_from([old, new, none])
        self.assertEqual(set(found), {cd.keyword_key("보험 비교")})
        self.assertEqual((found[cd.keyword_key("보험 비교")].search_demand, found[cd.keyword_key("보험 비교")].data_date), (900, "2026-11-01"))
        tie_a = sp.make("같은날", number=5, search_demand=1, data_date="2026-11-01")
        tie_b = sp.make("같은날", number=6, search_demand=2, data_date="2026-11-01")
        self.assertEqual(sg.external_from([tie_a, tie_b]), sg.external_from([tie_b, tie_a]), "같은 날이면 후보 번호로 가려 순서와 무관")

    def test_the_stored_reason_marks_the_source_and_fits_a_candidate(self):
        for item in sp.run(sp.rich(), count=50).suggestions:
            self.assertTrue(item.stored_reason.startswith("프로필 제안 — "), item.stored_reason)
            self.assertLessEqual(len(item.stored_reason), cd.MAX_REASON)
            self.assertNotIn("점수 근거", item.stored_reason)
        self.assertEqual(sg.SOURCE_MARK, "프로필 제안")

    def test_the_explanation_names_each_factor_with_its_value_and_share_and_the_total(self):
        item = sp.run(sp.rich()).suggestions[0]
        for part in item.factors:
            self.assertIn(f"{sc.FACTOR_NAMES[part.name]} {sg.num(part.value)}점(비중 {sg.num(part.share * 100)}%)", item.reason)
        self.assertIn(f"콘텐츠 작성 우선도 {sg.num(item.priority.score)}점", item.reason)
        self.assertEqual([sg.num(value) for value in (100, 100.0, 96.5, 89.4, 0, 33.3333, 35.25, 0.04)], ["100", "100", "96.5", "89.4", "0", "33.3", "35.2", "0"])

    def test_every_text_the_report_shows_is_free_of_a_promise_of_results(self):
        report = sp.run(sp.rich(), count=50)
        for item in report.suggestions:
            for text in sp_texts(item):
                self.assertIsNone(cd.forbidden_claim(text), text)
        banned = ("상위노출", "노출 확률", "검색 1위", "수익 보장", "확률", "순위", "랭킹")
        blob = json.dumps(report.to_dict(), ensure_ascii=False)
        self.assertEqual([word for word in banned if word in blob], [])


def sp_texts(item):
    return sp.texts_of(item) + [item.data_text, item.stored_reason]


class LongInputTest(unittest.TestCase):
    def test_huge_profile_fields_and_thousands_of_titles_finish_quickly_and_stay_correct(self):
        topic = ", ".join(f"주제{number}" for number in range(5000)) + " " + "가" * 200_000
        prof = ns(topic=topic, default_tags=tuple(f"태그{number}" for number in range(30)), excluded_topics=tuple(f"제외{number}" for number in range(100)))
        titles = [f"보일러 난방 점검 {number} 방법 정리 순서 요령" for number in range(20_000)]
        started = time.monotonic()
        report = sp.run(prof, existing_titles=titles, count=50)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 60.0, f"{elapsed:.1f}초")
        self.assertLessEqual(len(report.seeds), sg.MAX_SEEDS)
        self.assertEqual(sp.independent_problems(report, prof), [])

    def test_long_titles_are_cut_before_comparing_and_odd_text_does_not_break_anything(self):
        weird = ["\u0000" * 10, "힣" * 400, "AAA " * 100_000, "가" * 1_000_000, "‮반전‬ 글", "<script>x</script>", "a" * 5000 + " 보일러 난방"]
        report = sp.run(sp.profile(topic="보일러 난방"), existing_titles=weird, count=10)
        self.assertEqual(len(report.suggestions), 10)

    def test_the_stem_and_fold_helpers_stay_linear_on_a_very_long_word(self):
        word = "가나" * 200_000
        started = time.monotonic()
        tx.stem(word)
        tx.fold_repeats((word + " ") * 3)
        tx.stem_set(word * 3)
        self.assertLess(time.monotonic() - started, 10.0)


if __name__ == "__main__":
    unittest.main()
