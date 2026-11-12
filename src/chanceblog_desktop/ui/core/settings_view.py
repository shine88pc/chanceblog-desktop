"""설정 화면(연결 관리)의 뷰모델 — 순수 파이썬(화면 도구·서비스 층을 모른다). 공급자가 준 값(`ConnectionsData`)을 화면이 그리기만 하면 되는 딕셔너리로 바꾼다.

규칙(모두 시험이 지킨다):
  · **키 값은 어디에도 없다**(끝 글자도) — 받지도 않는다. 항목 이름은 비밀 모양을 가린 뒤에 줄인다.
  · 호출 코드가 없는 용도(`implemented` 가 거짓)는 '준비 중' 이고 연결 배지가 '연결됨' 일 수 없다 — 공급자가 '연결됨' 이라고 해도 '연결 확인 필요' 로 낮춘다(지어내지 않는다).
  · 키를 하나만 두거나(`max_entries == 1`) 어떤 오류에도 다른 키로 넘어가지 않는(`rotation == "never"`) 용도에는 '예비' 종류도 '키 더하기' 도 없다 — 이 규칙은 `single_choice` 한 곳이다.
  · 옛 용도(`legacy`)와 필요할 때만 보이는 용도(`on_demand`)는 항목이 남아 있거나 실제로 연결돼 있을 때만 카드로 보인다(`visible`).
  · 한도 줄은 기간마다 막대 한 줄('오늘 12 / 100회'·'이번 달 340 / 27,000회' — 뷰모델은 막대에 줄 숫자 칸 `bar` 만 더하고 색·퍼센트는 `gauges.usage_view` 규칙이 정한다)이고 서비스 고정 멈춤 문구는 한도에 실제로 닿았을 때만 보인다(어댑터가 거른다).
  · 항목의 '사용·예비·꺼짐' 은 연결 배지와 떼어 항목 줄의 작은 글("키 사용 설정: 사용")로만 보인다.
  · 예시 데이터(`sample`)는 모든 사용량 줄 끝에 '예시' 꼬리표가 붙는다. 못 읽은 사용량은 숫자 대신 '확인할 수 없어요' 이다.
  · 접이식 묶음은 다섯이다(UI-C1b) — 용도 묶음 넷(데이터 Provider·이미지·AI 보조·발행·연결 = `groups`)과 마지막 '정보'(`info` — 버전 + 접어 둔 진단 정보). 새 이름·구조는 운영자 2026-11-06 확인 요청 004 의 답 7.
  · 영문 상태 이름(`needs_check`·`rotation`·`standby` …)은 뷰모델의 글에 담기지 않는다 — 글은 문구표(`T`)에서만 온다(`key`·`tone`·`icon` 은 글이 아니라 그림·묶음을 고르는 값이다).
  · 특정 사람의 블로그에 맞춘 문장이 없다 — 용도 목록은 서비스 표에서, 문장은 문구표에서, 색은 토큰에서 온다.
"""
from __future__ import annotations

import datetime

from ... import capabilities
from . import gauges as G
from .services import CONN_PROBLEMS, CONN_STATUSES, GROUP_ORDER, PURPOSE_GROUPS
from .text import T, display_text

STATUS_TONE = {"not_connected": "muted", "needs_check": "warning", "connected": "ok", "auth_error": "danger", "rate_limited": "warning"}
READY_TONE = {"prep": "muted", "ok": "info", "nokey": "muted", "legacy": "muted"}
CHIP_ORDER = ("auth_error", "rate_limited", "needs_check", "connected")      # 묶음 머리 요약에 세는 연결 상태 — '연결 안 됨' 은 문제가 아니라서 세지 않는다
FALLBACK_GROUP = "data"                                                       # 표에 없는 새 용도가 숨지 않고 보이는 곳(표와 서비스 표가 어긋나면 시험이 알린다)
STATES = ("active", "standby", "off")
PARTIAL_TEXT = {"keystore": "conn_partial_keystore", "usage": "conn_partial_usage"}
INFO_GROUP = "info"                                                           # '정보' 묶음의 이름 — 서비스(용도) 묶음이 아니라 앱 정보라 `GROUP_ORDER`(용도 묶음 네 개)에는 없고 목록의 마지막 줄이다(UI-C1b)


def _shown(value, limit=300):
    return display_text(value, limit)                                          # 명령줄 출력·홈 화면과 같은 가리기 규칙(가린 뒤에 줄인다) — 화면 글의 한 지점(`text.display_text`)


def group_of(key):
    return PURPOSE_GROUPS.get(key, FALLBACK_GROUP)


def effective_status(info):
    """용도의 연결 배지에 보일 상태(다섯 가지 중 하나, 없으면 ''). 호출 코드가 없는 용도는 '연결됨' 이 될 수 없다 — 공급자가 그렇게 알려 와도 '연결 확인 필요' 로 낮춘다."""
    if not info.takes_keys or info.legacy:
        return ""
    status = info.status if info.status in CONN_STATUSES else "needs_check"
    return "needs_check" if status == "connected" and not info.implemented else status


def ready_kind(info):
    """'준비' 배지의 종류 — prep(호출 코드 없음) · ok(사용할 수 있어요) · nokey(키를 받지 않음) · legacy(옛 항목)."""
    if info.legacy:
        return "legacy"
    if not info.takes_keys:
        return "nokey"
    return "ok" if info.implemented else "prep"


def single_choice(info):
    """'예비' 가 하는 일이 없는 용도인가 — 키를 하나만 두거나(`max_entries == 1`) 어떤 오류에도 다른 키로 넘어가지 않는(`rotation == "never"`) 용도. '예비' 는 한도·일시 오류일 때 다음으로 넘어가는 키라
    넘어갈 일이 없으면 있어도 쓰이지 않는다. '예비' 를 숨기는 규칙은 이 함수 한 곳이다(`state_choices`·`entry_state` 가 이것만 본다)."""
    return info.max_entries == 1 or info.rotation == "never"


def state_choices(info):
    """키 사용 설정의 종류 — 전환할 키가 없는 용도(`single_choice`)는 '예비' 가 없다. 이 화면은 읽기만 하므로 고르는 곳이 아니라 어떤 종류가 있는지 알리는 글이다."""
    return ("active", "off") if single_choice(info) else ("active", "standby", "off")


def entry_state(info, entry):
    """항목 줄에 보이는 키 사용 설정. 전환할 키가 없는 용도(`single_choice`)의 '예비' 는 쓰이지 않는 것이라 '꺼짐' 으로 보인다(그 항목은 사용 중이 아니고 다른 키로 넘어가지도 않는다)."""
    state = entry.state if entry.state in STATES else "off"
    return "off" if state == "standby" and single_choice(info) else state


def policy_text(info, cap=None):
    """카드의 키 전환 안내. `cap` 은 키를 새로 더할 수 있는 최대 개수(제공자별 운영자 정책 — 쓰는 공급자의 카드만 준다). 안 주면 읽을 때 천장(`max_entries`)을 따른다(읽기 전용 카드는 이전과 같다)."""
    if not info.takes_keys or info.legacy:
        return ""
    limit = info.max_entries if cap is None else cap
    if limit == 1:
        return T["policy_single"]
    if info.rotation == "never":
        return T["policy_never"]
    return T["policy_failover"].format(n=limit)


def entry_vm(info, entry):
    return {"name": _shown(entry.name, 40) or T["entry_unnamed"], "state_line": T["entry_state"].format(state=T["state_" + entry_state(info, entry)]),
            "missing": T["entry_missing"] if entry.key_found is False else ""}


def _text_row(text, tag, note):
    return {"text": text, "tag": tag, "note": note, "bar": None}


def _bar_row(span, used, limit, tag):
    """기간 하나의 사용량 줄 — `text`(`오늘 12 / 100회`)와 막대에 줄 **숫자 칸** `bar`(기간 이름·쓴 수·한도·단위, 반올림한 정수). 숫자가 없거나 숫자가 아니거나 음수·한도 0 이하면 숫자를 지어내지 않고
    `오늘 확인할 수 없어요` 이고 `bar` 의 숫자는 None 이다(화면은 막대 없이 글만 그린다 — 0 으로 채우지 않는다). 글은 막대 부품과 같은 규칙(`gauges.usage_view`) 한 곳에서 나온다."""
    title, unit = _shown(span, 30), T["usage_unit"]
    view = G.usage_view(used, limit, unit, title)
    return {"text": view.text, "tag": tag, "note": False, "bar": {"title": title, "used": view.used, "limit": view.limit, "unit": unit}}


def usage_vm(info, sample):
    """한도 줄 — **기간마다 막대 한 줄**(`bar` 칸의 숫자를 화면이 `UsageBar` 로 그린다: 오늘 12 / 100회·이번 달 340 / 27,000회), 읽은 숫자는 그대로, 못 읽었으면 숫자를 지어내지 않고 막대 없이 '확인할 수 없어요'.
    콘솔 한도·한도 단계·멈춤 문구는 막대가 없는 작은 글 줄(`bar` 가 None). 예시 데이터는 줄마다 '예시' 꼬리표. 보일 것이 없으면 None."""
    usage = info.usage
    if usage is None:
        return None
    tag = T["usage_sample"] if sample else ""
    rows = []
    if not usage.readable:
        rows.append(_text_row(T["usage_unreadable_closed"] if usage.fail_closed else T["usage_unreadable"], tag, False))
        if usage.stop_cause:                                                  # 왜 못 믿는지 한 줄(서비스가 쉬운 한국어로 준다)
            rows.append(_text_row(_shown(usage.stop_cause, 200), tag, True))
    else:
        rows.extend(_bar_row(span, used, limit, tag) for span, used, limit in usage.rows)
        if usage.rows:
            small = ([T["usage_console"].format(n=f"{usage.console_limit:,}")] if usage.console_limit else []) + ([T["usage_attempts_note"]] if usage.attempts else [])
            if small:                                                             # 콘솔 한도·'실패한 호출도 센다' 는 작은 글로 따로 — 막대 줄은 '오늘 12 / 100회' 만 말한다
                rows.append(_text_row(" · ".join(small), tag, True))
        for note in (usage.stage_text, usage.stop_text, usage.stop_cause, usage.resume_text):
            if note:
                rows.append(_text_row(_shown(note, 200), tag, True))
    return {"title": T["usage_title"], "rows": rows} if rows else None


def card_vm(info, sample, keys=None):
    status, kind = effective_status(info), ready_kind(info)
    ready = {"text": T["ready_" + kind], "tone": READY_TONE[kind]}
    conn = {"text": T["status_" + status], "tone": STATUS_TONE[status]} if status else None
    note = {"prep": T["prep_note"], "nokey": T["nokey_note"], "legacy": T["legacy_note"], "ok": ""}[kind]
    desc = T.get("purpose_" + info.key, "")
    if kind == "nokey" and info.key == "github_repo" and not capabilities.external_write_enabled():          # 외부 게시가 꺼진 빌드는 Git 로그인을 쓰지 않는다 — 그렇게 말하지 않는다
        desc, note = T["purpose_github_repo_off"], T["nokey_note_off"]
    elif kind == "nokey" and info.key == "blogger":                                                         # Blogger 입력이 꺼진 빌드 — 입력 칸·단추 없이 이유만 보인다
        desc, note = T["purpose_blogger_off"], T["blogger_off_note"]
    choices = None if (not info.takes_keys or info.legacy) else {"label": T["choices_label"], "items": [T["state_" + state] for state in state_choices(info)]}
    entries = [entry_vm(info, entry) for entry in info.entries]
    name = _shown(info.label, 80)                                                # 화면 글과 접근 이름이 같은 가린 이름을 쓴다(키 모양 이름이 접근 이름에만 새지 않게)
    heard = [name, ready["text"]] + ([conn["text"]] if conn else []) + ([T["sample_tag"]] if sample else [])
    title = T.get("limit_" + info.key, "")                                       # 한도에 닿으면 어떻게 계속하는지(용도마다 문구표에 있을 때만)
    limit = {"title": title, "desc": T.get("limit_desc_" + info.key, "")} if title and info.takes_keys and not info.legacy else None
    return {"key": info.key, "name": name, "desc": desc, "gray": kind in ("prep", "legacy"), "ready": ready, "conn": conn,
            "ready_caption": T["ready_caption"], "conn_caption": T["conn_caption"], "note": note, "policy": policy_text(info, keys.effective_cap(info) if keys is not None and keys.writable else None), "limit": limit, "choices": choices,
            "entries_title": T["entries_title"], "entries": entries, "usage": usage_vm(info, sample), "a11y": ", ".join(heard),
            "keys": keys.card_keys(info, sample) if keys is not None else None}      # 키 행동(P4f) — 쓰는 공급자일 때만 값이 있다(없으면 카드는 읽기 전용 그대로)


def chips_of(infos):
    """묶음 머리의 요약 칩 — '준비 중 N' 먼저, 이어서 연결 상태별 개수(문제가 되는 것부터). 항목(용도) 상태를 그대로 센다."""
    chips = []
    prep = sum(1 for info in infos if ready_kind(info) == "prep")
    if prep:
        chips.append({"text": T["conn_chip_prep"].format(n=prep), "tone": READY_TONE["prep"]})
    counts = {}
    for info in infos:
        status = effective_status(info)
        counts[status] = counts.get(status, 0) + 1
    for status in CHIP_ORDER:
        if counts.get(status):
            chips.append({"text": T["conn_chip_status"].format(status=T["status_" + status], n=counts[status]), "tone": STATUS_TONE[status]})
    return chips


def has_problem(infos):
    return any(effective_status(info) in CONN_PROBLEMS for info in infos)


def visible(info):
    """카드로 보일 용도인가 — 옛 용도(`legacy`)와 필요할 때만 보이는 용도(`on_demand`)는 키 항목이 남아 있거나 실제로 연결돼 있을 때만 보인다. 나머지는 늘 보인다."""
    if info.legacy or info.on_demand:
        return bool(info.entries) or effective_status(info) == "connected"
    return True


def grouped(purposes):
    """용도들을 네 묶음으로 나눈다 — 묶음 순서대로 (묶음 이름, 용도들). 보이지 않는 용도(`visible`)는 빠진다. 보이는 한 용도는 정확히 한 묶음에 든다."""
    shown = [info for info in purposes if visible(info)]
    return [(key, [info for info in shown if group_of(info.key) == key]) for key in GROUP_ORDER]


def default_open(purposes):
    """처음 펼칠 묶음 — 문제(인증 정보 오류·요청 한도 도달)가 있는 첫 묶음, 없으면 '데이터'."""
    for key, infos in grouped(purposes):
        if has_problem(infos):
            return key
    return GROUP_ORDER[0]


def group_vm(key, infos, opened, sample, keys=None):
    chips = chips_of(infos)
    title = T["conn_group_" + key]
    summary = " · ".join(chip["text"] for chip in chips)
    state = T["conn_group_open"] if opened else T["conn_group_closed"]
    return {"key": key, "title": title, "open": opened, "chips": chips, "summary": summary, "cards": [card_vm(info, sample, keys) for info in infos],
            "a11y": ", ".join(part for part in (title, summary, state) if part)}


def info_vm(data, opened, loaded_at, version):
    """'정보' 묶음(UI-C1b) — **버전**(UI-C1a 의 버전 규칙 그대로: 읽으면 `v0.0.0`, 못 읽으면 개발 화면의 `개발 버전`)과 접어 둔 **진단 정보**(+ '키와 입력한 글은 담기지 않아요' 안내). 요약 칩은 없다.
    버전은 앱이 이미 읽어 둔 값(`VersionInfo`)을 받는다 — 이 순수 규칙이 파일을 읽지 않는다. 못 받았으면 개발 화면과 같은 `개발 버전`. 읽기만 한다(키·항목 이름·값은 어디에도 없다)."""
    title = T["conn_group_info"]
    state = T["conn_group_open"] if opened else T["conn_group_closed"]
    shown = version.text if version is not None else T["dev_version"]
    return {"key": INFO_GROUP, "title": title, "open": opened, "chips": [], "summary": "", "a11y": ", ".join((title, state)),
            "version": {"label": T["info_version"], "text": shown},
            "diag": {"show": T["diag_show"], "hide": T["diag_hide"], "note": T["diag_note"], "text": diag_text(data, loaded_at) if data else ""}}


def diag_text(data, when=None):
    """설정 화면의 '진단 정보'(기본 화면에는 안 보이고 펼칠 때만) — 읽은 시각·용도와 항목 수·읽은 곳(보관소·사용량)의 성공 여부뿐이다. 키 값도, 항목 이름도, 끝 글자도 담지 않는다."""
    stamp = (when or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    entries = sum(len(info.entries) for info in data.purposes)
    answer = lambda name: T["diag_unavailable"] if name in data.partial else T["diag_ok"]          # noqa: E731
    return "\n".join((f"{T['diag_when']}: {stamp}", f"{T['diag_purposes']}: {len(data.purposes)}", f"{T['diag_entries']}: {entries}",
                      f"{T['diag_keystore']}: {answer('keystore')}", f"{T['diag_usage']}: {answer('usage')}"))


def build_settings_view(data, state, *, failure=None, error_diag="", loaded_at=None, open_groups=None, version=None, keys=None):
    """설정 화면 하나의 뷰모델. `state` 는 홈과 같은 여섯 상태(loading · normal · empty · error · partial · offline)이고 `open_groups` 는 펼친 묶음 이름들(용도 묶음 넷 + `info`)이다.
    묶음은 다섯 — 용도 묶음 넷(`groups`: 데이터 Provider·이미지·AI 보조·발행·연결)과 마지막 `info`('정보' — 버전 + 진단 정보)."""
    sample = bool(data and data.sample)
    opened = set(open_groups or ())
    writable = bool(keys is not None and keys.writable)
    groups = [group_vm(key, infos, key in opened, sample, keys if writable else None) for key, infos in grouped(data.purposes)] if data and state in ("normal", "partial", "offline") else []
    banners = []
    if state == "partial" and data:
        banners = [("alert", T[PARTIAL_TEXT[name]]) for name in data.partial if name in PARTIAL_TEXT]
    elif state == "offline":
        banners = [("cloud_off", T["conn_offline"])]
    return {
        "title": T["settings_title"], "sub": T["settings_sub"], "sample": sample, "sample_tag": T["sample_tag"], "state": state,
        "fetched": T["last_fetch"].format(when=data.fetched) if data and data.fetched else "", "banners": banners, "refresh": T["conn_refresh"],
        "section": {"title": T["conn_title"], "desc": T["conn_desc_write" if writable else "conn_desc"]}, "groups": groups, "keys_note": T["conn_keys_note_write" if writable else "conn_keys_note"],
        "writable": writable, "notice": {"level": keys.notice[0], "text": keys.notice[1]} if writable and keys.notice else None, "busy": bool(writable and keys.busy),
        "info": info_vm(data, INFO_GROUP in opened, loaded_at, version),
        "loading": {"text": T["conn_loading"], "a11y": T["conn_loading_a11y"]},
        "empty": {"title": T["conn_empty_title"], "desc": T["conn_empty_desc"], "button": T["conn_empty_btn"]},
        "error": {"title": T["conn_error_title"], "desc": T["conn_error_desc"], "button": T["retry"], "diag": error_diag,
                  "user": getattr(failure, "user_message", "") if failure else ""},
    }
