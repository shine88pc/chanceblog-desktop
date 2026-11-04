"""변이 시험(코드를 일부러 망가뜨려도 시험이 통과하던 곳)에서 살아남은 12곳 — 조건 가드·때 표지·구매 과거형·시간 규칙 경계·영어 후기 전제·받침 판정·결론 제목 관문·태그 금지 표현·Slack 웹훅·개인 키 블록·주소 인자 이름의 점 — 을 한 곳씩 겨냥해 고정한다.

지키는 것(괄호는 겨냥한 변이의 이름):
  1) (N10) 경험을 나타내는 낱말 바로 뒤에 '…을 경우' 가 오면 겪은 일의 보고가 아니라 조건이라 위반이 아니다 — 같은 낱말이라도 '…했고' 로 끝맺으면 위반이다.
  2) (N18·N19) '어제·그제·며칠 전·지난달' 같은 때 표지 뒤의 '…받았습니다' 는 받은 일을 겪은 것으로 보고, '지난주' 도 때 표지다(방문·사용·구매 모두).
  3) (N24) 숫자가 여섯 자리를 넘게 이어진 글(`1234567시간 정도`) 속에서 일곱째 자리 이후만 떼어 소요 시간으로 읽지 않는다.
  4) (N48) 영어 `testimonial(s)` 도 후기를 전제한 글이다. (N51) 숫자 뒤에 이어 붙이는 '과/와' 는 숫자를 읽는 소리의 받침(영·일·삼·육·칠·팔)으로 고른다.
  5) (N58) 조사를 고를 때의 숫자 받침 표는 열 숫자 모두 읽는 소리와 같다. (N56) 결론으로 만드는 제목은 그 틀이 제외할 말·금지 표현에 걸리면 쓰지 않는다. (N61) 프로필의 금지 표현이 든 태그는 쓰지 않는다.
  6) (K09·K10) Slack 웹훅 주소와 개인 키 블록(정본 패턴이 못 알아보는 `ENCRYPTED PRIVATE KEY` 꼴)은 키 모양이라 참고 주소 칸에서 거절되고 오류에 값이 새지 않는다. (K23) 주소 인자 이름 속 점(`api.key`·`private.key`)은 무시하고 비밀 이름으로 본다.
기대값은 코드에서 가져오지 않고 손으로 적거나(문장·값 전체) 숫자를 읽는 소리처럼 코드와 따로 구한다. 키 모양 글은 조각을 이어서 만든다(저장소에 키 모양 글이 통째로 있으면 안 되므로). 네트워크·파일 없이 돈다.
"""
import sys
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.check import claims as cl  # noqa: E402
from chanceblog_desktop.content import draft_plan as dp  # noqa: E402
from chanceblog_desktop.content import post_types as pt  # noqa: E402
from chanceblog_desktop.content.candidates import Candidate  # noqa: E402
from chanceblog_desktop.content.draft_options import DraftOptions  # noqa: E402
from chanceblog_desktop.content.profiles import POST_TYPES, NaverProfile  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security.mask import has_key_shape, mask  # noqa: E402

Claim = cl.Claim
TODAY = "2026-11-03"
NOW = "2026-11-02T03:00:00Z"
DASHES = "-" * 5
READINGS = "영일이삼사오육칠팔구"                 # 0~9 를 읽는 소리 — 받침은 코드의 표가 아니라 이 글자에서 따로 구한다


def jongseong(syllable):
    """한글 음절의 받침 번호(없으면 0, ㄹ 은 8)."""
    return (ord(syllable) - 0xAC00) % 28


def invalid(test, work, *args, **kwargs):
    """`work(*args, **kwargs)` 가 `DRAFT_OPTION_INVALID` 로 거절되는지 보고 그 오류를 돌려준다."""
    with test.assertRaises(AppError) as caught:
        work(*args, **kwargs)
    test.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")
    return caught.exception


def error_bag(error):
    """오류가 사용자와 로그에 내놓는 모든 글(문구·안내·세부·칸 값·표현)."""
    shown = error.rendered()
    return " ".join([str(shown.message), str(getattr(shown, "action", "")), str(error.detail), repr(error.slots), repr(error), str(error)])


# ---- (N10·N18·N19·N24) '지어내지 않기' 검사 ---------------------------------------------------------------------------------------
class ConditionalAfterExperienceWordTest(unittest.TestCase):
    """N10 — 경험 낱말 바로 뒤의 '…을 경우' 는 조건이다(가드 '을경우')."""

    CONDITIONAL = (
        "직접 써봤을 경우 설정이 번거롭습니다.", "다녀왔을 경우 주차가 번거롭습니다.", "구매해봤을 경우 환불 절차가 번거롭습니다.", "사용해 봤을 경우 설정이 번거롭습니다.",
        "직접 방문했을 경우 대기 시간이 길어집니다.", "써 보았을 경우 설정이 번거롭습니다.",
    )
    REPORTED = (          # 같은 낱말을 '…했고' 로 끝맺으면 겪은 일의 보고다 — (문장, 걸리는 위반 전부 — 구매 낱말처럼 한 문장에 둘이 걸리는 것은 뺀다)
        ("직접 써봤고 설정이 번거롭습니다.", (Claim("experience_use", 0, "직접써봤"),)),
        ("다녀왔고 주차가 번거롭습니다.", (Claim("experience_visit", 0, "다녀왔"),)),
        ("사용해 봤고 설정이 번거롭습니다.", (Claim("experience_use", 0, "사용해봤"),)),
        ("직접 방문했고 대기 시간이 길어집니다.", (Claim("experience_visit", 0, "직접방문했"),)),
        ("써 보았고 설정이 번거롭습니다.", (Claim("experience_use", 0, "써보았"),)),
    )

    def test_conditional_sentences_are_not_violations(self):
        for sentence in self.CONDITIONAL:
            with self.subTest(sentence=sentence):
                self.assertEqual(cl.find_violations(sentence), ())
                self.assertEqual(cl.find_claims(sentence), ())

    def test_the_same_words_ended_as_a_report_are_violations(self):
        for sentence, expected in self.REPORTED:
            with self.subTest(sentence=sentence):
                self.assertEqual(cl.find_violations(sentence), expected)

    def test_a_condition_does_not_hide_a_report_in_the_next_sentence(self):
        text = "써 보았을 경우 설정이 번거롭습니다. 그런데 써 보았고 설정이 번거롭습니다."
        self.assertEqual(cl.find_violations(text), (Claim("experience_use", 1, "써보았"),))


class ReceivedAfterTimeMarkTest(unittest.TestCase):
    """N18 — 때 표지('어제·그제·며칠 전·지난달') 뒤의 '…받았습니다' 는 받은 일(구매·수령)을 겪은 것이다(구매 과거형 '받았')."""

    REPORTS = (
        ("어제 책을 받았습니다.", "어제책을받았습니다"), ("그제 소포를 받았다.", "그제소포를받았다"), ("며칠 전 우편물을 받았습니다.", "며칠전우편물을받았습니다"),
        ("지난달 우편물을 받았고 바로 열었다.", "지난달우편물을받았고"), ("엊그제 편지를 받았습니다.", "엊그제편지를받았습니다"),
    )

    def test_received_after_a_time_mark_is_a_purchase_claim(self):
        for sentence, word in self.REPORTS:
            with self.subTest(sentence=sentence):
                self.assertEqual(cl.find_violations(sentence), (Claim("experience_buy", 0, word),))

    def test_the_claim_is_found_inside_a_longer_text(self):
        text = "오늘은 정리를 해 봅니다. 어제 책을 받았습니다. 내용은 아래와 같습니다."
        self.assertEqual(cl.find_violations(text), (Claim("experience_buy", 1, "어제책을받았습니다"),))


class LastWeekTimeMarkTest(unittest.TestCase):
    """N19 — '지난주' 도 때 표지다: 뒤에 방문·사용·구매 과거형이 이어지면 겪은 일의 보고다(낱말은 때 표지부터 잡힌다)."""

    REPORTS = (
        ("지난주 부산에 갔습니다.", "experience_visit", "지난주부산에갔습니다"), ("지난주 카페에 다녀왔다.", "experience_visit", "지난주카페에다녀왔다"),
        ("지난주 그곳에 들렀어요.", "experience_visit", "지난주그곳에들렀어요"), ("지난주 앱을 설치했습니다.", "experience_use", "지난주앱을설치했"),
        ("지난주 영화를 봤습니다.", "experience_use", "지난주영화를봤습니다"), ("지난주 소포를 받았습니다.", "experience_buy", "지난주소포를받았습니다"),
        ("지난주 가방을 샀습니다.", "experience_buy", "지난주가방을샀습니다"),
    )

    def test_each_report_is_caught_from_the_time_mark(self):
        for sentence, category, word in self.REPORTS:
            with self.subTest(sentence=sentence):
                self.assertEqual(cl.find_violations(sentence), (Claim(category, 0, word),))


class LongDigitRunIsNotADurationTest(unittest.TestCase):
    """N24 — 소요 시간 규칙은 숫자 한 덩어리가 시작하는 자리에서만 걸린다: 여섯 자리를 넘는 숫자의 뒤쪽 여섯 자리를 떼어 '234567시간 정도' 로 읽지 않는다(같은 규칙의 다른 갈래 — 시각·일·주·개월·초·거리 — 도 같다)."""

    PAIRS = (          # (숫자가 너무 긴 문장, 숫자를 규칙이 읽는 길이로 줄인 같은 문장, 줄인 문장에서 걸리는 낱말)
        ("재생 누적은 12345678시간 정도입니다.", "재생 누적은 123456시간 정도입니다.", "123456시간정도"),
        ("일련번호 1234567분 정도 차이입니다.", "일련번호 123456분 정도 차이입니다.", "123456분정도"),
        ("누적 재생은 1234567시간가량 됩니다.", "누적 재생은 123456시간가량 됩니다.", "123456시간가량"),
        ("로그 번호 98765432분 이내를 뜻합니다.", "로그 번호 987654분 이내를 뜻합니다.", "987654분이내"),
        ("코드 1234567시간 안에 처리됩니다.", "코드 123456시간 안에 처리됩니다.", "123456시간안에"),
        ("참조 ID 1234567시간을 소요합니다.", "참조 ID 123456시간을 소요합니다.", "123456시간을소요"),
        ("참조 ID 1234567분이 소요됩니다.", "참조 ID 123456분이 소요됩니다.", "123456분이소요"),
        ("코드 123시에 해당합니다.", "코드 12시에 해당합니다.", "12시에"),
        ("번호 123시부터 시작합니다.", "번호 12시부터 시작합니다.", "12시부터"),
        ("시리얼 1234일 이내로 표기됩니다.", "시리얼 123일 이내로 표기됩니다.", "123일이내"),
        ("시리얼 1234주 안에 표기됩니다.", "시리얼 123주 안에 표기됩니다.", "123주안에"),
        ("참조 1234567초 정도입니다.", "참조 123456초 정도입니다.", "123456초정도"),
        ("참조 1234567일 남짓입니다.", "참조 123456일 남짓입니다.", "123456일남짓"),
        ("참조 1234567개월 안팎입니다.", "참조 123456개월 안팎입니다.", "123456개월안팎"),
        ("참조 1234567달 전후입니다.", "참조 123456달 전후입니다.", "123456달전후"),
        ("참조 12345일간 표기됩니다.", "참조 1234일간 표기됩니다.", "1234일간"),
        ("참조 12345주 동안 표기됩니다.", "참조 1234주 동안 표기됩니다.", "1234주동안"),
        ("참조 1234567분 거리입니다.", "참조 123456분 거리입니다.", "123456분거리"),
        ("참조 1234567시간마다 표기됩니다.", "참조 123456시간마다 표기됩니다.", "123456시간마다"),
        ("참조 1234567시간째 표기됩니다.", "참조 123456시간째 표기됩니다.", "123456시간째"),
        ("참조 1234567분전 기록입니다.", "참조 123456분전 기록입니다.", "123456분전"),
    )

    def test_digit_runs_longer_than_the_rule_reads_are_not_a_duration(self):
        for long_sentence, _short, _word in self.PAIRS:
            with self.subTest(sentence=long_sentence):
                self.assertEqual(cl.find_claims(long_sentence), ())

    def test_the_same_sentences_with_a_readable_number_are_a_duration(self):
        for _long, short_sentence, word in self.PAIRS:
            with self.subTest(sentence=short_sentence):
                self.assertEqual(cl.find_claims(short_sentence), (Claim("time", 0, word),))


# ---- (N48·N51) 글 유형 --------------------------------------------------------------------------------------------------------------
class EnglishTestimonialPremiseTest(unittest.TestCase):
    """N48 — 영어 `testimonial(s)` 도 `review` 처럼 경험형 후기를 전제한 글이다(낱말 경계로 찾아 다른 낱말 속의 것은 아니다)."""

    REVIEW = pt.Replacement("review", "경험형 후기", "정보형 안내 글", None)

    def test_testimonials_are_a_review_premise(self):
        for text in ("Blender testimonials", "blender testimonial", "Customer Testimonials", "testimonials", "Reviewing testimonials page"):
            with self.subTest(text=text):
                self.assertEqual(pt.premise_of(text), self.REVIEW)

    def test_a_word_that_only_contains_it_is_not(self):
        for text in ("contestimonial", "attestimonials"):
            with self.subTest(text=text):
                self.assertIsNone(pt.premise_of(text))

    def test_the_candidate_is_replaced_by_an_information_post(self):
        candidate = Candidate.new("Blender testimonials roundup", "blender testimonials", ("naver_a",), sub_keywords=(), post_type=POST_TYPES[0], now=NOW)
        plan = dp.build_plan(candidate, NaverProfile("naver_a", "블로그 에이", "https://blog.naver.com/exampleaaa"), today=TODAY)
        self.assertEqual(plan.replaced, ("경험형 후기", "정보형 안내 글"))
        self.assertEqual(plan.post_type, POST_TYPES[0])


class ConnectiveAfterDigitTest(unittest.TestCase):
    """N51 — 숫자 뒤에 이어 붙이는 '과/와'·'이랑/랑'·'이나/나' 는 그 숫자를 읽는 소리(영·일·이·삼·사·오·육·칠·팔·구)의 받침으로 고른다."""

    def test_every_digit_gets_the_particle_of_its_reading(self):
        for digit, reading in enumerate(READINGS):
            final = jongseong(reading) != 0
            for connective, with_final, without_final in (("와", "과", "와"), ("랑", "이랑", "랑"), ("나", "이나", "나")):
                with self.subTest(digit=digit, reading=reading, connective=connective):
                    expected = f"아이폰{digit}{with_final if final else without_final} 장단점"
                    self.assertEqual(pt.strip_premise(f"아이폰{digit} 후기{connective} 장단점"), expected)

    def test_a_digit_after_a_word_decides_by_the_digit(self):
        self.assertEqual(pt.strip_premise("갤럭시 S8 후기와 장단점"), "갤럭시 S8과 장단점")
        self.assertEqual(pt.strip_premise("갤럭시 S9 후기와 장단점"), "갤럭시 S9와 장단점")


# ---- (N56·N58·N61) 작성 기반 --------------------------------------------------------------------------------------------------------
def make(topic="겨울 보일러 점검 순서", keyword="보일러 점검", subs=("보일러 청소", "난방비"), post_type=POST_TYPES[0], blogs=("naver_a", "naver_b")):
    return Candidate.new(topic, keyword, blogs, sub_keywords=subs, post_type=post_type, now=NOW)


def profile(key, **changes):
    base = {"naver_a": ("블로그 에이", "https://blog.naver.com/exampleaaa"), "naver_b": ("블로그 비", "https://blog.naver.com/examplebbb")}[key]
    return NaverProfile(key, base[0], base[1], **changes)


def plan_of(blog, options=None, **profile_changes):
    return dp.build_plan(make(), profile(blog, **profile_changes), options, today=TODAY)


class NumberFinalConsonantTest(unittest.TestCase):
    """N58 — 조사를 고를 때 숫자는 읽는 소리의 받침을 본다: 종성 번호가 열 숫자 모두 읽는 소리(영·일·이·삼·사·오·육·칠·팔·구)의 받침과 같다."""

    def test_the_final_of_each_digit_is_the_final_of_its_reading(self):
        for digit, reading in enumerate(READINGS):
            with self.subTest(digit=digit, reading=reading):
                self.assertEqual(dp._final(str(digit)), jongseong(reading))

    def test_particles_after_each_digit(self):
        for digit, reading in enumerate(READINGS):
            final = jongseong(reading)
            with self.subTest(digit=digit, reading=reading):
                self.assertEqual(dp.particle(str(digit), "을", "를"), "을" if final else "를")
                self.assertEqual(dp.particle(str(digit), "이", "가"), "이" if final else "가")
                self.assertEqual(dp.particle(str(digit), "으로", "로"), "으로" if final not in (0, 8) else "로")          # ㄹ 받침(일·칠·팔)은 '로'
                self.assertEqual(dp._fill("{x:은/는} 다릅니다", x=f"모델 {digit}"), f"모델 {digit}{'은' if final else '는'} 다릅니다")

    def test_the_digit_one_is_read_with_a_final(self):
        self.assertEqual(dp.particle("1", "을", "를"), "을")
        self.assertEqual(dp.particle("1", "으로", "로"), "로")
        self.assertEqual(dp.particle("모델 1", "이", "가"), "이")


class ConclusionTitleGateTest(unittest.TestCase):
    """N56 — 결론으로 만드는 제목(`{키워드}: {결론}`·`{결론}: {키워드}`)은 그 틀(`: `)이 제외할 말·금지 표현에 걸리면 제목 후보에 넣지 않는다."""

    CONCLUSION = "환기가 먼저입니다"
    TITLE_OF = {"naver_a": "보일러 점검: 환기가 먼저입니다", "naver_b": "환기가 먼저입니다: 보일러 점검"}

    def test_without_a_blocking_word_the_conclusion_title_comes_first(self):
        for blog, title in self.TITLE_OF.items():
            with self.subTest(blog=blog):
                self.assertEqual(plan_of(blog, DraftOptions(conclusion=self.CONCLUSION)).titles[0], title)

    def test_an_excluded_word_in_the_frame_drops_the_conclusion_title(self):
        for blog in self.TITLE_OF:
            for colon in (":", "：", " : "):                                   # 반각·전각·공백이 낀 쌍점 — 모두 같은 글로 본다
                with self.subTest(blog=blog, colon=colon):
                    plain = plan_of(blog, DraftOptions(exclude=(colon,)))
                    given = plan_of(blog, DraftOptions(conclusion=self.CONCLUSION, exclude=(colon,)))
                    self.assertEqual(len(given.titles), 3)
                    self.assertEqual(given.titles, plain.titles)
                    self.assertEqual([title for title in given.titles if self.CONCLUSION in title], [])

    def test_a_forbidden_phrase_in_the_frame_drops_the_conclusion_title(self):
        for blog in self.TITLE_OF:
            with self.subTest(blog=blog):
                plain = plan_of(blog, DraftOptions(), forbidden_phrases=(":",))
                given = plan_of(blog, DraftOptions(conclusion=self.CONCLUSION), forbidden_phrases=(":",))
                self.assertEqual(len(given.titles), 3)
                self.assertEqual(given.titles, plain.titles)
                self.assertEqual([title for title in given.titles if self.CONCLUSION in title], [])


class TagForbiddenPhraseTest(unittest.TestCase):
    """N61 — 프로필의 금지 표현이 든 태그는 추천 태그에 넣지 않는다(프로필의 기본 태그와 키워드에 꼬리를 붙여 만든 태그 모두)."""

    DEFAULTS = ("겨울준비", "최저가보장", "난방절약")
    TAIL = {"naver_a": "정리", "naver_b": "가이드"}          # 블로그 말씨마다 키워드 뒤에 붙는 꼬리 하나

    def test_a_default_tag_with_a_forbidden_phrase_is_dropped(self):
        for blog in self.TAIL:
            with self.subTest(blog=blog):
                base = plan_of(blog, default_tags=self.DEFAULTS).tags
                banned = plan_of(blog, default_tags=self.DEFAULTS, forbidden_phrases=("최저가",)).tags
                self.assertIn("최저가보장", base)
                self.assertEqual(banned, tuple(tag for tag in base if tag != "최저가보장"))
                self.assertEqual(len(banned), len(base) - 1)

    def test_a_tag_made_of_the_keyword_and_a_forbidden_tail_is_dropped(self):
        for blog, tail in self.TAIL.items():
            with self.subTest(blog=blog):
                base = plan_of(blog, default_tags=self.DEFAULTS).tags
                banned = plan_of(blog, default_tags=self.DEFAULTS, forbidden_phrases=(tail,)).tags
                self.assertIn("보일러점검" + tail, base)
                self.assertIn("보일러점검", banned)                                        # 키워드만 있는 태그는 남는다(주제 낱말은 막을 수 없다)
                self.assertEqual(banned, tuple(tag for tag in base if tag != "보일러점검" + tail))

    def test_a_forbidden_word_inside_the_keyword_does_not_drop_the_keyword_tags(self):
        for blog in self.TAIL:
            with self.subTest(blog=blog):
                base = plan_of(blog, default_tags=self.DEFAULTS).tags
                self.assertEqual(plan_of(blog, default_tags=self.DEFAULTS, forbidden_phrases=("점검",)).tags, base)          # 키워드('보일러 점검')의 낱말은 막을 수 없다
                self.assertIn("보일러점검", base)

    def test_a_forbidden_phrase_that_no_tag_has_changes_nothing(self):
        for blog in self.TAIL:
            with self.subTest(blog=blog):
                self.assertEqual(plan_of(blog, default_tags=self.DEFAULTS, forbidden_phrases=("전혀없는표현",)).tags, plan_of(blog, default_tags=self.DEFAULTS).tags)


# ---- (K09·K10·K23) 키 모양과 주소 인자 ------------------------------------------------------------------------------------------------
HOOK = "https://hooks." + "slack.com/services/" + "T0123ABCD/" + "B0456EFGH/" + "abcdefghijklmnopqrstuvwx"           # Slack 웹훅 모양(가짜 값, 조각을 이어 만든다)
HOOK_PIECES = ("T0123ABCD", "B0456EFGH", "abcdefghijklmnop", "klmnopqrstuvwx")
KEY_BLOCK = DASHES + "BEGIN " + "ENCRYPTED " + "PRIVATE " + "KEY" + DASHES          # 정본 패턴이 못 알아보는 꼴(암호화한 개인 키)
KEY_PIECES = ("ENCRYPTED", "PRIVATE KEY")
KEY_DETAIL = "키 모양의 글이 들어 있다(값은 적지 않는다)"


class SlackWebhookShapeTest(unittest.TestCase):
    """K09 — Slack 웹훅 주소는 키 모양이다: `has_key_shape` 가 알아보고 참고 주소 칸에서 거절되며 오류에 웹훅의 조각이 새지 않는다."""

    def test_the_webhook_is_a_key_shape(self):
        self.assertTrue(has_key_shape(HOOK))
        self.assertTrue(has_key_shape("알림 주소는 " + HOOK + " 입니다"))
        self.assertTrue(has_key_shape("주소" + HOOK + "끝"))
        self.assertEqual(mask("알림 " + HOOK + " 끝"), "알림 [가림: Slack 웹훅] 끝")

    def test_slack_pages_without_a_webhook_path_are_not(self):
        for text in ("https://hooks.slack.com/", "https://api.slack.com/messaging/webhooks", "슬랙 웹훅 설정 방법"):
            with self.subTest(text=text):
                self.assertFalse(has_key_shape(text))

    def test_the_url_field_rejects_the_webhook_without_leaking_it(self):
        error = invalid(self, DraftOptions, urls=(HOOK,))
        self.assertEqual(error.detail, KEY_DETAIL)
        self.assertEqual(error.slots["항목"], "참고 URL")
        bag = error_bag(error)
        for piece in HOOK_PIECES:
            self.assertNotIn(piece, bag)

    def test_the_url_field_rejects_the_webhook_inside_a_longer_address(self):
        for url in (f"https://example.com/redirect?to={HOOK}", f"https://example.com/p#{HOOK}"):
            with self.subTest(url=url[:40]):
                error = invalid(self, DraftOptions, urls=(url,))
                self.assertEqual(error.detail, KEY_DETAIL)
                for piece in HOOK_PIECES:
                    self.assertNotIn(piece, error_bag(error))

    def test_the_url_field_rejects_a_percent_written_webhook(self):
        for url in (f"https://example.com/redirect?to={quote(HOOK, safe='')}", f"https://example.com/redirect?to={quote(quote(HOOK, safe=''), safe='')}"):
            with self.subTest(url=url[:40]):
                error = invalid(self, DraftOptions, urls=(url,))
                self.assertEqual(error.detail, KEY_DETAIL)
                for piece in HOOK_PIECES:
                    self.assertNotIn(piece, error_bag(error))

    def test_a_plain_slack_address_is_accepted(self):
        self.assertEqual(DraftOptions(urls=("https://api.slack.com/messaging/webhooks",)).urls, ("https://api.slack.com/messaging/webhooks",))


class PrivateKeyBlockShapeTest(unittest.TestCase):
    """K10 — 개인 키 블록 머리글(`ENCRYPTED PRIVATE KEY` 처럼 정본 패턴이 못 알아보는 꼴 포함)은 키 모양이라 참고 주소 칸에서 거절된다."""

    def test_the_block_header_is_a_key_shape(self):
        self.assertTrue(has_key_shape(KEY_BLOCK))
        self.assertTrue(has_key_shape("앞 글 " + KEY_BLOCK + " 뒤 글"))
        self.assertTrue(has_key_shape(KEY_BLOCK + "\nMIIFDjBABgkqhkiG9w0BBQ0wMzAbBgkqhkiG9w0BBQwwDgQI\n" + DASHES + "END " + "ENCRYPTED " + "PRIVATE " + "KEY" + DASHES))
        self.assertEqual(mask("앞 글 " + KEY_BLOCK), "앞 글 [가림: 개인 키 블록]")

    def test_public_blocks_are_not_a_private_key(self):
        for kind in ("PUBLIC KEY", "CERTIFICATE"):
            with self.subTest(kind=kind):
                self.assertFalse(has_key_shape(DASHES + "BEGIN " + kind + DASHES))

    def test_the_url_field_rejects_the_block_in_a_percent_written_address(self):
        url = "https://example.com/p?x=" + KEY_BLOCK.replace(" ", "%20")
        error = invalid(self, DraftOptions, urls=(url,))
        self.assertEqual(error.detail, KEY_DETAIL)
        self.assertEqual(error.slots["항목"], "참고 URL")
        bag = error_bag(error)
        for piece in KEY_PIECES:
            self.assertNotIn(piece, bag)

    def test_the_url_field_accepts_a_similar_looking_public_address(self):
        url = "https://example.com/p?x=" + (DASHES + "BEGIN " + "PUBLIC " + "KEY" + DASHES).replace(" ", "%20")
        self.assertEqual(DraftOptions(urls=(url,)).urls, (url,))


class DottedParameterNameTest(unittest.TestCase):
    """K23 — 주소 인자 이름은 `-`·`_`·`.`·공백을 무시하고 읽는다: `api.key`·`private.key`·`pass.word` 도 비밀 이름이다(점이 낱말을 쪼개 규칙을 피하지 못한다)."""

    VALUE = "abcdefghijklmnopqrstuvwxyz"          # 숫자뿐이 아닌 16자 이상 값 — 이름만 비밀 이름이면 거절된다(키 모양은 아니다)
    SECRET_NAMES = ("api.key", "private.key", "pass.word", "access.key", "client.secret", "session.id", "auth.code", "code.verifier", "pass.phrase", "x.api.key", "A.P.I.K.E.Y")
    PARAM_DETAIL = "비밀 인자가 들어 있다(인자 이름·값은 적지 않는다)"

    def test_dotted_secret_names_are_rejected_in_every_place_an_argument_can_be(self):
        for name in self.SECRET_NAMES:
            for start in ("?", "&", ";", "#"):
                with self.subTest(name=name, start=start):
                    url = f"https://example.com/p{'?a=1' if start == '&' else ''}{start}{name}={self.VALUE}"
                    error = invalid(self, DraftOptions, urls=(url,))
                    self.assertEqual(error.detail, self.PARAM_DETAIL)
                    self.assertNotIn(self.VALUE[:12], error_bag(error))

    def test_every_ignored_character_between_the_words_of_a_name(self):
        for separator in ("-", "_", ".", "%20", "%09", "-.", "_-", "%20."):          # 이름 속 `-`·`_`·`.`·공백·탭은 모두 무시하고 읽는다
            with self.subTest(separator=separator):
                url = f"https://example.com/p?api{separator}key={self.VALUE}"
                error = invalid(self, DraftOptions, urls=(url,))
                self.assertEqual(error.detail, self.PARAM_DETAIL)
                self.assertNotIn(self.VALUE[:12], error_bag(error))

    def test_a_percent_written_dot_is_read_the_same(self):
        url = f"https://example.com/p?api%2Ekey={self.VALUE}"
        self.assertEqual(invalid(self, DraftOptions, urls=(url,)).detail, self.PARAM_DETAIL)

    def test_harmless_dotted_names_are_accepted(self):
        for name in ("page.layout", "view.mode", "utm.source", "site.lang"):
            with self.subTest(name=name):
                url = f"https://example.com/p?{name}={self.VALUE}"
                self.assertEqual(DraftOptions(urls=(url,)).urls, (url,))

    def test_a_dotted_secret_name_with_a_short_or_numeric_value_is_accepted(self):
        for value in ("12345678901234567890", "short"):
            with self.subTest(value=value):
                url = f"https://example.com/p?api.key={value}"
                self.assertEqual(DraftOptions(urls=(url,)).urls, (url,))


if __name__ == "__main__":
    unittest.main()
