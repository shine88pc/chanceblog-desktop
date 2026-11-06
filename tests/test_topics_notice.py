"""사용자 메시지 `Notice`(`topics/notice.py`) 시험 — P2b 보완 N1~N8(D-53).

지키는 것:
  N1) 카탈로그 30개(안전 10·브랜드 3·진단 15·결과 2 — 전략 맞춤 1차 D-102 가 안전 알림 `ECONOMIC_CONFLICT` 하나를 더해 29 → 30)의 코드·수준·제목·설명·행동이 정해진 값이고 후보의 선정 이유 규칙을 통과한다.
  N2) 요청서 §8 의 세 표시 예(주제 구체화 필요·건강 정보 확인 필요·경제적 이해관계 확인 필요)가 글자 그대로 나온다.
  N3) 렌더(카드·글머리표·한 줄)는 파이썬 목록 꼴이 아니다. N4) 변환기(보고서·진단 행·한 번 돌린 결과·브랜드·보류). N5) **전수 점검** — 사용자에게 보일 수 있는 문장 어디에도 목록 꼴·내부 식별자가 없다.
  N6) 입력 글(`['a', 'b']`·`health_check`·`<b>`)은 `‘ ’` 밖으로 알림 글에 나오지 않는다. N7) 수준 매핑·정렬·`to_dict` 키 여섯 개. N8) 브랜드 알림 셋.
카탈로그의 문장은 초기값 — 전략 원문 확인 전이다. 네트워크·파일·실제 시계·난수 없이 돈다.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_corpus as corpus  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import brand as br  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402
from chanceblog_desktop.topics import notice as nt  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402

A = ts.PROFILES["naver_a"]
B = ts.PROFILES["naver_b"]
CODES = ("HEALTH_TOPIC", "HEALTH_EFFECT", "HEALTH_CLAIM", "HEALTH_STOP", "EXPERIENCE_CLAIM", "ECONOMIC_CHECK", "ECONOMIC_CONFLICT", "ECONOMIC_CONFIRMED", "COLLAB_POSSIBLE", "RESULT_PROMISE", "BRAND_ONLY", "BRAND_UNFEASIBLE",
         "BRAND_SPECIFIED", "DROP_COMBINATION", "DROP_EXCLUDED_KEYWORD", "DROP_TOO_LONG", "DROP_LANGUAGE", "DROP_NO_SEED", "DROP_NOT_DUE", "DROP_NO_KEYWORD", "DROP_INVALID", "DROP_RESULT_PROMISE",
         "DROP_ALREADY_EXISTS", "DROP_OVER_TARGET", "DROP_PER_SEED_KEEP", "DROP_OTHER_CHANNEL", "DROP_SOURCES", "DROP_UNSTABLE", "SHORTAGE", "HOLD_BAND")
LEVELS = {"HEALTH_TOPIC": "WARNING", "HEALTH_EFFECT": "WARNING", "HEALTH_CLAIM": "WARNING", "HEALTH_STOP": "ERROR", "EXPERIENCE_CLAIM": "WARNING", "ECONOMIC_CHECK": "WARNING", "ECONOMIC_CONFLICT": "WARNING", "ECONOMIC_CONFIRMED": "WARNING",
          "COLLAB_POSSIBLE": "INFO", "RESULT_PROMISE": "ERROR", "BRAND_ONLY": "WARNING", "BRAND_UNFEASIBLE": "WARNING", "BRAND_SPECIFIED": "INFO", "DROP_COMBINATION": "INFO", "DROP_EXCLUDED_KEYWORD": "INFO",
          "DROP_TOO_LONG": "INFO", "DROP_LANGUAGE": "INFO", "DROP_NO_SEED": "WARNING", "DROP_NOT_DUE": "INFO", "DROP_NO_KEYWORD": "WARNING", "DROP_INVALID": "WARNING", "DROP_RESULT_PROMISE": "ERROR",
          "DROP_ALREADY_EXISTS": "INFO", "DROP_OVER_TARGET": "INFO", "DROP_PER_SEED_KEEP": "INFO", "DROP_OTHER_CHANNEL": "INFO", "DROP_SOURCES": "WARNING", "DROP_UNSTABLE": "INFO", "SHORTAGE": "INFO",
          "HOLD_BAND": "INFO"}
TITLES = {"HEALTH_TOPIC": "건강 정보 확인 필요", "HEALTH_EFFECT": "건강 정보 확인 필요", "HEALTH_CLAIM": "건강 정보 확인 필요", "HEALTH_STOP": "의료·효과 단정 위험", "EXPERIENCE_CLAIM": "직접 겪은 경험 확인 필요",
          "ECONOMIC_CHECK": "경제적 이해관계 확인 필요", "ECONOMIC_CONFLICT": "경제적 이해관계 확인 필요", "ECONOMIC_CONFIRMED": "경제적 이해관계 표시 필요", "COLLAB_POSSIBLE": "협업 가능성 참고", "RESULT_PROMISE": "결과 약속 표현",
          "BRAND_ONLY": "주제 구체화 필요", "BRAND_UNFEASIBLE": "작성 기반 부족", "BRAND_SPECIFIED": "주제 구체화 완료", "SHORTAGE": "목표에 모자란 경로", "HOLD_BAND": "보류 구간"}


def seed(**changes):
    values = dict(seed_id="s1", major="가전", minor="소형가전", keyword="예시 로봇청소기", seed_type="general", scope="common", priority=False, excluded_keywords=(), sponsor_tag=None, state="active",
                  registered_on="2026-05-01", last_selected_on=None, active_since=None)
    values.update(changes)
    return sd.Seed(**values)


def run(profile, seeds, **options):
    return gn.generate(profile, seeds, options.pop("calendar", []), options.pop("history", ()), "2026-11-10", **options)


class CatalogTest(unittest.TestCase):                                                                          # N1
    def test_the_catalog_has_the_thirty_codes_in_the_documented_order(self):                                   # 의도적 갱신(전략 맞춤 1차, D-102): 스물아홉 → 서른 — `ECONOMIC_CONFLICT` 가 `ECONOMIC_CHECK` 바로 뒤에 들어갔다
        self.assertEqual(nt.CODES, CODES)
        self.assertEqual(tuple(nt.CATALOG), CODES)
        self.assertEqual(len(nt.CATALOG), 30)
        self.assertEqual((nt.LEVEL_INFO, nt.LEVEL_WARNING, nt.LEVEL_ERROR), ("INFO", "WARNING", "ERROR"))
        self.assertEqual(nt.LEVELS, ("INFO", "WARNING", "ERROR"))

    def test_every_code_has_the_pinned_level_and_the_pinned_title_where_one_is_given(self):
        for code in CODES:
            with self.subTest(code=code):
                level, title, message, action = nt.CATALOG[code]
                self.assertEqual(level, LEVELS[code])
                if code in TITLES:
                    self.assertEqual(title, TITLES[code])
                for text in (title, message, action):
                    self.assertTrue(text.strip() and "\n" not in text and len(text) <= nt.MAX_LINE)
                self.assertTrue(message.endswith((".", "다")) and action.endswith("."), code)

    def test_every_catalog_sentence_passes_the_candidates_selection_reason_rules_and_the_leak_check(self):
        for code in CODES:
            notice = nt.make(code)
            with self.subTest(code=code):
                self.assertEqual(nt.leaks(notice.text()), ())
                made = ts.make(selection_reasons=(notice.one_line(),))
                self.assertEqual(made.selection_reasons, (notice.one_line(),))

    def test_the_drop_reason_table_has_the_same_keys_as_the_generators_reasons_and_every_value_is_a_code(self):
        self.assertEqual(tuple(nt.DROP_REASON_NOTICE), gn.DROP_REASONS)
        self.assertEqual(len(nt.DROP_REASON_NOTICE), 17)
        for reason, code in nt.DROP_REASON_NOTICE.items():
            self.assertIn(code, nt.CATALOG, reason)
        self.assertEqual((nt.DROP_REASON_NOTICE["brand_only"], nt.DROP_REASON_NOTICE["brand_unfeasible"]), ("BRAND_ONLY", "BRAND_UNFEASIBLE"))

    def test_the_catalog_is_initial_values_the_module_says_so(self):
        doc = Path(nt.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
        self.assertIn("초기값 — 전략 원문 확인 전", doc)


class RequestSentencesTest(unittest.TestCase):                                                                 # N2
    def test_the_brand_only_notice_is_the_request_json_and_the_request_card(self):
        notice = nt.make("BRAND_ONLY")
        self.assertEqual(notice.to_dict(), {"code": "BRAND_ONLY", "level": "WARNING", "title": "주제 구체화 필요", "message": "브랜드명만으로는 작성 방향을 판단하기 어렵습니다.",
                                            "action": "제품, 기능 또는 비교 목적을 선택해 주세요.", "details": []})
        self.assertEqual(notice.text(), "주제 구체화 필요\n\n브랜드명만으로는 작성 방향을 판단하기 어렵습니다.\n제품, 기능 또는 비교 목적을 선택해 주세요.")

    def test_the_health_notice_is_the_request_card_with_the_concept_groups_as_bullets(self):
        report = sf.check_text(["불면을 완화하는 확실한 방법"])
        notice = nt.from_report(report)[0]
        self.assertEqual(notice.text(), "건강 정보 확인 필요\n\n효과를 단정하는 표현이 포함되어 있습니다.\n공식 근거를 확인하거나 일반 생활정보 표현으로 수정해 주세요.\n\n- 증상·상태 — 불면\n- 효과·결과 — 완화\n- 단정·보장 — 확실")

    def test_the_economic_notice_is_the_request_card(self):
        notice = nt.from_report(sf.check_text(["업체로부터 제품을 제공받음"]))[0]
        self.assertEqual(notice.title, "경제적 이해관계 확인 필요")
        self.assertEqual(notice.lines()[:4], ("경제적 이해관계 확인 필요", "", "제품·서비스 제공 또는 제휴 보상이 있는지 확인해 주세요.", "대가가 있다면 본문 첫 부분에 표시 문구가 필요합니다."))
        self.assertEqual(notice.details, ("현물 제공",))

    def test_a_notice_in_json_shape_has_exactly_the_requests_five_keys_plus_details(self):
        self.assertEqual(sorted(nt.make("HEALTH_STOP").to_dict()), ["action", "code", "details", "level", "message", "title"])


class RenderTest(unittest.TestCase):                                                                           # N3
    def test_a_card_is_title_blank_message_action_and_bullets_after_a_blank(self):
        notice = nt.make("HEALTH_TOPIC", ("제품·행위 — 영양제", "증상·상태 — 불면"))
        self.assertEqual(notice.lines(), ("건강 정보 확인 필요", "", "질환이나 건강 관련 제품을 다루는 주제입니다.", "공식 근거를 확인하고, 효과를 단정하지 않는 표현으로 써 주세요.", "", "- 제품·행위 — 영양제", "- 증상·상태 — 불면"))
        self.assertEqual(notice.text(), "\n".join(notice.lines()))
        self.assertEqual(notice.one_line(), "건강 정보 확인 필요 — 질환이나 건강 관련 제품을 다루는 주제입니다. 공식 근거를 확인하고, 효과를 단정하지 않는 표현으로 써 주세요.")

    def test_cards_and_bullet_lines_join_several_notices_without_a_list_shape(self):
        notices = (nt.make("BRAND_ONLY"), nt.make("SHORTAGE", ("씨앗 1개",)))
        self.assertEqual(nt.cards(notices), notices[0].text() + "\n\n" + notices[1].text())
        self.assertEqual(nt.bullet_lines(notices), ("- 주제 구체화 필요: 브랜드명만으로는 작성 방향을 판단하기 어렵습니다. 제품, 기능 또는 비교 목적을 선택해 주세요.",
                                                  "- 목표에 모자란 경로: 일부 경로의 후보가 목표보다 적습니다. 모자란 자리는 다른 경로가 채우지 않았습니다. 씨앗·이력·이슈를 더하면 늘어납니다."))
        for text in (nt.cards(notices), *nt.bullet_lines(notices)):
            self.assertNotRegex(text, r"\[.*\]")
            self.assertEqual(nt.leaks(text), ())
        self.assertEqual(nt.cards(()), "")
        self.assertEqual(nt.bullet_lines(()), ())


class ConvertersTest(unittest.TestCase):                                                                       # N4
    def test_from_report_makes_one_notice_per_finding_with_the_highest_level_first(self):
        report = sf.check_text(["수익 보장 영양제 확실히 치료 협찬 제공받음 직접 써본 후기"], opportunity=True)
        notices = nt.from_report(report)
        self.assertEqual([item.level for item in notices], sorted((item.level for item in notices), key=nt.LEVELS.index, reverse=True))
        self.assertEqual({item.code for item in notices}, {finding.code for finding in report.findings})
        self.assertEqual(nt.from_report(sf.SafetyReport((), ())), ())

    def test_from_dropped_turns_every_reason_into_its_notice_with_the_route_count_and_the_first_case(self):
        rows = [gn.Dropped("seed", reason, 2, f"씨앗 ‘예시’: 첫 사례 {number}") for number, reason in enumerate(gn.DROP_REASONS)]
        notices = nt.from_dropped(rows)
        self.assertEqual(len(notices), 17)
        by_code = {item.code: item for item in notices}
        self.assertEqual(set(by_code), {nt.DROP_REASON_NOTICE[reason] for reason in gn.DROP_REASONS})
        for item in notices:
            self.assertEqual(item.details[0], "씨앗 · 2건")
            self.assertTrue(item.details[1].startswith("씨앗 ‘예시’: 첫 사례"))
        with self.assertRaises(ValueError):
            nt.from_dropped([gn.Dropped("seed", "zzz", 1, "x")])

    def test_from_generated_adds_the_shortage_notice_with_the_routes_that_fell_short(self):
        found = run(A, [seed()], target=40)
        notices = nt.from_generated(found)
        self.assertTrue(any(item.code == "SHORTAGE" for item in notices))
        shortage = next(item for item in notices if item.code == "SHORTAGE")
        self.assertTrue(all(line.endswith("개") for line in shortage.details))
        self.assertEqual(nt.from_generated(run(A, [seed()], target=0)), nt.from_dropped(run(A, [seed()], target=0).dropped))

    def test_a_hold_band_candidate_gets_the_hold_notice_with_the_review_date_and_others_get_none(self):
        held = ts.rated(55, review_expires_at="2027-02-02T09:56:00Z")
        self.assertEqual(nt.hold_notice(held).details, ("검토 기한 2027-02-02",))
        self.assertIsNone(nt.hold_notice(ts.rated(90)))
        both = nt.for_candidate(held, sf.check_text(["영양제 구매 기준"]))
        self.assertEqual([item.code for item in both], ["HEALTH_TOPIC", "HOLD_BAND"])

    def test_the_selection_reason_lines_are_only_warnings_and_errors_and_the_info_stays_on_screen(self):
        report = sf.check_text(["영양제 구매 기준"], opportunity=True)
        self.assertEqual(len(nt.notes(report)), 1)
        self.assertEqual(len(nt.from_report(report)), 2)

    def test_the_converters_only_read_attributes_so_a_plain_object_works_too(self):
        class Row:
            route, reason, count, detail = "realtime", "unstable", 3, "이슈 ‘x’: 아직"
        self.assertEqual(nt.from_dropped([Row])[0].code, "DROP_UNSTABLE")


class LeakCheckTest(unittest.TestCase):                                                                        # N5
    def test_the_leak_check_finds_the_developer_shapes_and_passes_plain_korean(self):
        bad = ("['브랜드만 있음', '건강 표현 검토']", "{'a': 1}", "state=BRAND_ONLY", "health_check 표시", "top_n 칸", "Enum 값", "None 입니다", "<b>굵게</b>", "줄\\n바꿈", "'a' 와 'b'", "dict 형", "tuple 형")
        for text in bad:
            with self.subTest(text=text):
                self.assertTrue(nt.leaks(text), text)
        good = ("주제 구체화 필요", "‘['a', 'b']’ 는 입력한 글입니다", "‘health_check’ 낱말", "한국어와 English 가 섞인 글", "(걸린 말: 불면, 완화)", "AI 서비스 · PC 부품", "API 사용량", "2026-11-10", "50~64점")
        for text in good:
            with self.subTest(text=text):
                self.assertEqual(nt.leaks(text), (), text)
        self.assertTrue(nt.is_clean("깨끗한 글") and not nt.is_clean("[x]"))

    def test_a_notice_refuses_a_developer_shape_in_any_field(self):
        base = dict(code="BRAND_ONLY", level="WARNING", title="제목", message="설명입니다.", action="행동입니다.")
        for field in ("title", "message", "action"):
            with self.assertRaises(ValueError):
                nt.Notice(**{**base, field: "['a', 'b']"})
        with self.assertRaises(ValueError):
            nt.Notice(**base, details=("health_check",))
        with self.assertRaises(ValueError):
            nt.Notice(**base, details=["목록은 받지 않는다"])
        for bad in ({"code": "ZZZ"}, {"level": "FATAL"}, {"title": ""}, {"message": "두\n줄"}, {"action": "x" * 301}):
            with self.assertRaises(ValueError):
                nt.Notice(**{**base, **bad})

    def test_every_sentence_the_safety_module_can_say_over_the_whole_corpus_is_free_of_developer_shapes(self):
        groups = (corpus.RISK_HEALTH_STOP, corpus.RISK_HEALTH_CHECK, corpus.RISK_PROMISE, corpus.RISK_SPONSOR, corpus.RISK_EXPERIENCE, corpus.NORMAL_NAVER_B, corpus.NORMAL_EN)
        count = 0
        for group in groups:
            for text in group:
                report = sf.check_text([text], opportunity=True)
                for line in sf.notes(report):
                    count += 1
                    self.assertEqual(nt.leaks(line), (), line)
                for notice in nt.from_report(report):
                    count += 1
                    self.assertEqual(nt.leaks(notice.text()), (), notice.text())
        self.assertGreater(count, 150)

    def test_every_sentence_a_generated_run_can_say_is_free_of_developer_shapes(self):
        worlds = (
            run(A, [seed()], target=40), run(A, [seed(seed_type="priority", priority=True)], target=100), run(A, [seed(excluded_keywords=("비용",))], target=100), run(B, [seed(minor="로컬 AI")], target=100),
            run(A, [seed(seed_id="sp1", keyword="예시 호텔", major="여행", minor="숙박", seed_type="sponsorable", sponsor_tag="lodging_travel")], target=100),
            run(A, [seed(keyword="영양제", seed_type="priority", priority=True)], target=100), run(A, [seed(keyword="Gemini")], target=100), run(A, [seed(keyword="삼성", major="가", minor="없는 분류")], target=100),
            run(A, [seed(keyword="삼성 LG")], target=100), run(B, [seed(keyword="NVIDIA", major="가", minor="없는 분류")], target=100), run(ts.PROFILES["blogger_en"], [seed()], target=100), run(A, [], target=10),
            run(A, [seed(seed_id="z1", keyword="예시 난방", seed_type="seasonal")], calendar=[ts.example_entry(keywords=("예시 난방",))], target=100),
            run(A, [seed(keyword="예시 호텔", seed_type="sponsorable", sponsor_tag="lodging_travel", major="여행", minor="숙박")], target=100,
                campaigns=[sf.Campaign(campaign_id="camp-1", benefits=("goods", "payment"), status="confirmed", seed_id="s1")]),
            run(A, [seed(keyword="Claude", sponsor_tag="ai_service")], target=100, existing=run(A, [seed(keyword="Claude", sponsor_tag="ai_service")], target=100).candidates[:2]),
        )
        count = 0
        for found in worlds:
            lines = [*found.notes, *(row.detail for row in found.dropped), *(reason for candidate in found.candidates for reason in candidate.selection_reasons)]
            for line in lines:
                count += 1
                self.assertEqual(nt.leaks(line), (), line)
            for notice in nt.from_generated(found):
                count += 1
                self.assertEqual(nt.leaks(notice.text()), (), notice.text())
        self.assertGreater(count, 100)


class InputNeverLeaksTest(unittest.TestCase):                                                                  # N6
    def test_an_input_that_looks_like_a_python_list_or_a_code_or_a_tag_stays_inside_the_curly_quotes(self):
        for keyword in ("['a', 'b']", "health_check", "<b>굵게</b>"):
            with self.subTest(keyword=keyword):
                try:
                    pool = [seed(keyword=keyword, excluded_keywords=("비용",))]
                except Exception:
                    continue                                                        # 씨앗 칸 규칙이 이 모양을 거절하면 알림까지 오지 않는다
                found = run(A, pool, target=100)
                for notice in nt.from_generated(found):
                    for field in (notice.title, notice.message, notice.action):
                        self.assertNotIn(keyword, field)
                    for line in notice.details:
                        self.assertEqual(nt.leaks(line), ())

    def test_a_first_case_sentence_that_leaks_outside_the_quotes_loses_only_that_line(self):
        good = gn.Dropped("seed", "excluded_keyword", 1, "씨앗 ‘['a']’: 제외 키워드가 들어 있어 쓰지 않습니다")
        bad = gn.Dropped("seed", "too_long", 1, "씨앗 ['a', 'b']: 너무 깁니다")
        first, second = nt.from_dropped([good, bad])
        self.assertEqual(len(first.details), 2)
        self.assertEqual(second.details, ("씨앗 · 1건",), "새는 줄만 빠지고 알림은 그대로다")
        self.assertEqual(second.code, "DROP_TOO_LONG")

    def test_the_title_message_and_action_never_contain_anything_but_the_catalog_sentence(self):
        for code in CODES:
            notice = nt.make(code, ("‘입력’",))
            self.assertEqual((notice.title, notice.message, notice.action), nt.CATALOG[code][1:])


class LevelsTest(unittest.TestCase):                                                                           # N7
    def test_each_notice_has_the_level_of_its_catalog_row_and_the_list_is_sorted_by_level_then_catalog_order(self):
        for code in CODES:
            self.assertEqual(nt.make(code).level, LEVELS[code])
            self.assertEqual(nt.level_of(code), LEVELS[code])
        shuffled = [nt.make(code) for code in ("COLLAB_POSSIBLE", "HEALTH_STOP", "DROP_NO_SEED", "BRAND_ONLY", "SHORTAGE", "HEALTH_TOPIC", "RESULT_PROMISE")]
        self.assertEqual([item.code for item in nt.sort_notices(shuffled)], ["HEALTH_STOP", "RESULT_PROMISE", "HEALTH_TOPIC", "BRAND_ONLY", "DROP_NO_SEED", "COLLAB_POSSIBLE", "SHORTAGE"])

    def test_the_safety_report_codes_all_exist_in_the_catalog_and_an_error_means_stop_while_info_means_no_flag(self):
        for text in corpus.RISK_HEALTH_STOP + corpus.RISK_HEALTH_CHECK + corpus.RISK_SPONSOR + corpus.RISK_EXPERIENCE:
            report = sf.check_text([text], opportunity=True)
            for finding in report.findings:
                self.assertIn(finding.code, nt.CATALOG)
                self.assertEqual(finding.level, nt.level_of(finding.code))
            self.assertEqual(report.stop, any(finding.level == "ERROR" for finding in report.findings))
        info = sf.check_text(["로컬 AI 사양 확인"], opportunity=True)
        self.assertEqual((info.flags, info.level), ((), "INFO"))

    def test_to_dict_has_exactly_six_keys_and_details_is_a_list_and_a_list_argument_is_refused(self):
        data = nt.make("HEALTH_TOPIC", ("가", "나")).to_dict()
        self.assertEqual(list(data), ["code", "level", "title", "message", "action", "details"])
        self.assertEqual(data["details"], ["가", "나"])
        with self.assertRaises(ValueError):
            nt.level_of("ZZZ")
        with self.assertRaises(ValueError):
            nt.make("ZZZ")


class BrandNoticesTest(unittest.TestCase):                                                                     # N8
    def test_a_specified_brand_gives_the_info_notice_with_the_fixed_lines_and_the_count(self):
        view = br.assess(seed(keyword="Gemini"), B)
        notices = nt.from_brand(view)
        self.assertEqual([item.code for item in notices], ["BRAND_SPECIFIED"])
        self.assertEqual(notices[0].details, ("브랜드: Gemini", "제품·서비스 유형: AI 서비스", "유형을 정한 근거: 브랜드 표에 유형이 하나뿐이라", "하위 후보 3개"))

    def test_a_brand_that_needs_a_topic_gives_the_request_warning_with_the_reason_line(self):
        view = br.assess(seed(keyword="삼성", major="가", minor="없는 분류"), A)
        notices = nt.from_brand(view)
        self.assertEqual([item.code for item in notices], ["BRAND_ONLY"])
        self.assertEqual(notices[0].details, ("제품 유형이 여럿입니다: 가전·PC 주변기기",))
        listed = nt.from_brand(br.assess(seed(keyword="삼성 LG"), A))
        self.assertEqual(listed[0].details, ("브랜드가 둘 이상입니다: 삼성·LG",))

    def test_a_brand_whose_subtopics_all_fail_gives_the_unfeasible_warning_and_a_partial_failure_gives_both(self):
        low = ch.ChannelProfile(**{**ts.PROFILES["naver_b"].__dict__, "subheading_min": 10})
        notices = nt.from_brand(br.assess(seed(keyword="Gemini"), low))
        self.assertEqual([item.code for item in notices], ["BRAND_UNFEASIBLE"])
        self.assertEqual(notices[0].details, ("소제목 최소 수를 채우지 못한 하위 주제: 3개",))
        partial = ch.ChannelProfile(**{**ts.PROFILES["naver_b"].__dict__, "subheading_min": 8})
        both = nt.from_brand(br.assess(seed(keyword="Gemini"), partial))
        self.assertEqual({item.code for item in both}, {"BRAND_SPECIFIED", "BRAND_UNFEASIBLE"})

    def test_a_seed_that_is_not_a_brand_gives_nothing_and_the_view_names_never_leak(self):
        self.assertEqual(nt.from_brand(br.NOT_BRAND_VIEW), ())
        self.assertEqual(nt.from_brand(br.assess(seed(keyword="삼성 노트북 비교"), A)), ())
        for keyword in ("Gemini", "삼성", "삼성 LG", "NVIDIA"):
            for notice in nt.from_brand(br.assess(seed(keyword=keyword), A)) + nt.from_brand(br.assess(seed(keyword=keyword), B)):
                self.assertEqual(nt.leaks(notice.text()), (), notice.text())
                self.assertNotRegex(notice.text(), re.compile(r"BRAND_|NOT_BRAND|needs_topic"))


if __name__ == "__main__":
    unittest.main()
