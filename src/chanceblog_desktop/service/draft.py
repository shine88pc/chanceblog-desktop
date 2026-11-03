"""작성 기반 만들기 — 명령줄 `draft plan` 의 서비스 함수. 후보 번호(순번이나 번호 앞부분 — `candidates` 명령과 같은 규칙)와 대상 블로그를 정하고, 그 블로그의 프로필을 읽어
`content/draft_plan.py` 의 `build_plan` 으로 작성 기반을 만든다(제목 후보 3개·권장 목차·소제목·핵심 내용·주의사항·태그·확인 권장). 초안 문장은 만들지 않는다.

규칙:
  · **읽기만 한다** — 보관함을 읽기 전용으로 열고(`ctx.reading_only()` — 파일이 없어도 만들지 않는다) 설정 파일(프로필)을 읽을 뿐 아무것도 쓰지 않는다. 계획은 저장하지 않고 계산해서 보여 주기만 한다.
  · 선택 입력이 하나도 없어도 계획이 만들어진다(`DraftOptions` 는 모두 선택). 대상 블로그를 주지 않으면 그 후보를 고른 블로그(여럿이면 첫 번째)·없으면 추천 대상 블로그의 첫 번째로 정하고 그 사실을 알린다.
  · 네이버 블로그의 프로필이 아직 없으면 멈추지 않고 공통 기본값으로 만든다(계획의 확인 권장에 적힌다). 설정 파일이 깨졌으면 숨기지 않고 `SETTINGS_INVALID`.
  · 후보가 네이버 A·B 둘 다를 대상으로 하면 다른 네이버 블로그용 계획도 같은 입력으로 만들어 서로 너무 비슷한지 `check/similarity.py` 로 견준다(경고만 하고 막지 않는다).
  · 네트워크를 쓰지 않는다 — 참고 주소는 글자로만 다룬다(열지도 가져오지도 않는다).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..content import candidates as cd
from ..content import draft_options as do
from ..content import draft_plan as dp
from ..content import status as st
from ..content.profiles import KEYS as NAVER_KEYS
from ..errors import AppError
from . import candidates

PLATFORM_NAMES = {"github_pages": "GitHub Pages", "blogger_en": "Blogger 영문", "blogger_ko": "Blogger 한글", "naver_a": "네이버 A", "naver_b": "네이버 B"}


@dataclass(frozen=True)
class PlanResult:
    row: object                     # candidates.CandidateRow — 순번을 붙인 후보
    plan: object                    # DraftPlan
    options: object                 # DraftOptions — 이번에 받은 선택 입력
    notes: tuple                    # 이 명령이 덧붙이는 안내(대상 블로그를 정한 방법 …) — 계획의 확인 권장과 따로 보인다
    profile_found: bool             # 그 블로그의 프로필을 읽었는가
    comparison: object              # dp.PlanComparison(다른 네이버 블로그용 계획과 견준 것) 또는 None
    other_blog: object = None       # 견준 다른 네이버 블로그

    def to_dict(self):
        data = {"read_only": True, "candidate": self.row.to_dict(), "plan": self.plan.to_dict(), "options": self.options.to_dict(), "notes": list(self.notes), "profile_found": self.profile_found,
                "comparison": None}
        if self.comparison is not None:
            report = self.comparison.report
            data["comparison"] = {"blog": self.other_blog, "overall": report.overall, "title": report.title, "intro": report.intro, "body": report.body, "tags": report.tags, "level": report.level,
                                  "warnings": list(self.comparison.warnings)}
        return data


def choose_blog(candidate, blog):
    """대상 블로그와 그것을 정한 방법을 알리는 안내들. 주지 않으면 그 후보를 고른 블로그(여럿이면 첫 번째)·고른 적이 없으면 추천 대상 블로그의 첫 번째."""
    if blog is not None:
        if not isinstance(blog, str) or blog not in st.PLATFORMS:
            raise AppError("DRAFT_OPTION_INVALID", {"항목": "블로그", "이유": "다음 중 하나여야 합니다: " + ", ".join(st.PLATFORMS)})
        if blog not in candidate.blogs and blog not in candidate.selected_blogs:
            return blog, (f"{PLATFORM_NAMES[blog]} 은(는) 이 후보의 추천 대상 블로그({', '.join(PLATFORM_NAMES[name] for name in candidate.blogs)})가 아니지만 요청대로 만들었습니다.",)
        return blog, ()
    pool = candidate.selected_blogs or candidate.blogs
    chosen = pool[0]
    why = "고른 블로그" if candidate.selected_blogs else "추천 대상 블로그"
    if len(pool) > 1:
        return chosen, (f"대상 블로그를 정하지 않아 {why} 중 첫 번째인 {PLATFORM_NAMES[chosen]} 용으로 만들었습니다 — 다른 블로그용은 `--blog` 로 정합니다(" + ", ".join(PLATFORM_NAMES[name] for name in pool[1:]) + ").",)
    return chosen, ()


def load_profile(ctx, blog):
    """그 블로그의 프로필(네이버만 있다). 아직 없으면 (None, False) — 멈추지 않는다. 설정 파일이 깨졌으면 그대로 오류."""
    if blog not in NAVER_KEYS:
        return None, False
    try:
        return ctx.settings.naver_profile(blog), True
    except AppError as error:
        if error.code != "NAVER_PROFILE_MISSING":
            raise
        return None, False


def today_kst(ctx):
    """기준 날짜 — 한국 시간의 오늘(`YYYY-MM-DD`)."""
    return candidates.kst(ctx.stamp()).strftime("%Y-%m-%d")


def _other_naver(candidate, blog):
    other = "naver_b" if blog == "naver_a" else "naver_a"
    return other if blog in NAVER_KEYS and (other in candidate.blogs or other in candidate.selected_blogs) else None


def make_plan(ctx, ref, *, blog=None, post_type=None, options=None):
    """후보(`ref` — 순번이나 번호 앞 4자 이상)로 작성 기반을 만든다. 읽기만 한다 — 보관함도 설정도 바꾸지 않는다."""
    options = options if options is not None else do.DraftOptions()
    listed = candidates.list_candidates(ctx)                                  # 읽기 전용으로 연다(보관함이 없으면 만들지 않고 빈 목록)
    row = candidates.resolve(list(listed.rows), ref)
    candidate = row.candidate
    chosen, notes = choose_blog(candidate, blog)
    notes = list(notes)
    if candidate.status == cd.REJECTED:
        notes.append("이 후보는 ‘제외’ 상태입니다 — 계획만 만들었고 상태는 바꾸지 않았습니다.")
    profile, found = load_profile(ctx, chosen)
    today = today_kst(ctx)
    plan = dp.build_plan(candidate, profile, options, today=today, blog=chosen, post_type=post_type)
    comparison, other = None, _other_naver(candidate, chosen)
    if other is not None:
        other_profile, _found = load_profile(ctx, other)
        comparison = dp.compare_plans(plan, dp.build_plan(candidate, other_profile, options, today=today, blog=other, post_type=post_type))
    return PlanResult(row, plan, options, tuple(notes), found, comparison, other)


__all__ = ["PlanResult", "choose_blog", "load_profile", "make_plan", "today_kst"]
