"""계절(시기) 일치 규칙 시험(P0b, 결정 D-42) — 씨앗 낱말과 월 표의 '이어지는 낱말'이 **낱말 통째·구문** 으로만 맞고 부분 문자열로는 맞지 않는다.

지키는 것:
  1) 운영자 예시(2026-11-04 조건 5): 신용카드·체크카드·카드값 = 금융 카드 = '연말정산' 시기와 이어짐 / 그래픽카드·카드뮴 ≠. 같은 달의 '카드 혜택'·'법인카드' = . 추가 반례(사운드카드·교통카드·메모리카드·SD카드·크리스마스카드·카드키)는 모두 ≠ 로 정했다.
  2) 경계 규칙: 씨앗 낱말이 표의 낱말과 **통째로 같거나 뒤에 조사(`PARTICLE_TAILS`)만 붙은 것**이어야 한다. 낱말 속 글자 조각('아이폰' 의 '아이')·글의 낱말이 표의 낱말 속에 든 경우('의료' ⊂ '의료비')는 이어지지 않는다.
     띄어 쓴 구문('카드 혜택')은 그 낱말들이 글에 나란히(같은 차례로) 있어야 한다. 붙여 쓴 복합어('소형가전'·'해외여행')는 `RELATED_COMPOUNDS` 에 적힌 것만 이어진다.
  3) 정당했던 일치가 사라지지 않는다: 프로필 A·B 의 씨앗과 흔한 복합어는 표(와 복합어 사전)에 적어 두었고, 사전은 줄마다 값까지 못박는다(`EXPECTED_COMPOUNDS` — 줄을 소리 없이 지우거나 바꾸면 깨진다).
     시기 낱말 자체가 든 글은 그대로 `SEASON_MATCH`(100). 조사 붙은 오탐('아이폰을'·'카드뮴은')과 목록 밖 꼬리('세금들')도 이어지지 않는다.
  4) 결정성: 같은 입력은 같은 결과(캐시를 비워도). 모두 순수 계산이라 네트워크·실제 시계·자식 프로세스가 없다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import suggest_support as sp  # noqa: E402

from chanceblog_desktop.content import suggest as sg  # noqa: E402
from chanceblog_desktop.content import suggest_data as data  # noqa: E402
from chanceblog_desktop.content import suggest_score as sc  # noqa: E402
from chanceblog_desktop.content import suggest_text as tx  # noqa: E402
from chanceblog_desktop.content.suggest_data import FRAMES  # noqa: E402

PLAIN = [frame for frame in FRAMES if not frame.seasonal]
SEASONAL = [frame for frame in FRAMES if frame.seasonal]
CARD_ITEMS = {1: ["연말정산", "가계부"], 2: ["연말정산"], 11: ["연말정산 준비"], 12: ["연말정산"]}      # 금융 카드 구문이 든 시기 항목(달 → 표의 순서대로)
# 복합어 사전의 기대 값 — `suggest_data.RELATED_COMPOUNDS` 와 줄마다 같아야 한다(일부러 따로 적었다: 사전의 줄을 지우거나 바꾸면 이 시험이 깨져, 고칠 때는 이유를 적고 둘을 함께 고친다. D-42)
EXPECTED_COMPOUNDS = {
    # 집·살림·가전
    "가전": ("소형가전", "생활가전", "주방가전", "대형가전", "백색가전", "계절가전", "스마트가전", "청소가전", "미용가전", "가전제품", "가전할인"),
    "주방": ("주방가전", "주방용품"), "청소": ("대청소", "청소기", "로봇청소기", "청소가전", "에어컨청소"), "세탁": ("세탁기", "세탁소"), "빨래": ("이불빨래",), "이불": ("이불빨래", "겨울이불"), "침구": ("여름침구",),
    "정리": ("정리정돈",), "살림": ("살림꿀팁", "살림팁"), "곰팡이": ("곰팡이제거",), "방충": ("방충망",),
    # 난방·전기·냉방
    "난방": ("난방비", "난방기구", "난방용품", "난방절약"), "보일러": ("보일러교체", "보일러점검"), "전기": ("전기세", "전기히터", "전기요금", "전기장판"), "가스": ("가스비",), "에너지": ("에너지절약",),
    "절약": ("난방절약", "에너지절약", "생활절약", "절약팁", "전기절약"), "단열": ("단열재",), "방한": ("방한복",), "냉방": ("냉방비",), "에어컨": ("에어컨청소", "에어컨설치"), "제습": ("제습기",),
    # 계절·날씨
    "늦가을": ("늦가을여행",), "가을": ("가을철", "가을여행"), "겨울": ("겨울철", "겨울이불", "겨울여행", "겨울타이어", "겨울옷", "겨울방학"), "여름": ("여름철", "여름침구", "여름휴가", "여름옷", "여름방학"),
    "장마": ("장마철", "장마대비"), "김장": ("김장철", "김장김치"), "벚꽃": ("벚꽃명소",), "나들이": ("봄나들이", "가족나들이"),
    # 여행·휴가·야외
    "여행": ("국내여행", "해외여행", "가족여행", "제주여행", "신혼여행", "겨울여행", "단풍여행", "여행지"), "휴가": ("휴가철", "여름휴가"), "항공": ("항공권",), "캠핑": ("캠핑용품", "캠핑장비", "캠핑장"), "수영": ("수영장",), "스키": ("스키장",),
    # 건강
    "건강": ("건강검진", "건강관리", "건강식품"), "면역": ("면역력",), "감기": ("감기약",), "독감": ("독감예방접종",), "예방": ("예방접종",), "영양": ("영양제",), "비타민": ("비타민C", "비타민D"), "불면": ("불면증",),
    "피부": ("피부관리",), "다이어트": ("다이어트식단",), "헬스": ("헬스장",),
    # 아이·학교
    "아이": ("아이들", "아이옷"), "육아": ("육아용품",), "교육": ("교육비",), "학습": ("학습지",), "공부": ("공부법",), "학교": ("초등학교", "중학교", "고등학교", "대학교"), "입학": ("입학준비",), "학기": ("새학기",),
    "수능": ("수능도시락",), "활동": ("봉사활동",), "습관": ("생활습관",), "졸업": ("졸업사진",),
    # 돈·세금
    "보험": ("자동차보험", "실비보험", "보험료", "보험가입"), "연금": ("국민연금", "연금저축", "퇴직연금"), "저축": ("연금저축",), "공제": ("소득공제", "세액공제", "의료비공제"), "세금": ("세금환급",),
    "부가세": ("부가세신고",), "연말정산": ("연말정산서류", "연말정산환급", "연말정산간소화"), "가계부": ("가계부앱",), "세무": ("세무사",), "급여": ("급여명세서",),
    # 명절·기념일·쇼핑·기타
    "선물": ("선물세트", "추석선물", "설선물", "크리스마스선물"), "추석": ("추석선물", "추석명절"), "명절": ("추석명절", "설명절"), "크리스마스": ("크리스마스트리", "크리스마스선물", "크리스마스카드", "크리스마스케이크"),
    "핼러윈": ("핼러윈파티",), "발렌타인": ("발렌타인데이",), "월동": ("월동준비",), "쇼핑": ("쇼핑몰", "쇼핑행사", "온라인쇼핑"), "이사": ("이사업체",), "이삿짐": ("이삿짐센터",),
    "차례": ("차례상",), "귀성": ("귀성길",), "예식": ("예식장",),
    "자동차": ("자동차점검", "자동차보험"), "점검": ("자동차점검", "안전점검"), "안전": ("안전점검",), "타이어": ("겨울타이어",),
}


def related(word, month):
    return [item.word for item in sc.related_items(word, month)]


def fit(word, month):
    return sc.season_fit(word, month)[0]


def legacy_related(word, month):
    """P0b 이전의 일치 규칙(낱말이 이어지는 낱말을 포함하거나 서로 포함되면 이어진다)을 **지금 표에** 적용한 참고 구현 — '옛 규칙이면 걸렸을' 낱말만 골라 시험 예가 처음부터 안 걸리는 낱말이 아님을 보인다."""
    stems = tx.stems(word)
    found = []
    for item in data.SEASONS[month]:
        words = frozenset(tx.stem(entry) for entry in item.related) | (tx.stem_set(item.word) - sc.GENERIC_WORD_STEMS)
        if any(len(token) >= tx.MIN_STEM and len(entry) >= tx.MIN_STEM and (token == entry or entry in token or token in entry) for token in stems for entry in words):
            found.append(item.word)
    return found


def table_words(item):
    """표가 그 항목의 '한 낱말' 로 적은 것 — 한 낱말짜리 이어지는 낱말과 시기 낱말의 낱말(두 글자 이상, 흔한 말 제외)."""
    singles = {parts[0] for parts in (tx.words(entry) for entry in item.related) if len(parts) == 1}
    singles |= {word for word in tx.words(item.word) if len(tx.stem(word)) >= tx.MIN_STEM and tx.stem(word) not in sc.GENERIC_WORD_STEMS}
    return singles


class OperatorExamplesTest(unittest.TestCase):
    def test_credit_check_and_card_bill_connect_to_the_finance_items_of_every_month_and_to_nothing_else(self):
        for word in ("신용카드", "체크카드", "카드값"):
            for month in range(1, 13):
                with self.subTest(word=word, month=month):
                    self.assertEqual(related(word, month), CARD_ITEMS.get(month, []))
                    self.assertEqual(fit(word, month), sc.SEASON_RELATED if month in CARD_ITEMS else sc.SEASON_NEUTRAL)

    def test_graphics_card_and_cadmium_connect_to_no_item_in_any_month(self):
        for word in ("그래픽카드", "카드뮴"):
            for month in range(1, 13):
                with self.subTest(word=word, month=month):
                    self.assertEqual(related(word, month), [])
                    self.assertEqual(sc.season_fit(word, month), (sc.SEASON_NEUTRAL, None))

    def test_the_five_operator_examples_in_november_score_70_70_70_50_50(self):
        self.assertEqual([fit(word, 11) for word in ("신용카드", "체크카드", "카드값", "그래픽카드", "카드뮴")], [70, 70, 70, 50, 50])

    def test_card_benefit_and_corporate_card_and_the_other_finance_card_phrases_connect_like_the_three_examples(self):
        # '카드 혜택'·'법인카드'(운영자 예시) + '카드 공제'·'직불카드'·'선불카드'·띄어 쓴 '신용 카드'·붙여 쓴 '카드혜택' — 연말정산의 신용카드 등 사용금액과 가계부의 카드 지출 이야기라 같은 항목과 이어진다.
        for word in data.FINANCE_CARDS + ("카드 혜택을 비교", "법인카드로 결제", "법인 카드를 쓰는", "직불 카드는", "선불 카드로", "법인 카드", "직불 카드", "선불 카드"):
            for month in (1, 2, 6, 11, 12):
                with self.subTest(word=word, month=month):
                    self.assertEqual(related(word, month), CARD_ITEMS.get(month, []))

    def test_the_extra_counter_examples_are_decided_one_by_one_and_none_is_a_finance_card(self):
        # 사운드카드·메모리카드·SD카드·카드키 = 컴퓨터·전자 물건, 교통카드 = 버스·지하철 결제 수단(연말정산의 카드 항목에 따로 적지 않았다), 크리스마스카드 = 인사 카드 → 12월에는 '크리스마스' 시기와 이어진다(연말정산이 아니다).
        for word in ("사운드카드", "교통카드", "메모리카드", "SD카드", "크리스마스카드", "카드키"):
            for month in range(1, 13):
                with self.subTest(word=word, month=month):
                    wanted = ["크리스마스"] if (word, month) == ("크리스마스카드", 12) else []
                    self.assertEqual(related(word, month), wanted)

    def test_the_spaced_finance_cards_are_as_consistent_as_the_joined_ones_but_a_spaced_card_bill_is_not(self):
        # 붙여 쓴 5종(신용·체크·직불·선불·법인카드)은 띄어 쓴 꼴('법인 카드')도 같이 이어진다(독립 검증 L3). '카드 값' 은 '그래픽 카드 값' 오탐 때문에 계속 뺀다.
        for kind in ("신용", "체크", "직불", "선불", "법인"):
            for month in range(1, 13):
                with self.subTest(kind=kind, month=month):
                    self.assertEqual(related(f"{kind}카드", month), related(f"{kind} 카드", month))
                    self.assertEqual(related(f"{kind} 카드", month), CARD_ITEMS.get(month, []))
        self.assertEqual(related("카드 값", 11), [])

    def test_the_bare_word_card_is_too_vague_to_connect_anywhere(self):
        for word in ("카드", "카드를", "그래픽 카드", "카드 비교"):
            for month in range(1, 13):
                with self.subTest(word=word, month=month):
                    self.assertEqual(related(word, month), [])


class WholeWordRuleTest(unittest.TestCase):
    def test_the_particle_list_is_these_35_and_the_stemmer_strips_every_one_of_them(self):
        one = {"은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만", "으로", "에서", "까지", "부터", "이나", "이랑", "하고", "처럼"}
        added = {"에는", "에도", "에서는", "에서도", "으로는", "보다", "마다", "에게", "한테", "라도", "이라", "이며", "이란", "랑"}      # 낱말 처리의 어미 목록과 맞추려고 더한 14개(수정 2차)
        self.assertEqual(sc.PARTICLE_TAILS, frozenset(one | added))
        self.assertEqual(len(sc.PARTICLE_TAILS), 35)
        self.assertFalse({"들", "나는", "나", "라고", "라는"} & sc.PARTICLE_TAILS, "복수 '들'·'나는' 같은 말은 오탐 위험이라 넣지 않았다")
        for tail in sc.PARTICLE_TAILS:
            with self.subTest(tail=tail):
                word = "연말정산" + tail
                for _ in range(2):                                    # 한 번에 떼는 어미가 대부분이고 '으로는' 만 '으로' + '는' 두 번에 뗀다
                    word = tx.stem(word)
                self.assertEqual(word, "연말정산", "목록의 조사는 낱말 처리(`suggest_text.stem`)도 조사로 떼어야 한다 — 두 목록이 어긋나지 않게")

    def test_a_table_word_with_only_a_particle_after_it_still_connects(self):
        for tail in sorted(sc.PARTICLE_TAILS):
            with self.subTest(tail=tail):
                self.assertEqual(related("세금" + tail, 11), ["연말정산 준비"])
                self.assertEqual(related("김장" + tail, 11), ["김장"])

    def test_any_other_letters_after_the_table_word_make_it_another_word(self):
        for tail in ("액", "뮴", "폰", "화", "장", "기", "책", "표", "원", "소", "디어", "템"):
            with self.subTest(tail=tail):
                self.assertEqual(related("세금" + tail, 11), [])
                self.assertEqual(related("아이" + tail, 12), [])

    def test_a_table_word_inside_or_at_the_end_of_a_longer_word_does_not_connect(self):
        # 같은 낱말이 앞에 붙은 글자에도 속지 않는다 — 안쪽('매트리스' 의 '트리')·끝('유튜브' 의 '튜브')·다른 낱말의 앞머리('아이폰' 의 '아이').
        self.assertEqual(related("트리", 12), ["크리스마스"], "표에 '트리' 가 낱말로 있는 달은 이어진다(비교용)")
        for word, month in (("매트리스", 12), ("유튜브", 7), ("아이폰", 12), ("부가세금액", 11)):
            with self.subTest(word=word, month=month):
                self.assertEqual(related(word, month), [])

    def test_the_words_of_a_phrase_must_stand_side_by_side_in_the_same_order(self):
        self.assertEqual(related("카드 혜택", 11), ["연말정산 준비"])
        self.assertEqual(related("올해 카드 혜택 정리", 11), ["연말정산 준비"], "글 안 어디에 있어도 된다")
        self.assertEqual(related("카드의 혜택", 11), ["연말정산 준비"], "낱말 사이의 조사는 건너뛴다")
        for word in ("카드 비교 혜택", "혜택 카드", "혜택", "카드"):
            with self.subTest(word=word):
                self.assertEqual(related(word, 11), [])

    def test_spaces_and_marks_split_words_the_same_way_for_the_text_and_the_table(self):
        for word in ("신용카드", "신용 카드", "신용  카드", "신용-카드", "신용카드!", "(신용카드)"):
            with self.subTest(word=word):
                self.assertEqual(related(word, 11), ["연말정산 준비"])

    def test_season_fit_itself_splits_words_at_marks_and_commas_not_only_related_items(self):
        # 보관함 후보 평가(`assess`)는 `season_fit` 을 쓰므로 '신용카드, 체크카드 비교' 같은 제목의 쉼표·괄호 처리를 `season_fit` 이 직접 지켜야 한다(독립 검증이 찾은 시험 구멍).
        for sentence in ("(신용카드)", "신용카드, 체크카드", "[신용카드]", "신용카드!", "‘신용카드’", "신용-카드", "신용카드,체크카드", "비교: 신용카드/체크카드"):
            with self.subTest(sentence=sentence):
                self.assertEqual(sc.season_fit(sentence, 11)[0], sc.SEASON_RELATED)
                self.assertEqual(sc.season_fit(sentence, 11)[1].word, "연말정산 준비")
        for sentence in ("(그래픽카드)", "그래픽카드, 사운드카드", "[카드뮴]"):
            with self.subTest(sentence=sentence):
                self.assertEqual(sc.season_fit(sentence, 11), (sc.SEASON_NEUTRAL, None))

    def test_a_particle_after_letters_that_are_not_a_table_word_does_not_rescue_the_word(self):
        # 조사를 뗀 뒤 앞머리가 표의 낱말이면 이어진다고 읽으면 '세금액을'·'아이폰을' 이 걸린다 — 조사는 표의 낱말 바로 뒤에서만 센다(독립 검증이 찾은 시험 구멍).
        for word, month in (("아이폰을", 12), ("카드뮴은", 11), ("세금액을", 11), ("부가세금액을", 11), ("그래픽카드를", 11), ("유튜브를", 7), ("매트리스를", 12), ("운동화는", 1), ("전기차에서는", 11), ("마스크팩으로는", 11)):
            with self.subTest(word=word, month=month):
                self.assertEqual(related(word, month), [])
                self.assertEqual(sc.season_fit(word, month), (sc.SEASON_NEUTRAL, None))
        self.assertTrue(legacy_related("아이폰을", 12), "옛 규칙이면 걸렸을 낱말이어야 한다")

    def test_a_plural_or_other_ending_that_is_not_in_the_particle_list_is_not_read_as_a_particle(self):
        # 복수 '들'·'나는' 은 일부러 허용 목록에 넣지 않았다 — '세금들'·'김장들' 은 이어지지 않는다('아이들' 은 사전에 적은 복합어라 이어진다). 몰래 '들' 을 허용하면 이 시험이 깨진다.
        for word in ("세금들", "김장들", "카드값들", "신용카드들", "세금들을", "세금나는", "신용카드나는"):
            with self.subTest(word=word):
                self.assertEqual(related(word, 11), [])
        self.assertEqual(related("아이들", 12), ["크리스마스", "겨울방학"])

    def test_the_longer_particles_the_stemmer_also_strips_connect_like_the_short_ones(self):
        # 시기 낱말 통째 일치('김장에도' = 100)와 같은 글을 같게 읽는다 — 한 문장 안에서 100점 낱말은 받고 70점 낱말은 못 받는 어긋남이 없다(독립 검증 L1).
        self.assertEqual(sc.season_fit("김장에도", 11)[0], sc.SEASON_MATCH)
        for word in ("세금에도", "세금에는", "신용카드에는", "신용카드에서는", "신용카드에서도", "카드값으로는", "체크카드에게", "카드값마다", "카드값한테", "세금보다", "세금이라", "세금이며", "세금이란", "세금라도", "세금랑", "세금으로는"):
            with self.subTest(word=word):
                self.assertEqual(related(word, 11), ["연말정산 준비"])
                self.assertEqual(fit(word, 11), sc.SEASON_RELATED)
        self.assertEqual(related("보일러에는", 11), ["난방"])

    def test_a_one_letter_word_never_connects_even_with_a_particle(self):
        for word in ("눈", "눈이", "차", "차를", "집", "집에", "돈"):
            for month in range(1, 13):
                with self.subTest(word=word, month=month):
                    self.assertEqual(related(word, month), [])


class SubstringNoLongerMatchesTest(unittest.TestCase):
    # 오탐 제거 — 옛 규칙(부분 문자열 양쪽)이면 걸렸을 낱말만 모았다(`legacy_related` 로 그것을 먼저 확인한다). 그림자 낱말은 월 표의 이어지는 낱말('아이'·'전기'·'운동'·'선물'·'정리'·'마스크'·'튜브'·'수도'·'이사'·'모자'·'트리'·'사업' …)이다.
    FALSE_POSITIVES = (("아이폰", 12), ("아이패드", 7), ("아이디어", 3), ("전기차", 11), ("전기자전거", 11), ("운동화", 1), ("운동장", 5), ("선물옵션", 12), ("정리해고", 12), ("마스크팩", 11), ("유튜브", 7),
                       ("수도권", 12), ("이사회", 3), ("이사님", 3), ("모자이크", 5), ("매트리스", 12), ("이사업체", 4), ("정전기", 12), ("건조기", 11), ("가습기", 6), ("부가세금액", 11))

    def test_every_listed_word_was_connected_by_the_old_rule_and_is_not_by_the_new_one(self):
        for word, month in self.FALSE_POSITIVES:
            with self.subTest(word=word, month=month):
                self.assertTrue(legacy_related(word, month), "옛 규칙이면 걸렸을 낱말이어야 한다")
                self.assertEqual(related(word, month), [])
                self.assertEqual(sc.season_fit(word, month), (sc.SEASON_NEUTRAL, None))

    def test_a_word_inside_a_longer_table_word_does_not_connect_the_other_way_round_either(self):
        # 글의 낱말이 표의 낱말 속에 든 경우('의료' ⊂ '의료비'·'직장' ⊂ '직장인'·'학교' ⊂ '초등학교') — 표의 낱말 통째로 쓰면 이어지고 일부만 쓰면 안 이어진다.
        for short, whole, month in (("의료", "의료비", 11), ("직장", "직장인", 11), ("준비", "준비물", 3), ("생활", "생활습관", 8)):
            with self.subTest(short=short, whole=whole):
                self.assertTrue(legacy_related(short, month), "옛 규칙이면 걸렸을 낱말이어야 한다")
                self.assertEqual(related(short, month), [])
                self.assertTrue(related(whole, month), "표에 적힌 낱말 통째로는 그대로 이어진다")

    def test_a_travel_word_no_longer_connects_to_the_wedding_item_through_honeymoon(self):
        # 5월 '결혼식' 항목의 이어지는 낱말 '신혼여행' 이 낱말 '여행' 을 품었다는 이유만으로 평범한 '여행' 이 결혼식과 이어지던 것이 사라졌다. 다른 여행 항목(가정의 달·캠핑·연휴)은 그대로다.
        self.assertIn("결혼식", legacy_related("여행", 5))
        self.assertEqual(related("여행", 5), ["가정의 달", "캠핑", "연휴"])
        self.assertEqual(related("신혼여행", 5), ["가정의 달", "캠핑", "연휴", "결혼식"], "표에 적힌 '신혼여행' 통째로는 결혼식과 이어진다")

    def test_a_generic_word_alone_no_longer_connects_through_a_longer_related_word(self):
        # '준비' 는 흔한 말이라 시기 낱말('입학 준비' 등)에서도 뺐는데(GENERIC_WORD_STEMS) 이어지는 낱말 '준비물' 속에 들어 있다는 이유로 이어지던 것도 사라졌다.
        for month in (2, 3, 8, 10, 11):
            with self.subTest(month=month):
                self.assertTrue(legacy_related("준비", month))
                self.assertEqual(related("준비", month), [])
                self.assertEqual(related("테스트 준비", month), [])
        self.assertEqual(related("준비물", 3), ["새 학기"], "표에 적힌 낱말 통째로는 그대로")


class CompoundsAndKeptMatchesTest(unittest.TestCase):
    # 정당했던 일치(옛 규칙이 걸었고 뜻도 맞는 붙여 쓴 복합어) — 표의 낱말에 이어지는 복합어로 `RELATED_COMPOUNDS` 에 적었다.
    KEPT = (("소형가전", 11, ["쇼핑 행사"]), ("소형가전", 6, ["에어컨"]), ("제습기", 6, ["장마", "제습", "에어컨"]), ("제습기", 7, ["장마"]), ("해외여행", 1, ["겨울 여행"]), ("겨울철", 11, ["월동 준비", "겨울 타이어"]),
            ("난방비", 11, ["난방", "월동 준비"]), ("김장철", 11, ["김장"]), ("장마철", 6, ["장마"]), ("휴가철", 7, ["여름 휴가"]), ("독감예방접종", 11, ["독감"]), ("초등학교", 3, ["새 학기"]),
            ("연금저축", 11, ["연말정산 준비"]), ("크리스마스카드", 12, ["크리스마스"]), ("청소기", 3, ["미세먼지", "황사", "봄맞이 대청소", "이사"]), ("이불빨래", 6, ["장마", "제습", "여름 침구"]),
            ("가계부앱", 1, ["가계부"]), ("전기요금", 11, ["난방"]), ("가스비", 11, ["난방"]), ("비타민C", 11, ["독감"]), ("아이들", 7, ["여름방학", "물놀이"]), ("봉사활동", 12, ["겨울방학"]),
            ("캠핑장", 5, ["캠핑", "연휴"]), ("이사업체", 2, ["이사"]), ("자동차보험", 7, ["자동차 점검"]), ("에어컨청소", 8, ["폭염", "열대야", "에어컨 청소", "전기요금"]),
            # 수정 2차(독립 검증 M1) — 핵심어 + 흔한 뒤꼬리 아홉: 차례상·귀성길(설 명절)·예식장(결혼식)·스키장(겨울 여행)·이삿짐센터(이사)·졸업사진(졸업)·방충망(모기)·세무사(부가세)·급여명세서(연말정산)
            ("차례상", 1, ["설 명절"]), ("차례상", 2, ["설 명절"]), ("차례상", 9, ["추석 명절"]), ("귀성길", 1, ["설 명절"]), ("귀성길", 10, ["추석 명절"]), ("예식장", 5, ["결혼식"]), ("예식장", 9, ["결혼식"]),
            ("스키장", 1, ["겨울 여행"]), ("스키장", 12, ["겨울 여행"]), ("이삿짐센터", 8, ["이사 준비"]), ("이삿짐센터", 3, ["이사"]), ("졸업사진", 2, ["졸업"]), ("방충망", 6, ["모기"]), ("방충망", 7, ["모기"]),
            ("세무사", 4, ["종합소득세 준비"]), ("세무사", 6, ["부가세 준비"]), ("세무사", 7, ["부가세"]), ("급여명세서", 1, ["연말정산"]), ("급여명세서", 11, ["연말정산 준비"]), ("급여명세서", 12, ["연말정산"]))

    def test_the_kept_compounds_connect_to_the_items_the_old_rule_connected_them_to_when_they_fit(self):
        for word, month, items in self.KEPT:
            with self.subTest(word=word, month=month):
                self.assertEqual(related(word, month), items)
                self.assertEqual(fit(word, month), sc.SEASON_RELATED)

    def test_profile_a_seeds_keep_their_seasonal_matches_and_a_graphics_card_profile_gets_none(self):
        # 프로필 A(소형가전·제습기·숙박·여행·PC 주변기기·가전·가성비)의 6월·11월 시기 이어짐이 그대로다.
        self.assertEqual(related("가전", 11), ["쇼핑 행사"])
        self.assertEqual(related("여행", 11), ["늦가을 여행"])
        self.assertEqual(related("여행", 6), ["여름 휴가 준비"])
        for word in ("숙박", "PC 주변기기", "가성비", "AI 서비스", "PC 부품", "업무 자동화", "그래픽카드"):
            for month in (6, 11):
                with self.subTest(word=word, month=month):
                    self.assertEqual(related(word, month), [])

    def test_every_compound_belongs_to_a_table_word_and_contains_it_as_one_plain_word(self):
        known = {word for items in data.SEASONS.values() for item in items for word in table_words(item)}
        for base, compounds in data.RELATED_COMPOUNDS.items():
            with self.subTest(base=base):
                self.assertIn(base, known, "복합어 사전의 열쇠는 월 표의 낱말이어야 한다(안 쓰이는 줄이 쌓이지 않게)")
                self.assertGreaterEqual(len(base), tx.MIN_STEM)
                self.assertEqual(len(set(compounds)), len(compounds))
                for compound in compounds:
                    self.assertEqual(tx.words(compound), [compound.casefold()], f"{compound}: 띄어쓰기·기호 없는 한 낱말이어야 한다")
                    self.assertIn(base, compound, f"{compound} 는 {base} 를 담은 복합어여야 한다")
                    self.assertGreater(len(compound), len(base))

    def test_the_whole_dictionary_is_pinned_line_by_line_so_no_compound_can_disappear_or_change_silently(self):
        # 독립 검증 M2: 예전에는 24줄만 값이 못박혀 나머지 116줄을 지워도 시험이 통과했다. 이제 사전 전체(낱말 86개·복합어 149개)를 값까지 `EXPECTED_COMPOUNDS` 와 견준다.
        self.assertEqual(data.RELATED_COMPOUNDS, EXPECTED_COMPOUNDS)
        self.assertEqual((len(data.RELATED_COMPOUNDS), len({compound for compounds in data.RELATED_COMPOUNDS.values() for compound in compounds})), (86, 149))
        for base, compounds in EXPECTED_COMPOUNDS.items():
            self.assertEqual(tuple(data.RELATED_COMPOUNDS[base]), tuple(compounds), f"{base}: 복합어의 차례까지 같아야 한다")

    def test_a_compound_connects_to_every_item_of_every_month_that_lists_its_base_word(self):
        checked = 0
        for month, items in data.SEASONS.items():
            for item in items:
                for base in table_words(item):
                    for compound in data.RELATED_COMPOUNDS.get(base, ()):
                        checked += 1
                        with self.subTest(month=month, item=item.word, base=base, compound=compound):
                            self.assertIn(item.word, related(compound, month))
        self.assertGreater(checked, 900)

    def test_a_compound_that_the_table_does_not_list_is_not_connected_by_design(self):
        # 붙여 쓴 복합어는 표(와 복합어 사전)에 적힌 것만 이어진다 — 빠진 말은 사전에 한 줄 더하면 된다(D-42). '미니가전'·'추가세금' 은 일부러 적지 않은 예다.
        for word, month in (("미니가전", 11), ("추가세금", 11), ("해외직구", 11)):
            with self.subTest(word=word):
                self.assertEqual(related(word, month), [])

    def test_the_bare_word_card_is_not_in_the_table_at_all_and_only_the_finance_phrases_are(self):
        self.assertEqual(data.FINANCE_CARDS, ("신용카드", "체크카드", "직불카드", "선불카드", "법인카드", "신용 카드", "체크 카드", "직불 카드", "선불 카드", "법인 카드", "카드값", "카드혜택", "카드공제", "카드소득공제", "카드 혜택", "카드 공제", "카드 소득공제"))
        self.assertEqual(len(data.FINANCE_CARDS), 17)
        carriers = []
        for month, items in data.SEASONS.items():
            for item in items:
                self.assertNotIn("카드", item.related, f"{month}월 {item.word}")
                self.assertNotIn("카드", item.word)
                if set(data.FINANCE_CARDS) & set(item.related):
                    carriers.append((month, item.word))
                    self.assertTrue(set(data.FINANCE_CARDS) <= set(item.related), f"{month}월 {item.word}: 금융 카드 구문은 한 벌로 넣는다")
        self.assertEqual(carriers, [(1, "연말정산"), (1, "가계부"), (2, "연말정산"), (11, "연말정산 준비"), (12, "연말정산")])
        self.assertNotIn("카드", data.RELATED_COMPOUNDS)
        self.assertFalse([word for compounds in data.RELATED_COMPOUNDS.values() for word in compounds if word == "카드"])


class TableWideTest(unittest.TestCase):
    def test_every_related_word_and_phrase_and_season_word_connects_to_its_own_item_alone_and_with_a_particle(self):
        checked = 0
        for month, items in data.SEASONS.items():
            for item in items:
                entries = [*item.related, *sorted(table_words(item))]
                for entry in entries:
                    for tail in ("", "을", "에서"):
                        checked += 1
                        with self.subTest(month=month, item=item.word, entry=entry, tail=tail):
                            self.assertIn(item.word, related(entry + tail, month))
        self.assertGreater(checked, 2000)

    def test_a_season_word_inside_the_text_is_still_a_full_match_and_beats_the_relation(self):
        for month, items in data.SEASONS.items():
            for item in items:
                with self.subTest(month=month, item=item.word):
                    self.assertEqual(fit(f"{item.word} 정리", month), sc.SEASON_MATCH)
                    self.assertEqual(fit(f"올해 {item.word} 글", month), sc.SEASON_MATCH)

    def test_the_table_changes_only_where_the_card_words_were(self):
        # 월 표의 시기 낱말·이유는 P0b 가 건드리지 않았다 — 항목 수는 월마다 10~11개(전체 122개)이고 이어지는 낱말이 바뀐 곳은 금융 카드를 가리키던 다섯 항목뿐이다.
        self.assertEqual({month: len(items) for month, items in data.SEASONS.items()}, {1: 10, 2: 10, 3: 10, 4: 10, 5: 10, 6: 10, 7: 11, 8: 10, 9: 10, 10: 10, 11: 10, 12: 11})
        self.assertEqual(sum(len(items) for items in data.SEASONS.values()), 122)


class GenerateAndScoreTest(unittest.TestCase):
    def seeds(self, topic):
        return sg.extract_seeds(sg.view_of(sp.profile(topic=topic)))[0]

    def test_a_graphics_card_seed_gets_only_the_plain_frames_and_no_season_note(self):
        raws = sg.generate(self.seeds("그래픽카드"), 11)
        self.assertEqual(len(raws), len(PLAIN))
        self.assertTrue(all(item.season is None and item.note is None for item in raws))

    def test_a_credit_card_seed_gets_the_year_end_season_frames_and_a_card_blog_scores_the_relation(self):
        raws = sg.generate(self.seeds("신용카드"), 11)
        self.assertEqual(len(raws), len(PLAIN) + len(SEASONAL))
        self.assertEqual({item.season.word for item in raws if item.season is not None}, {"연말정산 준비"})
        report = sp.run(sp.profile(topic="신용카드"), month=11, count=10)
        self.assertEqual(sorted({part.value for item in report.suggestions for part in item.factors if part.name == "season"}), [70.0, 100.0])

    def test_the_plain_frames_of_a_season_related_seed_score_70_and_of_a_graphics_card_seed_score_50(self):
        for topic, wanted in (("신용카드", 70.0), ("그래픽카드", 50.0), ("보일러", 70.0), ("자전거", 50.0)):
            with self.subTest(topic=topic):
                report = sp.run(sp.profile(topic=topic), month=11, count=50)
                plain = [item for item in report.suggestions if item.frame_id in {frame.frame_id for frame in PLAIN}]
                self.assertTrue(plain)
                self.assertEqual({part.value for item in plain for part in item.factors if part.name == "season"}, {wanted})


class DeterminismAndCacheTest(unittest.TestCase):
    WORDS = ("신용카드", "그래픽카드", "소형가전", "해외여행", "아이폰", "의료비", "세금을", "카드 혜택", "김장철", "제습기", "준비", "")

    def snapshot(self):
        return [(word, month, sc.season_fit(word, month)[0], related(word, month)) for word in self.WORDS for month in range(1, 13)]

    def test_the_same_input_gives_the_same_result_also_after_the_cache_is_cleared(self):
        first = self.snapshot()
        self.assertEqual(self.snapshot(), first)
        sc._CONNECTORS.clear()                                  # 비공개 이름 — 바뀌면 이 시험을 고친다
        self.assertEqual(self.snapshot(), first)

    def test_the_related_items_come_in_the_order_of_the_table(self):
        for word in self.WORDS:
            for month in range(1, 13):
                with self.subTest(word=word, month=month):
                    order = [item.word for item in data.SEASONS[month]]
                    found = related(word, month)
                    self.assertEqual(found, [name for name in order if name in found])

    def test_the_per_item_word_lists_are_built_once_so_a_suggestion_run_does_not_rebuild_them(self):
        sc._CONNECTORS.clear()
        sp.run(sp.profile(topic="소형가전, 제습기, 여행, 그래픽카드"), month=11, count=10)
        built = dict(sc._CONNECTORS)
        self.assertEqual(sorted(item.word for item in built), sorted(item.word for item in data.SEASONS[11]), "그 달의 항목마다 한 번씩 만들었다")
        sp.run(sp.profile(topic="소형가전, 제습기, 여행, 그래픽카드"), month=11, count=10)
        self.assertEqual(len(sc._CONNECTORS), len(built))
        for item, found in built.items():
            self.assertIs(sc._CONNECTORS[item], found, "같은 달의 항목 목록은 다시 만들지 않는다")


class KnownLimitTest(unittest.TestCase):
    # 알려 둔 한계(P0b) — 이름에 KNOWN_LIMIT 를 달았다. 규칙이 바뀌면(복합어 규칙을 넓히는 등) 새 결정을 쓰고 이 시험을 의식적으로 고친다.
    def test_KNOWN_LIMIT_a_spaced_graphics_card_followed_by_benefit_still_matches_the_card_benefit_phrase(self):
        # '그래픽 카드 혜택' 처럼 띄어 쓴 '카드' 가 '혜택' 과 나란히 오면 구문 '카드 혜택' 이 맞는다 — 낱말만 보고 앞의 '그래픽' 은 보지 않는다. 붙여 쓴 '그래픽카드 혜택' 은 안 걸린다.
        self.assertEqual(related("그래픽 카드 혜택", 11), ["연말정산 준비"])
        self.assertEqual(related("그래픽카드 혜택", 11), [])

    def test_KNOWN_LIMIT_a_spaced_card_bill_is_not_connected_but_the_joined_one_is(self):
        # '카드 값' 처럼 띄어 쓰면 이어지지 않는다 — 구문으로 적으면 '그래픽 카드 값' 도 걸려서 일부러 적지 않았다(붙여 쓴 '카드값' 만 적었다).
        self.assertEqual(related("카드 값", 11), [])
        self.assertEqual(related("카드값", 11), ["연말정산 준비"])

    def test_KNOWN_LIMIT_a_particle_like_ending_of_another_word_is_read_as_the_particle(self):
        # '목표가'(목표 + 가) 처럼 낱말 끝이 조사와 같은 글자이면 조사로 읽는다 — 조사 허용 목록의 한계이고 옛 낱말 처리(`stem`)도 같다.
        self.assertEqual(related("목표가", 1), ["새해 계획"])


if __name__ == "__main__":
    unittest.main()
