"""'사진 정리' 창의 화면 배율 점검용 자식 프로세스(시험이 부른다 — 시험 모듈이 아니다). 배율은 프로세스가 시작될 때 환경 변수 `QT_SCALE_FACTOR` 로 정해야 해서(앱 코드에는 배율 값이 없다) 시험이 배율마다 이 파일을 따로 돌린다.
사용: python photo_scale_probe.py <논리 가로> <논리 세로>  → 표준 출력 마지막 줄에 JSON 한 줄(사진 정리 창의 여러 모습에서 글자 잘림·삐져나옴·가로 스크롤·창 안에 들어옴·아래 단추 줄이 보임).
창은 화면에 띄우지 않는다(offscreen). 사진 파일은 만들지도 읽지도 않는다(가짜 공급자·가짜 미리보기). **이 검사는 Qt 자체의 High DPI 흉내이고 실제 윈도 배율 렌더는 운영자 PC 에서 본다.**"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import ui_offscreen  # noqa: E402

ui_offscreen.prepare_environment()
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from chanceblog_desktop.ui.core import photo_view as pv  # noqa: E402
from chanceblog_desktop.ui.core import services  # noqa: E402
from chanceblog_desktop.ui.qt import app as qapp  # noqa: E402
from chanceblog_desktop.ui.qt import shell as shell_module  # noqa: E402


def preview(_path):
    pixmap = QPixmap(24, 18)
    pixmap.fill(QColor("#336699"))
    return pixmap


def main(width, height):
    ui_offscreen.install_system_fonts()
    app = qapp.make_app()
    window = shell_module.AppShell(services.FakeHomeProvider(), autoload=False, photos=pv.FakePhotoProvider(), photo_preview_maker=preview)
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
        buttons = (form.add_button, form.all_button, form.close_button)
        reports.append({"label": label, "inside": window.rect().contains(dialog.geometry()), "hscroll": form.scroll.horizontalScrollBar().maximum(), "clipping": ui_offscreen.find_clipping(dialog),
                        "squeezed": ui_offscreen.find_squeezed(dialog), "buttons": all(window.rect().contains(button.mapTo(window, button.rect().bottomRight())) and button.isVisible() for button in buttons)})

    fit("빈 창")
    names = [f"C:/Users/가나다/Pictures/{'긴이름' * 14}-{number:02d}.jpg" for number in range(1, 4)]
    board.add_paths(names + ["relative.jpg", "C:/x/y.gif"])
    form.refresh()
    fit("사진 세 장과 못 넣은 파일")
    card = form.rows["p001"]
    card.subject.edit.setText("가" * 60)
    card.note.edit.setText("나" * 301)
    fit("한도를 넘긴 글")
    card.note.edit.setText("비 오는 날")
    form.all_button.click()
    fit("모두 확인 줄")
    form.confirm_buttons[-1].click()
    form.rows["p003"].remove.click()
    fit("지운 뒤 되돌리기")
    form.lists_toggle.click()
    fit("목록 고치기")
    print(json.dumps({"scale": window.devicePixelRatioF(), "logical": [window.width(), window.height()], "reports": reports}, ensure_ascii=False))
    window.close()


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
