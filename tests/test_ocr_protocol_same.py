"""글자 읽기 약속(프로토콜)의 앱 쪽 사본과 작업자 쪽 원본이 **같은 글자**인지 견준다(설계서 3-2, 결정 D-512).

작업자 원본 `ocr_addon/protocol.py` 는 앱 묶음 밖(`src/` 밖)이라 앱이 가져올 수 없어서 `ui/core/ocr_protocol.py` 에 같은 글자의 사본을 둔다. 지키는 것:
  1) 머리말(첫 따옴표 글) 아래의 소스가 두 파일에서 한 글자도 다르지 않다(줄 끝 통일 뒤).
  2) 상수·오류 코드·허용 칸이 같고, 같은 입력에 같은 결과·같은 거절(양쪽을 가져와 견준다).
  3) 두 파일 모두 표준 라이브러리만 가져오고 3.10 문법이며 물결표·인터넷 주소가 없다.
  4) 요청 머리에 경로·파일 이름·사진 번호·종류·메모·Exif 가 들어갈 칸이 없다(모르는 칸은 작업자가 거절한다).
"""
import ast
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.ui.core import ocr_protocol as app_side  # noqa: E402

WORKER_FILE = ROOT / "ocr_addon" / "protocol.py"
APP_FILE = ROOT / "src" / "chanceblog_desktop" / "ui" / "core" / "ocr_protocol.py"
STDLIB_OK = {"json", "math"}


def load_worker():
    spec = importlib.util.spec_from_file_location("ocr_worker_protocol_original", str(WORKER_FILE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def body_after_docstring(path):
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    tree = ast.parse(text)
    first = tree.body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
    lines = text.split("\n")
    return "\n".join(lines[first.end_lineno:])


worker_side = load_worker()


def good_result(req_id=7):
    return {"t": "result", "id": req_id, "lines": [{"text": "한우 불고기", "cx": 0.31, "cy": 0.22, "h": 0.04}], "ms": {"det": 340, "rec": 860}, "net_attempts": 0}


class SameLettersTest(unittest.TestCase):
    def test_everything_below_the_docstring_is_identical_in_both_files(self):
        self.assertEqual(body_after_docstring(APP_FILE), body_after_docstring(WORKER_FILE))

    def test_the_constants_and_known_fields_are_equal(self):
        names = ("PROTO", "FMT_RGB24", "MAX_LONG_SIDE", "MAX_REQUEST_BYTES", "MAX_HEADER_BYTES", "DRAIN_LIMIT_BYTES", "MAX_LINES", "MAX_LINE_CHARS", "MAX_RESPONSE_BYTES", "ERROR_CODES", "OPT_RANGES",
                 "_RESULT_KEYS", "_LINE_KEYS", "_READY_KEYS")
        for name in names:
            self.assertEqual(getattr(app_side, name), getattr(worker_side, name), name)

    def test_the_numbers_the_design_pins_are_literal(self):
        self.assertEqual((app_side.PROTO, app_side.MAX_LONG_SIDE, app_side.MAX_LINES, app_side.MAX_LINE_CHARS, app_side.MAX_RESPONSE_BYTES), (1, 1600, 200, 400, 262144))
        self.assertEqual(app_side.ERROR_CODES, ("decode", "too_big", "engine", "net_blocked", "proto"))

    def test_the_same_request_gives_the_same_bytes(self):
        pixels = bytes(range(256)) * 3
        self.assertEqual(app_side.encode_request(7, 16, 16, pixels, "960"), worker_side.encode_request(7, 16, 16, pixels, "960"))
        self.assertEqual(app_side.encode_request(7, 16, 16, pixels), worker_side.encode_request(7, 16, 16, pixels))

    def test_the_same_responses_pass_and_the_same_ones_are_refused(self):
        samples = [good_result(), dict(good_result(), id=8), dict(good_result(), extra=1), {"t": "error", "id": 7, "code": "decode"}, {"t": "error", "id": 7, "code": "zzz"},
                   dict(good_result(), lines=[{"text": "a" * 401, "cx": 0.1, "cy": 0.1, "h": 0.1}]), dict(good_result(), lines=[{"text": "a", "cx": 1.5, "cy": 0.1, "h": 0.1}]),
                   dict(good_result(), lines=[{"text": "a", "cx": 0.1, "cy": 0.1, "h": 0.1, "score": 0.9}]), dict(good_result(), net_attempts=True), dict(good_result(), ms={"det": -1}), [], "x"]
        for sample in samples:
            outcomes = []
            for module in (app_side, worker_side):
                try:
                    module.validate_result(sample, 7)
                    outcomes.append("ok")
                except module.ProtocolError as error:
                    outcomes.append(error.code)
            self.assertEqual(outcomes[0], outcomes[1], repr(sample)[:80])

    def test_both_sides_refuse_nan_and_infinity(self):
        for module in (app_side, worker_side):
            for raw in (b'{"t":"result","x":NaN}', b'{"t":"result","x":Infinity}', b'{"t":"result","x":-Infinity}'):
                with self.assertRaises(ValueError):
                    module.loads_strict(raw)
            with self.assertRaises(ValueError):
                module.dumps_line({"x": float("nan")})


class FilesAreSafeTest(unittest.TestCase):
    def test_only_the_standard_library_is_imported_and_nothing_outgoing(self):
        for path in (APP_FILE, WORKER_FILE):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported.add((node.module or "").split(".")[0])
            self.assertEqual(imported - {"__future__"}, STDLIB_OK, path.name)

    def test_the_files_parse_as_python_310_and_have_no_tilde_or_web_address(self):
        for path in (APP_FILE, WORKER_FILE):
            text = path.read_text(encoding="utf-8")
            ast.parse(text, feature_version=(3, 10))
            self.assertNotIn("~", text, path.name)
            self.assertNotIn("http", text.lower(), path.name)

    def test_a_request_header_has_no_place_for_a_path_or_a_note(self):
        head = json.loads(app_side.encode_request(3, 2, 2, bytes(12), "960").split(b"\n", 1)[0])
        self.assertEqual(sorted(head), ["fmt", "h", "id", "n", "size", "t", "w"])
        for bad in ("path", "file", "photo_id", "photo_type", "note", "exif", "local_path"):
            raw = dict(head, **{bad: "x"})
            with self.assertRaises(worker_side.ProtocolError):
                worker_side.parse_header(json.dumps(raw).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
