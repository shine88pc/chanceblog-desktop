"""글자 읽기 추가 도구 폴더 확인 `service/ocr_addon.py`(결정 D-512, 설계서 3-9·5-1)의 시험 — 읽기만 하고(쓰기 0), 앱에 박은 모델·사전 해시가 신뢰의 뿌리이며, 어긋나면 `invalid`·없으면 `absent` 이다.

진짜 모델(18MB)은 쓰지 않는다 — 시험은 작은 가짜 파일의 크기·해시로 박은 값(`EMBEDDED_FILES`)을 임시로 바꿔 끼운다(원래 값은 문자 그대로 못박아 둔다).
"""
import ast
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.service import ocr_addon as oa  # noqa: E402

SOURCE = ROOT / "src" / "chanceblog_desktop" / "service" / "ocr_addon.py"
FILES = {"ocr_worker.exe": b"worker-bytes", "models/det/inference.onnx": b"det-model-bytes", "models/rec/inference.onnx": b"rec-model-bytes", "data/ppocrv5_korean_dict.txt": b"dict-bytes", "_internal/lib.dll": b"lib"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def info_for(files, **override):
    info = {"schema": 1, "name": "ocr_addon", "proto": 1, "files": [{"path": path, "bytes": len(data), "sha256": sha(data)} for path, data in sorted(files.items())],
            "models_dict": {name: {"bytes": len(files[name]), "sha256": sha(files[name])} for name in ("models/det/inference.onnx", "models/rec/inference.onnx", "data/ppocrv5_korean_dict.txt")},
            "packages": [{"name": "rapidocr", "version": "3.10.0"}, {"name": "onnxruntime", "version": "1.31.1"}, {"name": "numpy", "version": "2.5.4"}]}
    info.update(override)
    return info


EMBEDDED = {name: (len(FILES[name]), sha(FILES[name])) for name in ("models/det/inference.onnx", "models/rec/inference.onnx", "data/ppocrv5_korean_dict.txt")}


def write_addon(folder, files=None, info=None):
    files = dict(FILES if files is None else files)
    for relative, data in files.items():
        path = Path(folder, *relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    Path(folder, oa.INFO_NAME).write_text(json.dumps(info if info is not None else info_for(files), ensure_ascii=False), encoding="utf-8")


class AddonCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "ocr")
        os.makedirs(self.folder)
        patcher = mock.patch.dict(oa.EMBEDDED_FILES, EMBEDDED, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def listing(self):
        return sorted((os.path.relpath(os.path.join(root, name), self.folder), os.path.getsize(os.path.join(root, name)), os.path.getmtime(os.path.join(root, name)))
                      for root, _dirs, names in os.walk(self.folder) for name in names)


class AbsentAndOkTest(AddonCase):
    def test_a_missing_or_empty_folder_or_a_bad_argument_is_absent_not_an_error(self):
        self.assertEqual(oa.verify(os.path.join(self.tmp.name, "nothing")).state, oa.ABSENT)
        self.assertEqual(oa.verify(self.folder).state, oa.ABSENT)
        for bad in (None, 5, ["x"]):
            self.assertEqual(oa.verify(bad).state, oa.ABSENT)

    def test_a_good_folder_is_ok_and_reports_the_version_without_any_path(self):
        write_addon(self.folder)
        status = oa.verify(self.folder)
        self.assertEqual((status.state, status.ok, status.problems, status.version), (oa.OK, True, (), "rapidocr 3.10.0 · onnxruntime 1.31.1"))
        self.assertNotIn(self.tmp.name, repr(status))
        self.assertIsNone(oa.verify_problem(self.folder))

    def test_the_check_only_reads_and_leaves_the_folder_exactly_as_it_was(self):
        write_addon(self.folder)
        before = self.listing()
        oa.verify(self.folder)
        oa.verify(self.folder, check_files=False)
        self.assertEqual(self.listing(), before)

    def test_the_embedded_values_are_pinned_as_literal_numbers(self):
        """앱에 박은 값이 소스에서 바뀌면 시험이 빨개진다 — 임시로 끼운 시험용 값이 아니라 소스 글자를 직접 읽어 견준다."""
        real = {"models/det/inference.onnx": (4826518, "a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d"),
                "models/rec/inference.onnx": (13418787, "92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08"),
                "data/ppocrv5_korean_dict.txt": (47451, "a88071c68c01707489baa79ebe0405b7beb5cca229f4fc94cc3ef992328802d7")}
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        value = next(node.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "EMBEDDED_FILES" for target in node.targets))
        self.assertEqual(ast.literal_eval(value), real)

    def test_the_folder_name_and_the_fixed_command(self):
        self.assertTrue(oa.addon_folder("C:\\App").endswith("ocr"))
        command = oa.worker_command(self.folder)
        self.assertEqual((len(command), os.path.basename(command[0])), (1, "ocr_worker.exe"))


class InvalidTest(AddonCase):
    def problems(self):
        status = oa.verify(self.folder)
        self.assertEqual(status.state, oa.INVALID)
        self.assertNotIn(self.tmp.name, repr(status))
        return status.problems

    def test_a_missing_file_is_invalid(self):
        write_addon(self.folder)
        os.remove(os.path.join(self.folder, "_internal", "lib.dll"))
        self.assertEqual(self.problems(), ("missing",))
        self.assertIsNotNone(oa.verify_problem(self.folder))

    def test_a_changed_size_is_invalid_even_without_hashing(self):
        write_addon(self.folder)
        Path(self.folder, "_internal", "lib.dll").write_bytes(b"longer than before")
        self.assertEqual(self.problems(), ("size",))
        self.assertEqual(oa.verify(self.folder, check_files=False).problems, ("size",))

    def test_same_size_but_different_bytes_is_caught_by_the_hash_and_only_by_the_hash(self):
        write_addon(self.folder)
        Path(self.folder, "_internal", "lib.dll").write_bytes(b"LIB")
        self.assertEqual(self.problems(), ("hash",))
        self.assertEqual(oa.verify(self.folder, check_files=False).state, oa.OK, "빠른 확인은 크기만 본다 — 띄우기 전에는 해시까지 본다")

    def test_an_extra_file_is_invalid_but_the_two_system_leftovers_are_ignored(self):
        write_addon(self.folder)
        Path(self.folder, "Thumbs.db").write_bytes(b"x")
        Path(self.folder, "desktop.ini").write_bytes(b"x")
        self.assertEqual(oa.verify(self.folder).state, oa.OK)
        Path(self.folder, "_internal", "planted.dll").write_bytes(b"x")
        self.assertEqual(self.problems(), ("extra",))

    def test_a_model_that_differs_from_the_value_built_into_the_app_is_invalid_even_if_the_info_file_agrees(self):
        files = dict(FILES)
        files["models/rec/inference.onnx"] = b"another-model-of-other-size!"
        write_addon(self.folder, files)
        self.assertEqual(oa.verify(self.folder).problems, ("model_hash",), "정보 파일과 폴더가 서로 맞아도 앱에 박은 해시와 다르면 안 된다")

    def test_a_tampered_info_file_that_claims_the_app_hash_for_a_different_file_is_invalid(self):
        write_addon(self.folder)
        info = info_for(FILES)
        info["files"] = [dict(entry, sha256=sha(b"x")) if entry["path"] == "models/det/inference.onnx" else entry for entry in info["files"]]
        Path(self.folder, oa.INFO_NAME).write_text(json.dumps(info), encoding="utf-8")
        self.assertIn("model_hash", oa.verify(self.folder).problems)

    def test_a_models_dict_that_states_another_size_or_hash_than_the_app_is_invalid_even_when_the_file_list_agrees(self):
        """정보 파일의 모델 칸(models_dict)도 앱에 박은 값과 맞아야 한다 — 파일 목록·폴더가 맞아도 칸이 다르게 적혀 있거나 모양이 아니면 거절한다."""
        for label, change in (("sha256", lambda entry: entry.update(sha256=sha(b"other"))), ("bytes", lambda entry: entry.update(bytes=1)), ("empty", lambda entry: entry.clear())):
            with self.subTest(label=label):
                info = info_for(FILES)
                change(info["models_dict"]["models/det/inference.onnx"])
                write_addon(self.folder, info=info)
                self.assertEqual(oa.verify(self.folder).problems, ("model_hash",), label)
        info = info_for(FILES, models_dict="not a dict")
        write_addon(self.folder, info=info)
        self.assertEqual(oa.verify(self.folder).problems, ("model_hash",))

    def test_the_info_file_size_limit_is_two_megabytes_exactly(self):
        """한도 상수를 시험이 따라 바꾸지 않게 글자 그대로 못박는다 — 정확히 2MB 는 통과, 한 바이트 넘으면 거절."""
        write_addon(self.folder)
        path = Path(self.folder, oa.INFO_NAME)
        base = path.read_bytes()
        limit = 2 * 1024 * 1024
        self.assertEqual(oa.MAX_INFO_BYTES, limit)
        path.write_bytes(base + b" " * (limit - len(base)))
        self.assertEqual(oa.verify(self.folder).state, oa.OK)
        path.write_bytes(base + b" " * (limit - len(base) + 1))
        self.assertEqual(oa.verify(self.folder).problems, ("info",))

    def test_a_deeply_nested_json_info_file_is_invalid_and_never_lets_a_recursion_error_out(self):
        """검증 S SP-6 — 2MB 안에도 들어가는 아주 깊은 겹침도 invalid 로 거절한다(예외가 화면 쪽으로 새지 않게)."""
        write_addon(self.folder)
        Path(self.folder, oa.INFO_NAME).write_bytes(b"[" * 100000 + b"]" * 100000)
        status = oa.verify(self.folder)
        self.assertEqual((status.state, status.problems), (oa.INVALID, ("info",)))
        self.assertIsNotNone(oa.verify_problem(self.folder))
        with self.assertRaises(ValueError):
            oa.read_info(self.folder)

    def test_a_listed_file_that_is_a_link_is_refused_even_when_its_size_and_bytes_look_right(self):
        """검증 S SP-17 — 목록의 파일이 링크면 거절한다(링크를 따라 다른 곳의 파일을 읽지 않는다)."""
        write_addon(self.folder)
        with mock.patch.object(os.path, "islink", side_effect=lambda path: str(path).endswith("lib.dll")):
            self.assertEqual(oa.verify(self.folder).problems, ("missing",))
        self.assertEqual(oa.verify(self.folder).state, oa.OK, "대조 — 링크가 아니면 통과")

    def test_only_the_two_exact_system_leftovers_are_ignored_not_names_that_merely_start_or_end_like_them(self):
        """검증 S SP-17 — 낯선 파일 허용은 정확히 두 이름(대소문자 무시)뿐이다."""
        write_addon(self.folder)
        for name in ("thumbs_x.dll", "desktop.ini.exe", "Thumbs.db.bak", "xdesktop.ini", "thumbs.dll"):
            with self.subTest(name=name):
                path = Path(self.folder, name)
                path.write_bytes(b"x")
                self.assertEqual(oa.verify(self.folder).problems, ("extra",))
                path.unlink()
        for name in ("THUMBS.DB", "Desktop.INI"):
            with self.subTest(name=name):
                path = Path(self.folder, name)
                path.write_bytes(b"x")
                self.assertEqual(oa.verify(self.folder).state, oa.OK)
                path.unlink()

    def test_a_list_without_the_worker_is_invalid(self):
        files = {name: data for name, data in FILES.items() if name != "ocr_worker.exe"}
        write_addon(self.folder, files)
        self.assertEqual(oa.verify(self.folder).problems, ("worker",))

    def test_unsafe_paths_in_the_list_are_invalid(self):
        for bad in ("../outside.dll", "/abs/x.dll", "C:/x.dll", "a\\b.dll", "", "a//b.dll", "./a.dll", "a/./b.dll", "x\x00y", 5, None):
            with self.subTest(bad=repr(bad)):
                info = info_for(FILES)
                info["files"][0]["path"] = bad
                write_addon(self.folder, info=info)
                status = oa.verify(self.folder)
                self.assertEqual(status.state, oa.INVALID)
                self.assertEqual(status.problems, ("unsafe_path",))

    def test_a_malformed_info_file_is_invalid_and_never_raises(self):
        base = info_for(FILES)
        variants = [dict(base, name="other"), dict(base, proto=2), dict(base, files=[]), dict(base, files="x"), dict(base, files=[5]), dict(base, files=base["files"] + [base["files"][0]]),
                    dict(base, files=[dict(base["files"][0], bytes=-1)] + base["files"][1:]), dict(base, files=[dict(base["files"][0], bytes=True)] + base["files"][1:]),
                    dict(base, files=[dict(base["files"][0], sha256="XYZ")] + base["files"][1:])]
        for index, info in enumerate(variants):
            with self.subTest(index=index):
                write_addon(self.folder, info=info)
                self.assertEqual(oa.verify(self.folder).state, oa.INVALID)
        for raw in (b"", b"not json", b"[1, 2]", b"\xff\xfe", b"{" * 5000):
            Path(self.folder, oa.INFO_NAME).write_bytes(raw)
            self.assertEqual(oa.verify(self.folder).state, oa.INVALID, raw[:10])

    def test_a_huge_info_file_is_refused_before_it_is_read(self):
        write_addon(self.folder)
        Path(self.folder, oa.INFO_NAME).write_bytes(b" " * (oa.MAX_INFO_BYTES + 1))
        self.assertEqual(oa.verify(self.folder).problems, ("info",))

    def test_a_packages_value_that_is_not_a_list_is_invalid_and_never_lets_an_exception_out(self):
        """감사 OCR-S1 I7(결정 D-588) — 정보 파일의 `packages` 가 목록이 아닌 값(null·참거짓·숫자 …)이면 다른 검사를 모두 통과해도 예외가 새던 틈(`_version` 의 TypeError)을 닫았다: invalid(`info`) 로 끝난다. S1 의 probe5 가 찾은 여섯 모양(null·참·0·-1·아주 큰 정수·1.5)과 그 밖의 비목록."""
        for value in (None, True, False, 0, -1, 10 ** 30, 1.5, "x", {}, {"a": 1}):
            with self.subTest(packages=repr(value)[:20]):
                write_addon(self.folder, info=info_for(FILES, packages=value))
                status = oa.verify(self.folder)
                self.assertEqual((status.state, status.problems, status.version), (oa.INVALID, ("info",), ""))
                self.assertEqual(oa.verify_problem(self.folder), "info")
                self.assertEqual(oa.verify(self.folder, check_files=False).problems, ("info",))
                self.assertEqual(oa._version({"packages": value}), "", "버전 글을 읽는 함수도 예외를 내지 않는다")

    def test_a_packages_list_with_odd_entries_or_no_packages_at_all_is_still_ok_and_only_the_two_known_names_are_shown(self):
        for packages, version in (([], ""), ([None], ""), ([1], ""), ([[]], ""), ([{}], ""), ([{"name": "rapidocr", "version": 5}, {"name": "onnxruntime", "version": "1.31.1"}], "onnxruntime 1.31.1"),
                                  ([{"name": "numpy", "version": "2.5.4"}], "")):
            with self.subTest(packages=repr(packages)[:40]):
                write_addon(self.folder, info=info_for(FILES, packages=packages))
                status = oa.verify(self.folder)
                self.assertEqual((status.state, status.version), (oa.OK, version))
        info = info_for(FILES)
        del info["packages"]
        write_addon(self.folder, info=info)
        self.assertEqual((oa.verify(self.folder).state, oa.verify(self.folder).version), (oa.OK, ""), "칸이 아예 없으면 예전과 같다")

    def make_link(self, target, link):
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("이 환경에서는 디렉터리 링크를 만들 수 없다(권한 없음) — 같은 규칙은 아래 모의 시험이 본다")

    def test_a_directory_link_inside_the_folder_is_invalid_even_though_the_walk_does_not_look_inside_it(self):
        """감사 OCR-S1 I8(결정 D-588) — `os.walk` 는 디렉터리 링크 안을 돌지 않아 링크 뒤의 목록에 없는 파일이 `extra` 로 안 잡혔다. 이제 링크 자체를 `link` 문제로 센다."""
        write_addon(self.folder)
        outside = os.path.join(self.tmp.name, "outside")
        os.makedirs(outside)
        Path(outside, "planted.dll").write_bytes(b"x")
        self.make_link(outside, os.path.join(self.folder, "linked"))
        self.assertEqual(self.problems(), ("link",))
        self.assertEqual(oa.verify_problem(self.folder), "link")

    def test_a_directory_link_nested_below_the_top_folder_is_found_too(self):
        """검증 SQ 권고 2(변이 SQ-N5 — 링크 검사를 맨 위 폴더에서만 돌리면 살아남던 틈, 결정 D-593) — 묶음 폴더의 실제 모양은 `_internal` 아래 여러 겹이다. 새 폴더 안(맨 위에서 두 겹 아래)의 디렉터리 링크도 `link` 다."""
        write_addon(self.folder)
        outside = os.path.join(self.tmp.name, "outside")
        os.makedirs(outside)
        Path(outside, "planted.dll").write_bytes(b"x")
        nested = os.path.join(self.folder, "_internal", "deep")
        os.makedirs(nested)
        self.make_link(outside, os.path.join(nested, "linked2"))
        self.assertEqual(self.problems(), ("link",))
        self.assertEqual(oa.verify_problem(self.folder), "link")

    def test_a_listed_file_that_sits_behind_a_directory_link_is_refused_too(self):
        """목록의 파일은 마지막 성분만 링크인지 보므로 폴더째 다른 곳으로 옮기고 링크를 걸어도 크기·해시가 맞아 통과하던 길도 같은 `link` 로 막힌다."""
        write_addon(self.folder)
        moved = os.path.join(self.tmp.name, "moved_internal")
        os.rename(os.path.join(self.folder, "_internal"), moved)
        self.make_link(moved, os.path.join(self.folder, "_internal"))
        self.assertEqual(self.problems(), ("link",))

    def test_a_directory_link_is_found_by_the_walk_rule_where_links_cannot_be_made_too(self):
        """링크를 못 만드는 환경에서도 도는 모의 — `os.path.islink` 만 좁게 바꿔 폴더 하나를 링크처럼 보이게 한다(링크 안은 돌지 않으므로 그 안의 파일은 보이지 않는다)."""
        write_addon(self.folder)
        os.makedirs(os.path.join(self.folder, "sub"))
        Path(self.folder, "sub", "planted.dll").write_bytes(b"x")
        self.assertEqual(self.problems(), ("extra",), "대조 — 링크가 아니면 그 안의 낯선 파일이 extra 로 잡힌다")
        with mock.patch.object(os.path, "islink", side_effect=lambda path: os.path.basename(str(path)) == "sub"):
            self.assertEqual(self.problems(), ("link",))
        with mock.patch.object(os.path, "islink", side_effect=lambda path: os.path.basename(str(path)) == "_internal"):
            os.remove(os.path.join(self.folder, "sub", "planted.dll"))
            os.rmdir(os.path.join(self.folder, "sub"))
            self.assertEqual(self.problems(), ("link",), "목록의 파일이 든 폴더가 링크여도 같다")

    def test_a_nested_directory_link_is_found_by_the_walk_rule_where_links_cannot_be_made_too(self):
        """검증 SQ 권고 2 — 링크 권한이 없는 CI 에서도 '맨 위 폴더만 본다' 는 회귀가 걸리게 `os.path.islink` 만 이름으로 좁게 바꾼 모의: 맨 위에서 세 겹 아래(`_internal` 아래 `deep` 아래 `deeper`)의 폴더 하나를 링크처럼 보이게 한다(링크 안은 돌지 않으므로 그 안의 파일은 보이지 않는다)."""
        write_addon(self.folder)
        deeper = os.path.join(self.folder, "_internal", "deep", "deeper")
        os.makedirs(deeper)
        Path(deeper, "planted.dll").write_bytes(b"x")
        self.assertEqual(self.problems(), ("extra",), "대조 — 링크가 아니면 중첩 폴더 안의 낯선 파일이 extra 로 잡힌다")
        for name in ("deep", "deeper"):
            with self.subTest(link_named=name), mock.patch.object(os.path, "islink", side_effect=lambda path, name=name: os.path.basename(str(path)) == name):
                self.assertEqual(self.problems(), ("link",))

    def test_the_adapter_hash_hook_refuses_to_start_a_tampered_folder(self):
        from chanceblog_desktop.ui import ocr_adapter
        from capability_support import local_ocr_off, local_ocr_on
        write_addon(self.folder)
        Path(self.folder, "_internal", "lib.dll").write_bytes(b"LIB")
        local_ocr_on()
        self.addCleanup(local_ocr_off)
        adapter = ocr_adapter.OcrAdapter(oa.worker_command(self.folder), verify=lambda: oa.verify_problem(self.folder))
        outcome = adapter.read_rgb(16, 16, bytes(768), "960")
        self.assertEqual((outcome.error, adapter.launches), ("addon_invalid", 0))


class SourceShapeTest(unittest.TestCase):
    def test_the_service_only_reads_and_uses_no_network_or_process(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported - {"__future__"}, {"hashlib", "json", "os", "re", "dataclasses"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                self.assertNotIn(name, ("os.remove", "os.unlink", "os.rename", "os.replace", "os.mkdir", "os.makedirs", "os.rmdir", "os.system", "os.popen", "os.startfile", "shutil.rmtree", "shutil.copy"))
                if name == "open":
                    mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else "r"
                    self.assertEqual(mode, "rb", "파일은 읽기 전용으로만 연다")
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("~", text)
        self.assertNotIn("http", text.lower())
        self.assertNotIn("write_text", text)
        self.assertNotIn("write_bytes", text)


if __name__ == "__main__":
    unittest.main()
