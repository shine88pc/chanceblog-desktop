"""NAVER API HUB 검색어 트렌드 '안전 틀'(결정 D-35)의 레지스트리·연결 설정·옛 항목 처리·모양 검사·명령줄·표시 시험 — 한도 안전장치 쪽(월 창·장부·Fail-Closed·단계 판정)은 `test_service_naver_hub_quota.py` 가 본다.
네트워크·진짜 키·진짜 보관소 없이 돈다(가짜 시계·가짜 보관소·임시 폴더).

지키는 것:
  1) 레지스트리의 `naver_apihub` 값(칸·한도 창·콘솔 한도·단계표·고정 문구·키 1개)과 다른 용도·제공자의 값이 그대로다 — 숫자 하나·표시 하나가 바뀌어도 깨진다.
  2) 키는 하나뿐이다: 둘째 항목은 약관 확인이 있어도 거절하고(명령줄은 키를 묻기 전에), 다른 용도의 검사 순서와 문구는 그대로다. 파일의 항목 수 검사도 용도마다 상한을 쓴다.
  3) 옛 `naver_openapi` 항목이 든 `connections.json` 은 깨지지 않고 읽히고 어느 읽기 명령도 바꾸거나 지우지 않으며, 새 항목은 쉬운 한국어로 거절하고 옛 항목은 지울 수 있다. 낯선 용도 이름은 여전히 깨진 파일이다.
  4) 모양 검사(느슨한 영숫자·`-`·`_`, 8~128자)가 경계에서 정확하고 어느 오류 표면에도 입력한 값이 없다.
  5) 명령줄(`keys purposes·usage·policy·list`)이 한도·단계·시도/성공·마지막 성공/오류·중지 사유를 쉬운 한국어로 보이고(영문 코드 없음), 다른 용도의 출력 모양은 그대로이며, 읽기 명령은 아무것도 만들지 않는다.
  6) `format.keys_ledger_lines` 의 문구(결과 종류별 한국어·상태 번호·단계·중지).
가짜 값만 쓴다(실제 키 모양을 흉내 내지 않는다). 보이지 않는 글자는 `chr()` 로 만든다.
"""
import dataclasses
import io
import json
import re
import sys
import tempfile
import types
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import keystore as ks  # noqa: E402
from chanceblog_desktop.security import shape  # noqa: E402
from chanceblog_desktop.service import cli, doctor  # noqa: E402
from chanceblog_desktop.service import connections as c  # noqa: E402
from chanceblog_desktop.service import format as fmt  # noqa: E402
from chanceblog_desktop.service import quota as q  # noqa: E402

HUB, OLD = "naver_apihub", "naver_openapi"
SIX = [HUB, "naver_searchad", "image_provider", "ai_assist", "blogger", "github_repo"]
KEYED = [HUB, "naver_searchad", "image_provider", "ai_assist", "blogger"]                   # 키를 받는 현재 용도(`github_repo` 는 키를 받지 않는다)
STOP_TEXT = "NAVER API HUB의 새로운 데이터 조회를 사용할 수 없습니다. 저장된 정보와 기본 주제 선정 규칙으로 후보 생성을 계속합니다."
HUB_LABEL = "NAVER API HUB 검색어 트렌드"
OLD_LABEL = "옛 항목 — 네이버 오픈 API(검색·데이터랩)"
TAIL = "wQ8z"                                                       # 가짜 값의 끝 4자 — 다른 글에 우연히 들어 있지 않도록 특이하게
STAMP = "2026-11-02T01:30:12Z"                                      # `ss.NOW`
IDS = tuple(f"abcdef0{number}" * 4 for number in range(1, 5))
ALNUM_REASON = "영문·숫자와 _ - 만 쓸 수 있습니다(따옴표·괄호·한글·붙여 넣은 설명 글이 섞이지 않았는지 확인합니다)"
DEFAULT_REASON = "영문·숫자와 _ - + / = . ~ : 만 쓸 수 있습니다(따옴표·괄호·한글·붙여 넣은 설명 글이 섞이지 않았는지 확인합니다)"
HIDDEN_REASON = "공백·줄바꿈·눈에 안 보이는 글자가 들어 있습니다(앞뒤 공백도 안 됩니다)"
WORDS = ("needs_check", "not_connected", "auth_error", "rate_limited", "connected", "failover", "quota_exhausted", "transient_error", "timeout", "auth_failed", "bad_request",
         "policy_blocked", "content_blocked", "other_error", "unverifiable", "auth_unclear", "state_lost")        # 사람이 보는 글에 나오면 안 되는 영문 상태·결과 코드
PRIORITIES = ("bulk_refresh", "new_candidate", "selected_candidate", "critical")


def hub_fields(seed="a"):
    """NAVER API HUB 항목의 가짜 값 — 영문·숫자뿐이고 비밀 칸은 끝 4자가 `TAIL`. 실제 키 모양이 아니다."""
    return {"client_id": f"hubid{seed}Zk3x91", "client_secret": f"hubsecret{seed}Zk3x" + TAIL}


def windows(value, size=5):
    return [value[index:index + size] for index in range(len(value) - size + 1)]


def surfaces(error):
    """오류가 사용자·로그에 내보내는 모든 글."""
    shown = error.rendered()
    return [str(error), error.log_line(), shown.message, shown.action, shown.retry_text, str(error.detail), repr(error), repr(error.slots), " ".join(str(v) for v in error.slots.values()), repr(error.args)]


def raw_entry(purpose, entry_id, *, name="기본", order=1, client_id="legacyid0001", provider="", ack=""):
    """옛 프로그램이 `connections.json` 에 적었을 항목 하나(칸 이름은 `Entry.to_dict` 와 같다)."""
    return {"entry_id": entry_id, "purpose": purpose, "provider": provider, "name": name, "project": "", "order": order, "state": "active", "created_at": "2026-10-30T01:00:00Z",
            "checked_at": "", "last_ok_at": "", "check_result": "", "bucket": "id-" + shape.short_digest(client_id), "terms_ack_at": ack}


def write_file(ctx, entries, policies=None):
    """연결 설정 파일을 옛 프로그램이 쓰는 모양(정렬된 키·들여쓰기·마지막 줄바꿈)으로 직접 쓴다 → 쓴 바이트."""
    path = ctx.workspace.connections_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "entries": entries, "policies": policies or {}}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path.read_bytes()


class FakeStdin(io.StringIO):
    def __init__(self, text="", tty=False):
        super().__init__(text)
        self.tty = tty
        self.reads = 0

    def isatty(self):
        return self.tty

    def read(self, size=-1):
        self.reads += 1
        return super().read(size)


class FlakyStore(ks.MemoryStore):
    """지우기가 실패하는 가짜 보관소 — 보관소의 값을 먼저 지우는지 본다."""

    def __init__(self):
        super().__init__()
        self.fail_delete = False

    def _delete(self, ref):
        if self.fail_delete:
            raise AppError("KEY_STORE_UNAVAILABLE", detail="시험용 실패")
        return super()._delete(ref)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.clock = ss.Clock()
        self.ctx = ss.make_ctx(self.tmp, clock=self.clock)
        self.store = self.ctx.keystore

    def path(self):
        return self.ctx.workspace.connections_path

    def file_bytes(self):
        path = self.path()
        return path.read_bytes() if path.exists() else None

    def add_hub(self, seed="a", name="기본", **kwargs):
        return c.add_entry(self.ctx, HUB, name=name, fields=hub_fields(seed), **kwargs)

    def run_keys(self, *argv, stdin="", tty=False, prompt=None, json_mode=False):
        out, err = io.StringIO(), io.StringIO()
        source = FakeStdin(stdin, tty)
        code = cli.main((["--json"] if json_mode else []) + ["keys", *argv], out=out, err=err, ctx=self.ctx, stdin=source, prompt=prompt)
        return code, out.getvalue(), err.getvalue(), source


class OldWorldBase(Base):
    def old_world(self, count=2):
        """옛 프로그램이 만든 상태를 흉내 낸다 — `naver_openapi` 항목 `count` 개가 든 연결 설정 파일과 보관소의 값."""
        entries, found = [], []
        for index in range(count):
            fields = {"client_id": f"legacyid{index}001", "client_secret": f"legacysecret{index}" + TAIL}
            entries.append(raw_entry(OLD, IDS[index], name=("옛 기본", "옛 예비", "옛 셋째", "옛 넷째")[index], order=index + 1, client_id=fields["client_id"], ack="" if index == 0 else "2026-10-30T01:05:00Z"))
            self.store.put(f"{OLD}:{IDS[index]}", fields)
            found.append(fields)
        self.raw = write_file(self.ctx, entries)
        return found


# ---- 1) 레지스트리 ------------------------------------------------------------------------------------------------------------------
class ApiHubSpecTest(unittest.TestCase):
    """`naver_apihub` 용도의 값을 못박는다 — 어느 숫자·표시 하나가 바뀌어도 여기서 깨진다."""

    def test_the_purpose_is_first_and_its_basic_properties_are_pinned(self):
        """첫 용도가 NAVER API HUB 이고 이름·키를 받음·호출 코드 없음·항목 1개·옛 용도 아님·한도 묶음 칸이 정한 값 그대로다."""
        spec = c.PURPOSES[HUB]
        self.assertEqual(list(c.PURPOSES)[0], HUB)
        self.assertEqual((spec.key, spec.label), (HUB, HUB_LABEL))
        self.assertEqual((spec.takes_keys, spec.implemented, spec.works_without_key, spec.optional), (True, False, True, True))
        self.assertEqual((spec.max_entries, spec.legacy_to, spec.identity_field, spec.fallback_providers, spec.reset_hour), (1, "", "client_id", (), 0))
        self.assertEqual(spec.primary_secret(), "client_secret")
        self.assertIn("이 PC 전용", spec.client_scope)

    def test_the_two_fields_are_loose_alnum_values_of_8_to_128_characters(self):
        """칸은 Client ID(비밀 아님)·Client Secret(비밀) 둘이고 모양은 영숫자·`-`·`_` 8~128자의 느슨한 검사다."""
        fields = c.PURPOSES[HUB].fields
        self.assertEqual([(item.name, item.label, item.secret, item.min_len, item.max_len, item.charset) for item in fields],
                         [("client_id", "클라이언트 ID", False, 8, 128, "alnum"), ("client_secret", "클라이언트 시크릿", True, 8, 128, "alnum")])

    def test_one_provider_without_a_name_never_rotates_and_has_a_day_and_a_month_window(self):
        """제공자는 이름 없는 하나이고 어떤 오류에도 다른 키로 넘어가지 않으며(`never`) 한도 등급은 하나(하루 100·이번 달 27,000)다."""
        spec = c.PURPOSES[HUB]
        self.assertEqual(len(spec.providers), 1)
        provider = spec.providers[0]
        self.assertEqual((provider.key, provider.label, provider.rotation, provider.default_tier), ("", "NAVER API HUB", "never", "default"))
        self.assertEqual(provider.tier_names(), ("default",))
        expected = (c.Window("day", "day", 100), c.Window("month", "month", 27000))
        self.assertEqual(provider.windows(), expected)
        self.assertEqual(provider.windows("default"), expected)
        self.assertEqual(provider.windows("other"), ())
        self.assertIs(spec.provider(""), provider)
        self.assertIsNone(spec.provider("nope"))
        for window in provider.windows():
            self.assertEqual((window.minutes, window.header_sync), (0, False))

    def test_the_ledger_and_fail_closed_flags_the_console_limit_and_the_fixed_sentence(self):
        """장부·Fail-Closed 표시, 콘솔 월 한도 30,000, 사용자에게 보이는 고정 문구(기술 코드 없음)가 정한 그대로다."""
        provider = c.PURPOSES[HUB].providers[0]
        self.assertIs(provider.ledger, True)
        self.assertIs(provider.fail_closed, True)
        self.assertEqual(provider.console_limit, 30000)
        self.assertEqual(provider.stop_text, STOP_TEXT)
        self.assertEqual(c.APIHUB_STOP_TEXT, STOP_TEXT)
        self.assertIsNone(re.search(r"[A-Z]+_[A-Z_]+", provider.stop_text), "고정 문구에는 기술 오류 코드가 없다")

    def test_the_internal_limits_are_ninety_percent_of_the_console_limit(self):
        """프로그램 안 월 한도 27,000 은 콘솔 30,000 의 정확히 90% 이고 마지막 단계의 경계와 같다. 하루 한도는 100, 새 분석 상한은 5."""
        self.assertEqual((c.APIHUB_INTERNAL_DAY, c.APIHUB_INTERNAL_MONTH, c.APIHUB_CONSOLE_MONTH, c.APIHUB_NEW_CALL_CAP), (100, 27000, 30000, 5))
        provider = c.PURPOSES[HUB].providers[0]
        day, month = provider.windows()
        self.assertEqual(day.limit, 100)
        self.assertEqual(month.limit, provider.console_limit * 90 // 100)
        self.assertLess(month.limit, provider.console_limit)
        closed = next(stage for stage in provider.stages if stage.name == c.STAGE_CLOSED)
        self.assertEqual(c.stage_threshold(provider, closed), month.limit, "마지막 단계의 경계가 프로그램 안 월 한도다")

    def test_the_stage_table_is_exactly_70_80_90_percent(self):
        """단계표: 70% 안내만 · 80% 자동 새로고침 거절+직접 분석 5회 상한 · 90% 네 우선순위 모두 거절(필수 호출 포함)."""
        provider = c.PURPOSES[HUB].providers[0]
        self.assertEqual([(stage.name, stage.percent, stage.deny, stage.manual_max_calls) for stage in provider.stages],
                         [("notice", 70, (), 0), ("limited", 80, ("bulk_refresh",), 5), ("closed", 90, PRIORITIES, 0)])
        self.assertEqual((c.STAGE_NOTICE, c.STAGE_LIMITED, c.STAGE_CLOSED), ("notice", "limited", "closed"))
        for stage in provider.stages:
            with self.subTest(stage=stage.name):
                self.assertTrue(stage.text.strip())
                self.assertIn(f"{stage.percent}%", stage.text)
        self.assertEqual(set(provider.stages[-1].deny), set(q.PRIORITIES), "마지막 단계는 모든 우선순위를 거절한다 — 필수 호출도 예외가 없다")

    def test_the_stage_thresholds_are_21000_24000_27000(self):
        """단계 경계는 콘솔 월 한도 × 비율이다: 21,000 · 24,000 · 27,000."""
        provider = c.PURPOSES[HUB].providers[0]
        self.assertEqual([c.stage_threshold(provider, stage) for stage in provider.stages], [21000, 24000, 27000])

    def test_the_stage_switches_only_when_the_usage_after_the_call_goes_over_a_threshold(self):
        """호출 뒤 사용량이 경계와 같으면 아직 아니고 1 이라도 넘어야 그 단계다(21,000 → 없음 · 21,001 → 안내 · 24,001 → 제한 · 27,001 → 중지)."""
        provider = c.PURPOSES[HUB].providers[0]
        for used_after, expected in ((0, None), (1, None), (21000, None), (21001, "notice"), (24000, "notice"), (24001, "limited"), (27000, "limited"), (27001, "closed"), (10 ** 6, "closed")):
            with self.subTest(used_after=used_after):
                stage = c.stage_of(provider, used_after)
                self.assertEqual(stage.name if stage is not None else None, expected)

    def test_the_legacy_purpose_keeps_its_old_definition_and_sits_last(self):
        """옛 `naver_openapi` 는 레지스트리 맨 뒤에 옛 정의 그대로(하루 25,000·돌려쓰기 허용·항목 3개·넓은 글자) 남아 있고 새 용도를 가리킨다."""
        spec = c.PURPOSES[OLD]
        self.assertEqual(list(c.PURPOSES), SIX + [OLD])
        self.assertEqual((spec.legacy_to, spec.label, spec.max_entries, spec.takes_keys, spec.implemented, spec.identity_field), (HUB, OLD_LABEL, 3, True, False, "client_id"))
        self.assertEqual([(item.name, item.secret, item.min_len, item.max_len, item.charset) for item in spec.fields], [("client_id", False, 8, 64, ""), ("client_secret", True, 8, 64, "")])
        provider = spec.providers[0]
        self.assertEqual((provider.key, provider.rotation, provider.windows(), provider.ledger, provider.fail_closed, provider.console_limit, provider.stages),
                         ("", "limited", (c.Window("day", "day", 25000),), False, False, 0, ()))

    def test_naver_searchad_is_untouched(self):
        """검색광고 용도는 이 변경에서 건드리지 않았다 — 칸·한도(모름)·메모·항목 수까지 그대로."""
        spec = c.PURPOSES["naver_searchad"]
        self.assertEqual((spec.label, spec.summary, spec.max_entries, spec.legacy_to, spec.identity_field, spec.takes_keys, spec.implemented),
                         ("네이버 검색광고 API", "키워드 도구의 월간 검색 수 같은 지표를 조회하는 데 씁니다(준비 중).", 3, "", "customer_id", True, False))
        self.assertEqual([(item.name, item.label, item.secret, item.min_len, item.max_len, item.example, item.charset) for item in spec.fields],
                         [("customer_id", "고객 ID", False, 3, 20, "숫자 7자리 안팎", ""), ("access_license", "액세스 라이선스", True, 16, 128, "영문·숫자 40~64자", ""),
                          ("secret_key", "비밀 키", True, 16, 128, "영문·숫자·기호 40자 안팎", "")])
        provider = spec.providers[0]
        self.assertEqual((provider.key, provider.label, provider.rotation, provider.tiers, provider.default_tier, provider.note),
                         ("", "네이버 검색광고", "limited", (("default", ()),), "default", "한도를 아직 확인하지 못했습니다 — 한도 오류 응답으로만 감지합니다"))

    def test_the_other_purposes_keep_their_fields_providers_and_windows(self):
        """이미지 공급자(Unsplash 데모/정식 창)·AI 보조·Blogger·GitHub 의 칸·제공자·한도 창이 그대로다."""
        image = c.PURPOSES["image_provider"]
        self.assertEqual([(item.name, item.label, item.secret, item.min_len, item.max_len) for item in image.fields], [("access_key", "Access Key", True, 16, 128)])
        self.assertEqual([(item.key, item.rotation) for item in image.providers], [("unsplash", "never"), ("pexels", "limited"), ("pixabay", "limited")])
        self.assertEqual(image.providers[0].tiers, (("demo", (c.Window("hour", "sliding", 50, 60, True),)), ("production", (c.Window("hour", "sliding", 1000, 60, True),))))
        self.assertEqual((image.providers[0].default_tier, image.identity_field, image.label), ("demo", "", "이미지 공급자"))
        for other in image.providers[1:]:
            self.assertEqual((other.tiers, other.default_tier), ((("default", ()),), "default"))
        ai = c.PURPOSES["ai_assist"]
        self.assertEqual([(item.name, item.label, item.secret, item.min_len, item.max_len) for item in ai.fields], [("key", "API 키", True, 16, 256)])
        self.assertEqual([(item.key, item.label, item.rotation, item.tiers) for item in ai.providers], [("gemini", "Gemini", "limited", (("default", ()),))])
        blogger = c.PURPOSES["blogger"]
        self.assertEqual([(item.name, item.secret, item.min_len, item.max_len) for item in blogger.fields], [("client_id", False, 20, 128), ("client_secret", True, 8, 128), ("refresh_token", True, 20, 512)])
        self.assertEqual(([(item.key, item.label, item.rotation, item.tiers) for item in blogger.providers], blogger.identity_field), ([("", "Google", "limited", (("default", ()),))], "client_id"))
        git = c.PURPOSES["github_repo"]
        self.assertEqual((git.takes_keys, git.fields, [(item.key, item.label, item.rotation, item.tiers) for item in git.providers]), (False, (), [("", "GitHub", "never", (("default", ()),))]))

    def test_no_other_purpose_or_provider_has_the_new_flags(self):
        """새 칸(항목 상한·옛 용도·장부·Fail-Closed·콘솔 한도·단계표·고정 문구·글자 종류)은 NAVER API HUB 와 옛 용도 표시 말고는 모두 기본값이다."""
        self.assertEqual(c.MAX_ENTRIES_PER_PURPOSE, 3)
        for key, spec in c.PURPOSES.items():
            if key == HUB:
                continue
            with self.subTest(purpose=key):
                self.assertEqual(spec.max_entries, c.MAX_ENTRIES_PER_PURPOSE)
                self.assertEqual(spec.legacy_to, HUB if key == OLD else "")
                for provider in spec.providers:
                    self.assertEqual((provider.ledger, provider.fail_closed, provider.console_limit, provider.stages, provider.stop_text), (False, False, 0, (), ""))
                for item in spec.fields:
                    self.assertEqual(item.charset, "")


class AuthStateTest(Base):
    """`connections.auth_state` — Fail-Closed 가 신규 호출을 열어도 되는 인증 상태인지(시험 성공 기록이 24시간 안일 때만 `clear`)."""

    def entry_with(self, **changes):
        """키가 하나뿐이라 항목은 한 번만 만들고, 확인 결과 칸만 바꾼 사본으로 판정을 본다."""
        if not hasattr(self, "entry"):
            self.entry = self.add_hub().entry
        return dataclasses.replace(self.entry, **changes)

    def test_only_a_fresh_successful_check_is_clear(self):
        """시험 성공 기록이 24시간 안(24시간 정각까지)일 때만 `clear`, 기록이 없거나 오래됐거나 오류면 `unclear`, 인증 실패면 성공 기록이 있어도 `auth_failed` 다."""
        now = self.ctx.now()
        stamp = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        cases = (
            ({}, c.AUTH_UNCLEAR), ({"check_result": "ok", "last_ok_at": ""}, c.AUTH_UNCLEAR), ({"check_result": "error", "last_ok_at": stamp(now)}, c.AUTH_UNCLEAR),
            ({"check_result": "ok", "last_ok_at": stamp(now)}, c.AUTH_CLEAR), ({"check_result": "ok", "last_ok_at": stamp(now - timedelta(hours=24))}, c.AUTH_CLEAR),
            ({"check_result": "ok", "last_ok_at": stamp(now - timedelta(hours=24, seconds=1))}, c.AUTH_UNCLEAR),
            ({"check_result": "auth_failed", "last_ok_at": stamp(now)}, c.AUTH_BAD), ({"check_result": "auth_failed"}, c.AUTH_BAD),
        )
        for changes, expected in cases:
            with self.subTest(changes=changes):
                self.assertEqual(c.auth_state(self.entry_with(**changes), now=now), expected)
        self.assertEqual((c.AUTH_CLEAR, c.AUTH_BAD, c.AUTH_UNCLEAR), ("clear", "auth_failed", "unclear"))

    def test_the_valid_hours_can_be_given(self):
        """유효 시간을 인자로 줄 수 있고 그 경계도 정확하다(2시간 전 성공은 2시간 기준에는 맞고 1시간 기준에는 틀리다)."""
        now = self.ctx.now()
        entry = self.entry_with(check_result="ok", last_ok_at=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertEqual(c.auth_state(entry, now=now, valid_hours=2), c.AUTH_CLEAR)
        self.assertEqual(c.auth_state(entry, now=now, valid_hours=1), c.AUTH_UNCLEAR)


# ---- 2) 키는 하나뿐이다 ------------------------------------------------------------------------------------------------------------
class OneKeyTest(Base):
    def test_a_second_entry_is_refused_even_with_the_terms_and_another_value(self):
        """둘째 항목은 약관 확인·다른 이름·다른 값·다른 상태·다른 프로젝트·같은 이름까지 모두 한도 거절이고 보관소와 파일은 그대로다(한도를 늘리려는 키 돌려쓰기 금지)."""
        self.add_hub("a")
        refs, before = self.store.list_refs(), self.file_bytes()
        for name, kwargs in (("둘째", {}), ("둘째", {"terms_ack": True}), ("둘째", {"terms_ack": True, "state": "standby"}), ("둘째", {"terms_ack": True, "project": "다른 앱"}), ("기본", {"terms_ack": True})):
            with self.subTest(name=name, kwargs=kwargs):
                error = ss.code_of(c.add_entry, self.ctx, HUB, name=name, fields=hub_fields("b"), **kwargs)
                self.assertEqual(error.code, "KEY_ENTRY_LIMIT")
                self.assertEqual(error.slots, {"용도": HUB_LABEL, "개수": "1"})
                self.assertEqual(self.store.list_refs(), refs)
                self.assertEqual(self.file_bytes(), before)

    def test_the_refusal_says_one_key_in_plain_korean_and_why(self):
        """거절 문구는 '1개까지만' 이라고 쉬운 한국어로 말하고 세부에 이유(돌려 쓰지 않음)와 바꾸는 길(지운 뒤 새로 넣기)이 있다."""
        self.add_hub("a")
        error = ss.code_of(c.add_entry, self.ctx, HUB, name="둘째", fields=hub_fields("b"), terms_ack=True)
        shown = error.rendered()
        self.assertIn("「1」개까지만", shown.message)
        self.assertIn(HUB_LABEL, shown.message)
        self.assertEqual(error.detail, c.ENTRY_LIMIT_DETAIL)
        for phrase in ("하나만", "돌려 쓰지 않습니다", "keys remove"):
            self.assertIn(phrase, error.detail)

    def test_another_purpose_keeps_three_entries_and_the_old_limit_message_without_the_extra_detail(self):
        """3개까지 두는 제공자는 4번째 거절 문구에 '1개' 설명(세부)이 붙지 않는다. 의도적 갱신(P4f, D-250): 이미지 공급자(Unsplash)는 운영자 정책 표로 1개가 되어, 3개를 두는 AI 보조(Gemini)로 같은 일을 본다."""
        for number in range(3):
            c.add_entry(self.ctx, "ai_assist", name=f"키{number}", fields={"key": f"aikey{number}" + "Q" * 20}, terms_ack=True)
        error = ss.code_of(c.add_entry, self.ctx, "ai_assist", name="넷째", fields={"key": "aikey9" + "Q" * 20}, terms_ack=True)
        self.assertEqual((error.code, error.slots, error.detail), ("KEY_ENTRY_LIMIT", {"용도": c.PURPOSES["ai_assist"].label, "개수": "3"}, ""))
        self.assertIn("「3」개까지만", error.rendered().message)

    def test_after_removing_the_first_one_a_new_key_can_be_added(self):
        """지운 뒤에는 새 키를 넣을 수 있다 — 키를 바꾸는 길(지우고 다시 넣기)이 막히지 않는다."""
        first = self.add_hub("a", new_id=lambda: IDS[0]).entry
        c.remove_entry(self.ctx, c.short_id(first.entry_id), confirmed=True, keystore=self.store)
        self.assertEqual(self.store.list_refs(), [])
        second = self.add_hub("b", name="새 키", new_id=lambda: IDS[1]).entry
        self.assertEqual([(item.entry_id, item.name) for item in c.load(self.ctx).of_purpose(HUB)], [(IDS[1], "새 키")])
        self.assertEqual(self.store.list_refs(), [second.ref])

    def test_the_cli_refuses_the_second_key_before_reading_stdin_or_asking_the_terms(self):
        """명령줄은 둘째 키를 약관 질문보다 먼저, 키(표준 입력·숨김 입력)를 읽거나 묻기 전에 거절한다 — 입력한 키를 헛되이 받지 않는다."""
        self.add_hub("a")
        refs, before = self.store.list_refs(), self.file_bytes()
        code, out, err, source = self.run_keys("add", HUB, "--name", "둘째", "--stdin", stdin=json.dumps(hub_fields("b")))
        self.assertEqual((code, out, source.reads), (1, "", 0))
        self.assertIn("코드: KEY_ENTRY_LIMIT", err)
        self.assertNotIn("KEY_FAILOVER_TERMS_REQUIRED", err)
        asked = []
        code, out, err, source = self.run_keys("add", HUB, "--name", "둘째", tty=True, prompt=lambda text: asked.append(text) or "x")
        self.assertEqual((code, out, asked, source.reads), (1, "", [], 0))
        self.assertIn("코드: KEY_ENTRY_LIMIT", err)
        self.assertEqual(self.store.list_refs(), refs)
        self.assertEqual(self.file_bytes(), before)

    def test_the_cli_refuses_the_second_key_the_same_way_with_the_terms_flag(self):
        """약관 확인 표시(`--i-understand-terms`)를 붙여도 거절은 그대로고 키를 읽지 않는다."""
        self.add_hub("a")
        code, out, err, source = self.run_keys("add", HUB, "--name", "둘째", "--stdin", "--i-understand-terms", "--state", "예비", stdin=json.dumps(hub_fields("b")))
        self.assertEqual((code, out, source.reads), (1, "", 0))
        self.assertIn("코드: KEY_ENTRY_LIMIT", err)
        self.assertEqual(len(self.store.list_refs()), 1)

    def test_other_purposes_still_ask_for_the_terms_before_the_key_is_read_and_before_the_limit(self):
        """다른 용도의 검사 순서는 그대로다: 둘째 키는 약관 확인이 먼저(키를 읽기 전에), 이미 3개여도 확인 표시가 없으면 약관 안내가 먼저이고 표시가 있으면 한도 거절이다."""
        c.add_entry(self.ctx, "ai_assist", name="가", fields={"key": "aikeyA0" + "Q" * 20})                    # 의도적 갱신(P4f, D-250): 3개를 두는 AI 보조(Gemini)로 — 이미지 공급자(Unsplash)는 이제 1개라 둘째 키를 키 읽기 전에 거절한다
        code, out, err, source = self.run_keys("add", "ai_assist", "--name", "나", "--stdin", stdin=json.dumps({"key": "aikeyB0" + "Q" * 20}))
        self.assertEqual((code, out, source.reads), (1, "", 0))
        self.assertIn("코드: KEY_FAILOVER_TERMS_REQUIRED", err)
        for number in (1, 2):
            c.add_entry(self.ctx, "ai_assist", name=f"추가{number}", fields={"key": f"aikeyC{number}" + "Q" * 20}, terms_ack=True)
        code, out, err, source = self.run_keys("add", "ai_assist", "--name", "넷째", "--stdin", stdin=json.dumps({"key": "aikeyD0" + "Q" * 20}))
        self.assertEqual((code, source.reads), (1, 0))
        self.assertIn("코드: KEY_FAILOVER_TERMS_REQUIRED", err)
        code, out, err, source = self.run_keys("add", "ai_assist", "--name", "넷째", "--stdin", "--i-understand-terms", stdin=json.dumps({"key": "aikeyD0" + "Q" * 20}))
        self.assertEqual(code, 1)
        self.assertIn("코드: KEY_ENTRY_LIMIT", err)
        self.assertEqual(len(self.store.list_refs()), 3)

    def test_a_file_with_two_hub_entries_is_an_invalid_file(self):
        """손으로 고친 파일에 NAVER API HUB 항목이 둘이면 깨진 파일이다 — 몰래 둘째 키가 생기지 않는다."""
        write_file(self.ctx, [raw_entry(HUB, IDS[0], client_id="hubid0001ab"), raw_entry(HUB, IDS[1], name="둘째", order=2, client_id="hubid0002ab")])
        error = ss.code_of(c.load, self.ctx)
        self.assertEqual((error.code, error.detail), ("CONNECTIONS_FILE_INVALID", "한 용도의 항목이 1개를 넘는다"))
        write_file(self.ctx, [raw_entry(HUB, IDS[0], client_id="hubid0001ab")])
        self.assertEqual([item.entry_id for item in c.load(self.ctx).entries], [IDS[0]])

    def test_the_entry_count_limit_of_a_file_is_per_purpose(self):
        """옛 용도는 3개까지 읽히고 4개면 깨진 파일이다(용도마다 자기 상한을 쓴다)."""
        entries = [raw_entry(OLD, IDS[index], name=f"옛{index}", order=index + 1, client_id=f"legacyid{index}001") for index in range(4)]
        write_file(self.ctx, entries[:3])
        self.assertEqual(len(c.load(self.ctx).of_purpose(OLD)), 3)
        write_file(self.ctx, entries)
        error = ss.code_of(c.load, self.ctx)
        self.assertEqual((error.code, error.detail), ("CONNECTIONS_FILE_INVALID", "한 용도의 항목이 3개를 넘는다"))


# ---- 3) 옛 항목 처리 ----------------------------------------------------------------------------------------------------------------
class LegacyTest(OldWorldBase):
    def test_an_old_file_loads_and_reading_commands_change_and_delete_nothing(self):
        """옛 `naver_openapi` 항목이 든 파일은 깨지지 않고 읽히고, 읽기 명령(목록·사용량·용도·정책·진단)은 파일·보관소·사용량 파일 어느 것도 바꾸거나 지우거나 만들지 않는다."""
        self.old_world(2)
        refs = self.store.list_refs()
        self.assertEqual(len(refs), 2)
        data = c.load(self.ctx)
        self.assertEqual([item.entry_id for item in data.of_purpose(OLD)], [IDS[0], IDS[1]])
        self.assertEqual(data.of_purpose(OLD)[0].bucket, "id-" + shape.short_digest("legacyid0001"))
        self.assertEqual(data.of_purpose(OLD)[1].terms_ack_at, "2026-10-30T01:05:00Z")
        c.list_entries(self.ctx, keystore=self.store)
        q.QuotaGuard(self.ctx).usage()
        c.diagnostic_summary(self.ctx)
        for argv in (("list",), ("usage",), ("purposes",), ("policy", OLD), ("list", "--purpose", OLD), ("usage", OLD)):
            for json_mode in (False, True):
                with self.subTest(argv=argv, json=json_mode):
                    code, out, err, _ = self.run_keys(*argv, json_mode=json_mode)
                    self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.file_bytes(), self.raw, "읽기만 했으므로 파일은 바이트까지 그대로다")
        self.assertEqual(self.store.list_refs(), refs, "아무것도 자동으로 지우지 않는다")
        self.assertFalse(self.ctx.workspace.quota_path.exists(), "읽기 명령은 사용량 파일을 만들지 않는다")
        self.assertFalse(self.path().with_name("connections.json.bak").exists())

    def test_legacy_entries_show_as_needing_a_check_without_any_part_of_the_key(self):
        """옛 항목의 상태는 '연결 확인 필요'(호출 코드가 없다)이고 키의 일부(끝 4자 포함)는 보이지 않는다(PCSEC1 H2 — 예전에는 값이 16자 이상이면 끝 4자가 보였다)."""
        self.old_world(2)
        views = c.list_entries(self.ctx, keystore=self.store)
        self.assertEqual([(view.ordinal, view.entry.purpose, view.entry.name, view.status) for view in views], [(1, OLD, "옛 기본", c.NEEDS_CHECK), (2, OLD, "옛 예비", c.NEEDS_CHECK)])
        self.assertFalse(hasattr(views[0], "tail"))
        self.assertNotIn(TAIL, repr(views[0]) + str(views[0].to_dict()))

    def test_keys_list_marks_legacy_entries_and_names_the_new_purpose(self):
        """`keys list` 는 옛 항목마다 '옛 항목 — 새 키는 …(naver_apihub)에 넣고 이 항목은 지웁니다(키는 지우지 않았습니다)' 를 붙이고 용도별 상태에 옛 용도를 한 줄 보인다. 키 원문은 없다."""
        found = self.old_world(2)
        code, out, err, _ = self.run_keys("list")
        self.assertEqual((code, err), (0, ""))
        self.assertIn(f"{OLD_LABEL}: 연결 확인 필요", out)
        self.assertEqual(out.count("옛 항목 — 새 키는 NAVER API HUB 검색어 트렌드(naver_apihub)에 넣고 이 항목은 지웁니다(키는 지우지 않았습니다)"), 2)
        self.assertIn("옛 기본", out)
        self.assertIn("옛 예비", out)
        for fields in found:
            self.assertNotIn(fields["client_secret"], out)
        for word in WORDS:
            self.assertNotIn(word, out)

    def test_the_purpose_status_block_lists_the_legacy_purpose_only_when_it_has_entries(self):
        """용도별 상태 줄에 옛 용도는 그 항목이 남아 있을 때만 나온다 — 처음 쓰는 사람의 화면에는 옛 용도가 없다."""
        self.add_hub("a")
        code, out, err, _ = self.run_keys("list")
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("옛 항목", out)
        self.assertNotIn(OLD, out)
        code, out, err, _ = self.run_keys("list", json_mode=True)
        self.assertEqual([item["purpose"] for item in json.loads(out)["data"]["purposes"]], KEYED)

    def test_keys_list_json_has_the_legacy_purpose_with_its_entries(self):
        """`--json` 목록은 옛 용도(맨 뒤)와 그 항목들(번호·상태)을 담는다."""
        self.old_world(1)
        code, out, err, _ = self.run_keys("list", json_mode=True)
        self.assertEqual((code, err), (0, ""))
        purposes = {item["purpose"]: item for item in json.loads(out)["data"]["purposes"]}
        self.assertEqual(list(purposes), KEYED + [OLD])
        self.assertEqual([item["entry_id"] for item in purposes[OLD]["entries"]], [IDS[0]])
        self.assertEqual((purposes[OLD]["label"], purposes[OLD]["status"], purposes[OLD]["status_text"]), (OLD_LABEL, "needs_check", "연결 확인 필요"))
        self.assertEqual(purposes[HUB]["entries"], [])

    def test_removing_a_legacy_entry_deletes_the_secret_first_then_the_metadata(self):
        """옛 항목을 지울 때는 보관소의 값을 먼저 지운다 — 값을 못 지우면 메타데이터도 그대로이고, 지운 뒤에는 순서가 당겨진다."""
        self.old_world(2)
        flaky = FlakyStore()
        for ref in self.store.list_refs():
            flaky.put(ref, self.store.get(ref).to_dict())
        flaky.fail_delete = True
        error = ss.code_of(c.remove_entry, self.ctx, IDS[0][:8], confirmed=True, keystore=flaky)
        self.assertEqual(error.code, "KEY_STORE_UNAVAILABLE")
        self.assertEqual(self.file_bytes(), self.raw, "보관소 값을 못 지웠으면 메타데이터도 그대로다")
        self.assertTrue(flaky.exists(f"{OLD}:{IDS[0]}"))
        flaky.fail_delete = False
        result = c.remove_entry(self.ctx, IDS[0][:8], confirmed=True, keystore=flaky)
        self.assertEqual((result.entry.entry_id, result.purpose_label), (IDS[0], OLD_LABEL))
        self.assertFalse(flaky.exists(f"{OLD}:{IDS[0]}"))
        self.assertTrue(flaky.exists(f"{OLD}:{IDS[1]}"))
        rest = c.load(self.ctx).of_purpose(OLD)
        self.assertEqual([(item.entry_id, item.order) for item in rest], [(IDS[1], 1)])

    def test_the_cli_removes_a_legacy_entry_only_with_the_confirmation(self):
        """명령줄: 확인(`--yes`) 없이는 아무것도 지우지 않고, 번호 앞 8자와 확인이 있으면 보관소의 값과 항목을 함께 지운다."""
        self.old_world(2)
        code, out, err, _ = self.run_keys("remove", IDS[1][:8])
        self.assertEqual(code, 1)
        self.assertEqual(len(self.store.list_refs()), 2)
        self.assertEqual(self.file_bytes(), self.raw)
        code, out, err, _ = self.run_keys("remove", IDS[1][:8], "--yes")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("키 항목을 지웠습니다: 옛 예비", out)
        self.assertEqual(self.store.list_refs(), [f"{OLD}:{IDS[0]}"])
        self.assertEqual([item.entry_id for item in c.load(self.ctx).of_purpose(OLD)], [IDS[0]])

    def test_adding_to_the_legacy_purpose_is_refused_in_plain_korean_and_changes_nothing(self):
        """옛 용도에는 새 항목을 못 더한다 — 새 용도(naver_apihub)에 넣으라고, 옛 키는 지우지 않았다고 쉬운 한국어로 알리고, 값 검사보다 먼저 거절하며 보관소·파일은 그대로다."""
        self.old_world(1)
        refs, before = self.store.list_refs(), self.file_bytes()
        fields = {"client_id": "legacyidnew001", "client_secret": "legacysecretnew" + TAIL}
        error = ss.code_of(c.add_entry, self.ctx, OLD, name="새 옛", fields=fields, terms_ack=True)
        self.assertEqual((error.code, error.slots["항목"]), ("KEY_INVALID_SHAPE", "용도"))
        for phrase in ("옛 용도", HUB_LABEL, HUB, "지우지 않았습니다"):
            self.assertIn(phrase, error.slots["이유"])
        self.assertIn(HUB, error.rendered().message)
        self.assertEqual(self.store.list_refs(), refs)
        self.assertEqual(self.file_bytes(), before)
        again = ss.code_of(c.add_entry, self.ctx, OLD, name="x", fields={"nope": "y"})
        self.assertEqual(again.slots["항목"], "용도", "잘못된 값보다 옛 용도 거절이 먼저다")
        for text in surfaces(error):
            self.assertNotIn(fields["client_secret"], text)
            self.assertNotIn(TAIL, text)

    def test_the_cli_refuses_the_legacy_purpose_before_reading_or_asking_for_a_key(self):
        """명령줄은 옛 용도를 키를 읽거나 묻기 전에 거절한다(표준 입력 읽기 0번·숨김 입력 질문 0번)."""
        self.old_world(1)
        refs, before = self.store.list_refs(), self.file_bytes()
        fields = {"client_id": "legacyidnew001", "client_secret": "legacysecretnew" + TAIL}
        for extra in ((), ("--i-understand-terms",)):
            with self.subTest(extra=extra):
                code, out, err, source = self.run_keys("add", OLD, "--name", "새 옛", "--stdin", *extra, stdin=json.dumps(fields))
                self.assertEqual((code, out, source.reads), (1, "", 0))
                self.assertIn("코드: KEY_INVALID_SHAPE", err)
                self.assertIn(HUB, err)
                self.assertNotIn(TAIL, err)
                asked = []
                code, out, err, source = self.run_keys("add", OLD, "--name", "새 옛", *extra, tty=True, prompt=lambda text: asked.append(text) or "x")
                self.assertEqual((code, out, asked, source.reads), (1, "", [], 0))
        self.assertEqual(self.store.list_refs(), refs)
        self.assertEqual(self.file_bytes(), before)

    def test_state_order_and_policy_still_work_on_legacy_entries_and_delete_no_secret(self):
        """옛 항목도 상태·순서·정책은 바꿀 수 있고(지우기 전의 정리) 어느 것도 비밀을 지우지 않는다."""
        self.old_world(2)
        entry, before = c.set_state(self.ctx, "1", "standby")
        self.assertEqual((entry.entry_id, before, entry.state, entry.bucket), (IDS[0], "active", "standby", "id-" + shape.short_digest("legacyid0001")))
        items = c.reorder(self.ctx, OLD, [IDS[1][:8]])
        self.assertEqual([item.entry_id for item in items], [IDS[1], IDS[0]])
        c.set_policy(self.ctx, OLD, on_limit="save")
        self.assertEqual(c.load(self.ctx).policy(OLD).on_limit, "save")
        self.assertEqual(len(self.store.list_refs()), 2)

    def test_usage_hides_the_legacy_purpose_even_when_it_has_entries(self):
        """사용량 화면에는 옛 용도가 없다(사용량을 세지 않는다) — `keys usage 옛용도` 는 보여 줄 것이 없다고만 말한다."""
        self.old_world(2)
        self.assertEqual([view.purpose for view in q.QuotaGuard(self.ctx).usage()], KEYED)
        self.assertEqual(q.QuotaGuard(self.ctx).usage(OLD), [])
        code, out, err, _ = self.run_keys("usage", OLD)
        self.assertEqual((code, err, out.strip()), (0, "", "보여 줄 용도가 없습니다."))
        code, out, err, _ = self.run_keys("usage")
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("옛 항목", out)
        code, out, err, _ = self.run_keys("usage", OLD, json_mode=True)
        self.assertEqual(json.loads(out)["data"]["usage"], [])

    def test_the_purposes_command_lists_the_six_current_purposes_and_no_legacy_one(self):
        """`keys purposes` 는 옛 항목이 있어도 현재 용도 여섯 개만 보인다 — 사람 글과 `--json` 모두."""
        self.old_world(1)
        code, out, err, _ = self.run_keys("purposes")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(re.findall(r"^\[([a-z_]+)\]", out, re.M), SIX)
        self.assertNotIn(OLD, out)
        self.assertNotIn("옛 항목", out)
        code, out, err, _ = self.run_keys("purposes", json_mode=True)
        self.assertEqual([item["purpose"] for item in json.loads(out)["data"]["purposes"]], SIX)

    def test_listed_purposes_follow_the_entries(self):
        """`listed_purposes` — 항목이 없으면 현재 용도 여섯, 옛 항목이 있으면 맨 뒤에 옛 용도가 더해진다. 옛 용도가 아닌 레지스트리(시험용)는 모두 나온다."""
        self.assertEqual(c.listed_purposes(c.Data()), tuple(SIX))
        self.old_world(1)
        self.assertEqual(c.listed_purposes(c.load(self.ctx)), tuple(SIX) + (OLD,))
        generic = ss.generic_registry()
        self.assertEqual(c.listed_purposes(c.Data(), generic), tuple(generic))

    def test_the_diagnostic_summary_shows_the_legacy_row_only_when_it_has_entries(self):
        """진단 요약은 옛 용도 한 줄을 그 항목이 있을 때만 보이고 개수만 담는다(번호·이름·묶음·끝 4자 없음)."""
        self.assertEqual([row["purpose"] for row in c.diagnostic_summary(self.ctx)["purposes"]], SIX)
        self.old_world(2)
        summary = c.diagnostic_summary(self.ctx)
        self.assertEqual([row["purpose"] for row in summary["purposes"]], SIX + [OLD])
        self.assertEqual(summary["purposes"][-1], {"purpose": OLD, "entries": 2, "active": 2})
        text = json.dumps(summary, ensure_ascii=False)
        for probe in (IDS[0], IDS[0][:8], "옛 기본", "id-", TAIL, "legacyid0001"):
            self.assertNotIn(probe, text)

    def test_the_doctor_check_passes_with_legacy_entries_and_changes_nothing(self):
        """점검(`doctor`)의 연결 설정 항목은 옛 항목이 있어도 정상이고 파일을 바꾸지 않는다."""
        self.old_world(2)
        results = doctor.run_doctor(self.ctx)
        item = next(found for found in results if found.name == "연결 설정(키 항목)")
        self.assertEqual((item.status, item.code), ("ok", ""))
        self.assertIn("키 항목 2개", item.message)
        self.assertEqual(self.file_bytes(), self.raw)

    def test_an_unknown_purpose_name_or_a_wrong_provider_is_still_an_invalid_file(self):
        """옛 용도 길이 낯선 용도 이름을 받아 주지 않는다 — 비슷한 이름·빈 이름·글이 아닌 값·옛 용도의 낯선 제공자 모두 깨진 파일이다."""
        for purpose in ("naver_unknown", "naver_openapi2", "Naver_Openapi", "naver-openapi", "", 5, None):
            with self.subTest(purpose=purpose):
                entry = raw_entry(OLD, IDS[0])
                entry["purpose"] = purpose
                write_file(self.ctx, [entry])
                self.assertEqual(ss.code_of(c.load, self.ctx).code, "CONNECTIONS_FILE_INVALID")
        entry = raw_entry(OLD, IDS[0], provider="unsplash")
        write_file(self.ctx, [entry])
        self.assertEqual(ss.code_of(c.load, self.ctx).code, "CONNECTIONS_FILE_INVALID")


# ---- 4) 모양 검사 ------------------------------------------------------------------------------------------------------------------
class ShapeTest(unittest.TestCase):
    def problem(self, value, charset="alnum", min_len=8, max_len=128):
        return shape.value_problem(value, min_len=min_len, max_len=max_len, charset=charset)

    def test_alnum_accepts_letters_digits_dash_and_underscore(self):
        """느슨한 검사는 영문 대소문자·숫자·`-`·`_` 를 받는다(맨 앞·맨 뒤의 `-` `_` 도 모양으로는 받는다)."""
        for value in ("Ab1-_Cd2", "ABCDEFGH", "abcdefgh", "12345678", "a-b_c-d_e", "-_-_-_-_", "x" * 40 + "-" + "9" * 40):
            with self.subTest(value=value[:12]):
                self.assertEqual(self.problem(value), "")

    def test_alnum_length_boundaries_are_7_8_128_129(self):
        """길이 경계: 7자는 짧고 8자는 되고 128자는 되고 129자는 길다."""
        self.assertEqual(self.problem("a1" * 3 + "b"), "너무 짧습니다(최소 8자)")
        self.assertEqual(self.problem("a1" * 4), "")
        self.assertEqual(self.problem("a1" * 64), "")
        self.assertEqual(self.problem("a1" * 64 + "b"), "너무 깁니다(최대 128자)")

    def test_alnum_rejects_the_wider_symbols_the_default_accepts(self):
        """`+ / = . ~ :` 는 이 용도에서는 거절하고(이유는 영문·숫자와 `_ -` 만) 이유 글에 입력한 값이 없다."""
        for char in "+/=.~:":
            with self.subTest(char=char):
                value = f"abcd{char}1234efgh"
                reason = self.problem(value)
                self.assertEqual(reason, ALNUM_REASON)
                self.assertNotIn(value, reason)

    def test_alnum_rejects_quotes_brackets_symbols_korean_and_other_scripts(self):
        """따옴표·괄호·기호·한글·일본어·악센트 글자가 섞이면 거절한다."""
        for char in ('"', "'", "`", "(", ")", "[", "]", "{", "}", "<", ">", ",", ";", "!", "@", "#", "$", "%", "^", "&", "*", "|", chr(0xAC00), chr(0x3042), "é"):
            with self.subTest(char=char):
                self.assertEqual(self.problem(f"abcd{char}1234efgh"), ALNUM_REASON)

    def test_alnum_rejects_whitespace_and_invisible_characters_anywhere(self):
        """공백·탭·줄바꿈·줄 끝 문자·안 보이는 글자(너비 0 공백·방향 바꿈·한글 채움·BOM·소프트 하이픈)는 앞·가운데·뒤 어디에 있어도 같은 이유로 거절한다."""
        hidden = (" ", "\t", "\n", "\r", chr(0x00A0), chr(0x200B), chr(0x202E), chr(0x2066), chr(0x3164), chr(0xFEFF), chr(0x00AD))
        for char in hidden:
            for value in (f"abcd{char}1234efgh", f"{char}abcd1234efgh", f"abcd1234efgh{char}"):
                with self.subTest(code=ord(char), shown=value.index(char)):
                    reason = self.problem(value)
                    self.assertEqual(reason, HIDDEN_REASON)
                    self.assertNotIn(value, reason)

    def test_the_default_charset_still_accepts_the_wider_symbols_and_names_them(self):
        """기본 글자 종류는 그대로다 — `+ / = . ~ :` 를 받고 거절 이유가 그 글자들을 말한다(다른 용도는 영향이 없다)."""
        for char in "+/=.~:":
            with self.subTest(char=char):
                self.assertEqual(self.problem(f"abcd{char}1234efgh", charset=""), "")
                self.assertEqual(shape.value_problem(f"abcd{char}1234efgh", min_len=8, max_len=128), "")
        self.assertEqual(self.problem('abcd"1234efgh', charset=""), DEFAULT_REASON)
        self.assertEqual(shape.value_problem('abcd"1234efgh', min_len=8, max_len=128), DEFAULT_REASON)


class CheckFieldsTest(Base):
    def test_a_secret_with_a_dot_is_refused_naming_the_field_but_not_the_value(self):
        """Client Secret 에 `.` 가 있으면 '칸 이름과 이유'만 알리고 입력한 값(앞부분·끝 4자 포함)은 어느 오류 표면에도 없다."""
        spec = c.PURPOSES[HUB]
        bad = "hubsecret.dotted" + TAIL
        error = ss.code_of(c.check_fields, spec, {"client_id": "hubid1234567", "client_secret": bad})
        self.assertEqual((error.code, error.slots["항목"], error.slots["이유"]), ("KEY_INVALID_SHAPE", "클라이언트 시크릿", ALNUM_REASON))
        for text in surfaces(error):
            for probe in (bad, bad[:8], TAIL, "hubsecret"):
                self.assertNotIn(probe, text)
        refused = ss.code_of(c.add_entry, self.ctx, HUB, name="기본", fields={"client_id": "hubid1234567", "client_secret": bad})
        self.assertEqual(refused.code, "KEY_INVALID_SHAPE")
        self.assertEqual(self.store.list_refs(), [])
        self.assertIsNone(self.file_bytes_or_none())

    def file_bytes_or_none(self):
        path = self.ctx.workspace.connections_path
        return path.read_bytes() if path.exists() else None

    def test_a_short_client_id_is_refused_first_and_the_length_limits_are_exact(self):
        """Client ID 가 7자면 칸 이름 'Client ID' 와 '너무 짧습니다(최소 8자)' 로 거절하고(두 칸이 다 틀려도 앞 칸부터), 128자는 되고 129자는 길다."""
        spec = c.PURPOSES[HUB]
        good = "hubsecret1Zk3x" + TAIL
        error = ss.code_of(c.check_fields, spec, {"client_id": "abc1234", "client_secret": "x" * 200})
        self.assertEqual((error.slots["항목"], error.slots["이유"]), ("클라이언트 ID", "너무 짧습니다(최소 8자)"))
        self.assertIsNone(c.check_fields(spec, {"client_id": "a1" * 64, "client_secret": "b2" * 64}))
        error = ss.code_of(c.check_fields, spec, {"client_id": "hubid1234567", "client_secret": "b2" * 64 + "c"})
        self.assertEqual((error.slots["항목"], error.slots["이유"]), ("클라이언트 시크릿", "너무 깁니다(최대 128자)"))
        error = ss.code_of(c.check_fields, spec, {"client_id": "a1" * 64 + "b", "client_secret": good})
        self.assertEqual((error.slots["항목"], error.slots["이유"]), ("클라이언트 ID", "너무 깁니다(최대 128자)"))

    def test_the_field_names_must_match_the_purpose(self):
        """칸 이름이 빠지거나 낯설면 거절하고 이 용도의 칸 이름(client_id, client_secret)을 알린다."""
        spec = c.PURPOSES[HUB]
        error = ss.code_of(c.check_fields, spec, {"client_id": "hubid1234567"})
        self.assertEqual(error.code, "KEY_INVALID_SHAPE")
        self.assertIn("client_secret", error.slots["이유"])
        error = ss.code_of(c.check_fields, spec, {"client_id": "hubid1234567", "client_secret": "hubsecret1Zk3x", "extra": "x"})
        self.assertEqual(error.code, "KEY_INVALID_SHAPE")

    def test_the_legacy_purpose_keeps_the_wide_charset_while_the_hub_does_not(self):
        """옛 용도는 넓은 글자(`.` `+`)를 그대로 받고 NAVER API HUB 는 거절한다 — 글자 종류가 용도마다 따로다."""
        wide = {"client_id": "abcd+1234ef", "client_secret": "abc.defghij"}
        self.assertIsNone(c.check_fields(c.PURPOSES[OLD], wide))
        self.assertEqual(ss.code_of(c.check_fields, c.PURPOSES[HUB], wide).code, "KEY_INVALID_SHAPE")

    def test_a_good_value_is_stored_in_the_keystore_only_and_never_in_the_file(self):
        """정상 값은 보관소에만 있고 연결 설정 파일에는 값도 끝 4자도 없다(Client ID 도 해시 묶음 이름만)."""
        fields = hub_fields("a")
        result = c.add_entry(self.ctx, HUB, name="기본", fields=fields, project="앱")
        text = self.ctx.workspace.connections_path.read_text(encoding="utf-8")
        for probe in (fields["client_secret"], TAIL, fields["client_id"]):
            self.assertNotIn(probe, text)
        self.assertEqual(result.entry.bucket, "id-" + shape.short_digest(fields["client_id"]))
        self.assertEqual(self.store.get(result.entry.ref).to_dict(), fields)


# ---- 5) 명령줄·표시 ----------------------------------------------------------------------------------------------------------------
class CliHubTest(Base):
    def traffic(self):
        """키를 시험 성공으로 표시한 뒤 실제 호출 흐름(잡기·알리기) 세 번 — 성공 둘, 429 하나."""
        entry = self.add_hub("a").entry
        c.mark_check(self.ctx, entry.entry_id, "ok")
        guard = q.QuotaGuard(self.ctx, lock_wait=0)
        for outcome, status in (("ok", 200), ("ok", 200), ("rate_limited", 429)):
            lease = guard.acquire(HUB, priority=q.NEW, kind="search_trend", condition={"keywords": ["가", "나"], "period": "month"})
            self.assertIsInstance(lease, q.Lease, lease)
            guard.report(lease, outcome, status=status)
        return entry

    def test_purposes_shows_limits_stages_and_the_single_key_rule(self):
        """`keys purposes` 가 NAVER API HUB 의 한도(하루·이번 달·콘솔 월 한도)·단계표(경계 21,000/24,000/27,000)·키 1개 규칙·전환 없음을 쉬운 한국어로 보이고 마지막 줄에 예외를 알린다."""
        code, out, err, _ = self.run_keys("purposes")
        self.assertEqual((code, err), (0, ""))
        block = out[out.index("[naver_apihub]"):out.index("[naver_searchad]")]
        for text in ("하루 100회", "이번 달 27,000회", "서비스 콘솔 월 한도 30,000회", "한도 단계(이번 달 시도 수 기준):", "70%(21,000회)를 넘으면", "80%(24,000회)를 넘으면", "90%(27,000회)를 넘으면",
                     "키를 1개만 둡니다", "어떤 오류에도 다른 키로 자동 전환하지 않음", "아직 실제 호출 코드가 없어"):
            self.assertIn(text, block)
        self.assertEqual(out.rstrip().splitlines()[-1], "용도마다 키 항목은 3개까지입니다(예외: NAVER API HUB 검색어 트렌드 1개).")
        for word in WORDS:
            self.assertNotIn(word, out)

    def test_purposes_json_adds_the_extra_keys_only_for_the_hub(self):
        """`--json` 용도 사전은 NAVER API HUB 에만 `max_entries`·`console_limit`·`stages` 가 더해지고 다른 용도의 사전 모양은 그대로다."""
        code, out, err, _ = self.run_keys("purposes", json_mode=True)
        self.assertEqual((code, err), (0, ""))
        purposes = {item["purpose"]: item for item in json.loads(out)["data"]["purposes"]}
        self.assertEqual(list(purposes), SIX)
        hub = purposes[HUB]
        self.assertEqual(hub["max_entries"], 1)
        self.assertEqual([(item["name"], item["masked"], item["min_len"], item["max_len"]) for item in hub["fields"]], [("client_id", False, 8, 128), ("client_secret", True, 8, 128)])
        provider = hub["providers"][0]
        self.assertEqual((provider["rotation"], provider["default_tier"], provider["tiers"], provider["console_limit"]), ("never", "default", ["default"], 30000))
        self.assertEqual(provider["limits"], "하루 100회 · 이번 달 27,000회(서비스 콘솔 월 한도 30,000회)")
        self.assertEqual([(item["name"], item["percent"], item["above"], item["denies"]) for item in provider["stages"]],
                         [("notice", 70, 21000, []), ("limited", 80, 24000, ["bulk_refresh"]), ("closed", 90, 27000, list(PRIORITIES))])
        for stage in provider["stages"]:
            self.assertEqual(set(stage), {"name", "percent", "above", "text", "denies"})
            self.assertTrue(stage["text"])
        for key, item in purposes.items():
            if key == HUB:
                continue
            with self.subTest(purpose=key):
                self.assertEqual(set(item), {"purpose", "label", "summary", "takes_keys", "implemented", "works_without_key", "client_scope", "fields", "providers", "fallback_providers", "note"})
                for other in item["providers"]:
                    self.assertEqual(set(other), {"provider", "label", "rotation", "limits", "default_tier", "tiers"})

    def test_usage_with_the_purpose_as_a_word_or_as_an_option_is_the_same(self):
        """`keys usage 용도` 와 `keys usage --purpose 용도`(둘을 같이 적어도 같은 값이면)는 같은 출력이고 그 용도만 보인다."""
        self.add_hub("a")
        c.add_entry(self.ctx, "image_provider", name="기본", fields={"access_key": "imgkeyA0" + "Q" * 20})
        for json_mode in (False, True):
            with self.subTest(json=json_mode):
                first = self.run_keys("usage", HUB, json_mode=json_mode)
                second = self.run_keys("usage", "--purpose", HUB, json_mode=json_mode)
                third = self.run_keys("usage", HUB, "--purpose", HUB, json_mode=json_mode)
                self.assertEqual(first[0], 0)
                self.assertEqual(first[:3], second[:3])
                self.assertEqual(first[:3], third[:3])
                self.assertIn(HUB_LABEL if not json_mode else HUB, first[1])
                self.assertNotIn("이미지 공급자" if not json_mode else "image_provider", first[1])

    def test_two_different_purposes_are_a_usage_error(self):
        """용도를 서로 다르게 둘 적으면 사용법 오류(종료 코드 2)이고 아무 출력도 없다."""
        code, out, err, _ = self.run_keys("usage", HUB, "--purpose", "image_provider")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("용도를 서로 다르게 두 번 적었습니다", err)

    def test_an_invalid_purpose_word_is_a_usage_error_that_echoes_nothing_typed(self):
        """모르는 용도를 위치로 적어도(옵션 옆이든 `=` 로 붙이든) 사용법 오류이고 친 글자가 화면에 되풀이되지 않는다."""
        typed = "zzqq9988xx"
        for argv in (("usage", typed), ("usage", typed, "--purpose", HUB), ("usage", f"--purpose={typed}")):
            with self.subTest(argv=argv):
                code, out, err, _ = self.run_keys(*argv)
                self.assertEqual((code, out), (2, ""))
                for window in windows(typed):
                    self.assertNotIn(window, out + err)

    def test_usage_without_a_key_says_so_and_has_the_limits_in_json(self):
        """키가 없으면 '키가 없습니다' 만 말하고(호출 중지 줄 없음), `--json` 에는 한도(100·27,000·30,000)가 있고 멈춘 것이 아니다."""
        code, out, err, _ = self.run_keys("usage", HUB)
        self.assertEqual((code, err), (0, ""))
        self.assertIn(f"{HUB_LABEL} — 연결 안 됨", out)
        self.assertIn("키가 없습니다", out)
        self.assertNotIn("호출 중지", out)
        code, out, err, _ = self.run_keys("usage", HUB, json_mode=True)
        view = json.loads(out)["data"]["usage"][0]
        self.assertEqual((view["entries"], view["status"]), (0, "not_connected"))
        ledger = view["ledger"]
        self.assertEqual((ledger["stopped"], ledger["stage"], ledger["day_limit"], ledger["month_limit"], ledger["console_limit"]), (False, "ok", 100, 27000, 30000))

    def test_usage_with_an_unproven_key_shows_zeroes_and_stops_with_the_fixed_sentence(self):
        """시험 성공 기록이 없는 키는 오늘·이번 달 시도/성공 0, 내부·콘솔 한도, 마지막 성공/오류 없음, 그리고 고정 문구와 쉬운 사유로 '호출 중지' 를 보인다."""
        self.add_hub("a")
        code, out, err, _ = self.run_keys("usage", HUB)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            f"{HUB_LABEL} — 연결 확인 필요",
            "  오늘 시도 0회 · 성공 0회 / 내부 한도 100회",
            "  이번 달 시도 0회 · 성공 0회 / 내부 한도 27,000회(서비스 콘솔 월 한도 30,000회 — 마지막 안전장치)",
            "  마지막 성공 호출: 없음",
            "  마지막 오류: 없음",
            "  호출 중지: " + STOP_TEXT,
            "    사유: 인증 상태가 확실하지 않습니다 — 연결 시험에 성공한 기록이 있어야 새 호출을 합니다",
        ])

    def test_usage_after_a_successful_check_says_the_calls_are_not_stopped(self):
        """시험에 성공한 키는 '호출 중지: 아니요' 이고 고정 문구·사유 줄이 없다."""
        entry = self.add_hub("a").entry
        c.mark_check(self.ctx, entry.entry_id, "ok")
        code, out, err, _ = self.run_keys("usage", HUB)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("호출 중지: 아니요(지금은 새 조회를 할 수 있습니다)", out)
        self.assertNotIn(STOP_TEXT, out)
        self.assertNotIn("사유:", out)

    def test_usage_after_real_traffic_shows_attempts_and_successes_and_the_last_error_in_korean(self):
        """호출 흐름(성공 둘·429 하나)이 지나면 오늘·이번 달 모두 시도 3·성공 2, 마지막 성공 시각, '한도 초과 응답, 상태 429' 마지막 오류가 한국어로 보이고 영문 코드는 어디에도 없다. 429 직후에는 잠시 쉬는 중으로 멈춘다."""
        self.traffic()
        code, out, err, _ = self.run_keys("usage", HUB)
        self.assertEqual((code, err), (0, ""))
        for text in ("오늘 시도 3회 · 성공 2회 / 내부 한도 100회", "이번 달 시도 3회 · 성공 2회 / 내부 한도 27,000회", "마지막 성공 호출: 2026-11-02 10:30", "마지막 오류: 2026-11-02 10:30 — 한도 초과 응답, 상태 429",
                     "호출 중지: " + STOP_TEXT, "사유: 한도 초과 응답을 받아 잠시 쉬는 중입니다"):
            self.assertIn(text, out)
        for word in WORDS:
            self.assertNotIn(word, out)
        self.clock.advance(seconds=10)
        code, out, err, _ = self.run_keys("usage", HUB)
        self.assertIn("호출 중지: 아니요", out)
        self.assertNotIn(STOP_TEXT, out)

    def test_usage_json_carries_the_ledger_and_the_attempt_and_success_columns(self):
        """`--json` 사용량은 `ledger` 값(시도·성공·한도·마지막 오류)과 창마다 `attempts`·`successes` 를 담는다 — 하루 창과 월 창의 이름·구간 글자도."""
        self.traffic()
        self.clock.advance(seconds=10)
        code, out, err, _ = self.run_keys("usage", HUB, json_mode=True)
        view = json.loads(out)["data"]["usage"][0]
        ledger = view["ledger"]
        self.assertEqual((ledger["day_attempts"], ledger["day_successes"], ledger["month_attempts"], ledger["month_successes"]), (3, 2, 3, 2))
        self.assertEqual((ledger["day_limit"], ledger["month_limit"], ledger["console_limit"], ledger["stage"], ledger["stopped"]), (100, 27000, 30000, "ok", False))
        self.assertEqual(ledger["last_error"], {"at": STAMP, "outcome": "rate_limited", "status": 429})
        self.assertEqual(ledger["last_success"], STAMP)
        self.assertEqual([(row["window"], row["span"], row["used"], row["attempts"], row["successes"], row["limit"]) for row in view["rows"]],
                         [("day", "하루", 3, 3, 2, 100), ("month", "이번 달", 3, 3, 2, 27000)])

    def test_policy_shows_the_single_key_rule_the_stage_table_and_the_current_usage(self):
        """`keys policy naver_apihub` 는 키 하나·전환 없음 문장, 단계표, '지금 사용량:' 과 사용량 줄을 보인다(키가 없으면 멈춘 것이 아니다)."""
        code, out, err, _ = self.run_keys("policy", HUB)
        self.assertEqual((code, err), (0, ""))
        for text in (f"지금 정책({HUB_LABEL})", "키는 하나만 쓰고 어떤 오류(429 포함)에도 다른 키로 넘어가지 않습니다", "한도 단계(서비스 콘솔 월 한도 30,000회 기준):", "70%(21,000회)를 넘으면",
                     "80%(24,000회)를 넘으면", "90%(27,000회)를 넘으면", "전환은 하지 않습니다", "지금 사용량:", "오늘 시도 0회 · 성공 0회 / 내부 한도 100회", "호출 중지: 아니요"):
            self.assertIn(text, out)
        self.assertNotIn(STOP_TEXT, out)

    def test_policy_while_stopped_shows_the_fixed_sentence_and_json_has_the_ledger(self):
        """멈춘 동안(시험 성공 기록 없음)의 `keys policy` 는 고정 문구와 사유를 보이고 `--json` 에 `ledger` 가 있다."""
        self.add_hub("a")
        code, out, err, _ = self.run_keys("policy", HUB)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("호출 중지: " + STOP_TEXT, out)
        self.assertIn("사유: 인증 상태가 확실하지 않습니다", out)
        for word in WORDS:
            self.assertNotIn(word, out)
        code, out, err, _ = self.run_keys("policy", HUB, json_mode=True)
        data = json.loads(out)["data"]
        self.assertEqual(set(data), {"purpose", "policy", "ledger"})
        self.assertEqual((data["ledger"]["stopped"], data["ledger"]["stop_code"], data["ledger"]["stop_text"]), (True, "auth_unclear", STOP_TEXT))

    def test_policy_of_another_purpose_is_unchanged(self):
        """다른 용도의 `keys policy` 는 지금까지의 네 줄 그대로이고 사용량 줄·`ledger` 칸이 없다."""
        code, out, err, _ = self.run_keys("policy", "image_provider")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            "지금 정책(이미지 공급자): 허용된 다음 키로 전환(한도·일시 오류일 때만)",
            "  한도 등급: 기본",
            "  Unsplash: 어떤 오류에도 다른 키로 자동 전환하지 않습니다(키가 여러 개여도 개발용·운영용 구분이나 직접 고른 전환에만 씁니다).",
            "  전환은 한도(429·기간 한도)·일시 오류(500·502·503·504)·시간 초과일 때만, 허용된 다음 키(같은 용도·제공자의 사용·예비 항목)로, 한 요청에 한 바퀴를 넘지 않게 합니다. 인증·잘못된 요청·정책 차단은 숨기지 않고 안내만 합니다.",
        ])
        code, out, err, _ = self.run_keys("policy", "image_provider", json_mode=True)
        self.assertEqual(set(json.loads(out)["data"]), {"purpose", "policy"})

    def test_usage_of_another_purpose_keeps_its_format_and_has_no_ledger_keys(self):
        """다른 용도의 사용량 줄(`기본(Unsplash) 최근 60분 1 / 50 (2%)`)과 `--json` 의 칸이 지금까지 그대로고, 시도/성공 칸은 장부 용도의 창에만 있다."""
        self.add_hub("a")
        c.add_entry(self.ctx, "image_provider", name="기본", fields={"access_key": "imgkeyA0" + "Q" * 20})
        self.assertIsInstance(q.QuotaGuard(self.ctx, lock_wait=0).acquire("image_provider"), q.Lease)
        code, out, err, _ = self.run_keys("usage", "image_provider")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("  기본(Unsplash) 최근 60분 1 / 50 (2%)", out.splitlines())
        code, out, err, _ = self.run_keys("usage", json_mode=True)
        views = {item["purpose"]: item for item in json.loads(out)["data"]["usage"]}
        image = views["image_provider"]
        self.assertEqual(set(image), {"purpose", "label", "rows", "saving_mode", "blocked", "resume_at", "resume_text", "notice", "entries", "switches", "status", "status_text"})
        self.assertEqual([set(row) for row in image["rows"]], [{"entry", "provider", "window", "used", "limit", "near_limit", "span"}])
        self.assertEqual((image["rows"][0]["window"], image["rows"][0]["span"], image["rows"][0]["used"]), ("hour", "최근 60분", 1))
        self.assertIn("ledger", views[HUB])
        self.assertEqual([row["span"] for row in views[HUB]["rows"]], ["하루", "이번 달"])
        self.assertEqual([("attempts" in row, "successes" in row) for row in views[HUB]["rows"]], [(True, True), (True, True)])

    def test_the_human_output_of_the_hub_commands_has_no_english_codes(self):
        """NAVER API HUB 의 사람이 보는 출력(용도·목록·사용량·정책)에는 영문 상태·결과 코드가 없다."""
        self.traffic()
        for argv in (("usage", HUB), ("usage",), ("policy", HUB), ("list",), ("purposes",)):
            with self.subTest(argv=argv):
                code, out, err, _ = self.run_keys(*argv)
                self.assertEqual(code, 0, err)
                for word in WORDS:
                    self.assertNotIn(word, out + err)


class ReadOnlyHubTest(unittest.TestCase):
    def test_hub_read_commands_create_nothing_in_an_empty_data_folder(self):
        """NAVER API HUB 를 보는 읽기 명령은 아직 없는 데이터 폴더를 만들지 않고 오류 없이 끝난다(사람 글·`--json` 모두)."""
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "아직 없는 폴더"
            for argv in (("purposes",), ("list",), ("usage", HUB), ("usage", "--purpose", HUB), ("policy", HUB), ("usage",), ("list", "--purpose", HUB)):
                for json_flag in ((), ("--json",)):
                    with self.subTest(argv=argv, json=json_flag):
                        out, err = io.StringIO(), io.StringIO()
                        code = cli.main([*json_flag, "keys", *argv, "--data-dir", str(data)], out=out, err=err, env={}, stdin=FakeStdin())
                        self.assertEqual((code, err.getvalue()), (0, ""), out.getvalue())
                        self.assertFalse(data.exists(), "읽기 명령은 데이터 폴더를 만들지 않는다")

    def test_hub_read_commands_do_not_open_the_keystore_while_there_is_no_entry(self):
        """항목이 하나도 없으면 NAVER API HUB 읽기 명령도 키 보관소를 열지 않는다."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            ctx = ss.make_ctx(tmp, clock=ss.Clock())
            opened = []
            real = ctx.get_keystore

            def counting():
                opened.append(1)
                return real()

            ctx.get_keystore = counting
            for argv in (("list",), ("usage", HUB), ("policy", HUB), ("usage",), ("purposes",)):
                for json_flag in ((), ("--json",)):
                    with self.subTest(argv=argv, json=json_flag):
                        out, err = io.StringIO(), io.StringIO()
                        self.assertEqual(cli.main([*json_flag, "keys", *argv], out=out, err=err, ctx=ctx, stdin=FakeStdin()), 0, err.getvalue())
            self.assertEqual(opened, [])


# ---- 6) 장부 줄 ---------------------------------------------------------------------------------------------------------------------
def ledger_view(**changes):
    """`format.keys_ledger_lines` 가 읽는 값만 가진 가짜 사용량 보기."""
    base = dict(day_attempts=0, day_successes=0, month_attempts=0, month_successes=0, day_limit=100, month_limit=27000, console_limit=30000, last_success="", last_error=None, stage="ok",
                stage_text="", stopped=False, stop_code="", stop_cause="", stop_text="")
    base.update(changes)
    return types.SimpleNamespace(ledger=q.LedgerUsage(**base))


class LedgerLinesTest(unittest.TestCase):
    OUTCOME_TEXT = {"rate_limited": "한도 초과 응답", "quota_exhausted": "기간 한도 소진 응답", "transient_error": "서버 일시 오류", "timeout": "시간 초과", "auth_failed": "인증 실패",
                    "bad_request": "요청 형식 오류", "policy_blocked": "정책 차단", "content_blocked": "콘텐츠 차단", "other_error": "그 밖의 오류"}

    def error_line(self, outcome, status=0):
        lines = fmt.keys_ledger_lines(ledger_view(last_error={"at": STAMP, "outcome": outcome, "status": status}))
        return next(line for line in lines if line.startswith("  마지막 오류:"))

    def test_every_outcome_has_its_korean_wording_and_never_its_english_code(self):
        """결과 종류 아홉 가지(성공 제외)마다 정해진 한국어 문구가 한 줄에 나오고 영문 코드는 나오지 않는다 — 새 결과 종류가 생기면 이 표도 고쳐야 한다."""
        self.assertEqual(set(self.OUTCOME_TEXT), set(q.OUTCOMES) - {q.OK})
        for outcome, text in self.OUTCOME_TEXT.items():
            with self.subTest(outcome=outcome):
                line = self.error_line(outcome)
                self.assertEqual(line, f"  마지막 오류: 2026-11-02 10:30 — {text}")
                self.assertNotIn(outcome, line)
        self.assertEqual(self.error_line("something_new"), "  마지막 오류: 2026-11-02 10:30 — 그 밖의 오류")

    def test_the_status_number_is_shown_only_when_it_is_not_zero(self):
        """HTTP 상태 번호는 0(없음)이 아닐 때만 `, 상태 429` 로 붙는다."""
        self.assertEqual(self.error_line("rate_limited", 429), "  마지막 오류: 2026-11-02 10:30 — 한도 초과 응답, 상태 429")
        self.assertEqual(self.error_line("timeout", 0), "  마지막 오류: 2026-11-02 10:30 — 시간 초과")
        self.assertNotIn("상태", self.error_line("timeout", 0))

    def test_the_stage_line_appears_only_when_the_stage_is_not_ok(self):
        """한도 단계 줄은 단계가 `ok` 가 아닐 때만 나온다(안내·제한·중지 모두) — 단계 글이 있어도 `ok` 면 숨는다."""
        for stage, shown in (("ok", False), ("notice", True), ("limited", True), ("closed", True)):
            with self.subTest(stage=stage):
                lines = fmt.keys_ledger_lines(ledger_view(stage=stage, stage_text="단계 안내 글"))
                self.assertEqual("  한도 단계: 단계 안내 글" in lines, shown)

    def test_a_stopped_view_shows_the_fixed_sentence_and_the_cause_and_a_running_one_says_no(self):
        """멈췄으면 '호출 중지: 고정 문구'와 '사유: …' 두 줄, 아니면 '호출 중지: 아니요(…)' 한 줄이다."""
        stopped = fmt.keys_ledger_lines(ledger_view(stopped=True, stop_code="clock", stop_cause="시계가 되돌아갔습니다", stop_text=STOP_TEXT))
        self.assertEqual(stopped[-2:], ["  호출 중지: " + STOP_TEXT, "    사유: 시계가 되돌아갔습니다"])
        running = fmt.keys_ledger_lines(ledger_view())
        self.assertEqual(running[-1], "  호출 중지: 아니요(지금은 새 조회를 할 수 있습니다)")
        self.assertFalse([line for line in running if "사유" in line])

    def test_the_numbers_use_thousand_separators_and_the_last_success_and_error_default_to_none(self):
        """숫자는 천 단위 쉼표로 보이고 마지막 성공·오류가 없으면 '없음', 있으면 한국 시간으로 보인다."""
        lines = fmt.keys_ledger_lines(ledger_view(day_attempts=7, day_successes=5, month_attempts=12345, month_successes=12000))
        self.assertEqual(lines[:4], ["  오늘 시도 7회 · 성공 5회 / 내부 한도 100회",
                                     "  이번 달 시도 12,345회 · 성공 12,000회 / 내부 한도 27,000회(서비스 콘솔 월 한도 30,000회 — 마지막 안전장치)", "  마지막 성공 호출: 없음", "  마지막 오류: 없음"])
        self.assertIn("  마지막 성공 호출: 2026-11-02 10:30", fmt.keys_ledger_lines(ledger_view(last_success=STAMP)))

    def test_the_policy_lines_add_the_usage_block_only_for_a_ledger_view(self):
        """정책 줄은 장부 보기가 있을 때만 '지금 사용량:' 블록이 붙고, 키를 하나만 두는 용도는 전환 없음 문장을 쓴다."""
        spec, policy = c.PURPOSES[HUB], c.Policy()
        without = fmt.keys_policy_lines(spec, policy, changed=False)
        self.assertNotIn("지금 사용량:", without)
        self.assertTrue([line for line in without if "키는 하나만 쓰고 어떤 오류(429 포함)에도 다른 키로 넘어가지 않습니다" in line])
        with_view = fmt.keys_policy_lines(spec, policy, changed=False, view=ledger_view())
        self.assertEqual(with_view[:len(without)], without)
        self.assertEqual(with_view[len(without)], "지금 사용량:")
        self.assertEqual(with_view[len(without) + 1:], fmt.keys_ledger_lines(ledger_view()))
        self.assertTrue(fmt.keys_policy_lines(c.PURPOSES["image_provider"], policy, changed=False, view=types.SimpleNamespace(ledger=None))[-1].startswith("  전환은 한도(429·기간 한도)"))


class SingleKeyWordingTest(Base):
    """키를 하나만 두는 용도의 안내가 거짓이 되지 않게 — 정책 첫 줄과 깨진 사용량 파일 안내."""

    def test_the_policy_first_line_of_a_single_key_purpose_never_promises_a_switch(self):
        """`keys policy naver_apihub` 의 첫 줄은 '허용된 다음 키로 전환' 이 아니라 '키가 하나뿐이라 넘어가지 않음' 이다(다른 용도의 첫 줄은 그대로)."""
        code, out, err, _ = self.run_keys("policy", HUB)
        self.assertEqual((code, err), (0, ""))
        first = out.splitlines()[0]
        self.assertEqual(first, f"지금 정책({HUB_LABEL}): 키가 하나뿐이라 다른 키로 넘어가지 않음(절약·중단만)")
        self.assertNotIn("허용된 다음 키로 전환", first)
        code, out, err, _ = self.run_keys("policy", HUB, "--on-limit", "save")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[0], f"정책을 바꿨습니다({HUB_LABEL}): 키가 하나뿐이라 다른 키로 넘어가지 않음(절약·중단만)")
        code, out, err, _ = self.run_keys("policy", "image_provider")
        self.assertEqual(out.splitlines()[0], "지금 정책(이미지 공급자): 허용된 다음 키로 전환(한도·일시 오류일 때만)")

    def test_a_broken_usage_file_notice_is_true_for_each_kind_of_purpose(self):
        """사용량 파일이 깨졌을 때 안내: 다른 용도는 '절반을 썼다고 가정', NAVER API HUB 는 '절반으로 가정하지 않고 멈춘다'(거짓 안내를 하지 않는다)."""
        self.add_hub("a")
        c.add_entry(self.ctx, "image_provider", name="기본", fields={"access_key": "imgkeyA0" + "Q" * 20})
        self.ctx.workspace.quota_path.write_text("이것은 JSON 이 아니다", encoding="utf-8")
        views = {view.purpose: view for view in q.QuotaGuard(self.ctx, lock_wait=0).usage()}
        self.assertEqual(views[HUB].notice, q.LOST_NOTICE)
        self.assertIn("절반으로 가정하지 않고", views[HUB].notice)
        self.assertNotIn("절반을 이미 쓴 것으로 가정했습니다", views[HUB].notice)
        self.assertIn("오늘 한도의 절반을 이미 쓴 것으로 가정했습니다", views["image_provider"].notice)
        self.assertEqual(views["ai_assist"].notice, views["image_provider"].notice)
        code, out, err, _ = self.run_keys("usage", HUB)
        self.assertEqual((code, err), (0, ""))
        self.assertIn(f"주의: {q.LOST_NOTICE}", out)
        self.assertIn("호출 중지: " + STOP_TEXT, out)


if __name__ == "__main__":
    unittest.main()
