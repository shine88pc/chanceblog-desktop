"""'사진 정리'의 실제 공급자 `ui/photo_adapter.py`(사진 연동 2단계, 결정 D-499) — PySide6 없이 돈다(CI 와 같은 조건). 사진 파일은 이 시험이 임시 폴더에 만든 아주 작은 파일뿐이고(읽기 도구 `probe` 는 가짜), 어댑터는 읽기만 한다.

지키는 것:
  1) 어댑터를 가져오는 데 PySide6 가 필요 없다(Qt 이미지 읽기는 쓰는 자리에서 늦게 가져온다) · 파일을 쓰거나 지우거나 옮기지 않고 네트워크·하위 프로세스·표준 출력이 없다(소스 검사).
  2) `judge` 는 바꿔 끼운 읽기 도구의 판정을 그대로 돌려주고, `check` 는 서비스 `check_files` 의 결과를 `FileState` 로 옮긴다(파일 있음·없음·큰 PNG·가짜 사진·읽기 도구가 터진 파일).
  3) 돌려주는 값 어디에도 경로가 없다 · `PhotoBoard` 와 실제 파일로 이어도 같다(넣기 → 파일이 사라지면 '파일 없음' → 다시 찾기로 새 파일에 이어 붙이기).
"""
import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.ui import adapters, photo_adapter  # noqa: E402
from chanceblog_desktop.ui.core import app_state, imagerules as R, photo_view as pv  # noqa: E402

ADAPTER = ROOT / "src" / "chanceblog_desktop" / "ui" / "photo_adapter.py"
MARKER = "UNIQ-ADAPTER-n4c8"


def probe_of(fmt="jpeg", width=640, height=480, can_read=True):
    def probe(_path):
        return R.Probe(can_read, fmt, width, height)
    return probe


class TempPhotos(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix=MARKER)
        self.addCleanup(holder.cleanup)
        self.folder = Path(holder.name)

    def make(self, name, data=b"x"):
        path = self.folder / name
        path.write_bytes(data)
        return str(path)

    @staticmethod
    def manifest_of(*paths):
        manifest = pm.empty_manifest()
        for path in paths:
            manifest, _photo_id = pm.add_photo(manifest, path)
        return manifest


class SourceTest(unittest.TestCase):
    def test_importing_the_adapter_needs_no_pyside6_and_the_qt_reader_is_fetched_late(self):
        tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                self.assertNotIn("PySide6", [alias.name.split(".")[0] for alias in node.names])
            if isinstance(node, ast.ImportFrom):
                head = (node.module or "").split(".")[0]
                self.assertNotEqual(head, "PySide6")
                self.assertFalse(node.level == 1 and head == "qt", "Qt 화면 층은 맨 위에서 가져오지 않는다")
        late = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "qt"]
        self.assertEqual(len(late), 1, "Qt 이미지 읽기는 쓰는 함수 안에서 늦게 가져온다")
        provider = photo_adapter.ServicePhotoProvider()                                  # 만드는 데도 Qt 가 필요 없다
        self.assertFalse(provider.sample)

    def test_the_adapter_only_reads(self):
        source = ADAPTER.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
        self.assertFalse(imported & {"os", "shutil", "tempfile", "subprocess", "socket", "urllib", "http", "ssl", "pathlib", "logging", "traceback", "webbrowser", "ctypes", "requests"}, imported)
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertFalse(calls & {"open", "print", "input", "exec", "eval"}, calls)
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertFalse(attributes & {"write", "write_text", "write_bytes", "unlink", "remove", "rename", "replace", "mkdir", "makedirs", "copy", "copyfile", "move", "rmtree", "touch", "chmod", "stdout", "stderr"}, attributes)

    def test_the_app_state_pairs_the_real_photo_provider_when_the_home_provider_is_real(self):
        state = app_state.AppState(adapters.ServiceHomeProvider())
        self.assertIsInstance(state.drafts.photos.provider, photo_adapter.ServicePhotoProvider)
        injected = pv.FakePhotoProvider()
        self.assertIs(app_state.AppState(adapters.ServiceHomeProvider(), photos=injected).drafts.photos.provider, injected, "넣어 준 공급자가 짝 공급자보다 먼저다")

    def test_the_real_provider_pairs_with_the_home_provider_and_the_fake_stays_the_default_without_it(self):
        self.assertIsInstance(adapters.ServiceHomeProvider().photos_provider(), photo_adapter.ServicePhotoProvider)
        self.assertFalse(photo_adapter.ServicePhotoProvider.sample)
        self.assertTrue(pv.FakePhotoProvider.sample)
        self.assertIsInstance(app_state.AppState().drafts.photos.provider, pv.FakePhotoProvider)


class JudgeTest(unittest.TestCase):
    def test_judge_hands_the_path_to_the_swapped_in_reader_and_returns_its_verdict_unchanged(self):
        seen = []
        verdict = R.Verdict(R.OK, "", "", 4000, 3000, "jpeg")

        def judge(path):
            seen.append(path)
            return verdict
        provider = photo_adapter.ServicePhotoProvider(judge=judge)
        self.assertIs(provider.judge("C:/a/b.jpg"), verdict)
        self.assertEqual(seen, ["C:/a/b.jpg"])

    def test_a_reader_that_blows_up_is_not_hidden_here_the_board_turns_it_into_a_fixed_sentence(self):
        def judge(_path):
            raise RuntimeError(MARKER)
        board = pv.PhotoBoard(photo_adapter.ServicePhotoProvider(judge=judge))
        self.assertEqual(board.add_paths(["C:/a/b.jpg"]), (0, 1))
        shown = repr(board.rejected) + str(board.view()) + str(board.card())
        self.assertNotIn(MARKER, shown)
        self.assertEqual(board.rejected[0].reason, R.T["img_local_unreadable"])


class CheckTest(TempPhotos):
    def test_check_reports_each_file_in_the_list_order_with_size_and_format_and_never_a_path(self):
        good, other = self.make("one.jpg"), self.make("two.png")
        gone = str(self.folder / "three.webp")
        provider = photo_adapter.ServicePhotoProvider(probe=probe_of("jpeg", 4000, 3000))
        results = provider.check(self.manifest_of(good, gone, other))
        self.assertEqual([item.photo_id for item in results], ["p001", "p002", "p003"])
        self.assertEqual([item.state for item in results], [R.OK, "missing", R.OK])
        self.assertTrue(all(isinstance(item, pv.FileState) for item in results))
        first = results[0]
        self.assertEqual((first.width, first.height, first.format, first.verified, first.ok), (4000, 3000, "jpeg", True, True))
        self.assertEqual(results[1].message, R.T["img_local_missing"])
        self.assertFalse(results[1].ok)
        shown = repr(results) + "".join(item.message + item.warning for item in results)
        self.assertNotIn(MARKER, shown)
        self.assertNotIn(str(self.folder), shown)

    def test_the_big_png_rule_is_decided_by_the_pixels_the_reader_reports_and_only_for_png(self):
        path = self.make("big.png")
        manifest = self.manifest_of(path)
        for fmt, width, height, blocked in (("png", 10_000, 10_000, False), ("png", 10_001, 10_000, True), ("png", 12_001, 12_001, True), ("jpeg", 12_001, 12_001, False), ("webp", 12_001, 12_001, False)):
            results = photo_adapter.ServicePhotoProvider(probe=probe_of(fmt, width, height)).check(manifest)
            self.assertEqual(results[0].state, R.OK, (fmt, width, height))
            self.assertEqual(results[0].preview_blocked, blocked, (fmt, width, height))
        warned = photo_adapter.ServicePhotoProvider(probe=probe_of("png", 12_001, 12_001)).check(manifest)
        self.assertEqual(warned[0].warning, R.T["img_local_long_side"], "긴 변 경고는 그대로 이어진다")

    def test_a_reader_that_says_not_an_image_or_blows_up_marks_that_file_only(self):
        fake, fine = self.make("fake.jpg", b"not really"), self.make("fine.jpg")

        def probe(path):
            return R.Probe(False) if Path(path).name == "fake.jpg" else R.Probe(True, "jpeg", 10, 10)
        results = photo_adapter.ServicePhotoProvider(probe=probe).check(self.manifest_of(fake, fine))
        self.assertEqual([item.state for item in results], [R.NOT_IMAGE, R.OK])

        def boom(_path):
            raise RuntimeError(MARKER)
        broken = photo_adapter.ServicePhotoProvider(probe=boom).check(self.manifest_of(fine))
        self.assertEqual(broken[0].state, R.UNREADABLE)
        self.assertNotIn(MARKER, repr(broken) + broken[0].message)

    def test_a_file_named_jpg_that_is_really_another_format_is_unsupported(self):
        path = self.make("really_gif.jpg")
        results = photo_adapter.ServicePhotoProvider(probe=probe_of("gif", 10, 10)).check(self.manifest_of(path))
        self.assertEqual(results[0].state, R.UNSUPPORTED)
        self.assertEqual(results[0].message, R.T["img_local_unsupported"])

    def test_an_empty_list_is_an_empty_result(self):
        self.assertEqual(photo_adapter.ServicePhotoProvider(probe=probe_of()).check(pm.empty_manifest()), ())


class BoardWithRealFilesTest(TempPhotos):
    def provider(self, probe=None):
        seen = probe or probe_of("jpeg", 800, 600)
        return photo_adapter.ServicePhotoProvider(judge=lambda path: R.judge(path, seen), probe=seen)

    def test_add_then_lose_the_file_then_find_it_again(self):
        first, second = self.make("first.jpg"), self.make("second.jpg")
        board = pv.PhotoBoard(self.provider())
        self.assertEqual(board.add_paths([first, second, str(self.folder / "missing.jpg"), self.make("odd.gif")]), (2, 2))
        reasons = {item.name: item.reason for item in board.rejected}
        self.assertEqual(set(reasons), {"missing.jpg", "odd.gif"})
        self.assertEqual(reasons["odd.gif"], "지원하지 않는 형식이에요. JPG·PNG·WebP 사진만 쓸 수 있어요")
        self.assertEqual(reasons["missing.jpg"], R.T["img_local_missing"])
        self.assertEqual([row["file"]["badge"] for row in board.view()["rows"]], ["파일 있음 · 800×600", "파일 있음 · 800×600"])
        board.confirm("p001", True)
        os.remove(first)                                                               # 사용자가 파일을 지웠다(시험이 만든 임시 파일)
        board.open()
        rows = board.view()["rows"]
        self.assertEqual((rows[0]["file"]["state"], rows[0]["file"]["badge"], rows[0]["file"]["relink"]), ("missing", "파일 없음", True))
        self.assertEqual(rows[1]["file"]["state"], R.OK)
        self.assertTrue(board.photo("p001").confirmed_by_user, "파일이 없어져도 사용자가 한 확인은 그대로 둔다(고치기 전까지)")
        replacement = self.make("replacement.jpg")
        self.assertEqual(board.relink("p001", replacement), "ok")
        self.assertFalse(board.photo("p001").confirmed_by_user, "다른 파일로 이어 붙이면 확인이 풀린다")
        self.assertEqual(board.view()["rows"][0]["file"]["state"], R.OK)
        self.assertEqual(board.view()["rows"][0]["file_name"], "replacement.jpg")
        shown = str(board.view()) + str(board.card()) + repr(board.rejected)
        self.assertNotIn(str(self.folder), shown)
        self.assertNotIn(MARKER, shown)

    def test_closing_and_reopening_reads_the_files_again_without_changing_anything(self):
        path = self.make("only.jpg")
        board = pv.PhotoBoard(self.provider())
        board.add_paths([path])
        before = board.manifest
        board.open()
        board.close()
        board.open()
        self.assertEqual(board.manifest, before)
        self.assertEqual(Path(path).read_bytes(), b"x", "원본은 그대로")
        self.assertEqual(sorted(item.name for item in self.folder.iterdir()), ["only.jpg"], "사진 옆에 아무 파일도 만들지 않는다")


if __name__ == "__main__":
    unittest.main()
