"""채널 프로필 시험 — 채널 이름(코드 키·입력 별칭), 기본값(손으로 쓴 기댓값으로 숫자를 못박는다), 공통 상수, 엄격한 검사, 엄격한 JSON 왕복.

지키는 것:
  1) 채널 이름은 코드의 다섯 키 그대로이고(`PLATFORMS` 와 같다) 전략 문서의 Blogger A·B 는 입력 별칭으로만 받는다. 모르는 이름은 거절하고 대소문자·공백을 고쳐 받지 않는다.
  2) 기본값의 모든 숫자(가중치·비율·상위 N·묶음 상한·소제목·중복 기준·켜기·관심도 사용·언어·표시 이름)를 문서와 같은 손으로 쓴 값으로 못박는다.
  3) 가중치 합 100·비율 합 100, 범위 밖·모르는 칸·합 불일치는 CONTENT_INVALID 로 거절하고 고쳐 받지 않는다.
  4) 사전 변환은 엄격하다(schema·정확한 칸·다섯 채널이 하나씩) — 왕복하면 같은 프로필이 된다. 기본 프로필은 바꿀 수 없다.
네트워크·파일·실제 시계 없이 돈다.
"""
import dataclasses
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402, F401  (src 경로를 올린다)

from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.content.status import PLATFORMS  # noqa: E402
from chanceblog_desktop.service.format import PLATFORM_KO  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import model  # noqa: E402

KEYS = ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b")
# 손으로 쓴 기댓값 — 순서: 채널 적합도·작성 가능성·차별성·시기·근거·수익화
WEIGHTS = {"github_pages": (20, 15, 15, 15, 25, 10), "blogger_ko": (25, 25, 20, 10, 10, 10), "blogger_en": (30, 25, 20, 5, 10, 10), "naver_a": (25, 15, 10, 15, 10, 25),
           "naver_b": (25, 15, 10, 20, 10, 20)}
EVERGREEN = {"github_pages": 40, "blogger_ko": 85, "blogger_en": 90, "naver_a": 70, "naver_b": 50}
REALTIME = {"github_pages": 60, "blogger_ko": 15, "blogger_en": 10, "naver_a": 30, "naver_b": 50}
ENABLED = {"github_pages": False, "blogger_ko": False, "blogger_en": False, "naver_a": True, "naver_b": True}
TREND_USE = {"github_pages": "supporting", "blogger_ko": "reference", "blogger_en": "none", "naver_a": "primary", "naver_b": "primary"}
LANGUAGE = {"github_pages": "ko", "blogger_ko": "ko", "blogger_en": "en", "naver_a": "ko", "naver_b": "ko"}
NAMES = {"github_pages": "GitHub Pages", "blogger_ko": "Blogger 한글", "blogger_en": "Blogger 영문", "naver_a": "네이버 A", "naver_b": "네이버 B"}


def profile(base_key="naver_b", **changes):
    """기본 프로필 하나(`base_key`)에서 몇 칸만 바꾼 복사본 — 바꾼 값도 검사를 다시 거친다."""
    base = {p.key: p for p in ch.default_profiles()}[base_key]
    return dataclasses.replace(base, **changes)


def all_changed(p):
    """모든 칸(채널 키만 빼고)을 기본값과 다른, 그러나 올바른 값으로 바꾼 복사본."""
    weights = dict(p.weights)
    weights["channel_fit"], weights["monetization"] = weights["channel_fit"] + 1, weights["monetization"] - 1
    other_use = [use for use in ch.TREND_USES if use != p.trend_use][0]
    return dataclasses.replace(p, display_name=p.display_name + "!", language="en" if p.language == "ko" else "ko", generation_enabled=not p.generation_enabled,
                               history_enabled=not p.history_enabled, evergreen_pct=p.evergreen_pct + 1, realtime_pct=p.realtime_pct - 1, weights=weights, top_n=p.top_n + 1,
                               cluster_cap=p.cluster_cap + 1, subheading_min=p.subheading_min + 1, trend_use=other_use, dup_cutoffs=(30, 50, 80), topic_clusters=("x-one", "x-two"),
                               expansion_directions=("바꾼 방향",), monetization_focus=("x_tag",))


def rejected(test, call):
    """CONTENT_INVALID 로 거절하고 쉬운 한국어 안내가 만들어지는지 본다."""
    with test.assertRaises(AppError) as caught:
        call()
    test.assertEqual(caught.exception.code, "CONTENT_INVALID")
    test.assertTrue(caught.exception.rendered().message)
    return caught.exception


class ChannelNamesTest(unittest.TestCase):
    def test_the_channel_keys_are_the_five_code_keys_in_the_code_order(self):
        self.assertEqual(ch.CHANNELS, KEYS)
        self.assertEqual(ch.CHANNELS, PLATFORMS)

    def test_the_strategy_names_for_blogger_are_input_aliases_only(self):
        self.assertEqual(dict(ch.CHANNEL_ALIAS), {"blogger_a": "blogger_ko", "blogger_b": "blogger_en"})
        self.assertFalse(set(ch.CHANNEL_ALIAS) & set(ch.CHANNELS), "별칭은 코드 키와 겹치지 않는다")

    def test_canonical_keeps_code_keys_and_translates_aliases(self):
        for key in KEYS:
            self.assertEqual(ch.canonical(key), key)
        self.assertEqual(ch.canonical("blogger_a"), "blogger_ko")
        self.assertEqual(ch.canonical("blogger_b"), "blogger_en")

    def test_canonical_rejects_unknown_names_without_fixing_them(self):
        for name in ("", " naver_a", "naver_a ", "NAVER_A", "Blogger_A", "blogger_c", "blogger", "naver", "tistory", "naver-a", None, 3, ("naver_a",), b"naver_a"):
            with self.subTest(name=name):
                rejected(self, lambda name=name: ch.canonical(name))

    def test_the_alias_table_cannot_be_changed(self):
        with self.assertRaises(TypeError):
            ch.CHANNEL_ALIAS["blogger_c"] = "naver_a"

    def test_the_six_factor_names_and_their_korean_labels(self):
        self.assertEqual(ch.FACTOR_NAMES, ("channel_fit", "feasibility", "differentiation", "timing", "evidence", "monetization"))
        self.assertEqual(ch.FACTOR_LABELS["channel_fit"], "채널 적합도")
        self.assertEqual(ch.FACTOR_LABELS["feasibility"], "작성 가능성")
        self.assertEqual(ch.FACTOR_LABELS["differentiation"], "차별성")
        self.assertEqual(ch.FACTOR_LABELS["timing"], "시기")
        self.assertEqual(ch.FACTOR_LABELS["evidence"], "근거")
        self.assertEqual(ch.FACTOR_LABELS["monetization"], "수익화")
        self.assertEqual(set(ch.FACTOR_LABELS), set(ch.FACTOR_NAMES))


class DefaultProfilesTest(unittest.TestCase):
    def setUp(self):
        self.by_key = {p.key: p for p in ch.default_profiles()}

    def test_there_are_five_profiles_one_per_channel_in_the_code_order(self):
        self.assertEqual([p.key for p in ch.default_profiles()], list(KEYS))
        self.assertIsInstance(ch.default_profiles(), tuple)

    def test_the_weights_are_exactly_the_documented_numbers(self):
        for key, numbers in WEIGHTS.items():
            with self.subTest(channel=key):
                self.assertEqual(tuple(self.by_key[key].weights[name] for name in ch.FACTOR_NAMES), numbers)
                self.assertEqual(list(self.by_key[key].weights), list(ch.FACTOR_NAMES), "항목 순서도 같다")

    def test_every_weight_set_adds_up_to_one_hundred(self):
        for key, p in self.by_key.items():
            with self.subTest(channel=key):
                self.assertEqual(sum(p.weights.values()), 100)

    def test_the_evergreen_and_realtime_shares_are_exactly_the_documented_numbers(self):
        for key in KEYS:
            with self.subTest(channel=key):
                self.assertEqual(self.by_key[key].evergreen_pct, EVERGREEN[key])
                self.assertEqual(self.by_key[key].realtime_pct, REALTIME[key])
                self.assertEqual(self.by_key[key].evergreen_pct + self.by_key[key].realtime_pct, 100)

    def test_top_n_cluster_cap_subheadings_and_duplicate_cutoffs_are_the_same_for_every_channel(self):
        for key, p in self.by_key.items():
            with self.subTest(channel=key):
                self.assertEqual((p.top_n, p.cluster_cap, p.subheading_min), (5, 2, 4))
                self.assertEqual(p.dup_cutoffs, (40, 60, 75))

    def test_only_the_two_naver_channels_generate_candidates_and_every_channel_reads_history(self):
        for key in KEYS:
            with self.subTest(channel=key):
                self.assertIs(self.by_key[key].generation_enabled, ENABLED[key])
                self.assertIs(self.by_key[key].history_enabled, True)

    def test_trend_use_language_and_display_names(self):
        for key in KEYS:
            with self.subTest(channel=key):
                self.assertEqual(self.by_key[key].trend_use, TREND_USE[key])
                self.assertEqual(self.by_key[key].language, LANGUAGE[key])
                self.assertEqual(self.by_key[key].display_name, NAMES[key])

    def test_the_display_names_match_the_ones_the_service_layer_shows(self):
        self.assertEqual({key: p.display_name for key, p in self.by_key.items()}, dict(PLATFORM_KO))

    def test_the_only_english_channel_is_blogger_en_and_it_does_not_use_the_trend(self):
        self.assertEqual([key for key, p in self.by_key.items() if p.language == "en"], ["blogger_en"])
        self.assertEqual([key for key, p in self.by_key.items() if p.trend_use == "none"], ["blogger_en"])

    def test_the_text_lists_are_valid_identifiers_and_the_naver_channels_name_their_monetization_focus(self):
        for key, p in self.by_key.items():
            with self.subTest(channel=key):
                self.assertTrue(p.topic_clusters)
                self.assertTrue(all(ch.is_slug(name) for name in p.topic_clusters))
                self.assertTrue(p.expansion_directions)
                self.assertTrue(all(ch.is_tag(name) for name in p.monetization_focus))
        self.assertEqual(self.by_key["naver_a"].monetization_focus, ("small_appliance", "pc_peripheral", "lodging_travel"))
        self.assertEqual(self.by_key["naver_b"].monetization_focus, ("ai_service", "pc_parts", "work_automation"))
        for key in ("github_pages", "blogger_en", "blogger_ko"):
            self.assertEqual(self.by_key[key].monetization_focus, ())

    def test_the_default_profiles_cannot_be_changed(self):
        p = self.by_key["naver_b"]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.top_n = 9
        with self.assertRaises(TypeError):
            p.weights["timing"] = 99
        with self.assertRaises(AttributeError):
            ch.default_profiles().append(p)

    def test_changing_a_copy_goes_through_the_checks_and_leaves_the_default_alone(self):
        changed = dataclasses.replace(self.by_key["naver_b"], top_n=3)
        self.assertEqual(changed.top_n, 3)
        self.assertEqual(self.by_key["naver_b"].top_n, 5)
        rejected(self, lambda: dataclasses.replace(self.by_key["naver_b"], top_n=0))

    def test_the_profile_is_hashable_and_equal_by_value(self):
        self.assertEqual(hash(ch.default_profiles()[0]), hash(ch.default_profiles()[0]))
        self.assertEqual(profile("naver_a"), profile("naver_a"))
        self.assertNotEqual(profile("naver_a"), profile("naver_a", top_n=4))


class CommonConstantsTest(unittest.TestCase):
    def test_the_candidate_source_mix(self):
        self.assertEqual(dict(ch.SOURCE_MIX), {"seed": 30, "follow_up": 20, "seasonal": 20, "realtime": 15, "sponsor": 15})
        self.assertEqual(sum(ch.SOURCE_MIX.values()), 100)
        self.assertEqual(set(ch.SOURCE_MIX), set(model.SOURCE_TYPES))

    def test_the_candidates_made_and_kept_per_seed_type(self):
        self.assertEqual({name: tuple(quota) for name, quota in ch.PER_SEED.items()},
                         {"general": (3, 2), "priority": (5, 3), "seasonal": (5, 3), "realtime": (5, 3), "sponsorable": (5, 3)})
        self.assertTrue(all(quota.first >= quota.keep for quota in ch.PER_SEED.values()))

    def test_the_grade_cutoffs_the_hold_days_and_the_reuse_limits(self):
        self.assertEqual(ch.GRADE_CUTOFFS, (80, 65, 50))
        self.assertEqual(ch.HOLD_DAYS, 90)
        self.assertEqual(ch.FOLLOW_UP_PER_POST, 3)
        self.assertEqual(ch.MAX_CHANNELS_PER_TOPIC, 2)

    def test_the_constant_tables_cannot_be_changed(self):
        with self.assertRaises(TypeError):
            ch.SOURCE_MIX["seed"] = 31
        with self.assertRaises(TypeError):
            ch.PER_SEED["general"] = (9, 9)


class IdentifierShapeTest(unittest.TestCase):
    def test_slugs_are_lowercase_words_joined_by_hyphens(self):
        for good in ("local-ai", "a", "gpu-memory-requirements", "a1-b2", "9"):
            self.assertTrue(ch.is_slug(good), good)
        for bad in ("", "Local-ai", "local_ai", "local--ai", "-local", "local-", "local ai", "로컬-ai", "local-ai\n", " local-ai", "a" * 61, None, 3):
            self.assertFalse(ch.is_slug(bad), repr(bad))
        self.assertTrue(ch.is_slug("a" * 60))

    def test_tags_are_lowercase_words_joined_by_underscores(self):
        for good in ("pc_parts", "affiliate", "a1_b2"):
            self.assertTrue(ch.is_tag(good), good)
        for bad in ("", "Pc_parts", "pc-parts", "pc__parts", "_pc", "pc_", "pc parts", "pc_parts\n", "a" * 41, None, 3):
            self.assertFalse(ch.is_tag(bad), repr(bad))


class StrictProfileTest(unittest.TestCase):
    def test_weights_that_do_not_add_up_to_one_hundred_are_rejected(self):
        for delta in (-1, 1, 5):
            with self.subTest(delta=delta):
                weights = dict(profile().weights)
                weights["timing"] += delta
                rejected(self, lambda weights=weights: profile(weights=weights))

    def test_weights_must_name_exactly_the_six_factors(self):
        good = dict(profile().weights)
        missing = {name: value for name, value in good.items() if name != "timing"}
        missing["channel_fit"] += good["timing"]
        rejected(self, lambda: profile(weights=missing))
        extra = {**good, "luck": 0}
        rejected(self, lambda: profile(weights=extra))
        renamed = {("search_volume" if name == "timing" else name): value for name, value in good.items()}
        rejected(self, lambda: profile(weights=renamed))
        for not_a_mapping in (None, 100, [20, 15, 15, 15, 25, 10], "x"):
            rejected(self, lambda value=not_a_mapping: profile(weights=value))

    def test_each_weight_is_an_integer_between_zero_and_one_hundred(self):
        for bad in (-1, 101, 2.5, True, "20", None):
            with self.subTest(value=bad):
                weights = dict(profile().weights)
                weights["evidence"] = bad
                rejected(self, lambda weights=weights: profile(weights=weights))

    def test_a_zero_weight_is_allowed_when_the_rest_still_adds_up(self):
        weights = dict(profile().weights)
        weights["channel_fit"] += weights["timing"]
        weights["timing"] = 0
        self.assertEqual(profile(weights=weights).weights["timing"], 0)

    def test_the_evergreen_and_realtime_shares_must_add_up_to_one_hundred(self):
        rejected(self, lambda: profile(evergreen_pct=51))
        rejected(self, lambda: profile(realtime_pct=49))
        rejected(self, lambda: profile(evergreen_pct=101, realtime_pct=-1))
        rejected(self, lambda: profile(evergreen_pct=50.0, realtime_pct=50))
        rejected(self, lambda: profile(evergreen_pct=True, realtime_pct=99))
        self.assertEqual(profile(evergreen_pct=100, realtime_pct=0).evergreen_pct, 100)

    def test_counts_must_be_integers_inside_their_range(self):
        for name, low, high in (("top_n", 1, ch.MAX_TOP_N), ("cluster_cap", 1, ch.MAX_CLUSTER_CAP), ("subheading_min", 1, ch.MAX_SUBHEADING_MIN)):
            with self.subTest(field=name):
                self.assertEqual(getattr(profile(**{name: low}), name), low)
                self.assertEqual(getattr(profile(**{name: high}), name), high)
                for bad in (low - 1, high + 1, True, 2.0, "3", None):
                    rejected(self, lambda name=name, bad=bad: profile(**{name: bad}))

    def test_trend_use_and_language_come_from_closed_lists(self):
        self.assertEqual(ch.TREND_USES, ("primary", "supporting", "reference", "none"))
        for use in ch.TREND_USES:
            self.assertEqual(profile(trend_use=use).trend_use, use)
        for bad in ("secondary", "", "PRIMARY", None, True):
            rejected(self, lambda bad=bad: profile(trend_use=bad))
        for bad in ("jp", "KO", "", None):
            rejected(self, lambda bad=bad: profile(language=bad))

    def test_the_enabled_flags_must_be_real_booleans(self):
        for name in ("generation_enabled", "history_enabled"):
            for bad in (1, 0, "true", None):
                with self.subTest(field=name, value=bad):
                    rejected(self, lambda name=name, bad=bad: profile(**{name: bad}))

    def test_the_channel_key_must_be_a_code_key_and_an_alias_is_not_stored(self):
        for bad in ("blogger_a", "blogger_b", "tistory", "", None):
            rejected(self, lambda bad=bad: profile(key=bad))

    def test_the_display_name_is_one_short_line_without_markup(self):
        for bad in ("", " ", "네이버\nA", "<b>네이버</b>", "가" * 31, None, 3):
            with self.subTest(name=bad):
                rejected(self, lambda bad=bad: profile(display_name=bad))
        self.assertEqual(profile(display_name="가" * 30).display_name, "가" * 30)

    def test_duplicate_cutoffs_are_three_increasing_percentages(self):
        for bad in ((40, 60), (40, 60, 75, 90), (60, 40, 75), (40, 40, 75), (0, 60, 75), (40, 60, 100), (40.0, 60, 75), (True, 60, 75), "406075", None):
            with self.subTest(cutoffs=bad):
                rejected(self, lambda bad=bad: profile(dup_cutoffs=bad))
        self.assertEqual(profile(dup_cutoffs=[30, 50, 80]).dup_cutoffs, (30, 50, 80))

    def test_topic_clusters_are_unique_identifiers_in_a_list(self):
        for bad in (("Local-AI",), ("local ai",), ("local-ai", "local-ai"), "local-ai", None, ("local_ai",), (1,), tuple(f"c{i}" for i in range(ch.MAX_CLUSTERS + 1))):
            with self.subTest(clusters=bad):
                rejected(self, lambda bad=bad: profile(topic_clusters=bad))
        self.assertEqual(profile(topic_clusters=["a", "b"]).topic_clusters, ("a", "b"))

    def test_expansion_directions_are_unique_one_line_words_without_markup(self):
        for bad in (("설치", "설치"), ("<script>",), ("두\n줄",), ("",), "설치", None, tuple(f"방향{i}" for i in range(ch.MAX_DIRECTIONS + 1)), ("가" * 41,)):
            with self.subTest(directions=bad):
                rejected(self, lambda bad=bad: profile(expansion_directions=bad))

    def test_the_monetization_focus_is_a_list_of_unique_tags(self):
        for bad in (("PC",), ("pc parts",), ("pc_parts", "pc_parts"), "pc_parts", None, tuple(f"t{i}" for i in range(ch.MAX_FOCUS + 1))):
            with self.subTest(focus=bad):
                rejected(self, lambda bad=bad: profile(monetization_focus=bad))

    def test_the_error_tells_which_item_in_plain_korean(self):
        error = rejected(self, lambda: profile(top_n=0))
        self.assertIn("채널당 후보 수", error.rendered().message)
        self.assertIn("CONTENT_INVALID", CATALOG)
        weights = dict(profile().weights)
        weights["timing"] += 1
        error = rejected(self, lambda: profile(weights=weights))
        self.assertIn("항목별 가중치", error.rendered().message)
        self.assertIn("100", error.detail)


class CopyAndPlainViewTest(unittest.TestCase):
    # P2a(독립 검증 L3): 읽기 전용 보기(`MappingProxyType`)는 복사할 수 없어 채널 프로필이 `copy`·`pickle`·`dataclasses.asdict` 에서 TypeError 였다 — 가중치를 복사할 수 있는 읽기 전용 사전(`Weights`)으로 바꿨다.
    def test_every_default_profile_can_be_copied_deep_copied_and_pickled_and_stays_equal(self):
        import copy
        import pickle
        for profile in ch.default_profiles():
            with self.subTest(channel=profile.key):
                self.assertEqual(copy.copy(profile), profile)
                self.assertEqual(copy.deepcopy(profile), profile)
                for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                    self.assertEqual(pickle.loads(pickle.dumps(profile, protocol)), profile)
                self.assertEqual(hash(copy.deepcopy(profile)), hash(profile))

    def test_a_copy_still_has_read_only_weights_and_is_a_separate_object(self):
        import copy
        original = ch.default_profiles()[4]
        clone = copy.deepcopy(original)
        self.assertIsNot(clone.weights, original.weights)
        self.assertEqual(type(clone.weights), ch.Weights)
        with self.assertRaises(TypeError):
            clone.weights["timing"] = 1

    def test_asdict_and_astuple_work_and_json_text_comes_from_to_dict(self):
        # P2b(독립 검증 M1) 의도적 갱신: 가중치를 진짜 읽기 전용으로 만들려고 `dict` 하위 클래스를 `Mapping` 으로 바꿨다 — `asdict` 가 돌려주는 가중치도 읽기 전용 `Weights` 로 남아 JSON 글로 바로는
        # 못 쓴다(전에는 사전이라 됐다). JSON 글은 처음부터 `to_dict()`(일반 사전)가 맡는다 — `asdict`·`astuple` 이 오류 없이 되고 값이 같다는 약속은 그대로다.
        profile = ch.default_profiles()[4]
        data = dataclasses.asdict(profile)
        self.assertEqual(dict(data["weights"]), dict(profile.weights))
        self.assertEqual(type(data["weights"]), ch.Weights)
        with self.assertRaises(TypeError):
            data["weights"]["timing"] = 1
        self.assertEqual(json.loads(json.dumps(profile.to_dict()))["weights"], dict(profile.weights))
        self.assertEqual(json.loads(json.dumps({**data, "weights": dict(data["weights"])}))["weights"], dict(profile.weights))
        self.assertEqual(data["key"], "naver_b")
        self.assertEqual(len(dataclasses.astuple(profile)), len(dataclasses.fields(profile)))

    def test_the_weights_are_a_real_read_only_mapping_not_a_dictionary_so_calling_the_dictionary_parts_directly_fails_too(self):
        # P2b(독립 검증 M1): P2a 의 `dict` 하위 클래스는 `dict.update(w, …)`·`dict.__setitem__(w, …)`·`w.__init__(…)` 같은 직접 호출로 가중치가 바뀌었다 — 공유 기본값이 한 번 바뀌면 프로세스 전체가 오염된다.
        import operator
        from collections.abc import Mapping
        weights = ch.default_profiles()[0].weights
        before = dict(weights)
        self.assertIsInstance(weights, Mapping)
        self.assertNotIsInstance(weights, dict)
        attempts = (lambda: dict.update(weights, {"channel_fit": 99}), lambda: dict.__setitem__(weights, "channel_fit", 99), lambda: dict.__delitem__(weights, "channel_fit"), lambda: dict.clear(weights),
                    lambda: dict.pop(weights, "channel_fit"), lambda: dict.popitem(weights), lambda: dict.setdefault(weights, "extra", 1), lambda: weights.__init__({"channel_fit": 99}),
                    lambda: weights.__init__(), lambda: setattr(weights, "_data", {}), lambda: setattr(weights, "extra", 1), lambda: delattr(weights, "_data"), lambda: weights.__setattr__("x", 1),
                    lambda: operator.setitem(weights._data, "channel_fit", 99))
        for number, attempt in enumerate(attempts):
            with self.subTest(attempt=number):
                with self.assertRaises(TypeError):
                    attempt()
        self.assertEqual(dict(weights), before)
        self.assertEqual(dict(ch.default_profiles()[0].weights), before, "공유 기본값은 그대로다")
        self.assertEqual(sum(weights.values()), 100)

    def test_a_copy_of_the_weights_is_equal_but_never_the_same_object_and_can_be_pickled(self):
        import copy
        import pickle
        weights = ch.default_profiles()[3].weights
        for clone in (copy.copy(weights), copy.deepcopy(weights), pickle.loads(pickle.dumps(weights)), ch.Weights(weights), ch.Weights(dict(weights))):
            with self.subTest(clone=type(clone).__name__):
                self.assertIsNot(clone, weights)
                self.assertEqual(clone, weights)
                self.assertEqual(clone, dict(weights))
                self.assertEqual(dict(weights), clone)
                self.assertIs(type(clone), ch.Weights)
        self.assertEqual(repr(ch.Weights({"a": 1})), "Weights({'a': 1})")
        self.assertEqual(len(weights), 6)
        self.assertIn("timing", weights)
        self.assertEqual(weights.get("timing"), 15)
        self.assertIsNone(weights.get("nope"))
        self.assertEqual(list(weights.items())[0], ("channel_fit", 25))

    def test_the_weights_cannot_be_changed_by_any_of_the_usual_ways(self):
        weights = ch.default_profiles()[0].weights
        attempts = (lambda: weights.__setitem__("timing", 1), lambda: weights.__delitem__("timing"), lambda: weights.update(timing=1), lambda: weights.pop("timing"), lambda: weights.popitem(),
                    lambda: weights.setdefault("timing", 1), lambda: weights.clear())
        for attempt in attempts:
            with self.subTest(attempt=attempt):
                with self.assertRaises(TypeError):
                    attempt()
        with self.assertRaises(TypeError):
            weights |= {"timing": 1}
        self.assertEqual(sum(weights.values()), 100)

    def test_a_weights_object_behaves_like_a_dictionary_for_reading(self):
        weights = ch.default_profiles()[0].weights
        self.assertEqual(list(weights), list(ch.FACTOR_NAMES))
        self.assertEqual(weights, dict(weights))
        self.assertEqual(weights["evidence"], 25)
        self.assertEqual(ch.Weights(dict(weights)), weights)


class PlainKoreanErrorTest(unittest.TestCase):
    # P2a(독립 검증 L5): 안내 틀이 '원고의 「항목」 이 올바르지 않습니다' 라서 칸 이름만으로는 무엇이 틀렸는지 알 수 없었다 — 같은 오류 코드(`CONTENT_INVALID`)에 '어느 칸이 왜' 를 쉬운 말로 함께 담는다.
    def message(self, **changes):
        with self.assertRaises(AppError) as caught:
            profile(**changes)
        self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        return caught.exception.rendered().message

    def test_the_weight_sum_error_says_the_sum_and_what_it_should_be(self):
        weights = dict(profile().weights)
        weights["timing"] += 5
        shown = self.message(weights=weights)
        for needle in ("채널 프로필의 항목별 가중치", "합은 100", "105"):
            self.assertIn(needle, shown)

    def test_every_kind_of_wrong_value_names_the_profile_the_field_and_the_reason(self):
        cases = ((dict(top_n=0), "채널당 후보 수", "1~20"), (dict(cluster_cap=99), "주제 묶음 상한", "1~20"), (dict(subheading_min=0), "소제목 최소 수", "1~20"), (dict(evergreen_pct=101), "지속형 비율", "0~100"),
                 (dict(evergreen_pct=60), "지속형·실시간 비율", "합은 100"), (dict(language="fr"), "언어", "한국어"), (dict(trend_use="x"), "관심도 사용 정도", "주된 근거로 씀"), (dict(dup_cutoffs=(40, 60)), "중복 판정 기준", "세 개"),
                 (dict(dup_cutoffs=(60, 40, 75)), "중복 판정 기준", "커야"), (dict(display_name=""), "표시 이름", "한 줄"), (dict(topic_clusters=("Bad Name",)), "주제 묶음", "식별자"),
                 (dict(expansion_directions="문자열"), "확장 방향", "모양"), (dict(monetization_focus=("Bad",)), "우선 수익화 분야", "태그"), (dict(generation_enabled="yes"), "후보 생성 켜기", "true"))
        for changes, field, reason in cases:
            with self.subTest(changes=changes):
                shown = self.message(**changes)
                self.assertIn("채널 프로필의 " + field, shown)
                self.assertIn(reason, shown)

    def test_the_detail_for_the_log_is_kept_and_the_reason_is_in_the_message(self):
        weights = dict(profile().weights)
        weights["timing"] += 1
        with self.assertRaises(AppError) as caught:
            profile(weights=weights)
        self.assertIn("101", caught.exception.detail)
        self.assertIn("101", caught.exception.rendered().message)

    def test_the_structure_errors_when_reading_a_file_name_the_problem_too(self):
        good = ch.profiles_to_dict(ch.default_profiles())
        extra = {**good, "profiles": [{**good["profiles"][0], "unknown": 1}, *good["profiles"][1:]]}
        with self.assertRaises(AppError) as caught:
            ch.profiles_from_dict(extra)
        self.assertIn("모르는 칸", caught.exception.rendered().message)
        with self.assertRaises(AppError) as caught:
            ch.profiles_from_dict({**good, "profiles": good["profiles"][:4]})
        self.assertIn("빠진 채널", caught.exception.rendered().message)
        with self.assertRaises(AppError) as caught:
            ch.canonical("naver")
        self.assertIn("아는 채널 이름이 아닙니다", caught.exception.rendered().message)

    OLD_WORDING = ("원고의", "제목은 200자", "출처 주소는", "이미지 파일 이름", "폴더 구분", "주제는 200자", "핵심 키워드는 60자", "추천 이유는 300자", "상위노출", "저장하지 않았습니다")

    def test_the_shared_content_template_no_longer_talks_about_manuscripts_titles_or_candidates(self):
        # P2b(독립 검증 M7): P2a 는 이유를 안내문에 넣었지만 틀 앞의 '원고의' 와 뒤의 '제목은 200자 이하…' 조치가 그대로라 씨앗·캘린더·보류·채널 프로필 오류에 맞지 않았다 — 틀 자체를 중립으로 바꿨다.
        info = CATALOG["CONTENT_INVALID"]
        self.assertEqual((set(info.slots), info.retry_kind, info.code), ({"항목"}, "after_user", "CONTENT_INVALID"))
        for old in self.OLD_WORDING:
            self.assertNotIn(old, info.message + info.action, old)
        self.assertEqual(info.message, "다음 칸의 값이 올바르지 않습니다: **「항목」**.")
        self.assertIn("직접 고쳐야", info.action)
        for area in ("채널 프로필", "씨앗", "캘린더", "보류함"):
            self.assertIn(area, info.when)

    def test_every_engine_error_shows_the_field_and_the_reason_and_none_of_the_old_wording(self):
        from chanceblog_desktop.topics import hold, schedule, seeds
        weights = dict(profile().weights)
        weights["timing"] += 5
        calls = (lambda: profile(weights=weights), lambda: profile(top_n=0), lambda: ts.example_seed(keyword=""), lambda: ts.example_seed(state="proposed", active_since="2026-06-01"),
                 lambda: ts.example_entry(prep_start="01-01", publish_from="12-31"), lambda: ts.example_entry(name="상위노출 보장"), lambda: hold.review_expires_at("엉터리"),
                 lambda: hold.review_expires_at("2026-11-05T00:00:00Z", 0), lambda: seeds.seeds_from_dict({"schema": 1, "seeds": [{}]}), lambda: schedule.entries_from_dict({"schema": 2}),
                 lambda: ch.profiles_from_dict({"schema": 1}), lambda: ch.canonical("naver"), lambda: seeds.change_state(ts.example_seed(), "active", None))
        for number, call in enumerate(calls):
            with self.subTest(call=number):
                with self.assertRaises(AppError) as caught:
                    call()
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                shown = caught.exception.rendered()
                self.assertTrue(shown.message.startswith("다음 칸의 값이 올바르지 않습니다: 「"), shown.message)
                self.assertIn(" — ", shown.message, "칸 이름 뒤에 이유가 있다")
                fixed = shown.message.split("「", 1)[0] + shown.message.rsplit("」", 1)[-1] + " " + shown.action          # 틀의 고정 글(칸 안의 이유는 빼고 — 이유는 '상위노출 보장' 같은 말을 따옴표로 보일 수 있다)
                for old in self.OLD_WORDING:
                    self.assertNotIn(old, fixed, old)

    def test_the_candidate_template_is_left_alone_for_the_candidate_fields(self):
        # 후보 칸(주제·키워드·점수 …)의 오류는 그대로 `CANDIDATE_INVALID` 의 후보용 안내다(이 안내는 후보 칸에 맞다).
        with self.assertRaises(AppError) as caught:
            ts.make(topic="")
        self.assertEqual(caught.exception.code, "CANDIDATE_INVALID")
        self.assertIn("주제 후보의", caught.exception.rendered().message)
        self.assertIn("주제는 200자", caught.exception.rendered().action)

    def test_the_helpers_other_modules_use_build_the_same_kind_of_message(self):
        error = ch.invalid_in("씨앗", "대분류", "1~30자 한 줄이어야 한다")
        self.assertEqual((error.code, error.detail), ("CONTENT_INVALID", "1~30자 한 줄이어야 한다"))
        self.assertIn("씨앗의 대분류 — 1~30자 한 줄이어야 한다", error.rendered().message)
        self.assertIn("씨앗 목록 — 같은 번호", ch.invalid_in("씨앗", "씨앗 목록", "같은 번호").rendered().message)
        wrapped = ch.at_entry("씨앗", 3, error)
        self.assertIn("3번째 씨앗의 대분류 — 1~30자 한 줄이어야 한다", wrapped.rendered().message)
        self.assertEqual(wrapped.slots["항목"], "3번째 씨앗의 대분류 — 1~30자 한 줄이어야 한다", "화면 정리 없이도 공백이 하나뿐이고 칸 이름이 온전하다")
        self.assertEqual(error.slots["항목"], "씨앗의 대분류 — 1~30자 한 줄이어야 한다")
        self.assertEqual(ch.at_entry("캘린더", 12, ch.invalid_in("캘린더", "피크", "발행 기간 안이어야 한다")).slots["항목"], "12번째 캘린더의 피크 — 발행 기간 안이어야 한다")
        plain = AppError("CANDIDATE_INVALID", {"항목": "x", "이유": "y"})
        self.assertIs(ch.at_entry("씨앗", 3, plain), plain)
        self.assertIs(ch.explain("씨앗", plain), plain)


class JsonShapeTest(unittest.TestCase):
    def test_one_profile_round_trips_and_has_exactly_these_keys(self):
        for key in KEYS:
            with self.subTest(channel=key):
                p = profile(key)
                data = p.to_dict()
                self.assertEqual(tuple(data), ("key", "display_name", "language", "generation_enabled", "history_enabled", "evergreen_pct", "realtime_pct", "weights", "top_n",
                                               "cluster_cap", "subheading_min", "trend_use", "dup_cutoffs", "topic_clusters", "expansion_directions", "monetization_focus"))
                self.assertEqual(ch.ChannelProfile.from_dict(json.loads(json.dumps(data))), p)

    def test_the_whole_set_round_trips_through_json_text(self):
        data = ch.profiles_to_dict(ch.default_profiles())
        self.assertEqual(data["schema"], 1)
        self.assertEqual([item["key"] for item in data["profiles"]], list(KEYS))
        self.assertEqual(ch.profiles_from_dict(json.loads(json.dumps(data, ensure_ascii=False))), ch.default_profiles())

    def test_an_edited_set_survives_the_round_trip(self):
        edited = tuple(dataclasses.replace(p, top_n=3, cluster_cap=1) if p.key == "naver_a" else p for p in ch.default_profiles())
        again = ch.profiles_from_dict(ch.profiles_to_dict(edited))
        self.assertEqual(again, edited)
        self.assertEqual(again[3].top_n, 3)

    def test_every_field_survives_the_round_trip_when_all_of_them_are_changed(self):
        """모든 칸을 기본값과 다르게 바꾼 프로필 — 저장 모양에서 한 칸이라도 빠지거나 기본값으로 돌아오면 여기서 걸린다."""
        edited = tuple(all_changed(p) for p in ch.default_profiles())
        again = ch.profiles_from_dict(json.loads(json.dumps(ch.profiles_to_dict(edited), ensure_ascii=False)))
        self.assertEqual(again, edited)
        for before, after, default in zip(edited, again, ch.default_profiles(), strict=True):
            for name in (f.name for f in dataclasses.fields(ch.ChannelProfile) if f.name != "key"):
                with self.subTest(channel=before.key, field=name):
                    self.assertNotEqual(getattr(after, name), getattr(default, name), "바꾼 값이 기본값과 달라야 이 시험이 뜻이 있다")
                    self.assertEqual(getattr(after, name), getattr(before, name))

    def test_the_set_is_returned_in_the_code_order_whatever_the_file_order(self):
        data = ch.profiles_to_dict(ch.default_profiles())
        data["profiles"].reverse()
        self.assertEqual([p.key for p in ch.profiles_from_dict(data)], list(KEYS))
        self.assertEqual([item["key"] for item in ch.profiles_to_dict(reversed(ch.default_profiles()))["profiles"]], list(KEYS))

    def test_the_stored_values_are_json_plain_types(self):
        text = json.dumps(ch.profiles_to_dict(ch.default_profiles()), ensure_ascii=False)
        self.assertNotIn("mappingproxy", text)
        self.assertEqual(type(ch.default_profiles()[0].to_dict()["weights"]), dict)

    def test_the_set_needs_the_exact_schema(self):
        good = ch.profiles_to_dict(ch.default_profiles())
        for schema in (0, 2, "1", 1.0, True, None):
            with self.subTest(schema=schema):
                rejected(self, lambda schema=schema: ch.profiles_from_dict({**good, "schema": schema}))
        rejected(self, lambda: ch.profiles_from_dict({"profiles": good["profiles"]}))
        for not_a_dict in (None, [], "x", 1):
            rejected(self, lambda value=not_a_dict: ch.profiles_from_dict(value))

    def test_the_set_rejects_unknown_top_level_keys_and_a_non_list(self):
        good = ch.profiles_to_dict(ch.default_profiles())
        rejected(self, lambda: ch.profiles_from_dict({**good, "extra": 1}))
        rejected(self, lambda: ch.profiles_from_dict({"schema": 1, "profiles": tuple(good["profiles"])}))
        rejected(self, lambda: ch.profiles_from_dict({"schema": 1}))

    def test_an_unknown_or_missing_field_in_a_profile_is_rejected(self):
        good = ch.profiles_to_dict(ch.default_profiles())
        extra = json.loads(json.dumps(good))
        extra["profiles"][0]["monthly_volume"] = 1
        rejected(self, lambda: ch.profiles_from_dict(extra))
        for name in ch.ChannelProfile.__dataclass_fields__:
            with self.subTest(missing=name):
                data = json.loads(json.dumps(good))
                del data["profiles"][4][name]
                rejected(self, lambda data=data: ch.profiles_from_dict(data))

    def test_a_profile_with_a_wrong_value_is_rejected_when_read(self):
        good = ch.profiles_to_dict(ch.default_profiles())
        data = json.loads(json.dumps(good))
        data["profiles"][4]["weights"]["timing"] = 21
        rejected(self, lambda: ch.profiles_from_dict(data))
        data = json.loads(json.dumps(good))
        data["profiles"][0]["key"] = "blogger_a"
        rejected(self, lambda: ch.profiles_from_dict(data))
        data = json.loads(json.dumps(good))
        data["profiles"][3]["generation_enabled"] = "yes"
        rejected(self, lambda: ch.profiles_from_dict(data))

    def test_every_channel_must_be_present_exactly_once(self):
        good = ch.profiles_to_dict(ch.default_profiles())
        rejected(self, lambda: ch.profiles_from_dict({"schema": 1, "profiles": good["profiles"][:4]}))
        rejected(self, lambda: ch.profiles_from_dict({"schema": 1, "profiles": good["profiles"] + [good["profiles"][0]]}))
        rejected(self, lambda: ch.profiles_from_dict({"schema": 1, "profiles": []}))
        rejected(self, lambda: ch.profiles_from_dict({"schema": 1, "profiles": good["profiles"][:4] + ["naver_b"]}))

    def test_writing_a_partial_or_foreign_set_is_refused_too(self):
        rejected(self, lambda: ch.profiles_to_dict(ch.default_profiles()[:4]))
        rejected(self, lambda: ch.profiles_to_dict(ch.default_profiles() + ch.default_profiles()[:1]))
        rejected(self, lambda: ch.profiles_to_dict(list(ch.default_profiles()[:4]) + [{"key": "naver_b"}]))

    def test_from_dict_of_a_single_profile_wants_a_dict(self):
        for bad in (None, [], "naver_a", 3):
            rejected(self, lambda value=bad: ch.ChannelProfile.from_dict(value))


if __name__ == "__main__":
    unittest.main()
