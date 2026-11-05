"""보류함의 만료일 — 점수 구간이 `HOLD`(50~64점)인 후보를 며칠까지 보관하는지 계산한다(순수 계산: 날짜·시각은 인자로 받고 시계를 읽지 않는다).

계획 문서 3.1 표의 `bands.py`('보류 만료일' 자리) 대신 이 파일에 둔다 — 구간 계산(`score.band_of`)은 P1 에서 `score.py` 로 들어갔고 여기에는 그 구간의 **보관 기한**만 있다(독립 검증 L8-①, 결정 D-43).
  · 만료일 = 평가한 시각 + `channels.HOLD_DAYS`(90일). 시각은 협정세계시(UTC) `YYYY-MM-DDTHH:MM:SSZ` 이고 후보의 `review_expires_at` 칸과 같은 모양이다.
  · 보류 구간이 아닌 후보(우선 추천·일반·제외·점수 없음)는 만료일이 없다(`None`) — '만료일 없음' 과 '지났다' 는 다르다.
  · 지났는가는 `now >= 만료일` 이다(만료 시각 정각이면 지난 것). 지났어도 이 함수들은 아무것도 지우거나 바꾸지 않는다 — '90일이 지나도 변화가 없으면 상세 후보는 정리하고 이력만 남긴다' 는 저장·서비스 단계의 일이고
    여기서는 '지났다' 는 표시만 돌려준다. 처음 보류함에 들어간 때를 기준으로 한 번만 정할지 다시 평가할 때마다 새로 정할지도 부르는 쪽(저장 단계)이 정한다.
"""
from __future__ import annotations

from datetime import timedelta

from ..content.candidates import STAMP_FORMAT, _invalid, parse_stamp
from .channels import HOLD_DAYS
from .score import BAND_HOLD, BANDS

MAX_DAYS = 3650                                                       # 보관 날수의 상한(10년) — 실수로 아주 큰 값을 넣지 않게


def review_expires_at(evaluated_at, days=HOLD_DAYS):
    """평가한 시각(UTC `YYYY-MM-DDTHH:MM:SSZ`) + `days`일(기본 `HOLD_DAYS` = 90) → 만료 시각(같은 모양의 글). 모양이 틀린 시각·범위 밖 날수·달력을 넘는 값은 `CANDIDATE_INVALID`."""
    moment = parse_stamp(evaluated_at, "평가한 시각")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= MAX_DAYS:
        raise _invalid("보관 날수", f"1~{MAX_DAYS} 사이의 정수여야 합니다")
    try:
        due = moment + timedelta(days=days)
    except OverflowError:
        raise _invalid("검토 기한", "너무 먼 미래라 보관 기한을 계산할 수 없습니다", detail="달력 범위(9999년)를 넘는다") from None
    return due.strftime(STAMP_FORMAT)


def expiry_for(band, evaluated_at, days=HOLD_DAYS):
    """추천 구간(`score.band_of` 의 값)이 보류(`HOLD`)이면 만료 시각을, 그 밖의 구간이면 None 을 돌려준다. 모르는 구간 이름은 `ValueError`.
    평가한 시각과 날수는 구간과 상관없이 늘 검사한다(틀린 시각이 구간에 따라 숨지 않게)."""
    if not isinstance(band, str) or band not in BANDS:
        raise ValueError("모르는 추천 구간이다: " + ", ".join(BANDS) + " 중 하나여야 한다")
    expiry = review_expires_at(evaluated_at, days)
    return expiry if band == BAND_HOLD else None


def is_expired(expires_at, now):
    """만료 시각이 있고 `now`(UTC 시각 글)가 그 시각 이후(같은 시각 포함)이면 True. 만료 시각이 없으면(None) 항상 False — 보류 구간이 아닌 후보는 '지나지' 않는다."""
    if expires_at is None:
        parse_stamp(now, "지금 시각")
        return False
    return parse_stamp(now, "지금 시각") >= parse_stamp(expires_at, "검토 기한")


__all__ = ["MAX_DAYS", "expiry_for", "is_expired", "review_expires_at"]
