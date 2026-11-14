"""안내·결과 문장의 글 색 시험 — 확인 015 승인 10번(데스크톱 F029, 결정 D-487): 흰 바탕의 흐린 안내·결과 문장(`Text/Muted`, 대비 약 3.2)을 기존의 보조 글 색(`Text/Secondary`, 약 5.4)으로 읽히게 한다.
승인 범위는 **문장 색뿐**이다 — 입력 칸 테두리에 새 진한 색을 더하지 않고(승인한 목업의 색을 바꾸지 않는다) 새 색 값도 만들지 않는다. 흐린 글은 '힌트·빈 값'(값 칸의 없음 표시·점선 하나)에만 남는다.

지키는 것:
  1) (PySide6 없이 돈다 — CI 와 같은 조건) 값: 승인 때의 숫자(3.2 와 5.4 — 입력 칸 테두리 1.7)가 토큰의 실제 값을 WCAG 식으로 직접 계산한 값과 맞는다. 입력 칸 테두리 색 토큰과 그 스타일시트 줄은 그대로다.
     `sub` 와 `muted` 는 글자 크기·굵기·줄 높이가 같고 글자 색 키만 다르다(역할을 바꿔도 화면 배치가 달라지지 않는다).
  2) (PySide6 없이 돈다) 소스: 화면 소스(`ui/qt/*.py`)에서 `muted` 역할을 쓰는 곳은 **빈 값 다섯 곳**(값 칸의 없음 표시·점선)뿐이고, 문장 일곱 곳은 `sub` 다 — 어느 쪽으로든 한 곳이 바뀌면 빨갛다.
  3) (PySide6 가 있을 때만) 실제 위젯: 후보 상세의 빈 문장 셋·후보 카드의 요약 없음·초안 작성의 저장 목록 비었음·확인 권장 없음·카테고리 없음이 `sub` 역할이고, 스타일시트가 그 역할에 주는 색은 흰 바탕 대비 4.5 이상이다.
     빈 값(`평가 전`·`—`)은 그대로 `muted` 다.
창을 띄우지 않는다(offscreen). 가짜 공급자·합성 값만 쓰고 파일·네트워크를 쓰지 않는다.
"""
import ast
import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from chanceblog_desktop.ui.core import tokens  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

HAVE = importlib.util.find_spec("PySide6") is not None
if HAVE:
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_offscreen
    ui_offscreen.prepare_environment()
    from PySide6.QtWidgets import QLabel
    from chanceblog_desktop.ui.core import candidates as cd
    from chanceblog_desktop.ui.core import candidates_view as cv
    from chanceblog_desktop.ui.core import jobs
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import candidate_parts, candidate_screen, draft_screen, theme
    from chanceblog_desktop.ui.qt import components as UI

QT_DIR = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"
LABEL_CALLS = {"UI.label", "UI.Label", "label", "ClampedLabel", "UI.ElidedLabel", "ElidedLabel"}

# 빈 값 — 값 칸에 '없음' 을 알리는 짧은 글이나 점선 하나. 흐린 글(Muted)의 본래 쓰임(`Text/Muted`: 힌트·빈 값)이라 그대로 둔다. (파일, 함수, 글 식) → 이유
VALUE_SITES = {
    ("candidate_parts.py", "FactorRow.__init__", "vm['text']"): "점수 구성 한 줄의 값 자리 — 평가하지 못한 항목의 `평가 전`",
    ("candidate_screen.py", "_rows", "row['value']"): "후보 상세의 이름·값 줄 — 값이 없을 때의 없음 표시",
    ("draft_screen.py", "_chips_card", "'—'"): "칩이 하나도 없는 줄의 점선 하나",
    ("screens.py", "drawer_content", "field['value']"): "홈 서랍의 이름·값 줄 — 값이 없을 때의 `데이터 없음`",
    ("seed_screen.py", "_info_card", "row['value']"): "Seed 정보의 이름·값 줄 — 값이 없을 때의 없음 표시",
}
# 문장 — 흰 바탕에서 읽어야 하는 안내·결과 글(한 문장). 보조 글(`sub`, Secondary)이어야 한다. (파일, 함수, 글 식) → 이유
SENTENCE_SITES = {
    ("candidate_parts.py", "CandidateCard.__init__", "vm['summary']"): "후보 카드의 추천 이유 요약이 없을 때의 안내(`추천 이유가 아직 없어요`)",
    ("candidate_screen.py", "detail_content", "factors['empty']"): "후보 상세 — 점수 구성 정보가 없다는 결과 문장",
    ("candidate_screen.py", "detail_content", "reason['empty']"): "후보 상세 — 추천 이유가 아직 없다는 결과 문장",
    ("candidate_screen.py", "detail_content", "safety['none']"): "후보 상세 — 확인이 필요한 표시가 없다는 결과 문장",
    ("draft_screen.py", "_text_card", "text"): "초안 작성의 추천 카테고리 — 정하지 못했을 때의 안내(`정하지 못했어요 — 블로그에서 직접 골라 주세요.`)",
    ("draft_screen.py", "_checks_card", "'· ' + line if group['lines'] else line"): "초안 작성의 확인 권장 — 이 글에만 해당하는 것이 없다는 결과 문장",
    ("draft_screen.py", "_saved_card", "saved['empty']"): "초안 작성의 저장한 초안 목록이 비었을 때의 안내",
}


def role_sites(path):
    """한 화면 소스에서 라벨을 만드는 호출 → [(파일, 함수, 글 식, 역할 식 안의 글자들)]. 글자 역할은 둘째 자리 인자(또는 `role=`)다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def owner(node):
        names = []
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
        return ".".join(reversed(names))

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func) in LABEL_CALLS:
            role = node.args[1] if len(node.args) > 1 else next((keyword.value for keyword in node.keywords if keyword.arg == "role"), None)
            if role is not None:
                words = frozenset(part.value for part in ast.walk(role) if isinstance(part, ast.Constant) and isinstance(part.value, str))
                found.append((path.name, owner(node), ast.unparse(node.args[0]) if node.args else "", words))
    return found


def all_role_sites():
    return [site for path in sorted(QT_DIR.glob("*.py")) for site in role_sites(path)]


def rule_color(qss, role):
    """스타일시트가 `QLabel[role="…"]` 에 주는 글자 색."""
    found = re.search(r'QLabel\[role="' + re.escape(role) + r'"\] \{[^}]*?color: (#[0-9A-Fa-f]{6})', qss)
    if found is None:
        raise AssertionError(f"역할 {role} 의 글자 색 줄이 없다")
    return found.group(1)


# ---- 1) 값 ---------------------------------------------------------------------------------------------------------------------------------
class ValuesTest(unittest.TestCase):
    def test_the_approved_numbers_are_the_real_contrasts_on_the_white_surface(self):
        """승인 때의 3.2(흐린 글)·5.4(보조 글)·1.7(입력 칸 테두리)은 토큰 값을 WCAG 식으로 직접 계산한 값이다."""
        colors = tokens.palette()
        muted, secondary, border = (tokens.contrast(colors[key], colors["surface"]) for key in ("text_muted", "text_secondary", "border_strong"))
        self.assertTrue(3.19 < muted < 3.21, muted)
        self.assertTrue(5.42 < secondary < 5.43, secondary)
        self.assertTrue(1.71 < border < 1.73, border)

    def test_the_sentence_color_is_an_existing_text_token_and_reads_as_normal_text_on_every_ground_the_cards_use(self):
        colors = tokens.palette()
        self.assertEqual(tokens.ROLE_TEXT["sub"], "text_secondary")
        self.assertIn("text_secondary", tokens.TEXT_KEYS)
        for ground in ("surface", "surface_2", "bg_app"):
            self.assertGreaterEqual(tokens.contrast(colors["text_secondary"], colors[ground]), 4.5, ground)

    def test_the_hint_color_and_the_input_border_colors_keep_their_approved_values(self):
        """승인한 것은 문장 색 바꾸기뿐 — 흐린 글 토큰도 입력 칸 테두리(새 진한 색을 더하지 않는다)도 그대로다."""
        colors = tokens.palette()
        self.assertEqual((colors["text_muted"], colors["text_secondary"]), ("#8491A3", "#5F6B7A"))
        self.assertEqual((colors["border"], colors["border_strong"], colors["secondary_border"]), ("#DCE4F0", "#B8C7DA", "#AFC1D8"))
        self.assertEqual(tokens.ROLE_TEXT["muted"], "text_muted", "흐린 글 역할은 그대로 흐린 글 색이다 — 바꾼 것은 문장 쪽 역할이다")

    def test_the_two_roles_differ_only_in_the_color_so_the_swap_cannot_move_the_layout(self):
        self.assertEqual(tokens.type_style("sub"), tokens.type_style("muted"))
        self.assertNotEqual(tokens.ROLE_TEXT["sub"], tokens.ROLE_TEXT["muted"])

    def test_the_input_rules_of_the_stylesheet_still_use_the_strong_border_token_and_no_text_color_as_a_border(self):
        """스타일시트 소스: 입력 칸(한 줄·편집기)의 테두리는 `border_strong` 이고 글자 색 토큰이 테두리로 쓰이지 않는다."""
        source = (QT_DIR / "theme.py").read_text(encoding="utf-8")
        for selector in ("QLineEdit", 'QPlainTextEdit[editor="true"]'):
            found = re.search(r"\n" + re.escape(selector) + r" \{\{[^\n]*?border: 1px solid \{c\['border_strong'\]\}", source)
            self.assertIsNotNone(found, f"{selector} 의 테두리가 border_strong 이 아니다")
        self.assertIsNone(re.search(r"border[a-z-]*: [^;\n]*\{c\['text_(?:strong|primary|secondary|muted)'\]\}", source), "글자 색 토큰이 테두리에 쓰였다")


# ---- 2) 소스 -------------------------------------------------------------------------------------------------------------------------------
class SourceSitesTest(unittest.TestCase):
    def test_the_muted_role_is_used_for_exactly_the_five_empty_value_places(self):
        sites = all_role_sites()
        muted = {site[:3] for site in sites if "muted" in site[3]}
        self.assertEqual(sorted(muted - set(VALUE_SITES)), [], "빈 값이 아닌 곳에 흐린 글(muted)이 새로 쓰였다 — 문장이면 `sub` 로, 빈 값이면 이 표에 이유와 함께 더한다")
        self.assertEqual(sorted(set(VALUE_SITES) - muted), [], "표의 빈 값 자리가 더는 muted 가 아니다 — 승인 범위(문장만) 밖을 바꿨거나 코드가 옮겨졌다")

    def test_the_seven_sentence_places_use_the_secondary_role(self):
        sub = {site[:3] for site in all_role_sites() if "sub" in site[3]}
        self.assertEqual(sorted(set(SENTENCE_SITES) - sub), [], "안내·결과 문장이 보조 글(sub)이 아니다")
        for site in all_role_sites():
            if site[:3] in SENTENCE_SITES:
                self.assertNotIn("muted", site[3], site[:3])

    def test_every_listed_place_has_a_real_reason(self):
        for table in (VALUE_SITES, SENTENCE_SITES):
            for place, reason in table.items():
                self.assertGreaterEqual(len(reason), 12, place)
        self.assertFalse(set(VALUE_SITES) & set(SENTENCE_SITES))

    def test_the_scanner_itself_sees_a_synthetic_muted_sentence_and_ignores_badges(self):
        """이 시험의 눈이 정말 muted 라벨을 잡고 배지(`UI.Badge("muted", …)` — 다른 부품)는 놓아주는지 합성 소스로 확인한다."""
        import tempfile
        source = ("def f(UI, row):\n    UI.label(row['x'], 'muted', wrap=True)\n    UI.label(row['y'], 'small' if row['z'] else 'muted')\n    UI.Badge('muted', 'a')\n"
                  "    ClampedLabel(row['w'], role='muted')\n    UI.label(row['v'], 'sub')\n")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.py"
            path.write_text(source, encoding="utf-8")
            found = role_sites(path)
        self.assertEqual([(site[2], "muted" in site[3]) for site in found], [("row['x']", True), ("row['y']", True), ("row['w']", True), ("row['v']", False)])


# ---- 3) 실제 위젯 --------------------------------------------------------------------------------------------------------------------------
class _Shell:
    """화면 부품이 단추를 이을 때 부르는 셸 자리 — 아무 일도 하지 않는다."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def label_texts(root):
    return {(label.plain_text() if isinstance(label, (UI.Label, candidate_parts.ClampedLabel)) else label.text()): label for label in root.findChildren(QLabel)}


@unittest.skipUnless(HAVE, "PySide6 가 설치되어 있지 않다")
class RenderedSentencesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = ui_offscreen.install_system_fonts()
        cls.app = qapp.make_app()
        cls.qss = theme.build_qss(theme.colors())
        cls.colors = tokens.palette()

    def assert_reads_as_a_sentence(self, label, what):
        role = label.property("role")
        self.assertEqual(role, "sub", f"{what}: 안내·결과 문장이 보조 글이 아니다({role})")
        color = rule_color(self.qss, role)
        self.assertEqual(color, self.colors["text_secondary"], what)
        self.assertGreaterEqual(tokens.contrast(color, self.colors["surface"]), 4.5, what)

    def detail_labels(self, part):
        provider = cd.FakeCandidatesProvider()
        controller = cv.CandidatesController(provider, jobs.JobRunner())
        controller.apply_loaded(provider.load_candidates(lambda *args, **kwargs: None, lambda: False))
        found = [row.candidate.candidate_id for row in controller.rows() if part in row.candidate.topic]
        self.assertEqual(len(found), 1, part)
        self.assertTrue(controller.select(found[0]))
        body = candidate_screen.detail_content(_Shell(), controller.detail_view())[0]
        self.addCleanup(body.deleteLater)
        return label_texts(body)

    def test_the_empty_sentences_of_a_candidate_without_a_score_read_as_secondary_text(self):
        labels = self.detail_labels("점수 계산 전인 예")
        for key in ("cand_factor_none", "cand_reason_none"):
            self.assert_reads_as_a_sentence(labels[T[key]], key)

    def test_the_no_safety_sentence_reads_as_secondary_text(self):
        labels = self.detail_labels("자주 묻는 것 모음")                                       # 협업·건강 표시가 없는 후보
        self.assert_reads_as_a_sentence(labels[T["cand_safety_none"]], "cand_safety_none")

    def test_a_card_without_a_summary_reads_as_secondary_text_and_one_with_a_summary_keeps_the_small_role(self):
        provider = cd.FakeCandidatesProvider()
        controller = cv.CandidatesController(provider, jobs.JobRunner())
        controller.apply_loaded(provider.load_candidates(lambda *args, **kwargs: None, lambda: False))
        cards = {vm["title"]: vm for vm in controller.view()["grid"]["cards"]}
        without = cards["예시 후보 아 — 점수 계산 전인 예"]
        with_text = cards["예시 후보 가 — 순서대로 따라 하는 안내"]
        self.assertEqual((without["summary_missing"], with_text["summary_missing"]), (True, False))
        card = candidate_parts.CandidateCard(without)
        self.addCleanup(card.deleteLater)
        self.assertEqual(card.summary_label.plain_text(), T["cand_summary_none"])
        self.assert_reads_as_a_sentence(card.summary_label, "cand_summary_none")
        other = candidate_parts.CandidateCard(with_text)
        self.addCleanup(other.deleteLater)
        self.assertEqual(other.summary_label.property("role"), "small", "요약이 있는 카드는 그대로 작은 보조 글이다")

    def test_the_category_that_could_not_be_decided_reads_as_secondary_text_and_a_real_category_is_body_text(self):
        missing_card = draft_screen._text_card("추천 카테고리", T["drf_category_none"], True)
        present_card = draft_screen._text_card("추천 카테고리", "합성 카테고리", False)
        self.addCleanup(missing_card.deleteLater)
        self.addCleanup(present_card.deleteLater)
        self.assert_reads_as_a_sentence(label_texts(missing_card)[T["drf_category_none"]], "drf_category_none")
        self.assertEqual(label_texts(present_card)["합성 카테고리"].property("role"), "body", "값이 있을 때는 본문 글 그대로다")

    def test_the_empty_saved_list_sentence_reads_as_secondary_text(self):
        saved = {"count_text": "0편", "title": T["drf_saved_title"], "a11y": "합성", "sub": "합성 부제", "notice": None, "state": "ok", "rows": [], "empty": T["drf_saved_empty"], "unreadable_note": "", "loading": "", "loading_a11y": "", "error": {}}
        card = draft_screen._saved_card(_Shell(), saved, draft_screen.DraftsUi())
        self.addCleanup(card.deleteLater)
        self.assert_reads_as_a_sentence(label_texts(card)[T["drf_saved_empty"]], "drf_saved_empty")

    def test_the_no_check_needed_sentence_reads_as_secondary_text_and_a_real_check_line_keeps_the_small_role(self):
        vm = {"title": T["drf_side_checks"], "status": "합성 상태", "open_text": "펼치기", "closed_text": "접기",
              "specific": {"key": "specific", "title": T["drf_chk_specific"], "lines": [], "open": True, "empty": T["drf_chk_specific_none"], "chip": "0건", "tone": "muted"},
              "common": {"key": "common", "title": T["drf_chk_common"], "lines": ["합성 확인 권장 한 줄"], "open": False, "chip": "1건", "tone": "muted"}}
        card = draft_screen._checks_card(_Shell(), vm, draft_screen.DraftsUi())
        self.addCleanup(card.deleteLater)
        labels = label_texts(card)
        self.assert_reads_as_a_sentence(labels[T["drf_chk_specific_none"]], "drf_chk_specific_none")
        self.assertEqual(labels["· 합성 확인 권장 한 줄"].property("role"), "small", "있는 확인 권장은 그대로 작은 보조 글이다")

    def test_the_empty_values_keep_the_hint_color(self):
        """빈 값(`평가 전`)은 흐린 글 그대로 — 승인한 것은 문장 색뿐이다."""
        row = candidate_parts.FactorRow({"a11y": "합성", "name": "시기", "text": T["cand_factor_missing"], "missing": True, "fraction": 0, "weight_text": ""})
        self.addCleanup(row.deleteLater)
        self.assertEqual(row.value_label.property("role"), "muted")
        self.assertEqual(rule_color(self.qss, "muted"), self.colors["text_muted"])

    def test_the_stylesheet_gives_the_input_boxes_the_approved_border_color(self):
        for selector in ("QLineEdit", 'QPlainTextEdit\\[editor="true"\\]'):
            found = re.search(r"\n" + selector + r" \{[^}]*border: 1px solid (#[0-9A-Fa-f]{6})", self.qss)
            self.assertIsNotNone(found, selector)
            self.assertEqual(found.group(1), "#B8C7DA", selector)


if __name__ == "__main__":
    unittest.main()
