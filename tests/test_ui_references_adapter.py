"""참고 글 보관함의 어댑터(`ui/references_adapter.py`, 결정 D-490) 시험 — 진짜 서비스를 임시 데이터 폴더에서 돌린다(네트워크·실제 시크릿 없음, PySide6 없음). 어댑터가 서비스를 화면이 아는 모양으로 바꾸고,
거절을 고정 문장으로만 알리며(경로·번호·글은 없다), 화면 규칙(`ReferenceLibrary`)과 이어져 한 바퀴(올리기·열기·고치기·지우기)가 도는지 본다."""
import ast
import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import service_support as ss  # noqa: E402
from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.service import context as context_module  # noqa: E402
from chanceblog_desktop.ui import references_adapter as adapter  # noqa: E402
from chanceblog_desktop.ui.core import references_view as rv  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

SOURCE = ROOT / "src" / "chanceblog_desktop" / "ui" / "references_adapter.py"
MARK_TITLE, MARK_BODY = "UNIQ-TITLE-ad5k-제목", "UNIQ-BODY-ad7m-본문"


class AdapterCase(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="refs-adapter-")
        self.addCleanup(holder.cleanup)
        self.tmp = Path(os.path.realpath(holder.name))
        self.ctx = ss.make_ctx(self.tmp, clock=ss.Clock(), repo="")
        self.provider = adapter.ServiceReferencesProvider(None, context_factory=lambda data_dir=None: self.ctx)


class ProviderTest(AdapterCase):
    def test_the_provider_round_trips_through_the_real_service(self):
        row = self.provider.add("첫 글", "첫 본문")
        self.assertEqual((row.title, row.chars), ("첫 글", 4))
        listing = self.provider.list_rows()
        self.assertEqual([item.ref_id for item in listing.rows], [row.ref_id])
        opened = self.provider.open(row.ref_id)
        self.assertEqual((opened.title, opened.body), ("첫 글", "첫 본문"))
        saved = self.provider.save(row.ref_id, "고친 글", "고친 본문 입니다")
        self.assertEqual((saved.title, saved.chars), ("고친 글", 9))
        self.provider.delete(row.ref_id)
        self.assertEqual(self.provider.list_rows().rows, ())

    def test_add_file_reads_with_the_read_base_rules_and_reports_cp949(self):
        path = self.tmp / "옛 글.txt"
        path.write_bytes("옛 메모장 글입니다".encode("cp949"))
        row, cp949 = self.provider.add_file(str(path), "")
        self.assertEqual((row.title, cp949), ("옛 글", True))
        path.write_bytes("새 글입니다".encode("utf-8"))
        row2, cp949 = self.provider.add_file(path, "내 제목")
        self.assertEqual((row2.title, cp949), ("내 제목", False))

    def test_refusals_are_fixed_sentences_without_path_number_or_text(self):
        bad = self.tmp / (MARK_TITLE + ".docx")
        bad.write_text(MARK_BODY, encoding="utf-8")
        cases = (lambda: self.provider.add("", MARK_BODY), lambda: self.provider.add(MARK_TITLE + "가" * 80, MARK_BODY), lambda: self.provider.open("zzzzzzzz"), lambda: self.provider.open("../" + MARK_TITLE),
                 lambda: self.provider.save("zzzzzzzz", MARK_TITLE, MARK_BODY), lambda: self.provider.delete("zzzzzzzz"), lambda: self.provider.add_file(str(bad), MARK_TITLE))
        for call in cases:
            try:
                call()
            except rv.ReferencesRefusal as refusal:
                shown = refusal.message + repr(refusal) + repr(refusal.args)
                for marker in (MARK_TITLE, MARK_BODY, "zzzzzzzz", str(self.tmp), "내 글"):
                    self.assertNotIn(marker, shown)
                self.assertIsNone(refusal.__context__)
                self.assertIsNone(refusal.__cause__)
                self.assertTrue(refusal.message)
            else:
                self.fail("거절되지 않았다")

    def refusal_of(self, call):
        with self.assertRaises(rv.ReferencesRefusal) as caught:
            call()
        return caught.exception.message

    def test_the_vault_refusals_are_one_easy_sentence_not_the_stiff_common_one(self):
        """검증자 Q-08 — 보관함이 직접 거절한 것은 대화상자 나머지와 같은 해요체 한 문장이다('다음 칸의 값이 올바르지 않습니다: 「…」' 가 아니다)."""
        self.assertEqual(self.refusal_of(lambda: self.provider.add("", "본문")), "제목을 적어 주세요.")
        self.assertEqual(self.refusal_of(lambda: self.provider.add("가" * 81, "본문")), "제목은 80자까지만 적을 수 있어요.")
        self.assertEqual(self.refusal_of(lambda: self.provider.add("제목", "   ")), self.refusal_of(lambda: self.provider.add("제목", "")))
        for sentence in (self.refusal_of(lambda: self.provider.add("", "본문")), self.refusal_of(lambda: self.provider.add("제목", "x" * 100001))):
            self.assertNotIn("다음 칸의 값이", sentence)
            self.assertNotIn("「", sentence)
            self.assertNotIn("습니다", sentence)
            self.assertTrue(sentence.endswith("."))
        full = "".join(self.provider.add(f"글 {number}", "본문") and "" for number in range(50))
        self.assertEqual(full, "")
        self.assertEqual(self.refusal_of(lambda: self.provider.add("쉰한째", "본문")), "참고 글은 50개까지만 보관할 수 있어요. 쓰지 않는 글을 지운 뒤 다시 올려 주세요.")

    def test_a_secret_shape_refusal_names_only_the_place_and_the_kind_in_one_easy_sentence(self):
        sentence = self.refusal_of(lambda: self.provider.add("제목", "첫 줄\n" + ss.KEY + "\n끝"))
        self.assertIn("그 부분을 지운 뒤 다시 올려 주세요", sentence)
        self.assertIn("본문", sentence)
        self.assertNotIn(ss.KEY, sentence)
        self.assertNotIn("다음 칸의 값이", sentence)
        self.assertTrue(sentence.endswith("."))

    def test_sentences_of_other_errors_are_unchanged(self):
        """보관함이 쓰지 않은 오류 — 다른 곳의 CONTENT_INVALID(항목이 보관함 것이 아님)·쓰기 실패·못 찾음 — 는 앱 공통 문장 그대로다(앱 전체의 공통 문장은 건드리지 않았다)."""
        other = AppError("CONTENT_INVALID", {"항목": "다른 곳의 칸"}, detail="세부 " + MARK_BODY)
        self.assertEqual(adapter.sentence_of(other), other.rendered().message)
        self.assertIn("다음 칸의 값이", adapter.sentence_of(other))
        self.assertNotIn(MARK_BODY, adapter.sentence_of(other))
        missing = AppError("CONTENT_NOT_FOUND", {"항목": "없는 참고 글"}, detail="없음")
        self.assertEqual(adapter.sentence_of(missing), missing.rendered().message)
        failed = AppError("FILE_WRITE_FAILED", {"경로": "참고 글 보관함 폴더"}, detail="x")
        self.assertEqual(adapter.sentence_of(failed), failed.rendered().message)
        self.assertEqual(adapter.sentence_of(failed, T["ref_fail_delete"]), T["ref_fail_delete"])
        self.assertEqual(adapter.sentence_of(AppError("UNEXPECTED_ERROR", {}, detail="x")), T["ref_fail_other"])

    def test_the_reason_is_taken_only_when_the_item_starts_with_the_vault_subject(self):
        from chanceblog_desktop.service import references as service
        tricky = AppError("CONTENT_INVALID", {"항목": "다른 곳 — " + service.SUBJECT + " — 속임수"}, detail="x")
        self.assertEqual(adapter.sentence_of(tricky), tricky.rendered().message)
        mine = AppError("CONTENT_INVALID", {"항목": f"{service.SUBJECT} — 제목을 적어 주세요"}, detail="x")
        self.assertEqual(adapter.sentence_of(mine), "제목을 적어 주세요.")
        self.assertEqual(adapter.sentence_of(AppError("CONTENT_NOT_FOUND", {"항목": f"{service.SUBJECT} — 가짜"}, detail="x")), AppError("CONTENT_NOT_FOUND", {"항목": f"{service.SUBJECT} — 가짜"}, detail="x").rendered().message,
                         "CONTENT_INVALID 가 아닌 오류의 항목은 이유로 쓰지 않는다")

    def test_a_failed_delete_has_its_own_sentence_and_a_failed_save_keeps_the_service_sentence(self):
        row = self.provider.add("지울 글", "지울 본문")
        with mock.patch.object(Path, "unlink", side_effect=PermissionError(errno.EACCES, "접근 거부 " + MARK_BODY, str(self.tmp / MARK_BODY))):
            with self.assertRaises(rv.ReferencesRefusal) as caught:
                self.provider.delete(row.ref_id)
        self.assertEqual(caught.exception.message, T["ref_fail_delete"])
        self.assertNotIn(MARK_BODY, caught.exception.message)
        with mock.patch.object(context_module.os, "replace", side_effect=OSError(errno.EIO, "I/O 오류 " + MARK_BODY, str(self.tmp / MARK_BODY))):
            with self.assertRaises(rv.ReferencesRefusal) as saving:
                self.provider.save(row.ref_id, "고친 제목", "고친 본문")
        self.assertIn("참고 글 보관함 폴더", saving.exception.message)
        self.assertNotIn("저장하지 못했습니다", T["ref_fail_delete"])
        self.assertNotIn(MARK_BODY, saving.exception.message)
        self.assertEqual(self.provider.open(row.ref_id).body, "지울 본문", "실패한 지우기·저장은 글을 그대로 둔다")

    def test_the_folder_text_is_the_vault_folder_and_nothing_is_created_by_asking(self):
        before = sorted(path.name for path in self.tmp.rglob("*"))
        text = self.provider.folder_text()
        self.assertEqual(Path(text), self.ctx.workspace.root / "references")
        self.assertEqual(sorted(path.name for path in self.tmp.rglob("*")), before)

    def test_an_unusable_data_folder_gives_a_fixed_sentence_not_an_error(self):
        def refusing(data_dir=None):
            raise AppError("DATA_DIR_UNSAFE", {"경로": MARK_BODY}, detail=MARK_BODY)

        provider = adapter.ServiceReferencesProvider(None, context_factory=refusing)
        self.assertEqual(provider.folder_text(), T["ref_fail_folder"])
        with self.assertRaises(rv.ReferencesRefusal) as caught:
            provider.list_rows()
        self.assertEqual(caught.exception.message, T["ref_fail_folder"])
        for code in ("SETTINGS_INVALID", "UNEXPECTED_ERROR", "STORE_LOCKED"):
            self.assertEqual(adapter.sentence_of(AppError(code, {"파일": MARK_BODY}, detail=MARK_BODY)), T["ref_fail_other"], code)
        for code in sorted(adapter.SERVICE_CODES):
            self.assertIn(code, CATALOG)

    def test_opening_the_provider_creates_nothing(self):
        before = sorted(path.name for path in self.tmp.rglob("*"))
        adapter.ServiceReferencesProvider(None, context_factory=lambda data_dir=None: self.ctx)
        self.assertEqual(sorted(path.name for path in self.tmp.rglob("*")), before)


class WithTheScreenRulesTest(AdapterCase):
    def test_the_whole_screen_flow_works_on_the_real_service(self):
        library = rv.ReferenceLibrary(self.provider)
        self.assertEqual(library.open(), "loaded")
        self.assertEqual(library.view()["list"]["empty"], "아직 보관한 글이 없어요. 아래에 글을 붙여 넣어 저장하거나 파일에서 올려 주세요.")
        self.assertEqual(library.save("화면에서 올린 글", "화면에서 올린 본문입니다"), "saved")
        ref_id = library.current
        self.assertEqual(len(library.view()["list"]["rows"]), 1)
        library.edited("화면에서 고친 글", "화면에서 고친 본문입니다")
        self.assertEqual(library.save("화면에서 고친 글", "화면에서 고친 본문입니다"), "saved")
        self.assertEqual(self.provider.open(ref_id).title, "화면에서 고친 글")
        self.assertEqual(library.ask_delete(), "step1")
        self.assertEqual(library.advance_delete(), "step2")
        self.assertEqual(library.advance_delete(), "deleted")
        self.assertEqual(library.view()["list"]["rows"], [])
        again = rv.ReferenceLibrary(adapter.ServiceReferencesProvider(None, context_factory=lambda data_dir=None: self.ctx))
        again.open()
        self.assertEqual(again.view()["list"]["rows"], [], "지운 글은 다시 열어도 없다")

    def test_a_post_saved_in_one_session_is_listed_in_the_next(self):
        first = rv.ReferenceLibrary(self.provider)
        first.open()
        first.save("남는 글", "프로그램을 닫아도 남는 본문")
        first.close()
        second = rv.ReferenceLibrary(adapter.ServiceReferencesProvider(None, context_factory=lambda data_dir=None: self.ctx))
        second.open()
        self.assertEqual([row["label"].split(" · ")[0] for row in second.view()["list"]["rows"]], ["남는 글"])


class SourceRulesTest(unittest.TestCase):
    def test_the_adapter_has_no_file_network_or_qt_calls(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        banned = {"PySide6", "os", "pathlib", "socket", "subprocess", "urllib", "http", "logging", "tempfile", "shutil", "json", "sqlite3"}
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            for name in names:
                self.assertNotIn(name.split(".")[0], banned, name)
        called = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertFalse(called & {"print", "open", "eval", "exec"})
        self.assertFalse({name for name in called if name.split(".")[-1] in ("unlink", "write_text", "write_bytes", "mkdir", "rmdir", "replace", "rename")})
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn(chr(0x7E), text)
        self.assertNotIn("http", text)

    def test_every_error_is_turned_into_a_fixed_sentence_after_clearing_the_trace(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("error.__traceback__ = None", text)
        self.assertEqual(text.count("except AppError as error:"), 2)


if __name__ == "__main__":
    unittest.main()
