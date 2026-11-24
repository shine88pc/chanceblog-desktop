"""쿨다운과 접속 기록(NET 설계서 3.4·3.15, D-727) — **세션 안, 메모리만**이다(파일에 쓰지 않는다 — 개인 정보를 남기지 않는다). 앱을 끄면 사라지고 재시작이 쿨다운을 초기화해도 된다(접속이 모두 사용자 동작이라 해가 작다).

쿨다운: 같은 용도가 **연속 3번 실패**하면 5분 쉰다(쉬는 동안 `NET_COOLDOWN` 으로 즉시 거절하고 접속하지 않는다). 쉬는 시간이 끝나면 사용자가 누른 요청 **한 건만** 보내 보고(반쯤 열림),
성공이면 닫히고 실패면 두 배(10분 → 20분 → 상한 30분)로 다시 쉰다. 사용자 실수(400·422)와 한도 안내(429)는 연속 실패 계수에 넣지 않는다. 진행 중인 같은 용도의 두 번째 요청도 거절한다(단추 연타).
접속 기록은 메모리 고리 50건이고 한 건의 칸은 `RECORD_FIELDS` 뿐이다 — 머리글 값·본문·질의 값·토큰·주소는 기록하지 않는다.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, fields
from datetime import datetime, timedelta

from .errors import NetError

FAILS_TO_REST = 3
REST_SECONDS = (300.0, 600.0, 1200.0, 1800.0)      # 5분 → 10분 → 20분 → 상한 30분
LOG_SIZE = 50


@dataclass(frozen=True)
class ConnectionRecord:
    """접속 기록 한 건 — 사용자가 볼 수 있는 값만(비밀 없음)."""
    at: float             # 시각(초, 벽시계)
    use: str              # 용도 이름
    host: str             # 호스트(표의 것)
    method: str           # GET · POST
    route: str            # 길 이름 — 표의 글(숫자 ID 는 `<번호>`)
    status: int           # HTTP 상태(접속 전·중에 실패하면 0)
    error: str            # 오류 코드(성공이면 빈 글)
    sent: int             # 보낸 바이트(요청 줄·머리글·본문)
    received: int         # 받은 바이트(본문)
    seconds: float        # 걸린 시간


RECORD_FIELDS = tuple(field.name for field in fields(ConnectionRecord))


class Usage:
    """쿨다운과 접속 기록 — 용도마다 상태를 따로 갖는다. 시계는 바꿔 끼울 수 있다(시험)."""

    def __init__(self, *, clock=time.monotonic, wall=time.time):
        self._clock = clock
        self._wall = wall
        self._lock = threading.Lock()
        self._state = {}                    # 용도 → {"fails": 연속 실패, "level": 쉬는 단계, "until": 쉬는 시간 끝(시계 값) 또는 None}
        self._active = set()                # 진행 중인 용도
        self._log = deque(maxlen=LOG_SIZE)

    # ---- 시작 관문: 쉬는 중이거나 진행 중이면 거절한다 ----------------------------------------------------------------------------
    def begin(self, use):
        with self._lock:
            state = self._state.get(use)
            now = self._clock()
            if state and state["until"] is not None and now < state["until"]:
                raise NetError("NET_COOLDOWN", {"재시도 가능 시각": self._when(state["until"] - now)}, detail=f"{use}:cooldown", use=use)
            if use in self._active:
                raise NetError("NET_COOLDOWN", {"재시도 가능 시각": self._when(30)}, detail=f"{use}:in_flight", use=use)      # 단추 연타 — 지금 진행 중인 요청이 끝난 뒤
            self._active.add(use)

    def finish(self, use, *, ok, counts):
        """요청이 끝났다. `ok` 면 닫힘으로, 실패인데 `counts` 면 연속 실패를 센다(3번째에 쉼 — 반쯤 열림에서의 실패는 곧바로 한 단계 더 쉰다)."""
        with self._lock:
            self._active.discard(use)
            state = self._state.setdefault(use, {"fails": 0, "level": 0, "until": None})
            if ok:
                state.update(fails=0, level=0, until=None)
                return
            if not counts:
                return
            half_open = state["until"] is not None             # 쉬는 시간이 끝난 뒤의 시험 한 건이 실패했다
            state["fails"] += 1
            if half_open:
                state["level"] = min(state["level"] + 1, len(REST_SECONDS) - 1)
                state["until"] = self._clock() + REST_SECONDS[state["level"]]
            elif state["fails"] >= FAILS_TO_REST:
                state["until"] = self._clock() + REST_SECONDS[state["level"]]

    def abort(self, use):
        """접속 전에 거절돼 요청이 시작되지 못했다 — 진행 중 표시만 푼다(계수에 넣지 않는다)."""
        with self._lock:
            self._active.discard(use)

    def resting(self, use):
        """지금 쉬는 중인가(들여다보기용)."""
        with self._lock:
            state = self._state.get(use)
            return bool(state and state["until"] is not None and self._clock() < state["until"])

    def wall(self):
        """기록에 적는 벽시계 시각(초)."""
        return self._wall()

    def _when(self, seconds):
        """쉬는 시간이 끝나는 시각을 `HH:MM` 으로(사용자 문구의 「재시도 가능 시각」)."""
        return (datetime.fromtimestamp(self._wall()) + timedelta(seconds=max(1, int(seconds)))).strftime("%H:%M")

    # ---- 접속 기록 --------------------------------------------------------------------------------------------------------------
    def record(self, **values):
        """기록 한 건을 더한다 — 고정된 칸 말고는 받지 않는다."""
        if set(values) != set(RECORD_FIELDS):
            raise ValueError("접속 기록의 칸이 정해진 것과 다르다")
        with self._lock:
            self._log.append(ConnectionRecord(**values))

    def records(self):
        """기록을 오래된 것부터(복사본)."""
        with self._lock:
            return tuple(self._log)

    def count(self):
        with self._lock:
            return len(self._log)


SESSION = Usage()          # 앱 하나의 세션 — 클라이언트가 따로 정하지 않으면 이것을 쓴다


__all__ = ["ConnectionRecord", "FAILS_TO_REST", "LOG_SIZE", "REST_SECONDS", "RECORD_FIELDS", "SESSION", "Usage"]
