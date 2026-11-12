"""본문 속 Secret 형태 검사기(`security/scan.py`) 시험의 표본과 보조 함수 — 키 모양은 실행할 때 조각을 이어 붙여 만든다(저장소의 시험이 `.py`·`.md` 안의 완성된 키 모양 글을 막는다).
시험 파일이 아니라 도구 모음이다(이름이 `test` 로 시작하지 않는다). 네트워크·실제 비밀 없이 쓴다.

표본의 '몸'은 고정된 계산으로 만든다(같은 입력은 같은 글) — 영문·숫자·밑줄·붙임표가 골고루 들어가서 정규식의 글자 모음 한 곳만 바뀌어도 어느 시험에서 걸린다.
"""
import string

ALNUM = string.ascii_letters + string.digits
UPPER_DIGITS = string.ascii_uppercase + string.digits
B64URL = ALNUM + "_-"
TILDE = chr(126)                  # 물결표는 글자로 적지 않는다(문서·주석에 물결표를 두지 않는 규칙)
BEARER_CHARS = ALNUM + "._-+/" + TILDE

KINDS = ("google_api_key", "github_token", "bearer_token", "oauth_token", "aws_access_key", "pem_private_key")


def body(length, alphabet=ALNUM, shift=0):
    """고정된 계산으로 만든 `length` 글자(알파벳 전체를 돈다 — 7 은 62·64 와 서로소다)."""
    return "".join(alphabet[(index * 7 + shift) % len(alphabet)] for index in range(length))


def google(length=35, shift=3):
    return "AI" + "za" + body(length, B64URL, shift)


def github(letter="p", length=36, shift=5):
    return "gh" + letter + "_" + body(length, ALNUM, shift)


def github_pat(length=22, shift=11):
    return "github_" + "pat_" + body(length, ALNUM + "_", shift)


def bearer_value(length=30, shift=2):
    """Bearer 값 표본 — 마지막 글자는 영문·숫자다(값 끝의 점은 문장 부호로 보고 발견 자리에서 뺀다)."""
    return body(length - 1, BEARER_CHARS, shift) + "k"


def bearer(length=30, sep=" ", word="Bearer", shift=2):
    return word + sep + bearer_value(length, shift)


def ya29(length=30, shift=1):
    return "ya" + "29." + body(length, B64URL, shift)


def refresh(length=30, shift=9):
    return "1/" + "/" + body(length, B64URL, shift)


def gocspx(length=28, shift=7):
    return "GOC" + "SPX-" + body(length, B64URL, shift)


def jwt(head=36, payload=24, signature=30):
    """JWT 모양 세 덩어리 — `head`·`payload` 는 머리 `eyJ` 뒤의 글자 수, `signature` 는 서명 글자 수."""
    return "eyJ" + body(head, B64URL, 1) + "." + "eyJ" + body(payload, B64URL, 4) + "." + body(signature, B64URL, 6)


def named(name="access_token", value=None, sep="=", quote=""):
    value = body(30, B64URL, 8) if value is None else value
    return name + sep + quote + value + quote


def aws(prefix="AKIA", length=16, shift=4):
    return prefix + body(length, UPPER_DIGITS, shift)


def pem(kind="RSA "):
    return "-----" + "BEGIN " + kind + "PRIVATE KEY" + "-----"


# 유형 → (표본을 만드는 함수, 발견 글 전체 — 표본이 곧 발견 자리다)
FACTORIES = {
    "google_api_key": google,
    "github_token": github,
    "bearer_token": bearer_value,           # 발견 자리는 값뿐이라 값만 표본으로 쓴다(앞에 `bearer(...)` 낱말을 붙여 쓴다)
    "oauth_token": ya29,
    "aws_access_key": aws,
    "pem_private_key": pem,
}


def sample(kind):
    """유형 하나의 대표 표본 `(발견 자리의 글, 그 글을 담은 한 줄)` — 줄은 낱말을 앞에 붙인 모양이다."""
    token = FACTORIES[kind]()
    lead = {"bearer_token": "Authorization: Bearer ", "google_api_key": "key=", "github_token": "token: ", "oauth_token": "ya29 = ", "aws_access_key": "id ", "pem_private_key": ""}[kind]
    return token, lead + token


def locate(text, token, start=0):
    """`token` 이 `text` 에서 처음 나오는 자리(`start` 이후)의 `(줄, 시작 열, 끝 열)` — 검사기와 따로 센다(CRLF·LF·CR 을 줄바꿈 하나로)."""
    index = text.index(token, start)
    before = text[:index].replace("\r\n", "\n").replace("\r", "\n")
    line = before.count("\n") + 1
    col_start = len(before) - before.rfind("\n")                 # 줄바꿈이 없으면 rfind 가 -1 이라 길이 + 1
    return line, col_start, col_start + len(token) - 1


def position(text, offset):
    """글 안의 글자 위치 `offset`(0부터)의 `(줄, 열)`(둘 다 1부터) — 검사기와 따로 센다(CRLF·LF·CR 을 줄바꿈 하나로). `offset` 은 줄바꿈 한가운데가 아니어야 한다."""
    before = text[:offset].replace("\r\n", "\n").replace("\r", "\n")
    return before.count("\n") + 1, len(before) - before.rfind("\n")


def triples(findings):
    return [(item.kind, item.line, item.col_start, item.col_end) for item in findings]


def leaked(haystack, token, size=4):
    """`haystack` 에 `token` 의 연속한 `size` 글자가 하나라도 들어 있으면 True — 실패 출력에 토큰을 찍지 않으려고 불리언만 돌려준다."""
    return any(token[index:index + size] in haystack for index in range(len(token) - size + 1))
