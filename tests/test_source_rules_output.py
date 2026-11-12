"""소스 규칙 시험 — 비밀이 나갈 수 있는 출구(출력·로그·추적)와 가리기 규칙이 **공통 경계 한 곳**에만 있고, 새 우회가 생기면 바로 빨개진다(PCSEC1 H1).

지키는 것(AST 로 `src/chanceblog_desktop/` 전체를 읽는다 — 허용 목록은 한 줄마다 이유와 함께 못박고 '목록과 같음'을 단언한다. 새 `print` 가 생기면 목록에 없어서 빨개지고, 목록의 줄이 사라지면 낡은 줄이 남아서 빨개진다):
  1) 직접 출력: `print(` · `sys.stdout.write`·`sys.stderr.write` · `os.write(1|2, …)` · `sys.__excepthook__` · 표준 출력·오류 스트림 이름(`sys.stdout`·`sys.stderr`) 언급 · 훅·스트림을 바꾸는 대입 ·
     `logging`·`traceback`·`faulthandler` 가져오기는 경계(`security/boundary.py`)와 아래 허용 목록 밖에 없다. 허용된 `print` 는 **인자 식까지** 못박는다(`print(mask_block(text))` 가 `print(text)` 로 바뀌면 빨개진다).
  2) 가리기 규칙은 `security/` 안에만 있다: `[가림` 표지 글자열을 만들거나 비밀 이름 낱말을 정규식 리터럴로 가진 `re.*` 호출이 밖에 없다(밖의 한 곳은 화면의 고정 라벨이라 가리기가 아니다).
  3) 화면 쪽은 `security.mask.safe_detail` 을 `ui/core/text.py` 의 `display_text` 한 곳에서만 부른다(그 밖의 `security.mask` 가져오기는 감지·미리보기용으로 허용 목록에 이유가 있다).
  4) 오류 렌더링(`errors/render.py`)은 슬롯 값을 문구에 넣기 직전에 보안 모듈의 `mask` 를 거친다.
이 시험 자체도 합성 소스로 시험한다(어기는 소스가 실제로 걸리는지).
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "chanceblog_desktop"
BOUNDARY = "security/boundary.py"                                                    # 이 파일은 경계 자신이라 모든 규칙에서 빠진다

STREAM_WRITES = {"sys.stdout.write", "sys.stderr.write", "sys.__stdout__.write", "sys.__stderr__.write"}
STREAM_NAMES = {"sys.stdout", "sys.stderr", "sys.__stdout__", "sys.__stderr__"}
HOOK_TARGETS = {"sys.excepthook", "threading.excepthook", "sys.unraisablehook", "sys.stdout", "sys.stderr"}
FORBIDDEN_IMPORTS = {"logging", "traceback", "faulthandler"}
SECRET_WORDS = re.compile(r"(?i)password|passwd|secret|token|api.{0,6}key|authorization|cookie|credential|bearer")             # `api[_-]?key` 처럼 정규식 기호가 낀 모양도 잡는다
REGEX_FUNCTIONS = {"compile", "sub", "subn", "search", "match", "fullmatch", "findall", "finditer", "split"}

# (파일, 함수, 종류, 내용) → 이유. 종류: print(내용 = 호출 전체) · stream-name(내용 = 이름) · hook-assign(내용 = 대입 대상) · attr(내용 = 속성)
ALLOWED_OUTPUT = {
    ("service/cli.py", "say", "print", "print(mask_block(text), file=stream)"): "명령줄의 일반 출력 — 글 전체를 `mask_block`(경계) 으로 가린 뒤 낸다",
    ("service/cli.py", "main", "print", "print(mask_block(text), file=err, flush=True)"): "공개 확인을 기다리는 진행 안내 — `mask_block`(경계)을 거친다",
    ("service/cli.py", "main", "print", "print(json.dumps(_mask_deep({'ok': output.code == 0, 'command': command, 'data': output.data}), ensure_ascii=False, indent=2), file=out)"):
        "`--json` 출력 — 값 속 모든 글을 `_mask_deep`(경계)으로 가린 뒤 JSON 으로 만든다",
    ("service/cli.py", "_report_error", "print", "print(json.dumps(_mask_deep({'ok': False, 'command': command, 'error': _error_payload(error)}), ensure_ascii=False, indent=2), file=out)"):
        "`--json` 오류 출력 — `_mask_deep`(경계)을 거친다",
    ("service/cli.py", "_report_error", "print", "print(mask_block('\\n'.join(_error_text(error, verbose))), file=err)"): "오류 출력 — `mask_block`(경계)을 거친다",
    ("service/cli.py", "main", "stream-name", "sys.stdout"): "스트림을 주입하지 않았을 때의 기본 출력 — 진짜 실행에서는 진입점이 깐 경계 래퍼다",
    ("service/cli.py", "main", "stream-name", "sys.stderr"): "스트림을 주입하지 않았을 때의 기본 오류 출력 — 진짜 실행에서는 경계 래퍼다",
    ("ui/launcher.py", "error", "print", "print(USAGE_ERROR, USAGE_LINE, USAGE_HINT, sep='\\n', file=sys.stderr)"): "사용법 오류 — 입력한 값이 없는 고정 문장 셋뿐이다(값을 되풀이하지 않는다)",
    ("ui/launcher.py", "error", "stream-name", "sys.stderr"): "위 고정 문장의 출력 자리(진짜 실행에서는 경계 래퍼)",
    ("ui/launcher.py", "main", "print", "print(problem, file=out)"): "릴리스 버전을 못 읽을 때의 고정 안내(`release_problem` — 사용자 값 없음)",
    ("ui/launcher.py", "main", "print", "print(NEEDS_PYSIDE6, file=out)"): "PySide6 가 없을 때의 고정 안내 상수",
    ("ui/launcher.py", "main", "stream-name", "sys.stdout"): "`out` 을 주입하지 않았을 때의 기본 출력(진짜 실행에서는 경계 래퍼)",
    ("ui/core/app_state.py", "report_unexpected", "print", "print(unexpected_line(kind, value), file=target)"): "화면의 처리하지 못한 예외 한 줄 — `unexpected_line` 이 `display_text`(가리기)와 경로 지우기를 거친 짧은 글이다",
    ("ui/core/app_state.py", "report_unexpected", "stream-name", "sys.stderr"): "위 한 줄의 기본 출력 자리(진짜 실행에서는 경계 래퍼)",
    ("ui/qt/app.py", "hook", "attr", "sys.__excepthook__"): "Ctrl+C(KeyboardInterrupt)는 기본 훅에 넘긴다 — 기본 훅은 `sys.stderr`(진짜 실행에서는 경계 래퍼)에 쓰고 Ctrl+C 추적에는 값 글이 없다",
    ("ui/qt/app.py", "run", "hook-assign", "sys.excepthook"): "화면의 한 줄 예외 훅(`make_excepthook`)을 창이 만들어진 뒤 건다 — 한 줄은 `unexpected_line` 이 가린 글이고 추적은 내지 않는다",
}
# (파일, 종류, 내용) → 이유. 가리기 규칙이 `security/` 밖에 있는 곳.
ALLOWED_RULES_OUTSIDE = {
    ("ui/core/draft_text.py", "marker", "[가림]"): "화면에 보이는 고정 라벨('가려진 자리') — 비밀을 가리는 규칙이 아니라 화면 문구다",
}
# 화면 쪽에서 `security.mask` 의 `safe_detail` 이 아닌 다른 이름을 가져오는 곳 → 이유
ALLOWED_UI_MASK_IMPORTS = {
    ("ui/adapters.py", "mask"): "서비스 오류의 슬롯 값을 문구에 넣기 전에 한 번 더 가린다(오류 렌더링도 같은 일을 한다 — 겹쳐도 같다)",
    ("ui/core/draft_rules.py", "has_key_shape"): "초안 글에 키 모양이 있는지 **감지**(복사 관문) — 화면에 글을 내는 일이 아니다",
    ("ui/core/draft_rules.py", "mask"): "감지한 자리의 앞부분을 보이려고 가린 모양과 견준다 — 보이는 글은 `shown`(= `display_text`)을 거친다",
    ("ui/core/app_state.py", "_strip_invisible"): "경로를 보이지 않는 글자로 쪼개 지우기를 피하는 것을 막으려고 먼저 정리한다(가리기는 `display_text`)",
}


def parents_of(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def function_of(node, parents):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return ""


def output_sites(source, rel):
    """한 소스의 직접 출력·훅 대입·금지 가져오기 → [(파일, 함수, 종류, 내용)]."""
    tree = ast.parse(source)
    parents = parents_of(tree)
    found = []
    for node in ast.walk(tree):
        where = function_of(node, parents)
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name == "print":
                found.append((rel, where, "print", ast.unparse(node)))
            elif name in STREAM_WRITES:
                found.append((rel, where, "stream-write", name))
            elif name == "os.write" and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in (1, 2):
                found.append((rel, where, "stream-write", f"os.write({node.args[0].value}, …)"))
        elif isinstance(node, ast.Attribute):
            text = ast.unparse(node)
            if text in STREAM_NAMES:
                found.append((rel, where, "stream-name", text))
            elif text == "sys.__excepthook__":
                found.append((rel, where, "attr", text))
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                text = ast.unparse(target)
                if text in HOOK_TARGETS:
                    found.append((rel, where, "hook-assign", text))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    found.append((rel, where, "import", alias.name))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] in FORBIDDEN_IMPORTS:
            found.append((rel, where, "import", node.module))
    return found


def rule_sites(source, rel):
    """한 소스에서 가림 표지 글자열을 만들거나 비밀 이름 낱말을 정규식 리터럴로 가진 `re.*` 호출 → [(파일, 종류, 내용)]. (독스트링은 뺀다.)"""
    tree = ast.parse(source)
    parents = parents_of(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "[가림" in node.value:
            parent = parents.get(node)
            is_doc = isinstance(parent, ast.Expr) and isinstance(parents.get(parent), (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            if not is_doc:
                found.append((rel, "marker", node.value if len(node.value) <= 40 else node.value[:40]))
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name.startswith("re.") and name.split(".", 1)[1] in REGEX_FUNCTIONS and node.args:
                first = ast.unparse(node.args[0])
                if SECRET_WORDS.search(first):
                    found.append((rel, "regex", first[:60]))
    return found


def mask_imports(source):
    """한 소스에서 `security.mask` 에서 가져오는 이름들."""
    tree = ast.parse(source)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("security.mask"):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and (node.module or "") in ("security", "..security", "...security"):
            names += [alias.name for alias in node.names if alias.name == "safe_detail"]
    return names


def sources():
    for path in sorted(SRC.rglob("*.py")):
        yield path.relative_to(SRC).as_posix(), path.read_text(encoding="utf-8")


class DirectOutputTest(unittest.TestCase):
    def test_the_whole_source_tree_is_scanned(self):
        files = [rel for rel, _text in sources()]
        self.assertGreater(len(files), 150)
        self.assertIn(BOUNDARY, files)
        self.assertIn("service/cli.py", files)
        self.assertIn("ui/qt/app.py", files)

    def test_direct_output_and_hook_assignments_outside_the_boundary_are_exactly_the_allowed_list(self):
        found = set()
        for rel, text in sources():
            if rel != BOUNDARY:
                found.update(output_sites(text, rel))
        allowed = set(ALLOWED_OUTPUT)
        self.assertEqual(sorted(found - allowed), [], "허용 목록에 없는 직접 출력·훅 대입이 생겼다 — 경계(security/boundary.py)를 거치게 하거나 이유와 함께 목록에 더한다")
        self.assertEqual(sorted(allowed - found), [], "허용 목록에 낡은 줄이 남았다 — 코드가 바뀌었으면 목록도 바꾼다")

    def test_every_allowed_site_has_a_real_reason(self):
        for site, reason in ALLOWED_OUTPUT.items():
            with self.subTest(site=site[:3]):
                self.assertGreaterEqual(len(reason), 12, "이유는 한 문장으로 적는다")
        for site, reason in ALLOWED_RULES_OUTSIDE.items():
            self.assertGreaterEqual(len(reason), 12, site)
        for site, reason in ALLOWED_UI_MASK_IMPORTS.items():
            self.assertGreaterEqual(len(reason), 12, site)

    def test_every_allowed_print_masks_or_prints_a_fixed_text(self):
        masking = ("mask_block(", "_mask_deep(", "unexpected_line(")
        fixed = {"print(USAGE_ERROR, USAGE_LINE, USAGE_HINT, sep='\\n', file=sys.stderr)", "print(problem, file=out)", "print(NEEDS_PYSIDE6, file=out)"}
        for (rel, _function, kind, text), _reason in ALLOWED_OUTPUT.items():
            if kind == "print":
                with self.subTest(text=text[:50]):
                    self.assertTrue(any(word in text for word in masking) or text in fixed, "허용된 print 는 가리기 함수를 거치거나 값 없는 고정 글이어야 한다")

    def test_the_rule_itself_catches_new_direct_output_in_synthetic_sources(self):
        cases = {
            "print": "def f(x):\n    print(x)\n", "stream-write": "import sys\ndef f(x):\n    sys.stderr.write(x)\n", "stream-write-2": "import os\ndef f(x):\n    os.write(2, x)\n",
            "stream-name": "import sys\nout = sys.stdout\n", "attr": "import sys\ndef f(a, b, c):\n    sys.__excepthook__(a, b, c)\n", "hook-assign": "import sys\nsys.excepthook = lambda *a: None\n",
            "import-logging": "import logging\n", "import-traceback": "import traceback\n", "from-logging": "from logging import getLogger\n", "import-faulthandler": "import faulthandler\n",
            "stdout-assign": "import sys\nsys.stdout = None\n",
        }
        for label, source in cases.items():
            with self.subTest(label=label):
                self.assertTrue(output_sites(source, "x.py"), f"{label}: 이 소스는 걸려야 한다")
        for label, source in {"fd 변수": "import os\ndef f(fd, x):\n    os.write(fd, x)\n", "평범한 코드": "def f(x):\n    return x + 1\n", "다른 write": "def f(p):\n    p.write('x')\n"}.items():
            with self.subTest(label=label):
                self.assertEqual(output_sites(source, "x.py"), [], f"{label}: 걸리면 안 된다")

    def test_the_synthetic_source_of_the_changed_print_is_not_in_the_allowed_list(self):
        changed = output_sites("def say(stream, text):\n    print(text, file=stream)\n", "service/cli.py")
        self.assertEqual(len(changed), 1)
        self.assertNotIn(changed[0], ALLOWED_OUTPUT, "`print(mask_block(text))` 가 `print(text)` 로 바뀐 것은 허용 목록과 달라야 한다")


class MaskRulesLiveInSecurityTest(unittest.TestCase):
    def test_masking_rules_outside_the_security_package_are_exactly_the_allowed_list(self):
        found = set()
        for rel, text in sources():
            if not rel.startswith("security/"):
                found.update(rule_sites(text, rel))
        allowed = set(ALLOWED_RULES_OUTSIDE)
        self.assertEqual(sorted(found - allowed), [], "`security/` 밖에 가리기 규칙(가림 표지·비밀 이름 정규식)이 생겼다 — 경계(`mask`)를 부르도록 바꾼다")
        self.assertEqual(sorted(allowed - found), [], "허용 목록에 낡은 줄이 남았다")

    def test_the_rule_catches_a_hand_made_masker_in_a_synthetic_source(self):
        marker = "def hide(text):\n    return text.replace('abc', '[가림: 값]')\n"
        regex = "import re\nPATTERN = re.compile(r'(?i)(api[_-]?key=)\\S+')\n"
        regex_sub = "import re\ndef hide(text):\n    return re.sub(r'password=\\S+', 'x', text)\n"
        for label, source in (("표지", marker), ("정규식", regex), ("정규식 sub", regex_sub)):
            with self.subTest(label=label):
                self.assertTrue(rule_sites(source, "service/x.py"), f"{label}: 걸려야 한다")
        self.assertEqual(rule_sites("import re\nWORDS = re.compile(r'[가-힣]+')\n", "service/x.py"), [])
        self.assertEqual(rule_sites('def f():\n    """설명에 [가림: 값] 표지가 나온다."""\n    return 1\n', "service/x.py"), [], "독스트링은 코드가 아니다")

    def test_the_ui_calls_safe_detail_only_through_display_text(self):
        found = set()
        for rel, text in sources():
            if rel.startswith("ui/"):
                for name in mask_imports(text):
                    found.add((rel, name))
        self.assertIn(("ui/core/text.py", "safe_detail"), found, "화면 쪽에서 `safe_detail` 을 가져오는 곳은 `display_text` 안의 한 곳이다")
        direct = sorted(item for item in found if item[1] == "safe_detail" and item[0] != "ui/core/text.py")
        self.assertEqual(direct, [], "화면 쪽은 `safe_detail` 을 직접 가져오지 않는다 — `ui/core/text.py` 의 `display_text` 를 쓴다")
        others = {item for item in found if item[1] != "safe_detail"}
        self.assertEqual(sorted(others - set(ALLOWED_UI_MASK_IMPORTS)), [], "화면 쪽에 허용 목록에 없는 `security.mask` 가져오기가 생겼다")
        self.assertEqual(sorted(set(ALLOWED_UI_MASK_IMPORTS) - others), [], "허용 목록에 낡은 줄이 남았다")
        text_source = (SRC / "ui" / "core" / "text.py").read_text(encoding="utf-8")
        tree = ast.parse(text_source)
        display = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "display_text")
        inner = [node for node in ast.walk(display) if isinstance(node, ast.ImportFrom)]
        self.assertEqual([(item.module, [alias.name for alias in item.names]) for item in inner], [("security.mask", ["safe_detail"])], "`display_text` 가 보안 모듈의 `safe_detail` 을 부르는 유일한 화면 쪽 문")

    def test_the_view_modules_use_display_text_not_their_own_masking(self):
        names = {"app_state.py": "shown", "blog_form.py": "shown", "board_view.py": "_shown", "candidate_rules.py": "shown", "draft_rules.py": "shown", "keys_view.py": "_shown", "settings_view.py": "_shown"}
        for name, function in names.items():
            with self.subTest(file=name):
                tree = ast.parse((SRC / "ui" / "core" / name).read_text(encoding="utf-8"))
                node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == function)
                calls = [ast.unparse(call.func) for call in ast.walk(node) if isinstance(call, ast.Call)]
                self.assertEqual(calls, ["display_text"], f"{function} 는 `display_text` 만 부른다")
        notify = ast.parse((SRC / "ui" / "core" / "notify.py").read_text(encoding="utf-8"))
        offer = next(node for node in ast.walk(notify) if isinstance(node, ast.FunctionDef) and node.name == "offer")
        self.assertIn("display_text", [ast.unparse(call.func) for call in ast.walk(offer) if isinstance(call, ast.Call)], "안내(토스트)가 나가는 한 지점도 같은 가리기를 거친다")


class ErrorRenderingTest(unittest.TestCase):
    def test_slot_values_are_masked_by_the_security_module_before_they_enter_a_sentence(self):
        tree = ast.parse((SRC / "errors" / "render.py").read_text(encoding="utf-8"))
        masked = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_masked")
        imports = [(node.module, [alias.name for alias in node.names]) for node in ast.walk(masked) if isinstance(node, ast.ImportFrom)]
        self.assertEqual(imports, [("security.mask", ["mask"])])
        fill = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_fill")
        calls = [ast.unparse(node.func) for node in ast.walk(fill) if isinstance(node, ast.Call)]
        self.assertIn("_masked", calls, "`_fill` 은 슬롯 값을 `_masked` 로 가린 뒤 넣는다")
        order = [index for index, text in enumerate(ast.unparse(fill).split("\n")) if "clean_slot(_masked(" in text]
        self.assertTrue(order, "가리기가 먼저, 자르기(`clean_slot`)가 나중이다")


if __name__ == "__main__":
    unittest.main()
