"""안내·결과 문장의 글 색 시험 — 확인 015 승인 10번(데스크톱 F029, 결정 D-487): 흰 바탕의 흐린 안내·결과 문장(`Text/Muted`, 대비 약 3.2)을 기존의 보조 글 색(`Text/Secondary`, 약 5.4)으로 읽히게 한다.
승인 범위는 **문장 색뿐**이다 — 입력 칸 테두리에 새 진한 색을 더하지 않고(승인한 목업의 색을 바꾸지 않는다) 새 색 값도 만들지 않는다. 흐린 글은 '힌트·빈 값'(값 칸의 없음 표시·점선 하나)에만 남는다.

지키는 것:
  1) (PySide6 없이 돈다 — CI 와 같은 조건) 값: 승인 때의 숫자(3.2 와 5.4 — 입력 칸 테두리 1.7)가 토큰의 실제 값을 WCAG 식으로 직접 계산한 값과 맞는다. 입력 칸 테두리 색 토큰과 그 스타일시트 줄은 그대로다.
     `sub` 와 `muted` 는 글자 크기·굵기·줄 높이가 같고 글자 색 키만 다르다(역할을 바꿔도 화면 배치가 달라지지 않는다).
  2) (PySide6 없이 돈다) 소스: 화면 소스(`ui/qt/*.py`)의 라벨 호출 **열두 곳**(문장 일곱·빈 값 다섯)의 글자 역할 **식**(`ast.unparse` 글)을 표로 못박는다 — 낱말이 더해지거나 빠지거나 조건이 뒤집히면(`'sub' if missing else 'body'` ↔ 반대) 빨갛다.
     `muted` 라는 글자가 화면 소스 어디에 새로 나와도(변수·키워드·기본값·묶음 속 포함) 빈 값 다섯 밖이면 빨갛고, 역할을 글자가 아닌 변수로 넘기는 새 라벨 호출도 허용 목록(역할을 받아 라벨을 만드는 부품 넷) 밖이면 빨갛다.
     스타일시트 소스(`theme.py`)는 입력 칸 선택자마다 규칙 하나이고(덧붙은 규칙이 뒤에서 테두리를 덮지 못한다) `sub`·`muted` 역할 규칙이 손으로 덧붙지 않았으며, 화면 소스에서 `setStyleSheet` 는 `theme.py` 가 앱 전체에만 건다.
     (3차 지시) 빈 값 다섯의 값이 있을 때 글꼴 역할은 보통 글 색을 쓰는 어느 역할이든 된다(글꼴 손질을 막지 않는다). 손으로 쓴 역할 규칙은 `[role="낱말"]` 모양이고 낱말이 `sub`·`muted` 가 아닐 때만 허락한다(관계없는 역할의 손 규칙은 막지 않는다).
     `setStyleSheet` 는 `theme.py` 가 앱(`app`)에만 건다(같은 스타일시트를 한 번 더 거는 것은 막지 않는다). PySide6 없이 **만들어진 스타일시트**를 읽어(`qss_without_qt`) 역할 규칙 색·흐린 글 색을 쓰는 규칙·입력 칸 규칙을 확인하고,
     소스에서는 `QLineEdit`·`QPlainTextEdit`·`[role` 을 줄머리가 아니라 어디서든 센다. 화면 소스에 `setPalette`·`setProperty("styleSheet", …)`·글 속 HTML `color:`·`WindowText` 가 아닌 `setPen` 팔레트 색이 없고, 역할 표에 흐린 글 색을 가리키는
     별칭이 없으며, `muted` 글자가 짝 표의 **값**으로 숨는 길도 막는다(`BypassGuardsTest`).
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

from chanceblog_desktop.ui.core import gauges, tokens  # noqa: E402
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

# 빈 값 — 값 칸에 '없음' 을 알리는 짧은 글이나 점선 하나. 흐린 글(Muted)의 본래 쓰임(`Text/Muted`: 힌트·빈 값)이라 그대로 둔다. (파일, 함수, 글 식) → (없음 조건, 이유).
# 조건이 있으면 역할 식은 `'muted' if <조건> else '<글꼴 역할>'` 이다 — 조건은 못박고(뒤집히면 빨강) 값이 있을 때의 글꼴 역할은 보통 글 색(`VALUE_PRESENT_COLORS`)을 쓰는 어느 역할이든 된다. 글꼴(크기·굵기) 손질까지 막지 않는다
# (3차 지시, 검증자 2 의 FP8). 조건이 `None` 이면 역할 식은 정확히 `'muted'` 다.
VALUE_PRESENT_COLORS = ("text_primary", "text_strong")
VALUE_SITES = {
    ("candidate_parts.py", "FactorRow.__init__", "vm['text']"): ("vm['missing']", "점수 구성 한 줄의 값 자리 — 평가하지 못한 항목의 `평가 전`"),
    ("candidate_screen.py", "_rows", "row['value']"): ("row['missing']", "후보 상세의 이름·값 줄 — 값이 없을 때의 없음 표시(`데이터 부족`·`조회하지 못했어요` 포함)"),
    ("draft_screen.py", "_chips_card", "'—'"): (None, "칩이 하나도 없는 줄의 점선 하나"),
    ("screens.py", "drawer_content", "field['value']"): ("field['missing']", "홈 서랍의 이름·값 줄 — 값이 없을 때의 `데이터 없음`"),
    ("seed_screen.py", "_info_card", "row['value']"): ("row['missing']", "Seed 정보의 이름·값 줄 — 값이 없을 때의 없음 표시"),
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
    """화면 소스에서 글자 `muted` 가 나오는 모든 곳 → [(파일, 함수, 어디, 둘러싼 식)]. 어디 = `dict`(톤 → 색 같은 짝 표의 **열쇠** — 값 자리의 글자는 `other`) · `badge`(배지 종류) · `other`(그 밖 — 라벨의 역할 자리·변수·키워드·기본값·묶음 속·짝 표의 값 등)."""
    tree, parents = parse(path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "muted":
            parent = parents[node]
            if isinstance(parent, ast.Dict) and any(node is key for key in parent.keys):
                where = "dict"                                                  # 톤 → 색 같은 짝 표의 열쇠. 값 자리의 글자(`{'sub': 'muted'}` 같은 별칭 표·`**{'role': 'muted'}`)는 `other` 다(3차 지시 — 검증자 2 의 N01·N18·N22·N27)
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


def value_role_ok(role, condition):
    """빈 값 자리의 역할 식 — 조건이 없으면(`condition is None`) 정확히 `'muted'`, 있으면 `'muted' if <조건> else '<글꼴 역할>'` 모양이다. 조건은 못박고(뒤집히면 빨강) 값이 있을 때의 글꼴 역할은 보통 글 색
    (`VALUE_PRESENT_COLORS`)을 쓰는 어느 역할이든 된다 — 글자 크기·굵기를 바꾸는 글꼴 손질(`body_lg` → `body`)까지 막지 않는다(3차 지시, 검증자 2 의 FP8)."""
    if condition is None:
        return role == "'muted'"
    found = re.fullmatch(r"'muted' if " + re.escape(condition) + r" else '([a-z0-9_]+)'", role)
    return bool(found) and tokens.ROLE_TEXT.get(found.group(1)) in VALUE_PRESENT_COLORS


def literal_role_names(node):
    """글자 리터럴 역할 식(리터럴이거나 두 갈래가 모두 리터럴인 조건식)의 갈래 글자들 — 조건 식 속 글자(`vm['missing']` 의 `missing`)는 세지 않는다."""
    if isinstance(node, ast.Constant):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return literal_role_names(node.body) | literal_role_names(node.orelse)
    return set()


def role_selectors(source):
    """스타일시트 소스에서 `[role` 이 나오는 **모든 자리** → [(그 자리부터 40자, 따옴표 친 낱말 또는 None)] — 줄머리가 아니라 어디서든 센다(앞에 다른 선택자가 붙은 `QWidget[role=…]`·따옴표 없는 `[role=sub]`·값 없는 `[role]`·묶음 선택자도)."""
    found = []
    for match in re.finditer(r"\[role", source):
        tail = source[match.start():match.start() + 40]
        quoted = re.match(r'\[role="([A-Za-z0-9_{}]+)"\]', tail)
        found.append((tail, quoted.group(1) if quoted else None))
    return found


@functools.lru_cache(maxsize=1)
def qss_without_qt():
    """`theme.build_qss` 가 만드는 앱 전체 스타일시트 — **PySide6 없이**. `theme.py` 는 PySide6 를 가져와 불러올 수 없으므로 소스(`ast`)에서 스타일시트를 만드는 함수들만 뽑아 토큰(`K`)과 `gauges` 로 돌린다(색은 모두 `K.palette()` 에서 온다).
    소스 글을 정규식으로 읽는 시험은 선택자를 앞에 붙이거나 묶는 우회를 놓치지만 **만들어진 글**은 어떻게 만들었든 그대로 보인다. 뽑는 것은 `theme.py` 맨 위 단계의 함수 중 PySide6 에서 가져온 이름을 쓰지 않는 것 전부라서(스타일시트를 만드는 도우미가 새로 생겨도
    따라간다), 스타일시트를 만드는 함수가 Qt 이름을 쓰기 시작하면 그 함수가 빠져 `build_qss` 가 못 돌고 이 시험이 알려 준다."""
    tree = ast.parse((QT_DIR / "theme.py").read_text(encoding="utf-8"))
    qt_names = {alias.asname or alias.name for node in tree.body if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PySide6") for alias in node.names}
    plain = [node for node in tree.body if isinstance(node, ast.FunctionDef) and not ({part.id for part in ast.walk(node) if isinstance(part, ast.Name)} & qt_names)]
    if "build_qss" not in [node.name for node in plain]:
        raise AssertionError("스타일시트를 만드는 `build_qss` 가 Qt 이름을 쓰기 시작했거나 없어졌다 — 이 시험의 `qss_without_qt` 를 고쳐야 한다")
    namespace = {"K": tokens, "gauges": gauges}
    try:
        exec(compile(ast.fix_missing_locations(ast.Module(body=plain, type_ignores=[])), "theme_without_qt", "exec"), namespace)
        return namespace["build_qss"](tokens.palette())
    except NameError as error:
        raise AssertionError("스타일시트를 만드는 함수가 Qt 이름이나 이 시험이 모르는 이름을 쓰기 시작했다 — 이 시험의 `qss_without_qt` 를 고쳐야 한다: " + str(error)) from None


def qss_rules(qss):
    """만들어진 스타일시트 → [(선택자, {속성: 값})] — 중첩 없는 `선택자 { 속성: 값; … }` 글만 읽는다."""
    rules = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", qss):
        declarations = {}
        for part in body.split(";"):
            name, _, value = part.partition(":")
            if name.strip():
                declarations[name.strip()] = value.strip()
        rules.append((" ".join(selector.split()), declarations))
    return rules


def code_strings(tree):
    """코드 속 글 상수(모듈·클래스·함수 설명 글은 뺀다) — f-string 의 글 조각도 들어 있다."""
    docstrings = set()
    for node in [tree] + [item for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]:
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            docstrings.add(id(body[0].value))
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]


def color_route_findings(path):
    """화면 소스 한 파일에서 글자 색을 스타일시트 밖으로 정하는 길 → [글]: `setStyleSheet`·`setPalette` 속성 참조(별칭으로 받아 쓰는 것도)·글 상수 `styleSheet`(`setProperty("styleSheet", …)` 길)·
    글 상수 속 HTML·CSS 색(`color:`·`color=`)·**라벨 클래스**(이름이 `Label` 로 끝나는 것)가 그릴 때 `setPen` 에 쓰는 팔레트 색이 `QPalette.WindowText` 가 아닌 것(단추 같은 다른 부품의 그리기는 건드리지 않는다)."""
    tree, parents = parse(path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("setStyleSheet", "setPalette"):
            found.append(f"{node.attr}@{node.lineno}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setPen" and owner_of(node, parents).split(".")[0].endswith("Label"):
            for part in ast.walk(node):
                if isinstance(part, ast.Attribute) and ast.unparse(part.value) == "QPalette" and part.attr != "WindowText":
                    found.append(f"setPen:{part.attr}@{node.lineno}")
    for text in code_strings(tree):
        if text.lower() in ("stylesheet", "setstylesheet", "setpalette"):
            found.append(f"string:{text}")
        if re.search(r"color\s*[:=]", text, re.I):
            found.append(f"color-text:{text[:30]!r}")
    return found


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

    def test_no_hand_written_rule_can_reach_the_sub_or_muted_roles(self):
        """`sub`·`muted` 의 글자 색 규칙은 역할 표(`ROLE_TEXT`)에서 만드는 반복문 한 곳에서만 나온다. 스타일시트 소스에서 `[role` 이 나오는 **모든 자리**(줄머리가 아니라 어디서든 — `QWidget[role="sub"]`·따옴표 없는 `[role=sub]`·값 없는 `[role]`·
        다른 연산자를 쓴 `[role^=…]`)를 보고, 손으로 쓴 규칙은 `[role="낱말"]` 모양이고 낱말이 `sub`·`muted` 가 아닐 때만 허락한다 — 관계없는 역할의 손 규칙까지 막지 않는다(3차 지시 — 검증자 2 의 FP1, 우회 N02·N03)."""
        source = (QT_DIR / "theme.py").read_text(encoding="utf-8")
        found = role_selectors(source)
        self.assertEqual([word for _tail, word in found].count("{role}"), 1, "역할 규칙을 만드는 반복문은 한 곳이다")
        self.assertIn("""f'QLabel[role="{role}"] {{""", source)
        for tail, word in found:
            self.assertIsNotNone(word, f"역할 선택자가 `[role='낱말']`(큰따옴표) 모양이 아니다 — 따옴표 없음·연산자·값 없음은 뒤에서 sub·muted 를 덮을 수 있다: {tail!r}")
            self.assertNotIn(word, ("sub", "muted"), "손으로 쓴 규칙이 sub·muted 역할의 규칙을 건드린다")
        self.assertIn("ok", [word for _tail, word in found], "손으로 쓴 `ok` 규칙이 이 눈에 보여야 한다(눈이 먼 것이 아닌지)")

    def test_no_screen_source_but_the_theme_sets_a_stylesheet_and_the_theme_sets_it_on_the_app_only(self):
        """위젯마다 색을 따로 박는 길(`setStyleSheet`)이 화면 소스 어디에도 없다(속성 참조를 세므로 별칭으로 받아 쓰는 것도 잡는다) — 박으면 역할 규칙과 다른 색이 보인다. `theme.py` 는 앱 전체(`app`)에만 건다:
        같은 스타일시트를 한 번 더 거는 것까지는 막지 않는다(3차 지시 — 검증자 2 의 FP3)."""
        receivers = {}
        for path in sorted(QT_DIR.glob("*.py")):
            tree, _ = parse(path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "setStyleSheet":
                    receivers.setdefault(path.name, set()).add(ast.unparse(node.value))
        self.assertEqual(receivers, {"theme.py": {"app"}})

    def test_the_rule_reader_takes_the_last_rule_and_counts_every_rule_even_a_nested_one(self):
        qss = 'QLabel[role="sub"] { color: #111111; }\nQFrame QLabel[role="sub"] { font-size: 1px; color: #222222; }\nQLabel[role="muted"] { color: #333333; }\n'
        self.assertEqual(rule_colors(qss, "sub"), ["#111111", "#222222"])
        self.assertEqual(rule_color(qss, "sub"), "#222222", "뒤에 나온 규칙이 이긴다")
        self.assertEqual((rule_colors(qss, "muted"), rule_color(qss, "muted")), (["#333333"], "#333333"))
        with self.assertRaises(AssertionError):
            rule_color(qss, "small")


# ---- 1b) PySide6 없는 CI 에서도 문장 색을 몰래 바꾸는 길을 막는다(3차 지시 — 검증자 2 의 권고 1) ---------------------------------------------------------------
class BypassGuardsTest(unittest.TestCase):
    """2차 지시의 시험은 PySide6 가 없는 CI 에서 소스 글만 읽었다 — 위젯에 따로 박은 색·역할 표의 별칭·스타일시트에 덧붙인 규칙처럼 그 눈이 놓치는 길이 남았다. 여기서는 **만들어진 스타일시트**를
    PySide6 없이 만들어 읽고, 소스에서는 줄머리가 아니라 어디서든 센다. 별칭을 거치거나 `**{…}` 로 숨긴 호출처럼 정적으로 막기 어려운 것은 아래 '그려진 그림' 시험(PySide6 가 있을 때)이 맡는다."""

    def test_the_role_color_function_returns_the_documented_tokens_of_the_two_roles(self):
        """스타일시트의 역할 규칙은 `role_color` 로 만든다 — 표(`ROLE_TEXT`)가 맞아도 이 함수가 틀리면 만들어진 색이 틀린다(검증자 2 의 N25)."""
        colors = tokens.palette()
        self.assertEqual(tokens.role_color(colors, "sub"), colors["text_secondary"])
        self.assertEqual(tokens.role_color(colors, "muted"), colors["text_muted"])

    def test_the_muted_color_has_exactly_one_role_so_no_alias_can_hide_a_muted_sentence(self):
        """흐린 글 색을 가리키는 역할이 하나 더 생기면(`hint` → `text_muted`) 화면 소스에 `muted` 라는 글자가 없이도 흐린 문장을 쓸 수 있다(검증자 2 의 N28)."""
        self.assertEqual([role for role, key in tokens.ROLE_TEXT.items() if key == "text_muted"], ["muted"], "흐린 글 색을 가리키는 역할이 하나 더 생겼다")
        self.assertEqual(sorted(tokens.ROLE_STYLE), ["muted", "sub"], "크기·굵기를 빌려 쓰는 역할 표가 바뀌었다")

    def test_every_literal_role_a_screen_uses_has_a_definition(self):
        """화면이 글자 리터럴로 쓰는 역할은 모두 역할 표에 있다 — 표에 없는 역할은 색도 크기도 앱 기본값으로 그려진다."""
        used = set()
        for site in all_role_sites():
            if site.literal:
                used |= literal_role_names(ast.parse(site.role, mode="eval").body)
        self.assertEqual(sorted(used - set(tokens.ROLE_TEXT)), [], "역할 표에 없는 글자 역할을 쓴 곳이 있다")

    def test_the_built_stylesheet_has_one_color_rule_for_each_of_the_two_roles_even_without_qt(self):
        """PySide6 가 없어도 만들어진 스타일시트에서 `sub`·`muted` 역할 규칙이 하나씩이고 토큰의 색이다(역할 규칙을 만드는 반복문이 틀리면 — 검증자 2 의 N25 와 구현자의 R11)."""
        colors, qss = tokens.palette(), qss_without_qt()
        for role, key in (("sub", "text_secondary"), ("muted", "text_muted")):
            self.assertEqual(rule_colors(qss, role), [colors[key]], role)

    def test_the_muted_color_is_used_in_the_built_stylesheet_only_by_the_muted_role_and_the_invisible_trend_rule(self):
        """만들어진 스타일시트에서 흐린 글 색을 쓰는 규칙은 `muted` 역할과 보이는 글이 없는 `QLabel[trend="none"]` 뿐이다 — 문장이 아닌 곳(배지 등)에 흐린 글 색이 새로 쓰이는 길을 막는다(검증자 2 의 N11).
        새 쓰임이 정말 필요하면 이 시험의 허용 목록에 이유와 함께 더한다."""
        muted = tokens.palette()["text_muted"].upper()
        users = sorted({selector for selector, declarations in qss_rules(qss_without_qt()) if any(muted in value.upper() for value in declarations.values())})
        self.assertEqual(users, ['QLabel[role="muted"]', 'QLabel[trend="none"]'])

    def test_the_built_stylesheet_has_exactly_the_pinned_input_rules_with_the_approved_border_even_without_qt(self):
        """만들어진 스타일시트에서 입력 칸(한 줄·편집기)을 건드리는 선택자는 정해진 목록 그대로이고, 두 주 규칙의 테두리는 승인한 `1px solid #B8C7DA` 하나뿐이다(`border-color` 덧붙임도 없다)."""
        rules = qss_rules(qss_without_qt())
        self.assertEqual([selector for selector, _ in rules if "QLineEdit" in selector or "QPlainTextEdit" in selector], INPUT_SELECTORS)
        for selector in ("QLineEdit", 'QPlainTextEdit[editor="true"]'):
            (declarations,) = [declarations for name, declarations in rules if name == selector]
            self.assertEqual({name: value for name, value in declarations.items() if name.startswith("border") and name != "border-radius"}, {"border": "1px solid " + tokens.palette()["border_strong"]}, selector)

    def test_every_mention_of_an_input_box_class_in_the_stylesheet_source_is_one_of_the_pinned_rules(self):
        """소스에서 `QLineEdit`·`QPlainTextEdit` 가 나오는 **모든 자리**를 센다(줄머리가 아니라 어디서든 — `QWidget QLineEdit {…}`·`QPushButton, QLineEdit {…}` 도 센다, 검증자 2 의 N04·N06)."""
        source = (QT_DIR / "theme.py").read_text(encoding="utf-8")
        for word in ("QLineEdit", "QPlainTextEdit"):
            self.assertEqual(source.count(word), sum(selector.count(word) for selector in INPUT_SELECTORS), f"{word} 가 정해진 규칙 밖에도 나온다")

    def test_the_two_main_input_rules_have_no_border_declaration_but_the_approved_one(self):
        """두 주 규칙의 본문에는 `border` 선언이 하나뿐이다 — 같은 줄에 `border-color: …` 를 덧붙이면 앞의 `border: … border_strong` 글은 그대로여도 테두리 색이 바뀐다(검증자 2 의 N05)."""
        source = (QT_DIR / "theme.py").read_text(encoding="utf-8")
        for selector in ("QLineEdit", 'QPlainTextEdit[editor="true"]'):
            found = re.search(r"^" + re.escape(selector) + r" \{\{([^\n]*)\}\}$", source, re.M)
            self.assertIsNotNone(found, selector)
            names = [part.partition(":")[0].strip() for part in found.group(1).split(";") if part.strip()]
            self.assertEqual([name for name in names if name.startswith("border") and name != "border-radius"], ["border"], f"{selector}: 테두리 선언이 `border` 하나가 아니다")

    def test_no_screen_source_sets_a_color_through_the_property_the_palette_html_or_the_painter(self):
        """화면 소스(`theme.py` 밖)에는 글자 색을 스타일시트 밖으로 정하는 길이 없다: `setStyleSheet`·`setPalette`(별칭으로 받아 쓰는 것도)·`setProperty("styleSheet", …)`·글 속 HTML `color:`·
        라벨이 그릴 때 쓰는 `setPen` 의 팔레트 색이 `WindowText` 가 아닌 것(검증자 2 의 N07·N09·N10). 별칭·`**{…}` 로 숨긴 것은 정적으로 막기 어려워 그려진 그림 시험의 몫이다."""
        findings = {path.name: color_route_findings(path) for path in sorted(QT_DIR.glob("*.py")) if path.name != "theme.py"}
        self.assertEqual({name: found for name, found in findings.items() if found}, {}, "글자 색을 스타일시트 밖으로 정하는 길이 새로 생겼다")

    def test_the_new_scanners_see_the_bypasses_and_leave_harmless_code_alone(self):
        """이 시험들의 눈이 정말 우회를 잡고 멀쩡한 코드는 건드리지 않는지 합성 소스로 확인한다(눈이 먼 시험은 늘 초록이다)."""
        bypass = ("class L:\n    def a(self):\n        self.setProperty('styleSheet', 'x')\n    def b(self):\n        ss = self.setStyleSheet\n    def c(self):\n        self.setPalette(p)\n"
                  "    def d(self):\n        self.setText(f'<b style=\"color:{c}\">x</b>')\n\n\nclass SummaryLabel:\n    def e(self, painter):\n        painter.setPen(self.palette().color(QPalette.Mid))\n")
        harmless = ("class M:\n    '''설명 글에 color: 와 setStyleSheet 가 있어도 된다.'''\n    def a(self, painter):\n        painter.setPen(self.palette().color(QPalette.WindowText))\n"
                    "        self.setProperty('role', 'body')\n        return 'colorful words and a stylesheet-free text'\n\n\nclass ShinyButton:\n    def paintEvent(self, painter):\n        painter.setPen(self.palette().color(QPalette.ButtonText))\n")
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "bypass.py").write_text(bypass, encoding="utf-8")
            (Path(folder) / "harmless.py").write_text(harmless, encoding="utf-8")
            found, quiet = color_route_findings(Path(folder) / "bypass.py"), color_route_findings(Path(folder) / "harmless.py")
        self.assertEqual(sorted(item.split("@")[0].split(":")[0] for item in found), ["color-text", "setPalette", "setPen", "setStyleSheet", "string"])
        self.assertEqual(quiet, [])
        selectors = ('QLabel[role="{role}"] {{ }}\nQWidget[role="sub"] {{ }}\nQLabel[role=sub] {{ }}\nQLabel[role] {{ }}\nQLabel[role^="sub"] {{ }}\nQLabel[role="note"] {{ }}\n')
        self.assertEqual([word for _tail, word in role_selectors(selectors)], ["{role}", "sub", None, None, None, "note"])
        self.assertEqual(qss_rules("A, B { color: #111; margin: 1px }\nC { x: y(1, 2) }"), [("A, B", {"color": "#111", "margin": "1px"}), ("C", {"x": "y(1, 2)"})])
        self.assertTrue(value_role_ok("'muted' if row['missing'] else 'body'", "row['missing']"), "글꼴 손질은 허락한다(FP8)")
        self.assertTrue(value_role_ok("'muted'", None))
        for role in ("'muted' if not row['missing'] else 'body'", "'sub' if row['missing'] else 'body'", "'muted' if row['missing'] else 'sub'", "'muted' if row['missing'] else 'caption'", "'muted' if row['missing'] else 'muted'", "'body'"):
            self.assertFalse(value_role_ok(role, "row['missing']"), role)
        self.assertFalse(value_role_ok("'sub'", None))

    def test_the_sub_and_muted_rules_of_the_built_stylesheet_differ_only_in_the_color(self):
        """'배치가 안 움직인다'(UI_VISUAL_QA 14절)를 토큰이 아니라 **만들어진 규칙**에서 지킨다 — `tokens.type_style` 만 비교하면 스타일시트를 만드는 반복문이 sub 의 글자 크기·굵기를 슬쩍 바꿔도(굵기 +100·크기 +1px) 초록이었다
        (4차 지시 — 검증자 2 3차의 M13·M14). `sub` 규칙은 `muted` 규칙과 글자 색만 다르고 크기·굵기는 토큰의 `type_style` 그대로다."""
        rules = dict(qss_rules(qss_without_qt()))
        sub, muted = rules['QLabel[role="sub"]'], rules['QLabel[role="muted"]']
        self.assertEqual({name: value for name, value in sub.items() if name != "color"}, {name: value for name, value in muted.items() if name != "color"}, "sub 와 muted 의 규칙이 색 말고도 다르다 — 배치가 움직인다")
        style = tokens.type_style("sub")
        self.assertEqual((sub["font-size"], sub["font-weight"]), (f"{style.size}px", str(style.weight)), "만들어진 sub 규칙의 글자 크기·굵기가 토큰과 다르다")

    def test_the_app_applies_the_built_stylesheet_unchanged(self):
        """`qss_without_qt` 는 `build_qss(tokens.palette())` 만 읽는다. 앱에 거는 단계(`theme.apply`)가 걸기 직전에 글을 바꾸면(`replace` 로 색을 갈아 끼움) PySide6 없는 CI 는 몰랐다(4차 지시 — 검증자 2 3차의 M16;
        Qt 가 있으면 팔레트 시험이 잡는다). `apply` 가 거는 글은 `build_qss(colors())` 이고, 같은 스타일시트를 한 번 더 거는 것(`app.styleSheet()` — FP3)은 막지 않는다.
        구조가 바뀌어(지역 변수·덧붙이는 규칙) 빨개지면 바뀐 식이 색을 몰래 바꾸지 않는지 보고 이 시험의 식을 고친다."""
        tree, _parents = parse(QT_DIR / "theme.py")
        apply = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "apply")
        applied = [ast.unparse(call.args[0]) for call in ast.walk(apply) if isinstance(call, ast.Call) and ast.unparse(call.func) == "app.setStyleSheet" and call.args]
        self.assertIn("build_qss(colors())", applied, "`apply` 가 앱에 거는 글이 `build_qss(colors())` 가 아니다 — 걸기 직전에 색이 바뀌지 않는지 보고 이 시험의 식을 고친다")
        self.assertEqual(sorted(set(applied) - {"build_qss(colors())", "app.styleSheet()"}), [], "`apply` 가 만든 스타일시트를 바꿔서 건다(걸기 직전에 색이 바뀔 수 있다)")

    def test_the_color_dictionary_the_stylesheet_is_built_from_is_the_token_palette(self):
        """`apply` 는 `colors()` 로 스타일시트를 만든다. `colors()` 가 토큰 팔레트가 아닌 사전을 주면(보조 글 자리에 흐린 글 색 — 검증자 2 3차의 M17) PySide6 없는 CI 는 몰랐다 — 반환식을 `K.palette(theme_name())` 로 못박는다.
        구조가 바뀌어 빨개지면 바뀐 식이 색을 몰래 바꾸지 않는지 보고 이 시험의 식을 고친다."""
        tree, _parents = parse(QT_DIR / "theme.py")
        colors = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "colors")
        self.assertEqual([ast.unparse(node.value) for node in ast.walk(colors) if isinstance(node, ast.Return)], ["K.palette(theme_name())"], "`colors()` 가 토큰 팔레트 그대로가 아니다 — 색이 바뀌지 않는지 보고 이 시험의 식을 고친다")


# ---- 2) 소스 -------------------------------------------------------------------------------------------------------------------------------
class SourceSitesTest(unittest.TestCase):
    def test_the_twelve_places_use_exactly_the_pinned_role_expressions(self):
        """낱말만이 아니라 역할 **식** 을 못박는다 — 조건이 뒤집히거나(`'sub' if missing else 'body'` ↔ 반대) 갈래 하나가 바뀌어도(요약이 늘 `sub`) 빨갛다."""
        sites = all_role_sites()
        counts = collections.Counter(site.key for site in sites)
        for table in (SENTENCE_SITES, VALUE_SITES):
            for key in table:
                self.assertEqual(counts[key], 1, f"{key}: 이 라벨 호출이 정확히 하나여야 한다(코드가 옮겨졌거나 같은 글 식이 둘이다)")
        for key, (role, _reason) in SENTENCE_SITES.items():
            self.assertEqual([site.role for site in sites if site.key == key], [role], key)
        for key, (condition, _reason) in VALUE_SITES.items():
            (role,) = [site.role for site in sites if site.key == key]
            self.assertTrue(value_role_ok(role, condition), f"{key}: 빈 값 자리의 역할 식 `{role}` 이 `'muted' if {condition} else <보통 글 색 역할>` 이 아니다")

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
            for place, (_role, reason) in table.items():
                self.assertGreaterEqual(len(reason), 12, place)
        for place, (role, _reason) in SENTENCE_SITES.items():
            self.assertTrue(role.startswith("'"), place)
        for place, (condition, _reason) in VALUE_SITES.items():
            self.assertTrue(condition is None or condition.endswith("['missing']"), place)
        self.assertFalse(set(VALUE_SITES) & set(SENTENCE_SITES))
        self.assertEqual((len(VALUE_SITES), len(SENTENCE_SITES)), (5, 7))

    def test_the_scanners_see_a_synthetic_muted_sentence_a_variable_role_and_a_role_keyword_and_ignore_badges(self):
        """이 시험들의 눈이 정말 muted 라벨·변수 역할·`role=` 키워드를 잡고 배지(`UI.Badge("muted", …)` — 다른 부품)·톤 표의 열쇠는 따로 세는지 합성 소스로 확인한다."""
        source = ("def f(UI, row, page_head):\n    UI.label(row['x'], 'muted', wrap=True)\n    UI.label(row['y'], 'small' if row['z'] else 'muted')\n    UI.Badge('muted', 'a')\n"
                  "    ClampedLabel(row['w'], role='muted')\n    UI.label(row['v'], 'sub')\n    r = 'muted'\n    UI.label(row['u'], r)\n    page_head('t', 's', role='muted')\n"
                  "    x = {'sub': 'muted'}.get(r, r)\n    UI.label(row['t'], **{'role': 'muted'})\n"
                  "\n\ndef g(text, role='muted'):\n    return {'muted': 1}\n")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.py"
            path.write_text(source, encoding="utf-8")
            sites = role_sites(path)
            census = muted_strings(path)
        self.assertEqual(sorted((site.text, "muted" in site.words, site.literal) for site in sites),
                         sorted([("row['x']", True, True), ("row['y']", True, True), ("row['w']", True, True), ("row['v']", False, True), ("row['u']", False, False), ("'t'", True, True)]))
        self.assertEqual(sorted(found[2] for found in census), ["badge", "dict"] + ["other"] * 8, "변수·키워드·기본값·조건식·라벨 인자 둘·짝 표의 값(`{'sub': 'muted'}`·`**{'role': 'muted'}`)이 모두 `other` 다 — 짝 표의 열쇠만 `dict` 다")


# ---- 2b) AP13 기록(UI_DESIGN_SPEC 13절)이 코드 사실과 맞는다(3차 지시 — 검증자 2 의 권고 3·정보) ------------------------------------------------------------
class DrawerRecordDocTest(unittest.TestCase):
    """AP13 은 코드로 하지 않고 UI_DESIGN_SPEC 13절에 근거와 설계만 남겼다. 그 기록이 말하는 사실을 코드에 묶어 둔다: 13절 맨 위의 비개발자용 두 문장 요약, 그리고 '잠복 결함' — 코드에 아직 있다
    (`close_drawer_silently` 가 `_drawer_return` 을 비우지 않는다). **홈 서랍에서는** 사용자가 그 길에 닿지 못한다(서랍 막이가 창 전체를 덮고 Tab 이 서랍 안에 갇히며 앱의 단축키는 Esc 와 Ctrl+S 뿐이고 서랍 안 단추는 `go()` 를 부르지 않는다).
    **후보 서랍에서는 이미 닿는다**(창 논리 폭 1366 미만에서 서랍 아래 고정 줄의 `이 주제로 만들기` 가 서랍이 열린 채 `go("drafts")` 를 부른다) — 그래도 거의 터지지 않는 것은 서랍을 여는 네 길이 돌아갈 자리를 새로 쓰기 때문이다
    (4차 지시 — 검증자 2 3차의 권고 1). 누가 이 길을 열거나 막거나 결함을 고치면 이 시험이 빨개져 13절을 함께 고치게 한다."""

    def section(self):
        text = (ROOT / "docs" / "UI_DESIGN_SPEC.md").read_text(encoding="utf-8")
        return text[text.index("## 13. 홈 추천 줄 서랍의 막다른 길"):]

    def test_the_section_starts_with_a_two_sentence_summary_a_non_developer_can_read(self):
        summary = [part.strip() for part in self.section().split("\n\n") if part.strip()][1]                  # 0 은 제목
        self.assertTrue(summary.startswith("**쉬운 요약**:"), summary[:30])
        self.assertEqual(summary.count("습니다."), 2, "두 문장이다")
        self.assertNotIn("`", summary, "쉬운 요약에는 코드 이름이 없다")
        self.assertIn("고치지 않았", summary)

    def test_the_drawer_defect_is_recorded_as_latent_and_the_code_facts_behind_that_still_hold(self):
        section = self.section()
        self.assertIn("**잠복 결함**", section)
        self.assertNotIn("지금도 있는 오류", section, "사용자가 닿지 못하는 결함을 '지금도 있는 오류' 라고 적지 않는다")
        for word in ("서랍 막이", "Tab", "Esc 와 Ctrl+S", "`_drawer_return = None`"):
            self.assertIn(word, section, word)
        shell = (QT_DIR / "shell.py").read_text(encoding="utf-8")
        functions = {node.name: node for node in ast.walk(ast.parse(shell)) if isinstance(node, ast.FunctionDef)}

        def clears_the_return_target(name):
            return any(isinstance(node, ast.Assign) and ast.unparse(node.value) == "None" and any(ast.unparse(target) == "self._drawer_return" for target in node.targets) for node in ast.walk(functions[name]))

        self.assertTrue(clears_the_return_target("close_drawer"), "`close_drawer` 는 돌아갈 자리를 비운다")
        self.assertFalse(clears_the_return_target("close_drawer_silently"), "`close_drawer_silently` 가 돌아갈 자리를 비우게 고쳐졌다 — 13절의 잠복 결함 문장을 고친다")
        self.assertEqual(shell.count("QShortcut("), 2, "앱의 단축키가 늘었다 — 홈 서랍이 열린 채 `go()` 로 가는 입력이 생겼는지 보고 13절을 고친다(후보 서랍은 이미 닿는다)")
        self.assertIn("QShortcut(QKeySequence(Qt.Key_Escape)", shell)
        self.assertIn('QShortcut(QKeySequence("Ctrl+S")', shell)
        self.assertIn("self.drawer = UI.Drawer(root)", shell, "서랍은 창의 바탕(사이드바까지 든 곳)에 얹힌다")
        self.assertIn("self.centralWidget().findChildren(QWidget)", shell[shell.index("def _trap_focus"):], "서랍·대화상자가 열리면 바깥 위젯에 Tab 이 가지 않는다")
        components = (QT_DIR / "components.py").read_text(encoding="utf-8")
        drawer = components[components.index("class Drawer("):components.index("class Dialog(")]
        self.assertIn("self.scrim.setGeometry(0, 0, parent.width(), parent.height())", drawer, "서랍 막이가 창 전체를 덮는다")
        self.assertIn("self.scrim.mousePressEvent = lambda _e: self.close_requested()", drawer, "막을 누르면 서랍이 닫힌다")
        screens = ast.parse((QT_DIR / "screens.py").read_text(encoding="utf-8"))
        home_drawer = next(node for node in ast.walk(screens) if isinstance(node, ast.FunctionDef) and node.name == "drawer_content")
        used = {node.attr for node in ast.walk(home_drawer) if isinstance(node, ast.Attribute) and ast.unparse(node.value) == "shell"}
        self.assertEqual(used, {"close_drawer", "draft", "notify_soon"}, "홈 서랍 안 단추가 부르는 셸 함수가 바뀌었다 — `go()` 로 가게 됐다면 13절의 '홈 서랍에서는 닿지 못한다' 를 고친다")

    def test_the_candidate_drawer_already_reaches_go_with_the_drawer_open_and_the_next_open_overwrites_the_return_target(self):
        """13절 (b) 의 둘째 사실 — 후보 서랍(창 논리 폭 1366 미만)에서는 서랍 아래 고정 줄의 `이 주제로 만들기` 가 서랍이 열린 채 `go("drafts")` 를 부른다(4차 지시 — 검증자 2 3차의 권고 1: 옛 문장은 '서랍이 열려 있는 동안 사용자는
        그 길에 닿지 못한다' 였고 후보 서랍에서는 거짓이었다). 그래도 거의 터지지 않는 것은 서랍을 여는 네 길(`open_drawer`·`seed_open`·`seed_open_new`·`cand_open`)이 모두 돌아갈 자리(`_drawer_return`)를 새로 쓰고, 옛 값을 꺼내 쓰는 곳이
        `close_drawer` 하나(`_sync_overlays` 는 열기 길이 방금 쓴 값을 그대로 둘 뿐)이며 거기서도 초점이 비었을 때만 `setFocus` 를 부르기 때문이다. 덮이지 않은 채 읽히는 길은 돌아온 후보 화면에서 Esc 로 닫을 때 하나(조용히 닫으면 고른 후보가 남는다).
        누가 이 길을 막거나 열면(고정 줄을 서랍에서 빼거나 새 길이 옛 값을 읽으면) 이 시험이 빨개져 13절을 함께 고치게 한다."""
        section = self.section()
        for word in ("**홈 서랍에서는 사용자가 그 길에 닿지 못한다**", "**후보 서랍에서는 이미 닿는다**", "1366", "서랍 아래 고정 줄의 `이 주제로 만들기`", '`go("drafts")`', "`open_drawer`·`seed_open`·`seed_open_new`·`cand_open`", "새로 쓰기 때문", "`close_drawer` 하나", "`_sync_overlays`", "돌아와 Esc 로 닫을 때"):
            self.assertIn(word, section, word)
        self.assertNotIn("지금 사용자는 그 길에 닿지 못한다", section, "후보 서랍에서는 이미 닿는다 — 모든 서랍이 닿지 못한다고 적지 않는다")
        shell = (QT_DIR / "shell.py").read_text(encoding="utf-8")
        functions = {node.name: node for node in ast.walk(ast.parse(shell)) if isinstance(node, ast.FunctionDef)}

        def calls(name):
            return [ast.unparse(node) for node in ast.walk(functions[name]) if isinstance(node, ast.Call)]

        def writes_the_return_target(name):
            return any(isinstance(node, ast.Assign) and ast.unparse(node.value) != "None" and any(ast.unparse(target) == "self._drawer_return" for target in node.targets) for node in ast.walk(functions[name]))

        self.assertIn("self.drawer.set_content(content, detail_footer(self, cand_view))", shell, "후보 서랍에 고정 줄(`이 주제로 만들기`)이 붙는다")
        screen = (QT_DIR / "candidate_screen.py").read_text(encoding="utf-8")
        self.assertIn("bar.triggered.connect(lambda _key: shell.cand_make_draft())", screen[screen.index("def detail_footer("):screen.index("def pane_placeholder(")], "고정 줄의 단추가 `cand_make_draft` 를 부른다")
        self.assertIn("self.go('drafts')", calls("cand_make_draft"), "`cand_make_draft` 가 서랍이 열린 채 `go(\"drafts\")` 를 부른다")
        self.assertIn("self.close_drawer_silently()", calls("go"), "`go` 가 서랍을 조용히 닫는다")
        from chanceblog_desktop.ui.core import part_rules
        self.assertEqual((part_rules.detail_layout(1365).mode, part_rules.detail_layout(1366).mode), ("drawer", "fixed"), "논리 폭 1366 미만에서만 후보 상세가 서랍으로 뜬다")
        for name in ("open_drawer", "seed_open", "seed_open_new", "cand_open"):
            self.assertTrue(writes_the_return_target(name), f"`{name}` 이 돌아갈 자리를 새로 쓰지 않는다 — 옛 값이 남아 읽힐 수 있다")
        readers = sorted(name for name, node in functions.items() if any(isinstance(part, ast.Attribute) and isinstance(part.ctx, ast.Load) and ast.unparse(part) == "self._drawer_return" for part in ast.walk(node)))
        self.assertEqual(readers, ["_sync_overlays", "close_drawer"], "돌아갈 자리의 값을 읽는 함수가 늘었다 — 지워진 위젯을 건드릴 새 길인지 보고 13절을 고친다")
        self.assertIn("if QApplication.focusWidget() is None and target is not None:", ast.get_source_segment(shell, functions["close_drawer"]), "옛 값으로 `setFocus` 를 부르는 것은 초점이 비었을 때뿐이다")
        state_source = (ROOT / "src" / "chanceblog_desktop" / "ui" / "core" / "app_state.py").read_text(encoding="utf-8")
        self.assertIn('picked = self.candidates.close_detail() if (self.page == "topics" and not silent) else None', state_source, "조용히 닫으면 고른 후보가 남고 닫기·Esc 가 그것을 돌려준다 — 13절의 '돌아온 화면에서 Esc' 길")


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
