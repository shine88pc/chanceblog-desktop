"""확정한 글자가 든 초안의 화면 규칙·복사·저장·다시 열기 시험 — 글자 읽기 b 단계 B3(설계 2-8·2-9·4절, 결정 D-520에서 D-525). 순수 층(`ui/core`)과 진짜 서비스(임시 폴더)로 돌고 PySide6·네트워크·실제 시크릿이 없다.
본문 생성기 쪽은 `test_content_photo_text_body` 가 본다.

지키는 것:
  1) 만들 때(`이 주제로 만들기`·`다시 만들기`) 확정한 사진의 확정한 줄만 요청에 실려 본문에 틀 문장과 줄들로 들어간다(경로·파일 이름은 요청에 없다). 확정한 글자가 없으면 본문이 지금과 같다.
  2) 복사는 줄을 그대로 두고 `{{사진 N}}` 만 `[이미지 N]` 으로 바꾼다. 올릴 사진 순서 안내·경로 모양 안내·'확인하지 않은 가격' 안내는 확정한 글자에도 그대로 동작한다.
  3) 확정한 줄이 바뀌면 카드가 '다시 만들기' 를 안내하고 본문은 몰래 고치지 않는다.
  4) 읽은 글은 저장하지 않는다 — 저장한 파일에는 줄이 없고(칸은 열네 개 그대로), 다시 연 초안은 저장한 본문을 그대로 두지만 줄은 없으며 '다시 만들기' 를 하면 확정한 글자 문단이 본문에 안 들어간다(알려 둔 한계).
"""
import dataclasses
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_content_photo_text_body import FRAME, MENU, METHOD, NL, old_photo_lines  # noqa: E402
from test_ui_drafts_core import GENERIC, target_of  # noqa: E402
from test_ui_drafts_save_core import drive, made_saving, saving  # noqa: E402
from test_ui_drafts_save_service import fresh  # noqa: E402
from test_ui_drafts_save_service import store as real_store  # noqa: E402
from test_ui_drafts_service import drive as real_drive  # noqa: E402
from test_ui_drafts_service import drive_regenerate  # noqa: E402
from test_ui_drafts_service import target_of as real_target_of  # noqa: E402
from test_ui_photo_copy_core import copied  # noqa: E402
from test_ui_photo_make_core import confirm  # noqa: E402
from test_ui_photo_save_core import path_of  # noqa: E402
from test_ui_photo_save_service import Base  # noqa: E402

from chanceblog_desktop.check import claims  # noqa: E402
from chanceblog_desktop.content import photo_flow as pf  # noqa: E402
from chanceblog_desktop.content import photo_manifest as pm  # noqa: E402
from chanceblog_desktop.security import mask as mask_module  # noqa: E402
from chanceblog_desktop.security import shape  # noqa: E402
from chanceblog_desktop.ui.core import draft_rules as rules  # noqa: E402
from chanceblog_desktop.ui.core import text  # noqa: E402

T = text.T
WIFI = ("아메리카노 4,500원", "Wi-Fi Password:", "12345678", "콘센트 사용 가능")          # 줄 하나씩은 입구를 지나고 이으면 `mask` 가 '이름: 값' 으로 읽는 글(독립 검증 SP-1)


def read_lines(controller, number, lines, confirmed=()):
    """사진 `number` 의 읽은 줄을 목록에 채우고(`set_analysis` — 글자 읽기가 하는 일) `confirmed` 의 줄을 확인한 뒤 사진을 확정한다."""
    photo_id = pm.photo_id_of(number)
    manifest, _dropped = pm.set_analysis(controller.photos.manifest, photo_id, method=METHOD, texts=lines)
    for index in confirmed:
        manifest = pm.confirm_item(manifest, photo_id, pm.TEXTS, index)
    controller.photos.manifest = manifest
    return controller.photos.confirm(photo_id, True)


def with_lines(lines=MENU, confirmed="all", photo_count=2):
    """사진 `photo_count` 장을 넣고 첫 사진에 읽은 줄을 확인해 확정한 뒤 만든 컨트롤러."""
    controller, provider = made_saving()
    controller.photos.add_paths([path_of(number) for number in range(1, photo_count + 1)])
    read_lines(controller, 1, lines, range(len(lines)) if confirmed == "all" else confirmed)
    for number in range(2, photo_count + 1):
        confirm(controller, number, user_subject=f"대상 {number}")
    drive(controller)
    return controller, provider


class MakeTest(unittest.TestCase):
    def test_only_the_confirmed_lines_of_confirmed_photos_ride_along_and_land_in_the_made_body(self):
        controller, provider = made_saving()
        controller.photos.add_paths([path_of(1), path_of(2), path_of(3)])
        read_lines(controller, 1, MENU, confirmed=(0, 2))
        read_lines(controller, 2, ("둘째 글",))
        read_lines(controller, 3, ("셋째 글",), confirmed=(0,))
        controller.photos.confirm("p003", False)
        self.assertEqual(drive(controller), "started")
        request = provider.calls[-1]
        self.assertEqual([(item.number, item.confirmed_texts) for item in request.photos], [(1, (MENU[0], MENU[2])), (2, ())], "확정하지 않은 사진은 싣지 않고 확인 안 한 줄도 싣지 않는다")
        self.assertNotIn("UNIQ-", str(dataclasses.asdict(request)) + repr(request), "경로·파일 이름은 요청에 없다")
        body = controller.body
        self.assertIn(FRAME + NL + NL + MENU[0] + NL + MENU[2], body)
        self.assertEqual(body.count(FRAME), 1)
        for left_out in (MENU[1], "둘째 글", "셋째 글"):
            self.assertNotIn(left_out, body)

    def test_without_confirmed_lines_the_made_body_is_what_it_was(self):
        controller, _provider = made_saving()
        controller.photos.add_paths([path_of(1), path_of(2)])
        confirm(controller, 1, user_subject="매장 입구 간판", user_note="주차는 뒤쪽이에요")
        confirm(controller, 2, caption="메뉴판 앞에서")
        drive(controller)
        made = (controller.title, controller.body)
        self.assertNotIn(FRAME, controller.body)
        with mock.patch.object(pf, "photo_lines", old_photo_lines):
            drive(controller)
        self.assertEqual((controller.title, controller.body), made)

    def test_photos_with_lines_that_are_all_unconfirmed_make_the_same_body_as_the_old_way(self):
        controller, _provider = with_lines(confirmed=())
        made = controller.body
        self.assertNotIn(FRAME, made)
        for line in MENU:
            self.assertNotIn(line, made)
        with mock.patch.object(pf, "photo_lines", old_photo_lines):
            drive(controller)
        self.assertEqual(controller.body, made)


class BlockedMakeTest(unittest.TestCase):
    """줄 하나씩은 입구를 지나는 확정 줄들을 이으면 비밀 모양으로 읽히는 경우(독립 검증 SP-1, 결정 D-522) — 사진 정보 검사가 만들기 전에 막고 화면은 사진 정보를 가리킨다(주제 후보 탓도, '잠시 뒤 다시 시도' 도 아니다)."""

    def test_the_remake_stops_at_the_photo_info_sentence_keeps_the_body_and_never_calls_the_provider(self):
        controller, provider = made_saving()
        controller.photos.add_paths([path_of(1)])
        read_lines(controller, 1, WIFI, range(len(WIFI)))
        calls, before = len(provider.calls), (controller.title, controller.body, controller.state)
        self.assertEqual(drive(controller), "photos")
        self.assertEqual(controller.notice, ("error", T["pho_make_blocked"]))
        self.assertEqual(len(provider.calls), calls, "공급자는 부르지도 않는다")
        self.assertEqual((controller.title, controller.body, controller.state), before, "이미 만든 본문은 그대로다")
        for line in WIFI:
            self.assertNotIn(line, str(controller.notice))

    def test_the_first_make_stops_at_the_photo_info_too_and_the_failure_screen_never_shows(self):
        controller, provider = saving()
        controller.open_target(target_of(GENERIC))
        controller.photos.add_paths([path_of(1)])
        read_lines(controller, 1, WIFI, range(len(WIFI)))
        state = controller.state
        self.assertEqual(drive(controller), "photos")
        self.assertEqual((controller.state, controller.result, provider.calls), (state, None, []))
        self.assertNotEqual(controller.state, "error", "'초안을 만들지 못했어요 — 잠시 뒤에 다시 시도' 화면이 아니다")
        self.assertEqual(controller.notice, ("error", T["pho_make_blocked"]))

    def test_unconfirming_the_name_line_lets_the_make_through_and_the_other_lines_land_in_the_body(self):
        controller, _provider = made_saving()
        controller.photos.add_paths([path_of(1)])
        read_lines(controller, 1, WIFI, range(len(WIFI)))
        self.assertEqual(drive(controller), "photos")
        controller.photos.manifest = pm.confirm_item(controller.photos.manifest, "p001", pm.TEXTS, 1, False)
        controller.photos.confirm("p001", True)
        self.assertEqual(drive(controller), "started", "풀 길은 이름 줄을 확인하지 않거나 지우는 것이다")
        self.assertIn(FRAME + NL + NL + NL.join((WIFI[0], WIFI[2], WIFI[3])), controller.body)
        self.assertNotIn(WIFI[1], controller.body)

    def test_the_card_asks_for_no_remake_while_the_lines_are_refused(self):
        controller, _provider = with_lines(lines=MENU[:2])
        self.assertEqual(controller.photos_card()["remake"], "")
        manifest, _dropped = pm.set_analysis(controller.photos.manifest, "p001", method=METHOD, texts=WIFI)
        for index in range(len(WIFI)):
            manifest = pm.confirm_item(manifest, "p001", pm.TEXTS, index)
        controller.photos.manifest = manifest
        controller.photos.confirm("p001", True)
        self.assertEqual(controller.photos_card()["remake"], "", "막힌 사진 정보는 '다시 만들기' 를 안내하지 않는다(기존 막힘과 같다) — 만들기를 누르면 막힌 이유 문장이 나온다")
        self.assertEqual(drive(controller), "photos")
        self.assertEqual(controller.notice, ("error", T["pho_make_blocked"]))


class CopyTest(unittest.TestCase):
    def pile(self, photo_count):
        """사진 `photo_count` 장 × 줄 60개 × 줄당 200자를 모두 확정해 만든 컨트롤러."""
        controller, _provider = made_saving()
        controller.photos.add_paths([path_of(number) for number in range(1, photo_count + 1)])
        for number in range(1, photo_count + 1):
            lines = tuple((f"{number:02d}-{index:02d}-" + "가나다라마바사 " * 40)[:200] for index in range(60))
            read_lines(controller, number, lines, range(len(lines)))
        drive(controller)
        return controller

    def test_the_copy_gate_blocks_a_body_over_one_hundred_thousand_characters_and_lets_one_under_it_through(self):
        """알려 둔 한계(독립 검증 QP-2, 결정 D-523) — 본문 만들기는 20만 자까지 되고 저장은 3만 자까지인데, 복사 관문은 10만 자(`security.shape.MAX_SCAN_CHARS`)를 넘는 본문을 키 모양 검사를 믿을 수 없다고 보고 막는다."""
        self.assertEqual(shape.MAX_SCAN_CHARS, 100_000)
        ordinary = "가나다 " * 40_000
        self.assertEqual(rules.secret_spots(ordinary[:100_000]), ())
        self.assertEqual(rules.secret_spots(ordinary[:100_001]), ((0, 1),), "넘으면 믿을 수 없어 처음 한 자리를 돌려준다(실패 열림 금지)")
        small, large = self.pile(7), self.pile(9)
        self.assertLess(len(small.body), shape.MAX_SCAN_CHARS)
        self.assertGreater(len(large.body), shape.MAX_SCAN_CHARS)
        self.assertLess(len(large.body), mask_module.MAX_MASK_INPUT, "만들어지기는 한다 — 막는 것은 복사 관문뿐이다")
        self.assertIsNotNone(copied(small, "body"), "10만 자 이하에서 복사는 된다")
        self.assertEqual(large.copy_decision("body")[0], "blocked")
        self.assertIsNone(copied(large, "body"))

    def test_the_body_copy_keeps_the_lines_and_turns_only_the_slots_into_image_marks(self):
        controller, _provider = with_lines()
        body = copied(controller, "body")
        self.assertEqual(body, controller.body.replace("{{사진 1}}", "[이미지 1]").replace("{{사진 2}}", "[이미지 2]"))
        self.assertNotIn("{{", body)
        for line in MENU:
            self.assertIn(line, body.split(NL))
        self.assertEqual(copied(controller, "all"), controller.title + NL + NL + body)

    def test_the_upload_order_lines_are_the_same_with_or_without_the_lines(self):
        with_text, _provider = with_lines()
        without, _other = with_lines(confirmed=())
        shown, plain = dict(with_text.gate("body").reasons), dict(without.gate("body").reasons)
        self.assertEqual(shown["uploads"], plain["uploads"])
        self.assertEqual(len(shown["uploads"]), 2, "올릴 사진은 번호와 짧은 파일 이름 두 줄")
        self.assertNotIn("photos", shown, "어긋남이 없다")
        self.assertEqual(with_text.photo_gate_lines("body")[0], ())

    def test_a_path_shaped_line_shows_the_path_note_like_any_user_text_and_plain_lines_do_not(self):
        controller, _provider = with_lines(("메뉴 하나", "C:/Users/누구/Pictures/간판.jpg", "메뉴 셋"))
        self.assertEqual(controller.photo_gate_notes("body"), (T["pho_gate_paths"],))
        plain, _other = with_lines()
        self.assertEqual(plain.photo_gate_notes("body"), ())

    def test_prices_in_confirmed_lines_show_up_in_the_copy_dialog_as_unchecked_prices(self):
        controller, _provider = with_lines()
        shown = dict(controller.gate("body").reasons).get("claims", ())
        self.assertTrue(any(line.startswith(claims.LABELS[claims.PRICE]) and "28,000원" in line for line in shown), shown)
        decision, dialog = controller.copy_decision("body")
        self.assertEqual(decision, "confirm")
        self.assertIn("28,000원", dialog["body"])

    def test_a_claim_like_confirmed_line_is_listed_in_the_copy_dialog_and_never_passes_silently(self):
        """사진에 적힌 글이 직접 겪은 일처럼 읽혀도(후기 문구가 적힌 간판 등) 확정한 줄은 초안을 거절하지 않지만, 복사할 때 확인창이 '직접 사용·체험했다는 주장' 으로 먼저 알리고 막지는 않는다."""
        controller, _provider = with_lines(("직접 사용해 보니 효과가 좋았어요", "한우 불고기 전골"))
        self.assertIn("직접 사용해 보니 효과가 좋았어요", controller.body)
        shown = dict(controller.gate("body").reasons).get("claims", ())
        self.assertTrue(any(line.startswith(claims.LABELS[claims.EXPERIENCE_USE]) for line in shown), shown)
        self.assertEqual(controller.copy_decision("body")[0], "confirm", "막지 않고 먼저 묻는다")

    def test_a_strong_health_claim_in_a_confirmed_line_blocks_the_copy_like_any_other_text_and_deleting_it_unblocks(self):
        """제품 라벨의 효능 문구처럼 건강 효과를 단정하는 글이 확정한 줄에 있으면 복사 관문이 막는다(기존 규칙 그대로 — 새 구멍이 없다). 본문에서 그 문단을 지우면 풀린다."""
        controller, _provider = with_lines(("당뇨 100% 완치 보장",))
        self.assertIn("당뇨 100% 완치 보장", controller.body)
        self.assertEqual(controller.health_for("body").stage, "stop")
        self.assertEqual(controller.copy_decision("body")[0], "blocked")
        controller.set_body(controller.body.replace(FRAME + NL + NL + "당뇨 100% 완치 보장", ""))
        self.assertNotIn("완치", controller.body)
        self.assertNotEqual(controller.copy_decision("body")[0], "blocked")

    def test_a_mild_health_claim_in_a_confirmed_line_only_asks_for_a_check_it_is_not_blocked(self):
        controller, _provider = with_lines(("면역력 증진에 도움을 줄 수 있음", "1일 1회 1정 섭취"))
        self.assertEqual(controller.health_for("body").stage, "evidence")
        self.assertEqual(controller.copy_decision("body")[0], "confirm")

    def test_the_photo_gate_stays_quiet_about_the_lines_themselves(self):
        controller, _provider = with_lines()
        problems, uploads = controller.photo_gate_lines("body")
        self.assertEqual((problems, len(uploads)), ((), 2))


class RemakeTest(unittest.TestCase):
    def test_changing_the_confirmed_lines_after_making_asks_for_a_remake_and_never_edits_the_body(self):
        controller, _provider = with_lines(confirmed=(0, 1))
        self.assertEqual(controller.photos_card()["remake"], "")
        before = controller.body
        controller.photos.manifest = pm.confirm_item(controller.photos.manifest, "p001", pm.TEXTS, 2)
        controller.photos.confirm("p001", True)
        self.assertEqual(controller.photos_card()["remake"], T["pho_card_remake"])
        self.assertEqual(controller.body, before, "본문은 몰래 고치지 않는다")
        self.assertNotIn(MENU[2], before)
        drive(controller)
        self.assertEqual(controller.photos_card()["remake"], "")
        self.assertIn(MENU[0] + NL + MENU[1] + NL + MENU[2], controller.body)

    def test_unconfirming_the_photo_takes_the_lines_out_of_the_next_make(self):
        controller, _provider = with_lines()
        self.assertIn(FRAME, controller.body)
        controller.photos.confirm("p001", False)
        drive(controller)
        self.assertNotIn(FRAME, controller.body)
        self.assertNotIn("{{사진 1}}", controller.body)


class RealServiceTest(Base):
    """진짜 공급자·서비스·임시 폴더 — 본문 만들기부터 저장·다시 열기·다시 만들기까지."""

    def lines_controller(self, lines=MENU):
        controller = self.with_photos()
        read_lines(controller, 1, lines, range(len(lines)))
        confirm(controller, 2, user_subject="두 번째 대상")
        real_drive(controller)
        return controller

    def test_the_real_engine_builds_the_body_with_the_frame_and_the_confirmed_lines(self):
        controller = self.lines_controller()
        body = controller.result.body
        self.assertIn(FRAME + NL + NL + NL.join(MENU), body.body_text)
        self.assertEqual(controller.body, body.body_text)
        self.assertEqual(body.generated_texts().count(FRAME), 1)
        self.assertEqual(claims.find_violations(list(body.generated_texts())), ())
        self.assertIn(NL.join(MENU), body.user_paragraphs())

    def test_the_wifi_lines_stop_the_first_make_at_the_photo_info_and_the_failure_screen_never_shows(self):
        controller = self.setup.controller()
        controller.open_target(real_target_of(self.engine))
        controller.photos.add_paths(self.paths)
        read_lines(controller, 1, WIFI, range(len(WIFI)))
        confirm(controller, 2, user_subject="두 번째 대상")
        state = controller.state
        self.assertEqual(real_drive(controller), "photos", "진짜 서비스까지 가지 않는다")
        self.assertEqual((controller.state, controller.result, controller.notice), (state, None, ("error", T["pho_make_blocked"])))
        self.assertNotEqual(controller.state, "error", "'초안을 만들지 못했어요 — 잠시 뒤에 다시 시도' 화면이 아니다")
        controller.photos.manifest = pm.confirm_item(controller.photos.manifest, "p001", pm.TEXTS, 1, False)
        controller.photos.confirm("p001", True)
        self.assertEqual(real_drive(controller), "started")
        self.assertIn(FRAME + NL + NL + NL.join((WIFI[0], WIFI[2], WIFI[3])), controller.body)

    def test_saving_writes_no_line_and_keeps_the_fourteen_fields(self):
        controller = self.lines_controller()
        real_store(controller, "save")
        data = (self.folder / f"{controller.saved_id}.json").read_bytes()
        for line in MENU:
            self.assertNotIn(line.encode("utf-8"), data)
        saved = json.loads(data.decode("utf-8"))
        self.assertEqual(sorted(saved), sorted(pm.ENVELOPE_KEYS))
        self.assertEqual(saved["schema"], pm.SCHEMA)
        for photo in saved["photos"]:
            self.assertEqual(sorted(photo), sorted(pm.FIELDS), "칸은 열네 개 그대로다")
            self.assertEqual(len(photo), 14)
            self.assertEqual((photo["visible_text"], photo["observed_objects"], photo["analysis_method"]), ([], [], "manual"))
        self.assertTrue(saved["photos"][0]["confirmed_by_user"], "확정은 저장된다 — 읽은 글만 저장하지 않는다")

    def test_a_reopened_draft_keeps_its_saved_body_but_has_no_lines_and_a_remake_leaves_them_out(self):
        controller = self.lines_controller()
        real_store(controller, "save")
        saved_body, draft_id = controller.body, controller.saved_id
        self.assertIn(FRAME + NL + NL + NL.join(MENU), saved_body)
        again = fresh(self.setup)
        real_store(again, "list")
        status, applied = real_store(again, "open", draft_id)
        self.assertEqual((status, applied), ("started", True))
        self.assertEqual(again.body, saved_body, "이미 저장한 본문은 그대로다 — 확정한 글자 문단도 그대로 들어 있다")
        self.assertEqual(tuple(photo.visible_text for photo in again.photos.manifest.photos), ((), ()), "읽은 글은 다시 열면 없다")
        self.assertEqual(tuple(photo.analysis_method for photo in again.photos.manifest.photos), ("manual", "manual"))
        self.assertEqual(again.photos_card()["remake"], "", "다시 연 순간의 사진을 기준으로 삼으므로 '다시 만들기' 안내가 안 뜬다 — 글자가 빠진다는 말은 화면 묶음이 따로 해야 한다")
        self.assertFalse(again.text_unsaved(), "저장한 본문을 안 고쳤으면 '다시 만들기' 에 확인창이 없다 — 확정한 글자 문단이 확인창도 없이 빠진다(알려 둔 한계, 화면 묶음이 안내를 정한다)")
        self.assertEqual(drive_regenerate(again), "started")
        self.assertNotIn(FRAME, again.body, "알려 둔 한계 — 다시 열어 '다시 만들기' 를 하면 확정한 글자는 본문에 안 들어간다(다시 읽고 확인해야 한다)")
        for line in MENU:
            self.assertNotIn(line, again.body)
        self.assertIn("{{사진 1}}", again.body, "사진 자리와 사용자 글은 그대로 들어간다")


if __name__ == "__main__":
    unittest.main()
