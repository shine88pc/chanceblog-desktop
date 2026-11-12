"""초안 작성 화면의 순수 층(`ui/core/draft_rules.py`·`drafts.py`·`drafts_view.py`·`draft_text.py`) 시험 — PySide6 없이 돈다(CI 와 같은 조건). 가짜 후보(제목·키워드는 모두 지어낸 예시)와 가짜 공급자만 쓴다.

지키는 것:
  1) **확인 권장 가르기**: 알려진 고정 글 여섯 가지와 소제목 수 어긋남 줄만 '모든 글 공통'(접힘), 나머지 — 모르는 줄·서비스가 나중에 더하는 줄 포함 — 는 모두 '이 글에만 해당'(펼침). 위험한 줄(협찬·민감 주제·단정 낱말·쓰지 못한 문장·입력한 가격)이 접히지 않는다. 서비스 소스의 글자와 같은지 견준다.
  2) **복사 전 관문**: 키·토큰 모양이면 막고(제목·본문·전체·키워드·태그·요약 모두), 이 글에만 해당하는 확인 권장·분야 못 읽음·점검 걸림·거의 안 고침이 있으면 첫 복사에 확인창(`confirm_copy` 만 글을 준다), 이미 확인한 것은 다시 묻지 않고 새로 생긴 것만 다시 묻는다. 복사할 글은 **고친 그대로**다.
  3) **안전 판정이 '자동 초안 중지' 인 후보는 본문이 나오지 않는다** — 후보 화면의 단추가 꺼지고, 화면 상태가 공급자를 부르지 않고 거절하고, 공급자가 중지를 말하면 본문을 버리고, 다른 후보의 초안이 오면 버린다.
  4) **고친 내용은 확인 없이 사라지지 않는다**: 다시 만들기·다른 제목 후보·화면 떠나기·앱 닫기 앞에 확인창, 실패해도 이미 보이던 초안·고친 내용은 그대로.
  5) 화면 글은 쉬운 말뿐이고(금지 표현·파이썬 글·명령줄 글 없음) 쓰이지 않는 문구가 없다. 아무것도 저장하지 않고 클립보드를 모른다(소스 규칙).
  6) **독립 검증 수정 라운드(V1~V5)**: 정상 주소·파일 이름은 키 모양으로 막지 않고 알려진 키 모양만 막으며 막은 자리를 앞부분만 짚는다 · 건강 효과 단정(운영자 C 예시 9개)은 서비스가 만든 글·선택 입력·편집기·제목 어디에 있어도 복사를 막고
     일상 문장 50개·A/B 대조 40개·생성한 초안은 막지 않는다 · 검사 카드는 본 범위를 밝힌다 · 다시 만드는 동안에는 제목·본문을 고칠 수 없다 · 변이 점검이 찾은 시험 틈(N05·N07·N10·N22·N32).
"""
import ast
import dataclasses
import re
import sys
import threading
import types
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from draft_samples import CONTROL, DAILY, KNOWN_LIMITS, NORMAL_ADDRESSES, NORMAL_FILE_NAMES, NORMAL_MORE, OPERATOR_C, SECRET_ADDRESSES, hexed, mixed  # noqa: E402
import garbage_samples as GS  # noqa: E402

from chanceblog_desktop.check import claims as claim_check  # noqa: E402
from chanceblog_desktop.check import garbage as garbage_rule  # noqa: E402
from chanceblog_desktop.content import body_bank  # noqa: E402
from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content import draft_body as cdb  # noqa: E402
from chanceblog_desktop.content import draft_options as do  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import safety  # noqa: E402
from chanceblog_desktop.ui.core import app_state, draft_garbage as dg, draft_rules as rules, draft_text, drafts, drafts_view as dv, jobs, text  # noqa: E402
from chanceblog_desktop.ui.core import candidates as ucd  # noqa: E402
from chanceblog_desktop.ui.core import candidates_view as cv  # noqa: E402

T = text.T
UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
CONTENT_DIR = ROOT / "src" / "chanceblog_desktop" / "content"
KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
FORBIDDEN_WORDS = ("월 검색량", "검색량", "상위노출", "노출 확률", "검색 1위", "수익 보장", "보장", "월간 검색")
PROFILES = ucd.PROFILES
ROWS = ucd._sample_candidates("normal")


def engine(number, topic, keyword, channel="naver_a", subs=(), status="NEW"):
    """가짜 엔진 후보 하나(번호는 `number` 로 정해진다)."""
    return ucd.build_candidate(number, topic, channel, "top", keywords=(keyword, *subs), status=status)


GENERIC = engine(901, "예시 후보 가 — 분야를 알 수 없는 안내", "예시 낱말 가", subs=("예시 보조 가",))                  # 분야 낱말이 없다 → 분야 못 읽음(generic)
SOFTWARE = engine(902, "예시 AI 서비스 사용법", "예시 AI 서비스")                                                            # 소프트웨어 분야이고 네이버 A 의 협찬 가능 분야가 아니다 → 이 글에만 해당하는 줄이 없다
APPLIANCE = engine(903, "예시 청소기 고르는 기준", "예시 청소기")                                                         # 가전 분야 + 네이버 A 의 협찬 가능 분야 → 협찬 안내 줄
HEALTH = engine(904, "예시 영양제 고르는 기준", "예시 영양제")                                                          # 민감 주제(건강)
STOPPED = engine(905, "예시 영양제 먹으면 바로 낫는 방법", "예시 영양제", subs=("예시 보조 가",))                              # 안전 판정 '자동 초안 중지'
OTHER_CHANNEL = engine(906, "예시 후보 카 — 다른 채널의 예", "예시 낱말 카", channel="blogger_ko")
REJECTED = engine(907, "예시 후보 사 — 제외한 후보", "예시 낱말 사", status="REJECTED")
CATALOG = [GENERIC, SOFTWARE, APPLIANCE, HEALTH, STOPPED, OTHER_CHANNEL, REJECTED]


def old_candidate(topic, keyword, subs=(), blog="naver_a"):
    return cd.Candidate.new(topic, keyword, (blog,), sub_keywords=tuple(subs))


def body_of(topic, keyword, subs=(), blog="naver_a", options=None, post_type=None):
    old = old_candidate(topic, keyword, subs, blog)
    return cdb.build_body(old, None, options, today="2026-11-05", blog=blog, post_type=post_type, channel=PROFILES[blog], safety=safety.check_text([old.topic, old.keyword, *old.sub_keywords]))


def new_controller(*, delay=0.0, fail=None):
    provider = drafts.FakeDraftsProvider(lambda: CATALOG, delay, fail=fail)
    return dv.DraftsController(provider, jobs.JobRunner())


def target_of(row, *, stop=None, name="예시 블로그 가"):
    return drafts.DraftTarget(row.candidate_id, row.topic, row.channel, name, safety.assess(row).stop if stop is None else stop, True)


def drive(controller, starter=None):
    results = {}
    status, job = (starter or controller.start_make)(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
    if job is not None:
        job.join(30)
    if "ok" in results:
        controller.apply_made(results["ok"])
    elif "failed" in results:
        controller.apply_make_failed(results["failed"])
    return status


def made(row=GENERIC, **kwargs):
    controller = new_controller(**kwargs)
    controller.open_target(target_of(row))
    drive(controller)
    return controller


def made_from(row, *, options=None):
    """한 후보만 담은 가짜 공급자로 만든 초안 — `options` 는 선택 입력 칸 이름 → 글(만들기 전에 적은 것이 처음 초안에 들어간다)."""
    controller = dv.DraftsController(drafts.FakeDraftsProvider(lambda: [row]), jobs.JobRunner())
    controller.open_target(target_of(row))
    for name, value in (options or {}).items():
        controller.set_option(name, value)
    drive(controller)
    return controller


def all_strings(value, skip=()):
    """뷰모델의 모든 글 — `skip` 에 든 이름의 칸(눌렀을 때 넘기는 열쇠 같은 값)은 보이는 글이 아니라 건너뛴다."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for name, item in value.items():
            if name not in skip:
                yield from all_strings(item, skip)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from all_strings(item, skip)

KEYS_NOT_SHOWN = ("key", "name", "kind", "tone", "state", "url", "index", "id")


# ---- 1) 규칙 -------------------------------------------------------------------------------------------------------------------------------
class SplitChecksTest(unittest.TestCase):
    def test_the_known_fixed_lines_and_the_heading_count_line_are_common_and_every_other_line_is_specific(self):
        common = [prefix + " — 뒤에 이어지는 글" for prefix in rules.COMMON_PREFIXES] + ["소제목이 6개입니다 — 이 블로그 프로필의 소제목 수(3~5개)와 다릅니다."]
        for line in common:
            with self.subTest(line=line[:20]):
                self.assertTrue(rules.is_common(line))
        specific = ["협찬·광고·제휴로 제품이나 서비스를 받았거나 대가를 받았다면 그 사실을 글 앞부분에 직접 밝혀 주세요", "나중에 서비스가 새로 더한 줄", "", " " + common[0], "앞에 말이 붙은 " + common[0],
                    "소제목이 6개입니다 — 이 블로그 프로필의 소제목 수(3~5개)와 다릅니다. 그리고 다른 말", "소제목이 많아요 — 이 블로그 프로필의 소제목 수(3~5개)와 다릅니다."]
        for line in specific:
            with self.subTest(line=line[:20]):
                self.assertFalse(rules.is_common(line))
        self.assertFalse(rules.is_common(None))
        self.assertFalse(rules.is_common(3))
        first, second = rules.split_checks([*specific[:2], *common[:2], *specific[:2]])
        self.assertEqual((len(first), len(second)), (2, 2), "같은 줄은 한 번만 보인다")

    def test_the_common_lines_are_still_the_texts_the_service_writes(self):
        service = (CONTENT_DIR / "draft_body.py").read_text(encoding="utf-8") + (CONTENT_DIR / "draft_plan.py").read_text(encoding="utf-8")
        for prefix in rules.COMMON_PREFIXES:
            with self.subTest(prefix=prefix[:20]):
                self.assertIn(prefix, service, "서비스의 글이 바뀌었다 — 가르기 목록을 다시 본다")
        self.assertIn("이 블로그 프로필의 소제목 수(", service)
        self.assertEqual(rules.GENERIC_DOMAIN, body_bank.DOMAINS[-1])
        self.assertEqual(rules.COPY_ITEMS, ("title", "body", "all", "keywords", "tags", "summary"))
        from chanceblog_desktop.content import profiles
        self.assertEqual(dv.POST_TYPES, profiles.POST_TYPES)

    def test_real_drafts_put_every_dangerous_service_line_in_the_specific_group(self):
        warnings = [cdb.EVIDENCE_NOTE, cdb.SPONSOR_WORD_NOTE, cdb.ASSERTION_NOTE.format(words="‘최고’")]
        specific, common = rules.split_checks(warnings)
        self.assertEqual((len(specific), common), (3, ()), "세 경고는 늘 펼친 쪽")
        appliance = body_of("예시 청소기 최고 효과 정리", "예시 청소기 최고")
        specific, common = rules.split_checks(appliance.checks)
        joined = "\n".join(specific)
        self.assertIn("단정·최상급·효과를 말하는 표현", joined)
        self.assertIn("협찬·광고·제휴로", joined)
        self.assertTrue(appliance.sponsor_slot)
        self.assertEqual(len(common), 6, "고정 여섯 줄은 접힌 쪽")
        self.assertFalse([line for line in common if "협찬" in line or "단정" in line or "건강" in line or "금융" in line])
        finance = body_of("예시 주식 투자 기초", "예시 주식")
        self.assertIn("금융처럼", "\n".join(rules.split_checks(finance.checks)[0]))
        dropped = body_of("예시 청소기 고르는 기준", "예시 청소기", options=do.DraftOptions(exclude=("확인",)))
        self.assertIn("쓰지 못했습니다", "\n".join(rules.split_checks(dropped.checks)[0]))
        priced = body_of("예시 청소기 고르는 기준", "예시 청소기", options=do.DraftOptions(price_date=("예시 3,000원",), urls=("https://example.com/a",)), post_type="비교형")
        specific = "\n".join(rules.split_checks(priced.checks)[0])
        self.assertIn("입력하신 가격·날짜는 그대로 넣었습니다", specific)
        self.assertIn("입력하신 참고 주소는", specific)
        plain = body_of("예시 AI 서비스 사용법", "예시 AI 서비스")
        self.assertEqual((rules.split_checks(plain.checks)[0], len(rules.split_checks(plain.checks)[1])), ((), 6), "이 글에만 해당하는 줄이 없는 초안")

    def test_no_screen_line_has_a_command_snippet_and_the_missing_profile_line_is_the_screen_sentence(self):
        raw = "이 네이버 블로그의 프로필이 아직 없어 공통 기본값으로 만들었습니다 — `naver-profile set` 으로 프로필을 정하면 그 값이 먼저 적용됩니다."
        self.assertEqual(rules.plain_line(raw), T["drf_chk_profile"])
        self.assertEqual(rules.plain_line("새 줄 `some command --flag` 을 쓰세요"), "새 줄 을 쓰세요")
        plain = body_of("예시 후보 가 — 안내", "예시 낱말 가")
        self.assertTrue([line for line in plain.checks if "`" in line], "서비스의 줄에는 명령 조각이 있다")
        for line in (*rules.split_checks(plain.checks)[0], *rules.split_checks(plain.checks)[1]):
            self.assertNotIn("`", line)
            self.assertNotIn("naver-profile", line)

    def test_the_lines_the_screen_adds_come_from_structure(self):
        generic = types.SimpleNamespace(domain="generic", replaced=None)
        self.assertEqual(rules.derived_lines(generic), (T["drf_chk_domain"],))
        both = types.SimpleNamespace(domain="generic", replaced=("후기 형식", "정보형"))
        self.assertEqual(len(rules.derived_lines(both)), 2)
        self.assertIn("‘후기 형식’", rules.derived_lines(both)[1])
        self.assertEqual(rules.derived_lines(types.SimpleNamespace(domain="appliance", replaced=None)), ())


class SecretAndCountTest(unittest.TestCase):
    def test_key_and_token_shapes_are_found_wherever_they_sit_and_normal_writing_is_not(self):
        shapes = [KEY_SHAPED, "gh" + "p_" + "A1b2C3d4E5f6G7h8I9", "sk" + "-" + "A1b2C3d4E5f6G7h8I9j0", "ya" + "29." + "A1b2C3d4E5f6G7h8", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4", "예시글" + KEY_SHAPED + "예시글",
                  "Bea" + "rer " + "abcdefABCDEF0123456789"]       # 마지막 모양은 접두사·긴 덩어리 검사(`looks_secret`)가 못 보고 정본 패턴(`has_key_shape`)만 본다 — 변이 점검 R03 이 처음 한 바퀴에서 살아남아 더했다
        for shape in shapes:
            with self.subTest(shape=shape[:6]):
                self.assertTrue(rules.has_secret("앞의 글 " + shape + " 뒤의 글"))
        for normal in ("예시 청소기 고르는 기준을 한 줄로 정리해요.", "2026년 11월 5일", "https://blog.naver.com/example-blog-a", "A1B2", ""):
            with self.subTest(normal=normal[:10]):
                self.assertFalse(rules.has_secret(normal))
        self.assertTrue(rules.has_secret(None))
        self.assertTrue(rules.has_secret("정상", 3))

    def test_the_character_counts_are_the_services_way_of_counting(self):
        body = body_of("예시 청소기 고르는 기준", "예시 청소기")
        self.assertEqual(rules.count_text(body.body_text), (body.chars, body.chars_with_spaces))
        self.assertEqual(rules.count_text("가 나\n다"), (3, 4))
        self.assertEqual(rules.count_text(""), (0, 0))


class AddressShapeTest(unittest.TestCase):
    """독립 검증 V2: 정상 주소·파일 이름(긴 글번호·상품번호·해시·하이픈이 긴 글 주소)이 키 모양으로 오탐되어 복사 여섯 단추가 모두 잠기던 문제 — 주소·파일 이름 안에서는 **알려진 키 모양만** 막는다."""
    GHP = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9"                                  # 접두사만 있는 짧은 모양(정본 패턴이 아니라 접두사 규칙이 본다)
    SKP = "sk" + "-proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3"                       # `sk-` 로 시작하는 진짜 키 모양 — 주소 안에서는 정본 패턴(`has_key_shape`)만 이것을 본다(`sk-hynix-…` 같은 글 주소와 구분)

    def test_normal_addresses_and_file_names_are_not_key_shapes_wherever_they_sit(self):
        for address in (*NORMAL_ADDRESSES, *NORMAL_FILE_NAMES):
            for sentence in (address, f"참고한 곳은 {address} 입니다.", f"앞 글\n{address}\n뒤 글", f"({address})"):
                with self.subTest(sentence=sentence[:40]):
                    self.assertFalse(rules.has_secret(sentence), sentence)
                    self.assertEqual(rules.secret_places(("본문", sentence)), ())

    def test_known_key_shapes_inside_an_address_or_a_file_name_are_still_found(self):
        inside = (f"https://example.com/page?x={KEY_SHAPED}", f"https://example.com/?ref={self.GHP}", "https://user:" + "pw1234" + "@example.com/x", "https://example.com/%41%4B%49%41ABCDEFGHIJKLMNOP",
                  f"{KEY_SHAPED}.jpg", f"blog.naver.com/exampleaaa/{KEY_SHAPED}", f"www.example.com/a?k={self.GHP}", f"https://example.com/?k={self.SKP}")
        for sentence in inside:
            for written in (sentence, f"앞 글 {sentence} 뒤 글"):
                with self.subTest(sentence=sentence[:40]):
                    self.assertTrue(rules.has_secret(written), written)
                    places = rules.secret_places(("본문", written))
                    self.assertTrue(places)
                    self.assertTrue(all(KEY_SHAPED not in place and self.GHP not in place and self.SKP not in place for place in places), "비밀은 미리보기에 되풀이하지 않는다")
                    if self.SKP in sentence:
                        self.assertTrue(any("[가림" in place for place in places), "주소 안의 정본 키 모양은 시작한 자리부터 가려서 보인다(정본 패턴이 자리를 정한다)")

    def test_outside_an_address_the_old_rule_still_applies_exactly(self):
        from chanceblog_desktop.security.mask import has_key_shape
        from chanceblog_desktop.security.shape import looks_secret
        samples = ["예시 청소기 고르는 기준을 한 줄로 정리해요.", "d41d8cd98f00b204e9800998ecf8427e", "상품번호는 AB1234567890123456789012345 입니다", KEY_SHAPED, "앞 글 " + KEY_SHAPED + " 뒤 글", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4",
                   "ABC-1234-DEFG-5678-HIJK-9012-LMNO", "2026년 11월 5일", "가나다라마바사아자차카타파하" * 3, "Bea" + "rer " + "abcdefABCDEF0123456789", "앞 글 " + self.GHP + " 뒤 글"]
        for sample in samples:
            with self.subTest(sample=sample[:20]):
                self.assertEqual(rules.has_secret(sample), looks_secret(sample) or has_key_shape(sample), "주소·파일 이름 밖의 글은 예전 규칙 그대로다")
        self.assertTrue(rules.has_secret(KEY_SHAPED + " https://example.com/a1"), "주소 옆의 키 덩어리는 여전히 걸린다")
        self.assertTrue(rules.has_secret("https://example.com/a1 " + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"))

    def test_the_places_name_the_text_show_the_front_and_never_a_key_and_stay_within_the_limit(self):
        text = "문장이에요 " * 6 + f"https://example.com/?ref={self.GHP}" + " 뒤 글"
        places = rules.secret_places(("제목", "앞 글 " + KEY_SHAPED), ("본문", text))
        self.assertEqual(len(places), 2)
        self.assertTrue(places[0].startswith("제목 — ") and places[1].startswith("본문 — "))
        for place in places:
            self.assertLessEqual(len(place.split(" — ", 1)[1]), rules.PREVIEW + 1, "앞 40자만 보인다")
            self.assertNotIn(KEY_SHAPED, place)
            self.assertNotIn(self.GHP, place)
            self.assertNotIn(self.GHP[:4], place, "정본 모양이 아닌 접두사 키는 걸린 덩어리의 앞 8자만 보여 접두사도 되풀이하지 않는다")
        self.assertIn("[가림", places[0], "정본 비밀 모양은 가려서 보인다")
        long_login = rules.secret_places(("본문", "https://user:" + "pw1234" + "@example.com/" + "a" * 80))[0]
        self.assertLessEqual(len(long_login.split(" — ", 1)[1]), rules.PREVIEW + 1, "가린 뒤에도 긴 주소는 앞 40자만 보인다")
        many = [("본문", f"문장 {number} {chr(65 + number)}1b2C3d4E5f6G7h8I9j0K1l2M3n4") for number in range(9)]          # 의도적 갱신(PCSEC1V D16): 미리보기가 덩어리의 앞 글자를 보이지 않으므로 서로 다른 자리는 앞의 글(문맥)로 가른다
        self.assertEqual(len(rules.secret_places(*many)), rules.SPOT_LIMIT)
        self.assertEqual(rules.secret_places(("본문", "정상 글입니다.")), ())
        self.assertEqual(rules.secret_places(("본문", 123)), ("본문",), "글이 아닌 값은 이름만 짚는다")

    def test_a_long_text_full_of_addresses_is_checked_quickly(self):
        import time
        big = "\n".join("문장이에요 https://blog.naver.com/exampleaaa/223012345678 입니다." for _ in range(300))
        started = time.perf_counter()
        self.assertFalse(rules.has_secret(big))
        self.assertLess(time.perf_counter() - started, 3, "주소가 많은 긴 글도 빨리 훑는다")


class AddressSecretTest(unittest.TestCase):
    """독립 검증 D1(3차 수정) — 주소 안에서도 **이름이 비밀 낱말인 인자의 긴 값·웹훅 주소·비밀 이름 아래의 긴 경로 값·경로 글자에 붙은 `sk-` 키** 는 막는다(옛 규칙은 막았고 V2 고침이 풀었던 것).
    서비스의 `참고 URL` 칸이 거절하는 주소를 편집기가 통과시키는 모순이 없고, 정상 주소·글 106개는 하나도 막히지 않는다(오탐 0)."""
    WRAPS = ("{}", "앞 글 {} 뒤 글", "({})", "앞 글\n{}\n뒤 글", "[참고] {}")

    def test_every_secret_address_is_blocked_wherever_it_sits_and_its_preview_never_repeats_the_secret(self):
        self.assertGreaterEqual(len(SECRET_ADDRESSES), 39)
        for name, address, secret in SECRET_ADDRESSES:
            for wrap in self.WRAPS:
                written = wrap.format(address)
                with self.subTest(name=name, wrap=wrap[:6]):
                    self.assertTrue(rules.has_secret(written), written[:90])
                    places = rules.secret_places(("본문", written))
                    self.assertTrue(places)
                    for place in places:
                        self.assertNotIn(secret[:8], place, "비밀의 앞 여덟 글자도 화면에 되풀이하지 않는다")
                        self.assertLessEqual(len(place.split(" — ", 1)[1]), rules.PREVIEW + 1, "앞 40자만 보인다")

    def test_normal_addresses_and_posts_are_never_blocked(self):
        everything = (*NORMAL_MORE, *NORMAL_ADDRESSES, *NORMAL_FILE_NAMES)
        self.assertGreaterEqual(len(everything), 106)
        for address in everything:
            for wrap in self.WRAPS:
                written = wrap.format(address)
                with self.subTest(address=address[:50], wrap=wrap[:6]):
                    self.assertFalse(rules.has_secret(written), written[:90])
                    self.assertEqual(rules.secret_places(("본문", written)), ())

    def test_the_editor_is_never_weaker_than_the_reference_address_field_of_the_service(self):
        refused = 0
        for name, address, _secret in SECRET_ADDRESSES:
            if not address.startswith("https://"):
                continue
            try:
                rules.build_options({"urls": address})
            except AppError:
                refused += 1
                with self.subTest(name=name):
                    self.assertTrue(rules.has_secret(address), "서비스의 참고 URL 칸이 거절하는 비밀 주소는 편집기도 막는다")
        self.assertGreaterEqual(refused, 15, "(전제) 서비스가 거절하는 시료가 충분히 있다")

    def test_the_known_limits_stay_open_and_are_written_down(self):
        for name, address in KNOWN_LIMITS:
            with self.subTest(name=name):
                self.assertFalse(rules.has_secret(address), "정상 주소(글번호·해시·긴 글 주소)와 모양이 같아 일부러 막지 않는다 — 막게 되면 결정 기록의 한계도 고친다")
        row = next(line for line in (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines() if line.startswith("| D-312 |"))
        for word in ("경로", "쉼표", "한계"):
            self.assertIn(word, row, "한계가 결정 기록에 적혀 있다")

    def test_a_named_argument_is_pointed_at_by_its_name_and_never_echoed(self):
        secret = hexed("c1", 32)
        place = rules.secret_places(("본문", "참고 https://api.example.com/v1/data?access_token=" + secret))[0]
        self.assertIn("access_token=", place)
        self.assertIn("[가림", place)
        self.assertNotIn(secret[:6], place)
        webhook = rules.secret_places(("본문", "https://discord.com/api/webhooks/112233445566778899/" + mixed("c6", 68, "_-")))[0]
        self.assertTrue(webhook.endswith(T["drf_spot_hidden"]), "이름·모양으로 알아본 자리는 글자 없이 표시만 남는다")

    def test_a_long_unrecognized_chunk_is_hidden_without_its_first_characters(self):
        """PCSEC1V D16: 이름·모양으로 알아보지 못한 긴 영숫자 덩어리는 어디서부터인지만 짚고(`[가림]`) 앞 8글자도 화면에 되풀이하지 않는다 — 키 파생 글자를 보이지 않는 H2 와 같은 정신."""
        chunk = "D0f6YYIg" + "k3Xa9Qm2" + "Lw7Ze5Rt" + "Pb1Nc8Vh" + "Js4Ug6Wd" + "0Fi3"
        pem_body = "MIIEvQIBADANBgkq" + "hkiG9w0BAQEFAASC" + "BKcwggSjAgEAAoIB" + "AQC7VJTUt9Us8cKj"                    # 개인 키 본문 한 줄(머리 줄만 가려지고 본문 덩어리는 옛 긴 영숫자 규칙이 잡는다)
        for pem in ("-----BEGIN " + "PRIVATE KEY-----\n" + pem_body + "\n-----END " + "PRIVATE KEY-----", "앞 글\n-----BEGIN " + "PRIVATE KEY-----\n" + pem_body + "\n뒤 글"):
            with self.subTest(text=pem[:16]):
                places = rules.secret_places(("본문", pem))
                self.assertTrue(places)
                for place in places:
                    for piece in (pem_body[:8], pem_body[:4], pem_body[8:16]):
                        self.assertNotIn(piece, place, "개인 키 본문의 글자도 미리보기에 되풀이하지 않는다")
        for text in ("앞 글 " + chunk + " 뒤 글", chunk, "첫 줄\n" + chunk):
            with self.subTest(text=text[:12]):
                places = rules.secret_places(("본문", text))
                self.assertEqual(len(places), 1)
                for piece in (chunk[:8], chunk[:4], chunk[-4:]):
                    self.assertNotIn(piece, places[0])
                self.assertTrue(places[0].endswith(T["drf_spot_hidden"]), places[0])

    def test_a_preview_next_to_an_argument_name_has_balanced_brackets(self):
        """독립 검증 D4(겉모양): `…key=[가림: 주소 인자] Google API 키]` 처럼 닫는 괄호가 하나 남지 않는다."""
        key = "AI" + "za" + mixed("br", 35, "_-")
        for address in ("https://maps.example.com/api?key=" + key, "https://maps.example.com/api?x=1&key=" + key + "&y=2", "https://example.com/?k=" + key, "https://example.com/x?token=" + mixed("br2", 30)):
            for place in rules.secret_places(("본문", "참고 " + address)):
                with self.subTest(place=place):
                    self.assertEqual(place.count("["), place.count("]"), "닫는 괄호가 하나 남지 않는다")
                    self.assertNotIn("주소 인자] ", place, "가린 이름이 한 번 더 가려져 글자가 남지 않는다")

    def test_a_short_or_plain_value_and_a_name_that_is_no_secret_word_pass(self):
        for address in ("https://example.com/p?token=123456", "https://example.com/p?key=value", "https://example.com/p?sig=ok", "https://example.com/p?code=200", "https://example.com/p?keyword=" + mixed("kw", 40),
                        "https://example.com/p?ref=" + mixed("rf", 40), "https://example.com/p?id=" + mixed("id", 40), "https://example.com/p?token=" + "1" * 30, "https://example.com/reset/short"):
            with self.subTest(address=address[:40]):
                self.assertFalse(rules.has_secret(address), address)

    def test_sk_keys_stuck_to_path_letters_are_found_but_task_and_risk_slugs_are_not(self):
        for key in ("sk-" + "proj-" + mixed("sk1", 60, "_-"), "sk-" + "ant-api03-" + mixed("sk2", 93, "_-"), "sk-" + "or-v1-" + hexed("sk3", 64), "sk-" + mixed("sk4", 48)):
            with self.subTest(key=key[:8]):
                self.assertTrue(rules.has_secret("https://example.com/path/abc" + key))
                self.assertTrue(rules.has_secret("https://example.com/?k=" + key))
        for slug in ("https://www.notion.so/Task-" + hexed("sk5", 32), "https://example.com/task-proj-management-tools-for-small-teams-2026", "https://example.com/blog/risk-management-guide-for-2026",
                     "https://example.com/desk-" + hexed("sk6", 40), "https://example.com/sk-hynix-memory-news-2026"):
            with self.subTest(slug=slug[:50]):
                self.assertFalse(rules.has_secret(slug), slug)


class ScanLimitTest(unittest.TestCase):
    """독립 검증 D3 — 안전 관련 변이 N-03(퍼센트로 쓴 글자를 세 겹까지 푼다)·N-05(너무 긴 글은 믿지 않고 막는다)·N-11(작은 복사도 자기 글의 키 모양을 본다)을 못박는다."""

    @staticmethod
    def coded(text, layers):
        for _ in range(layers):
            text = "".join("%" + format(ord(ch), "02X") for ch in text)
        return text

    def test_a_key_written_in_percent_codes_is_found_up_to_three_layers_and_never_echoed(self):
        key = "gh" + "p_" + mixed("pct", 24)
        for layers in (1, 2, 3):
            address = "https://example.com/?r=" + self.coded(key, layers)
            with self.subTest(layers=layers):
                self.assertTrue(rules.has_secret(address))
                self.assertTrue(rules.has_secret("앞 글 " + address + " 뒤 글"))
                for place in rules.secret_places(("본문", address)):
                    self.assertNotIn(key[:8], place)
        self.assertFalse(rules.has_secret("https://example.com/?r=" + self.coded("가나다", 3)), "퍼센트로 쓴 평범한 글은 막지 않는다")

    def test_a_text_over_the_scan_limit_is_blocked_instead_of_let_through(self):
        from chanceblog_desktop.security.shape import MAX_SCAN_CHARS
        long_text = "가" * (MAX_SCAN_CHARS + 1)
        self.assertTrue(rules.has_secret(long_text))
        self.assertEqual(rules.secret_spots(long_text), ((0, 1),))
        self.assertTrue(rules.secret_places(("본문", long_text)))
        self.assertFalse(rules.has_secret("가" * MAX_SCAN_CHARS), "한도 안의 평범한 글은 막지 않는다")
        controller = made(SOFTWARE)
        controller.set_body(long_text)
        self.assertEqual(controller.copy_decision("body")[0], "blocked")
        self.assertIsNone(controller.final_text("body"))

    def test_the_small_copies_block_a_key_shape_in_their_own_text(self):
        controller = made(APPLIANCE)
        self.assertEqual([controller.copy_decision(item)[0] for item in ("keywords", "tags", "summary")], ["copy"] * 3, "(전제) 깨끗한 초안은 작은 복사가 된다")
        body = controller.result.body
        controller.result = dataclasses.replace(controller.result, body=dataclasses.replace(body, core_keywords=("예시 청소기", KEY_SHAPED), tags=("예시", KEY_SHAPED), tags_text="#예시 #" + KEY_SHAPED, summary="한 줄 요약 " + KEY_SHAPED))
        for item in ("keywords", "tags", "summary"):
            with self.subTest(item=item):
                kind, dialog = controller.copy_decision(item)
                self.assertEqual(kind, "blocked")
                self.assertNotIn(KEY_SHAPED, dialog["body"], "막음 안내창도 키를 되풀이하지 않는다")
                self.assertIsNone(controller.final_text(item))
        self.assertEqual(controller.copy_decision("body")[0], "confirm", "본문 복사는 작은 복사의 키와 상관없다")


class ThirdRoundGapTest(unittest.TestCase):
    """독립 검증 D3 — 변이에 살아남던 나머지(N-07·N-10·N-12·N-20·N04·N13)를 못박는다."""
    OWN_MARK = "영양제 성분표를 읽는 방법을 정리했어요."                                  # 판정기가 '표시만(mark)' 으로 읽는 문장

    def test_a_sentence_stays_whole_up_to_four_hundred_letters_and_longer_ones_are_cut_into_four_hundred(self):
        self.assertEqual(len(rules.health_units("가" * 300)), 1, "300자 한 문장은 한 조각이다(조각 한도를 줄이면 여러 조각으로 갈린다)")
        self.assertEqual([len(unit) for unit in rules.health_units("가" * 900)], [400, 400, 100])
        self.assertEqual(len(rules.health_units("가" * 400)), 1)

    def test_a_health_word_in_the_reference_address_field_is_not_the_writers_claim(self):
        base = HealthSecondLineTest.BASE
        controller = made_from(base, options={"urls": "https://ko.wikipedia.org/wiki/당뇨병"})
        self.assertEqual(controller.state, "normal")
        self.assertEqual(controller.user_health().stage, "general", "참고 주소 칸은 글이 아니다")
        self.assertEqual(controller._user_health_lines(), ())
        written = made_from(base, options={"message": "당뇨 환자의 식단 기록 방법을 정리했어요."})
        self.assertTrue(written._user_health_lines(), "(대조) 같은 말을 글로 적으면 줄이 생긴다")

    def test_the_mark_stage_of_the_writers_own_text_adds_a_check_line_but_does_not_block(self):
        self.assertEqual(safety.check_text([self.OWN_MARK]).stage, "mark", "(전제)")
        controller = made_from(HealthSecondLineTest.BASE, options={"message": self.OWN_MARK})
        self.assertEqual(controller._user_health_lines(), (T["drf_chk_health_mark"],))
        specific, _common, gate_lines, _unknown = controller.checks()
        self.assertIn(T["drf_chk_health_mark"], specific)
        self.assertIn(T["drf_chk_health_mark"], gate_lines)
        self.assertEqual(controller.blocks_for("all"), (), "표시만 단계는 막지 않는다")

    def test_the_block_dialog_names_at_most_the_place_limit_even_when_two_reasons_add_up(self):
        controller = made(SOFTWARE)
        blocks = (("keyshape", ("본문 — 첫째", "본문 — 둘째", "본문 — 셋째")), ("health", ("제목 — 넷째", "제목 — 다섯째", "제목 — 여섯째")))
        dialog = controller.blocked_dialog(blocks)
        lines = [line for line in dialog["body"].splitlines() if line.startswith(T["drf_gate_line"].format(text=""))]
        self.assertEqual(len(lines), rules.SPOT_LIMIT)
        self.assertEqual(lines[0], T["drf_gate_line"].format(text="본문 — 첫째"))
        self.assertIn(T["drf_secret_body"], dialog["body"])
        self.assertIn(T["drf_health_body"], dialog["body"])

    def test_a_sentence_the_writer_typed_is_judged_for_an_invented_experience_unless_the_experience_field_holds_it(self):
        sentence = "직접 써 보니 정말 좋았어요."
        self.assertTrue(rules.claims_of(sentence, {"message": sentence}), "경험 칸이 비어 있으면 다른 칸에 같은 문장을 적어도 경험을 지어낸 것으로 읽힌다")
        self.assertFalse([note for note in rules.claims_of(sentence, {"experience": sentence}) if note.violation], "경험 칸에 적은 문장은 위반이 아니다")
        self.assertTrue([note for note in rules.claims_of(sentence, {}) if note.violation])

    def test_an_unknown_copy_item_is_unavailable_whatever_the_text_holds(self):
        controller = made(APPLIANCE)
        self.assertEqual(controller.copy_decision("body")[0], "confirm", "(전제) 이 초안은 본문 복사에 확인창이 뜬다")
        for item in ("nope", "", "Body", None):
            with self.subTest(item=item):
                self.assertEqual(controller.copy_decision(item), ("unavailable", None))
        controller.set_body(controller.body + "\n" + KEY_SHAPED)
        self.assertEqual(controller.copy_decision("body")[0], "blocked", "(전제)")
        self.assertEqual(controller.copy_decision("nope"), ("unavailable", None), "키 모양이 있어도 모르는 항목은 막음 안내가 아니라 쓸 수 없는 항목이다")


class ChangedCharsTest(unittest.TestCase):
    GENERATED = "첫 문단이에요 하나.\n\n둘째 문단이에요 둘.\n\n셋째 문단이에요 셋."
    TITLES = ("제목 후보 하나", "제목 후보 둘", "제목 후보 셋")

    def changed(self, title="제목 후보 하나", body=None):
        return rules.changed_chars("제목 후보 하나", self.TITLES, title, self.GENERATED, self.GENERATED if body is None else body)

    def test_only_a_real_change_counts(self):
        self.assertEqual(self.changed(), 0)
        self.assertEqual(self.changed(body="첫 문단이에요   하나.\r\n\r\n\r\n둘째 문단이에요 둘.\n \n셋째 문단이에요\n셋.\n"), 0, "줄바꿈·공백만 다른 것은 고친 것이 아니다")
        self.assertEqual(self.changed(title="제목 후보 둘"), 0, "다른 제목 후보를 고른 것은 고친 것이 아니다")

    def test_a_changed_added_or_removed_paragraph_counts_its_length_and_a_new_title_counts_too(self):
        second = "둘째 문단이에요 둘."
        self.assertEqual(self.changed(body=self.GENERATED.replace("둘째 문단이에요 둘.", "둘째 문단이에요 다름.")), len("둘째 문단이에요 다름."), "문단 안에서 한 낱말만 고쳐도 그 문단 전체를 센다(문단 단위)")
        self.assertEqual(self.changed(body=self.GENERATED + "\n\n내가 더한 문단이에요."), len("내가 더한 문단이에요."))
        self.assertEqual(self.changed(body=self.GENERATED.replace("\n\n" + second, "")), len(second))
        self.assertEqual(self.changed(title="내가 고친 새 제목이에요"), len("내가 고친 새 제목이에요"))
        self.assertEqual(self.changed(title="", body=""), sum(len(item) for item in rules.paragraphs_of(self.GENERATED)) + len("제목 후보 하나"), "전부 지우면 지운 문단과 제목을 모두 센다")

    def test_the_unchanged_boundary_is_one_hundred_twenty_characters(self):
        self.assertEqual(rules.UNCHANGED_BELOW, 120)
        for size, unchanged in ((119, True), (120, False), (0, True)):
            with self.subTest(size=size):
                found = rules.inspect_text("제목 후보 하나", self.GENERATED + ("\n\n" + "가" * size if size else ""), generated_title="제목 후보 하나", generated_titles=self.TITLES, generated_body=self.GENERATED)
                self.assertEqual((found.changed, found.unchanged), (size, unchanged))


class ClaimsTest(unittest.TestCase):
    def test_an_invented_experience_and_an_unverified_price_are_found_with_a_masked_preview(self):
        found = rules.claims_of("예시 청소기를 정리했어요.\n\n직접 써 보니 정말 좋았습니다. 가격은 12,000원이었어요.")
        kinds = {(note.violation, note.pair[0]) for note in found}
        self.assertIn((True, claim_check.EXPERIENCE_USE), kinds)
        self.assertIn((False, claim_check.PRICE), kinds)
        self.assertTrue(all(len(note.preview) <= rules.PREVIEW for note in found))
        self.assertEqual(rules.claims_of("예시 청소기를 고르는 순서를 정리했어요."), ())
        leaked = rules.claims_of("직접 써 보니 정말 좋았습니다 " + KEY_SHAPED)
        self.assertTrue(leaked)
        self.assertNotIn(KEY_SHAPED, " ".join(note.preview for note in leaked), "비밀 모양은 가리고 보인다")

    def test_a_sentence_the_user_typed_as_the_experience_is_not_a_violation_but_a_price_still_is_reviewed(self):
        mine = "직접 써 보니 정말 좋았습니다."
        options = {"experience": mine}
        self.assertEqual([note for note in rules.claims_of(mine, options) if note.violation], [])
        self.assertTrue([note for note in rules.claims_of(mine) if note.violation], "경험을 적지 않았으면 같은 문장도 위반")
        self.assertTrue([note for note in rules.claims_of("가격은 12,000원이었어요.", {"experience": mine}) if not note.violation])
        self.assertEqual(rules.user_texts({"message": " 한 줄 ", "must_include": "하나\n\n 둘 ", "urls": ""}), ("한 줄", "하나", "둘"))


class GateTest(unittest.TestCase):
    def inspection(self, **more):
        values = dict(secret=False, claims=(), changed=500, unchanged=False, chars=1900, spaced=2500)
        values.update(more)
        return rules.Inspection(**values)

    def note(self, word="써 보니", category=claim_check.EXPERIENCE_USE):
        return rules.ClaimNote(True, "직접 사용·체험했다는 주장", f"직접 {word} 정말 좋았습니다.", (category, word))

    def test_a_clean_draft_has_no_gate(self):
        gate = rules.gate_for("body", self.inspection(), (), False, {})
        self.assertEqual((gate.blocked, gate.reasons, gate.new, gate.needs_dialog, gate.count), (False, (), False, False, 0))

    def test_a_key_shape_blocks_and_the_groups_are_listed_in_a_fixed_order(self):
        inspection = self.inspection(secret=True, claims=(self.note(),), unchanged=True)
        gate = rules.gate_for("all", inspection, ("협찬 줄",), True, {})
        self.assertTrue(gate.blocked)
        self.assertEqual([name for name, _items in gate.reasons], ["check", "domain", "claims", "unchanged"])
        self.assertEqual(gate.count, 4)

    def test_the_soft_unchanged_guidance_is_for_the_body_not_for_a_title_only_copy(self):
        inspection = self.inspection(unchanged=True)
        self.assertEqual([name for name, _items in rules.gate_for("body", inspection, (), False, {}).reasons], ["unchanged"])
        self.assertEqual([name for name, _items in rules.gate_for("all", inspection, (), False, {}).reasons], ["unchanged"])
        self.assertEqual(rules.gate_for("title", inspection, (), False, {}).reasons, ())

    def test_what_was_confirmed_is_not_asked_again_but_something_new_is(self):
        first = rules.gate_for("body", self.inspection(claims=(self.note(),)), ("협찬 줄",), True, {})
        self.assertTrue(first.needs_dialog)
        acknowledged = {name: set(keys) for name, keys in first.keys.items()}
        again = rules.gate_for("body", self.inspection(claims=(self.note(),)), ("협찬 줄",), True, acknowledged)
        self.assertEqual((again.new, again.needs_dialog, again.count), (False, False, 3), "새 것이 없으면 묻지 않는다")
        fewer = rules.gate_for("body", self.inspection(), ("협찬 줄",), True, acknowledged)
        self.assertFalse(fewer.new, "줄어든 것은 다시 묻지 않는다")
        more = rules.gate_for("body", self.inspection(claims=(self.note(), self.note("다녀왔", claim_check.EXPERIENCE_VISIT))), ("협찬 줄",), True, acknowledged)
        self.assertTrue(more.new and more.needs_dialog)
        self.assertEqual(more.count, 4, "새 것이 있으면 지금의 모든 항목이 확인창에 보인다")
        another = rules.gate_for("body", self.inspection(), ("협찬 줄", "새로 생긴 줄"), True, acknowledged)
        self.assertTrue(another.new)

    def test_only_title_body_and_all_have_a_gate(self):
        for item in ("keywords", "tags", "summary", "other"):
            with self.assertRaises(ValueError):
                rules.gate_for(item, self.inspection(), (), False, {})


class CompletionConditionsTest(unittest.TestCase):
    """P4e 완료 조건(운영자 2026-11-09) 중 다른 시험이 따로 못박지 않던 것 — ⑬ 실제 경험·방문·가격·협찬을 임의로 만들지 않음 · ⑭ 출처와 확인 필요 상태 표시 · ⑫ 건강 C 는 자동 중지(서비스 시험에 세 모양)."""

    def test_a_generated_draft_never_invents_experience_visits_prices_dates_or_sponsorship(self):
        checked = 0
        for row in CATALOG:
            if safety.assess(row).stop:
                continue
            for blog in ("naver_a", "naver_b"):
                with self.subTest(topic=row.topic[:14], blog=blog):
                    body = body_of(row.topic, row.primary_keyword, tuple(row.secondary_keywords), blog)
                    shown = "\n".join((body.title_text, body.body_text, body.summary, body.tags_text))
                    self.assertEqual(rules.claims_of(body.body_text) + rules.claims_of(body.selected_title), (), "지어낸 경험·사례·가격·날짜·통계로 읽히는 문장이 없다(`check/claims`)")
                    self.assertIsNone(re.search(r"[0-9]", shown), "숫자(가격·날짜·수치)를 지어 넣지 않는다")
                    self.assertFalse([word for word in ("협찬을 받아", "제공받아", "원고료", "내돈내산", "직접 써 보니", "다녀왔", "방문해 보니", "구매해 보니") if word in shown], "경험·방문·협찬을 한 것처럼 쓰지 않는다")
                    checked += 1
        self.assertGreaterEqual(checked, 8)

    def test_the_right_column_carries_every_field_the_operator_listed_and_the_copy_buttons_copy_them(self):
        """완료 조건 ④~⑨: 핵심·보조 키워드·태그·추천 카테고리·한 줄 요약·확인 권장이 서비스의 값 그대로 오른쪽 칸에 있고, 키워드·태그·요약은 각자 복사 단추로 그 값만 복사한다."""
        controller = made(APPLIANCE)
        body, side = controller.result.body, controller.view()["normal"]["side"]
        self.assertTrue(body.core_keywords and body.sub_keywords and body.tags and body.summary and body.checks)
        self.assertEqual((side["keywords"]["core"], side["keywords"]["sub"]), ([rules.shown(item, 40) for item in body.core_keywords], [rules.shown(item, 40) for item in body.sub_keywords]))
        self.assertEqual(side["tags"]["items"], [rules.shown(item, 40) for item in body.tags])
        self.assertEqual(side["summary"]["text"], rules.shown(body.summary, 200))
        self.assertEqual((side["category"]["text"], side["category"]["missing"]), (rules.shown(body.category, 60) if body.category else T["drf_category_none"], not body.category))
        shown_checks = len(side["checks"]["specific"]["lines"]) + len(side["checks"]["common"]["lines"])
        self.assertGreaterEqual(shown_checks, len(set(body.checks)) - 1, "서비스의 확인 권장이 빠짐없이 두 묶음에 나뉘어 보인다(같은 글은 한 번만)")
        self.assertEqual(controller.text_for("keywords"), dv.KEYWORD_SEPARATOR.join((*body.core_keywords, *body.sub_keywords)))
        self.assertEqual((controller.text_for("tags"), controller.text_for("summary")), (body.tags_text, body.summary))
        for item in ("keywords", "tags", "summary"):
            kind, text = controller.copy_decision(item)
            self.assertEqual((kind, text), ("copy", controller.text_for(item)))

    def test_an_experience_appears_in_the_draft_only_when_the_user_typed_it(self):
        typed = "직접 써 보니 화면이 단순해서 쓰기 편했어요."
        plain = body_of(SOFTWARE.topic, SOFTWARE.primary_keyword, (), "naver_a")
        given = body_of(SOFTWARE.topic, SOFTWARE.primary_keyword, (), "naver_a", options=do.DraftOptions(experience=typed))
        self.assertNotIn(typed, plain.body_text)
        self.assertIn(typed, given.body_text, "사용자가 적은 경험은 적은 그대로 들어간다")
        self.assertEqual(rules.claims_of(plain.body_text), ())
        self.assertEqual(rules.claims_of(given.body_text, {"experience": typed}), (), "사용자가 적은 문장은 위반으로 세지 않는다(서비스가 만들 때와 같다)")
        self.assertTrue(any("경험" in line for line in plain.checks), "경험을 넣지 않았다는 확인 권장이 따라 붙는다")

    def test_a_category_the_service_chose_is_shown_and_a_missing_one_says_so(self):
        """독립 검증 V4(변이 N32): 시험·시료 프로필에는 추천 카테고리가 없어 '정하지 못했어요' 만 보였다 — 서비스가 카테고리를 정한 초안의 표시 경로를 못박는다."""
        controller = made(GENERIC)
        side = controller.view()["normal"]["side"]["category"]
        self.assertEqual((side["title"], side["text"], side["missing"]), (T["drf_side_category"], T["drf_category_none"], True))
        controller.result = dataclasses.replace(controller.result, body=dataclasses.replace(controller.result.body, category="예시 생활 정보"))
        side = controller.view()["normal"]["side"]["category"]
        self.assertEqual((side["text"], side["missing"]), ("예시 생활 정보", False), "서비스가 정한 카테고리가 그대로 보인다")
        controller.result = dataclasses.replace(controller.result, body=dataclasses.replace(controller.result.body, category="예시 " + KEY_SHAPED))
        self.assertNotIn(KEY_SHAPED, controller.view()["normal"]["side"]["category"]["text"], "보이는 글은 비밀 모양을 가린다")

    def test_the_checks_card_says_where_the_facts_come_from_and_how_many_things_need_checking(self):
        controller = made(APPLIANCE)
        card = controller.view()["normal"]["side"]["checks"]
        specific, common = len(card["specific"]["lines"]), len(card["common"]["lines"])
        self.assertGreaterEqual(specific + common, 1)
        self.assertEqual(card["status"], T["drf_chk_status"].format(source=T["drf_chk_source_none"], total=specific + common, specific=specific))
        self.assertIn("직접 확인", card["status"], "참고 주소가 없으면 사실·가격·날짜는 직접 확인하라고 말한다")
        controller.set_option("urls", "https://example.com/a\n\nhttps://example.com/b")
        self.assertTrue(controller.regen_dialog() is not None, "적은 선택 입력을 아직 반영하지 않은 것도 고친 내용이다")
        drive(controller, controller.start_regenerate)
        card = controller.view()["normal"]["side"]["checks"]
        self.assertIn(T["drf_chk_source_some"].format(n=2), card["status"], "반영한 참고 주소의 개수(빈 줄은 세지 않는다)가 출처로 보인다")
        self.assertNotIn("https://", card["status"], "주소 글은 이 줄에 되풀이하지 않는다")
        self.assertIn("확인 필요", card["status"])


class HealthSecondLineTest(unittest.TestCase):
    """독립 검증 V1②·V3 — 건강 효과 단정의 **두 번째 방어선**. 후보의 제목·키워드는 서비스가 이미 판정해 자동 초안 중지로 막는다. 이 화면은 거기에 더해 복사할 글 자체(서비스가 만든 글·사용자가 적은 선택 입력·고친 글·고친 제목)를
    문장 단위로 주제 엔진의 판정기(`topics.safety`)에 한 번 더 걸어 중지 단계(C)면 복사를 막고, 표시만·근거 확인 단계(A·B)는 직접 쓴 글에 한해 확인 권장 줄을 더한다. 판정기 자체의 낱말·표현 한계는 이 묶음이 고치지 않는다(별도 묶음)."""
    BASE = engine(910, "예시 청소기 고르는 기준", "예시 청소기")

    def test_the_stage_names_and_the_stop_stage_are_the_engines(self):
        self.assertEqual(rules.HEALTH_STAGES, tuple(safety.HEALTH_STAGES))
        self.assertEqual(rules.HEALTH_STOP, safety.STAGE_STOP)

    def test_units_are_sentences_long_ones_are_cut_and_a_non_text_has_none(self):
        self.assertEqual(rules.health_units("첫 문장이에요. 둘째 문장이에요?\n셋째 줄"), ("첫 문장이에요.", "둘째 문장이에요?", "셋째 줄"))
        for empty in ("", "  \n ", None, 7):
            self.assertEqual(rules.health_units(empty), ())
        long = "가" * (rules.HEALTH_UNIT_MAX * 2 + 5)
        self.assertEqual([len(unit) for unit in rules.health_units(long)], [rules.HEALTH_UNIT_MAX, rules.HEALTH_UNIT_MAX, 5])

    def test_the_review_gives_the_highest_stage_and_a_masked_preview_of_the_stopped_pieces_only(self):
        review = drafts.review_health(("본문", ("영양제 바로 알기", "이 영양제는 피로를 즉시 없애줍니다", "")), ("제목", ("당뇨 100% 보장",)))
        self.assertEqual((review.stage, review.places), ("stop", ("본문 — 이 영양제는 피로를 즉시 없애줍니다", "제목 — 당뇨 100% 보장")))
        self.assertEqual(drafts.review_health(), rules.HealthReview("general", ()))
        self.assertEqual(drafts.review_health(("본문", (None, 5, "  "))), rules.HealthReview("general", ()), "글이 아니거나 빈 조각은 보지 않는다")
        self.assertEqual(drafts.review_health(("본문", ("무선 청소기 고르는 기준",))).stage, "general")
        self.assertEqual(drafts.review_health(("본문", ("영양제 바로 알기",))).places, (), "중지가 아니면 짚을 자리가 없다")
        self.assertEqual(len(drafts.review_health(("본문", OPERATOR_C * 2)).places), rules.SPOT_LIMIT)
        self.assertEqual(drafts.review_health(("본문", ("피로를 즉시 줄이는 방법 " + KEY_SHAPED,))).places[0].count(KEY_SHAPED), 0, "비밀 모양은 미리보기에서 가린다")
        self.assertEqual(drafts.review_health(("본문", ("피로를 즉시 줄이는 방법",))).stage, safety.check_text(["피로를 즉시 줄이는 방법"]).stage, "조각 하나의 결과는 엔진 판정기와 같다")

    def test_the_engine_judge_is_asked_sentence_by_sentence_so_far_apart_words_do_not_turn_a_normal_draft_into_a_claim(self):
        row = engine(911, "눈이 피로할 때 모니터 위치 확인하기", "눈이 피로할")
        controller = made_from(row)
        self.assertEqual(controller.state, "normal")
        body = controller.draft_body()
        whole = safety.check_text([controller.title, controller.body, body.summary, body.tags_text]).stage
        self.assertEqual(whole, "stop", "(전제) 글 전체를 한 덩어리로 넣으면 정상 초안이 중지로 읽힌다 — 그래서 문장 단위로 본다")
        self.assertNotEqual(controller.health_for("all").stage, "stop")
        self.assertEqual(controller.blocks_for("all"), ())

    def test_the_nine_operator_examples_block_the_copy_in_the_options_the_editor_and_the_title(self):
        for sentence in OPERATOR_C:
            for field in ("message", "opinion"):                                                 # 선택 입력 — 초안에 그대로 들어간다
                with self.subTest(sentence=sentence[:12], place=field):
                    controller = made_from(self.BASE, options={field: sentence})
                    self.assertIn(sentence, controller.body, "적은 글이 본문에 들어갔다")
                    for item in ("body", "all"):
                        kind, dialog = controller.copy_decision(item)
                        self.assertEqual(kind, "blocked", (item, sentence))
                        self.assertIsNone(controller.final_text(item))
                        self.assertIsNone(controller.confirm_copy(item))
                    self.assertIn(T["drf_health_body"], dialog["body"])
                    self.assertIn(T["drf_where_head"], dialog["body"])
                    self.assertTrue([line for line in dialog["body"].splitlines() if line.startswith("· 본문 — ") and sentence[:10] in line], "어느 문장이 걸렸는지 앞부분을 짚는다")
                    self.assertEqual((dialog["ok"], dialog["cancel"]), (T["drf_secret_ok"], None), "확인만 있는 안내창이다(우회 없음)")
                    self.assertNotEqual(controller.copy_decision("title")[0], "blocked", "제목은 그 글이 아니다")
            with self.subTest(sentence=sentence[:12], place="editor"):                             # 편집기에 직접 쓴 글
                controller = made_from(self.BASE)
                self.assertEqual([item for item in ("body", "all") if controller.blocks_for(item)], [], "(전제) 고치기 전에는 막지 않는다")
                controller.set_body(controller.body + "\n\n" + sentence)
                self.assertEqual([controller.copy_decision(item)[0] for item in ("body", "all")], ["blocked", "blocked"])
                controller.inspect()
                card = controller.view()["normal"]["side"]["inspect"]
                self.assertEqual((card["tone"], card["status"]), ("error", T["drf_inspect_health_stop"]))
                self.assertTrue([line for line in card["lines"] if sentence[:10] in line])
                controller.set_body(controller.draft_body().body_text)
                self.assertEqual(controller.copy_decision("body")[0] != "blocked", True, "고치면 다시 복사할 수 있다")
            with self.subTest(sentence=sentence[:12], place="title"):                              # 제목 칸
                controller = made_from(self.BASE)
                controller.set_title(sentence)
                self.assertEqual([controller.copy_decision(item)[0] for item in ("title", "all")], ["blocked", "blocked"])
                self.assertNotEqual(controller.copy_decision("body")[0], "blocked", "본문은 그 글이 아니다")
                kind, dialog = controller.copy_decision("title")
                self.assertTrue([line for line in dialog["body"].splitlines() if line.startswith("· 제목 — ")])

    def test_daily_sentences_and_the_ab_control_sentences_never_block(self):
        controller = made_from(self.BASE)
        base = controller.draft_body().body_text
        for sentence in (*DAILY, *CONTROL):
            with self.subTest(sentence=sentence[:16]):
                controller.set_body(base + "\n\n" + sentence)
                controller.set_title(sentence)
                self.assertEqual([kind for kind, _places in controller.blocks_for("all")], [])
        for sentence in CONTROL[::9]:                                                           # 선택 입력으로도 — 초안을 새로 만들어야 해서 몇 개만
            with self.subTest(sentence=sentence[:16], place="option"):
                controller = made_from(self.BASE, options={"message": sentence, "opinion": sentence})
                self.assertEqual([kind for kind, _places in controller.blocks_for("all")], [])

    def test_generated_drafts_of_health_looking_candidates_are_never_blocked(self):
        checked = 0
        for number, sentence in enumerate(CONTROL, start=920):
            controller = made_from(engine(number, sentence, " ".join(sentence.split()[:2])))
            if controller.state != "normal":                                                     # 후보가 자동 초안 중지면 초안이 없다 — 막을 글도 없다
                continue
            checked += 1
            for item in rules.COPY_ITEMS:
                self.assertEqual([kind for kind, _places in controller.blocks_for(item) if kind == "health"], [], (sentence, item))
        self.assertGreaterEqual(checked, 30, "대조 후보 40개 중 대부분은 초안이 나온다")

    def test_a_health_word_in_the_users_own_text_adds_a_check_line_but_the_candidates_own_health_topic_does_not(self):
        lines = lambda controller: controller.view()["normal"]["side"]["checks"]["specific"]["lines"]            # noqa: E731
        own = (T["drf_chk_health_mark"], T["drf_chk_health_evidence"])
        controller = made(HEALTH)
        self.assertFalse([line for line in lines(controller) if line in own], "후보 글의 건강 낱말은 서비스가 이미 줄을 붙인다 — 같은 말을 되풀이하지 않는다")
        controller.set_body(controller.body + "\n\n영양제는 건강에 도움이 된다고 해요.")
        self.assertTrue([line for line in lines(controller) if line in own], "직접 쓴 글의 건강 낱말은 확인 권장 줄이 된다")
        kind, dialog = controller.copy_decision("body")
        self.assertEqual(kind, "confirm")
        self.assertTrue([line for line in own if line in dialog["body"]], "첫 복사 확인창에도 보인다")
        self.assertEqual(controller.confirm_copy("body"), controller.body)
        self.assertEqual(controller.copy_decision("body")[0], "copy", "확인한 줄은 다시 묻지 않는다")
        again = made_from(self.BASE, options={"message": "영양제는 건강에 도움이 된다고 해요."})
        self.assertTrue([line for line in lines(again) if line in own], "선택 입력에 적은 건강 낱말도 같다")
        self.assertFalse([line for line in lines(made_from(self.BASE)) if line in own], "건강 낱말이 없으면 줄도 없다")

    def test_the_check_card_names_what_it_looked_at_and_shows_the_stop_and_the_careful_note(self):
        controller = made(SOFTWARE)
        controller.set_body(controller.body + "\n\n" + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8)
        controller.inspect()
        card = controller.view()["normal"]["side"]["inspect"]
        self.assertEqual((card["tone"], card["status"]), ("ok", T["drf_inspect_ok"]))
        for word in ("경험", "가격", "날짜", "통계", "키 모양", "건강 단정", "직접 확인"):
            self.assertIn(word, card["status"], "초록 문구는 본 범위와 못 보는 것을 밝힌다")
        careful = made(SOFTWARE)
        careful.set_body(careful.body + "\n\n" + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8 + "\n\n영양제는 건강에 도움이 된다고 해요.")
        careful.inspect()
        card = careful.view()["normal"]["side"]["inspect"]
        self.assertEqual(card["tone"], "warning")
        self.assertIn(T["drf_inspect_health_check"], [card["status"], *card["lines"]])
        self.assertNotEqual(card["status"], T["drf_inspect_ok"], "건강 낱말이 있는데 초록 문구를 보이지 않는다")
        controller.set_body(controller.body + "\n\n이 영양제는 피로를 즉시 없애줍니다.")
        controller.inspect()
        card = controller.view()["normal"]["side"]["inspect"]
        self.assertEqual((card["tone"], card["status"]), ("error", T["drf_inspect_health_stop"]))
        self.assertEqual(card["lines"][0], T["drf_gate_line"].format(text="본문 — 이 영양제는 피로를 즉시 없애줍니다."), "걸린 문장이 맨 위에 보인다")

    def test_the_small_copies_are_judged_on_their_own_text_and_a_claim_after_the_dialog_still_blocks(self):
        controller = made(APPLIANCE)
        self.assertEqual([controller.copy_decision(item)[0] for item in ("keywords", "tags", "summary")], ["copy"] * 3)
        body = controller.result.body
        controller.result = dataclasses.replace(controller.result, body=dataclasses.replace(body, summary="영양제로 불면이 바로 치료됩니다", tags=("예시", "당뇨 100% 보장"), tags_text="#예시 #당뇨 100% 보장"))
        self.assertEqual([controller.copy_decision(item)[0] for item in ("keywords", "tags", "summary")], ["copy", "blocked", "blocked"])
        kind, dialog = controller.copy_decision("summary")
        self.assertTrue([line for line in dialog["body"].splitlines() if line.startswith("· 한 줄 요약 — 영양제로 불면이")])
        self.assertIsNone(controller.final_text("summary"))
        fresh = made(APPLIANCE)
        self.assertEqual(fresh.copy_decision("body")[0], "confirm")
        fresh.set_body(fresh.body + "\n\n피로를 즉시 줄이는 방법을 알려 드릴게요.")                 # 확인창이 떠 있는 동안 글에 단정이 생겼다
        self.assertIsNone(fresh.confirm_copy("body"))
        self.assertIsNone(fresh.copy_asked)


class AddressAndOptionsTest(unittest.TestCase):
    def test_the_write_address_is_made_only_from_a_plain_naver_blog_address(self):
        self.assertEqual(rules.naver_write_url("https://blog.naver.com/example-blog-a"), "https://blog.naver.com/example-blog-a?Redirect=Write")
        self.assertEqual(rules.naver_write_url("https://blog.naver.com/example_blog-1/"), "https://blog.naver.com/example_blog-1?Redirect=Write")
        for wrong in ("http://blog.naver.com/example-blog-a", "https://blog.naver.com.evil.example/a", "https://evil.example/blog.naver.com/a", "https://m.blog.naver.com/example-blog-a", "https://blog.naver.com/",
                      "https://blog.naver.com", "https://blog.naver.com/a/b", "https://user:pass@blog.naver.com/a", "https://blog.naver.com:8443/a", "https://blog.naver.com/a?x=1", "https://blog.naver.com/a#top",
                      "https://blog.naver.com/a b", "https://blog.naver.com/" + "a" * 41, "javascript:alert(1)", "", None, 3, "blog.naver.com/a", "https://blog.naver.com/한글", "https://blog.naver.com/a%2Fb"):
            with self.subTest(wrong=str(wrong)[:30]):
                self.assertEqual(rules.naver_write_url(wrong), "")

    def test_the_two_column_limit_is_1280_and_the_editor_height_is_inside_the_agreed_range(self):
        """창 논리 폭 1280 이상에서만 오른쪽 칸을 편집기 옆에 둔다(D-283) — 경계 1279·1280 과 글이 아닌 값. 편집기의 최소 높이는 C-Type §15.4 의 420~480 안이다(변이 점검 R17 이 처음 한 바퀴에서 살아남아 더한 시험)."""
        self.assertEqual((rules.SIDE_BY_SIDE_FROM, rules.side_by_side(1279), rules.side_by_side(1280), rules.side_by_side(1279.9), rules.side_by_side(1280.0)), (1280, False, True, False, True))
        for width in (1093, 910, 900, 0, -5):                                     # 1366×768 의 125%·150% 와 최소 창
            self.assertFalse(rules.side_by_side(width), width)
        for width in (1366, 1536, 1600, 1920):
            self.assertTrue(rules.side_by_side(width), width)
        for wrong in (None, "1600", True, float("nan")):
            self.assertFalse(rules.side_by_side(wrong), repr(wrong))
        self.assertTrue(420 <= rules.EDITOR_MIN_HEIGHT <= 480)

    def test_the_option_fields_are_the_services_names_in_a_fixed_order_and_every_field_has_a_hint(self):
        labels = rules.option_labels()
        self.assertEqual(labels, do.LABELS)
        self.assertEqual([name for name, _single in rules.OPTION_FIELDS], ["message", "experience", "opinion", "conclusion", "audience", "must_include", "price_date", "urls"])
        for name, _single in rules.OPTION_FIELDS:
            self.assertIn(name, do.KEYS)
            self.assertTrue(T["drf_hint_" + name])
        self.assertEqual(rules.LIST_FIELDS, ("must_include", "price_date", "urls"))
        self.assertEqual(do.LABELS["experience"], "실제 사용 경험", "서비스의 확인 권장 문장이 이 이름으로 칸을 가리킨다")

    def test_the_fields_become_the_services_options_and_the_service_is_the_judge(self):
        chosen = rules.options_dict({"message": "  예시   전할 말  ", "experience": "", "must_include": "첫째 문장\n\n  둘째 문장  \n", "urls": "   ", "price_date": "예시 3,000원", "unknown": "무시", "audience": 3})
        self.assertEqual(chosen, {"message": "예시 전할 말", "must_include": "첫째 문장\n둘째 문장", "price_date": "예시 3,000원"})
        built = rules.build_options(chosen)
        self.assertEqual((built.message, built.must_include, built.price_date, built.experience), ("예시 전할 말", ("첫째 문장", "둘째 문장"), ("예시 3,000원",), ""))
        self.assertEqual(rules.options_dict(None), {})
        with self.assertRaises(AppError) as caught:
            rules.build_options({"experience": "예시 " + KEY_SHAPED})
        self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")
        self.assertNotIn(KEY_SHAPED, caught.exception.rendered().message)


# ---- 2) 컨트롤러 ------------------------------------------------------------------------------------------------------------------------------
class EmptyAndRefusedTest(unittest.TestCase):
    def test_without_a_candidate_there_is_one_line_and_one_button_and_nothing_to_do(self):
        controller = new_controller()
        view = controller.view()
        self.assertEqual((view["state"], view["normal"], view["empty"]["title"], view["empty"]["button"]), ("empty", None, "주제 후보에서 후보를 골라 '이 주제로 만들기' 를 눌러 주세요", "주제 후보로 가기"))
        self.assertEqual(controller.start_make(), ("unavailable", None))
        self.assertEqual(controller.copy_decision("body"), ("unavailable", None))
        self.assertEqual((controller.has_unsaved(), controller.inspect(), controller.leave_dialog(), controller.open_info()[0]), (False, None, None, ""))
        self.assertEqual(controller.provider.calls, [])

    def test_a_stopped_candidate_never_reaches_the_provider_and_no_body_text_is_in_the_view(self):
        controller = new_controller()
        self.assertEqual(controller.open_target(target_of(STOPPED, stop=True)), "refused")
        self.assertEqual(controller.start_make(), ("refused", None))
        view = controller.view()
        self.assertEqual((view["state"], view["normal"], controller.provider.calls), ("refused", None, []))
        self.assertEqual((view["refused"]["title"], view["refused"]["button"]), (T["drf_refused_title"], T["drf_to_topics"]))
        self.assertEqual((controller.title, controller.body, controller.result), ("", "", None))
        for item in rules.COPY_ITEMS:
            self.assertEqual(controller.copy_decision(item), ("unavailable", None))
        self.assertEqual(controller.open_info()[0], "")

    def test_a_target_that_hides_the_stop_flag_is_refused_by_the_provider_and_the_screen_drops_everything(self):
        controller = new_controller()
        controller.open_target(target_of(STOPPED, stop=False))
        self.assertEqual(drive(controller), "started")
        self.assertEqual((controller.state, controller.refusal, controller.result, controller.title, controller.body), ("refused", "stopped", None, "", ""))
        self.assertIsNone(controller.view()["normal"])
        self.assertEqual(len(controller.provider.calls), 1)

    def test_an_answer_that_arrives_for_a_stop_flagged_target_or_another_candidate_is_dropped(self):
        good = made(APPLIANCE).result
        controller = new_controller()
        controller.open_target(target_of(GENERIC))
        status, job = controller.start_make()
        job.join(30)
        controller.apply_made(good)                                           # 다른 후보의 초안
        self.assertEqual((controller.state, controller.result, controller.body), ("error", None, ""))
        controller.open_target(target_of(GENERIC))
        controller.start_make()[1].join(30)
        controller.target = target_of(GENERIC, stop=True)                      # 그 사이 중지로 바뀌었다고 해 보자
        controller.apply_made(made(GENERIC).result)
        self.assertEqual((controller.state, controller.result), ("error", None))
        controller.pending = None
        controller.apply_made(made(GENERIC).result)                            # 시작하지 않은 일의 답
        self.assertEqual(controller.state, "error")

    def test_a_candidate_of_another_channel_is_refused_before_the_provider_and_a_missing_one_has_its_own_screen(self):
        controller = new_controller()
        self.assertEqual(controller.open_target(target_of(OTHER_CHANNEL)), "refused")
        self.assertEqual((controller.start_make(), controller.refusal, controller.provider.calls), (("refused", None), "channel", []))
        self.assertEqual(controller.view()["refused"]["title"], T["drf_channel_title"])
        controller.open_target(drafts.DraftTarget("tc-naver_a-seed-ffffffffffffffff", "예시", "naver_a", "예시", False, True))
        drive(controller)
        self.assertEqual((controller.state, controller.view()["notfound"]["title"]), ("notfound", T["drf_notfound_title"]))


class DraftFlowTest(unittest.TestCase):
    def test_a_draft_shows_the_service_texts_unedited_and_the_actions_are_ready(self):
        controller = made(GENERIC)
        view, body = controller.view(), controller.result.body
        normal = view["normal"]
        self.assertEqual((view["state"], controller.has_unsaved(), controller.title, controller.body), ("normal", False, body.selected_title, body.body_text))
        self.assertEqual([item["text"] for item in normal["title_box"]["picks"]], list(body.titles))
        self.assertEqual(sum(1 for item in normal["title_box"]["picks"] if item["selected"]), 1)
        self.assertTrue(420 <= normal["editor"]["min_height"] <= 480)
        self.assertEqual((normal["editor"]["value"], normal["editor"]["edited"], normal["editor"]["edit_text"]), (body.body_text, False, T["drf_edit_none"]))
        self.assertEqual([(item["key"], item["enabled"]) for item in normal["actions"]["buttons"]], [("title", True), ("body", True), ("all", True), ("open", True)])
        self.assertEqual([item["kind"] for item in normal["actions"]["buttons"]], ["secondary", "secondary", "primary", "ghost"], "화면의 주요 단추는 하나")
        self.assertEqual(normal["side"]["image"]["state"], "before")
        self.assertEqual(normal["side"]["image"]["state_text"], "이미지 검색 전")
        self.assertEqual([item["text"] for item in (normal["side"]["keywords"]["copy"], normal["side"]["tags"]["copy"], normal["side"]["summary"]["copy"])], ["키워드 복사", "태그 복사", "요약 복사"])

    def test_the_image_slot_has_two_states_only(self):
        controller = made(GENERIC)
        self.assertEqual(controller.toggle_image(), "skip")
        self.assertEqual(controller.view()["normal"]["side"]["image"]["state_text"], "이미지 없이 진행")
        self.assertEqual(controller.toggle_image(), "before")
        self.assertEqual(dv.IMAGE_STATES, ("before", "skip"))

    def test_checks_are_split_into_the_open_specific_group_and_the_closed_common_group(self):
        view = made(APPLIANCE).view()["normal"]["side"]["checks"]
        self.assertEqual((view["specific"]["open"], view["common"]["open"]), (True, False))
        self.assertTrue([line for line in view["specific"]["lines"] if "협찬" in line])
        self.assertEqual(len(view["common"]["lines"]), 6)
        generic = made(GENERIC).view()["normal"]["side"]["checks"]
        self.assertEqual(generic["specific"]["lines"], [T["drf_chk_domain"]], "분야를 못 읽었다는 줄이 펼친 쪽에 있다")
        none = made(SOFTWARE).view()["normal"]["side"]["checks"]
        self.assertEqual((none["specific"]["lines"], none["specific"]["chip"], none["specific"]["tone"]), ([], "0건", "muted"))
        controller = made(APPLIANCE)
        controller.set_common_open(True)
        self.assertTrue(controller.view()["normal"]["side"]["checks"]["common"]["open"])

    def test_a_rejected_candidate_gets_a_draft_with_a_note_and_a_different_blog_gets_a_note(self):
        view = made(REJECTED).view()
        self.assertEqual(view["notice"]["level"], "info")
        self.assertIn("‘제외’ 상태", view["notice"]["text"])
        controller = made(GENERIC)
        controller.set_blog("naver_b")
        drive(controller)
        notice = controller.view()["notice"]
        self.assertIn("예시 블로그 나", notice["text"])
        self.assertIn("용으로 만들었어요", notice["text"])

    def test_a_new_draft_starts_fresh_and_the_same_input_gives_the_same_draft(self):
        first, second = made(GENERIC), made(GENERIC)
        self.assertEqual(first.result.body.to_dict(), second.result.body.to_dict())
        first.set_body(first.body + "\n\n더한 문단이에요.")
        first.copy_decision("body")
        self.assertTrue(first.copy_asked)
        self.assertEqual(first.regen_dialog()["title"], T["drf_regen_title"])
        drive(first, first.start_regenerate)
        self.assertEqual((first.body, first.has_unsaved(), first.ack, first.copied, first.copy_asked, first.inspection), (first.result.body.body_text, False, {}, set(), None, None))
        self.assertEqual(first.view()["notice"]["text"], T["drf_made_again"])

    def test_failures_keep_what_is_on_the_screen_and_never_show_a_python_text_or_a_code(self):
        controller = made(GENERIC)
        controller.set_body(controller.body + "\n\n내가 더한 문단이에요.")
        controller.provider.fail = drafts.DraftFailure("원문은 쓰이지 않는다 /tmp/x.db", code="STORE_X", kind="io")
        controller.regen_asked = True
        drive(controller, controller.start_regenerate)
        view = controller.view()
        self.assertEqual((view["state"], view["notice"]["level"], view["notice"]["text"]), ("normal", "error", T["drf_fail_io"]))
        self.assertIn("내가 더한 문단이에요.", controller.body, "실패해도 고친 내용은 그대로")
        self.assertTrue(controller.has_unsaved())
        self.assertNotIn("원문은 쓰이지 않는다", " ".join(all_strings(view)))
        first = new_controller(fail=drafts.DraftFailure("원문은 쓰이지 않는다", code="TOPIC_STORE_CORRUPT", kind="corrupt"))
        first.open_target(target_of(GENERIC))
        drive(first)
        view = first.view("code: TOPIC_STORE_CORRUPT")
        self.assertEqual((view["state"], view["error"]["user"], view["error"]["diag"]), ("error", T["drf_fail_corrupt"], "code: TOPIC_STORE_CORRUPT"))
        self.assertNotIn("TOPIC_STORE_CORRUPT", " ".join((view["error"]["title"], view["error"]["desc"], view["error"]["button"], view["error"]["user"])))

    def test_a_wrong_option_names_the_field_and_a_reason_and_never_the_typed_text(self):
        controller = made(GENERIC)
        controller.set_option("experience", "예시 " + KEY_SHAPED)
        self.assertTrue(controller.options_pending())
        controller.regen_asked = True
        drive(controller, controller.start_regenerate)
        notice = controller.view()["notice"]
        self.assertEqual(notice["level"], "error")
        self.assertIn("‘실제 사용 경험’", notice["text"])
        shown = controller.view()
        shown["normal"]["options"]["fields"] = []                              # 적은 칸의 글은 입력 칸이 보여 주는 사용자의 글이다 — 그 밖에는 어디에도 나오지 않는다
        self.assertNotIn(KEY_SHAPED, " ".join(all_strings(shown)) + notice["text"])
        self.assertEqual(controller.state, "normal")
        self.assertTrue(controller.has_unsaved(), "적은 칸은 그대로 남는다")

    def test_the_options_apply_to_the_new_draft_and_stop_being_pending(self):
        controller = made(GENERIC)
        self.assertFalse(controller.options_pending())
        for name, value in (("message", "예시 전하고 싶은 말 한 줄"), ("audience", "예시 독자 한 명"), ("must_include", "예시 반드시 넣을 문장입니다.\n둘째 문장이에요.")):
            self.assertTrue(controller.set_option(name, value))
        self.assertFalse(controller.set_option("unknown", "x"))
        self.assertTrue(controller.options_pending())
        self.assertTrue(controller.has_unsaved())
        controller.set_post_type("비교형")
        dialog = controller.regen_dialog()
        self.assertIsNotNone(dialog)
        drive(controller, controller.start_regenerate)
        self.assertIn("예시 반드시 넣을 문장입니다.", controller.body)
        self.assertEqual((controller.options_pending(), controller.has_unsaved(), controller.result.post_type), (False, False, "비교형"))
        self.assertEqual(controller.result.options["audience"], "예시 독자 한 명")

    def test_the_blog_and_the_post_type_choices_are_validated(self):
        controller = made(GENERIC)
        self.assertEqual((controller.set_blog("naver_b"), controller.set_blog("github_pages"), controller.set_blog(None), controller.blog), (True, False, False, "naver_b"))
        self.assertEqual((controller.set_post_type("없는 유형"), controller.set_post_type("문제 해결형"), controller.set_post_type(None), controller.post_type), (False, True, True, None))
        options = controller.view()["normal"]["options"]
        self.assertEqual([item["label"] for item in options["types"]], ["후보 기준", *dv.POST_TYPES])
        self.assertEqual([item["label"] for item in options["blogs"]], ["예시 블로그 가", "예시 블로그 나"])
        self.assertEqual([item["name"] for item in options["fields"]], ["message", "experience", "opinion", "conclusion", "audience", "must_include", "price_date", "urls"])
        self.assertEqual([item["label"] for item in options["fields"]][1], "실제 사용 경험")
        self.assertEqual(options["apply"]["text"], "다시 만들기")
        self.assertFalse(options["open"])
        controller.toggle_options()
        self.assertTrue(controller.view()["normal"]["options"]["open"])

    def test_the_unexpected_exception_state_drops_everything_but_keeps_the_target(self):
        controller = made(GENERIC)
        controller.set_body("고친 글")
        controller.apply_unexpected(RuntimeError("터짐 /tmp/x"))
        view = controller.view()
        self.assertEqual((view["state"], controller.result, controller.body, controller.target.candidate_id), ("error", None, "", GENERIC.candidate_id))
        self.assertNotIn("터짐", " ".join(all_strings(view)))
        self.assertEqual(view["error"]["user"], T["job_failed"])


class LossGuardsTest(unittest.TestCase):
    def test_leaving_cancels_a_running_job_so_the_provider_sees_the_cancel_and_the_late_answer_is_dropped(self):
        """화면을 떠나면 돌던 만들기를 **취소**한다(공급자의 `cancelled()` 가 참이 된다) — 변이 점검 V02 가 처음 한 바퀴에서 살아남아 더한 시험. 떠난 뒤 늦게 온 답은 어디에도 보이지 않는다."""
        import threading
        import time
        entered, seen = threading.Event(), threading.Event()

        class Waiting(drafts.DraftsProvider):
            def make_draft(self, request, progress, cancelled):
                entered.set()
                for _ in range(600):
                    if cancelled():
                        seen.set()
                        raise jobs.JobCancelled()
                    time.sleep(0.01)
                raise AssertionError("취소가 오지 않았다")

        controller = dv.DraftsController(Waiting(), jobs.JobRunner())
        controller.open_target(target_of(GENERIC))
        status, job = controller.start_make()
        self.assertEqual(status, "started")
        self.assertTrue(entered.wait(5), "공급자가 일을 시작했다")
        controller.leave()
        self.assertTrue(seen.wait(5), "떠나면 돌던 만들기가 취소된다")
        job.join(5)
        self.assertEqual((controller.state, controller.target, controller.result), ("empty", None, None))
        self.assertFalse(controller.apply_made(types.SimpleNamespace(candidate_id=GENERIC.candidate_id, body=body_of("예시 청소기 고르는 기준", "예시 청소기"))), "떠난 뒤의 답은 버린다")
        self.assertEqual((controller.state, controller.result), ("empty", None))

    def test_editing_the_title_the_body_or_an_unapplied_option_makes_the_draft_unsaved(self):
        controller = made(GENERIC)
        self.assertFalse(controller.has_unsaved())
        controller.set_body(controller.body + " ")
        self.assertTrue(controller.has_unsaved())
        controller.set_body(controller.draft_body().body_text)
        self.assertFalse(controller.has_unsaved(), "원래대로 돌리면 고친 것이 아니다")
        controller.set_title(controller.title + "!")
        self.assertTrue(controller.has_unsaved() and controller.title_edited())
        controller.set_title(controller.generated_titles()[2])
        self.assertFalse(controller.has_unsaved(), "다른 제목 후보를 고른 것은 고친 것이 아니다")
        controller.set_option("opinion", "예시 의견")
        self.assertTrue(controller.has_unsaved() and controller.options_pending())
        controller.set_option("opinion", "")
        self.assertFalse(controller.has_unsaved())

    def test_picking_another_title_asks_first_when_the_title_was_edited(self):
        controller = made(GENERIC)
        titles = controller.generated_titles()
        self.assertEqual((controller.pick_title(0), controller.title), ("ok", titles[0]))
        self.assertEqual(controller.pick_title(7), "unavailable")
        self.assertEqual(controller.pick_title(True), "unavailable")
        controller.set_title("내가 고친 제목")
        self.assertEqual(controller.pick_title(1), "confirm")
        self.assertEqual((controller.title, controller.pick_dialog()["cancel"], controller.pick_dialog()["ok"]), ("내가 고친 제목", "취소", "제목 바꾸기"))
        controller.discard_pick()
        self.assertIsNone(controller.pick_dialog())
        self.assertFalse(controller.confirm_pick())
        self.assertEqual(controller.title, "내가 고친 제목")
        controller.pick_title(1)
        self.assertTrue(controller.confirm_pick())
        self.assertEqual(controller.title, titles[1])

    def test_regenerating_asks_first_when_something_would_be_lost_and_not_otherwise(self):
        controller = made(GENERIC)
        self.assertIsNone(controller.regen_dialog())
        controller.set_body(controller.body + "\n\n더한 문단")
        self.assertEqual(controller.start_regenerate(), ("unconfirmed", None), "확인창을 보이지 않으면 아무것도 하지 않는다")
        self.assertEqual(len(controller.provider.calls), 1)
        dialog = controller.regen_dialog()
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), ("고친 내용이 사라져요 — 다시 만들까요?", "다시 만들기", "취소"))
        controller.discard_regen()
        self.assertEqual(controller.start_regenerate(), ("unconfirmed", None))
        controller.regen_dialog()
        self.assertEqual(drive(controller, controller.start_regenerate), "started")
        self.assertEqual(len(controller.provider.calls), 2)
        self.assertEqual(new_controller().start_regenerate(), ("unavailable", None))

    def test_leaving_and_closing_ask_only_when_something_would_be_lost_and_leaving_clears_the_draft(self):
        controller = made(GENERIC)
        self.assertIsNone(controller.leave_dialog())
        controller.set_body("고친 글")
        leave, close = controller.leave_dialog("leave"), controller.leave_dialog("close")
        self.assertEqual((leave["title"], close["title"]), ("고친 내용이 사라져요", "고친 내용이 사라져요"))
        self.assertEqual((leave["ok"], close["ok"], leave["cancel"], close["cancel"]), ("그래도 이동", "그래도 닫기", "취소", "취소"))
        self.assertNotEqual(leave["body"], close["body"])
        controller.discard_leave()
        self.assertIsNone(controller.leave_asked)
        controller.leave()
        self.assertEqual((controller.state, controller.result, controller.target, controller.body, controller.has_unsaved()), ("empty", None, None, "", False))

    def test_every_kind_of_unsaved_edit_gets_the_leave_close_and_regenerate_dialogs(self):
        """독립 검증 V4(변이 N10·N11): 제목만·선택 입력만 고쳐도 떠나기·닫기·다시 만들기 앞에 확인창이 뜬다 — 본문을 고쳤을 때만 뜨면 `AppState.nav` 는 옮기지 않는데 안내창은 없는 조용한 막힘이 된다."""
        edits = {"title": lambda c: c.set_title(c.title + "!"), "body": lambda c: c.set_body(c.body + " 더함"), "option": lambda c: c.set_option("opinion", "예시 의견")}
        for name, edit in edits.items():
            with self.subTest(edit=name):
                state = app_state.AppState()
                state.nav("drafts")
                state.drafts.open_target(target_of(ROWS[0]))
                drive(state.drafts)
                controller = state.drafts
                self.assertEqual((controller.leave_dialog(), controller.regen_dialog(), state.leave_guard("topics")), (None, None, None), "(전제) 고치기 전에는 묻지 않는다")
                edit(controller)
                self.assertTrue(controller.has_unsaved())
                for kind in ("leave", "close"):
                    self.assertIsNotNone(controller.leave_dialog(kind), (name, kind))
                self.assertIsNotNone(controller.regen_dialog(), name)
                self.assertIsNotNone(state.leave_guard("topics"), name)
                self.assertIsNotNone(state.close_guard(), name)
                self.assertFalse(state.nav("topics"), "안내창이 뜨는 만큼 옮기지 않는다")

    def test_the_editor_is_locked_while_a_new_draft_is_being_made_so_typed_text_is_never_overwritten(self):
        """독립 검증 V5: 다시 만들기가 도는 동안 친 글이 새 초안에 덮여 확인 없이 사라지던 틈 — 도는 동안에는 제목·본문을 고칠 수 없다(편집기 읽기 전용). 처음 만들 때는 편집기가 없다."""
        import threading
        gate, entered, got = threading.Event(), threading.Event(), {}

        class Slow(drafts.FakeDraftsProvider):
            def make_draft(self, request, progress, cancelled):
                if self.calls:                                                         # 처음 한 번은 바로, 다시 만들기는 문이 열릴 때까지(시간에 기대지 않는다)
                    entered.set()
                    gate.wait(10)
                return super().make_draft(request, progress, cancelled)

        controller = dv.DraftsController(Slow(lambda: CATALOG), jobs.JobRunner())
        controller.open_target(target_of(GENERIC))
        self.assertFalse(controller.locked)
        drive(controller)
        self.assertEqual((controller.locked, controller.view()["normal"]["editor"]["editable"], controller.view()["normal"]["title_box"]["editable"]), (False, True, True))
        controller.set_body(controller.body + "\n\n더한 문단")
        self.assertIsNotNone(controller.regen_dialog())
        status, job = controller.start_regenerate(on_done=lambda result, _payload: got.setdefault("ok", result))
        self.assertEqual(status, "started")
        self.assertTrue(entered.wait(5))
        self.assertTrue(controller.locked and controller.busy)
        mine, title = controller.body, controller.title
        self.assertEqual((controller.set_body("도는 동안 새로 친 글"), controller.set_title("도는 동안 새 제목"), controller.pick_title(1)), (False, False, "unavailable"))
        controller.pick_asked = 1
        self.assertFalse(controller.confirm_pick(), "확인창 뒤에도 도는 동안에는 제목을 바꾸지 않는다")
        self.assertEqual((controller.body, controller.title), (mine, title), "도는 동안은 아무것도 고쳐지지 않는다")
        view = controller.view()["normal"]
        self.assertEqual((view["editor"]["editable"], view["title_box"]["editable"], view["editor"]["locked_text"], view["title_box"]["locked_text"]), (False, False, T["drf_edit_locked"], T["drf_edit_locked"]))
        gate.set()
        job.join(10)
        self.assertTrue(controller.apply_made(got["ok"]))
        self.assertEqual((controller.locked, controller.view()["normal"]["editor"]["editable"]), (False, True))
        self.assertTrue(controller.set_body("새 초안이 온 뒤에는 다시 고칠 수 있다") and controller.set_title("새 제목"))
        self.assertEqual((controller.body, controller.title), ("새 초안이 온 뒤에는 다시 고칠 수 있다", "새 제목"))

    def test_the_app_state_refuses_to_leave_an_unsaved_draft_without_force_and_clears_it_when_leaving(self):
        state = app_state.AppState()
        state.nav("drafts")
        state.drafts.open_target(target_of(ROWS[0]))
        self.assertEqual(state.page, "drafts")
        drive(state.drafts)
        self.assertIsNone(state.leave_guard("topics"))
        self.assertIsNone(state.close_guard())
        state.drafts.set_body(state.drafts.body + "\n\n더함")
        self.assertEqual(state.leave_guard("topics")["ok"], "그래도 이동")
        self.assertEqual(state.close_guard()["ok"], "그래도 닫기")
        self.assertIsNone(state.leave_guard("drafts"))
        self.assertIsNone(state.leave_guard("없는 메뉴"))
        self.assertFalse(state.nav("topics"), "고친 내용이 있으면 확인 없이는 옮기지 않는다")
        self.assertEqual((state.page, state.drafts.has_unsaved()), ("drafts", True))
        self.assertTrue(state.nav("topics", force=True))
        self.assertEqual((state.page, state.drafts.state, state.drafts.result), ("topics", "empty", None))
        state.nav("drafts")
        state.drafts.open_target(target_of(ROWS[0]))
        drive(state.drafts)
        self.assertTrue(state.nav("home"), "고친 곳이 없으면 바로 옮긴다")
        self.assertEqual(state.drafts.state, "empty")

    def test_the_menu_has_the_draft_screen_after_the_topics_and_the_next_steps_keep_only_the_history(self):
        self.assertEqual([item[0] for item in app_state.NAV], ["home", "topics", "drafts", "seed", "blogs", "settings"])
        self.assertEqual(dict((item[0], item[1]) for item in app_state.NAV)["drafts"], "nav_draft")
        self.assertEqual(T["nav_draft"], "초안 작성")
        self.assertEqual(app_state.NAV_GROUPS[0], ("core", "nav_group_core", ("home", "topics", "drafts")))
        self.assertEqual([item[0] for item in app_state.NEXT_STEPS], ["history"])
        self.assertEqual([key for _group, _label, items in app_state.nav_groups() for key, _name, _icon in items], ["home", "topics", "drafts", "seed", "blogs", "settings"])


class CopyGateTest(unittest.TestCase):
    def test_the_first_copy_of_a_draft_with_specific_lines_asks_and_only_the_confirmation_gives_the_text(self):
        controller = made(APPLIANCE)
        kind, dialog = controller.copy_decision("body")
        self.assertEqual(kind, "confirm")
        self.assertEqual((dialog["ok"], dialog["cancel"]), ("그래도 복사", "취소"))
        self.assertTrue(dialog["title"].startswith("확인 권장 ") and dialog["title"].endswith("건을 읽었나요?"))
        self.assertIn("협찬", dialog["body"])
        self.assertEqual(controller.copy_asked, "body")
        self.assertIsNone(controller.confirm_copy("title"), "다른 단추의 확인으로는 글을 주지 않는다")
        controller.discard_copy()
        self.assertIsNone(controller.confirm_copy("body"), "취소하면 글을 주지 않는다")
        self.assertEqual(controller.copy_decision("body")[0], "confirm")
        self.assertEqual(controller.confirm_copy("body"), controller.result.body.body_text)
        self.assertEqual(controller.copy_decision("body"), ("copy", controller.result.body.body_text), "이미 확인한 것은 다시 묻지 않는다")
        self.assertEqual(controller.copy_decision("all")[0], "copy")

    def test_without_any_specific_line_or_unreadable_domain_the_title_and_the_edited_body_copy_directly(self):
        controller = made(SOFTWARE)
        self.assertEqual(controller.copy_decision("title"), ("copy", controller.title))
        kind, dialog = controller.copy_decision("body")
        self.assertEqual((kind, dialog["title"], dialog["ok"]), ("confirm", T["drf_soft_title"], "그래도 복사"), "거의 고치지 않은 초안은 부드러운 안내 하나(막지 않는다)")
        self.assertNotIn("확인 권장", dialog["title"])
        controller.discard_copy()
        controller.set_body(controller.body + "\n\n" + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8)
        self.assertEqual(controller.copy_decision("body"), ("copy", controller.body), "충분히 고친 글은 바로 복사한다")

    def test_an_unreadable_domain_and_a_sensitive_topic_ask_too(self):
        generic = made(GENERIC)
        kind, dialog = generic.copy_decision("title")
        self.assertEqual(kind, "confirm")
        self.assertIn(T["drf_chk_domain"], dialog["body"])
        health = made(HEALTH)
        kind, dialog = health.copy_decision("title")
        self.assertEqual(kind, "confirm")
        self.assertIn("건강처럼", dialog["body"])

    def test_the_small_copies_never_ask_but_are_blocked_by_a_key_shape(self):
        controller = made(GENERIC)
        body = controller.result.body
        self.assertEqual(controller.copy_decision("keywords"), ("copy", ", ".join((*body.core_keywords, *body.sub_keywords))))
        self.assertEqual(controller.copy_decision("tags"), ("copy", body.tags_text))
        self.assertEqual(controller.copy_decision("summary"), ("copy", body.summary))
        controller.set_body(controller.body + " " + KEY_SHAPED)
        for item in rules.COPY_ITEMS:
            with self.subTest(item=item):
                kind, dialog = controller.copy_decision(item)
                self.assertEqual((kind, dialog["title"], dialog["cancel"]), ("blocked", "복사할 수 없어요", None))
                self.assertNotIn(KEY_SHAPED, dialog["body"])
                self.assertIsNone(controller.final_text(item))
                self.assertIsNone(controller.confirm_copy(item))

    def test_a_key_shape_typed_into_the_title_blocks_the_body_copy_too_and_a_key_that_appears_after_the_dialog_blocks_the_copy(self):
        controller = made(APPLIANCE)
        controller.set_title("제목 " + KEY_SHAPED)
        self.assertEqual(controller.copy_decision("body")[0], "blocked")
        controller.set_title(controller.generated_titles()[0])
        self.assertEqual(controller.copy_decision("body")[0], "confirm")
        controller.set_body(controller.body + " " + KEY_SHAPED)                 # 확인창이 떠 있는 동안 글에 키 모양이 생겼다
        self.assertIsNone(controller.confirm_copy("body"))
        self.assertIsNone(controller.copy_asked)

    def test_a_draft_with_normal_reference_addresses_can_be_copied_and_nothing_is_blocked(self):
        """독립 검증 V2: `참고 URL` 칸에 정상 주소(글번호·상품번호·해시·긴 글 주소)를 넣어 만든 초안이 키 모양으로 오탐되어 여섯 복사 단추가 모두 잠기던 문제."""
        addresses = [address for address in NORMAL_ADDRESSES if address.startswith("https://") and "d41d8" not in address]        # 경로에 해시가 든 주소는 서비스의 생성기가 본문에 쓰지 못한다 — 편집기에 직접 친 글은 `AddressShapeTest` 가 본다
        controller = made(SOFTWARE)
        controller.set_option("urls", "\n".join(addresses))
        self.assertIsNotNone(controller.regen_dialog())
        drive(controller, controller.start_regenerate)
        self.assertEqual(controller.state, "normal")
        self.assertTrue(all(address in controller.body for address in addresses), "주소가 본문에 들어갔다")
        controller.set_body(controller.body + "\n\n" + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8)
        for item in rules.COPY_ITEMS:
            with self.subTest(item=item):
                kind, payload = controller.copy_decision(item)
                self.assertNotEqual(kind, "blocked", item)
                self.assertEqual(controller.blocks_for(item), ())
                text = payload if kind == "copy" else controller.confirm_copy(item)
                self.assertEqual(text, controller.text_for(item), "복사할 글이 그대로 나온다")

    def test_a_key_inside_an_address_typed_in_the_editor_blocks_and_the_dialog_points_to_the_place(self):
        controller = made(SOFTWARE)
        controller.set_body(controller.body + "\n\n참고: https://example.com/page?x=" + KEY_SHAPED + " 입니다.")
        for item in ("body", "all", "keywords", "tags", "summary"):
            self.assertEqual(controller.copy_decision(item)[0], "blocked", item)
        kind, dialog = controller.copy_decision("body")
        self.assertIn(T["drf_secret_body"], dialog["body"])
        self.assertIn(T["drf_where_head"], dialog["body"])
        lines = [line for line in dialog["body"].splitlines() if line.startswith("· ")]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("· 본문 — "))
        self.assertIn("com/page?x=", lines[0], "걸린 곳 앞의 글이 보여 어디인지 알 수 있다")
        self.assertIn("[가림", lines[0], "주소 안의 정본 키 모양은 걸린 자리에서 가려서 보인다(키를 되풀이하지 않는다)")
        self.assertNotIn(KEY_SHAPED, dialog["body"])
        controller.inspect()
        card = controller.view()["normal"]["side"]["inspect"]
        self.assertEqual((card["tone"], card["status"]), ("error", T["drf_inspect_secret"]))
        self.assertTrue(card["lines"] and card["lines"][0].startswith("· 본문 — "), "검사 카드도 걸린 자리를 앞부분만 짚는다")
        self.assertNotIn(KEY_SHAPED, " ".join(card["lines"]))
        controller.set_body(controller.draft_body().body_text + "\n\n참고: https://example.com/page?x=1234 입니다.")
        self.assertNotEqual(controller.copy_decision("body")[0], "blocked", "키가 없는 주소로 고치면 복사할 수 있다")
        controller.set_title("제목 " + KEY_SHAPED)
        kind, dialog = controller.copy_decision("title")
        self.assertEqual(kind, "blocked")
        self.assertTrue([line for line in dialog["body"].splitlines() if line.startswith("· 제목 — ")], "제목에서 걸렸으면 제목을 짚는다")

    def test_the_copied_text_is_exactly_what_the_editor_holds(self):
        controller = made(SOFTWARE)
        original = controller.result.body
        self.assertEqual(controller.text_for("all"), original.plain_text, "고치지 않았으면 서비스의 복사용 글과 같다")
        self.assertEqual(controller.text_for("title"), original.title_text)
        self.assertEqual(controller.text_for("body"), original.body_text)
        mine = "내가 고친 본문\n\n둘째 문단  끝에 공백  \n"
        controller.set_body(mine)
        controller.set_title("내가 고친 제목")
        self.assertEqual((controller.text_for("body"), controller.text_for("title"), controller.text_for("all")), (mine, "내가 고친 제목", "내가 고친 제목\n\n" + mine))
        self.assertIsNone(controller.text_for("nothing"))
        controller.set_body("   \n ")
        self.assertIsNone(controller.final_text("body"), "빈 글은 복사하지 않는다")

    def test_the_gate_asks_again_only_for_a_new_claim_after_an_edit_and_lists_the_sentence(self):
        controller = made(SOFTWARE)
        controller.set_body(controller.body + "\n\n" + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8)
        self.assertEqual(controller.copy_decision("body")[0], "copy")
        controller.set_body(controller.body + "\n\n직접 써 보니 정말 좋았습니다.")
        kind, dialog = controller.copy_decision("body")
        self.assertEqual(kind, "confirm")
        self.assertIn("직접 써 보니 정말 좋았습니다.", dialog["body"])
        self.assertIn("고친 글에서 확인이 필요한 곳", dialog["body"])
        self.assertEqual(controller.confirm_copy("body"), controller.body)
        self.assertEqual(controller.copy_decision("body")[0], "copy", "같은 문장은 다시 묻지 않는다")
        controller.set_body(controller.body + "\n\n가격은 12,000원이었어요.")
        self.assertEqual(controller.copy_decision("body")[0], "confirm", "새 문장은 다시 묻는다")

    def test_an_invented_experience_typed_into_the_title_is_found_and_asked_about(self):
        """독립 검증 V4(변이 N05): 제목 칸에 적은 지어낸 경험도 본문과 같이 점검에 걸린다."""
        controller = made(SOFTWARE)
        controller.set_body(controller.body + "\n\n" + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8)
        controller.set_title("직접 써 보니 정말 좋았습니다.")
        inspection = controller.inspect()
        self.assertTrue([note for note in inspection.violations if "직접 써 보니" in note.preview], "제목 칸의 지어낸 경험이 걸린다")
        self.assertTrue([line for line in controller.view()["normal"]["side"]["inspect"]["lines"] if "직접 써 보니" in line])
        kind, dialog = controller.copy_decision("title")
        self.assertEqual(kind, "confirm")
        self.assertIn("직접 써 보니 정말 좋았습니다.", dialog["body"])
        self.assertEqual(rules.inspect_text("직접 써 보니 정말 좋았습니다.", "정상 문단이에요.").violations[0].pair[0], claim_check.EXPERIENCE_USE)
        self.assertEqual(rules.inspect_text("정상 제목이에요", "정상 문단이에요.").claims, ())

    def test_a_draft_with_only_a_price_or_a_date_sentence_asks_and_lists_that_sentence_in_the_dialog(self):
        """독립 검증 V4(변이 N07): 가격·날짜·통계는 지어낸 경험(위반)이 아니라 '확인하지 않은 것' 이지만 확인창에는 그 문장이 보인다 — 순수 시험도 이것을 못박는다(Qt 시험은 CI 에서 건너뛴다)."""
        for sentence, label in (("가격은 12,000원이었어요.", "확인하지 않은 가격"), ("2026년 11월 5일에 확인했어요.", "확인하지 않은 날짜")):
            with self.subTest(sentence=sentence):
                controller = made(SOFTWARE)
                controller.set_body(controller.body + "\n\n" + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8 + "\n\n" + sentence)
                self.assertEqual(controller.checks()[0], (), "(전제) 이 글에만 해당하는 확인 권장은 없다 — 확인창의 이유는 가격·날짜 문장뿐이다")
                kind, dialog = controller.copy_decision("body")
                self.assertEqual(kind, "confirm", "가격·날짜만 있어도 확인창이 먼저다")
                self.assertIn(label, dialog["body"])
                self.assertIn(sentence, dialog["body"])
                self.assertFalse(controller.inspect().violations, "위반이 아니라 확인할 것이다")
                self.assertEqual(controller.confirm_copy("body"), controller.body)
                self.assertEqual(controller.copy_decision("body")[0], "copy", "확인한 문장은 다시 묻지 않는다")

    def test_the_decision_never_touches_the_copied_marks_or_the_clipboard(self):
        controller = made(SOFTWARE)
        before = (set(controller.copied), controller.title, controller.body, controller.state)
        for item in rules.COPY_ITEMS:
            controller.copy_decision(item)
        self.assertEqual((set(controller.copied), controller.title, controller.body, controller.state), before)
        self.assertTrue(controller.mark_copied("body"))
        self.assertFalse(controller.mark_copied("nothing"))
        self.assertEqual(controller.view()["normal"]["actions"]["buttons"][1]["text"], "✓ 본문 복사됨")
        self.assertTrue(controller.view()["normal"]["actions"]["buttons"][1]["copied"])
        controller.clear_copied("body")
        self.assertEqual(controller.view()["normal"]["actions"]["buttons"][1]["text"], "본문 복사")
        controller.mark_copied("keywords")
        self.assertEqual(controller.view()["normal"]["side"]["keywords"]["copy"]["text"], "✓ 키워드 복사됨")
        self.assertEqual([controller.copied_text(item) for item in ("title", "all", "tags", "summary")], ["✓ 제목 복사됨", "✓ 전체 복사됨", "✓ 태그 복사됨", "✓ 요약 복사됨"])


class InspectionCardTest(unittest.TestCase):
    def test_the_check_card_goes_from_before_to_ok_to_stale_to_claims_to_secret(self):
        controller = made(SOFTWARE)
        card = lambda: controller.view()["normal"]["side"]["inspect"]  # noqa: E731
        self.assertEqual((card()["status"], card()["tone"]), (T["drf_inspect_before"], "muted"))
        controller.inspect()
        self.assertEqual((card()["tone"], card()["status"]), ("info", T["drf_inspect_unchanged"].format(n=0)), "고치지 않은 초안")
        controller.set_body(controller.body + "\n\n" + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8)
        self.assertEqual(card()["status"], T["drf_inspect_stale"])
        controller.inspect()
        self.assertEqual((card()["tone"], card()["status"]), ("ok", T["drf_inspect_ok"]))
        controller.set_body(controller.body + "\n\n직접 써 보니 정말 좋았습니다.")
        controller.inspect()
        self.assertEqual(card()["tone"], "warning")
        self.assertTrue([line for line in card()["lines"] if "직접 써 보니" in line])
        controller.set_body(controller.body + " " + KEY_SHAPED)
        controller.inspect()
        self.assertEqual((card()["tone"], card()["status"]), ("error", T["drf_inspect_secret"]))
        self.assertNotIn(KEY_SHAPED, " ".join(all_strings(card())))

    def test_inspecting_changes_nothing_and_the_status_line_follows_the_edits(self):
        controller = made(SOFTWARE)
        before = (controller.title, controller.body, set(controller.copied))
        controller.inspect()
        self.assertEqual((controller.title, controller.body, set(controller.copied)), before)
        self.assertEqual(controller.editor_status()["edit_text"], T["drf_edit_none"])
        controller.set_body(controller.body + "\n\n더한 문단이에요.")
        status = controller.editor_status()
        self.assertEqual((status["edited"], status["edit_text"]), (True, T["drf_edit_some"].format(n=len("더한 문단이에요."))))
        self.assertIn("공백 제외", status["count_text"])


class OpenAddressTest(unittest.TestCase):
    def test_the_button_is_on_only_for_a_plain_naver_blog_address_and_the_address_is_the_write_page_only(self):
        controller = made(GENERIC)
        url, why = controller.open_info()
        self.assertEqual((url, why), ("https://blog.naver.com/example-blog-a?Redirect=Write", ""))
        self.assertEqual(controller.view()["normal"]["actions"]["buttons"][3]["url"], url)
        for blog_url in ("", "http://blog.naver.com/a", "https://evil.example/a"):
            with self.subTest(blog_url=blog_url):
                controller.result = drafts.DraftResult(controller.result.candidate_id, controller.result.body, "naver_a", "정보형", {}, controller.result.blog_names, blog_url, False, False, False, True)
                button = controller.view()["normal"]["actions"]["buttons"][3]
                why = T["drf_open_why_unusable" if blog_url else "drf_open_why_profile"]          # D-362: 비어 있으면 '적으면 열 수 있어요', 적어 둔 주소가 네이버 블로그 주소가 아니면 '그 주소는 열지 않아요'
                self.assertEqual((controller.open_info()[0], button["enabled"], button["tip"]), ("", False, why))
        controller.state = "loading"
        self.assertEqual(controller.open_info(), ("", T["drf_open_why_wait"]))


class CandidateDetailActionTest(unittest.TestCase):
    def loaded(self):
        controller = cv.CandidatesController(ucd.FakeCandidatesProvider("normal"), jobs.JobRunner())
        controller.apply_loaded(controller.provider.load_candidates(lambda *a: None, lambda: False))
        return controller

    def detail_of(self, controller, topic_part):
        row = next(item for item in controller.rows() if topic_part in item.candidate.topic)
        controller.select(row.candidate.candidate_id)
        return controller.detail_view()

    def test_the_make_button_is_on_for_a_normal_naver_candidate_and_off_with_a_reason_otherwise(self):
        controller = self.loaded()
        on = self.detail_of(controller, "순서대로 따라 하는")["draft"]
        self.assertEqual((on["text"], on["enabled"], on["reason"]), ("이 주제로 만들기", True, ""))
        stop = self.detail_of(controller, "먹으면 바로 낫는")["draft"]
        self.assertEqual((stop["enabled"], stop["reason"], stop["tip"]), (False, T["drf_make_why_stop"], T["drf_make_why_stop"]))
        other = self.detail_of(controller, "다른 채널의 예")["draft"]
        self.assertEqual((other["enabled"], other["reason"]), (False, T["drf_make_why_channel"]))
        other = self.detail_of(controller, "또 다른 채널")["draft"]
        self.assertEqual(other["enabled"], False)

    def test_the_make_button_is_off_while_candidates_are_being_made_and_comes_back_after(self):
        """독립 검증 V4(변이 N22): 후보를 만드는 중에는 `이 주제로 만들기` 가 꺼지고 까닭이 글로 보인다 — 문구가 쓰이는지가 아니라 동작을 본다."""
        import threading
        controller = self.loaded()
        row = next(item for item in controller.rows() if "순서대로 따라 하는" in item.candidate.topic)
        before = controller.draft_vm(row)
        self.assertEqual((before["enabled"], before["reason"]), (True, ""))
        release = threading.Event()
        job = controller.runner.start(cv.WRITE_KEY, lambda progress, cancelled: release.wait(10))
        try:
            self.assertTrue(controller.busy)
            busy = controller.draft_vm(row)
            self.assertEqual((busy["enabled"], busy["reason"], busy["tip"]), (False, T["drf_make_why_wait"], T["drf_make_why_wait"]))
            controller.select(row.candidate.candidate_id)
            self.assertEqual(controller.detail_view()["draft"]["enabled"], False, "상세 창의 단추도 같다")
        finally:
            release.set()
            job.join(10)
        self.assertFalse(controller.busy)
        self.assertEqual(controller.draft_vm(row)["enabled"], True)

    def test_the_target_carries_only_the_whole_number_and_the_shown_values_and_the_stop_flag(self):
        controller = self.loaded()
        self.assertIsNone(controller.draft_target(), "고른 후보가 없으면 None")
        self.detail_of(controller, "먹으면 바로 낫는")
        target = controller.draft_target()
        self.assertEqual((target.stop, target.sample, target.channel), (True, True, "naver_b"))
        self.assertEqual(target.candidate_id, next(item for item in controller.rows() if item.stop).candidate.candidate_id)
        self.assertEqual(set(target.__dataclass_fields__), {"candidate_id", "title", "channel", "channel_name", "stop", "sample"})
        controller.state = "loading"
        self.assertIsNone(controller.draft_target())

    def test_the_sample_app_state_makes_a_draft_from_the_sample_candidate_it_shows(self):
        state = app_state.AppState()
        controller = state.candidates
        controller.apply_loaded(controller.provider.load_candidates(lambda *a: None, lambda: False))
        row = next(item for item in controller.rows() if "순서대로 따라 하는" in item.candidate.topic)
        controller.select(row.candidate.candidate_id)
        state.drafts.open_target(controller.draft_target())
        self.assertEqual(drive(state.drafts), "started")
        self.assertEqual((state.drafts.state, state.drafts.result.candidate_id), ("normal", row.candidate.candidate_id))
        self.assertTrue(state.drafts.result.sample)
        self.assertEqual(state.drafts_view()["sample"], True)
        stop = next(item for item in controller.rows() if item.stop)
        controller.select(stop.candidate.candidate_id)
        state.drafts.leave()
        state.drafts.open_target(controller.draft_target())
        self.assertEqual((state.drafts.state, state.drafts.start_make()), ("refused", ("refused", None)))


# ---- 3) 글 ------------------------------------------------------------------------------------------------------------------------------------
class TextTest(unittest.TestCase):
    def test_every_draft_text_is_easy_and_free_of_promises_search_counts_codes_and_commands(self):
        for key, value in draft_text.DRAFT_T.items():
            with self.subTest(key=key):
                self.assertTrue(value.strip(), key)
                self.assertTrue(key.startswith("drf_"), "열쇠는 모두 `drf_` 로 시작해 다른 화면의 문구와 겹치지 않는다")
                self.assertNotRegex(value, r"\bNone\b|\bTrue\b|\bFalse\b|\['|Traceback|Exception|Error")
                for word in FORBIDDEN_WORDS + text.FORBIDDEN:
                    self.assertNotIn(word, value)
                self.assertNotRegex(value, r"https?://|\w:[\\/]|\\|`|--[a-z]")
                self.assertEqual(T[key], value, "T 에 합쳐져 있다")

    def test_the_view_models_of_every_state_have_no_python_text_no_enum_name_and_no_forbidden_word(self):
        views = []
        views.append(new_controller().view())
        stopped = new_controller()
        stopped.open_target(target_of(STOPPED, stop=True))
        views.append(stopped.view())
        loading = new_controller()
        loading.open_target(target_of(GENERIC))
        views.append(loading.view())
        for row in (GENERIC, APPLIANCE, HEALTH, SOFTWARE, REJECTED):
            controller = made(row)
            controller.inspect()
            controller.toggle_options()
            controller.set_common_open(True)
            controller.mark_copied("all")
            views.append(controller.view())
            controller.set_body(controller.body + "\n\n직접 써 보니 정말 좋았습니다. 가격은 12,000원이었어요.")
            controller.inspect()
            views.append(controller.view())
            views.append({"dialog": controller.copy_decision("body")[1], "regen": controller.regen_dialog(), "leave": controller.leave_dialog(), "close": controller.leave_dialog("close"), "blocked": controller.blocked_dialog()})
        leaks = r"\['|\bNone\b|\bTrue\b|\bFalse\b|Traceback|\bnaver_[ab]\b|\bgeneric\b|\bappliance\b|\bCONTENT_INVALID\b|\bDRAFT_OPTION_INVALID\b|\bTOPIC_[A-Z_]+\b"
        count = 0
        for view in views:
            normal = view.get("normal")
            shown = {key: item for key, item in view.items() if key != "normal"}
            if normal:                                                        # 본문·제목 후보·적은 칸의 글은 서비스가 만든 글이거나 사용자가 적은 글이라 따로 본다 — 나머지(문구·단추·확인 권장 줄)는 모두 훑는다
                editor = {key: item for key, item in normal["editor"].items() if key != "value"}
                title_box = {key: item for key, item in normal["title_box"].items() if key not in ("value", "picks")}
                options = {key: item for key, item in normal["options"].items() if key != "fields"}
                shown["normal"] = {**normal, "editor": editor, "title_box": title_box, "options": options}
            for value in all_strings(shown, KEYS_NOT_SHOWN):
                count += 1
                self.assertNotRegex(value, leaks)
                for word in FORBIDDEN_WORDS + text.FORBIDDEN:
                    self.assertFalse(word in value, f"{word} / {value[:40]}")
        self.assertGreater(count, 300)


# ---- 5) 글 모양 점검(N-2) — 경고만 한다: 규칙은 `check/garbage.py`, 이 묶음은 그 결과를 사람이 읽는 말로 바꾸는 화면 계층(`draft_garbage.py`)과 컨트롤러 연결 ------------------------------------------------------------------
def run_garbage(controller):
    """`검사하기` 와 같은 길 — 작업 스레드에서 돌리고 도착한 결과를 적용한다(순수 시험이라 콜백이 모은 값을 직접 적용한다)."""
    got = {}
    status, job = controller.start_garbage(on_done=lambda result, payload: got.setdefault("ok", result), on_error=lambda failure, payload: got.setdefault("err", failure))
    if job is not None:
        job.join(30)
    if "ok" in got:
        controller.apply_garbage(got["ok"])
    elif "err" in got:
        controller.apply_garbage_failed(got["err"])
    return status


def checked(body, title=None, row=SOFTWARE):
    """초안을 만들고 본문(과 제목)을 고쳐 글 모양 점검까지 마친 컨트롤러."""
    controller = made(row)
    controller.set_body(body)
    if title is not None:
        controller.set_title(title)
    run_garbage(controller)
    return controller


def card_rows(card):
    return [row["text"] for group in card["groups"] for row in group["rows"]]


class Held:
    """검사 작업을 시험이 문을 열어 줄 때까지 붙잡는다 — 시간에 기대지 않고 '도는 중' 을 확실히 본다."""

    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()
        self.threads = []
        self.real = dg.run

    def __call__(self, generation, title, body):
        self.threads.append(threading.current_thread())
        self.entered.set()
        if not self.release.wait(30):
            raise AssertionError("시험이 문을 열어 주지 않았다")
        return self.real(generation, title, body)


class Forbidden:
    """불리면 실패하는 규칙 — '복사 길·글 치기·보기에서는 규칙을 부르지 않는다' 를 증명한다."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("글 모양 점검 규칙이 불렸다")


class GarbageTrackerTest(unittest.TestCase):
    """세대 번호·낡은 결과 판정·무시 기억·카드 — Qt 도 작업 스레드도 없이 도는 순수 논리(CI 가 돌린다)."""

    def tracker_with(self, title, body):
        tracker = dg.GarbageTracker()
        generation = tracker.begin(title, body)
        self.assertTrue(tracker.deliver(dg.run(generation, title, body)))
        return tracker

    def test_a_new_tracker_shows_the_before_state_and_has_nothing(self):
        card = dg.GarbageTracker().card("", "")
        self.assertEqual((card["state"], card["tone"], card["status"], card["busy"], card["groups"], card["stale"]), ("before", "muted", T["drf_g_before"], False, [], ""))
        self.assertEqual((card["button"]["text"], card["button"]["enabled"]), (T["drf_inspect_btn"], True))

    def test_each_check_gets_a_new_generation_and_a_second_start_is_refused_while_one_runs(self):
        tracker = dg.GarbageTracker()
        first = tracker.begin("제목", "본문")
        self.assertEqual((tracker.running, tracker.begin("제목", "본문")), (True, None))
        self.assertTrue(tracker.deliver(dg.run(first, "제목", "본문")))
        second = tracker.begin("제목", "본문")
        self.assertGreater(second, first)
        self.assertGreater(first, 0)

    def test_the_running_card_says_so_and_turns_the_button_into_checking(self):
        tracker = dg.GarbageTracker()
        tracker.begin("제목", "본문")
        card = tracker.card("제목", "본문")
        self.assertEqual((card["state"], card["tone"], card["status"], card["busy"]), ("running", "muted", T["drf_g_running"], True))
        self.assertEqual(card["button"], {"text": "검사 중…", "a11y": T["drf_g_busy_a11y"], "enabled": False})

    def test_a_result_is_taken_once_and_only_for_the_running_check(self):
        tracker = dg.GarbageTracker()
        generation = tracker.begin("제목", "본문")
        result = dg.run(generation, "제목", "본문")
        self.assertTrue(tracker.deliver(result))
        self.assertFalse(tracker.deliver(result), "같은 결과를 두 번 받지 않는다")
        self.assertEqual(tracker.card("제목", "본문")["state"], "clean")

    def test_a_result_of_another_generation_is_dropped_and_the_running_check_goes_on(self):
        tracker = dg.GarbageTracker()
        generation = tracker.begin("제목", "본문")
        stranger = dg.run(generation + 7, "제목", "본문")
        self.assertFalse(tracker.deliver(stranger))
        self.assertEqual((tracker.pending, tracker.result), (generation, None))
        self.assertFalse(tracker.deliver(None))
        self.assertTrue(tracker.deliver(dg.run(generation, "제목", "본문")))

    def test_reset_while_running_drops_the_late_result_and_clears_everything(self):
        tracker = dg.GarbageTracker()
        generation = tracker.begin("제목", "{{a}} {{b}}")
        late = dg.run(generation, "제목", "{{a}} {{b}}")
        tracker.ignored.add("placeholder:x")
        tracker.reset()
        self.assertFalse(tracker.deliver(late))
        self.assertEqual((tracker.pending, tracker.result, tracker.ignored, tracker.failed, tracker.card("제목", "")["state"]), (None, None, set(), False, "before"))
        self.assertGreater(tracker.generation, generation)

    def test_a_failure_is_taken_only_for_the_running_check_and_the_next_start_clears_it(self):
        tracker = dg.GarbageTracker()
        generation = tracker.begin("제목", "본문")
        self.assertFalse(tracker.fail(generation + 1))
        self.assertTrue(tracker.running)
        self.assertTrue(tracker.fail(generation))
        card = tracker.card("제목", "본문")
        self.assertEqual((card["state"], card["tone"], card["status"], card["busy"]), ("failed", "muted", T["drf_g_failed"], False))
        self.assertFalse(tracker.fail(generation), "이미 끝난 검사의 실패를 다시 받지 않는다")
        self.assertIsNotNone(tracker.begin("제목", "본문"))
        self.assertEqual(tracker.card("제목", "본문")["state"], "running")

    def test_stale_follows_the_digest_of_what_was_checked(self):
        tracker = self.tracker_with("제목", "가나다")
        self.assertEqual(tracker.stale("제목", "가나다"), "")
        self.assertEqual(tracker.stale("제목", "가나다라"), "body", "글자 수가 다르면 바뀐 것")
        self.assertEqual(tracker.stale("제목", "가나라"), "body", "글자 수가 같아도 지문이 다르면 바뀐 것")
        self.assertEqual(tracker.stale("다른 제목", "가나다"), "title")
        self.assertEqual(tracker.stale("다른 제목", "가나다라"), "body", "본문이 먼저다")
        self.assertEqual(tracker.stale("제목", "가나다"), "", "고쳤다 되돌리면 낡지 않았다")
        self.assertEqual(tracker.stale("제목", "".join(["가", "나", "다"])), "", "같은 글이면 다른 객체여도 같다")

    def test_the_digest_is_a_short_hash_that_does_not_hold_the_text(self):
        digest = dg.digest_of("고유표지문장")
        self.assertEqual((len(digest), set(digest) <= set("0123456789abcdef")), (16, True))
        self.assertEqual(dg.digest_of("고유표지문장"), digest)
        self.assertNotEqual(dg.digest_of("고유표지문장 "), digest)
        result = dg.run(3, "고유제목표지", "고유본문표지")
        self.assertNotIn("고유", repr(result))
        self.assertEqual((result.generation, result.title_digest, result.body_digest), (3, dg.digest_of("고유제목표지"), dg.digest_of("고유본문표지")))

    def test_the_stale_card_keeps_the_result_and_says_the_body_changed(self):
        tracker = self.tracker_with("제목", "앞 {{이름}} 뒤")
        fresh = tracker.card("제목", "앞 {{이름}} 뒤")
        stale = tracker.card("제목", "앞 {{이름}} 뒤 더")
        self.assertEqual((fresh["stale"], fresh["stale_text"]), ("", ""))
        self.assertEqual((stale["stale"], stale["state"], stale["stale_text"]), ("body", "found", T["drf_g_stale_body"]))
        self.assertTrue(stale["stale_text"].startswith("본문이 변경됨"))
        self.assertEqual(stale["groups"], fresh["groups"], "결과는 지우지 않는다")
        title_only = tracker.card("다른 제목", "앞 {{이름}} 뒤")
        self.assertEqual((title_only["stale"], title_only["stale_text"]), ("title", T["drf_g_stale_title"]))

    def test_ignoring_one_hides_every_same_fingerprint_and_restore_brings_them_back(self):
        tracker = self.tracker_with("", "가&nbsp;나&nbsp;다&nbsp;라 {{이름}}")
        card = tracker.card("", "가&nbsp;나&nbsp;다&nbsp;라 {{이름}}")
        self.assertEqual(card["status"], T["drf_g_found"].format(n=4))
        entity = next(group for group in card["groups"] if group["kind"] == "entity")
        self.assertEqual(len(entity["rows"]), 3)
        self.assertTrue(tracker.ignore(entity["rows"][1]["key"]))
        after = tracker.card("", "가&nbsp;나&nbsp;다&nbsp;라 {{이름}}")
        self.assertEqual((after["status"], [group["kind"] for group in after["groups"]]), (T["drf_g_found"].format(n=1), ["placeholder"]))
        self.assertEqual((after["restore"]["visible"], after["restore"]["text"]), (True, T["drf_g_restore"].format(n=3)))
        self.assertTrue(tracker.restore())
        self.assertEqual((tracker.card("", "")["restore"]["visible"], tracker.restore()), (False, False))

    def test_ignore_all_takes_what_was_only_counted_not_just_what_was_shown(self):
        body = "\n".join("줄 {{" + f"p{number:02d}" + "}} 입니다" for number in range(25))
        tracker = self.tracker_with("", body)
        card = tracker.card("", body)
        self.assertEqual((card["status"], len(card["groups"][0]["rows"]), card["groups"][0]["more"]), (T["drf_g_found"].format(n=25), 10, T["drf_g_more"].format(n=15)))
        self.assertEqual(card["ignore_all"], {"text": "모두 무시(25건)", "a11y": T["drf_g_ignore_all_a11y"].format(n=25), "visible": True}, "숨은 건까지 무시되므로 단추에 건수가 적힌다")
        self.assertTrue(tracker.ignore_all())
        after = tracker.card("", body)
        self.assertEqual((after["state"], after["status"], after["groups"], after["restore"]["text"]), ("clean", T["drf_g_clean_ignored"].format(n=25), [], T["drf_g_restore"].format(n=25)))
        self.assertFalse(tracker.ignore_all(), "더 무시할 것이 없다")

    def test_the_next_check_forgets_ignored_things_that_are_gone_and_keeps_those_that_remain(self):
        tracker = self.tracker_with("", "{{a}} {{b}}")
        self.assertTrue(tracker.ignore_all())
        generation = tracker.begin("", "{{a}} {{c}}")
        tracker.deliver(dg.run(generation, "", "{{a}} {{c}}"))
        card = tracker.card("", "{{a}} {{c}}")
        self.assertEqual((card["status"], card["restore"]["text"], len(tracker.ignored)), (T["drf_g_found"].format(n=1), T["drf_g_restore"].format(n=1), 1))
        self.assertEqual(card_rows(card), ["본문 1문단 1번째 줄 앞에서 7번째 글자 · ‘{{c}}’"], "새로 생긴 것은 새 항목으로 보인다")

    def test_the_ignore_all_button_says_how_many_it_takes_and_follows_the_visible_count(self):
        """N2FIX — `모두 무시` 는 숨은 건(10건을 넘어 개수로만 보이던 것)까지 지문으로 무시하므로 단추 글에 건수를 적는다. 건수는 지금 보이는 건수를 따라 바뀐다."""
        body = "{{a}} {{b}} {{c}} {{d}}"
        tracker = self.tracker_with("", body)
        card = tracker.card("", body)
        self.assertEqual(card["ignore_all"], {"text": "모두 무시(4건)", "a11y": T["drf_g_ignore_all_a11y"].format(n=4), "visible": True})
        self.assertTrue(tracker.ignore(card["groups"][0]["rows"][0]["key"]))
        self.assertEqual(tracker.card("", body)["ignore_all"], {"text": "모두 무시(3건)", "a11y": T["drf_g_ignore_all_a11y"].format(n=3), "visible": True})
        self.assertTrue(tracker.ignore(tracker.card("", body)["groups"][0]["rows"][0]["key"]))
        self.assertEqual(tracker.card("", body)["ignore_all"], {"text": "모두 무시(2건)", "a11y": T["drf_g_ignore_all_a11y"].format(n=2), "visible": True})
        self.assertTrue(tracker.ignore(tracker.card("", body)["groups"][0]["rows"][0]["key"]))
        self.assertEqual(tracker.card("", body)["ignore_all"], {"text": "", "a11y": "", "visible": False}, "하나만 남으면 단추가 없다")
        for state_card in (dg.GarbageTracker().card("", ""), self.tracker_with("", "깨끗해요").card("", "깨끗해요")):
            self.assertEqual(state_card["ignore_all"], {"text": "", "a11y": "", "visible": False})

    def test_a_key_whose_number_is_the_count_of_the_visible_items_changes_nothing(self):
        """B04 — 열쇠의 순번은 0 부터 보이는 건수 미만이다. 건수와 같은 순번(마지막 다음)은 받지 않는다."""
        body = "{{a}} {{b}} {{c}}"
        tracker = self.tracker_with("", body)
        generation = tracker.card("", body)["groups"][0]["rows"][0]["key"].partition(".")[0]
        self.assertFalse(tracker.ignore(f"{generation}.{len(tracker.visible())}"))
        self.assertEqual(tracker.ignored, set())
        self.assertTrue(tracker.ignore(f"{generation}.{len(tracker.visible()) - 1}"), "마지막 순번은 받는다")
        self.assertFalse(tracker.ignore(f"{generation}.{len(tracker.visible())}"), "하나 줄어든 건수와 같은 순번도 받지 않는다")
        self.assertEqual(len(tracker.ignored), 1)

    def test_ignore_all_after_ignoring_one_keeps_the_first_one_and_takes_the_rest(self):
        """B05 — 먼저 하나를 무시한 뒤 `모두 무시` 를 눌러도 먼저 무시한 것이 되살아나지 않는다(합쳐서 무시한 건수가 전체다)."""
        body = "{{a}} {{b}} {{c}} {{d}}"
        tracker = self.tracker_with("", body)
        self.assertTrue(tracker.ignore(tracker.card("", body)["groups"][0]["rows"][0]["key"]))
        self.assertTrue(tracker.ignore_all())
        card = tracker.card("", body)
        self.assertEqual((len(tracker.ignored), card["state"], card["restore"]["text"]), (4, "clean", T["drf_g_restore"].format(n=4)))

    def test_abandon_turns_a_delivered_result_into_the_failed_card_and_the_next_check_works(self):
        """D4 — 결과를 받은 뒤 화면에 그리다 예외가 났을 때(`deliver()` 가 이미 도는 중 번호를 지운 뒤) 카드를 `점검을 끝내지 못했어요` 로 둔다. `fail()` 은 이 길에서 아무것도 못 한다."""
        tracker = self.tracker_with("제목", "{{a}} {{b}}")
        tracker.ignored.add("placeholder:keep")
        tracker.abandon()
        card = tracker.card("제목", "{{a}} {{b}}")
        self.assertEqual((card["state"], card["tone"], card["status"], card["busy"], card["groups"], card["button"]["enabled"], card["ignore_all"]["visible"], card["restore"]["visible"]),
                         ("failed", "muted", T["drf_g_failed"], False, [], True, False, False))
        self.assertEqual((tracker.running, tracker.result, tracker.pending, tracker.failed, tracker.ignored), (False, None, None, True, {"placeholder:keep"}), "무시 기억은 그대로")
        self.assertEqual((tracker._snapshot, tracker._asked), (None, None), "검사했던 글의 복사본을 놓는다(받아 둔 원문을 쥐고 있지 않는다)")
        self.assertEqual((tracker.visible(), tracker.ignored_count(), tracker.stale("제목", "다른 글"), tracker.ignore("1.0"), tracker.ignore_all()), ((), 0, "", False, False))
        self.assertFalse(tracker.fail(tracker.generation), "이미 끝난 것의 실패를 다시 받지 않는다")
        generation = tracker.begin("제목", "{{a}} {{b}}")
        self.assertTrue(tracker.deliver(dg.run(generation, "제목", "{{a}} {{b}}")))
        self.assertEqual((tracker.card("제목", "{{a}} {{b}}")["state"], tracker.failed), ("found", False), "다음 검사는 정상이다")

    def test_abandon_while_a_check_is_running_drops_its_late_result(self):
        tracker = dg.GarbageTracker()
        generation = tracker.begin("제목", "{{a}}")
        late = dg.run(generation, "제목", "{{a}}")
        self.assertEqual(tracker._asked, ("제목", "{{a}}"), "(전제) 도는 동안 검사 때의 글 복사본을 쥐고 있다")
        tracker.abandon()
        self.assertEqual((tracker.running, tracker.card("제목", "{{a}}")["state"]), (False, "failed"))
        self.assertEqual((tracker._asked, tracker._snapshot), (None, None), "도는 중에 버리면 검사 때의 글 복사본도 놓는다")
        self.assertFalse(tracker.deliver(late), "도는 중 번호를 지웠으니 늦게 온 결과는 받지 않는다")

    def test_a_key_of_another_generation_or_out_of_range_changes_nothing(self):
        tracker = self.tracker_with("", "{{a}}")
        key = tracker.card("", "{{a}}")["groups"][0]["rows"][0]["key"]
        generation, _dot, number = key.partition(".")
        for bad in (f"{int(generation) + 1}.{number}", f"{generation}.99", f"{generation}.-1", f"{generation}.x", "", "x", None, 5, f"{generation}."):
            with self.subTest(bad):
                self.assertFalse(tracker.ignore(bad))
        self.assertEqual(tracker.ignored, set())
        self.assertTrue(tracker.ignore(key))

    def test_the_card_only_uses_the_info_and_muted_tones_in_every_state(self):
        bodies = ("", "깨끗한 글이에요.", "{{a}}", "{{a}} " + GS.ZWSP, "가" * 100_001)
        tones = set()
        for body in bodies:
            tracker = dg.GarbageTracker()
            generation = tracker.begin("제목", body)
            tracker.deliver(dg.run(generation, "제목", body))
            tones.add(tracker.card("제목", body)["tone"])
            tones.add(tracker.card("제목", body + "더")["tone"])
            tracker.ignore_all()
            tones.add(tracker.card("제목", body)["tone"])
        running = dg.GarbageTracker()
        running.begin("", "")
        failed = dg.GarbageTracker()
        failed.fail(failed.begin("", ""))
        tones |= {dg.GarbageTracker().card("", "")["tone"], running.card("", "")["tone"], failed.card("", "")["tone"]}
        self.assertEqual(tones, {"info", "muted"}, "빨강(error)·주황(warning)·초록(ok) 은 막음·확인창·안전의 뜻이라 쓰지 않는다")

    def test_the_states_have_their_own_status_lines(self):
        fresh = self.tracker_with("제목", "깨끗해요").card("제목", "깨끗해요")
        self.assertEqual((fresh["state"], fresh["status"], fresh["groups"], fresh["ignore_all"]["visible"], fresh["restore"]["visible"]), ("clean", T["drf_g_clean"], [], False, False))
        found = self.tracker_with("", "{{a}} {{b}}").card("", "{{a}} {{b}}")
        self.assertEqual((found["state"], found["tone"], found["status"], found["ignore_all"]["visible"]), ("found", "info", T["drf_g_found"].format(n=2), True))
        single = self.tracker_with("", "{{a}}").card("", "{{a}}")
        self.assertEqual(single["ignore_all"]["visible"], False, "하나뿐이면 '모두 무시' 가 따로 필요 없다")
        skipped = self.tracker_with("", "가" * 100_001).card("", "가" * 100_001)
        self.assertEqual((skipped["state"], skipped["tone"], skipped["status"], skipped["groups"]), ("skipped", "muted", T["drf_g_skipped"], []))

    def test_at_most_ten_details_of_one_kind_are_shown_and_the_rest_is_only_a_count(self):
        for total in (9, 10, 11, 35):
            with self.subTest(total):
                body = "\n".join("{{" + f"p{number:02d}" + "}}" for number in range(total))
                tracker = self.tracker_with("", body)
                group = tracker.card("", body)["groups"][0]
                self.assertEqual((len(group["rows"]), group["chip"], group["more"]), (min(total, 10), T["drf_g_chip"].format(n=total), T["drf_g_more"].format(n=total - 10) if total > 10 else ""))

    def test_an_ignored_item_lets_the_next_hidden_one_take_its_place(self):
        body = "\n".join("{{" + f"p{number:02d}" + "}}" for number in range(12))
        tracker = self.tracker_with("", body)
        group = tracker.card("", body)["groups"][0]
        self.assertEqual(group["more"], T["drf_g_more"].format(n=2))
        tracker.ignore(group["rows"][0]["key"])
        group = tracker.card("", body)["groups"][0]
        self.assertEqual((len(group["rows"]), group["more"], group["chip"]), (10, T["drf_g_more"].format(n=1), T["drf_g_chip"].format(n=11)))
        self.assertTrue(group["rows"][-1]["text"].endswith("‘{{p10}}’"))

    def test_the_kinds_come_in_the_fixed_order_and_every_key_is_unique(self):
        body = S_ALL_KINDS
        tracker = self.tracker_with("", body)
        card = tracker.card("", body)
        self.assertEqual([group["kind"] for group in card["groups"]], list(garbage_rule.KINDS))
        keys = [row["key"] for group in card["groups"] for row in group["rows"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual([group["title"] for group in card["groups"]], [T["drf_g_kind_" + kind] for kind in garbage_rule.KINDS])
        for group in card["groups"]:
            self.assertEqual(group["reason"].count("\n"), 0)
            self.assertTrue(group["reason"].startswith(T["drf_g_why_" + group["kind"]]))

    def test_each_row_names_its_place_and_its_reason(self):
        body = "첫 문단\n\n안녕" + GS.ZWSP + "하세요 {{이름}}"
        rows = card_rows(self.tracker_with("제목 {{a}}", body).card("제목 {{a}}", body))
        self.assertEqual(rows, ["본문 2문단 1번째 줄 앞에서 3번째 글자 · ‘안녕’ 바로 뒤 · 폭 없는 공백(U+200B) 1개", "제목 앞에서 4번째 글자 · ‘{{a}}’", "본문 2문단 1번째 줄 앞에서 8번째 글자 · ‘{{이름}}’"])

    def test_every_kind_has_a_row_shape(self):
        sentence = "사랑해요 영원히 변하지 않을 거예요."
        cases = {
            "broken": ("앞 글자" + GS.FFFD + GS.FFFD, "본문 1문단 1번째 줄 앞에서 5번째 글자 · ‘앞 글자’ 바로 뒤 · 대체 문자(U+FFFD) 2개"),
            "control": ("색 " + GS.ESC + "빨강", "본문 1문단 1번째 줄 앞에서 3번째 글자 · ‘색’ 바로 뒤 · 제어 문자 이스케이프(U+001B)"),
            "entity": ("가격&nbsp;12", "본문 1문단 1번째 줄 앞에서 3번째 글자 · ‘&nbsp;’"),
            "fence": (GS.fenced("코드"), "본문 1문단 1번째 줄 앞에서 1번째 글자 외 1곳 · 역따옴표 세 개 줄 2줄"),
            "dup_word": ("그래서 좋아요 좋아요 좋아요", "본문 1문단 1번째 줄 앞에서 5번째 글자 · ‘좋아요 좋아요 좋아요’ · 붙어서 3번"),
            "dup_sentence": (sentence + "\n\n다른 문단이에요.\n\n" + sentence, "본문 1문단 1번째 줄과 3문단 1번째 줄 · ‘사랑해요 영원히 변하지…’ · 2번 나와요"),
        }
        for kind, (body, wanted) in cases.items():
            with self.subTest(kind):
                card = self.tracker_with("", body).card("", body)
                self.assertEqual([row["text"] for group in card["groups"] if group["kind"] == kind for row in group["rows"]], [wanted])

    def test_the_same_sentence_twice_on_one_line_is_told_apart_by_the_character_numbers(self):
        sentence = "사랑해요 영원히 변하지 않을 거예요."
        body = sentence + " " + sentence + " " + sentence
        rows = card_rows(self.tracker_with("", body).card("", body))
        self.assertEqual(rows, ["본문 1문단 1번째 줄 앞에서 1번째 글자와 22번째 글자 외 1곳 · ‘사랑해요 영원히 변하지…’ · 3번 나와요"])
        two = card_rows(self.tracker_with("", sentence + " " + sentence).card("", sentence + " " + sentence))
        self.assertEqual(two, ["본문 1문단 1번째 줄 앞에서 1번째 글자와 22번째 글자 · ‘사랑해요 영원히 변하지…’ · 2번 나와요"])
        other_line = card_rows(self.tracker_with("", sentence + "\n" + sentence).card("", sentence + "\n" + sentence))
        self.assertEqual(other_line, ["본문 1문단 1번째 줄과 1문단 2번째 줄 · ‘사랑해요 영원히 변하지…’ · 2번 나와요"], "다른 줄이면 줄 번호로 가른다")

    def test_a_hit_on_a_blank_line_and_on_a_leading_blank_line_say_so(self):
        for body, wanted in (("첫 문단\n\n" + GS.ZWSP + "\n\n끝", "본문 1문단 다음 빈 줄 앞에서 1번째 글자 · 줄 맨 앞 · 폭 없는 공백(U+200B) 1개"), ("\n" + GS.ZWSP + "\n본문", "본문 맨 앞 빈 줄 앞에서 1번째 글자 · 줄 맨 앞 · 폭 없는 공백(U+200B) 1개")):
            with self.subTest(body[:8]):
                self.assertEqual(card_rows(self.tracker_with("", body).card("", body)), [wanted])

    def test_a_hit_in_the_title_names_the_title_and_a_hit_at_its_start_says_so(self):
        card = self.tracker_with(GS.ZWSP + "제목", "본문").card(GS.ZWSP + "제목", "본문")
        self.assertEqual(card_rows(card), ["제목 앞에서 1번째 글자 · 제목 맨 앞 · 폭 없는 공백(U+200B) 1개"])

    def test_the_text_before_a_hit_is_cut_to_eight_characters_and_the_caught_text_to_twelve(self):
        before = "일이삼사오육칠팔구십" + GS.ZWSP
        self.assertEqual(card_rows(self.tracker_with("", before).card("", before)), ["본문 1문단 1번째 줄 앞에서 11번째 글자 · ‘…삼사오육칠팔구십’ 바로 뒤 · 폭 없는 공백(U+200B) 1개"])
        sentence = "사랑해요 영원히 변하지 않을 거예요."
        body = sentence + "\n\n" + sentence
        row = card_rows(self.tracker_with("", body).card("", body))[0]
        self.assertIn("‘사랑해요 영원히 변하지…’", row)
        self.assertNotIn("않", row)
        short = "{{" + "가" * 30 + "}}"
        self.assertIn("‘{{" + "가" * 10 + "…’", card_rows(self.tracker_with("", short).card("", short))[0])

    def test_a_group_of_the_same_character_is_one_row_with_a_count_and_the_first_place(self):
        body = "가" + GS.ZWSP * 3 + "나\n\n다" + GS.ZWSP + "라"
        rows = card_rows(self.tracker_with("", body).card("", body))
        self.assertEqual(rows, ["본문 1문단 1번째 줄 앞에서 2번째 글자 외 3곳 · ‘가’ 바로 뒤 · 폭 없는 공백(U+200B) 4개"])

    def test_every_invisible_character_of_the_rule_has_a_name_and_the_code_is_shown(self):
        named = []
        for code in range(0xE0100):
            if garbage_rule._INVISIBLE.fullmatch(chr(code)):
                self.assertNotEqual(dg.invisible_name(code), T["drf_g_n_other"], hex(code))
                named.append(code)
        self.assertGreater(len(named), 100)
        self.assertEqual(dg.invisible_name(0x1F600), T["drf_g_n_other"])

    def test_invisible_and_control_characters_beside_a_hit_are_shown_as_boxes_and_never_raw_anywhere_on_the_card(self):
        body = "가나" + GS.WJ + "다" + GS.ZWSP + " 색 " + GS.ESC + GS.FFFD + "끝 {{이름}}"
        card = self.tracker_with("제목" + GS.BOM, body).card("제목" + GS.BOM, body)
        rows = card_rows(card)
        self.assertTrue([row for row in rows if "가나" + dg.BOX + "다" in row], rows)
        for value in all_strings(card, KEYS_NOT_SHOWN):
            self.assertIsNone(garbage_rule.HIDDEN.search(value), f"보이지 않는 글자가 카드에 날것으로 나갔다: {value[:40]!r}")

    def test_a_key_shape_next_to_a_hit_is_never_repeated_on_the_card(self):
        key = GS.KEY_SHAPED
        cases = (key + GS.ZWSP + "뒤", "앞" + GS.ZWSP + key, key + "{{이름}}", "{{이름}}" + key, " ".join([key] * 4), key + GS.FFFD + key, key + "&nbsp;" + key, key + GS.ESC + key, key + " 좋아요 좋아요 좋아요 " + key, "{{" + key + "}}",
                 key + GS.fenced("코드") + key, "\n\n".join([key + " 같은 문장이 되풀이돼요 정말로 그래요.", key + " 같은 문장이 되풀이돼요 정말로 그래요."]))
        for body in cases:
            with self.subTest(body[:30].replace("\n", " ")):
                card = self.tracker_with(key + " 제목" + GS.ZWSP, body).card(key + " 제목" + GS.ZWSP, body)
                shown = " ".join(all_strings(card, KEYS_NOT_SHOWN))
                for start in range(0, len(key) - 7):
                    self.assertNotIn(key[start:start + 8], shown, "키 모양의 조각이 카드에 되풀이됐다")

    def test_the_card_has_no_original_sentence_beyond_the_cut_pieces(self):
        long_sentence = "고유한표지문장은이렇게길어서한번에다보이면안되는문장이에요."
        body = long_sentence + "\n\n" + long_sentence
        shown = " ".join(all_strings(self.tracker_with("", body).card("", body), KEYS_NOT_SHOWN))
        self.assertNotIn(long_sentence[:16], shown)
        self.assertIn(long_sentence[:12], shown)

    def test_the_card_texts_have_no_python_text_enum_name_or_forbidden_word(self):
        leaks = r"\['|\bNone\b|\bTrue\b|\bFalse\b|Traceback|\bnaver_[ab]\b|\bgeneric\b|\bplaceholder\b|\bdup_word\b|\bdup_sentence\b|\binvisible\b|\bbroken\b|\bfence\b|\bentity\b|\bcontrol\b"
        card = self.tracker_with("", S_ALL_KINDS).card("", S_ALL_KINDS)
        strings = list(all_strings(card, KEYS_NOT_SHOWN))
        self.assertGreater(len(strings), 40)
        for value in strings:
            self.assertNotRegex(value, leaks)
            for word in FORBIDDEN_WORDS + text.FORBIDDEN:
                self.assertFalse(word in value, f"{word} / {value[:40]}")

    def test_five_thousand_findings_make_the_card_fast_and_repeated_cards_are_cheap(self):
        import time
        body = "\n".join("{{" + f"p{number:04d}" + "}}" for number in range(5000))
        tracker = self.tracker_with("", body)
        start = time.perf_counter()
        card = tracker.card("", body)
        built = time.perf_counter() - start
        self.assertLess(built, 2.0)
        self.assertEqual((card["status"], card["groups"][0]["more"]), (T["drf_g_found"].format(n=5000), T["drf_g_more"].format(n=4990)))
        start = time.perf_counter()
        for _ in range(200):
            tracker.card("", body + "더")
        self.assertLess(time.perf_counter() - start, 1.0, "글을 칠 때마다 불러도 가볍다(가공은 결과가 바뀔 때만)")


S_ALL_KINDS = ("깨진 " + GS.FFFD + " 글자 그리고 " + GS.ZWSP + "\n\n색 " + GS.ESC + "빨강 가격&nbsp;12 {{이름}} 그래서 좋아요 좋아요 좋아요\n\n" + GS.fenced("코드") +
               "\n\n사랑해요 영원히 변하지 않을 거예요.\n\n그날을 기억해요.\n\n사랑해요 영원히 변하지 않을 거예요.")


class GarbageControllerTest(unittest.TestCase):
    """컨트롤러 연결 — 작업 스레드로 한 길만 돌고, 세대 번호로 낡은 결과를 버리고, 새 초안·떠남·닫기에서 모두 지운다."""

    def test_a_check_needs_a_draft_and_is_refused_while_the_draft_is_being_made(self):
        empty = new_controller()
        self.assertEqual(empty.start_garbage(), ("unavailable", None))
        busy = made(SOFTWARE)
        with mock.patch.object(type(busy), "busy", new_callable=mock.PropertyMock, return_value=True):
            self.assertEqual(busy.start_garbage(), ("unavailable", None))

    def test_the_check_runs_on_another_thread_and_the_callbacks_too_and_the_result_holds_no_text(self):
        controller = made(SOFTWARE)
        controller.set_body("고유본문표지 {{a}}")
        threads, got = [], {}
        held = Held()
        with mock.patch.object(dg, "run", held):
            status, job = controller.start_garbage(on_done=lambda result, payload: (threads.append(threading.current_thread()), got.setdefault("ok", result)), on_error=lambda failure, payload: None)
            held.release.set()
            job.join(30)
        self.assertEqual(status, "started")
        self.assertIsNot(held.threads[0], threading.current_thread(), "검사는 화면 스레드가 아니라 작업 스레드에서 돈다")
        self.assertIsNot(threads[0], threading.current_thread())
        self.assertNotIn("고유본문", repr(got["ok"]))
        self.assertTrue(controller.apply_garbage(got["ok"]))

    def test_while_running_the_card_says_checking_and_a_second_start_is_busy(self):
        held = Held()
        with mock.patch.object(dg, "run", held):
            controller = made(SOFTWARE)
            controller.set_body("{{a}}")
            status, job = controller.start_garbage()
            self.assertTrue(held.entered.wait(10))
            card = controller.garbage_card()
            self.assertEqual((status, card["state"], card["busy"], card["button"]["text"], card["button"]["enabled"]), ("started", "running", True, "검사 중…", False))
            self.assertEqual(controller.start_garbage(), ("busy", None), "중복 실행 방지")
            held.release.set()
            job.join(10)
        self.assertEqual(controller.garbage_card()["state"], "running", "결과를 적용하기 전까지는 도는 중이다")

    def test_the_result_is_applied_once_and_a_second_check_works(self):
        controller = checked("{{a}} 와 {{b}}")
        card = controller.garbage_card()
        self.assertEqual((card["state"], card["status"], card["busy"]), ("found", T["drf_g_found"].format(n=2), False))
        self.assertEqual((card["stale"], card["stale_text"]), ("", ""), "방금 검사한 글은 낡지 않았다")
        controller.set_body(controller.body + " 더")
        self.assertEqual((controller.garbage_card()["stale"], controller.garbage_card()["stale_text"]), ("body", T["drf_g_stale_body"]))
        controller.set_body(controller.body[:-2])
        self.assertEqual(controller.garbage_card()["stale"], "", "되돌리면 낡지 않았다")
        controller.set_title(controller.title + "!")
        self.assertEqual(controller.garbage_card()["stale"], "title")
        controller.set_title(controller.title[:-1])
        self.assertEqual(run_garbage(controller), "started")
        self.assertEqual(controller.garbage_card()["status"], T["drf_g_found"].format(n=2))

    def test_editing_while_the_check_runs_marks_the_result_stale_when_it_arrives(self):
        held = Held()
        with mock.patch.object(dg, "run", held):
            controller = made(SOFTWARE)
            controller.set_body("{{a}}")
            got = {}
            status, job = controller.start_garbage(on_done=lambda result, payload: got.setdefault("ok", result))
            held.entered.wait(10)
            controller.set_body("{{a}} 더 썼어요")
            held.release.set()
            job.join(10)
        self.assertTrue(controller.apply_garbage(got["ok"]))
        card = controller.garbage_card()
        self.assertEqual((card["state"], card["stale"], card["stale_text"]), ("found", "body", T["drf_g_stale_body"]))
        self.assertEqual(card_rows(card), ["본문 1문단 1번째 줄 앞에서 1번째 글자 · ‘{{a}}’"])

    def test_leaving_the_screen_while_running_drops_the_late_result(self):
        held = Held()
        with mock.patch.object(dg, "run", held):
            controller = made(SOFTWARE)
            controller.set_body("{{a}}")
            got = {}
            status, job = controller.start_garbage(on_done=lambda result, payload: got.setdefault("ok", result), on_cancel=lambda payload: got.setdefault("cancelled", True))
            held.entered.wait(10)
            controller.leave()
            held.release.set()
            job.join(10)
        self.assertEqual(got.keys() & {"ok"}, set(), "취소된 작업은 완료로 알리지 않는다")
        self.assertFalse(controller.apply_garbage(got.get("ok")))
        self.assertEqual(controller.garbage.card("", "")["state"], "before")

    def test_the_worker_checks_the_text_of_the_moment_the_check_started_even_when_it_only_begins_after_an_edit(self):
        """D5 D01 — 작업자가 시작 때의 글 복사본이 아니라 **지금 컨트롤러의 글**을 읽으면(작업자가 늦게 시작하면 그 사이에 바뀐 글을 읽는다) 낡은 글의 점검이 새 글의 결과인 척한다. 작업의 시작을 시험이 미뤄 그 틈을 만든다 — 붙잡는 `Held` 는 인자를 받은 뒤에 붙잡아 이 틈을 못 본다."""
        deferred = []

        class Deferred(dv.Job):
            def start(self):                                             # 시작을 미룬다 — 시험이 글을 바꾼 뒤 직접 돌린다
                deferred.append(self)
                return True

        seen = []
        real = dg.run

        def spy(generation, title, body):
            seen.append((title, body))
            return real(generation, title, body)

        controller = made(SOFTWARE)
        controller.set_title("시작 때 제목")
        controller.set_body("시작 때 본문 {{a}}")
        with mock.patch.object(dv, "Job", Deferred), mock.patch.object(dg, "run", spy):
            status, job = controller.start_garbage()
            controller.set_title("고친 제목")
            controller.set_body("고친 본문")
            deferred[0]._run()                                           # 작업자는 글이 바뀐 뒤에야 일을 시작한다
        self.assertEqual((status, seen), ("started", [("시작 때 제목", "시작 때 본문 {{a}}")]))

    def test_a_late_cancel_notice_never_changes_the_check_that_is_running_now(self):
        """E02 의 순수 쪽 — 취소 알림은 아무것도 바꾸지 않는다(새 초안·떠남·닫기에서 이미 모두 지웠다)."""
        held = Held()
        controller = made(SOFTWARE)
        controller.set_body("{{a}}")
        with mock.patch.object(dg, "run", held):
            status, job = controller.start_garbage()
            self.assertTrue(held.entered.wait(10))
            self.assertFalse(controller.apply_garbage_cancelled())
            card = controller.garbage_card()
            self.assertEqual((card["state"], controller.garbage.running, controller.garbage.failed), ("running", True, False))
            held.release.set()
            job.join(10)

    def test_a_new_draft_or_another_candidate_while_running_drops_the_late_result(self):
        for action in ("regenerate", "open_target"):
            with self.subTest(action):
                held = Held()
                with mock.patch.object(dg, "run", held):
                    controller = made(SOFTWARE)
                    controller.set_body("{{a}}")
                    got = {}
                    status, job = controller.start_garbage(on_done=lambda result, payload: got.setdefault("ok", result))
                    held.entered.wait(10)
                    if action == "regenerate":
                        drive(controller, controller.start_make)
                    else:
                        controller.open_target(target_of(APPLIANCE))
                    held.release.set()
                    job.join(10)
                self.assertFalse(controller.apply_garbage(got.get("ok")))
                self.assertEqual(controller.garbage.card("", "")["state"], "before")

    def test_a_rule_that_raises_makes_a_failed_card_and_the_next_check_works(self):
        controller = made(SOFTWARE)
        controller.set_body("{{a}}")
        with mock.patch.object(dg, "run", Forbidden()):
            self.assertEqual(run_garbage(controller), "started")
        card = controller.garbage_card()
        self.assertEqual((card["state"], card["status"], card["busy"], card["tone"]), ("failed", T["drf_g_failed"], False, "muted"))
        self.assertEqual(controller.state, "normal", "글 모양 점검의 실패가 초안 화면을 오류 상태로 만들지 않는다")
        self.assertEqual(run_garbage(controller), "started")
        self.assertEqual(controller.garbage_card()["state"], "found")

    def test_an_old_failure_does_not_fail_the_new_check(self):
        controller = made(SOFTWARE)
        controller.set_body("{{a}}")
        generation = controller.garbage.begin(controller.title, controller.body)                  # 작업 없이 '도는 중' 상태만 만든다
        old = jobs.JobFailure("x", "Boom")
        old.generation = generation - 100
        self.assertFalse(controller.apply_garbage_failed(old))
        self.assertTrue(controller.garbage.running)
        self.assertFalse(controller.apply_garbage_failed(jobs.JobFailure("x", "Boom")), "어느 검사의 실패인지 모르면 받지 않는다")
        current = jobs.JobFailure("x", "Boom")
        current.generation = generation
        self.assertTrue(controller.apply_garbage_failed(current))
        self.assertEqual(controller.garbage_card()["state"], "failed")

    def test_shutdown_drops_the_result_and_does_not_wait_for_the_worker(self):
        import time
        held = Held()
        with mock.patch.object(dg, "run", held):
            controller = made(SOFTWARE)
            controller.set_body("{{a}}")
            got = {}
            status, job = controller.start_garbage(on_done=lambda result, payload: got.setdefault("ok", result))
            held.entered.wait(10)
            start = time.perf_counter()
            controller.shutdown()
            self.assertLess(time.perf_counter() - start, 0.5, "작업자 종료를 기다리지 않는다")
            held.release.set()
            job.join(10)
        self.assertEqual(got, {})
        self.assertFalse(controller.garbage.running)

    def test_the_side_card_list_has_the_garbage_card_right_after_the_inspect_card(self):
        side = made(SOFTWARE).view()["normal"]["side"]
        keys = list(side)
        self.assertEqual(keys[:3], ["inspect", "garbage", "keywords"])
        self.assertEqual(side["garbage"]["title"], "글 모양 점검")
        self.assertEqual(side["garbage"]["note"], "복사를 막지 않아요")
        self.assertEqual(side["garbage"], made(SOFTWARE).garbage_card())

    def test_ignore_methods_work_through_the_controller_and_a_new_draft_clears_the_memory(self):
        controller = checked("{{a}} {{b}}")
        key = controller.garbage_card()["groups"][0]["rows"][0]["key"]
        self.assertTrue(controller.ignore_garbage(key))
        self.assertEqual(controller.garbage_card()["status"], T["drf_g_found"].format(n=1))
        self.assertTrue(controller.restore_garbage())
        self.assertTrue(controller.ignore_all_garbage())
        self.assertEqual(controller.garbage_card()["state"], "clean")
        controller.set_body("{{a}} {{b}}")
        drive(controller, controller.start_make)
        self.assertEqual(controller.garbage.ignored, set(), "새 초안은 무시 기억을 지운다")
        self.assertEqual(controller.garbage_card()["state"], "before")

    def test_the_ignore_memory_lives_only_in_memory(self):
        source = (UI_DIR / "core" / "draft_garbage.py").read_text(encoding="utf-8")
        for forbidden in ("open(", "write", "json", "sqlite", "pickle", "shelve", "os.", "pathlib", "settings", "environ"):
            self.assertNotIn(forbidden, source, forbidden)
        controller = checked("{{a}} {{b}}")
        controller.ignore_all_garbage()
        simple = (type(None), bool, int, str, tuple, list, set, frozenset, dict, dg.GarbageResult)
        for name, value in vars(controller.garbage).items():
            self.assertIsInstance(value, simple, f"추적기의 {name} 칸은 메모리 값뿐이다(파일·소켓·스레드를 쥐지 않는다)")

    def test_the_scan_is_not_called_while_typing_inspecting_viewing_or_copying(self):
        controller = made(SOFTWARE)
        forbidden = Forbidden()
        with mock.patch.object(dg, "run", forbidden), mock.patch.object(garbage_rule, "scan", forbidden):
            for index in range(5):
                controller.set_title("제목 " + "가" * index)
                controller.set_body(controller.body + " 더 {{a}} " + GS.ZWSP)
            controller.inspect()
            controller.view()
            controller.garbage_card()
            controller.editor_status()
            controller.title_picks()
            controller.inspect_card()
            controller.options_vm()
            for item in rules.COPY_ITEMS:
                controller.copy_decision(item)
                controller.blocks_for(item)
                controller.final_text(item)
                controller.confirm_copy(item)
            controller.leave_dialog()
            controller.regen_dialog()
        self.assertEqual(forbidden.calls, 0)

    def test_only_start_garbage_reaches_the_rule_in_the_controller_source(self):
        path = UI_DIR / "core" / "drafts_view.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        users = []
        for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
            for node in ast.walk(function):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "garbage" and node.attr == "run":
                    users.append(function.name)
        self.assertEqual(users, ["start_garbage"])
        source = path.read_text(encoding="utf-8")
        self.assertNotIn("scan(", source)
        self.assertNotIn("check.garbage", source)
        self.assertNotIn("check import garbage", source)


class GarbageSeparationTest(unittest.TestCase):
    """운영자 조건: 경고만 — 복사 길·확인창·단추 상태·건강·출처·안전 점검과 분리. 글 모양 점검이 있든 없든 복사 결과가 글자까지 같다."""
    GATE_FUNCTIONS = ("gate", "copy_decision", "confirm_copy", "final_text", "blocks_for", "blocked_dialog", "gate_dialog", "text_for", "checks", "health_for", "user_health", "_inspect_now")

    def outcomes(self, controller):
        """복사 단추를 누른 결과를 모두 모은다 — 항목마다 (결정, 안내창 글·복사할 글), 막음 이유, 마지막 글, 확인한 뒤의 글. 확인 기억은 매번 지운다."""
        found = []
        for item in rules.COPY_ITEMS:
            controller.ack, controller.copy_asked = {}, None
            kind, payload = controller.copy_decision(item)
            confirmed = controller.confirm_copy(item) if kind == "confirm" else None
            found.append((item, kind, payload, controller.blocks_for(item), controller.final_text(item), confirmed))
            controller.ack, controller.copy_asked = {}, None
        return found

    def test_the_copy_path_gives_the_same_results_for_three_hundred_different_inputs_with_or_without_a_check(self):
        bodies = GS.mixed_bodies(300)
        self.assertEqual(len(set(bodies)), 300)
        controller = made(SOFTWARE)
        kinds = {"unavailable": 0, "blocked": 0, "confirm": 0, "copy": 0}
        with mock.patch.object(dg, "run", Forbidden()):
            before = []
            for body in bodies:
                controller.set_body(body)
                before.append(self.outcomes(controller))
        for number, body in enumerate(bodies):
            controller.set_body(body)
            self.assertEqual(run_garbage(controller), "started")
            if number % 3 == 0:
                controller.ignore_all_garbage()
            elif number % 3 == 1:
                card = controller.garbage_card()
                if card["groups"]:
                    controller.ignore_garbage(card["groups"][0]["rows"][0]["key"])
            with mock.patch.object(dg, "run", Forbidden()), mock.patch.object(garbage_rule, "scan", Forbidden()):
                after = self.outcomes(controller)
            self.assertEqual(after, before[number], f"입력 {number} 의 복사 결과가 글 모양 점검 때문에 달라졌다")
            for entry in after:
                kinds[entry[1]] += 1
        self.assertGreater(kinds["blocked"], 100, "막음이 여러 번 일어난 입력 모음이어야 한다")
        self.assertGreater(kinds["confirm"], 30)
        self.assertGreater(kinds["copy"], 100)

    def test_the_dialogs_never_contain_a_phrase_of_the_new_card(self):
        phrases = {T["drf_g_title"], T["drf_g_note"], T["drf_g_stale_body"], T["drf_g_busy"], *(T["drf_g_kind_" + kind] for kind in garbage_rule.KINDS)}
        controller = made(SOFTWARE)
        seen = 0
        for body in GS.mixed_bodies(60):
            controller.set_body(body)
            run_garbage(controller)
            for item in rules.GATED:
                controller.ack, controller.copy_asked = {}, None
                kind, payload = controller.copy_decision(item)
                if kind in ("confirm", "blocked"):
                    seen += 1
                    for value in all_strings(payload):
                        for phrase in phrases:
                            self.assertNotIn(phrase, value)
        self.assertGreater(seen, 30)

    def test_the_action_buttons_are_the_same_before_during_and_after_a_check_and_with_findings(self):
        controller = made(SOFTWARE)
        controller.set_body("{{a}} " + GS.ZWSP)
        plain = controller.view()["normal"]["actions"]
        held = Held()
        with mock.patch.object(dg, "run", held):
            status, job = controller.start_garbage()
            held.entered.wait(10)
            self.assertEqual(controller.view()["normal"]["actions"], plain, "검사 중에도 복사 단추는 그대로")
            held.release.set()
            job.join(10)
        run_garbage(controller)
        self.assertEqual(controller.view()["normal"]["actions"], plain)
        controller.ignore_all_garbage()
        self.assertEqual(controller.view()["normal"]["actions"], plain)

    def test_the_other_cards_are_unchanged_by_the_check(self):
        controller = made(SOFTWARE)
        controller.set_body(controller.body + "\n\n직접 써 보니 정말 좋았습니다.\n\n{{a}}")
        controller.inspect()
        before = {key: value for key, value in controller.view()["normal"]["side"].items() if key != "garbage"}
        run_garbage(controller)
        controller.ignore_all_garbage()
        self.assertEqual({key: value for key, value in controller.view()["normal"]["side"].items() if key != "garbage"}, before)
        self.assertEqual((controller.inspect_card()["tone"], controller.state), ("warning", "normal"))

    def test_a_check_does_not_change_the_text_the_marks_the_acknowledgements_or_the_unsaved_state(self):
        controller = made(SOFTWARE)
        controller.set_title(controller.title + " 고침")
        controller.set_body(GS.mixed_bodies(5)[3])
        controller.mark_copied("body")
        def state():
            return (controller.title.encode("utf-8", "surrogatepass"), controller.body.encode("utf-8", "surrogatepass"), set(controller.copied), dict(controller.ack), controller.has_unsaved(), controller.copy_asked,
                    [controller.text_for(item) for item in rules.COPY_ITEMS], controller.editor_status())

        before = state()
        controller.inspect()
        run_garbage(controller)
        controller.ignore_all_garbage()
        controller.restore_garbage()
        self.assertEqual(state(), before, "검사 전후 제목·본문 바이트와 복사할 글이 같다")

    def test_the_gate_functions_never_reach_the_new_state(self):
        tree = ast.parse((UI_DIR / "core" / "drafts_view.py").read_text(encoding="utf-8"))
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        for name in self.GATE_FUNCTIONS:
            with self.subTest(name):
                self.assertIn(name, functions)
                for node in ast.walk(functions[name]):
                    if isinstance(node, ast.Attribute):
                        self.assertNotIn(node.attr, ("garbage", "garbage_card", "start_garbage", "apply_garbage", "ignore_garbage"))
                    if isinstance(node, ast.Name):
                        self.assertNotIn(node.id, ("garbage", "dg"))

    def test_the_gate_the_claims_check_the_safety_check_and_the_services_do_not_know_the_rule(self):
        src = ROOT / "src" / "chanceblog_desktop"
        self.assertNotIn("garbage", (src / "ui" / "core" / "draft_rules.py").read_text(encoding="utf-8"))
        for folder in ("service", "topics", "render", "content", "publish", "security", "topicdb"):
            for path in sorted((src / folder).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                    for module in modules:
                        self.assertNotIn("garbage", module, f"{path.name}: {module}")
        for name in ("claims.py", "similarity.py", "profile_options.py"):
            self.assertNotIn("garbage", (src / "check" / name).read_text(encoding="utf-8"), name)
        self.assertNotIn("garbage", (src / "ui" / "core" / "drafts.py").read_text(encoding="utf-8"))

    def test_the_card_has_no_button_for_copying_or_for_the_gate_and_no_new_dialog(self):
        card = checked(S_ALL_KINDS).garbage_card()
        self.assertEqual(sorted(card["button"]), ["a11y", "enabled", "text"])
        self.assertEqual(sorted(card["ignore_all"]), ["a11y", "text", "visible"])
        for group in card["groups"]:
            self.assertEqual(sorted(group), ["chip", "kind", "more", "reason", "rows", "title"])
            for row in group["rows"]:
                self.assertEqual(sorted(row), ["a11y", "button", "key", "text"])
        self.assertFalse([name for name in dir(dg.GarbageTracker) if "copy" in name or "dialog" in name or "gate" in name])


class GarbageTextTest(unittest.TestCase):
    def test_the_phrases_the_operator_named_are_in_the_texts(self):
        self.assertEqual(T["drf_g_title"], "글 모양 점검")
        self.assertTrue(T["drf_g_stale_body"].startswith("본문이 변경됨"))
        self.assertEqual(T["drf_g_more"].format(n=3), "… 외 3건")
        self.assertEqual(T["drf_g_busy"], "검사 중…")
        self.assertIn("검사하기", T["drf_g_hint"])
        self.assertIn("복사", T["drf_g_note"])
        self.assertEqual(dg.DETAIL_MAX, 10)

    def test_every_new_text_key_starts_with_the_new_prefix_and_is_used_by_the_screen_layer_or_the_qt_files(self):
        keys = [key for key in draft_text.DRAFT_T if key.startswith("drf_g_")]
        self.assertGreater(len(keys), 60)
        sources = "".join(path.read_text(encoding="utf-8") for path in (UI_DIR / "core" / "draft_garbage.py", UI_DIR / "core" / "drafts_view.py"))
        for key in keys:
            used = key in sources or any(key.startswith(prefix) for prefix in ("drf_g_kind_", "drf_g_why_")) or key.startswith(("drf_g_n_", "drf_g_c_"))
            self.assertTrue(used, key)


# ---- 4) 소스 규칙 -----------------------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    CORE = [UI_DIR / "core" / name for name in ("draft_rules.py", "drafts.py", "drafts_view.py", "draft_text.py", "draft_garbage.py")]       # 글 모양 점검 화면 계층(N-2)을 더했다 — 더하는 방향으로만 고친다
    ALL_NEW = CORE + [UI_DIR / "drafts_adapter.py"]
    REAL_BLOGS = ("ssae" + "ssace", "shine" + "5652", "스마트" + "프라이싱", "스마트" + "초이스", "실전" + "노트", "디지털" + "찬스")

    def calls(self, path):
        return [ast.unparse(node.func) for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.Call)]

    def test_the_screen_code_has_no_file_writing_call_no_clipboard_and_no_clock(self):
        exact = {"open", "os.open", "os.write", "os.fsync", "os.replace", "os.rename", "os.remove", "os.unlink", "shutil.copy", "shutil.copyfile", "shutil.copy2", "shutil.move", "shutil.rmtree", "write_json", "sqlite3.connect"}
        attributes = {"write_text", "write_bytes", "unlink", "mkdir", "touch", "rmtree", "write_json", "save_seeds", "init_files", "fsync", "rmdir", "chmod", "open_for_write", "init_topics", "generate_candidates", "add_candidate",
                      "set_candidate_status", "move_candidate", "select_candidate", "make_plan", "save_naver_profile", "setText", "clipboard"}
        for path in self.ALL_NEW:
            for call in self.calls(path):
                with self.subTest(file=path.name, call=call):
                    self.assertNotIn(call, exact)
                    self.assertNotIn(call.rsplit(".", 1)[-1], attributes)
            source = path.read_text(encoding="utf-8")
            for forbidden in ("datetime.now", "time.time(", "QGuiApplication", "clipboard", "subprocess", "socket", "urllib.request", "http.client"):
                self.assertFalse(forbidden in source, f"{path.name}: {forbidden}")

    def test_the_core_files_never_import_the_service_layer_or_a_gui_toolkit_and_the_heavy_modules_are_loaded_late(self):
        for path in self.CORE:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    module = ("." * node.level) + (node.module or "")
                    with self.subTest(file=path.name, module=module):
                        self.assertFalse(module.lstrip(".").split(".")[0] in ("service", "publish", "render", "assist", "topicdb"), module)
                        self.assertNotIn("PySide6", module)
        for path in self.CORE:
            top_level = [node for node in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(node, ast.ImportFrom)]
            heavy = [("." * node.level) + (node.module or "") for node in top_level if (node.module or "").split(".")[0] in ("check", "security", "topics") or ("content" in (node.module or "") and "profiles" not in (node.module or ""))]
            self.assertEqual(heavy, [], f"{path.name}: 무거운 모듈은 쓰는 함수 안에서 늦게 가져온다")

    def test_the_adapter_calls_one_service_function_and_the_service_is_imported_late(self):
        path = UI_DIR / "drafts_adapter.py"
        calls = self.calls(path)
        self.assertEqual([call for call in calls if call.startswith("draft_engine.")], ["draft_engine.make_body_for_engine"])
        self.assertFalse([call for call in calls if call.startswith(("service.", "topic_service.", "legacy_service."))])
        tree = ast.parse(path.read_text(encoding="utf-8"))
        top = [("." * node.level) + (node.module or "") for node in tree.body if isinstance(node, ast.ImportFrom)]
        self.assertNotIn("..service.draft_engine", top)
        self.assertNotIn("..content", " ".join(top))

    def test_no_english_secret_word_and_no_real_blog_name_in_the_new_files(self):
        words = re.compile(r"(?i)(?<![A-Za-z0-9_])(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?(?![A-Za-z0-9_])")
        for path in self.ALL_NEW:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(words.search(node.value), (path.name, node.value[:40]))
            source = path.read_text(encoding="utf-8")
            for name in self.REAL_BLOGS:
                self.assertFalse(name in source, path.name)

    def test_the_new_text_file_is_merged_into_the_shared_table_after_the_candidate_texts(self):
        source = (UI_DIR / "core" / "text.py").read_text(encoding="utf-8")
        self.assertIn("T.update(DRAFT_T)", source)
        self.assertLess(source.index("T.update(CAND_T)"), source.index("T.update(DRAFT_T)"))


if __name__ == "__main__":
    unittest.main()
