"""'밖으로 나가는 호출이 새로 생기면 빨개진다' — 소스 규칙 시험(PCSEC1 H3 넷째 겹의 정적 짝, 보안 조사 SECAUDIT 의 '밖으로 나가는 호출' 전수 위에 세운다).

`src/chanceblog_desktop/` 전체(vendor 제외)에서 바깥과 닿는 모듈·호출(`subprocess`·`socket`·`ssl`·`http`·`urllib.request`·`ftplib`·`smtplib`·`telnetlib`·`xmlrpc`·`requests`·`asyncio`·`webbrowser`·`os.system`·
`os.popen`·`os.spawn*`·`os.exec*`·`os.startfile`·Qt 의 `QDesktopServices`·`PySide6.QtNetwork` 와 PySide6 의 웹 모듈)을 사용하는 곳을 AST 로 모아 **아래 허용 목록과 같음**을 단언한다. 목록에 없는 곳이 생기면 이 시험이 빨개지고,
목록의 곳이 사라져도 빨개진다(낡은 허용을 남기지 않는다). 허용마다 이유가 있다 — 바깥에 **쓰는** 곳은 `subprocess`(관문 안) 하나뿐이다.
`urllib.parse`(주소를 글자로 쪼개는 일)는 연결이 아니다 — 어디서든 쓸 수 있다.
"""
import ast
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import service_support as ss  # noqa: E402

SRC = ss.ROOT / "src" / "chanceblog_desktop"
OUTGOING_MODULES = {"subprocess", "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "telnetlib", "xmlrpc", "requests", "asyncio", "webbrowser", "socketserver", "imaplib", "poplib"}
OUTGOING_OS = {"system", "popen", "startfile", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe"}
QT_NAMES = {"QDesktopServices", "QNetworkAccessManager", "QTcpSocket", "QUdpSocket", "QWebEngineView", "QWebSocket"}
QT_MODULES = {"QtNetwork", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel", "QtWebSockets", "QtHttpServer"}

# (파일, 쓰는 것) → 이유. 이 표가 앱이 바깥과 닿는 길의 전부다.
ALLOWED = {
    ("publish/gitrepo.py", "subprocess"): "git 하위 프로세스를 띄우는 유일한 곳(`run_command`) — 외부 Write 관문(`capabilities.require_external_write`)이 첫 줄이라 이 빌드에서는 한 번도 띄우지 않는다",
    ("ui/qt/shell.py", "QDesktopServices"): "`qt_open_url` — 네이버 글쓰기 주소를 기본 브라우저로 연다(주소만 연다 — 로그인·입력·발행은 사용자가 브라우저에서 직접, 앱은 연결하지 않는다)",
    ("ui/qt/components.py", "QDesktopServices"): "이미지 출처 링크 열기(`check_url` 로 주소 모양을 거른 뒤 기본 브라우저가 연다) — 앱은 연결하지 않는다",
}


def found_outgoing():
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(SRC).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in OUTGOING_MODULES and alias.name != "urllib.parse":
                        names.append(top)
                    if alias.name.split(".")[-1] in QT_MODULES:
                        names.append(alias.name.split(".")[-1])
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                top = module.split(".")[0]
                if node.level == 0 and top in OUTGOING_MODULES and module != "urllib.parse":
                    if not (top == "urllib" and all(alias.name == "parse" for alias in node.names)):
                        names.append(top)
                if module.split(".")[-1] in QT_MODULES:
                    names.append(module.split(".")[-1])
                names += [alias.name for alias in node.names if alias.name in QT_NAMES or alias.name in QT_MODULES]
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in OUTGOING_OS:
                names.append(f"os.{node.attr}")
            elif isinstance(node, ast.Name) and node.id in QT_NAMES:
                names.append(node.id)
            for name in names:
                found.setdefault((rel, name), []).append(getattr(node, "lineno", 0))
    return found


class OutgoingCallSitesTest(unittest.TestCase):
    def test_the_places_that_touch_the_outside_are_exactly_the_allowed_list(self):
        found = found_outgoing()
        self.assertEqual(sorted(found), sorted(ALLOWED), "바깥과 닿는 코드가 허용 목록과 다르다 — 새로 생겼거나 사라졌다. 새로 생긴 곳은 외부 Write 관문·이유를 갖추고 이 표에 더한다")

    def test_every_allowance_has_a_real_reason(self):
        for key, reason in ALLOWED.items():
            self.assertGreater(len(reason), 20, key)

    def test_only_one_allowed_place_can_write_to_the_outside_and_it_sits_behind_the_gate(self):
        writers = [key for key in ALLOWED if key[1] in ("subprocess", "socket", "http", "urllib", "ssl")]
        self.assertEqual(writers, [("publish/gitrepo.py", "subprocess")])

    def test_urllib_parse_is_the_only_urllib_use_outside_the_allowed_list(self):
        for path in sorted(SRC.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "urllib":
                    self.assertEqual(node.module, "urllib.parse", f"{path.name}:{node.lineno} — urllib 에서는 주소를 쪼개는 parse 만 쓴다")

    def test_the_detector_would_catch_a_new_outgoing_call(self):
        """대조 — 탐지기가 헛돌지 않는다: 합성 소스에서 같은 규칙으로 찾아 본다."""
        probe = ast.parse("import socket\nfrom http import client\nimport urllib.request\nimport urllib.parse\nfrom urllib.parse import quote\nimport os\nos.system('x')\nimport webbrowser\n")
        names = []
        for node in ast.walk(probe):
            if isinstance(node, ast.Import):
                names += [alias.name.split(".")[0] for alias in node.names if alias.name.split(".")[0] in OUTGOING_MODULES and alias.name != "urllib.parse"]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in OUTGOING_MODULES and node.module != "urllib.parse":
                names.append(node.module.split(".")[0])
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in OUTGOING_OS:
                names.append("os." + node.attr)
        self.assertEqual(sorted(names), ["http", "os.system", "socket", "urllib", "webbrowser"])


if __name__ == "__main__":
    unittest.main()
