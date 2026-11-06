"""주제 엔진 서비스 — 명령줄 `topics`(상태·초기화·검사·후보 계획·후보 저장·우수 후보·목록·상세·보류함 검토·백업·복원)의 서비스 함수(P3, 계획 3.3, 결정 D-59~D-63).
계산은 `topics/`(순수), 저장은 `topicdb/`(SQLite `topic_engine.db`·백업)가 하고 여기서는 그것을 사람이 쓰는 흐름으로 잇는다 — 이 모듈은 파일을 직접 열거나 쓰지 않는다(설정 파일은 `topic_files` 가 `write_json` 으로만 쓴다).

규칙:
  · **읽기 전용이 기본이다**: `status`·`check`·`plan`·`top`·`list`·`show`·`review` 는 아무것도 쓰지 않고(보관함 파일도 만들지 않는다 — 읽기 전용 열기), 저장하는 일(`init`·`generate`)은 `confirmed=True`(`--yes`)가 있을 때만이다.
    `generate` 의 저장은 '읽고 판단하고 쓰기' 가 **한 트랜잭션**이다(`TopicStore.add_candidates` — 쓰기 잠금을 잡은 뒤 지금 있는 후보를 읽어 남은 자리를 세고 새 후보를 만든다).
  · **남은 자리**(계획 11.1): 채널마다 `slots.count_slots` 가 기존 후보를 세어(`remaining_slots = max(0, 목표 − 활성 − 검토 대기)`) 그 몫으로 `generate` 를 부른다(`target=남은 자리`, 줄어든 몫은 `route_targets` 가 다시 나눈다).
    `generate` 의 `existing=` 동작은 그대로다. 새로 만든 후보가 이미 있는 후보와 **같은 후보**(번호·채널+주제 해시·채널+씨앗+검색 의도+관점)이면 쓰지 않고 센다 — 모자란 자리는 다른 후보가 채우지 않는다.
  · 후보 계획은 후보 생성이 켜진 채널(`generation_enabled` — 처음 값은 네이버 A·B)에서만 만든다. **협찬 정보(`Campaign`)는 P3 에서 빈 목록**이다(저장은 P6 — 새 사용자 데이터 파일을 만들지 않는다).
  · 자동 초안 중지는 저장하지 않고 `safety.assess(후보).stop` 으로 계산한다. 사용자에게 보일 안내는 `topics.notice`(고정 문장)·`topics.wording` 에서만 나오고 `AppError.detail`·파이썬 목록 꼴·내부 코드는 화면 글에 없다.
  · 사용자 입력(기준일·목표 개수·채널)은 이 모듈이 먼저 검사해 `AppError`(CONTENT_INVALID — 입력한 값은 되풀이하지 않는다)로 바꾼다.
  · 블로그(`chanceblog`) 저장소 파일은 **읽기만** 한다 — GitHub Pages 는 `_posts` 머리말, Blogger 영문·한글은 `blogger_history.json`·`blogger_ko_history.json`, 네이버 A·B 는 글 보관함의 발행한 글. 읽은 기록은 보관함의 장부(`history_ledger`)에도 남아
    블로그 쪽에서 글이 없어져도 중복 검사에는 계속 쓰인다. 못 읽은 항목은 건너뛰고 안내로 알린다.
  · 관심도(Trend)는 공급자를 받는 틀만 있다(기본 '없음' = 조회 안 함 — 캘린더만으로 시기를 정한다). 실제 호출은 P5 다.
"""
from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from pathlib import Path

from ..content import status as st
from ..content.candidates import FOLLOW_ON, HOLD, STATUS_KO, STATUSES
from ..echo import shown_ref, shown_topic_backup
from ..errors import AppError
from ..topicdb import backup as tbackup
from ..topicdb.store import history_key, open_for_write, open_read_only
from ..topics import brand, dedupe, hold, layout, notice, safety, schedule, score, select, slots, wording
from ..topics import seeds as seedmod
from ..topics import generate as gen
from ..topics import history as hist
from ..topics import trend as trendmod
from ..topics.channels import CHANNELS, invalid_in
from ..topics.model import check_candidate_score
from . import topic_files as tf

SUBJECT = "주제 엔진"
KST = timezone(timedelta(hours=9), "KST")
MAX_POST_FILES = 5000                                        # `_posts` 에서 읽을 글 파일 수의 상한
MAX_POST_BYTES = 2 * 1024 * 1024                             # 글 파일 하나의 상한(넘으면 건너뛰고 안내)
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_SHOWN_WARNINGS = 10
MAX_ORDINAL_DIGITS = 3
MIN_PREFIX = 4
HEX_ID = re.compile(r"tc-[a-z_]+-[a-z_]+-([0-9a-f]{16})")    # 엔진이 만드는 후보 번호의 모양 — 앞 8자만 화면에 보인다
HISTORY_FILES = {"blogger_en": "blogger_history.json", "blogger_ko": "blogger_ko_history.json"}
STORE_MISSING, STORE_READY, STORE_OLD, STORE_EMPTY = "missing", "ready", "old_structure", "empty"
HISTORY_READ, HISTORY_NOT_CONNECTED, HISTORY_MISSING, HISTORY_UNREADABLE, HISTORY_NO_STORE = "read", "not_connected", "missing", "unreadable", "no_store"


# ---- 입력 검사 ----------------------------------------------------------------------------------------------------------------
def check_today(value):
    """기준일(`YYYY-MM-DD`) — 없으면 None. 달력에 없는 날짜나 모양이 틀린 값은 CONTENT_INVALID(입력한 값은 되풀이하지 않는다)."""
    if value is None:
        return None
    if not isinstance(value, str) or hist.valid_day(value) is None or int(value[:4]) > schedule.MAX_YEAR:
        raise invalid_in(SUBJECT, "기준일", f"2026-11-05 같은 모양의 달력에 있는 날짜(2000~{schedule.MAX_YEAR}년)여야 합니다")
    return value


def check_target(value):
    """채널당 후보 수 목표 — 없으면 None. 1~`generate.MAX_TARGET` 의 정수(참·거짓·실수는 거절)."""
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= gen.MAX_TARGET:
        raise invalid_in(SUBJECT, "목표 개수", f"1~{gen.MAX_TARGET} 사이의 정수여야 합니다")
    return value


def check_channel(value):
    """채널 — 없으면 None. 코드의 채널 이름이나 전략 문서의 별칭(blogger_a·blogger_b). 틀리면 CONTENT_INVALID(입력한 값은 되풀이하지 않는다)."""
    if value is None:
        return None
    if isinstance(value, str):
        if value in CHANNELS:
            return value
        if value in ("blogger_a", "blogger_b"):
            return {"blogger_a": "blogger_ko", "blogger_b": "blogger_en"}[value]
    raise invalid_in(SUBJECT, "채널", wording.one_of(CHANNELS, wording.CHANNEL_KO))


def _check_status(value):
    if value is not None and (not isinstance(value, str) or value not in STATUSES):
        raise invalid_in(SUBJECT, "작업 상태", wording.one_of(STATUSES, STATUS_KO))
    return value


def _check_band(value):
    if value is not None and (not isinstance(value, str) or value not in score.BANDS):
        raise invalid_in(SUBJECT, "추천 구간", wording.one_of(score.BANDS, score.BAND_KO))
    return value


def today_of(ctx, today=None):
    """기준일 — 준 날짜(검사한 값)이거나 지금(한국 시간)의 날짜."""
    return check_today(today) or ctx.now().astimezone(KST).strftime("%Y-%m-%d")


def now_stamp(ctx, today=None):
    """기한 판정에 쓰는 '지금' 시각 글(UTC) — 기준일을 줬으면 그 날 0시, 아니면 시계의 지금."""
    given = check_today(today)
    return f"{given}T00:00:00Z" if given else ctx.stamp()


# ---- 보관함 열기(읽기 전용) --------------------------------------------------------------------------------------------------------
def _is_empty_file(path):
    return path.is_file() and path.stat().st_size == 0


def _read_store(paths):
    """읽기 전용으로 연 보관함 → (보관함 또는 None, 상태). 파일이 없으면 만들지 않고 (None, 'missing'), 0바이트 파일(만들다 멈춘 흔적)은 (None, 'empty') — 쓰기 열기와 같은 정의로 '아직 없는 것' 이다(D-69)."""
    if not paths.database.exists():
        return None, STORE_MISSING
    if _is_empty_file(paths.database):
        return None, STORE_EMPTY
    store = open_read_only(paths.database)
    return store, STORE_OLD if store.needs_migration else STORE_READY


def _existing_candidates(paths):
    """저장된 후보들(읽기 전용) → (후보들, 상태, 발행 이력 장부, 연결들). 구조가 옛 판이면 읽지 않는다 — 저장하는 명령이 올린다."""
    store, state = _read_store(paths)
    if store is None or state == STORE_OLD:
        if store is not None:
            store.close()
        return (), state, (), ()
    with store:
        return tuple(store.list_candidates()), state, tuple(store.history_records()), tuple(store.links())


# ---- 블로그 발행 이력 읽기(읽기 전용) ----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class HistoryChannel:
    channel: str
    state: str                        # read · not_connected · missing · unreadable · no_store
    count: int                        # 읽은 기록 수

    def to_dict(self):
        return {"channel": self.channel, "state": self.state, "count": self.count}


@dataclass(frozen=True)
class HistoryReading:
    records: tuple                    # HistoryRecord — 이번에 읽은 것
    channels: tuple                   # HistoryChannel — 채널 순서
    warnings: tuple                   # 쉬운 한국어 줄들

    def to_dict(self):
        return {"channels": [item.to_dict() for item in self.channels], "records": len(self.records), "warnings": list(self.warnings)}


def _read_json_file(path):
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("파일이 너무 큽니다")
    return json.loads(path.read_bytes().decode("utf-8"))


def _channel_warnings(channel, found):
    return [f"{wording.CHANNEL_KO[channel]} 이력 {item.message()}" for item in found]


def _read_pages_history(repo, warnings):
    posts = repo / "_posts"
    if not posts.is_dir():
        return (), HISTORY_MISSING
    made, files = [], sorted(posts.rglob("*.md"))
    if len(files) > MAX_POST_FILES:
        warnings.append(f"GitHub Pages 글이 {len(files)}개라 앞의 {MAX_POST_FILES}개만 읽었습니다")
        files = files[:MAX_POST_FILES]
    skipped = 0
    for path in files:
        try:
            if path.stat().st_size > MAX_POST_BYTES:
                skipped += 1
                continue
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            skipped += 1
            continue
        found = hist.read_front_matter(text, filename=path.name)
        made.extend(found.records)
        warnings.extend(_channel_warnings("github_pages", found.warnings[:2]))
    if skipped:
        warnings.append(f"GitHub Pages 글 {skipped}개는 읽을 수 없거나 너무 커서 건너뛰었습니다")
    return tuple(made), HISTORY_READ


def _read_blogger_history(repo, channel, warnings):
    path = repo / HISTORY_FILES[channel]
    if not path.is_file():
        return (), HISTORY_MISSING
    try:
        items = _read_json_file(path)
    except (OSError, ValueError, RecursionError):
        warnings.append(f"{wording.CHANNEL_KO[channel]} 이력 파일을 읽을 수 없어 건너뛰었습니다")
        return (), HISTORY_UNREADABLE
    if not isinstance(items, list):
        warnings.append(f"{wording.CHANNEL_KO[channel]} 이력 파일이 목록이 아니라 건너뛰었습니다")
        return (), HISTORY_UNREADABLE
    found = hist.read_history_entries(items, channel)
    warnings.extend(_channel_warnings(channel, found.warnings[:3]))
    return found.records, HISTORY_READ


def _read_naver_history(ctx, warnings):
    """네이버 A·B 의 발행한 글 — 글 보관함(읽기 전용)에서 읽는다. 보관함이 없으면 '글 보관함 없음'."""
    try:
        store = ctx.reading_only().store()
    except AppError as error:
        if error.code == "CONTENT_NOT_FOUND":
            return {"naver_a": ((), HISTORY_NO_STORE), "naver_b": ((), HISTORY_NO_STORE)}
        warnings.append("글 보관함을 열 수 없어 네이버 발행 이력은 읽지 못했습니다")
        return {"naver_a": ((), HISTORY_UNREADABLE), "naver_b": ((), HISTORY_UNREADABLE)}
    items = {"naver_a": [], "naver_b": []}
    try:
        with store:
            for summary in store.list():
                project = store.load(summary.project_id)
                for channel in items:
                    variant = project.variants.get(channel)
                    if variant is not None and st.is_published(channel, variant.status):
                        items[channel].append({"title": project.title, "keywords": [], "date": (variant.published_at or "")[:10] or None, "url": variant.published_url, "ref": project.project_id})
    except AppError:
        warnings.append("글 보관함의 글을 읽다 문제가 있어 네이버 발행 이력은 읽지 못했습니다")
        return {"naver_a": ((), HISTORY_UNREADABLE), "naver_b": ((), HISTORY_UNREADABLE)}
    made = {}
    for channel, rows in items.items():
        found = hist.read_naver_items(rows, channel)
        warnings.extend(_channel_warnings(channel, found.warnings[:3]))
        made[channel] = (found.records, HISTORY_READ)
    return made


def read_blog_history(ctx):
    """5채널의 발행 이력을 읽는다(읽기만 한다) → `HistoryReading`. 블로그 저장소가 연결돼 있지 않거나 파일이 없거나 못 읽는 채널은 상태로 알리고 멈추지 않는다."""
    warnings, by_channel = [], {}
    repo = ctx.repo_path_or_none()
    if repo is None or not Path(repo).is_dir():
        for channel in ("github_pages", "blogger_en", "blogger_ko"):
            by_channel[channel] = ((), HISTORY_NOT_CONNECTED)
    else:
        repo = Path(repo)
        by_channel["github_pages"] = _read_pages_history(repo, warnings)
        for channel in HISTORY_FILES:
            by_channel[channel] = _read_blogger_history(repo, channel, warnings)
    by_channel.update(_read_naver_history(ctx, warnings))
    records = tuple(record for channel in CHANNELS for record in by_channel[channel][0])
    channels = tuple(HistoryChannel(channel, by_channel[channel][1], len(by_channel[channel][0])) for channel in CHANNELS)
    shown = warnings[:MAX_SHOWN_WARNINGS] + ([f"그 밖에도 읽지 못한 항목 안내가 {len(warnings) - MAX_SHOWN_WARNINGS}건 더 있습니다"] if len(warnings) > MAX_SHOWN_WARNINGS else [])
    return HistoryReading(records, channels, tuple(shown))


def merge_history(read, ledger):
    """이번에 읽은 기록과 장부의 기록을 합친다 — 같은 기록(채널·장부 열쇠)은 이번에 읽은 것이 이기고 장부에만 있는 기록(블로그에서 없어진 글)도 남는다. 같은 입력은 늘 같은 순서다."""
    merged = {(record.channel, history_key(record)): record for record in ledger}
    merged.update({(record.channel, history_key(record)): record for record in read})
    return tuple(sorted(merged.values(), key=lambda item: (CHANNELS.index(item.channel), item.date or "", item.ref or "", item.title)))


# ---- 후보 계획 ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ChannelPlan:
    channel: str
    enabled: bool                     # 후보 생성이 켜진 채널인가
    target: int                       # 목표 개수
    slots: object                     # slots.Slots(후보 생성이 꺼진 채널은 None)
    candidates: tuple                 # 새로 저장할(저장했다면 저장한) 후보 — 같은 후보를 뺀 뒤
    duplicates: int                   # 새로 만들었지만 이미 있는 후보와 같아서 쓰지 않은 수
    stopped: int                      # 새 후보 중 자동 초안 중지로 계산되는 수(저장하지 않는 계산값)
    notices: tuple                    # notice.Notice — 진단·모자람
    trend_notes: tuple                # 관심도 안내 줄들
    withheld: tuple = ()              # 키·토큰 모양이 들어 있어 저장하지 않은 후보마다 씨앗 이름 하나(낱말은 없다)

    @property
    def name(self):
        return wording.CHANNEL_KO[self.channel]

    def to_dict(self):
        info = self.slots
        return {"channel": self.channel, "name": self.name, "enabled": self.enabled, "target": self.target, "withheld_seeds": list(self.withheld),
                "slots": None if info is None else {"active_existing": info.active_existing, "pending_review": info.pending_review, "remaining": info.remaining,
                                                    "ignored": [{"reason": why, "count": count} for why, count in info.ignored]},
                "new_candidates": [candidate.to_dict() for candidate in self.candidates], "duplicates": self.duplicates, "stopped": self.stopped,
                "notices": [item.to_dict() for item in self.notices], "trend_notes": list(self.trend_notes)}


@dataclass(frozen=True)
class PlanResult:
    today: str
    plans: tuple                      # ChannelPlan — 채널 순서
    saved: bool                       # 보관함에 저장했는가(미리 보기는 거짓)
    store_state: str                  # missing · ready · old_structure
    history: HistoryReading
    notes: tuple                      # 전체 안내(쉬운 한국어)

    @property
    def total(self):
        return sum(len(plan.candidates) for plan in self.plans)

    def to_dict(self):
        return {"today": self.today, "saved": self.saved, "store": self.store_state, "total_new": self.total, "channels": [plan.to_dict() for plan in self.plans], "history": self.history.to_dict(),
                "notes": list(self.notes)}


def _draft_states(ctx, links):
    """글 상태로 계산하는 DRAFTING·DRAFT_READY — 연결(`CandidateLink`)에 기존 후보 번호가 있으면 그 후보가 이은 글의 그 채널 흐름 상태에서 읽는다(`content.candidates.FOLLOW_ON` 의 대응). 저장하지 않는다.
    읽을 수 없으면 비워 두고 안내를 돌려준다. → ({엔진 후보 번호: 글 상태}, 안내 줄들)"""
    wanted = {link.engine_candidate_id: link for link in links if link.legacy_candidate_id}
    if not wanted:
        return {}, ()
    try:
        store = ctx.reading_only().store()
    except AppError:
        return {}, ("기존 글 보관함을 열 수 없어 초안 상태는 세지 않았습니다",)
    states, notes = {}, []
    reverse = {FOLLOW_ON[slots.DRAFTING]: slots.DRAFTING, FOLLOW_ON[slots.DRAFT_READY]: slots.DRAFT_READY}          # 글 흐름의 상태 → 초안 단계 이름
    with store:
        for engine_id, link in wanted.items():
            try:
                legacy = store.load_candidate(link.legacy_candidate_id)
                project = store.load(legacy.project_id) if legacy.project_id else None
            except AppError:
                notes.append("기존 후보와 이어진 글을 읽을 수 없어 그 후보의 초안 상태는 세지 않았습니다")
                continue
            variant = None if project is None else project.variants.get(link.channel)
            if variant is not None and variant.status in reverse:
                states[engine_id] = reverse[variant.status]
    return states, tuple(dict.fromkeys(notes))


@dataclass(frozen=True)
class _Inputs:
    profiles: tuple
    seeds: tuple
    calendar: tuple
    history_read: HistoryReading
    states: dict                      # 파일 이름 → Loaded.state
    keyed_seeds: tuple = ()           # 키·토큰 모양이 있어 후보를 만들지 않고 뺀 씨앗마다 이름 하나(낱말은 없다, D-77)


def _split_key_shaped_seeds(found):
    """씨앗 중 키·토큰 모양이 든 것을 후보를 만들기 **전에** 뺀다 → (쓸 씨앗들, 뺀 씨앗마다 이름 하나). 채널의 경로별 몫은 만든 후보로 채워지므로 키 모양 씨앗의 후보가 저장 직전에야 걸러지면 그 몫만큼
    같은 채널의 다른 씨앗 후보가 밀려난다(작은 목표에서는 아예 안 생긴다) — 미리 빼 두면 나머지 씨앗이 몫을 채운다(D-77). 후보 저장 직전의 거름(`_withhold_key_shaped`)은 방어선으로 남는다."""
    usable, names = [], []
    for seed in found:
        if tbackup.scan_key_shape(json.dumps(seed.to_dict(), ensure_ascii=False)):
            names.append(_shown_seed(seed.seed_id))
        else:
            usable.append(seed)
    return tuple(usable), tuple(names)


def _read_inputs(ctx, paths):
    profiles, seeds, calendar = tf.load_profiles(paths), tf.load_seeds(paths), tf.load_calendar(paths)
    usable, keyed = _split_key_shaped_seeds(seeds.value)
    return _Inputs(profiles.value, usable, calendar.value, read_blog_history(ctx), {layout.CHANNEL_PROFILES_FILE: profiles.state, layout.SEEDS_FILE: seeds.state, layout.CALENDAR_FILE: calendar.state}, keyed)


def _generate_channel(profile, inputs, history, existing, today, remaining, interest):
    found = interest or trendmod.TrendResult({}, False, (), ())
    return gen.generate(profile, inputs.seeds, inputs.calendar, history, today, existing=existing, target=remaining, interest=found.interest or None, interest_outage=found.outage, campaigns=())


def _filter_same(new, existing):
    """새로 만든 후보에서 이미 있는 후보(또는 앞서 고른 새 후보)와 같은 후보를 뺀다 → (남은 후보들, 뺀 수). 같은 후보 열쇠(`slots.sameness_keys`)를 사전에 모아 견준다 — 후보가 많아도 쌍마다 견주지 않는다(D-71)."""
    taken = set()
    for other in existing:
        taken.update(slots.sameness_keys(other))
    kept, dropped = [], 0
    for candidate in new:
        keys = slots.sameness_keys(candidate)
        if not taken.isdisjoint(keys):
            dropped += 1
            continue
        kept.append(candidate)
        taken.update(keys)
    return tuple(kept), dropped


def _shown_seed(seed_id):
    """안내에 보일 씨앗 이름 — 씨앗 번호만(낱말은 되풀이하지 않는다). 번호 자체가 키 모양이거나 없으면 가린다."""
    if not isinstance(seed_id, str) or not seed_id or tbackup.scan_key_shape(seed_id):
        return "(이름 가림)"
    return wording.clean_word(seed_id, 30)


def _withhold_key_shaped(kept):
    """키·토큰처럼 보이는 글이 든 새 후보는 저장하지 않는다 — 보관함에 한 번 들어가면 지우는 길이 없어 백업이 영원히 막히기 때문이다(D-68). → (남은 후보들, 거른 후보마다 씨앗 이름 하나).
    다른 후보는 그대로 저장한다. 낱말은 화면에도 되풀이하지 않는다."""
    safe, names = [], []
    for candidate in kept:
        if tbackup.scan_key_shape(json.dumps(candidate.to_dict(), ensure_ascii=False)):
            names.append(_shown_seed(candidate.seed_id))
        else:
            safe.append(candidate)
    return tuple(safe), tuple(names)


def _plan_channels(profiles, inputs, history, existing, today, now, target, channels, interest, draft_states):
    """채널마다 남은 자리를 세고 그 몫만큼 후보를 만든다(순수 계산 — 아무것도 쓰지 않는다)."""
    plans = []
    for profile in profiles:
        if channels and profile.key not in channels:
            continue
        mine = tuple(item for item in existing if item.channel == profile.key)
        goal = target if target is not None else gen.DEFAULT_TARGET
        if not profile.generation_enabled:
            plans.append(ChannelPlan(profile.key, False, goal, None, (), 0, 0, (), ()))
            continue
        known = {item.candidate_id for item in mine}
        counted = slots.count_slots(mine, goal, now, draft_states={key: value for key, value in draft_states.items() if key in known})
        found = interest.get(profile.key) if interest else None
        generated = _generate_channel(profile, inputs, history, mine, today, counted.remaining, found)
        kept, dropped = _filter_same(generated.candidates, mine)
        kept, withheld = _withhold_key_shaped(kept)
        stopped = sum(safety.assess(candidate).stop for candidate in kept)
        notices = notice.from_generated(generated)
        plans.append(ChannelPlan(profile.key, True, goal, counted, kept, dropped, stopped, notices, () if found is None else found.notes, withheld))
    return tuple(plans)


def _trend_inputs(provider, profiles, inputs, history, existing, today, now, target, channels, draft_states):
    """관심도 공급자에게 새 후보의 키워드를 물어 채널별 `TrendResult` 로 모은다(공급자가 '없음' 이면 묻지 않는다). 트랜잭션 **밖에서** 하므로 느린 공급자가 쓰기 잠금을 쥐고 기다리지 않는다."""
    if provider is None or isinstance(provider, trendmod.NoTrend):
        return {}
    first = _plan_channels(profiles, inputs, history, existing, today, now, target, channels, {}, draft_states)
    return {plan.channel: trendmod.collect(provider, [item.primary_keyword for item in plan.candidates], today) for plan in first if plan.enabled}


def _spread_notes(plans):
    """이번 실행에서 만든 새 후보끼리 채널 사이 같은 주제 검사(`dedupe.check_topic_spread` — 한 주제는 최대 2채널, 두 채널에 쓰면 일곱 항목 중 4개 이상 달라야 한다)를 하고 걸린 것을 쉬운 말 줄로 돌려준다.
    **표시만 한다** — 후보를 지우거나 막지 않는다. 가장 보수적인 최소 구현이라 이미 저장된 후보와는 견주지 않는다(다음 몫, D-74)."""
    new = [candidate for plan in plans for candidate in plan.candidates]
    if len({candidate.channel for candidate in new}) < 2:
        return ()
    lines = []
    for spread in dedupe.check_topic_spread(new):
        lines.extend(f"채널 사이 같은 주제: {problem}" for problem in spread.problems)
    return tuple(lines)


def _overall_notes(history_read, inputs, store_state, extra=()):
    notes = list(extra)
    if store_state == STORE_OLD:
        notes.append("주제 엔진 보관함이 옛 구조라 읽지 않았습니다 — 저장하는 명령(generate --yes)이 새 구조로 올립니다")
    if store_state == STORE_EMPTY:
        notes.append("주제 엔진 보관함 파일이 비어 있습니다(만들다 멈춘 흔적일 수 있습니다) — 저장하는 명령(generate --yes 나 init --yes)이 새로 만듭니다")
    if inputs.states[layout.SEEDS_FILE] == tf.STATE_MISSING or (not inputs.seeds and not inputs.keyed_seeds):
        notes.append("씨앗이 하나도 없습니다 — 씨앗 없이는 후보를 만들 수 없습니다(채널 프로필과 캘린더는 기본값을 씁니다)")
    if inputs.keyed_seeds:
        names = "·".join(f"‘{name}’" for name in dict.fromkeys(inputs.keyed_seeds))
        notes.append(f"키·토큰처럼 보이는 글이 든 씨앗 {len(inputs.keyed_seeds)}개(씨앗 {names})는 후보를 만들지 않았습니다 — 그 씨앗의 글에서 키처럼 보이는 낱말을 지운 뒤 다시 해 주세요(`topics check` 가 찾아 줍니다)")
    notes.extend(history_read.warnings)
    return tuple(notes)


def plan_candidates(ctx, *, today=None, target=None, channel=None, trend=None):
    """후보 계획(읽기 전용) — 프로필·씨앗·캘린더·블로그 이력과 보관함의 기존 후보를 읽어 채널마다 남은 자리만큼 후보를 만들어 보여 준다. 아무것도 쓰지 않는다(보관함 파일도 만들지 않는다)."""
    day, goal, only = today_of(ctx, today), check_target(target), check_channel(channel)
    paths = tf.topic_paths(ctx.workspace)
    inputs = _read_inputs(ctx, paths)
    existing, state, ledger, links = _existing_candidates(paths)
    history = merge_history(inputs.history_read.records, ledger)
    stamp = now_stamp(ctx, today)
    states, state_notes = _draft_states(ctx, links)
    chosen = (only,) if only else ()
    interest = _trend_inputs(trend, inputs.profiles, inputs, history, existing, day, stamp, goal, chosen, states)
    plans = _plan_channels(inputs.profiles, inputs, history, existing, day, stamp, goal, chosen, interest, states)
    return PlanResult(day, plans, False, state, inputs.history_read, _overall_notes(inputs.history_read, inputs, state, (*state_notes, *_spread_notes(plans))))


def generate_candidates(ctx, *, confirmed, today=None, target=None, channel=None, trend=None):
    """후보 저장 — `confirmed=True`(`--yes`)가 있을 때만 저장한다(없으면 `plan_candidates` 와 같은 미리 보기). 저장은 **한 트랜잭션**이다: 쓰기 잠금을 잡은 뒤 지금 있는 후보를 읽어 남은 자리를 세고 새 후보를 만들어
    모두 저장한다(두 창이 동시에 해도 겹치지 않고, 도중에 실패하면 하나도 저장되지 않는다). 읽은 발행 이력도 같은 트랜잭션으로 장부에 올린다."""
    if confirmed is not True:
        return plan_candidates(ctx, today=today, target=target, channel=channel, trend=trend)
    day, goal, only = today_of(ctx, today), check_target(target), check_channel(channel)
    paths = tf.topic_paths(ctx.workspace)
    inputs = _read_inputs(ctx, paths)
    existing_ro, _state, ledger_ro, links = _existing_candidates(paths)
    stamp = now_stamp(ctx, today)
    states, state_notes = _draft_states(ctx, links)
    chosen = (only,) if only else ()
    interest = _trend_inputs(trend, inputs.profiles, inputs, merge_history(inputs.history_read.records, ledger_ro), existing_ro, day, stamp, goal, chosen, states)
    done = []

    def plan(existing):
        history = merge_history(inputs.history_read.records, ledger_ro)
        plans = _plan_channels(inputs.profiles, inputs, history, existing, day, stamp, goal, chosen, interest, states)
        done.append(plans)
        return tuple(candidate for item in plans for candidate in item.candidates)

    with open_for_write(paths.database) as store:
        store.add_candidates(plan, now=ctx.stamp(), history=inputs.history_read.records)
    return PlanResult(day, done[0], True, STORE_READY, inputs.history_read, _overall_notes(inputs.history_read, inputs, STORE_READY, (*state_notes, *_spread_notes(done[0]))))


# ---- 상태·검사·초기화 ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class FileState:
    name: str
    state: str                        # missing(없음 — 기본값) · ok(읽음) · invalid(못 읽음)
    count: int                        # 읽은 항목 수(프로필은 채널 수)
    reason: str                       # 못 읽는 이유(쉬운 말 — 입력한 값이나 개발자 메모는 없다)

    def to_dict(self):
        return {"name": self.name, "state": self.state, "count": self.count, "reason": self.reason}


def _reason_of(error):
    """읽을 수 없는 이유 — 칸 오류가 가진 쉬운 말 이유만 쓰고, 없으면 고정 문장이다(`AppError.detail` 은 쓰지 않는다)."""
    reason = getattr(error, "reason", "")
    if isinstance(reason, str) and reason.strip() and notice.is_clean(reason):
        return reason
    return "글자나 JSON 모양이 올바르지 않습니다(메모장이라면 '다른 이름으로 저장' 에서 인코딩을 UTF-8 로 저장했는지, 쉼표·따옴표가 맞는지 확인해 주세요)" if error.code == "TOPIC_FILE_INVALID" else "칸의 값이나 모양이 올바르지 않습니다"


def _file_state(name, path):
    try:
        loaded = tf.load_json_set(name, path)
    except AppError as error:
        if error.code not in ("TOPIC_FILE_INVALID", "CONTENT_INVALID"):
            raise
        if tf.is_blank_file(path):
            return FileState(name, "invalid", 0, "파일이 비어 있습니다(0바이트 — 만들다 멈춘 흔적일 수 있습니다) — `topics init --yes` 가 기본 내용으로 채웁니다(내용이 있는 파일은 건드리지 않습니다)"), None
        return FileState(name, "invalid", 0, _reason_of(error)), None
    return FileState(name, loaded.state, len(loaded.value), ""), loaded.value


@dataclass(frozen=True)
class StatusResult:
    files: tuple                      # FileState — 프로필·씨앗·캘린더
    store_state: str                  # missing · ready · old_structure · newer · corrupt · unreadable
    store_version: object             # 보관함 구조 판(읽을 수 있을 때)
    counts: tuple                     # ((채널, 후보 수), …) — 채널 순서
    enabled: tuple                    # 후보 생성이 켜진 채널들
    history: HistoryReading
    paths: object

    def to_dict(self):
        return {"files": [item.to_dict() for item in self.files], "store": self.store_state, "store_version": self.store_version, "candidates": {channel: number for channel, number in self.counts},
                "generation_enabled": list(self.enabled), "history": self.history.to_dict()}


_STORE_STATE_OF = {"TOPIC_STORE_VERSION_UNSUPPORTED": "newer", "TOPIC_STORE_CORRUPT": "corrupt", "TOPIC_STORE_RECOVERY_PENDING": "unreadable", "TOPIC_STORE_LOCKED": "unreadable", "FILE_WRITE_FAILED": "unreadable"}


def status(ctx):
    """상태 보기(읽기 전용) — 설정 파일·보관함·후보 수·블로그 이력을 읽을 수 있는지. 못 읽는 것도 오류로 멈추지 않고 상태로 알린다."""
    paths = tf.topic_paths(ctx.workspace)
    files, profiles = [], tf.DEFAULT_VALUES[layout.CHANNEL_PROFILES_FILE]()
    for name, path in paths.json_files():
        shown, value = _file_state(name, path)
        files.append(shown)
        if name == layout.CHANNEL_PROFILES_FILE and value is not None:
            profiles = value
    counts, version = tuple((channel, 0) for channel in CHANNELS), None
    try:
        store, state = _read_store(paths)
        if store is not None:
            with store:
                version = store.schema_version
                if state == STORE_READY:
                    counts = tuple((channel, store.count(channel)) for channel in CHANNELS)
    except AppError as error:
        state = _STORE_STATE_OF.get(error.code)
        if state is None:
            raise
    return StatusResult(tuple(files), state, version, counts, tuple(item.key for item in profiles if item.generation_enabled), read_blog_history(ctx), paths)


@dataclass(frozen=True)
class CheckResult:
    files: tuple                      # FileState
    notices: tuple                    # notice.Notice — 브랜드 이름만 있는 씨앗 미리 보기
    proposals: tuple                  # 180일 미선택 씨앗 제안(쉬운 말 줄)
    evaluations: tuple                # 다시 평가할 때가 된 캘린더 항목(쉬운 말 줄)
    seeds: int
    entries: int
    keyed: tuple = ()                 # 키·토큰 모양이 든 항목(쉬운 말 줄 — 씨앗·항목 이름만, 낱말은 되풀이하지 않는다)
    public_keyed: tuple = ()          # 블로그에서 읽은 발행 이력 중 키·토큰 모양이 든 글(쉬운 말 줄 — 글 번호만) — 이미 공개된 글이라 저장·백업을 막지 않는다(D-75)

    @property
    def ok(self):
        return all(item.state != "invalid" for item in self.files)

    def to_dict(self):
        return {"ok": self.ok, "files": [item.to_dict() for item in self.files], "seeds": self.seeds, "calendar_entries": self.entries, "brand_notices": [item.to_dict() for item in self.notices],
                "idle_seeds": list(self.proposals), "calendar_to_review": list(self.evaluations), "key_shaped": list(self.keyed), "public_key_shaped": list(self.public_keyed)}


def _key_shaped_items(seeds_found, calendar_found, profiles):
    """키·토큰처럼 보이는 글이 든 씨앗·캘린더 항목·채널 프로필을 쉬운 말 줄로(읽기 전용 — 씨앗·항목 이름만 보이고 낱말은 되풀이하지 않는다). 그런 글이 든 씨앗의 후보는 저장하지 않고 백업도 막히므로 먼저 알려 준다(D-68)."""
    lines = []
    for label, items, key in (("씨앗", seeds_found, "seed_id"), ("캘린더 항목", calendar_found, "entry_id"), ("채널 프로필", profiles, "key")):
        for item in items:
            if tbackup.scan_key_shape(json.dumps(item.to_dict(), ensure_ascii=False)):
                lines.append(f"{label} ‘{_shown_seed(getattr(item, key, None))}’ 에 키·토큰처럼 보이는 글이 있습니다")
    return tuple(lines)


def _key_shaped_history(records):
    """블로그에서 읽은 발행 이력 중 키·토큰처럼 보이는 글이 든 것을 쉬운 말 줄로(글 번호만 — 낱말은 되풀이하지 않는다). 이미 공개된 글이라 장부에 담고 백업도 막지 않지만(D-75) 그것이 실제 키라면
    이미 드러난 것이니 알려 둔다."""
    lines = []
    for record in records:
        if tbackup.scan_key_shape(json.dumps([record.title, list(record.keywords), record.url, record.topic, record.ref], ensure_ascii=False)):
            number = "번호 없음" if not record.ref else _shown_seed(record.ref)
            lines.append(f"{wording.CHANNEL_KO[record.channel]} 발행 글 ‘{number}’ 의 제목·키워드·주소에 키·토큰처럼 보이는 글이 있습니다")
    return tuple(lines)


def check_files(ctx, *, today=None):
    """씨앗·캘린더·채널 프로필 검사(읽기 전용) — 엄격한 모양으로 읽어 보고, 180일 미선택 씨앗(제안만)·다시 평가할 캘린더 항목·브랜드 이름만 있는 씨앗('주제 구체화 필요' — 저장 없이 미리 보기)을 알린다."""
    day = today_of(ctx, today)
    paths = tf.topic_paths(ctx.workspace)
    files, values = [], {}
    for name, path in paths.json_files():
        shown, value = _file_state(name, path)
        files.append(shown)
        values[name] = value
    seeds_found = values.get(layout.SEEDS_FILE) or ()
    calendar_found = values.get(layout.CALENDAR_FILE) or ()
    profiles = values.get(layout.CHANNEL_PROFILES_FILE) or tf.DEFAULT_VALUES[layout.CHANNEL_PROFILES_FILE]()
    proposals = tuple(item.message() for item in seedmod.idle_proposals(seeds_found, day)) if seeds_found else ()
    evaluations = tuple(sorted(f"캘린더 항목 ‘{wording.clean_word(entry.name, 30)}’ 은(는) 마지막 평가가 오래되었거나 없어 다시 평가할 때가 되었습니다" for entry in calendar_found if schedule.needs_evaluation(entry, day)))     # 파일 순서와 무관하게 늘 같은 순서
    notices = []
    for profile in profiles:
        if not profile.generation_enabled:
            continue
        for seed in seedmod.usable_seeds(seeds_found, profile.key):
            view = brand.assess(seed, profile)
            for item in notice.from_brand(view):
                notices.append(dataclasses.replace(item, details=(f"{profile.display_name} · 씨앗 ‘{wording.clean_word(seed.keyword, 30)}’",) + item.details))
    keyed = _key_shaped_items(seeds_found, calendar_found, profiles)
    public_keyed = _key_shaped_history(read_blog_history(ctx).records)
    return CheckResult(tuple(files), notice.sort_notices(notices), proposals, evaluations, len(seeds_found), len(calendar_found), keyed, public_keyed)


@dataclass(frozen=True)
class InitResult:
    confirmed: bool
    made: tuple                       # 만든(미리 보기면 만들) 파일 이름들
    kept: tuple                       # 이미 있어 그대로 둔 것들
    folder: object
    store_created: bool

    def to_dict(self):
        return {"confirmed": self.confirmed, "created": list(self.made), "kept": list(self.kept), "store_created": self.store_created}


def init_topics(ctx, *, confirmed):
    """주제 엔진 폴더와 설정 파일 셋·보관함을 처음 만든다 — `confirmed=True`(`--yes`)가 있을 때만 만든다(없으면 만들 것만 알려 주고 아무것도 만들지 않는다). 이미 있는 파일은 그대로 둔다."""
    paths = tf.topic_paths(ctx.workspace)
    names = tf.missing_files(paths)
    store_missing = not paths.database.exists() or _is_empty_file(paths.database)
    if confirmed is not True:
        return InitResult(False, names, tuple(name for name, _path in paths.json_files() if name not in names), paths.folder, store_missing)
    made, kept = tf.init_files(paths)
    with open_for_write(paths.database):
        pass
    return InitResult(True, made, kept, paths.folder, store_missing)


# ---- 우수 후보·목록·상세·보류함 ------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Row:
    ordinal: int                      # 저장한 순서(전체 목록 기준 1부터 — 후보는 지워지지 않아 바뀌지 않는다)
    candidate: object                 # TopicCandidate
    stop: bool                        # 자동 초안 중지(저장하지 않는 계산값)

    def to_dict(self):
        return {"ordinal": self.ordinal, "ref": short_ref(self.candidate.candidate_id), "stop": self.stop, **self.candidate.to_dict()}


def _hex_part(candidate_id):
    found = HEX_ID.fullmatch(candidate_id)
    return found.group(1) if found else None


def short_ref(candidate_id):
    """화면에 보일 짧은 번호 — 엔진 번호의 16진수 부분 앞 8자(모양이 다르면 번호 앞 8자)."""
    found = HEX_ID.fullmatch(candidate_id)
    return found.group(1)[:8] if found else candidate_id[:8]


def _rows(candidates):
    """저장소가 준 순서(저장한 순서) 그대로 순번을 붙인다 — 후보를 지우는 길이 없어 한 번 붙은 순번은 바뀌지 않는다(같은 날 두 번 저장해도 그대로, D-70)."""
    return [Row(number, item, safety.assess(item).stop) for number, item in enumerate(candidates, start=1)]


def _load_rows(paths):
    store, state = _read_store(paths)
    if store is None:
        return [], state
    with store:
        if state == STORE_OLD:
            return [], state
        return _rows(store.list_candidates()), state


@dataclass(frozen=True)
class ListResult:
    rows: tuple                       # Row — 거른 뒤의 것
    total: int                        # 거르기 전 전체 후보 수
    store_state: str

    def to_dict(self):
        return {"candidates": [row.to_dict() for row in self.rows], "total": self.total, "shown": len(self.rows), "store": self.store_state}


def list_candidates(ctx, *, channel=None, status=None, band=None):
    """저장된 후보 목록(읽기 전용). 순번은 거르기 전 전체 목록 기준이라 거르면 건너뛴 번호가 생긴다."""
    only, work, zone = check_channel(channel), _check_status(status), _check_band(band)
    rows, state = _load_rows(tf.topic_paths(ctx.workspace))
    shown = [row for row in rows if (only is None or row.candidate.channel == only) and (work is None or row.candidate.work_status == work) and (zone is None or row.candidate.recommendation_band == zone)]
    return ListResult(tuple(shown), len(rows), state)


@dataclass(frozen=True)
class TopChannel:
    channel: str
    enabled: bool
    rows: tuple                       # Row — 우수 후보(보여 줄 순서)
    shortfall: int                    # 모자란 수
    problems: tuple                   # 점수가 다시 계산한 값과 달라 뺀 후보 안내(쉬운 말)

    @property
    def name(self):
        return wording.CHANNEL_KO[self.channel]

    def to_dict(self):
        return {"channel": self.channel, "name": self.name, "enabled": self.enabled, "top": [row.to_dict() for row in self.rows], "shortfall": self.shortfall, "problems": list(self.problems)}


@dataclass(frozen=True)
class TopResult:
    channels: tuple
    store_state: str

    def to_dict(self):
        return {"store": self.store_state, "channels": [item.to_dict() for item in self.channels]}


def top_candidates(ctx, *, channel=None):
    """채널별 우수 후보 상위 N개(읽기 전용) — 같은 주제 묶음은 최대 2개·모자라면 일반 후보로 보충·사람이 제외·보류한 후보는 숨김(`select.top_view`). 점수가 그 채널의 가중치로 다시 계산한 값과 다른 후보는 빼고 안내한다."""
    only = check_channel(channel)
    paths = tf.topic_paths(ctx.workspace)
    profiles = tf.load_profiles(paths).value
    rows, state = _load_rows(paths)
    results = []
    for profile in profiles:
        if only and profile.key != only:
            continue
        mine, problems = [], []
        for row in rows:
            if row.candidate.channel != profile.key:
                continue
            try:
                check_candidate_score(row.candidate, profile)
            except AppError:
                problems.append(f"순번 {row.ordinal} 후보는 저장된 점수가 지금 채널 프로필의 가중치로 다시 계산한 값과 달라 우수 후보에서 뺐습니다")
                continue
            mine.append(row)
        view = select.top_view([row.candidate for row in mine], profile)
        by_id = {row.candidate.candidate_id: row for row in mine}
        results.append(TopChannel(profile.key, profile.generation_enabled, tuple(by_id[item.candidate_id] for item in view.items), view.shortfall, tuple(problems)))
    return TopResult(tuple(results), state)


def resolve(rows, text):
    """순번(1~999)·후보 번호 전체·번호의 16진수 앞 4자 이상(겹치지 않을 때) → 그 줄. 없으면 TOPIC_CANDIDATE_NOT_FOUND, 앞부분이 둘 이상과 맞으면 TOPIC_CANDIDATE_AMBIGUOUS. 친 글은 번호 모양일 때만 되풀이한다."""
    wanted = text.strip() if isinstance(text, str) else ""
    shown = shown_ref(wanted) if wanted else "(비어 있음)"
    if not wanted:
        raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": shown}, detail="후보 번호를 적는다 — 목록의 순번이나 번호의 앞 4자 이상")
    if re.fullmatch(f"[1-9][0-9]{{0,{MAX_ORDINAL_DIGITS - 1}}}", wanted):
        number = int(wanted)
        if number > len(rows):
            raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": f"순번 {number}(후보는 {len(rows)}개뿐입니다)"}, detail=f"후보는 {len(rows)}개뿐이다")
        return rows[number - 1]
    exact = [row for row in rows if row.candidate.candidate_id == wanted]
    if exact:
        return exact[0]
    lowered = wanted.lower()
    if len(wanted) < MIN_PREFIX or not re.fullmatch(r"[0-9a-f]+", lowered):
        raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": shown}, detail=f"번호는 목록의 순번이거나 번호(16진수)의 앞 {MIN_PREFIX}자 이상으로 적는다")
    found = [row for row in rows if (hexed := _hex_part(row.candidate.candidate_id)) is not None and hexed.startswith(lowered)]
    if not found:
        raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": shown})
    if len(found) > 1:
        overlapping = " · ".join(f"순번 {row.ordinal}({short_ref(row.candidate.candidate_id)})" for row in found[:8])
        raise AppError("TOPIC_CANDIDATE_AMBIGUOUS", {"항목": f"{shown} — 겹치는 후보: {overlapping}"}, detail="겹치는 후보: " + overlapping)
    return found[0]


@dataclass(frozen=True)
class ShowResult:
    row: Row
    notices: tuple                    # notice.Notice — 안전 표시·보류 안내
    stay: object                      # HoldStay 또는 None
    snapshots: int                    # 점수 스냅샷 수
    link: object                      # CandidateLink 또는 None

    def to_dict(self):
        return {"candidate": self.row.to_dict(), "notices": [item.to_dict() for item in self.notices], "hold": None if self.stay is None else self.stay._asdict(), "score_snapshots": self.snapshots,
                "link": None if self.link is None else self.link.to_dict()}


def show_candidate(ctx, ref):
    """후보 하나의 자세한 내용(읽기 전용) — 안전 표시·보류 기한(`notice` 변환)·점수 스냅샷 수·연결."""
    paths = tf.topic_paths(ctx.workspace)
    store, state = _read_store(paths)
    if store is None or state == STORE_OLD:
        if store is not None:
            store.close()
        raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": shown_ref(ref.strip() if isinstance(ref, str) else "")}, detail="주제 엔진 보관함이 없거나 옛 구조라 후보가 하나도 없다")
    with store:
        row = resolve(_rows(store.list_candidates()), ref)
        candidate = row.candidate
        stay = next((item for item in store.hold_stays() if item.candidate_id == candidate.candidate_id), None)
        notices = notice.for_candidate(candidate, safety.assess(candidate))
        return ShowResult(row, notices, stay, len(store.score_history(candidate.candidate_id)), store.load_link(candidate.candidate_id))


@dataclass(frozen=True)
class ReviewItem:
    row: Row
    expires_at: object                # 보류 기한(사람이 보류한 후보는 None)
    expired: bool                     # 기한이 지났다 — 지우지 않고 표시만 한다
    days_left: object                 # 남은 날수(지났으면 음수, 기한이 없으면 None)

    def to_dict(self):
        return {"ordinal": self.row.ordinal, "ref": short_ref(self.row.candidate.candidate_id), "channel": self.row.candidate.channel, "topic": self.row.candidate.topic, "work_status": self.row.candidate.work_status,
                "band": self.row.candidate.recommendation_band, "expires_at": self.expires_at, "expired": self.expired, "days_left": self.days_left}


@dataclass(frozen=True)
class ReviewResult:
    items: tuple                      # ReviewItem — 기한이 이른 것이 먼저
    expired: int
    now: str
    store_state: str

    def to_dict(self):
        return {"now": self.now, "store": self.store_state, "expired": self.expired, "held": [item.to_dict() for item in self.items]}


def review_holds(ctx, *, today=None):
    """보류함 검토(읽기 전용) — 보류함(점수 구간 보류)에 머무는 후보와 사람이 보류한 후보를 기한과 함께 보이고 기한이 지난 것을 표시한다. **아무것도 지우거나 바꾸지 않는다**(정리는 운영자가 정한다)."""
    stamp = now_stamp(ctx, today)
    paths = tf.topic_paths(ctx.workspace)
    store, state = _read_store(paths)
    if store is None or state == STORE_OLD:
        if store is not None:
            store.close()
        return ReviewResult((), 0, stamp, state)
    with store:
        rows = {row.candidate.candidate_id: row for row in _rows(store.list_candidates())}
        stays = {stay.candidate_id: stay for stay in store.hold_stays()}
    items = []
    for row in rows.values():
        held = row.candidate.candidate_id in stays or row.candidate.work_status == HOLD
        if not held:
            continue
        due = stays[row.candidate.candidate_id].expires_at if row.candidate.candidate_id in stays else row.candidate.review_expires_at
        expired = hold.is_expired(due, stamp)
        left = None if due is None else (_day_of(due) - _day_of(stamp)).days
        items.append(ReviewItem(row, due, expired, left))
    items.sort(key=lambda item: (item.expires_at is None, item.expires_at or "", item.row.ordinal))
    return ReviewResult(tuple(items), sum(item.expired for item in items), stamp, state)


def _day_of(stamp):
    """UTC 시각 글 → 날짜 — 남은 날수 계산용."""
    return date.fromisoformat(stamp[:10])


# ---- 백업·복원 ---------------------------------------------------------------------------------------------------------------------
def backups_folder(ctx):
    return Path(ctx.workspace.backups_dir) / "topic_engine"


def backup_topics(ctx):
    """주제 엔진 데이터(보관함 + 설정 파일 셋)의 점검한 백업을 `backups/topic_engine/` 에 만든다(최근 10개 보관). 기존 `backup`(글 보관함)과 따로다. 키·자격 증명은 담지 않는다."""
    paths = tf.topic_paths(ctx.workspace)
    return tbackup.make_backup(paths.folder, backups_folder(ctx), now=ctx.now())


def restore_topics(ctx, ref=None, *, latest=False, confirmed):
    """백업으로 주제 엔진 데이터를 되돌린다 — 지금 파일이 백업의 내용으로 바뀌므로 `confirmed=True`(`--yes`)가 있어야 한다(아니면 아무것도 바꾸지 않고 CONFIRMATION_REQUIRED). 백업은 확인 전에도 읽어 보고
    (바꾸지 않고) 틀리면 거절한다. 바꾸기 직전 상태는 `before-restore` 백업으로 먼저 남긴다."""
    paths = tf.topic_paths(ctx.workspace)
    folder = backups_folder(ctx)
    source = tbackup.resolve_backup(folder, ref, latest=latest)
    tbackup.read_backup(source)
    if confirmed is not True:
        raise AppError("CONFIRMATION_REQUIRED", {"항목": f"주제 엔진 백업으로 되돌리기 — {shown_topic_backup(source.name)}(지금 보관함과 설정 파일이 그 백업의 내용으로 바뀝니다 — 바꾸기 직전 상태는 before-restore 폴더에 따로 백업해 둡니다)"},
                       detail="지금 주제 엔진 보관함과 설정 파일이 그 백업의 내용으로 바뀝니다(바꾸기 직전 상태는 backups 폴더 안 before-restore 에 따로 백업해 둡니다) — 맞으면 같은 명령 끝에 --yes 를 붙여 다시 실행합니다")
    return tbackup.restore_backup(source, paths.folder, folder, now=ctx.now())


__all__ = [
    "ChannelPlan", "CheckResult", "FileState", "HistoryChannel", "HistoryReading", "InitResult", "ListResult", "PlanResult", "ReviewItem", "ReviewResult", "Row", "ShowResult", "StatusResult", "TopChannel",
    "TopResult", "backup_topics", "backups_folder", "check_channel", "check_files", "check_target", "check_today", "generate_candidates", "init_topics", "list_candidates", "merge_history", "now_stamp",
    "plan_candidates", "read_blog_history", "resolve", "restore_topics", "review_holds", "short_ref", "show_candidate", "status", "today_of", "top_candidates",
]
