"""후보 산출물 키 모양 훑기(`scripts/release_check.py` 의 `scan_folder`·`scan_stream`, D-672) 시험.

지키는 것:
  1) 새 규칙 없음: 키 모양 판정은 `security/scan.py` 의 `scan_secrets` 를 그대로 부른다(부르는 것을 시험이 지켜 본다). 여섯 유형이 모두 잡힌다.
  2) 빠짐없이: 하위 폴더·숨은 파일·확장자 없는 파일·대문자 확장자·이진 파일·UTF-8 BOM·UTF-16 파일·여러 덩어리로 나뉜 큰 파일·zip 안의 파일·이름에 든 키 모양까지 잡는다.
  3) 덩어리 경계: 키가 덩어리 경계에 걸쳐도 정확히 한 번 센다(경계를 훑는 모든 자리를 쓸어 본다). 줄 번호는 파일 맨 앞부터 센 값이고 CR·LF·CRLF 가 덩어리 사이에서 갈려도 맞다.
  4) 조용히 건너뛰지 않는다: 링크·다른 압축 형식·너무 큰 파일·읽기 실패·깨진 zip·암호 걸린 zip·중첩 zip·압축 한도 초과는 모두 '읽지 못함' 으로 이유와 함께 센다.
  5) 안전: 결과·표·JSON 어디에도 키 글자와 이 PC 의 경로가 없다(카나리). 키 모양 파일 이름은 가려서 보인다. 폴더 안 파일은 한 바이트도 바뀌지 않는다.
키 모양은 `scan_samples` 가 실행할 때 조각을 이어 붙여 만든다. 네트워크·실제 비밀 없이 돈다.
"""
import codecs
import io
import os
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

    def test_utf16_files_with_a_bom_are_read_as_utf16(self):
        text = f"앞 줄\n{KEY}\n끝\n"
        self.put({"le.txt": text.encode("utf-16"), "be.txt": codecs.BOM_UTF16_BE + text.encode("utf-16-be")})
        result = self.scan()
        self.assertEqual(self.lines_of(result), [("be.txt", 2), ("le.txt", 2)])

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

    def test_empty_stream_and_the_size_limit(self):
        self.assertEqual(self.run_stream(b"", 10), ([], 0))
        with self.assertRaises(rc._TooBig):
            self.run_stream(b"x" * 100, 10, limit=50)
        self.assertEqual(self.run_stream(b"x" * 100, 10, limit=100)[1], 100)

    def test_the_default_sizes_are_what_the_docs_say(self):
        self.assertEqual((rc.CHUNK_BYTES, rc.OVERLAP_CHARS), (1 << 20, 4096))
        self.assertGreater(rc.OVERLAP_CHARS, 200)                              # 키·토큰 모양보다 길게 겹친다


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
