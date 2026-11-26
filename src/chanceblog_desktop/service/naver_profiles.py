"""네이버 프로필 합쳐 읽기(글 흐름 1b, 결정 D-648) — **데이터 형식을 바꾸지 않고** 읽을 때 두 곳을 합친다.

네이버 블로그 프로필이 사는 곳은 둘로 갈라져 있었다. 명령줄(`naver-profile set`)은 설정 파일(`settings.json` 의 `naver_profiles`)에 쓰고, 화면의 `블로그 관리` 는 채널 프로필 파일
(`topic_engine/channel_profiles.json`)에 쓴다. 네이버 검토·복사(`review.request_review`)는 설정 파일의 프로필만 읽어서 **화면만 쓰는 사람은 네이버 검토를 켤 수 없었다**.

  · `profile_for(ctx, 블로그)` — **설정 파일의 프로필이 먼저**다(명령줄로 정한 값이 우선). 없을 때만 블로그 관리에 **블로그 ID 나 주소가 등록된** 슬롯에서 표시 이름·블로그 주소·주제·대상 독자·말투와
    기본 태그(주요 주제 낱말 — 복사 패키지는 태그가 하나는 있어야 한다)를 가져와 프로필을 만든다(나머지 칸은 프로필의 기본값이다). 주요 주제가 없으면 태그가 없어 검토가 NAVER_PACKAGE_INCOMPLETE 로 멈춘다. 만들 수 없으면(등록 안 됨·네이버 블로그 주소가 아님·채널 파일을 읽을 수 없음) 예전처럼 NAVER_PROFILE_MISSING 이다.
    **블로그 관리의 우선 키워드·제외 키워드·선호 글 유형은 읽지 않는다** — 그 화면이 세 칸을 '지금 저장만 해요' 라고 말하고(결정 D-241, `tests/test_ui_blogs_topic.py` 의 꼬리표 시험이 엔진 코드의 읽기를 막는다) 프로필의 '제외 주제' 는 복사 패키지의 주의 문장을 만들므로,
    이 세 칸에서 값을 가져오면 그 말이 거짓이 된다. 합친 프로필의 '제외 주제' 는 늘 비어 있다(설정 파일의 프로필을 쓰는 사람만 이 칸을 채운다).
    설정 파일이 깨져 있으면(SETTINGS_INVALID) 합치지 않고 그대로 멈춘다 — 깨진 파일을 숨기지 않는다.
  · `profile_keys(ctx)` — 지금 검토할 수 있는(프로필이 읽히는) 네이버 블로그 열쇠들.
**읽기만 한다**: 파일도 폴더도 만들지 않고 두 파일의 모양·위치·쓰는 길은 그대로다(이관 없음). 화면에서 프로필을 만들고 고치는 일은 이 묶음에 없다(1b-2).
"""
from __future__ import annotations

from ..content.profiles import KEYS as NAVER_KEYS
from ..content.profiles import NaverProfile
from ..errors import AppError

BLOG_ADDRESS = "https://blog.naver.com/"
MAX_TOPIC = 200


def _address(blog_ref):
    """블로그 ID 면 네이버 블로그 주소로, 이미 주소(https)면 그대로 — 프로필이 받는 모양인지는 `NaverProfile` 이 엄격히 본다."""
    ref = str(blog_ref).strip()
    return ref if ref.lower().startswith("http") else BLOG_ADDRESS + ref


def _topic_text(words):
    """주요 주제 낱말들 → 쉼표로 이은 한 줄(프로필의 주제 칸 한도 안에서 낱말을 끊지 않고)."""
    kept, used = [], 0
    for word in words:
        extra = len(word) + (2 if kept else 0)
        if used + extra > MAX_TOPIC:
            break
        kept.append(word)
        used += extra
    return ", ".join(kept)


def from_channel(channel):
    """블로그 관리의 채널 프로필 한 슬롯 → 네이버 프로필. 네이버 슬롯이고 블로그 ID·주소가 등록돼 있고 프로필이 받아 주는 값일 때만이고, 아니면 None(오류를 내지 않는다)."""
    if getattr(channel, "key", None) not in NAVER_KEYS or not getattr(channel, "blog_ref", ""):
        return None
    try:
        return NaverProfile(channel.key, channel.display_name, _address(channel.blog_ref), topic=_topic_text(channel.main_topics), audience=channel.audience, tone=channel.tone,
                            default_tags=tuple(channel.main_topics))          # 복사 패키지는 태그가 하나는 있어야 해서 주요 주제 낱말을 기본 태그로 쓴다 — 우선 키워드·제외 키워드·선호 글 유형은 읽지 않는다(그 화면이 '저장만 해요' 라고 말한다)
    except AppError:
        return None


def _from_channel_file(ctx, key):
    """채널 프로필 파일(읽기만 — 파일도 폴더도 만들지 않는다)에서 그 블로그의 프로필을 만든다. 파일을 읽을 수 없으면 None."""
    from . import blog_profiles                                      # 늦게 — 이 함수가 필요할 때만 주제 엔진 부품을 가져온다
    try:
        snapshot = blog_profiles.read_snapshot(ctx)
    except (AppError, OSError):
        return None
    channel = next((item for item in snapshot.profiles if item.key == key), None)
    return None if channel is None else from_channel(channel)


def profile_for(ctx, key):
    """그 네이버 블로그(`naver_a`·`naver_b`)의 프로필 — 설정 파일이 먼저, 없으면 블로그 관리에 등록한 것에서. 둘 다 없으면 NAVER_PROFILE_MISSING, 설정 파일이 깨졌으면 SETTINGS_INVALID."""
    try:
        return ctx.settings.naver_profile(key)
    except AppError as error:
        if error.code != "NAVER_PROFILE_MISSING":
            raise
    found = _from_channel_file(ctx, key) if key in NAVER_KEYS else None
    if found is None:
        raise AppError("NAVER_PROFILE_MISSING", {"블로그": key})
    return found


def profile_keys(ctx):
    """프로필이 읽히는 네이버 블로그 열쇠들(`NAVER_KEYS` 순서). 설정 파일이 깨졌으면 SETTINGS_INVALID 가 그대로 난다."""
    found = []
    for key in NAVER_KEYS:
        try:
            profile_for(ctx, key)
        except AppError as error:
            if error.code == "NAVER_PROFILE_MISSING":
                continue
            raise
        found.append(key)
    return tuple(found)
