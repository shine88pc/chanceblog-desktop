"""후속 정리 둘째 묶음(POLISH-2)의 순수 시험(PySide6 없이 돈다 — CI 와 같은 조건) — POLISH-1 의 독립 검증이 '병합은 막지 않지만 고칠 만하다' 고 남긴 작은 어색함(QP-4)과 툴팁 글(SP-7·QP-5)의 소스 규칙.

지키는 것:
  1) 개수가 붙는 칩의 보이는 글은 늘 `이름 · 개수` 다 — 숫자로 끝나는 이름도 아닌 이름도 같은 구분 글이라 한 줄에 놓인 칩들 사이에서 구분 글이 섞이지 않는다(QP-4 ①). 접근 이름은 이름이 숫자로 끝날 때만 쉼표로 가르는 것이 그대로다.
  2) 문장 속에 ` · ` 로 이어 붙는 채널 줄(Seed 가져오기·일괄 바꾸기·후보 만들기 확인창)은 줄 앞머리에 쌍점이 없고 줄마다 `이름: 개수` 의 쌍점 하나뿐이다 — 쌍점이 두 번 겹치지 않고(QP-4 ②), 이름이 숫자로 끝나도 개수와 붙어 읽히지 않는다(QP-4 ③).
  3) 후보 화면 주제 묶음 칩의 접근 이름은 채널 칩과 같은 모양(`이름, 개수`)이다 — 식별자 그대로 보이는 묶음 이름이 숫자로 끝나도 개수와 붙어 읽히지 않는다(QP-4 ③).
  4) 툴팁에 사용자가 친 글(별명·제목)을 넣는 자리는 모두 `plain_tooltip` 을 거친다 — 소스 규칙(SP-7·QP-5: 별명이 `<b>x</b>` 모양이어도 툴팁이 칩 글과 같게 글자 그대로 보인다. 실제로 보이는 모양은 `test_ui_qt_polish2`).
실제 블로그 이름·아이디·주소는 이 시험에 없다(예시 값뿐).
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_ui_candidates_core as cc  # noqa: E402
import test_ui_seeds_core as sc  # noqa: E402

from chanceblog_desktop.ui.core import channel_names as cn, part_rules, text  # noqa: E402

T = text.T
QT_DIR = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"
NAMES = ("전체", "모든 소속", "공통", "GitHub Pages", "Blogger 1", "Blogger 2", "네이버 블로그 1", "네이버 블로그 2", "맛집 2024", "A&B", "R&D 2", "예시 가게", "😀🚀")


class ChipCaptionTest(unittest.TestCase):
    def test_every_name_gets_the_same_middle_dot_with_its_count_whatever_it_ends_with(self):
        for name in NAMES:
            for count in (0, 1, 9, 19, 1234):
                shown = part_rules.chip_caption(name, count)
                self.assertEqual(shown, f"{name} · {count}", (name, count))
                self.assertNotIn("  ", shown, "두 칸 구분 글은 더 이상 없다")
                self.assertEqual(shown.count(" · "), 1)

    def test_a_row_of_chips_never_mixes_separators(self):
        """한 줄에 놓이는 소속 칩들(다섯 채널·공통·모든 소속) — 이름이 숫자로 끝나는 칩과 아닌 칩이 같은 모양의 구분 글이다(`Blogger 1 · 1` 옆의 `GitHub Pages  1`)."""
        names = ["모든 소속", "공통", *[cn.chip_label(key) for key in cn.ORDER]]
        captions = [part_rules.chip_caption(name, number) for number, name in enumerate(names, start=1)]
        for caption in captions:
            self.assertRegex(caption, r"^.+ · \d+$", caption)

    def test_a_chip_without_a_count_is_still_the_name_only(self):
        for name in NAMES:
            self.assertEqual(part_rules.chip_caption(name, None), name)

    def test_the_accessible_name_still_uses_a_comma_after_a_name_that_ends_with_a_digit_and_a_space_after_any_other(self):
        """접근 이름은 이번에 안 바꿨다 — 보이는 글의 구분 글이 섞이는 것이 문제였고 화면 읽기 프로그램은 두 모양 모두 개수를 따로 읽는다."""
        self.assertEqual(part_rules.chip_accessible("네이버 블로그 1", 6), "네이버 블로그 1, 6")
        self.assertEqual(part_rules.chip_accessible("맛집 2024", 12), "맛집 2024, 12")
        self.assertEqual(part_rules.chip_accessible("전체", 19), "전체 19")
        self.assertEqual(part_rules.chip_accessible("GitHub Pages", 1), "GitHub Pages 1")


class ChannelLineTest(unittest.TestCase):
    """채널마다 `이름: 개수` 를 ` · ` 로 이어 붙인 한 줄 — 앞머리와 줄 사이는 쌍점이 아니라 줄표(` — `)다."""

    def line_of(self, body, header):
        lines = [line for line in body.splitlines() if line.startswith(header)]
        self.assertEqual(len(lines), 1, (header, body))
        return lines[0]

    def assert_one_colon_per_row(self, line, header, rows):
        self.assertNotIn(":", header, "앞머리에는 쌍점이 없다 — 줄마다의 쌍점과 겹치지 않는다")
        self.assertEqual(line.count(":"), rows, f"쌍점은 줄마다 하나뿐이다: {line}")
        self.assertNotRegex(line, r"\d \d+개", "이름 끝 숫자와 개수가 붙어 읽히지 않는다")

    def test_the_seed_import_dialog_line_has_one_colon_per_channel_and_none_in_its_header(self):
        controller = sc.seeds_view.SeedsController(sc.seeds.FakeSeedsProvider(import_mode="ok"), sc.jobs.JobRunner())
        sc.load(controller)
        sc.drive(controller, sc.partial(controller.start_import_preview, "가짜 파일 위치"))
        body = controller.import_dialog()["body"]
        header = T["seeds_imp_channels"].split("{rows}")[0]
        line = self.line_of(body, header)
        self.assertEqual(header, "승인하면 채널마다 쓸 수 있게 되는 Seed 수 — ")
        self.assert_one_colon_per_row(line, header, len(controller.import_info.per_channel))
        self.assertIn("네이버 블로그 1: 2개(후보 생성 켜짐)", line, "줄의 모양은 그대로다")

    def test_the_seed_bulk_dialog_line_has_one_colon_per_changed_channel_and_none_in_its_header(self):
        controller = sc.new_controller()
        for seed_id in ("EX001", "EX002", "EX003", "EX004", "EX005", "EX006", "EX009"):
            controller.toggle_check(seed_id)
        body = controller.bulk_dialog("activate")["body"]
        header = T["seeds_bulk_counts"].split("{rows}")[0]
        line = self.line_of(body, header)
        self.assertEqual(header, "바꾼 뒤 채널마다 쓸 수 있는 Seed 수 — ")
        rows = line.count("→")
        self.assertGreaterEqual(rows, 1)
        self.assert_one_colon_per_row(line, header, rows)
        self.assertIn(T["seeds_bulk_count_row"].format(name="네이버 블로그 1", before=3, after=7), line, "줄의 모양은 그대로다")

    def test_the_candidate_make_dialog_line_uses_the_same_row_shape_and_the_same_header_as_the_seed_dialogs(self):
        engine = tuple(cc.cd.ChannelPreview(key, name, number) for number, (key, name) in enumerate((("github_pages", "예시 지"), ("blogger_en", "예시 영 1"), ("blogger_ko", "예시 한 2"), ("naver_a", "네이버 블로그 1"), ("naver_b", "예시 나")), start=1))
        provider = cc.Scripted(cc.data_of(cc.ts.rated(80, candidate_id="c-1"), sample=False), preview=cc.preview_of())
        provider.gate.set()
        controller = cc.new_controller(provider)
        controller.preview = cc.cd.MakePreview(store="ok", channels=engine, total_new=15, seeds_used=3)
        body = controller.make_dialog()["body"]
        header = T["cand_make_counts"].split("{rows}")[0].format(total=15)
        line = self.line_of(body, header)
        self.assertEqual(header, "새 후보를 최대 15개 만들어요 — ")
        self.assert_one_colon_per_row(line, header, 5)
        self.assertIn("네이버 블로그 1: 4개", line)
        self.assertIn("예시 영 1: 2개", line, "이름이 숫자로 끝나도 개수와 붙지 않는다")
        self.assertIn("예시 한 2: 3개", line)

    def test_no_wording_puts_a_name_straight_in_front_of_a_number_any_more(self):
        """이름이 들어가는 칸 `{name}` 바로 뒤에 공백 하나와 숫자 칸이 오는 문구(`{name} {n}개`)가 채널·묶음 이름 줄에 남지 않았다 — 앞서 고친 것(POLISH-1)에 후보 만들기 줄과 주제 묶음 접근 이름을 더했다."""
        for key in ("seeds_channel_chip", "seeds_imp_channel_row", "seeds_bulk_count_row", "cand_filter_channel_a11y", "cand_make_row", "cand_filter_cluster_a11y"):
            self.assertNotRegex(T[key], r"\{name\} \{(?:n|before)\}", key)


class ClusterChipTest(unittest.TestCase):
    def test_the_topic_group_chip_reads_its_name_and_count_apart_when_the_name_ends_with_a_digit(self):
        controller = cc.new_controller(data=cc.data_of(cc.ts.make(topic_cluster="group2", candidate_id="c-new"), cc.ts.make(topic_cluster="group2", candidate_id="c-new-2"), cc.ts.make(topic_cluster="local-ai", candidate_id="c-ai")))
        chips = {chip["key"]: chip for chip in controller.view()["filters"]["cluster"]}
        self.assertEqual(chips["group2"]["a11y"], "주제 묶음 group2, 2개", "이름 끝 숫자와 개수 사이에 쉼표 — `group22개` 로 읽히지 않는다")
        self.assertEqual(chips["local-ai"]["a11y"], "주제 묶음 로컬 AI, 1개")
        self.assertEqual(T["cand_filter_cluster_a11y"], "주제 묶음 {name}, {n}개")

    def test_the_topic_group_chip_has_the_same_shape_as_the_channel_chip(self):
        channel = T["cand_filter_channel_a11y"].format(name="네이버 블로그 1", n=6)
        cluster = T["cand_filter_cluster_a11y"].format(name="네이버 블로그 1", n=6)
        self.assertEqual(channel.split(" ", 1)[1], cluster.split(" ", 2)[2], "이름 뒤의 쉼표와 개수 모양이 같다")


class TooltipSourceRulesTest(unittest.TestCase):
    """툴팁에 사용자가 친 글이 들어가는 자리는 모두 `plain_tooltip` 을 거친다 — Qt 는 서식 글처럼 보이는 툴팁(`<b>…</b>`)을 서식으로 읽는다. 새 자리가 원문을 `setToolTip` 에 바로 넣으면 이 시험이 알린다(좁은 소스 규칙: 이 시험이 지키는 자리만 본다 — 다른 묶음이 앱 고정 글 툴팁을 더해도 깨지지 않는다)."""

    def source(self, name):
        return (QT_DIR / name).read_text(encoding="utf-8")

    def test_with_tooltip_and_the_places_that_carry_names_go_through_plain_tooltip(self):
        components = self.source("components.py")
        self.assertIn("def plain_tooltip(text):", components)
        body = components[components.index("def with_tooltip(widget, text):"):]
        self.assertIn("widget.setToolTip(plain_tooltip(text))", body.split("\n# ----", 1)[0], "`with_tooltip` 는 글을 `plain_tooltip` 으로 바꿔 단다")
        self.assertIn("self.setToolTip(plain_tooltip(text))", components, "ElidedLabel(블로그 이름·한 줄 설명)")
        self.assertIn("self.setToolTip(plain_tooltip(full))", components, "SemanticBadge")
        self.assertEqual(self.source("blog_parts.py").count('chip.setToolTip(UI.plain_tooltip(option["tip"]))'), 2, "Seed 서랍의 고르는 칩 둘(한 가지 고르기·여러 개 고르기)")
        screens = self.source("screens.py")
        self.assertIn('badge.setToolTip(UI.plain_tooltip(d["blog_tip"]))', screens, "홈 서랍의 블로그 배지")
        self.assertIn('button.setToolTip(UI.plain_tooltip(draft["tip"]))', screens, "홈 서랍의 초안 단추")
        self.assertIn("self.setToolTip(UI.plain_tooltip(self._full))", self.source("candidate_parts.py"), "후보 카드의 줄인 글")

    def test_no_raw_name_goes_straight_into_a_tooltip_in_those_files(self):
        raw = {"components.py": ("self.setToolTip(text)", "self.setToolTip(full)", "widget.setToolTip(text)"),
               "blog_parts.py": ('chip.setToolTip(option["tip"])',),
               "screens.py": ('badge.setToolTip(d["blog_tip"])', 'button.setToolTip(draft["tip"])'),
               "candidate_parts.py": ("self.setToolTip(self._full)",)}
        for name, snippets in raw.items():
            source = self.source(name)
            for snippet in snippets:
                self.assertNotIn(snippet, source, f"{name}: 원문을 그대로 툴팁에 넣었다 — `plain_tooltip` 을 거쳐야 한다: {snippet}")

    def test_the_helper_leaves_a_text_alone_unless_it_looks_like_markup_so_ordinary_tooltips_do_not_change(self):
        """소스 모양 — 서식 글처럼 보일 때만 감싼다(`Qt.mightBeRichText` 가 참일 때). 거의 모든 툴팁은 한 글자도 안 바뀐다. 실제 동작은 `test_ui_qt_polish2`."""
        components = self.source("components.py")
        helper = components[components.index("def plain_tooltip(text):"):components.index("def with_tooltip(widget, text):")]
        self.assertIn("QtGui.Qt.mightBeRichText(text)", helper)
        self.assertIn("html.escape(text, quote=False)", helper)
        self.assertIn("return text", helper)


class DialogSourceRulesTest(unittest.TestCase):
    """확인창(`Dialog`)의 두 고침은 PySide6 시험(`test_ui_qt_polish2`)이 동작으로 지키고, 여기서는 CI(PySide6 없음)에서도 보이는 소스 모양을 지킨다 — 바꿔 열기 예약이 받는 객체를 함께 주는 형태이고, 높이 규칙이 `roomy`·`tight` 두 한도와 8px 여백을 갖는다."""

    def dialog_method(self, name):
        tree = ast.parse((QT_DIR / "components.py").read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Dialog")
        return next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)

    def test_the_replace_schedule_passes_its_receiver_so_it_is_cancelled_when_the_dialog_is_deleted(self):
        code = ast.unparse(self.dialog_method("present"))
        self.assertIn("QTimer.singleShot(0, self, self._replace_settled)", code)
        self.assertNotIn("QTimer.singleShot(0, self._replace_settled)", code, "받는 객체 없는 예약은 지워진 부품에 `place()` 를 부른다(SP-6)")
        self.assertIn("if replacing:", code, "바꿔 열 때만 예약한다(새로 여는 확인창은 그대로)")

    def test_the_height_rule_has_a_usual_limit_and_a_tight_one_with_eight_pixel_margins(self):
        code = ast.unparse(self.dialog_method("place"))
        for needed in ("roomy = max(120, parent.height() - 32)", "tight = max(120, parent.height() - 16)", "self.resize(width, needed if needed <= tight else roomy)", "max(8, (parent.height() - self.height()) // 2)"):
            self.assertIn(needed, code, needed)
        self.assertNotIn("max(16, (parent.height() - self.height()) // 2)", code, "위쪽 여백 최솟값이 16 이면 조금 넘치는 확인창의 아래 여백이 모자란다(PQ-18)")


if __name__ == "__main__":
    unittest.main()
