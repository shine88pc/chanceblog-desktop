"""안내·결과 문장의 글 색 시험 — 확인 015 승인 10번(데스크톱 F029, 결정 D-487): 흰 바탕의 흐린 안내·결과 문장(`Text/Muted`, 대비 약 3.2)을 기존의 보조 글 색(`Text/Secondary`, 약 5.4)으로 읽히게 한다.
승인 범위는 **문장 색뿐**이다 — 입력 칸 테두리에 새 진한 색을 더하지 않고(승인한 목업의 색을 바꾸지 않는다) 새 색 값도 만들지 않는다. 흐린 글은 '힌트·빈 값'(값 칸의 없음 표시·점선 하나)에만 남는다.

지키는 것:
  1) (PySide6 없이 돈다 — CI 와 같은 조건) 값: 승인 때의 숫자(3.2 와 5.4 — 입력 칸 테두리 1.7)가 토큰의 실제 값을 WCAG 식으로 직접 계산한 값과 맞는다. 입력 칸 테두리 색 토큰과 그 스타일시트 줄은 그대로다.
     `sub` 와 `muted` 는 글자 크기·굵기·줄 높이가 같고 글자 색 키만 다르다(역할을 바꿔도 화면 배치가 달라지지 않는다).
  2) (PySide6 없이 돈다) 소스: 화면 소스(`ui/qt/*.py`)의 라벨 호출 **열두 곳**(문장 일곱·빈 값 다섯)의 글자 역할 **식**(`ast.unparse` 글)을 표로 못박는다 — 낱말이 더해지거나 빠지거나 조건이 뒤집히면(`'sub' if missing else 'body'` ↔ 반대) 빨갛다.
     `muted` 라는 글자가 화면 소스 어디에 새로 나와도(변수·키워드·기본값·묶음 속 포함) 빈 값 다섯 밖이면 빨갛고, 역할을 글자가 아닌 변수로 넘기는 새 라벨 호출도 허용 목록(역할을 받아 라벨을 만드는 부품 넷) 밖이면 빨갛다.
     스타일시트 소스(`theme.py`)는 입력 칸 선택자마다 규칙 하나이고(덧붙은 규칙이 뒤에서 테두리를 덮지 못한다) `sub`·`muted` 역할 규칙이 손으로 덧붙지 않았으며, 화면 소스에서 `setStyleSheet(` 는 `theme.py` 의 앱 전체 한 곳뿐이다.
  3) (PySide6 가 있을 때만) 실제 위젯: 후보 상세의 빈 문장 셋·후보 카드의 요약 없음·초안 작성의 저장 목록 비었음·확인 권장 없음·카테고리 없음이 `sub` 역할이고, 만들어진 스타일시트에 그 역할 규칙은 하나이며 보조 글 색이다.
     위젯이 **실제로 쓰는** 글자 색(`palette()` 의 WindowText)도 보조 글 색이고 흰 바탕 대비 4.5 이상이다. 빈 값(`평가 전`·`데이터 부족`·`조회하지 못했어요`)은 그대로 `muted` 이고 실제 색도 흐린 글 색이다.
     입력 칸은 스타일시트 글이 아니라 **그려진 그림**의 테두리 픽셀이 `#B8C7DA` 다.
창을 띄우지 않는다(offscreen). 가짜 공급자·합성 값만 쓰고 파일·네트워크를 쓰지 않는다.
"""
import ast
import collections
import functools
import importlib.util
import re
import sys
import tempfile
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
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget
    from chanceblog_desktop.ui.core import candidates as cd
    from chanceblog_desktop.ui.core import candidates_view as cv
    from chanceblog_desktop.ui.core import jobs
    from chanceblog_desktop.ui.qt import app as qapp
    from chanceblog_desktop.ui.qt import candidate_parts, candidate_screen, draft_screen, theme
    from chanceblog_desktop.ui.qt import components as UI

QT_DIR = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"
LABEL_CALLS = {"UI.label", "UI.Label", "label", "Label", "ClampedLabel", "UI.ElidedLabel", "ElidedLabel"}
BADGE_CALLS = {"UI.Badge", "Badge"}

# 빈 값 — 값 칸에 '없음' 을 알리는 짧은 글이나 점선 하나. 흐린 글(Muted)의 본래 쓰임(`Text/Muted`: 힌트·빈 값)이라 그대로 둔다. (파일, 함수, 글 식) → (역할 식, 이유)
VALUE_SITES = {
    ("candidate_parts.py", "FactorRow.__init__", "vm['text']"): ("'muted' if vm['missing'] else 'h3'", "점수 구성 한 줄의 값 자리 — 평가하지 못한 항목의 `평가 전`"),
    ("candidate_screen.py", "_rows", "row['value']"): ("'muted' if row['missing'] else 'body_lg'", "후보 상세의 이름·값 줄 — 값이 없을 때의 없음 표시(`데이터 부족`·`조회하지 못했어요` 포함)"),
    ("draft_screen.py", "_chips_card", "'—'"): ("'muted'", "칩이 하나도 없는 줄의 점선 하나"),
    ("screens.py", "drawer_content", "field['value']"): ("'muted' if field['missing'] else 'body_lg'", "홈 서랍의 이름·값 줄 — 값이 없을 때의 `데이터 없음`"),
    ("seed_screen.py", "_info_card", "row['value']"): ("'muted' if row['missing'] else 'body_lg'", "Seed 정보의 이름·값 줄 — 값이 없을 때의 없음 표시"),
}
# 문장 — 흰 바탕에서 읽어야 하는 안내·결과 글(한 문장). 보조 글(`sub`, Secondary)이어야 한다. (파일, 함수, 글 식) → (역할 식, 이유)
SENTENCE_SITES = {
    ("candidate_parts.py", "CandidateCard.__init__", "vm['summary']"): ("'sub' if vm['summary_missing'] else 'small'", "후보 카드의 추천 이유 요약이 없을 때의 안내(`추천 이유가 아직 없어요`)"),
    ("candidate_screen.py", "detail_content", "factors['empty']"): ("'sub'", "후보 상세 — 점수 구성 정보가 없다는 결과 문장"),
    ("candidate_screen.py", "detail_content", "reason['empty']"): ("'sub'", "후보 상세 — 추천 이유가 아직 없다는 결과 문장"),
    ("candidate_screen.py", "detail_content", "safety['none']"): ("'sub'", "후보 상세 — 확인이 필요한 표시가 없다는 결과 문장"),
    ("draft_screen.py", "_text_card", "text"): ("'sub' if missing else 'body'", "초안 작성의 추천 카테고리 — 정하지 못했을 때의 안내(`정하지 못했어요 — 블로그에서 직접 골라 주세요.`)"),
    ("draft_screen.py", "_checks_card", "'· ' + line if group['lines'] else line"): ("'small' if group['lines'] else 'sub'", "초안 작성의 확인 권장 — 이 글에만 해당하는 것이 없다는 결과 문장"),
    ("draft_screen.py", "_saved_card", "saved['empty']"): ("'sub'", "초안 작성의 저장한 초안 목록이 비었을 때의 안내"),
}
# 역할을 글자가 아닌 변수(`role`)로 그대로 넘기는 호출 — 역할을 받아 라벨을 만들어 주는 부품 넷. 이 밖에서 변수로 역할을 넘기면 어떤 글자가 들어가는지 이 시험이 볼 수 없으므로 허용하지 않는다.
PASS_THROUGH = {
    ("backup_parts.py", "BackupSection.__init__", "text"),
    ("components.py", "label", "text"),
    ("screens.py", "page_head", "title"),
    ("style_dialog.py", "StyleDialog._note", "text"),
}
# 입력 칸(한 줄·편집기)에 규칙을 거는 선택자 전부 — 스타일시트에서 나오는 순서 그대로. 규칙이 하나라도 더해지면 이 목록이 달라져 빨갛다(QSS 는 뒤 규칙이 이기므로 덧붙은 규칙이 테두리를 바꿀 수 있다).
INPUT_SELECTORS = ["QLineEdit", "QLineEdit:focus", "QLineEdit:disabled", 'QLineEdit[invalid="true"]', 'QLineEdit[invalid="true"]:focus', 'QPlainTextEdit[editor="true"]', 'QPlainTextEdit[editor="true"]:focus', 'QPlainTextEdit[mono="true"], QLabel[mono="true"]']


class Site(collections.namedtuple("Site", "file owner text role words literal")):
    """글자 역할을 받는 호출 하나 — 글 식(`text`)·역할 식(`role`, `ast.unparse` 글)·역할 식 안의 글자들·역할 식이 글자 리터럴뿐인가."""

    @property
    def key(self):
        return (self.file, self.owner, self.text)


def parse(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return tree, {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def owner_of(node, parents):
    names = []
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return ".".join(reversed(names))


def literal_role(node):
    """역할 식이 글자 리터럴이거나, 조건이 무엇이든 두 갈래가 모두 글자 리터럴인 조건식인가."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.IfExp):
        return literal_role(node.body) and literal_role(node.orelse)
    return False


def role_sites(path):
    """한 화면 소스에서 글자 역할을 받는 호출 → [Site]. 라벨을 만드는 호출은 둘째 자리 인자(또는 `role=`)가, 그 밖의 호출(`page_head(…, role=…)` 등)은 `role=` 키워드가 역할이다."""
    tree, parents = parse(path)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        keyword = next((item.value for item in node.keywords if item.arg == "role"), None)
        role = node.args[1] if ast.unparse(node.func) in LABEL_CALLS and len(node.args) > 1 else keyword
        if role is None:
            continue
        words = frozenset(part.value for part in ast.walk(role) if isinstance(part, ast.Constant) and isinstance(part.value, str))
        found.append(Site(Path(path).name, owner_of(node, parents), ast.unparse(node.args[0]) if node.args else "", ast.unparse(role), words, literal_role(role)))
    return found


@functools.lru_cache(maxsize=1)
def all_role_sites():
    return tuple(site for path in sorted(QT_DIR.glob("*.py")) for site in role_sites(path))


def muted_strings(path):
    """화면 소스에서 글자 `muted` 가 나오는 모든 곳 → [(파일, 함수, 어디, 둘러싼 식)]. 어디 = `dict`(톤 → 색 같은 짝 표의 열쇠) · `badge`(배지 종류) · `other`(그 밖 — 라벨의 역할 자리·변수·키워드·기본값·묶음 속 등)."""
    tree, parents = parse(path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "muted":
            parent = parents[node]
            if isinstance(parent, ast.Dict):
                where = "dict"
            elif isinstance(parent, ast.Call) and ast.unparse(parent.func) in BADGE_CALLS and parent.args and parent.args[0] is node:
                where = "badge"
            else:
                where = "other"
            found.append((Path(path).name, owner_of(node, parents), where, ast.unparse(parent)[:80]))
    return found


def rule_colors(qss, role):
    """스타일시트에서 `QLabel[role="…"]` 규칙(앞에 다른 선택자가 붙은 `QFrame QLabel[role="…"]` 도 센다)이 주는 글자 색들 — 나온 순서대로."""
    return re.findall(r'QLabel\[role="' + re.escape(role) + r'"\] \{[^}]*?color: (#[0-9A-Fa-f]{6})', qss)


def rule_color(qss, role):
    """그 역할의 글자 색 — 같은 선택자가 여러 번 나오면 **마지막** 규칙이 이긴다(QSS 도 CSS 처럼 뒤 규칙이 이긴다)."""
    found = rule_colors(qss, role)
    if not found:
        raise AssertionError(f"역할 {role} 의 글자 색 줄이 없다")
    return found[-1]


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

    def test_the_stylesheet_source_has_one_rule_for_each_input_selector_and_none_added_later(self):
        """입력 칸 규칙을 뒤에 덧붙이면(QSS 는 뒤 규칙이 이긴다) 첫 규칙만 읽는 시험은 못 잡는 채로 테두리가 바뀐다 — 입력 칸 선택자 목록을 순서까지 못박아, 규칙 하나가 더해져도 빨갛다.
        (새 규칙이 꼭 필요하면 이 목록과 '승인한 목업의 색' 근거를 함께 고친다.)"""
        source = (QT_DIR / "theme.py").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"^(QLineEdit[^{\n]*|QPlainTextEdit[^{\n]*) \{\{", source, re.M), INPUT_SELECTORS)

    def test_the_label_role_rules_come_only_from_the_generated_loop(self):
        """`sub`·`muted` 의 글자 색 규칙은 역할 표(`ROLE_TEXT`)에서 만드는 반복문 한 곳에서만 나온다 — 손으로 덧붙인 `QLabel[role="sub"] { … }` 줄이 있으면(뒤 규칙이 이긴다) 빨갛다."""
        source = (QT_DIR / "theme.py").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'QLabel\[role="([a-z0-9_]+)"\]', source), ["ok"], "손으로 쓴 역할 규칙은 `ok` 하나뿐이다(나머지는 반복문이 만든다)")
        self.assertIn("""f'QLabel[role="{role}"] {{""", source)

    def test_only_the_theme_sets_a_stylesheet_and_only_once(self):
        """위젯마다 색을 따로 박는 길(`setStyleSheet`)이 화면 소스 어디에도 없다 — 박으면 역할 규칙과 다른 색이 보인다."""
        calls = {}
        for path in sorted(QT_DIR.glob("*.py")):
            tree, _ = parse(path)
            count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setStyleSheet")
            if count:
                calls[path.name] = count
        self.assertEqual(calls, {"theme.py": 1})

    def test_the_rule_reader_takes_the_last_rule_and_counts_every_rule_even_a_nested_one(self):
        qss = 'QLabel[role="sub"] { color: #111111; }\nQFrame QLabel[role="sub"] { font-size: 1px; color: #222222; }\nQLabel[role="muted"] { color: #333333; }\n'
        self.assertEqual(rule_colors(qss, "sub"), ["#111111", "#222222"])
        self.assertEqual(rule_color(qss, "sub"), "#222222", "뒤에 나온 규칙이 이긴다")
        self.assertEqual((rule_colors(qss, "muted"), rule_color(qss, "muted")), (["#333333"], "#333333"))
        with self.assertRaises(AssertionError):
            rule_color(qss, "small")


# ---- 2) 소스 -------------------------------------------------------------------------------------------------------------------------------
class SourceSitesTest(unittest.TestCase):
    def test_the_twelve_places_use_exactly_the_pinned_role_expressions(self):
        """낱말만이 아니라 역할 **식** 을 못박는다 — 조건이 뒤집히거나(`'sub' if missing else 'body'` ↔ 반대) 갈래 하나가 바뀌어도(요약이 늘 `sub`) 빨갛다."""
        sites = all_role_sites()
        counts = collections.Counter(site.key for site in sites)
        for table in (SENTENCE_SITES, VALUE_SITES):
            for key, (role, _reason) in table.items():
                self.assertEqual(counts[key], 1, f"{key}: 이 라벨 호출이 정확히 하나여야 한다(코드가 옮겨졌거나 같은 글 식이 둘이다)")
                self.assertEqual([site.role for site in sites if site.key == key], [role], key)

    def test_the_muted_role_is_used_for_exactly_the_five_empty_value_places(self):
        muted = {site.key for site in all_role_sites() if "muted" in site.words}
        self.assertEqual(sorted(muted - set(VALUE_SITES)), [], "빈 값이 아닌 곳에 흐린 글(muted)이 새로 쓰였다 — 문장이면 `sub` 로, 빈 값이면 이 표에 이유와 함께 더한다")
        self.assertEqual(sorted(set(VALUE_SITES) - muted), [], "표의 빈 값 자리가 더는 muted 가 아니다 — 승인 범위(문장만) 밖을 바꿨거나 코드가 옮겨졌다")

    def test_the_seven_sentence_places_use_the_secondary_role(self):
        sub = {site.key for site in all_role_sites() if "sub" in site.words}
        self.assertEqual(sorted(set(SENTENCE_SITES) - sub), [], "안내·결과 문장이 보조 글(sub)이 아니다")
        for site in all_role_sites():
            if site.key in SENTENCE_SITES:
                self.assertNotIn("muted", site.words, site.key)

    def test_the_word_muted_appears_in_the_screen_sources_only_as_the_five_value_roles_badge_kinds_and_tone_tables(self):
        """`muted` 라는 글자가 라벨의 역할로 새로 나오는 모든 길을 막는다 — 변수(`_r = 'muted'`)·`role=` 키워드·함수 기본값·튜플 속 글자까지. 배지 종류(`UI.Badge("muted", …)`)와 톤 → 색 표의 열쇠는 다른 부품이라 센다."""
        others = sorted((site[0], site[1]) for path in sorted(QT_DIR.glob("*.py")) for site in muted_strings(path) if site[2] == "other")
        self.assertEqual(others, sorted((key[0], key[1]) for key in VALUE_SITES), "빈 값 다섯 밖에서 `muted` 글자가 역할 자리에 쓰였다")

    def test_a_role_is_passed_as_a_string_literal_except_at_the_four_pass_through_places(self):
        """역할이 변수로 넘어가면(`role = 'muted'` 한 줄로) 위 표가 볼 수 없다 — 변수로 넘기는 곳은 역할을 받아 라벨을 만드는 부품 넷뿐이고 그 역할 식은 `role` 이다."""
        found = [site for site in all_role_sites() if not site.literal]
        self.assertEqual(sorted(site.key for site in found), sorted(PASS_THROUGH), "역할을 변수로 넘기는 새 호출이 생겼다 — 글자 리터럴로 쓰거나, 정말 받아 넘기는 부품이면 허용 목록에 이유와 함께 더한다")
        self.assertEqual({site.role for site in found}, {"role"})

    def test_every_listed_place_has_a_real_reason(self):
        for table in (VALUE_SITES, SENTENCE_SITES):
            for place, (role, reason) in table.items():
                self.assertGreaterEqual(len(reason), 12, place)
                self.assertTrue(role.startswith("'"), place)
        self.assertFalse(set(VALUE_SITES) & set(SENTENCE_SITES))
        self.assertEqual((len(VALUE_SITES), len(SENTENCE_SITES)), (5, 7))

    def test_the_scanners_see_a_synthetic_muted_sentence_a_variable_role_and_a_role_keyword_and_ignore_badges(self):
        """이 시험들의 눈이 정말 muted 라벨·변수 역할·`role=` 키워드를 잡고 배지(`UI.Badge("muted", …)` — 다른 부품)·톤 표의 열쇠는 따로 세는지 합성 소스로 확인한다."""
        source = ("def f(UI, row, page_head):\n    UI.label(row['x'], 'muted', wrap=True)\n    UI.label(row['y'], 'small' if row['z'] else 'muted')\n    UI.Badge('muted', 'a')\n"
                  "    ClampedLabel(row['w'], role='muted')\n    UI.label(row['v'], 'sub')\n    r = 'muted'\n    UI.label(row['u'], r)\n    page_head('t', 's', role='muted')\n"
                  "\n\ndef g(text, role='muted'):\n    return {'muted': 1}\n")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.py"
            path.write_text(source, encoding="utf-8")
            sites = role_sites(path)
            census = muted_strings(path)
        self.assertEqual(sorted((site.text, "muted" in site.words, site.literal) for site in sites),
                         sorted([("row['x']", True, True), ("row['y']", True, True), ("row['w']", True, True), ("row['v']", False, True), ("row['u']", False, False), ("'t'", True, True)]))
        self.assertEqual(sorted(found[2] for found in census), ["badge", "dict"] + ["other"] * 6, "변수·키워드·기본값·조건식·라벨 인자 둘이 모두 `other` 다")


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

    def shown_color(self, label):
        """위젯이 **실제로 쓰는** 글자 색 — 앱 스타일시트가 입혀진 뒤(`ensurePolished`)의 팔레트 값이다(스타일시트 글만 읽으면 위젯에 따로 박은 색이나 뒤에 덧붙은 규칙을 놓친다)."""
        label.ensurePolished()
        return label.palette().color(QPalette.WindowText).name().upper()

    def assert_reads_as_a_sentence(self, label, what):
        role = label.property("role")
        self.assertEqual(role, "sub", f"{what}: 안내·결과 문장이 보조 글이 아니다({role})")
        self.assertEqual(rule_colors(self.qss, role), [self.colors["text_secondary"]], f"{what}: 스타일시트의 {role} 역할 규칙은 하나이고 보조 글 색이어야 한다")
        color = self.shown_color(label)
        self.assertEqual(color, self.colors["text_secondary"].upper(), f"{what}: 위젯이 실제로 쓰는 글자 색이 보조 글 색이 아니다")
        self.assertGreaterEqual(tokens.contrast(color, self.colors["surface"]), 4.5, what)

    def assert_keeps_the_hint_color(self, label, what):
        self.assertEqual(label.property("role"), "muted", what)
        self.assertEqual(rule_colors(self.qss, "muted"), [self.colors["text_muted"]], what)
        self.assertEqual(self.shown_color(label), self.colors["text_muted"].upper(), f"{what}: 빈 값의 실제 글자 색은 흐린 글 그대로다")

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
        self.assert_keeps_the_hint_color(row.value_label, "cand_factor_missing")
        self.assertEqual(rule_color(self.qss, "muted"), self.colors["text_muted"])

    def test_the_missing_value_cells_of_a_candidate_detail_keep_the_hint_color_and_real_values_do_not(self):
        """후보 상세의 값 칸(`조회하지 못했어요`·`데이터 부족`)은 흐린 글로 남긴 다섯 곳 중 문장에 가장 가까운 둘이다 — 지금은 승인 범위(문장) 밖이라 그대로임을 못박는다(D-487 남은 일)."""
        host = QWidget()
        self.addCleanup(host.deleteLater)
        layout = QVBoxLayout(host)
        candidate_screen._rows(layout, [{"label": "최근 관심도", "value": T["cand_trend_unavailable"], "missing": True}, {"label": "비교", "value": T["cand_trend_missing"], "missing": True},
                                        {"label": "변화", "value": "올라가는 중", "missing": False}])
        labels = label_texts(host)
        for key in ("cand_trend_unavailable", "cand_trend_missing"):
            self.assert_keeps_the_hint_color(labels[T[key]], key)
        self.assertEqual(labels["올라가는 중"].property("role"), "body_lg")
        self.assertNotEqual(self.shown_color(labels["올라가는 중"]), self.colors["text_muted"].upper(), "값이 있는 칸은 흐린 글이 아니다")

    def test_the_built_stylesheet_has_one_color_rule_for_each_of_the_two_roles(self):
        for role, key in (("sub", "text_secondary"), ("muted", "text_muted")):
            self.assertEqual(rule_colors(self.qss, role), [self.colors[key]], f"{role}: 규칙이 하나가 아니거나 색이 토큰과 다르다")
            self.assertEqual(rule_color(self.qss, role), self.colors[key])

    def test_the_built_stylesheet_has_one_rule_for_each_input_box_with_the_approved_border_color(self):
        for selector in ("QLineEdit", 'QPlainTextEdit\\[editor="true"\\]'):
            rules = re.findall(r"(?:^|\n)" + selector + r" \{([^}]*)\}", self.qss)
            self.assertEqual(len(rules), 1, f"{selector}: 규칙이 하나가 아니다")
            self.assertIn("border: 1px solid #B8C7DA", rules[0], selector)

    def test_the_input_boxes_are_really_drawn_with_the_approved_border_color(self):
        """스타일시트 글이 아니라 **그려진 그림**의 테두리 픽셀을 읽는다 — 뒤에 덧붙은 규칙·위젯에 따로 박은 색이 테두리를 바꿔도 잡는다(offscreen 에서 가장자리 가운데 점은 정확히 `#B8C7DA`)."""
        line = QLineEdit()
        line.resize(240, 40)
        editor = QPlainTextEdit()
        editor.setProperty("editor", "true")
        editor.resize(240, 90)
        for widget in (line, editor):
            self.addCleanup(widget.deleteLater)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.ensurePolished()
        for widget, points in ((line, ((0, 20), (120, 0), (120, 39), (239, 20))), (editor, ((0, 45), (120, 0), (120, 89), (239, 45)))):
            image = widget.grab().toImage()
            for x, y in points:
                self.assertEqual(image.pixelColor(x, y).name().upper(), "#B8C7DA", (type(widget).__name__, x, y))


if __name__ == "__main__":
    unittest.main()
