"""번호 자리에 친 글이 오류 문구·`--json`·`--verbose`·데이터 폴더에 되풀이되지 않는다 — 번호를 받는 모든 명령을 파서에서 모아 가짜 키로 훑는 표 시험.

지키는 것:
  1) `echo.shown_ref`·`shown_backup`: 번호 모양(16진수 8자 이하·앱이 만드는 백업 이름 하나)만 되풀이하고 그 밖의 글(글이 아닌 값 포함)은 고정 말로 바꾼다.
     그 모양은 실제 번호(`uuid4().hex` 32자·화면의 짧은 번호 8자)·실제 백업 이름과 맞고, 8자보다 긴 16진수(키 조각일 수 있다)는 되풀이하지 않는다.
  2) 표: 파서(`cli.build_parser`)에서 **번호 자리**(위치 인자의 이름이 번호·글번호·항목·백업파일)를 가진 모든 명령을 찾아 그 자리마다 가짜 키 여러 종을 넣고(화면·`--json`·`--verbose`·`--yes`
     변형, 보관함이 있을 때와 없을 때) 표준 출력·표준 오류와 데이터 폴더 어디에도 값(조각·인코딩 변형 포함)이 없음을 본다. 새 명령이 번호 자리를 가지면 이 표에 저절로 걸린다
     (모르는 위치 인자·필수 옵션이 생기면 그것도 실패로 알려 표를 고치게 한다).
  3) 오류를 만드는 소스: `…_NOT_FOUND`·`CANDIDATE_AMBIGUOUS` 의 칸 값은 고정 글·`shown_ref` 호출·짧은 번호·숫자뿐이다(새 오류 지점이 친 글을 그대로 담으면 걸린다).
  4) 번호 모양이면 예전처럼 되풀이한다 — 없는 순번 `999`·없는 번호 `a1b2c3d4` 는 '찾을 수 없습니다' 로 쉬운 말이고, 키를 쳤을 때와 오류 코드·종료 코드·하실 일이 같다(친 글 자리만 다르다).
  5) 진짜 프로세스(`python -m chanceblog_desktop`)로 열두 가지 넘는 명령을 확인한다(셸 인용·cp949 콘솔 포함).
가짜 키는 실행할 때 무작위(고정 시드)로 만든다 — 저장소에는 키 모양 글이 없다. 네트워크·실제 비밀 없이 돈다.
"""
import argparse
import ast
import base64
import builtins
import contextlib
import errno
import io
import json
import os
import random
import re
import string
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop import echo  # noqa: E402
from chanceblog_desktop.content.candidates import Candidate  # noqa: E402
from chanceblog_desktop.content.model import ContentProject  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402

SRC = ss.ROOT / "src" / "chanceblog_desktop"
HIDDEN_FLAG = 0x08000000                                       # CREATE_NO_WINDOW — 시험이 콘솔 창을 띄우지 않게(Windows 에서만 뜻이 있다)
ALNUM = string.ascii_letters + string.digits
URLSAFE = ALNUM + "_-"
UPPER_DIGITS = string.ascii_uppercase + string.digits
HEX = "0123456789abcdef"
NOT_HEX_LETTERS = "ghijklmnopqrstuvwxyzGHIJKLMNOPQRSTUVWXYZ"
NUMBER_SLOTS = frozenset({"번호", "글번호", "항목", "백업파일"})                    # 위치 인자의 이름(metavar)이 이것이면 번호 자리다
OTHER_SLOTS = frozenset({"폴더", "파일", "용도", "action", "blog", "사용|예비|꺼짐"})   # 번호 자리가 아닌 것으로 알려진 위치 인자(경로·고정 선택지)
REQUIRED_OPTION_VALUES = {"--blog": "naver_a", "--platform": "naver_a", "--url": "https://example.com/x", "--title": "제목", "--topic": "주제", "--keyword": "키워드", "--name": "기본"}
PLACEHOLDER = echo.TYPED_NUMBER


# ---- 가짜 키 -----------------------------------------------------------------------------------------------------------------------
class Maker:
    def __init__(self, seed):
        self.rnd = random.Random(seed)

    def text(self, length, alphabet=ALNUM):
        """영문자·숫자가 섞이고 16진수만으로 된 글은 아닌 무작위 글(번호 모양과 겹치지 않는다)."""
        while True:
            value = "".join(self.rnd.choice(alphabet) for _ in range(length))
            if any(ch.isdigit() for ch in value) and any(ch in NOT_HEX_LETTERS for ch in value):
                return value

    def hexa(self, length):
        return "".join(self.rnd.choice(HEX) for _ in range(length))


def make_canaries(seed=20261104):
    """(이름, 친 글, 찾는 알맹이) — 키 모양 5종(AIza·ghp_·sk-·AKIA·JWT)과 새 sk- 모양 3종, 모양 없는 긴 영숫자와 번호 모양에 가까운 것까지 28종."""
    maker = Maker(seed)
    text, hexa = maker.text, maker.hexa
    found = []

    def add(kind, value, core=None):
        found.append({"kind": kind, "value": value, "core": value if core is None else core})

    core = text(35, URLSAFE); add("google", "AI" + "za" + core, core)
    core = text(36); add("github", "gh" + "p_" + core, core)
    core = text(48); add("sk-plain", "s" + "k-" + core, core)
    core = text(74, URLSAFE); add("sk-project", "s" + "k-proj-" + core, core)
    core = text(93, URLSAFE); add("sk-anthropic", "s" + "k-ant-api03-" + core, core)
    core = hexa(64); add("sk-openrouter", "s" + "k-or-v1-" + core, core)
    core = text(16, UPPER_DIGITS); add("aws", "AK" + "IA" + core, core)
    first, second, third = text(20, URLSAFE), text(30, URLSAFE), text(43, URLSAFE); add("jwt", "ey" + "J" + first + "." + second + "." + third, first + second + third)
    add("random40", text(40))
    add("random24", text(24))
    add("urlsafe17", text(17, URLSAFE))
    add("nonhex9", text(9))
    add("hex9", hexa(9))
    add("hex12", hexa(12))
    add("hex32", hexa(32))
    add("base64", base64.b64encode(bytes(maker.rnd.randrange(256) for _ in range(36))).decode())
    add("pixabay-like", "".join(maker.rnd.choice(string.digits) for _ in range(8)) + "-" + hexa(24))
    add("unsplash-like", text(43, URLSAFE))
    core = text(40); add("hangul-around", "비밀키는" + core + "입니다", core)
    core = text(40); add("double-quoted", '"' + core + '"', core)
    core = text(35, URLSAFE); add("parenthesised", "(AI" + "za" + core + ")", core)
    core = text(39); add("dash-first", "-" + core, core)
    first, second = text(20), text(20); add("newline-inside", first + "\n" + second, first)
    core = text(30); add("tab-comma", "\t" + core + ",", core)
    core = text(24); add("unicode-escapes", "".join("\\u%04x" % ord(ch) for ch in core), core)
    core = text(30); add("percent-encoded", urllib.parse.quote(core + "!@#$%^&*()가나"), core)
    core = text(5000); add("too-long", core, core[:60])
    core = text(40); add("fullwidth-around", "，" + core + "）", core)
    return found


CANARIES = make_canaries()


def pieces(text):
    if len(text) < 8:
        return []
    middle = len(text) // 2
    return [text[:8], text[middle - 4:middle + 4], text[-8:]]


def needles_of(canary):
    """출력·파일에 있으면 값이 새어 나온 것으로 보는 글들 — 값·알맹이·그 조각(앞·가운데·끝 8자)·JSON/퍼센트로 쓴 모양."""
    found = {canary["value"], canary["value"].strip(), canary["core"]}
    for text in (canary["value"].strip(), canary["core"]):
        found |= {json.dumps(text, ensure_ascii=True)[1:-1], json.dumps(text, ensure_ascii=False)[1:-1], urllib.parse.quote(text)}
        found |= set(pieces(text))
    return sorted((item for item in found if len(item) >= 6), key=len, reverse=True)


def scan_text(blob, needles):
    return [item[:6] for item in needles if item in blob]


def scan_tree(root, needles):
    """폴더 안 파일 이름·내용에서 찾은 글(UTF-8·UTF-16·cp949 로 쓴 모양까지)."""
    found = []
    encoded = []
    for item in needles:
        for encoding in ("utf-8", "utf-16-le", "cp949"):
            try:
                encoded.append((item, item.encode(encoding)))
            except UnicodeEncodeError:
                continue
    for path in Path(root).rglob("*"):
        found += [item[:6] for item in needles if item in path.name]
        if path.is_file():
            data = path.read_bytes()
            found += [item[:6] for item, raw in encoded if raw in data]
    return found


# ---- 명령 모으기 -------------------------------------------------------------------------------------------------------------------
def positionals(parser):
    return [action for action in parser._actions if not action.option_strings and not isinstance(action, argparse._SubParsersAction)]


def leaf_commands(parser, path=()):
    """(명령 이름들, 파서) — 하위 명령이 없는 명령만."""
    subs = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    if not subs:
        yield path, parser
        return
    for name, child in subs[0].choices.items():
        yield from leaf_commands(child, path + (name,))


def label_of(action):
    return action.metavar or action.dest


def number_commands():
    """번호 자리를 가진 명령 → [(명령 이름들, 파서, [번호 자리 위치 인자…])]. 번호 자리인지 아닌지 모르는 위치 인자가 있으면 실패로 알린다(새 명령이 표를 빠져나가지 못하게)."""
    found = []
    for path, parser in leaf_commands(cli.build_parser()):
        slots = []
        for action in positionals(parser):
            label = label_of(action)
            if label in NUMBER_SLOTS:
                slots.append(action)
            elif label not in OTHER_SLOTS:
                raise AssertionError(f"{' '.join(path)}: 번호 자리인지 아닌지 모르는 위치 인자 '{label}' — 시험의 NUMBER_SLOTS 나 OTHER_SLOTS 에 넣어 분류하세요")
        if slots:
            found.append((path, parser, slots))
    return found


NUMBER_COMMANDS = number_commands()


class World:
    """시험 한 벌의 데이터 폴더 — 후보 하나·글 하나가 있거나(`with_data`) 아무것도 없다."""

    def __init__(self, with_data):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.ctx = ss.make_ctx(self.root, clock=ss.Clock())
        self.project = "abcd1234"
        if with_data:
            code, out, err = ss.run_cli(self.ctx, "candidates", "add", "--topic", "겨울 난방비 줄이기", "--keyword", "난방비", "--blog", "github_pages")
            assert code == 0, (out, err)
            view = ss.projects.new_project(self.ctx, "글 하나", ss.ko_text())
            self.project = view.project_id[:8]

    def close(self):
        self.tmp.cleanup()

    def benign(self, action):
        label = label_of(action)
        if action.choices:
            return str(next(iter(action.choices)))
        if label == "글번호":
            return self.project
        if "|" in label:
            return label.split("|")[0]
        if label in ("번호", "항목"):
            return "1"
        return "x"

    def argv(self, path, parser, slot, value, extra=()):
        """`slot`(번호 자리 하나)에 value 를 넣고 다른 위치 인자·필수 옵션은 무해한 값으로 채운 명령줄."""
        argv = list(path)
        for action in positionals(parser):
            argv.append(value if action is slot else self.benign(action))
        for action in parser._actions:
            if action.option_strings and action.required:
                flag = action.option_strings[0]
                chosen = REQUIRED_OPTION_VALUES.get(flag)
                if action.choices and chosen not in action.choices:
                    chosen = str(next(iter(action.choices)))
                if chosen is None:
                    raise AssertionError(f"{' '.join(path)}: 모르는 필수 옵션 {flag} — 시험의 REQUIRED_OPTION_VALUES 에 무해한 값을 넣으세요")
                argv += [flag, chosen]
        return argv + list(extra)


def variants_of(parser, *, thorough=True):
    flags = {flag for action in parser._actions for flag in action.option_strings}
    found = [(), ("--json",)]
    if thorough:
        found.append(("--verbose",))
    if "--yes" in flags:
        found += [("--yes",), ("--yes", "--json")]
    return found


# ---- 1) 번호 모양 판정 ----------------------------------------------------------------------------------------------------------------
class ShapeTest(unittest.TestCase):
    def test_numbers_and_short_hexadecimal_prefixes_are_repeated_as_typed(self):
        for text in ("1", "9", "999", "0", "00", "ab", "ABCD", "a1b2c3d4", "deadbeef", "12345678", "AbCdEf12", "f"):
            with self.subTest(text=text):
                self.assertEqual(echo.shown_ref(text), text)

    def test_anything_else_is_replaced_by_the_fixed_words(self):
        for text in ("", " ", "a1b2c3d4e", "123456789", "0123456789abcdef", "g", "qqqq", "x1", "-1", "+1", "1.0", "1 2", "12\n", "\n12", "ab-cd", "a_b", "１２３", "١٢٣", "가나", "abc가", "(1)", '"1"',
                     "AIza" + "A" * 35, "key=1", "1" * 9, "f" * 9):
            with self.subTest(text=text[:12]):
                self.assertEqual(echo.shown_ref(text), PLACEHOLDER)
        for value in (None, 5, 1.5, b"abc", ["1"], ("1",), {"a": 1}, object()):
            with self.subTest(kind=type(value).__name__):
                self.assertEqual(echo.shown_ref(value), PLACEHOLDER)

    def test_the_length_limit_is_the_shortest_real_number_shown_on_screen(self):
        """화면에 보이는 짧은 번호가 8자이고 번호 전체는 32자(16진수) — 8자까지만 되풀이하고 9자부터는 키 조각일 수 있어 되풀이하지 않는다."""
        candidate = Candidate.new("주제", "키워드", ("naver_a",), now="2026-11-04T00:00:00Z")
        project = ContentProject.new("제목", "본문 " * 30, now="2026-11-04T00:00:00Z")
        for name, number in (("후보", candidate.candidate_id), ("글", project.project_id)):
            self.assertRegex(number, r"^[0-9a-f]{32}$", name)
            for size in range(1, 9):
                self.assertEqual(echo.shown_ref(number[:size]), number[:size], f"{name} 앞 {size}자")
            for size in range(9, 33):
                self.assertEqual(echo.shown_ref(number[:size]), PLACEHOLDER, f"{name} 앞 {size}자")
        self.assertEqual(echo.shown_ref(candidate.candidate_id.upper()[:8]), candidate.candidate_id.upper()[:8], "대문자로 쳐도 번호 앞부분이다(후보는 대소문자를 가리지 않는다)")

    def test_a_backup_name_is_repeated_only_in_the_shape_the_app_makes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Store.open(Path(tmp) / "chanceblog.db") as store:
                made = store.backup(Path(tmp) / "backups", now=ss.NOW)
            self.assertEqual(echo.shown_backup(made.name), made.name, "앱이 만든 백업 이름은 되풀이한다")
        for name in ("chanceblog-20261104-120000.db", "chanceblog-19991231-235959.db"):
            self.assertEqual(echo.shown_backup(name), name)
        for name in ("", "chanceblog.db", "backup.db", "chanceblog-20261104-120000.db ", "chanceblog-20261104-120000.db\n", "xchanceblog-20261104-120000.db", "chanceblog-2026110-120000.db", "chanceblog-20261104-12000.db",
                     "chanceblog-２０２６１１０４-120000.db", "chanceblog-١٢٣٤٥٦٧٨-120000.db", "chanceblog-20261104-120000.DB", "C:\\x\\chanceblog-20261104-120000.db", "a/chanceblog-20261104-120000.db",
                     "chanceblog-20261104-120000.db.bak", "AI" + "za" + "A" * 35, None, 5, b"x"):
            with self.subTest(name=str(name)[:20]):
                self.assertEqual(echo.shown_backup(name), echo.TYPED_FILE)

    def test_the_two_fixed_phrases_are_plain_korean_and_contain_no_value(self):
        self.assertEqual((echo.TYPED_NUMBER, echo.TYPED_FILE), ("(입력한 번호)", "(입력한 파일)"))

    def test_the_module_is_standard_library_only_and_does_nothing_when_imported(self):
        tree = ast.parse((SRC / "echo.py").read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
        self.assertEqual(imported, {"__future__", "re"})
        self.assertFalse([node for node in tree.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)], "불러올 때 실행되는 호출이 없다")


# ---- 2) 표: 번호를 받는 모든 명령 × 가짜 키
NEEDLES = {item["kind"]: needles_of(item) for item in CANARIES}
EMPTY_KINDS = frozenset({"random40", "hex32", "hangul-around", "sk-project", "double-quoted", "percent-encoded", "newline-inside", "too-long", "unicode-escapes", "pixabay-like"})


def sweep(world, *, thorough, kinds=None):
    """모든 명령·번호 자리·가짜 키·변형을 돌려 새어 나온 것(명령·키 이름·어디서)을 모은다 → (샌 것들, 돌린 횟수). 종료 코드는 처리된 오류(1)나 사용법 오류(2)여야 한다(성공하면 키가 번호로 받아들여진 것이다)."""
    leaks, runs = [], 0
    for path, parser, slots in NUMBER_COMMANDS:
        for slot in slots:
            for canary in (item for item in CANARIES if kinds is None or item["kind"] in kinds):
                for extra in variants_of(parser, thorough=thorough):
                    argv = world.argv(path, parser, slot, canary["value"], extra)
                    code, out, err = ss.run_cli(world.ctx, *argv)
                    runs += 1
                    where = f"{' '.join(path)} [{label_of(slot)}] {' '.join(extra) or '기본'}"
                    for channel, blob in (("표준 출력", out), ("표준 오류", err)):
                        if scan_text(blob, NEEDLES[canary["kind"]]):
                            leaks.append((where, canary["kind"], channel))
                    if code not in (1, 2):
                        leaks.append((where, canary["kind"], f"종료 코드 {code}"))
                    if "Traceback" in err:
                        leaks.append((where, canary["kind"], "스택 추적"))
    return leaks, runs


class TableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full, cls.empty = World(True), World(False)
        cls.full_result = sweep(cls.full, thorough=True)             # 모든 명령·번호 자리·가짜 키·변형을 한 번씩만 돌리고 아래 시험들이 그 결과를 본다
        cls.empty_result = sweep(cls.empty, thorough=False, kinds=EMPTY_KINDS)      # 보관함이 없을 때는 갈래만 다르니 대표 모양 열 가지만

    @classmethod
    def tearDownClass(cls):
        cls.full.close()
        cls.empty.close()

    def test_no_command_repeats_a_key_typed_in_a_number_slot_when_the_data_exists(self):
        leaks, runs = self.full_result
        self.assertEqual(leaks[:12], [], f"{len(leaks)}곳에서 샜다")
        self.assertGreater(runs, 2000, "표가 너무 작다 — 명령이나 가짜 키가 빠졌다(지금은 번호 자리 27곳 × 가짜 키 28종 × 변형 3~5가지 = 2,548번)")

    def test_no_command_repeats_a_key_typed_in_a_number_slot_when_there_is_no_data_folder_content(self):
        """보관함이 없으면 오류의 갈래가 다르다(`candidates show` 는 '아직 보관함이 없다' 로 알린다)."""
        leaks, runs = self.empty_result
        self.assertEqual(leaks[:12], [], f"{len(leaks)}곳에서 샜다")
        self.assertGreater(runs, 600, "표가 너무 작다(지금은 번호 자리 27곳 × 대표 모양 10가지 × 변형 2~4가지 = 640번)")

    def test_no_key_reaches_a_file_name_or_the_content_of_any_file_in_the_data_folder(self):
        for name, world in (("데이터가 있을 때", self.full), ("없을 때", self.empty)):
            for canary in CANARIES:
                with self.subTest(world=name, kind=canary["kind"]):
                    self.assertEqual(scan_tree(world.root, needles_of(canary)), [])

    def test_the_table_covers_every_number_taking_command_the_parser_knows(self):
        names = sorted(" ".join(path) for path, _parser, _slots in NUMBER_COMMANDS)
        for expected in ("candidates show", "candidates select", "candidates hold", "candidates reject", "candidates restore", "candidates review", "candidates delete", "candidates link", "candidates unlink",
                         "draft plan", "show", "edit", "approve", "revoke", "delete", "publish-pages", "check-deploy", "naver-package", "naver-done", "review", "preview", "restore",
                         "keys remove", "keys state", "keys order", "keys test"):
            self.assertIn(expected, names)
        self.assertEqual(len([1 for _path, _parser, slots in NUMBER_COMMANDS for _slot in slots]), 30, "번호 자리의 수 — 새 번호 자리가 생기면 이 숫자를 고친다(표는 저절로 따라온다 — P3 가 `topics show`·`topics restore` 둘을 더해 27 → 29, DB 가 `draft body` 를 더해 29 → 30)")
        self.assertGreaterEqual(len({item["kind"] for item in CANARIES}), 28)

    def test_two_number_slots_of_one_command_are_both_swept(self):
        link = [slots for path, _parser, slots in NUMBER_COMMANDS if path == ("candidates", "link")]
        self.assertEqual([len(slots) for slots in link], [2])


# ---- 2b) 리눅스의 파일 이름 길이 한계 흉내 — 백업 파일 자리에 너무 긴 글을 쳐도 그 글이 오류 문구로 되풀이되지 않는다(D-80) --------------------------------------------------------
# 우분투 검사에서만 `topics restore <너무 긴 글> --verbose` 의 표준 오류에 친 글이 되풀이됐다: 리눅스는 이름 한 마디가 255바이트(NAME_MAX)를 넘거나 경로가 4096바이트를 넘으면
# `os.stat` 가 `OSError(ENAMETOOLONG, 'File name too long: <그 이름>')` 을 내고, `pathlib.Path.is_dir()` 는 ENOENT·ENOTDIR·EBADF·ELOOP 만 삼켜 그 오류가 올라왔다(윈도는 '없는 파일' 로 돌려줘 안 보였다).
# 아래는 그 동작을 윈도에서도 똑같이 흉내 내서(`os.stat`·`os.lstat`·`pathlib.Path.stat`·열기·목록) 같은 표 시험을 돌린다 — 어느 PC 에서도 같은 자리에서 빨개진다.
LINUX_NAME_MAX = 255                                           # 이름 한 마디의 한계(바이트)
LINUX_PATH_MAX = 4096                                          # 경로 전체의 한계(바이트)
PATH_SLOT = "백업파일"                                          # 친 글이 파일 시스템 경로로 쓰이는 번호 자리(명령 둘 — `topics restore`·`restore`)


def beyond_linux_limits(path):
    """리눅스라면 `ENAMETOOLONG` 을 낼 경로인가 — 이름 한 마디가 255바이트를 넘거나 전체가 4096바이트 이상이다(`/`·`\\` 를 둘 다 마디 구분으로 본다 — 윈도에서 도는 이 시험의 임시 폴더 경로도 같은 눈으로 본다)."""
    if path is None or isinstance(path, int):
        return False
    try:
        text = os.fsdecode(path)
    except TypeError:
        return False

    def size(piece):
        return len(piece.encode("utf-8", "surrogatepass"))

    return size(text) >= LINUX_PATH_MAX or any(size(piece) > LINUX_NAME_MAX for piece in re.split(r"[\\/]", text))


def _limited(real):
    def limited(*args, **kwargs):
        target = args[0] if args else kwargs.get("path", kwargs.get("file"))
        if beyond_linux_limits(target):
            raise OSError(errno.ENAMETOOLONG, "File name too long", target)          # 리눅스처럼 파일 이름(= 친 글)이 오류 문구에 들어간다
        return real(*args, **kwargs)

    return limited


@contextlib.contextmanager
def linux_name_limits():
    """`with` 로 쓴다 — 그 안에서는 파일 시스템 호출이 너무 긴 이름에 리눅스처럼 `OSError(ENAMETOOLONG, 'File name too long', 이름)` 을 낸다(윈도에서도 같게).
    파이썬 3.10 의 `pathlib` 은 `os.stat` 를 클래스를 만들 때 붙잡아 두어 `os.stat` 만 바꿔서는 `Path.is_dir()` 에 닿지 않으므로 `Path.stat` 도 직접 바꾼다."""
    with contextlib.ExitStack() as stack:
        for owner, name in ((os, "stat"), (os, "lstat"), (os, "listdir"), (os, "scandir"), (os, "open"), (os, "mkdir"), (Path, "stat"), (builtins, "open"), (io, "open")):
            stack.enter_context(mock.patch.object(owner, name, _limited(getattr(owner, name))))
        yield


def path_variants(parser):
    """`--json`·`--verbose`·`--yes` 와 그 조합 — 우분투에서 샌 길은 `--verbose`(오류 세부)였고, `--yes` 를 같이 줄 때 복원이 더 깊이 들어간다."""
    flags = {flag for action in parser._actions for flag in action.option_strings}
    found = [(), ("--json",), ("--verbose",), ("--verbose", "--json")]
    if "--yes" in flags:
        found += [("--yes",), ("--yes", "--json"), ("--yes", "--verbose"), ("--yes", "--verbose", "--json")]
    return found


def sweep_path_slots(world, typed):
    """친 글 `typed`([(이름, 글, 찾을 글들)…])을 백업 파일 자리에 넣고 모든 변형으로 돌린다 → (샌 것들, 돌린 횟수, {(명령, 이름, 변형): (종료 코드, 출력, 오류)}).
    종료 코드는 처리된 오류(1)나 사용법 오류(2)여야 하고 스택 추적이 없어야 한다."""
    leaks, runs, results = [], 0, {}
    for path, parser, slots in NUMBER_COMMANDS:
        for slot in (item for item in slots if label_of(item) == PATH_SLOT):
            for name, value, needles in typed:
                for extra in path_variants(parser):
                    code, out, err = ss.run_cli(world.ctx, *world.argv(path, parser, slot, value, extra))
                    runs += 1
                    results[(" ".join(path), name, extra)] = (code, out, err)
                    where = f"{' '.join(path)} {' '.join(extra) or '기본'}"
                    for channel, blob in (("표준 출력", out), ("표준 오류", err)):
                        if scan_text(blob, needles):
                            leaks.append((where, name, channel))
                    if code not in (1, 2):
                        leaks.append((where, name, f"종료 코드 {code}"))
                    if "Traceback" in err:
                        leaks.append((where, name, "스택 추적"))
    return leaks, runs, results


def long_names(seed=20261106):
    """리눅스가 `ENAMETOOLONG` 을 내는(또는 한계 딱인) 여러 모양의 긴 글 → [(이름, 친 글, 찾을 글들)]. 찾을 글은 무작위 알맹이와 그 조각이다(앱이 일부러 되풀이하는 백업 이름 `topic-…` 은 찾지 않는다)."""
    maker = Maker(seed)
    found = []

    def add(name, core, value):
        found.append((name, value, needles_of({"value": core, "core": core})))

    core = maker.text(256); add("name-256", core, core)
    core = maker.text(300); add("name-300", core, core)
    core = maker.text(4000); add("name-4000", core, core)
    core = maker.text(100); add("path-over-4096", core, "/".join([core] * 51))
    core = maker.text(300); add("long-directory-then-backup-name", core, core + "/topic-20261106-120000")
    core = maker.text(300); add("backup-name-then-long", core, "topic-20261106-120000/" + core)
    core = maker.text(300); add("climbing-then-long", core, "../" + core)
    core = maker.text(300); add("backslashes", core, "C:\\" + core + "\\topic-20261106-120000")
    add("hangul-258-bytes", "가" * 86, "가" * 86 + "/topic-20261106-120000")
    core = maker.text(255); add("name-255-at-the-limit", core, core)
    return found


class LinuxNameLimitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World(True)
        cls.canaries = [(item["kind"], item["value"], NEEDLES[item["kind"]]) for item in CANARIES]
        cls.longs = long_names()
        with linux_name_limits():
            cls.result = sweep_path_slots(cls.world, cls.canaries + cls.longs)

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    def test_the_emulation_raises_what_linux_raises(self):
        """흉내 자체의 시험 — 너무 긴 이름은 `OSError(ENAMETOOLONG)` 이고 오류 문구에 이름이 들어 있다(그것이 샌 길이다). 한계 안의 이름과 짧은 경로는 그대로 지나간다."""
        long_name = "q" * 300
        with linux_name_limits():
            for call in (lambda: Path(long_name).is_dir(), lambda: Path(long_name).exists(), lambda: Path(long_name).is_file(), lambda: Path(long_name).stat(), lambda: os.stat(long_name),
                         lambda: os.lstat(long_name), lambda: open(long_name, "rb"), lambda: os.listdir(long_name)):
                with self.assertRaises(OSError) as caught:
                    call()
                self.assertEqual(caught.exception.errno, errno.ENAMETOOLONG)
                self.assertIn(long_name, str(caught.exception))
            self.assertFalse(Path("q" * 255).is_dir(), "한계 딱 그만큼은 그냥 '없는 폴더'")
            self.assertFalse(os.path.exists(long_name), "`os.path.exists` 는 어떤 OS 오류든 삼킨다")
            with tempfile.TemporaryDirectory() as tmp:
                self.assertTrue(Path(tmp).is_dir())
        self.assertTrue(beyond_linux_limits("/".join(["w" * 100] * 50)), "마디는 짧아도 전체가 4096바이트 이상")
        self.assertTrue(beyond_linux_limits("가" * 86), "글자는 86자여도 258바이트")
        self.assertFalse(beyond_linux_limits("가" * 85), "255바이트 딱")
        self.assertFalse(beyond_linux_limits(3))
        self.assertFalse(beyond_linux_limits(None))

    def test_no_path_taking_command_repeats_a_long_or_key_shaped_text_even_with_verbose_and_yes(self):
        leaks, runs, results = self.result
        self.assertEqual(leaks[:12], [], f"{len(leaks)}곳에서 샜다")
        self.assertEqual({command for command, _name, _extra in results}, {"topics restore", "restore"}, "친 글을 경로로 쓰는 명령은 이 둘이다 — 새 명령이 백업 파일 자리를 가지면 여기에 저절로 걸린다")
        self.assertGreater(runs, 550, "표가 너무 작다(지금은 명령 2 × 친 글 38종 × 변형 8가지 = 608번)")

    def test_a_text_that_cannot_be_a_backup_ends_in_the_plain_not_found_error_on_every_variant(self):
        """`topics restore` 는 친 글이 어떤 모양이든 같은 '백업을 찾을 수 없음'(TOPIC_BACKUP_INVALID)이고 종료 코드 1 이다."""
        _leaks, _runs, results = self.result
        for name, _value, _needles in self.longs:
            for extra in (("--json",), ("--yes", "--json"), ("--verbose", "--json"), ("--yes", "--verbose", "--json")):
                with self.subTest(name=name, extra=" ".join(extra)):
                    code, out, err = results[("topics restore", name, extra)]
                    self.assertEqual(code, 1)
                    self.assertEqual(json.loads(out)["error"]["code"], "TOPIC_BACKUP_INVALID")
        for kind, value, _needles in self.canaries:
            with self.subTest(kind=kind):
                code, out, err = results[("topics restore", kind, ("--yes", "--verbose", "--json"))]
                if value.startswith("-"):
                    self.assertEqual(code, 2, "`-` 로 시작하는 글은 옵션으로 읽혀 사용법 오류다")
                else:
                    self.assertEqual((code, json.loads(out)["error"]["code"]), (1, "TOPIC_BACKUP_INVALID"))

    def test_the_outcome_does_not_depend_on_what_the_operating_system_does_with_the_name(self):
        """흉내 안과 밖(진짜 이 PC)의 화면이 글자까지 같다 — 모양이 이상한 글은 OS 에 묻기 전에 걸러 어느 OS 에서나 같은 길을 탄다."""
        _leaks, _runs, results = self.result
        path, parser, slots = next(item for item in NUMBER_COMMANDS if item[0] == ("topics", "restore"))
        for name, value, _needles in self.longs:
            for extra in (("--json",), ("--verbose",)):
                with self.subTest(name=name, extra=" ".join(extra)):
                    outside = ss.run_cli(self.world.ctx, *self.world.argv(path, parser, slots[0], value, extra))
                    self.assertEqual(results[("topics restore", name, extra)], outside)

    def test_no_number_slot_of_any_command_repeats_the_too_long_text_when_the_filesystem_has_linux_limits(self):
        """우분투 검사가 돈 표(번호 자리 전부 × 변형)에서 샌 것은 `too-long`(5,000자) 하나였다 — 그 가짜 키를 모든 번호 자리·모든 변형에 넣어 흉내 아래에서 다시 돌린다.
        (가짜 키 28종 전부를 흉내 아래에서 돌린 것도 샌 곳 0 이었다 — 시간이 길어 이 시험에는 넣지 않았다.)"""
        with linux_name_limits():
            leaks, runs = sweep(self.world, thorough=True, kinds={"too-long"})
        self.assertEqual(leaks[:12], [], f"{len(leaks)}곳에서 샜다")
        self.assertGreater(runs, 90, "표가 너무 작다(지금은 번호 자리 29곳 × 변형 3~5가지 = 99번)")

    def test_a_long_text_typed_for_a_folder_option_is_not_repeated_either(self):
        """번호 자리가 아닌 경로 옵션(`--repo`·`--data-dir`)에 친 5,000자 글도 같다 — 고치기 전에는 `--data-dir` 의 글이 기본 화면에도, `--repo` 의 글이 `--verbose` 에 되풀이됐다
        (예상 못 한 OS 오류의 세부 — 모든 명령이 쓰는 `unexpected_error` 한 곳이 고쳤다). 데이터 폴더는 임시 폴더로 따로 준다(사용자의 진짜 폴더를 건드리지 않는다)."""
        typed = Maker(20261107).text(5000)
        needles = needles_of({"value": typed, "core": typed})
        found, runs = [], 0
        with linux_name_limits(), tempfile.TemporaryDirectory() as tmp:
            under_tmp = str(Path(tmp) / typed)                      # 폴더 자리에 줄 값 — 임시 폴더 아래의 긴 이름(상대 경로로 주면 이 시험을 도는 자리가 저장소 안일 때 '저장소 안은 안 됩니다' 가 경로를 보여 줘 시험이 흔들린다)
            cases = [("--repo", ("topics", "status")), ("--repo", ("topics", "check")), ("--repo", ("topics", "plan", "--today", "2026-11-10")), ("--data-dir", ("topics", "status")),
                     ("--data-dir", ("topics", "restore", "--latest")), ("--data-dir", ("list",)), ("--data-dir", ("connect", under_tmp))]
            for option, command in cases:
                for extra in ((), ("--verbose",), ("--json",), ("--verbose", "--json")):
                    out, err = io.StringIO(), io.StringIO()
                    argv = [*(("--data-dir", tmp) if option == "--repo" else ()), option, typed if option == "--repo" else under_tmp, *command, *extra]
                    code = cli.main(argv, out=out, err=err, env={})
                    runs += 1
                    where = f"{option} {' '.join(command[:2]) if command[0] != 'connect' else 'connect'} {' '.join(extra) or '기본'}"
                    if scan_text(out.getvalue() + err.getvalue(), needles):
                        found.append((where, "글이 되풀이됨"))
                    if code not in (0, 1, 2) or "Traceback" in err.getvalue():
                        found.append((where, f"종료 코드 {code} 또는 스택 추적"))
        self.assertEqual(found[:12], [], f"{len(found)}곳에서 샜다")
        self.assertEqual(runs, 28)

    def test_no_text_reaches_a_file_name_or_the_content_of_any_file_in_the_data_folder_either(self):
        for name, _value, needles in self.canaries + self.longs:
            with self.subTest(name=name):
                self.assertEqual(scan_tree(self.world.root, needles), [])


# ---- 3) 오류를 만드는 소스 ---------------------------------------------------------------------------------------------------------------
WATCHED_CODES = {"CANDIDATE_NOT_FOUND", "CONTENT_NOT_FOUND", "CANDIDATE_AMBIGUOUS"}
SAFE_CALLS = {"shown_ref", "shown_backup", "short_id"}
SAFE_NAMES = {"number", "revision"}                                   # 숫자(순번·판 번호)
KNOWN_SITES = {("store.py", "_open_read_only")}                       # 읽기 전용으로 열 글 저장소 파일 이름(앱이 정한 `chanceblog.db`) — 친 번호가 아니다


def safe_slot(node, function):
    """칸 값 식이 친 글을 그대로 담지 않는가 — 고정 글·`shown_ref`/`shown_backup`/`short_id` 호출·숫자 이름, 그것들만 이은 f-글."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
        return name in SAFE_CALLS
    if isinstance(node, ast.Name):
        return node.id in SAFE_NAMES or (node.id == "what" and function == "_not_found")        # `_not_found(what)` 는 부르는 쪽을 따로 본다
    if isinstance(node, ast.JoinedStr):
        return all(safe_slot(part.value if isinstance(part, ast.FormattedValue) else part, function) for part in node.values)
    return False


def watched_sites(path):
    """(함수 이름, 줄, 식) — `AppError(<감시 코드>, {"항목": 식})` 와 `_not_found(식)` 의 칸 값."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func.id if isinstance(node.func, ast.Name) else ""
            if callee == "AppError" and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in WATCHED_CODES and len(node.args) > 1 and isinstance(node.args[1], ast.Dict):
                for key, value in zip(node.args[1].keys, node.args[1].values, strict=True):
                    if isinstance(key, ast.Constant) and key.value == "항목":
                        yield function.name, node.lineno, value
            elif callee == "_not_found" and node.args:
                yield function.name, node.lineno, node.args[0]


class SourceTest(unittest.TestCase):
    FILES = (SRC / "service" / "candidates.py", SRC / "service" / "projects.py", SRC / "content" / "store.py")

    def test_the_slot_of_every_not_found_and_ambiguous_error_holds_no_typed_text(self):
        count = 0
        for path in self.FILES:
            for function, line, value in watched_sites(path):
                count += 1
                with self.subTest(file=path.name, function=function, line=line):
                    self.assertTrue(safe_slot(value, function) or (path.name, function) in KNOWN_SITES, ast.unparse(value))
        self.assertGreaterEqual(count, 15, "감시하는 오류 지점을 못 찾았다 — 이 시험의 찾기 규칙이 깨졌다")

    def test_the_guard_itself_catches_a_site_that_repeats_the_typed_text(self):
        for source, expected in (('raise AppError("CONTENT_NOT_FOUND", {"항목": wanted})', False), ('raise AppError("CANDIDATE_NOT_FOUND", {"항목": text.strip()})', False),
                                 ('raise _not_found(wanted)', False), ('raise _not_found(f"순번 {number}")', True), ('raise AppError("CONTENT_NOT_FOUND", {"항목": shown_ref(wanted)})', True),
                                 ('raise AppError("CONTENT_NOT_FOUND", {"항목": f"{wanted} 의 {revision}판"})', False), ('raise AppError("CONTENT_NOT_FOUND", {"항목": f"{shown_ref(wanted)} 의 {revision}판"})', True),
                                 ('raise AppError("CANDIDATE_NOT_FOUND", {"항목": short_id(candidate_id)})', True), ('raise _not_found(_short(text))', False)):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "x.py"
                path.write_text("def f():\n    " + source + "\n", encoding="utf-8")
                sites = list(watched_sites(path))
                self.assertEqual(len(sites), 1, source)
                self.assertEqual(safe_slot(sites[0][2], sites[0][0]), expected, source)

    def test_the_restore_confirmation_and_the_backup_errors_name_a_backup_only_through_the_helper(self):
        cli_tree = ast.parse((SRC / "service" / "cli.py").read_text(encoding="utf-8"))
        restore = next(node for node in cli_tree.body if isinstance(node, ast.FunctionDef) and node.name == "cmd_restore")
        text = ast.unparse(restore)
        self.assertIn("shown_backup(source.name)", text)
        self.assertNotIn("{source.name}", text)
        projects_tree = ast.parse((SRC / "service" / "projects.py").read_text(encoding="utf-8"))
        restore_store = next(node for node in projects_tree.body if isinstance(node, ast.FunctionDef) and node.name == "restore_store")
        self.assertIn("shown_backup(Path(source).name)", ast.unparse(restore_store))
        self.assertIn("_without_typed_backup", ast.unparse(restore_store))


# ---- 4) 번호 모양이면 예전처럼 ----------------------------------------------------------------------------------------------------------
class NormalPathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World(True)

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    def commands(self):
        """후보·글 번호 자리(키 보관 `keys` 와 백업 파일은 따로 본다)."""
        for path, parser, slots in NUMBER_COMMANDS:
            if path[0] == "keys" or path in (("restore",), ("topics", "restore")):          # P3 의도적 갱신: `topics restore` 도 기존 `restore` 처럼 백업 이름 자리라 번호 시험에서 빼고 따로 본다(`test_service_topics_cli` 가 이름 모양만 되풀이함을 못박는다)
                continue
            for slot in slots:
                yield path, parser, slot

    def test_a_number_that_does_not_exist_is_still_repeated_and_said_in_plain_words(self):
        seen = 0
        for path, parser, slot in self.commands():
            for typed, shown in (("999", None), ("a1b2c3d4", "a1b2c3d4")):
                for extra in ((), ("--json",)):
                    argv = self.world.argv(path, parser, slot, typed, extra)
                    code, out, err = ss.run_cli(self.world.ctx, *argv)
                    where = f"{' '.join(argv)}"
                    self.assertEqual(code, 1, (where, out, err))
                    text = out + err
                    seen += 1
                    self.assertIn("찾을 수 없습니다", text, where)
                    self.assertNotIn(PLACEHOLDER, text, where)
                    self.assertIn(typed if typed == "a1b2c3d4" else "999", text, where)
                    if "--json" not in extra:
                        self.assertIn("코드: ", text, where)
                        self.assertIn("하실 일: ", text, where)
        self.assertEqual(seen, 96, "후보·글 번호 자리 24곳(P3 가 `topics show` 를, DB 가 `draft body` 를 더했다) × 번호 2가지 × 변형 2가지")

    def test_a_key_gets_the_same_error_code_exit_code_and_advice_as_a_missing_number_only_the_typed_words_differ(self):
        canary = next(item for item in CANARIES if item["kind"] == "random40")["value"]
        compared = 0
        for path, parser, slot in self.commands():
            for extra in ((), ("--json",), ("--verbose",)):
                known = ss.run_cli(self.world.ctx, *self.world.argv(path, parser, slot, "a1b2c3d4", extra))
                typed = ss.run_cli(self.world.ctx, *self.world.argv(path, parser, slot, canary, extra))
                where = f"{' '.join(path)} [{label_of(slot)}] {' '.join(extra) or '기본'}"
                self.assertEqual(typed[0], known[0], where)
                same = lambda result, word: (result[1] + result[2]).replace(word, "<값>")      # noqa: E731
                self.assertEqual(same(typed, PLACEHOLDER), same(known, "a1b2c3d4"), where)
                self.assertIn(PLACEHOLDER, typed[1] + typed[2], where)
                compared += 1
        self.assertEqual(compared, 72, "후보·글 번호 자리 24곳(P3 가 `topics show` 를, DB 가 `draft body` 를 더했다) × 변형 3가지")

    def test_an_ordinal_past_the_end_is_said_with_its_number_and_a_real_short_number_is_found(self):
        code, out, err = ss.run_cli(self.world.ctx, "candidates", "show", "999")
        self.assertEqual(code, 1)
        self.assertIn("「순번 999」", err)
        self.assertIn("후보는 1개뿐", out + err.replace("세부: ", ""))
        code, out, err = ss.run_cli(self.world.ctx, "candidates", "show", "1")
        self.assertEqual((code, err), (0, ""))
        code, out, err = ss.run_cli(self.world.ctx, "show", self.world.project)
        self.assertEqual((code, err), (0, ""))

    def test_a_backup_made_by_the_app_is_still_named_in_the_confirmation_and_any_other_name_is_not(self):
        made = ss.run_cli(self.world.ctx, "backup")
        self.assertEqual(made[0], 0, made)
        name = sorted(path.name for path in self.world.ctx.workspace.backups_dir.glob("chanceblog-*.db"))[-1]
        code, out, err = ss.run_cli(self.world.ctx, "restore", str(self.world.ctx.workspace.backups_dir / name))
        self.assertEqual(code, 1)
        self.assertIn(f"「백업으로 되돌리기 — {name}」", err)
        code, out, err = ss.run_cli(self.world.ctx, "restore", "--latest")
        self.assertEqual(code, 1)
        self.assertIn("백업으로 되돌리기 — chanceblog-", err)
        code, out, err = ss.run_cli(self.world.ctx, "restore", "내백업.db")
        self.assertEqual(code, 1)
        self.assertIn(f"「백업으로 되돌리기 — {echo.TYPED_FILE}」", err)
        self.assertNotIn("내백업", out + err)

    def test_a_missing_backup_named_by_the_app_shape_fails_with_the_name_and_a_foreign_one_without_it(self):
        folder = self.world.ctx.workspace.backups_dir
        code, out, err = ss.run_cli(self.world.ctx, "restore", "chanceblog-20200101-000000.db", "--yes")
        self.assertEqual(code, 1, (out, err))
        self.assertIn("chanceblog-20200101-000000.db", err, "앱이 만드는 이름 모양이면 되풀이한다")
        code, out, err = ss.run_cli(self.world.ctx, "restore", str(folder / "없는파일.db"), "--yes")
        self.assertEqual(code, 1, (out, err))
        self.assertNotIn("없는파일", out + err)
        self.assertIn(echo.TYPED_FILE, err)
        self.assertNotIn(str(folder), out + err, "친 경로(폴더)도 되풀이하지 않는다")

    def test_an_existing_file_that_is_not_a_database_is_never_named_by_its_typed_name_or_path(self):
        """검증 지적(restore 오류 칸 정리의 '이름' 갈래를 지키는 시험이 없었다 — `_without_typed_backup` 이 이름 비교를 빼도 모든 시험이 통과했다): 폴더 안의 키 모양 이름 `<키>.db`(있지만 데이터베이스가 아닌 파일)를
        `restore <경로> --yes` 로 고르면 오류가 파일 이름만 칸에 담는다 — 화면·`--json`·`--verbose` 어디에도 그 이름·경로가 없고 `(입력한 파일)` 로 나온다."""
        world = World(True)
        self.addCleanup(world.close)
        key = "Qm7Xc2Vb9Nk4Lp8Rt3Wz6Yh1Jd5Sf0GaPq"
        folder = world.root / "somewhere"
        folder.mkdir()
        target = folder / f"{key}.db"
        target.write_bytes(b"not a database " * 50)
        for extra in ((), ("--json",), ("--verbose",)):
            with self.subTest(extra=extra):
                code, out, err = ss.run_cli(world.ctx, "restore", str(target), "--yes", *extra)
                self.assertEqual(code, 1, (out, err))
                shown = json.dumps(json.loads(out), ensure_ascii=False) if "--json" in extra else out + err
                self.assertIn(echo.TYPED_FILE, shown)
                for piece in (key, key[:12], key[-12:], str(folder), str(target)):
                    self.assertNotIn(piece, shown)


# ---- 5) 진짜 프로세스 ----------------------------------------------------------------------------------------------------------------------
class ProcessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.root = Path(cls.tmp.name)
        cls.data = cls.root / "데이터 폴더"
        cls.env = {**ss.env_without_repo(), "PYTHONPATH": str(ss.ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}          # 부모 환경이 ascii 여도 자식의 한글 출력을 읽을 수 있게(cp949 시험은 아래에서 따로 바꾼다)
        for argv in (("candidates", "add", "--topic", "겨울 난방비 줄이기", "--keyword", "난방비", "--blog", "github_pages"), ("new", "--title", "글 하나", "--text", "본문입니다 " * 30)):
            code, out, err = cls.launch(*argv)
            assert code == 0, (out, err)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def launch(cls, *argv, cp949=False):
        """진짜 프로세스로 한 번 → (종료 코드, 표준 출력, 표준 오류). cp949=True 면 한국어 윈도 콘솔처럼 `-X utf8` 없이 cp949 로 출력한다."""
        env = dict(cls.env)
        if cp949:
            env.update({"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp949"})
            command = [sys.executable, "-m", "chanceblog_desktop", "--data-dir", str(cls.data), *argv]
            encoding = "cp949"
        else:
            env.update({"PYTHONUTF8": "1"})
            command = [sys.executable, "-X", "utf8", "-m", "chanceblog_desktop", "--data-dir", str(cls.data), *argv]
            encoding = "utf-8"
        flags = {"creationflags": HIDDEN_FLAG} if os.name == "nt" else {}
        done = subprocess.run(command, input=b"", capture_output=True, env=env, cwd=cls.root, timeout=180, **flags)
        return done.returncode, done.stdout.decode(encoding, "replace"), done.stderr.decode(encoding, "replace")

    def values(self, *kinds):
        return [item for item in CANARIES if item["kind"] in kinds]

    def check(self, argv, canary, *, cp949=False):
        code, out, err = self.launch(*argv, cp949=cp949)
        text = out + err
        self.assertNotIn("Traceback", err, argv[:2])
        self.assertIn(code, (1, 2), (argv[:2], out, err))
        self.assertEqual(scan_text(text, needles_of(canary)), [], (argv[:2], canary["kind"]))
        return code, out, err

    @staticmethod
    def fill(template, value):
        return [value if part == "{k}" else part for part in template]

    def test_fourteen_commands_of_a_real_process_never_repeat_a_key_typed_in_the_number_slot(self):
        commands = (("candidates", "show", "{k}"), ("candidates", "select", "{k}", "--blog", "github_pages"), ("candidates", "hold", "{k}"), ("candidates", "delete", "{k}", "--yes"),
                    ("candidates", "link", "1", "{k}"), ("candidates", "unlink", "{k}"), ("draft", "plan", "{k}"), ("show", "{k}"), ("edit", "{k}", "--title", "x"), ("publish-pages", "{k}", "--yes"),
                    ("naver-package", "{k}", "--blog", "naver_a"), ("restore", "{k}"), ("restore", "{k}", "--yes"), ("--json", "show", "{k}"), ("--verbose", "show", "{k}"))
        count = 0
        for canary in self.values("random40", "sk-project"):
            for template in commands:
                with self.subTest(command=" ".join(template), kind=canary["kind"]):
                    self.check(self.fill(template, canary["value"]), canary)
                    count += 1
        self.assertGreaterEqual(count, 30)

    def test_the_same_holds_on_a_cp949_console_and_for_values_with_spaces_and_quote_marks(self):
        for template in (("candidates", "show", "{k}"), ("show", "{k}"), ("restore", "{k}", "--yes"), ("--json", "show", "{k}")):
            for canary in self.values("random40", "hangul-around"):
                with self.subTest(command=" ".join(template), kind=canary["kind"], console="cp949"):
                    self.check(self.fill(template, canary["value"]), canary, cp949=True)
        maker = Maker(77)
        for pattern in ("{a} {b}", '"{a}" {b}', "'{a}'&{b}", "{a}%PATH%{b}"):
            core = maker.text(36)
            canary = {"kind": "spaces-and-marks", "value": pattern.format(a=core[:18], b=core[18:]), "core": core[:18]}
            with self.subTest(pattern=pattern):
                self.check(self.fill(("show", "{k}"), canary["value"]), canary)

    def test_a_key_given_through_a_shell_command_line_is_not_repeated_either(self):
        """셸이 인용 부호를 풀고 넘기는 경우(`cmd /c`·`sh -c`) — 한 줄로 이어 쳐도 같다."""
        canary = next(item for item in CANARIES if item["kind"] == "random40")
        value = canary["value"]
        line = f'"{sys.executable}" -X utf8 -m chanceblog_desktop --data-dir "{self.data}" show "{value}"'
        env = {**self.env, "PYTHONUTF8": "1"}
        flags = {"creationflags": HIDDEN_FLAG} if os.name == "nt" else {}
        done = subprocess.run(line, shell=True, input=b"", capture_output=True, env=env, cwd=self.root, timeout=180, **flags)
        text = done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
        self.assertEqual(done.returncode, 1, text)
        self.assertEqual(scan_text(text, needles_of(canary)), [])
        self.assertIn(PLACEHOLDER, text)

    def test_numbers_are_still_repeated_by_a_real_process_and_nothing_was_written(self):
        code, out, err = self.launch("show", "a1b2c3d4")
        self.assertEqual(code, 1)
        self.assertIn("글을 찾을 수 없습니다: 「a1b2c3d4」", err)
        code, out, err = self.launch("candidates", "show", "999")
        self.assertEqual(code, 1)
        self.assertIn("「순번 999」", err)
        for canary in CANARIES:
            self.assertEqual(scan_tree(self.data, needles_of(canary)), [], canary["kind"])


def setUpModule():
    ss.external_write_on()                                   # 이 시험은 게시 흐름을 쓴다 — 외부 Write 관문을 임시로만 연다(소스 상수는 False — PCSEC1 H3)


def tearDownModule():
    ss.external_write_off()


if __name__ == "__main__":
    unittest.main()
