"""주제 후보 화면의 순수 부분 시험(PySide6 없이 돈다 — CI 와 같은 조건) — 카드·상세 글 규칙·거르기·찾기·정렬·개수 요약·상태(빈 화면 다섯)·선택(고정 ↔ 서랍)·후보 만들기 흐름(`CandidatesController`)·뷰모델·가짜 공급자.

지키는 것:
  1) **점수·구간은 홈과 같은 규칙이다** — 같은 점수(0~100 모두와 점수 없음)에서 홈의 추천 줄과 이 화면의 카드가 같은 점수 글·같은 구간 이름·같은 링 유무를 낸다. 새 점수·새 구간 규칙이 없다. 점수가 없으면 링 없이 `점수 계산 전`(0점이 아니다).
  2) 카드는 배지 **최대 둘**·키워드 칩 **최대 셋**(+N)·추천 이유 요약 **120자 이내**(가린 뒤에 줄인다). 상세는 같은 후보의 값을 있는 그대로 — 점수 구성은 엔진의 항목 점수 그대로이고 평가 못 한 항목은 `평가 전`(0 이 아니다).
  3) 관심도는 `최근 관심도(상대값)` 이고 월 검색량·상위노출·노출 확률 같은 말은 어느 문구·뷰모델에도 없다. 연결 안 된 데이터에는 `예시` 표시가 붙는다. 파이썬 목록·영문 값 이름·내부 번호가 글에 없다.
  4) 거르기·찾기·고르기·상세 열기·창 방식 바꾸기는 파일에 닿지 않고(실제 어댑터 시험은 `test_ui_candidates_service`), 선택은 상세 창 방식(고정 ↔ 서랍)이 바뀌어도 유지된다. 후보는 한 번에 24장만 그린다.
  5) **후보 만들기는 확인창이 먼저다**: 확인창을 보이지 않고 부르면 아무것도 하지 않고, 취소하면 표시를 거두며, 만드는 중에 또 눌러도 새로 시작하지 않는다. 만들 후보가 없으면 확인창도 쓰기 길도 없다. 실패하면 종류별 쉬운 문장이고 목록은 그대로다.
  6) 화면 코드(`ui/core`·`ui/qt`)에는 파일을 쓰는 호출이 없다. 실제 블로그 이름·후보 제목은 어디에도 없다 — 예시는 가짜 낱말뿐이다.
"""
import ast
import re
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.service import topics as topic_service  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import notice, safety  # noqa: E402
from chanceblog_desktop.topics.model import check_candidate_score  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.ui import candidates_adapter  # noqa: E402
from chanceblog_desktop.ui.core import board_view, candidate_rules as rules, candidate_text, candidates as cd, candidates_view as cv, gauges, jobs, services, text  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
T = text.T
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
FORBIDDEN_WORDS = ("월 검색량", "검색량", "상위노출", "노출 확률", "검색 1위", "수익 보장", "보장", "월간 검색")


def row_of(candidate, ordinal=1, stop=False):
    return cd.CandidateRow(ordinal, candidate, stop)


def data_of(*candidates, store="ready", channels=None, seeds=(), skipped=0, sample=False, stops=()):
    rows = tuple(cd.CandidateRow(number, item, number in stops) for number, item in enumerate(candidates, start=1))
    return cd.CandidatesData(rows, store, channels if channels is not None else cd._sample_channels(), tuple(seeds), skipped, len(rows) + skipped, sample)


class Scripted(cd.CandidatesProvider):
    """시험이 정한 값을 돌려주는 공급자 — `data`·`preview`·`outcome`, 정해 둔 실패(`fail`), 문을 열어 줄 때까지 기다리는 쓰기(`gate`)."""

    def __init__(self, data, preview=None, outcome=None, fail=None, gated=False):
        self.data, self.preview, self.outcome, self.fail = data, preview, outcome or cd.MakeOutcome(0), dict(fail or {})
        self.gate = threading.Event()
        self.gated = gated
        self.calls = []

    def _enter(self, name):
        self.calls.append(name)
        if self.gated and not self.gate.wait(30):
            raise AssertionError("시험이 문을 열어 주지 않았다")
        if name in self.fail:
            raise self.fail[name]

    def load_candidates(self, progress, cancelled):
        self._enter("load")
        return self.data

    def preview_make(self, progress, cancelled):
        self._enter("preview")
        return self.preview

    def make_candidates(self, preview, progress, cancelled):
        self._enter("make")
        return self.outcome


def preview_of(new=4, store="ready", lacks=(), proposed=0, used=2, channels=None):
    rows = channels if channels is not None else (cd.ChannelPreview("naver_a", "예시 블로그 가", new, 18, 20, 0, ("조합 제외",)),)
    return cd.MakePreview(store, rows, new, used, proposed, tuple(lacks), False)


def new_controller(provider=None, data=None):
    provider = provider or cd.FakeCandidatesProvider()
    controller = cv.CandidatesController(provider, jobs.JobRunner())
    controller.apply_loaded(data if data is not None else provider.load_candidates(SAFE, NEVER))
    return controller


def drive(controller, starter):
    """일을 시작하고 끝까지 기다려 결과를 받는다(셸이 하는 일과 같다). → (시작 상태, 끝난 일: 'ok'·'failed'·None)."""
    results = {}
    status, job = starter(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
    if status != "started":
        return status, None
    job.join(10)
    if "ok" in results:
        controller.apply_write_ok(results["ok"])
        return status, "ok"
    controller.apply_write_failed(results["failed"])
    return status, "failed"


NON_TEXT = ("id", "key", "kind", "tone", "state", "band", "icon", "preset")           # 글이 아니라 그림·상태·눌렀을 때 넘기는 열쇠를 고르는 값(`board_view` 의 `key`·`state` 와 같다)


def all_strings(value):
    """뷰모델 속 모든 글(딕셔너리 키는 빼고 값만). `id`·`key`·`state` 같은 칸은 글이 아니다."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in NON_TEXT:
                continue
            yield from all_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from all_strings(item)
    elif isinstance(value, str):
        yield value


# ---- 1) 점수·구간은 홈과 같다 ------------------------------------------------------------------------------------------------------------
class HomeParityTest(unittest.TestCase):
    def test_every_score_from_zero_to_a_hundred_and_no_score_get_the_same_text_band_and_ring_as_the_home_row(self):
        for score in (None, *range(0, 101)):
            candidate = ts.rated(score, candidate_id=f"cand-{score}") if score is not None else ts.make(candidate_id="cand-none")
            card_view = new_controller(data=data_of(candidate))._card(row_of(candidate), False)
            home = board_view.row_vm(services.RecommendRow("x", "제목", score, None, None), 1)
            with self.subTest(score=score):
                self.assertEqual((card_view["score"], card_view["ring"], card_view["band"], card_view["band_label"]), (home["score"], home["ring"], home["band"], home["band_label"]))
                self.assertEqual(card_view["score_text"], home["score_text"], "홈과 같은 글(점수 숫자 또는 `점수 계산 전`)")

    def test_the_band_borders_are_the_engines_eighty_sixty_five_fifty_and_the_names_are_the_homes(self):
        names = {79: "일반 후보", 80: "우선 추천", 64: "보류", 65: "일반 후보", 49: "제외", 50: "보류", 0: "제외", 100: "우선 추천"}
        for score, name in names.items():
            self.assertEqual(rules.band_name(rules.band_key(ts.rated(score, candidate_id=f"c{score}"))), name, score)
        self.assertEqual(rules.band_name("none"), "점수 계산 전")
        self.assertEqual(rules.BAND_KEYS, ("high", "good", "mid", "low", "none"))
        self.assertEqual(gauges.SCORE_CUTOFFS, tuple(ch.GRADE_CUTOFFS), "홈 링의 경계는 엔진의 경계 그대로다")

    def test_a_candidate_without_a_score_has_no_ring_says_score_not_calculated_and_is_not_counted_as_zero(self):
        candidate, zero_candidate = ts.make(candidate_id="cand-none", topic="예시 점수 없음 후보"), ts.rated(0, candidate_id="cand-zero", topic="예시 영점 후보")
        controller = new_controller(data=data_of(candidate, zero_candidate))
        cards = {item["title"]: item for item in controller.view()["grid"]["cards"]}
        none, zero = cards[candidate.topic], cards[zero_candidate.topic]
        self.assertEqual((none["ring"], none["score"], none["score_text"], none["band"]), (False, None, "점수 계산 전", None))
        self.assertEqual((zero["ring"], zero["score"], zero["band"], zero["band_label"]), (True, 0, "low", "제외"), "실제 0점은 링이 있는 '제외' 구간이다")
        self.assertIn("점수 계산 전", none["a11y"])
        self.assertNotIn("0점", none["a11y"])

    def test_a_card_reads_as_one_line_title_channel_score_and_band(self):
        candidate = ts.rated(92, candidate_id="cand-92")
        controller = new_controller(data=data_of(candidate))
        card_view = controller.view()["grid"]["cards"][0]
        self.assertEqual(card_view["a11y"], f"{candidate.topic}, {controller.channel_info('naver_b')['name']}, 점수 92점 우선 추천")

    def test_the_cards_of_the_samples_pass_the_engines_score_check_like_the_home_does(self):
        for item in cd.FakeCandidatesProvider().candidates:
            check_candidate_score(item, cd.PROFILES[item.channel])

    def test_the_fake_automatic_stop_flag_is_the_engines_own_pure_function(self):
        data = cd.FakeCandidatesProvider().load_candidates(SAFE, NEVER)
        stops = {row.candidate.topic for row in data.rows if row.stop}
        self.assertEqual(stops, {"예시 영양제 먹으면 바로 낫는 방법"})


# ---- 2) 규칙 ----------------------------------------------------------------------------------------------------------------------------
class RulesTest(unittest.TestCase):
    def test_the_screen_constants_are_pinned_by_hand_not_by_reading_them_back(self):
        self.assertEqual((rules.PAGE, rules.SUMMARY_MAX, rules.CHIPS_MAX, rules.BADGES_MAX, rules.TITLE_LIMIT, rules.CHIP_LIMIT), (24, 120, 3, 2, 200, 14))
        self.assertEqual(rules.PAGE % 2, 0)
        self.assertEqual(rules.PAGE % 3, 0, "3열·2열 모두 나누어떨어져 마지막 줄이 비지 않는다")
        self.assertEqual(rules.STATUS_KEYS, ("all", "NEW", "REVIEW", "SELECTED", "HOLD", "REJECTED"))

    def test_the_summary_is_at_most_one_hundred_twenty_characters_for_any_reason_lines(self):
        for lengths in ((10,), (60, 60), (120,), (121,), (300,), (50, 50, 50), (5, 5, 5, 5), (119, 3), (40, 80)):
            lines = tuple("가" * size for size in lengths)
            candidate = ts.make(selection_reasons=lines)
            shown = rules.summary(candidate)
            with self.subTest(lengths=lengths):
                self.assertLessEqual(len(shown), 120)
                self.assertTrue(shown.startswith("가" * min(lengths[0], 119)))
        self.assertEqual(rules.summary(ts.make(selection_reasons=())), "")

    def test_the_summary_is_the_first_whole_lines_that_fit_and_cuts_a_too_long_first_line_with_an_ellipsis(self):
        self.assertEqual(rules.summary(ts.make(selection_reasons=("가나다", "라마바"))), "가나다 · 라마바")
        self.assertEqual(rules.summary(ts.make(selection_reasons=("가" * 70, "나" * 70))), "가" * 70, "둘째 줄까지 넣으면 120자를 넘으니 첫 줄만")
        cut = rules.summary(ts.make(selection_reasons=("가" * 200,)))
        self.assertEqual((len(cut), cut[-1]), (120, "…"))

    def test_the_summary_drops_the_safety_notes_which_belong_to_the_safety_section(self):
        safe_line = notice.make("HEALTH_TOPIC", ("영양제",)).one_line()
        candidate = ts.make(selection_reasons=("씨앗에서 넓힌 후보예요", safe_line + "(걸린 말: 영양제)", "시기는 모름이에요"))
        self.assertEqual(rules.reason_lines(candidate), (["씨앗에서 넓힌 후보예요", "시기는 모름이에요"], [safe_line + "(걸린 말: 영양제)"]))
        self.assertNotIn("건강 정보 확인 필요", rules.summary(candidate))

    def test_a_key_shaped_text_is_masked_before_it_is_cut_in_the_summary_the_chips_and_the_card(self):
        candidate = ts.make(topic="예시 제목 " + KEY_SHAPED, primary_keyword=KEY_SHAPED, selection_reasons=("이유 " + KEY_SHAPED,), candidate_id="cand-key")
        controller = new_controller(data=data_of(candidate))
        card_view = controller.view()["grid"]["cards"][0]
        pieces = [card_view["title"], card_view["summary"], *card_view["keywords"], card_view["a11y"]]
        for piece in pieces:
            self.assertNotIn(KEY_SHAPED, piece)
            self.assertNotIn(KEY_SHAPED[:10], piece, "앞부분도 남지 않는다 — 가리기가 먼저, 자르기가 나중이다")
        controller.select("cand-key")
        shown = " ".join(all_strings(controller.detail_view()))
        self.assertNotIn(KEY_SHAPED[:10], shown)

    def test_the_keyword_chips_are_at_most_three_and_the_rest_is_a_plus_count(self):
        for total in range(1, 9):
            words = tuple(f"예시 낱말 {number}" for number in range(total))
            candidate = ts.make(primary_keyword=words[0], secondary_keywords=words[1:])
            chips, more = rules.keyword_chips(candidate)
            with self.subTest(total=total):
                self.assertEqual((len(chips), more), (min(total, 3), max(0, total - 3)))
                self.assertEqual(chips[0], words[0], "핵심 키워드가 먼저다")
        self.assertEqual(rules.keyword_chips(ts.make(primary_keyword="가" * 40))[0], ["가" * 13 + "…"])

    def test_a_card_has_at_most_two_badges_in_every_combination(self):
        candidate_for = lambda status: ts.make(candidate_id="cand-" + status, work_status=status)                       # noqa: E731
        warn = notice.make("HEALTH_TOPIC")
        for status in ("NEW", "REVIEW", "SELECTED", "HOLD", "REJECTED"):
            for stop in (False, True):
                for notices in ((), (warn,), (warn, notice.make("HEALTH_STOP"), notice.make("ECONOMIC_CHECK"))):
                    badges = rules.card_badges(candidate_for(status), stop, notices)
                    with self.subTest(status=status, stop=stop, notices=len(notices)):
                        self.assertLessEqual(len(badges), 2)
                        self.assertEqual(badges[0]["text"], rules.status_name(status))
                        self.assertEqual(len(badges), 2 if stop or notices else 1)
                        if stop:
                            self.assertEqual(badges[1]["text"], "자동 초안 중지", "중지가 주의보다 앞선다")
        self.assertEqual(rules.card_badges(candidate_for("NEW"), False, (notice.make("COLLAB_POSSIBLE"),)), [{"kind": "status", "tone": "info", "text": "새 후보"}], "참고(INFO) 안내만 있으면 주의 배지가 없다")

    def test_filters_keep_only_what_they_name_and_all_of_them_must_hold(self):
        a, b = ts.rated(90, candidate_id="c-a", channel="naver_a", cluster="local-ai", work_status="NEW"), ts.rated(70, candidate_id="c-b", channel="naver_b", cluster="pc-parts", work_status="SELECTED")
        rows = [row_of(a, 1), row_of(b, 2)]
        pick = lambda **kw: [row.candidate.candidate_id for row in rows if rules.matches(row, **kw)]                  # noqa: E731
        self.assertEqual(pick(), ["c-a", "c-b"])
        self.assertEqual((pick(channel="naver_a"), pick(channel="naver_b"), pick(channel="blogger_ko")), (["c-a"], ["c-b"], []))
        self.assertEqual((pick(status="NEW"), pick(status="SELECTED"), pick(status="HOLD")), (["c-a"], ["c-b"], []))
        self.assertEqual((pick(band="high"), pick(band="good"), pick(band="low")), (["c-a"], ["c-b"], []))
        self.assertEqual((pick(cluster="local-ai"), pick(cluster="pc-parts")), (["c-a"], ["c-b"]))
        self.assertEqual(pick(channel="naver_a", status="SELECTED"), [], "조건은 모두 지켜야 한다")

    def test_the_search_needs_every_piece_in_the_title_or_the_keywords_and_ignores_case(self):
        candidate = ts.make(topic="Local AI 사양 정리", primary_keyword="로컬 AI", secondary_keywords=("GPU 메모리",))
        row = row_of(candidate)
        for query, expected in (("local", True), ("LOCAL ai", True), ("gpu", True), ("메모리 gpu", True), ("로컬 사양", True), ("없는낱말", False), ("local 없는낱말", False), ("", True), ("   ", True)):
            with self.subTest(query=query):
                self.assertEqual(rules.matches(row, words=rules.query_words(query)), expected)
        self.assertEqual(rules.query_words(None), ())

    def test_the_order_is_the_score_high_to_low_with_no_score_last_and_ties_by_the_stored_order(self):
        rows = [row_of(ts.rated(70, candidate_id="c70"), 1), row_of(ts.make(candidate_id="cnone"), 2), row_of(ts.rated(90, candidate_id="c90a"), 3), row_of(ts.rated(0, candidate_id="c0"), 4), row_of(ts.rated(90, candidate_id="c90b"), 5)]
        self.assertEqual([row.candidate.candidate_id for row in rules.sort_rows(rows)], ["c90a", "c90b", "c70", "c0", "cnone"])

    def test_the_facet_counts_cover_every_candidate_and_do_not_depend_on_the_other_filters(self):
        rows = [row_of(ts.rated(score, candidate_id=f"c{score}", channel="naver_a" if score % 2 else "naver_b"), number) for number, score in enumerate((95, 85, 70, 60, 30), start=1)]
        bands = rules.counts_by(rows, rules.band_key, rules.BAND_KEYS)
        self.assertEqual(bands, {"all": 5, "high": 2, "good": 1, "mid": 1, "low": 1, "none": 0})
        self.assertEqual(rules.counts_by(rows, lambda item: item.channel, ("naver_a", "naver_b")), {"all": 5, "naver_a": 2, "naver_b": 3})

    def test_the_factor_rows_are_the_engines_six_scores_as_they_are_and_a_missing_one_is_not_zero(self):
        candidate = ts.make(scores=ts.card(80, channel_fit=90, feasibility=70, evidence=80), candidate_id="c-f")
        rows = rules.factor_rows(candidate, tuple((name, 10 + number) for number, name in enumerate(ch.FACTOR_NAMES)))
        self.assertEqual([row["name"] for row in rows], [ch.FACTOR_LABELS[name] for name in ch.FACTOR_NAMES])
        self.assertEqual([(row["value"], row["missing"]) for row in rows], [(90, False), (70, False), (None, True), (None, True), (80, False), (None, True)])
        self.assertEqual([row["text"] for row in rows], ["90점", "70점", "평가 전", "평가 전", "80점", "평가 전"])
        self.assertEqual([row["fraction"] for row in rows], [0.9, 0.7, 0.0, 0.0, 0.8, 0.0])
        self.assertEqual(rows[0]["weight_text"], "가중치 10")
        self.assertEqual(rows[0]["a11y"], "채널 적합도 90점, 가중치 10")
        self.assertEqual(rules.factor_rows(candidate)[0]["weight_text"], "", "가중치를 모르면 말하지 않는다")

    def test_the_trend_rows_say_relative_value_with_the_period_and_never_a_search_count(self):
        candidate = ts.full(candidate_id="c-t")
        rows, note = rules.trend_rows(candidate)
        labels = [label for label, _value, _missing in rows]
        self.assertEqual(labels, ["관심도 값", "변화", "비교 기간", "비교 키워드", "조회일"])
        self.assertEqual(rows[0][1], "73 (0~100 사이의 상대값)")
        self.assertEqual(rows[1][1], "상승")
        self.assertIn("검색한 횟수가 아니에요", note)
        shown = " ".join([note, *(value for _label, value, _missing in rows)])
        for word in FORBIDDEN_WORDS:
            self.assertNotIn(word, shown)

    def test_a_candidate_without_a_trend_value_says_data_is_lacking_or_could_not_be_asked_and_not_zero(self):
        rows, note = rules.trend_rows(ts.make(candidate_id="c-n"))
        self.assertEqual(rows, [("관심도 값", "데이터 부족", True)])
        self.assertIn("0 이 아니라 모르는 값", note)
        unavailable, _note = rules.trend_rows(ts.make(candidate_id="c-u", data_status="unavailable"))
        self.assertEqual(unavailable, [("관심도 값", "조회하지 못했어요", True)])

    def test_the_seed_rows_name_the_route_and_the_seed_word_and_say_when_the_seed_is_not_found(self):
        candidate = ts.make(seed_id="seed-1", source_type="seed", candidate_id="c-s")
        found = rules.seed_rows(candidate, cd.SeedInfo("예시 낱말 가", "예시 대분류", "예시 중분류"))
        self.assertEqual(found, [("후보가 생긴 경로", "씨앗", False), ("Seed", "‘예시 낱말 가’ · 예시 대분류 › 예시 중분류", False)])
        self.assertEqual(rules.seed_rows(candidate, None)[1], ("Seed", "Seed 정보를 찾지 못했어요", True))
        self.assertEqual(rules.seed_rows(ts.make(seed_id=None, source_type="follow_up", candidate_type="follow_up", candidate_id="c-f"), None), [("후보가 생긴 경로", "후속", False), ("Seed", "Seed 없이 만들어진 후보예요", True)])
        self.assertNotIn("seed-1", " ".join(str(item) for row in rules.seed_rows(candidate, None) for item in row), "Seed 번호는 글에 나가지 않는다")

    def test_the_hold_deadline_is_one_korean_date_and_the_engines_utc_date_line_is_not_repeated(self):
        candidate = ts.rated(60, candidate_id="c-h", review_expires_at="2027-02-02T20:30:00Z")
        self.assertEqual(rules.hold_row(candidate)["value"], "2027-02-03", "UTC 20:30 은 한국으로 다음 날이다")
        self.assertIsNone(rules.hold_row(ts.rated(90, candidate_id="c-x")))
        notices = notice.for_candidate(candidate, safety.assess(candidate))
        self.assertTrue(any(line.startswith("검토 기한") for item in notices for line in item.details), "엔진의 안내에는 UTC 날짜 줄이 있다")
        cards, _stop = rules.safety_cards(notices, False)
        self.assertFalse(any(line.startswith("검토 기한") for card_view in cards for line in card_view["details"]))

    def test_the_safety_cards_are_the_engines_fixed_sentences_with_a_level_word_and_a_stop_sentence(self):
        notices = (notice.make("HEALTH_STOP", ("영양제",)), notice.make("HEALTH_TOPIC"), notice.make("COLLAB_POSSIBLE"))
        cards, stop = rules.safety_cards(notices, True)
        self.assertEqual([card_view["level"] for card_view in cards], ["자동 초안 중지", "확인 필요", "참고"])
        self.assertEqual(cards[0]["title"], "의료·효과 단정 위험")
        self.assertEqual(cards[0]["details"], ["영양제"])
        self.assertIn("자동으로 초안을 만들지 않아요", stop)
        self.assertEqual(rules.safety_cards((), False), ([], ""))

    def test_the_info_rows_use_the_service_names_and_the_korean_time_and_mask_the_reader(self):
        candidate = ts.make(candidate_id="c-i", target_reader="독자 " + KEY_SHAPED, created_at="2026-11-04T09:56:00Z", similar_post_ids=("p1", "p2"), duplicate_status="different_topic")
        rows = {row["label"]: row["value"] for row in rules.info_rows(candidate, "예시 블로그 나")}
        self.assertEqual((rows["채널"], rows["후보 종류"], rows["검색 의도"], rows["글 종류"], rows["언어"]), ("예시 블로그 나", "지속형", "고르기", "구매 안내", "한국어"))
        self.assertEqual((rows["만든 때"], rows["중복 판정"], rows["비슷한 글"]), ("2026-11-04 18:56", "다른 주제", "2개"))
        self.assertNotIn(KEY_SHAPED[:10], rows["대상 독자"])

    def test_the_topic_icon_is_stable_for_a_cluster_and_always_one_of_the_eight_topic_icons(self):
        picks = {rules.topic_icon(slug) for slug in ("local-ai", "pc-parts", "small-appliances", "x", "api-and-limits")}
        self.assertTrue(picks <= set(rules.TOPIC_ICONS))
        self.assertEqual(rules.topic_icon("local-ai"), rules.topic_icon("local-ai"))
        self.assertEqual(len(rules.TOPIC_ICONS), 8)
        self.assertEqual(rules.avatar_text("naver_a", "예시 블로그 가"), "A")
        self.assertEqual((rules.avatar_text("blogger_ko", "블로그 에이"), rules.avatar_text("github_pages", "  Pages"), rules.avatar_text("blogger_en", "")), ("블", "P", "?"))

    def test_the_short_number_is_the_services_short_ref_for_engine_shaped_and_other_numbers(self):
        for candidate_id in ("tc-naver_a-seed-1393a6c72220948e", "tc-blogger_ko-follow_up-abcdef0123456789", "cand-ex-001", "x", "short"):
            self.assertEqual(cv.short_number(candidate_id), topic_service.short_ref(candidate_id), candidate_id)
        self.assertEqual(cv.short_number("tc-naver_a-seed-1393a6c72220948e"), "1393a6c7")
        for item in cd.FakeCandidatesProvider().candidates:
            self.assertEqual(len(cv.short_number(item.candidate_id)), 8)
            self.assertNotEqual(cv.short_number(item.candidate_id), item.candidate_id)

    def test_the_tag_names_use_the_service_table_and_mask_unknown_tags(self):
        self.assertEqual(rules.tag_names(ts.make(monetization_tags=("pc_parts", "small_appliance"), candidate_id="c-tag")), ["PC 부품", "소형가전"])
        self.assertEqual(rules.tag_names(ts.make(monetization_tags=("custom_tag",), candidate_id="c-tag2")), ["custom_tag"])


# ---- 3) 컨트롤러 — 읽기·거르기·고르기 ------------------------------------------------------------------------------------------------------
class ReadAndFilterTest(unittest.TestCase):
    def test_loading_states_and_a_reload_that_keeps_what_was_shown(self):
        controller = cv.CandidatesController(cd.FakeCandidatesProvider(), jobs.JobRunner())
        self.assertEqual((controller.state, controller.view()["grid"]["cards"], controller.view()["filters"]), ("loading", [], None))
        controller.apply_loaded(controller.provider.load_candidates(SAFE, NEVER))
        self.assertEqual((controller.state, controller.view()["grid"]["found"]), ("normal", 14))
        controller.apply_load_failed(cd.CandidateFailure("가", code="X", kind="corrupt"))
        view = controller.view()
        self.assertEqual((view["state"], view["error"]["title"], view["filters"], view["make"]["enabled"]), ("error", "후보를 읽지 못했어요.", None, False))
        self.assertEqual(len(controller.rows()), 14, "읽기 오류가 이전에 읽은 값을 지우지 않는다")
        self.assertEqual(view["make"]["reason"], "후보를 읽은 뒤에 쓸 수 있어요.")

    def test_the_view_reads_the_fourteen_samples_in_score_order_with_the_counts_and_the_result_sentence(self):
        controller = new_controller()
        view = controller.view()
        scores = [card_view["score"] for card_view in view["grid"]["cards"]]
        self.assertEqual(scores, sorted(scores, key=lambda value: (value is None, -(value or 0))))
        self.assertEqual(view["filters"]["result"], "14장을 보여 줘요(조건에 맞는 후보 14개 · 전체 14개)")
        self.assertTrue(view["sample"] and all(card_view["sample"] and card_view["sample_tag"] == "예시" for card_view in view["grid"]["cards"]))

    def test_filters_search_and_the_page_size_only_change_what_is_shown(self):
        controller = new_controller(cd.FakeCandidatesProvider("many"))
        self.assertEqual((len(controller.view()["grid"]["cards"]), controller.view()["grid"]["found"], controller.view()["grid"]["more"]["text"]), (24, 130, "24개 더 보기"))
        controller.show_more()
        self.assertEqual(len(controller.view()["grid"]["cards"]), 48)
        controller.set_channel("naver_a")
        self.assertEqual(controller.limit, 24, "거르기를 바꾸면 처음 24장으로 돌아간다")
        found = controller.found()
        self.assertTrue(found and all(row.candidate.channel == "naver_a" for row in found))
        controller.set_status("NEW")
        controller.set_band("high")
        self.assertTrue(all(rules.band_key(row.candidate) == "high" for row in controller.found()))
        self.assertTrue(controller.filters_active())
        controller.reset_filters()
        self.assertEqual((controller.view()["grid"]["found"], controller.filters_active()), (130, False))
        controller.set_query("낱말 007")
        self.assertEqual([row.candidate.topic for row in controller.found()], ["예시 후보 007"])
        self.assertEqual(controller.query, "낱말 007")

    def test_the_wrong_filter_values_are_refused_and_change_nothing(self):
        controller = new_controller()
        before = (controller.channel, controller.status, controller.band, controller.cluster)
        self.assertEqual([controller.set_channel("naver_c"), controller.set_status("DONE"), controller.set_band("huge"), controller.set_cluster("no-such")], [False] * 4)
        self.assertEqual((controller.channel, controller.status, controller.band, controller.cluster), before)
        self.assertFalse(controller.select("no-such-id"))
        self.assertTrue(controller.set_query(None) and controller.query == "", "글이 아닌 값은 빈 글이다")

    def test_the_chips_count_every_channel_status_and_band_and_mark_the_active_one(self):
        controller = new_controller()
        controller.set_status("NEW")
        filters = controller.view()["filters"]
        status = {chip["key"]: chip for chip in filters["status"]}
        self.assertEqual([(key, chip["count"]) for key, chip in status.items()], [("all", 14), ("NEW", 10), ("REVIEW", 1), ("SELECTED", 1), ("HOLD", 1), ("REJECTED", 1)])
        self.assertEqual([key for key, chip in status.items() if chip["active"]], ["NEW"])
        self.assertEqual([chip["key"] for chip in filters["channel"]], ["all", "github_pages", "blogger_ko", "naver_a", "naver_b"], "후보가 있거나 후보 생성이 켜진 채널만")
        self.assertEqual(sum(chip["count"] for chip in filters["band"] if chip["key"] != "all"), 14, "구간 칩의 합은 전체와 같다(점수 계산 전 포함)")
        self.assertEqual(status["HOLD"]["a11y"], "작업 상태 보류 1개")
        self.assertEqual({chip["key"]: chip["a11y"] for chip in filters["band"]}["mid"], "점수 구간 보류 2개", "같은 낱말(보류·제외)도 어느 묶음인지 접근 이름이 가른다")

    def test_the_band_and_cluster_chips_are_hidden_behind_more_filters_until_one_is_active(self):
        controller = new_controller()
        filters = controller.view()["filters"]
        self.assertEqual((filters["more"]["open"], filters["more"]["text"], filters["more"]["available"]), (False, "더 거르기", True))
        controller.set_band("high")
        filters = controller.view()["filters"]
        self.assertEqual((filters["more"]["open"], filters["more"]["text"]), (True, "더 거르기 닫기"), "점수 구간 조건이 걸려 있으면 열린 채")
        controller.reset_filters()
        self.assertFalse(controller.view()["filters"]["more"]["open"])
        controller.toggle_more_filters()
        self.assertTrue(controller.view()["filters"]["more"]["open"])
        controller.toggle_more_filters()
        controller.set_cluster("local-ai")
        filters = controller.view()["filters"]
        self.assertEqual((filters["more"]["open"], filters["more"]["text"]), (True, "더 거르기 닫기"))
        self.assertTrue(all(row.candidate.topic_cluster == "local-ai" for row in controller.found()))
        self.assertEqual({chip["key"]: chip["label"] for chip in filters["cluster"]}["local-ai"], "로컬 AI")
        unknown = new_controller(data=data_of(ts.make(topic_cluster="brand-new-cluster", candidate_id="c-new")))
        self.assertEqual([chip["label"] for chip in unknown.view()["filters"]["cluster"]], ["전체", "brand-new-cluster"])

    def test_a_channel_with_no_candidate_and_no_generation_has_no_chip_and_the_chosen_one_is_dropped_when_it_vanishes(self):
        controller = new_controller()
        controller.set_channel("naver_a")
        data = cd.CandidatesData(tuple(row for row in controller.rows() if row.candidate.channel != "naver_a"), "ready", cd._sample_channels(enabled=("naver_b",)), (), 0, 7, True)
        controller.apply_loaded(data)
        self.assertEqual(controller.channel, "all", "사라진 채널 거르기는 풀린다")
        self.assertNotIn("naver_a", [chip["key"] for chip in controller.view()["filters"]["channel"]])

    def test_the_cards_show_at_most_two_badges_three_chips_and_a_short_summary_for_every_sample(self):
        for scenario in ("normal", "many"):
            controller = new_controller(cd.FakeCandidatesProvider(scenario))
            controller.limit = 1000
            for card_view in controller.view()["grid"]["cards"]:
                with self.subTest(card=card_view["title"]):
                    self.assertLessEqual(len(card_view["badges"]), 2)
                    self.assertLessEqual(len(card_view["keywords"]), 3)
                    self.assertLessEqual(len(card_view["summary"]), 120)
                    self.assertEqual(card_view["more_text"], f"+{card_view['more']}" if card_view["more"] else "")

    def test_the_sample_shows_the_caution_the_stop_the_status_and_the_missing_summary_cases(self):
        controller = new_controller()
        cards = {card_view["title"]: card_view for card_view in controller.view()["grid"]["cards"]}
        self.assertEqual([b["text"] for b in cards["예시 영양제 고르는 기준"]["badges"]], ["새 후보", "주의"])
        self.assertEqual([b["text"] for b in cards["예시 영양제 먹으면 바로 낫는 방법"]["badges"]], ["검토 중", "자동 초안 중지"])
        self.assertEqual([b["text"] for b in cards["예시 후보 다 — 자주 묻는 것 모음"]["badges"]], ["선택됨"])
        none = cards["예시 후보 아 — 점수 계산 전인 예"]
        self.assertEqual((none["summary"], none["summary_missing"], none["ring"]), ("추천 이유가 아직 없어요", True, False))
        self.assertEqual(cards["예시 후보 가 — 순서대로 따라 하는 안내"]["more_text"], "+2")

    def test_every_card_text_is_the_masked_value_and_the_channel_name_is_the_profile_name_with_the_service_name_as_the_fallback(self):
        data = cd.CandidatesData((row_of(ts.rated(80, channel="naver_a", candidate_id="c-1")),), "ready", (cd.ChannelInfo("naver_a", "", None, True),), (), 0, 1, False)
        controller = new_controller(data=data)
        self.assertEqual(controller.view()["grid"]["cards"][0]["channel"]["name"], "네이버 A", "프로필 이름이 비면 서비스의 채널 이름")
        keyed = cd.CandidatesData((row_of(ts.rated(80, channel="naver_a", candidate_id="c-1")),), "ready", (cd.ChannelInfo("naver_a", "이름 " + KEY_SHAPED, None, True),), (), 0, 1, False)
        shown = new_controller(data=keyed).view()["grid"]["cards"][0]["channel"]["name"]
        self.assertNotIn(KEY_SHAPED[:10], shown)

    def test_selection_survives_a_reload_and_goes_when_the_candidate_is_gone(self):
        controller = new_controller()
        first = controller.view()["grid"]["cards"][0]["id"]
        self.assertTrue(controller.select(first))
        controller.apply_loaded(controller.provider.load_candidates(SAFE, NEVER))
        self.assertEqual(controller.selected, first)
        controller.apply_loaded(data_of(ts.make(candidate_id="other")))
        self.assertEqual((controller.selected, controller.opened), (None, False))


# ---- 4) 빈 화면 다섯 ----------------------------------------------------------------------------------------------------------------------
class EmptyStatesTest(unittest.TestCase):
    def empty_of(self, **kwargs):
        controller = new_controller(data=cd.CandidatesData(**kwargs))
        return controller.view()["grid"]["empty"], controller

    def test_the_five_empty_screens_say_different_things_and_none_has_a_second_primary_button(self):
        nostore, _ = self.empty_of(store="missing")
        old, _ = self.empty_of(store="old_structure")
        none, _ = self.empty_of(store="ready")
        skipped, _ = self.empty_of(store="ready", skipped=3, total=3)
        controller = new_controller()
        controller.set_query("전혀없는낱말")
        filtered = controller.view()["grid"]["empty"]
        titles = [item["title"] for item in (nostore, old, none, skipped, filtered)]
        self.assertEqual(len(set(titles)), 5)
        self.assertEqual([item["kind"] for item in (nostore, old, none, skipped, filtered)], ["nostore", "old", "none", "skipped", "filtered"])
        self.assertEqual([item["reset"] for item in (nostore, old, none, skipped, filtered)], [False, False, False, False, True], "다음 행동 단추는 거른 결과가 없을 때의 '거르기 풀기' 하나(주요 행동은 머리의 `후보 만들기` 하나)")
        self.assertIn("읽기만 해서 새로 만들지 않았어요", nostore["desc"])
        self.assertIn("옛 구조", old["title"])
        self.assertIn("옛 모양 사본", old["desc"])

    def test_without_any_candidate_there_is_no_filter_card_but_a_filtered_empty_list_keeps_it(self):
        for kwargs in (dict(store="missing"), dict(store="old_structure"), dict(store="ready"), dict(store="ready", skipped=3, total=3)):
            controller = new_controller(data=cd.CandidatesData(**kwargs))
            self.assertIsNone(controller.view()["filters"], f"{kwargs}: 거를 후보가 하나도 없으면 거르기 카드가 없다(0 으로 가득한 칩만 남는다)")
            self.assertIsNotNone(controller.view()["grid"]["empty"])
        controller = new_controller()
        controller.set_query("전혀없는낱말")
        view = controller.view()
        self.assertIsNotNone(view["filters"], "후보가 있으면 거른 결과가 없어도 거르기 카드는 그대로(거르기 풀기가 거기 있다)")
        self.assertEqual(view["grid"]["empty"]["kind"], "filtered")

    def test_an_empty_store_file_reads_like_a_missing_one_and_the_missing_note_shows_only_for_real_data(self):
        controller = new_controller(data=cd.CandidatesData((), "empty", (), (), 0, 0, False))
        view = controller.view()
        self.assertEqual(view["grid"]["empty"]["kind"], "nostore")
        self.assertEqual([banner[0] for banner in view["banners"]], ["info"])
        sample = new_controller(data=cd.CandidatesData((), "missing", (), (), 0, 0, True))
        self.assertEqual(sample.view()["banners"], [], "예시 데이터에는 파일 안내를 붙이지 않는다")

    def test_candidates_dropped_because_their_score_cannot_be_trusted_are_counted_in_one_sentence(self):
        controller = new_controller(data=data_of(ts.rated(80, candidate_id="c-ok"), skipped=2))
        view = controller.view()
        self.assertEqual(view["banners"], [("warning", "점수를 확인할 수 없어 뺀 후보가 2개 있어요.")])
        self.assertEqual((view["grid"]["found"], view["grid"]["total"]), (1, 1))

    def test_the_empty_cards_never_offer_to_write_and_the_filtered_one_can_be_reset(self):
        controller = new_controller(cd.FakeCandidatesProvider("empty"))
        view = controller.view()
        self.assertEqual((view["grid"]["empty"]["kind"], view["make"]["enabled"]), ("none", True))
        controller = new_controller()
        controller.set_status("REJECTED")
        controller.set_band("high")
        self.assertEqual(controller.view()["grid"]["empty"]["kind"], "filtered")
        controller.reset_filters()
        self.assertIsNone(controller.view()["grid"]["empty"])


# ---- 5) 선택·상세 ----------------------------------------------------------------------------------------------------------------------
class DetailTest(unittest.TestCase):
    def test_selection_keeps_the_candidate_when_the_detail_changes_between_fixed_and_drawer(self):
        controller = new_controller()
        chosen = controller.view()["grid"]["cards"][3]["id"]
        controller.set_layout("fixed")
        self.assertTrue(controller.select(chosen))
        self.assertEqual((controller.selected, controller.drawer_wanted(), controller.detail_view()["id"]), (chosen, False, chosen), "고정 방식에서는 서랍이 필요 없고 상세는 고른 후보를 보인다")
        controller.set_layout("drawer")
        self.assertEqual((controller.selected, controller.opened, controller.drawer_wanted()), (chosen, False, False), "서랍 방식으로 줄 때 서랍이 저절로 열리지는 않지만 선택은 남는다")
        self.assertTrue([card_view for card_view in controller.view()["grid"]["cards"] if card_view["selected"]])
        controller.select(chosen)
        self.assertTrue(controller.drawer_wanted(), "다시 누르면 열린다")
        controller.set_layout("fixed")
        self.assertEqual((controller.selected, controller.detail_view()["id"]), (chosen, chosen), "서랍에서 고정으로 바뀌어도 같은 후보")
        self.assertFalse(controller.set_layout("floating"))
        self.assertEqual(controller.mode, "fixed")

    def test_closing_the_detail_clears_the_selection_in_both_modes_and_tells_which_candidate_was_closed(self):
        controller = new_controller()
        chosen = controller.view()["grid"]["cards"][0]["id"]
        for mode in ("fixed", "drawer"):
            controller.set_layout(mode)
            controller.select(chosen)
            self.assertEqual(controller.close_detail(), chosen)
            self.assertEqual((controller.selected, controller.opened, controller.detail_view()), (None, False, None))
            self.assertIsNone(controller.close_detail(), "열려 있지 않으면 None")

    def test_the_selected_card_is_marked_and_its_description_says_so(self):
        controller = new_controller()
        chosen = controller.view()["grid"]["cards"][0]["id"]
        controller.select(chosen)
        cards = controller.view()["grid"]["cards"]
        self.assertEqual([card_view["id"] for card_view in cards if card_view["selected"]], [chosen])
        self.assertTrue(cards[0]["desc"].endswith("선택됨"))
        self.assertIn("누르면 점수와 이유가 열려요.", cards[1]["desc"])

    def test_the_detail_shows_every_section_with_the_values_as_they_are(self):
        controller = new_controller()
        top = controller.view()["grid"]["cards"][0]
        controller.select(top["id"])
        detail = controller.detail_view()
        self.assertEqual((detail["heading"], detail["score"], detail["band_label"], detail["final_text"], detail["ring"]), (top["title"], 92, "우선 추천", "최종 점수 92점", True))
        self.assertEqual([(row["name"], row["value"]) for row in detail["factors"]["rows"]], [("채널 적합도", 95), ("작성 가능성", 92), ("차별성", 88), ("시기", 90), ("근거", 90), ("수익화", 92)])
        self.assertEqual(detail["factors"]["note"], "", "평가 못 한 항목이 없으면 다시 나누는 설명도 없다")
        self.assertEqual([row["label"] for row in detail["trend"]["rows"]][:2], ["관심도 값", "변화"])
        self.assertEqual([row["value"] for row in detail["seed"]["rows"]], ["씨앗", "‘예시 낱말 가’ · 예시 대분류 하나 › 예시 중분류 하나"])
        self.assertEqual(detail["safety"]["none"], "확인이 필요한 표시는 없어요.")
        self.assertEqual([item for item in detail["keywords"]["items"]], ["예시 낱말 가", "예시 보조 가", "예시 보조 나", "예시 보조 다", "예시 보조 라"], "상세에는 키워드가 모두 보인다")
        self.assertEqual({row["label"]: row["value"] for row in detail["info"]["rows"]}["채널"], "예시 블로그 가")
        self.assertTrue(detail["sample"] and detail["sample_tag"] == "예시 데이터")
        self.assertEqual([badge["text"] for badge in detail["badges"]], ["새 후보", "지속형"])

    def test_a_candidate_with_missing_factors_shows_them_as_not_evaluated_and_explains_the_division(self):
        controller = new_controller()
        edge = next(card_view for card_view in controller.view()["grid"]["cards"] if card_view["title"] == "예시 영양제 고르는 기준")
        controller.select(edge["id"])
        detail = controller.detail_view()
        self.assertEqual([row["text"] for row in detail["factors"]["rows"]], ["85점", "90점", "평가 전", "평가 전", "80점", "70점"])
        self.assertIn("0점이 아니에요", detail["factors"]["note"])
        self.assertEqual([item["title"] for item in detail["safety"]["cards"]], ["건강 정보 확인 필요"])
        self.assertEqual(detail["safety"]["stop"], "")

    def test_a_candidate_without_a_score_has_no_ring_no_final_line_and_an_empty_factor_card(self):
        controller = new_controller()
        none = next(card_view for card_view in controller.view()["grid"]["cards"] if card_view["title"].startswith("예시 후보 아"))
        controller.select(none["id"])
        detail = controller.detail_view()
        self.assertEqual((detail["ring"], detail["score"], detail["final_text"], detail["missing_text"], detail["score_a11y"]), (False, None, "", "점수 계산 전", "점수 계산 전"))
        self.assertEqual((detail["factors"]["rows"], detail["factors"]["empty"]), ([], "점수 구성 정보가 없어요."))
        self.assertEqual((detail["reason"]["lines"], detail["reason"]["empty"]), ([], "추천 이유가 아직 없어요."))

    def test_the_stop_candidate_says_so_in_the_badge_the_card_and_the_sentence(self):
        controller = new_controller()
        stop = next(card_view for card_view in controller.view()["grid"]["cards"] if card_view["title"].startswith("예시 영양제 먹으면"))
        controller.select(stop["id"])
        detail = controller.detail_view()
        self.assertIn("자동 초안 중지", [badge["text"] for badge in detail["badges"]])
        self.assertTrue(detail["safety"]["stop"])
        self.assertEqual(detail["safety"]["cards"][0]["level"], "자동 초안 중지")

    def test_the_hold_band_candidate_shows_a_korean_deadline_row_once(self):
        controller = new_controller()
        hold = next(card_view for card_view in controller.view()["grid"]["cards"] if card_view["title"].startswith("예시 후보 바"))
        controller.select(hold["id"])
        detail = controller.detail_view()
        self.assertTrue(re.fullmatch(r"20\d\d-\d\d-\d\d", detail["hold"]["value"]), detail["hold"])
        shown = " ".join(all_strings(detail["safety"]))
        self.assertNotIn("검토 기한", shown)
        controller.select(controller.view()["grid"]["cards"][0]["id"])
        self.assertIsNone(controller.detail_view()["hold"])

    def test_the_number_is_only_the_short_one_and_the_full_internal_number_never_reaches_a_text(self):
        controller = new_controller()
        row = controller.rows()[0]
        controller.select(row.candidate.candidate_id)
        detail = controller.detail_view()
        self.assertEqual(detail["number"]["ref"], cv.short_number(row.candidate.candidate_id))
        shown = " ".join(all_strings(detail)) + " ".join(all_strings(controller.view()))
        self.assertNotIn(row.candidate.candidate_id, shown)
        self.assertNotRegex(shown, r"tc-[a-z_]+-[a-z_]+-[0-9a-f]{16}")

    def test_no_detail_without_a_selection_or_before_the_candidates_are_read(self):
        controller = cv.CandidatesController(cd.FakeCandidatesProvider(), jobs.JobRunner())
        self.assertIsNone(controller.detail_view())
        controller.apply_loaded(controller.provider.load_candidates(SAFE, NEVER))
        self.assertIsNone(controller.detail_view())
        self.assertEqual(controller.pane_empty()["title"], "후보를 골라 보세요")

    def test_the_fixed_pane_is_wanted_only_when_the_candidates_are_read_and_there_is_one_to_choose(self):
        controller = cv.CandidatesController(cd.FakeCandidatesProvider(), jobs.JobRunner())
        self.assertFalse(controller.pane_visible(), "읽는 중에는 창이 아니라 본문이 안내한다")
        controller.apply_loaded(controller.provider.load_candidates(SAFE, NEVER))
        self.assertTrue(controller.pane_visible())
        controller.apply_load_failed(cd.CandidateFailure("x", code="SAMPLE_CODE", kind="corrupt"))
        self.assertFalse(controller.pane_visible(), "읽기 오류에서는 창이 없다")
        for scenario in ("empty", "no_store", "old_structure"):
            empty = cv.CandidatesController(cd.FakeCandidatesProvider(scenario), jobs.JobRunner())
            empty.apply_loaded(empty.provider.load_candidates(SAFE, NEVER))
            self.assertFalse(empty.pane_visible(), f"{scenario}: 고를 후보가 하나도 없으면 창을 두지 않는다")
        controller.apply_loaded(controller.provider.load_candidates(SAFE, NEVER))
        controller.set_query("없는낱말")
        self.assertTrue(controller.pane_visible(), "거른 결과가 없어도 후보가 있으면 창은 그대로(거르기만 풀면 다시 고른다)")


# ---- 6) 후보 만들기 ---------------------------------------------------------------------------------------------------------------------
class MakeFlowTest(unittest.TestCase):
    def ready(self, **kwargs):
        provider = Scripted(data_of(ts.rated(80, candidate_id="c-1"), sample=False), preview=preview_of(**kwargs.pop("preview", {})), **kwargs)
        provider.gate.set()                                                        # 읽기·미리 보기는 막지 않는다(막는 시험은 만들기 앞에서 문을 닫는다)
        controller = new_controller(provider)
        provider.calls.clear()                                                     # 처음 읽은 기록은 지운다 — 아래 시험은 그 뒤에 부른 것만 본다
        return provider, controller

    def test_the_preview_reads_only_and_the_dialog_says_the_counts_the_seeds_that_nothing_is_deleted_and_no_key_or_network(self):
        provider, controller = self.ready(preview={"new": 6, "proposed": 2, "used": 3})
        status, outcome = drive(controller, controller.start_preview)
        self.assertEqual((status, outcome, provider.calls), ("started", "ok", ["preview"]))
        dialog = controller.make_dialog()
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), ("후보를 최대 6개 만들까요?", "만들기", "취소"))        # 의도적 갱신(P4d, D-277): 미리 본 개수라 서비스가 쓰는 시점에 다시 세면 달라질 수 있어 `최대`
        body = dialog["body"]
        # 의도적 갱신(P4d, D-277): 첫 문장만 `새 후보를 최대 6개 …` — 위 제목과 같은 까닭(미리 본 개수)
        for expected in ("새 후보를 최대 6개 만들어요: 예시 블로그 가 6개", "승인한 Seed 3개에서 만들어요. 승인 전 Seed 2개는 쓰이지 않아요.", "건너뛰는 것: 조합 제외", "지금 있는 후보는 지워지거나 바뀌지 않아요", "키나 네트워크는 쓰지 않아요", "연결 전"):
            self.assertIn(expected, body)
        self.assertNotIn("make", provider.calls, "미리 보기는 아무것도 쓰지 않는다")

    def test_without_the_dialog_nothing_is_written_not_even_by_calling_start_make_directly(self):
        provider, controller = self.ready()
        drive(controller, controller.start_preview)
        self.assertEqual(controller.start_make(), ("unconfirmed", None))
        self.assertEqual(controller.start_make(), ("unconfirmed", None))
        self.assertEqual(provider.calls, ["preview"])
        self.assertEqual(controller.view()["notice"], None)

    def test_with_the_dialog_the_confirmed_make_writes_once_and_says_how_many_were_made(self):
        provider, controller = self.ready(outcome=cd.MakeOutcome(4, 1, 0), preview={"new": 4})
        drive(controller, controller.start_preview)
        controller.make_dialog()
        status, outcome = drive(controller, controller.start_make)
        self.assertEqual((status, outcome, provider.calls), ("started", "ok", ["preview", "make"]))
        self.assertEqual(controller.view()["notice"], {"level": "ok", "text": "후보 4개를 만들었어요. 같은 후보 1개는 건너뛰었어요."})
        self.assertIsNone(controller.preview, "만든 뒤에는 미리 보기를 지운다")
        self.assertEqual(controller.start_make(), ("unavailable", None), "같은 확인으로 두 번 만들 수 없다")

    def test_the_result_sentence_covers_none_made_duplicates_and_withheld_key_shaped_ones(self):
        for outcome, expected in ((cd.MakeOutcome(0, 3, 0), "새로 만든 후보가 없어요. 같은 후보 3개는 건너뛰었어요."), (cd.MakeOutcome(2, 0, 1), "후보 2개를 만들었어요. 키·토큰처럼 보이는 글이 든 후보 1개는 저장하지 않았어요.")):
            provider, controller = self.ready(outcome=outcome)
            drive(controller, controller.start_preview)
            controller.make_dialog()
            drive(controller, controller.start_make)
            self.assertEqual(controller.notice, ("ok", expected))

    def test_the_dialog_says_at_most_the_previewed_count_while_the_result_line_says_only_the_real_count(self):
        """독립 검증(P4d 수정 F6) — 서비스는 쓰는 시점에 다시 세므로 미리 본 개수(12)와 실제로 만든 개수(6)가 다를 수 있다. 확인창의 개수 문장은 `최대 N개`, 결과 줄은 실제 개수(`최대` 없음)."""
        provider, controller = self.ready(preview={"new": 12}, outcome=cd.MakeOutcome(6, 0, 0))
        drive(controller, controller.start_preview)
        dialog = controller.make_dialog()
        self.assertEqual(dialog["title"], "후보를 최대 12개 만들까요?")
        self.assertEqual(dialog["body"].splitlines()[0], "새 후보를 최대 12개 만들어요: 예시 블로그 가 12개")
        self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
        self.assertEqual(controller.notice, ("ok", "후보 6개를 만들었어요."), "결과 줄은 실제로 만든 개수만 말한다")
        self.assertNotIn("최대", controller.notice[1])
        self.assertNotIn("최대", T["cand_made"] + T["cand_made_dup"] + T["cand_made_withheld"] + T["cand_made_none"], "결과 문장 틀에는 `최대` 가 없다")
        self.assertIn("최대", T["cand_make_title"] + T["cand_make_counts"], "확인창의 개수 문장 틀에는 `최대` 가 있다")

    def test_closing_the_dialog_without_confirming_takes_the_mark_back_so_the_same_make_can_no_longer_start(self):
        provider, controller = self.ready()
        drive(controller, controller.start_preview)
        controller.make_dialog()
        self.assertTrue(controller.make_asked)
        controller.discard_make()
        self.assertEqual((controller.make_asked, controller.start_make()), (False, ("unconfirmed", None)))
        self.assertEqual(provider.calls, ["preview"])

    def test_a_second_start_while_the_first_one_is_running_is_ignored(self):
        provider, controller = self.ready(gated=True)
        drive(controller, controller.start_preview)
        provider.gate.clear()
        controller.make_dialog()
        results = {}
        first = controller.start_make(on_done=lambda result, _p: results.setdefault("ok", result), on_error=lambda failure, _p: results.setdefault("failed", failure))
        self.assertEqual(first[0], "started")
        self.assertTrue(controller.busy)
        controller.make_asked = True                                              # 확인창이 다시 떴다고 가정해도 이미 도는 중이면 새로 시작하지 않는다
        self.assertEqual(controller.start_make(), ("busy", None))
        self.assertEqual(controller.start_preview(), ("busy", None))
        self.assertIsNone(controller.start_load(), "만드는 중에는 읽기도 시작하지 않는다")
        self.assertEqual(controller.make_info(), (False, "저장하거나 미리 보는 중에는 쓸 수 없어요."))
        provider.gate.set()
        first[1].join(10)
        self.assertEqual(provider.calls.count("make"), 1)
        controller.apply_write_ok(results["ok"])
        self.assertFalse(controller.busy)

    def test_a_preview_with_nothing_to_make_has_no_dialog_no_write_and_a_card_that_says_what_is_missing(self):
        for lacks, expected in ((("no_channel",), "후보 생성이 켜진 채널이 없어요"), (("no_seed",), "승인한 Seed 가 없어요"), (("full",), "목표 개수가 이미 찼어요"), (("none",), "새로 만들 수 있는 후보가 없어요")):
            provider = Scripted(data_of(ts.make(candidate_id="c-1")), preview=cd.MakePreview("ready", (), 0, 0, 2, lacks, False))
            controller = new_controller(provider)
            drive(controller, controller.start_preview)
            self.assertIsNone(controller.make_dialog(), lacks)
            self.assertEqual(controller.start_make(), ("unavailable", None))
            prep = controller.view()["prep"]
            self.assertTrue(any(expected in line for line in prep["lines"]), (lacks, prep["lines"]))
            self.assertEqual([button["key"] for button in prep["buttons"]], ["seed", "blogs", "close"], "이미 있는 화면(Seed 관리·블로그 관리)으로만 간다")
            self.assertEqual(provider.calls, ["load", "preview"])
        provider = Scripted(data_of(ts.make(candidate_id="c-1")), preview=cd.MakePreview("ready", (), 0, 0, 2, ("no_seed",), False))
        controller = new_controller(provider)
        drive(controller, controller.start_preview)
        self.assertIn("승인 전 Seed 2개는 승인하기 전에는 쓰이지 않아요.", controller.view()["prep"]["lines"])
        controller.close_preview()
        self.assertIsNone(controller.view()["prep"])

    def test_the_dialog_also_tells_the_first_time_store_step_and_the_old_structure_step_and_the_approximate_count(self):
        for store, expected in (("missing", "처음 한 번 새로 만들어요"), ("empty", "비어 있는 후보 보관함 파일을 새로 채워요"), ("old_structure", "새 구조로 올려요")):
            provider, controller = self.ready(preview={"store": store})
            drive(controller, controller.start_preview)
            body = controller.make_dialog()["body"]
            self.assertIn(expected, body, store)
            self.assertEqual("달라질 수 있어요" in body, store == "old_structure")
        provider, controller = self.ready(preview={"store": "ready"})
        drive(controller, controller.start_preview)
        body = controller.make_dialog()["body"]
        self.assertNotIn("처음 한 번", body)
        self.assertNotIn("새 구조로", body)

    def test_a_failed_make_says_it_in_an_easy_sentence_per_kind_and_leaves_the_list_as_it_was(self):
        for kind, expected in (("busy", "다른 창에서 후보 보관함을 쓰고 있어서"), ("disk", "저장 공간이 부족해서"), ("io", "읽기 전용이거나 다른 프로그램이"), ("newer", "더 새로운 프로그램이 만든"), ("corrupt", "후보 보관함을 읽지 못해서"),
                               ("invalid", "주제 엔진 설정 파일을 읽지 못해서"), ("other", "후보를 만들지 못했어요")):
            failure = cd.CandidateFailure("원문은 쓰이지 않는다", code="STORE_X", kind=kind)
            provider, controller = self.ready(fail={"make": failure})
            before = [row.candidate.candidate_id for row in controller.rows()]
            drive(controller, controller.start_preview)
            controller.make_dialog()
            status, outcome = drive(controller, controller.start_make)
            with self.subTest(kind=kind):
                self.assertEqual((status, outcome), ("started", "failed"))
                notice_text = controller.notice
                self.assertEqual(notice_text[0], "error")
                self.assertIn(expected, notice_text[1])
                self.assertNotIn("원문은 쓰이지 않는다", notice_text[1])
                self.assertEqual([row.candidate.candidate_id for row in controller.rows()], before, "실패해도 후보 목록은 그대로")
                self.assertIsNone(controller.preview)
                self.assertEqual(controller.start_make(), ("unavailable", None), "실패한 뒤에는 미리 보기부터 다시 한다")

    def test_a_failure_that_is_not_ours_becomes_the_general_easy_sentence_without_the_exception_text(self):
        provider, controller = self.ready(fail={"make": RuntimeError("C:/비밀/경로 에서 터졌다")})
        drive(controller, controller.start_preview)
        controller.make_dialog()
        drive(controller, controller.start_make)
        self.assertEqual(controller.notice, ("error", T["cand_fail_other"]))
        self.assertNotIn("비밀", " ".join(all_strings(controller.view())))

    def test_a_failed_preview_says_nothing_changed_and_a_busy_one_says_why(self):
        provider, controller = self.ready(fail={"preview": cd.CandidateFailure("가", code="X", kind="corrupt")})
        status, outcome = drive(controller, controller.start_preview)
        self.assertEqual((status, outcome, controller.notice), ("started", "failed", ("error", "만들 후보를 미리 보지 못했어요. 아무것도 바뀌지 않았어요.")))
        provider, controller = self.ready(fail={"preview": cd.CandidateFailure("가", code="X", kind="busy")})
        drive(controller, controller.start_preview)
        self.assertIn("다른 창에서 후보 보관함을 쓰고 있어서", controller.notice[1])

    def test_the_make_button_is_off_until_the_candidates_are_read_and_says_why(self):
        controller = cv.CandidatesController(cd.FakeCandidatesProvider(), jobs.JobRunner())
        self.assertEqual(controller.start_preview(), ("unavailable", None))
        self.assertEqual(controller.view()["make"], {"text": "후보 만들기", "tip": T["cand_make_tip"], "enabled": False, "reason": "후보를 읽는 중에는 쓸 수 없어요."})
        controller.apply_loaded(controller.provider.load_candidates(SAFE, NEVER))
        self.assertTrue(controller.view()["make"]["enabled"])

    def test_the_fake_provider_makes_candidates_in_memory_only_and_the_numbers_do_not_repeat(self):
        provider = cd.FakeCandidatesProvider("no_store")
        controller = new_controller(provider)
        self.assertEqual(controller.view()["grid"]["empty"]["kind"], "nostore")
        for _ in range(2):
            drive(controller, controller.start_preview)
            controller.make_dialog()
            self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
            controller.apply_loaded(provider.load_candidates(SAFE, NEVER))
        ids = [row.candidate.candidate_id for row in controller.rows()]
        self.assertEqual((len(ids), len(set(ids)), provider.store), (8, 8, "ready"))
        self.assertTrue(provider.sample)

    def test_the_lacking_sample_has_the_lacking_preview_and_the_fake_refuses_a_make_without_anything_to_make(self):
        provider = cd.FakeCandidatesProvider("lacking")
        preview = provider.preview_make(SAFE, NEVER)
        self.assertEqual((preview.can_make, preview.lacks), (False, ("no_seed",)))
        with self.assertRaises(cd.CandidateFailure):
            provider.make_candidates(preview, SAFE, NEVER)

    def test_a_slot_exception_resets_the_flow_without_a_stack_text(self):
        provider, controller = self.ready()
        drive(controller, controller.start_preview)
        controller.make_dialog()
        controller.apply_write_unexpected(RuntimeError("터짐"))
        self.assertEqual((controller.preview, controller.make_asked, controller.notice), (None, False, ("error", T["cand_fail_other"])))
        controller.apply_unexpected(RuntimeError("터짐"))
        view = controller.view()
        self.assertEqual((view["state"], controller.data, controller.selected), ("error", None, None))
        self.assertNotIn("터짐", " ".join(all_strings(view)))


# ---- 7) 글 ------------------------------------------------------------------------------------------------------------------------------
class TextTest(unittest.TestCase):
    def test_every_candidate_text_is_used_easy_and_free_of_promises_search_counts_and_codes(self):
        used = set()
        for path in list((UI_DIR / "core").glob("candidate*.py")) + list((UI_DIR / "qt").glob("candidate*.py")) + [UI_DIR / "candidates_adapter.py", UI_DIR / "qt" / "shell.py", UI_DIR / "core" / "app_state.py"]:
            if path.exists() and path.name != "candidate_text.py":                  # 문구표 자신은 모든 열쇠를 적어 두므로 '쓰인 곳' 이 아니다
                used |= set(re.findall(r'''T\[["'](cand_[a-z0-9_]+)["']\]''', path.read_text(encoding="utf-8")))
                used |= set(re.findall(r'''["'](cand_[a-z0-9_]+)["']''', path.read_text(encoding="utf-8")))
        unused = sorted(key for key in candidate_text.CAND_T if key not in used)
        self.assertEqual(unused, [], "쓰이지 않는 문구가 있다")
        for key, value in candidate_text.CAND_T.items():
            with self.subTest(key=key):
                self.assertTrue(value.strip(), key)
                self.assertNotRegex(value, r"\bNone\b|\bTrue\b|\bFalse\b|\['|Traceback|Exception|Error")
                for word in FORBIDDEN_WORDS + text.FORBIDDEN:
                    self.assertNotIn(word, value)
                self.assertNotRegex(value, r"https?://|\w:[\\/]|\\")
                self.assertEqual(T[key], value, "T 에 합쳐져 있다")
        self.assertTrue(all(key.startswith("cand_") for key in candidate_text.CAND_T), "열쇠는 모두 `cand_` 로 시작해 다른 화면의 문구와 겹치지 않는다")

    def test_the_view_models_never_contain_python_lists_enum_names_or_the_internal_number(self):
        controller = new_controller()
        values, engine_values = list(all_strings(controller.view())), []
        for card_view in list(controller.view()["grid"]["cards"]):
            controller.select(card_view["id"])
            detail = controller.detail_view()
            engine_values += list(all_strings(detail.pop("safety")))                    # 안전 표시는 엔진의 고정 문장·걸린 말 그룹 이름(예: 단정·보장 계열)이라 우리 문구 규칙(금지어)과 따로 본다
            values += list(all_strings(detail))
        self.assertGreater(len(values), 300)
        leaks = r"\['|\bNone\b|\bTrue\b|\bFalse\b|Traceback|\brising\b|\binsufficient\b|\bevergreen\b|\bNEW\b|\bREVIEW\b|\bSELECTED\b|\bREJECTED\b|\bHOLD\b|\bhealth_check\b"
        for value in values:
            with self.subTest(value=value[:40]):
                self.assertNotRegex(value, leaks)
                for word in FORBIDDEN_WORDS + text.FORBIDDEN:
                    self.assertNotIn(word, value)
        self.assertTrue(engine_values)
        for value in engine_values:
            self.assertNotRegex(value, leaks)

    def test_the_error_and_loading_states_use_easy_sentences_and_the_diag_text_is_the_only_place_for_a_code(self):
        controller = cv.CandidatesController(cd.FakeCandidatesProvider("error"), jobs.JobRunner())
        controller.apply_load_failed(cd.CandidateFailure("가나다", code="TOPIC_STORE_CORRUPT", kind="corrupt"))
        view = controller.view("code: TOPIC_STORE_CORRUPT")
        self.assertEqual((view["error"]["title"], view["error"]["button"], view["error"]["user"]), ("후보를 읽지 못했어요.", "다시 읽기", "가나다"))
        self.assertNotIn("TOPIC_STORE_CORRUPT", " ".join(piece for key, piece in (("desc", view["error"]["desc"]), ("title", view["error"]["title"]))))
        self.assertEqual(view["error"]["diag"], "code: TOPIC_STORE_CORRUPT")


def code_literals(tree):
    """소스 트리 속 글 리터럴 — 설명 글인 독스트링(모듈·클래스·함수의 첫 문장)은 빼고 코드가 실제로 쓰는 글만."""
    docs = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
            and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)}
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs]


class EveryStateWordsTest(unittest.TestCase):
    """독립 검증(P4d 수정 F2-2) — 금지어(상위노출 보장·노출 확률·검색 1위·수익 보장·월 검색량·검색량)는 격자·상세 두 상태만이 아니라 **화면이 낼 수 있는 모든 상태**의 글에 없다:
    읽는 중·빈 화면 다섯·읽기 오류(오류 종류마다)·준비 안내 카드(까닭마다)·확인창(보관함 상태마다)·알림 줄(만드는 중·결과·실패 종류마다)·예시 표시."""
    WORDS = ("상위노출 보장", "상위노출", "노출 확률", "검색 1위", "수익 보장", "월 검색량", "검색량", "월간 검색", "보장")

    def states(self):
        found = []

        def add(name, value):
            found.append((name, list(all_strings(value))))

        add("loading", cv.CandidatesController(cd.FakeCandidatesProvider(), jobs.JobRunner()).view())
        for name, data in (("no_store", data_of(store="missing")), ("empty_file", data_of(store="empty")), ("old_structure", data_of(store="old_structure")), ("none", data_of(store="ready")), ("skipped_all", data_of(store="ready", skipped=3))):
            add("empty:" + name, new_controller(Scripted(data), data=data).view())
        filtered = new_controller()
        filtered.set_query("없는낱말")
        add("empty:filtered", filtered.view())
        add("sample", new_controller(data=data_of(ts.rated(80, candidate_id="c-s"), sample=True)).view())
        add("banner:skipped", new_controller(data=data_of(ts.rated(80, candidate_id="c-b"), skipped=2)).view())
        codes = list(candidates_adapter.KIND_OF_CODE) + ["SOMETHING_ELSE"]
        for code in codes:                                                                               # 읽기 오류 — 어댑터가 오류 코드마다 고르는 쉬운 문장(`ui/core/text.py` 의 공용 표 포함)
            failure = candidates_adapter.failure_of(AppError(code, {"파일": "x"}), reading=True)
            controller = new_controller(Scripted(data_of()), data=data_of())
            controller.apply_load_failed(failure)
            add("error:" + code, controller.view("code: " + code))
        for lacks in (("no_channel",), ("no_seed",), ("full",), ("none",)):
            controller = new_controller(Scripted(data_of(ts.make(candidate_id="c-p")), preview=cd.MakePreview("ready", (), 0, 0, 2, lacks, False)))
            drive(controller, controller.start_preview)
            add("prep:" + lacks[0], controller.view())
        for store in ("missing", "empty", "old_structure", "ready"):                                     # 확인창 — 건너뛰는 이유가 많아 `외 N가지` 까지 나오는 모양 포함
            reasons = ("조합 제외", "목표 개수 초과", "씨앗당 남길 수 초과", "시기가 아님", "다섯째 이유", "여섯째 이유")
            preview = cd.MakePreview(store, (cd.ChannelPreview("naver_a", "예시 블로그 가", 7, 13, 20, 2, reasons), cd.ChannelPreview("naver_b", "예시 블로그 나", 5, 15, 20, 0, ())), 12, 3, 2, (), False)
            controller = new_controller(Scripted(data_of(ts.make(candidate_id="c-d")), preview=preview))
            drive(controller, controller.start_preview)
            add("dialog:" + store, controller.make_dialog())
        for name, outcome in (("made", cd.MakeOutcome(5, 2, 1)), ("made_only", cd.MakeOutcome(4, 0, 0)), ("none_made", cd.MakeOutcome(0, 3, 0))):          # 알림 줄 — 만드는 중·결과
            controller = new_controller(Scripted(data_of(ts.rated(80, candidate_id="c-n")), preview=preview_of(new=5), outcome=outcome))
            drive(controller, controller.start_preview)
            add("notice:plan", controller.view())
            controller.make_dialog()
            controller.apply_write_ok(cd.MakeOutcome(0))
            controller.pending = {"kind": "make"}
            add("notice:working", {"notice": ("info", T["cand_make_working"])})
            drive(controller, controller.start_preview)
            controller.make_dialog()
            drive(controller, controller.start_make)
            add("notice:" + name, controller.view())
        for kind in cd.KINDS_OF_FAILURE:                                                                 # 알림 줄 — 실패 종류마다(미리 보기·만들기 둘 다)
            for step in ("preview", "make"):
                controller = new_controller(Scripted(data_of(ts.make(candidate_id="c-f")), preview=preview_of(new=3), fail={step: cd.CandidateFailure("원본 글", code="SAMPLE_CODE", kind=kind)}))
                drive(controller, controller.start_preview)
                if step == "make":
                    controller.make_dialog()
                    drive(controller, controller.start_make)
                add(f"notice:fail:{step}:{kind}", controller.view())
        return found

    def test_no_state_of_the_screen_has_a_forbidden_word_and_the_scan_really_covers_many_states_and_texts(self):
        found = self.states()
        names = [name for name, _strings in found]
        total = sum(len(strings) for _name, strings in found)
        for kind in ("loading", "sample", "banner:skipped", "empty:no_store", "empty:empty_file", "empty:old_structure", "empty:none", "empty:skipped_all", "empty:filtered", "prep:no_channel", "prep:no_seed", "prep:full", "prep:none",
                     "dialog:missing", "dialog:empty", "dialog:old_structure", "dialog:ready", "notice:plan", "notice:made", "notice:made_only", "notice:none_made", "notice:fail:preview:busy", "notice:fail:make:other"):
            self.assertIn(kind, names)
        self.assertGreaterEqual(len(names), 45)
        self.assertGreater(total, 600, "스캔이 실제로 많은 글을 훑는다")
        for name, strings in found:
            for value in strings:
                for word in self.WORDS + text.FORBIDDEN:
                    self.assertNotIn(word, value, f"{name}: {value[:60]}")

    def test_the_scan_sees_the_confirmation_prep_and_notice_texts_so_a_forbidden_word_there_would_be_caught(self):
        by_name = dict(self.states())
        self.assertIn("후보를 최대 12개 만들까요?", by_name["dialog:ready"])
        self.assertIn(T["cand_prep_no_seed"], by_name["prep:no_seed"])
        self.assertIn("후보 5개를 만들었어요. 같은 후보 2개는 건너뛰었어요. 키·토큰처럼 보이는 글이 든 후보 1개는 저장하지 않았어요.", by_name["notice:made"])
        self.assertIn(T["cand_fail_busy"], by_name["notice:fail:make:busy"])
        self.assertIn(T["cand_plan_failed"], by_name["notice:fail:preview:other"])
        self.assertIn(T["cand_fail_io"], by_name["notice:fail:preview:io"])
        self.assertIn(T["cand_empty_old_title"], by_name["empty:old_structure"])
        self.assertIn(T["cand_loading"], by_name["loading"])
        fake = by_name["dialog:ready"] + by_name["prep:full"] + by_name["notice:made"] + by_name["error:TOPIC_STORE_CORRUPT"]
        self.assertTrue([value for value in fake + ["월 검색량 기준"] if "검색량" in value], "대조: 금지어가 한 곳에라도 있으면 걸러 내는 식이 실제로 걸린다")


# ---- 8) 소스 규칙 ------------------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    CORE = [UI_DIR / "core" / name for name in ("candidates.py", "candidate_rules.py", "candidates_view.py", "candidate_text.py")]
    REAL_BLOGS = ("ssae" + "ssace", "shine" + "5652", "스마트" + "프라이싱", "스마트" + "초이스", "실전" + "노트", "디지털" + "찬스")

    def calls(self, path):
        return [ast.unparse(node.func) for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.Call)]

    def test_the_screen_code_has_no_file_writing_call_at_all(self):
        exact = {"open", "os.open", "os.write", "os.fsync", "os.replace", "os.rename", "os.remove", "os.unlink", "shutil.copy", "shutil.copyfile", "shutil.copy2", "shutil.move", "shutil.rmtree", "write_json", "save_seeds", "init_files", "sqlite3.connect"}
        attributes = {"write_text", "write_bytes", "unlink", "mkdir", "touch", "rmtree", "write_json", "save_seeds", "init_files", "fsync", "rmdir", "chmod", "open_for_write", "init_topics", "generate_candidates", "cleanup_hold"}
        for path in self.CORE + [UI_DIR / "core" / "app_state.py"]:
            for call in self.calls(path):
                with self.subTest(file=path.name, call=call):
                    self.assertNotIn(call, exact)
                    self.assertNotIn(call.rsplit(".", 1)[-1], attributes)

    def test_the_core_files_never_import_the_service_layer_or_a_gui_toolkit(self):
        for path in self.CORE:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    module = ("." * node.level) + (node.module or "")
                    with self.subTest(file=path.name, module=module):
                        self.assertNotIn("service", module.split("."), "화면의 순수 부분은 서비스를 직접 부르지 않는다 — 어댑터가 한다")
                        self.assertNotIn("PySide6", module)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("PySide6", alias.name)

    def test_the_make_flow_has_one_starter_and_it_needs_the_dialog_mark(self):
        tree = ast.parse((UI_DIR / "core" / "candidates_view.py").read_text(encoding="utf-8"))
        starts = {node.name: ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in ("start_make", "start_preview")}
        self.assertIn("not self.make_asked", starts["start_make"])
        self.assertIn("unconfirmed", starts["start_make"])
        self.assertIn("make_candidates", starts["start_make"])
        self.assertNotIn("make_candidates", starts["start_preview"])
        self.assertIn("preview_make", starts["start_preview"])
        writers = {}
        for path in UI_DIR.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr == "make_candidates":
                    writers.setdefault(path.name, 0)
                    writers[path.name] += 1
        self.assertEqual(sorted(writers), ["candidates_view.py"], "쓰는 길(`make_candidates`)을 부르는 곳은 컨트롤러 한 곳뿐이다 — 셸은 `start_make` 만 부른다")

    def test_no_forbidden_word_is_in_a_string_literal_of_the_core_code_which_could_bypass_the_phrase_table(self):
        """독립 검증(P4d 수정 F2-2) — 문구 표(`candidate_text.py`)를 거치지 않고 코드가 직접 적은 글에도 금지어가 없다(독스트링은 설명이라 뺀다)."""
        words = EveryStateWordsTest.WORDS + text.FORBIDDEN
        scanned = 0
        for path in self.CORE + [UI_DIR / "candidates_adapter.py"]:
            for value in code_literals(ast.parse(path.read_text(encoding="utf-8"))):
                scanned += 1
                for word in words:
                    self.assertNotIn(word, value, f"{path.name}: {value[:60]}")
        self.assertGreater(scanned, 600, "글 리터럴을 실제로 훑는다")
        self.assertEqual([word for word in words if word in "월 검색량 기준"], ["월 검색량", "검색량"], "대조: 식이 금지어를 실제로 알아본다")

    def test_no_real_blog_name_is_in_the_candidate_code_or_this_test(self):
        for path in self.CORE + [Path(__file__)]:
            body = path.read_text(encoding="utf-8")
            for value in self.REAL_BLOGS:
                self.assertNotIn(value, body, path.name)


if __name__ == "__main__":
    unittest.main()
