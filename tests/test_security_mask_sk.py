"""`sk-` 로 시작하는 새 키 모양 시험(`security/mask.py`) — OpenAI 프로젝트 키(`sk-proj-…`)·Anthropic 키(`sk-ant-api03-…`)·OpenRouter 키(`sk-or-v1-…`)와 그 밖의 `sk-` 긴 모양이 가려진다.

지키는 것:
  1) 세 모양 × 여러 길이 × 이웃(한글 조사·괄호·따옴표·줄바꿈·밑줄 뒤·주소·JSON) — 통째로 가려지고(조각이 안 남고) 다시 가려도 같으며 `has_key_shape`·`shape.looks_secret` 도 키로 본다.
  2) 꼬리 길이 경계(접두사만 있거나 모자라면 키가 아니다)·접두사가 낱말 속(`desk-proj-…`)이면 키가 아니다.
  3) **정상 글은 그대로다** — 새로 쓴 정상 문장 200개(한국어·영어·주소·낱말·코드·번호 …, 사람이 쓴 100개 + 낱말 × 틀로 만든 100개)를 하나도 바꾸지 않는다. 앞선 규칙을 못 맞출 문장은 이 목록에 없다.
  4) 마스크가 아는 모든 키 모양을 `shape.looks_secret`(키·이름 칸의 자기 검사)도 안다 — 두 곳이 어긋나 한쪽만 아는 모양이 생기지 않게 시험이 일치를 지킨다(`looks_secret` 이 더 넓다).
  5) 입력 길이에 선형이다(`sk-aa-` 를 몇만 번 이어도 제곱으로 느려지지 않는다). 앱 안에서도 가려진다 — `draft plan` 칸은 거절하고 `candidates` 화면은 가린다.
가짜 키는 실행할 때 조각을 이어 만든다(저장소의 시험이 `.py` 안의 키 모양 글을 막는다). 네트워크·실제 비밀 없이 돈다.
"""
import random
import string
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.security import mask as mk  # noqa: E402
from chanceblog_desktop.security import shape  # noqa: E402
from chanceblog_desktop.security.mask import has_key_shape, mask  # noqa: E402

URLSAFE = string.ascii_letters + string.digits + "_-"
HEX = "0123456789abcdef"
SK = "s" + "k-"                                                       # 조각을 이어 저장소에 키 모양 글이 없게 한다


def tail(seed, length, alphabet=URLSAFE):
    rnd = random.Random(seed)
    while True:
        text = "".join(rnd.choice(alphabet) for _ in range(length))
        if alphabet is HEX or (any(ch.isdigit() for ch in text) and any(ch.isupper() for ch in text) and any(ch.islower() for ch in text)):
            return text


def project_key(length=74, seed=1):
    return SK + "proj-" + tail(seed, length)


def anthropic_key(length=93, seed=2, kind="api03"):
    return SK + "ant-" + kind + "-" + tail(seed, length)


def openrouter_key(length=64, seed=3):
    return SK + "or-v1-" + tail(seed, length, HEX)


SHAPES = {
    "OpenAI 프로젝트 키": [project_key(length, seed) for seed, length in enumerate((20, 48, 74, 156, 300), start=10)],
    "Anthropic 키": [anthropic_key(length, seed, kind) for seed, (length, kind) in enumerate(((20, "api03"), (93, "api03"), (93, "api04"), (60, "admin01"), (120, "sid01"), (50, "oat01")), start=20)],
    "OpenRouter 키": [openrouter_key(length, seed) for seed, length in enumerate((20, 40, 64, 100), start=30)],
}
CONTEXTS = {
    "단독": "{k}", "뒤 조사": "{k}를 쓰세요", "앞 한글": "키{k}", "한글 사이": "키는{k}입니다", "괄호": "({k})", "따옴표": '"{k}"', "작은따옴표": "'{k}'", "쉼표": "{k},끝", "마침표": "{k}.",
    "줄바꿈 앞뒤": "앞 줄\n{k}\n뒷 줄", "줄 끝": "앞 줄\n키는 {k}", "줄 처음": "{k}\n뒷 줄", "대괄호": "[{k}]", "공백": "키는 {k} 입니다", "밑줄 뒤": "KEY_{k}", "등호 뒤": "KEY={k}",
    "주소 인자": "https://example.com/a?v={k}&x=1", "JSON": '{"api": "{k}", "n": 1}', "탭": "\t{k}\t", "윈도 줄바꿈": "앞\r\n{k}\r\n뒤", "백틱": "`{k}`", "마크다운 링크": "[설명]({k})",
}


def fragments(secret, size=12):
    return {secret[index:index + size] for index in range(0, max(len(secret) - size + 1, 1), 5)} | {secret[:size], secret[-size:], secret[len(secret) // 2:len(secret) // 2 + size]}


class NewShapesAreMaskedTest(unittest.TestCase):
    def test_every_shape_and_length_in_every_context_is_masked_completely(self):
        count = 0
        for label, secrets in SHAPES.items():
            for secret in secrets:
                for name, context in CONTEXTS.items():
                    text = context.replace("{k}", secret)
                    masked = mask(text)
                    count += 1
                    with self.subTest(label=label, length=len(secret), context=name):
                        self.assertIn(f"[가림: {label}]", masked)
                        self.assertFalse([piece for piece in fragments(secret) if piece in masked], masked)
                        self.assertEqual(mask(masked), masked, "이미 가린 글을 다시 가려도 같다")
                        self.assertTrue(has_key_shape(text))
        self.assertEqual(count, sum(len(items) for items in SHAPES.values()) * len(CONTEXTS))
        self.assertEqual(count, 15 * 22, "세 모양 15가지 길이 × 이웃 22가지")

    def test_the_label_and_the_words_around_the_key_are_kept(self):
        self.assertEqual(mask("키는" + project_key() + "입니다"), "키는[가림: OpenAI 프로젝트 키]입니다")
        self.assertEqual(mask("(" + anthropic_key() + ")"), "([가림: Anthropic 키])")
        self.assertEqual(mask(openrouter_key() + "를 쓰세요"), "[가림: OpenRouter 키]를 쓰세요")
        self.assertEqual(mask("앞 줄\n" + anthropic_key() + "\n뒷 줄"), "앞 줄\n[가림: Anthropic 키]\n뒷 줄")
        self.assertEqual(mask(project_key() + " 와 " + openrouter_key()), "[가림: OpenAI 프로젝트 키] 와 [가림: OpenRouter 키]")

    def test_two_keys_stuck_together_or_listed_are_both_masked(self):
        text = project_key(seed=41) + "," + anthropic_key(seed=42) + " " + openrouter_key(seed=43)
        masked = mask(text)
        self.assertEqual(masked.count("[가림"), 3)
        for secret in (project_key(seed=41), anthropic_key(seed=42), openrouter_key(seed=43)):
            self.assertFalse([piece for piece in fragments(secret) if piece in masked])

    def test_the_plain_old_sk_key_is_still_masked_with_its_old_label(self):
        plain = SK + tail(50, 48, string.ascii_letters + string.digits)
        self.assertEqual(mask("키는" + plain + "입니다"), "키는[가림: sk- 형식 API 키]입니다")

    def test_a_longer_sk_shape_with_mixed_case_and_digits_is_masked_with_the_general_label(self):
        for kind in ("svcacct", "admin", "None", "live"):
            secret = SK + kind + "-" + tail(60 + len(kind), 80)
            with self.subTest(kind=kind):
                self.assertEqual(mask(secret), "[가림: sk- 형식 API 키(긴 모양)]")
                self.assertEqual(mask("키는" + secret + "입니다"), "키는[가림: sk- 형식 API 키(긴 모양)]입니다")
        self.assertEqual(mask(SK + "a1B2-" * 10), "[가림: sk- 형식 API 키(긴 모양)]")
        self.assertEqual(mask(SK + "a1B2" * 12), "[가림: sk- 형식 API 키]", "영숫자뿐인 긴 모양은 정본(옛) 규칙이 먼저 가린다 — 그 출력은 그대로다")

    def test_hidden_characters_inside_a_key_do_not_hide_it(self):
        secret = project_key()
        split = secret[:14] + chr(0x200B) + secret[14:30] + chr(0x2060) + secret[30:]
        self.assertEqual(mask("키" + split), "키[가림: OpenAI 프로젝트 키]")
        self.assertTrue(has_key_shape("키" + split))


class BoundariesTest(unittest.TestCase):
    def test_the_tail_must_be_at_least_twenty_characters_long(self):
        for prefix, label in ((SK + "proj-", "OpenAI 프로젝트 키"), (SK + "ant-api03-", "Anthropic 키"), (SK + "or-v1-", "OpenRouter 키")):
            for size, masked in ((0, False), (1, False), (19, False), (20, True), (21, True), (64, True)):
                text = prefix + "aB3" * 30
                text = prefix + text[len(prefix):len(prefix) + size]
                with self.subTest(prefix=prefix, size=size):
                    self.assertEqual(mask(text) != text, masked, text)
                    if masked:
                        self.assertEqual(mask(text), f"[가림: {label}]")

    def test_the_tail_ends_at_the_first_character_that_cannot_be_part_of_a_key(self):
        secret = project_key()
        self.assertEqual(mask(secret + "!"), "[가림: OpenAI 프로젝트 키]!")
        self.assertEqual(mask(secret + "/path"), "[가림: OpenAI 프로젝트 키]/path")
        self.assertEqual(mask(secret + " 이어지는 글"), "[가림: OpenAI 프로젝트 키] 이어지는 글")
        self.assertEqual(mask(secret + "가나다"), "[가림: OpenAI 프로젝트 키]가나다")

    def test_a_prefix_that_is_the_end_of_a_longer_word_is_not_a_key(self):
        """`desk-proj-…`·`task-ant-api03-…` 처럼 `sk-` 앞이 영숫자이면 더 긴 낱말의 일부다(정본의 ASCII 경계와 같다)."""
        for letters in ("de", "ta", "ri", "di", "ma", "a", "A", "t", "9", "Z"):
            for secret in (project_key(), anthropic_key(), openrouter_key(), SK + "svc-" + tail(70, 80)):
                with self.subTest(letters=letters, head=secret[:10]):
                    self.assertEqual(mask(letters + secret), letters + secret)
        self.assertEqual(mask("Sk-proj-" + "aB3" * 20), "Sk-proj-" + "aB3" * 20)
        self.assertEqual(mask("SK-PROJ-" + "aB3" * 20), "SK-PROJ-" + "aB3" * 20, "대문자 접두사는 키가 아니다(서비스가 이 모양으로 내지 않는다)")

    def test_anthropic_needs_a_kind_with_two_digits_and_the_other_prefixes_are_exact(self):
        body = "aB3dE5" * 8
        for text in (SK + "ant-" + body, SK + "ant-colony-" + body, SK + "ant-api-" + body, SK + "ant-a03-" + body, SK + "ant-averyveryverylongword03-" + body):
            with self.subTest(text=text[:24]):
                self.assertEqual(mask(text).count("[가림: Anthropic 키]"), 0, "종류가 `영문 소문자 2~8자 + 숫자 2자 + -` 모양이 아니면 Anthropic 키로 보지 않는다(긴 모양 규칙이 따로 가릴 수는 있다)")
        self.assertEqual(mask(SK + "projects-" + "aB3dE5" * 3), SK + "projects-" + "aB3dE5" * 3, "`sk-projects-…` 는 접두사 `sk-proj-` 가 아니다")
        self.assertEqual(mask(SK + "or-" + "aB3dE5" * 3), SK + "or-" + "aB3dE5" * 3)
        self.assertEqual(mask(SK + "or-v1-" + "aB3dE5" * 3 + "xy"), "[가림: OpenRouter 키]", "꼬리 20자")
        self.assertEqual(mask(SK + "or-v1-" + "aB3dE5" * 3 + "x"), SK + "or-v1-" + "aB3dE5" * 3 + "x", "꼬리 19자")
        self.assertEqual(mask(SK + "or-v12-" + "aB3dE5" * 4), "[가림: OpenRouter 키]", "판 번호가 두 자리여도 같은 모양이다")

    def test_the_general_shape_needs_an_upper_case_letter_a_digit_and_forty_characters(self):
        body = "aB3dE5fG7hI9" * 4
        self.assertEqual(mask(SK + "svc-" + body), "[가림: sk- 형식 API 키(긴 모양)]")
        self.assertEqual(mask(SK + "svc-" + body[:35]), SK + "svc-" + body[:35], "꼬리가 40자 미만이다(`svc-` 포함 39자)")
        self.assertEqual(mask(SK + "svc-" + body[:36]), "[가림: sk- 형식 API 키(긴 모양)]", "꼬리가 딱 40자")
        self.assertEqual(mask(SK + ("abcdefgh-" * 10) + "1"), SK + ("abcdefgh-" * 10) + "1", "대문자가 없다 — 소문자 낱말을 붙임표로 이은 글이다")
        self.assertEqual(mask(SK + ("ABCDEFGH-" * 10)), SK + ("ABCDEFGH-" * 10), "숫자가 없다")
        far = SK + "x" * 10 + "-" + "x" * 55 + "A1" + "x" * 30
        self.assertEqual(mask(far), far, "대문자·숫자가 꼬리 앞 60자 안에 없다(앞내다보기는 60자까지 — 선형 시간을 지키려고)")


NORMAL_BY_HAND = (
    "겨울철 난방비를 줄이려면 창문 틈새를 먼저 막아 보세요.", "이번 주말에는 가족과 함께 근처 공원에서 산책을 했습니다.", "SK하이닉스 실적 발표를 보고 투자 계획을 다시 세웠다는 글을 읽었습니다.",
    "SK텔레콤의 새 요금제와 알뜰폰 요금제를 표로 비교해 정리했습니다.", "회의록은 공유 폴더에 올려 두었으니 확인 부탁드립니다.", "대출 금리가 오르면 월 상환액이 얼마나 늘어나는지 계산해 보겠습니다.",
    "이 글은 직접 쓴 것이며 광고나 협찬과 무관합니다.", "세탁기 통세척은 한 달에 한 번이면 충분하다는 설명서의 안내를 따랐습니다.", "제주도 여행 코스는 동쪽과 서쪽으로 나누어 짜는 편이 이동 시간을 줄여 줍니다.",
    "프로젝트 관리 도구를 고를 때는 팀 규모와 예산을 함께 따져 보세요.", "건강검진 결과표에서 수치가 높게 나온 항목은 의사와 상담하는 것이 좋습니다.", "오늘의 환율은 어제보다 조금 내려 거래하기 좋은 날이었습니다.",
    "스마트폰 배터리 수명을 늘리는 방법 다섯 가지를 소개합니다.", "자동차 보험은 갱신하기 전에 최소 세 곳의 견적을 비교해 보는 것이 좋습니다.", "아이들과 함께 만든 김치볶음밥이 생각보다 맛있게 완성되었습니다.",
    "도서관에서 빌린 책을 반납하러 가는 길에 비가 내리기 시작했습니다.", "연말정산 때 놓치기 쉬운 공제 항목을 미리 확인해 두면 환급액이 늘어납니다.", "노트북 SSD 를 교체하기 전에 반드시 백업을 해 두세요.",
    "영수증 사진을 찍어 두면 나중에 경비 처리할 때 편합니다.", "이 레시피의 핵심은 양파를 충분히 볶아 단맛을 끌어내는 것입니다.", "주차장 이용 요금은 최초 30분 무료이고 이후 10분마다 500원입니다.",
    "Our team reviewed the project plan and agreed on a task-oriented schedule for next quarter.", "The desk-top publishing tool ships with a risk-free thirty day trial.", "Please ask-me-anything threads are open until Friday evening.",
    "To install scikit-learn run the usual package manager command and restart the notebook.", "She said the sk-learn import error was caused by an outdated environment, not by the code.", "The mask-wearing rules changed again, so check the latest guidance before travelling.",
    "A skip-list is a probabilistic data structure that keeps elements in sorted order.", "Skype calls were replaced by video meetings after the office move last spring.", "We shipped the task-runner update with a short changelog and a migration note.",
    "The risk-adjusted return of the fund was lower than the benchmark over three years.", "Remember to lock the disk-encryption settings before handing the laptop to support.", "Her sketch-book was full of tiny drawings of cats, cafes and train stations.",
    "https://example.com/news/sk-hynix-hbm4-mass-production-schedule-announced-this-week", "https://example.com/blog/sk-telecom-launches-new-unlimited-plan-for-students-in-seoul", "https://example.com/guide/sk-ant-colony-optimization-algorithm-explained-with-examples",
    "https://example.com/tag/sk-project-management-tools-for-small-teams-compared", "참고 주소는 https://example.com/column/sk-group-annual-report-summary-2026 입니다.", "관련 기사: sk-innovation-battery-plant-expansion-in-hungary-and-the-us-market-outlook",
    "커밋 해시 3f2a9c1d7e4b5a6c8d9e0f1a2b3c4d5e6f7a8b9c 를 기준으로 되돌렸습니다.", "파일 체크섬은 d41d8cd98f00b204e9800998ecf8427e 입니다(빈 파일의 MD5).", "세션 번호 550e8400-e29b-41d4-a716-446655440000 은 로그에서 찾을 수 있습니다.",
    "주문번호 ORD-2026-1104-0001 로 문의해 주세요.", "상품 코드 SKU-12345-AB 는 품절입니다.", "ISBN 978-3-16-148410-0 책을 주문했습니다.", "송장번호 1234-5678-9012 로 배송 조회가 가능합니다.",
    "택배는 CJ대한통운으로 발송되었고 내일 오전에 도착할 예정입니다.", "Basic internationalization support landed in the last release.", "Bearer of good news, the shipment arrived a day early.",
    "api key 를 발급받는 방법은 서비스 설정 화면에서 안내합니다.", "비밀번호를 정기적으로 바꾸는 습관은 계정 보안에 도움이 됩니다.", "토큰이란 무엇인지 초보자도 이해하도록 풀어서 설명합니다.",
    "tokenizer 사용 방법과 사전 크기에 대한 간단한 설명입니다.", "secret santa 선물 교환은 연말 모임의 단골 행사입니다.", "task-force 운영 방법과 회의 주기를 정했습니다.",
    "git checkout -b feature/new-login-flow 로 새 가지를 만들었습니다.", "npm install 이 끝난 뒤에 개발 서버를 다시 시작하세요.", "pip install -r requirements.txt 를 실행했는데 경고만 몇 줄 나왔습니다.",
    "docker compose up -d 로 로컬 환경을 띄운 다음 접속해 보세요.", "export PATH=$PATH:/usr/local/bin 을 셸 설정 파일에 추가했습니다.", "SELECT name, price FROM products WHERE stock > 0 ORDER BY price;",
    "클래스 이름은 sk-circle 과 sk-chase-dot 처럼 짧은 로딩 애니메이션 라이브러리에서 쓰입니다.", "css 파일에서 .sk-fade-in-up 클래스가 중복 정의되어 있었습니다.", "파일 이름 sk-proj.txt 는 샘플 데이터이고 비밀과 관계없습니다.",
    "프로젝트 이름은 sk-project 이고 담당자는 다음 주에 정해집니다.", "sk-ant-colony 라는 이름의 연구 모임이 있습니다.", "하이픈이 든 낱말 sk-or-v1 은 문서에서 예시로만 쓰였습니다.",
    "이메일은 hello.world@example.com 로 보내 주시면 됩니다.", "전화번호 02-1234-5678 은 평일 오전에만 받습니다.", "오늘 점심 메뉴는 김치찌개와 계란말이, 시금치나물이었습니다.",
    "Meeting notes: agenda, action items, owners and due dates are listed below.", "The recipe calls for two cups of flour, one cup of sugar and a pinch of salt.", "Tomorrow's weather will be sunny with a light breeze from the west.",
    "Version 2.4.1 fixes a crash on startup and improves the speed of the search page.", "Release candidate rc-2026-11-04-build-117 passed all smoke tests.", "The invoice number is INV-2026-000123 and the due date is November 30.",
    "내일 오전 열 시에 치과 예약이 있어서 회의 시간을 조금 늦췄습니다.", "새로 산 청소기는 흡입력이 좋은 대신 소음이 조금 큰 편입니다.", "독서 모임에서는 한 달에 한 권씩 소설과 비소설을 번갈아 읽습니다.",
    "마라톤 완주를 목표로 매주 세 번씩 가볍게 뛰는 연습을 하고 있습니다.", "반려견 산책 시간은 아침 저녁으로 나누어 하루 두 번이 적당합니다.", "냉장고 정리는 유통기한이 임박한 재료부터 꺼내는 것이 요령입니다.",
    "비 오는 날 운전할 때는 평소보다 차간 거리를 두 배로 늘려야 합니다.", "전세 계약을 하기 전에는 등기부등본과 확정일자를 반드시 확인하세요.", "조명은 색온도가 낮을수록 따뜻한 느낌을 주어 침실에 어울립니다.",
    "엑셀에서 조건부 서식을 쓰면 중복된 값을 한눈에 찾을 수 있습니다.", "프레젠테이션은 핵심 메시지 하나로 시작해 세 가지 근거로 이어 가는 편이 좋습니다.", "회원 가입을 하지 않아도 일부 기능은 무료로 이용할 수 있습니다.",
    "배터리 잔량이 20퍼센트 아래로 내려가면 절전 모드가 자동으로 켜집니다.", "이 사진은 지난가을 설악산에서 찍은 것이고 보정은 하지 않았습니다.", "버스 환승 할인은 하차 후 30분 안에 다시 탑승해야 적용됩니다.",
    "알레르기가 있는 분은 성분표에서 땅콩과 우유 표기를 먼저 확인해 주세요.", "겨울 이불을 세탁할 때는 건조기보다 햇볕에 말리는 편이 좋습니다.", "자격증 시험 접수는 다음 달 첫째 주 월요일부터 시작됩니다.",
    "중고 거래를 할 때는 직접 만나 물건 상태를 확인하고 현금으로 결제하세요.", "커피 원두는 개봉 후 한 달 안에 마시는 것이 향이 가장 좋습니다.", "공유 오피스 입주 전에 계약 기간과 해지 조건을 꼼꼼히 읽어 보세요.",
    "문서에는 키가 sk-proj- 로 시작한다고만 적혀 있고 실제 값은 없습니다.", "The sk-ant-api03 prefix is documented in the vendor guide; never paste a full key into a chat window.",
    "접두사 sk-or-v1- 는 설명용 예시일 뿐 어떤 계정과도 관계가 없습니다.", "Our naming rule is sk-<team>-<year>, for example sk-design-2026, and it is used only for folders.",
    "회의 자료 폴더 sk-2026-q4-planning-and-budget-review 는 다음 주까지 정리합니다.", "Use the task-based checklist when you onboard a new teammate to the desk-top support tool.",
)

SUBJECTS = ("프로젝트", "견적서", "회의록", "여행 일정", "구매 후기를 쓰는 방법", "투자 공부 노트", "요리 레시피", "운동 기록", "독서 메모", "이사 준비 목록")
WORDS = ("sk-hynix", "sk-telecom", "sk-group", "sk-innovation", "sk-ant-colony", "sk-project", "sk-or-later", "sk-learn", "task-force", "desk-top")
TEMPLATES = (
    "{s} 정리 — 관련 자료 이름은 {w} 로 저장했습니다.", "{s} 를 공유할 때 주소 끝에 {w}-2026-11 을 붙였습니다.", "https://example.com/archive/{w}-{s_ascii}-weekly-summary-for-the-whole-team",
    "{s} 문서 제목은 {w} 이고 수정 이력은 아래에 적었습니다.", "Notes about {w}: the {s_ascii} draft was reviewed twice before publishing.",
    "{s} 관련 태그: {w}, 일상, 기록, 정리.", "slug 예시는 {w}-{s_ascii}-checklist-for-beginners-and-everyone-else 입니다.", "{w} 항목은 {s} 목록의 마지막에 있습니다.",
    "In the {s_ascii} folder the file {w}.md explains the naming rules.", "{s} 일정표에서 {w} 행은 다음 주 화요일로 미뤄졌습니다.",
)
ASCII = ("project", "estimate", "minutes", "trip", "review", "invest", "recipe", "workout", "reading", "moving")


def generated_normal_sentences():
    found = []
    for template_number, template in enumerate(TEMPLATES):
        for index, (subject, word) in enumerate(zip(SUBJECTS, WORDS[template_number % len(WORDS):] + WORDS[:template_number % len(WORDS)], strict=True)):
            found.append(template.format(s=subject, s_ascii=ASCII[index], w=word))
    return found


NORMAL = NORMAL_BY_HAND + tuple(generated_normal_sentences())


class NormalTextIsLeftAloneTest(unittest.TestCase):
    def test_there_are_two_hundred_distinct_sentences(self):
        self.assertEqual(len(set(NORMAL)), len(NORMAL))
        self.assertGreaterEqual(len(NORMAL_BY_HAND), 100)
        self.assertEqual(len(generated_normal_sentences()), 100)
        self.assertGreaterEqual(len(NORMAL), 200)

    def test_not_one_of_them_is_changed_by_the_mask_and_none_looks_like_a_key_shape(self):
        changed = [text for text in NORMAL if mask(text) != text]
        self.assertEqual(changed, [], f"{len(changed)}/{len(NORMAL)} 문장이 바뀌었다")
        self.assertEqual([text for text in NORMAL if has_key_shape(text)], [])

    def test_a_normal_sentence_around_a_real_looking_key_loses_only_the_key(self):
        secret = project_key()
        for text in NORMAL[:60]:
            with self.subTest(head=text[:12]):
                masked = mask(text + " " + secret + " " + text)
                self.assertEqual(masked, text + " [가림: OpenAI 프로젝트 키] " + text)

    def test_the_new_rules_do_not_change_the_output_for_text_the_old_rules_masked(self):
        """정본이 가리던 글의 출력은 그대로다 — 새 규칙은 정본이 못 알아보던 `sk-` 모양만 더한다."""
        old_style = SK + tail(60, 48, string.ascii_letters + string.digits)
        self.assertEqual(mask("키는 " + old_style + " 입니다"), "키는 [가림: sk- 형식 API 키] 입니다")
        for text in ("api_key = \"" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv\"", "Authorization: Bearer " + "aB3dE5fG7hI9jK1lM3nO5pQ7"):
            self.assertIn("[가림", mask(text))


class ConsistencyWithTheSelfCheckTest(unittest.TestCase):
    """`shape.looks_secret`(키·이름 칸의 자기 검사)은 마스크보다 넓다 — 마스크가 아는 모양은 모두 알아야 한다."""

    def test_every_shape_the_mask_knows_is_also_a_secret_for_the_self_check(self):
        known = {}
        for label, secrets in SHAPES.items():
            for secret in secrets:
                known[f"{label} {len(secret)}자"] = secret
        known["sk- 일반 모양"] = SK + "svcacct-" + tail(61, 80)
        known["옛 sk- 모양"] = SK + tail(62, 48, string.ascii_letters + string.digits)
        for label, secret in known.items():
            for context in ("{k}", "키는{k}입니다", "({k})", "앞\n{k}\n뒤"):
                text = context.replace("{k}", secret)
                with self.subTest(label=label, context=context):
                    self.assertTrue(mask(text) != text)
                    self.assertTrue(shape.looks_secret(text), "마스크가 아는 모양을 자기 검사가 모르면 두 곳이 어긋난 것이다")
                    self.assertNotEqual(shape.label_problem(text, max_len=500), "")

    def test_every_pattern_the_mask_has_is_listed_in_the_shapes_it_reports(self):
        for label, pattern in mk._NEW_SK_PATTERNS:
            self.assertIn(pattern, mk._SHAPE_PATTERNS, label)
        self.assertEqual([label for label, _pattern in mk._NEW_SK_PATTERNS], ["OpenAI 프로젝트 키", "Anthropic 키", "OpenRouter 키", "sk- 형식 API 키(긴 모양)"])

    def test_the_self_check_prefix_for_sk_keys_covers_every_tail_the_mask_accepts(self):
        """자기 검사의 `sk-` 꼬리(영숫자·`-`·`_` 12자 이상)는 마스크의 어떤 `sk-` 규칙보다 넓다 — 마스크가 20자 꼬리를 키로 보는 모양이면 자기 검사는 12자부터 키로 본다."""
        for size in (12, 20, 40):
            self.assertTrue(shape.looks_secret(SK + "proj-" + "a" * size))
        self.assertFalse(shape.looks_secret(SK + "a" * 11))


class SpeedTest(unittest.TestCase):
    def assert_fast(self, text, limit=5.0):
        started = time.perf_counter()
        mask(text)
        has_key_shape(text)
        self.assertLess(time.perf_counter() - started, limit, f"{len(text)}자")

    def test_huge_inputs_are_linear(self):
        self.assert_fast("sk-aa-" * 60_000)                     # `sk-` 가 수만 번 되풀이되는 입력 — 시작마다 앞내다보기가 끝까지 훑는 제곱 시간 구현을 잡는다(독립 검증이 짚음: 앞 글자를 따로 붙인 예전 입력은 `sk-` 가 한 번뿐이라 못 잡았다)
        self.assert_fast("sk-AA-" * 60_000)                     # 대문자는 바로 있고 숫자가 없는 꼴 — 숫자 쪽 앞내다보기가 끝까지 훑는 구현을 잡는다
        self.assert_fast("sk-proj-" * 40_000)
        self.assert_fast("sk-ant-api03-" * 25_000)
        self.assert_fast("sk-or-v1-" * 35_000)
        self.assert_fast("s" + "k-aa-" * 60_000)                # 앞 글자만 따로 붙은 예전 입력
        self.assert_fast("s" + "k-" + "a" * 300_000)
        self.assert_fast("s" + "k-" + "aB3-" * 75_000)
        self.assert_fast(("키는 " + project_key() + " 입니다 ") * 2_000)
        self.assert_fast(("sk-aA1" + "x" * 50 + " ") * 4_000)

    def test_scaling_is_close_to_linear(self):
        def took(times):
            text = ("키는" + project_key() + "입니다 ") * times
            started = time.perf_counter()
            mask(text)
            return time.perf_counter() - started

        small, large = took(1_000), took(9_000)
        self.assertLess(large, max(small * 40, 2.0), f"9배 입력에 {large / max(small, 1e-9):.1f}배")


class InsideTheAppTest(unittest.TestCase):
    """키를 글칸에 잘못 넣었을 때 앱의 화면에서 — 선택 입력은 거절하고 후보 화면은 가린다."""

    def fresh(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        ctx = ss.make_ctx(tmp.name)
        code, out, err = ss.run_cli(ctx, "candidates", "add", "--topic", "겨울 난방비", "--keyword", "난방비", "--blog", "github_pages")
        self.assertEqual(code, 0, (out, err))
        return ctx

    @staticmethod
    def leaks(text, secret):
        return [piece for piece in fragments(secret) if piece in text]

    def test_draft_plan_refuses_each_new_shape_in_every_free_text_option_and_prints_none_of_it(self):
        ctx = self.fresh()
        options = ("--message", "--experience", "--opinion", "--audience", "--title-direction", "--conclusion", "--must-include", "--exclude", "--price-date")
        for secrets in SHAPES.values():
            secret = secrets[2]
            for option in options:
                for form in (secret, "참고 " + secret + " 입니다", "키는" + secret + "를"):
                    with self.subTest(option=option, head=secret[:12], form=form[:6]):
                        code, out, err = ss.run_cli(ctx, "draft", "plan", "1", option, form)
                        self.assertEqual(code, 1, (out, err))
                        self.assertIn("DRAFT_OPTION_INVALID", err)
                        self.assertEqual(self.leaks(out + err, secret), [])

    def test_a_topic_with_a_new_shape_is_masked_on_every_candidate_screen(self):
        for label, secrets in SHAPES.items():
            secret = secrets[2]
            ctx = self.fresh()
            code, out, err = ss.run_cli(ctx, "candidates", "add", "--topic", "키 모양 " + secret + " 이 든 주제", "--keyword", "키워드 둘", "--blog", "naver_a")
            self.assertEqual((code, self.leaks(out + err, secret)), (0, []), label)
            self.assertIn("[가림", out)
            for argv in (("candidates", "list"), ("--json", "candidates", "list"), ("candidates", "show", "2"), ("--json", "candidates", "show", "2"), ("--verbose", "candidates", "list"),
                         ("candidates", "delete", "2"), ("--json", "candidates", "delete", "2")):
                with self.subTest(label=label, argv=argv):
                    code, out, err = ss.run_cli(ctx, *argv)
                    self.assertEqual(self.leaks(out + err, secret), [])
                    self.assertIn("[가림", out + err)


if __name__ == "__main__":
    unittest.main()
