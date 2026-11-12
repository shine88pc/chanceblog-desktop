"""초안 작성 화면의 순수 규칙 — 확인 권장 줄 가르기·복사 전 관문·고친 양·키 모양·네이버 주소·선택 입력 모으기. PySide6 도 파일도 서비스도 모른다.

가장 큰 위험은 **지어낸 사실이나 위험한 표현이 든 글이 확인 없이 복사되는 것**이다. 그래서 규칙을 작게 쪼개 시험이 하나씩 못박는다:
  · `split_checks` — 서비스의 확인 권장은 줄마다 표지가 없다. **알려진 고정 글 여섯 가지와 소제목 수 어긋남 줄만 '모든 글 공통'(접힘)** 이고 나머지(모르는 줄 포함)는 모두 '이 글에만 해당'(펼침)이다 — 틀려도 위험한 줄이 접히지 않는 쪽으로 틀린다.
  · `inspect_text` — 편집기 글을 `check/claims`(지어낸 경험·사실 점검)와 키·토큰 모양 검사로 훑고, 생성한 글에서 얼마나 고쳤는지(고친 글자 수 — 문단 단위)를 센다. 건강 판정(`HealthReview`)은 부른 쪽이 넣어 준다.
  · `secret_spots`·`secret_places`·`has_secret` — 키·토큰 모양을 찾고 **어디가 걸렸는지** 앞부분만 짚는다. 주소·파일 이름 모양은 긴 영숫자 덩어리 검사에서 빼고 **알려진 키 모양만** 막는다(서비스의 `참고 URL` 칸과 같은 취지 — 정상 주소가 키 모양으로 오탐되어 복사가 모두 잠기는 일을 막는다).
  · `health_units` — 건강 판정(`topics.safety`)을 거는 글 조각(문장 단위). 판정은 `drafts.review_health` 가 한다(이 파일은 `topics` 를 모른다).
  · `Gate`·`gate_for` — 복사 전 관문: 키 모양이나 건강 효과 단정(판정 단계 C)이면 **막고**, 이 글에만 해당하는 확인 권장·분야 못 읽음·점검 걸림·거의 안 고침이 있으면 **확인창**을 띄운다(이미 확인한 것은 다시 묻지 않고 새로 생긴 것만 다시 묻는다).
  · `naver_write_url` — `네이버 글쓰기 열기` 가 여는 주소: 프로필의 블로그 주소가 `https://blog.naver.com/<아이디>` 모양일 때만 그 블로그의 글쓰기 주소, 아니면 빈 글(단추를 끈다).
무거운 모듈(`check/claims`·`security`)은 쓰는 함수 안에서 늦게 가져온다(화면이 열릴 때 정규식을 한꺼번에 만들지 않게).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from .text import T, display_text

GENERIC_DOMAIN = "generic"                                   # `content.body_bank.DOMAINS` 의 마지막 — 후보의 낱말에서 분야를 못 읽었을 때(시험이 같은 값인지 견준다)
UNCHANGED_BELOW = 120                                         # 고친 글자 수가 이보다 적으면 '거의 고치지 않은 초안'(D-285) — 한 문단 남짓
GATED = ("title", "body", "all")                              # 글 본문이 나가는 복사 — 복사 전 관문(확인창)을 거친다
SOFT_UNCHANGED = ("body", "all")                              # '거의 고치지 않았어요' 안내가 붙는 복사(제목만 복사는 본문이 아니다)
SMALL_COPIES = ("keywords", "tags", "summary")                # 오른쪽 칸의 작은 복사 — 키 모양 검사만 한다
COPY_ITEMS = (*GATED, *SMALL_COPIES)
EDITOR_MIN_HEIGHT = 440                                       # 본문 편집기의 최소 높이(C-Type §15.4: 420~480)
SIDE_BY_SIDE_FROM = 1280                                      # 창 논리 폭이 이만큼 이상이면 오른쪽 칸(키워드·태그·확인 권장 …)을 편집기 옆에 두고(왼쪽 약 68%·오른쪽 약 32%), 미만이면 편집기 아래로 내린다(D-283)
PREVIEW = 40                                                  # 점검에 걸린 문장을 화면에 보이는 글자 수(앞부분)
MAX_CLAIM_LINES = 8                                           # 점검 결과에 보이는 문장 수(나머지는 개수로만)
BLOG_NAMES = ("naver_a", "naver_b")
# 선택 입력 칸 — (이름, 한 줄인가). 여러 줄 칸은 줄마다 한 항목이다. 칸 이름(라벨)은 서비스의 `DraftOptions` 이름 그대로 쓴다(`T["drf_opt_<이름>"]`, 시험이 같은지 견준다).
OPTION_FIELDS = (("message", True), ("experience", True), ("opinion", True), ("conclusion", True), ("audience", True), ("must_include", False), ("price_date", False), ("urls", False))
LIST_FIELDS = tuple(name for name, single in OPTION_FIELDS if not single)

def side_by_side(width):
    """초안 화면의 오른쪽 칸을 편집기 옆에 둘 만큼 창이 넓은가(창의 논리 폭 — 윈도 배율을 나눈 값). 1366×768 의 125%(논리 약 1093)·150%(약 910)와 최소 창 900 은 아래로 내린다."""
    return isinstance(width, (int, float)) and not isinstance(width, bool) and width >= SIDE_BY_SIDE_FROM


# ---- 확인 권장 줄 가르기 --------------------------------------------------------------------------------------------------------------------
# 서비스(`content/draft_body.py`·`draft_plan.py`)가 거의 모든 초안에 붙이는 고정 글의 앞부분 — 소스의 글자와 같음을 시험이 견준다. 이 목록에 없는 줄은 모두 '이 글에만 해당' 이다.
COMMON_PREFIXES = (
    "본문은 입력하신 내용과 일반적인 확인 순서만으로 만든 기본 글입니다",
    "직접 사용하거나 방문하거나 구매한 경험은 본문에 넣지 않았습니다",
    "가격·날짜·수치는 본문에 넣지 않았습니다",
    "참고 자료를 입력하지 않았습니다",
    "추천 카테고리를 정하지 못했습니다",
    "이 네이버 블로그의 프로필이 아직 없어 공통 기본값으로 만들었습니다",
)
PROFILE_PREFIX = COMMON_PREFIXES[-1]
_HEADING_COUNT = re.compile("^소제목이 [0-9]+개입니다 — 이 블로그 프로필의 소제목 수[(][0-9]+~[0-9]+개[)]와 다릅니다[.]$")      # 프로필의 소제목 수와 틀의 차이 — 거의 모든 초안에 붙는다(M6)
_SNIPPET = re.compile("[ ]*`[^`]*`[ ]*")                                                                                    # 명령줄 조각(`…`) — 화면 문장에는 쓰지 않는다


def is_common(line):
    """'모든 글 공통' 줄인가 — 알려진 고정 글로 **시작**하거나 소제목 수 어긋남 줄과 **정확히** 같은 모양일 때뿐이다."""
    return isinstance(line, str) and (line.startswith(COMMON_PREFIXES) or bool(_HEADING_COUNT.match(line)))


def plain_line(line):
    """확인 권장 한 줄을 화면 문장으로 — 프로필이 없다는 줄은 명령 대신 화면 문장으로 바꾸고, 그 밖에 명령줄 조각(`…`)이 있으면 그 조각을 뺀다."""
    if line.startswith(PROFILE_PREFIX):
        return T["drf_chk_profile"]
    return " ".join(_SNIPPET.sub(" ", line).split()) if "`" in line else line


def split_checks(lines):
    """확인 권장 줄들 → (이 글에만 해당, 모든 글 공통) — 각각 화면 문장으로 바꾼 줄들(순서 그대로, 같은 줄은 한 번만). 모르는 줄은 앞쪽(이 글에만 해당)이다."""
    specific, common = [], []
    for line in lines:
        text = plain_line(str(line))
        bucket = common if is_common(str(line)) else specific
        if text and text not in bucket:
            bucket.append(text)
    return tuple(specific), tuple(common)


def derived_lines(body):
    """서비스가 줄로 알려 주지 않지만 구조 칸으로 알 수 있는 이 글의 사실 — 분야를 못 읽었다(`generic`)·후기 형식을 정보형으로 바꿨다. 줄 글이 서비스의 줄과 겹치지 않는다."""
    found = []
    if getattr(body, "domain", "") == GENERIC_DOMAIN:
        found.append(T["drf_chk_domain"])
    replaced = getattr(body, "replaced", None)
    if replaced:
        found.append(T["drf_chk_replaced"].format(old=shown(replaced[0], 20), new=shown(replaced[1], 20)))
    return tuple(found)


# ---- 보이는 글 다듬기 ----------------------------------------------------------------------------------------------------------------------
def shown(value, limit=PREVIEW):
    """화면에 나가는 외부 글(점검에 걸린 문장·후보 제목)에서 비밀 모양을 가리고 한 줄로 줄인다 — 명령줄 출력과 같은 규칙(`security/mask.py`)."""
    return display_text(value, limit)


# ---- 키·토큰 모양 --------------------------------------------------------------------------------------------------------------------------
# `security/shape.looks_secret` 은 알려진 접두사와 '24자 이상 이어진 영숫자 덩어리' 둘을 본다. 둘째는 주소·파일 이름의 글번호·상품번호·해시·긴 글 주소도 키로 읽어서(독립 검증 V2)
# 정상 주소가 든 초안의 복사 여섯 단추가 모두 잠겼다. 그래서 **주소·파일 이름 모양 안에서는 이름이나 모양이 알려진 비밀만** 보고, 그 밖의 글은 예전처럼 둘 다 본다.
# 알려진 모양 = 정본 패턴·접두사·로그인 정보(독립 검증 V2) + 이름이 비밀 낱말인 주소 인자의 긴 값·웹훅 주소·비밀 이름 아래의 긴 경로 값·`sk-` 키가 경로 글자에 붙은 모양(독립 검증 D1).
# 이름 규칙은 서비스의 `참고 URL` 칸(`content/draft_options`)과 **같은 함수**를 쓴다 — 두 곳이 어긋나 편집기가 더 약해지는 일이 없게. 보안 코드(`security/`)는 고치지 않고 이 관문이 가려 본다.
WINDOW = 23                                                   # 긴 영숫자 덩어리 규칙은 24자 이상이라 이보다 짧은 창에서는 일어날 수 없다 — 주소 안에서는 이 길이의 창으로 훑어 알려진 접두사만 본다
SPOT_LIMIT = 3                                                # 막은 자리를 화면에 보이는 개수
CONTEXT_BEFORE = 14                                           # 미리보기에서 걸린 곳 앞의 글(문맥) 글자 수
FILE_EXTENSIONS = frozenset((
    "jpg", "jpeg", "jpe", "jfif", "png", "gif", "webp", "bmp", "svg", "heic", "heif", "avif", "tif", "tiff", "ico", "psd", "ai", "eps",
    "pdf", "doc", "docx", "docm", "xls", "xlsx", "xlsm", "xlsb", "ppt", "pptx", "pptm", "hwp", "hwpx", "odt", "ods", "odp", "rtf", "txt", "csv", "tsv", "md", "epub",
    "html", "htm", "css", "js", "mjs", "ts", "tsx", "jsx", "py", "java", "sql", "xml", "yaml", "yml", "toml", "log", "json",
    "zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "iso", "mp3", "wav", "flac", "aac", "ogg", "m4a", "mp4", "m4v", "mov", "avi", "wmv", "flv", "mkv", "webm", "srt"))        # 키·인증서 파일(pem·key·env …)은 일부러 뺐다
_ADDRESS = re.compile(r"(?i)(?:[a-z][a-z0-9+.\-]{1,15}://|www\.|(?<![a-z0-9._\-])(?:[a-z0-9\-]{1,63}\.)+[a-z]{2,24}/)[^\s<>\"'`]*")      # 방식이 있는 주소·`www.` 주소·방식 없이 쓴 `사이트.com/경로` — 공백·꺾쇠·따옴표 전까지(`? & % # =` 도 주소의 일부다)
_BARE_ADDRESS = re.compile(r"(?i)^[a-z0-9\-]{1,63}(?:\.[a-z0-9\-]{1,63})*\.[a-z]{2,24}/")      # 방식 없이 쓴 `사이트.com/경로` 모양(덩어리 맨 앞에서 시작할 때)
_KEY_RUN = re.compile(r"[A-Za-z0-9_\-+/=.~:]{10,}")                                           # 키·토큰에 쓰이는 글자만 이어진 덩어리(접두사 규칙의 가장 짧은 모양이 10자)
_LOGIN = re.compile(r"//[^/\s@:]*:[^/\s@]+@")                                                  # 주소 속 `사용자:비밀번호@`(사용자 이름이 빈 `//:비밀번호@` 도)
_WEBHOOKS = (                                                                                  # 알려진 웹훅 주소의 경로 모양 — 주소 자체가 열쇠다(채팅·자동화 서비스). 그 밖의 서비스는 모른다(D-312 의 한계)
    re.compile(r"(?i)/webhooks?/[0-9]{15,25}/[A-Za-z0-9_\-]{20,}"),                           # 디스코드식: /webhooks/숫자번호/긴 값
    re.compile(r"(?i)/incomingwebhook/[A-Za-z0-9]{20,}"),                                       # 팀즈식
    re.compile(r"(?i)/hooks/catch/[0-9]+/[A-Za-z0-9]{5,}"),                                     # 자피어식
    re.compile(r"(?i)/with/key/[A-Za-z0-9_\-]{16,}"),                                           # 이프트식
    re.compile(r"(?i)/hooks/[A-Za-z0-9]{24,}(?![A-Za-z0-9])"),                                  # 그 밖의 `/hooks/긴 값` (하이픈이 든 글 주소 `/hooks/using-…` 는 아니다)
)
_SK_PREFIXED = re.compile(r"sk-(?:proj|svcacct|admin|ant|or)-([A-Za-z0-9_\-]{20,})")         # 종류가 붙은 `sk-` 키 — 앞이 영숫자여도 읽는다(앞에 글자가 붙은 `task-proj-…` 글 주소는 아래 꼬리 모양으로 가른다)
_SK_PLAIN = re.compile(r"(?<![A-Za-z0-9])sk-([A-Za-z0-9]{20,})")                             # 구형 `sk-` + 영숫자 20자 이상(앞이 영숫자가 아닐 때만 — `Task-…` 같은 글 주소 제외)
_SK_LONG = re.compile(r"sk-([A-Za-z0-9]{40,})")                                               # 구형 `sk-` + 영숫자 40자 이상 — 앞이 영숫자여도 읽는다. 대문자와 숫자가 모두 있어야 한다(`Task-` 다음의 소문자 16진수 글번호·해시와 가른다)
_TELEGRAM = re.compile(r"[0-9]{6,12}:[0-9A-Za-z_\-]{20,}")                                   # 텔레그램 봇 꼴(`security/shape` 의 접두사 규칙과 같은 모양 — 창(WINDOW)보다 길어서 따로 본다)
_ALNUM_RUN = re.compile(r"[A-Za-z0-9]{24,}")                                                  # 영숫자만 24자 이상 이어진 덩어리
_PATH_VALUE = re.compile(r"[A-Za-z0-9]{20,}(?![A-Za-z0-9])")                                  # 비밀 이름 바로 아래 경로 조각의 값
_ATTACHED_RUN = re.compile(r"[^\x00-\x7f]([A-Za-z0-9]{24,})")                                # 한글 같은 글자에 바로 붙은 긴 영숫자 덩어리(구분 없이 붙여 쓴 키)
_COMMA_TAIL = re.compile(r",([A-Za-z0-9]{24,})(?![A-Za-z0-9])[^A-Za-z0-9]{0,3}$")             # 경로 맨 끝에 쉼표로 이어 붙은 긴 영숫자(뒤에 `.html` 같은 글자가 이어지면 아니다)
_TAIL_RUN = re.compile(r"[A-Za-z0-9]{12,}")                                                   # 종류가 붙은 `sk-` 키 꼬리에 있어야 하는 영숫자 덩어리(글 주소의 짧은 낱말과 가른다)


def _first_difference(original, other):
    """두 글이 처음 달라지는 자리 — 가리기 결과(`mask`)와 견줘 비밀 모양이 시작하는 곳을 찾는다."""
    for index, (left, right) in enumerate(zip(original, other)):
        if left != right:
            return index
    return min(len(original), len(other))


def _token_like(run):
    """영문자와 숫자가 모두 든 덩어리인가 — 키처럼 생겼다."""
    return any(ch.isalpha() for ch in run) and any(ch.isdigit() for ch in run)


def _extra_hit(form, literal):
    """주소 한 덩어리(글 그대로이거나 퍼센트를 푼 모양)에서 **이름이나 모양이 알려진 비밀**을 찾는다 → 가장 앞의 시작 자리 또는 None(독립 검증 D1).
    ① 이름이 비밀 낱말인 인자의 긴 값(`?이름=값`·`&`·`;`·`#`) — 서비스의 `참고 URL` 칸과 **같은 함수**(`_params`·`_secret_name`·`_secret_value`) ② 웹훅 주소 ③ 비밀 이름 바로 아래의 긴 경로 값 ④ 경로 글자에 붙은 `sk-` 키
    ⑤ 텔레그램 봇 꼴 ⑥ 점 없는 긴 사이트 이름(`xyz://무작위 글`) ⑦ 한글에 구분 없이 붙은 긴 영숫자(`literal` 일 때만 — 퍼센트를 푼 한글 뒤는 보지 않는다) ⑧ 경로 맨 끝에 쉼표로 이어 붙은 긴 영숫자.
    경로의 무작위 긴 값 일반과 인자 값 속 쉼표 목록은 정상 주소(글번호·해시·상품 번호 목록)와 모양이 같아 보지 않는다(D-312 의 한계)."""
    from ...content.draft_options import _params, _secret_name, _secret_value
    found = []
    tail = form.split("://", 1)[-1]
    head = len(form) - len(tail)                                                  # 방식(`https://`)까지의 길이 — 방식이 없으면 0
    cursor = head
    for name, argument in _params(form):                                          # ① `?token=…` 같은 이름 있는 인자
        index = form.find("=" + argument, cursor)
        if index >= 0:
            cursor = index + 1 + len(argument)
        if _secret_name(name) and _secret_value(argument):
            found.append(index + 1 if index >= 0 else head)
            break
    found += [match.start() for match in (pattern.search(form) for pattern in _WEBHOOKS) if match]          # ② 웹훅
    path = re.split(r"[?#]", tail, maxsplit=1)[0]
    segments = path.split("/")
    offset = head
    for position in range(len(segments) - 1):                                     # ③ `/비밀 이름/긴 값`
        offset += len(segments[position]) + 1
        value = _PATH_VALUE.match(segments[position + 1])
        if value and segments[position] and _token_like(value.group()) and _secret_name(segments[position]):
            found.append(offset)
            break
    match = _COMMA_TAIL.search(path)                                              # ⑧ 경로 끝에 쉼표로 이어 붙은 긴 영숫자(`…/글,해시`) — 인자 값 속 쉼표 목록(`?products=해시,해시`)은 보지 않는다
    if match and _token_like(match.group(1)):
        found.append(head + match.start(1))
    for match in _SK_PREFIXED.finditer(form):                                     # ④ `…글자sk-proj-…`
        if _token_like(match.group(1)) and _TAIL_RUN.search(match.group(1)):
            found.append(match.start())
            break
    for match in _SK_PLAIN.finditer(form):
        if _token_like(match.group(1)):
            found.append(match.start())
            break
    for match in _SK_LONG.finditer(form):
        if any(ch.isupper() for ch in match.group(1)) and any(ch.isdigit() for ch in match.group(1)):
            found.append(match.start())
            break
    match = _TELEGRAM.search(form)                                                # ⑤
    if match:
        found.append(match.start())
    if "://" in form:                                                             # ⑥ 사이트 이름 자리에 점 없이 이어진 긴 글
        host = re.split(r"[/?#]", tail, maxsplit=1)[0].rsplit("@", 1)[-1].split(":", 1)[0]
        match = None if "." in host else _ALNUM_RUN.search(host)
        if match and _token_like(match.group()):
            found.append(head + host.find(match.group()))
    if literal:                                                                   # ⑦
        for match in _ATTACHED_RUN.finditer(form):
            if _token_like(match.group(1)):
                found.append(match.start(1))
                break
    return min(found) if found else None


def _address_hit(region):
    """주소·파일 이름 한 덩어리에서 **알려진 비밀만** 찾는다 → `(덩어리 안의 시작, 걸린 글의 길이)` 또는 None. 길이가 None 이면 덩어리 끝까지(정본 모양 — 가려서 보인다), 0 이면 자리만 짚는다(이름·모양으로 알아본 것 — 비밀 글자를 한 자도 되풀이하지 않는다).
    정본 패턴(`has_key_shape`)·접두사(`looks_secret` 을 `WINDOW` 글자 창으로 — 긴 덩어리 규칙이 일어나지 않게)·`_extra_hit` 의 이름·모양 규칙·`사용자:비밀번호@`. 퍼센트로 쓴 글자를 푼 모양(세 번 겹쳐 쓴 것까지)도 같이 본다."""
    from ...security.mask import has_key_shape, mask
    from ...security.shape import looks_secret
    forms = [region]
    for _ in range(3):
        decoded = unquote(forms[-1])
        if decoded == forms[-1]:
            break
        forms.append(decoded)
    for number, form in enumerate(forms):
        if has_key_shape(form):
            return (_first_difference(form, mask(form)) if number == 0 else 0), None
        for start in range(max(1, len(form) - WINDOW + 1)):
            window = form[start:start + WINDOW]
            # `sk-` 뒤에 열두 글자만 이어져도 접두사로 보는 느슨한 규칙은 `sk-hynix-…` 같은 글 주소에도 걸린다 — 진짜 `sk-` 키는 위의 정본 패턴(`has_key_shape`)과 `_extra_hit` 가 보므로 창에서는 그 접두사를 뺀 나머지 접두사만 본다
            if looks_secret(window) and looks_secret(window.replace("sk-", "sk ")):
                return (start if number == 0 else 0), None
        spot = _extra_hit(form, number == 0)
        if spot is not None:
            return (spot if number == 0 else 0), 0
    found = _LOGIN.search(region)
    return (found.start(), None) if found else None


def _spot(base, end, hit):
    """`_address_hit` 의 결과를 글 전체에서의 (시작, 끝) 으로 — 덩어리가 글에서 `base` 에서 `end` 까지다."""
    start = base + hit[0]
    return (start, end if hit[1] is None else start + hit[1])


_LINE_BREAK = re.compile(r"\r\n|\n|\r")


def _scanner_spans(text):
    """본문 속 비밀 형태 검사기(`security/scan.py` — Google API 키·GitHub 토큰·Bearer 토큰·OAuth 토큰·AWS 액세스 키·개인 키)가 찾은 자리들 → ((시작, 끝), …) 글자 번호(끝은 포함하지 않는다).
    복사 관문이 저장·백업 전 검사와 **같은 종류**를 막게 한다(PCSEC1 M3) — 모양을 알아보는 규칙은 검사기 한 곳에 있고 여기서는 부르기만 한다."""
    from ...security import scan
    found = scan.scan_secrets(text)
    if not found:
        return ()
    starts = [0]
    starts.extend(match.end() for match in _LINE_BREAK.finditer(text))
    return tuple((starts[item.line - 1] + item.col_start - 1, starts[item.line - 1] + item.col_end) for item in found)


def secret_spots(text):
    """글에서 키·토큰 모양이 걸린 자리들 — ((시작, 끝), …) 순서대로. 없으면 빈 튜플. 글이 아니거나 너무 길면 믿을 수 없어 처음 한 자리를 돌려준다(실패 열림 금지).
    주소·파일 이름 모양은 알려진 키 모양만 보고(`_address_hit`), 그 밖의 덩어리는 `looks_secret`(접두사·긴 영숫자)을 그대로 쓴다. 정본 패턴(`has_key_shape`)은 글 전체에 건다."""
    from ...security.mask import has_key_shape, mask
    from ...security.shape import MAX_SCAN_CHARS, looks_secret
    if not isinstance(text, str):
        return ((0, 0),)
    if len(text) > MAX_SCAN_CHARS:
        return ((0, 1),)
    spots, parts, last = [], [], 0
    for found in _ADDRESS.finditer(text):
        hit = _address_hit(found.group())
        if hit is not None:
            spots.append(_spot(found.start(), found.end(), hit))
        parts += [text[last:found.start()], " " * (found.end() - found.start())]
        last = found.end()
    parts.append(text[last:])
    rest = "".join(parts)                                                        # 주소를 지운 나머지 글(자리는 그대로 — 글자를 공백으로 바꿨다)
    for found in _KEY_RUN.finditer(rest):
        run = found.group()
        if "." in run and (run.rpartition(".")[2].lower() in FILE_EXTENSIONS or _BARE_ADDRESS.match(run)):
            hit = _address_hit(run)                                              # 파일 이름·`사이트.com/경로` — 주소처럼 알려진 비밀만
        else:
            hit = (0, None) if looks_secret(run) else None
        if hit is not None:
            spots.append(_spot(found.start(), found.end(), hit))
    if not spots and has_key_shape(text):                                        # 여러 덩어리에 걸친 정본 패턴(`Bearer …`·개인 키 블록 …)
        at = _first_difference(text, mask(text))
        spots.append((at, at + 1))
    for span in _scanner_spans(text):                                            # 검사기의 여섯 유형도 같은 관문에서 막는다(위에서 이미 잡은 자리와 겹치면 그 자리가 대신한다)
        if not any(span[0] < other[1] and other[0] < span[1] for other in spots):
            spots.append(span)
    return tuple(sorted(spots))


def has_secret(*texts):
    """키·토큰 모양이 하나라도 있는가 — 글이 아니면 참(믿을 수 없다). 주소·파일 이름 모양은 알려진 키 모양만 본다(`secret_spots`)."""
    return any(secret_spots(text) for text in texts)


def _place(name, text, start, end):
    """막은 자리 하나의 미리보기 — `이름 — …걸린 곳 앞의 글 + 걸린 곳의 앞부분`(전체 PREVIEW 글자). 정본 비밀 모양은 가려서(`[가림: …]`), 그 밖의 긴 덩어리(알아보지 못한 영숫자)는 글자 없이 `[가림]` 표시만 남는다 — 앞 글자도 화면에 되풀이하지 않는다(PCSEC1 D16)."""
    from ...security.mask import mask
    before = text[max(0, start - CONTEXT_BEFORE):start]
    hit = text[start:end]
    masked = mask(hit)
    front = T["drf_spot_hidden"] if not hit else (masked if masked != hit else T["drf_spot_hidden"])      # 길이가 0 인 자리(이름·모양으로 알아본 것)는 글자를 보이지 않고 어디서부터인지만 짚는다
    if hit and masked == hit and any(start < other_end and other_start < end for other_start, other_end in _scanner_spans(text)):
        front = T["drf_spot_hidden"]                                                         # 검사기가 찾은 자리와 겹치는데 가려지지 않는 글자는 한 자도 되풀이하지 않는다 — 어디서부터인지만 짚는다(PCSEC1 M3)
    if hit and masked != hit and before.endswith("="):
        front = T["drf_spot_hidden"]                                                         # `key=` 바로 뒤의 가림 이름이 `shown` 의 주소 인자 가림에 한 번 더 걸려 닫는 괄호가 남는 겉모양을 막는다
    return f"{name} — " + ("…" if start > CONTEXT_BEFORE else "") + shown(before + front, PREVIEW)


def secret_places(*named):
    """((이름, 글), …) → 키·토큰 모양을 막은 자리의 미리보기들(`SPOT_LIMIT` 개까지, 같은 것은 한 번) — 없으면 빈 튜플. 이름은 화면에 보이는 말(`제목`·`본문`·`키워드` …)이다."""
    places = []
    for name, text in named:
        for start, end in secret_spots(text):
            place = _place(name, text, start, end) if isinstance(text, str) else str(name)       # 글이 아닌 값은 이름만(미리볼 글이 없다)
            if place not in places:
                places.append(place)
            if len(places) >= SPOT_LIMIT:
                return tuple(places)
    return tuple(places)


def count_text(text):
    """(공백·줄바꿈을 뺀 글자 수, 줄바꿈을 뺀 글자 수 — 공백 포함) — 서비스의 `count_chars` 와 같은 센 법."""
    return len("".join(text.split())), len(text.replace(chr(10), "").replace(chr(13), ""))


def paragraphs_of(text):
    """글 → 문단들(빈 줄로 가르고 문단 안의 줄바꿈·공백은 한 칸으로) — 문단이 같은지 견주는 모양."""
    unified = text.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))
    return [" ".join(part.split()) for part in re.split("\n[ \t]*\n", unified) if part.strip()]


def changed_chars(generated_title, generated_titles, title, generated_body, body):
    """생성한 글에서 **고친 글자 수** — 본문은 문단 목록을 견줘 바뀐 문단(바꾼·더한·지운 문단)의 글자 수 합(문단 안에서 한 낱말만 고쳐도 그 문단 전체를 센다), 제목은 생성한 제목 후보 셋 중 하나가 아니면 고친 것으로 보고 긴 쪽의 글자 수를 더한다.
    줄바꿈·공백만 다른 것은 고친 것이 아니다."""
    first, second = paragraphs_of(generated_body), paragraphs_of(body)
    total = 0
    for tag, a_start, a_end, b_start, b_end in difflib.SequenceMatcher(None, first, second, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        total += max(sum(len(item) for item in first[a_start:a_end]), sum(len(item) for item in second[b_start:b_end]))
    if " ".join(title.split()) not in {" ".join(item.split()) for item in generated_titles}:
        total += max(len(" ".join(title.split())), len(" ".join(generated_title.split())))
    return total


# ---- 점검 ----------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ClaimNote:
    violation: bool                                          # 지어낸 경험·사례처럼 읽히는 것(True) / 확인하지 않은 가격·날짜·시각·통계(False)
    label: str                                               # 쉬운 이름(`check/claims` 의 분류 이름)
    preview: str                                             # 걸린 문장의 앞부분(비밀 모양은 가렸다)
    pair: tuple                                              # (분류, 근거 낱말) — 이미 확인한 것을 기억하는 열쇠


HEALTH_STAGES = ("general", "mark", "evidence", "stop")      # `topics.safety.HEALTH_STAGES` 와 같은 값·같은 순서(낮은 단계 → 높은 단계) — 시험이 같은지 견준다
HEALTH_STOP = "stop"                                         # 의료·효과 단정 위험(C) — 복사를 막는다
HEALTH_UNIT_MAX = 400                                        # 건강 판정을 거는 글 조각의 최대 글자 수(더 긴 문장은 이만큼씩 자른다)


@dataclass(frozen=True)
class HealthReview:
    """글 조각들의 건강 판정 결과 — 가장 높은 단계(`HEALTH_STAGES`)와 중지(C)에 걸린 조각의 앞부분 미리보기(비밀 모양은 가렸다, `SPOT_LIMIT` 개까지)."""
    stage: str = "general"
    places: tuple = ()


def health_units(text):
    """글 → 건강 판정을 **따로** 거는 글 조각들(문장 단위 — `check/claims.split_sentences`, 한 조각은 `HEALTH_UNIT_MAX` 글자까지). 글 전체를 한 덩어리로 넣으면 서로 먼 문장의 낱말이 섞여 정상 글이 중지로 읽혀서 문장마다 본다.
    글이 아니거나 비어 있으면 빈 튜플."""
    from ...check import claims as check
    units = []
    for sentence in check.split_sentences(text if isinstance(text, str) else ""):
        units += [sentence[start:start + HEALTH_UNIT_MAX] for start in range(0, len(sentence), HEALTH_UNIT_MAX)]
    return tuple(units)


@dataclass(frozen=True)
class Inspection:
    secret: bool                                             # 키·토큰 모양이 있다 — 복사를 막는다
    claims: tuple                                            # ClaimNote
    changed: int                                             # 고친 글자 수
    unchanged: bool                                          # 거의 고치지 않았다(`UNCHANGED_BELOW` 미만)
    chars: int                                               # 본문 글자 수(공백 제외)
    spaced: int                                              # 본문 글자 수(공백 포함)
    places: tuple = ()                                       # 키·토큰 모양을 막은 자리의 미리보기(앞부분만, 가렸다)
    health: object = None                                    # 제목·본문의 건강 판정(`HealthReview`) — 부른 쪽이 넣는다(이 파일은 `topics` 를 모른다). 없으면 보지 않았다

    @property
    def violations(self):
        return tuple(note for note in self.claims if note.violation)

    @property
    def reviews(self):
        return tuple(note for note in self.claims if not note.violation)


def user_texts(options):
    """사용자가 선택 입력에 적은 모든 글(칸마다 한 덩어리, 여러 줄 칸은 줄마다) — 서비스가 만들 때와 같이 '사용자 글은 위반에서 뺀다' 를 맞추려고 쓴다."""
    found = []
    for name, single in OPTION_FIELDS:
        value = (options or {}).get(name, "")
        found += [value.strip()] if single else [line.strip() for line in value.splitlines()]
    return tuple(text for text in found if text)


def claims_of(text, options=None):
    """편집기 글을 `check/claims` 로 훑는다 → ClaimNote 튜플(문장 순). 사용자가 '실제 사용 경험' 을 적었으면 그 글과 똑같은 문장은 위반에서 뺀다(서비스가 본문을 만들 때와 같다)."""
    from ...check import claims as check
    sentences = check.split_sentences(text)
    given = bool((options or {}).get("experience", "").strip())
    found = check.find_claims(sentences, experience_given=given, user_sentences=user_texts(options) if given else ())
    notes, seen = [], set()
    for claim in found:
        pair = (claim.category, claim.word)
        key = (claim.position, pair)
        if key in seen:
            continue
        seen.add(key)
        notes.append(ClaimNote(check.is_violation(claim.category), check.LABELS.get(claim.category, claim.category), shown(sentences[claim.position] if 0 <= claim.position < len(sentences) else "", PREVIEW), pair))
    return tuple(notes)


def inspect_text(title, body, *, generated_title="", generated_titles=(), generated_body="", options=None, health=None):
    """편집기의 제목·본문을 한 번에 훑는다 — 키·토큰 모양(막은 자리 포함)·지어낸 사실 점검·고친 양·글자 수. 건강 판정은 부른 쪽이 `health`(`HealthReview`)로 넣는다. 파일·네트워크·클립보드를 쓰지 않는다."""
    changed = changed_chars(generated_title, generated_titles, title, generated_body, body)
    chars, spaced = count_text(body)
    places = secret_places((T["drf_where_title"], title), (T["drf_where_body"], body))
    return Inspection(bool(places), claims_of(body, options) + (claims_of(title, options) if title.strip() else ()), changed, changed < UNCHANGED_BELOW, chars, spaced, places, health)


# ---- 복사 전 관문 --------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Gate:
    """한 복사에 대한 관문의 결과 — `blocked`(키 모양·건강 효과 단정: 복사하지 않는다)·`reasons`(이름 → 항목들, 확인창에 보인다)·`new`(아직 확인하지 않은 것이 있다 — 확인창을 띄운다)."""
    blocked: bool
    reasons: tuple                                           # ((묶음 이름, 항목 글들), …) — 항목이 있는 묶음만
    new: bool
    keys: dict                                               # 묶음 이름 → 확인하면 기억할 열쇠 집합(`확인함` 으로 쌓인다)
    blocks: tuple = ()                                       # 막은 이유와 그 자리의 미리보기 — (('keyshape', 미리보기들), ('health', 미리보기들)) 중 해당하는 것(키·토큰 모양 / 건강 효과 단정)

    @property
    def count(self):
        return sum(len(items) for _name, items in self.reasons)

    @property
    def needs_dialog(self):
        return self.new and bool(self.reasons)


GATE_GROUPS = ("check", "domain", "claims", "unchanged")      # 확인창에 보이는 묶음 순서


def gate_for(item, inspection, specific_lines, domain_unknown, acknowledged, health=None):
    """`item`(`title`·`body`·`all`) 을 복사하기 전 관문. `acknowledged`(묶음 이름 → 이미 확인한 항목 집합)에 있는 것은 다시 묻지 않고 새로 생긴 것만 다시 묻는다(새 것이 있으면 확인창에는 지금의 모든 항목이 보인다).
    키 모양과 **건강 효과 단정**(`health` — 이 복사할 글의 `HealthReview` 가 중지 단계)은 확인이 아니라 **막음**이다. 제목만 복사할 때는 본문의 '거의 고치지 않았어요' 안내를 붙이지 않는다."""
    if item not in GATED:
        raise ValueError("관문은 제목·본문·전체 복사에만 있다")
    found = {"check": tuple(specific_lines), "domain": (T["drf_chk_domain"],) if domain_unknown else (),
             "claims": tuple(dict.fromkeys(f"{note.label}: {note.preview}" for note in inspection.claims)),
             "unchanged": (T["drf_gate_unchanged"],) if inspection.unchanged and item in SOFT_UNCHANGED else ()}
    keys = {"check": set(found["check"]), "domain": set(found["domain"]), "claims": {note.pair for note in inspection.claims}, "unchanged": set(found["unchanged"])}
    new = any(keys[name] - set(acknowledged.get(name, ())) for name in GATE_GROUPS)
    reasons = tuple((name, found[name]) for name in GATE_GROUPS if found[name])
    blocks = []
    if inspection.secret:
        blocks.append(("keyshape", tuple(inspection.places)))
    if health is not None and health.stage == HEALTH_STOP:
        blocks.append(("health", tuple(health.places)))
    return Gate(bool(blocks), reasons, new, keys, tuple(blocks))


# ---- 네이버 글쓰기 열기 ---------------------------------------------------------------------------------------------------------------------
_BLOG_ID = re.compile("^[A-Za-z0-9_-]{1,40}$")
WRITE_SUFFIX = "?Redirect=Write"


def naver_write_url(blog_url):
    """프로필의 블로그 주소(`https://blog.naver.com/<아이디>`)에서 글쓰기 주소를 만든다 — **주소만 열기**: https·`blog.naver.com`·아이디 한 토막(영문·숫자·`_`·`-`)이고 로그인 정보·포트·인자·조각이 없을 때만, 아니면 빈 글(단추를 끈다)."""
    if not isinstance(blog_url, str) or not blog_url or len(blog_url) > 200 or any(ch.isspace() for ch in blog_url):
        return ""
    try:
        parts = urlsplit(blog_url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return ""
    if parts.scheme != "https" or host != "blog.naver.com" or port is not None or parts.username or parts.password or parts.query or parts.fragment:
        return ""
    blog_id = parts.path.strip("/")
    if not _BLOG_ID.match(blog_id) or "/" in blog_id:
        return ""
    return f"https://blog.naver.com/{blog_id}{WRITE_SUFFIX}"


# ---- 선택 입력 ------------------------------------------------------------------------------------------------------------------------------
def options_dict(fields):
    """화면 칸의 글(이름 → 글) → 서비스에 넘길 칸들(이름 → 글 한 덩어리) — 비어 있는 칸은 뺀다. 여러 줄 칸은 빈 줄을 버리고 줄마다 앞뒤 공백을 뺀다. 칸 이름이 아닌 키는 버린다."""
    found = {}
    for name, single in OPTION_FIELDS:
        value = fields.get(name, "") if isinstance(fields, dict) else ""
        if not isinstance(value, str):
            continue
        text = " ".join(value.split()) if single else chr(10).join(line.strip() for line in value.splitlines() if line.strip())
        if text:
            found[name] = text
    return found


def build_options(chosen):
    """`options_dict` 의 결과 → 서비스의 `DraftOptions`(값 검사는 그쪽이 심판이다 — 틀리면 `DRAFT_OPTION_INVALID`). 여러 줄 칸은 줄마다 한 항목이다."""
    from ...content.draft_options import DraftOptions
    values = {name: (tuple(text.splitlines()) if name in LIST_FIELDS else text) for name, text in chosen.items()}
    return DraftOptions(**values)


def option_labels():
    """칸 이름(`message` …) → 서비스가 쓰는 한국어 이름 — 오류 문장에서 '어느 칸' 을 가리킬 때 쓴다."""
    from ...content.draft_options import LABELS
    return dict(LABELS)
