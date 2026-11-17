"""사진 Manifest 핵심 규칙(`content/photo_manifest.py` — 순수 파이썬, 사진 연동 초안 1단계, 결정 D-496·D-497) 시험. 네트워크·실제 시크릿·화면 도구(PySide6) 없이 돈다. 파일은 만들지 않는다.

지키는 것:
  1) 모양 — 사진 한 장의 칸은 운영자가 정한 열네 가지뿐이고(EXIF·썸네일 같은 다른 칸은 쓰지도 읽지도 않는다) 저장하는 글은 결정적이다(UTF-8·BOM 없음·키 정렬·왕복 같음).
  2) 한도 — 사진 30장·대상 60자·메모 300자·설명 글 100자·종류 20자·위치 60자·분석 항목 20개·200자의 경계(되는 값과 안 되는 값).
  3) 경로 — 절대 경로만, 인터넷 주소·네트워크 위치·와일드카드·`..`·장치 이름·대체 스트림·260자 초과·지원하지 않는 확장자 거절. 확장자 목록은 `imagerules` 의 것을 읽는다(복사하지 않는다). `own_posts` 의 경로 모양 규칙과 같은 결과.
  4) 확정한 것만 초안으로 — 확정하지 않은 사진·확인하지 않은 분석 항목은 초안 입력에 없고, 경로·파일 이름·`photo_id` 문자열은 어떤 출력에도 없다(이 시험이 표식 글로 못박는다).
  5) 분석 결과는 기본으로 저장하지 않고, 사람의 얼굴·관계·감정·신원을 짐작한 말과 키·토큰·개인 번호 모양은 받지 않는다.
  6) 번호·순서 — 지운 사진의 번호를 다시 쓰지 않고, 순서는 빈틈없이 1부터이고, 내용을 고치면 확정이 풀린다.
  7) 자리표시자 `{{사진 N}}` — 정확한 모양만 인정하고 본문과 목록의 어긋남(없는 사진·확정 전 사진·빠진 사진·되풀이·순서)을 알린다.
  8) 엄격하게 읽기·고정 문장 오류 — 모르는 칸·잘못된 종류·중복 키·BOM·너무 큰 글 거절, 오류 어디에도 경로·글이 없다.
CI 는 윈도·리눅스 × 3.10·3.12 네 칸이다 — 경로 시험은 윈도 모양(`C:\\…`)을 글자로만 다뤄 어느 운영체제에서나 같고, 정렬·대소문자·긴 파일 이름에 기대지 않는다.
"""
import ast
import dataclasses
import json
import os
import sys
import traceback
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import scan_samples  # noqa: E402
from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.content import saved_draft as sd  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import own_posts  # noqa: E402
from chanceblog_desktop.ui.core import imagerules  # noqa: E402

SOURCE = ROOT / "src" / "chanceblog_desktop" / "content" / "photo_manifest.py"
USER_DIR, FILE_STEM = "UNIQ-USERDIR-q7w2", "UNIQ-FILE-k3x9"
DRAFT_ID = "dd-" + "0123456789abcdef0123"
EXIF_KEYS = ("exif", "gps", "thumbnail", "camera", "taken_at", "latitude", "image", "bytes", "hash")


def win(name, folder=USER_DIR):
    return f"C:\\Users\\{folder}\\Pictures\\{name}"


def path_of(number):
    return win(f"{FILE_STEM}-{number:02d}.jpg")


def build(count=3, **fields):
    """사진 `count` 장짜리 목록(경로 `…\\UNIQ-FILE-k3x9-01.jpg` …)."""
    manifest = pm.empty_manifest()
    for number in range(1, count + 1):
        manifest, _id = pm.add_photo(manifest, path_of(number), photo_type="음식", **fields)
    return manifest


def confirmed(manifest, *photo_ids):
    for photo_id in photo_ids:
        manifest = pm.set_confirmed(manifest, photo_id, True)
    return manifest


def code_of(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except AppError as error:
        return error
    raise AssertionError("AppError 가 나지 않았다")


def channels(error):
    """오류가 사람이나 기록에 나갈 수 있는 모든 글."""
    shown = error.rendered()
    trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    return {"str": str(error), "repr": repr(error), "args": repr(error.args), "slots": repr(error.slots), "detail": error.detail, "log": error.log_line(), "message": shown.message, "action": shown.action,
            "trace": trace}


class Base(unittest.TestCase):
    def assertRefuses(self, function, *args, code="CONTENT_INVALID", **kwargs):
        error = code_of(function, *args, **kwargs)
        self.assertEqual(error.code, code)
        return error

    def assertNoLeak(self, error, markers):
        for name, text in channels(error).items():
            for marker in markers:
                self.assertNotIn(marker, text, f"{name} 에 표식 글이 있다")


class ShapeTest(Base):
    def test_a_photo_has_exactly_the_fourteen_fields_the_operator_named_and_the_envelope_has_four(self):
        self.assertEqual(pm.FIELDS, ("photo_id", "local_path", "display_order", "photo_type", "analysis_method", "observed_objects", "visible_text", "setting", "user_subject", "user_note",
                                     "preferred_section", "placement", "confirmed_by_user", "caption"))
        self.assertEqual(pm.SCHEMA, "chanceblog.photo-manifest/1")
        data = build(2).to_dict()
        self.assertEqual(set(data), {"schema", "draft_id", "next_number", "photos"})
        for photo in data["photos"]:
            self.assertEqual(set(photo), set(pm.FIELDS))
        self.assertEqual(set(data["photos"][0]["placement"]), {"kind", "nth"})

    def test_the_text_is_deterministic_utf8_without_bom_with_sorted_keys_and_one_trailing_newline(self):
        manifest = confirmed(build(3, user_subject="반찬 다섯 가지"), "p002")
        text = manifest.to_text()
        self.assertEqual(text, build_again(manifest).to_text())
        self.assertEqual(text, json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", "context.write_json 이 쓰는 글자와 같다")
        self.assertTrue(text.endswith("}\n") and not text.endswith("\n\n"))
        self.assertNotEqual(text[:1], "\ufeff")
        self.assertIn("반찬 다섯 가지", text, "한글을 이스케이프하지 않는다")
        self.assertNotIn("\\u", text)
        self.assertEqual(text.encode("utf-8").decode("utf-8"), text)
        keys = [line.strip().split('"')[1] for line in text.splitlines() if line.startswith("  ") and line.strip().startswith('"') and line.count('"') >= 2 and not line.startswith("    ")]
        self.assertEqual(keys, sorted(keys), "맨 바깥 키가 정렬돼 있다")

    def test_a_round_trip_returns_the_same_manifest_including_analysis_when_it_is_kept(self):
        manifest, dropped = pm.set_analysis(confirmed(build(2, user_note="메모"), "p001"), "p002", method="local:paddleocr", objects=["접시", "국자"], texts=["된장찌개 9,000원"])
        self.assertEqual(dropped, 0)
        manifest = pm.confirm_item(manifest, "p002", pm.TEXTS, 0)
        for keep in (False, True):
            with self.subTest(persist_analysis=keep):
                loaded = pm.PhotoManifest.from_text(manifest.to_text(persist_analysis=keep))
                if keep:
                    self.assertEqual(loaded, manifest)
                else:
                    self.assertEqual(loaded, dataclasses.replace(manifest, photos=tuple(dataclasses.replace(p, observed_objects=(), visible_text=(), analysis_method="manual") for p in manifest.photos)))
        self.assertEqual(pm.PhotoManifest.from_text(build(0).to_text()), build(0))

    def test_when_the_analysis_results_are_not_written_the_method_name_is_written_as_manual_too(self):
        """남은 결과가 없는데 '분석했다' 는 이름(`local:paddleocr`)만 파일에 남으면 다시 열었을 때 분석한 사진처럼 보인다 — 결과를 안 쓰면 방법도 `manual` 로 쓰고, 결과를 쓰기로 하면 방법도 그대로 쓴다."""
        manifest, _dropped = pm.set_analysis(build(1), "p001", method="local:paddleocr", texts=["메뉴"])
        self.assertEqual(manifest.photos[0].analysis_method, "local:paddleocr", "메모리에서는 그대로다")
        self.assertEqual(manifest.to_dict()["photos"][0]["analysis_method"], "manual")
        self.assertEqual(json.loads(manifest.to_text())["photos"][0]["analysis_method"], "manual")
        self.assertEqual(manifest.to_dict(persist_analysis=True)["photos"][0]["analysis_method"], "local:paddleocr")
        self.assertEqual(pm.PhotoManifest.from_text(manifest.to_text()).photos[0].analysis_method, "manual")
        empty, _dropped = pm.set_analysis(build(1), "p001", method="local:paddleocr")
        self.assertEqual(pm.PhotoManifest.from_text(empty.to_text(persist_analysis=True)).photos[0].analysis_method, "local:paddleocr", "분석했지만 아무것도 못 찾은 것도 쓰기로 했으면 남는다")

    def test_no_exif_or_other_extra_field_is_ever_written_or_accepted(self):
        data = build(1).to_dict()
        text = build(1).to_text()
        for key in EXIF_KEYS:
            self.assertNotIn(f'"{key}"', text)
            extra = json.loads(text)
            extra["photos"][0][key] = "x"
            self.assertRefuses(pm.PhotoManifest.from_dict, extra)
            outer = json.loads(text)
            outer[key] = "x"
            self.assertRefuses(pm.PhotoManifest.from_dict, outer)
        missing = json.loads(text)
        del missing["photos"][0]["caption"]
        self.assertRefuses(pm.PhotoManifest.from_dict, missing)
        self.assertEqual(data["photos"][0]["analysis_method"], "manual")

    def test_the_reprs_of_photos_and_manifests_never_show_paths_or_texts(self):
        manifest = pm.empty_manifest()
        for number in (1, 2):
            manifest, _id = pm.add_photo(manifest, path_of(number), photo_type="UNIQ-TYPE-h8", setting="UNIQ-SETTING-f6", preferred_section="UNIQ-SECTION-g7", user_subject="UNIQ-SUBJECT-a1", user_note="UNIQ-NOTE-b2",
                                         caption="UNIQ-CAP-c3")
        manifest = confirmed(manifest, "p001")
        manifest, _dropped = pm.set_analysis(manifest, "p002", method="local:x", objects=["UNIQ-OBJ-d4"], texts=["UNIQ-TXT-e5"])
        shown = repr(manifest) + repr(manifest.photos[0]) + str(manifest.photos[1]) + repr(manifest.photos[1].observed_objects[0]) + repr(pm.draft_inputs(manifest))
        for marker in (USER_DIR, FILE_STEM, "UNIQ-SUBJECT-a1", "UNIQ-NOTE-b2", "UNIQ-CAP-c3", "UNIQ-OBJ-d4", "UNIQ-TXT-e5", "UNIQ-TYPE-h8", "UNIQ-SETTING-f6", "UNIQ-SECTION-g7"):
            self.assertNotIn(marker, shown, "경로·종류·장소 분위기·들어갈 위치·대상·메모·설명 글·분석 글은 repr 에 나오지 않는다")


def build_again(manifest):
    return pm.PhotoManifest(manifest.photos, manifest.next_number, manifest.draft_id)


class LimitTest(Base):
    def test_thirty_photos_fit_and_the_thirty_first_is_refused(self):
        manifest = build(pm.MAX_PHOTOS)
        self.assertEqual(len(manifest.photos), 30)
        error = self.assertRefuses(pm.add_photo, manifest, path_of(31))
        self.assertIn("30장", error.rendered().message)
        self.assertEqual(len(manifest.photos), 30)
        extra = dataclasses.replace(manifest.photos[0], photo_id="p031", local_path=path_of(31), display_order=30)
        self.assertRefuses(pm.PhotoManifest, (*manifest.photos, extra), 32)

    def test_every_text_limit_accepts_the_edge_and_refuses_one_more(self):
        edges = {"user_subject": 60, "user_note": 300, "caption": 100, "preferred_section": 60, "photo_type": 20, "setting": 20, "observation": 200}
        for name, high in edges.items():
            with self.subTest(field=name, high=high):
                text, reason = pm.check_text(name, "가" * high)
                self.assertEqual((text, reason), ("가" * high, None))
                text, reason = pm.check_text(name, "가" * (high + 1))
                self.assertIsNone(text)
                self.assertIn(f"{high}자까지만", reason)
        manifest = build(1)
        for name, high in (("user_subject", 60), ("user_note", 300), ("caption", 100)):
            ok = pm.update_photo(manifest, "p001", **{name: "나" * high})
            self.assertEqual(len(getattr(ok.photos[0], name)), high)
            self.assertRefuses(pm.update_photo, manifest, "p001", **{name: "나" * (high + 1)})

    def test_the_length_is_counted_after_the_text_is_tidied_to_one_line(self):
        padded = "  " + "가" * 60 + " \n\t "
        self.assertEqual(pm.check_text("user_subject", padded), ("가" * 60, None))
        self.assertEqual(pm.check_text("user_note", "가 " * 100), (("가 " * 100).strip(), None))
        self.assertEqual(pm.check_text("user_note", "줄 하나\n줄 둘\r\n줄 셋"), ("줄 하나 줄 둘 줄 셋", None))
        self.assertEqual(pm.check_text("user_subject", "보\u200b이\u202e는"), ("보이는", None), "보이지 않는 글자는 지운다")

    def test_the_analysis_lists_hold_twenty_items_of_two_hundred_characters(self):
        manifest = build(1)
        manifest, dropped = pm.set_analysis(manifest, "p001", method="local:x", texts=[f"글{n}" for n in range(20)])
        self.assertEqual((len(manifest.photos[0].visible_text), dropped), (20, 0))
        manifest, dropped = pm.set_analysis(manifest, "p001", method="local:x", texts=[f"글{n}" for n in range(21)])
        self.assertEqual((len(manifest.photos[0].visible_text), dropped), (20, 1), "스물한 번째는 버린다")
        manifest, dropped = pm.set_analysis(manifest, "p001", method="local:x", texts=["가" * 200, "가" * 201])
        self.assertEqual((len(manifest.photos[0].visible_text), dropped), (1, 1))
        too_many = [{"text": f"글{n}", "confirmed": False} for n in range(21)]
        raw = build(1).to_dict(True)
        raw["photos"][0]["visible_text"] = too_many
        self.assertRefuses(pm.PhotoManifest.from_dict, raw)

    def test_the_limits_and_lists_the_operator_can_see_are_pinned_as_literal_numbers(self):
        """한도 상수를 시험이 상수 이름으로만 대면 상수가 바뀌어도 시험이 따라 바뀐다 — 문서(D-497)에 적힌 숫자를 글자 그대로 못박는다."""
        self.assertEqual((pm.MAX_PHOTOS, pm.MAX_SUBJECT, pm.MAX_NOTE, pm.MAX_CAPTION, pm.MAX_LABEL, pm.MAX_SECTION), (30, 60, 300, 100, 20, 60))
        self.assertEqual((pm.MAX_OBSERVATIONS, pm.MAX_OBSERVATION_CHARS, pm.MAX_NTH, pm.MAX_NUMBER, pm.MAX_PATH_CHARS, pm.MAX_TEXT_BYTES), (20, 200, 50, 999, 260, 524288))
        self.assertEqual(pm.PLACEMENT_KINDS, ("auto", "top", "after_heading", "after_paragraph", "between_sentences"))
        self.assertEqual(pm.DEFAULT_SETTINGS, ("실내", "실외", "테라스", "주차장", "객실", "야경"))
        self.assertEqual((pm.METHOD_MANUAL, pm.DEFAULT_TYPE, pm.SCHEMA), ("manual", "기타", "chanceblog.photo-manifest/1"))
        self.assertEqual(pm.ENVELOPE_KEYS, ("schema", "draft_id", "next_number", "photos"))
        self.assertEqual(pm.ADD_FIELDS, ("setting", "user_subject", "user_note", "preferred_section", "placement", "caption"))
        self.assertEqual(pm.EDIT_FIELDS, ("local_path", "photo_type", *pm.ADD_FIELDS))
        self.assertEqual(pm.DRAFT_KEYS, ("number", "display_order", "photo_type", "setting", "user_subject", "user_note", "preferred_section", "placement", "caption", "confirmed_objects", "confirmed_texts"))
        self.assertEqual(pm.PLACEHOLDER.pattern, "\\{\\{사진 ([1-9][0-9]{0,2})\\}\\}")

    def test_the_placement_index_ranges(self):
        for kind in ("after_paragraph", "between_sentences"):
            with self.subTest(kind=kind):
                self.assertEqual(pm.Placement(kind, 1).nth, 1)
                self.assertEqual(pm.Placement(kind, pm.MAX_NTH).nth, pm.MAX_NTH)
                for bad in (0, -1, pm.MAX_NTH + 1, True, "2", None):
                    self.assertRefuses(pm.Placement, kind, bad)
        for kind in ("auto", "top", "after_heading"):
            self.assertEqual(pm.Placement(kind, 0).nth, 0)
            self.assertRefuses(pm.Placement, kind, 1)
        for bad in ("end", "", "AUTO", None, 3):
            self.assertRefuses(pm.Placement, bad, 0)

    def test_the_photo_numbers_run_out_at_999_and_are_never_reused(self):
        manifest = pm.PhotoManifest((), 999)
        manifest, photo_id = pm.add_photo(manifest, path_of(1))
        self.assertEqual((photo_id, manifest.next_number), ("p999", 1000))
        self.assertRefuses(pm.add_photo, manifest, path_of(2))
        self.assertRefuses(pm.PhotoManifest, (), 1001)
        self.assertRefuses(pm.PhotoManifest, manifest.photos, 999)
        self.assertRefuses(pm.PhotoManifest, (), True)
        self.assertRefuses(pm.PhotoManifest, (), "3")
        for bad in (0, 1000, -1, True, "p1", None, "p000", "P001"):
            if isinstance(bad, str) or bad is None or isinstance(bad, bool) or not 1 <= bad <= 999:
                self.assertRefuses(pm.photo_id_of, bad)
        self.assertRefuses(pm.number_of, "p000")


class PathRulesTest(Base):
    def test_good_paths_are_accepted_in_every_spelling(self):
        for path in (win("a.jpg"), win("A.JPG"), win("사진.jpeg"), win("메뉴 판 1.PNG"), win("x.webp"), "C:/Users/t/Pictures/a.jpg", "D:\\a.jpg", win("한글 폴더", "홍길동") + ".jpg", "c:\\Photos\\a.Jpeg"):
            with self.subTest(path=path):
                self.assertIsNone(pm.path_problem(path, posix=False))
        self.assertIsNone(pm.path_problem("/home/tester/a.jpg", posix=True))
        self.assertIsNotNone(pm.path_problem("/home/tester/a.jpg", posix=False), "윈도에서는 드라이브 없는 `/…` 경로를 쓰지 않는다")
        self.assertIsNone(pm.path_problem(win("가" * 40 + ".jpg")))

    def test_bad_paths_are_refused(self):
        cases = {
            "상대 경로": "a.jpg", "폴더 상대": "Pictures\\a.jpg", "드라이브 상대": "C:a.jpg", "점점": "C:\\Pictures\\..\\a.jpg", "점점 슬래시": "C:/Pictures/../a.jpg", "점점 앞": "..\\a.jpg",
            "네트워크 역슬래시": "\\\\server\\share\\a.jpg", "네트워크 슬래시": "//server/share/a.jpg", "장치 경로": "\\\\.\\C:\\a.jpg", "긴 경로 표기": "\\\\?\\C:\\a.jpg",
            "인터넷 주소": "https://example.com/a.jpg", "파일 주소": "file:///C:/a.jpg", "스크립트": "javascript:alert(1)//a.jpg", "별": "C:\\a*.jpg", "물음표": "C:\\a?.jpg",
            "대체 스트림": "C:\\a.jpg:stream", "드라이브 뒤 콜론": "C:\\x:y\\a.jpg", "끝 구분자": "C:\\Pictures\\", "끝 슬래시": "C:/Pictures/a.jpg/", "빈 글": "", "공백": "   ", "앞 공백": " C:\\a.jpg",
            "뒤 공백": "C:\\a.jpg ", "줄바꿈": "C:\\a\nb.jpg", "탭": "C:\\a\tb.jpg", "널": "C:\\a\x00.jpg", "삭제 문자": "C:\\a\x7f.jpg", "글자 방향 바꾸기": "C:\\photo\u202egpj.exe.jpg", "폭 없는 공백": "C:\\a\u200b.jpg",
            "짝 없는 대리": "C:\\a\ud800.jpg", "gif": "C:\\a.gif", "bmp": "C:\\a.bmp", "heic": "C:\\a.heic", "txt": "C:\\a.txt", "확장자 없음": "C:\\a", "점만": "C:\\a.", "이중 확장자": "C:\\a.jpg.exe",
            "CON": "C:\\CON.jpg", "con 소문자": "C:\\con.png", "NUL 확장자 뒤": "C:\\nul.tar.jpg", "COM1": "C:\\COM1.webp", "LPT9": "C:\\x\\LPT9.jpeg", "CONIN$": "C:\\CONIN$.jpg", "공백 붙은 장치": "C:\\CON .jpg",
        }
        for name, path in cases.items():
            with self.subTest(case=name):
                self.assertIsNotNone(pm.path_problem(path, posix=False), repr(path))
        for bad in (None, 5, b"C:\\a.jpg", ["C:\\a.jpg"], Path("C:\\a.jpg"), True):
            self.assertIsNotNone(pm.path_problem(bad), repr(bad))

    def test_network_places_and_web_addresses_are_refused_with_their_own_reason_even_where_a_slash_path_is_allowed(self):
        """윈도가 아닌 곳(`posix=True`)에서는 `//서버/공유/a.jpg` 가 `/` 로 시작해 절대 경로로 보이므로 이 검사가 따로 있어야 막힌다 — 이유 문장도 따로다."""
        network = pm._P_NETWORK
        back = chr(92)
        for path in ("//server/share/a.jpg", back * 2 + "server" + back + "share" + back + "a.jpg", back * 2 + "." + back + "C:" + back + "a.jpg", back * 2 + "?" + back + "C:" + back + "a.jpg",
                     "https://example.com/a.jpg", "http://x/a.jpg", "file:///C:/a.jpg", "ftp://h/a.jpg", "javascript:alert(1)//a.jpg"):
            for posix in (False, True):
                with self.subTest(path=path, posix=posix):
                    self.assertEqual(pm.path_problem(path, posix=posix), network)
        self.assertIn("네트워크 위치", network)
        self.assertNotEqual(pm.path_problem("relative/a.jpg"), network)

    def test_the_length_limit_is_260_characters(self):
        stem = "C:\\" + "d" * 240 + "\\"
        ok = stem + "a" * (260 - len(stem) - 4) + ".jpg"
        self.assertEqual(len(ok), 260)
        self.assertIsNone(pm.path_problem(ok, posix=False))
        self.assertIsNotNone(pm.path_problem(ok[:-4] + "a.jpg", posix=False))
        self.assertIn("260", pm.path_problem(ok[:-4] + "a.jpg", posix=False))
        self.assertEqual(pm.MAX_PATH_CHARS, 260)

    def test_the_extension_list_is_read_from_imagerules_not_copied(self):
        self.assertEqual(pm.accepted_extensions(), imagerules.SUPPORTED_EXTENSIONS)
        original = imagerules.SUPPORTED_EXTENSIONS
        try:
            imagerules.SUPPORTED_EXTENSIONS = (".png",)
            self.assertIsNotNone(pm.path_problem(win("a.jpg")))
            self.assertIsNone(pm.path_problem(win("a.png")))
        finally:
            imagerules.SUPPORTED_EXTENSIONS = original
        source = SOURCE.read_text(encoding="utf-8")
        for literal in ('".jpg"', '".jpeg"', '".png"', '".webp"', "'.jpg'", "'.png'"):
            self.assertNotIn(literal, source, "확장자 목록을 따로 적지 않았다")

    def test_the_shape_rules_match_the_existing_text_file_rules_of_own_posts(self):
        """사진 경로의 모양 규칙은 `own_posts` 의 것과 같다(확장자만 다르다) — 둘이 갈라지지 않게 같은 표를 둘 다에 댄다."""
        base = os.path.abspath(os.sep)
        sep = os.sep
        cases = [base + "dir" + sep + "a.EXT", base + "a.EXT", base + "dir" + sep + ".." + sep + "a.EXT", "rel" + sep + "a.EXT", "a.EXT", "//srv/share/a.EXT", "\\\\srv\\share\\a.EXT",
                 "http://example.com/a.EXT", "file:///x/a.EXT", base + "a*.EXT", base + "a?.EXT", base + "a.EXT:s", base + "CON.EXT", base + "nul.EXT", base + "com1.EXT", base + "a\x00b.EXT",
                 base + "a\tb.EXT", base + "dir" + sep, "", "   ", base + "a" * 10 + ".EXT"]
        for case in cases:
            with self.subTest(case=case):
                photo = pm.path_problem(case.replace("EXT", "jpg"), posix=os.name != "nt")
                text = own_posts._shape(case.replace("EXT", "md"))[1]
                self.assertEqual(photo is None, text is None, f"사진: {photo} / 글 파일: {text}")

    def test_the_same_file_is_found_through_separators_and_case_but_other_files_are_not(self):
        first = win("Menu.JPG")
        manifest, _id = pm.add_photo(pm.empty_manifest(), first)
        for variant in (win("menu.jpg"), "c:/users/" + USER_DIR.lower() + "/pictures/MENU.JPG", "C:\\Users\\" + USER_DIR + "\\Pictures\\.\\Menu.JPG", "C:\\Users\\" + USER_DIR + "\\x\\..\\Pictures\\Menu.JPG"):
            if pm.path_problem(variant) is None:
                with self.subTest(variant=variant):
                    self.assertRefuses(pm.add_photo, manifest, variant)
        manifest, _id = pm.add_photo(manifest, win("Menu2.jpg"))
        manifest, _id = pm.add_photo(manifest, win("Menu.jpg", "other"))
        self.assertEqual(len(manifest.photos), 3)
        self.assertEqual(pm.path_key("/a/B.jpg"), "/a/B.jpg", "윈도 경로가 아니면 대소문자를 구분한다")
        self.assertNotEqual(pm.path_key("/a/B.jpg"), pm.path_key("/a/b.jpg"))


class TextRulesTest(Base):
    def test_clean_text_is_returned_and_empty_optional_text_is_allowed(self):
        self.assertEqual(pm.check_text("user_note", "  비 오는 날의  한 컷  "), ("비 오는 날의 한 컷", None))
        for name in ("setting", "user_subject", "user_note", "preferred_section", "caption"):
            self.assertEqual(pm.check_text(name, ""), ("", None))
            self.assertEqual(pm.check_text(name, " \n\t"), ("", None))
        for name in ("photo_type", "observation"):
            text, reason = pm.check_text(name, "  ")
            self.assertIsNone(text)
            self.assertIn("비워 둘 수 없어요", reason)
        self.assertIsNone(pm.check_text("unknown_field", "x")[0])
        for bad in (None, 5, b"x", ["x"]):
            self.assertIsNone(pm.check_text("user_note", bad)[0])

    def test_markup_templates_invisible_lookalikes_and_stacked_marks_are_refused(self):
        bad = ("<b>굵게</b>", "<script>x</script>", "<img src=x onerror=alert(1)>", "{{사진 1}}", "{% if x %}", "{# 메모 #}", "javascript:alert(1)", "onclick=run()",
               "\u3164" * 3, "\u2800", "a\u0301\u0301\u0301\u0301", "\u0301")
        for text in bad:
            for name in ("user_subject", "user_note", "caption", "preferred_section", "setting", "photo_type", "observation"):
                with self.subTest(text=text, field=name):
                    self.assertIsNone(pm.check_text(name, text)[0])

    def test_key_and_token_shapes_and_personal_numbers_are_refused_without_echoing_them(self):
        secrets = {"google": scan_samples.google(), "github": scan_samples.github(), "bearer": scan_samples.bearer(), "pem": scan_samples.pem()}
        for name, secret in secrets.items():
            for field in ("user_subject", "user_note", "caption", "preferred_section", "photo_type", "setting", "observation"):
                with self.subTest(kind=name, field=field):
                    text, reason = pm.check_text(field, f"앞 {secret} 뒤")
                    self.assertIsNone(text)
                    self.assertNotIn(secret[:12], reason)
        cards = ("4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111", "카드 4111 1111 1111 1111 입니다", "378282246310005")
        residents = ("900101-1234567", "9001011234567", "900101 2345678", "010203-4567890")
        for text in (*cards, *residents):
            with self.subTest(number=text):
                self.assertIsNotNone(pm.personal_number_problem(text))
                self.assertIsNone(pm.check_text("user_note", text)[0])
        fine = ("010-1234-5678", "02-123-4567", "12,000원", "2026-11-16", "4111 1111 1111 1112", "901301-1234567", "1234567", "13자리 1234567890123 번", "주문번호 20261116001")
        for text in fine:
            with self.subTest(fine=text):
                self.assertEqual(pm.check_text("user_note", text), (text, None))
        self.assertIsNotNone(pm.personal_number_problem("901301-1234568"), "달이 13 이어도 카드 번호 검사 숫자가 맞으면 거른다")
        sentence = pm.personal_number_problem("901301-1234568")
        self.assertIn("번호가 아니라면", sentence, "검증 Q-8 — 번호가 아닌 긴 숫자도 우연히 걸릴 수 있으니 풀이 안내가 문장에 있다")
        self.assertIn("쉼표나 글자", sentence)
        _clean, reason = pm.check_text("user_note", "주문번호 4539148803436467")
        self.assertIn("쉼표나 글자", reason or "")

    def test_promises_of_results_are_refused_in_the_texts_that_reach_the_draft_but_not_in_labels(self):
        promise = "상위노출 보장"
        for name in ("user_subject", "user_note", "caption"):
            self.assertIsNone(pm.check_text(name, promise)[0], name)
        for name in ("photo_type", "setting", "preferred_section", "observation"):
            self.assertEqual(pm.check_text(name, promise)[1], None, name)

    def test_reasons_are_fixed_sentences_that_never_repeat_the_text(self):
        for text in ("UNIQ-<b>-x", "UNIQ-{{y}}-z"):
            _clean, reason = pm.check_text("user_note", text)
            self.assertNotIn("UNIQ", reason)
        error = self.assertRefuses(pm.add_photo, pm.empty_manifest(), win("a.jpg"), user_note="<i>UNIQ-NOTE-zz</i>")
        self.assertNoLeak(error, ["UNIQ-NOTE-zz", USER_DIR])

    def test_lost_confirmation_lists_the_photos_whose_confirmation_a_change_undid(self):
        """검증 Q-9 — `update_photo` 는 새 목록만 돌려주므로 확정이 풀린 사진 번호를 알려 주는 도우미를 둔다."""
        manifest = confirmed(build(3), "p001", "p003")
        self.assertEqual(pm.lost_confirmation(manifest, manifest), ())
        self.assertEqual(pm.lost_confirmation(manifest, pm.update_photo(manifest, "p001", user_note="새 메모")), (1,))
        self.assertEqual(pm.lost_confirmation(manifest, pm.update_photo(manifest, "p002", user_note="새 메모")), (), "확정이 아니던 사진은 풀린 것이 아니다")
        self.assertEqual(pm.lost_confirmation(manifest, pm.set_confirmed(manifest, "p003", False)), (3,))
        self.assertEqual(pm.lost_confirmation(manifest, pm.remove_photo(manifest, "p003")), (), "지운 사진은 목록에 없으니 풀린 것으로 세지 않는다")
        moved = pm.move_photo(manifest, "p003", 1)
        self.assertEqual(pm.lost_confirmation(manifest, moved), (), "순서만 바꾸면 확정은 그대로다")
        self.assertEqual(pm.lost_confirmation(manifest, pm.update_photo(pm.update_photo(manifest, "p003", caption="설명"), "p001", caption="설명")), (1, 3))
        self.assertRefuses(pm.lost_confirmation, manifest, None)
        self.assertRefuses(pm.lost_confirmation, "p001", manifest)

    def test_the_type_list_is_only_checked_when_the_type_changes_or_is_added(self):
        """검증 Q-7 — 메모만 고쳤는데 옛 종류가 지금 목록에 없다고 거절하면 안 된다. 종류를 바꾸거나 더할 때만 목록을 본다."""
        types = ("간판", "메뉴판", "기타")
        manifest, _id = pm.add_photo(pm.empty_manifest(), path_of(1), photo_type="간판", photo_types=types)
        later = ("메뉴판", "기타")                                                     # 사용자가 목록에서 '간판' 을 지운 뒤
        edited = pm.update_photo(manifest, "p001", user_note="메모", photo_types=later)
        self.assertEqual((edited.photos[0].photo_type, edited.photos[0].user_note), ("간판", "메모"))
        self.assertRefuses(pm.update_photo, manifest, "p001", photo_type="반찬", photo_types=later)
        self.assertRefuses(pm.update_photo, manifest, "p001", photo_type="간판 2", photo_types=later)
        self.assertEqual(pm.update_photo(manifest, "p001", photo_type="메뉴판", photo_types=later).photos[0].photo_type, "메뉴판")
        self.assertRefuses(pm.add_photo, manifest, path_of(2), photo_type="간판", photo_types=later)               # 더할 때는 늘 본다
        self.assertEqual(pm.update_photo(manifest, "p001", user_note="메모").photos[0].user_note, "메모", "목록을 안 주면 보지 않는다")

    def test_the_type_list_can_be_given_and_then_the_kind_must_be_in_it(self):
        types = ("간판", "메뉴판")
        manifest, _id = pm.add_photo(pm.empty_manifest(), path_of(1), photo_type="간판", photo_types=types)
        self.assertRefuses(pm.add_photo, manifest, path_of(2), photo_type="반찬", photo_types=types)
        self.assertRefuses(pm.update_photo, manifest, "p001", photo_type="반찬", photo_types=types)
        self.assertEqual(pm.update_photo(manifest, "p001", photo_type="메뉴판", photo_types=types).photos[0].photo_type, "메뉴판")
        self.assertEqual(pm.update_photo(manifest, "p001", photo_type="내가 만든 종류").photos[0].photo_type, "내가 만든 종류", "목록을 주지 않으면 모양만 본다")
        self.assertEqual(pm.DEFAULT_PHOTO_TYPES, ("간판", "건물 외관", "메뉴판", "인테리어", "대표 메뉴", "반찬", "음식", "지도 캡처", "기타"))
        self.assertIn("기타", pm.DEFAULT_PHOTO_TYPES)


class OperationTest(Base):
    def test_adding_numbers_the_photos_in_order_and_fills_safe_defaults(self):
        manifest = build(3)
        self.assertEqual([photo.photo_id for photo in manifest.photos], ["p001", "p002", "p003"])
        self.assertEqual([photo.display_order for photo in manifest.photos], [1, 2, 3])
        self.assertEqual(manifest.next_number, 4)
        photo = manifest.photos[0]
        self.assertEqual((photo.analysis_method, photo.confirmed_by_user, photo.observed_objects, photo.visible_text, photo.placement), ("manual", False, (), (), pm.Placement("auto", 0)))
        self.assertEqual((photo.setting, photo.user_subject, photo.user_note, photo.preferred_section, photo.caption), ("", "", "", "", ""))
        self.assertEqual([photo.number for photo in manifest.photos], [1, 2, 3])
        self.assertIs(manifest.by_number(2), manifest.photos[1])
        self.assertIsNone(manifest.by_number(9))
        self.assertRefuses(manifest.photo, "p009")

    def test_add_gives_only_the_content_fields_and_never_a_confirmation_or_analysis(self):
        manifest, photo_id = pm.add_photo(pm.empty_manifest(), path_of(1), photo_type="간판", setting="실외", user_subject="입구", user_note="비 오는 날", preferred_section="도입", placement={"kind": "top", "nth": 0},
                                          caption="입구 간판")
        photo = manifest.photo(photo_id)
        self.assertEqual((photo.photo_type, photo.setting, photo.user_subject, photo.user_note, photo.preferred_section, photo.caption), ("간판", "실외", "입구", "비 오는 날", "도입", "입구 간판"))
        self.assertEqual(photo.placement, pm.Placement("top", 0))
        for field, value in (("confirmed_by_user", True), ("observed_objects", ["a"]), ("visible_text", ["a"]), ("analysis_method", "local:x"), ("photo_id", "p009"), ("display_order", 1), ("local_path", "x")):
            with self.subTest(field=field):
                self.assertRefuses(pm.add_photo, pm.empty_manifest(), path_of(2), **{field: value})

    def test_a_removed_number_is_never_given_to_a_new_photo_and_the_order_is_renumbered(self):
        manifest = build(3)
        manifest = pm.remove_photo(manifest, "p003")                      # 가장 큰 번호를 지워도
        manifest, new_id = pm.add_photo(manifest, path_of(9))
        self.assertEqual(new_id, "p004", "p003 을 다시 쓰면 본문의 {{사진 3}} 이 엉뚱한 사진을 가리킨다")
        manifest = pm.remove_photo(manifest, "p001")
        self.assertEqual([(p.photo_id, p.display_order) for p in manifest.photos], [("p002", 1), ("p004", 2)])
        self.assertEqual(manifest.next_number, 5)
        self.assertRefuses(pm.remove_photo, manifest, "p001")
        self.assertRefuses(pm.remove_photo, manifest, "p002 ")
        self.assertEqual(len(build(3).photos), 3, "원래 목록은 그대로다")

    def test_moving_and_reordering_keep_the_numbers_and_make_the_order_gapless(self):
        manifest = build(4)
        moved = pm.move_photo(manifest, "p004", 1)
        self.assertEqual([p.photo_id for p in moved.photos], ["p004", "p001", "p002", "p003"])
        self.assertEqual([p.display_order for p in moved.photos], [1, 2, 3, 4])
        self.assertEqual([p.photo_id for p in pm.move_photo(manifest, "p001", 4).photos], ["p002", "p003", "p004", "p001"])
        self.assertEqual([p.photo_id for p in pm.move_photo(manifest, "p002", 2).photos], ["p001", "p002", "p003", "p004"])
        self.assertEqual([p.photo_id for p in pm.move_photo(manifest, "p003", 2).photos], ["p001", "p003", "p002", "p004"])
        for bad in (0, 5, -1, True, "1", None):
            self.assertRefuses(pm.move_photo, manifest, "p001", bad)
        again = pm.reorder(manifest, ["p003", "p001", "p004", "p002"])
        self.assertEqual([(p.photo_id, p.display_order) for p in again.photos], [("p003", 1), ("p001", 2), ("p004", 3), ("p002", 4)])
        self.assertEqual(again.next_number, manifest.next_number)
        for bad in (["p001", "p002", "p003"], ["p001", "p001", "p002", "p003"], ["p001", "p002", "p003", "p009"], "p001p002", None, ["p001", "p002", "p003", 4], [["p001"], "p002", "p003", "p004"]):
            self.assertRefuses(pm.reorder, manifest, bad)

    def test_changing_the_content_of_a_confirmed_photo_unconfirms_it_and_an_unchanged_value_does_not(self):
        manifest = confirmed(build(2, user_subject="냉면"), "p001", "p002")
        for field, value in (("photo_type", "간판"), ("setting", "실내"), ("user_subject", "비빔냉면"), ("user_note", "추가"), ("preferred_section", "마무리"), ("caption", "설명"),
                             ("placement", {"kind": "after_heading", "nth": 0}), ("placement", pm.Placement("after_paragraph", 2)), ("local_path", path_of(50))):
            with self.subTest(field=field):
                changed = pm.update_photo(manifest, "p001", **{field: value})
                self.assertFalse(changed.photo("p001").confirmed_by_user)
                self.assertTrue(changed.photo("p002").confirmed_by_user, "다른 사진은 그대로다")
        same = pm.update_photo(manifest, "p001", user_subject="  냉면  ", photo_type="음식")
        self.assertEqual(same, manifest)
        self.assertTrue(same.photo("p001").confirmed_by_user)

    def test_update_refuses_the_fields_that_have_their_own_functions(self):
        manifest = build(2)
        for field, value in (("confirmed_by_user", True), ("display_order", 2), ("photo_id", "p009"), ("analysis_method", "local:x"), ("observed_objects", ()), ("visible_text", ()), ("number", 3), ("exif", "x")):
            with self.subTest(field=field):
                self.assertRefuses(pm.update_photo, manifest, "p001", **{field: value})
        self.assertRefuses(pm.update_photo, manifest, "p009", user_note="x")
        self.assertRefuses(pm.update_photo, manifest, "p001", local_path="C:\\a.gif")
        self.assertRefuses(pm.update_photo, manifest, "p001", local_path=path_of(2))
        self.assertEqual(pm.update_photo(manifest, "p001", local_path=path_of(1)), manifest)

    def test_relinking_a_photo_drops_its_analysis_and_confirmation_because_it_is_another_file(self):
        manifest, _dropped = pm.set_analysis(build(1), "p001", method="local:paddleocr", objects=["접시"], texts=["김치찌개"])
        manifest = pm.confirm_item(manifest, "p001", pm.TEXTS, 0)
        manifest = confirmed(manifest, "p001")
        moved = pm.update_photo(manifest, "p001", local_path=path_of(77))
        photo = moved.photo("p001")
        self.assertEqual((photo.analysis_method, photo.observed_objects, photo.visible_text, photo.confirmed_by_user), ("manual", (), (), False))
        edited = pm.update_photo(manifest, "p001", user_note="메모만")
        self.assertEqual(edited.photo("p001").visible_text, manifest.photo("p001").visible_text, "같은 파일이면 분석 결과는 그대로다")

    def test_confirming_needs_a_real_boolean_and_only_set_confirmed_turns_it_on(self):
        manifest = build(2)
        on = pm.set_confirmed(manifest, "p001", True)
        self.assertTrue(on.photo("p001").confirmed_by_user)
        self.assertFalse(manifest.photo("p001").confirmed_by_user, "원래 목록은 그대로다")
        self.assertFalse(pm.set_confirmed(on, "p001", False).photo("p001").confirmed_by_user)
        for bad in (1, 0, "true", None, "예"):
            self.assertRefuses(pm.set_confirmed, manifest, "p001", bad)
        self.assertRefuses(pm.set_confirmed, manifest, "p009", True)
        self.assertRefuses(pm.Photo, "p001", win("a.jpg"), 1, "음식", confirmed_by_user=1)

    def test_a_manifest_refuses_inconsistent_content(self):
        one, two = build(2).photos
        self.assertRefuses(pm.PhotoManifest, (one, dataclasses.replace(two, display_order=3)))                      # 순서에 빈틈
        self.assertRefuses(pm.PhotoManifest, (one, dataclasses.replace(two, display_order=1)))                      # 순서 겹침
        self.assertRefuses(pm.PhotoManifest, (one, dataclasses.replace(two, photo_id="p001")))                      # 번호 겹침
        self.assertRefuses(pm.PhotoManifest, (one, dataclasses.replace(two, local_path=one.local_path.lower())))    # 같은 파일
        self.assertRefuses(pm.PhotoManifest, (one, two), 2)                                                          # 다음 번호가 이미 쓴 번호
        self.assertRefuses(pm.PhotoManifest, (one, "p002"))
        self.assertRefuses(pm.PhotoManifest, "p001")
        self.assertRefuses(pm.PhotoManifest, (), 0, "dd-123")
        self.assertRefuses(pm.PhotoManifest, (), 0, 5)
        self.assertEqual(pm.PhotoManifest((one, two)).next_number, 3)
        self.assertEqual(pm.PhotoManifest((), 0, DRAFT_ID).draft_id, DRAFT_ID)
        self.assertTrue(sd.is_draft_id(DRAFT_ID))

    def test_every_function_leaves_the_original_manifest_unchanged(self):
        manifest = confirmed(build(3, user_note="메모"), "p001")
        before = manifest.to_text(True)
        pm.add_photo(manifest, path_of(9))
        pm.remove_photo(manifest, "p001")
        pm.move_photo(manifest, "p003", 1)
        pm.reorder(manifest, ["p003", "p002", "p001"])
        pm.update_photo(manifest, "p001", user_note="바뀜")
        pm.set_confirmed(manifest, "p002", True)
        pm.set_analysis(manifest, "p002", method="local:x", texts=["가"])
        self.assertEqual(manifest.to_text(True), before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            manifest.photos[0].user_note = "몰래"


class DraftInputsTest(Base):
    def make(self):
        manifest = build(4, user_subject="UNIQ-SUBJ")
        manifest = pm.update_photo(manifest, "p001", user_subject="UNIQ-S1", user_note="UNIQ-N1", caption="UNIQ-C1", setting="실내", preferred_section="대표 메뉴", placement={"kind": "after_paragraph", "nth": 2})
        manifest = pm.update_photo(manifest, "p002", user_subject="UNIQ-S2-숨김", user_note="UNIQ-N2-숨김", caption="UNIQ-C2-숨김")
        manifest = pm.update_photo(manifest, "p003", user_subject="UNIQ-S3", photo_type="메뉴판")
        manifest, _dropped = pm.set_analysis(manifest, "p001", method="local:fake", objects=["UNIQ-OBJ-ok", "UNIQ-OBJ-no"], texts=["UNIQ-TXT-ok 9,000원", "UNIQ-TXT-no"])
        manifest = pm.confirm_item(pm.confirm_item(manifest, "p001", pm.OBJECTS, 0), "p001", pm.TEXTS, 0)
        manifest, _dropped = pm.set_analysis(manifest, "p003", method="local:fake", texts=["UNIQ-TXT3"])
        manifest = pm.confirm_item(manifest, "p003", pm.TEXTS, 0)
        return confirmed(manifest, "p001", "p003")                       # p002·p004 는 확정하지 않았다

    def test_only_confirmed_photos_and_only_their_confirmed_items_go_to_the_draft(self):
        sent = pm.draft_inputs(self.make())
        self.assertEqual([item.number for item in sent], [1, 3])
        first, third = sent
        self.assertEqual((first.user_subject, first.user_note, first.caption, first.setting, first.preferred_section), ("UNIQ-S1", "UNIQ-N1", "UNIQ-C1", "실내", "대표 메뉴"))
        self.assertEqual(first.placement, pm.Placement("after_paragraph", 2))
        self.assertEqual(first.confirmed_objects, ("UNIQ-OBJ-ok",))
        self.assertEqual(first.confirmed_texts, ("UNIQ-TXT-ok 9,000원",))
        self.assertEqual((third.photo_type, third.confirmed_texts, third.confirmed_objects), ("메뉴판", ("UNIQ-TXT3",), ()))
        everything = json.dumps([item.to_dict() for item in sent], ensure_ascii=False) + repr(sent)
        for hidden in ("UNIQ-S2", "UNIQ-N2", "UNIQ-C2", "UNIQ-OBJ-no", "UNIQ-TXT-no", "UNIQ-SUBJ"):
            self.assertNotIn(hidden, everything, "확정하지 않은 사진·확인하지 않은 항목은 초안 입력에 없다")

    def test_no_path_file_name_or_internal_photo_id_is_ever_in_what_is_sent(self):
        sent = pm.draft_inputs(self.make())
        shown = [json.dumps([item.to_dict() for item in sent], ensure_ascii=False), repr(sent), str(sent), repr(sent[0]), str(dataclasses.asdict(sent[0])), json.dumps(sent[0].to_dict()),
                 " ".join(sent[0].texts()), " ".join(sent[1].texts())]
        for text in shown:
            for hidden in (USER_DIR, FILE_STEM, "Pictures", "C:\\", "C:/", ".jpg", "p001", "p003", "photo_id", "local_path", "analysis_method", "confirmed_by_user", "manual", "local:fake"):
                self.assertNotIn(hidden, text)
        self.assertEqual(set(sent[0].to_dict()), set(pm.DRAFT_KEYS))
        self.assertEqual(tuple(sent[0].to_dict()), pm.DRAFT_KEYS)
        self.assertEqual({field.name for field in dataclasses.fields(pm.DraftPhoto)}, set(pm.DRAFT_KEYS))

    def test_nothing_is_sent_when_nothing_is_confirmed_and_the_order_follows_display_order(self):
        manifest = build(3, user_subject="가")
        self.assertEqual(pm.draft_inputs(manifest), ())
        self.assertEqual(pm.draft_inputs(pm.empty_manifest()), ())
        moved = pm.move_photo(confirmed(manifest, "p001", "p003"), "p003", 1)
        self.assertEqual([item.number for item in pm.draft_inputs(moved)], [3, 1])
        self.assertEqual([item.display_order for item in pm.draft_inputs(moved)], [1, 2])

    def test_a_confirmation_that_is_not_exactly_true_does_not_send_a_photo(self):
        manifest = confirmed(build(2, user_subject="가"), "p001", "p002")
        object.__setattr__(manifest.photos[0], "confirmed_by_user", 1)
        self.assertEqual([item.number for item in pm.draft_inputs(manifest)], [2])
        manifest2, _dropped = pm.set_analysis(build(1), "p001", method="local:x", texts=["글"])
        manifest2 = confirmed(manifest2, "p001")
        object.__setattr__(manifest2.photos[0].visible_text[0], "confirmed", "yes")
        self.assertEqual(pm.draft_inputs(manifest2)[0].confirmed_texts, ())

    def test_repeated_texts_are_sent_once_in_their_first_order(self):
        manifest = pm.empty_manifest()
        manifest, _id = pm.add_photo(manifest, path_of(1))
        manifest, _dropped = pm.set_analysis(manifest, "p001", method="local:x", objects=["접시", "국자", "접시"], texts=["김치찌개", "된장찌개", "김치찌개"])
        for kind in (pm.OBJECTS, pm.TEXTS):
            for index in range(3):
                manifest = pm.confirm_item(manifest, "p001", kind, index)
        sent = pm.draft_inputs(confirmed(manifest, "p001"))[0]
        self.assertEqual((sent.confirmed_objects, sent.confirmed_texts), (("접시", "국자"), ("김치찌개", "된장찌개")))

    def test_the_last_gate_stops_a_secret_shape_that_somehow_got_into_a_confirmed_photo(self):
        manifest = confirmed(build(1, user_note="괜찮은 글"), "p001")
        object.__setattr__(manifest.photos[0], "user_note", scan_samples.google())
        error = self.assertRefuses(pm.draft_inputs, manifest)
        self.assertNoLeak(error, [scan_samples.google()[:10]])
        self.assertRefuses(pm.draft_inputs, "p001")
        self.assertRefuses(pm.draft_inputs, None)

    def test_the_last_gate_checks_every_text_that_leaves_not_just_the_note(self):
        """검증 Q-1 — 마지막 관문은 초안으로 나가는 글 모두를 본다(`DraftPhoto.texts()` 에서 하나라도 빠지면 걸린다): 종류·장소 분위기·대상·메모·들어갈 곳·설명 글과 확인한 대상·확인한 글자 각각.
        입력 검사(`check_text`)를 건너뛴 값을 `object.__setattr__` 로 넣어 본다."""
        key = scan_samples.google()
        for name in ("photo_type", "setting", "user_subject", "user_note", "preferred_section", "caption"):
            with self.subTest(field=name):
                manifest = confirmed(build(1), "p001")
                object.__setattr__(manifest.photos[0], name, key)
                error = self.assertRefuses(pm.draft_inputs, manifest)
                self.assertNoLeak(error, [key[:10]])
        for kind, attribute in ((pm.OBJECTS, "observed_objects"), (pm.TEXTS, "visible_text")):
            for index in (0, 1):
                with self.subTest(kind=kind, index=index):
                    manifest, _dropped = pm.set_analysis(build(1), "p001", method="local:x", objects=["접시", "국자"], texts=["김치찌개", "된장찌개"])
                    for position in (0, 1):
                        manifest = pm.confirm_item(manifest, "p001", kind, position)
                    manifest = confirmed(manifest, "p001")
                    self.assertEqual(len(pm.draft_inputs(manifest)[0].texts()), 6 + 2, "확인한 항목이 하나의 종류에서 둘 나간다는 전제")
                    object.__setattr__(getattr(manifest.photos[0], attribute)[index], "text", key)
                    error = self.assertRefuses(pm.draft_inputs, manifest)
                    self.assertNoLeak(error, [key[:10]])


class AnalysisTest(Base):
    def test_analysis_results_are_not_written_by_default_and_come_back_empty(self):
        manifest, _dropped = pm.set_analysis(build(1), "p001", method="local:paddleocr", objects=["UNIQ-OBJ"], texts=["UNIQ-TXT"])
        manifest = pm.confirm_item(manifest, "p001", pm.TEXTS, 0)
        self.assertNotIn("UNIQ-OBJ", manifest.to_text())
        self.assertNotIn("UNIQ-TXT", manifest.to_text())
        self.assertNotIn("UNIQ-TXT", json.dumps(manifest.to_dict()))
        self.assertEqual(manifest.to_dict()["photos"][0]["observed_objects"], [])
        self.assertEqual(manifest.to_dict()["photos"][0]["visible_text"], [])
        self.assertIn("UNIQ-TXT", manifest.to_text(persist_analysis=True))
        self.assertEqual(pm.PhotoManifest.from_text(manifest.to_text()).photos[0].visible_text, ())
        self.assertEqual(manifest.photos[0].visible_text[0].confirmed, True, "메모리에서는 그대로 쓴다")
        import inspect
        self.assertFalse(inspect.signature(pm.PhotoManifest.to_text).parameters["persist_analysis"].default)
        self.assertFalse(inspect.signature(pm.PhotoManifest.to_dict).parameters["persist_analysis"].default)
        self.assertFalse(inspect.signature(pm.Photo.to_dict).parameters["persist_analysis"].default)

    def test_new_analysis_items_start_unconfirmed_and_replace_the_old_ones_and_unconfirm_the_photo(self):
        manifest = confirmed(build(1), "p001")
        manifest, dropped = pm.set_analysis(manifest, "p001", method="local:paddleocr", texts=["가", "나"])
        photo = manifest.photo("p001")
        self.assertEqual(dropped, 0)
        self.assertEqual([(item.text, item.confirmed) for item in photo.visible_text], [("가", False), ("나", False)])
        self.assertEqual((photo.analysis_method, photo.confirmed_by_user), ("local:paddleocr", False))
        again, _dropped = pm.set_analysis(manifest, "p001", method="local:other", objects=["그릇"])
        self.assertEqual(again.photo("p001").visible_text, ())
        self.assertEqual(again.photo("p001").analysis_method, "local:other")

    def test_the_plugin_output_is_not_trusted_and_bad_items_are_dropped_and_counted(self):
        bad = ["<b>x</b>", scan_samples.google(), "4111 1111 1111 1111", "", "   ", 5, None, "가" * 201, "{{사진 1}}"]
        manifest, dropped = pm.set_analysis(build(1), "p001", method="local:x", objects=["그릇", *bad], texts=["메뉴", *bad])
        self.assertEqual(dropped, 2 * len(bad))
        photo = manifest.photo("p001")
        self.assertEqual(([item.text for item in photo.observed_objects], [item.text for item in photo.visible_text]), (["그릇"], ["메뉴"]))
        manifest, dropped = pm.set_analysis(build(1), "p001", method="local:x", objects="not a list", texts=None)
        self.assertEqual((dropped, manifest.photo("p001").observed_objects, manifest.photo("p001").visible_text), (2, (), ()))
        for method in ("manual", "", "local:", "LOCAL:x", "local:UPPER", "remote:x", None, 5, "local:" + "a" * 41, "local:a b", "gemini"):
            with self.subTest(method=method):
                self.assertRefuses(pm.set_analysis, build(1), "p001", method=method, texts=["가"])
        self.assertRefuses(pm.set_analysis, build(1), "p009", method="local:x")
        for method in ("local:paddleocr", "local:rapidocr", "local:a", "local:a.b-c_d", "local:" + "a" * 40):
            pm.set_analysis(build(1), "p001", method=method)

    def test_what_was_guessed_about_faces_relationships_feelings_or_identity_is_not_accepted_as_an_observed_object(self):
        guessed = ("사람 두 명", "웃는 남자", "행복해 보이는 가족", "친구와 함께", "여성의 얼굴", "아이가 먹는 모습", "연인", "엄마", "슬픈 표정", "유명 연예인", "본인 사진", "누구의 이름",
                   "a happy family", "two people", "smiling woman", "Face", "a child", "celebrity", "FRIENDS", "boyfriend and girlfriend", "angry customer", "손님 세 명", "직원", "딸과 아빠")
        for text in guessed:
            with self.subTest(text=text):
                self.assertIsNotNone(pm.inference_problem(text))
                manifest, dropped = pm.set_analysis(build(1), "p001", method="local:x", objects=[text])
                self.assertEqual((dropped, manifest.photo("p001").observed_objects), (1, ()))
                self.assertRefuses(pm.Photo, "p001", win("a.jpg"), 1, "음식", observed_objects=(pm.Observation(text),))
        plain = ("아이스 아메리카노", "아이스크림", "딸기 케이크", "딸기", "불고기 전골", "냉면 한 그릇", "나무 테이블", "입구 간판", "접시 위의 반찬", "a bowl of noodles", "interface", "menu board",
                 "wine glass", "table and chairs", "지도 화면", "메뉴판")
        for text in plain:
            with self.subTest(plain=text):
                self.assertIsNone(pm.inference_problem(text))
        manifest, dropped = pm.set_analysis(build(1), "p001", method="local:x", texts=["손님 한 명당 1개", "사람 수에 따라"])
        self.assertEqual(dropped, 0, "간판에서 읽은 글자는 그대로 인용이라 걸러내지 않는다 — 확인은 사용자가 한다")

    def test_the_user_confirms_or_edits_items_one_by_one_and_any_change_unconfirms_the_photo(self):
        manifest, _dropped = pm.set_analysis(build(1), "p001", method="local:x", objects=["접시", "국자"], texts=["김치찌개 8,000", "된장찌개 9,000"])
        ready = confirmed(pm.confirm_item(manifest, "p001", pm.TEXTS, 1), "p001")
        self.assertEqual([item.confirmed for item in ready.photo("p001").visible_text], [False, True])
        self.assertTrue(ready.photo("p001").confirmed_by_user)
        flipped = pm.confirm_item(ready, "p001", pm.TEXTS, 0)
        self.assertFalse(flipped.photo("p001").confirmed_by_user, "확정한 뒤 항목을 바꾸면 확정이 풀린다")
        self.assertEqual(pm.confirm_item(ready, "p001", pm.TEXTS, 1), ready, "그대로면 확정도 그대로")
        undone = pm.confirm_item(ready, "p001", pm.TEXTS, 1, False)
        self.assertFalse(undone.photo("p001").visible_text[1].confirmed)
        edited = pm.edit_item(ready, "p001", pm.TEXTS, 1, "된장찌개 9,500")
        self.assertEqual((edited.photo("p001").visible_text[1].text, edited.photo("p001").visible_text[1].confirmed, edited.photo("p001").confirmed_by_user), ("된장찌개 9,500", False, False))
        self.assertRefuses(pm.edit_item, ready, "p001", pm.OBJECTS, 0, "행복한 사람")
        self.assertRefuses(pm.edit_item, ready, "p001", pm.TEXTS, 0, scan_samples.google())
        self.assertRefuses(pm.edit_item, ready, "p001", pm.TEXTS, 0, "")
        for bad_index in (2, -1, True, "0", None):
            self.assertRefuses(pm.confirm_item, ready, "p001", pm.TEXTS, bad_index)
        for bad_kind in ("caption", "", None, "OBJECTS"):
            self.assertRefuses(pm.confirm_item, ready, "p001", bad_kind, 0)
        self.assertRefuses(pm.confirm_item, ready, "p001", pm.TEXTS, 0, "yes")

    def test_an_item_the_user_did_not_confirm_is_not_a_fact(self):
        manifest, _dropped = pm.set_analysis(confirmed(build(1), "p001"), "p001", method="local:x", texts=["UNIQ-PRICE 99,000원"])
        manifest = confirmed(manifest, "p001")
        sent = pm.draft_inputs(manifest)
        self.assertEqual(sent[0].confirmed_texts, ())
        self.assertNotIn("UNIQ-PRICE", repr(sent) + json.dumps(sent[0].to_dict(), ensure_ascii=False))


class PlaceholderTest(Base):
    def test_the_placeholder_is_the_photo_number_in_double_braces(self):
        self.assertEqual(pm.placeholder(3), "{{사진 3}}")
        self.assertEqual(pm.placeholder("p012"), "{{사진 12}}")
        self.assertEqual(pm.placeholder(999), "{{사진 999}}")
        self.assertEqual(pm.number_of("p003"), 3)
        self.assertEqual(pm.photo_id_of(3), "p003")
        for bad in (0, 1000, -1, True, None, "x", "p000", "p1", 2.0):
            self.assertRefuses(pm.placeholder, bad)

    def test_stray_braces_matches_the_plain_definition_and_grows_with_the_text_not_its_square(self):
        """검증 S-16 — 옛 구현은 글자 수의 제곱에 비례해(1만 개 자리표시자 본문 13초) 느렸다. 같은 답을 선형으로 내는지 단순한 정의와 견주고, 큰 본문이 금방 끝나는지 본다."""
        import random
        import re
        import time
        rng = random.Random(20261116)
        parts = ["{{", "}}", "{{사진 1}}", "{{사진 22}}", "{{사진 0}}", "{{사진 1 }}", "{", "}", "가", " ", "{{{", "}}}", "{{사진 7}}{{"]

        def plain(text):
            spans = [(start, end) for _n, start, end in pm.find_placeholders(text)]
            return sum(1 for found in re.finditer("[{][{]|[}][}]", text) if not any(start <= found.start() < end for start, end in spans))

        for _ in range(400):
            text = "".join(rng.choice(parts) for _ in range(rng.randint(0, 30)))
            self.assertEqual(pm.stray_braces(text), plain(text), text)
        self.assertEqual(pm.stray_braces("{{사진 1}} {{ }}"), 2)
        self.assertEqual(pm.stray_braces(None), 0)
        big = ("{{사진 1}}" + "본문 " * 5) * 10_000 + "{{ 하나 }}"
        started = time.perf_counter()
        report = pm.placeholder_report(build(3), big)
        elapsed = time.perf_counter() - started
        self.assertEqual((len(report.found), report.stray), (10_000, 2))
        self.assertLess(elapsed, 3.0, "1만 개 자리표시자 본문이 몇 초씩 걸리면 안 된다(옛 구현 13초)")
        many = "".join(f"{{{{사진 {number}}}}} " for number in range(1, 1000)) * 10
        started = time.perf_counter()
        report = pm.placeholder_report(build(3), many)
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertEqual(len(report.repeated), 999)

    def test_only_the_exact_form_counts_and_the_positions_are_reported(self):
        text = "도입 {{사진 1}} 본문{{사진 12}}끝 {{사진 1}}"
        found = pm.find_placeholders(text)
        self.assertEqual([item[0] for item in found], [1, 12, 1])
        for number, start, end in found:
            self.assertEqual(text[start:end], f"{{{{사진 {number}}}}}")
        for near in ("{{사진3}}", "{{ 사진 3 }}", "{{사진 03}}", "{{사진 0}}", "{{사진 1000}}", "{{사진  3}}", "{{사진 ３}}", "{사진 3}", "{{photo 3}}", "[사진 3]", "{{사진 3}", "{{사진 -3}}", "{{사진 3 }}", "{{사진 3\n}}"):
            with self.subTest(near=near):
                self.assertEqual(pm.find_placeholders(near), ())
        self.assertEqual(pm.find_placeholders(None), ())
        self.assertEqual(pm.find_placeholders(""), ())
        self.assertEqual(len(pm.find_placeholders("{{사진 1}}{{사진 2}}")), 2)

    def test_braces_that_are_not_exact_placeholders_are_counted_as_stray(self):
        self.assertEqual(pm.stray_braces("{{사진 1}} 본문"), 0)
        self.assertEqual(pm.stray_braces("{{사진3}}"), 2)
        self.assertEqual(pm.stray_braces("앞 {{ 이름 }} {{사진 1}} {{사진 2}}"), 2)
        self.assertEqual(pm.stray_braces("{{{{사진 1}}"), 1)
        self.assertEqual(pm.stray_braces(None), 0)

    def test_the_report_names_what_does_not_match_between_the_body_and_the_photo_list(self):
        manifest = confirmed(build(4), "p001", "p002", "p003")                    # p004 는 확정하지 않았다
        ok = pm.placeholder_report(manifest, "가 {{사진 1}} 나 {{사진 2}} 다 {{사진 3}}")
        self.assertTrue(ok.ok)
        self.assertEqual(ok.found, (1, 2, 3))
        report = pm.placeholder_report(manifest, "{{사진 2}} {{사진 9}} {{사진 4}} {{사진 2}} {{사진 1}} {{사진3}}")
        self.assertEqual(report.dangling, (9,))
        self.assertEqual(report.unconfirmed, (4,))
        self.assertEqual(report.missing, (3,))
        self.assertEqual(report.repeated, (2,))
        self.assertTrue(report.order_differs)
        self.assertEqual(report.stray, 2)
        self.assertFalse(report.ok)
        self.assertEqual(report.found, (2, 9, 4, 2, 1))
        self.assertTrue(pm.placeholder_report(manifest, "{{사진 3}} {{사진 1}} {{사진 2}}").order_differs)
        self.assertFalse(pm.placeholder_report(manifest, "{{사진 1}} {{사진 3}}").order_differs, "빠진 것은 순서가 아니라 '빠짐' 으로 알린다")
        self.assertEqual(pm.placeholder_report(manifest, "{{사진 1}} {{사진 3}}").missing, (2,))
        self.assertTrue(pm.placeholder_report(pm.empty_manifest(), "본문만").ok)
        self.assertFalse(pm.placeholder_report(pm.empty_manifest(), "{{사진 1}}").ok)

    def test_reordering_or_removing_photos_does_not_move_the_numbers_in_the_body(self):
        manifest = confirmed(build(3), "p001", "p002", "p003")
        body = "{{사진 1}} 와 {{사진 2}} 와 {{사진 3}}"
        self.assertTrue(pm.placeholder_report(manifest, body).ok)
        moved = pm.move_photo(manifest, "p003", 1)
        self.assertEqual([photo.number for photo in moved.photos], [3, 1, 2])
        self.assertTrue(pm.placeholder_report(moved, body).order_differs, "순서가 어긋났다고 알린다")
        self.assertEqual(pm.placeholder_report(moved, body).dangling, ())
        removed = pm.remove_photo(manifest, "p002")
        self.assertEqual(pm.placeholder_report(removed, body).dangling, (2,))
        self.assertIs(removed.by_number(2), None)
        self.assertEqual(removed.by_number(3).display_order, 2, "순서만 다시 매기고 번호는 그대로다")


class LooksLikePathTest(unittest.TestCase):
    """복사 확인창이 알리는 '파일 경로처럼 보이는 글' 규칙(검증 S PS-4) — 드라이브 경로·네트워크 위치(UNC)·`file:///` 는 참, 인터넷 주소·시각·문장 속 `글자:` 는 거짓이다. 참·거짓만 돌려주고 글은 되풀이하지 않는다."""
    BS = chr(92)

    def test_paths_that_look_like_files_are_found_anywhere_in_a_sentence(self):
        bs = self.BS
        cases = (("원본은 C:" + bs + "Users" + bs + "홍길동" + bs + "Pictures" + bs + "간판.jpg 예요", "드라이브 경로(역슬래시)"), ("원본은 d:/photos/a.jpg 예요", "드라이브 경로(슬래시·소문자)"), ("(C:/x)", "괄호 바로 뒤"),
                 ("사진C:" + bs + "a.jpg", "한글 바로 뒤"), (bs * 2 + "서버" + bs + "공유" + bs + "사진.jpg", "네트워크 위치(한글 서버)"), ("위치 " + bs * 2 + "nas/photos", "네트워크 위치(슬래시)"),
                 ("file:///C:/a.jpg", "file 주소"), ("FILE:///a", "file 주소(대문자)"))
        for text, what in cases:
            with self.subTest(what):
                self.assertIs(pm.looks_like_path(text), True)

    def test_things_that_only_resemble_a_path_are_not_found(self):
        bs = self.BS
        cases = (("https://blog.naver.com/x", "https 주소"), ("http://x", "http 주소"), ("오전 10:30/11:00 에 갔어요", "시각"), ("Note:/ 참고", "문장 속 글자와 콜론"), ("C: 드라이브", "슬래시 없음"), ("C:file", "슬래시 없음 2"),
                 (bs * 2 + "서버", "슬래시 없는 역슬래시 둘"), (bs + "n 줄바꿈 글자", "역슬래시 하나"), ("그냥 맛있는 집이에요", "일반 문장"), ("", "빈 글"))
        for text, what in cases:
            with self.subTest(what):
                self.assertIs(pm.looks_like_path(text), False)

    def test_anything_that_is_not_text_is_not_a_path(self):
        for value in (None, 0, 3.5, b"C:/a", ("C:/a",), ["C:/a"]):
            with self.subTest(repr(value)):
                self.assertIs(pm.looks_like_path(value), False)

    def test_long_texts_without_a_path_are_checked_in_linear_time(self):
        import time
        for text in ("가나다 " * 50000, "a:" * 100000, chr(92) * 200000, "http://" * 50000):
            started = time.perf_counter()
            self.assertIs(pm.looks_like_path(text), False)
            self.assertLess(time.perf_counter() - started, 3.0)


class StrictReadTest(Base):
    def good(self):
        return json.loads(confirmed(build(2, user_note="메모"), "p001").to_text())

    def test_wrong_shapes_are_refused_with_fixed_sentences_that_never_repeat_paths_or_texts(self):
        def mutate(change):
            data = self.good()
            change(data)
            return data

        cases = {
            "객체 아님": [1, 2], "문자열": "x", "None": None, "바깥 키 빠짐": mutate(lambda d: d.pop("next_number")), "바깥 키 늘어남": mutate(lambda d: d.update(exif="x")),
            "schema 다름": mutate(lambda d: d.update(schema="other/1")), "schema 숫자": mutate(lambda d: d.update(schema=1)), "photos 객체": mutate(lambda d: d.update(photos={})),
            "photos 안이 글": mutate(lambda d: d.update(photos=["p001"])), "next_number 글": mutate(lambda d: d.update(next_number="3")), "next_number 불리언": mutate(lambda d: d.update(next_number=True)),
            "next_number 작음": mutate(lambda d: d.update(next_number=2)), "next_number 0": mutate(lambda d: d.update(next_number=0)), "draft_id 틀림": mutate(lambda d: d.update(draft_id="DD-1")),
            "draft_id 숫자": mutate(lambda d: d.update(draft_id=5)),
            "display_order 불리언": mutate(lambda d: d["photos"][0].update(display_order=True)), "display_order 글": mutate(lambda d: d["photos"][0].update(display_order="1")),
            "display_order 소수": mutate(lambda d: d["photos"][0].update(display_order=1.0)), "순서 빈틈": mutate(lambda d: d["photos"][1].update(display_order=3)),
            "confirmed 숫자": mutate(lambda d: d["photos"][0].update(confirmed_by_user=1)), "confirmed 글": mutate(lambda d: d["photos"][0].update(confirmed_by_user="true")),
            "photo_id 틀림": mutate(lambda d: d["photos"][0].update(photo_id="P001")), "photo_id 중복": mutate(lambda d: d["photos"][1].update(photo_id="p001")),
            "경로 중복": mutate(lambda d: d["photos"][1].update(local_path=d["photos"][0]["local_path"])), "경로 틀림": mutate(lambda d: d["photos"][0].update(local_path="..\\a.jpg")),
            "경로 gif": mutate(lambda d: d["photos"][0].update(local_path="C:\\a.gif")), "경로 숫자": mutate(lambda d: d["photos"][0].update(local_path=5)),
            "method 틀림": mutate(lambda d: d["photos"][0].update(analysis_method="gemini")), "placement 글": mutate(lambda d: d["photos"][0].update(placement="top")),
            "placement 키 늘어남": mutate(lambda d: d["photos"][0]["placement"].update(extra=1)), "placement kind": mutate(lambda d: d["photos"][0]["placement"].update(kind="end")),
            "placement nth": mutate(lambda d: d["photos"][0]["placement"].update(kind="after_paragraph", nth=0)), "관찰 글": mutate(lambda d: d["photos"][0].update(observed_objects="접시")),
            "관찰 항목 글": mutate(lambda d: d["photos"][0].update(visible_text=["김치"])), "관찰 항목 키": mutate(lambda d: d["photos"][0].update(visible_text=[{"text": "김치"}])),
            "관찰 항목 확인": mutate(lambda d: d["photos"][0].update(visible_text=[{"text": "김치", "confirmed": "yes"}])),
            "관찰 짐작": mutate(lambda d: d["photos"][0].update(observed_objects=[{"text": "웃는 사람", "confirmed": True}])),
            "메모 길이": mutate(lambda d: d["photos"][0].update(user_note="가" * 301)), "메모 태그": mutate(lambda d: d["photos"][0].update(user_note="<b>")), "대상 숫자": mutate(lambda d: d["photos"][0].update(user_subject=5)),
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                error = self.assertRefuses(pm.PhotoManifest.from_dict, data)
                self.assertNoLeak(error, [USER_DIR, FILE_STEM, "UNIQ"])
                self.assertTrue(error.rendered().message)

    def test_text_that_is_not_the_stored_form_is_refused(self):
        good = self.good()
        text = json.dumps(good, ensure_ascii=False)
        for name, bad in {"BOM": "\ufeff" + text, "빈 글": "", "공백": "  ", "JSON 아님": "{abc", "같은 키 두 번": text.replace('"schema"', '"next_number": 3, "schema"', 1), "NaN": text.replace('"next_number": 3', '"next_number": NaN'),
                          "Infinity": text.replace('"next_number": 3', '"next_number": Infinity'), "깊은 겹침": "[" * 100000 + "]" * 100000, "글 아님": b"{}", "None": None, "너무 큼": " " * (pm.MAX_TEXT_BYTES + 1),
                          "바이트로 큼": "가" * (pm.MAX_TEXT_BYTES // 3 + 1), "뒤에 글": text + " x"}.items():
            with self.subTest(case=name):
                self.assertRefuses(pm.PhotoManifest.from_text, bad)
        self.assertEqual(pm.PhotoManifest.from_text(text), pm.PhotoManifest.from_dict(good))
        self.assertEqual(pm.PhotoManifest.from_text(text + "\n\n  "), pm.PhotoManifest.from_dict(good))
        room = pm.MAX_TEXT_BYTES - len(text.encode("utf-8"))
        self.assertEqual(pm.PhotoManifest.from_text(text + " " * room), pm.PhotoManifest.from_dict(good), "512KB 정확히는 된다")
        error = self.assertRefuses(pm.PhotoManifest.from_text, text + " " * (room + 1))
        self.assertIn("너무 커요", error.rendered().message, "JSON 으로는 멀쩡해도 512KB 를 넘으면 읽지 않는다")

    def test_a_newer_schema_is_reported_as_newer_and_other_schemas_as_wrong(self):
        for newer in ("chanceblog.photo-manifest/2", "chanceblog.photo-manifest/10"):
            data = self.good()
            data["schema"] = newer
            error = self.assertRefuses(pm.PhotoManifest.from_dict, data, code="STORE_VERSION_UNSUPPORTED")
            self.assertTrue(error.rendered().message)
        for other in ("chanceblog.photo-manifest/0", "chanceblog.photo-manifest/x", "chanceblog.photo-manifest/", "chanceblog.photo-manifest/1.0", "chanceblog.other/1", "chanceblog.photo-manifest/-2", "chanceblog.photo-manifest/²"):
            data = self.good()
            data["schema"] = other
            self.assertRefuses(pm.PhotoManifest.from_dict, data)

    def test_errors_carry_no_path_text_or_photo_file_name_in_any_channel(self):
        data = self.good()
        data["photos"][0]["local_path"] = "C:\\Users\\" + USER_DIR + "\\..\\" + FILE_STEM + ".jpg"
        error = self.assertRefuses(pm.PhotoManifest.from_dict, data)
        self.assertNoLeak(error, [USER_DIR, FILE_STEM])
        for error in (code_of(pm.add_photo, pm.empty_manifest(), win("x.gif")), code_of(pm.add_photo, pm.empty_manifest(), win("a.jpg"), user_note="UNIQ-NOTE-q<b>"),
                      code_of(pm.update_photo, build(1), "p001", user_note="UNIQ-NOTE-q<b>"), code_of(pm.update_photo, build(1), "p001", local_path=win("y.gif"))):
            self.assertEqual(error.code, "CONTENT_INVALID")
            self.assertNoLeak(error, [USER_DIR, "UNIQ-NOTE-q", ".gif"])


class SourceRulesTest(unittest.TestCase):
    def test_the_core_module_is_pure_no_files_no_network_no_clock_no_random_no_output(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        forbidden = {"subprocess", "socket", "urllib", "http", "ssl", "webbrowser", "ctypes", "requests", "asyncio", "random", "secrets", "time", "datetime", "logging", "shutil", "tempfile", "pathlib", "PySide6"}
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            for name in names:
                self.assertNotIn(name.split(".")[0], forbidden)
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        for banned in ("open", "print", "input", "exec", "eval", "os.stat", "os.lstat", "os.listdir", "os.scandir", "os.walk", "os.remove", "os.replace", "os.makedirs", "os.environ.get", "os.getenv", "Path"):
            self.assertNotIn(banned, calls)
        attributes = {ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Attribute) and ast.unparse(node.value) == "os"}
        self.assertEqual(attributes, {"os.name"}, "운영체제 이름 하나만 읽는다")
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("print(", text)

    def test_using_the_pure_module_in_a_fresh_interpreter_loads_no_network_process_or_screen_module(self):
        """정적 검사(위)에 더해 실제로 써 본다 — 새 인터프리터에서 모듈을 가져와 사진을 더하고 초안 입력까지 뽑아도(늦게 가져오는 `imagerules`·`security` 포함) 소켓·ssl·http·하위 프로세스·PySide6 같은 모듈이 올라오지 않는다."""
        import subprocess
        # `import uuid` 는 스냅샷 앞에 둔다: 기존 모듈(content/candidates.py·model.py)이 uuid 를 가져오는데, 파이썬 3.10 의 uuid 는 윈도·맥이 아니면 맨 위에서 platform 을 가져오고
        # 3.10 의 platform 은 subprocess(→ select·selectors)를 맨 위에서 가져온다 — 리눅스 3.10 에서만 이 셋이 같이 올라와 앱 CI 한 칸이 빨갛게 됐다(2026-11-16).
        # 감시 목록(subprocess·select·selectors 포함)은 그대로 두고, 사진 규칙 모듈이 '새로' 올린 것만 본다(소스에서 이 모듈들을 가져오는 일은 위 정적 검사가 따로 막는다).
        code = "\n".join(["import sys", "sys.path.insert(0, sys.argv[1])", "import uuid", "before = set(sys.modules)", "from chanceblog_desktop.content import photo_manifest as pm",
                          "m = pm.add_photo(pm.empty_manifest(), 'C:/a/b.jpg')[0]", "pm.draft_inputs(pm.set_confirmed(m, 'p001', True))", "pm.PhotoManifest.from_text(m.to_text())", "loaded = sorted(set(sys.modules) - before)",
                          "watch = ('socket', 'ssl', 'http', 'subprocess', 'ctypes', 'asyncio', 'PySide6', 'requests', 'webbrowser', 'smtplib', 'ftplib', 'select', 'selectors', 'tempfile', 'logging', 'random', 'secrets', 'shutil')",
                          "print([n for n in loaded if n.split('.')[0] in watch or n == 'urllib.request'])"])
        done = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c", code, str(ROOT / "src")], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-400:])
        self.assertEqual(done.stdout.strip(), "[]", "이 모듈이 바깥과 닿는 모듈을 올렸다")

    def test_the_screen_layer_is_reached_only_for_imagerules_and_only_inside_a_function(self):
        """검증 Q-4 — 규칙 모듈이 화면 층(`ui.core`)을 가져오는 것은 이 저장소에서 처음이라 예외를 하나로 좁힌다: `imagerules` 한 모듈만, 함수 안에서만(맨 위에서 가져오면 `ui/core/__init__` 때문에 문구 모듈 열 개가 같이 올라온다)."""
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = (node.module or "") if isinstance(node, ast.ImportFrom) else ""
                self.assertNotIn("ui", module.split("."), "화면 층은 맨 위에서 가져오지 않는다")
        found = {(node.module, tuple(alias.name for alias in node.names)) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and "ui" in (node.module or "").split(".")}
        self.assertEqual(found, {("ui.core", ("imagerules",))}, "허용 집합은 imagerules 하나다")

    def test_the_text_checks_reuse_the_existing_checkers_instead_of_new_ones(self):
        source = SOURCE.read_text(encoding="utf-8")
        for needle in ("clean_line", "find_markup", "forbidden_claim", "_BLANK_LOOKALIKES", "_STACKED_MARKS", "_looks_secret", "scan.has_secret", "imagerules", "is_draft_id"):
            self.assertIn(needle, source, needle)

    def test_every_error_code_used_exists_in_the_catalog(self):
        from chanceblog_desktop.errors import CATALOG
        import re
        codes = set(re.findall(r'AppError\(\s*"([A-Z][A-Z0-9_]+)"', SOURCE.read_text(encoding="utf-8")))
        self.assertEqual(codes, {"CONTENT_INVALID", "STORE_VERSION_UNSUPPORTED"})
        for code in codes:
            self.assertIn(code, CATALOG)


if __name__ == "__main__":
    unittest.main()
