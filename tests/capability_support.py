"""시험이 이 빌드의 소스 상수 관문(`capabilities.py`)을 **임시로만** 여는 도우미(시험이 아니다 — PCSEC1).

`EXTERNAL_WRITE`(외부 Write)와 `BLOGGER_OAUTH_INPUT`(Blogger 입력)은 이 빌드에서 False 인 소스 상수다 — 설정·환경 변수·명령줄이 바꿀 수 없고 생산 코드에는 켜기 훅이 없다. 기존 게시·자격 증명 구조 시험은
시험 모듈의 `setUpModule` 에서 `mock.patch.object` 로 켜 두고 `tearDownModule` 에서 되돌린다(켠 채로 다른 시험에 새지 않는다).
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop import capabilities  # noqa: E402

_PATCHERS = {"EXTERNAL_WRITE": [], "BLOGGER_OAUTH_INPUT": [], "LOCAL_OCR": [],
             # 인터넷 접속 스위치 다섯(NET, D-720) — 시험이 임시로만 켠다
             "NET_UPDATE_CHECK": [], "NET_PAGES_SITE": [], "PAGES_BRANCH_PUSH": [], "NET_BLOGGER_OAUTH": [], "NET_BLOGGER_DRAFT": [],
             # 업데이트 설치 스위치(UPDATE 갈래) — 시험이 임시로만 켠다
             "UPDATE_APPLY": []}


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


def external_write_on():
    """외부 Write 관문을 시험에서만 임시로 연다. NET(D-720)부터 올린 글의 공개 주소 확인은 좁은 스위치(`NET_PAGES_SITE`)도 함께 요구하므로, 예전에 `EXTERNAL_WRITE` 하나가 열던 같은 흐름을 이 시험들이 그대로 돌게 그 스위치도 함께 임시로 연다."""
    _on("EXTERNAL_WRITE")
    _on("NET_PAGES_SITE")


def external_write_off():
    _off("EXTERNAL_WRITE")
    _off("NET_PAGES_SITE")


def blogger_input_on():
    _on("BLOGGER_OAUTH_INPUT")


def blogger_input_off():
    _off("BLOGGER_OAUTH_INPUT")


def local_ocr_on():
    """글자 읽기 작업자 관문(`LOCAL_OCR`, 결정 D-512)을 시험에서만 임시로 연다 — 켠 채 다른 시험에 새지 않게 `local_ocr_off` 로 되돌린다."""
    _on("LOCAL_OCR")


def local_ocr_off():
    _off("LOCAL_OCR")
