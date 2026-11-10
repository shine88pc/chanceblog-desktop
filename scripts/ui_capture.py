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
**키 연결 화면**(P4f)은 환경마다 12장면(카드의 키 구역·등록 대화상자 입력/확인/칸 문제/칸 셋/둘째 키 약관·삭제 확인창·별칭 바꾸기·쓰는 중·저장소 없음·실패 안내·실제 어댑터)을 찍고 점검한다 — `--only keys` 를 주면 이 장면만 찍는다(다른 사진을 다시 만들지 않는다).
**키는 사진에 나오지 않는다**: 입력 칸은 점으로만 보이고(가짜 글 열두 자), 이름은 모두 가짜이며, 실제 어댑터 장면도 이 도구가 만든 임시 폴더와 프로그램 안의 가짜 보관소만 쓴다(자격 증명 관리자는 건드리지 않는다).
**주제 후보 화면**(D-270)은 환경마다 20장면(기본·거르기·글 검색·상세·상세의 아래쪽·자동 초안 중지 후보·점수 계산 전 후보·빈 목록 셋(보관함 없음·후보 없음·거른 결과 없음)·옛 구조·읽는 중·읽기 오류·만들 수 없을 때의 준비 안내·후보 만들기 확인창·만든 뒤·좁은 창과 그 서랍·실제 어댑터 둘)을 찍고 점검한다 — 후보·채널 이름은 모두 가짜이고(`예시 후보 가` …) 실제 어댑터 장면은 임시 폴더에만 쓴다.
**초안 작성 화면**(D-280부터 D-289까지, 글 모양 점검 D-315)은 환경마다 19장면(글 모양 점검 셋(결과 있음·본문이 변경됨·최소 창)과 기본(협찬 줄이 있는 초안)·소프트웨어 초안·`모든 글 공통` 펼침·만드는 방법 펼침·복사 직후·분야 못 읽는 초안의 복사 전 확인창·고친 글의 확인창·거의 안 고친 초안의 안내·거절·후보 없음·읽는 중·찾지 못함·오류·좁은 창·실제 어댑터 둘)을 찍고 점검한다 — 후보·블로그 이름·글은 모두 가짜이고 실제 어댑터 장면은 임시 폴더에만 쓴다(클립보드·주소 열기는 기록만 하는 가짜). `--only drafts` 를 주면 이 장면만 찍는다.
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

    if getattr(args, "only", "") == "keys":                                              # 키 연결 장면만(다른 사진은 건드리지 않는다)
        keys_shots(app, ui_offscreen, args, report, logical, tag, out)
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if getattr(args, "only", "") == "drafts":                                            # 초안 작성 장면만(다른 사진은 건드리지 않는다)
        drafts_shots(app, ui_offscreen, args, report, logical, tag, out)
        print(json.dumps(report, ensure_ascii=False))
        return 0
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
    keys_shots(app, ui_offscreen, args, report, logical, tag, out)
    candidates_shots(app, ui_offscreen, args, report, logical, tag, out)
    drafts_shots(app, ui_offscreen, args, report, logical, tag, out)
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
    """블로그 관리 화면(P4b) 사진·점검 — 기본·저장 시도 뒤 칸 오류·저장 결과·빈 슬롯(등록 카드)·읽는 중·읽기 오류·삭제 확인창·좁은 창(900×560)·실제 어댑터(임시 폴더 — 저장 결과까지)·주제 설정 구역(P4c — 폼 안쪽 스크롤을 구역으로 옮긴 장면과 우선·제외에 같은 낱말을 넣은 겹침 오류 장면).
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

    def scroll_to_topic(window):
        """폼 안쪽 스크롤을 '주제 설정' 구역(제목·설명이 함께 보이게)으로 옮긴다 — 폼은 안쪽 스크롤이라 새 구역은 첫 화면 아래에 있다."""
        from chanceblog_desktop.ui.core.text import T
        ui = window.screen_widget.blogs_ui
        content = ui.form_scroll.widget()
        heading = next(label for label in content.findChildren(UI.Label) if label.plain_text() == T["blogs_sec_topic"])
        ui.form_scroll.verticalScrollBar().setValue(max(0, heading.mapTo(content, heading.rect().topLeft()).y() - 12))
        ui_offscreen.settle(app, 3)

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
    window = make(blogs.FakeBlogsProvider())                                           # 주제 설정(P4c) — 폼 안쪽 스크롤을 새 구역으로 옮겨 우선·제외 키워드 칸과 선호 글 유형 칩을 보인다(가짜 낱말만)
    scroll_to_topic(window)
    shoot(window, "blogs_topic")
    audit(window, "blogs_topic")
    window.blog_edit("exclude_keywords", "예시 제외어, 예시 키워드 둘")                  # 우선과 제외에 같은 낱말 — 저장을 시도하면 두 칸 옆에 쉬운 문장이 보이고 서비스는 부르지 않는다
    window.blog_save()
    ui_offscreen.settle(app)                                                           # 저장 시도가 첫 오류 칸을 문장까지 보이게 스크롤한다(그 위치 그대로 찍는다 — 작은 창에서도 오류 문장이 보여야 하는 장면)
    shoot(window, "blogs_topic_invalid")
    audit(window, "blogs_topic_invalid")
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


def keys_shots(app, ui_offscreen, args, report, logical, tag, out):
    """키 연결 화면(P4f) 사진·점검 — 설정 카드의 키 구역(예시 — 페이지 전체)·등록 대화상자(입력·칸 문제·확인 단계·칸이 셋인 것·둘째 키 약관 확인)·삭제 확인창·별칭 바꾸기·쓰는 중·키 저장소를 못 쓰는 환경·실패 안내·실제 어댑터(저장 뒤).
    **키는 사진에 나오지 않는다** — 입력 칸은 점으로만 보이고(가짜 글 열두 자 — 키가 아니다) 이름은 모두 가짜(`예시 키 1` …)이며 실제 어댑터도 이 도구가 만든 임시 폴더와 프로그램 안의 가짜 보관소만 쓴다(자격 증명 관리자는 건드리지 않는다).
    점검은 글자 잘림·눌려 잘린 부품·가로 스크롤과 '대화상자가 창 안에 들어오는가'(`fits_window`)다."""
    import tempfile
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget
    from chanceblog_desktop.ui.core import keys as key_core
    from chanceblog_desktop.ui.core.clock import FixedClock
    from chanceblog_desktop.ui.core.services import FakeHomeProvider
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import key_parts
    from chanceblog_desktop.ui.qt.shell import AppShell

    def make(provider):
        window = AppShell(FakeHomeProvider(), connections=provider, autoload=False, clock=FixedClock(CAPTURE_TIME))
        window.resize(*logical)
        window.show()
        window.go("settings")
        ui_offscreen.wait_until(app, lambda: window.state.conn_state != "loading", 10)
        ui_offscreen.settle(app)
        for accordion in window.screen_widget.findChildren(UI.Accordion):
            if not accordion.is_open:
                accordion.flip()
        ui_offscreen.settle(app)
        return window

    def settled(window):
        """쓰기가 끝나고 새 값을 읽어 다시 그릴 때까지 기다린다."""
        ui_offscreen.wait_until(app, lambda: not window.state.keys.busy and window.state.keys.pending is None, 10)
        ui_offscreen.wait_until(app, lambda: window.state.conn_state != "loading" and not window.state.conn_loading, 10)
        ui_offscreen.settle(app, 6)

    def audit(window, name):
        dialog = window.dialog
        inside = (not dialog.is_open) or window.rect().contains(dialog.geometry())
        report["checks"][name] = {"clipped": ui_offscreen.find_clipping(window) + ui_offscreen.find_squeezed(window), "horizontal_scroll": window.scroll.horizontalScrollBar().maximum() > 0, "fits_window": bool(inside)}

    def shoot(window, name, whole=False):
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()                                                         # 앞 동작의 포커스 링이 사진에 남지 않게(포커스 링은 별도 시험)
        if whole:                                                                      # 페이지 전체 — 창을 아주 길게 늘려 찍고 마지막 위젯 아래까지만 남긴다
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

    def click(button):
        QTest.mouseClick(button, Qt.LeftButton)
        ui_offscreen.settle(app, 4)

    def register_button(window, purpose):
        return next(widget for widget in window.screen_widget.findChildren(QAbstractButton) if widget.property("focus_key") == f"key-register:{purpose}")

    def row_of(window, purpose):
        return next(row for row in window.screen_widget.findChildren(key_parts.KeyRow) if row.purpose == purpose)

    dots = "x" * 12                                                                    # 가짜 글 열두 자 — 칸에는 점으로만 보인다(키가 아니다)
    window = make(key_core.FakeKeysProvider("normal"))                                 # 예시 카드 — 행·배지·단추·꺼진 이유·'키 등록'
    shoot(window, "keys_cards", whole=True)
    audit(window, "keys_cards")
    window.close()
    window = make(key_core.FakeKeysProvider("not_connected"))                          # 키가 하나도 없는 처음 모습에서 등록 대화상자
    click(register_button(window, "image_provider"))
    form = window.key_form
    shoot(window, "keys_register")                                                     # 입력 단계 — 처음 포커스는 첫 키 칸
    audit(window, "keys_register")
    form.secret_edits["access_key"].setText(dots)
    click(form.next_button)
    shoot(window, "keys_register_confirm")                                             # 확인 단계 — 서비스·제공자·별칭만, 처음 포커스는 취소
    audit(window, "keys_register_confirm")
    click(form.back_button)
    form.secret_edits["access_key"].setText("")
    click(form.next_button)
    shoot(window, "keys_register_invalid")                                             # 빈 칸 — 문제는 칸 옆 문장
    audit(window, "keys_register_invalid")
    window.key_cancel()
    click(register_button(window, "blogger"))                                          # 칸이 셋인 가장 큰 대화상자
    for edit in window.key_form.secret_edits.values():
        edit.setText(dots)
    shoot(window, "keys_register_three")
    audit(window, "keys_register_three")
    window.key_cancel()
    window.close()
    window = make(key_core.FakeKeysProvider("not_connected"))                          # 둘째 키 — AI 보조에 첫 키를 넣어 두면 둘째 키 등록이 약관 확인을 묻는다
    click(register_button(window, "ai_assist"))
    form = window.key_form
    form.secret_edits["key"].setText("x" * 24)                                         # 첫 키는 실제로 저장된다(가짜 공급자 — 메모리) — 서비스의 최소 글자 수를 넘는 가짜 글
    click(form.next_button)
    click(form.save_button)
    settled(window)
    click(register_button(window, "ai_assist"))
    form = window.key_form
    form.secret_edits["key"].setText(dots)
    form.alias_edit.setText("둘째 키")
    click(form.next_button)
    shoot(window, "keys_register_terms")                                               # 약관 안내와 확인 칸(확인하기 전에는 저장이 꺼져 있다)
    audit(window, "keys_register_terms")
    window.key_cancel()
    window.close()
    window = make(key_core.FakeKeysProvider("normal"))
    click(row_of(window, "image_provider").buttons["delete"])
    shoot(window, "keys_delete")                                                       # 삭제 확인창 — 처음 포커스는 취소
    audit(window, "keys_delete")
    window.close_dialog()
    click(row_of(window, "image_provider").buttons["rename"])
    shoot(window, "keys_rename")
    audit(window, "keys_rename")
    window.close_dialog()
    window.close()
    provider = key_core.FakeKeysProvider("normal")                                     # 쓰는 중 — 단추가 모두 꺼지고 안내 띠가 보인다(창을 닫으면 일도 취소된다)
    window = make(provider)
    provider.delay = 30
    click(row_of(window, "image_provider").buttons["state:off"])
    shoot(window, "keys_busy")
    audit(window, "keys_busy")
    window.close()
    window = make(key_core.FakeKeysProvider("normal", store_ready=False))              # 키 저장소를 못 쓰는 환경 — 오류가 아니라 상태
    shoot(window, "keys_nostore", whole=True)
    audit(window, "keys_nostore")
    window.close()
    provider = key_core.FakeKeysProvider("normal")                                     # 실패 안내 — 쉬운 문장
    window = make(provider)

    def failing(*_args):
        raise key_core.make_failure("io", "SAMPLE_FILE_WRITE_FAILED")
    provider.set_key_state = failing
    click(row_of(window, "image_provider").buttons["state:off"])
    settled(window)
    shoot(window, "keys_failed")
    audit(window, "keys_failed")
    window.close()
    with tempfile.TemporaryDirectory() as tmp:                                         # 실제 어댑터 — 임시 폴더·가짜 보관소에 가짜 이름·값으로 저장한 뒤의 모습(예시 표시 없음)
        from chanceblog_desktop.security.keystore import MemoryStore
        from chanceblog_desktop.service.context import Context, Settings, Workspace
        from chanceblog_desktop.ui.keys_adapter import ServiceKeysProvider
        workspace = Workspace(Path(tmp) / "data")
        ctx = Context(workspace, Settings(workspace.settings_path), backend=None, keystore=MemoryStore())
        window = make(ServiceKeysProvider(context_factory=lambda data_dir=None: ctx))
        click(register_button(window, "ai_assist"))
        form = window.key_form
        form.alias_edit.setText("예시 키 하나")
        form.secret_edits["key"].setText("example-ai-key-" + "0" * 12)
        click(form.next_button)
        click(form.save_button)
        settled(window)
        shoot(window, "keys_real", whole=True)
        audit(window, "keys_real")
        window.close()


def candidates_shots(app, ui_offscreen, args, report, logical, tag, out):
    """주제 후보 화면(D-270) 사진·점검 — 기본·거르기·글 검색·상세(고정 창 또는 서랍)·상세의 아래쪽·자동 초안 중지 후보·점수 계산 전 후보·빈 목록 셋·옛 구조·읽는 중·읽기 오류·준비 안내·후보 만들기 확인창·만든 뒤·좁은 창(900×560)과 그 서랍·실제 어댑터 둘(임시 폴더).
    **후보·채널 이름은 모두 가짜**(`예시 후보 가` … — 실제 블로그 이름·후보 제목은 어디에도 없다)이고 실제 어댑터도 이 도구가 만든 임시 폴더만 읽고 쓴다(사용자 데이터 폴더는 건드리지 않는다). 점검은 글자 잘림(눌려 반쯤 잘린 부품 포함)·가로 스크롤과
    '고정 상세 창·서랍이 창 안에 들어오는가'(`fits_window`)·대화상자가 창 안에 들어오는가·카드 열 수가 규칙대로인가(`columns`)다."""
    import tempfile
    from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton
    from chanceblog_desktop.ui.core import candidates as cd
    from chanceblog_desktop.ui.core import part_rules
    from chanceblog_desktop.ui.core.clock import FixedClock
    from chanceblog_desktop.ui.core.services import FakeHomeProvider
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt.shell import AppShell

    def make(provider, wait=True, size=None):
        window = AppShell(FakeHomeProvider(), candidates=provider, autoload=False, clock=FixedClock(CAPTURE_TIME), clipboard=lambda value: True)
        window.resize(*(size or logical))
        window.show()
        window.go("topics")
        if wait:
            ui_offscreen.wait_until(app, lambda: window.state.candidates.state != "loading" and not window.state.candidates.loading, 10)
        ui_offscreen.settle(app, 8)
        return window

    def ids(window):
        return {card["title"]: card["id"] for card in window.state.candidates_view()["grid"]["cards"]}

    def find_id(window, part):
        return next(value for key, value in ids(window).items() if part in key)

    def search_box(window):
        return next(widget for widget in window.screen_widget.findChildren(QLineEdit) if widget.property("focus_key") == "cand-query")

    def open_card(window, candidate_id):
        window.cand_open(candidate_id)
        ui_offscreen.wait_until(app, lambda: window.detail_pane.isVisible() or (window.drawer.is_open and window.drawer.x() <= window.width() - window.drawer.width() + 2), 3)
        ui_offscreen.settle(app, 8)

    def scroll_detail_down(window, section=None):
        """상세를 아래로 내린다 — `section`(구역 제목)이 있으면 그 구역이 위에 오게, 없으면 맨 아래."""
        scroll = window.detail_pane.scroll if window.detail_pane.isVisible() else window.drawer.scroll
        target = scroll.verticalScrollBar().maximum()
        if section:
            for label in scroll.widget().findChildren(QLabel):
                if getattr(label, "plain_text", lambda: label.text())() == section:
                    target = min(target, max(0, label.mapTo(scroll.widget(), label.rect().topLeft()).y() - 24))
                    break
        scroll.verticalScrollBar().setValue(target)
        ui_offscreen.settle(app, 6)

    def audit(window, name):
        found = {"clipped": ui_offscreen.find_clipping(window) + ui_offscreen.find_squeezed(window), "horizontal_scroll": window.scroll.horizontalScrollBar().maximum() > 0}
        layout = part_rules.detail_layout(window.width())
        ui = getattr(window.screen_widget, "cand_ui", None)
        if ui is not None and ui.grid is not None:
            found["columns"] = ui.columns == layout.columns
        if window.detail_pane.isVisible():                                             # 고정 상세 창이 창 안에 있고 안쪽에 가로 스크롤이 없다
            found["fits_window"] = window.detail_pane.geometry().right() <= window.width() and window.detail_pane.height() <= window.height() and window.detail_pane.width() == layout.detail_width
            found["pane_horizontal_scroll"] = window.detail_pane.scroll.horizontalScrollBar().maximum() > 0
        elif window.drawer.is_open:
            found["fits_window"] = window.drawer.width() <= window.width() and window.drawer.height() <= window.height()
            found["pane_horizontal_scroll"] = window.drawer.scroll.horizontalScrollBar().maximum() > 0
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

    def press_make_and_wait(window, want_dialog):
        window.cand_make()
        ui_offscreen.wait_until(app, lambda: (window.dialog.is_open if want_dialog else window.state.candidates.preview is not None), 10)
        ui_offscreen.settle(app, 8)

    def press_dialog_ok(window):
        next(widget for widget in window.dialog.findChildren(QPushButton) if widget.property("focus_key") == "dialog-ok").click()

    window = make(cd.FakeCandidatesProvider())                                         # 기본 — 거르기 카드·카드 격자(열 수는 창 폭 규칙)·고정 상세 창의 안내(서랍 방식이면 없다)
    shoot(window, "cand")
    audit(window, "cand")
    window.cand_channel("naver_a")                                                     # 거르기 — 채널·점수 구간 칩·`더 거르기`(주제 묶음 칩)·결과 개수·거르기 풀기
    window.cand_band("high")
    window.cand_toggle_filters()
    ui_offscreen.settle(app, 8)
    shoot(window, "cand_filters")
    audit(window, "cand_filters")
    window.cand_reset_filters()
    window.cand_toggle_filters()                                                       # `더 거르기` 를 닫는다(아래 장면은 기본 모양)
    search_box(window).setText("영양제")                                                # 글 검색 — 제목·키워드(칠 때는 카드 격자만 다시 놓는다)
    window.cand_query("영양제")
    ui_offscreen.settle(app, 8)
    shoot(window, "cand_search")
    audit(window, "cand_search")
    window.cand_reset_filters()
    open_card(window, find_id(window, "예시 후보 가 —"))                               # 상세 — 점수 링·점수 구성·추천 이유·최근 관심도(상대값)·Seed 출처·안전 표시·기본 정보
    shoot(window, "cand_detail")
    audit(window, "cand_detail")
    scroll_detail_down(window)
    shoot(window, "cand_detail_more")
    audit(window, "cand_detail_more")
    open_card(window, find_id(window, "먹으면 바로 낫는"))                              # 자동 초안 중지 후보 — `주의`·`자동 초안 중지` 배지와 안전 표시
    scroll_detail_down(window, "안전 표시")
    shoot(window, "cand_stop")
    audit(window, "cand_stop")
    open_card(window, find_id(window, "점수 계산 전인 예"))                             # 점수 계산 전 — 링 없이 `점수 계산 전`(0점 링이 아니다)
    shoot(window, "cand_none")
    audit(window, "cand_none")
    window.close()
    for scenario, name in (("no_store", "cand_empty_nostore"), ("empty", "cand_empty_none"), ("old_structure", "cand_old")):    # 서로 다른 빈 안내 — 보관함 없음·후보 없음·옛 구조
        window = make(cd.FakeCandidatesProvider(scenario))
        shoot(window, name)
        audit(window, name)
        window.close()
    window = make(cd.FakeCandidatesProvider())                                         # 거른 결과 없음 — 거르기 풀기 단추가 있는 안내
    search_box(window).setText("없는낱말")
    window.cand_query("없는낱말")
    ui_offscreen.settle(app, 8)
    shoot(window, "cand_empty_filtered")
    audit(window, "cand_empty_filtered")
    window.close()
    window = make(cd.FakeCandidatesProvider(delay=30), wait=False)                     # 읽는 중 — 일이 끝나기 전에 찍는다(창을 닫으면 읽기도 취소된다)
    shoot(window, "cand_loading")
    audit(window, "cand_loading")
    window.close()
    window = make(cd.FakeCandidatesProvider("error"))                                  # 읽기 오류 — 쓰는 길 없이 다시 읽기·진단 정보(펼침)
    window.screen_widget.findChild(UI.Disclosure).flip()
    ui_offscreen.settle(app)
    shoot(window, "cand_error")
    audit(window, "cand_error")
    window.close()
    window = make(cd.FakeCandidatesProvider("lacking"))                                # 만들 수 없을 때의 준비 안내 — 무엇이 모자란지와 이미 있는 화면으로 가는 단추(쓰기 단추 없음)
    press_make_and_wait(window, want_dialog=False)
    shoot(window, "cand_prep")
    audit(window, "cand_prep")
    window.close()
    window = make(cd.FakeCandidatesProvider())                                         # 후보 만들기 확인창 — 처음 포커스는 취소, 개수·Seed·지워지지 않는다·키·네트워크를 쓰지 않는다
    press_make_and_wait(window, want_dialog=True)
    shoot(window, "cand_dialog")
    audit_dialog(window, "cand_dialog")
    press_dialog_ok(window)                                                            # 만들기 — 가짜 공급자라 메모리에서만 더해진다
    ui_offscreen.wait_until(app, lambda: len(window.state.candidates.rows()) == 18 and not window.state.candidates.busy and not window.state.candidates.loading, 10)
    ui_offscreen.settle(app, 8)
    shoot(window, "cand_made")
    audit(window, "cand_made")
    window.close()
    window = make(cd.FakeCandidatesProvider(), size=(900, 560))                        # 최소 창 — 서랍 방식·2열·가로 스크롤 없음
    shoot(window, "cand_narrow")
    audit(window, "cand_narrow")
    open_card(window, find_id(window, "예시 후보 가 —"))                               # 최소 창의 서랍 — 같은 내용
    shoot(window, "cand_narrow_detail")
    audit(window, "cand_narrow_detail")
    window.close()
    with tempfile.TemporaryDirectory() as tmp:                                          # 실제 어댑터 — 보관함이 아직 없다는 안내·예시 표시 없음·가짜 Seed 를 승인해 두고 후보 만들기를 한 결과(임시 폴더에만 쓴다)
        import json as json_module
        from chanceblog_desktop.security.keystore import MemoryStore
        from chanceblog_desktop.service import topic_files
        from chanceblog_desktop.service.context import Context, Settings, Workspace
        from chanceblog_desktop.topics import seeds as seed_rules
        from chanceblog_desktop.ui.candidates_adapter import ServiceCandidatesProvider
        from chanceblog_desktop.ui.core import seeds
        workspace = Workspace(Path(tmp) / "data")
        ctx = Context(workspace, Settings(workspace.settings_path), backend=None, keystore=MemoryStore())
        provider = ServiceCandidatesProvider(context_factory=lambda data_dir=None: ctx)
        window = make(provider)
        shoot(window, "cand_real_first")
        audit(window, "cand_real_first")
        window.close()
        paths = topic_files.topic_paths(ctx.workspace)
        paths.folder.mkdir(parents=True, exist_ok=True)
        paths.seeds.write_bytes(json_module.dumps(seed_rules.seeds_to_dict(seeds.FakeSeedsProvider().seeds), ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + bytes([10]))
        window = make(provider)
        press_make_and_wait(window, want_dialog=True)
        press_dialog_ok(window)
        ui_offscreen.wait_until(app, lambda: len(window.state.candidates.rows()) > 0 and not window.state.candidates.busy and not window.state.candidates.loading, 60)
        ui_offscreen.settle(app, 8)
        first = next(iter(ids(window).values()), None)
        if first is not None:
            open_card(window, first)
        shoot(window, "cand_real")
        audit(window, "cand_real")
        report["checks"]["cand_real"]["made"] = len(window.state.candidates.rows())
        window.close()


def drafts_shots(app, ui_offscreen, args, report, logical, tag, out):
    """초안 작성 화면(D-280~D-289) 사진·점검 — 기본(협찬 줄이 있는 초안)·소프트웨어 초안(이 글에만 해당하는 줄이 없다)·`모든 글 공통` 펼침·만드는 방법 펼침·분야 못 읽는 초안의 복사 전 확인창·고친 글의 확인창·거의 안 고친 초안의 안내·복사 직후·거절(자동 초안 중지 후보)·후보 없음·읽는 중·찾지 못함·오류·좁은 창(900×560)·실제 어댑터(임시 폴더).
    **후보·블로그 이름·글은 모두 가짜**(`예시 …` — 실제 블로그 이름·후보 제목·본문은 어디에도 없다)이고 실제 어댑터 장면도 이 도구가 만든 임시 폴더만 읽는다(사용자 데이터 폴더·자격 증명 관리자는 건드리지 않는다). 클립보드·주소 열기는 이 도구가 끼운 가짜(기록만 한다)다.
    점검은 글자 잘림(눌려 반쯤 잘린 부품 포함)·가로 스크롤(바깥·안쪽)·'아래 고정 행동 줄이 창 안에 보이는가'(`fits_window`)·칸 수가 규칙대로인가(`side_by_side`)·대화상자가 창 안에 들어오는가다."""
    import tempfile
    from PySide6.QtWidgets import QAbstractButton, QScrollArea
    from chanceblog_desktop.ui.core import candidates as cd
    from chanceblog_desktop.ui.core import draft_rules
    from chanceblog_desktop.ui.core import drafts
    from chanceblog_desktop.ui.core.clock import FixedClock
    from chanceblog_desktop.ui.core.services import FakeHomeProvider
    from chanceblog_desktop.ui.qt.shell import AppShell

    def engine(number, topic, keyword, channel="naver_a", subs=()):
        return cd.build_candidate(number, topic, channel, "top", keywords=(keyword, *subs))

    generic = engine(901, "예시 후보 가 — 분야를 알 수 없는 안내", "예시 낱말 가", subs=("예시 보조 가",))      # 분야 낱말이 없다 → 분야를 읽지 못함(복사 전 확인창)
    software = engine(902, "예시 AI 서비스 사용법", "예시 AI 서비스")                                           # 이 글에만 해당하는 줄이 없다
    appliance = engine(903, "예시 청소기 고르는 기준", "예시 청소기")                                          # 가전 분야 + 협찬 가능 분야 → 협찬 안내 줄
    stopped = engine(905, "예시 영양제 먹으면 바로 낫는 방법", "예시 영양제", subs=("예시 보조 가",))             # 안전 판정 '자동 초안 중지'
    other = engine(906, "예시 후보 카 — 다른 채널의 예", "예시 낱말 카", channel="blogger_ko")
    copied, opened = [], []

    def candidates_with(*extra):
        provider = cd.FakeCandidatesProvider()
        provider.candidates = [*provider.candidates, *extra]
        return provider

    def make(provider=None, drafts_provider=None, size=None, wait=True):
        window = AppShell(FakeHomeProvider(), candidates=provider or candidates_with(generic, software, appliance, stopped, other), drafts=drafts_provider, autoload=False, clock=FixedClock(CAPTURE_TIME),
                          clipboard=lambda value: copied.append(value) or True, url_opener=lambda url: opened.append(url) or True)
        window.resize(*(size or logical))
        window.show()
        window.go("topics")
        if wait:
            ui_offscreen.wait_until(app, lambda: window.state.candidates.state != "loading" and not window.state.candidates.loading, 10)
        ui_offscreen.settle(app, 8)
        return window

    def candidate_id(window, candidate):
        return next(row.candidate.candidate_id for row in window.state.candidates.rows() if row.candidate.candidate_id == candidate.candidate_id)

    def draft_of(window, candidate, wait=True):
        """후보를 골라 `이 주제로 만들기` 를 누른다 — 초안이 보일 때까지(또는 읽는 중 모양으로) 기다린다."""
        window.cand_open(candidate_id(window, candidate))
        ui_offscreen.settle(app, 8)
        window.cand_make_draft()
        if wait:
            ui_offscreen.wait_until(app, lambda: window.state.drafts.state != "loading" and not window.state.drafts.busy, 15)
        ui_offscreen.settle(app, 8)

    def back(window):
        window.go("topics")
        ui_offscreen.wait_until(app, lambda: window.state.candidates.state != "loading" and not window.state.candidates.loading, 10)
        ui_offscreen.settle(app, 8)

    def ui_of(window):
        return getattr(window.screen_widget, "drf_ui", None)

    def audit(window, name):
        found = {"clipped": ui_offscreen.find_clipping(window) + ui_offscreen.find_squeezed(window), "horizontal_scroll": window.scroll.horizontalScrollBar().maximum() > 0}
        inner = window.screen_widget.findChild(QScrollArea) if window.screen_widget is not None else None
        if inner is not None:
            found["inner_horizontal_scroll"] = inner.horizontalScrollBar().maximum() > 0
        ui = ui_of(window)
        if ui is not None and ui.action_bar is not None:                                    # 아래 고정 행동 줄이 창 안에 보이고 칸 수가 규칙대로다
            bar = ui.action_bar
            found["fits_window"] = bar.isVisible() and bar.mapTo(window, bar.rect().bottomLeft()).y() <= window.height()
            found["side_by_side"] = ui.side == draft_rules.side_by_side(window.width())
        report["checks"][name] = found

    def audit_dialog(window, name):
        report["checks"][name] = {"clipped": ui_offscreen.find_clipping(window.dialog), "fits_window": window.dialog.height() <= window.height() and window.dialog.width() <= window.width()}

    def shoot(window, name):
        from PySide6.QtWidgets import QApplication
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()                                                           # 앞 동작의 포커스 링이 사진에 남지 않게(포커스 링은 별도 시험)
        ui_offscreen.settle(app, 3)
        pixmap = window.grab()
        if not args.check:
            pixmap.save(str(out / f"{tag}_{name}.png"))
        report["shots"][name] = [pixmap.width(), pixmap.height(), round(pixmap.devicePixelRatio(), 2)]

    def scroll_right_to(window, key):
        """오른쪽 칸의 `key` 접이식이 보이게 안쪽 스크롤을 내린다."""
        inner = window.screen_widget.findChild(QScrollArea)
        ui = ui_of(window)
        target = ui.accordions[key]
        inner.verticalScrollBar().setValue(max(0, target.mapTo(inner.widget(), target.rect().topLeft()).y() - 40))
        ui_offscreen.settle(app, 6)

    window = make()
    draft_of(window, appliance)                                                         # 기본 — 협찬 안내 줄이 있는 초안(이 글에만 해당 1건·모든 글 공통 접힘)
    shoot(window, "drafts")
    audit(window, "drafts")
    ui_of(window).accordions["common"].toggle.click()                                   # 모든 글 공통 펼침
    ui_offscreen.settle(app, 6)
    scroll_right_to(window, "common")
    shoot(window, "drafts_checks")
    audit(window, "drafts_checks")
    window.state.drafts.set_common_open(False)
    back(window)
    draft_of(window, software)                                                          # 소프트웨어 — 이 글에만 해당하는 줄이 없다·만드는 방법 펼침
    shoot(window, "drafts_clean")
    audit(window, "drafts_clean")
    window.drf_toggle_options()
    ui_offscreen.settle(app, 8)
    shoot(window, "drafts_options")
    audit(window, "drafts_options")
    window.drf_toggle_options()
    window.drf_copy("title")                                                            # 복사 직후 — 단추가 `✓ 제목 복사됨` 으로 바뀐 모습(1.8초 동안)
    ui_offscreen.settle(app, 4)
    shoot(window, "drafts_copied")
    audit(window, "drafts_copied")
    report["checks"]["drafts_copied"]["copied"] = len(copied)
    window.state.drafts.leave()
    back(window)
    draft_of(window, generic)                                                           # 분야를 읽지 못한 초안 — 본문 복사는 확인창이 먼저(처음 포커스는 취소)
    window.drf_copy("body")
    ui_offscreen.settle(app, 8)
    shoot(window, "drafts_gate")
    audit_dialog(window, "drafts_gate")
    window.close_dialog()
    editor = ui_of(window).editor
    editor.setPlainText(editor.toPlainText() + "\n\n" + "직접 확인한 사실을 한 문단으로 적었어요. 이 서비스는 모든 사람에게 100% 효과가 있어요. " * 3)       # 고친 글에서 확인이 필요한 문장이 걸린다
    ui_offscreen.settle(app, 6)
    window.drf_copy("body")
    ui_offscreen.settle(app, 8)
    shoot(window, "drafts_gate_claims")
    audit_dialog(window, "drafts_gate_claims")
    window.close_dialog()
    window.state.drafts.leave()
    window.close()
    window = make()                                                                     # 거의 안 고친 초안 — 분야가 읽히고 이 글에만 해당하는 줄이 없는 초안의 본문 복사는 막지 않는 안내
    draft_of(window, software)
    window.drf_copy("body")
    ui_offscreen.settle(app, 8)
    shoot(window, "drafts_soft")
    audit_dialog(window, "drafts_soft")
    window.close_dialog()
    window.state.drafts.leave()
    window.close()
    window = make()                                                                     # 거절 — 안전 판정 '자동 초안 중지' 후보를 코드로 불러도 공급자를 부르지 않는다(단추는 꺼져 있다)
    window.cand_open(candidate_id(window, stopped))
    ui_offscreen.settle(app, 8)
    window.state.drafts.open_target(window.state.candidates.draft_target())
    window.go("drafts")
    window.drf_retry()
    ui_offscreen.settle(app, 8)
    shoot(window, "drafts_refused")
    audit(window, "drafts_refused")
    window.close()
    window = make()                                                                     # 후보 없음 — 메뉴로 열었을 때
    window.go("drafts")
    ui_offscreen.settle(app, 8)
    shoot(window, "drafts_empty")
    audit(window, "drafts_empty")
    window.close()
    provider = candidates_with(generic, software, appliance, stopped, other)
    slow = drafts.FakeDraftsProvider(lambda: tuple(provider.candidates), delay=30)      # 읽는 중 — 일이 끝나기 전에 찍는다(창을 닫으면 작업도 취소된다)
    window = make(provider, slow)
    draft_of(window, software, wait=False)
    shoot(window, "drafts_loading")
    audit(window, "drafts_loading")
    window.close()
    window = make(provider, drafts.FakeDraftsProvider(lambda: ()))                      # 찾지 못함 — 보관함에서 그 후보가 없어졌을 때
    draft_of(window, software)
    shoot(window, "drafts_notfound")
    audit(window, "drafts_notfound")
    window.close()
    broken = drafts.FakeDraftsProvider(lambda: tuple(provider.candidates), fail=drafts.DraftFailure("예시 오류", code="SAMPLE_DRAFT_FAILED", kind="other"))
    window = make(provider, broken)                                                     # 오류 — 종류별 고정 문장·다시 만들기·진단 정보(펼침)
    draft_of(window, software)
    from chanceblog_desktop.ui.qt import components as UI
    window.screen_widget.findChild(UI.Disclosure).flip()
    ui_offscreen.settle(app, 6)
    shoot(window, "drafts_error")
    audit(window, "drafts_error")
    window.close()
    sample = "첫 문단이에요.\n\n안녕" + chr(0x200B) + "하세요 {{이름}} 님 가격&nbsp;12 좋아요 좋아요 좋아요\n\n" + chr(0x60) * 3 + "\n코드 줄\n" + chr(0x60) * 3             # 글 모양 점검 사진용 가짜 글 — 보이지 않는 글자·자리표시·HTML 표시·같은 낱말 반복·코드 블록 표시

    def garbage_checked(size=None):
        """초안을 만들고 가짜 글을 넣은 뒤 `검사하기` 를 눌러 글 모양 점검 결과가 카드에 보이게 한다."""
        win = make(size=size)
        draft_of(win, software)
        ui_of(win).editor.setPlainText(sample)
        ui_offscreen.settle(app, 6)
        win.drf_inspect()
        ui_offscreen.wait_until(app, lambda: not win.state.drafts.garbage.running, 15)
        ui_offscreen.settle(app, 8)
        return win

    def scroll_garbage(win):
        """글 모양 점검 카드가 사진 위쪽에 보이게 안쪽 스크롤을 내린다(카드는 오른쪽 칸 — 좁은 창에서는 아래쪽에 쌓인다)."""
        inner = win.screen_widget.findChild(QScrollArea)
        target = ui_of(win).garbage.status.parentWidget()                             # 카드 틀(상태 줄이 들어 있는 카드)
        inner.verticalScrollBar().setValue(max(0, target.mapTo(inner.widget(), target.rect().topLeft()).y() - 24))
        ui_offscreen.settle(app, 6)

    window = garbage_checked()                                                          # 글 모양 점검(N-2) — 결과 있음: 종류별 항목과 `무시`·`모두 무시`
    scroll_garbage(window)
    shoot(window, "drafts_garbage")
    audit(window, "drafts_garbage")
    ui_of(window).garbage.buttons[0].click()                                            # 하나를 무시하고 글을 더 쳤다 — `본문이 변경됨`·`무시한 1건 다시 보기`
    editor = ui_of(window).editor
    editor.setPlainText(editor.toPlainText() + " 더")
    ui_offscreen.settle(app, 8)
    scroll_garbage(window)
    shoot(window, "drafts_garbage_stale")
    audit(window, "drafts_garbage_stale")
    window.state.drafts.leave()
    window.close()
    window = garbage_checked((900, 560))                                                # 최소 창 — 한 칸으로 쌓인 카드
    scroll_garbage(window)
    shoot(window, "drafts_garbage_narrow")
    audit(window, "drafts_garbage_narrow")
    window.state.drafts.leave()
    window.close()
    window = make(size=(900, 560))                                                      # 최소 창 — 한 칸으로 쌓인다·아래 고정 줄이 창 안에 있다
    draft_of(window, appliance)
    shoot(window, "drafts_narrow")
    audit(window, "drafts_narrow")
    window.state.drafts.leave()
    window.close()
    with tempfile.TemporaryDirectory() as tmp:                                          # 실제 어댑터 — 임시 폴더에 가짜 Seed 를 승인해 두고 후보를 만든 뒤 그 후보로 초안을 만든다(프로필 파일은 없다 → 기본값으로 만들고 `네이버 글쓰기 열기` 는 꺼진다). 실제 블로그 이름·후보 제목·본문은 없다
        import json as json_module
        from chanceblog_desktop.security.keystore import MemoryStore
        from chanceblog_desktop.service import topic_files
        from chanceblog_desktop.service.context import Context, Settings, Workspace
        from chanceblog_desktop.topics import seeds as seed_rules
        from chanceblog_desktop.ui.candidates_adapter import ServiceCandidatesProvider
        from chanceblog_desktop.ui.core import seeds
        from chanceblog_desktop.ui.drafts_adapter import ServiceDraftsProvider
        workspace = Workspace(Path(tmp) / "data")
        ctx = Context(workspace, Settings(workspace.settings_path), backend=None, keystore=MemoryStore())
        paths = topic_files.topic_paths(ctx.workspace)
        paths.folder.mkdir(parents=True, exist_ok=True)
        paths.seeds.write_bytes(json_module.dumps(seed_rules.seeds_to_dict(seeds.FakeSeedsProvider().seeds), ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + bytes([10]))
        window = make(ServiceCandidatesProvider(context_factory=lambda data_dir=None: ctx), ServiceDraftsProvider(context_factory=lambda data_dir=None: ctx))
        window.cand_make()                                                              # 후보 만들기 → 미리 보기 → 확인창의 `만들기`(임시 폴더에만 쓴다)
        ui_offscreen.wait_until(app, lambda: window.dialog.is_open, 20)
        ui_offscreen.settle(app, 6)
        next(button for button in window.dialog.findChildren(QAbstractButton) if button.property("focus_key") == "dialog-ok").click()
        ui_offscreen.wait_until(app, lambda: len(window.state.candidates.rows()) > 0 and not window.state.candidates.busy and not window.state.candidates.loading, 60)
        ui_offscreen.settle(app, 8)
        usable = next((row for row in window.state.candidates.rows() if not row.stop and row.candidate.channel in ("naver_a", "naver_b")), None)
        if usable is not None:
            window.cand_open(usable.candidate.candidate_id)
            ui_offscreen.settle(app, 8)
            window.cand_make_draft()
            ui_offscreen.wait_until(app, lambda: window.state.drafts.state != "loading" and not window.state.drafts.busy, 30)
            ui_offscreen.settle(app, 8)
        shoot(window, "drafts_real")
        audit(window, "drafts_real")
        report["checks"]["drafts_real"]["state"] = window.state.drafts.state
        window.state.drafts.leave()
        window.close()
        window = make(ServiceCandidatesProvider(context_factory=lambda data_dir=None: ctx), ServiceDraftsProvider(context_factory=lambda data_dir=None: ctx))
        window.go("drafts")                                                             # 메뉴로 열면 후보를 고르지 않았다는 안내 한 줄
        ui_offscreen.settle(app, 8)
        shoot(window, "drafts_real_empty")
        audit(window, "drafts_real_empty")
        window.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", default="ui_shots")
    parser.add_argument("--env", action="append", default=None, help="가로x세로@배율% (여러 번 줄 수 있다)")
    parser.add_argument("--check", action="store_true", help="사진을 저장하지 않고 점검만")
    parser.add_argument("--gallery", action="store_true", help="앱 화면 대신 공통 부품 모음(개발용)을 찍고 점검한다")
    parser.add_argument("--only", choices=("keys", "drafts"), default="", help="키 연결 화면(P4f) 또는 초안 작성 화면(P4e) 장면만 찍고 점검한다")
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
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), args.out, "--env", env, "--child"] + (["--check"] if args.check else []) + (["--gallery"] if args.gallery else []) + (["--only", args.only] if args.only else [])
        done = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8", creationflags=0x08000000 if os.name == "nt" else 0)
        if done.returncode != 0:
            print(f"[{env}] 실패(종료 코드 {done.returncode}) — 오류 마지막 줄: {(done.stderr.strip().splitlines() or [''])[-1][:200]}", file=sys.stderr)
            return 1
        results.append(json.loads(done.stdout.strip().splitlines()[-1]))
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
