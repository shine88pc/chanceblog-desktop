"""보관소 '있는지만 묻기' 가 자격 증명 값을 파이썬 bytes 로 꺼내지 않는 것을 지키는 시험 — AS-S1 권고-3·참고-7·참고-8(결정 D-610).

발견(감사 탐침 probe_exists): `KeyStore.exists()` 가 `_read` 를 불러 모든 비밀 칸이 든 묶음 전체를 `ctypes.string_at` 로 파이썬 bytes 로 복사했다 — 코드 안의 '값은 꺼내지 않는다'(`connections.py`·`ui/adapters.py`)와 어긋나고,
설정 화면을 열 때마다 항목 수만큼 되풀이됐다. 파이썬 bytes 는 앱이 지울 수 없고 가비지 수집 때까지 남는다.
지키는 것:
  1) `Win32CredApi.exists(target)` 는 `CredReadW` 가 OS 쪽에 만든 사본을 **읽지 않고** 바로 0 으로 덮은 뒤 `CredFree` 로 돌려준다 — `ctypes.string_at` 을 부르지 않는다(가짜 DLL 시험). 어떤 길로 끝나도(예외 포함) `CredFree` 는 한 번이다.
  2) `WindowsCredentialStore.exists` 는 그 길을 쓴다(값을 꺼내는 `read` 를 부르지 않는다). 오류 번호의 뜻은 예전과 같다: 없음은 거짓, 그 밖의 번호는 `KEY_STORE_UNAVAILABLE`(번호만).
  3) 참고-7: `decode_fields` 는 깊이 겹친 JSON 의 `RecursionError` 도 값 없는 `KEY_STORE_UNAVAILABLE` 로 바꾼다(3.10 은 파이썬 재귀 한도를 쓴다).
  4) 참고-8: `KEY_TOO_LONG` 세부에 묶음의 바이트 수가 들어가지 않는다(머리말의 '길이 같은 일부 정보도 만들지 않는다').
진짜 자격 증명 관리자는 부르지 않는다(가짜 DLL·가짜 API 만).
"""
import ctypes
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_security_keystore as tk  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import keystore as ks  # noqa: E402


def string_at_spy():
    """`ctypes.string_at` 을 부르면 시험이 실패하게 하는 감시(값을 파이썬 bytes 로 꺼내는 유일한 길)."""
    return mock.patch.object(ctypes, "string_at", side_effect=AssertionError("값을 파이썬 bytes 로 꺼냈다(ctypes.string_at)"))


class Win32ExistsTest(unittest.TestCase):
    def setUp(self):
        self.dll = tk.FakeDll()
        self.error = 0
        self.api = ks.Win32CredApi(self.dll, lambda: self.error)
        self.target = "ChanceBlogDesktop:" + tk.REF
        self.api.write(self.target, ks.encode_fields(tk.FIELDS))

    def test_a_stored_value_is_reported_without_ever_being_copied_wiped_in_the_os_copy_and_freed_once(self):
        with string_at_spy():
            self.assertEqual(self.api.exists(self.target), 0)
        self.assertEqual(len(self.dll.allocated), 1)
        self.assertTrue(self.dll.wiped(), "관리자가 돌려준 원본 메모리를 0 으로 덮어야 한다")
        self.assertEqual(self.dll.free_calls, [self.dll.read_address])

    def test_each_call_frees_exactly_once_and_repeated_calls_do_not_accumulate_copies(self):
        with string_at_spy():
            for count in (1, 2, 3):
                self.assertEqual(self.api.exists(self.target), 0)
                self.assertEqual(len(self.dll.free_calls), count)

    def test_a_missing_item_or_any_other_failure_returns_the_error_number_and_frees_nothing(self):
        with string_at_spy():
            for last, expected in ((tk.NOT_FOUND, tk.NOT_FOUND), (5, 5), (0, 1)):
                with self.subTest(last_error=last):
                    self.error = last
                    self.assertEqual(self.api.exists("ChanceBlogDesktop:naver_openapi:missing"), expected)
        self.assertEqual(self.dll.free_calls, [], "실패한 읽기에서는 돌려줄 메모리가 없다")

    def test_a_value_of_size_zero_and_a_success_without_a_pointer(self):
        with string_at_spy():
            self.dll.zero_size = True
            self.assertEqual(self.api.exists(self.target), 0)
            self.assertEqual(self.dll.free_calls, [self.dll.read_address])
            self.dll.zero_size = False
            self.dll.null_result = True
            self.dll.free_calls.clear()
            for last, expected in ((0, 1), (5, 5)):
                self.error = last
                self.assertEqual(self.api.exists(self.target), expected)
            self.assertEqual(self.dll.free_calls, [], "돌려받은 메모리가 없으니 돌려줄 것도 없다")

    def test_the_memory_is_still_given_back_when_wiping_it_raises(self):
        with mock.patch.object(ctypes, "memset", side_effect=RuntimeError("지우다 실패")):
            with self.assertRaises(RuntimeError):
                self.api.exists(self.target)
        self.assertEqual(self.dll.free_calls, [self.dll.read_address], "예외가 나도 CredFree 를 돌려준다")

    def test_the_control_read_still_copies_so_the_spy_really_sees_the_value_path(self):
        with mock.patch.object(ctypes, "string_at", wraps=ctypes.string_at) as spy:
            self.api.read(self.target)
        self.assertEqual(spy.call_count, 1)
        with mock.patch.object(ctypes, "string_at", wraps=ctypes.string_at) as spy:
            self.api.exists(self.target)
        self.assertEqual(spy.call_count, 0)


class StoreExistsTest(unittest.TestCase):
    def test_the_store_asks_the_exists_path_and_never_the_value_path(self):
        class OnlyExists:
            def __init__(self):
                self.asked, self.answer = [], 0

            def exists(self, target):
                self.asked.append(target)
                return self.answer

            def read(self, target):
                raise AssertionError("값을 꺼내는 read 를 불렀다")

        api = OnlyExists()
        store = ks.WindowsCredentialStore(api)
        self.assertIs(store.exists(tk.REF), True)
        self.assertEqual(api.asked, ["ChanceBlogDesktop:" + tk.REF])
        api.answer = tk.NOT_FOUND
        self.assertIs(store.exists(tk.REF), False)
        for number in (5, 1312, 1):
            with self.subTest(number=number):
                api.answer = number
                with self.assertRaises(AppError) as caught:
                    store.exists(tk.REF)
                self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
                self.assertEqual(caught.exception.detail, f"CredReadW 실패(오류 번호 {number})")

    def test_a_malformed_ref_is_refused_before_the_api_is_asked_even_on_the_exists_path(self):
        """AS2 시험 렌즈 Q 필수-3(D-619) — `exists` 의 `check_ref` 가 새 길의 유일한 입력 검사다(`_target` 은 모양을 보지 않는다). 지워도 초록이던 변이(Q21)를 죽인다: `exists` 가 있는 API 로 잘못된 번호를 주면
        API 에 묻기 **전에** ValueError 이고 값을 읽는 길은 한 번도 안 불린다. 올바른 번호는 그대로 API 에 묻는다."""
        class Counting:
            def __init__(self):
                self.asked = []

            def exists(self, target):
                self.asked.append(target)
                return 0

            def read(self, target):
                raise AssertionError("값을 꺼내는 read 를 불렀다")

        api = Counting()
        store = ks.WindowsCredentialStore(api)
        for ref in ("not a ref", "", " ", "naver_openapi:", ":" + "ab12" * 8, "naver_openapi:" + "x" * 500, "../x", "a" * 5000, None, 7, b"naver_openapi:ab12"):
            with self.subTest(ref=repr(ref)[:40]):
                with self.assertRaises(ValueError):
                    store.exists(ref)
        self.assertEqual(api.asked, [], "잘못된 번호인데 API 에 물었다")
        self.assertIs(store.exists(tk.REF), True)
        self.assertEqual(api.asked, ["ChanceBlogDesktop:" + tk.REF])

    def test_the_whole_store_on_the_fake_dll_never_copies_a_value_when_only_asked_whether_it_exists(self):
        dll = tk.FakeDll()
        error = [0]
        store = ks.WindowsCredentialStore(ks.Win32CredApi(dll, lambda: error[0]))
        store.put(tk.REF, tk.FIELDS)
        with string_at_spy():
            self.assertTrue(store.exists(tk.REF))
            error[0] = tk.NOT_FOUND
            self.assertFalse(store.exists("naver_openapi:" + "cd34" * 8))
        error[0] = 0
        self.assertEqual(store.get(tk.REF).to_dict(), tk.FIELDS, "값을 꺼내는 길은 그대로 동작한다")

    def test_a_test_double_api_without_exists_still_works_through_the_older_path(self):
        api = tk.FakeApi()
        store = ks.WindowsCredentialStore(api)
        store.put(tk.REF, tk.FIELDS)
        self.assertTrue(store.exists(tk.REF))
        self.assertFalse(store.exists("naver_openapi:" + "ef56" * 8))
        self.assertEqual([call[0] for call in api.calls if call[0] == "read"], ["read", "read"])

    def test_the_memory_store_and_the_ref_check_are_unchanged(self):
        memory = ks.MemoryStore()
        memory.put(tk.REF, tk.FIELDS)
        self.assertTrue(memory.exists(tk.REF))
        self.assertFalse(memory.exists("naver_openapi:" + "ab12" * 7 + "ab13"))
        with self.assertRaises(ValueError):
            ks.WindowsCredentialStore(tk.FakeApi()).exists("not a ref")


class DecodeAndLengthTest(unittest.TestCase):
    def test_a_recursion_error_while_reading_the_bundle_is_a_plain_unavailable_error_without_the_text(self):
        raw = ks.encode_fields({"k": tk.MARKER})
        with mock.patch.object(ks.json, "loads", side_effect=RecursionError("maximum recursion depth exceeded " + tk.MARKER)):
            with self.assertRaises(AppError) as caught:
                ks.decode_fields(raw)
        error = caught.exception
        self.assertEqual(error.code, "KEY_STORE_UNAVAILABLE")
        self.assertEqual(error.detail, "보관된 값을 해석하지 못했다(RecursionError)")
        for text in tk.surfaces(error):
            self.assertNotIn(tk.MARKER, text)

    def test_a_deeply_nested_bundle_of_the_largest_allowed_size_ends_as_an_app_error_on_every_python(self):
        for depth in (500, 900, 1100, 1270):
            with self.subTest(depth=depth):
                raw = ("[" * depth).encode("utf-16-le")
                with self.assertRaises(AppError) as caught:
                    ks.decode_fields(raw)
                self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")

    def test_the_too_long_detail_names_no_number_so_the_size_of_the_input_is_not_revealed(self):
        value = (tk.MARKER * 200)[:1273]
        with self.assertRaises(AppError) as caught:
            ks.encode_fields({"k": value})
        error = caught.exception
        self.assertEqual(error.slots, {"허용 용량": "2,560바이트"}, "한도는 알려도 된다 — 입력의 크기는 아니다")
        self.assertEqual(error.detail, "묶음이 한도를 넘었다")
        self.assertNotRegex(error.detail, r"[0-9]")
        for text in tk.surfaces(error):
            self.assertNotIn("2,562", text)
            self.assertNotIn(tk.MARKER, text)
        longer = (tk.MARKER * 400)[:1500]
        with self.assertRaises(AppError) as again:
            ks.encode_fields({"k": longer})
        self.assertEqual(again.exception.detail, error.detail, "길이가 달라도 같은 세부다")


if __name__ == "__main__":
    unittest.main()
