"""'키에 대해 보이는 것은 다섯 가지뿐' — 소스 규칙 시험(PCSEC1 H2, 운영자 결정 2026-11-11).

키 화면·명령줄(`keys list`·`keys add`)·`--json`·`doctor`·연결 시험에 보이는 키 관련 정보는 **제공자 이름·항목 번호(Key Slot)·등록 여부·마지막 연결 시험·등록 시각**뿐이다. 키 원문도 일부 글자(끝 4자·앞부분·접두어·길이)도
다시 보이지 않는다. 이 시험은 `service/`·`ui/`·`security/` 의 소스에서 **비밀 값의 일부를 잘라 표시에 쓰는 코드**가 남지 않았음을 AST 로 확인한다(허용 목록은 이유와 함께 — 지금은 비어 있다):
  1) 끝 4자를 만들던 이름(`tail_hint`·`TAIL_MIN_LEN`·`TAIL_SHOWN`·`last4` 류)이 어디에도 없다.
  2) 사용자에게 나가는 글(설명 글·주석이 아닌 문자열)에 `끝 4자`·`****` 가 없다.
  3) 비밀 값을 가리키는 식(`reveal`·`secret`·`api_key`·`access_key`·`SecretBox`·`take()`)을 자르는(`[:n]`·`[-n:]`) 곳이 없다.
  4) 값을 꺼내는 `reveal(` 호출이 `service/`·`ui/` 에 없다(보관소 모듈 `security/keystore.py` 가 정의만 한다) — `SecretBox.take()` 는 화면 입력을 서비스로 넘기는 두 곳뿐이다.
화면 위젯 전수 훑기(가짜 키와 그 모든 네 글자 조각이 어느 위젯 글에도 없음)는 `tests/test_ui_qt_keys.py`(`key_leak_support.widget_hits`)가 그대로 지킨다.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import service_support as ss  # noqa: E402

SRC = ss.ROOT / "src" / "chanceblog_desktop"
FOLDERS = ("service", "ui", "security")
TAIL_NAMES = re.compile(r"(?i)tail_hint|TAIL_(?:MIN_LEN|SHOWN)|last_?4|last_?four|mask_?tail|tail_?4|head_?hint|prefix_?hint")
SECRET_EXPRESSION = re.compile(r"(?i)reveal|secret|api_?key|access_?key|SecretBox|\.take\(")
ALLOWED_TAKE = {("ui/core/keys.py"): "키 등록 흐름이 화면 입력(`SecretBox`)을 서비스 함수로 넘기려고 한 번 꺼낸다(표시하지 않는다)",
                ("ui/keys_adapter.py"): "어댑터가 `SecretBox` 를 서비스 함수의 인자로 한 번 꺼낸다(표시하지 않는다)"}


def files():
    for folder in FOLDERS:
        for path in sorted((SRC / folder).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path, ast.parse(path.read_text(encoding="utf-8"))


def docstring_nodes(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


class KeyDisplayRulesTest(unittest.TestCase):
    def test_no_name_in_the_ui_service_or_security_code_makes_a_tail_or_head_of_a_value(self):
        hits = []
        for path, tree in files():
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Name):
                    names.append(node.id)
                elif isinstance(node, ast.Attribute):
                    names.append(node.attr)
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                    names.append(node.name)
                elif isinstance(node, ast.arg):
                    names.append(node.arg)
                elif isinstance(node, ast.keyword) and node.arg:
                    names.append(node.arg)
                elif isinstance(node, ast.alias):
                    names.append(node.name)
                for name in names:
                    if TAIL_NAMES.search(name):
                        hits.append((path.relative_to(SRC).as_posix(), getattr(node, "lineno", 0), name))
        self.assertEqual(hits, [], "값의 끝·앞 일부를 만들던 이름이 남았다(PCSEC1 H2)")

    def test_no_text_that_reaches_the_user_mentions_a_tail_or_shows_stars_for_a_value(self):
        hits = []
        for path, tree in files():
            skip = docstring_nodes(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                    if "끝 4자" in node.value or "****" in node.value:
                        hits.append((path.relative_to(SRC).as_posix(), node.lineno, node.value[:40]))
        self.assertEqual(hits, [], "사용자에게 나가는 글에 '끝 4자'·'****' 가 있다(설명 글·주석은 괜찮다)")

    def test_nothing_cuts_a_piece_out_of_an_expression_that_holds_a_secret(self):
        hits = []
        for path, tree in files():
            for node in ast.walk(tree):
                if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice) and SECRET_EXPRESSION.search(ast.unparse(node.value)):
                    hits.append((path.relative_to(SRC).as_posix(), node.lineno, ast.unparse(node)[:60]))
                if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.UnaryOp) and isinstance(node.slice.op, ast.USub) and SECRET_EXPRESSION.search(ast.unparse(node.value)):
                    hits.append((path.relative_to(SRC).as_posix(), node.lineno, ast.unparse(node)[:60]))        # `value[-1]`
        self.assertEqual(hits, [], "비밀 값을 자르는 식이 있다")

    def test_the_secret_is_only_revealed_by_the_keystore_module_itself(self):
        calls, takes = [], set()
        for path, tree in files():
            rel = path.relative_to(SRC).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "reveal":
                        calls.append((rel, node.lineno))
                    if node.func.attr == "take":
                        takes.add(rel)
        self.assertEqual(calls, [], "`reveal(` 은 어디서도 부르지 않는다 — 값을 꺼내 표시에 쓸 길이 없다")
        self.assertEqual(sorted(takes), sorted(ALLOWED_TAKE), "`SecretBox.take()` 는 화면 입력을 서비스로 넘기는 허용 목록의 곳뿐이다")

    def test_the_allowances_each_have_a_reason(self):
        for key, reason in ALLOWED_TAKE.items():
            self.assertGreater(len(reason), 15, key)

    def test_the_rules_would_catch_what_they_forbid(self):
        """대조 — 규칙이 헛돌지 않는다: 합성 소스에서 같은 규칙으로 찾아 본다."""
        probe = ast.parse("def tail_hint(value):\n    return '****' + value[-4:]\nkey = fields.reveal('secret')[:4]\nshown = '끝 4자 ' + x\n")
        names = [node.name for node in ast.walk(probe) if isinstance(node, ast.FunctionDef) and TAIL_NAMES.search(node.name)]
        stars = [node.value for node in ast.walk(probe) if isinstance(node, ast.Constant) and isinstance(node.value, str) and ("****" in node.value or "끝 4자" in node.value)]
        cuts = [ast.unparse(node) for node in ast.walk(probe) if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice) and SECRET_EXPRESSION.search(ast.unparse(node.value))]
        self.assertEqual((len(names), len(stars), len(cuts)), (1, 2, 1))


# 값 객체 `Secret` 이 보관소 값 묶음에 값을 넘겨 주는 문 `into(값 묶음, 이름)` — `reveal(` 과 같은 효력이라(값이 사전으로 나간다) 같은 허용 목록 방식으로 막는다(재작업 1 권고-3, 안전 검증 S).
# 허용은 (파일, 함수) 쌍이다 — 서비스·화면·보안 소스 어디서든 이 이름을 부르거나 가리키거나 글자로 넘기는 곳은 이 한 곳뿐이다.
ALLOWED_INTO = {("service/connections.py", "attach_refresh_token"): "로그인이 받은 갱신용 값을 같은 보관소 값 묶음에 한 칸으로 더하는 유일한 곳 — 서비스 층이 값을 꺼내는 호출(`reveal`)을 하지 않으려고 값 객체가 사전에 직접 넣는 문이다"}


def scopes(tree):
    """(범위 이름, 그 안의 모든 노드) 들 — 범위는 맨 바깥 함수·메서드('클래스.메서드')이고 그 밖의 모듈 맨 위 줄은 '(모듈)' 이다."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, ast.walk(node)
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield f"{node.name}.{member.name}", ast.walk(member)
                else:
                    yield "(모듈)", ast.walk(member)
        else:
            yield "(모듈)", ast.walk(node)


def into_scopes(tree):
    """그 소스에서 `into` 를 쓰는 범위들 — 호출(`x.into(…)`)만이 아니라 가리키기(`f = x.into`)·글자로 꺼내기(`getattr(x, "into")`·`hasattr`)·가져오기(`from m import into`)·이름 자체도 센다."""
    found = set()
    for scope, nodes in scopes(tree):
        for node in nodes:
            if (isinstance(node, ast.Attribute) and node.attr == "into") or (isinstance(node, ast.Name) and node.id == "into") or (isinstance(node, ast.Constant) and node.value == "into") \
                    or (isinstance(node, ast.alias) and node.name == "into") or (isinstance(node, ast.keyword) and node.arg == "into") or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "into"):
                found.add(scope)
    return found


class SecretHandoverRuleTest(unittest.TestCase):
    """재작업 1 권고-3 — `Secret.into` 는 `reveal(` 금지 규칙(위 규칙 4)이 보지 않던 새 문이었다: `service/`·`ui/` 가 앞으로 `secret.into({}, "x")` 로 값을 꺼내도 규칙이 빨개지지 않았다."""

    def test_the_value_object_hands_its_value_over_only_where_the_allow_list_says(self):
        found = set()
        for path, tree in files():
            rel = path.relative_to(SRC).as_posix()
            found |= {(rel, scope) for scope in into_scopes(tree)}
        self.assertEqual(found, set(ALLOWED_INTO), "`into` 를 쓰는 곳이 허용 목록과 다르다 — 새로 생겼거나 사라졌다. 값을 꺼내는 길이라 `reveal(` 처럼 막는다")

    def test_the_allowance_has_a_reason_and_the_allowed_function_really_uses_it(self):
        for key, reason in ALLOWED_INTO.items():
            self.assertGreater(len(reason), 15, key)
        rel, function = next(iter(ALLOWED_INTO))
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        self.assertEqual({scope for scope in into_scopes(tree)}, {function}, "허용한 함수가 정말 이 문을 쓴다(낡은 허용을 남기지 않는다)")

    def test_the_rule_would_catch_every_shape_of_the_door(self):
        """대조 — 규칙이 헛돌지 않는다: 합성 소스에서 같은 함수로 찾아 본다(평범한 코드는 걸리지 않는다)."""
        shapes = {"호출": "def put(secret, values):\n    secret.into(values, 'x')\n", "가리키기": "def put(secret):\n    return secret.into\n", "글자로 꺼내기": "def put(secret, values):\n    getattr(secret, 'into')(values, 'x')\n",
                  "가져오기": "from m import into\n", "정의": "class Box:\n    def into(self, values, name):\n        pass\n", "이름 인자": "def go(**kw):\n    return kw\ngo(into=1)\n"}
        for label, source in shapes.items():
            with self.subTest(label=label):
                self.assertTrue(into_scopes(ast.parse(source)), label)
        for label, source in {"into 가 든 낱말": "def go(x):\n    return x.intolerance, 'into the woods', x.into_value\n", "그냥 코드": "import json\njson.dumps({'a': 1})\n"}.items():
            with self.subTest(label=label):
                self.assertEqual(into_scopes(ast.parse(source)), set(), label)


if __name__ == "__main__":
    unittest.main()
