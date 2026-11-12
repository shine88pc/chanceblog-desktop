"""화면 '정보' 카드의 한 줄(개인 PC 제한 시험용, 미서명 Package)과 커밋 앞 7자리(`ui/qt/screens.py` 의 `info_card`) PySide6 시험 — 창을 띄우지 않는다(offscreen).

**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — D-32). 사용자 폴더·보관소·클립보드는 건드리지 않는다(가짜 공급자, 데이터 폴더를 읽지 않음).
지키는 것: 묶음 정보가 있으면 버전 줄에 커밋이 붙고 안내 한 줄이 따로 생기며(글이 줄어들지 않게 줄바꿈), 없으면 카드가 개발 화면과 같은 글 개수다. 실제 앱 틀에서 설정 → 정보를 펴도 같다.
"""
import importlib.util
import sys
import unittest

import packaging_support as ps
from chanceblog_desktop.ui.core import services
from chanceblog_desktop.ui.core import version as app_version

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ps.ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()                       # 창을 띄우지 않는다(offscreen) + 윈도 글꼴 폴더
    from PySide6.QtWidgets import QLabel, QWidget
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import components as UI
    from chanceblog_desktop.ui.qt import screens as S
    from chanceblog_desktop.ui.qt import shell as shell_module
    from chanceblog_desktop.ui.core import settings_view as sv

COMMIT = "0123456789abcdef0123456789abcdef01234567"
PACKAGE = app_version.VersionInfo("v0.1.0-preview.1", "file", COMMIT[:7], app_version.PACKAGE_NOTICE)
PLAIN = app_version.VersionInfo("v0.1.0-preview.1", "file")
TRIAL = app_version.VersionInfo("v0.1.0-preview.1", "file", COMMIT[:7], f"{app_version.PACKAGE_NOTICE} · {app_version.PACKAGE_TRIAL_NOTICE}")


@unittest.skipUnless(HAVE, "PySide6 가 있어야 한다")
class InfoCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp.make_app([])

    def card_labels(self, version):
        frame = S.info_card(sv.info_vm(None, True, None, version))
        self.addCleanup(frame.deleteLater)
        return frame, [label.plain_text() for label in frame.findChildren(UI.Label)]

    def test_a_plain_version_makes_the_same_card_as_the_dev_screen(self):
        _frame, labels = self.card_labels(PLAIN)
        self.assertEqual(labels[:2], ["버전", "v0.1.0-preview.1"])
        self.assertNotIn(app_version.PACKAGE_NOTICE, " ".join(labels))
        self.assertNotIn("커밋", " ".join(labels))

    def test_a_package_adds_the_commit_to_the_version_line_and_one_notice_line_after_it(self):
        _frame, plain = self.card_labels(PLAIN)
        _frame, package = self.card_labels(PACKAGE)
        self.assertEqual(package[:2], ["버전", f"v0.1.0-preview.1 · 커밋 {COMMIT[:7]}"])
        self.assertEqual(package[2], "개인 PC 제한 시험용, 미서명 Package")
        self.assertEqual(package[3:], plain[2:])                                       # 나머지 글(진단 정보·안내)은 그대로
        self.assertEqual(len(package), len(plain) + 1)

    def test_the_notice_line_wraps_and_is_a_caption_so_it_never_widens_the_card(self):
        frame, _labels = self.card_labels(PACKAGE)
        notice = [label for label in frame.findChildren(UI.Label) if label.plain_text() == app_version.PACKAGE_NOTICE]
        self.assertEqual(len(notice), 1)
        self.assertTrue(notice[0].wordWrap())
        frame.resize(200, 300)
        frame.show()
        self.app.processEvents()
        self.assertLessEqual(frame.sizeHint().width(), 520)
        frame.close()

    def test_a_trial_build_shows_the_trial_sentence_in_the_same_wrapped_notice_line(self):
        frame, labels = self.card_labels(TRIAL)
        self.assertEqual(labels[2], f"{app_version.PACKAGE_NOTICE} · {app_version.PACKAGE_TRIAL_NOTICE}")
        self.assertEqual(len(labels), len(self.card_labels(PACKAGE)[1]))                      # 줄이 하나 더 생기지 않는다 — 같은 안내 줄이 길어질 뿐
        notice = [label for label in frame.findChildren(UI.Label) if label.plain_text() == labels[2]]
        self.assertEqual(len(notice), 1)
        self.assertTrue(notice[0].wordWrap())
        frame.resize(200, 300)
        frame.show()
        self.app.processEvents()
        self.assertLessEqual(frame.sizeHint().width(), 520)
        frame.close()

    def test_no_card_text_or_accessible_name_holds_more_than_the_seven_commit_characters(self):
        frame, _labels = self.card_labels(PACKAGE)
        parts = [label.plain_text() for label in frame.findChildren(UI.Label)] + [w.accessibleName() + w.toolTip() for w in frame.findChildren(QWidget)]
        joined = " ".join(parts)
        self.assertIn(COMMIT[:7], joined)
        self.assertNotIn(COMMIT[:8], joined)


@unittest.skipUnless(HAVE, "PySide6 가 있어야 한다")
class InsideTheRealShellTest(unittest.TestCase):
    """실제 앱 틀(가짜 공급자)에서 설정 → 정보를 폈을 때 같은 글이 보인다."""

    @classmethod
    def setUpClass(cls):
        cls.app = qapp.make_app([])

    def open_info(self, version):
        window = shell_module.AppShell(services.FakeHomeProvider(delay=0.0), connections=services.FakeConnectionsProvider(), autoload=False, version_info=version)
        self.addCleanup(window.close)
        window.resize(1440, 900)
        window.show()
        ui_offscreen.settle(self.app, 4)
        window.go("settings")
        ui_offscreen.wait_until(self.app, lambda: window.state.conn_state != "loading", 10)
        ui_offscreen.settle(self.app, 4)
        accordions = {item.key: item for item in window.screen_widget.findChildren(UI.Accordion)}
        accordions["info"].flip()
        ui_offscreen.settle(self.app, 4)
        return window, [label.plain_text() for label in accordions["info"].body.findChildren(UI.Label)]

    def test_the_folded_info_group_shows_the_version_commit_and_notice_when_opened(self):
        window, labels = self.open_info(PACKAGE)
        self.assertEqual(labels[:3], ["버전", f"v0.1.0-preview.1 · 커밋 {COMMIT[:7]}", app_version.PACKAGE_NOTICE])
        sidebar_text = " ".join(label.text() for label in window.findChildren(QLabel))
        self.assertIn("v0.1.0-preview.1", sidebar_text)                                 # 사이드바 아래 버전 글은 짧은 그대로

    def test_without_package_information_the_group_is_what_it_was(self):
        _window, labels = self.open_info(PLAIN)
        self.assertEqual(labels[:2], ["버전", "v0.1.0-preview.1"])
        self.assertNotIn(app_version.PACKAGE_NOTICE, labels)


if __name__ == "__main__":
    unittest.main()
