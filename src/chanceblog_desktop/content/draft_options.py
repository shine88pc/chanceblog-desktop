"""작성 선택 입력(`DraftOptions`) — 후보를 골라 작성 기반(`DraftPlan`)을 만들 때 사용자가 **덧붙일 수 있는** 11가지 입력(요구서 v0.3.1 §5.2).

규칙: ① 모든 칸은 선택이다 — 하나도 안 적어도(비어 있어도) 오류도 진행 차단도 없다. 비어 있는 칸은 값 적용 순서(사용자 입력 → 블로그 프로필 → 글 유형 틀 → 후보 → 공통 기본값)에서 그냥 건너뛴다.
② 글칸은 한 줄로 정리한다(`clean_line` — 제어·보이지 않는 글자를 지우고 공백을 접는다). 길이 상한이 있고, 눈에 안 보이거나 쌓인 글자·위험한 HTML·스크립트·템플릿 표기·
   결과를 약속하는 표현(상위노출 보장 같은 것 — 후보와 같은 규칙 `candidates.forbidden_claim`)은 거절한다. 경험을 단정하는 말은 **막지 않는다** — 사용자 자신의 글이기 때문이다(검사는 `check/claims.py`).
③ 참고 URL 은 https 공개 주소만 받고 로그인 정보(`사용자:비밀@`)·`javascript:` 같은 주소·토큰이 든 인자·IP 주소·점 없는 이름을 거절한다. **앱은 그 주소를 열지도 가져오지도 않는다** — 글자 그대로 보여 줄 뿐이다.
④ 글 길이는 `1500-2000`(범위)이나 `2500+`(이상) 모양의 숫자 범위만 받는다(200~100,000자). ⑤ JSON 으로 저장·불러올 수 있고(`to_dict`·`from_dict`) 모르는 키는 거절한다.
틀린 값은 `DRAFT_OPTION_INVALID`(어느 칸이 왜 안 되는지 문구에 담긴다)로 거절한다. 네트워크·파일은 쓰지 않는다.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from ..errors import AppError
from .candidates import _BLANK_LOOKALIKES, _STACKED_MARKS, forbidden_claim
from .profiles import MAX_CHARS_LIMIT, clean_line, find_markup

SCHEMA = 1
MAX_MESSAGE = 500
MAX_EXPERIENCE = 1000
MAX_OPINION = 500
MAX_CONCLUSION = 300
MAX_AUDIENCE = 100
MAX_TITLE_DIRECTION = 100
MAX_MUST_INCLUDE, MAX_SENTENCE = 10, 200
MAX_EXCLUDE, MAX_EXCLUDE_WORD = 20, 60
MAX_URLS, MAX_URL = 10, 300
RAW_ITEMS = 100                            # 한 칸에 넣을 수 있는 항목 수의 상한(빈 항목·겹치는 항목까지 센다) — 터무니없이 긴 목록을 하나하나 검사하기 전에 거절한다
MAX_PRICE_DATE, MAX_PRICE_DATE_ITEM = 10, 100
MIN_LENGTH = 200                           # 원하는 글 길이의 하한
MAX_LENGTH = MAX_CHARS_LIMIT               # 상한(프로필의 글 길이 상한과 같다)
LABELS = {
    "message": "직접 전달하고 싶은 내용", "experience": "실제 사용 경험", "opinion": "개인 의견", "must_include": "반드시 포함할 문장", "exclude": "제외할 내용", "audience": "특정 독자층",
    "length": "원하는 글 길이", "title_direction": "원하는 제목 방향", "urls": "참고 URL", "price_date": "실제 가격이나 날짜", "conclusion": "최종 결론",
}
KEYS = tuple(LABELS)
_BAD_URL_CHARS = frozenset("<>\"'`\\{}|^")
# 가리기 규칙은 눈에 안 보이는 글자로 보고 지우지만 `clean_line`·`_BLANK_LOOKALIKES` 가 못 잡는 드문 자리 — 배정 안 된 U+2065·U+FFF0~FFF8, 태그·변형 선택자 보충 구역 U+E0000~E0FFF.
# 그대로 두면 비밀 검사가 '글이 바뀌었다' 고 봐서 '비밀번호' 문구로 잘못 안내한다
_RARE_INVISIBLES = re.compile("[\u2065\ufff0-\ufff8\U000e0000-\U000e0fff]")
# 주소 인자 이름(소문자로 하고 `-`·`_`·`.`·공백을 지운 모양)이 이 낱말을 품으면 비밀을 나르는 이름이다: `token`·`access_token`·`token_value`·`token2`·`token[]`·`password_hash`·`xamzsignature`·`phpsessid` …
# (`tokenizer`·`tokens`·`secretary` 처럼 낱말을 품기만 한 평범한 이름은 값도 함께 봐서 숫자뿐이거나 짧은 값이면 통과시킨다)
_SECRET_NAME_PARTS = ("token", "secret", "password", "passwd", "pwd", "signature", "authorization", "bearer", "jwt", "credential", "apikey", "accesskey", "privatekey", "sessionid", "sessid")
# 이 이름은 정확히 같을 때만 비밀 이름이다 — 낱말을 품기만 한 `country_code`·`keyword`·`sessions`·`authors`·`sid1` 은 아니다
_SECRET_NAME_SAME = frozenset({"sig", "key", "auth", "pass", "otp", "sign", "sid", "ticket", "code", "session"})
# 사이트 이름의 마지막 낱말이 이것이면 공개 주소가 아니다(내부망·예약 이름)
_RESERVED_TLDS = frozenset({"localhost", "internal", "local", "localdomain", "lan", "intranet", "private", "corp", "home", "invalid", "test", "onion", "arpa"})
_KNOWN_SCHEMES = frozenset({"http", "ftp", "file", "data", "javascript", "mailto", "tel", "ws", "wss", "ssh", "git", "blob", "about", "chrome", "vbscript"})
_NUMBER = r"([0-9]{3,6})"
_RANGE = re.compile(rf"{_NUMBER}자?[-~]{_NUMBER}자?")
_OPEN = re.compile(rf"{_NUMBER}자?(?:\+|이상|[-~])")


def _invalid(key, reason, *, detail=""):
    """선택 입력의 칸 값이 틀렸을 때의 오류 — 사용자가 읽는 문구에 어느 칸(`key` 의 한국어 이름)이 왜(`reason`) 안 되는지가 담긴다."""
    return AppError("DRAFT_OPTION_INVALID", {"항목": LABELS.get(key, key), "이유": reason}, detail=detail or reason)


_SECRET_REASON = "비밀번호·키·토큰처럼 보이는 글이 들어 있습니다(‘이름: 값’ 꼴도 비밀로 보여 받지 않습니다) — 문장으로 바꿔 써 주세요"
_URL_SHAPE_REASON = "주소에 키·토큰처럼 보이는 글이 들어 있습니다 — 그 부분을 빼고 주소를 입력해 주세요"
_URL_PARAM_REASON = "주소에 토큰이나 인증 값처럼 보이는 인자가 들어 있습니다 — 주소에서 ? 뒤를 빼고 입력해 주세요"


def _looks_secret(text):
    """가리기 규칙(`security.mask`)이 비밀로 알아보는 글이 들어 있는가. 그런 글은 칸 값으로 받지 않는다 — `이름: 값` 꼴도 비밀로 본다(한글에 바로 붙은 키도 가리기 규칙이 알아본다)."""
    from ..security.mask import mask                            # 늦게 가져온다(가리기 모듈은 vendor/ 를 먼저 올려야 한다)
    return mask(text) != text


def _forms(text):
    """주소를 읽는 모양들 — 글 그대로와 퍼센트로 쓴 글자를 풀어 쓴 모양(`token%3D…`, 두 번 겹쳐 쓴 `%253D` 까지)."""
    forms = [text]
    for _ in range(2):
        decoded = unquote(forms[-1])
        if decoded == forms[-1]:
            break
        forms.append(decoded)
    return forms


def _has_key_shape(text):
    """키·토큰 모양만 본다(주소 인자 이름·`이름: 값` 꼴은 보지 않는다) — 퍼센트로 쓴 모양(`Bearer%20…`)도."""
    from ..security.mask import has_key_shape
    return any(has_key_shape(form) for form in _forms(text))


def squash(text):
    """비교하는 모양 — 호환 문자를 풀고(NFKC) 모든 공백을 없애고 소문자로 한다. '가상 자산' 과 '가상자산', 'AI' 와 'ＡＩ' 를 같은 낱말로 본다."""
    return "".join(unicodedata.normalize("NFKC", str(text)).split()).casefold()


# ---- 글 길이 ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class LengthWish:
    """원하는 글 길이 — `low` 자 이상 `high` 자 이하, `high` 가 없으면(None) `low` 자 이상."""
    low: int
    high: int | None = None

    def __post_init__(self):
        if not isinstance(self.low, int) or isinstance(self.low, bool) or not MIN_LENGTH <= self.low <= MAX_LENGTH:
            raise _invalid("length", f"{MIN_LENGTH}~{MAX_LENGTH:,}자 사이여야 합니다", detail="하한이 범위 밖이다")
        if self.high is not None and (not isinstance(self.high, int) or isinstance(self.high, bool) or not self.low <= self.high <= MAX_LENGTH):
            raise _invalid("length", f"상한은 하한 {self.low:,}자 이상 {MAX_LENGTH:,}자 이하여야 합니다", detail="상한이 범위 밖이다")

    def text(self):
        """저장하는 모양: `1500-2000` 또는 `2500+`."""
        return f"{self.low}+" if self.high is None else f"{self.low}-{self.high}"

    def korean(self):
        """화면에 보일 모양: `1,500~2,000자` 또는 `2,500자 이상`."""
        return f"{self.low:,}자 이상" if self.high is None else f"{self.low:,}~{self.high:,}자"

    def to_range(self):
        return self.low, self.high


def parse_length(text):
    """`1500-2000`·`1500~2000자`·`2,500+`·`2500자 이상` 같은 글 → LengthWish. 쉼표·공백·전각 글자는 무시한다. 모양이 아니면 DRAFT_OPTION_INVALID."""
    if not isinstance(text, str):
        raise _invalid("length", "글이어야 합니다")
    plain = "".join(ch for ch in unicodedata.normalize("NFKC", text).replace("〜", "~").replace("–", "-").replace("—", "-") if not ch.isspace() and ch != ",")
    found = _RANGE.fullmatch(plain)
    if found:
        return LengthWish(int(found.group(1)), int(found.group(2)))
    found = _OPEN.fullmatch(plain)
    if found:
        return LengthWish(int(found.group(1)))
    raise _invalid("length", "1500-2000(범위)이나 2500+(이상) 모양의 숫자여야 합니다", detail=f"모양이 아니다(입력한 글은 적지 않는다, {len(plain)}자)")


# ---- 칸 값 정리 ------------------------------------------------------------------------------------------------------------------
def _text(value, key, high):
    """글칸 하나 — 한 줄로 정리하고 길이·눈에 안 보이는 글자·위험한 표기·결과를 약속하는 표현을 본다. 빈 글은 ''."""
    if not isinstance(value, str):
        raise _invalid(key, "글이어야 합니다", detail=f"{type(value).__name__} 은 받지 않는다")
    text = clean_line(value)
    if len(text) > high:
        raise _invalid(key, f"{high}자 이하여야 합니다(지금 {len(text)}자)")
    if _BLANK_LOOKALIKES.search(text) or _RARE_INVISIBLES.search(text):
        raise _invalid(key, "눈에 보이지 않거나 빈칸·깨진 글자처럼 보이는 글자가 들어 있습니다")
    if _STACKED_MARKS.search(text):
        raise _invalid(key, "겹쳐 쌓였거나 홀로 붙은 결합 문자가 들어 있습니다")
    markup = find_markup(text)
    if markup:
        raise _invalid(key, markup)
    if _looks_secret(text):
        raise _invalid(key, _SECRET_REASON, detail="비밀 모양의 글이 들어 있다(값은 적지 않는다)")
    claim = forbidden_claim(text)
    if claim:
        label = claim[0]
        raise _invalid(key, f"‘{label}’ 같은 결과를 약속하는 표현은 쓸 수 없습니다", detail=f"쓸 수 없는 표현의 종류: {label}(입력한 글은 적지 않는다)")
    return text


def _texts(values, key, *, count, high):
    """글 목록 — list·tuple(글 하나만 줘도 된다)만 받는다. 빈 글은 버리고 같은 글(띄어쓰기·대소문자 무시)은 앞의 것만 남긴다."""
    if isinstance(values, str):
        values = (values,)
    if not isinstance(values, (list, tuple)):
        raise _invalid(key, "글의 목록이어야 합니다", detail=f"{type(values).__name__} 은 받지 않는다(순서가 정해지지 않는다)")
    if len(values) > RAW_ITEMS:
        raise _invalid(key, f"항목이 너무 많습니다(한 칸에 {RAW_ITEMS}개까지)")
    found, seen = [], set()
    for item in values:
        text = _text(item, key, high)
        if text and squash(text) not in seen:
            seen.add(squash(text))
            found.append(text)
    if len(found) > count:
        raise _invalid(key, f"{count}개까지 쓸 수 있습니다(지금 {len(found)}개)")
    return tuple(found)


def _numberish(label):
    """IP 주소의 한 토막처럼 읽히는 낱말 — `127`·`0x7f`·`0177`·`0x7f000001`."""
    return label.isdigit() or (label[:2].casefold() == "0x" and len(label) > 2 and all(ch in "0123456789abcdefABCDEF" for ch in label[2:]))


def _host_problem(host):
    if not host:
        return "사이트 이름이 없습니다"
    if "." not in host or host.startswith(".") or host.endswith(".") or host.casefold() == "localhost":
        return "공개 사이트 주소(example.com 같은 이름)여야 합니다"
    labels = host.split(".")
    if _numberish(labels[-1]) or all(_numberish(label) for label in labels):
        return "숫자로 된 IP 주소는 쓸 수 없습니다 — 사이트 이름으로 된 공개 주소여야 합니다"
    if labels[-1].casefold() in _RESERVED_TLDS:
        return "내부망이나 예약된 이름은 쓸 수 없습니다 — 누구나 열 수 있는 공개 주소여야 합니다"
    for label in labels:
        if not label or label.startswith("-") or label.endswith("-") or not label.replace("-", "").isalnum():
            return "사이트 이름에 쓸 수 없는 글자가 있습니다"
    return ""


def _url(value):
    """참고 URL 하나 — https 공개 주소만. 열지도 가져오지도 않는다(글자 그대로 보여 줄 뿐)."""
    key = "urls"
    if not isinstance(value, str):
        raise _invalid(key, "글이어야 합니다")
    text = value.strip()
    if not text:
        return ""
    if len(text) > MAX_URL:
        raise _invalid(key, f"주소는 {MAX_URL}자 이하여야 합니다")
    if any(ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co") or ch in _BAD_URL_CHARS for ch in text):
        raise _invalid(key, "공백·제어 문자·따옴표·꺾쇠·역슬래시·중괄호가 들어 있습니다")
    try:
        parts = urlsplit(text)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise _invalid(key, "주소 모양이 올바르지 않습니다") from None
    if parts.scheme != "https":
        scheme = parts.scheme.casefold() if parts.scheme.casefold() in _KNOWN_SCHEMES else ("(없음)" if not parts.scheme else "(알 수 없는 종류)")
        raise _invalid(key, "https:// 로 시작하는 주소여야 합니다", detail=f"https 가 아닌 주소의 종류: {scheme}")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise _invalid(key, "주소에 로그인 정보(사용자:비밀번호@)가 들어 있습니다")
    problem = _host_problem(host)
    if problem:
        raise _invalid(key, problem)
    if _has_key_shape(text):                                                    # 이름과 상관없이 키 모양이 들어 있다(경로·인자·조각 어디든)
        raise _invalid(key, _URL_SHAPE_REASON, detail="키 모양의 글이 들어 있다(값은 적지 않는다)")
    if port is not None and not 1 <= port <= 65535:
        raise _invalid(key, "포트 번호가 올바르지 않습니다")
    for form in _forms(text):                                                   # 글 그대로와 퍼센트를 푼 글 둘 다 — `token%3D…` 처럼 `=` 까지 퍼센트로 쓴 것도 읽는다
        for name, argument in _params(form):                                    # `?token=…`·`#access_token=…`·`;token=…` — 이름이 비밀 이름이고 값도 비밀로 보일 때만
            if _secret_name(name) and _secret_value(argument):
                raise _invalid(key, _URL_PARAM_REASON, detail="비밀 인자가 들어 있다(인자 이름·값은 적지 않는다)")
    return text


def _params(text):
    """주소의 `이름=값` 조각들 — `?`·`&`·`;`·`#` 로 끊은 덩어리마다(조각 안의 `?` 인자와 경로에 `;` 로 단 인자도 포함)."""
    for chunk in re.split("[?&;#]", text.split("://", 1)[-1]):
        if "=" in chunk:
            name, _equal, argument = chunk.partition("=")
            yield name.rsplit("/", 1)[-1], argument


def _secret_value(argument):
    """비밀 인자의 값이 비밀로 보이는가 — 비었거나 숫자뿐이거나 16자 미만이면 상태 번호·짧은 설정 값이라 통과, 숫자뿐이 아닌 16자 이상이면 비밀이다(키 모양은 주소 어디에 있든 따로 거절한다)."""
    plain = unquote(argument).strip()
    return not plain.isdigit() and len(plain) >= 16


def _secret_name(name):
    """주소 인자 이름이 비밀 값을 나르는 이름인가 — 대소문자·`-`·`_`·`.`·공백을 무시하고 비밀 낱말을 품은 이름, 또는 모호한 낱말(`sid`·`ticket`·`code` …)과 정확히 같은 이름.
    퍼센트로 쓴 이름은 호출하는 쪽이 `_forms` 로 풀어서 넘긴다."""
    plain = "".join(ch for ch in name.casefold() if ch not in "-_. " + chr(9))
    return plain in _SECRET_NAME_SAME or any(part in plain for part in _SECRET_NAME_PARTS)


def _url_key(text):
    """같은 주소인지 가리는 모양 — 방식과 사이트 이름만 대소문자를 무시하고 경로·인자는 구분한다."""
    parts = urlsplit(text)
    return (parts.scheme.casefold(), parts.netloc.casefold(), parts.path, parts.query, parts.fragment)


def _urls(values):
    if isinstance(values, str):
        values = (values,)
    if not isinstance(values, (list, tuple)):
        raise _invalid("urls", "주소의 목록이어야 합니다", detail=f"{type(values).__name__} 은 받지 않는다")
    if len(values) > RAW_ITEMS:
        raise _invalid("urls", f"항목이 너무 많습니다(한 칸에 {RAW_ITEMS}개까지)")
    found, seen = [], set()
    for item in values:
        text = _url(item)
        if text and _url_key(text) not in seen:
            seen.add(_url_key(text))
            found.append(text)
    if len(found) > MAX_URLS:
        raise _invalid("urls", f"{MAX_URLS}개까지 쓸 수 있습니다(지금 {len(found)}개)")
    return tuple(found)


def _length(value):
    if value is None or value == "":
        return None
    if isinstance(value, LengthWish):
        return value
    if isinstance(value, str):
        return parse_length(value)
    raise _invalid("length", "1500-2000(범위)이나 2500+(이상) 모양이어야 합니다", detail=f"{type(value).__name__} 은 받지 않는다")


class _DuplicateKey(ValueError):
    """JSON 객체에 같은 키가 두 번 있다."""


def _no_duplicate_keys(pairs):
    """`json.loads(object_pairs_hook=…)` — 같은 키가 두 번 나오면 마지막 값으로 덮어쓰지 않고 거절한다."""
    found = {}
    for name, value in pairs:
        if name in found:
            raise _DuplicateKey()
        found[name] = value
    return found


@dataclass(frozen=True)
class DraftOptions:
    message: str = ""                          # 직접 전달하고 싶은 내용
    experience: str = ""                       # 실제 사용 경험(방문·체험 포함) — 이것이 있어야 경험 단락이 들어간다
    opinion: str = ""                          # 개인 의견
    must_include: tuple = ()                   # 반드시 포함할 문장들
    exclude: tuple = ()                        # 제외할 내용(낱말·구)
    audience: str = ""                         # 특정 독자층
    length: object = None                      # 원하는 글 길이(LengthWish — 문자열로 줘도 된다)
    title_direction: str = ""                  # 원하는 제목 방향
    urls: tuple = ()                           # 참고 URL(https 공개 주소 — 열지도 가져오지도 않는다)
    price_date: tuple = ()                     # 사용자가 확인한 실제 가격이나 날짜
    conclusion: str = ""                       # 최종 결론

    def __post_init__(self):
        def put(name, value):
            object.__setattr__(self, name, value)

        for name, high in (("message", MAX_MESSAGE), ("experience", MAX_EXPERIENCE), ("opinion", MAX_OPINION), ("audience", MAX_AUDIENCE), ("title_direction", MAX_TITLE_DIRECTION),
                           ("conclusion", MAX_CONCLUSION)):
            put(name, _text(getattr(self, name), name, high))
        put("must_include", _texts(self.must_include, "must_include", count=MAX_MUST_INCLUDE, high=MAX_SENTENCE))
        put("exclude", _texts(self.exclude, "exclude", count=MAX_EXCLUDE, high=MAX_EXCLUDE_WORD))
        put("price_date", _texts(self.price_date, "price_date", count=MAX_PRICE_DATE, high=MAX_PRICE_DATE_ITEM))
        put("urls", _urls(self.urls))
        put("length", _length(self.length))

    # ---- 읽기 ------------------------------------------------------------------------------------------------------------
    def is_empty(self):
        """아무 칸도 적지 않았는가 — 그래도 계획은 만들어진다."""
        return not any(getattr(self, name) for name in KEYS)

    @property
    def has_experience(self):
        return bool(self.experience)

    def user_texts(self):
        """사용자가 적은 모든 글(제외할 내용 포함, 참고 URL 은 뺀다) — 문장 검사에서 사용자 글을 가려내는 데 쓴다."""
        singles = (self.message, self.experience, self.opinion, self.audience, self.title_direction, self.conclusion)
        return tuple(item for item in (*singles, *self.must_include, *self.exclude, *self.price_date) if item)

    # ---- JSON ------------------------------------------------------------------------------------------------------------
    def to_dict(self):
        return {
            "schema": SCHEMA, "message": self.message, "experience": self.experience, "opinion": self.opinion, "must_include": list(self.must_include), "exclude": list(self.exclude),
            "audience": self.audience, "length": None if self.length is None else self.length.text(), "title_direction": self.title_direction, "urls": list(self.urls),
            "price_date": list(self.price_date), "conclusion": self.conclusion,
        }

    @classmethod
    def from_dict(cls, data):
        """저장된 모양을 엄격하게 읽는다 — 모르는 키·어긋난 값은 DRAFT_OPTION_INVALID. 빠진 키는 비어 있는 것이다(`schema` 는 있다면 1 이어야 한다)."""
        if not isinstance(data, dict):
            raise _invalid("선택 입력", "JSON 객체({ … })여야 합니다", detail="객체가 아니다")
        unknown = [name for name in data if name not in KEYS and name != "schema"]
        if unknown:
            raise _invalid("선택 입력", f"모르는 키가 {len(unknown)}개 있습니다(쓸 수 있는 키: {', '.join(KEYS)})", detail=f"모르는 키 {len(unknown)}개(키 이름은 적지 않는다)")
        if "schema" in data and (type(data["schema"]) is not int or data["schema"] != SCHEMA):
            raise _invalid("선택 입력", f"저장 형식(schema {SCHEMA})이 아닙니다")
        return cls(**{name: value for name, value in data.items() if name != "schema"})

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, text):
        try:
            data = json.loads(text, object_pairs_hook=_no_duplicate_keys)
        except _DuplicateKey:
            raise _invalid("선택 입력", "같은 키가 두 번 이상 있습니다", detail="JSON 에 같은 키가 중복되어 있다(키 이름은 적지 않는다)") from None
        except RecursionError:
            raise _invalid("선택 입력", "JSON 이 너무 깊게 겹쳐 있습니다", detail="JSON 중첩이 너무 깊다") from None
        except (TypeError, ValueError):
            raise _invalid("선택 입력", "JSON 글이 아닙니다", detail="JSON 으로 읽을 수 없다") from None
        return cls.from_dict(data)


__all__ = ["DraftOptions", "KEYS", "LABELS", "LengthWish", "MAX_LENGTH", "MIN_LENGTH", "parse_length", "squash"]
