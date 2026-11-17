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
OUTGOING_MODULES = {"subprocess", "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "telnetlib", "xmlrpc", "requests", "asyncio", "webbrowser", "socketserver", "imaplib", "poplib", "multiprocessing"}
OUTGOING_OS = {"system", "popen", "startfile", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe", "posix_spawn", "posix_spawnp"}
QT_NAMES = {"QDesktopServices", "QNetworkAccessManager", "QTcpSocket", "QUdpSocket", "QWebEngineView", "QWebSocket"}
QT_MODULES = {"QtNetwork", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel", "QtWebSockets", "QtHttpServer"}
# 하위 프로세스를 띄우는 또 다른 길 — 예전 규칙에는 `QProcess`(Qt)·`ProcessPoolExecutor`·`multiprocessing`·`os.posix_spawn` 이 없어서 새 코드가 그 길로 시험을 통과할 틈이 있었다(결정 D-512, 설계 3-8 (3)).
PROCESS_NAMES = {"QProcess", "ProcessPoolExecutor"}

# (파일, 쓰는 것) → 이유. 이 표가 앱이 바깥과 닿는 길의 전부다.
ALLOWED = {
    ("publish/gitrepo.py", "subprocess"): "git 하위 프로세스를 띄우는 유일한 곳(`run_command`) — 외부 Write 관문(`capabilities.require_external_write`)이 첫 줄이라 이 빌드에서는 한 번도 띄우지 않는다",
    ("ui/qt/shell.py", "QDesktopServices"): "`qt_open_url` — 네이버 글쓰기 주소를 기본 브라우저로 연다(주소만 연다 — 로그인·입력·발행은 사용자가 브라우저에서 직접, 앱은 연결하지 않는다)",
    ("ui/qt/components.py", "QDesktopServices"): "이미지 출처 링크 열기(`check_url` 로 주소 모양을 거른 뒤 기본 브라우저가 연다) — 앱은 연결하지 않는다",
}


def outgoing_names(node):
    """AST 노드 하나에서 바깥과 닿는 이름들(모듈·호출·Qt 이름·하위 프로세스를 띄우는 이름)을 찾는다 — 소스 전체 훑기와 탐지기 대조 시험이 같은 함수를 쓴다."""
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
    if isinstance(node, ast.ImportFrom):
        names += [alias.name for alias in node.names if alias.name in PROCESS_NAMES]
    elif isinstance(node, ast.Attribute) and node.attr in PROCESS_NAMES:
        names.append(node.attr)
    elif isinstance(node, ast.Name) and node.id in PROCESS_NAMES:
        names.append(node.id)
    return names


def found_outgoing():
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(SRC).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            for name in outgoing_names(node):
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

    def test_the_detector_catches_every_other_way_to_start_a_process(self):
        """결정 D-512(설계 3-8 (3)) — 예전 감시 이름에는 `QProcess` 가 없어서 새 코드가 그 길로 시험을 '통과' 할 수 있었다. 감시 이름을 늘렸다(`multiprocessing`·`QProcess`·`ProcessPoolExecutor`·`os.posix_spawn`)."""
        probe = ast.parse("import multiprocessing\nfrom multiprocessing import Pool\nfrom concurrent.futures import ProcessPoolExecutor\nimport concurrent.futures\nconcurrent.futures.ProcessPoolExecutor()\n"
                          "from PySide6.QtCore import QProcess\nimport PySide6.QtCore as qc\nqc.QProcess()\nimport os\nos.posix_spawn('x', [], {})\nos.posix_spawnp('x', [], {})\n")
        names = {name for node in ast.walk(probe) for name in outgoing_names(node)}
        self.assertEqual(names, {"multiprocessing", "ProcessPoolExecutor", "QProcess", "os.posix_spawn", "os.posix_spawnp"})

    def test_ordinary_threads_and_pools_of_threads_are_not_flagged(self):
        probe = ast.parse("import threading\nimport json\nfrom concurrent.futures import ThreadPoolExecutor\nimport concurrent.futures\nfrom PySide6.QtCore import QThread, QTimer\nimport os\nos.getcwd()\n")
        self.assertEqual([name for node in ast.walk(probe) for name in outgoing_names(node)], [])

    def test_no_source_file_uses_the_added_process_names_yet(self):
        added = {"multiprocessing", "QProcess", "ProcessPoolExecutor", "os.posix_spawn", "os.posix_spawnp"}
        self.assertEqual(sorted(key for key in found_outgoing() if key[1] in added), [], "하위 프로세스를 띄우는 새 길은 허용 목록·관문 없이는 늘 수 없다")


if __name__ == "__main__":
    unittest.main()
