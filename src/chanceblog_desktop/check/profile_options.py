"""네이버 블로그 프로필의 '글 만들 때 쓰는 항목' 중 **점검에 쓰이는 것**(소제목 수 범위·제외 주제)을 글에 비춰 보고 경고를 만든다(docs/ARCHITECTURE.md §5 `check/`).

경고만 하고 막지 않는다 — 복사 패키지의 다른 경고(금지 표현·글 길이 …)와 같은 길(`NaverPackage.warnings`)로 미리 보기·검토·복사용 글의 `[주의]` 에 함께 나온다.
도입부 스타일·설명 난이도·마무리 방식·기본 글 유형은 **저장만** 한다(초안을 쓰는 단계에서 읽는다) — 여기서는 보지 않는다. 같은 주제 재사용 기준(`topic_reuse_days`)은 후보를 고를 때 쓴다(`service/candidates.py`).
`render/naver.py` 의 `build_package`(글을 복사 패키지로 바꾸는 순수 변환)는 이 항목을 읽지 않는다 — 그것을 바꾸지 않고 서비스 층(`service/naver_flow.py`)이 변환 결과의 경고에 이 경고를 덧붙인다.
네트워크·파일은 쓰지 않는다.
"""
from __future__ import annotations

import re
import unicodedata

_HEADING = re.compile(r"<h[2-4]>")                 # 정화한 본문 HTML 의 소제목(`#`~`####` 제목 줄은 h2~h4 가 된다)


def subheading_count(body_html):
    """복사 패키지 본문(허용 태그만 있는 HTML)의 소제목 수 — 제목 줄(`#`~`####`) 하나가 하나다."""
    return len(_HEADING.findall(body_html))


def _squash(text):
    """비교하는 모양 — 호환 문자(전각 `ＡＩ`·전각 숫자 …)를 풀고(NFKC) 모든 공백을 없애고 소문자로 한다. 그래서 '가상 자산' 과 '가상자산', 'AI' 와 'ＡＩ' 를 같은 낱말로 본다
    (경고일 뿐이라 낱말 사이가 붙어 우연히 맞는 드문 경우보다 놓치는 쪽이 더 나쁘다)."""
    return "".join(unicodedata.normalize("NFKC", str(text)).split()).casefold()


def option_warnings(profile, package):
    """프로필의 소제목 수 범위·제외 주제를 `package`(NaverPackage)에 비춰 본 경고 문장들(없으면 빈 튜플)."""
    warnings = []
    count = subheading_count(package.body_html)
    low, high = profile.subheading_min, profile.subheading_max
    if count < low or count > high:
        span = f"{low}개" if low == high else f"{low}~{high}개"
        warnings.append(f"소제목이 {count}개입니다 — 이 블로그의 기준({span})보다 {'적습니다' if count < low else '많습니다'}.")
    title, body = _squash(package.title), _squash(package.core_text)
    for topic in profile.excluded_topics:
        wanted = _squash(topic)
        for where, text in (("제목", title), ("본문", body)):
            if wanted in text:
                warnings.append(f"제외 주제 「{topic}」 이(가) {where}에 있습니다 — 이 블로그에서 다루지 않기로 한 주제입니다.")
    return tuple(warnings)


__all__ = ["option_warnings", "subheading_count"]
