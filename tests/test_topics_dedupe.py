"""중복 판정(`topics/dedupe.py`) 시험 — 구간 경계(40·60·75), 유사도 계산(낱말·글자 조각·키워드), 보조 신호, 같은 채널 기존 글 찾기, 표시 칸에만 적기, 채널 사이 최대 2채널과 일곱 항목.

지키는 것:
  1) 유사도(%)를 채널의 기준(`dup_cutoffs`)으로 네 구간(다른 주제·비슷한 요소·다른 관점 필요·중복 또는 업데이트 후보)에 넣는다 — 기준과 같은 숫자는 위 구간(39/40·59/60·74/75 가 갈린다). 모르면 None.
  2) 유사도 계산은 단순하고 설명할 수 있다 — 낱말 겹침 40 : 글자 조각 겹침 30 의 가중 평균, 키워드가 더 높게 겹치면 평균으로 올릴 뿐 내리지 않는다. 같은 글은 100, 아무것도 안 겹치면 0, 순서를 바꿔도 같고 결정적이다.
  3) **숫자만으로 지우거나 제외하지 않는다** — 결과는 표시 칸(`duplicate_status`·`similar_post_ids`)에만 적히고 작업 상태·점수·추천 구간은 그대로다. 문구도 삭제를 말하지 않는다.
  4) 채널 사이는 같은 원천 주제를 최대 2채널까지, 그리고 일곱 항목(대상 독자·언어·검색 의도·관점·목차·채널 고유 정보·수익 목적) 중 4개 이상이 달라야 허용한다. 모르는 항목은 달라진 것으로 세지 않는다.
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import copy
import dataclasses
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import dedupe as dd  # noqa: E402
from chanceblog_desktop.topics import history as hs  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402

B = ts.PROFILES["naver_b"]
S = dd.Signature
BOUNDARIES = ((0, "different_topic"), (39, "different_topic"), (40, "similar_elements"), (59, "similar_elements"), (60, "different_angle_needed"), (74, "different_angle_needed"),
              (75, "duplicate_or_update"), (100, "duplicate_or_update"))


def record(title, *, channel="naver_b", date=None, ref=None, keywords=(), topic=None):
    return hs.HistoryRecord(channel=channel, title=title, keywords=keywords, date=date, ref=ref, topic=topic, origin="naver_items")


def cand(candidate_id="c1", **changes):
    return ts.make(candidate_id=candidate_id, **changes)


class CutoffTest(unittest.TestCase):
    def test_the_default_cutoffs_are_the_ones_of_every_channel_profile(self):
        self.assertEqual(dd.DEFAULT_CUTOFFS, (40, 60, 75))
        for key, profile in ts.PROFILES.items():
            with self.subTest(channel=key):
                self.assertEqual(profile.dup_cutoffs, dd.DEFAULT_CUTOFFS)

    def test_the_four_statuses_are_the_four_values_of_the_candidate_model(self):
        self.assertEqual((dd.DIFFERENT_TOPIC, dd.SIMILAR_ELEMENTS, dd.ANGLE_NEEDED, dd.DUPLICATE_OR_UPDATE), md.DUPLICATE_STATUSES)
        self.assertEqual(set(dd.STATUS_KO), set(md.DUPLICATE_STATUSES))
        self.assertEqual(dd.STATUS_KO["duplicate_or_update"], "중복 또는 기존 글 업데이트 후보")

    def test_the_edges_39_40_59_60_74_75_fall_on_the_documented_sides(self):
        for percent, expected in BOUNDARIES:
            with self.subTest(percent=percent):
                self.assertEqual(dd.status_of(percent), expected)
                self.assertEqual(dd.status_of(percent, B), expected)
                self.assertEqual(dd.status_of(percent, (40, 60, 75)), expected)

    def test_every_number_from_0_to_100_has_exactly_one_status_in_the_documented_counts(self):
        counts = {}
        for percent in range(101):
            counts[dd.status_of(percent)] = counts.get(dd.status_of(percent), 0) + 1
        self.assertEqual(counts, {"different_topic": 40, "similar_elements": 20, "different_angle_needed": 15, "duplicate_or_update": 26})
        order = [md.DUPLICATE_STATUSES.index(dd.status_of(percent)) for percent in range(101)]
        self.assertEqual(order, sorted(order), "숫자가 커질수록 구간도 같거나 더 심해진다")

    def test_other_cutoffs_move_the_edges_and_a_profile_brings_its_own(self):
        for percent, expected in ((29, "different_topic"), (30, "similar_elements"), (49, "similar_elements"), (50, "different_angle_needed"), (69, "different_angle_needed"),
                                  (70, "duplicate_or_update")):
            with self.subTest(percent=percent):
                self.assertEqual(dd.status_of(percent, (30, 50, 70)), expected)
        strict = dataclasses.replace(B, dup_cutoffs=(20, 35, 50))
        self.assertEqual(dd.status_of(50, strict), "duplicate_or_update")
        self.assertEqual(dd.status_of(50, B), "similar_elements")
        self.assertEqual(dd.status_of(19, strict), "different_topic")
        self.assertEqual(dd.status_of(20, strict), "similar_elements")

    def test_an_unknown_similarity_gives_no_status_and_not_a_different_topic(self):
        self.assertIsNone(dd.status_of(None))
        self.assertIsNone(dd.status_of(None, B))

    def test_wrong_percentages_and_cutoffs_are_refused(self):
        for bad in (-1, 101, 50.5, 50.0, True, "50", [50], float("nan")):
            with self.subTest(percent=bad):
                with self.assertRaises(ValueError):
                    dd.status_of(bad)
        for bad in ((40, 60), (40, 60, 75, 80), (60, 40, 75), (40, 40, 75), (0, 60, 75), (40, 60, 100), (40.0, 60, 75), ("40", 60, 75), None, 3, (True, 60, 75), "40,60,75"):
            with self.subTest(cutoffs=bad):
                with self.assertRaises(ValueError):
                    dd.status_of(50, bad)


class WordsTest(unittest.TestCase):
    def test_words_are_lowercase_split_by_script_with_particles_and_fillers_removed(self):
        self.assertEqual(dd.words_of("개인 PC 에서 로컬 AI 를 돌릴 때 확인할 사양"), ["개인", "pc", "로컬", "ai", "돌릴", "때", "확인할", "사양"])
        self.assertEqual(dd.words_of("스마트폰은 설정에서 앱 권한을 정리하는 방법"), ["스마트폰", "설정", "앱", "권한", "정리하"])
        self.assertEqual(dd.words_of("ＡＩ Tools 가이드"), ["ai", "tools"])
        self.assertEqual(dd.words_of("A1B2 v1.5"), ["a1b2", "v1", "5"])

    def test_a_particle_is_cut_only_when_two_or_more_letters_remain(self):
        self.assertEqual(dd.words_of("아이가 서버를 사용자의 노트북으로"), ["아이", "서버", "사용자", "노트북"])
        self.assertEqual(dd.words_of("나이"), ["나이"])
        self.assertEqual(dd.words_of("하이"), ["하이"])

    def test_the_longest_particle_is_cut_first(self):
        self.assertEqual(dd.words_of("사무실에서도 학교로는 서울에서는"), ["사무실", "학교", "서울"])
        self.assertEqual(dd.words_of("컴퓨터에서는"), ["컴퓨터"])
        self.assertEqual(dd.words_of("집에서는"), ["집에서"], "남는 글자가 하나뿐이면 긴 조사를 못 떼고 짧은 조사만 뗀다")

    def test_filler_words_can_be_kept_on_request_and_a_particle_alone_is_always_dropped_when_filtering(self):
        self.assertEqual(dd.words_of("정리 방법", filtered=False), ["정리", "방법"])
        self.assertEqual(dd.words_of("정리 방법"), [])
        self.assertEqual(dd.words_of("를 의 에서"), [])
        self.assertEqual(dd.words_of("를 의", filtered=False), ["를", "의"])

    def test_text_without_letters_or_digits_has_no_words(self):
        for text in ("", "   ", "!!!", "---", "…"):
            self.assertEqual(dd.words_of(text), [])

    def test_other_scripts_are_kept_as_whole_runs(self):
        self.assertEqual(dd.words_of("日本語 テスト"), ["日本語", "テスト"])

    def test_grams_are_two_letter_pieces_per_word_and_a_one_letter_word_stays_whole(self):
        self.assertEqual(dd.grams_of(["노트북"]), {"노트", "트북"})
        self.assertEqual(dd.grams_of(["ai", "x"]), {"ai", "x"})
        self.assertEqual(dd.grams_of([]), set())
        self.assertEqual(dd.grams_of(["노트북", "트북"]), {"노트", "트북"})


class SimilarityTest(unittest.TestCase):
    def test_the_same_title_is_100_and_nothing_in_common_is_0(self):
        same = dd.similarity(S("로컬 AI 사양"), S("로컬 AI 사양"))
        self.assertEqual(same, dd.Similarity(100, 100, 100, 100, None))
        none = dd.similarity(S("무선 청소기 고르는 기준", ("무선 청소기",)), S("스마트폰 앱 권한 점검하는 방법", ("스마트폰",)))
        self.assertEqual(none, dd.Similarity(0, 0, 0, 0, 0))

    def test_the_edges_of_the_four_statuses_can_be_built_from_the_word_overlap(self):
        # 낱말이 모두 두 글자 한글이라 글자 조각 겹침도 낱말 겹침과 같다 — 공통 ÷ 합집합
        cases = (("고양 강아 토끼", "고양 강아 거북 호랑", 40, "similar_elements"), ("로컬 ai 사양 확인", "로컬 ai 사양 점검", 60, "different_angle_needed"),
                 ("고양 강아 토끼", "고양 강아 토끼 거북", 75, "duplicate_or_update"), ("고양 강아 토끼 거북", "고양 강아 호랑 사자 여우", 29, "different_topic"))
        for left, right, percent, status in cases:
            with self.subTest(left=left, right=right):
                found = dd.similarity(S(left), S(right))
                self.assertEqual(found.percent, percent)
                self.assertEqual(dd.status_of(found.percent), status)

    def test_the_title_score_is_forty_words_to_thirty_grams(self):
        found = dd.similarity(S("노트북 추천 가이드"), S("노트북추천 정리"))
        self.assertEqual((found.words, found.grams, found.title, found.percent), (0, 50, 21, 21))
        self.assertEqual((dd.WEIGHT_WORDS, dd.WEIGHT_GRAMS), (40, 30))
        mixed = dd.similarity(S("고양 강아 토끼 거북"), S("고양 강아 토끼 호랑"))
        self.assertEqual((mixed.words, mixed.grams, mixed.title), (60, 60, 60))

    def test_the_result_is_symmetric_deterministic_and_inside_0_to_100(self):
        texts = ("로컬 AI 사양", "개인 PC 에서 로컬 AI 를 돌릴 때 확인할 사양", "무선 청소기 고르는 기준", "스마트폰 앱 권한 점검하는 방법", "노트북 추천 가이드", "노트북추천 정리", "연말정산 준비 체크리스트",
                 "연말정산 서류 준비 체크리스트 정리", "정리 방법", "ＡＩ tools", "AI Tools", "日本語 テスト", "!!!", "")
        for left, right in itertools.product(texts, repeat=2):
            with self.subTest(left=left[:12], right=right[:12]):
                forward, backward = dd.similarity(S(left), S(right)), dd.similarity(S(right), S(left))
                self.assertEqual(forward, backward)
                self.assertEqual(forward, dd.similarity(S(left), S(right)))
                for number in forward:
                    self.assertTrue(number is None or (isinstance(number, int) and 0 <= number <= 100))

    def test_a_text_is_100_percent_like_itself_unless_it_has_nothing_to_compare(self):
        for text in ("로컬 AI 사양", "정리 방법", "노트북추천", "x", "日本語"):
            with self.subTest(text=text):
                self.assertEqual(dd.similarity(S(text), S(text)).percent, 100)
        self.assertIsNone(dd.similarity(S(""), S("")).percent)
        self.assertIsNone(dd.similarity(S("!!!"), S("---")).percent)
        self.assertEqual(dd.similarity(S(""), S("로컬")).percent, None)

    def test_case_width_spacing_particles_and_fillers_do_not_change_the_result(self):
        base = dd.similarity(S("로컬 AI 사양"), S("로컬 AI 사양 확인"))
        for left in ("로컬 ai 사양", "ＬＯＣＡＬ".replace("ＬＯＣＡＬ", "로컬") + " ＡＩ 사양", "로컬   AI\t사양", "로컬을 AI 의 사양", "로컬 AI 사양 방법", "가이드 로컬 AI 사양 정리"):
            with self.subTest(left=left):
                self.assertEqual(dd.similarity(S(left), S("로컬 AI 사양 확인")), base)

    def test_words_that_only_contain_a_filler_are_still_compared_when_nothing_else_is_left(self):
        self.assertEqual(dd.similarity(S("정리 방법"), S("정리 방법")).percent, 100)
        self.assertEqual(dd.similarity(S("정리 방법"), S("정리 가이드")).percent, 30)       # 낱말 1/3 · 글자 조각 1/4 → (40×1/3 + 30×1/4) ÷ 70

    def test_keywords_raise_the_score_to_the_average_when_they_overlap_more_than_the_title_does(self):
        found = dd.similarity(S("고양 강아 토끼", ("고양이", "강아지")), S("고양 강아 거북", ("고양이", "강아지", "토끼")))
        self.assertEqual((found.title, found.keywords, found.percent), (50, 67, 58))

    def test_keywords_never_lower_the_score_and_missing_keywords_are_unknown_not_zero(self):
        different_keywords = dd.similarity(S("고양 강아 토끼", ("가나",)), S("고양 강아 토끼", ("다라",)))
        self.assertEqual((different_keywords.title, different_keywords.keywords, different_keywords.percent), (100, 0, 100))
        one_sided = dd.similarity(S("고양 강아 토끼", ("가나",)), S("고양 강아 토끼"))
        self.assertEqual((one_sided.keywords, one_sided.percent), (None, 100))
        both_empty = dd.similarity(S("고양 강아 토끼"), S("고양 강아 토끼"))
        self.assertIsNone(both_empty.keywords)

    def test_keyword_overlap_compares_the_normalized_keys_so_spacing_and_case_do_not_matter(self):
        found = dd.similarity(S("아무 글", ("로컬 AI", "GPU")), S("전혀 다른 제목", ("로컬ai", "gpu")))
        self.assertEqual(found.keywords, 100)
        self.assertEqual(found.percent, 50, "제목 점수 0 과 키워드 100 의 평균")

    def test_the_keywords_alone_decide_when_the_titles_have_nothing_to_compare(self):
        found = dd.similarity(S("", ("로컬 AI",)), S("", ("로컬 AI", "GPU")))
        self.assertEqual((found.title, found.keywords, found.percent), (None, 50, 50))

    def test_wrong_kinds_are_programming_errors(self):
        for left, right in ((None, S("x")), (S("x"), "x"), ("x", "y"), (("x", ()), S("x"))):
            with self.subTest(left=repr(left)[:10]):
                with self.assertRaises(TypeError):
                    dd.similarity(left, right)

    def test_the_signature_of_a_candidate_is_its_topic_and_all_its_keywords_and_of_a_record_its_title_and_keywords(self):
        made = cand(topic="예시 주제 글", primary_keyword="핵심어", secondary_keywords=("보조 하나", "보조 둘"))
        self.assertEqual(dd.signature_of(made), S("예시 주제 글", ("핵심어", "보조 하나", "보조 둘")))
        self.assertEqual(dd.signature_of(record("예시 제목", keywords=("가", "나"))), S("예시 제목", ("가", "나")))
        for bad in (None, "글", {"title": "x"}, S("x")):
            with self.assertRaises(TypeError):
                dd.signature_of(bad)


class SignalsAndCompareTest(unittest.TestCase):
    def test_two_candidates_are_compared_on_the_five_signals(self):
        left = cand("c1", primary_keyword="로컬 AI 사양", search_intent="selection_guide", topic_cluster="local-ai", topic_angle="memory", target_reader="일반 사용자")
        same = cand("c2", primary_keyword="로컬ai사양", search_intent="selection_guide", topic_cluster="local-ai", topic_angle="memory", target_reader="일반  사용자".replace("  ", " "))
        other = cand("c3", primary_keyword="다른 키워드", search_intent="how_to", topic_cluster="pc-parts", topic_angle="price", target_reader="전문가")
        self.assertEqual(dd.signals_of(left, same), dd.Signals(True, True, True, True, True))
        self.assertEqual(dd.signals_of(left, other), dd.Signals(False, False, False, False, False))

    def test_a_past_post_only_has_keywords_so_the_other_signals_are_unknown(self):
        made = cand(primary_keyword="로컬 AI 사양")
        self.assertEqual(dd.signals_of(made, record("제목", keywords=("로컬AI사양", "기타"))), dd.Signals(True, None, None, None, None))
        self.assertEqual(dd.signals_of(made, record("제목", keywords=("다른 말",))), dd.Signals(False, None, None, None, None))
        self.assertEqual(dd.signals_of(made, record("제목")), dd.Signals(None, None, None, None, None))

    def test_compare_returns_the_similarity_the_status_of_the_channel_and_the_signals(self):
        made = cand(topic="로컬 ai 사양 확인", primary_keyword="로컬 AI 사양")
        found = dd.compare(made, record("로컬 ai 사양 점검"), B)
        self.assertEqual((found.percent, found.status, found.signals.keyword), (60, "different_angle_needed", None))
        with_keyword = dd.compare(made, record("로컬 ai 사양 점검", keywords=("로컬 AI 사양",)), B)
        self.assertEqual((with_keyword.percent, with_keyword.status, with_keyword.signals.keyword), (80, "duplicate_or_update", True), "키워드가 같으면 제목 60 과 키워드 100 의 평균으로 올라간다")
        strict = dataclasses.replace(B, dup_cutoffs=(20, 35, 50))
        self.assertEqual(dd.compare(made, record("로컬 ai 사양 점검"), strict).status, "duplicate_or_update")
        self.assertEqual(dd.compare(made, record("로컬 ai 사양 점검")).status, "different_angle_needed", "기준을 안 주면 기본값")

    def test_nothing_to_compare_means_an_unknown_status_with_its_own_sentence(self):
        found = dd.compare(cand(topic="!!!", primary_keyword="x"), record("---", keywords=()))
        self.assertEqual((found.percent, found.status), (None, None))
        self.assertIn("확인하지 못했습니다", found.hint())
        blank = dd.Comparison(dd.Similarity(None, None, None, None, None), None, dd.Signals())
        self.assertIsNone(blank.status)
        self.assertIn("확인하지 못했습니다", blank.hint())

    def test_the_sentence_names_the_status_and_the_percent_and_never_says_to_delete(self):
        made = cand(topic="고양 강아 토끼", primary_keyword="고양이")
        for title, status, must in (("전혀 다른 글 하나", "different_topic", "다른 주제"), ("고양 강아 거북 호랑", "similar_elements", "비슷한 요소 있음"),
                                    ("고양 강아 토끼 거북", "duplicate_or_update", "중복 또는 기존 글 업데이트 후보")):
            with self.subTest(status=status):
                found = dd.compare(made, record(title, keywords=("고양이",) if status == "duplicate_or_update" else ("무관한 말",)))
                self.assertEqual(found.status, status)
                text = found.hint()
                self.assertIn(must, text)
                self.assertIn(f"({found.percent}%)", text)
                for forbidden in ("삭제", "제외", "버립니다", "지웁니다"):
                    self.assertNotIn(forbidden, text)
        angle = dd.compare(made, cand("c2", topic="고양 강아 토끼 거북 호랑", primary_keyword="무관한 말")).hint()
        self.assertIn("다른 관점이 필요", angle)
        self.assertIn("관점이나 대상 독자를 달리하면", angle)
        update = dd.compare(made, record("고양 강아 토끼 거북", keywords=("고양이",))).hint()
        self.assertIn("지우지 않고 표시만 합니다", update)
        self.assertIn("핵심 키워드", update)

    def test_a_comparison_is_frozen_and_equal_for_equal_inputs(self):
        found = dd.compare(cand(), record("예시"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            found.status = "different_topic"
        self.assertEqual(found, dd.compare(cand(), record("예시")))

    def test_wrong_kinds_are_programming_errors(self):
        for args in ((None, record("x")), (cand(), None), (cand(), "글"), (record("x"), cand())):
            with self.subTest(args=type(args[0]).__name__):
                with self.assertRaises(TypeError):
                    dd.compare(*args)


class FindMatchesTest(unittest.TestCase):
    def setUp(self):
        self.made = cand(topic="로컬 ai 사양 확인", primary_keyword="로컬 AI 사양")

    def test_only_records_of_the_same_channel_that_are_not_a_different_topic_come_back_most_alike_first(self):
        records = [record("무선 청소기 고르는 기준"), record("로컬 ai 사양 점검", ref="r60"), record("로컬 ai 사양 확인", ref="r100"), record("로컬 ai 사양 확인", channel="naver_a", ref="other"),
                   record("로컬 ai", ref="r50")]
        found = dd.find_matches(self.made, records, B)
        self.assertEqual([(match.record.ref, match.comparison.percent) for match in found], [("r100", 100), ("r60", 60), ("r50", 50)])
        self.assertEqual([match.comparison.status for match in found], ["duplicate_or_update", "different_angle_needed", "similar_elements"])

    def test_ties_are_broken_by_the_newer_date_then_the_title_then_the_reference_and_a_missing_date_comes_last(self):
        a = record("로컬 ai 사양 점검", date="2026-10-01", ref="a")
        b = record("로컬 ai 사양 점검", date="2026-11-01", ref="b")
        c = record("로컬 ai 사양 점검", date=None, ref="c")
        d = record("로컬 ai 사양 검토", date="2026-11-01", ref="d")
        e = record("로컬 ai 사양 점검", date="2026-11-01", ref="a-first")
        expected = ["d", "a-first", "b", "a", "c"]            # 같은 점수 → 최근 날짜(11-01 셋) → 제목(검토 < 점검) → 번호(a-first < b) → 날짜 있는 것(a) → 날짜 없는 것(c)
        for order in itertools.permutations([a, b, c, d, e]):
            with self.subTest(order=[item.ref for item in order]):
                self.assertEqual([match.record.ref for match in dd.find_matches(self.made, list(order), B, limit=5)], expected)

    def test_the_limit_cuts_the_list_and_is_checked(self):
        records = [record(f"로컬 ai 사양 점검{n}", ref=f"r{n}") for n in range(6)] + [record("로컬 ai 사양 확인", ref="best")]
        self.assertEqual(len(dd.find_matches(self.made, records, B)), 3)
        self.assertEqual(dd.find_matches(self.made, records, B, limit=1)[0].record.ref, "best")
        self.assertEqual(len(dd.find_matches(self.made, records, B, limit=dd.MAX_MATCHES)), 7)
        for bad in (0, -1, dd.MAX_MATCHES + 1, True, 2.0, None):
            with self.subTest(limit=bad):
                with self.assertRaises(ValueError):
                    dd.find_matches(self.made, records, B, limit=bad)

    def test_the_original_topic_of_a_past_post_is_compared_too_and_the_better_one_counts(self):
        only_topic_alike = record("전혀 다른 제목으로 나간 글", topic="로컬 ai 사양 확인", ref="t")
        found = dd.find_matches(self.made, [only_topic_alike], B)
        self.assertEqual((found[0].record.ref, found[0].comparison.percent), ("t", 100))
        self.assertEqual(dd.find_matches(self.made, [record("전혀 다른 제목으로 나간 글", topic="무선 청소기", ref="t")], B), ())

    def test_the_profile_must_be_the_one_of_the_candidates_channel(self):
        with self.assertRaises(ValueError) as caught:
            dd.find_matches(self.made, [record("로컬 ai 사양 점검")], ts.PROFILES["naver_a"])
        self.assertIn("채널", str(caught.exception))
        self.assertEqual(len(dd.find_matches(dataclasses.replace(self.made, channel="naver_a"), [record("로컬 ai 사양 점검", channel="naver_a")], ts.PROFILES["naver_a"])), 1)

    def test_the_channel_cutoffs_decide_which_records_are_kept(self):
        records = [record("로컬 ai 사양 점검", ref="r")]
        loose = dataclasses.replace(B, dup_cutoffs=(70, 80, 90))
        self.assertEqual(dd.find_matches(self.made, records, loose), ())
        self.assertEqual(len(dd.find_matches(self.made, records, B)), 1)

    def test_no_records_give_no_matches_and_the_input_is_not_changed(self):
        self.assertEqual(dd.find_matches(self.made, [], B), ())
        records = [record("로컬 ai 사양 점검", ref="a"), record("로컬 ai 사양 확인", ref="b")]
        before = copy.deepcopy(records)
        dd.find_matches(self.made, iter(records), B)
        self.assertEqual(records, before)

    def test_wrong_kinds_are_programming_errors(self):
        for args in ((None, [], B), (self.made, [], None), (self.made, [{"title": "x"}], B), (self.made, [self.made], B), (self.made, None, B)):
            with self.subTest(args=repr(args)[:20]):
                with self.assertRaises(TypeError):
                    dd.find_matches(*args)


class MarkedTest(unittest.TestCase):
    def setUp(self):
        self.made = cand(topic="로컬 ai 사양 확인", primary_keyword="로컬 AI 사양", scores=ts.flat_card(90), work_status="REVIEW")
        self.matches = dd.find_matches(self.made, [record("로컬 ai 사양 확인", ref="r100"), record("로컬 ai 사양 점검", ref="r60"), record("로컬 ai 사양 검토 확인", ref="r70")], B)

    def test_the_worst_status_and_the_reference_numbers_are_written_to_the_display_fields_only(self):
        result = dd.marked(self.made, self.matches)
        self.assertEqual(result.duplicate_status, "duplicate_or_update")
        self.assertEqual(result.similar_post_ids, tuple(match.record.ref for match in self.matches))
        for name in ("scores", "work_status", "topic", "primary_keyword", "channel", "candidate_id", "recommendation_band", "review_expires_at", "selection_reasons"):
            self.assertEqual(getattr(result, name), getattr(self.made, name), name)
        self.assertEqual((result.work_status, result.recommendation_band), ("REVIEW", "RECOMMENDED"))

    def test_the_original_candidate_is_not_changed(self):
        before = self.made.to_dict()
        dd.marked(self.made, self.matches)
        self.assertEqual(self.made.to_dict(), before)
        self.assertIsNone(self.made.duplicate_status)

    def test_no_similar_post_means_a_different_topic_and_no_numbers(self):
        result = dd.marked(self.made, ())
        self.assertEqual((result.duplicate_status, result.similar_post_ids), ("different_topic", ()))

    def test_a_match_without_a_reference_sets_the_status_but_adds_no_number(self):
        found = dd.find_matches(self.made, [record("로컬 ai 사양 점검")], B)
        result = dd.marked(self.made, found)
        self.assertEqual((result.duplicate_status, result.similar_post_ids), ("different_angle_needed", ()))

    def test_repeated_numbers_are_written_once_in_order(self):
        found = dd.find_matches(self.made, [record("로컬 ai 사양 확인", ref="same"), record("로컬 ai 사양 점검", ref="same"), record("로컬 ai 사양 점검 확인", ref="other")], B)
        self.assertEqual(dd.marked(self.made, found).similar_post_ids, ("same", "other"))

    def test_the_status_follows_the_most_alike_match_whatever_the_order_given(self):
        shuffled = tuple(reversed(self.matches))
        self.assertEqual(dd.marked(self.made, shuffled).duplicate_status, "duplicate_or_update")

    def test_a_marked_candidate_is_still_a_valid_candidate_and_survives_a_json_round_trip(self):
        result = dd.marked(self.made, self.matches)
        self.assertEqual(md.TopicCandidate.from_dict(result.to_dict()), result)

    def test_a_marked_candidate_stays_visible_in_the_top_view_this_module_never_excludes_it(self):
        from chanceblog_desktop.topics import select as sel
        result = dd.marked(self.made, self.matches)
        self.assertEqual(result.duplicate_status, "duplicate_or_update")
        self.assertEqual([item.candidate_id for item in sel.top_view([result], B).items], [self.made.candidate_id])

    def test_wrong_kinds_are_programming_errors(self):
        for args in ((None, ()), (self.made, [None]), (self.made, [self.matches[0].record]), (self.made, None)):
            with self.subTest(args=repr(args)[:20]):
                with self.assertRaises(TypeError):
                    dd.marked(*args)


def pair(first_changes=None, second_changes=None, channels=("naver_a", "naver_b")):
    left = ts.make(candidate_id="c-left", channel=channels[0], language="en" if channels[0] == "blogger_en" else "ko", source_topic_id="src1", **(first_changes or {}))
    right = ts.make(candidate_id="c-right", channel=channels[1], language="en" if channels[1] == "blogger_en" else "ko", source_topic_id="src1", **(second_changes or {}))
    return left, right


FOUR = ({"target_reader": "독자 가", "search_intent": "selection_guide", "topic_angle": "angle-a", "monetization_tags": ("pc_parts",)},
        {"target_reader": "독자 나", "search_intent": "how_to", "topic_angle": "angle-b", "monetization_tags": ()})


class AcrossChannelsTest(unittest.TestCase):
    def test_the_seven_items_and_the_minimum_are_these(self):
        self.assertEqual(dd.CROSS_ITEMS, ("reader", "language", "intent", "angle", "outline", "channel_info", "monetization"))
        self.assertEqual(set(dd.CROSS_ITEM_KO), set(dd.CROSS_ITEMS))
        self.assertEqual((dd.MIN_DIFFERENT_ITEMS, ch.MAX_CHANNELS_PER_TOPIC), (4, 2))

    def test_four_different_items_are_enough_and_the_rest_are_listed_as_same_or_unknown(self):
        verdict = dd.compare_across_channels(*pair(*FOUR))
        self.assertEqual(verdict.differing, ("reader", "intent", "angle", "monetization"))
        self.assertEqual(verdict.same, ("language",))
        self.assertEqual(verdict.unknown, ("outline", "channel_info"))
        self.assertTrue(verdict.enough)
        self.assertEqual((verdict.first, verdict.second, verdict.channels), ("c-left", "c-right", ("naver_a", "naver_b")))

    def test_three_different_items_are_not_enough_and_one_more_makes_it_enough(self):
        first, second = dict(FOUR[0]), dict(FOUR[1])
        second["monetization_tags"] = first["monetization_tags"]
        verdict = dd.compare_across_channels(*pair(first, second))
        self.assertEqual((len(verdict.differing), verdict.enough), (3, False))
        extra = dd.compare_across_channels(*pair(first, second), extras=dd.PairExtras(outline_differs=True))
        self.assertEqual((extra.differing, extra.enough), (("reader", "intent", "angle", "outline"), True))

    def test_an_unknown_item_is_neither_different_nor_the_same(self):
        verdict = dd.compare_across_channels(*pair(*FOUR), extras=dd.PairExtras(outline_differs=False, channel_info_differs=None))
        self.assertEqual((verdict.same, verdict.unknown), (("language", "outline"), ("channel_info",)))

    def test_a_copy_that_only_changes_the_language_is_not_enough(self):
        left, right = pair({}, {}, channels=("naver_a", "blogger_en"))
        verdict = dd.compare_across_channels(left, right)
        self.assertEqual(verdict.differing, ("language",))
        self.assertFalse(verdict.enough)

    def test_the_language_counts_as_one_of_the_items(self):
        verdict = dd.compare_across_channels(*pair(*FOUR, channels=("naver_a", "blogger_en")))
        self.assertEqual(verdict.differing, ("reader", "language", "intent", "angle", "monetization"))

    def test_the_monetization_purpose_compares_the_set_of_tags_not_their_order(self):
        for first, second, expected in ((("pc_parts", "ai_service"), ("ai_service", "pc_parts"), False), (("pc_parts",), (), True), ((), (), False), (("pc_parts",), ("ai_service",), True)):
            with self.subTest(first=first, second=second):
                verdict = dd.compare_across_channels(*pair({"monetization_tags": first}, {"monetization_tags": second}))
                self.assertEqual("monetization" in verdict.differing, expected)

    def test_the_reader_text_is_compared_after_normalizing_spacing_and_case(self):
        verdict = dd.compare_across_channels(*pair({"target_reader": "일반 사용자 PC"}, {"target_reader": "일반사용자 pc"}))
        self.assertNotIn("reader", verdict.differing)

    def test_the_minimum_can_be_changed_within_one_to_seven(self):
        left, right = pair(*FOUR)
        self.assertTrue(dd.compare_across_channels(left, right, min_different=1).enough)
        self.assertTrue(dd.compare_across_channels(left, right, min_different=4).enough)
        self.assertFalse(dd.compare_across_channels(left, right, min_different=5).enough)
        for bad in (0, 8, -1, True, 4.0, None):
            with self.subTest(min_different=bad):
                with self.assertRaises(ValueError):
                    dd.compare_across_channels(left, right, min_different=bad)

    def test_the_same_channel_and_wrong_kinds_are_programming_errors(self):
        left, right = pair()
        with self.assertRaises(ValueError):
            dd.compare_across_channels(left, dataclasses.replace(right, channel=left.channel))
        for args in ((None, right), (left, None), (left, "c"), (left.scores, right)):
            with self.subTest(args=type(args[0]).__name__):
                with self.assertRaises(TypeError):
                    dd.compare_across_channels(*args)
        with self.assertRaises(TypeError):
            dd.compare_across_channels(left, right, extras=(True, True))


class TopicSpreadTest(unittest.TestCase):
    def three(self):
        first = ts.make(candidate_id="c1", channel="naver_a", source_topic_id="src1", **FOUR[0])
        second = ts.make(candidate_id="c2", channel="naver_b", source_topic_id="src1", **FOUR[1])
        third = ts.make(candidate_id="c3", channel="github_pages", source_topic_id="src1", target_reader="독자 다", search_intent="comparison", topic_angle="angle-c", monetization_tags=("x_tag",))
        return first, second, third

    def test_a_topic_in_one_channel_is_fine_even_with_several_candidates(self):
        pool = [ts.make(candidate_id="a", source_topic_id="s"), ts.make(candidate_id="b", source_topic_id="s")]
        (spread,) = dd.check_topic_spread(pool)
        self.assertEqual((spread.source_topic_id, spread.channels, spread.too_many, spread.pairs, spread.allowed, spread.problems), ("s", ("naver_b",), False, (), True, ()))

    def test_two_channels_that_differ_enough_are_allowed(self):
        first, second, _third = self.three()
        (spread,) = dd.check_topic_spread([first, second])
        self.assertEqual((spread.channels, spread.too_many, spread.allowed, spread.problems), (("naver_a", "naver_b"), False, True, ()))
        self.assertEqual(len(spread.pairs), 1)

    def test_two_channels_that_barely_differ_are_not_allowed_and_the_reason_names_the_channels(self):
        first, second = pair({}, {"target_reader": "다른 독자"})
        (spread,) = dd.check_topic_spread([first, second])
        self.assertFalse(spread.allowed)
        self.assertEqual(len(spread.problems), 1)
        self.assertIn("네이버 A 과 네이버 B", spread.problems[0])
        self.assertIn("충분하지 않습니다", spread.problems[0])

    def test_three_channels_are_too_many_even_when_every_pair_differs_enough(self):
        first, second, third = self.three()
        (spread,) = dd.check_topic_spread([first, second, third])
        self.assertTrue(spread.too_many)
        self.assertFalse(spread.allowed)
        self.assertEqual(spread.channels, ("github_pages", "naver_a", "naver_b"))
        self.assertEqual(len(spread.pairs), 3)
        self.assertIn("3개 채널", spread.problems[0])
        self.assertIn("최대 2개 채널", spread.problems[0])

    def test_candidates_without_a_source_topic_are_skipped_and_groups_are_kept_apart_and_sorted(self):
        first, second, _third = self.three()
        loose = ts.make(candidate_id="x1", channel="blogger_ko", source_topic_id=None)
        other = ts.make(candidate_id="y1", channel="naver_a", source_topic_id="aaa")
        spreads = dd.check_topic_spread([second, loose, first, other])
        self.assertEqual([spread.source_topic_id for spread in spreads], ["aaa", "src1"])
        self.assertEqual(dd.check_topic_spread([loose]), ())
        self.assertEqual(dd.check_topic_spread([]), ())

    def test_extras_from_the_caller_can_make_a_barely_different_pair_enough(self):
        first, second = pair({}, {"target_reader": "다른 독자"})
        extras = {("c-left", "c-right"): dd.PairExtras(outline_differs=True, channel_info_differs=True)}
        (spread,) = dd.check_topic_spread([first, second], extras=extras)
        self.assertEqual(spread.pairs[0].differing, ("reader", "outline", "channel_info"))
        self.assertFalse(spread.allowed, "셋뿐이라 아직 부족하다")
        (relaxed,) = dd.check_topic_spread([first, second], extras=extras, min_different=3)
        self.assertTrue(relaxed.allowed)

    def test_the_result_does_not_depend_on_the_input_order(self):
        first, second, third = self.three()
        expected = dd.check_topic_spread([first, second, third])
        for order in itertools.permutations([first, second, third]):
            self.assertEqual(dd.check_topic_spread(list(order)), expected)

    def test_wrong_kinds_are_programming_errors(self):
        for bad in ([None], [{"candidate_id": "x"}], [record("x")]):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(TypeError):
                    dd.check_topic_spread(bad)


class PublicNamesTest(unittest.TestCase):
    def test_the_module_lists_exactly_the_names_it_exports(self):
        for name in dd.__all__:
            self.assertTrue(hasattr(dd, name), name)
        self.assertEqual(len(set(dd.__all__)), len(dd.__all__))
        self.assertEqual(dd.MAX_MATCHES, md.MAX_SIMILAR)


if __name__ == "__main__":
    unittest.main()
