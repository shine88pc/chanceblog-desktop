"""'사진 정리'(사진 연동 초안 2단계, 결정 D-499)의 순수 층 — `ui/core/photo_rules.py`·`photo_view.py`(PhotoBoard)·`photo_text.py` 와 초안 컨트롤러에 매단 사진 목록. PySide6 없이 돈다(CI 와 같은 조건). 파일은 만들지 않는다(가짜 공급자).

지키는 것:
  1) 규칙표 — 종류 9종·장소 분위기 6종·종류별 기본 '들어갈 곳'(결정 4)·종류별 예시(운영자 예시 문장)·큰 PNG 판정(PNG 만, 1억 화소를 넘을 때만 — 결정 16)·글자 수 표시.
  2) 사진 넣기 — 못 넣은 파일은 이름과 고정 이유만(경로 없음), 30장 한도, 중복, 읽기 도구가 터져도 그 파일만 못 넣음.
  3) 고치기 — 한도를 넘거나 검사에 걸린 글은 반영하지 않고 이유만(글은 이 객체가 쥐지 않음), 내용을 고치면 확인이 풀리고 안내가 한 번 뜸, 종류를 바꾸면 사용자가 따로 안 골랐을 때만 기본 들어갈 곳이 바뀜.
  4) 확인 — '모두 확인했어요' 는 확인 줄(수)을 먼저 보이고 한 번 더 눌러야 표시, 그만두면 그대로.
  5) 순서·지우기·되돌리기·다시 찾기·종류 목록 고치기·닫기 경고.
  6) 뷰모델에 경로가 없고(파일 이름만) 입력 칸은 늘 보이며 종류에 맞는 예시가 바뀐다 · 초안 컨트롤러는 사진이 없어도 지금과 같고 새 초안·떠남·저장한 초안 열기에서 사진 목록이 비워진다 · 소스 규칙(파일·네트워크·하위 프로세스·표준 출력 0).
"""
import ast
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import scan_samples  # noqa: E402
from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.topics import safety  # noqa: E402
from chanceblog_desktop.ui.core import candidates as ucd  # noqa: E402
from chanceblog_desktop.ui.core import drafts, drafts_view as dv, imagerules as R, jobs, photo_rules as rules, photo_text, photo_view as pv, text  # noqa: E402

T = text.T
UI_CORE = ROOT / "src" / "chanceblog_desktop" / "ui" / "core"
UI_QT = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"
USER_DIR, FILE_STEM = "UNIQ-USERDIR-q7w2", "UNIQ-FILE-k3x9"


def path_of(number, ext="jpg"):
    return f"C:/Users/{USER_DIR}/Pictures/{FILE_STEM}-{number:02d}.{ext}"


def new_board(count=0, **provider):
    board = pv.PhotoBoard(pv.FakePhotoProvider(**provider))
    if count:
        board.add_paths([path_of(number) for number in range(1, count + 1)])
    return board


def row_of(board, photo_id="p001"):
    return next(row for row in board.view()["rows"] if row["photo_id"] == photo_id)


def dumped(board):
    return json.dumps(board.view(), ensure_ascii=False)


class RulesTest(unittest.TestCase):
    def test_the_lists_the_operator_chose(self):
        self.assertEqual(rules.TYPES, ("간판", "건물 외관", "메뉴판", "인테리어", "대표 메뉴", "반찬", "음식", "지도 캡처", "기타"))
        self.assertEqual(rules.SETTINGS, ("실내", "실외", "테라스", "주차장", "객실", "야경"))
        self.assertEqual(rules.DEFAULT_SECTION_BY_TYPE, {"간판": "도입", "건물 외관": "도입", "메뉴판": "내용 소제목", "대표 메뉴": "내용 소제목", "음식": "내용 소제목", "반찬": "내용 소제목", "인테리어": "분위기 소제목", "지도 캡처": "", "기타": ""})
        self.assertEqual(set(rules.DEFAULT_SECTION_BY_TYPE), set(rules.TYPES))
        self.assertEqual(rules.default_section("내가 만든 종류"), "")
        self.assertEqual(rules.SECTION_CHOICES, ("", "도입", "내용 소제목", "분위기 소제목", "마무리"))
        self.assertEqual(rules.PLACEMENT_KINDS, ("auto", "top", "after_heading", "after_paragraph", "between_sentences"))
        self.assertEqual(rules.PLACEMENT_KINDS, pm.PLACEMENT_KINDS)
        self.assertEqual((rules.MAX_LIST_ITEMS, rules.PROTECTED_TYPE, rules.THUMB_SIDE), (20, "기타", 96))

    def test_the_examples_follow_the_type_and_include_the_operators_own_sentences(self):
        self.assertEqual(rules.example_for("반찬"), "반찬 5개")
        self.assertEqual(rules.example_for("대표 메뉴"), "메인 메뉴 한우 불고기 전골")
        self.assertEqual(rules.example_for("간판"), "매장 입구 간판과 주차장 전경")
        self.assertEqual(rules.example_for("처음 보는 종류"), rules.EXAMPLE_DEFAULT)
        self.assertEqual(set(rules.EXAMPLES), set(rules.TYPES))
        self.assertEqual(len(set(rules.EXAMPLES.values())), len(rules.TYPES), "종류마다 예시가 다르다")

    def test_a_png_over_a_hundred_million_pixels_gets_no_preview_but_nothing_else_does(self):
        limit = rules.PNG_PIXEL_LIMIT
        self.assertEqual(limit, 100_000_000)
        self.assertFalse(rules.preview_blocked("png", 10_000, 10_000), "정확히 1억 화소는 만든다")
        self.assertTrue(rules.preview_blocked("png", 10_001, 10_000))
        self.assertTrue(rules.preview_blocked("PNG", 20_000, 20_000))
        self.assertTrue(rules.preview_blocked("png", 1, limit + 1))
        for fmt in ("jpeg", "jpg", "webp", "gif", "", None):
            self.assertFalse(rules.preview_blocked(fmt, 30_000, 30_000), fmt)
        for width, height in ((0, 0), (None, 5), ("x", 5), (5, None), (-1, -1)):
            self.assertFalse(rules.preview_blocked("png", width, height), (width, height))
        self.assertFalse(pv.FileState("p001", R.OK, width=640, height=480, format="png").preview_blocked)
        self.assertTrue(pv.FileState("p001", R.OK, width=20_000, height=20_000, format="png").preview_blocked)
        self.assertFalse(pv.FileState("p001", R.OK, width=20_000, height=20_000, format="jpeg").preview_blocked)

    def test_counters_and_over_limit_text(self):
        self.assertEqual(rules.count_text(12, 60), "12/60")
        self.assertEqual(rules.count_text(0, 300), "0/300")
        self.assertFalse(rules.over_limit(60, 60))
        self.assertTrue(rules.over_limit(61, 60))
        self.assertEqual(rules.over_text(60, 60), "")
        self.assertIn("60자까지만", rules.over_text(61, 60))
        self.assertIn("61", rules.over_text(61, 60))
        self.assertEqual(rules.FIELD_LIMITS, {"user_subject": 60, "user_note": 300, "caption": 100})

    def test_file_badges_are_words_and_only_the_fixable_states_offer_finding_again(self):
        self.assertEqual(rules.badge("ok"), "파일 있음")
        self.assertEqual(rules.badge("ok", 4000, 3000), "파일 있음 · 4000×3000")
        words = {"missing": "파일 없음", "link": "링크라서 쓰지 않아요", "cloud": "내려받지 않은 파일이에요", "too_big": "너무 커요(20MB까지)", "unsupported": "지원하지 않는 형식이에요", "not_image": "사진 파일이 아니에요",
                 "not_file": "파일이 아니에요", "unreadable": "읽지 못했어요", "unknown": "아직 확인하지 않았어요"}
        for state, expected in words.items():
            self.assertEqual(rules.badge(state), expected, state)
            self.assertNotEqual(rules.tone_of(state), "ok" if state != "unknown" else "x")
        self.assertEqual(rules.badge("무슨 상태"), "아직 확인하지 않았어요")
        self.assertEqual(rules.tone_of("ok"), "ok")
        self.assertEqual(rules.tone_of("unknown"), "muted")
        self.assertEqual(rules.RELINKABLE, frozenset({"missing", "link", "not_file", "unsupported", "not_image", "unreadable"}))
        self.assertNotIn("ok", rules.RELINKABLE)
        self.assertNotIn("cloud", rules.RELINKABLE, "내려받지 않은 파일은 다른 파일을 고르는 것이 아니라 내려받아야 한다")

    def test_section_and_placement_choices(self):
        self.assertEqual([value for value, _text in rules.section_choices("")], list(rules.SECTION_CHOICES))
        self.assertEqual([text for _value, text in rules.section_choices("")], ["자동", "도입", "내용 소제목", "분위기 소제목", "마무리"])
        extra = rules.section_choices("대표 메뉴 소개")
        self.assertEqual(extra[-1], ("대표 메뉴 소개", "대표 메뉴 소개"), "목록 밖의 값(나중 단계가 적은 소제목 글)은 조용히 지우지 않고 하나 더한다")
        self.assertEqual([text for _kind, text in rules.placement_choices()], ["자동", "글 맨 앞", "소제목 바로 뒤", "문단 뒤", "문장 사이"])
        self.assertTrue(rules.needs_nth("after_paragraph") and rules.needs_nth("between_sentences"))
        self.assertFalse(any(rules.needs_nth(kind) for kind in ("auto", "top", "after_heading")))

    def test_the_shown_file_name_has_no_folder_and_secret_shapes_are_masked(self):
        self.assertEqual(rules.short_name("C:/Users/누구/Pictures/메뉴판.jpg"), "메뉴판.jpg")
        self.assertEqual(rules.short_name("C:\\Users\\누구\\Pictures\\간판.png"), "간판.png")
        self.assertEqual(rules.short_name("/home/a/b.webp"), "b.webp")
        self.assertEqual(rules.short_name(None), "")
        self.assertEqual(rules.short_name("C:/dir/"), "")
        self.assertLessEqual(len(rules.short_name("C:/a/" + "가" * 100 + ".jpg", 40)), 41)
        key = scan_samples.google()
        self.assertNotIn(key, rules.short_name(f"C:/a/{key}.jpg"))

    def test_the_new_screen_texts_follow_the_house_rules(self):
        for key, value in photo_text.PHOTO_T.items():
            self.assertIs(T[key], value, key)
            self.assertTrue(key.startswith("pho_"), key)
            for word in text.FORBIDDEN:
                self.assertNotIn(word, value, key)
        self.assertEqual(T["pho_count"].format(n=7, c=3), "사진 7장 · 확인 3/7")
        self.assertEqual(T["pho_card_count"].format(n=2, c=1), "사진 2장 · 확인 1/2")
        self.assertEqual(T["pho_file_ok_size"].format(w=4000, h=3000), "파일 있음 · 4000×3000")


class AddingTest(unittest.TestCase):
    def test_good_photos_are_added_in_order_and_start_as_other_and_unconfirmed(self):
        board = new_board()
        self.assertEqual(board.add_paths([path_of(1), path_of(2, "PNG"), path_of(3, "webp")]), (3, 0))
        photos = board.manifest.photos
        self.assertEqual([(photo.photo_id, photo.display_order, photo.photo_type, photo.confirmed_by_user) for photo in photos], [("p001", 1, "기타", False), ("p002", 2, "기타", False), ("p003", 3, "기타", False)])
        self.assertEqual(board.count, 3)
        self.assertEqual(board.view()["notice"], {"level": "info", "text": "사진 3장을 넣었어요."})
        self.assertTrue(all(state.ok and state.verified for state in board.states.values()))

    def test_bad_files_are_listed_with_their_name_and_a_fixed_reason_and_never_a_path(self):
        board = new_board()
        paths = [path_of(1), path_of(2, "gif"), "relative/a.jpg", path_of(1), f"C:/x/{FILE_STEM}-nul.txt"]
        added, rejected = board.add_paths(paths)
        self.assertEqual((added, rejected), (1, 4))
        reasons = {item.name: item.reason for item in board.rejected}
        self.assertEqual(reasons[f"{FILE_STEM}-02.gif"], "지원하지 않는 형식이에요. JPG·PNG·WebP 사진만 쓸 수 있어요")
        self.assertEqual(reasons["a.jpg"], "사진 파일 위치가 올바르지 않아요. 파일 선택 창에서 직접 골라 주세요")
        self.assertEqual(reasons[f"{FILE_STEM}-01.jpg"], "이미 넣은 사진이에요.")
        for item in board.rejected:
            self.assertNotIn(USER_DIR, item.name)
            self.assertNotIn("/", item.name)
            self.assertNotIn(USER_DIR, repr(item) + str(item))
        shown = dumped(board)
        self.assertNotIn(USER_DIR, shown)
        self.assertNotIn("C:/", shown)
        self.assertEqual(board.view()["rejected"]["title"], "넣지 못한 파일")
        self.assertEqual(len(board.view()["rejected"]["rows"]), 4)
        board.clear_rejected()
        self.assertIsNone(board.view()["rejected"])

    def test_the_judgement_of_the_image_reader_decides_and_a_crashing_reader_only_rejects_that_file(self):
        verdicts = {path_of(1): R.Verdict(R.TOO_BIG, T["img_local_too_big"]), path_of(2): R.Verdict(R.NOT_IMAGE, T["img_local_not_image"]), path_of(3): R.Verdict(R.OK, "", "", 20000, 20000, "png")}
        board = new_board(verdicts=verdicts)
        self.assertEqual(board.add_paths([path_of(1), path_of(2), path_of(3), path_of(4)]), (2, 2))
        self.assertEqual({item.reason for item in board.rejected}, {T["img_local_too_big"], T["img_local_not_image"]})
        self.assertTrue(board.states["p001"].preview_blocked, "큰 PNG 는 넣을 수는 있고 미리보기만 막는다")
        crash = new_board(fail={"judge"})
        self.assertEqual(crash.add_paths([path_of(1)]), (0, 1))
        self.assertEqual(crash.rejected[0].reason, T["img_local_unreadable"])
        self.assertEqual(crash.count, 0)

    def test_thirty_photos_fit_and_the_rest_are_refused_with_the_limit_sentence(self):
        board = new_board(30)
        self.assertEqual(board.count, 30)
        self.assertTrue(board.full)
        view = board.view()
        self.assertFalse(view["add"]["enabled"])
        self.assertEqual(view["full"], "사진이 30장이라 더 넣을 수 없어요. 쓰지 않을 사진을 지운 뒤 다시 추가해 주세요.")
        self.assertEqual(board.add_paths([path_of(31), path_of(32)]), (0, 2))
        self.assertEqual({item.reason for item in board.rejected}, {"사진은 30장까지만 넣을 수 있어요."})
        board.remove("p030")
        self.assertTrue(board.view()["add"]["enabled"])
        self.assertEqual(board.add_paths([path_of(31)]), (1, 0))

    def test_the_list_of_files_not_added_is_replaced_by_each_new_choice(self):
        board = new_board()
        board.add_paths([path_of(1, "gif"), path_of(2, "bmp")])
        self.assertEqual(sorted(item.name for item in board.rejected), [f"{FILE_STEM}-01.gif", f"{FILE_STEM}-02.bmp"])
        board.add_paths([path_of(3, "tif")])
        self.assertEqual([item.name for item in board.rejected], [f"{FILE_STEM}-03.tif"], "앞 선택의 못 넣은 파일은 이번 선택으로 바뀐다")
        board.add_paths([path_of(4)])
        self.assertEqual(board.rejected, (), "다 넣었으면 목록이 비워진다")

    def test_choosing_nothing_changes_nothing(self):
        board = new_board(2)
        before = board.manifest
        for nothing in (None, [], (), "", [""], [None, 5]):
            self.assertEqual(board.add_paths(nothing), (0, 0))
        self.assertEqual(board.manifest, before)
        self.assertEqual(board.view()["notice"]["text"], "사진 2장을 넣었어요.")


class EditingTest(unittest.TestCase):
    def test_changing_the_type_changes_the_default_section_only_when_the_user_did_not_choose_one(self):
        board = new_board(1)
        self.assertEqual(board.set_type("p001", "간판"), "ok")
        self.assertEqual(board.photo("p001").preferred_section, "도입")
        board.set_type("p001", "메뉴판")
        self.assertEqual(board.photo("p001").preferred_section, "내용 소제목")
        board.set_type("p001", "인테리어")
        self.assertEqual(board.photo("p001").preferred_section, "분위기 소제목")
        board.set_type("p001", "지도 캡처")
        self.assertEqual(board.photo("p001").preferred_section, "")
        board.set_section("p001", "마무리")
        board.set_type("p001", "간판")
        self.assertEqual(board.photo("p001").preferred_section, "마무리", "사용자가 고른 곳은 바뀌지 않는다")
        self.assertEqual(board.set_type("p001", "없는 종류"), "refused")
        self.assertEqual(board.set_type("p009", "간판"), "refused")
        self.assertEqual(board.photo("p001").photo_type, "간판")

    def test_the_example_text_changes_with_the_type_and_the_inputs_are_always_in_the_row(self):
        board = new_board(1)
        row = row_of(board)
        self.assertEqual(row["subject"]["label"], "이 사진은 무엇인가요?")
        self.assertEqual(row["subject"]["example"], "예: " + rules.example_for("기타"))
        board.set_type("p001", "반찬")
        self.assertEqual(row_of(board)["subject"]["example"], "예: 반찬 5개")
        board.set_type("p001", "대표 메뉴")
        self.assertEqual(row_of(board)["subject"]["example"], "예: 메인 메뉴 한우 불고기 전골")
        board.set_type("p001", "간판")
        self.assertEqual(row_of(board)["subject"]["example"], "예: 매장 입구 간판과 주차장 전경")
        self.assertEqual(row["note"]["label"], "한마디 메모(선택)")
        for key in ("subject", "note", "caption"):
            self.assertEqual(set(row[key]), {"name", "label", "a11y", "value", "example", "limit", "count", "error"})
        self.assertEqual((row["subject"]["limit"], row["note"]["limit"], row["caption"]["limit"]), (60, 300, 100))

    def test_text_is_applied_when_valid_and_refused_with_a_reason_when_over_the_limit_or_unsafe(self):
        board = new_board(1)
        self.assertEqual(board.set_text("p001", "user_subject", "  매장 입구   간판  "), "ok")
        self.assertEqual(board.photo("p001").user_subject, "매장 입구 간판")
        self.assertEqual(row_of(board)["subject"]["count"], "8/60")
        self.assertEqual(board.set_text("p001", "user_subject", "매장 입구 간판"), "unchanged")
        too_long = "가" * 61
        self.assertEqual(board.set_text("p001", "user_subject", too_long), "invalid")
        self.assertEqual(board.photo("p001").user_subject, "매장 입구 간판", "반영하지 않았다")
        self.assertIn("60자까지만", row_of(board)["subject"]["error"])
        self.assertNotIn(too_long, dumped(board) + repr(vars(board)), "거절된 글은 이 객체가 쥐지 않는다")
        self.assertEqual(board.set_text("p001", "user_subject", "다시 짧게"), "ok")
        self.assertEqual(row_of(board)["subject"]["error"], "")
        key = scan_samples.google()
        self.assertEqual(board.set_text("p001", "user_note", f"앞 {key} 뒤"), "invalid")
        self.assertNotIn(key[:12], dumped(board) + repr(vars(board)))
        self.assertEqual(board.set_text("p001", "caption", "<b>굵게</b>"), "invalid")
        self.assertEqual(board.set_text("p001", "caption", "기본 반찬"), "ok")
        self.assertEqual(board.set_text("p001", "user_note", "가" * 300), "ok")
        self.assertEqual(row_of(board)["note"]["count"], "300/300")
        self.assertEqual(board.set_text("p001", "preferred_section", "x"), "refused")
        self.assertEqual(board.set_text("p009", "caption", "x"), "refused")

    def test_changing_a_confirmed_photo_unconfirms_it_once_with_a_note_and_an_unchanged_value_does_not(self):
        board = new_board(2)
        board.confirm("p001", True)
        board.confirm("p002", True)
        self.assertEqual(board.set_text("p001", "user_subject", "냉면"), "ok")
        self.assertFalse(board.photo("p001").confirmed_by_user)
        self.assertTrue(board.photo("p002").confirmed_by_user)
        self.assertEqual(row_of(board)["changed_note"], "내용을 고쳐서 확인 표시를 풀었어요. 다시 확인해 주세요.")
        board.confirm("p001", True)
        self.assertEqual(row_of(board)["changed_note"], "", "다시 확인하면 안내가 사라진다")
        self.assertEqual(board.set_text("p001", "user_subject", "냉면"), "unchanged")
        self.assertTrue(board.photo("p001").confirmed_by_user)
        board.set_setting("p001", "테라스")
        self.assertFalse(board.photo("p001").confirmed_by_user)

    def test_setting_section_and_placement(self):
        board = new_board(1)
        for label in ("실내", "실외", "테라스", "주차장", "객실", "야경", ""):
            self.assertIn(board.set_setting("p001", label), ("ok", "unchanged"))
            self.assertEqual(board.photo("p001").setting, label)
        self.assertEqual(board.set_setting("p001", "지하실"), "refused")
        self.assertEqual(board.set_section("p001", "마무리"), "ok")
        self.assertEqual(board.set_section("p001", "아무 곳"), "refused")
        self.assertEqual(board.set_placement("p001", "top"), "ok")
        self.assertEqual(board.photo("p001").placement, pm.Placement("top", 0))
        self.assertEqual(board.set_placement("p001", "after_paragraph"), "ok")
        self.assertEqual(board.photo("p001").placement, pm.Placement("after_paragraph", 1))
        self.assertEqual(board.step_nth("p001", 1), "ok")
        self.assertEqual(board.photo("p001").placement.nth, 2)
        self.assertEqual(board.set_placement("p001", "between_sentences", 5), "ok")
        self.assertEqual(board.photo("p001").placement, pm.Placement("between_sentences", 5))
        self.assertEqual(board.set_placement("p001", "between_sentences", 500), "ok")
        self.assertEqual(board.photo("p001").placement.nth, 50, "50 을 넘으면 50")
        self.assertEqual(board.step_nth("p001", 1), "unchanged")
        self.assertEqual(board.set_placement("p001", "after_paragraph", 0), "ok")
        self.assertEqual(board.photo("p001").placement.nth, 1, "1 보다 작으면 1")
        self.assertEqual(board.step_nth("p001", -1), "unchanged")
        self.assertEqual(board.set_placement("p001", "auto"), "ok")
        self.assertEqual(board.step_nth("p001", 1), "refused", "몇 번째가 없는 자리에는 늘릴 수 없다")
        self.assertEqual(board.set_placement("p001", "end"), "refused")
        self.assertEqual(board.step_nth("p001", 2), "refused")
        self.assertFalse(board.photo("p001").confirmed_by_user)


class ConfirmTest(unittest.TestCase):
    def test_confirming_one_photo_and_undoing_it(self):
        board = new_board(2)
        self.assertEqual(board.confirm("p001", True), "ok")
        self.assertEqual(board.confirmed_count, 1)
        self.assertEqual(board.confirm("p001", True), "unchanged")
        self.assertEqual(board.confirm("p001", False), "ok")
        self.assertEqual(board.confirm("p001", "yes"), "refused")
        self.assertEqual(board.confirm("p009", True), "refused")
        self.assertEqual(board.confirmed_count, 0)

    def test_confirm_all_shows_a_count_first_and_changes_nothing_until_the_second_press(self):
        board = new_board(3)
        board.confirm("p002", True)
        before = board.manifest
        self.assertEqual(board.confirm_all(), "refused", "1단계(확인 줄)를 건너뛴 두 번째 단계는 아무것도 하지 않는다")
        self.assertEqual(board.manifest, before)
        self.assertEqual(board.ask_confirm_all(), "ask")
        view = board.view()
        self.assertEqual(view["confirm_ask"]["text"], "사진 2장을 모두 ‘확인했어요’ 로 표시할까요? 표시한 사진의 종류·대상·메모가 초안에 쓰여요.")
        self.assertEqual((view["confirm_ask"]["yes"], view["confirm_ask"]["no"]), ("2장 모두 확인", "그만두기"))
        self.assertFalse(view["confirm_all"]["enabled"], "확인 줄이 떠 있는 동안 처음 단추는 꺼진다")
        self.assertEqual(board.manifest, before, "묻는 것만으로는 바뀌지 않는다")
        board.cancel_confirm_all()
        self.assertIsNone(board.view()["confirm_ask"])
        self.assertEqual(board.manifest, before)
        board.ask_confirm_all()
        self.assertEqual(board.confirm_all(), "ok")
        self.assertEqual(board.confirmed_count, 3)
        self.assertEqual(board.view()["notice"]["text"], "사진 2장을 확인했다고 표시했어요.")
        self.assertIsNone(board.view()["confirm_ask"])
        self.assertEqual(board.ask_confirm_all(), "none")
        self.assertEqual(board.view()["notice"]["text"], "확인하지 않은 사진이 없어요.")
        self.assertFalse(board.view()["confirm_all"]["enabled"])

    def test_any_other_change_withdraws_the_confirm_line(self):
        for action in (lambda board: board.set_type("p001", "간판"), lambda board: board.move("p001", 1), lambda board: board.remove("p002"), lambda board: board.confirm("p001", True),
                       lambda board: board.add_paths([path_of(9)])):
            board = new_board(2)
            board.ask_confirm_all()
            action(board)
            self.assertEqual(board.confirm_all_asked, 0)
            self.assertEqual(board.confirm_all(), "refused")


class OrderAndRemoveTest(unittest.TestCase):
    def test_moving_changes_the_order_and_never_the_numbers(self):
        board = new_board(3)
        self.assertEqual(board.move("p003", -1), "ok")
        self.assertEqual([(photo.photo_id, photo.display_order) for photo in board.manifest.photos], [("p001", 1), ("p003", 2), ("p002", 3)])
        self.assertEqual(board.move("p001", -1), "edge")
        self.assertEqual(board.move("p002", 1), "edge")
        self.assertEqual(board.view()["notice"]["text"], "더 옮길 수 없어요.")
        self.assertEqual(board.move("p001", 2), "edge")
        self.assertEqual(board.move("p009", 1), "refused")
        rows = board.view()["rows"]
        self.assertEqual([(row["number"], row["up"]["enabled"], row["down"]["enabled"]) for row in rows], [(1, False, True), (3, True, True), (2, True, False)])
        self.assertEqual([row["label"] for row in rows], ["사진 1", "사진 3", "사진 2"])

    def test_removing_drops_the_info_not_the_file_and_the_last_one_can_be_undone(self):
        board = new_board(3)
        board.set_text("p002", "user_note", "비 오는 날")
        board.confirm("p002", True)
        self.assertEqual(board.remove("p002"), "ok")
        self.assertEqual([photo.photo_id for photo in board.manifest.photos], ["p001", "p003"])
        self.assertEqual([photo.display_order for photo in board.manifest.photos], [1, 2])
        self.assertEqual(board.view()["notice"]["text"], "사진 2번을 목록에서 지웠어요. 파일은 그대로 있어요.")
        self.assertEqual(board.view()["undo"]["text"], "지운 사진 되돌리기")
        self.assertEqual(board.undo_remove(), "ok")
        restored = board.photo("p002")
        self.assertEqual((restored.display_order, restored.user_note, restored.confirmed_by_user), (2, "비 오는 날", True))
        self.assertEqual([photo.photo_id for photo in board.manifest.photos], ["p001", "p002", "p003"])
        self.assertIsNone(board.view()["undo"])
        self.assertEqual(board.undo_remove(), "refused")
        self.assertEqual(board.view()["notice"]["text"], "지운 사진을 되돌렸어요.")

    def test_the_undo_goes_away_when_anything_else_changes_and_a_new_photo_never_takes_the_removed_number(self):
        for other in (lambda board: board.set_text("p001", "caption", "설명"), lambda board: board.move("p001", 1), lambda board: board.add_paths([path_of(9)]), lambda board: board.confirm("p001", True)):
            board = new_board(3)
            board.remove("p003")
            other(board)
            self.assertIsNone(board.view()["undo"])
            self.assertEqual(board.undo_remove(), "refused")
        board = new_board(3)
        board.remove("p003")
        board.add_paths([path_of(9)])
        self.assertEqual([photo.photo_id for photo in board.manifest.photos], ["p001", "p002", "p004"], "지운 번호를 새 사진이 물려받지 않는다")

    def test_removing_clears_that_photos_errors_and_notes_only(self):
        board = new_board(2)
        board.set_text("p001", "user_subject", "가" * 61)
        board.set_text("p002", "user_subject", "가" * 61)
        board.remove("p001")
        self.assertEqual(board.error_of("p001", "user_subject"), "")
        self.assertNotEqual(board.error_of("p002", "user_subject"), "")
        self.assertEqual(board.remove("p001"), "refused")


class FilesAndRelinkTest(unittest.TestCase):
    def test_the_file_state_badges_in_the_row(self):
        board = new_board(4, states={path_of(2): "missing", path_of(3): "link", path_of(4): "cloud"})
        board.refresh_files()
        badges = [(row["file"]["state"], row["file"]["badge"], row["file"]["relink"], row["file"]["tone"]) for row in board.view()["rows"]]
        self.assertEqual(badges, [("ok", "파일 있음 · 640×480", False, "ok"), ("missing", "파일 없음", True, "warn"), ("link", "링크라서 쓰지 않아요", True, "warn"), ("cloud", "내려받지 않은 파일이에요", False, "warn")])
        self.assertTrue(all(row["file"]["a11y"].startswith(f"사진 {row['number']} 파일 상태") for row in board.view()["rows"]))

    def test_a_crashing_check_leaves_the_states_unknown_and_tells_the_user(self):
        board = new_board(1)
        board.provider.fail.add("check")
        self.assertEqual(board.refresh_files(), "failed")
        self.assertEqual(board.view()["notice"]["level"], "error")
        self.assertEqual(row_of(board)["file"]["badge"], "아직 확인하지 않았어요")
        self.assertEqual(board.open(), board.generation)
        self.assertTrue(board.is_open)

    def test_a_big_png_keeps_working_but_the_row_says_no_preview(self):
        board = new_board(verdicts={path_of(1, "png"): R.Verdict(R.OK, "", "", 12_000, 12_000, "png"), path_of(2): R.Verdict(R.OK, "", "", 12_000, 12_000, "jpeg")})
        board.add_paths([path_of(1, "png"), path_of(2)])
        rows = board.view()["rows"]
        self.assertEqual([row["preview"]["blocked"] for row in rows], [True, False])
        self.assertEqual(rows[0]["preview"]["blocked_text"], "너무 커서 미리보기를 못 만들어요")
        self.assertEqual(rows[0]["file"]["state"], "ok", "사진은 그대로 쓸 수 있다")

    def test_relinking_checks_the_new_file_and_resets_the_confirmation(self):
        board = new_board(2, states={path_of(1): "missing"})
        board.refresh_files()
        board.confirm("p001", True)
        self.assertEqual(board.relink("p001", path_of(1, "png")), "ok")
        self.assertEqual(board.photo("p001").local_path, path_of(1, "png"))
        self.assertFalse(board.photo("p001").confirmed_by_user)
        self.assertEqual(row_of(board)["file"]["state"], "ok")
        self.assertEqual(board.view()["notice"]["text"], "사진 파일을 다시 연결했어요.")
        self.assertEqual(board.relink("p001", path_of(2)), "refused", "다른 사진이 이미 쓰는 파일")
        self.assertEqual(board.view()["notice"]["text"], "이미 넣은 사진이에요.")
        self.assertEqual(board.relink("p001", "relative.jpg"), "refused")
        self.assertEqual(board.relink("p001", path_of(5, "gif")), "refused")
        self.assertEqual(board.relink("p001", ""), "cancelled")
        self.assertEqual(board.relink("p001", None), "cancelled")
        self.assertEqual(board.relink("p009", path_of(7)), "refused")
        self.assertEqual(board.photo("p001").local_path, path_of(1, "png"))

    def test_the_view_never_carries_a_path_only_the_file_name_and_the_preview_reader_gets_it_separately(self):
        board = new_board(2)
        board.set_text("p001", "user_note", "메모")
        shown = dumped(board) + repr(board.view()) + repr(board.card())
        for marker in (USER_DIR, "C:/", "C:\\", "Pictures", "/Users/"):
            self.assertNotIn(marker, shown)
        self.assertEqual(row_of(board)["file_name"], f"{FILE_STEM}-01.jpg")
        self.assertEqual(board.local_path("p001"), path_of(1), "미리보기를 읽는 화면 층만 부른다")
        self.assertEqual(board.local_path("p009"), "")
        self.assertNotIn(USER_DIR, repr(vars(board)) + repr(board.states) + repr(board.manifest))


class ListsAndCloseTest(unittest.TestCase):
    def test_types_and_settings_can_be_added_and_removed_but_not_what_photos_use_or_the_protected_type(self):
        board = new_board(1)
        self.assertEqual(board.add_type("테이블 위"), "ok")
        self.assertIn("테이블 위", board.types)
        self.assertEqual(board.add_type("테이블 위"), "invalid")
        self.assertEqual(board.view()["lists"]["notice"]["text"], "이미 있는 이름이에요.")
        self.assertEqual(board.add_type("간판"), "invalid")
        self.assertEqual(board.add_type("  "), "invalid")
        self.assertEqual(board.add_type("가" * 21), "invalid")
        self.assertEqual(board.add_type(scan_samples.google()), "invalid")
        self.assertEqual(board.add_type(None), "invalid")
        self.assertEqual(board.set_type("p001", "테이블 위"), "ok", "더한 종류를 쓸 수 있다")
        self.assertEqual(board.remove_type("테이블 위"), "refused")
        self.assertEqual(board.view()["lists"]["notice"]["text"], "사진에서 쓰고 있어서 지울 수 없어요.")
        board.set_type("p001", "간판")
        self.assertEqual(board.remove_type("테이블 위"), "ok")
        self.assertEqual(board.remove_type("기타"), "refused")
        self.assertEqual(board.view()["lists"]["notice"]["text"], "‘기타’ 는 지울 수 없어요.")
        self.assertEqual(board.remove_type("없는 종류"), "refused")
        self.assertEqual(board.add_setting("발코니"), "ok")
        self.assertEqual(board.set_setting("p001", "발코니"), "ok")
        self.assertEqual(board.remove_setting("발코니"), "refused")
        board.set_setting("p001", "")
        self.assertEqual(board.remove_setting("발코니"), "ok")
        self.assertEqual(board.add_setting("테라스"), "invalid")

    def test_a_list_holds_twenty_names(self):
        board = new_board()
        for number in range(rules.MAX_LIST_ITEMS - len(board.types)):
            self.assertEqual(board.add_type(f"종류 {number}"), "ok")
        self.assertEqual(len(board.types), 20)
        self.assertEqual(board.add_type("하나 더"), "invalid")
        self.assertEqual(board.view()["lists"]["notice"]["text"], "목록에는 20개까지 둘 수 있어요.")

    def test_the_lists_view_marks_what_can_be_removed_and_clearing_keeps_the_edited_lists(self):
        board = new_board(1)
        board.set_type("p001", "간판")
        board.set_setting("p001", "야경")
        lists = board.view()["lists"]
        removable = {item["name"]: item["removable"] for item in lists["types"]["items"]}
        self.assertFalse(removable["간판"] and removable["기타"])
        self.assertTrue(removable["메뉴판"])
        self.assertFalse(removable["기타"])
        self.assertFalse({item["name"]: item["removable"] for item in lists["settings"]["items"]}["야경"])
        board.add_type("내가 더한 종류")
        board.clear()
        self.assertIn("내가 더한 종류", board.types, "목록 고침은 앱이 사는 동안 그대로다")
        self.assertEqual(board.count, 0)

    def test_closing_warns_once_about_a_rejected_text_and_then_closes_and_shutdown_never_warns(self):
        board = new_board(1)
        board.open()
        board.set_text("p001", "user_subject", "가" * 61)
        self.assertEqual(board.close(), pv.CLOSE_WARNED)
        self.assertTrue(board.is_open)
        self.assertIn("그 글은 버리고 닫아요", board.view()["notice"]["text"])
        self.assertEqual(board.close(), "closed")
        self.assertFalse(board.is_open)
        self.assertEqual(board.error_of("p001", "user_subject"), "")
        board.open()
        board.set_text("p001", "user_subject", "가" * 61)
        self.assertEqual(board.shutdown(), "closed")
        self.assertFalse(board.is_open)
        clean = new_board(1)
        clean.open()
        self.assertEqual(clean.close(), "closed")

    def test_closing_clears_the_transient_parts_but_keeps_the_photos(self):
        board = new_board(2)
        board.open()
        board.add_paths([path_of(3, "gif")])
        board.remove("p002")
        board.ask_confirm_all()
        board.close()
        view = board.view()
        self.assertEqual((view["rejected"], view["undo"], view["confirm_ask"], view["notice"]), (None, None, None, None))
        self.assertEqual(board.count, 1)

    def test_the_board_is_cleared_for_a_new_draft(self):
        board = new_board(3)
        board.confirm("p001", True)
        board.open()
        generation = board.generation
        board.clear()
        self.assertEqual((board.count, board.is_open, board.confirmed_count, board.rejected, board.errors), (0, False, 0, (), {}))
        self.assertGreater(board.generation, generation)
        board.add_paths([path_of(1)])
        self.assertEqual(board.manifest.photos[0].photo_id, "p001", "새 초안은 번호를 처음부터 센다")


class ViewTest(unittest.TestCase):
    def test_the_view_of_an_empty_board(self):
        view = new_board().view()
        self.assertEqual((view["title"], view["count"]["text"], view["empty"]), ("사진 정리", "사진 0장 · 확인 0/0", T["pho_empty"]))
        self.assertEqual(view["rows"], [])
        self.assertTrue(view["add"]["enabled"])
        self.assertFalse(view["confirm_all"]["enabled"])
        self.assertEqual(view["full"], "")
        self.assertIsNone(view["undo"])
        self.assertIn("30장", view["limits"])
        self.assertIn("60자", view["limits"])
        self.assertIn("300자", view["limits"])
        self.assertIn("100자", view["limits"])
        self.assertIn("밖으로 보내지 않아요", view["intro"])

    def test_a_row_has_everything_the_screen_draws_and_the_inputs_are_never_folded(self):
        board = new_board(2)
        board.set_type("p001", "간판")
        board.set_setting("p001", "야경")
        row = row_of(board)
        self.assertEqual(set(row), {"photo_id", "number", "label", "file_name", "a11y", "type", "setting", "subject", "note", "caption", "place", "confirmed", "confirm", "changed_note", "file", "preview", "up", "down", "remove"})
        self.assertEqual(row["type"]["choices"], list(rules.TYPES))
        self.assertEqual([value for value, _text in row["setting"]["choices"]], ["", *rules.SETTINGS])
        self.assertEqual(row["setting"]["choices"][0], ("", "정하지 않음"))
        self.assertEqual((row["type"]["value"], row["setting"]["value"]), ("간판", "야경"))
        self.assertEqual(row["place"]["section"]["value"], "도입")
        self.assertTrue(row["place"]["open"], "값이 있으면 자리 정하기를 펼쳐 둔다")
        self.assertFalse(row_of(board, "p002")["place"]["open"])
        self.assertEqual(row["confirm"]["text"], "확인했어요 — 이 내용을 초안에 써요")
        self.assertIn("사진 1, 종류 간판", row["a11y"])
        for key in ("type", "setting", "subject", "note", "caption"):
            self.assertIn("사진 1", row[key]["a11y"], key)
        self.assertEqual(row["place"]["nth"]["visible"], False)
        board.set_placement("p001", "after_paragraph", 3)
        place = row_of(board)["place"]
        self.assertEqual((place["nth"]["visible"], place["nth"]["value"], place["nth"]["text"]), (True, 3, "3번째"))

    def test_a_custom_type_or_setting_the_photo_already_has_stays_in_its_choices(self):
        board = new_board(1)
        board.add_type("임시 종류")
        board.set_type("p001", "임시 종류")
        board.types.remove("임시 종류")                              # 목록에서 사라져도(코드로) 사진이 가진 종류는 선택지에 남는다
        self.assertIn("임시 종류", row_of(board)["type"]["choices"])

    def test_the_card_for_the_draft_screen(self):
        board = new_board()
        card = board.card()
        self.assertEqual((card["has"], card["count"], card["button"], card["unsaved"]), (False, "넣은 사진이 없어요", "사진 넣기", ""))
        board.add_paths([path_of(1), path_of(2)])
        board.confirm("p001", True)
        card = board.card()
        self.assertEqual((card["has"], card["count"], card["button"]), (True, "사진 2장 · 확인 1/2", "사진 정리 열기"))
        self.assertEqual((card["unsaved"], card["trash"]), ("", None), "사진을 넣었다고 저장 안내를 보이지는 않는다 — 고쳤는데 저장 안 했을 때만(3단계)")
        self.assertEqual(board.card(unsaved=True)["unsaved"], "사진 정보를 고쳤어요. 초안을 저장해야 사진 정보도 함께 저장돼요.")
        trash = board.card(trash=True)["trash"]
        self.assertEqual((trash["text"], trash["restore"], trash["clear"]), ("지운 초안의 사진 정보를 되돌릴 사본으로 남겨 뒀어요. 사진 파일은 그대로 있어요.", "사진 정보 되돌리기", "사진 정보 사본 비우기"))
        self.assertIn("밖으로 보내지 않아요", card["hint"])
        self.assertEqual(card["row_title"], "사진 넣기(선택)")


def engine(number, topic, keyword, channel="naver_a"):
    return ucd.build_candidate(number, topic, channel, "top", keywords=(keyword, "예시 보조 낱말"), status="NEW")


class DraftsControllerTest(unittest.TestCase):
    ROW = engine(901, "예시 후보 가 — 분야를 알 수 없는 안내", "예시 낱말 가")

    def made(self):
        controller = dv.DraftsController(drafts.FakeDraftsProvider(lambda: [self.ROW]), jobs.JobRunner())
        controller.open_target(drafts.DraftTarget(self.ROW.candidate_id, self.ROW.topic, self.ROW.channel, "예시 블로그 가", safety.assess(self.ROW).stop, True))
        results = {}
        status, job = controller.start_make(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
        job.join(30)
        controller.apply_made(results["ok"])
        return controller

    def test_the_controller_has_a_board_and_the_views_carry_the_card_without_changing_anything_else(self):
        controller = self.made()
        self.assertIsInstance(controller.photos, pv.PhotoBoard)
        normal = controller.view()["normal"]
        self.assertEqual(set(normal["side"]), {"inspect", "garbage", "keywords", "tags", "category", "summary", "photos", "image", "checks"})
        self.assertEqual(normal["side"]["photos"], controller.photos_card())
        self.assertEqual(normal["options"]["photos"], controller.photos_card())
        self.assertEqual({key: value for key, value in normal["side"]["photos"].items() if key != "remake"}, controller.photos.card(), "컨트롤러의 카드는 사진 카드에 '다시 만들기 안내' 한 칸만 더한다")
        self.assertEqual(normal["side"]["photos"]["remake"], "", "사진을 안 만졌으면 안내가 없다")
        self.assertEqual(set(normal["options"]) - {"photos"}, {"open", "toggle", "title", "note", "blog_title", "blogs", "type_title", "types", "fields", "apply", "pending", "pending_text"})
        self.assertEqual(normal["side"]["photos"]["count"], "넣은 사진이 없어요")

    def test_making_and_remaking_a_draft_does_not_touch_the_photos_and_having_none_changes_nothing(self):
        controller = self.made()
        title, body = controller.title, controller.body
        controller.photos.add_paths([path_of(1), path_of(2)])
        controller.photos.confirm("p001", True)
        self.assertEqual(controller.title, title)
        self.assertEqual(controller.body, body, "사진을 넣어도 글은 그대로다(초안 연결은 3단계)")
        results = {}
        status, job = controller.start_make(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
        job.join(30)
        controller.apply_made(results["ok"])
        self.assertEqual(controller.photos.count, 2, "다시 만들어도 사진 목록은 남는다")
        self.assertFalse(controller.text_unsaved(), "사진을 넣어도 글은 안 바뀌었다 — 다시 만들기 확인은 글만 본다")
        self.assertTrue(controller.photos_unsaved() and controller.has_unsaved(), "사진 정보를 고쳤다(저장 전)")
        self.assertEqual(controller.save_state(), self.made().save_state())

    def test_a_made_draft_is_the_same_with_or_without_photo_operations(self):
        """사진이 없으면 초안 만들기·저장 상태·화면 뷰모델이 지금과 같고, 사진을 넣고 확인하고 고치고 지워도 글·저장 상태·뷰모델(사진 카드 말고)은 그대로다(초안 연결은 3단계)."""
        plain, busy = self.made(), self.made()
        busy.photos.open()
        busy.photos.add_paths([path_of(1), path_of(2)])
        busy.photos.confirm("p001", True)
        busy.photos.set_text("p001", "user_note", "비 오는 날")
        busy.photos.remove("p002")
        busy.photos.close()

        def without_photos(controller):
            normal = dict(controller.view()["normal"])
            normal["side"] = {key: value for key, value in normal["side"].items() if key != "photos"}
            normal["options"] = {key: value for key, value in normal["options"].items() if key != "photos"}
            return normal

        self.assertEqual((plain.title, plain.body, plain.text_unsaved(), plain.save_state()), (busy.title, busy.body, busy.text_unsaved(), busy.save_state()))
        self.assertEqual(without_photos(plain), without_photos(busy))
        self.assertEqual((plain.has_unsaved(), busy.has_unsaved()), (False, True), "사진 정보를 고쳤으면 떠나기·닫기 앞에서 묻는다(3단계 — 사진 정보도 저장한다)")
        self.assertEqual(plain.photos.card()["count"], "넣은 사진이 없어요")
        self.assertEqual(busy.photos.card()["count"], "사진 1장 · 확인 0/1")

    def test_a_new_draft_leaving_the_screen_and_opening_a_saved_draft_clear_the_photos(self):
        controller = self.made()
        controller.photos.add_paths([path_of(1)])
        controller.leave()
        self.assertEqual(controller.photos.count, 0)
        controller = self.made()
        controller.photos.add_paths([path_of(1)])
        controller.open_target(drafts.DraftTarget(self.ROW.candidate_id, self.ROW.topic, self.ROW.channel, "예시 블로그 가", False, True))
        self.assertEqual(controller.photos.count, 0)

    def test_the_app_state_wires_the_provider_and_a_provider_can_be_injected(self):
        from chanceblog_desktop.ui.core import app_state
        state = app_state.AppState()
        self.assertIsInstance(state.drafts.photos.provider, pv.FakePhotoProvider)
        fake = pv.FakePhotoProvider()
        self.assertIs(app_state.AppState(photos=fake).drafts.photos.provider, fake)


class SourceRulesTest(unittest.TestCase):
    FILES = ("photo_rules.py", "photo_view.py", "photo_text.py")

    def test_the_pure_files_know_no_screen_tool_no_files_no_network_no_output(self):
        forbidden = {"PySide6", "subprocess", "socket", "urllib", "http", "ssl", "webbrowser", "ctypes", "requests", "asyncio", "logging", "traceback", "shutil", "tempfile", "random", "secrets", "time", "datetime", "pathlib"}
        banned_calls = {"open", "print", "input", "exec", "eval", "os.stat", "os.lstat", "os.listdir", "os.scandir", "os.remove", "os.replace", "os.makedirs", "Path"}
        for name in self.FILES:
            tree = ast.parse((UI_CORE / name).read_text(encoding="utf-8"))
            imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
            imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
            self.assertFalse(imported & forbidden, (name, imported & forbidden))
            calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
            self.assertFalse(calls & banned_calls, (name, calls & banned_calls))
            self.assertNotIn("sys.stdout", (UI_CORE / name).read_text(encoding="utf-8"))

    def test_nothing_in_the_core_files_writes_a_path_or_a_typed_text_into_an_error(self):
        source = (UI_CORE / "photo_view.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        providers = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in ("PhotoProvider", "FakePhotoProvider")]
        self.assertEqual(len(providers), 2)
        inside_fake = {id(node) for provider in providers for node in ast.walk(provider)}
        for node in ast.walk(tree):
            if id(node) in inside_fake:
                continue                                                                       # 공급자 약속(미구현 표시)과 가짜 공급자(시험용으로 일부러 터뜨림)만 오류를 낸다
            if isinstance(node, ast.Raise) or (isinstance(node, ast.Call) and ast.unparse(node.func) in ("AppError", "RuntimeError", "ValueError", "Exception")):
                self.fail("이 파일은(공급자 약속·가짜 공급자 밖에서는) 오류를 새로 만들어 내지 않는다: " + ast.unparse(node)[:60])
        self.assertEqual(source.count("error.__traceback__ = None"), source.count("except AppError as error"), "잡은 규칙 오류마다 호출 흔적을 끊는다")
        self.assertGreaterEqual(source.count("error.__traceback__ = None"), 2)
        for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and id(node) not in inside_fake):
            body = ast.unparse(handler)
            for leak in ("str(error", "repr(error", "error.args", "error.message", "format(error"):
                self.assertNotIn(leak, body, "잡은 오류의 글을 그대로 다른 곳에 쓰지 않는다")

    PHOTO_FILES = {
        "content/photo_manifest.py": "1단계 — 사진 정보 규칙", "service/photo_manifest.py": "1단계 — 사진 정보 보관·사진 파일 읽기 확인", "ui/core/photo_rules.py": "2단계 — 화면의 규칙표", "ui/core/photo_text.py": "2단계 — 화면 문구",
        "ui/core/photo_view.py": "2단계 — 사진 정리 컨트롤러", "ui/photo_adapter.py": "2단계 — 실제 사진 공급자(읽기만)", "ui/qt/photo_parts.py": "2단계 — 줄 부품", "ui/qt/photo_screen.py": "2단계 — 사진 정리 창",
        "ui/adapters.py": "홈 공급자의 짝 사진 공급자(읽기만)", "ui/core/app_state.py": "짝 공급자를 초안 컨트롤러의 사진 목록에 연결", "ui/core/drafts_view.py": "초안 컨트롤러가 사진 목록(메모리)을 들고 카드 뷰모델을 낸다",
        "content/draft_body.py": "본문 생성기가 확정한 사진(`DraftPhoto`)을 받아 사진 줄을 끼운다(3단계 본문 연결) — 사진을 안 주면 지금과 같다", "content/photo_flow.py": "사진 줄을 본문 블록에 끼우는 순수 함수(3단계 본문 연결)", "service/draft_engine.py": "엔진 후보로 초안을 만들 때 확정한 사진을 본문 생성기에 넘긴다(3단계 본문 연결)",
        "ui/core/drafts.py": "저장한 초안 공급자의 값(사진 정보 저장·열기·지우기 결과)과 가짜 공급자(3단계)", "ui/drafts_adapter.py": "저장한 초안 공급자가 사진 정보를 함께 저장·열기·사본으로 옮기기·되돌리기·사본 비우기(3단계, 확인 024)",
        "ui/core/text.py": "문구 합치기(PHOTO_T)", "ui/qt/draft_screen.py": "'사진' 카드와 '사진 넣기(선택)' 줄", "ui/qt/shell.py": "사진 정리 창 열기·닫기·Esc",
        "ui/core/attribution.py": "기존 — 이미지 출처 표기(사진 정리와 무관)", "ui/qt/components.py": "기존 — 공통 부품 설명(사진 정리와 무관)",
    }

    def test_only_the_listed_source_files_mention_photos_so_saving_making_exporting_and_backup_are_untouched(self):
        """3단계(초안 연결) 전에는 초안 저장(`draft_store`·`saved_draft`)·글 만들기(엔진·`DraftOptions`)·내보내기·백업 코드가 사진을 모른다 — 새로 사진 이야기가 나오는 파일은 이유와 함께 여기에 더한다."""
        src = ROOT / "src" / "chanceblog_desktop"
        found = sorted(path.relative_to(src).as_posix() for path in src.rglob("*.py") if "photo" in path.read_text(encoding="utf-8").lower())
        self.assertEqual(found, sorted(self.PHOTO_FILES), "사진을 새로 말하는 파일은 이유와 함께 PHOTO_FILES 에 더한다")
        self.assertTrue(all(reason.strip() for reason in self.PHOTO_FILES.values()))
        for untouched in ("service/draft_store.py", "content/saved_draft.py", "content/draft_options.py", "service/backup_flow.py"):
            if (src / untouched).exists():
                self.assertNotIn("photo", (src / untouched).read_text(encoding="utf-8").lower(), untouched)

    def test_every_tone_the_sheet_uses_has_a_readable_text_color_on_every_surface(self):
        """글자 대비 — 사진 정리 화면이 글에 입히는 계열(`set_tone` 과 `TONE` 표)의 글자색은 바탕(면·앱 바탕·옅은 면) 어디서나 대비 4.5 이상이다(토큰 시험이 계열마다 따로도 지킨다 — 여기서는 이 화면이 실제로 쓰는 것만 본다)."""
        from chanceblog_desktop.ui.core import tokens
        colors = tokens.palette()
        used = set()
        for name in ("photo_parts.py", "photo_screen.py"):
            tree = ast.parse((UI_QT / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "set_tone":
                    for argument in node.args:
                        used |= {item.value for item in ast.walk(argument) if isinstance(item, ast.Constant) and isinstance(item.value, str)}
                if isinstance(node, ast.Assign) and any(getattr(target, "id", "") == "TONE" for target in node.targets):
                    used |= {item.value for item in node.value.values if isinstance(item, ast.Constant)}
        used &= set(tokens.TONES)                                                     # 인자에 든 다른 글(칸 이름 등)은 계열이 아니다
        self.assertEqual(used, {"blue", "green", "orange", "red", "slate"}, "이 화면이 쓰는 계열 — 새 계열을 쓰면 여기서 대비를 다시 본다")
        for tone in sorted(used):
            text_color = colors[tokens.TONES[tone][2]]
            for background in ("surface", "bg_app", "surface_2"):
                self.assertGreaterEqual(tokens.contrast(text_color, colors[background]), 4.5, (tone, background))
        self.assertGreaterEqual(tokens.contrast(colors["text_secondary"], colors["surface"]), 5.4, "보조 글(안내·글자 수·예시)은 5.4 이상")

    def test_the_pure_files_import_only_the_repository_modules_they_need(self):
        """순수 파일이 서비스·초안 저장·초안 목록 같은 쪽을 가져오지 않는다 — 이 저장소 안에서 가져오는 모듈이 정해진 것뿐이다."""
        expected = {"photo_rules.py": {"content.photo_manifest", "imagerules", "text"}, "photo_view.py": {"content.photo_manifest", "errors", "imagerules", "photo_rules", "text"}, "photo_text.py": set()}
        for name, wanted in expected.items():
            tree = ast.parse((UI_CORE / name).read_text(encoding="utf-8"))
            found = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:                              # 이 저장소 안의 모듈(상대 가져오기)만
                    for alias in node.names:
                        found.add(alias.name if node.module is None else (f"{node.module}.{alias.name}" if node.module == "content" else node.module))
            self.assertEqual(found, wanted, name)

    def test_the_view_core_reuses_the_stage_one_rules_and_never_its_own_limits(self):
        source = (UI_CORE / "photo_view.py").read_text(encoding="utf-8")
        for needle in ("pm.update_photo", "pm.check_text", "pm.add_photo", "pm.move_photo", "pm.remove_photo", "pm.set_confirmed", "pm.path_problem", "pm.MAX_PHOTOS"):
            self.assertIn(needle, source, needle)
        rules_source = (UI_CORE / "photo_rules.py").read_text(encoding="utf-8")
        for needle in ("pm.DEFAULT_PHOTO_TYPES", "pm.DEFAULT_SETTINGS", "pm.MAX_SUBJECT", "pm.MAX_NOTE", "pm.MAX_CAPTION", "pm.NEEDS_NTH"):
            self.assertIn(needle, rules_source, needle)


if __name__ == "__main__":
    unittest.main()
