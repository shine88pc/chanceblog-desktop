"""시험이 이 빌드의 소스 상수 관문(`capabilities.py`)을 **임시로만** 여는 도우미(시험이 아니다 — PCSEC1).

`EXTERNAL_WRITE`(외부 Write)와 `BLOGGER_OAUTH_INPUT`(Blogger 입력)은 이 빌드에서 False 인 소스 상수다 — 설정·환경 변수·명령줄이 바꿀 수 없고 생산 코드에는 켜기 훅이 없다. 기존 게시·자격 증명 구조 시험은
시험 모듈의 `setUpModule` 에서 `mock.patch.object` 로 켜 두고 `tearDownModule` 에서 되돌린다(켠 채로 다른 시험에 새지 않는다).
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop import capabilities  # noqa: E402

_PATCHERS = {"EXTERNAL_WRITE": [], "BLOGGER_OAUTH_INPUT": []}


def _on(name):
    patcher = mock.patch.object(capabilities, name, True)
    patcher.start()
    _PATCHERS[name].append(patcher)


def _off(name):
    while _PATCHERS[name]:
        _PATCHERS[name].pop().stop()


def external_write_on():
    _on("EXTERNAL_WRITE")


def external_write_off():
    _off("EXTERNAL_WRITE")


def blogger_input_on():
    _on("BLOGGER_OAUTH_INPUT")


def blogger_input_off():
    _off("BLOGGER_OAUTH_INPUT")
