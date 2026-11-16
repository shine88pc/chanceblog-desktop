"""참고 글 보관함(`service/references.py` — 화면 없음, 결정 D-489) 시험. **전부 임시 폴더**(이 PC 의 실제 데이터 폴더는 읽지도 쓰지도 않는다). 네트워크·실제 시크릿 없이 돈다.

지키는 것:
  1) 한도 — 보관 개수 50(51번째는 거절)·제목 1–80자(공백만·눈에 안 보이는 글자뿐·제어 문자는 거절)·본문 1–100,000자(`own_posts.MAX_TEXT_CHARS` 와 같은 값 — 10만 자 정확히와 +1)·파일 1MB.
  2) 경로 탈출 0 — 글 번호는 앱이 만든 `[a-z0-9]{8}` 이고 파일 이름은 `ref-<번호>.json` 뿐이다. 사용자가 준 글자(번호·제목·본문·파일 이름)는 어떤 경우에도 경로가 되지 않는다(`../`·구분자·NUL·줄 바꿈·전각 글자·대문자·긴 글).
  3) 원자적 저장 — 이름 바꾸기·디스크 쓰기가 실패해도 옛 파일이 그대로이고 임시 파일이 남지 않으며 오류에 경로가 없다.
  4) 삭제 정확성 — 확인이 있어야 하고 번호가 정한 파일 하나만 지운다(다른 글·다른 파일·폴더·바깥 파일은 그대로, 링크·폴더는 거절).
  5) 깨진 파일 건너뜀 — 목록은 읽을 수 없는 파일을 빼고 개수만 알린다(앱을 멈추지 않고 깨진 파일을 고치지 않는다).
  6) 글·제목·경로가 오류·로그·예외·호출 흔적에 되풀이되지 않는다.
  7) 소스 규칙 — 파일 쓰기는 `write_json` 과 `delete_reference` 의 `unlink` 뿐, 네트워크·하위 프로세스·표준 출력 0.
CI 는 윈도·리눅스 × 3.10·3.12 네 칸이다 — 운영체제에 따라 다른 시험은 `skipUnless`/`skipIf` 와 이유를 적었다.
"""
import ast
import contextlib
import dataclasses
import errno
import functools
import io
import os
import re
import secrets
import stat
import sys
import tempfile
import traceback
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import service_support as ss  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import context as context_module  # noqa: E402
from chanceblog_desktop.service import own_posts  # noqa: E402
from chanceblog_desktop.service import references as ref  # noqa: E402

SOURCE = ROOT / "src" / "chanceblog_desktop" / "service" / "references.py"
UNIQ_TITLE, UNIQ_BODY, UNIQ_DIR = "UNIQ-TITLE-k3x9-제목", "UNIQ-BODY-m4z8-본문", "uniq-dir-q7w2n5"
BROKEN_ID = "brokenid"
UNIQ_LONG = UNIQ_BODY * 20_000
IDS = ("aaaaaaaa", "bbbbbbbb", "cccccccc", "dddddddd", "eeeeeeee")
INVISIBLE = chr(0x200B) * 3 + chr(0x2060) + chr(0xFEFF)
SAYS = {"title_empty": "제목을 적어 주세요", "title_long": "제목은 80자까지만", "title_chars": "제어 문자를 쓸 수 없어요", "full": "50개까지만 보관할 수 있어요", "id": "참고 글 번호가 올바르지 않아요",
        "broken": "보관된 글 파일이 올바르지 않아 열지 않았어요", "long": "글이 너무 길어요. 100,000자 이하만 읽어요", "empty": "읽을 글이 없어요", "form": "글자를 저장할 수 없는 모양이에요",
        "folder": "참고 글 보관함 폴더가 올바르지 않아요"}


def snapshot(root):
    """폴더 안의 모든 파일(바이트)·폴더 이름 — 앞뒤 비교로 '아무것도 바꾸지 않았다' 를 본다."""
    root = Path(root)
    files = {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}
    folders = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir())
    return files, folders


def channels(error):
    """오류가 사람이나 기록에 나갈 수 있는 모든 글(예외 글·`repr`·인자·칸·세부·기록 한 줄·렌더링 문구·행동 안내·추적 기록)."""
    shown = error.rendered()
    trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    return {"str": str(error), "repr": repr(error), "args": repr(error.args), "slots": repr(error.slots), "detail": error.detail, "log": error.log_line(), "message": shown.message,
            "action": shown.action, "trace": trace}


def holds_content(value, markers, big=2048, depth=0):
    """값(과 그 안의 목록·사전·객체 속성)에 표식 글이 있거나 `big` 보다 긴 글·바이트가 있는가."""
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


def leaking_locals(error, markers, big=2048):
    """오류의 호출 흔적이 붙든 모든 틀의 지역 변수 가운데 글을 담은 것 → ['함수.변수', …]."""
    found, trace = [], error.__traceback__
    while trace is not None:
        frame = trace.tb_frame
        for name, value in list(frame.f_locals.items()):
            if holds_content(value, markers, big):
                found.append(f"{frame.f_code.co_name}.{name}")
        trace = trace.tb_next
    return found


class RefCase(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory(prefix="refs-")
        self.addCleanup(holder.cleanup)
        self.tmp = Path(os.path.realpath(holder.name))
        self.clock = ss.Clock()
        self.ctx = ss.make_ctx(self.tmp, clock=self.clock, repo="")
        self.folder = self.ctx.workspace.root / "references"

    def put_raw(self, name, data):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def put_valid(self, ref_id, **changes):
        """손으로 만든 정상 파일(앱이 쓰는 것과 같은 칸)."""
        import json
        data = {"schema": 1, "id": ref_id, "title": "손으로 만든 글", "body": "본문입니다.", "created_at": "2026-11-15T01:00:00Z", "updated_at": "2026-11-15T01:00:00Z"}
        data.update(changes)
        return self.put_raw(f"ref-{ref_id}.json", json.dumps(data, ensure_ascii=False))

    def refused(self, call, key=None, code="CONTENT_INVALID"):
        """부른 일이 `code` 로 거절된다 — 문장에 `SAYS[key]` 가 있고 오류 객체를 돌려준다."""
        with self.assertRaises(AppError) as caught:
            call()
        error = caught.exception
        self.assertEqual(error.code, code)
        if key is not None:
            self.assertIn(SAYS[key], error.rendered().message)
        return error

    def refuse_keeping_frames(self, call):
        """거절 오류를 돌려준다. `assertRaises` 는 호출 흔적 틀을 비우므로 쓰지 않는다."""
        try:
            call()
        except AppError as error:
            return error
        self.fail("거절되지 않았다")


# ---- 1) 상수 ----------------------------------------------------------------------------------------------------------------------
class ConstantsTest(unittest.TestCase):
    def test_the_limits_are_the_agreed_values(self):
        self.assertEqual((ref.MAX_REFERENCES, ref.TITLE_MIN, ref.TITLE_MAX, ref.MAX_BODY_CHARS), (50, 1, 80, 100_000))
        self.assertEqual(ref.MAX_BODY_CHARS, own_posts.MAX_TEXT_CHARS, "본문 한도는 파일 읽기 쪽 한도와 같은 값이다")
        self.assertEqual((ref.FOLDER, ref.ID_CHARS, ref.SCHEMA), ("references", 8, 1))

    def test_a_new_id_is_eight_lowercase_letters_or_digits(self):
        seen = set()
        for _ in range(300):
            value = ref.new_id()
            self.assertRegex(value, r"\A[a-z0-9]{8}\Z")
            seen.add(value)
        self.assertGreater(len(seen), 290, "무작위 값이라 거의 겹치지 않는다")


# ---- 2) 추가·목록·열기·고치기 ------------------------------------------------------------------------------------------------------
class RoundTripTest(RefCase):
    def test_an_empty_vault_lists_nothing_and_creates_nothing(self):
        before = snapshot(self.tmp)
        listing = ref.list_references(self.ctx)
        self.assertEqual((listing.entries, listing.skipped, listing.total), ((), 0, 0))
        self.assertEqual(snapshot(self.tmp), before)
        self.assertFalse(self.folder.exists(), "읽기만 하는 길은 폴더를 만들지 않는다")

    def test_adding_writes_one_file_named_after_the_id_with_the_six_fields_in_utf8_without_bom(self):
        added = ref.add_reference(self.ctx, title="  내 첫 글  ", body="안녕하세요.\r\n두 번째 줄입니다.  \n")
        self.assertRegex(added.ref_id, r"\A[a-z0-9]{8}\Z")
        self.assertEqual(added.title, "내 첫 글", "제목은 앞뒤 공백을 걷는다")
        self.assertEqual(added.body, "안녕하세요.\n두 번째 줄입니다.  \n", "줄 끝만 LF 로 통일하고(CRLF → LF) 끝 공백·마지막 줄 바꿈은 그대로다")
        self.assertEqual(added.created_at, "2026-11-02T01:30:12Z")
        self.assertEqual(added.updated_at, added.created_at)
        files = sorted(path.name for path in self.folder.iterdir())
        self.assertEqual(files, [f"ref-{added.ref_id}.json"], "임시 파일이 남지 않고 글 하나가 파일 하나다")
        raw = (self.folder / files[0]).read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "BOM 없음")
        text = raw.decode("utf-8")
        self.assertIn("내 첫 글", text, "한글이 그대로 적힌다(\\u 로 풀리지 않는다)")
        import json
        self.assertEqual(set(json.loads(text)), {"schema", "id", "title", "body", "created_at", "updated_at"})

    def test_a_reference_survives_closing_the_program_and_is_read_by_a_new_context(self):
        added = ref.add_reference(self.ctx, title="남는 글", body="프로그램을 닫아도 남아요.")
        other = ss.make_ctx(self.tmp, clock=ss.Clock(), repo="")                      # 같은 데이터 폴더를 가리키는 새 Context(= 앱을 다시 연 것)
        listing = ref.list_references(other)
        self.assertEqual([(entry.ref_id, entry.title, entry.chars) for entry in listing.entries], [(added.ref_id, "남는 글", len("프로그램을 닫아도 남아요."))])
        self.assertEqual(ref.open_reference(other, added.ref_id), added)

    def test_the_list_is_newest_first_and_open_returns_the_whole_text(self):
        first = ref.add_reference(self.ctx, title="첫째", body="가" * 10)
        self.clock.advance(minutes=5)
        second = ref.add_reference(self.ctx, title="둘째", body="나" * 20)
        self.clock.advance(minutes=5)
        third = ref.add_reference(self.ctx, title="셋째", body="다" * 30)
        listing = ref.list_references(self.ctx)
        self.assertEqual([entry.title for entry in listing.entries], ["셋째", "둘째", "첫째"])
        self.assertEqual([entry.chars for entry in listing.entries], [30, 20, 10])
        self.assertEqual(ref.open_reference(self.ctx, second.ref_id).body, "나" * 20)
        self.clock.advance(minutes=5)
        ref.update_reference(self.ctx, first.ref_id, title="첫째", body="가" * 11)         # 고치면 맨 위로 온다
        self.assertEqual([entry.title for entry in ref.list_references(self.ctx).entries], ["첫째", "셋째", "둘째"])
        self.assertEqual(third.ref_id in {entry.ref_id for entry in ref.list_references(self.ctx).entries}, True)

    def test_updating_overwrites_title_and_body_keeps_created_at_and_moves_updated_at(self):
        added = ref.add_reference(self.ctx, title="처음", body="처음 글")
        self.clock.advance(hours=1)
        changed = ref.update_reference(self.ctx, added.ref_id, title=" 고친 제목 ", body="고친 글\n둘째 줄")
        self.assertEqual((changed.title, changed.body), ("고친 제목", "고친 글\n둘째 줄"))
        self.assertEqual(changed.created_at, added.created_at)
        self.assertEqual(changed.updated_at, "2026-11-02T02:30:12Z")
        self.assertEqual(ref.open_reference(self.ctx, added.ref_id), changed)
        self.assertEqual(len(list(self.folder.iterdir())), 1, "고쳐도 파일은 하나다")

    def test_updating_with_nothing_changed_writes_nothing(self):
        added = ref.add_reference(self.ctx, title="그대로", body="그대로 글")
        path = self.folder / f"ref-{added.ref_id}.json"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        self.clock.advance(hours=3)
        with mock.patch.object(ref, "write_json", side_effect=AssertionError("쓰면 안 된다")):
            same = ref.update_reference(self.ctx, added.ref_id, title=" 그대로 ", body="그대로 글")
        self.assertEqual(same, added)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_update_and_open_of_a_missing_reference_are_not_found_and_create_nothing(self):
        before = snapshot(self.tmp)
        self.refused(lambda: ref.open_reference(self.ctx, "zzzzzzzz"), code="CONTENT_NOT_FOUND")
        self.refused(lambda: ref.update_reference(self.ctx, "zzzzzzzz", title="제목", body="본문"), code="CONTENT_NOT_FOUND")
        self.assertEqual(snapshot(self.tmp), before)

    def test_ids_do_not_collide_the_new_id_is_drawn_again(self):
        ref.add_reference(self.ctx, title="하나", body="본문")
        taken = next(self.folder.iterdir()).name[4:12]
        with mock.patch.object(ref, "new_id", side_effect=[taken, taken, "freshid1"]):
            second = ref.add_reference(self.ctx, title="둘", body="본문")
        self.assertEqual(second.ref_id, "freshid1")
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    def test_when_no_free_id_can_be_found_nothing_is_written(self):
        ref.add_reference(self.ctx, title="하나", body="본문")
        taken = next(self.folder.iterdir()).name[4:12]
        before = snapshot(self.tmp)
        with mock.patch.object(ref, "new_id", return_value=taken):
            self.refused(lambda: ref.add_reference(self.ctx, title="둘", body="본문"))
        self.assertEqual(snapshot(self.tmp), before)

    def test_the_stored_text_keeps_everything_except_what_the_edit_box_unifies(self):
        """D-489 의 옛 문장('글자 하나도 바꾸지 않는다')은 화면 경로에서 거짓이어서(독립 검증 S-2) 고쳤다 — 통일하는 것은 CRLF·CR·U+2028·U+2029·맨 앞 BOM·NBSP 뿐이고 나머지는 그대로다."""
        body = "  앞 공백 과 끝 공백  " + chr(13) + chr(10) + chr(13) + chr(10) + chr(9) + "탭" + chr(0x200B) + "제로폭" + chr(10) + chr(10)
        added = ref.add_reference(self.ctx, title="모양 그대로", body=body)
        expected = "  앞 공백 과 끝 공백  " + chr(10) + chr(10) + chr(9) + "탭" + chr(0x200B) + "제로폭" + chr(10) + chr(10)
        self.assertEqual(ref.open_reference(self.ctx, added.ref_id).body, expected)

    def test_a_record_and_an_entry_do_not_show_the_title_or_the_text_in_their_repr(self):
        added = ref.add_reference(self.ctx, title=UNIQ_TITLE, body=UNIQ_BODY)
        entry = ref.list_references(self.ctx).entries[0]
        for shown in (repr(added), repr(entry), str(added), str(entry), repr(ref.list_references(self.ctx))):
            self.assertNotIn(UNIQ_TITLE, shown)
            self.assertNotIn(UNIQ_BODY, shown)
        self.assertEqual(dataclasses.is_dataclass(added) and added.chars, len(UNIQ_BODY))


# ---- 3) 한도 ----------------------------------------------------------------------------------------------------------------------
class TitleLimitTest(RefCase):
    def test_the_title_lengths_one_and_eighty_are_accepted_and_eighty_one_is_refused(self):
        self.assertEqual(ref.add_reference(self.ctx, title="가", body="본문").title, "가")
        self.assertEqual(len(ref.add_reference(self.ctx, title="나" * 80, body="본문").title), 80)
        self.refused(lambda: ref.add_reference(self.ctx, title="다" * 81, body="본문"), "title_long")
        self.assertEqual(len(list(self.folder.iterdir())), 2, "거절한 글은 파일을 만들지 않는다")

    def test_the_title_length_is_counted_after_trimming(self):
        self.assertEqual(len(ref.add_reference(self.ctx, title="  " + "가" * 80 + "  ", body="본문").title), 80)

    def test_an_empty_or_blank_title_is_refused(self):
        for title in ("", " ", "   \t  ", "\n", INVISIBLE, " " + INVISIBLE + " ", None, 123, b"abc", ["제목"]):
            with self.subTest(title=repr(title)[:20]):
                self.refused(lambda: ref.add_reference(self.ctx, title=title, body="본문"), "title_empty")
        self.assertFalse(self.folder.exists())

    def test_control_characters_inside_a_title_are_refused(self):
        for bad in ("줄\n바꿈", "탭\t글", "널\x00글", "벨\x07글", "줄 구분", "문단 구분", "짝 없는" + chr(0xD800)):
            with self.subTest(title=ascii(bad)):
                self.refused(lambda: ref.add_reference(self.ctx, title=bad, body="본문"), "title_chars")
        self.assertFalse(self.folder.exists())

    def test_a_title_with_path_like_text_is_only_text_never_a_path(self):
        before_outside = snapshot(self.tmp)
        added = ref.add_reference(self.ctx, title="../../escape/" + chr(92) + "x", body="본문")
        self.assertEqual(added.title, "../../escape/" + chr(92) + "x")
        self.assertEqual([path.name for path in self.folder.iterdir()], [f"ref-{added.ref_id}.json"])
        after_files, _folders = snapshot(self.tmp)
        new = sorted(set(after_files) - set(before_outside[0]))
        self.assertEqual(new, [f"data/references/ref-{added.ref_id}.json"], "새 파일은 보관함 폴더 안의 파일 하나뿐이다")


class BodyLimitTest(RefCase):
    def test_the_body_lengths_one_and_one_hundred_thousand_are_accepted_and_one_more_is_refused(self):
        self.assertEqual(ref.add_reference(self.ctx, title="하나", body="가").chars, 1)
        self.assertEqual(ref.add_reference(self.ctx, title="십만", body="나" * 100_000).chars, 100_000)
        self.refused(lambda: ref.add_reference(self.ctx, title="십만하나", body="다" * 100_001), "long")
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    def test_the_largest_possible_file_still_fits_the_file_limit_and_reads_back(self):
        """제어 문자는 JSON 에서 6바이트로 풀린다 — 가장 큰 본문도 1MB 안이다."""
        body = "가" + "\x07" * 99_999
        added = ref.add_reference(self.ctx, title="제일 큰 글", body=body)
        path = self.folder / f"ref-{added.ref_id}.json"
        self.assertLess(path.stat().st_size, ref.MAX_FILE_BYTES)
        self.assertEqual(ref.open_reference(self.ctx, added.ref_id).body, body)
        wide = ref.add_reference(self.ctx, title="넓은 글자", body="\U0001F600" * 100_000)
        self.assertLess((self.folder / f"ref-{wide.ref_id}.json").stat().st_size, ref.MAX_FILE_BYTES)

    def test_an_empty_blank_binary_or_non_text_body_is_refused(self):
        for body, key in (("", "empty"), (" \n\t ", "empty"), (INVISIBLE, "empty"), (None, "empty"), (123, "empty"), (b"abc", "empty"), ("글\x00글", None), ("글" + chr(0xD800) + "글", "form")):
            with self.subTest(body=ascii(body)[:20]):
                self.refused(lambda: ref.add_reference(self.ctx, title="제목", body=body), key)
        self.assertFalse(self.folder.exists())

    def test_update_applies_the_same_limits_and_leaves_the_old_text(self):
        added = ref.add_reference(self.ctx, title="옛 제목", body="옛 본문")
        path = self.folder / f"ref-{added.ref_id}.json"
        before = path.read_bytes()
        for title, body, key in (("새" * 81, "본문", "title_long"), ("   ", "본문", "title_empty"), ("제목", "가" * 100_001, "long"), ("제목", "", "empty"), ("제목", "x\x00", None)):
            with self.subTest(key=key):
                self.refused(lambda: ref.update_reference(self.ctx, added.ref_id, title=title, body=body), key)
                self.assertEqual(path.read_bytes(), before, "거절한 고치기는 옛 글을 그대로 둔다")
        self.assertEqual(len(ref.update_reference(self.ctx, added.ref_id, title="가" * 80, body="나" * 100_000).body), 100_000)


class CountLimitTest(RefCase):
    def test_fifty_references_fit_and_the_fifty_first_is_refused_until_one_is_deleted(self):
        ids = [ref.add_reference(self.ctx, title=f"글 {number}", body=f"본문 {number}").ref_id for number in range(50)]
        self.assertEqual(len(ref.list_references(self.ctx).entries), 50)
        before = snapshot(self.tmp)
        self.refused(lambda: ref.add_reference(self.ctx, title="쉰한째", body="본문"), "full")
        self.assertEqual(snapshot(self.tmp), before, "거절한 추가는 아무것도 쓰지 않는다")
        ref.delete_reference(self.ctx, ids[0], confirmed=True)
        self.assertEqual(ref.add_reference(self.ctx, title="다시 쉰째", body="본문").title, "다시 쉰째")
        self.assertEqual(len(ref.list_references(self.ctx).entries), 50)

    def test_updating_is_allowed_when_the_vault_is_full(self):
        ids = [ref.add_reference(self.ctx, title=f"글 {number}", body="본문").ref_id for number in range(50)]
        self.assertEqual(ref.update_reference(self.ctx, ids[7], title="고침", body="고친 본문").title, "고침")

    def test_a_broken_file_counts_toward_the_limit(self):
        for number in range(49):
            ref.add_reference(self.ctx, title=f"글 {number}", body="본문")
        self.put_raw("ref-zzzzzzzz.json", "깨진 파일")                                 # 49 + 깨진 1 = 50 → 이미 가득 찼다
        before = snapshot(self.tmp)
        self.refused(lambda: ref.add_reference(self.ctx, title="쉰한째", body="본문"), "full")
        self.assertEqual(snapshot(self.tmp), before)
        ref.delete_reference(self.ctx, "zzzzzzzz", confirmed=True)
        self.assertEqual(ref.add_reference(self.ctx, title="쉰째", body="본문").title, "쉰째")

    def test_files_that_are_not_named_like_a_reference_do_not_count(self):
        for name in ("note.txt", "ref-ABCDEFGH.json", "ref-abc.json", "ref-abcdefghi.json", "ref-abcdefgh.json.tmp", "ref-abcdefgh.JSON", "xref-abcdefgh.json"):
            self.put_raw(name, "상관없는 파일")
        for number in range(50):
            ref.add_reference(self.ctx, title=f"글 {number}", body="본문")
        self.assertEqual((len(ref.list_references(self.ctx).entries), ref.list_references(self.ctx).skipped), (50, 0))


# ---- 4) 경로 탈출 0 ----------------------------------------------------------------------------------------------------------------
class PathSafetyTest(RefCase):
    BAD_IDS = ("../aaaaaaa", "..", "../..", "./aaaaaaa", "aaaaaaa/", "aaaa/aaa", "aaaa" + chr(92) + "aaa", "..aaaaaa", "aaaaaaa.", "aaaaaaa", "aaaaaaaaa", "AAAAAAAA", "aaaaaaaA", "", " ", "aaaaaaaa ", " aaaaaaaa",
               "aaaaaaaa\n", "aaaaaaaa\x00", "aaaaaa\x00a", "\x00\x00\x00\x00\x00\x00\x00\x00", "ref-aaaaaaaa.json", "ref-aaaaaaaa", "aaaaaaaa.json", "ａａａａａａａａ", "a" * 200, "a" * 5000, "C:" + chr(92) + "x",
               "/etc/passwd", chr(0x7E) + "root", "aaaaaaaa/../bbbbbbbb", "ａ" * 8, "٠١٢٣٤٥٦٧", None, 12345678, 1.5, True, b"aaaaaaaa", ["aaaaaaaa"], ("aaaaaaaa",), {"id": "aaaaaaaa"}, object())

    def test_is_id_accepts_only_the_exact_shape(self):
        self.assertTrue(ref.is_id("abcdefgh"))
        self.assertTrue(ref.is_id("0a1b2c3d"))
        for bad in self.BAD_IDS:
            with self.subTest(bad=ascii(bad)[:30]):
                self.assertFalse(ref.is_id(bad))

    def test_open_update_and_delete_refuse_a_bad_id_without_touching_anything(self):
        ref.add_reference(self.ctx, title="지켜야 할 글", body="본문")
        (self.tmp / "outside.json").write_text("바깥 파일", encoding="utf-8")
        (self.ctx.workspace.root / "settings-like.json").write_text("{}", encoding="utf-8")
        before = snapshot(self.tmp)
        for bad in self.BAD_IDS:
            with self.subTest(bad=ascii(bad)[:30]):
                self.refused(lambda: ref.open_reference(self.ctx, bad), "id")
                self.refused(lambda: ref.update_reference(self.ctx, bad, title="제목", body="본문"), "id")
                self.refused(lambda: ref.delete_reference(self.ctx, bad, confirmed=True), "id")
        self.assertEqual(snapshot(self.tmp), before)

    def test_a_bad_id_never_reaches_the_file_system(self):
        """번호 모양이 틀리면 파일 상태 조회·열기·지우기 어느 것도 하지 않는다(경로를 만들기 전에 거절)."""
        for bad in ("../aaaaaaa", "aaaaaaaa\x00", "A" * 8, "", None):
            with self.subTest(bad=ascii(bad)):
                with mock.patch.object(ref, "_lstat", side_effect=AssertionError("조회 금지")), mock.patch.object(ref, "_file_of", side_effect=AssertionError("경로 금지")):
                    self.refused(lambda: ref.open_reference(self.ctx, bad), "id")
                    self.refused(lambda: ref.update_reference(self.ctx, bad, title="제목", body="본문"), "id")
                    self.refused(lambda: ref.delete_reference(self.ctx, bad, confirmed=True), "id")

    def test_every_path_the_service_builds_is_the_vault_folder_plus_the_exact_file_name(self):
        added = ref.add_reference(self.ctx, title="../../x", body="본문")
        self.assertEqual(ref._file_of(self.ctx, added.ref_id), self.folder / f"ref-{added.ref_id}.json")
        self.assertEqual(ref.folder_path(self.ctx), self.ctx.workspace.root / "references")
        seen = []
        real = ref.write_json
        with mock.patch.object(ref, "write_json", side_effect=lambda path, data, **kw: (seen.append(Path(path)), real(path, data, **kw))[1]):
            ref.add_reference(self.ctx, title="또 하나", body="본문")
            ref.update_reference(self.ctx, added.ref_id, title="고침", body="고친 본문")
        self.assertEqual(len(seen), 2)
        for path in seen:
            self.assertEqual(path.parent, self.folder)
            self.assertRegex(path.name, r"\Aref-[a-z0-9]{8}\.json\Z")

    def test_the_data_folder_is_resolved_the_way_the_other_services_do(self):
        from chanceblog_desktop.service.context import Workspace
        env = {"CHANCEBLOG_DESKTOP_DATA": str(self.tmp / "elsewhere")}
        workspace = Workspace.resolve(env=env)
        ctx = ss.make_ctx(self.tmp, clock=self.clock, repo="")
        ctx.workspace = workspace
        self.assertEqual(ref.folder_path(ctx), self.tmp / "elsewhere" / "references")
        ref.add_reference(ctx, title="다른 폴더", body="본문")
        self.assertEqual(len(list((self.tmp / "elsewhere" / "references").iterdir())), 1)

    def test_a_folder_that_is_a_file_or_a_link_is_refused_and_not_followed(self):
        self.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
        self.folder.write_text("폴더가 아닌 파일", encoding="utf-8")
        self.refused(lambda: ref.list_references(self.ctx), "folder")
        self.refused(lambda: ref.add_reference(self.ctx, title="제목", body="본문"), "folder")
        self.assertEqual(self.folder.read_text(encoding="utf-8"), "폴더가 아닌 파일")
        self.folder.unlink()
        target = self.tmp / "real-folder"
        target.mkdir()
        try:
            os.symlink(target, self.folder, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("이 환경에서는 폴더 링크를 만들 수 없다 — 모의 상태 정보로 규칙 자체는 아래 시험이 본다")
        self.refused(lambda: ref.list_references(self.ctx), "folder")
        self.refused(lambda: ref.add_reference(self.ctx, title="제목", body="본문"), "folder")
        self.assertEqual(list(target.iterdir()), [], "링크 너머에는 아무것도 쓰지 않는다")

    def test_a_link_like_folder_is_refused_by_the_rule_itself(self):
        self.folder.mkdir(parents=True)
        with mock.patch.object(own_posts, "_link_like", return_value=True):
            self.refused(lambda: ref.list_references(self.ctx), "folder")
            self.refused(lambda: ref.add_reference(self.ctx, title="제목", body="본문"), "folder")
        self.assertEqual(list(self.folder.iterdir()), [])


# ---- 5) 원자적 저장 ---------------------------------------------------------------------------------------------------------------
class AtomicWriteTest(RefCase):
    def setUp(self):
        super().setUp()
        self.added = ref.add_reference(self.ctx, title="옛 제목", body="옛 본문")
        self.path = self.folder / f"ref-{self.added.ref_id}.json"
        self.before = self.path.read_bytes()

    def assert_untouched(self):
        self.assertEqual(self.path.read_bytes(), self.before, "옛 파일이 그대로다")
        self.assertEqual([path.name for path in self.folder.iterdir()], [self.path.name], "임시 파일이 남지 않았다")

    def test_a_failed_rename_leaves_the_old_file_and_no_temp_file(self):
        with mock.patch.object(context_module.os, "replace", side_effect=OSError(errno.EIO, "I/O 오류")):
            error = self.refused(lambda: ref.update_reference(self.ctx, self.added.ref_id, title="새 제목", body="새 본문"), code="FILE_WRITE_FAILED")
        self.assert_untouched()
        self.assertEqual(error.slots, {"경로": "참고 글 보관함 폴더"}, "실제 경로 대신 고정 이름")

    def test_a_full_disk_is_reported_as_disk_full_and_the_old_file_stays(self):
        with mock.patch.object(context_module.os, "write", side_effect=OSError(errno.ENOSPC, "No space left")):
            error = self.refused(lambda: ref.update_reference(self.ctx, self.added.ref_id, title="새 제목", body="새 본문"), code="DISK_FULL")
        self.assert_untouched()
        self.assertNotIn(str(self.tmp), repr(channels(error)))

    def test_a_write_that_stops_halfway_never_replaces_the_old_file(self):
        real_write = os.write
        calls = []

        def half(fd, data):
            calls.append(len(data))
            real_write(fd, bytes(data)[: len(data) // 2])
            raise OSError(errno.EIO, "쓰다가 끊김")

        with mock.patch.object(context_module.os, "write", side_effect=half):
            self.refused(lambda: ref.update_reference(self.ctx, self.added.ref_id, title="새 제목", body="새 본문"), code="FILE_WRITE_FAILED")
        self.assertTrue(calls)
        self.assert_untouched()

    def test_a_failed_first_save_creates_no_file_at_all(self):
        before = snapshot(self.tmp)
        with mock.patch.object(context_module.os, "replace", side_effect=OSError(errno.EACCES, "접근 거부")):
            self.refused(lambda: ref.add_reference(self.ctx, title="새 글", body="새 본문"), code="FILE_WRITE_FAILED")
        self.assertEqual(snapshot(self.tmp), before)

    def test_the_new_text_arrives_only_by_renaming_a_finished_temp_file(self):
        renames = []
        real = os.replace

        def spy(source, target):
            renames.append((Path(source).name, Path(target).name, Path(source).read_bytes()))
            return real(source, target)

        with mock.patch.object(context_module.os, "replace", side_effect=spy):
            ref.update_reference(self.ctx, self.added.ref_id, title="새 제목", body="새 본문")
        self.assertEqual(len(renames), 1)
        source, target, data = renames[0]
        found = ref._TEMP.fullmatch(source)
        self.assertTrue(found is not None and found.group(1) == self.added.ref_id, f"임시 파일 이름이 `ref-번호.json.프로세스번호-무작위.tmp` 모양이다: {source}")
        self.assertIn(f".{os.getpid()}-", source)
        self.assertEqual(target, self.path.name)
        self.assertIn("새 본문".encode("utf-8"), data, "이름을 바꾸는 순간 임시 파일에는 새 글이 다 쓰여 있다")
        self.assertEqual(ref.open_reference(self.ctx, self.added.ref_id).body, "새 본문")

    def test_write_failures_never_repeat_the_text_title_or_path(self):
        """오류가 되풀이하면 안 되는 표식은 **무작위 토큰**이다 — 임시 데이터 폴더 이름과 OS 오류 글에 심은 토큰이 오류 문장·추적 글에 없어야 한다. (예전에는 'Users' 글자를 표식으로 썼는데 저장소가
        `C:/Users/…` 아래에 있으면 추적 글에 소스 파일 자신의 경로가 들어가 환경에 따라 빨강이었다 — 독립 검증 S-4.)"""
        body = UNIQ_BODY * 3
        token = "tok" + secrets.token_hex(6)                                                     # 이 실행에만 있는 표식 — 어떤 소스 경로·문장에도 우연히 들어 있지 않다
        folder_token = Path(self.tmp).name                                                       # 임시 데이터 폴더 이름(무작위) — 데이터 폴더 경로에 들어 있다
        os_message = "C:" + chr(92) + token + chr(92) + UNIQ_DIR + chr(92) + "x"
        with mock.patch.object(context_module.os, "replace", side_effect=OSError(errno.EIO, os_message)):
            error = self.refuse_keeping_frames(functools.partial(ref.update_reference, self.ctx, self.added.ref_id, title=UNIQ_TITLE, body=body))
        shown = channels(error)
        for name, text in shown.items():
            for marker in (UNIQ_TITLE, UNIQ_BODY, UNIQ_DIR, token, folder_token, str(self.ctx.workspace.root)):
                self.assertNotIn(marker, text, f"{name} 에 {marker} 가 있다")
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self.assertEqual(leaking_locals(error, [UNIQ_TITLE, UNIQ_BODY]), [])


# ---- 6) 삭제 ----------------------------------------------------------------------------------------------------------------------
class DeleteTest(RefCase):
    def make_two(self):
        first = ref.add_reference(self.ctx, title="첫째", body="첫째 본문")
        second = ref.add_reference(self.ctx, title="둘째", body="둘째 본문")
        return first, second

    def test_deleting_needs_the_confirmation_and_does_nothing_without_it(self):
        first, _second = self.make_two()
        before = snapshot(self.tmp)
        for bad in (False, None, 0, 1, "yes", "True", [True]):
            with self.subTest(confirmed=repr(bad)):
                self.refused(lambda: ref.delete_reference(self.ctx, first.ref_id, confirmed=bad), code="CONFIRMATION_REQUIRED")
        with self.assertRaises(TypeError):
            ref.delete_reference(self.ctx, first.ref_id)                                    # 확인에는 기본값이 없다(빠뜨리면 TypeError)
        self.assertEqual(snapshot(self.tmp), before)

    def test_it_deletes_exactly_one_file_and_nothing_else(self):
        first, second = self.make_two()
        self.put_raw("note.txt", "손으로 둔 글")
        self.put_raw("ref-ABCDEFGH.json", "대문자 이름")
        (self.folder / "sub").mkdir()
        (self.folder / "sub" / f"ref-{first.ref_id}.json").write_text("안쪽 폴더의 같은 이름", encoding="utf-8")
        (self.tmp / "outside.json").write_text("바깥", encoding="utf-8")
        before, _ = snapshot(self.tmp)
        ref.delete_reference(self.ctx, first.ref_id, confirmed=True)
        after, folders = snapshot(self.tmp)
        self.assertEqual(sorted(set(before) - set(after)), [f"data/references/ref-{first.ref_id}.json"], "사라진 파일은 정확히 하나")
        self.assertEqual({key: after[key] for key in after}, {key: before[key] for key in before if key in after}, "남은 파일의 내용은 그대로")
        self.assertIn("data/references/sub", folders)
        self.assertEqual([entry.ref_id for entry in ref.list_references(self.ctx).entries], [second.ref_id])

    def test_deleting_twice_or_a_missing_reference_is_not_found(self):
        first, _second = self.make_two()
        ref.delete_reference(self.ctx, first.ref_id, confirmed=True)
        self.refused(lambda: ref.delete_reference(self.ctx, first.ref_id, confirmed=True), code="CONTENT_NOT_FOUND")
        self.refused(lambda: ref.delete_reference(self.ctx, "zzzzzzzz", confirmed=True), code="CONTENT_NOT_FOUND")
        self.refused(lambda: ref.open_reference(self.ctx, first.ref_id), code="CONTENT_NOT_FOUND")

    def test_a_broken_file_can_be_deleted(self):
        self.put_raw("ref-qqqqqqqq.json", "깨진 파일")
        ref.delete_reference(self.ctx, "qqqqqqqq", confirmed=True)
        self.assertFalse((self.folder / "ref-qqqqqqqq.json").exists())

    def test_a_folder_with_the_file_name_is_refused_and_left_alone(self):
        (self.folder / "ref-dirdirdi.json").mkdir(parents=True)
        (self.folder / "ref-dirdirdi.json" / "keep.txt").write_text("남아야 함", encoding="utf-8")
        before = snapshot(self.tmp)
        self.refused(lambda: ref.delete_reference(self.ctx, "dirdirdi", confirmed=True), "broken")
        self.assertEqual(snapshot(self.tmp), before)

    def test_a_link_with_the_file_name_is_refused_and_its_target_stays(self):
        target = self.tmp / "target.json"
        target.write_text("링크 너머", encoding="utf-8")
        self.folder.mkdir(parents=True)
        try:
            os.symlink(target, self.folder / "ref-linklink.json")
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("이 환경에서는 링크를 만들 수 없다 — 모의 상태 정보로 규칙 자체는 아래 시험이 본다")
        self.refused(lambda: ref.delete_reference(self.ctx, "linklink", confirmed=True), "broken")
        self.assertEqual(target.read_text(encoding="utf-8"), "링크 너머")
        self.assertTrue(os.path.lexists(self.folder / "ref-linklink.json"))

    def test_a_link_like_file_is_refused_by_the_rule_itself(self):
        added = ref.add_reference(self.ctx, title="링크 모양", body="본문")
        with mock.patch.object(own_posts, "_link_like", side_effect=lambda info: not stat.S_ISDIR(info.st_mode)):      # 파일만 링크처럼 보이게(폴더는 보통 폴더 — 폴더 링크는 FolderLinkTest 가 본다)
            self.refused(lambda: ref.delete_reference(self.ctx, added.ref_id, confirmed=True), "broken")
            self.refused(lambda: ref.open_reference(self.ctx, added.ref_id), "broken")
        self.assertTrue((self.folder / f"ref-{added.ref_id}.json").exists())

    def test_the_only_unlink_is_on_the_one_file_path_of_that_id(self):
        first, _second = self.make_two()
        removed = []
        real = Path.unlink
        with mock.patch.object(Path, "unlink", autospec=True, side_effect=lambda self_, *a, **k: (removed.append(self_), real(self_, *a, **k))[1]):
            ref.delete_reference(self.ctx, first.ref_id, confirmed=True)
        self.assertEqual(removed, [self.folder / f"ref-{first.ref_id}.json"])

    def test_a_failed_delete_is_a_write_failure_without_the_path(self):
        first, _second = self.make_two()
        with mock.patch.object(Path, "unlink", side_effect=PermissionError(errno.EACCES, "접근 거부", str(self.tmp))):
            error = self.refused(lambda: ref.delete_reference(self.ctx, first.ref_id, confirmed=True), code="FILE_WRITE_FAILED")
        self.assertEqual(error.slots, {"경로": "참고 글 보관함 폴더"})
        self.assertNotIn(str(self.tmp), repr(channels(error)))
        self.assertTrue((self.folder / f"ref-{first.ref_id}.json").exists())


# ---- 7) 깨진 파일 건너뜀 -----------------------------------------------------------------------------------------------------------
class BrokenFilesTest(RefCase):
    def setUp(self):
        super().setUp()
        self.good = ref.add_reference(self.ctx, title="멀쩡한 글", body="멀쩡한 본문")

    def break_variants(self):
        """(이름 설명, 번호, 바이트) — 모두 읽을 수 없는 파일이다."""
        import json
        good = {"schema": 1, "id": "aaaaaaaa", "title": "제목", "body": "본문", "created_at": "2026-11-15T01:00:00Z", "updated_at": "2026-11-15T01:00:00Z"}

        def make(**changes):
            data = dict(good)
            data.update(changes)
            return json.dumps(data, ensure_ascii=False).encode("utf-8")

        def without(key):
            data = dict(good)
            del data[key]
            return json.dumps(data, ensure_ascii=False).encode("utf-8")

        yield "empty file", "aaaaaaaa", b""
        yield "not json", "aaaaaaaa", "이건 JSON 이 아니에요".encode("utf-8")
        yield "truncated", "aaaaaaaa", make()[:-10]
        yield "bom", "aaaaaaaa", b"\xef\xbb\xbf" + make()
        yield "utf-16", "aaaaaaaa", make().decode("utf-8").encode("utf-16")
        yield "cp949 bytes", "aaaaaaaa", make(title="가나다").decode("utf-8").encode("cp949")
        yield "list", "aaaaaaaa", b"[1, 2]"
        yield "string", "aaaaaaaa", b'"text"'
        yield "null", "aaaaaaaa", b"null"
        yield "deep", "aaaaaaaa", b"[" * 100_000 + b"]" * 100_000
        yield "schema 2", "aaaaaaaa", make(schema=2)
        yield "schema true", "aaaaaaaa", make(schema=True)
        yield "schema string", "aaaaaaaa", make(schema="1")
        yield "extra key", "aaaaaaaa", make(extra="x")
        for key in ("schema", "id", "title", "body", "created_at", "updated_at"):
            yield f"missing {key}", "aaaaaaaa", without(key)
        yield "id differs from the file name", "bbbbbbbb", make()
        yield "id wrong shape", "aaaaaaaa", make(id="AAAAAAAA")
        yield "title empty", "aaaaaaaa", make(title="")
        yield "title blank", "aaaaaaaa", make(title="   ")
        yield "title untrimmed", "aaaaaaaa", make(title=" 제목 ")
        yield "title too long", "aaaaaaaa", make(title="가" * 81)
        yield "title newline", "aaaaaaaa", make(title="줄\n바꿈")
        yield "title not str", "aaaaaaaa", make(title=5)
        yield "body empty", "aaaaaaaa", make(body="")
        yield "body blank", "aaaaaaaa", make(body="  \n ")
        yield "body too long", "aaaaaaaa", make(body="가" * 100_001)
        yield "body nul", "aaaaaaaa", make(body="글\u0000글")
        yield "body not str", "aaaaaaaa", make(body=["글"])
        yield "created bad", "aaaaaaaa", make(created_at="어제")
        yield "updated bad", "aaaaaaaa", make(updated_at="2026-11-15 01:00:00")
        yield "created newline", "aaaaaaaa", make(created_at="2026-11-15T01:00:00Z\n")
        yield "stamp not str", "aaaaaaaa", make(created_at=20261115)
        yield "over one megabyte", "aaaaaaaa", make(body="가" * 90_000) + b" " * (ref.MAX_FILE_BYTES + 5)

    def test_every_kind_of_broken_file_is_skipped_and_counted_and_the_good_one_is_listed(self):
        variants = list(self.break_variants())
        self.assertGreaterEqual(len(variants), 38)
        for label, ref_id, data in variants:                      # 변이마다 파일 하나만 두고 목록을 본다(이름의 번호는 `id` 칸과 맞거나 일부러 다르다)
            with self.subTest(label=label):
                path = self.put_raw(f"ref-{ref_id}.json", data)
                listing = ref.list_references(self.ctx)
                self.assertEqual([entry.ref_id for entry in listing.entries], [self.good.ref_id], label)
                self.assertEqual(listing.skipped, 1, label)
                self.assertEqual(listing.total, 2)
                path.unlink()
        self.assertEqual(ref.list_references(self.ctx).skipped, 0)

    def test_several_broken_files_are_all_counted_and_never_touched(self):
        for number in range(4):
            self.put_raw(f"ref-brok000{number}.json", "깨진 파일 " + str(number))
        before = snapshot(self.tmp)
        listing = ref.list_references(self.ctx)
        self.assertEqual((len(listing.entries), listing.skipped), (1, 4))
        self.assertEqual(snapshot(self.tmp), before, "목록은 깨진 파일을 고치거나 지우거나 옮기지 않는다")

    def test_opening_or_updating_a_broken_file_is_refused_and_leaves_its_bytes(self):
        path = self.put_raw("ref-brokenid.json", "깨진 파일 내용")
        before = path.read_bytes()
        self.refused(lambda: ref.open_reference(self.ctx, "brokenid"), "broken")
        self.refused(lambda: ref.update_reference(self.ctx, "brokenid", title="새 제목", body="새 본문"), "broken")
        self.assertEqual(path.read_bytes(), before, "깨진 파일은 덮어쓰지 않는다")

    def test_a_directory_or_a_link_with_a_reference_name_is_skipped(self):
        (self.folder / "ref-dirdirdi.json").mkdir()
        target = self.tmp / "t.json"
        import json
        target.write_text(json.dumps({"schema": 1, "id": "linklink", "title": "링크", "body": "링크 본문", "created_at": "2026-11-15T01:00:00Z", "updated_at": "2026-11-15T01:00:00Z"}, ensure_ascii=False), encoding="utf-8")
        made_link = True
        try:
            os.symlink(target, self.folder / "ref-linklink.json")
        except (OSError, NotImplementedError, AttributeError):
            made_link = False
        listing = ref.list_references(self.ctx)
        self.assertEqual([entry.ref_id for entry in listing.entries], [self.good.ref_id])
        self.assertEqual(listing.skipped, 2 if made_link else 1)

    def test_more_than_fifty_matching_files_only_the_first_fifty_are_read(self):
        for number in range(52):
            self.put_valid(f"x{number:07d}", title=f"손글 {number}")
        listing = ref.list_references(self.ctx)
        self.assertEqual(len(listing.entries) + listing.skipped, 53)
        self.assertLessEqual(len(listing.entries), 50)
        self.assertGreaterEqual(listing.skipped, 3)

    def test_the_file_size_check_happens_before_reading_everything(self):
        path = self.put_raw("ref-hugehuge.json", b"x" * (ref.MAX_FILE_BYTES + 100))
        read = []
        real = own_posts._read_prefix
        with mock.patch.object(own_posts, "_read_prefix", side_effect=lambda target, limit, expected: (read.append(Path(target).name), real(target, limit, expected))[1]):
            listing = ref.list_references(self.ctx)
        self.assertNotIn("ref-hugehuge.json", read, "1MB 를 넘는 파일은 열지도 않는다")
        self.assertEqual(listing.skipped, 1)
        self.assertTrue(path.exists())

    def test_a_file_that_grows_after_the_check_is_read_only_up_to_the_limit(self):
        path = self.put_raw("ref-growgrow.json", "{}")
        real = own_posts._read_prefix
        seen = []

        def spy(target, limit, expected):
            seen.append(limit)
            path.write_bytes(b"y" * (ref.MAX_FILE_BYTES * 2))
            return real(target, limit, expected)

        with mock.patch.object(own_posts, "_read_prefix", side_effect=spy):
            listing = ref.list_references(self.ctx)
        self.assertIn(ref.MAX_FILE_BYTES + 1, seen)
        self.assertEqual(listing.skipped, 1)

    def test_an_unreadable_folder_is_a_fixed_refusal(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(ref.os, "scandir", side_effect=PermissionError(errno.EACCES, "접근 거부", str(self.tmp))):
            error = self.refuse_keeping_frames(lambda: ref.list_references(self.ctx))
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertIn("읽을 수 없어요", error.rendered().message)
        self.assertNotIn(str(self.tmp), repr(channels(error)))
        self.assertIsNone(error.__context__)


# ---- 8) 파일에서 올리기 -------------------------------------------------------------------------------------------------------------
class AddFromFileTest(RefCase):
    def setUp(self):
        super().setUp()
        self.src = self.tmp / "내 글 모음"
        self.src.mkdir()

    def make_file(self, name, data):
        path = self.src / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def test_a_utf8_text_file_is_added_with_a_title_made_from_its_name(self):
        path = self.make_file("여름 휴가 후기.txt", "여름 휴가를 다녀왔어요.\r\n정말 좋았어요.")
        added = ref.add_from_file(self.ctx, path)
        self.assertEqual((added.reference.title, added.reference.body, added.encoding), ("여름 휴가 후기", "여름 휴가를 다녀왔어요.\n정말 좋았어요.", "utf-8"), "윈도 메모장의 CRLF 는 LF 로 통일되어 보관된다")
        self.assertEqual(ref.open_reference(self.ctx, added.reference.ref_id), added.reference)
        self.assertEqual(path.read_bytes(), "여름 휴가를 다녀왔어요.\r\n정말 좋았어요.".encode("utf-8"), "원본 파일은 그대로다")

    def test_a_given_title_wins_and_a_blank_one_falls_back_to_the_file_name(self):
        path = self.make_file("원본.md", "# 제목\n본문")
        self.assertEqual(ref.add_from_file(self.ctx, path, title="  내가 정한 제목 ").reference.title, "내가 정한 제목")
        self.assertEqual(ref.add_from_file(self.ctx, path, title="   ").reference.title, "원본")
        self.assertEqual(ref.add_from_file(self.ctx, str(path), title=None).reference.title, "원본")

    def test_a_cp949_file_is_read_and_reported_as_cp949(self):
        path = self.make_file("옛 메모장.txt", "옛 메모장으로 저장한 글입니다.".encode("cp949"))
        added = ref.add_from_file(self.ctx, path)
        self.assertEqual((added.encoding, added.reference.body), ("cp949", "옛 메모장으로 저장한 글입니다."))

    def test_a_title_made_from_an_awkward_file_name_is_cut_or_replaced(self):
        long_name = self.make_file("긴" * 120 + ".txt", "본문")
        self.assertEqual(ref.add_from_file(self.ctx, long_name).reference.title, "긴" * 80)
        blank = self.make_file("." + "txt", "본문")                                    # 이름이 없는 `.txt` 파일 — 확장자 없는 이름으로 읽히거나 제목이 비어도 기본 제목이다
        added = ref.add_from_file(self.ctx, blank) if blank.suffix.lower() == ".txt" else None
        if added is not None:
            self.assertTrue(ref._title_reason(added.reference.title) is None)
        self.assertEqual(ref._title_from_path(self.src / ("제목" + chr(0) + "끝.txt")), ref.DEFAULT_TITLE)
        self.assertEqual(ref._title_from_path(self.src / ("   .txt")), ref.DEFAULT_TITLE)

    def test_the_file_rules_are_the_own_posts_rules_and_nothing_is_stored_on_refusal(self):
        cases = {
            "other format": self.make_file("문서.docx", "본문"), "missing": self.src / "없는 파일.txt", "relative": "상대/경로.txt", "folder as file": self.src, "empty file": self.make_file("빈.txt", ""),
            "binary": self.make_file("이진.txt", b"abc\x00def"), "too big": self.make_file("큰.txt", b"a" * (own_posts.MAX_FILE_BYTES + 1)), "bad encoding": self.make_file("깨짐.txt", b"\xff\xfe\xfa\x80"),
            "too long": self.make_file("긴글.txt", "가" * (own_posts.MAX_TEXT_CHARS + 1)), "unc": chr(92) * 2 + "server" + chr(92) + "share" + chr(92) + "a.txt", "url": "https" + ":" + chr(47) * 2 + "host.invalid" + chr(47) + "a.txt",
            "wildcard": str(self.src / "*.txt"), "dotdot": str(self.src / ".." / "내 글 모음" / "a.txt"), "device": str(self.src / "NUL.txt"), "list": [self.src], "none": None,
        }
        for label, path in cases.items():
            with self.subTest(label=label):
                error = self.refused(lambda: ref.add_from_file(self.ctx, path))
                self.assertIn("참고 글 보관함 — ", error.slots["항목"])
        self.assertFalse(self.folder.exists(), "거절한 파일은 보관함 폴더도 만들지 않는다")

    def test_the_refusal_sentences_are_the_ones_of_the_read_base(self):
        wanted = {"문서.docx": own_posts._R_SUFFIX, "없는 파일.txt": own_posts._R_MISSING, "빈.txt": own_posts._R_EMPTY}
        self.make_file("빈.txt", "")
        self.make_file("문서.docx", "본문")
        for name, sentence in wanted.items():
            error = self.refused(lambda: ref.add_from_file(self.ctx, self.src / name))
            self.assertEqual(error.detail, sentence)

    def test_a_refused_file_never_repeats_the_path_the_file_name_or_the_text(self):
        marker_path = self.src / (UNIQ_DIR + ".docx")
        marker_path.write_text(UNIQ_BODY, encoding="utf-8")
        for path in (marker_path, self.src / (UNIQ_DIR + "-missing.txt"), str(self.src / (UNIQ_DIR + "*.txt"))):
            error = self.refuse_keeping_frames(functools.partial(ref.add_from_file, self.ctx, path))
            for name, text in channels(error).items():
                for marker in (UNIQ_DIR, UNIQ_BODY, str(self.tmp), "내 글 모음"):
                    self.assertNotIn(marker, text, f"{name} 에 {marker} 가 있다")
            self.assertIsNone(error.__cause__)
            self.assertIsNone(error.__context__)
            self.assertEqual(leaking_locals(error, [UNIQ_DIR, UNIQ_BODY]), [])

    def test_a_full_vault_refuses_a_file_too(self):
        for number in range(50):
            ref.add_reference(self.ctx, title=f"글 {number}", body="본문")
        path = self.make_file("쉰한째.txt", "본문")
        self.refused(lambda: ref.add_from_file(self.ctx, path), "full")
        self.assertEqual(len(list(self.folder.iterdir())), 50)


# ---- 9) 글·제목·경로가 새지 않는다 ------------------------------------------------------------------------------------------------------
class NoLeakTest(RefCase):
    MARKERS = [UNIQ_TITLE, UNIQ_BODY]

    def test_the_helper_does_find_a_function_that_holds_the_content(self):
        """대조: 지역 변수에 글을 쥔 채 오류를 내는 함수는 이 눈에 잡힌다 — 이것이 안 잡히면 아래 시험은 아무것도 못 지킨다."""
        def holder():
            kept = (UNIQ_BODY * 10)
            raise ValueError(len(kept))

        try:
            holder()
        except ValueError as error:
            found = leaking_locals(error, self.MARKERS)
        self.assertIn("holder.kept", found)

    def test_no_refusal_leaves_the_text_in_the_error_or_in_its_frames(self):
        added = ref.add_reference(self.ctx, title="기존 글", body="기존 본문")
        add, update = functools.partial(ref.add_reference, self.ctx), functools.partial(ref.update_reference, self.ctx)
        middle = UNIQ_TITLE[:6] + chr(10) + UNIQ_TITLE[6:]
        calls = {
            "title too long": functools.partial(add, title=UNIQ_TITLE + "가" * 80, body=UNIQ_BODY),
            "body too long": functools.partial(add, title=UNIQ_TITLE, body=UNIQ_LONG),
            "body nul": functools.partial(add, title=UNIQ_TITLE, body=UNIQ_BODY + "\x00"),
            "body surrogate": functools.partial(add, title=UNIQ_TITLE, body=UNIQ_BODY + chr(0xD800)),
            "title surrogate": functools.partial(add, title=UNIQ_TITLE + chr(0xD800), body=UNIQ_BODY),
            "title newline": functools.partial(add, title=middle, body=UNIQ_BODY),
            "update body too long": functools.partial(update, added.ref_id, title=UNIQ_TITLE, body=UNIQ_LONG),
            "update bad id": functools.partial(update, "../" + UNIQ_TITLE, title=UNIQ_TITLE, body=UNIQ_BODY),
            "update missing": functools.partial(update, "zzzzzzzz", title=UNIQ_TITLE, body=UNIQ_BODY),
            "open bad id": functools.partial(ref.open_reference, self.ctx, "../" + UNIQ_TITLE),
            "delete bad id": functools.partial(ref.delete_reference, self.ctx, "../" + UNIQ_BODY, confirmed=True),
        }
        for label, call in calls.items():
            with self.subTest(label=label):
                error = self.refuse_keeping_frames(call)
                for name, text in channels(error).items():
                    for marker in (UNIQ_TITLE, UNIQ_BODY):
                        self.assertNotIn(marker, text, f"{name} 에 {marker} 가 있다")
                self.assertIsNone(error.__cause__)
                self.assertIsNone(error.__context__)
                self.assertEqual(leaking_locals(error, [UNIQ_TITLE, UNIQ_BODY]), [], label)

    def test_a_full_vault_refusal_does_not_hold_the_text_in_its_frames(self):
        for number in range(50):
            ref.add_reference(self.ctx, title=f"글 {number}", body="본문")
        error = self.refuse_keeping_frames(functools.partial(ref.add_reference, self.ctx, title=UNIQ_TITLE, body=UNIQ_BODY))
        self.assertIn(SAYS["full"], error.rendered().message)
        self.assertEqual(leaking_locals(error, [UNIQ_TITLE, UNIQ_BODY]), [])
        self.assertNotIn(UNIQ_TITLE, repr(channels(error)))

    def test_a_broken_file_error_does_not_repeat_the_file_content_or_the_name(self):
        self.put_raw(f"ref-{BROKEN_ID}.json", UNIQ_BODY + " 깨진 JSON " + UNIQ_TITLE)
        for call in (functools.partial(ref.open_reference, self.ctx, BROKEN_ID), functools.partial(ref.update_reference, self.ctx, BROKEN_ID, title="제목", body="본문")):
            error = self.refuse_keeping_frames(call)
            for name, text in channels(error).items():
                for marker in (UNIQ_TITLE, UNIQ_BODY, BROKEN_ID, str(self.tmp)):
                    self.assertNotIn(marker, text, f"{name} 에 {marker} 가 있다")
            self.assertEqual(leaking_locals(error, [UNIQ_TITLE, UNIQ_BODY]), [])

    def test_nothing_is_printed_logged_or_sent_while_using_the_vault(self):
        out, err = io.StringIO(), io.StringIO()
        blocked = AssertionError("네트워크·하위 프로세스는 쓰지 않는다")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertNoLogs(level="DEBUG"), \
                mock.patch("socket.socket", side_effect=blocked), mock.patch("subprocess.Popen", side_effect=blocked), mock.patch("urllib.request.urlopen", side_effect=blocked):
            added = ref.add_reference(self.ctx, title=UNIQ_TITLE, body=UNIQ_BODY)
            ref.list_references(self.ctx)
            ref.open_reference(self.ctx, added.ref_id)
            ref.update_reference(self.ctx, added.ref_id, title="고침", body=UNIQ_BODY + "2")
            self.refused(lambda: ref.add_reference(self.ctx, title="", body=UNIQ_BODY))
            ref.delete_reference(self.ctx, added.ref_id, confirmed=True)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))


# ---- 9-2) 키·토큰 모양 검사 -------------------------------------------------------------------------------------------------------------
class SecretShapeTest(RefCase):
    """저장 직전에 키·토큰 모양(`security/scan.py` — 초안 저장·백업과 같은 검사기)이 있으면 아무것도 쓰지 않고 위치와 유형만 알린다(운영자 결정 2026-11-11 의 같은 원칙). 읽기는 막지 않는다."""

    def kinds(self):
        import scan_samples as S
        return [(kind, S.sample(kind)[1]) for kind in S.KINDS]

    def test_every_secret_shape_in_the_body_or_the_title_is_refused_with_only_the_place_and_kind(self):
        kinds = self.kinds()
        self.assertGreaterEqual(len(kinds), 6)
        for kind, secret in kinds:
            for where, make in (("본문", functools.partial(ref.add_reference, self.ctx, title="멀쩡한 제목", body="앞 글입니다." + chr(10) + secret + chr(10) + "뒷 글입니다.")),
                                ("제목", functools.partial(ref.add_reference, self.ctx, title="제목 " + secret, body="멀쩡한 본문"))):
                with self.subTest(kind=kind, where=where):
                    error = self.refuse_keeping_frames(make)
                    self.assertEqual(error.code, "CONTENT_INVALID")
                    message = error.rendered().message
                    self.assertIn(f"{where} ", message)
                    self.assertIn("줄에", message)
                    self.assertIn("그 부분을 지운 뒤 다시 올려 주세요", message)
                    for name, text in channels(error).items():
                        self.assertNotIn(secret, text, f"{name} 에 찾은 글이 있다")
                    self.assertEqual(leaking_locals(error, [secret]), [])
                    self.assertIsNone(error.__context__)
        self.assertFalse(self.folder.exists(), "거절한 글은 보관함 폴더도 만들지 않는다")

    def test_the_place_is_the_line_of_the_shape(self):
        error = self.refused(lambda: ref.add_reference(self.ctx, title="제목", body="하나\n둘\n셋 " + ss.KEY + "\n넷"))
        self.assertIn("본문 3번째 줄", error.rendered().message)

    def test_updating_with_a_secret_shape_is_refused_and_leaves_the_old_file(self):
        added = ref.add_reference(self.ctx, title="옛 제목", body="옛 본문")
        path = self.folder / f"ref-{added.ref_id}.json"
        before = path.read_bytes()
        self.refused(lambda: ref.update_reference(self.ctx, added.ref_id, title="옛 제목", body="새 본문 " + ss.KEY))
        self.refused(lambda: ref.update_reference(self.ctx, added.ref_id, title="새 제목 " + ss.KEY, body="옛 본문"))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual([item.name for item in self.folder.iterdir()], [path.name])

    def test_a_file_with_a_secret_shape_is_refused_and_nothing_is_stored(self):
        source = self.tmp / "내 글.txt"
        source.write_text("글입니다.\n" + ss.KEY + "\n", encoding="utf-8")
        error = self.refused(lambda: ref.add_from_file(self.ctx, source))
        self.assertNotIn(ss.KEY, repr(channels(error)))
        self.assertFalse(self.folder.exists())

    def test_reading_is_not_blocked_but_saving_it_again_is(self):
        self.put_valid("handmade", body="손으로 넣은 글 " + ss.KEY)
        self.assertEqual(len(ref.list_references(self.ctx).entries), 1)
        opened = ref.open_reference(self.ctx, "handmade")
        self.refused(lambda: ref.update_reference(self.ctx, "handmade", title=opened.title, body=opened.body))
        self.assertEqual(ref.update_reference(self.ctx, "handmade", title=opened.title, body="키를 지운 글").body, "키를 지운 글")

    def test_a_normal_post_with_long_digits_and_words_is_not_taken_for_a_secret(self):
        body = "주문 번호는 1234567890123456입니다. api 와 token 이라는 말은 그냥 낱말이에요. Bearer 는 영어 낱말이고 AKIA 로 시작하는 글자도 짧으면 괜찮아요: AKIA12."
        self.assertEqual(ref.add_reference(self.ctx, title="평범한 글", body=body).body, body)

    def test_the_scan_is_fast_enough_for_the_largest_post(self):
        import time
        body = ("가나다라마바사아자차카타파하 " * 8 + "입니다.\n") * 1000
        body = body[: ref.MAX_BODY_CHARS]
        started = time.perf_counter()
        ref.add_reference(self.ctx, title="큰 글", body=body)
        self.assertLess(time.perf_counter() - started, 2.0, "10만 자 글 한 편을 보관하는 데 걸린 시간")


# ---- 9-3) 본문 통일(S-2)·임시 파일(S-R1·S-R2)·폴더 링크(S-R3)·파일 크기 경계(S-R6)·백업 목록 문장(S-R4) — 독립 검증 S 1차의 고침 ---------------------------------------
def reference_normalize(text):
    """`normalize_body` 와 따로 짠 느린 기준 구현(한 글자씩) — 규칙 문장 그대로: CRLF·낱개 CR·U+2028·U+2029 → LF, NBSP → 보통 공백, 맨 앞 BOM 하나 제거."""
    out, index = [], 0
    while index < len(text):
        char = text[index]
        if char == chr(13):
            out.append(chr(10))
            index += 2 if text[index + 1:index + 2] == chr(10) else 1
            continue
        out.append(chr(10) if char in (chr(0x2028), chr(0x2029)) else " " if char == chr(0xA0) else char)
        index += 1
    return "".join(out).lstrip(chr(0xFEFF))                                                # 맨 앞의 BOM 은 모두(편집 칸은 하나만 떼지만 통일한 글이 편집 칸을 지나도 그대로이려면 모두 뗀다)


class BodyNormalizeTest(RefCase):
    CR, LF, LS, PS, NBSP, BOM = chr(13), chr(10), chr(0x2028), chr(0x2029), chr(0xA0), chr(0xFEFF)

    def table(self):
        cr, lf, ls, ps, nbsp, bom = self.CR, self.LF, self.LS, self.PS, self.NBSP, self.BOM
        return (
            ("가" + cr + lf + "나", "가" + lf + "나"), ("가" + cr + "나", "가" + lf + "나"), ("가" + lf + cr + "나", "가" + lf + lf + "나"), ("가" + cr + cr + lf + "나", "가" + lf + lf + "나"),
            ("가" + ls + "나", "가" + lf + "나"), ("가" + ps + "나", "가" + lf + "나"), ("가" + ls + cr + lf + "나", "가" + lf + lf + "나"), ("가나" + cr + lf, "가나" + lf),
            (bom + "가", "가"), (bom + bom + "가", "가"), (bom * 3, ""), ("가" + bom, "가" + bom), (lf + bom + "가", lf + bom + "가"), (" " + bom + "가", " " + bom + "가"), (nbsp + bom + "가", " " + bom + "가"), (bom + nbsp + "가", " 가"),
            ("가" + nbsp + "나", "가 나"), (nbsp * 3 + "가", "   가"),
        )

    def kept(self):
        """통일하지 않고 그대로 두는 글들 — 끝 공백·탭·빈 줄·보이지 않는 글자·다른 줄 구분 글자·NFD·이모지·제어 문자."""
        import unicodedata
        return ("가  " + chr(9) + "나 " + chr(10), "가" + chr(0x200B) + "나", "가" + chr(0x0B) + chr(0x0C) + chr(0x85) + "나", "가" + chr(0x1F600) + "나", unicodedata.normalize("NFD", "한글 글자"), unicodedata.normalize("NFC", "한글 글자"),
                "끝 공백  ", chr(10) * 3 + "가" + chr(10) * 3, "가" + chr(7) + "나", "가" + chr(0x3000) + "나", "가" + chr(0x2003) + "나", "가" + chr(0x202E) + "나")

    def test_the_table_of_what_is_unified(self):
        for original, expected in self.table():
            with self.subTest(original=ascii(original)):
                self.assertEqual(ref.normalize_body(original), expected)
                self.assertEqual(ref.normalize_body(expected), expected, "통일한 글을 또 통일해도 그대로다")

    def test_everything_else_is_kept_exactly(self):
        for text in self.kept():
            with self.subTest(text=ascii(text)):
                self.assertEqual(ref.normalize_body(text), text)

    def test_it_agrees_with_a_slow_reference_on_random_strings(self):
        import random
        alphabet = ["가", "나", " ", chr(9), self.CR, self.LF, self.LS, self.PS, self.NBSP, self.BOM, chr(0x200B), "a"]
        rng = random.Random(20261116)
        for _ in range(3000):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 14)))
            self.assertEqual(ref.normalize_body(text), reference_normalize(text), ascii(text))
            self.assertEqual(ref.normalize_body(ref.normalize_body(text)), ref.normalize_body(text))

    def test_what_is_stored_is_the_unified_text_and_the_file_has_no_carriage_return(self):
        original = "첫 줄" + self.CR + self.LF + "둘째" + self.NBSP + "줄" + self.LS + "셋째 줄" + self.PS + "끝 " + self.CR
        added = ref.add_reference(self.ctx, title="통일", body=original)
        expected = "첫 줄" + self.LF + "둘째 줄" + self.LF + "셋째 줄" + self.LF + "끝 " + self.LF
        self.assertEqual(added.body, expected)
        raw = (self.folder / f"ref-{added.ref_id}.json").read_text(encoding="utf-8")
        import json
        self.assertEqual(json.loads(raw)["body"], expected)
        self.assertNotIn(self.CR, json.loads(raw)["body"])
        self.assertEqual(ref.open_reference(self.ctx, added.ref_id).body, expected, "저장 뒤 다시 열어도 같다")
        self.assertEqual(ref.list_references(self.ctx).entries[0].chars, len(expected), "목록의 글자 수 = 저장한 글(= 편집 칸에 보이는 글)의 글자 수")

    def test_the_limits_count_the_stored_text_after_the_unifying(self):
        ok = "가" * 99_999 + self.CR + self.LF                                             # 날 글자 100,001 → 통일하면 100,000
        self.assertEqual(ref.add_reference(self.ctx, title="경계", body=ok).chars, 100_000)
        self.refused(lambda: ref.add_reference(self.ctx, title="넘음", body="가" * 100_000 + self.CR + self.LF), "long")   # 날 글자 100,002 → 통일해도 100,001
        self.refused(lambda: ref.add_reference(self.ctx, title="넘음", body="가" * 100_001), "long")

    def test_a_body_that_is_empty_after_the_unifying_is_refused(self):
        for body in (self.BOM, self.BOM + self.NBSP, self.NBSP * 4, self.LS + self.PS + self.CR):
            with self.subTest(body=ascii(body)):
                self.refused(lambda: ref.add_reference(self.ctx, title="빈 글", body=body), "empty")
        self.assertFalse(self.folder.exists())

    def test_a_crlf_file_is_kept_unified_and_opens_with_the_same_length_as_the_list_says(self):
        source = self.tmp / "메모장 글.txt"
        source.write_bytes(("첫 줄입니다." + self.CR + self.LF + "둘째 줄입니다." + self.CR + self.LF + self.CR + self.LF + "셋째 줄입니다." + self.CR + self.LF).encode("utf-8"))
        added = ref.add_from_file(self.ctx, source)
        expected = "첫 줄입니다." + self.LF + "둘째 줄입니다." + self.LF + self.LF + "셋째 줄입니다." + self.LF
        self.assertEqual(added.reference.body, expected)
        opened = ref.open_reference(self.ctx, added.reference.ref_id)
        self.assertEqual((opened.body, opened.chars), (expected, len(expected)))
        self.assertEqual(ref.list_references(self.ctx).entries[0].chars, len(expected))
        self.assertEqual(source.read_bytes().count(self.CR.encode()), 4, "원본 파일은 그대로다")

    def test_saving_the_same_text_again_with_other_line_ends_writes_nothing(self):
        added = ref.add_reference(self.ctx, title="그대로", body="가" + self.LF + "나")
        path = self.folder / f"ref-{added.ref_id}.json"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        self.clock.advance(hours=1)
        with mock.patch.object(ref, "write_json", side_effect=AssertionError("쓰면 안 된다")):
            same = ref.update_reference(self.ctx, added.ref_id, title="그대로", body="가" + self.CR + self.LF + "나")
        self.assertEqual(same, added)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_a_hand_made_file_with_the_old_line_ends_reads_unified_and_is_not_rewritten_until_saved_with_a_change(self):
        path = self.put_valid("legacy01", body="가" + self.CR + self.LF + "나" + self.NBSP + "다")
        before = path.read_bytes()
        listing = ref.list_references(self.ctx)
        opened = ref.open_reference(self.ctx, "legacy01")
        self.assertEqual((opened.body, listing.entries[0].chars), ("가" + self.LF + "나 다", 5))
        self.assertEqual(path.read_bytes(), before, "읽기는 파일을 바꾸지 않는다")
        with mock.patch.object(ref, "write_json", side_effect=AssertionError("쓰면 안 된다")):
            ref.update_reference(self.ctx, "legacy01", title=opened.title, body=opened.body)
        self.assertEqual(path.read_bytes(), before, "통일한 글 그대로 저장하면 바뀐 것이 없어 쓰지 않는다")
        ref.update_reference(self.ctx, "legacy01", title=opened.title, body=opened.body + "!")
        self.assertNotEqual(path.read_bytes(), before)
        import json
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["body"], "가" + self.LF + "나 다!")


class TempFileTest(RefCase):
    def test_every_save_uses_a_new_temp_name_with_the_process_number_and_never_the_fixed_one(self):
        names = []
        real = os.replace

        def spy(source, target):
            names.append(Path(source).name)
            return real(source, target)

        added = None
        with mock.patch.object(context_module.os, "replace", side_effect=spy):
            added = ref.add_reference(self.ctx, title="하나", body="본문")
            for number in range(6):
                self.clock.advance(minutes=1)
                ref.update_reference(self.ctx, added.ref_id, title="하나", body=f"본문 {number}")
        self.assertEqual(len(names), 7)
        self.assertEqual(len(set(names)), 7, "쓸 때마다 이름이 다르다")
        for name in names:
            found = ref._TEMP.fullmatch(name)
            self.assertTrue(found is not None and found.group(1) == added.ref_id, name)
            self.assertIn(f".{os.getpid()}-", name)
            self.assertNotEqual(name, f"ref-{added.ref_id}.json.tmp")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"ref-{added.ref_id}.json"], "다 쓴 뒤 임시 파일은 없다")

    def test_a_failed_write_removes_its_own_unique_temp_file(self):
        added = ref.add_reference(self.ctx, title="하나", body="본문")
        with mock.patch.object(context_module.os, "replace", side_effect=OSError(errno.EIO, "I/O 오류")):
            self.refused(lambda: ref.update_reference(self.ctx, added.ref_id, title="하나", body="고친 본문"), code="FILE_WRITE_FAILED")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"ref-{added.ref_id}.json"])

    def test_other_json_writes_keep_the_fixed_temp_name(self):
        """`unique_temp` 는 보관함만 쓴다 — 설정 같은 기존 쓰기의 임시 파일 이름은 그대로 `<이름>.tmp` 다."""
        names = []
        real = os.replace
        with mock.patch.object(context_module.os, "replace", side_effect=lambda source, target: (names.append(Path(source).name), real(source, target))[1]):
            context_module.write_json(self.tmp / "other.json", {"a": 1})
        self.assertEqual(names, ["other.json.tmp"])

    def test_two_real_processes_editing_the_same_post_never_break_or_lose_it(self):
        """독립 검증 S-R1 의 실험을 시험으로 — 고정 임시 파일 이름이면 두 프로세스가 같은 글을 150번씩 고칠 때 대부분 글 파일이 깨졌다. 지금은 쓸 때마다 다른 임시 이름이라 마지막 쓰기가 이긴다."""
        import json
        import subprocess
        added = ref.add_reference(self.ctx, title="경쟁 글", body="처음 본문")
        child = HERE / "references_race_child.py"
        for round_number in range(3):
            go = self.tmp / f"go-{round_number}"
            children = [subprocess.Popen([sys.executable, "-B", "-X", "utf8", str(child), str(ROOT / "src"), str(self.ctx.workspace.root), added.ref_id, label, "150", str(go)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         encoding="utf-8", errors="replace") for label in ("가", "나")]
            for each in children:
                self.assertEqual(each.stdout.readline().strip(), "READY", "자식이 시작하지 못했다")
            go.write_text("go", encoding="utf-8")
            reports = []
            for each in children:
                out, err = each.communicate(timeout=240)
                self.assertEqual(each.returncode, 0, err[-600:])
                reports.append(json.loads(out.strip().splitlines()[-1]))
            for report in reports:
                self.assertEqual(report["other"], [], "AppError 가 아닌 실패는 없다")
                self.assertGreater(report["ok"], 0)
            listing = ref.list_references(self.ctx)
            self.assertEqual((len(listing.entries), listing.skipped), (1, 0), f"{round_number + 1}번째 판: 글 파일이 깨지거나 사라졌다")
            final = ref.open_reference(self.ctx, added.ref_id)
            self.assertRegex(final.body, r"\A[가나]-\d+\Z")
            self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [f"ref-{added.ref_id}.json"], "임시 파일이 남지 않았다")


class LeftoverTempTest(RefCase):
    def make_leftovers(self, ref_id):
        """쓰다 프로세스가 죽어 남은 임시 파일들(새 본문이 평문으로 든다) — 옛 고정 이름과 새 이름."""
        names = (f"ref-{ref_id}.json.tmp", f"ref-{ref_id}.json.4242-abcdef12.tmp", f"ref-{ref_id}.json.7-00000000.tmp")
        for name in names:
            self.put_raw(name, "새 본문 " + UNIQ_BODY)
        return names

    def test_a_killed_write_leaves_the_old_file_and_a_temp_that_is_not_listed_and_the_delete_removes(self):
        added = ref.add_reference(self.ctx, title="죽는 글", body="옛 본문")
        path = self.folder / f"ref-{added.ref_id}.json"
        before = path.read_bytes()
        with mock.patch.object(context_module.os, "replace", side_effect=KeyboardInterrupt("프로세스가 죽는 순간을 흉내")):
            with self.assertRaises(KeyboardInterrupt):
                ref.update_reference(self.ctx, added.ref_id, title="죽는 글", body="새 본문 " + UNIQ_BODY)
        self.assertEqual(path.read_bytes(), before, "옛 파일은 그대로다")
        temps = [item for item in self.folder.iterdir() if item.name != path.name]
        self.assertEqual(len(temps), 1, "임시 파일에 새 본문이 남는다 — 문서가 이 한계를 적는다")
        self.assertIn(UNIQ_BODY.encode("utf-8"), temps[0].read_bytes())
        listing = ref.list_references(self.ctx)
        self.assertEqual((len(listing.entries), listing.skipped), (1, 0), "임시 파일은 목록·건너뜀 어디에도 안 잡힌다")
        ref.delete_reference(self.ctx, added.ref_id, confirmed=True)
        self.assertEqual(list(self.folder.iterdir()), [], "글을 지우면 그 번호의 임시 파일(평문 사본)도 함께 사라진다")

    def test_deleting_removes_exactly_the_temp_files_of_that_post_and_nothing_else(self):
        first = ref.add_reference(self.ctx, title="첫째", body="첫째 본문")
        second = ref.add_reference(self.ctx, title="둘째", body="둘째 본문")
        mine = self.make_leftovers(first.ref_id)
        others = self.make_leftovers(second.ref_id)
        decoys = (f"ref-{first.ref_id}.json.4242-zzzzzzzz.tmp",f"ref-{first.ref_id}.json.tmp.bak", f"ref-{first.ref_id}x.json.tmp", f"xref-{first.ref_id}.json.tmp", f"ref-{first.ref_id}.json.4242-abcdef1.tmp",
                  f"ref-{first.ref_id}.json.abc-abcdef12.tmp", "note.txt")
        for name in decoys:
            self.put_raw(name, "상관없는 파일 " + name)
        (self.folder / f"ref-{first.ref_id}.json.5-abcdef12.tmp").mkdir()                       # 폴더는 임시 파일이 아니다
        (self.folder / f"ref-{first.ref_id}.json.5-abcdef12.tmp" / "keep.txt").write_text("남아야 함", encoding="utf-8")
        before = {path.relative_to(self.folder).as_posix(): (path.read_bytes() if path.is_file() else None) for path in self.folder.rglob("*")}
        ref.delete_reference(self.ctx, first.ref_id, confirmed=True)
        after = {path.relative_to(self.folder).as_posix(): (path.read_bytes() if path.is_file() else None) for path in self.folder.rglob("*")}
        gone = sorted(set(before) - set(after))
        self.assertEqual(gone, sorted([f"ref-{first.ref_id}.json", *mine]), "사라진 것은 그 글 파일과 그 번호의 임시 파일 셋뿐")
        self.assertEqual({key: after[key] for key in after}, {key: before[key] for key in before if key in after}, "남은 것의 내용은 그대로")
        for name in (*others, *decoys, f"ref-{second.ref_id}.json", f"ref-{first.ref_id}.json.5-abcdef12.tmp/keep.txt"):
            self.assertIn(name, after, name)

    def test_leftover_temp_files_are_not_counted_toward_the_limit_and_do_not_break_the_list(self):
        for number in range(49):
            ref.add_reference(self.ctx, title=f"글 {number}", body="본문")
        self.make_leftovers("zzzzzzzz")
        listing = ref.list_references(self.ctx)
        self.assertEqual((len(listing.entries), listing.skipped), (49, 0))
        self.assertEqual(ref.add_reference(self.ctx, title="쉰째", body="본문").title, "쉰째")

    def test_a_temp_file_that_cannot_be_removed_stops_the_delete_before_the_post_file_and_says_so_without_the_path(self):
        added = ref.add_reference(self.ctx, title="지울 글", body="본문")
        leftovers = self.make_leftovers(added.ref_id)
        real = Path.unlink

        def refuse_temps(path, *args, **kwargs):
            if path.name.endswith(".tmp"):
                raise PermissionError(errno.EACCES, "접근 거부 " + UNIQ_DIR, str(path))
            return real(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", autospec=True, side_effect=refuse_temps):
            error = self.refused(lambda: ref.delete_reference(self.ctx, added.ref_id, confirmed=True), code="FILE_WRITE_FAILED")
        self.assertEqual(error.slots, {"경로": "참고 글 보관함 폴더"})
        self.assertNotIn(UNIQ_DIR, repr(channels(error)))
        self.assertTrue((self.folder / f"ref-{added.ref_id}.json").exists(), "임시 파일을 못 지웠으면 글 파일도 지우지 않는다(다시 할 수 있다)")
        for name in leftovers:
            self.assertTrue((self.folder / name).exists())
        ref.delete_reference(self.ctx, added.ref_id, confirmed=True)                           # 막힘이 풀리면 그대로 다시 지울 수 있다
        self.assertEqual(list(self.folder.iterdir()), [])


class FolderLinkTest(RefCase):
    """독립 검증 S-R3 — 보관함 폴더가 링크(정션 포함)이면 목록·추가뿐 아니라 열기·고치기·지우기도 거절한다."""

    def calls(self):
        return (("list", lambda: ref.list_references(self.ctx)), ("add", lambda: ref.add_reference(self.ctx, title="제목", body="본문")), ("open", lambda: ref.open_reference(self.ctx, "aaaaaaaa")),
                ("update", lambda: ref.update_reference(self.ctx, "aaaaaaaa", title="새 제목", body="새 본문")), ("delete", lambda: ref.delete_reference(self.ctx, "aaaaaaaa", confirmed=True)))

    def test_a_folder_that_looks_like_a_link_is_refused_by_all_five_and_nothing_is_touched(self):
        path = self.put_valid("aaaaaaaa")
        before = {item.name: item.read_bytes() for item in self.folder.iterdir()}
        with mock.patch.object(own_posts, "_link_like", side_effect=lambda info: stat.S_ISDIR(info.st_mode)):      # 폴더만 링크처럼 보이게(파일은 보통 파일)
            for label, call in self.calls():
                with self.subTest(call=label):
                    self.refused(call, "folder")
        self.assertEqual({item.name: item.read_bytes() for item in self.folder.iterdir()}, before)
        self.assertTrue(path.exists())

    def test_a_bad_number_is_still_refused_as_a_bad_number_before_the_folder_is_looked_at(self):
        self.folder.mkdir(parents=True)
        with mock.patch.object(own_posts, "_link_like", side_effect=lambda info: stat.S_ISDIR(info.st_mode)):
            self.refused(lambda: ref.open_reference(self.ctx, "../x"), "id")
            self.refused(lambda: ref.update_reference(self.ctx, "../x", title="제목", body="본문"), "id")
            self.refused(lambda: ref.delete_reference(self.ctx, "../x", confirmed=True), "id")

    def test_a_folder_that_does_not_exist_yet_is_not_a_problem_for_the_readers(self):
        self.assertIsNone(ref._folder_problem(self.folder))
        self.refused(lambda: ref.open_reference(self.ctx, "aaaaaaaa"), code="CONTENT_NOT_FOUND")
        self.refused(lambda: ref.delete_reference(self.ctx, "aaaaaaaa", confirmed=True), code="CONTENT_NOT_FOUND")
        self.assertFalse(self.folder.exists())

    def test_a_real_windows_junction_is_refused_by_all_five_and_the_target_is_not_touched(self):
        if os.name != "nt":
            self.skipTest("정션은 윈도에만 있다 — 모의 상태 정보로 규칙 자체는 위 시험이 본다")
        import subprocess
        target = self.tmp / "target-folder"
        target.mkdir()
        (target / "ref-aaaaaaaa.json").write_text(json_text("aaaaaaaa"), encoding="utf-8")
        self.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(self.folder), str(target)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if made.returncode != 0 or not self.folder.exists():
            self.skipTest("이 환경에서는 정션을 만들 수 없다")
        before = {item.name: item.read_bytes() for item in target.iterdir()}
        for label, call in self.calls():
            with self.subTest(call=label):
                self.refused(call, "folder")
        self.assertEqual({item.name: item.read_bytes() for item in target.iterdir()}, before, "정션 너머 파일은 읽히지도 고쳐지지도 지워지지도 않았다")

    def test_a_real_symlink_to_a_folder_is_refused_too_when_the_system_allows_one(self):
        target = self.tmp / "target-folder"
        target.mkdir()
        (target / "ref-aaaaaaaa.json").write_text(json_text("aaaaaaaa"), encoding="utf-8")
        self.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, self.folder, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("이 환경에서는 폴더 링크를 만들 수 없다")
        before = {item.name: item.read_bytes() for item in target.iterdir()}
        for label, call in self.calls():
            with self.subTest(call=label):
                self.refused(call, "folder")
        self.assertEqual({item.name: item.read_bytes() for item in target.iterdir()}, before)


def json_text(ref_id, body="본문입니다."):
    import json
    return json.dumps({"schema": 1, "id": ref_id, "title": "정션 너머의 글", "body": body, "created_at": "2026-11-15T01:00:00Z", "updated_at": "2026-11-15T01:00:00Z"}, ensure_ascii=False)


class FileSizeBoundaryTest(RefCase):
    """독립 검증 S-R6 — 보관 파일 하나의 상한은 정확히 1MiB(1,048,576 바이트)이고 그 바이트까지는 읽고 한 바이트 더 크면 건너뛴다."""

    def padded(self, ref_id, size):
        data = json_text(ref_id).encode("utf-8")
        assert len(data) <= size
        return data + b" " * (size - len(data))                                                # JSON 은 끝 공백을 허용한다

    def test_the_limit_is_exactly_one_mebibyte(self):
        self.assertEqual(ref.MAX_FILE_BYTES, 1_048_576)

    def test_one_byte_under_exactly_and_one_byte_over(self):
        for number, (size, listed) in enumerate(((ref.MAX_FILE_BYTES - 1, True), (ref.MAX_FILE_BYTES, True), (ref.MAX_FILE_BYTES + 1, False), (ref.MAX_FILE_BYTES + 4096, False))):
            ref_id = f"size{number:04d}"
            with self.subTest(size=size):
                path = self.put_raw(f"ref-{ref_id}.json", self.padded(ref_id, size))
                self.assertEqual(path.stat().st_size, size)
                listing = ref.list_references(self.ctx)
                self.assertEqual((ref_id in [entry.ref_id for entry in listing.entries], listing.skipped), (listed, 0 if listed else 1))
                if listed:
                    self.assertEqual(ref.open_reference(self.ctx, ref_id).title, "정션 너머의 글")
                else:
                    self.refused(lambda: ref.open_reference(self.ctx, ref_id), "broken")
                    self.refused(lambda: ref.update_reference(self.ctx, ref_id, title="새 제목", body="새 본문"), "broken")
                path.unlink()

    def test_a_file_over_the_limit_is_not_even_opened(self):
        self.put_raw("ref-readbyte.json", b" " * (ref.MAX_FILE_BYTES * 3))
        seen = []
        real = own_posts._read_prefix
        with mock.patch.object(own_posts, "_read_prefix", side_effect=lambda path, limit, expected: (seen.append(limit), real(path, limit, expected))[1]):
            ref.list_references(self.ctx)
        self.assertEqual(seen, [], "크기가 상한을 넘는 파일은 열지도 않는다")


class BackupNoteTest(RefCase):
    """독립 검증 S-R4 — 백업 카드의 '담지 않는 것' 목록이 보관함에 대해 사실을 말한다(줄 수 아홉·이름은 그대로, 아홉째 줄의 이유 문장만 고쳤다)."""

    def test_the_ninth_line_tells_the_truth_about_the_vault_and_the_list_keeps_its_nine_names(self):
        from chanceblog_desktop.security import backup_note
        self.assertEqual([name for name, _ in backup_note.EXCLUDED], ["키·토큰·쿠키·세션·자격 증명", "connections.json", "quota_state.json", "publish/", "locks/", "backups/", "logs/", "임시·복구용 사본", "외부에서 가져온 원본 자료"])
        reason = dict(backup_note.EXCLUDED)["외부에서 가져온 원본 자료"]
        for word in ("참고 글 보관함", "references/", "들어 있지 않아요", "직접 옮겨"):
            self.assertIn(word, reason)
        self.assertNotIn("앱 데이터에 두지 않아서", reason, "참고 글은 앱 데이터에 있으므로 이 말은 더는 사실이 아니다")
        self.assertIn("오류 이름", dict(backup_note.EXCLUDED)["logs/"], "다른 줄(M074 의 logs/)은 그대로다")

    def test_a_real_backup_manifest_carries_that_sentence_and_still_leaves_the_vault_out(self):
        import backup_support as bs
        from chanceblog_desktop.security import backup_note
        with tempfile.TemporaryDirectory(prefix="refs-note-") as tmp:
            world = bs.World(Path(os.path.realpath(tmp)), posts=1, drafts=0, candidates_count=0)
            ref.add_reference(world.ctx, title="백업에 없는 글", body="본문")
            manifest = world.manifest(world.backup())
            reasons = {item["name"]: item["reason"] for item in manifest["excluded"]}
            self.assertEqual(reasons["외부에서 가져온 원본 자료"], dict(backup_note.EXCLUDED)["외부에서 가져온 원본 자료"])
            self.assertEqual(len(manifest["excluded"]), 9)


# ---- 10) 소스 규칙 ----------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    def setUp(self):
        self.text = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.text)

    def calls(self):
        """(호출, 그 호출을 감싼 가장 안쪽 함수의 이름)."""
        def walk(node, function=""):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Call):
                    yield child, function
                yield from walk(child, child.name if isinstance(child, ast.FunctionDef) else function)
        return list(walk(self.tree))

    def test_the_only_file_changing_calls_are_write_json_and_one_unlink_in_delete_reference(self):
        found = []
        for node, function in self.calls():
            name = node.func.attr if isinstance(node.func, ast.Attribute) else (node.func.id if isinstance(node.func, ast.Name) else "")
            full = ast.unparse(node.func)
            if name in ("unlink", "mkdir", "rmdir", "rename", "replace", "write_text", "write_bytes", "write", "open", "touch", "chmod", "rmtree", "makedirs", "copy", "copy2", "copyfile", "move", "remove", "symlink", "link"):
                found.append((name, function))
            if full in ("os.open", "os.write", "os.fsync", "os.replace", "os.rename", "os.remove", "os.unlink", "os.link", "os.symlink", "os.makedirs", "os.mkdir", "os.chmod", "os.truncate"):
                found.append((full, function))
        self.assertEqual(found, [("unlink", "delete_reference")] * 2, "파일을 바꾸는 길은 지우기의 unlink 둘(그 번호의 임시 파일들·글 파일 하나)뿐이고 쓰기는 모두 context.write_json 이다")
        names = {ast.unparse(node.func) for node, _function in self.calls()}
        self.assertIn("write_json", names)

    def test_no_network_process_or_output_modules_are_imported_and_nothing_prints(self):
        banned = {"subprocess", "socket", "urllib", "http", "ssl", "webbrowser", "ctypes", "requests", "shutil", "tempfile", "logging", "asyncio", "threading", "multiprocessing", "random"}
        for node in ast.walk(self.tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            for name in names:
                self.assertNotIn(name.split(".")[0], banned, name)
        called = {ast.unparse(node.func) for node, _function in self.calls()}
        self.assertFalse(called & {"print", "input", "exec", "eval", "compile", "__import__", "getattr", "setattr", "os.system", "os.popen", "os.startfile", "sys.stdout.write", "sys.stderr.write"})
        self.assertFalse({name for name in called if name.startswith(("logging.", "logger.", "log."))})

    def test_the_text_has_no_web_address_no_ascii_tilde_and_no_secret_words(self):
        self.assertNotRegex(self.text, r"https?://|www\.")
        self.assertNotIn(chr(0x7E), self.text)
        strings = [node.value for node in ast.walk(self.tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        secret = re.compile(r"(?i)\b(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?\b")
        for value in strings:
            self.assertIsNone(secret.search(value), value[:30])

    def test_every_function_that_builds_a_file_path_from_a_given_id_checks_the_id_first(self):
        """번호를 받는 함수(열기·고치기·지우기)는 경로를 만들기 전에 `is_id` 로 모양을 확인한다 — 사용자가 준 글자가 경로가 되지 않는다."""
        functions = {node.name: node for node in self.tree.body if isinstance(node, ast.FunctionDef)}

        def lines(function, name):
            return sorted(node.lineno for node in ast.walk(function) if isinstance(node, ast.Call) and ast.unparse(node.func) == name)

        for name, builder in (("open_reference", "_file_of"), ("update_reference", "_change"), ("delete_reference", "_file_of")):
            checks, builds = lines(functions[name], "is_id"), lines(functions[name], builder)
            with self.subTest(function=name):
                self.assertTrue(checks and builds and checks[0] < builds[0], "번호 모양 확인이 경로를 만드는 일보다 먼저다")
        users = sorted(node.name for node in functions.values() if any(isinstance(call, ast.Call) and ast.unparse(call.func) == "_file_of" for call in ast.walk(node)))
        self.assertEqual(users, ["_change", "_free_id", "_save", "delete_reference", "list_references", "open_reference"], "경로를 만드는 곳은 이 여섯 곳뿐이다")
        callers = sorted(node.name for node in functions.values() if any(isinstance(call, ast.Call) and ast.unparse(call.func) == "_change" for call in ast.walk(node)))
        self.assertEqual(callers, ["update_reference"], "`_change` 는 번호를 확인한 `update_reference` 만 부른다")
        build = functions["_file_of"]
        self.assertEqual(ast.unparse(build.body[-1].value), "folder_path(ctx) / f'{FILE_PREFIX}{ref_id}{FILE_SUFFIX}'")

    def test_the_file_name_is_made_only_from_the_prefix_the_id_and_the_suffix(self):
        self.assertEqual((ref.FILE_PREFIX, ref.FILE_SUFFIX), ("ref-", ".json"))
        self.assertEqual(re.compile(ref._ID.pattern).pattern, "[a-z0-9]{8}")
        self.assertEqual(ref._NAME.pattern, r"ref-([a-z0-9]{8})\.json")

    def test_the_vault_is_not_part_of_the_full_backup(self):
        """첫 판은 보관함을 백업에 넣지 않는다(백업 형식은 그대로) — 진짜 전체 백업을 만들어도 보관함의 파일·글이 백업 폴더에 없고 보관함은 그대로다."""
        import backup_support as bs
        with tempfile.TemporaryDirectory(prefix="refs-backup-") as tmp:
            world = bs.World(Path(os.path.realpath(tmp)), posts=1, drafts=0, candidates_count=0)
            added = ref.add_reference(world.ctx, title=UNIQ_TITLE, body=UNIQ_BODY)
            vault = world.root / "references"
            before = {path.name: path.read_bytes() for path in vault.iterdir()}
            outcome = world.backup()
            folder = world.folder(outcome)
            names = [path.relative_to(folder).as_posix() for path in folder.rglob("*")]
            self.assertTrue(names, "백업은 만들어졌다")
            self.assertFalse([name for name in names if "references" in name or added.ref_id in name], names)
            for path in folder.rglob("*"):
                if path.is_file():
                    data = path.read_bytes()
                    self.assertNotIn(UNIQ_BODY.encode("utf-8"), data, path.name)
                    self.assertNotIn(UNIQ_TITLE.encode("utf-8"), data, path.name)
            self.assertEqual({path.name: path.read_bytes() for path in vault.iterdir()}, before, "백업이 보관함을 건드리지 않았다")
            manifest = world.manifest(outcome)
            self.assertEqual([key for key, value in manifest.items() if "references" in repr(value)], ["excluded"], "목록 파일에서 보관함을 말하는 곳은 '담지 않은 것' 의 이유 문장 하나뿐이다(담은 파일·빠진 것에는 없다)")

    def test_a_real_restore_leaves_the_vault_untouched_even_when_the_vault_changed_after_the_backup(self):
        """진짜 백업·복원 흐름 — 복원이 보관함(`references/`)의 파일을 지우거나 되돌리거나 고치지 않는다(보관함은 백업에 안 들어 있으니 백업 뒤에 올리고·고치고·지운 것이 복원 뒤에도 그대로여야 한다).
        복원 자체는 실제로 돌았음을 글 보관함의 글 개수가 백업 때로 돌아간 것으로 확인하고, 복원 전 안전 사본(`before-restore`)에도 보관함의 파일·글이 없다."""
        import backup_support as bs
        from chanceblog_desktop.service import backup_flow as bf
        from chanceblog_desktop.service import projects
        with tempfile.TemporaryDirectory(prefix="refs-restore-") as tmp:
            world = bs.World(Path(os.path.realpath(tmp)), posts=1, drafts=0, candidates_count=0)
            ctx = world.ctx
            ctx.clock.advance(minutes=1)
            before_backup = ref.add_reference(ctx, title=UNIQ_TITLE + "-전", body=UNIQ_BODY + "-전")
            outcome = world.backup()
            ctx.clock.advance(minutes=1)
            after = ref.add_reference(ctx, title=UNIQ_TITLE + "-후", body=UNIQ_BODY + "-후")
            doomed = ref.add_reference(ctx, title="곧 지울 글", body="곧 지울 본문")
            ctx.clock.advance(minutes=1)
            ref.update_reference(ctx, before_backup.ref_id, title=UNIQ_TITLE + "-고침", body=UNIQ_BODY + "-고침")
            ref.delete_reference(ctx, doomed.ref_id, confirmed=True)
            projects.new_project(ctx, "백업 뒤에 만든 글", "백업 뒤의 본문")                     # 복원이 되돌릴 것(글 보관함) — 복원이 실제로 도는지 보는 표지
            self.assertEqual(len(projects.list_projects(ctx)), 2)
            vault = world.root / "references"

            def snap():
                return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(vault.iterdir())}

            expected = snap()
            self.assertEqual(len(expected), 2)
            result = bf.restore_full_backup(ctx, outcome.row.name, confirmed=True)
            self.assertEqual(result.status, bf.STATUS_COMPLETE)
            self.assertEqual(len(projects.list_projects(ctx)), 1, "복원은 실제로 돌았다 — 글 보관함은 백업 때로 돌아갔다")
            self.assertEqual(snap(), expected, "복원은 보관함의 파일을 하나도 건드리지 않았다(내용·수정 시각 그대로)")
            listing = ref.list_references(ctx)
            self.assertEqual(sorted(entry.ref_id for entry in listing.entries), sorted([before_backup.ref_id, after.ref_id]))
            self.assertEqual(ref.open_reference(ctx, before_backup.ref_id).title, UNIQ_TITLE + "-고침")
            for path in ctx.workspace.backups_dir.rglob("*"):                                    # 복원 전 안전 사본에도 보관함이 없다
                self.assertNotIn("references", path.relative_to(ctx.workspace.backups_dir).as_posix())
                if path.is_file():
                    data = path.read_bytes()
                    self.assertNotIn(UNIQ_BODY.encode("utf-8"), data, path.name)
                    self.assertNotIn(UNIQ_TITLE.encode("utf-8"), data, path.name)


if __name__ == "__main__":
    unittest.main()
