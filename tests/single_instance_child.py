"""`test_single_instance` 의 진짜 프로세스 시험이 띄우는 도우미(시험이 아니다) — 진짜 윈도 뮤텍스(커널)는 그대로 쓰고 창 층만 가짜로 바꿔, 창이 없는 시험 환경에서 12초를 기다리거나
진짜 안내 상자를 띄우지 않게 한다. 사용: `python single_instance_child.py <역할> <데이터 폴더>`.

역할: `claim-hold`·`claim-probe`·`claim-waithold` 는 단일 실행 장치(`claim`)만 부르고, `launcher-hold`·`launcher-probe` 는 진짜 `launcher.main` 을 가짜 화면(Qt 없음)으로 돈다.
`-hold`·`-waithold` 는 판정을 찍은 뒤 부모가 표준 입력으로 줄을 보낼 때까지 살아서 뮤텍스를 쥐고(앱 창이 열려 있는 것과 같다), `-probe` 는 판정을 찍고 곧 끝난다.
`-waithold` 는 창을 8초까지 기다리며(처음 창 목록을 읽을 때 `POLL` 을 찍는다) 그 사이 먼저 열려 있던 앱이 끝나면 뮤텍스를 넘겨받는다.
찍는 글: `CLAIM <참/거짓> <이유>`·`POLL`·`BOX`(안내 상자를 보이려 했다)·`RUN`(화면을 열려 했다)·`EXIT <종료 코드> <이유>`.
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.ui import single_instance as si  # noqa: E402


class Probe(si.Win32Api):
    """진짜 뮤텍스를 쓰고 창 층만 가짜 — 열린 창이 없다고 답하고, 안내 상자 대신 `BOX` 를 찍는다."""

    announce_poll = False
    polled = False

    def top_windows(self):
        if self.announce_poll and not self.polled:
            Probe.polled = True
            print("POLL", flush=True)
        return []

    def message_box(self, title, text):
        print("BOX", flush=True)


def main(argv):
    role, folder = argv[0], argv[1]
    Probe.announce_poll = role.endswith("waithold")
    si.default_api = lambda platform=None: Probe()
    si.WAIT_SECONDS, si.POLL_SECONDS = (8.0 if role.endswith("waithold") else 0.3), 0.05
    if role.startswith("claim"):
        print("CLAIM", si.claim(folder), si.last_note(), flush=True)
    else:
        module = types.ModuleType("chanceblog_desktop.ui.qt.app")
        module.run = lambda provider, argv=None: (print("RUN", flush=True), 0)[1]
        sys.modules["chanceblog_desktop.ui.qt.app"] = module
        from chanceblog_desktop.ui import launcher
        launcher.has_pyside6 = lambda: True
        code = launcher.main(["--data-dir", folder])
        print("EXIT", code, si.last_note(), flush=True)
    if role.endswith("hold"):
        sys.stdin.readline()                                   # 부모가 줄을 보낼 때까지 쥐고 산다


if __name__ == "__main__":
    main(sys.argv[1:])
