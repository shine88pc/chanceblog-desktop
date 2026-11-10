"""기존 글 읽기 기반(`service/own_posts.py` — 화면 없음, 운영자 확정 범위, 결정 D-325–D-329) 시험. **전부 임시 폴더**(이 PC 의 실제 글·데이터 폴더는 읽지도 쓰지도 않는다). 네트워크·실제 시크릿 없이 돈다.

지키는 것:
  1) 운영자가 확정한 범위 — 상수 값(최대 2개·파일당 2MB·10만 자·txt 와 md 둘뿐)·개수(0·1·2·3·같은 파일 두 번)·경로 종류(폴더·없는 파일·와일드카드·인터넷 주소 모양·네트워크 위치·NUL 든 경로·빈 글·상대 경로)·
     확장자(대소문자·다른 형식)·크기(2MB 정확히·+1 바이트·읽는 중 커짐)·글자표(UTF-8·BOM·CP949·깨진 바이트·NUL)·빈 글·10만 자 정확히와 10만 + 1자.
  2) 읽기 전용 — 읽은 뒤 파일 바이트·수정 시각 불변, 같은 폴더에 새 파일 0, 임시 파일·캐시 0, 열기는 모드 `rb` 한 번뿐, 파일 핸들은 바로 닫힌다.
  3) 오류에 경로·파일 이름·글 내용이 없다 — 예외·`repr`·`args`·`slots`·`detail`·`log_line`·렌더링 문구·추적 기록·앞 오류 연결·로그·표준 출력에 어느 것도 되풀이되지 않는다(OS 오류가 경로를 실어 와도).
  4) 네트워크 0 — `socket`·`urllib`·`http`·`ssl` 의 입구를 막고 실행해도 통과하고, 소스가 그런 부품을 가져오지 않는다(서비스 층 전체 규칙은 `test_service_safety`).
  5) 링크·재해석 지점은 따라가지 않는다(심볼릭 링크·윈도 정션 — 만들 수 없는 환경이면 이유를 보이며 건너뛴다, 모의 상태 정보로 모든 운영체제에서 규칙 자체를 확인), 클라우드에만 있는 파일은 열지 않는다.
CI 는 윈도·리눅스 × 3.10·3.12 네 칸이다 — 운영체제에 따라 다른 시험은 `skipUnless`/`skipIf` 와 이유를 적었다.
"""
import ast
import builtins
import contextlib
import dataclasses
import hashlib
import io
import os
import random
import stat
import subprocess
import sys
import tempfile
import threading
import traceback
import types
import unittest
import warnings
from pathlib import Path, PurePath
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from chanceblog_desktop.errors import AppError, clean_slot  # noqa: E402
from chanceblog_desktop.errors.render import MAX_SLOT_CHARS  # noqa: E402
from chanceblog_desktop.service import own_posts as op  # noqa: E402
from chanceblog_desktop.service import topics as topics_service  # noqa: E402

SOURCE = ROOT / "src" / "chanceblog_desktop" / "service" / "own_posts.py"
REAL_OPEN = builtins.open
BS = chr(92)
TILDE = chr(0x7E)                      # 물결표 — 글자 상수에 직접 쓰지 않는다(새 글에 물결표를 쓰지 않는 규칙을 이 파일도 지킨다)
MB = 1024 * 1024
SAYS = {                     # 거절 문장에 들어 있어야 하는 말(문장이 바뀌면 이 표도 의식적으로 함께 고친다)
    "count": "한 번에 1개에서 2개까지만 고를 수 있어요", "list": "고른 파일 목록의 모양이 올바르지 않아요", "same": "같은 파일을 두 번 골랐어요", "path": "파일 위치가 올바르지 않아요",
    "network": "인터넷 주소나 네트워크 위치의 파일은 읽지 않아요", "suffix": "이 형식은 아직 읽지 않아요", "reserved": "장치 이름으로 쓰이는 파일 이름은 읽지 않아요",
    "missing": "파일을 읽을 수 없어요", "not_file": "글 파일이 아니에요", "link": "링크로 연결된 파일은 읽지 않아요", "cloud": "내려받지 않은 파일이에요",
    "big": "파일이 너무 커요. 2MB 이하 파일만 읽어요", "binary": "글 파일이 아닌 것 같아요", "encoding": "글자 모양을 읽을 수 없어요", "empty": "읽을 글이 없어요",
    "long": "글이 너무 길어요. 100,000자 이하만 읽어요", "changed": "고른 뒤에 파일이 바뀐 것 같아요",
}
UNIQUE_DIR, UNIQUE_NAME, UNIQUE_BODY = "uniq-dir-zq7k3j9x", "uniq-name-w5p2m8-제목", "UNIQ-BODY-r4t6y8-본문"


# ---- 도우미 -----------------------------------------------------------------------------------------------------------------------
class FakeFile:
    """`open` 이 돌려주는 가짜 파일 — 읽기 요청 크기를 기록하고, 크기 없이 통째로 읽으면 실패한다(상한 + 1 바이트까지만 읽는지 확인한다).
    `fileno()` 는 진짜 파일 핸들(`OpenRecorder` 가 같은 경로를 따로 열어 붙여 준다)의 것을 빌려 준다 — 읽기 길이 연 핸들의 `fstat` 으로 검사 때와 같은 파일인지 견주기 때문이다(OWNFIX D2)."""

    def __init__(self):
        self.requests, self.closed, self.delivered, self.real = [], False, 0, None

    def attach(self, real):
        self.real = real
        return self

    def fileno(self):
        return self.real.fileno()

    def read(self, size=-1):
        if size is None or size < 0:
            raise AssertionError("크기 없이 통째로 읽었다")
        if size > op.MAX_FILE_BYTES + 1 - self.delivered:
            raise AssertionError("남은 허용량(상한 + 1 바이트)보다 많이 요청했다")
        self.requests.append(size)
        data = self.serve(size)
        self.delivered += len(data)
        return data

    def __enter__(self):
        return self

    def __exit__(self, *error):
        self.close()
        return False

    def close(self):
        self.closed = True
        if self.real is not None:
            self.real.close()


class EndlessFile(FakeFile):
    """읽을 때마다 요청한 만큼 주는 끝없는 파일 — 읽는 동안 계속 커지는 파일 흉내."""

    def serve(self, size):
        return b"a" * size


class SizedFile(FakeFile):
    """정해진 바이트만 주고 끝나는 파일."""

    def __init__(self, total):
        super().__init__()
        self.left = total

    def serve(self, size):
        give = min(size, self.left)
        self.left -= give
        return b"a" * give


class ChunkedFile(FakeFile):
    """한 번에 `chunk` 바이트까지만 돌려주는 파일(짧게 읽히는 경우)."""

    def __init__(self, data, chunk):
        super().__init__()
        self.buffer, self.chunk = io.BytesIO(data), chunk

    def serve(self, size):
        return self.buffer.read(min(size, self.chunk))


class RealBackedFile(FakeFile):
    """붙여 준 진짜 파일에서 읽되 읽은 바이트 수와 요청 크기를 센다 — 읽는 중 커지는 진짜 파일에서 상한 + 1 바이트까지만 읽는지 본다."""

    def serve(self, size):
        return self.real.read(size)


class OpenRecorder:
    """내장 `open` 을 대신 끼워 호출을 기록한다 — `fakes`({정리한 경로: 가짜 파일})에 있는 경로는 가짜 파일을, 없으면 진짜 `open` 을 쓴다."""

    def __init__(self, fakes=None):
        self.calls, self.fakes = [], dict(fakes or {})

    def __call__(self, file, mode="r", *args, **kwargs):
        self.calls.append((os.fspath(file), mode, args, kwargs))
        fake = self.fakes.get(os.path.normcase(os.fspath(file)))
        return fake.attach(REAL_OPEN(file, "rb")) if fake is not None else REAL_OPEN(file, mode, *args, **kwargs)


class DoctoredStat:
    """진짜 상태 정보를 베끼고 몇 칸만 바꾼 모의 정보(윈도의 재해석 지점·오프라인 표시를 모든 운영체제에서 흉내 낸다)."""

    def __init__(self, real, **override):
        for name in ("st_mode", "st_size", "st_ino", "st_dev"):
            setattr(self, name, getattr(real, name))
        for name, value in override.items():
            setattr(self, name, value)


def fake_key(path):
    return os.path.normcase(str(path))


def snapshot(root):
    """폴더 전체의 (종류·크기·수정 시각·내용 해시) — 읽은 뒤에 바뀐 것이 없는지 견준다."""
    state = {}
    for path in sorted(Path(root).rglob("*")):
        info = path.lstat()
        is_file = stat.S_ISREG(info.st_mode)
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if is_file else ""
        state[path.relative_to(root).as_posix()] = (stat.S_IFMT(info.st_mode), info.st_size if is_file else 0, info.st_mtime_ns, digest)
    return state


def unc(*parts):
    """네트워크 위치 모양의 글(`\\\\서버\\공유\\…`) — 백슬래시를 글자 상수에 직접 쓰지 않고 만든다."""
    return BS * 2 + BS.join(parts)


def channels(error):
    """오류가 사람이나 기록에 나갈 수 있는 모든 글(예외 글·`repr`·인자·칸·세부·기록 한 줄·렌더링 문구·행동 안내·추적 기록)."""
    shown = error.rendered()
    trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    return {"str": str(error), "repr": repr(error), "args": repr(error.args), "slots": repr(error.slots), "detail": error.detail, "log": error.log_line(), "message": shown.message,
            "action": shown.action, "retry": shown.retry_text, "trace": trace}


def holds_content(value, markers, big=4096, depth=0):
    """값(과 그 안의 목록·사전·객체 속성)에 표식 글이 있거나 `big` 보다 긴 글·바이트가 있는가 — 호출 흔적이 붙든 지역 변수에 글이 남았는지 보는 눈이다."""
    if isinstance(value, (str, bytes, bytearray)):
        if len(value) > big:
            return True
        kind = str if isinstance(value, str) else bytes
        return any(marker in value for marker in markers if isinstance(marker, kind))
    if depth >= 3:
        return False
    if isinstance(value, dict):
        return any(holds_content(item, markers, big, depth + 1) for item in list(value.values()))
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(holds_content(item, markers, big, depth + 1) for item in list(value))
    if hasattr(value, "__dict__") and not callable(value) and not isinstance(value, types.ModuleType):
        return any(holds_content(item, markers, big, depth + 1) for item in list(vars(value).values()))
    return False


def leaking_locals(error, markers, big=4096):
    """오류의 호출 흔적이 붙든 모든 틀의 지역 변수 가운데 글을 담은 것 → ['함수.변수', …]."""
    found, trace = [], error.__traceback__
    while trace is not None:
        frame = trace.tb_frame
        for name, value in list(frame.f_locals.items()):
            if holds_content(value, markers, big):
                found.append(f"{frame.f_code.co_name}.{name}")
        trace = trace.tb_next
    return found


class OwnCase(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="own-posts-")
        self.addCleanup(holder.cleanup)
        self.root = Path(os.path.realpath(holder.name))              # 임시 폴더 위쪽에 링크가 있어도 풀어 둔다(링크는 거절 대상이므로)

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def abs_name(self, name):
        return str(self.root) + os.sep + name

    def refused(self, paths, key):
        """`paths` 를 읽으면 `CONTENT_INVALID` 로 거절되고 문장에 `SAYS[key]` 가 있다 — 오류 객체를 돌려준다."""
        with self.assertRaises(AppError) as caught:
            op.read_own_files(paths)
        error = caught.exception
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertEqual(error.requested_code, "CONTENT_INVALID")
        shown = error.slots["항목"]
        self.assertTrue(shown.startswith("기존 글 파일 — "), shown)
        self.assertIn(SAYS[key], shown)
        return error

    def make_symlink(self, link, target, directory=False):
        try:
            os.symlink(target, link, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"이 환경에서는 심볼릭 링크를 만들 수 없다({type(error).__name__}) — 윈도는 개발자 모드나 관리자 권한이 있어야 한다")

    def doctor_lstat(self, path, **override):
        """`path` 하나의 `os.lstat` 결과만 바꿔 돌려준다(나머지 경로는 진짜 값)."""
        target, real = fake_key(path), os.lstat

        def fake(candidate, *args, **kwargs):
            info = real(candidate, *args, **kwargs)
            return DoctoredStat(info, **override) if fake_key(candidate) == target else info

        return mock.patch.object(os, "lstat", fake)

    def doctor_fstat(self, **override):
        """읽기 길이 연 핸들의 `os.fstat` 결과를 바꿔 돌려준다 — 값이 함수면 진짜 값을 넣어 부른다(예: 파일 번호 + 1)."""
        real = os.fstat

        def fake(descriptor):
            info = real(descriptor)
            return DoctoredStat(info, **{name: (value(getattr(info, name)) if callable(value) else value) for name, value in override.items()})

        return mock.patch.object(os, "fstat", fake)

    def after_the_check(self, change):
        """검사(`_inspect_all`)가 끝난 바로 뒤에 `change()` 를 불러 같은 이름을 바꿔치는 경쟁 상태를 흉내 낸다."""
        real = op._inspect_all

        def hooked(pures):
            infos = real(pures)
            change()
            return infos

        return mock.patch.object(op, "_inspect_all", hooked)

    def assert_absent(self, error, secrets, label=""):
        """오류가 나갈 수 있는 모든 글 어디에도 `secrets` 가 없고 앞 오류(OS 오류)가 따라붙지 않았다."""
        self.assertIsNone(error.__cause__, label)
        self.assertIsNone(error.__context__, label)
        for channel, text in channels(error).items():
            for secret in secrets:
                self.assertNotIn(secret, text, f"{label}: {channel} 에 {secret[:12]} 가 있다")


# ---- 1) 상수·값 -------------------------------------------------------------------------------------------------------------------
class ConstantsAndValueTest(unittest.TestCase):
    def test_the_limits_are_the_values_the_operator_confirmed(self):
        self.assertEqual(op.MAX_FILES, 2)
        self.assertEqual(op.MAX_FILE_BYTES, 2 * 1024 * 1024)
        self.assertEqual(op.MAX_TEXT_CHARS, 100_000)
        self.assertEqual(op.ALLOWED_SUFFIXES, (".txt", ".md"))

    def test_the_file_size_limit_is_the_same_constant_as_the_post_reading_rule(self):
        """글 파일 하나의 상한은 연결 저장소 글을 읽는 규칙(`topics.MAX_POST_BYTES`)과 같은 값이다 — 한쪽만 바뀌면 여기서 걸린다."""
        self.assertEqual(op.MAX_FILE_BYTES, topics_service.MAX_POST_BYTES)

    def test_the_result_value_is_frozen_and_keeps_only_the_text_its_length_and_the_charset_name(self):
        value = op.OwnText("가나다", 3)
        self.assertEqual([item.name for item in dataclasses.fields(value)], ["text", "chars", "encoding"])
        self.assertEqual(value.encoding, "utf-8")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.text = "x"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.chars = 1
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.encoding = "cp949"
        self.assertNotIn("가나다", repr(value))
        self.assertIn("chars=3", repr(value))
        self.assertIn("encoding='utf-8'", repr(value))
        self.assertEqual(value, op.OwnText("가나다", 3))
        self.assertEqual(hash(value), hash(op.OwnText("가나다", 3)))
        self.assertEqual(op.OwnText("가나다", 3, "cp949").encoding, "cp949")
        self.assertNotEqual(value, op.OwnText("가나다", 3, "cp949"))
        self.assertEqual(op.ENCODINGS, ("utf-8", "cp949"))

    def test_a_value_whose_char_count_or_charset_name_does_not_match_cannot_be_built(self):
        cases = (("가나", 3, "utf-8"), ("가나", 1, "utf-8"), ("", 1, "utf-8"), ("a", True, "utf-8"), (b"ab", 2, "utf-8"), (None, 0, "utf-8"),
                 ("가나", 2, "latin-1"), ("가나", 2, "UTF-8"), ("가나", 2, "utf-8-sig"), ("가나", 2, None), ("가나", 2, ""), ("가나", 2, ["utf-8"]))
        for text, chars, encoding in cases:
            with self.subTest(text=type(text).__name__, chars=chars, encoding=encoding):
                with self.assertRaises(ValueError) as caught:
                    op.OwnText(text, chars, encoding)
                self.assertNotIn("가나", str(caught.exception))

    def test_every_refusal_sentence_fits_the_message_slot_and_is_plain(self):
        sentences = {name: value for name, value in vars(op).items() if name.startswith("_R_")}
        self.assertEqual(len(sentences), 17)
        for name, sentence in sentences.items():
            with self.subTest(name=name):
                shown = f"{op.SUBJECT} — {sentence}"
                self.assertLessEqual(len(shown), MAX_SLOT_CHARS, "안내 칸의 길이 상한을 넘으면 문장이 잘린다")
                self.assertEqual(clean_slot(shown), shown)
                for bad in (TILDE, "http", "「", "」", "**", BS):
                    self.assertNotIn(bad, shown)

    def test_the_refusal_is_rendered_with_the_whole_sentence_by_the_error_catalog(self):
        for key in ("count", "suffix", "empty", "long"):
            sentence = {"count": op._R_COUNT, "suffix": op._R_SUFFIX, "empty": op._R_EMPTY, "long": op._R_LONG}[key]
            with self.subTest(key=key):
                shown = op._refuse(sentence).rendered()
                self.assertIn(SAYS[key], shown.message)
                self.assertNotIn("…", shown.message)
                self.assertTrue(shown.action)


# ---- 2) 개수 ----------------------------------------------------------------------------------------------------------------------
class CountTest(OwnCase):
    def test_one_file_and_two_files_are_read_in_the_given_order(self):
        first, second = self.put("a.txt", "첫째 글"), self.put("b.md", "둘째 글")
        one = op.read_own_files([first])
        self.assertEqual([item.text for item in one], ["첫째 글"])
        both = op.read_own_files([first, second])
        self.assertEqual([item.text for item in both], ["첫째 글", "둘째 글"])
        self.assertEqual([item.text for item in op.read_own_files((second, first))], ["둘째 글", "첫째 글"])
        self.assertIsInstance(both, tuple)
        self.assertEqual([item.chars for item in both], [4, 4])

    def test_zero_or_three_files_are_refused(self):
        files = [self.put(f"f{number}.txt", "내용") for number in range(3)]
        self.refused([], "count")
        self.refused((), "count")
        self.refused(files, "count")
        self.refused(files * 2, "count")

    def test_the_same_file_twice_is_refused_before_anything_is_read_or_even_looked_at(self):
        """같은 경로를 두 번 고른 것은 글자 모양만으로 알 수 있으므로 파일 시스템에 묻기 전에 거절한다."""
        path = self.put("a.txt", "내용")
        with mock.patch("builtins.open", side_effect=AssertionError("읽으면 안 된다")), mock.patch.object(os, "lstat", side_effect=AssertionError("파일 시스템에 물으면 안 된다")):
            self.refused([path, path], "same")
            self.refused([str(path), path], "same")

    def test_other_spellings_of_the_same_path_are_the_same_file(self):
        path = self.put("sub/a.txt", "내용")
        spellings = (str(path), self.root / "sub" / "." / "a.txt", str(self.root) + os.sep + "sub" + os.sep + os.sep + "a.txt", str(path).replace(os.sep, "/"))
        for other in spellings:
            with self.subTest(other=str(other)[len(str(self.root)):]):
                self.refused([path, other], "same")

    def test_a_hard_link_is_the_same_file_too(self):
        first = self.put("a.txt", "내용")
        second = self.root / "b.txt"
        try:
            os.link(first, second)
        except (OSError, NotImplementedError, AttributeError) as error:
            self.skipTest(f"이 환경에서는 하드 링크를 만들 수 없다({type(error).__name__}) — 같은 파일 판별은 파일 번호 비교로 한다")
        self.refused([first, second], "same")

    def test_two_different_files_with_the_same_content_are_two_files(self):
        first, second = self.put("a.txt", "같은 글"), self.put("b.txt", "같은 글")
        self.assertEqual([item.text for item in op.read_own_files([first, second])], ["같은 글", "같은 글"])

    def test_files_that_report_no_file_number_are_not_taken_for_the_same_file(self):
        """파일 번호를 못 주는 파일 시스템(번호 0)의 우연한 일치를 같은 파일로 보지 않는다."""
        first, second = self.put("a.txt", "첫째 글"), self.put("b.txt", "둘째 글")
        names, real = {fake_key(first), fake_key(second)}, os.lstat

        def numberless(candidate, *args, **kwargs):
            info = real(candidate, *args, **kwargs)
            return DoctoredStat(info, st_ino=0, st_dev=7) if fake_key(candidate) in names else info

        with mock.patch.object(os, "lstat", numberless):
            self.assertEqual([item.text for item in op.read_own_files([first, second])], ["첫째 글", "둘째 글"])

    def test_two_names_that_report_the_same_file_number_are_the_same_file_even_without_a_hard_link(self):
        first, second = self.put("a.txt", "첫째 글"), self.put("b.txt", "둘째 글")
        names, real = {fake_key(first), fake_key(second)}, os.lstat

        def one_file(candidate, *args, **kwargs):
            info = real(candidate, *args, **kwargs)
            return DoctoredStat(info, st_ino=12345, st_dev=7) if fake_key(candidate) in names else info

        with mock.patch.object(os, "lstat", one_file), mock.patch("builtins.open", side_effect=AssertionError("읽으면 안 된다")):
            self.refused([first, second], "same")

    def test_files_with_the_same_file_number_on_different_devices_are_two_files(self):
        """파일 번호는 같아도 장치 번호가 다르면 다른 파일이다 — 번호만 견주면 둘째 파일을 같은 파일로 잘못 거절한다(검증자 변이 V09, OWNFIX D4). 읽을 때의 `fstat` 도 같은 모의 값을 낸다."""
        first, second = self.put("a.txt", "첫째 글"), self.put("b.txt", "둘째 글")
        device = {fake_key(first): 7, fake_key(second): 8}
        by_real_number = {os.lstat(first).st_ino: 7, os.lstat(second).st_ino: 8}
        real_lstat, real_fstat = os.lstat, os.fstat

        def lstat(candidate, *args, **kwargs):
            info = real_lstat(candidate, *args, **kwargs)
            return DoctoredStat(info, st_ino=12345, st_dev=device[fake_key(candidate)]) if fake_key(candidate) in device else info

        def fstat(descriptor):
            info = real_fstat(descriptor)
            return DoctoredStat(info, st_ino=12345, st_dev=by_real_number[info.st_ino]) if info.st_ino in by_real_number else info

        with mock.patch.object(os, "lstat", lstat), mock.patch.object(os, "fstat", fstat):
            self.assertEqual([item.text for item in op.read_own_files([first, second])], ["첫째 글", "둘째 글"])

    @unittest.skipUnless(os.name == "nt", "윈도 전용: 윈도는 파일 이름의 대소문자를 구분하지 않는다")
    def test_on_windows_a_different_capitalization_is_the_same_file(self):
        path = self.put("Notes.TXT", "내용")
        self.refused([path, str(path).lower()], "same")
        self.refused([str(path).upper(), path], "same")
        with mock.patch.object(os, "lstat", side_effect=AssertionError("파일 시스템에 물으면 안 된다")):          # 대소문자만 다른 같은 경로는 글자 모양만으로도 알 수 있다
            self.refused([path, str(path).lower()], "same")

    @unittest.skipIf(os.name == "nt", "윈도는 대소문자만 다른 이름을 같은 파일로 본다 — 위 시험이 그쪽을 다룬다")
    def test_on_a_case_sensitive_system_names_that_differ_in_case_are_two_files(self):
        first, second = self.put("Note.txt", "큰 글"), self.put("note.txt", "작은 글")
        if len(os.listdir(self.root)) != 2:
            self.skipTest("이 파일 시스템은 대소문자를 구분하지 않는다")
        self.assertEqual([item.text for item in op.read_own_files([first, second])], ["큰 글", "작은 글"])

    def test_a_single_path_or_anything_but_a_list_or_tuple_is_refused(self):
        path = self.put("a.txt", "내용")
        for value in (str(path), path, {str(path)}, {str(path): 1}, (item for item in [path]), None, 5, b"x", frozenset([path])):
            with self.subTest(kind=type(value).__name__):
                self.refused(value, "list")

    def test_when_the_second_path_is_bad_the_first_is_not_even_opened(self):
        good = self.put("a.txt", "내용")
        with mock.patch("builtins.open", side_effect=AssertionError("읽으면 안 된다")):
            self.refused([good, self.root / "missing.txt"], "missing")
            self.refused([good, self.root / "b.docx"], "suffix")


# ---- 3) 경로 종류 -----------------------------------------------------------------------------------------------------------------
class PathKindTest(OwnCase):
    def test_a_folder_is_refused_and_never_opened(self):
        named = self.root / "folder.txt"
        named.mkdir()
        plain = self.root / "plainfolder"
        plain.mkdir()
        with mock.patch("builtins.open", side_effect=AssertionError("폴더를 열면 안 된다")):
            self.refused([named], "not_file")
            self.refused([plain], "suffix")                      # 형식 이름이 없으면 형식에서 먼저 걸린다
            self.refused([self.root], "suffix")

    def test_a_missing_file_is_refused(self):
        self.refused([self.root / "missing.txt"], "missing")
        self.refused([self.root / "nofolder" / "missing.md"], "missing")

    def test_a_name_with_a_lone_surrogate_is_refused_without_an_unexpected_error(self):
        """짝 없는 서로게이트 글자는 운영체제 호출에서 인코딩 오류가 난다 — 그 오류도 고정 문장으로 바꿔 거절하고 글자는 되풀이하지 않는다."""
        error = self.refused([self.abs_name("a" + chr(0xD800) + ".txt")], "missing")
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self.assertNotIn(chr(0xD800), repr(error.slots) + error.detail + str(error))

    def test_a_bare_root_has_no_file_to_inspect(self):
        info, reason = op._inspect(Path(self.root.anchor))
        self.assertIsNone(info)
        self.assertIn(SAYS["missing"], reason)

    def test_wildcards_are_never_expanded(self):
        self.put("a.txt", "내용")
        for name in ("*.txt", "a?.txt", "?.txt", "*", "a*.md"):
            with self.subTest(name=name):
                self.refused([self.abs_name(name)], "path")

    def test_internet_address_shapes_are_refused_as_a_network_place(self):
        for scheme in ("http", "https", "ftp", "ftps", "file", "data", "mailto", "javascript", "ws", "sftp", "smb", "HTTP", "FILE", "a1"):
            for text in (f"{scheme}://host.invalid/a.txt", f"{scheme}:a.txt", f"{scheme}:/a.txt", f"{scheme}:///a.md", "  " + f"{scheme}://host.invalid/a.md"):
                with self.subTest(text=text):
                    self.refused([text], "network")

    def test_network_places_are_refused_in_every_spelling(self):
        shapes = (unc("srv", "share", "a.txt"), "//srv/share/a.txt", BS + "/srv/share/a.txt", "/" + BS + "srv/share/a.txt", "///srv/share/a.txt", unc("?", "C:", "a.txt"),
                  unc("?", "UNC", "srv", "share", "a.txt"), unc(".", "COM1"), unc("srv"), "//srv")
        for shape in shapes:
            with self.subTest(shape=shape):
                self.refused([shape], "network")
        for shape in (unc("srv", "share", "a.txt"), "//srv/share/a.txt"):
            with self.subTest(path=shape):
                self.refused([Path(shape)], "network")

    def test_a_path_object_with_a_broken_network_shape_is_refused_whatever_pathlib_makes_of_it(self):
        """`Path` 로 건네면 파이썬 판·운영체제에 따라 pathlib 가 모양을 먼저 고친다(3.10 윈도는 `//srv` 를 `\\srv` 로, 리눅스는 `///srv/x` 를 `/srv/x` 로) — 어느 쪽이든 아무것도 열지 않고 거절한다."""
        shapes = ("///srv/share/a.txt", "//srv", unc("srv"), unc(".", "COM1"), unc("?", "C:", "a.txt"), "//")
        with mock.patch("builtins.open", side_effect=AssertionError("열면 안 된다")):
            for shape in shapes:
                with self.subTest(path=shape):
                    with self.assertRaises(AppError) as caught:
                        op.read_own_files([Path(shape)])
                    self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_a_nul_or_other_control_character_in_the_path_is_refused(self):
        for name in ("a\x00.txt", "\x00", "line\nbreak.txt", "tab\there.txt", "bell\x07.txt", "del\x7f.txt", "\x1fa.txt", "ret\rurn.md"):
            with self.subTest(name=repr(name)):
                self.refused([self.abs_name(name)], "path")
        self.refused([self.abs_name("a.txt") + "\x00"], "path")

    def test_an_empty_or_blank_path_is_refused(self):
        for text in ("", " ", "   ", chr(0x3000), chr(0xA0) * 3):
            with self.subTest(text=repr(text)):
                self.refused([text], "path")

    def test_anything_but_a_string_or_a_path_is_refused(self):
        for value in (b"a.txt", 5, None, 1.5, object(), ["a.txt"], PurePath(str(self.root / "a.txt")), {"a": 1}):
            with self.subTest(kind=type(value).__name__):
                self.refused([value], "path")

    def test_a_relative_path_is_refused_even_when_the_file_is_there(self):
        self.put("a.txt", "내용")
        before = os.getcwd()
        self.addCleanup(os.chdir, before)
        os.chdir(self.root)
        for text in ("a.txt", "./a.txt", "sub/../a.txt", "../" + self.root.name + "/a.txt", Path("a.txt")):
            with self.subTest(text=str(text)):
                self.refused([text], "path")

    def test_a_dot_dot_part_in_an_absolute_path_is_refused(self):
        self.put("sub/a.txt", "내용")
        self.refused([str(self.root / "sub" / ".." / "sub" / "a.txt")], "path")
        self.refused([self.root / "sub" / ".." / "sub" / "a.txt"], "path")
        self.refused([self.abs_name("..")], "path")

    def test_a_colon_outside_the_drive_letter_is_refused_so_a_data_stream_cannot_be_named(self):
        for name in ("a.txt:stream", "a:b.txt", "a.md::data", "x:"):
            with self.subTest(name=name):
                self.refused([self.abs_name(name)], "path")

    def test_a_trailing_separator_and_a_very_long_path_are_refused(self):
        self.put("a.txt", "내용")
        self.refused([self.abs_name("a.txt") + os.sep], "path")
        self.refused([self.abs_name("a.txt") + "/"], "path")
        self.refused([self.abs_name("a" * op.MAX_PATH_CHARS + ".txt")], "path")
        self.refused([self.abs_name("a" * 1_000_000 + ".txt")], "path")

    def test_windows_device_names_are_refused_on_every_operating_system(self):
        names = ("CON.txt", "NUL.md", "con.TXT", "Prn.md", "AUX.txt", "COM1.txt", "com9.md", "LPT1.txt", "lpt9.MD", "COM¹.txt", "LPT³.md", "CONIN$.txt", "CONOUT$.md", "NUL.tar.md", "nul .md",
                 "CON .txt", "con..txt")
        for name in names:
            with self.subTest(name=name):
                self.refused([self.abs_name(name)], "reserved")

    def test_names_that_only_look_like_device_names_are_ordinary_files(self):
        for name in ("console.txt", "com0.md", "lpt10.txt", "aux2.txt", "nulls.md", "prn_a.txt", "concat.txt", "com.md", "icon.txt"):
            with self.subTest(name=name):
                path = self.put(name, "평범한 글 " + name)
                self.assertEqual(op.read_own_files([path])[0].text, "평범한 글 " + name)

    def test_ordinary_unusual_names_are_read(self):
        for name in ("내 글 (최종본).txt", "a b  c.md", "일기.2026.11.10.txt", "100%_진짜.md", "a#b&c;d.txt", "[초안] 글.md", "{brace}.txt", "it's.txt", "한글이름만.md", "a,b.txt"):
            with self.subTest(name=name):
                path = self.put(name, "글 " + name)
                self.assertEqual(op.read_own_files([path])[0].text, "글 " + name)

    def test_a_string_a_path_and_a_string_subclass_give_the_same_result(self):
        class Text(str):
            pass

        path = self.put("a.txt", "내용")
        for value in (str(path), path, Text(str(path))):
            self.assertEqual(op.read_own_files([value])[0].text, "내용")

    @unittest.skipUnless(os.name == "nt", "윈도 전용: 윈도는 슬래시와 역슬래시를 둘 다 경로 구분자로 쓴다")
    def test_on_windows_forward_slashes_work_like_backslashes(self):
        path = self.put("sub/a.txt", "내용")
        self.assertEqual(op.read_own_files([str(path).replace(os.sep, "/")])[0].text, "내용")

    def test_a_special_file_that_is_not_a_regular_file_is_refused_without_opening(self):
        path = self.put("a.txt", "내용")
        with self.doctor_lstat(path, st_mode=stat.S_IFCHR | 0o666), mock.patch("builtins.open", side_effect=AssertionError("장치를 열면 안 된다")):
            self.refused([path], "not_file")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "리눅스 전용: 이름 붙은 파이프(FIFO)는 이 운영체제에 없다")
    def test_a_named_pipe_is_refused_instead_of_hanging(self):
        pipe = self.root / "pipe.txt"
        os.mkfifo(pipe)
        outcome = []

        def attempt():
            try:
                op.read_own_files([pipe])
            except AppError as error:
                outcome.append(error)

        worker = threading.Thread(target=attempt, daemon=True)
        worker.start()
        worker.join(10)
        self.assertFalse(worker.is_alive(), "파이프를 열려다 멈췄다")
        self.assertEqual(len(outcome), 1)
        self.assertIn(SAYS["not_file"], outcome[0].slots["항목"])


# ---- 4) 확장자 --------------------------------------------------------------------------------------------------------------------
class SuffixTest(OwnCase):
    def test_only_txt_and_md_are_read_and_the_case_does_not_matter(self):
        for name in ("a.txt", "a.md", "A.TXT", "A.MD", "a.Txt", "a.mD", "a.exe.txt", "a.b.c.md", "내 글.TXT"):
            with self.subTest(name=name):
                path = self.put(name, "내용 " + name)
                self.assertEqual(op.read_own_files([path])[0].text, "내용 " + name)

    def test_every_other_form_is_refused_as_not_read_yet(self):
        for name in ("a.markdown", "a.html", "a.htm", "a.docx", "a.pdf", "a.json", "a.rst", "a.text", "a.mdx", "a.txt.exe", "a.md.exe", "a.exe", "a", "a.txt.", "a.md ", "a.txt.bak", ".txt",
                     ".md", "txt", "md", "a.TXT.HTM"):
            with self.subTest(name=name):
                self.refused([self.abs_name(name)], "suffix")

    def test_the_suffix_check_never_touches_the_file_system(self):
        with mock.patch.object(os, "lstat", side_effect=AssertionError("파일 시스템을 불렀다")), mock.patch("builtins.open", side_effect=AssertionError("열었다")):
            self.refused([self.abs_name("secret.docx")], "suffix")
            self.refused([self.abs_name("a.markdown")], "suffix")


# ---- 5) 크기·읽는 중 커짐 ---------------------------------------------------------------------------------------------------------
class SizeTest(OwnCase):
    def test_a_file_of_exactly_the_limit_passes_the_size_check_and_is_stopped_by_the_text_length_instead(self):
        path = self.put("limit.txt", b" " * op.MAX_FILE_BYTES)
        self.assertEqual(path.stat().st_size, 2 * MB)
        self.refused([path], "long")

    def test_one_byte_over_the_limit_is_refused_by_the_file_size_before_anything_is_opened(self):
        path = self.put("over.txt", b"a" * (op.MAX_FILE_BYTES + 1))
        with mock.patch("builtins.open", side_effect=AssertionError("큰 파일을 열었다")):
            self.refused([path], "big")

    def test_a_file_that_grows_while_it_is_read_is_cut_off_at_the_limit_plus_one_byte(self):
        path = self.put("a.txt", "작은 글")
        endless = EndlessFile()
        recorder = OpenRecorder({fake_key(path): endless})
        with mock.patch("builtins.open", recorder):
            self.refused([path], "big")
        self.assertEqual(len(recorder.calls), 1)
        self.assertEqual(recorder.calls[0][1:], ("rb", (), {}))
        self.assertEqual(sum(endless.requests), op.MAX_FILE_BYTES + 1)
        self.assertEqual(endless.delivered, op.MAX_FILE_BYTES + 1)
        self.assertTrue(all(isinstance(size, int) and size > 0 for size in endless.requests))
        self.assertTrue(endless.closed, "파일을 닫지 않았다")

    def test_the_boundary_between_the_size_refusal_and_the_length_refusal_is_exactly_the_limit(self):
        for size, key in ((op.MAX_FILE_BYTES - 1, "long"), (op.MAX_FILE_BYTES, "long"), (op.MAX_FILE_BYTES + 1, "big")):
            with self.subTest(size=size):
                path = self.put("a.txt", "작은 글")
                fake = SizedFile(size)
                with mock.patch("builtins.open", OpenRecorder({fake_key(path): fake})):
                    self.refused([path], key)
                self.assertLessEqual(fake.delivered, op.MAX_FILE_BYTES + 1)

    def test_a_file_object_that_returns_short_reads_is_read_to_the_end(self):
        data = ("가나다라마바사 " * 50).encode("utf-8")
        path = self.put("a.txt", "작은 글")
        fake = ChunkedFile(data, 7)
        with mock.patch("builtins.open", OpenRecorder({fake_key(path): fake})):
            result = op.read_own_files([path])
        self.assertEqual(result[0].text, data.decode("utf-8"))
        self.assertGreater(len(fake.requests), len(data) // 7)
        self.assertTrue(fake.closed)

    def test_the_two_files_are_each_limited_separately(self):
        first, second = self.put("a.txt", "첫째 글"), self.put("b.txt", b"b" * (op.MAX_FILE_BYTES + 1))
        self.refused([first, second], "big")


# ---- 6) 글자표 --------------------------------------------------------------------------------------------------------------------
class EncodingTest(OwnCase):
    def test_utf8_text_is_read_unchanged(self):
        text = "안녕하세요. 첫 문단입니다.\n\n둘째 문단 — 따옴표 “와” 이모지 😀 도 있어요."
        result = op.read_own_files([self.put("a.txt", text)])[0]
        self.assertEqual((result.text, result.chars), (text, len(text)))

    def test_a_utf8_byte_order_mark_is_dropped(self):
        path = self.put("a.txt", b"\xef\xbb\xbf" + "가나다".encode("utf-8"))
        result = op.read_own_files([path])[0]
        self.assertEqual((result.text, result.chars), ("가나다", 3))

    def test_cp949_from_a_korean_notepad_file_is_read_when_it_is_not_utf8(self):
        text = "한글 메모장으로 저장한 글입니다. 가나다라 마바사."
        data = text.encode("cp949")
        with self.assertRaises(UnicodeDecodeError):
            data.decode("utf-8")
        result = op.read_own_files([self.put("a.txt", data)])[0]
        self.assertEqual((result.text, result.chars, result.encoding), (text, len(text), "cp949"))

    def test_cp949_is_wider_than_the_euc_kr_table_so_syllables_outside_it_are_read_too(self):
        """CP949 는 완성형(EUC-KR) 2,350자 밖의 음절(똠·쌰·뷁 …)도 담는다 — 글자표를 EUC-KR 로 좁히면 이런 글을 못 읽는다(검증자 변이 V15, OWNFIX D4)."""
        text = "똠방각하 쌰갈 뷁, 완성형 밖의 음절을 모은 글 가나다"
        data = text.encode("cp949")
        for narrow in ("utf-8", "euc-kr"):
            with self.assertRaises(UnicodeDecodeError, msg=narrow):
                data.decode(narrow)
        result = op.read_own_files([self.put("a.txt", data)])[0]
        self.assertEqual((result.text, result.encoding), (text, "cp949"))

    def test_utf8_is_tried_before_cp949(self):
        text = "ASCII 만 있는 글 and a UTF-8 글 가나다"
        self.assertEqual(op.read_own_files([self.put("a.md", text)])[0].text, text)

    def test_bytes_that_neither_utf8_nor_cp949_can_read_are_refused(self):
        for data in (b"\xff", b"\x80abc", b"abc\xff\xfedef", b"\xc3\x28", b"\xe2\x82", b"\xed\xa0\x80", b"\xfe\xff", b"\x93hello\x94"):
            with self.subTest(data=data):
                self.refused([self.put("a.txt", data)], "encoding")

    def test_utf16_and_utf32_files_are_refused_because_they_contain_nul_bytes(self):
        for encoding in ("utf-16", "utf-16-le", "utf-16-be", "utf-32"):
            with self.subTest(encoding=encoding):
                self.refused([self.put("a.txt", "hello 안녕".encode(encoding))], "binary")

    def test_a_nul_byte_anywhere_refuses_the_file(self):
        body = "정상 글".encode("utf-8")
        for data in (b"\x00" + body, body + b"\x00", body[:3] + b"\x00" + body[3:], b"\x00", b"a\x00b", b"PK\x03\x04\x00\x00" + body):
            with self.subTest(data=data[:8]):
                self.refused([self.put("a.txt", data)], "binary")

    def test_the_charset_name_tells_how_the_text_was_read(self):
        """N-3a 화면이 'CP949 로 읽었어요 — 글자가 깨져 보이면 UTF-8 로 저장해 다시 골라 주세요' 를 보일 수 있게 읽은 글자표 이름을 값에 담는다(OWNFIX D6)."""
        korean = "한글 메모장으로 저장한 글"
        for label, data, expected in (("ascii only", b"plain ascii text", "utf-8"), ("utf-8 korean", korean.encode("utf-8"), "utf-8"), ("utf-8 with bom", b"\xef\xbb\xbf" + korean.encode("utf-8"), "utf-8"),
                                      ("cp949 korean", korean.encode("cp949"), "cp949")):
            with self.subTest(label=label):
                result = op.read_own_files([self.put("a.txt", data)])[0]
                self.assertEqual(result.encoding, expected)
                self.assertIn(result.encoding, op.ENCODINGS)

    def test_known_limit_a_japanese_or_chinese_euc_text_is_read_as_a_heap_of_hangul(self):
        """알려 둔 한계(D-327): EUC-JP·EUC-CN 으로 저장한 글은 CP949 로 '성공' 해 한글 더미로 읽힌다 — 한자 비율로 거르는 방식은 쓰지 않았다(검증자 권고). 바꾸려면 새 결정이 필요해서 지금 동작을 못박는다."""
        for text, codec in (("日本語の文章を書いています。", "euc-jp"), ("中文汉字测试", "gb2312")):
            with self.subTest(codec=codec):
                data = text.encode(codec)
                result = op.read_own_files([self.put("a.txt", data)])[0]
                self.assertEqual(result.encoding, "cp949")
                self.assertEqual(result.text, data.decode("cp949"))
                self.assertNotEqual(result.text, text)

    def test_known_limit_a_seven_bit_text_with_escape_characters_is_not_filtered(self):
        """알려 둔 한계(D-327): ESC 같은 제어 문자가 든 7비트 글(ISO-2022-JP)은 거르지 않는다 — 거르는 것은 NUL 뿐이다. 계산하는 쪽이 보이지 않는 글자를 정리한다."""
        data = "こんにちは".encode("iso-2022-jp")
        self.assertIn(b"\x1b", data)
        result = op.read_own_files([self.put("a.txt", data)])[0]
        self.assertEqual((result.text, result.encoding), (data.decode("utf-8"), "utf-8"))
        self.assertIn(chr(27), result.text)

    def test_a_file_with_only_a_byte_order_mark_has_nothing_to_read(self):
        self.refused([self.put("a.txt", b"\xef\xbb\xbf")], "empty")


# ---- 7) 글 내용·길이 --------------------------------------------------------------------------------------------------------------
class ContentTest(OwnCase):
    def test_an_empty_file_has_nothing_to_read(self):
        self.refused([self.put("a.txt", b"")], "empty")

    def test_a_text_of_only_blanks_has_nothing_to_read(self):
        for text in (" ", "\n", "\r\n\r\n", "\t \t", chr(0x3000), chr(0xA0), " \n\t" + chr(0x3000) + chr(0xA0) + "\r\n", "\n" * 5000):
            with self.subTest(text=repr(text)[:12]):
                self.refused([self.put("a.txt", text)], "empty")

    def test_a_text_of_only_invisible_characters_has_nothing_to_read(self):
        for text in (chr(0x200B) * 5, chr(0xFEFF) + chr(0xFEFF), chr(0xAD), chr(0x202E) + chr(0x202C), "\x07", chr(0x2060), " " + chr(0x200B) + "\n" + chr(0x200D) + "\t", chr(0xE000)):
            with self.subTest(text=[hex(ord(ch)) for ch in text][:3]):
                self.refused([self.put("a.txt", text)], "empty")

    def test_a_single_visible_character_among_blanks_is_enough(self):
        for text in (" \n" + chr(0x200B) + "가" + "\n", ".", "a", "😀", "\n\n한\n\n"):
            with self.subTest(text=repr(text)):
                result = op.read_own_files([self.put("a.txt", text)])[0]
                self.assertEqual((result.text, result.chars), (text, len(text)))

    def test_exactly_the_limit_in_characters_is_read_and_one_more_is_refused(self):
        samples = (("ascii", lambda count: "a" * count, "utf-8"), ("hangul-utf8", lambda count: "가" * count, "utf-8"), ("hangul-cp949", lambda count: "가" * count, "cp949"))
        for label, make, encoding in samples:
            with self.subTest(label=label, case="limit"):
                result = op.read_own_files([self.put("a.txt", make(op.MAX_TEXT_CHARS).encode(encoding))])[0]
                self.assertEqual(result.chars, 100_000)
                self.assertEqual(len(result.text), 100_000)
                self.assertEqual(result.encoding, "cp949" if encoding == "cp949" else "utf-8")
            with self.subTest(label=label, case="over"):
                self.refused([self.put("a.txt", make(op.MAX_TEXT_CHARS + 1).encode(encoding))], "long")

    def test_a_long_text_is_refused_and_never_cut_short(self):
        self.refused([self.put("a.txt", "가나다라마바사 " * 20000)], "long")
        good = self.put("good.txt", "정상 글")
        too_long = self.put("long.txt", "x" * (op.MAX_TEXT_CHARS + 1))
        with self.assertRaises(AppError):
            op.read_own_files([good, too_long])

    def test_the_text_check_alone_refuses_what_the_file_path_would_refuse(self):
        for text, key in (("a\x00b", "binary"), ("", "empty"), (" \n", "empty"), ("x" * (op.MAX_TEXT_CHARS + 1), "long")):
            with self.subTest(key=key):
                self.assertIn(SAYS[key], op._check_text(text))
        self.assertIsNone(op._check_text("가" * op.MAX_TEXT_CHARS))
        self.assertIsNone(op._check_text("글"))

    def test_line_endings_are_kept_and_counted_as_characters(self):
        text = "a\r\nb\rc\nd\r\n\r\ne"
        self.assertEqual(op.read_own_files([self.put("a.txt", text)])[0].text, text)
        full = "abcd\r\n" * 16666 + "abcd"
        self.assertEqual(len(full), op.MAX_TEXT_CHARS)
        self.assertEqual(op.read_own_files([self.put("b.txt", full)])[0].chars, 100_000)
        self.refused([self.put("c.txt", full + "e")], "long")


# ---- 8) 읽기 전용 -----------------------------------------------------------------------------------------------------------------
class ReadOnlyTest(OwnCase):
    def test_reading_changes_nothing_on_disk_and_creates_no_temporary_file(self):
        first, second = self.put("a.txt", "첫째 글"), self.put("sub/b.md", "둘째 글")
        scratch = self.root.parent / (self.root.name + "-scratch")
        scratch.mkdir()
        self.addCleanup(scratch.rmdir)
        before = snapshot(self.root)
        with mock.patch.object(tempfile, "tempdir", str(scratch)):
            for _ in range(3):
                op.read_own_files([first, second])
            self.refused([first, self.root / "missing.txt"], "missing")
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(os.listdir(scratch), [])

    def test_a_refused_read_changes_nothing_either(self):
        self.put("a.txt", b"\xff")
        self.put("big.txt", b"a" * (op.MAX_FILE_BYTES + 1))
        self.put("e.txt", "")
        before = snapshot(self.root)
        for name, key in (("a.txt", "encoding"), ("big.txt", "big"), ("e.txt", "empty")):
            self.refused([self.root / name], key)
        self.assertEqual(snapshot(self.root), before)

    def test_every_file_is_opened_exactly_once_in_binary_read_mode(self):
        first, second = self.put("a.txt", "첫째 글"), self.put("b.md", "둘째 글")
        recorder = OpenRecorder()
        with mock.patch("builtins.open", recorder):
            op.read_own_files([first, second])
        self.assertEqual([(Path(call[0]), call[1], call[2], call[3]) for call in recorder.calls], [(first, "rb", (), {}), (second, "rb", (), {})])

    def test_the_file_handle_is_closed_right_away_so_the_file_can_be_removed(self):
        path = self.put("a.txt", "내용")
        op.read_own_files([path])
        path.unlink()
        self.assertFalse(path.exists())

    def test_a_read_only_file_is_read_and_stays_the_same(self):
        path = self.put("a.txt", "읽기만 되는 글")
        os.chmod(path, stat.S_IREAD)
        self.addCleanup(os.chmod, path, stat.S_IREAD | stat.S_IWRITE)
        before = snapshot(self.root)
        self.assertEqual(op.read_own_files([path])[0].text, "읽기만 되는 글")
        self.assertEqual(snapshot(self.root), before)

    def test_nothing_is_written_or_created_anywhere_while_reading(self):
        first, second = self.put("a.txt", "첫째 글"), self.put("b.md", "둘째 글")

        def boom(*args, **kwargs):
            raise AssertionError("쓰기 길을 불렀다")

        with contextlib.ExitStack() as stack:
            for name in ("write_text", "write_bytes", "mkdir", "unlink", "rmdir", "touch", "chmod"):
                stack.enter_context(mock.patch.object(Path, name, boom))
            for name in ("remove", "rename", "replace", "mkdir", "rmdir", "unlink", "chmod", "makedirs", "write", "fsync", "truncate"):
                stack.enter_context(mock.patch.object(os, name, boom))
            self.assertEqual([item.text for item in op.read_own_files([first, second])], ["첫째 글", "둘째 글"])


# ---- 9) 소스 규칙(AST) ------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    def setUp(self):
        self.text = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.text)

    def calls(self):
        """(호출한 이름, 그 호출을 감싼 가장 안쪽 함수 이름, 호출 노드) 를 모두."""
        def walk(node, function=""):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Call):
                    yield ast.unparse(child.func), function, child
                yield from walk(child, child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function)
        return list(walk(self.tree))

    def test_the_only_open_call_is_a_binary_read_inside_read_prefix(self):
        opens = [(name, function, [ast.unparse(arg) for arg in node.args], node.keywords) for name, function, node in self.calls() if name.rsplit(".", 1)[-1] in ("open", "open_code", "FileIO", "fdopen")]
        self.assertEqual(opens, [("open", "_read_prefix", ["path", "'rb'"], [])])

    def test_no_call_can_write_delete_create_or_start_a_program(self):
        banned = {"write", "write_text", "write_bytes", "unlink", "rmdir", "mkdir", "touch", "chmod", "remove", "rename", "makedirs", "rmtree", "copy", "copy2", "copyfile", "copytree", "move",
                  "mkstemp", "mktemp", "NamedTemporaryFile", "TemporaryFile", "TemporaryDirectory", "fsync", "truncate", "symlink", "link", "utime", "system", "popen", "Popen", "run",
                  "check_output", "startfile", "dump", "dumps", "print"}
        found = sorted({name for name, _, _ in self.calls() if name.rsplit(".", 1)[-1] in banned})
        self.assertEqual(found, [])

    def test_the_imports_are_standard_library_only_and_no_network_ui_or_logging_module_is_among_them(self):
        absolute, relative = set(), []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                absolute |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                (relative.append((node.module, node.level)) if node.level else absolute.add((node.module or "").split(".")[0]))
        self.assertEqual(absolute, {"__future__", "os", "re", "stat", "unicodedata", "dataclasses", "pathlib"})
        self.assertEqual(relative, [("errors", 2)])
        for banned in ("socket", "urllib", "http", "ssl", "ctypes", "subprocess", "logging", "tempfile", "shutil", "json", "sqlite3", "asyncio", "PySide6", "webbrowser"):
            self.assertNotIn(banned, absolute)

    def test_the_module_reads_no_environment_and_keeps_no_state(self):
        for node in ast.walk(self.tree):
            self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal))
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ("environ", "getenv", "putenv"))
        for name, value in vars(op).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, bytearray), name)

    def test_the_service_safety_rules_pass_and_the_one_open_is_tied_to_the_function_name_and_file(self):
        import test_service_safety as safety
        self.assertEqual(safety.write_violations("own_posts.py", self.tree), [])
        renamed = ast.parse(self.text.replace("def _read_prefix(", "def _read_elsewhere("))
        self.assertTrue(safety.write_violations("own_posts.py", renamed), "함수 이름이 바뀌면 열기 허용이 걸리지 않아야 한다")
        self.assertTrue(safety.write_violations("projects.py", self.tree), "다른 서비스 파일에서는 같은 코드도 허용되지 않아야 한다")
        text_mode = ast.parse(self.text.replace('open(path, "rb")', 'open(path, "r")'))
        self.assertTrue(safety.write_violations("own_posts.py", text_mode), "모드가 rb 가 아니면 걸려야 한다")

    def test_no_new_error_code_and_no_secret_word_appear_in_the_strings(self):
        codes = {node.args[0].value for node in ast.walk(self.tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "AppError" and node.args and isinstance(node.args[0], ast.Constant)}
        self.assertEqual(codes, {"CONTENT_INVALID"})
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotRegex(node.value, r"(?i)(api[_ -]?key|secret|token|passw|credential)")

    def test_the_text_and_the_comments_have_no_tilde_and_no_web_address(self):
        self.assertNotIn(TILDE, self.text)
        self.assertNotRegex(self.text, r"(?i)(https?|ftp)://|www[.]")


# ---- 10) 오류에 경로·이름·내용이 없다 -----------------------------------------------------------------------------------------------
class NoLeakTest(OwnCase):
    def secrets(self):
        return (UNIQUE_DIR, UNIQUE_NAME, UNIQUE_BODY, str(self.root), self.root.name, str(self.root).replace(os.sep, "/"))

    def scenarios(self):
        folder = self.root / UNIQUE_DIR
        make = lambda name, data: self.put(f"{UNIQUE_DIR}/{name}", data)        # noqa: E731
        good = make(UNIQUE_NAME + ".txt", UNIQUE_BODY)
        (folder / (UNIQUE_NAME + "-폴더.txt")).mkdir()
        scheme = "ht" + "tps"
        return {
            "suffix": [make(UNIQUE_NAME + ".docx", UNIQUE_BODY)],
            "missing": [folder / (UNIQUE_NAME + "-없음.txt")],
            "folder": [folder / (UNIQUE_NAME + "-폴더.txt")],
            "empty": [make(UNIQUE_NAME + "-빈.txt", "  \n ")],
            "binary": [make(UNIQUE_NAME + "-바이너리.txt", UNIQUE_BODY.encode("utf-8") + b"\x00")],
            "encoding": [make(UNIQUE_NAME + "-깨짐.txt", b"\xff" + UNIQUE_BODY.encode("utf-8"))],
            "long": [make(UNIQUE_NAME + "-긴글.txt", (UNIQUE_BODY + " ") * 20000)],
            "big": [make(UNIQUE_NAME + "-큰파일.txt", UNIQUE_BODY.encode("utf-8") + b"a" * op.MAX_FILE_BYTES)],
            "same": [good, good],
            "count": [good, good, good],
            "wildcard": [str(folder / (UNIQUE_NAME + "*.txt"))],
            "network": [unc(UNIQUE_DIR, "share", UNIQUE_NAME + ".txt")],
            "address": [f"{scheme}://{UNIQUE_DIR}.invalid/{UNIQUE_NAME}.txt"],
            "relative": [UNIQUE_DIR + "/" + UNIQUE_NAME + ".txt"],
            "dotdot": [str(folder / ".." / UNIQUE_DIR / (UNIQUE_NAME + ".txt"))],
            "control": [str(folder / (UNIQUE_NAME + "\x00.txt"))],
            "device": [str(folder / "CON.txt")],
            "stream": [str(folder / (UNIQUE_NAME + ".txt:" + UNIQUE_BODY))],
            "kind": [object()],
            "shape": {UNIQUE_BODY: UNIQUE_NAME},
        }

    def channels(self, error):
        return channels(error)

    def assert_clean(self, error, label):
        self.assert_absent(error, self.secrets(), label)
        for text in (UNIQUE_DIR, UNIQUE_NAME, UNIQUE_BODY):
            self.assertNotIn(text, repr(error.__dict__))

    def test_no_refusal_repeats_the_path_the_file_name_or_the_content(self):
        for label, paths in self.scenarios().items():
            with self.subTest(label=label):
                with self.assertRaises(AppError) as caught:
                    op.read_own_files(paths)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                self.assert_clean(caught.exception, label)

    def test_a_system_error_that_carries_the_path_is_not_repeated(self):
        path = self.put(f"{UNIQUE_DIR}/{UNIQUE_NAME}.txt", UNIQUE_BODY)

        def denied_open(file, *args, **kwargs):
            raise PermissionError(13, "거부됨 " + UNIQUE_NAME, os.fspath(file))

        def broken_lstat(target, *args, **kwargs):
            raise OSError(5, UNIQUE_NAME + UNIQUE_BODY, os.fspath(target))

        with mock.patch("builtins.open", denied_open):
            self.assert_clean(self.refused([path], "missing"), "open")
        with mock.patch.object(os, "lstat", broken_lstat):
            self.assert_clean(self.refused([path], "missing"), "lstat")
        with mock.patch("builtins.open", side_effect=ValueError(UNIQUE_NAME + UNIQUE_BODY)):
            self.assert_clean(self.refused([path], "missing"), "value")
        with mock.patch.object(os, "lstat", side_effect=ValueError(UNIQUE_NAME + UNIQUE_BODY)):
            self.assert_clean(self.refused([path], "missing"), "lstat-value")
        with mock.patch.object(os, "fstat", side_effect=OSError(5, UNIQUE_NAME + UNIQUE_BODY, os.fspath(path))):
            self.assert_clean(self.refused([path], "missing"), "fstat")
        with mock.patch("builtins.open", side_effect=OSError(5, UNIQUE_NAME, os.fspath(path))):
            self.assert_clean(self.refused([path], "missing"), "oserror")

    def test_nothing_is_logged_printed_or_warned_for_any_refusal_or_success(self):
        scenarios = self.scenarios()
        good = self.put(f"{UNIQUE_DIR}/{UNIQUE_NAME}-두번째.md", UNIQUE_BODY)
        out, err = io.StringIO(), io.StringIO()
        with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertNoLogs(level="DEBUG"):
            warnings.simplefilter("always")
            for paths in scenarios.values():
                with self.assertRaises(AppError):
                    op.read_own_files(paths)
            self.assertEqual(len(op.read_own_files([good])), 1)
        self.assertEqual((out.getvalue(), err.getvalue(), [str(item.message) for item in caught]), ("", "", []))

    def test_the_result_never_shows_the_text_in_its_repr_or_carries_a_path(self):
        path = self.put(f"{UNIQUE_DIR}/{UNIQUE_NAME}.txt", UNIQUE_BODY)
        result = op.read_own_files([path])
        text = repr(result) + str(result)
        for secret in self.secrets():
            self.assertNotIn(secret, text)
        self.assertEqual(sorted(vars(result[0])), ["chars", "encoding", "text"])

    def test_the_exception_keeps_no_reference_to_the_os_error_that_carried_the_path(self):
        path = self.put(f"{UNIQUE_DIR}/{UNIQUE_NAME}.txt", UNIQUE_BODY)
        with mock.patch("builtins.open", side_effect=PermissionError(13, UNIQUE_NAME, os.fspath(path))):
            error = self.refused([path], "missing")
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self.assertTrue(error.__suppress_context__ or error.__context__ is None)


# ---- 11) 네트워크 0 ---------------------------------------------------------------------------------------------------------------
class NetworkZeroTest(OwnCase):
    def test_no_network_entry_point_is_called_on_any_path(self):
        import http.client
        import socket
        import ssl
        import urllib.request

        def boom(*args, **kwargs):
            raise AssertionError("네트워크 부품을 불렀다")

        first, second = self.put("a.txt", "첫째 글"), self.put("b.md", "둘째 글")
        scheme = "ht" + "tps"
        inputs = [[f"{scheme}://host.invalid/a.txt"], [unc("srv", "share", "a.txt")], ["//srv/share/a.txt"], [Path("//srv/share/a.txt")], [self.root / "missing.txt"], [first, first], [first, first, second]]
        with contextlib.ExitStack() as stack:
            for target, name in ((socket, "socket"), (socket, "create_connection"), (socket, "getaddrinfo"), (socket, "gethostbyname"), (urllib.request, "urlopen"),
                                 (http.client.HTTPConnection, "connect"), (http.client.HTTPSConnection, "connect"), (ssl.SSLContext, "wrap_socket")):
                stack.enter_context(mock.patch.object(target, name, boom))
            self.assertEqual([item.text for item in op.read_own_files([first, second])], ["첫째 글", "둘째 글"])
            for paths in inputs:
                with self.assertRaises(AppError):
                    op.read_own_files(paths)

    def test_the_module_does_not_even_import_a_network_part(self):
        for module in ("socket", "ssl", "http", "urllib", "ftplib", "smtplib", "requests"):
            self.assertNotIn(module, vars(op), module)


# ---- 12) 결과의 성질 --------------------------------------------------------------------------------------------------------------
class ResultTest(OwnCase):
    def test_the_result_is_a_tuple_of_frozen_values_in_a_stable_order(self):
        first, second = self.put("a.txt", "가"), self.put("b.txt", "나나")
        for order in ((first, second), (second, first)):
            result = op.read_own_files(list(order))
            self.assertIsInstance(result, tuple)
            self.assertTrue(all(isinstance(item, op.OwnText) for item in result))
            self.assertEqual([item.chars for item in result], [len(item.text) for item in result])
        self.assertEqual(op.read_own_files([first, second]), op.read_own_files([first, second]))
        self.assertEqual([item.text for item in op.read_own_files([second, first])], ["나나", "가"])

    def test_a_second_call_sees_the_changed_file_because_nothing_is_cached(self):
        path = self.put("a.txt", "처음 글")
        first = op.read_own_files([path])
        path.write_bytes("바뀐 글".encode("utf-8"))
        second = op.read_own_files([path])
        self.assertEqual((first[0].text, second[0].text), ("처음 글", "바뀐 글"))
        self.assertIsNot(first[0], second[0])

    def test_one_refused_file_returns_nothing_even_when_the_other_was_fine(self):
        good, bad = self.put("a.txt", "좋은 글"), self.put("b.txt", b"\xff")
        for order in ([good, bad], [bad, good]):
            with self.assertRaises(AppError):
                op.read_own_files(order)

    def test_each_file_is_opened_once_per_call(self):
        first, second = self.put("a.txt", "첫째 글"), self.put("b.md", "둘째 글")
        recorder = OpenRecorder()
        with mock.patch("builtins.open", recorder):
            op.read_own_files([first, second])
            op.read_own_files([second])
        self.assertEqual(len(recorder.calls), 3)

    def test_the_text_is_not_normalized_beyond_the_byte_order_mark(self):
        text = "e" + chr(0x301) + " ﬁ " + chr(0x3000) + "가" + chr(0x200B) + chr(0xFE0F)
        self.assertEqual(op.read_own_files([self.put("a.txt", text)])[0].text, text)


# ---- 13) 링크·재해석 지점·클라우드 ---------------------------------------------------------------------------------------------------
class LinkTest(OwnCase):
    def test_a_symbolic_link_to_a_text_file_is_not_followed(self):
        target = self.put("real.txt", "진짜 글")
        link = self.root / "link.txt"
        self.make_symlink(link, target)
        with mock.patch("builtins.open", side_effect=AssertionError("링크를 열면 안 된다")):
            self.refused([link], "link")
        self.assertEqual(op.read_own_files([target])[0].text, "진짜 글")

    def test_a_link_to_a_folder_in_the_middle_of_the_path_is_not_followed(self):
        self.put("realdir/a.txt", "진짜 글")
        link = self.root / "linkdir"
        self.make_symlink(link, self.root / "realdir", directory=True)
        with mock.patch("builtins.open", side_effect=AssertionError("링크를 열면 안 된다")):
            self.refused([link / "a.txt"], "link")

    def test_the_symbolic_link_flag_of_the_file_mode_alone_is_refused_on_every_operating_system(self):
        """리눅스처럼 재해석 지점 표시가 없는 운영체제의 심볼릭 링크는 파일 종류(`st_mode`)로 알아본다 — 윈도의 링크는 아래 재해석 지점 규칙으로도 걸리므로 모의 정보로 이 길을 따로 확인한다."""
        path = self.put("a.txt", "내용")
        with self.doctor_lstat(path, st_mode=stat.S_IFLNK | 0o777), mock.patch("builtins.open", side_effect=AssertionError("링크를 열면 안 된다")):
            self.refused([path], "link")

    def test_a_broken_link_is_refused(self):
        link = self.root / "broken.txt"
        self.make_symlink(link, self.root / "nowhere.txt")
        self.refused([link], "link")

    @unittest.skipUnless(os.name == "nt", "윈도 전용: 정션(폴더 링크)은 윈도에만 있다")
    def test_a_windows_junction_in_the_middle_of_the_path_is_not_followed(self):
        self.put("realdir/a.txt", "진짜 글")
        junction = self.root / "junc"
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(self.root / "realdir")], capture_output=True)
        if done.returncode:
            self.skipTest("이 환경에서는 정션을 만들 수 없다")
        self.addCleanup(os.rmdir, junction)
        with mock.patch("builtins.open", side_effect=AssertionError("정션을 따라 열면 안 된다")):
            self.refused([junction / "a.txt"], "link")
        self.assertEqual(op.read_own_files([self.root / "realdir" / "a.txt"])[0].text, "진짜 글")

    def test_a_reparse_point_that_names_another_place_is_refused_on_every_operating_system(self):
        path = self.put("a.txt", "내용")
        for tag in (0xA000000C, 0xA0000003, 0xA000001D):
            with self.subTest(tag=hex(tag)):
                with self.doctor_lstat(path, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_ARCHIVE, st_reparse_tag=tag), mock.patch("builtins.open", side_effect=AssertionError("열었다")):
                    self.refused([path], "link")

    def test_a_folder_that_is_a_reparse_point_in_the_middle_of_the_path_is_refused(self):
        path = self.put("sub/a.txt", "내용")
        with self.doctor_lstat(self.root / "sub", st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_DIRECTORY, st_reparse_tag=0xA0000003):
            self.refused([path], "link")

    def test_a_cloud_placeholder_that_is_on_this_pc_is_read_like_an_ordinary_file(self):
        """OneDrive 같은 클라우드 동기 폴더의 파일은 재해석 지점이지만 링크가 아니다(이름을 가리키는 비트가 꺼져 있다) — 내려받아 있으면 읽는다."""
        path = self.put("a.txt", "클라우드 폴더의 글")
        with self.doctor_lstat(path, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_ARCHIVE, st_reparse_tag=0x9000001A):
            self.assertEqual(op.read_own_files([path])[0].text, "클라우드 폴더의 글")

    def test_a_file_that_is_not_on_this_pc_is_refused_without_opening_it(self):
        path = self.put("a.txt", "내용")
        for label, attributes in (("offline", stat.FILE_ATTRIBUTE_OFFLINE), ("recall-on-open", 0x00040000), ("recall-on-data-access", 0x00400000 | stat.FILE_ATTRIBUTE_REPARSE_POINT)):
            with self.subTest(label=label):
                with self.doctor_lstat(path, st_file_attributes=attributes, st_reparse_tag=0x9000001A), mock.patch("builtins.open", side_effect=AssertionError("내려받기가 일어난다")):
                    self.refused([path], "cloud")

    def test_the_attributes_that_only_windows_has_do_not_matter_elsewhere(self):
        path = self.put("a.txt", "내용")
        with self.doctor_lstat(path):
            self.assertEqual(op.read_own_files([path])[0].text, "내용")


# ---- 13-2) 검사와 읽기 사이의 바꿔치기(OWNFIX D2) ---------------------------------------------------------------------------------
class SwapTest(OwnCase):
    """검사(`_inspect_all`)가 끝난 뒤 읽기 전에 같은 이름을 링크·다른 파일로 바꿔도 따라가지 않는다 — 열린 핸들의 `fstat` 이 검사 때의 상태와 같은 일반 파일인지 견주기 때문이다."""

    def pair(self):
        return self.put("victim.txt", "원래 글"), self.put("other.txt", "SECRET-TARGET-본문")

    def test_without_a_swap_the_same_hook_changes_nothing_and_the_file_is_read(self):
        victim, _ = self.pair()
        with self.after_the_check(lambda: None):
            result = op.read_own_files([victim])
        self.assertEqual((result[0].text, result[0].encoding), ("원래 글", "utf-8"))

    def test_a_file_replaced_by_another_file_after_the_check_is_refused(self):
        victim, other = self.pair()
        with self.after_the_check(lambda: os.replace(other, victim)):
            error = self.refused([victim], "changed")
        self.assert_absent(error, ["SECRET-TARGET"], "replaced")
        self.assertEqual(victim.read_bytes(), "SECRET-TARGET-본문".encode("utf-8"))

    def test_a_file_swapped_for_a_symbolic_link_after_the_check_is_refused(self):
        victim, other = self.pair()
        decoy = self.root / "decoy-link.txt"
        self.make_symlink(decoy, other)
        with self.after_the_check(lambda: os.replace(decoy, victim)):
            error = self.refused([victim], "changed")
        self.assert_absent(error, ["SECRET-TARGET"], "linked")

    def test_a_file_deleted_after_the_check_is_refused_as_unreadable(self):
        victim, _ = self.pair()
        with self.after_the_check(lambda: os.unlink(victim)):
            self.refused([victim], "missing")

    def test_a_file_that_grows_after_the_check_is_refused_and_the_read_stops_at_the_limit_plus_one_byte(self):
        victim, _ = self.pair()
        counting = RealBackedFile()
        recorder = OpenRecorder({fake_key(victim): counting})

        def grow():
            with REAL_OPEN(victim, "ab") as handle:
                handle.write(b"x" * (3 * MB))

        with self.after_the_check(grow), mock.patch("builtins.open", recorder):
            self.refused([victim], "big")
        self.assertEqual(counting.delivered, op.MAX_FILE_BYTES + 1)
        self.assertTrue(counting.closed)

    def test_an_opened_file_that_is_not_the_checked_file_is_refused(self):
        victim, _ = self.pair()
        for label, override in (("other file number", {"st_ino": lambda number: number + 1}), ("other device", {"st_dev": lambda number: number + 1}),
                                ("not a regular file", {"st_mode": stat.S_IFCHR | 0o666}), ("a folder", {"st_mode": stat.S_IFDIR | 0o755})):
            with self.subTest(label=label), self.doctor_fstat(**override):
                self.refused([victim], "changed")
        with self.doctor_fstat():                                                  # 통제: 아무것도 안 바꾸면 읽힌다
            self.assertEqual(op.read_own_files([victim])[0].text, "원래 글")

    def test_a_file_system_without_file_numbers_is_checked_for_the_kind_only(self):
        victim, _ = self.pair()
        real = os.lstat

        def numberless(candidate, *args, **kwargs):
            info = real(candidate, *args, **kwargs)
            return DoctoredStat(info, st_ino=0) if fake_key(candidate) == fake_key(victim) else info

        with mock.patch.object(os, "lstat", numberless):
            with self.doctor_fstat(st_ino=999999):                                 # 검사 때 번호가 0 이면 번호가 달라도 견주지 않는다
                self.assertEqual(op.read_own_files([victim])[0].text, "원래 글")
            with self.doctor_fstat(st_mode=stat.S_IFCHR | 0o666):                  # 그래도 일반 파일인지는 본다
                self.refused([victim], "changed")

    def test_the_state_of_each_file_is_compared_with_its_own_check_in_the_given_order(self):
        first, second = self.put("a.txt", "첫째 글"), self.put("b.txt", "둘째 글")
        for order in ([first, second], [second, first]):
            self.assertEqual(len(op.read_own_files(order)), 2)
        with self.after_the_check(lambda: os.replace(self.put("c.txt", "셋째 글"), second)):
            self.refused([first, second], "changed")


# ---- 13-3) 호출 흔적이 글을 붙들지 않는다(OWNFIX D1) ------------------------------------------------------------------------------
class FrameLocalsTest(OwnCase):
    """읽은 뒤 거절한 오류의 `__traceback__` 이 붙든 틀의 지역 변수 어디에도 글이 없다 — 오류를 쥐고 있는 쪽이 `frame.f_locals` 로 파일 내용을 읽을 수 없게 한다."""
    MARK = "UNIQ-FRAME-w9k3-본문"
    INVISIBLE = chr(0x200B) * 3 + chr(0x2060) + chr(0x200D) * 2 + chr(0xFEFF) + chr(0x200B) * 2

    def markers(self, text):
        return [text, text.encode("utf-8")]

    def refuse(self, paths):
        """거절 오류를 돌려준다. `assertRaises` 는 쓰지 않는다 — 그것은 잡은 오류의 호출 흔적 틀을 모두 비워(`traceback.clear_frames`) 지역 변수를 볼 수 없게 만든다."""
        try:
            op.read_own_files(paths)
        except AppError as error:
            return error
        self.fail("거절되지 않았다")

    def test_the_helper_does_find_a_function_that_holds_the_content(self):
        """대조: 지역 변수에 글을 쥔 채 오류를 내는 함수는 이 눈에 잡힌다 — 이것이 안 잡히면 아래 시험은 아무것도 못 지킨다."""
        marker = "UNIQ-CONTROL-q1-본문"

        def holder():
            data = (marker * 10).encode("utf-8")
            raise ValueError(len(data))

        try:
            holder()
        except ValueError as error:
            found = leaking_locals(error, self.markers(marker))
        self.assertIn("holder.data", found)
        self.assertEqual(leaking_locals(AppError("CONTENT_INVALID"), self.markers(marker)), [])

    def test_no_refusal_after_reading_leaves_the_text_in_the_frames_of_the_error(self):
        mark_bytes = self.MARK.encode("utf-8")
        cases = {
            "too long": (self.put("long.txt", (self.MARK + " ") * 6000), self.markers(self.MARK)),
            "nul": (self.put("nul.txt", mark_bytes + b"\x00" + mark_bytes), self.markers(self.MARK)),
            "charset": (self.put("charset.txt", b"\xff" + mark_bytes), self.markers(self.MARK)),
            "empty": (self.put("empty.txt", " \n" + self.INVISIBLE + "\n"), self.markers(self.INVISIBLE)),
        }
        for label, (path, markers) in cases.items():
            with self.subTest(label=label):
                self.assertEqual(leaking_locals(self.refuse([path]), markers), [], label)

    def test_a_file_that_grows_after_the_check_is_refused_without_its_bytes_staying_in_the_frames(self):
        path = self.put("grow.txt", self.MARK + " 처음 글")

        def grow():
            with REAL_OPEN(path, "ab") as handle:
                handle.write(b"x" * (3 * MB))

        with self.after_the_check(grow):
            error = self.refuse([path])
        self.assertIn(SAYS["big"], error.slots["항목"])
        self.assertEqual(leaking_locals(error, self.markers(self.MARK)), [])

    def test_the_text_of_a_file_read_before_the_refused_one_is_not_held_either(self):
        first = self.put("first.txt", self.MARK + " 첫째 글")
        second = self.put("second.txt", "x" * (op.MAX_TEXT_CHARS + 1))
        error = self.refuse([first, second])
        self.assertIn(SAYS["long"], error.slots["항목"])
        self.assertEqual(leaking_locals(error, self.markers(self.MARK)), [])

    def test_clearing_the_traceback_is_enough_for_a_caller_that_keeps_the_error(self):
        """N-3a 쪽 규칙(문서): 오류를 잡으면 `rendered().message` 만 꺼내고 `error.__traceback__ = None` 으로 비운다."""
        error = self.refuse([self.put("long.txt", (self.MARK + " ") * 6000)])
        message = error.rendered().message
        error.__traceback__ = None
        self.assertIsNone(error.__traceback__)
        self.assertEqual(leaking_locals(error, self.markers(self.MARK)), [])
        self.assertIn(SAYS["long"], message)


# ---- 14) 무작위 입력(고정 씨앗) -----------------------------------------------------------------------------------------------------
class FuzzTest(OwnCase):
    """어떤 입력에도 `AppError`(거절)나 올바른 결과 말고는 나오지 않는다 — 씨앗을 고정한 무작위 입력이라 같은 입력이 늘 같다."""
    POOL = ("a", "b", "가", "1", ".", ".", " ", "/", BS, ":", "*", "?", "-", "_", "\x00", "\n", chr(0xD800), "CON", "nul", "%", "#", "..", chr(0x200B), chr(0x3000), "txt", "md")

    def test_random_paths_are_either_read_or_refused_with_the_one_error(self):
        rng = random.Random(20261110)
        self.put("ok.txt", "정상 글")
        bases = ("", str(self.root) + os.sep, str(self.root) + "/", "//", "C:" + BS, "ht" + "tp://", BS * 2, str(self.root) + os.sep + "ok", str(self.root) + os.sep + "..")
        refused = 0
        for _ in range(1500):
            text = rng.choice(bases) + "".join(rng.choice(self.POOL) for _ in range(rng.randint(0, 12))) + rng.choice(("", ".txt", ".md", ".TXT", ".docx", ".txt "))
            for value in (text, Path(text)):
                try:
                    result = op.read_own_files([value])
                except AppError as error:
                    refused += 1
                    self.assertEqual(error.code, "CONTENT_INVALID")
                else:
                    self.assertEqual(len(result), 1)
        self.assertGreater(refused, 2900, "대부분은 거절되어야 한다")
        self.assertEqual(op.read_own_files([self.root / "ok.txt"])[0].text, "정상 글")

    def test_random_file_contents_are_either_read_consistently_or_refused_with_the_one_error(self):
        rng = random.Random(7)
        path = self.root / "fuzz.txt"
        read = refused = 0
        for _ in range(500):
            size = rng.choice((0, 1, 2, 5, 50, 500))
            data = bytes(rng.choice((0, 10, 13, 32, 65, 128, 200, 239, 255, rng.randrange(256))) for _ in range(size))
            path.write_bytes(data)
            try:
                result = op.read_own_files([path])
            except AppError as error:
                refused += 1
                self.assertEqual(error.code, "CONTENT_INVALID")
                continue
            read += 1
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].chars, len(result[0].text))
            self.assertNotIn("\x00", result[0].text)
            self.assertTrue(any(not ch.isspace() for ch in result[0].text))
        self.assertGreater(read, 20)
        self.assertGreater(refused, 20)


# ---- 15) 문서 ---------------------------------------------------------------------------------------------------------------------
class DocsTest(unittest.TestCase):
    """문서 시험 — 이 묶음의 결정 행(D-325–D-329)과 구조·보안·변경 이력의 이 묶음 줄을 못박는다.

    OWNFIX D5 에서 바꾼 것(약화가 아니다 — 지운 단언이 없고 이 묶음 자신의 행에 대한 단언은 더 엄격해졌다): 예전에는 `own_posts.py` 를 언급하는 **모든** 결정 행이 D-325–D-329 안이어야 하고 구조·보안·변경 이력에서
    그 낱말이 든 줄이 **정확히 한 줄씩**이어야 한다고 못박았다. 그래서 다음 묶음(N-3a)이 문서에 이 파일 이름을 한 줄만 언급해도 이 시험이 반드시 빨개졌다(독립 검증의 모의). 이제는
    ① 이 묶음의 행을 **번호**(D-325–D-329 각각)로 찾아 번호마다 있어야 할 낱말을 행 단위로 못박는다(예전의 '합친 글에 낱말이 있다' 보다 엄격하다 — 합친 글에 대한 예전 낱말 단언도 그대로 둔다)
    ② 다른 행·줄이 같은 파일 이름을 언급하는 것은 허용하고 줄 수는 '한 줄 이상' 으로 본다 ③ 구조·보안·변경 이력에서는 이 묶음의 줄(파일 이름과 `D-325–D-329` 를 함께 가진 줄)이 필요한 낱말을 모두 가졌는지 본다.
    물결표·웹 주소·표 모양 단언은 이 묶음의 행·줄에 그대로 건다."""
    ROW_WORDS = {                     # 이 묶음의 행마다 있어야 하는 낱말
        "D-325": ("own_posts.py", "txt", "md", "2MB", "100,000", "MAX_FILES", "MAX_FILE_BYTES", "MAX_TEXT_CHARS", "OwnText", "encoding", "N-3a", "N-3b", "T1"),
        "D-326": ("own_posts.py", "절대 경로", "심볼릭 링크", "정션", "같은 파일", "lstat", "fstat", "내려받지 않음", "파일 자신만", "OneDrive", "열일곱", "고정 문장", "__traceback__"),
        "D-327": ("own_posts.py", "CP949", "EUC-JP", "ESC", "네트워크 드라이브", "네트워크 마운트", "OneDrive", "GetDriveTypeW", "fstat", "사실 기록"),
        "D-328": ("own_posts.py", "하지 않은 것", "붙여 넣기", "test_service_safety", "READ_OPENS", "io.open", "opener"),
        "D-329": ("own_posts.py", "원복", "test_service_own_posts.py", "ARCHITECTURE", "V09", "S07"),
    }
    UNION_WORDS = ("txt", "md", "2MB", "100,000", "네트워크 드라이브", "CP949", "심볼릭 링크", "정션", "같은 파일", "하지 않은 것", "붙여 넣기", "test_service_safety", "READ_OPENS", "OneDrive", "절대 경로", "원복", "T1")
    LINE_WORDS = {                    # 구조·보안·변경 이력에서 이 묶음의 줄이 가져야 하는 낱말
        "docs/ARCHITECTURE.md": ("own_posts.py", "D-325–D-329", "2MB", "화면 없", "OwnText", "fstat", "EUC-JP", "네트워크 마운트", "파일 자신만"),
        "docs/SECURITY.md": ("own_posts.py", "D-325–D-329", "2MB", "저장 0", "txt", "fstat", "EUC-JP", "네트워크 마운트", "파일 자신만"),
        "CHANGELOG.md": ("own_posts.py", "D-325–D-329", "2MB", "CONTENT_INVALID", "원복"),
    }

    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def rows(self):
        text = self.read("docs/DECISIONS.md")
        rows = {}
        for number in self.ROW_WORDS:
            found = [line for line in text.splitlines() if line.startswith(f"| {number} |")]
            self.assertEqual(len(found), 1, f"{number} 행은 정확히 한 줄이어야 한다")
            rows[number] = found[0]
        return rows

    def test_each_decision_row_of_this_bundle_exists_once_in_order_and_carries_its_own_words(self):
        rows = self.rows()
        text = self.read("docs/DECISIONS.md")
        positions = [text.index(f"| {number} |") for number in self.ROW_WORDS]
        self.assertEqual(positions, sorted(positions), "행은 번호 순서로 있어야 한다")
        for number, words in self.ROW_WORDS.items():
            for word in words:
                self.assertIn(word, rows[number], f"{number} 행에 '{word}' 가 없다")
            self.assertEqual(len(rows[number].split("|")), 6, f"{number}: 표의 한 행은 칸이 다섯이어야 한다")
        joined = "\n".join(rows.values())
        for word in self.UNION_WORDS:
            self.assertIn(word, joined, word)
        self.assertNotIn(TILDE, joined)
        self.assertNotRegex(joined, r"(?i)(https?|ftp)://|www[.]")

    def test_other_rows_may_mention_the_module_but_the_rows_of_this_bundle_are_found_by_number(self):
        """다음 묶음(N-3a)의 행이 이 파일 이름을 언급해도(D-330 부터) 이 시험은 깨지지 않는다 — 모의: 그런 행을 문서 글에 덧붙여 봐도 번호로 찾은 이 묶음의 행은 그대로 다섯이다."""
        text = self.read("docs/DECISIONS.md") + "\n| D-330 | 2026-11-11 | 다음 묶음이 `own_posts.py` 를 부른다 | 근거 |\n| D-331 | 2026-11-11 | 또 `own_posts.py` 를 말한다 | 근거 |\n"
        mine = [line for line in text.splitlines() if line.startswith("| D-") and "own_posts.py" in line and line.split("|")[1].strip() in self.ROW_WORDS]
        self.assertEqual([line.split("|")[1].strip() for line in mine], list(self.ROW_WORDS))

    def test_the_architecture_the_security_doc_and_the_changelog_carry_a_line_of_this_bundle(self):
        for rel, words in self.LINE_WORDS.items():
            with self.subTest(file=rel):
                lines = [line for line in self.read(rel).splitlines() if "own_posts.py" in line]
                self.assertGreaterEqual(len(lines), 1, "이 파일 이름을 언급한 줄은 한 줄 이상이다(다른 묶음의 줄이 더 있어도 된다)")
                mine = [line for line in lines if all(word in line for word in words)]
                self.assertGreaterEqual(len(mine), 1, f"{rel}: 이 묶음의 줄이 낱말 {words} 를 모두 가져야 한다")
                for line in mine:
                    self.assertNotIn(TILDE, line)
                    self.assertNotRegex(line, r"(?i)(https?|ftp)://|www[.]")

    def test_the_architecture_lists_the_eight_cautions_for_the_next_bundle_right_under_the_module_line(self):
        lines = self.read("docs/ARCHITECTURE.md").splitlines()
        first = next(number for number, line in enumerate(lines) if line.startswith("- **기존 글 읽기 기반**(") and "own_posts.py" in line)
        caution = lines[first + 1]
        self.assertTrue(caution.startswith("  이 읽기 길을 쓰는 N-3a 가 조심할 점 여덟"), caution[:40])
        for mark in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧"):
            self.assertIn(mark, caution)
        for word in ("화면 모델", "error.__traceback__ = None", "keys_adapter", "CRLF", "BOM", "입력 경로의 확장자", "몇 번째 파일", "보이지 않는 글자", "취소", "선형"):
            self.assertIn(word, caution, word)
        self.assertNotIn(TILDE, caution)
        self.assertNotRegex(caution, r"(?i)(https?|ftp)://|www[.]")


if __name__ == "__main__":
    unittest.main()
