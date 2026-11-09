"""초안 작성 화면의 실제 공급자(`ui/drafts_adapter.py`) 시험 — 실제 임시 폴더의 엔진 보관함·설정 파일과 진짜 서비스 함수로 초안을 만들어 본다(PySide6 없이 돈다 — CI 와 같은 조건). 네트워크·실제 시계·자격 증명 보관소는 쓰지 않는다.

지키는 것:
  1) **읽기 전용 증명**: 초안을 만들고 선택 입력·블로그·글 유형을 바꿔 다시 만들고 검사·복사 결정을 해도(보관함 없음·0바이트·옛 구조·정상·깨진 보관함·깨진 설정 파일 모두) 임시 폴더 전체 바이트·파일 목록이 그대로이고 보관함이 만들어지지 않는다.
  2) 후보 번호(엔진 번호 전체)로 만든다 — 옛 후보 보관함의 순번과 섞이지 않고 같은 입력이면 같은 초안이며 가짜 공급자의 초안과 글자까지 같다(가짜가 진짜의 모양을 지킨다).
  3) 거절·실패는 종류별 쉬운 문장이고(자동 초안 중지·네이버가 아닌 채널·후보 없음·틀린 칸·깨진 보관함·깨진 설정) 입력한 글·경로·오류 글이 화면에 나가지 않는다. 안전 판정 중지 후보는 본문이 만들어지지 않는다.
  4) 네트워크·키 보관소를 부르지 않는다.
"""
import dataclasses
import os
import socket
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
from draft_samples import OPERATOR_C  # noqa: E402
from test_service_draft_engine import engine_candidate  # noqa: E402
from test_topicdb_store import v1_class  # noqa: E402
from test_ui_candidates_service import World  # noqa: E402

from chanceblog_desktop.ui import adapters, candidates_adapter, drafts_adapter  # noqa: E402
from chanceblog_desktop.ui.core import candidates_view as cv  # noqa: E402
from chanceblog_desktop.ui.core import draft_rules as rules  # noqa: E402
from chanceblog_desktop.ui.core import drafts, jobs, text  # noqa: E402
from chanceblog_desktop.ui.core import drafts_view as dv  # noqa: E402

T = text.T
KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731


class Bomb:
    """키 보관소 자리에 끼우는 폭탄 — 어떤 호출이든 시험이 실패한다(초안 화면은 키 보관소를 모른다)."""

    def __getattr__(self, name):
        raise AssertionError(f"키 보관소를 불렀다: {name}")


class Setup:
    def __init__(self, test, *, profiles=False, count=0):
        self.world = World(test)
        self.ctx = dataclasses.replace(self.world.ctx, keystore=Bomb())
        self.world.ctx = self.ctx
        self.provider = drafts_adapter.ServiceDraftsProvider(context_factory=lambda data_dir=None: self.ctx)
        if profiles:
            ss.naver_profiles(self.ctx)
        self.engines = [engine_candidate(number, "naver_a" if number % 2 else "naver_b") for number in range(1, count + 1)]
        if self.engines:
            self.world.add(*self.engines)

    def request(self, engine, **more):
        return drafts.DraftRequest(engine.candidate_id, more.get("blog"), more.get("post_type"), more.get("options", {}))

    def make(self, engine, **more):
        return self.provider.make_draft(self.request(engine, **more), SAFE, NEVER)

    def controller(self):
        return dv.DraftsController(self.provider, jobs.JobRunner())


def target_of(engine, *, stop=False, name="예시"):
    return drafts.DraftTarget(engine.candidate_id, engine.topic, engine.channel, name, stop, False)


def drive(controller):
    results = {}
    status, job = controller.start_make(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
    if job is not None:
        job.join(30)
    if "ok" in results:
        controller.apply_made(results["ok"])
    elif "failed" in results:
        controller.apply_make_failed(results["failed"])
    return status


def failure_of(call, *args, **kwargs):
    with unittest.TestCase().assertRaises(drafts.DraftFailure) as caught:
        call(*args, **kwargs)
    return caught.exception


class NoNetwork:
    """네트워크를 부르면 시험이 실패한다."""

    def __enter__(self):
        def boom(*args, **kwargs):
            raise AssertionError("네트워크를 불렀다")
        self.patches = [mock.patch.object(socket.socket, "connect", boom), mock.patch.object(urllib.request, "urlopen", boom)]
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self.patches:
            patch.stop()


# ---- 1) 읽기 전용 증명 ---------------------------------------------------------------------------------------------------------------
class ReadOnlyTest(unittest.TestCase):
    def use(self, setup, engine):
        """화면이 하는 일을 모두 해 본다 — 초안 만들기·선택 입력·블로그·글 유형을 바꿔 다시 만들기·고치기·검사·모든 복사 결정."""
        controller = setup.controller()
        controller.open_target(target_of(engine))
        drive(controller)
        if controller.state != "normal":
            return controller
        controller.set_body(controller.body + "\n\n직접 써 보니 정말 좋았습니다. 가격은 12,000원이었어요.")
        controller.set_title(controller.title + "!")
        controller.inspect()
        controller.view()
        for item in rules.COPY_ITEMS:
            controller.copy_decision(item)
            controller.confirm_copy(item)
            controller.discard_copy()
        for name, value in (("message", "예시 전하고 싶은 말"), ("must_include", "예시 문장 하나\n예시 문장 둘"), ("audience", "예시 독자")):
            controller.set_option(name, value)
        controller.set_blog("naver_b")
        controller.set_post_type("문제 해결형")
        controller.regen_dialog()
        drive_regenerate(controller)
        controller.view()
        controller.toggle_options()
        controller.toggle_image()
        controller.leave_dialog()
        controller.leave()
        return controller

    def test_no_engine_folder_a_zero_byte_file_an_old_structure_and_a_normal_store_change_nothing(self):
        for kind in ("none", "empty", "old", "normal"):
            with self.subTest(kind=kind):
                setup = Setup(self, profiles=kind != "none")
                engine = engine_candidate(1)
                if kind == "empty":
                    setup.world.paths.folder.mkdir(parents=True, exist_ok=True)
                    setup.world.paths.database.write_bytes(b"")
                elif kind == "old":
                    setup.world.paths.folder.mkdir(parents=True, exist_ok=True)
                    setup.world.add(engine, store_class=v1_class())
                elif kind == "normal":
                    setup.world.add(engine, *[engine_candidate(number) for number in range(2, 31)])
                else:
                    setup.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
                before, listing = setup.world.tree(), setup.world.listing()
                with NoNetwork():
                    controller = self.use(setup, engine)
                self.assertEqual((setup.world.tree(), setup.world.listing()), (before, listing), "바이트·목록이 그대로다")
                self.assertEqual(setup.world.paths.database.exists(), kind != "none", "보관함이 만들어지지 않는다")
                if kind in ("none", "empty", "old"):
                    self.assertEqual(controller.state, "notfound", "읽을 후보가 없으면 '후보를 찾지 못했어요'")
                else:
                    self.assertEqual(controller.state, "empty", "다 쓰고 화면을 떠났다")

    def test_a_broken_store_and_a_broken_profile_file_are_an_easy_error_and_nothing_is_overwritten(self):
        setup = Setup(self, count=2)
        setup.world.paths.database.write_bytes(b"this is not a database" * 20)
        before = setup.world.tree()
        failure = failure_of(setup.make, setup.engines[0])
        self.assertIn(failure.kind, ("corrupt", "io"))
        self.assertNotIn("this is not", failure.user_message)
        self.assertEqual(setup.world.tree(), before)
        broken = Setup(self, count=1)
        broken.world.paths.profiles.write_text("{ not json", encoding="utf-8")
        before = broken.world.tree()
        failure = failure_of(broken.make, broken.engines[0])
        self.assertEqual(failure.kind, "corrupt")
        self.assertEqual(failure.user_message, T["drf_fail_corrupt"])
        self.assertNotIn("not json", failure.user_message)
        self.assertEqual(broken.world.tree(), before)

    def test_a_data_folder_that_is_not_a_folder_is_an_easy_sentence(self):
        provider = drafts_adapter.ServiceDraftsProvider("C:/없는/폴더/예시", context_factory=lambda data_dir=None: None)
        failure = failure_of(provider.make_draft, drafts.DraftRequest("x", None, None, {}), SAFE, NEVER)
        self.assertEqual((failure.kind, failure.user_message), ("io", T["data_dir_missing"]))


def drive_regenerate(controller):
    controller.regen_asked = True
    results = {}
    status, job = controller.start_regenerate(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
    if job is not None:
        job.join(30)
    if "ok" in results:
        controller.apply_made(results["ok"])
    elif "failed" in results:
        controller.apply_make_failed(results["failed"])
    return status


# ---- 2) 만들기 ------------------------------------------------------------------------------------------------------------------------
class MakeTest(unittest.TestCase):
    def test_the_result_has_the_body_the_names_and_the_blog_address_from_the_profiles(self):
        setup = Setup(self, profiles=True, count=2)
        engine = setup.engines[0]
        result = setup.make(engine)
        self.assertEqual((result.candidate_id, result.blog, result.sample, result.profile_found, result.rejected), (engine.candidate_id, "naver_a", False, True, False))
        self.assertEqual(result.blog_url, "https://blog.naver.com/exampleaaa")
        self.assertEqual([key for key, _name in result.blog_names], ["naver_a", "naver_b"])
        self.assertTrue(result.body.selected_title and result.body.body_text)
        other = setup.make(engine, blog="naver_b", post_type="문제 해결형", options={"message": "예시 전하고 싶은 말 한 줄"})
        self.assertEqual((other.blog, other.post_type, other.blog_url, other.options), ("naver_b", "문제 해결형", "https://blog.naver.com/examplebbb", {"message": "예시 전하고 싶은 말 한 줄"}))
        self.assertIn("예시 전하고 싶은 말 한 줄", other.body.body_text)
        self.assertEqual(rules.naver_write_url(other.blog_url), "https://blog.naver.com/examplebbb?Redirect=Write")

    def test_without_profiles_it_still_makes_the_draft_and_the_open_button_has_no_address(self):
        setup = Setup(self, count=1)
        result = setup.make(setup.engines[0])
        self.assertEqual((result.profile_found, result.channel_found, result.blog_url), (False, False, ""))
        controller = setup.controller()
        controller.open_target(target_of(setup.engines[0]))
        drive(controller)
        self.assertEqual(controller.state, "normal")
        self.assertEqual(controller.open_info(), ("", T["drf_open_why_profile"]))
        self.assertFalse(controller.view()["normal"]["actions"]["buttons"][3]["enabled"])

    def test_the_same_input_gives_the_same_draft_and_the_fake_provider_makes_the_same_text(self):
        setup = Setup(self, count=3)
        engine = setup.engines[0]
        first, second = setup.make(engine), setup.make(engine)
        self.assertEqual(first.body.to_dict(), second.body.to_dict())
        fake = drafts.FakeDraftsProvider(lambda: setup.engines).make_draft(setup.request(engine), SAFE, NEVER)
        self.assertEqual(fake.body.to_dict(), first.body.to_dict(), "가짜 공급자가 진짜와 같은 글을 만든다")
        self.assertTrue(fake.sample and not first.sample)
        options = {"experience": "예시 경험 한 줄입니다.", "price_date": "예시 가격 3,000원\n예시 날짜 2026-11-05", "urls": "https://example.com/a"}
        real = setup.make(engine, blog="naver_b", post_type="비교형", options=options)
        fake = drafts.FakeDraftsProvider(lambda: setup.engines).make_draft(setup.request(engine, blog="naver_b", post_type="비교형", options=options), SAFE, NEVER)
        self.assertEqual(fake.body.to_dict(), real.body.to_dict())

    def test_the_old_store_ordinal_never_decides_which_candidate_is_drafted(self):
        setup = Setup(self, count=2)
        from chanceblog_desktop.service import candidates as legacy_service
        legacy_service.add_candidate(setup.ctx, topic="옛 후보 이 — 전혀 다른 주제", keyword="옛 낱말 이", blogs=("naver_a",))
        result = setup.make(setup.engines[1])
        self.assertEqual(result.body.topic, setup.engines[1].topic)
        self.assertNotIn("옛 낱말 이", result.body.plain_text)


# ---- 3) 거절·실패 ---------------------------------------------------------------------------------------------------------------------
class IndependenceTest(unittest.TestCase):
    def test_the_local_draft_works_whatever_the_repository_pause_variable_says_and_the_code_never_touches_it(self):
        """P4e 완료 조건(운영자 2026-11-09): 데스크톱은 저장소 변수 `PIPELINE_PAUSE` 를 읽지도 등록·수정·삭제하지도 않고, 그 값이 `true` 여도 로컬 초안 기능은 그대로 돈다(발행 자동화를 멈추는 변수와 이 화면은 상관없다)."""
        setup = Setup(self, profiles=True, count=2)
        engine = setup.engines[0]
        plain = setup.make(engine)
        for value in ("true", "TRUE", "1", "false"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"PIPELINE_PAUSE": value}):
                paused = setup.make(engine)
                self.assertEqual((paused.body.selected_title, paused.body.body_text, paused.blog), (plain.body.selected_title, plain.body.body_text, plain.blog), "값이 달라도 같은 입력이면 같은 초안이다")
                controller = setup.controller()
                controller.open_target(target_of(engine))
                drive(controller)
                self.assertEqual(controller.state, "normal")
        root = Path(__file__).resolve().parent.parent
        mentions = [str(path.relative_to(root)) for folder in ("src", "scripts", ".github") for path in (root / folder).rglob("*") if path.is_file() and path.suffix in (".py", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".json") and "PIPELINE_PAUSE" in path.read_text(encoding="utf-8", errors="ignore")]
        self.assertEqual(mentions, [], "저장소 변수 PIPELINE_PAUSE 를 읽거나 쓰는 코드·작업 흐름이 없다")


class SecondLineTest(unittest.TestCase):
    """독립 검증 수정 라운드 — 진짜 서비스로 만든 초안에서도 화면의 복사 관문이 같게 일한다: 정상 참고 주소는 복사되고(V2) 선택 입력에 적은 건강 효과 단정은 복사를 막는다(V1·V3)."""

    def drafted(self, setup, engine, **fields):
        controller = setup.controller()
        controller.open_target(target_of(engine))
        for name, value in fields.items():
            controller.set_option(name, value)
        drive(controller)
        return controller

    def test_normal_reference_addresses_make_a_draft_that_can_be_copied(self):
        setup = Setup(self, profiles=True, count=2)
        addresses = ["https://blog.naver.com/exampleaaa/223012345678", "https://www.coupang.com/vp/products/1234567890", "https://www.law.go.kr/lsInfoP.do?lsiSeq=123456"]
        controller = self.drafted(setup, setup.engines[0], urls="\n".join(addresses))
        self.assertEqual(controller.state, "normal")
        self.assertTrue(all(address in controller.body for address in addresses), "진짜 서비스가 받아 본문에 넣은 주소다")
        controller.set_body(controller.body + "\n\n" + "내가 직접 확인한 사실을 한 문단으로 적어요. " * 8)
        for item in rules.COPY_ITEMS:
            with self.subTest(item=item):
                kind, payload = controller.copy_decision(item)
                self.assertNotEqual(kind, "blocked", item)
                self.assertEqual(payload if kind == "copy" else controller.confirm_copy(item), controller.text_for(item))

    def test_a_health_claim_typed_into_an_option_blocks_the_copy_and_nothing_is_written(self):
        setup = Setup(self, profiles=True, count=2)
        before = setup.world.tree()
        for sentence in OPERATOR_C:
            with self.subTest(sentence=sentence[:12]):
                controller = self.drafted(setup, setup.engines[0], message=sentence)
                self.assertEqual(controller.state, "normal", "후보는 정상이라 초안은 나온다")
                self.assertEqual([controller.copy_decision(item)[0] for item in ("body", "all")], ["blocked", "blocked"])
                kind, dialog = controller.copy_decision("body")
                self.assertTrue([line for line in dialog["body"].splitlines() if line.startswith("· 본문 — ") and sentence[:10] in line])
        self.assertEqual(setup.world.tree(), before, "읽기만 했다")


class RefusalTest(unittest.TestCase):
    def test_a_stopped_candidate_a_foreign_channel_and_a_missing_one_are_refused_in_easy_sentences(self):
        setup = Setup(self)
        stopped = engine_candidate(3, topic="예시 영양제 먹으면 바로 낫는 방법", primary_keyword="예시 영양제", secondary_keywords=("예시 보조 가",), safety_flags=("health_check",))
        foreign = engine_candidate(4, "blogger_ko")
        setup.world.add(stopped, foreign, engine_candidate(5))
        failure = failure_of(setup.make, stopped)
        self.assertEqual((failure.kind, failure.user_message, failure.code), ("stopped", T["drf_refused_desc"], "CONTENT_INVALID"))
        self.assertNotIn("영양제", failure.user_message)
        failure = failure_of(setup.make, foreign)
        self.assertEqual((failure.kind, failure.user_message), ("channel", T["drf_channel_desc"]))
        failure = failure_of(setup.provider.make_draft, drafts.DraftRequest("tc-naver_a-seed-ffffffffffffffff", None, None, {}), SAFE, NEVER)
        self.assertEqual((failure.kind, failure.user_message), ("notfound", T["drf_fail_notfound"]))
        for whole in ("1", "2", "3"):
            self.assertEqual(failure_of(setup.provider.make_draft, drafts.DraftRequest(whole, None, None, {}), SAFE, NEVER).kind, "notfound", "순번으로는 찾지 않는다")

    def test_the_controller_shows_no_body_for_a_stopped_candidate_even_if_it_asks_the_service_anyway(self):
        setup = Setup(self)
        stopped = engine_candidate(3, topic="예시 영양제 먹으면 바로 낫는 방법", primary_keyword="예시 영양제", secondary_keywords=("예시 보조 가",), safety_flags=("health_check",))
        setup.world.add(stopped)
        controller = setup.controller()
        controller.open_target(target_of(stopped, stop=False))                     # 화면의 값이 거짓말을 한다 — 서비스가 거절한다
        self.assertEqual(drive(controller), "started")
        self.assertEqual((controller.state, controller.refusal, controller.result, controller.body, controller.title), ("refused", "stopped", None, "", ""))
        self.assertIsNone(controller.view()["normal"])
        controller.open_target(target_of(stopped, stop=True))
        self.assertEqual(controller.start_make(), ("refused", None))

    def test_a_wrong_option_is_the_field_and_a_fixed_reason_and_never_the_typed_text(self):
        setup = Setup(self, count=1)
        engine = setup.engines[0]
        for options, label in (({"experience": "예시 " + KEY_SHAPED}, "실제 사용 경험"), ({"urls": "http://example.com/a"}, "참고 URL"), ({"message": "예시 " + "aB3" * 10}, "직접 전달하고 싶은 내용")):
            with self.subTest(options=list(options)):
                failure = failure_of(setup.make, engine, options=options)
                self.assertEqual(failure.kind, "option")
                self.assertIn(label, failure.user_message)
                self.assertNotIn(KEY_SHAPED, failure.user_message)
                self.assertNotIn("aB3aB3", failure.user_message)
                self.assertNotIn("http://", failure.user_message)
        self.assertEqual(failure_of(setup.make, engine, options={"experience": "예시 " + KEY_SHAPED}).field, "experience")
        self.assertEqual(failure_of(setup.make, engine, post_type="없는 유형").kind, "option")

    def test_the_failure_sentences_come_from_the_kind_and_carry_no_path_or_exception_text(self):
        from chanceblog_desktop.errors import AppError
        for code, kind in (("TOPIC_STORE_CORRUPT", "corrupt"), ("TOPIC_STORE_VERSION_UNSUPPORTED", "newer"), ("TOPIC_STORE_LOCKED", "io"), ("DISK_FULL", "io"), ("TOPIC_FILE_INVALID", "corrupt"), ("CANDIDATE_INVALID", "invalid"),
                           ("TOPIC_CANDIDATE_NOT_FOUND", "notfound"), ("UNEXPECTED_ERROR", "other"), ("NOT_A_REAL_CODE", "other")):
            with self.subTest(code=code):
                failure = drafts_adapter.failure_of(AppError(code, {"항목": "C:/비밀 경로/x.db"}, detail="C:/비밀 경로/x.db") if code in ("UNEXPECTED_ERROR", "TOPIC_STORE_CORRUPT") else _raw(code))
                self.assertEqual((failure.kind, failure.code), (kind, code))
                self.assertNotIn("비밀 경로", failure.user_message)
                self.assertNotRegex(failure.user_message, r"[A-Z_]{8,}|\\|[A-Za-z]:/")


def _raw(code):
    return type("Raw", (), {"code": code, "slots": {"항목": "C:/비밀 경로/x.db"}})()


# ---- 4) 화면 연결 ----------------------------------------------------------------------------------------------------------------------
class EndToEndTest(unittest.TestCase):
    def test_the_candidates_screen_hands_over_the_whole_number_and_the_draft_screen_makes_that_candidate(self):
        setup = Setup(self, profiles=True, count=6)
        candidates_provider = candidates_adapter.ServiceCandidatesProvider(context_factory=lambda data_dir=None: setup.ctx)
        listing = cv.CandidatesController(candidates_provider, jobs.JobRunner())
        listing.apply_loaded(candidates_provider.load_candidates(SAFE, NEVER))
        wanted = setup.engines[2]
        listing.select(wanted.candidate_id)
        target = listing.draft_target()
        self.assertEqual((target.candidate_id, target.stop, target.channel), (wanted.candidate_id, False, wanted.channel))
        before = setup.world.tree()
        controller = setup.controller()
        controller.open_target(target)
        with NoNetwork():
            self.assertEqual(drive(controller), "started")
        self.assertEqual((controller.state, controller.result.candidate_id, controller.result.body.topic), ("normal", wanted.candidate_id, wanted.topic))
        self.assertEqual(setup.world.tree(), before, "초안을 만들어도 파일이 바뀌지 않는다")
        url, why = controller.open_info()
        self.assertEqual((url.startswith("https://blog.naver.com/example"), why), (True, ""))

    def test_the_paired_provider_of_the_real_home_provider_is_the_service_drafts_provider_and_reads_the_same_folder(self):
        home = adapters.ServiceHomeProvider("C:/예시/데이터")
        paired = home.drafts_provider()
        self.assertIsInstance(paired, drafts_adapter.ServiceDraftsProvider)
        self.assertEqual(paired._data_dir, "C:/예시/데이터")
        self.assertFalse(paired.sample)


if __name__ == "__main__":
    unittest.main()
