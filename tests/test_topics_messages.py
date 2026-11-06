"""`topics/` 가 내는 사용자 노출 문장 전수 점검 — P2b 보완 M1·M2(D-57).

지키는 것:
  M1) 오류 경로 100가지 이상(`PROBES` — 채널 프로필·씨앗·캘린더·보류함·후보·연결·협찬 정보의 칸마다 하나씩 틀리게)을 `AppError` 로 받아 「항목」·「이유」 슬롯 값과 `rendered()` 의 문장·조치에서
      파이썬 목록 꼴·내부 식별자·`Enum` 표기·닫힌 목록의 원시 값(`naver_a`·`ko`·`primary`·`NEW` …)이 나오지 않는다. 운영자가 적은 값은 `‘ ’` 안에만 나온다.
  M2) 생성·진단 문장(`generate()` 의 `Dropped.detail`·`Generated.notes`·선정 이유, 확장·작성 가능성·이슈 검사의 이유)에도 같은 검사를 건다.
새 오류 경로를 더하면 `PROBES` 에도 더한다. `ValueError`·`TypeError`(개발자용 — 잘못된 인자)는 화면에 가지 않아 대상이 아니다. 네트워크·파일·실제 시계·난수 없이 돈다.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import expand as ex  # noqa: E402
from chanceblog_desktop.topics import feasibility as fe  # noqa: E402
from chanceblog_desktop.topics import generate as gn  # noqa: E402
from chanceblog_desktop.topics import hold as hl  # noqa: E402
from chanceblog_desktop.topics import link as lk  # noqa: E402
from chanceblog_desktop.topics import model as md  # noqa: E402
from chanceblog_desktop.topics import notice as nt  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402
from chanceblog_desktop.topics import schedule as sc  # noqa: E402
from chanceblog_desktop.topics import score as se  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402
from chanceblog_desktop.content.candidates import STATUSES  # noqa: E402

PROFILE = ch.default_profiles()[3].to_dict()
SEED = dict(seed_id="s1", major="가", minor="나", keyword="노트북", seed_type="general", scope="common", priority=False, excluded_keywords=[], sponsor_tag=None, state="active", registered_on="2026-01-01",
            last_selected_on=None, active_since=None)
ENTRY = dict(entry_id="x1", name="장마철", keywords=("제습기",), prep_start="05-20", publish_from="06-01", publish_to="07-31", repeat="yearly")
CAND = dict(candidate_id="cand0001", source_type="seed", candidate_type="evergreen", channel="naver_b", language="ko", topic="개인 PC 로컬 AI", primary_keyword="로컬 AI 사양", search_intent="selection_guide",
            content_type="buying_guide", topic_cluster="local-ai", topic_angle="memory-requirements", target_reader="일반 사용자", created_at="2026-11-04T09:56:00Z")
RAW_VALUES = tuple(sorted({*ch.CHANNELS, *ch.LANGUAGES, *ch.TREND_USES, *ch.FACTOR_NAMES, *sd.SEED_TYPES, *sd.SCOPES, *sd.STATES, *sc.REPEATS, *md.SOURCE_TYPES, *md.CANDIDATE_TYPES, *md.SEARCH_INTENTS,
                          *md.CONTENT_TYPES, *md.SAFETY_FLAGS, *md.DUPLICATE_STATUSES, *se.DATA_STATUSES, *se.TREND_STATUSES, *STATUSES, *se.BANDS, *gn.ROUTES, *gn.DROP_REASONS, *ex.BLOCK_REASONS, *ex.FAMILIES,
                          *nt.LEVELS, *sf.INTEREST_TYPES} - {"info", "none", "seed", "common", "partial", "flat", "falling", "rising", "primary", "reference", "supporting", "comparison", "information", "invalid", "sources", "language"}))
INPUT_QUOTE = re.compile("‘[^’]*’")
HYPHEN_ID = re.compile(r"(?<![0-9A-Za-z-])(?=[a-z0-9-]*[a-z])[a-z0-9]+(?:-[a-z0-9]+)+(?![0-9A-Za-z-])")
FAMILY_WORDS = tuple(ex.FAMILIES)                                              # 확장 계열 이름은 영어 방향 낱말(‘low-pressure habit’)과 겹칠 수 있어 따옴표 밖에서만 본다


def word_regex(words):
    return re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True)) + r")(?![A-Za-z0-9_])")


RAW = word_regex([word for word in RAW_VALUES if word not in FAMILY_WORDS])
RAW_FAMILY = word_regex(FAMILY_WORDS)


def leak(text, *, inside_quotes=True):
    """화면 글에 새는 것이 있으면 그 종류의 목록, 없으면 빈 목록 — 구조(목록 꼴·식별자·`Enum`)와 닫힌 목록의 원시 값 이름 둘을 본다. 오류 경로(M1)는 따옴표 안까지 보고(틀린 입력이 `zzz` 같은 값이라서),
    생성 문장(M2)은 따옴표 안의 채널 방향 낱말(영어 ‘everyday checklist’ 같은 것)을 원시 값으로 오해하지 않게 따옴표 밖만 본다."""
    outside = INPUT_QUOTE.sub("", text)
    found = list(nt.leaks(text))
    found += [f"붙임표 식별자 {match}" for match in HYPHEN_ID.findall(outside)]
    found += [f"원시 값 {match}" for match in RAW.findall(text if inside_quotes else outside)]
    found += [f"계열 이름 {match}" for match in RAW_FAMILY.findall(outside)]
    return found


def calls(label, make, values):
    return [(f"{label}[{value!r:.24}]", lambda value=value: make(value)) for value in values]


def build_probes():
    probes = []
    for key in ch._KEYS:
        for value in ("zzz", -5, [], None, {"x": 1}):
            probes.append((f"profile.{key}={value!r:.12}", lambda key=key, value=value: ch.ChannelProfile.from_dict({**PROFILE, key: value})))
    probes += [("profile.unknown", lambda: ch.ChannelProfile.from_dict({**PROFILE, "zzz": 1})), ("profile.missing", lambda: ch.ChannelProfile.from_dict({k: v for k, v in PROFILE.items() if k != "top_n"})),
               ("profile.notdict", lambda: ch.ChannelProfile.from_dict(3)), ("canonical", lambda: ch.canonical("zzz")), ("canonical none", lambda: ch.canonical(None)),
               ("profiles twice", lambda: ch.profiles_from_dict({"schema": 1, "profiles": [PROFILE, PROFILE]})), ("profiles missing", lambda: ch.profiles_from_dict({"schema": 1, "profiles": [PROFILE]})),
               ("profiles schema", lambda: ch.profiles_from_dict({"schema": 2, "profiles": []})), ("profiles keys", lambda: ch.profiles_from_dict({"schema": 1, "profiles": [], "x": 1})),
               ("profiles list", lambda: ch.profiles_from_dict({"schema": 1, "profiles": 3})), ("weights names", lambda: ch.ChannelProfile.from_dict({**PROFILE, "weights": {"a": 1}})),
               ("weights sum", lambda: ch.ChannelProfile.from_dict({**PROFILE, "weights": {name: 1 for name in ch.FACTOR_NAMES}}))]
    for key in sd._KEYS:
        for value in ("zzz", -5, [], None):
            probes.append((f"seed.{key}={value!r:.12}", lambda key=key, value=value: sd.Seed.from_dict({**SEED, key: value})))
    probes += [("seed.unknown", lambda: sd.Seed.from_dict({**SEED, "zzz": 1})), ("seed.missing", lambda: sd.Seed.from_dict({k: v for k, v in SEED.items() if k != "state"})),
               ("seed sponsorable", lambda: sd.Seed.from_dict({**SEED, "seed_type": "sponsorable"})), ("seed state change", lambda: sd.change_state(sd.Seed(**SEED), "zzz", "2026-02-01")),
               ("seeds twice id", lambda: sd.seeds_from_dict({"schema": 1, "seeds": [SEED, SEED]})), ("seeds twice word", lambda: sd.seeds_from_dict({"schema": 1, "seeds": [SEED, {**SEED, "seed_id": "s2"}]})),
               ("seeds schema", lambda: sd.seeds_from_dict({"schema": 2, "seeds": []})), ("seeds keys", lambda: sd.seeds_from_dict({"schema": 1, "seeds": [], "x": 1})), ("seeds list", lambda: sd.seeds_from_dict({"schema": 1, "seeds": 3})),
               ("seeds nth", lambda: sd.seeds_from_dict({"schema": 1, "seeds": [SEED, {**SEED, "seed_id": "s2", "keyword": "마우스", "seed_type": "zzz"}]}))]
    for key in sc._KEYS:
        if key in ("year", "last_evaluated_on"):
            continue
        for value in ("zzz", -5, [], None):
            probes.append((f"entry.{key}={value!r:.12}", lambda key=key, value=value: sc.CalendarEntry.from_dict({**{**ENTRY, "year": None, "last_evaluated_on": None, "channels": ()}, key: value})))
    probes += [("entry.unknown", lambda: sc.CalendarEntry.from_dict({"zzz": 1})), ("entry repeat", lambda: sc.CalendarEntry(**{**ENTRY, "repeat": "weekly"})),
               ("entry channels", lambda: sc.CalendarEntry(**{**ENTRY, "channels": ("zzz",)})), ("entries twice", lambda: sc.entries_from_dict({"schema": 1, "entries": [sc.CalendarEntry(**ENTRY).to_dict()] * 2})),
               ("entries schema", lambda: sc.entries_from_dict({"schema": 2, "entries": []})), ("entries keys", lambda: sc.entries_from_dict({"schema": 1, "entries": [], "x": 1})),
               ("entries list", lambda: sc.entries_from_dict({"schema": 1, "entries": 3})),
               ("entries nth", lambda: sc.entries_from_dict({"schema": 1, "entries": [sc.CalendarEntry(**ENTRY).to_dict(), {**sc.CalendarEntry(**ENTRY).to_dict(), "entry_id": "x2", "repeat": "weekly"}]}))]
    for key in ("source_type", "candidate_type", "language", "search_intent", "content_type", "data_status", "duplicate_status", "work_status", "trend_status", "channel", "safety_flags", "monetization_tags",
                "similar_post_ids", "topic_cluster", "topic_angle", "candidate_id", "created_at", "review_expires_at", "scores", "trend_ratio", "selection_reasons"):
        for value in ("zzz", ("zzz",), -5):
            probes.append((f"candidate.{key}={value!r:.12}", lambda key=key, value=value: md.TopicCandidate(**{**CAND, key: value})))
    probes += [("candidate alias", lambda: md.TopicCandidate(**{**CAND, "channel": "blogger_a"})), ("candidate post type", lambda: md.to_post_type("zzz")),
               ("candidate from_dict short", lambda: md.TopicCandidate.from_dict({"candidate_id": "x"})), ("candidate from_dict extra", lambda: md.TopicCandidate.from_dict({"schema": 1, **CAND, "zzz": 1})),
               ("candidate expiry", lambda: md.check_candidate_expiry(ts.rated(90, review_expires_at="2027-02-02T09:56:00Z"))),
               ("candidate expiry missing", lambda: md.check_candidate_expiry(ts.rated(55))), ("candidate score channel", lambda: md.check_candidate_score(md.TopicCandidate(**CAND), ch.DEFAULT_PROFILES[0])),
               ("trend status", lambda: md.check_trend("zzz", None, None, (), None)), ("link unknown", lambda: lk.CandidateLink.from_dict({"zzz": 1})), ("link schema", lambda: lk.Provenance.from_dict({"schema": 1})),
               ("link notdict", lambda: lk.CandidateLink.from_dict(3)), ("hold stamp", lambda: hl.review_expires_at("엉터리")), ("hold days", lambda: hl.review_expires_at("2026-11-04T09:56:00Z", 0)),
               ("campaign id", lambda: sf.Campaign(campaign_id="a b", benefits=("goods",), status="confirmed", seed_id="s1")), ("campaign benefits", lambda: sf.Campaign(campaign_id="c1", benefits=("zzz",), status="confirmed", seed_id="s1")),
               ("campaign status", lambda: sf.Campaign(campaign_id="c1", benefits=("goods",), status="zzz", seed_id="s1")), ("campaign no link", lambda: sf.Campaign(campaign_id="c1", benefits=("goods",), status="confirmed")),
               ("campaign channel", lambda: sf.Campaign(campaign_id="c1", benefits=("goods",), status="confirmed", seed_id="s1", channel="blogger_a")),
               ("campaign dict", lambda: sf.Campaign.from_dict({"zzz": 1})),
               # 전략 맞춤 1차(D-102)가 더한 오류 경로 — `UNKNOWN`(기본 상태)·`NONE` 섞기·제안 중 `NONE`·같은 뜻 두 번(옛 이름과 새 이름)
               ("campaign unknown", lambda: sf.Campaign(campaign_id="c1", benefits=("UNKNOWN",), status="confirmed", seed_id="s1")),
               ("campaign none mixed", lambda: sf.Campaign(campaign_id="c1", benefits=("NONE", "OTHER"), status="confirmed", seed_id="s1")),
               ("campaign none proposed", lambda: sf.Campaign(campaign_id="c1", benefits=("NONE",), status="proposed", seed_id="s1")),
               ("campaign same meaning twice", lambda: sf.Campaign(campaign_id="c1", benefits=("goods", "PRODUCT_PROVIDED"), status="confirmed", seed_id="s1")),
               ("campaign too many", lambda: sf.Campaign(campaign_id="c1", benefits=sf.BENEFIT_KINDS + ("NONE",), status="confirmed", seed_id="s1"))]
    return probes


PROBES = build_probes()


def caught(make):
    try:
        make()
    except AppError as error:
        return error
    return None


class ErrorSentencesTest(unittest.TestCase):                                                                   # M1
    def test_there_are_at_least_a_hundred_error_paths_that_really_raise_an_app_error(self):
        errors = [(label, caught(make)) for label, make in PROBES]
        raised = [label for label, error in errors if error is not None]
        self.assertGreaterEqual(len(raised), 100, f"AppError 가 난 경로 {len(raised)}개")

    def test_no_error_sentence_shows_a_list_shape_an_identifier_an_enum_or_a_raw_value_name(self):
        checked = 0
        actions = {}
        for label, make in PROBES:
            error = caught(make)
            if error is None:
                continue
            with self.subTest(probe=label):
                shown = [str(error.slots.get("항목", "")), str(error.slots.get("이유", "")), error.rendered().message]
                for text in shown:
                    self.assertEqual(leak(text), [], f"{label} → {text}")
                actions.setdefault(error.code, set()).add(error.rendered().action)
            checked += 1
        self.assertGreaterEqual(checked, 100)
        for code, texts in actions.items():
            self.assertEqual(len(texts), 1, f"{code} 의 하실 일 문구는 입력 값이 들어가지 않은 고정 문장이다(안내 표 그대로)")

    def test_the_developer_note_keeps_the_raw_values_but_only_in_the_detail(self):
        error = caught(lambda: sd.Seed.from_dict({**SEED, "seed_type": "zzz"}))
        self.assertIn("general", error.detail)
        self.assertNotIn("general", error.slots["항목"])
        error = caught(lambda: ch.ChannelProfile.from_dict({**PROFILE, "zzz": 1}))
        self.assertIn("모르는 칸", error.slots["항목"])
        self.assertIn("zzz", error.detail)

    def test_what_the_operator_typed_comes_back_only_inside_curly_quotes(self):
        error = caught(lambda: ch.ChannelProfile.from_dict({**PROFILE, "zzz": 1}))
        self.assertIn("‘zzz’", error.slots["항목"])
        error = caught(lambda: ch.canonical("zzz"))
        self.assertIn("‘zzz’", error.slots["항목"])
        error = caught(lambda: ch.canonical("['a', 'b']"))
        self.assertIn("‘['a', 'b']’", error.slots["항목"])
        self.assertEqual(leak(error.slots["항목"]), [])

    def test_the_known_old_bad_sentences_are_gone(self):
        samples = (caught(lambda: ch.ChannelProfile.from_dict({**PROFILE, "zzz": 1, "top_n": None})), caught(lambda: sd.seeds_from_dict({"schema": 1, "seeds": [SEED, SEED]})),
                   caught(lambda: ch.ChannelProfile.from_dict({**PROFILE, "language": "jp"})), caught(lambda: ch.profiles_from_dict({"schema": 1, "profiles": [PROFILE, PROFILE]})))
        for error in samples:
            text = str(error.slots.get("항목", ""))
            self.assertNotRegex(text, r"\[\s*'")
            self.assertNotIn("top_n", text)
            self.assertNotIn("['", text)


def worlds():
    A, B = ts.PROFILES["naver_a"], ts.PROFILES["naver_b"]

    def seed(**changes):
        return ts.example_seed(**{"seed_id": "s1", "keyword": "예시 로봇청소기", "major": "가전", "minor": "소형가전", **changes})

    entry = ts.example_entry(keywords=("예시 난방",), name="예시 난방 시기")
    return (
        gn.generate(A, [seed()], [], (), "2026-11-10", target=40), gn.generate(A, [seed(seed_type="priority", priority=True, excluded_keywords=("비용",))], [], (), "2026-11-10", target=100),
        gn.generate(A, [seed(seed_id="z1", keyword="예시 난방", seed_type="seasonal"), seed(seed_id="z2", keyword="예시 보일러", seed_type="seasonal")], [entry], (), "2026-11-10", target=100),
        gn.generate(A, [seed(seed_id="sp1", keyword="예시 호텔", major="여행", minor="숙박", seed_type="sponsorable", sponsor_tag="lodging_travel")], [], (), "2026-11-10", target=100),
        gn.generate(B, [seed(keyword="예시 로컬 AI", major="AI", minor="AI 서비스", seed_type="priority", priority=True)], [], (), "2026-11-10", target=100),
        gn.generate(A, [seed(keyword="예시 영양제", seed_type="priority", priority=True)], [], (), "2026-11-10", target=100),
        gn.generate(A, [seed(keyword="삼성 LG")], [], (), "2026-11-10", target=100), gn.generate(A, [seed(keyword="삼성", major="가", minor="없는 분류")], [], (), "2026-11-10", target=100),
        gn.generate(B, [seed(keyword="Gemini", major="가", minor="없는 분류")], [], (), "2026-11-10", target=100), gn.generate(ts.PROFILES["blogger_en"], [seed()], [], (), "2026-11-10", target=100),
        gn.generate(A, [], [], (), "2026-11-10", target=10),
    )


class GeneratedSentencesTest(unittest.TestCase):                                                               # M2
    def test_the_diagnosis_sentences_the_notes_and_the_selection_reasons_have_no_leak(self):
        count = 0
        for found in worlds():
            lines = [*found.notes, *(row.detail for row in found.dropped), *(reason for candidate in found.candidates for reason in candidate.selection_reasons)]
            for line in lines:
                count += 1
                self.assertEqual(leak(line, inside_quotes=False), [], line)
        self.assertGreater(count, 100)

    def test_the_expansion_blocked_reasons_for_every_seed_kind_have_no_leak(self):
        A, B = ts.PROFILES["naver_a"], ts.PROFILES["naver_b"]
        count = 0
        for kind in sd.SEED_TYPES:
            for profile in (A, B, ts.PROFILES["blogger_en"]):
                for minor in ("소형가전", "없는 분류", "숙박", "simple habits"):
                    opened = ex.expand(ts.example_seed(seed_type="sponsorable" if kind == "sponsorable" else kind, sponsor_tag="small_appliance" if kind == "sponsorable" else None, minor=minor, excluded_keywords=("비용",)), profile, limit=20)
                    for blocked in opened.blocked:
                        count += 1
                        self.assertEqual(leak(blocked.detail, inside_quotes=False), [], blocked.detail)
        self.assertGreater(count, 100)

    def test_the_writability_reasons_have_no_leak_for_every_kind_and_intent(self):
        for content_type in md.CONTENT_TYPES:
            for intent in md.SEARCH_INTENTS:
                for minimum in (4, 8, 10):
                    for line in fe.assess(content_type, intent, subheading_min=minimum).reasons:
                        self.assertEqual(leak(line), [], line)

    def test_the_issue_check_reasons_have_no_leak(self):
        issue = gn.RealtimeItem(channel="naver_a", topic="예시 새 소식이 나왔다", primary_keyword="예시 새 소식", topic_cluster="small-appliances", topic_angle="what-changed", search_intent="context_explainer",
                                content_type="news_analysis", first_reported_at="2026-11-09T00:00:00Z", sources=(gn.Source(url="https://a.example.org/x"),))
        for line in gn.check_realtime(issue, "2026-11-10T00:00:00Z").reasons:
            self.assertEqual(leak(line), [], line)

    def test_the_leak_check_itself_catches_what_it_should(self):
        for text in ("모르는 칸 ['zzz'], 빠진 칸 []", "같은 씨앗 번호가 두 번 들어 있다: ['s1']", "다음 중 하나여야 합니다: general, priority", "채널 naver_a 를 쓰세요", "언어 ko, en", "top_n 칸", "small-appliances 묶음",
                     "<b>x</b>", "NEW 상태"):
            with self.subTest(text=text):
                self.assertTrue(leak(text), text)
        for text in ("모르는 칸이 있습니다: ‘zzz’ · 빠진 칸이 있습니다: ‘채널당 후보 수’", "2026-11-10 기준", "다음 중 하나여야 합니다: ‘한국어’, ‘영어’"):
            with self.subTest(text=text):
                self.assertEqual(leak(text), [], text)


if __name__ == "__main__":
    unittest.main()
