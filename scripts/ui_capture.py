"""화면(홈·상태 화면·연결 전·구역별 상태·서랍·대화상자·툴팁·토스트와 설정 화면의 접이식·여섯 상태·실제 어댑터 모습·사용량 막대 상태)을 **창을 띄우지 않고**(offscreen) 사진으로 찍고, 같은 환경에서 글자 잘림·누르는 칸·가로 스크롤을 점검한다 — 정식 시각 검수 도구(docs/UI_VISUAL_QA.md).

실행(저장소 맨 위 폴더에서, PySide6 가 있는 파이썬으로):
    python scripts/ui_capture.py <저장 폴더> --env 1366x768@100 [--env 1920x1080@125 …] [--check] [--gallery]
검증 환경 `가로x세로@배율%`: 필수 1366x768@100 · 1920x1080@100 · 1920x1080@125, 조건부 1920x1080@150. **이 PC 에서는 윈도 배율을 바꾸지 않으므로** 배율은
Qt 가 직접 지원하는 환경 변수(`QT_SCALE_FACTOR`)로 흉내 낸다 — 프로세스를 시작할 때 정해야 하므로 환경마다 자식 프로세스로 돌리고(앱 코드에는 배율 값이 없다), 창의 논리 크기는 화면 크기를 배율로 나눈 값이다.
실제 윈도 125·150% 렌더·한글 입력기·화면 읽기·개인 PC 확인은 운영자 PC 검증으로 남는다. `--check` 는 사진을 저장하지 않고 점검 결과(JSON)만 낸다.
`--gallery`(개발용, UI-C0) 는 앱 화면 대신 **공통 부품 모음**(`scripts/ui_gallery.py` — 배지·점수 링·구성 막대·사용량 막대·탭·행동 줄·카드 그림자)을 한 장에 담아 찍고 같은 환경에서 글자 잘림·가로 넘침을 점검한다.
사용자 화면·메뉴에는 없는 도구이고 `gui` 명령의 동작·이 도구의 기본 인자는 바뀌지 않는다.
**시계는 고정한다**(UI-C1a): 상단 앱 바의 날짜·시간은 컴퓨터 시계라 다시 찍을 때마다 달라지므로, 사진은 가짜 시계 `FixedClock`(2026-11-06 20:10)로 찍는다 — 같은 코드·같은 환경이면 같은 사진이다(진단 시각 줄도 같은 시계).
**블로그 관리 화면**(P4b)은 환경마다 11장면(기본·고치는 중·저장 시도 뒤 칸 오류·저장 결과·삭제 확인창·빈 슬롯·읽는 중·읽기 오류·좁은 창·실제 어댑터 처음·저장 뒤)을 찍고 점검한다 — 이름은 모두 가짜이고 실제 어댑터 장면은 임시 폴더에만 쓴다. 점검의 '잘림' 에는 눌려 반쯤 잘린 부품(`ui_offscreen.find_squeezed`)이 들어 있고, `fits_window` 는 아래 고정 행동 줄이 창 안에 보이는지다.
**Seed 관리 화면**(D-230)은 환경마다 17장면(기본·거르기·상세 서랍·180일 제안 표시·고치기 오류·승인 결과·새 Seed 폼 둘·일괄 변경 확인창·제안 파일 확인창·빈 목록·읽는 중·읽기 오류·좁은 창과 그 서랍·실제 어댑터 둘)을 찍고 점검한다 — Seed 는 모두 가짜이고 실제 어댑터 장면은 임시 폴더에만 쓴다.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENVS = ("1366x768@100", "1920x1080@100", "1920x1080@125", "1920x1080@150")
CAPTURE_TIME = datetime.datetime(2026, 11, 6, 20, 10)                    # 사진용 고정 시각(금요일 20:10) — 상단 앱 바·진단 시각에 쓴다


def parse_env(text):
    size, _, percent = text.partition("@")
    width, _, height = size.partition("x")
    return int(width), int(height), int(percent or 100)


def gallery_child(args):
    """한 환경에서 부품 모음 한 장의 사진·점검(`--gallery`) — 배율 환경 변수가 켜진 채 시작된 자식 프로세스."""
    sys.path.insert(0, str(HERE))
    import ui_gallery
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from chanceblog_desktop.ui.qt import app as qapp
    general, fixed = ui_offscreen.install_system_fonts()
    app = qapp.make_app()
    width, height, percent = parse_env(args.env)
    logical = (round(width * 100 / percent), round(height * 100 / percent))
    out = Path(args.out)
    if not args.check:
        out.mkdir(parents=True, exist_ok=True)
    page, parts = ui_gallery.build_gallery(logical[0])
    ui_gallery.fit(page, app, ui_offscreen)
    pixmap = page.grab()
    if not args.check:
        pixmap.save(str(out / f"{args.env.replace('@', '_')}_gallery.png"))
    over = ui_gallery.overflow(page)
    report = {"env": args.env, "logical": logical, "scale_factor_env": os.environ.get("QT_SCALE_FACTOR", "1"), "fonts": [general, fixed],
              "shots": {"gallery": [pixmap.width(), pixmap.height(), round(pixmap.devicePixelRatio(), 2)]},
              "checks": {"gallery": {"clipped": ui_offscreen.find_clipping(page), "horizontal_scroll": bool(over), "overflow": over,
                                     "counts": {key: (len(value) if isinstance(value, list) else int(value is not None)) for key, value in parts.items()}}}}
    print(json.dumps(report, ensure_ascii=False))
    return 0


def child(args):
    """한 환경(배율 하나)에서 사진·점검 — 이 프로세스는 배율 환경 변수가 켜진 채 시작되었다."""
    if getattr(args, "gallery", False):
        return gallery_child(args)
    sys.path.insert(0, str(HERE))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QApplication, QPushButton, QToolTip, QWidget
    from chanceblog_desktop.ui.core.clock import FixedClock
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

    def make(scenario, **options):
        window = AppShell(FakeHomeProvider(scenario, **options), autoload=False, clock=FixedClock(CAPTURE_TIME))
        window.resize(*logical)
        window.show()
        window.reload()
        ui_offscreen.wait_until(app, lambda: window.state.list_state != "loading", 10)
        ui_offscreen.settle(app)
        return window

    def shoot(window, name, whole=False):
        focus = QApplication.focusWidget()
        if focus is not None and name != "tooltip":
            focus.clearFocus()                                   # 앞 동작의 포커스 링이 사진에 남지 않게(포커스 링은 별도 시험)
        if whole:                                                # 페이지 전체 — 창을 아주 길게 늘려 찍고 마지막 위젯 아래까지만 남긴다(구역별 상태가 한 장에 다 보이게)
            window.resize(logical[0], 6000)
            ui_offscreen.settle(app, 8)
            bottom = max(w.mapTo(window, w.rect().bottomLeft()).y() for w in window.screen_widget.findChildren(QWidget) if w.isVisible()) + 40
            pixmap = window.grab()
            pixmap = pixmap.copy(QRect(0, 0, pixmap.width(), min(pixmap.height(), round(bottom * pixmap.devicePixelRatio()))))
            window.resize(*logical)
            ui_offscreen.settle(app)
        else:
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
    for name, options in (("home_before_connect", {"board": None}), ("home_sections", {"board": mixed_board()})):             # 새 구역을 안 읽는 공급자(연결 전·집계 전) · 구역마다 다른 상태(한 구역의 문제가 다른 구역을 막지 않는다)
        window = make("normal", **options)
        shoot(window, name, whole=True)
        audit(window, name)
        window.close()
    window = make("normal")
    window.open_drawer(window.state.home_view()["board"]["recommend"][0]["rows"][1]["id"])                          # 추천 줄을 눌러 여는 기존 상세 서랍
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
    settings_shots(app, ui_offscreen, args, report, logical, tag, out)
    blogs_shots(app, ui_offscreen, args, report, logical, tag, out)
    seeds_shots(app, ui_offscreen, args, report, logical, tag, out)
    print(json.dumps(report, ensure_ascii=False))
    return 0


def mixed_board():
    """구역마다 다른 상태의 **가짜** 홈 구역들 — Naver A 추천은 못 읽음·Naver B 추천은 후보 생성 꺼짐·작성 중 초안은 못 읽음·최근 발행은 읽은 글(발행일을 모르는 글 하나·건너뛴 글 하나). 실제 이름·값이 없다."""
    from chanceblog_desktop.ui.core.services import BoardData, ChannelRead, ListRead, RecentRow, ServiceFailure
    from chanceblog_desktop.ui.core.text import T
    broken = ServiceFailure(T["board_err_store"], code="SAMPLE_STORE_UNREADABLE")
    channels = (ChannelRead("A", "블로그 A", True, "failed", "", (), 0, broken), ChannelRead("B", "블로그 B", False, "ok", "", ()))
    recent = ListRead("ok", (RecentRow("p1", "자취방 곰팡이 없애는 순서", "2026-11-03T01:00:00Z", True), RecentRow("p2", "겨울철 실내 습도 관리", None, True)), 1)
    return BoardData(channels, ListRead("failed", (), 0, ServiceFailure(T["board_err_store"], code="SAMPLE_PROJECTS_UNREADABLE")), recent, True)


def real_settings_provider(tmp):
    """실제 어댑터로 읽는 설정 화면 사진용 — 임시 폴더의 데이터 폴더 + 프로그램 안의 가짜 보관소(자격 증명 관리자는 건드리지 않는다)에 **가짜 이름·가짜 값**의 키 항목 셋을 넣는다."""
    from chanceblog_desktop.security.keystore import MemoryStore
    from chanceblog_desktop.service import connections
    from chanceblog_desktop.service.context import Context, Settings, Workspace
    from chanceblog_desktop.ui.adapters import ServiceConnectionsProvider
    workspace = Workspace(Path(tmp) / "data")
    ctx = Context(workspace, Settings(workspace.settings_path), backend=None, keystore=MemoryStore())
    for purpose, name, fields in (("naver_apihub", "예시 키 1", {"client_id": "example-client-001", "client_secret": "example-secret-0001"}), ("image_provider", "예시 키 2", {"access_key": "example-access-key-0002"}),
                                  ("ai_assist", "예시 키 3", {"key": "example-ai-key-0000003"})):
        connections.add_entry(ctx, purpose, name=name, fields=fields, keystore=ctx.keystore)
    return ServiceConnectionsProvider(context_factory=lambda data_dir=None: ctx)


def usage_states_provider():
    """설정 카드의 사용량 막대 상태를 한 장에 보이는 예시 공급자(UI-C1b) — 파랑(79%)·노랑(80%)·빨강(90%)·한도 넘음(120%)·읽지 못함(막대 없이 글). 숫자는 모두 지어낸 예시다(화면에도 `예시` 꼬리표가 붙는다)."""
    from dataclasses import replace
    from chanceblog_desktop.ui.core import services
    usage = {"naver_apihub": services.UsageInfo((("오늘", 79, 100), ("이번 달", 21600, 27000)), True, 30000, "이번 달 사용량이 NAVER API HUB 콘솔 한도의 70%를 넘었습니다 — 아직 정상이지만 사용량을 살펴 주세요.", fail_closed=True),
             "image_provider": services.UsageInfo((("최근 60분", 45, 50),)),
             "ai_assist": services.UsageInfo((("오늘", 120, 100),)),
             "blogger": services.UsageInfo(readable=False)}
    purposes = tuple(replace(item, usage=usage[item.key], entries=item.entries or (services.EntryInfo("예시 키 1", "active", True),)) if item.key in usage else item
                     for item in services.sample_connections("normal"))

    class UsageStates(services.ConnectionsProvider):
        sample = True

        def load_connections(self, progress, cancelled):
            return services.ConnectionsData(purposes=purposes, sample=True, fetched="오늘 09:12")

    return UsageStates()


def settings_shots(app, ui_offscreen, args, report, logical, tag, out):
    """설정 화면(P4a) 사진·점검 — 접이식 기본 모습·모두 펼침(페이지 전체)·읽는 중·빈·오류(진단 정보 펼침)·일부만·오프라인·실제 어댑터 모습·사용량 막대 상태(UI-C1b). 같은 환경에서 글자 잘림·가로 스크롤도 잰다."""
    import tempfile
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication, QWidget
    from chanceblog_desktop.ui.core.clock import FixedClock
    from chanceblog_desktop.ui.core.services import FakeConnectionsProvider, FakeHomeProvider
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt.shell import AppShell

    def make(provider, wait=True):
        window = AppShell(FakeHomeProvider(), connections=provider, autoload=False, clock=FixedClock(CAPTURE_TIME))
        window.resize(*logical)
        window.show()
        window.go("settings")
        if wait:
            ui_offscreen.wait_until(app, lambda: window.state.conn_state != "loading", 10)
        ui_offscreen.settle(app)
        return window

    def open_all(window):
        for accordion in window.screen_widget.findChildren(UI.Accordion):
            if not accordion.is_open:
                accordion.flip()
        ui_offscreen.settle(app)

    def audit(window, name):
        report["checks"][name] = {"clipped": ui_offscreen.find_clipping(window), "horizontal_scroll": window.scroll.horizontalScrollBar().maximum() > 0}

    def shoot(window, name, whole=False):
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()                                                         # 앞 동작의 포커스 링이 사진에 남지 않게(포커스 링은 별도 시험)
        if whole:                                                                      # 페이지 전체 — 창을 아주 길게 늘려 찍고 마지막 눌리는 곳·글자 아래까지만 남긴다
            window.resize(logical[0], 6000)
            ui_offscreen.settle(app, 8)
            bottom = max(w.mapTo(window, w.rect().bottomLeft()).y() for w in window.screen_widget.findChildren(QWidget) if w.isVisible()) + 40
            pixmap = window.grab()
            pixmap = pixmap.copy(QRect(0, 0, pixmap.width(), min(pixmap.height(), round(bottom * pixmap.devicePixelRatio()))))
            window.resize(*logical)
            ui_offscreen.settle(app)
        else:
            ui_offscreen.settle(app, 3)
            pixmap = window.grab()
        if not args.check:
            pixmap.save(str(out / f"{tag}_{name}.png"))
        report["shots"][name] = [pixmap.width(), pixmap.height(), round(pixmap.devicePixelRatio(), 2)]

    window = make(FakeConnectionsProvider("normal"))                                     # 기본 모습 — 문제(한도)가 있는 데이터 묶음만 펼쳐져 있다
    shoot(window, "settings")
    audit(window, "settings")
    open_all(window)                                                                   # 네 묶음을 모두 펼친 페이지 전체 — 연결 상태 다섯 가지·준비 중·한도 줄·예시 꼬리표가 한 장에 보인다
    shoot(window, "settings_all", whole=True)
    audit(window, "settings_all")
    window.close()
    window = make(FakeConnectionsProvider("normal", delay=30), wait=False)               # 읽는 중 — 일이 끝나기 전에 찍는다(창을 닫으면 읽기도 취소된다)
    shoot(window, "settings_loading")
    audit(window, "settings_loading")
    window.close()
    for scenario in ("empty", "error", "partial", "offline"):
        window = make(FakeConnectionsProvider(scenario))
        if scenario == "error":
            window.screen_widget.findChild(UI.Disclosure).flip()                        # 진단 정보를 펼쳐 코드·시각만 있는 것을 보인다
            ui_offscreen.settle(app)
        shoot(window, f"settings_{scenario}")
        audit(window, f"settings_{scenario}")
        window.close()
    with tempfile.TemporaryDirectory() as tmp:                                          # 실제 어댑터 — 예시 표시·꼬리표가 없고 '연결됨' 이 없으며 사용량은 실제 값(0)이다
        window = make(real_settings_provider(tmp))
        open_all(window)
        shoot(window, "settings_real", whole=True)
        audit(window, "settings_real")
        window.close()
    window = make(usage_states_provider())                                              # 사용량 막대의 모든 상태(파랑·노랑·빨강·한도 넘음·못 읽음) — 예시 숫자
    open_all(window)
    shoot(window, "settings_usage", whole=True)
    audit(window, "settings_usage")
    window.close()


def blogs_shots(app, ui_offscreen, args, report, logical, tag, out):
    """블로그 관리 화면(P4b) 사진·점검 — 기본·저장 시도 뒤 칸 오류·저장 결과·빈 슬롯(등록 카드)·읽는 중·읽기 오류·삭제 확인창·좁은 창(900×560)·실제 어댑터(임시 폴더 — 저장 결과까지).
    **이름은 모두 가짜**(`예시 블로그 가` …)이고 실제 어댑터도 이 도구가 만든 임시 폴더만 읽고 쓴다(사용자 데이터 폴더·보관소는 건드리지 않는다). 점검은 글자 잘림·가로 스크롤과 '아래 고정 행동 줄이 창 안에 보이는가'(`fits_window`)다."""
    import tempfile
    from PySide6.QtWidgets import QApplication
    from chanceblog_desktop.ui.core import blogs
    from chanceblog_desktop.ui.core.clock import FixedClock
    from chanceblog_desktop.ui.core.services import FakeHomeProvider
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt.shell import AppShell

    def make(provider, wait=True, size=None):
        window = AppShell(FakeHomeProvider(), blogs=provider, autoload=False, clock=FixedClock(CAPTURE_TIME), file_picker=lambda *_: "")
        window.resize(*(size or logical))
        window.show()
        window.go("blogs")
        if wait:
            ui_offscreen.wait_until(app, lambda: window.state.blogs.state != "loading" and not window.state.blogs.loading, 10)
        ui_offscreen.settle(app)
        return window

    def wait_write(window):
        ui_offscreen.wait_until(app, lambda: not window.state.blogs.busy and window.state.blogs.pending is None, 10)
        ui_offscreen.settle(app)

    def audit(window, name, narrow=False):
        found = {"clipped": ui_offscreen.find_clipping(window) + ui_offscreen.find_squeezed(window), "horizontal_scroll": window.scroll.horizontalScrollBar().maximum() > 0}      # 눌려 잘린 부품(`find_squeezed`)도 잘림으로 센다
        ui = getattr(window.screen_widget, "blogs_ui", None)
        if ui is not None and ui.bar is not None and not narrow:                      # 아래 고정 행동 줄(저장 단추)이 창 안에 보인다 — 좁은 창은 목록이 위로 올라 페이지가 스크롤된다
            found["fits_window"] = ui.bar.mapTo(window, ui.bar.rect().bottomLeft()).y() <= window.height()
        report["checks"][name] = found

    def shoot(window, name):
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()                                                         # 앞 동작의 포커스 링이 사진에 남지 않게(포커스 링은 별도 시험)
        ui_offscreen.settle(app, 3)
        pixmap = window.grab()
        if not args.check:
            pixmap.save(str(out / f"{tag}_{name}.png"))
        report["shots"][name] = [pixmap.width(), pixmap.height(), round(pixmap.devicePixelRatio(), 2)]

    window = make(blogs.FakeBlogsProvider())                                           # 기본 — 네이버 A 선택(채널 색 배지·카드 왼쪽 줄)·저장·되돌리기·복제는 꺼져 있고 삭제만 켜져 있다
    shoot(window, "blogs")
    audit(window, "blogs")
    window.blog_edit("alias", "새 별명")                                               # 고치는 중 — 저장 전 변경 배지(카드·폼 머리)·저장·되돌리기가 켜진다
    window.blog_edit("display_name", "")
    ui_offscreen.settle(app)
    shoot(window, "blogs_editing")
    audit(window, "blogs_editing")
    window.blog_save()                                                                 # 저장 시도 — 서비스를 부르지 않고 문제 칸 옆에 쉬운 문장, 알림 줄
    ui_offscreen.settle(app)
    shoot(window, "blogs_invalid")
    audit(window, "blogs_invalid")
    window.blog_edit("display_name", "예시 블로그 가")
    window.blog_save()                                                                 # 저장 — 가짜 공급자(메모리)에만 쓴다
    wait_write(window)
    shoot(window, "blogs_saved")
    audit(window, "blogs_saved")
    window.blog_delete()                                                               # 삭제 확인창 — 처음 포커스는 취소, 지우기는 위험 단추
    ui_offscreen.settle(app)
    shoot(window, "blogs_delete")
    report["checks"]["blogs_delete"] = {"clipped": ui_offscreen.find_clipping(window.dialog), "fits_window": window.dialog.height() <= window.height() and window.dialog.width() <= window.width()}
    window.close_dialog()
    window.close()
    window = make(blogs.FakeBlogsProvider("empty"))                                    # 모든 슬롯이 비었다 — 등록 카드 다섯과 '등록' 폼
    shoot(window, "blogs_empty")
    audit(window, "blogs_empty")
    window.close()
    window = make(blogs.FakeBlogsProvider(delay=30), wait=False)                       # 읽는 중 — 일이 끝나기 전에 찍는다(창을 닫으면 읽기도 취소된다)
    shoot(window, "blogs_loading")
    audit(window, "blogs_loading")
    window.close()
    window = make(blogs.FakeBlogsProvider("error"))                                    # 읽기 오류 — 폼 없이 다시 읽기·진단 정보(펼침)
    window.screen_widget.findChild(UI.Disclosure).flip()
    ui_offscreen.settle(app)
    shoot(window, "blogs_error")
    audit(window, "blogs_error")
    window.close()
    window = make(blogs.FakeBlogsProvider(), size=(900, 560))                          # 최소 창 — 슬롯 목록이 폼 위로 올라가고 페이지가 세로로 스크롤된다(가로 스크롤은 없다)
    shoot(window, "blogs_narrow")
    audit(window, "blogs_narrow", narrow=True)
    window.close()
    with tempfile.TemporaryDirectory() as tmp:                                          # 실제 어댑터 — 파일이 아직 없다는 안내·예시 표시 없음·가짜 이름을 넣고 저장한 결과(임시 폴더에만 쓴다)
        from chanceblog_desktop.security.keystore import MemoryStore
        from chanceblog_desktop.service.context import Context, Settings, Workspace
        from chanceblog_desktop.ui.blogs_adapter import ServiceBlogsProvider
        workspace = Workspace(Path(tmp) / "data")
        ctx = Context(workspace, Settings(workspace.settings_path), backend=None, keystore=MemoryStore())
        window = make(ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx))
        shoot(window, "blogs_real_first")
        audit(window, "blogs_real_first")
        for name, value in (("display_name", "예시 블로그 가"), ("blog_ref", "example-blog-a"), ("main_topics", "예시 주제 하나, 예시 주제 둘"), ("color_preset", "warm_lifestyle")):
            window.blog_edit(name, value)
        window.blog_save()
        wait_write(window)
        shoot(window, "blogs_real")
        audit(window, "blogs_real")
        window.close()


def seeds_shots(app, ui_offscreen, args, report, logical, tag, out):
    """Seed 관리 화면(D-230) 사진·점검 — 기본 목록·거르기·상세 서랍·180일 제안 표시·고치기 오류·승인 결과·새 Seed 폼(빈 것·오류)·일괄 변경 확인창·제안 파일 확인창·빈 목록·읽는 중·읽기 오류·좁은 창(900×560)·좁은 창의 서랍·실제 어댑터(임시 폴더).
    **Seed 는 모두 가짜**(`예시 낱말 가` … — 실제 Seed 목록·블로그 이름은 어디에도 없다)이고 실제 어댑터도 이 도구가 만든 임시 폴더만 읽고 쓴다(사용자 데이터 폴더는 건드리지 않는다). 점검은 글자 잘림(눌려 반쯤 잘린 부품 포함)·가로 스크롤과
    '서랍의 아래 고정 행동 줄이 창 안에 보이는가'(`fits_window`)·대화상자가 창 안에 들어오는가다."""
    import json as json_module
    import tempfile
    from PySide6.QtWidgets import QApplication
    from chanceblog_desktop.ui.core import seeds
    from chanceblog_desktop.ui.core.clock import FixedClock
    from chanceblog_desktop.ui.core.services import FakeHomeProvider
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt.shell import AppShell

    def make(provider, wait=True, size=None, picked=""):
        window = AppShell(FakeHomeProvider(), seeds=provider, autoload=False, clock=FixedClock(CAPTURE_TIME), file_picker=lambda *_: picked)
        window.resize(*(size or logical))
        window.show()
        window.go("seed")
        if wait:
            ui_offscreen.wait_until(app, lambda: window.state.seeds.state != "loading" and not window.state.seeds.loading, 10)
        ui_offscreen.settle(app)
        return window

    def wait_write(window):
        ui_offscreen.wait_until(app, lambda: not window.state.seeds.busy and window.state.seeds.pending is None, 10)
        ui_offscreen.settle(app)

    def open_detail(window, seed_id):
        window.seed_open(seed_id)
        ui_offscreen.wait_until(app, lambda: window.drawer.x() <= window.width() - window.drawer.width() + 2, 3)
        ui_offscreen.settle(app)

    def audit(window, name):
        found = {"clipped": ui_offscreen.find_clipping(window) + ui_offscreen.find_squeezed(window), "horizontal_scroll": window.scroll.horizontalScrollBar().maximum() > 0}
        ui = getattr(window, "seeds_drawer_ui", None) if window.drawer.is_open else None
        if ui is not None and ui.bar is not None:                                      # 서랍의 아래 고정 행동 줄이 창 안에 보인다
            found["fits_window"] = ui.bar.mapTo(window, ui.bar.rect().bottomLeft()).y() <= window.height() and window.drawer.width() <= window.width()
        report["checks"][name] = found

    def audit_dialog(window, name):
        report["checks"][name] = {"clipped": ui_offscreen.find_clipping(window.dialog), "fits_window": window.dialog.height() <= window.height() and window.dialog.width() <= window.width()}

    def shoot(window, name):
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()                                                         # 앞 동작의 포커스 링이 사진에 남지 않게(포커스 링은 별도 시험)
        ui_offscreen.settle(app, 3)
        pixmap = window.grab()
        if not args.check:
            pixmap.save(str(out / f"{tag}_{name}.png"))
        report["shots"][name] = [pixmap.width(), pixmap.height(), round(pixmap.devicePixelRatio(), 2)]

    window = make(seeds.FakeSeedsProvider())                                           # 기본 — 승인 전 안내 줄·개수 칩·채널별 쓸 수 있는 Seed 와 후보 생성 켜짐·거르기·일괄 변경 줄·Seed 줄 목록
    shoot(window, "seed")
    audit(window, "seed")
    window.seed_toggle_filters()                                                       # 거르기 — 상태·소속·중요도 칩과 결과 개수·조건 지우기
    window.seed_status("proposed")
    window.seed_scope("naver_a")
    ui_offscreen.settle(app)
    shoot(window, "seed_filters")
    audit(window, "seed_filters")
    window.seed_reset_filters()
    window.seed_toggle_filters()
    open_detail(window, "EX001")                                                       # 상세 서랍 — 승인 전 Seed: 승인하기(주요)·쉬게 두기·저장·되돌리기
    shoot(window, "seed_detail")
    audit(window, "seed_detail")
    window.close_drawer()
    open_detail(window, "EX009")                                                       # 180일 쓰이지 않은 사용 중 Seed — '쉬게 할까요?' 는 제안일 뿐 상태는 그대로다
    shoot(window, "seed_idle")
    audit(window, "seed_idle")
    window.close_drawer()
    open_detail(window, "EX002")                                                       # 고치기 오류 — 서비스를 부르지 않고 문제 칸 옆에 쉬운 문장, 알림 줄
    window.seed_edit("reason", "가" * 250)
    window.seed_edit("priority_keywords", "겹침")
    window.seed_edit("excluded_keywords", "겹침")
    window.seed_save()
    ui_offscreen.settle(app)
    shoot(window, "seed_invalid")
    audit(window, "seed_invalid")
    window.seed_revert()
    window.seed_state("approve")                                                       # 승인 — 확인창 없이 저장(가짜 공급자 — 메모리에만), 서랍은 새 상태에 맞는 행동으로 바뀐다
    wait_write(window)
    shoot(window, "seed_saved")
    audit(window, "seed_saved")
    window.close_drawer()
    window.seed_open_new()                                                             # 새 Seed 등록 — 빈 폼(승인 전으로 등록)과 저장 시도 뒤 칸 오류
    ui_offscreen.wait_until(app, lambda: window.drawer.x() <= window.width() - window.drawer.width() + 2, 3)
    ui_offscreen.settle(app)
    shoot(window, "seed_new")
    audit(window, "seed_new")
    window.seed_create()
    ui_offscreen.settle(app)
    shoot(window, "seed_new_invalid")
    audit(window, "seed_new_invalid")
    window.close()
    window = make(seeds.FakeSeedsProvider())                                           # 일괄 변경 확인창 — 처음 포커스는 취소, 개수·처음 몇 개 이름·바뀐 뒤 채널별 수
    for seed_id in ("EX001", "EX002", "EX003", "EX004", "EX005", "EX006"):
        window.seed_check(seed_id)
    ui_offscreen.settle(app)
    window.seed_bulk("activate")
    ui_offscreen.settle(app)
    shoot(window, "seed_bulk")
    audit_dialog(window, "seed_bulk")
    window.close_dialog()
    window.close()
    window = make(seeds.FakeSeedsProvider(), picked="C:/예시 폴더/예시 제안.json")        # 제안 파일 확인창 — 읽어 본 개수·모두 승인 전으로 등록(파일은 읽지 않고 가짜 공급자가 예시를 돌려준다)
    window.seed_import()
    ui_offscreen.wait_until(app, lambda: window.dialog.is_open, 10)
    ui_offscreen.settle(app)
    shoot(window, "seed_import")
    audit_dialog(window, "seed_import")
    window.close_dialog()
    window.close()
    window = make(seeds.FakeSeedsProvider("empty"))                                    # 아직 Seed 가 없다 — 빈 목록 안내
    shoot(window, "seed_empty")
    audit(window, "seed_empty")
    window.close()
    window = make(seeds.FakeSeedsProvider(delay=30), wait=False)                       # 읽는 중 — 일이 끝나기 전에 찍는다(창을 닫으면 읽기도 취소된다)
    shoot(window, "seed_loading")
    audit(window, "seed_loading")
    window.close()
    window = make(seeds.FakeSeedsProvider("error"))                                    # 읽기 오류 — 쓰는 길 없이 다시 읽기·진단 정보(펼침)
    window.screen_widget.findChild(UI.Disclosure).flip()
    ui_offscreen.settle(app)
    shoot(window, "seed_error")
    audit(window, "seed_error")
    window.close()
    window = make(seeds.FakeSeedsProvider(), size=(900, 560))                          # 최소 창 — 개수·거르기·일괄 변경 줄이 다음 줄로 넘어가고 가로 스크롤은 없다
    shoot(window, "seed_narrow")
    audit(window, "seed_narrow")
    open_detail(window, "EX001")                                                       # 최소 창의 서랍 — 아래 고정 행동 줄이 창 안에 보인다
    shoot(window, "seed_narrow_detail")
    audit(window, "seed_narrow_detail")
    window.close()
    with tempfile.TemporaryDirectory() as tmp:                                          # 실제 어댑터 — 파일이 아직 없다는 안내·예시 표시 없음·가짜 Seed 를 넣고 승인한 결과(임시 폴더에만 쓴다)
        from chanceblog_desktop.security.keystore import MemoryStore
        from chanceblog_desktop.service import topic_files
        from chanceblog_desktop.service.context import Context, Settings, Workspace
        from chanceblog_desktop.topics import seeds as seed_rules
        from chanceblog_desktop.ui.seeds_adapter import ServiceSeedsProvider
        workspace = Workspace(Path(tmp) / "data")
        ctx = Context(workspace, Settings(workspace.settings_path), backend=None, keystore=MemoryStore())
        provider = ServiceSeedsProvider(context_factory=lambda data_dir=None: ctx)
        window = make(provider)
        shoot(window, "seed_real_first")
        audit(window, "seed_real_first")
        window.close()
        paths = topic_files.topic_paths(ctx.workspace)
        paths.folder.mkdir(parents=True, exist_ok=True)
        paths.seeds.write_bytes((json_module.dumps(seed_rules.seeds_to_dict(seeds.FakeSeedsProvider().seeds), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        window = make(provider)
        open_detail(window, "EX001")
        window.seed_state("approve")
        wait_write(window)
        shoot(window, "seed_real")
        audit(window, "seed_real")
        window.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", default="ui_shots")
    parser.add_argument("--env", action="append", default=None, help="가로x세로@배율% (여러 번 줄 수 있다)")
    parser.add_argument("--check", action="store_true", help="사진을 저장하지 않고 점검만")
    parser.add_argument("--gallery", action="store_true", help="앱 화면 대신 공통 부품 모음(개발용)을 찍고 점검한다")
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
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), args.out, "--env", env, "--child"] + (["--check"] if args.check else []) + (["--gallery"] if args.gallery else [])
        done = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8", creationflags=0x08000000 if os.name == "nt" else 0)
        if done.returncode != 0:
            print(f"[{env}] 실패(종료 코드 {done.returncode}) — 오류 마지막 줄: {(done.stderr.strip().splitlines() or [''])[-1][:200]}", file=sys.stderr)
            return 1
        results.append(json.loads(done.stdout.strip().splitlines()[-1]))
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
