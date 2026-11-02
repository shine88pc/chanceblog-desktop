"""주제 후보 모델 시험 — 상태 이동 표(문서와 코드가 같은지·25칸 전수), 블로그별 선택 기록, 값 검사(경계·거절), 표현 규칙, 엄격한 JSON 저장 모양.

지키는 것:
  1) 상태는 다섯이고 이동 표는 문서(§9)와 코드가 같다. 표에 있는 이동만 되고(25칸 전수), 초안 이후 상태는 새로 만들지 않고 네이버 흐름에 대응한다.
  2) 지표는 모두 선택이다('데이터 없음'). 값이 있으면 조회일도 있어야 하고, 모든 값은 경계에서 맞게 받고 틀리면 CONTENT_INVALID 로 거절한다 — 고쳐 받지 않는다.
  3) 상위노출 보장·노출 확률·검색 1위 가능성·수익 보장 같은 표현은 어느 글칸에도 쓸 수 없고, 지표 이름(라벨)은 허용된 표현뿐이다.
  4) 후보는 바꿀 수 없는 값이고 바뀔 때마다 판 번호가 오른다. 선택은 블로그마다 따로 기록한다.
  5) 저장 모양(JSON)은 엄격하게 읽는다 — 모르는 칸·어긋난 값은 거절하고, 나중에 칸이 늘어도 옛 자료는 읽힌다.
  6) 표현 금지·위험한 표기 규칙은 거절 목록과 통과 목록(각 40개 이상)으로 정의하고, 거절 문구는 후보 전용으로 어느 칸이 왜 안 되는지 담는다. 한계는 글자 그대로의 숫자로 지킨다.
네트워크·파일 없이 돈다.
"""
import dataclasses
import json
import re
import sys
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import Candidate  # noqa: E402
from chanceblog_desktop.content import candidates as cand  # noqa: E402
from chanceblog_desktop.content import profiles  # noqa: E402
from chanceblog_desktop.content.candidates import (  # noqa: E402
    ALLOWED_TERMS, FOLLOW_ON, FOLLOW_ON_KO, LABELS, MAX_KEYWORD, MAX_REASON, MAX_RELATED_RESULTS, MAX_REVISION, MAX_SEARCH_DEMAND, MAX_SUB_KEYWORDS, MAX_TOPIC, METRIC_FIELDS, SHORT_ID, STATUS_KO,
    STATUSES, TRANSITIONS, TRENDS, can_transition, find_forbidden_claim, forbidden_claim, keyword_key, next_statuses, parse_stamp, short_id, status_name)
from chanceblog_desktop.content.profiles import find_markup  # noqa: E402
from chanceblog_desktop.content.status import PLATFORMS, statuses  # noqa: E402
from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.errors.render import UNKNOWN_SLOT  # noqa: E402

NOW = "2026-11-02T03:00:00Z"
LATER = "2026-11-02T04:30:00Z"
DAY = "2026-11-01"
ARCH = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
TROUBLE = (ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
# 지표마다 맞는 값 하나(조회일과 함께 넣어야 한다)
SAMPLES = {"search_demand": 1200, "related_blog_results": 300, "trend": "보합", "mobile_share": 60, "seasonality": (6, 7), "duplicate": True, "profile_fit": 70, "priority": 55,
           "keyword_opportunity": 40}
FULL = dict(sub_keywords=("보일러 에러", "난방비 절약"), blogs=("naver_a", "naver_b", "github_pages"), post_type="문제 해결형", search_demand=12000, related_blog_results=34500,
            trend="상승", mobile_share=72.5, seasonality=(11, 12, 1, 2), duplicate=False, profile_fit=81, priority=76.5, keyword_opportunity=64,
            reason="겨울 전에 찾는 사람이 늘고 관련 글이 많지 않습니다.", data_date=DAY)


def section9():
    start = ARCH.index("## 9. 데이터 모델")
    return ARCH[start:ARCH.index("\n## 10.", start)]


def make(**changes):
    base = {"topic": "겨울철 보일러 점검 방법", "keyword": "보일러 점검", "blogs": ("naver_a",), "candidate_id": "c1", "now": NOW}
    base.update(changes)
    return Candidate.new(base.pop("topic"), base.pop("keyword"), base.pop("blogs"), **base)


def refuses(test, code, callable_, *args, **kwargs):
    """AppError 의 코드를 확인하고, 사용자 문구의 자리표시자가 모두 채워지는지도 본다."""
    with test.assertRaises(AppError) as caught:
        callable_(*args, **kwargs)
    error = caught.exception
    test.assertEqual(error.code, code, error.detail)
    shown = error.rendered()
    test.assertNotIn(UNKNOWN_SLOT, shown.message + shown.action, f"{code}: 자리표시자가 비었다")
    return error


class StatusTableTest(unittest.TestCase):
    def test_the_five_states_and_their_korean_names(self):
        self.assertEqual(STATUSES, ("NEW", "REVIEW", "SELECTED", "HOLD", "REJECTED"))
        self.assertEqual([STATUS_KO[state] for state in STATUSES], ["새 후보", "검토 중", "선택됨", "보류", "제외"])
        self.assertEqual([status_name(state) for state in STATUSES], ["새 후보", "검토 중", "선택됨", "보류", "제외"])
        self.assertEqual(set(STATUS_KO), set(STATUSES))

    def test_the_transition_table_is_pinned_so_a_change_is_always_a_deliberate_one(self):
        self.assertEqual({state: tuple(targets) for state, targets in TRANSITIONS.items()}, {
            "NEW": ("REVIEW", "SELECTED", "HOLD", "REJECTED"), "REVIEW": ("SELECTED", "HOLD", "REJECTED"), "HOLD": ("REVIEW", "SELECTED", "REJECTED"),
            "REJECTED": ("REVIEW",), "SELECTED": ("HOLD", "REVIEW"),
        })

    def test_nothing_goes_back_to_new_and_a_rejected_one_can_only_be_revived_into_review(self):
        for state, targets in TRANSITIONS.items():
            self.assertNotIn("NEW", targets, state)
            self.assertNotIn(state, targets, "제자리 이동은 표에 없다")
        self.assertEqual(TRANSITIONS["REJECTED"], ("REVIEW",))
        self.assertTrue(all(state in STATUSES for targets in TRANSITIONS.values() for state in targets))

    def test_the_helpers_agree_with_the_table_for_all_25_pairs(self):
        for current in STATUSES:
            self.assertEqual(next_statuses(current), TRANSITIONS[current])
            for requested in STATUSES:
                with self.subTest(current=current, requested=requested):
                    self.assertEqual(can_transition(current, requested), requested in TRANSITIONS[current])
        self.assertFalse(can_transition("NEW", "DRAFTING"))
        self.assertFalse(can_transition("NOPE", "NEW"))
        self.assertEqual(next_statuses("NOPE"), ())

    def test_moving_follows_the_table_for_all_25_pairs_and_names_the_states_in_korean(self):
        for current in STATUSES:
            for requested in STATUSES:
                with self.subTest(current=current, requested=requested):
                    start = make(status=current)
                    if requested in TRANSITIONS[current]:
                        moved = start.moved(requested, now=LATER)
                        self.assertEqual((moved.status, moved.revision, moved.updated_at), (requested, 2, LATER))
                        self.assertEqual((start.status, start.revision), (current, 1), "원래 후보는 그대로다")
                    else:
                        error = refuses(self, "CANDIDATE_TRANSITION_INVALID", start.moved, requested, now=LATER)
                        self.assertEqual(error.slots, {"현재 상태": STATUS_KO[current], "요청 상태": STATUS_KO[requested]})
                        shown = error.rendered().message
                        self.assertIn(STATUS_KO[current], shown)
                        self.assertIn(STATUS_KO[requested], shown)
                        self.assertNotIn(current, shown, "영문 상태 코드는 화면 문구에 나오지 않는다")
                        self.assertEqual((start.status, start.revision), (current, 1))

    def test_a_move_changes_only_the_status_the_choice_record_the_revision_and_the_time(self):
        item = make(project_id="p1", **FULL)
        for requested in ("REVIEW", "HOLD", "REJECTED", "SELECTED"):
            with self.subTest(requested=requested):
                before, after = item.to_dict(), item.moved(requested, now=LATER).to_dict()
                changed = {name for name in before if before[name] != after[name]}
                self.assertEqual(changed, {"status", "selections", "revision", "updated_at"} if requested == "SELECTED" else {"status", "revision", "updated_at"})

    def test_a_state_that_is_not_a_candidate_state_cannot_be_moved_to(self):
        for bad in ("DRAFTING", "DRAFT_READY", "COPIED", "PUBLISHED", "NOT_STARTED", "new", "", None, 5, ["NEW"]):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make().moved, bad)
        for bad in ("DRAFTING", "nope", None, 5):
            with self.subTest(status=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, status=bad)

    def test_a_time_that_is_not_a_real_stamp_is_refused_by_every_way_of_changing_a_candidate(self):
        item = make(**{"sub_keywords": ("보조",)})
        for bad in ("어제", "", "2026-11-02", "2026-02-30T00:00:00Z", 5):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", item.moved, "REVIEW", now=bad)
                refuses(self, "CANDIDATE_INVALID", item.moved, "SELECTED", now=bad)
                refuses(self, "CANDIDATE_INVALID", item.moved, "SELECTED", blog="naver_b", now=bad)
                refuses(self, "CANDIDATE_INVALID", item.edited, reason="새 이유", now=bad)
        self.assertEqual((item.status, item.revision, item.updated_at, item.selections), ("NEW", 1, NOW, ()))

    def test_a_failed_move_changes_nothing(self):
        start = make(status="REJECTED")
        before = start.to_dict()
        refuses(self, "CANDIDATE_TRANSITION_INVALID", start.moved, "SELECTED", now=LATER)
        self.assertEqual(start.to_dict(), before)


class FollowOnTest(unittest.TestCase):
    NINE = {"NEW", "REVIEW", "SELECTED", "DRAFTING", "DRAFT_READY", "COPIED", "HOLD", "REJECTED", "PUBLISHED"}

    def test_the_four_later_states_are_not_new_candidate_states_but_map_onto_the_existing_naver_flow(self):
        self.assertEqual(FOLLOW_ON, {"DRAFTING": "DRAFT_GENERATED", "DRAFT_READY": "READY_TO_COPY", "COPIED": "COPY_COMPLETED", "PUBLISHED": "PUBLISHED_MANUAL"})
        self.assertEqual(set(FOLLOW_ON) | set(STATUSES), self.NINE, "요구서의 아홉 상태가 모두 어느 한쪽에 있다")
        self.assertFalse(set(FOLLOW_ON) & set(STATUSES), "초안 이후 상태를 후보 상태로 또 만들지 않는다")
        flow = statuses("naver_a")
        self.assertEqual(statuses("naver_b"), flow)
        self.assertTrue(all(target in flow for target in FOLLOW_ON.values()), "대응하는 상태가 실제 네이버 흐름에 있다")
        order = [flow.index(target) for target in FOLLOW_ON.values()]
        self.assertEqual(order, sorted(order), "진행 순서가 흐름과 같다")

    def test_every_one_of_the_nine_states_and_the_four_flow_states_has_a_korean_name(self):
        self.assertEqual(set(FOLLOW_ON_KO), set(FOLLOW_ON))
        self.assertEqual([status_name(name) for name in ("DRAFTING", "DRAFT_READY", "COPIED", "PUBLISHED")], ["초안 작성 중", "초안 완료", "복사 완료", "발행 완료"])
        self.assertEqual([status_name(name) for name in ("DRAFT_GENERATED", "READY_TO_COPY", "COPY_COMPLETED", "PUBLISHED_MANUAL")], ["초안 작성 중", "초안 완료", "복사 완료", "발행 완료"])
        for name in self.NINE:
            self.assertTrue(status_name(name), name)
        self.assertEqual(len({status_name(name) for name in self.NINE}), 9, "아홉 상태의 이름이 서로 다르다")

    def test_a_name_for_an_unknown_state_is_refused_not_guessed(self):
        for bad in ("NOPE", "", None, 5, "new", "REVIEW_REQUIRED", "PUBLISH_FAILED", "NOT_STARTED", "APPROVED", ["NEW"]):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", status_name, bad)


class DocumentTest(unittest.TestCase):
    def test_the_documented_transitions_are_what_the_code_does(self):
        line = " / ".join(f"`{state}` → " + "·".join(f"`{target}`" for target in targets) for state, targets in TRANSITIONS.items())
        self.assertIn(line, section9())

    def test_the_documented_follow_on_correspondence_is_what_the_code_says(self):
        text = section9()
        shown = "(요구서의 " + "·".join(FOLLOW_ON) + " 는 각각 " + "·".join(f"`{flow}`" for flow in FOLLOW_ON.values()) + " 에 대응하고, 화면에는 " + "·".join(FOLLOW_ON_KO.values()) + "로 보인다)"
        self.assertIn(shown, text)
        for name in ("DRAFTING", "DRAFT_READY", "COPIED"):             # PUBLISHED 는 Pages 흐름의 진짜 상태 이름이라 문서에 나와도 된다
            self.assertNotIn(f"`{name}`", text, "요구서에만 있는 이름은 앱의 상태 이름처럼 쓰지 않는다(상태 표시 시험이 낯선 이름으로 본다)")

    def test_the_documented_expression_rule_and_allowed_names_match(self):
        text = section9()
        for needle in ALLOWED_TERMS + ("상위노출 보장", "노출 확률", "검색 1위 가능성", "수익 보장"):
            self.assertIn(needle, text, needle)

    def test_the_new_error_codes_are_in_the_table_with_the_slots_the_code_fills(self):
        for code, slots in (("CANDIDATE_NOT_FOUND", {"항목"}), ("CANDIDATE_TRANSITION_INVALID", {"현재 상태", "요청 상태"}), ("CANDIDATE_CONFIRM_REQUIRED", {"항목"})):
            with self.subTest(code):
                self.assertIn(code, CATALOG)
                self.assertEqual(set(CATALOG[code].slots), slots)
                self.assertIn(f"`{code}`", TROUBLE)
                self.assertTrue(CATALOG[code].message and CATALOG[code].action)

    def test_the_candidate_error_texts_say_what_to_do_in_candidate_words(self):
        self.assertIn("후보", CATALOG["CANDIDATE_NOT_FOUND"].message)
        self.assertIn("후보", CATALOG["CANDIDATE_TRANSITION_INVALID"].message)
        self.assertIn("되살린", CATALOG["CANDIDATE_TRANSITION_INVALID"].action)
        self.assertIn("확인", CATALOG["CANDIDATE_CONFIRM_REQUIRED"].message)

    def test_candidate_handling_is_listed_among_the_things_that_work_without_ai(self):
        start = ARCH.index("## 8. AI 없이 반드시 동작해야 하는 기능")
        self.assertIn("주제 후보 관리", ARCH[start:ARCH.index("\n## 9.", start)])

    def test_the_profile_options_are_listed_in_the_architecture_row(self):
        row = next(line for line in ARCH.splitlines() if line.startswith("| `content/` |"))
        for needle in ("candidates.py", "도입부 스타일", "소제목 수", "설명 난이도", "마무리 방식", "제외 주제", "같은 주제 재사용 기준", "기본 글 유형"):
            self.assertIn(needle, row, needle)


class SelectionTest(unittest.TestCase):
    def test_selecting_without_a_blog_picks_every_recommended_blog_at_that_moment(self):
        picked = make(blogs=("naver_b", "naver_a")).moved("SELECTED", now=LATER)
        self.assertEqual(picked.selections, (("naver_a", LATER), ("naver_b", LATER)), "플랫폼 순서로 정리된다")
        self.assertEqual(picked.selected_blogs, ("naver_a", "naver_b"))
        self.assertEqual(picked.selected_time("naver_a"), LATER)
        self.assertIsNone(picked.selected_time("github_pages"))

    def test_selecting_for_one_blog_records_only_that_blog_even_if_it_was_not_recommended(self):
        picked = make(blogs=("naver_a", "naver_b")).moved("SELECTED", blog="naver_b", now=LATER)
        self.assertEqual(picked.selections, (("naver_b", LATER),))
        elsewhere = make(blogs=("naver_a",)).moved("SELECTED", blog="blogger_en", now=LATER)
        self.assertEqual(elsewhere.selections, (("blogger_en", LATER),), "추천은 힌트일 뿐 고르는 것은 운영자다")

    def test_a_second_blog_can_be_added_while_the_candidate_stays_selected_and_a_blog_can_be_reselected(self):
        first = make(blogs=("naver_a", "naver_b")).moved("SELECTED", blog="naver_a", now=NOW)
        second = first.moved("SELECTED", blog="naver_b", now=LATER)
        self.assertEqual((second.status, second.selections, second.revision), ("SELECTED", (("naver_a", NOW), ("naver_b", LATER)), 3))
        again = second.moved("SELECTED", blog="naver_a", now="2026-11-03T00:00:00Z")
        self.assertEqual(again.selections, (("naver_a", "2026-11-03T00:00:00Z"), ("naver_b", LATER)), "다시 고르면 그 블로그의 시각만 새로 된다")
        self.assertEqual(first.selections, (("naver_a", NOW),), "원래 후보는 그대로다")

    def test_selecting_an_already_selected_candidate_without_a_blog_is_not_a_move(self):
        picked = make().moved("SELECTED", now=NOW)
        refuses(self, "CANDIDATE_TRANSITION_INVALID", picked.moved, "SELECTED", now=LATER)

    def test_a_rejected_candidate_cannot_be_selected_even_for_a_blog(self):
        refuses(self, "CANDIDATE_TRANSITION_INVALID", make(status="REJECTED").moved, "SELECTED", blog="naver_a", now=LATER)

    def test_the_blog_argument_is_for_selecting_only_and_must_be_a_known_blog(self):
        for status in ("REVIEW", "HOLD", "REJECTED", "NEW"):
            with self.subTest(status=status):
                refuses(self, "CANDIDATE_INVALID", make().moved, status, blog="naver_a")
        for bad in ("naver_c", "", "NAVER_A", 5, ["naver_a"]):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make().moved, "SELECTED", blog=bad)

    def test_the_record_of_a_choice_stays_when_the_candidate_is_put_on_hold_or_back_in_review(self):
        picked = make().moved("SELECTED", now=NOW)
        for status in ("HOLD", "REVIEW"):
            with self.subTest(status=status):
                self.assertEqual(picked.moved(status, now=LATER).selections, (("naver_a", NOW),))
        back = picked.moved("HOLD", now=LATER).moved("SELECTED", now="2026-11-05T00:00:00Z")
        self.assertEqual(back.selections, (("naver_a", "2026-11-05T00:00:00Z"),), "다시 고르면 시각이 새로 된다")

    def test_the_selection_record_is_checked_strictly(self):
        for bad in ((("naver_c", NOW),), (("naver_a", "어제"),), (("naver_a", NOW), ("naver_a", LATER)), (("naver_a",),), "naver_a", 5, ((5, NOW),), (("naver_a", NOW, 1),), (("naver_a", "2026-02-30T00:00:00Z"),)):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, selections=bad)
        self.assertEqual(make(status="SELECTED", selections={"naver_b": NOW, "github_pages": LATER}).selections, (("github_pages", LATER), ("naver_b", NOW)))
        self.assertEqual(make(status="HOLD", selections=[["naver_a", NOW]]).selections, (("naver_a", NOW),))


class ValidationTest(unittest.TestCase):
    def test_a_minimal_candidate_has_no_data_and_the_documented_defaults(self):
        item = make()
        self.assertEqual((item.candidate_id, item.topic, item.keyword, item.blogs, item.sub_keywords, item.post_type), ("c1", "겨울철 보일러 점검 방법", "보일러 점검", ("naver_a",), (), "정보형"))
        self.assertEqual((item.status, item.selections, item.project_id, item.revision, item.created_at, item.updated_at, item.reason, item.data_date), ("NEW", (), None, 1, NOW, NOW, "", None))
        self.assertTrue(all(getattr(item, name) is None for name in METRIC_FIELDS), "지표는 모두 비어 있다 — 데이터 없음")
        self.assertFalse(item.has_data())

    def test_a_new_candidate_without_an_id_gets_a_fresh_one_and_the_current_time(self):
        first, second = Candidate.new("주제", "키워드", ["naver_a"]), Candidate.new("주제", "키워드", ["naver_a"])
        self.assertRegex(first.candidate_id, r"^[0-9a-f]{32}$")
        self.assertNotEqual(first.candidate_id, second.candidate_id)
        self.assertRegex(first.created_at, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(first.created_at, first.updated_at)
        self.assertEqual(first.revision, 1)

    def test_the_candidate_id_is_a_short_plain_token(self):
        for good in ("a", "c-1_x", "A" * 64, "0" * 64, "z"):
            self.assertEqual(make(candidate_id=good).candidate_id, good)
        for bad in ("", "a" * 65, "a b", "../x", "a/b", "한글", "a\n", "a\nb", " a", "a;DROP", 5, b"a"):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, candidate_id=bad)
        refuses(self, "CANDIDATE_INVALID", Candidate, None, "주제", "키워드", ("naver_a",), created_at=NOW, updated_at=NOW)      # `new` 는 번호가 없으면 만들지만 직접 만들 때는 번호가 꼭 있어야 한다

    def test_topic_keyword_and_reason_are_one_clean_short_line(self):
        for field, low, high in (("topic", 1, MAX_TOPIC), ("keyword", 1, MAX_KEYWORD), ("reason", 0, MAX_REASON)):
            with self.subTest(field=field):
                self.assertEqual(getattr(make(**{field: "가" * high}), field), "가" * high)
                self.assertEqual(getattr(make(**{field: "  앞뒤 공백  "}), field), "앞뒤 공백", "앞뒤 공백만 있으면 그냥 정리한다")
                refuses(self, "CANDIDATE_INVALID", make, **{field: "가" * (high + 1)})
                for bad in ("줄\n바꿈", "탭\t넣기", "겹친  공백", "널\x00문자", "숨은\u200b글자", "방향\u202e뒤집기", "채움\u3164글자", "점자\u2800빈칸", "채움\uffa0글자", 5, None, ["글"], b"bytes"):
                    with self.subTest(field=field, bad=repr(bad)):
                        refuses(self, "CANDIDATE_INVALID", make, **{field: bad})
                if low:
                    for empty in ("", "   "):
                        refuses(self, "CANDIDATE_INVALID", make, **{field: empty})
                else:
                    self.assertEqual(make(**{field: ""}).reason, "")

    def test_raw_html_and_template_traces_are_refused_everywhere_text_goes(self):
        for trace in ("<b>굵게</b>", "<script>x</script>", "<!-- 주석 -->", "{{ 값 }}", "{% if x %}", "{# 메모 #}", "닫는 %}", "javascript:alert(1)", "JavaScript:x", "<br/>", "</p>"):
            for field in ("topic", "keyword", "reason"):
                with self.subTest(field=field, trace=trace):
                    refuses(self, "CANDIDATE_INVALID", make, **{field: trace})
            with self.subTest(field="sub_keywords", trace=trace):
                refuses(self, "CANDIDATE_INVALID", make, sub_keywords=(trace,))
        for fine in ("가격 > 100만원", "3 < 5 비교", "A&B 비교", "100% 확인", "맥북 vs 갤럭시북", "a<b 비교"):
            self.assertEqual(make(topic=fine).topic, fine)

    def test_a_keyword_needs_at_least_one_letter_or_digit(self):
        for bad in ("?!", "---", "    ", "…"):
            with self.subTest(bad=bad):
                refuses(self, "CANDIDATE_INVALID", make, keyword=bad)
        self.assertEqual(make(keyword="C++").keyword, "C++")
        self.assertEqual(make(keyword="7").keyword, "7")

    def test_sub_keywords_are_distinct_words_that_differ_from_the_core_keyword(self):
        self.assertEqual(make(sub_keywords=["가", "나"]).sub_keywords, ("가", "나"))
        words = tuple(f"보조{index}" for index in range(MAX_SUB_KEYWORDS))
        self.assertEqual(make(sub_keywords=words).sub_keywords, words)
        refuses(self, "CANDIDATE_INVALID", make, sub_keywords=words + ("하나 더",))
        for bad in (("보일러 점검",), ("보일러점검",), ("보일러  점검",), ("가", "가"), ("Abc", "aBC"), ("보일러 에러", "보일러에러"), ("",), ("?!",), "문자열 하나", "가나다", (5,), 5, ("가" * (MAX_KEYWORD + 1),)):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, sub_keywords=bad)

    def test_blogs_are_one_or_more_distinct_known_platforms_and_keep_the_order_given(self):
        self.assertEqual(PLATFORMS, ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"))
        self.assertEqual(make(blogs=PLATFORMS).blogs, PLATFORMS)
        self.assertEqual(make(blogs=["naver_b", "naver_a"]).blogs, ("naver_b", "naver_a"))
        for platform in PLATFORMS:
            self.assertEqual(make(blogs=(platform,)).blogs, (platform,))
        for bad in ((), [], ("naver_c",), ("naver_a", "naver_a"), "naver_a", ("NAVER_A",), (5,), ("naver_a", None), None, 5, PLATFORMS + ("naver_a",)):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, blogs=bad)

    def test_the_post_type_is_one_of_the_five_and_shares_the_profile_list(self):
        self.assertIs(cand.POST_TYPES, profiles.POST_TYPES)
        self.assertEqual(profiles.POST_TYPES, ("정보형", "비교형", "문제 해결형", "제품·서비스 소개형", "장소·업체 정보형"))
        for kind in profiles.POST_TYPES:
            self.assertEqual(make(post_type=kind).post_type, kind)
        for bad in ("경험형 후기", "후기", "", "정보형 ", "info", None, 5):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, post_type=bad)

    def test_counts_are_whole_numbers_in_range(self):
        for field, high in (("search_demand", MAX_SEARCH_DEMAND), ("related_blog_results", MAX_RELATED_RESULTS)):
            for good in (0, 1, high):
                with self.subTest(field=field, good=good):
                    self.assertEqual(getattr(make(**{field: good, "data_date": DAY}), field), good)
            for bad in (-1, high + 1, True, False, 1.5, 3.0, "10", [1], float("nan"), float("inf"), 10 ** 400):
                with self.subTest(field=field, bad=repr(bad)[:20]):
                    refuses(self, "CANDIDATE_INVALID", make, **{field: bad, "data_date": DAY})

    def test_scores_and_the_mobile_share_are_numbers_from_0_to_100(self):
        for field in ("mobile_share", "profile_fit", "priority", "keyword_opportunity"):
            for good in (0, 0.0, 0.5, 50, 99.9, 100, 100.0):
                with self.subTest(field=field, good=good):
                    self.assertEqual(getattr(make(**{field: good, "data_date": DAY}), field), good)
            for bad in (-0.1, -1, 100.1, 101, True, False, "50", [50], float("nan"), float("inf"), float("-inf"), 10 ** 400, -10 ** 400):
                with self.subTest(field=field, bad=repr(bad)[:20]):
                    refuses(self, "CANDIDATE_INVALID", make, **{field: bad, "data_date": DAY})

    def test_the_trend_is_up_flat_or_down(self):
        self.assertEqual(TRENDS, ("상승", "보합", "하락"))
        for good in TRENDS:
            self.assertEqual(make(trend=good, data_date=DAY).trend, good)
        for bad in ("올라감", "", "UP", "상승 ", 1, True, ["상승"]):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, trend=bad, data_date=DAY)

    def test_seasonality_is_a_set_of_months_kept_in_calendar_order(self):
        self.assertEqual(make(seasonality=[12, 1, 2], data_date=DAY).seasonality, (1, 2, 12))
        self.assertEqual(make(seasonality=range(1, 13), data_date=DAY).seasonality, tuple(range(1, 13)))
        self.assertEqual(make(seasonality=(6,), data_date=DAY).seasonality, (6,))
        for bad in ((), [], (0,), (13,), (1, 1), (1.5,), (True,), ("1",), "123", 5, (1, None), tuple(range(1, 14))):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, seasonality=bad, data_date=DAY)

    def test_the_duplicate_flag_is_yes_no_or_unknown(self):
        for good in (True, False):
            self.assertIs(make(duplicate=good, data_date=DAY).duplicate, good)
        self.assertIsNone(make().duplicate)
        for bad in (0, 1, "예", "True", [], 0.0):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, duplicate=bad, data_date=DAY)

    def test_every_metric_can_be_left_out_and_any_one_alone_needs_the_date(self):
        self.assertEqual(set(SAMPLES), set(METRIC_FIELDS))
        for field, value in SAMPLES.items():
            with self.subTest(field=field):
                alone = make(**{field: value, "data_date": DAY})
                self.assertTrue(alone.has_data())
                self.assertEqual([name for name in METRIC_FIELDS if getattr(alone, name) is not None], [field])
                error = refuses(self, "CANDIDATE_INVALID", make, **{field: value})
                self.assertEqual(error.slots["항목"], LABELS["data_date"])
        self.assertEqual(make(data_date=DAY).data_date, DAY, "지표가 없어도 조회일만 있을 수 있다(조회했지만 데이터가 없음)")
        everything = make(data_date=DAY, **SAMPLES)
        self.assertEqual([getattr(everything, name) for name in METRIC_FIELDS], [SAMPLES[name] for name in METRIC_FIELDS])

    def test_the_data_date_is_a_real_calendar_day_from_2000_on(self):
        for good in ("2026-11-02", "2000-01-01", "2024-02-29", "2099-12-31"):
            self.assertEqual(make(data_date=good).data_date, good)
        for bad in ("2026-02-29", "2026-13-01", "2026-00-10", "2026-11-31", "1999-12-31", "2026-1-2", "26-11-02", "2026/11/02", "2026-11-02 ", " 2026-11-02", "2026-11-02\n",
                    "２０２６-11-02", "٢٠٢٦-١١-٠٢", "2026-11-02T00:00:00Z", "", 20261102, 5, ["2026-11-02"]):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, data_date=bad)

    def test_times_are_real_utc_stamps_from_2000_on(self):
        for field in ("created_at", "updated_at"):
            for bad in ("", "2026-11-02", "2026-11-02T03:00:00", "2026-11-02T03:00:00+09:00", "2026-11-02 03:00:00Z", "2026-02-30T00:00:00Z", "2026-11-02T24:00:00Z",
                        "2026-11-02T23:60:00Z", "2026-11-02T03:00:00Z\n", "1999-12-31T23:59:59Z", "２０２６-11-02T03:00:00Z", None, 5):
                with self.subTest(field=field, bad=repr(bad)):
                    kwargs = {"candidate_id": "c1", "topic": "t", "keyword": "k", "blogs": ("naver_a",), "created_at": NOW, "updated_at": NOW, field: bad}
                    refuses(self, "CANDIDATE_INVALID", Candidate, **kwargs)
        self.assertEqual(parse_stamp("2026-11-02T03:04:05Z").second, 5)
        self.assertEqual(parse_stamp("2000-01-01T00:00:00Z").year, 2000)
        refuses(self, "CANDIDATE_INVALID", parse_stamp, "2026-11-02T03:04:05Z ")
        refuses(self, "CANDIDATE_INVALID", make, now="어제")

    def test_the_revision_is_a_positive_whole_number_and_the_project_link_a_plain_token(self):
        for bad in (0, -1, True, 1.0, "1", None):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", dataclasses.replace, make(), revision=bad)
        for bad in ("", "a b", "../x", "a\n", 5, "x" * 65):
            with self.subTest(bad=repr(bad)):
                refuses(self, "CANDIDATE_INVALID", make, project_id=bad)
        self.assertEqual(make(project_id="p-1_x").project_id, "p-1_x")
        self.assertEqual(make(status="NEW", project_id="p1").status, "NEW", "연결과 상태는 따로다 — 연결이 있다고 상태가 강제되지 않는다")

    def test_a_candidate_cannot_be_changed_after_it_is_made(self):
        item = make()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            item.status = "SELECTED"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            item.keyword = "다른 키워드"
        self.assertEqual(item, make())
        self.assertEqual(hash(item), hash(make()))
        self.assertEqual(hash(make(**FULL)), hash(make(**FULL)))


class EditTest(unittest.TestCase):
    def test_editing_makes_a_new_candidate_with_a_higher_revision(self):
        item = make()
        edited = item.edited(search_demand=500, data_date=DAY, reason="찾는 사람이 늘었습니다.", now=LATER)
        self.assertEqual((edited.search_demand, edited.data_date, edited.reason, edited.revision, edited.updated_at, edited.created_at), (500, DAY, "찾는 사람이 늘었습니다.", 2, LATER, NOW))
        self.assertEqual((item.search_demand, item.revision), (None, 1), "원래 후보는 그대로다")

    def test_editing_nothing_or_the_same_values_returns_the_same_candidate_without_a_new_revision(self):
        item = make(**FULL)
        self.assertIs(item.edited(), item)
        self.assertIs(item.edited(topic=item.topic, priority=item.priority, now=LATER), item)

    def test_the_fixed_fields_cannot_be_edited_here(self):
        for name, value in (("candidate_id", "x"), ("status", "SELECTED"), ("selections", (("naver_a", NOW),)), ("revision", 9), ("created_at", LATER), ("updated_at", LATER), ("schema", 1), ("nope", 1)):
            with self.subTest(name=name):
                refuses(self, "CANDIDATE_INVALID", make().edited, **{name: value})

    def test_an_edit_is_checked_like_a_new_candidate(self):
        item = make(**FULL)
        refuses(self, "CANDIDATE_INVALID", item.edited, priority=101)
        refuses(self, "CANDIDATE_INVALID", item.edited, reason="수익 보장")
        refuses(self, "CANDIDATE_INVALID", item.edited, data_date=None)           # 지표가 남아 있는데 조회일만 지울 수는 없다
        self.assertIsNone(item.edited(data_date=None, **{name: None for name in METRIC_FIELDS}).data_date, "지표를 모두 지우면 조회일도 지울 수 있다")

    def test_editing_keeps_the_status_the_choice_record_and_the_creation_time(self):
        picked = make(**FULL).moved("SELECTED", blog="naver_b", now=LATER)
        edited = picked.edited(priority=10, now="2026-11-05T00:00:00Z")
        self.assertEqual((edited.status, edited.selections, edited.created_at, edited.candidate_id), (picked.status, picked.selections, picked.created_at, picked.candidate_id))
        self.assertEqual((edited.revision, edited.updated_at, edited.priority), (picked.revision + 1, "2026-11-05T00:00:00Z", 10))

    def test_the_project_link_can_be_set_and_cleared_by_editing(self):
        linked = make().edited(project_id="p1", now=LATER)
        self.assertEqual((linked.project_id, linked.revision), ("p1", 2))
        self.assertIsNone(linked.edited(project_id=None).project_id)


class ExpressionRuleTest(unittest.TestCase):
    BANNED = ("상위노출 보장", "상위 노출 보장", "상위노출을 보장합니다", "상위 노출을 100% 보장", "상위노출 확정", "상위노출 장담", "노출 확률", "노출확률이 높음", "노출될 확률", "상위노출 가능성",
              "검색 노출 가능성이 높다", "검색 1위 가능성", "검색1위가능성", "1위 보장", "1위 확률이 높다", "수익 보장", "수익을 보장합니다", "월 수익 100% 보장", "수익 장담", "수익률 보장")
    ODD_SPACES = ("ＳＥＯ 상위노출\u3000보장", "상위\u00a0노출 보장", "상위\u2009노출\u2009보장")      # 다른 종류의 공백·전각 글자 — 찾는 쪽은 잡고, 글칸은 공백이 달라서 먼저 거절한다
    FINE = ("키워드 기회도가 높습니다", "콘텐츠 작성 우선도: 높음", "블로그 프로필 적합도 82", "최근 관심도 변화: 상승", "관련 블로그 검색 결과 수 3,450건", "개인정보 노출 가능성 점검 방법",
            "암보험 보장 범위 비교", "수익 구조 이해하기", "노출 빈도 줄이는 법", "1위 업체 후기 정리", "최소 보장 금액 알아보기", "상위 노출 방법 공부", "검색 결과 정리")

    def test_the_four_forbidden_kinds_of_claims_are_found_however_they_are_spaced_or_inflected(self):
        for text in self.BANNED:
            with self.subTest(text=text):
                self.assertIsNotNone(find_forbidden_claim(text))
                self.assertIsNotNone(find_forbidden_claim(f"앞말 {text} 뒷말"))

    def test_claims_with_unusual_spaces_or_full_width_letters_are_found_too(self):
        for text in self.ODD_SPACES:
            with self.subTest(text=text):
                self.assertIsNotNone(find_forbidden_claim(text))
                refuses(self, "CANDIDATE_INVALID", make, reason=text)

    def test_ordinary_sentences_and_the_allowed_names_are_not_claims(self):
        for text in self.FINE + ALLOWED_TERMS:
            with self.subTest(text=text):
                self.assertIsNone(find_forbidden_claim(text))
        self.assertIsNone(find_forbidden_claim(""))

    def test_a_claim_is_refused_in_every_text_field(self):
        for text in self.BANNED:
            for field in ("topic", "keyword", "reason"):
                with self.subTest(field=field, text=text):
                    error = refuses(self, "CANDIDATE_INVALID", make, **{field: text})
                    self.assertEqual(error.slots["항목"], LABELS[field])
                    self.assertIn("쓸 수 없는 표현", error.detail)
            with self.subTest(field="sub_keywords", text=text):
                refuses(self, "CANDIDATE_INVALID", make, sub_keywords=("정상", text))
        for text in self.FINE:
            self.assertEqual(make(reason=text).reason, text)
            self.assertEqual(make(topic=text).topic, text)

    def test_a_claim_cannot_be_smuggled_in_by_editing(self):
        refuses(self, "CANDIDATE_INVALID", make().edited, topic="이 방법은 상위노출 보장")
        refuses(self, "CANDIDATE_INVALID", make().edited, sub_keywords=("검색 1위 가능성",))

    def test_the_claim_check_works_on_the_text_without_spaces_or_punctuation(self):
        self.assertEqual(find_forbidden_claim("상위 노출을 100% 보장"), "상위노출을100보장")
        self.assertEqual(find_forbidden_claim("노출 확률"), "노출확률")

    def test_the_metric_names_are_the_allowed_wording_and_make_no_promises(self):
        shown = {name: LABELS[name] for name in ("keyword_opportunity", "priority", "profile_fit", "trend", "related_blog_results")}
        self.assertEqual(shown, {"keyword_opportunity": "키워드 기회도", "priority": "콘텐츠 작성 우선도", "profile_fit": "블로그 프로필 적합도", "trend": "최근 관심도 변화",
                                 "related_blog_results": "관련 블로그 검색 결과 수"})
        self.assertEqual(set(shown.values()), set(ALLOWED_TERMS))
        for name, label in LABELS.items():
            with self.subTest(label=name):
                self.assertIsNone(find_forbidden_claim(label))
                self.assertTrue(label and label == label.strip() and "\n" not in label)
                for word in ("보장", "확률", "가능성", "1위", "상위노출"):
                    self.assertNotIn(word, label)

    def test_every_displayed_field_has_a_label_and_nothing_else_does(self):
        internal = {"selections", "project_id", "revision", "created_at", "updated_at"}
        self.assertEqual(set(LABELS), {item.name for item in dataclasses.fields(Candidate)} - internal)
        self.assertTrue(set(METRIC_FIELDS) <= set(LABELS))
        self.assertEqual(len(set(LABELS.values())), len(LABELS), "이름이 서로 다르다")


class KeywordKeyTest(unittest.TestCase):
    def test_spacing_case_width_and_punctuation_do_not_make_a_different_keyword(self):
        key = keyword_key("보일러 점검")
        for same in ("보일러점검", "보일러  점검", " 보일러 점검 ", "보일러-점검", "보일러·점검!", "보일러\u3000점검"):
            self.assertEqual(keyword_key(same), key, same)
        self.assertEqual(keyword_key("iPhone 15"), keyword_key("ＩＰＨＯＮＥ１５"))
        self.assertEqual(keyword_key("Mac Book"), keyword_key("macbook"))
        self.assertNotEqual(keyword_key("보일러 점검"), keyword_key("보일러 수리"))
        self.assertNotEqual(keyword_key("a1"), keyword_key("a2"))

    def test_text_without_letters_or_digits_gives_an_empty_key(self):
        for text in ("", "   ", "?!", "---", "…"):
            self.assertEqual(keyword_key(text), "", text)
        self.assertEqual(keyword_key("한 글 2"), "한글2")


class JsonShapeTest(unittest.TestCase):
    KEYS = ["schema", "candidate_id", "topic", "keyword", "sub_keywords", "blogs", "post_type", "search_demand", "related_blog_results", "trend", "mobile_share", "seasonality",
            "duplicate", "profile_fit", "priority", "keyword_opportunity", "reason", "data_date", "status", "selections", "project_id", "revision", "created_at", "updated_at"]

    def full(self):
        return make(project_id="p1", status="REVIEW", **FULL).moved("SELECTED", blog="naver_a", now=LATER)

    def test_the_stored_shape_has_exactly_the_documented_fields_and_every_field_is_stored(self):
        data = make().to_dict()
        self.assertEqual(sorted(data), sorted(self.KEYS))
        self.assertEqual(set(data), {item.name for item in dataclasses.fields(Candidate)} | {"schema"}, "칸을 더하고 저장 모양을 빠뜨리지 않았는가")
        self.assertEqual(data["schema"], 1)

    def test_a_full_candidate_survives_the_trip_through_json_text(self):
        item = self.full()
        data = item.to_dict()
        self.assertEqual(data["selections"], {"naver_a": LATER})
        self.assertEqual(data["blogs"], ["naver_a", "naver_b", "github_pages"])
        self.assertEqual(data["seasonality"], [1, 2, 11, 12])
        text = json.dumps(data, ensure_ascii=False)
        back = Candidate.from_dict(json.loads(text))
        self.assertEqual(back, item)
        self.assertEqual(back.to_dict(), data)
        self.assertIsNot(back, item)
        self.assertIsNot(data["blogs"], item.blogs)

    def test_a_minimal_candidate_round_trips_and_keeps_missing_metrics_missing(self):
        item = make()
        data = item.to_dict()
        self.assertTrue(all(data[name] is None for name in METRIC_FIELDS))
        self.assertEqual(Candidate.from_dict(json.loads(json.dumps(data))), item)

    def test_numbers_keep_their_kind_through_json(self):
        item = make(mobile_share=72.5, priority=76, profile_fit=0, data_date=DAY)
        back = Candidate.from_dict(json.loads(json.dumps(item.to_dict())))
        self.assertEqual((back.mobile_share, back.priority, back.profile_fit), (72.5, 76, 0))
        self.assertIsInstance(back.priority, int)
        self.assertIsInstance(back.mobile_share, float)

    def test_only_the_required_fields_may_be_missing_so_older_data_still_reads(self):
        data = make().to_dict()
        required = {"schema", "candidate_id", "topic", "keyword", "blogs", "status", "revision", "created_at", "updated_at"}
        stripped = {name: value for name, value in data.items() if name in required}
        self.assertEqual(Candidate.from_dict(stripped), make())
        for name in sorted(required):
            with self.subTest(missing=name):
                refuses(self, "CANDIDATE_INVALID", Candidate.from_dict, {key: value for key, value in data.items() if key != name})

    def test_unknown_or_malformed_stored_data_is_refused_not_repaired(self):
        data = make().to_dict()
        wrong_type = {"blogs": "naver_a", "sub_keywords": "가나다", "seasonality": "123", "selections": "x", "revision": "1", "status": 5, "trend": 5, "duplicate": "yes", "post_type": None,
                      "search_demand": "10", "priority": "high", "topic": 5, "keyword": None, "reason": 5, "data_date": 20261101, "candidate_id": 5, "created_at": 5, "project_id": 5}
        bad = {"비밀 칸": {**data, "비밀": "x"}, "schema 없음": {key: value for key, value in data.items() if key != "schema"}, "schema 0": {**data, "schema": 0},
               "schema 2": {**data, "schema": 2}, "schema 참": {**data, "schema": True}, "schema 소수": {**data, "schema": 1.0}, "schema 글": {**data, "schema": "1"},
               "목록": [], "글": "text", "없음": None, "숫자": 5, "빈 사전": {}}
        bad.update({f"{name} 모양 틀림": {**data, name: value} for name, value in wrong_type.items()})
        for name, value in bad.items():
            with self.subTest(name):
                refuses(self, "CANDIDATE_INVALID", Candidate.from_dict, value)

    def test_inner_values_are_checked_when_reading_too(self):
        data = make(**FULL).to_dict()
        for name, value in (("topic", "수익 보장 방법"), ("blogs", ["naver_c"]), ("blogs", []), ("search_demand", -5), ("mobile_share", 101), ("data_date", None), ("created_at", "어제"),
                            ("selections", {"naver_c": NOW}), ("selections", {"naver_a": "어제"}), ("seasonality", [13]), ("status", "DRAFTING"), ("revision", 0)):
            with self.subTest(name=name, value=repr(value)):
                refuses(self, "CANDIDATE_INVALID", Candidate.from_dict, {**data, name: value})

    def test_the_stored_shape_has_no_secrets(self):
        text = repr(self.full().to_dict()).lower()
        for needle in ("password", "token", "cookie", "secret", "session", "api_key"):
            self.assertNotIn(needle, text)

    def test_the_module_describes_itself_in_plain_wording(self):
        # 값이 아니라 문서 문구가 규칙을 어기지 않는지 — 소스 안의 라벨 표에 약속하는 말이 없다
        source = (ROOT / "src" / "chanceblog_desktop" / "content" / "candidates.py").read_text(encoding="utf-8")
        table = source[source.index("LABELS = {"):source.index("ALLOWED_TERMS")]
        self.assertFalse(re.search(r"보장|확률|가능성|상위노출", table), "라벨 표에 약속하는 말이 있다")


class ClaimListsTest(unittest.TestCase):
    """표현 금지 규칙 — 거절 목록(영어·한자·변형 낱말·전각·NFD·구두점 끼움)과 통과 목록(부정·경계하는 글·보통 낱말이 먼 곳에 흩어진 글). 둘 다 규칙을 바꿀 때 먼저 읽는 '정의' 다."""

    REFUSED = (
        # 상위노출 보장 계열 — 보장·보증·약속·확정·장담·책임
        "상위노출 보장", "상위 노출 보장", "상위노출을 보장합니다", "상위 노출을 100% 보장", "상위노출 확정", "상위노출 장담", "상위노출 보증", "상위노출 약속", "상위노출 책임집니다",
        "상위노출 보장해드립니다", "상위노출을 100% 책임집니다", "상위 노출 100% 보증", "검색 상위노출 약속드립니다", "블로그 상위노출 100% 보장", "네이버 상위노출 보장",
        "상위노출보장", "상위노출 보장합니다 문의 주세요",
        # 노출·순위·첫 페이지 보장
        "노출 보장", "노출을 보장합니다", "노출 보증", "노출을 장담", "순위 보장", "순위를 보장해 드립니다", "검색 순위 보장", "상위 랭킹 보장", "첫 페이지 보장", "첫페이지 노출 보장",
        "1페이지 보장", "상단 노출 보장", "탑 노출 보장", "메인 노출 보장", "최상위 노출 보장", "검색 결과 1페이지 보장", "첫 페이지 노출 책임",
        # 앞쪽 단정 표현
        "무조건 상위노출", "100% 상위노출", "확실한 상위노출", "보장 상위노출 서비스",
        # 노출 확률·가능성
        "노출 확률", "노출확률이 높음", "노출될 확률", "상위노출 가능성", "상위노출 확률 높이기", "검색 노출 가능성이 높다", "상위노출 가능합니다", "상위노출 가능", "블로그 노출 가능성",
        "노출 확률 높이는 법",
        # 검색 1위
        "검색 1위 가능성", "검색1위가능성", "1위 보장", "1위 확률이 높다", "1위 달성", "1위 달성 가능", "1위 가능", "1위를 약속", "1등 보장", "검색 1등 보장", "일위 보장", "네이버 1위 보장",
        "1 위 보장",
        # 수익
        "수익 보장", "수익을 보장합니다", "월 수익 100% 보장", "수익 장담", "수익률 보장", "수익 확정", "수익 보증", "수익 약속", "수익창출을 확약", "수익 창출 보장", "수익 100% 보장 블로그 부업",
        "블로그 수익 보장 강의", "위험 없는 수익 보장", "원금 손실 위험 없이 수익 보장",
        # 영어(영문 블로그용 후보)
        "Guaranteed #1 ranking on Google", "guaranteed top ranking", "rank #1 guaranteed", "guaranteed income", "100% profit guaranteed", "No.1 guaranteed", "Top 1 ranking chance",
        "exposure probability", "guaranteed first page of Google", "We guarantee page one rankings", "guaranteed traffic and rankings", "earnings guaranteed", "Guaranteed Top 10 Results",
        "guaranteed SERP position", "Ranking guarantee", "guarantee #1 spot on search", "100% guaranteed rankings", "Our SEO guarantees first page results", "guaranteed profit blog",
        "income guaranteed from blogging", "Guaranteed ranking improvement",
        # 한자·영어 섞기
        "上位노출 보장", "상위露出 보장", "상위노출 保障", "上位露出 保障", "노출 確率", "수익 保障", "SEO 상위노출 guarantee", "收益 保障", "상위노출 保證", "상위노출 約束", "상위노출 確定",
        "상위노출 可能", "상위노출 可能性", "사기업 상위노출 보장",
        # 전각·로마 숫자·동그라미 숫자·구두점 끼움
        "ＳＥＯ 상위노출 보장", "１위 가능성", "Ⅰ위 가능성", "①위 보장", "상.위.노.출.보.장", "상위노출(보장)", "상위-노출-보장", "상위노출/보장", "Ｇｕａｒａｎｔｅｅｄ ＃１ ranking",
    )
    # 눈에 안 보이는 글자·다른 종류의 공백을 끼운 것 — 찾는 쪽(`find_forbidden_claim`)은 잡고, 글칸은 '한 줄' 규칙이 먼저 거절한다
    HIDDEN_VARIANTS = ("ＳＥＯ 상위노출" + chr(0x3000) + "보장", "상위" + chr(0x200B) + "노출 보장", "수익" + chr(0x200D) + "보장", "노" + chr(0x2060) + "출 확률", "상위" + chr(0xA0) + "노출 보장",
                       "상위" + chr(0x2009) + "노출" + chr(0x2009) + "보장", "검색" + chr(0xFEFF) + "1위 가능성")
    ACCEPTED = (
        # 부정 — 약속하지 않는다는 말
        "상위노출을 보장하지 않습니다", "수익을 보장하지 않습니다", "순위를 보장하지 않는 이유", "노출은 보장되지 않습니다", "상위노출 보장은 불가능합니다", "1위 보장은 불가능", "수익 보장할 수 없는 이유",
        "검색 순위는 보장할 수 없습니다", "상위노출 보장 못 합니다", "상위노출 보장 안 합니다", "수익 보장 없이 시작하는 부업", "노출 보장 없는 광고 상품",
        "상위노출 보장은 하지는 않습니다", "상위노출 보장할 수는 없습니다", "상위노출 보장할 수가 없어요", "상위노출 보장 안 해요", "상위노출 보장은 어렵습니다", "상위노출 보장이 아닙니다",
        "수익 보장은 아니고 참고용입니다", "수익 보장이 안 돼요", "수익 보장도 안 됩니다",
        # 그런 약속을 경계하는 글
        "상위노출 보장 업체 피하는 법", "상위노출 보장 광고에 속지 않는 법", "수익 보장 상품의 위험성", "상위노출 보장은 사기일까?", "순위 보장 마케팅 주의사항", "수익 보장 문구에 속지 마세요",
        "상위노출 보장 피해 사례", "상위노출 보장에 속는 사람들", "상위노출 보장에 속아서 손해 본 후기", "상위노출 보장으로 속이는 업체", "상위노출 보장 허위 광고", "상위노출 보장 과장 광고 구별법",
        "상위노출 보장 함정 조심", "상위노출 보장 주의하세요", "상위노출 보장 주의할 점", "상위노출 보장 주의해야 하는 이유", "상위노출 보장 주의점", "상위노출 보장 믿어도 될까",
        "상위노출 보장 믿을 수 있을까", "상위노출 보장 낚시 광고", "상위노출 보장은 거짓말", "사기 상위노출 보장",
        # 먼 낱말을 짝지으면 걸리던 보통 글(예전 규칙의 8자 창)
        "보험 수익자 지정과 보장 범위", "연금보험 수익 구조와 보장 한도 비교", "광고 수익 구조와 보장 한도", "대선 1위 후보의 당선 확률", "1위 후보 확률 분석", "피부 노출 시 감염 확률",
        "방사선 노출 후 암 발생 확률", "암보험 보장 범위 비교", "수익 구조 이해하기", "노출 빈도 줄이는 법", "1위 업체 후기 정리", "최소 보장 금액 알아보기", "상위 노출 방법 공부",
        "검색 결과 정리", "개인정보 노출 가능성 점검 방법", "보험 보장 순위 비교", "수익형 블로그 보장 소득 vs 변동 소득", "보장 보험 수익 계산기", "보장 범위 넓은 실손보험 비교",
        "수익을 내는 블로그 운영법", "1위 기업 분석", "구글 검색 순위 확인하는 방법", "순위 추적 도구 비교", "자본주의 수익 구조 분석", "민주주의 수익 모델", "사기업 수익 구조와 보장 한도",
        "코스피 순위 변동 분석", "1등급 한우 고르는 법", "노출 시간 줄이는 방법", "상위권 대학 입시 전략", "확정 수익이 아닌 예상 수익 계산", "리그 순위 확정 경기 일정", "연봉 순위 비교",
        "SEO 기초 가이드", "겨울철 보일러 점검 방법",
        # 지표 이름(허용된 표현)
        "키워드 기회도가 높습니다", "콘텐츠 작성 우선도: 높음", "블로그 프로필 적합도 82", "최근 관심도 변화: 상승", "관련 블로그 검색 결과 수 3,450건",
        # 영어
        "how search ranking algorithms work", "income tax guide for freelancers", "profit margin calculator", "warranty guarantee period explained", "money back guarantee policy", "page rank explained",
        "top 10 laptops of 2026", "ranking factors for local SEO", "exposure therapy for anxiety", "We do not guarantee rankings", "rankings are not guaranteed", "no guarantee of income",
        "why nobody can guarantee first page results", "probability and statistics basics", "Search ranking guarantee: myth or reality", "How to avoid SEO companies that guarantee rankings",
        "guaranteed rankings are a red flag", "Guarantee page speed score", "ranking changes after a core update", "top 3 mistakes in blogging",
    )
    REFUSED += (
        # 보장류 낱말·조사·숫자·접두 낱말을 하나씩
        "상위노출 확약합니다", "1페이지 노출 책임", "메인 노출 확정", "상단 노출 장담", "최상단 노출 책임", "검색 순위 책임", "상위 순위 확정", "상위 랭킹 책임", "상위권 노출 확정", "검색 노출 확정",
        "상위노출 guaranteed", "상위노출 GUARANTEE", "랭크 보장", "일페이지 보장", "첫 화면 보장", "최상단 보장", "최상위 보장", "일등 보장", "상위노출 99% 보장", "상위노출 100퍼센트 보장",
        "상위노출 100프로 보장", "보장형 상위노출", "보증된 상위노출", "보장하는 상위노출", "100퍼센트 상위노출", "백 프로 상위노출", "100% 검색 1위", "반드시 1위", "확실히 검색 1위",
        "무조건적으로 상위노출", "상위노출이 가능합니다",
        # 노출 확률·가능성 — 앞에 붙는 낱말과 조사
        "포털 노출 가능성", "네이버 노출 가능성", "구글 노출 가능성", "첫페이지 노출 가능성", "메인 노출 가능성", "상단 노출 가능성", "노출되는 확률", "노출할 확률", "노출하는 확률", "노출의 확률",
        # 영어 — 낱말·짝·수익·확률
        "Our plan guarantees rankings", "guaranteeing top ranking", "guaranteed ranked first", "guaranteed revenue", "guaranteed profits", "guaranteed page one", "guaranteed page 1",
        "guaranteed number one", "guaranteed no 1", "guaranteed top 1", "guaranteed 1 spot", "guaranteed 1 position", "guaranteed 1 result", "guaranteed 1 results", "guaranteed one spot",
        "guaranteed top spot", "guaranteed top result", "guaranteed top results", "guaranteed top position", "guaranteed top 3", "guaranteed top 5", "guaranteed top 10", "guaranteed top ten",
        "ranking chances", "ranking likelihood", "ranking odds", "exposure chance", "serp probability", "SEO guaranteed ranks", "guaranteed traffic",
    )
    REFUSED += (
        # 낱말 하나씩 — 규칙에서 그 낱말만 빼도 걸리지 않게 되는 말(변이 점검이 확인한다)
        "상단노출 확정", "랭킹 보장", "검색랭크 보장", "상위랭크 보장", "보장된 검색 1위", "보증 검색1위", "노출 guaranteed", "순위 guarantee",
        "상위노출을 가능하게 합니다", "상위노출될 가능성이 높습니다", "상위노출되는 가능성이 높습니다", "상위노출할 가능성이 큽니다", "상위노출하는 가능성을 높이는 법", "상위노출의 가능성이 높습니다",
        "상위노출되는 확률이 높습니다", "상위노출하는 확률을 높이는 법",
        "글의 노출이 확률에 달려 있습니다", "노출을 확률로 계산합니다",
    )
    ACCEPTED += (
        "상위노출 보장의 함정", "상위노출 보장 업체 조심하세요",                  # 경계 표지 낱말 하나씩(함정·조심) — 다른 표지 없이도 지나간다
    )
    ACCEPTED += (
        "1100% 상위노출 키워드", "시험 2100 상위노출 사례",
        # 영어 부정·경계 표지 낱말을 하나씩
        "rankings never guaranteed", "without guaranteed income", "neither ranking nor income is guaranteed", "impossible to guarantee rankings", "can't guarantee rankings", "nobody guarantees rankings",
        "no guarantee ranking", "Beware of guaranteed rankings", "guaranteed income is a scam", "scams that promise guaranteed income", "fake guaranteed rankings", "SEO fraud: guaranteed rankings",
        "misleading guaranteed income claims", "guaranteed income lies", "guaranteed rankings lie", "myths about guaranteed rankings", "red flags: guaranteed rankings", "avoid guaranteed rankings",
        "scam: guaranteed income", "scams about guaranteed income", "myth: guaranteed rankings", "flag guaranteed rankings",
        "상위노출 보장하지도 않습니다", "상위노출 보장하지를 않습니다", "상위노출은 보장되지는 않습니다", "상위노출은 보장되지도 않습니다",
        "we cannot guarantee rankings", "neither guaranteed rankings", "guaranteed income nor rankings",
    )
    # 알려진 한계 — 규칙의 '표현 자체' 를 금지하므로 보통 글에도 걸린다(운영자가 말을 바꿔 쓴다). 바뀌면 일부러 바꾼 것이어야 한다.
    OVER_BLOCKED = ("월드컵 1위 가능성 분석", "광고 노출 확률 높이는 법", "상위노출 가능성 점검 도구", "SEO 상위노출 가능성 높이는 법", "수익 보장 상품 비교")

    def test_the_lists_are_big_enough_to_mean_something(self):
        self.assertGreaterEqual(len(self.REFUSED), 100)
        self.assertGreaterEqual(len(self.ACCEPTED), 60)
        self.assertEqual(len(set(self.REFUSED)), len(self.REFUSED))
        self.assertEqual(len(set(self.ACCEPTED)), len(self.ACCEPTED))
        self.assertFalse(set(self.REFUSED) & set(self.ACCEPTED))

    def test_every_refused_phrase_is_found_and_refused_in_the_topic_the_reason_and_the_sub_keywords(self):
        nfd = (unicodedata.normalize("NFD", "상위노출 보장"), unicodedata.normalize("NFD", "수익을 보장합니다"), unicodedata.normalize("NFD", "검색 1위 가능성"))
        for text in self.REFUSED + nfd:
            with self.subTest(text=text):
                self.assertIsNotNone(find_forbidden_claim(text))
                self.assertIsNotNone(find_forbidden_claim(f"앞말 {text} 뒷말"), "앞뒤에 다른 말이 붙어도 찾는다")
                for field in ("topic", "reason"):
                    error = refuses(self, "CANDIDATE_INVALID", make, **{field: text})
                    self.assertEqual(error.slots["항목"], LABELS[field])
                    self.assertIn("약속하는 표현", error.rendered().message)
                refuses(self, "CANDIDATE_INVALID", make, sub_keywords=("정상", text))

    def test_claims_with_hidden_characters_or_odd_spaces_are_found_and_the_field_refuses_them_either_way(self):
        for text in self.HIDDEN_VARIANTS:
            with self.subTest(text=repr(text)):
                self.assertIsNotNone(find_forbidden_claim(text))
                for field in ("topic", "keyword", "reason"):
                    refuses(self, "CANDIDATE_INVALID", make, **{field: text})

    def test_every_accepted_phrase_goes_through_everywhere_text_goes(self):
        for text in self.ACCEPTED + ALLOWED_TERMS:
            with self.subTest(text=text):
                self.assertIsNone(find_forbidden_claim(text))
                self.assertEqual(make(topic=text).topic, text)
                self.assertEqual(make(reason=text).reason, text)
                if len(text) <= MAX_KEYWORD:
                    self.assertEqual(make(keyword=text).keyword, text)
                    self.assertEqual(make(sub_keywords=(text,)).sub_keywords, (text,))

    def test_the_known_limits_are_pinned_so_a_change_is_deliberate(self):
        for text in self.OVER_BLOCKED:
            with self.subTest(text=text):
                self.assertIsNotNone(find_forbidden_claim(text))

    def test_the_text_is_decomposed_and_widened_before_looking_so_ways_of_writing_it_do_not_matter(self):
        for text in (unicodedata.normalize("NFD", "상위노출 보장"), "ＳＥＯ 상위노출 보장", "１위 가능성", "Ｇｕａｒａｎｔｅｅｄ ＃１ ranking"):
            with self.subTest(text=text):
                self.assertIsNotNone(find_forbidden_claim(text))
        self.assertNotEqual(unicodedata.normalize("NFD", "상위노출 보장"), "상위노출 보장")

    def test_the_claim_is_named_in_plain_words_in_the_message_the_user_reads(self):
        for text, label in (("상위노출 보장", "상위노출 보장"), ("노출 확률", "노출 확률·가능성"), ("검색 1위 가능성", "검색 1위 보장·가능성"), ("수익 보장", "수익 보장"),
                            ("순위 보장", "노출·순위 보장"), ("guaranteed income", "순위·수익 보장"), ("exposure probability", "노출·순위 확률")):
            with self.subTest(text=text):
                self.assertEqual(forbidden_claim(text)[0], label)
                error = refuses(self, "CANDIDATE_INVALID", make, reason=text)
                self.assertIn(f"‘{label}’ 같은 결과를 약속하는 표현은 쓸 수 없습니다", error.rendered().message)
                self.assertIn("추천 이유", error.rendered().message)
                self.assertNotIn("원고", error.rendered().message)
                self.assertIn("쓸 수 없는 표현", error.detail)

    PINNED = (
        # (글, 규칙 이름, 잡은 말(띄어쓰기를 지운 모양))
        ("상위노출 보장", "상위노출 보장", "상위노출보장"), ("최상단 노출 책임", "상위노출 보장", "최상단노출책임"), ("상단 노출 확정", "상위노출 보장", "상단노출확정"),
        ("검색랭킹 보장", "노출·순위 보장", "검색랭킹보장"), ("상위 랭크 보장", "노출·순위 보장", "상위랭크보장"), ("랭킹 보장", "노출·순위 보장", "랭킹보장"), ("노출 보장", "노출·순위 보장", "노출보장"),
        ("상위노출 가능성", "노출 확률·가능성", "상위노출가능성"), ("상위노출 확률", "노출 확률·가능성", "상위노출확률"), ("노출 확률", "노출 확률·가능성", "노출확률"),
        ("검색 1위 가능성", "검색 1위 보장·가능성", "검색1위가능성"), ("검색 1위 확률", "검색 1위 보장·가능성", "검색1위확률"), ("1위 달성", "검색 1위 보장·가능성", "1위달성"),
        ("수익 보장", "수익 보장", "수익보장"), ("수익률 확정", "수익 보장", "수익률확정"),
        ("보장된 검색 1위", "상위노출 보장", "보장된검색1위"), ("100% 검색 1위", "상위노출 보장", "100검색1위"), ("무조건 상위노출", "상위노출 보장", "무조건상위노출"),
        # 한자 — 한 글자라도 한글로 바꾸지 못하면 다른 규칙에 걸려 이름이 달라진다
        ("上位露出保障", "상위노출 보장", "상위노출보장"), ("상위노출 可能性", "노출 확률·가능성", "상위노출가능성"), ("上위노출 보장", "상위노출 보장", "상위노출보장"),
        ("상위노출 確率", "노출 확률·가능성", "상위노출확률"), ("收益 保障", "수익 보장", "수익보장"), ("상위노출 保證", "상위노출 보장", "상위노출보증"), ("상위노출 約束", "상위노출 보장", "상위노출약속"),
        ("상위노출 確定", "상위노출 보장", "상위노출확정"),
    )

    def test_the_found_phrase_and_the_rule_name_are_pinned_phrase_by_phrase(self):
        """어느 규칙이 어떤 말을 잡았는지까지 — 낱말 하나를 규칙에서 빼도 같은 글이 다른 규칙에 걸려 '거절' 은 그대로일 수 있어, 이름·잡은 말을 같이 못 박는다."""
        for text, label, found in self.PINNED:
            with self.subTest(text=text):
                self.assertEqual(forbidden_claim(text), (label, found))
                self.assertEqual(find_forbidden_claim(text), found)
                error = refuses(self, "CANDIDATE_INVALID", make, reason=text)
                self.assertIn(f"‘{label}’ 같은 결과를 약속하는 표현은 쓸 수 없습니다", error.rendered().message)
                self.assertEqual(error.detail, f"쓸 수 없는 표현: {found}")

    def test_the_rules_look_at_words_that_are_next_to_each_other_not_words_that_merely_share_a_sentence(self):
        for text in ("수익 구조와 방법 그리고 보장 범위", "노출 시간과 확률 계산", "1위 업체와 확률 이야기", "상위 노출 방법 말고 다른 보장 이야기"):
            with self.subTest(text=text):
                self.assertIsNone(find_forbidden_claim(text))

    def test_every_particle_that_may_sit_between_two_words_still_counts_as_next_to_each_other(self):
        for particle in ("을", "를", "이", "가", "은", "는", "도", "만", "으로", "로", "의"):
            for stem, tail in (("상위노출", "보장"), ("순위", "보증"), ("1위", "약속"), ("수익", "장담"), ("검색 1위", "달성")):
                with self.subTest(particle=particle, stem=stem):
                    self.assertIsNotNone(find_forbidden_claim(f"{stem}{particle} {tail}"))
        for gap in ("에 대한", "관련 모든", "시 감염", "의 모든 것과"):
            with self.subTest(gap=gap):
                self.assertIsNone(find_forbidden_claim(f"상위노출{gap} 보장"), "조사 하나보다 긴 말이 끼면 바로 이어진 것이 아니다")

    def test_the_english_windows_have_exact_edges(self):
        filler = lambda count: " ".join(["word"] * count)
        # 보장하는 말과 순위 말 사이: 뒤로는 낱말 3개까지, 앞으로도 3개까지
        self.assertIsNotNone(find_forbidden_claim(f"guaranteed {filler(3)} ranking"))
        self.assertIsNone(find_forbidden_claim(f"guaranteed {filler(4)} ranking"))
        self.assertIsNotNone(find_forbidden_claim(f"ranking {filler(3)} guaranteed"))
        self.assertIsNone(find_forbidden_claim(f"ranking {filler(4)} guaranteed"))
        self.assertIsNotNone(find_forbidden_claim(f"guaranteed {filler(2)} top spot"))
        self.assertIsNone(find_forbidden_claim(f"guaranteed {filler(3)} top spot"), "두 낱말짜리 말은 한 칸 일찍 끝난다")
        # 부정은 보장하는 말 앞뒤 3낱말 안에 있어야 면해 준다
        self.assertIsNone(find_forbidden_claim(f"not {filler(2)} guaranteed income"))
        self.assertIsNotNone(find_forbidden_claim(f"not {filler(3)} guaranteed income"))
        self.assertIsNone(find_forbidden_claim("guaranteed income not"))
        self.assertIsNone(find_forbidden_claim("guaranteed income is not real"), "뒤로도 3낱말까지")
        self.assertIsNotNone(find_forbidden_claim("guaranteed income is really not real"), "뒤로 4낱말째의 부정은 면해 주지 못한다")
        # 확률 말은 순위 말 뒤 낱말 2개 안, 부정은 앞 4낱말 안
        self.assertIsNotNone(find_forbidden_claim("ranking chance"))
        self.assertIsNotNone(find_forbidden_claim(f"ranking {filler(2)} chance"))
        self.assertIsNone(find_forbidden_claim(f"ranking {filler(3)} chance"))
        self.assertIsNone(find_forbidden_claim("not ranking chance"))
        self.assertIsNone(find_forbidden_claim(f"not {filler(2)} ranking chance"), "확률 말의 부정은 앞 4낱말까지")
        self.assertIsNotNone(find_forbidden_claim(f"not {filler(3)} ranking chance"))
        self.assertIsNone(find_forbidden_claim("chance ranking"), "확률 말이 순위 말 앞에 오면 아니다")

    def test_each_english_clause_boundary_stops_a_negation(self):
        for boundary in (".", ";", "!", "?", "but", "however", "yet", "although", "though"):
            with self.subTest(boundary=boundary):
                self.assertIsNotNone(find_forbidden_claim(f"rankings are not guaranteed {boundary} guaranteed income"))
        for glued in ("Rankings are not guaranteed.  Guaranteed income", "Rankings are not guaranteed;guaranteed income", "Rankings are not guaranteed!guaranteed income"):
            with self.subTest(glued=glued):
                self.assertIsNotNone(find_forbidden_claim(glued))
        self.assertIsNotNone(find_forbidden_claim("No.1 guaranteed"), "No.1 의 점은 문장 끝이 아니다")
        self.assertIsNotNone(find_forbidden_claim("SEO services: guaranteed rankings"), "쌍점(:)은 절을 나누지 않는다 — 제목에 흔하다")

    def test_both_roman_numeral_one_signs_count_as_the_number_one(self):
        for sign in (chr(0x2160), chr(0x2170), chr(0x2460), chr(0xFF11)):                           # Ⅰ  ⅰ  ①  １
            with self.subTest(sign=sign):
                self.assertIsNotNone(find_forbidden_claim(sign + "위 가능성"))
                self.assertIsNotNone(find_forbidden_claim("검색 " + sign + "위 보장"))

    def test_an_english_negation_does_not_leak_into_the_next_sentence_or_clause(self):
        for text in ("Rankings are not guaranteed. Guaranteed income!", "Rankings are not guaranteed; guaranteed income", "No guarantee of ranking however guaranteed income",
                     "Not guaranteed income yet guaranteed income", "Rankings are not guaranteed but guaranteed income", "We cannot guarantee anything! guaranteed #1 ranking", "No.1 guaranteed"):
            with self.subTest(text=text):
                self.assertIsNotNone(find_forbidden_claim(text))
        for text in ("Rankings are not guaranteed. Income tax guide", "no guaranteed income", "We do not guarantee rankings, income or traffic", "never guaranteed top ranking"):
            with self.subTest(text=text):
                self.assertIsNone(find_forbidden_claim(text))

    def test_english_claims_are_found_only_inside_one_clause(self):
        self.assertIsNotNone(find_forbidden_claim("SEO services: guaranteed rankings"))
        self.assertIsNone(find_forbidden_claim("Our rankings improved. We guarantee delivery"), "순위 이야기와 보장 이야기가 다른 문장이면 짝짓지 않는다")
        self.assertIsNone(find_forbidden_claim("Ranking factors but we guarantee delivery times"))

    def test_a_negation_only_excuses_the_claim_it_follows(self):
        self.assertIsNone(find_forbidden_claim("상위노출을 보장하지 않습니다"))
        self.assertIsNotNone(find_forbidden_claim("상위노출을 보장하지 않습니다. 하지만 수익 보장"))
        self.assertIsNotNone(find_forbidden_claim("수익 보장! 상위노출을 보장하지 않습니다"))
        self.assertIsNotNone(find_forbidden_claim("rankings are not guaranteed but guaranteed income"))


class MarkupRuleTest(unittest.TestCase):
    """원시 HTML·스크립트·템플릿 표기 — 위험한 것은 거절하고, 제네릭·부등호·`JavaScript: 제목` 같은 보통 글은 통과한다."""

    REFUSED = (
        "<b>굵게</b>", "<script>x</script>", "<script", "<SCRIPT>alert(1)", "</script>", "x<script>", "<!-- 주석 -->", "<!DOCTYPE html>", "<?php echo 1; ?>", "<![CDATA[x]]>", "<br/>", "<br>", "</p>",
        "<p class=a>", "<div>글</div>", "<a href=x>링크</a>", "<A HREF=\"x\">", "<span style=x>", "<h1>제목</h1>", "<img src=x onerror=alert(1)>", "<img", "<iframe src=x>", "<style>", "<form action=x>",
        "<object data=x>", "<embed src=x>", "<link rel=x>", "<meta http-equiv=x>", "<svg onload=x>", "<input onfocus=x>", "<button>", "<textarea>", "<video src=x>", "<body>", "<html>",
        "text onclick=alert(1)", "x onerror = y", "onload=run()", "onmouseover=x", "<x onclick=1>",
        "javascript:alert(1)", "JavaScript:x", "JAVASCRIPT:void(0)", "javascript :x", "vbscript:msgbox(1)", "data:text/html,<b>x</b>", "data:image/png;base64,AAAA", "Data:x",
        "{{ 값 }}", "{{", "}}", "{% if x %}", "{%", "%}", "{# 메모 #}", "{#", "#}", "닫는 %}", "}} 뒤", "앞 #}",
    )
    ACCEPTED = (
        "JavaScript: 비동기 처리 정리", "JavaScript: The Good Parts 리뷰", "TypeScript vs JavaScript: 무엇을 쓸까", "Map<String, List<Integer>> 사용법", "List<int> 와 Array<string> 비교", "Vector<T> 정리",
        "Dictionary<string, int> 쓰는 법", "Pair<A, B> 만들기", "Optional<User> 반환하기", "<3 마음", "a<b 비교", "x < y 이고 y > z", "3 < 5 비교", "가격 > 100만원", "A&B 비교", "100% 확인",
        "맥북 vs 갤럭시북", "C# vs C++ 성능 비교", "data: 1,2,3 형식", "Metadata: 정리", "Data: 공공데이터 활용", "online=true 옵션 설명", "onion=양파 이야기", "once=1 설정", "online 강의 정리",
        "if (a < b && c > d)", "5 > 3 > 1", "화살표 -> 와 => 쓰기", "이메일 <받는사람> 형식", "{x} 같은 중괄호", "{1,2,3} 집합 표기", "함수 f(x) = {x}", "해시태그 #블로그 #SEO",
        "퍼센트 % 기호", "100%% 이스케이프", "template 이란", "script 라는 낱말", "style 가이드", "link 걸기", "form 작성법", "img 태그 설명 없는 글", "object 지향", "embed 영상 넣는 법", "svg 아이콘 만들기",
        "linkedin 프로필 쓰기", "formatting 규칙", "scripting 입문", "stylesheet 정리",
        # 낱말 한가운데의 data: · on…= 는 주소·이벤트 속성이 아니다(낱말 경계)
        "Metadata:정리", "seasonchange=2 옵션",
    )

    def test_the_lists_are_big_enough_to_mean_something(self):
        self.assertGreaterEqual(len(self.REFUSED), 40)
        self.assertGreaterEqual(len(self.ACCEPTED), 40)

    def test_every_refused_trace_is_found_by_find_markup_and_refused_in_every_text_field(self):
        for trace in self.REFUSED:
            with self.subTest(trace=trace):
                self.assertTrue(find_markup(trace), "사유 문장이 돌아온다")
                for field in ("topic", "reason"):
                    error = refuses(self, "CANDIDATE_INVALID", make, **{field: trace})
                    self.assertEqual(error.slots["항목"], LABELS[field])
                    self.assertIn("쓸 수 없습니다", error.rendered().message)
                refuses(self, "CANDIDATE_INVALID", make, sub_keywords=(trace,))
                if len(trace) <= MAX_KEYWORD and keyword_key(trace):
                    refuses(self, "CANDIDATE_INVALID", make, keyword=trace)

    def test_every_accepted_text_goes_through(self):
        for text in self.ACCEPTED:
            with self.subTest(text=text):
                self.assertIsNone(find_markup(text))
                self.assertEqual(make(topic=text).topic, text)
                self.assertEqual(make(reason=text).reason, text)

    DANGEROUS = ("script", "iframe", "img", "style", "form", "object", "embed", "link", "meta", "svg", "base", "frame", "frameset", "applet", "input", "textarea", "button", "select", "option",
                 "body", "html", "head", "title", "math", "template", "video", "audio", "source", "track", "canvas", "portal", "dialog", "noscript", "xml", "marquee")
    PLAIN = ("a", "abbr", "b", "big", "blockquote", "br", "center", "cite", "code", "dd", "del", "dfn", "div", "dl", "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "ins", "kbd", "li",
             "mark", "nav", "ol", "p", "pre", "q", "s", "samp", "section", "small", "span", "strike", "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "tt", "u",
             "ul", "var", "wbr", "article", "aside", "footer", "header", "main", "figure", "figcaption", "details", "summary", "label", "fieldset", "legend", "caption", "col", "colgroup",
             "hgroup", "address", "bdi", "bdo", "data", "dir", "menu", "nobr", "rb", "rp", "rt", "ruby", "time", "xmp")
    EVENTS = ("abort", "animationend", "auxclick", "beforeunload", "blur", "cancel", "canplay", "change", "click", "close", "contextmenu", "copy", "cut", "dblclick", "drag", "dragend", "drop",
              "durationchange", "emptied", "ended", "error", "focus", "focusin", "hashchange", "input", "invalid", "keydown", "keyup", "load", "loadeddata", "message", "mousedown", "mouseover",
              "pagehide", "paste", "pause", "play", "playing", "pointerdown", "popstate", "progress", "ratechange", "readystatechange", "reset", "resize", "scroll", "search", "seeked", "select",
              "selectstart", "show", "stalled", "storage", "submit", "suspend", "timeupdate", "toggle", "touchstart", "transitionend", "unload", "volumechange", "waiting", "wheel")

    def test_every_dangerous_tag_name_is_refused_with_or_without_a_closing_bracket_and_the_list_is_pinned(self):
        from chanceblog_desktop.content import profiles as profile_module
        self.assertEqual(profile_module._DANGEROUS_TAGS, self.DANGEROUS)
        for name in self.DANGEROUS:
            for text in (f"<{name}>", f"<{name} x=1>", f"</{name}>", f"<{name.upper()}", f"앞<{name} 뒤"):
                with self.subTest(text=text):
                    self.assertEqual(find_markup(text), "HTML 태그는 쓸 수 없습니다")
            self.assertIsNone(find_markup(f"{name} 라는 낱말"), name)
            self.assertIsNone(find_markup(f"<{name}x>"), f"<{name}x> 는 다른 낱말이다")

    def test_every_plain_tag_name_is_refused_only_when_the_tag_is_closed_and_the_list_is_pinned(self):
        from chanceblog_desktop.content import profiles as profile_module
        names = set(self.PLAIN)
        for name in names:
            for text in (f"<{name}>", f"<{name} class=x>", f"</{name}>", f"<{name}/>", f"<{name.upper()}>"):
                with self.subTest(text=text):
                    self.assertEqual(find_markup(text), "HTML 태그는 쓸 수 없습니다")
            self.assertIsNone(find_markup(f"a<{name} 뒤"), f"닫히지 않은 <{name} 는 부등호 글이다")
        written = {name for name in self.PLAIN} | {f"h{n}" for n in range(1, 7)}
        self.assertEqual({name for name in profile_module._PLAIN_TAGS if "[" not in name} | {f"h{n}" for n in range(1, 7)}, written, "소스의 목록과 이 시험의 목록이 같다")

    def test_every_event_attribute_family_is_refused_when_followed_by_an_equals_sign(self):
        for name in self.EVENTS:
            for text in (f"x on{name}=y", f"on{name.upper()} = y", f"on{name}=alert(1)"):
                with self.subTest(text=text):
                    self.assertEqual(find_markup(text), "onclick= 같은 이벤트 속성은 쓸 수 없습니다")
            self.assertIsNone(find_markup(f"on{name} 이라는 이름"), name)
        for fine in ("online=true", "onion=1", "once=2", "only=3", "onto=4", "ongoing=5", "onset=6"):
            with self.subTest(fine=fine):
                self.assertIsNone(find_markup(fine))

    def test_the_closing_braces_alone_are_refused_each_one_on_its_own(self):
        """닫는 표기만 있는 글도 템플릿을 깨뜨릴 수 있다 — 여는 표기와 따로 시험한다."""
        for closing_only in ("}}", "%}", "#}", "앞 }} 뒤", "앞 %} 뒤", "앞 #} 뒤"):
            with self.subTest(closing_only=closing_only):
                self.assertEqual(find_markup(closing_only), "{% · {{ 같은 템플릿 표기는 쓸 수 없습니다")
                refuses(self, "CANDIDATE_INVALID", make, topic=closing_only)

    def test_the_reason_says_what_kind_of_thing_was_found(self):
        for text, reason in (("<b>x</b>", "HTML 태그는 쓸 수 없습니다"), ("a onclick=x", "onclick= 같은 이벤트 속성은 쓸 수 없습니다"), ("javascript:alert(1)", "javascript: 같은 스크립트 주소는 쓸 수 없습니다"),
                             ("{% x %}", "{% · {{ 같은 템플릿 표기는 쓸 수 없습니다")):
            with self.subTest(text=text):
                self.assertEqual(find_markup(text), reason)
                self.assertIn(reason, refuses(self, "CANDIDATE_INVALID", make, topic=text).rendered().message)

    def test_a_colon_followed_by_a_space_is_a_title_not_an_address(self):
        self.assertIsNone(find_markup("JavaScript: 비동기"))
        self.assertIsNone(find_markup("javascript: "))
        self.assertIsNotNone(find_markup("javascript:alert"))
        self.assertIsNotNone(find_markup("javascript:"+"x"))


class InvisibleCharsTest(unittest.TestCase):
    """눈에 보이지 않거나 빈칸·깨진 글자처럼 보이는 글자는 고쳐 받지 않고 거절한다(주제·키워드·보조 키워드·추천 이유 모두)."""

    HIDDEN = {"이모지 변형 선택자 U+FE0F": chr(0xFE0F), "변형 선택자 U+FE00": chr(0xFE00), "변형 선택자 U+FE0E": chr(0xFE0E), "몽골 변형 선택자 U+180B": chr(0x180B), "몽골 변형 선택자 U+180C": chr(0x180C),
              "몽골 변형 선택자 U+180D": chr(0x180D), "개체 대체 문자 U+FFFC": chr(0xFFFC), "깨진 글자 표시 U+FFFD": chr(0xFFFD),
              "한글 채움 U+3164": chr(0x3164), "한글 채움 U+FFA0": chr(0xFFA0), "점자 빈칸 U+2800": chr(0x2800), "결합 문자 이음 U+034F": chr(0x34F), "한글 초성 채움 U+115F": chr(0x115F),
              "크메르 U+17B4": chr(0x17B4), "크메르 U+17B5": chr(0x17B5), "한글 중성 채움 U+1160": chr(0x1160), "몽골 변형 선택자 U+180F": chr(0x180F)}

    def test_each_hidden_or_broken_character_is_refused_in_every_text_field(self):
        for label, char in self.HIDDEN.items():
            with self.subTest(label):
                for field in ("topic", "keyword", "reason"):
                    refuses(self, "CANDIDATE_INVALID", make, **{field: f"가나{char}다라"})
                    refuses(self, "CANDIDATE_INVALID", make, **{field: f"가나다라{char}"})
                refuses(self, "CANDIDATE_INVALID", make, sub_keywords=(f"가{char}나",))

    def test_stacked_or_stray_combining_marks_are_refused_but_one_accent_is_fine(self):
        grave, acute, circumflex, tilde = chr(0x300), chr(0x301), chr(0x302), chr(0x303)
        top = chr(0x36F)
        for text in (f"e{grave}{acute}{circumflex}", f"a{grave}{grave}{grave}b", f"가 {grave}나", f"{grave}가나", f"가{tilde}{acute}{grave}{circumflex}", f"a{top}{top}{top}b", f"가 {top}나", f"{top}가나"):
            with self.subTest(text=text):
                refuses(self, "CANDIDATE_INVALID", make, topic=text)
        for fine in (f"Cre{chr(0x300)}me", f"cafe{acute} 추천", f"a{grave}{acute} 두 개까지는", "정상적인 한국어 주제"):
            with self.subTest(fine=fine):
                self.assertEqual(make(topic=fine).topic, fine)

    def test_emoji_without_a_variation_selector_and_ordinary_symbols_are_fine(self):
        for fine in ("\N{FIRE} 핫딜 모음", "별 \N{BLACK STAR} 표시", "수학 \N{PLUS-MINUS SIGN} 기호", "한자 漢字 섞기"):
            with self.subTest(fine=fine):
                self.assertEqual(make(topic=fine).topic, fine)
        refuses(self, "CANDIDATE_INVALID", make, topic="\N{BLACK HEART SUIT}" + chr(0xFE0F) + " 하트")

    def test_the_reason_says_the_text_has_characters_that_cannot_be_seen(self):
        error = refuses(self, "CANDIDATE_INVALID", make, topic=f"가{chr(0xFFFD)}나")
        self.assertIn("눈에 보이지 않거나", error.rendered().message)
        error = refuses(self, "CANDIDATE_INVALID", make, topic=f"가 {chr(0x300)}나")
        self.assertIn("결합 문자", error.rendered().message)


class MessageTest(unittest.TestCase):
    """거절 문구 — 원고용이 아니라 후보 전용이고, 어느 칸이 왜 안 되는지 사용자가 읽는 문구에 있다."""

    CASES = (
        ({"topic": "가" * 201}, "추천 포스팅 주제", "200자 이하"), ({"keyword": "가" * 61}, "핵심 키워드", "60자 이하"), ({"reason": "가" * 301}, "추천 이유", "300자 이하"),
        ({"topic": ""}, "추천 포스팅 주제", "비워 둘 수 없고"), ({"topic": "줄\n바꿈"}, "추천 포스팅 주제", "한 줄"), ({"topic": 5}, "추천 포스팅 주제", "글이어야"), ({"keyword": "?!"}, "핵심 키워드", "글자나 숫자가 하나도 없습니다"),
        ({"sub_keywords": ("보일러 점검",)}, "보조 키워드", "핵심 키워드나 다른 보조 키워드와 같습니다"), ({"sub_keywords": tuple(f"w{n}" for n in range(21))}, "보조 키워드", "20개까지"),
        ({"sub_keywords": {"가": 1}}, "보조 키워드", "목록"), ({"blogs": ("naver_c",)}, "추천 대상 블로그", "naver_a"), ({"blogs": {"naver_a"}}, "추천 대상 블로그", "목록"),
        ({"post_type": "후기"}, "추천 글 유형", "정보형"), ({"search_demand": -1}, "월간 검색 수요", "1,000,000,000"), ({"related_blog_results": True}, "관련 블로그 검색 결과 수", "정수"),
        ({"trend": "올라감"}, "최근 관심도 변화", "상승, 보합, 하락"), ({"mobile_share": 101, "data_date": DAY}, "모바일 비중", "0~100"), ({"seasonality": (13,), "data_date": DAY}, "계절성", "1~12"),
        ({"duplicate": 1, "data_date": DAY}, "기존 글 중복 여부", "예·아니오"), ({"priority": 5}, "데이터 조회일", "조회일도 있어야"), ({"data_date": "2026-02-30"}, "데이터 조회일", "달력에 없는"),
        ({"data_date": "어제"}, "데이터 조회일", "2026-11-02 같은 모양"), ({"status": "DRAFTING"}, "상태", "새 후보, 검토 중, 선택됨, 보류, 제외"), ({"candidate_id": "a b"}, "후보 번호", "1~64자"),
        ({"project_id": "a b"}, "연결한 글 번호", "1~64자"), ({"revision": 0}, "판 번호", "1,000,000,000"), ({"created_at": "어제"}, "만든 시각", "2026-11-02T03:04:05Z 같은 모양"),
        ({"selections": (("naver_c", NOW),)}, "선택 기록", "블로그 구분"),
    )

    def test_each_rejected_value_says_which_field_and_why(self):
        for changes, field, reason in self.CASES:
            with self.subTest(field=field, reason=reason):
                if "revision" in changes or "created_at" in changes:                       # 이 두 칸은 `new` 가 아니라 이미 만든 후보를 고쳐서 시험한다
                    error = refuses(self, "CANDIDATE_INVALID", dataclasses.replace, make(), **changes)
                else:
                    error = refuses(self, "CANDIDATE_INVALID", make, **changes)
                shown = error.rendered()
                self.assertIn(f"주제 후보의 「{field}」", shown.message)
                self.assertIn(reason, shown.message)
                self.assertNotIn("원고", shown.message)
                self.assertNotIn("출처 주소", shown.action, "원고용 하실 일이 아니다")
                self.assertEqual(error.slots["항목"], field)

    def test_the_new_code_is_in_the_table_with_the_slots_the_code_fills(self):
        self.assertEqual(set(CATALOG["CANDIDATE_INVALID"].slots), {"항목", "이유"})
        self.assertEqual(CATALOG["CANDIDATE_INVALID"].retry_kind, "after_user")
        self.assertIn("`CANDIDATE_INVALID`", TROUBLE)
        self.assertIn("`CANDIDATE_CORRUPT`", TROUBLE)
        self.assertIn("쓸 수 없습니다", CATALOG["CANDIDATE_INVALID"].action)
        self.assertEqual(AppError("CANDIDATE_INVALID").rendered().message.count("알 수 없음"), 2, "값을 안 주면 자리표시자가 비었다고 알린다")

    def test_a_long_internal_number_is_shown_short(self):
        self.assertEqual(short_id("0123456789abcdef0123456789abcdef"), "01234567")
        self.assertEqual(short_id("c1"), "c1")
        self.assertEqual(short_id("12345678"), "12345678")
        self.assertEqual(short_id("123456789"), "12345678")
        self.assertEqual(SHORT_ID, 8)

    def test_the_status_name_function_says_why_an_unknown_state_is_refused(self):
        error = refuses(self, "CANDIDATE_INVALID", status_name, "NOPE")
        self.assertIn("아는 상태가 아닙니다", error.rendered().message)

    def test_an_edit_that_names_a_fixed_field_says_which_ones(self):
        error = refuses(self, "CANDIDATE_INVALID", make().edited, status="SELECTED", revision=9)
        self.assertIn("상태", error.rendered().message)
        self.assertIn("revision", error.rendered().message)


class LimitsTest(unittest.TestCase):
    """길이·개수·판 번호의 한계 — 시험이 상수를 불러다 쓰면 상수가 몰래 바뀌어도 따라가므로, 여기서는 **글자 그대로의 숫자** 로 경계를 지킨다."""

    def test_the_documented_limits_are_these_numbers(self):
        self.assertEqual((MAX_TOPIC, MAX_KEYWORD, MAX_REASON, MAX_SUB_KEYWORDS), (200, 60, 300, 20))
        self.assertEqual((MAX_SEARCH_DEMAND, MAX_RELATED_RESULTS, MAX_REVISION), (1_000_000_000, 10_000_000_000, 1_000_000_000))

    def test_the_topic_the_reason_and_the_keywords_stop_at_exactly_these_lengths(self):
        for field, limit in (("topic", 200), ("reason", 300), ("keyword", 60)):
            with self.subTest(field=field):
                self.assertEqual(len(getattr(make(**{field: "가" * limit}), field)), limit)
                refuses(self, "CANDIDATE_INVALID", make, **{field: "가" * (limit + 1)})
        self.assertEqual(len(make(sub_keywords=("나" * 60,)).sub_keywords[0]), 60)
        refuses(self, "CANDIDATE_INVALID", make, sub_keywords=("나" * 61,))

    def test_there_can_be_twenty_sub_keywords_but_not_twenty_one(self):
        self.assertEqual(len(make(sub_keywords=[f"보조{n}" for n in range(20)]).sub_keywords), 20)
        refuses(self, "CANDIDATE_INVALID", make, sub_keywords=[f"보조{n}" for n in range(21)])

    def test_the_counts_stop_at_exactly_these_numbers(self):
        self.assertEqual(make(search_demand=1_000_000_000, data_date=DAY).search_demand, 1_000_000_000)
        refuses(self, "CANDIDATE_INVALID", make, search_demand=1_000_000_001, data_date=DAY)
        self.assertEqual(make(related_blog_results=10_000_000_000, data_date=DAY).related_blog_results, 10_000_000_000)
        refuses(self, "CANDIDATE_INVALID", make, related_blog_results=10_000_000_001, data_date=DAY)

    def test_the_revision_has_an_upper_bound_and_going_past_it_is_an_app_error_not_an_overflow(self):
        top = dataclasses.replace(make(), revision=1_000_000_000)
        self.assertEqual(top.revision, 1_000_000_000)
        refuses(self, "CANDIDATE_INVALID", dataclasses.replace, make(), revision=1_000_000_001)
        refuses(self, "CANDIDATE_INVALID", dataclasses.replace, make(), revision=2 ** 63)
        refuses(self, "CANDIDATE_INVALID", top.edited, reason="한 번 더")
        refuses(self, "CANDIDATE_INVALID", top.moved, "REVIEW")
        refuses(self, "CANDIDATE_INVALID", Candidate.from_dict, {**make().to_dict(), "revision": 2 ** 70})

    def test_the_time_in_a_stamp_must_use_a_capital_z_and_digits(self):
        for bad in ("2026-11-02T03:00:00z", "2026-11-02t03:00:00Z", "2026-11-02T03:00:00 Z"):
            with self.subTest(bad=bad):
                refuses(self, "CANDIDATE_INVALID", parse_stamp, bad)
                refuses(self, "CANDIDATE_INVALID", make, now=bad)
        self.assertEqual(parse_stamp("2026-11-02T03:00:00Z").hour, 3)


class StricterShapeTest(unittest.TestCase):
    """검증이 낮음으로 짚은 것들 — 목록 모양·시각 순서·새 후보의 선택 기록·고르기와 재선택."""

    def test_blogs_and_sub_keywords_take_only_lists_and_tuples(self):
        for bad in ({"naver_a"}, frozenset({"naver_a"}), {"naver_a": 1}, (b for b in ("naver_a",)), iter(("naver_a",)), "naver_a", b"naver_a", range(1)):
            with self.subTest(blogs=repr(bad)[:30]):
                refuses(self, "CANDIDATE_INVALID", make, blogs=bad)
        for bad in ({"가"}, {"가": 1}, (w for w in ("가",)), iter(("가",)), "가", b"x"):
            with self.subTest(sub_keywords=repr(bad)[:30]):
                refuses(self, "CANDIDATE_INVALID", make, sub_keywords=bad)
        self.assertEqual(make(blogs=["naver_a"]).blogs, ("naver_a",))
        self.assertEqual(make(sub_keywords=["가"]).sub_keywords, ("가",))
        refuses(self, "CANDIDATE_INVALID", make, seasonality={1: 2}, data_date=DAY)

    def test_the_changed_time_cannot_be_before_the_made_time(self):
        refuses(self, "CANDIDATE_INVALID", Candidate, "c1", "주제", "키워드", ("naver_a",), created_at=LATER, updated_at=NOW)
        item = Candidate("c1", "주제", "키워드", ("naver_a",), created_at=NOW, updated_at=NOW)
        self.assertEqual(item.updated_at, NOW)
        refuses(self, "CANDIDATE_INVALID", item.edited, reason="새 이유", now="2026-11-02T02:59:59Z")
        refuses(self, "CANDIDATE_INVALID", item.moved, "REVIEW", now="2026-11-02T02:59:59Z")
        self.assertEqual(item.moved("REVIEW", now=NOW).updated_at, NOW, "같은 시각은 괜찮다")
        refuses(self, "CANDIDATE_INVALID", Candidate.from_dict, {**make().to_dict(), "updated_at": "2026-11-02T02:00:00Z"})

    def test_a_clock_that_went_backwards_does_not_make_the_changed_time_go_backwards(self):
        item = make().moved("REVIEW", now="2026-11-09T00:00:00Z")
        with mock.patch.object(cand, "utc_now", return_value="2026-11-03T00:00:00Z"):
            later = item.edited(reason="시계가 뒤로 간 PC 에서 고침")
        self.assertEqual(later.updated_at, "2026-11-09T00:00:00Z")
        with mock.patch.object(cand, "utc_now", return_value="2026-12-01T00:00:00Z"):
            self.assertEqual(item.moved("HOLD").updated_at, "2026-12-01T00:00:00Z")

    def test_a_new_candidate_cannot_carry_a_selection_record_but_every_other_state_can(self):
        refuses(self, "CANDIDATE_INVALID", make, status="NEW", selections=(("naver_a", NOW),))
        for status in ("REVIEW", "SELECTED", "HOLD", "REJECTED"):
            with self.subTest(status=status):
                self.assertEqual(make(status=status, selections=(("naver_a", NOW),)).selections, (("naver_a", NOW),))
        self.assertEqual(make(status="NEW").selections, ())
        error = refuses(self, "CANDIDATE_INVALID", Candidate.from_dict, {**make().to_dict(), "selections": {"naver_a": NOW}})
        self.assertIn("선택 기록", error.rendered().message)

    def test_choosing_again_after_a_hold_or_a_review_forgets_the_blogs_chosen_before_but_keeps_them_while_it_waits(self):
        both = make(blogs=("naver_a", "naver_b")).moved("SELECTED", now=NOW)
        self.assertEqual(both.selected_blogs, ("naver_a", "naver_b"))
        for waiting in ("HOLD", "REVIEW"):
            with self.subTest(waiting=waiting):
                parked = both.moved(waiting, now=LATER)
                self.assertEqual(parked.selected_blogs, ("naver_a", "naver_b"), "물려 있는 동안 기록은 남는다")
                again = parked.moved("SELECTED", blog="naver_a", now="2026-11-03T00:00:00Z")
                self.assertEqual(again.selections, (("naver_a", "2026-11-03T00:00:00Z"),), "다시 고른 블로그만 남는다")
                everything = parked.moved("SELECTED", now="2026-11-03T00:00:00Z")
                self.assertEqual(everything.selected_blogs, ("naver_a", "naver_b"))
        still = both.moved("SELECTED", blog="naver_a", now=LATER)
        self.assertEqual(still.selections, (("naver_a", LATER), ("naver_b", NOW)), "계속 선택됨이면 다른 블로그의 기록이 그대로다")


class KeywordKeyMeaningTest(unittest.TestCase):
    """키워드 열쇠가 뜻이 다른 키워드를 같다고 하지 않는다 — `+`·`#`·숫자 사이의 소수점은 남기고, 띄어쓰기·그 밖의 기호는 같은 키워드로 본다."""

    DIFFERENT = (("C++", "C#"), ("C++", "C"), ("C#", "C"), ("1.5", "15"), ("3.14", "314"), ("v1.2", "v12"), ("A+", "A"), ("금리 1.5%", "금리 15%"), ("2026.11", "202611"), ("12.3", "1.23"),
                 ("F#", "F"), ("C++20", "C20"), ("1+1", "11"), ("보일러 점검", "보일러 수리"))
    SAME = (("보일러 점검", "보일러-점검"), ("1,000", "1000"), ("A.I.", "AI"), ("Wi-Fi 6", "WiFi 6"), ("iPhone 15", "iphone15"), ("ＩＰＨＯＮＥ １５", "iPhone 15"), ("C++", "ｃ＋＋"), ("보일러·점검!", "보일러 점검"),
            ("e-mail", "email"), ("1.5", "１．５"))

    def test_different_keywords_have_different_keys(self):
        for left, right in self.DIFFERENT:
            with self.subTest(left=left, right=right):
                self.assertNotEqual(keyword_key(left), keyword_key(right))

    def test_the_same_keyword_written_differently_has_the_same_key(self):
        for left, right in self.SAME:
            with self.subTest(left=left, right=right):
                self.assertEqual(keyword_key(left), keyword_key(right))

    def test_a_key_made_only_of_symbols_is_empty_so_such_a_keyword_is_refused(self):
        for text in ("++", "#", "+#+", "...", "+", "...+"):
            self.assertEqual(keyword_key(text), "", text)
            refuses(self, "CANDIDATE_INVALID", make, keyword=text)
        self.assertEqual(keyword_key("."), "")
        self.assertEqual(keyword_key("a."), "a")
        self.assertEqual(keyword_key(".5"), "5")
        self.assertEqual(keyword_key("5."), "5")

    def test_a_dot_is_kept_only_when_a_digit_sits_on_both_sides_of_it(self):
        for text, key in (("a.5", "a5"), ("5.a", "5a"), ("v.2", "v2"), ("3.x", "3x"), ("a.b", "ab"), ("1.5", "1.5"), ("v1.2.3", "v1.2.3"), ("1..5", "15"), ("a1.2b", "a1.2b"), (".5.", "5")):
            with self.subTest(text=text):
                self.assertEqual(keyword_key(text), key)

    def test_c_plus_plus_and_c_sharp_can_be_the_core_and_a_sub_keyword_together(self):
        item = make(keyword="C++", sub_keywords=("C#", "C"))
        self.assertEqual((item.keyword, item.sub_keywords), ("C++", ("C#", "C")))
        refuses(self, "CANDIDATE_INVALID", make, keyword="C++", sub_keywords=("c＋＋",))
        refuses(self, "CANDIDATE_INVALID", make, keyword="1.5", sub_keywords=("１．５",))


if __name__ == "__main__":
    unittest.main()
