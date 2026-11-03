"""한도 안전장치(`service/quota.py`) 시험 — 시계·보관소·데이터 폴더는 모두 가짜(고정 시각)이고 네트워크·진짜 자격 증명 관리자는 쓰지 않는다.

지키는 것:
  1) 예산: 우선순위마다 남겨 둘 몫(일괄 30%·새 후보 20%·선택된 후보 10%·필수 호출 0%)의 경계 — 이미지 공급자 데모(시간당 50회)에서 일반 호출 45번·필수 호출 5번.
  2) 전환: 결과 10종 × 정책 × 항목 배치 전수 — 전환할 수 있는 것은 정확히 네 가지(429·기간 한도·일시 5xx·시간 초과)뿐이고 인증·잘못된 요청·정책 차단·콘텐츠 차단·그 밖의 오류는 어떤 정책에서도
     다른 항목을 시도하지 않는다. 한 요청에 같은 항목을 두 번 시도하지 않고(한 바퀴), 한도 오류 뒤에는 같은 묶음으로 넘어가지 않고, 성공 뒤 다음 요청은 첫 항목부터 시작한다.
  3) 쉬기: Retry-After 를 지키고(0 이어도 연타하지 않는다) 지수 백오프·상한·초기화 시각 경계, 머리글 보정, 창 경계, 깨진 상태 파일, 키가 없는 상태, 결정성, 동시에 부르는 두 흐름.
"""
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.service import quota as q  # noqa: E402

UTC = timezone.utc
NOW = ss.NOW                                                    # 2026-11-02 01:30:12 UTC = 한국 시각 10:30:12
KST_MIDNIGHT = datetime(2026, 11, 2, 15, 0, 0, tzinfo=UTC)      # 한국 시각 2026-11-03 00:00:00 — 다음 초기화


def naver_fields(number):
    return {"client_id": f"app{number:02d}" + "x" * 14, "client_secret": f"sec{number:02d}abcde"}


def image_fields(number):
    return {"access_key": f"key{number:02d}" + "Q" * 20}


class GuardCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.clock = ss.Clock()
        self.ctx = ss.make_ctx(tmp.name, clock=self.clock)
        self.guard = q.QuotaGuard(self.ctx, lock_wait=0)

    def naver(self, number, *, state="active", project=None, ack=True):
        return cn.add_entry(self.ctx, "naver_openapi", name=f"키{number}", fields=naver_fields(number), project=project or f"앱{number}", state=state, terms_ack=ack).entry

    def image(self, number, *, state="active", project=None, ack=True, provider=""):
        return cn.add_entry(self.ctx, "image_provider", name=f"이미지{number}", fields=image_fields(number), project=project or f"앱{number}", state=state, terms_ack=ack, provider=provider).entry

    def state(self):
        return json.loads(self.ctx.workspace.quota_path.read_text(encoding="utf-8"))

    def put_used(self, entry, used, *, window="day"):
        """그 항목의 한도 묶음에 이 창의 사용량을 직접 적어 둔다(수만 번 부르지 않으려고)."""
        path = self.ctx.workspace.quota_path
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema": 1, "buckets": {}, "failovers": []}
        bucket = state["buckets"].setdefault(q.bucket_key(entry), {"windows": {}, "blocked_until": "", "block_kind": "", "backoff": 0})
        held = {"label": "", "used": 0, "minutes": {}, "limit": 0, "limit_at": ""}
        if window == "day":
            held["label"], held["used"] = "2026-11-02", used
        else:
            held["minutes"] = {"2026-11-02T01:30": used}
        bucket["windows"][window] = held
        path.write_text(json.dumps(state), encoding="utf-8")

    def lease(self, purpose="naver_openapi", **kwargs):
        got = self.guard.acquire(purpose, **kwargs)
        self.assertIsInstance(got, q.Lease, got)
        return got

    def denied(self, purpose="naver_openapi", **kwargs):
        got = self.guard.acquire(purpose, **kwargs)
        self.assertIsInstance(got, q.Denied, got)
        return got


class BudgetTest(GuardCase):
    def test_the_demo_image_budget_allows_forty_five_ordinary_calls_and_keeps_five_for_required_ones(self):
        entry = self.image(1, ack=False)
        for priority, last_ok in ((q.BULK, 34), (q.NEW, 39), (q.SELECTED, 44), (q.CRITICAL, 49)):
            for used, expected in ((last_ok, True), (last_ok + 1, False)):
                with self.subTest(priority=priority, used=used):
                    self.put_used(entry, used, window="hour")
                    got = self.guard.acquire("image_provider", priority=priority)
                    self.assertEqual(isinstance(got, q.Lease), expected, (priority, used, got))
        self.put_used(entry, 50, window="hour")
        self.assertEqual(self.denied("image_provider", priority=q.CRITICAL).code, "exhausted")

    def test_ninety_percent_of_the_naver_budget_starts_saving_mode_for_ordinary_calls_only(self):
        entry = self.naver(1)
        for used, selected_ok in ((22498, True), (22499, True), (22500, False), (22501, False)):
            with self.subTest(used=used):
                self.put_used(entry, used)
                got = self.guard.acquire("naver_openapi", priority=q.SELECTED)
                self.assertEqual(isinstance(got, q.Lease), selected_ok, got)
        self.put_used(entry, 22500)
        self.assertIsInstance(self.guard.acquire("naver_openapi", priority=q.CRITICAL), q.Lease)
        self.put_used(entry, 25000)
        self.assertEqual(self.denied(priority=q.CRITICAL).code, "exhausted")
        self.put_used(entry, 24999)
        self.assertIsInstance(self.guard.acquire("naver_openapi", priority=q.CRITICAL), q.Lease)

    def test_several_calls_at_once_must_leave_the_reserve_as_well(self):
        entry = self.naver(1)
        self.put_used(entry, 22400)
        self.assertEqual(self.denied(priority=q.SELECTED, calls=101).code, "saving_mode")
        self.assertIsInstance(self.guard.acquire("naver_openapi", priority=q.SELECTED, calls=100), q.Lease)

    def test_the_reserve_rounds_up_when_the_limit_is_not_a_multiple_of_ten(self):
        """한도 55 에서 10% 는 5.5 — 올림해 6 을 남긴다(내림하면 5 만 남는다). 30% 는 16.5 → 17, 20% 는 11 그대로."""
        base = cn.PURPOSES["naver_openapi"]
        small = cn.Provider("", "네이버", cn.ROTATION_LIMITED, (("default", (cn.Window("day", "day", 55),)),), "default")
        registry = {**cn.PURPOSES, "naver_openapi": cn.Purpose(**{**base.__dict__, "providers": (small,)})}
        guard = q.QuotaGuard(self.ctx, registry=registry, lock_wait=0)
        entry = cn.add_entry(self.ctx, "naver_openapi", name="키", fields=naver_fields(1), project="앱", registry=registry).entry
        for used, priority, allowed in ((48, q.SELECTED, True), (49, q.SELECTED, False), (43, q.NEW, True), (44, q.NEW, False), (37, q.BULK, True), (38, q.BULK, False), (54, q.CRITICAL, True), (55, q.CRITICAL, False)):
            with self.subTest(used=used, priority=priority):
                self.put_used(entry, used)
                self.assertEqual(isinstance(guard.acquire("naver_openapi", priority=priority), q.Lease), allowed)

    def test_a_call_is_counted_before_it_is_made_so_two_flows_cannot_overspend(self):
        self.naver(1)
        self.lease(calls=3)
        self.lease()
        self.assertEqual(self.state()["buckets"][q.bucket_key(cn.load(self.ctx).entries[0])]["windows"]["day"]["used"], 4)

    def test_the_priority_floors_are_exactly_these(self):
        self.assertEqual(q.FLOOR_PERCENT, {"bulk_refresh": 30, "new_candidate": 20, "selected_candidate": 10, "critical": 0})
        self.assertEqual(q.PRIORITIES, ("bulk_refresh", "new_candidate", "selected_candidate", "critical"))

    def test_the_day_resets_at_korean_midnight_to_the_second(self):
        entry = self.naver(1)
        self.put_used(entry, 25000)
        self.assertEqual(self.denied().code, "exhausted")
        self.clock.now = KST_MIDNIGHT - timedelta(seconds=1)
        self.assertEqual(self.denied().code, "exhausted")
        self.clock.now = KST_MIDNIGHT
        self.assertIsInstance(self.guard.acquire("naver_openapi", priority=q.CRITICAL), q.Lease)

    def test_the_resume_time_of_an_exhausted_day_is_the_next_korean_midnight(self):
        entry = self.naver(1)
        self.put_used(entry, 25000)
        got = self.denied()
        self.assertEqual(got.retry_at, KST_MIDNIGHT)
        self.assertEqual(got.resume_text, "내일 00:00 이후 자동 재개")
        self.assertTrue(got.degraded)

    def test_a_sliding_window_forgets_a_minute_only_after_its_whole_window_has_passed(self):
        self.image(1, ack=False)
        self.lease("image_provider", priority=q.CRITICAL)                                      # 01:30:12 → 01:30 묶음
        for seconds, counted in ((60 * 60 + 47, True), (60 * 60 + 48, False)):                 # 02:30:59 까지는 센다, 02:31:00 부터는 안 센다
            self.clock.now = NOW + timedelta(seconds=seconds)
            view = self.guard.usage("image_provider")[0]
            with self.subTest(seconds=seconds):
                self.assertEqual(view.rows[0].used, 1 if counted else 0)

    def test_the_day_window_counts_per_korean_day_not_per_utc_day(self):
        entry = self.naver(1)
        self.lease()
        self.clock.now = datetime(2026, 11, 2, 14, 59, 59, tzinfo=UTC)                         # 한국 시각 같은 날 23:59:59
        self.assertEqual(self.guard.usage("naver_openapi")[0].rows[0].used, 1)
        self.clock.now = KST_MIDNIGHT
        self.assertEqual(self.guard.usage("naver_openapi")[0].rows[0].used, 0)
        self.assertEqual(entry.purpose, "naver_openapi")

    def test_a_cache_makes_the_denial_use_the_cache_instead_of_degrading(self):
        entry = self.naver(1)
        self.put_used(entry, 22500)
        plain, cached = self.denied(priority=q.NEW), self.denied(priority=q.NEW, cached=True)
        self.assertEqual((plain.degraded, plain.use_cache), (True, False))
        self.assertEqual((cached.degraded, cached.use_cache), (False, True))
        self.assertEqual(cached.code, "saving_mode")

    def test_bad_arguments_are_programming_errors(self):
        self.naver(1)
        for kwargs in ({"calls": 0}, {"calls": -1}, {"calls": True}, {"calls": 1001}, {"calls": 1.5}, {"priority": "urgent"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.guard.acquire("naver_openapi", **kwargs)
        with self.assertRaises(ValueError):
            self.guard.acquire("nowhere")
        with self.assertRaises(ValueError):
            self.guard.report(self.lease(), "exploded")


class ClassifyTest(unittest.TestCase):
    def test_http_statuses_map_to_exactly_the_documented_kinds(self):
        table = {429: q.RATE_LIMITED, 500: q.TRANSIENT, 502: q.TRANSIENT, 503: q.TRANSIENT, 504: q.TRANSIENT, 401: q.AUTH_FAILED, 403: q.AUTH_FAILED, 400: q.BAD_REQUEST, 422: q.BAD_REQUEST,
                 200: q.OK, 204: q.OK, 404: q.OTHER_ERROR, 501: q.OTHER_ERROR, 418: q.OTHER_ERROR}
        for status, kind in table.items():
            with self.subTest(status=status):
                self.assertEqual(q.classify_http(status), kind)

    def test_a_forbidden_with_no_requests_left_is_a_rate_limit_but_a_plain_forbidden_is_an_auth_failure(self):
        self.assertEqual(q.classify_http(403, {"X-Ratelimit-Remaining": "0"}), q.RATE_LIMITED)
        self.assertEqual(q.classify_http(403, {"x-ratelimit-remaining": 0}), q.RATE_LIMITED)
        self.assertEqual(q.classify_http(403, {"X-Ratelimit-Remaining": "12"}), q.AUTH_FAILED)
        self.assertEqual(q.classify_http(403, {"X-Ratelimit-Remaining": "abc"}), q.AUTH_FAILED)
        self.assertEqual(q.classify_http(403, None), q.AUTH_FAILED)
        self.assertEqual(q.classify_http(401, {"X-Ratelimit-Remaining": "0"}), q.AUTH_FAILED)

    def test_the_switchable_kinds_are_exactly_four_and_every_kind_has_a_plain_advice(self):
        self.assertEqual(q.SWITCH_KINDS, {"rate_limited", "quota_exhausted", "transient_error", "timeout"})
        self.assertEqual(set(q.OUTCOMES), {"ok"} | q.SWITCH_KINDS | {"auth_failed", "bad_request", "policy_blocked", "content_blocked", "other_error"})
        self.assertEqual(set(q.ADVICE_CODE), set(q.OUTCOMES) - {"ok"})
        self.assertEqual(q.LIMIT_KINDS, {"rate_limited", "quota_exhausted"})


class SwitchRulesTest(GuardCase):
    def arrange(self, layout):
        """layout: 'two' 서로 다른 앱 둘 · 'three' 셋 · 'same' 같은 앱 둘 · 'unsplash' 이미지 공급자 둘(서로 다른 앱)."""
        if layout == "two":
            return "naver_openapi", [self.naver(1), self.naver(2)]
        if layout == "three":
            return "naver_openapi", [self.naver(1), self.naver(2), self.naver(3)]
        if layout == "same":
            first = self.naver(1, project="같은 앱")
            second = cn.add_entry(self.ctx, "naver_openapi", name="키2", fields={"client_id": naver_fields(1)["client_id"], "client_secret": "other12345"}, project="같은 앱", terms_ack=True).entry
            return "naver_openapi", [first, second]
        return "image_provider", [self.image(1, ack=False), self.image(2)]

    def next_entry(self, purpose, request):
        got = self.guard.acquire(purpose, request=request)
        return got.entry_id if isinstance(got, q.Lease) else None

    def test_every_outcome_under_every_policy_and_layout(self):
        """결과 10종 × 정책 둘 × 배치 넷 — 전환은 (네 가지 결과 · failover · 전환이 허용되는 제공자 · 한도 오류면 다른 묶음) 일 때만."""
        for layout in ("two", "three", "same", "unsplash"):
            for policy in (cn.ON_FAILOVER, cn.ON_SAVE):
                for outcome in q.OUTCOMES:
                    with self.subTest(layout=layout, policy=policy, outcome=outcome):
                        self.setUp()
                        purpose, entries = self.arrange(layout)
                        cn.set_policy(self.ctx, purpose, on_limit=policy)
                        first = self.lease(purpose)
                        self.assertEqual(first.entry_id, entries[0].entry_id)
                        result = self.guard.report(first, outcome)
                        follow = self.next_entry(purpose, first.request) if result.action == q.ACT_NEXT else None
                        should_switch = (outcome in q.SWITCH_KINDS and policy == cn.ON_FAILOVER and layout in ("two", "three", "same")
                                         and not (outcome in q.LIMIT_KINDS and layout == "same"))
                        self.assertEqual(result.action == q.ACT_NEXT, should_switch, result)
                        if should_switch:
                            self.assertEqual(follow, entries[1].entry_id)
                        else:
                            self.assertIsNone(follow)
                            again = self.guard.acquire(purpose, request=first.request) if outcome != "ok" else None
                            if result.action != q.ACT_RETRY:
                                self.assertFalse(isinstance(again, q.Lease), (outcome, again))
                        self.assertEqual(first.request.closed, result.action in (q.ACT_DONE, q.ACT_STOP))

    def test_the_five_non_switch_outcomes_give_a_plain_action_and_never_a_retry(self):
        expected = {q.AUTH_FAILED: "키가 잘못됐거나 권한이 없습니다", q.BAD_REQUEST: "요청 내용이 올바르지 않습니다", q.POLICY_BLOCKED: "서비스 정책으로 차단됐습니다", q.CONTENT_BLOCKED: "서비스 정책으로 차단됐습니다"}
        for outcome, words in expected.items():
            with self.subTest(outcome=outcome):
                self.setUp()
                self.naver(1)
                self.naver(2)
                result = self.guard.report(self.lease(), outcome)
                self.assertEqual(result.action, q.ACT_STOP)
                self.assertIn(words, result.advice)
                self.assertEqual(result.wait_seconds, 0)

    def test_one_round_only_each_entry_at_most_once_per_request(self):
        entries = self.arrange("three")[1]
        request, seen = None, []
        for _ in range(6):
            got = self.guard.acquire("naver_openapi", request=request)
            if not isinstance(got, q.Lease):
                break
            seen.append(got.entry_id)
            request = got.request
            self.guard.report(got, q.TRANSIENT)
        self.assertEqual(seen[:3], [item.entry_id for item in entries])
        self.assertEqual(len(seen), len(set(seen)) + (1 if len(seen) > 3 else 0), seen)
        self.assertLessEqual(len(set(seen)), 3)
        self.assertEqual(self.denied(request=request).code in ("closed", "no_more_keys"), True)

    def test_the_first_entry_is_always_tried_first_after_a_success(self):
        purpose, entries = self.arrange("two")
        first = self.lease(purpose)
        self.assertEqual(self.guard.report(first, q.TRANSIENT).action, q.ACT_NEXT)
        second = self.guard.acquire(purpose, request=first.request)
        self.assertEqual(second.entry_id, entries[1].entry_id)
        self.assertTrue(second.switched)
        self.assertIn("다른 키로 바꿨습니다: '키1' → '키2' (이유: transient_error)", second.notice)
        self.assertEqual(self.guard.report(second, q.OK).action, q.ACT_DONE)
        self.assertEqual(self.lease(purpose).entry_id, entries[0].entry_id, "순환 상태를 저장하지 않는다 — 다음 일은 첫 항목부터")

    def test_a_limit_error_never_switches_to_the_same_bucket_but_a_transient_one_may(self):
        purpose, entries = self.arrange("same")
        first = self.lease(purpose)
        self.assertEqual(self.guard.report(first, q.RATE_LIMITED).action, q.ACT_STOP)
        self.assertEqual(self.denied(purpose).code, "blocked")
        self.setUp()
        purpose, entries = self.arrange("same")
        first = self.lease(purpose)
        self.assertEqual(self.guard.report(first, q.TIMEOUT).action, q.ACT_NEXT)
        self.assertEqual(self.guard.acquire(purpose, request=first.request).entry_id, entries[1].entry_id)

    def test_the_same_bucket_rule_holds_even_when_no_block_was_recorded(self):
        """막힘 기록이 없어도(요청 상태만으로) 한도 오류 뒤에는 같은 묶음의 항목으로 넘어가지 않고, 일시 오류 뒤에는 넘어간다 — 이중 방어."""
        purpose, entries = self.arrange("same")
        limited = q.Request(purpose, q.NEW, tried=[entries[0].entry_id], last_kind=q.RATE_LIMITED)
        self.assertNotIsInstance(self.guard.acquire(purpose, request=limited), q.Lease)
        transient = q.Request(purpose, q.NEW, tried=[entries[0].entry_id], last_kind=q.TIMEOUT)
        self.assertEqual(self.guard.acquire(purpose, request=transient).entry_id, entries[1].entry_id)

    def test_a_blocked_first_entry_is_skipped_at_the_start_of_the_next_request(self):
        purpose, entries = self.arrange("two")
        first = self.lease(purpose)
        self.guard.report(first, q.QUOTA_EXHAUSTED)
        got = self.lease(purpose)
        self.assertEqual((got.entry_id, got.switched), (entries[1].entry_id, True))
        self.assertIn("이유: blocked", got.notice)
        self.clock.now = KST_MIDNIGHT
        self.assertEqual(self.lease(purpose).entry_id, entries[0].entry_id, "초기화 시각이 지나면 첫 항목으로 돌아온다")

    def test_standby_entries_are_only_used_after_the_active_ones_and_never_start_a_request(self):
        first, spare = self.naver(1), self.naver(2, state="standby")
        got = self.lease()
        self.assertEqual(got.entry_id, first.entry_id)
        self.assertEqual(self.guard.report(got, q.RATE_LIMITED).action, q.ACT_NEXT)
        self.assertEqual(self.guard.acquire("naver_openapi", request=got.request).entry_id, spare.entry_id)

    def test_an_off_or_standby_only_purpose_has_no_key_and_that_is_not_an_error(self):
        self.naver(1, state="standby")
        got = self.denied()
        self.assertEqual((got.code, got.degraded), ("no_key", True))
        self.assertIn("키가 없어도 핵심 기능은 그대로", got.reason)

    def test_unsplash_never_switches_for_any_outcome_and_only_retries_a_transient_failure_once(self):
        _purpose, entries = self.arrange("unsplash")
        for outcome in (q.RATE_LIMITED, q.QUOTA_EXHAUSTED, q.AUTH_FAILED, q.BAD_REQUEST):
            with self.subTest(outcome=outcome):
                self.setUp()
                _purpose, entries = self.arrange("unsplash")
                got = self.lease("image_provider")
                self.assertEqual(self.guard.report(got, outcome).action, q.ACT_STOP)
                after = self.guard.acquire("image_provider")
                self.assertFalse(isinstance(after, q.Lease) and after.entry_id != entries[0].entry_id, after)
        for outcome in (q.TRANSIENT, q.TIMEOUT):
            with self.subTest(outcome=outcome):
                self.setUp()
                _purpose, entries = self.arrange("unsplash")
                first = self.lease("image_provider")
                one = self.guard.report(first, outcome)
                self.assertEqual((one.action, one.wait_seconds), (q.ACT_RETRY, 2))
                again = self.guard.acquire("image_provider", request=first.request)
                self.assertEqual((again.entry_id, again.switched), (entries[0].entry_id, False))
                two = self.guard.report(again, outcome)
                self.assertEqual(two.action, q.ACT_STOP)
                self.assertTrue(first.request.closed)

    def test_a_single_key_gets_one_short_retry_for_a_transient_failure_then_gives_up(self):
        self.naver(1)
        first = self.lease()
        self.assertEqual(self.guard.report(first, q.TRANSIENT).action, q.ACT_RETRY)
        second = self.guard.acquire("naver_openapi", request=first.request)
        self.assertEqual(second.entry_id, first.entry_id)
        self.assertEqual(self.guard.report(second, q.TIMEOUT).action, q.ACT_STOP)

    def test_nothing_ever_switches_into_a_provider_that_never_rotates(self):
        """다른 제공자가 한도에 걸려도 `rotation = never` 인 제공자(Unsplash)로는 넘어가지 않는다 — 운영자가 fallback 으로 켜 두었어도."""
        base = cn.PURPOSES["image_provider"]
        registry = {**cn.PURPOSES, "image_provider": cn.Purpose(**{**base.__dict__, "fallback_providers": ("unsplash",)})}
        guard = q.QuotaGuard(self.ctx, registry=registry, lock_wait=0)
        cn.add_entry(self.ctx, "image_provider", name="펙셀", fields=image_fields(1), provider="pexels", registry=registry)
        cn.add_entry(self.ctx, "image_provider", name="언스플래시", fields=image_fields(2), provider="unsplash", terms_ack=True, state="standby", registry=registry)
        first = guard.acquire("image_provider")
        self.assertEqual(first.provider, "pexels")
        for outcome in (q.RATE_LIMITED, q.QUOTA_EXHAUSTED):
            self.assertEqual(guard.report(first, outcome).action, q.ACT_STOP, outcome)
            self.setUp()
            guard = q.QuotaGuard(self.ctx, registry=registry, lock_wait=0)
            cn.add_entry(self.ctx, "image_provider", name="펙셀", fields=image_fields(1), provider="pexels", registry=registry)
            cn.add_entry(self.ctx, "image_provider", name="언스플래시", fields=image_fields(2), provider="unsplash", terms_ack=True, state="standby", registry=registry)
            first = guard.acquire("image_provider")

    def test_a_first_entry_with_a_rejected_key_stops_everything_and_never_falls_back_to_the_next_one(self):
        first, second = self.naver(1), self.naver(2)
        got = self.lease()
        result = self.guard.report(got, q.AUTH_FAILED)
        self.assertEqual(result.action, q.ACT_STOP)
        self.assertEqual(cn.load(self.ctx).of_purpose("naver_openapi")[0].check_result, cn.CHECK_AUTH)
        for _ in range(3):
            denied = self.denied()
            self.assertEqual(denied.code, "auth_failed")
            self.assertIn("키가 잘못됐거나 권한이 없습니다", denied.reason)
        self.assertEqual(self.guard.purpose_status("naver_openapi", keystore=self.ctx.keystore), cn.AUTH_ERROR)
        cn.set_state(self.ctx, first.entry_id[:8], cn.OFF)                                 # 사용자가 직접 끄면 그다음 항목이 첫 항목이 된다
        self.assertEqual(self.lease().entry_id, second.entry_id)

    def test_a_policy_of_saving_only_never_switches_and_failover_is_the_default(self):
        self.naver(1)
        self.naver(2)
        self.assertEqual(cn.load(self.ctx).policy("naver_openapi").on_limit, cn.ON_FAILOVER)
        cn.set_policy(self.ctx, "naver_openapi", on_limit=cn.ON_SAVE)
        got = self.lease()
        self.assertEqual(self.guard.report(got, q.RATE_LIMITED).action, q.ACT_STOP)
        self.assertEqual(self.denied().code, "blocked")

    def test_a_fallback_provider_is_only_used_when_the_registry_names_it(self):
        base = cn.PURPOSES["ai_assist"]
        for fallbacks in ((), ("other",)):
            with self.subTest(fallbacks=fallbacks):
                self.setUp()
                registry = {**cn.PURPOSES, "ai_assist": cn.Purpose(**{**base.__dict__, "providers": base.providers + (cn.Provider("other", "Other", cn.ROTATION_LIMITED, (("default", ()),), "default"),),
                                                                       "fallback_providers": fallbacks})}
                guard = q.QuotaGuard(self.ctx, registry=registry, lock_wait=0)
                cn.add_entry(self.ctx, "ai_assist", name="가", fields={"key": "k1" + "Z" * 20}, provider="gemini", registry=registry)
                cn.add_entry(self.ctx, "ai_assist", name="나", fields={"key": "k2" + "Z" * 20}, provider="other", terms_ack=True, state="standby", registry=registry)
                first = guard.acquire("ai_assist")
                result = guard.report(first, q.RATE_LIMITED)
                nxt = guard.acquire("ai_assist", request=first.request)
                if fallbacks:
                    self.assertEqual(result.action, q.ACT_NEXT)
                    self.assertEqual((type(nxt).__name__, nxt.provider), ("Lease", "other"))
                else:
                    self.assertEqual(result.action, q.ACT_STOP)
                    self.assertIsInstance(nxt, q.Denied)


    def fallback_registry(self, *fallbacks):
        base = cn.PURPOSES["image_provider"]
        return {**cn.PURPOSES, "image_provider": cn.Purpose(**{**base.__dict__, "fallback_providers": tuple(fallbacks)})}

    def test_a_new_request_never_starts_on_an_automatic_switch_free_provider_after_the_first_key_is_blocked(self):
        """새 일(시작)도 전환과 같은 규칙을 지킨다 — 첫 항목(Pexels)의 묶음이 쉬는 중이어도 자동 전환이 없는 제공자(Unsplash)의 키로는 시작하지 않는다(`fallback_providers` 를 켠 배치에서만 보인다)."""
        registry = self.fallback_registry("unsplash")
        guard = q.QuotaGuard(self.ctx, registry=registry, lock_wait=0)
        cn.add_entry(self.ctx, "image_provider", name="페", fields=image_fields(1), provider="pexels", project="앱1", registry=registry)
        cn.add_entry(self.ctx, "image_provider", name="언", fields=image_fields(2), provider="unsplash", project="앱2", state="standby", terms_ack=True, registry=registry)
        first = guard.acquire("image_provider")
        self.assertEqual((type(first).__name__, first.provider), ("Lease", "pexels"))
        guard.report(first, q.RATE_LIMITED)
        for _ in range(2):                                                       # 새 일을 몇 번 시작해도 같다
            started = guard.acquire("image_provider")
            self.assertIsInstance(started, q.Denied)
            self.assertEqual((started.code, started.degraded), ("blocked", True))
        self.assertEqual([item["to"] for item in self.state()["failovers"]], [])

    def test_a_new_request_may_start_on_the_next_limited_provider_when_the_registry_allows_it(self):
        """같은 배치에서 다음 제공자가 한도를 나누는 일반 제공자(Pixabay)이면 새 일이 그 키로 시작한다 — 위 시험이 '아무것도 못 쓰게 막는 것'이 아니라는 대조."""
        registry = self.fallback_registry("pixabay")
        guard = q.QuotaGuard(self.ctx, registry=registry, lock_wait=0)
        cn.add_entry(self.ctx, "image_provider", name="페", fields=image_fields(1), provider="pexels", project="앱1", registry=registry)
        cn.add_entry(self.ctx, "image_provider", name="픽", fields=image_fields(2), provider="pixabay", project="앱2", state="standby", terms_ack=True, registry=registry)
        first = guard.acquire("image_provider")
        guard.report(first, q.RATE_LIMITED)
        started = guard.acquire("image_provider")
        self.assertEqual((type(started).__name__, started.provider, started.switched), ("Lease", "pixabay", True))

    def test_a_new_request_does_not_start_on_the_same_limit_bucket_of_a_blocked_first_key(self):
        registry = self.fallback_registry()
        guard = q.QuotaGuard(self.ctx, registry=registry, lock_wait=0)
        cn.add_entry(self.ctx, "image_provider", name="페1", fields=image_fields(1), provider="pexels", project="같은 앱", registry=registry)
        cn.add_entry(self.ctx, "image_provider", name="페2", fields=image_fields(2), provider="pexels", project="같은 앱", state="standby", terms_ack=True, registry=registry)
        first = guard.acquire("image_provider")
        guard.report(first, q.RATE_LIMITED)
        started = guard.acquire("image_provider")
        self.assertEqual((type(started).__name__, started.code), ("Denied", "blocked"))


class BackoffTest(GuardCase):
    def test_retry_after_zero_still_waits_the_base_backoff_and_a_longer_one_is_kept(self):
        self.naver(1, ack=False)
        for asked, waited in ((0, 5), (None, 5), (3, 5), (5, 5), (6, 6), (100, 100), (100.5, 101), ("30", 30), ("0", 5)):
            with self.subTest(asked=asked):
                self.setUp()
                self.naver(1, ack=False)
                got = self.lease()
                result = self.guard.report(got, q.RATE_LIMITED, retry_after=asked)
                self.assertEqual(result.wait_seconds, waited)
                self.assertEqual(result.blocked_until, NOW + timedelta(seconds=waited))

    def test_the_block_lifts_at_the_exact_second_and_not_before(self):
        self.naver(1, ack=False)
        got = self.lease()
        self.guard.report(got, q.RATE_LIMITED, retry_after=100)
        self.clock.now = NOW + timedelta(seconds=99)
        self.assertEqual(self.denied().code, "blocked")
        self.clock.now = NOW + timedelta(seconds=100)
        self.assertIsInstance(self.guard.acquire("naver_openapi"), q.Lease)

    def test_a_huge_retry_after_is_capped_at_forty_eight_hours(self):
        self.naver(1, ack=False)
        for asked in (10 ** 12, 10 ** 30, float("inf"), 48 * 3600 + 1):
            with self.subTest(asked=asked):
                self.setUp()
                self.naver(1, ack=False)
                result = self.guard.report(self.lease(), q.RATE_LIMITED, retry_after=asked)
                self.assertEqual(result.wait_seconds, 48 * 3600)

    def test_consecutive_limit_errors_back_off_exponentially_up_to_an_hour_and_success_resets_it(self):
        self.naver(1, ack=False)
        waits = []
        for _ in range(12):
            self.clock.now += timedelta(hours=60)                                         # 막힘이 풀린 뒤 다시(하루 사용량이 쌓이지 않게 며칠씩 건너뛴다)
            waits.append(self.guard.report(self.lease(priority=q.CRITICAL), q.RATE_LIMITED).wait_seconds)
        self.assertEqual(waits, [5, 10, 20, 40, 80, 160, 320, 640, 1280, 2560, 3600, 3600])
        self.clock.now += timedelta(hours=60)
        self.guard.report(self.lease(priority=q.CRITICAL), q.OK)
        self.clock.now += timedelta(hours=1)
        self.assertEqual(self.guard.report(self.lease(priority=q.CRITICAL), q.RATE_LIMITED).wait_seconds, 5)

    def test_the_retry_after_header_is_used_when_no_number_is_given(self):
        self.naver(1, ack=False)
        result = self.guard.report(self.lease(), q.RATE_LIMITED, headers={"Retry-After": "90"})
        self.assertEqual(result.wait_seconds, 90)

    def test_quota_exhausted_blocks_until_the_given_reset_or_the_next_korean_midnight(self):
        cases = ((NOW + timedelta(hours=3), NOW + timedelta(hours=3)), (None, KST_MIDNIGHT), (NOW - timedelta(minutes=1), KST_MIDNIGHT), (NOW, KST_MIDNIGHT), (NOW + timedelta(days=9), KST_MIDNIGHT),
                 (datetime(2026, 11, 2, 5, 0, 0), KST_MIDNIGHT), ("tomorrow", KST_MIDNIGHT))
        for reset, until in cases:
            with self.subTest(reset=reset):
                self.setUp()
                self.naver(1, ack=False)
                got = self.lease()
                self.assertEqual(self.guard.report(got, q.QUOTA_EXHAUSTED, reset_at=reset).blocked_until, until)
                self.assertEqual(self.denied().retry_at, until)

    def test_an_exhausted_report_makes_the_usage_show_the_limit_reached_and_the_resume_time(self):
        self.naver(1, ack=False)
        self.guard.report(self.lease(), q.QUOTA_EXHAUSTED)
        view = self.guard.usage("naver_openapi")[0]
        self.assertEqual((view.rows[0].used, view.rows[0].limit, view.blocked, view.resume_text), (25000, 25000, True, "내일 00:00 이후 자동 재개"))
        self.assertEqual(self.guard.purpose_status("naver_openapi", keystore=self.ctx.keystore), cn.RATE_LIMITED)


CAP = 48 * 3600
# (Retry-After 글, 쉬어야 할 초) — 시각은 NOW = 2026-11-02(월요일) 01:30:12 UTC 이고 달 이름은 영어 약어뿐이다.
READABLE_NUMBERS = (("90", 90), (" 90 ", 90), ("\t90\t", 90), ("00090", 90), ("0", 0), ("0.0", 0), ("100.0", 100), ("100.5", 101), ("89.01", 90), ("0.5", 1), ("1.5", 2),
                    ("172799", 172799), ("172800", CAP), ("172800.5", CAP), ("172799.5", CAP), ("172801", CAP), ("9999999999", CAP), ("99999999999999999999", CAP),
                    ("0" * 64, 0), ("0" * 60 + "123", 123), ("0" * 54 + "9999999999", CAP), ("0" * 50 + "999999999", CAP))
UNREADABLE_TEXTS = ("", " ", "\n", "-5", "-0", "-0.5", "+30", "inf", "nan", "Infinity", "NaN", "1e3", "1E3", "30s", "30 s", "1,5", "1.5.2", ".5", "5.", "1_000", "0x10", "０", "１２０", "٣٠", "30\n", "\n30",
                    "3 0", "abc", "9" * 65, "9" * 500000, "Mon, 02 Nov 2026 01:31:52 GMT" + "x" * 40)
HTTP_DATES = (("Mon, 02 Nov 2026 01:31:52 GMT", 100), ("Mon, 02 Nov 2026 01:30:13 GMT", 1), ("Mon, 02 Nov 2026 01:30:12 GMT", 0), ("Mon, 02 Nov 2026 01:30:11 GMT", 0), ("Sun, 06 Nov 1994 08:49:37 GMT", 0),
              ("Wed, 04 Nov 2026 01:30:11 GMT", CAP - 1), ("Wed, 04 Nov 2026 01:30:12 GMT", CAP), ("Wed, 04 Nov 2026 01:30:13 GMT", CAP), ("Fri, 31 Dec 9999 23:59:59 GMT", CAP), ("Tue, 29 Feb 2028 01:31:52 GMT", CAP),
              ("Fri, 02 Nov 2026 01:31:52 GMT", 100), ("Monday, 02-Nov-26 01:31:52 GMT", 100), ("Sunday, 06-Nov-94 08:49:37 GMT", 0), ("Sunday, 06-Nov-76 08:49:37 GMT", CAP), ("Sunday, 06-Nov-77 08:49:37 GMT", 0),
              ("Mon Nov  2 01:31:52 2026", 100), ("Mon Nov 02 01:31:52 2026", 100), (" Mon, 02 Nov 2026 01:31:52 GMT\t", 100))
BAD_DATES = ("Mon, 31 Feb 2026 01:31:52 GMT", "Mon, 29 Feb 2027 01:31:52 GMT", "Mon, 00 Nov 2026 01:31:52 GMT", "Mon, 02 Nov 2026 24:00:00 GMT", "Mon, 02 Nov 2026 01:60:00 GMT", "Mon, 02 Nov 2026 01:31:60 GMT",
             "Mon, 02 Nov 2026 01:31:52 PST", "Mon, 02 Nov 2026 01:31:52 UTC", "Mon, 02 Nov 2026 01:31:52 +0000", "Mon, 02 Nov 2026 01:31:52", "02 Nov 2026 01:31:52 GMT", "Mon, 2 Nov 2026 01:31:52 GMT",
             "Mon, 02 nov 2026 01:31:52 GMT", "Mon, 02 11월 2026 01:31:52 GMT", "Mon, 02 Nov 26 01:31:52 GMT", "Monday, 02-Nov-2026 01:31:52 GMT", "Mon,  02 Nov 2026 01:31:52 GMT", "Mon Nov 2 01:31:52 2026",
             "Mon Nov  2 01:31:52 26", "Monday 02 Nov 2026 01:31:52 GMT", "2026-11-02T01:31:52Z", "Mon, 02 Nov 2026 01:31:52 GMT 1")


class RetryAfterFormatTest(GuardCase):
    """`Retry-After` 를 읽는 모든 꼴 — 정수 초·소수 초·HTTP-date 세 꼴을 읽고, 읽을 수 없으면 0 이 아니라 1분 이상 쉰다."""

    def test_whole_and_decimal_seconds_are_read_and_rounded_up_and_a_huge_number_is_capped(self):
        for text, seconds in READABLE_NUMBERS:
            with self.subTest(text=text[:70]):
                self.assertEqual(q.retry_after_seconds(text, NOW), seconds)

    def test_every_form_that_cannot_be_read_rests_a_full_minute_not_zero(self):
        self.assertEqual(q.RETRY_UNREADABLE_SECONDS, 60)
        for text in UNREADABLE_TEXTS:
            with self.subTest(text=text[:70]):
                self.assertEqual(q.retry_after_seconds(text, NOW), 60)

    def test_the_three_http_date_forms_are_read_as_the_distance_from_now_and_a_past_date_means_zero(self):
        for text, seconds in HTTP_DATES:
            with self.subTest(text=text):
                self.assertEqual(q.retry_after_seconds(text, NOW), seconds)

    def test_dates_that_are_not_real_or_not_in_gmt_are_unreadable_and_never_guessed(self):
        for text in BAD_DATES:
            with self.subTest(text=text):
                self.assertEqual(q.retry_after_seconds(text, NOW), 60)
                self.assertIsNone(q.parse_http_date(text, NOW))

    def test_the_two_digit_year_of_the_old_date_form_follows_the_fifty_year_rule(self):
        self.assertEqual(q.parse_http_date("Sunday, 06-Nov-76 08:49:37 GMT", NOW), datetime(2076, 11, 6, 8, 49, 37, tzinfo=UTC))
        self.assertEqual(q.parse_http_date("Sunday, 06-Nov-77 08:49:37 GMT", NOW), datetime(1977, 11, 6, 8, 49, 37, tzinfo=UTC))
        self.assertEqual(q.parse_http_date("Sunday, 06-Nov-26 08:49:37 GMT", NOW), datetime(2026, 11, 6, 8, 49, 37, tzinfo=UTC))
        self.assertEqual(q.parse_http_date("Sunday, 06-Nov-00 08:49:37 GMT", NOW), datetime(2000, 11, 6, 8, 49, 37, tzinfo=UTC))
        later = datetime(2025, 1, 1, tzinfo=UTC)                                         # 시계가 2025년이면 같은 '76' 은 51년 앞이라 1976 이 되고 '75' 는 딱 50년 앞이라 2075 다
        self.assertEqual(q.parse_http_date("Sunday, 06-Nov-76 08:49:37 GMT", later).year, 1976)
        self.assertEqual(q.parse_http_date("Sunday, 06-Nov-75 08:49:37 GMT", later).year, 2075)

    def test_the_date_is_read_in_any_timezone_of_the_clock_and_without_the_locale(self):
        seoul = datetime(2026, 11, 2, 10, 30, 12, tzinfo=timezone(timedelta(hours=9)))     # 같은 순간의 한국 시각
        self.assertEqual(q.retry_after_seconds("Mon, 02 Nov 2026 01:31:52 GMT", seoul), 100)
        self.assertEqual(q.retry_after_seconds("Mon, 02 Nov 2026 01:31:52 GMT", NOW.astimezone(timezone(timedelta(hours=-8)))), 100)

    def test_a_clock_with_fractions_of_a_second_rounds_the_distance_to_a_date_up_and_never_down(self):
        date = "Mon, 02 Nov 2026 01:31:52 GMT"                                           # NOW(01:30:12) 로부터 정확히 100초 뒤
        for micro, seconds in ((0, 100), (1, 100), (500000, 100), (999999, 100), (1000000 - 1, 100)):
            with self.subTest(micro=micro):
                self.assertEqual(q.retry_after_seconds(date, NOW.replace(microsecond=micro)), seconds)
        later = NOW + timedelta(seconds=99, microseconds=500000)                              # 날짜까지 0.5초 남음 → 1초
        self.assertEqual(q.retry_after_seconds(date, later), 1)
        self.assertEqual(q.retry_after_seconds(date, NOW + timedelta(seconds=100)), 0)
        self.assertEqual(q.retry_after_seconds(date, NOW + timedelta(seconds=100, microseconds=1)), 0, "이미 지난 날짜는 0")

    def test_values_that_are_not_text_or_numbers_are_unreadable_and_a_missing_one_is_zero(self):
        self.assertEqual(q.retry_after_seconds(None, NOW), 0)
        for value, seconds in ((0, 0), (0.0, 0), (100, 100), (100.5, 101), (100.0, 100), (CAP, CAP), (CAP - 1, CAP - 1), (CAP + 1, CAP), (10 ** 30, CAP), (float("inf"), CAP), (0.1, 1)):
            with self.subTest(value=value):
                self.assertEqual(q.retry_after_seconds(value, NOW), seconds)
        for value in (-1, -0.5, -4, float("-inf"), float("nan"), True, False, b"30", bytearray(b"30"), [30], (30,), {"s": 30}, object()):
            with self.subTest(value=type(value).__name__ + repr(value)[:10]):
                self.assertEqual(q.retry_after_seconds(value, NOW), 60)

    def test_a_very_long_text_is_refused_in_a_blink(self):
        import time
        started = time.monotonic()
        for text in ("9" * 300000, "1" * 299999 + ".5", "Mon, " * 60000, chr(0x3000) * 300000 + "5"):
            self.assertEqual(q.retry_after_seconds(text, NOW), 60)
        self.assertLess(time.monotonic() - started, 5.0)

    def test_the_report_waits_for_a_decimal_a_date_or_an_unreadable_value_and_the_block_lifts_exactly_then(self):
        for headers, waited in (({"Retry-After": "100.5"}, 101), ({"retry-after": "Mon, 02 Nov 2026 01:31:52 GMT"}, 100), ({"RETRY-AFTER": "Mon Nov  2 01:31:52 2026"}, 100),
                                ({"Retry-After": "soon"}, 60), ({"Retry-After": "-3"}, 60), ({"Retry-After": "nan"}, 60), ({"Retry-After": ""}, 60), ({"Retry-After": "Sun, 06 Nov 1994 08:49:37 GMT"}, 5),
                                ({"Retry-After": "0"}, 5), ({"Retry-After": None}, 5), ({}, 5), (None, 5)):
            with self.subTest(headers=headers):
                self.setUp()
                self.naver(1, ack=False)
                result = self.guard.report(self.lease(), q.RATE_LIMITED, headers=headers)
                self.assertEqual(result.wait_seconds, waited)
                self.assertEqual(result.blocked_until, NOW + timedelta(seconds=waited))
                self.clock.now = NOW + timedelta(seconds=waited - 1)
                self.assertEqual(self.denied().code, "blocked")
                self.clock.now = NOW + timedelta(seconds=waited)
                self.assertIsInstance(self.guard.acquire("naver_openapi"), q.Lease)

    def test_the_number_given_to_report_wins_over_the_header_and_a_text_is_read_like_a_header(self):
        self.naver(1, ack=False)
        result = self.guard.report(self.lease(), q.RATE_LIMITED, retry_after=40, headers={"Retry-After": "900"})
        self.assertEqual(result.wait_seconds, 40)
        self.setUp()
        self.naver(1, ack=False)
        self.assertEqual(self.guard.report(self.lease(), q.RATE_LIMITED, retry_after="Mon, 02 Nov 2026 01:31:52 GMT", headers={"Retry-After": "900"}).wait_seconds, 100)
        self.setUp()
        self.naver(1, ack=False)
        self.assertEqual(self.guard.report(self.lease(), q.RATE_LIMITED, retry_after="nonsense", headers={"Retry-After": "900"}).wait_seconds, 60)

    def test_an_unreadable_value_never_shortens_the_exponential_backoff_that_follows(self):
        self.naver(1, ack=False)
        waits = []
        for _ in range(8):
            self.clock.now += timedelta(hours=60)
            waits.append(self.guard.report(self.lease(priority=q.CRITICAL), q.RATE_LIMITED, headers={"Retry-After": "later"}).wait_seconds)
        self.assertEqual(waits, [60, 60, 60, 60, 80, 160, 320, 640])


class HeaderSyncTest(GuardCase):
    def test_the_response_headers_override_the_local_count_and_the_limit(self):
        self.image(1, ack=False)
        got = self.lease("image_provider")
        self.guard.report(got, q.OK, headers={"x-RATELIMIT-remaining": "12", "X-Ratelimit-Limit": "50"})
        self.assertEqual(self.guard.usage("image_provider")[0].rows[0].used, 38)
        again = self.lease("image_provider", priority=q.CRITICAL)
        self.guard.report(again, q.OK, headers={"X-Ratelimit-Remaining": "999", "X-Ratelimit-Limit": "1000"})
        row = self.guard.usage("image_provider")[0].rows[0]
        self.assertEqual((row.used, row.limit), (1, 1000))
        self.clock.now = NOW + timedelta(hours=23)
        self.assertEqual(self.guard.usage("image_provider")[0].rows[0].limit, 1000)
        self.clock.now = NOW + timedelta(hours=25)
        self.assertEqual(self.guard.usage("image_provider")[0].rows[0].limit, 50, "머리글로 안 한도는 24시간 뒤에는 정해 둔 값으로 돌아간다")

    def test_untrustworthy_headers_are_ignored(self):
        self.image(1, ack=False)
        bad = ({"X-Ratelimit-Remaining": "60", "X-Ratelimit-Limit": "50"}, {"X-Ratelimit-Remaining": "-1", "X-Ratelimit-Limit": "50"}, {"X-Ratelimit-Remaining": "x", "X-Ratelimit-Limit": "50"},
               {"X-Ratelimit-Remaining": True, "X-Ratelimit-Limit": "50"}, {"X-Ratelimit-Remaining": "5", "X-Ratelimit-Limit": "0"}, {"X-Ratelimit-Remaining": "5"}, {"X-Ratelimit-Limit": "50"},
               {"X-Ratelimit-Remaining": "5", "X-Ratelimit-Limit": "99999999999"}, "not a mapping", None, [])
        for headers in bad:
            with self.subTest(headers=headers):
                self.setUp()
                self.image(1, ack=False)
                self.guard.report(self.lease("image_provider"), q.OK, headers=headers)
                row = self.guard.usage("image_provider")[0].rows[0]
                self.assertEqual((row.used, row.limit), (1, 50))

    def test_a_window_without_header_sync_ignores_the_headers(self):
        self.naver(1, ack=False)
        self.guard.report(self.lease(), q.OK, headers={"X-Ratelimit-Remaining": "1", "X-Ratelimit-Limit": "50"})
        self.assertEqual(self.guard.usage("naver_openapi")[0].rows[0].limit, 25000)

    def test_the_production_tier_changes_the_hourly_limit(self):
        self.image(1, ack=False)
        cn.set_policy(self.ctx, "image_provider", tier="production")
        self.assertEqual(self.guard.usage("image_provider")[0].rows[0].limit, 1000)
        cn.set_policy(self.ctx, "image_provider", tier="demo")
        self.assertEqual(self.guard.usage("image_provider")[0].rows[0].limit, 50)


class StateFileTest(GuardCase):
    def test_a_damaged_state_file_assumes_half_of_the_day_was_used_and_keeps_the_bad_copy(self):
        self.naver(1, ack=False)
        path = self.ctx.workspace.quota_path
        path.parent.mkdir(parents=True, exist_ok=True)
        for broken in ("{not json", "[]", json.dumps({"schema": 2, "buckets": {}, "failovers": []}), json.dumps({"schema": 1, "buckets": {"a": {}}, "failovers": []}), "\u0000" * 10):
            with self.subTest(broken=broken[:12]):
                path.write_text(broken, encoding="utf-8")
                view = self.guard.usage("naver_openapi")[0]
                self.assertEqual(view.rows[0].used, 12500)
                self.assertIn("오늘 한도의 절반을 이미 쓴 것으로 가정했습니다", view.notice)
                self.assertEqual(path.read_text(encoding="utf-8"), broken, "읽기만 하는 usage 는 깨진 파일을 건드리지 않는다")
                self.lease()
                self.assertTrue(path.with_name(path.name + ".bak").exists())
                self.assertEqual(path.with_name(path.name + ".bak").read_text(encoding="utf-8"), broken)
                self.assertEqual(self.state()["buckets"][q.bucket_key(cn.load(self.ctx).entries[0])]["windows"]["day"]["used"], 12501)
                path.with_name(path.name + ".bak").unlink()

    def test_unknown_keys_and_bad_numbers_in_the_state_file_are_refused_as_damage(self):
        self.naver(1, ack=False)
        bucket = q.bucket_key(cn.load(self.ctx).entries[0])
        good = {"windows": {}, "blocked_until": "", "block_kind": "", "backoff": 0}
        window = {"label": "", "used": 0, "minutes": {}, "limit": 0, "limit_at": ""}
        cases = [{"schema": 1, "buckets": {}, "failovers": [], "extra": 1}, {"schema": True, "buckets": {}, "failovers": []}, {"schema": 1, "buckets": {bucket: {**good, "extra": 1}}, "failovers": []},
                 {"schema": 1, "buckets": {bucket: {**good, "blocked_until": "soon"}}, "failovers": []}, {"schema": 1, "buckets": {bucket: {**good, "block_kind": "weird"}}, "failovers": []},
                 {"schema": 1, "buckets": {bucket: {**good, "backoff": -1}}, "failovers": []}, {"schema": 1, "buckets": {bucket: {**good, "windows": {"day": {**window, "used": -1}}}}, "failovers": []},
                 {"schema": 1, "buckets": {bucket: {**good, "windows": {"day": {**window, "minutes": {"bad": 1}}}}}, "failovers": []}, {"schema": 1, "buckets": {}, "failovers": [{"at": "x"}]},
                 {"schema": 1, "buckets": {bucket: {**good, "windows": {"day": {**window, "used": 10 ** 10}}}}, "failovers": []}]
        for case in cases:
            with self.subTest(case=str(case)[:60]):
                self.ctx.workspace.quota_path.write_text(json.dumps(case), encoding="utf-8")
                self.assertIn("가정했습니다", self.guard.usage("naver_openapi")[0].notice)

    def test_reading_the_usage_creates_nothing(self):
        self.naver(1, ack=False)
        before = ss.tree_snapshot(self.ctx.workspace.root)
        self.guard.usage()
        self.guard.purpose_status("naver_openapi")
        self.assertEqual(ss.tree_snapshot(self.ctx.workspace.root), before)
        self.assertFalse(self.ctx.workspace.quota_path.exists())

    def test_the_same_calls_leave_byte_identical_state_files(self):
        outputs = []
        for _ in range(2):
            self.setUp()
            self.naver(1, ack=False)
            first = self.lease(priority=q.SELECTED, calls=2)
            self.guard.report(first, q.RATE_LIMITED, retry_after=40, headers={"X-Ratelimit-Remaining": "4", "X-Ratelimit-Limit": "9"})
            self.clock.advance(seconds=41)
            self.guard.report(self.lease(), q.OK)
            outputs.append(self.ctx.workspace.quota_path.read_text(encoding="utf-8"))
        self.assertEqual(outputs[0], outputs[1])

    def test_the_failover_log_keeps_the_last_thirty_switches_without_any_key_text(self):
        self.naver(1)
        self.naver(2)
        for _ in range(35):
            self.clock.now = KST_MIDNIGHT + timedelta(days=_ + 1)
            first = self.lease()
            self.guard.report(first, q.TRANSIENT)
            second = self.guard.acquire("naver_openapi", request=first.request)
            self.guard.report(second, q.OK)
        log = self.state()["failovers"]
        self.assertEqual(len(log), 30)
        self.assertEqual(sorted(log[0]), ["at", "from", "purpose", "reason", "to"])
        self.assertEqual((log[0]["from"], log[0]["to"], log[0]["reason"]), ("키1", "키2", "transient_error"))
        text = json.dumps(self.state(), ensure_ascii=False)
        for value in list(naver_fields(1).values()) + list(naver_fields(2).values()):
            self.assertNotIn(value, text)


class AvailabilityTest(GuardCase):
    def test_no_key_at_all_is_a_plain_degraded_answer_for_every_purpose_and_the_reads_all_work(self):
        for purpose in cn.PURPOSES:
            if not cn.PURPOSES[purpose].takes_keys:
                continue
            with self.subTest(purpose=purpose):
                got = self.guard.acquire(purpose)
                self.assertEqual((type(got).__name__, got.code, got.degraded), ("Denied", "no_key", True))
        views = self.guard.usage()
        self.assertEqual(len(views), 5)
        for view in views:
            self.assertEqual((view.entries, view.rows, view.blocked, view.saving_mode), (0, (), False, False))
            self.assertEqual(self.guard.purpose_status(view.purpose), cn.NOT_CONNECTED)

    def test_a_lock_held_by_another_flow_denies_instead_of_spending_blindly(self):
        self.naver(1, ack=False)
        with cn.locked(self.ctx, "quota-state"):
            got = self.denied()
        self.assertEqual((got.code, got.degraded), ("busy", True))
        self.assertIsInstance(self.guard.acquire("naver_openapi"), q.Lease)

    def test_a_state_file_that_cannot_be_written_denies_the_call_with_the_reason_and_counts_nothing(self):
        from unittest import mock

        from chanceblog_desktop.errors import AppError
        entry = self.naver(1, ack=False)
        with mock.patch.object(q, "write_json", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "x"})):
            got = self.denied()
        self.assertEqual((got.code, got.degraded), ("unavailable", True))
        self.assertIn("FILE_WRITE_FAILED", got.reason)
        self.assertFalse(self.ctx.workspace.quota_path.exists())
        self.assertIsInstance(self.guard.acquire_entry(entry), q.Lease)
        with mock.patch.object(q, "write_json", side_effect=AppError("DISK_FULL", {"경로": "x"})):
            self.assertEqual(self.guard.acquire_entry(entry).code, "unavailable")

    def test_the_usage_lists_the_last_three_switches_with_names_and_reasons_only(self):
        self.naver(1)
        self.naver(2)
        for number in range(4):
            self.clock.now = KST_MIDNIGHT + timedelta(days=number + 1)
            first = self.lease()
            self.guard.report(first, q.TIMEOUT)
            self.guard.report(self.guard.acquire("naver_openapi", request=first.request), q.OK)
        view = self.guard.usage("naver_openapi")[0]
        self.assertEqual(len(view.switches), 3)
        self.assertTrue(all("'키1' → '키2' (이유: timeout)" in item for item in view.switches), view.switches)

    def test_a_closed_request_cannot_be_reused(self):
        self.naver(1, ack=False)
        first = self.lease()
        self.guard.report(first, q.OK)
        self.assertEqual(self.denied(request=first.request).code, "closed")
        self.assertEqual(self.denied("image_provider", request=first.request).code, "closed")

    def test_acquire_entry_never_borrows_another_entry(self):
        first, second = self.naver(1), self.naver(2)
        self.put_used(first, 25000)
        got = self.guard.acquire_entry(first)
        self.assertIsInstance(got, q.Denied)
        self.assertIsInstance(self.guard.acquire_entry(second), q.Lease)

    def test_the_usage_marks_saving_mode_at_ninety_percent_and_lists_every_entry_bucket_once(self):
        first = self.naver(1)
        self.naver(2)
        self.put_used(first, 22500)
        view = self.guard.usage("naver_openapi")[0]
        self.assertTrue(view.saving_mode)
        self.assertEqual([(row.entry, row.used) for row in view.rows], [("키1", 22500), ("키2", 0)])
        self.put_used(first, 22499)
        self.assertFalse(self.guard.usage("naver_openapi")[0].saving_mode)

    def test_two_flows_calling_at_the_same_time_lose_no_count(self):
        entry = self.naver(1, ack=False)
        guard = q.QuotaGuard(self.ctx, lock_wait=30)
        failures, leases = [], []

        def work():
            try:
                for _ in range(8):
                    got = guard.acquire("naver_openapi")
                    leases.append(got)
            except Exception as problem:                                                 # 시험 스레드의 어떤 실패도 모아서 아래에서 보인다
                failures.append(repr(problem))

        threads = [threading.Thread(target=work) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        self.assertEqual(failures, [])
        granted = [item for item in leases if isinstance(item, q.Lease)]
        self.assertEqual(len(granted), 16)
        self.assertEqual(self.state()["buckets"][q.bucket_key(entry)]["windows"]["day"]["used"], 16)


class ProcessRaceTest(GuardCase):
    def test_two_real_processes_calling_at_the_same_time_lose_no_count(self):
        """진짜 프로세스 둘이 같은 데이터 폴더의 사용량 기록을 동시에 갱신해도 센 수가 어긋나지 않는다(잠금 파일 + 원자적 쓰기)."""
        import os
        import subprocess
        entry = self.naver(1, ack=False)
        env = {**ss.env_without_repo(), "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        flags = {"creationflags": 0x08000000} if os.name == "nt" else {}                       # 콘솔 창을 띄우지 않는다(Windows 에서만 뜻이 있다)
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve().parent / "quota_race_child.py"), str(ss.ROOT / "src"), str(self.ctx.workspace.root), "12"]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, **flags) for _ in range(2)]
        results = [child.communicate(timeout=240) for child in children]
        self.assertEqual([child.returncode for child in children], [0, 0], results)
        counts = [tuple(int(part) for part in out.decode().split()) for out, _err in results]
        self.assertEqual(sum(granted for granted, _denied in counts), 24, counts)
        self.assertEqual(self.state()["buckets"][q.bucket_key(entry)]["windows"]["day"]["used"], 24)


class SecretTest(GuardCase):
    def test_nothing_the_guard_writes_or_says_contains_a_key_value(self):
        entries = [self.naver(1), self.naver(2)]
        values = [value for number in (1, 2) for value in naver_fields(number).values()]
        spoken = []
        first = self.lease()
        for outcome in q.OUTCOMES:
            self.setUp()
            entries = [self.naver(1), self.naver(2)]
            lease = self.lease()
            result = self.guard.report(lease, outcome, retry_after=7, headers={"X-Ratelimit-Remaining": "3", "X-Ratelimit-Limit": "9"})
            spoken += [result.advice, result.notice, repr(result), repr(lease), self.ctx.workspace.quota_path.read_text(encoding="utf-8")]
            follow = self.guard.acquire("naver_openapi", request=lease.request)
            spoken += [repr(follow), getattr(follow, "reason", ""), getattr(follow, "notice", "")]
            spoken += [json.dumps(view.to_dict(), ensure_ascii=False) for view in self.guard.usage()]
        for text in spoken:
            for value in values:
                self.assertNotIn(value, text)
        self.assertEqual(first.purpose, "naver_openapi")
        self.assertEqual(len(entries), 2)


if __name__ == "__main__":
    unittest.main()
