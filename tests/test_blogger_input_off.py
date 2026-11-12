"""Blogger OAuth 입력 칸 숨김·거절과 시험용 보관소 안내(PCSEC1 — 운영자 결정 2026-11-11 6항, 보안 조사 M2).

지키는 것:
  1) **소스 상수** `capabilities.BLOGGER_OAUTH_INPUT` 는 False 다(호출 코드가 없는 이 빌드는 Blogger 로그인 정보를 받지 않는다 — 켜는 길이 없고 시험만 임시로 켠다).
  2) **서비스**: `connections.add_entry` 가 blogger 용도를 **보관소에 쓰기 전에** 거절한다(KEY_INVALID_SHAPE + 쉬운 이유). 다른 용도는 그대로다. 저장 구조는 그대로라서 상수를 켜면(시험) 예전처럼 저장된다 —
     이미 저장된 항목은 꺼져 있어도 목록·지우기가 된다.
  3) **명령줄**: `keys add blogger` 는 **키를 묻기 전에** 같은 안내로 거절한다(`--stdin` 입력도 읽지 않는다). `keys purposes` 는 입력 칸 대신 안내를 보이고 JSON 의 `takes_keys` 는 거짓·`fields` 는 빈 목록이다.
  4) **화면 데이터**: 실제·예시 공급자 모두 blogger 카드에 입력 칸·제공자·키 등록 단추가 없다(카드 글은 '받지 않아요' 안내). 상수를 켜면(시험) 기존 3칸 카드 그대로다.
  5) **시험용 가짜 보관소 안내(M2)**: 시험 전용 가짜 보관소(`is_fake`)를 쓰는 중이면 키 카드의 보관소 안내와 등록 대화상자 머리말이 '시험용 보관소 — 실제 키를 넣지 마세요' 를 알린다(진짜 보관소·시험용 메모리 보관소는 아니다).
네트워크 없이 돈다.
"""
import dataclasses
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import secret_support as sec  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security.keystore import MemoryStore  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.ui import adapters  # noqa: E402
from chanceblog_desktop.ui.core import app_state, jobs, keys, services, settings_view  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

FIELDS = {"client_id": "BloggerClient0001.apps.example", "client_secret": "S3cretValue" + "ForTheTest0001", "refresh_token": "RefreshValue" + "ForTheTest00000001"}      # 조립한 가짜 값(저장소 비밀 스캐너 오탐을 없앤다)
FIELD_LABELS = ("클라이언트 ID", "클라이언트 시크릿", "갱신용 인증 값")


def flat_texts(value):
    """뷰모델 안의 모든 글(딕셔너리·목록·튜플·dataclass 를 따라간다)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from flat_texts(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from flat_texts(item)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            yield from flat_texts(getattr(value, item.name))


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.store = MemoryStore()
        self.ctx = ss.make_ctx(self.tmp, repo=None)
        self.ctx.keystore = self.store


class ConstantTest(unittest.TestCase):
    def test_the_blogger_input_constant_is_off_in_the_shipped_source(self):
        self.assertIs(capabilities.BLOGGER_OAUTH_INPUT, False)
        self.assertFalse(capabilities.blogger_oauth_input_enabled())
        for value in (1, "yes", object()):
            with mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", value):
                self.assertFalse(capabilities.blogger_oauth_input_enabled(), "글자 그대로 True 일 때만 열린다")

    def test_only_blogger_changes_what_a_purpose_accepts(self):
        for key, spec in cn.PURPOSES.items():
            self.assertEqual(cn.accepts_input(spec), spec.takes_keys and key != "blogger", key)
        with mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", True):
            self.assertTrue(cn.accepts_input(cn.PURPOSES["blogger"]))


class ServiceTest(Base):
    def add(self, purpose="blogger", fields=FIELDS, **kwargs):
        return cn.add_entry(self.ctx, purpose, name="기본", fields=fields, keystore=self.store, **kwargs)

    def test_adding_a_blogger_entry_is_refused_before_anything_is_written(self):
        with self.assertRaises(AppError) as caught:
            self.add()
        self.assertEqual(caught.exception.code, "KEY_INVALID_SHAPE")
        self.assertEqual(caught.exception.slots["이유"], cn.BLOGGER_INPUT_OFF)
        self.assertIn("받지 않습니다", cn.BLOGGER_INPUT_OFF)
        self.assertLessEqual(len(cn.BLOGGER_INPUT_OFF), 160, "오류 문구 칸(160자)에 다 들어간다")
        self.assertEqual(self.store.list_refs(), [], "보관소에 아무것도 쓰지 않았다")
        self.assertFalse(self.ctx.workspace.connections_path.exists(), "연결 설정 파일도 만들지 않았다")
        shown = caught.exception.rendered().message
        self.assertIn("Blogger", shown)
        for secret in FIELDS.values():
            sec.assert_no_secret(self, secret, shown + repr(caught.exception.slots) + str(caught.exception.detail), "거절 오류")

    def test_other_purposes_are_untouched(self):
        result = self.add("ai_assist", {"key": "AiAssistKeyForTheTest00001"}, provider="gemini")
        self.assertEqual(result.entry.purpose, "ai_assist")
        self.assertEqual(len(self.store.list_refs()), 1)

    def test_with_the_constant_opened_by_a_test_the_stored_structure_is_the_same_as_before(self):
        with mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", True):
            result = self.add()
        self.assertEqual(result.entry.purpose, "blogger")
        fields = self.store.get(self.store.list_refs()[0])
        self.assertEqual(sorted(fields.names()) if hasattr(fields, "names") else sorted(FIELDS), sorted(FIELDS))
        self.assertEqual(fields.reveal("client_secret"), FIELDS["client_secret"], "값은 자격 증명 관리자(여기서는 가짜 보관소)에만 있다")
        sec.assert_no_secret(self, FIELDS["client_secret"], self.ctx.workspace.connections_path.read_text(encoding="utf-8"), "연결 설정 파일")

    def test_an_entry_saved_earlier_can_still_be_listed_and_removed_while_the_input_is_off(self):
        with mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", True):
            self.add()
        views = cn.list_entries(self.ctx, keystore=self.store)
        self.assertEqual([(view.entry.purpose, view.entry.name) for view in views], [("blogger", "기본")])
        removed = cn.remove_entry(self.ctx, cn.short_id(views[0].entry.entry_id) if hasattr(cn, "short_id") else views[0].entry.entry_id, confirmed=True, keystore=self.store)
        self.assertEqual(removed.entry.purpose, "blogger")
        self.assertEqual(self.store.list_refs(), [])


class CliTest(Base):
    class NoReadStdin:
        def read(self, *args):
            raise AssertionError("키를 묻기 전에 거절해야 한다 — 입력을 읽었다")

        def isatty(self):
            raise AssertionError("키를 묻기 전에 거절해야 한다")

    def run_cli(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), out=out, err=err, ctx=self.ctx, env={}, stdin=stdin if stdin is not None else io.StringIO(""))
        return code, out.getvalue(), err.getvalue()

    def test_keys_add_blogger_is_refused_before_asking_for_the_key(self):
        before = ss.tree_snapshot(self.tmp)
        code, out, err = self.run_cli("keys", "add", "blogger", "--name", "기본", "--stdin", stdin=self.NoReadStdin())
        self.assertEqual(code, 1)
        self.assertIn("KEY_INVALID_SHAPE", err)
        self.assertIn("이 시험 버전에서는 Blogger 로그인 정보를 받지 않습니다", err)
        self.assertEqual(self.store.list_refs(), [])
        self.assertEqual(ss.tree_snapshot(self.tmp), before)

    def test_keys_add_blogger_with_json_output_has_the_same_error(self):
        code, out, err = self.run_cli("--json", "keys", "add", "blogger", "--name", "기본", "--stdin", stdin=io.StringIO(json.dumps(FIELDS)))
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual((payload["ok"], payload["error"]["code"]), (False, "KEY_INVALID_SHAPE"))
        sec.assert_no_secret(self, FIELDS["client_secret"], out + err, "명령줄 출력")

    def test_keys_purposes_shows_a_note_instead_of_the_input_fields_for_blogger(self):
        code, out, err = self.run_cli("keys", "purposes")
        self.assertEqual(code, 0, err)
        block = out.split("[blogger]", 1)[1].split("[github_repo]", 1)[0]
        self.assertIn("안내: 이 시험 버전에서는 Blogger 로그인 정보를 받지 않습니다", block)
        self.assertNotIn("받는 칸", block)
        for label in FIELD_LABELS:
            self.assertNotIn(label, block)
        code, out, err = self.run_cli("--json", "keys", "purposes")
        blogger = next(item for item in json.loads(out)["data"]["purposes"] if item["purpose"] == "blogger")
        self.assertEqual((blogger["takes_keys"], blogger["fields"]), (False, []))
        self.assertEqual(blogger["note"], cn.BLOGGER_INPUT_OFF)

    def test_the_other_purposes_still_list_their_fields(self):
        code, out, err = self.run_cli("--json", "keys", "purposes")
        by = {item["purpose"]: item for item in json.loads(out)["data"]["purposes"]}
        self.assertTrue(by["image_provider"]["takes_keys"])
        self.assertEqual([item["name"] for item in by["image_provider"]["fields"]], ["access_key"])


class ScreenDataTest(Base):
    def real_blogger(self):
        provider = adapters.ServiceConnectionsProvider(None, context_factory=lambda data_dir=None: self.ctx, keystore=self.store)
        data = provider.load_connections(lambda *_: None, lambda: False)
        return data, next(info for info in data.purposes if info.key == "blogger")

    def test_the_real_provider_gives_the_blogger_card_no_input_fields_providers_or_register_button(self):
        data, info = self.real_blogger()
        self.assertEqual((info.takes_keys, info.providers, info.fields, info.status), (False, (), (), ""))
        vm = settings_view.card_vm(info, False)
        self.assertEqual((vm["desc"], vm["note"]), (T["purpose_blogger_off"], T["blogger_off_note"]))
        texts = " ".join(flat_texts(vm))
        for label in FIELD_LABELS:
            self.assertNotIn(label, texts)
        env_state = app_state.AppState(services.FakeHomeProvider(), connections=keys.FakeKeysProvider(), runner=jobs.JobRunner())
        env_state.apply_connections(data)
        controller = env_state.keys
        self.assertIsNone(controller.register_vm(info))
        self.assertIsNone(controller.card_keys(info))
        self.assertIsNone(controller.open_register("blogger"))

    def test_the_sample_provider_hides_it_the_same_way(self):
        info = next(item for item in services.sample_connections() if item.key == "blogger")
        self.assertEqual((info.takes_keys, info.providers, info.fields), (False, (), ()))

    def test_with_the_constant_opened_by_a_test_the_three_field_card_is_back(self):
        with mock.patch.object(capabilities, "BLOGGER_OAUTH_INPUT", True):
            sample = next(item for item in services.sample_connections() if item.key == "blogger")
            data, info = self.real_blogger()
        self.assertEqual([item.label for item in sample.fields], list(FIELD_LABELS))
        self.assertTrue(info.takes_keys)
        self.assertEqual([item.label for item in info.fields], list(FIELD_LABELS))

    def test_the_two_sample_tables_still_agree_with_the_service_table_for_blogger(self):
        """예시 표(`_CONN_TABLE`)와 서비스 표는 구조가 같다 — 입력을 막는 것은 만들 때의 상수 확인 하나다."""
        spec = cn.PURPOSES["blogger"]
        row = next(item for item in services._CONN_TABLE if item[0] == "blogger")
        self.assertEqual((row[3], row[4]), (spec.takes_keys, spec.max_entries))


class FakeStoreNoticeTest(Base):
    class FlaggedStore(MemoryStore):
        is_fake = True

    def env(self, fake):
        class Provider(keys.FakeKeysProvider):
            def load_connections(self, progress, cancelled):
                return dataclasses.replace(super().load_connections(progress, cancelled), fake_store=fake)

        state = app_state.AppState(services.FakeHomeProvider(), connections=Provider(), runner=jobs.JobRunner())
        state.apply_connections(Provider().load_connections(lambda *_: None, lambda: False))
        return state.keys

    def test_a_real_store_and_the_memory_test_store_show_no_notice(self):
        for fake in (False,):
            controller = self.env(fake)
            info = controller.info("image_provider")
            self.assertIsNone(controller.card_keys(info)["store_note"])
            draft = controller.open_register("image_provider")
            self.assertNotIn(T["keys_store_fake"], draft.vm()["intro"])
        provider = adapters.ServiceConnectionsProvider(None, context_factory=lambda data_dir=None: self.ctx, keystore=self.store)
        self.assertFalse(provider.load_connections(lambda *_: None, lambda: False).fake_store)

    def test_a_fake_store_puts_the_notice_on_the_key_cards_and_the_registration_dialog(self):
        controller = self.env(True)
        info = controller.info("image_provider")
        note = controller.card_keys(info)["store_note"]
        self.assertEqual((note["title"], note["why"]), (T["keys_store_fake"], T["keys_store_fake_why"]))
        self.assertEqual(T["keys_store_fake"], "시험용 보관소 — 실제 키를 넣지 마세요")
        self.assertEqual(T["keys_store_fake_why"], "지금은 시험 전용 가짜 보관소를 쓰고 있어요. 여기에 넣은 키는 안전하게 보관되지 않아요.")          # 글자 그대로(T 끼리만 견주면 이유 문장이 비어도 모른다)
        draft = controller.open_register("image_provider")
        intro = draft.vm()["intro"]
        self.assertIn(T["keys_store_fake"], intro)
        self.assertIn(T["keys_store_fake_why"], intro, "이유 문장도 대화상자 첫머리에 있다")
        self.assertIn(T["keys_reg_intro"], intro, "원래 머리말도 그대로다")

    def test_data_read_without_the_flag_shows_no_notice_by_default(self):
        self.assertIs(services.ConnectionsData().fake_store, False)
        self.assertIs(services.ConnectionsData(purposes=()).fake_store, False)

    def test_the_service_provider_reads_the_fake_flag_from_the_store(self):
        store = self.FlaggedStore()
        provider = adapters.ServiceConnectionsProvider(None, context_factory=lambda data_dir=None: self.ctx, keystore=store)
        data = provider.load_connections(lambda *_: None, lambda: False)
        self.assertTrue(data.fake_store)
        self.assertTrue(data.store_ready)

    def test_the_real_file_fake_store_makes_the_provider_say_so(self):
        import tempfile
        from chanceblog_desktop.security.keystore import FileFakeStore
        with tempfile.TemporaryDirectory() as folder:
            provider = adapters.ServiceConnectionsProvider(None, context_factory=lambda data_dir=None: self.ctx, keystore=FileFakeStore(folder))
            data = provider.load_connections(lambda *_: None, lambda: False)
        self.assertTrue(data.fake_store, "시험 전용 가짜 파일 보관소는 스스로 가짜라고 말하고, 화면 어댑터가 그것을 읽어 안내를 켠다")
        self.assertTrue(data.store_ready)

    def test_a_missing_store_keeps_its_own_notice(self):
        controller = self.env(True)
        data = controller.data()
        controller_state = dataclasses.replace(data, store_ready=False)
        controller._data = lambda: controller_state
        info = controller.info("image_provider")
        note = controller.card_keys(info)["store_note"]
        self.assertEqual(note["title"], T["keys_store_missing"])


if __name__ == "__main__":
    unittest.main()
