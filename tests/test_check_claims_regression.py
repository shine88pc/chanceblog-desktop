"""검증자가 따로 만든 예문 187개(위반 78·통과 73·확인 권장 36)와 추가 형태 53개로 '지어내지 않기' 검사의 재현율·오탐률을 고정한다.

지키는 것:
  1) 위반 예문은 모두(재현율 100%, 지시 기준은 85% 이상) 걸리고 분류도 맞다(영어 예문은 분류를 따지지 않는다). 통과 예문은 아무것도 안 걸린다(오탐 0, 기준은 5% 이하).
  2) 확인 권장 예문은 그 분류로 나오고 위반으로는 나오지 않는다.
  3) 어간 × 어미를 곱한 문장(체험해·착용해·시승해·먹어 … × 보니·봤·본 결과 …)이 걸리고, 같은 어간의 권유·조건·부정·질문·따옴표 언급은 지나간다.
  4) '-했던·-했지만' 꾸밈·대조꼴, '…했다고 합니다' 옮겨 전하기, 글 쓰는 일을 가리키는 과거형('방문했을 때 …정리했습니다')은 지나가고, 같은 낱말이라도 겪은 일의 보고면 걸린다.
  5) 보이지 않는 글자·자모를 끼워도 같은 결과다. 영어 첫 사람 경험 단정도 걸린다.
알려진 한계: 한자 혼용(直接 使用)·글자 사이에 숫자나 자음을 끼운 것·낱말 목록에 없는 체감 표현('배터리가 오래 갔습니다' 같은 낱말 없는 문장)은 못 잡을 수 있다.
네트워크·파일 없이 돈다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.check import claims as cl  # noqa: E402

USE, VISIT, BUY, INCOME, EFFECT, DIALOGUE, CASE = cl.EXPERIENCE_USE, cl.EXPERIENCE_VISIT, cl.EXPERIENCE_BUY, cl.EXPERIENCE_INCOME, cl.EXPERIENCE_EFFECT, cl.DIALOGUE, cl.CASE

# 경험을 주장하는 글 — (문장, 걸려야 하는 분류 또는 None=아무 위반이나)
VIOLATIONS = (
    ('써 봤는데 생각보다 훨씬 조용했어요.', USE), ('일주일 사용해 보니 배터리가 이틀은 가더라고요.', USE),
    ('이 칫솔을 3개월 동안 써 왔습니다.', USE), ('직접 사용해 보았습니다.', USE),
    ('제가 직접 체험해 본 결과를 정리했습니다.', USE), ('에어프라이어로 직접 만들어 먹어봤습니다.', USE),
    ('설치해 봤더니 5분도 안 걸렸어요.', USE), ('직접 착용해 보니 사이즈가 작았어요.', USE),
    ('매일 아침 한 알씩 복용했습니다.', USE), ('두 달째 쓰고 있는데 아직 멀쩡합니다.', USE),
    ('한 달 정도 사용 중인데 만족합니다.', USE), ('쓰다 보니 어느새 손에 익었습니다.', USE),
    ('한 번 들어 봤는데 음질이 깨끗했어요.', USE), ('이 앱으로 가계부를 써 보니 지출이 한눈에 보였습니다.', USE),
    ('먹어보니 달지 않고 담백했어요.', USE), ('제가 이 강좌를 끝까지 들었습니다.', USE),
    ('노트북에 직접 깔아서 써 봤습니다.', USE), ('면접 전에 이 방법을 따라 해 보았습니다.', USE),
    ('이 제품을 사용해 본 소감을 적습니다.', USE), ('저는 이 서비스를 작년부터 이용했습니다.', USE),
    ('지난 토요일에 가족들과 다녀왔어요.', VISIT), ('어제 퇴근하고 들렀는데 한산했습니다.', VISIT),
    ('점심시간에 맞춰 갔더니 줄이 길었어요.', VISIT), ('직접 가 보니 주차장이 넓었어요.', VISIT),
    ('예약 없이 방문했더니 40분 기다렸습니다.', VISIT), ('저는 지난달에 이곳을 찾았습니다.', VISIT),
    ('서울 본점에 직접 방문해 보았습니다.', VISIT), ('우리 가족은 이번 연휴에 이곳에서 묵었습니다.', VISIT),
    ('입구를 찾느라 조금 헤맸습니다.', VISIT), ('주말에 아이들과 함께 다녀온 곳입니다.', VISIT),
    ('다녀왔는데 사람이 정말 많더라고요.', VISIT), ('제가 직접 가서 확인했습니다.', VISIT),
    ('이번에 새로 구입한 제품입니다.', BUY), ('쿠팡 로켓배송으로 주문했는데 다음 날 도착했습니다.', BUY),
    ('할인 중이라 두 개 샀어요.', BUY), ('공식 스토어에서 결제를 마쳤습니다.', BUY),
    ('제품이 도착해서 바로 포장을 뜯었습니다.', BUY), ('내 돈 주고 샀어요.', BUY),
    ('공식 몰에서 결제했더니 사은품을 받았습니다.', BUY), ('최근에 이 노트북을 구입했습니다.', BUY),
    ('저는 이 제품을 직접 구매했습니다.', BUY), ('이 방법으로 첫 달에 30만 원을 벌었습니다.', INCOME),
    ('블로그를 시작하고 석 달 만에 수익을 냈어요.', INCOME), ('광고 수익이 매달 늘고 있습니다.', INCOME),
    ('애드센스 첫 정산을 받았습니다.', INCOME), ('블로그 수익이 월 100만 원을 넘었습니다.', INCOME),
    ('허리 통증이 확실히 줄었어요.', EFFECT), ('피부 결이 한결 부드러워졌습니다.', EFFECT),
    ('화면이 밝아서 눈이 편안했습니다.', EFFECT), ('소음이 거의 들리지 않아서 만족합니다.', EFFECT),
    ('가격 대비 성능이 훌륭하다고 느꼈습니다.', EFFECT), ('솔직히 기대 이상이었어요.', EFFECT),
    ('몸이 가벼워진 느낌이 들었어요.', EFFECT), ('맛이 정말 일품이었습니다.', EFFECT),
    ('배터리가 하루 종일 갔습니다.', EFFECT), ('설치가 쉬웠어요.', EFFECT),
    ('맛이 별로였어요.', EFFECT), ('생각보다 가벼워서 놀랐어요.', EFFECT),
    ('직원분께 물어보니 인기 메뉴라고 알려 주셨어요.', DIALOGUE), ('전화로 확인했더니 오늘은 재고가 없다고 하더군요.', DIALOGUE),
    ('사장님께서 직접 설명해 주셨습니다.', DIALOGUE), ('이웃님이 댓글로 질문을 주셨는데요.', DIALOGUE),
    ('친구가 써 보라고 해서 시작했어요.', DIALOGUE), ('고객센터와 통화해 보니 환불은 7일 이내라고 합니다.', DIALOGUE),
    ('의사 선생님이 괜찮다고 하셨어요.', DIALOGUE), ('상담원이 친절하게 안내해 주었습니다.', DIALOGUE),
    ('댓글을 남겨 주신 이웃님 덕분에 알게 됐습니다.', DIALOGUE), ('제가 아는 한 분도 같은 문제를 겪었어요.', CASE),
    ('얼마 전 한 독자가 메일을 보내 왔습니다.', CASE), ('회사 동료 B씨는 이 방법으로 합격했습니다.', CASE),
    ('박 대리는 이 앱으로 일정을 정리한다고 합니다.', CASE), ('실제 고객 사례를 소개하겠습니다.', CASE),
    ('저희 어머니도 같은 방법으로 효과를 보셨어요.', CASE), ('I tried this app for a week and it worked well.', None),
    ('In my experience, the battery lasts two days.', None), ('I visited the store last Saturday.', None),
    ('My honest review after using it for 3 months.', None), ('Used it every day and loved it.', None),
)

# 경험을 주장하지 않는 글(안내·조건·부정·질문·권유·일반 설명) — 아무것도 걸리면 안 된다
PASSES = (
    '구매하기 전에 반품 규정을 먼저 확인해 보세요.', '방문하기 전에 주차 가능 여부를 전화로 문의해 보시기 바랍니다.',
    '직접 써 보지 않은 제품은 후기처럼 쓰지 않습니다.', '이 글은 공식 자료를 바탕으로 정리한 안내문이며 개인 체험담이 아닙니다.',
    '사용해 보고 싶다면 무료 체험 기간을 먼저 확인하세요.', '설치 방법은 아래 순서대로 따라 하면 됩니다.',
    '처음 이용하는 분이라면 가입 절차부터 살펴보세요.', '주문 내역은 마이페이지에서 언제든 확인할 수 있습니다.',
    '다녀오신 분은 영수증을 꼭 보관해 두세요.', '먹어 보기 전에 원재료명을 확인하는 습관이 필요합니다.',
    '체험 후기를 쓰려면 실제로 이용한 경험이 있어야 합니다.', '비교할 때는 같은 조건에서 같은 항목을 견주어야 합니다.',
    '이 제품은 두 가지 색상으로 판매됩니다.', '앱을 처음 실행하면 권한 요청 화면이 나타납니다.',
    '점검이 끝나면 전원을 다시 켜 주세요.', '증상이 계속되면 서비스 센터에 문의하세요.',
    '문의가 많은 항목은 공식 FAQ에 정리되어 있습니다.', '직원에게 물어보면 메뉴 추천을 받을 수 있습니다.',
    '댓글은 비밀번호 없이도 남길 수 있습니다.', '고객센터 운영 시간은 공식 홈페이지 공지를 확인하세요.',
    '효과는 개인마다 다르므로 전문가와 상담하세요.', '이 방법으로 수익을 보장하지 않습니다.',
    '수익을 내려면 꾸준한 글쓰기가 필요하다고 알려져 있습니다.', '광고 수익은 방문자 수와 광고 단가에 따라 달라집니다.',
    '한 달 동안 사용해 보고 환불할 수 있는 정책이 있는지 확인합니다.', '일주일 동안 쓸 수 있는 체험판이 제공됩니다.',
    '구매했을 때 받은 영수증은 교환과 환불에 필요합니다.', '사용해 보니 어떠셨는지 댓글로 알려 주세요.',
    '써 보시고 마음에 드시면 구독해 주세요.', '이용 후에는 후기 작성에 참여해 주세요.',
    '신제품이 나오면 가격이 내려가는 경우가 많습니다.', '지난 모델과 비교해 무게가 줄었다고 공식 자료에 나와 있습니다.',
    '제조사는 소음을 줄였다고 설명합니다.', '지인에게 추천하고 싶다면 사용 목적부터 정리하세요.',
    '친구에게 선물할 때는 영수증을 함께 챙기세요.', '김치찌개 레시피를 단계별로 정리했습니다.',
    '카메라 설정 방법을 사진과 함께 정리합니다.', '더 자세한 내용은 아래 링크를 참고하세요.',
    '여행 일정은 이동 시간을 고려해 여유 있게 짜는 것이 좋습니다.', '장점은 휴대성이고 단점은 배터리 용량입니다.',
    '장점과 단점을 함께 정리합니다.', 'A사와 B사의 요금제를 같은 기준으로 비교합니다.',
    '이 약은 하루 세 번 복용합니다.', '권장 사용 시간은 제품 설명서에 나와 있습니다.',
    '사용 중에 이상이 느껴지면 즉시 중단하십시오.', '만족하지 못하면 환불이 가능한지 확인하세요.',
    '만족했다면 후기를 남겨 주세요.', '불편했던 점이 있다면 알려 주세요.',
    '이 기능이 편리하다고 느끼는 사용자가 많습니다.', '가족과 함께 이용하기 좋은 곳을 소개합니다.',
    '내일 방문할 예정이라면 오늘 예약하세요.', '다녀온 뒤에는 사진을 정리해 보세요.',
    '처음 설치할 때 실수하기 쉬운 부분을 짚어 줍니다.', 'Unboxing 영상이 필요하다면 공식 채널에서 확인하세요.',
    'How to choose a laptop: a guide for beginners.', 'Check the official site before you visit.',
    '일정이 바뀔 수 있으니 출발 전에 다시 확인하세요.', '직접 써 본 사람만 적을 수 있는 내용입니다.',
    '사장님께 예약 방법을 여쭤보면 친절하게 안내해 줄 가능성이 높습니다.', '방문했을 때 확인할 점을 체크리스트로 정리했습니다.',
    '가격이 저렴했던 시기에 사는 것이 유리할 수 있습니다.', '예전에는 설치가 불편했지만 최근 버전에서는 자동 설치를 지원합니다.',
    '초기 버전은 속도가 느렸으나 업데이트로 개선되었다고 안내되어 있습니다.', '비쌌던 가격이 내려간 사례가 있는지 판매처에서 확인하세요.',
    '한 고객이 불만을 제기하면 바로 사과하는 것이 응대 요령입니다.', '어떤 분은 기능이 많을수록 좋다고 생각하지만 필요한 기능만 고르는 것이 좋습니다.',
    '써 보니 어떠셨나요?', '방문해 보니 어땠나요? 댓글로 알려 주세요.',
    '좋았던 점과 아쉬웠던 점을 항목으로 나누어 적습니다.', '후기 형식으로 쓰려면 직접 사용한 사람의 입력이 필요합니다.',
    '인기 메뉴는 매장 직원에게 물어보면 알 수 있습니다.', '이 글을 쓰는 데 참고한 자료는 아래에 모아 두었습니다.',
    '독자가 직접 사용해 보고 비교할 수 있도록 확인 항목을 나눕니다.',
)

# 확인 권장(위반이 아니다) — (문장, 분류)
REVIEWS = (
    ('월 구독료는 9,900원입니다.', 'price'), ('권장 소비자가는 129,000원입니다.', 'price'),
    ('2만 원대 가격입니다.', 'price'), ('약 5만5천 원 정도입니다.', 'price'),
    ('가격은 49달러부터 시작합니다.', 'price'), ('정가는 1,200엔입니다.', 'price'),
    ('이천 원이 추가됩니다.', 'price'), ('입장료는 팔천 원입니다.', 'price'),
    ('약 100만 원입니다.', 'price'), ('가격은 사만 원입니다.', 'price'),
    ('USD 49 부터 시작합니다.', 'price'), ('1억 2천만 원입니다.', 'price'),
    ('요금은 월 19,800 원입니다.', 'price'), ('2025년 12월 31일까지 신청할 수 있습니다.', 'date'),
    ('2026.01.15 에 업데이트됩니다.', 'date'), ('12월 25일에 문을 엽니다.', 'date'),
    ('1월 1일부터 적용됩니다.', 'date'), ('올해 3월에 개정되었습니다.', 'date'),
    ('11/3 에 출시됩니다.', 'date'), ('매일 오전 10시에 시작합니다.', 'time'),
    ('저녁 7시 30분까지 운영합니다.', 'time'), ('이동에 20분 정도 걸립니다.', 'time'),
    ('설치에는 약 2시간이 소요됩니다.', 'time'), ('배송은 영업일 기준 3일 이내입니다.', 'time'),
    ('영업시간은 09:00~18:00 입니다.', 'time'), ('사용자의 85%가 선택했습니다.', 'stat'),
    ('만족도는 92퍼센트입니다.', 'stat'), ('점유율은 약 12.5%입니다.', 'stat'),
    ('응답자의 절반 이상이 같은 의견이었습니다.', 'stat'), ('소비자원 조사에 따르면 불만이 늘었습니다.', 'stat'),
    ('전문가 설문 결과를 인용합니다.', 'stat'), ('5명 중 3명이 선택했습니다.', 'stat'),
    ('전체의 3분의 1이 해당합니다.', 'stat'), ('열 명 중 아홉 명이 선택했습니다.', 'stat'),
    ('한국소비자원 조사에 의하면 불만이 늘었습니다.', 'stat'), ('판매량이 3배 늘었다고 합니다.', 'stat'),
)

# 추가 형태: 부정·인용·가정·높임·제목·표·목록·전각·띄어쓰기
EXTRA_VIOLATIONS = (
    '방문했습니다만 사람이 많았습니다.', '사용해 보았습니다만 별로였습니다.',
    '먹어 본 결과 맛이 진했습니다.', '체험해보았다.',
    '써 봤는데 좋았어요.', '써보니 편했어요.',
    '사용해 보았습니다.', '다녀왔어요.',
    '구매했는데 만족해요.', '방문했을 때 직원이 친절했어요.',
    '## 직접 사용해보니', '- 직접 써본 후기',
    '| 항목 | 직접 사용해본 결과 |', '1) 써 봤을 때의 느낌: 좋았다',
    '[후기] 다녀왔습니다', '**직접 먹어봤어요**',
    '추천받아서 구매했습니다.', '지인이 소개해 줘서 써 봤습니다.',
    '체험단으로 제공받아 사용했습니다.', '협찬받아 써 봤습니다.',
    '實使用 후기를 남깁니다. 直接 써봤어요.', 'ＳＮＳ에서 보고 구매했습니다.',
    '써 봤 는 데 좋았 어요', '사 용 해 보 니 편 했 습 니 다',
    '체감상 훨씬 빨랐습니다.', '써본 결과는 만족입니다.',
    '실사용 기준으로 정리했습니다.',
)
EXTRA_PASSES = (
    '직접 써보지 않았지만 공식 자료를 정리했습니다.', '구매하지 않았습니다.',
    '방문한 적이 없습니다.', '사용해 본 적은 없습니다.',
    '써 본 적이 없어서 후기는 쓰지 않습니다.', '사용해 보면 알 수 있습니다.',
    '직접 사용해 보면 차이를 알 수 있습니다.', '방문하시면 입구에서 안내 직원이 도와줍니다.',
    '구매하시면 영수증을 보관하세요.', '써 보시길 권합니다.',
    '다녀오시면 후기를 남겨 주세요.', '사용해 보셨나요?',
    '직접 써 보신 분은 댓글로 알려 주세요.', '방문했다면 영수증을 보관하세요.',
    '만약 구매했다면 환불 규정을 확인합니다.', "'직접 써봤는데 좋았어요' 같은 후기를 그대로 믿지 마세요.",
    '"사용해보니 좋더라" 라는 표현은 경험을 전제한 말입니다.', "후기를 쓸 때는 '다녀왔습니다' 같은 말을 직접 겪은 경우에만 씁니다.",
    '체감 효과는 사람마다 다릅니다.', '체감 성능은 환경에 따라 달라질 수 있습니다.',
    '실사용 후기는 판매처 게시판에서 확인할 수 있습니다.', '후기를 남기기 전에 이용 약관을 확인합니다.',
    '리뷰를 읽을 때는 광고 표시를 확인하세요.', '이 글은 직접 체험한 내용이 아니라 공식 자료를 정리한 안내입니다.',
    '경험한 일만 경험한 것처럼 쓰세요.', '본인이 직접 사용한 경험이 있을 때만 경험담을 적습니다.',
)


def violated(text):
    return {claim.category for claim in cl.find_violations(text)}


class IndependentExamplesTest(unittest.TestCase):
    def test_every_example_has_the_expected_size(self):
        self.assertEqual((len(VIOLATIONS), len(PASSES), len(REVIEWS)), (78, 73, 36))
        self.assertEqual((len(EXTRA_VIOLATIONS), len(EXTRA_PASSES)), (27, 26))

    def test_recall_and_false_positive_rates_meet_the_bar(self):
        missed = [text for text, _kind in VIOLATIONS if not violated(text)] + [text for text in EXTRA_VIOLATIONS if not violated(text)]
        total = len(VIOLATIONS) + len(EXTRA_VIOLATIONS)
        self.assertGreaterEqual((total - len(missed)) / total, 0.85, missed)
        noisy = [text for text in (*PASSES, *EXTRA_PASSES) if cl.find_violations(text)]
        self.assertLessEqual(len(noisy) / (len(PASSES) + len(EXTRA_PASSES)), 0.05, noisy)

    def test_every_violating_example_is_caught_with_its_category(self):
        for text, want in VIOLATIONS:
            with self.subTest(text=text):
                found = violated(text)
                self.assertTrue(found)
                if want is not None:
                    self.assertIn(want, found)

    def test_extra_forms_are_caught(self):
        for text in EXTRA_VIOLATIONS:
            with self.subTest(text=text):
                self.assertTrue(violated(text))

    def test_no_passing_example_is_flagged(self):
        for text in PASSES:
            with self.subTest(text=text):
                self.assertEqual(cl.find_claims(text), ())

    def test_extra_passing_forms_are_not_violations(self):
        for text in EXTRA_PASSES:
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_reviews_come_out_with_their_category_and_never_as_violations(self):
        for text, category in REVIEWS:
            with self.subTest(text=text):
                found = cl.find_claims(text)
                self.assertIn(category, {claim.category for claim in found})
                self.assertEqual(cl.find_violations(text), ())
                self.assertTrue(all(claim.category in cl.REVIEWS for claim in found))


class GeneralisationTest(unittest.TestCase):
    """낱말을 한 줄씩 늘린 것이 아니라 어간 × 어미 곱이다 — 처음 보는 조합도 걸린다."""
    STEMS = ("사용해", "써", "이용해", "체험해", "경험해", "착용해", "복용해", "설치해", "적용해", "테스트해", "시승해", "시착해", "시식해", "시청해", "먹어", "마셔", "입어", "신어", "발라", "들어",
             "읽어", "돌려", "켜", "틀어", "타", "앉아", "만져", "깔아", "열어", "눌러", "만들어", "끓여", "구워", "따라해")
    TRIED = ("보니", "봤", "보았", "본 결과", "본 후", "본 소감", "본 느낌")

    def test_every_stem_times_every_ending_is_an_experience_claim(self):
        for stem in self.STEMS:
            for ending in self.TRIED:
                text = f"어제 {stem} {ending}"
                with self.subTest(text=text):
                    self.assertIn(USE, violated(text + " 만족했습니다."))
                    self.assertIn(USE, violated("직접 " + text + " 생각보다 괜찮았어요"))

    def test_the_same_stems_in_advice_conditions_negations_and_questions_pass(self):
        for stem in self.STEMS:
            for text in (f"{stem} 보세요.", f"{stem} 보시면 알 수 있습니다.", f"{stem} 본 적이 없습니다.", f"{stem} 보지 않았지만 공식 자료를 정리했습니다.", f"{stem} 보고 싶다면 체험판부터 확인하세요.",
                         f"{stem} 봤다면 후기를 남겨 주세요.", f"{stem} 본 사람은 결과를 댓글로 알려 주세요.", f"{stem} 보니 어떠셨나요?", f"{stem} 본 경우에만 경험담을 적습니다.", f"{stem} 보지 않은 제품은 후기처럼 쓰지 않습니다."):
                with self.subTest(text=text):
                    self.assertEqual(cl.find_violations(text), ())

    def test_visits_in_every_form_of_the_past(self):
        for text in ("점심에 갔더니 줄이 길었어요.", "비 오는 날 갔다가 허탕을 쳤습니다.", "가족과 다녀온 곳입니다.", "제주에서 이틀을 묵었습니다.", "입구를 못 찾아 헤맸습니다.", "지난 주말에 방문했는데 한산했어요.",
                     "저는 친구와 이곳을 찾았습니다.", "우리 가족은 연휴에 이곳에 들렀습니다.", "어제 다녀왔어요."):
            with self.subTest(text=text):
                self.assertIn(VISIT, violated(text))
        for text in ("방문하기 전에 영업시간을 확인하세요.", "다녀오신 분은 영수증을 보관하세요.", "방문했다면 영수증을 보관하세요.", "갔더니 어땠나요?", "방문한 적이 없다면 후기를 쓰지 않습니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_buying_in_every_form_of_the_past(self):
        for text in ("이번에 새로 구입한 제품입니다.", "공식 스토어에서 결제를 마쳤습니다.", "주문한 제품이 도착했습니다.", "택배 상자를 열어 포장을 뜯었습니다.", "어제 두 개를 샀어요.", "직접 구매했습니다.", "최근에 구매한 노트북입니다."):
            with self.subTest(text=text):
                self.assertIn(BUY, violated(text))
        for text in ("구매하기 전에 환불 규정을 확인하세요.", "구매한 경우 영수증을 보관하세요.", "구매했다면 영수증을 보관하세요.", "구매를 마치면 안내 메일이 옵니다.", "주문 내역은 마이페이지에서 확인합니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_income_and_effect_claims(self):
        for text in ("블로그 수익이 월 100만 원을 넘었습니다.", "광고 수익이 매달 늘고 있습니다.", "애드센스 정산을 받았습니다.", "첫 달부터 수익이 늘었어요."):
            with self.subTest(text=text):
                self.assertIn(INCOME, violated(text))
        for text in ("허리 통증이 줄었어요.", "피부 결이 부드러워졌습니다.", "화면이 밝아서 눈이 편안했습니다.", "소음이 거의 없어서 만족합니다.", "맛이 별로였어요.", "설치가 쉬웠어요.", "배터리가 하루 종일 갔습니다."):
            with self.subTest(text=text):
                self.assertIn(EFFECT, violated(text))

    def test_people_and_conversations(self):
        for text in ("사장님께서 직접 설명해 주셨습니다.", "상담원이 친절하게 안내해 주었습니다.", "친구가 써 보라고 해서 시작했어요.", "댓글을 남겨 주신 이웃님 덕분에 알게 됐습니다.", "의사 선생님이 괜찮다고 하셨어요."):
            with self.subTest(text=text):
                self.assertIn(DIALOGUE, violated(text))
        for text in ("박 대리는 이 앱으로 일정을 정리한다고 합니다.", "실제 고객 사례를 소개하겠습니다.", "저희 어머니도 같은 방법으로 효과를 보셨어요.", "회사 동료 B씨는 합격했습니다.", "한 독자가 메일을 보내 왔습니다."):
            with self.subTest(text=text):
                self.assertIn(CASE, violated(text))


class GuardsTest(unittest.TestCase):
    ADJECTIVES = ("편리했", "불편했", "느렸", "빨랐", "저렴했", "비쌌", "아쉬웠", "좋았", "쉬웠", "어려웠", "무거웠", "작았")

    def test_modifier_and_contrast_forms_of_a_past_state_pass_but_a_report_does_not(self):
        for word in self.ADJECTIVES:
            for text in (f"{word}던 점은 최신 버전에서 개선되었다고 안내됩니다.", f"예전에는 {word}지만 지금은 다릅니다.", f"초기 버전은 {word}으나 업데이트로 나아졌습니다.", f"{word}던 점과 아쉬웠던 점을 나눠 적습니다."):
                with self.subTest(text=text):
                    self.assertEqual(cl.find_violations(text), ())
            with self.subTest(word=word):
                self.assertIn(EFFECT, violated(f"써 보니 정말 {word}습니다.") | violated(f"정말 {word}어요."))
        self.assertEqual(cl.find_violations("느렸던 노트북 속도 개선"), ())
        self.assertEqual(cl.find_violations("불편했던 점을 모아 정리합니다."), ())

    def test_reporting_what_others_say_is_not_the_authors_effect_claim(self):
        for text in ("지난 모델과 비교해 무게가 줄었다고 공식 자료에 나와 있습니다.", "제조사는 소음이 줄었다고 설명합니다.", "소음이 줄었다는 후기가 있습니다만 개인차가 있습니다.", "수익이 늘었다고 알려져 있습니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_questions_pass(self):
        for text in ("써 보니 어떠셨나요?", "방문해 보니 어땠나요? 댓글로 알려 주세요.", "직접 사용해 보셨나요?", "다녀왔는데 어땠는지 궁금합니다?", "구매했는데 만족하시나요"):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_a_quoted_phrase_that_is_only_pointed_at_passes_but_a_standalone_quote_does_not(self):
        for text in ("'직접 써봤는데 좋았어요' 같은 후기를 그대로 믿지 마세요.", "\"사용해보니 좋더라\" 라는 표현은 경험을 전제한 말입니다.", "후기를 쓸 때는 '다녀왔습니다' 같은 말을 직접 겪은 경우에만 씁니다.",
                     "「직접 사용해 봤어요」 처럼 쓰지 않습니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())
        for text in ("\"직접 써봤는데 좋았어요\" 라고 합니다.", "후기: '직접 써봤는데 좋았어요'", "저는 \"써보니 편했다\" 고 느꼈습니다."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))

    def test_writing_about_the_article_is_not_an_experience_but_a_visit_report_is(self):
        for text in ("방문했을 때 확인할 점을 체크리스트로 정리했습니다.", "구매했을 때 받는 서류를 표로 정리했습니다.", "사용했을 때 주의할 점을 항목으로 나누어 적었습니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())
        for text in ("방문했을 때 줄이 길었습니다.", "구매했을 때 포장이 훌륭했습니다.", "사용했을 때 소음이 컸습니다."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))

    def test_a_generic_person_in_a_condition_passes_but_one_who_did_something_does_not(self):
        for text in ("한 고객이 불만을 제기하면 바로 사과하는 것이 응대 요령입니다.", "어떤 분은 기능이 많을수록 좋다고 생각하지만 필요한 기능만 고르는 것이 좋습니다.", "한 독자가 질문하면 답을 드리겠습니다."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())
        for text in ("한 고객이 불만을 제기했습니다.", "어떤 분은 이렇게 해결했습니다.", "얼마 전 한 독자가 메일을 보내 왔습니다."):
            with self.subTest(text=text):
                self.assertIn(CASE, violated(text))

    def test_pointing_at_a_negated_report_passes(self):
        for text in ("이 글은 직접 체험한 내용이 아니라 공식 자료를 정리한 안내입니다.", "본인이 직접 사용한 경험이 있을 때만 경험담을 적습니다.", "직접 다녀온 경우에만 방문 후기를 씁니다.", "직접 사용한 사람은 댓글을 남겨 주세요."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())


class InvisibleCharactersTest(unittest.TestCase):
    BASE = "직접 사용해보니 편리했습니다."
    FILLERS = {"ZWSP": "\u200b", "ZWNJ": "\u200c", "ZWJ": "\u200d", "BOM": "\ufeff", "soft hyphen": "\u00ad", "word joiner": "\u2060", "LRM": "\u200e", "RLO": "\u202e", "한글 채움 3164": "\u3164",
               "한글 채움 115F": "\u115f", "한글 채움 1160": "\u1160", "한글 채움 FFA0": "\uffa0", "변형 선택자": "\ufe0f", "결합 자소 결합기": "\u034f", "점자 빈칸": "\u2800", "물체 대체": "￼"}

    def test_a_hidden_character_inside_a_word_changes_nothing(self):
        for name, filler in self.FILLERS.items():
            with self.subTest(filler=name):
                self.assertIn(USE, violated(self.BASE.replace("사용", "사용" + filler).replace("보니", filler + "보니")))
                self.assertIn(USE, violated(filler.join(self.BASE)))

    def test_hidden_characters_between_jamo_do_not_hide_a_claim(self):
        import unicodedata
        decomposed = unicodedata.normalize("NFD", self.BASE)
        self.assertIn(USE, violated(decomposed))
        for filler in ("\u200b", "\u200d", "\ufeff", "\u3164", "\u115f"):
            with self.subTest(filler=repr(filler)):
                self.assertIn(USE, violated(filler.join(decomposed)))

    def test_compatibility_jamo_and_full_width_letters_are_folded(self):
        self.assertTrue(cl.find_violations("직접 사용해보니 ㅍㅕㄴ리했습니다."))
        self.assertTrue(cl.find_violations("ＡＩ 앱을 직접 사용해보니 좋았습니다."))
        self.assertTrue(cl.find_violations("직.접 사.용.해.보.니"))
        self.assertTrue(cl.find_violations("직/접/사/용/해/보/니 편/리/했/습/니/다"))

    def test_hidden_characters_do_not_break_the_review_rules_either(self):
        self.assertEqual({claim.category for claim in cl.find_claims("가격은 3\u200b만 원입니다.")}, {cl.PRICE})
        self.assertEqual({claim.category for claim in cl.find_claims("가격은 1\u200d2,000원입니다.")}, {cl.PRICE})


class EnglishTest(unittest.TestCase):
    def test_first_person_experience_claims_in_english(self):
        for text in ("I tried this app for a week and it worked well.", "In my experience, the battery lasts two days.", "I visited the store last Saturday.", "My honest review after using it for 3 months.",
                     "Used it every day and loved it.", "We stayed two nights and the staff said it was fine.", "I bought it last week.", "I've used it daily for a year.", "After trying three models, I made my choice.",
                     "The owner told me the shop opens at nine.", "I earned my first $100 from ads."):
            with self.subTest(text=text):
                self.assertTrue(cl.find_violations(text))

    def test_advice_and_guides_in_english_pass(self):
        for text in ("How to choose a laptop: a guide for beginners.", "Check the official site before you visit.", "You can try the free plan first.", "If you tried it, tell us what you think.",
                     "I have never tried it, so this guide uses official specs.", "Before you buy, compare the return policies.", "Unboxing videos are available on the official channel."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())


class MoreReviewsTest(unittest.TestCase):
    def test_new_review_shapes(self):
        for text, category in (("USD 49 부터 시작합니다.", cl.PRICE), ("49 USD 입니다.", cl.PRICE), ("올해 3월에 개정되었습니다.", cl.DATE), ("작년 12월에 출시되었습니다.", cl.DATE), ("11/3 에 출시됩니다.", cl.DATE),
                               ("설치에는 약 2시간이 소요됩니다.", cl.TIME), ("배송은 영업일 기준 3일 이내입니다.", cl.TIME), ("전체의 3분의 1이 해당합니다.", cl.STAT), ("열 명 중 아홉 명이 선택했습니다.", cl.STAT),
                               ("한국소비자원 조사에 의하면 불만이 늘었습니다.", cl.STAT), ("판매량이 3배 늘었다고 합니다.", cl.STAT)):
            with self.subTest(text=text):
                self.assertIn(category, {claim.category for claim in cl.find_claims(text)})

    def test_plain_fractions_and_unrelated_numbers_are_not_dates(self):
        for text in ("설탕은 1/2 컵을 넣습니다.", "화면 비율은 16/9 입니다.", "3개를 고릅니다."):
            with self.subTest(text=text):
                self.assertNotIn(cl.DATE, {claim.category for claim in cl.find_claims(text)})


OWN_VIOLATIONS = (
    "이 노트북을 3개월째 쓰고 있는데 발열이 심하지 않아요.", "작년 여름에 제주도에서 일주일을 보냈습니다.", "직접 입어보고 나서 사이즈를 골랐어요.", "어제 새로 나온 앱을 설치해서 써봤는데 속도가 빠르네요.",
    "친구한테 추천받아서 샀는데 만족합니다.", "여러 번 먹어 본 결과 이 제품이 제일 맛있었어요.", "두 달 동안 매일 복용했더니 피로가 줄었습니다.", "공식 매장에 직접 가서 상담을 받았습니다.",
    "점원이 신제품을 추천해 주었어요.", "오늘 아침에 일찍 도착했더니 대기가 없었습니다.", "이 방법으로 월 50만 원을 벌고 있습니다.", "제 친구도 이 방법을 따라 해서 성공했습니다.",
    "지난주 일요일에 가족과 함께 체험해 봤습니다.", "써보면서 느낀 점은 배터리가 오래 간다는 것입니다.", "사용하면서 불편한 점은 없었습니다.", "리뷰를 위해 제품을 제공받아 사용했습니다.",
    "주문하고 이틀 만에 받았습니다.", "이용해 보신 분들의 후기가 좋아서 저도 가입했어요.", "저는 이 브랜드를 5년 넘게 써 왔습니다.", "샤워기를 교체해 봤더니 수압이 확 달라졌어요.",
    "카페에 들어서자마자 커피 향이 가득했습니다.", "호텔 직원이 체크인을 도와줬습니다.", "한 달 전에 이 앱을 깔았고 지금도 잘 쓰고 있어요.",
)
OWN_PASSES = (
    "써 보시면 알겠지만 설정이 간단합니다.", "이 기능은 처음 쓰는 분도 쉽게 따라 할 수 있습니다.", "구매 전에 호환 여부를 확인하세요.", "배터리는 사용 환경에 따라 달라질 수 있습니다.", "방문 시간은 매장마다 다를 수 있습니다.",
    "직접 확인하기 어렵다면 고객센터에 문의해 보세요.", "후기를 참고할 때는 광고 표시 여부를 먼저 살펴봅니다.", "이 제품은 가볍고 휴대하기 편한 편입니다.", "장점은 가볍다는 점이고 단점은 가격입니다.",
    "많은 사용자가 만족한다고 알려져 있습니다.", "설치 후에는 재부팅이 필요합니다.", "처음 방문하는 분은 예약 방법을 먼저 확인하세요.", "사용 중에 이상이 있으면 즉시 중단하세요.", "먹어 보고 싶다면 소량부터 시도해 보세요.",
    "써본 사람만 알 수 있는 팁이라고 소개하는 글이 많지만 공식 자료로 확인합니다.", "이 글은 체험이 아니라 공개된 자료를 기준으로 작성했습니다.", "후기 작성 시 개인정보를 포함하지 마세요.", "제품을 받으면 구성품을 먼저 확인합니다.",
    "다녀온 뒤에는 영수증을 정리해 두면 좋습니다.", "이 글에서는 세 가지 방법을 비교해 보았습니다.", "단계별로 정리해 보니 핵심은 세 가지입니다.", "자주 묻는 질문을 모아 정리했습니다.", "두 제품의 차이를 표로 만들어 보았습니다.",
    "이 문제를 해결한 방법을 순서대로 안내합니다.", "공식 문서에서 확인한 내용을 바탕으로 작성했습니다.", "사람들이 흔히 겪는 문제를 먼저 짚어 봅니다.", "비용은 판매처마다 다르니 직접 확인하세요.", "예약은 전화나 앱으로 할 수 있습니다.",
)


class OwnExamplesTest(unittest.TestCase):
    """구현자가 따로 만든 새 예문 — 검증자 예문과 겹치지 않는다. 못 잡는 알려진 한계 한 가지: '다녀와서 사진을 정리했어요.'(글 쓰는 일을 가리키는 과거형과 겹친다)."""

    def test_every_own_violation_is_caught_and_no_own_pass_is_flagged(self):
        missed = [text for text in OWN_VIOLATIONS if not violated(text)]
        flagged = [text for text in OWN_PASSES if cl.find_violations(text)]
        self.assertEqual((missed, flagged), ([], []))
        self.assertGreaterEqual(len(OWN_VIOLATIONS), 23)
        self.assertGreaterEqual(len(OWN_PASSES), 28)

    def test_the_known_limit_is_still_a_limit_not_a_surprise(self):
        self.assertEqual(cl.find_violations("다녀와서 사진을 정리했어요."), ())


class BoundaryTest(unittest.TestCase):
    def test_a_marker_far_after_the_claim_does_not_excuse_it(self):
        text = "써봤는데 이번에는 정말 오랫동안 아주 만족스럽게 지냈고 다른 사람에게 권한다면 좋겠습니다."
        self.assertIn(USE, violated(text))
        self.assertEqual(cl.find_violations("써봤다면 이렇게 하세요."), (), "바로 뒤의 표지는 쓴다")

    def test_a_two_character_sentence_is_checked(self):
        self.assertIn(BUY, violated("샀다."))
        self.assertIn(BUY, violated("샀다"))
        self.assertEqual(cl.find_violations("네."), ())

    def test_single_literals_that_nothing_else_covers(self):
        self.assertIn(INCOME, violated("30만 원 벌었습니다."))
        self.assertIn(EFFECT, violated("소음이 확 줄어든 것을 체감했습니다."))
        self.assertIn(EFFECT, violated("사용 후 기분이 좋아졌어요."))

    def test_the_is_it_that_guard_passes_a_question_like_continuation(self):
        for text in ("직접 써봤는지 확인해 보세요.", "사용해 보니 어떠셨는지 댓글로 알려 주세요.", "방문해 봤는지 기록해 두세요."):
            with self.subTest(text=text):
                self.assertEqual(cl.find_violations(text), ())

    def test_a_digit_in_front_of_a_year_does_not_make_a_date(self):
        self.assertNotIn(cl.DATE, {claim.category for claim in cl.find_claims("주문번호 12019-3-4 확인")})
        self.assertIn(cl.DATE, {claim.category for claim in cl.find_claims("주문일 2019-3-4 확인")})
        self.assertNotIn(cl.DATE, {claim.category for claim in cl.find_claims("코드 112025년 표기")})

    def test_an_ellipsis_ends_a_sentence(self):
        self.assertEqual(cl.split_sentences("가나다… 라마바"), ["가나다…", "라마바"])
        self.assertEqual(cl.split_sentences("가나다…라마바"), ["가나다…라마바"])

    def test_only_the_first_three_past_forms_after_a_time_word_are_looked_at(self):
        text = "방문했을 때 정리했고 작성했고 소개했고 안내했고 줄이 길었습니다."
        self.assertNotIn(VISIT, violated(text), "앞의 세 곳이 모두 글 쓰는 일이면 뒤의 것은 보지 않는다(긴 글에서 늘어지지 않게)")
        self.assertIn(VISIT, violated("방문했을 때 정리했고 줄이 길었습니다."))

    def test_the_review_cap_holds_even_when_one_sentence_brings_several(self):
        many = "가격은 약 3만 원이고 2025년에 나왔고 약 2시간 걸리며 85%가 선택했습니다."
        sentences = ["가격은 약 3만 원입니다."] * 499 + [many] + ["가격은 약 3만 원입니다."] * 5
        found = cl.find_claims(sentences)
        self.assertEqual(len(found), cl.MAX_FINDINGS)
        self.assertEqual(found[-1].position, 499)
        self.assertEqual(len(cl.find_claims([many] * 400)), cl.MAX_FINDINGS)


class NoViolationIsEverDroppedTest(unittest.TestCase):
    PRICE_LINE = "가격은 약 3만 원입니다."
    CLAIM = "직접 써보니 좋았습니다."

    def test_a_violation_after_many_review_findings_is_still_found(self):
        for text in (" ".join([self.PRICE_LINE] * 600 + [self.CLAIM]), [self.PRICE_LINE] * 600 + [self.CLAIM], [self.PRICE_LINE] * 5000 + [self.CLAIM]):
            found = cl.find_violations(text)
            self.assertTrue(found, "위반이 상한에 밀려 사라졌다")
            self.assertEqual({claim.category for claim in found}, {USE, EFFECT})
            every = cl.find_claims(text)
            self.assertEqual(sum(1 for claim in every if not cl.is_violation(claim.category)), cl.MAX_FINDINGS)
            self.assertTrue({claim.category for claim in every} >= {USE, EFFECT})

    def test_only_the_reviews_are_capped(self):
        reviews = cl.find_claims(" ".join([self.PRICE_LINE] * 2000))
        self.assertEqual(len(reviews), cl.MAX_FINDINGS)
        self.assertEqual(cl.MAX_FINDINGS, 500)
        flagged = cl.find_violations(" ".join([self.CLAIM] * 2000))
        self.assertEqual({claim.position for claim in flagged}, set(range(2000)))
        self.assertGreaterEqual(len(flagged), 2000)

    def test_violations_in_between_the_reviews_keep_their_positions(self):
        sentences = [self.PRICE_LINE] * 700
        sentences[650] = self.CLAIM
        sentences[699] = "방문했을 때 줄이 길었습니다."
        found = cl.find_violations(sentences)
        self.assertEqual(sorted({claim.position for claim in found}), [650, 699])


class NoHiddenCharactersInSourceTest(unittest.TestCase):
    """새 소스·시험 파일에는 눈에 안 보이는 글자·글자 방향 제어·줄 구분 문자가 날것으로 들어 있지 않다 — 필요하면 이스케이프 표기(역슬래시 u 와 번호)로 적는다(편집기가 지우거나 코드 검사 도구가 의심하지 않게)."""
    FILES = ("src/chanceblog_desktop/check/claims.py", "src/chanceblog_desktop/content/draft_options.py", "src/chanceblog_desktop/content/post_types.py", "src/chanceblog_desktop/content/draft_plan.py",
             "src/chanceblog_desktop/service/draft.py", "tests/test_check_claims.py", "tests/test_check_claims_regression.py", "tests/test_content_draft_options.py", "tests/test_content_draft_plan.py",
             "tests/test_content_post_types.py", "tests/test_service_draft.py", "tests/test_service_draft_process.py")
    FILLERS = frozenset(chr(code) for code in (0x3164, 0xFFA0, 0x115F, 0x1160, 0x2800))
    ALLOWED = frozenset(chr(code) for code in (10, 13, 9))

    def test_no_raw_invisible_or_bidi_or_line_separator_characters(self):
        import unicodedata
        root = Path(__file__).resolve().parent.parent
        for name in self.FILES:
            text = (root / name).read_text(encoding="utf-8")
            bad = sorted({hex(ord(ch)) for ch in text if ch not in self.ALLOWED and (ch in self.FILLERS or unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"))})
            with self.subTest(file=name):
                self.assertEqual(bad, [])
                self.assertEqual(len(text.splitlines()), len(text.split(chr(10))) - (1 if text.endswith(chr(10)) else 0), "줄 구분 문자가 섞여 줄 수가 달라진다")


if __name__ == "__main__":
    unittest.main()
