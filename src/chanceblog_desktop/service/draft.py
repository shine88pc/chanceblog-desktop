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

import re
from dataclasses import dataclass

from ..content import candidates as cd
from ..content import draft_options as do
from ..content import draft_plan as dp
from ..content import status as st
from ..content.profiles import KEYS as NAVER_KEYS
from ..errors import AppError
from . import candidates

PLATFORM_NAMES = {"github_pages": "GitHub Pages", "blogger_en": "Blogger 영문", "blogger_ko": "Blogger 한글", "naver_a": "네이버 A", "naver_b": "네이버 B"}
# 가리기 규칙이 모르는 모양 없는 긴 무작위 영숫자(Unsplash 키 43자처럼 긴 것)가 계획 출력에 그대로 나가지 않게 글칸에서 거절한다. 네이버 키(client_id 20자·secret 10자)와 24자 미만의 키는 이 규칙이 못 막는다(모양만으로는 정상 글과 구분할 수 없다).
# 주소 칸(`urls`)은 뺀다 — 주소 경로의 번호·이름은 정상이다(그래서 주소 칸에 든 키도 못 막는다 — 후속).
# 영숫자만 24자 이상(영문자와 숫자가 함께)은 글에서 거의 나오지 않는다 — `security/shape.looks_secret` 처럼 `-`·`/`·`.` 까지 한 덩어리로 보면 정상 입력 202개 중 68개(33.7% — 모델명·파일 이름·주소 조각)를 거절해서 쓰지 않았다.
_RANDOM_RUN = re.compile(r"[A-Za-z0-9]{24,}")
_ESCAPED_RUN = re.compile(r"(?:\\u[0-9A-Fa-f]{4}){6,}")                 # `\uXXXX` 를 여섯 번 넘게 이은 글 — 글자를 이스케이프로 써서 위 모양을 피한 것
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")                   # `+`·`/` 가 든 base64 덩어리 — 40자 이상이고 무작위로 보일 때만(경로 `a/b/c` 와 구분)
_URLSAFE_RUN = re.compile(r"[A-Za-z0-9_-]{40,}")                         # `-`·`_` 가 몇 개 든 긴 키(base64url) — 40자 이상, 무작위로 보이고 `-`·`_` 가 8글자에 하나 이하일 때만(낱말을 붙임표로 이은 이름·주소 조각은 붙임표가 더 잦다)
TOKEN_REASON = "영문·숫자가 24자 이상 이어진 긴 글(키·토큰·번호처럼 보입니다)이 들어 있습니다 — 키나 토큰이면 지우고, 번호나 해시라면 앞 몇 글자만 적거나 말로 바꿔 써 주세요"
FREE_TEXT_FIELDS = ("message", "experience", "opinion", "audience", "title_direction", "conclusion")
FREE_TEXT_LISTS = ("must_include", "exclude", "price_date")


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


def _random_looking(run):
    """대문자·소문자가 각각 20% 이상이고 숫자가 4% 이상인가 — 무작위 base64 는 대문자·소문자가 각각 약 40%·숫자 약 16% 이고, 경로·이름·낱말은 소문자나 대문자 한쪽이 훨씬 많다(40자 무작위 글이 이 문턱에 못 미쳐 놓칠 확률은 2% 안팎이고 길수록 줄어든다)."""
    size = len(run)
    return sum(ch.isupper() for ch in run) * 5 >= size and sum(ch.islower() for ch in run) * 5 >= size and sum(ch.isdigit() for ch in run) * 25 >= size


def looks_like_a_token(text):
    """글에 키·토큰처럼 보이는 긴 덩어리가 있는가 — 영문자와 숫자가 함께 든 영숫자 24자 이상, `\\uXXXX` 이스케이프를 여섯 번 넘게 이은 글, 무작위로 보이고(대문자·소문자·숫자가 고루 섞임) `+` 나 `/` 가 든 40자 이상의 base64 덩어리,
    `-`·`_` 가 드문(8글자에 하나 이하) 무작위로 보이는 40자 이상의 덩어리."""
    if not isinstance(text, str):
        return True
    if _ESCAPED_RUN.search(text):
        return True
    if any(any(ch.isalpha() for ch in run) and any(ch.isdigit() for ch in run) for run in _RANDOM_RUN.findall(text)):
        return True
    if any(("+" in run or "/" in run) and _random_looking(run) for run in _BASE64_RUN.findall(text)):
        return True
    return any(_random_looking(run) and (run.count("-") + run.count("_")) * 8 <= len(run) for run in _URLSAFE_RUN.findall(text))


def refuse_long_tokens(options):
    """선택 입력의 글칸(주소 칸 제외)에 긴 무작위 영숫자가 있으면 DRAFT_OPTION_INVALID — 어느 칸인지만 알리고 입력한 글은 오류의 어디에도 적지 않는다."""
    for name in FREE_TEXT_FIELDS + FREE_TEXT_LISTS:
        value = getattr(options, name)
        for text in ((value,) if isinstance(value, str) else value):
            if looks_like_a_token(text):
                raise AppError("DRAFT_OPTION_INVALID", {"항목": do.LABELS[name], "이유": TOKEN_REASON}, detail="긴 영숫자 덩어리가 들어 있다(값은 적지 않는다)")


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
    refuse_long_tokens(options)                                               # 가리기 규칙이 모르는 긴 무작위 영숫자 키가 계획에 나가지 않게(알려진 모양은 `DraftOptions` 가 이미 거절한다)
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
