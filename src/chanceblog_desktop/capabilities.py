"""이 빌드가 할 수 있는 일의 **소스 상수** 관문(PCSEC1 H3 — 외부 Write 완전 비활성, 운영자 결정 2026-11-11, docs/DECISIONS.md).

개인 PC 제한 시험 빌드는 **외부에 쓰는 일**(git push·GitHub PR 만들기·Chance 자동 게시·원격에 닿는 git 하위 명령·배포 확인·Blogger API 호출·네이버 자동 로그인·게시·
Cookie·Session 사용·예약 게시·외부 초안 전송)을 **하지 않는다.** 이 모듈의 상수가 그 스위치이고, 켜는 길은 소스를 고치는 것 하나뿐이다:

  · 설정 파일·환경 변수·명령줄·화면 어디에도 이 상수를 바꾸는 길이 없다(시험이 소스에서 확인한다).
  · 시험은 `unittest.mock.patch.object(capabilities, "EXTERNAL_WRITE", True)` 로 **임시로만** 켠다. 생산 코드에는 시험용 켜기 훅이 없다.
  · 켜려면 어떻게 바꾸고 어떤 별도 검증이 필요한지는 docs/DECISIONS.md D-343 의 PUBPR 제안 단락에 있다.

`require_external_write(작업)` 는 외부 Write 가 닿는 모든 진입점의 **첫 줄**에서 부른다 — 꺼져 있으면 하위 프로세스·네트워크를 한 번도 부르기 전에
`EXTERNAL_WRITE_DISABLED` 로 거절한다(`service/external.py` 의 어댑터 등록부·거절 백엔드와 이중 방어).
`BLOGGER_OAUTH_INPUT` 은 같은 방식의 두 번째 상수다 — Blogger 의 OAuth 입력(클라이언트 비밀·갱신 토큰)을 받는 길이 이 빌드에는 없다(호출 코드가 없다).
`LOCAL_OCR` 은 같은 모양의 세 번째 상수다(결정 D-512, 운영자 확인 026 ②·028 ②) — **이 PC 안에서만** 계산하는 글자 읽기 작업자(별도 프로세스)를 띄워도 되는가. 바깥에 쓰는 일이 아니라서 `EXTERNAL_WRITE` 와 따로 두고,
같은 방식으로 지킨다: 기본은 False, 설정·환경 변수·명령줄·화면에 켜는 길이 없고, 시험만 `mock.patch.object` 로 임시로 켠다. 켜는 것은 소스 한 줄을 고치는 별도 변경(운영자 승인)이다.
`require_local_ocr(작업)` 는 작업자를 띄우는 유일한 곳(`ui/ocr_adapter.py`)의 **첫 줄**에서 부른다 — 꺼져 있으면 하위 프로세스를 한 번도 부르기 전에 `OCR_UNAVAILABLE` 로 거절한다.
"""
from __future__ import annotations

from .errors import AppError

EXTERNAL_WRITE = False            # 외부에 쓰는 모든 일의 스위치 — 이 빌드는 False 다(바꾸려면 소스를 고쳐야 한다)
BLOGGER_OAUTH_INPUT = False       # Blogger OAuth 입력 칸 — 호출 코드가 없는 이 빌드에서는 받지 않는다(저장 구조는 그대로 둔다)
LOCAL_OCR = False                 # 이 PC 안의 글자 읽기 작업자(별도 프로세스) 스위치 — 이 빌드는 False 다(켜려면 소스를 고쳐야 하고 별도 승인이 든다)


def external_write_enabled():
    """외부 Write 가 켜져 있는가(소스 상수가 글자 그대로 True 일 때만 — 1·'yes' 같은 참 비슷한 값은 켜지 못한다)."""
    return EXTERNAL_WRITE is True


def require_external_write(operation):
    """외부 Write 진입점의 첫 줄 — 꺼져 있으면 `EXTERNAL_WRITE_DISABLED`(아무것도 하지 않는다: 하위 프로세스·네트워크·파일 쓰기 전)."""
    if EXTERNAL_WRITE is not True:
        raise AppError("EXTERNAL_WRITE_DISABLED", {"작업": operation})


def blogger_oauth_input_enabled():
    """Blogger OAuth 입력 칸을 받는가(이 빌드는 아니오)."""
    return BLOGGER_OAUTH_INPUT is True


def local_ocr_enabled():
    """글자 읽기 작업자를 띄워도 되는가(소스 상수가 글자 그대로 True 일 때만 — 1·'yes' 같은 참 비슷한 값은 켜지 못한다)."""
    return LOCAL_OCR is True


def require_local_ocr(operation):
    """글자 읽기 작업자를 띄우는 진입점의 첫 줄 — 꺼져 있으면 `OCR_UNAVAILABLE`(아무것도 하지 않는다: 하위 프로세스·파일 쓰기 전)."""
    if LOCAL_OCR is not True:
        raise AppError("OCR_UNAVAILABLE", {"작업": operation})


__all__ = ["BLOGGER_OAUTH_INPUT", "EXTERNAL_WRITE", "LOCAL_OCR", "blogger_oauth_input_enabled", "external_write_enabled", "local_ocr_enabled", "require_external_write", "require_local_ocr"]
