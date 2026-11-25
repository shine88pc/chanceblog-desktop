"""후보 산출물 키 모양 훑기(`scripts/release_check.py` 의 `scan_folder`·`scan_stream`, D-672) 시험.

지키는 것:
  1) 새 규칙 없음: 키 모양 판정은 `security/scan.py` 의 `scan_secrets` 를 그대로 부른다(부르는 것을 시험이 지켜 본다). 여섯 유형이 모두 잡힌다.
  2) 빠짐없이: 하위 폴더·숨은 파일·확장자 없는 파일·대문자 확장자·이진 파일·UTF-8 BOM·UTF-16·UTF-32 표지 파일·여러 덩어리로 나뉜 큰 파일·zip 안의 파일·이름에 든 키 모양까지 잡는다.
  3) 덩어리 경계: 키가 덩어리 경계에 걸쳐도 정확히 한 번 센다(경계를 훑는 모든 자리와 끝이 한계 자리와 정확히 같아지는 모든 경우를 쓸고, 고정 시드 차분 시험으로 통째 훑기와 견준다). 줄 번호는 파일 맨 앞부터 센 값이고
     CR·LF·CRLF 가 덩어리 사이에서 갈려도 맞다. 길이 상한이 없는 긴 토큰(JWT·Bearer 값·access_token 값)은 기본 크기(덩어리 1MiB·겹침 65,536)에서도 경계의 여러 자리에 걸쳐 정확히 한 번 센다 — 놓치지 않는 길이는 겹침의 절반(32,768 글자)까지다(D-672 ②).
  4) 조용히 건너뛰지 않는다: 링크·다른 압축 형식·너무 큰 파일·읽기 실패·깨진 zip(압축 본문이 중간에서 깨진 큰 멤버·읽다 줄어든 파일 포함)·암호 걸린 zip·중첩 zip·압축 한도 초과는 모두 '읽지 못함' 으로 이유와 함께 센다.
     못 보는데 읽은 파일로 세는 것(표지 없는 UTF-16·UTF-32·읽지 못함 목록 밖 압축)은 한계로 이름을 적고 시험이 그 모양을 못박는다(D-672 ⑦).
  5) 안전: 결과·표·JSON 어디에도 키 글자와 이 PC 의 경로가 없다(카나리). 키 모양 파일 이름은 발견 목록과 읽지 못함 목록(이유 열 가지마다)에서 가려서 보인다. 폴더 안 파일은 한 바이트도 바뀌지 않는다.
키 모양은 `scan_samples` 가 실행할 때 조각을 이어 붙여 만든다. 네트워크·실제 비밀 없이 돈다.
"""
import codecs
import io
import os
import random
import re
import stat
import sys
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import release_check_support as rs
import scan_samples as S
import secret_support
from release_check_support import rc

from chanceblog_desktop.security import scan

SAMPLES = {"google_api_key": S.google(), "github_token": S.github(), "aws_access_key": S.aws(), "pem_private_key": S.pem(), "oauth_token": S.ya29(), "bearer_token": S.bearer()}
KEY = S.github()                                 # 가장 단순한 표본 — 40자 안팎, 앞뒤가 영문·숫자가 아니면 한 건


class FolderCase(unittest.TestCase):
    def setUp(self):
        self._temp = rs.temp_dir()
        self.root = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def put(self, files):
        rs.write_files(self.root, files)

    def scan(self, **kwargs):
        return rc.scan_folder(self.root, **kwargs)

    def lines_of(self, result):
        return sorted((item.path, item.line) for item in result.findings)


class BasicsTest(FolderCase):
    def test_a_clean_folder_counts_every_file_and_byte_and_finds_nothing(self):
        files = {"a.txt": "문제 없는 글\n", "sub/b.log": "다른 글\n", "sub/deep/c": "확장자 없음\n", "빈 파일.txt": ""}
        self.put(files)
        result = self.scan()
        self.assertEqual((result.files_read, result.bytes_read), (4, sum(len(text.encode("utf-8")) for text in files.values())))
        self.assertEqual((result.findings, result.unread, result.openable, result.archives_opened), ([], [], True, 0))

    def test_all_six_kinds_are_found_with_the_scanner_labels_and_the_right_line(self):
        for kind, sample in SAMPLES.items():
            with self.subTest(kind=kind):
                with rs.temp_dir() as folder:
                    rs.write_files(folder, {"note.txt": f"첫 줄\n둘째 줄\n앞 {sample} 뒤\n끝\n"})
                    result = rc.scan_folder(folder)
                self.assertEqual([(item.path, item.label, item.line) for item in result.findings], [("note.txt", scan.KIND_LABELS[kind], 3)])
                self.assertEqual(result.files_read, 1)

    def test_every_hiding_place_is_searched(self):
        places = {"top.txt": "a", ".hidden": "b", ".cache/inner.txt": "c", "no_ext": "d", "UPPER.LOG": "e", "dir.with.dots/x.y.z": "f", "한글 폴더/한글 파일.txt": "g", "a/b/c/d/e/f/g/h.json": "h"}
        self.put({rel: f"{value}\n{KEY}\n" for rel, value in places.items()})
        result = self.scan()
        self.assertEqual(self.lines_of(result), sorted((rel, 2) for rel in places))

    def test_a_key_inside_a_binary_file_is_found(self):
        self.put({"data.bin": b"\x00\x01\x02\xff\xfe" + KEY.encode("ascii") + b"\x00\x00\xff", "x.db": b"SQLite format 3\x00" + b"\x00" * 40 + KEY.encode("ascii")})
        result = self.scan()
        self.assertEqual(sorted(item.path for item in result.findings), ["data.bin", "x.db"])

    def test_a_key_inside_a_compiled_module_file_is_found_like_in_any_other_binary(self):
        import marshal
        pyc = b"\x00" * 16 + marshal.dumps(compile(f'TOKEN = "{KEY}"\n', "mod.py", "exec"))                    # 묶음의 .pyc 와 같은 모양 — 글자 상수가 바이트 그대로 들어 있다
        self.put({"lib/mod.pyc": pyc, "lib/clean.pyc": b"\x00" * 16 + marshal.dumps(compile("X = 1\n", "clean.py", "exec"))})
        result = self.scan()
        self.assertEqual([(item.path, item.label) for item in result.findings], [("lib/mod.pyc", "GitHub 토큰")])
        self.assertEqual((result.files_read, result.unread), (2, []))

    def test_utf16_files_with_a_bom_are_read_as_utf16(self):
        text = f"앞 줄\n{KEY}\n끝\n"
        self.put({"le.txt": text.encode("utf-16"), "be.txt": codecs.BOM_UTF16_BE + text.encode("utf-16-be")})
        result = self.scan()
        self.assertEqual(self.lines_of(result), [("be.txt", 2), ("le.txt", 2)])

    def test_utf32_files_with_a_bom_are_read_as_utf32_not_as_utf16(self):
        """독립 검증 S 권고-1: UTF-32 LE 표지(FF FE 00 00)는 UTF-16 LE 표지(FF FE)와 앞 두 바이트가 같아 UTF-16 으로 잘못 읽혔다 — 글자 사이에 널이 끼어 키를 놓쳤다."""
        text = f"앞 줄\n{KEY}\n끝\n"
        self.put({"le.txt": codecs.BOM_UTF32_LE + text.encode("utf-32-le"), "be.txt": codecs.BOM_UTF32_BE + text.encode("utf-32-be")})
        self.assertEqual(self.lines_of(self.scan()), [("be.txt", 2), ("le.txt", 2)])

    def test_known_limits_files_the_scan_cannot_see_into_are_still_counted_as_read(self):
        """D-672 ⑦ 가 이름으로 적은 한계를 시험이 못박는다 — 표지 없는 UTF-16·UTF-32 는 키가 글자 사이 널에 가려 못 보고, 표지가 읽지 못함 목록 밖인 압축(zstd·lz4·OLE·zlib)은 읽지 못함이 아니라 읽은 파일로 센다
        (일부러: 실제 설치 묶음에서 10번이 영원히 PASS 가 못 되므로). 평문으로 든 키는 그런 표지 뒤에서도 보인다. 이 시험이 바뀌면 D-672 ⑦ 도 같이 고친다."""
        text = f"앞 줄\n{KEY}\n끝\n"
        markers = {"zstd": b"\x28\xb5\x2f\xfd", "lz4": b"\x04\x22\x4d\x18", "ole": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "zlib": b"\x78\x9c"}
        files = {"utf16_no_bom.txt": text.encode("utf-16-le"), "utf32_no_bom.txt": text.encode("utf-32-le")}
        files.update({f"{name}.bin": head + b"\x00" * 16 + f"평문 {KEY} 평문".encode("utf-8") for name, head in markers.items()})
        self.put(files)
        result = self.scan()
        self.assertEqual(sorted(item.path for item in result.findings), ["lz4.bin", "ole.bin", "zlib.bin", "zstd.bin"])      # 표지 뒤 평문 키만 보인다
        self.assertEqual((result.files_read, result.unread), (6, []))                                                          # 못 보는 둘도 읽은 파일로 센다

    def test_a_utf8_bom_does_not_shift_the_line_or_hide_the_key(self):
        self.put({"bom.txt": codecs.BOM_UTF8 + f"{KEY}\n둘째\n".encode("utf-8"), "bom2.txt": codecs.BOM_UTF8 + f"첫째\n{KEY}\n".encode("utf-8")})
        self.assertEqual(self.lines_of(self.scan()), [("bom.txt", 1), ("bom2.txt", 2)])

    def test_lines_are_counted_for_lf_crlf_and_cr_alike(self):
        self.put({"lf.txt": f"a\nb\nc\n{KEY}\n", "crlf.txt": f"a\r\nb\r\nc\r\n{KEY}\r\n", "cr.txt": f"a\rb\rc\r{KEY}\r", "mixed.txt": f"a\r\nb\rc\n{KEY}"})
        self.assertEqual(self.lines_of(self.scan()), [("cr.txt", 4), ("crlf.txt", 4), ("lf.txt", 4), ("mixed.txt", 4)])

    def test_several_keys_in_one_file_are_each_counted(self):
        self.put({"many.txt": f"{S.github()}\n중간\n{S.google()}\n{S.aws()}\n"})
        result = self.scan()
        self.assertEqual([(item.label, item.line) for item in result.findings], [("GitHub 토큰", 1), ("Google API 키", 3), ("AWS 액세스 키", 4)])

    def test_the_same_folder_scanned_twice_gives_the_same_result(self):
        self.put({"a.txt": f"{KEY}\n", "b/c.txt": "글\n", "z.zip": b"PK\x03\x04garbage"})
        self.assertEqual(self.scan(), self.scan())

    def test_the_result_order_does_not_depend_on_the_order_the_file_system_lists_entries(self):
        """독립 검증 Q P1(#40): 폴더 항목을 이름 순으로 세므로 파일 시스템이 어떤 순서로 알려 줘도 결과 순서가 같다."""
        self.put({"b.txt": f"{KEY}\n", "a.txt": f"{KEY}\n", "c/z.txt": f"{KEY}\n", "c/y.txt": f"{KEY}\n"})
        real = os.scandir

        class Backwards:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return reversed(list(self.handle.__enter__()))

            def __exit__(self, *args):
                return self.handle.__exit__(*args)
        with mock.patch("os.scandir", lambda path: Backwards(real(path))):
            result = self.scan()
        self.assertEqual([item.path for item in result.findings], ["a.txt", "b.txt", "c/y.txt", "c/z.txt"])

    def test_a_zero_byte_file_is_a_file_that_was_read(self):
        self.put({"empty": ""})
        result = self.scan()
        self.assertEqual((result.files_read, result.bytes_read, result.unread), (1, 0, []))

    def test_an_empty_folder_reads_zero_files_and_a_missing_folder_or_a_file_is_not_openable(self):
        self.assertEqual((self.scan().files_read, self.scan().openable), (0, True))
        self.assertFalse(rc.scan_folder(self.root / "없는 폴더").openable)
        self.put({"file.txt": "글\n"})
        self.assertFalse(rc.scan_folder(self.root / "file.txt").openable)
        self.assertEqual(rc.scan_folder(self.root / "없는 폴더").unread, [])

    def test_paths_in_the_result_are_relative_with_forward_slashes(self):
        self.put({"a/b/c.txt": f"{KEY}\n"})
        paths = [item.path for item in self.scan().findings]
        self.assertEqual(paths, ["a/b/c.txt"])
        self.assertNotIn(str(self.root), paths[0])

    def test_a_relative_folder_argument_works_too(self):
        self.put({"a.txt": f"{KEY}\n"})
        previous = os.getcwd()
        os.chdir(self.root.parent)
        try:
            result = rc.scan_folder(self.root.name)
        finally:
            os.chdir(previous)
        self.assertEqual([(item.path, item.line) for item in result.findings], [("a.txt", 1)])

    def test_the_default_dataclass_lists_are_not_shared_between_results(self):
        first, second = rc.FolderScan("a"), rc.FolderScan("b")
        first.findings.append(rc.Finding("x", "y", 1))
        first.unread.append(rc.Unread("x", "link"))
        self.assertEqual((second.findings, second.unread), ([], []))

    def test_a_file_named_like_an_archive_but_holding_text_is_read_as_text(self):
        self.put({"fake.zip": f"이름만 zip\n{KEY}\n", "fake.gz": f"이름만 gz\n{KEY}\n"})
        result = self.scan()
        self.assertEqual(self.lines_of(result), [("fake.gz", 2), ("fake.zip", 2)])
        self.assertEqual((result.unread, result.archives_opened), ([], 0))


class ScannerReuseTest(FolderCase):
    def test_the_key_judgement_is_the_existing_scanner_called_on_the_file_text(self):
        calls = []
        real = scan.scan_secrets

        def spy(text, where=""):
            calls.append(text)
            return real(text, where)
        self.put({"a.txt": f"앞\n{KEY}\n", "b.txt": "문제 없는 글\n"})
        with mock.patch.object(scan, "scan_secrets", spy):
            result = self.scan()
        self.assertTrue(any(KEY in text for text in calls), "파일 내용을 scan_secrets 에 건네야 한다")
        self.assertTrue(all(isinstance(text, str) for text in calls))
        self.assertEqual([(item.path, item.line) for item in result.findings], [("a.txt", 2)])

    def test_the_result_is_the_scanners_result_not_a_second_opinion(self):
        text = f"{S.google()}\n{S.pem()}\n{S.bearer()}\n"
        self.put({"a.txt": text})
        direct = sorted((hit.line, scan.KIND_LABELS[hit.kind]) for hit in scan.scan_secrets(text))
        self.assertEqual(sorted((item.line, item.label) for item in self.scan().findings), direct)

    def test_a_scanner_that_finds_nothing_means_nothing_is_reported(self):
        self.put({"a.txt": f"{KEY}\n"})
        with mock.patch.object(scan, "scan_secrets", lambda text, where="": ()):
            self.assertEqual(self.scan().findings, [])

    def test_the_script_defines_no_key_pattern_of_its_own(self):
        import ast
        tree = ast.parse((rs.ROOT / "scripts" / "release_check.py").read_text(encoding="utf-8"))
        compiled = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "compile"]
        for node in compiled:
            for argument in node.args[:1]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    self.assertNotRegex(argument.value, r"[A-Za-z]{3,}[_-]", f"{node.lineno}행: 키 접두사 모양 정규식을 새로 만들지 않는다")


class ChunkBoundaryTest(unittest.TestCase):
    def run_stream(self, data, chunk, overlap=128, limit=None):
        return rc.scan_stream(io.BytesIO(data), scan, chunk_bytes=chunk, overlap_chars=overlap, limit_bytes=limit)

    def test_a_key_is_counted_exactly_once_wherever_the_chunk_boundary_falls(self):
        problems = []
        for kind, sample in SAMPLES.items():
            for chunk in (13, 64):
                for offset in range(0, 100):
                    data = ("x" * offset + "\n" + sample + "\n끝").encode("utf-8") if offset % 2 else ("x" * offset + " " + sample + " 끝").encode("utf-8")
                    hits, size = self.run_stream(data, chunk)
                    expected = [(kind, 2 if offset % 2 else 1)]
                    if hits != expected or size != len(data):
                        problems.append((kind, chunk, offset, hits))
        self.assertEqual(problems[:3], [], f"틀린 자리 {len(problems)}곳")

    def test_line_numbers_across_many_chunks_match_a_direct_scan(self):
        lines = [f"줄 {number}" for number in range(1, 301)]
        for position in (1, 77, 150, 299, 300):
            lines[position - 1] = f"앞 {KEY} 뒤"
        data = ("\n".join(lines) + "\n").encode("utf-8")
        direct = [hit.line for hit in scan.scan_secrets(data.decode("utf-8"))]
        for chunk in (13, 100, 1000):
            with self.subTest(chunk=chunk):
                hits, _ = self.run_stream(data, chunk, overlap=256)
                self.assertEqual([line for _, line in hits], direct)
                self.assertEqual(direct, [1, 77, 150, 299, 300])

    def test_a_carriage_return_and_line_feed_split_between_chunks_is_still_one_line_break(self):
        text = "".join(f"줄{number}\r\n" for number in range(60)) + KEY + "\r\n"
        data = text.encode("utf-8")
        for chunk in range(5, 45):
            with self.subTest(chunk=chunk):
                hits, _ = self.run_stream(data, chunk, overlap=64)
                self.assertEqual([line for _, line in hits], [61])

    def test_lines_separated_only_by_carriage_returns_are_counted_across_chunks(self):
        data = ("".join(f"줄{number}\r" for number in range(60)) + KEY + "\r").encode("utf-8")
        for chunk in range(5, 45):
            with self.subTest(chunk=chunk):
                hits, _ = self.run_stream(data, chunk, overlap=64)
                self.assertEqual([line for _, line in hits], [61])

    def test_a_multibyte_character_split_between_chunks_is_decoded_correctly(self):
        data = ("가나다라마바사" * 10 + "\n" + KEY + "\n").encode("utf-8")
        for chunk in (1, 2, 4, 5, 7):
            with self.subTest(chunk=chunk):
                hits, size = self.run_stream(data, chunk, overlap=256)
                self.assertEqual(([line for _, line in hits], size), ([2], len(data)))

    def test_a_utf16_stream_in_tiny_chunks_is_decoded_correctly(self):
        data = (f"앞 줄\n{KEY}\n끝\n").encode("utf-16")
        for chunk in (1, 2, 3, 5):
            with self.subTest(chunk=chunk):
                hits, _ = self.run_stream(data, chunk, overlap=256)
                self.assertEqual([line for _, line in hits], [2])

    def test_a_utf32_stream_in_tiny_chunks_is_decoded_correctly(self):
        data = (f"앞 줄\n{KEY}\n끝\n").encode("utf-32")
        for chunk in (1, 2, 3, 4, 5, 7):
            with self.subTest(chunk=chunk):
                hits, size = self.run_stream(data, chunk, overlap=256)
                self.assertEqual(([line for _, line in hits], size), ([2], len(data)))

    def test_a_key_in_the_last_chunk_of_a_big_file_is_found_and_none_are_invented(self):
        data = (("무의미한 글 한 줄 " * 5 + "\n") * 400 + KEY + "\n").encode("utf-8")
        hits, size = self.run_stream(data, 997, overlap=512)
        self.assertEqual(([line for _, line in hits], size), ([401], len(data)))
        clean, _ = self.run_stream((("무의미한 글 한 줄 " * 5 + "\n") * 400).encode("utf-8"), 997, overlap=512)
        self.assertEqual(clean, [])

    def test_keys_inside_the_overlap_region_are_not_counted_again(self):
        data = (f"{KEY}\n" + "무의미 " * 20).encode("utf-8")
        hits, _ = self.run_stream(data, 60, overlap=400)
        self.assertEqual([line for _, line in hits], [1])

    def test_two_different_keys_close_together_are_both_counted_across_a_boundary(self):
        data = f"{S.github()} {S.google()}\n".encode("utf-8")
        for chunk in range(3, 60):
            with self.subTest(chunk=chunk):
                hits, _ = self.run_stream(data, chunk, overlap=256)
                self.assertEqual(sorted(kind for kind, _ in hits), ["github_token", "google_api_key"])

    def test_a_key_is_counted_once_whenever_its_end_meets_the_deferral_limit_or_the_counted_mark_exactly(self):
        """독립 검증 Q R4: 키의 끝이 '미룬 구간의 경계' 나 '이미 센 자리' 와 정확히 같아지는 모든 자리를 작은 덩어리로 쓴다 — 키 뒤에 덩어리·미룬 구간보다 긴 글을 두어 끝 덩어리가 아닌 덩어리에서 센다
        (`<` 가 `<=` 로 바뀌면 같은 키가 두 번 세어지고, 끝이 미룬 경계와 같은 키는 `<=` 가 `<` 로 바뀌면 한 번도 안 세어진다)."""
        problems = []
        for kind, sample in SAMPLES.items():
            for chunk, overlap in ((2, 128), (3, 128), (5, 128), (13, 128), (7, 130), (5, 392)):
                for base in (0, 450):                                              # 앞쪽(꼬리가 아직 짧다)과 한참 뒤(꼬리가 가득 찼다)
                    for offset in range(chunk):                                    # 덩어리 한 주기 — 끝 자리가 경계와 겹치는 자리가 반드시 있다
                        data = (" " * (base + offset) + sample + " " + "x " * 150).encode("utf-8")
                        hits, size = self.run_stream(data, chunk, overlap)
                        if hits != [(kind, 1)] or size != len(data):
                            problems.append((kind, chunk, overlap, base + offset, hits))
        self.assertEqual(problems[:3], [], f"틀린 자리 {len(problems)}곳")

    def test_random_texts_scanned_in_small_chunks_give_exactly_the_whole_text_result(self):
        """고정 시드 차분 시험(독립 검증 Q R4): 무작위 글(여러 유형의 키·줄바꿈 LF·CR·CRLF 섞임·한글·UTF-8·UTF-16)을 작은 덩어리·겹침으로 훑은 결과(유형·줄)가 통째로 한 번 훑은 결과와 같다.
        키는 늘 구분자로 둘러싼다(이어 붙은 글자로 두 모양이 겹치면 통째 훑기에서는 한쪽이 다른 쪽에 가려지는데 창이 잘리면 가려진 쪽이 따로 보인다 — `scan_secrets` 자체의 성질이고 이 도구 쪽 문제가 아니다). 겹침의 절반(앞 낱말 포함)보다 긴 연속 글자가 든 글은 설계상 한계라 뺀다."""
        samples = (S.github(), S.google(), S.aws(), S.pem(), S.ya29(), S.bearer(), S.github_pat(), S.jwt(), S.refresh(), S.gocspx(), S.named())
        pieces = ("가나다라 ", "plain words ", " ", "\t", "ab ", "=", '"', "'", ".")
        newlines = ("\n", "\r\n", "\r")
        grid = ((2, 392), (5, 392), (5, 784), (13, 128), (64, 392), (97, 784), (3, 200), (7, 256))
        rng = random.Random(20261125)
        problems, ran = [], 0
        for case in range(300):
            newline = rng.choice(newlines)
            parts = []
            for _ in range(rng.randint(8, 30)):
                roll = rng.random()
                if roll < 0.3:
                    parts.append(" " + rng.choice(samples) + rng.choice((" ", "\t", newline)))
                elif roll < 0.55:
                    parts.append(newline)
                else:
                    parts.append(rng.choice(pieces) * rng.randint(1, 5))
            text = "".join(parts)
            chunk, overlap = grid[case % len(grid)]
            longest = max((len(found.group(0)) for found in re.finditer(r"[A-Za-z0-9._" + S.TILDE + r"+/=%-]+", text)), default=0)
            if longest + 24 > overlap // 2:
                continue
            data = text.encode(("utf-8", "utf-16", "utf-8")[case % 3])
            hits, size = self.run_stream(data, chunk, overlap)
            ran += 1
            if sorted(hits) != sorted((hit.kind, hit.line) for hit in scan.scan_secrets(text)) or size != len(data):
                problems.append((case, chunk, overlap))
        self.assertGreaterEqual(ran, 200, "빼는 글이 너무 많으면 이 시험이 아무것도 안 본 채 통과한다")
        self.assertEqual(problems[:3], [], f"통째 훑기와 다른 사례 {len(problems)}개")

    def test_empty_stream_and_the_size_limit(self):
        self.assertEqual(self.run_stream(b"", 10), ([], 0))
        with self.assertRaises(rc._TooBig):
            self.run_stream(b"x" * 100, 10, limit=50)
        self.assertEqual(self.run_stream(b"x" * 100, 10, limit=100)[1], 100)

    def test_the_default_sizes_are_what_the_docs_say(self):
        self.assertEqual((rc.CHUNK_BYTES, rc.OVERLAP_CHARS), (1 << 20, 65536))
        self.assertEqual(rc.SAFE_KEY_CHARS, 32768)                             # 겹침의 절반 — 이 길이까지는 경계 어디에 걸려도 놓치지 않는다(D-672 ②)
        self.assertEqual((rc.MAX_FILE_BYTES, rc.MAX_MEMBER_BYTES, rc.MAX_ARCHIVE_BYTES), (1 << 30, 256 << 20, 1 << 30))          # 파일 1GiB·zip 안 파일 256MB·zip 한 개 합계 1GiB(D-672 ③·④)
        self.assertEqual(rc.SAFE_KEY_CHARS, rc.OVERLAP_CHARS // 2)
        self.assertGreater(rc.OVERLAP_CHARS, 200)                              # 키·토큰 모양보다 길게 겹친다

    def test_a_token_as_long_as_half_the_overlap_is_found_once_at_every_boundary_position(self):
        overlap = 256                                                          # 겹침의 절반(128 글자)까지는 어디에 걸려도 놓치지 않는다(작은 크기로 모든 자리를 쓸어 본다)
        safe = overlap // 2
        rest = safe - 44
        tokens = (
            ("oauth_token", S.jwt(head=36, payload=rest // 2, signature=rest - rest // 2)),     # JWT 모양, 정확히 safe 글자
            ("oauth_token", S.ya29(length=safe - 5)),                                           # 접두사 포함 safe 글자
            ("bearer_token", S.bearer(length=safe - 7)),                                        # 'Bearer ' 낱말 포함 safe 글자
        )
        after = " " + "x " * 200                                                            # 토큰 뒤에 미룬 구간과 덩어리보다 긴 글을 둔다 — 끝 덩어리가 아닌 덩어리에서 센다
        problems = []
        for kind, token in tokens:
            self.assertEqual(len(token), safe)
            for chunk in (61, 128):
                for offset in range(chunk + overlap + 3):
                    data = (" " * offset + token + after).encode("utf-8")
                    hits, size = self.run_stream(data, chunk, overlap)
                    if hits != [(kind, 1)] or size != len(data):
                        problems.append((kind, chunk, offset, hits))
        self.assertEqual(problems[:3], [], f"틀린 자리 {len(problems)}곳")


class LongTokenBoundaryTest(unittest.TestCase):
    """기본 덩어리(1MiB)·기본 겹침으로, 길이 상한이 없는 모양(JWT·Bearer 값·access_token 값)이 덩어리 경계에 걸려도 정확히 한 번 센다(독립 검증 S 필수-1·Q R5).
    옛 겹침(4,096 글자)에서는 경계에 걸친 2,049 글자보다 긴 토큰을 조용히 놓쳐 10번이 거짓 PASS 가 될 수 있었다. 놓치지 않는 길이는 겹침의 절반(`SAFE_KEY_CHARS`)까지다."""

    BOUNDARY = rc.CHUNK_BYTES                     # 첫 덩어리가 끝나는 자리(ASCII 만 써서 바이트 = 글자)
    ROOM = 70000                                  # 경계 뒤에 남기는 글(둘째 덩어리 — 가장 긴 토큰의 나머지도 들어간다)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        line = b"2026-11-25 10:00:00 INFO worker finished the job without any problem\n"
        cls.filler = line * ((cls.BOUNDARY + cls.ROOM) // len(line) + 1)

    @staticmethod
    def jwt(total):
        """`total` 글자 JWT 모양(머리 36 글자, 나머지는 본문과 서명이 절반씩) — 길이 상한이 없는 OAuth 토큰 모양."""
        rest = total - 44
        return S.jwt(head=36, payload=rest // 2, signature=rest - rest // 2)

    def plant(self, token, start):
        """채움 글의 `start` 자리에서 시작하도록 `token` 을 심는다(앞뒤에 공백 하나) → (바이트, 토큰이 있는 줄 번호)."""
        raw = token.encode("ascii")
        data = bytearray(self.filler[:self.BOUNDARY + self.ROOM])
        data[start - 1:start + len(raw) + 1] = b" " + raw + b" "
        return bytes(data), data.count(b"\n", 0, start) + 1

    def check(self, token, start, kind):
        data, line = self.plant(token, start)
        hits, size = rc.scan_stream(io.BytesIO(data), scan)                    # 기본 덩어리·기본 겹침
        self.assertEqual((hits, size), ([(kind, line)], len(data)), f"토큰 {len(token)}글자·시작 자리 {start}")

    def test_the_planted_tokens_are_exactly_one_hit_each_for_the_scanner_on_its_own(self):
        for label, token, kind in (("JWT 9,000", self.jwt(9000), "oauth_token"), ("Bearer 6,000", S.bearer(6000), "bearer_token"),
                                   ("access_token 5,000", S.named("access_token", value=S.body(5000, S.B64URL, 8)), "oauth_token"),
                                   ("안전 길이 JWT", self.jwt(rc.SAFE_KEY_CHARS), "oauth_token")):
            with self.subTest(label=label):
                self.assertEqual([hit.kind for hit in scan.scan_secrets(token)], [kind])

    def test_a_nine_thousand_character_jwt_is_found_once_wherever_the_boundary_cuts_it(self):
        token = self.jwt(9000)
        for before in (20, 4500, 8990):                                        # 경계 앞에 놓이는 토큰 글자 수 — 머리 안·본문 끝 가까이·서명 거의 끝
            with self.subTest(before=before):
                self.check(token, self.BOUNDARY - before, "oauth_token")

    def test_a_six_thousand_character_bearer_value_is_found_once_wherever_the_boundary_cuts_it(self):
        token = S.bearer(6000)                                                 # 'Bearer ' 낱말 + 값 6,000 글자
        for before in (7, 3000, len(token)):                                   # 낱말 바로 뒤에서 잘림·값 한가운데·끝이 경계 바로 앞
            with self.subTest(before=before):
                self.check(token, self.BOUNDARY - before, "bearer_token")

    def test_a_long_access_token_value_is_found_once_when_the_boundary_cuts_it(self):
        token = S.named("access_token", value=S.body(5000, S.B64URL, 8))
        for before in (13, 2500, len(token)):                                  # '=' 바로 뒤에서 잘림·값 한가운데·끝이 경계 바로 앞
            with self.subTest(before=before):
                self.check(token, self.BOUNDARY - before, "oauth_token")

    def test_tokens_that_end_just_before_or_start_exactly_at_the_boundary_are_found_once(self):
        token = self.jwt(9000)
        for label, start in (("끝이 경계 바로 앞", self.BOUNDARY - len(token)), ("끝이 경계 한 글자 뒤", self.BOUNDARY - len(token) + 1),
                             ("끝이 경계 1,000 글자 앞(미룬 구간 안)", self.BOUNDARY - len(token) - 1000), ("시작이 경계 바로 앞 글자", self.BOUNDARY - 1),
                             ("시작이 경계 자리", self.BOUNDARY)):
            with self.subTest(label=label):
                self.check(token, start, "oauth_token")

    def test_a_token_ending_exactly_at_the_deferral_limit_or_one_either_side_is_found_once(self):
        token = self.jwt(9000)
        limit = self.BOUNDARY - rc.OVERLAP_CHARS // 2                          # 첫 덩어리에서 끝이 이 자리까지인 발견은 바로 센다(그 뒤는 다음 덩어리로 미룬다)
        for delta in (-1, 0, 1):
            with self.subTest(delta=delta):
                self.check(token, limit + delta - len(token), "oauth_token")

    def test_a_token_as_long_as_the_safe_length_is_found_once_even_in_the_tightest_spot(self):
        token = self.jwt(rc.SAFE_KEY_CHARS)
        limit = self.BOUNDARY - rc.OVERLAP_CHARS // 2
        for label, end in (("끝이 미룬 구간 바로 안쪽(가장 빠듯한 자리)", limit + 1), ("끝이 경계 바로 앞", self.BOUNDARY), ("끝이 경계 5,000 글자 뒤", self.BOUNDARY + 5000)):
            with self.subTest(label=label):
                self.check(token, end - len(token), "oauth_token")

    def test_the_folder_scan_finds_the_long_token_across_the_boundary_of_a_real_file(self):
        data, line = self.plant(self.jwt(9000), self.BOUNDARY - 4500)
        with rs.temp_dir() as folder:
            rs.write_files(folder, {"logs/big.log": data})
            result = rc.scan_folder(folder)
        self.assertEqual([(item.path, item.label, item.line) for item in result.findings], [("logs/big.log", "OAuth 토큰", line)])
        self.assertEqual((result.files_read, result.bytes_read, result.unread), (1, len(data), []))


class ZipTest(FolderCase):
    def make_zip(self, rel, members, compression=zipfile.ZIP_DEFLATED):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression) as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        return path

    def test_a_key_inside_a_deflated_member_is_found_with_a_path_through_the_zip(self):
        self.make_zip("pack.zip", {"inner/a.txt": f"앞\n{KEY}\n", "b.txt": "문제 없는 글\n", "dir/": ""})
        result = self.scan()
        self.assertEqual([(item.path, item.line) for item in result.findings], [("pack.zip!inner/a.txt", 2)])
        self.assertEqual((result.archives_opened, result.files_read, result.unread), (1, 2, []))
        self.assertEqual(result.bytes_read, len(f"앞\n{KEY}\n".encode("utf-8")) + len("문제 없는 글\n".encode("utf-8")))

    def test_a_compiled_module_inside_the_bundle_library_zip_is_searched(self):
        import marshal
        pyc = b"\x00" * 16 + marshal.dumps(compile(f'TOKEN = "{KEY}"\n', "mod.py", "exec"))
        self.make_zip("_internal/base_library.zip", {"os.pyc": pyc, "clean.pyc": b"\x00" * 16 + marshal.dumps(compile("X = 1\n", "clean.py", "exec"))})
        result = self.scan()
        self.assertEqual([(item.path, item.label) for item in result.findings], [("_internal/base_library.zip!os.pyc", "GitHub 토큰")])
        self.assertEqual((result.archives_opened, result.files_read, result.unread), (1, 2, []))

    def test_stored_members_and_zips_without_a_zip_suffix_are_read_too(self):
        self.make_zip("pack.bin", {"a.txt": f"{KEY}\n"}, compression=zipfile.ZIP_STORED)
        self.make_zip("lib/base_library", {"x.pyc": f"x {KEY}\n".encode("utf-8")})
        result = self.scan()
        self.assertEqual(sorted(item.path for item in result.findings), ["lib/base_library!x.pyc", "pack.bin!a.txt"])
        self.assertEqual(result.archives_opened, 2)

    def test_a_zip_inside_a_zip_a_gzip_member_and_an_encrypted_member_are_reported_unread_with_reasons(self):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as archive:
            archive.writestr("deep.txt", f"{KEY}\n")
        path = self.make_zip("pack.zip", {"nested.dat": inner.getvalue(), "g.dat": b"\x1f\x8b\x08\x00" + "압축 흉내".encode("utf-8"), "ok.txt": "글\n"})
        data = bytearray(path.read_bytes())
        # 마지막 중앙 디렉터리 항목이 아니라 첫 항목의 '암호 걸림' 비트만 켠다(항목 이름 nested.dat)
        index = data.index(b"PK\x01\x02")
        data[index + 8] |= 1
        path.write_bytes(bytes(data))
        result = self.scan()
        reasons = {item.path: item.reason for item in result.unread}
        self.assertEqual(reasons, {"pack.zip!nested.dat": "zip_encrypted", "pack.zip!g.dat": "other_archive"})
        self.assertEqual(result.findings, [])
        self.assertEqual(result.files_read, 1)

    def test_a_zip_member_that_is_a_zip_is_reported_as_nested(self):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as archive:
            archive.writestr("deep.txt", f"{KEY}\n")
        self.make_zip("pack.zip", {"nested.dat": inner.getvalue()})
        result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("pack.zip!nested.dat", "zip_nested")])
        self.assertEqual(result.findings, [])

    def test_a_broken_zip_is_one_unread_file_not_a_crash(self):
        self.put({"bad.zip": b"PK\x03\x04garbage garbage", "good.txt": f"{KEY}\n"})
        result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("bad.zip", "zip_broken")])
        self.assertEqual([(item.path, item.line) for item in result.findings], [("good.txt", 1)])

    def test_a_member_whose_checksum_fails_is_unread_and_the_rest_are_still_read(self):
        path = self.make_zip("pack.zip", {"a.txt": "hello world 123456 hello\n", "b.txt": f"{KEY}\n"}, compression=zipfile.ZIP_STORED)
        path.write_bytes(path.read_bytes().replace(b"hello world", b"hellO world"))
        result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("pack.zip!a.txt", "zip_broken")])
        self.assertEqual([item.path for item in result.findings], ["pack.zip!b.txt"])

    def make_zip_with_a_big_member(self, damage):
        """난수 300KB 를 deflate 로 묶은 큰 멤버(big.bin)와 깨끗한 작은 글 멤버(small.txt)가 든 pack.zip 을 만들고, big.bin 의 압축 본문을 `damage(바이트, 본문 시작, 압축 크기)` 로 망가뜨린다.
        앞쪽 4KB 는 멀쩡하다 — 훑기의 첫 확인(`peek`)은 지나가고 끝까지 읽는 중에 깨진다."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("big.bin", random.Random(5).randbytes(300000))
            archive.writestr("small.txt", f"앞\n{KEY}\n")
        blob = bytearray(buffer.getvalue())
        local = blob.index(b"PK\x03\x04")
        name_length = int.from_bytes(blob[local + 26:local + 28], "little")
        extra_length = int.from_bytes(blob[local + 28:local + 30], "little")
        start = local + 30 + name_length + extra_length
        size = int.from_bytes(blob[local + 18:local + 22], "little")                 # 압축된 크기
        self.assertGreater(size, 200000)
        damage(blob, start, size)
        (self.root / "pack.zip").write_bytes(bytes(blob))

    def test_a_big_member_whose_compressed_body_breaks_after_the_first_kilobytes_is_unread_and_the_rest_is_still_read(self):
        """독립 검증 Q R2: 압축 본문이 중간에서 깨진 큰 멤버(zlib 오류 또는 CRC 불일치)는 그 멤버 하나만 '읽지 못함' 이고 훑기는 예외로 끝나지 않는다."""
        def zeros(blob, start, size):
            blob[start + size // 2:start + size] = bytes(size - size // 2)            # 본문 절반 뒤를 0 으로 — 압축 줄기가 중간에서 끊긴다

        def flipped(blob, start, size):
            at = start + size * 6 // 10
            for index in range(at, at + 40):                                         # 본문 6/10 지점 40바이트를 뒤집는다
                blob[index] ^= 0xA5
        for label, damage in (("본문 절반 뒤를 0 으로", zeros), ("본문 6/10 지점 뒤집기", flipped)):
            with self.subTest(label=label):
                self.make_zip_with_a_big_member(damage)
                result = self.scan()
                self.assertEqual([(item.path, item.reason) for item in result.unread], [("pack.zip!big.bin", "zip_broken")])
                self.assertEqual([(item.path, item.line) for item in result.findings], [("pack.zip!small.txt", 2)])
                self.assertEqual(result.files_read, 1)

    def test_a_zip_that_ends_early_while_it_is_being_read_is_unread_not_a_crash(self):
        """독립 검증 Q R2(EOFError): 열린 뒤 줄어든 파일(로그가 돌려 쓰이거나 복사가 끊긴 경우) — 압축 본문을 읽다 파일 끝을 만나면 그 멤버 하나만 '읽지 못함' 이다."""
        class Shrinking(io.BytesIO):
            big_reads = 0

            def read(self, size=-1):
                if size is not None and size >= 4096:                                # 압축 본문을 읽는 큰 읽기는 첫 번째만 돌려주고 그 뒤로는 파일 끝을 돌려준다
                    Shrinking.big_reads += 1
                    if Shrinking.big_reads > 1:
                        return b""
                return super().read(size)
        self.make_zip_with_a_big_member(lambda blob, start, size: None)             # 멀쩡한 zip
        result = self.scan(opener=lambda path: Shrinking(Path(path).read_bytes()))
        self.assertGreaterEqual(Shrinking.big_reads, 2)
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("pack.zip!big.bin", "zip_broken")])
        self.assertEqual([(item.path, item.line) for item in result.findings], [("pack.zip!small.txt", 2)])
        self.assertEqual(result.files_read, 1)

    def test_the_member_and_total_size_limits_make_members_unread(self):
        self.make_zip("pack.zip", {"a.txt": "0123456789" * 3, "b.txt": "abcdefghij", "c.txt": "abcdefghij"})
        with mock.patch.object(rc, "MAX_MEMBER_BYTES", 20):
            result = self.scan()
        self.assertEqual(sorted((item.path, item.reason) for item in result.unread), [("pack.zip!a.txt", "zip_budget")])
        self.assertEqual(result.files_read, 2)
        with mock.patch.object(rc, "MAX_ARCHIVE_BYTES", 15):
            result = self.scan()
        self.assertEqual(sorted(item.path for item in result.unread), ["pack.zip!a.txt", "pack.zip!c.txt"])
        self.assertEqual(result.files_read, 1)

    def test_a_member_exactly_as_big_as_the_limit_is_read_and_one_byte_more_is_not(self):
        self.make_zip("pack.zip", {"a.txt": "x" * 20, "b.txt": "y" * 21})
        with mock.patch.object(rc, "MAX_MEMBER_BYTES", 20):
            result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("pack.zip!b.txt", "zip_budget")])
        self.assertEqual(result.files_read, 1)

    def test_a_member_that_grows_past_the_limit_while_reading_is_unread(self):
        self.make_zip("pack.zip", {"a.txt": "0123456789" * 30})
        real = rc.scan_stream

        def tight(stream, scan_module, **kwargs):
            kwargs["limit_bytes"] = 5
            return real(stream, scan_module, **kwargs)
        with mock.patch.object(rc, "scan_stream", tight):
            result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("pack.zip!a.txt", "too_big")])

    def test_key_shaped_names_of_a_zip_and_of_its_members_are_findings_and_hidden(self):
        name = f"{S.github()}.txt"
        self.make_zip("pack.zip", {name: "깨끗한 내용\n"})
        result = self.scan()
        self.assertEqual([(item.line, item.label) for item in result.findings], [(0, "GitHub 토큰")])
        self.assertIn("가림", result.findings[0].path)
        self.assertNotIn(S.github()[:12], result.findings[0].path)

    def test_zip_directory_entries_are_not_files(self):
        self.make_zip("pack.zip", {"folder/": "", "folder/x.txt": "글\n"})
        result = self.scan()
        self.assertEqual((result.files_read, result.unread), (1, []))

    def test_an_unsupported_compression_method_is_unread_not_a_crash(self):
        path = self.make_zip("pack.zip", {"a.txt": "글\n" * 5, "b.txt": f"{KEY}\n"})
        data = bytearray(path.read_bytes())
        index = data.index(b"PK\x01\x02")
        data[index + 10] = 99                                                  # 중앙 디렉터리의 압축 방식 번호를 모르는 값으로
        path.write_bytes(bytes(data))
        result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("pack.zip!a.txt", "zip_broken")])
        self.assertEqual([item.path for item in result.findings], ["pack.zip!b.txt"])


class UnreadTest(FolderCase):
    def test_other_archive_formats_are_unread_with_a_reason_and_never_counted_as_read(self):
        heads = {"a.gz": b"\x1f\x8b\x08\x00", "b.bz2": b"BZh91AY", "c.xz": b"\xfd7zXZ\x00\x00", "d.7z": b"7z\xbc\xaf\x27\x1c\x00\x04", "e.rar": b"Rar!\x1a\x07\x00", "f.cab": b"MSCF\x00\x00\x00\x00"}
        self.put({name: head + b"x" * 40 for name, head in heads.items()})
        result = self.scan()
        self.assertEqual(sorted((item.path, item.reason) for item in result.unread), sorted((name, "other_archive") for name in heads))
        self.assertEqual((result.files_read, result.bytes_read), (0, 0))

    def test_a_file_over_the_size_limit_is_unread_and_a_small_one_is_read(self):
        self.put({"big.bin": b"x" * 50, "small.txt": f"{KEY}\n"})                # 키 한 줄은 41바이트
        with mock.patch.object(rc, "MAX_FILE_BYTES", 45):
            result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("big.bin", "too_big")])
        self.assertEqual([item.path for item in result.findings], ["small.txt"])
        self.assertEqual(result.files_read, 1)

    def test_the_size_limit_boundary_is_inclusive(self):
        self.put({"a.txt": "x" * 40, "b.txt": "x" * 41})
        with mock.patch.object(rc, "MAX_FILE_BYTES", 40):
            result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("b.txt", "too_big")])
        self.assertEqual(result.files_read, 1)

    def test_a_file_that_grows_past_the_limit_while_being_read_is_unread(self):
        self.put({"a.txt": "x" * 100})
        real = rc.scan_stream

        def tight(stream, scan_module, **kwargs):
            kwargs["limit_bytes"] = 10
            return real(stream, scan_module, **kwargs)
        with mock.patch.object(rc, "scan_stream", tight):
            result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("a.txt", "too_big")])

    def test_a_file_that_cannot_be_opened_is_unread_and_the_others_are_still_scanned(self):
        self.put({"locked.db": "잠긴 파일", "ok.txt": f"{KEY}\n"})
        real = open

        def opener(path):
            if str(path).endswith("locked.db"):
                raise PermissionError("가짜 잠김")
            return real(path, "rb")
        result = self.scan(opener=opener)
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("locked.db", "os_error")])
        self.assertEqual([item.path for item in result.findings], ["ok.txt"])
        self.assertEqual(result.files_read, 1)

    def test_a_file_that_fails_in_the_middle_of_reading_is_unread_and_leaves_no_half_result(self):
        self.put({"flaky.txt": f"{KEY}\n"})

        class Flaky(io.BytesIO):
            calls = 0

            def read(self, size=-1):
                Flaky.calls += 1
                if Flaky.calls > 2:
                    raise OSError("가짜 읽기 실패")
                return super().read(size)
        result = self.scan(opener=lambda path: Flaky(Path(path).read_bytes()), chunk_bytes=8)
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("flaky.txt", "os_error")])
        self.assertEqual((result.findings, result.files_read), ([], 0))

    def test_links_are_not_followed_and_are_counted_as_unread(self):
        self.put({"real/inside.txt": f"{KEY}\n", "linked/inside.txt": f"{KEY}\n", "linkfile.txt": f"{KEY}\n", "plain.txt": "글\n"})
        names = {"linked", "linkfile.txt"}
        real_lstat = os.lstat

        def fake_lstat(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if Path(path).name in names:
                return types.SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_size=info.st_size, st_file_attributes=0, st_reparse_tag=0)
            return info
        with mock.patch("os.lstat", fake_lstat):
            result = self.scan()
        self.assertEqual(sorted((item.path, item.reason) for item in result.unread), [("linked", "link"), ("linkfile.txt", "link")])
        self.assertEqual([item.path for item in result.findings], ["real/inside.txt"])           # 링크 안은 들여다보지 않는다
        self.assertEqual(result.files_read, 2)

    def test_cloud_only_placeholders_are_never_opened_and_are_counted_as_unread(self):
        for bit in (0x1000, 0x40000, 0x400000):
            with self.subTest(bit=hex(bit)):
                with rs.temp_dir() as folder:
                    rs.write_files(folder, {"cloud.txt": f"{KEY}\n", "local.txt": "글\n", "cloudfolder/inner.txt": f"{KEY}\n"})
                    real_lstat, real_open, opened = os.lstat, open, []

                    def fake_lstat(path, *args, **kwargs):
                        info = real_lstat(path, *args, **kwargs)
                        if Path(path).name in ("cloud.txt", "cloudfolder"):
                            return types.SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size, st_file_attributes=0x400 | bit, st_reparse_tag=0x9000001A)     # 클라우드 자리표시는 재해석 지점이지만 링크는 아니다
                        return info

                    def opener(path):
                        opened.append(Path(path).name)
                        return real_open(path, "rb")
                    with mock.patch("os.lstat", fake_lstat):
                        result = rc.scan_folder(folder, opener=opener)
                self.assertEqual(sorted((item.path, item.reason) for item in result.unread), [("cloud.txt", "cloud_only"), ("cloudfolder", "cloud_only")])
                self.assertEqual(opened, ["local.txt"])                  # 자리표시는 열지도 않고 그 폴더 안을 읽지도 않는다
                self.assertEqual((result.findings, result.files_read), ([], 1))

    def test_a_real_symbolic_link_is_not_followed_when_the_system_allows_making_one(self):
        self.put({"target/inside.txt": f"{KEY}\n"})
        try:
            os.symlink(self.root / "target", self.root / "link", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("이 환경에서는 심볼릭 링크를 만들 수 없다")
        result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("link", "link")])
        self.assertEqual([item.path for item in result.findings], ["target/inside.txt"])

    def test_the_link_test_is_the_one_the_app_uses_for_symlinks_and_windows_reparse_points(self):
        fake = types.SimpleNamespace
        self.assertTrue(rc._is_link(fake(st_mode=stat.S_IFLNK, st_file_attributes=0, st_reparse_tag=0)))
        self.assertTrue(rc._is_link(fake(st_mode=stat.S_IFDIR, st_file_attributes=0x400, st_reparse_tag=0xA0000003)))        # 윈도 정션(마운트 지점)
        self.assertTrue(rc._is_link(fake(st_mode=stat.S_IFDIR, st_file_attributes=0x400, st_reparse_tag=0xA000000C)))        # 윈도 심볼릭 링크
        self.assertFalse(rc._is_link(fake(st_mode=stat.S_IFREG, st_file_attributes=0x400, st_reparse_tag=0x9000001A)))       # OneDrive 같은 클라우드 자리표시는 링크가 아니다
        self.assertFalse(rc._is_link(fake(st_mode=stat.S_IFREG, st_file_attributes=0x20, st_reparse_tag=0)))
        self.assertFalse(rc._is_link(fake(st_mode=stat.S_IFDIR)))

    def test_entries_that_are_not_regular_files_are_unread(self):
        self.put({"a.txt": "글\n"})
        with mock.patch.object(rc.stat, "S_ISREG", lambda mode: False):
            result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("a.txt", "not_regular")])

    def test_a_folder_that_cannot_be_listed_is_unread_and_the_rest_are_scanned(self):
        self.put({"secret_dir/x.txt": f"{KEY}\n", "ok/y.txt": f"{KEY}\n"})
        real = os.scandir

        def fake(path):
            if Path(path).name == "secret_dir":
                raise PermissionError("가짜 거부")
            return real(path)
        with mock.patch("os.scandir", fake):
            result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("secret_dir", "os_error")])
        self.assertEqual([item.path for item in result.findings], ["ok/y.txt"])

    def test_an_entry_whose_status_cannot_be_read_is_unread(self):
        self.put({"a.txt": "글\n", "b.txt": f"{KEY}\n"})
        real = os.lstat

        def fake(path, *args, **kwargs):
            if Path(path).name == "a.txt":
                raise PermissionError("가짜 거부")
            return real(path, *args, **kwargs)
        with mock.patch("os.lstat", fake):
            result = self.scan()
        self.assertEqual([(item.path, item.reason) for item in result.unread], [("a.txt", "os_error")])
        self.assertEqual([item.path for item in result.findings], ["b.txt"])

    def test_every_reason_the_script_can_give_has_a_plain_korean_text(self):
        import ast
        tree = ast.parse((rs.ROOT / "scripts" / "release_check.py").read_text(encoding="utf-8"))
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Unread" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                used.add(node.args[1].value)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_read_into" and isinstance(node.args[-1], ast.Constant):
                used.add(node.args[-1].value)
        used |= {"zip_nested"}
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(rc.REASON_TEXT)), [])
        self.assertTrue(all(any("가" <= ch <= "힣" for ch in text) for text in rc.REASON_TEXT.values()))


class NameFindingTest(FolderCase):
    def test_a_file_name_shaped_like_a_key_is_a_finding_and_is_shown_hidden(self):
        secret = S.github()
        self.put({f"{secret}.txt": "깨끗한 내용\n", "ok.txt": "글\n"})
        result = self.scan()
        self.assertEqual([(item.line, item.label) for item in result.findings], [(0, "GitHub 토큰")])
        self.assertIn("가림", result.findings[0].path)
        secret_support.assert_no_secret(self, secret, rc.render_scans([result]), what="폴더 표")
        secret_support.assert_no_secret(self, secret, rc.render_json([], [result], "0"), what="JSON")

    def test_a_folder_name_shaped_like_a_key_is_a_finding_and_what_is_inside_is_hidden_but_not_a_second_finding(self):
        secret = S.aws()
        self.put({f"{secret}/inner.txt": "깨끗한 내용\n"})
        result = self.scan()
        self.assertEqual([(item.line, item.label) for item in result.findings], [(0, "AWS 액세스 키")])
        self.assertEqual(result.files_read, 1)

    def test_a_key_in_both_the_name_and_the_content_gives_two_findings(self):
        self.put({f"{S.google()}.txt": f"{KEY}\n"})
        result = self.scan()
        self.assertEqual(sorted((item.line, item.label) for item in result.findings), [(0, "Google API 키"), (1, "GitHub 토큰")])

    def test_names_that_merely_look_long_or_odd_are_not_findings(self):
        self.put({"a" * 120 + ".txt": "글\n", "ghp_짧음.txt": "글\n", "access_token.txt": "글\n", "AKIA.txt": "글\n"})
        self.assertEqual(self.scan().findings, [])

    def test_unreadable_entries_still_have_their_names_checked(self):
        self.put({f"{S.github()}.bin": "내용"})
        with mock.patch.object(rc.stat, "S_ISREG", lambda mode: False):
            result = self.scan()
        self.assertEqual([item.line for item in result.findings], [0])
        self.assertEqual([item.reason for item in result.unread], ["not_regular"])


class UnreadNameMaskTest(FolderCase):
    """'읽지 못함' 목록의 경로도 키 모양 이름을 가린다(D-672 ⑥) — 읽지 못한 이유마다(링크·클라우드 자리표시·일반 파일 아님·다른 압축·너무 큰 파일·읽기 실패·깨진 zip·zip 안의 여러 이유)
    키처럼 생긴 이름의 파일·폴더가 표와 JSON 에 글자 그대로 나오지 않는다(독립 검증 Q R3). 발견 목록의 이름 가림은 `NameFindingTest` 가 본다."""

    SECRET = S.github()

    @staticmethod
    def lstat_as(names, **fields):
        real = os.lstat

        def fake(path, *args, **kwargs):
            info = real(path, *args, **kwargs)
            if Path(path).name in names:
                return types.SimpleNamespace(st_mode=fields.get("st_mode", info.st_mode), st_size=info.st_size, st_file_attributes=fields.get("st_file_attributes", 0),
                                             st_reparse_tag=fields.get("st_reparse_tag", 0))
            return info
        return fake

    def folder(self, label, files):
        folder = self.root / label
        folder.mkdir(parents=True, exist_ok=True)
        rs.write_files(folder, files)
        return folder

    def zip_with_key_named_members(self, path):
        """멤버 이름이 모두 키 모양인 zip — 안에 든 zip(중첩)·gzip 머리·암호 걸림 비트·한도를 넘는 큰 글·CRC 가 틀린 글을 한 개씩 둔다."""
        key = self.SECRET
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as archive:
            archive.writestr("deep.txt", "글\n")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
            for name, content in ((f"{key}.nested", inner.getvalue()), (f"{key}.gz", b"\x1f\x8b\x08\x00" + b"x" * 30), (f"{key}.enc", "암호 걸린 척\n"),
                                  (f"{key}.big", "0123456789" * 30), (f"{key}.crc", "hello world 123456 hello\n")):
                archive.writestr(name, content)
        data = bytearray(path.read_bytes())
        end = data.rindex(b"PK\x05\x06")                                                              # 바깥 zip 의 끝 기록(저장된 안쪽 zip 에도 같은 표지가 있으니 맨 마지막 것)
        directory = int.from_bytes(data[end + 16:end + 20], "little")                                 # 중앙 디렉터리가 시작하는 자리
        entry = data.index(f"{key}.enc".encode("ascii"), directory) - 46                              # 중앙 디렉터리의 그 항목 머리
        data[entry + 8] |= 1                                                                         # 암호 걸림 비트
        path.write_bytes(bytes(data).replace(b"hello world", b"hellO world"))                         # 저장된 글을 바꿔 CRC 가 틀리게 한다

    def scenarios(self):
        key = self.SECRET

        def links():
            folder = self.folder("links", {f"{key}.txt": "x\n", f"{key}/inside.txt": "y\n"})
            with mock.patch("os.lstat", self.lstat_as({f"{key}.txt", key}, st_mode=stat.S_IFLNK | 0o777)):
                return rc.scan_folder(folder)

        def cloud():
            folder = self.folder("cloud", {f"{key}.txt": "x\n", f"{key}/inside.txt": "y\n"})
            with mock.patch("os.lstat", self.lstat_as({f"{key}.txt", key}, st_file_attributes=0x400 | 0x1000, st_reparse_tag=0x9000001A)):
                return rc.scan_folder(folder)

        def not_regular():
            folder = self.folder("notregular", {f"{key}.txt": "x\n"})
            with mock.patch.object(rc.stat, "S_ISREG", lambda mode: False):
                return rc.scan_folder(folder)

        def other_archive():
            return rc.scan_folder(self.folder("gz", {f"{key}.gz": b"\x1f\x8b\x08\x00" + b"x" * 40}))

        def too_big():
            folder = self.folder("big", {f"{key}.bin": b"x" * 50})
            with mock.patch.object(rc, "MAX_FILE_BYTES", 45):
                return rc.scan_folder(folder)

        def unreadable_file():
            folder = self.folder("locked", {f"{key}.db": "잠긴 파일"})
            real = open

            def opener(path):
                if key in str(path):
                    raise PermissionError("가짜 잠김")
                return real(path, "rb")
            return rc.scan_folder(folder, opener=opener)

        def unreadable_status():
            folder = self.folder("nostatus", {f"{key}.txt": "x\n"})
            real = os.lstat

            def fake(path, *args, **kwargs):
                if Path(path).name == f"{key}.txt":
                    raise PermissionError("가짜 거부")
                return real(path, *args, **kwargs)
            with mock.patch("os.lstat", fake):
                return rc.scan_folder(folder)

        def unlistable_folder():
            folder = self.folder("nolist", {f"{key}/inside.txt": "x\n"})
            real = os.scandir

            def fake(path):
                if Path(path).name == key:
                    raise PermissionError("가짜 거부")
                return real(path)
            with mock.patch("os.scandir", fake):
                return rc.scan_folder(folder)

        def broken_zip():
            return rc.scan_folder(self.folder("brokenzip", {f"{key}.zip": b"PK\x03\x04garbage garbage"}))

        def zip_members():
            folder = self.folder("zipmembers", {})
            self.zip_with_key_named_members(folder / "pack.zip")
            with mock.patch.object(rc, "MAX_MEMBER_BYTES", 200):
                return rc.scan_folder(folder)

        def key_named_zip():
            folder = self.folder("keyzip", {})
            self.zip_with_key_named_members(folder / f"{key}.zip")
            with mock.patch.object(rc, "MAX_MEMBER_BYTES", 200):
                return rc.scan_folder(folder)
        return {"링크": links, "클라우드 자리표시": cloud, "일반 파일 아님": not_regular, "다른 압축": other_archive, "너무 큰 파일": too_big, "열기 실패": unreadable_file,
                "상태 읽기 실패": unreadable_status, "폴더 목록 실패": unlistable_folder, "깨진 zip": broken_zip, "zip 안 이유들": zip_members, "키 이름 zip 안 이유들": key_named_zip}

    def test_every_reason_hides_a_key_shaped_name_in_the_table_and_in_the_json(self):
        seen = set()
        for label, scenario in self.scenarios().items():
            with self.subTest(label=label):
                result = scenario()
                self.assertTrue(result.unread, "그 상황이 '읽지 못함' 을 만든다")
                seen |= {item.reason for item in result.unread}
                shown, as_json = rc.render_scans([result]), rc.render_json([], [result], "0")
                for text, what in ((shown, "폴더 표"), (as_json, "JSON")):
                    secret_support.assert_no_secret(self, self.SECRET, text, what=what)
                    self.assertIn("가림", text)                                           # 이름을 아예 없앤 것이 아니라 가려서 보인다
                self.assertTrue(all("가림" in item.path for item in result.unread), label)
        self.assertEqual(seen, set(rc.REASON_TEXT), "이유마다 이름 가림 시험이 있어야 한다(새 이유를 더하면 여기에도 상황을 더한다)")


class OutputTest(FolderCase):
    def test_no_key_character_run_and_no_machine_path_reach_the_table_or_the_json(self):
        secrets = [S.github(), S.google(), S.aws(), S.pem(), S.ya29(), S.bearer()]
        self.put({"logs/a.log": "\n".join(f"줄 {index} {secret}" for index, secret in enumerate(secrets)) + "\n", "z.zip": b"PK\x03\x04bad"})
        result = self.scan()
        shown = rc.render_scans([result])
        as_json = rc.render_json(rc.run_checks(rs.ROOT, selftest_runner=rs.selftest_ok, scans=[result]), [result], "0.0.0")
        for secret in secrets:
            secret_support.assert_no_secret(self, secret, shown, what="폴더 표")
            secret_support.assert_no_secret(self, secret, as_json, what="JSON")
        for text in (shown, as_json):
            self.assertNotIn(str(self.root), text)
            self.assertNotIn(self.root.name, text)

    def test_the_folder_table_has_the_counts_and_one_line_per_finding_and_unread_file(self):
        self.put({"a.log": f"앞\n{KEY}\n", "b.gz": b"\x1f\x8b\x08\x00 x", "c.txt": "글\n"})
        text = rc.render_scans([self.scan()])
        row = next(line for line in text.splitlines() if line.startswith("| 폴더 1 |"))
        self.assertTrue(row.startswith("| 폴더 1 | 2 | "), row)
        self.assertTrue(row.endswith("| 0 | 1 | 1 |"), row)                 # 열어 본 zip 0 · 발견 1 · 읽지 못함 1
        self.assertIn("a.log:2 GitHub 토큰", text)
        self.assertIn("b.gz — 열지 못하는 압축 형식", text)

    def test_a_name_finding_is_shown_as_a_file_name_finding_not_as_line_zero(self):
        self.put({f"{S.github()}.txt": "글\n"})
        text = rc.render_scans([self.scan()])
        self.assertIn("(파일 이름) GitHub 토큰", text)
        self.assertNotIn(":0 ", text)

    def test_long_lists_show_twenty_and_count_the_rest(self):
        self.put({f"k{number:02d}.txt": f"{KEY}\n" for number in range(25)})
        text = rc.render_scans([self.scan()])
        self.assertEqual(sum(1 for line in text.splitlines() if line.startswith("  - k")), 20)
        self.assertIn("외 5개", text)
        self.assertIn("발견 25개", text)

    def test_nothing_is_printed_for_no_scans(self):
        self.assertEqual(rc.render_scans([]), "")

    def test_hostile_file_names_are_shown_plain(self):
        names = ["줄\x07바꿈.txt", "탭\t이름.txt", "안녕" + chr(0x202E) + "txt.exe"]
        created = 0
        for name in names:
            try:
                self.put({name: f"{KEY}\n"})
                created += 1
            except OSError:
                continue
        if not created:
            self.skipTest("이 파일 시스템은 이런 이름을 허용하지 않는다")
        text = rc.render_scans([self.scan()])
        for bad in ("\x07", "\t", chr(0x202E)):
            self.assertNotIn(bad, text)


class ReadOnlyScanTest(FolderCase):
    def test_scanning_changes_no_byte_adds_no_file_and_leaves_the_folder_listing_alone(self):
        self.put({"a.txt": f"{KEY}\n", "b/c.log": "글\n", "d.zip": b"PK\x03\x04bad", "e.gz": b"\x1f\x8b\x08\x00"})
        before, listing = rs.tree_fingerprint(self.root), sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        self.scan()
        rc.render_scans([self.scan()])
        self.assertEqual(rs.tree_fingerprint(self.root), before)
        self.assertEqual(sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*")), listing)

    def test_the_scan_closes_every_file_it_opens(self):
        self.put({"a.txt": "글\n", "b.zip": b"PK\x03\x04bad", "c.gz": b"\x1f\x8b\x08\x00"})
        opened = []
        real = open

        def opener(path):
            handle = real(path, "rb")
            opened.append(handle)
            return handle
        self.scan(opener=opener)
        self.assertEqual(len(opened), 3)
        self.assertTrue(all(handle.closed for handle in opened))


if __name__ == "__main__":
    unittest.main()
