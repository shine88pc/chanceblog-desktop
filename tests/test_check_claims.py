"""'지어내지 않기' 검사(`check/claims.py`) 시험 — 한국어 낱말 규칙의 오탐·미탐이 현실적이므로 걸리는 예문(위반 100개 이상·확인 권장 25개 이상)과 지나가는 예문(100개 이상)을 목록으로 고정한다(독립 검증자의 예문 187개는 `test_check_claims_regression.py`).

지키는 것:
  1) 경험을 단정하는 말(직접 사용·방문·구매·수익·체감·실제 대화나 댓글·실제 사례)은 위반으로 걸리고, 그 분류가 맞다.
  2) 아직 하지 않은 일을 안내하는 말(방문 전에 확인하는 것이 좋습니다·사용해 보세요·구매했다면 …)과 경험을 지어내지 말라는 말은 지나간다.
  3) 가격·날짜·시각·통계는 '확인 권장' 이고 위반이 아니다(막지 않는다).
  4) 경험을 입력했을 때는 사용자 문장만 위반에서 빠지고 그 밖의 문장은 그대로 걸린다. 입력하지 않았으면 어디에 있든 위반이다.
  5) 띄어쓰기를 바꿔도 같은 결과이고, 같은 입력은 같은 결과(결정적)이며, 아주 긴 글(수십만 자)도 1초 안에 끝난다(정규식이 선형 시간).
  6) 글이 아닌 입력은 CONTENT_INVALID 로 거절한다.
네트워크·파일 없이 돈다.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.check import claims as cl  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402

USE, VISIT, BUY, INCOME, EFFECT, DIALOGUE, CASE = cl.EXPERIENCE_USE, cl.EXPERIENCE_VISIT, cl.EXPERIENCE_BUY, cl.EXPERIENCE_INCOME, cl.EXPERIENCE_EFFECT, cl.DIALOGUE, cl.CASE
PRICE, DATE, TIME, STAT = cl.PRICE, cl.DATE, cl.TIME, cl.STAT

# 위반 — (문장, 걸려야 하는 분류). 한 문장이 여러 분류에 걸릴 수 있어 '그 분류가 들어 있다' 를 본다.
VIOLATING = (
    # 직접 사용·체험
    ("직접 사용해보니 편리했습니다.", USE), ("한 달 동안 써봤는데 생각보다 가볍습니다.", USE), ("이 앱을 사용해 본 결과 속도가 빨랐습니다.", USE), ("저는 이 제품을 매일 사용했습니다.", USE),
    ("설치해 보니 별다른 설정 없이 바로 실행됐습니다.", USE), ("먹어 보니 생각보다 달지 않았습니다.", USE), ("입어 보니 사이즈가 넉넉했습니다.", USE), ("직접 써본 내용을 정리했습니다.", USE),
    ("세 달째 사용 중인 제품입니다.", USE), ("제가 직접 테스트해봤습니다.", USE), ("실제로 설치했는데 오류는 없었습니다.", USE), ("몇 번 타 보니 금방 익숙해졌습니다.", USE),
    ("노트북에 깔아 보니 용량이 크지 않았습니다.", USE), ("일주일간 착용했더니 자국이 남지 않았습니다.", USE), ("써 보았더니 생각보다 오래 갔습니다.", USE), ("체험해 보니 설명서와 똑같이 작동했습니다.", USE),
    ("직접 이용해본 결과를 공유합니다.", USE), ("우리는 이 방법을 두 해 동안 사용했습니다.", USE), ("저희는 이 도구를 매일 써왔습니다.", USE), ("마셔 보니 향이 진했습니다.", USE),
    ("사용해 봤는데 소음이 거의 없었습니다.", USE), ("직접 먹어본 메뉴만 소개합니다.", USE), ("열어 보니 부품이 모두 들어 있었습니다.", USE), ("돌려 보니 결과가 금방 나왔습니다.", USE),
    ("제가 직접 써서 확인한 내용입니다.", USE), ("만들어 보니 재료가 생각보다 적게 들었습니다.", USE), ("두 주 동안 이용했는데 불편한 점은 없었습니다.", USE), ("복용해 보니 속이 편했습니다.", USE),
    ("한 달간 사용해왔고 큰 문제는 없었습니다.", USE),
    # 직접 방문
    ("방문했을 때 대기 줄이 길지 않았습니다.", VISIT), ("지난주에 다녀왔습니다.", VISIT), ("가 보니 대기 줄이 길지 않았습니다.", VISIT), ("직접 방문했는데 직원분이 친절했습니다.", VISIT),
    ("근처를 지나다가 들렀습니다.", VISIT), ("찾아가 보니 입구가 눈에 잘 띄었습니다.", VISIT), ("다녀온 후기를 남깁니다.", VISIT), ("주말에 방문했더니 사람이 많았습니다.", VISIT),
    ("점심시간에 갔을 때 자리가 넉넉했습니다.", VISIT), ("제가 다녀온 곳은 역에서 가까웠습니다.", VISIT), ("찾아갔을 때 문이 닫혀 있었습니다.", VISIT), ("직접 가 봤는데 생각보다 좁았습니다.", VISIT),
    ("방문해 보았습니다.", VISIT), ("들러 보니 메뉴판이 따로 없었습니다.", VISIT), ("지난달에 방문했습니다.", VISIT), ("다녀와 보니 생각보다 가까웠습니다.", VISIT),
    ("직접 찾아갔더니 간판이 바뀌어 있었습니다.", VISIT), ("방문했는데 예약이 필요했습니다.", VISIT), ("가봤더니 문이 열려 있었습니다.", VISIT),
    ("직접 다녀 봤는데 입구가 좁았습니다.", VISIT), ("직접 다녀와서 확인한 내용을 적었습니다.", VISIT),
    # 구매
    ("이 제품을 구매했습니다.", BUY), ("온라인에서 주문했는데 사흘 만에 도착했습니다.", BUY), ("할인할 때 샀습니다.", BUY), ("가격이 올라서 구입했어요.", BUY), ("직접 결제했습니다.", BUY),
    ("택배로 받았습니다.", BUY), ("내돈내산으로 정리합니다.", BUY), ("두 개 질렀습니다.", BUY), ("구매해 보니 포장이 단단했습니다.", BUY), ("배송받았는데 상자가 찌그러져 있었습니다.", BUY),
    ("지난달에 구입해 봤습니다.", BUY), ("구매했을 때 영수증을 같이 받았습니다.", BUY), ("한 번 사 봤습니다.", BUY), ("주문해서 받았습니다.", BUY), ("매장에서 바로 샀는데 후회는 없습니다.", BUY),
    # 수익
    ("이 방법으로 수익을 냈습니다.", INCOME), ("한 달 만에 수익이 났습니다.", INCOME), ("광고로 돈을 벌었습니다.", INCOME), ("첫 달부터 수익을 올렸습니다.", INCOME), ("수익 인증을 해 봅니다.", INCOME),
    ("애드센스로 정산받았습니다.", INCOME), ("블로그로 용돈을 벌었어요.", INCOME), ("수익이 생겼습니다.", INCOME), ("체험단으로 수익을 얻었습니다.", INCOME), ("수익화에 성공했습니다.", INCOME),
    # 효과·느낌
    ("효과를 봤습니다.", EFFECT), ("차이를 체감했습니다.", EFFECT), ("확실히 달라졌습니다.", EFFECT), ("써 본 후 피부가 좋아졌습니다.", EFFECT), ("만족스러웠습니다.", EFFECT), ("가격 대비 아쉬웠습니다.", EFFECT),
    ("소음이 조용했습니다.", EFFECT), ("정말 놀랐습니다.", EFFECT), ("바로 효과를 느꼈습니다.", EFFECT), ("살이 빠졌습니다.", EFFECT), ("눈에 띄게 좋아졌습니다.", EFFECT), ("생각보다 저렴했습니다.", EFFECT),
    ("서비스가 훌륭했습니다.", EFFECT), ("맛있었습니다.", EFFECT), ("사용 후 통증이 나아졌습니다.", EFFECT), ("기대보다 실망했습니다.", EFFECT), ("차이가 느껴졌습니다.", EFFECT),
    ("체감할 수 있었습니다.", EFFECT), ("깔끔했습니다.", EFFECT), ("느꼈다.", EFFECT), ("화면이 선명해서 편리했습니다.", EFFECT),
    # 실제 대화·댓글
    ("댓글로 질문을 남겨 주셨습니다.", DIALOGUE), ("이웃님이 댓글로 물어보셨는데요.", DIALOGUE), ("전화해 보니 재고가 없다고 했습니다.", DIALOGUE), ("직원분이 말씀하시길 이 메뉴가 가장 인기라고 합니다.", DIALOGUE),
    ("친구가 말하길 괜찮다고 했습니다.", DIALOGUE), ("사장님께서 말씀해 주셨습니다.", DIALOGUE), ("문의했더니 곧바로 답변이 왔습니다.", DIALOGUE), ("고객센터에 문의했더니 교환이 가능하다고 안내받았습니다.", DIALOGUE),
    ("지인에게 들었는데 꽤 쓸 만하다고 합니다.", DIALOGUE), ("괜찮다고 하더라고요.", DIALOGUE), ("써 보니 좋더라고요.", DIALOGUE), ("상담받았을 때 이런 설명을 들었습니다.", DIALOGUE),
    ("카톡으로 물어보니 바로 답이 왔습니다.", DIALOGUE), ("괜찮다고 말씀하셨습니다.", DIALOGUE), ("통화했을 때 직원이 알려 준 내용입니다.", DIALOGUE),
    # 실제 사례
    ("실제 사례를 하나 소개합니다.", CASE), ("한 고객은 이렇게 말했습니다.", CASE), ("제 지인은 이 방법으로 해결했습니다.", CASE), ("A씨는 이 방법을 따랐습니다.", CASE), ("김씨는 비슷한 문제를 겪었습니다.", CASE),
    ("어떤 분은 이렇게 해결했다고 합니다.", CASE), ("한 직장인은 퇴근 후 이 방법을 썼습니다.", CASE), ("제 친구도 같은 증상이 있었습니다.", CASE), ("실제로 있었던 일입니다.", CASE),
    ("한 주부는 이렇게 절약했습니다.", CASE),
)

# 확인 권장 — (문장, 분류). 위반이 아니다.
REVIEWING = (
    ("가격은 약 3만 원입니다.", PRICE), ("월 9,900원입니다.", PRICE), ("정가는 12,000원입니다.", PRICE), ("29$ 에 판매합니다.", PRICE), ("₩5000 부터 시작합니다.", PRICE), ("십만 원대입니다.", PRICE),
    ("5천 원 정도입니다.", PRICE), ("2만 5천 원입니다.", PRICE), ("삼만 원에 팝니다.", PRICE), ("1만원대 제품입니다.", PRICE), ("약 3만 원", PRICE),
    ("2026년 11월 3일에 출시됩니다.", DATE), ("11월 3일부터 시작합니다.", DATE), ("2026-11-03 기준입니다.", DATE), ("2026.11.03 에 바뀌었습니다.", DATE), ("2025년에 개정됐습니다.", DATE),
    ("오전 9시부터 영업합니다.", TIME), ("9시부터 18시까지 운영합니다.", TIME), ("약 30분 소요됩니다.", TIME), ("24시간 운영합니다.", TIME), ("10:30 에 시작합니다.", TIME), ("2시간 정도 걸립니다.", TIME),
    ("사용자의 70%가 선택합니다.", STAT), ("30퍼센트 늘었습니다.", STAT), ("통계에 따르면 늘고 있습니다.", STAT), ("조사 결과 절반이 선택했습니다.", STAT), ("10명 중 7명이 고릅니다.", STAT),
    ("응답자 대부분이 같은 답을 했습니다.", STAT), ("연구에 따르면 차이가 있습니다.", STAT),
)

# 지나가는 글 — 아무것도 걸리지 않는다(위반도 확인 권장도). 안내·조건·부정·경험을 지어내지 말라는 말·일반 설명.
PASSING = (
    "주요 기능은 다음과 같이 정리할 수 있습니다.", "방문하기 전에 공식 안내로 주차할 수 있는지 살펴보면 좋습니다.", "구매 전에 환불 조건을 확인합니다.", "사용해 보면 차이를 알 수 있습니다.",
    "직접 확인해 보시기 바랍니다.", "직접 방문하여 확인하시기 바랍니다.", "써 보시고 마음에 들면 계속 쓰세요.", "구매했다면 영수증을 보관하세요.", "사용해 본 적이 없다면 먼저 체험판을 살펴보세요.",
    "써 본 것처럼 쓰지 않습니다.", "경험하지 않은 일을 경험한 것처럼 쓰지 않습니다.", "직접 겪은 일이 아니면 겪은 것처럼 적지 않습니다.", "써 본 적이 있다면 그 내용을 따로 단락으로 적어 둘 수 있습니다.",
    "가격은 공식 홈페이지에서 확인하세요.", "영업 시간은 매장 안내문에서 확인해 주세요.", "이 글은 공개된 자료를 바탕으로 정리했습니다.", "제품 정보를 정리하고 선택 기준을 소개합니다.",
    "독자가 궁금해할 질문을 먼저 정리합니다.", "핵심 개념을 쉬운 말로 설명합니다.", "확인할 기준을 항목으로 나누어 보여 줍니다.", "장점과 제한을 함께 적어 균형을 맞춥니다.",
    "상황별로 어떤 선택이 맞는지 안내합니다.", "마지막에는 과장 없이 핵심만 다시 정리합니다.", "주차 가능 여부는 방문 전에 확인합니다.", "구매하기 전에 후기를 여러 곳에서 비교해 보세요.",
    "예약이 필요한지 미리 알아보는 것이 좋습니다.", "처음 설치할 때는 공식 설명서를 먼저 읽습니다.", "무료 체험이 있는지 확인해 봅니다.", "직접 사용해 보고 결정하는 것이 가장 정확합니다.",
    "사용해 보는 과정에서 문제가 생기면 고객센터에 문의합니다.", "설정 방법은 제품 설명서에 나와 있습니다.", "비교할 때는 같은 기준을 모든 대상에 적용합니다.",
    "방문하는 날의 날씨와 교통 상황도 함께 살펴봅니다.", "이용 방법은 다음 순서로 안내합니다.", "먼저 문제가 나타나는 조건을 정리합니다.", "원인을 단정하지 않고 확인 순서로 안내합니다.",
    "같은 문제가 반복되면 전문가에게 문의하는 것이 안전합니다.", "공식 안내가 바뀔 수 있으니 작성일을 함께 적습니다.", "제목에는 핵심 키워드를 자연스럽게 넣습니다.",
    "보조 키워드는 소제목과 본문에 나누어 씁니다.", "문단은 짧게 나누어 읽기 쉽게 합니다.", "예시는 가상의 상황임을 밝히고 실제 사례처럼 쓰지 않습니다.",
    "광고처럼 읽히지 않도록 장점과 제한을 함께 적습니다.", "결과를 장담하거나 과장하는 표현은 쓰지 않습니다.", "확인하지 않은 수치는 적지 않습니다.", "댓글로 질문을 남겨 주세요.",
    "궁금한 점은 공식 고객센터에 문의해 보세요.", "이웃님의 의견도 환영합니다.", "지인에게 추천할 때는 사용 목적을 먼저 묻습니다.", "친구와 함께 갈 때는 미리 예약합니다.",
    "가기 전에 영업일을 확인합니다.", "근처에 들를 때는 대기 시간을 확인하세요.", "구매 후에는 영수증과 보증서를 보관합니다.", "사용 후에는 부품을 깨끗이 닦아 말립니다.",
    "사용 후 이상이 느껴지면 즉시 중단하고 전문가와 상담합니다.", "효과는 사람마다 다를 수 있습니다.", "수익은 상황에 따라 달라질 수 있습니다.", "수익을 약속하는 표현은 쓰지 않습니다.",
    "방문하기 전에 지도 앱으로 위치를 확인합니다.", "가격 비교는 같은 조건에서 합니다.", "두 제품의 차이를 표로 정리합니다.", "장소 정보는 공식 안내를 기준으로 적습니다.",
    "이용 전에 확인할 사항을 먼저 알려 드립니다.", "주차 공간이 있는지는 공식 안내에서 확인하는 것이 좋습니다.", "메뉴와 시설은 바뀔 수 있으므로 방문 전 확인을 권합니다.",
    "방문 목적에 따라 적합한 곳이 달라질 수 있습니다.", "처음 접하는 독자가 이해하기 쉽도록 용어를 풀어 씁니다.", "일반적인 상황을 가정해 설명합니다.", "다음 글에서는 관련 주제를 더 다룹니다.",
    "결론은 한두 문장으로 정리합니다.", "체크리스트로 마무리하면 다시 확인하기 좋습니다.", "도움이 되는 자료의 주소를 함께 적습니다.", "출처가 분명한 자료만 인용합니다.",
    "인용할 때는 출처를 밝히고 글의 흐름에 맞게 줄입니다.", "사진은 직접 찍은 것만 사용합니다.", "직접 확인한 내용만 적습니다.", "확인하지 못한 내용은 적지 않습니다.",
    "이 글은 개인 의견을 포함합니다.", "제품 비교는 공개된 사양을 기준으로 합니다.", "사양은 제조사 공식 자료에서 확인합니다.", "환불 규정은 구매처마다 다를 수 있습니다.",
    "배송 기간은 판매처 안내를 따릅니다.", "설치할 때는 전원을 먼저 끕니다.", "문제가 생기면 전원을 끄고 연결 상태를 확인합니다.", "먼저 가장 쉬운 방법부터 시도합니다.",
    "해결이 되지 않으면 다음 방법으로 넘어갑니다.", "재발을 막으려면 정기적으로 점검합니다.", "점검 주기는 제품 설명서를 따릅니다.", "같은 증상이 계속되면 서비스 센터를 찾습니다.",
    "소제목은 세 개에서 다섯 개로 나눕니다.", "제목은 핵심 키워드로 시작하는 것이 좋습니다.", "태그는 글의 주제와 직접 관련된 낱말로 고릅니다.", "카테고리는 블로그 설정에 맞춰 고릅니다.",
    "초안을 읽고 필요한 부분만 고쳐서 올립니다.", "글 길이는 목표 범위 안에서 조절합니다.", "글을 올리기 전에 맞춤법을 한 번 더 살핍니다.", "저작권이 있는 글과 사진은 허락 없이 가져오지 않습니다.",
    "광고나 협찬이 있다면 글 첫머리에 밝힙니다.", "협찬을 받은 경우에는 그 사실을 분명히 적습니다.", "구독 중인 서비스라면 해지 방법도 함께 확인합니다.", "이용 중인 서비스가 있다면 약관을 다시 읽어 봅니다.",
    "사용 중인 제품의 모델명을 확인합니다.", "한 달에 한 번 점검하면 충분합니다.", "일주일 동안 사용할 수 있는 무료 체험이 있습니다.", "한 달 동안 환불이 가능한지 확인합니다.",
    "세 달 동안 무료로 이용할 수 있습니다.", "사용자의 후기를 읽을 때는 광고 표시가 있는지 살핍니다.", "후기가 많다고 해서 품질이 좋다고 단정하지 않습니다.",
    "비교 대상은 같은 시기의 제품으로 맞춥니다.", "가격 변동은 판매처에서 직접 확인합니다.", "직접 사용한 경험이 있다면 그 내용을 따로 적어 주세요.", "방문했다면 영수증을 보관합니다.", "방문했을 때 확인했다면 영수증을 보관하세요.", "제품을 구매했을 때는 영수증과 보증서를 보관하세요.", "구매했을 경우 교환 조건을 먼저 확인합니다.", "주문했는지 헷갈리면 주문 내역에서 확인합니다.", "방문했을 때 확인할 항목은 다음과 같습니다.",
    "구매했는지 여부는 주문 내역에서 확인합니다.", "후기를 쓰는 방법은 다음 순서를 따릅니다.", "고객 사례는 허락을 받은 경우에만 소개합니다.", "대화 내용을 옮길 때는 상대의 동의를 먼저 구합니다.",
    "댓글에는 개인정보를 적지 않도록 안내합니다.", "수익을 공개할 때는 증빙 자료가 있어야 합니다.", "먼저 공식 문서의 설치 항목을 읽어 봅니다.", "방문 후기를 쓸 때는 직접 다녀온 경우에만 적습니다.",
    "이 프로그램을 직접 사용한 사람은 많지 않습니다.", "여기에 직접 다녀온 사람들이 많다고 합니다.",
)


class ClassificationTest(unittest.TestCase):
    def test_the_lists_are_big_enough_to_pin_the_rules(self):
        self.assertGreaterEqual(len(VIOLATING), 100)
        self.assertGreaterEqual(len(PASSING), 100)
        self.assertGreaterEqual(len(REVIEWING), 25)
        self.assertEqual(len(set(PASSING)), len(PASSING), "중복된 예문")
        self.assertEqual(len({text for text, _ in VIOLATING}), len(VIOLATING), "중복된 예문")

    def test_every_violating_sentence_is_found_and_classified(self):
        misses = []
        for text, category in VIOLATING:
            found = {claim.category for claim in cl.find_claims(text)}
            if category not in found:
                misses.append((text, category, sorted(found)))
        self.assertEqual(misses, [])

    def test_every_violating_sentence_has_at_least_one_violation(self):
        for text, _category in VIOLATING:
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))

    def test_every_passing_sentence_finds_nothing(self):
        noisy = [(text, cl.find_claims(text)) for text in PASSING if cl.find_claims(text)]
        self.assertEqual(noisy, [])

    def test_review_sentences_are_reviews_and_never_violations(self):
        for text, category in REVIEWING:
            with self.subTest(text=text):
                found = cl.find_claims(text)
                self.assertIn(category, {claim.category for claim in found})
                self.assertEqual(cl.find_violations(text), ())
                self.assertTrue(all(not cl.is_violation(claim.category) for claim in found))

    def test_the_examples_in_the_task_brief(self):
        self.assertTrue(cl.find_violations("직접 사용해보니 편리했습니다."))
        self.assertEqual(cl.find_claims("주요 기능은 다음과 같이 정리할 수 있습니다."), ())
        self.assertTrue(cl.find_violations("방문했을 때 대기 줄이 길지 않았습니다."))
        self.assertEqual(cl.find_claims("방문하기 전에 공식 안내로 주차할 수 있는지 살펴보면 좋습니다."), ())
        self.assertEqual([claim.category for claim in cl.find_claims("약 3만 원")], [PRICE])

    def test_spacing_does_not_change_the_result(self):
        for text, _category in VIOLATING[::7]:
            squeezed = text.replace(" ", "")
            spaced = " ".join(text.replace(" ", ""))
            with self.subTest(text=text):
                base = [claim.category for claim in cl.find_claims(text)]
                self.assertEqual([claim.category for claim in cl.find_claims(squeezed)], base)
                self.assertEqual([claim.category for claim in cl.find_claims(spaced)], base)
        for text in PASSING[::9]:
            with self.subTest(text=text):
                self.assertEqual(cl.find_claims(text.replace(" ", "")), ())

    def test_full_width_and_case_forms_are_the_same_words(self):
        self.assertTrue(cl.find_violations("Ａ씨는 이 방법을 따랐습니다."))
        self.assertTrue(cl.find_violations("ＡＩ 앱을 직접 사용해보니 편리했습니다."))
        self.assertEqual([claim.category for claim in cl.find_claims("가격은 １２，０００원입니다.")], [PRICE])


class ApiTest(unittest.TestCase):
    def test_claim_is_category_position_word_and_the_position_is_the_sentence_number(self):
        found = cl.find_claims("먼저 개념을 설명합니다. 직접 사용해보니 편리했습니다. 마무리합니다.")
        self.assertTrue(found)
        category, position, word = found[0]
        self.assertEqual((category, position, word), (USE, 1, "직접사용해보니"))              # 근거 낱말은 규칙이 걸린 가장 긴 덩어리(띄어쓰기를 지운 모양)
        self.assertTrue(all(claim.position == 1 for claim in found))
        self.assertIsInstance(found, tuple)

    def test_a_list_input_numbers_the_list_and_a_text_input_numbers_its_sentences(self):
        sentences = ["첫 문장입니다.", "직접 사용해보니 편리했습니다.", "세 번째입니다."]
        self.assertEqual({claim.position for claim in cl.find_claims(sentences)}, {1})
        self.assertEqual({claim.position for claim in cl.find_claims(tuple(sentences))}, {1})
        self.assertEqual(cl.find_claims(" ".join(sentences)), cl.find_claims(sentences))

    def test_findings_come_in_sentence_order(self):
        found = cl.find_claims(["약 3만 원입니다.", "방문했을 때 대기 줄이 길지 않았습니다.", "수익을 냈습니다."])
        self.assertEqual([claim.position for claim in found], sorted(claim.position for claim in found))
        self.assertEqual({claim.position for claim in found}, {0, 1, 2})

    def test_the_category_groups_are_disjoint_and_every_category_has_a_label(self):
        self.assertFalse(set(cl.VIOLATIONS) & set(cl.REVIEWS))
        self.assertEqual(set(cl.LABELS), set(cl.VIOLATIONS) | set(cl.REVIEWS))
        self.assertTrue(all(cl.is_violation(category) for category in cl.VIOLATIONS))
        self.assertFalse(any(cl.is_violation(category) for category in cl.REVIEWS))
        self.assertFalse(cl.is_violation("모르는 분류"))

    def test_find_violations_and_find_reviews_split_the_findings(self):
        text = "직접 사용해보니 편리했습니다. 가격은 약 3만 원입니다."
        every = cl.find_claims(text)
        self.assertEqual(cl.find_violations(text) + cl.find_reviews(text), tuple(sorted(every, key=lambda claim: (claim.position, not cl.is_violation(claim.category)))))
        self.assertTrue(all(cl.is_violation(claim.category) for claim in cl.find_violations(text)))
        self.assertTrue(all(not cl.is_violation(claim.category) for claim in cl.find_reviews(text)))
        self.assertEqual(cl.find_reviews("직접 사용해보니 편리했습니다."), ())

    def test_empty_and_blank_input_finds_nothing(self):
        for value in ("", "   ", "\n\n", [], (), [""], ["  ", "\t"], "...", "!!!"):
            with self.subTest(value=value):
                self.assertEqual(cl.find_claims(value), ())

    def test_split_sentences(self):
        self.assertEqual(cl.split_sentences("가나다. 라마바! 사아자?\n차카타"), ["가나다.", "라마바!", "사아자?", "차카타"])
        self.assertEqual(cl.split_sentences("값은 3.5 입니다. 끝"), ["값은 3.5 입니다.", "끝"])
        self.assertEqual(cl.split_sentences('그는 "좋다." 라고 했다. 끝'), ['그는 "좋다."', "라고 했다.", "끝"])
        self.assertEqual(cl.split_sentences(""), [])
        self.assertEqual(cl.split_sentences(" \n "), [])
        self.assertEqual(cl.split_sentences("하나\r\n둘\u2028셋"), ["하나", "둘", "셋"])

    def test_input_that_is_not_text_is_refused(self):
        for value in (None, 5, 1.5, {"a": "b"}, {"가"}, b"abc", [1, 2], ["가", 3], ["가", None], object()):
            with self.subTest(value=value):
                with self.assertRaises(AppError) as caught:
                    cl.find_claims(value)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        with self.assertRaises(AppError) as caught:
            cl.find_claims("가나다", experience_given=True, user_sentences=5)
        self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_the_same_input_gives_the_same_result(self):
        text = " ".join(text for text, _ in VIOLATING[:40]) + " " + " ".join(PASSING[:40])
        first = cl.find_claims(text)
        for _ in range(3):
            self.assertEqual(cl.find_claims(text), first)

    def test_only_the_number_of_review_findings_is_capped_never_the_violations(self):
        reviews = cl.find_claims("가격은 약 3만 원입니다. " * 2000)
        self.assertEqual(len(reviews), 500)
        self.assertEqual(cl.MAX_FINDINGS, 500)
        self.assertEqual(reviews[0].position, 0)
        found = cl.find_claims("직접 사용해보니 편리했습니다. " * 2000)
        self.assertEqual({claim.position for claim in found}, set(range(2000)))
        self.assertGreaterEqual(len(found), 2000)
        self.assertEqual(found[0].position, 0)


class ExperienceGivenTest(unittest.TestCase):
    MINE = "직접 사용해보니 편리했습니다."

    def test_without_experience_even_the_users_own_sentence_is_a_violation(self):
        self.assertTrue(cl.find_violations([self.MINE], experience_given=False, user_sentences=[self.MINE]))

    def test_with_experience_only_the_users_sentences_are_exempt(self):
        sentences = [self.MINE, "방문했을 때 대기 줄이 길지 않았습니다.", "약 3만 원입니다."]
        found = cl.find_claims(sentences, experience_given=True, user_sentences=[self.MINE])
        self.assertFalse([claim for claim in found if claim.position == 0 and cl.is_violation(claim.category)])
        self.assertTrue([claim for claim in found if claim.position == 1 and cl.is_violation(claim.category)])
        self.assertTrue([claim for claim in found if claim.position == 2 and claim.category == PRICE])

    def test_a_plan_line_that_echoes_the_user_text_is_exempt_only_when_the_content_is_the_same(self):
        for label in ("실제 경험(입력)", "전하고 싶은 내용(입력)", "마무리에 넣을 결론(입력)", "제목 방향(입력)"):
            wrapped = f"{label}: " + self.MINE
            self.assertEqual(cl.find_violations([wrapped], experience_given=True, user_sentences=[self.MINE]), (), label)
            self.assertTrue(cl.find_violations([wrapped], experience_given=False, user_sentences=[self.MINE]))
        self.assertTrue(cl.find_violations(["실제 경험(입력): " + self.MINE + " 방문해 보니 좋았습니다."], experience_given=True, user_sentences=[self.MINE]), "되풀이 줄에 다른 단정이 덧붙으면 걸린다")
        self.assertTrue(cl.find_violations(["실제 경험: " + self.MINE], experience_given=True, user_sentences=[self.MINE]), "(입력) 표지가 없는 이름은 떼지 않는다")
        self.assertTrue(cl.find_violations(["이 가게는 " + self.MINE], experience_given=True, user_sentences=[self.MINE]), "그냥 품고 있는 것은 면제가 아니다")

    def test_a_sentence_that_only_contains_a_user_sentence_is_not_exempt(self):
        mine = "정말 좋았어요"
        for generated in ("이 가게는 방문해 보니 정말 좋았어요 라고 적습니다.", "사장님께서 말씀하시길 정말 좋았어요 라고 합니다", "정말 좋았어요 그리고 직접 써보니 편했습니다."):
            with self.subTest(generated=generated):
                self.assertTrue(cl.find_violations([generated], experience_given=True, user_sentences=[mine]))
        self.assertEqual(cl.find_violations([mine], experience_given=True, user_sentences=[mine]), ())
        self.assertEqual(cl.find_violations(["정말  좋았어요!"], experience_given=True, user_sentences=[mine]), (), "띄어쓰기·기호 차이는 같은 문장이다")

    def test_a_fragment_of_the_users_text_is_not_exempt(self):
        mine = "직접 사용해보니 편리했습니다, 가격도 적당했습니다."                      # 쉼표로 이어진 한 문장의 앞부분만 있는 문장은 같은 문장이 아니다
        self.assertTrue(cl.find_violations(["직접 사용해보니 편리했습니다"], experience_given=True, user_sentences=mine))
        mine = "직접 사용해보니 편리했습니다. 가격도 적당했습니다."
        self.assertEqual(cl.find_violations(["직접 사용해보니 편리했습니다."], experience_given=True, user_sentences=mine), (), "한 덩어리 글은 문장마다 나눠 견준다")
        self.assertEqual(cl.find_violations([mine], experience_given=True, user_sentences=mine), (), "한 덩어리 글 전체도 같은 글이다")
        self.assertTrue(cl.find_violations(["직접 사용해보니 편리했습니다. 방문해 보니 좋았습니다."], experience_given=True, user_sentences=mine))

    def test_the_same_sentence_in_a_different_case_or_width_is_exempt(self):
        self.assertEqual(cl.find_violations(["ＡＩ 앱을 직접 사용해보니 편리했습니다"], experience_given=True, user_sentences=["ai 앱을 직접 사용해보니 편리했습니다."]), ())

    def test_the_users_text_can_be_one_string_or_a_list(self):
        for mine in (self.MINE, [self.MINE], (self.MINE,)):
            self.assertEqual(cl.find_violations(self.MINE, experience_given=True, user_sentences=mine), ())

    def test_reviews_are_reported_even_for_the_users_sentences(self):
        mine = "직접 사용해보니 편리했습니다. 가격은 약 3만 원입니다."
        found = cl.find_claims(mine, experience_given=True, user_sentences=mine)
        self.assertEqual([claim.category for claim in found], [PRICE])

    def test_a_different_sentence_is_not_exempted_by_a_similar_user_sentence(self):
        found = cl.find_violations(["직접 사용해보니 정말 편리했습니다."], experience_given=True, user_sentences=[self.MINE])
        self.assertTrue(found)

    def test_very_short_user_sentences_do_not_exempt_anything(self):
        found = cl.find_violations(["직접 사용해보니 편리했습니다."], experience_given=True, user_sentences=["네", "편리"])
        self.assertTrue(found)

    def test_experience_given_without_user_sentences_exempts_nothing(self):
        self.assertTrue(cl.find_violations([self.MINE], experience_given=True))


class HiddenCharactersTest(unittest.TestCase):
    def test_a_hidden_character_between_jamo_does_not_hide_a_claim(self):
        import unicodedata
        base = "직접 사용해보니 편리했습니다."
        for text in (unicodedata.normalize("NFD", base), "\u200b".join(unicodedata.normalize("NFD", base)), "\u200b".join(base)):
            with self.subTest(text=repr(text[:12])):
                self.assertTrue(cl.find_violations(text))


class PerformanceTest(unittest.TestCase):
    def assert_fast(self, text, limit=5.0):                                      # 제곱 시간이면 수 분 걸리는 입력이라 넉넉히 잡는다(느린 러너에서 흔들리지 않게)
        started = time.perf_counter()
        cl.find_claims(text)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, limit, f"{len(text)}자에 {elapsed:.2f}초")

    def test_hundreds_of_thousands_of_characters_finish_within_a_second(self):
        paragraph = " ".join(PASSING) + " "
        self.assert_fast(paragraph * (300_000 // len(paragraph) + 1))

    def test_one_endless_sentence_is_linear_too(self):
        self.assert_fast("가" * 300_000)
        self.assert_fast("사용" * 150_000)
        self.assert_fast("직접 " * 100_000)
        self.assert_fast("댓글로 " * 80_000)

    def test_long_runs_of_spaces_and_punctuation_are_linear(self):
        self.assert_fast(" " * 300_000 + "가")
        self.assert_fast("가. " * 100_000)
        self.assert_fast(".!?" * 100_000)
        self.assert_fast("\n" * 300_000)

    def test_repeated_trigger_words_are_linear(self):
        self.assert_fast("방문했을 때 " * 50_000)
        self.assert_fast("수익" * 120_000)
        self.assert_fast("0123456789" * 30_000)
        self.assert_fast("원" * 200_000)
        self.assert_fast("한달" * 100_000)


if __name__ == "__main__":
    unittest.main()
