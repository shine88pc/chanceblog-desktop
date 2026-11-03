"""비밀 보관소 시험(`security/keystore.py`) — 키·시크릿·토큰은 보관소에만 있고, 어떤 오류 문구·`repr`·시험 실패 출력에도 값이 없다.

지키는 것:
  1) 보관소 번호(ref) 규칙과 JSON·UTF-16 묶기, 자격 증명 값 한도(2,560바이트)의 경계, 짝 없는 대용 문자·잘못된 칸 모양의 거절. **어느 오류에도 값이 담기지 않는다.**
  2) `SecretFields`(꺼낸 값 묶음)는 `repr`·`str`·`format`·직렬화·복사로 값을 내지 않고 바꿀 수 없다.
  3) 보관소 규약(`MemoryStore`·`FileFakeStore`·가짜 API 를 끼운 `WindowsCredentialStore`)이 모두 같다 — 덮어쓰기·없는 값·멱등 삭제·목록(정렬·접두 거르기)·실패 시 옛 값 유지.
  4) 진짜 `advapi32` 대신 **가짜 dll**(진짜 `ctypes` 구조체)을 끼운 `Win32CredApi` 가 구조체를 맞게 채우고, 읽은 메모리를 0 으로 덮고, `CredFree` 를 성공한 읽기·열거마다 정확히 한 번(실패한 읽기에는 0번)
     부르고, 예외가 나도 부른다. 오류 번호가 0 이어도 실패를 성공으로 오해하지 않는다.
  5) 시험 전용 가짜 파일 보관소는 환경 변수·임시 폴더·이름·표시 파일이 **모두** 맞을 때만 열리고, 환경 변수가 없으면 프로그램의 기본 경로는 언제나 진짜 보관소만 연다(설치본 `sys.frozen` 은 환경 변수를 무시).
     소스에서 `memory-file`·`FileFakeStore` 는 `security/keystore.py` 한 곳에만 있다.
  6) 진짜 Windows 자격 증명 관리자 시험은 `CHANCEBLOG_TEST_REAL_CREDSTORE=1` 일 때만 돈다(기본 건너뜀) — 고유한 `ChanceBlogDesktop:__test__:<uuid>` 항목을 만들고 읽고 지우며 `finally` 로 반드시 지운다(가짜 값만).
네트워크·실제 비밀 없이 돈다. 값 표식(`SECRETVALUE…`)이 어느 글에도 없어야 한다는 것이 이 파일의 중심 확인이다.
"""
import ast
import copy
import ctypes
import json
import os
import pickle
import sys
import tempfile
import traceback
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.security import keystore as ks  # noqa: E402

MARKER = "SECRETVALUE" + "-" + "7f3a9c"            # 어떤 문구에도 나오면 안 되는 가짜 값의 표식
REF = "naver_openapi:" + "ab12" * 8
FIELDS = {"client_id": "id-" + "a" * 17, "client_secret": MARKER + "-" + "b" * 10}
NOT_FOUND = 1168
CONTRACT_REFS = ("naver_openapi:bbbb", "naver_openapi:aaaa", "image_provider:cccc", "__test__:zzzz")


def surfaces(error):
    """오류가 사람·로그·개발자에게 보일 수 있는 모든 글(문구·하실 일·세부·기록용 한 줄·`repr`·값 칸·스택 추적)."""
    shown = error.rendered()
    return [str(error), repr(error), error.log_line(), str(error.detail), shown.message, shown.action, shown.retry_text, repr(error.slots), repr(error.args),
            "".join(traceback.format_exception(type(error), error, error.__traceback__))]


def make_fake_dir(root, name=None, *, marker=True):
    """시험 전용 보관소로 열 수 있는 폴더(이름 접두·표시 파일)를 root 안에 만든다."""
    folder = Path(root) / ((name if name is not None else ks.TEST_DIR_PREFIX) + uuid.uuid4().hex[:8])
    folder.mkdir()
    if marker:
        (folder / ks.TEST_MARKER).write_text("fake", encoding="utf-8")
    return folder


class NoLeak(unittest.TestCase):
    def assert_no_leak(self, error, *pieces):
        for text in surfaces(error):
            for piece in pieces:
                self.assertNotIn(piece, text)


class FakeApi:
    """`Win32CredApi` 의 가짜 — 같은 네 함수(write·read·delete·enumerate)를 파이썬 값으로 흉내 낸다. 부른 일은 `calls` 에 남고 `errors[이름]` 에 번호를 넣으면 그 일이 그 번호로 실패한다."""

    def __init__(self):
        self.items = {}
        self.calls = []
        self.errors = {}
        self.extra_names = []              # 열거 결과에 끼워 넣는 남의 이름들(오동작하는 API 흉내)

    def write(self, target, raw):
        self.calls.append(("write", target, bytes(raw)))
        if self.errors.get("write"):
            return self.errors["write"]
        self.items[target] = bytes(raw)
        return 0

    def read(self, target):
        self.calls.append(("read", target))
        if self.errors.get("read"):
            return self.errors["read"], None
        if target not in self.items:
            return NOT_FOUND, None
        return 0, self.items[target]

    def delete(self, target):
        self.calls.append(("delete", target))
        if self.errors.get("delete"):
            return self.errors["delete"]
        if target not in self.items:
            return NOT_FOUND
        del self.items[target]
        return 0

    def enumerate(self, pattern):
        self.calls.append(("enumerate", pattern))
        if self.errors.get("enumerate"):
            return self.errors["enumerate"], []
        head = pattern[:-1]
        names = [name for name in self.items if name.startswith(head)] + list(self.extra_names)
        return (0, names) if names else (NOT_FOUND, [])


class FakeDll:
    """advapi32 의 가짜 — 진짜 ctypes 구조체·포인터로 `Cred*` 함수의 모양을 흉내 낸다(Linux 에서도 돈다). 출력 인자는 `byref(x)._obj` 로 얻어 포인터 값을 직접 채운다."""

    def __init__(self):
        self.items = {}
        self.written = []              # CredWriteW 에서 읽은 구조체 내용
        self.kept = []                 # 넘겨받은 구조체(그 값 메모리가 시험이 볼 때까지 살아 있게)
        self.allocated = []            # 읽기·열거가 '할당' 해 준 (구조체, 버퍼, 크기) — 메모리가 지워졌는지 본다
        self.arrays = []
        self.free_calls = []           # CredFree 로 돌려받은 주소들
        self.fail = set()              # 이 이름의 함수는 0(실패)을 돌려준다
        self.null_entry = False        # 열거 결과의 첫 칸을 널로 둔다(읽다가 예외가 나는 길)
        self.zero_size = False         # 읽기가 크기 0 인 값을 돌려준다
        self.null_result = False       # 읽기가 '성공' 이라면서 아무 포인터도 채워 주지 않는다(있을 수 없는 일)
        self.read_address = None
        self.array_address = None

    def CredWriteW(self, byref_credential, flags):
        credential = byref_credential._obj
        self.kept.append(credential)
        size = credential.CredentialBlobSize
        blob = ctypes.string_at(credential.CredentialBlob, size) if size else b""
        self.written.append({"type": credential.Type, "persist": credential.Persist, "target": credential.TargetName, "size": size, "user": credential.UserName, "flags": flags, "blob": blob})
        if "CredWriteW" in self.fail:
            return 0
        self.items[credential.TargetName] = blob
        return 1

    def _make(self, target, raw):
        credential = ks._CREDENTIALW()
        credential.Type = 1
        credential.TargetName = target
        buffer = None
        if raw:
            buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
            credential.CredentialBlobSize = len(raw)
            credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        self.allocated.append((credential, buffer, len(raw)))
        return credential

    def CredReadW(self, target, type_, flags, byref_out):
        if "CredReadW" in self.fail or target not in self.items:
            return 0
        if self.null_result:
            return 1
        credential = self._make(target, b"" if self.zero_size else self.items[target])
        pointer = ctypes.pointer(credential)
        ctypes.memmove(ctypes.addressof(byref_out._obj), ctypes.addressof(pointer), ctypes.sizeof(pointer))
        self.read_address = ctypes.addressof(credential)
        return 1

    def CredDeleteW(self, target, type_, flags):
        if "CredDeleteW" in self.fail or target not in self.items:
            return 0
        del self.items[target]
        return 1

    def CredEnumerateW(self, pattern, flags, byref_count, byref_out):
        if "CredEnumerateW" in self.fail:
            return 0
        names = [name for name in self.items if name.startswith(pattern[:-1])]
        if not names:
            return 0
        credentials = [self._make(name, self.items[name]) for name in names]
        array = (ctypes.POINTER(ks._CREDENTIALW) * len(credentials))()
        for index, credential in enumerate(credentials):
            if self.null_entry and index == 0:
                continue
            array[index] = ctypes.pointer(credential)
        self.arrays.append(array)
        byref_count._obj.value = len(credentials)
        first = ctypes.cast(array, ctypes.POINTER(ctypes.POINTER(ks._CREDENTIALW)))
        ctypes.memmove(ctypes.addressof(byref_out._obj), ctypes.addressof(first), ctypes.sizeof(first))
        self.array_address = ctypes.addressof(array)
        return 1

    def CredFree(self, pointer):
        self.free_calls.append(ctypes.cast(pointer, ctypes.c_void_p).value)

    def wiped(self):
        """할당해 준 모든 값 메모리가 0 으로 덮였나."""
        return all(buffer is None or ctypes.string_at(ctypes.addressof(buffer), size) == b"\0" * size for _credential, buffer, size in self.allocated)


# ---- 보관소 번호 ----------------------------------------------------------------------------------------------------------------------
class RefTest(NoLeak):
    def test_good_refs_are_accepted_and_returned_unchanged(self):
        for ref in ("naver_openapi:abc123", "__test__:" + "a" * 32, "a:b", "image_provider:A-b_C", "a" + "b" * 39 + ":x", "p:" + "x" * 64, "_:_", "ai_assist:" + "0123456789abcdef" * 2):
            with self.subTest(ref=ref):
                self.assertEqual(ks.check_ref(ref), ref)

    def test_bad_refs_are_refused_with_a_value_error_that_does_not_hold_the_ref(self):
        bad = ("", "naver_openapi", ":abc", "Naver:abc", "naver:abc*", "naver:ab c", "naver:", "9naver:abc", "naver-x:abc", "a" + "b" * 40 + ":x", "p:" + "x" * 65, "naver:abc\n",
               "naver::abc", "naver:한글", "na ver:abc", "naveｒ:abc", "naver:abc:def", "naver\u0000:abc", "*:abc", MARKER + ":x y")
        for ref in bad:
            with self.subTest(ref=ref):
                with self.assertRaises(ValueError) as caught:
                    ks.check_ref(ref)
                self.assertNotIn(MARKER, str(caught.exception))
                self.assertNotIn("naver", str(caught.exception))

    def test_a_ref_that_is_not_text_is_refused(self):
        for ref in (None, 5, b"naver:abc", ["naver:abc"], object()):
            with self.subTest(kind=type(ref).__name__):
                with self.assertRaises(ValueError):
                    ks.check_ref(ref)


# ---- 묶기·한도·오류에 값이 없음 ------------------------------------------------------------------------------------------------------
class EncodeTest(NoLeak):
    def test_fields_round_trip_through_utf16_json_for_text_of_every_kind(self):
        samples = {
            "영문": {"k": "plain-value"}, "한글": {"k": "가나다라마바사"}, "이모지(대용 쌍)": {"k": "🙂🚀"}, "빈 값": {"k": ""}, "따옴표·역슬래시·줄바꿈": {"k": 'a"b\\c\nd'},
            "여러 칸": {"client_id": "x" * 20, "client_secret": "y" * 10, "z_3": "한글🙂"}, "여덟 칸": {f"f{number}": f"v{number}" for number in range(8)},
            "이름 32자": {"a" + "b" * 31: "v"},
        }
        for name, fields in samples.items():
            with self.subTest(sample=name):
                raw = ks.encode_fields(fields)
                self.assertEqual(len(raw) % 2, 0)
                self.assertNotEqual(raw[:2], b"\xff\xfe", "바이트 순서 표시(BOM)를 붙이지 않는다")
                self.assertEqual(json.loads(raw.decode("utf-16-le")), fields)
                self.assertEqual(ks.decode_fields(raw).to_dict(), fields)

    def test_the_encoding_does_not_depend_on_the_order_of_fields(self):
        self.assertEqual(ks.encode_fields({"a": "1", "b": "2"}), ks.encode_fields({"b": "2", "a": "1"}))

    def test_the_value_limit_is_2560_bytes_so_1280_utf16_units_pass_and_one_more_unit_is_refused(self):
        """`{"k":"` 가 6글자, 끝의 `"}` 가 2글자 — 값이 1272글자면 JSON 이 1280글자(UTF-16 2560바이트)다."""
        for name, unit in (("영문", "x"), ("한글", "가"), ("큰따옴표(JSON 에서 두 글자)", None)):
            for length, passes in ((1272, True), (1273, False)):
                value = ('"' * (length // 2 if unit is None else 0)) if unit is None else unit * length
                if unit is None:
                    value = '"' * (636 if passes else 637)
                with self.subTest(kind=name, passes=passes):
                    if passes:
                        self.assertEqual(len(ks.encode_fields({"k": value})), 2560)
                    else:
                        with self.assertRaises(AppError) as caught:
                            ks.encode_fields({"k": value})
                        self.assertEqual(caught.exception.requested_code, "KEY_TOO_LONG")

    def test_a_surrogate_pair_counts_as_two_units(self):
        self.assertEqual(len(ks.encode_fields({"k": "🙂" * 636})), 2560)
        with self.assertRaises(AppError) as caught:
            ks.encode_fields({"k": "🙂" * 637})
        self.assertEqual(caught.exception.requested_code, "KEY_TOO_LONG")

    def test_the_limit_counts_every_field_and_the_json_around_them(self):
        """두 칸이면 `{"a":"` 6 + `","b":"` 7 + `"}` 2 = 15글자가 값 밖에 더 든다 — 값 합계 1265 가 한도다."""
        self.assertEqual(len(ks.encode_fields({"a": "x" * 600, "b": "y" * 665})), 2560)
        with self.assertRaises(AppError) as caught:
            ks.encode_fields({"a": "x" * 600, "b": "y" * 666})
        self.assertEqual(caught.exception.requested_code, "KEY_TOO_LONG")

    def test_too_long_says_the_limit_and_the_size_and_never_the_value(self):
        value = (MARKER * 200)[:1273]
        with self.assertRaises(AppError) as caught:
            ks.encode_fields({"k": value})
        error = caught.exception
        self.assertEqual(error.slots, {"허용 용량": "2,560바이트"})
        self.assertEqual(error.detail, "2,562바이트(UTF-16)")
        self.assert_no_leak(error, MARKER, "SECRETVALUE", value[:20])

    def test_a_lone_surrogate_is_refused_as_an_invalid_shape_and_says_nothing_about_the_text(self):
        value = MARKER + "\ud800" + "tail-" + MARKER
        with self.assertRaises(AppError) as caught:
            ks.encode_fields({"k": value})
        error = caught.exception
        self.assertEqual(error.requested_code, "KEY_INVALID_SHAPE")
        self.assertEqual(error.slots, {"항목": "값", "이유": "표시할 수 없는 글자가 들어 있습니다"})
        self.assertTrue(error.__suppress_context__, "원래 예외(글자가 든 문구)를 오류에 이어 붙이지 않는다")
        self.assert_no_leak(error, MARKER, "SECRETVALUE", "ud800", "\ud800", "tail-")

    def test_a_wrong_shape_of_fields_is_a_type_error_with_no_value_in_it(self):
        too_many = {f"f{number}": "v" for number in range(9)}
        cases = {
            "비어 있음": {}, "아홉 칸": too_many, "대문자 이름": {"Bad": "v"}, "숫자로 시작": {"1a": "v"}, "공백이 든 이름": {"a b": "v"}, "빈 이름": {"": "v"}, "이름 33자": {"a" + "b" * 32: "v"},
            "숫자 값": {"k": 5}, "None 값": {"k": None}, "바이트 값": {"k": MARKER.encode()}, "리스트 값": {"k": [MARKER]}, "글이 아닌 이름": {5: "v"}, "리스트": [MARKER], "글": MARKER, "None": None,
        }
        for name, fields in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(TypeError) as caught:
                    ks.encode_fields(fields)
                self.assertNotIn(MARKER, str(caught.exception))
                self.assertNotIn("SECRETVALUE", str(caught.exception))

    def test_decoding_a_foreign_or_broken_blob_is_refused_without_showing_what_was_in_it(self):
        text = MARKER + "-not-json"
        blobs = {
            "홀수 바이트": text.encode("utf-16-le") + b"\x00", "JSON 아님": text.encode("utf-16-le"), "리스트": json.dumps([MARKER]).encode("utf-16-le"),
            "빈 객체": b"{\x00}\x00", "값이 글이 아님": json.dumps({"k": [MARKER]}).encode("utf-16-le"), "칸 이름 틀림": json.dumps({"Bad Name": MARKER}).encode("utf-16-le"),
            "아홉 칸": json.dumps({f"f{number}": MARKER for number in range(9)}).encode("utf-16-le"), "UTF-8 로 적힘": json.dumps({"k": MARKER}).encode("utf-8"),
            "짝 없는 대용 문자": b"\x00\xd8" * 3, "빈 바이트": b"",
        }
        for name, raw in blobs.items():
            with self.subTest(blob=name):
                with self.assertRaises(AppError) as caught:
                    ks.decode_fields(raw)
                self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
                self.assert_no_leak(caught.exception, MARKER, "SECRETVALUE", "not-json")

    def test_the_detail_of_a_decode_failure_names_only_the_kind_of_error(self):
        for name, raw, kind in (("홀수 바이트", (MARKER + "x").encode("utf-16-le") + b"\x00", "UnicodeDecodeError"), ("JSON 아님", (MARKER + "x").encode("utf-16-le"), "JSONDecodeError"),
                                ("짝 없는 대용 문자", b"\x00\xd8" * 3, "UnicodeDecodeError")):
            with self.subTest(blob=name):
                with self.assertRaises(AppError) as caught:
                    ks.decode_fields(raw)
                self.assertEqual(caught.exception.detail, f"보관된 값을 해석하지 못했다({kind})")
        with self.assertRaises(AppError) as shape:
            ks.decode_fields(json.dumps([MARKER]).encode("utf-16-le"))
        self.assertEqual(shape.exception.detail, "보관된 값의 모양이 올바르지 않다")


# ---- 꺼낸 값 묶음 ----------------------------------------------------------------------------------------------------------------------
class SecretFieldsTest(unittest.TestCase):
    def setUp(self):
        self.fields = ks.SecretFields(FIELDS)

    def test_no_text_form_of_the_object_shows_a_value_or_even_a_field_name(self):
        shown = {
            "repr": repr(self.fields), "str": str(self.fields), "format": format(self.fields), "format+서식": format(self.fields, ">60"), "f-string": f"{self.fields}", "f-string !r": f"{self.fields!r:>60}",
            "%s": "%s" % (self.fields,), "%r": "%r" % (self.fields,), "리스트 속": str([self.fields]), "딕셔너리 속": str({"k": self.fields}), "튜플 속": repr((self.fields,)),
        }
        for name, text in shown.items():
            with self.subTest(form=name):
                for piece in (MARKER, "SECRETVALUE", "client_secret", "client_id", FIELDS["client_id"]):
                    self.assertNotIn(piece, text)
        self.assertEqual(repr(self.fields), "<SecretFields 칸 2개 — 값은 가려져 있음>")
        self.assertEqual(str(self.fields), repr(self.fields))

    def test_it_cannot_be_pickled_or_copied(self):
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=protocol):
                with self.assertRaises(TypeError):
                    pickle.dumps(self.fields, protocol=protocol)
        with self.assertRaises(TypeError):
            copy.copy(self.fields)
        with self.assertRaises(TypeError):
            copy.deepcopy(self.fields)

    def test_it_cannot_be_changed(self):
        with self.assertRaises(AttributeError):
            self.fields._data = {}
        with self.assertRaises(AttributeError):
            self.fields.other = 1
        with self.assertRaises(AttributeError):
            del self.fields._data
        self.assertEqual(self.fields.reveal("client_id"), FIELDS["client_id"])

    def test_values_come_out_only_through_reveal_and_to_dict(self):
        self.assertEqual(self.fields.reveal("client_secret"), FIELDS["client_secret"])
        self.assertEqual(self.fields.to_dict(), FIELDS)
        self.assertEqual(self.fields.names(), ("client_id", "client_secret"))
        self.assertEqual(len(self.fields), 2)
        self.assertIn("client_id", self.fields)
        self.assertNotIn("other", self.fields)

    def test_a_missing_field_is_a_key_error_that_names_only_the_field(self):
        with self.assertRaises(KeyError) as caught:
            self.fields.reveal("nope")
        self.assertEqual(caught.exception.args, ("nope",))

    def test_the_copy_from_to_dict_and_the_input_dict_are_not_shared_with_the_object(self):
        source = dict(FIELDS)
        fields = ks.SecretFields(source)
        source["client_id"] = "changed"
        self.assertEqual(fields.reveal("client_id"), FIELDS["client_id"])
        copied = fields.to_dict()
        copied["client_id"] = "changed-too"
        self.assertEqual(fields.reveal("client_id"), FIELDS["client_id"])

    def test_a_failing_test_assertion_does_not_print_the_values(self):
        other = ks.SecretFields({"client_id": "different"})
        messages = []
        for work in (lambda: self.assertEqual(self.fields, other), lambda: self.assertIn("zzz", self.fields), lambda: self.assertIs(self.fields, other), lambda: self.assertEqual([self.fields], [other]),
                     lambda: self.assertEqual({"k": self.fields}, {"k": other}), lambda: self.assertIsNone(self.fields)):
            try:
                work()
            except AssertionError as error:
                messages.append(str(error))
        self.assertEqual(len(messages), 6, "모든 실패가 실제로 났어야 이 시험이 의미가 있다")
        for text in messages:
            for piece in (MARKER, "SECRETVALUE", FIELDS["client_id"], "different"):
                self.assertNotIn(piece, text)


# ---- 보관소 규약(모든 구현이 같다) ---------------------------------------------------------------------------------------------------------
class ContractMixin:
    """모든 보관소 구현이 같은 규약을 지키는지 본다 — 구현마다 `make_store` 만 정해 이 믹스인과 `unittest.TestCase` 를 함께 상속한다."""

    def make_store(self):
        raise NotImplementedError

    def setUp(self):
        self.store = self.make_store()

    def test_put_then_get_returns_the_same_fields_as_a_secret_fields_object(self):
        self.store.put(REF, FIELDS)
        got = self.store.get(REF)
        self.assertIsInstance(got, ks.SecretFields)
        self.assertEqual(got.to_dict(), FIELDS)
        self.assertIsNot(self.store.get(REF), got)

    def test_a_missing_ref_gives_none_and_does_not_exist(self):
        self.assertIsNone(self.store.get(REF))
        self.assertFalse(self.store.exists(REF))
        self.store.put(REF, FIELDS)
        self.assertTrue(self.store.exists(REF))
        self.assertFalse(self.store.exists("naver_openapi:other"))

    def test_putting_again_overwrites_without_adding_a_second_item(self):
        self.store.put(REF, FIELDS)
        self.store.put(REF, {"client_id": "second-" + "z" * 8})
        self.assertEqual(self.store.get(REF).to_dict(), {"client_id": "second-" + "z" * 8})
        self.assertEqual(self.store.list_refs(), [REF])

    def test_delete_is_idempotent_and_reports_whether_something_was_there(self):
        self.store.put(REF, FIELDS)
        self.assertIs(self.store.delete(REF), True)
        self.assertIs(self.store.delete(REF), False)
        self.assertIsNone(self.store.get(REF))
        self.assertFalse(self.store.exists(REF))
        self.assertEqual(self.store.list_refs(), [])

    def test_the_list_is_sorted_and_can_be_narrowed_by_a_prefix(self):
        for ref in CONTRACT_REFS:
            self.store.put(ref, {"k": "v-" + ref})
        self.assertEqual(self.store.list_refs(), sorted(CONTRACT_REFS))
        self.assertEqual(self.store.list_refs(""), sorted(CONTRACT_REFS))
        self.assertEqual(self.store.list_refs("naver_openapi:"), ["naver_openapi:aaaa", "naver_openapi:bbbb"])
        self.assertEqual(self.store.list_refs("naver"), ["naver_openapi:aaaa", "naver_openapi:bbbb"])
        self.assertEqual(self.store.list_refs("image_provider:c"), ["image_provider:cccc"])
        self.assertEqual(self.store.list_refs("__test__:"), ["__test__:zzzz"])
        self.assertEqual(self.store.list_refs("nothing"), [])
        self.assertEqual(self.store.list_refs("naver_openapi:aaaa"), ["naver_openapi:aaaa"])
        self.store.delete("naver_openapi:aaaa")
        self.assertEqual(self.store.list_refs("naver_openapi:"), ["naver_openapi:bbbb"])

    def test_a_prefix_with_a_wildcard_or_a_wrong_shape_is_refused(self):
        self.store.put(REF, FIELDS)
        for prefix in ("Naver", "naver*", "*", ":abc", "a:b:c", "naver_openapi:ab*", "naver openapi", "naver\n", 5, None, b"naver"):
            with self.subTest(prefix=prefix):
                with self.assertRaises(ValueError):
                    self.store.list_refs(prefix)

    def test_every_operation_refuses_a_bad_ref(self):
        for ref in ("", "naver_openapi", "Naver:abc", "naver:abc*", None):
            for name, work, args in (("put", self.store.put, (ref, FIELDS)), ("get", self.store.get, (ref,)), ("delete", self.store.delete, (ref,)), ("exists", self.store.exists, (ref,))):
                with self.subTest(ref=ref, operation=name):
                    with self.assertRaises(ValueError):
                        work(*args)

    def test_a_refused_put_leaves_the_old_value_alone(self):
        self.store.put(REF, FIELDS)
        too_long = {"k": "x" * 1273}
        with self.assertRaises(AppError) as long_error:
            self.store.put(REF, too_long)
        self.assertEqual(long_error.exception.requested_code, "KEY_TOO_LONG")
        with self.assertRaises(AppError) as shape_error:
            self.store.put(REF, {"k": "\ud800"})
        self.assertEqual(shape_error.exception.requested_code, "KEY_INVALID_SHAPE")
        with self.assertRaises(TypeError):
            self.store.put(REF, {"k": 5})
        self.assertEqual(self.store.get(REF).to_dict(), FIELDS)

    def test_the_limit_boundary_holds_through_the_store(self):
        self.store.put(REF, {"k": "가" * 1272})
        self.assertEqual(self.store.get(REF).reveal("k"), "가" * 1272)
        with self.assertRaises(AppError) as caught:
            self.store.put(REF, {"k": "가" * 1273})
        self.assertEqual(caught.exception.requested_code, "KEY_TOO_LONG")
        self.assertEqual(self.store.get(REF).reveal("k"), "가" * 1272, "한도를 넘긴 쓰기가 옛 값을 지우지 않는다")

    def test_text_of_every_kind_survives_a_round_trip(self):
        fields = {"k": '한글 🙂 "따옴표" \\ \n 줄바꿈', "other": ""}
        self.store.put(REF, fields)
        self.assertEqual(self.store.get(REF).to_dict(), fields)

    def test_changing_the_input_after_put_does_not_change_what_is_stored(self):
        fields = dict(FIELDS)
        self.store.put(REF, fields)
        fields["client_id"] = "changed"
        self.assertEqual(self.store.get(REF).to_dict(), FIELDS)

    def test_the_store_object_shows_no_value_in_any_text_form(self):
        self.store.put(REF, FIELDS)
        for text in (repr(self.store), str(self.store), f"{self.store}", "%r" % (self.store,), str([self.store])):
            for piece in (MARKER, "SECRETVALUE", FIELDS["client_id"], "client_secret"):
                self.assertNotIn(piece, text)


class MemoryStoreContractTest(ContractMixin, unittest.TestCase):
    def make_store(self):
        return ks.MemoryStore()


class FileFakeStoreContractTest(ContractMixin, unittest.TestCase):
    def make_store(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        return ks.FileFakeStore(make_fake_dir(tmp.name))


class WindowsStoreContractTest(ContractMixin, unittest.TestCase):
    def make_store(self):
        return ks.WindowsCredentialStore(FakeApi())


class MemoryStoreTest(NoLeak):
    def test_the_repr_counts_items_and_a_store_starts_empty(self):
        store = ks.MemoryStore()
        self.assertEqual(repr(store), "<MemoryStore 항목 0개>")
        store.put(REF, FIELDS)
        self.assertEqual(repr(store), "<MemoryStore 항목 1개>")

    def test_a_blob_changed_by_someone_else_is_refused_on_get_without_showing_it(self):
        store = ks.MemoryStore()
        text = MARKER + "-foreign"
        for name, raw in {"JSON 아님": text.encode("utf-16-le"), "홀수 바이트": text.encode("utf-16-le") + b"\x01", "리스트": json.dumps([text]).encode("utf-16-le"),
                          "값이 글이 아님": json.dumps({"k": [text]}).encode("utf-16-le"), "UTF-8": text.encode("utf-8")}.items():
            with self.subTest(blob=name):
                store._blobs[REF] = raw
                with self.assertRaises(AppError) as caught:
                    store.get(REF)
                self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
                self.assert_no_leak(caught.exception, MARKER, "SECRETVALUE", "foreign")
                self.assertTrue(store.exists(REF), "읽을 수 없는 값도 '있다' 고 알린다(지우는 것은 사용자의 결정이다)")
                self.assertTrue(store.delete(REF))

    def test_the_base_class_does_nothing_by_itself(self):
        for work in (lambda: ks.KeyStore().put(REF, FIELDS), lambda: ks.KeyStore().get(REF), lambda: ks.KeyStore().delete(REF), lambda: ks.KeyStore().list_refs()):
            with self.assertRaises(NotImplementedError):
                work()


# ---- Windows 자격 증명 관리자 보관소(가짜 API) -----------------------------------------------------------------------------------------------
class WindowsCredentialStoreTest(NoLeak):
    def setUp(self):
        self.api = FakeApi()
        self.store = ks.WindowsCredentialStore(self.api)

    def test_the_target_name_is_the_app_name_then_the_ref_and_the_bytes_are_utf16_json_within_the_limit(self):
        self.store.put(REF, FIELDS)
        (name, target, raw), = self.api.calls
        self.assertEqual((name, target), ("write", "ChanceBlogDesktop:" + REF))
        self.assertLessEqual(len(raw), 2560)
        self.assertEqual(len(raw) % 2, 0)
        self.assertEqual(json.loads(raw.decode("utf-16-le")), FIELDS)

    def test_a_value_over_the_limit_is_refused_before_the_api_is_called(self):
        with self.assertRaises(AppError) as caught:
            self.store.put(REF, {"k": "x" * 1273})
        self.assertEqual(caught.exception.requested_code, "KEY_TOO_LONG")
        self.assertEqual(self.api.calls, [])
        self.store.put(REF, {"k": "x" * 1272})
        self.assertEqual(len(self.api.calls[0][2]), 2560)

    def test_a_failed_write_is_a_key_store_error_with_only_the_error_number(self):
        for number in (5, 1312, 87, 2202):
            with self.subTest(number=number):
                self.api.errors["write"] = number
                with self.assertRaises(AppError) as caught:
                    self.store.put(REF, FIELDS)
                self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
                self.assertEqual(caught.exception.detail, f"CredWriteW 실패(오류 번호 {number})")
                self.assert_no_leak(caught.exception, MARKER, "SECRETVALUE")

    def test_read_errors_a_missing_item_is_none_and_any_other_number_is_a_failure(self):
        self.api.errors["read"] = NOT_FOUND
        self.assertIsNone(self.store.get(REF))
        self.assertFalse(self.store.exists(REF))
        for number in (5, 1312, 1):
            with self.subTest(number=number):
                self.api.errors["read"] = number
                for work in (lambda: self.store.get(REF), lambda: self.store.exists(REF)):
                    with self.assertRaises(AppError) as caught:
                        work()
                    self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
                    self.assertEqual(caught.exception.detail, f"CredReadW 실패(오류 번호 {number})")

    def test_delete_errors_a_missing_item_is_false_and_any_other_number_is_a_failure(self):
        self.api.errors["delete"] = NOT_FOUND
        self.assertIs(self.store.delete(REF), False)
        for number in (5, 1312):
            with self.subTest(number=number):
                self.api.errors["delete"] = number
                with self.assertRaises(AppError) as caught:
                    self.store.delete(REF)
                self.assertEqual(caught.exception.detail, f"CredDeleteW 실패(오류 번호 {number})")

    def test_enumerate_asks_for_the_app_prefix_with_a_trailing_wildcard_and_maps_errors(self):
        self.store.put(REF, FIELDS)
        for prefix in ("", "naver_openapi:", "__test__:", "naver"):
            with self.subTest(prefix=prefix):
                self.api.calls.clear()
                self.store.list_refs(prefix)
                self.assertEqual(self.api.calls, [("enumerate", f"ChanceBlogDesktop:{prefix}*")])
        self.api.errors["enumerate"] = NOT_FOUND
        self.assertEqual(self.store.list_refs("zzz"), [])
        self.api.errors["enumerate"] = 5
        with self.assertRaises(AppError) as caught:
            self.store.list_refs("")
        self.assertEqual(caught.exception.detail, "CredEnumerateW 실패(오류 번호 5)")

    def test_names_that_are_not_ours_are_dropped_from_the_list(self):
        self.store.put(REF, FIELDS)
        self.api.extra_names = ["Other:naver_openapi:zzz", "ChanceBlogDesktop:Bad Name!", "ChanceBlogDesktop:", "ChanceBlogDesktop:UPPER:abc", 123, None, "ChanceBlogDesktop:image_provider:ok1"]
        self.assertEqual(self.store.list_refs(""), sorted([REF, "image_provider:ok1"]))
        self.assertEqual(self.store.list_refs("naver_openapi:"), [REF])

    def test_without_an_api_a_non_windows_environment_is_refused_and_with_one_it_is_not(self):
        with self.assertRaises(AppError) as caught:
            ks.WindowsCredentialStore(windows=False)
        self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
        self.assertEqual(caught.exception.detail, "Windows 가 아닌 환경이라 자격 증명 관리자를 쓸 수 없다")
        self.assertIsInstance(ks.WindowsCredentialStore(FakeApi(), windows=False), ks.WindowsCredentialStore)
        self.assertIsInstance(ks.WindowsCredentialStore(FakeApi(), windows=True), ks.WindowsCredentialStore)

    def test_a_failure_to_load_the_system_library_is_a_key_store_error_that_keeps_the_message_out(self):
        for error in (OSError(MARKER), AttributeError(MARKER)):
            with self.subTest(kind=type(error).__name__):
                with mock.patch.object(ks, "_load_advapi32", side_effect=error):
                    with self.assertRaises(AppError) as caught:
                        ks.WindowsCredentialStore(windows=True)
                self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
                self.assertIn(type(error).__name__, caught.exception.detail)
                self.assert_no_leak(caught.exception, MARKER, "SECRETVALUE")

    def test_the_repr_is_fixed_text(self):
        self.store.put(REF, FIELDS)
        self.assertEqual(repr(self.store), "<WindowsCredentialStore>")
        self.assertFalse(self.store.is_fake)


# ---- ctypes 층(가짜 dll) ------------------------------------------------------------------------------------------------------------------
class CredentialLayoutTest(unittest.TestCase):
    def test_the_structure_matches_the_documented_credentialw_layout(self):
        cred = ks._CREDENTIALW
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            expected = {"Flags": 0, "Type": 4, "TargetName": 8, "Comment": 16, "LastWritten": 24, "CredentialBlobSize": 32, "CredentialBlob": 40, "Persist": 48, "AttributeCount": 52,
                        "Attributes": 56, "TargetAlias": 64, "UserName": 72}
            self.assertEqual(ctypes.sizeof(cred), 80)
        else:
            expected = {"Flags": 0, "Type": 4, "TargetName": 8, "Comment": 12, "LastWritten": 16, "CredentialBlobSize": 24, "CredentialBlob": 28, "Persist": 32, "AttributeCount": 36,
                        "Attributes": 40, "TargetAlias": 44, "UserName": 48}
            self.assertEqual(ctypes.sizeof(cred), 52)
        for name, offset in expected.items():
            with self.subTest(field=name):
                self.assertEqual(getattr(cred, name).offset, offset)
        self.assertEqual(ctypes.sizeof(ks._FILETIME), 8)


class Win32CredApiTest(unittest.TestCase):
    def setUp(self):
        self.dll = FakeDll()
        self.error = 0
        self.api = ks.Win32CredApi(self.dll, lambda: self.error)
        self.target = "ChanceBlogDesktop:" + REF
        self.raw = ks.encode_fields(FIELDS)

    def test_write_fills_the_structure_with_the_generic_type_the_local_machine_persistence_and_the_bytes(self):
        self.assertEqual(self.api.write(self.target, self.raw), 0)
        (call,) = self.dll.written
        self.assertEqual(call, {"type": 1, "persist": 2, "target": self.target, "size": len(self.raw), "user": "ChanceBlogDesktop", "flags": 0, "blob": self.raw})

    def test_write_wipes_the_copy_it_handed_over_even_though_the_fake_kept_the_structure(self):
        self.api.write(self.target, self.raw)
        kept = self.dll.kept[0]
        self.assertEqual(ctypes.string_at(kept.CredentialBlob, kept.CredentialBlobSize), b"\0" * len(self.raw))

    def test_write_reports_the_last_error_number_and_never_zero_for_a_failure(self):
        self.dll.fail.add("CredWriteW")
        for last, expected in ((5, 5), (1312, 1312), (0, 1), (None, 1)):
            with self.subTest(last_error=last):
                self.error = last
                self.assertEqual(self.api.write(self.target, self.raw), expected)
        self.assertEqual(self.dll.items, {})

    def test_read_returns_the_bytes_wipes_the_memory_it_was_given_and_frees_it_exactly_once(self):
        self.api.write(self.target, self.raw)
        self.assertEqual(self.api.read(self.target), (0, self.raw))
        self.assertEqual(len(self.dll.allocated), 1)
        self.assertTrue(self.dll.wiped(), "관리자가 돌려준 원본 메모리를 0 으로 덮어야 한다")
        self.assertEqual(self.dll.free_calls, [self.dll.read_address])

    def test_each_successful_read_frees_once_and_a_failed_read_frees_nothing(self):
        self.api.write(self.target, self.raw)
        for count in (1, 2, 3):
            self.api.read(self.target)
            self.assertEqual(len(self.dll.free_calls), count)
        before = list(self.dll.free_calls)
        for last, expected in ((NOT_FOUND, NOT_FOUND), (5, 5), (0, 1)):
            with self.subTest(last_error=last):
                self.error = last
                self.assertEqual(self.api.read("ChanceBlogDesktop:naver_openapi:missing"), (expected, None))
        self.dll.fail.add("CredReadW")
        self.assertEqual(self.api.read(self.target)[1], None)
        self.assertEqual(self.dll.free_calls, before, "실패한 읽기에서는 돌려줄 메모리가 없다")

    def test_a_stored_value_of_size_zero_reads_as_empty_bytes_and_is_still_freed(self):
        self.api.write(self.target, self.raw)
        self.dll.zero_size = True
        self.assertEqual(self.api.read(self.target), (0, b""))
        self.assertEqual(self.dll.free_calls, [self.dll.read_address])

    def test_a_success_that_hands_back_no_pointer_is_a_failure_and_never_reads_a_null_pointer(self):
        self.api.write(self.target, self.raw)
        self.dll.null_result = True
        for last, expected in ((0, 1), (5, 5)):
            with self.subTest(last_error=last):
                self.error = last
                self.assertEqual(self.api.read(self.target), (expected, None))
        self.assertEqual(self.dll.free_calls, [], "돌려받은 메모리가 없으니 돌려줄 것도 없다")

    def test_delete_returns_zero_or_the_error_number(self):
        self.api.write(self.target, self.raw)
        self.assertEqual(self.api.delete(self.target), 0)
        self.assertEqual(self.dll.items, {})
        self.error = NOT_FOUND
        self.assertEqual(self.api.delete(self.target), NOT_FOUND)
        self.error = 0
        self.assertEqual(self.api.delete(self.target), 1)

    def test_enumerate_returns_the_names_wipes_the_blobs_and_frees_the_array_once(self):
        names = ["ChanceBlogDesktop:naver_openapi:one", "ChanceBlogDesktop:naver_openapi:two", "ChanceBlogDesktop:image_provider:three"]
        for name in names:
            self.api.write(name, self.raw)
        self.assertEqual(self.api.enumerate("ChanceBlogDesktop:*"), (0, names))
        self.assertEqual(self.dll.free_calls, [self.dll.array_address])
        self.assertEqual(len(self.dll.allocated), 3)
        self.assertTrue(self.dll.wiped())
        self.dll.free_calls.clear()
        self.assertEqual(self.api.enumerate("ChanceBlogDesktop:naver_openapi:*"), (0, names[:2]))
        self.assertEqual(self.dll.free_calls, [self.dll.array_address])

    def test_a_failed_enumeration_frees_nothing_and_reports_the_error(self):
        for last, expected in ((NOT_FOUND, NOT_FOUND), (5, 5), (0, 1)):
            with self.subTest(last_error=last):
                self.error = last
                self.assertEqual(self.api.enumerate("ChanceBlogDesktop:none*"), (expected, []))
        self.assertEqual(self.dll.free_calls, [])

    def test_the_array_is_freed_even_when_reading_an_entry_raises(self):
        self.api.write(self.target, self.raw)
        self.dll.null_entry = True
        with self.assertRaises(ValueError):
            self.api.enumerate("ChanceBlogDesktop:*")
        self.assertEqual(self.dll.free_calls, [self.dll.array_address], "예외가 나도 CredFree 를 돌려준다")

    def test_the_whole_store_works_on_top_of_the_fake_dll(self):
        store = ks.WindowsCredentialStore(self.api)
        store.put(REF, FIELDS)
        store.put("image_provider:abcd", {"access_key": "k" * 20})
        self.assertEqual(store.get(REF).to_dict(), FIELDS)
        self.assertTrue(store.exists(REF))
        self.assertEqual(store.list_refs(), sorted([REF, "image_provider:abcd"]))
        self.assertEqual(store.list_refs("image_provider:"), ["image_provider:abcd"])
        self.assertIs(store.delete(REF), True)
        self.error = NOT_FOUND                     # 진짜 Windows 는 없는 항목에 이 번호를 남긴다 — 가짜 dll 은 번호를 정하지 않으므로 시험이 정한다
        self.assertIs(store.delete(REF), False)
        self.assertIsNone(store.get(REF))
        self.assertEqual(store.list_refs("naver_openapi:"), [])
        self.assertTrue(self.dll.wiped())

    def test_the_real_library_is_not_loaded_when_a_dll_is_given(self):
        with mock.patch.object(ks, "_load_advapi32", side_effect=AssertionError("진짜 라이브러리를 불렀다")):
            ks.Win32CredApi(FakeDll(), lambda: 0)


# ---- 시험 전용 가짜 파일 보관소와 기본 보관소 고르기 ------------------------------------------------------------------------------------------
class FileFakeStoreTest(NoLeak):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = make_fake_dir(self.root)
        self.store = ks.FileFakeStore(self.folder)
        self.file = self.folder / ks.TEST_FILE

    def test_it_says_it_is_fake_and_leaves_no_temporary_file_after_a_write(self):
        self.assertTrue(self.store.is_fake)
        self.assertEqual(repr(self.store), "<FileFakeStore 시험 전용>")
        self.store.put(REF, FIELDS)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), sorted([ks.TEST_MARKER, ks.TEST_FILE]))

    def test_a_file_that_is_not_the_expected_shape_is_refused_by_every_operation_without_showing_it(self):
        text = MARKER + "-garbage"
        for name, content in {"JSON 아님": text, "리스트": json.dumps([text]), "값이 글이 아님": json.dumps({REF: 5}), "빈 글": ""}.items():
            with self.subTest(content=name):
                self.file.write_text(content, encoding="utf-8")
                for work in (lambda: self.store.get(REF), lambda: self.store.put(REF, FIELDS), lambda: self.store.delete(REF), lambda: self.store.list_refs(), lambda: self.store.exists(REF)):
                    with self.assertRaises(AppError) as caught:
                        work()
                    self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
                    self.assert_no_leak(caught.exception, MARKER, "SECRETVALUE", "garbage")

    def test_a_value_that_is_not_hex_is_refused_on_read(self):
        self.file.write_text(json.dumps({REF: "zz-" + MARKER}), encoding="utf-8")
        with self.assertRaises(AppError) as caught:
            self.store.get(REF)
        self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
        self.assert_no_leak(caught.exception, MARKER, "SECRETVALUE")

    def test_a_ref_in_the_file_with_a_wrong_shape_is_left_out_of_the_list(self):
        self.store.put(REF, FIELDS)
        data = json.loads(self.file.read_text(encoding="utf-8"))
        data["Not A Ref"] = "00"
        self.file.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.store.list_refs(), [REF])

    def test_a_failed_write_is_a_key_store_error_and_keeps_the_old_content(self):
        self.store.put(REF, FIELDS)
        with mock.patch.object(ks.os, "replace", side_effect=OSError(13, MARKER)):
            with self.assertRaises(AppError) as caught:
                self.store.put("image_provider:new1", {"k": "v"})
        self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
        self.assert_no_leak(caught.exception, MARKER, "SECRETVALUE")
        self.assertEqual(self.store.get(REF).to_dict(), FIELDS)
        self.assertIsNone(self.store.get("image_provider:new1"))


class OpenTestDirTest(NoLeak):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.good = make_fake_dir(self.root)

    def env(self, folder=None, value=ks.TEST_STORE_VALUE):
        found = {}
        if value is not None:
            found[ks.ENV_KEYSTORE] = value
        if folder is not None:
            found[ks.ENV_KEYSTORE_DIR] = str(folder)
        return found

    def refused(self, env, temp_root=None):
        with self.assertRaises(AppError) as caught:
            ks.open_test_dir(env, temp_root=self.root if temp_root is None else temp_root)
        self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
        return caught.exception

    def test_a_folder_that_passes_every_guard_is_accepted(self):
        self.assertEqual(ks.open_test_dir(self.env(self.good), temp_root=self.root), Path(os.path.realpath(self.good)))

    def test_the_variable_must_be_exactly_memory_file(self):
        for value in (None, "", "memory", "MEMORY-FILE", "memory-file ", "windows", "real", "1", "true", "file"):
            with self.subTest(value=value):
                self.refused(self.env(self.good, value))

    def test_a_missing_or_relative_folder_is_refused(self):
        for folder in (None, "", "relative/" + ks.TEST_DIR_PREFIX + "x", ks.TEST_DIR_PREFIX + "x", "."):
            with self.subTest(folder=folder):
                self.refused(self.env(folder))

    def test_a_relative_path_is_refused_even_when_it_would_resolve_to_a_good_folder_from_the_current_directory(self):
        before = os.getcwd()
        self.addCleanup(os.chdir, before)
        os.chdir(self.root)
        self.assertTrue((Path(self.good.name) / ks.TEST_MARKER).is_file(), "시험 준비: 현재 폴더 기준으로는 좋은 폴더다")
        self.refused(self.env(self.good.name))
        self.refused(self.env("." + os.sep + self.good.name))
        self.assertEqual(ks.open_test_dir(self.env(self.good), temp_root=self.root), Path(os.path.realpath(self.good)))

    def test_a_folder_outside_the_given_temporary_root_is_refused(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as other_root:
            outside = make_fake_dir(other_root)
            self.refused(self.env(outside))
            self.assertEqual(ks.open_test_dir(self.env(outside), temp_root=other_root), Path(os.path.realpath(outside)))

    def test_the_temporary_root_itself_is_refused_even_with_the_right_name_and_marker(self):
        with tempfile.TemporaryDirectory(prefix=ks.TEST_DIR_PREFIX, ignore_cleanup_errors=True) as named_root:
            (Path(named_root) / ks.TEST_MARKER).write_text("fake", encoding="utf-8")
            self.refused(self.env(named_root), temp_root=named_root)

    def test_a_wrong_name_prefix_is_refused(self):
        for name in ("other-", "chanceblog-keystore-", "CHANCEBLOG-FAKE-KEYSTORE-", "x" + ks.TEST_DIR_PREFIX):
            with self.subTest(name=name):
                self.refused(self.env(make_fake_dir(self.root, name)))

    def test_a_missing_marker_or_a_marker_that_is_a_folder_is_refused(self):
        self.refused(self.env(make_fake_dir(self.root, marker=False)))
        folder = make_fake_dir(self.root, marker=False)
        (folder / ks.TEST_MARKER).mkdir()
        self.refused(self.env(folder))

    def test_a_dot_dot_path_that_leaves_the_checked_folder_is_refused(self):
        evil = self.root / "evil"
        evil.mkdir()
        (evil / ks.TEST_MARKER).write_text("fake", encoding="utf-8")
        self.refused(self.env(str(self.good) + os.sep + ".." + os.sep + "evil"))
        self.refused(self.env(str(self.good) + os.sep + ".."))

    def test_the_default_temporary_folder_of_the_machine_is_used_when_no_root_is_given(self):
        folder = Path(tempfile.mkdtemp(prefix=ks.TEST_DIR_PREFIX))
        self.addCleanup(lambda: [path.unlink() for path in folder.iterdir()] and None or folder.rmdir())
        (folder / ks.TEST_MARKER).write_text("fake", encoding="utf-8")
        self.assertEqual(ks.open_test_dir(self.env(folder)), Path(os.path.realpath(folder)))


class DefaultKeystoreTest(NoLeak):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.good = make_fake_dir(self.root)
        self.test_env = {ks.ENV_KEYSTORE: ks.TEST_STORE_VALUE, ks.ENV_KEYSTORE_DIR: str(self.good)}

    def test_without_the_variable_only_the_real_store_is_ever_opened_and_on_a_non_windows_machine_that_is_refused(self):
        for env in ({}, {ks.ENV_KEYSTORE: ""}, {ks.ENV_KEYSTORE_DIR: str(self.good)}, {"CHANCEBLOG_DESKTOP_DATA": str(self.root)}):
            with self.subTest(env=sorted(env)):
                with self.assertRaises(AppError) as caught:
                    ks.default_keystore(env, windows=False, temp_root=self.root)
                self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
                self.assertEqual(caught.exception.detail, "Windows 가 아닌 환경이라 자격 증명 관리자를 쓸 수 없다")

    def test_without_the_variable_a_given_api_gives_the_real_kind_of_store_and_never_the_fake(self):
        for env in ({}, {ks.ENV_KEYSTORE: ""}, {ks.ENV_KEYSTORE_DIR: str(self.good)}):
            with self.subTest(env=sorted(env)):
                store = ks.default_keystore(env, windows=False, api=FakeApi(), temp_root=self.root)
                self.assertIsInstance(store, ks.WindowsCredentialStore)
                self.assertFalse(store.is_fake)

    def test_with_every_guard_satisfied_the_fake_file_store_opens_and_works(self):
        store = ks.default_keystore(self.test_env, windows=False, api=FakeApi(), temp_root=self.root)
        self.assertIsInstance(store, ks.FileFakeStore)
        self.assertTrue(store.is_fake)
        store.put(REF, FIELDS)
        self.assertEqual(store.get(REF).to_dict(), FIELDS)
        self.assertEqual(store.list_refs("naver"), [REF])

    def test_with_the_variable_set_but_any_guard_failing_nothing_opens_and_the_real_store_is_not_used_instead(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as other_root:
            bad_envs = {
                "값이 다름": {ks.ENV_KEYSTORE: "memory", ks.ENV_KEYSTORE_DIR: str(self.good)}, "폴더 없음": {ks.ENV_KEYSTORE: ks.TEST_STORE_VALUE}, "상대 경로": {ks.ENV_KEYSTORE: ks.TEST_STORE_VALUE, ks.ENV_KEYSTORE_DIR: "x"},
                "임시 폴더 밖": {ks.ENV_KEYSTORE: ks.TEST_STORE_VALUE, ks.ENV_KEYSTORE_DIR: str(make_fake_dir(other_root))},
                "이름 틀림": {ks.ENV_KEYSTORE: ks.TEST_STORE_VALUE, ks.ENV_KEYSTORE_DIR: str(make_fake_dir(self.root, "wrong-"))},
                "표시 파일 없음": {ks.ENV_KEYSTORE: ks.TEST_STORE_VALUE, ks.ENV_KEYSTORE_DIR: str(make_fake_dir(self.root, marker=False))},
            }
            for name, env in bad_envs.items():
                with self.subTest(case=name):
                    with self.assertRaises(AppError) as caught:
                        ks.default_keystore(env, windows=True, api=FakeApi(), temp_root=self.root)
                    self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")

    def test_an_installed_build_ignores_the_variable_completely(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            store = ks.default_keystore(self.test_env, windows=False, api=FakeApi(), temp_root=self.root)
            self.assertIsInstance(store, ks.WindowsCredentialStore)
            self.assertFalse(store.is_fake)
            with self.assertRaises(AppError) as caught:
                ks.default_keystore(self.test_env, windows=False, temp_root=self.root)
            self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
            self.assertEqual(caught.exception.detail, "Windows 가 아닌 환경이라 자격 증명 관리자를 쓸 수 없다", "설치본은 환경 변수가 있어도 가짜 보관소를 열지 않는다")

    def test_with_no_environment_given_the_process_environment_is_read(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(ks.ENV_KEYSTORE, None)
            os.environ.pop(ks.ENV_KEYSTORE_DIR, None)
            with self.assertRaises(AppError):
                ks.default_keystore(windows=False)
            self.assertIsInstance(ks.default_keystore(windows=False, api=FakeApi()), ks.WindowsCredentialStore)
            os.environ[ks.ENV_KEYSTORE] = ks.TEST_STORE_VALUE
            os.environ[ks.ENV_KEYSTORE_DIR] = str(self.good)
            self.assertIsInstance(ks.default_keystore(windows=False, api=FakeApi(), temp_root=self.root), ks.FileFakeStore)


class SourceGuardTest(unittest.TestCase):
    SRC = ROOT / "src" / "chanceblog_desktop"
    KEYSTORE = SRC / "security" / "keystore.py"

    def test_the_test_only_store_and_its_switch_appear_in_no_other_source_file(self):
        offenders = []
        for path in sorted(self.SRC.rglob("*.py")):
            if path == self.KEYSTORE:
                continue
            text = path.read_text(encoding="utf-8")
            for needle in (ks.TEST_STORE_VALUE, "FileFakeStore"):
                if needle in text:
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}: {needle}")
        self.assertEqual(offenders, [])
        self.assertGreaterEqual(len(list(self.SRC.rglob("*.py"))), 20, "원본 파일을 찾지 못했다 — 이 시험의 찾기 규칙이 깨졌다")

    def test_the_fake_store_is_only_ever_built_inside_default_keystore(self):
        tree = ast.parse(self.KEYSTORE.read_text(encoding="utf-8"))
        total = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "FileFakeStore"]
        inside = set()
        for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "FileFakeStore":
                    inside.add(function.name)
        self.assertEqual(len(total), 1)
        self.assertEqual(inside, {"default_keystore"})

    def test_no_silent_exception_swallowing_in_the_source(self):
        tree = ast.parse(self.KEYSTORE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                with self.subTest(line=node.lineno):
                    self.assertIsNotNone(node.type, "맨 except: 금지")
                    self.assertFalse(all(isinstance(item, ast.Pass) for item in node.body), "본문이 pass 뿐인 except 금지")

    def test_the_source_never_writes_a_secret_to_a_file_or_the_environment(self):
        text = self.KEYSTORE.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("putenv", "setdefault") and ast.unparse(node.value).endswith("environ"):
                self.fail("환경 변수에 쓰는 코드가 있다")
        writes = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in ("write_text", "write_bytes")]
        functions = {}
        for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
            for node in ast.walk(function):
                if isinstance(node, ast.Attribute) and node.attr in ("write_text", "write_bytes"):
                    functions[node.lineno] = function.name
        self.assertEqual(sorted(set(functions.values())), ["_save"], "파일에 쓰는 곳은 시험 전용 가짜 보관소의 `_save` 하나뿐이다")
        self.assertEqual(len(writes), len(functions))


class CatalogTest(unittest.TestCase):
    def test_the_codes_this_module_raises_have_guidance_in_the_error_table(self):
        for code in ("KEY_STORE_UNAVAILABLE", "KEY_TOO_LONG", "KEY_INVALID_SHAPE"):
            with self.subTest(code=code):
                self.assertIn(code, CATALOG, "오류 안내 표에 이 코드의 행이 없다 — 행을 더하고 sync_errors 를 돌린다(조용히 건너뛰지 않는다)")
                info = CATALOG[code]
                self.assertTrue(info.message and info.action)
                self.assertEqual(AppError(code).code, code, "표에 없는 코드는 UNEXPECTED_ERROR 로 바뀐다")


# ---- 진짜 자격 증명 관리자(기본 건너뜀) -----------------------------------------------------------------------------------------------------
@unittest.skipUnless(os.environ.get("CHANCEBLOG_TEST_REAL_CREDSTORE") == "1", "진짜 자격 증명 관리자 시험은 CHANCEBLOG_TEST_REAL_CREDSTORE=1 일 때만 돈다")
@unittest.skipUnless(os.name == "nt", "진짜 자격 증명 관리자는 Windows 에만 있다")
class RealCredentialStoreTest(unittest.TestCase):
    """이 PC 의 진짜 Windows 자격 증명 관리자에 **가짜 값**을 쓰고 읽고 지운다. 고유한 `__test__` 항목만 만들고 `finally` 로 반드시 지우며, 끝에 `__test__:` 항목이 하나도 없음을 확인한다."""

    def test_a_unique_fake_item_round_trips_and_nothing_is_left_behind(self):
        store = ks.WindowsCredentialStore()
        ref = "__test__:" + uuid.uuid4().hex
        longest = {"k": "가" * 1272}
        try:
            self.assertFalse(store.exists(ref))
            store.put(ref, FIELDS)
            self.assertTrue(store.exists(ref))
            self.assertIn(ref, store.list_refs("__test__:"))
            self.assertEqual(store.get(ref).to_dict(), FIELDS)
            store.put(ref, {"client_id": "FAKE-덮어쓴-값-" + uuid.uuid4().hex})
            self.assertEqual(sorted(store.get(ref).names()), ["client_id"])
            store.put(ref, longest)
            self.assertEqual(store.get(ref).to_dict(), longest, "2,560바이트(UTF-16 1,280글자) 값이 진짜 보관소에서도 그대로 돌아온다")
            with self.assertRaises(AppError) as caught:
                store.put(ref, {"k": "가" * 1273})
            self.assertEqual(caught.exception.requested_code, "KEY_TOO_LONG")
            self.assertEqual(store.get(ref).to_dict(), longest)
        finally:
            store.delete(ref)
        self.assertFalse(store.exists(ref))
        self.assertIsNone(store.get(ref))
        self.assertFalse(store.delete(ref), "이미 지운 항목을 또 지워도 오류가 아니다")
        self.assertEqual(store.list_refs("__test__:"), [], "삭제 뒤 남은 `__test__` 항목이 0 이어야 한다")


if __name__ == "__main__":
    unittest.main()
