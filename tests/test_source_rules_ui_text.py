"""소스 규칙 시험 — 화면의 글이 **서식 글(HTML)로 읽히는 길**이 소스에서 닫혀 있고, 새 길이 생기면 바로 빨개진다(독립 감사 AS-S1 필수-1·필수-2·권고-4·권고-5·참고-12·참고-13, 결정 D-595·D-596, 2차 검증 S 의 권고-4 — 결정 D-603). PySide6 가 없어도 돈다(소스만 읽는다).

왜: Qt 의 `QLabel` 은 글 형식을 정하지 않으면(`AutoText`) 첫 줄에 서식 태그가 있는 글을 통째로 서식 글로 읽는다. 서식 글의 `<img src=경로>` 는 Qt 가 그 경로의 그림을 직접 불러오고(윈도에서 네트워크 공유 경로면 접속을 시도한다),
`<b>`·`<table>` 은 칩 모양을 속인다. 툴팁도 같다(서식 글처럼 보이는 툴팁은 서식으로 읽힌다). 외부 글(Seed·후보·백업·별명)이 닿을 수 있는 화면 부품은 모두 **일반 글(`Qt.PlainText`)** 로 그리고, 서식 글은 허용 목록의 두 곳뿐이다.

지키는 것(AST 로 `src/chanceblog_desktop/` 전체를 읽는다 — 허용 목록은 한 줄마다 이유와 함께 못박고 '목록과 같음'을 단언한다):
  1) `QLabel` 을 물려받는 모든 클래스(`QtWidgets.QLabel` 꼴·`from … import QLabel as 별칭`·`별칭 = QLabel` 대입 포함)는 `__init__` 안에서 `self.setTextFormat(...)` 을 **반드시**(조건·반복 안에 숨지 않게) 부르고 — 어떤 글(`setText`·`set_text`)보다 먼저 —
     `super().__init__` 에는 글을 넘기지 않는다(생성자 인자가 `setText` 를 먼저 불러 한 번이라도 서식 글로 읽히지 않게). 하위 클래스의 하위 클래스(상속 사슬)가 `QLabel.__init__` 을 직접 불러 부모의 안전한 생성자를 건너뛰는 것도, `type(이름, (QLabel,), …)` 로 만든 하위 클래스도 거절한다.
  2) `QLabel(...)`(별칭 포함)을 직접 만드는 곳은 만든 이름에 **같은 문장 목록 안에서 그 뒤에** `setTextFormat` 을 부른다(이름에 담지 않은 `addWidget(QLabel(...))` 꼴은 거절).
  3) `setTextFormat` 의 인자는 `Qt.PlainText` 만 쓴다. `Qt.RichText` 는 허용 목록의 두 곳(글 전체를 `html.escape` 한 줄바꿈 글 · Unsplash 출처 줄)뿐이고, 목록은 실제와 정확히 같다. `getattr(객체, 'setTextFormat')` 같은 이름 돌려 부르기도 거절한다.
  4) 툴팁: 모든 `setToolTip(...)`·`setStatusTip(...)`·`setWhatsThis(...)`·`setTabToolTip(번호, ...)`·`setProperty('toolTip'|'statusTip'|'whatsThis', ...)` 의 글은 `plain_tooltip(...)` 을 거치거나 빈 글(`""`)이다(고정 문구도 뷰모델이 나중에 동적 글을 섞을 수 있어 같은 길로 보낸다).
     `QToolTip.showText` 의 글은 `.toolTip()` 이나 `plain_tooltip(...)` 이다. 이 이름들을 `getattr` 로 돌려 부르는 것도 거절한다.
  5) 서식 글(HTML·마크다운)을 읽는 다른 길 — `QTextBrowser`·`QTextEdit`·`QMessageBox`·웹 위젯과 `setHtml`·`insertHtml`·`appendHtml`·`setMarkdown` 호출(`getattr` 로 돌려 부르기 포함) — 은 앱에 하나도 없다(감사 AS-S1 D-6 의 '쓰지 않는 것' 을 시험으로 못박았다).
이 시험 자체도 합성 소스로 시험한다(어기는 소스가 실제로 걸리는지, 무해한 소스는 조용한지 — 훑기가 아무것도 못 보고 초록이 되는 일과 과탐을 함께 막는다). 검증 S 의 탐침 23개(`ProbeTableTest`)를 그대로 표로 옮겨 두었다.
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
RICH_SETTERS = {"setHtml", "insertHtml", "appendHtml", "setMarkdown", "insertMarkdown"}

# 서식 글로 읽히는 글을 받는 메서드 → 글이 오는 인자 자리(0 부터)
TIP_METHODS = {"setToolTip": 0, "setStatusTip": 0, "setWhatsThis": 0, "setTabToolTip": 1}
TIP_PROPERTIES = {"toolTip", "statusTip", "whatsThis"}                  # `setProperty('toolTip', 글)` 꼴 — 속성 이름으로 같은 글 길을 연다
TIP_NEEDLES = tuple(TIP_METHODS) + ("showText", "toolTip", "statusTip", "whatsThis")

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


def is_qlabel(node, names=("QLabel",)):
    """`QLabel`(또는 가져오기·대입 별칭 — `names`)이거나 `<무엇>.QLabel` 꼴인가."""
    return (isinstance(node, ast.Name) and node.id in names) or (isinstance(node, ast.Attribute) and node.attr == "QLabel")


def qlabel_names(tree):
    """이 소스에서 `QLabel` 을 가리키는 이름 — `QLabel` 과 `from … import QLabel as 별칭` 과 `별칭 = QLabel`·`별칭 = X.QLabel` 대입(되풀이해 따라간다)."""
    names = {"QLabel"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names if alias.name == "QLabel")
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and is_qlabel(node.value, names) and node.targets[0].id not in names):
                names.add(node.targets[0].id)
                changed = True
    return names


def label_classes(tree, names, known=()):
    """`QLabel` 을 직접 물려받는 클래스와, 그것(또는 `known` 으로 알려 준 다른 파일의 하위 클래스)을 다시 물려받는 클래스(상속 사슬)."""
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    direct = [cls for cls in classes if any(is_qlabel(base, names) for base in cls.bases)]
    derived = set(known) | {cls.name for cls in direct}
    changed = True
    while changed:
        changed = False
        for cls in classes:
            if cls.name not in derived and any((isinstance(base, ast.Name) and base.id in derived) or (isinstance(base, ast.Attribute) and base.attr in derived) for base in cls.bases):
                derived.add(cls.name)
                changed = True
    return direct, [cls for cls in classes if cls.name in derived and cls not in direct]


def method_calls(root, names):
    """`root` 안의 `<무엇>.<names 중 하나>(...)` 호출을 소스 순서(줄·칸)로."""
    found = [node for node in ast.walk(root) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in names]
    return sorted(found, key=lambda call: (call.lineno, call.col_offset))


def getattr_calls(root, names):
    """`getattr(객체, '이름')` 중 `names` 에 든 글자 이름을 돌려 부르는 것 — 이름으로 부르는 규칙이 못 보는 길."""
    return [node for node in ast.walk(root) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant) and node.args[1].value in names]


def method_references(root, parents, names):
    """`객체.이름` 을 **부르지 않고** 값으로 쓰는 곳(변수에 담기 `fn = w.setToolTip`·`connect(...)`·`partial(...)` 에 넘기기) — 그렇게 쓰면 '부르는 모양' 으로 보는 규칙이 못 본다."""
    return [node for node in ast.walk(root) if isinstance(node, ast.Attribute) and node.attr in names
            and not (isinstance(parents.get(node), ast.Call) and parents[node].func is node)]


def enclosing_function(node, parents):
    """`node` 를 품은 가장 가까운 함수와 그 '클래스.함수' 이름(없으면 None 과 '<module>')."""
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = parents.get(current)
            return current, (f"{owner.name}.{current.name}" if isinstance(owner, ast.ClassDef) else current.name)
    return None, "<module>"


def enclosing_class(node, parents):
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.ClassDef):
            return current
    return None


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


def is_self_call(stmt, names):
    """문장 하나가 곧바로 `self.<names 중 하나>(...)` 호출인가."""
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr in names and dotted(stmt.value.func.value) == "self")


def has_self_call(stmt, names):
    """문장 안(중첩 포함) 어디에든 `self.<names 중 하나>(...)` 호출이 있는가."""
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in names and dotted(node.func.value) == "self" for node in ast.walk(stmt))


def surely_runs(stmts, names):
    """이 문장들이 지나가면 **반드시** `self.<names 중 하나>` 를 부르는가 — 곧바로 한 호출이거나, 두 갈래가 모두 부르는 `if/else` 이거나, 그런 `with` 다(조건·반복·예외 길에 숨은 호출은 세지 않는다)."""
    for stmt in stmts:
        if is_self_call(stmt, names):
            return True
        if isinstance(stmt, ast.If) and stmt.orelse and surely_runs(stmt.body, names) and surely_runs(stmt.orelse, names):
            return True
        if isinstance(stmt, (ast.With, ast.AsyncWith)) and surely_runs(stmt.body, names):
            return True
    return False


def containing_block(stmt, parents):
    """그 문장이 든 문장 목록(함수 본문·`if` 몸통·모듈 …)."""
    parent = parents.get(stmt)
    for field in ("body", "orelse", "finalbody"):
        block = getattr(parent, field, None)
        if isinstance(block, list) and stmt in block:
            return block
    return []


def label_findings(source, allowed_rich=(), known=()):
    """한 소스의 서식 글 발견. 돌려주는 값: (문제 글 목록, QLabel 하위 클래스 이름 목록(직접+상속 사슬), 서식 글(RichText)을 켜는 함수 이름 목록).
    `allowed_rich`: 서식 글을 켜도 되는 '클래스.함수' 이름들(허용 목록의 이 파일 몫 — 아니면 문제로 센다). `known`: 다른 파일에서 이미 알아낸 `QLabel` 하위 클래스 이름들."""
    tree, parents = parse_source(source)
    names = qlabel_names(tree)
    direct, indirect = label_classes(tree, names, known)
    indirect_names = {cls.name for cls in indirect}
    problems, rich = [], []
    for cls in direct:
        problems.extend(class_problems(cls))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if is_qlabel(node.func, names):
            problems.extend(creation_problems(node, parents))
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "__init__" and is_qlabel(node.func.value, names):
            problems.extend(parent_init_problems(node, parents, indirect_names))
        elif isinstance(node.func, ast.Name) and node.func.id == "type" and len(node.args) == 3 and isinstance(node.args[1], (ast.Tuple, ast.List)) \
                and any(is_qlabel(base, names) or (isinstance(base, ast.Name) and base.id in indirect_names | set(known)) for base in node.args[1].elts):
            problems.append(f"줄 {node.lineno}: type(…, (QLabel, …), …) 로 하위 클래스를 만든다 — 규칙이 못 본다(클래스 문으로 만들고 __init__ 에서 setTextFormat 을 부른다)")
    for call in getattr_calls(tree, {"setTextFormat"}):
        problems.append(f"줄 {call.lineno}: getattr 로 setTextFormat 을 돌려 부른다 — 규칙이 못 본다")
    for reference in method_references(tree, parents, {"setTextFormat"}):
        problems.append(f"줄 {reference.lineno}: setTextFormat 을 부르지 않고 값으로 쓴다(변수에 담기·넘기기) — 규칙이 못 본다")
    for call in method_calls(tree, {"setTextFormat"}):
        name = format_name(call)
        function, qualified = enclosing_function(call, parents)
        if name == "RichText":
            rich.append(qualified)
            if qualified not in allowed_rich:
                problems.append(f"{qualified}: setTextFormat(Qt.RichText) — 허용 목록에 없는 곳에서 서식 글을 켠다(줄 {call.lineno})")
        elif name != "PlainText":
            problems.append(f"{qualified}: setTextFormat(Qt.{name}) — Qt.PlainText 만 쓴다(줄 {call.lineno})")
    return problems, [cls.name for cls in direct + indirect], rich


def class_problems(cls):
    init = next((item for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == "__init__"), None)
    if init is None:
        return [f"클래스 {cls.name}(QLabel): __init__ 이 없어 글 형식이 기본(AutoText)으로 남는다"]
    problems = []
    body = init.body
    format_at = next((index for index, stmt in enumerate(body) if surely_runs([stmt], {"setTextFormat"})), None)
    text_at = next((index for index, stmt in enumerate(body) if has_self_call(stmt, {"setText", "set_text"})), None)
    if format_at is None:
        problems.append(f"클래스 {cls.name}(QLabel): __init__ 이 self.setTextFormat 을 반드시(조건·반복 안에 숨지 않게) 부르지 않는다 — 글이 AutoText(서식 글로 읽힘)로 남을 수 있다")
    elif text_at is not None and text_at <= format_at:
        problems.append(f"클래스 {cls.name}(QLabel): setTextFormat 보다 먼저(또는 같은 문장에서) setText 를 부른다(줄 {body[text_at].lineno})")
    for call in (node for node in ast.walk(init) if isinstance(node, ast.Call) and is_super_init(node)):
        args_ok = not call.keywords and (not call.args or (len(call.args) == 1 and dotted(call.args[0]) == "parent"))
        if not args_ok:
            problems.append(f"클래스 {cls.name}(QLabel): super().__init__({', '.join(ast.unparse(arg) for arg in call.args)}) — 글을 생성자에 넘기면 setTextFormat 보다 먼저 setText 가 불린다(줄 {call.lineno})")
    return problems


def parent_init_problems(call, parents, indirect_names):
    """`QLabel.__init__(self, ...)` 직접 호출 — 글(또는 `text=`)을 넘기면 setTextFormat 보다 먼저 setText 가 불리고, 하위 클래스의 하위 클래스가 부르면 부모의 안전한 생성자를 건너뛴다."""
    owner = enclosing_class(call, parents)
    extra = call.args[1:]
    carries_text = bool(call.keywords) or any(dotted(arg) != "parent" for arg in extra)
    if owner is not None and owner.name in indirect_names:
        return [f"클래스 {owner.name}: QLabel.__init__ 을 직접 부른다 — 부모(하위 클래스)의 안전한 생성자(일반 글 지정)를 건너뛴다(줄 {call.lineno})"]
    if carries_text:
        return [f"줄 {call.lineno}: QLabel.__init__(self, ...) 에 글을 넘긴다 — setTextFormat 보다 먼저 setText 가 불린다"]
    return []


def creation_problems(call, parents):
    function, qualified = enclosing_function(call, parents)
    stmt = parents.get(call)
    target = None
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target = dotted(stmt.targets[0])
    elif isinstance(stmt, ast.AnnAssign):
        target = dotted(stmt.target)
    if target is None:
        return [f"{qualified}: QLabel(...) 을 이름에 담지 않았다 — setTextFormat 을 부를 수 없다(줄 {call.lineno})"]
    block = containing_block(stmt, parents)
    after = block[block.index(stmt) + 1:] if stmt in block else []
    if not any(isinstance(item, ast.Expr) and isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Attribute) and item.value.func.attr == "setTextFormat"
               and dotted(item.value.func.value) == target for item in after):
        return [f"{qualified}: {target} = QLabel(...) 뒤에 같은 문장 목록 안에서 {target}.setTextFormat 을 곧바로 부르지 않는다 — AutoText(서식 글로 읽힘)로 남을 수 있다(줄 {call.lineno})"]
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
    """한 소스의 날것 툴팁류 글 목록(`plain_tooltip` 을 거치지 않은 `setToolTip`·`setStatusTip`·`setWhatsThis`·`setTabToolTip`·`setProperty('toolTip', …)`·`QToolTip.showText`, `getattr` 로 돌려 부르기)."""
    tree, parents = parse_source(source)
    problems = []
    for reference in method_references(tree, parents, set(TIP_METHODS) | {"showText"}):
        problems.append(f"줄 {reference.lineno}: {reference.attr} 을 부르지 않고 값으로 쓴다(변수에 담기·넘기기) — 규칙이 못 본다")
    for call in method_calls(tree, set(TIP_METHODS) | {"showText", "setProperty"}):
        name = call.func.attr
        if name in TIP_METHODS:
            index = TIP_METHODS[name]
            exact = len(call.args) == index + 1 if name == "setToolTip" else len(call.args) > index
            if not exact or not tooltip_arg_ok(call.args[index]):
                shown = ast.unparse(call.args[index]) if len(call.args) > index else "<없음>"
                problems.append(f"줄 {call.lineno}: {name}({shown}) — plain_tooltip(...) 을 거치지 않았다")
        elif name == "setProperty":
            if call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value in TIP_PROPERTIES:
                if len(call.args) < 2 or not tooltip_arg_ok(call.args[1]):
                    shown = ast.unparse(call.args[1]) if len(call.args) > 1 else "<없음>"
                    problems.append(f"줄 {call.lineno}: setProperty({call.args[0].value!r}, {shown}) — plain_tooltip(...) 을 거치지 않았다")
        elif dotted(call.func.value) in ("QToolTip", "QtWidgets.QToolTip"):
            if len(call.args) < 2 or not show_text_arg_ok(call.args[1]):
                shown = ast.unparse(call.args[1]) if len(call.args) > 1 else "<없음>"
                problems.append(f"줄 {call.lineno}: QToolTip.showText 의 글 {shown} — .toolTip() 이나 plain_tooltip(...) 이어야 한다")
    for call in getattr_calls(tree, set(TIP_METHODS)):
        problems.append(f"줄 {call.lineno}: getattr 로 {call.args[1].value} 를 돌려 부른다 — 규칙이 못 본다")
    return problems


def rich_sink_findings(source):
    """서식 글(HTML·마크다운)을 읽는 다른 길 — 그런 위젯 이름(가져오기 포함)과 `setHtml` 류 호출(`getattr` 로 돌려 부르기 포함). 앱은 이것들을 하나도 쓰지 않는다(감사 AS-S1 D-6)."""
    tree, parents = parse_source(source)
    found = [f"줄 {reference.lineno}: {reference.attr} 을 부르지 않고 값으로 쓴다" for reference in method_references(tree, parents, RICH_SETTERS)]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found += [f"줄 {node.lineno}: 가져오기 {alias.name}" for alias in node.names if alias.name.split(".")[-1] in RICH_WIDGETS]
        elif isinstance(node, ast.Name) and node.id in RICH_WIDGETS:
            found.append(f"줄 {node.lineno}: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in RICH_WIDGETS:
            found.append(f"줄 {node.lineno}: {node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in RICH_SETTERS:
            found.append(f"줄 {node.lineno}: {node.func.attr}(...)")
    found += [f"줄 {call.lineno}: getattr 로 {call.args[1].value} 를 돌려 부른다" for call in getattr_calls(tree, RICH_SETTERS)]
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
        first = {name: label_findings(source) for name, source in source_files(("QLabel",))}
        cls.known = {name for _problems, classes, _rich in first.values() for name in classes}       # 상속 사슬 — 이 이름들을 물려받는 클래스가 `QLabel` 낱말 없는 파일에 있어도 본다
        cls.found = {name: label_findings(source, allowed_rich={qualified for (file, qualified) in ALLOWED_RICH_TEXT if file == name}, known=cls.known)
                     for name, source in source_files(("QLabel", *cls.known))}

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
        problems = [f"{name}: {problem}" for name, source in source_files(TIP_NEEDLES) for problem in tooltip_findings(source)]
        self.assertEqual(problems, [], "날것 툴팁류 글은 서식 글처럼 보이면 서식으로 읽힌다 — `plain_tooltip(글)` 을 거치게 한다(고정 문구도)")


# ---- 합성 소스(훑기 자체의 시험) -------------------------------------------------------------------------------------------------
GOOD_CLASS = '''
class Chip(QLabel):
    def __init__(self, text):
        super().__init__()
        self.setTextFormat(Qt.PlainText)
        self.setText(text)
'''

# 검증 S 의 탐침 `probe_ui_rules.py` 23개 그대로(라벨, 소스, 종류, 잡혀야 하는가) — 놓친 13개를 못박고 무해한 것은 조용해야 한다.
PROBE_CASES = (
    ("alias import: class X(Q)", "from PySide6.QtWidgets import QLabel as Q\nclass X(Q):\n    def __init__(self, t):\n        super().__init__(t)\n", "label", True),
    ("alias import: Q(text) 직접 생성", "from PySide6.QtWidgets import QLabel as Q\ndef f(t):\n    x = Q(t)\n    return x\n", "label", True),
    ("전체 이름 PySide6.QtWidgets.QLabel(...)", "import PySide6\ndef f(t):\n    x = PySide6.QtWidgets.QLabel(t)\n    return x\n", "label", True),
    ("람다 안 생성", "make = lambda t: QLabel(t)\n", "label", True),
    ("하위 클래스의 하위 클래스: 부모 생성자 직접", "class Sub(ElidedLabel):\n    def __init__(self, t):\n        QLabel.__init__(self, t)\n", "label", True),
    ("하위 클래스의 하위 클래스: setTextFormat(AutoText) 되돌림", "class Sub(ElidedLabel):\n    def __init__(self, t):\n        super().__init__(t)\n        self.setTextFormat(Qt.AutoText)\n", "label", True),
    ("하위 클래스의 하위 클래스: setText 재정의 후 서식", "class Sub(CardChip):\n    def __init__(self, t):\n        super().__init__(t)\n    def refresh(self, t):\n        self.setTextFormat(Qt.RichText)\n        self.setText(t)\n", "label", True),
    ("조건 안 setTextFormat", "class X(QLabel):\n    def __init__(self, t):\n        super().__init__()\n        if False:\n            self.setTextFormat(Qt.PlainText)\n        self.setText(t)\n", "label", True),
    ("getattr 로 setTextFormat(RichText)", "class X(QLabel):\n    def __init__(self, t):\n        super().__init__()\n        self.setTextFormat(Qt.PlainText)\n        getattr(self, 'setTextFormat')(Qt.RichText)\n", "label", True),
    ("type() 으로 하위 클래스", "X = type('X', (QLabel,), {})\n", "label", True),
    ("setText(f'<img …') 를 일반 라벨에 — 일반 글이라 안전(과탐 없어야)", "def f(self, p):\n    self.preview = QLabel()\n    self.preview.setTextFormat(Qt.PlainText)\n    self.preview.setText(f'<img src={p}>')\n", "label", False),
    ("setToolTip 날것", "def f(w, t):\n    w.setToolTip(t)\n", "tip", True),
    ("setStatusTip 날것", "def f(w, t):\n    w.setStatusTip(t)\n", "tip", True),
    ("setWhatsThis 날것", "def f(w, t):\n    w.setWhatsThis(t)\n", "tip", True),
    ("setTabToolTip 날것", "def f(w, t):\n    w.setTabToolTip(0, t)\n", "tip", True),
    ("setProperty('toolTip', t)", "def f(w, t):\n    w.setProperty('toolTip', t)\n", "tip", True),
    ("getattr(w,'setToolTip')(t)", "def f(w, t):\n    getattr(w, 'setToolTip')(t)\n", "tip", True),
    ("QAction.setToolTip 날것", "def f(a, t):\n    a.setToolTip(t)\n", "tip", True),
    ("QMessageBox 별칭 import", "from PySide6.QtWidgets import QMessageBox as MB\nMB.information(None, 'x', '<b>y</b>')\n", "sink", True),
    ("QtWidgets.QMessageBox 속성", "import PySide6.QtWidgets as W\nW.QMessageBox.warning(None, 't', 'x')\n", "sink", True),
    ("QTextBrowser 별칭", "from PySide6.QtWidgets import QTextBrowser as TB\nx = TB()\n", "sink", True),
    ("QPlainTextEdit + appendHtml", "def f(e):\n    e.appendHtml('<b>x</b>')\n", "sink", True),
    ("QLabel.setMarkdown 등 setText 대체(setMarkdown)", "def f(d):\n    d.setMarkdown('x')\n", "sink", True),
)

# 무해한 소스 — 같은 모양이라도 안전하게 쓴 것은 조용해야 한다(과탐 0).
HARMLESS_CASES = (
    ("안전한 하위 클래스의 하위 클래스(부모 생성자에 글 위임)", "class Sub(ElidedLabel):\n    def __init__(self, t):\n        super().__init__(t)\n", "label"),
    ("별칭으로 맞게 쓴 하위 클래스", "from PySide6.QtWidgets import QLabel as Q\nclass X(Q):\n    def __init__(self, t):\n        super().__init__()\n        self.setTextFormat(Qt.PlainText)\n        self.setText(t)\n", "label"),
    ("별칭으로 맞게 직접 생성", "from PySide6.QtWidgets import QLabel as Q\ndef f(t):\n    x = Q()\n    x.setTextFormat(Qt.PlainText)\n    x.setText(t)\n    return x\n", "label"),
    ("두 갈래가 모두 형식을 정하는 if/else", "class X(QLabel):\n    def __init__(self, wrap):\n        super().__init__()\n        if wrap:\n            self.setTextFormat(Qt.PlainText)\n        else:\n            self.setTextFormat(Qt.PlainText)\n        self.setText('x')\n", "label"),
    ("with 안의 형식 지정", "class X(QLabel):\n    def __init__(self, t):\n        super().__init__()\n        with lock:\n            self.setTextFormat(Qt.PlainText)\n        self.setText(t)\n", "label"),
    ("글을 안 넘기는 QLabel.__init__(self) — 직접 하위 클래스", "class X(QLabel):\n    def __init__(self):\n        QLabel.__init__(self)\n        self.setTextFormat(Qt.PlainText)\n", "label"),
    ("QLabel 이 아닌 type() 과 이름이 변수인 getattr", "X = type('X', (object,), {})\ndef f(board, name, args):\n    return getattr(board, name)(*args)\n", "label"),
    ("상관없는 setProperty·getattr·메서드 값", "def f(w, value, signal):\n    w.setProperty('role', value)\n    w.setProperty('tone', 'ok')\n    signal.connect(w.setEnabled)\n    return getattr(w, 'objectName')()\n", "tip"),
    ("plain_tooltip 을 거친 툴팁류 다섯 길", "def f(w, t):\n    w.setToolTip(plain_tooltip(t))\n    w.setStatusTip(plain_tooltip(t))\n    w.setWhatsThis('')\n    w.setTabToolTip(0, UI.plain_tooltip(t))\n    w.setProperty('toolTip', plain_tooltip(t))\n", "tip"),
    ("서식 아닌 편집 길", "def f(e, d):\n    e.appendPlainText('<b>x</b>')\n    d.setPlainText('x')\n    d.insertPlainText('y')\n", "sink"),
)


# 시험 검증 Q 의 참고-1 — 다른 이름으로 가져온 `QLabel` 과 `setToolTip` 의 간접 호출(이름 돌려 부르기·메서드를 변수에 담기·넘기기). 잡혀야 한다.
EXTRA_CASES = (
    ("별칭 L 의 하위 클래스", "from PySide6.QtWidgets import QLabel as L\nclass A(L):\n    def __init__(self, text):\n        super().__init__(text)\n", "label"),
    ("별칭 L 을 이름에 안 담고 넘김", "from PySide6.QtWidgets import QLabel as L\ndef f(layout):\n    layout.addWidget(L('<b>x</b>'))\n", "label"),
    ("getattr 로 setToolTip", "def f(w, t):\n    getattr(w, 'setToolTip')(t)\n", "tip"),
    ("메서드를 변수에 담아 부름", "def f(w, t):\n    fn = w.setToolTip\n    fn(t)\n", "tip"),
    ("메서드를 connect 에 넘김", "def f(w, signal):\n    signal.connect(w.setStatusTip)\n", "tip"),
    ("setTextFormat 을 변수에 담아 부름", "def f(w):\n    fn = w.setTextFormat\n    fn(Qt.RichText)\n", "label"),
    ("setHtml 을 변수에 담아 부름", "def f(d):\n    put = d.setHtml\n    put('x')\n", "sink"),
)


def scanner_caught(kind, source, **options):
    if kind == "label":
        return bool(label_findings(source, **options)[0])
    if kind == "tip":
        return bool(tooltip_findings(source))
    return bool(rich_sink_findings(source))


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

    def test_a_format_call_that_hides_in_a_condition_or_comes_in_another_block_does_not_count(self):
        """검증 S 의 권고-4 — `if False:` 안의 `setTextFormat` 은 `__init__` 이 그 줄을 지나지 않을 수 있어 글이 서식 글로 남는다(두 갈래가 모두 부르는 `if/else` 만 센다). 직접 생성도 같은 문장 목록에서 그 뒤여야 한다."""
        self.assertTrue(self.problems("class X(QLabel):\n    def __init__(self, t):\n        super().__init__()\n        if t:\n            self.setTextFormat(Qt.PlainText)\n        self.setText(t)\n"))
        self.assertTrue(self.problems("class X(QLabel):\n    def __init__(self, t):\n        super().__init__()\n        for _ in t:\n            self.setTextFormat(Qt.PlainText)\n"))
        self.assertTrue(self.problems("class X(QLabel):\n    def __init__(self, t):\n        super().__init__()\n        if t:\n            self.setTextFormat(Qt.PlainText)\n        else:\n            pass\n"), "한 갈래만 정하는 if/else")
        self.assertTrue(self.problems("class X(QLabel):\n    def __init__(self, t):\n        super().__init__()\n        try:\n            self.setTextFormat(Qt.PlainText)\n        except Exception:\n            pass\n"), "예외 길에 숨은 호출")
        self.assertTrue(self.problems("def make(self, t):\n    self.preview = QLabel()\n    if t:\n        self.preview.setTextFormat(Qt.PlainText)\n"), "직접 생성 뒤의 조건 안 호출")
        self.assertEqual(self.problems("def make(self, t):\n    if t:\n        self.preview = QLabel()\n        self.preview.setTextFormat(Qt.PlainText)\n"), [], "생성과 같은 문장 목록 안에서 곧바로 부르면 된다")

    def test_aliases_of_qlabel_are_followed_through_imports_and_assignments(self):
        names = qlabel_names(ast.parse("from PySide6.QtWidgets import QFrame, QLabel as Q, QLabel\nR = Q\nS = QtWidgets.QLabel\nT = Unrelated\n"))
        self.assertEqual(names, {"QLabel", "Q", "R", "S"})
        self.assertTrue(self.problems("Q = QLabel\nclass X(Q):\n    def __init__(self, t):\n        super().__init__(t)\n"), "대입 별칭")
        self.assertTrue(self.problems("import PySide6.QtWidgets as W\nclass X(W.QLabel):\n    pass\n"), "모듈 별칭의 속성 꼴")

    def test_the_inheritance_chain_is_followed_so_a_grandchild_cannot_skip_the_safe_constructor(self):
        grandchild = "class Base(QLabel):\n    def __init__(self, t):\n        super().__init__()\n        self.setTextFormat(Qt.PlainText)\n        self.setText(t)\n\nclass Sub(Base):\n    def __init__(self):\n        QLabel.__init__(self)\n"
        found = label_findings(grandchild)
        self.assertEqual(found[1], ["Base", "Sub"], "상속 사슬의 클래스도 목록에 든다")
        self.assertTrue(found[0], "손자 클래스가 QLabel.__init__ 을 글 없이 불러도 부모의 일반 글 지정을 건너뛴다")
        self.assertTrue(label_findings("class Sub(ElidedLabel):\n    def __init__(self):\n        QLabel.__init__(self)\n", known={"ElidedLabel"})[0], "다른 파일에서 알아낸 하위 클래스도 따라간다")
        self.assertEqual(label_findings("class Sub(ElidedLabel):\n    def __init__(self):\n        QLabel.__init__(self)\n")[0], [], "알려지지 않은 부모는 사슬을 모르므로 글 없는 호출은 그냥 둔다")
        self.assertEqual(label_findings("class Sub(ElidedLabel):\n    def __init__(self, t):\n        super().__init__(t)\n", known={"ElidedLabel"})[0], [], "부모 생성자에 글을 맡기는 것은 안전하다")
        self.assertTrue(label_findings("class Sub(Base):\n    def __init__(self, t):\n        QLabel.__init__(self, t)\n", known={"Base"})[0])

    def test_a_type_call_that_builds_a_label_subclass_or_a_getattr_call_of_a_watched_name_is_caught(self):
        self.assertTrue(self.problems("X = type('X', (QLabel,), {})\n"))
        self.assertTrue(self.problems("X = type('X', [QtWidgets.QLabel], {})\n"))
        self.assertTrue(self.problems("from PySide6.QtWidgets import QLabel as Q\nX = type('X', (Q,), {})\n"))
        self.assertTrue(self.problems("def f(w):\n    getattr(w, 'setTextFormat')(Qt.RichText)\n"))
        self.assertEqual(self.problems("X = type('X', (object,), {})\ndef f(w, name):\n    getattr(w, name)()\n"), [])

    def test_only_plain_text_and_the_listed_rich_text_are_formats(self):
        for bad in ("Qt.AutoText", "Qt.MarkdownText", "fmt"):
            source = f"def make(self):\n    self.preview = QLabel()\n    self.preview.setTextFormat({bad})\n"
            self.assertTrue(self.problems(source), bad)
        rich_source = "class Box:\n    def __init__(self):\n        self.credit = QLabel()\n        self.credit.setTextFormat(Qt.RichText)\n"
        problems, _classes, rich = label_findings(rich_source, allowed_rich={"Box.__init__"})
        self.assertEqual((problems, rich), ([], ["Box.__init__"]), "허용 목록에 든 곳의 RichText 는 문제가 아니다")
        problems, _classes, rich = label_findings(rich_source)
        self.assertEqual(rich, ["Box.__init__"])
        self.assertTrue(problems, "허용 목록에 없는 곳의 RichText 는 그 자리에서 문제다")

    def test_a_rich_text_widget_or_html_setter_is_caught_in_every_spelling_and_plain_widgets_pass(self):
        for bad in ("x = QTextBrowser()", "x = QtWidgets.QTextEdit()", "from PySide6.QtWidgets import QMessageBox", "from PySide6.QtWidgets import QTextEdit as T", "def f(d):\n    d.setHtml('x')", "def f(d):\n    d.insertHtml('x')",
                    "def f(d):\n    d.appendHtml('x')", "def f(d):\n    d.setMarkdown('x')", "x = QWebEngineView()", "import PySide6.QtWebEngineWidgets.QWebEngineView", "def f(d):\n    getattr(d, 'appendHtml')('x')"):
            self.assertTrue(rich_sink_findings(bad), bad)
        for good in ("x = QPlainTextEdit()", "from PySide6.QtWidgets import QLabel, QPlainTextEdit", "def f(d):\n    d.setPlainText('x')", "x = QTextLayout('a')", "x = 'QTextBrowser setHtml'  # QMessageBox", "def f(d):\n    d.appendPlainText('x')"):
            self.assertEqual(rich_sink_findings(good), [], good)

    def test_a_raw_tooltip_is_caught_and_the_safe_forms_pass(self):
        for bad in ("self.setToolTip(text)", "chip.setToolTip(reason)", "x.setToolTip(a if b else '')", "x.setToolTip(T['k'])", "x.setToolTip()", "x.setToolTip(tip())", "x.setToolTip(helper.plain_tooltip2(t))"):
            self.assertTrue(tooltip_findings(f"def f(x):\n    {bad}\n"), bad)
        for good in ("self.setToolTip(plain_tooltip(text))", "chip.setToolTip(UI.plain_tooltip(reason))", "self.name.setToolTip('')", "w.setToolTip(plain_tooltip(a if b else ''))"):
            self.assertEqual(tooltip_findings(f"def f(x):\n    {good}\n"), [], good)

    def test_the_other_tooltip_like_paths_are_caught_raw_and_pass_through_plain_tooltip(self):
        """검증 S 의 권고-4 — `setStatusTip`·`setWhatsThis`·`setTabToolTip`·`setProperty('toolTip', …)`·`getattr` 로 돌려 부르기도 같은 서식 글 길이다."""
        raw = ("w.setStatusTip(t)", "w.setWhatsThis(t)", "w.setTabToolTip(0, t)", "w.setProperty('toolTip', t)", "w.setProperty('statusTip', t)", "w.setProperty('whatsThis', t)",
               "w.setStatusTip()", "w.setTabToolTip(0)", "w.setProperty('toolTip')", "getattr(w, 'setToolTip')(t)", "getattr(w, 'setStatusTip')", "getattr(w, 'setTabToolTip')(0, t)")
        for bad in raw:
            self.assertTrue(tooltip_findings(f"def f(w, t):\n    {bad}\n"), bad)
        safe = ("w.setStatusTip(plain_tooltip(t))", "w.setStatusTip('')", "w.setWhatsThis(UI.plain_tooltip(t))", "w.setTabToolTip(0, plain_tooltip(t))", "w.setTabToolTip(index, '')", "w.setProperty('toolTip', plain_tooltip(t))",
                "w.setProperty('role', t)", "w.setProperty(name, t)", "getattr(w, name)(t)", "getattr(w, 'objectName')()")
        for good in safe:
            self.assertEqual(tooltip_findings(f"def f(w, t, name, index):\n    {good}\n"), [], good)

    def test_a_raw_show_text_is_caught_and_the_safe_forms_pass(self):
        self.assertTrue(tooltip_findings("def f(w, t):\n    QToolTip.showText(pos, t, w)\n"))
        self.assertTrue(tooltip_findings("def f(w, t):\n    QToolTip.showText(pos)\n"))
        self.assertEqual(tooltip_findings("def f(w):\n    QToolTip.showText(pos, w.toolTip(), w)\n"), [])
        self.assertEqual(tooltip_findings("def f(w, t):\n    QToolTip.showText(pos, plain_tooltip(t), w)\n"), [])
        self.assertEqual(tooltip_findings("def f(w, t):\n    other.showText(pos, t, w)\n"), [], "QToolTip 이 아닌 showText 는 보지 않는다")


class ProbeTableTest(unittest.TestCase):
    """검증 S 의 탐침 23개를 표로 옮겨 항목마다 따로 단언한다 — 잡혀야 하는 것은 잡히고(놓친 13개 포함) 안전한 것(`setText` 에 서식 모양 글을 넣는 일반 라벨)은 조용하다. 무해한 열 가지도 조용하다(과탐 0)."""

    def test_every_case_the_verifier_probed_is_caught_or_quiet_as_expected(self):
        self.assertEqual(len(PROBE_CASES), 23)
        for label, source, kind, expect in PROBE_CASES:
            for options in ({}, {"known": {"ElidedLabel", "CardChip"}}):
                if options and kind != "label":
                    continue
                with self.subTest(case=label, known=bool(options)):
                    self.assertEqual(scanner_caught(kind, source, **options), expect)

    def test_the_cases_the_scanner_used_to_miss_are_now_caught(self):
        missed_before = ("alias import: class X(Q)", "alias import: Q(text) 직접 생성", "하위 클래스의 하위 클래스: 부모 생성자 직접", "하위 클래스의 하위 클래스: setText 재정의 후 서식", "조건 안 setTextFormat",
                         "getattr 로 setTextFormat(RichText)", "type() 으로 하위 클래스", "setStatusTip 날것", "setWhatsThis 날것", "setTabToolTip 날것", "setProperty('toolTip', t)", "getattr(w,'setToolTip')(t)",
                         "QPlainTextEdit + appendHtml")
        by_label = {label: (source, kind) for label, source, kind, _expect in PROBE_CASES}
        self.assertEqual(len(missed_before), 13)
        for label in missed_before:
            with self.subTest(case=label):
                source, kind = by_label[label]
                self.assertTrue(scanner_caught(kind, source), "놓치던 모양을 이제 잡아야 한다")

    def test_the_qlabel_alias_and_indirect_call_shapes_the_test_verifier_found_are_caught(self):
        self.assertEqual(len(EXTRA_CASES), 7)
        for label, source, kind in EXTRA_CASES:
            with self.subTest(case=label):
                self.assertTrue(scanner_caught(kind, source), "다른 이름·간접 호출 모양을 못 봤다")

    def test_harmless_sources_stay_quiet_with_and_without_the_known_chain(self):
        self.assertEqual(len(HARMLESS_CASES), 10)
        for label, source, kind in HARMLESS_CASES:
            for options in ({}, {"known": {"ElidedLabel", "CardChip"}}):
                if options and kind != "label":
                    continue
                with self.subTest(case=label, known=bool(options)):
                    self.assertFalse(scanner_caught(kind, source, **options), "무해한 소스를 거절했다(과탐)")


if __name__ == "__main__":
    unittest.main()
