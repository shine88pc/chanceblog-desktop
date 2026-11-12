"""연결 설정 시험(`service/connections.py`) — 용도별 키 항목이 보관소에만 비밀을 두고, 어떤 오류·파일·표시에도 입력한 값이 새지 않는지 본다. 네트워크·진짜 자격 증명 관리자 없이 돈다(보관소는 가짜).

지키는 것:
  1) 레지스트리(현재 용도 6개와 맨 뒤의 옛 용도 `naver_openapi` 1개·칸 이름·이미지 공급자는 Unsplash 가 첫 제공자이고 Secret Key 칸이 없다·한도 정책 값·상태 문구 5종·항목 최대 3개 — NAVER API HUB 만 1개)가 정해 둔 값 그대로다.
     여러 항목·하루 창·돌려쓰기 같은 '일반 동작'은 실제 레지스트리에서 더할 수 있는 용도(이미지 공급자 등)나 `ss.generic_registry()`(옛 첫 용도를 시험용으로 되살린 것)로 시험한다.
  2) `add_entry`: 값은 보관소에, 메타데이터만 `connections.json` 에(키 값·끝 4자가 파일에 없다). 둘째 키부터 약관 확인, 같은 이름·같은 값 거절, 한도 묶음 이름, 안내 문구.
  3) **어떤 거절 문구에도 입력 원문이 없다** — 가짜 키 모양 7종 × 이웃 글자(한글·괄호·따옴표·줄바꿈 …) × 입력 자리 8곳을 전수로 부르고 오류의 모든 표면(`str`·`log_line`·`rendered`·`detail`·`repr`·`slots`)을 본다.
  4) 실패 처리(보관소 오류·메타데이터 쓰기 실패의 롤백)와 `connections.json` 의 모양 검사(깨진 파일은 건드리지 않고 `CONNECTIONS_FILE_INVALID`).
  5) 목록은 읽기만 하고 끝 4자는 16자 이상일 때만 보이며, 상태 5종은 '시험 성공 기록 + 유효 기간 + 실제 호출 코드가 있을 때'만 연결됨이다.
  6) 항목 고르기(순번·번호 앞부분·겹침)와 지우기(확인·번호 앞 8자·보관소 먼저), 상태·순서·정책·확인 결과 바꾸기, 연결 시험(최소 호출·60초 규칙), 잠금, 진단 요약과 데이터 폴더 스윕.
가짜 키 모양은 실행할 때 조각을 이어 붙여 만든다(저장소의 시험이 `.py` 안의 키 모양 문자열을 막는다). 보이지 않는 글자는 `chr()` 로 만든다.
"""
import contextlib
import copy
import dataclasses
import inspect
import json
import sys
import tempfile
import time
import types
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import keystore as ks  # noqa: E402
from chanceblog_desktop.security import shape  # noqa: E402
from chanceblog_desktop.service import connections as c  # noqa: E402

TAIL = "wQ8z"                                                     # 가짜 값의 끝 4자 — 다른 글에 우연히 들어 있지 않도록 특이하게
STAMP = "2026-11-02T01:30:12Z"                                    # `ss.NOW` 의 `ctx.stamp()`
ENTRY_KEYS = {"entry_id", "purpose", "provider", "name", "project", "order", "state", "created_at", "checked_at", "last_ok_at", "check_result", "bucket", "terms_ack_at"}
SAME_BUCKET_NOTE = "같은 앱(소속 프로젝트)의 키라서 한도가 늘지 않습니다 — 한도에 걸렸을 때 이 키로는 넘어가지 않습니다."
NOT_READY = "시험 기능 준비 중 — 이 용도는 아직 실제 호출을 하지 않습니다"
LIMIT_SECONDS = 2.5
ID1, ID2, ID3 = "abcdef01" * 4, "abcdef02" * 4, "abcdef03" * 4
HIDDEN_CHARS = tuple(chr(code) for code in (0x20, 0x09, 0x0A, 0x0D, 0xA0, 0x200B, 0x202E, 0x2066, 0x3164, 0xFEFF, 0xAD, 0x00, 0x7F, 0x2028, 0x2800, 0xE000, 0x0378))


def key_shapes():
    """비밀 모양 표본(이름 → 글) — 모두 끝 4자가 `TAIL`. 조각을 이어 붙여 저장소에는 키 문자열이 없다."""
    return {
        "google": "AI" + "za" + "A" * 35 + TAIL,
        "github": "gh" + "p_" + "B" * 36 + TAIL,
        "sk": "s" + "k-" + "C" * 40 + TAIL,
        "aws": "AK" + "IA" + "D" * 16 + TAIL,
        "slack": "xo" + "xb-" + "1" * 12 + TAIL,
        "jwt": "ey" + "J" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12 + TAIL,
        "plain": "Rk" + "7" * 30 + TAIL,
    }


NEIGHBORS = (("", ""), ("키는", "입니다"), ("(", ")"), ('"', '"'), ("'", "'"), ("\n", "\n"), ("값=", ""), ("", "\n다음 줄"), ("한글", ""), ("", "한글"), ("[", "]"), ("`", "`"), ("_", "_"))


def values(purpose, seed="a"):
    """용도의 모든 칸에 넣을 가짜 값 — seed 가 다르면 값이 다르고 칸마다 다르다. 모든 칸이 최소 길이를 넘고 끝 4자는 `TAIL`."""
    found = {}
    for index, item in enumerate(c.PURPOSES[purpose].fields):
        body = (f"{seed}{index}Zk3") * 40
        found[item.name] = body[: item.min_len + 3] + TAIL
    return found


def key_ids(*ids):
    it = iter(ids)
    return lambda: next(it)


class FlakyStore(ks.MemoryStore):
    """실패를 흉내 내는 가짜 보관소 — 플래그를 켜면 그 일이 KEY_STORE_UNAVAILABLE 로 실패한다."""

    def __init__(self):
        super().__init__()
        self.fail_write = self.fail_read = self.fail_delete = False

    def _problem(self):
        return AppError("KEY_STORE_UNAVAILABLE", detail="시험용 실패")

    def _write(self, ref, raw):
        if self.fail_write:
            raise self._problem()
        super()._write(ref, raw)

    def _read(self, ref):
        if self.fail_read:
            raise self._problem()
        return super()._read(ref)

    def _delete(self, ref):
        if self.fail_delete:
            raise self._problem()
        return super()._delete(ref)


def surfaces(error):
    """오류가 사용자·로그에 내보내는 모든 글."""
    shown = error.rendered()
    return [str(error), error.log_line(), shown.message, shown.action, shown.retry_text, str(error.detail), repr(error), repr(error.slots), " ".join(str(v) for v in error.slots.values()), repr(error.args)]


def all_text(ctx):
    """데이터 폴더 안 모든 파일의 글(없는 폴더는 빈 글)."""
    root = Path(ctx.workspace.root)
    return {path.relative_to(root).as_posix(): path.read_bytes().decode("utf-8", "replace") for path in sorted(root.rglob("*")) if path.is_file()}


def implemented_registry():
    registry = dict(c.PURPOSES)
    registry["image_provider"] = dataclasses.replace(c.PURPOSES["image_provider"], implemented=True)
    return registry


class Base(unittest.TestCase):
    OLD_KEY_LIMITS = False         # 의도적 갱신(P4f, D-250): 참이면 이 시험 동안만 모든 제공자의 상한을 P4f 이전처럼 3 으로 되돌린다 — 실제 표의 값(Unsplash 1 …)은 `test_service_key_limits` 가 못박는다

    def setUp(self):
        if self.OLD_KEY_LIMITS:
            patcher = ss.old_key_limits()
            patcher.start()
            self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.clock = ss.Clock()
        self.ctx = ss.make_ctx(self.tmp, clock=self.clock)
        self.store = self.ctx.keystore
        self.cases = 0

    def new_ctx(self, repo=""):
        """따로 쓰는 새 Context(새 데이터 폴더·새 가짜 보관소)."""
        self.cases += 1
        return ss.make_ctx(self.tmp / f"case{self.cases}", clock=ss.Clock(), repo=repo)

    def add(self, purpose="image_provider", name="기본", seed="a", ctx=None, **kwargs):
        kwargs.setdefault("terms_ack", True)
        return c.add_entry(ctx or self.ctx, purpose, name=name, fields=values(purpose, seed), **kwargs)

    def file_path(self, ctx=None):
        return (ctx or self.ctx).workspace.connections_path

    def file_bytes(self, ctx=None):
        path = self.file_path(ctx)
        return path.read_bytes() if path.exists() else None

    def read_file(self, ctx=None):
        return json.loads(self.file_path(ctx).read_text(encoding="utf-8"))

    def assert_no_leak(self, error, *secrets, label=""):
        probes = set()
        for secret in secrets:
            probes.add(secret)
            if len(secret) >= 12:
                probes.update({secret[:8], secret[-4:]})
        for text in surfaces(error):
            for probe in probes:
                self.assertNotIn(probe, text, f"{label}: {probe!r} 가 오류 표면에 있다")

    def assert_rejected(self, code, *args, ctx=None, **kwargs):
        """add_entry 가 이 코드로 거절되고 보관소·파일이 그대로다 → 오류."""
        ctx = ctx or self.ctx
        refs, before = ctx.keystore.list_refs(), self.file_bytes(ctx)
        error = ss.code_of(c.add_entry, ctx, *args, **kwargs)
        self.assertEqual(error.code, code, f"{error.slots} {error.detail}")
        self.assertEqual(ctx.keystore.list_refs(), refs)
        self.assertEqual(self.file_bytes(ctx), before)
        return error


class RegistryTest(Base):
    def test_the_six_purposes_in_order_with_their_field_names(self):
        expected = {
            "naver_apihub": ["client_id", "client_secret"], "naver_searchad": ["customer_id", "access_license", "secret_key"], "image_provider": ["access_key"],
            "ai_assist": ["key"], "blogger": ["client_id", "client_secret", "refresh_token"], "github_repo": [],
            "naver_openapi": ["client_id", "client_secret"],                 # 옛 용도 — 맨 뒤에 정의만 남아 있다(옛 파일의 항목을 읽고 보여 주려고, 새 항목은 받지 않는다)
        }
        self.assertEqual(list(c.PURPOSES), list(expected))
        for purpose, names in expected.items():
            with self.subTest(purpose=purpose):
                self.assertEqual([item.name for item in c.PURPOSES[purpose].fields], names)
        self.assertEqual(c.listed_purposes(c.Data()), tuple(expected)[:6])      # 화면에 보이는 용도는 현재 용도 여섯 개(옛 용도는 그 항목이 남아 있을 때만 보인다)

    def test_which_fields_are_secret_and_the_first_secret_field_is_the_one_whose_tail_is_shown(self):
        secret = {"naver_apihub": {"client_id": False, "client_secret": True}, "naver_searchad": {"customer_id": False, "access_license": True, "secret_key": True},
                  "image_provider": {"access_key": True}, "ai_assist": {"key": True}, "blogger": {"client_id": False, "client_secret": True, "refresh_token": True}, "github_repo": {},
                  "naver_openapi": {"client_id": False, "client_secret": True}}
        for purpose, flags in secret.items():
            with self.subTest(purpose=purpose):
                self.assertEqual({item.name: item.secret for item in c.PURPOSES[purpose].fields}, flags)
        primary = {"naver_apihub": "client_secret", "naver_searchad": "access_license", "image_provider": "access_key", "ai_assist": "key", "blogger": "client_secret", "github_repo": "",
                   "naver_openapi": "client_secret"}
        self.assertEqual({purpose: spec.primary_secret() for purpose, spec in c.PURPOSES.items()}, primary)

    def test_the_image_provider_takes_one_access_key_and_never_a_second_secret_key(self):
        spec = c.PURPOSES["image_provider"]
        self.assertEqual([item.name for item in spec.fields], ["access_key"])
        self.assertEqual(spec.fields[0].label, "Access Key")
        self.assertFalse(any("secret" in item.name for item in spec.fields))
        error = ss.code_of(c.add_entry, self.ctx, "image_provider", name="기본", fields={**values("image_provider"), "secret_key": "x" * 20})
        self.assertEqual(error.code, "KEY_INVALID_SHAPE")

    def test_unsplash_is_the_first_provider_and_never_rotates_with_the_documented_limits(self):
        spec = c.PURPOSES["image_provider"]
        first = spec.providers[0]
        self.assertEqual((first.key, first.label, first.rotation, first.default_tier), ("unsplash", "Unsplash", "never", "demo"))
        self.assertEqual(first.tier_names(), ("demo", "production"))
        self.assertEqual(first.windows("demo"), (c.Window("hour", "sliding", 50, 60, True),))
        self.assertEqual(first.windows("production"), (c.Window("hour", "sliding", 1000, 60, True),))
        self.assertEqual(first.windows(""), first.windows("demo"))
        self.assertEqual(first.windows("no-such-tier"), ())
        self.assertEqual([item.key for item in spec.providers], ["unsplash", "pexels", "pixabay"])
        for other in spec.providers[1:]:
            with self.subTest(provider=other.key):
                self.assertEqual((other.rotation, other.windows()), ("limited", ()))
        self.assertIs(spec.provider(""), first)                     # 제공자를 안 고르면 첫 제공자
        self.assertIsNone(spec.provider("nope"))

    def test_naver_has_a_daily_window_and_the_other_single_provider_purposes_have_none_known(self):
        naver = c.PURPOSES["naver_apihub"].providers[0]                          # 첫 용도는 NAVER API HUB — 하루 100회와 이번 달 27,000회 창이 있고 돌려쓰기는 없다
        self.assertEqual((naver.key, naver.rotation, naver.windows()), ("", "never", (c.Window("day", "day", 100), c.Window("month", "month", 27000))))
        self.assertEqual(c.PURPOSES["naver_apihub"].max_entries, 1)
        old = c.PURPOSES["naver_openapi"].providers[0]                            # 옛 용도의 정의는 그대로 남아 있다(옛 파일을 읽고 보여 주려고)
        self.assertEqual((old.key, old.rotation, old.windows()), ("", "limited", (c.Window("day", "day", 25000),)))
        self.assertEqual(ss.generic_registry()["naver_openapi"].providers[0].windows(), (c.Window("day", "day", 25000),))      # 시험용으로 되살린 옛 첫 용도도 같은 하루 창이다
        for purpose in ("naver_searchad", "ai_assist", "blogger"):
            with self.subTest(purpose=purpose):
                self.assertEqual(c.PURPOSES[purpose].providers[0].windows(), ())

    def test_fallback_providers_are_empty_by_default_and_every_purpose_works_without_a_key(self):
        for purpose, spec in c.PURPOSES.items():
            with self.subTest(purpose=purpose):
                self.assertEqual(spec.fallback_providers, ())
                self.assertIs(spec.works_without_key, True)
                self.assertIn("이 PC 전용", spec.client_scope)
                self.assertTrue(spec.label and spec.summary or purpose == "github_repo")
        self.assertIs(c.PURPOSES["ai_assist"].optional, True)

    def test_identity_fields_decide_the_limit_bucket_only_for_the_purposes_that_have_an_app_id(self):
        self.assertEqual({purpose: spec.identity_field for purpose, spec in c.PURPOSES.items()},
                         {"naver_apihub": "client_id", "naver_searchad": "customer_id", "image_provider": "", "ai_assist": "", "blogger": "client_id", "github_repo": "", "naver_openapi": "client_id"})

    def test_status_and_state_words_are_five_and_three_and_only_in_these_tables(self):
        self.assertEqual(c.STATUS_TEXT, {"connected": "연결됨", "needs_check": "연결 확인 필요", "rate_limited": "요청 한도 도달", "auth_error": "인증 정보 오류", "not_connected": "연결 안 됨"})
        self.assertEqual(c.STATE_TEXT, {"active": "사용", "standby": "예비", "off": "꺼짐"})
        self.assertEqual(c.STATES, ("active", "standby", "off"))
        self.assertEqual((c.CONNECTED, c.NEEDS_CHECK, c.RATE_LIMITED, c.AUTH_ERROR, c.NOT_CONNECTED), ("connected", "needs_check", "rate_limited", "auth_error", "not_connected"))

    def test_the_constants_the_rules_depend_on_are_pinned(self):
        self.assertEqual(c.MAX_ENTRIES_PER_PURPOSE, 3)
        self.assertEqual((c.CHECK_VALID_HOURS, c.TEST_MIN_INTERVAL), (24, 60))
        self.assertEqual((c.DELETE_PREFIX, c.MIN_PREFIX, c.MAX_ORDINAL_DIGITS), (8, 4, 2))
        self.assertEqual((c.MAX_NAME_CHARS, c.MAX_PROJECT_CHARS), (40, 60))
        self.assertEqual((c.SCHEMA, c.FILE_NAME), (1, "connections.json"))
        self.assertEqual((c.ON_SAVE, c.ON_FAILOVER, c.ROTATION_NEVER, c.ROTATION_LIMITED), ("save", "failover", "never", "limited"))
        self.assertEqual(c.Policy().on_limit, "failover")                     # 기본 정책은 허용된 다음 키로 전환(제공자가 never 이면 어차피 전환하지 않는다)

    def test_the_terms_notice_in_the_code_is_the_one_the_troubleshooting_table_shows(self):
        doc = (ss.ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
        row = next(line for line in doc.splitlines() if line.startswith("| `KEY_FAILOVER_TERMS_REQUIRED`"))
        self.assertIn(c.TERMS_NOTICE, row)
        for phrase in ("약관", "본인 소유의 정당한 키", "이 프로그램에 없습니다"):
            self.assertIn(phrase, c.TERMS_NOTICE)

    def test_the_github_repository_purpose_takes_no_key_and_says_why_without_any_value(self):
        spec = c.PURPOSES["github_repo"]
        self.assertEqual((spec.takes_keys, spec.fields), (False, ()))
        secret = key_shapes()["plain"]
        error = self.assert_rejected("KEY_INVALID_SHAPE", "github_repo", name="기본", fields={"key": secret})
        self.assertIn("Git", error.rendered().message)
        self.assert_no_leak(error, secret)


class AddEntryTest(Base):
    OLD_KEY_LIMITS = True          # 의도적 갱신(P4f, D-250): 항목이 여럿인 상태를 만든다

    def test_the_first_key_puts_the_value_in_the_keystore_and_only_metadata_in_the_file(self):
        fields = values("image_provider")
        result = c.add_entry(self.ctx, "image_provider", name="기본", fields=fields, project="내 앱", new_id=key_ids(ID1))
        entry = result.entry
        self.assertEqual(entry.ref, "image_provider:" + ID1)
        self.assertEqual(self.store.get(entry.ref).to_dict(), fields)
        self.assertEqual(self.store.list_refs(), ["image_provider:" + ID1])
        text = self.file_path().read_text(encoding="utf-8")
        for secret in fields.values():
            self.assertNotIn(secret, text)
            self.assertNotIn(secret[-4:], text)
        data = json.loads(text)
        self.assertEqual(set(data), {"schema", "entries", "policies"})
        self.assertEqual((data["schema"], data["policies"], len(data["entries"])), (1, {}, 1))
        saved = data["entries"][0]
        self.assertEqual(set(saved), ENTRY_KEYS)
        self.assertEqual(saved,
                         {"entry_id": ID1, "purpose": "image_provider", "provider": "unsplash", "name": "기본", "project": "내 앱", "order": 1, "state": "active", "created_at": STAMP,
                          "checked_at": "", "last_ok_at": "", "check_result": "", "bucket": "p-내 앱", "terms_ack_at": ""})
        self.assertEqual(result.notes, ())
        self.assertNotIn("fields", repr(result).lower().replace("terms", ""))
        self.assertFalse(self.file_path().with_name("connections.json.bak").exists())           # 처음 쓸 때는 직전 내용이 없다

    def test_a_second_key_needs_the_terms_confirmation_and_records_when_it_was_given(self):
        self.add(new_id=key_ids(ID1))
        self.clock.advance(minutes=5)
        result = c.add_entry(self.ctx, "image_provider", name="예비", fields=values("image_provider", "b"), project="다른 앱", terms_ack=True, new_id=key_ids(ID2))
        self.assertEqual((result.entry.order, result.entry.terms_ack_at, result.entry.created_at), (2, "2026-11-02T01:35:12Z", "2026-11-02T01:35:12Z"))
        self.assertEqual(result.notes, (c.TERMS_NOTICE,))                          # 다른 프로젝트라 '한도가 늘지 않는다' 안내는 없다
        first = next(item for item in c.load(self.ctx).entries if item.entry_id == ID1)
        self.assertEqual(first.terms_ack_at, "")                                  # 첫 키에는 확인이 없다
        third = c.add_entry(self.ctx, "image_provider", name="셋째", fields=values("image_provider", "c"), project="셋째 앱", terms_ack=True, new_id=key_ids(ID3))
        self.assertEqual((third.entry.order, third.notes), (3, (c.TERMS_NOTICE,)))

    def test_the_first_key_never_records_a_terms_confirmation_even_if_one_is_passed(self):
        result = c.add_entry(self.ctx, "image_provider", name="기본", fields=values("image_provider"), terms_ack=True)
        self.assertEqual((result.entry.terms_ack_at, result.notes), ("", ()))

    def test_a_second_key_without_the_confirmation_is_refused_and_nothing_is_stored(self):
        self.add()
        error = self.assert_rejected("KEY_FAILOVER_TERMS_REQUIRED", "image_provider", name="예비", fields=values("image_provider", "b"))
        self.assertEqual(error.rendered().message, "「이미지 공급자」에 둘째 키를 더하려면 약관 확인이 필요해 아직 저장하지 않았습니다.")
        self.assertIn("--i-understand-terms", error.rendered().action)
        self.assertIn(c.TERMS_NOTICE, error.rendered().action)
        for flag in (False, None, 0, ""):
            with self.subTest(flag=flag):
                self.assert_rejected("KEY_FAILOVER_TERMS_REQUIRED", "image_provider", name="예비", fields=values("image_provider", "b"), terms_ack=flag)

    def test_the_same_project_says_the_limit_does_not_grow_and_a_different_provider_does_not(self):
        self.add(project="내 앱")
        same = c.add_entry(self.ctx, "image_provider", name="예비", fields=values("image_provider", "b"), project="내 앱", terms_ack=True)
        self.assertEqual(same.notes, (SAME_BUCKET_NOTE, c.TERMS_NOTICE))
        other_provider = c.add_entry(self.ctx, "image_provider", name="핵시", fields=values("image_provider", "c"), project="내 앱", provider="pexels", terms_ack=True)
        self.assertEqual(other_provider.notes, ())                  # 의도적 갱신(P4f, D-250): 둘째 키 약관 안내는 '같은 서비스(제공자)의 둘째 키' 에만 — 다른 제공자(Pexels)의 첫 키에는 없다(운영자 정책 표)
        self.assertEqual(other_provider.entry.terms_ack_at, "")
        self.assertEqual((other_provider.entry.provider, other_provider.entry.bucket), ("pexels", "p-내 앱"))

    def test_the_bucket_of_an_image_key_is_the_project_name_folded_and_unspecified_ones_share_one_bucket(self):
        cases = (("My App", "p-my app"), ("", "p-(미지정)"), ("내 앱", "p-내 앱"), ("ABC", "p-abc"))
        for project, expected in cases:
            with self.subTest(project=project):
                ctx = self.new_ctx()
                self.assertEqual(self.add(ctx=ctx, project=project).entry.bucket, expected)
        ctx = self.new_ctx()
        self.add(ctx=ctx, project="")
        again = self.add(ctx=ctx, name="예비", seed="b", project="")
        self.assertEqual(again.notes[0], SAME_BUCKET_NOTE)                         # 프로젝트를 안 적은 두 키는 한도를 함께 쓴다고 본다

    def test_a_naver_bucket_is_decided_by_the_client_id_not_by_the_project_and_never_holds_the_id(self):
        shared_id, other_id = "SharedClientId01", "OtherClientId002"
        registry = ss.generic_registry()                       # 항목이 여럿인 용도(옛 첫 용도를 시험용으로 되살린 것) — 실제 레지스트리의 NAVER API HUB 는 키를 하나만 두고 옛 용도는 새 항목을 받지 않는다
        first = c.add_entry(self.ctx, "naver_openapi", name="기본", fields={"client_id": shared_id, "client_secret": "s1" * 5}, project="앱 하나", registry=registry)
        second = c.add_entry(self.ctx, "naver_openapi", name="예비", fields={"client_id": shared_id, "client_secret": "s2" * 5}, project="앱 둘", terms_ack=True, registry=registry)
        third = c.add_entry(self.ctx, "naver_openapi", name="셋째", fields={"client_id": other_id, "client_secret": "s3" * 5}, project="앱 하나", terms_ack=True, registry=registry)
        self.assertEqual(first.entry.bucket, second.entry.bucket)
        self.assertNotEqual(first.entry.bucket, third.entry.bucket)
        for entry in (first.entry, second.entry, third.entry):
            self.assertTrue(entry.bucket.startswith("id-"))
            self.assertNotIn(shared_id, entry.bucket)
            self.assertNotIn(other_id, entry.bucket)
        self.assertEqual(second.notes, (SAME_BUCKET_NOTE, c.TERMS_NOTICE))
        self.assertEqual(third.notes, (c.TERMS_NOTICE,))
        self.assertNotIn(shared_id, self.file_path().read_text(encoding="utf-8"))

    def test_defaults_state_provider_and_random_ids(self):
        first = self.add()
        self.assertRegex(first.entry.entry_id, r"^[0-9a-f]{32}$")
        self.assertEqual((first.entry.provider, first.entry.state), ("unsplash", "active"))
        second = self.add(name="예비", seed="b", state="standby")
        self.assertEqual(second.entry.state, "standby")
        self.assertNotEqual(first.entry.entry_id, second.entry.entry_id)
        naver = self.add("naver_apihub")
        self.assertEqual(naver.entry.provider, "")
        pexels = self.add(name="핵시", seed="c", provider="pexels")
        self.assertEqual(pexels.entry.provider, "pexels")

    def test_the_third_and_last_slot_then_a_fourth_key_is_refused_with_the_limit_message(self):
        for index, name in enumerate(("기본", "예비", "셋째"), start=1):
            self.add(name=name, seed=str(index))
        error = self.assert_rejected("KEY_ENTRY_LIMIT", "image_provider", name="넷째", fields=values("image_provider", "d"), terms_ack=True)
        self.assertEqual(error.rendered().message, "「이미지 공급자」에는 키 항목을 「3」개까지만 둘 수 있습니다.")
        self.assertEqual(len(c.load(self.ctx).entries), 3)
        other = self.add("naver_apihub")                                         # 한도는 용도마다 따로다
        self.assertEqual(other.entry.order, 1)

    def test_a_rejected_fourth_key_does_not_even_ask_for_the_terms(self):
        for index in range(3):
            self.add(name=f"항목{index}", seed=str(index))
        self.assert_rejected("KEY_ENTRY_LIMIT", "image_provider", name="넷째", fields=values("image_provider", "d"))

    def test_the_same_name_and_the_same_value_are_duplicates_within_a_purpose_only(self):
        self.add(name="기본", seed="a")
        error = self.assert_rejected("KEY_DUPLICATE", "image_provider", name="기본", fields=values("image_provider", "b"), terms_ack=True)
        self.assertEqual(error.slots["항목"], "같은 이름")
        error = self.assert_rejected("KEY_DUPLICATE", "image_provider", name="다른 이름", fields=values("image_provider", "a"), terms_ack=True)
        self.assertEqual(error.slots["항목"], "같은 값")
        self.assertIn("기본", error.slots["이유"])                                  # 이미 있는 항목의 이름(비밀이 아닌 이름표)은 알려 준다
        ok = c.add_entry(self.ctx, "ai_assist", name="기본", fields={"key": values("image_provider", "a")["access_key"]})
        self.assertEqual(ok.entry.purpose, "ai_assist")                           # 용도가 다르면 같은 값·같은 이름도 괜찮다

    def test_a_duplicate_is_found_by_reading_the_stored_value_and_a_different_value_is_not_one(self):
        self.add(name="기본", seed="a")
        second = self.add(name="예비", seed="b")                                    # 값이 다르면 중복이 아니다
        self.assertEqual(second.entry.name, "예비")
        error = self.assert_rejected("KEY_DUPLICATE", "image_provider", name="셋째", fields=values("image_provider", "b"), terms_ack=True)
        self.assertEqual(error.slots["항목"], "같은 값")
        self.assertIn("예비", error.slots["이유"])

    def test_a_stored_value_that_is_gone_is_not_a_duplicate(self):
        first = self.add(name="기본", seed="a")
        self.store.delete(first.entry.ref)                                          # 보관소의 값이 밖에서 지워졌다(항목은 '연결 확인 필요' 로 남는다)
        again = self.add(name="다시", seed="a")
        self.assertEqual(again.entry.name, "다시")

    def test_when_the_keystore_cannot_be_read_the_add_stops_with_the_keystore_error_and_writes_nothing(self):
        store = FlakyStore()
        first = c.add_entry(self.ctx, "image_provider", name="기본", fields=values("image_provider", "a"), keystore=store)
        before = (self.file_bytes(), store.list_refs())
        store.fail_read = True
        for seed in ("a", "b"):                                                     # 같은 값이든 다른 값이든 — 중복인지 알 수 없으니 확인 없이 저장하지 않는다
            with self.subTest(seed=seed):
                error = ss.code_of(c.add_entry, self.ctx, "image_provider", name="예비" + seed, fields=values("image_provider", seed), terms_ack=True, keystore=store)
                self.assertEqual(error.code, "KEY_STORE_UNAVAILABLE")               # 중복이라고 잘못 말하지 않고 보관소 오류를 그대로 알린다
                self.assertEqual((self.file_bytes(), store.list_refs()), before)
        self.assertEqual(len(c.load(self.ctx).entries), 1)
        self.assertEqual(first.entry.ref, store.list_refs()[0])

    def test_the_file_holds_nothing_derived_from_a_secret_value_not_even_a_short_hash(self):
        import base64
        import hashlib
        secrets = []
        for purpose in ("naver_apihub", "naver_searchad", "image_provider", "ai_assist", "blogger"):
            self.add(purpose, name="기본", seed="q", project="앱")
            spec = c.PURPOSES[purpose]
            secrets += [(purpose, item.name, values(purpose, "q")[item.name]) for item in spec.fields if item.secret]
        text = self.file_path().read_text(encoding="utf-8")
        self.assertGreaterEqual(len(secrets), 7)
        checked = 0
        for purpose, field, value in secrets:
            raw = value.encode("utf-8")
            body = json.dumps({name: values(purpose, "q")[name] for name in sorted(values(purpose, "q"))}, ensure_ascii=False, separators=(",", ":"))
            candidates = [shape.short_digest(value), shape.short_digest(body)]
            for name in ("md5", "sha1", "sha224", "sha256", "sha384", "sha512", "sha3_256", "blake2b", "blake2s"):
                for data in (raw, body.encode("utf-8"), (purpose + value).encode("utf-8"), (purpose + "\0" + body).encode("utf-8"), ("chanceblog-desktop:fingerprint:1\0" + purpose + "\0" + body).encode("utf-8")):
                    digest = hashlib.new(name, data).digest()
                    candidates += [digest.hex(), base64.b64encode(digest).decode("ascii"), base64.urlsafe_b64encode(digest).decode("ascii")]
            for mark in candidates:
                for size in (8, 12):
                    if len(mark) >= size:
                        checked += 1
                        self.assertNotIn(mark[:size], text, f"{purpose}.{field}: 값에서 만든 표시가 파일에 있다")
                        self.assertNotIn(mark[:size].upper(), text)
        self.assertGreater(checked, 1000)
        for needle in (TAIL, "fingerprint"):
            self.assertNotIn(needle, text)

    def test_the_limit_bucket_is_only_ever_made_from_a_plain_field_never_from_a_secret_one(self):
        for key, spec in c.PURPOSES.items():
            with self.subTest(purpose=key):
                if spec.identity_field:
                    self.assertFalse(spec.field(spec.identity_field).secret, "한도 묶음 이름은 비밀 칸에서 만들지 않는다 — 약한 값은 해시만으로 알아낼 수 있다")
                else:
                    self.assertEqual(c._bucket_of(spec, values(key) if spec.takes_keys else {}, "프로젝트"), "p-프로젝트")


class RejectionTest(Base):
    def one(self, ctx=None, **overrides):
        """image_provider 한 항목을 더해 본다 — 칸·이름·프로젝트·제공자·상태를 바꿔서."""
        ctx = ctx or self.new_ctx()
        arguments = {"name": "기본", "fields": values("image_provider"), "project": "", "provider": "", "state": "active"}
        arguments.update(overrides)
        return ctx, arguments

    def reject(self, code, **overrides):
        ctx, arguments = self.one(**overrides)
        return self.assert_rejected(code, "image_provider", ctx=ctx, **arguments)

    def test_names_of_every_bad_kind_are_refused_and_good_ones_pass(self):
        bad = {"비어 있음": "", "41자": "가" * 41, "앞 공백": " 기본", "뒤 공백": "기본 ", "연속 공백": "기  본", "줄바꿈": "기\n본", "탭": "기\t본", "키 모양": key_shapes()["plain"], "비문자열": None, "숫자": 5}
        for label, name in bad.items():
            with self.subTest(name=label):
                error = self.reject("KEY_INVALID_SHAPE", name=name)
                self.assertEqual(error.slots["항목"], "이름")
        self.assertEqual(self.reject("KEY_INVALID_SHAPE", name="").rendered().message, "「이름」 값이 올바르지 않아 저장하지 않았습니다: 「비어 있습니다」.")
        for good in ("기본", "예비 키", "회사 계정", "My project 2", "naver-app", "가" * 40):
            with self.subTest(good=good):
                ctx, arguments = self.one(name=good)
                self.assertEqual(c.add_entry(ctx, "image_provider", **arguments).entry.name, good)

    def test_projects_of_every_bad_kind_are_refused_and_the_sixty_char_limit_is_exact(self):
        for label, project in {"61자": "가" * 61, "줄바꿈": "앱\n둘", "키 모양": key_shapes()["sk"], "앞 공백": " 앱", "비문자열": 7}.items():
            with self.subTest(project=label):
                self.assertEqual(self.reject("KEY_INVALID_SHAPE", project=project).slots["항목"], "소속 프로젝트")
        ctx, arguments = self.one(project="가" * 60)
        self.assertEqual(c.add_entry(ctx, "image_provider", **arguments).entry.project, "가" * 60)

    def test_a_name_or_a_project_written_as_a_labelled_value_is_refused_before_anything_is_written(self):
        """PCSEC1V: 이름·소속 프로젝트는 비밀이 아닌 칸이라 `connections.json` 에 평문으로 남는다 — `client_secret=값` 처럼 가리기 규칙이 가릴 글(운영자 이름 11개)은 쓰기 전에 거절한다. 위치(항목)만 알리고 값은 어디에도 없다."""
        value = "CANARY_" + "ALIAS" + "k3x9"                                       # 모양이 없는 가짜 값(조립)
        for label in ("Authorization: Bearer ", "api_key=", "apikey=", "serviceKey=", "access_token=", "refresh_token=", "client_secret=", "password=", "Cookie: sid=", "Set-Cookie: sid=", "X-API-Key: "):
            for where, slot in (("name", "이름"), ("project", "소속 프로젝트")):
                with self.subTest(label=label, where=where):
                    error = self.reject("KEY_INVALID_SHAPE", **{where: label + value})            # 보관소·파일이 그대로임은 `assert_rejected` 가 본다
                    self.assertEqual(error.slots["항목"], slot)
                    self.assertIn("키나 토큰처럼 보이는", error.slots["이유"])
                    self.assert_no_leak(error, value, label=label)
        for fine in ("예비 키", "회사 계정", "My project 2", "naver-app", "token bucket", "api key 발급용", "secret santa"):                 # 평범한 이름은 그대로 저장된다
            with self.subTest(fine=fine):
                ctx, arguments = self.one(name=fine, project=fine)
                self.assertEqual(c.add_entry(ctx, "image_provider", **arguments).entry.name, fine)

    def test_a_project_whose_folded_name_is_longer_than_the_project_still_saves_a_readable_file(self):
        """**알려진 빈틈(소스 수정 대기)** — `ß` 는 소문자로 접으면 `ss` 두 글자라 60자 프로젝트의 묶음 이름(`p-` + 접은 글)이 파일 검사 한도(`.{1,80}`)를 넘고,
        `add_entry` 가 성공한 바로 다음 `load` 가 CONNECTIONS_FILE_INVALID 로 멈춘다(스스로 깨뜨린 파일). 묶음 이름을 80자 안으로 줄이게(또는 해시로) 고치면 이 시험이
        '예상 밖의 성공' 이 되니 그때 `@unittest.expectedFailure` 표시를 지운다."""
        ctx, arguments = self.one(project="ß" * 60)
        c.add_entry(ctx, "image_provider", **arguments)
        self.assertEqual(len(c.load(ctx).entries), 1)

    def test_values_are_refused_for_every_hidden_or_forbidden_character(self):
        base = values("image_provider")["access_key"]
        for char in HIDDEN_CHARS:
            for where, text in (("앞", char + base), ("가운데", base[:10] + char + base[10:]), ("뒤", base + char)):
                with self.subTest(char=hex(ord(char)), where=where):
                    error = self.reject("KEY_INVALID_SHAPE", fields={"access_key": text})
                    self.assertEqual(error.slots["항목"], "Access Key")
                    self.assertIn("공백·줄바꿈·눈에 안 보이는 글자", error.slots["이유"])
        for char in ('"', "'", "`", "(", ")", "[", "]", "{", "}", "<", ">", "\\", ",", ";", "|", "$", "%", "*", "?", "!", "@", "#", "&", "^", chr(0xAC00), chr(0xFF21)):
            with self.subTest(char=char):
                error = self.reject("KEY_INVALID_SHAPE", fields={"access_key": base[:10] + char + base[10:]})
                self.assertIn("영문·숫자와", error.slots["이유"])
        ok = self.new_ctx()
        allowed = "ab_-+/=.~:" + "Z" * 10
        self.assertEqual(c.add_entry(ok, "image_provider", name="기본", fields={"access_key": allowed}).entry.name, "기본")

    def test_the_length_limits_of_every_field_are_exact(self):
        registry = ss.generic_registry()                       # 현재 용도 6개 + 옛 첫 용도(`naver_openapi`)를 새 항목을 받는 시험용으로 되살린 것 — 옛 용도의 칸 길이도 그대로 지킨다
        self.assertEqual(list(registry), list(c.PURPOSES))
        for purpose, spec in registry.items():
            for item in spec.fields:
                for length, accepted in ((item.min_len - 1, False), (item.min_len, True), (item.max_len, True), (item.max_len + 1, False)):
                    with self.subTest(purpose=purpose, field=item.name, length=length):
                        ctx = self.new_ctx()
                        fields = {**values(purpose), item.name: "a" * length}
                        if accepted:
                            self.assertEqual(c.add_entry(ctx, purpose, name="기본", fields=fields, registry=registry).entry.purpose, purpose)
                        else:
                            error = self.assert_rejected("KEY_INVALID_SHAPE", purpose, ctx=ctx, name="기본", fields=fields, registry=registry)
                            self.assertEqual(error.slots["항목"], item.label)
                            self.assertIn("최소" if length < item.min_len else "최대", error.slots["이유"])

    def test_field_names_must_match_the_purpose_exactly(self):
        good = values("naver_apihub")
        cases = {"빠진 칸": {"client_id": good["client_id"]}, "모르는 칸": {**good, "extra": "x" * 10}, "다른 칸": {"client_id": good["client_id"], "other": good["client_secret"]}, "빈 dict": {}}
        for label, fields in cases.items():
            with self.subTest(case=label):
                ctx = self.new_ctx()
                error = self.assert_rejected("KEY_INVALID_SHAPE", "naver_apihub", ctx=ctx, name="기본", fields=fields)
                self.assertEqual(error.slots["항목"], "입력 칸")
                self.assertIn("client_id, client_secret", error.slots["이유"])
        error = self.assert_rejected("KEY_INVALID_SHAPE", "naver_apihub", name="기본", fields={"client_id": good["client_id"]})
        self.assertIn("빠진 칸이 있습니다: client_secret", error.slots["이유"])
        for label, fields in {"리스트": ["a"], "None": None, "글": "abc", "숫자 값": {"client_id": 5, "client_secret": 6}, "글 아닌 이름": {5: "x" * 10}}.items():
            with self.subTest(case=label):
                error = self.assert_rejected("KEY_INVALID_SHAPE", "naver_apihub", name="기본", fields=fields)
                self.assertEqual(error.slots["항목"], "입력")

    def test_unknown_purpose_provider_state_and_a_purpose_that_takes_no_key(self):
        error = ss.code_of(c.add_entry, self.ctx, "no_such_purpose", name="기본", fields=values("image_provider"))
        self.assertEqual((error.code, error.slots["항목"]), ("CONNECTION_NOT_FOUND", "용도 이름"))
        for purpose in (None, 5, ["image_provider"]):
            with self.subTest(purpose=purpose):
                self.assertEqual(ss.code_of(c.add_entry, self.ctx, purpose, name="기본", fields=values("image_provider")).code, "CONNECTION_NOT_FOUND")
        self.assertEqual(self.reject("KEY_INVALID_SHAPE", provider="nope").slots["항목"], "제공자")
        other = ss.code_of(c.add_entry, self.ctx, "naver_apihub", name="기본", fields=values("naver_apihub"), provider="unsplash")        # 다른 용도의 제공자 이름은 이 용도(제공자 하나)에서 거절
        self.assertEqual((other.code, other.slots["항목"]), ("KEY_INVALID_SHAPE", "제공자"))
        for state in ("예비", "ACTIVE", "", None, "on"):
            with self.subTest(state=state):
                self.assertEqual(self.reject("KEY_INVALID_SHAPE", state=state).slots["항목"], "상태")

    def test_a_whole_key_value_inside_the_name_or_the_project_is_refused(self):
        value = values("image_provider")["access_key"]
        for slot in ("name", "project"):
            with self.subTest(slot=slot):
                error = self.reject("KEY_INVALID_SHAPE", **{slot: "내것 " + value})
                self.assertEqual(error.slots["항목"], "이름")
                self.assertIn("키 값이", error.slots["이유"])
                self.assert_no_leak(error, value)

    def test_a_value_too_long_for_the_keystore_is_too_long_exactly_past_2560_bytes(self):
        registry = dict(c.PURPOSES)
        spec = c.PURPOSES["image_provider"]
        registry["image_provider"] = dataclasses.replace(spec, fields=(dataclasses.replace(spec.fields[0], max_len=5000),))
        # JSON `{"access_key":"` 15글자 + 값 + `"}` 2글자 → 값 1263자면 1280글자 = 정확히 2,560바이트(UTF-16)
        passing = c.add_entry(self.ctx, "image_provider", name="기본", fields={"access_key": "a" * 1263}, registry=registry)
        self.assertEqual(len(self.store.get(passing.entry.ref).reveal("access_key")), 1263)
        ctx = self.new_ctx()
        error = ss.code_of(c.add_entry, ctx, "image_provider", name="기본", fields={"access_key": "a" * 1264}, registry=registry)
        self.assertEqual(error.code, "KEY_TOO_LONG")
        self.assertIn("2,560바이트", error.rendered().message)
        self.assertNotIn("a" * 20, " ".join(surfaces(error)))
        self.assertEqual((ctx.keystore.list_refs(), self.file_bytes(ctx)), ([], None))

    def test_huge_inputs_are_refused_quickly(self):
        huge = "가" * 300_000
        for label, overrides in {"이름": {"name": huge}, "프로젝트": {"project": huge}, "값": {"fields": {"access_key": huge}}, "영문 값": {"fields": {"access_key": "a" * 300_000}}}.items():
            with self.subTest(slot=label):
                started = time.perf_counter()
                error = self.reject("KEY_INVALID_SHAPE", **overrides)
                self.assertLess(time.perf_counter() - started, LIMIT_SECONDS)
                self.assertNotIn("가가가가", " ".join(surfaces(error)))


class NoEchoTest(Base):
    SLOTS = ("secret_value", "plain_value", "name", "project", "provider", "purpose", "state", "unknown_field_name")
    PURPOSE = "naver_apihub"                       # 비밀 칸(client_secret)과 비밀이 아닌 칸(client_id)이 하나씩 있는 용도 — 실제 레지스트리의 첫 용도(글자 범위가 영문·숫자·`_ -` 뿐이라 `.` 이 든 값은 모양 검사에서 거절된다)

    def registry(self):
        return c.PURPOSES

    def call(self, ctx, slot, text):
        purpose, fields = self.PURPOSE, values(self.PURPOSE)
        arguments = {"name": "기본", "project": "", "provider": "", "state": "active"}
        if slot == "secret_value":
            fields["client_secret"] = text
        elif slot == "plain_value":
            fields["client_id"] = text
        elif slot == "unknown_field_name":
            fields[text] = "x" * 10
        elif slot == "purpose":
            purpose = text
        else:
            arguments[slot] = text
        return c.add_entry(ctx, purpose, fields=fields, registry=self.registry(), **arguments)

    def test_no_refusal_and_no_result_ever_contains_what_was_typed(self):
        for shape_name, secret in key_shapes().items():
            for before, after in NEIGHBORS:
                wrapped = before + secret + after
                for slot in self.SLOTS:
                    with self.subTest(shape=shape_name, neighbors=(before, after), slot=slot):
                        ctx = self.new_ctx()
                        try:
                            result = self.call(ctx, slot, wrapped)
                        except AppError as error:
                            self.assert_no_leak(error, secret, wrapped, label=slot)
                            self.assertEqual((ctx.keystore.list_refs(), self.file_bytes(ctx)), ([], None), "거절된 입력은 어디에도 남지 않는다")
                        else:
                            self.assertIn(slot, ("secret_value", "plain_value"), "이름·프로젝트·제공자·용도·상태 자리의 키 모양 글은 받지 않는다")
                            self.assertNotIn(secret, repr(result))
                            self.assertNotIn(TAIL, repr(result))
                            for path, text in all_text(ctx).items():
                                self.assertNotIn(secret, text, path)
                                self.assertNotIn(TAIL, text, path)

    def test_random_long_values_in_every_slot_are_not_echoed_either(self):
        import random
        rng = random.Random(11)
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-+/=.~:가나다()\"' \n\t"
        for index in range(60):
            text = "".join(rng.choice(alphabet) for _ in range(rng.choice((20, 64, 200, 900))))
            for slot in self.SLOTS:
                with self.subTest(index=index, slot=slot):
                    ctx = self.new_ctx()
                    try:
                        result = self.call(ctx, slot, text)
                    except AppError as error:
                        self.assert_no_leak(error, text, text.strip(), label=slot)
                    else:
                        if slot in ("name", "project"):
                            self.assertFalse(shape.looks_secret(text), "이름·프로젝트로는 키처럼 보이는 글을 받지 않는다")        # 이름표로 받아들인 글은 이름표라 화면에 보이는 것이 맞다
                        else:
                            self.assertNotIn(text, repr(result))

    def test_the_complete_sweep_after_a_normal_session_finds_no_value_in_any_file(self):
        fields = dict(values("image_provider"))
        c.add_entry(self.ctx, "image_provider", name="기본", fields=fields, project="내 앱")
        for path, text in all_text(self.ctx).items():
            for value in fields.values():
                self.assertNotIn(value, text, path)
                self.assertNotIn(TAIL, text, path)


class NoEchoGenericTest(NoEchoTest):
    """같은 전수 시험을 '일반 용도'로도 한다 — 옛 첫 용도(`naver_openapi`)를 새 항목을 받는 시험용으로 되살린 레지스트리(`ss.generic_registry()`)는 기본 글자 범위(`_ - + / = . ~ :` 포함)의 값도 받아들이므로
    '받아들인 값이 어느 파일에도 남지 않는다' 쪽도 옛 시험과 같게 지켜진다(NAVER API HUB 는 글자 범위가 좁아 그런 값을 모양 검사에서 거절한다)."""
    PURPOSE = "naver_openapi"

    def registry(self):
        return ss.generic_registry()


class FailureHandlingTest(Base):
    OLD_KEY_LIMITS = True          # 의도적 갱신(P4f, D-250): 항목이 여럿인 상태를 만든다

    def test_a_keystore_that_cannot_write_leaves_no_metadata_behind(self):
        store = FlakyStore()
        store.fail_write = True
        secret = values("image_provider")["access_key"]
        error = ss.code_of(c.add_entry, self.ctx, "image_provider", name="기본", fields=values("image_provider"), keystore=store)
        self.assertEqual(error.code, "KEY_STORE_UNAVAILABLE")
        self.assert_no_leak(error, secret)
        self.assertEqual((store.list_refs(), self.file_bytes()), ([], None))

    def test_a_metadata_write_failure_takes_the_value_out_of_the_keystore_again(self):
        broken = AppError("FILE_WRITE_FAILED", {"경로": "x"})
        with mock.patch.object(c, "write_json", side_effect=broken):
            error = ss.code_of(c.add_entry, self.ctx, "image_provider", name="기본", fields=values("image_provider"))
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertEqual((self.store.list_refs(), self.file_bytes()), ([], None))

    def test_when_even_the_rollback_fails_it_says_so_without_any_value(self):
        store = FlakyStore()
        secret = values("image_provider")["access_key"]

        def failing_write(path, data):
            store.fail_delete = True
            raise AppError("FILE_WRITE_FAILED", {"경로": "x"})

        with mock.patch.object(c, "write_json", side_effect=failing_write):
            error = ss.code_of(c.add_entry, self.ctx, "image_provider", name="기본", fields=values("image_provider"), keystore=store)
        self.assertEqual(error.code, "KEY_STORE_UNAVAILABLE")
        self.assertIn("지우지 못했다", error.detail)
        self.assert_no_leak(error, secret)
        self.assertEqual(len(store.list_refs()), 1)                              # 못 지운 값이 남았음을 숨기지 않는다 — 오류 세부가 알린다

    def test_a_failing_save_after_a_good_one_keeps_the_old_file_and_removes_only_the_new_value(self):
        self.add(new_id=key_ids(ID1))
        before = self.file_bytes()
        with mock.patch.object(c, "write_json", side_effect=AppError("DISK_FULL", {})):
            error = ss.code_of(c.add_entry, self.ctx, "image_provider", name="예비", fields=values("image_provider", "b"), terms_ack=True)
        self.assertEqual(error.code, "DISK_FULL")
        self.assertEqual(self.store.list_refs(), ["image_provider:" + ID1])
        self.assertEqual(self.file_bytes(), before)


def write_raw(ctx, payload):
    path = ctx.workspace.connections_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    elif isinstance(payload, str):
        path.write_text(payload, encoding="utf-8", newline="\n")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


class FileFormatTest(Base):
    OLD_KEY_LIMITS = True          # 의도적 갱신(P4f, D-250): 항목이 여럿인 상태를 만든다

    def setUp(self):
        super().setUp()
        self.add(name="기본", project="프로젝트마커", new_id=key_ids(ID1))
        self.add(name="예비", seed="b", project="프로젝트마커", new_id=key_ids(ID2))
        c.set_policy(self.ctx, "image_provider", on_limit="save")
        self.good = self.read_file()
        self.markers = [ID1, ID2, "프로젝트마커"]

    def invalid(self, payload, label=""):
        """이 내용의 파일을 읽으면 CONNECTIONS_FILE_INVALID — 파일은 그대로이고 문구에 파일 내용이 없다."""
        write_raw(self.ctx, payload)
        before = self.file_bytes()
        error = ss.code_of(c.load, self.ctx)
        self.assertEqual(error.code, "CONNECTIONS_FILE_INVALID", label)
        self.assertEqual(self.file_bytes(), before, label)
        self.assertEqual(error.rendered().message, "연결 설정 파일을 읽을 수 없습니다: 「connections.json」.")
        for text in surfaces(error):
            for marker in self.markers:
                self.assertNotIn(marker, text, label)
        return error

    def mutated(self, change):
        data = copy.deepcopy(self.good)
        change(data)
        return data

    def test_a_good_file_round_trips_and_the_backup_is_the_previous_good_content(self):
        loaded = c.load(self.ctx)
        self.assertEqual([item.entry_id for item in loaded.entries], [ID1, ID2])
        self.assertEqual(loaded.policy("image_provider").on_limit, "save")
        self.assertEqual(loaded.policy("naver_apihub"), c.Policy())                # 정하지 않은 용도는 기본 정책
        self.assertEqual(json.loads(self.file_path().with_name("connections.json.bak").read_text(encoding="utf-8"))["policies"], {})   # 정책을 정하기 직전의 내용
        c.save(self.ctx, loaded)
        self.assertEqual(json.loads(self.file_path().with_name("connections.json.bak").read_text(encoding="utf-8")), self.good)
        self.assertEqual(self.read_file(), self.good)

    def test_top_level_shapes(self):
        cases = {
            "schema 2": lambda g: g.__setitem__("schema", 2), "schema 글": lambda g: g.__setitem__("schema", "1"), "schema 참": lambda g: g.__setitem__("schema", True),
            "schema None": lambda g: g.__setitem__("schema", None), "낯선 최상위 칸": lambda g: g.__setitem__("extra", 1), "entries 없음": lambda g: g.pop("entries"),
            "policies 없음": lambda g: g.pop("policies"), "schema 없음": lambda g: g.pop("schema"), "entries 가 dict": lambda g: g.__setitem__("entries", {}),
            "policies 가 list": lambda g: g.__setitem__("policies", []),
        }
        for label, change in cases.items():
            with self.subTest(case=label):
                self.invalid(self.mutated(change), label)

    def test_not_json_or_not_an_object(self):
        for label, payload in {"JSON 아님": "{not json 프로젝트마커", "빈 파일": "", "list": "[]", "글": '"x"', "null": "null", "숫자": "5", "깨진 UTF-8": b"\xff\xfe\x00{", "BOM 만": b"\xef\xbb\xbf"}.items():
            with self.subTest(case=label):
                self.invalid(payload, label)

    def test_entry_shapes_missing_unknown_and_wrongly_typed_keys(self):
        self.invalid(self.mutated(lambda g: g["entries"].__setitem__(0, "항목")), "dict 아님")
        self.invalid(self.mutated(lambda g: g["entries"][0].__setitem__("extra", 1)), "낯선 항목 칸")
        for key in sorted(ENTRY_KEYS):
            with self.subTest(missing=key):
                self.invalid(self.mutated(lambda g, key=key: g["entries"][0].pop(key)), f"{key} 없음")
        for key in ("entry_id", "purpose", "provider", "name", "project", "state", "created_at", "checked_at", "last_ok_at", "check_result", "bucket", "terms_ack_at"):
            with self.subTest(wrong_type=key):
                self.invalid(self.mutated(lambda g, key=key: g["entries"][0].__setitem__(key, 5)), f"{key} 숫자")
        for label, value in {"참": True, "글": "1", "음수": -1, "1001": 1001, "실수": 1.5, "None": None}.items():
            with self.subTest(order=label):
                self.invalid(self.mutated(lambda g, value=value: g["entries"][0].__setitem__("order", value)), f"order {label}")

    def test_entry_values_that_are_not_allowed(self):
        cases = {
            "짧은 번호": ("entry_id", "abc"), "대문자 번호": ("entry_id", "A" * 32), "긴 번호": ("entry_id", "a" * 33), "16진 아님": ("entry_id", "g" * 32),
            "묶음 접두사": ("bucket", "x-abc"), "빈 묶음": ("bucket", "p-"), "긴 묶음": ("bucket", "id-" + "a" * 81), "접두사 없음": ("bucket", "abc"),
            "상태": ("state", "inactive"), "한글 상태": ("state", "사용"), "확인 결과": ("check_result", "maybe"),
            "만든 시각 빈 글": ("created_at", ""), "13월": ("created_at", "2026-13-01T00:00:00Z"), "공백 시각": ("created_at", "2026-11-02 01:30:12"), "Z 없음": ("created_at", "2026-11-02T01:30:12"),
            "확인 시각": ("checked_at", "어제"), "성공 시각": ("last_ok_at", "2026-02-30T00:00:00Z"), "약관 시각": ("terms_ack_at", "x"),
            "이름 비었음": ("name", ""), "이름 앞 공백": ("name", " 기본"), "이름 키 모양": ("name", key_shapes()["plain"]), "프로젝트 줄바꿈": ("project", "앱\n둘"),
            "제공자": ("provider", "nope"), "이미지의 빈 제공자": ("provider", ""), "모르는 용도": ("purpose", "unknown_purpose"), "키를 안 받는 용도": ("purpose", "github_repo"),
        }
        for label, (key, value) in cases.items():
            with self.subTest(case=label):
                self.invalid(self.mutated(lambda g, key=key, value=value: g["entries"][0].__setitem__(key, value)), label)

    def test_duplicate_ids_and_too_many_entries_in_a_purpose(self):
        self.invalid(self.mutated(lambda g: g["entries"].append(copy.deepcopy(g["entries"][0]))), "겹친 번호")

        def four(g):
            for index in (3, 4):
                extra = copy.deepcopy(g["entries"][0])
                extra.update(entry_id=f"{index:032x}", name=f"항목{index}", order=index)
                g["entries"].append(extra)

        self.invalid(self.mutated(four), "용도당 4개")

    def test_policy_shapes(self):
        cases = {
            "모르는 용도": lambda g: g["policies"].__setitem__("nope", {"on_limit": "save", "tier": "", "changed_at": ""}),
            "dict 아님": lambda g: g["policies"].__setitem__("image_provider", "save"),
            "낯선 칸": lambda g: g["policies"]["image_provider"].__setitem__("extra", 1),
            "칸 없음": lambda g: g["policies"]["image_provider"].pop("tier"),
            "나쁜 on_limit": lambda g: g["policies"]["image_provider"].__setitem__("on_limit", "turbo"),
            "tier 숫자": lambda g: g["policies"]["image_provider"].__setitem__("tier", 5),
            "없는 tier": lambda g: g["policies"]["image_provider"].__setitem__("tier", "gold"),
            "나쁜 시각": lambda g: g["policies"]["image_provider"].__setitem__("changed_at", "bad"),
            "키를 안 받는 용도의 tier": lambda g: g["policies"].__setitem__("github_repo", {"on_limit": "save", "tier": "demo", "changed_at": ""}),
        }
        for label, change in cases.items():
            with self.subTest(case=label):
                self.invalid(self.mutated(change), label)
        write_raw(self.ctx, self.mutated(lambda g: g["policies"]["image_provider"].__setitem__("tier", "production")))
        self.assertEqual(c.load(self.ctx).policy("image_provider").tier, "production")

    def test_a_file_nested_far_too_deep_is_also_just_an_invalid_file(self):
        """**알려진 빈틈(소스 수정 대기)** — `json.loads` 는 아주 깊은 중첩에 RecursionError 를 내는데 `load` 가 ValueError·OSError 만 받아 CONNECTIONS_FILE_INVALID 대신 예상 못 한 오류가 된다.
        `load` 가 RecursionError 도 같은 오류로 바꾸게 고치면 이 시험이 '예상 밖의 성공' 이 되니 그때 `@unittest.expectedFailure` 표시를 지운다."""
        self.invalid("[" * 20000 + "]" * 20000, "깊은 중첩")

    def test_every_change_on_top_of_a_broken_file_stops_and_leaves_everything_alone(self):
        write_raw(self.ctx, "{broken")
        before, refs = self.file_bytes(), self.store.list_refs()
        calls = {
            "add": lambda: c.add_entry(self.ctx, "image_provider", name="셋째", fields=values("image_provider", "c"), terms_ack=True),
            "remove": lambda: c.remove_entry(self.ctx, ID1[:8], confirmed=True),
            "state": lambda: c.set_state(self.ctx, "1", "off"),
            "reorder": lambda: c.reorder(self.ctx, "image_provider", ["1"]),
            "policy": lambda: c.set_policy(self.ctx, "image_provider", on_limit="failover"),
            "mark": lambda: c.mark_check(self.ctx, ID1, "ok"),
            "list": lambda: c.list_entries(self.ctx, keystore=self.store),
            "test": lambda: c.test_entry(self.ctx, "1", None),
            "summary": lambda: c.diagnostic_summary(self.ctx),
            "save": lambda: c.save(self.ctx, c.Data()),
        }
        for label, call in calls.items():
            with self.subTest(call=label):
                self.assertEqual(ss.code_of(call).code, "CONNECTIONS_FILE_INVALID")
                self.assertEqual(self.file_bytes(), before)
                self.assertEqual(self.store.list_refs(), refs)
                self.assertFalse(self.file_path().with_name("connections.json.bak").read_bytes().startswith(b"{broken"))     # 깨진 내용이 .bak 으로 번지지 않는다


class ListAndStatusTest(Base):
    OLD_KEY_LIMITS = True          # 의도적 갱신(P4f, D-250): 항목이 여럿인 상태를 만든다

    def test_listing_reads_only_and_never_creates_the_data_folder_or_a_lock(self):
        ctx = self.new_ctx()
        self.assertEqual(c.list_entries(ctx, keystore=ctx.keystore), [])
        self.assertEqual((c.load(ctx), c.diagnostic_summary(ctx)["purposes"][0]), (c.Data(), {"purpose": "naver_apihub", "entries": 0, "active": 0}))
        self.assertFalse(ctx.workspace.root.exists())
        self.add(ctx=ctx)
        before = ss.tree_snapshot(ctx.workspace.root)
        c.list_entries(ctx, keystore=ctx.keystore)
        c.list_entries(ctx, purpose="image_provider", keystore=ctx.keystore)
        self.assertEqual(ss.tree_snapshot(ctx.workspace.root), before)
        self.assertFalse(any("connections.lock" in name for name in before if not name.startswith("locks")))

    def test_the_view_never_shows_any_part_of_the_value_whatever_its_length(self):
        """의도적 강화(PCSEC1 H2, 운영자 결정 2026-11-11): 예전에는 값이 16자 이상이면 끝 4자(`****abcd`)를 목록에 보였다 — 이제 어느 길이에서도 값의 일부(끝·앞·접두어·길이)가 없다."""
        for length in (8, 15, 16, 30, 64):
            with self.subTest(length=length):
                ctx = self.new_ctx()
                secret = ("s" * length)[: length - 4] + TAIL
                c.add_entry(ctx, "naver_apihub", name="기본", fields={"client_id": "ClientId0001", "client_secret": secret})
                view = c.list_entries(ctx, keystore=ctx.keystore)[0]
                self.assertFalse(hasattr(view, "tail"))
                self.assertNotIn("tail", view.to_dict())
                shown = json.dumps(view.to_dict(), ensure_ascii=False) + repr(view)
                self.assertNotIn(secret, shown)
                self.assertNotIn(TAIL, shown)
                self.assertNotIn("****", shown)

    def test_a_missing_or_unreadable_value_needs_a_check(self):
        first = self.add(new_id=key_ids(ID1))
        second = self.add(name="예비", seed="b", new_id=key_ids(ID2))
        self.store.delete(second.entry.ref)
        views = c.list_entries(self.ctx, keystore=self.store)
        self.assertEqual([(view.entry.entry_id, view.status) for view in views], [(ID1, "needs_check"), (ID2, "needs_check")])
        self.assertEqual([view.status for view in c.list_entries(self.ctx, keystore=None)], ["needs_check", "needs_check"])
        flaky = FlakyStore()
        flaky.fail_read = True
        views = c.list_entries(self.ctx, keystore=flaky)
        self.assertEqual([view.status for view in views], ["needs_check", "needs_check"])
        self.assertEqual(first.entry.entry_id, ID1)

    def test_filtering_and_the_global_ordinals_follow_the_purpose_order_then_the_item_order(self):
        self.add("image_provider", name="기본", new_id=key_ids(ID1))
        self.add("naver_apihub", name="기본", new_id=key_ids(ID2))
        self.add("image_provider", name="예비", seed="b", new_id=key_ids(ID3))
        views = c.list_entries(self.ctx, keystore=self.store)
        self.assertEqual([(view.ordinal, view.entry.purpose, view.entry.name) for view in views], [(1, "naver_apihub", "기본"), (2, "image_provider", "기본"), (3, "image_provider", "예비")])
        only = c.list_entries(self.ctx, purpose="image_provider", keystore=self.store)
        self.assertEqual([(view.ordinal, view.entry.name) for view in only], [(2, "기본"), (3, "예비")])        # 거르기를 해도 순번은 전체 기준 그대로
        self.assertEqual(c.list_entries(self.ctx, purpose="blogger", keystore=self.store), [])

    def test_the_view_shows_korean_words_from_the_tables_and_the_english_code_only_under_status(self):
        self.add(state="standby")
        view = c.list_entries(self.ctx, keystore=self.store)[0].to_dict()
        self.assertEqual((view["status"], view["status_text"], view["state"], view["state_text"]), ("needs_check", "연결 확인 필요", "standby", "예비"))
        self.assertEqual([key for key, value in view.items() if value == "needs_check"], ["status"])
        self.assertEqual([key for key, value in view.items() if value == "standby"], ["state"])
        self.assertEqual(set(view), {"ordinal", "entry_id", "purpose", "provider", "name", "project", "order", "state", "state_text", "status", "status_text", "created_at",
                                     "checked_at", "last_ok_at", "check_result", "terms_ack_at"})
        self.assertNotIn("bucket", view, "묶음 이름(NAVER 고객 ID 같은 칸의 해시)은 명령줄 JSON 에 싣지 않는다 — 운영자의 '다섯 가지' 밖(PCSEC1V D14)")
        self.assertNotIn("fingerprint", view)                                      # 값에서 만든 표시는 목록에 싣지 않는다

    def entry_with(self, **changes):
        entry = self.add(ctx=self.new_ctx()).entry
        return dataclasses.replace(entry, **changes)

    def test_the_five_statuses_follow_the_rules_in_order(self):
        impl, plain = c.PURPOSES["image_provider"], c.PURPOSES["image_provider"]
        impl = dataclasses.replace(impl, implemented=True)
        now = self.ctx.now()
        recent = self.ctx.stamp()
        ok = {"check_result": "ok", "last_ok_at": recent, "checked_at": recent}
        status = lambda entry, spec=impl, **kw: c.entry_status(entry, spec, now=now, **kw)           # noqa: E731
        self.assertEqual(status(self.entry_with(state="off", **ok)), "not_connected")
        self.assertEqual(status(self.entry_with(check_result="auth_failed")), "auth_error")
        self.assertEqual(status(self.entry_with(state="off", check_result="auth_failed")), "not_connected")      # 꺼진 항목이 먼저다
        self.assertEqual(status(self.entry_with(**ok), secret_present=False), "needs_check")
        self.assertEqual(status(self.entry_with(check_result="auth_failed"), secret_present=False), "auth_error")
        self.assertEqual(status(self.entry_with(**ok)), "connected")
        self.assertEqual(status(self.entry_with(**ok), plain), "needs_check", "실제 호출 코드가 없는 용도는 시험 성공 기록이 있어도 연결됨이 아니다(정직)")
        for label, changes in {"시험한 적 없음": {}, "오류 기록": {"check_result": "error", "last_ok_at": recent}, "성공 시각 없음": {"check_result": "ok"}}.items():
            with self.subTest(case=label):
                self.assertEqual(status(self.entry_with(**changes)), "needs_check")

    def test_a_successful_test_counts_for_exactly_twenty_four_hours(self):
        impl = dataclasses.replace(c.PURPOSES["image_provider"], implemented=True)
        now = self.ctx.now()
        for seconds, expected in ((0, "connected"), (24 * 3600 - 1, "connected"), (24 * 3600, "connected"), (24 * 3600 + 1, "needs_check"), (48 * 3600, "needs_check")):
            with self.subTest(seconds_ago=seconds):
                stamp = (now - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
                entry = self.entry_with(check_result="ok", last_ok_at=stamp)
                self.assertEqual(c.entry_status(entry, impl, now=now), expected)
        entry = self.entry_with(check_result="ok", last_ok_at=(now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertEqual(c.entry_status(entry, impl, now=now, valid_hours=1), "connected")
        self.assertEqual(c.entry_status(entry, impl, now=now, valid_hours=0), "needs_check")

    def test_the_purpose_status_follows_the_first_active_entry(self):
        registry = implemented_registry()
        self.assertEqual(c.purpose_status(self.ctx, c.load(self.ctx), "image_provider", registry, self.store), "not_connected")
        standby = self.add(name="예비", state="standby", new_id=key_ids(ID1)).entry
        self.assertEqual(c.purpose_status(self.ctx, c.load(self.ctx), "image_provider", registry, self.store), "not_connected", "예비만 있으면 연결 안 됨")
        a = self.add(name="가", seed="b", new_id=key_ids(ID2)).entry
        b = self.add(name="나", seed="c", new_id=key_ids(ID3)).entry
        c.mark_check(self.ctx, a.entry_id, "auth_failed")
        c.mark_check(self.ctx, b.entry_id, "ok")
        data = c.load(self.ctx)
        self.assertEqual(c.primary_entry(data, "image_provider").entry_id, a.entry_id)
        self.assertEqual(c.purpose_status(self.ctx, data, "image_provider", registry, self.store), "auth_error", "첫 사용 항목이 인증 실패면 둘째가 성공이어도 첫째를 따른다(다른 키로 바꿔 보이지 않는다)")
        c.set_state(self.ctx, a.entry_id[:8], "off")
        data = c.load(self.ctx)
        self.assertEqual(c.primary_entry(data, "image_provider").entry_id, b.entry_id)
        self.assertEqual(c.purpose_status(self.ctx, data, "image_provider", registry, self.store), "connected")
        self.assertEqual(c.purpose_status(self.ctx, data, "image_provider", c.PURPOSES, self.store), "needs_check")
        self.assertEqual(c.purpose_status(self.ctx, data, "image_provider", registry, None), "needs_check", "보관소를 못 열면 확인 필요")
        self.store.delete(b.ref)
        self.assertEqual(c.purpose_status(self.ctx, data, "image_provider", registry, self.store), "needs_check")
        self.assertEqual(standby.state, "standby")

    def test_with_no_keys_at_all_every_read_function_gives_an_empty_normal_answer(self):
        ctx = self.new_ctx()
        data = c.load(ctx)
        self.assertEqual((data.entries, data.policies, c.numbered(data.entries)), ((), (), []))
        for purpose in c.PURPOSES:
            with self.subTest(purpose=purpose):
                self.assertIsNone(c.primary_entry(data, purpose))
                self.assertEqual(c.purpose_status(ctx, data, purpose, keystore=ctx.keystore), "not_connected")
                self.assertEqual(data.policy(purpose), c.Policy())
        self.assertEqual(c.list_entries(ctx, keystore=None), [])
        self.assertEqual(c.diagnostic_summary(ctx), {"purposes": [{"purpose": key, "entries": 0, "active": 0} for key in c.PURPOSES if key != "naver_openapi"]})
        self.assertFalse(ctx.workspace.root.exists())


class ResolveAndRemoveTest(Base):
    OLD_KEY_LIMITS = True          # 의도적 갱신(P4f, D-250): 항목이 여럿인 상태를 만든다

    N1, N2 = "1a2b3c4d" + "0" * 24, "1a2b9999" + "0" * 24
    I1, I2, I3 = "bbbb0001" + "0" * 24, "bbbb0002" + "0" * 24, "cccc0003" + "0" * 24
    FIRST = "naver_searchad"            # 순번이 이미지 공급자보다 앞서고(레지스트리 둘째) 항목을 3개까지 두는 용도 — 첫 용도 NAVER API HUB 는 키를 하나만 두고 옛 `naver_openapi` 는 맨 뒤라 새 항목을 받지 않는다

    def setUp(self):
        super().setUp()
        self.add(self.FIRST, name="기본", new_id=key_ids(self.N1))
        self.add(self.FIRST, name="예비", seed="b", new_id=key_ids(self.N2))
        self.add("image_provider", name="기본", new_id=key_ids(self.I1))
        self.add("image_provider", name="예비", seed="b", new_id=key_ids(self.I2))
        self.add("image_provider", name="셋째", seed="c", new_id=key_ids(self.I3))

    def rows(self):
        return c.numbered(c.load(self.ctx).entries)

    def resolved(self, text):
        return c.resolve(self.rows(), text).entry.entry_id

    def test_ordinals_ids_prefixes_and_spaces(self):
        self.assertEqual([row.ordinal for row in self.rows()], [1, 2, 3, 4, 5])
        self.assertEqual([row.entry.entry_id for row in self.rows()], [self.N1, self.N2, self.I1, self.I2, self.I3])
        for text, expected in {"1": self.N1, "5": self.I3, " 3 ": self.I1, self.N1: self.N1, self.N1.upper(): self.N1, "1a2b3": self.N1, "1A2B3C4D": self.N1, "bbbb0002": self.I2, "BBBB0002": self.I2,
                               "cccc": self.I3, "ccc0": None}.items():
            with self.subTest(text=text):
                if expected is None:
                    self.assertEqual(ss.code_of(c.resolve, self.rows(), text).code, "CONNECTION_NOT_FOUND")
                else:
                    self.assertEqual(self.resolved(text), expected)

    def test_refusals_say_what_went_wrong_in_the_detail_and_always_use_the_not_found_code(self):
        cases = {"6": "항목은 5개뿐이다", "99": "항목은 5개뿐이다", "0": "너무 짧", "100": "너무 짧", "abc": "앞 4자 이상", "zzzz": "맞는 항목 없음", "": "비어 있음", "   ": "비어 있음", None: "비어 있음", 3: "비어 있음"}
        for text, hint in cases.items():
            with self.subTest(text=text):
                error = ss.code_of(c.resolve, self.rows(), text)
                self.assertEqual(error.code, "CONNECTION_NOT_FOUND")
                self.assertIn(hint, error.slots["항목"] + " " + error.detail)
        error = ss.code_of(c.resolve, self.rows(), "1a2b")
        self.assertIn("기본", error.detail)
        self.assertIn("예비", error.detail)
        self.assertEqual(error.slots["항목"], "번호가 여러 항목과 겹침")

    def test_without_a_confirmation_nothing_is_removed_whatever_truthy_thing_is_passed(self):
        refs, before = self.store.list_refs(), self.file_bytes()
        for confirmed in (False, None, 0, 1, "yes", "true", "True", [], ["x"], "1"):
            for text in ("3", self.I1[:8], self.I1):
                with self.subTest(confirmed=confirmed, text=text):
                    error = ss.code_of(c.remove_entry, self.ctx, text, confirmed=confirmed)
                    self.assertEqual(error.code, "CONFIRMATION_REQUIRED")
                    self.assertIn(f"keys remove {self.I1[:8]} --yes", error.detail)
                    self.assertIn("순번으로는 지우지 않습니다", error.detail)
                    self.assertEqual((self.store.list_refs(), self.file_bytes()), (refs, before))

    def test_an_ordinal_or_a_short_prefix_never_deletes_even_when_confirmed(self):
        refs, before = self.store.list_refs(), self.file_bytes()
        for text in ("5", "05", self.I3[:4], self.I3[:5], self.I3[:6], self.I3[:7]):
            with self.subTest(text=text):
                try:
                    error = ss.code_of(c.remove_entry, self.ctx, text, confirmed=True)
                except AssertionError:
                    self.fail(f"{text!r} 로 지워졌다")
                self.assertIn(error.code, ("CONNECTION_DELETE_NEEDS_NUMBER", "CONNECTION_NOT_FOUND"))
                if text != "05":
                    self.assertEqual(error.code, "CONNECTION_DELETE_NEEDS_NUMBER")
                    self.assertIn(f"keys remove {self.I3[:8]} --yes", error.detail)
                self.assertEqual((self.store.list_refs(), self.file_bytes()), (refs, before))

    def test_eight_characters_or_the_whole_number_delete_the_value_first_and_then_the_metadata(self):
        for text in (self.I1[:8], self.I1, self.I1.upper(), " " + self.I1[:8] + " "):
            with self.subTest(text=text):
                ctx = self.new_ctx()
                for purpose, name, seed, new in (("image_provider", "기본", "a", self.I1), ("image_provider", "예비", "b", self.I2), ("image_provider", "셋째", "c", self.I3), (self.FIRST, "기본", "a", self.N1)):
                    self.add(purpose, name=name, seed=seed, ctx=ctx, new_id=key_ids(new))
                events = []
                original_delete, original_save = ctx.keystore._delete, c.save

                def spying_delete(ref, events=events, original_delete=original_delete):
                    events.append(("delete", ref))
                    return original_delete(ref)

                def spying_save(*args, events=events, original_save=original_save, **kwargs):
                    events.append(("save",))
                    return original_save(*args, **kwargs)

                ctx.keystore._delete = spying_delete
                with mock.patch.object(c, "save", side_effect=spying_save):
                    result = c.remove_entry(ctx, text, confirmed=True)
                self.assertEqual(events, [("delete", "image_provider:" + self.I1), ("save",)], "보관소가 먼저")
                self.assertEqual((result.entry.entry_id, result.keep_cache, result.purpose_label), (self.I1, False, "이미지 공급자"))
                self.assertEqual(sorted(ctx.keystore.list_refs()), sorted(["image_provider:" + self.I2, "image_provider:" + self.I3, f"{self.FIRST}:" + self.N1]))
                rest = c.load(ctx)
                self.assertEqual([(item.entry_id, item.order) for item in rest.of_purpose("image_provider")], [(self.I2, 1), (self.I3, 2)], "남은 항목의 순서가 1부터 다시 매겨진다")
                self.assertEqual([item.order for item in rest.of_purpose(self.FIRST)], [1])

    def test_keep_cache_is_just_the_users_choice_handed_back(self):
        for passed, expected in ((True, True), (False, False), ("yes", True), (0, False)):
            with self.subTest(keep_cache=passed):
                ctx = self.new_ctx()
                self.add(ctx=ctx, new_id=key_ids(self.I1))
                self.assertIs(c.remove_entry(ctx, self.I1[:8], confirmed=True, keep_cache=passed).keep_cache, expected)

    def test_a_value_that_is_already_gone_does_not_stop_the_removal(self):
        self.store.delete("image_provider:" + self.I2)
        result = c.remove_entry(self.ctx, self.I2[:8], confirmed=True)
        self.assertEqual(result.entry.entry_id, self.I2)
        self.assertEqual([item.entry_id for item in c.load(self.ctx).of_purpose("image_provider")], [self.I1, self.I3])

    def test_when_the_keystore_cannot_delete_the_metadata_stays_so_the_item_can_be_removed_again(self):
        store = FlakyStore()
        store.put("image_provider:" + self.I3, values("image_provider", "c"))
        store.fail_delete = True
        before = self.file_bytes()
        error = ss.code_of(c.remove_entry, self.ctx, self.I3[:8], confirmed=True, keystore=store)
        self.assertEqual(error.code, "KEY_STORE_UNAVAILABLE")
        self.assertEqual(self.file_bytes(), before)
        self.assertEqual(len(store.list_refs()), 1)
        store.fail_delete = False
        self.assertEqual(c.remove_entry(self.ctx, self.I3[:8], confirmed=True, keystore=store).entry.entry_id, self.I3)

    def test_an_unknown_item_is_reported_before_the_confirmation_is_even_looked_at(self):
        self.assertEqual(ss.code_of(c.remove_entry, self.ctx, "ffffffff", confirmed=False).code, "CONNECTION_NOT_FOUND")
        self.assertEqual(ss.code_of(c.remove_entry, self.ctx, "ffffffff", confirmed=True).code, "CONNECTION_NOT_FOUND")


class ChangeTest(Base):
    OLD_KEY_LIMITS = True          # 의도적 갱신(P4f, D-250): 항목이 여럿인 상태를 만든다

    def setUp(self):
        super().setUp()
        self.add(name="기본", new_id=key_ids(ID1))
        self.add(name="예비", seed="b", new_id=key_ids(ID2))
        self.add(name="셋째", seed="c", new_id=key_ids(ID3))
        self.add("naver_apihub", name="기본", new_id=key_ids("aaaa1111" * 4))

    def order(self, purpose="image_provider"):
        return [item.entry_id for item in c.load(self.ctx).of_purpose(purpose)]

    def test_set_state_changes_the_state_and_reports_the_previous_one(self):
        entry, before = c.set_state(self.ctx, "2", "off")
        self.assertEqual((entry.entry_id, entry.state, before), (ID1, "off", "active"))                 # 순번 2 = 이미지 공급자의 첫 항목(네이버가 1번)
        self.assertEqual({item.entry_id: item.state for item in c.load(self.ctx).entries if item.purpose == "image_provider"}, {ID1: "off", ID2: "active", ID3: "active"})
        for state in ("active", "standby", "off"):
            with self.subTest(state=state):
                self.assertEqual(c.set_state(self.ctx, ID2[:8], state)[0].state, state)
        for bad in ("사용", "ACTIVE", "", None):
            with self.subTest(bad=bad):
                self.assertEqual(ss.code_of(c.set_state, self.ctx, "2", bad).code, "KEY_INVALID_SHAPE")
        self.assertEqual(ss.code_of(c.set_state, self.ctx, "ffffffff", "off").code, "CONNECTION_NOT_FOUND")

    def test_setting_the_same_state_does_not_write_the_file_again(self):
        with mock.patch.object(c, "save") as saved:
            entry, before = c.set_state(self.ctx, "2", "active")
        self.assertEqual((entry.state, before), ("active", "active"))
        saved.assert_not_called()
        with mock.patch.object(c, "save", wraps=c.save) as saved:
            c.set_state(self.ctx, "2", "standby")
        self.assertEqual(saved.call_count, 1)

    def test_reorder_puts_the_named_items_first_and_keeps_the_others_in_their_old_order(self):
        self.assertEqual(self.order(), [ID1, ID2, ID3])
        result = c.reorder(self.ctx, "image_provider", [ID3[:8]])
        self.assertEqual([item.entry_id for item in result], [ID3, ID1, ID2])
        self.assertEqual(self.order(), [ID3, ID1, ID2])
        c.reorder(self.ctx, "image_provider", [ID2[:8], ID1[:8], ID3[:8]])
        self.assertEqual(self.order(), [ID2, ID1, ID3])
        self.assertEqual([item.order for item in c.load(self.ctx).of_purpose("image_provider")], [1, 2, 3])
        c.reorder(self.ctx, "image_provider", [])
        self.assertEqual(self.order(), [ID2, ID1, ID3])
        self.assertEqual(self.order("naver_apihub"), ["aaaa1111" * 4])

    def test_reorder_refuses_another_purposes_item_a_repeated_item_and_unknown_things(self):
        before = self.file_bytes()
        self.assertEqual(ss.code_of(c.reorder, self.ctx, "image_provider", ["1"]).code, "KEY_INVALID_SHAPE")             # 순번 1 은 네이버 항목
        self.assertEqual(ss.code_of(c.reorder, self.ctx, "image_provider", ["2", ID1]).code, "KEY_INVALID_SHAPE")         # 같은 항목을 두 번(순번과 번호)
        self.assertEqual(ss.code_of(c.reorder, self.ctx, "image_provider", ["ffffffff"]).code, "CONNECTION_NOT_FOUND")
        self.assertEqual(ss.code_of(c.reorder, self.ctx, "no_such", ["2"]).code, "CONNECTION_NOT_FOUND")
        self.assertEqual(self.file_bytes(), before)

    def test_policy_defaults_to_failover_and_either_value_is_set_without_any_confirmation(self):
        self.assertEqual(c.load(self.ctx).policy("image_provider"), c.Policy("failover", "", ""))
        self.assertEqual(set(inspect.signature(c.set_policy).parameters), {"ctx", "purpose", "on_limit", "tier", "registry"})
        self.clock.advance(hours=1)
        saved = c.set_policy(self.ctx, "image_provider", on_limit="save")
        self.assertEqual(saved, c.Policy("save", "", "2026-11-02T02:30:12Z"))
        self.assertEqual(c.load(self.ctx).policy("image_provider"), saved)
        self.assertEqual(c.set_policy(self.ctx, "image_provider", on_limit="failover").on_limit, "failover")
        self.assertEqual(c.load(self.ctx).policy("naver_apihub"), c.Policy(), "다른 용도의 정책은 그대로")

    def test_the_tier_is_only_for_purposes_that_have_more_than_one_and_can_be_cleared(self):
        self.assertEqual(c.set_policy(self.ctx, "image_provider", tier="production").tier, "production")
        self.assertEqual(c.load(self.ctx).policy("image_provider").on_limit, "failover", "tier 만 바꿔도 on_limit 은 그대로")
        self.assertEqual(c.set_policy(self.ctx, "image_provider", tier="demo").tier, "demo")
        self.assertEqual(c.set_policy(self.ctx, "image_provider", tier="").tier, "")
        for purpose, tier in (("naver_apihub", "default"), ("naver_apihub", "demo"), ("naver_openapi", "default"), ("naver_openapi", "demo"), ("image_provider", "gold"), ("image_provider", "default"), ("github_repo", "demo")):
            with self.subTest(purpose=purpose, tier=tier):
                self.assertEqual(ss.code_of(c.set_policy, self.ctx, purpose, tier=tier).code, "KEY_INVALID_SHAPE")

    def test_policy_refusals(self):
        before = self.file_bytes()
        for on_limit in ("turbo", "", "FAILOVER", 1):
            with self.subTest(on_limit=on_limit):
                self.assertEqual(ss.code_of(c.set_policy, self.ctx, "image_provider", on_limit=on_limit).code, "KEY_INVALID_SHAPE")
        for purpose in ("no_such", None, 5):
            with self.subTest(purpose=purpose):
                self.assertEqual(ss.code_of(c.set_policy, self.ctx, purpose, on_limit="save").code, "CONNECTION_NOT_FOUND")
        self.assertEqual(self.file_bytes(), before)

    def test_mark_check_records_the_result_and_only_a_success_moves_the_last_ok_time(self):
        self.clock.advance(minutes=3)
        later = "2026-11-02T01:33:12Z"
        entry = c.mark_check(self.ctx, ID1, "ok")
        self.assertEqual((entry.check_result, entry.checked_at, entry.last_ok_at), ("ok", later, later))
        self.clock.advance(minutes=3)
        entry = c.mark_check(self.ctx, ID1, "error")
        self.assertEqual((entry.check_result, entry.checked_at, entry.last_ok_at), ("error", "2026-11-02T01:36:12Z", later))
        entry = c.mark_check(self.ctx, ID1, "auth_failed")
        self.assertEqual((entry.check_result, entry.last_ok_at), ("auth_failed", later))
        self.assertIsNone(c.mark_check(self.ctx, "f" * 32, "ok"))
        for bad in ("", "good", None, "OK"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as caught:
                    c.mark_check(self.ctx, ID1, bad)
                self.assertNotIn(ID1, str(caught.exception))
        self.assertEqual(c.load(self.ctx).policy("image_provider"), c.Policy())


class FakeGuard:
    """`acquire_entry`·`report` 를 가진 가짜 한도 안전장치 — 부른 일을 적어 둔다."""

    def __init__(self, lease=None):
        self.calls = []
        self.lease = lease if lease is not None else types.SimpleNamespace(entry_id="lease-1")

    def acquire_entry(self, entry, calls=1, priority="normal"):
        self.calls.append(("acquire", entry.entry_id, calls, priority))
        return self.lease

    def report(self, lease, kind, headers=None):
        self.calls.append(("report", lease, kind, headers))


class TestEntryTest(Base):
    HEADERS = {"X-Ratelimit-Remaining": "49", "X-Ratelimit-Limit": "50"}

    def setUp(self):
        super().setUp()
        self.registry = implemented_registry()
        self.entry = self.add(new_id=key_ids(ID1)).entry
        self.fields = values("image_provider")
        self.calls = []

    def make_tester(self, outcome="ok", headers=None):
        def run(spec, entry, fields):
            self.calls.append((spec, entry, fields))
            return c.ProviderResult(outcome, headers)
        return run

    def run_test(self, tester, **kwargs):
        return c.test_entry(self.ctx, "1", tester, registry=self.registry, **kwargs)

    def test_in_the_real_registry_no_purpose_has_call_code_so_a_test_does_nothing_and_says_so(self):
        before = self.file_bytes()
        for tester in (self.make_tester(), None):
            with self.subTest(tester=tester is not None):
                result = c.test_entry(self.ctx, "1", tester)
                self.assertEqual((result.ran, result.reason, result.message, result.entry.entry_id), (False, "not_ready", NOT_READY, ID1))
        self.assertEqual((self.calls, self.file_bytes()), ([], before))
        result = c.test_entry(self.ctx, "1", None, registry=self.registry)                    # 시험 함수가 없으면 구현된 용도여도 준비 중
        self.assertEqual((result.ran, result.reason), (False, "not_ready"))
        for purpose, spec in c.PURPOSES.items():
            self.assertIs(spec.implemented, False, purpose)

    def test_a_success_is_recorded_and_makes_the_entry_connected_for_a_day(self):
        result = self.run_test(self.make_tester("ok"))
        self.assertEqual((result.ran, result.reason, result.outcome), (True, "", "ok"))
        self.assertEqual((result.entry.check_result, result.entry.checked_at, result.entry.last_ok_at), ("ok", STAMP, STAMP))
        spec, entry, fields = self.calls[0]
        self.assertEqual((spec, entry.entry_id), (self.registry["image_provider"], ID1))
        self.assertIsInstance(fields, ks.SecretFields)
        self.assertEqual(fields.to_dict(), self.fields)
        self.assertEqual(c.list_entries(self.ctx, keystore=self.store, registry=self.registry)[0].status, "connected")

    def test_every_other_outcome_is_an_error_except_an_authentication_failure_which_stops_the_entry(self):
        for outcome, expected in (("auth_failed", "auth_failed"), ("rate_limited", "error"), ("error", "error"), ("weird", "error")):
            with self.subTest(outcome=outcome):
                self.setUp()
                result = self.run_test(self.make_tester(outcome))
                self.assertEqual((result.ran, result.entry.check_result, result.entry.last_ok_at), (True, expected, ""))
                status = c.list_entries(self.ctx, keystore=self.store, registry=self.registry)[0].status
                self.assertEqual(status, "auth_error" if expected == "auth_failed" else "needs_check")
        self.setUp()
        for odd in (lambda s, e, f: None, lambda s, e, f: "ok", lambda s, e, f: 5):
            with self.subTest(odd=odd):
                self.clock.advance(minutes=5)
                self.assertEqual(self.run_test(odd).entry.check_result, "error")

    def test_a_tester_that_raises_is_recorded_as_an_error_without_its_message(self):
        secret = self.fields["access_key"]

        def boom(spec, entry, fields):
            raise RuntimeError("연결 실패 " + secret)

        result = self.run_test(boom)
        self.assertEqual((result.ran, result.outcome, result.message, result.entry.check_result), (True, "error", "RuntimeError", "error"))
        self.assertNotIn(secret, repr(result))
        self.assertNotIn(TAIL, " ".join(text for text in all_text(self.ctx).values()))

    def test_the_same_key_is_not_tested_again_within_sixty_seconds(self):
        self.run_test(self.make_tester())
        for seconds in (0, 1, 30, 59):
            with self.subTest(seconds=seconds):
                self.clock.now = ss.NOW + timedelta(seconds=seconds)
                calls = len(self.calls)
                result = self.run_test(self.make_tester())
                self.assertEqual((result.ran, result.reason, result.message), (False, "too_soon", "같은 키는 60초 안에 다시 시험하지 않습니다"))
                self.assertLessEqual(60 - seconds, result.wait_seconds)
                self.assertLessEqual(result.wait_seconds, 60 - seconds + 1)
                self.assertEqual(len(self.calls), calls)
        self.assertEqual(c.load(self.ctx).entries[0].checked_at, STAMP, "시험하지 않았으니 기록도 안 바뀐다")
        for seconds in (60, 61, 3600):
            with self.subTest(seconds=seconds):
                self.clock.now = ss.NOW + timedelta(seconds=seconds)
                calls = len(self.calls)
                self.assertTrue(self.run_test(self.make_tester()).ran)
                self.assertEqual(len(self.calls), calls + 1)
                self.clock.now = ss.NOW                                             # 다음 시험을 위해 기록 시각을 원래대로 되돌려 놓는다
                c.mark_check(self.ctx, ID1, "ok")

    def test_a_clock_that_went_backwards_does_not_block_the_test(self):
        self.run_test(self.make_tester())
        self.clock.advance(hours=-1)
        self.assertTrue(self.run_test(self.make_tester()).ran)

    def test_a_missing_value_is_reported_and_the_tester_is_not_called(self):
        self.store.delete(self.entry.ref)
        result = self.run_test(self.make_tester())
        self.assertEqual((result.ran, result.reason, result.message), (False, "no_value", "보관소에 키가 없습니다 — 항목을 지우고 다시 추가합니다"))
        self.assertEqual(self.calls, [])

    def test_the_guard_counts_the_test_call_and_receives_the_headers_untouched(self):
        for outcome, kind in (("ok", "ok"), ("auth_failed", "auth_failed"), ("rate_limited", "rate_limited"), ("error", "other_error"), ("weird", "other_error")):
            with self.subTest(outcome=outcome):
                self.setUp()
                guard = FakeGuard()
                self.run_test(self.make_tester(outcome, self.HEADERS), guard=guard)
                self.assertEqual(guard.calls, [("acquire", ID1, 1, "critical"), ("report", guard.lease, kind, self.HEADERS)])
                self.assertIs(guard.calls[1][3], self.HEADERS)
        self.setUp()
        guard = FakeGuard()

        def boom(spec, entry, fields):
            raise RuntimeError("x")

        self.run_test(boom, guard=guard)
        self.assertEqual(guard.calls[1], ("report", guard.lease, "other_error", None))

    def test_when_the_guard_refuses_the_test_call_is_not_made(self):
        guard = FakeGuard(lease=types.SimpleNamespace(reason="한도에 가까워 절약 모드"))
        before = self.file_bytes()
        result = self.run_test(self.make_tester(), guard=guard)
        self.assertEqual((result.ran, result.reason, result.message), (False, "not_ready", "한도에 가까워 절약 모드"))
        self.assertEqual((self.calls, self.file_bytes(), [call[0] for call in guard.calls]), ([], before, ["acquire"]))


class LockTest(Base):
    OLD_KEY_LIMITS = True          # 의도적 갱신(P4f, D-250): 항목이 여럿인 상태를 만든다

    def lock_path(self):
        return self.ctx.workspace.locks_dir / "connections.lock"

    @contextlib.contextmanager
    def fast_lock(self):
        """`locked` 의 기본 기다림(10초)을 없애 다른 작업이 쥐고 있을 때 바로 KEYS_BUSY 가 나게 한다."""
        original = c.locked
        with mock.patch.object(c, "locked", lambda ctx, name="connections", wait=0: original(ctx, name, wait=wait)):
            yield

    def test_a_second_holder_gets_keys_busy_and_the_lock_is_always_released(self):
        with c.locked(self.ctx):
            self.assertTrue(self.lock_path().exists())
            error = ss.code_of(c.locked(self.ctx, wait=0).__enter__)
            self.assertEqual(error.code, "KEYS_BUSY")
        self.assertFalse(self.lock_path().exists())
        with self.assertRaises(RuntimeError):
            with c.locked(self.ctx):
                raise RuntimeError("안에서 실패")
        self.assertFalse(self.lock_path().exists())
        with c.locked(self.ctx):                                                       # 풀린 뒤에는 다시 잡힌다
            self.assertTrue(self.lock_path().exists())

    def test_each_lock_name_is_its_own_lock(self):
        with c.locked(self.ctx, "connections"):
            with c.locked(self.ctx, "quota-state", wait=0):
                self.assertTrue((self.ctx.workspace.locks_dir / "quota-state.lock").exists())

    def test_every_change_happens_inside_the_lock_and_is_refused_while_another_holds_it(self):
        self.add(new_id=key_ids(ID1))
        seen = []
        original_save = c.save

        def watching_save(*args, **kwargs):
            seen.append(self.lock_path().exists())
            return original_save(*args, **kwargs)

        with mock.patch.object(c, "save", side_effect=watching_save):
            self.add(name="예비", seed="b", new_id=key_ids(ID2))
            c.set_state(self.ctx, "1", "off")
            c.reorder(self.ctx, "image_provider", ["2"])
            c.set_policy(self.ctx, "image_provider", on_limit="save")
            c.mark_check(self.ctx, ID1, "ok")
            c.remove_entry(self.ctx, ID2[:8], confirmed=True)
        self.assertEqual(seen, [True] * 6)
        self.assertFalse(self.lock_path().exists())
        before, refs = self.file_bytes(), self.store.list_refs()
        with self.fast_lock(), c.locked(self.ctx):
            calls = {
                "add": lambda: self.add(name="셋째", seed="c"),
                "remove": lambda: c.remove_entry(self.ctx, ID1[:8], confirmed=True),
                "state": lambda: c.set_state(self.ctx, "1", "standby"),
                "reorder": lambda: c.reorder(self.ctx, "image_provider", ["1"]),
                "policy": lambda: c.set_policy(self.ctx, "image_provider", on_limit="failover"),
                "mark": lambda: c.mark_check(self.ctx, ID1, "error"),
            }
            for label, call in calls.items():
                with self.subTest(call=label):
                    self.assertEqual(ss.code_of(call).code, "KEYS_BUSY")
        self.assertEqual((self.file_bytes(), self.store.list_refs()), (before, refs))

    def test_the_value_is_put_into_the_keystore_only_while_the_lock_is_held(self):
        held = []

        class Spy(ks.MemoryStore):
            def _write(spy, ref, raw):
                held.append(self.lock_path().exists())
                super()._write(ref, raw)

            def _delete(spy, ref):
                held.append(self.lock_path().exists())
                return super()._delete(ref)

        store = Spy()
        added = c.add_entry(self.ctx, "image_provider", name="기본", fields=values("image_provider"), keystore=store, new_id=key_ids(ID1))
        c.remove_entry(self.ctx, added.entry.entry_id[:8], confirmed=True, keystore=store)
        self.assertEqual(held, [True, True])


class DiagnosticsTest(Base):
    OLD_KEY_LIMITS = True          # 의도적 갱신(P4f, D-250): 항목이 여럿인 상태를 만든다

    def test_the_summary_has_only_counts_and_no_name_id_project_tail_or_value(self):
        fields = values("image_provider")
        a = c.add_entry(self.ctx, "image_provider", name="비밀이름", fields=fields, project="비밀프로젝트", new_id=key_ids(ID1)).entry
        c.add_entry(self.ctx, "image_provider", name="예비", fields=values("image_provider", "b"), state="standby", terms_ack=True)
        self.add("naver_apihub", name="네이버")
        summary = c.diagnostic_summary(self.ctx)
        self.assertEqual(summary, {"purposes": [{"purpose": "naver_apihub", "entries": 1, "active": 1}, {"purpose": "naver_searchad", "entries": 0, "active": 0},
                                                {"purpose": "image_provider", "entries": 2, "active": 1}, {"purpose": "ai_assist", "entries": 0, "active": 0},
                                                {"purpose": "blogger", "entries": 0, "active": 0}, {"purpose": "github_repo", "entries": 0, "active": 0}]})              # 옛 용도는 그 항목이 남아 있을 때만 요약에 한 줄이 있다
        text = json.dumps(summary, ensure_ascii=False)
        probes = [ID1, ID1[:8], "비밀이름", "비밀프로젝트", "예비", "네이버", a.bucket, TAIL, "****", *fields.values()]
        for probe in probes:
            self.assertNotIn(probe, text, probe)

    def test_a_whole_session_leaves_no_value_or_tail_in_any_file_of_the_data_folder(self):
        registry = implemented_registry()
        secrets = []
        for purpose, seed, name in (("image_provider", "a", "기본"), ("image_provider", "b", "예비"), ("image_provider", "c", "셋째"), ("naver_apihub", "a", "기본"), ("ai_assist", "a", "기본")):
            self.add(purpose, name=name, seed=seed, project=f"앱 {seed}")
            secrets.extend(values(purpose, seed).values())
        c.set_state(self.ctx, "3", "standby")
        c.reorder(self.ctx, "image_provider", ["4"])
        c.set_policy(self.ctx, "image_provider", on_limit="save", tier="production")
        c.mark_check(self.ctx, c.load(self.ctx).entries[0].entry_id, "ok")
        guard = FakeGuard()
        c.test_entry(self.ctx, "3", lambda spec, entry, fields: c.ProviderResult("ok", {"X-Ratelimit-Remaining": "40"}), guard=guard, registry=registry)
        self.clock.advance(minutes=5)
        c.remove_entry(self.ctx, c.load(self.ctx).of_purpose("image_provider")[0].entry_id[:8], confirmed=True)
        files = all_text(self.ctx)
        self.assertTrue({"connections.json", "connections.json.bak", "settings.json"} <= set(files), sorted(files))
        for path, text in files.items():
            for secret in secrets:
                self.assertNotIn(secret, text, path)
                self.assertNotIn(secret[-4:], text, path)
        self.assertEqual([path for path in files if path.startswith("locks/")], [], "잠금 파일은 끝나면 남지 않는다")

    def test_the_connections_file_is_plain_metadata_a_person_could_read_and_never_a_secret_store(self):
        self.add(project="내 앱")
        data = self.read_file()
        flat = json.dumps(data, ensure_ascii=False)
        for word in ("access_key", "client_secret", "refresh_token", "secret_key", "access_license"):
            self.assertNotIn(word, flat)                                        # 칸 이름조차 파일에 없다(칸은 보관소의 값 묶음 안에만 있다)


def setUpModule():
    ss.blogger_input_on()                                    # 이 시험은 실제 레지스트리의 blogger 용도를 그릇으로 쓴다 — Blogger 입력을 임시로만 연다(소스 상수는 False — PCSEC1)


def tearDownModule():
    ss.blogger_input_off()


if __name__ == "__main__":
    unittest.main()
