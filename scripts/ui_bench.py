"""화면 성능 실측(창을 띄우지 않는 offscreen) — 첫 화면 시간·작업 스레드 대 직접 기다림의 화면 멈춤·뷰모델 만들기·다시 그리기·메모리. 결과는 이 PC·offscreen 에서의 값이다(실제 윈도 창은 더 걸릴 수 있다).

실행: python scripts/ui_bench.py        (PySide6 가 있는 파이썬으로)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_offscreen  # noqa: E402

ui_offscreen.prepare_environment()


def working_set_mb():
    """이 프로세스의 작업 집합 메모리(MB) — 윈도만, 아니면 None."""
    import ctypes
    from ctypes import wintypes
    if not hasattr(ctypes, "windll"):
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return round(counters.WorkingSetSize / 1048576, 1) if ok else None


def main():
    started = time.perf_counter()
    from PySide6.QtCore import QTimer
    from chanceblog_desktop.ui.core import app_state, services
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt.shell import AppShell
    import_ms = (time.perf_counter() - started) * 1000
    ui_offscreen.install_system_fonts()
    started = time.perf_counter()
    app = qapp.make_app()
    app_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    window = AppShell(services.FakeHomeProvider(), autoload=False)
    window.resize(1440, 900)
    window.show()
    shell_ms = (time.perf_counter() - started) * 1000
    window.reload()
    ui_offscreen.wait_until(app, lambda: window.state.list_state != "loading", 10)
    ui_offscreen.settle(app)
    first_ms = (time.perf_counter() - started) * 1000
    memory = working_set_mb()

    renders = []
    for _ in range(20):
        t = time.perf_counter()
        window.render()
        app.processEvents()
        renders.append((time.perf_counter() - t) * 1000)
    window.close()

    def gaps(delay, block):
        win = AppShell(services.FakeHomeProvider(delay=delay), autoload=False)
        win.resize(1440, 900)
        win.show()
        ticks, last = [], [time.perf_counter()]

        def tick():
            now = time.perf_counter()
            ticks.append(now - last[0])
            last[0] = now

        timer = QTimer()
        timer.timeout.connect(tick)
        timer.start(5)
        if block:                                              # 화면 스레드에서 직접 기다리면(나쁜 방법)
            def blocking():
                services.FakeHomeProvider(delay=delay).load_home(lambda *a: None, lambda: False)
            QTimer.singleShot(50, blocking)
            ui_offscreen.wait_until(app, lambda: len(ticks) > 5 and max(ticks) > delay * 0.8, delay + 5)
        else:
            win.reload()
            ui_offscreen.wait_until(app, lambda: win.state.list_state != "loading", delay + 5)
        timer.stop()
        win.close()
        return max(ticks) * 1000

    thread_gap = gaps(1.2, False)
    block_gap = gaps(1.2, True)

    results = {}
    for count in (2000, 20000):
        topics = services.sample_topics(count)
        state = app_state.AppState(services.FakeHomeProvider(count=count))
        state.apply_home(services.HomeData(topics=topics, sample=True))
        t = time.perf_counter()
        for _ in range(5):
            state.home_view()
        results[count] = (time.perf_counter() - t) * 1000 / 5

    print(f"가져오기(import) PySide6·화면 모듈: {import_ms:.0f}ms")
    print(f"QApplication 만들기(글꼴·스타일시트): {app_ms:.0f}ms")
    print(f"앱 틀 만들기+보이기: {shell_ms:.0f}ms · 첫 화면(후보 5줄까지): {first_ms:.0f}ms")
    print(f"다시 그리기 20번: 평균 {sum(renders) / len(renders):.1f}ms · 최대 {max(renders):.1f}ms")
    print(f"1.2초짜리 일 동안 화면 멈춤(5ms 타이머의 가장 긴 틈): 작업 스레드 {thread_gap:.0f}ms · 화면 스레드에서 직접 기다림 {block_gap:.0f}ms")
    print(f"뷰모델 만들기(홈): 후보 2,000개 {results[2000]:.1f}ms · 20,000개 {results[20000]:.1f}ms (화면은 5줄만 그린다)")
    print(f"작업 집합 메모리(첫 화면 직후): {memory}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
