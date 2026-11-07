"""규칙 기반 초안 본문 만들기 — 명령줄 `draft body` 의 서비스 함수. 후보 번호(순번이나 번호 앞부분 — `candidates` 명령과 같은 규칙)와 대상 네이버 블로그를 정하고, 그 블로그의 프로필(설정 파일의 네이버 프로필과
주제 엔진의 채널 프로필)을 읽어 `content/draft_body.py` 의 `build_body` 로 **AI 없이** 복사해 직접 고쳐 쓸 수 있는 정보형 초안 한 개를 만든다(제목 후보 3개·선택 제목·도입부·소제목 4~6개와 문단·주의사항·마무리·키워드·태그·카테고리·한 줄 요약·확인 권장).

규칙:
  · **읽기만 한다** — 보관함을 읽기 전용으로 열고(`ctx.reading_only()` — 파일이 없어도 만들지 않는다) 설정 파일(네이버 프로필)과 채널 프로필 파일을 읽을 뿐 아무것도 쓰지 않는다. 초안은 저장하지 않고 계산해서 보여 주기만 한다
    (초안을 저장하는 길은 초안 화면 묶음이 정한다). 네트워크·시계(기준 날짜만 읽는다)·난수를 쓰지 않는다.
  · 선택 입력은 `draft plan` 과 같은 11칸이고 모두 선택이다(하나도 없어도 초안이 만들어진다). 입력한 글은 프로필·기본값보다 먼저 쓰이고 그대로 본문에 들어간다. 키·토큰처럼 보이는 긴 글은 `draft plan` 과 같은 기준으로 거절한다.
  · 첫 제품은 네이버 A·B 다(운영자 확정 답변 2026-11-06 9절) — 대상 블로그를 주지 않으면 후보를 고른(없으면 추천한) 블로그 가운데 첫 번째 네이버 블로그로 정하고 그 사실을 알린다. 네이버가 아닌 블로그는 `DRAFT_OPTION_INVALID`.
  · 네이버 프로필이 아직 없어도 멈추지 않고 공통 기본값으로 만든다(확인 권장에 적힌다). 채널 프로필 파일이 없으면 기본 프로필을 쓴다. 두 설정 파일 중 하나가 깨졌으면 숨기지 않고 오류로 멈춘다.
  · **안전 판정**(독립 검증 H2): 후보의 제목·키워드·보조 키워드로 주제 엔진의 안전 판정(`topics.safety.check_text` — `draft plan` 은 부르지 않는다)을 한 번 계산한다. 자동 초안 중지(`stop`)인 후보는 본문 전체에 같은 말이 되풀이되므로
    만들지 않고 `CONTENT_INVALID` 로 거절한다(문구는 '후보 보기에서 이유를 확인해 주세요' 이고 입력한 글을 되풀이하지 않는다). 중지는 아니지만 근거 확인 필요·협찬 낱말 추정이면 초안을 만들고 확인 권장 맨 위에 경고를 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..content import body_bank as bb
from ..content import body_lang as bl
from ..content import candidates as cd
from ..content import draft_body as db
from ..content import draft_options as do
from ..content.profiles import KEYS as NAVER_KEYS
from ..errors import AppError
from ..topics import safety
from . import blog_profiles, candidates, draft
from . import topic_files as tf

STYLE_KO = {bl.STYLE_HAEYO: "해요체", bl.STYLE_HAPSYO: "합니다체"}
RULE = "─" * 8


@dataclass(frozen=True)
class BodyResult:
    row: object                     # candidates.CandidateRow — 순번을 붙인 후보
    body: object                    # DraftBody
    options: object                 # DraftOptions — 이번에 받은 선택 입력
    notes: tuple                    # 이 명령이 덧붙이는 안내(대상 블로그를 정한 방법 …) — 초안의 확인 권장과 따로 보인다
    profile_found: bool             # 그 블로그의 네이버 프로필(설정 파일)을 읽었는가
    channel_found: bool             # 채널 프로필 파일을 읽었는가(없으면 기본 프로필)

    def to_dict(self):
        return {"read_only": True, "candidate": self.row.to_dict(), "body": self.body.to_dict(), "options": self.options.to_dict(), "notes": list(self.notes), "profile_found": self.profile_found,
                "channel_found": self.channel_found}


def choose_naver_blog(candidate, blog):
    """대상 블로그와 그것을 정한 방법을 알리는 안내들. `draft plan` 과 같은 규칙으로 정하되 첫 제품은 네이버 A·B 라서, 블로그를 주지 않았을 때는 고른(없으면 추천한) 블로그 가운데
    첫 번째 네이버 블로그를 쓰고, 네이버가 하나도 없거나 네이버가 아닌 블로그를 주면 DRAFT_OPTION_INVALID."""
    chosen, notes = draft.choose_blog(candidate, blog)
    if chosen in NAVER_KEYS:
        return chosen, notes
    if blog is None:
        pool = candidate.selected_blogs or candidate.blogs
        found = [name for name in pool if name in NAVER_KEYS]
        if found:
            others = ", ".join(draft.PLATFORM_NAMES[name] for name in found[1:])
            tail = f" — 다른 블로그용은 `--blog` 로 정합니다({others})." if others else "."
            return found[0], (f"대상 블로그를 정하지 않아 네이버 블로그 중 첫 번째인 {draft.PLATFORM_NAMES[found[0]]} 용으로 만들었습니다" + tail,)
    raise AppError("DRAFT_OPTION_INVALID", {"항목": "블로그", "이유": "본문 초안은 네이버 블로그(naver_a·naver_b)용만 만듭니다 — `--blog naver_a` 처럼 네이버 블로그를 정해 주세요"},
                   detail="네이버가 아닌 블로그는 본문 초안을 만들지 않는다")


def load_channel(ctx, blog):
    """그 블로그의 채널 프로필(주제 엔진 — 읽기만 한다) → (프로필, 파일을 읽었는가). 파일이 없거나 0바이트면 기본 프로필. 읽을 수 없거나 모양이 틀린 파일은 그대로 오류."""
    snapshot = blog_profiles.read_snapshot(ctx)
    channel = next(item for item in snapshot.profiles if item.key == blog)
    return channel, snapshot.state == tf.STATE_OK


def screen(candidate):
    """후보의 제목(주제)·핵심 키워드·보조 키워드로 주제 엔진의 안전 판정(`topics.safety.check_text`)을 계산한다 — 엔진이 후보를 평가할 때(`safety.assess`)와 같은 글이다. 자동 초안 중지(`stop`)이면 본문을 만들지 않고
    `CONTENT_INVALID` 로 거절한다(입력한 글을 오류에 적지 않는다). 중지가 아니면 판정 결과를 돌려주어 생성기가 확인 권장 맨 위의 경고에 쓴다."""
    report = safety.check_text([candidate.topic, candidate.keyword, *candidate.sub_keywords])
    if report.stop:
        raise AppError("CONTENT_INVALID", {"항목": db.STOP_ITEM}, detail="주제 엔진의 안전 판정이 자동 초안 중지인 후보라 본문 초안을 만들지 않았다(입력한 글은 적지 않는다)")
    return report


def make_body(ctx, ref, *, blog=None, post_type=None, options=None):
    """후보(`ref` — 순번이나 번호 앞 4자 이상)로 규칙 기반 초안 한 개를 만든다. 읽기만 한다 — 보관함도 설정도 채널 프로필 파일도 바꾸지 않는다."""
    options = options if options is not None else do.DraftOptions()
    draft.refuse_long_tokens(options)                                         # 가리기 규칙이 모르는 긴 무작위 영숫자 키가 초안에 나가지 않게(알려진 모양은 `DraftOptions` 가 이미 거절한다)
    listed = candidates.list_candidates(ctx)                                  # 읽기 전용으로 연다(보관함이 없으면 만들지 않고 빈 목록)
    row = candidates.resolve(list(listed.rows), ref)
    candidate = row.candidate
    report = screen(candidate)
    chosen, notes = choose_naver_blog(candidate, blog)
    notes = list(notes)
    if candidate.status == cd.REJECTED:
        notes.append("이 후보는 ‘제외’ 상태입니다 — 초안만 만들었고 상태는 바꾸지 않았습니다.")
    profile, found = draft.load_profile(ctx, chosen)
    channel, channel_found = load_channel(ctx, chosen)
    body = db.build_body(candidate, profile, options, today=draft.today_kst(ctx), blog=chosen, post_type=post_type, channel=channel, safety=report)
    return BodyResult(row, body, options, tuple(notes), found, channel_found)


def body_lines(result, *, verbose=False):
    """초안을 사람이 읽는 줄로 — 복사용 본문(제목 + 본문)은 글 그대로 가운데에 놓고, 앞에 요약·뒤에 키워드·태그·카테고리·한 줄 요약·확인 권장. 분야·말투·반영한 입력은 `--verbose`(와 `--json`)에서만 보인다."""
    body, row = result.body, result.row
    lines = [f"초안 본문 — 후보 [{row.ordinal}] {body.topic} · {draft.PLATFORM_NAMES[body.blog]} 용 (규칙으로 만든 기본 초안입니다 — AI 를 쓰지 않았고 아무것도 저장하지 않았습니다)"]
    lines.append(f"  글 유형: {body.post_type}   본문 {body.chars:,}자(공백 제외, 공백 포함 {body.chars_with_spaces:,}자) · 소제목 {len(body.sections)}개 · 말투 {STYLE_KO[body.style]}")
    if body.replaced:
        lines.append(f"  ※ 후보의 ‘{body.replaced[0]}’ 형식은 ‘{body.replaced[1]}’{bl.particle(body.replaced[1], '으로', '로')} 바꿔 구성했습니다(경험을 지어내지 않습니다).")
    lines += ["제목 후보:"] + [f"  {number}. {title}" for number, title in enumerate(body.titles, 1)]
    lines.append(f"선택한 제목: {body.selected_title}")
    lines += [f"{RULE} 복사용 글(제목 + 본문) {RULE}", "", body.plain_text, "", f"{RULE} 여기까지 {RULE}"]
    lines.append("핵심 키워드: " + ", ".join(body.core_keywords))
    lines.append("보조 키워드: " + ", ".join(body.sub_keywords))
    lines.append("추천 태그: " + (body.tags_text or "없음"))
    lines.append(f"추천 카테고리: {body.category or '정하지 못했습니다'}")
    lines.append(f"한 줄 요약: {body.summary}")
    lines += ["확인 권장(있어도 초안은 이대로 복사해 쓸 수 있습니다):"] + [f"  - {text}" for text in body.checks]
    for note in result.notes:
        lines.append(f"참고: {note}")
    if verbose:
        used = ", ".join(do.LABELS[name] for name in body.used) or "없음"
        lines.append(f"만든 방법: 분야 {bb.DOMAIN_KO[body.domain]} · 반영한 입력 {used} · 협찬 안내 자리 {'있음' if body.sponsor_slot else '없음'} · 건강·금융·법률 안내 {'있음' if body.sensitive else '없음'} · "
                     f"쓰지 못한 문장 칸 {body.dropped}개 · 네이버 프로필 {'읽음' if result.profile_found else '없음'} · 채널 프로필 {'읽음' if result.channel_found else '기본값'}")
    return lines


__all__ = ["BodyResult", "body_lines", "choose_naver_blog", "load_channel", "make_body"]
