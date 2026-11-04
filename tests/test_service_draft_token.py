"""`draft plan` 선택 입력의 긴 무작위 영숫자 거절 시험(`service/draft.py` 의 `looks_like_a_token`·`refuse_long_tokens`) — 가리기 규칙이 모르는 모양 없는 키가 계획 출력에 나가지 않는다.

지키는 것:
  1) 영문자와 숫자가 함께 든 영숫자 24자 이상·`\\uXXXX` 이스케이프를 이은 글·`+`/`/` 가 든 base64 덩어리·`-`/`_` 가 드문 base64url 덩어리가 글칸 아홉 곳(전하고 싶은 내용·경험·의견·독자층·제목 방향·결론·
     반드시 포함할 문장·제외할 내용·가격이나 날짜) 어디에 어떤 모양으로 들어 있어도 거절되고(`DRAFT_OPTION_INVALID`, 종료 코드 1) 입력한 글은 화면·`--json`·`--verbose` 어디에도 없다.
  2) **정상 글은 거의 거절하지 않는다** — 새로 쓴 정상 입력 200개(모델명·파일 이름·주소 조각·날짜·가격·명령어·한국어 문장 …, 사람이 쓴 100개 + 낱말 × 틀로 만든 100개)를 하나도 거절하지 않고,
     거절하는 것은 32·40자 해시를 적은 문장(키와 구분할 수 없다)뿐이다 — 그 둘을 더한 202개 중 2개(1.0%). `security/shape.looks_secret` 을 그대로 쓰면 같은 정상 입력 202개 중 68개(33.7%)를 거절해서 쓰지 않았다.
  3) 주소 칸은 이 규칙을 받지 않는다(주소 경로의 번호·이름은 정상이다 — 주소 칸의 비밀 검사는 `content/draft_options.py` 가 따로 한다).
  4) 알려 둔 한계를 시험이 못박는다 — 짧은 키(8~17자)·20자씩 둘로 나눈 키는 모양만으로 구분할 수 없어 받는다.
가짜 키는 실행할 때 무작위(고정 시드)로 만든다. 네트워크·실제 비밀 없이 돈다.
"""
import base64
import random
import string
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import draft_options as do  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import draft  # noqa: E402

ALNUM = string.ascii_letters + string.digits
URLSAFE = ALNUM + "_-"
HEX = "0123456789abcdef"
FREE_OPTIONS = (("--message", "message"), ("--experience", "experience"), ("--opinion", "opinion"), ("--audience", "audience"), ("--title-direction", "title_direction"), ("--conclusion", "conclusion"),
                ("--must-include", "must_include"), ("--exclude", "exclude"), ("--price-date", "price_date"))


class Maker:
    def __init__(self, seed):
        self.rnd = random.Random(seed)

    def text(self, length, alphabet=ALNUM):
        while True:
            value = "".join(self.rnd.choice(alphabet) for _ in range(length))
            if any(ch.isdigit() for ch in value) and any(ch.islower() for ch in value) and any(ch.isupper() for ch in value):
                return value

    def hexa(self, length):
        return "".join(self.rnd.choice(HEX) for _ in range(length))


def canaries():
    """(이름, 친 글, 알맹이) — 모양 없는 긴 무작위 영숫자의 여러 꼴."""
    maker = Maker(20261104)
    found = []

    def add(kind, value, core=None):
        found.append((kind, value, value if core is None else core))

    for size in (24, 25, 32, 40, 64, 100):
        add(f"alnum{size}", maker.text(size))
    add("hex32", maker.hexa(32))
    add("hex48", maker.hexa(48))
    core = maker.text(43, URLSAFE); add("urlsafe43", core)
    core = maker.text(60, URLSAFE); add("urlsafe60", core)
    core = base64.b64encode(bytes(maker.rnd.randrange(256) for _ in range(36))).decode(); add("base64-48", core)
    core = "".join(maker.rnd.choice(ALNUM) for _ in range(20)) + "+" + "".join(maker.rnd.choice(ALNUM) for _ in range(30)) + "="; add("base64-plus", core)
    core = maker.text(22) + "/" + maker.text(22) + "/" + maker.text(8); add("base64-slashes", core)
    core = maker.text(24); add("escapes", "".join("\\u%04x" % ord(ch) for ch in core), core)
    core = maker.text(40); add("hangul-around", "비밀키는" + core + "입니다", core)
    core = maker.text(40); add("double-quoted", '"' + core + '"', core)
    core = maker.text(36); add("comma-after", core + ",다음", core)
    core = maker.text(36); add("dash-before", "-" + core, core)
    core = maker.text(36); add("tab-before", "\t" + core, core)
    core = maker.text(30); add("percent", core + "%21%40%23", core)
    core = maker.text(40); add("inside-a-sentence", "저장한 값은 " + core + " 이고 다시 쓰지 않습니다.", core)
    return found


CANARIES = canaries()

BY_HAND = (
    "겨울철 난방비를 줄이는 방법을 중심으로 전기장판과 보일러 사용량을 비교해 주세요.", "독자는 30대 직장인이고 퇴근 후에 짧게 읽을 수 있는 글이면 좋겠습니다.", "제목은 질문형으로 하되 너무 길지 않게 부탁드립니다.",
    "결론은 이번 달부터 바로 해 볼 수 있는 세 가지 행동으로 정리해 주세요.", "광고처럼 보이는 표현과 과장된 효과 표현은 빼 주세요.", "가격은 2026년 11월 기준으로 직접 확인한 1,299,000원입니다.",
    "삼성 갤럭시 S25 울트라 512GB 모델과 아이폰 16 프로 맥스 256GB 모델을 비교합니다.", "모델명은 SM-S938N-512GB-Titanium-Black 이고 색상은 티타늄 블랙입니다.", "NVIDIA GeForce RTX 4090 24GB 와 RTX 4080 Super 16GB 의 가격 차이를 다룹니다.",
    "서울 성수동 카페 거리를 걸으며 다섯 곳을 둘러본 일정입니다.", "제주 서귀포시 올레길 7코스 약 15.1km 를 4시간 정도 걸었습니다.", "회의록 파일 이름은 2026-11-04-weekly-meeting-notes-final-version.md 입니다.",
    "참고 문서는 https://example.com/guide/winter-heating-cost-saving-tips-2026 입니다.", "공식 안내 페이지 https://www.example.org/notice/2026/11/04/energy-support-program 를 참고했습니다.",
    "세션 식별자 550e8400-e29b-41d4-a716-446655440000 은 로그에서 찾았습니다.", "git checkout -b feature/winter-heating-guide 로 새 가지를 만들어 작성합니다.", "pip install scikit-learn 과 numpy 를 설치한 뒤 예제를 실행합니다.",
    "docker compose up -d 로 개발 환경을 띄우는 과정을 보여 주세요.", "SELECT name, price FROM products WHERE stock > 0 ORDER BY price DESC LIMIT 10; 쿼리를 설명합니다.", "환경 변수 PATH 에 /usr/local/bin 을 추가하는 방법을 포함해 주세요.",
    "경로 C:/Users/example/Documents/blog/drafts 에 초안을 저장했습니다.", "SKU-12345-AB 상품과 SKU-67890-CD 상품의 재고를 비교한 표를 넣어 주세요.", "주문번호 ORD-2026-1104-0001 로 문의한 사례는 빼 주세요.",
    "ISBN 978-3-16-148410-0 책을 소개하는 부분을 넣어 주세요.", "배송은 CJ대한통운으로 3일 걸렸고 송장번호는 따로 적지 않습니다.", "운동 기록은 주 3회 5km 달리기이고 평균 페이스는 6분 30초입니다.",
    "독서 모임에서 읽은 책은 소설 두 권과 에세이 한 권입니다.", "다음 글에서는 연말정산 공제 항목 중 놓치기 쉬운 것들을 다룰 예정입니다.", "대출 금리 인상이 월 상환액에 미치는 영향을 계산 예시와 함께 보여 주세요.",
    "초보자도 따라 할 수 있도록 단계마다 사진 설명이 들어가면 좋겠습니다.", "마지막 문단에서는 이번 글의 핵심을 한 줄로 요약해 주세요.", "이 글은 직접 겪은 후기가 아니라 공개된 자료를 정리한 안내 글입니다.",
    "블로그 말투는 부드러운 존댓말로 하고 이모티콘은 쓰지 않습니다.", "소제목은 다섯 개 이내로 하고 각 소제목 아래 두세 문단을 넣어 주세요.", "비교 표에는 월 요금, 약정 기간, 데이터 제공량을 꼭 넣어 주세요.",
    "알뜰폰과 통신 3사 요금제의 차이를 표 하나로 정리합니다.", "SK텔레콤과 KT, LG유플러스의 5G 요금제를 같은 기준으로 비교합니다.", "SK하이닉스 HBM4 양산 일정에 관한 공식 발표 내용만 인용해 주세요.",
    "에너지 효율 1등급 냉장고와 2등급 냉장고의 전기요금 차이를 계산합니다.", "Apple Watch Series 10 과 Galaxy Watch 7 의 배터리 지속 시간을 비교합니다.", "Wi-Fi 6E 공유기와 Wi-Fi 7 공유기의 속도 차이를 쉽게 풀어 설명해 주세요.",
    "USB-C 케이블 규격(USB 3.2 Gen 2x2)과 충전 와트 수를 정리합니다.", "에어프라이어 레시피는 닭봉 12개, 소금 한 꼬집, 후추 약간으로 간단히 씁니다.", "청소기 필터 교체 주기는 제조사 안내에 따라 3개월마다라고 적어 주세요.",
    "아이와 함께 가기 좋은 주말 나들이 장소 열 곳을 소개합니다.", "캠핑장 예약은 매월 1일 오전 10시에 열리고 경쟁이 치열하다는 점을 알려 주세요.", "겨울 이불 세탁법은 세탁망 사용과 약한 탈수를 핵심으로 적어 주세요.",
    "방한용품 가격대는 1만 원대, 3만 원대, 5만 원대로 나누어 보여 주세요.", "한글 파일(HWP)을 PDF 로 바꾸는 방법과 글꼴이 깨질 때 해결법을 포함합니다.", "엑셀 VLOOKUP 과 XLOOKUP 함수의 차이를 예제 데이터 20행으로 설명해 주세요.",
    "파워포인트 발표 자료는 슬라이드 15장 이내로 줄이는 요령을 다룹니다.", "Python 3.12 의 f-string 개선점과 type 힌트 변화를 간단히 소개합니다.", "JavaScript 의 async/await 와 Promise.all 을 비교하는 예제를 넣어 주세요.",
    "Kubernetes 클러스터를 처음 만들 때 필요한 최소 구성을 설명합니다.", "AWS S3 버킷 정책에서 퍼블릭 접근을 막는 설정 화면을 단계별로 설명해 주세요.", "CSS Grid 와 Flexbox 중 어느 쪽이 레이아웃에 더 알맞은지 사례로 비교합니다.",
    "SEO 제목은 60자 이내, 설명은 160자 이내로 맞춰 주세요.", "해시태그는 #겨울난방 #절약팁 #전기장판 세 개만 쓰겠습니다.", "인용은 출처를 밝히고 두 줄을 넘지 않게 해 주세요.",
    "숫자는 반올림하지 말고 자료에 있는 값 그대로 쓰겠습니다.", "날짜는 2026-11-04 형식으로 통일하고 시간은 24시간제로 적습니다.", "연락처는 글에 넣지 않고 문의는 댓글로만 받는다고 안내해 주세요.",
    "이미지는 직접 찍은 사진만 쓰고 출처 표기가 필요한 이미지는 쓰지 않습니다.", "글 길이는 공백 제외 2,000자 안팎, 소제목은 네 개로 구성해 주세요.", "도입부는 독자가 자주 하는 질문 하나로 시작해 주세요.",
    "마무리에는 다음 글 예고를 한 문장 넣어 주세요.", "금액 표기는 1,500원, 12,000원, 250,000원처럼 쉼표를 넣어 주세요.", "온도는 영하 5도에서 영상 3도 사이라고 적어 주세요.",
    "소비전력은 정격 800W, 절전 모드 5W 라고 제품 설명서에 나와 있습니다.", "버전 2.4.1 에서 고쳐진 문제와 알려진 한계를 구분해서 적어 주세요.", "릴리스 후보 rc-2026-11-04-build-117 은 시험을 모두 통과했다고 합니다.",
    "송장 INV-2026-000123 의 납기일은 11월 30일입니다.", "전화 상담은 평일 오전 9시부터 오후 6시까지라는 점을 안내합니다.", "이메일 문의는 영업일 기준 이틀 안에 답변한다고 적혀 있습니다.",
    "회원 등급은 일반, 우수, VIP 세 단계이고 기준은 연간 구매 금액입니다.", "세탁기 용량은 21kg, 건조기 용량은 17kg 이고 둘 다 에너지 효율 1등급입니다.", "자동차 보험료는 만 26세 이상, 무사고 3년 기준으로 비교합니다.",
    "전세 계약 전 등기부등본과 확정일자를 확인하라는 내용을 꼭 넣어 주세요.", "건강 정보는 의사의 진단을 대신하지 않는다는 문구를 마지막에 넣어 주세요.", "투자 관련 내용은 수익을 보장하지 않는다는 점을 분명히 밝혀 주세요.",
    "제외할 내용은 정치 이야기와 특정 업체 비방입니다.", "반드시 포함할 문장은 이 글의 정보는 작성 시점 기준이라는 안내입니다.", "참고 자료는 정부 공식 누리집과 제조사 설명서 두 가지만 씁니다.",
    "독자층은 처음 캠핑을 준비하는 부부와 아이 한 명 가족입니다.", "제목 방향은 숫자를 넣어 구체적으로, 예를 들어 다섯 가지 방법처럼 해 주세요.", "맛집 소개는 메뉴 이름과 가격만 적고 평가는 넣지 않겠습니다.",
    "여행 경비는 교통비 4만 원, 숙박비 12만 원, 식비 6만 원입니다.", "KTX 서울에서 부산까지 약 2시간 40분, 일반실 요금은 59,800원입니다.", "인천공항 제2터미널에서 시내까지 공항철도로 약 60분 걸립니다.",
    "오전 6시 30분 기상, 7시 아침 식사, 8시 출발 순서로 일정을 적습니다.", "에어컨 필터 청소 주기는 2주에 한 번, 필터 모델은 AC-F1200 이라고 적어 주세요.", "배터리 용량 5,000mAh, 충전 속도 45W, 무게 197g 이라는 사양만 인용합니다.",
    "한국 시각 2026-11-04 21:30 기준으로 확인한 내용이라고 밝혀 주세요.", "블로그 카테고리는 생활 정보, 재테크, 여행 세 가지입니다.", "비교 대상은 A 요금제(월 33,000원)와 B 요금제(월 45,000원)입니다.",
    "해외 직구 관세는 150달러를 넘으면 부과된다는 점을 안내합니다.", "iPhone15ProMax 와 GalaxyS24Ultra 의 카메라 성능을 같은 조건에서 비교합니다.", "인터넷 속도 측정 결과는 다운로드 940Mbps, 업로드 880Mbps 였습니다.",
    "ChatGPT 와 Gemini 같은 AI 도구를 쓰는 방법을 정리하되 특정 제품 홍보는 피해 주세요.", "Wi-Fi 비밀번호 대신 QR 코드로 손님에게 접속 방법을 알려 주는 팁을 넣어 주세요.",
)
SUBJECTS = ("난방비 절약", "알뜰폰 요금제", "캠핑 장비", "연말정산", "노트북 고르기", "제주 여행", "전기차 충전", "집밥 레시피", "운동 습관", "독서 모임")
TOKENS = ("Galaxy-S25-Ultra-512GB-Titanium", "RTX-4090-Founders-Edition-24GB", "iPhone16ProMax256GB", "SM-S938N-512GB", "model-2026-11-04-final-release-candidate",
          "https://example.com/blog/2026/11/winter-heating-guide", "v2.4.1-hotfix-20261104", "INV-2026-000123-B", "feature/winter-heating-guide-v2", "KR-2026-ENERGY-SUPPORT-0042")
TEMPLATES = (
    "{s} 글에서 모델명 {t} 을 한 번만 언급해 주세요.", "{s} 관련 참고 문서 이름은 {t} 입니다.", "{s} 를 다룰 때 {t} 같은 표기는 그대로 옮겨 적습니다.",
    "{s}: 제품 코드 {t} 가 들어간 문장은 따옴표로 묶어 주세요.", "{s} 글의 폴더 이름은 {t} 로 정했습니다.", "{s} 자료 {t} 의 날짜와 버전을 본문에 밝혀 주세요.",
    "{s} 에 대한 메모 — {t} 는 예시일 뿐 실제 상품이 아닙니다.", "{s} 포스팅 초안 파일은 {t}.md 로 저장합니다.", "{s} 를 설명하는 표에 {t} 행을 넣어 주세요.", "{s} 주제의 태그 후보는 {t} 와 일상 기록입니다.",
)
HASH_SENTENCES = ("커밋 3f2a9c1d7e4b5a6c8d9e0f1a2b3c4d5e6f7a8b9c 의 변경 내용을 설명하는 글입니다.", "파일의 MD5 해시 d41d8cd98f00b204e9800998ecf8427e 는 빈 파일의 값입니다.")


def generated():
    return [template.format(s=subject, t=TOKENS[(index + number) % len(TOKENS)]) for number, template in enumerate(TEMPLATES) for index, subject in enumerate(SUBJECTS)]


NORMAL = BY_HAND + tuple(generated())


def options_with(name, value):
    if name in ("must_include", "exclude", "price_date"):
        return do.DraftOptions(**{name: (value,)})
    return do.DraftOptions(**{name: value})


class TokenShapeTest(unittest.TestCase):
    def test_every_long_random_form_is_a_token(self):
        for kind, value, _core in CANARIES:
            with self.subTest(kind=kind):
                self.assertTrue(draft.looks_like_a_token(value))

    def test_the_boundaries_of_each_rule(self):
        maker = Maker(5)
        for size, expected in ((23, False), (24, True), (25, True)):
            self.assertIs(draft.looks_like_a_token(maker.text(size)), expected, size)
        self.assertFalse(draft.looks_like_a_token("a" * 60), "영문자만이면 글이다")
        self.assertFalse(draft.looks_like_a_token("1" * 60), "숫자만이면 번호다")
        self.assertTrue(draft.looks_like_a_token("a" * 30 + "1"))
        self.assertTrue(draft.looks_like_a_token("\\u0061" * 6))
        self.assertFalse(draft.looks_like_a_token("\\u0061" * 5), "이스케이프는 여섯 번부터")
        self.assertFalse(draft.looks_like_a_token("회사 \\u0061 와 \\u0062 표기를 설명합니다."))
        self.assertFalse(draft.looks_like_a_token("Users/example/Documents/blog/drafts/2026/WinterGuideFinal/images"), "경로는 글이다(대문자·소문자·숫자가 있어도 소문자가 훨씬 많아 무작위로 보이지 않는다)")
        long_path = "docs/Guide/Getting/Started/With/The/New/Dashboard/Version2/Release/Notes/Final"
        self.assertFalse(draft.looks_like_a_token(long_path), "긴 경로도 소문자가 훨씬 많아 글이다")
        self.assertFalse(draft.looks_like_a_token("Samsung-Galaxy-S25-Ultra-512GB-Titanium-Black-Limited-Edition"), "붙임표가 잦은 이름은 글이다")
        self.assertFalse(draft.looks_like_a_token("Understanding-Home-Heating-Costs-In-Winter-2026-Complete-Guide"))
        self.assertTrue(draft.looks_like_a_token(Maker(9).text(43, URLSAFE)))

    def test_a_base64url_key_cut_by_dashes_is_found_by_its_own_rule_and_a_dashed_name_is_not(self):
        """영숫자만 24자 규칙에는 안 걸리게(조각이 11자씩) 자른 base64url 모양 — `-`·`_` 가 드물고(8글자에 하나 이하) 무작위로 보이는 40자 이상 덩어리 규칙만 잡는다."""
        pieces = ("aB3dE5fG7hI", "9jK1lM3nO5p", "Qr7St9Uv1Wx", "Yz3Ab5Cd7Ef", "Gh9Ij1Kl3Mn")
        value = "-".join(pieces[:2]) + "_" + "-".join(pieces[2:])
        self.assertEqual(max(len(run) for run in value.replace("-", " ").replace("_", " ").split()), 11)
        self.assertGreaterEqual(len(value), 40)
        self.assertTrue(draft.looks_like_a_token(value))
        self.assertTrue(draft.looks_like_a_token("키는 " + value + " 입니다"))
        dense = "-".join(("aB3dE", "5fG7h", "I9jK1", "lM3nO", "5pQr7", "St9Uv", "1Wx3Y", "z5Ab7", "Cd9Ef"))              # 붙임표가 5글자마다 — 낱말을 붙임표로 이은 이름이다
        self.assertGreaterEqual(len(dense), 40)
        self.assertFalse(draft.looks_like_a_token(dense))
        self.assertFalse(draft.looks_like_a_token(value[:39]), "40자 미만이다")

    def test_a_value_that_is_not_text_is_not_trusted(self):
        for value in (None, 5, b"abc", ["a"], object()):
            with self.subTest(kind=type(value).__name__):
                self.assertTrue(draft.looks_like_a_token(value))


class RefusalTest(unittest.TestCase):
    def test_every_shape_in_every_free_text_slot_is_refused_without_the_value(self):
        count = 0
        for kind, value, core in CANARIES:
            for option, name in FREE_OPTIONS:
                with self.subTest(kind=kind, slot=name):
                    try:
                        options = options_with(name, value)
                    except AppError:
                        continue                                            # 선택 입력 자체의 검사가 먼저 거절한 것(길이·눈에 안 보이는 글자 …)은 어느 쪽이든 거절이다
                    with self.assertRaises(AppError) as caught:
                        draft.refuse_long_tokens(options)
                    error = caught.exception
                    self.assertEqual(error.code, "DRAFT_OPTION_INVALID")
                    self.assertEqual(error.slots["항목"], do.LABELS[name])
                    shown = error.rendered()
                    self.assertNotIn(core[:8], shown.message + shown.action + error.detail + error.log_line())
                    count += 1
        self.assertGreater(count, 150, "거의 모든 모양·칸을 시험한다")

    def test_the_command_refuses_with_exit_code_one_and_prints_none_of_it_in_any_output_form(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            ctx = ss.make_ctx(tmp)
            code, out, err = ss.run_cli(ctx, "candidates", "add", "--topic", "겨울 난방비", "--keyword", "난방비", "--blog", "github_pages")
            self.assertEqual(code, 0, (out, err))
            for kind, value, core in CANARIES:
                for option, _name in FREE_OPTIONS[:3] + FREE_OPTIONS[6:7]:
                    for extra in ((), ("--json",), ("--verbose",)):
                        with self.subTest(kind=kind, option=option, extra=extra):
                            code, out, err = ss.run_cli(ctx, "draft", "plan", "1", f"{option}={value}", *extra)
                            self.assertEqual(code, 1, (out, err))
                            self.assertIn("DRAFT_OPTION_INVALID", out + err)
                            self.assertNotIn(core[:8], out + err)
                            self.assertNotIn(core[-8:], out + err)
            code, out, err = ss.run_cli(ctx, "draft", "plan", "1", "--message", "겨울철 난방비를 줄이는 방법 중심으로 써 주세요.")
            self.assertEqual((code, err), (0, ""), "정상 입력은 그대로 계획이 만들어진다")

    def test_the_reason_is_the_plain_sentence_and_names_the_slot(self):
        with self.assertRaises(AppError) as caught:
            draft.refuse_long_tokens(do.DraftOptions(experience=CANARIES[3][1]))
        shown = caught.exception.rendered()
        self.assertIn("실제 사용 경험", shown.message)
        self.assertIn("24자 이상 이어진", shown.message)
        self.assertIn("앞 몇 글자만 적거나", shown.message)

    def test_the_address_slot_is_not_checked_by_this_rule(self):
        options = do.DraftOptions(urls=("https://www.notion.so/My-Page-8f3c2a1d9e7b4c6a8d0e1f2a3b4c5d6e", "https://example.com/watch/" + "a1b2c3d4e5" * 4))
        draft.refuse_long_tokens(options)                                    # 예외 없음
        self.assertEqual(len(options.urls), 2)


class NormalInputsTest(unittest.TestCase):
    def test_there_are_two_hundred_distinct_normal_inputs(self):
        self.assertEqual(len(set(NORMAL)), len(NORMAL))
        self.assertEqual(len(BY_HAND), 100)
        self.assertEqual(len(generated()), 100)
        self.assertEqual(len(NORMAL), 200)
        self.assertEqual(len(HASH_SENTENCES), 2)

    def test_not_one_normal_input_is_refused_by_this_rule_in_any_of_the_nine_slots(self):
        """이 규칙이 거절하는 정상 입력의 수 — 선택 입력 자체의 길이 한도(제외할 내용 60자·독자층 100자 …)에 걸리는 것은 이 규칙의 일이 아니라서 그 칸에는 넣어 보지 않는다."""
        refused, tried = [], 0
        for text in NORMAL:
            self.assertFalse(draft.looks_like_a_token(text), text)
            for _option, name in FREE_OPTIONS:
                try:
                    options = options_with(name, text)
                except AppError:
                    continue
                tried += 1
                try:
                    draft.refuse_long_tokens(options)
                except AppError as error:
                    refused.append((error.code, name, text[:20]))
        self.assertEqual(refused, [], f"{len(refused)}건")
        self.assertGreater(tried, 1000, "칸마다 길이 한도가 달라 넣어 본 짝이 너무 적으면 이 시험이 아무것도 못 본다")

    def test_only_a_sentence_with_a_full_hash_is_refused_and_that_is_the_known_limit(self):
        """32·40자 해시는 무작위 키와 모양이 같아 구분할 수 없다 — 정상 입력 202개 중 이 둘(1.0%)만 거절한다. 앞 몇 글자만 적도록 안내한다."""
        for text in HASH_SENTENCES:
            with self.assertRaises(AppError) as caught:
                draft.refuse_long_tokens(do.DraftOptions(message=text))
            self.assertIn("번호나 해시라면 앞 몇 글자만", caught.exception.rendered().message)
        self.assertEqual(len([text for text in NORMAL + HASH_SENTENCES if draft.looks_like_a_token(text)]), 2)

    def test_the_whole_command_still_makes_a_plan_for_a_normal_input(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            ctx = ss.make_ctx(tmp)
            self.assertEqual(ss.run_cli(ctx, "candidates", "add", "--topic", "겨울 난방비", "--keyword", "난방비", "--blog", "github_pages")[0], 0)
            for text in NORMAL[::40]:
                with self.subTest(text=text[:20]):
                    code, out, err = ss.run_cli(ctx, "draft", "plan", "1", "--message", text)
                    self.assertEqual((code, err), (0, ""), (out, err))


class KnownLimitsTest(unittest.TestCase):
    """알려 둔 한계 — 모양만으로는 정상 글과 구분할 수 없는 짧은 키는 받는다(문서의 한계 문장과 같은 사실)."""

    def test_short_keys_and_keys_split_in_two_pass(self):
        maker = Maker(21)
        for kind, value in (("8자", maker.text(8)), ("16자", maker.text(16)), ("17자", maker.text(17, URLSAFE)), ("20자 둘", maker.text(20) + " " + maker.text(20)), ("23자", maker.text(23))):
            with self.subTest(kind=kind):
                self.assertFalse(draft.looks_like_a_token(value))


if __name__ == "__main__":
    unittest.main()
