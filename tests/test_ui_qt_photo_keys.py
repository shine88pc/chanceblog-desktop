"""사진 정리 창의 칩 묶음 키보드(검증 Q N-6)와 Qt 시험의 틈 여섯(검증 Q N-7 — NQ40·NQ41·NQ42·NQ02·NQ25·NQ29)을 못박는 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 진짜 키 이벤트로 눌러 본다.
**PySide6 가 없으면 통째로 건너뛴다**(저장소 CI 에는 PySide6 가 없다). 시험 도구(`PhotoBase`·가짜 선택기·가짜 미리보기 만들기)는 `test_ui_qt_photo` 것을 이어 쓰고 그 모듈의 시험은 가져오지 않는다.

지키는 것:
  1) 칩 묶음(종류·장소 분위기·들어갈 곳·자리)마다 Tab 정거장은 하나(고른 칩, 고른 것이 없으면 첫 칩) — 한 줄이 23정거장이던 것이 9정거장으로. ←↑→↓ 는 묶음 안에서 칩 사이로 포커스를 옮기고(끝에서는 반대쪽 끝으로 돈다)
     Home·End 는 처음·마지막 칩으로 가며 방향키는 고르지 않고(Space·Enter 가 고른다) 묶음 밖으로 나가지 않는다. 다시 들어올 때는 고른 칩에 선다. 칩마다 'n개 중 m번째' 접근 설명이 있다.
  2) 시험 틈 여섯 — 되돌린 뒤 파일 상태 다시 읽기(NQ40)·같은 위치로 다시 찾기(NQ41)·설명 글만 있어도 자리 정하기가 열림(NQ42)·치는 중인 칸은 다시 그릴 때 덮어쓰지 않음(NQ02)·미리보기의 가로세로 비율(NQ25)·몸이 창 높이를 씀(NQ29).
"""
import ast
import string
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import test_ui_qt_photo as tq  # noqa: E402     (시험 도구만 이어 쓴다 — 이 모듈은 그 모듈의 시험 클래스를 가져오지 않는다)

HAVE = tq.HAVE
if HAVE:
    import ui_offscreen
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget
    from chanceblog_desktop.ui.qt import photo_screen
    from chanceblog_desktop.ui.qt.photo_parts import ChipGroupKeys

T = tq.T
fake_path = tq.fake_path
FILE_MARK = tq.FILE_MARK


class ChipSourceTest(unittest.TestCase):
    """소스 글로 못박는 칩 키보드 규칙 — PySide6 가 없는 CI 에서도 돈다(위의 동작 시험은 PySide6 가 있어야 돈다)."""

    def parts(self):
        source = (tq.QT_DIR / "photo_parts.py").read_text(encoding="utf-8")
        return source, ast.parse(source)

    def test_the_chip_keyboard_lives_in_one_place_of_the_parts_file_and_is_marked_for_the_later_merge(self):
        source, _tree = self.parts()
        self.assertEqual(source.count("class ChipGroupKeys"), 1)
        self.assertEqual(source.count("installEventFilter"), 1)
        self.assertIn("BLOGSEL-2 의 칩 묶음 키 처리와 같은 규칙", source)
        screen = (tq.QT_DIR / "photo_screen.py").read_text(encoding="utf-8")
        self.assertNotIn("installEventFilter", screen)
        self.assertNotIn("Key_Left", screen)

    def test_the_two_key_tables_and_the_focus_rules_are_the_ones_the_design_says(self):
        source, tree = self.parts()
        tables = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("CHIP_MOVE_KEYS", "CHIP_EDGE_KEYS"):
                tables[node.targets[0].id] = {ast.unparse(key): ast.literal_eval(value) for key, value in zip(node.value.keys, node.value.values)}
        self.assertEqual(tables["CHIP_MOVE_KEYS"], {"Qt.Key_Left": -1, "Qt.Key_Up": -1, "Qt.Key_Right": 1, "Qt.Key_Down": 1}, "←↑ 는 앞으로, →↓ 는 뒤로")
        self.assertEqual(tables["CHIP_EDGE_KEYS"], {"Qt.Key_Home": 0, "Qt.Key_End": -1}, "Home 은 처음, End 는 마지막 칩")
        group = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "ChipGroupKeys")
        methods = {node.name: node for node in group.body if isinstance(node, ast.FunctionDef)}
        sync = {node.attr for node in ast.walk(methods["sync"]) if isinstance(node, ast.Attribute)}
        self.assertTrue({"StrongFocus", "ClickFocus"} <= sync and "NoFocus" not in sync, "정거장만 Tab, 나머지는 클릭으로만 — NoFocus 로 만들지 않는다(접근성 규칙)")
        keyed = {node.attr for node in ast.walk(methods["eventFilter"]) if isinstance(node, ast.Attribute)}
        self.assertTrue({"ShiftModifier", "ControlModifier", "AltModifier", "MetaModifier"} <= keyed, "조합 키는 건드리지 않는다")
        self.assertIn("_reveal", {node.attr for node in ast.walk(methods["eventFilter"]) if isinstance(node, ast.Attribute)}, "옮겨 간 칩을 보이는 곳으로 가져온다")
        self.assertEqual(sorted(methods), ["__init__", "_reveal", "eventFilter", "stop", "sync"])
        for name, method in methods.items():
            if name != "sync":
                self.assertNotIn("setFocusPolicy", {part.attr for part in ast.walk(method) if isinstance(part, ast.Attribute)}, f"칩의 포커스 정책은 sync 한 곳에서만 정한다 — {name}")
        self.assertEqual(sorted(field for _text, field, _spec, _conversion in string.Formatter().parse(T["pho_chip_hint"]) if field), ["m", "n"])


class KeysBase(tq.PhotoBase):
    """줄·칩을 다루는 도구."""

    def group(self, card, kind):
        return list(getattr(card, f"_chips_{kind}").values())

    def tab_stops(self, form, card):
        """줄에서 Tab 이 실제로 서는 곳(보이고 켜져 있고 Tab 포커스가 있는 것) — 줄 부품이 알려 주는 화면 순서대로."""
        return [widget for widget in card.stops() if widget.isVisibleTo(form) and widget.isEnabled() and bool(widget.focusPolicy() & Qt.TabFocus)]

    def the_stop(self, chips):
        stops = [chip for chip in chips if bool(chip.focusPolicy() & Qt.TabFocus)]
        self.assertEqual(len(stops), 1, [(chip.text(), int(chip.focusPolicy().value)) for chip in chips])
        return stops[0]

    def key(self, key, modifier=None):
        widget = QApplication.focusWidget()
        if modifier is None:
            QTest.keyClick(widget, key)
        else:
            QTest.keyClick(widget, key, modifier)
        self.settle(1)
        return QApplication.focusWidget()

    def walk(self, key, steps, start):
        start.setFocus(Qt.TabFocusReason)
        self.settle(1)
        seen = [QApplication.focusWidget()]
        for _ in range(steps):
            seen.append(self.key(key))
        return seen

    def make_image(self, name, fmt, width, height):
        path = self.tmp / name
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor("#aa5533"))
        self.assertTrue(image.save(str(path), fmt))
        return str(path)


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class ChipKeysTest(KeysBase):
    def test_each_chip_group_is_a_single_tab_stop_so_a_photo_row_has_about_nine_stops(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3))
        card = form.rows["p002"]
        stops = self.tab_stops(form, card)
        self.assertEqual(len(stops), 9, [widget.accessibleName() for widget in stops])
        self.assertLess(len(stops), 12, "한 줄이 23정거장이던 것이 줄었다")
        for kind in ("type", "setting"):
            group = self.group(card, kind)
            self.assertGreaterEqual(len(group), 7)
            self.assertEqual([chip for chip in group if chip in stops], [self.the_stop(group)], kind)
        card.place_toggle.click()
        self.settle(3)
        for kind in ("section", "kind"):
            self.assertEqual([chip for chip in self.group(card, kind) if chip in self.tab_stops(form, card)], [self.the_stop(self.group(card, kind))], kind)
        self.assertLessEqual(len(self.tab_stops(form, card)), 14, "자리 정하기를 펼쳐도 한 줄이 34정거장이던 것이 줄었다")

    def test_the_one_stop_is_the_chosen_chip_and_the_first_chip_when_nothing_is_chosen(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        types, settings = self.group(card, "type"), self.group(card, "setting")
        self.assertEqual([chip.text() for chip in types if chip.isChecked()], ["기타"])
        self.assertIs(self.the_stop(types), self.chip(form, "type", "p001", "기타"), "고른 칩이 정거장이다")
        self.assertIs(self.the_stop(settings), settings[0], "정하지 않음(첫 칩)이 고른 상태다")
        self.chip(form, "type", "p001", "음식").click()
        self.chip(form, "setting", "p001", "테라스").click()
        self.settle(4)
        self.assertEqual((board.photo("p001").photo_type, board.photo("p001").setting), ("음식", "테라스"))
        self.assertIs(self.the_stop(self.group(card, "type")), self.chip(form, "type", "p001", "음식"), "고르면 정거장이 따라온다")
        self.assertIs(self.the_stop(self.group(card, "setting")), self.chip(form, "setting", "p001", "테라스"))
        chips = [QPushButton("가"), QPushButton("나"), QPushButton("다")]                       # 고른 것이 하나도 없는 묶음 — 첫 칩이 정거장
        for chip in chips:
            chip.setCheckable(True)
        host = QWidget()
        keys = ChipGroupKeys(host, chips)
        self.assertEqual([bool(chip.focusPolicy() & Qt.TabFocus) for chip in chips], [True, False, False])
        chips[2].setChecked(True)
        keys.sync()
        self.assertEqual([bool(chip.focusPolicy() & Qt.TabFocus) for chip in chips], [False, False, True])
        self.assertTrue(all(chip.focusPolicy() != Qt.NoFocus for chip in chips), "정거장이 아닌 칩도 클릭으로 포커스를 받는다")
        self.assertEqual(ChipGroupKeys(QWidget(), []).stop(), None)

    def test_arrow_keys_home_and_end_move_inside_the_group_wrap_around_and_never_choose(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        types = self.group(card, "type")
        self.assertEqual([chip.text() for chip in types][0::8], ["간판", "기타"])
        self.the_stop(types).setFocus(Qt.TabFocusReason)                                   # 기타(마지막 칩)
        self.settle(1)
        moves = [(Qt.Key_Right, "간판"), (Qt.Key_Right, "건물 외관"), (Qt.Key_Down, "메뉴판"), (Qt.Key_Left, "건물 외관"), (Qt.Key_Up, "간판"), (Qt.Key_Left, "기타"), (Qt.Key_Up, "지도 캡처"),
                 (Qt.Key_Home, "간판"), (Qt.Key_End, "기타"), (Qt.Key_Down, "간판")]
        for key, expected in moves:
            focused = self.key(key)
            self.assertIn(focused, types, "포커스가 묶음 밖으로 나갔다")
            self.assertEqual(focused.text(), expected, key)
        self.assertEqual(board.photo("p001").photo_type, "기타", "방향키는 포커스만 옮기고 고르지 않는다")
        self.assertEqual([chip.text() for chip in types if chip.isChecked()], ["기타"])
        settings = self.group(card, "setting")
        settings[0].setFocus(Qt.TabFocusReason)
        self.settle(1)
        self.assertEqual(self.key(Qt.Key_Left).text(), "야경", "다른 묶음도 같다 — 처음에서 왼쪽은 마지막 칩")
        self.assertEqual(self.key(Qt.Key_Home).text(), "정하지 않음")

    def test_space_and_enter_choose_the_chip_that_has_the_focus_and_the_stop_follows(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        types = self.group(card, "type")
        self.chip(form, "type", "p001", "음식").setFocus(Qt.TabFocusReason)
        self.settle(1)
        self.key(Qt.Key_Space)
        self.assertEqual(board.photo("p001").photo_type, "음식")
        self.assertIs(self.the_stop(self.group(card, "type")), self.chip(form, "type", "p001", "음식"))
        self.assertEqual(self.key(Qt.Key_Left).text(), "반찬")
        self.key(Qt.Key_Return)
        self.assertEqual(board.photo("p001").photo_type, "반찬", "엔터도 고른다")
        self.assertIs(self.the_stop(self.group(card, "type")), self.chip(form, "type", "p001", "반찬"))
        self.assertIn(QApplication.focusWidget(), self.group(card, "type"), "고른 뒤에도 포커스는 그 칩에 있다")
        self.assertEqual(len(types), len(self.group(card, "type")), "칩이 다시 만들어지지 않았다")

    def test_tab_and_shift_tab_walk_a_row_through_nine_stops_and_a_mouse_click_still_chooses_any_chip(self):
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3))
        card = form.rows["p002"]
        stops = self.tab_stops(form, card)
        before = self.tab_stops(form, form.rows["p001"])[-1]
        after = self.tab_stops(form, form.rows["p003"])[0]
        forward = self.walk(Qt.Key_Tab, len(stops) + 1, before)
        self.assertEqual(forward[1:], stops + [after], [getattr(widget, "accessibleName", lambda: "?")() for widget in forward])
        backward = self.walk(Qt.Key_Backtab, len(stops) + 1, after)
        self.assertEqual(backward[1:], stops[::-1] + [before])
        for widget in forward + backward:
            self.assertTrue(form.isAncestorOf(widget) or widget is form, "포커스가 대화상자 밖으로 나갔다")
        chip = self.chip(form, "type", "p002", "반찬")                                     # 정거장이 아닌 칩
        self.assertFalse(bool(chip.focusPolicy() & Qt.TabFocus))
        QTest.mouseClick(chip, Qt.LeftButton)
        self.settle(3)
        self.assertEqual(board.photo("p002").photo_type, "반찬", "마우스는 정거장이 아닌 칩도 고른다")
        self.assertIs(self.the_stop(self.group(card, "type")), chip)

    def test_tab_comes_back_to_the_chosen_chip_not_to_the_chip_the_arrows_stopped_on(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        types = self.group(card, "type")
        chosen = self.chip(form, "type", "p001", "음식")
        chosen.click()
        self.settle(3)
        chosen.setFocus(Qt.TabFocusReason)
        self.settle(1)
        self.assertEqual(self.key(Qt.Key_Right).text(), "지도 캡처")                         # 포커스만 옮겼다(고르지 않았다)
        self.assertEqual([chip.text() for chip in types if chip.isChecked()], ["음식"])
        out = self.key(Qt.Key_Tab)
        self.assertNotIn(out, types, "Tab 은 묶음 밖으로 나간다")
        back = self.key(Qt.Key_Backtab)
        self.assertIs(back, chosen, "다시 들어올 때는 고른 칩에 선다")
        self.assertEqual(self.key(Qt.Key_Backtab) in types, False, "한 번 더 누르면 묶음 앞의 부품으로 간다 — 다른 칩들은 건너뛴다")

    def test_a_key_with_shift_control_or_alt_is_left_alone_so_it_never_moves_between_chips(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        types = self.group(card, "type")
        stop = self.the_stop(types)                                                          # 기타 — 마지막 칩
        for modifier in (Qt.ShiftModifier, Qt.ControlModifier, Qt.AltModifier):
            stop.setFocus(Qt.TabFocusReason)
            self.settle(1)
            focused = self.key(Qt.Key_Right, modifier)
            self.assertNotEqual(focused.text() if focused in types else None, "간판", f"조합 키({modifier})가 묶음 안에서 돌았다")

    def test_the_chips_say_which_one_of_how_many_and_the_group_has_a_name(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        for kind in ("type", "setting"):
            group = self.group(card, kind)
            for number, chip in enumerate(group, 1):
                self.assertEqual(chip.accessibleDescription(), T["pho_chip_hint"].format(n=len(group), m=number), (kind, number))
                self.assertTrue(chip.accessibleName().startswith(card.vm[kind]["a11y"]), "칩의 접근 이름은 그대로(묶음 이름 + 칩 이름)다")
            self.assertEqual(group[0].parentWidget().accessibleName(), card.vm[kind]["a11y"], "묶음에 이름이 있다")
        self.assertEqual(self.group(card, "type")[0].accessibleDescription(), "9개 중 1번째예요. 방향키로 옮기고 스페이스나 엔터로 골라요.")

    def test_chips_that_are_made_again_when_the_list_of_kinds_grows_keep_the_same_keyboard_rule(self):
        window, form = self.sheet()
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        self.assertEqual(form.act("add_type", "새 종류"), "ok")
        self.settle(4)
        types = self.group(card, "type")
        self.assertEqual((len(types), types[-1].text()), (10, "새 종류"))
        self.assertIs(self.the_stop(types), self.chip(form, "type", "p001", "기타"))
        self.chip(form, "type", "p001", "간판").setFocus(Qt.TabFocusReason)
        self.settle(1)
        self.assertEqual(self.key(Qt.Key_End).text(), "새 종류", "새로 만든 칩도 방향키와 End 가 된다")
        self.assertEqual(self.key(Qt.Key_Right).text(), "간판")
        self.assertEqual(len(card._chip_groups), 4, "묶음마다 키보드 규칙이 하나씩 있다")

    def test_an_arrow_key_brings_a_chip_that_is_off_screen_into_view(self):
        window, form = self.sheet(size=(900, 560))
        self.add_photos(form, *[fake_path(number) for number in range(1, 5)])
        viewport, bar = form.scroll.viewport(), form.scroll.verticalScrollBar()
        bar.setValue(0)
        self.settle(2)
        card = form.rows["p003"]
        stop = self.the_stop(self.group(card, "type"))
        stop.setFocus(Qt.TabFocusReason)                                                     # 프로그램으로 옮긴 포커스는 스크롤이 따라가지 않는다
        self.settle(2)
        self.assertEqual(bar.value(), 0)
        target = self.key(Qt.Key_Left)
        top = target.mapTo(viewport, target.rect().topLeft()).y()
        bottom = target.mapTo(viewport, target.rect().bottomLeft()).y()
        self.assertTrue(0 <= top and bottom <= viewport.height(), (top, bottom, viewport.height()))
        self.assertGreater(bar.value(), 0, "몸이 스크롤됐다")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class GapTest(KeysBase):
    """검증 Q N-7 — 문서가 말하는 동작인데 시험이 지키지 않던 곳 여섯(Q 의 변이 NQ40·41·42·02·25·29 가 살아남았다)."""

    def test_undoing_a_removal_reads_the_files_again_and_the_returned_row_shows_a_file_that_went_missing(self):                # NQ40
        provider = tq.pv.FakePhotoProvider()
        window = self.drafted(photos=provider)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3))
        form.rows["p002"].remove.click()
        self.settle(4)
        self.assertNotIn("p002", form.rows)
        provider.states[fake_path(2)] = "missing"                                            # 지운 사이에 파일이 없어졌다
        provider.calls.clear()
        form.undo_button.click()
        self.settle(6)
        self.assertIn("check", provider.calls, "되돌린 뒤 파일 상태를 다시 읽는다")
        card = form.rows["p002"]
        self.assertEqual(self.lt(card.badge), "파일 없음")
        self.assertTrue(card.relink.isVisibleTo(form))
        self.assertEqual(self.lt(form.rows["p001"].badge), "파일 있음 · 640×480")

    def test_relinking_a_photo_to_the_place_it_already_has_works_once_the_file_is_back(self):                                  # NQ41
        provider = tq.pv.FakePhotoProvider()
        window = self.drafted(photos=provider)
        window, form = self.sheet(window)
        self.add_photos(form, fake_path(1), fake_path(2))
        self.assertEqual(window.photos_close(), "closed")
        provider.states[fake_path(1)] = "missing"
        window, form = self.sheet(window)
        card = form.rows["p001"]
        self.assertEqual(self.lt(card.badge), "파일 없음")
        provider.states.pop(fake_path(1))                                                    # 파일이 돌아왔다
        self.relinks.append(fake_path(1))                                                    # 파일 선택 창에서 같은 위치를 다시 고른다
        card.relink.click()
        self.settle(6)
        board = window.state.drafts.photos
        self.assertEqual(board.photo("p001").local_path, fake_path(1))
        self.assertEqual(self.lt(form.notice), T["pho_relinked"], "'이미 넣은 사진이에요' 로 거절되지 않는다")
        self.assertEqual(self.lt(card.badge), "파일 있음 · 640×480")
        self.assertFalse(card.relink.isVisibleTo(form))
        self.relinks.append(fake_path(2))                                                    # 다른 사진이 쓰는 위치는 여전히 중복이다
        window.photos_relink("p001")
        self.settle(4)
        self.assertEqual(board.photo("p001").local_path, fake_path(1))
        self.assertEqual(self.lt(form.notice), T["pho_rejected_dup"])

    def test_a_photo_that_has_only_a_caption_a_chosen_section_or_a_chosen_kind_opens_the_place_part_when_the_sheet_is_opened_again(self):   # NQ42
        window, form = self.sheet()
        board = window.state.drafts.photos
        self.add_photos(form, fake_path(1), fake_path(2), fake_path(3), fake_path(4))
        for card in form.rows.values():
            self.assertFalse(card.place_body.isVisibleTo(form))
        self.assertEqual(board.set_text("p001", "caption", "메뉴판 오른쪽 아래"), "ok")
        self.assertEqual(board.set_section("p002", "도입"), "ok")
        self.assertEqual(board.set_placement("p003", "top"), "ok")
        self.assertEqual(window.photos_close(), "closed")
        window, form = self.sheet(window)
        opened = {photo_id: card.place_body.isVisibleTo(form) for photo_id, card in form.rows.items()}
        self.assertEqual(opened, {"p001": True, "p002": True, "p003": True, "p004": False}, "값이 있는 줄만 펼쳐져 있다 — 쳐 둔 설명 글이 접힌 곳에 숨지 않는다")
        self.assertEqual(form.rows["p001"].caption.edit.text(), "메뉴판 오른쪽 아래")

    def test_text_typed_in_a_field_is_not_overwritten_when_the_sheet_is_drawn_again_before_it_was_committed(self):              # NQ02
        window, form = self.sheet()
        self.add_photos(form, fake_path(1))
        card = form.rows["p001"]
        self.activate(window)
        card.subject.edit.setFocus(Qt.TabFocusReason)
        self.settle(2)
        self.assertTrue(card.subject.edit.hasFocus(), "시험의 전제: 칸에 포커스가 있다")
        QTest.keyClicks(card.subject.edit, "typing now")
        form.refresh()
        self.settle(2)
        self.assertEqual(card.subject.edit.text(), "typing now", "치는 중인 글은 다시 그릴 때 덮어쓰지 않는다")
        self.assertEqual(window.state.drafts.photos.photo("p001").user_subject, "", "아직 규칙에 넘기지 않았다")
        QTest.keyClick(card.subject.edit, Qt.Key_Return)
        self.settle(3)
        self.assertEqual(window.state.drafts.photos.photo("p001").user_subject, "typing now")
        card.note.edit.setFocus(Qt.TabFocusReason)                                           # 한도를 넘어 거절된 글은 포커스가 없어도 칸에 남는다
        self.settle(1)
        QTest.keyClicks(card.note.edit, "x" * 301)
        card.subject.edit.setFocus(Qt.TabFocusReason)
        self.settle(3)
        form.refresh()
        self.settle(2)
        self.assertEqual(len(card.note.edit.text()), 301, "거절된 글은 사라지지 않는다")

    def test_the_preview_keeps_the_picture_shape_of_the_original(self):                                                     # NQ25
        for width, height, expected in ((800, 600, (96, 72)), (600, 800, (72, 96)), (1600, 400, (96, 24)), (300, 300, (96, 96))):
            with self.subTest(size=(width, height)):
                pixmap = photo_screen.make_preview(self.make_image(f"p{width}x{height}.jpg", "JPG", width, height))
                self.assertFalse(pixmap.isNull())
                self.assertLessEqual(abs(pixmap.width() - expected[0]), 1)
                self.assertLessEqual(abs(pixmap.height() - expected[1]), 1)
                self.assertLessEqual(max(pixmap.width(), pixmap.height()), tq.rules.THUMB_SIDE)
        window = self.drafted(real_files=True)
        window, form = self.sheet(window)
        self.add_photos(form, self.make_image("a43.jpg", "JPG", 400, 300))
        ui_offscreen.wait_until(self.app, lambda: not form.rows["p001"].preview.pixmap().isNull(), 8)
        shown = form.rows["p001"].preview.pixmap()
        self.assertLessEqual(abs(shown.width() * 3 - shown.height() * 4), 4, (shown.width(), shown.height()))

    def test_the_body_of_the_sheet_uses_the_height_the_window_gives_it(self):                                              # NQ29
        for size in ((1366, 768), (900, 560)):
            with self.subTest(size=size):
                window, form = self.sheet(size=size)
                self.add_photos(form, *[fake_path(number) for number in range(1, 5)])
                self.assertGreater(form.scroll.verticalScrollBar().maximum(), 0, "줄이 창보다 길어 몸이 스크롤된다")
                self.assertLessEqual(window.height() - form.scroll.height(), 200, f"몸 {form.scroll.height()}px — 창 높이에서 제목·상태 줄·단추 줄·여백만 뺀 만큼 쓴다(실측 174px)")
                self.assertGreater(form.scroll.maximumHeight(), 5000, "몸 높이에 따로 정한 상한이 없다")
        self.assertGreaterEqual(form.scroll.height(), 300, "최소 창에서도 몸이 한 줄의 반 이상은 보인다")


if __name__ == "__main__":
    unittest.main()
