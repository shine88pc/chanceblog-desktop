"""화면(홈·상태 화면·서랍·대화상자·툴팁·토스트)을 **창을 띄우지 않고**(offscreen) 사진으로 찍고, 같은 환경에서 글자 잘림·누르는 칸·가로 스크롤을 점검한다 — 정식 시각 검수 도구(docs/UI_VISUAL_QA.md).

실행(저장소 맨 위 폴더에서, PySide6 가 있는 파이썬으로):
    python scripts/ui_capture.py <저장 폴더> --env 1366x768@100 [--env 1920x1080@125 …] [--check]
검증 환경 `가로x세로@배율%`: 필수 1366x768@100 · 1920x1080@100 · 1920x1080@125, 조건부 1920x1080@150. **이 PC 에서는 윈도 배율을 바꾸지 않으므로** 배율은
Qt 가 직접 지원하는 환경 변수(`QT_SCALE_FACTOR`)로 흉내 낸다 — 프로세스를 시작할 때 정해야 하므로 환경마다 자식 프로세스로 돌리고(앱 코드에는 배율 값이 없다), 창의 논리 크기는 화면 크기를 배율로 나눈 값이다.
실제 윈도 125·150% 렌더·한글 입력기·화면 읽기·개인 PC 확인은 운영자 PC 검증으로 남는다. `--check` 는 사진을 저장하지 않고 점검 결과(JSON)만 낸다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENVS = ("1366x768@100", "1920x1080@100", "1920x1080@125", "1920x1080@150")


def parse_env(text):
    size, _, percent = text.partition("@")
    width, _, height = size.partition("x")
    return int(width), int(height), int(percent or 100)


def child(args):
    """한 환경(배율 하나)에서 사진·점검 — 이 프로세스는 배율 환경 변수가 켜진 채 시작되었다."""
    sys.path.insert(0, str(HERE))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QApplication, QPushButton, QToolTip
    from chanceblog_desktop.ui.core.services import FakeHomeProvider
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt.shell import AppShell
    general, fixed = ui_offscreen.install_system_fonts()
    app = qapp.make_app()
    width, height, percent = parse_env(args.env)
    logical = (round(width * 100 / percent), round(height * 100 / percent))
    out = Path(args.out)
    if not args.check:                                                   # 점검만 할 때는 폴더도 만들지 않는다
        out.mkdir(parents=True, exist_ok=True)
    tag = args.env.replace("@", "_")
    report = {"env": args.env, "logical": logical, "scale_factor_env": os.environ.get("QT_SCALE_FACTOR", "1"), "fonts": [general, fixed], "shots": {}, "checks": {}}

    def make(scenario):
        window = AppShell(FakeHomeProvider(scenario), autoload=False)
        window.resize(*logical)
        window.show()
        window.reload()
        ui_offscreen.wait_until(app, lambda: window.state.list_state != "loading", 10)
        ui_offscreen.settle(app)
        return window

    def shoot(window, name):
        focus = QApplication.focusWidget()
        if focus is not None and name != "tooltip":
            focus.clearFocus()                                   # 앞 동작의 포커스 링이 사진에 남지 않게(포커스 링은 별도 시험)
        ui_offscreen.settle(app, 3)
        pixmap = window.grab()
        if not args.check:
            pixmap.save(str(out / f"{tag}_{name}.png"))
        report["shots"][name] = [pixmap.width(), pixmap.height(), round(pixmap.devicePixelRatio(), 2)]

    def audit(window, name):
        report["checks"][name] = {"clipped": ui_offscreen.find_clipping(window), "horizontal_scroll": window.scroll.horizontalScrollBar().maximum() > 0}

    window = make("normal")
    shoot(window, "home")
    audit(window, "home")
    window.state.list_state = "loading"
    window.render()
    shoot(window, "loading")
    audit(window, "loading")
    window.close()
    for scenario in ("empty", "error", "partial", "offline"):
        window = make(scenario)
        if scenario == "error":
            window.screen_widget.findChild(UI.Disclosure).flip()
            ui_offscreen.settle(app)
            window.scroll.verticalScrollBar().setValue(window.scroll.verticalScrollBar().maximum())          # 진단 정보까지 보이게
            ui_offscreen.settle(app)
        shoot(window, scenario)
        audit(window, scenario)
        window.close()
    window = make("normal")
    window.open_drawer(window.state.home_rows()[1].id)
    ui_offscreen.wait_until(app, lambda: window.drawer.x() <= window.width() - window.drawer.width() + 2, 3)
    ui_offscreen.settle(app)
    shoot(window, "drawer")
    report["checks"]["drawer"] = {"clipped": ui_offscreen.find_clipping(window.drawer), "fits_window": window.drawer.width() <= window.width() and window.drawer.height() <= window.height()}
    window.close_drawer()
    window.show_sample_info()
    ui_offscreen.settle(app)
    shoot(window, "dialog")
    report["checks"]["dialog"] = {"clipped": ui_offscreen.find_clipping(window.dialog), "fits_window": window.dialog.height() <= window.height() and window.dialog.width() <= window.width()}
    window.close_dialog()
    badge = next(button for button in window.findChildren(QPushButton) if button.accessibleName() == "예시 데이터")
    window.activateWindow()
    ui_offscreen.wait_until(app, window.isActiveWindow, 2)
    badge.setFocus(Qt.TabFocusReason)                                                      # 키보드 포커스로 툴팁을 띄운다(포커스 링도 함께 보인다)
    ui_offscreen.wait_until(app, QToolTip.isVisible, 2)
    ui_offscreen.settle(app, 3)
    tip = next((w for w in QApplication.topLevelWidgets() if w.metaObject().className() == "QTipLabel" and w.isVisible()), None)
    base = window.grab()
    if tip is not None:                                                                    # 툴팁은 따로 뜨는 작은 창이라 창 사진에 안 찍힌다 — 같은 자리에 겹쳐 그린다
        painter = QPainter(base)
        spot = badge.mapTo(window, QPoint(0, badge.height() + 4))                          # 화면 없는 환경의 가짜 화면(800x800)이 툴팁을 구석으로 밀어내므로, 진짜 앱이 놓는 자리(배지 바로 아래)에 그린다
        painter.drawPixmap(QPoint(min(spot.x(), window.width() - tip.width() - 8), spot.y()), tip.grab())
        painter.end()
    if not args.check:
        base.save(str(out / f"{tag}_tooltip.png"))
    report["shots"]["tooltip"] = [base.width(), base.height(), round(base.devicePixelRatio(), 2)]
    fits = tip is not None and tip.width() >= tip.sizeHint().width() and tip.height() >= tip.sizeHint().height()
    report["checks"]["tooltip"] = {"clipped": [] if fits else ["툴팁이 안 떴거나 글자보다 작다"], "text": QToolTip.text(), "size": [tip.width(), tip.height()] if tip is not None else None,
                                   "focus_ring_on_badge": badge.hasFocus()}
    QToolTip.hideText()
    window.notify("'초안 만들기' 은(는) 다음 단계에서 열려요.")
    ui_offscreen.settle(app)
    shoot(window, "toast")
    report["checks"]["toast"] = {"clipped": ui_offscreen.find_clipping(window)}
    window.close()
    print(json.dumps(report, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", default="ui_shots")
    parser.add_argument("--env", action="append", default=None, help="가로x세로@배율% (여러 번 줄 수 있다)")
    parser.add_argument("--check", action="store_true", help="사진을 저장하지 않고 점검만")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        args.env = args.env[0]
        return child(args)
    results = []
    for env in args.env or ENVS:
        percent = parse_env(env)[2]
        environment = dict(os.environ, PYTHONUTF8="1")
        environment.pop("QT_SCALE_FACTOR", None)
        if percent != 100:
            environment["QT_SCALE_FACTOR"] = str(percent / 100)
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), args.out, "--env", env, "--child"] + (["--check"] if args.check else [])
        done = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8", creationflags=0x08000000 if os.name == "nt" else 0)
        if done.returncode != 0:
            print(f"[{env}] 실패(종료 코드 {done.returncode}) — 오류 마지막 줄: {(done.stderr.strip().splitlines() or [''])[-1][:200]}", file=sys.stderr)
            return 1
        results.append(json.loads(done.stdout.strip().splitlines()[-1]))
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
