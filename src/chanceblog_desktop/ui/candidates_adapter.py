"""주제 후보 화면의 실제 공급자 — 서비스(`service/topics.py`)를 화면이 아는 모양(`ui/core/candidates.py`)으로 맞추는 얇은 어댑터다. **쓰는 길은 `make_candidates` 가 부르는 서비스 함수 `generate_candidates` 하나뿐**이다 —
화면 코드(`ui/qt`·`ui/core`)에는 파일을 쓰는 호출이 없다(시험이 소스를 훑는다). 홈·설정·블로그 관리·Seed 관리 어댑터는 그대로다.

읽기(`load_candidates`)는 서비스의 `list_candidates`(후보 전부 — 읽기 전용 열기라 보관함 파일도 폴더도 만들지 않는다)와 설정 읽기 `topic_files.load_profiles`·`load_seeds`(없으면 기본값·빈 목록 — 파일을 만들지 않는다)뿐이고,
**점수가 그 채널 가중치로 다시 계산한 값과 다른 후보는 홈과 같은 규칙(`check_candidate_score`)으로 빼고 개수만 알린다**(홈과 다른 점수를 보이지 않는다). 미리 보기(`preview_make`)는 `plan_candidates`(읽기 전용)이고
쓰기(`make_candidates`)는 `generate_candidates(confirmed=True, trend=None)` 한 번이다 — **관심도 공급자는 `None`**(네트워크 호출 0·키·자격 증명 보관소를 부르지 않는다). 서비스의 `PlanResult.notes` 는 명령줄 글이 섞여 있어 화면에는 쓰지 않는다.
서비스 오류(`AppError`)는 **종류**(다른 창이 씀·디스크 가득·쓰기 실패·더 새 판·깨짐·설정 파일)로만 나눠 화면에 알린다 — 화면 문장은 `ui/core/text.py` 의 정해진 말이고 오류의 세부(경로·예외 이름·입력한 값)는 화면에 나가지 않는다. 이 모듈은 PySide6 를 모른다.
"""
from __future__ import annotations

from ..errors import AppError
from ..service import topic_files
from ..service import topics as service
from ..service.context import make_context
from ..topics import channels as ch
from ..topics import model
from ..topics import seeds as seedmod
from .adapters import engine_failure, is_folder
from .core.candidate_rules import shown
from .core.candidates import CandidateFailure, CandidateRow, CandidatesData, CandidatesProvider, ChannelInfo, ChannelPreview, MakeOutcome, MakePreview, SeedInfo
from .core.jobs import JobCancelled
from .core.text import T

KIND_OF_CODE = {"TOPIC_STORE_LOCKED": "busy", "DISK_FULL": "disk", "FILE_WRITE_FAILED": "io", "FILE_IN_USE": "io", "FILE_PATH_TOO_LONG": "io", "DATA_DIR_UNSAFE": "io", "TOPIC_STORE_VERSION_UNSUPPORTED": "newer",
                "TOPIC_STORE_CORRUPT": "corrupt", "CANDIDATE_INVALID": "corrupt", "TOPIC_STORE_RECOVERY_PENDING": "corrupt", "TOPIC_FILE_INVALID": "invalid", "CONTENT_INVALID": "invalid"}      # 서비스 오류 코드 → 화면이 다르게 다룰 종류(나머지는 `other`)
NOT_SKIP = "SHORTAGE"                                                                  # 서비스 진단 알림 중 '건너뛰는 이유' 가 아닌 것(목표에 모자란 경로 — 결과를 설명할 뿐)


def failure_of(error, *, reading=False):
    """서비스 오류 → 화면용 실패(종류 + 진단 코드). 읽기 오류는 홈과 같은 쉬운 문장 표(`engine_failure`)를, 쓰기 오류는 종류별 정해진 말을 쓴다 — 오류의 세부·경로·입력한 값이 화면에 나가지 않는다."""
    kind = KIND_OF_CODE.get(error.code, "other")
    if reading:
        known = engine_failure(error)
        return CandidateFailure(known.user_message, known.code, kind=kind)
    return CandidateFailure(T["cand_fail_" + kind], code=error.code, kind=kind)


def channels_of(profiles):
    """채널 프로필 → 화면의 채널 정보(표시 이름·색 프리셋·후보 생성 켜짐·가중치) — 채널 순서."""
    by_key = {profile.key: profile for profile in profiles}
    found = []
    for key in ch.CHANNELS:
        profile = by_key.get(key)
        if profile is None:
            found.append(ChannelInfo(key))
            continue
        found.append(ChannelInfo(key, profile.display_name, profile.color_preset, profile.generation_enabled, tuple((name, profile.weights[name]) for name in ch.FACTOR_NAMES)))
    return tuple(found)


def trusted_rows(rows, profiles):
    """점수가 그 채널의 가중치로 다시 계산한 값과 같은 후보만(저장한 순서) → (행들, 뺀 수). 홈의 `top_candidates` 와 같은 규칙(`check_candidate_score`)이다."""
    by_key = {profile.key: profile for profile in profiles}
    kept, skipped = [], 0
    for row in rows:
        profile = by_key.get(row.candidate.channel)
        try:
            if profile is None:
                raise AppError("CANDIDATE_INVALID", {"항목": "채널"})
            model.check_candidate_score(row.candidate, profile)
        except AppError:
            skipped += 1
            continue
        kept.append(CandidateRow(row.ordinal, row.candidate, row.stop))
    return tuple(kept), skipped


def seeds_of(rows, seeds):
    """후보가 가리키는 Seed 의 낱말·분류 — ((Seed 번호, SeedInfo), …). 번호는 화면 글에 나가지 않고 상세가 낱말을 찾는 데만 쓴다."""
    wanted = {row.candidate.seed_id for row in rows if row.candidate.seed_id}
    return tuple((seed.seed_id, SeedInfo(seed.keyword, seed.major, seed.minor, seed.state)) for seed in seeds if seed.seed_id in wanted)


def preview_from(plan, profiles, seeds):
    """서비스의 미리 보기(`PlanResult`)·채널 프로필·Seed → 화면의 미리 보기. 후보 생성이 켜진 채널의 새 후보 수·남은 자리·건너뛰는 이유와 쓰는 Seed 수·승인 전 Seed 수를 구조값에서 직접 센다(서비스의 안내 글은 쓰지 않는다).
    새 후보가 하나도 없으면 까닭(`lacks`)을 가린다: 일하는 채널이 없다 → 승인한 Seed 가 없다 → 남은 자리가 없다 → 그 밖에 새로 만들 것이 없다."""
    names = {profile.key: profile.display_name for profile in profiles}
    enabled = [item for item in plan.plans if item.enabled]
    rows = tuple(ChannelPreview(item.channel, shown(names.get(item.channel) or item.name, 30), len(item.candidates), None if item.slots is None else item.slots.remaining, item.target, item.duplicates,
                                tuple(dict.fromkeys(entry.title for entry in item.notices if entry.code != NOT_SKIP))) for item in enabled)
    total = sum(item.new for item in rows)
    lacks = []
    if not enabled:
        lacks.append("no_channel")
    elif not any(seedmod.usable_seeds(seeds, item.channel) for item in enabled):
        lacks.append("no_seed")
    elif not total:
        lacks.append("full" if all(item.slots is not None and item.slots.remaining == 0 for item in enabled) else "none")
    used = len({candidate.seed_id for item in enabled for candidate in item.candidates if candidate.seed_id})
    proposed = sum(1 for seed in seeds if seed.state == seedmod.STATE_PROPOSED)
    return MakePreview(plan.store_state, rows, total, used, proposed, tuple(lacks), False)


class ServiceCandidatesProvider(CandidatesProvider):
    sample = False

    def __init__(self, data_dir=None, *, context_factory=None):
        self._data_dir, self._factory = data_dir, context_factory or make_context

    def _context(self):
        if self._data_dir is not None and not is_folder(self._data_dir):                  # 직접 정한 데이터 폴더가 없거나 파일이면 빈 화면이 아니라 쉬운 안내(홈·설정·블로그·Seed 관리와 같다)
            raise CandidateFailure(T["data_dir_missing"], code="DATA_DIR_NOT_FOUND", kind="io")
        return self._factory(data_dir=self._data_dir)

    @staticmethod
    def _seeds(paths):
        """Seed 파일 읽기 — 상세의 'Seed 출처' 낱말을 찾는 데만 쓰므로 못 읽어도 후보 읽기를 막지 않는다(그 칸이 `Seed 정보를 찾지 못했어요` 가 된다)."""
        try:
            return topic_files.load_seeds(paths).value
        except AppError:
            return ()

    def load_candidates(self, progress, cancelled):
        """후보를 읽는다 — 읽기뿐이다(보관함·설정 파일을 만들지도 올리지도 바꾸지도 않는다)."""
        ctx = self._context()
        try:
            result = service.list_candidates(ctx)
            if cancelled():
                raise JobCancelled()
            paths = topic_files.topic_paths(ctx.workspace)
            profiles = topic_files.load_profiles(paths).value
        except AppError as error:
            raise failure_of(error, reading=True) from None
        if cancelled():
            raise JobCancelled()
        rows, skipped = trusted_rows(result.rows, profiles)
        return CandidatesData(rows, result.store_state, channels_of(profiles), seeds_of(rows, self._seeds(paths)), skipped, result.total, False)

    def preview_make(self, progress, cancelled):
        """만들 후보를 미리 본다 — 읽기뿐이다(`plan_candidates` — 아무것도 쓰지 않고 보관함 파일도 만들지 않는다)."""
        ctx = self._context()
        try:
            plan = service.plan_candidates(ctx, trend=None)
            if cancelled():
                raise JobCancelled()
            paths = topic_files.topic_paths(ctx.workspace)
            profiles, seeds = topic_files.load_profiles(paths).value, topic_files.load_seeds(paths).value
        except AppError as error:
            raise failure_of(error) from None
        if cancelled():
            raise JobCancelled()
        return preview_from(plan, profiles, seeds)

    def make_candidates(self, preview, progress, cancelled):
        """**이 화면의 유일한 쓰기** — 사용자가 확인창에서 `만들기` 를 눌렀을 때만 불린다. 서비스 함수 하나(`generate_candidates` — 한 트랜잭션: 하나라도 안 되면 하나도 저장되지 않는다)를 부르고, 중간에 끊을 수 없다(취소 신호를 보지 않는다)."""
        if not preview.can_make:
            raise CandidateFailure(T["cand_fail_other"], code="CONTENT_INVALID", kind="invalid")
        ctx = self._context()
        try:
            saved = service.generate_candidates(ctx, confirmed=True, trend=None)
        except AppError as error:
            raise failure_of(error) from None
        return MakeOutcome(saved.total, sum(item.duplicates for item in saved.plans), sum(len(item.withheld) for item in saved.plans))


__all__ = ["KIND_OF_CODE", "ServiceCandidatesProvider", "channels_of", "failure_of", "preview_from", "seeds_of", "trusted_rows"]
