"""콘솔 출력 안전장치.

Windows 한국어 콘솔(cp949)은 '—'·이모지 같은 문자를 표현하지 못해, 그런 문자를 print 하면 CLI가 예외로 멈춘다
(CI의 Linux는 UTF-8이라 드러나지 않는다). CLI 진입점(main) 첫 줄에서 safe_output() 을 부르면
표현할 수 없는 문자만 '?'로 바뀌고 한글은 그대로 출력된다.

로그·Actions 실행 요약에 외부에서 온 문자열(LLM 글 제목, 피드에서 온 다른 블로그 이력 제목, API 오류 문구)을
넣을 때는 one_line()·md_cell() 을 거친다. 개행이나 단독 CR 로 새 줄을 시작해 '::error::' 같은 워크플로 명령을
흉내 내거나 요약 문서에 제목·링크·표를 끼워 넣는 것을 막는다(docs/SECURITY_GUARDRAILS.md G-L2).
"""
import re
import sys
import unicodedata

# 마크다운 문법 문자 → 무해한 표기(실행 요약은 마크다운으로 렌더링된다). 백틱은 코드 스팬을 여는 문자라 작은따옴표로 바꾼다.
_MD_SAFE = (("|", "&#124;"), ("`", "'"), ("<", "&lt;"), (">", "&gt;"), ("[", "&#91;"), ("]", "&#93;"))

# 글자 순서를 뒤집거나 보이지 않게 만드는 문자(소프트 하이픈·폭 없는 공백·방향 제어·단어 결합자·BOM). 알림 글 소독(pipeline/notify.py)과 시크릿 값 정리(clean_secret)가
# 같은 목록을 쓰도록 한 곳에 둔다(순환 임포트를 피하려고 notify 가 아니라 여기). 소스에는 보이지 않는 문자를 넣지 않으려고 코드 포인트로 쓴다.
INVISIBLE_CODEPOINTS = (0x00AD, *range(0x200B, 0x2010), *range(0x202A, 0x202F), *range(0x2060, 0x2065), *range(0x2066, 0x206A), 0xFEFF)
INVISIBLE_RE = re.compile("[" + "".join(chr(code) for code in INVISIBLE_CODEPOINTS) + "]")
_INVISIBLE_SET = frozenset(chr(code) for code in INVISIBLE_CODEPOINTS)
_REMOVED_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})      # 제어 문자·서식 문자(공유 목록의 문자도 모두 여기에 든다)·짝 없는 서로게이트


def one_line(text, limit=300):
    """외부 유래 문자열을 로그에 넣을 한 줄로 접는다(길이는 limit 이하, 줄이면 끝에 '…').

    - 줄을 바꾸는 모든 문자(개행·단독 CR·U+2028·U+2029·U+0085·탭)와 그 밖의 제어 문자는 공백으로 바꾸고 연속 공백은 하나로 줄인다.
    - 워크플로 명령 표기 '::' 와 로그 서식 표기 '##[' 는 어디에 있든 풀어 놓는다. Actions 러너는 줄 맨 앞(앞 공백은 무시)의
      '::' 를 명령으로 읽으므로, 앞에 공백을 붙이는 것으로는 막을 수 없다.
    """
    raw = "" if text is None else str(text)
    spaced = "".join(" " if unicodedata.category(ch) == "Cc" else ch for ch in raw)
    folded = " ".join(spaced.split())
    folded = re.sub(r":(?=:)", ": ", folded).replace("##[", "# [")
    if len(folded) > limit:
        folded = folded[:max(limit - 1, 0)].rstrip() + "…"
    return folded


def md_cell(text, limit=120):
    """마크다운(실행 요약의 목록·표)에 안전하게 넣을 한 줄 텍스트. one_line() 에 더해 표·링크·HTML·코드 문법 문자를 바꾼다."""
    folded = one_line(text, limit)
    for char, safe in _MD_SAFE:
        folded = folded.replace(char, safe)
    return folded


def clean_secret(value):
    """시크릿 값을 쓸 수 있는 모양으로 정리한다: 보이지 않는 문자(INVISIBLE_CODEPOINTS)·제어 문자·서식 문자를 어디에 있든 지우고 앞뒤 공백을 자른다.

    채팅 앱·문서에서 복사해 붙여 넣은 값에는 폭 없는 공백(U+200B)·단어 결합자(U+2060)·BOM(U+FEFF) 같은 문자가 섞이기 쉽다. 눈에 보이지 않고 `str.strip()` 도 못 지워
    인증이 설명 없이 어긋난다(이슈 #58). 값 가운데의 보통 공백은 건드리지 않는다(시크릿에는 공백이 없어 그런 값은 원래도 인증이 실패해 드러난다).
    보이지 않는 문자가 없는 값은 `value.strip()` 과 똑같이 돌려준다(예전 동작과 같다)."""
    raw = "" if value is None else str(value)
    return "".join(ch for ch in raw if ch not in _INVISIBLE_SET and unicodedata.category(ch) not in _REMOVED_CATEGORIES).strip()


def secret_was_cleaned(value):
    """clean_secret 이 앞뒤 공백 자르기(예전 동작) 말고 보이지 않는 문자·제어 문자를 더 지웠는가. 시크릿을 다시 등록하라고 알릴 때 쓴다(값은 출력하지 않는다)."""
    raw = "" if value is None else str(value)
    return clean_secret(raw) != raw.strip()


def safe_output():
    """stdout/stderr 가 인코딩하지 못하는 문자를 예외 대신 '?'로 대체하도록 바꾼다(되돌릴 필요 없음)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)  # StringIO·캡처 스트림에는 없다
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass
