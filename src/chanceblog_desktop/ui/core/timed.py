"""시간 제한이 있는 읽기 — 순수 파이썬(화면 도구·서비스 층을 모른다). 읽기 하나가 오래 걸려도 화면을 불러오는 작업 전체가 거기서 멈추지 않게, 일을 도우미 스레드에서 돌리고 제한 시간 안에 안 끝나면 기다리지 않고 넘어간다.

**넘긴 일은 멈출 수 없다** — 버리고 가는 것이라 **읽기만 하는 일**에만 쓴다(데몬 스레드라 앱이 끝날 때 막지 않고, 버려진 읽기는 끝나면 값을 그냥 버린다). 쓰는 일에는 쓰지 않는다(절반만 하고 버려질 수 있다).
홈의 '최근 발행'(UI-C1c)이 글마다 발행한 때를 읽을 때 쓴다: 글 하나가 느려도 그 글만 `발행일 확인 불가` 가 되고 홈은 그대로다.
"""
from __future__ import annotations

import threading


class ReadTimeout(Exception):
    """제한 시간 안에 읽기가 끝나지 않았다."""


def call_within(seconds, work, *args):
    """`work(*args)` 를 도우미 스레드에서 돌려 `seconds` 초 안에 끝나면 그 값을 돌려준다. 제한을 넘으면 `ReadTimeout`, 일이 예외를 냈으면 그 예외를 그대로 다시 낸다.
    제한이 0 이하(남은 시간이 없다)면 일을 시작하지 않고 곧바로 `ReadTimeout`. 제한을 넘긴 일은 멈출 수 없어 그대로 두고 간다(위 설명)."""
    if not seconds > 0:                                                              # 0 이하·NaN — 시작하지 않는다
        raise ReadTimeout()
    box = {}

    def run():
        try:
            box["value"] = work(*args)
        except Exception as error:                                                   # 일의 오류는 부른 쪽이 받는다(스레드에서 사라지지 않게)
            box["error"] = error

    thread = threading.Thread(target=run, name="timed-read", daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise ReadTimeout()
    if "error" in box:
        raise box["error"]
    return box["value"]
