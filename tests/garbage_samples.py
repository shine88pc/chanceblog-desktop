"""'글 모양 점검'(N-2) 시험이 함께 쓰는 예문 도구(시험 모듈이 아니다). 모두 지어낸 글이고 실제 블로그·후보·글이 아니다. 눈에 안 보이는 글자·제어 문자·물결 글자는 소스에 날것으로 쓰지 않고 코드 숫자로 만든다.

  · 글자 이름 상수(`ZWSP`·`ESC`·`TILDE` …)와 글 만들기 도구(`lines`·`fenced` …)
  · `found(...)`·`kinds(...)`·`caught(...)` — 규칙 결과를 시험이 읽기 좋게 줄인다(걸린 글은 위치로 다시 잘라 본다 — 결과에는 걸린 글이 없다)
  · `NORMAL_TEXTS` — 정상으로 읽혀야 하는 글(걸림 0)
  · `mixed_bodies(count)` — 정상·가비지·키 모양·건강 단정·확인 권장이 섞인 같은 입력 `count` 개(복사 결과 차분 시험용, 늘 같은 글)
"""
import hashlib

ZWSP, ZWNJ, ZWJ, WJ, BOM, SHY, FILL, LRM, RLM = (chr(code) for code in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x3164, 0x200E, 0x200F))
VS16, VS15, TAG_BEGIN, TAG_G, TAG_CANCEL, BLACK_FLAG = (chr(code) for code in (0xFE0F, 0xFE0E, 0xE0001, 0xE0067, 0xE007F, 0x1F3F4))
FFFD, PUA, NONCHAR, SURROGATE, CARD = (chr(code) for code in (0xFFFD, 0xE0BC, 0xFFFF, 0xD800, 0x1F4D2))
NUL, ESC, FF, DEL, NEL, TAB = (chr(code) for code in (0x00, 0x1B, 0x0C, 0x7F, 0x85, 0x09))
TILDE, TICK, BACKSLASH = chr(0x7E), chr(0x60), chr(0x5C)
FAMILY = chr(0x1F468) + ZWJ + chr(0x1F469) + ZWJ + chr(0x1F467)
HEART = chr(0x2764) + VS16
KEYCAP = "1" + VS16 + chr(0x20E3)
FLAG_SCOTLAND = BLACK_FLAG + "".join(chr(code) for code in (0xE0067, 0xE0062, 0xE0073, 0xE0063, 0xE0074, 0xE007F))
PERSIAN = chr(0x0645) + ZWNJ + chr(0x06CC)
MOJIBAKE_KO = "가나다".encode("utf-8").decode("cp1252", "replace")                       # 한글을 윈도 글자표로 잘못 읽은 글
MOJIBAKE_ACCENT = "caf" + chr(0xC3) + chr(0xA9)                                          # é 가 깨진 꼴
MOJIBAKE_QUOTE = chr(0xE2) + chr(0x20AC) + chr(0x2122)                                   # 따옴표가 깨진 꼴
MOJIBAKE_FFFD = chr(0xEF) + chr(0xBF) + chr(0xBD)
NFD_HANGUL = "".join(chr(code) for code in (0x1112, 0x1161, 0x11AB, 0x1100, 0x1173, 0x11AF))      # 분리형 한글 '한글'
FULL_STOP, ELLIPSIS, IDEOGRAPHIC_STOP = ".", chr(0x2026), chr(0x3002)


def lines(*items):
    return "\n".join(items)


def fenced(*body, marker=TICK * 3, info=""):
    """코드 블록으로 감싼 글 — 열고 닫는 줄 사이에 `body` 줄들."""
    return "\n".join([marker + info, *body, marker])


def found(text, kind=None, *, title=""):
    """규칙의 결과(`Finding` 목록) — `kind` 를 주면 그 종류만."""
    from chanceblog_desktop.check import garbage
    return [finding for finding in garbage.scan(title, text).findings if kind is None or finding.kind == kind]


def kinds(text, *, title=""):
    """결과의 (종류, 하위 종류) 목록."""
    return [(finding.kind, finding.sub) for finding in found(text, title=title)]


def caught(text, finding, *, title=""):
    """한 건이 걸린 글들 — 위치(구간)로 원문을 다시 잘라 본다(규칙의 결과에는 걸린 글이 없다)."""
    return [(title if field == "title" else text)[start:end] for field, start, end in finding.spans]


def count(text, kind, *, title=""):
    return len(found(text, kind, title=title))


# ---- 정상으로 읽혀야 하는 글 — 걸림 0 (규칙의 오탐 점검) ----------------------------------------------------------------------------------------
NORMAL_TEXTS = (
    "오늘은 정말 좋은 날이에요. 날씨가 맑아서 산책을 다녀왔고, 점심에는 따뜻한 국수를 먹었어요.",
    "정말 정말 좋아요",                                                                 # 두 번 강조
    "두근두근 두근두근 설레요",                                                          # 의성어 두 번
    "ㅋㅋㅋ ㅋㅋㅋ ㅋㅋㅋ 너무 웃겨요 ㅠㅠ ㅠㅠ ㅠㅠ",                                          # 자모뿐인 어절
    "아 아 아 정말 놀랐어요",                                                             # 한 글자 어절
    "점수는 100 100 100 이었어요",                                                       # 숫자뿐인 어절
    "감사합니다.\n\n다음에 또 만나요.\n\n감사합니다.",                                       # 10글자 미만 문장
    "café와 señor, façade 에서 만났어요",                                               # 프랑스어·스페인어
    "5°C 4×4 ±3 © ® ½ □ 항목 ■ 항목 ▶ 시작 ✔ 완료",                                      # 기호
    "항목" + TAB + "값\r\n다음 줄\n표 복사본",                                             # 탭·윈도 줄바꿈
    "가족 " + FAMILY + " 사진 " + HEART + " 그리고 " + KEYCAP + " 번 " + FLAG_SCOTLAND,       # 이모지 이음·변형 선택자·깃발
    "페르시아 글자 " + PERSIAN + " 는 정상이에요",                                            # 폭 없는 비이음의 정상 쓰임
    "example.test/a?x=1&y=2&lang=ko 와 R&D, AT&T, Q&A 코너",                    # 세미콜론 없는 &
    "[리뷰] 아이폰 한 달 사용기 [광고] [이미지 1] OO병원에서 ○○ 씨를 만났어요",                # 말머리·이미지 자리·익명
    "HTML 에서 " + TICK + "&nbsp;" + TICK + " 는 공백을 뜻하고 템플릿은 " + TICK + "{{ title }}" + TICK + " 처럼 써요",    # 코드 조각 안
    "설명" + "\n" + TILDE * 3 + " 오늘의 일기 " + TILDE * 3 + "\n본문 좋아요" + TILDE * 3,      # 물결 장식 줄·끝의 물결
    "The quick brown fox jumps over the lazy dog. Dr. Kim said hello.",
    "She said that it was fine. He had enough of it.",
)


# ---- 문장부호·괄호·쉼표가 낱말 사이에 낀 같은 낱말(D-323) ---------------------------------------------------------------------------------------------
# 실제 글에서 같은 낱말 반복으로 오탐되던 **모양**을 지어낸 문장으로 옮긴 것이다(실제 글을 베끼지 않았다). 모두 걸림 0 이어야 하고, 사이의 부호를 뺀 같은 글은 같은 낱말 반복으로 걸린다(= 이 모음이 새 규칙을 실제로 시험한다).
PUNCTUATED_SHAPES = (
    "Logistics: Logistics of the new warehouse are described in this section.",                    # 낱말 콜론 반복
    "Statistics Bureau (SBX): [SBX releases quarterly tables]",                                      # 괄호 약어 + 콜론 + 대괄호 반복
    "References: ESO, [ESO Science Notes], ESO Press releases",                                     # 참고자료 줄(쉼표 + 대괄호)
    "Source: ZED. ZED operates the survey every spring.",                                           # 마침표 뒤 반복
    "Prepared by (WXYZ). WXYZ has not reviewed this guide.",                                        # 괄호 약어 뒤 마침표
    "Well, well, well, look who is here.",
    "Sure. Sure, I would go with you.",
    "It was really, really loud in the hall.",
    "No, no, no, that is not what I meant.",
    "Yes. Yes. Yes. We finally did it.",
    "**Staffing:** Staffing for the event is listed below.",                                        # 굵은 표시가 붙은 콜론 반복
    "Agency: Agency guidance applies to all branches.",
    "Notes: Notes are kept in the shared folder.",
    "Department (HRX): [HRX publishes the yearly plan]",
    "She said " + chr(0x22) + "no," + chr(0x22) + " no matter what happened.",                    # 따옴표 안 쉼표
    "- Alpha: Alpha team notes\n- Beta: Beta team notes",                                            # 목록 줄
    "wait" + ELLIPSIS + " wait" + ELLIPSIS + " wait for it",                                         # 말줄임표
    "알겠어요, 알겠어요, 알겠어요 정말이에요.",
    "아니요, 아니요, 아니요 괜찮아요.",
    "좋아요! 좋아요! 좋아요! 너무 좋아요.",
    "참고: 참고, 참고 자료는 아래에 있어요.",
    "(요약) 요약, 요약 내용은 다음과 같아요.",
)


# ---- 복사 결과 차분 시험용 — 정상·가비지·키 모양·건강 단정·확인 권장이 섞인 같은 입력 ----------------------------------------------------------------------
KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"                                         # 키 모양(가짜) — 복사 관문이 막는다
FRAGMENTS = {
    "normal": ("오늘은 정말 좋은 날이에요. 날씨가 맑아서 산책을 다녀왔어요.", "정리한 순서대로 천천히 확인해 보세요.", "비교할 때는 기준을 먼저 적어 두면 편해요.", "처음 쓰는 분도 쉽게 따라 할 수 있어요."),
    "garbage": ("안녕" + ZWSP + "하세요", "깨진 " + FFFD + " 글자", "{{이름}} 님께", "가격&nbsp;12,000원", "좋아요 좋아요 좋아요", "색깔 " + ESC + "[31m빨강", "[이름] 자리", fenced("코드 줄"), "ê°€ë‚˜ë‹¤ 깨짐",
                "사랑해요 영원히 변하지 않을 거예요.\n\n그날을 기억해요.\n\n사랑해요 영원히 변하지 않을 거예요."),
    "secret": ("키는 " + KEY_SHAPED + " 입니다", KEY_SHAPED),
    "health": ("영양제로 불면이 바로 치료됩니다", "당뇨 100% 보장"),
    "claims": ("직접 써 보니 정말 좋았습니다.", "가격은 12,000원이었어요.", "지난주에 직접 방문했습니다."),
}


def mixed_bodies(count):
    """같은 입력 `count` 개 — 앞 몇 개는 범주를 하나씩 돌려 가며 만들고 나머지는 정해진 씨앗의 무작위로 섞는다(늘 같은 글). 모든 범주가 여러 번 들어가므로 복사 결과가 막음·확인·복사로 고루 나뉜다."""
    import random
    rng = random.Random(20261110)
    names = list(FRAGMENTS)
    bodies = []
    for number in range(count):
        picked = []
        for _ in range(rng.randint(1, 4)):
            name = names[(number + len(picked)) % len(names)] if number < len(names) * 3 else rng.choice(names)
            picked.append(rng.choice(FRAGMENTS[name]))
        bodies.append("\n\n".join(picked) + f"\n\n{number + 1}번째 메모예요.")                # 번호를 붙여 모두 서로 다른 글이 되게 한다
    return bodies
