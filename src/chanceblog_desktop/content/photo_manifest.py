"""사진 Manifest(사진 정보 목록, 스키마 `chanceblog.photo-manifest/1`) — 글(초안) 하나에 붙는 사진들의 **구조화된 목록**과 그 규칙(사진 연동 초안 1단계, 결정 D-496·D-497).
순수 파이썬이다 — 파일·네트워크·시계·무작위·표준 출력을 쓰지 않는다(파일이 있는지 보고 JSON 파일을 읽고 쓰는 일은 `service/photo_manifest.py`). 같은 입력은 늘 같은 글자다.

운영자 결정(2026-11-16, 이슈 #206·#209·#212): 사진은 PC 밖으로 보내지 않고 AI·네트워크·사진 자동 분석이 없다. 앱은 **원본 사진을 복사·저장하지 않고** 파일 위치·순서·종류·사용자가 확인한 정보만 기억한다.
장면 설명은 사용자가 사진마다 적은 글이고, 앱은 사용자가 적지 않은 맛·가격·사실을 지어내지 않는다.

사진 한 장의 칸은 운영자가 정한 **열네 가지**뿐이다(`FIELDS`) — photo_id·local_path·display_order·photo_type·analysis_method·observed_objects·visible_text·setting·user_subject·user_note·
preferred_section·placement·confirmed_by_user·caption. 목록 파일에 그 밖의 칸(EXIF·촬영 위치·기기·썸네일 …)이 있으면 읽지 않고 거절한다 — 이 모듈은 이미지 파일을 열지도 않는다.

규칙(모두 fail closed — 의심스러우면 만들지 않고 고정 문장으로 거절한다):
  · **한도** — 한 글에 사진 최대 `MAX_PHOTOS`(30)장, 대상 `MAX_SUBJECT`(60)자·메모 `MAX_NOTE`(300)자·설명 글 `MAX_CAPTION`(100)자, 종류·장소 분위기 20자·들어갈 위치 60자, 분석 결과 항목 한 칸에 20개·한 개 200자.
    글칸은 한 줄로 정리하고(`clean_line`) 눈에 안 보이거나 빈칸처럼 보이는 글자·겹쳐 쌓인 결합 문자·HTML·`{{ }}` 같은 템플릿 표기·키·토큰 모양·결과를 약속하는 표현·주민등록번호나 카드 번호 모양은 거절한다(선택 입력 `DraftOptions` 와 같은 검사기).
  · **사진 번호** — `photo_id` 는 앱이 만든 `p001`…`p999` 이고 사용자가 준 글자가 아니다. 한 목록 안에서 다시 쓰지 않는다(`next_number` 가 늘기만 한다) — 지운 사진의 번호를 새 사진이 물려받아 본문 속 `{{사진 3}}` 이 엉뚱한
    사진을 가리키는 일이 없게. 본문에는 `{{사진 N}}`(N = 이 번호의 숫자)만 쓴다. 순서(`display_order`, 1부터 빈틈없이)를 바꾸거나 사진을 지워도 번호와 본문은 바뀌지 않는다 — 앱은 본문을 몰래 고치지 않고 어긋남만 알린다(`placeholder_report`).
  · **경로** — `local_path` 는 이 PC 의 **절대 경로**(`C:\\…`·`C:/…`, 윈도가 아니면 `/…` 도)이고 `service/own_posts.py` 의 경로 모양 규칙과 같다: 인터넷 주소 모양·네트워크 위치(`\\\\서버\\공유`)·와일드카드·제어 문자·`..`·윈도 장치
    이름(`CON.jpg`)·드라이브 문자 자리가 아닌 `:`(대체 데이터 스트림)·끝의 구분자는 거절하고 260자(윈도가 파일을 못 여는 길이)를 넘으면 거절한다. 확장자는 **`ui/core/imagerules.py` 의 지원 확장자**(JPG·JPEG·PNG·WebP)뿐이다 —
    사진 규칙(실제 형식 확인·EXIF 회전 자동 적용·원본 수정 금지·20MB·긴 변 12,000px 경고)은 새로 만들지 않고 그 파일을 쓴다. 같은 파일(경로의 대소문자·구분자 차이 무시)을 두 번 넣을 수 없다. 경로는 어떤 출력(초안 입력·오류·`repr`)에도 나오지 않는다.
  · **종류·위치** — 종류(`photo_type`)·장소 분위기(`setting`)는 사용자가 고르는 짧은 이름이다(목록은 사용자가 고칠 수 있어 이 모듈은 모양만 보고, 목록을 주면 그 안에서만 받는다). `placement` 는 `{kind, nth}` 이고 kind 는
    `auto`(생성기가 정함)·`top`(글 맨 앞)·`after_heading`(소제목 뒤)·`after_paragraph`(n번째 문단 뒤)·`between_sentences`(n번째 문장 뒤)다.
  · **분석 결과는 기본으로 저장하지 않는다** — `observed_objects`·`visible_text` 는 `{글, 확인 여부}` 항목의 목록이고 메모리에서만 쓴다(`to_dict` 의 기본은 빈 목록이고 분석 방법도 `manual` 로 쓴다 — 켜려면 `persist_analysis=True`). 나중의 로컬 분석 플러그인이 `set_analysis` 로
    **확인 전** 항목을 채우고, 사용자가 고치고(`edit_item`) 확인해야(`confirm_item`) 한다. 관찰한 대상에서 얼굴·관계·감정·신원을 짐작한 말(`inference_problem`)은 받지 않는다. 읽은 글자도 사용자가 확인하기 전에는 사실이 아니다.
  · **확정한 것만 초안으로** — `draft_inputs` 는 `confirmed_by_user` 가 참인 사진의, 확인한 항목만 `DraftPhoto` 로 뽑는다(순서대로). **경로·파일 이름·`photo_id` 문자열은 담지 않는다**(번호 N 만 — 자리표시자를 만들려면 필요하다).
    사진의 내용(경로·종류·대상·메모·위치·설명 글·분석 항목)을 고치면 확정이 풀린다(`update_photo`·`confirm_item` …) — 확정은 지금 저장된 값에 대한 것이다. 확정은 `set_confirmed` 로만 켠다.
  · **저장 모양** — JSON(UTF-8·BOM 없음, 키를 정렬·들여쓰기 2칸·끝에 줄바꿈 하나 — `service/context.write_json` 과 같은 글자). 읽을 때는 칸 이름·종류·한도를 모두 엄격하게 본다(모르는 칸·같은 키 두 번·`NaN`·너무 깊은 겹침·512KB 초과 거절).
오류는 기존 오류 체계의 `CONTENT_INVALID`(고정 문장 — 글·경로는 문장에도 세부에도 없다)·`STORE_VERSION_UNSUPPORTED`(더 새로운 판)이다.
알려 둔 한계: 낱말 목록(`inference_problem`)은 완전하지 않다 — 마지막 방어선은 사용자가 확인하는 단계다. 같은 파일을 하드 링크·다른 경로로 넣은 것은 이 모듈이 알아보지 못한다(`service/photo_manifest.py` 가 파일을 볼 때 알린다).
"""
from __future__ import annotations

import json
import ntpath
import os
import posixpath
import re
import unicodedata
from dataclasses import dataclass, field, replace

from ..errors import AppError
from . import draft_options as _options
from .candidates import _BLANK_LOOKALIKES, _STACKED_MARKS, forbidden_claim
from .profiles import clean_line, find_markup
from .saved_draft import is_draft_id

SCHEMA = "chanceblog.photo-manifest/1"
SCHEMA_PREFIX = "chanceblog.photo-manifest/"
FIELDS = ("photo_id", "local_path", "display_order", "photo_type", "analysis_method", "observed_objects", "visible_text", "setting", "user_subject", "user_note", "preferred_section", "placement",
          "confirmed_by_user", "caption")
ENVELOPE_KEYS = ("schema", "draft_id", "next_number", "photos")
MAX_PHOTOS = 30
MAX_NUMBER = 999
MAX_PATH_CHARS = 260
MAX_LABEL = 20
MAX_SECTION = 60
MAX_SUBJECT, MAX_NOTE, MAX_CAPTION = 60, 300, 100
MAX_OBSERVATIONS, MAX_OBSERVATION_CHARS = 20, 200
MAX_NTH = 50
MAX_TEXT_BYTES = 512 * 1024
DEFAULT_PHOTO_TYPES = ("간판", "건물 외관", "메뉴판", "인테리어", "대표 메뉴", "반찬", "음식", "지도 캡처", "기타")
DEFAULT_SETTINGS = ("실내", "실외", "객실", "야경")
DEFAULT_TYPE = "기타"
METHOD_MANUAL = "manual"
PLACEMENT_KINDS = ("auto", "top", "after_heading", "after_paragraph", "between_sentences")
NEEDS_NTH = frozenset({"after_paragraph", "between_sentences"})
OBJECTS, TEXTS = "observed_objects", "visible_text"
ANALYSIS_KINDS = (OBJECTS, TEXTS)
ADD_FIELDS = ("setting", "user_subject", "user_note", "preferred_section", "placement", "caption")      # `add_photo` 가 처음부터 받는 칸
EDIT_FIELDS = ("local_path", "photo_type") + ADD_FIELDS                                                      # `update_photo` 가 고칠 수 있는 칸(그 밖의 칸은 전용 함수로만)
DRAFT_KEYS = ("number", "display_order", "photo_type", "setting", "user_subject", "user_note", "preferred_section", "placement", "caption", "confirmed_objects", "confirmed_texts")

_PHOTO_ID = re.compile(r"p([0-9]{3})")
_METHOD = re.compile(r"manual|local:[a-z0-9][a-z0-9._-]{0,39}")
PLACEHOLDER = re.compile(r"\{\{사진 ([1-9][0-9]{0,2})\}\}")
_BRACES = re.compile(r"\{\{|\}\}")
_WIN_ABS = re.compile(r"[A-Za-z]:[\\/]")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]+:")
_DRIVE = re.compile(r"[A-Za-z]:")
_SEPARATORS = re.compile(r"[\\/]+")
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{name}{digit}" for name in ("COM", "LPT") for digit in "123456789¹²³"})      # `service/own_posts.py` 와 같은 표
_BAD_PATH_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})                                                                                    # 제어·서식(글자 방향 바꾸기 …)·짝 없는 대리·사용자 지정·줄·문단 구분

# 글칸 → (사용자에게 보일 이름, 최대 글자 수, 결과를 약속하는 표현을 막는가, 비워 둘 수 없는가)
_TEXT_RULES = {
    "photo_type": ("사진 종류", MAX_LABEL, False, True),
    "setting": ("장소 분위기", MAX_LABEL, False, False),
    "user_subject": ("사진의 대상", MAX_SUBJECT, True, False),
    "user_note": ("사진 메모", MAX_NOTE, True, False),
    "preferred_section": ("들어갈 위치", MAX_SECTION, False, False),
    "caption": ("사진 설명 글", MAX_CAPTION, True, False),
    "observation": ("분석 결과", MAX_OBSERVATION_CHARS, False, True),
}

# 거절 사유 — 사용자에게 보이는 고정 문장이다(글·경로·파일 이름은 어떤 문장에도 없다).
_P_FORM = "사진 파일 위치가 올바르지 않아요. 파일 선택 창에서 직접 골라 주세요"
_P_NETWORK = "인터넷 주소나 네트워크 위치의 사진은 쓰지 않아요. 이 PC 에 저장된 사진을 골라 주세요"
_P_LONG = f"사진 파일 위치가 너무 길어요({MAX_PATH_CHARS}자까지). 사진을 더 짧은 폴더로 옮긴 뒤 골라 주세요"
_P_SUFFIX = "지원하지 않는 형식이에요. JPG·PNG·WebP 사진만 쓸 수 있어요"
_P_RESERVED = "윈도에서 장치 이름으로 쓰이는 파일 이름은 쓰지 않아요. 파일 이름을 바꾼 뒤 골라 주세요"
_R_INFERENCE = "사진 속 사람의 얼굴·관계·감정·신원을 짐작한 말은 받지 않아요. 직접 보고 확인한 대상만 적어 주세요"
_R_PERSONAL = "주민등록번호나 카드 번호처럼 보이는 숫자는 받지 않아요"
_R_SECRET = "키·토큰처럼 보이는 글이 들어 있어요. 그 부분을 지운 뒤 다시 적어 주세요"
_R_FULL = f"사진은 한 글에 {MAX_PHOTOS}장까지만 넣을 수 있어요"
_R_NUMBERS = f"사진 번호를 모두 썼어요({MAX_NUMBER}번까지). 새 글에서 다시 시작해 주세요"
_R_DUPLICATE = "같은 사진을 이미 넣었어요"
_R_NO_PHOTO = "그 사진이 목록에 없어요"
_R_EDIT = "고칠 수 없는 칸이에요"
_R_FORM = "사진 정보의 모양이 올바르지 않아요"
_R_BIG = "사진 정보가 너무 커요"
_R_SHAPE = "사진 정보 파일을 읽을 수 없어요"
_R_ORDER = "사진 순서가 올바르지 않아요"
_R_FLAG = "참이나 거짓이어야 해요"
_R_KIND = "분석 결과의 종류가 올바르지 않아요"
_R_METHOD = "분석 방법의 이름이 올바르지 않아요"
_R_ID = "사진 번호가 올바르지 않아요"
_R_DRAFT_ID = "초안 번호가 올바르지 않아요"
_R_PLACEMENT = "사진 위치가 올바르지 않아요"
_R_ITEM = "고를 분석 결과가 목록에 없어요"
_R_TYPES = "사진 종류 목록에 없는 종류예요"

_INFERENCE_KO = ("얼굴", "표정", "인물", "사람", "남자", "여자", "남성", "여성", "소년", "소녀", "어린이", "아기", "노인", "청년", "손님", "직원", "종업원",
                 "가족", "부부", "연인", "커플", "친구", "동료", "엄마", "아빠", "어머니", "아버지", "부모", "형제", "자매", "아들", "남편", "아내", "애인",
                 "행복", "기쁨", "슬픔", "화난", "웃는", "웃음", "미소", "우는", "눈물", "즐거운", "외로운", "놀란", "우울", "신원", "본인", "누구", "유명인", "연예인", "정치인", "대통령", "이름")
_INFERENCE_GUARDED = ("아이(?![스디템폰패돌콘어])", "(?<![가-힣])딸(?![기꾹])")                  # 아이스·아이디·아이템·아이폰 … 과 딸기·딸꾹질은 사람을 가리키지 않는다
_INFERENCE_EN = ("face", "faces", "person", "people", "man", "men", "woman", "women", "boy", "girl", "child", "children", "kid", "kids", "baby", "couple", "family", "friend", "friends", "mother",
                 "father", "parent", "parents", "husband", "wife", "son", "daughter", "boyfriend", "girlfriend", "brother", "sister", "colleague", "customer", "customers", "staff", "waiter", "waitress",
                 "smile", "smiles", "smiling", "laugh", "laughing", "happy", "sad", "angry", "crying", "joyful", "lonely", "celebrity", "famous", "identity")
_INFERENCE = re.compile("|".join([*map(re.escape, _INFERENCE_KO), *_INFERENCE_GUARDED]) + r"|\b(?:" + "|".join(_INFERENCE_EN) + r")\b", re.IGNORECASE)
_RESIDENT = re.compile(r"(?<![0-9])([0-9]{2})([0-9]{2})([0-9]{2})[- ]?[1-8][0-9]{6}(?![0-9])")
_CARD = re.compile(r"(?<![0-9])(?:[0-9][ -]?){12,18}[0-9](?![0-9])")


def _invalid(reason, number=None):
    """기존 오류 체계(`CONTENT_INVALID`)의 고정 문장 오류 — 글·경로·파일 이름은 문장에도 세부에도 없다(사진 번호만 들 수 있다)."""
    head = "사진 정보" if number is None else f"사진 {number}"
    return AppError("CONTENT_INVALID", {"항목": f"{head} — {reason}"}, detail=reason)


# ---- 번호·자리표시자 -----------------------------------------------------------------------------------------------------------------------
def is_photo_id(value):
    """`p001`…`p999` 모양인가(`p000` 은 아니다)."""
    found = _PHOTO_ID.fullmatch(value) if isinstance(value, str) else None
    return found is not None and int(found.group(1)) >= 1


def photo_id_of(number):
    """사진 번호(1–999) → `p001` 꼴 번호. 범위 밖이면 `CONTENT_INVALID`."""
    if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= MAX_NUMBER:
        raise _invalid(_R_ID)
    return f"p{number:03d}"


def number_of(photo_id):
    """`p003` → 3(화면에 보이는 사진 번호 N — 본문의 `{{사진 N}}` 과 같다)."""
    if not is_photo_id(photo_id):
        raise _invalid(_R_ID)
    return int(photo_id[1:])


def placeholder(number):
    """본문에 넣는 자리표시자 `{{사진 N}}` — 사진 번호(숫자) 또는 `p003` 꼴 번호로 만든다. 사진 파일이 아니라 번호만 글에 들어간다(내보낼 때 앱이 사진으로 바꾼다)."""
    value = number_of(number) if isinstance(number, str) else number
    photo_id_of(value)                                                  # 번호가 1–999 인지 본다(아니면 `CONTENT_INVALID`)
    return f"{{{{사진 {value}}}}}"


def find_placeholders(text):
    """본문에서 `{{사진 N}}` 모양 정확히 하나씩 → `((N, 시작, 끝), …)`(글에 나온 순서). 공백이 다르거나 0·네 자리 번호인 비슷한 모양은 자리표시자로 치지 않는다."""
    return tuple((int(found.group(1)), found.start(), found.end()) for found in PLACEHOLDER.finditer(text)) if isinstance(text, str) else ()


def stray_braces(text):
    """`{{`·`}}` 중 정확한 자리표시자 `{{사진 N}}` 안에 있지 않은 것의 수 — 내보내기 전에 남아 있으면 안 되는 템플릿 표기다."""
    if not isinstance(text, str):
        return 0
    spans = [(start, end) for _number, start, end in find_placeholders(text)]
    return sum(1 for found in _BRACES.finditer(text) if not any(start <= found.start() < end for start, end in spans))


# ---- 경로 ---------------------------------------------------------------------------------------------------------------------------------
def accepted_extensions():
    """받는 사진 확장자(소문자) — `ui/core/imagerules.py` 의 지원 확장자 그대로(여기에 따로 적지 않는다). 늦게 가져온다(화면 층의 순수 규칙 파일이다)."""
    from ..ui.core import imagerules
    return tuple(imagerules.SUPPORTED_EXTENSIONS)


def path_problem(path, *, posix=None):
    """사진 파일 위치의 모양 검사 → 거절 사유(고정 문장) 또는 None. 파일을 만지지 않는다(어느 운영체제에서나 같은 결과 — `posix` 는 `/…` 로 시작하는 경로를 절대 경로로 볼지, 기본은 윈도가 아닐 때).
    `service/own_posts.py` 의 경로 모양 규칙과 같고(확장자만 사진 확장자), 사진 파일은 260자를 넘으면 거절한다."""
    if not isinstance(path, str) or not path.strip() or path != path.strip() or any(unicodedata.category(ch) in _BAD_PATH_CATEGORIES for ch in path):
        return _P_FORM
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return _P_FORM
    if len(path) > MAX_PATH_CHARS:
        return _P_LONG
    if path.replace("/", "\\").startswith("\\\\") or _SCHEME.match(path):
        return _P_NETWORK
    if "*" in path or "?" in path or (path[2:] if _DRIVE.match(path) else path).count(":") or path[-1] in "/\\":
        return _P_FORM
    posix = (os.name != "nt") if posix is None else posix
    if not (_WIN_ABS.match(path) or (posix and path.startswith("/"))) or ".." in _SEPARATORS.split(path):
        return _P_FORM
    name = _SEPARATORS.split(path)[-1]
    if ntpath.splitext(name)[1].lower() not in accepted_extensions():
        return _P_SUFFIX
    if name.split(".", 1)[0].rstrip(" ").upper() in _RESERVED:
        return _P_RESERVED
    return None


def path_key(path):
    """같은 파일인지 가리는 모양 — 윈도 경로(`C:\\…`)는 구분자·대소문자를 통일하고, 그 밖의 경로는 정리만 한다. 모양이 맞는 경로(`path_problem` 이 None)에만 쓴다."""
    if _WIN_ABS.match(path):
        return ntpath.normcase(ntpath.normpath(path))
    return posixpath.normpath(path)


# ---- 글칸 ---------------------------------------------------------------------------------------------------------------------------------
def inference_problem(text):
    """분석이 '관찰했다' 고 한 대상에서 얼굴·관계·감정·신원을 짐작한 말이 있으면 사유, 없으면 None(낱말 목록이라 완전하지 않다 — 마지막 방어선은 사용자의 확인이다)."""
    return _R_INFERENCE if isinstance(text, str) and _INFERENCE.search(text) else None


def _luhn(digits):
    total, flip = 0, False
    for ch in reversed(digits):
        number = int(ch)
        if flip:
            number = number * 2 - 9 if number * 2 > 9 else number * 2
        total, flip = total + number, not flip
    return total % 10 == 0


def personal_number_problem(text):
    """주민등록번호(생년월일 모양이 맞는 6+7자리)나 카드 번호(13–19자리, 검사 숫자가 맞는 것) 같은 숫자가 있으면 사유, 없으면 None."""
    for found in _RESIDENT.finditer(text):
        if 1 <= int(found.group(2)) <= 12 and 1 <= int(found.group(3)) <= 31:
            return _R_PERSONAL
    for found in _CARD.finditer(text):
        digits = re.sub("[^0-9]", "", found.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return _R_PERSONAL
    return None


def _has_secret(text):
    from ..security import scan
    return _options._looks_secret(text) or scan.has_secret(text)


def check_text(name, value):
    """글칸 하나(`name`: photo_type·setting·user_subject·user_note·preferred_section·caption·observation)의 검사 → `(정리한 글, None)` 또는 `(None, 사유)`. 예외를 내지 않는다 — 화면이 칸마다 바로 보여 주려고 쓴다.
    정리 = 한 줄로(제어·보이지 않는 글자를 지우고 공백을 접는다). 비워 둘 수 있는 칸의 빈 글은 `''`."""
    rule = _TEXT_RULES.get(name)
    if rule is None:
        return None, _R_EDIT
    label, high, claims, required = rule
    if not isinstance(value, str):
        return None, f"{label}: 글이어야 해요"
    text = clean_line(value)
    if not text:
        return (None, f"{label}: 비워 둘 수 없어요") if required else ("", None)
    if len(text) > high:
        return None, f"{label}: {high}자까지만 적을 수 있어요"
    if _BLANK_LOOKALIKES.search(text) or _options._RARE_INVISIBLES.search(text):
        return None, f"{label}: 눈에 보이지 않거나 빈칸처럼 보이는 글자가 들어 있어요"
    if _STACKED_MARKS.search(text):
        return None, f"{label}: 겹쳐 쌓였거나 홀로 붙은 결합 문자가 들어 있어요"
    markup = find_markup(text)
    if markup:
        return None, f"{label}: {markup}"
    if _has_secret(text):
        return None, f"{label}: {_R_SECRET}"
    personal = personal_number_problem(text)
    if personal:
        return None, f"{label}: {personal}"
    if claims:
        claim = forbidden_claim(text)
        if claim:
            return None, f"{label}: ‘{claim[0]}’ 같은 결과를 약속하는 표현은 쓸 수 없어요"
    return text, None


def _text(name, value, number=None):
    clean, reason = check_text(name, value)
    if reason is not None:
        raise _invalid(reason, number)
    return clean


def _flag(value, number=None):
    if type(value) is not bool:
        raise _invalid(_R_FLAG, number)
    return value


# ---- 값 ----------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Observation:
    """분석 결과 한 항목 — 글과 사용자의 확인 여부. 확인(`confirmed`)하기 전에는 사실이 아니고 초안에 가지 않는다. 글은 `repr` 에 나오지 않는다."""
    text: str = field(repr=False)
    confirmed: bool = False

    def __post_init__(self):
        object.__setattr__(self, "text", _text("observation", self.text))
        _flag(self.confirmed)

    def to_dict(self):
        return {"text": self.text, "confirmed": self.confirmed}


@dataclass(frozen=True)
class Placement:
    """사진이 들어갈 자리 — `kind`(`PLACEMENT_KINDS`)와 몇 번째(`nth` — 문단·문장 뒤일 때만 1 이상, 그 밖에는 0)."""
    kind: str = "auto"
    nth: int = 0

    def __post_init__(self):
        if not isinstance(self.kind, str) or self.kind not in PLACEMENT_KINDS or not isinstance(self.nth, int) or isinstance(self.nth, bool):
            raise _invalid(_R_PLACEMENT)
        if (self.kind in NEEDS_NTH and not 1 <= self.nth <= MAX_NTH) or (self.kind not in NEEDS_NTH and self.nth != 0):
            raise _invalid(_R_PLACEMENT)

    def to_dict(self):
        return {"kind": self.kind, "nth": self.nth}


def _placement(value):
    if isinstance(value, Placement):
        return value
    if isinstance(value, dict) and set(value) == {"kind", "nth"}:
        return Placement(value["kind"], value["nth"])
    raise _invalid(_R_PLACEMENT)


def _observation(value, number=None):
    if isinstance(value, Observation):
        return value
    if isinstance(value, dict) and set(value) == {"text", "confirmed"}:
        return Observation(value["text"], value["confirmed"])
    raise _invalid(_R_FORM, number)


def _observations(values, kind, number):
    if not isinstance(values, (list, tuple)) or len(values) > MAX_OBSERVATIONS:
        raise _invalid(_R_FORM if not isinstance(values, (list, tuple)) else f"분석 결과는 한 칸에 {MAX_OBSERVATIONS}개까지만 둘 수 있어요", number)
    items = tuple(_observation(value, number) for value in values)
    if kind == OBJECTS and any(inference_problem(item.text) for item in items):
        raise _invalid(_R_INFERENCE, number)
    return items


@dataclass(frozen=True)
class Photo:
    """사진 한 장 — 운영자가 정한 열네 칸(`FIELDS`). 불변이고 만들 때 모든 칸을 검사한다(틀리면 `CONTENT_INVALID`). 경로·글은 `repr` 에 나오지 않는다."""
    photo_id: str
    local_path: str = field(repr=False)
    display_order: int
    photo_type: str
    analysis_method: str = METHOD_MANUAL
    observed_objects: tuple = field(default=(), repr=False)
    visible_text: tuple = field(default=(), repr=False)
    setting: str = field(default="", repr=False)
    user_subject: str = field(default="", repr=False)
    user_note: str = field(default="", repr=False)
    preferred_section: str = field(default="", repr=False)
    placement: Placement = field(default_factory=Placement, repr=False)
    confirmed_by_user: bool = False
    caption: str = field(default="", repr=False)

    def __post_init__(self):
        def put(name, value):
            object.__setattr__(self, name, value)

        number = number_of(self.photo_id) if is_photo_id(self.photo_id) else None
        if number is None:
            raise _invalid(_R_ID)
        problem = path_problem(self.local_path)
        if problem is not None:
            raise _invalid(problem, number)
        if not isinstance(self.display_order, int) or isinstance(self.display_order, bool) or not 1 <= self.display_order <= MAX_PHOTOS:
            raise _invalid(_R_ORDER, number)
        if not isinstance(self.analysis_method, str) or _METHOD.fullmatch(self.analysis_method) is None:
            raise _invalid(_R_METHOD, number)
        for name in ("photo_type", "setting", "user_subject", "user_note", "preferred_section", "caption"):
            put(name, _text(name, getattr(self, name), number))
        put("observed_objects", _observations(self.observed_objects, OBJECTS, number))
        put("visible_text", _observations(self.visible_text, TEXTS, number))
        put("placement", _placement(self.placement))
        _flag(self.confirmed_by_user, number)

    @property
    def number(self):
        """화면에 보이는 사진 번호 N(`{{사진 N}}` 의 N)."""
        return number_of(self.photo_id)

    def to_dict(self, persist_analysis=False):
        """저장하는 모양 — 열네 칸. 분석 결과(`observed_objects`·`visible_text`)는 `persist_analysis` 가 아니면 빈 목록이고(기본으로 저장하지 않는다) 그때 분석 방법도 `manual` 로 쓴다 —
        남은 결과가 없는데 '분석했다' 는 이름만 파일에 남지 않게."""
        keep = bool(persist_analysis)
        return {"photo_id": self.photo_id, "local_path": self.local_path, "display_order": self.display_order, "photo_type": self.photo_type, "analysis_method": self.analysis_method if keep else METHOD_MANUAL,
                "observed_objects": [item.to_dict() for item in self.observed_objects] if keep else [], "visible_text": [item.to_dict() for item in self.visible_text] if keep else [],
                "setting": self.setting, "user_subject": self.user_subject, "user_note": self.user_note, "preferred_section": self.preferred_section, "placement": self.placement.to_dict(),
                "confirmed_by_user": self.confirmed_by_user, "caption": self.caption}


@dataclass(frozen=True)
class DraftPhoto:
    """초안에 보내는 사진 한 장의 **최소 정보** — 확정한 사진의 확인한 것뿐이다. `number` 는 화면에 보이는 사진 번호 N 이다(자리표시자 `{{사진 N}}` 을 만들려고 필요하다).
    경로·파일 이름·`photo_id` 문자열·분석 방법·확인 전 항목은 없다. 글은 `repr` 에 나오지 않는다."""
    number: int
    display_order: int
    photo_type: str
    setting: str = field(repr=False)
    user_subject: str = field(repr=False)
    user_note: str = field(repr=False)
    preferred_section: str = field(repr=False)
    placement: Placement = field(repr=False)
    caption: str = field(repr=False)
    confirmed_objects: tuple = field(repr=False)
    confirmed_texts: tuple = field(repr=False)

    def to_dict(self):
        return {"number": self.number, "display_order": self.display_order, "photo_type": self.photo_type, "setting": self.setting, "user_subject": self.user_subject, "user_note": self.user_note,
                "preferred_section": self.preferred_section, "placement": self.placement.to_dict(), "caption": self.caption, "confirmed_objects": list(self.confirmed_objects),
                "confirmed_texts": list(self.confirmed_texts)}

    def texts(self):
        """초안으로 가는 모든 글(검사용)."""
        return (self.photo_type, self.setting, self.user_subject, self.user_note, self.preferred_section, self.caption, *self.confirmed_objects, *self.confirmed_texts)


@dataclass(frozen=True)
class PlaceholderReport:
    """본문과 사진 목록을 견준 결과 — 번호만 담는다. `ok` 가 거짓이면 내보내기 전에 사용자가 고쳐야 한다."""
    found: tuple = ()           # 본문에 나온 사진 번호(나온 순서, 되풀이 포함)
    dangling: tuple = ()        # 목록에 없는 사진을 가리키는 번호
    unconfirmed: tuple = ()     # 확정하지 않은 사진을 가리키는 번호
    missing: tuple = ()         # 확정했는데 본문에 자리표시자가 없는 사진 번호
    repeated: tuple = ()        # 본문에 두 번 이상 나온 번호
    order_differs: bool = False  # 본문에 처음 나온 순서가 사진 목록 순서와 다르다
    stray: int = 0              # 정확한 자리표시자가 아닌 `{{`·`}}` 의 수

    @property
    def ok(self):
        return not (self.dangling or self.unconfirmed or self.missing or self.repeated or self.order_differs or self.stray)


def _unique(numbers):
    seen = []
    for number in numbers:
        if number not in seen:
            seen.append(number)
    return tuple(seen)


@dataclass(frozen=True)
class PhotoManifest:
    """글 하나의 사진 목록 — 사진들(`display_order` 1부터 빈틈없이)·다음에 줄 번호(`next_number`, 늘기만 한다)·이어진 초안 번호(저장 전 초안이면 `''`). 만들 때 모두 검사한다.
    `next_number` 를 0 으로 두면 가장 큰 번호의 다음으로 정한다."""
    photos: tuple = ()
    next_number: int = 0
    draft_id: str = ""

    def __post_init__(self):
        photos = tuple(self.photos) if isinstance(self.photos, (list, tuple)) else None
        if photos is None or len(photos) > MAX_PHOTOS or not all(isinstance(photo, Photo) for photo in photos):
            raise _invalid(_R_FULL if photos is not None and len(photos) > MAX_PHOTOS else _R_FORM)
        if [photo.display_order for photo in photos] != list(range(1, len(photos) + 1)):
            raise _invalid(_R_ORDER)
        ids = [photo.photo_id for photo in photos]
        if len(set(ids)) != len(ids) or len({path_key(photo.local_path) for photo in photos}) != len(photos):
            raise _invalid(_R_DUPLICATE)
        highest = max((photo.number for photo in photos), default=0)
        if type(self.next_number) is not int:
            raise _invalid(_R_ID)
        upcoming = highest + 1 if self.next_number == 0 else self.next_number
        if not highest < upcoming <= MAX_NUMBER + 1:
            raise _invalid(_R_ID)
        if not isinstance(self.draft_id, str) or (self.draft_id and not is_draft_id(self.draft_id)):
            raise _invalid(_R_DRAFT_ID)
        object.__setattr__(self, "photos", photos)
        object.__setattr__(self, "next_number", upcoming)

    def photo(self, photo_id):
        """번호(`p003`)로 사진 하나 — 없으면 `CONTENT_INVALID`."""
        for photo in self.photos:
            if photo.photo_id == photo_id:
                return photo
        raise _invalid(_R_NO_PHOTO)

    def by_number(self, number):
        """사진 번호 N 의 사진 — 없으면 None."""
        return next((photo for photo in self.photos if photo.number == number), None)

    def to_dict(self, persist_analysis=False):
        return {"schema": SCHEMA, "draft_id": self.draft_id, "next_number": self.next_number, "photos": [photo.to_dict(persist_analysis) for photo in self.photos]}

    def to_text(self, persist_analysis=False):
        """저장하는 글 — `service/context.write_json` 이 쓰는 것과 같은 글자(키 정렬·들여쓰기 2칸·UTF-8·끝 줄바꿈 하나, BOM 없음)."""
        return json.dumps(self.to_dict(persist_analysis), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data):
        """저장한 모양을 엄격하게 읽는다 — 칸 이름이 정확히 같고 종류·한도가 모두 맞아야 한다(모르는 칸·`True` 를 숫자로 받기 …은 거절). 더 새로운 판은 `STORE_VERSION_UNSUPPORTED`."""
        if not isinstance(data, dict) or set(data) != set(ENVELOPE_KEYS):
            raise _invalid(_R_SHAPE)
        schema = data["schema"]
        if schema != SCHEMA:
            if isinstance(schema, str) and schema.startswith(SCHEMA_PREFIX) and re.fullmatch("[0-9]{1,6}", schema[len(SCHEMA_PREFIX):]) and int(schema[len(SCHEMA_PREFIX):]) > 1:
                raise AppError("STORE_VERSION_UNSUPPORTED", {"파일": "사진 정보"}, detail="사진 정보 판이 더 새롭다")
            raise _invalid(_R_SHAPE)
        if not isinstance(data["photos"], list) or type(data["next_number"]) is not int or data["next_number"] < 1:
            raise _invalid(_R_SHAPE)
        photos = tuple(_photo_from_dict(raw) for raw in data["photos"])
        return cls(photos, data["next_number"], data["draft_id"])

    @classmethod
    def from_text(cls, text):
        """저장한 글 → 목록. 512KB 가 넘거나 JSON 이 아니거나(BOM·같은 키 두 번·`NaN`·너무 깊은 겹침 포함) 모양이 틀리면 `CONTENT_INVALID`."""
        if not isinstance(text, str):
            raise _invalid(_R_SHAPE)
        if len(text) > MAX_TEXT_BYTES or len(text.encode("utf-8", "surrogatepass")) > MAX_TEXT_BYTES:
            raise _invalid(_R_BIG)
        try:
            data = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
        except (ValueError, RecursionError):
            raise _invalid(_R_SHAPE) from None
        return cls.from_dict(data)


class _Duplicate(ValueError):
    """JSON 객체에 같은 키가 두 번 있다."""


def _no_duplicates(pairs):
    found = {}
    for name, value in pairs:
        if name in found:
            raise _Duplicate()
        found[name] = value
    return found


def _no_constant(_name):
    raise ValueError("NaN·Infinity 는 받지 않는다")


def _photo_from_dict(raw):
    if not isinstance(raw, dict) or set(raw) != set(FIELDS):
        raise _invalid(_R_SHAPE)
    if type(raw["display_order"]) is not int or not isinstance(raw["photo_id"], str):
        raise _invalid(_R_SHAPE)
    return Photo(raw["photo_id"], raw["local_path"], raw["display_order"], raw["photo_type"], raw["analysis_method"], tuple(_listed(raw["observed_objects"])), tuple(_listed(raw["visible_text"])),
                 raw["setting"], raw["user_subject"], raw["user_note"], raw["preferred_section"], _placement(raw["placement"]), raw["confirmed_by_user"], raw["caption"])


def _listed(values):
    if not isinstance(values, list):
        raise _invalid(_R_SHAPE)
    return values


# ---- 목록 만들기·바꾸기(모두 새 목록을 돌려준다 — 원래 것은 그대로) -----------------------------------------------------------------------------
def empty_manifest(draft_id=""):
    """사진이 없는 목록."""
    return PhotoManifest((), 0, draft_id)


def _renumber(photos):
    return tuple(replace(photo, display_order=order) for order, photo in enumerate(photos, start=1))


def _swap(manifest, photo_id, new):
    return replace(manifest, photos=tuple(new if photo.photo_id == photo_id else photo for photo in manifest.photos))


def add_photo(manifest, local_path, /, *, photo_type=DEFAULT_TYPE, photo_types=None, **fields):
    """사진 한 장을 맨 뒤에 더한다 → `(새 목록, 새 사진 번호)`. 30장이 차 있거나 번호를 다 썼거나 경로가 틀렸거나 같은 사진이 이미 있으면 거절한다. 처음부터 줄 수 있는 칸은 `ADD_FIELDS` 뿐이고
    확정(`confirmed_by_user`)·분석 결과는 줄 수 없다. `photo_types` 를 주면 종류가 그 목록 안에 있어야 한다."""
    if not isinstance(manifest, PhotoManifest) or set(fields) - set(ADD_FIELDS):
        raise _invalid(_R_EDIT)
    if len(manifest.photos) >= MAX_PHOTOS:
        raise _invalid(_R_FULL)
    if manifest.next_number > MAX_NUMBER:
        raise _invalid(_R_NUMBERS)
    problem = path_problem(local_path)
    if problem is not None:
        raise _invalid(problem)
    if path_key(local_path) in {path_key(photo.local_path) for photo in manifest.photos}:
        raise _invalid(_R_DUPLICATE)
    photo = Photo(photo_id_of(manifest.next_number), local_path, len(manifest.photos) + 1, photo_type, **fields)
    _require_type(photo, photo_types)
    return replace(manifest, photos=(*manifest.photos, photo), next_number=manifest.next_number + 1), photo.photo_id


def remove_photo(manifest, photo_id):
    """사진 한 장을 지운다 — 남은 사진의 순서를 1부터 다시 매기고(번호는 그대로) 지운 번호는 다시 쓰지 않는다."""
    manifest.photo(photo_id)
    return replace(manifest, photos=_renumber(tuple(photo for photo in manifest.photos if photo.photo_id != photo_id)))


def move_photo(manifest, photo_id, to_order):
    """사진 한 장을 `to_order` 번째(1부터)로 옮긴다 — 나머지는 차례대로 밀린다."""
    photo = manifest.photo(photo_id)
    if not isinstance(to_order, int) or isinstance(to_order, bool) or not 1 <= to_order <= len(manifest.photos):
        raise _invalid(_R_ORDER)
    rest = [other for other in manifest.photos if other.photo_id != photo_id]
    rest.insert(to_order - 1, photo)
    return replace(manifest, photos=_renumber(rest))


def reorder(manifest, photo_ids):
    """사진 순서를 `photo_ids`(지금 있는 사진 번호를 모두, 한 번씩) 순서로 바꾼다."""
    if (not isinstance(photo_ids, (list, tuple)) or not all(isinstance(photo_id, str) for photo_id in photo_ids) or len(set(photo_ids)) != len(photo_ids)
            or sorted(photo_ids) != sorted(photo.photo_id for photo in manifest.photos)):
        raise _invalid(_R_ORDER)
    by_id = {photo.photo_id: photo for photo in manifest.photos}
    return replace(manifest, photos=_renumber([by_id[photo_id] for photo_id in photo_ids]))


def update_photo(manifest, photo_id, /, *, photo_types=None, **changes):
    """사진 한 장의 내용(`EDIT_FIELDS`)을 고친다. **내용이 실제로 바뀌면 확정이 풀린다**(확정은 지금 저장된 값에 대한 것이다). 파일 위치(`local_path`)를 바꾸면 다른 사진이므로 분석 결과도 비운다.
    확정(`confirmed_by_user`)·순서·번호·분석 결과는 여기서 고칠 수 없다(`set_confirmed`·`move_photo`·`set_analysis` …). 바뀐 것이 없으면 그대로 돌려준다."""
    if set(changes) - set(EDIT_FIELDS):
        raise _invalid(_R_EDIT)
    old = manifest.photo(photo_id)
    if "local_path" in changes:
        problem = path_problem(changes["local_path"])
        if problem is not None:
            raise _invalid(problem, old.number)
        if path_key(changes["local_path"]) in {path_key(photo.local_path) for photo in manifest.photos if photo.photo_id != photo_id}:
            raise _invalid(_R_DUPLICATE, old.number)
    new = replace(old, **changes)
    _require_type(new, photo_types)
    if new == old:
        return manifest
    if new.local_path != old.local_path:
        new = replace(new, analysis_method=METHOD_MANUAL, observed_objects=(), visible_text=())
    return _swap(manifest, photo_id, replace(new, confirmed_by_user=False))


def _require_type(photo, photo_types):
    if photo_types is not None and photo.photo_type not in tuple(photo_types):
        raise _invalid(_R_TYPES, photo.number)


def set_confirmed(manifest, photo_id, confirmed):
    """사진 한 장의 확정을 켜고 끈다(사용자가 이 사진의 정보를 보고 초안에 보내도 된다고 한 것). 확정은 이 함수로만 켠다."""
    old = manifest.photo(photo_id)
    return _swap(manifest, photo_id, replace(old, confirmed_by_user=_flag(confirmed, old.number)))


def _kind(kind):
    if kind not in ANALYSIS_KINDS:
        raise _invalid(_R_KIND)
    return kind


def set_analysis(manifest, photo_id, *, method, objects=(), texts=()):
    """(나중의 로컬 분석 플러그인이 쓴다) 분석 결과를 **확인 전** 항목으로 채운다 → `(새 목록, 거른 항목 수)`. 글이 아니거나 모양·한도·비밀·개인 번호 검사에 걸린 항목, 관찰한 대상에서 얼굴·관계·감정·신원을 짐작한 말은 버리고,
    한 칸에 20개가 넘는 것도 버린다. 분석 방법 이름은 `local:이름` 이어야 하고, 이전 결과는 모두 대체되며 확정은 풀린다. 플러그인의 출력은 믿지 않는다 — 여기서 다시 검사한다."""
    if not isinstance(method, str) or _METHOD.fullmatch(method) is None or method == METHOD_MANUAL:
        raise _invalid(_R_METHOD)
    old = manifest.photo(photo_id)
    dropped = 0
    kept = {}
    for kind, raw in ((OBJECTS, objects), (TEXTS, texts)):
        items = []
        for value in (raw if isinstance(raw, (list, tuple)) else ()):
            clean, reason = check_text("observation", value)
            if reason is not None or (kind == OBJECTS and inference_problem(clean)) or len(items) >= MAX_OBSERVATIONS:
                dropped += 1
                continue
            items.append(Observation(clean, False))
        dropped += 0 if isinstance(raw, (list, tuple)) else 1
        kept[kind] = tuple(items)
    return _swap(manifest, photo_id, replace(old, analysis_method=method, observed_objects=kept[OBJECTS], visible_text=kept[TEXTS], confirmed_by_user=False)), dropped


def _with_item(manifest, photo_id, kind, index, build):
    old = manifest.photo(photo_id)
    items = list(getattr(old, _kind(kind)))
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(items):
        raise _invalid(_R_ITEM, old.number)
    changed = build(items[index])
    if changed == items[index]:
        return manifest
    items[index] = changed
    return _swap(manifest, photo_id, replace(old, **{kind: tuple(items)}, confirmed_by_user=False))


def confirm_item(manifest, photo_id, kind, index, confirmed=True):
    """분석 결과 항목 하나를 확인했다고 표시한다(또는 푼다). 항목이 바뀌면 사진의 확정이 풀린다."""
    _flag(confirmed)
    return _with_item(manifest, photo_id, kind, index, lambda item: Observation(item.text, confirmed))


def edit_item(manifest, photo_id, kind, index, text):
    """사용자가 분석 결과 항목의 글을 고친다 — 고친 항목은 다시 **확인 전**이 된다(확인은 `confirm_item`). 새 글도 같은 검사를 거친다(관찰한 대상이면 짐작한 말 거절 포함)."""
    return _with_item(manifest, photo_id, kind, index, lambda item: Observation(text, False))


# ---- 초안으로 보내는 정보 · 본문과 견주기 ------------------------------------------------------------------------------------------------------
def draft_inputs(manifest):
    """초안에 보낼 정보 → `(DraftPhoto, …)`(사진 순서대로). **확정한 사진만, 그 사진의 확인한 항목만** 담고 경로·파일 이름·`photo_id` 문자열은 담지 않는다. 같은 글의 항목은 하나만 남긴다.
    마지막 관문 — 내보내는 글에 키·토큰 모양이 있으면 `CONTENT_INVALID` 로 멈춘다(fail closed)."""
    if not isinstance(manifest, PhotoManifest):
        raise _invalid(_R_FORM)
    sent = []
    for photo in manifest.photos:
        if photo.confirmed_by_user is not True:
            continue
        objects = _unique(item.text for item in photo.observed_objects if item.confirmed is True)
        texts = _unique(item.text for item in photo.visible_text if item.confirmed is True)
        sent.append(DraftPhoto(photo.number, photo.display_order, photo.photo_type, photo.setting, photo.user_subject, photo.user_note, photo.preferred_section, photo.placement, photo.caption,
                               objects, texts))
    for item in sent:
        if any(_has_secret(text) for text in item.texts() if text):
            raise _invalid(_R_SECRET, item.number)
    return tuple(sent)


def placeholder_report(manifest, text):
    """본문(`text`)의 자리표시자와 사진 목록을 견준다 — 내보내기 전에 어긋남을 알리려는 것이다(본문은 고치지 않는다)."""
    found = tuple(number for number, _start, _end in find_placeholders(text))
    known = {photo.number: photo for photo in manifest.photos}
    appearing = _unique(found)
    sent = [photo.number for photo in manifest.photos if photo.confirmed_by_user]
    expected = [number for number in sent if number in appearing]
    actual = [number for number in appearing if number in sent]
    return PlaceholderReport(found, tuple(number for number in appearing if number not in known), tuple(number for number in appearing if number in known and not known[number].confirmed_by_user),
                             tuple(number for number in sent if number not in appearing), tuple(number for number in appearing if found.count(number) > 1), actual != expected, stray_braces(text))


__all__ = ["ADD_FIELDS", "ANALYSIS_KINDS", "DEFAULT_PHOTO_TYPES", "DEFAULT_SETTINGS", "DRAFT_KEYS", "DraftPhoto", "EDIT_FIELDS", "ENVELOPE_KEYS", "FIELDS", "MAX_PHOTOS", "Observation", "PLACEMENT_KINDS",
           "PLACEHOLDER", "Photo", "PhotoManifest", "Placement", "PlaceholderReport", "SCHEMA", "accepted_extensions", "add_photo", "check_text", "confirm_item", "draft_inputs", "edit_item", "empty_manifest",
           "find_placeholders", "inference_problem", "is_photo_id", "move_photo", "number_of", "path_key", "path_problem", "personal_number_problem", "photo_id_of", "placeholder", "placeholder_report",
           "remove_photo", "reorder", "set_analysis", "set_confirmed", "stray_braces", "update_photo"]
