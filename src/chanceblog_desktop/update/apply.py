"""설치 종류별 적용 어댑터의 **빈 틀**(UPDATE 설계서 3-8) — 이 갈래(U-1·U-2·U-3)에는 설치 도구(Velopack·Inno)를 띄우는 코드가 **한 줄도 없다**. 실제 어댑터는 설치 도구 결정(확인 041 의 시험 결과) 뒤에 U-4 가 채운다.

여기 있는 것: 어댑터가 지켜야 할 모양(`ApplyAdapter`)과 지금 쓰는 두 가지 — 휴대용·소스 실행은 스스로 바뀌지 않으니 `UPDATE_NOT_INSTALLED_KIND` 로 거절하는 어댑터, 아직 어댑터가 없는 설치 종류(velopack·inno)에 닿으면
`UPDATE_APPLY_FAILED`(이유: 어댑터 없음)로 거절하는 어댑터. 두 가지 모두 아무것도 실행하지 않는다.
모든 어댑터의 `apply` 는 **첫 문장이 스위치 관문**(`capabilities.require_update_apply`)이다 — 꺼져 있으면 `UPDATE_DISABLED` 로 하위 프로세스·파일 쓰기 전에 끝난다. 시험은 이 모양을 가짜 어댑터로 확인한다.
공통 규칙(U-4 가 지킨다): 인자는 고정 목록이고 셸을 거치지 않으며, 경로는 우리가 만든 임시 폴더의 우리가 정한 이름뿐이고, 하위 프로세스의 출력은 읽지 않고, 종료 코드가 0 이 아니면 `UPDATE_APPLY_FAILED`(기록에는 숫자만)이다.
"""
from __future__ import annotations

from .. import capabilities
from ..errors import AppError

INSTALLED_KINDS = ("velopack", "inno")
UNSUPPORTED_KINDS = ("portable", "source", "")


class ApplyAdapter:
    """설치 종류 하나의 적용 방법. 하위 클래스는 `_apply` 만 채운다 — `apply` 의 첫 문장(스위치 관문)은 바꾸지 않는다."""
    kind = ""

    def apply(self, staged, *, from_version, to_version, recovery=False):
        """검증된 파일(`staged`)을 설치 도구에 넘긴다. 성공하면 앱은 곧 정상 종료한다. 실패는 `AppError`(`UPDATE_APPLY_FAILED` 등)."""
        capabilities.require_update_apply("업데이트 설치")
        return self._apply(staged, from_version=from_version, to_version=to_version, recovery=recovery)

    def _apply(self, staged, *, from_version, to_version, recovery):
        raise NotImplementedError


class UnsupportedKindAdapter(ApplyAdapter):
    """휴대용·소스 실행 — 프로그램이 스스로 바뀌지 않는다. 새 압축 파일을 받아 풀어 쓰는 안내만 한다."""

    def __init__(self, kind=""):
        self.kind = kind if kind in UNSUPPORTED_KINDS else ""

    def _apply(self, staged, *, from_version, to_version, recovery):
        raise AppError("UPDATE_NOT_INSTALLED_KIND", detail=f"kind:{self.kind or 'unknown'}")


class MissingAdapter(ApplyAdapter):
    """설치 도구가 정해지기 전의 자리 — 아무것도 실행하지 않고 거절한다(fail closed). U-4 가 `adapter_for` 에서 이것을 진짜 어댑터로 바꾼다."""

    def __init__(self, kind):
        self.kind = kind

    def _apply(self, staged, *, from_version, to_version, recovery):
        raise AppError("UPDATE_APPLY_FAILED", detail=f"adapter_missing:{self.kind}")


def adapter_for(kind):
    """설치 종류 → 어댑터. 모르는 종류는 지원하지 않는 쪽(`UnsupportedKindAdapter`)으로 닫는다."""
    if kind in INSTALLED_KINDS:
        return MissingAdapter(kind)
    return UnsupportedKindAdapter(kind if kind in UNSUPPORTED_KINDS else "")


__all__ = ["ApplyAdapter", "INSTALLED_KINDS", "MissingAdapter", "UNSUPPORTED_KINDS", "UnsupportedKindAdapter", "adapter_for"]
