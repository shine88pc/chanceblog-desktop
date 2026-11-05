"""특성 시험(P0) — 규칙 기반 제안 엔진(`content/suggest*.py`)과 제안 서비스의 '네이버 둘뿐' 가정을 **현재 모습 그대로** 못박는다(계획 문서 `docs/TOPIC_ENGINE_PLAN.md` 의 G2·G4 제안 쪽). 네트워크·시크릿·실제 시계·자식 프로세스 없음(날짜는 `today` 인자).

왜: 5채널 주제 선정 전략의 새 엔진을 얹기 전에, 지금의 제안 결과(같은 입력 → 같은 결과)가 뒤의 단계에서 소리 없이 바뀌지 않게 못박는다. 이 시험은 '옳다고 정한 것' 이 아니라 '지금 이렇다' 이다 —
바꾸려면 새 결정(D-nn)을 쓰고 해당 시험을 의식적으로 고친다. 현재 동작이 마음에 안 드는 것(알려진 결함)은 이름에 `KNOWN_DEFECT` 를 달았다 — 위험 씨앗의 건강·브랜드 표시 없음(P2)·Legacy 상대값 87 이 우선도를 내림(뒤집는 단계 없음). 계절 낱말의 부분 일치는 P0b 가 토큰/구문 기반으로
바꾸며 의도적으로 뒤집었다(D-42) — 그 시험들은 `KNOWN_DEFECT` 이름을 지우고 새 기대로 고쳤으며 각 시험 위 주석에 '(P0b 가 의도적으로 바꿈, D-42)' 이력이 있다. 새 규칙의 전체 시험은 `tests/test_season_match.py`.
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
from chanceblog_desktop.content import candidates as cd  # noqa: E402
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
    # (P0b 가 의도적으로 바꿈, D-42) 이 줄은 P0 때 '연말정산 준비 시기에 챙겨 볼 그래픽카드 정리' 100점 …(조합 74·알림 0)이었다. 이제는 6월과 같다 — 그래픽카드는 금융 카드가 아니라 시기 제안이 없다(조합 68·알림 1).
    ("B", 11): (PROFILE_B, 11, 68, 1, (
        ("AI 서비스 처음 알아볼 때 꼭 짚어 둘 기본 정리", "AI 서비스", "정보형", 88.2, "AI 서비스", "주제", "info-basic", None),
        ("AI 서비스를 시작하기 전에 확인할 체크리스트", "AI 서비스 체크리스트", "정보형", 88.2, "AI 서비스", "주제", "info-check", None),
        ("AI 서비스 자주 묻는 질문 모음", "AI 서비스 질문", "정보형", 88.2, "AI 서비스", "주제", "info-faq", None))),
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
    # 월 11 의 '연말정산 준비' 항목의 이어지는 낱말에는 금융 카드 구문(신용카드·체크카드·카드값·카드 혜택 …, `suggest_data.FINANCE_CARDS`)이 있다. P0 때는 '카드' 한 낱말이 있었고 `season_fit` 은 낱말 하나가 '카드' 를
    # **포함하기만 하면**(`word in token`) 이어진다고 보았다. P0b 가 토큰/구문 일치로 바꾸고(D-42) 이 클래스의 KNOWN_DEFECT 시험들을 의도적으로 뒤집었다 — 각 시험 위 주석에 이력이 있다.
    def fit(self, word, month=11):
        score, item = sc.season_fit(word, month)
        return score, None if item is None else item.word

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_card_words_the_operator_means_to_match_do_match_the_year_end_tax_season(self):
        # 신용카드·체크카드·카드값(과 '카드 혜택'·'법인카드'·'카드 공제'·띄어 쓴 '신용 카드') 은 금융 카드 이야기라 일치가 의도다 — P0b 가 부분 문자열을 토큰/구문 기반으로 바꾼 뒤에도 그대로다.
        # (P0 의 목록에는 '카드' 한 낱말도 있었다 — 뜻이 여럿이라 P0b 가 뺐다: 바로 아래 시험, D-42)
        for word in ("신용카드", "체크카드", "카드값", "카드 혜택", "법인카드", "카드 공제", "신용 카드", "체크 카드", "법인 카드", "직불 카드", "선불 카드"):
            with self.subTest(word=word):
                self.assertEqual(self.fit(word), (sc.SEASON_RELATED, YEAR_END))
                self.assertEqual([item.word for item in sc.related_items(word, 11)], [YEAR_END])

    # 의도적 변경 시험(P0b, D-42): P0 의 시험은 '카드' 한 낱말도 연말정산 시기와 이어진다고 못박았다 — P0b 가 의도적으로 바꿨다. '카드' 는 금융 카드·그래픽카드·게임 카드·카드 뉴스를 다 뜻해서 낱말 하나로는 모른다('모름 ≠ 0' — 감점이 아니라 시기와 무관한 중립 50).
    def test_the_bare_word_card_is_too_vague_to_connect_to_the_year_end_tax_season(self):
        self.assertEqual(self.fit("카드"), (sc.SEASON_NEUTRAL, None))
        self.assertEqual(sc.related_items("카드", 11), ())
        self.assertEqual(self.fit("그래픽 카드"), (sc.SEASON_NEUTRAL, None), "띄어 써도 '카드' 낱말 하나로는 이어지지 않는다")

    # 의도적 변경 시험(P0b, D-42): P0 의 KNOWN_DEFECT 시험('그래픽카드'·'카드뮴' 이 '카드' 를 품었다는 이유만으로 (70, 연말정산 준비))을 P0b 가 의도적으로 뒤집었다 — 낱말 속 글자 조각은 일치로 보지 않는다.
    def test_graphics_card_and_cadmium_do_not_match_the_year_end_tax_season(self):
        for word in ("그래픽카드", "카드뮴"):
            with self.subTest(word=word):
                self.assertEqual(self.fit(word), (sc.SEASON_NEUTRAL, None))
                self.assertEqual(sc.related_items(word, 11), ())

    # 의도적 변경 시험(P0b, D-42): P0 는 추가 반례(사운드카드·교통카드·메모리카드)의 현재 값(모두 일치)만 적고 옳고 그름은 P0b 가 정하라고 했다 — 여섯 모두 금융 카드가 아니라 일치하지 않는 것으로 정했다.
    # 사운드카드·메모리카드·SD카드·카드키=컴퓨터·전자 부품/물건, 교통카드=버스·지하철 결제 수단(연말정산의 신용·체크·직불·선불 카드와 다른 말로 쓰여 따로 적지 않았다), 크리스마스카드=인사 카드(12월엔 '크리스마스' 시기).
    def test_other_words_that_only_contain_card_do_not_match_either_and_p0b_decided_each(self):
        for word in ("사운드카드", "교통카드", "메모리카드", "SD카드", "크리스마스카드", "카드키"):
            with self.subTest(word=word):
                self.assertEqual(self.fit(word), (sc.SEASON_NEUTRAL, None))

    # 의도적 변경 시험(P0b, D-42): P0 의 시험은 다섯 낱말이 1·2·12월 '연말정산' 에 모두 걸린다고 못박았다 — 이제 금융 카드 셋만 걸리고 그래픽카드·카드뮴은 어느 달에도 안 걸린다. 6월은 그대로 아무것도 안 걸린다.
    def test_the_financial_card_words_match_the_neighbouring_year_end_items_and_the_others_match_nothing_in_any_month(self):
        for word in ("신용카드", "체크카드", "카드값"):
            with self.subTest(word=word):
                self.assertEqual(self.fit(word, 1), (sc.SEASON_RELATED, "연말정산"))
                self.assertEqual(self.fit(word, 2), (sc.SEASON_RELATED, "연말정산"))
                self.assertEqual(self.fit(word, 12), (sc.SEASON_RELATED, "연말정산"))
                self.assertEqual(self.fit(word, 6), (sc.SEASON_NEUTRAL, None))
        for word in ("그래픽카드", "카드뮴"):
            for month in range(1, 13):
                with self.subTest(word=word, month=month):
                    self.assertEqual(self.fit(word, month), (sc.SEASON_NEUTRAL, None))

    # 의도적 변경 시험(P0b, D-42): P0 의 시험은 일치가 부분 문자열 양쪽('세금' ⊂ '부가세금액'·'의료' ⊂ '의료비'·'직장' ⊂ '직장인')이라고 못박았다 — P0b 가 낱말 속-낱말 일치를 모두 없앴다(부가세금액·의료·직장은 오탐 제거).
    # 표의 낱말과 통째로 같은 것('의료비'·'직장인'·'세금')과 거기에 조사만 붙은 것('세금을')은 그대로 이어진다.
    def test_the_matching_is_whole_word_so_a_short_word_inside_a_long_word_no_longer_matches(self):
        self.assertEqual(self.fit("부가세금액"), (sc.SEASON_NEUTRAL, None))                      # '세금' ⊂ '부가세금액' — 낱말 속 글자 조각
        self.assertEqual(self.fit("의료"), (sc.SEASON_NEUTRAL, None))                            # '의료' ⊂ '의료비' — 글의 낱말이 표의 낱말 속에 든 경우
        self.assertEqual(self.fit("직장"), (sc.SEASON_NEUTRAL, None))                            # '직장' ⊂ '직장인'
        for word in ("세금", "세금을", "의료비", "의료비를", "직장인", "직장인은"):
            with self.subTest(word=word):
                self.assertEqual(self.fit(word), (sc.SEASON_RELATED, YEAR_END))
        self.assertEqual(self.fit("자전거"), (sc.SEASON_NEUTRAL, None))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_season_word_itself_still_scores_a_full_match_and_beats_the_substring_relation(self):
        self.assertEqual(self.fit("연말정산 준비 그래픽카드"), (sc.SEASON_MATCH, YEAR_END))
        self.assertGreater(sc.SEASON_MATCH, sc.SEASON_RELATED)
        self.assertGreater(sc.SEASON_RELATED, sc.SEASON_NEUTRAL)


class SeasonGenericWordTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_text_with_only_a_generic_word_does_not_connect_to_a_season_whose_name_contains_it(self):
        # '준비'·'마무리'·'행사' 는 시기 이름의 일부여도('종합소득세 준비'·'여름 마무리'·'쇼핑 행사') 주제를 가리키지 않는 흔한 말이라 이어지는 낱말로 쓰지 않는다(`GENERIC_WORD_STEMS`).
        self.assertEqual(sc.GENERIC_WORD_STEMS, frozenset({"준비", "시즌", "시기", "행사", "마무리"}))
        for text, month in (("테스트 준비", 4), ("테스트 마무리", 8), ("테스트 행사", 11), ("테스트 시기", 11)):
            with self.subTest(text=text, month=month):
                self.assertEqual(sc.season_fit(text, month), (sc.SEASON_NEUTRAL, None))
        # 같은 항목이어도 흔한 말을 뺀 나머지 낱말은 이어지고(70), 이름 전체가 들어 있으면 일치한다(100)
        scores = [sc.season_fit(text, month)[0] for text, month in (("종합소득세", 4), ("종합소득세 준비", 4), ("쇼핑", 11), ("쇼핑 행사", 11), ("여름 마무리", 8))]
        self.assertEqual(scores, [sc.SEASON_RELATED, sc.SEASON_MATCH, sc.SEASON_RELATED, sc.SEASON_MATCH, sc.SEASON_MATCH])


class GraphicsCardTopSuggestionTest(unittest.TestCase):
    # 의도적 변경 시험(P0b, D-42): P0 의 KNOWN_DEFECT 시험은 프로필 B(AI 서비스·PC 부품·업무 자동화·그래픽카드)의 11월 1위가 '연말정산 준비 시기에 챙겨 볼 그래픽카드 정리' 100점이라고 못박았다 — P0b 가 의도적으로 뒤집었다.
    # 이제 11월 1위는 시기와 무관한 '정보형 기본' 제안이다(점수 88.2 = 프로필 적합도 100 · 시기 50(중립) · 신선도 100 · 균형 100 의 가중 평균).
    def test_profile_b_in_november_no_longer_ranks_a_year_end_tax_title_for_graphics_cards_first(self):
        report = run(PROFILE_B, 11)
        top = report.suggestions[0]
        self.assertEqual((top.topic, top.keyword, top.priority.score, top.priority.level), ("AI 서비스 처음 알아볼 때 꼭 짚어 둘 기본 정리", "AI 서비스", 88.2, "높음"))
        self.assertEqual((top.season, top.frame_id, top.seed, top.seed_source), (None, "info-basic", "AI 서비스", "주제"))
        self.assertEqual([(part.name, part.value) for part in top.factors], [("fit", 100.0), ("season", 50.0), ("freshness", 100.0), ("balance", 100.0)])
        for item in report.suggestions:
            self.assertNotIn("연말정산", item.topic + item.reason)
        self.assertEqual((report.generated, len(report.notes)), (68, 1))
        self.assertIn("시기 맞춤 제안은 만들지 못했습니다", report.notes[0])

    # 의도적 변경 시험(P0b, D-42): P0 의 KNOWN_DEFECT 시험은 '그래픽카드' 가 카테고리에서 와도 같은 제목이 94.7 로 1위라고 못박았다 — P0b 가 의도적으로 뒤집었다. 씨앗이 어디서 오든 같은 제목은 없다(조합 91 → 85).
    def test_the_year_end_title_is_gone_also_when_the_graphics_card_seed_comes_from_the_category(self):
        report = run(PROFILE_B_TAGGED, 11)
        top = report.suggestions[0]
        self.assertEqual((top.topic, top.priority.score, top.seed_source, top.season), ("AI 서비스 처음 알아볼 때 꼭 짚어 둘 기본 정리", 88.2, "주제", None))
        self.assertEqual(report.generated, 85)
        self.assertFalse([item.topic for item in report.suggestions if "연말정산" in item.topic])

    # 의도적 변경 시험(P0b, D-42): P0 의 KNOWN_DEFECT 시험은 연말정산 제목이 표에 '카드' 가 든 달(11·12·1·2월)에만 나온다고 못박았다 — 이제 프로필 B 는 어느 달에도 시기 제안이 없다(조합·알림·1위가 열두 달 모두 같다).
    # 1월에는 '가계부' 항목에도 '카드' 가 들어 있어 '가계부 시기에 챙겨 볼 그래픽카드 정리' 도 나왔었다(P0 가 못박지 못한 같은 오탐) — 그것도 사라졌다.
    def test_the_year_end_title_for_graphics_cards_appears_in_no_month(self):
        for month in range(1, 13):
            with self.subTest(month=month):
                report = run(PROFILE_B, month)
                self.assertEqual((report.generated, len(report.notes), report.suggestions[0].topic), (68, 1, "AI 서비스 처음 알아볼 때 꼭 짚어 둘 기본 정리"))
                self.assertFalse([item.topic for item in report.suggestions if item.season is not None])
                self.assertFalse([item.topic for item in report.suggestions if "시기에 챙겨 볼 그래픽카드" in item.topic])

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
        pattern = sg._RISKY.pattern.split("|")                                      # 비공개 이름 — 바뀌면 이 시험을 고친다
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


class StoredCandidatePriorityTest(unittest.TestCase):
    """보관함 후보의 우선도 계산(`sg.assess` — `candidates list --priority`·`candidates show` 가 `service/suggestions.py` 를 거쳐 쓴다)도 제안과 **같은 `season_fit`** 을 쓴다. 그래서 계절 낱말 부분 일치의 영향은 제안 결과에만 있지 않다."""

    def assess(self, word, profile=None, **fields):
        item = cd.Candidate.new(f"{word} 고르는 법", word, ("naver_b",), candidate_id="c0000001", now="2026-11-03T00:00:00Z", **fields)
        return sg.assess(item, profile=profile, today=TODAY, month=11)

    # 의도적 변경 시험(P0b, D-42): P0 의 KNOWN_DEFECT 시험은 보관함 후보 '그래픽카드'·'카드뮴' 이 11월에 시기 요인 70점과 '연말정산 준비' 이유를 받아 우선도 89.1(프로필 B 가 있으면 92.9)이라고 못박았다 — P0b 가 의도적으로 뒤집었다.
    # 이제 평범한 낱말('자전거')과 같은 81.8(프로필 B 가 있으면 88.2)이고 추천 이유에 시기 문장이 없다.
    def test_a_stored_candidates_priority_no_longer_reads_graphics_card_and_cadmium_as_the_year_end_season(self):
        for word in ("그래픽카드", "카드뮴"):
            with self.subTest(word=word):
                found = self.assess(word)
                self.assertEqual((found.priority.score, found.priority.level, found.season), (81.8, "높음", None))
                self.assertEqual([(part.name, part.value) for part in found.parts], [("season", 50.0), ("freshness", 100.0), ("balance", 100.0)])
                self.assertNotIn("연말정산", found.reason)
        with_profile = self.assess("그래픽카드", PROFILE_B)
        self.assertEqual((with_profile.priority.score, with_profile.fit, with_profile.season), (88.2, 100, None))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_intended_card_words_get_the_same_season_factor_and_a_plain_word_gets_the_neutral_one(self):
        for word in ("신용카드", "체크카드", "카드값"):                                            # 금융 카드 — P0b 뒤에도 그대로여야 한다
            with self.subTest(word=word):
                found = self.assess(word)
                self.assertEqual((found.priority.score, found.season.word), (89.1, YEAR_END))
        plain = self.assess("자전거")
        self.assertEqual((plain.priority.score, plain.season, [(part.name, part.value) for part in plain.parts][0]), (81.8, None, ("season", 50.0)))
        self.assertNotIn("연말정산", plain.reason)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_external_months_on_the_candidate_decide_the_season_factor_without_reading_the_word(self):
        in_season = self.assess("그래픽카드", seasonality=(11,), data_date="2026-11-03")
        off_season = self.assess("그래픽카드", seasonality=(6,), data_date="2026-11-03")
        self.assertEqual(([(part.name, part.value) for part in in_season.parts][0], in_season.season), (("season", 100.0), None))
        self.assertEqual(([(part.name, part.value) for part in off_season.parts][0], off_season.season, off_season.priority.score), (("season", 30.0), None, 74.5))


class RelativeIndexScoreEffectTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: 상대지수 87 이 '월간 검색 수요 87회' 로 들어오면 우선도의 기회도 요인이 38.9점으로 계산되어 우선도가 9.2점 내려간다(없을 때 81.8 → 72.6) — 상대값과 횟수를 구분하는 장치가 없다.
    # 뒤집는 단계가 계획에 없다 — Legacy 칸은 그대로 두고(D-37 ③) 새 Trend 칸이 대신한다. 이 시험은 '이 칸은 상대값과 횟수를 구분하지 못해 우선도가 내려간다' 는 현재 모습을 계속 기록한다.
    def test_KNOWN_DEFECT_a_relative_index_of_87_is_scored_as_87_searches_and_lowers_the_priority(self):
        bare = cd.Candidate.new("주제 테스트 문장", "키워드", ("naver_b",), candidate_id="c0", now="2026-11-03T00:00:00Z")
        indexed = cd.Candidate.new("주제 테스트 문장", "키워드", ("naver_b",), candidate_id="c1", now="2026-11-03T00:00:00Z", search_demand=87, data_date="2026-11-03")
        without, with_87 = (sg.assess(item, profile=None, today=TODAY) for item in (bare, indexed))
        self.assertEqual((without.priority.score, [part.name for part in without.parts]), (81.8, ["season", "freshness", "balance"]))
        self.assertEqual((with_87.priority.score, [(part.name, round(part.value, 2)) for part in with_87.parts]),
                         (72.6, [("season", 50.0), ("freshness", 100.0), ("balance", 100.0), ("opportunity", 38.89)]))


if __name__ == "__main__":
    unittest.main()
