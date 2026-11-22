"""설정 화면의 백업·복원 카드가 '복원을 시작하지 않았어요' 안내를 제대로 그리는지의 PySide6 시험(L8b, 결정 D-570) — 지금 보관함에 앱이 만들지 않는 구조가 있어 복원 직전 사본으로 되돌릴 수 없을 때.

**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_backup_live_structure`). 창 만들기·누르기·기다리기는 `test_ui_qt_backup` 의 틀을 그대로 쓴다.

지키는 것:
  1) 실제 서비스를 임시 폴더에서 카드 단추로 끝까지 돌린다 — 지금 글 보관함에 뷰가 있으면 복원 단추(확인창 '복원하기')가 첫 문장 '복원을 시작하지 않았어요' + 이유 한 줄 + 다음에 할 일 한 줄로 끝나고, 지금 데이터·파일은 그대로이며 안전 사본을 만들지 않았다.
     창 위젯의 어떤 글에도 개체 이름·오류 코드·데이터 폴더 경로가 없다.
  2) 그 안내(첫 문장 + 이유 줄 + 다음에 할 일 줄)는 어느 창 크기(최소 900×560 포함)에서도 틀 안이다 — 가로 스크롤·글자 잘림·눌림이 없다.
"""
import contextlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import backup_support as bs  # noqa: E402
import key_leak_support as leak  # noqa: E402
import test_service_backup_live_structure as tls  # noqa: E402
import test_ui_qt_backup as qtb  # noqa: E402

from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.ui import backups_adapter  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

if qtb.HAVE:
    ui_offscreen = qtb.ui_offscreen


@unittest.skipUnless(qtb.HAVE, "PySide6 가 설치되어 있지 않다")
class LiveStructureCardTest(qtb.Base):
    def test_the_real_service_refuses_with_the_easy_sentence_and_line_and_changes_nothing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world = bs.World.cached(tmp.name)
        provider = backups_adapter.ServiceBackupsProvider(str(world.root), context_factory=lambda data_dir=None: world.ctx)
        window = self.make(provider)
        self.click(self.card(window).create_button)
        self.wait_write(window)
        row = self.card(window).rows[0]
        with contextlib.closing(sqlite3.connect(str(world.path("chanceblog.db")))) as database:
            database.execute(f"CREATE VIEW {tls.CANARY}_mine AS SELECT project_id, title FROM projects")
            database.commit()
        world.ctx.clock.advance(seconds=30)
        before = world.data_digests()
        self.restore_through_dialog(window, row.name)
        self.wait_write(window)
        card = self.card(window)
        self.assertEqual((self.notice_level(card), self.notice_text(card)), ("error", T["backup_fail_restore_unstarted"]))
        self.assertEqual([line.plain_text() for line in card.notice_lines], [T["backup_restore_live_structure"], T["backup_restore_live_structure_help"]])
        self.assertEqual(world.data_digests(), before, "아무것도 바뀌지 않았다")
        self.assertFalse((world.ctx.workspace.backups_dir / bf.SAFETY_FOLDER).exists(), "시작하지 않았으니 안전 사본도 만들지 않았다")
        shown = " ".join(text for _label, text in leak.widget_texts(window))
        for hidden in (tls.CANARY, "RESTORE_FAILED", "live_structure", str(world.root)):
            self.assertNotIn(hidden, shown.replace(str(world.ctx.workspace.backups_dir), ""), hidden)

    def test_the_notice_stays_inside_the_window_at_every_size(self):
        notice = ("error", T["backup_fail_restore_unstarted"], (T["backup_restore_live_structure"], T["backup_restore_live_structure_help"]))
        for size in qtb.SIZES:
            with self.subTest(size=size):
                window = self.make(qtb.Stepped(), size=size)
                window.state.backups.notice = notice
                window.render()
                self.settle(3)
                card = self.card(window)
                self.assertEqual((self.notice_level(card), self.notice_text(card)), ("error", T["backup_fail_restore_unstarted"]))
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0)
                self.assertEqual(ui_offscreen.find_clipping(window), [])
                self.assertEqual(ui_offscreen.find_squeezed(window.screen_widget), [])
                window.close()


if __name__ == "__main__":
    unittest.main()
