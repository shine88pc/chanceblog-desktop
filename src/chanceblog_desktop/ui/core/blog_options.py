"""블로그 관리 화면의 '보기' 목록과 제안 문장(순수 규칙) — 사용자가 낱말을 직접 떠올려 쳐 넣지 않고 **프로그램이 제안한 보기에서 고르게** 하려는 값들이다.

모든 보기는 이 앱이 이미 가진 목록에서 오거나(주제 묶음 이름 `topics/wording.CLUSTER_KO`·협찬 분야 이름 `TAG_KO`·글 유형 `content/profiles.POST_TYPES`) 이 파일에 짧게 적은 고정 낱말이다 — 파일·네트워크·AI 를 부르지 않고 시계·난수도 쓰지 않는다.
저장하는 값은 **기존과 같은 글**이다(서비스가 읽는 칸·한도·검사 그대로): 보기를 고르는 것은 그 글을 대신 넣어 주는 일일 뿐이어서 엔진·후보·초안은 달라지지 않는다. 보기 밖의 글(기존 파일에 손으로 쓴 값)은 지우지 않고 그대로 보여 준다.
이 파일에는 실제 블로그 이름·아이디·주소가 없다. 제안 문장은 화면에서 고른 값으로만 만들고, 사용자가 고쳐 저장한다.
"""
from __future__ import annotations

from types import MappingProxyType

from ...content.profiles import POST_TYPES, find_markup
from ...topics import channels as ch
from ...topics import wording


def _unique(*groups):
    """여러 묶음을 이어 붙이되 같은 낱말(대소문자 구분 없이)은 처음 하나만 둔다."""
    seen, out = set(), []
    for group in groups:
        for word in group:
            if word.casefold() not in seen:
                seen.add(word.casefold())
                out.append(word)
    return tuple(out)


# ---- 한 줄 칸의 보기(하나만 고르거나 '직접 입력') ------------------------------------------------------------------------------------------
ROLE_CHOICES = ("정보 공유", "후기 기록", "제품 비교", "브랜드 소개", "일상 기록")
AUDIENCE_CHOICES = ("20–30대 직장인", "대학생", "주부", "여행자", "개발 입문자", "자영업자")
TONE_CHOICES = ("친근한 말투", "정중한 설명체", "간결한 정보체", "생생한 후기체")
LINE_CHOICES = MappingProxyType({"channel_role": ROLE_CHOICES, "audience": AUDIENCE_CHOICES, "tone": TONE_CHOICES})

# ---- 낱말 칸의 제안(여러 개 고르는 칩 + 직접 추가) ----------------------------------------------------------------------------------------
TOPIC_WORDS = _unique(wording.CLUSTER_KO.values())                    # 주제 묶음 이름 — 이 앱이 후보를 만들 수 있는 주제의 이름이다
SPONSOR_WORDS = _unique(wording.TAG_KO.values())                      # 협찬 가능 분야 이름
KEYWORD_WORDS = _unique(TOPIC_WORDS, SPONSOR_WORDS)                   # 우선·제외 키워드의 제안
CATEGORY_WORDS = _unique(SPONSOR_WORDS, POST_TYPES)                   # 카테고리의 제안 — 분야 이름과 글 유형 이름
WORD_SUGGESTIONS = MappingProxyType({"main_topics": TOPIC_WORDS, "categories": CATEGORY_WORDS, "priority_keywords": KEYWORD_WORDS, "exclude_keywords": KEYWORD_WORDS})

TOPIC_PICK = 3                                                        # 소개글 제안에 쓰는 주제 낱말의 수


# ---- 소개글 제안 ----------------------------------------------------------------------------------------------------------------------
def _usable(text):
    """제안 문장에 넣어도 되는 글 조각인가 — 비어 있지 않고 위험한 표기(꺾쇠 태그·스크립트·템플릿)가 없다."""
    return bool(text) and not find_markup(text)


def suggest_intro(role="", audience="", tone="", topics=()):
    """고른 값으로 만든 소개글 제안 한 문장 묶음(없으면 빈 글). 모두 비어 있으면 빈 글이고, 모양은 늘 같은 틀이다 — 낱말에 붙는 조사(을·를·으로)를 가릴 필요가 없는 틀만 쓴다:
    ① `{주제 앞 셋} 이야기를 담아요.` ② `{독자}에게 도움이 되는 {역할} 블로그예요.`(독자나 역할 중 하나뿐이면 그 한쪽만) ③ `‘{문체}’ 느낌으로 읽기 편하게 써요.`
    위험한 표기가 든 조각은 빼고, 전체가 소개글 상한(`MAX_INTRO`)을 넘으면 뒤의 문장부터 뺀다 — 하나도 남지 않으면 빈 글."""
    role, audience, tone = (item if isinstance(item, str) else "" for item in (role, audience, tone))
    words = tuple(word for word in (topics or ()) if isinstance(word, str) and _usable(word))[:TOPIC_PICK]
    role, audience, tone = (item if _usable(item) else "" for item in (role, audience, tone))
    sentences = []
    if words:
        sentences.append(f"{'·'.join(words)} 이야기를 담아요.")
    if audience and role:
        sentences.append(f"{audience}에게 도움이 되는 {role} 블로그예요.")
    elif audience:
        sentences.append(f"{audience}에게 도움이 되는 글을 써요.")
    elif role:
        sentences.append(f"{role} 블로그예요.")
    if tone:
        sentences.append(f"‘{tone}’ 느낌으로 읽기 편하게 써요.")
    while sentences and len(" ".join(sentences)) > ch.MAX_INTRO:
        sentences.pop()
    return " ".join(sentences)
