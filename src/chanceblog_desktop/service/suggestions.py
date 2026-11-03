"""자동 후보 제안 — 서비스 층: 명령줄 `candidates suggest`(읽기만 함)·`candidates suggest --add`(고른 제안을 새 후보로 보관함에 넣음)·`candidates list --priority`·`candidates show` 의 우선도.
계산·규칙은 `content/suggest*.py` 가 하고 여기서는 보관함·설정을 읽어 넘기고 결과를 사람이 쓰는 흐름으로 잇는다(네트워크·AI·키는 쓰지 않는다 — 외부 검색 데이터가 없는 칸은 '데이터 없음').

규칙:
  · `suggest` 는 **읽기만 한다** — 보관함을 `ctx.reading_only()` 로 열어(없으면 비어 있는 것으로 본다) 파일을 만들지도 올리지도 않고, 설정 파일도 읽기만 한다. 후보가 하나도 없어도 프로필로 먼저 제안한다.
  · 기존 글 제목은 **보관함의 원고 제목과 '선택됨' 후보의 주제**에서만 읽는다 — 연결한 chanceblog 저장소의 글 제목은 읽지 않는다(`publish/` 에 `_posts` 머리말의 제목만 안전하게 읽는 함수가 아직 없어 이번에는 하지 않았다 — 알려 둔 한계).
  · `--add` 는 제안을 먼저 보여 주고 `--yes` 없이는 넣지 않는다(넣을 목록만 보인다). 넣을 때는 보관함의 한 쓰기 트랜잭션(`Store.add_candidates`)에서 **키워드(같은 블로그)로 이미 있는지 다시 확인**하고 있으면 건너뛰므로
    같은 명령을 다시 실행해도 겹치지 않는다. 번호는 같은 입력이면 같은 순서이고 보관함에 넣은 제안은 숨겨지되 번호는 그대로라서(`content/suggest.py`) 같은 `--add 1,2` 를 되풀이해도 다른 제안이 들어가지 않는다.
    번호 대신 키워드(따옴표로 묶음)로도 고를 수 있다 — 그 사이 보관함이 바뀌어 번호가 달라졌을 때를 위해서다.
  · 오류 문구에는 사용자가 친 값을 싣지 않는다(몇 번째 값인지만).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace

from ..content import candidates as cd
from ..content import suggest as sg
from ..content.profiles import KEYS as NAVER_KEYS
from ..errors import AppError
from .candidates import _fresh_stamp, kst, numbered

LIMITS_NOTE = "기존 글 확인은 보관함의 원고 제목과 고른 후보의 주제를 기준으로 합니다(연결한 chanceblog 저장소의 글 제목은 아직 읽지 않습니다)."
OTHER_BLOG_GUIDANCE = ("이 블로그는 프로필(주제·카테고리)을 저장해 두는 곳이 아직 없어 제안할 수 없습니다 — 지금은 네이버 A·B 프로필의 주제로만 제안합니다. "
                       "직접 적으려면 `candidates add` 를, 표로 가져오려면 `candidates import-csv` 를 씁니다.")
MAX_SPEC_ITEMS = 200
MAX_SPEC_CHARS = 2000
_NUMBER = re.compile(r"[0-9]{1,6}")
_RANGE = re.compile(r"([0-9]{1,4})\s*[-~]\s*([0-9]{1,4})")
_SPLIT = re.compile(r"[,，]")


# ---- 읽기 ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Vault:
    candidates: tuple               # Candidate — 보관함의 모든 후보(만든 시각 순이 아니라 저장소가 주는 순서)
    projects: tuple                 # Summary — 보관함의 글(원고) 목록
    state: str                      # ready · old_structure · missing

    def titles(self):
        """기존 글 제목들 — 보관함의 원고 제목 + '선택됨' 후보의 주제(고르면 쓰기로 한 글감이다)."""
        return tuple(item.title for item in self.projects) + tuple(item.topic for item in self.candidates if item.status == cd.SELECTED)


def read_vault(ctx):
    """보관함을 **읽기 전용**으로 읽는다(파일이 없으면 비어 있는 것으로 — 만들지 않는다). 쓰다 꺼져 끝내지 못한 저장이 남았으면 STORE_RECOVERY_PENDING 으로 멈춘다."""
    try:
        store = ctx.reading_only().store()
    except AppError as error:
        if error.code == "CONTENT_NOT_FOUND":
            return Vault((), (), "missing")
        raise
    with store:
        return Vault(tuple(store.list_candidates()), tuple(store.list()), "old_structure" if store.needs_migration else "ready")


def today_of(ctx):
    """오늘 — 한국 시간의 달력 날짜(시계는 `ctx` 가 준다)."""
    return kst(ctx.stamp()).date()


def profile_for(ctx, blog):
    """그 블로그의 저장된 네이버 프로필(없으면 None). 다른 블로그는 프로필을 저장하는 곳이 아직 없어 None. 설정 파일이 깨졌으면 SETTINGS_INVALID 로 멈춘다."""
    if blog not in NAVER_KEYS:
        return None
    try:
        return ctx.settings.naver_profile(blog)
    except AppError as error:
        if error.code != "NAVER_PROFILE_MISSING":
            raise
        return None


def profiled_blogs(ctx):
    return tuple(blog for blog in NAVER_KEYS if profile_for(ctx, blog) is not None)


# ---- 제안 ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Group:
    blog: str
    profile_name: str               # 프로필의 표시명(프로필이 없으면 '')
    report: object                  # sg.Report

    def to_dict(self):
        data = self.report.to_dict()
        data["profile_name"] = self.profile_name
        return data


@dataclass(frozen=True)
class SuggestResult:
    groups: tuple
    vault_state: str
    limits: tuple

    def to_dict(self):
        return {"blogs": [group.to_dict() for group in self.groups], "store": self.vault_state, "limits": list(self.limits)}


def _report(ctx, vault, blog, profile, *, count, month, post_type):
    report = sg.suggest(profile, today=today_of(ctx), existing_titles=vault.titles(), candidates=vault.candidates, blog=blog, count=count, month=month, post_type=post_type)
    if profile is None and blog not in NAVER_KEYS:
        report = replace(report, guidance=OTHER_BLOG_GUIDANCE)
    return report


def run_suggest(ctx, *, blog=None, count=sg.DEFAULT_COUNT, month=None, post_type=None):
    """프로필·보관함·달력으로 주제 후보를 제안한다(읽기만). `blog` 를 안 주면 프로필이 저장된 네이버 블로그마다(하나도 없으면 네이버 A 에 프로필 안내)."""
    vault = read_vault(ctx)
    blogs = (blog,) if blog is not None else (profiled_blogs(ctx) or (NAVER_KEYS[0],))
    groups = []
    for name in blogs:
        profile = profile_for(ctx, name)
        groups.append(Group(name, "" if profile is None else profile.display_name, _report(ctx, vault, name, profile, count=count, month=month, post_type=post_type)))
    return SuggestResult(tuple(groups), vault.state, (LIMITS_NOTE,))


# ---- 넣기 ---------------------------------------------------------------------------------------------------------------------------
def parse_add_spec(text):
    """`--add` 값 → 항목들. `all`(처음 보이던 번호 1~개수 전부) 또는 쉼표로 나눈 번호(`3`)·번호 범위(`2-4`)·키워드 글. 틀리면 ValueError(사용자가 친 글은 싣지 않는다)."""
    if not isinstance(text, str) or len(text) > MAX_SPEC_CHARS:
        raise ValueError("너무 깁니다")
    tokens = [token.strip() for token in _SPLIT.split(text) if token.strip()]
    if not tokens:
        raise ValueError("넣을 제안의 번호(예: 1,3)나 all 을 적어야 합니다")
    if any(token.casefold() in ("all", "전체") for token in tokens):
        if len(tokens) != 1:
            raise ValueError("all 은 다른 값과 함께 쓸 수 없습니다")
        return ("all",)
    items = []
    for token in tokens:
        span = _RANGE.fullmatch(token)
        if span:
            low, high = int(span.group(1)), int(span.group(2))
            if not 1 <= low <= high or high - low >= MAX_SPEC_ITEMS:
                raise ValueError("번호 범위가 올바르지 않습니다(예: 2-4)")
            items += range(low, high + 1)
        elif _NUMBER.fullmatch(token):
            if int(token) < 1:
                raise ValueError("번호는 1 이상이어야 합니다")
            items.append(int(token))
        else:
            items.append(token)
    if len(items) > MAX_SPEC_ITEMS:
        raise ValueError(f"한 번에 {MAX_SPEC_ITEMS}개까지 넣을 수 있습니다")
    return tuple(dict.fromkeys(items))


def merge_add_specs(parts):
    """`--add` 를 여러 번 적었을 때(`--add 1 --add 3,5`) 값을 적은 순서대로 이어 붙인다 — 마지막 것만 남기지 않는다. `all` 은 다른 값과 함께 쓸 수 없고 한 번에 `MAX_SPEC_ITEMS` 개까지다."""
    merged = tuple(dict.fromkeys(item for part in parts for item in part))
    if "all" in merged and len(merged) != 1:
        raise ValueError("all 은 다른 값과 함께 쓸 수 없습니다")
    if len(merged) > MAX_SPEC_ITEMS:
        raise ValueError(f"한 번에 {MAX_SPEC_ITEMS}개까지 넣을 수 있습니다")
    return merged


@dataclass(frozen=True)
class AddItem:
    suggestion: object              # sg.Suggestion — 넣을(또는 건너뛴) 제안(번호로 찾은 숨긴 제안은 None)
    label: str                      # 사용자가 지정한 방법: 번호 · 키워드 · all
    action: str                     # add · skip
    reason: str = ""                # 건너뛴 이유

    def to_dict(self):
        return {"label": self.label, "action": self.action, "reason": self.reason, "suggestion": None if self.suggestion is None else self.suggestion.to_dict()}


@dataclass(frozen=True)
class AddResult:
    blog: str
    confirmed: bool
    items: tuple                    # AddItem — 지정한 순서대로
    added: tuple                    # CandidateRow — 넣었으면 그 후보들(전체 목록 기준 순번)
    late_skips: tuple               # AddItem — 넣는 순간 이미 있어 건너뛴 것(그 사이 다른 명령이 넣었다)

    def to_dict(self):
        return {"blog": self.blog, "confirmed": self.confirmed, "items": [item.to_dict() for item in self.items], "added": [row.to_dict() for row in self.added],
                "late_skips": [item.to_dict() for item in self.late_skips]}


def _not_found(position, guidance=None, notes=()):
    why = "" if not guidance else " — 지금 이 블로그에는 제안이 하나도 없다: " + guidance + "".join(" " + note for note in notes)       # notes 는 버린 씨앗 개수뿐(씨앗 글은 없다)
    return AppError("SUGGESTION_NOT_FOUND", {"항목": f"--add 의 {position}번째 값"}, detail="지금 제안 목록에 없다 — `candidates suggest` 로 번호를 다시 확인한다" + why)


def _resolve(report, vault, blog, spec):
    """지정한 번호·키워드를 지금의 제안 목록과 맞춰 본다 → AddItem 들. 목록에 없는 값이 하나라도 있으면 SUGGESTION_NOT_FOUND(아무것도 넣지 않는다)."""
    by_rank = {item.rank: item for item in report.suggestions}
    by_key = {cd.keyword_key(item.keyword): item for item in (*report.suggestions, *report.more)}                   # 키워드는 요청한 개수 뒤의 제안에서도 찾는다
    owned = sg.vault_keys(vault.candidates, blog)
    out, seen = [], set()

    def add(item, label):
        key = cd.keyword_key(item.keyword)
        if key not in seen:
            seen.add(key)
            out.append(AddItem(item, label, "add"))

    for position, wanted in enumerate(spec, start=1):
        if wanted == "all":                                          # 처음 보이던 번호 1~개수 전부 — 이미 넣어 숨겨진 번호는 건너뛰므로 되풀이해도 다음 제안이 딸려 들어가지 않는다(다음 쪽은 번호 범위로)
            quiet = []
            for rank in range(1, report.count + 1):
                if rank in by_rank:
                    add(by_rank[rank], "all")
                elif rank in report.hidden_ranks:
                    quiet.append(rank)
            if quiet:
                out.append(AddItem(None, "all", "skip", "번호 " + ", ".join(str(rank) for rank in quiet) + " 은(는) 이미 보관함에 있거나 최근에 고른 제안이라 숨겨져 있습니다(번호는 그대로입니다)"))
        elif isinstance(wanted, int):
            if wanted in by_rank:
                add(by_rank[wanted], f"번호 {wanted}")
            elif wanted in report.hidden_ranks:
                out.append(AddItem(None, f"번호 {wanted}", "skip", "이미 보관함에 있거나 최근에 고른 제안이라 숨겨져 있습니다(번호는 그대로입니다)"))
            else:
                raise _not_found(position, report.guidance, report.notes)
        else:
            key = cd.keyword_key(wanted)
            if key in by_key:
                add(by_key[key], "키워드")
            elif key and key in owned:
                out.append(AddItem(None, "키워드", "skip", "이미 보관함에 있습니다"))
            else:
                raise _not_found(position, report.guidance, report.notes)
    return out


def add_suggestions(ctx, spec, *, blog, count=sg.DEFAULT_COUNT, month=None, post_type=None, confirmed=False):
    """고른 제안을 '새 후보'(출처 표시 `프로필 제안`)로 보관함에 넣는다. `confirmed` 가 `True` 가 아니면 아무것도 넣지 않고 넣을 목록만 돌려준다(보관함도 읽기만 한다).
    넣을 때는 보관함의 쓰기 트랜잭션 안에서 **같은 키워드·같은 블로그의 후보가 이미 있는지 다시 확인**해 있으면 건너뛰므로(번호가 아니라 키워드로 판정) 같은 명령을 되풀이해도 겹치지 않는다."""
    vault = read_vault(ctx)
    profile = profile_for(ctx, blog)
    report = _report(ctx, vault, blog, profile, count=count, month=month, post_type=post_type)
    items = _resolve(report, vault, blog, spec)
    chosen = [item for item in items if item.action == "add"]
    if confirmed is not True or not chosen:
        return AddResult(blog, confirmed is True, tuple(items), (), ())               # 확인했는데 넣을 것이 없으면 '넣은 것 없음' 으로(미리 보기가 아니다)
    outcome = {}

    def plan(existing):                                            # 쓰기 잠금 안에서 — 지금 있는 후보로 다시 확인한다
        rows = numbered(existing)
        taken = {cd.keyword_key(row.candidate.keyword) for row in rows if blog in row.candidate.blogs}
        stamp = _fresh_stamp(ctx, rows)
        ids = sorted(uuid.uuid4().hex for _ in chosen)             # 번호를 오름차순으로 나눠 준다 — 같은 시각에 만든 후보도 제안 번호 순서로 순번이 매겨진다
        fresh, late = [], []
        for number, item in enumerate(chosen):
            found = item.suggestion
            key = cd.keyword_key(found.keyword)
            if key in taken:
                late.append(replace(item, action="skip", reason="넣는 순간 이미 보관함에 있어 건너뛰었습니다"))
                continue
            taken.add(key)
            candidate = cd.Candidate.new(found.topic, found.keyword, (blog,), candidate_id=ids[number], now=ctx.stamp(), sub_keywords=found.sub_keywords, post_type=found.post_type,
                                         reason=found.stored_reason)
            fresh.append(replace(candidate, created_at=stamp, updated_at=stamp))
        outcome["rows"], outcome["late"] = rows, late
        return fresh

    with ctx.store() as store:
        added = store.add_candidates(plan)
    final = {row.candidate.candidate_id: row for row in numbered([row.candidate for row in outcome["rows"]] + list(added))}
    return AddResult(blog, True, tuple(items), tuple(final[item.candidate_id] for item in added), tuple(outcome["late"]))


# ---- 보관함 후보의 우선도 ------------------------------------------------------------------------------------------------------------------
def assess_rows(ctx, rows, *, blog=None):
    """후보 줄들(`CandidateRow`)에 같은 계산을 적용한다 → ({후보 번호: sg.Assessment}, 알림 글들). 보관함 값은 바꾸지 않는다(읽기만 한다). 후보의 블로그 중 프로필이 저장된 첫 블로그(`blog` 를 주면 그 블로그)의 프로필로 적합도를 본다.
    프로필 설정을 읽을 수 없으면(SETTINGS_INVALID) 적합도 없이 계산하고 그 사실을 알림에 적는다."""
    vault = read_vault(ctx)
    index = sg.TitleIndex(vault.titles())
    project_titles = {item.project_id: item.title for item in vault.projects}
    today, found, notes, profiles = today_of(ctx), {}, [], {}

    def profile_of(name):
        if name not in profiles:
            try:
                profiles[name] = profile_for(ctx, name)
            except AppError as error:
                if error.code != "SETTINGS_INVALID":
                    raise
                profiles[name] = None
                notes.append("설정 파일을 읽을 수 없어 블로그 프로필 적합도는 계산하지 않았습니다(오류 코드 SETTINGS_INVALID — `doctor` 로 확인합니다).")
        return profiles[name]

    for row in rows:
        item = row.candidate
        profile = None
        for name in ((blog,) if blog else item.blogs):
            profile = profile_of(name)
            if profile is not None:
                break
        own = (project_titles[item.project_id],) if item.project_id in project_titles else ()
        found[item.candidate_id] = sg.assess(item, profile=profile, today=today, titles=index, own_titles=own)
    return found, tuple(dict.fromkeys(notes))


__all__ = [
    "AddItem", "AddResult", "Group", "SuggestResult", "Vault", "add_suggestions", "assess_rows", "merge_add_specs", "parse_add_spec", "profile_for", "profiled_blogs", "read_vault", "run_suggest",
    "today_of",
]
