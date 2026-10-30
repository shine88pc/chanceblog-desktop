"""비밀 값으로 보이는 문자열 패턴(단일 원천).

저장소 검증기(scripts/validate_repo.py), 이슈 수정 사후 검증(pipeline/edits/checks.py),
이슈 수정의 로그 정제·외부 전송 전 점검(pipeline/edits/safety.py),
로그·이력 마스킹(pipeline/llm.py 의 mask())이 함께 쓴다. 패턴을 추가·수정하면 모두에 적용된다.
(소비처 목록은 tests/test_security_settings.py 가 실제 import 와 대조한다.)
"""
import re

SECRET_PATTERNS = [
    ("Google API 키", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    # 2026-10-18 공개 이력에 남았던 123.txt(D-30)의 형식: 점이 든 접두사 'AQ.' + 영숫자·-·_ 40자 이상(총 53자 안팎).
    # 앞 글자가 영문자·숫자면 제외한다(FAQ. 같은 단어 끝). 단어 경계(\b) 대신 look-behind 를 쓴다: \b 는
    # 한글·밑줄 바로 뒤에 붙은 키('키는AQ.…')를 놓친다.
    ("Google API 키(새 형식)", re.compile(r"(?<![A-Za-z0-9])AQ\.[0-9A-Za-z_\-]{40,}")),
    ("Google OAuth 클라이언트 시크릿", re.compile(r"GOCSPX-[0-9A-Za-z_\-]{20,}")),
    ("Google refresh token", re.compile(r"\b1//0[0-9A-Za-z_\-]{40,}")),
    ("Google access token", re.compile(r"\bya29\.[0-9A-Za-z_\-]{30,}")),
    ("GitHub 토큰", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,}")),
    ("GitHub PAT", re.compile(r"\bgithub_pat_[0-9A-Za-z_]{40,}")),
    ("개인 키 블록", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----")),
    ("Slack 토큰", re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}")),
    ("AWS 액세스 키", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # 텔레그램 봇 토큰: '<봇 번호 숫자>:<영숫자·-·_ 35자>'(실제 8~10자리·35자, 여유를 둬 6~12자리·30~50자). 이 서비스는 토큰이 요청 주소의 경로
    # (https://api.telegram.org/bot<토큰>/sendMessage)에 들어가 오류 문구·스택트레이스에 주소째 새기 쉽다 — 알림 모듈(pipeline/notify.py)이
    # 정확한 값 치환에 더해 이 모양으로도 한 번 더 가린다(docs/SECURITY_GUARDRAILS.md G-C12). 앞에는 제한이 없다 — 주소 경로에서는 'bot' 글자 바로 뒤에 붙는다
    # (…/bot<토큰>/…). 비밀 절반 뒤에 영숫자·-·_ 가 더 이어지면 토큰이 아니라 다른 긴 문자열이라 제외한다.
    ("Telegram 봇 토큰", re.compile(r"[0-9]{6,12}:[A-Za-z0-9_\-]{30,50}(?![A-Za-z0-9_\-])")),
    ("sk- 형식 API 키", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    # 값이 환경변수 이름(대문자_숫자_밑줄)이면 시크릿이 아니라 레지스트리의 '이름 매핑'이다
    ("client_secret JSON 값", re.compile(r'"client_secret"\s*:\s*"(?![A-Z][A-Z0-9_]*")[^"]{8,}"')),
    ("키/토큰 할당", re.compile(r"""(?i)\b(?:api[_-]?key|secret|token|passwd|password)\b\s*[:=]\s*['"][A-Za-z0-9_\-/+=]{24,}['"]""")),
]


def find_secrets(text):
    """text 안에서 비밀로 보이는 값의 (라벨, 마스킹된 미리보기) 목록. 값 전체는 돌려주지 않는다."""
    found = []
    for label, rx in SECRET_PATTERNS:
        match = rx.search(text or "")
        if match:
            found.append((label, match.group(0)[:4] + "***"))
    return found
