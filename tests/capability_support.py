"""시험이 이 빌드의 소스 상수 관문(`capabilities.py`)을 **임시로만** 여는 도우미(시험이 아니다 — PCSEC1).

`EXTERNAL_WRITE`(외부 Write)와 `BLOGGER_OAUTH_INPUT`(Blogger 입력)은 이 빌드에서 False 인 소스 상수다 — 설정·환경 변수·명령줄이 바꿀 수 없고 생산 코드에는 켜기 훅이 없다. 기존 게시·자격 증명 구조 시험은
시험 모듈의 `setUpModule` 에서 `mock.patch.object` 로 켜 두고 `tearDownModule` 에서 되돌린다(켠 채로 다른 시험에 새지 않는다).
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402

_PATCHERS = {"EXTERNAL_WRITE": [], "BLOGGER_OAUTH_INPUT": [], "LOCAL_OCR": [],
             # 인터넷 접속 스위치 다섯(NET, D-720) — 시험이 임시로만 켠다
             "NET_UPDATE_CHECK": [], "NET_PAGES_SITE": [], "PAGES_BRANCH_PUSH": [], "NET_BLOGGER_OAUTH": [], "NET_BLOGGER_DRAFT": []}


def _on(name):
    patcher = mock.patch.object(capabilities, name, True)
    patcher.start()
    _PATCHERS[name].append(patcher)


def _off(name):
    while _PATCHERS[name]:
        _PATCHERS[name].pop().stop()


def switch_on(name):
    """이름으로 스위치 하나를 시험에서만 임시로 연다(`switch_off` 로 되돌린다 — 켠 채 다른 시험에 새지 않게)."""
    _on(name)


def switch_off(name):
    _off(name)


_TRANSPORT_PATCHERS = []


def local_origin_transport_on():
    """진짜 git·로컬 bare 저장소 시험이 `file` 전송을 임시로 허용한다(`gitrepo._EXTRA_TRANSPORTS` — 시험 접합부. 생산 코드는 https·ssh 만 허용한다)."""
    patcher = mock.patch.object(gitrepo, "_EXTRA_TRANSPORTS", ("file",))
    patcher.start()
    _TRANSPORT_PATCHERS.append(patcher)


def local_origin_transport_off():
    while _TRANSPORT_PATCHERS:
        _TRANSPORT_PATCHERS.pop().stop()


def external_write_on():
    """외부 Write 관문을 시험에서만 임시로 연다. NET(D-720)부터 올린 글의 공개 주소 확인은 좁은 스위치(`NET_PAGES_SITE`)도 함께 요구하므로, 예전에 `EXTERNAL_WRITE` 하나가 열던 같은 흐름을 이 시험들이 그대로 돌게 그 스위치도 함께 임시로 연다.
    PUBPR(D-740)부터 git 받기·올리기도 좁은 스위치(`PAGES_BRANCH_PUSH`)를 함께 요구하므로 같은 까닭으로 그것도 함께 연다 — 그리고 로컬 bare 저장소(원격 대신 폴더 경로)를 쓰는 시험을 위해 `file` 전송을 임시로 허용한다."""
    _on("EXTERNAL_WRITE")
    _on("NET_PAGES_SITE")
    _on("PAGES_BRANCH_PUSH")
    local_origin_transport_on()


def external_write_off():
    _off("EXTERNAL_WRITE")
    _off("NET_PAGES_SITE")
    _off("PAGES_BRANCH_PUSH")
    local_origin_transport_off()
    # 스위치가 켜진 동안 `make_context` 가 꽂은 `pages_git` 어댑터 공장(`wiring.register_enabled` 는 더하기만 한다)이 다른 시험으로 새지 않게 거둔다 —
    # PUBPR 이전에는 꽂히는 것이 아무 일도 안 하는 자리표시자라 새도 티가 나지 않았지만 지금은 진짜 어댑터라, 새면 기본 문맥의 `backend` 가 `LocalOnlyBackend` 가 아니게 된다.
    from chanceblog_desktop.service import external
    external.unregister(external.KIND_PAGES_GIT)


def blogger_input_on():
    _on("BLOGGER_OAUTH_INPUT")


def blogger_input_off():
    _off("BLOGGER_OAUTH_INPUT")


def local_ocr_on():
    """글자 읽기 작업자 관문(`LOCAL_OCR`, 결정 D-512)을 시험에서만 임시로 연다 — 켠 채 다른 시험에 새지 않게 `local_ocr_off` 로 되돌린다."""
    _on("LOCAL_OCR")


def local_ocr_off():
    _off("LOCAL_OCR")
