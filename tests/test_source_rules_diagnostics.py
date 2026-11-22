"""'진단 정보 복사'(L3, 결정 D-539 에서 D-541)의 소스 규칙 시험 — 순수 AST 라 PySide6 없이 CI 에서도 돈다(검증 S 의 SP-5·SP-6 제안을 합쳤다).

지키는 것:
  1) **눌러야만 복사한다**: `copy_diagnostics` 를 가리키는 곳(부름·`fn = …` 이름 붙이기·다른 신호에 물리기 모두)은 `src/` 전체에서 정확히 한 곳이고, 그곳은 단추의 `….clicked.connect(…)` 인자 안이다 — 화면을 그리거나 카드를 만들 때 저절로 복사하는 길이 없다.
     (이것을 지키는 Qt 시험은 CI 에 PySide6 가 없어 건너뛰므로 같은 약속을 소스 규칙으로도 못박는다.)
  2) **실패의 코드는 프로그램이 정한 이름뿐이다**(D-541 의 전제): `ui/` 아래 `…Failure(…)` 의 코드 자리는 글자 상수·`….code`·`type(…).__name__`·그렇게 정해진 변수·`getattr(…, "code")`(글자 가림 함수로 감싼 것 포함) 중 하나다.
     오류 코드 칸은 영문·숫자·밑줄이면 통과하므로, 나중에 사용자 글(블로그 이름·후보 제목 …)이 코드 자리에 들어가면 그 글이 그대로 복사된다 — 그때 이 시험이 빨개져 설계를 다시 보게 한다.
이 시험 자신도 합성 소스로 시험한다(어기는 소스가 실제로 걸리고 지켜진 소스는 안 걸린다).
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
UI = SRC / "chanceblog_desktop" / "ui"
ALLOWED_NAMES = {"code"}                                                                   # 코드를 담는 변수 이름 — 같은 함수 안의 대입이 모두 허용 모양이어야 한다
WRAPPERS = ("str", "display_text", "_shown", "shown")                                         # 글자 가림·글로 바꾸기 — 안의 값이 허용 모양이면 감싼 것도 허용


def parents_of(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def copy_references(tree):
    """`copy_diagnostics` 를 가리키는 곳(부름뿐 아니라 `fn = shell.copy_diagnostics` 처럼 이름만 붙이거나 다른 곳에 넘기는 것도) → [(줄, 단추의 `….clicked.connect(…)` 인자 안인가)].
    정의(`def`)와 글(독스트링·주석) 속 이름은 가리킴이 아니다."""
    parents, found = parents_of(tree), []
    for node in ast.walk(tree):
        if not ((isinstance(node, ast.Attribute) and node.attr == "copy_diagnostics") or (isinstance(node, ast.Name) and node.id == "copy_diagnostics")):
            continue
        chain, cursor = [], node
        while cursor in parents:
            cursor = parents[cursor]
            chain.append(cursor)
        inside = any(isinstance(item, ast.Call) and ast.unparse(item.func).endswith("clicked.connect") for item in chain)
        found.append((node.lineno, inside))
    return found


def kind_of(node):
    """코드 자리의 식이 허용 모양이면 그 모양 이름, 아니면 None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "상수"
    if isinstance(node, ast.Attribute) and node.attr == "code":
        return "….code"
    if isinstance(node, ast.Attribute) and node.attr == "__name__" and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "type":
        return "type(…).__name__"
    if isinstance(node, ast.Name) and (node.id in ALLOWED_NAMES or node.id.isupper()):
        return "이름 " + node.id
    if isinstance(node, ast.Call):
        name = getattr(node.func, "id", getattr(node.func, "attr", ""))
        if name == "getattr" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == "code":
            return "getattr(…,'code')"
        if name in WRAPPERS and node.args and kind_of(node.args[0]):
            return "감싼 " + kind_of(node.args[0])
    if isinstance(node, ast.BoolOp) and all(kind_of(value) for value in node.values):
        return "or 묶음"
    return None


def name_origin_ok(function, name):
    """변수 `code` 가 가리키는 값 — 같은 함수 안의 대입이 모두 허용 모양이거나 함수의 인자(그 함수를 부르는 곳은 따로 검사된다)여야 한다."""
    if function is None:
        return False
    params = {arg.arg for arg in function.args.args + function.args.kwonlyargs}
    values = [node.value for node in ast.walk(function) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    return (name in params or bool(values)) and all(kind_of(value) for value in values)


def failure_sites(tree):
    """`…Failure(…)` 를 만드는 곳 → [(줄, 만드는 이름, 코드 자리의 글, 허용 모양 이름 또는 None)]. 코드 자리는 `code=` 인자 또는 둘째 위치 인자다."""
    parents, found = parents_of(tree), []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", getattr(node.func, "attr", ""))
        if not (name.endswith("Failure") or name == "make_failure"):
            continue
        value = next((keyword.value for keyword in node.keywords if keyword.arg == "code"), None)
        if value is None and len(node.args) >= 2:
            value = node.args[1]
        if value is None:
            continue
        kind = kind_of(value)
        if isinstance(value, ast.Name) and value.id in ALLOWED_NAMES:
            function = node
            while function in parents and not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function = parents[function]
            kind = kind if name_origin_ok(function if isinstance(function, ast.FunctionDef) else None, value.id) else None
        found.append((node.lineno, name, ast.unparse(value)[:60], kind))
    return found


class CopyOnlyOnClickRuleTest(unittest.TestCase):
    def test_copy_diagnostics_is_referred_to_from_exactly_one_place_and_only_inside_a_click_handler(self):
        found = {}
        for path in sorted(SRC.rglob("*.py")):
            for line, inside in copy_references(ast.parse(path.read_text(encoding="utf-8"))):
                found[f"{path.name}:{line}"] = inside
        self.assertEqual(len(found), 1, found)
        self.assertEqual(list(found)[0].split(":")[0], "screens.py")
        self.assertTrue(all(found.values()), found)

    def test_the_rule_itself_tells_a_click_handler_from_an_automatic_call_an_alias_or_another_signal(self):
        inside = lambda source: [flag for _line, flag in copy_references(ast.parse(source))]
        self.assertEqual(inside("def build(shell):\n    button.clicked.connect(lambda _=False: shell.copy_diagnostics())\n"), [True])
        self.assertEqual(inside("def build(shell):\n    button.clicked.connect(shell.copy_diagnostics)\n"), [True])
        self.assertEqual(inside("def build(shell):\n    button.clicked.connect(lambda _=False: None)\n    shell.copy_diagnostics()\n"), [False])
        self.assertEqual(inside("def build(shell):\n    button.clicked.connect(lambda _=False: None)\n    (lambda: shell.copy_diagnostics())()\n"), [False])
        self.assertEqual(inside("def build(shell):\n    fn = shell.copy_diagnostics\n    button.clicked.connect(lambda _=False: fn())\n"), [False])               # 이름만 붙여 두었다가 부르는 길도 걸린다
        self.assertEqual(inside("def build(shell):\n    window.changed.connect(lambda: shell.copy_diagnostics())\n"), [False])                                      # 눌림이 아닌 다른 신호에 물리는 것도 걸린다
        self.assertEqual(inside("def build(shell):\n    QTimer.singleShot(0, lambda: shell.copy_diagnostics())\n"), [False])
        self.assertEqual(inside("def copy_diagnostics(self):\n    '''copy_diagnostics 를 설명하는 글'''\n    return 1\n"), [])                                                  # 정의와 글 속 이름은 가리킴이 아니다


class FailureCodeOriginRuleTest(unittest.TestCase):
    def test_every_failure_code_in_the_ui_is_a_constant_a_service_code_or_an_exception_class_name(self):
        rows = []
        for path in sorted(UI.rglob("*.py")):
            rows += [(path.name,) + row for row in failure_sites(ast.parse(path.read_text(encoding="utf-8")))]
        self.assertGreater(len(rows), 80, "코드 자리를 못 찾았다 — 이 시험의 찾기 규칙이 깨졌다(만든 날 89곳: 상수 49·`….code` 14·변수 11·예외 클래스 이름 10·감싼 것 3·`getattr` 2)")
        self.assertEqual([row for row in rows if row[4] is None], [])

    def test_the_rule_itself_flags_user_text_in_the_code_place_and_lets_the_program_made_names_pass(self):
        flagged = {
            "블로그 이름 변수": "def f(blog_name):\n    raise BlogFailure('x', code=blog_name, kind='io')\n",
            "말 속 글": "def f(slots):\n    raise DraftFailure('x', code=slots.get('항목', ''))\n",
            "만든 글": "def f(title):\n    raise JobFailure('x', code=f'E_{title}')\n",
            "변수 code 에 사용자 값": "def f(slots):\n    code = str(slots.get('항목', ''))\n    raise DraftFailure('x', code=code)\n",
            "둘째 위치 인자": "def f(title):\n    raise JobFailure('x', title)\n",
            "빈 인자의 변수": "def f():\n    raise JobFailure('x', code=value)\n",
        }
        for label, source in flagged.items():
            self.assertTrue([row for row in failure_sites(ast.parse(source)) if row[3] is None], label)
        passed = {
            "상수": "raise BlogFailure('x', code='DATA_DIR_NOT_FOUND', kind='io')\n",
            "예외 클래스 이름": "def f(error):\n    return JobFailure('x', code=type(error).__name__)\n",
            "서비스 코드": "def f(error):\n    return ServiceFailure('x', code=error.code)\n",
            "getattr 코드": "def f(failure):\n    return JobFailure('x', code=getattr(failure, 'code', ''))\n",
            "변수 code(인자)": "def f(code):\n    return JobFailure('x', code=code)\n",
            "변수 code(허용 대입)": "def f(error):\n    code = str(getattr(error, 'code', '') or '')\n    return DraftFailure('x', code=code)\n",
            "가림으로 감싼 코드": "def f(failure):\n    return JobFailure('x', code=display_text(getattr(failure, 'code', '') or '', 80))\n",
            "상수 이름": "def f():\n    return JobFailure('x', CODE)\n",
        }
        for label, source in passed.items():
            rows = failure_sites(ast.parse(source))
            self.assertTrue(rows, label)
            self.assertEqual([row for row in rows if row[3] is None], [], label)


if __name__ == "__main__":
    unittest.main()
