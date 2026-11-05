"""연결(`CandidateLink`)·출처 스냅샷(`Provenance`)·사용자 데이터 파일 이름(`layout`) 시험.

지키는 것:
  1) 연결은 엔진 후보 번호·기존 후보 번호·초안 계획 번호·원천 주제 번호·씨앗 번호·채널 여섯 칸이고, 후보에 있는 값은 그대로 옮기며 나머지는 나중에 붙는다. JSON 은 엄격하다.
  2) 출처 스냅샷은 새 점수(여섯 항목·최종·구간)·선정 이유·관심도 상태와 기준·자료 상태·씨앗 출처를 하나도 빠뜨리지 않고 담는다 — 후보의 모든 값은 '담는다' 아니면 '담지 않는다(까닭)' 둘 중 하나다.
  3) 한 칸이라도 바뀌면 스냅샷도 달라진다(빠뜨린 칸이 있으면 이 시험이 잡는다). 구간이 점수와 어긋난 스냅샷은 거절한다.
  4) 사용자 데이터 파일 이름은 정확히 네 개이고 기존 보관함·설정 파일 이름과 겹치지 않으며 키·자격 증명을 뜻하는 이름이 없다.
네트워크·파일·실제 시계·난수 없이 돈다.
"""
import dataclasses
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import connections as old_connections  # noqa: E402
from chanceblog_desktop.service import context as old_context  # noqa: E402
from chanceblog_desktop.service import quota as old_quota  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402
from chanceblog_desktop.topics import link  # noqa: E402
from chanceblog_desktop.topics import model  # noqa: E402

LINK_FIELDS = ("engine_candidate_id", "legacy_candidate_id", "draft_plan_id", "source_topic_id", "seed_id", "channel")
CARRIED = ("scores", "recommendation_band", "selection_reasons", "trend_status", "trend_ratio", "trend_period", "trend_compared_group", "trend_queried_on", "data_status", "seed_id",
           "source_type", "source_topic_id", "channel")


def plain_link(**changes):
    values = {"engine_candidate_id": "e1", "legacy_candidate_id": None, "draft_plan_id": None, "source_topic_id": None, "seed_id": None, "channel": "naver_b"}
    values.update(changes)
    return link.CandidateLink(**values)


class CandidateLinkTest(unittest.TestCase):
    def test_the_link_has_exactly_these_six_fields(self):
        self.assertEqual(tuple(f.name for f in dataclasses.fields(link.CandidateLink)), LINK_FIELDS)

    def test_a_link_made_from_a_candidate_carries_what_the_candidate_has(self):
        c = ts.full()
        made = link.CandidateLink.of(c)
        self.assertEqual((made.engine_candidate_id, made.source_topic_id, made.seed_id, made.channel), (c.candidate_id, "src-local-ai", "seed-gpu", "naver_b"))
        self.assertEqual((made.legacy_candidate_id, made.draft_plan_id), (None, None))

    def test_the_legacy_and_draft_numbers_are_added_later(self):
        made = link.CandidateLink.of(ts.make(), legacy_candidate_id="0123456789abcdef0123456789abcdef", draft_plan_id="p" * 64)
        self.assertEqual((made.legacy_candidate_id, made.draft_plan_id), ("0123456789abcdef0123456789abcdef", "p" * 64))
        later = dataclasses.replace(link.CandidateLink.of(ts.make()), legacy_candidate_id="L1")
        self.assertEqual(later.legacy_candidate_id, "L1")
        self.assertEqual(later.engine_candidate_id, "cand0001")

    def test_a_candidate_without_a_seed_or_a_source_topic_gives_none(self):
        made = link.CandidateLink.of(ts.make())
        self.assertEqual((made.source_topic_id, made.seed_id), (None, None))

    def test_the_numbers_have_the_same_shape_as_the_candidate_number(self):
        for name in ("engine_candidate_id", "legacy_candidate_id", "draft_plan_id", "source_topic_id", "seed_id"):
            for good in ("a", "A-b_9", "x" * 64):
                self.assertEqual(getattr(plain_link(**{name: good}), name), good)
            for bad in ("", "x" * 65, "a b", "a.b", "한글", 3):
                with self.subTest(field=name, value=bad):
                    with self.assertRaises(AppError):
                        plain_link(**{name: bad})

    def test_only_the_engine_candidate_number_is_required(self):
        with self.assertRaises(AppError):
            plain_link(engine_candidate_id=None)
        for name in ("legacy_candidate_id", "draft_plan_id", "source_topic_id", "seed_id"):
            self.assertIsNone(getattr(plain_link(**{name: None}), name))

    def test_the_channel_is_a_code_key_and_an_alias_is_refused(self):
        for key in ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"):
            self.assertEqual(plain_link(channel=key).channel, key)
        for bad in ("blogger_a", "blogger_b", "tistory", None, ""):
            with self.assertRaises(AppError):
                plain_link(channel=bad)

    def test_the_fields_can_only_be_given_by_name_and_all_of_them(self):
        with self.assertRaises(TypeError):
            link.CandidateLink("e1", None, None, None, None, "naver_b")
        with self.assertRaises(TypeError):
            link.CandidateLink(engine_candidate_id="e1", channel="naver_b")

    def test_the_link_is_a_frozen_value(self):
        made = plain_link()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            made.channel = "naver_a"
        self.assertEqual(plain_link(), plain_link())
        self.assertEqual(hash(plain_link()), hash(plain_link()))

    def test_a_link_can_only_be_made_from_an_engine_candidate(self):
        for bad in (None, {"candidate_id": "x"}, ts.make().scores):
            with self.assertRaises(TypeError):
                link.CandidateLink.of(bad)

    def test_the_link_round_trips_through_json_text(self):
        for made in (plain_link(), link.CandidateLink.of(ts.full(), legacy_candidate_id="L1", draft_plan_id="plan-1")):
            data = made.to_dict()
            self.assertEqual(tuple(data), ("schema", *LINK_FIELDS))
            self.assertEqual(data["schema"], 1)
            self.assertEqual(link.CandidateLink.from_dict(json.loads(json.dumps(data))), made)

    def test_the_link_is_read_strictly(self):
        good = plain_link().to_dict()
        for schema in (0, 2, "1", True, None):
            with self.assertRaises(AppError):
                link.CandidateLink.from_dict({**good, "schema": schema})
        for name in LINK_FIELDS:
            data = dict(good)
            del data[name]
            with self.subTest(missing=name):
                with self.assertRaises(AppError):
                    link.CandidateLink.from_dict(data)
        for extra in ("status", "legacy_id", "anything"):
            with self.assertRaises(AppError):
                link.CandidateLink.from_dict({**good, extra: 1})
        for bad in (None, [], "x"):
            with self.assertRaises(AppError):
                link.CandidateLink.from_dict(bad)
        schema_less = dict(good)
        del schema_less["schema"]
        with self.assertRaises(AppError):
            link.CandidateLink.from_dict(schema_less)


def changed_candidate(name):
    """`ts.full()` 에서 스냅샷에 담기는 칸 하나만 다른 올바른 값으로 바꾼 후보."""
    other = {
        "scores": ts.flat_card(70), "selection_reasons": ("다른 이유",), "trend_status": "flat", "trend_ratio": 10, "trend_period": "최근 6개월", "trend_compared_group": ("로컬 AI",),
        "trend_queried_on": "2026-11-03", "data_status": "partial", "seed_id": "seed-other", "source_type": "sponsor", "source_topic_id": "src-other", "channel": "naver_a",
    }
    return dataclasses.replace(ts.full(), **{name: other[name]})


class ProvenanceTest(unittest.TestCase):
    def test_the_snapshot_holds_the_documented_values_of_the_candidate(self):
        c = ts.full()
        snapshot = link.Provenance.of(c)
        self.assertEqual(tuple(f.name for f in dataclasses.fields(link.Provenance)), CARRIED)
        for name in CARRIED:
            with self.subTest(field=name):
                self.assertEqual(getattr(snapshot, name), getattr(c, name))
        self.assertEqual(snapshot.recommendation_band, "RECOMMENDED")
        self.assertEqual(snapshot.scores.final, 85)

    def test_every_value_of_the_candidate_is_either_carried_or_explained_as_not_carried(self):
        attributes = {f.name for f in dataclasses.fields(model.TopicCandidate)} | {"recommendation_band"}
        carried = {f.name for f in dataclasses.fields(link.Provenance)}
        not_carried = set(link.NOT_CARRIED)
        self.assertEqual(carried & not_carried, set(), "한 값이 양쪽에 있으면 안 된다")
        self.assertEqual(carried | not_carried, attributes, "후보의 새 칸은 스냅샷에 담을지 말지 정해야 한다")
        for name, reason in link.NOT_CARRIED.items():
            self.assertTrue(isinstance(reason, str) and len(reason) > 5, name)

    def test_the_values_the_operator_named_are_all_carried(self):
        for name in ("scores", "recommendation_band", "selection_reasons", "trend_status", "trend_ratio", "trend_period", "trend_compared_group", "trend_queried_on", "data_status",
                     "seed_id", "source_type", "source_topic_id", "channel"):
            self.assertIn(name, {f.name for f in dataclasses.fields(link.Provenance)})
        for name in ("work_status", "search_demand_count", "search_demand_source", "candidate_id"):
            self.assertIn(name, link.NOT_CARRIED)

    def test_every_carried_value_shows_up_in_the_stored_form(self):
        c = ts.full()
        data = link.Provenance.of(c).to_dict()
        for name in CARRIED:
            expected = c.recommendation_band if name == "recommendation_band" else getattr(c, name)
            expected = expected.to_dict() if name == "scores" else list(expected) if isinstance(expected, tuple) else expected
            with self.subTest(field=name):
                self.assertEqual(data[name], expected)

    def test_changing_any_one_carried_value_of_the_candidate_changes_the_snapshot(self):
        base = link.Provenance.of(ts.full())
        for name in CARRIED:
            if name == "recommendation_band":
                continue                                          # 점수에서 계산하는 값 — 점수를 바꾸는 항목에서 함께 본다
            with self.subTest(field=name):
                changed = link.Provenance.of(changed_candidate(name))
                self.assertNotEqual(changed, base)
                self.assertNotEqual(getattr(changed, name), getattr(base, name))

    def test_a_changed_score_changes_the_band_in_the_snapshot_too(self):
        self.assertEqual(link.Provenance.of(changed_candidate("scores")).recommendation_band, "GENERAL")

    def test_the_snapshot_is_the_same_for_the_same_candidate_and_frozen(self):
        self.assertEqual(link.Provenance.of(ts.full()), link.Provenance.of(ts.full()))
        snapshot = link.Provenance.of(ts.full())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.channel = "naver_a"
        self.assertEqual(hash(snapshot), hash(link.Provenance.of(ts.full())))

    def test_a_candidate_without_scores_gives_an_unrated_snapshot(self):
        snapshot = link.Provenance.of(ts.make())
        self.assertEqual(snapshot.recommendation_band, "UNRATED")
        self.assertIsNone(snapshot.scores.final)
        self.assertEqual(link.Provenance.from_dict(snapshot.to_dict()), snapshot)

    def test_the_snapshot_keeps_the_trend_and_leaves_the_real_count_out(self):
        snapshot = link.Provenance.of(ts.full())
        self.assertEqual((snapshot.trend_status, snapshot.trend_ratio, snapshot.trend_compared_group), ("rising", 73, ("로컬 AI", "클라우드 AI")))
        for name in snapshot.to_dict():
            self.assertNotIn("demand", name)
            self.assertNotIn("volume", name)

    def test_the_snapshot_round_trips_through_json_text(self):
        for c in (ts.full(), ts.make(), ts.rated(70, source_topic_id="s1")):
            snapshot = link.Provenance.of(c)
            data = snapshot.to_dict()
            self.assertEqual(tuple(data), ("schema", *CARRIED))
            self.assertEqual(link.Provenance.from_dict(json.loads(json.dumps(data, ensure_ascii=False))), snapshot)

    def test_the_snapshot_is_read_strictly(self):
        good = link.Provenance.of(ts.full()).to_dict()
        for schema in (0, 2, "1", True, None):
            with self.assertRaises(AppError):
                link.Provenance.from_dict({**good, "schema": schema})
        for name in CARRIED:
            data = dict(good)
            del data[name]
            with self.subTest(missing=name):
                with self.assertRaises(AppError):
                    link.Provenance.from_dict(data)
        for extra in ("work_status", "search_demand_count", "topic", "anything"):
            with self.subTest(extra=extra):
                with self.assertRaises(AppError):
                    link.Provenance.from_dict({**good, extra: 1})
        for bad in (None, [], "x"):
            with self.assertRaises(AppError):
                link.Provenance.from_dict(bad)

    def test_a_band_that_does_not_match_the_final_score_is_refused(self):
        good = link.Provenance.of(ts.full()).to_dict()
        for band in ("GENERAL", "HOLD", "EXCLUDED", "UNRATED"):
            with self.subTest(band=band):
                with self.assertRaises(AppError):
                    link.Provenance.from_dict({**good, "recommendation_band": band})
        for band in ("recommended", "", None, 1, "WINNER"):
            with self.assertRaises(AppError):
                link.Provenance.from_dict({**good, "recommendation_band": band})

    def test_the_snapshot_checks_its_values_like_the_candidate_does(self):
        good = link.Provenance.of(ts.full()).to_dict()
        for name, bad in (("selection_reasons", ["수익 보장"]), ("selection_reasons", ["이유"] * 11), ("trend_status", "unavailable"), ("trend_ratio", True), ("trend_ratio", 101),
                          ("trend_period", None), ("trend_queried_on", None), ("trend_queried_on", "어제"), ("data_status", "unknown"), ("source_type", "manual"), ("seed_id", "a b"),
                          ("source_topic_id", ""), ("channel", "blogger_a"), ("scores", None), ("scores", {"final": 85}), ("trend_compared_group", [])):
            with self.subTest(field=name):
                with self.assertRaises(AppError):
                    link.Provenance.from_dict({**good, name: bad})

    def test_a_snapshot_can_only_be_made_from_an_engine_candidate(self):
        for bad in (None, {"channel": "naver_b"}, ts.make().scores):
            with self.assertRaises(TypeError):
                link.Provenance.of(bad)

    def test_the_snapshot_fields_can_only_be_given_by_name_and_all_of_them(self):
        with self.assertRaises(TypeError):
            link.Provenance(ts.flat_card(80), "RECOMMENDED")
        data = {name: getattr(link.Provenance.of(ts.full()), name) for name in CARRIED}
        del data["trend_period"]
        with self.assertRaises(TypeError):
            link.Provenance(**data)


class LayoutTest(unittest.TestCase):
    def test_the_four_file_names_are_exactly_these(self):
        self.assertEqual(layout.CHANNEL_PROFILES_FILE, "channel_profiles.json")
        self.assertEqual(layout.SEEDS_FILE, "seeds.json")
        self.assertEqual(layout.CALENDAR_FILE, "calendar.json")
        self.assertEqual(layout.ENGINE_DB_FILE, "topic_engine.db")
        self.assertEqual(layout.USER_DATA_FILES, ("channel_profiles.json", "seeds.json", "calendar.json", "topic_engine.db"))

    def test_the_json_files_and_the_sqlite_file_are_kept_apart(self):
        self.assertEqual(layout.JSON_FILES, ("channel_profiles.json", "seeds.json", "calendar.json"))
        self.assertEqual(layout.SQLITE_FILES, ("topic_engine.db",))
        self.assertEqual(layout.JSON_FILES + layout.SQLITE_FILES, layout.USER_DATA_FILES)
        self.assertTrue(all(name.endswith(".json") for name in layout.JSON_FILES))
        self.assertTrue(all(name.endswith(".db") for name in layout.SQLITE_FILES))

    def test_the_names_are_plain_unique_lowercase_file_names(self):
        self.assertEqual(len(set(layout.USER_DATA_FILES)), len(layout.USER_DATA_FILES))
        for name in layout.USER_DATA_FILES:
            with self.subTest(name=name):
                self.assertRegex(name, r"^[a-z][a-z0-9_]*\.(json|db)$")

    def test_the_names_do_not_collide_with_the_files_the_app_already_keeps(self):
        existing = {old_context.STORE_NAME, "settings.json", old_connections.FILE_NAME, old_quota.FILE_NAME}
        self.assertEqual(existing, {"chanceblog.db", "settings.json", "connections.json", "quota_state.json"})
        self.assertEqual(set(layout.USER_DATA_FILES) & existing, set())
        self.assertNotEqual(layout.ENGINE_DB_FILE, old_context.STORE_NAME, "기존 보관함 chanceblog.db 는 바꾸지 않는다")

    def test_no_name_stands_for_a_key_or_a_credential(self):
        for name in layout.USER_DATA_FILES:
            for word in ("key", "token", "secret", "password", "credential", "cred"):
                self.assertNotIn(word, name)


if __name__ == "__main__":
    unittest.main()
