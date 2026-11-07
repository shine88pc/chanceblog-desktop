"""Seed 관리 화면의 목록 규칙 — 거르기·개수 요약·채널별 쓸 수 있는 수·일괄 변경 대상과 미리 보기. 순수 계산(파일·시계·화면 도구 없음).

  · **거르기**는 상태·소속·중요도·글 검색이고 모두 읽기뿐이다(파일을 바꾸지 않는다). 글 검색은 낱말·대분류·중분류에서 공백으로 나눈 조각이 **모두** 들어 있는 씨앗을 찾는다(대소문자는 가리지 않는다).
  · **채널마다 쓸 수 있는 수**는 서비스의 `usable_seeds` 와 같은 뜻이다 — 상태가 사용 중이고 허용 채널에 그 채널이 든 씨앗. 후보 생성이 켜져 있는지는 따로 보인다(첫 버전은 네이버 A·B 만 켜짐).
  · **일괄 변경**은 고른 씨앗 중 그 일로 바꿀 수 있는 것만 대상이다(`BULK_FROM` — 서비스의 `TRANSITIONS` 와 같은 길): 사용 중으로 바꾸기 = 승인 전·쉬는 중, 쉬게 하기 = 승인 전·사용 중.
    미리 보기는 바꾸기 전과 바꾼 뒤의 채널별 쓸 수 있는 수를 메모리에서 계산해 보인다(아무것도 쓰지 않는다).
"""
from __future__ import annotations

from ...topics import seeds as sd
from . import seed_form as sf
from .text import T

STATUS_KEYS = ("all", sd.STATE_PROPOSED, sd.STATE_ACTIVE, sd.STATE_INACTIVE)
BULK_KINDS = ("activate", "rest")
BULK_TARGET = {"activate": sd.STATE_ACTIVE, "rest": sd.STATE_INACTIVE}
BULK_FROM = {"activate": (sd.STATE_PROPOSED, sd.STATE_INACTIVE), "rest": (sd.STATE_PROPOSED, sd.STATE_ACTIVE)}          # `sd.TRANSITIONS` 를 지키는 길(시험이 견준다)
PAGE = 40                                                                                                                # 목록에 한 번에 그리는 줄 수 — 더 보려면 '더 보기'
NAMES_SHOWN = 5                                                                                                          # 일괄 변경 확인창에 이름을 보이는 개수
REASONS_SHOWN = 5                                                                                                        # 제안 파일 확인창에 거절 이유를 보이는 개수


def status_counts(seeds):
    """상태마다 씨앗 수 `{all, proposed, active, inactive}`."""
    counts = {key: 0 for key in STATUS_KEYS}
    for seed in seeds:
        counts["all"] += 1
        counts[seed.state] += 1
    return counts


def facet_counts(seeds, attribute, keys):
    """소속·중요도 같은 한 가지 기준의 값마다 씨앗 수(`all` 은 전체)."""
    counts = {key: 0 for key in keys}
    counts["all"] = 0
    for seed in seeds:
        counts["all"] += 1
        value = getattr(seed, attribute)
        if value in counts:
            counts[value] += 1
    return counts


def query_words(text):
    """검색 글 → 찾을 조각들(한 줄로 다듬고 공백으로 나눠 소문자로)."""
    return tuple(piece for piece in sf.clean_line(text if isinstance(text, str) else "").casefold().split(" ") if piece)


def matches(seed, status="all", scope="all", importance="all", words=()):
    """이 씨앗이 거르기 조건에 맞는가 — 모든 조건을 지켜야 하고 검색 조각은 낱말·대분류·중분류에 모두 있어야 한다."""
    if status != "all" and seed.state != status:
        return False
    if scope != "all" and seed.scope != scope:
        return False
    if importance != "all" and seed.seed_type != importance:
        return False
    if words:
        hay = " ".join((seed.keyword, seed.major, seed.minor)).casefold()
        return all(word in hay for word in words)
    return True


def usable_counts(seeds, override=None):
    """채널마다 쓸 수 있는 씨앗 수 `{채널: 수}` — 사용 중이고 허용 채널에 그 채널이 든 씨앗(`override` 는 `{번호: 가정한 상태}` — 일괄 변경의 '바꾼 뒤' 를 미리 계산할 때)."""
    override = override or {}
    counts = {code: 0 for code in sf.CHANNEL_ORDER}
    for seed in seeds:
        if override.get(seed.seed_id, seed.state) == sd.STATE_ACTIVE:
            for code in seed.allowed_channels:
                counts[code] += 1
    return counts


def channel_rows(seeds, generation):
    """채널마다 한 줄: 이름·쓸 수 있는 수·후보 생성 켜짐 여부(켜짐 True·꺼짐 False·읽지 못함 None)."""
    counts, flags = usable_counts(seeds), dict(generation)
    return [{"key": code, "name": sf.channel_name(code), "count": counts[code], "generation": flags.get(code)} for code in sf.CHANNEL_ORDER]


def generation_text(flag):
    return T["seeds_gen_on"] if flag is True else T["seeds_gen_off"] if flag is False else T["seeds_gen_unknown"]


def bulk_ids(seeds, selected, kind):
    """고른 씨앗 중 그 일로 바꿀 수 있는 번호들(파일 순서). 모르는 번호는 세지 않는다."""
    allowed = BULK_FROM[kind]
    chosen = set(selected)
    return tuple(seed.seed_id for seed in seeds if seed.seed_id in chosen and seed.state in allowed)


def bulk_preview(seeds, selected, kind):
    """일괄 변경 미리 보기(아무것도 쓰지 않는다) — 바꿀 번호들·상태별 개수·가려서 줄인 처음 몇 개 이름·바뀌지 않는 개수·바꾸기 전후 채널별 쓸 수 있는 수."""
    ids = bulk_ids(seeds, selected, kind)
    by_id = {seed.seed_id: seed for seed in seeds}
    parts = {state: sum(1 for seed_id in ids if by_id[seed_id].state == state) for state in BULK_FROM[kind]}
    names = [sf.shown(by_id[seed_id].keyword, 30) for seed_id in ids[:NAMES_SHOWN]]
    before = usable_counts(seeds)
    after = usable_counts(seeds, {seed_id: BULK_TARGET[kind] for seed_id in ids})
    chosen = {seed_id for seed_id in selected if seed_id in by_id}
    return {"ids": ids, "count": len(ids), "parts": parts, "names": names, "rest": max(0, len(ids) - len(names)), "skipped": len(chosen) - len(ids),
            "channels": [{"key": code, "name": sf.channel_name(code), "before": before[code], "after": after[code]} for code in sf.CHANNEL_ORDER]}
