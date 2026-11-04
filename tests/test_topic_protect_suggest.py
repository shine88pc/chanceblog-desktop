"""특성 시험(P0) — 규칙 기반 제안 엔진(`content/suggest*.py`)과 제안 서비스의 '네이버 둘뿐' 가정을 **현재 모습 그대로** 못박는다(계획 문서 `docs/TOPIC_ENGINE_PLAN.md` 의 G2·G4 제안 쪽). 네트워크·시크릿·실제 시계·자식 프로세스 없음(날짜는 `today` 인자).

왜: 5채널 주제 선정 전략의 새 엔진을 얹기 전에, 지금의 제안 결과(같은 입력 → 같은 결과)가 뒤의 단계에서 소리 없이 바뀌지 않게 못박는다. 이 시험은 '옳다고 정한 것' 이 아니라 '지금 이렇다' 이다 —
바꾸려면 새 결정(D-nn)을 쓰고 해당 시험을 의식적으로 고친다. 현재 동작이 마음에 안 드는 것(알려진 결함)은 이름에 `KNOWN_DEFECT` 를 달았다 — 계절 낱말의 부분 일치(P0b 가 토큰/구문 기반으로 바꾸며 뒤집는다)·위험 씨앗의 건강·브랜드 표시 없음(P2).
이미 있는 시험과 겹치지 않게 더한다 — 이미 있는 것: 결정성 한 가지 입력(`test_suggest.DeterminismTest`)·월 표 12개월 8~15항목과 이름 있는 시기 낱말(`test_suggest_data.SeasonTableTest`)·계절 점수 일반 예(`test_suggest_score.SeasonFitTest`)·
수요 점수의 양 끝(`test_suggest_score.OpportunityTest`)·위험 낱말 32개 목록(`test_suggest.SeedFilterTest.test_every_word_of_the_experience_and_guarantee_list_is_pinned_by_a_test`)·다른 블로그 안내문(`test_service_suggestions` 의 `OTHER_BLOG_GUIDANCE`).
"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import service_support as support  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.content import suggest as sg  # noqa: E402
from chanceblog_desktop.content import suggest_score as sc  # noqa: E402
from chanceblog_desktop.content.profiles import KEYS as NAVER_KEYS  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.service import suggestions as svc  # noqa: E402

TODAY = date(2026, 11, 3)
PROFILE_A = NaverProfile("naver_a", "생활 소비 블로그", "https://blog.naver.com/testa", topic="소형가전, 제습기, 숙박, 여행, PC 주변기기", audience="30대 직장인",
                         categories=(("가전", "소형가전"), ("여행", "숙박·여행")), default_tags=("제습기", "가성비"))
PROFILE_B = NaverProfile("naver_b", "AI PC 블로그", "https://blog.naver.com/testb", topic="AI 서비스, PC 부품, 업무 자동화, 그래픽카드", audience="개인 사용자")
PROFILE_B_TAGGED = NaverProfile("naver_b", "AI PC 블로그", "https://blog.naver.com/testb", topic="AI 서비스, PC 부품, 업무 자동화", audience="개인 사용자",
                                categories=(("PC", "그래픽카드"),), default_tags=("그래픽카드",))
PROFILE_RISKY = NaverProfile("naver_b", "위험 씨앗", "https://blog.naver.com/testb", topic="영양제, 불면증 해결, 삼성 갤럭시, 체험단 모집")
YEAR_END = "연말정산 준비"                       # 11월 시기 항목 — 이어지는 낱말에 '카드' 가 들어 있다

# 손으로 옮겨 적은 현재 결과(첫 셋) — (제목, 핵심 키워드, 글 유형, 점수, 씨앗, 씨앗 출처, 틀, 시기 낱말). 같은 입력의 전체 JSON 은 아래 결정성 시험이 두 번 돌려 같은지 본다.
CASES = {
    ("A", 11): (PROFILE_A, 11, 137, 0, (
        ("쇼핑 행사 시기에 챙겨 볼 소형가전 정리", "쇼핑 행사 소형가전", "정보형", 100.0, "소형가전", "주제", "info-season", "쇼핑 행사"),
        ("늦가을 여행 시기에 챙겨 볼 여행 정리", "늦가을 여행", "정보형", 100.0, "여행", "주제", "info-season", "늦가을 여행"),
        ("늦가을 여행 시기 여행 관리 요령", "늦가을 여행 관리", "정보형", 100.0, "여행", "주제", "info-season-care", "늦가을 여행"))),
    ("A", 6): (PROFILE_A, 6, 155, 0, (
        ("에어컨 시기에 챙겨 볼 소형가전 정리", "에어컨 소형가전", "정보형", 100.0, "소형가전", "주제", "info-season", "에어컨"),
        ("에어컨 시기 소형가전 관리 요령", "에어컨 소형가전 관리", "정보형", 100.0, "소형가전", "주제", "info-season-care", "에어컨"),
        ("장마 시기에 챙겨 볼 제습기 정리", "장마 제습기", "정보형", 100.0, "제습기", "주제", "info-season", "장마"))),
    ("B", 11): (PROFILE_B, 11, 74, 0, (
        ("연말정산 준비 시기에 챙겨 볼 그래픽카드 정리", "연말정산 준비 그래픽카드", "정보형", 100.0, "그래픽카드", "주제", "info-season", YEAR_END),
        ("그래픽카드 처음 알아볼 때 꼭 짚어 둘 기본 정리", "그래픽카드", "정보형", 92.9, "그래픽카드", "주제", "info-basic", YEAR_END),
        ("그래픽카드를 시작하기 전에 확인할 체크리스트", "그래픽카드 체크리스트", "정보형", 92.9, "그래픽카드", "주제", "info-check", YEAR_END))),
    ("B", 6): (PROFILE_B, 6, 68, 1, (
        ("AI 서비스 처음 알아볼 때 꼭 짚어 둘 기본 정리", "AI 서비스", "정보형", 88.2, "AI 서비스", "주제", "info-basic", None),
        ("AI 서비스를 시작하기 전에 확인할 체크리스트", "AI 서비스 체크리스트", "정보형", 88.2, "AI 서비스", "주제", "info-check", None),
        ("AI 서비스 자주 묻는 질문 모음", "AI 서비스 질문", "정보형", 88.2, "AI 서비스", "주제", "info-faq", None))),
}


def run(profile, month, **kwargs):
    return sg.suggest(profile, today=TODAY, count=10, month=month, **kwargs)


def dump(report):
    return json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)


def row(item):
    return (item.topic, item.keyword, item.post_type, item.priority.score, item.seed, item.seed_source, item.frame_id, None if item.season is None else item.season.word)


class DeterminismAndSnapshotTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_same_input_twice_gives_the_same_json_for_profiles_a_and_b_in_june_and_november(self):
        for (name, month), (profile, _month, _generated, _notes, _top) in CASES.items():
            with self.subTest(profile=name, month=month):
                first, second = run(profile, month), run(profile, month)
                self.assertEqual(dump(first), dump(second))
                self.assertEqual((first.blog, first.month, first.today, first.count), (profile.key, month, "2026-11-03", 10))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_first_three_suggestions_and_the_counts_for_the_four_cases(self):
        for (name, month), (profile, _month, generated, notes, top) in CASES.items():
            with self.subTest(profile=name, month=month):
                report = run(profile, month)
                self.assertEqual((len(report.suggestions), report.generated, len(report.notes), report.filtered, report.guidance), (10, generated, notes, (), None))
                self.assertEqual([row(item) for item in report.suggestions[:3]], list(top))
                self.assertEqual([item.rank for item in report.suggestions], list(range(1, 11)))
                self.assertTrue(all(item.blog == profile.key for item in report.suggestions))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_seeds_come_from_the_topic_then_the_categories_then_the_tags(self):
        seeds = lambda profile: [(seed.text, seed.source) for seed in run(profile, 11).seeds]      # noqa: E731
        self.assertEqual(seeds(PROFILE_A), [("소형가전", "주제"), ("제습기", "주제"), ("숙박", "주제"), ("여행", "주제"), ("PC 주변기기", "주제"), ("가전", "카테고리"), ("가성비", "태그")])
        self.assertEqual(seeds(PROFILE_B), [("AI 서비스", "주제"), ("PC 부품", "주제"), ("업무 자동화", "주제"), ("그래픽카드", "주제")])
        self.assertEqual(seeds(PROFILE_B_TAGGED), [("AI 서비스", "주제"), ("PC 부품", "주제"), ("업무 자동화", "주제"), ("그래픽카드", "카테고리"), ("PC", "카테고리")])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_report_and_suggestion_json_have_exactly_these_fields_and_no_caution_or_disclosure_field(self):
        report = run(PROFILE_B, 6)
        self.assertEqual(sorted(report.to_dict()), ["blog", "count", "filtered", "generated", "guidance", "hidden_ranks", "month", "notes", "post_type", "seed_total", "seeds", "suggestions", "today"])
        self.assertEqual(sorted(report.suggestions[0].to_dict()), ["blog", "computed_on", "data", "data_date", "data_text", "factors", "frame", "keyword", "metrics", "post_type", "priority",
                                                                    "profile_fit", "rank", "reason", "season", "seed", "seed_source", "sub_keywords", "topic"])
        self.assertEqual([part.name for part in report.suggestions[0].factors], ["fit", "season", "freshness", "balance"])      # 외부 지표가 없으면 기회도 요인은 빠진다(0점이 아니다)


class SeasonFitCardTest(unittest.TestCase):
    # 월 11 의 '연말정산 준비' 항목은 이어지는 낱말에 '카드' 가 있다. 지금의 `season_fit` 은 낱말 하나가 '카드' 를 **포함하기만 하면** 이어진다고 본다(`word in token`).
    def fit(self, word, month=11):
        score, item = sc.season_fit(word, month)
        return score, None if item is None else item.word

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_card_words_the_operator_means_to_match_do_match_the_year_end_tax_season(self):
        # 신용카드·체크카드·카드값(과 '카드 혜택') 은 금융 카드 이야기라 일치가 의도다 — P0b 가 부분 문자열을 토큰/구문 기반으로 바꾼 뒤에도 그대로여야 한다.
        for word in ("신용카드", "체크카드", "카드값", "카드 혜택", "카드"):
            with self.subTest(word=word):
                self.assertEqual(self.fit(word), (sc.SEASON_RELATED, YEAR_END))
                self.assertEqual([item.word for item in sc.related_items(word, 11)], [YEAR_END])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: '그래픽카드'(컴퓨터 부품)와 '카드뮴'(금속 이름)도 '카드' 를 품었다는 이유만으로 연말정산 시기와 이어진다 — P0b 가 (50, None) 으로 뒤집는다.
    def test_KNOWN_DEFECT_graphics_card_and_cadmium_match_the_year_end_tax_season_only_because_they_contain_card(self):
        for word in ("그래픽카드", "카드뮴"):
            with self.subTest(word=word):
                self.assertEqual(self.fit(word), (sc.SEASON_RELATED, YEAR_END))
                self.assertEqual([item.word for item in sc.related_items(word, 11)], [YEAR_END])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_other_words_that_only_contain_card_also_match_today_and_p0b_decides_each(self):
        # 운영자 예시 밖의 추가 반례(사운드카드·교통카드·메모리카드) — 현재 동작만 적는다. 맞는지 아닌지는 P0b 구현자가 정해 보고한다(여기서는 옳고 그름을 정하지 않는다).
        for word in ("사운드카드", "교통카드", "메모리카드"):
            with self.subTest(word=word):
                self.assertEqual(self.fit(word), (sc.SEASON_RELATED, YEAR_END))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_same_five_words_match_the_neighbouring_year_end_items_in_other_months_and_nothing_in_june(self):
        for word in ("그래픽카드", "신용카드", "체크카드", "카드값", "카드뮴"):
            with self.subTest(word=word):
                self.assertEqual(self.fit(word, 1), (sc.SEASON_RELATED, "연말정산"))
                self.assertEqual(self.fit(word, 2), (sc.SEASON_RELATED, "연말정산"))
                self.assertEqual(self.fit(word, 12), (sc.SEASON_RELATED, "연말정산"))
                self.assertEqual(self.fit(word, 6), (sc.SEASON_NEUTRAL, None))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_matching_is_substring_both_ways_so_a_short_word_inside_a_long_related_word_matches_too(self):
        # 이어지는 낱말('세금'·'공제' …)이 글의 낱말 안에 들어 있어도(`word in token`) 글의 낱말이 이어지는 낱말 안에 들어 있어도(`token in word`) 이어진다.
        self.assertEqual(self.fit("부가세금액"), (sc.SEASON_RELATED, YEAR_END))                 # '세금' ⊂ '부가세금액' (이어지는 낱말이 글의 낱말 안에 든다)
        self.assertEqual(self.fit("의료"), (sc.SEASON_RELATED, YEAR_END))                       # '의료' ⊂ '의료비' (글의 낱말이 이어지는 낱말 안에 든다)
        self.assertEqual(self.fit("직장"), (sc.SEASON_RELATED, YEAR_END))                       # '직장' ⊂ '직장인'
        self.assertEqual(self.fit("세금"), (sc.SEASON_RELATED, YEAR_END))
        self.assertEqual(self.fit("자전거"), (sc.SEASON_NEUTRAL, None))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_season_word_itself_still_scores_a_full_match_and_beats_the_substring_relation(self):
        self.assertEqual(self.fit("연말정산 준비 그래픽카드"), (sc.SEASON_MATCH, YEAR_END))
        self.assertGreater(sc.SEASON_MATCH, sc.SEASON_RELATED)
        self.assertGreater(sc.SEASON_RELATED, sc.SEASON_NEUTRAL)


class GraphicsCardTopSuggestionTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: 프로필 B(AI 서비스·PC 부품·업무 자동화·그래픽카드)의 11월 1위가 '연말정산 준비 시기에 챙겨 볼 그래픽카드 정리' 100점이다 — P0b 가 계절 일치를 고치면 이 제안은 사라진다.
    def test_KNOWN_DEFECT_profile_b_in_november_ranks_a_year_end_tax_title_for_graphics_cards_first(self):
        top = run(PROFILE_B, 11).suggestions[0]
        self.assertEqual((top.topic, top.keyword, top.priority.score, top.priority.level), ("연말정산 준비 시기에 챙겨 볼 그래픽카드 정리", "연말정산 준비 그래픽카드", 100.0, "높음"))
        self.assertEqual((top.season.word, top.frame_id, top.seed, top.seed_source), (YEAR_END, "info-season", "그래픽카드", "주제"))
        self.assertEqual([(part.name, part.value) for part in top.factors], [("fit", 100.0), ("season", 100.0), ("freshness", 100.0), ("balance", 100.0)])
        self.assertIn("연말정산", top.reason)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: 같은 씨앗이어도 '그래픽카드' 가 주제가 아닌 카테고리에서 오면 점수만 94.7 로 내려갈 뿐 같은 제목이 1위다.
    def test_KNOWN_DEFECT_the_same_title_wins_when_the_graphics_card_seed_comes_from_the_category(self):
        report = run(PROFILE_B_TAGGED, 11)
        top = report.suggestions[0]
        self.assertEqual((top.topic, top.priority.score, top.seed_source, top.season.word), ("연말정산 준비 시기에 챙겨 볼 그래픽카드 정리", 94.7, "카테고리", YEAR_END))
        self.assertEqual(report.generated, 91)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: 11월이 아니면(6월) 같은 프로필에서 연말정산 제안이 나오지 않는다 — 결함은 달 표와 부분 일치가 만나는 11·12·1·2월에만 보인다.
    def test_KNOWN_DEFECT_the_year_end_title_appears_only_in_the_months_whose_table_holds_card(self):
        self.assertFalse([item.topic for item in run(PROFILE_B, 6).suggestions if "연말정산" in item.topic])
        for month, word in ((11, YEAR_END), (12, "연말정산"), (1, "연말정산"), (2, "연말정산")):
            with self.subTest(month=month):
                self.assertIn(f"{word} 시기에 챙겨 볼 그래픽카드 정리", [item.topic for item in run(PROFILE_B, month).suggestions])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_real_card_seed_gets_the_same_year_end_title_and_that_one_is_meant(self):
        profile = NaverProfile("naver_a", "카드 블로그", "https://blog.naver.com/testcard", topic="신용카드, 가계부")
        titles = [item.topic for item in run(profile, 11).suggestions]
        self.assertIn("연말정산 준비 시기에 챙겨 볼 신용카드 정리", titles)


class RiskySeedTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: 건강·브랜드 낱말('영양제'·'불면증 해결'·'삼성 갤럭시')은 아무 표시 없이 씨앗이 되어 제안으로 나간다 — 건강·브랜드·협찬 표시 규칙은 코드에 없다(P2 에서 새 모듈이 더한다).
    def test_KNOWN_DEFECT_health_and_brand_seeds_pass_into_suggestions_with_no_caution_mark(self):
        report = sg.suggest(PROFILE_RISKY, today=TODAY, count=10)
        self.assertEqual([(seed.text, seed.source) for seed in report.seeds], [("영양제", "주제"), ("불면증 해결", "주제"), ("삼성 갤럭시", "주제")])
        self.assertEqual(sg.seed_report(sg.view_of(PROFILE_RISKY))[1:], (3, 0, 1))                  # (씨앗 수, 비밀 모양으로 버림, 위험 낱말로 버림)
        titles = [item.topic for item in report.suggestions]
        self.assertEqual(titles[:2], ["영양제 처음 알아볼 때 꼭 짚어 둘 기본 정리", "영양제를 시작하기 전에 확인할 체크리스트"])
        self.assertTrue({"영양제", "불면증 해결", "삼성 갤럭시"} <= {item.seed for item in report.suggestions})
        blob = json.dumps(report.to_dict(), ensure_ascii=False)
        for mark in ("건강", "의학", "협찬", "광고", "브랜드", "전문가"):
            self.assertNotIn(mark, blob, f"제안 결과에 '{mark}' 표시가 생겼다 — 새 규칙이면 이 시험과 계획 문서를 함께 고친다")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_sponsored_trial_seed_is_dropped_and_only_counted_in_a_note(self):
        report = sg.suggest(PROFILE_RISKY, today=TODAY, count=10)
        self.assertNotIn("체험단", json.dumps(report.to_dict(), ensure_ascii=False))
        self.assertTrue(any("씨앗 1개는 쓰지 않았습니다" in note for note in report.notes), report.notes)
        only = sg.suggest(NaverProfile("naver_b", "체험단만", "https://blog.naver.com/testb", topic="체험단 모집"), today=TODAY)
        self.assertEqual((only.suggestions, only.guidance), ((), sg.GUIDANCE))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_risky_word_list_has_no_word_for_health_brand_or_sponsorship_tags_other_than_trial_and_review_words(self):
        pattern = sg._RISKY.pattern.split("|")
        self.assertIn("체험단", pattern)
        self.assertIn("후기", pattern)
        for word in ("협찬", "제휴", "광고", "건강", "영양", "삼성"):
            self.assertNotIn(word, pattern)
        self.assertFalse(sg.is_risky("영양제"))
        self.assertFalse(sg.is_risky("불면증 해결"))
        self.assertFalse(sg.is_risky("삼성 갤럭시"))
        self.assertTrue(sg.is_risky("체험단 모집"))


class OtherChannelsInTheSuggestionServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = support.make_ctx(self.tmp.name)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_only_the_two_naver_blogs_have_profiles_and_the_other_three_always_get_none(self):
        self.assertEqual(NAVER_KEYS, ("naver_a", "naver_b"))
        self.assertEqual([svc.profile_for(self.ctx, blog) for blog in st.PLATFORMS], [None] * 5)               # 아직 프로필을 저장하지 않았다
        support.naver_profiles(self.ctx)
        found = {blog: svc.profile_for(self.ctx, blog) for blog in st.PLATFORMS}
        self.assertEqual([blog for blog, profile in found.items() if profile is not None], ["naver_a", "naver_b"])
        self.assertEqual((found["github_pages"], found["blogger_en"], found["blogger_ko"]), (None, None, None))
        self.assertEqual((found["naver_a"].key, found["naver_b"].key), ("naver_a", "naver_b"))
        self.assertEqual(svc.profiled_blogs(self.ctx), ("naver_a", "naver_b"))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_suggestion_for_a_non_naver_blog_is_an_empty_list_with_the_other_blog_guidance(self):
        support.naver_profiles(self.ctx)
        for blog in ("github_pages", "blogger_en", "blogger_ko"):
            with self.subTest(blog=blog):
                group = svc.run_suggest(self.ctx, blog=blog).groups[0]
                self.assertEqual((group.blog, group.profile_name, group.report.suggestions, group.report.guidance), (blog, "", (), svc.OTHER_BLOG_GUIDANCE))
        for phrase in ("저장해 두는 곳이 아직 없어", "네이버 A·B 프로필의 주제로만", "candidates add", "candidates import-csv"):
            self.assertIn(phrase, svc.OTHER_BLOG_GUIDANCE)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_without_a_blog_the_service_suggests_for_each_saved_naver_profile_and_otherwise_asks_for_naver_a(self):
        group = svc.run_suggest(self.ctx).groups
        self.assertEqual([item.blog for item in group], ["naver_a"])
        self.assertEqual(group[0].report.guidance, sg.GUIDANCE)                                                # 프로필이 없으면 '프로필에 주제를 적어 달라' 안내
        support.naver_profiles(self.ctx)
        self.assertEqual([item.blog for item in svc.run_suggest(self.ctx).groups], ["naver_a", "naver_b"])
        self.assertEqual([item.profile_name for item in svc.run_suggest(self.ctx).groups], ["블로그 에이", "블로그 비"])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_engine_itself_already_accepts_all_five_channel_keys_and_only_the_service_layer_blocks_them(self):
        for blog in st.PLATFORMS:
            with self.subTest(blog=blog):
                report = sg.suggest(PROFILE_B, today=TODAY, blog=blog, count=10, month=11)
                self.assertEqual((report.blog, len(report.suggestions)), (blog, 10))
                self.assertTrue(all(item.blog == blog for item in report.suggestions))
        with self.assertRaises(Exception) as caught:
            sg.suggest(PROFILE_B, today=TODAY, blog="naver_c")
        self.assertEqual(getattr(caught.exception, "code", ""), "CANDIDATE_INVALID")


class RelativeIndexScoreEffectTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: 상대지수 87 이 '월간 검색 수요 87회' 로 들어오면 우선도의 기회도 요인이 38.9점으로 계산되어 우선도가 9.2점 내려간다(없을 때 81.8 → 72.6) — 상대값과 횟수를 구분하는 장치가 없다.
    def test_KNOWN_DEFECT_a_relative_index_of_87_is_scored_as_87_searches_and_lowers_the_priority(self):
        from chanceblog_desktop.content import candidates as cd
        bare = cd.Candidate.new("주제 테스트 문장", "키워드", ("naver_b",), candidate_id="c0", now="2026-11-03T00:00:00Z")
        indexed = cd.Candidate.new("주제 테스트 문장", "키워드", ("naver_b",), candidate_id="c1", now="2026-11-03T00:00:00Z", search_demand=87, data_date="2026-11-03")
        without, with_87 = (sg.assess(item, profile=None, today=TODAY) for item in (bare, indexed))
        self.assertEqual((without.priority.score, [part.name for part in without.parts]), (81.8, ["season", "freshness", "balance"]))
        self.assertEqual((with_87.priority.score, [(part.name, round(part.value, 2)) for part in with_87.parts]),
                         (72.6, [("season", 50.0), ("freshness", 100.0), ("balance", 100.0), ("opportunity", 38.89)]))


if __name__ == "__main__":
    unittest.main()
