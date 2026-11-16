"""'사진 정리' 화면(사진 연동 초안 2단계, 결정 D-499)의 순수 규칙 — 목록(종류·장소 분위기·들어갈 곳·자리)·종류별 예시와 기본 들어갈 곳·글자 수 표시·미리보기를 만들지 말아야 하는 큰 PNG 판정·파일 상태 배지.
PySide6·파일·서비스를 모른다(그래서 CI 에서 시험한다). 사진 규칙(JPG·PNG·WebP 만·실제 형식·20MB·긴 변 경고)은 새로 만들지 않고 `imagerules.py`·`content/photo_manifest.py` 의 것을 그대로 쓴다 — 이 파일은 화면이 보이는 말과 선택 목록만 정한다.

운영자 확인 023(이슈 #219, 2026-11-16 '추천대로 전부 진행')으로 정한 값:
  · 사진 종류 기본 9종(`pm.DEFAULT_PHOTO_TYPES`)과 장소 분위기 기본 6종(실내·실외·테라스·주차장·객실·야경 — `pm.DEFAULT_SETTINGS`)은 화면 안에서 더하고 지울 수 있다(앱을 닫으면 처음 목록으로 돌아간다 — 새 설정 칸을 만들지 않았다).
  · 종류별 기본 '들어갈 곳': 간판·건물 외관 → 도입, 메뉴판·대표 메뉴·음식·반찬 → 내용 소제목, 인테리어 → 분위기 소제목, 지도 캡처·기타 → 자동. 사용자가 고른 값은 바꾸지 않는다.
  · **PNG 만** 가로×세로가 1억 화소를 넘으면 미리보기(썸네일)를 만들지 않고 '너무 커서 미리보기를 못 만들어요' 로 알린다(사진은 그대로 쓸 수 있다). JPG·WebP 는 영향이 없다 — 이미지 읽기 도구가 **헤더에서 읽은 크기**로 판정하고 본문을 풀기 전에 막는다.
"""
from __future__ import annotations

import re

from ...content import photo_manifest as pm
from . import imagerules as R
from .text import T, display_text

TYPES = tuple(pm.DEFAULT_PHOTO_TYPES)
SETTINGS = tuple(pm.DEFAULT_SETTINGS)
MAX_LIST_ITEMS = 20                                      # 종류·장소 분위기 목록 하나에 둘 수 있는 이름의 수
PROTECTED_TYPE = pm.DEFAULT_TYPE                          # 지울 수 없는 종류(사진을 처음 넣을 때의 종류)
PNG_PIXEL_LIMIT = 100_000_000                            # PNG 의 가로×세로가 이 값을 넘으면 미리보기를 만들지 않는다(결정 16)
THUMB_SIDE = 96                                          # 한 줄의 미리보기 한 변(px — 긴 변을 이만큼으로 줄여 그린다)
FIELD_LIMITS = {"user_subject": pm.MAX_SUBJECT, "user_note": pm.MAX_NOTE, "caption": pm.MAX_CAPTION}
TEXT_FIELDS = tuple(FIELD_LIMITS)

# '들어갈 곳' — 빈 글은 자동(앱이 정한다). 나머지는 `preferred_section`(60자 글)에 그대로 적히고 3단계가 소제목 글·별칭으로 읽는다.
SECTION_AUTO = ""
SECTION_CHOICES = (SECTION_AUTO, "도입", "내용 소제목", "분위기 소제목", "마무리")
SECTION_TEXT_KEY = {SECTION_AUTO: "pho_section_auto", "도입": "pho_section_intro", "내용 소제목": "pho_section_content", "분위기 소제목": "pho_section_mood", "마무리": "pho_section_closing"}
DEFAULT_SECTION_BY_TYPE = {"간판": "도입", "건물 외관": "도입", "메뉴판": "내용 소제목", "대표 메뉴": "내용 소제목", "음식": "내용 소제목", "반찬": "내용 소제목", "인테리어": "분위기 소제목", "지도 캡처": SECTION_AUTO, "기타": SECTION_AUTO}
# '자리' — 사진이 들어갈 자리(`placement.kind`)와 몇 번째(문단·문장 뒤일 때만)
PLACEMENT_TEXT_KEY = {"auto": "pho_place_auto", "top": "pho_place_top", "after_heading": "pho_place_after_heading", "after_paragraph": "pho_place_after_paragraph", "between_sentences": "pho_place_between_sentences"}
PLACEMENT_KINDS = tuple(PLACEMENT_TEXT_KEY)
# 종류별 '이 사진은 무엇인가요?' 예시(운영자 예시 문장을 그대로 쓰고, 나머지는 같은 모양으로 새로 썼다 — 사실·맛·가격을 말하지 않는다). 모르는(내가 더한) 종류는 `EXAMPLE_DEFAULT`.
EXAMPLES = {"간판": "매장 입구 간판과 주차장 전경", "건물 외관": "골목에서 본 가게 건물", "메뉴판": "점심 메뉴판", "인테리어": "창가 좌석 쪽 모습", "대표 메뉴": "메인 메뉴 한우 불고기 전골", "반찬": "반찬 5개",
            "음식": "주문한 음식 한 상", "지도 캡처": "가게 위치가 보이는 지도 화면", "기타": "이 사진에 대해 한마디"}
EXAMPLE_DEFAULT = "이 사진에서 보이는 것"
NOTE_EXAMPLE_KEY = "pho_note_example"


def example_for(type_label):
    """종류에 맞는 '이 사진은 무엇인가요?' 예시(칸 안 흐린 글) — 종류가 바뀌면 같이 바뀐다. 모르는 종류는 일반 예시."""
    return EXAMPLES.get(type_label, EXAMPLE_DEFAULT)


def default_section(type_label):
    """종류의 기본 '들어갈 곳' — 모르는(사용자가 더한) 종류는 자동."""
    return DEFAULT_SECTION_BY_TYPE.get(type_label, SECTION_AUTO)


def section_choices(current):
    """'들어갈 곳' 선택 목록 — 고정 다섯 가지에, 지금 값이 그 밖의 글이면(나중 단계가 적은 소제목 글 등) 그 글을 하나 더해 조용히 지우지 않는다. [(값, 보이는 글), …]"""
    items = [(value, T[SECTION_TEXT_KEY[value]]) for value in SECTION_CHOICES]
    if current and current not in SECTION_CHOICES:
        items.append((current, display_text(current, 30)))
    return items


def placement_choices():
    """'자리' 선택 목록 — [(kind, 보이는 글), …]."""
    return [(kind, T[PLACEMENT_TEXT_KEY[kind]]) for kind in PLACEMENT_KINDS]


def needs_nth(kind):
    """그 자리가 '몇 번째' 를 받는가(문단 뒤·문장 사이)."""
    return kind in pm.NEEDS_NTH


def count_text(length, limit):
    """글자 수 표시 — `12/60`."""
    return T["pho_count_text"].format(n=length, limit=limit)


def over_limit(length, limit):
    return length > limit


def over_text(length, limit):
    """한도를 넘었을 때의 안내(색만이 아니라 글로도) — 빈 글이면 넘지 않은 것이다."""
    return T["pho_over"].format(limit=limit, n=length) if length > limit else ""


def preview_blocked(fmt, width, height):
    """미리보기를 만들면 안 되는 사진인가 — **PNG 이고** 가로×세로가 1억 화소를 넘을 때만 참이다(JPG·WebP·크기를 모르는 것은 거짓). 헤더에서 읽은 크기로 판정하므로 본문을 풀기 전에 부른다."""
    try:
        return str(fmt).lower() == "png" and int(width) * int(height) > PNG_PIXEL_LIMIT
    except (TypeError, ValueError):
        return False


_NAME_SPLIT = re.compile(r"[\\/]+")


def short_name(path, limit=40):
    """목록에 보이는 파일 이름(폴더 없이 이름만, 비밀 모양을 가린 뒤 줄인 한 줄) — 경로는 화면에도 보이지 않는다."""
    parts = _NAME_SPLIT.split(path) if isinstance(path, str) else [""]
    return display_text(parts[-1] if parts and parts[-1] else "", limit)


# ---- 파일 상태 ------------------------------------------------------------------------------------------------------------------------
STATE_OK, STATE_MISSING, STATE_LINK, STATE_NOT_FILE, STATE_CLOUD = "ok", "missing", "link", "not_file", "cloud"
STATE_UNKNOWN = "unknown"
BADGE_KEY = {R.OK: "pho_file_ok", STATE_MISSING: "pho_file_missing", STATE_LINK: "pho_file_link", STATE_CLOUD: "pho_file_cloud", R.TOO_BIG: "pho_file_toobig", R.UNSUPPORTED: "pho_file_unsupported",
             R.NOT_IMAGE: "pho_file_notimage", STATE_NOT_FILE: "pho_file_notfile", R.UNREADABLE: "pho_file_unreadable", STATE_UNKNOWN: "pho_file_unknown"}
RELINKABLE = frozenset({STATE_MISSING, STATE_LINK, STATE_NOT_FILE, R.UNSUPPORTED, R.NOT_IMAGE, R.UNREADABLE})      # '다시 찾기' 를 보이는 상태(파일을 바꿔 연결하면 풀릴 수 있는 것)
TONE = {R.OK: "ok", STATE_UNKNOWN: "muted"}                                                                         # 그 밖의 상태는 모두 'warn'


def badge(state, width=0, height=0):
    """파일 상태 → 배지 글. 크기를 알면 `파일 있음 · 4000×3000`. 상태는 색만이 아니라 늘 글이다."""
    if state == R.OK and width and height:
        return T["pho_file_ok_size"].format(w=width, h=height)
    return T[BADGE_KEY.get(state, "pho_file_unknown")]


def tone_of(state):
    return TONE.get(state, "warn")
