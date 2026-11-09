"""키 연결(P4f) 시험이 함께 쓰는 '키가 새는지' 전수 검사 도구 — 가짜 키와 그 조각이 어디에도 없는지를 센다.

가짜 키는 실행할 때 조각을 이어 붙여 만든다(저장소에는 키 문자열이 없다). 조각은 영문 대소문자·숫자·기호를 섞어 어느 화면 글·파일 구조 글에도 우연히 들어 있지 않게 골랐다.
'조각' = 키의 모든 네 글자 윈도(앞 4글자·뒤 4글자 이상의 조각을 모두 포함한다) — 한 곳이라도 있으면 샌 것이다.

검사하는 곳(`find_*` 는 모두 '찾은 곳의 설명' 목록을 돌려주고, 비어 있어야 통과다):
  · 객체 그래프(`graph_hits`) — dict·list·tuple·set·dataclass·`__dict__`·`__slots__`·클로저 칸·함수 기본값·바운드 메서드의 `__self__` 를 따라가며 모든 글을 본다.
  · 위젯 트리(`widget_hits` — Qt 가 있을 때만) — 모든 위젯의 글·툴팁·접근 이름·설명·플레이스홀더·창 제목·상태 팁·What's This·객체 이름·동적 속성 값.
  · 파일(`file_hits`) — 폴더 안 모든 파일의 바이트(utf-8·utf-16 둘 다).
  · 예외(`error_hits`) — `str`·`repr`·`args`·`slots`·`detail` 과 호출 흔적(`__traceback__`)의 프레임 지역 변수·`__context__`·`__cause__`.
"""
import dataclasses
import re
import types
from pathlib import Path


def make_key(seed="a", length=36):
    """진짜 같은 모양의 가짜 키 — 조각을 이어 붙여 만든다. seed 가 다르면 값이 다르다."""
    pieces = {"a": ("Qx7Zk", "-Wm3Vp", "_Ty8Rn", "2Hs+Jd", "6Lg4Bf", "9Nc1Mu", "5Xo0Ka"), "b": ("Hv4Pq", "-Ze8Wd", "_Rt3Jn", "7Gs+Bk", "2Lf9Cy", "6Mx1Uo", "0Va5Ni"),
              "c": ("Ju6Tb", "-Cx2Fe", "_Dy9Ro", "4Ka+Wl", "8Pz3Gh", "1Sn7Vm", "5Qi0Ud")}
    text = "".join(pieces.get(seed, pieces["a"]))
    while len(text) < length:
        text += text
    return text[:length]


def fragments(key, size=4):
    """키의 모든 `size` 글자 윈도(중복 없음) — 앞·뒤 조각을 포함한다."""
    return sorted({key[index:index + size] for index in range(len(key) - size + 1)})


def needles(*keys, size=4):
    found = set()
    for key in keys:
        found.add(key)
        found.update(fragments(key, size))
    return sorted(found)


def text_hits(text, probes):
    if not isinstance(text, str):
        return []
    return [probe for probe in probes if probe in text]


# ---- 객체 그래프 ------------------------------------------------------------------------------------------------------------------------
def graph_hits(root, probes, *, limit=200000, skip=()):
    """`root` 에서 닿는 모든 객체의 글에서 `probes` 를 찾는다 → ['경로: 찾은 조각', …]. 글이 아닌 모듈·클래스·스레드 잠금은 따라가지 않는다. `skip` 은 따라가지 않을 객체들(예: 가짜 보관소)."""
    skip_ids = {id(item) for item in skip}
    seen, found, stack = set(), [], [("root", root)]
    steps = 0
    while stack and steps < limit:
        path, value = stack.pop()
        steps += 1
        if id(value) in seen or id(value) in skip_ids:
            continue
        seen.add(id(value))
        if isinstance(value, (str, bytes, bytearray)):
            if isinstance(value, str):
                found += [f"{path}: {probe}" for probe in text_hits(value, probes)[:1]]
            else:
                raw = bytes(value)                                                             # 바이트는 utf-8 과 utf-16 둘 다로 본다(보관소는 글을 UTF-16 으로 적는다)
                found += [f"{path}(bytes): {probe}" for probe in probes if probe.encode("utf-8") in raw or probe.encode("utf-16-le") in raw][:1]
            continue
        if isinstance(value, (int, float, bool, type(None), types.ModuleType, type)) or callable(value) and isinstance(value, types.BuiltinFunctionType):
            continue
        children = []
        if isinstance(value, dict):
            children = [(f"{path}[{key!r}]", item) for key, item in value.items()] + [(f"{path}<key>", key) for key in value]
        elif isinstance(value, (list, tuple, set, frozenset)):
            children = [(f"{path}[{index}]", item) for index, item in enumerate(value)]
        elif isinstance(value, types.MethodType):
            children = [(f"{path}.__self__", value.__self__), (f"{path}.__func__", value.__func__)]
        elif isinstance(value, types.FunctionType):
            children = [(f"{path}.cell{index}", cell.cell_contents) for index, cell in enumerate(value.__closure__ or ()) if _alive(cell)]
            children += [(f"{path}.default{index}", item) for index, item in enumerate(value.__defaults__ or ())]
            children += [(f"{path}.kwdefault[{key}]", item) for key, item in (value.__kwdefaults__ or {}).items()]
        else:
            if dataclasses.is_dataclass(value) and not isinstance(value, type):
                children += [(f"{path}.{field.name}", getattr(value, field.name, None)) for field in dataclasses.fields(value)]
            if hasattr(value, "__dict__"):
                try:
                    children += [(f"{path}.{key}", item) for key, item in vars(value).items()]
                except TypeError:
                    pass
            for cls in type(value).__mro__:
                for slot in getattr(cls, "__slots__", ()) if isinstance(getattr(cls, "__slots__", ()), (tuple, list)) else ():
                    if slot not in ("__dict__", "__weakref__") and hasattr(value, slot):
                        children.append((f"{path}.{slot}", getattr(value, slot)))
            if hasattr(value, "__len__") and hasattr(value, "__getitem__") and not hasattr(value, "__dict__") and not isinstance(value, (str, bytes)):
                try:
                    children += [(f"{path}[{index}]", value[index]) for index in range(min(len(value), 200))]
                except Exception:                                                         # 이상한 컨테이너는 건너뛴다
                    pass
        stack.extend(children)
    return found


def _alive(cell):
    try:
        cell.cell_contents
    except ValueError:                                                                    # 비어 있는 칸
        return False
    return True


# ---- 위젯 트리(Qt) ---------------------------------------------------------------------------------------------------------------------
def own_texts(widget):
    """위젯 하나만(자식 제외)의 모든 글 → [(설명, 글)] — 글·툴팁·접근 이름·설명·상태 팁·What's This·창 제목·객체 이름·플레이스홀더·동적 속성 값."""
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QTextEdit
    name = f"{type(widget).__name__}:{widget.objectName()}"
    found = [(f"{name}.{label}", value) for label, value in (("toolTip", widget.toolTip()), ("accessibleName", widget.accessibleName()), ("accessibleDescription", widget.accessibleDescription()),
                                                              ("statusTip", widget.statusTip()), ("whatsThis", widget.whatsThis()), ("windowTitle", widget.windowTitle()), ("objectName", widget.objectName()))]
    if isinstance(widget, (QLabel, QAbstractButton)):
        found.append((f"{name}.text", widget.text()))
    if isinstance(widget, QLineEdit):
        found += [(f"{name}.text", widget.text()), (f"{name}.displayText", widget.displayText()), (f"{name}.placeholder", widget.placeholderText())]
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        found.append((f"{name}.plain", widget.toPlainText()))
    if isinstance(widget, QComboBox):
        found += [(f"{name}.item{index}", widget.itemText(index)) for index in range(widget.count())]
    for prop in widget.dynamicPropertyNames():
        key = bytes(prop).decode("utf-8", "replace")
        if key == "_PySideInvalidatePtr":                                                 # PySide 가 스크롤 막대·뷰포트에 다는 내부 포인터 속성 — 글이 아니고 읽을 수도 없다(읽으면 변환 오류)
            continue
        try:
            value = widget.property(key)
        except RuntimeError:                                                              # 그 밖에 읽을 수 없는 속성 — 읽지 못한 사실만 남긴다(조용히 건너뛰지 않는다)
            value = "<읽을 수 없는 속성>"
        found.append((f"{name}.property:{key}", value if isinstance(value, str) else re.sub(r" at 0x[0-9A-Fa-f]+", "", repr(value))))     # `repr` 끝의 메모리 주소(`… at 0x…37C0`)는 글이 아니고 실행마다 달라 길이 검사(`37`)에 우연히 걸린다 — 빼고 모은다
    return found


def widget_texts(root):
    """위젯 트리 전체(숨겨진 위젯 포함)의 모든 글 → [(설명, 글)]. Qt 를 이 함수 안에서만 가져온다."""
    from PySide6.QtWidgets import QWidget
    found = []
    for widget in [root, *root.findChildren(QWidget)]:
        found += own_texts(widget)
    return found


def widget_hits(root, probes, *, typing_into=()):
    """위젯 트리에서 `probes` 를 찾는다. `typing_into` 는 키를 아직 입력하는 중인 칸들 — 그 칸의 글자(`text`·`displayText`)만 건너뛴다(입력 중인 칸에 글이 있는 것은 당연하다. 툴팁·접근 이름 같은 다른 속성은 이 칸도 본다)."""
    from PySide6.QtWidgets import QWidget
    skip = {id(item) for item in typing_into}
    found = []
    for widget in [root, *root.findChildren(QWidget)]:
        for label, value in own_texts(widget):
            if id(widget) in skip and (label.endswith(".text") or label.endswith(".displayText")):
                continue
            found += [f"{label}: {probe}" for probe in text_hits(value, probes)[:1]]
    return found


# ---- 파일 -------------------------------------------------------------------------------------------------------------------------------
def file_hits(folder, probes, *, skip=()):
    """폴더 안 모든 파일의 바이트에서 조각을 찾는다(utf-8·utf-16 둘 다). `skip` 은 건너뛸 폴더들(가짜 보관소 폴더)."""
    root = Path(folder)
    skip_paths = [Path(item) for item in skip]
    found = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if any(parent in skip_paths for parent in path.parents):
            continue
        raw = path.read_bytes()
        for probe in probes:
            if probe.encode("utf-8") in raw or probe.encode("utf-16-le") in raw:
                found.append(f"{path.relative_to(root).as_posix()}: {probe}")
                break
    return found


# ---- 예외 -------------------------------------------------------------------------------------------------------------------------------
def error_texts(error):
    """오류가 사용자·로그에 내보내는 모든 글(AppError 와 JobFailure 모두)."""
    texts = [str(error), repr(error), repr(getattr(error, "args", ())), str(getattr(error, "detail", "")), repr(getattr(error, "slots", {})), str(getattr(error, "user_message", "")),
             str(getattr(error, "code", "")), repr(getattr(error, "problems", {}))]
    rendered = getattr(error, "rendered", None)
    if callable(rendered):
        shown = rendered()
        texts += [shown.message, shown.action, shown.retry_text]
    log_line = getattr(error, "log_line", None)
    if callable(log_line):
        texts.append(log_line())
    return texts


def error_hits(error, probes, *, app_only=True, skip=()):
    """예외의 모든 글 + 호출 흔적의 프레임 지역 변수 + 앞선 오류(`__context__`·`__cause__`) 에서 조각을 찾는다. `app_only` 면 앱 소스(`chanceblog_desktop`)의 프레임만 본다(시험 함수가 자기 변수로 키를 들고 있는 것은 앱이 샌 것이 아니다).
    `skip` 은 따라가지 않을 객체들 — 프레임의 `self`(공급자)에서 시험의 가짜 보관소(키를 **일부러** 담고 있다)로 닿는 길을 끊는다."""
    found, seen, stack = [], set(), [error]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        for text in error_texts(current):
            found += [f"{type(current).__name__} 글: {probe}" for probe in text_hits(text, probes)[:1]]
        trace = current.__traceback__
        while trace is not None:
            if app_only and "chanceblog_desktop" not in trace.tb_frame.f_code.co_filename.replace(chr(92), "/"):
                trace = trace.tb_next
                continue
            for name, value in trace.tb_frame.f_locals.items():
                found += [f"프레임 {trace.tb_frame.f_code.co_name}.{name}: {hit}" for hit in graph_hits(value, probes, limit=20000, skip=skip)[:2]]
            trace = trace.tb_next
        stack += [current.__context__, current.__cause__]
    return found
