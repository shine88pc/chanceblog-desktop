"""화면 글 부품이 외부 글을 **서식 글(HTML)로 읽지 않는다** — PySide6 시험(창을 화면에 띄우지 않고 offscreen). **PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 소스 모양은 `test_source_rules_ui_text` 가 PySide6 없이 지킨다).
독립 감사 AS-S1 필수-1·필수-2·권고-4·권고-5·참고-12(결정 D-595): 키워드 칩(`CardChip`)·한 줄 줄임표 글(`ElidedLabel`)·토스트(`Toast`)·의미 배지(`SemanticBadge`)는 Qt 기본 글 형식(AutoText)이라 `<img src=경로>` 가 든 글을 서식 글로 읽어
그림을 불러왔다(마우스를 올리기만 해도 — 윈도에서 네트워크 공유 경로면 접속 시도). 서식 모양 글(`<b>`·`<table>`·`<a>`)로 칩 모양을 속일 수도 있었다. 이 시험은 공격 모양 글을 이 부품에 주고 아래를 못박는다.
모든 그림 글은 **이 시험이 임시 폴더에 만든 작은 PNG 의 로컬 경로**뿐이다 — 네트워크 경로(SMB)는 한 번도 부르지 않는다.

지키는 것(부품마다):
  1) 글 형식이 `Qt.PlainText` 이고 받은 글이 쓴 그대로 보인다(`text()`).
  2) 그리거나(`grab`)·크기를 재거나(기본 `sizeHint`·`heightForWidth`)·마우스를 올려도(MouseMove) 서식 글 문서(`QTextDocument`)가 생기지 않는다 — 그림을 읽는 길이 없다. 글 부품의 기본 크기는 글자 폭 그대로다(그림 크기가 아니다).
  3) 옛 안전한 길(`Label` 일반·줄바꿈 글, `Badge`)은 그대로 쓴 그대로 보인다(그림 조각이 문서에 없다).
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QImage, QMouseEvent, QTextDocument
    from PySide6.QtWidgets import QApplication, QLabel, QWidget
    from chanceblog_desktop.ui.core import part_rules
    from chanceblog_desktop.ui.core import tokens as K
    from chanceblog_desktop.ui.core.text import display_text
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import candidate_parts, components as UI


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class PlainTextBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        image = QImage(41, 29, QImage.Format_RGB32)
        image.fill(Qt.red)
        cls.png = Path(cls.folder.name, "cover.png")
        assert image.save(str(cls.png))
        cls.attacks = {                                                        # 공격 모양 글 — 그림은 모두 이 시험의 로컬 PNG(경로 꼴 둘)
            "bold": "<b>x</b>",
            "image": f'<img src="{cls.png.as_posix()}">',
            "image-url": f'<img src="{cls.png.as_uri()}">',
            "link": '<a href="' + "https" + "://example.invalid/x" + '">link</a>',            # 웹 주소 모양이 소스에 그대로 없게 조립한다(가짜 호스트 — 접속 코드는 없다)
            "table": "<table><tr><td>t</td></tr></table>",
        }

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    # ---- 도구 ----
    @staticmethod
    def documents(widget):
        return widget.findChildren(QTextDocument)

    def poke(self, widget):
        """서식 글이었다면 그림을 읽었을 모든 길을 한 번씩 지난다 — 그리기·기본 크기·줄바꿈 높이·마우스 올림."""
        widget.resize(260, 40)
        widget.ensurePolished()
        QLabel.sizeHint(widget)
        QLabel.minimumSizeHint(widget)
        QLabel.heightForWidth(widget, 120)
        widget.grab()
        move = QMouseEvent(QEvent.MouseMove, QPointF(3, 3), QPointF(3, 3), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(widget, move)                                   # 보내는 일은 그 자리에서 끝난다 — 이벤트 큐를 돌리지 않는다(옛 서식 글 라벨이 남은 채 큐를 돌리면 이 PC 의 Qt 가 접근 위반으로 죽어 시험이 깨끗이 빨개지지 않는다)

    def assert_plain(self, widget, shown, name, text_width=True):
        """글 형식이 일반 글이고 서식 글 문서가 없으며 글이 쓴 그대로이다. `text_width` 면 기본 크기가 글자 폭 이상이다(그림·꾸민 글이면 훨씬 작다). 어긴 것을 모아 한 번에 알린다."""
        found = []
        if widget.textFormat() != Qt.PlainText:
            found.append(f"{name}: 글 형식이 {widget.textFormat().name} 이다(Qt.PlainText 여야 한다)")
        if widget.text() != shown:
            found.append(f"{name}: 보이는 글이 받은 글과 다르다 {widget.text()!r} != {shown!r}")
        self.poke(widget)
        if self.documents(widget):
            found.append(f"{name}: 서식 글 문서(QTextDocument)가 생겼다 — 그림을 읽는 길")
        if widget.textFormat() != Qt.PlainText:
            found.append(f"{name}: 그리고 난 뒤 글 형식이 {widget.textFormat().name} 이다")
        if text_width:
            hint = QLabel.sizeHint(widget)
            if hint.width() + 2 < widget.fontMetrics().horizontalAdvance(shown):
                found.append(f"{name}: 기본 크기 {hint.width()}x{hint.height()} 가 글자 폭보다 좁다(서식 글로 읽혔다)")
        if found:
            self.fail(" / ".join(found))


class AttackTextTest(PlainTextBase):
    def test_a_keyword_chip_shows_attack_text_as_typed_and_never_builds_a_rich_text_document(self):
        for name, text in self.attacks.items():
            with self.subTest(attack=name):
                chip = candidate_parts.CardChip(text)
                self.assert_plain(chip, text, f"CardChip/{name}")
                self.assertEqual(chip.accessibleName(), text, "접근 이름은 받은 글 그대로")
                self.assertEqual(chip.property("kw"), True)

    def test_a_keyword_chip_with_its_own_accessible_name_keeps_it(self):
        chip = candidate_parts.CardChip(self.attacks["bold"], accessible="키워드 x")
        self.assert_plain(chip, self.attacks["bold"], "CardChip/accessible")
        self.assertEqual(chip.accessibleName(), "키워드 x")

    def test_an_elided_label_shows_attack_text_as_typed_and_a_mouse_over_builds_no_rich_text_document(self):
        for name, text in self.attacks.items():
            with self.subTest(attack=name):
                label = UI.ElidedLabel(text, "small")
                self.assert_plain(label, text, f"ElidedLabel/{name}")
                self.assertEqual(label._full, text, "그리는 글은 받은 글 그대로")
                self.assertEqual(label.property("role"), "small")
                self.assertEqual(UI.ElidedLabel(text).sizeHint().width(), 0, "한 줄 줄임표 글의 덮어쓴 크기 힌트는 그대로(폭 0, 칸이 정한다)")

    def test_an_elided_label_set_to_new_text_later_stays_plain(self):
        label = UI.ElidedLabel("처음 글", "small")
        label.setText(self.attacks["image"])
        self.assert_plain(label, self.attacks["image"], "ElidedLabel/setText")

    def test_a_toast_shows_attack_text_as_typed_and_never_builds_a_rich_text_document(self):
        for name, text in self.attacks.items():
            with self.subTest(attack=name):
                parent = QWidget()
                parent.resize(500, 300)
                self.addCleanup(parent.close)
                toast = UI.Toast(parent)
                self.assertEqual(toast.textFormat(), Qt.PlainText, f"Toast/{name}: 글을 주기 전부터 일반 글")
                toast.show_message(text, "error")
                shown = display_text(text, 120)
                self.assertEqual(toast.text(), shown, f"Toast/{name}")
                self.assertEqual(toast.accessibleName(), shown)
                self.assert_plain(toast, shown, f"Toast/{name}", text_width=False)

    def test_a_semantic_badge_shows_attack_text_as_typed_and_never_builds_a_rich_text_document(self):
        for name, text in self.attacks.items():
            with self.subTest(attack=name):
                badge = UI.SemanticBadge(K.BADGE_KINDS[0], text)
                shown = part_rules.clip_text(" ".join(text.split()), part_rules.BADGE_MAX_CHARS)
                self.assert_plain(badge, shown, f"SemanticBadge/{name}")
                self.assertEqual(badge.full_text, " ".join(text.split()))
                self.assertEqual(badge.property("semantic"), K.BADGE_KINDS[0])

    def test_a_semantic_badge_with_the_default_name_is_plain_too(self):
        badge = UI.SemanticBadge(K.BADGE_KINDS[0])
        self.assert_plain(badge, K.badge_label(K.BADGE_KINDS[0]), "SemanticBadge/기본 이름")

    def test_a_clamped_card_text_never_puts_its_text_in_the_label_and_is_plain_text_anyway(self):
        for name, text in self.attacks.items():
            with self.subTest(attack=name):
                clamped = candidate_parts.ClampedLabel(text, "small", 2)
                self.assertEqual(clamped.textFormat(), Qt.PlainText, f"ClampedLabel/{name}")
                self.assertEqual((clamped.text(), clamped.plain_text()), ("", text), "글은 QLabel 안이 아니라 직접 그린다")
                self.poke(clamped)
                self.assertEqual(self.documents(clamped), [], name)


class SafePathTest(PlainTextBase):
    """이미 안전하던 길은 그대로다 — 일반 글은 형식이 PlainText, 줄바꿈 글은 이스케이프한 서식 글이라 그림 조각이 문서에 없고 보이는 글이 쓴 그대로."""

    def test_a_plain_label_and_a_badge_show_attack_text_as_typed(self):
        for name, text in self.attacks.items():
            with self.subTest(attack=name):
                label = UI.Label(text)
                self.assert_plain(label, text, f"Label/{name}")
                self.assertEqual(label.plain_text(), text)
                badge = UI.Badge("info", text)
                self.assert_plain(badge, text, f"Badge/{name}")
                self.assertEqual(badge.accessibleName(), text)

    def test_a_wrapping_label_is_escaped_rich_text_so_the_document_holds_the_typed_text_and_no_image(self):
        for name, text in self.attacks.items():
            with self.subTest(attack=name):
                label = UI.Label(text, wrap=True)
                self.poke(label)
                documents = self.documents(label)
                self.assertEqual(len(documents), 1, name)
                document = documents[0]
                self.assertEqual(document.toPlainText().strip(), text, f"Label(wrap)/{name}: 보이는 글이 쓴 그대로")
                formats = document.allFormats()
                self.assertFalse(any(item.isImageFormat() for item in formats), f"Label(wrap)/{name}: 문서에 그림 조각이 없다")
                self.assertFalse(any(item.isTableFormat() or item.isTableCellFormat() for item in formats), f"Label(wrap)/{name}: 문서에 표가 없다")
                self.assertFalse(any(item.isCharFormat() and item.toCharFormat().isAnchor() for item in formats), f"Label(wrap)/{name}: 문서에 링크가 없다")
                self.assertEqual(document.rootFrame().childFrames(), [], f"Label(wrap)/{name}: 문서에 틀(표)이 없다")
                self.assertEqual(label.plain_text(), text)


if __name__ == "__main__":
    unittest.main()
