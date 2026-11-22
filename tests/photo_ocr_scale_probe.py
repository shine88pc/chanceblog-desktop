"""'사진 정리' 창의 **글자 읽기 칸** 화면 배율 점검용 자식 프로세스(시험이 부른다 — 시험 모듈이 아니다, 결정 D-513). 배율은 프로세스가 시작될 때 환경 변수 `QT_SCALE_FACTOR` 로 정해야 해서 시험이 배율마다 이 파일을 따로 돌린다.
사용: python photo_ocr_scale_probe.py <논리 가로> <논리 세로>  → 표준 출력 마지막 줄에 JSON 한 줄(글자 읽기 칸의 여러 모습에서 글자 잘림·삐져나옴·가로 스크롤·창 안에 들어옴·아래 단추 줄이 보임).
창은 화면에 띄우지 않는다(offscreen). 사진 파일은 만들지도 읽지도 않는다(가짜 공급자·가짜 읽기·가짜 미리보기). **이 검사는 Qt 자체의 High DPI 흉내이고 실제 윈도 배율 렌더는 운영자 PC 에서 본다.**"""
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import ui_offscreen  # noqa: E402

ui_offscreen.prepare_environment()
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from chanceblog_desktop.ui.core import photo_ocr_view as pov  # noqa: E402
from chanceblog_desktop.ui.core import photo_view as pv  # noqa: E402
from chanceblog_desktop.ui.core import services  # noqa: E402
from chanceblog_desktop.ui.qt import app as qapp  # noqa: E402
from chanceblog_desktop.ui.qt import shell as shell_module  # noqa: E402

LINES = tuple(f"차림표 {number} 번 메뉴 이름이 조금 길어요 {number * 1000:,}원" for number in range(1, 25))


class Gate(pov.FakeOcrProvider):
    """`release()` 전에는 읽지 않고 기다리는 가짜 공급자 — 읽는 중인 모습을 붙잡는다."""

    def __init__(self):
        super().__init__(default=pov.OcrOutcome(LINES))
        self.gate = threading.Event()

    def read(self, job):
        self.gate.wait(30)
        return super().read(job)


def preview(_path):
    pixmap = QPixmap(24, 18)
    pixmap.fill(QColor("#336699"))
    return pixmap


def main(width, height):
    ui_offscreen.install_system_fonts()
    app = qapp.make_app()
    clock = [1000.0]
    provider = Gate()
    window = shell_module.AppShell(services.FakeHomeProvider(), autoload=False, photos=pv.FakePhotoProvider(), photo_preview_maker=preview, ocr=provider,
                                   ocr_options=dict(monotonic=lambda: clock[0], reader=lambda path, size: (1, 1, b"abc")))
    window.resize(width, height)
    window.show()
    ui_offscreen.settle(app, 6)
    form = window.photos_open()
    ui_offscreen.settle(app, 8)
    board = window.state.drafts.photos
    reports = []

    def fit(label):
        ui_offscreen.settle(app, 6)
        dialog = window.dialog
        ui_offscreen.wait_until(app, lambda: not ui_offscreen.find_clipping(dialog) and not ui_offscreen.find_squeezed(dialog), 5)      # 겹친 배치(줄 → 칸 → 사진 줄 → 창)는 층마다 이벤트 루프를 한 바퀴씩 돌아 자리를 잡는다 — 잡힐 때까지(최대 5초) 기다린 뒤 잘림을 본다(5초가 지나도 남으면 진짜 잘림이다)
        ui_offscreen.settle(app, 2)
        buttons = (form.add_button, form.all_button, form.close_button)
        blocks = [card.ocr_block for card in form.rows.values() if card.ocr_block is not None]
        reports.append({"label": label, "inside": window.rect().contains(dialog.geometry()), "hscroll": form.scroll.horizontalScrollBar().maximum(),
                        "list_hscroll": max([block.scroll.horizontalScrollBar().maximum() for block in blocks] or [0]), "clipping": ui_offscreen.find_clipping(dialog), "squeezed": ui_offscreen.find_squeezed(dialog),
                        "buttons": all(window.rect().contains(button.mapTo(window, button.rect().bottomRight())) and button.isVisible() for button in buttons)})

    board.add_paths([f"C:/Users/가나다/Pictures/{'긴이름' * 14}-{number:02d}.jpg" for number in range(1, 3)])
    form.refresh()
    block = form.rows["p001"].ocr_block
    fit("읽기 전")
    block.read_button.click()
    ui_offscreen.settle(app, 4)
    clock[0] += 20
    form.ocr_tick()
    fit("읽는 중·오래 걸림")
    provider.gate.set()
    ui_offscreen.wait_until(app, lambda: block.vm is not None and block.vm["state"] == "done", 20)
    fit("읽은 글 24줄")
    block.lines.setFocus(Qt.TabFocusReason)
    QTest.keyClick(block.lines, Qt.Key_F2)
    block.lines.rows[0].editor.setText("가" * 150)
    fit("고치는 중")
    block.lines.rows[0].editor.setText("900101-1234567")
    QTest.keyClick(block.lines.rows[0].editor, Qt.Key_Return)
    fit("이유가 보이는 줄")
    QTest.keyClick(block.lines.rows[0].editor, Qt.Key_Escape)
    block.all_button.click()
    fit("모두 맞아요 확인 줄")
    block.all_ask.no.click()
    block.read_button.click()
    fit("다시 읽기 확인 줄")
    print(json.dumps({"scale": window.devicePixelRatioF(), "logical": [window.width(), window.height()], "reports": reports}, ensure_ascii=False))
    window.close()


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
