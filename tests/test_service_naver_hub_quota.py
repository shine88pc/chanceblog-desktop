"""NAVER API HUB 검색어 트렌드 '안전 틀'(결정 D-35)의 한도 안전장치 핵심 시험 — `service/quota.py` 의 월 창·시도/성공 분리·호출 장부·Fail-Closed·한도 단계·상태 파일 판 1/2·확인 절차.
시계·보관소·데이터 폴더는 모두 가짜(고정 시각)이고 네트워크·진짜 자격 증명 관리자·진짜 네이버 서버는 쓰지 않는다. 키 값도 모두 가짜(실제 키 모양이 아니다).

지키는 것:
  A) 월 창: 한국 시간 달력 월(라벨 `YYYY-MM`), 다음 달 1일 00:00 에 초 단위로 정확히 0 으로 돌아가고(12월은 다음 해 1월), 일 창 100·월 창 27,000 이 **둘 다** 지켜진다(먼저 닿는 쪽이 막고 다시 열리는 시각은 더 늦은 쪽).
  B) 시도/성공: 호출하기 전에 시도를 세고(실패·429·시간 초과도 시도다) 성공은 성공했을 때만, 성공 수는 호출을 잡은 때가 속한 창에만 올라 시도 수를 넘지 않는다. 다른 제공자의 상태 파일 모양은 그대로다.
  C) 호출 장부: 최근 200건, 비밀·응답 본문·요청 본문 없이 종류·시각·조건 해시·성공 여부·HTTP 상태·재시도·응답 사용·캐시 적중만 적는다.
  D) Fail-Closed: 사용량 기록 파일이 깨졌거나·월/일 계수가 모순이거나·시계가 되돌아갔거나·인증 상태가 불명확하거나·연결 설정 파일이 깨졌거나·잠금·쓰기가 안 되면 **호출하지 않고** 고정 문구를 보인다(자동으로 풀지 않는다).
  E) 한도 단계(콘솔 월 한도 30,000 기준): 호출 뒤 사용량이 21,000 을 넘으면 안내·24,000 을 넘으면 자동 새로고침 중지(직접 시작한 분석은 한 번에 5회까지)·27,000 을 넘으면 모든 신규 호출 중지. 마지막 10% 예약은 쓰지 않는다.
  F) 키 돌려쓰기 금지: 429·기간 한도·인증 실패·일시 오류 어느 것도 다른 키로 넘어가지 않는다.
  G) 상태 파일 판: 장부가 없는 파일은 판 1 그대로(옛 프로그램이 쓴 파일을 깨졌다고 보지 않는다), 장부가 생긴 파일만 판 2.
  H) 기간 한도 소진 응답 뒤의 쉬는 시각: 월 창이 있는 제공자는 다음 달 1일 00:00(한국 시간), 일 창만 있는 제공자는 그대로 다음 한국 자정.
  I) 성공한 실제 호출의 보고는 마지막 성공 시각을 갱신해 인증 '맑음' 24시간 창을 이어 준다(실패·모호한 결과·다른 제공자·인증 실패로 멈춘 항목은 갱신하지 않는다).
  J) 옛 용도(`naver_openapi`)로는 호출 몫을 주지 않는다(쉬운 한국어 거절, 새 용도로 안내).
"""
import copy
import json
import re
import sys
import tempfile
import unicodedata
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.service import quota as q  # noqa: E402

UTC = timezone.utc
NOW = ss.NOW                                                         # 2026-11-02 01:30:12 UTC = 한국 시각 10:30:12
STAMP = "2026-11-02T01:30:12Z"
NEXT_MIDNIGHT = datetime(2026, 11, 2, 15, 0, 0, tzinfo=UTC)          # 한국 시각 2026-11-03 00:00:00 — 일 창의 다음 초기화
NEXT_MONTH = datetime(2026, 11, 30, 15, 0, 0, tzinfo=UTC)            # 한국 시각 2026-12-01 00:00:00 — 월 창의 다음 초기화
YESTERDAY = NOW - timedelta(days=1)                                  # 한국 시각 2026-11-01 10:30:12 — 같은 달·다른 날
PURPOSE = "naver_apihub"
FIXED = "NAVER API HUB의 새로운 데이터 조회를 사용할 수 없습니다. 저장된 정보와 기본 주제 선정 규칙으로 후보 생성을 계속합니다."
ANOMALY = "이번 달 사용량 숫자가 한도나 앞의 기록과 맞지 않아"
FAILURES = {q.RATE_LIMITED: 429, q.QUOTA_EXHAUSTED: 429, q.TRANSIENT: 503, q.TIMEOUT: None, q.AUTH_FAILED: 401, q.BAD_REQUEST: 400, q.POLICY_BLOCKED: 403, q.CONTENT_BLOCKED: 400, q.OTHER_ERROR: 418}


def stamp(moment):
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def hub_fields(number=1):
    return {"client_id": f"hubid{number:02d}" + "x" * 10, "client_secret": f"hubsecret{number:02d}abcd"}


def image_fields(number=1):
    return {"access_key": f"key{number:02d}" + "Q" * 20}


def blank_audit():
    return {"last_seen": "", "high_water": {"month": "", "attempts": 0}, "last_success": "", "last_error": {"at": "", "outcome": "", "status": 0}, "hold": "", "next_id": 1, "ledger": []}


def window(label, used, successes=0):
    return {"label": label, "used": used, "minutes": {}, "limit": 0, "limit_at": "", "successes": successes}


def ledger_entry(call_id, started, *, calls=1, ok=False):
    return {"id": call_id, "kind": "", "started": stamp(started), "finished": stamp(started) if ok else "", "condition": "", "ok": ok, "status": 200 if ok else 0, "outcome": "ok" if ok else "",
            "retries": 0, "used_response": ok, "cache_hit": False, "calls": calls}


class HubCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.clock = ss.Clock()
        self.ctx = ss.make_ctx(tmp.name, clock=self.clock)
        self.guard = q.QuotaGuard(self.ctx, lock_wait=0)
        self.entry = None

    # ---- 준비 ----------------------------------------------------------------------------------------------------------------------
    def hub(self, *, ok=True, number=1):
        """NAVER API HUB 항목 하나 — `ok` 면 연결 시험 성공 기록을 남겨 인증 상태가 분명하게 한다."""
        self.entry = cn.add_entry(self.ctx, PURPOSE, name=f"허브{number}", fields=hub_fields(number), project="허브").entry
        if ok:
            cn.mark_check(self.ctx, self.entry.entry_id, "ok")
        return self.entry

    def image(self, number=1):
        return cn.add_entry(self.ctx, "image_provider", name=f"이미지{number}", fields=image_fields(number), project=f"앱{number}", terms_ack=True).entry

    def at(self, moment, *, auth=True):
        """시계를 옮긴다(`auth` 면 그 시각에 연결 시험이 성공한 것으로 다시 적어 24시간 유효 기간 때문에 인증이 흐려지지 않게 한다)."""
        self.clock.now = moment
        if auth and self.entry is not None:
            cn.mark_check(self.ctx, self.entry.entry_id, "ok")

    @property
    def path(self):
        return self.ctx.workspace.quota_path

    def state(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write_state(self, state):
        self.path.write_text(json.dumps(state), encoding="utf-8")

    def bucket(self, entry=None):
        return self.state()["buckets"][q.bucket_key(entry or self.entry)]

    def audit(self):
        return self.bucket()["audit"]

    def put(self, *, day=0, month=0, day_ok=0, month_ok=0, day_label="2026-11-02", month_label="2026-11", audit=None, **bucket_extra):
        """장부 묶음의 계수를 직접 적는다 — 묶음을 새로(장부는 비운 채) 만들고 일·월 창에 시도·성공 수를 적는다(수만 번 부르지 않으려고)."""
        state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"schema": 2, "buckets": {}, "failovers": []}
        bucket = {"windows": {"day": window(day_label, day, day_ok), "month": window(month_label, month, month_ok)}, "blocked_until": "", "block_kind": "", "backoff": 0, "audit": blank_audit()}
        bucket.update(bucket_extra)
        if audit:
            bucket["audit"].update(audit)
        state["schema"] = 2
        state["buckets"][q.bucket_key(self.entry)] = bucket
        self.write_state(state)

    def lease(self, **kwargs):
        got = self.guard.acquire(PURPOSE, **kwargs)
        self.assertIsInstance(got, q.Lease, got)
        return got

    def denied(self, **kwargs):
        got = self.guard.acquire(PURPOSE, **kwargs)
        self.assertIsInstance(got, q.Denied, got)
        return got

    def assert_closed(self, got, code, *, cached=False, cause=""):
        """Fail-Closed 거절 — 호출하지 않았고, 고정 문구를 보이고, 사유는 기술 코드 없는 쉬운 한국어다."""
        self.assertIsInstance(got, q.Denied, got)
        self.assertEqual(got.code, code, got)
        self.assertEqual(got.reason, FIXED)
        if cached:
            self.assertTrue(got.use_cache)
            if code not in ("unavailable", "busy"):
                self.assertFalse(got.degraded)
        else:
            self.assertTrue(got.degraded)
            self.assertFalse(got.use_cache)
        self.assertTrue(got.cause)
        self.assertIn(cause, got.cause)
        self.assertNotIn("오류 코드", got.cause)
        self.assertIsNone(re.search(r"[A-Z]{3,}_[A-Z_]+", got.cause), got.cause)


class PinsTest(unittest.TestCase):
    def test_the_constants_the_rules_depend_on_are_pinned(self):
        self.assertEqual((q.SCHEMA, q.SCHEMA_LEDGER, q.SCHEMAS), (1, 2, (1, 2)))
        self.assertEqual(q.MAX_LEDGER, 200)
        self.assertEqual(q.CLOCK_TOLERANCE, timedelta(minutes=5))
        self.assertEqual((q.CONDITION_HEX, q.HOLD_STATE_LOST, q.MAX_KIND), (12, "state_lost", 40))
        self.assertEqual(q.FLOOR_PERCENT, {"bulk_refresh": 30, "new_candidate": 20, "selected_candidate": 10, "critical": 0})      # 다른 제공자의 예약 규칙은 그대로
        self.assertEqual(q.RESERVE_PERCENT, 10)

    def test_the_fixed_sentence_is_exactly_this_one_and_comes_from_the_provider(self):
        self.assertEqual(cn.APIHUB_STOP_TEXT, FIXED)
        provider = cn.PURPOSES[PURPOSE].providers[0]
        self.assertEqual(provider.stop_text, FIXED)
        self.assertTrue(provider.ledger and provider.fail_closed)
        self.assertEqual((provider.console_limit, provider.rotation), (30000, "never"))
        self.assertEqual(provider.windows(), (cn.Window("day", "day", 100), cn.Window("month", "month", 27000)))

    def test_the_stage_table_is_seventy_eighty_ninety_percent_of_the_console_limit(self):
        provider = cn.PURPOSES[PURPOSE].providers[0]
        stages = sorted(provider.stages, key=lambda item: item.percent)
        self.assertEqual([(item.name, item.percent, cn.stage_threshold(provider, item)) for item in stages], [("notice", 70, 21000), ("limited", 80, 24000), ("closed", 90, 27000)])
        self.assertEqual([item.deny for item in stages], [(), ("bulk_refresh",), ("bulk_refresh", "new_candidate", "selected_candidate", "critical")])
        self.assertEqual([item.manual_max_calls for item in stages], [0, 5, 0])
        self.assertEqual(cn.stage_threshold(provider, stages[-1]), provider.windows()[1].limit)          # 90% = 프로그램 안 월 한도


class MonthWindowTest(HubCase):
    def test_the_state_file_holds_a_year_dash_month_label_next_to_the_day_label(self):
        self.hub()
        self.lease()
        state = self.state()
        windows = state["buckets"][q.bucket_key(self.entry)]["windows"]
        self.assertEqual(state["schema"], 2)
        self.assertEqual(set(windows), {"day", "month"})
        self.assertEqual((windows["day"]["label"], windows["day"]["used"], windows["day"]["successes"]), ("2026-11-02", 1, 0))
        self.assertEqual((windows["month"]["label"], windows["month"]["used"], windows["month"]["successes"]), ("2026-11", 1, 0))
        self.assertEqual(set(windows["month"]), {"label", "used", "minutes", "limit", "limit_at", "successes"})

    def test_the_month_label_and_the_next_month_start_follow_korean_calendar_months(self):
        spec = cn.PURPOSES[PURPOSE]
        day, month = spec.providers[0].windows()
        self.assertEqual(q._month_label(NOW), "2026-11")
        self.assertEqual(q._month_label(datetime(2026, 3, 5, tzinfo=UTC)), "2026-03")
        self.assertEqual(q._month_label(datetime(2026, 11, 30, 14, 59, 59, tzinfo=UTC)), "2026-11")
        self.assertEqual(q._month_label(datetime(2026, 11, 30, 15, 0, 0, tzinfo=UTC)), "2026-12")
        self.assertEqual(q._month_label(datetime(2026, 12, 31, 15, 0, 0, tzinfo=UTC)), "2027-01")
        cases = ((NOW, NEXT_MONTH), (datetime(2026, 11, 30, 14, 59, 59, tzinfo=UTC), NEXT_MONTH), (datetime(2026, 11, 30, 15, 0, 0, tzinfo=UTC), datetime(2026, 12, 31, 15, 0, 0, tzinfo=UTC)),
                 (datetime(2026, 12, 31, 14, 59, 59, tzinfo=UTC), datetime(2026, 12, 31, 15, 0, 0, tzinfo=UTC)), (datetime(2026, 12, 31, 15, 0, 0, tzinfo=UTC), datetime(2027, 1, 31, 15, 0, 0, tzinfo=UTC)),
                 (datetime(2027, 2, 15, tzinfo=UTC), datetime(2027, 2, 28, 15, 0, 0, tzinfo=UTC)))
        for moment, expected in cases:
            with self.subTest(moment=moment):
                self.assertEqual(q._next_month_start(moment), expected)
                self.assertEqual(q._next_reset(moment, spec, month), expected)
                self.assertEqual(q._frees_at({"minutes": {}}, month, moment, 5), expected)
        self.assertEqual(q._next_reset(NOW, spec, day), NEXT_MIDNIGHT)
        self.assertEqual(q._next_reset(NOW, spec), NEXT_MIDNIGHT)                  # 창을 안 주면 지금까지처럼 일 창

    def test_the_month_window_counts_and_rolls_over_like_the_day_window(self):
        spec = cn.PURPOSES[PURPOSE]
        month = spec.providers[0].windows()[1]
        stale = {"label": "2026-10", "used": 9, "minutes": {}, "limit": 0, "limit_at": "", "successes": 4}
        self.assertEqual(q._used_of(stale, month, spec, NOW), 0)
        q._record(stale, month, spec, NOW, 2)
        self.assertEqual((stale["label"], stale["used"], stale["successes"]), ("2026-11", 2, 0))
        current = {"label": "2026-11", "used": 9, "minutes": {}, "limit": 0, "limit_at": "", "successes": 4}
        self.assertEqual(q._used_of(current, month, spec, NOW), 9)
        q._record(current, month, spec, NOW, 2)
        self.assertEqual((current["label"], current["used"], current["successes"]), ("2026-11", 11, 4))

    def test_the_month_starts_at_korean_midnight_of_the_first_to_the_second(self):
        self.hub()
        self.put(month=27000, day=0, day_label="2026-11-30")
        self.at(datetime(2026, 11, 30, 14, 59, 59, tzinfo=UTC))
        got = self.denied(priority=q.CRITICAL)
        self.assertEqual(got.code, "exhausted")
        self.at(datetime(2026, 11, 30, 15, 0, 0, tzinfo=UTC))
        self.lease(priority=q.CRITICAL)
        windows = self.bucket()["windows"]
        self.assertEqual((windows["month"]["label"], windows["month"]["used"]), ("2026-12", 1))
        self.assertEqual((windows["day"]["label"], windows["day"]["used"]), ("2026-12-01", 1))

    def test_december_rolls_over_into_the_next_years_january(self):
        self.hub()
        self.put(month=27000, month_label="2026-12", day=0, day_label="2026-12-31")
        self.at(datetime(2026, 12, 31, 14, 59, 59, tzinfo=UTC))
        self.assertEqual(self.denied(priority=q.CRITICAL).code, "exhausted")
        self.at(datetime(2026, 12, 31, 15, 0, 0, tzinfo=UTC))
        self.lease(priority=q.CRITICAL)
        self.assertEqual(self.bucket()["windows"]["month"]["label"], "2027-01")

    def test_the_day_limit_hundred_stops_first_and_the_retry_is_the_next_korean_midnight(self):
        self.hub()
        self.put(day=100, month=5 + 95)
        got = self.denied(priority=q.CRITICAL)
        self.assert_closed(got, "exhausted", cause="오늘 내부 한도(100회)를 다 썼습니다")
        self.assertNotIn("이번 달", got.cause)
        self.assertEqual(got.retry_at, NEXT_MIDNIGHT)
        self.assertEqual(got.resume_text, "내일 00:00 이후 자동 재개")

    def test_the_month_limit_stops_with_the_first_of_next_month_as_the_retry(self):
        self.hub()
        self.put(day=0, month=27000)
        got = self.denied(priority=q.CRITICAL)
        self.assert_closed(got, "exhausted", cause="이번 달 내부 한도(27,000회)를 다 썼습니다")
        self.assertNotIn("오늘", got.cause)
        self.assertEqual(got.retry_at, NEXT_MONTH)
        self.assertEqual(got.resume_text, "12월 01일 00:00 이후 자동 재개")

    def test_the_last_call_of_the_month_budget_is_allowed_and_the_next_is_not(self):
        self.hub()
        self.put(month=26999)
        self.lease(priority=q.CRITICAL)
        self.assertEqual(self.bucket()["windows"]["month"]["used"], 27000)
        self.assertEqual(self.denied(priority=q.CRITICAL).code, "exhausted")
        self.assertEqual(self.bucket()["windows"]["month"]["used"], 27000)

    def test_a_request_for_more_calls_than_the_month_has_left_is_denied_whole(self):
        self.hub()
        self.put(month=26999)
        self.assertEqual(self.denied(priority=q.CRITICAL, calls=2).code, "exhausted")
        windows = self.bucket()["windows"]
        self.assertEqual((windows["month"]["used"], windows["day"]["used"]), (26999, 0))              # 하나도 세지 않았다

    def test_with_both_windows_full_the_later_reset_is_the_retry(self):
        self.hub()
        self.put(day=100, month=27000)
        got = self.denied(priority=q.CRITICAL)
        self.assertEqual(got.retry_at, NEXT_MONTH)
        self.assertIn("오늘 내부 한도(100회)를 다 썼습니다", got.cause)
        self.assertIn("이번 달 내부 한도(27,000회)를 다 썼습니다", got.cause)

    def test_a_rolled_day_frees_the_day_but_not_the_month_and_a_rolled_month_frees_both(self):
        self.hub()
        self.put(day=100, month=27000, day_label="2026-11-01")                           # 날은 어제 것 — 이번 달 27,000번은 그대로
        got = self.denied(priority=q.CRITICAL)
        self.assert_closed(got, "exhausted", cause="이번 달 내부 한도(27,000회)를 다 썼습니다")
        self.assertNotIn("오늘", got.cause)
        self.assertEqual(got.retry_at, NEXT_MONTH)
        view = self.guard.usage(PURPOSE)[0]
        self.assertEqual((view.ledger.day_attempts, view.ledger.month_attempts), (0, 27000))
        self.put(day=100, month=27000, day_label="2026-11-01", month_label="2026-10")    # 달이 바뀌면 날도 바뀐다 — 둘 다 비었다
        self.lease(priority=q.CRITICAL)
        windows = self.bucket()["windows"]
        self.assertEqual((windows["day"]["used"], windows["month"]["used"]), (1, 1))

    def test_a_day_count_with_a_month_count_of_the_past_is_a_contradiction_not_a_rolled_month(self):
        self.hub()
        self.put(day=100, month=27000, month_label="2026-10")                            # 오늘의 100번이 이번 달 0번 안에 있을 수 없다
        self.assert_closed(self.denied(priority=q.CRITICAL), "unverifiable", cause=ANOMALY)


class AttemptsAndSuccessesTest(HubCase):
    def test_an_attempt_is_counted_before_the_call_in_both_windows_and_no_success_yet(self):
        self.hub()
        self.lease(kind="search_trend")
        windows = self.bucket()["windows"]
        self.assertEqual([(windows[name]["used"], windows[name]["successes"]) for name in ("day", "month")], [(1, 0), (1, 0)])
        self.assertEqual(self.audit()["last_success"], "")

    def test_a_success_adds_the_calls_to_the_successes_of_both_windows(self):
        self.hub()
        lease = self.lease(calls=3)
        windows = self.bucket()["windows"]
        self.assertEqual([(windows[name]["used"], windows[name]["successes"]) for name in ("day", "month")], [(3, 0), (3, 0)])
        self.guard.report(lease, q.OK, status=200)
        windows = self.bucket()["windows"]
        self.assertEqual([(windows[name]["used"], windows[name]["successes"]) for name in ("day", "month")], [(3, 3), (3, 3)])
        self.assertEqual(self.audit()["last_success"], STAMP)
        self.assertEqual(self.audit()["last_error"], {"at": "", "outcome": "", "status": 0})

    def test_every_failure_kind_counts_the_attempt_but_never_a_success(self):
        for outcome, status in FAILURES.items():
            with self.subTest(outcome=outcome):
                self.setUp()
                self.hub()
                lease = self.lease(kind="search_trend")
                self.guard.report(lease, outcome, status=status)
                windows = self.bucket()["windows"]
                self.assertEqual([(windows[name]["used"], windows[name]["successes"]) for name in ("day", "month")], [(1, 0), (1, 0)])
                self.assertEqual(self.audit()["last_error"], {"at": STAMP, "outcome": outcome, "status": status or 0})
                self.assertEqual(self.audit()["last_success"], "")
                record = self.audit()["ledger"][0]
                self.assertEqual((record["ok"], record["outcome"], record["status"], record["finished"], record["used_response"]), (False, outcome, status or 0, STAMP, False))

    def test_successes_never_exceed_attempts_over_a_mixed_run(self):
        self.hub()
        for number in range(5):
            lease = self.lease()
            self.guard.report(lease, q.OK if number % 2 == 0 else q.RATE_LIMITED, status=200 if number % 2 == 0 else 429)
            self.at(self.clock.now + timedelta(seconds=10))
        windows = self.bucket()["windows"]
        for name in ("day", "month"):
            self.assertEqual((windows[name]["used"], windows[name]["successes"]), (5, 3))

    def test_a_late_success_is_credited_only_to_the_windows_the_call_started_in(self):
        self.hub()
        self.at(datetime(2026, 11, 2, 14, 59, 59, tzinfo=UTC))                          # 한국 시각 11월 2일 23:59:59
        first = self.lease()
        self.at(datetime(2026, 11, 2, 15, 0, 5, tzinfo=UTC))                            # 한국 시각 11월 3일 00:00:05 — 일 창이 넘어간다
        self.lease()
        self.guard.report(first, q.OK)
        windows = self.bucket()["windows"]
        self.assertEqual((windows["day"]["label"], windows["day"]["used"], windows["day"]["successes"]), ("2026-11-03", 1, 0))
        self.assertEqual((windows["month"]["label"], windows["month"]["used"], windows["month"]["successes"]), ("2026-11", 2, 1))

    def test_a_success_reported_after_midnight_is_credited_to_the_day_of_the_call_while_that_window_still_stands(self):
        self.hub()
        self.at(datetime(2026, 11, 2, 14, 59, 59, tzinfo=UTC))
        first = self.lease()
        self.at(datetime(2026, 11, 2, 15, 0, 1, tzinfo=UTC))
        self.guard.report(first, q.OK)
        windows = self.bucket()["windows"]
        self.assertEqual((windows["day"]["label"], windows["day"]["used"], windows["day"]["successes"]), ("2026-11-02", 1, 1))
        self.assertEqual((windows["month"]["used"], windows["month"]["successes"]), (1, 1))

    def test_the_http_status_is_stored_only_in_the_range_one_hundred_to_five_ninety_nine(self):
        self.hub()
        cases = ((99, 0), (100, 100), (599, 599), (600, 0), (True, 0), ("429", 0), (429.5, 0), (None, 0), (-1, 0))
        for status, stored in cases:
            with self.subTest(status=status):
                lease = self.lease()
                self.guard.report(lease, q.OTHER_ERROR, status=status)
                self.assertEqual(self.audit()["ledger"][-1]["status"], stored)
                self.assertEqual(self.audit()["last_error"]["status"], stored)
                self.at(self.clock.now + timedelta(seconds=1))

    def test_the_used_response_flag_defaults_to_the_outcome_and_an_explicit_value_wins(self):
        self.hub()
        for outcome, given, expected in ((q.OK, None, True), (q.OK, False, False), (q.OTHER_ERROR, None, False), (q.OTHER_ERROR, True, True), (q.OK, 0, False), (q.OTHER_ERROR, 1, True)):
            with self.subTest(outcome=outcome, given=given):
                lease = self.lease()
                self.guard.report(lease, outcome, used_response=given)
                self.assertIs(self.audit()["ledger"][-1]["used_response"], expected)

    def test_the_usage_view_shows_today_and_this_month_attempts_and_successes_separately(self):
        self.hub()
        self.guard.report(self.lease(calls=2), q.OK, status=200)
        self.guard.report(self.lease(), q.TIMEOUT)
        led = self.guard.usage(PURPOSE)[0].ledger
        self.assertEqual((led.day_attempts, led.day_successes, led.month_attempts, led.month_successes), (3, 2, 3, 2))
        self.assertEqual((led.day_limit, led.month_limit, led.console_limit), (100, 27000, 30000))
        self.assertEqual(led.last_success, STAMP)
        self.assertEqual(led.last_error, {"at": STAMP, "outcome": "timeout", "status": 0})
        self.assertEqual((led.stage, led.stage_text, led.stopped, led.stop_code, led.stop_cause, led.stop_text), ("ok", "", False, "", "", ""))

    def test_the_usage_view_after_a_success_only_has_no_error_and_changes_no_file(self):
        self.hub()
        self.guard.report(self.lease(), q.OK, status=200)
        before = self.path.read_bytes()
        led = self.guard.usage(PURPOSE)[0].ledger
        self.assertEqual((led.last_error, led.last_success, led.stopped), (None, STAMP, False))
        self.assertEqual(self.path.read_bytes(), before)

    def test_reporting_the_same_call_twice_cannot_push_successes_above_attempts(self):
        self.hub()
        lease = self.lease()
        self.guard.report(lease, q.OK)
        self.guard.report(lease, q.OK)
        windows = self.bucket()["windows"]
        self.assertEqual([(windows[name]["used"], windows[name]["successes"]) for name in ("day", "month")], [(1, 1), (1, 1)])
        self.lease()                                                                                           # 계수가 모순이 되지 않았다 — 다음 호출이 막히지 않는다

    def test_the_usage_view_names_an_unclear_auth_state_as_the_stop_reason(self):
        self.hub(ok=False)
        led = self.guard.usage(PURPOSE)[0].ledger
        self.assertEqual((led.stopped, led.stop_code, led.stop_text), (True, "auth_unclear", FIXED))
        self.assertIn("인증 상태가 확실하지 않습니다", led.stop_cause)

    def test_the_purpose_status_says_rate_limited_only_when_new_calls_are_stopped_by_the_limit(self):
        self.hub()
        self.put(month=100, day=1)
        self.assertEqual(self.guard.purpose_status(PURPOSE), cn.NEEDS_CHECK)                                  # 호출 코드가 아직 없어 '연결 확인 필요' 가 정직하다
        self.put(month=27000)
        self.assertEqual(self.guard.purpose_status(PURPOSE), cn.RATE_LIMITED)

    def test_the_usage_view_names_the_stop_reason_after_a_rate_limit_and_uses_the_fixed_sentence(self):
        self.hub()
        self.guard.report(self.lease(), q.RATE_LIMITED, status=429)
        led = self.guard.usage(PURPOSE)[0].ledger
        self.assertEqual((led.stopped, led.stop_code, led.stop_cause, led.stop_text), (True, "blocked", "한도 초과 응답을 받아 잠시 쉬는 중입니다", FIXED))
        self.assertEqual(led.last_error, {"at": STAMP, "outcome": "rate_limited", "status": 429})

    def test_the_ledger_part_of_the_dict_has_exactly_these_fields_and_rows_get_attempts_and_successes(self):
        self.hub()
        self.guard.report(self.lease(), q.OK)
        view = self.guard.usage(PURPOSE)[0]
        found = view.to_dict()
        self.assertEqual(set(found["ledger"]), {"day_attempts", "day_successes", "month_attempts", "month_successes", "day_limit", "month_limit", "console_limit", "last_success", "last_error",
                                                "stage", "stage_text", "stopped", "stop_code", "stop_cause", "stop_text"})
        rows = {row["window"]: row for row in found["rows"]}
        self.assertEqual(set(rows), {"day", "month"})
        self.assertEqual((rows["day"]["span"], rows["month"]["span"]), ("하루", "이번 달"))
        for row in rows.values():
            self.assertEqual((row["used"], row["attempts"], row["successes"]), (1, 1, 1))
        self.assertEqual((rows["day"]["limit"], rows["month"]["limit"]), (100, 27000))

    def test_a_purpose_without_a_key_still_shows_its_limits_and_creates_no_file(self):
        view = self.guard.usage(PURPOSE)[0]
        self.assertEqual((view.entries, view.ledger.day_limit, view.ledger.month_limit, view.ledger.console_limit), (0, 100, 27000, 30000))
        self.assertEqual((view.ledger.day_attempts, view.ledger.month_attempts, view.ledger.stopped), (0, 0, False))
        self.assertFalse(self.path.exists())

    def test_other_providers_keep_the_old_state_shape_and_the_old_dict_shape(self):
        image = self.image()
        ai = cn.add_entry(self.ctx, "ai_assist", name="보조", fields={"key": "aikey" + "Z" * 20}).entry
        first = self.guard.acquire("image_provider")
        self.assertIsInstance(first, q.Lease)
        self.assertEqual(first.call_id, 0)
        self.assertIsInstance(self.guard.acquire("ai_assist"), q.Lease)
        state = self.state()
        self.assertEqual(state["schema"], 1)
        self.assertEqual(set(state), {"schema", "buckets", "failovers"})
        self.assertEqual(set(state["buckets"]), {q.bucket_key(image), q.bucket_key(ai)})
        for bucket in state["buckets"].values():
            self.assertEqual(set(bucket), {"windows", "blocked_until", "block_kind", "backoff"})
        self.assertEqual(set(state["buckets"][q.bucket_key(image)]["windows"]["hour"]), {"label", "used", "minutes", "limit", "limit_at"})
        text = json.dumps(state)
        self.assertNotIn("audit", text)
        self.assertNotIn("successes", text)
        view = self.guard.usage("image_provider")[0]
        self.assertNotIn("ledger", view.to_dict())
        self.assertIsNone(view.ledger)
        self.assertEqual(set(view.rows[0].to_dict()), {"entry", "provider", "window", "used", "limit", "near_limit", "span"})
        self.assertEqual([item.purpose for item in self.guard.usage()], ["naver_apihub", "naver_searchad", "image_provider", "ai_assist", "blogger"])      # 옛 용도는 사용량이 없어 건너뛴다

    def test_the_old_denial_of_another_provider_keeps_its_own_wording(self):
        self.image()
        entry = cn.load(self.ctx).entries[0]
        state = {"schema": 1, "buckets": {q.bucket_key(entry): {"windows": {"hour": {"label": "", "used": 0, "minutes": {"2026-11-02T01:30": 50}, "limit": 0, "limit_at": ""}}, "blocked_until": "",
                                                                 "block_kind": "", "backoff": 0}}, "failovers": []}
        self.ctx.workspace.quota_path.write_text(json.dumps(state), encoding="utf-8")
        got = self.guard.acquire("image_provider", priority=q.CRITICAL)
        self.assertIsInstance(got, q.Denied)
        self.assertEqual((got.code, got.cause), ("exhausted", ""))
        self.assertTrue(got.reason.startswith("한도를 다 써서"))

    def test_the_connection_test_call_is_counted_and_written_to_the_ledger_with_its_kind(self):
        entry = self.hub(ok=False)
        first = self.guard.acquire_entry(entry, kind="connection_test")
        self.assertIsInstance(first, q.Lease)
        self.assertEqual(first.call_id, 1)
        record = self.audit()["ledger"][0]
        self.assertEqual((record["kind"], record["calls"], record["finished"], record["retries"]), ("connection_test", 1, "", 0))
        self.guard.report(first, q.OK, status=200)
        windows = self.bucket()["windows"]
        self.assertEqual([(windows[name]["used"], windows[name]["successes"]) for name in ("day", "month")], [(1, 1), (1, 1)])


class LedgerTest(HubCase):
    COND = {"keywordGroups": [{"groupName": "난방", "keywords": ["겨울 난방비", "전기요금"]}], "startDate": "2026-10-01", "timeUnit": "month"}

    def test_a_finished_record_holds_exactly_the_documented_fields(self):
        self.hub()
        lease = self.lease(kind="search_trend", condition=self.COND)
        self.assertEqual(lease.call_id, 1)
        self.guard.report(lease, q.OK, status=200)
        expected = {"id": 1, "kind": "search_trend", "started": STAMP, "finished": STAMP, "condition": q.condition_hash(self.COND), "ok": True, "status": 200, "outcome": "ok", "retries": 0,
                    "used_response": True, "cache_hit": False, "calls": 1}
        self.assertEqual(self.audit()["ledger"], [expected])
        self.assertEqual((self.audit()["next_id"], self.audit()["last_success"]), (2, STAMP))

    def test_a_call_that_was_never_reported_stays_as_a_pending_attempt(self):
        self.hub()
        self.lease(kind="search_trend", condition=self.COND, calls=2)
        record = self.audit()["ledger"][0]
        self.assertEqual((record["finished"], record["ok"], record["status"], record["outcome"], record["used_response"], record["calls"]), ("", False, 0, "", False, 2))
        self.assertEqual(self.bucket()["windows"]["month"]["used"], 2)                                  # 시도는 이미 셌다
        second = self.lease()
        self.assertEqual(second.call_id, 2)

    def test_the_condition_hash_is_twelve_hex_characters_independent_of_key_order_and_normalised(self):
        found = q.condition_hash({"a": 1, "b": [1, 2]})
        self.assertRegex(found, r"\A[0-9a-f]{12}\Z")
        self.assertEqual(found, q.condition_hash({"b": [1, 2], "a": 1}))
        self.assertEqual(q.condition_hash({"word": " 겨울 "}), q.condition_hash({"word": "겨울"}))
        self.assertEqual(q.condition_hash({"word": unicodedata.normalize("NFD", "한글")}), q.condition_hash({"word": "한글"}))
        self.assertEqual(q.condition_hash({unicodedata.normalize("NFD", "한글"): 1}), q.condition_hash({"한글": 1}))
        self.assertNotEqual(q.condition_hash({"a": 1}), q.condition_hash({"a": 2}))
        self.assertNotEqual(q.condition_hash({"a": [1, 2]}), q.condition_hash({"a": [2, 1]}))
        self.assertNotEqual(q.condition_hash({"a": True}), q.condition_hash({"a": 1}))
        self.assertNotEqual(q.condition_hash({"a": {"x": 1}}), q.condition_hash({"a": {"x": 2}}))
        self.assertEqual(q.condition_hash(None), "")
        self.assertNotEqual(q.condition_hash({}), "")

    def test_a_condition_with_a_credential_like_field_name_or_a_non_json_value_is_refused(self):
        for name in ("client_secret", "client_id", "Client-Secret", "authorization", "x-ncp-apigw-api-key", "X-NCP-APIGW-API-KEY-ID", "key", "token", "password", "api_key", "secret", " token "):
            with self.subTest(name=name), self.assertRaises(ValueError):
                q.condition_hash({name: "x"})
        with self.assertRaises(ValueError):
            q.condition_hash({"a": {"b": {"token": 1}}})
        for bad in ({1: 2}, {"a": object()}, {"a": {1, 2}}, {"a": b"x"}, {"a": float("nan")}, {"a": float("inf")}, object()):
            with self.subTest(bad=repr(bad)), self.assertRaises(ValueError):
                q.condition_hash(bad)
        deep = {}
        cursor = deep
        for _ in range(10):
            cursor["a"] = {}
            cursor = cursor["a"]
        with self.assertRaises(ValueError):
            q.condition_hash(deep)

    def test_a_refused_condition_stops_the_call_before_anything_is_written(self):
        self.hub()
        with self.assertRaises(ValueError):
            self.guard.acquire(PURPOSE, condition={"client_secret": hub_fields()["client_secret"]})
        self.assertFalse(self.path.exists())

    def test_no_file_holds_the_keywords_the_dates_or_the_key_values(self):
        self.hub()
        self.guard.report(self.lease(kind="search_trend", condition=self.COND), q.OK, status=200)
        self.guard.record_cache_hit(PURPOSE, kind="search_trend", condition=self.COND)
        texts = {path.relative_to(self.ctx.workspace.root).as_posix(): path.read_text(encoding="utf-8", errors="replace") for path in sorted(Path(self.ctx.workspace.root).rglob("*")) if path.is_file()}
        self.assertIn("quota_state.json", texts)
        for name, text in texts.items():
            for needle in ("겨울 난방비", "전기요금", "난방", "2026-10-01", "keywordGroups", hub_fields()["client_secret"], hub_fields()["client_id"]):
                self.assertNotIn(needle, text, f"{name} 에 {needle!r}")
        self.assertIn(q.condition_hash(self.COND), texts["quota_state.json"])

    def test_the_ledger_keeps_only_the_latest_two_hundred_calls(self):
        self.hub()
        done = 0
        for day in range(3):
            self.at(NOW + timedelta(days=day))
            for _ in range(100 if day < 2 else 5):
                self.lease()
                done += 1
        ledger = self.audit()["ledger"]
        self.assertEqual((done, len(ledger)), (205, 200))
        self.assertEqual([item["id"] for item in ledger], list(range(6, 206)))
        self.assertEqual(self.audit()["next_id"], 206)

    def test_a_smaller_ledger_limit_drops_the_oldest_and_a_record_that_left_is_written_again_when_reported(self):
        self.hub()
        with mock.patch.object(q, "MAX_LEDGER", 2):
            first = self.lease(kind="search_trend", calls=2)
            self.lease()
            self.lease()
            self.assertEqual([item["id"] for item in self.audit()["ledger"]], [2, 3])
            self.at(NOW + timedelta(seconds=30))
            self.guard.report(first, q.OK, status=200)
            ledger = self.audit()["ledger"]
        self.assertEqual([item["id"] for item in ledger], [3, 4])
        late = ledger[-1]
        self.assertEqual((late["kind"], late["started"], late["finished"], late["ok"], late["calls"], late["status"]), ("", STAMP, stamp(NOW + timedelta(seconds=30)), True, 2, 200))
        windows = self.bucket()["windows"]
        self.assertEqual((windows["month"]["used"], windows["month"]["successes"]), (4, 2))

    def test_the_first_attempt_has_no_retries_and_the_second_try_of_the_same_request_has_one(self):
        self.hub()
        first = self.lease(kind="search_trend")
        result = self.guard.report(first, q.TIMEOUT)
        self.assertEqual((result.action, result.wait_seconds), (q.ACT_RETRY, 2))
        second = self.lease(request=first.request, kind="search_trend")
        self.assertEqual(second.call_id, 2)
        self.guard.report(second, q.OK, status=200)
        ledger = self.audit()["ledger"]
        self.assertEqual([(item["retries"], item["outcome"]) for item in ledger], [(0, "timeout"), (1, "ok")])
        windows = self.bucket()["windows"]
        self.assertEqual((windows["month"]["used"], windows["month"]["successes"]), (2, 1))

    def test_a_cache_hit_is_noted_without_counting_an_attempt_or_a_success(self):
        self.hub()
        self.guard.report(self.lease(), q.OK, status=200)
        before = copy.deepcopy(self.bucket()["windows"])
        self.assertIs(self.guard.record_cache_hit(PURPOSE, kind="search_trend", condition=self.COND), True)
        self.assertEqual(self.bucket()["windows"], before)
        record = self.audit()["ledger"][-1]
        self.assertEqual(record, {"id": 2, "kind": "search_trend", "started": STAMP, "finished": STAMP, "condition": q.condition_hash(self.COND), "ok": True, "status": 0, "outcome": "ok",
                                  "retries": 0, "used_response": True, "cache_hit": True, "calls": 0})
        self.assertEqual(self.audit()["next_id"], 3)
        self.lease()                                                                                         # 그 뒤에도 정상으로 센다(장부와 계수가 어긋나지 않는다)

    def test_a_cache_hit_before_any_call_creates_the_ledger_bucket_with_empty_windows(self):
        self.hub()
        self.assertIs(self.guard.record_cache_hit(PURPOSE), True)
        state = self.state()
        self.assertEqual(state["schema"], 2)
        bucket = state["buckets"][q.bucket_key(self.entry)]
        self.assertEqual(bucket["windows"], {})
        self.assertEqual(len(bucket["audit"]["ledger"]), 1)
        self.assertEqual(self.guard.usage(PURPOSE)[0].ledger.month_attempts, 0)

    def test_a_cache_hit_is_not_noted_without_a_key_or_with_a_broken_state_file(self):
        self.assertIs(self.guard.record_cache_hit(PURPOSE), False)
        self.assertFalse(self.path.exists())
        self.hub()
        self.path.write_text("not json{", encoding="utf-8")
        self.assertIs(self.guard.record_cache_hit(PURPOSE), False)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "not json{")

    def test_a_cache_hit_is_only_for_ledger_purposes_and_checks_its_arguments(self):
        self.hub()
        self.image()
        with self.assertRaises(ValueError):
            self.guard.record_cache_hit("image_provider")
        with self.assertRaises(ValueError):
            self.guard.record_cache_hit("no_such_purpose")
        for kind in ("Search", "x" * 41, 5, None, "a b"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.guard.record_cache_hit(PURPOSE, kind=kind)

    def test_the_call_kind_is_checked_on_every_way_in(self):
        entry = self.hub()
        for kind in ("Search", "x" * 41, 5, None, "a b", "한글"):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    self.guard.acquire(PURPOSE, kind=kind)
                with self.assertRaises(ValueError):
                    self.guard.acquire_entry(entry, kind=kind)
        self.assertFalse(self.path.exists())
        self.lease(kind="x" * 40)
        self.lease(kind="")
        self.lease(kind="a_1")


class FailClosedTest(HubCase):
    def test_a_broken_state_file_denies_and_is_neither_moved_nor_repaired_by_this_provider(self):
        broken = {"깨진 글": "not json{", "모르는 판": json.dumps({"schema": 3, "buckets": {}, "failovers": []}), "낯선 칸": json.dumps({"schema": 1, "buckets": {}, "failovers": [], "extra": 1}),
                  "판 1 에 장부 칸": json.dumps({"schema": 1, "buckets": {"x/-/y": {"windows": {}, "blocked_until": "", "block_kind": "", "backoff": 0, "audit": blank_audit()}}, "failovers": []})}
        for name, text in broken.items():
            with self.subTest(name=name):
                self.setUp()
                self.hub()
                self.path.write_text(text, encoding="utf-8")
                before = self.path.read_bytes()
                self.assert_closed(self.guard.acquire(PURPOSE), "unverifiable", cause="사용량 기록 파일을 읽을 수 없어")
                self.assert_closed(self.guard.acquire(PURPOSE, cached=True), "unverifiable", cached=True, cause="사용량 기록 파일을 읽을 수 없어")
                self.assertEqual(self.path.read_bytes(), before)
                self.assertFalse(self.path.with_name(self.path.name + ".bak").exists())
                led = self.guard.usage(PURPOSE)[0].ledger
                self.assertEqual((led.stopped, led.stop_code, led.stop_text), (True, "unverifiable", FIXED))
                self.assertEqual(self.path.read_bytes(), before)                                            # 사용량 보기는 읽기만 한다

    def test_another_provider_repairs_the_file_the_old_way_but_this_one_stays_stopped_until_the_operator_confirms(self):
        self.hub()
        self.image()
        self.path.write_text("not json{", encoding="utf-8")
        self.assert_closed(self.guard.acquire(PURPOSE), "unverifiable", cause="사용량 기록 파일을 읽을 수 없어")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "not json{")
        self.assertIsInstance(self.guard.acquire("image_provider"), q.Lease)                                    # 다른 제공자는 지금까지처럼 절반을 쓴 것으로 보고 계속한다
        self.assertEqual(self.path.with_name(self.path.name + ".bak").read_text(encoding="utf-8"), "not json{")
        state = self.state()
        self.assertEqual(state["schema"], 2)
        held = state["buckets"][q.bucket_key(self.entry)]
        self.assertEqual((held["windows"], held["audit"]["hold"]), ({}, "state_lost"))                          # 절반으로 가정하지 않고 '확인 필요' 만 남긴다
        self.assert_closed(self.guard.acquire(PURPOSE), "unverifiable", cause="사라진 적이 있어")
        self.assertEqual(self.guard.acquire_entry(self.entry).code, "unverifiable")
        self.assertEqual(self.guard.acknowledge(PURPOSE, confirmed=True), 1)
        after = self.bucket()
        self.assertEqual(after["audit"]["hold"], "")
        self.assertEqual([(after["windows"][name]["used"], after["windows"][name]["successes"]) for name in ("day", "month")], [(50, 0), (13500, 0)])
        self.assertEqual((after["audit"]["last_seen"], after["audit"]["high_water"]), (STAMP, {"month": "2026-11", "attempts": 13500}))
        self.lease()
        windows = self.bucket()["windows"]
        self.assertEqual((windows["day"]["used"], windows["month"]["used"]), (51, 13501))

    def test_the_hold_is_written_the_moment_the_broken_file_is_moved_even_if_the_other_call_is_denied(self):
        self.hub()
        self.image()
        self.path.write_text("not json{", encoding="utf-8")
        got = self.guard.acquire("image_provider", priority=q.BULK, calls=40)                                     # 절반을 쓴 상태에서 40번은 못 부른다 — 거절돼 저장이 없어도
        self.assertIsInstance(got, q.Denied)
        self.assertTrue(self.path.with_name(self.path.name + ".bak").exists())
        self.assertEqual(self.bucket()["audit"]["hold"], "state_lost")
        self.assertEqual(self.denied().code, "unverifiable")

    def test_the_operator_confirmation_needs_an_explicit_true_and_a_fail_closed_purpose(self):
        self.hub()
        self.guard.report(self.lease(), q.OK)
        before = self.path.read_bytes()
        for value in (False, None, 1, "yes", 0, "True"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.guard.acknowledge(PURPOSE, confirmed=value)
        with self.assertRaises(ValueError):
            self.guard.acknowledge(PURPOSE)
        with self.assertRaises(ValueError):
            self.guard.acknowledge("image_provider", confirmed=True)
        with self.assertRaises(ValueError):
            self.guard.acknowledge("no_such_purpose", confirmed=True)
        self.assertEqual(self.path.read_bytes(), before)

    def test_the_confirmation_without_any_entry_releases_nothing(self):
        self.assertEqual(self.guard.acknowledge(PURPOSE, confirmed=True), 0)

    def test_a_month_above_the_limit_is_an_anomaly_but_exactly_the_limit_is_only_exhausted(self):
        self.hub()
        self.put(month=27001)
        self.assert_closed(self.denied(priority=q.CRITICAL), "unverifiable", cause=ANOMALY)
        self.put(month=27000)
        self.assert_closed(self.denied(priority=q.CRITICAL), "exhausted", cause="이번 달 내부 한도")

    def test_a_day_above_the_limit_is_an_anomaly_but_exactly_the_limit_is_only_exhausted(self):
        self.hub()
        self.put(day=101, month=101)
        self.assert_closed(self.denied(priority=q.CRITICAL), "unverifiable", cause=ANOMALY)
        self.put(day=100, month=100)
        self.assert_closed(self.denied(priority=q.CRITICAL), "exhausted", cause="오늘 내부 한도")

    def test_more_successes_than_attempts_is_refused_as_a_broken_file_and_as_an_anomaly(self):
        self.hub()
        self.put(day=2, month=5, day_ok=3)
        before = self.path.read_bytes()
        self.assert_closed(self.denied(priority=q.CRITICAL), "unverifiable", cause="사용량 기록 파일을 읽을 수 없어")
        self.assertEqual(self.path.read_bytes(), before)
        spec = cn.PURPOSES[PURPOSE]
        windows = spec.providers[0].windows()
        bucket = {"windows": {"day": window("2026-11-02", 2, 3), "month": window("2026-11", 5, 0)}, "blocked_until": "", "block_kind": "", "backoff": 0, "audit": blank_audit()}
        self.assertIn("맞지 않아", q.QuotaGuard._count_anomaly(bucket, windows, spec, NOW))
        bucket["windows"]["day"] = window("2026-11-02", 2, 2)
        self.assertEqual(q.QuotaGuard._count_anomaly(bucket, windows, spec, NOW), "")
        bucket["windows"]["month"] = window("2026-11", 5, 6)
        self.assertIn("맞지 않아", q.QuotaGuard._count_anomaly(bucket, windows, spec, NOW))

    def test_a_day_larger_than_the_month_is_an_anomaly_and_equal_is_fine(self):
        self.hub()
        self.put(day=50, month=49)
        self.assert_closed(self.denied(priority=q.CRITICAL), "unverifiable", cause=ANOMALY)
        self.put(day=50, month=50)
        self.lease(priority=q.CRITICAL)

    def test_a_month_count_below_the_highest_one_seen_is_an_anomaly_but_only_within_the_same_month(self):
        self.hub()
        self.put(month=9, audit={"high_water": {"month": "2026-11", "attempts": 10}})
        self.assert_closed(self.denied(priority=q.CRITICAL), "unverifiable", cause=ANOMALY)
        self.put(month=10, audit={"high_water": {"month": "2026-11", "attempts": 10}})
        self.lease(priority=q.CRITICAL)
        self.assertEqual(self.audit()["high_water"], {"month": "2026-11", "attempts": 11})
        self.put(month=3, audit={"high_water": {"month": "2026-10", "attempts": 5000}})                     # 지난달의 최고치는 이번 달을 막지 않는다
        self.lease(priority=q.CRITICAL)
        self.assertEqual(self.audit()["high_water"], {"month": "2026-11", "attempts": 4})

    def test_the_ledger_cannot_hold_more_calls_than_the_month_count(self):
        self.hub()
        entries = [ledger_entry(number, YESTERDAY) for number in (1, 2, 3)]
        self.put(month=2, audit={"ledger": entries, "next_id": 4})
        self.assert_closed(self.denied(priority=q.CRITICAL), "unverifiable", cause=ANOMALY)
        self.put(month=3, audit={"ledger": entries, "next_id": 4})
        self.lease(priority=q.CRITICAL)
        self.put(month=3, audit={"ledger": [ledger_entry(1, YESTERDAY, calls=5)], "next_id": 2})           # 한 번에 5회 부른 기록은 5 로 센다
        self.assertIn("unverifiable", self.denied(priority=q.CRITICAL).code)
        self.put(month=5, audit={"ledger": [ledger_entry(1, YESTERDAY, calls=5)], "next_id": 2})
        self.lease(priority=q.CRITICAL)

    def test_the_ledger_cannot_hold_more_successes_than_the_month_successes(self):
        self.hub()
        entries = [ledger_entry(number, YESTERDAY, ok=True) for number in (1, 2)]
        self.put(month=5, month_ok=1, audit={"ledger": entries, "next_id": 3})
        self.assert_closed(self.denied(priority=q.CRITICAL), "unverifiable", cause=ANOMALY)
        self.put(month=5, month_ok=2, audit={"ledger": entries, "next_id": 3})
        self.lease(priority=q.CRITICAL)

    def test_the_ledger_of_today_cannot_exceed_the_day_count_or_the_day_successes(self):
        self.hub()
        today = [ledger_entry(number, NOW) for number in (1, 2, 3)]
        self.put(day=2, month=5, audit={"ledger": today, "next_id": 4})
        self.assert_closed(self.denied(priority=q.CRITICAL), "unverifiable", cause=ANOMALY)
        self.put(day=3, month=5, audit={"ledger": today, "next_id": 4})
        self.lease(priority=q.CRITICAL)
        done = [ledger_entry(number, NOW, ok=True) for number in (1, 2)]
        self.put(day=3, month=5, day_ok=1, month_ok=2, audit={"ledger": done, "next_id": 3})
        self.assert_closed(self.denied(priority=q.CRITICAL), "unverifiable", cause=ANOMALY)
        self.put(day=3, month=5, day_ok=2, month_ok=2, audit={"ledger": done, "next_id": 3})
        self.lease(priority=q.CRITICAL)
        self.put(day=4, month=5, audit={"ledger": [ledger_entry(1, NOW, calls=5)], "next_id": 2})
        self.assertEqual(self.denied(priority=q.CRITICAL).code, "unverifiable")

    def test_a_clock_that_went_back_by_exactly_five_minutes_is_still_allowed(self):
        self.hub()
        self.guard.report(self.lease(), q.OK)
        self.at(NOW - timedelta(minutes=5))
        self.lease()
        self.assertEqual(self.audit()["last_seen"], STAMP)                                                   # 시각이 뒤로 가도 '마지막으로 본 시각' 은 되돌아가지 않는다

    def test_a_small_backward_jitter_is_allowed_and_never_lowers_the_last_seen_time(self):
        self.hub()
        self.guard.report(self.lease(), q.OK)
        for minutes in (1, 3, 4):
            self.at(NOW - timedelta(minutes=minutes))
            self.lease()
            self.assertEqual(self.audit()["last_seen"], STAMP)
        self.assertEqual(self.bucket()["windows"]["day"]["used"], 4)

    def test_a_clock_one_second_beyond_five_minutes_back_is_denied_and_nothing_moves(self):
        self.hub()
        self.guard.report(self.lease(), q.OK)
        before = self.path.read_bytes()
        self.at(NOW - timedelta(minutes=5, seconds=1))
        got = self.denied()
        self.assert_closed(got, "clock", cause="시계")
        self.assertIsNone(got.retry_at)
        self.assertEqual(got.resume_text, "")
        self.assertEqual(self.audit()["last_seen"], STAMP)
        self.assertEqual(self.bucket()["windows"]["day"]["used"], 1)
        self.assert_closed(self.guard.acquire(PURPOSE, cached=True), "clock", cached=True, cause="시계")
        led = self.guard.usage(PURPOSE)[0].ledger
        self.assertEqual((led.stopped, led.stop_code, led.stop_text), (True, "clock", FIXED))
        self.assertEqual(self.state()["buckets"], json.loads(before.decode("utf-8"))["buckets"])
        self.at(NOW + timedelta(seconds=10))                                                                   # 시계가 돌아오면 저절로 다시 열린다
        self.lease()
        self.assertEqual(self.audit()["last_seen"], stamp(NOW + timedelta(seconds=10)))

    def test_the_operator_confirmation_accepts_the_current_clock_and_reopens(self):
        self.hub()
        self.guard.report(self.lease(), q.OK)
        self.at(NOW - timedelta(hours=1))
        self.assertEqual(self.denied().code, "clock")
        self.assertEqual(self.guard.acknowledge(PURPOSE, confirmed=True), 1)
        self.assertEqual(self.audit()["last_seen"], stamp(NOW - timedelta(hours=1)))
        self.lease()
        windows = self.bucket()["windows"]
        self.assertEqual((windows["day"]["used"], windows["month"]["used"]), (2, 2))                           # 계수는 그대로 이어진다(상태 파일이 사라진 것이 아니다)

    def test_the_connection_test_call_is_stopped_by_the_clock_a_hold_and_an_anomaly_too(self):
        entry = self.hub(ok=False)
        self.assertIsInstance(self.guard.acquire_entry(entry), q.Lease)                                       # 인증 확인 전이어도 시험 호출은 된다
        self.at(NOW - timedelta(minutes=10), auth=False)
        self.assert_closed(self.guard.acquire_entry(entry), "clock", cause="시계")
        self.at(NOW, auth=False)
        self.put(audit={"hold": "state_lost"})
        self.assert_closed(self.guard.acquire_entry(entry), "unverifiable", cause="사라진 적이 있어")
        self.put(day=50, month=49)
        self.assert_closed(self.guard.acquire_entry(entry), "unverifiable", cause=ANOMALY)

    def test_a_broken_connection_settings_file_denies_with_the_fixed_sentence_and_writes_nothing(self):
        self.hub()
        self.ctx.workspace.connections_path.write_text("not json{", encoding="utf-8")
        self.assert_closed(self.guard.acquire(PURPOSE), "unavailable", cause="사용량 기록을 읽거나 쓰지 못해 이번 호출은 건너뜁니다")
        self.assertFalse(self.path.exists())

    def test_a_broken_connection_settings_file_keeps_the_old_wording_for_other_providers(self):
        self.image()
        self.ctx.workspace.connections_path.write_text("not json{", encoding="utf-8")
        got = self.guard.acquire("image_provider")
        self.assertEqual((got.code, got.cause), ("unavailable", ""))
        self.assertIn("오류 코드 CONNECTIONS_FILE_INVALID", got.reason)

    def test_without_a_check_record_the_auth_state_is_unclear_and_the_call_is_refused(self):
        self.hub(ok=False)
        self.assert_closed(self.denied(), "auth_unclear", cause="인증 상태가 확실하지 않습니다")
        self.assertFalse(self.path.exists())

    def test_a_check_success_opens_the_gate_for_exactly_twenty_four_hours(self):
        self.hub()
        self.lease()
        self.clock.now = NOW + timedelta(hours=24)
        self.lease()
        self.clock.now = NOW + timedelta(hours=24, seconds=1)
        self.assert_closed(self.denied(), "auth_unclear", cause="인증 상태가 확실하지 않습니다")
        windows = self.bucket()["windows"]
        self.assertEqual((windows["day"]["label"], windows["day"]["used"], windows["month"]["used"]), ("2026-11-03", 1, 2))             # 거절된 호출은 세지 않았다

    def test_an_auth_failure_record_stops_the_call_with_its_own_code(self):
        entry = self.hub()
        cn.mark_check(self.ctx, entry.entry_id, "auth_failed")
        self.assert_closed(self.denied(), "auth_failed", cause="인증 정보 오류")
        fresh = cn.load(self.ctx).entries[0]                                                                  # `acquire_entry` 는 부르는 쪽이 방금 읽은 항목을 믿는다
        self.assertEqual(self.guard.acquire_entry(fresh).code, "auth")                                       # 시험 호출도 인증이 실패로 멈춘 항목에는 하지 않는다

    def test_a_check_with_a_non_success_result_is_not_a_clear_auth_state(self):
        entry = self.hub(ok=False)
        cn.mark_check(self.ctx, entry.entry_id, "error")
        self.assert_closed(self.denied(), "auth_unclear", cause="인증 상태가 확실하지 않습니다")

    def test_a_lock_held_by_another_flow_denies_with_the_fixed_sentence(self):
        self.hub()
        with cn.locked(self.ctx, "quota-state"):
            got = self.guard.acquire(PURPOSE)
            cached = self.guard.acquire(PURPOSE, cached=True)
        self.assert_closed(got, "busy", cause="다른 창이 사용량을 기록하는 중")
        self.assert_closed(cached, "busy", cached=True, cause="다른 창이 사용량을 기록하는 중")
        self.assertFalse(self.path.exists())
        self.lease()

    def test_a_state_file_that_cannot_be_written_denies_the_call_and_counts_nothing(self):
        self.hub()
        with mock.patch.object(q, "write_json", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "x"})):
            self.assert_closed(self.guard.acquire(PURPOSE), "unavailable", cause="사용량 기록을 읽거나 쓰지 못해 이번 호출은 건너뜁니다")
        self.assertFalse(self.path.exists())
        self.lease()
        self.assertEqual(self.bucket()["windows"]["month"]["used"], 1)
        before = self.path.read_bytes()
        with mock.patch.object(q, "write_json", side_effect=AppError("DISK_FULL", {"경로": "x"})):
            self.assert_closed(self.guard.acquire(PURPOSE), "unavailable", cause="사용량 기록을 읽거나 쓰지 못해")
            self.assertEqual(self.guard.acquire_entry(self.entry).code, "unavailable")
        self.assertEqual(self.path.read_bytes(), before)

    def test_a_closed_request_is_also_answered_with_the_fixed_sentence(self):
        self.hub()
        first = self.lease()
        self.guard.report(first, q.OK)
        self.assert_closed(self.guard.acquire(PURPOSE, request=first.request), "closed", cause="이 일은 이미 끝났습니다")

    def test_without_a_key_the_call_is_skipped_with_the_ordinary_no_key_wording(self):
        got = self.guard.acquire(PURPOSE)
        self.assertIsInstance(got, q.Denied)
        self.assertEqual((got.code, got.cause), ("no_key", ""))
        self.assertEqual(got.reason, "연결된 키가 없어 이 보조 기능만 건너뜁니다(키가 없어도 핵심 기능은 그대로 됩니다)")
        self.assertNotEqual(got.reason, FIXED)


class StageTest(HubCase):
    USED = (20998, 20999, 21000, 21001, 23994, 23995, 23998, 23999, 24000, 24001, 26994, 26995, 26996, 26997, 26998, 26999, 27000)
    NOTICE, LIMITED = cn.APIHUB_STAGES[0].text, cn.APIHUB_STAGES[1].text

    @staticmethod
    def allowed(priority, after, calls):
        if after > 27000:
            return False
        if priority == q.BULK:
            return after <= 24000
        if priority == q.NEW:
            return after <= 24000 or calls <= 5
        return True

    def test_the_whole_table_of_priorities_and_calls_around_each_threshold(self):
        self.hub()
        for used in self.USED:
            for calls in (1, 2, 5, 6):
                for priority in q.PRIORITIES:
                    with self.subTest(used=used, calls=calls, priority=priority):
                        self.put(month=used)
                        got = self.guard.acquire(PURPOSE, calls=calls, priority=priority)
                        after = used + calls
                        self.assertEqual(isinstance(got, q.Lease), self.allowed(priority, after, calls), got)
                        if isinstance(got, q.Denied):
                            self.assertEqual((got.code, got.retry_at), ("exhausted" if after > 27000 else "saving_mode", NEXT_MONTH))
                            self.assertEqual(got.reason, FIXED)

    def test_the_notice_comes_with_the_call_that_ends_above_seventy_percent_for_every_priority(self):
        self.hub()
        for priority in q.PRIORITIES:
            for used, expected in ((20998, ""), (20999, ""), (21000, self.NOTICE), (21001, self.NOTICE), (23998, self.NOTICE), (23999, self.NOTICE), (24000, self.LIMITED), (26999, self.LIMITED)):
                if priority == q.BULK and used >= 24000:
                    continue                                                   # 자동 새로고침은 80% 를 넘으면 받지 못한다(아래 시험)
                with self.subTest(priority=priority, used=used):
                    self.put(month=used)
                    got = self.lease(priority=priority)
                    self.assertEqual(got.notice, expected)

    def test_a_stage_denial_asks_the_caller_to_use_the_saved_value_when_it_has_one(self):
        self.hub()
        self.put(month=24000)
        got = self.guard.acquire(PURPOSE, priority=q.BULK, cached=True)
        self.assert_closed(got, "saving_mode", cached=True, cause="자동 새로고침과 자동 배치를 멈췄습니다")
        self.put(month=27000)
        self.assert_closed(self.guard.acquire(PURPOSE, priority=q.CRITICAL, cached=True), "exhausted", cached=True, cause="이번 달 내부 한도")

    def test_automatic_refresh_stops_above_eighty_percent_and_says_why(self):
        self.hub()
        self.put(month=23999)
        self.lease(priority=q.BULK)
        self.assertEqual(self.bucket()["windows"]["month"]["used"], 24000)
        got = self.denied(priority=q.BULK)
        self.assert_closed(got, "saving_mode", cause="자동 새로고침과 자동 배치를 멈췄습니다")
        self.assertEqual((got.retry_at, got.resume_text), (NEXT_MONTH, "12월 01일 00:00 이후 자동 재개"))
        self.put(month=23999)
        self.assertEqual(self.denied(priority=q.BULK, calls=2).code, "saving_mode")                          # 이 호출 뒤 24,001 이 되는 것도 받지 않는다

    def test_a_manual_analysis_may_call_five_at_a_time_after_eighty_percent_and_any_number_before(self):
        self.hub()
        self.put(month=24000)
        self.lease(priority=q.NEW, calls=5)
        self.put(month=24000)
        self.assert_closed(self.denied(priority=q.NEW, calls=6), "saving_mode", cause="한 번에 5회까지")
        self.put(month=18000)
        self.lease(priority=q.NEW, calls=6)                                                                  # 80% 를 넘기 전에는 상한이 없다
        self.put(month=23994)
        self.lease(priority=q.NEW, calls=6)                                                                  # 이 호출 뒤 24,000 — 아직 넘지 않았다
        self.put(month=23995)
        self.assertEqual(self.denied(priority=q.NEW, calls=6).code, "saving_mode")                           # 24,001 이 되니 상한 적용
        self.put(month=26998)
        self.assertEqual(self.denied(priority=q.NEW, calls=3).code, "exhausted")                              # 상한 안이어도 월 한도를 넘는다
        self.put(month=26997)
        self.lease(priority=q.NEW, calls=3)

    def test_everything_but_automatic_refresh_goes_on_until_the_internal_month_limit(self):
        self.hub()
        for priority in (q.NEW, q.SELECTED, q.CRITICAL):
            with self.subTest(priority=priority):
                self.put(month=26999)
                self.lease(priority=priority)
                self.assertEqual(self.denied(priority=priority).code, "exhausted")
        self.put(month=26999)
        self.assertEqual(self.denied(priority=q.CRITICAL, calls=2).code, "exhausted")

    def test_at_the_month_limit_every_priority_including_critical_is_refused_until_next_month(self):
        self.hub()
        self.put(month=27000)
        for priority in q.PRIORITIES:
            with self.subTest(priority=priority):
                got = self.denied(priority=priority)
                self.assert_closed(got, "exhausted", cause="이번 달 내부 한도(27,000회)를 다 썼습니다")
                self.assertEqual(got.retry_at, NEXT_MONTH)

    def test_this_provider_keeps_no_ten_percent_reserve_for_the_day_or_the_month(self):
        self.hub()
        for priority in q.PRIORITIES:
            with self.subTest(priority=priority, window="day"):
                self.put(day=99, month=99)
                self.lease(priority=priority)
                self.assertEqual(self.denied(priority=priority).code, "exhausted")
        self.put(day=0, month=23000)
        self.lease(priority=q.BULK)                                                                        # 옛 규칙(남은 몫 30% 이상)이었다면 이미 받지 못했을 자리
        self.put(day=0, month=26000)
        self.lease(priority=q.SELECTED)

    def test_the_usage_view_names_the_stage_by_the_next_call(self):
        self.hub()
        stages = ((20998, "ok", ""), (20999, "ok", ""), (21000, "notice", self.NOTICE), (23999, "notice", self.NOTICE), (24000, "limited", self.LIMITED), (26999, "limited", self.LIMITED),
                  (27000, "closed", cn.APIHUB_STAGES[2].text))
        for used, name, text in stages:
            with self.subTest(used=used):
                self.put(month=used)
                led = self.guard.usage(PURPOSE)[0].ledger
                self.assertEqual((led.stage, led.stage_text, led.month_attempts), (name, text, used))
                self.assertEqual(led.stopped, used == 27000)
        self.put(month=27000)
        led = self.guard.usage(PURPOSE)[0].ledger
        self.assertEqual((led.stop_code, led.stop_cause, led.stop_text), ("exhausted", "이번 달 내부 한도(27,000회)를 다 썼습니다", FIXED))

    def test_the_near_limit_flag_follows_the_stage_for_the_month_and_the_limit_for_the_day(self):
        self.hub()
        cases = (({"day": 99, "month": 99}, False, False), ({"day": 100, "month": 100}, True, False), ({"day": 0, "month": 21000}, False, False), ({"day": 0, "month": 23999}, False, False),
                 ({"day": 0, "month": 24000}, False, True), ({"day": 0, "month": 26999}, False, True), ({"day": 0, "month": 27000}, False, True))
        for counts, day_near, month_near in cases:
            with self.subTest(counts=counts):
                self.put(**counts)
                view = self.guard.usage(PURPOSE)[0]
                near = {row.window: row.near_limit for row in view.rows}
                self.assertEqual((near["day"], near["month"]), (day_near, month_near))
                self.assertEqual(view.saving_mode, day_near or month_near)

    def test_the_other_providers_keep_their_ten_percent_reserve(self):
        self.image()
        entry = cn.load(self.ctx).entries[0]
        state = {"schema": 1, "buckets": {q.bucket_key(entry): {"windows": {"hour": {"label": "", "used": 0, "minutes": {"2026-11-02T01:30": 45}, "limit": 0, "limit_at": ""}}, "blocked_until": "",
                                                                 "block_kind": "", "backoff": 0}}, "failovers": []}
        self.ctx.workspace.quota_path.write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual(self.guard.acquire("image_provider", priority=q.SELECTED).code, "saving_mode")        # 50 중 45 를 쓰면 일반 호출은 절약 모드
        self.assertIsInstance(self.guard.acquire("image_provider", priority=q.CRITICAL), q.Lease)


class RotationTest(HubCase):
    def test_a_rate_limit_answer_stops_without_trying_another_key_and_rests_five_seconds(self):
        self.hub()
        lease = self.lease(kind="search_trend")
        result = self.guard.report(lease, q.RATE_LIMITED, status=429)
        self.assertEqual(result.action, q.ACT_STOP)
        self.assertEqual(result.blocked_until, NOW + timedelta(seconds=5))
        self.assertTrue(result.advice)
        bucket = self.bucket()
        self.assertEqual((bucket["blocked_until"], bucket["block_kind"], bucket["backoff"]), (stamp(NOW + timedelta(seconds=5)), "rate_limited", 1))
        got = self.denied()
        self.assert_closed(got, "blocked", cause="한도 초과 응답을 받아 잠시 쉬는 중입니다")
        self.assertEqual(got.retry_at, NOW + timedelta(seconds=5))
        self.at(NOW + timedelta(seconds=4))
        self.assertEqual(self.denied().code, "blocked")
        self.at(NOW + timedelta(seconds=5))
        self.lease()

    def test_a_retry_after_header_longer_than_the_backoff_is_obeyed(self):
        self.hub()
        result = self.guard.report(self.lease(), q.RATE_LIMITED, retry_after="120", status=429)
        self.assertEqual(result.blocked_until, NOW + timedelta(seconds=120))
        self.assertEqual(self.denied().retry_at, NOW + timedelta(seconds=120))

    def test_a_second_entry_can_never_exist_so_there_is_nothing_to_rotate_to(self):
        entry = self.hub()
        data = cn.load(self.ctx)
        self.assertFalse(self.guard._may_switch(data, PURPOSE, [entry, entry], entry))
        self.assertEqual(cn.PURPOSES[PURPOSE].fallback_providers, ())
        path = self.ctx.workspace.connections_path
        raw = json.loads(path.read_text(encoding="utf-8"))
        twin = dict(raw["entries"][0])
        twin.update({"entry_id": "ab" * 16, "name": "복제", "order": 2})
        raw["entries"].append(twin)
        path.write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(ss.code_of(cn.load, self.ctx).code, "CONNECTIONS_FILE_INVALID")
        self.assert_closed(self.guard.acquire(PURPOSE), "unavailable", cause="사용량 기록을 읽거나 쓰지 못해")

    def test_an_exhausted_answer_keeps_the_real_attempt_counts_and_rests_until_the_first_of_next_month_korean_time(self):
        """서버가 기간 한도 소진을 알리면 월 창이 있는 제공자는 '다음 한국 자정' 이 아니라 다음 달 1일 00:00(한국 시간)까지 쉰다 — 이틀 뒤 같은 달에 다시 열리지 않는다(독립 검증 지적 1). 시도 수는 채워 넣지 않는다."""
        self.hub()
        result = self.guard.report(self.lease(), q.QUOTA_EXHAUSTED, status=429)
        self.assertEqual((result.action, result.blocked_until), (q.ACT_STOP, NEXT_MONTH))
        windows = self.bucket()["windows"]
        self.assertEqual((windows["day"]["used"], windows["month"]["used"]), (1, 1))                           # 한도까지 채워 넣지 않는다
        bucket = self.bucket()
        self.assertEqual((bucket["blocked_until"], bucket["block_kind"]), (stamp(NEXT_MONTH), "quota_exhausted"))
        got = self.denied()
        self.assert_closed(got, "blocked", cause="서비스가 기간 한도를 다 썼다고 알려 와 다음 초기화 때까지 쉽니다")
        self.assertEqual(got.retry_at, NEXT_MONTH)
        self.assertEqual(got.resume_text, "12월 01일 00:00 이후 자동 재개")

    def test_an_exhausted_answer_with_a_reset_time_rests_until_that_time(self):
        self.hub()
        result = self.guard.report(self.lease(), q.QUOTA_EXHAUSTED, reset_at=NOW + timedelta(hours=1))
        self.assertEqual(result.blocked_until, NOW + timedelta(hours=1))

    def test_an_auth_failure_stops_the_entry_and_the_next_call_is_refused_with_its_own_code(self):
        self.hub()
        result = self.guard.report(self.lease(), q.AUTH_FAILED, status=401)
        self.assertEqual(result.action, q.ACT_STOP)
        self.assertTrue(result.advice)
        self.assertEqual(cn.load(self.ctx).entries[0].check_result, "auth_failed")
        self.assert_closed(self.denied(), "auth_failed", cause="인증 정보 오류")

    def test_a_server_error_is_retried_once_with_the_same_key_and_then_stops(self):
        self.hub()
        first = self.lease(kind="search_trend")
        self.assertEqual(self.guard.report(first, q.TRANSIENT, status=503).action, q.ACT_RETRY)
        second = self.lease(request=first.request, kind="search_trend")
        self.assertEqual((second.entry_id, second.call_id), (first.entry_id, 2))
        self.assertEqual(self.guard.report(second, q.TRANSIENT, status=503).action, q.ACT_STOP)
        self.assertEqual([(item["retries"], item["status"], item["outcome"]) for item in self.audit()["ledger"]], [(0, 503, "transient_error"), (1, 503, "transient_error")])
        windows = self.bucket()["windows"]
        self.assertEqual((windows["day"]["used"], windows["day"]["successes"]), (2, 0))
        self.assert_closed(self.guard.acquire(PURPOSE, request=first.request), "closed", cause="이 일은 이미 끝났습니다")


class ExhaustedRestTest(HubCase):
    """서버가 기간 한도 소진(`quota_exhausted`)을 알렸을 때 쉬는 시각 — 월 창이 있는 제공자는 다음 달 1일 00:00(한국 시간), 일 창만 있는 제공자는 그대로 다음 한국 자정(독립 검증 지적 1)."""

    def test_the_rest_ends_at_korean_midnight_of_the_first_of_the_next_month_for_any_moment_of_the_month(self):
        """달의 처음·한가운데·마지막 1초·새 달 정각·12월(다음 해 1월)·윤년 2월 — 쉬는 시각이 '다음 달 1일 00:00(한국)' 이고 결과·저장한 막힘 시각·거절의 다시 열릴 시각이 모두 같다."""
        cases = ((datetime(2026, 11, 1, 15, 0, 0, tzinfo=UTC), datetime(2026, 11, 30, 15, 0, 0, tzinfo=UTC)),      # 한국 11-02 00:00:00 → 12-01 00:00
                 (NOW, NEXT_MONTH),
                 (datetime(2026, 11, 30, 14, 59, 59, tzinfo=UTC), datetime(2026, 11, 30, 15, 0, 0, tzinfo=UTC)),      # 한국 11-30 23:59:59 → 1초 뒤
                 (datetime(2026, 11, 30, 15, 0, 0, tzinfo=UTC), datetime(2026, 12, 31, 15, 0, 0, tzinfo=UTC)),        # 한국 12-01 00:00:00 정각 — 새 달이 이미 시작됐으니 그다음 달(1월 1일)
                 (datetime(2026, 12, 15, 3, 0, 0, tzinfo=UTC), datetime(2026, 12, 31, 15, 0, 0, tzinfo=UTC)),         # 12월 → 다음 해 1월 1일 00:00(한국)
                 (datetime(2028, 2, 10, 3, 0, 0, tzinfo=UTC), datetime(2028, 2, 29, 15, 0, 0, tzinfo=UTC)))           # 윤년 2월 → 3월 1일 00:00(한국) = 2월 29일 15:00(UTC)
        for moment, expected in cases:
            with self.subTest(moment=moment):
                self.setUp()
                self.clock.now = moment
                self.hub()
                result = self.guard.report(self.lease(), q.QUOTA_EXHAUSTED, status=429)
                self.assertEqual((result.action, result.blocked_until), (q.ACT_STOP, expected))
                self.assertEqual(self.bucket()["blocked_until"], stamp(expected))
                self.assertEqual(self.denied().retry_at, expected)

    def test_two_days_later_in_the_same_month_it_is_still_closed_and_it_opens_exactly_at_the_new_month(self):
        """옛 동작(다음 한국 자정)이면 이틀 뒤 같은 달에 다시 열렸다 — 이제 다음 달 1일 00:00 한 초 전까지 닫혀 있고 그 정각에 열린다."""
        self.hub()
        self.guard.report(self.lease(), q.QUOTA_EXHAUSTED, status=429)
        for moment in (NOW + timedelta(hours=1), NEXT_MIDNIGHT - timedelta(seconds=1), NEXT_MIDNIGHT, NOW + timedelta(days=2), NEXT_MIDNIGHT + timedelta(days=1), NEXT_MONTH - timedelta(seconds=1)):
            with self.subTest(moment=moment):
                self.at(moment)
                got = self.denied()
                self.assert_closed(got, "blocked", cause="서비스가 기간 한도를 다 썼다고 알려 와 다음 초기화 때까지 쉽니다")
                self.assertEqual(got.retry_at, NEXT_MONTH)
        self.at(NEXT_MONTH)
        self.lease()
        windows = self.bucket()["windows"]
        self.assertEqual((windows["month"]["label"], windows["month"]["used"], windows["day"]["label"], windows["day"]["used"]), ("2026-12", 1, "2026-12-01", 1))

    def test_a_server_reset_time_within_forty_eight_hours_wins_and_a_farther_past_or_naive_one_is_ignored(self):
        """서버가 48시간 안의 초기화 시각을 알려 주면 그 시각(경계 48시간 정각 포함), 48시간을 넘거나 지났거나 시간대가 없으면 믿지 않고 다음 달 1일."""
        cases = ((timedelta(hours=1), NOW + timedelta(hours=1)), (timedelta(hours=48), NOW + timedelta(hours=48)), (timedelta(hours=48, seconds=1), NEXT_MONTH), (timedelta(days=20), NEXT_MONTH),
                 (timedelta(0), NEXT_MONTH), (timedelta(seconds=-1), NEXT_MONTH))
        for offset, expected in cases:
            with self.subTest(offset=offset):
                self.setUp()
                self.hub()
                self.assertEqual(self.guard.report(self.lease(), q.QUOTA_EXHAUSTED, reset_at=NOW + offset).blocked_until, expected)
        self.setUp()
        self.hub()
        self.assertEqual(self.guard.report(self.lease(), q.QUOTA_EXHAUSTED, reset_at=datetime(2026, 11, 2, 5, 0, 0)).blocked_until, NEXT_MONTH)

    def test_the_rest_depends_on_which_windows_the_provider_has(self):
        """월 창이 하나라도 있으면 다음 달 1일(일 창이 같이 있어도), 일 창만이면 다음 한국 자정, 슬라이딩 창뿐이면 그 길이, 창이 없으면 60분."""
        spec = cn.PURPOSES[PURPOSE]
        day, month, hour = cn.Window("day", "day", 100), cn.Window("month", "month", 27000), cn.Window("hour", "sliding", 50, 60, True)
        cases = (((day, month), NEXT_MONTH), ((month, day), NEXT_MONTH), ((month,), NEXT_MONTH), ((day,), NEXT_MIDNIGHT), ((hour,), NOW + timedelta(minutes=60)), ((), NOW + timedelta(minutes=60)))
        for windows, expected in cases:
            with self.subTest(windows=[item.kind for item in windows]):
                self.assertEqual(self.guard._exhaust_until(spec, windows, NOW, None), expected)

    def test_a_day_only_provider_still_rests_until_the_next_korean_midnight_and_fills_its_window(self):
        """일 창만 있는 제공자(시험용 일반 용도 — 옛 `naver_openapi` 정의)는 지금까지처럼 다음 한국 자정까지 쉬고 창을 한도까지 채운다(다른 용도의 동작은 그대로)."""
        registry = ss.generic_registry()
        guard = q.QuotaGuard(self.ctx, registry=registry, lock_wait=0)
        entry = cn.add_entry(self.ctx, "naver_openapi", name="일반", fields={"client_id": "legacyid0001", "client_secret": "legacysecret01"}, project="앱", registry=registry).entry
        lease = guard.acquire("naver_openapi")
        self.assertIsInstance(lease, q.Lease, lease)
        result = guard.report(lease, q.QUOTA_EXHAUSTED, status=429)
        self.assertEqual((result.action, result.blocked_until), (q.ACT_STOP, NEXT_MIDNIGHT))
        held = self.state()["buckets"][q.bucket_key(entry)]
        self.assertEqual((held["windows"]["day"]["used"], held["blocked_until"]), (25000, stamp(NEXT_MIDNIGHT)))
        self.assertNotIn("audit", held)


class AuthRefreshTest(HubCase):
    """성공한 실제 호출의 보고가 마지막 성공 시각을 갱신해 인증 '맑음' 의 24시간 창을 이어 준다(독립 검증 지적 2). 실패·모호한 결과·다른 제공자·인증 실패로 멈춘 항목은 갱신하지 않는다."""

    def entry_now(self):
        return cn.load(self.ctx).entries[0]

    def reported(self, outcome, *, hours=5, **kwargs):
        """새 항목(연결 시험 성공 = NOW)으로 시작해 `hours` 시간 뒤에 호출을 잡고 `outcome` 을 보고한 다음의 항목."""
        self.setUp()
        self.hub()
        self.at(NOW + timedelta(hours=hours), auth=False)
        self.guard.report(self.lease(), outcome, **kwargs)
        return self.entry_now()

    def test_a_successful_report_refreshes_the_last_success_time_and_leaves_the_test_time_alone(self):
        """성공 보고 → `last_ok_at` 이 그 시각, 확인 결과 ok, 마지막 시험 시각(`checked_at`)은 그대로(연결 시험의 60초 규칙은 시험 호출만 센다)."""
        entry = self.reported(q.OK, status=200)
        self.assertEqual((entry.last_ok_at, entry.check_result, entry.checked_at), (stamp(NOW + timedelta(hours=5)), "ok", STAMP))

    def test_each_success_carries_the_twenty_four_hour_window_on_to_the_second(self):
        """연결 시험 성공 23시간 뒤의 성공 보고가 창을 이어 줘서 47시간 정각까지 맑고 1초 뒤에는 불명확 — 보고가 없었다면 24시간 뒤부터 불명확이었다."""
        self.hub()
        self.at(NOW + timedelta(hours=23), auth=False)
        self.guard.report(self.lease(), q.OK, status=200)
        self.at(NOW + timedelta(hours=47), auth=False)
        self.lease()
        self.at(NOW + timedelta(hours=47, seconds=1), auth=False)
        self.assert_closed(self.denied(), "auth_unclear", cause="인증 상태가 확실하지 않습니다")
        self.setUp()
        self.hub()
        self.at(NOW + timedelta(hours=24), auth=False)
        self.lease()
        self.at(NOW + timedelta(hours=24, seconds=1), auth=False)
        self.assert_closed(self.denied(), "auth_unclear", cause="인증 상태가 확실하지 않습니다")

    def test_a_failure_of_any_kind_never_refreshes_the_last_success_time(self):
        """실패 9종(429·기간 한도·일시 오류·시간 초과·인증 실패·잘못된 요청·정책 차단·콘텐츠 차단·그 밖의 오류) 어느 것도 `last_ok_at` 을 바꾸지 않는다. 인증 실패만 확인 결과를 auth_failed 로 하고(그때 시각이 `checked_at`) 나머지는 `checked_at` 도 그대로다."""
        for outcome, status in FAILURES.items():
            with self.subTest(outcome=outcome):
                entry = self.reported(outcome, status=status)
                self.assertEqual(entry.last_ok_at, STAMP)
                if outcome == q.AUTH_FAILED:
                    self.assertEqual((entry.check_result, entry.checked_at), ("auth_failed", stamp(NOW + timedelta(hours=5))))
                else:
                    self.assertEqual((entry.check_result, entry.checked_at), ("ok", STAMP))

    def test_a_success_with_an_ambiguous_status_or_an_unused_response_does_not_refresh(self):
        """성공이라는데 응답 상태가 2xx 가 아니거나(199·300·404·500·599) 응답을 못 썼다고 알린 보고는 모호해서 갱신하지 않고, 상태가 2xx(200·204·299)이거나 안 적은(None) 보고는 갱신한다."""
        fresh, stale = stamp(NOW + timedelta(hours=5)), STAMP
        cases = (({"status": 199}, stale), ({"status": 300}, stale), ({"status": 404}, stale), ({"status": 500}, stale), ({"status": 599}, stale), ({"status": 200, "used_response": False}, stale),
                 ({"used_response": False}, stale), ({"status": 200}, fresh), ({"status": 204}, fresh), ({"status": 299}, fresh), ({}, fresh), ({"status": 200, "used_response": True}, fresh))
        for kwargs, expected in cases:
            with self.subTest(**kwargs):
                self.assertEqual(self.reported(q.OK, **kwargs).last_ok_at, expected)

    def test_a_late_success_does_not_revive_an_entry_stopped_for_failed_authentication(self):
        """인증 실패로 멈춘 뒤에 먼저 잡아 둔 호출의 성공 보고가 늦게 와도 항목은 되살아나지 않고(확인 결과 auth_failed·`last_ok_at` 그대로) 다음 호출은 인증 실패 코드로 거절된다."""
        self.hub()
        first, second = self.lease(), self.lease()
        self.guard.report(first, q.AUTH_FAILED, status=401)
        self.at(NOW + timedelta(hours=1), auth=False)
        self.guard.report(second, q.OK, status=200)
        entry = self.entry_now()
        self.assertEqual((entry.check_result, entry.last_ok_at), ("auth_failed", STAMP))
        self.assert_closed(self.denied(), "auth_failed", cause="인증 정보 오류")

    def test_providers_without_the_fail_closed_gate_do_not_touch_the_connection_file_on_success(self):
        """Fail-Closed 가 아닌 제공자(이미지 공급자)의 성공 보고는 연결 설정 파일을 쓰지 않는다 — 바이트가 그대로다(다른 용도의 동작은 그대로)."""
        self.image()
        path = self.ctx.workspace.connections_path
        before = path.read_bytes()
        lease = self.guard.acquire("image_provider")
        self.assertIsInstance(lease, q.Lease, lease)
        self.guard.report(lease, q.OK, status=200)
        self.assertEqual(path.read_bytes(), before)

    def test_mark_call_ok_changes_only_the_last_success_and_the_check_result_and_never_revives_a_stopped_entry(self):
        """`connections.mark_call_ok` — 없는 항목은 None(파일 그대로), 정상 항목은 `last_ok_at`·확인 결과 ok 만 바뀌고 나머지 칸은 같고, 시험 오류(error) 항목은 ok 가 되고, 인증 실패(auth_failed) 항목은 None 이고 파일 그대로."""
        entry = self.hub(ok=False)
        path = self.ctx.workspace.connections_path
        before = path.read_bytes()
        self.assertIsNone(cn.mark_call_ok(self.ctx, "ff" * 16))
        self.assertEqual(path.read_bytes(), before)
        self.clock.now = NOW + timedelta(hours=2)
        changed = cn.mark_call_ok(self.ctx, entry.entry_id)
        self.assertEqual((changed.last_ok_at, changed.check_result), (stamp(NOW + timedelta(hours=2)), "ok"))
        self.assertEqual({key: value for key, value in changed.to_dict().items() if key not in ("last_ok_at", "check_result")},
                         {key: value for key, value in entry.to_dict().items() if key not in ("last_ok_at", "check_result")})
        cn.mark_check(self.ctx, entry.entry_id, "error")
        self.assertEqual(cn.mark_call_ok(self.ctx, entry.entry_id).check_result, "ok")
        cn.mark_check(self.ctx, entry.entry_id, "auth_failed")
        stopped = path.read_bytes()
        self.assertIsNone(cn.mark_call_ok(self.ctx, entry.entry_id))
        self.assertEqual(path.read_bytes(), stopped)

    def test_a_success_report_that_cannot_write_the_connection_file_still_keeps_the_usage_record(self):
        """연결 설정 파일을 못 써서 보고가 오류로 끝나도 사용량(성공 수·장부)은 이미 저장돼 있다 — 한도 기록을 먼저 저장하고 마지막 성공 시각을 적는다."""
        self.hub()
        lease = self.lease()
        with mock.patch.object(cn, "save", side_effect=AppError("FILE_WRITE_FAILED")):
            with self.assertRaises(AppError):
                self.guard.report(lease, q.OK, status=200)
        windows = self.bucket()["windows"]
        self.assertEqual((windows["day"]["used"], windows["day"]["successes"], windows["month"]["successes"]), (1, 1, 1))
        self.assertEqual(self.audit()["ledger"][0]["ok"], True)


class LegacyAcquireTest(HubCase):
    """옛 용도(`naver_openapi`)로는 호출 몫을 주지 않는다 — 쉬운 한국어로 거절하고 새 용도로 안내한다(독립 검증 지적 7)."""

    def setUp(self):
        super().setUp()
        self.registry = ss.generic_registry()
        self.legacy = cn.add_entry(self.ctx, "naver_openapi", name="옛 기본", fields={"client_id": "legacyid0001", "client_secret": "legacysecret01"}, project="앱", registry=self.registry).entry

    def check(self, got):
        self.assertIsInstance(got, q.Denied, got)
        self.assertEqual((got.code, got.degraded, got.use_cache, got.retry_at, got.resume_text, got.cause), ("legacy", True, False, None, "", ""))
        for text in ("옛 용도라 호출하지 않습니다", "NAVER API HUB 검색어 트렌드", "naver_apihub", "옛 항목의 키는 지우지 않았습니다"):
            self.assertIn(text, got.reason)
        self.assertIsNone(re.search(r"[A-Z]{3,}_[A-Z_]+", got.reason), got.reason)

    def test_the_legacy_purpose_is_refused_for_every_priority_count_and_cache_flag_without_touching_the_usage_file(self):
        """우선순위 4종 × 횟수 × 저장해 둔 값 표시 어느 것으로도 거절이고 사용량 파일은 만들어지지도 않는다."""
        guard = q.QuotaGuard(self.ctx, lock_wait=0)
        for priority in q.PRIORITIES:
            for calls in (1, 5):
                for cached in (False, True):
                    with self.subTest(priority=priority, calls=calls, cached=cached):
                        self.check(guard.acquire("naver_openapi", calls, priority=priority, cached=cached))
        self.assertFalse(self.path.exists())

    def test_the_connection_test_call_of_a_legacy_entry_is_refused_too(self):
        """`acquire_entry` 로 옛 항목을 콕 집어 잡아도 거절이고 사용량 파일은 그대로 없다."""
        self.check(q.QuotaGuard(self.ctx, lock_wait=0).acquire_entry(self.legacy))
        self.assertFalse(self.path.exists())

    def test_the_legacy_purpose_is_refused_even_with_no_entry_at_all_instead_of_saying_there_is_no_key(self):
        """항목이 하나도 없어도 옛 용도는 '연결된 키가 없어' 가 아니라 옛 용도 거절이다."""
        cn.remove_entry(self.ctx, self.legacy.entry_id[:8], confirmed=True)
        self.check(q.QuotaGuard(self.ctx, lock_wait=0).acquire("naver_openapi"))

    def test_other_purposes_and_a_registry_that_opens_the_purpose_still_give_calls(self):
        """옛 용도 거절은 `legacy_to` 가 있는 용도에만 — 새 용도·이미지 공급자는 그대로 몫을 받고, 일반 시험 레지스트리(`legacy_to` 가 빈 옛 정의)의 같은 이름 용도도 몫을 받는다."""
        self.hub()
        self.image()
        guard = q.QuotaGuard(self.ctx, lock_wait=0)
        self.assertIsInstance(guard.acquire(PURPOSE), q.Lease)
        self.assertIsInstance(guard.acquire("image_provider"), q.Lease)
        self.assertIsInstance(q.QuotaGuard(self.ctx, registry=self.registry, lock_wait=0).acquire("naver_openapi"), q.Lease)


class SchemaTest(HubCase):
    @staticmethod
    def good_v2():
        return {"schema": 2, "buckets": {"naver_apihub/-/id-abcd1234": {"windows": {"day": window("2026-11-02", 3, 2), "month": window("2026-11", 5, 4)}, "blocked_until": "", "block_kind": "", "backoff": 0,
                                                                         "audit": {"last_seen": STAMP, "high_water": {"month": "2026-11", "attempts": 5}, "last_success": STAMP,
                                                                                   "last_error": {"at": STAMP, "outcome": "rate_limited", "status": 429}, "hold": "", "next_id": 3,
                                                                                   "ledger": [ledger_entry(1, NOW, ok=True), ledger_entry(2, NOW)]}}}, "failovers": []}

    def test_both_versions_are_readable_and_the_pinned_good_example_is_valid(self):
        self.assertTrue(q._valid_state({"schema": 1, "buckets": {}, "failovers": []}))
        self.assertTrue(q._valid_state({"schema": 2, "buckets": {}, "failovers": []}))
        self.assertTrue(q._valid_state(self.good_v2()))
        held = self.good_v2()
        held["buckets"]["naver_apihub/-/id-abcd1234"]["audit"]["hold"] = "state_lost"
        self.assertTrue(q._valid_state(held))

    def test_a_schema_number_that_is_not_one_or_two_is_refused(self):
        for value in (True, False, 0, 3, -1, "1", "2", None, [1]):
            with self.subTest(value=value):
                self.assertFalse(q._valid_state({"schema": value, "buckets": {}, "failovers": []}))

    def test_every_shape_rule_of_the_ledger_parts_is_enforced(self):
        key = "naver_apihub/-/id-abcd1234"

        def mutate(change):
            raw = copy.deepcopy(self.good_v2())
            change(raw["buckets"][key], raw)
            return raw

        entry = lambda raw: raw["audit"]["ledger"][0]        # noqa: E731
        rules = {
            "창에 successes 가 없다": lambda b, r: b["windows"]["day"].pop("successes"),
            "successes 가 시도보다 많다": lambda b, r: b["windows"]["month"].update({"successes": 6}),
            "successes 가 글이다": lambda b, r: b["windows"]["month"].update({"successes": "4"}),
            "audit 에 모르는 칸": lambda b, r: b["audit"].update({"extra": 1}),
            "audit 에 빠진 칸": lambda b, r: b["audit"].pop("ledger"),
            "hold 값이 낯설다": lambda b, r: b["audit"].update({"hold": "other"}),
            "last_seen 이 글자 모양이 아니다": lambda b, r: b["audit"].update({"last_seen": "2026-11-02 01:30:12"}),
            "last_success 가 글자 모양이 아니다": lambda b, r: b["audit"].update({"last_success": "어제"}),
            "high_water 달 라벨이 틀렸다": lambda b, r: b["audit"]["high_water"].update({"month": "2026-1"}),
            "high_water 횟수가 음수다": lambda b, r: b["audit"]["high_water"].update({"attempts": -1}),
            "high_water 에 모르는 칸": lambda b, r: b["audit"]["high_water"].update({"x": 1}),
            "last_error 결과가 낯설다": lambda b, r: b["audit"]["last_error"].update({"outcome": "boom"}),
            "last_error 상태가 600 이다": lambda b, r: b["audit"]["last_error"].update({"status": 600}),
            "next_id 가 참거짓이다": lambda b, r: b["audit"].update({"next_id": True}),
            "next_id 가 음수다": lambda b, r: b["audit"].update({"next_id": -1}),
            "장부 항목의 시각이 틀렸다": lambda b, r: entry(b).update({"started": "2026-11-02 01:30:12"}),
            "장부 항목의 시작 시각이 비었다": lambda b, r: entry(b).update({"started": ""}),
            "장부 항목의 끝 시각이 틀렸다": lambda b, r: entry(b).update({"finished": "x"}),
            "장부 항목의 조건 해시가 16진수가 아니다": lambda b, r: entry(b).update({"condition": "XYZ"}),
            "장부 항목의 조건 해시가 13자다": lambda b, r: entry(b).update({"condition": "a" * 13}),
            "장부 항목의 결과가 낯설다": lambda b, r: entry(b).update({"outcome": "boom"}),
            "장부 항목의 종류에 대문자": lambda b, r: entry(b).update({"kind": "Search"}),
            "장부 항목의 종류가 41자다": lambda b, r: entry(b).update({"kind": "a" * 41}),
            "장부 항목의 상태가 600 이다": lambda b, r: entry(b).update({"status": 600}),
            "장부 항목의 호출 수가 음수다": lambda b, r: entry(b).update({"calls": -1}),
            "장부 항목의 호출 수가 참거짓이다": lambda b, r: entry(b).update({"calls": True}),
            "장부 항목의 ok 가 숫자다": lambda b, r: entry(b).update({"ok": 1}),
            "장부 항목의 cache_hit 가 글이다": lambda b, r: entry(b).update({"cache_hit": "no"}),
            "장부 항목에 모르는 칸": lambda b, r: entry(b).update({"extra": 1}),
            "장부 항목에 빠진 칸": lambda b, r: entry(b).pop("retries"),
            "장부가 201건이다": lambda b, r: b["audit"].update({"ledger": [ledger_entry(number, NOW) for number in range(1, 202)]}),
            "묶음에 모르는 칸": lambda b, r: b.update({"extra": 1}),
            "묶음의 backoff 가 음수다": lambda b, r: b.update({"backoff": -1}),
            "묶음의 block_kind 가 낯설다": lambda b, r: b.update({"block_kind": "other"}),
            "failovers 가 1001건이다": lambda b, r: r.update({"failovers": [{"at": "a", "purpose": "b", "from": "c", "to": "d", "reason": "e"}] * 1001}),
            "최상위에 모르는 칸": lambda b, r: r.update({"extra": 1}),
        }
        for name, change in rules.items():
            with self.subTest(rule=name):
                self.assertFalse(q._valid_state(mutate(change)))
        exact = copy.deepcopy(self.good_v2())
        exact["buckets"][key]["audit"]["ledger"] = [ledger_entry(number, NOW) for number in range(1, 201)]
        self.assertTrue(q._valid_state(exact))                                                                # 200건은 된다
        exact["buckets"][key]["audit"]["next_id"] = 10 ** 9
        self.assertTrue(q._valid_state(exact))

    def test_version_one_refuses_the_ledger_columns_the_old_program_never_wrote(self):
        key = "naver_apihub/-/id-abcd1234"
        with_audit = self.good_v2()
        with_audit["schema"] = 1
        self.assertFalse(q._valid_state(with_audit))
        only_successes = self.good_v2()
        only_successes["schema"] = 1
        del only_successes["buckets"][key]["audit"]
        self.assertFalse(q._valid_state(only_successes))                                                      # 창의 successes 만 남은 판 1
        plain = {"schema": 1, "buckets": {key: {"windows": {"day": {"label": "2026-11-02", "used": 1, "minutes": {}, "limit": 0, "limit_at": ""}}, "blocked_until": "", "block_kind": "", "backoff": 0}},
                 "failovers": []}
        self.assertTrue(q._valid_state(plain))
        plain["schema"] = 2                                                                                    # 판 2 에서도 장부 없는 묶음은 옛 모양 그대로다
        self.assertTrue(q._valid_state(plain))
        plain["buckets"][key]["windows"]["day"]["successes"] = 0
        self.assertFalse(q._valid_state(plain))

    def test_a_file_the_old_program_wrote_is_valid_stays_version_one_and_is_kept_by_a_ledger_call(self):
        self.image()
        image = cn.load(self.ctx).entries[0]
        legacy = {"windows": {"day": {"label": "2026-11-02", "used": 7, "minutes": {}, "limit": 0, "limit_at": ""}}, "blocked_until": "", "block_kind": "", "backoff": 0}
        old = {"schema": 1, "buckets": {q.bucket_key(image): {"windows": {"hour": {"label": "", "used": 0, "minutes": {"2026-11-02T01:30": 3}, "limit": 0, "limit_at": ""}}, "blocked_until": "",
                                                              "block_kind": "", "backoff": 0}, "naver_openapi/-/id-0a1b2c3d": legacy}, "failovers": []}
        self.write_state(old)
        before = self.path.read_bytes()
        view = self.guard.usage("image_provider")[0]
        self.assertEqual((view.rows[0].used, view.notice), (3, ""))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.path.with_name(self.path.name + ".bak").exists())
        self.assertIsInstance(self.guard.acquire("image_provider"), q.Lease)
        after = self.state()
        self.assertEqual(after["schema"], 1)
        self.assertEqual(after["buckets"]["naver_openapi/-/id-0a1b2c3d"], legacy)
        self.assertEqual(after["buckets"][q.bucket_key(image)]["windows"]["hour"]["minutes"]["2026-11-02T01:30"], 4)
        self.hub()
        self.guard.report(self.lease(), q.OK)
        grown = self.state()
        self.assertEqual(grown["schema"], 2)
        self.assertEqual(grown["buckets"]["naver_openapi/-/id-0a1b2c3d"], legacy)
        self.assertEqual(grown["buckets"][q.bucket_key(image)], after["buckets"][q.bucket_key(image)])
        self.assertIn("audit", grown["buckets"][q.bucket_key(self.entry)])
        self.assertFalse(self.path.with_name(self.path.name + ".bak").exists())
        self.assertEqual(self.guard.usage("image_provider")[0].notice, "")

    def test_a_file_without_any_ledger_bucket_is_written_as_version_one_again(self):
        self.image()
        self.assertIsInstance(self.guard.acquire("image_provider"), q.Lease)
        self.assertEqual(self.state()["schema"], 1)
        self.hub()
        self.lease()
        self.assertEqual(self.state()["schema"], 2)


if __name__ == "__main__":
    unittest.main()
