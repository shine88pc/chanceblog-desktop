"""'밖으로 나가는 호출이 새로 생기면 빨개진다' — 소스 규칙 시험(PCSEC1 H3 넷째 겹의 정적 짝, 보안 조사 SECAUDIT 의 '밖으로 나가는 호출' 전수 위에 세운다).

`src/chanceblog_desktop/` 전체(vendor 제외)에서 바깥과 닿는 모듈·호출(`subprocess`·`socket`·`ssl`·`http`·`urllib.request`·`ftplib`·`smtplib`·`telnetlib`·`xmlrpc`·`requests`·`asyncio`·`webbrowser`·`os.system`·
`os.popen`·`os.spawn*`·`os.exec*`·`os.startfile`·Qt 의 `QDesktopServices`·`PySide6.QtNetwork` 와 PySide6 의 웹 모듈)을 사용하는 곳을 AST 로 모아 **아래 허용 목록과 같음**을 단언한다. 목록에 없는 곳이 생기면 이 시험이 빨개지고,
목록의 곳이 사라져도 빨개진다(낡은 허용을 남기지 않는다). 허용마다 이유가 있다 — 바깥에 **쓰는** 곳은 `subprocess`(관문 안) 하나뿐이다.
`urllib.parse`(주소를 글자로 쪼개는 일)는 연결이 아니다 — 어디서든 쓸 수 있다.

덧붙임(AS-S1 권고-6, D-611): 위 표는 '바깥으로 나가는' 길이다. 그 길을 **돌아서** 갈 수 있는 네이티브·동적 호출(`ctypes`·`winreg`·`msvcrt`·`pty`·`runpy`·`__import__`·`importlib.import_module`·`exec`·`eval`·
`import os as 별칭`·`from os import <위험 이름>`·`getattr(os, …)`)은 따로 `NATIVE_ALLOWED` 표(파일마다 이유)로 못박고, `vendor/` 안의 바깥 모듈도 `VENDOR_ALLOWED` 표로 못박는다. 감사가 합성 코드로 재현한 못 보는 모양
(`probe_scanner.py` 의 목록)이 모두 잡히고 지금 소스는 위반이 0 이다.

덧붙임(NET 갈래, D-735 — 운영자 확인 038 ①): 허용 목록을 **범주 표**로 쪼갰다(`ALLOWED_GIT_WRITE`·`ALLOWED_LOCAL_WORKER`·`ALLOWED_BROWSER`·`ALLOWED_NET_CLIENT`·`ALLOWED_LOOPBACK`) — 뒤 갈래가 같은 줄을 고쳐 병합 충돌을 내지 않고 **자기 범주 표에 한 줄**만 더하게 하려는 것이다.
`ALLOWED` 는 여섯 표의 합집합(키가 겹치지 않음을 시험이 확인)이고 '정확히 N곳' 단언은 그대로다(지금 8곳: 1 + 1 + 2 + 2 + 1 + 1 — BLOGGER 갈래가 루프백 한 줄을(D-771)·UPDATE U-4 가 설치 도구 한 줄을 더했다). 더 엄격해진 것: 접속·쓰기 범주의 이유 글에는 **관문 이름(`require_…`)** 이 들어 있어야 하고,
`http`·`ssl` 은 `net/client.py` 한 파일에만, `socket` 은 `net/loopback.py` 한 파일에만(지금 1곳) 허용되며 `urllib`(`parse` 말고) 항목과 그 밖의 하위 프로세스 항목은 여전히 허용 표에 없다.

덧붙임(UPDATE U-4, v1update4 — 설치 도구 어댑터, 결정 D-850 이상): 범주 표를 하나 더했다(`ALLOWED_UPDATE_SETUP` — 앱이 Inno Setup 을 띄우는 `update/apply.py` 의 `subprocess` **정확히 한 곳**). `ALLOWED` 는 여섯 표의 합집합이 되어 **정확히 N+1 곳**이고
(옛 단언을 지운 곳 없이 이 표만 더한다 — 이 표의 이유에도 관문 이름 `require_update_apply` 가 있어야 하고, 그 파일이 바깥과 닿는 이름은 `subprocess` 하나뿐임을 따로 못박는다), 하위 프로세스를 띄우는 허용은 둘에서 **셋**(git·글자 읽기 작업자·설치 도구)이 됐다.
"""
import ast
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import service_support as ss  # noqa: E402

SRC = ss.ROOT / "src" / "chanceblog_desktop"
OUTGOING_MODULES = {"subprocess", "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "telnetlib", "xmlrpc", "requests", "asyncio", "webbrowser", "socketserver", "imaplib", "poplib", "multiprocessing",
                    # AS-S1 2차 권고-3(D-619) — 같은 길의 안쪽 이름·옛 모듈: C 쪽 소켓·TLS·프로세스 모듈, 가져오기만 해도 브라우저를 여는 `antigravity`, 파이썬 3.10 의 `asyncore`·`smtpd`(3.12 에서 없어졌어도 3.10 칸이 돈다)
                    "_socket", "_ssl", "_multiprocessing", "antigravity", "asyncore", "smtpd"}
# BLOGGER 재작업 1(안전 검증 S 의 참고-13, D-780) — 이름 목록 밖이던 서버·바깥 모듈: 새 파일이 `wsgiref.simple_server` 로 모든 주소를 듣는 서버를 열어도 이 시험이 빨개지지 않았다. 표준 라이브러리의 서버·클라이언트(`wsgiref`·`nntplib`·`pydoc` 은 작은 웹 서버를 띄울 수 있다)와
# 흔한 바깥 라이브러리 이름이다 — 앱이 쓰는 의존성이 아니라서 소스에 하나라도 생기면 허용 목록 시험이 빨개진다(회귀 그물일 뿐, 일부러 숨기는 코드를 막는 방어가 아니다).
EXTRA_OUTGOING_MODULES = {"wsgiref", "nntplib", "pydoc", "urllib3", "httpx", "aiohttp", "websockets", "paramiko", "pycurl", "tornado", "twisted", "gevent", "grpc", "zmq", "flask", "fastapi", "uvicorn"}
OUTGOING_MODULES |= EXTRA_OUTGOING_MODULES
OUTGOING_OS = {"system", "popen", "startfile", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe", "posix_spawn", "posix_spawnp"}
QT_NAMES = {"QDesktopServices", "QNetworkAccessManager", "QTcpSocket", "QUdpSocket", "QWebEngineView", "QWebSocket"}
QT_MODULES = {"QtNetwork", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel", "QtWebSockets", "QtHttpServer"}
# 하위 프로세스를 띄우는 또 다른 길 — 예전 규칙에는 `QProcess`(Qt)·`ProcessPoolExecutor`·`multiprocessing`·`os.posix_spawn` 이 없어서 새 코드가 그 길로 시험을 통과할 틈이 있었다(결정 D-512, 설계 3-8 (3)).
PROCESS_NAMES = {"QProcess", "ProcessPoolExecutor"}
# 위 이름을 돌아서 부를 수 있는 길(AS-S1 권고-6, D-611) — 윈도 API 를 직접 부르는 모듈·가짜 터미널·다른 파일을 실행하는 모듈, 이름 없이 모듈을 가져오는 호출, 별칭·`getattr` 로 숨기는 `os`.
NATIVE_MODULES = {"ctypes", "winreg", "msvcrt", "pty", "runpy",
                  # AS-S1 2차 권고-3(D-619) — `os` 가 안에서 쓰는 운영체제 내장 모듈(`nt.system`·`posix.system`)·윈도 프로세스 API(`_winapi.CreateProcess`)·`subprocess` 가 쓰는 `_posixsubprocess`
                  "nt", "posix", "_winapi", "_posixsubprocess"}
GUARDED_NAMES = NATIVE_MODULES | {"__import__", "importlib.import_module", "exec", "eval", "os-alias", "getattr(os)", "getattr(builtins)", "sys.modules"}
BUILTINS_HOLDERS = {"builtins", "__builtins__"}                                  # `builtins.exec`·`__builtins__.__import__` 처럼 내장 이름을 속성으로 부르는 모양의 앞쪽 이름
DYNAMIC_HOLDERS = {"os": "getattr(os)", "builtins": "getattr(builtins)", "__builtins__": "getattr(builtins)"}   # `X.__dict__`·`X.__getattribute__`·`vars(X)` 가 이름 없이 꺼낼 수 있는 곳 — 걸리는 이름
REEXPORT_HOLDERS = {"os", "_os"}                                                 # `glob.os.system`·`tempfile._os.system`·`os.path.os.system` 처럼 다른 모듈이 다시 내놓는 `os`

# (파일, 쓰는 것) → 이유. 이 표가 정직한 코드가 바깥과 닿는 길의 전부다(회귀 그물 — 일부러 숨기는 코드를 막는 방어가 아니다, AS-S1 2차 권고-3·D-619).
# NET 갈래(D-735)부터 범주 표 다섯의 합집합이다 — 새 접속 갈래는 **자기 범주 표에 한 줄**만 더한다. 접속·쓰기 범주(`ALLOWED_GIT_WRITE`·`ALLOWED_NET_CLIENT`·`ALLOWED_LOOPBACK`)의 이유에는 관문 이름(`require_…`)이 있어야 한다.
ALLOWED_GIT_WRITE = {                       # 정확히 1곳 — git 이 접속한다(앱은 git 하위 프로세스를 띄울 뿐이다)
    ("publish/gitrepo.py", "subprocess"): "git 하위 프로세스를 띄우는 유일한 곳(`run_command`) — 외부 Write 관문(`capabilities.require_external_write`)이 첫 줄이라 이 빌드에서는 한 번도 띄우지 않는다",
}
ALLOWED_LOCAL_WORKER = {                    # 정확히 1곳 — 이 PC 안 계산(바깥에 쓰지 않는다)
    ("ui/ocr_adapter.py", "subprocess"): "이 PC 의 글자 읽기 작업자를 띄우는 유일한 곳(`_launch`) — `LOCAL_OCR` 관문이 첫 줄이고 인자는 고정, 셸 없음, 소켓·인터넷 코드 없음, 바깥에 쓰지 않는다(이 PC 안의 계산, 결정 D-512)",
}
ALLOWED_BROWSER = {                         # 정확히 2곳 — 앱은 접속하지 않고 OS 가 기본 브라우저로 연다
    ("ui/qt/shell.py", "QDesktopServices"): "`qt_open_url` — 네이버 글쓰기 주소를 기본 브라우저로 연다(주소만 연다 — 로그인·입력·발행은 사용자가 브라우저에서 직접, 앱은 연결하지 않는다)",
    ("ui/qt/components.py", "QDesktopServices"): "이미지 출처 링크 열기(`check_url` 로 주소 모양을 거른 뒤 기본 브라우저가 연다) — 앱은 연결하지 않는다",
}
ALLOWED_NET_CLIENT = {                      # 정확히 2곳 — 새 인터넷 접속이 나가는 유일한 문(NET 갈래가 더했다, D-735)
    ("net/client.py", "http"): "보안 접속 클라이언트가 `http.client` 로 요청 한 건을 보내는 유일한 곳(`NetClient`) — 공개 함수의 첫 문장이 `capabilities.require_net` 관문이고 호스트·길·머리글·크기·시간·이동은 `net/endpoints.py` 의 소스 표가 정하며 스위치가 모두 꺼진 이 빌드에서는 만들어지지도 않는다",
    ("net/client.py", "ssl"): "같은 클라이언트의 TLS 환경(`_make_context`) — 인증서 검증 필수·호스트 이름 확인·최소 TLS 1.2 이고 `capabilities.require_net` 관문 뒤에서만 쓰인다(검증을 끄거나 낮추는 이름은 소스 어디에도 없다)",
}
ALLOWED_LOOPBACK = {                        # 정확히 1곳 — BLOGGER 갈래(D-771)가 더했다
    ("net/loopback.py", "socket"): '로그인 코드를 받으려고 이 PC 안(127.0.0.1)에서 **한 번만** 듣는 유일한 곳 — `capabilities.require_net("blogger_oauth", …)` 가 공개 함수의 첫 문장이고 바깥 주소로 나가는 연결은 만들지 않으며 주소는 글자 `127.0.0.1` 하나뿐이다',
}
ALLOWED_UPDATE_SETUP = {                    # 정확히 1곳 — 업데이트 설치 도구(Inno Setup)를 띄운다(UPDATE U-4, 결정 D-850 이상). 접속은 설치 도구가 하는 일이 아니라 앱이 먼저 받아 검증한 파일만 넘긴다
    ("update/apply.py", "subprocess"): "검증된 Inno Setup 을 끊어서 띄우는 유일한 곳(`launch_setup`) — 업데이트 설치 관문(`capabilities.require_update_apply`)이 첫 문장이라 이 빌드에서는 한 번도 띄우지 않고, 인자는 고정 목록·셸 없음·출력은 읽지 않으며 종료 코드도 기다리지 않는다(앱이 먼저 끝난다)",
}
ALLOWED_CATEGORIES = {"git_write": ALLOWED_GIT_WRITE, "local_worker": ALLOWED_LOCAL_WORKER, "browser": ALLOWED_BROWSER, "net_client": ALLOWED_NET_CLIENT, "loopback": ALLOWED_LOOPBACK, "update_setup": ALLOWED_UPDATE_SETUP}
ALLOWED = {**ALLOWED_GIT_WRITE, **ALLOWED_LOCAL_WORKER, **ALLOWED_BROWSER, **ALLOWED_NET_CLIENT, **ALLOWED_LOOPBACK, **ALLOWED_UPDATE_SETUP}

# (파일, 쓰는 것) → 이유. 네이티브·동적 호출의 전부다(AS-S1 권고-6, D-611) — 새 파일이 `ctypes` 등을 가져오면 이 시험이 빨개지고, 이유 없이는 표에 더할 수 없다.
NATIVE_ALLOWED = {
    ("security/keystore.py", "ctypes"): "Windows 자격 증명 관리자(`advapi32` 의 `CredWriteW`·`CredReadW`·`CredDeleteW`·`CredEnumerateW`·`CredFree`)를 부르는 유일한 곳 — 키를 OS 보안 저장소에만 두려는 것이고 하위 프로세스·접속이 아니다",
    ("service/liveness.py", "ctypes"): "프로세스가 살아 있는지 읽기만 하는 `kernel32` 호출(`OpenProcess`·`GetExitCodeProcess`·`GetProcessTimes`·`GetComputerNameW`) — 끝내거나 신호를 보내는 권한을 쓰지 않는다",
    ("ui/single_instance.py", "ctypes"): "이미 떠 있는 같은 앱의 창을 앞으로 가져오는 `kernel32`·`user32` 호출 — 창 제목·실행 파일 경로는 비교에만 쓰고 저장·출력하지 않는다",
    ("ui/winroot.py", "ctypes"): "윈도 폴더를 윈도에 직접 묻는 읽기 한 번(`GetSystemWindowsDirectoryW`) — 쓰기·하위 프로세스·접속이 없고 윈도가 아니면 가져오지도 않는다",
    ("ui/ocr_adapter.py", "ctypes"): "글자 읽기 작업자를 띄울 때 작업 제한 장치(Job 개체)를 만드는 `kernel32` 호출 — 작업자를 가두는 쪽이며 `LOCAL_OCR` 관문 뒤에서만 쓰인다(결정 D-512)",
}
# vendor/ 는 `chanceblog` 의 파일을 한 글자도 바꾸지 않고 가져온 것이라(해시는 `tests/test_vendor_core.py` 가 지킨다) 앱 소스 훑기에서 빠져 있었다 — 그 안에서 바깥과 닿는 곳도 이름과 이유로 못박는다.
VENDOR_ALLOWED = {
    ("scripts/verify_pages_deploy.py", "http"): "블로그 배포 확인 도구(`http.client`) — vendor 는 불변이라 가져오기가 남는다. 앱은 `fetcher` 를 주입해 이 길을 쓰지 않는다(`net/` 의 `pages_site` 용 클라이언트가 접속한다 — 시험 `test_net_allowlist` 가 못박는다) · 외부 쓰기 관문(`require_external_write`)을 지난 뒤에만 부르고 이 빌드에서는 부르지 않는다",
    ("scripts/verify_pages_deploy.py", "urllib"): "같은 도구의 `urllib.request` — 앱은 `fetcher` 를 주입해 이 길(자동 이동·시스템 프록시)을 쓰지 않는다 · 같은 관문 뒤에서만 쓰인다",
}


def guarded_names(node):
    """AST 노드 하나에서 위 감시 이름을 **돌아서** 부르는 모양(`GUARDED_NAMES`)을 찾는다(AS-S1 권고-6, D-611): 네이티브 모듈 가져오기·`import os as 별칭`·`from os import <위험 이름>`(`from os import *` 포함)·
    `importlib.import_module`·`__import__`·`exec`·`eval`·`getattr(os, …)`. `getattr(os, '글자')` 는 그 글자가 위험 이름일 때만, 글자가 아닌 인자는 늘 걸린다(`getattr(os, 'O_BINARY', 0)` 같은 평범한 이름은 아니다)."""
    found = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split(".")[0] in NATIVE_MODULES:
                found.append(alias.name.split(".")[0])
            if alias.name == "os" and alias.asname:
                found.append("os-alias")
    elif isinstance(node, ast.ImportFrom) and node.level == 0:
        module = node.module or ""
        if module.split(".")[0] in NATIVE_MODULES:
            found.append(module.split(".")[0])
        if module == "os":
            found += [f"os.{alias.name}" for alias in node.names if alias.name in OUTGOING_OS]
            if any(alias.name == "*" for alias in node.names):
                found.append("os-alias")
        if module == "importlib" and any(alias.name in ("import_module", "__import__") for alias in node.names):
            found.append("importlib.import_module")
    elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "importlib" and node.attr == "import_module":
        found.append("importlib.import_module")
    elif isinstance(node, ast.Name) and node.id in ("__import__", "exec", "eval"):
        found.append(node.id)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "os":
        picked = node.args[1] if len(node.args) > 1 else None
        if isinstance(picked, ast.Constant) and isinstance(picked.value, str):
            if picked.value in OUTGOING_OS:
                found.append(f"os.{picked.value}")
        else:
            found.append("getattr(os)")
    found += guarded_bypass_names(node)
    return found


def guarded_bypass_names(node):
    """`guarded_names` 의 덧붙임(AS-S1 2차 권고-3·AS2 시험 렌즈 Q 권고-1, D-619) — 이름을 돌려 부르는 다른 모양: ① 별칭으로 가져온 `importlib`(`import importlib as il` — 별칭의 `import_module` 은 노드 하나로는 못 따르니 가져오는 줄을 건다)
    ② `builtins.__import__`·`__builtins__.exec` 처럼 내장 이름을 속성으로 부르는 모양과 `from builtins import exec` ③ 이름 없이 꺼내는 `os.__dict__`·`os.__getattribute__`·`vars(os)`(와 `builtins`·`__builtins__` 쪽 같은 모양)
    ④ `getattr(builtins, …)` ⑤ `sys.modules[…]`(가져오기 없이 모듈을 꺼낸다). 평범한 코드(`app.exec()`·`self.__dict__`·`vars(self)`·`sys.modules.get(…)`)는 걸리지 않는다."""
    found = []
    if isinstance(node, ast.Import):
        found += ["importlib.import_module" for alias in node.names if alias.name == "importlib" and alias.asname]
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "") == "builtins":
        found += [alias.name for alias in node.names if alias.name in ("__import__", "exec", "eval")]
        found += ["getattr(builtins)" for alias in node.names if alias.name == "*"]
    elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        holder = node.value.id
        if holder in BUILTINS_HOLDERS and node.attr in ("__import__", "exec", "eval"):
            found.append(node.attr)
        if holder in DYNAMIC_HOLDERS and node.attr in ("__dict__", "__getattribute__"):
            found.append(DYNAMIC_HOLDERS[holder])
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.args and isinstance(node.args[0], ast.Name):
        holder = node.args[0].id
        if node.func.id == "vars" and holder in DYNAMIC_HOLDERS:
            found.append(DYNAMIC_HOLDERS[holder])
        if node.func.id == "getattr" and holder in BUILTINS_HOLDERS:
            picked = node.args[1] if len(node.args) > 1 else None
            if isinstance(picked, ast.Constant) and isinstance(picked.value, str):
                if picked.value in ("__import__", "exec", "eval"):
                    found.append(picked.value)
            else:
                found.append("getattr(builtins)")
    elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Attribute) and node.value.attr == "modules" and isinstance(node.value.value, ast.Name) and node.value.value.id == "sys":
        found.append("sys.modules")                      # 읽을 때만 — `sys.modules[이름] = 모듈`(앱이 불러온 모듈을 등록하는 `core.py`·`doctor.py` 의 적재기)은 꺼내는 일이 아니다
    return found


def outgoing_names(node):
    """AST 노드 하나에서 바깥과 닿는 이름들(모듈·호출·Qt 이름·하위 프로세스를 띄우는 이름, 그리고 그것을 돌아서 부르는 모양 — `guarded_names`)을 찾는다 — 소스 전체 훑기와 탐지기 대조 시험이 같은 함수를 쓴다."""
    names = guarded_names(node)
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
    names += reexposed_names(node)
    return names


def reexposed_names(node):
    """같은 이름을 **다른 모양**으로 부르는 길(AS-S1 2차 권고-3, D-619): 다른 모듈이 다시 내놓는 `os`(`glob.os.system`·`tempfile._os.system`·`os.path.os.system`)·다시 내놓는 `subprocess`(`gitrepo.subprocess.run`)·다른 모듈에서 가져온
    바깥 모듈 이름(`from ..publish.gitrepo import subprocess as sp`)·Qt 이름을 속성으로(`QtGui.QDesktopServices`)나 `getattr(QtGui, 'QDesktopServices')` 로 부르는 모양. 이름은 예전 표(`ALLOWED`)와 같은 이름으로 걸린다."""
    names = []
    if isinstance(node, ast.Attribute):
        if node.attr in OUTGOING_OS and isinstance(node.value, ast.Attribute) and node.value.attr in REEXPORT_HOLDERS:
            names.append(f"os.{node.attr}")
        if node.attr == "subprocess":
            names.append("subprocess")
        if node.attr in QT_NAMES:
            names.append(node.attr)
    elif isinstance(node, ast.ImportFrom):
        top = (node.module or "").split(".")[0] if node.level == 0 else ""
        if top not in OUTGOING_MODULES:
            names += [alias.name for alias in node.names if alias.name in OUTGOING_MODULES]
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
        if isinstance(node.args[1].value, str) and node.args[1].value in QT_NAMES | PROCESS_NAMES:
            names.append(node.args[1].value)
    return names


_NAMES = {}


def names_in(path):
    """그 파일에서 `outgoing_names` 가 찾은 (이름, 줄 번호)들 — 같은 파일(경로·수정 시각·크기가 같으면)은 한 번만 훑는다(소스 훑기 시험이 여러 번 부른다)."""
    info = path.stat()
    key = (str(path), info.st_mtime_ns, info.st_size)
    if key not in _NAMES:
        _NAMES[key] = [(name, getattr(node, "lineno", 0)) for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) for name in outgoing_names(node)]
    return _NAMES[key]


def found_outgoing(guarded=False, root=None):
    """(파일, 이름) → 줄 번호들. 기본은 예전과 같은 '바깥으로 나가는 길' 표(`ALLOWED` 와 견준다)이고, `guarded=True` 는 그것을 돌아서 부르는 네이티브·동적 호출(`NATIVE_ALLOWED` 와 견준다)이다 — 두 표가 섞이지 않는다.
    `root` 는 훑을 폴더(기본은 앱 소스)다."""
    base = SRC if root is None else root
    found = {}
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(base).as_posix()
        for name, line in names_in(path):
            if (name in GUARDED_NAMES) == guarded:
                found.setdefault((rel, name), []).append(line)
    return found


class OutgoingCallSitesTest(unittest.TestCase):
    def test_the_places_that_touch_the_outside_are_exactly_the_allowed_list(self):
        found = found_outgoing()
        self.assertEqual(sorted(found), sorted(ALLOWED), "바깥과 닿는 코드가 허용 목록과 다르다 — 새로 생겼거나 사라졌다. 새로 생긴 곳은 외부 Write 관문·이유를 갖추고 이 표에 더한다")

    def test_every_allowance_has_a_real_reason(self):
        for key, reason in ALLOWED.items():
            self.assertGreater(len(reason), 20, key)
        for table in (ALLOWED_GIT_WRITE, ALLOWED_NET_CLIENT, ALLOWED_LOOPBACK, ALLOWED_UPDATE_SETUP):                 # NET 설계서 E3 — 접속·쓰기 범주는 이유에 관문 이름이 들어 있어야 한다(더 엄격, 설치 도구 범주도 같다)
            for key, reason in table.items():
                self.assertIn("require_", reason, f"{key}: 접속·쓰기 허용의 이유에는 관문 이름(`require_…`)이 있어야 한다")
        self.assertIn("LOCAL_OCR", ALLOWED_LOCAL_WORKER[("ui/ocr_adapter.py", "subprocess")], "글자 읽기 작업자의 이유에는 자기 관문 이름이 있다")
        self.assertIn("require_update_apply", ALLOWED_UPDATE_SETUP[("update/apply.py", "subprocess")], "설치 도구를 띄우는 곳의 이유에는 자기 관문 이름이 있다")

    def test_one_place_writes_to_the_outside_and_one_place_starts_the_local_worker_each_behind_its_own_gate(self):
        """결정 D-512(설계 3-8 (2)) — '바깥에 쓰는 곳은 하나' 가 '바깥에 쓰는 곳 하나 + 이 PC 안 계산 작업자 하나' 가 됐다. 옛 단언보다 약하지 않다: 하위 프로세스·소켓·웹 모듈이 허용 목록에 이 둘 말고는 없고,
        글자 읽기 쪽은 네트워크 모듈을 하나도 가져오지 않는다(어댑터의 바깥 이름은 `subprocess` 하나)."""
        external_writers = [("publish/gitrepo.py", "subprocess")]
        local_workers = [("ui/ocr_adapter.py", "subprocess")]
        setup_launchers = [("update/apply.py", "subprocess")]                 # UPDATE U-4(결정 D-850 이상) — 정확히 한 곳이 더해졌다
        process_like = sorted(key for key in ALLOWED if key[1] in ("subprocess", "multiprocessing", "QProcess", "ProcessPoolExecutor") or key[1].startswith("os."))
        self.assertEqual(process_like, sorted(external_writers + local_workers + setup_launchers), "하위 프로세스를 띄우는 허용은 이 셋뿐이다(git·글자 읽기 작업자·설치 도구)")
        # NET 설계서 E1 — 옛 단언 '소켓·http·urllib·ssl 이 든 허용이 0' 은 새 접속이 생길 수 없다는 뜻이었다. 이제는 '이 파일, 이 이름들만' 이고 다른 곳은 여전히 빨갛다(변이 M-NET-06·07 이 직접 깬다).
        network_like = sorted(key for key in ALLOWED if key[1] in ("socket", "http", "urllib", "ssl"))
        self.assertEqual(network_like, sorted(list(ALLOWED_NET_CLIENT) + list(ALLOWED_LOOPBACK)), "접속 모듈이 든 허용은 접속 범주 표의 것뿐이다")
        self.assertEqual([key for key in ALLOWED if key[1] == "urllib"], [], "urllib 은 어느 허용에도 없다(parse 말고는 쓰지 않는다)")
        self.assertEqual(sorted(key for key in ALLOWED if key[1] in ("http", "ssl")), [("net/client.py", "http"), ("net/client.py", "ssl")], "http·ssl 은 net/client.py 한 파일에만")
        self.assertEqual([key for key in ALLOWED if key[1] == "socket"], [key for key in ALLOWED_LOOPBACK if key[1] == "socket"], "socket 은 루프백 범주 표의 것뿐이다")
        self.assertTrue(all(key[0] == "net/loopback.py" for key in ALLOWED_LOOPBACK), "소켓은 net/loopback.py 한 파일에만(BLOGGER 갈래가 더한다)")
        self.assertEqual(sorted(key for key in found_outgoing() if key[0] == "ui/ocr_adapter.py"), local_workers, "어댑터가 바깥과 닿는 이름은 subprocess 하나뿐이다")
        self.assertEqual(sorted(key for key in found_outgoing() if key[0].startswith("update/")), setup_launchers, "업데이트 패키지가 바깥과 닿는 이름은 apply.py 의 subprocess 하나뿐이다(접속은 net/ 틀 밖에서 하지 않는다)")
        self.assertEqual(sorted(key for key in found_outgoing(guarded=True) if key[0].startswith("update/")), [], "설치 도구를 띄우는 길에 네이티브·동적 호출이 없다")
        self.assertEqual(sorted(key for key in found_outgoing() if key[0].startswith("net/")), sorted(list(ALLOWED_NET_CLIENT) + list(ALLOWED_LOOPBACK)), "net 패키지가 바깥과 닿는 이름은 표의 것뿐이다")

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


class GuardedCallSitesTest(unittest.TestCase):
    """AS-S1 권고-6(D-611) — 우회 모양을 보는 탐지와 네이티브·동적 호출 허용 표."""

    # 감사 탐침(`probe_scanner.py`)의 합성 코드 — 옛 탐지기가 '못 봄' 으로 놓친 것들. 각 코드에서 기대하는 이름 집합.
    MISSED_BEFORE = {
        "from os import system": ("from os import system\nsystem('x')\n", {"os.system"}),
        "from os import popen as run": ("from os import popen as run\nrun('x')\n", {"os.popen"}),
        "from os import *": ("from os import *\nsystem('x')\n", {"os-alias"}),
        "import os as o; o.popen": ("import os as o\no.popen('x')\n", {"os-alias"}),
        "getattr(os, 'system')": ("import os\ngetattr(os, 'system')('x')\n", {"os.system"}),
        "getattr(os, 이름 변수)": ("import os\nname = 'sys' + 'tem'\ngetattr(os, name)('x')\n", {"getattr(os)"}),
        "ctypes ShellExecuteW": ("import ctypes\nctypes.windll.shell32.ShellExecuteW(0, 'open', 'calc', None, None, 1)\n", {"ctypes"}),
        "ctypes CreateProcessW via WinDLL": ("import ctypes\nctypes.WinDLL('kernel32').CreateProcessW\n", {"ctypes"}),
        "from ctypes import windll": ("from ctypes import windll\nwindll.kernel32\n", {"ctypes"}),
        "importlib.import_module('subprocess')": ("import importlib\nimportlib.import_module('subprocess').run(['x'])\n", {"importlib.import_module"}),
        "from importlib import import_module": ("from importlib import import_module\nimport_module('socket')\n", {"importlib.import_module"}),
        "__import__('socket')": ("__import__('socket').create_connection(('h', 1))\n", {"__import__"}),
        "winreg": ("import winreg\n", {"winreg"}),
        "msvcrt": ("import msvcrt\n", {"msvcrt"}),
        "pty": ("import pty\n", {"pty"}),
        "runpy": ("import runpy\nrunpy.run_path('x')\n", {"runpy"}),
        "from runpy import run_path": ("from runpy import run_path\n", {"runpy"}),
        "exec('import subprocess')": ("exec('import subprocess')\n", {"exec"}),
        "eval": ("eval('1 + 1')\n", {"eval"}),
    }
    STILL_SEEN = {
        "import subprocess": ("import subprocess\n", {"subprocess"}), "os.system": ("import os\nos.system('x')\n", {"os.system"}), "import asyncio": ("import asyncio\n", {"asyncio"}),
    }
    HARMLESS = {
        "getattr(os, 평범한 이름)": "import os\nfd = os.open('x', os.O_WRONLY | getattr(os, 'O_BINARY', 0))\n", "app.exec()": "app = object()\napp.exec()\n", "import os.path as p": "import os.path as p\n",
        "from os import path, getcwd": "from os import path, getcwd\n", "importlib.util": "import importlib.util\nimportlib.util.spec_from_file_location('m', 'x.py')\n", "literal_eval": "from ast import literal_eval\nliteral_eval('1')\n",
        "re.compile": "import re\nre.compile('x')\n", "shutil.which": "import shutil\nshutil.which('git')\n", "threading": "import threading\nimport json\n", "os.getcwd": "import os\nos.getcwd()\nos.path.join('a', 'b')\n",
        "이름에 exec 가 든 변수": "my_exec = 1\nevaluate = 2\nname = 'exec'\n", "importlib 만": "import importlib\n",
    }

    def names_of(self, source):
        return {name for node in ast.walk(ast.parse(source)) for name in outgoing_names(node)}

    def test_every_shape_the_audit_probe_missed_is_now_seen_by_its_own_name(self):
        for label, (source, expected) in self.MISSED_BEFORE.items():
            with self.subTest(label=label):
                self.assertTrue(expected <= self.names_of(source), f"{label}: 기대 {sorted(expected)} / 실제 {sorted(self.names_of(source))}")

    def test_what_the_old_detector_already_saw_is_still_seen(self):
        for label, (source, expected) in self.STILL_SEEN.items():
            with self.subTest(label=label):
                self.assertEqual(self.names_of(source), expected)

    def test_ordinary_look_alikes_are_not_flagged(self):
        for label, source in self.HARMLESS.items():
            with self.subTest(label=label):
                self.assertEqual(self.names_of(source), set())

    def test_the_two_tables_are_kept_apart_so_the_old_assertions_keep_their_meaning(self):
        self.assertEqual({key for key in found_outgoing() if key[1] in GUARDED_NAMES}, set(), "예전 표에는 돌아서 부르는 이름이 섞이지 않는다")
        self.assertTrue(set(NATIVE_ALLOWED) <= set(found_outgoing(guarded=True)))

    def test_the_files_that_use_native_or_dynamic_calls_are_exactly_the_allowed_list(self):
        self.assertEqual(sorted(found_outgoing(guarded=True)), sorted(NATIVE_ALLOWED), "네이티브·동적 호출이 허용 표와 다르다 — 새로 생겼거나 사라졌다. 새로 생긴 곳은 이유를 갖추고 이 표에 더한다")

    def test_every_native_allowance_has_a_real_reason(self):
        for key, reason in NATIVE_ALLOWED.items():
            with self.subTest(key=key):
                self.assertGreater(len(reason), 30)
                self.assertEqual(key[1], "ctypes", "지금 소스에서 네이티브 길을 쓰는 것은 ctypes 뿐이다")

    def test_ctypes_is_imported_by_exactly_the_five_windows_helpers_and_nothing_else_is_used(self):
        files = sorted({key[0] for key in found_outgoing(guarded=True) if key[1] == "ctypes"})
        self.assertEqual(files, ["security/keystore.py", "service/liveness.py", "ui/ocr_adapter.py", "ui/single_instance.py", "ui/winroot.py"])
        used = {key[1] for key in found_outgoing(guarded=True)}
        self.assertEqual(used, {"ctypes"}, "winreg·msvcrt·pty·runpy·__import__·import_module·exec·eval·별칭·getattr(os) 는 한 곳도 없다")

    def test_vendor_scripts_outside_modules_are_a_closed_table(self):
        vendor = ss.ROOT / "vendor"
        self.assertTrue(vendor.is_dir())
        self.assertEqual(sorted(found_outgoing(root=vendor)), sorted(VENDOR_ALLOWED))
        self.assertEqual(sorted(found_outgoing(guarded=True, root=vendor)), [], "vendor 안에 네이티브·동적 호출이 없다")
        for key, reason in VENDOR_ALLOWED.items():
            with self.subTest(key=key):
                self.assertGreater(len(reason), 20)

    def test_the_detector_finds_a_new_bypass_in_a_synthetic_tree_of_the_second_round(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a" / "fine.py").write_text("import json\nimport sys\nsys.modules['x'] = json\nclass A:\n    def go(self):\n        return self.__dict__, vars(self)\napp = object()\napp.exec()\n", encoding="utf-8")
            (root / "a" / "sneaky.py").write_text("import builtins\nbuiltins.__import__('socket')\nfrom builtins import exec as run\nimport sys\nsys.modules['os'].system('x')\nimport nt\n", encoding="utf-8")
            self.assertEqual(sorted(found_outgoing(guarded=True, root=root)), [("a/sneaky.py", "__import__"), ("a/sneaky.py", "exec"), ("a/sneaky.py", "nt"), ("a/sneaky.py", "sys.modules")])
            self.assertEqual(sorted(found_outgoing(root=root)), [], "예전 표에는 돌아서 부르는 이름이 섞이지 않는다")

    def test_the_detector_finds_a_new_bypass_in_a_synthetic_tree(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a" / "fine.py").write_text("import json\nimport os\nos.getcwd()\n", encoding="utf-8")
            (root / "a" / "sneaky.py").write_text("import os as o\nfrom os import system\nimport ctypes\n__import__('socket')\n", encoding="utf-8")
            self.assertEqual(sorted(found_outgoing(root=root)), [("a/sneaky.py", "os.system")])
            self.assertEqual(sorted(found_outgoing(guarded=True, root=root)), [("a/sneaky.py", "__import__"), ("a/sneaky.py", "ctypes"), ("a/sneaky.py", "os-alias")])


class BypassShapesTest(unittest.TestCase):
    """AS-S1 2차(안전 검증 S) 권고-3 + AS2 시험 렌즈 Q 권고-1(D-619) — 검증자의 합성 코드 38개(탐침 `probe_scanner2`) 중 33개와 시험 렌즈가 더한 4개를 **못박는다**: 이름으로 보이게 만든 것은 `NOW_SEEN`(기대하는 이름 집합까지),
    AST 이름 규칙으로는 보이지 않는 것은 `HONEST_LIMITS`(이유와 함께 '지금은 안 보인다' 를 못박는다 — 나중에 보이게 되면 이 시험이 빨개져 `NOW_SEEN` 으로 옮기게 한다).
    이 시험은 **정직한 코드의 회귀 그물**이다 — 새로 쓴 평범한 코드가 바깥으로 나가는 길을 만들면 빨개지게 할 뿐, 일부러 숨기는 코드를 막는 방어가 아니다(`docs/SECURITY.md` D-359·D-611). 지금 소스는 위반 0 이고 허용 표는 정확히 일치한다."""

    AUDIT_LABELS = (
        "os.__dict__['system']", "vars(os)['system']", "os.__getattribute__('system')", "builtins.__import__('socket')", "__builtins__.__import__", "builtins.exec", "builtins.eval", "importlib alias: il.import_module",
        "glob.os.system (재노출)", "tempfile._os.system", "os.path.os.system", "nt.system (윈도 내장 모듈)", "_winapi.CreateProcess", "_socket.socket", "_ssl", "sys.modules['subprocess']", "재노출 gitrepo.subprocess",
        "from ..publish.gitrepo import subprocess as sp", "QtGui.QDesktopServices (속성)", "getattr(QtGui, 'QDesktopServices')", "import antigravity (webbrowser)", "operator.attrgetter('system')(os)",
        "timeit.timeit(문자열 실행)", "cProfile.run(문자열 실행)", "compile + types.FunctionType", "importlib.util.module_from_spec", "asyncore (3.10)", "smtpd (3.10)", "pdb.run", "code.interact", "ensurepip.bootstrap",
        "sqlite3 ATTACH 네트워크 경로", "os.fspath + Path('//srv/x').read_text",
    )
    NOW_SEEN = {
        "os.__dict__['system']": ("import os\nos.__dict__['system']('x')\n", {"getattr(os)"}),
        "vars(os)['system']": ("import os\nvars(os)['system']('x')\n", {"getattr(os)"}),
        "os.__getattribute__('system')": ("import os\nos.__getattribute__('system')('x')\n", {"getattr(os)"}),
        "builtins.__import__('socket')": ("import builtins\nbuiltins.__import__('socket')\n", {"__import__"}),
        "__builtins__.__import__": ("__builtins__.__import__('socket')\n", {"__import__"}),
        "builtins.exec": ("import builtins\nbuiltins.exec('import subprocess')\n", {"exec"}),
        "builtins.eval": ("import builtins\nbuiltins.eval('1')\n", {"eval"}),
        "importlib alias: il.import_module": ("import importlib as il\nil.import_module('socket')\n", {"importlib.import_module"}),
        "glob.os.system (재노출)": ("import glob\nglob.os.system('x')\n", {"os.system"}),
        "tempfile._os.system": ("import tempfile\ntempfile._os.system('x')\n", {"os.system"}),
        "os.path.os.system": ("import os.path\nos.path.os.system('x')\n", {"os.system"}),
        "nt.system (윈도 내장 모듈)": ("import nt\nnt.system('x')\n", {"nt"}),
        "_winapi.CreateProcess": ("import _winapi\n_winapi.CreateProcess(None, 'x', None, None, 0, 0, None, None, None)\n", {"_winapi"}),
        "_socket.socket": ("import _socket\n_socket.socket()\n", {"_socket"}),
        "_ssl": ("import _ssl\n", {"_ssl"}),
        "sys.modules['subprocess']": ("import sys\nsys.modules['subprocess'].run(['x'])\n", {"sys.modules"}),
        "재노출 gitrepo.subprocess": ("from ..publish import gitrepo\ngitrepo.subprocess.run(['x'])\n", {"subprocess"}),
        "from ..publish.gitrepo import subprocess as sp": ("from ..publish.gitrepo import subprocess as sp\nsp.run(['x'])\n", {"subprocess"}),
        "QtGui.QDesktopServices (속성)": ("from PySide6 import QtGui\nQtGui.QDesktopServices.openUrl(None)\n", {"QDesktopServices"}),
        "getattr(QtGui, 'QDesktopServices')": ("from PySide6 import QtGui\ngetattr(QtGui, 'QDesktopServices')\n", {"QDesktopServices"}),
        "import antigravity (webbrowser)": ("import antigravity\n", {"antigravity"}),
        "asyncore (3.10)": ("import asyncore\n", {"asyncore"}),
        "smtpd (3.10)": ("import smtpd\n", {"smtpd"}),
        # 시험 렌즈 Q 권고-1 — 같은 부류의 다른 모양 넷과 그 짝
        "from builtins import exec as _e": ("from builtins import exec as _e\n_e('x')\n", {"exec"}),
        "sys.modules['os'].system": ("import sys\nsys.modules['os'].system('x')\n", {"sys.modules"}),
        "vars(__builtins__)[조립한 이름]": ("vars(__builtins__)['__imp' + 'ort__']('ctypes')\n", {"getattr(builtins)"}),
        "from builtins import __import__": ("from builtins import __import__\n__import__('socket')\n", {"__import__"}),
        "getattr(builtins, 이름 변수)": ("import builtins\nname = 'ex' + 'ec'\ngetattr(builtins, name)('x')\n", {"getattr(builtins)"}),
        "getattr(builtins, 'exec')": ("import builtins\ngetattr(builtins, 'exec')('x')\n", {"exec"}),
        "builtins.__dict__": ("import builtins\nbuiltins.__dict__['exec']('x')\n", {"getattr(builtins)"}),
        "posix.system": ("import posix\nposix.system('x')\n", {"posix"}),
        "_posixsubprocess": ("import _posixsubprocess\n", {"_posixsubprocess"}),
        "_multiprocessing": ("import _multiprocessing\n", {"_multiprocessing"}),
    }
    HONEST_LIMITS = {
        "operator.attrgetter('system')(os)": ("import os\nimport operator\noperator.attrgetter('system')(os)('x')\n", "속성 이름을 값으로 넘기는 일반 함수 — `attrgetter` 는 정렬에도 평범하게 쓰여 이름만으로는 가를 수 없다"),
        "timeit.timeit(문자열 실행)": ("import timeit\ntimeit.timeit(\"__import__('os').system('x')\", number=1)\n", "표준 모듈이 글을 실행해 준다 — 그런 모듈 이름이 끝이 없어 이름 목록으로는 다 못 막는다"),
        "cProfile.run(문자열 실행)": ("import cProfile\ncProfile.run(\"import os\")\n", "같은 이유(글을 실행하는 표준 모듈)"),
        "compile + types.FunctionType": ("import types\ncode = compile('x=1', 'f', 'exec')\ntypes.FunctionType(code, {})()\n", "내장 `compile` 과 함수 만들기 — `re.compile` 같은 평범한 이름과 갈리지 않는다"),
        "importlib.util.module_from_spec": ("import importlib.util\nspec = importlib.util.spec_from_file_location('m', 'x.py')\nm = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(m)\n", "앱의 적재기 둘(`core.py`·`service/doctor.py`)이 평범하게 쓴다 — 파일 경로로 앱 자신의 스크립트를 불러오는 일"),
        "pdb.run": ("import pdb\npdb.run('x')\n", "같은 이유(글을 실행하는 표준 모듈)"),
        "code.interact": ("import code\ncode.interact()\n", "같은 이유(글을 실행하는 표준 모듈)"),
        "ensurepip.bootstrap": ("import ensurepip\nensurepip.bootstrap()\n", "표준 모듈이 패키지를 설치한다 — 이름 목록으로는 끝이 없다"),
        "sqlite3 ATTACH 네트워크 경로": ("import sqlite3\nc = sqlite3.connect(':memory:')\nc.execute(\"ATTACH DATABASE '//srv/share/x.db' AS x\")\n", "글자 안의 경로는 AST 이름 규칙이 아니라 글자 검사의 몫이다(연결한 폴더 가드 `_plain_local_shape` 와 같은 부류)"),
        "os.fspath + Path('//srv/x').read_text": ("from pathlib import Path\nPath('//srv/x').read_text()\n", "같은 이유(글자 안의 경로 — AST 이름 규칙이 아니라 글자 검사의 몫)"),
    }
    HARMLESS = {
        "app.exec()·dialog.exec()": "app = object()\napp.exec()\ndialog = object()\ndialog.exec()\n",
        "self.__dict__·vars(self)": "class A:\n    def go(self):\n        return self.__dict__, vars(self), vars(A)\n",
        "sys.modules.get·in·대입·삭제": "import sys\nmodule = sys.modules.get('x')\nsys.modules['x'] = module\ndel sys.modules['x']\nsys.modules.pop('x', None)\nprint('x' in sys.modules)\n",
        "builtins 만 가져오기·print": "import builtins\nbuiltins.print('x')\nfrom builtins import print as p\np('x')\n",
        "importlib.util 별칭": "import importlib.util as iu\niu.spec_from_file_location('m', 'x.py')\n",
        "getattr(self, 이름)": "class A:\n    def go(self, name):\n        return getattr(self, name), getattr(self, 'x', None)\n",
        "상대 가져오기": "from . import helpers\nfrom .shapes import checker\nfrom ..content import store\n",
        "이름이 비슷한 속성": "x = object()\nx.os_name\nx.subprocess_name\nx.exec_module_name\nx.QDesktopServicesLike\n",
        "os.path·os.environ·os.getcwd": "import os\nos.path.join('a', 'b')\nos.environ.get('x')\nos.getcwd()\n",
    }

    def names_of(self, source):
        return {name for node in ast.walk(ast.parse(source)) for name in outgoing_names(node)}

    def test_the_audit_list_of_thirty_three_is_fully_accounted_for_by_the_two_tables(self):
        self.assertEqual(len(self.AUDIT_LABELS), 33)
        self.assertEqual(len(set(self.AUDIT_LABELS)), 33)
        known = set(self.NOW_SEEN) | set(self.HONEST_LIMITS)
        self.assertEqual([label for label in self.AUDIT_LABELS if label not in known], [], "검증자의 합성 코드가 어느 표에도 없다 — 잊힌 모양")
        self.assertEqual(set(self.NOW_SEEN) & set(self.HONEST_LIMITS), set())

    def test_every_shape_the_second_audit_found_is_seen_by_its_own_name(self):
        for label, (source, expected) in self.NOW_SEEN.items():
            with self.subTest(label=label):
                self.assertEqual(self.names_of(source), expected)

    def test_the_shapes_that_stay_unseen_are_listed_as_honest_limits_with_a_reason(self):
        for label, (source, reason) in self.HONEST_LIMITS.items():
            with self.subTest(label=label):
                self.assertGreater(len(reason), 15)
                self.assertEqual(self.names_of(source), set(), "이제 보이게 됐다 — `NOW_SEEN` 으로 옮기고 기대 이름을 적는다")

    def test_ordinary_code_that_looks_alike_is_not_flagged(self):
        for label, source in self.HARMLESS.items():
            with self.subTest(label=label):
                self.assertEqual(self.names_of(source), set())

    def test_the_new_names_stay_in_the_guarded_table_or_the_old_outgoing_table_and_never_in_both(self):
        for label, (source, expected) in self.NOW_SEEN.items():
            with self.subTest(label=label):
                for name in expected:
                    in_guarded = name in GUARDED_NAMES
                    in_outgoing = name in OUTGOING_MODULES or name in OUTGOING_OS or name.startswith("os.") or name in QT_NAMES or name in PROCESS_NAMES
                    self.assertNotEqual(in_guarded, in_outgoing, f"{name} 은 두 표 가운데 한 곳에만 있어야 한다")

    def test_the_app_source_has_no_violation_of_the_widened_rules_and_the_tables_match_exactly(self):
        self.assertEqual(sorted(found_outgoing()), sorted(ALLOWED))
        self.assertEqual(sorted(found_outgoing(guarded=True)), sorted(NATIVE_ALLOWED))
        self.assertEqual(sorted(found_outgoing(root=ss.ROOT / "vendor")), sorted(VENDOR_ALLOWED))
        self.assertEqual(sorted(found_outgoing(guarded=True, root=ss.ROOT / "vendor")), [])

    def test_the_security_document_calls_this_check_a_regression_net_for_honest_code_and_not_a_defence(self):
        text = (ss.ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("정직한 코드의 회귀 그물", text)
        self.assertIn("**의도적** 우회는 막지 못하고", text, "옛 한계(D-359)는 그대로 남는다")


class NamedServerModulesTest(unittest.TestCase):
    """BLOGGER 재작업 1(D-780) — 이름 목록에 더한 서버·바깥 모듈을 탐지기가 모든 가져오기 모양에서 이름으로 알아보고, 지금 소스(와 vendor)에는 하나도 없다."""

    @staticmethod
    def names_of(source):
        return {name for node in ast.walk(ast.parse(source)) for name in outgoing_names(node)}

    def test_each_added_name_is_seen_in_every_import_shape(self):
        for name in sorted(EXTRA_OUTGOING_MODULES):
            for source in (f"import {name}\n", f"import {name}.sub\n", f"from {name} import thing\n", f"from {name}.sub import thing\n", f"import {name} as alias\n"):
                with self.subTest(source=source.strip()):
                    self.assertEqual(self.names_of(source), {name})

    def test_a_new_file_that_opens_a_server_with_one_of_them_is_not_in_the_allowed_list(self):
        """안전 검증 S 의 S-M10 — 새 파일이 서버를 여는 모양(`wsgiref.simple_server`)이 허용 목록에 없는 곳으로 잡힌다."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a" / "server.py").write_text("import wsgiref.simple_server\n\n\ndef serve():\n    return wsgiref.simple_server.make_server('', 0, None)\n", encoding="utf-8")
            (root / "a" / "fine.py").write_text("import json\nimport os\nos.getcwd()\n", encoding="utf-8")
            self.assertEqual(sorted(found_outgoing(root=root)), [("a/server.py", "wsgiref")])

    def test_no_source_file_or_vendor_script_uses_them_today_and_the_names_are_in_the_list(self):
        self.assertTrue(EXTRA_OUTGOING_MODULES <= OUTGOING_MODULES)
        self.assertTrue({"wsgiref", "nntplib", "pydoc", "urllib3", "httpx", "aiohttp", "websockets", "paramiko"} <= OUTGOING_MODULES, "표준 라이브러리의 서버·클라이언트와 흔한 바깥 라이브러리 이름은 목록에 남아 있어야 한다(목록에서 이름을 빼도 시험이 따라 줄지 않게 글자로 못박는다)")
        self.assertEqual(sorted(key for key in found_outgoing() if key[1] in EXTRA_OUTGOING_MODULES), [])
        self.assertEqual(sorted(key for key in found_outgoing(root=ss.ROOT / "vendor") if key[1] in EXTRA_OUTGOING_MODULES), [])

    def test_ordinary_look_alike_names_are_not_flagged(self):
        for source in ("import json\nimport html\n", "from pathlib import Path\n", "x = object()\nx.wsgiref_name\n", "import wsgiref_helper_that_is_not_the_module\n", "from . import helpers\n"):
            with self.subTest(source=source.strip()[:40]):
                self.assertEqual(self.names_of(source), set())


if __name__ == "__main__":
    unittest.main()
