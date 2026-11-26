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

인터넷 접속 스위치 다섯(`NET_UPDATE_CHECK`·`NET_PAGES_SITE`·`PAGES_BRANCH_PUSH`·`NET_BLOGGER_OAUTH`·`NET_BLOGGER_DRAFT`, D-720, 운영자 확인 038 ①)은 같은 방식의 상수다 — 새 접속마다 따로 두고 모두 False 다.
`require_net(용도, 작업)` 은 `net/client.py` 와 접속 흐름의 관문이다(용도마다 필요한 스위치가 모두 True 여야 지나고, 모르는 용도는 거절한다). `SWITCH_NAMES` 가 모든 상수 이름의 표이고,
출하 표(`packaging/pkgcommon.py` 의 `SHIPPED_OPEN_SWITCHES`)에 적힌 것만 켠 채 내보낼 수 있다 — 지금은 빈 표다(켜진 것 0).
업데이트 설치 스위치 하나(`UPDATE_APPLY`, UPDATE 갈래, 운영자 확인 038 ①)도 같은 방식의 상수다 — 접속이 아니라 **설치 도구를 띄우고 시작 때 업데이트 점검 표식을 읽고 쓰는 일**의 스위치라서
`NET_USES` 에 없고 `require_update_apply(작업)` 이 관문이다(꺼져 있으면 `UPDATE_DISABLED`). `NET_UPDATE_CHECK`(확인·내려받기)와 따로 켠다 — 확인만 켜고 설치는 꺼 두는 단계가 가능해야 한다.
"""
from __future__ import annotations

from .errors import AppError

EXTERNAL_WRITE = False            # 외부에 쓰는 모든 일의 스위치 — 이 빌드는 False 다(바꾸려면 소스를 고쳐야 한다)
BLOGGER_OAUTH_INPUT = False       # Blogger OAuth 입력 칸 — 호출 코드가 없는 이 빌드에서는 받지 않는다(저장 구조는 그대로 둔다)
LOCAL_OCR = False                 # 이 PC 안의 글자 읽기 작업자(별도 프로세스) 스위치 — 이 빌드는 False 다(켜려면 소스를 고쳐야 하고 별도 승인이 든다)
# ---- 인터넷 접속 스위치 다섯(NET, 운영자 확인 038 ① — 구현 준비까지, 모두 False): 새 접속마다 별개의 소스 상수다. 켜는 변경은 상수 한 줄 + `packaging/pkgcommon.py` 의 출하 표 한 줄이고 갈래마다 새 번호를 받는다.
NET_UPDATE_CHECK = False          # 업데이트 확인(읽기, 사용자가 단추를 누를 때만) — 함께 켜져 있어야 하는 것 없음
NET_PAGES_SITE = False            # 올린 글의 공개 주소 확인(읽기) — EXTERNAL_WRITE 와 함께
PAGES_BRANCH_PUSH = False         # git 으로 새 가지에 올리기·병합 확인용 받기 — EXTERNAL_WRITE 와 함께
NET_BLOGGER_OAUTH = False         # Blogger 로그인·토큰 갱신·연결 해제와 읽기 요청 — 함께 켜져 있어야 하는 것 없음
NET_BLOGGER_DRAFT = False         # Blogger 초안 저장(쓰기 한 가지) — EXTERNAL_WRITE·NET_BLOGGER_OAUTH 와 함께
UPDATE_APPLY = False              # 내려받은 업데이트를 설치 도구에 넘겨 적용하는 일과 시작 때의 점검 표식 — 켜는 확인은 구현·독립 검증 뒤 새 번호로(UPDATE 갈래)

# 모든 스위치 상수 이름의 표(시험이 소스의 대문자 상수 대입·출하 표·문서 표와 같음을 확인한다 — 새 상수를 빼먹으면 빨개진다)
SWITCH_NAMES = ("EXTERNAL_WRITE", "BLOGGER_OAUTH_INPUT", "LOCAL_OCR", "NET_UPDATE_CHECK", "NET_PAGES_SITE", "PAGES_BRANCH_PUSH", "NET_BLOGGER_OAUTH", "NET_BLOGGER_DRAFT", "UPDATE_APPLY")
# `require_net` 이 아는 용도 이름(이 밖의 이름은 거절한다)
NET_USES = ("update_check", "pages_site", "pages_branch", "blogger_oauth", "blogger_read", "blogger_draft")


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


def net_update_check_enabled():
    """업데이트 확인 접속이 열려 있는가(소스 상수가 글자 그대로 True 일 때만)."""
    return NET_UPDATE_CHECK is True


def net_pages_site_enabled():
    """올린 글의 공개 주소 확인 접속이 열려 있는가(이 스위치만으로는 부족하다 — `require_net` 은 EXTERNAL_WRITE 도 함께 요구한다)."""
    return NET_PAGES_SITE is True


def pages_branch_push_enabled():
    """git 으로 새 가지에 올리기·병합 확인용 받기가 열려 있는가(이 스위치만으로는 부족하다 — EXTERNAL_WRITE 도 함께 요구한다)."""
    return PAGES_BRANCH_PUSH is True


def net_blogger_oauth_enabled():
    """Blogger 로그인·읽기 접속이 열려 있는가."""
    return NET_BLOGGER_OAUTH is True


def net_blogger_draft_enabled():
    """Blogger 초안 저장이 열려 있는가(이 스위치만으로는 부족하다 — EXTERNAL_WRITE·NET_BLOGGER_OAUTH 도 함께 요구한다)."""
    return NET_BLOGGER_DRAFT is True


def update_apply_enabled():
    """업데이트 설치(설치 도구 넘기기·시작 때 점검 표식)가 열려 있는가(소스 상수가 글자 그대로 True 일 때만)."""
    return UPDATE_APPLY is True


def require_update_apply(operation):
    """업데이트 설치 진입점의 첫 줄 — 꺼져 있으면 `UPDATE_DISABLED`(아무것도 하지 않는다: 하위 프로세스·파일 쓰기 전)."""
    if UPDATE_APPLY is not True:
        raise AppError("UPDATE_DISABLED", {"작업": operation})


def open_switch_names():
    """지금 열려 있는(글자 그대로 True) 스위치 이름들 — 읽기만 하는 점검(`doctor` 같은 곳)이 쓴다. 기본 빌드는 빈 튜플이다."""
    return tuple(name for name in SWITCH_NAMES if globals().get(name) is True)


def require_net(use, operation):
    """인터넷 접속 진입점의 관문 — 용도 이름(`NET_USES`)마다 필요한 스위치가 **모두 글자 그대로 True** 일 때만 지난다(NET 설계서 3.3 진리표).
    모르는 용도 이름은 거절한다(안전한 쪽). 윗 스위치(`EXTERNAL_WRITE`)가 필요한 용도에서 그것이 꺼져 있으면 옛 문구 그대로 `EXTERNAL_WRITE_DISABLED`,
    그 밖의 거절은 `NETWORK_DISABLED` 다. 아무것도 하지 않은 채 끝낸다: 소켓·하위 프로세스·파일 쓰기 전."""
    if use == "update_check":
        needs_write, ready = False, NET_UPDATE_CHECK is True
    elif use == "pages_site":
        needs_write, ready = True, NET_PAGES_SITE is True
    elif use == "pages_branch":
        needs_write, ready = True, PAGES_BRANCH_PUSH is True
    elif use == "blogger_oauth" or use == "blogger_read":
        needs_write, ready = False, NET_BLOGGER_OAUTH is True
    elif use == "blogger_draft":
        needs_write, ready = True, NET_BLOGGER_OAUTH is True and NET_BLOGGER_DRAFT is True
    else:
        raise AppError("NETWORK_DISABLED", {"작업": operation})
    if needs_write and EXTERNAL_WRITE is not True:
        raise AppError("EXTERNAL_WRITE_DISABLED", {"작업": operation})
    if not ready:
        raise AppError("NETWORK_DISABLED", {"작업": operation})


__all__ = ["BLOGGER_OAUTH_INPUT", "EXTERNAL_WRITE", "LOCAL_OCR", "NET_BLOGGER_DRAFT", "NET_BLOGGER_OAUTH", "NET_PAGES_SITE", "NET_UPDATE_CHECK", "NET_USES", "PAGES_BRANCH_PUSH", "SWITCH_NAMES", "UPDATE_APPLY",
           "blogger_oauth_input_enabled", "external_write_enabled", "local_ocr_enabled", "net_blogger_draft_enabled", "net_blogger_oauth_enabled", "net_pages_site_enabled", "net_update_check_enabled",
           "open_switch_names", "pages_branch_push_enabled", "require_external_write", "require_local_ocr", "require_net", "require_update_apply", "update_apply_enabled"]
