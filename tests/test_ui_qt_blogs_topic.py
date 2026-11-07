"""블로그 관리 화면의 **주제 설정 세 칸**(우선 키워드·제외 키워드·선호 글 유형 — P4c)의 PySide6 시험 — 창을 화면에 띄우지 않고(offscreen) 새 구역·칸·칩·겹침 오류·쓰기 흐름·읽기 전용 증명·키보드·접근 이름·배치를 확인한다.
**PySide6 가 없으면 통째로 건너뛴다**(CI 에는 PySide6 가 없다 — 순수 부분은 `test_ui_blogs_topic`). 사용자의 클립보드·보관소·데이터 폴더·설정 파일은 건드리지 않는다(가짜 공급자·임시 폴더의 실제 서비스). 옛 시험의 바탕(`Base`)을 그대로 쓴다.

지키는 것:
  1) 새 구역 `주제 설정(선택)` 이 자세한 정보와 모양 사이에 있고 설명은 사실만 말한다(지금은 저장만 — 아직 연결되어 있지 않다). 칸은 이름·힌트(한도 숫자)·접근 이름이 있고 칩은 글 유형 다섯이 서비스의 이름 그대로 보이며 누르는 칸은 36px 이상이다.
  2) 칸을 고치는 동안 화면을 다시 그리지 않고, 칩은 눌러서도 키보드(Space)로도 켜고 끌 수 있으며 칩마다 따로 Tab 정거장이다. 되돌리기는 저장된 값으로 돌려놓는다.
  3) 우선·제외에 같은 낱말이 있으면 고친 칸 옆에, 저장을 시도하면 두 칸 옆에 쉬운 문장이 보이고 첫 오류 칸으로 포커스·스크롤이 가며 서비스를 부르지 않는다. 두 칸을 함께 바꾸는 옳은 요청(바꿔치기)은 저장된다.
  4) 실제 서비스: 등록하며 세 칸을 채워 저장→다시 열면 보인다·삭제가 세 칸을 비운다·키 모양은 서비스가 거절해 칸 옆에 문장이 보이고 입력은 남는다·손으로 고친 판 2 파일의 값이 보이고 다른 칸을 저장해도 보존된다.
  5) 열고 고르고 고치고 칩을 눌러도 **파일이 하나도 안 바뀐다**(임시 폴더 전체 바이트).
  6) 여섯 크기에서 글자 잘림·눌림·가로 스크롤이 없고 아래 고정 행동 줄이 창 안에 있다. 허용된 가장 긴 값(20개×30자·글 유형 다섯)도 마찬가지다. 작은 노트북(1366×768 의 125%)에서 겹침 오류가 붙어도 저장 줄이 창 안이고 첫 오류 칸이 문장까지 보인다.
"""
import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.ui import blogs_adapter  # noqa: E402
from chanceblog_desktop.ui.core import blogs, text, tokens  # noqa: E402

import service_support as support  # noqa: E402
from test_ui_qt_blogs import HAVE, SIZES, Base  # noqa: E402,I001

if HAVE:
    import ui_offscreen
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication
    from chanceblog_desktop.ui.qt import components as UI

T = text.T
THREE = ("priority_keywords", "exclude_keywords", "preferred_post_types")
POST_TYPES = ("정보형", "비교형", "문제 해결형", "제품·서비스 소개형", "장소·업체 정보형")      # 서비스의 `POST_TYPES` 와 같은 다섯 — 시험이 직접 적는다


def read_profiles(ctx):
    path = Path(ctx.workspace.root) / "topic_engine" / "channel_profiles.json"
    return {item["key"]: item for item in json.loads(path.read_text(encoding="utf-8"))["profiles"]}


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class TopicSectionTest(Base):
    def test_the_topic_section_sits_between_the_detail_and_look_sections_and_its_text_says_only_what_is_true(self):
        window = self.make()
        ui = self.ui(window)
        order = list(ui.fields)
        self.assertEqual(len(order), 18)
        self.assertEqual(order[order.index("monetization_focus") + 1:order.index("color_preset")], list(THREE))
        labels = {label.plain_text(): label for label in window.screen_widget.findChildren(UI.Label)}
        titles = ("자세한 정보(선택)", "주제 설정(선택)", "모양(선택)")
        for title in titles:
            self.assertIn(title, labels)
        ys = [labels[title].mapTo(window, labels[title].rect().topLeft()).y() for title in titles]
        self.assertLess(ys[0], ys[1])
        self.assertLess(ys[1], ys[2])
        desc = next(name for name in labels if name.startswith("이 블로그에서 먼저 다루고 싶은 낱말, 피하고"))
        self.assertEqual(desc, T["blogs_sec_topic_desc"])
        for part in ("저장만", "아직 연결되어 있지 않아요"):
            self.assertIn(part, desc)

    def test_the_keyword_fields_are_named_text_inputs_and_the_post_types_are_five_named_chips(self):
        window = self.make()
        fields = self.ui(window).fields
        for name, label in (("priority_keywords", "우선 키워드"), ("exclude_keywords", "제외 키워드")):
            view = fields[name]
            self.assertEqual((view.kind, view.edit.accessibleName(), len(view.controls)), ("words", label, 1), name)
            self.assertGreaterEqual(view.edit.height(), tokens.SIZE["hit"], name)
            hint = view.hint.plain_text()
            self.assertIn("20개", hint)
            self.assertIn("30자", hint)
            self.assertEqual(view.edit.accessibleDescription(), hint, "칸의 접근 설명이 안내다")
        self.assertEqual(fields["priority_keywords"].edit.text(), "예시 키워드 하나, 예시 키워드 둘")
        self.assertEqual(fields["exclude_keywords"].edit.text(), "예시 제외어")
        self.assertIn("우선 키워드와 같은 낱말은 쓸 수 없어요", fields["exclude_keywords"].hint.plain_text())
        view = fields["preferred_post_types"]
        self.assertEqual((view.kind, list(view.chips)), ("multi", list(POST_TYPES)))
        for value, chip in view.chips.items():
            self.assertEqual(chip.text(), value, "글 유형 이름은 서비스의 값 그대로다")
            self.assertEqual(chip.accessibleName(), f"선호 글 유형: {value}")
            self.assertGreaterEqual(chip.height(), tokens.SIZE["hit"], value)
            self.assertEqual(chip.isChecked(), value in ("정보형", "비교형"), value)
        for name in THREE:
            self.assertEqual([label.text() for label in fields[name].findChildren(UI.Label) if label.text() == "필수"], [], f"{name}: 선택 칸에는 필수 표시가 없다")

    def test_typing_and_clicking_change_the_draft_and_the_buttons_without_redrawing_and_revert_restores_the_saved_values(self):
        window = self.make()
        screen, ui = window.screen_widget, self.ui(window)
        self.assertFalse(self.action(window, "save").isEnabled())
        self.type_into(window, "priority_keywords", "예시 새 키워드, 예시 둘째")
        self.assertIs(window.screen_widget, screen, "고치는 동안 화면을 다시 그리지 않는다")
        self.assertEqual(window.state.blogs.values("naver_a")["priority_keywords"], "예시 새 키워드, 예시 둘째")
        self.assertTrue(self.action(window, "save").isEnabled() and self.action(window, "revert").isEnabled())
        self.assertTrue(ui.unsaved.isVisibleTo(window))
        chip = ui.fields["preferred_post_types"].chips["문제 해결형"]
        chip.click()
        self.settle()
        self.assertTrue(chip.isChecked())
        self.assertEqual(sorted(window.state.blogs.values("naver_a")["preferred_post_types"]), ["문제 해결형", "비교형", "정보형"])
        self.assertIs(window.screen_widget, screen)
        self.assertEqual(window.state.blogs.dirty_names("naver_a"), ("priority_keywords", "preferred_post_types"))
        self.type_into(window, "priority_keywords", "예시 키워드 하나, 예시 키워드 둘")
        chip.click()
        self.settle()
        self.assertFalse(self.action(window, "save").isEnabled(), "저장된 값으로 돌아가면 저장 단추가 다시 꺼진다")
        self.type_into(window, "exclude_keywords", "예시 바뀐 제외어")
        self.assertTrue(self.action(window, "revert").isEnabled())
        self.action(window, "revert").click()
        self.settle()
        fields = self.ui(window).fields
        self.assertEqual((fields["exclude_keywords"].edit.text(), fields["priority_keywords"].edit.text()), ("예시 제외어", "예시 키워드 하나, 예시 키워드 둘"))
        self.assertFalse(window.state.blogs.is_dirty("naver_a"))

    def test_the_chips_work_by_click_and_by_keyboard_and_each_chip_is_its_own_tab_stop(self):
        window = self.make()
        view = self.ui(window).fields["preferred_post_types"]
        chip = view.chips["장소·업체 정보형"]
        chip.setFocus(Qt.TabFocusReason)
        QTest.keyClick(chip, Qt.Key_Space)
        self.settle()
        self.assertTrue(chip.isChecked())
        self.assertIn("장소·업체 정보형", window.state.blogs.values("naver_a")["preferred_post_types"])
        QTest.keyClick(chip, Qt.Key_Space)
        self.settle()
        self.assertFalse(chip.isChecked())
        self.assertNotIn("장소·업체 정보형", window.state.blogs.values("naver_a")["preferred_post_types"])
        start = window.nav_buttons["blogs"]
        self.focus(start)
        seen, current = [], start
        for _ in range(150):
            seen.append(current)
            current.focusNextChild()
            self.settle(1)
            current = QApplication.focusWidget()
            self.assertIsNotNone(current)
            if current is start:
                break
        else:
            self.fail("Tab 이 한 바퀴를 돌지 못했다")
        stops = {id(widget) for widget in seen}
        for name in THREE:
            for control in self.ui(window).fields[name].controls:
                self.assertIn(id(control), stops, f"{name}: {control.accessibleName()} 가 Tab 한 바퀴에 있다")


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class OverlapTest(Base):
    def test_a_word_in_both_keyword_fields_shows_a_sentence_beside_the_touched_field_then_both_after_a_save_try_and_never_calls_the_service(self):
        provider = blogs.FakeBlogsProvider()
        window = self.make(provider)
        calls = list(provider.calls)
        self.type_into(window, "exclude_keywords", "예시 제외어, 예시 키워드 둘")
        self.assertEqual(self.field_error(window, "exclude_keywords"), T["bf_err_overlap_exclude_keywords"], "고친 칸 옆에 먼저 보인다")
        self.assertEqual(self.field_error(window, "priority_keywords"), "")
        self.assertTrue(self.ui(window).fields["exclude_keywords"].edit.property("invalid"))
        self.action(window, "save").click()
        self.settle(8)
        ui = self.ui(window)
        self.assertEqual(ui.first_error, "priority_keywords", "화면에 놓인 순서의 첫 오류 칸")
        self.assertEqual((self.field_error(window, "priority_keywords"), self.field_error(window, "exclude_keywords")), (T["bf_err_overlap_priority_keywords"], T["bf_err_overlap_exclude_keywords"]))
        self.assertIs(window.focusWidget(), ui.fields["priority_keywords"].controls[0], "첫 문제 칸으로 포커스가 간다")
        self.assertEqual(provider.calls, calls, "서비스를 부르지 않는다")
        self.assertEqual(window.state.blogs.notice, ("error", T["blogs_save_invalid"]))
        for name in ("priority_keywords", "exclude_keywords"):
            self.assertIn("한쪽에서만 적어 주세요", ui.fields[name].edit.accessibleDescription(), "오류 문장이 칸의 접근 설명에 실린다")
            self.assertNotIn("예시 키워드 둘", self.field_error(window, name), "입력한 낱말을 되풀이하지 않는다")
        self.type_into(window, "exclude_keywords", "예시 제외어")
        self.assertEqual((self.field_error(window, "priority_keywords"), self.field_error(window, "exclude_keywords")), ("", ""), "한쪽에서 빼면 둘 다 풀린다")

    def test_swapping_a_word_between_the_two_fields_passes_and_is_saved_from_the_screen(self):
        provider = blogs.FakeBlogsProvider()
        window = self.make(provider)
        self.type_into(window, "priority_keywords", "예시 키워드 둘, 예시 제외어")
        self.type_into(window, "exclude_keywords", "예시 키워드 하나")
        self.assertEqual((self.field_error(window, "priority_keywords"), self.field_error(window, "exclude_keywords")), ("", ""))
        self.action(window, "save").click()
        self.wait_write(window)
        self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_saved"]))
        slot = provider.slots["naver_a"]
        self.assertEqual((slot.priority_keywords, slot.exclude_keywords), (("예시 키워드 둘", "예시 제외어"), ("예시 키워드 하나",)))


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class RealServiceTest(Base):
    def test_register_with_topic_settings_reopen_and_clear_through_the_screen_with_the_real_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            window = self.make(provider)
            self.type_into(window, "display_name", "예시 블로그 가")
            self.type_into(window, "blog_ref", "example-blog-a")
            self.type_into(window, "priority_keywords", "예시 우선 하나, 예시 우선 둘")
            self.type_into(window, "exclude_keywords", "예시 제외어")
            chips = self.ui(window).fields["preferred_post_types"].chips
            chips["문제 해결형"].click()
            chips["정보형"].click()
            self.action(window, "save").click()
            self.wait_write(window)
            self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_saved"]))
            data = read_profiles(ctx)
            self.assertEqual((data["naver_a"]["priority_keywords"], data["naver_a"]["exclude_keywords"], data["naver_a"]["preferred_post_types"]), (["예시 우선 하나", "예시 우선 둘"], ["예시 제외어"], ["정보형", "문제 해결형"]))
            for key, item in data.items():
                if key != "naver_a":
                    self.assertEqual([item[name] for name in THREE], [[], [], []], f"{key}: 다른 슬롯은 그대로")
            window.close()
            again = self.make(provider)                                                                     # 다시 열면 저장한 값이 보인다
            fields = self.ui(again).fields
            self.assertEqual((fields["priority_keywords"].edit.text(), fields["exclude_keywords"].edit.text()), ("예시 우선 하나, 예시 우선 둘", "예시 제외어"))
            self.assertEqual([value for value, chip in fields["preferred_post_types"].chips.items() if chip.isChecked()], ["정보형", "문제 해결형"])
            self.assertFalse(again.state.blogs.is_dirty("naver_a"))
            self.action(again, "delete").click()                                                            # 삭제 = 슬롯 비우기 — 세 칸도 비워진다
            self.settle()
            next(button for button in again.dialog.findChildren(QAbstractButton) if button.text() == "지우기").click()
            self.wait_write(again)
            cleared = read_profiles(ctx)["naver_a"]
            self.assertEqual([cleared[name] for name in THREE], [[], [], []])
            fields = self.ui(again).fields
            self.assertEqual((fields["priority_keywords"].edit.text(), fields["exclude_keywords"].edit.text()), ("", ""))
            self.assertFalse([chip for chip in fields["preferred_post_types"].chips.values() if chip.isChecked()])

    def test_a_key_shaped_keyword_is_refused_by_the_real_service_with_the_sentence_beside_the_field_and_the_input_stays(self):
        shape = "AK" + "IA" + "ABCDEFGHIJKLMNOP"                                                              # 키 모양의 가짜 값 — 조각으로 나눠 적어 저장소에 키 문자열이 없다
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            window = self.make(provider)
            self.type_into(window, "blog_ref", "example-blog-a")
            self.type_into(window, "exclude_keywords", shape)
            before = support.tree_snapshot(Path(ctx.workspace.root))
            self.action(window, "save").click()
            self.wait_write(window)
            self.assertEqual(support.tree_snapshot(Path(ctx.workspace.root)), before, "아무것도 쓰지 않았다")
            self.assertEqual(self.field_error(window, "exclude_keywords"), T["bf_err_key_shape"])
            self.assertNotIn(shape, self.field_error(window, "exclude_keywords") + repr(window.state.blogs.notice), "문장에 입력한 값이 되풀이되지 않는다")
            self.assertEqual(self.ui(window).fields["exclude_keywords"].edit.text(), shape, "입력은 그대로 남는다")
            self.assertEqual(window.state.blogs.notice, ("error", T["blogs_fail_invalid"]))

    def test_opening_selecting_typing_and_clicking_the_new_fields_write_nothing_with_the_real_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            before = support.tree_snapshot(Path(ctx.workspace.root))
            listing = sorted(str(path) for path in Path(tmp).rglob("*"))
            window = self.make(provider)
            self.type_into(window, "priority_keywords", "예시 우선")
            self.type_into(window, "exclude_keywords", "예시 우선")                                           # 겹침 — 오류 표시만 한다
            chips = self.ui(window).fields["preferred_post_types"].chips
            chips["정보형"].click()
            chips["비교형"].click()
            self.settle()
            window.blog_select("naver_b")
            window.blog_select("naver_a")
            self.settle()
            self.action(window, "revert").click()
            self.settle()
            self.assertEqual(support.tree_snapshot(Path(ctx.workspace.root)), before)
            self.assertEqual(sorted(str(path) for path in Path(tmp).rglob("*")), listing, "열고 고르고 고치고 눌러도 파일도 폴더도 만들지 않는다")

    def test_a_hand_edited_version_two_file_shows_the_values_in_the_fields_and_saving_another_field_keeps_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            folder = Path(ctx.workspace.root) / "topic_engine"
            folder.mkdir(parents=True)
            profiles = tuple(dataclasses.replace(p, blog_ref="example-blog-a", priority_keywords=("예시 우선",), exclude_keywords=("예시 제외",), preferred_post_types=("비교형", "정보형"), home_regions=("예시 지역",), top_n=9)
                             if p.key == "naver_a" else p for p in ch.default_profiles())
            (folder / "channel_profiles.json").write_text(json.dumps(ch.profiles_to_dict(profiles), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            provider = blogs_adapter.ServiceBlogsProvider(context_factory=lambda data_dir=None: ctx)
            window = self.make(provider)
            fields = self.ui(window).fields
            self.assertEqual((fields["priority_keywords"].edit.text(), fields["exclude_keywords"].edit.text()), ("예시 우선", "예시 제외"))
            self.assertEqual([value for value, chip in fields["preferred_post_types"].chips.items() if chip.isChecked()], ["정보형", "비교형"])
            self.assertFalse(window.state.blogs.is_dirty("naver_a"), "손으로 적은 순서가 달라도 고친 것이 아니다")
            self.type_into(window, "alias", "예시 별명")
            self.action(window, "save").click()
            self.wait_write(window)
            self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_saved"]))
            mine = read_profiles(ctx)["naver_a"]
            self.assertEqual((mine["priority_keywords"], mine["exclude_keywords"], mine["preferred_post_types"], mine["home_regions"], mine["top_n"], mine["alias"]),
                             (["예시 우선"], ["예시 제외"], ["비교형", "정보형"], ["예시 지역"], 9, "예시 별명"))


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class LayoutTest(Base):
    def reveal(self, window, name):
        ui = self.ui(window)
        ui.form_scroll.ensureWidgetVisible(ui.fields[name], 0, 12)
        self.settle(2)
        return ui.fields[name], ui.form_scroll.viewport()

    def test_the_new_section_never_clips_or_squeezes_and_the_save_row_stays_in_the_window_at_every_size(self):
        for size in SIZES:
            with self.subTest(size=size):
                window = self.make(size=size)
                for name in THREE:
                    view, viewport = self.reveal(window, name)
                    top, bottom = view.mapTo(viewport, view.rect().topLeft()).y(), view.mapTo(viewport, view.rect().bottomLeft()).y()
                    if view.height() <= viewport.height():
                        self.assertGreaterEqual(top, 0, f"{size} {name}: 칸 이름이 잘리지 않는다")
                        self.assertLessEqual(bottom, viewport.height() + 1, f"{size} {name}: 칸 아래(안내)까지 보인다")
                    self.assertEqual(ui_offscreen.find_clipping(window), [], f"{size} {name}")
                    self.assertEqual(ui_offscreen.find_squeezed(window), [], f"{size} {name}: 부품이 눌려 반쯤 잘리는 곳이 없다")
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, f"{size}: 가로 스크롤이 없다")
                button = self.action(window, "save")
                if size != (900, 560):
                    self.assertLessEqual(button.mapTo(window, button.rect().bottomLeft()).y(), window.height(), f"{size}: 저장 단추가 창 안에 보인다")
                    self.assertEqual(window.scroll.verticalScrollBar().maximum(), 0, f"{size}: 페이지가 창보다 길지 않다 — 칸이 늘어도 폼 안쪽 스크롤이 받는다")
                window.close()

    def test_the_longest_allowed_values_never_clip_or_squeeze_and_are_saved(self):
        priority = ", ".join(f"{'가' * 28}{index:02d}" for index in range(20))
        exclude = ", ".join(f"{'나' * 28}{index:02d}" for index in range(20))
        for size in ((1366, 768), (900, 560)):
            with self.subTest(size=size):
                window = self.make(size=size)
                window.blog_edit("priority_keywords", priority)
                window.blog_edit("exclude_keywords", exclude)
                for value in POST_TYPES:
                    if not self.ui(window).fields["preferred_post_types"].chips[value].isChecked():
                        self.ui(window).fields["preferred_post_types"].chips[value].click()
                self.settle(4)
                self.assertEqual(window.state.blogs.problems("naver_a"), {}, "허용된 가장 긴 값이다 — 문제가 없다")
                self.assertEqual(len(window.state.blogs.values("naver_a")["preferred_post_types"]), 5)
                self.reveal(window, "preferred_post_types")
                self.assertEqual(ui_offscreen.find_clipping(window), [], size)
                self.assertEqual(ui_offscreen.find_squeezed(window), [], size)
                self.action(window, "save").click()
                self.wait_write(window)
                self.assertEqual(window.state.blogs.notice, ("ok", T["blogs_saved"]))
                saved = window.state.blogs.provider.slots["naver_a"]
                self.assertEqual((len(saved.priority_keywords), len(saved.exclude_keywords), saved.preferred_post_types), (20, 20, POST_TYPES))
                self.assertEqual(window.scroll.horizontalScrollBar().maximum(), 0, f"{size}: 긴 값이 가로 스크롤을 만들지 않는다")
                window.close()

    def test_an_overlap_error_keeps_the_save_row_in_the_window_and_scrolls_the_first_error_whole_into_view_at_the_small_laptop_size(self):
        for size in ((1093, 614), (1366, 768), (1280, 720)):
            with self.subTest(size=size):
                window = self.make(size=size)
                self.type_into(window, "exclude_keywords", "예시 제외어, 예시 키워드 둘")
                self.action(window, "save").click()
                self.settle(8)
                ui = self.ui(window)
                self.assertEqual(ui.first_error, "priority_keywords")
                self.assertTrue(window.screen_widget.findChildren(UI.Label))
                bar = ui.bar
                self.assertLessEqual(bar.mapTo(window, bar.rect().bottomLeft()).y(), window.height(), f"{size}: 알림 줄이 붙어도 행동 줄이 창 안에 있다")
                self.assertEqual(window.scroll.verticalScrollBar().maximum(), 0, f"{size}: 페이지가 창보다 길지 않다")
                view, viewport = ui.fields["priority_keywords"], ui.form_scroll.viewport()
                self.assertGreaterEqual(view.mapTo(viewport, view.rect().topLeft()).y(), 0, "칸 이름이 잘리지 않는다")
                self.assertLessEqual(view.mapTo(viewport, view.rect().bottomLeft()).y(), viewport.height() + 1, "오류 문장까지 한 덩어리로 보인다(행동 줄 뒤로 숨지 않는다)")
                self.assertTrue(view.error_row.isVisibleTo(window))
                other, viewport = self.reveal(window, "exclude_keywords")
                self.assertTrue(other.error_row.isVisibleTo(window))
                self.assertLessEqual(other.mapTo(viewport, other.rect().bottomLeft()).y(), viewport.height() + 1, "둘째 오류 칸도 문장까지 보인다")
                self.assertEqual(ui_offscreen.find_squeezed(window), [], size)
                window.close()


if __name__ == "__main__":
    unittest.main()
