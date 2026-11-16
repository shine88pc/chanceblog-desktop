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


class InspectBeforeReadTest(TempPhotos):
    """검증 S T-1 — 실제 공급자는 사진을 넣을 때·다시 찾을 때 이미지 읽기를 부르기 전에 서비스의 `lstat` 점검(목록 점검과 같은 코드)을 거친다. 걸린 파일은 읽기 도구를 **한 번도 부르지 않는다**."""

    def setUp(self):
        super().setUp()
        self.reads = []

        def judge(path):
            self.reads.append(path)
            return R.Verdict(R.OK, "", "", 640, 480, "jpeg")
        self.board = pv.PhotoBoard(photo_adapter.ServicePhotoProvider(judge=judge, probe=probe_of()))

    @staticmethod
    def helpers():
        import test_service_photo_manifest as tsm                                      # 모듈만 가져온다(시험 모음 클래스를 이 모듈에 들이지 않는다)
        return tsm.LinkAndCloudTest, tsm.svc

    def test_each_cloud_bit_and_each_link_tag_and_a_folder_and_a_missing_file_are_refused_without_a_read(self):
        helpers, svc = self.helpers()
        photo = self.make("a.jpg")
        cases = {"OFFLINE": helpers.info("file", helpers.CLOUD_BITS["OFFLINE"]), "RECALL_ON_OPEN": helpers.info("file", helpers.CLOUD_BITS["RECALL_ON_OPEN"]),
                 "RECALL_ON_DATA_ACCESS": helpers.info("file", helpers.CLOUD_BITS["RECALL_ON_DATA_ACCESS"]), "symlink": helpers.info("file", helpers.REPARSE, helpers.NAME_TAGS["symlink"]),
                 "mount_point": helpers.info("file", helpers.REPARSE, helpers.NAME_TAGS["mount_point"]), "folder": helpers.info("dir", 0x10)}
        expected = {"OFFLINE": svc._C_CLOUD, "RECALL_ON_OPEN": svc._C_CLOUD, "RECALL_ON_DATA_ACCESS": svc._C_CLOUD, "symlink": svc._C_LINK, "mount_point": svc._C_LINK, "folder": svc._C_NOT_FILE}
        for label, info in cases.items():
            with self.subTest(case=label):
                with helpers.fake_lstat({Path(photo): info}):
                    self.assertEqual(self.board.add_paths([photo]), (0, 1))
                self.assertEqual(self.reads, [], "이미지 읽기를 부르지 않았다")
                self.assertEqual(self.board.rejected[0].reason, expected[label])
                self.assertEqual(self.board.count, 0)
        self.assertEqual(self.board.add_paths([str(self.folder / "nothing.jpg")]), (0, 1))
        self.assertEqual((self.reads, self.board.rejected[0].reason), ([], R.T[R.MESSAGES[R.MISSING]]), "없는 파일도 읽지 않는다")

    def test_a_folder_on_the_path_that_is_a_link_refuses_every_photo_below_it_without_a_read(self):
        helpers, svc = self.helpers()
        sub = self.folder / "sub"
        sub.mkdir()
        photo = str(sub / "a.jpg")
        (sub / "a.jpg").write_bytes(b"x")
        for tag in helpers.NAME_TAGS.values():
            with helpers.fake_lstat({sub: helpers.info("dir", helpers.REPARSE | 0x10, tag)}):
                self.assertEqual(self.board.add_paths([photo]), (0, 1))
            self.assertEqual((self.reads, self.board.rejected[0].reason), ([], svc._C_LINK))

    def test_a_normal_file_is_read_exactly_once_and_added(self):
        photo = self.make("a.jpg")
        self.assertEqual(self.board.add_paths([photo]), (1, 0))
        self.assertEqual(self.reads, [photo])

    def test_relinking_to_a_refused_file_is_refused_without_a_read_and_a_normal_file_still_relinks(self):
        helpers, svc = self.helpers()
        first, second, third = self.make("a.jpg"), self.make("b.jpg"), self.make("c.jpg")
        self.board.add_paths([first])
        self.reads.clear()
        with helpers.fake_lstat({Path(second): helpers.info("file", helpers.CLOUD_BITS["RECALL_ON_DATA_ACCESS"])}):
            self.assertEqual(self.board.relink("p001", second), "refused")
        self.assertEqual((self.reads, self.board.photo("p001").local_path), ([], first))
        with helpers.fake_lstat({Path(second): helpers.info("file", helpers.REPARSE, helpers.NAME_TAGS["symlink"])}):
            self.assertEqual(self.board.relink("p001", second), "refused")
        self.assertEqual(self.reads, [])
        self.assertEqual(self.board.relink("p001", third), "ok")
        self.assertEqual((self.reads, self.board.photo("p001").local_path), ([third], third))

    def test_a_real_junction_and_a_real_symbolic_link_are_refused_without_a_read_and_the_plain_file_is_added(self):
        real = self.folder / "real"
        real.mkdir()
        (real / "a.jpg").write_bytes(b"x")
        plain = self.make("plain.jpg")
        try:
            import _winapi
            _winapi.CreateJunction(str(real), str(self.folder / "via"))
            junction = str(self.folder / "via" / "a.jpg")
        except (ImportError, AttributeError, OSError):
            junction = None
        symlink = self.folder / "link.jpg"
        try:
            os.symlink(plain, symlink)
        except (OSError, NotImplementedError, AttributeError):
            symlink = None
        if junction is None and symlink is None:
            self.skipTest("이 환경에서는 정션도 심볼릭 링크도 만들 수 없다")
        chosen = [item for item in (junction, str(symlink) if symlink else None, plain) if item]
        added, refused = self.board.add_paths(chosen)
        self.assertEqual((added, refused), (1, len(chosen) - 1))
        self.assertEqual(self.reads, [plain], "정상 사진만 읽었다")
        self.assertEqual({item.reason for item in self.board.rejected}, {self.helpers()[1]._C_LINK})

    def test_the_light_check_is_the_same_code_the_list_check_uses(self):
        helpers, svc = self.helpers()
        photo = self.make("a.jpg")
        manifest = self.manifest_of(photo)
        for info in (None, helpers.info("file", helpers.CLOUD_BITS["OFFLINE"]), helpers.info("file", helpers.REPARSE, helpers.NAME_TAGS["symlink"]), helpers.info("dir", 0x10)):
            with helpers.fake_lstat({Path(photo): info} if info is not None else {}):
                state, message = svc.inspect_photo(photo)
                result = svc.check_files(manifest)[0]
            self.assertEqual((state, message), (result.state, result.message if state != "ok" else ""))
        self.assertEqual(svc.inspect_photo(str(self.folder / "missing.jpg"))[0], "missing")
        for odd in ("", None, 7, b"x"):
            self.assertEqual(svc.inspect_photo(odd)[0], "missing", "글이 아니거나 빈 글은 없는 것으로 본다")

    def test_the_adapter_hands_the_check_to_a_swapped_in_function_and_to_the_service_by_default(self):
        seen = []
        provider = photo_adapter.ServicePhotoProvider(inspect=lambda path: seen.append(path) or ("ok", ""))
        self.assertEqual(provider.inspect("C:/a/b.jpg"), ("ok", ""))
        self.assertEqual(seen, ["C:/a/b.jpg"])
        photo = self.make("a.jpg")
        self.assertEqual(photo_adapter.ServicePhotoProvider().inspect(photo), ("ok", ""))
        self.assertEqual(photo_adapter.ServicePhotoProvider().inspect(str(self.folder / "x.jpg"))[0], "missing")


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
        board = pv.PhotoBoard(photo_adapter.ServicePhotoProvider(judge=judge, inspect=lambda path: ("ok", "")))
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
        for fmt, width, height, blocked in (("png", 6_000, 10_000, False), ("png", 6_001, 10_000, True), ("png", 12_001, 12_001, True), ("jpeg", 12_001, 12_001, False), ("webp", 12_001, 12_001, False)):
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
