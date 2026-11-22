"""규칙 기반 초안의 '공식 자료' 표기(F117)와 어색한 문장(F116) 고치기(결정 D-549에서 D-552)를 못박는 시험 — 순수 함수라 네트워크·파일·PySide6 없이 돈다.

지키는 것:
  1) **바뀐 문장 표**(`CHANGES`·`UI_CHANGES`): 고친 문장 스물한 곳과 화면 문구 셋의 옛 글이 지금 표에 한 군데도 없고 새 글이 정확히 한 번 있다(처음 고쳤다가 다시 바꾼 글 `SUPERSEDED` 도 어디에도 없다). 새 글은 숫자·물결표·주소·평가 단정·1인칭 체험 없이
     `check/claims.py` 검사와 입구 검사(주제 엔진 `check_text` 의 안전 단계·사용자 글칸 `photo_manifest.check_text`)를 모든 분야·두 말투로 통과하고, 옛 글과 **공백 뺀 글자 수·공백 수가 같다**(해요체·합니다체 모두) —
     본문 분량 맞추기(`draft_body._fit`)가 고치지 않은 선택 문장을 켜고 끄지 않게 하려는 것이다.
  2) **공식 자료 표기**: 확인할 곳(W) 목록에는 판매 페이지·예약 페이지·지도 앱·전문 업체처럼 공식이 아닌 곳이 있다 — W 자리가 든 문장은 그곳을 '공식 자료'·'공식 안내'라고 부르지 않고 '기준' 으로 삼으라고도 하지 않는다.
     '공식' 은 곳이 아니라 내용(공식 순서)에만 붙는다. 어떤 분야·어느 항목이 들어가도 마찬가지다.
  3) **조사**: 장소 글의 한 줄 요약은 '…에 가기 전에는' 이고, 확인 권장의 `「낱말」 이/가` 는 받침에 맞으며, 화면 문구는 값의 받침을 읽지 않는 고정 낱말로 받는다.
  4) **낱말 반복·연결**: 자주 놓치는 부분을 '놓치는 것' 으로 돌려 말하지 않고, 본문에 들어가는 가격 마무리 문장이 독자에게 뜻이 통하며, 문제 해결형 주의사항에 작업·전이 되풀이되지 않는다.
  5) **구조는 그대로**: 사진을 넣어도 사진 줄 말고는 사진 없는 글과 같은 문단이다(`{{사진 N}}`·복사 변환은 이 묶음이 건드리지 않았다).
옛 글을 되돌리거나 새 글을 틀리게 바꾸면 이 시험이 빨개진다(변이 시험 — 보고서 표).
"""
import functools
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.check import claims  # noqa: E402
from chanceblog_desktop.content import body_bank as bb  # noqa: E402
from chanceblog_desktop.content import body_blocks as blk  # noqa: E402
from chanceblog_desktop.content import body_lang as bl  # noqa: E402
from chanceblog_desktop.content import body_library  # noqa: E402
from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.content import draft_body as db  # noqa: E402
from chanceblog_desktop.content import draft_plan as dp  # noqa: E402
from chanceblog_desktop.content import photo_flow as pf  # noqa: E402
from chanceblog_desktop.content.draft_options import DraftOptions  # noqa: E402
from chanceblog_desktop.topics import safety  # noqa: E402
from chanceblog_desktop.ui.core import draft_rules as rules  # noqa: E402
from chanceblog_desktop.ui.core import draft_text  # noqa: E402
from test_content_body_library import BANNED, FIRST_PERSON, KEYWORDS, TYPES, all_templates, flat_items, sample_values  # noqa: E402
from test_content_draft_body import CANDIDATES, INFO, PLACE, TODAY, TROUBLE, body_of, make, profile  # noqa: E402
from test_content_photo_flow import photo  # noqa: E402

T = draft_text.DRAFT_T
W_SLOTS = {"W", "w1", "w2", "w3"}
# 확인할 곳(W) 목록에서 공식이 아닌 곳 — 이름이 곳의 종류를 그대로 말한다(시험이 빈 껍데기가 아니도록 목록에 아직 있는지도 본다)
NON_OFFICIAL_W = ("판매 페이지의 상세 안내", "예약 페이지의 안내", "지도 앱의 장소 정보", "전문 업체의 안내")
# (이름, 종류, 옛 글, 새 글) — 종류: template(문장 틀)·item(분야 목록 항목)·constant(`draft_body.PRICE_TAIL`)
CHANGES = (
    ("F117-1", "template", "{c3:은/는} {w1} 같은 공식 자료에서 확인하는 것이 기본이에요.", "{c3:은/는} {w1} 같은 곳에서 꼼꼼히 확인하는 것이 기본이에요."),
    ("F117-2", "template", "다른 글에 적힌 내용과 다르면 {w2:을/를} 기준으로 삼아요.", "다른 글에 적힌 내용과 다르면 {w2:을/를} 정확히 확인해요."),
    ("F117-3", "template", "{w1} 같은 공식 자료에서 확인할 수 있는 항목부터 보면 시간이 줄어요.", "{w1}에서 곧바로 확인할 수 있는 항목을 우선 보면 시간이 많이 줄어요."),
    ("F117-4", "template", "조건이 적혀 있지 않으면 {w1} 같은 공식 자료에서 확인해요.", "조건이 적혀 있지 않으면 {w1} 같은 곳에서 꼼꼼히 확인해요."),
    ("F117-5", "template", "조건이 적혀 있지 않으면 {w1} 같은 공식 자료에서 확인하세요.", "표에 조건이 빠져 있다면 {w1} 같은 곳에서 곧바로 확인하세요."),
    ("F117-6", "template", "{w1} 같은 공식 자료에 적힌 순서가 있다면 그것을 먼저 따라요.", "{w1} 같은 곳에 공식 순서가 적혀 있다면 그것을 먼저 따라가요."),
    ("F117-7", "template", "조건과 호환 여부는 {w1} 같은 공식 자료에 나와 있어요.", "조건과 호환 여부는 {w1} 같은 곳에서 알아볼 수 있어요."),
    ("F117-8", "template", "운영 시간과 휴무는 {w1} 같은 공식 자료에서 확인해요.", "운영 시간과 휴무는 {w1} 같은 곳에서 정확히 확인해요."),
    ("F117-9", "template", "글을 읽는 때의 공식 안내를 {w1} 같은 곳에서 한 번 더 확인하세요.", "혹시 달라진 점이 없는지 {w1} 같은 곳에서 한 번 더 확인해 보세요."),
    ("F117-10", "template", "{W:을/를} 기준으로 삼으면 돼요.", "{W}에서 한번 살펴보면 돼요."),
    ("F117-11", "template", "기준으로 삼은 곳이 한 곳뿐이라면 가능하면 두 곳에서 같은 내용인지 대조해요.", "확인했던 곳이 한 곳뿐이라면 가능하면 두 곳에서 같은 내용인지 서로 대조해요."),
    ("F116-1", "template", "{kw:을/를} 가기 전에는 위치, 이용 방법, 운영 정보, 예약 방식을 확인해요.", "{kw}에 가기 전에는 위치, 이용 방법, 운영 정보, 예약 방식을 확인해요."),
    ("F116-2", "template", "{b2:은/는} 어떤 작업을 하든 시작하기 전에 먼저 챙겨 두세요.", "{b2:은/는} 어떤 방법을 쓰든 빠뜨리지 말고 먼저 챙겨 두세요."),
    ("F116-3", "template", "어디서부터 들어야 할지 막막해지기 쉬운 주제예요.", "어디부터 시작해야 할지 막막해지기 쉬운 주제예요."),
    ("F116-4", "template", "{c1:은/는} 처한 환경에 따라, {c2:은/는} 하는 방식에 따라 중요도가 달라져요.", "{c1:은/는} 처한 환경에 따라, {c2:은/는} 쓰는 용도에 따라 중요도가 달라져요."),
    ("F116-5", "template", "추측으로 채운 기능 목록은 선택을 흐려요.", "추측으로 채운 기능 목록은 판단을 흐려요."),
    ("F116-6", "template", "예약과 취소 규정은 예약을 정하기 전에 읽어 두는 것이 안전해요.", "예약과 취소 규정은 예약을 잡기 전에는 읽어 두는 것이 안전해요."),
    ("F116-7", "template", "글을 읽는 때의 정보를 {w1} 같은 곳에서 확인하세요.", "달라진 게 없는지 {w1} 같은 곳에서 한번 확인하세요."),
    ("F116-8a", "item", "케이스 크기와 전원 용량을 놓치는 것", "케이스 크기와 전원 용량을 모르는 것"),
    ("F116-8b", "item", "주차나 대중교통 정보를 놓치는 것", "주차나 대중교통 정보를 모르는 것"),
    ("F116-9", "constant", "값은 바뀔 수 있으니 올리는 날 한 번 더 확인해 주세요.", "값은 바뀔 수 있으니 이용 전에 한 번 더 확인해 주세요."),
)
# 처음 고쳤다가 독립 검증 뒤 다시 바꾼 글(F116-4 의 '세운 목적' — 목록 항목 '사용 목적…' 과 같은 낱말을 되풀이해 '쓰는 용도' 로 바꿨다) — 문장 틀·목록·만든 글 어디에도 되살아나면 안 된다
SUPERSEDED = ("세운 목적",)
# 화면 문구(`ui/core/draft_text.py`) — (열쇠, 옛 조각, 새 조각)
UI_CHANGES = (
    ("drf_chk_replaced", "‘{new}’ 으로 바꿔 구성했어요", "‘{new}’ 형태로 바꿔 구성했어요"),
    ("drf_delete_body", "‘{title}’ 을 지워요.", "‘{title}’ 초안을 지워요."),
    ("drf_delete_unreadable_body", "읽을 수 없는 초안 {number} 을 지워요.", "읽을 수 없는 초안({number})을 지워요."),
)
# 값 바로 뒤에 받침으로 갈리는 조사를 박아 둔 화면 문구 가운데 값이 늘 같은 고정 이름으로 끝나서 맞는 것(전수 확인 — `draft_garbage` 의 위치 문구는 '…줄'·'…글자' 로만 끝난다)
SAFE_FIXED_PARTICLES = {"drf_g_pair": "{a} 는 늘 '…줄' 로 끝난다(과)", "drf_g_pair_col": "{where} 는 늘 '…글자' 로 끝난다(와)"}
PARTICLE_AFTER_SLOT = re.compile("[}]([’”']?)( ?)(으로|로|은|는|이|가|을|를|과|와|이나|나|이라|라|이에요|예요)(?![가-힣])")
SPLIT = re.compile("(?<=[.?!]) ")
SLOT = re.compile("[{][A-Za-z0-9_]+(?::([^{}/:]+)/[^{}/:]+)?[}]")


def live_templates():
    """지금 표의 모든 문장 틀(글 유형 5종의 소제목 틀·도입·주의사항·마무리·민감 안내·한 줄 요약) — 같은 틀은 한 번만."""
    return [template for _name, template in all_templates()]


def live_items():
    return [text for banks in bb.BANKS.values() for text in flat_items(banks)]


def hapsyo(text):
    return bl.to_hapsyo(text)


def counted(template):
    """틀을 같은 가짜 값('가나' + 조사 쌍의 앞 조사)으로 채운 글의 (공백 뺀 글자 수, 공백 수)."""
    text = SLOT.sub(lambda found: "가나" + (found.group(1) or ""), template)
    return len("".join(text.split())), text.count(" ")


def fills(template):
    """그 틀을 모든 분야·키워드·목록 시작 자리로 채운 문장들 — 값이 모자라 못 채우는 조합은 건너뛴다."""
    found = []
    for domain in bb.DOMAINS:
        for offset in range(8):
            values = sample_values(domain, KEYWORDS[offset % len(KEYWORDS)], offset)
            if all(values.get(slot) for slot in bl.slots_of(template)):
                found.append(bl.tidy(bl.collapse(bl.fill(template, values))))
    return found


class ChangeTableTest(unittest.TestCase):
    def test_the_table_has_twenty_one_distinct_changes(self):
        self.assertEqual(len(CHANGES), 21)
        self.assertEqual(len({name for name, *_rest in CHANGES}), 21)
        for name, _kind, old, new in CHANGES:
            with self.subTest(change=name):
                self.assertNotEqual(old, new)

    def test_every_old_text_is_gone_and_every_new_text_is_in_the_live_tables_exactly_once(self):
        templates, items, tail = live_templates(), live_items(), [db.PRICE_TAIL]
        for name, kind, old, new in CHANGES:
            pool = {"template": templates, "item": items, "constant": tail}[kind]
            with self.subTest(change=name):
                self.assertEqual(pool.count(old), 0, "옛 글이 아직 있다")
                self.assertEqual(pool.count(new), 1, "새 글이 정확히 한 번 있어야 한다")
        for text in SUPERSEDED:
            with self.subTest(superseded=text):
                self.assertEqual([one for one in (*templates, *items, *tail) if text in one], [], "다시 바꾼 글이 되살아났다")

    def test_a_changed_text_keeps_the_count_of_characters_and_spaces_in_both_speech_styles(self):
        """`draft_body._fit` 은 공백 뺀 글자 수로 선택 문장을 켜고 끈다 — 길이가 달라지면 고치지 않은 선택 문장이 켜지거나 꺼져 '바뀐 곳이 의도한 문장뿐' 이 깨진다(결정 D-551)."""
        for name, _kind, old, new in CHANGES:
            with self.subTest(change=name):
                self.assertEqual(counted(old), counted(new), "해요체 길이")
                self.assertEqual(counted(hapsyo(old)), counted(hapsyo(new)), "합니다체 길이")

    def test_the_new_texts_have_no_digit_tilde_address_backslash_first_person_or_banned_word(self):
        for name, _kind, _old, new in CHANGES:
            fixed = bl.skeleton(new)
            with self.subTest(change=name):
                self.assertIsNone(re.search("[0-9]", fixed))
                self.assertNotIn("~", new)
                self.assertNotIn("http", new.casefold())
                self.assertNotIn(chr(92), new)
                self.assertIsNone(FIRST_PERSON.search(fixed))
                for word in BANNED:
                    self.assertNotIn(word, fixed, word)

    def test_the_new_templates_pass_the_claim_check_for_every_domain_and_both_speech_styles(self):
        total = 0
        for name, kind, _old, new in CHANGES:
            if kind != "template":
                continue
            for sentence in fills(new):
                for text in (sentence, bl.tidy(bl.in_style(sentence, bl.STYLE_HAPSYO))):
                    total += 1
                    with self.subTest(change=name, text=text):
                        self.assertEqual(claims.find_claims([text]), ())
                        self.assertEqual(claims.find_violations([text]), ())
        self.assertGreater(total, 600)
        for name, kind, _old, new in CHANGES:
            if kind in ("item", "constant"):
                with self.subTest(change=name):
                    self.assertEqual(claims.find_claims([new]), ())
                    self.assertEqual(claims.find_claims([new + "."]), ())

    def test_every_new_template_is_one_sentence_and_every_ending_converts_to_the_formal_style(self):
        for name, kind, _old, new in CHANGES:
            if kind != "template":
                continue
            with self.subTest(change=name):
                self.assertEqual(len(claims.split_sentences(new)), 1)
                self.assertTrue(new.endswith((".", "?")))
                converted = bl.split_ending(hapsyo(bl.fill(new, {slot: "표본" for slot in bl.slots_of(new)})))[0]
                if converted.endswith("요"):
                    self.assertTrue(converted.endswith(("세요", "까요")), converted[-6:])

    def test_the_new_sentences_never_raise_the_safety_stage_of_the_sentence_they_replace(self):
        """주제 엔진의 입구 검사(`topics.safety.check_text`)는 복사 관문(`ui/core/drafts.review_health`)이 쓰는 판정기다 — 같은 값으로 채운 옛·새 문장을 견줘 단계가 오르지 않는다."""
        order = safety.HEALTH_STAGES
        checked = 0
        for name, kind, old, new in CHANGES:
            if kind == "template":
                pairs = list(zip(fills(old), fills(new)))
                self.assertEqual(len(fills(old)), len(fills(new)), name)
            else:
                pairs = [(old, new)]
            for before, after in pairs:
                checked += 1
                with self.subTest(change=name, before=before):
                    self.assertLessEqual(order.index(safety.check_text([after]).stage), order.index(safety.check_text([before]).stage))
        self.assertGreater(checked, 600)

    def test_the_new_sentences_pass_the_entrance_check_the_users_own_texts_pass(self):
        """사용자가 적는 글칸의 입구 검사(`photo_manifest.check_text` — 보이지 않는 글자·마크업·키 모양·개인 번호·결과를 약속하는 표현)를 새 문장도 그대로 통과하고 글이 바뀌지 않는다."""
        checked = 0
        for name, kind, _old, new in CHANGES:
            texts = [new]
            if kind == "template":
                texts = [*fills(new), *(bl.tidy(bl.in_style(sentence, bl.STYLE_HAPSYO)) for sentence in fills(new))]
            for text in texts:
                checked += 1
                with self.subTest(change=name, text=text):
                    clean, reason = pm.check_text("user_note", text)
                    self.assertIsNone(reason)
                    self.assertEqual(clean, text)
        self.assertGreater(checked, 600)

    def test_the_screen_texts_changed_as_listed(self):
        for key, old, new in UI_CHANGES:
            with self.subTest(key=key):
                self.assertNotIn(old, T[key])
                self.assertEqual(T[key].count(new), 1)


class OfficialLabelTest(unittest.TestCase):
    """F117 — W(확인할 곳) 목록은 판매 페이지·예약 페이지·지도 앱·전문 업체처럼 공식이 아닌 곳을 담는다. 문장이 그 목록을 '공식 자료' 라고 부르면 틀린 이름표다."""

    def w_templates(self):
        found = [template for template in live_templates() if set(bl.slots_of(template)) & W_SLOTS]
        self.assertGreaterEqual(len(found), 14)                       # 빈 껍데기 방지 — 지금 W 자리가 든 틀이 열네 개 넘는다
        return found

    def test_the_bank_still_holds_the_non_official_places_so_this_guard_is_not_empty(self):
        everything = {text for banks in bb.BANKS.values() for text in banks["W"]}
        for name in NON_OFFICIAL_W:
            with self.subTest(place=name):
                self.assertIn(name, everything)

    def test_no_template_with_a_where_slot_calls_it_official_or_makes_it_the_standard(self):
        for template in self.w_templates():
            with self.subTest(template=template):
                self.assertNotIn("공식 자료", template)
                self.assertNotIn("공식 안내", template)
                self.assertNotIn("같은 공식", template)
                self.assertNotIn("기준으로 삼", template)

    def test_a_filled_sentence_never_says_official_except_for_the_official_order_and_the_items_own_names(self):
        """어떤 분야·어느 항목이 들어가도: 목록 항목의 이름(제조사 공식 누리집·공식 안내에 적힌 내용 …)과 '공식 순서' 를 빼면 문장에 '공식' 이 없다 — 곳이 공식인지 문장이 정하지 않는다."""
        names = sorted(set(live_items()), key=lambda text: (-len(text), text))                 # 목록의 모든 항목 이름(확인할 기준 '공식 안내에 적힌 내용' 같은 것도 항목이다)
        checked = 0
        for template in self.w_templates():
            for sentence in fills(template):
                rest = sentence.replace("공식 순서", "")
                for name in names:
                    rest = rest.replace(name, "")
                checked += 1
                with self.subTest(template=template, sentence=sentence):
                    self.assertNotIn("공식", rest)
                    self.assertNotIn("공식 자료", sentence)
                    self.assertNotIn("같은 공식", sentence)
        self.assertGreater(checked, 500)

    def test_the_official_order_sentence_names_the_order_official_not_the_place(self):
        found = [template for template in self.w_templates() if "공식 순서" in template]
        self.assertEqual(found, ["{w1} 같은 곳에 공식 순서가 적혀 있다면 그것을 먼저 따라가요."])
        for sentence in fills(found[0]):
            self.assertRegex(sentence, "같은 곳에 공식 순서가 적혀 있다면")

    def test_the_official_info_section_of_a_place_post_lists_the_places_without_making_one_the_standard(self):
        paragraph = body_library.LIBRARY[PLACE]["official"][0]
        self.assertEqual(paragraph[1], "{W}에서 한번 살펴보면 돼요.")
        self.assertNotIn("기준으로 삼", " ".join(paragraph))
        for body in (body_of(make(*CANDIDATES[7])), body_of(make(*CANDIDATES[8]), blog="naver_b")):
            official = next(block for block in body.blocks if block.key == "official")
            text = " ".join(official.paragraphs)
            self.assertNotIn("기준으로 삼", text)
            self.assertIn("에서 한번 살펴보면 돼요.", text)


class ParticleTest(unittest.TestCase):
    PLACE_KEYWORDS = ("제주 숙소", "동네 도서관", "서울 맛집", "미술관", "부산 호텔", "캠핑장", "공원", "박물관", "온천", "펜션", "해수욕장", "스키장", "전망대", "게스트하우스", "리조트", "글램핑",
                      "도서관", "식당", "카페", "여행지", "근교 산책", "야경 명소", "축제", "체크인 안내", "당일치기 코스")

    def test_the_place_summary_goes_with_e_and_never_with_eul_or_reul(self):
        seen_first = 0
        for keyword in self.PLACE_KEYWORDS:
            for blog in ("naver_a", "naver_b"):
                body = body_of(make(f"{keyword} 안내", keyword, (), PLACE), None, None, blog)
                with self.subTest(keyword=keyword, blog=blog):
                    self.assertIsNone(re.search("[을를] 가기 전에", body.summary + body.body_text), body.summary)
                seen_first += "에 가기 전에는 위치, 이용 방법, 운영 정보, 예약 방식을 확인해요." in body.summary
        self.assertGreater(seen_first, 5)                                       # 고친 틀이 실제로 뽑힌 조합이 있다(빈 껍데기 방지)
        self.assertEqual([text for text in blk.SUMMARY[PLACE] if "가기 전에는" in text], ["{kw}에 가기 전에는 위치, 이용 방법, 운영 정보, 예약 방식을 확인해요."])

    def plan_lines(self, prof=None, options=None, keyword="난방비 절약"):
        plan = dp.build_plan(make(keyword, keyword, (), INFO), prof, options, today=TODAY, blog="naver_a")
        return [line for line in plan.checks if "「" in line]

    def test_the_plan_check_lines_pick_i_or_ga_by_the_final_sound_of_the_quoted_word(self):
        cases = (
            (dict(prof=profile("naver_a", excluded_topics=("난방",))), "「난방」 이 후보의 핵심 키워드·주제에 있습니다"),
            (dict(prof=profile("naver_a", excluded_topics=("보일러",)), keyword="보일러 점검"), "「보일러」 가 후보의 핵심 키워드·주제에 있습니다"),
            (dict(options=DraftOptions(exclude=("광고",), message="광고가 없습니다")), "「광고」 가 입력하신 ‘직접 전달하고 싶은 내용’ 에 들어 있습니다"),
            (dict(options=DraftOptions(exclude=("난방",), experience="난방 이야기")), "「난방」 이 입력하신 ‘실제 사용 경험’ 에 들어 있습니다"),
            (dict(prof=profile("naver_a", forbidden_phrases=("절약",))), "「절약」 이 후보의 핵심 키워드에 있습니다"),
            (dict(prof=profile("naver_a", forbidden_phrases=("보일러",)), keyword="보일러 점검"), "「보일러」 가 후보의 주제에 있습니다"),
        )
        for kwargs, expected in cases:
            lines = self.plan_lines(**kwargs)
            with self.subTest(expected=expected):
                self.assertTrue(any(expected in line for line in lines), lines)
                self.assertFalse(any("이(가)" in line for line in lines), lines)

    def test_the_plan_particle_reads_hangul_and_the_names_of_latin_letters(self):
        """`draft_plan.particle` 은 한글 받침과 영문 글자 이름(디디알 — ㄹ 받침, 지피유 — 받침 없음)을 읽고 읽은 대로 이/가 를 고른다."""
        self.assertEqual(dp.particle("난방", "이", "가"), "이")
        self.assertEqual(dp.particle("보일러", "이", "가"), "가")
        self.assertEqual(dp.particle("DDR", "이", "가"), "이")          # 디디알 — ㄹ 받침
        self.assertEqual(dp.particle("GPU", "이", "가"), "가")          # 지피유 — 받침 없음

    def test_the_screen_texts_do_not_pick_a_particle_by_the_ending_of_a_value(self):
        found = set()
        for key, text in T.items():
            if isinstance(text, str) and PARTICLE_AFTER_SLOT.search(text):
                found.add(key)
        self.assertEqual(found, set(SAFE_FIXED_PARTICLES), sorted(found - set(SAFE_FIXED_PARTICLES)))

    def test_the_replaced_format_line_reads_right_for_every_label_a_replacement_can_have(self):
        for old, new in (("방문 후기", "위치·이용 정보와 방문 전 확인사항"), ("제품 체험 후기", "공개된 제품 정보와 구매 전 확인사항"), ("직접 사용 후기", "기능과 선택 기준 정리"), ("경험형 후기", "정보형 안내 글"),
                         ("경험형 후기", "제품·서비스 소개형 안내 글")):
            line = rules.derived_lines(types.SimpleNamespace(domain="appliance", replaced=(old, new)))[0]
            with self.subTest(new=new):
                self.assertIn(f"‘{new}’ 형태로 바꿔 구성했어요", line)
                self.assertNotIn("’ 으로", line)

    def test_the_delete_confirmations_do_not_depend_on_how_the_title_or_number_ends(self):
        for title in ("노트북 정리", "집 보일러", "독서 습관 만들기", "GPU"):
            body = T["drf_delete_body"].format(title=title)
            with self.subTest(title=title):
                self.assertTrue(body.startswith(f"‘{title}’ 초안을 지워요."), body)
                self.assertNotIn("’ 을", body)
        self.assertTrue(T["drf_delete_unreadable_body"].format(number="dd-bbbbbbbb").startswith("읽을 수 없는 초안(dd-bbbbbbbb)을 지워요."))


@functools.lru_cache(maxsize=1)
def all_bodies():
    """키워드 열여섯 x 글 유형 5 x 블로그 2 = 160편(한 번만 만든다) — (키워드, 글 유형, 블로그, 초안)."""
    found = []
    for keyword in KEYWORDS + ("노트북 전원", "제주 숙소", "동네 도서관", "곰팡이 제거", "로봇청소기", "ChatGPT 요금제"):
        for post_type in TYPES:
            for blog in ("naver_a", "naver_b"):
                found.append((keyword, post_type, blog, body_of(make(f"{keyword} 정리", keyword, ("보조 낱말",), post_type), None, None, blog)))
    return tuple(found)


class WordingTest(unittest.TestCase):
    def bodies(self, post_types=TYPES):
        return [item for item in all_bodies() if item[1] in post_types]

    def test_no_sentence_turns_the_same_mistake_around_as_what_people_often_miss(self):
        """'자주 놓치는 부분은 …을 놓치는 것이에요' · '…놓치는 것은 선택에서 자주 놓치는 부분이에요' — 같은 말을 돌려 말하는 문장이 없다."""
        count = 0
        for keyword, post_type, blog, body in self.bodies():
            for sentence in SPLIT.split(body.body_text.replace("\n", " ")):
                count += 1
                with self.subTest(keyword=keyword, type=post_type, blog=blog, sentence=sentence):
                    self.assertFalse("놓치는 것" in sentence and "놓치는 부분" in sentence, sentence)
        self.assertGreater(count, 8000)

    def test_no_template_filled_from_the_lists_turns_the_same_mistake_around(self):
        """모든 문장 틀 x 분야 x 목록 항목 자리(전수) — '자주 놓치는 부분은 …놓치는 것이에요' 꼴이 어느 조합에도 없다."""
        count = 0
        for template in live_templates():
            for sentence in fills(template):
                count += 1
                self.assertFalse("놓치는 것" in sentence and "놓치는 부분" in sentence, sentence)
        self.assertGreater(count, 9000)

    def test_a_post_with_a_price_ends_that_paragraph_with_a_sentence_a_reader_can_follow(self):
        options = DraftOptions(price_date=("2026-11-01 기준 가격 1만원",))
        for post_type in TYPES:
            body = body_of(make("노트북 정리", "노트북", (), post_type), None, options)
            price = next(text for block in body.blocks for text in block.paragraphs if text.endswith(db.PRICE_TAIL))
            with self.subTest(type=post_type):
                self.assertTrue(price.startswith(db.PRICE_LEAD))
                self.assertNotIn("올리는 날", body.body_text)
                self.assertEqual(db.PRICE_TAIL, "값은 바뀔 수 있으니 이용 전에 한 번 더 확인해 주세요.")


    def test_the_writers_own_check_line_still_talks_to_the_writer(self):
        body = body_of(make("노트북 정리", "노트북", (), INFO))
        self.assertTrue(any("올리는 날 한 번 더 맞는지 살펴 주세요" in line for line in body.checks))

    def test_a_trouble_post_does_not_repeat_work_and_before_inside_one_caution_sentence(self):
        for keyword, post_type, blog, body in self.bodies((TROUBLE,)):
            cautions = next(block for block in body.blocks if block.kind == db.CAUTIONS)
            sentences = [one for one in SPLIT.split(" ".join(cautions.paragraphs)) if "먼저 챙겨 두세요" in one]
            with self.subTest(keyword=keyword, blog=blog):
                self.assertEqual(len(sentences), 1, sentences)
                self.assertFalse("작업 전" in sentences[0] and "작업을" in sentences[0], sentences[0])
                self.assertNotIn("시작하기 전에 먼저", sentences[0])

    def test_the_old_awkward_phrases_are_in_no_generated_body(self):
        gone = ("어디서부터 들어야", "하는 방식에 따라", "선택을 흐려요", "예약을 정하기 전에", "글을 읽는 때의", "같은 공식 자료", "공식 자료에서 확인하는 것이 기본", "를 가기 전에는", *SUPERSEDED)
        for keyword, post_type, blog, body in self.bodies():
            text = body.summary + " " + body.body_text
            for phrase in gone:
                with self.subTest(keyword=keyword, type=post_type, blog=blog, phrase=phrase):
                    self.assertNotIn(phrase, text)


class StructureUntouchedTest(unittest.TestCase):
    def test_photos_only_add_their_own_lines_and_leave_every_other_paragraph_as_it_was(self):
        """사진 줄(`{{사진 N}}`)·복사 변환·자리 넣기는 이 묶음이 건드리지 않았다 — 사진을 넣어도 그 줄 말고는 사진 없는 글과 같은 문단이다."""
        photos = (photo(1), photo(2, kind="top"), photo(3, kind="after_paragraph", nth=1))
        for number in (0, 3, 6, 7, 11):
            row = CANDIDATES[number]
            plain = body_of(make(*row))
            with_photos = db.build_body(make(*row), None, None, today=TODAY, blog="naver_a", photos=photos)
            lines = [text for block in with_photos.blocks for text in block.paragraphs]
            kept = [text for text in lines if "{{사진" not in text]
            with self.subTest(candidate=row[1]):
                self.assertEqual(kept, [text for block in plain.blocks for text in block.paragraphs])
                self.assertEqual(sorted(text for text in lines if "{{사진" in text), ["{{사진 1}}", "{{사진 2}}", "{{사진 3}}"])
                self.assertEqual(pf.to_copy_text("{{사진 2}}"), "[이미지 2]")
                self.assertEqual(with_photos.title_text, plain.title_text)


if __name__ == "__main__":
    unittest.main()
