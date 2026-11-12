"""키 연결 화면(P4f)의 순수 규칙 시험 — 입력 칸 규칙·`SecretBox`·가짜 공급자와 서비스 표의 일치·`KeysController`(행동 가능 여부·쓰기 흐름·중복 클릭·입력 유지)·등록 초안·설정 뷰모델. PySide6 가 없어도 돈다.

지키는 것:
  1) 입력 규칙은 **느슨하다**(빈 값·가운데 공백·제어 문자·비정상적으로 짧음만 거르고 정확한 길이·모양은 강제하지 않는다)이고 결과는 문제 이름뿐이다 — 입력한 글이 어디에도 되돌려지지 않는다.
  2) `SecretBox` 는 꺼내면 비워지고 `repr`·`str`·`format`·복사·직렬화가 글을 보이지 않는다.
  3) 가짜 공급자의 제공자·칸·약관 확인 표는 서비스 표(`connections.PURPOSES`)와 같다(둘을 견준다).
  4) 읽기 전용 공급자에서는 키 행동이 하나도 없고 카드는 이전과 같다. 쓰는 공급자에서도 쓰기는 사용자가 단추를 눌렀을 때만 시작되고 한 번에 하나다(돌고 있을 때의 두 번째는 아무 일도 하지 않고 통을 비운다).
  5) 키 저장소를 못 쓰는 환경은 오류가 아니라 상태다(등록·삭제·별칭·시험은 꺼지고 까닭이 보인다). 호출 코드가 없는 용도의 시험은 '준비 중' 으로 꺼져 있고, 이용 약관 확인 전 용도는 시험도 하지 않는다.
  6) 실패해도 별칭 같은 입력은 남고 키는 다시 입력한다. **가짜 키와 그 조각이 컨트롤러·상태·뷰모델·작업 일감·실패 객체 어디에도 없다**(전수).
  7) 삭제 도중 파일 쓰기가 실패하면(키 저장소의 키는 이미 지워졌을 수 있다) '바뀐 것은 없어요' 라고 하지 않고 어느 쪽이어도 참인 문장을 보이며 목록을 바로 다시 읽는다 — 다른 쓰기의 같은 실패 문장은 그대로다(독립 검증 M1, `DeleteFailureTest`).
"""
import dataclasses
import re
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import key_leak_support as leak  # noqa: E402

from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.ui.core import app_state, jobs, key_rules, keys, keys_view, services, settings_view  # noqa: E402
from chanceblog_desktop.ui.core.text import FORBIDDEN, T  # noqa: E402

KEY = leak.make_key("a")
OTHER = leak.make_key("b")
NEEDLES = leak.needles(KEY, OTHER)
INTERNAL = re.compile(r"\b(?:needs_check|not_connected|auth_error|rate_limited|rotation|failover|standby|implemented|takes_keys|max_entries|legacy|fail_closed|KEY_[A-Z_]+|SAMPLE_[A-Z_]+)\b")


def box_for(purpose="image_provider", key=KEY):
    """용도의 모든 입력 칸에 같은 가짜 글을 담은 통."""
    box = keys.SecretBox()
    for name, _label, _min in services._FIELD_TABLE[purpose]:
        box.put(name, key)
    return box


class Env:
    """가짜 공급자 + 실제 작업 스레드 틀 — 쓰기 하나를 실제 작업 스레드에서 돌리고 결과를 컨트롤러에 넘긴다(화면이 시그널로 하는 일을 시험이 직접 한다)."""

    def __init__(self, provider=None, **kwargs):
        self.runner = jobs.JobRunner()
        self.provider = provider or keys.FakeKeysProvider(**kwargs)
        self.state = app_state.AppState(services.FakeHomeProvider(), connections=self.provider, runner=self.runner)
        self.reload()

    @property
    def controller(self):
        return self.state.keys

    def reload(self):
        self.state.apply_connections(self.provider.load_connections(lambda *_: None, lambda: False))

    def info(self, purpose):
        return self.controller.info(purpose)

    def run(self, starter):
        """`starter(**콜백)` 이 `("started", 작업)` 을 주면 끝까지 돌려 결과를 컨트롤러에 넘긴다 → (상태, (종류, 값))."""
        results = []
        status, job = starter(on_done=lambda result, _payload: results.append(("ok", result)), on_error=lambda failure, _payload: results.append(("err", failure)),
                              on_cancel=lambda _payload: results.append(("cancel", None)))
        if status != "started":
            return status, job
        job.join(10)
        kind, value = results[0]
        if kind == "ok":
            self.controller.apply_write_ok(value)
        elif kind == "err":
            self.controller.apply_write_failed(value)
        if self.controller.reload_wanted:
            self.reload()
        return status, (kind, value)


class RulesTest(unittest.TestCase):
    def test_pasted_line_breaks_are_removed_and_outer_spaces_are_trimmed(self):
        breaks = chr(10) + chr(13) + chr(11) + chr(12) + chr(0x85) + chr(0x2028) + chr(0x2029)
        self.assertEqual(key_rules.clean_secret("  abcd" + breaks + "efgh  "), "abcdefgh")
        self.assertEqual(key_rules.clean_secret(chr(13) + chr(10) + "abcdefgh" + chr(13) + chr(10)), "abcdefgh")
        self.assertEqual(key_rules.clean_secret(""), "")
        self.assertEqual(key_rules.clean_secret("ab cd"), "ab cd")                       # 가운데 공백은 그대로 둔다 — 문제로 알린다

    def test_the_secret_check_is_loose_it_only_refuses_empty_hidden_and_abnormally_short_values(self):
        cases = {"": "empty", "abc": "short", "1234567": "short", "12345678": "", "ab cdefgh": "hidden", "ab" + chr(9) + "cdefgh": "hidden", "ab" + chr(0x200B) + "cdefgh": "hidden",
                 "ab" + chr(0) + "cdefgh": "hidden", "가나다라마바사아": "", "!@#$%^&*()": "", "x" * 5000: ""}
        for text, expected in cases.items():
            with self.subTest(text=text[:10]):
                self.assertEqual(key_rules.secret_problem(text), expected)
        self.assertEqual(key_rules.SECRET_MIN, 8)

    def test_the_exact_length_and_shape_of_a_key_are_never_forced(self):
        for length in (8, 16, 24, 39, 40, 43, 64, 128, 256, 1000):
            self.assertEqual(key_rules.secret_problem("k" + "Z" * (length - 1)), "", length)
        for shape_text in (KEY, OTHER, "AKIA" + "Q" * 20, "plain-words-with-dashes-1234", "한글키값입니다만괜찮아요"):
            self.assertEqual(key_rules.secret_problem(shape_text), "", shape_text[:8])

    def test_problem_names_never_contain_what_was_typed(self):
        inputs = (KEY, KEY + " " + OTHER, "", KEY[:3], KEY + chr(0x200B), "  " + KEY + "  ")
        for text in inputs:
            for result in (key_rules.secret_problem(text), key_rules.secret_problem(key_rules.clean_secret(text)), key_rules.alias_problem(text)):
                self.assertIn(result, ("",) + key_rules.SECRET_PROBLEMS + key_rules.ALIAS_PROBLEMS)
                self.assertEqual(leak.text_hits(result, NEEDLES), [])

    def test_the_alias_check_normalizes_spaces_and_refuses_keys_and_hidden_characters(self):
        self.assertEqual(key_rules.normalize_alias("  내   별칭  "), "내 별칭")
        cases = {"기본": "", "  내   별칭  ": "", "": "empty", "   ": "empty", "가" * 40: "", "가" * 41: "long", KEY: "keyish", "내 키 " + KEY: "keyish", "ghp" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3": "keyish",
                 "숨" + chr(0x200B) + "김": "hidden", "줄" + chr(10) + "바꿈": ""}                                   # 줄바꿈은 공백 하나로 접힌다
        for text, expected in cases.items():
            with self.subTest(text=text[:10]):
                self.assertEqual(key_rules.alias_problem(text), expected)
        self.assertEqual(key_rules.alias_problem(key_rules.DEFAULT_ALIAS), "")

    def test_constants_match_the_service(self):
        self.assertEqual(key_rules.ALIAS_MAX, cn.MAX_NAME_CHARS)
        self.assertEqual((key_rules.ALIAS_MAX, key_rules.DEFAULT_ALIAS, key_rules.SECRET_MIN), (40, "기본", 8))


class SecretBoxTest(unittest.TestCase):
    def test_take_returns_the_texts_once_and_leaves_the_box_empty(self):
        box = keys.SecretBox().put("access_key", KEY).put("other", OTHER)
        self.assertEqual((len(box), bool(box), box.names()), (2, True, ("access_key", "other")))
        taken = box.take()
        self.assertEqual(taken, {"access_key": KEY, "other": OTHER})
        self.assertEqual((len(box), bool(box), box.names(), box.take()), (0, False, (), {}))
        taken["access_key"] = "바뀜"
        self.assertEqual(box.take(), {})                                                 # 꺼낸 사본을 바꿔도 통은 그대로 비어 있다

    def test_discard_empties_the_box(self):
        box = keys.SecretBox().put("access_key", KEY)
        box.discard()
        self.assertEqual((len(box), box.take()), (0, {}))

    def test_nothing_about_the_box_shows_the_text(self):
        box = keys.SecretBox().put("access_key", KEY)
        for shown in (repr(box), str(box), format(box), f"{box}", "%s" % box, "%r" % box):
            self.assertEqual(leak.text_hits(shown, NEEDLES), [])
            self.assertIn("가려져 있음", shown)
        self.assertEqual(leak.text_hits(repr([box]) + repr({"x": box}) + repr((box,)), NEEDLES), [])

    def test_copy_and_serialization_are_refused(self):
        import copy
        import pickle
        box = keys.SecretBox().put("access_key", KEY)
        for call in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.subTest(call=call.__name__):
                with self.assertRaises(TypeError):
                    call(box)
        with self.assertRaises(AttributeError):
            box._fields = {}
        with self.assertRaises(AttributeError):
            box.extra = 1

    def test_the_box_compares_by_identity_only(self):
        first, second = keys.SecretBox().put("a", KEY), keys.SecretBox().put("a", KEY)
        self.assertNotEqual(first, second)
        self.assertEqual(first, first)
        self.assertEqual(len({first, second}), 2)


class TablesTest(unittest.TestCase):
    """가짜 공급자의 표(`services._PROVIDER_TABLE`·`_FIELD_TABLE`·`TERMS_PENDING`)가 서비스 표와 같다."""

    def test_providers_match_the_service(self):
        for key, spec in cn.PURPOSES.items():
            with self.subTest(purpose=key):
                expected = tuple((item.key, item.label, spec.entry_cap(item.key), item.second_key_needs_terms) for item in spec.providers) if spec.takes_keys and not spec.legacy_to else ()
                self.assertEqual(tuple(services._PROVIDER_TABLE.get(key, ())), expected)

    def test_fields_match_the_service(self):
        for key, spec in cn.PURPOSES.items():
            if not spec.takes_keys or spec.legacy_to:
                continue
            with self.subTest(purpose=key):
                self.assertEqual(tuple(services._FIELD_TABLE[key]), tuple((item.name, item.label, item.min_len) for item in spec.fields))

    def test_the_terms_pending_purposes_are_the_service_ones_that_never_call_before_the_terms_are_known(self):
        pending = {key for key, spec in cn.PURPOSES.items() if any(item.fail_closed for item in spec.providers)}
        self.assertEqual(set(services.TERMS_PENDING), pending)
        self.assertEqual(services.TERMS_PENDING, ("naver_apihub",))

    def test_the_sample_marks_what_can_be_tested_and_why_not(self):
        by_key = {info.key: info for info in services.sample_connections()}
        self.assertEqual({key: (info.can_test, info.test_blocked) for key, info in by_key.items()},
                         {"naver_apihub": (False, "terms"), "naver_searchad": (False, ""), "image_provider": (True, ""), "ai_assist": (False, ""), "blogger": (False, ""), "github_repo": (False, "")})
        self.assertEqual(by_key["github_repo"].providers, ())
        for info in by_key.values():
            for entry in info.entries:
                self.assertTrue(entry.ref.startswith("sample-"))


class ReadOnlyProviderTest(unittest.TestCase):
    def test_a_read_only_provider_has_no_key_actions_and_the_card_is_the_old_card(self):
        runner = jobs.JobRunner()
        provider = services.FakeConnectionsProvider()
        state = app_state.AppState(services.FakeHomeProvider(), connections=provider, runner=runner)
        state.apply_connections(provider.load_connections(lambda *_: None, lambda: False))
        controller = state.keys
        self.assertFalse(controller.writable)
        view = state.settings_view()
        self.assertEqual((view["writable"], view["notice"], view["busy"], view["keys_note"], view["section"]["desc"]), (False, None, False, T["conn_keys_note"], T["conn_desc"]))
        for group in view["groups"]:
            for card in group["cards"]:
                self.assertIsNone(card["keys"])
        box = box_for()
        for starter in (lambda: controller.start_add("image_provider", "unsplash", "기본", box, False), lambda: controller.start_remove("image_provider", "sample-image_provider-1"),
                        lambda: controller.start_state("image_provider", "sample-image_provider-1", "off"), lambda: controller.start_rename("image_provider", "sample-image_provider-1", "새 이름"),
                        lambda: controller.start_move("image_provider", "sample-image_provider-1", 1), lambda: controller.start_test("image_provider", "sample-image_provider-1")):
            self.assertEqual(starter()[0], "unavailable")
        self.assertEqual(len(box), 0, "시작되지 않은 등록은 통을 비운다")
        self.assertIsNone(controller.open_register("image_provider"))

    def test_the_read_only_view_is_the_same_as_before_the_keys_were_added(self):
        provider = services.FakeConnectionsProvider()
        data = provider.load_connections(lambda *_: None, lambda: False)
        plain = settings_view.build_settings_view(data, "normal")
        controller = keys_view.KeysController(provider, jobs.JobRunner(), lambda: data)
        self.assertEqual(settings_view.build_settings_view(data, "normal", keys=controller), plain)


class CardTest(unittest.TestCase):
    def cards(self, env):
        return {card["key"]: card["keys"] for group in env.state.settings_view()["groups"] for card in group["cards"]}

    def test_every_key_taking_card_has_keys_and_the_github_card_has_none(self):
        env = Env()
        cards = self.cards(env)
        self.assertIsNone(cards["github_repo"])
        for key in ("naver_apihub", "naver_searchad", "image_provider", "ai_assist", "blogger"):
            self.assertIsNotNone(cards[key], key)

    def test_a_card_without_keys_says_not_connected_and_that_keys_are_not_needed_and_still_offers_the_registration(self):
        env = Env(scenario="not_connected")
        card = self.cards(env)["naver_apihub"]
        self.assertEqual((card["rows"], card["none"]), ([], "연결 안 됨 — 키 없이도 쓸 수 있어요"))
        self.assertEqual((card["register"]["enabled"], card["register"]["reason"], card["register"]["text"]), (True, "", "키 등록"))
        self.assertEqual(card["register"]["a11y"], "NAVER API HUB 검색어 트렌드 키 등록")

    def test_one_key_services_are_full_with_one_key_and_say_why_with_the_number(self):
        env = Env()
        cards = self.cards(env)
        self.assertEqual(cards["naver_apihub"]["register"]["enabled"], False)
        self.assertEqual(cards["naver_apihub"]["register"]["reason"], "NAVER API HUB 검색어 트렌드는 키를 1개까지만 둘 수 있어요. 바꾸려면 기존 키를 먼저 지워 주세요.")
        self.assertEqual(cards["image_provider"]["register"]["enabled"], True)                  # 다른 제공자(Pexels·Pixabay)의 자리가 남아 있다
        env.run(lambda **cb: env.controller.start_add("image_provider", "pexels", "펙셀스", box_for(), False, **cb))
        env.run(lambda **cb: env.controller.start_add("image_provider", "pixabay", "픽사베이", box_for(), False, **cb))
        full = self.cards(env)["image_provider"]["register"]
        self.assertEqual((full["enabled"], full["reason"]), (False, "이미지 공급자에 둘 수 있는 키 자리가 모두 찼어요. 바꾸려면 기존 키를 먼저 지워 주세요."))

    def test_a_row_shows_name_state_badge_with_text_priority_provider_last_success_and_last_error(self):
        env = Env()
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "첫째", box_for("ai_assist"), False, **cb))
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "둘째", box_for("ai_assist", OTHER), True, **cb))
        rows = self.cards(env)["ai_assist"]["rows"]
        self.assertEqual([row["name"] for row in rows], ["첫째", "둘째"])
        self.assertEqual([[badge["text"] for badge in row["badges"]] for row in rows], [["사용", "우선순위 1"], ["사용", "우선순위 2"]])
        self.assertEqual([badge["tone"] for badge in rows[0]["badges"]], ["ok", "muted"])
        self.assertEqual(rows[0]["lines"], ["마지막 성공: 아직 없어요"])
        env.run(lambda **cb: env.controller.start_state("ai_assist", rows[1]["ref"], "standby", **cb))
        rows = self.cards(env)["ai_assist"]["rows"]
        self.assertEqual([badge["text"] for badge in rows[1]["badges"]], ["예비", "우선순위 2"])
        self.assertEqual(rows[1]["badges"][0]["tone"], "info")
        for row in rows:
            for badge in row["badges"]:
                self.assertTrue(badge["text"].strip(), "상태 배지는 색만이 아니라 글자를 함께 보인다")

    def test_last_success_time_is_shown_in_korean_time_and_the_last_error_in_an_easy_sentence(self):
        self.assertEqual(keys_view.when_text("2026-11-07T05:20:00Z"), "2026-11-07 14:20")
        self.assertEqual((keys_view.when_text(""), keys_view.when_text("엉뚱한 글"), keys_view.when_text(None)), ("", "", ""))
        env = Env()
        info = env.info("image_provider")
        entry = info.entries[0]
        for check, text in (("ok", "마지막 확인: 연결을 확인했어요"), ("auth_failed", "마지막 오류: 서비스가 키를 거절했어요. 키를 다시 확인해 주세요."), ("error", "마지막 오류: 연결을 확인하지 못했어요. 잠시 뒤 다시 시험해 보세요.")):
            row = env.controller.row_vm(info, services.EntryInfo(entry.name, "active", True, entry.ref, "unsplash", "2026-11-07T05:20:00Z", check, 1), 0, 1)
            self.assertIn("마지막 성공: 2026-11-07 14:20", row["lines"])
            self.assertIn(text, row["lines"])
            self.assertEqual(leak.text_hits(" ".join(row["lines"]), ["auth_failed", "error"]), [] if check != "error" else [])
        missing = env.controller.row_vm(info, services.EntryInfo("키", "active", False, "x", "unsplash"), 0, 1)
        self.assertIn("보관소에서 이 키를 찾지 못했어요. 지우고 다시 등록해 주세요.", missing["lines"])

    def test_the_actions_of_a_row_follow_the_rules_of_its_service(self):
        env = Env()
        def keys_of(purpose, index=0):
            return [action["key"] for action in self.cards(env)[purpose]["rows"][index]["actions"]]
        self.assertEqual(keys_of("naver_apihub"), ["test", "state:off", "rename", "delete"])                  # 키 하나·전환 없음 → 예비 없음, 순서 없음
        self.assertEqual(keys_of("naver_searchad", 0), ["test", "state:standby", "state:off", "up", "down", "rename", "delete"])         # 예시에는 항목이 둘이고 전환 규칙이 한도·일시 오류라 예비와 순서 단추가 있다
        self.assertIn("state:off", keys_of("image_provider"))
        self.assertNotIn("state:standby", keys_of("image_provider"))
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "가", box_for("ai_assist"), False, **cb))
        self.assertEqual(keys_of("ai_assist"), ["test", "state:standby", "state:off", "rename", "delete"])          # 둘 이상 둘 수 있는 서비스는 예비가 있다(항목이 하나면 순서 단추 없음)
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "나", box_for("ai_assist", OTHER), True, **cb))
        self.assertEqual(keys_of("ai_assist", 0), ["test", "state:standby", "state:off", "up", "down", "rename", "delete"])

    def test_up_is_off_for_the_first_row_and_down_for_the_last_with_a_reason(self):
        env = Env()
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "가", box_for("ai_assist"), False, **cb))
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "나", box_for("ai_assist", OTHER), True, **cb))
        rows = self.cards(env)["ai_assist"]["rows"]
        first = {action["key"]: action for action in rows[0]["actions"]}
        last = {action["key"]: action for action in rows[1]["actions"]}
        self.assertEqual((first["up"]["enabled"], first["up"]["reason"], first["down"]["enabled"]), (False, "이미 맨 위예요.", True))
        self.assertEqual((last["down"]["enabled"], last["down"]["reason"], last["up"]["enabled"]), (False, "이미 맨 아래예요.", True))

    def test_every_action_has_a_name_that_says_what_and_for_which_key(self):
        env = Env()
        for card in self.cards(env).values():
            if card is None:
                continue
            for row in card["rows"]:
                for action in row["actions"]:
                    self.assertTrue(action["text"] and action["a11y"].endswith(row["name"]), action)
                    self.assertIn(action["text"], action["a11y"])
                    self.assertEqual(action["enabled"], not action["reason"], "꺼진 행동은 까닭 문장을 가진다")

    def test_the_test_button_is_off_with_the_reason_when_there_is_no_calling_code_or_the_terms_are_unknown(self):
        env = Env()
        prep = {action["key"]: action for action in self.cards(env)["naver_searchad"]["rows"][0]["actions"]}["test"]
        self.assertEqual((prep["enabled"], prep["reason"]), (False, "아직 시험할 수 없어요(준비 중). 이 서비스는 아직 실제 연결 기능이 없어요."))
        terms = {action["key"]: action for action in self.cards(env)["naver_apihub"]["rows"][0]["actions"]}["test"]
        self.assertEqual((terms["enabled"], terms["reason"]), (False, "이용 약관을 확인하기 전이라 연결 시험을 하지 않아요."))
        ready = {action["key"]: action for action in self.cards(env)["image_provider"]["rows"][0]["actions"]}["test"]
        self.assertEqual((ready["enabled"], ready["reason"]), (True, ""))

    def test_without_a_key_store_registration_deletion_rename_and_test_are_off_but_the_page_is_fine(self):
        env = Env(store_ready=False)
        cards = self.cards(env)
        self.assertEqual(cards["naver_apihub"]["store_note"], {"title": "이 컴퓨터에서는 키 저장소를 쓸 수 없어요.", "why": T["keys_store_missing_why"]})
        for key in ("naver_apihub", "image_provider"):
            self.assertEqual((cards[key]["register"]["enabled"], cards[key]["register"]["reason"]), (False, "이 컴퓨터에서는 키 저장소를 쓸 수 없어요."))
            actions = {action["key"]: action for action in cards[key]["rows"][0]["actions"]}
            for name in ("test", "rename", "delete"):
                self.assertEqual((actions[name]["enabled"], actions[name]["reason"]), (False, "이 컴퓨터에서는 키 저장소를 쓸 수 없어요."), (key, name))
            self.assertTrue(actions["state:off"]["enabled"])                                  # 파일만 바꾸는 행동은 그대로
        box = box_for()
        self.assertEqual(env.controller.start_add("image_provider", "pexels", "펙", box, False)[0], "unavailable")
        self.assertEqual(len(box), 0)
        self.assertEqual(env.provider.writes, [])

    def test_a_card_with_a_store_is_not_marked_unavailable(self):
        env = Env()
        for card in self.cards(env).values():
            if card is not None:
                self.assertIsNone(card["store_note"])

    def test_legacy_entries_can_only_be_deleted_and_never_registered(self):
        info = services.PurposeInfo("naver_openapi", "옛 항목", legacy=True, entries=(services.EntryInfo("옛 키", "active", True, "legacy-1", "", "", "", 1),), providers=())
        data = services.ConnectionsData(purposes=(info,), store_ready=True)
        controller = keys_view.KeysController(keys.FakeKeysProvider(), jobs.JobRunner(), lambda: data)
        card = controller.card_keys(info)
        self.assertEqual([action["key"] for action in card["rows"][0]["actions"]], ["delete"])
        self.assertIsNone(card["register"])
        self.assertEqual(card["none"], "")


class FlowTest(unittest.TestCase):
    def test_add_runs_on_a_worker_thread_with_the_box_and_nothing_else(self):
        env = Env(scenario="not_connected")
        thread = []
        original = env.provider.add_key

        def spy(*args, **kwargs):
            thread.append(threading.current_thread())
            return original(*args, **kwargs)
        env.provider.add_key = spy
        status, (kind, outcome) = env.run(lambda **cb: env.controller.start_add("image_provider", "unsplash", "  내   별칭 ", box_for(), False, **cb))
        self.assertEqual((status, kind, outcome.kind), ("started", "ok", "added"))
        self.assertNotEqual(thread[0], threading.main_thread())
        self.assertEqual(env.controller.notice, ("ok", T["keys_ok_added"]))
        self.assertEqual([row.name for row in env.info("image_provider").entries], ["내 별칭"])                  # 별칭은 다듬어 서비스에 간다
        self.assertEqual(env.provider.writes, ["add"])

    def test_the_second_click_while_one_is_running_does_nothing_and_empties_its_box(self):
        env = Env(scenario="not_connected", delay=0.4)
        started = []
        first = box_for()
        status, job = env.controller.start_add("image_provider", "unsplash", "첫째", first, False, on_done=lambda *_: started.append("done"))
        self.assertEqual(status, "started")
        self.assertTrue(env.controller.busy)
        second = box_for("image_provider", OTHER)
        self.assertEqual(env.controller.start_add("image_provider", "pexels", "둘째", second, False)[0], "busy")
        self.assertEqual(len(second), 0)
        self.assertEqual(env.controller.start_remove("image_provider", "sample-image_provider-1")[0], "busy")
        self.assertEqual(env.controller.start_rename("image_provider", "sample-image_provider-1", "새 이름")[0], "busy")
        self.assertEqual(env.controller.start_state("image_provider", "sample-image_provider-1", "off")[0], "busy")
        self.assertEqual(env.controller.start_move("image_provider", "sample-image_provider-1", 1)[0], "busy")
        self.assertEqual(env.controller.start_test("image_provider", "sample-image_provider-1")[0], "busy")
        for action in env.controller.card_keys(env.info("image_provider"))["rows"] or []:
            self.assertFalse(any(item["enabled"] for item in action["actions"]), "쓰는 동안 모든 단추가 꺼진다")
        job.join(10)
        self.assertEqual(env.provider.writes, ["add"], "두 번째 클릭은 공급자를 부르지 않았다")
        self.assertEqual(len(first), 0)
        env.controller.apply_write_ok(keys.KeyOutcome("added"))

    def test_invalid_input_never_calls_the_provider_and_empties_the_box(self):
        env = Env(scenario="not_connected")
        env.run(lambda **cb: env.controller.start_add("image_provider", "unsplash", "기본", box_for(), False, **cb))
        cases = (("", "unsplash", False, {"name": "empty"}), ("기본", "pexels", False, {"name": "duplicate"}), (KEY, "pexels", False, {"name": "keyish"}), ("긴" * 41, "pexels", False, {"name": "long"}),
                 ("새 별칭", "unsplash", True, {"provider": "full"}), ("새 별칭", "없는 제공자", True, {"provider": "full"}))
        for name, provider, terms, expected in cases:
            with self.subTest(name=name[:6], provider=provider):
                env.provider.writes.clear()
                box = box_for("image_provider", OTHER)
                status, problems = env.controller.start_add("image_provider", provider, name, box, terms)
                self.assertEqual(status, "invalid")
                self.assertLessEqual(set(expected.items()), set(problems.items()))                 # 이 문제가 들어 있다(Unsplash 가 이미 차 있어 다른 문제가 함께 있을 수 있다)
                self.assertEqual((len(box), env.provider.writes), (0, []))

    def test_the_second_key_of_the_same_service_needs_the_terms_before_anything_starts(self):
        env = Env(scenario="not_connected")
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "가", box_for("ai_assist"), False, **cb))
        box = box_for("ai_assist", OTHER)
        self.assertEqual(env.controller.start_add("ai_assist", "gemini", "나", box, False), ("invalid", {"terms": "required"}))
        self.assertEqual((len(box), env.provider.writes), (0, ["add"]))
        self.assertEqual(env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "나", box_for("ai_assist", OTHER), True, **cb))[1][0], "ok")

    def test_a_different_provider_of_the_same_purpose_and_blogger_channels_ask_no_terms(self):
        env = Env(scenario="not_connected")
        self.assertEqual(env.run(lambda **cb: env.controller.start_add("image_provider", "unsplash", "가", box_for(), False, **cb))[1][0], "ok")
        self.assertEqual(env.run(lambda **cb: env.controller.start_add("image_provider", "pexels", "나", box_for("image_provider", OTHER), False, **cb))[1][0], "ok")
        self.assertEqual(env.run(lambda **cb: env.controller.start_add("blogger", "", "한글", box_for("blogger"), False, **cb))[1][0], "ok")
        self.assertEqual(env.run(lambda **cb: env.controller.start_add("blogger", "", "영문", box_for("blogger", OTHER), False, **cb))[1][0], "ok")
        self.assertEqual(env.controller.start_add("blogger", "", "셋째", box_for("blogger"), True)[0], "invalid")

    def test_a_failed_add_keeps_the_alias_and_asks_for_the_key_again_with_the_problems_beside_the_boxes(self):
        env = Env(scenario="not_connected")
        draft = env.controller.open_register("image_provider")
        draft.set_alias("내 별칭")
        short = keys.SecretBox().put("access_key", "x" * 9)                                     # 서비스(가짜)의 최소 길이 16 보다 짧다
        env.run(lambda **cb: env.controller.start_add("image_provider", draft.provider, draft.alias, short, False, **cb))
        self.assertIs(env.controller.draft, draft)
        self.assertEqual((draft.alias, draft.step, draft.problems), ("내 별칭", "input", {"access_key": "min:16"}))
        self.assertEqual(env.controller.notice[0], "error")
        self.assertEqual(env.controller.notice[1], T["keys_fail_invalid"])
        vm = draft.vm()
        self.assertEqual(vm["fields"][0]["error"], "Access Key 칸이 너무 짧아요(최소 16자). 끝까지 복사됐는지 확인해 주세요.")
        self.assertEqual(vm["alias"]["value"], "내 별칭")
        self.assertEqual(env.info("image_provider").entries, services.sample_connections("not_connected")[2].entries)

    def test_a_successful_add_closes_the_draft_and_asks_for_a_new_read(self):
        env = Env(scenario="not_connected")
        env.controller.open_register("image_provider")
        env.run(lambda **cb: env.controller.start_add("image_provider", "unsplash", "기본", box_for(), False, **cb))
        self.assertIsNone(env.controller.draft)
        self.assertEqual(len(env.info("image_provider").entries), 1)                            # 다시 읽은 값에 새 항목이 있다

    def test_remove_rename_state_move_and_test_each_work_and_leave_the_others_alone(self):
        env = Env()
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "가", box_for("ai_assist"), False, **cb))
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "나", box_for("ai_assist", OTHER), True, **cb))
        a, b = [row.ref for row in env.info("ai_assist").entries]
        self.assertEqual(env.run(lambda **cb: env.controller.start_move("ai_assist", b, -1, **cb))[1][1].kind, "moved")
        self.assertEqual([row.name for row in env.info("ai_assist").entries], ["나", "가"])
        self.assertEqual(env.controller.notice, ("ok", T["keys_ok_moved"]))
        self.assertEqual(env.controller.start_move("ai_assist", b, -1)[0], "unavailable")                # 이미 맨 위
        self.assertEqual(env.run(lambda **cb: env.controller.start_state("ai_assist", a, "standby", **cb))[1][1].kind, "state")
        self.assertEqual(env.controller.start_state("ai_assist", a, "standby")[0], "unavailable")         # 이미 그 상태
        self.assertEqual(env.run(lambda **cb: env.controller.start_rename("ai_assist", a, "새 이름", **cb))[1][1].kind, "renamed")
        self.assertEqual(env.controller.start_rename("ai_assist", a, "나")[1], {"name": "duplicate"})
        self.assertEqual(env.controller.start_rename("ai_assist", a, "새  이름")[0], "nothing")           # 다듬으면 같은 이름 — 쓰지 않는다
        self.assertEqual(env.controller.notice, ("info", T["keys_ok_unchanged"]))
        self.assertEqual(env.controller.start_rename("ai_assist", a, "")[1], {"name": "empty"})
        self.assertEqual(env.run(lambda **cb: env.controller.start_remove("ai_assist", b, **cb))[1][1].kind, "removed")
        self.assertEqual([(row.name, row.state, row.order) for row in env.info("ai_assist").entries], [("새 이름", "standby", 1)])
        self.assertEqual(env.controller.notice, ("ok", T["keys_ok_removed"]))

    def test_a_test_result_goes_to_the_row_and_the_file_is_read_again(self):
        for result, text in (("ok", T["keys_test_ok"]), ("auth_failed", T["keys_test_auth"]), ("rate_limited", T["keys_test_limit"]), ("error", T["keys_test_error"])):
            with self.subTest(result=result):
                env = Env(test_result=result)
                ref = env.info("image_provider").entries[0].ref
                status, (kind, outcome) = env.run(lambda **cb: env.controller.start_test("image_provider", ref, **cb))
                self.assertEqual((outcome.kind, outcome.result), ("tested", result))
                row = env.controller.card_keys(env.info("image_provider"))["rows"][0]
                self.assertEqual(row["note"]["text"], text)
                self.assertIsNone(env.controller.notice)
                expected_check = {"ok": "ok", "auth_failed": "auth_failed"}.get(result, "error")
                self.assertEqual(env.info("image_provider").entries[0].check, expected_check)

    def test_a_test_of_a_service_without_calling_code_is_refused_before_the_provider_and_says_getting_ready(self):
        env = Env()
        ref = env.info("naver_searchad").entries[0].ref
        self.assertEqual(env.controller.start_test("naver_searchad", ref)[0], "unavailable")
        self.assertEqual(env.controller.start_test("naver_apihub", env.info("naver_apihub").entries[0].ref)[0], "unavailable")
        self.assertEqual(env.provider.writes, [])
        outcome = env.provider.test_key("naver_searchad", ref, lambda *_: None, lambda: False)
        self.assertEqual((outcome.kind, outcome.result), ("tested", "not_ready"))

    def test_a_failure_shows_an_easy_sentence_by_kind_and_asks_for_a_new_read_only_when_the_list_is_stale(self):
        env = Env()
        controller = env.controller
        for kind, sentence in (("limit", T["keys_fail_limit"]), ("store", T["keys_fail_store"]), ("busy", T["keys_fail_busy"]), ("io", T["keys_fail_io_edit"]), ("disk", T["keys_fail_disk"]), ("other", T["keys_fail_other"])):
            controller.pending = {"kind": "rename", "purpose": "image_provider", "ref": "x"}
            self.assertEqual(controller.apply_write_failed(keys.make_failure(kind, "CODE")), kind)
            self.assertEqual((controller.notice, controller.reload_wanted), (("error", sentence), False), kind)
        for kind in ("notfound", "corrupt"):
            controller.pending = {"kind": "remove", "purpose": "image_provider", "ref": "x"}
            controller.apply_write_failed(keys.make_failure(kind, "CODE"))
            self.assertTrue(controller.reload_wanted, kind)
        controller.pending = {"kind": "add", "purpose": "image_provider", "ref": ""}
        controller.apply_write_failed(keys.make_failure("store", "KEY_STORE_UNAVAILABLE", leftover=True))
        self.assertEqual(controller.notice, ("error", T["keys_fail_leftover"]))
        # 키를 새로 넣는 등록의 실패는 '키는 다시 입력해 주세요' 까지 말하고, 그 밖의 쓰기(지우기·상태·순서·별칭)는 다시 입력할 키가 없다
        for kind, adding, editing in (("io", "keys_fail_io", "keys_fail_io_edit"), ("invalid", "keys_fail_invalid", "keys_fail_invalid_edit")):
            controller.pending = {"kind": "add", "purpose": "image_provider", "ref": ""}
            controller.apply_write_failed(keys.make_failure(kind, "CODE"))
            self.assertEqual(controller.notice, ("error", T[adding]), kind)
            self.assertIn("다시 입력", T[adding])
            for work in ("remove", "state", "move", "rename", "test"):
                controller.pending = {"kind": work, "purpose": "image_provider", "ref": "x"}
                controller.apply_write_failed(keys.make_failure(kind, "CODE"))
                # 의도적 갱신(독립 검증 M1): 지우기의 저장 실패(io)는 키 저장소의 키를 이미 지운 뒤일 수 있어 '바뀐 것은 없어요' 문장이 아니라 따로 정한 문장이다(글자까지는 아래 `DeleteFailureTest` 가 못박는다)
                expected = T["keys_fail_remove_io"] if (kind, work) == ("io", "remove") else T[editing]
                self.assertEqual(controller.notice, ("error", expected), (kind, work))
                self.assertNotIn("다시 입력", expected)

    def test_an_unexpected_exception_gives_a_plain_sentence_without_its_name_or_content(self):
        env = Env()
        env.controller.pending = {"kind": "add", "purpose": "image_provider", "ref": ""}
        env.controller.reloading = True
        name = env.controller.apply_unexpected(ValueError("내용 " + KEY))
        self.assertEqual((name, env.controller.notice), ("ValueError", ("error", T["keys_fail_other"])))
        self.assertFalse(env.controller.reloading, "새 값을 기다리다 슬롯이 죽어도 단추가 영영 꺼져 있지 않다")
        self.assertEqual(leak.graph_hits(env.controller.notice, NEEDLES), [])
        self.assertFalse(env.controller.busy)

    def test_a_foreign_failure_is_shown_as_the_plain_other_sentence(self):
        env = Env()
        env.controller.pending = {"kind": "remove", "purpose": "image_provider", "ref": "x"}
        env.controller.apply_write_failed(jobs.JobFailure("내용 " + KEY, code="X"))
        self.assertEqual(env.controller.notice, ("error", T["keys_fail_other"]))


class GoneThenFails(keys.FakeKeysProvider):
    """삭제가 '키 저장소의 키는 지워졌는데 파일 쓰기에서 실패' 하도록 흉내 내는 가짜 공급자 — 첫 삭제만 항목을 남기고(키가 없다고 표시) 실패하고, 두 번째부터는 보통 가짜 공급자처럼 지운다."""

    def __init__(self, kind, **kwargs):
        super().__init__(**kwargs)
        self.kind, self.failed_once = kind, False

    def remove_key(self, purpose, ref, progress, cancelled):
        if self.failed_once:
            return super().remove_key(purpose, ref, progress, cancelled)
        self.failed_once = True
        self._enter("remove", cancelled)
        with self._lock:
            entries, index = self._find(purpose, ref)
            entries[index] = dataclasses.replace(entries[index], key_found=False)
            self._touched.add(purpose)
        raise keys.make_failure(self.kind, "SAMPLE_X")


class DeleteFailureTest(unittest.TestCase):
    """독립 검증 M1 — 삭제 도중 `connections.json` 쓰기가 실패하면 키 저장소의 키는 이미 지워졌을 수 있다(서비스는 저장소를 먼저 지운다). 오류 종류(`io`·`disk`)만으로는 '키가 이미 지워졌다' 와
    '아무것도 안 바뀌었다(파일을 읽거나 잠그는 앞 단계에서 실패)' 를 구별할 수 없으므로 화면은 '바뀐 것은 없어요' 라고 하지 않고 어느 쪽이어도 참인 문장을 보이며 목록을 바로 다시 읽는다.
    다른 쓰기(등록·상태·순서·별칭·시험)의 저장 실패 문장은 사실이라 그대로다. 문장은 자기 상수를 돌려 쓰지 않으려고 여기에 글자 그대로 적었다."""
    REMOVE = {
        "io": "키를 지우다가 연결 설정 파일에 저장하지 못했어요. 키가 이미 지워졌을 수도 있어서 목록을 다시 읽어 드릴게요. 그 줄에 '보관소에서 이 키를 찾지 못했어요' 가 보이면 삭제를 한 번 더 눌러 정리해 주세요. 키가 그대로면 잠시 뒤 다시 지워 주세요.",
        "disk": "키를 지우다가 디스크 공간이 모자라 저장하지 못했어요. 키가 이미 지워졌을 수도 있어서 목록을 다시 읽어 드릴게요. 그 줄에 '보관소에서 이 키를 찾지 못했어요' 가 보이면 삭제를 한 번 더 눌러 정리해 주세요. 키가 그대로면 공간을 만든 뒤 다시 지워 주세요.",
    }
    IO_ADD = "연결 설정 파일에 저장하지 못했어요. 바뀐 것은 없어요. 키는 보관소에 남지 않았으니 다시 입력해 주세요."
    IO_EDIT = "연결 설정 파일에 저장하지 못했어요. 바뀐 것은 없어요. 잠시 뒤 다시 시도해 주세요."
    DISK = "디스크 공간이 모자라 저장하지 못했어요. 바뀐 것은 없어요. 공간을 만든 뒤 다시 시도해 주세요."
    ROW_MISSING = "보관소에서 이 키를 찾지 못했어요. 지우고 다시 등록해 주세요."

    @staticmethod
    def failed(work, kind):
        controller = Env().controller
        controller.pending = {"kind": work, "purpose": "image_provider", "ref": "x"}
        controller.apply_write_failed(keys.make_failure(kind, "CODE"))
        return controller

    def test_a_failed_save_while_deleting_asks_for_a_new_read_and_never_says_nothing_changed(self):
        for kind, sentence in self.REMOVE.items():
            with self.subTest(kind=kind):
                controller = self.failed("remove", kind)
                self.assertEqual(controller.notice, ("error", sentence))
                self.assertTrue(controller.reload_wanted)
                self.assertIsNone(controller.pending)
                for untrue in ("바뀐 것은 없어요", "바뀌지 않았어요", "아무것도"):
                    self.assertNotIn(untrue, sentence)

    def test_the_sentences_are_plain_korean_without_error_names_paths_or_key_shapes(self):
        for kind, sentence in self.REMOVE.items():
            with self.subTest(kind=kind):
                self.assertRegex(sentence, r"^[가-힣 .']+$")                              # 한글·공백·마침표·작은따옴표뿐 — 영문 오류 글·경로·코드·숫자·키 모양이 들어갈 자리가 없다
                self.assertEqual(leak.text_hits(sentence, NEEDLES), [])
                self.assertIsNone(INTERNAL.search(sentence))
                for word in FORBIDDEN:
                    self.assertNotIn(word, sentence)

    def test_the_sentences_point_at_the_row_text_and_the_button_that_really_exist(self):
        env = Env()
        info = env.info("image_provider")
        gone = dataclasses.replace(info.entries[0], key_found=False)
        row = env.controller.row_vm(info, gone, 0, 1)
        self.assertIn(self.ROW_MISSING, row["lines"])
        delete = next(item for item in row["actions"] if item["key"] == "delete")
        self.assertEqual((delete["text"], delete["enabled"]), ("삭제", True))                    # 키를 찾지 못한 행에서도 삭제는 눌린다
        quoted = "'" + self.ROW_MISSING.split(".")[0] + "'"
        for kind, sentence in self.REMOVE.items():
            self.assertIn(quoted, sentence, kind)
            self.assertIn("삭제를 한 번 더 눌러", sentence, kind)
        self.assertEqual(env.controller.delete_dialog(info, gone)["ok"], "지우기")                 # 이어서 나오는 확인창의 단추

    def test_the_other_writes_keep_their_true_sentences_and_do_not_ask_for_a_new_read_on_a_save_failure(self):
        for work in ("add", "state", "move", "rename", "test"):
            for kind, expected in (("io", self.IO_ADD if work == "add" else self.IO_EDIT), ("disk", self.DISK)):
                with self.subTest(work=work, kind=kind):
                    controller = self.failed(work, kind)
                    self.assertEqual((controller.notice, controller.reload_wanted), (("error", expected), False))

    def test_the_other_failures_of_a_delete_are_as_before(self):
        before = (
            ("store", "키 보관소(Windows 자격 증명 관리자)를 쓰지 못했어요. 아무것도 바뀌지 않았어요. 잠시 뒤 다시 시도해 주세요.", False),
            ("busy", "다른 곳에서 연결 설정을 바꾸는 중이에요. 잠시 뒤 다시 눌러 주세요.", False),
            ("notfound", "그 키는 이미 지워졌거나 바뀌었어요. 목록을 다시 읽어 드릴게요.", True),
            ("corrupt", "연결 설정 파일을 읽지 못했어요. 파일은 고치거나 지우지 않았어요. 아래 진단 정보를 함께 알려 주세요.", True),
            ("invalid", "입력한 내용을 다시 확인해 주세요. 바뀐 것은 없어요.", False),
            ("other", "처리하지 못했어요. 아무것도 바뀌지 않았어요. 다시 시도해도 같으면 진단 정보를 함께 알려 주세요.", False),
        )
        for kind, sentence, reload in before:
            with self.subTest(kind=kind):
                controller = self.failed("remove", kind)
                self.assertEqual((controller.notice, controller.reload_wanted), (("error", sentence), reload))
        controller = Env().controller
        controller.pending = {"kind": "remove", "purpose": "image_provider", "ref": "x"}
        controller.apply_write_failed(None)                                                      # 취소 신호 — 서비스를 부르기 전에 끝난다
        self.assertEqual((controller.notice, controller.reload_wanted), (("error", before[-1][1]), False))

    def test_the_screen_flow_reads_again_shows_the_row_as_not_found_and_a_second_delete_cleans_up(self):
        for kind in ("io", "disk"):
            with self.subTest(kind=kind):
                env = Env(provider=GoneThenFails(kind))
                controller = env.controller
                row_before = controller.card_keys(env.info("image_provider"))["rows"][0]
                self.assertNotIn(self.ROW_MISSING, row_before["lines"])
                ref = row_before["ref"]
                status, (outcome, failure) = env.run(lambda **cb: controller.start_remove("image_provider", ref, **cb))
                self.assertEqual((status, outcome, failure.kind), ("started", "err", kind))
                self.assertEqual(controller.notice, ("error", self.REMOVE[kind]))
                row_after = controller.card_keys(env.info("image_provider"))["rows"][0]
                self.assertEqual(row_after["ref"], ref)
                self.assertIn(self.ROW_MISSING, row_after["lines"], "컨트롤러가 다시 읽게 했으니 새 값의 행이 '키를 찾지 못했어요' 로 보인다")
                self.assertFalse(controller.busy)
                status, (outcome, done) = env.run(lambda **cb: controller.start_remove("image_provider", ref, **cb))
                self.assertEqual((status, outcome, done.kind), ("started", "ok", "removed"))
                self.assertEqual(controller.notice, ("ok", "키를 지웠어요."))
                self.assertEqual(env.info("image_provider").entries, ())


class DraftTest(unittest.TestCase):
    def draft(self, scenario="not_connected", purpose="image_provider"):
        env = Env(scenario=scenario)
        return env, env.controller.open_register(purpose)

    def test_the_draft_starts_with_the_default_alias_and_the_first_provider_with_room(self):
        env, draft = self.draft()
        self.assertEqual((draft.alias, draft.provider, draft.step, draft.terms, draft.problems), ("기본", "unsplash", "input", False, {}))
        env2, draft2 = self.draft("normal")                                                    # Unsplash 가 차 있으면 자리가 남은 첫 제공자
        self.assertEqual(draft2.provider, "pexels")

    def test_the_provider_chips_show_which_ones_are_full(self):
        env, draft = self.draft("normal")
        vm = draft.vm()
        self.assertEqual([(item["key"], item["selected"], item["enabled"]) for item in vm["providers"]], [("unsplash", False, False), ("pexels", True, True), ("pixabay", False, True)])
        self.assertEqual(vm["providers"][0]["reason"], T["keys_reg_provider_full"])
        self.assertFalse(draft.set_provider("unsplash"))
        self.assertTrue(draft.set_provider("pixabay"))
        self.assertEqual(draft.provider, "pixabay")
        self.assertEqual(self.draft("not_connected", "naver_apihub")[1].vm()["providers"], [], "제공자가 하나면 고르는 칸이 없다")

    def test_next_needs_a_good_alias_and_good_boxes_and_only_the_first_problems_are_listed(self):
        env, draft = self.draft()
        draft.set_alias("")
        self.assertFalse(draft.go_confirm({"access_key": "short"}))
        self.assertEqual((draft.step, draft.problems), ("input", {"access_key": "short", "name": "empty"}))
        draft.set_alias("내 별칭")
        self.assertNotIn("name", draft.problems, "별칭을 고치면 그 칸의 문제는 지워진다")
        self.assertFalse(draft.go_confirm({"access_key": "hidden"}))
        self.assertTrue(draft.go_confirm({}))
        self.assertEqual((draft.step, draft.problems), ("confirm", {}))
        draft.back()
        self.assertEqual((draft.step, draft.alias), ("input", "내 별칭"))

    def test_the_same_alias_in_the_service_is_a_problem_before_anything_is_sent(self):
        env, draft = self.draft("normal", "ai_assist")
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "기본", box_for("ai_assist"), False, **cb))
        draft = env.controller.open_register("ai_assist")
        self.assertFalse(draft.go_confirm({}))
        self.assertEqual(draft.problems, {"name": "duplicate"})
        self.assertEqual(draft.vm()["alias"]["error"], T["keys_alias_duplicate"])

    def test_the_confirm_step_shows_the_service_the_provider_and_the_alias_and_never_a_key(self):
        env, draft = self.draft("not_connected", "image_provider")
        draft.set_alias("  내   별칭 ")
        self.assertTrue(draft.go_confirm({}))
        vm = draft.vm()
        self.assertEqual(vm["confirm"]["lines"], ["서비스: 이미지 공급자", "제공자: Unsplash", "별칭: 내 별칭"])
        self.assertEqual(vm["step"], "confirm")
        self.assertEqual(leak.graph_hits(vm, NEEDLES), [])
        self.assertTrue(vm["confirm"]["note"])

    def test_the_terms_box_is_needed_for_the_second_key_of_a_service_and_only_then(self):
        env, draft = self.draft("not_connected", "ai_assist")
        self.assertFalse(draft.needs_terms())
        env.run(lambda **cb: env.controller.start_add("ai_assist", "gemini", "가", box_for("ai_assist"), False, **cb))
        draft = env.controller.open_register("ai_assist")
        draft.set_alias("나")
        self.assertTrue(draft.needs_terms())
        self.assertTrue(draft.go_confirm({}))
        self.assertFalse(draft.can_save())
        self.assertEqual(draft.vm()["buttons"]["save"], {"text": "저장", "enabled": False, "reason": T["keys_fail_terms"]})
        draft.set_terms(True)
        self.assertTrue(draft.can_save())
        self.assertEqual(draft.vm()["confirm"]["terms"]["show"], True)

    def test_a_draft_knows_its_service_and_starts_as_not_handed_to_a_save(self):
        env, draft = self.draft()
        self.assertEqual(draft.purpose, "image_provider")
        self.assertFalse(draft.submitted)

    def test_a_draft_is_kept_when_the_dialog_is_reopened_and_gone_after_close(self):
        env, draft = self.draft()
        draft.set_alias("남는 별칭")
        self.assertIs(env.controller.open_register("image_provider"), draft)
        env.controller.close_register()
        self.assertIsNone(env.controller.draft)
        self.assertEqual(env.controller.open_register("image_provider").alias, "기본")

    def test_the_dialog_does_not_open_while_busy_or_without_a_store_or_without_room(self):
        env = Env(store_ready=False)
        self.assertIsNone(env.controller.open_register("image_provider"))
        env = Env()
        self.assertIsNone(env.controller.open_register("naver_apihub"))                          # 자리가 없다
        self.assertIsNone(env.controller.open_register("github_repo"))                           # 키를 받지 않는다

    def test_delete_and_rename_dialogs_say_what_is_erased_and_that_it_cannot_be_undone(self):
        env = Env()
        info = env.info("image_provider")
        entry = info.entries[0]
        dialog = env.controller.delete_dialog(info, entry)
        self.assertEqual((dialog["title"], dialog["ok"], dialog["cancel"]), ("키를 지울까요?", "지우기", "취소"))
        for phrase in (entry.name, "Windows 자격 증명 관리자", "되돌릴 수 없어요", "다른 키나 블로그 글에는 영향이 없어요"):
            self.assertIn(phrase, dialog["body"])
        rename = env.controller.rename_dialog(info, entry)
        self.assertEqual((rename["title"], rename["value"], rename["max"]), ("별칭 바꾸기", entry.name, 40))
        self.assertIn(entry.name, rename["body"])
        self.assertIn("키 자체는 바뀌지 않아요", rename["body"])

    def test_a_key_shaped_name_in_a_file_is_masked_in_every_sentence(self):
        shaped = "ghp" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        info = services.PurposeInfo("ai_assist", "AI 보조", entries=(services.EntryInfo(shaped, "active", True, "r1", "gemini", "", "", 1),), providers=(services.ProviderInfo("gemini", "Gemini", 3),), max_entries=3)
        data = services.ConnectionsData(purposes=(info,), store_ready=True)
        controller = keys_view.KeysController(keys.FakeKeysProvider(), jobs.JobRunner(), lambda: data)
        shown = repr(controller.card_keys(info)) + repr(controller.delete_dialog(info, info.entries[0])) + repr(controller.rename_dialog(info, info.entries[0])["body"])
        self.assertNotIn(shaped, shown)
        self.assertNotIn(shaped[:20], shown)


class NoLeakTest(unittest.TestCase):
    """키가 컨트롤러·상태·뷰모델·작업 일감·실패 객체 어디에도 없다 — 전수."""

    def test_after_every_kind_of_write_nothing_the_app_holds_contains_the_key_or_a_piece_of_it(self):
        env = Env(scenario="not_connected")
        draft = env.controller.open_register("image_provider")
        views = [draft.vm()]
        draft.set_alias("기본")
        self.assertTrue(draft.go_confirm({}))
        views.append(draft.vm())
        env.run(lambda **cb: env.controller.start_add("image_provider", draft.provider, draft.alias, box_for(), False, **cb))
        env.run(lambda **cb: env.controller.start_add("image_provider", "pexels", "다시", box_for("image_provider", OTHER), False, **cb))
        env.run(lambda **cb: env.controller.start_add("image_provider", "pexels", "중복", box_for("image_provider", OTHER), False, **cb))        # 자리 없음 → invalid
        short = keys.SecretBox().put("access_key", KEY[:9])
        status, outcome = env.run(lambda **cb: env.controller.start_add("image_provider", "pixabay", "짧음", short, False, **cb))
        self.assertEqual(outcome[0], "err")
        ref = env.info("image_provider").entries[0].ref
        env.run(lambda **cb: env.controller.start_rename("image_provider", ref, "새 이름", **cb))
        env.run(lambda **cb: env.controller.start_test("image_provider", ref, **cb))
        env.run(lambda **cb: env.controller.start_state("image_provider", ref, "off", **cb))
        env.run(lambda **cb: env.controller.start_remove("image_provider", ref, **cb))
        views.append(env.state.settings_view())
        env.runner.join_all(5)
        self.assertEqual(leak.graph_hits(env.state, NEEDLES), [], "상태 전체(컨트롤러·작업 틀·일감·공급자)")
        self.assertEqual(leak.graph_hits(views, NEEDLES), [])
        self.assertEqual(leak.graph_hits(env.controller.notice, NEEDLES), [])
        self.assertEqual(leak.graph_hits(env.controller.row_notes, NEEDLES), [])
        self.assertEqual(leak.graph_hits(env.provider, NEEDLES), [], "가짜 공급자도 키를 보관하지 않는다")

    def test_the_job_closure_holds_only_an_empty_box_after_the_job(self):
        env = Env(scenario="not_connected")
        box = box_for()
        status, outcome = env.run(lambda **cb: env.controller.start_add("image_provider", "unsplash", "기본", box, False, **cb))
        job = env.runner.job(keys_view.WRITE_KEY)
        self.assertEqual(len(box), 0)
        self.assertEqual(leak.graph_hits(job, NEEDLES), [])
        self.assertEqual(leak.graph_hits(job.work, NEEDLES), [])

    def test_a_provider_that_fails_before_taking_the_box_still_leaves_the_box_empty_and_the_job_record_clean(self):
        """공급자가 통을 꺼내지 않고 죽어도(예기치 못한 오류 — 오류 글에 키가 들어 있다고 해도) 일이 끝난 뒤의 일 기록(`runner` 가 들고 있다)에 키가 남지 않는다."""
        class Dies(keys.FakeKeysProvider):
            def add_key(self, purpose, provider, name, secret, terms_ack, progress, cancelled):
                raise ValueError("내용 " + KEY)
        env = Env(Dies(scenario="not_connected"))
        box = box_for()
        status, (kind, failure) = env.run(lambda **cb: env.controller.start_add("image_provider", "unsplash", "기본", box, False, **cb))
        self.assertEqual((status, kind), ("started", "err"))
        self.assertEqual(len(box), 0)
        self.assertEqual(leak.graph_hits(env.state, NEEDLES), [])
        self.assertEqual(leak.graph_hits(env.runner.job(keys_view.WRITE_KEY), NEEDLES), [])
        self.assertEqual(env.controller.notice, ("error", T["keys_fail_other"]))
        self.assertEqual(leak.error_hits(failure, NEEDLES), [])

    def test_failure_objects_of_the_fake_provider_carry_no_key_in_text_or_frames(self):
        env = Env(scenario="not_connected")
        for name, secret, terms in (("", KEY, False), ("짧음", KEY[:9], False)):
            box = keys.SecretBox().put("access_key", secret)
            try:
                env.provider.add_key("image_provider", "unsplash", name, box, terms, lambda *_: None, lambda: False)
            except keys.KeyFailure as failure:
                self.assertEqual(leak.error_hits(failure, NEEDLES), [], name)
                self.assertEqual(len(box), 0)
            else:
                self.fail("실패해야 한다")

    def test_a_key_pasted_into_the_alias_box_is_refused_and_not_kept_anywhere(self):
        env = Env(scenario="not_connected")
        draft = env.controller.open_register("image_provider")
        draft.set_alias("내 키 " + KEY)
        self.assertFalse(draft.go_confirm({}))
        self.assertEqual((draft.problems, draft.alias), ({"name": "keyish"}, ""))
        draft.set_alias(KEY)
        box = box_for()
        self.assertEqual(env.controller.start_add("image_provider", "unsplash", KEY, box, False), ("invalid", {"name": "keyish"}))
        self.assertEqual((len(box), draft.alias, env.provider.writes), (0, "", []))
        self.assertEqual(leak.graph_hits((draft, draft.vm(), env.state), NEEDLES), [])
        self.assertEqual(draft.vm()["alias"]["error"], T["keys_alias_keyish"])

    def test_view_models_show_no_internal_names_in_any_visible_text(self):
        env = Env()
        view = env.state.settings_view()
        shown = []

        def walk(value, key=""):
            if isinstance(value, dict):
                for name, item in value.items():
                    walk(item, name)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item, key)
            elif isinstance(value, str) and key in ("text", "reason", "a11y", "name", "none", "title", "why", "lines", "desc", "hint", "label", "error", "policy", "note", "summary", "state_line", "missing"):
                shown.append(value)
        walk(view)
        self.assertGreater(len(shown), 50)
        for text in shown:
            self.assertIsNone(INTERNAL.search(text), text)


class SettingsViewTest(unittest.TestCase):
    def test_a_writable_provider_changes_only_the_texts_the_notice_and_the_card_keys(self):
        env = Env()
        view = env.state.settings_view()
        data = env.state.conn_data
        plain = settings_view.build_settings_view(data, "normal")
        self.assertTrue(view["writable"])
        self.assertEqual((view["section"]["desc"], view["keys_note"]), (T["conn_desc_write"], T["conn_keys_note_write"]))
        for text in (view["section"]["desc"], view["keys_note"]):
            self.assertNotIn("읽기만", text)
            self.assertNotIn("아직 없어요", text)
        policies = {}
        for group, old in zip(view["groups"], plain["groups"]):
            for card, old_card in zip(group["cards"], old["cards"]):
                # `policy`(키 전환 안내)는 쓰는 공급자에서 제공자별 상한(운영자 정책) 기준이다 — 읽기 전용 카드의 '용도당 최대 3개' 는 읽을 때 천장 값이라 Blogger·검색광고에서는 실제 등록 상한과 달랐다.
                self.assertEqual({key: value for key, value in card.items() if key not in ("keys", "policy")}, {key: value for key, value in old_card.items() if key not in ("keys", "policy")})
                policies[card["key"]] = (card["policy"], old_card["policy"])
        self.assertEqual(policies["blogger"], ("예비: 한도·일시 오류일 때만 다음 키로 넘어가요(용도당 최대 2개)", "예비: 한도·일시 오류일 때만 다음 키로 넘어가요(용도당 최대 3개)"))
        self.assertEqual(policies["naver_searchad"], (T["policy_single"], "예비: 한도·일시 오류일 때만 다음 키로 넘어가요(용도당 최대 3개)"))
        for same in ("naver_apihub", "image_provider", "ai_assist", "github_repo"):
            self.assertEqual(policies[same][0], policies[same][1], same)                       # 이 넷은 둘이 같다(천장과 상한의 합이 같거나 안내가 없다)
        for key, (shown, _old) in policies.items():
            if key == "ai_assist":
                self.assertIn("최대 3개", shown)                                                  # 한 제공자(Gemini)가 3개까지다
            else:
                self.assertNotIn("최대 3개", shown, key)                                          # 'NAVER API HUB 를 뺀 모든 서비스에 3개' 라는 공통 규칙은 쓰지 않는다(운영자 정책)

    def test_the_last_result_is_shown_as_a_notice_with_its_level(self):
        env = Env(scenario="not_connected")
        env.run(lambda **cb: env.controller.start_add("image_provider", "unsplash", "기본", box_for(), False, **cb))
        self.assertEqual(env.state.settings_view()["notice"], {"level": "ok", "text": T["keys_ok_added"]})
        env.controller.notice = ("error", T["keys_fail_other"])
        self.assertEqual(env.state.settings_view()["notice"], {"level": "error", "text": T["keys_fail_other"]})

    def test_the_buttons_stay_off_while_the_new_value_is_read_after_a_write_until_it_arrives_or_the_read_ends_any_way(self):
        """쓰기가 끝나도 새 값을 받기 전에는 낡은 목록의 행이 보인다 — 그 행을 또 눌러 이미 지운 항목을 다시 건드리지 않게 단추는 새 값이 올 때까지 꺼져 있다(읽기가 어떻게 끝나도 켜진다)."""
        env = Env()
        controller = env.controller
        entry = env.info("image_provider").entries[0]
        for ending in ("loaded", "failed", "unexpected", "cancelled"):
            controller.reloading = True
            self.assertTrue(controller.busy and env.state.settings_view()["busy"], ending)
            self.assertEqual(controller.start_state("image_provider", entry.ref, "off")[0], "busy", ending)
            self.assertFalse(controller.register_vm(env.info("image_provider"))["enabled"], ending)
            if ending == "loaded":
                env.state.apply_connections(env.provider.load_connections(lambda *_: None, lambda: False))
            elif ending == "failed":
                env.state.apply_conn_failure(jobs.JobFailure("읽지 못했어요", code="SAMPLE_X"))
            elif ending == "unexpected":
                env.state.apply_conn_unexpected(ValueError("x"))
            else:
                env.state.apply_conn_cancelled()
            self.assertFalse(controller.busy, ending)
            env.state.apply_connections(env.provider.load_connections(lambda *_: None, lambda: False))

    def test_busy_is_in_the_view_while_a_write_runs(self):
        env = Env(delay=0.3)
        status, job = env.controller.start_state("image_provider", env.info("image_provider").entries[0].ref, "off")
        self.assertTrue(env.state.settings_view()["busy"])
        job.join(5)
        self.assertFalse(env.state.settings_view()["busy"])


class TextTest(unittest.TestCase):
    def test_every_key_text_is_plain_korean_with_no_internal_names_or_promises(self):
        from chanceblog_desktop.ui.core.key_text import KEY_T
        self.assertGreaterEqual(len(KEY_T), 100)
        for key, text in KEY_T.items():
            with self.subTest(key=key):
                self.assertTrue(text.strip())
                self.assertIsNone(INTERNAL.search(text), text)
                for word in FORBIDDEN:
                    self.assertNotIn(word, text)
        self.assertEqual(set(KEY_T) - set(T), set(), "모든 키 문구가 T 에 합쳐진다")

    def test_the_sentences_with_blanks_can_be_filled_with_the_names_the_code_gives(self):
        fills = {"service": "서비스", "n": 3, "name": "별칭", "when": "2026-11-07 14:20", "field": "칸", "action": "행동", "state": "사용", "step": "1단계", "provider": "제공자"}
        for key, text in T.items():
            if key.startswith("keys_") and "{" in text:
                with self.subTest(key=key):
                    names = re.findall(r"\{([a-z_]+)\}", text)
                    self.assertTrue(set(names) <= set(fills), (key, names))
                    self.assertNotIn("{", text.format(**{name: fills[name] for name in names}))

    def test_problem_sentences_name_the_box_and_say_what_to_do(self):
        for code in ("empty", "hidden", "short", "min:16", "long", "chars", "unprintable", "other"):
            sentence = keys_view.problem_text("Access Key", code)
            self.assertIn("Access Key", sentence)
            self.assertEqual(leak.text_hits(sentence, NEEDLES), [])
        self.assertIn("(최소 16자)", keys_view.problem_text("API 키", "min:16"))
        for code in ("empty", "long", "hidden", "keyish", "value", "duplicate", "other"):
            self.assertTrue(keys_view.alias_text(code))
        self.assertIn("40자", keys_view.alias_text("long"))


def setUpModule():
    import capability_support
    capability_support.blogger_input_on()                    # 이 시험은 blogger 카드를 키 입력 용도의 예로 쓴다 — Blogger 입력을 임시로만 연다(소스 상수는 False — PCSEC1)


def tearDownModule():
    import capability_support
    capability_support.blogger_input_off()


if __name__ == "__main__":
    unittest.main()
