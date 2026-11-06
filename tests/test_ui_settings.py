"""설정 화면(연결 관리, P4a)의 순수 부분 시험 — PySide6 없이 돈다(네트워크·실제 보관소·시크릿 없음). 뷰모델·가짜 공급자·실제 서비스 어댑터·접이식 묶음·'연결됨' 정직 표시·키 값 비노출·예시 꼬리표.

지키는 것:
  1) 용도 일곱이 네 묶음(데이터·이미지·AI·발행)에 빠짐·겹침 없이 나뉘고 옛 용도는 항목이 남아 있을 때만 보인다. 묶음 머리의 요약 칩은 용도 상태를 그대로 센다.
  2) 호출 코드가 없는 동안(`implemented=False`) 어떤 글에도 '연결됨' 이 없다 — 반대로 호출 코드가 있고 시험 성공이 24시간 안이면 '연결됨' 이 나온다. 준비 배지와 연결 배지는 따로, 키 사용 설정은 항목 줄의 작은 글로만.
  3) 키를 하나만 두는 용도(NAVER API HUB)에는 '예비' 선택지도 '키 더하기' 도 없고 '다른 키로 넘어가지 않아요' 가 보인다. 다른 용도는 사용·예비·꺼짐.
  4) 키 값(끝 4자 포함)은 화면·진단·기록 어디에도 없다 — 어댑터는 보관소에 '있나' 만 묻고 값을 꺼내지 않는다. 읽기만 한다(파일을 만들거나 바꾸지 않는다).
  5) 예시 데이터는 모든 사용량 줄에 '예시' 꼬리표가 붙고 실제 데이터에는 없다. 못 읽은 사용량은 숫자 대신 '확인할 수 없어요'.
  6) 영문 상태 이름·내부 열쇠가 뷰모델의 글에 없고, 실제 블로그 이름·아이디·색 이름이 코드·시험에 없다(범용 원칙).
"""
import contextlib
import dataclasses
import datetime
import io
import json
import logging
import re
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import service_support as support  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security.keystore import MemoryStore  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.service import quota  # noqa: E402
from chanceblog_desktop.ui import adapters  # noqa: E402
from chanceblog_desktop.ui.core import app_state, jobs, services, text, tokens  # noqa: E402
from chanceblog_desktop.ui.core import settings_view as sv  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
GOOGLE_KEY = "AI" + "za" + "SyD4e7Kq9ZmW2xV8bN5tR1cY6uH3jL0pGfA1B"[:35]            # 키 모양의 가짜 값(조각을 이어 만들어 저장소에는 키 문자열이 없다)
GITHUB_KEY = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
HUB = {"client_id": "hubclient001", "client_secret": GOOGLE_KEY}
IMAGE = {"access_key": GITHUB_KEY}
AI = {"key": GOOGLE_KEY[::-1]}                                                          # 거꾸로 뒤집어 또 다른 모양의 가짜 값
FIVE = ("not_connected", "needs_check", "connected", "auth_error", "rate_limited")
INTERNAL = re.compile(r"\b(?:rotation|failover|active|standby|needs_check|not_connected|auth_error|rate_limited|connected|implemented|takes_keys|max_entries|legacy|fail_closed|unverifiable|"
                      r"naver_apihub|naver_searchad|naver_openapi|image_provider|ai_assist|blogger|github_repo)\b")
UPPER_CODE = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")


def info(key, **fields):
    """서비스 표(`connections.PURPOSES`)의 용도 하나를 화면용 값으로 — 이름·키 항목 수·전환 규칙은 표 그대로, 나머지는 `fields` 로 바꾼다."""
    spec = cn.PURPOSES[key]
    base = {"label": spec.label, "implemented": spec.implemented, "takes_keys": spec.takes_keys, "max_entries": spec.max_entries, "rotation": spec.providers[0].rotation,
            "legacy": bool(spec.legacy_to), "status": "not_connected" if spec.takes_keys and not spec.legacy_to else ""}
    base.update(fields)
    return services.PurposeInfo(key, **base)


def view_of(*purposes, state="normal", **fields):
    return sv.build_settings_view(services.ConnectionsData(purposes=tuple(purposes), **fields), state)


def cards_of(view):
    return {card["key"]: card for group in view["groups"] for card in group["cards"]}


def visible_strings(value, skip=("key", "tone", "icon", "diag")):
    """뷰모델 안의 글 전부(재귀) — 그림·묶음을 고르는 값(`key`·`tone`·`icon`)과 진단 정보(`diag`)는 뺀다."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for name, item in value.items():
            if name not in skip:
                yield from visible_strings(item, skip)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from visible_strings(item, skip)


def leaks(shown, secret, size=6):
    """`shown` 에 비밀의 연속된 `size` 글자 조각이 남아 있으면 그 조각들(비어 있어야 한다)."""
    return sorted({secret[i:i + size] for i in range(len(secret) - size + 1) if secret[i:i + size] in shown})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = support.make_ctx(self.tmp.name, repo="")                                  # 연결한 저장소 설정을 저장하지 않는다 — 데이터 폴더는 키 항목을 넣을 때 처음 생긴다
        self.store = self.ctx.keystore
        self.provider = adapters.ServiceConnectionsProvider(context_factory=lambda data_dir=None: self.ctx)

    def add(self, purpose, name, fields, **kwargs):
        return cn.add_entry(self.ctx, purpose, name=name, fields=fields, keystore=self.store, **kwargs).entry

    def read(self, provider=None):
        return (provider or self.provider).load_connections(lambda *a: None, lambda: False)

    def wording(self, state, data):
        return sv.build_settings_view(data, state)


class GroupsTest(Base):
    def test_the_seven_purposes_fall_into_the_four_groups_with_no_gap_and_no_overlap(self):
        registry = cn.PURPOSES
        self.assertEqual(len(registry), 7)
        self.assertEqual(set(services.PURPOSE_GROUPS), set(registry), "묶음 표가 서비스 표와 어긋났다(빠졌거나 남는 용도)")
        self.assertEqual(services.GROUP_ORDER, ("data", "image", "ai", "publish"))
        self.assertEqual(set(services.PURPOSE_GROUPS.values()), set(services.GROUP_ORDER))
        infos = [info(key, entries=(services.EntryInfo("남은 항목"),) if (spec.legacy_to or key in services.ON_DEMAND) else (), on_demand=key in services.ON_DEMAND) for key, spec in registry.items()]
        groups = sv.grouped(infos)                                                                                       # 옛 용도·필요할 때만 보이는 용도에 항목을 하나씩 두면 일곱이 모두 보인다(보이는 규칙은 아래 시험)
        self.assertEqual([key for key, _members in groups], list(services.GROUP_ORDER))
        flat = [member.key for _key, members in groups for member in members]
        self.assertEqual(sorted(flat), sorted(registry), "빠진 용도가 있다")
        self.assertEqual(len(flat), len(set(flat)), "두 묶음에 든 용도가 있다")
        self.assertEqual({key: [member.key for member in members] for key, members in groups},
                         {"data": ["naver_apihub", "naver_searchad", "naver_openapi"], "image": ["image_provider"], "ai": ["ai_assist"], "publish": ["blogger", "github_repo"]})

    def test_the_four_group_titles_and_every_purpose_has_its_own_sentence(self):
        view = view_of(*[info(key) for key, spec in cn.PURPOSES.items() if not spec.legacy_to])
        self.assertEqual([group["title"] for group in view["groups"]], ["데이터", "이미지", "AI", "발행·연결"])         # 통합 전달서 §34 — 마지막 묶음 이름은 '발행·연결'(Blogger·GitHub)
        for key in cn.PURPOSES:
            self.assertTrue(text.T.get("purpose_" + key), f"{key} 의 한 줄 설명이 문구표에 없다")
        self.assertEqual({key: card["desc"] for key, card in cards_of(view).items()}, {key: text.T["purpose_" + key] for key in cards_of(view)})

    def test_a_purpose_the_group_table_does_not_know_still_shows_instead_of_vanishing(self):
        new = services.PurposeInfo("some_new_purpose", "새 용도", status="not_connected")
        view = view_of(new, info("blogger"))
        self.assertIn("some_new_purpose", cards_of(view))
        self.assertEqual(sv.group_of("some_new_purpose"), sv.FALLBACK_GROUP)
        self.assertEqual(sv.FALLBACK_GROUP, "data")

    def test_the_old_purpose_is_listed_only_while_entries_remain_in_the_view_model(self):
        old = info("naver_openapi", entries=())
        self.assertNotIn("naver_openapi", cards_of(view_of(old, info("naver_apihub"))))
        kept = view_of(dataclasses.replace(old, entries=(services.EntryInfo("옛 키", "active", True),)), info("naver_apihub"))
        self.assertIn("naver_openapi", cards_of(kept))
        card = cards_of(kept)["naver_openapi"]
        self.assertEqual((card["ready"]["text"], card["conn"], card["choices"], card["policy"]), ("옛 항목", None, None, ""))       # 옛 항목은 '준비 중' 도 연결 배지도 아니다
        self.assertTrue(card["gray"])                                                                                                 # 쓰이지 않는 옛 항목도 회색 톤
        self.assertEqual(card["note"], text.T["legacy_note"])

    def test_the_old_purpose_and_the_search_ad_purpose_show_only_with_an_entry_or_a_real_connection(self):
        """통합 전달서 §34 — 검색광고는 '실제 연결 시에만' 보인다. 옛 용도처럼 키 항목이 있거나 실제로 연결돼 있을 때만 카드가 있고, 나머지 용도는 항목이 없어도 늘 보인다."""
        self.assertEqual(services.ON_DEMAND, ("naver_searchad",))
        bare = [info(key, on_demand=key in services.ON_DEMAND) for key in cn.PURPOSES]                                        # 키 항목이 하나도 없는 설치
        self.assertEqual([member.key for _key, members in sv.grouped(bare) for member in members], ["naver_apihub", "image_provider", "ai_assist", "blogger", "github_repo"])
        ad = info("naver_searchad", on_demand=True)
        self.assertFalse(sv.visible(ad))
        self.assertTrue(sv.visible(dataclasses.replace(ad, entries=(services.EntryInfo("키", "off", True),))))                   # 항목이 있으면(꺼 두었어도) 보인다
        self.assertTrue(sv.visible(dataclasses.replace(ad, implemented=True, status="connected")))                               # 실제로 연결돼 있으면 보인다
        self.assertFalse(sv.visible(dataclasses.replace(ad, status="connected")))                                                # 호출 코드가 없어 '연결 확인 필요' 로 낮아진 것은 연결이 아니다
        self.assertTrue(all(sv.visible(info(key)) for key in ("naver_apihub", "image_provider", "ai_assist", "blogger", "github_repo")))
        self.assertEqual([group["summary"] for group in view_of(*bare)["groups"]], ["준비 중 1", "준비 중 1", "준비 중 1", "준비 중 1"])   # 안 보이는 용도는 묶음 머리 요약에도 안 센다
        self.assertEqual(sv.default_open([dataclasses.replace(ad, status="auth_error"), info("blogger", status="auth_error")]), "publish")   # 안 보이는 용도의 상태는 '문제' 로 펼침을 정하지 못한다

    def test_the_real_adapter_lists_the_old_purpose_only_when_an_old_file_still_holds_its_entries(self):
        keys = [item.key for item in self.read().purposes]
        self.assertEqual(keys, ["naver_apihub", "naver_searchad", "image_provider", "ai_assist", "blogger", "github_repo"])           # 옛 용도 없음
        registry = support.generic_registry()                                                                                        # 새 항목을 더할 수 있는 시험용 옛 용도
        cn.add_entry(self.ctx, "naver_openapi", name="옛 키", fields={"client_id": "oldclient001", "client_secret": "oldsecret0001"}, keystore=self.store, registry=registry)
        data = self.read()
        self.assertEqual([item.key for item in data.purposes][-1], "naver_openapi")
        old = data.purposes[-1]
        self.assertEqual((old.legacy, old.status, [entry.name for entry in old.entries]), (True, "", ["옛 키"]))


class ChipsTest(unittest.TestCase):
    def test_the_group_summary_counts_the_purposes_exactly_like_the_example(self):
        """3개 용도(둘은 준비 중이고 하나만 키가 있어 확인 필요)의 묶음 머리 = '준비 중 2 · 연결 확인 필요 1' — 옛 용도는 세지 않는다."""
        data = (info("naver_apihub", status="needs_check", entries=(services.EntryInfo("키", "active", True),)), info("naver_searchad", status="not_connected"),
                info("naver_openapi", entries=(services.EntryInfo("옛 키", "active", True),)))
        group = view_of(*data)["groups"][0]
        self.assertEqual((group["key"], group["summary"]), ("data", "준비 중 2 · 연결 확인 필요 1"))
        self.assertEqual([chip["text"] for chip in group["chips"]], ["준비 중 2", "연결 확인 필요 1"])

    def test_every_group_summary_of_the_sample_matches_the_states_of_its_purposes(self):
        view = sv.build_settings_view(services.ConnectionsData(purposes=services.sample_connections("normal"), sample=True), "normal")
        summaries = {group["key"]: group["summary"] for group in view["groups"]}
        self.assertEqual(summaries, {"data": "준비 중 2 · 요청 한도 도달 1 · 연결 확인 필요 1", "image": "연결됨 1", "ai": "준비 중 1", "publish": "준비 중 1 · 인증 정보 오류 1"})
        for group in view["groups"]:                                                                      # 칩 글자 = 카드의 배지 글자를 센 값
            ready = [card["ready"]["text"] for card in group["cards"]]
            statuses = [card["conn"]["text"] for card in group["cards"] if card["conn"]]
            expected = ([f"준비 중 {ready.count('준비 중')}"] if "준비 중" in ready else []) + [f"{name} {statuses.count(name)}" for name in ("인증 정보 오류", "요청 한도 도달", "연결 확인 필요", "연결됨") if name in statuses]
            self.assertEqual([chip["text"] for chip in group["chips"]], expected, group["key"])

    def test_the_neutral_not_connected_state_is_not_a_chip_and_a_group_with_nothing_to_say_has_none(self):
        group = view_of(info("naver_apihub", status="not_connected"), info("naver_searchad", status="not_connected"))["groups"][0]
        self.assertEqual([chip["text"] for chip in group["chips"]], ["준비 중 2"])                                  # '연결 안 됨' 은 문제가 아니라서 세지 않는다
        publish = view_of(info("github_repo"))["groups"][3]
        self.assertEqual((publish["chips"], publish["summary"]), ([], ""))
        self.assertEqual(publish["a11y"], "발행·연결, 접혀 있어요")

    def test_the_chip_counts_every_purpose_that_has_the_same_status(self):
        """점검 V26 — 칩 숫자는 같은 상태인 용도의 수다(숫자를 늘 1 로 굳혀도 통과하던 틈)."""
        two = view_of(info("naver_apihub", status="needs_check"), info("naver_searchad", status="needs_check"))["groups"][0]
        self.assertEqual(two["summary"], "준비 중 2 · 연결 확인 필요 2")
        limited = view_of(info("naver_apihub", status="rate_limited"), info("naver_searchad", status="rate_limited"))["groups"][0]
        self.assertEqual([chip["text"] for chip in limited["chips"]], ["준비 중 2", "요청 한도 도달 2"])
        crowd = [services.PurposeInfo(f"extra_{n}", f"새 용도 {n}", status="auth_error") for n in range(4)]            # 표에 없는 용도는 '데이터' 묶음에 들어온다 — 같은 상태 넷
        self.assertEqual([chip["text"] for chip in view_of(*crowd)["groups"][0]["chips"]], ["준비 중 4", "인증 정보 오류 4"])

    def test_the_group_name_for_a_screen_reader_says_the_title_the_summary_and_whether_it_is_open(self):
        view = sv.build_settings_view(services.ConnectionsData(purposes=services.sample_connections("normal"), sample=True), "normal", open_groups={"data"})
        names = {group["key"]: group["a11y"] for group in view["groups"]}
        self.assertEqual(names["data"], "데이터, 준비 중 2 · 요청 한도 도달 1 · 연결 확인 필요 1, 펼쳐져 있어요")
        self.assertEqual(names["image"], "이미지, 연결됨 1, 접혀 있어요")

    def test_a_problem_is_a_problem_even_for_a_purpose_that_is_only_getting_ready(self):
        self.assertTrue(sv.has_problem([info("blogger", status="auth_error")]))
        self.assertTrue(sv.has_problem([info("naver_apihub", status="rate_limited")]))
        self.assertFalse(sv.has_problem([info("naver_apihub", status="needs_check"), info("blogger", status="not_connected")]))


class FirstOpenTest(unittest.TestCase):
    def test_the_first_group_with_a_problem_opens_first_and_without_a_problem_the_data_group_does(self):
        quiet = (info("naver_apihub", status="needs_check"), info("image_provider"), info("blogger"))
        self.assertEqual(sv.default_open(quiet), "data")
        self.assertEqual(sv.default_open((info("naver_apihub"), info("blogger", status="auth_error"))), "publish")
        self.assertEqual(sv.default_open((info("image_provider", status="rate_limited"), info("blogger", status="auth_error"))), "image")          # 둘이면 앞 묶음
        self.assertEqual(sv.default_open((info("naver_apihub", status="rate_limited"), info("blogger", status="auth_error"))), "data")
        self.assertEqual(sv.default_open(()), "data")
        self.assertEqual(sv.default_open(services.sample_connections("normal")), "data")                                                         # 예시: 한도에 닿은 용도가 데이터에 있다

    def test_the_state_picks_the_first_open_group_once_and_then_keeps_what_the_user_did(self):
        state = app_state.AppState(services.FakeHomeProvider(), connections=services.FakeConnectionsProvider())
        self.assertIsNone(state.conn_open)
        state.apply_connections(services.ConnectionsData(purposes=(info("naver_apihub"), info("blogger", status="auth_error"))))
        self.assertEqual(state.conn_open, {"publish"})
        self.assertTrue(state.set_group_open("data", True))
        self.assertTrue(state.set_group_open("publish", False))
        self.assertEqual(state.conn_open, {"data"})
        state.apply_connections(services.ConnectionsData(purposes=(info("image_provider", status="rate_limited"),)))                              # 새로 읽어도(문제가 다른 묶음에 생겨도) 사용자가 정한 대로
        self.assertEqual(state.conn_open, {"data"})
        self.assertFalse(state.set_group_open("nope", True))
        self.assertEqual(state.conn_open, {"data"})
        view = state.settings_view()
        self.assertEqual({group["key"]: group["open"] for group in view["groups"]}, {"data": True, "image": False, "ai": False, "publish": False})


class HonestStatusTest(Base):
    def test_while_no_purpose_has_call_code_no_text_anywhere_says_connected(self):
        """실제 서비스 표는 모든 용도가 호출 코드가 없다 — 시험 성공 기록이 24시간 안에 있어도 '연결됨' 은 어디에도 나오지 않는다."""
        for spec in cn.PURPOSES.values():
            self.assertFalse(spec.implemented, spec.key)
        entry = self.add("naver_apihub", "내 키", HUB)
        self.add("image_provider", "이미지 키", IMAGE)
        cn.mark_check(self.ctx, entry.entry_id, cn.CHECK_OK)
        image_id = next(item.entry_id for item in cn.load(self.ctx).entries if item.purpose == "image_provider")
        cn.mark_check(self.ctx, image_id, cn.CHECK_OK)
        view = view_of(*self.read().purposes)
        blob = json.dumps(view, ensure_ascii=False)
        self.assertNotIn("연결됨", blob)
        self.assertEqual(cards_of(view)["naver_apihub"]["conn"]["text"], "연결 확인 필요")
        self.assertEqual(cards_of(view)["image_provider"]["conn"]["text"], "연결 확인 필요")

    def test_even_when_a_provider_claims_connected_a_purpose_without_call_code_is_shown_as_needs_check(self):
        card = cards_of(view_of(info("naver_apihub", status="connected", implemented=False)))["naver_apihub"]
        self.assertEqual((card["ready"]["text"], card["conn"]["text"]), ("준비 중", "연결 확인 필요"))
        self.assertNotIn("연결됨", json.dumps(card, ensure_ascii=False))
        self.assertEqual(sv.effective_status(info("naver_apihub", status="connected", implemented=False)), "needs_check")
        self.assertEqual(sv.effective_status(info("naver_apihub", status="no_such_state")), "needs_check")                                  # 모르는 상태는 확인 필요
        self.assertEqual(sv.effective_status(info("naver_apihub", status="no_such_state", implemented=True)), "needs_check")                 # 호출 코드가 있어도 모르는 상태를 '연결됨' 으로 읽지 않는다

    def test_a_purpose_with_call_code_and_a_fresh_successful_test_shows_connected_and_a_stale_one_does_not(self):
        """반대 방향 — 가짜 서비스 표(호출 코드가 있는 NAVER API HUB)에서는 '연결됨' 이 나오고, 24시간이 지나면 다시 '연결 확인 필요' 다."""
        spec = dataclasses.replace(cn.PURPOSES["naver_apihub"], implemented=True)
        registry = {**cn.PURPOSES, "naver_apihub": spec}
        entry = self.add("naver_apihub", "내 키", HUB, registry=registry)
        cn.mark_check(self.ctx, entry.entry_id, cn.CHECK_OK, registry=registry)
        provider = adapters.ServiceConnectionsProvider(context_factory=lambda data_dir=None: self.ctx, registry=registry)
        view = view_of(*self.read(provider).purposes)
        card = cards_of(view)["naver_apihub"]
        self.assertEqual((card["ready"]["text"], card["conn"]["text"], card["gray"]), ("사용할 수 있어요", "연결됨", False))
        self.assertEqual([chip["text"] for chip in view["groups"][0]["chips"]], ["연결됨 1"])                                                # 허브만 연결됨 — 키 항목이 없는 검색광고는 카드도 칩도 없다(§34)
        self.assertNotIn("naver_searchad", cards_of(view))
        self.ctx.clock.advance(hours=25)
        stale = cards_of(view_of(*self.read(provider).purposes))["naver_apihub"]
        self.assertEqual(stale["conn"]["text"], "연결 확인 필요")
        self.ctx.clock.advance(hours=-25)
        cn.mark_check(self.ctx, entry.entry_id, cn.CHECK_AUTH, registry=registry)
        self.assertEqual(cards_of(view_of(*self.read(provider).purposes))["naver_apihub"]["conn"]["text"], "인증 정보 오류")

    def test_a_missing_key_in_the_store_is_needs_check_and_says_so_on_the_entry_line(self):
        entry = self.add("naver_apihub", "내 키", HUB)
        self.store.delete(entry.ref)
        card = cards_of(view_of(*self.read().purposes))["naver_apihub"]
        self.assertEqual(card["conn"]["text"], "연결 확인 필요")
        self.assertEqual(card["entries"][0]["missing"], "보관소에서 이 키를 찾지 못했어요.")
        found = self.add("image_provider", "이미지 키", IMAGE)
        self.assertEqual(found.purpose, "image_provider")
        self.assertEqual(cards_of(view_of(*self.read().purposes))["image_provider"]["entries"][0]["missing"], "")

    def test_the_status_texts_are_the_five_the_service_table_defines_and_the_state_words_are_its_too(self):
        for key, shown in cn.STATUS_TEXT.items():
            self.assertEqual(text.T["status_" + key], shown, key)
        self.assertEqual(set(cn.STATUS_TEXT), set(FIVE))
        for key, shown in cn.STATE_TEXT.items():
            self.assertEqual(text.T["state_" + key], shown, key)

    def test_the_two_badges_are_separate_and_the_item_setting_is_a_small_line_not_a_badge(self):
        card = cards_of(view_of(info("naver_apihub", status="needs_check", entries=(services.EntryInfo("내 키", "active", True),))))["naver_apihub"]
        self.assertEqual(sorted(card["ready"]), ["text", "tone"])
        self.assertEqual(sorted(card["conn"]), ["text", "tone"])
        self.assertEqual((card["ready_caption"], card["conn_caption"]), ("준비", "연결"))
        self.assertNotEqual(card["ready"]["text"], card["conn"]["text"])
        self.assertEqual(card["entries"], [{"name": "내 키", "state_line": "키 사용 설정: 사용", "missing": ""}])
        for word in ("사용", "예비", "꺼짐"):                                                                 # 항목 상태 낱말은 배지에 섞이지 않는다
            self.assertNotEqual(card["ready"]["text"], word)
            self.assertNotEqual(card["conn"]["text"], word)

    def test_the_badge_tones_keep_a_problem_visible_without_relying_on_color_alone(self):
        tones = {status: sv.STATUS_TONE[status] for status in FIVE}
        self.assertEqual(tones, {"not_connected": "muted", "needs_check": "warning", "connected": "ok", "auth_error": "danger", "rate_limited": "warning"})
        self.assertEqual(sv.READY_TONE, {"prep": "muted", "ok": "info", "nokey": "muted", "legacy": "muted"})
        for status in FIVE:
            self.assertTrue(text.T["status_" + status])                                                       # 어느 상태든 색과 함께 글자가 있다


class SingleKeyRuleTest(unittest.TestCase):
    def test_a_single_key_purpose_never_offers_standby_or_add_key_anywhere_in_the_view_model(self):
        hub = info("naver_apihub", status="needs_check", entries=(services.EntryInfo("내 키", "active", True),), usage=services.UsageInfo((("오늘", 1, 100),), True, 30000))
        self.assertEqual(hub.max_entries, 1)
        self.assertEqual(sv.state_choices(hub), ("active", "off"))
        card = cards_of(view_of(hub))["naver_apihub"]
        self.assertEqual(card["choices"], {"label": "키 사용 설정 종류", "items": ["사용", "꺼짐"]})                       # '고를 수 있는' 이라고 말하지 않는다 — 이 화면은 읽기만 한다
        self.assertNotIn("고를", card["choices"]["label"])
        blob = json.dumps(card, ensure_ascii=False)
        for word in ("예비", "키 더하기", "더하기", "추가"):
            self.assertNotIn(word, blob, word)
        self.assertEqual(card["policy"], text.T["policy_single"])

    def test_a_purpose_that_never_switches_keys_offers_no_standby_either(self):
        """L4 — 이미지 공급자 카드가 '자동으로 다른 키로 넘어가지 않아요' 라면서 '예비' 를 보이면 모순이다. 규칙은 '키 하나이거나 전환 없음' 한 곳(`single_choice`)이다."""
        image = info("image_provider", entries=(services.EntryInfo("가", "active", True), services.EntryInfo("나", "standby", True)))
        self.assertEqual((image.max_entries, image.rotation), (3, "never"))
        self.assertTrue(sv.single_choice(image))
        self.assertEqual(sv.state_choices(image), ("active", "off"))
        card = cards_of(view_of(image))["image_provider"]
        self.assertEqual(card["choices"]["items"], ["사용", "꺼짐"])
        self.assertEqual([entry["state_line"] for entry in card["entries"]], ["키 사용 설정: 사용", "키 사용 설정: 꺼짐"])        # 저장된 '예비' 는 쓰이지 않으니 꺼짐으로
        self.assertNotIn("예비", json.dumps(card, ensure_ascii=False))
        self.assertEqual(card["policy"], text.T["policy_never"])
        self.assertTrue(sv.single_choice(info("naver_apihub")))                                                          # 키 하나인 용도
        self.assertTrue(sv.single_choice(info("blogger", max_entries=1)))                                                 # 키 하나만 두면 전환 규칙이 무엇이든 '예비' 가 없다
        self.assertTrue(sv.single_choice(info("blogger", rotation="never")))                                              # 전환이 없으면 키가 몇 개든 '예비' 가 없다
        for key in ("naver_searchad", "ai_assist", "blogger"):                                                            # 전환하는 용도는 그대로 세 가지
            self.assertFalse(sv.single_choice(info(key)), key)
            self.assertEqual(sv.state_choices(info(key)), ("active", "standby", "off"), key)

    def test_the_api_hub_card_says_what_happens_at_the_limit_in_the_handoff_words(self):
        """통합 전달서 §34 — '한도 도달 시 저장된 데이터로 계속' + 보조 설명. 다른 용도 카드에는 이 문장이 없다(Seed·캘린더로 후보를 만드는 일은 NAVER API HUB 이야기다)."""
        cards = cards_of(view_of(*[info(key) for key in ("naver_apihub", "naver_searchad", "image_provider", "ai_assist", "blogger", "github_repo")]))
        self.assertEqual(cards["naver_apihub"]["limit"], {"title": "한도 도달 시 저장된 데이터로 계속", "desc": "새 API 호출을 중지하고 Seed, 캘린더와 기존 발행 이력으로 후보를 생성합니다."})
        self.assertEqual([key for key, card in cards.items() if card["limit"]], ["naver_apihub"])
        self.assertNotIn("절약 모드", json.dumps(cards, ensure_ascii=False))                                              # 전달서가 바꾸라고 한 옛 말
        self.assertNotIn("저장된 정보와 기본 규칙으로 계속해요", json.dumps(cards["naver_apihub"], ensure_ascii=False))       # 같은 말을 두 가지로 하지 않는다

    def test_a_standby_entry_of_a_single_key_purpose_is_shown_as_off_because_nothing_uses_it(self):
        for stored in ("standby", "off"):
            card = cards_of(view_of(info("naver_apihub", entries=(services.EntryInfo("내 키", stored, True),))))["naver_apihub"]
            self.assertEqual(card["entries"][0]["state_line"], "키 사용 설정: 꺼짐", stored)
            self.assertNotIn("예비", json.dumps(card, ensure_ascii=False), stored)
        multi = cards_of(view_of(info("naver_searchad", entries=(services.EntryInfo("가", "active", True), services.EntryInfo("나", "standby", True), services.EntryInfo("다", "off", True)))))
        self.assertEqual([entry["state_line"] for entry in multi["naver_searchad"]["entries"]], ["키 사용 설정: 사용", "키 사용 설정: 예비", "키 사용 설정: 꺼짐"])

    def test_the_other_purposes_offer_all_three_settings_and_the_standby_sentence(self):
        for key in ("naver_searchad", "ai_assist", "blogger"):
            card = cards_of(view_of(info(key)))[key]
            self.assertEqual(card["choices"]["items"], ["사용", "예비", "꺼짐"], key)
            self.assertEqual(card["policy"], "예비: 한도·일시 오류일 때만 다음 키로 넘어가요(용도당 최대 3개)", key)

    def test_the_screen_text_says_the_single_key_does_not_switch_and_unsplash_does_not_switch_automatically(self):
        self.assertIn("다른 키로 넘어가지 않아요", text.T["policy_single"])
        self.assertEqual(text.T["policy_single"], "키는 1개만 써요 · 한도에 닿아도 다른 키로 넘어가지 않아요")           # 괄호 안 설명은 한도 문장(`limit`)으로 옮겼다
        image = cards_of(view_of(info("image_provider")))["image_provider"]
        self.assertEqual(image["policy"], text.T["policy_never"])
        self.assertIn("자동으로 다른 키로 넘어가지 않아요", image["policy"])
        self.assertEqual(sv.policy_text(info("github_repo")), "")                                           # 키를 받지 않는 용도에는 키 전환 이야기가 없다
        self.assertEqual(sv.policy_text(info("naver_openapi")), "")

    def test_the_card_has_no_field_for_an_action_so_nothing_can_look_pressable_yet(self):
        """읽기만 하는 화면 — 용도 카드·묶음·화면 뷰모델의 칸이 이 목록뿐이다(키 더하기·지우기·시험 같은 동작 칸은 다음 묶음(P4f)이 더하면서 이 시험을 고친다)."""
        view = view_of(info("naver_apihub"))
        self.assertEqual(set(view), {"title", "sub", "sample", "sample_tag", "state", "fetched", "banners", "refresh", "section", "groups", "keys_note", "advanced", "loading", "empty", "error"})
        self.assertEqual(set(view["groups"][0]), {"key", "title", "open", "chips", "summary", "cards", "a11y"})
        self.assertEqual(set(view["groups"][0]["cards"][0]), {"key", "name", "desc", "gray", "ready", "conn", "ready_caption", "conn_caption", "note", "policy", "limit", "choices", "entries_title",
                                                               "entries", "usage", "a11y"})
        self.assertEqual(text.T["conn_keys_note"], "화면에서 키를 넣는 기능은 아직 없어요.")                                   # 명령줄·개발 순서('다음 묶음') 낱말 없이 — 접이식 '묶음' 과 낱말이 겹치지도 않는다
        self.assertEqual(view["keys_note"], text.T["conn_keys_note"])
        for word in ("명령줄", "묶음", "P4"):
            self.assertNotIn(word, text.T["conn_keys_note"], word)


class CardTextTest(unittest.TestCase):
    def test_the_getting_ready_card_is_gray_and_says_there_is_no_connecting_function_yet(self):
        card = cards_of(view_of(info("naver_searchad")))["naver_searchad"]
        self.assertEqual((card["gray"], card["ready"]["text"], card["note"]), (True, "준비 중", "아직 실제로 연결하는 기능이 없어요. 키가 없어도 핵심 기능은 그대로예요."))

    def test_github_takes_no_key_and_has_no_connection_badge(self):
        card = cards_of(view_of(info("github_repo")))["github_repo"]
        self.assertEqual((card["ready"]["text"], card["conn"], card["note"], card["choices"], card["policy"], card["gray"]),
                         ("키 없음", None, "키를 받지 않아요. 컴퓨터의 Git 로그인을 써요. 로그인 확인은 아직 못 해요.", None, "", False))      # 연결 상태를 말하지 않는 대신 '확인은 아직 못 한다' 고 알린다(L5)
        self.assertEqual(card["entries"], [])

    def test_no_card_says_the_core_features_stay_the_same_twice(self):
        """L9 — AI 카드에 '핵심 기능은 그대로예요' 가 용도 설명과 준비 중 안내에 두 번 있었다(안심 문장은 준비 중 안내에 한 번만)."""
        view = view_of(*[info(key) for key, spec in cn.PURPOSES.items() if not spec.legacy_to])
        for key, card in cards_of(view).items():
            self.assertLessEqual(" ".join(visible_strings(card)).count("핵심 기능은 그대로예요"), 1, key)
        self.assertEqual(cards_of(view)["ai_assist"]["desc"], "요약이나 설명을 돕는 선택 기능이에요. 기본은 꺼짐이에요.")
        self.assertEqual(cards_of(view)["ai_assist"]["note"], text.T["prep_note"])

    def test_the_example_explanations_say_that_the_connection_states_are_examples_too(self):
        """L6 — 예시에서는 이미지 공급자가 '연결됨' 이지만 실제 서비스에서는 나올 수 없는 모습이다. 예시 설명이 키 이름·숫자만이 아니라 연결 상태도 예시라고 말한다."""
        for key in ("conn_sample_tip", "conn_sample_dialog_body"):
            self.assertIn("연결 상태", text.T[key], key)
            self.assertIn("예시", text.T[key], key)
        self.assertIn("'연결됨'", text.T["conn_sample_dialog_body"])
        self.assertNotIn("아닙니다", text.T["conn_sample_tip"])                                                              # 화면의 '~해요' 말투와 맞춘다

    def test_a_purpose_with_call_code_is_not_gray_and_has_no_getting_ready_note(self):
        card = cards_of(view_of(info("image_provider", implemented=True, status="not_connected")))["image_provider"]
        self.assertEqual((card["gray"], card["ready"], card["note"]), (False, {"text": "사용할 수 있어요", "tone": "info"}, ""))

    def test_a_key_shaped_entry_name_is_masked_before_it_is_cut_and_a_missing_name_is_named(self):
        shown = cards_of(view_of(info("naver_searchad", entries=(services.EntryInfo("내 키 " + GOOGLE_KEY, "active", True), services.EntryInfo("", "active", True)))))["naver_searchad"]["entries"]
        self.assertEqual(leaks(shown[0]["name"], GOOGLE_KEY, 5), [])
        self.assertIn("가림", shown[0]["name"])
        self.assertEqual(shown[1]["name"], text.T["entry_unnamed"])

    def test_the_sentences_never_promise_and_never_carry_a_command_or_a_python_list(self):
        for key in [name for name in text.T if name.startswith(("conn_", "policy_", "prep_", "nokey_", "legacy_", "usage_", "purpose_", "ready_", "status_", "settings_", "advanced_", "entry"))]:
            value = text.T[key]
            for word in text.FORBIDDEN:
                self.assertNotIn(word, value, key)
            self.assertNotRegex(value, r"keys |--|`|\['|\"\]|Traceback", key)                             # 명령줄 글·백틱·파이썬 목록 꼴이 없다
            self.assertNotRegex(value, UPPER_CODE, key)


class UsageTest(unittest.TestCase):
    def rows(self, usage, sample=False):
        shown = sv.usage_vm(info("naver_apihub", usage=usage), sample)
        return None if shown is None else shown["rows"]

    def test_the_api_hub_usage_line_reads_like_the_operator_example(self):
        usage = services.UsageInfo((("오늘", 12, 100), ("이번 달", 340, 27000)), True, 30000, fail_closed=True)
        self.assertEqual(self.rows(usage), [{"text": "오늘 12 / 100회 · 이번 달 340 / 27,000회", "tag": "", "note": False},                                    # 통합 전달서 §34 — '오늘 00 / 00회'
                                            {"text": "서비스 콘솔 월 한도 30,000회 · 실패한 호출도 세어요", "tag": "", "note": True}])                      # 콘솔 한도·세는 방식은 작은 글로 따로
        self.assertNotIn("시도", " ".join(row["text"] for row in self.rows(usage)))
        no_console = self.rows(services.UsageInfo((("오늘", 1, 100),), True))
        self.assertEqual([row["text"] for row in no_console], ["오늘 1 / 100회", "실패한 호출도 세어요"])
        self.assertEqual([row["text"] for row in self.rows(services.UsageInfo((("오늘", 1, 100),), False, 500))], ["오늘 1 / 100회", "서비스 콘솔 월 한도 500회"])

    def test_a_usage_that_could_not_be_read_shows_no_numbers_but_the_sentence(self):
        closed = self.rows(services.UsageInfo(readable=False, fail_closed=True))
        self.assertEqual(closed, [{"text": "확인할 수 없어요. 새 조회를 멈추고 저장된 정보로 계속해요.", "tag": "", "note": False}])
        plain = self.rows(services.UsageInfo(readable=False, rows=(("오늘", 50, 100),)))
        self.assertEqual([row["text"] for row in plain], ["확인할 수 없어요. 사용량 기록을 읽지 못했어요."])
        for rows in (closed, plain):
            self.assertFalse(re.search(r"\d", " ".join(row["text"] for row in rows)))                      # 못 읽은 값으로 숫자를 지어내지 않는다
        with_cause = self.rows(services.UsageInfo(readable=False, fail_closed=True, stop_cause="사용량 기록이 사라진 적이 있어요"))
        self.assertEqual([(row["text"], row["note"]) for row in with_cause][1:], [("사용량 기록이 사라진 적이 있어요", True)])

    def test_a_stopped_purpose_shows_the_fixed_sentence_and_one_reason_and_when_it_opens_again(self):
        usage = services.UsageInfo((("오늘", 100, 100),), True, 30000, "", cn.APIHUB_STOP_TEXT, "오늘 내부 한도(100회)를 다 썼습니다", "내일 00:00 이후 자동 재개", True, True)
        rows = self.rows(usage)
        self.assertEqual([row["note"] for row in rows], [False, True, True, True, True])                      # 숫자 줄 · 콘솔 한도 줄 · 고정 문구 · 사유 · 다시 열리는 때
        self.assertEqual(rows[2]["text"], cn.APIHUB_STOP_TEXT)
        self.assertEqual(rows[3]["text"], "오늘 내부 한도(100회)를 다 썼습니다")

    def test_a_purpose_with_nothing_to_say_has_no_usage_block_and_the_sample_tags_every_row(self):
        self.assertIsNone(self.rows(None))
        self.assertIsNone(self.rows(services.UsageInfo()))
        rows = self.rows(services.UsageInfo((("최근 60분", 7, 50),)), sample=True)
        self.assertEqual(rows, [{"text": "최근 60분 7 / 50회", "tag": "예시", "note": False}])

    def test_the_adapter_turns_the_service_usage_into_the_same_values(self):
        spec = cn.PURPOSES["naver_apihub"]
        ledger = quota.LedgerUsage(12, 10, 340, 300, 100, 27000, 30000, "", None, "notice", "이번 달 사용량이 70%를 넘었습니다", False, "", "", "")
        view = quota.UsageView("naver_apihub", spec.label, (), False, False, None, "", "", 1, (), ledger)
        self.assertEqual(adapters.usage_of(spec, view), services.UsageInfo((("오늘", 12, 100), ("이번 달", 340, 27000)), True, 30000, "이번 달 사용량이 70%를 넘었습니다", "", "", "", True, True))
        stopped = dataclasses.replace(ledger, stopped=True, stop_code="exhausted", stop_cause="오늘 내부 한도(100회)를 다 썼습니다", stop_text=cn.APIHUB_STOP_TEXT)
        got = adapters.usage_of(spec, dataclasses.replace(view, ledger=stopped, blocked=True, resume_text="내일 00:00 이후 자동 재개"))
        self.assertEqual((got.stage_text, got.stop_text, got.stop_cause, got.resume_text), ("", cn.APIHUB_STOP_TEXT, "오늘 내부 한도(100회)를 다 썼습니다", "내일 00:00 이후 자동 재개"))
        for unreadable in (dataclasses.replace(view, notice="기록 파일을 읽을 수 없어요"), dataclasses.replace(view, ledger=dataclasses.replace(ledger, stop_code="unverifiable", stopped=True, stop_cause="모순"))):
            got = adapters.usage_of(spec, unreadable)
            self.assertEqual((got.readable, got.fail_closed, got.rows), (False, True, ()))
        image = cn.PURPOSES["image_provider"]
        plain = quota.UsageView("image_provider", image.label, (quota.UsageRow("키 가", "Unsplash", "hour", 7, 50, False, "최근 60분"), quota.UsageRow("키 나", "Unsplash", "hour", 1, 50, False, "최근 60분")),
                                False, False, None, "", "", 2, (), None)
        self.assertEqual(adapters.usage_of(image, plain), services.UsageInfo((("최근 60분", 7, 50),)))                                  # 첫 항목의 한도 창만
        self.assertIsNone(adapters.usage_of(image, quota.UsageView("image_provider", image.label, (), False, False, None, "", "", 0, (), None)))
        self.assertIsNone(adapters.usage_of(image, None))
        blocked = quota.UsageView("image_provider", image.label, (), False, True, None, "오늘 18:00 이후 자동 재개", "", 1, (), None)
        self.assertEqual(adapters.usage_of(image, blocked), services.UsageInfo(resume_text="오늘 18:00 이후 자동 재개"))

    def test_the_real_usage_of_a_fresh_data_folder_is_zero_attempts_and_a_broken_record_is_unreadable_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp, repo="")
            provider = adapters.ServiceConnectionsProvider(context_factory=lambda data_dir=None: ctx)
            hub = provider.load_connections(lambda *a: None, lambda: False).purposes[0]
            self.assertEqual((hub.key, hub.usage.rows, hub.usage.console_limit, hub.usage.readable), ("naver_apihub", (("오늘", 0, 100), ("이번 달", 0, 27000)), 30000, True))
            ctx.workspace.root.mkdir(parents=True)
            ctx.workspace.quota_path.write_text("{ 깨진 파일", encoding="utf-8")                           # 사용량 기록이 깨졌다
            data = provider.load_connections(lambda *a: None, lambda: False)
            hub = data.purposes[0]
            self.assertEqual((hub.usage.readable, hub.usage.rows, hub.usage.fail_closed), (False, (), True))
            self.assertIn("usage", data.partial)
            self.assertEqual(ctx.workspace.quota_path.read_text(encoding="utf-8"), "{ 깨진 파일")           # 읽기만 한다 — 깨진 파일을 옮기거나 고치지 않았다
            self.assertFalse(ctx.workspace.quota_path.with_name("quota_state.json.bak").exists())
            view = sv.build_settings_view(data, "partial")
            self.assertEqual([banner[1] for banner in view["banners"]], [text.T["conn_partial_usage"]])
            self.assertEqual(cards_of(view)["naver_apihub"]["usage"]["rows"][0]["text"], text.T["usage_unreadable_closed"])
            self.assertTrue(all(card["usage"] is None for key, card in cards_of(view).items() if key != "naver_apihub"))      # 키 항목이 없는 용도는 셀 것도 없다


class SampleTagTest(unittest.TestCase):
    def test_every_usage_row_of_every_sample_scenario_carries_the_example_tag(self):
        seen = 0
        for scenario in services.CONN_SCENARIOS:
            if scenario in ("empty", "error"):
                continue
            data = services.FakeConnectionsProvider(scenario).load_connections(lambda *a: None, lambda: False)
            view = sv.build_settings_view(data, "partial" if scenario == "partial" else "normal")
            self.assertTrue(view["sample"], scenario)
            for card in cards_of(view).values():
                for row in (card["usage"] or {"rows": []})["rows"]:
                    seen += 1
                    self.assertEqual(row["tag"], "예시", f"{scenario}: {row['text']}")
        self.assertGreater(seen, 8)

    def test_a_real_data_view_has_no_example_tag_and_no_example_badge(self):
        data = services.ConnectionsData(purposes=(info("naver_apihub", usage=services.UsageInfo((("오늘", 1, 100),), True, 30000)),), sample=False)
        view = sv.build_settings_view(data, "normal")
        self.assertFalse(view["sample"])
        self.assertEqual([row["tag"] for card in cards_of(view).values() for row in card["usage"]["rows"]], ["", ""])               # 숫자 줄과 콘솔 한도 줄 — 둘 다 꼬리표가 없다
        self.assertNotIn("예시", json.dumps(view["groups"], ensure_ascii=False))
        state = app_state.AppState(services.FakeHomeProvider(), connections=services.FakeConnectionsProvider())
        self.assertFalse(state.settings_view()["sample"])                                                  # 아직 아무것도 못 받았을 때
        state.apply_connections(data)
        self.assertFalse(state.settings_view()["sample"])
        state.apply_connections(services.FakeConnectionsProvider().load_connections(lambda *a: None, lambda: False))
        self.assertTrue(state.settings_view()["sample"])

    def test_the_fake_service_table_is_the_real_one_except_that_only_the_example_pretends_one_purpose_has_call_code(self):
        table = {row[0]: row for row in services._CONN_TABLE}
        self.assertEqual(list(table), list(cn.PURPOSE_ORDER))
        for key, spec in cn.PURPOSES.items():
            _key, label, implemented, takes_keys, max_entries, rotation, legacy = table[key]
            self.assertEqual((label, takes_keys, max_entries, rotation, legacy), (spec.label, spec.takes_keys, spec.max_entries, spec.providers[0].rotation, bool(spec.legacy_to)), key)
        self.assertEqual([key for key, row in table.items() if row[2]], ["image_provider"])               # 예시에서만 — 실제 서비스는 아무도 호출 코드가 없다
        self.assertEqual([key for key, spec in cn.PURPOSES.items() if spec.implemented], [])

    def test_each_sample_scenario_gives_its_own_screen_state_and_the_five_connection_statuses_are_all_visible_in_the_normal_one(self):
        expected = {"normal": "normal", "empty": "empty", "partial": "partial", "offline": "offline", **{status: "normal" for status in FIVE}}
        for scenario, state in expected.items():
            provider = services.FakeConnectionsProvider(scenario)
            holder = app_state.AppState(services.FakeHomeProvider(), connections=provider)
            holder.apply_connections(provider.load_connections(lambda *a: None, lambda: False))
            self.assertEqual(holder.conn_state, state, scenario)
        with self.assertRaises(jobs.JobFailure):
            services.FakeConnectionsProvider("error").load_connections(lambda *a: None, lambda: False)
        with self.assertRaises(ValueError):
            services.FakeConnectionsProvider("nope")
        normal = view_of(*services.sample_connections("normal"), sample=True)
        self.assertEqual({card["conn"]["text"] for card in cards_of(normal).values() if card["conn"]}, {text.T["status_" + status] for status in FIVE})

    def test_each_status_scenario_puts_that_status_on_every_purpose_that_can_have_it(self):
        for status in FIVE:
            view = view_of(*services.sample_connections(status), sample=True)
            shown = [card["conn"]["text"] for card in cards_of(view).values() if card["conn"]]
            self.assertEqual(len(shown), 4 if status == "not_connected" else 5, status)                    # 키 항목이 하나도 없는 처음 모습에서는 검색광고 카드가 안 보인다(§34)
            if status == "connected":                                                                      # 호출 코드가 있는 용도(예시의 이미지 공급자)만 '연결됨' — 나머지는 확인 필요
                self.assertEqual(sorted(shown), sorted(["연결됨"] + ["연결 확인 필요"] * 4))
                self.assertEqual([key for key, card in cards_of(view).items() if card["conn"] and card["conn"]["text"] == "연결됨"], ["image_provider"])
            else:
                self.assertEqual(set(shown), {text.T["status_" + status]}, status)
        fresh = services.sample_connections("not_connected")
        self.assertEqual([item.entries for item in fresh], [()] * len(fresh))                              # 키를 하나도 넣지 않은 처음 모습
        self.assertEqual({chip["text"] for group in view_of(*fresh)["groups"] for chip in group["chips"]}, {"준비 중 1"})

    def test_the_partial_sample_cannot_know_whether_keys_exist_and_cannot_say_connected(self):
        data = services.FakeConnectionsProvider("partial").load_connections(lambda *a: None, lambda: False)
        self.assertEqual(data.partial, ("keystore", "usage"))
        for item in data.purposes:
            self.assertTrue(all(entry.key_found is None for entry in item.entries), item.key)
            self.assertNotEqual(item.status, "connected", item.key)
        view = sv.build_settings_view(data, "partial")
        self.assertEqual([banner[1] for banner in view["banners"]], [text.T["conn_partial_keystore"], text.T["conn_partial_usage"]])
        self.assertNotIn("연결됨", json.dumps(view["groups"], ensure_ascii=False))


class NoInternalCodesTest(Base):
    def test_no_english_state_name_internal_key_or_error_code_is_in_any_visible_text(self):
        views = []
        for scenario in services.CONN_SCENARIOS:
            if scenario == "error":
                continue
            data = services.FakeConnectionsProvider(scenario).load_connections(lambda *a: None, lambda: False)
            views.append((scenario, sv.build_settings_view(data, "partial" if scenario == "partial" else "offline" if scenario == "offline" else "empty" if scenario == "empty" else "normal")))
        self.add("naver_apihub", "내 키", HUB)
        self.add("ai_assist", "보조 키", AI)
        views.append(("real", view_of(*self.read().purposes)))
        views.append(("loading", sv.build_settings_view(None, "loading")))
        for name, view in views:
            for shown in visible_strings(view):
                self.assertIsNone(INTERNAL.search(shown), f"{name}: 영문 내부 이름이 보인다: {shown!r}")
                self.assertIsNone(UPPER_CODE.search(shown), f"{name}: 오류 코드가 보인다: {shown!r}")

    def test_the_card_names_come_from_the_service_table_and_the_picture_keys_are_the_only_english(self):
        view = view_of(*[info(key) for key in ("naver_apihub", "naver_searchad", "image_provider", "ai_assist", "blogger", "github_repo")])
        self.assertEqual([card["name"] for group in view["groups"] for card in group["cards"]],
                         [cn.PURPOSES[key].label for key in ("naver_apihub", "naver_searchad", "image_provider", "ai_assist", "blogger", "github_repo")])
        english = {chip["tone"] for group in view["groups"] for chip in group["chips"]} | {card["ready"]["tone"] for group in view["groups"] for card in group["cards"]}
        self.assertLessEqual(english, {"muted", "info", "ok", "warning", "danger"})                         # 글이 아니라 색을 고르는 이름


class AdapterTest(Base):
    def test_reading_creates_no_file_and_changes_none_and_leaves_the_store_untouched(self):
        self.assertFalse(self.ctx.workspace.root.exists())
        data = self.read()
        self.assertFalse(self.ctx.workspace.root.exists(), "데이터 폴더를 만들었다")
        self.assertEqual((data.sample, data.offline, data.partial), (False, False, ()))
        self.add("naver_apihub", "내 키", HUB)
        self.add("image_provider", "이미지 키", IMAGE)
        before, blobs = support.tree_snapshot(self.ctx.workspace.root), dict(self.store._blobs)
        for _ in range(2):
            self.read()
        self.assertEqual(support.tree_snapshot(self.ctx.workspace.root), before)
        self.assertEqual(self.store._blobs, blobs)

    def test_an_empty_install_lists_six_purposes_all_not_connected_with_no_entries(self):
        data = self.read()
        self.assertEqual([(item.key, item.status, item.entries, item.implemented) for item in data.purposes],
                         [("naver_apihub", "not_connected", (), False), ("naver_searchad", "not_connected", (), False), ("image_provider", "not_connected", (), False),
                          ("ai_assist", "not_connected", (), False), ("blogger", "not_connected", (), False), ("github_repo", "", (), False)])
        view = view_of(*data.purposes)
        self.assertEqual([item.key for item in data.purposes if item.on_demand], ["naver_searchad"])                       # 어댑터는 여섯을 읽어 오되 검색광고에 '필요할 때만 보임' 표시를 단다
        self.assertEqual(sorted(cards_of(view)), ["ai_assist", "blogger", "github_repo", "image_provider", "naver_apihub"])   # 항목이 없는 검색광고는 카드가 없다(§34 '실제 연결 시에만')
        self.assertEqual([group["summary"] for group in view["groups"]], ["준비 중 1", "준비 중 1", "준비 중 1", "준비 중 1"])
        self.assertEqual(sv.default_open(data.purposes), "data")

    def test_a_search_ad_entry_makes_its_card_appear_and_the_sample_flags_the_same_purpose(self):
        self.add("naver_searchad", "광고 키", {"customer_id": "1234567", "access_license": "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6", "secret_key": "Q7r8S9t0U1v2W3x4Y5z6A7b8C9d0E1f2"})
        cards = cards_of(view_of(*self.read().purposes))
        self.assertIn("naver_searchad", cards)
        self.assertEqual([entry["name"] for entry in cards["naver_searchad"]["entries"]], ["광고 키"])
        self.assertEqual([item.key for item in services.sample_connections("normal") if item.on_demand], ["naver_searchad"])            # 예시도 같은 규칙을 쓴다
        self.assertIn("naver_searchad", cards_of(view_of(*services.sample_connections("normal"), sample=True)))                          # 예시에는 항목이 있어 보인다
        self.assertNotIn("naver_searchad", cards_of(view_of(*services.sample_connections("not_connected"), sample=True)))                # 처음 모습에서는 안 보인다

    def test_the_adapter_hands_over_the_service_table_entry_limit_so_the_api_hub_card_offers_only_use_and_off(self):
        """점검 A08 — 어댑터가 항목 수 상한(`max_entries`)을 굳은 값(3)으로 넘기면 NAVER API HUB 카드에 '예비' 가 생긴다. 어댑터가 넘긴 값이 서비스 표와 같고, 같은 화면의 API HUB 선택지는 [사용, 꺼짐]이다."""
        by_key = {item.key: item for item in self.read().purposes}
        for key, spec in cn.PURPOSES.items():
            if not spec.legacy_to:
                self.assertEqual((by_key[key].max_entries, by_key[key].takes_keys), (spec.max_entries, spec.takes_keys), key)
        self.assertEqual([(key, by_key[key].max_entries) for key in ("naver_apihub", "naver_searchad", "image_provider", "ai_assist", "blogger")],
                         [("naver_apihub", 1), ("naver_searchad", 3), ("image_provider", 3), ("ai_assist", 3), ("blogger", 3)])
        cards = cards_of(view_of(*by_key.values()))
        self.assertEqual(cards["naver_apihub"]["choices"]["items"], ["사용", "꺼짐"])                                        # 같은 화면에서 API HUB 선택지는 [사용, 꺼짐]
        self.assertNotIn("예비", json.dumps(cards["naver_apihub"], ensure_ascii=False))
        self.assertEqual(cards["blogger"]["choices"]["items"], ["사용", "예비", "꺼짐"])                                     # 전환하는 용도는 그대로 세 가지

    def test_the_adapter_hands_over_the_service_table_switch_rule_so_the_image_card_does_not_promise_a_switch(self):
        """점검 A07 — 어댑터가 전환 규칙(`rotation`)을 굳은 값(limited)으로 넘기면 이미지 공급자가 거짓으로 '다음 키로 넘어가요' 라고 말한다."""
        by_key = {item.key: item for item in self.read().purposes}
        for key, spec in cn.PURPOSES.items():
            if not spec.legacy_to:
                self.assertEqual(by_key[key].rotation, spec.providers[0].rotation, key)
        self.assertEqual([(key, by_key[key].rotation) for key in ("naver_apihub", "image_provider", "blogger")], [("naver_apihub", "never"), ("image_provider", "never"), ("blogger", "limited")])
        cards = cards_of(view_of(*by_key.values()))
        self.assertEqual(cards["image_provider"]["policy"], text.T["policy_never"])
        self.assertNotIn("다음 키로 넘어가요", cards["image_provider"]["policy"])                                            # 이미지 공급자는 넘어가지 않는다
        self.assertEqual(cards["image_provider"]["choices"]["items"], ["사용", "꺼짐"])
        self.assertEqual(cards["blogger"]["policy"], "예비: 한도·일시 오류일 때만 다음 키로 넘어가요(용도당 최대 3개)")

    def test_a_broken_usage_record_makes_a_purpose_without_a_ledger_unreadable_instead_of_half_used(self):
        """점검 A05 — 서비스는 깨진 기록을 '절반을 썼다고 가정' 한 숫자로 보여 주지만 실제 값이 아니다. 장부가 없는 용도(이미지 공급자)도 숫자 없이 '확인할 수 없어요' 로 보인다."""
        image = cn.PURPOSES["image_provider"]
        half = quota.UsageView("image_provider", image.label, (quota.UsageRow("키 가", "Unsplash", "hour", 25, 50, False, "최근 60분"),), False, False, None, "", "기록 파일을 읽을 수 없어요", 1, (), None)
        got = adapters.usage_of(image, half)
        self.assertEqual((got.readable, got.rows, got.fail_closed), (False, (), False))
        self.add("image_provider", "이미지 키", IMAGE)
        self.ctx.workspace.quota_path.write_text("{ 깨진 파일", encoding="utf-8")
        data = self.read()
        by_key = {item.key: item for item in data.purposes}
        self.assertFalse(by_key["image_provider"].usage.readable)
        self.assertIn("usage", data.partial)
        rows = cards_of(view_of(*data.purposes))["image_provider"]["usage"]["rows"]
        self.assertEqual([row["text"] for row in rows], [text.T["usage_unreadable"]])
        self.assertFalse(re.search(r"\d", rows[0]["text"]))                                                                     # 못 읽은 값으로 숫자를 지어내지 않는다

    def test_the_service_fixed_stop_sentence_reaches_the_screen_only_when_the_limit_was_really_reached(self):
        """통합 전달서 §34 — '…사용할 수 없습니다' 는 한도에 닿았을 때만. 인증이 아직 확실하지 않은 처음 모습에는 고장 난 것처럼 읽히므로 내지 않는다(사유 한 줄은 그대로)."""
        spec = cn.PURPOSES["naver_apihub"]
        cause = "인증 상태가 확실하지 않습니다 — 연결 시험에 성공한 기록이 있어야 새 호출을 합니다"
        ledger = quota.LedgerUsage(12, 10, 340, 300, 100, 27000, 30000, "", None, "ok", "", True, "auth_unclear", cause, cn.APIHUB_STOP_TEXT)
        view = quota.UsageView("naver_apihub", spec.label, (), False, False, None, "", "", 1, (), ledger)
        self.assertEqual(adapters.LIMIT_STOPS, ("blocked", "exhausted"))
        for code in ("auth_unclear", "auth_failed", "clock"):
            got = adapters.usage_of(spec, dataclasses.replace(view, ledger=dataclasses.replace(ledger, stop_code=code)))
            self.assertEqual((got.stop_text, got.stop_cause), ("", cause), code)
        for code in ("blocked", "exhausted"):
            self.assertEqual(adapters.usage_of(spec, dataclasses.replace(view, ledger=dataclasses.replace(ledger, stop_code=code))).stop_text, cn.APIHUB_STOP_TEXT, code)
        self.add("naver_apihub", "내 키", HUB)                                                                                  # 처음 넣은 키 — 연결 시험 기록이 아직 없다
        shown = json.dumps(cards_of(view_of(*self.read().purposes))["naver_apihub"], ensure_ascii=False)
        self.assertNotIn("사용할 수 없습니다", shown)
        self.assertNotIn(cn.APIHUB_STOP_TEXT, shown)

    def test_entries_show_their_name_and_setting_and_whether_the_store_has_them_never_the_value(self):
        self.add("naver_apihub", "내 키", HUB)
        self.add("ai_assist", "보조 키", AI, state=cn.STANDBY)
        data = self.read()
        by_key = {item.key: item for item in data.purposes}
        self.assertEqual(by_key["naver_apihub"].entries, (services.EntryInfo("내 키", "active", True),))
        self.assertEqual(by_key["ai_assist"].entries, (services.EntryInfo("보조 키", "standby", True),))
        self.assertEqual((by_key["naver_apihub"].status, by_key["ai_assist"].status), ("needs_check", "not_connected"))        # 사용 항목이 없으면 연결 안 됨

    def test_a_missing_data_dir_and_a_broken_connection_file_are_easy_messages_with_the_code_only_for_the_diagnostics(self):
        absent = adapters.ServiceConnectionsProvider(str(Path(self.tmp.name) / "없는 폴더"), context_factory=lambda data_dir=None: self.ctx)
        with self.assertRaises(jobs.JobFailure) as caught:
            absent.load_connections(lambda *a: None, lambda: False)
        self.assertEqual((caught.exception.user_message, caught.exception.code), (text.T["data_dir_missing"], "DATA_DIR_NOT_FOUND"))
        self.add("naver_apihub", "내 키", HUB)
        self.ctx.workspace.connections_path.write_text("{ 깨진 파일 " + GOOGLE_KEY, encoding="utf-8")
        before = self.ctx.workspace.connections_path.read_bytes()
        with self.assertRaises(jobs.JobFailure) as caught:
            self.read()
        failure = caught.exception
        self.assertEqual((failure.user_message, failure.code), (text.T["conn_file_invalid"], "CONNECTIONS_FILE_INVALID"))
        for piece in ("keys", "`", ".bak", "connections.json", "깨진", GOOGLE_KEY[:12]):
            self.assertNotIn(piece, failure.user_message)
        self.assertEqual(self.ctx.workspace.connections_path.read_bytes(), before)                       # 고치거나 지우지 않았다
        state = app_state.AppState(services.FakeHomeProvider(), connections=self.provider)
        state.apply_conn_failure(failure, datetime.datetime(2026, 11, 6, 10, 0, 0))
        view = state.settings_view()
        self.assertEqual((view["state"], view["error"]["user"]), ("error", text.T["conn_file_invalid"]))
        self.assertEqual(view["error"]["diag"], "code: CONNECTIONS_FILE_INVALID\ntime: 2026-11-06 10:00:00")
        self.assertEqual(view["groups"], [])
        self.assertNotIn("CONNECTIONS_FILE_INVALID", json.dumps({key: value for key, value in view.items() if key != "error"}, ensure_ascii=False))

    def test_an_unsafe_data_folder_has_an_easy_sentence_too_and_other_service_errors_use_the_home_wording(self):
        error = AppError("DATA_DIR_UNSAFE", {"경로": "C:\\x"}, detail="git 저장소 안이다")
        failure = adapters.settings_failure(error)
        self.assertEqual((failure.user_message, failure.code), (text.T["conn_dir_unsafe"], "DATA_DIR_UNSAFE"))
        other = adapters.settings_failure(AppError("FILE_WRITE_FAILED", {"경로": "C:\\x"}))
        self.assertEqual((other.user_message, other.code), (text.T["data_unreadable"], "FILE_WRITE_FAILED"))
        self.assertEqual(set(adapters.SETTINGS_WORDED), {"CONNECTIONS_FILE_INVALID", "DATA_DIR_UNSAFE"})

    def test_a_store_that_cannot_be_opened_marks_the_read_partial_and_never_claims_a_key_exists(self):
        self.add("naver_apihub", "내 키", HUB)
        self.add("image_provider", "이미지 키", IMAGE)
        self.ctx.keystore = None
        self.ctx.get_keystore = lambda: (_ for _ in ()).throw(AppError("KEY_STORE_UNAVAILABLE"))
        data = self.read()
        self.assertEqual(data.partial, ("keystore",))
        by_key = {item.key: item for item in data.purposes}
        self.assertEqual([entry.key_found for entry in by_key["naver_apihub"].entries], [None])
        self.assertEqual((by_key["naver_apihub"].status, by_key["image_provider"].status), ("needs_check", "needs_check"))
        view = sv.build_settings_view(data, "partial")
        self.assertEqual([banner[1] for banner in view["banners"]], [text.T["conn_partial_keystore"]])
        self.assertEqual(cards_of(view)["naver_apihub"]["entries"][0]["missing"], "")                    # 모르는 것을 '없다' 고 말하지 않는다

    def test_a_store_that_fails_on_one_question_marks_the_read_partial_as_well(self):
        class Flaky(MemoryStore):
            def exists(self, ref):
                raise AppError("KEY_STORE_UNAVAILABLE")
        self.add("naver_apihub", "내 키", HUB)
        data = self.read(adapters.ServiceConnectionsProvider(context_factory=lambda data_dir=None: self.ctx, keystore=Flaky()))
        self.assertEqual(data.partial, ("keystore",))
        self.assertEqual(data.purposes[0].entries[0].key_found, None)

    def test_the_provider_is_read_only_by_construction_it_calls_no_writer_of_the_service(self):
        source = (UI_DIR / "adapters.py").read_text(encoding="utf-8")
        start = source.index("class ServiceConnectionsProvider")
        body = source[start:]
        for forbidden in ("add_entry", "remove_entry", "set_state", "reorder", "set_policy", "mark_check", "mark_call_ok", "test_entry", "acquire", "report(", "acknowledge", "record_cache_hit",
                          ".put(", ".delete(", "write_json", "save(", "keep_bad_copy", "locked("):
            self.assertNotIn(forbidden, body, forbidden)

    def test_the_provider_never_reads_a_key_value_nor_the_tail_it_only_asks_whether_the_store_has_it(self):
        self.add("naver_apihub", "내 키", HUB)
        self.add("image_provider", "이미지 키", IMAGE)
        self.add("ai_assist", "보조 키", AI)

        class Spy(MemoryStore):
            def __init__(self, blobs):
                super().__init__()
                self._blobs, self.gets, self.asked = dict(blobs), 0, []

            def get(self, ref):
                self.gets += 1
                raise AssertionError("화면 어댑터가 키 값을 꺼냈다")

            def exists(self, ref):
                self.asked.append(ref)
                return super().exists(ref)

        spy = Spy(self.store._blobs)
        provider = adapters.ServiceConnectionsProvider(context_factory=lambda data_dir=None: self.ctx, keystore=spy)
        original = cn.list_entries
        cn.list_entries = lambda *a, **k: (_ for _ in ()).throw(AssertionError("끝 4자를 만드는 `list_entries` 를 불렀다"))
        try:
            data = self.read(provider)
        finally:
            cn.list_entries = original
        self.assertEqual(spy.gets, 0)
        self.assertGreaterEqual(len(spy.asked), 3)
        self.assertTrue(all(ref.split(":")[0] in ("naver_apihub", "image_provider", "ai_assist") for ref in spy.asked))
        self.assertEqual(len(data.purposes), 6)


class KeyHygieneTest(Base):
    def test_no_key_value_nor_its_last_four_characters_reaches_the_view_model_the_diagnostics_or_the_log(self):
        secrets = {"허브 시크릿": GOOGLE_KEY, "이미지": GITHUB_KEY, "보조": AI["key"]}
        self.add("naver_apihub", "내 키", HUB)
        self.add("image_provider", "이미지 키", IMAGE)
        self.add("ai_assist", "보조 키", AI)
        records, handler = [], logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        root = logging.getLogger()
        root.addHandler(handler)
        previous_level = root.level
        root.setLevel(logging.DEBUG)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                data = self.read()
                state = app_state.AppState(services.FakeHomeProvider(), connections=self.provider)
                state.apply_connections(data, datetime.datetime(2026, 11, 6, 10, 0, 0))
                view = state.settings_view()
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)
        shown = json.dumps(view, ensure_ascii=False) + repr(data) + sv.diag_text(data) + view["advanced"]["diag"] + out.getvalue() + err.getvalue() + " ".join(records)
        for name, secret in secrets.items():
            self.assertEqual(leaks(shown, secret, 6), [], f"{name} 의 조각이 보인다")
            self.assertNotIn("****" + secret[-4:], shown, name)                                           # `list_entries` 가 만드는 끝 4자 표시도 없다
        self.assertNotIn("****", shown)
        self.assertNotIn("hubclient001", shown)                                                          # 비밀이 아닌 칸(클라이언트 ID)도 화면 값이 아니다
        self.assertEqual(records, [])                                                                    # 읽는 동안 기록(log)을 남기지 않는다

    def test_a_key_shaped_purpose_name_is_masked_in_the_accessible_names_too(self):
        """L1 — 보이는 이름은 가렸는데 접근 이름(화면 읽기 프로그램이 읽는 글)만 용도 이름 원본이면 키 모양 글이 그대로 샌다."""
        weird = services.PurposeInfo("some_new_purpose", "서비스 " + GOOGLE_KEY, status="needs_check", entries=(services.EntryInfo("키 " + GITHUB_KEY, "active", True),))
        view = view_of(weird, info("blogger"), sample=True)
        card = cards_of(view)["some_new_purpose"]
        for secret in (GOOGLE_KEY, GITHUB_KEY):
            self.assertEqual(leaks(json.dumps(view, ensure_ascii=False), secret, 6), [], "뷰모델 어딘가에 키 모양 글이 남았다")
            self.assertEqual(leaks(card["a11y"], secret, 5), [], "접근 이름에 키 모양 글이 남았다")
        self.assertIn("가림", card["name"])
        self.assertTrue(card["a11y"].startswith(card["name"]))                                                              # 접근 이름의 첫 칸은 화면에 보이는 (가린) 이름이다

    def test_the_diagnostics_hold_the_time_the_counts_and_two_read_results_and_nothing_else(self):
        self.add("naver_apihub", "내 키", HUB)
        data = self.read()
        shown = sv.diag_text(data, datetime.datetime(2026, 11, 6, 10, 0, 0))
        self.assertEqual(shown, "time: 2026-11-06 10:00:00\npurposes: 6\nentries: 1\nkeystore: ok\nusage: ok")
        partial = dataclasses.replace(data, partial=("keystore", "usage"))
        self.assertTrue(sv.diag_text(partial).endswith("keystore: unavailable\nusage: unavailable"))
        self.assertNotRegex(shown, r"내 키|hubclient|AIza")


class AppStateTest(unittest.TestCase):
    def test_a_failure_text_with_a_key_shaped_piece_is_masked_before_the_view_model_holds_it(self):
        """점검 S04 — 실패한 읽기의 글·코드에 키 모양이 섞여 와도 상태에는 가린 글만 남아 뷰모델·진단 정보 어디에도 안 나온다."""
        state = app_state.AppState(services.FakeHomeProvider(), connections=services.FakeConnectionsProvider())
        state.apply_conn_failure(jobs.JobFailure("읽지 못했어요 " + GOOGLE_KEY, code="ERR_" + GITHUB_KEY), datetime.datetime(2026, 11, 6, 10, 0, 0))
        view = state.settings_view()
        self.assertEqual(view["state"], "error")
        shown = json.dumps(view, ensure_ascii=False) + repr(state.conn_failure.__dict__)
        for secret in (GOOGLE_KEY, GITHUB_KEY):
            self.assertEqual(leaks(shown, secret, 6), [], "실패 글의 키 모양이 상태에 남았다")
        self.assertTrue(view["error"]["user"].startswith("읽지 못했어요"))                                                      # 문장은 남고 키 모양만 가려진다

    def test_reading_runs_on_a_worker_thread_and_a_second_start_is_refused(self):
        class Slow(services.ConnectionsProvider):
            thread = None

            def load_connections(self, progress, cancelled):
                Slow.thread = threading.current_thread().name
                time.sleep(0.4)
                return services.ConnectionsData(purposes=services.sample_connections("normal"), sample=True)

        state = app_state.AppState(services.FakeHomeProvider(), connections=Slow())
        got = []
        started = time.perf_counter()
        job = state.start_conn_load(on_done=lambda result, _payload: got.append(result))
        self.assertIsNotNone(job)
        self.assertLess(time.perf_counter() - started, 0.3)                                               # 시작은 곧바로 돌아온다(읽기가 화면 스레드를 막지 않는다)
        self.assertEqual((state.conn_state, state.conn_loading), ("loading", True))
        self.assertIsNone(state.start_conn_load())                                                        # 중복 클릭은 거절
        self.assertTrue(job.join(5))
        self.assertEqual(Slow.thread, "job-" + app_state.CONN_KEY)
        self.assertNotEqual(Slow.thread, threading.current_thread().name)
        self.assertEqual(len(got), 1)
        state.apply_connections(got[0])
        self.assertEqual((state.conn_state, state.conn_loading), ("normal", False))
        self.assertEqual(state.load_count, 0)                                                             # 홈 불러오기와 따로다
        self.assertEqual(state.conn_load_count, 1)

    def test_a_reload_keeps_what_is_on_screen_but_a_retry_after_an_error_shows_the_reading_state(self):
        provider = services.FakeConnectionsProvider()
        state = app_state.AppState(services.FakeHomeProvider(), connections=provider)
        state.apply_connections(provider.load_connections(lambda *a: None, lambda: False))
        job = state.start_conn_load()
        job.join(5)
        self.assertEqual(state.conn_state, "normal")                                                      # 보이던 내용 그대로 두고 새 값이 오면 바꾼다
        state.apply_conn_failure(jobs.JobFailure("읽지 못했어요", code="X_Y"), None)
        self.assertEqual(state.conn_state, "error")
        self.assertIsNotNone(state.conn_data)                                                             # 이전 정보는 지우지 않는다
        state.start_conn_load().join(5)
        self.assertEqual(state.conn_state, "loading")                                                     # 다시 시도하면 읽는 중 모습 → 값이 오면 정상
        state.apply_connections(provider.load_connections(lambda *a: None, lambda: False))
        self.assertEqual((state.conn_state, state.conn_failure), ("normal", None))

    def test_a_slot_that_breaks_becomes_an_error_state_with_only_the_exception_name(self):
        fake = "AI" + "za" + "G" * 35
        state = app_state.AppState(services.FakeHomeProvider(), connections=services.FakeConnectionsProvider())
        state.apply_connections(services.FakeConnectionsProvider().load_connections(lambda *a: None, lambda: False))
        state.apply_conn_unexpected(ValueError(f"내부 값 C:\\비밀\\경로 {fake}"), datetime.datetime(2026, 11, 6, 10, 0, 0))
        view = state.settings_view()
        self.assertEqual((view["state"], state.conn_state), ("error", "error"))
        self.assertIsNone(state.conn_data)
        self.assertEqual(view["error"]["user"], text.T["job_failed"])
        self.assertEqual(view["error"]["diag"], "code: ValueError\ntime: 2026-11-06 10:00:00")
        for piece in (fake, "비밀", "C:\\", "내부 값"):
            self.assertNotIn(piece, json.dumps(view, ensure_ascii=False) + repr(vars(state.conn_failure)))

    def test_the_six_states_follow_the_data_and_each_state_has_its_own_view_model_shape(self):
        state = app_state.AppState(services.FakeHomeProvider(), connections=services.FakeConnectionsProvider())
        loading = state.settings_view()
        self.assertEqual((loading["state"], loading["groups"], loading["advanced"]["diag"], loading["banners"]), ("loading", [], "", []))
        for scenario, wanted, banners in (("normal", "normal", 0), ("partial", "partial", 2), ("offline", "offline", 1), ("empty", "empty", 0)):
            state.apply_connections(services.FakeConnectionsProvider(scenario).load_connections(lambda *a: None, lambda: False))
            view = state.settings_view()
            self.assertEqual((view["state"], len(view["banners"])), (wanted, banners), scenario)
            self.assertEqual(bool(view["groups"]), wanted != "empty", scenario)
        state.apply_conn_cancelled()
        self.assertEqual(state.conn_state, "empty")
        state.apply_connections(services.FakeConnectionsProvider().load_connections(lambda *a: None, lambda: False))
        state.apply_conn_cancelled()
        self.assertEqual(state.conn_state, "normal")                                                      # 취소하면 보이던 모습으로
        self.assertEqual(sv.build_settings_view(None, "loading")["loading"], {"text": text.T["conn_loading"], "a11y": text.T["conn_loading_a11y"]})

    def test_the_home_provider_hands_over_the_matching_settings_provider(self):
        self.assertIsInstance(services.FakeHomeProvider().connections_provider(), services.FakeConnectionsProvider)
        self.assertIsInstance(services.HomeProvider().connections_provider(), services.FakeConnectionsProvider)                  # 따로 정하지 않은 공급자는 예시(표시가 붙는다)
        real = adapters.ServiceHomeProvider("C:\\어딘가", context_factory=lambda data_dir=None: None)
        paired = real.connections_provider()
        self.assertIsInstance(paired, adapters.ServiceConnectionsProvider)
        self.assertEqual((paired._data_dir, paired._factory, paired.sample), ("C:\\어딘가", real._factory, False))
        state = app_state.AppState(real)
        self.assertIsInstance(state.conn_provider, adapters.ServiceConnectionsProvider)
        explicit = services.FakeConnectionsProvider("partial")
        self.assertIs(app_state.AppState(real, connections=explicit).conn_provider, explicit)
        self.assertIsInstance(app_state.AppState().conn_provider, services.FakeConnectionsProvider)

    def test_a_sample_reads_no_data_folder_no_store_and_no_file(self):
        provider = services.FakeHomeProvider().connections_provider()
        self.assertTrue(provider.sample)
        no_file = mock.patch("builtins.open", side_effect=AssertionError("파일을 열었다"))
        no_folder = mock.patch("os.listdir", side_effect=AssertionError("폴더를 봤다"))
        with no_file, no_folder:
            data = provider.load_connections(lambda *a: None, lambda: False)
        self.assertTrue(data.sample)
        self.assertEqual(len(data.purposes), 6)


class BadgeColorsTest(unittest.TestCase):
    def test_every_status_badge_text_is_readable_on_its_own_background_and_only_known_tones_are_used(self):
        colors = tokens.palette()
        for text_key, ground in (("success_text", "success_100"), ("warning_text", "warning_100"), ("danger_text", "danger_100"), ("primary_text", "primary_100"), ("text_secondary", "surface_2")):
            self.assertGreaterEqual(tokens.contrast(colors[text_key], colors[ground]), 4.5, f"{text_key} on {ground}")
        for ink in ("text_secondary", "text_primary", "text_strong", "warning_text"):                          # 준비 중 카드(회색 톤 — 꺼진 바탕 토큰) 위의 글자도 읽힌다
            self.assertGreaterEqual(tokens.contrast(colors[ink], colors["disabled_bg"]), 4.5, f"{ink} on disabled_bg")
        self.assertEqual(set(sv.STATUS_TONE.values()) | set(sv.READY_TONE.values()), {"muted", "info", "ok", "warning", "danger"})
        self.assertGreaterEqual(tokens.SIZE["acc_h"], tokens.SIZE["hit"])                                   # 접이식 머리는 누르는 칸 36 이상


class NoRealNamesTest(unittest.TestCase):
    """범용 원칙(운영자 2026-11-06) — 코드·시험·문서에 실제 블로그 이름·아이디·색 이름을 쓰지 않는다(예시는 가짜 이름만). 이 시험 자신도 낱말을 조각으로 이어 적는다."""
    WORDS = ("스마트" + "프라이싱", "실전" + "노트", "ssaess" + "ace", "shine" + "5652", "크" + "림", "코" + "랄", "민" + "트", "네이" + "비", "청" + "록")

    def test_the_screen_code_the_tools_and_the_new_tests_name_no_real_blog_and_no_blog_color(self):
        files = sorted(UI_DIR.rglob("*.py")) + [ROOT / "scripts" / "ui_capture.py", ROOT / "tests" / "test_ui_settings.py", ROOT / "tests" / "test_ui_qt_settings.py",
                                                ROOT / "docs" / "UI_COMPONENTS.md", ROOT / "docs" / "UI_DESIGN_SPEC.md", ROOT / "docs" / "UI_VISUAL_QA.md", ROOT / "docs" / "UI_STATES.md"]
        hits = {path.name: [word for word in self.WORDS if word in path.read_text(encoding="utf-8")] for path in files if path.exists()}
        self.assertEqual({name: found for name, found in hits.items() if found}, {})
        self.assertGreater(len(files), 12)

    def test_the_example_names_are_made_up_and_the_blog_labels_are_the_old_neutral_ones(self):
        sample_names = {entry.name for item in services.sample_connections("normal") for entry in item.entries}
        self.assertEqual(sample_names, {"예시 키 1", "예시 키 A", "예시 키 B"})
        self.assertEqual(app_state.BLOG_NAMES, {"A": "블로그 A", "B": "블로그 B"})


if __name__ == "__main__":
    unittest.main()
