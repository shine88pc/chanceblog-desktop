"""엔진 후보로 초안을 만드는 서비스 함수(`service/draft_engine.py`) 시험 — 진짜 임시 폴더의 엔진 보관함·설정 파일·옛 후보 보관함으로 확인한다(PySide6 없이 돈다, 네트워크·실제 시계 없음).

왜 이 함수가 있나: `draft_body.make_body(ctx, ref)` 는 옛 후보 보관함에서 순번·번호 앞부분으로 후보를 찾고 주제 후보 화면의 후보는 엔진 보관함에 있다 — 화면의 번호를 `make_body` 에 넘기면 틀린 후보의 초안이 만들어질 수 있다.

지키는 것:
  1) **같은 후보를 옛 보관함에 넣어 `make_body` 로 만든 초안과 글자까지 같다**(블로그 A·B·선택 입력·글 유형을 바꿔도).
  2) 순번이 같은 옛 후보가 있어도 섞이지 않는다 — 엔진 후보는 **번호 전체가 같을 때만** 찾는다(순번·앞부분·짧은 번호·빈 글은 `TOPIC_CANDIDATE_NOT_FOUND`).
  3) 거절: 자동 초안 중지 후보·네이버가 아닌 채널·틀린 선택 입력·키 모양 입력은 본문 없이 같은 오류 코드로 거절하고 입력한 글을 오류에 되풀이하지 않는다.
  4) **읽기 전용**: 보관함 없음·0바이트·옛 구조·정상·깨진 보관함·설정 파일 깨짐 어느 상태에서도 임시 폴더 전체 바이트와 파일 목록이 그대로이고 보관함이 만들어지지 않는다.
  5) 서비스 코드에 파일을 쓰거나 네트워크를 부르는 호출이 없고 `service/draft_body.py` 는 그대로다.
"""
import ast
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
from test_topicdb_store import v1_class  # noqa: E402
from test_ui_candidates_service import World, candidate  # noqa: E402

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content import draft_body as content_body  # noqa: E402
from chanceblog_desktop.content import draft_options as do  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import candidates as legacy_service  # noqa: E402
from chanceblog_desktop.service import draft_body as body_service  # noqa: E402
from chanceblog_desktop.service import draft_engine as engine_service  # noqa: E402
from chanceblog_desktop.service import topics as topic_service  # noqa: E402
from chanceblog_desktop.topicdb import store as topic_store  # noqa: E402
from chanceblog_desktop.topics import model  # noqa: E402

SERVICE = ROOT / "src" / "chanceblog_desktop" / "service" / "draft_engine.py"
KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"


def engine_candidate(number=1, channel="naver_a", **more):
    values = dict(topic=f"예시 후보 {number} — 순서대로 따라 하는 안내", primary_keyword=f"예시 낱말 {number}", secondary_keywords=("예시 보조 가", "예시 보조 나"))
    values.update(more)
    return candidate(number, 88, channel, **values)


def legacy_twin(ctx, engine):
    """엔진 후보와 같은 글을 가진 후보를 **옛 보관함**에 넣는다 — `make_body` 의 입력."""
    return legacy_service.add_candidate(ctx, topic=engine.topic, keyword=engine.primary_keyword, blogs=(engine.channel,), sub_keywords=tuple(engine.secondary_keywords), post_type=model.to_post_type(engine.content_type))


def code_of(call, *args, **kwargs):
    with unittest.TestCase().assertRaises(AppError) as caught:
        call(*args, **kwargs)
    return caught.exception


class EquivalenceTest(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        ss.naver_profiles(self.world.ctx)

    def both(self, engine, **asked):
        self.world.add(engine)
        legacy_twin(self.world.ctx, engine)
        mine = engine_service.make_body_for_engine(self.world.ctx, engine.candidate_id, **asked)
        old = body_service.make_body(self.world.ctx, "1", **asked)
        return mine, old

    def test_the_draft_is_the_same_as_the_one_made_from_the_old_store_for_both_naver_blogs(self):
        for number, channel in ((1, "naver_a"), (2, "naver_b")):
            with self.subTest(channel=channel):
                world = World(self)
                ss.naver_profiles(world.ctx)
                engine = engine_candidate(number, channel)
                world.add(engine)
                legacy_twin(world.ctx, engine)
                mine = engine_service.make_body_for_engine(world.ctx, engine.candidate_id)
                old = body_service.make_body(world.ctx, "1")
                self.assertEqual(mine.body.to_dict(), old.body.to_dict())
                self.assertEqual((mine.blog, mine.post_type, mine.profile_found), (channel, old.body.post_type, True))
                self.assertEqual(mine.body.plain_text, old.body.plain_text)

    def test_options_the_other_blog_and_the_post_type_change_the_draft_in_the_same_way_as_the_old_path(self):
        engine = engine_candidate(1)
        options = do.DraftOptions(message="예시 전하고 싶은 말 한 줄", audience="예시 독자 한 명", must_include=("예시 반드시 넣을 문장입니다.",), price_date=("예시 가격 3,000원",))
        mine, old = self.both(engine, blog="naver_b", post_type="문제 해결형", options=options)
        self.assertEqual(mine.body.to_dict(), old.body.to_dict())
        self.assertEqual((mine.blog, mine.post_type), ("naver_b", "문제 해결형"))
        self.assertIn("예시 반드시 넣을 문장입니다.", mine.body.body_text)
        self.assertEqual(mine.options, options)

    def test_the_same_input_gives_the_same_draft(self):
        engine = engine_candidate(1)
        self.world.add(engine)
        first = engine_service.make_body_for_engine(self.world.ctx, engine.candidate_id)
        second = engine_service.make_body_for_engine(self.world.ctx, engine.candidate_id)
        self.assertEqual(first.body.to_dict(), second.body.to_dict())
        self.assertEqual((first.body.chars >= 1800, len(first.body.titles)), (True, 3))

    def test_the_engines_safety_report_reaches_the_generator_for_a_health_and_a_sponsor_word_candidate(self):
        """독립 검증 V4(변이 N03): `make_body_for_engine` 이 안전 판정 결과를 생성기에 넘기지 않으면(`safety=None`) 건강 근거 확인·협찬 낱말 경고가 확인 권장에서 조용히 사라진다 — 옛 길(`make_body`)과 글자까지 같은지 견주고 그 줄이 실제로 있는지도 본다."""
        for number, (topic, keyword, phrase) in enumerate((("영양제를 식후 바로 먹어도 될까", "영양제", "건강 효과를 근거 없이 말하기 쉬운 주제"), ("협찬 받은 청소기 비교", "청소기", "협찬·광고를 뜻하는 말")), start=1):
            with self.subTest(topic=topic):
                world = World(self)
                ss.naver_profiles(world.ctx)
                engine = engine_candidate(number, topic=topic, primary_keyword=keyword, secondary_keywords=("예시 보조 가",))
                world.add(engine)
                legacy_twin(world.ctx, engine)
                mine = engine_service.make_body_for_engine(world.ctx, engine.candidate_id)
                old = body_service.make_body(world.ctx, "1")
                self.assertEqual(mine.body.to_dict(), old.body.to_dict())
                self.assertTrue([line for line in mine.body.checks if phrase in line], phrase)

    def test_the_legacy_candidate_carries_only_the_fields_the_link_table_says_and_is_never_stored(self):
        engine = engine_candidate(1, content_type="troubleshooting")
        legacy = engine_service.legacy_of(engine)
        self.assertEqual((legacy.topic, legacy.keyword, legacy.sub_keywords, legacy.blogs, legacy.post_type, legacy.candidate_id), (engine.topic, engine.primary_keyword, tuple(engine.secondary_keywords), (engine.channel,), model.to_post_type("troubleshooting"), engine.candidate_id))
        self.assertEqual((legacy.reason, legacy.search_demand, legacy.trend, legacy.project_id), ("", None, None, None), "값을 만들어 넣지 않는다")
        world = World(self)
        world.add(engine)
        before = world.tree()
        engine_service.make_body_for_engine(world.ctx, engine.candidate_id)
        self.assertEqual(world.tree(), before)
        self.assertEqual(legacy_service.list_candidates(world.ctx).total, 0, "옛 후보 보관함에도 아무것도 생기지 않는다")


class NoMixUpTest(unittest.TestCase):
    def test_an_old_candidate_with_the_same_ordinal_is_never_used(self):
        world = World(self)
        engine = engine_candidate(1)
        world.add(engine)
        legacy_service.add_candidate(world.ctx, topic="옛 후보 이 — 전혀 다른 주제", keyword="옛 낱말 이", blogs=("naver_a",))
        self.assertEqual(body_service.make_body(world.ctx, "1").body.topic, "옛 후보 이 — 전혀 다른 주제", "(`make_body` 의 순번은 옛 보관함의 순번이다 — 이 시험이 막으려는 오인)")
        result = engine_service.make_body_for_engine(world.ctx, engine.candidate_id)
        self.assertEqual((result.body.topic, result.candidate_id), (engine.topic, engine.candidate_id))
        self.assertNotIn("옛 낱말 이", result.body.plain_text)

    def test_only_the_whole_number_finds_a_candidate(self):
        world = World(self)
        engine = engine_candidate(1)
        world.add(engine, engine_candidate(2))
        number = engine.candidate_id
        for wrong in ("1", "2", "001", number[:8], number[:20], number.upper(), number + "x", " " + number, "", None, 1, ["x"], "후보"):
            with self.subTest(wrong=wrong):
                error = code_of(engine_service.make_body_for_engine, world.ctx, wrong)
                self.assertEqual(error.code, "TOPIC_CANDIDATE_NOT_FOUND")
                self.assertNotIn("후보", str(error.slots.get("항목", "")).replace("(비어 있음)", ""))
        self.assertEqual(engine_service.make_body_for_engine(world.ctx, number).candidate_id, number)


class RefusalTest(unittest.TestCase):
    def setUp(self):
        self.world = World(self)

    def test_a_candidate_the_safety_check_stopped_never_gets_a_body(self):
        engine = engine_candidate(3, topic="예시 영양제 먹으면 바로 낫는 방법", primary_keyword="예시 영양제", secondary_keywords=("예시 보조 가",), safety_flags=("health_check",))
        self.world.add(engine)
        listed = topic_service.list_candidates(self.world.ctx)
        self.assertTrue(listed.rows[0].stop, "엔진도 자동 초안 중지로 본다")
        error = code_of(engine_service.make_body_for_engine, self.world.ctx, engine.candidate_id)
        self.assertEqual((error.code, error.slots["항목"]), ("CONTENT_INVALID", content_body.STOP_ITEM))
        self.assertNotIn("영양제", error.rendered().message + error.detail, "후보의 글을 오류에 되풀이하지 않는다")

    def test_a_channel_that_is_not_naver_is_refused_with_the_same_code_as_the_cli(self):
        engine = engine_candidate(4, "blogger_ko")
        self.world.add(engine)
        error = code_of(engine_service.make_body_for_engine, self.world.ctx, engine.candidate_id)
        self.assertEqual((error.code, error.slots["항목"]), ("DRAFT_OPTION_INVALID", "블로그"))
        self.assertEqual(engine_service.make_body_for_engine(self.world.ctx, engine.candidate_id, blog="naver_a").blog, "naver_a", "블로그를 직접 정하면 만든다(후보가 그 블로그용은 아니다)")

    def test_every_health_c_example_stops_the_draft_and_a_health_a_topic_still_gets_a_checked_draft(self):
        """P4e 완료 조건 ⑫: 건강 판정이 C(의료·효과 단정 위험 — 증상+즉각 효과·질환+단정·건강 제품+즉시 효과)이면 초안을 자동으로 만들지 않는다. 서로 다른 세 모양의 C 와, 같은 건강 주제라도 A(표시만)이면 초안이 나오는 것을 함께 본다."""
        c_topics = (("예시 두통 즉시 사라지는 방법", "예시 두통"), ("예시 당뇨 반드시 낫는 식단", "예시 당뇨"), ("예시 영양제 먹으면 바로 낫는 방법", "예시 영양제"))
        engines = [engine_candidate(20 + number, topic=topic, primary_keyword=keyword, secondary_keywords=("예시 보조 가",)) for number, (topic, keyword) in enumerate(c_topics)]
        mild = engine_candidate(30, topic="예시 영양제 고르는 기준", primary_keyword="예시 영양제", secondary_keywords=("예시 보조 가",))
        self.world.add(*engines, mild)
        rows = {row.candidate.candidate_id: row for row in topic_service.list_candidates(self.world.ctx).rows}
        for engine in engines:
            with self.subTest(topic=engine.topic):
                self.assertEqual((rows[engine.candidate_id].stop, rows[engine.candidate_id].candidate.work_status), (True, engine.work_status), "엔진도 자동 초안 중지로 본다(건강 C)")
                error = code_of(engine_service.make_body_for_engine, self.world.ctx, engine.candidate_id)
                self.assertEqual((error.code, error.slots["항목"]), ("CONTENT_INVALID", content_body.STOP_ITEM))
        self.assertFalse(rows[mild.candidate_id].stop, "건강 A(표시만)는 중지가 아니다")
        made = engine_service.make_body_for_engine(self.world.ctx, mild.candidate_id)
        self.assertTrue(made.body.selected_title and made.body.body_text)
        self.assertTrue(made.body.sensitive or any("건강" in line or "민감" in line for line in made.body.checks), "건강 주제 초안에는 확인 권장이 따라 붙는다")

    def test_wrong_options_are_refused_with_the_field_and_a_reason_but_never_the_text(self):
        engine = engine_candidate(5)
        self.world.add(engine)
        for kwargs, field in (({"blog": "github_pages"}, "블로그"), ({"blog": "naver_c"}, "블로그"), ({"post_type": "없는 유형"}, "글 유형")):
            with self.subTest(kwargs=kwargs):
                error = code_of(engine_service.make_body_for_engine, self.world.ctx, engine.candidate_id, **kwargs)
                self.assertEqual((error.code, error.slots["항목"]), ("DRAFT_OPTION_INVALID", field))
        with self.assertRaises(AppError) as caught:
            do.DraftOptions(experience="예시 " + KEY_SHAPED)
        self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")
        self.assertNotIn(KEY_SHAPED, caught.exception.rendered().message + caught.exception.detail)
        long_run = "예시 " + "aB3" * 10
        options = do.DraftOptions(message=long_run)
        error = code_of(engine_service.make_body_for_engine, self.world.ctx, engine.candidate_id, options=options)
        self.assertEqual(error.code, "DRAFT_OPTION_INVALID")
        self.assertNotIn("aB3aB3", error.rendered().message + error.detail)

    def test_if_the_old_candidate_rules_ever_refuse_a_candidate_the_draft_is_refused_and_nothing_changes(self):
        from unittest import mock
        engine = engine_candidate(6, primary_keyword="예시 낱말 육")
        self.world.add(engine)
        before = self.world.tree()
        with mock.patch.object(cd.Candidate, "new", side_effect=AppError("CANDIDATE_INVALID", {"항목": "주제", "이유": "예시"})):
            error = code_of(engine_service.make_body_for_engine, self.world.ctx, engine.candidate_id)
        self.assertEqual(error.code, "CANDIDATE_INVALID")
        self.assertEqual(self.world.tree(), before)


class StopBothWaysTest(unittest.TestCase):
    """안전 판정 중지는 두 길이 **따로** 본다 — 엔진이 계산한 `stop`(행의 `stop`)과 초안 서비스의 `screen`. 둘은 보통 같은 후보를 가리켜 한쪽이 빠져도 위의 시험은 못 알아챈다 — 그래서 한쪽만 중지인 입력을
    따로 만들어 어느 한쪽만으로도 본문이 만들어지지 않음을 못박는다(변이 점검 E01·E02 가 처음 한 바퀴에서 살아남아 더한 시험)."""

    def row(self, stop):
        return types.SimpleNamespace(stop=stop)

    def test_the_engine_stop_alone_refuses_a_harmless_text(self):
        legacy = engine_service.legacy_of(engine_candidate(7))
        error = code_of(engine_service._refuse_stop, self.row(True), legacy)
        self.assertEqual((error.code, error.slots["항목"]), ("CONTENT_INVALID", content_body.STOP_ITEM))
        self.assertNotIn("예시 후보", error.rendered().message + error.detail, "후보의 글을 오류에 되풀이하지 않는다")

    def test_the_draft_screen_alone_refuses_a_stopping_text(self):
        legacy = engine_service.legacy_of(engine_candidate(8, topic="예시 영양제 먹으면 바로 낫는 방법", primary_keyword="예시 영양제", secondary_keywords=("예시 보조 가",)))
        error = code_of(engine_service._refuse_stop, self.row(False), legacy)
        self.assertEqual((error.code, error.slots["항목"]), ("CONTENT_INVALID", content_body.STOP_ITEM))
        self.assertNotIn("영양제", error.rendered().message + error.detail, "후보의 글을 오류에 되풀이하지 않는다")

    def test_neither_refuses_a_harmless_candidate_and_the_report_comes_back(self):
        legacy = engine_service.legacy_of(engine_candidate(9))
        report = engine_service._refuse_stop(self.row(False), legacy)
        self.assertFalse(report.stop)


class ReadOnlyTest(unittest.TestCase):
    def check_untouched(self, world, candidate_id="x" * 8):
        before, listing = world.tree(), world.listing()
        error = code_of(engine_service.make_body_for_engine, world.ctx, candidate_id)
        self.assertIn(error.code, ("TOPIC_CANDIDATE_NOT_FOUND", "TOPIC_STORE_CORRUPT", "TOPIC_STORE_VERSION_UNSUPPORTED", "TOPIC_STORE_RECOVERY_PENDING", "TOPIC_FILE_INVALID"))
        self.assertEqual((world.tree(), world.listing()), (before, listing))
        self.assertFalse(world.paths.database.exists() and not before, "보관함이 만들어지지 않는다")
        return error

    def test_no_engine_store_at_all_creates_nothing(self):
        world = World(self)
        world.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
        self.check_untouched(world)
        self.assertFalse(world.paths.folder.exists(), "엔진 보관함 폴더도 만들지 않는다")

    def test_an_empty_file_an_old_structure_and_a_normal_store_are_read_without_a_change(self):
        for kind in ("empty", "old", "normal"):
            with self.subTest(kind=kind):
                world = World(self)
                ss.naver_profiles(world.ctx)
                engine = engine_candidate(1)
                if kind == "empty":
                    world.paths.folder.mkdir(parents=True, exist_ok=True)
                    world.paths.database.write_bytes(b"")
                elif kind == "old":
                    world.paths.folder.mkdir(parents=True, exist_ok=True)
                    world.add(engine, store_class=v1_class())
                else:
                    world.add(engine)
                before, listing = world.tree(), world.listing()
                if kind == "normal":
                    result = engine_service.make_body_for_engine(world.ctx, engine.candidate_id)
                    self.assertEqual(result.candidate_id, engine.candidate_id)
                    legacy_service.list_candidates(world.ctx)
                else:
                    self.assertEqual(code_of(engine_service.make_body_for_engine, world.ctx, engine.candidate_id).code, "TOPIC_CANDIDATE_NOT_FOUND")
                self.assertEqual((world.tree(), world.listing()), (before, listing))

    def test_a_broken_store_and_a_broken_profile_file_stop_with_an_error_and_change_nothing(self):
        world = World(self)
        engine = engine_candidate(1)
        world.add(engine)
        world.paths.database.write_bytes(b"this is not a database" * 20)
        error = self.check_untouched(world, engine.candidate_id)
        self.assertNotIn("this is not", error.rendered().message + error.detail)
        world2 = World(self)
        engine2 = engine_candidate(1)
        world2.add(engine2)
        world2.paths.profiles.write_text("{ not json", encoding="utf-8")
        before = world2.tree()
        self.assertEqual(code_of(engine_service.make_body_for_engine, world2.ctx, engine2.candidate_id).code in ("TOPIC_FILE_INVALID", "CONTENT_INVALID"), True)
        self.assertEqual(world2.tree(), before)

    def test_reading_the_profile_gives_the_blog_address_and_names_and_a_missing_profile_gives_none(self):
        world = World(self)
        engine = engine_candidate(1)
        world.add(engine)
        none = engine_service.make_body_for_engine(world.ctx, engine.candidate_id)
        self.assertEqual((none.profile_found, none.blog_url, none.channel_found), (False, "", False))
        self.assertEqual([key for key, _name in none.blog_names], ["naver_a", "naver_b"])
        ss.naver_profiles(world.ctx)
        found = engine_service.make_body_for_engine(world.ctx, engine.candidate_id)
        self.assertEqual((found.profile_found, found.blog_url), (True, "https://blog.naver.com/exampleaaa"))
        other = engine_service.make_body_for_engine(world.ctx, engine.candidate_id, blog="naver_b")
        self.assertEqual(other.blog_url, "https://blog.naver.com/examplebbb")

    def test_a_rejected_candidate_gets_a_draft_and_the_flag_and_keeps_its_state(self):
        world = World(self)
        engine = engine_candidate(1, work_status="REJECTED")
        world.add(engine)
        before = world.tree()
        result = engine_service.make_body_for_engine(world.ctx, engine.candidate_id)
        self.assertTrue(result.rejected)
        self.assertEqual(world.tree(), before)
        with topic_store.open_read_only(world.paths.database) as store:
            self.assertEqual(store.list_candidates()[0].work_status, "REJECTED")


class SourceRulesTest(unittest.TestCase):
    def test_the_service_file_has_no_write_or_network_call_and_no_english_secret_words(self):
        source = SERVICE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        for forbidden in ("open", "write_text", "write_bytes", "write_json", "unlink", "mkdir", "sqlite3.connect", "os.replace", "shutil.copy", "urlopen", "socket.socket", "open_for_write", "generate_candidates", "init_topics"):
            self.assertFalse([call for call in calls if call == forbidden or call.endswith("." + forbidden)], forbidden)
        words = re.compile(r"(?i)(?<![A-Za-z0-9_])(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?(?![A-Za-z0-9_])")
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertIsNone(words.search(node.value), node.value[:40])
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse({module for module in imported if module and module.split(".")[0] in ("ui", "publish", "render", "assist", "jobs")})

    def test_no_ai_client_or_prompt_assembly_exists_in_the_code_so_nothing_can_pass_forbidden_material_to_an_ai(self):
        """P4e 완료 조건 ⑪·'AI 입력 허용·금지' 점검(운영자 2026-11-09): 이 저장소 코드에는 **AI 호출도 프롬프트를 짜는 곳도 아직 없다**(AI 미연결 — 규칙 기반 초안만). 그래서 AI 에 넘길 수 있는 값이 하나도 없고(허용 목록 밖의 외부 웹페이지 본문·기사·원자료 응답·
        라이선스 불명 자료·제3자 이미지·개인정보가 넘어갈 길이 없다) 허용·금지 목록과 자동 보류 규칙은 AI 연결 묶음이 프롬프트 조립부와 함께 지켜야 한다. 이 시험은 AI SDK 를 가져오는 곳과 프롬프트를 짜는 함수가 **생기면 실패해서** 그 묶음이 이 점검을 다시 하게 만든다."""
        sdk_roots = {"openai", "anthropic", "litellm", "langchain", "langchain_core", "cohere", "mistralai", "ollama", "google.generativeai", "google.genai", "vertexai", "transformers"}
        assemblers = re.compile(r"(?i)^(?:build|assemble|make|compose|render|create)_?(?:system_|user_|llm_|ai_)?prompt|^(?:system|user)_prompt$|^prompt_(?:for|builder|template)")
        found_imports, found_functions = [], []
        for path in sorted((ROOT / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
                for module in modules:
                    if module in sdk_roots or module.split(".")[0] in sdk_roots or any(module.startswith(root + ".") for root in sdk_roots):
                        found_imports.append((path.name, module))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and assemblers.search(node.name):
                    found_functions.append((path.name, node.name))
        self.assertEqual(found_imports, [], "AI SDK 를 가져오는 곳이 생겼다 — 입력 허용·금지 목록을 지키는지 점검하고 이 시험·결정 기록을 함께 고친다")
        self.assertEqual(found_functions, [], "프롬프트를 짜는 함수가 생겼다 — 입력 허용·금지 목록·자동 보류 규칙을 지키는지 점검하고 이 시험·결정 기록을 함께 고친다")
        draft_files = [ROOT / "src" / "chanceblog_desktop" / name for name in ("service/draft_engine.py", "ui/drafts_adapter.py", "ui/core/drafts.py", "ui/core/drafts_view.py", "ui/core/draft_rules.py")]
        for path in draft_files:
            imported = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imported |= {alias.name for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    imported.add(node.module)
            wrong = {name for name in imported if name.split(".")[0] in {"socket", "http", "requests", "httpx", "aiohttp", "subprocess", "urllib3"} or name.startswith(("urllib.request", "urllib.error"))}     # `urllib.parse`(주소 글자 가르기)는 네트워크가 아니다
            self.assertEqual(wrong, set(), f"{path.name}: 초안 경로는 네트워크도 외부 프로그램도 부르지 않는다")

    def test_the_cli_draft_body_service_is_the_one_from_main_and_the_new_function_does_not_replace_it(self):
        self.assertTrue(hasattr(body_service, "make_body") and callable(body_service.make_body))
        self.assertNotEqual(engine_service.make_body_for_engine, body_service.make_body)
        source = (ROOT / "src" / "chanceblog_desktop" / "service" / "draft_body.py").read_text(encoding="utf-8")
        self.assertNotIn("draft_engine", source, "`draft_body.py` 는 새 함수를 모른다 — 한 글자도 바뀌지 않았다")


if __name__ == "__main__":
    unittest.main()
