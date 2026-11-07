"""본문 문단 틀 모음 — 글 유형 5종의 소제목 단계별 틀(`body_lib_*.py`)과 어느 단계를 어떤 순서로 쓰는지(순수 자료).

소제목은 `post_types.TEMPLATES`·`EXTRA_STEPS` 의 단계 하나가 하나다(`draft plan` 처럼 `키워드: 단계, 단계` 로 묶지 않는다 — 소제목 글은 그 단계의 `heads` 를 그대로 쓴다).
· 소제목이 되는 단계(`BODY_STEPS`): 정보형 5(독자가 궁금해하는 문제·핵심 개념·확인할 기준·활용 방법·점검표) · 비교형 5 · 문제 해결형 6 · 제품·서비스 소개형 5 · 장소·업체 정보형 6.
· 틀의 '주의사항'(정보형)과 '정리' 단계(정보형·비교형·제품·서비스 소개형)는 소제목이 아니라 **주의사항 블록·마무리 블록**이 맡는다 — 제목은 그 단계의 `heads` 를 쓴다.
· 사용자의 실제 경험이 입력되면 `EXPERIENCE_STEPS` 의 단계가 마무리 앞에 더해진다(문단은 사용자 글뿐). 소제목이 6개를 넘지 않게 문제 해결형·장소·업체 정보형은 마지막 단계(`DROPPED_FOR_EXPERIENCE`)를 뺀다.
"""
from __future__ import annotations

from . import body_lib_compare, body_lib_info, body_lib_place, body_lib_product, body_lib_trouble
from . import post_types as pt

LIBRARY = {pt.INFO: body_lib_info.SECTIONS, pt.COMPARE: body_lib_compare.SECTIONS, pt.TROUBLE: body_lib_trouble.SECTIONS, pt.PRODUCT: body_lib_product.SECTIONS, pt.PLACE: body_lib_place.SECTIONS}
BODY_STEPS = {
    pt.INFO: ("problem", "concept", "criteria", "usage", "checklist"),
    pt.COMPARE: ("purpose", "basis", "features", "pros", "choice"),
    pt.TROUBLE: ("symptom", "cause", "order", "fix", "prevent", "extra"),
    pt.PRODUCT: ("overview", "features", "fit", "before", "pros"),
    pt.PLACE: ("overview", "info", "before", "menu", "purpose", "official"),
}
DROPPED_FOR_EXPERIENCE = {pt.TROUBLE: "extra", pt.PLACE: "official"}
MAX_SECTIONS = 6
MIN_SECTIONS = 4


def step_of(post_type, key):
    """글 유형 틀(`TEMPLATES`)이나 더하는 단계(`EXTRA_STEPS`)에서 그 열쇠의 `Step`."""
    for step in (*pt.TEMPLATES[post_type], *pt.EXTRA_STEPS):
        if step.key == key:
            return step
    raise KeyError(key)


def caution_step():
    """주의사항 블록의 제목이 되는 단계 — 정보형 틀의 '주의사항' 이다(다른 글 유형도 같은 제목을 쓴다)."""
    return step_of(pt.INFO, "caution")


def closing_step(post_type):
    """마무리 블록의 제목이 되는 단계 — 그 글 유형 틀의 마지막 '정리' 단계(없으면 정보형의 '핵심 정리')."""
    steps = pt.TEMPLATES[post_type]
    return steps[-1] if steps[-1].key == "summary" else step_of(pt.INFO, "summary")


def section_texts(post_type, key):
    """그 단계의 문단 틀들(셋)."""
    return LIBRARY[post_type][key]


__all__ = ["BODY_STEPS", "DROPPED_FOR_EXPERIENCE", "LIBRARY", "MAX_SECTIONS", "MIN_SECTIONS", "caution_step", "closing_step", "section_texts", "step_of"]
