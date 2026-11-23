"""소스 규칙 시험 — 화면의 글이 **서식 글(HTML)로 읽히는 길**이 소스에서 닫혀 있고, 새 길이 생기면 바로 빨개진다(독립 감사 AS-S1 필수-1·필수-2·권고-4·권고-5·참고-12·참고-13, 결정 D-595·D-596). PySide6 가 없어도 돈다(소스만 읽는다).

왜: Qt 의 `QLabel` 은 글 형식을 정하지 않으면(`AutoText`) 첫 줄에 서식 태그가 있는 글을 통째로 서식 글로 읽는다. 서식 글의 `<img src=경로>` 는 Qt 가 그 경로의 그림을 직접 불러오고(윈도에서 네트워크 공유 경로면 접속을 시도한다),
`<b>`·`<table>` 은 칩 모양을 속인다. 툴팁도 같다(서식 글처럼 보이는 툴팁은 서식으로 읽힌다). 외부 글(Seed·후보·백업·별명)이 닿을 수 있는 화면 부품은 모두 **일반 글(`Qt.PlainText`)** 로 그리고, 서식 글은 허용 목록의 두 곳뿐이다.

지키는 것(AST 로 `src/chanceblog_desktop/` 전체를 읽는다 — 허용 목록은 한 줄마다 이유와 함께 못박고 '목록과 같음'을 단언한다):
  1) `QLabel` 을 물려받는 모든 클래스(`QtWidgets.QLabel` 꼴 포함)는 `__init__` 안에서 `self.setTextFormat(...)` 을 부른다 — 그것도 어떤 글(`setText`·`set_text`)보다 먼저, 그리고 `super().__init__` 에는 글을 넘기지 않는다(생성자 인자가 `setText` 를 먼저 불러 한 번이라도 서식 글로 읽히지 않게).
  2) `QLabel(...)` 을 직접 만드는 곳은 만든 이름에 같은 함수 안에서 `setTextFormat` 을 부른다(이름에 담지 않은 `addWidget(QLabel(...))` 꼴은 거절).
  3) `setTextFormat` 의 인자는 `Qt.PlainText` 만 쓴다. `Qt.RichText` 는 허용 목록의 두 곳(글 전체를 `html.escape` 한 줄바꿈 글 · Unsplash 출처 줄)뿐이고, 목록은 실제와 정확히 같다.
  4) 툴팁: 모든 `setToolTip(...)` 은 `plain_tooltip(...)` 을 거치거나 빈 글(`""`)이다(고정 문구도 뷰모델이 나중에 동적 글을 섞을 수 있어 같은 길로 보낸다). `QToolTip.showText` 의 글은 `.toolTip()` 이나 `plain_tooltip(...)` 이다.
  5) 서식 글(HTML·마크다운)을 읽는 다른 길 — `QTextBrowser`·`QTextEdit`·`QMessageBox`·웹 위젯과 `setHtml`·`insertHtml`·`setMarkdown` 호출 — 은 앱에 하나도 없다(감사 AS-S1 D-6 의 '쓰지 않는 것' 을 시험으로 못박았다).
이 시험 자체도 합성 소스로 시험한다(어기는 소스가 실제로 걸리는지 — 훑기가 아무것도 못 보고 초록이 되는 일을 막는다).
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "chanceblog_desktop"

# (파일, 함수) → 이유. 서식 글(Qt.RichText)을 켜는 곳 — 새 곳을 더하려면 글을 이스케이프한 근거를 여기 적는다.
ALLOWED_RICH_TEXT = {
    ("ui/qt/components.py", "Label.__init__"): "줄바꿈 글 — 글 전체를 `html.escape` 한 뒤 줄 간격 상자 하나에만 넣는다(`<`·`&` 도 글자 그대로 보인다)",
    ("ui/qt/components.py", "AttributionRow.__init__"): "Unsplash 출처 줄 — 고정 틀 안에 작가 이름(`html.escape`)과 `check_url` 을 통과한 Unsplash 주소만 넣는다",
}

# 서식 글을 읽는 다른 위젯·설정 호출 — 앱은 하나도 쓰지 않는다. 쓰려면 이 목록을 건드리는 결정(근거)이 먼저다.
RICH_WIDGETS = {"QTextBrowser", "QTextEdit", "QMessageBox", "QWebEngineView", "QWebEnginePage", "QWebEngineProfile", "QQuickWidget"}
RICH_SETTERS = {"setHtml", "insertHtml", "setMarkdown", "insertMarkdown"}

# 이 훑기가 실제로 보고 있어야 하는 `QLabel` 하위 클래스(훑기가 아무것도 못 보고 초록이 되지 않게 — 이보다 늘어나는 것은 허용, 늘어난 것도 위 규칙을 받는다)
KNOWN_LABEL_CLASSES = {"Label", "ElidedLabel", "SemanticBadge", "Toast", "ClampedLabel", "CardChip"}


# ---- 훑기 도구 ---------------------------------------------------------------------------------------------------------------
def parse_source(source):
    tree = ast.parse(source)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return tree, parents


def dotted(node):
    """`self.preview`·`badge` 같은 이름 줄(점 이름). 호출·첨자 같은 다른 꼴이면 None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def is_qlabel(node):
    """`QLabel` 또는 `QtWidgets.QLabel` 꼴인가."""
    return (isinstance(node, ast.Name) and node.id == "QLabel") or (isinstance(node, ast.Attribute) and node.attr == "QLabel")


def method_calls(root, names):
    """`root` 안의 `<무엇>.<names 중 하나>(...)` 호출을 소스 순서(줄·칸)로."""
    found = [node for node in ast.walk(root) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in names]
    return sorted(found, key=lambda call: (call.lineno, call.col_offset))


def enclosing_function(node, parents):
    """`node` 를 품은 가장 가까운 함수와 그 '클래스.함수' 이름(없으면 None 과 '<module>')."""
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = parents.get(current)
            return current, (f"{owner.name}.{current.name}" if isinstance(owner, ast.ClassDef) else current.name)
    return None, "<module>"


def format_name(call):
    """`setTextFormat(Qt.PlainText)` 의 인자 이름(`PlainText`). 다른 꼴이면 그 소스 글."""
    if not call.args:
        return "<없음>"
    arg = call.args[0]
    if isinstance(arg, ast.Attribute) and dotted(arg.value) in ("Qt", "QtCore.Qt", "Qt.TextFormat"):
        return arg.attr
    return ast.unparse(arg)


def is_super_init(call):
    func = call.func
    return (isinstance(func, ast.Attribute) and func.attr == "__init__" and isinstance(func.value, ast.Call)
            and isinstance(func.value.func, ast.Name) and func.value.func.id == "super")


def label_findings(source):
    """한 소스의 서식 글 발견. 돌려주는 값: (문제 글 목록, QLabel 하위 클래스 이름 목록, 서식 글(RichText)을 켜는 함수 이름 목록)."""
    tree, parents = parse_source(source)
    problems, classes, rich = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(is_qlabel(base) for base in node.bases):
            classes.append(node.name)
            problems.extend(class_problems(node))
        if isinstance(node, ast.Call) and is_qlabel(node.func):
            problems.extend(creation_problems(node, tree, parents))
    for call in method_calls(tree, {"setTextFormat"}):
        name = format_name(call)
        function, qualified = enclosing_function(call, parents)
        if name == "RichText":
            rich.append(qualified)
        elif name != "PlainText":
            problems.append(f"{qualified}: setTextFormat(Qt.{name}) — Qt.PlainText 만 쓴다(줄 {call.lineno})")
    return problems, classes, rich


def class_problems(cls):
    init = next((item for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == "__init__"), None)
    if init is None:
        return [f"클래스 {cls.name}(QLabel): __init__ 이 없어 글 형식이 기본(AutoText)으로 남는다"]
    problems = []
    formats = [call for call in method_calls(init, {"setTextFormat"}) if dotted(call.func.value) == "self"]
    texts = [call for call in method_calls(init, {"setText", "set_text"}) if dotted(call.func.value) == "self"]
    if not formats:
        problems.append(f"클래스 {cls.name}(QLabel): __init__ 이 self.setTextFormat 을 부르지 않는다 — 글이 AutoText(서식 글로 읽힘)로 남는다")
    elif texts and (texts[0].lineno, texts[0].col_offset) < (formats[0].lineno, formats[0].col_offset):
        problems.append(f"클래스 {cls.name}(QLabel): setTextFormat 보다 먼저 {texts[0].func.attr} 를 부른다(줄 {texts[0].lineno})")
    for call in (node for node in ast.walk(init) if isinstance(node, ast.Call) and is_super_init(node)):
        args_ok = not call.keywords and (not call.args or (len(call.args) == 1 and dotted(call.args[0]) == "parent"))
        if not args_ok:
            problems.append(f"클래스 {cls.name}(QLabel): super().__init__({', '.join(ast.unparse(arg) for arg in call.args)}) — 글을 생성자에 넘기면 setTextFormat 보다 먼저 setText 가 불린다(줄 {call.lineno})")
    return problems


def creation_problems(call, tree, parents):
    function, qualified = enclosing_function(call, parents)
    parent = parents.get(call)
    target = None
    if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
        target = dotted(parent.targets[0])
    elif isinstance(parent, ast.AnnAssign):
        target = dotted(parent.target)
    if target is None:
        return [f"{qualified}: QLabel(...) 을 이름에 담지 않았다 — setTextFormat 을 부를 수 없다(줄 {call.lineno})"]
    scope = function if function is not None else tree
    if not any(dotted(item.func.value) == target for item in method_calls(scope, {"setTextFormat"})):
        return [f"{qualified}: {target} = QLabel(...) 에 같은 함수 안에서 setTextFormat 을 부르지 않는다 — AutoText(서식 글로 읽힘)로 남는다(줄 {call.lineno})"]
    return []


def tooltip_arg_ok(arg):
    if isinstance(arg, ast.Constant) and arg.value == "":
        return True
    if isinstance(arg, ast.Call):
        func = arg.func
        return (isinstance(func, ast.Name) and func.id == "plain_tooltip") or (isinstance(func, ast.Attribute) and func.attr == "plain_tooltip")
    return False


def show_text_arg_ok(arg):
    if tooltip_arg_ok(arg):
        return True
    return isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "toolTip" and not arg.args


def tooltip_findings(source):
    """한 소스의 날것 툴팁 글 목록(`plain_tooltip` 을 거치지 않은 `setToolTip`·`QToolTip.showText`)."""
    tree, _parents = parse_source(source)
    problems = []
    for call in method_calls(tree, {"setToolTip", "showText"}):
        if call.func.attr == "setToolTip":
            if len(call.args) != 1 or not tooltip_arg_ok(call.args[0]):
                shown = ast.unparse(call.args[0]) if call.args else "<없음>"
                problems.append(f"줄 {call.lineno}: setToolTip({shown}) — plain_tooltip(...) 을 거치지 않았다")
        elif dotted(call.func.value) in ("QToolTip", "QtWidgets.QToolTip"):
            if len(call.args) < 2 or not show_text_arg_ok(call.args[1]):
                shown = ast.unparse(call.args[1]) if len(call.args) > 1 else "<없음>"
                problems.append(f"줄 {call.lineno}: QToolTip.showText 의 글 {shown} — .toolTip() 이나 plain_tooltip(...) 이어야 한다")
    return problems


def rich_sink_findings(source):
    """서식 글(HTML·마크다운)을 읽는 다른 길 — 그런 위젯 이름(가져오기 포함)과 `setHtml` 류 호출. 앱은 이것들을 하나도 쓰지 않는다(감사 AS-S1 D-6)."""
    tree, _parents = parse_source(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found += [f"줄 {node.lineno}: 가져오기 {alias.name}" for alias in node.names if alias.name.split(".")[-1] in RICH_WIDGETS]
        elif isinstance(node, ast.Name) and node.id in RICH_WIDGETS:
            found.append(f"줄 {node.lineno}: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in RICH_WIDGETS:
            found.append(f"줄 {node.lineno}: {node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in RICH_SETTERS:
            found.append(f"줄 {node.lineno}: {node.func.attr}(...)")
    return found


def source_files(needles):
    """`src/chanceblog_desktop` 의 파이썬 파일 중 `needles` 낱말이 든 것 — (상대 경로, 소스)."""
    for path in sorted(SRC.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if any(needle in source for needle in needles):
            yield path.relative_to(SRC).as_posix(), source


# ---- 실제 소스 -----------------------------------------------------------------------------------------------------------------
class RealSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found = {name: label_findings(source) for name, source in source_files(("QLabel",))}

    def test_the_scan_really_sees_the_known_label_classes(self):
        seen = {name for _problems, classes, _rich in self.found.values() for name in classes}
        self.assertTrue(KNOWN_LABEL_CLASSES <= seen, f"훑기가 못 본 QLabel 하위 클래스: {sorted(KNOWN_LABEL_CLASSES - seen)}")

    def test_every_label_subclass_and_every_direct_label_is_plain_text_from_its_first_line(self):
        problems = [f"{name}: {problem}" for name, (found, _classes, _rich) in self.found.items() for problem in found]
        self.assertEqual(problems, [], "QLabel 은 글 형식을 정하지 않으면 서식 글(<img src=…>·<b>)로 읽는다 — `__init__` 에서 setTextFormat(Qt.PlainText) 을 먼저 부르고 그 뒤에 글을 넣는다")

    def test_rich_text_is_switched_on_only_where_the_text_is_escaped_and_the_list_matches_exactly(self):
        actual = {(name, qualified) for name, (_problems, _classes, rich) in self.found.items() for qualified in rich}
        self.assertEqual(actual, set(ALLOWED_RICH_TEXT), "서식 글(RichText)을 켜는 곳이 허용 목록과 다르다 — 새 곳은 글을 이스케이프한 근거와 함께 목록에 더한다(없어진 곳은 목록에서 뺀다)")
        for reason in ALLOWED_RICH_TEXT.values():
            self.assertTrue(reason.strip())

    def test_no_rich_text_widget_and_no_html_setter_is_used_anywhere_in_the_app(self):
        needles = tuple(RICH_WIDGETS | RICH_SETTERS)
        problems = [f"{name}: {problem}" for name, source in source_files(needles) for problem in rich_sink_findings(source)]
        self.assertEqual(problems, [], "서식 글(HTML·마크다운)을 읽는 위젯·설정 호출은 앱에 없다 — 쓰려면 결정(근거)이 먼저다")

    def test_every_tooltip_goes_through_plain_tooltip(self):
        problems = [f"{name}: {problem}" for name, source in source_files(("setToolTip", "showText")) for problem in tooltip_findings(source)]
        self.assertEqual(problems, [], "날것 툴팁 글은 서식 글처럼 보이면 서식으로 읽힌다 — `plain_tooltip(글)` 을 거치게 한다(고정 문구도)")


# ---- 합성 소스(훑기 자체의 시험) -------------------------------------------------------------------------------------------------
GOOD_CLASS = '''
class Chip(QLabel):
    def __init__(self, text):
        super().__init__()
        self.setTextFormat(Qt.PlainText)
        self.setText(text)
'''


class ScannerSelfTest(unittest.TestCase):
    def problems(self, source):
        return label_findings(source)[0]

    def test_a_correct_class_and_a_correct_direct_label_pass(self):
        self.assertEqual(label_findings(GOOD_CLASS), ([], ["Chip"], []))
        direct = "def make(text):\n    badge = QLabel(text)\n    badge.setTextFormat(Qt.PlainText)\n    return badge\n"
        self.assertEqual(label_findings(direct), ([], [], []))
        parent_only = "class Toast(QLabel):\n    def __init__(self, parent):\n        super().__init__(parent)\n        self.setTextFormat(Qt.PlainText)\n"
        self.assertEqual(self.problems(parent_only), [])
        attribute_base = "class Chip(QtWidgets.QLabel):\n    def __init__(self):\n        super().__init__()\n        self.setTextFormat(Qt.PlainText)\n"
        self.assertEqual(label_findings(attribute_base), ([], ["Chip"], []))

    def test_a_subclass_that_never_sets_the_format_is_caught(self):
        self.assertTrue(self.problems("class Chip(QLabel):\n    def __init__(self, text):\n        super().__init__()\n        self.setText(text)\n"))
        self.assertTrue(self.problems("class Chip(QLabel):\n    pass\n"), "__init__ 이 없는 하위 클래스")
        self.assertTrue(self.problems("class Chip(QtWidgets.QLabel):\n    def __init__(self, text):\n        super().__init__(text)\n"), "속성 꼴 기반 클래스도 본다")

    def test_a_subclass_that_passes_the_text_to_the_constructor_or_sets_text_first_is_caught(self):
        passed = "class Chip(QLabel):\n    def __init__(self, text):\n        super().__init__(text)\n        self.setTextFormat(Qt.PlainText)\n"
        self.assertTrue(self.problems(passed), "생성자 인자는 setText 를 먼저 부른다")
        keyword = "class Chip(QLabel):\n    def __init__(self, text):\n        super().__init__(text=text)\n        self.setTextFormat(Qt.PlainText)\n"
        self.assertTrue(self.problems(keyword))
        late = "class Chip(QLabel):\n    def __init__(self, text):\n        super().__init__()\n        self.setText(text)\n        self.setTextFormat(Qt.PlainText)\n"
        self.assertTrue(self.problems(late), "setText 가 setTextFormat 보다 먼저")
        set_text_late = "class Chip(QLabel):\n    def __init__(self, text):\n        super().__init__()\n        self.set_text(text)\n        self.setTextFormat(Qt.PlainText)\n"
        self.assertTrue(self.problems(set_text_late))

    def test_a_direct_label_without_a_format_or_without_a_name_is_caught(self):
        self.assertTrue(self.problems("def make(text):\n    badge = QLabel(text)\n    return badge\n"))
        self.assertTrue(self.problems("def make(layout):\n    layout.addWidget(QLabel('x'))\n"), "이름에 담지 않으면 setTextFormat 을 부를 수 없다")
        self.assertTrue(self.problems("def make(self):\n    self.preview = QLabel()\n    other.setTextFormat(Qt.PlainText)\n"), "다른 이름의 setTextFormat 은 소용없다")
        self.assertTrue(self.problems("def make(self):\n    self.preview = QtWidgets.QLabel()\n"), "속성 꼴 생성도 본다")
        other_function = "def a(self):\n    self.preview = QLabel()\n\ndef b(self):\n    self.preview.setTextFormat(Qt.PlainText)\n"
        self.assertTrue(self.problems(other_function), "다른 함수의 호출은 이 생성을 지키지 않는다")
        self.assertEqual(self.problems("def make(self):\n    self.preview = QLabel()\n    self.preview.setTextFormat(Qt.PlainText)\n"), [])

    def test_only_plain_text_and_the_listed_rich_text_are_formats(self):
        for bad in ("Qt.AutoText", "Qt.MarkdownText", "fmt"):
            source = f"def make(self):\n    self.preview = QLabel()\n    self.preview.setTextFormat({bad})\n"
            self.assertTrue(self.problems(source), bad)
        problems, _classes, rich = label_findings("class Box:\n    def __init__(self):\n        self.credit = QLabel()\n        self.credit.setTextFormat(Qt.RichText)\n")
        self.assertEqual((problems, rich), ([], ["Box.__init__"]), "RichText 는 문제가 아니라 허용 목록 대조로 넘긴다")

    def test_a_rich_text_widget_or_html_setter_is_caught_in_every_spelling_and_plain_widgets_pass(self):
        for bad in ("x = QTextBrowser()", "x = QtWidgets.QTextEdit()", "from PySide6.QtWidgets import QMessageBox", "from PySide6.QtWidgets import QTextEdit as T", "def f(d):\n    d.setHtml('x')", "def f(d):\n    d.insertHtml('x')",
                    "def f(d):\n    d.setMarkdown('x')", "x = QWebEngineView()", "import PySide6.QtWebEngineWidgets.QWebEngineView"):
            self.assertTrue(rich_sink_findings(bad), bad)
        for good in ("x = QPlainTextEdit()", "from PySide6.QtWidgets import QLabel, QPlainTextEdit", "def f(d):\n    d.setPlainText('x')", "x = QTextLayout('a')", "x = 'QTextBrowser setHtml'  # QMessageBox"):
            self.assertEqual(rich_sink_findings(good), [], good)

    def test_a_raw_tooltip_is_caught_and_the_safe_forms_pass(self):
        for bad in ("self.setToolTip(text)", "chip.setToolTip(reason)", "x.setToolTip(a if b else '')", "x.setToolTip(T['k'])", "x.setToolTip()", "x.setToolTip(tip())", "x.setToolTip(helper.plain_tooltip2(t))"):
            self.assertTrue(tooltip_findings(f"def f(x):\n    {bad}\n"), bad)
        for good in ("self.setToolTip(plain_tooltip(text))", "chip.setToolTip(UI.plain_tooltip(reason))", "self.name.setToolTip('')", "w.setToolTip(plain_tooltip(a if b else ''))"):
            self.assertEqual(tooltip_findings(f"def f(x):\n    {good}\n"), [], good)

    def test_a_raw_show_text_is_caught_and_the_safe_forms_pass(self):
        self.assertTrue(tooltip_findings("def f(w, t):\n    QToolTip.showText(pos, t, w)\n"))
        self.assertTrue(tooltip_findings("def f(w, t):\n    QToolTip.showText(pos)\n"))
        self.assertEqual(tooltip_findings("def f(w):\n    QToolTip.showText(pos, w.toolTip(), w)\n"), [])
        self.assertEqual(tooltip_findings("def f(w, t):\n    QToolTip.showText(pos, plain_tooltip(t), w)\n"), [])
        self.assertEqual(tooltip_findings("def f(w, t):\n    other.showText(pos, t, w)\n"), [], "QToolTip 이 아닌 showText 는 보지 않는다")


if __name__ == "__main__":
    unittest.main()
