"""특성 시험(P0) — 화면 어댑터·뷰모델과 '채널은 둘뿐' 가정·'주제 후보' 자리를 **현재 모습 그대로** 못박는다(계획 문서 `docs/TOPIC_ENGINE_PLAN.md` 의 G1·G4 화면 쪽·G5). PySide6 없이 돈다(네트워크·시크릿·실제 시계 없음).

왜: 5채널 주제 선정 전략을 얹기 전에, 지금 정상인 것이 뒤의 단계에서 소리 없이 바뀌지 않게 먼저 못박는다. 이 시험은 '옳다고 정한 것' 이 아니라 '지금 이렇다' 이다 — 바꾸려면 새 결정(D-nn)을 쓰고 해당 시험을 의식적으로 고친다.
현재 동작이 마음에 안 드는 것(알려진 결함)은 이름에 `KNOWN_DEFECT` 를 달아 두었고, 그것을 고치는 단계가 일부러 뒤집는다.
이미 있는 시험(`test_ui_adapters.py`·`test_ui_core.py`)과 겹치지 않게, 거기에 없는 경계·조합만 더한다 — 이미 있는 것: 우선도 라벨 낱개(`test_priority_labels`)·메뉴 여섯과 이름(`test_the_menu_has_exactly_six_entries_in_the_operator_order`)·
홈 카드 넷·행 다섯·칩 다섯의 이름(`test_home_view_has_four_cards_five_rows_and_five_chips`)·예시 데이터의 정렬(`test_the_home_list_is_ordered_by_priority_then_newest_with_hand_written_expectations`)·보류 제외(`test_held_topics_are_not_recommended_but_counted_as_saved_ideas`).
"""
import ast
import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import service_support as support  # noqa: E402
from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.ui import adapters  # noqa: E402
from chanceblog_desktop.ui.core import app_state, services, text  # noqa: E402

QT_DIR = ROOT / "src" / "chanceblog_desktop" / "ui" / "qt"
TODAY = datetime.date(2026, 11, 3)                  # 화면의 '오늘' 을 고정한다(`AppState(today=…)` — 실제 시계를 읽지 않는다)
STAMP = "2026-11-03T00:{minute:02d}:00Z"          # 후보마다 만든 시각을 1분씩 달리해 순서를 정한다(같은 날)


def cand(index, blogs=("naver_a",), **fields):
    """보관함에 넣을 후보 하나 — 번호·만든 시각을 index 로 정해 순서가 늘 같다(실제 시계 없음)."""
    return cd.Candidate.new(f"주제 {index:02d}", f"키워드{index:02d}", tuple(blogs), candidate_id=f"cand{index:04d}", now=STAMP.format(minute=index % 60), **fields)


def topic(name, blogs=("A",), **fields):
    return services.Topic(id=name, title=name, blogs=tuple(blogs), **fields)


def state_with(*topics):
    state = app_state.AppState(services.FakeHomeProvider(), today=TODAY)
    state.apply_home(services.HomeData(topics=tuple(topics)))
    return state


def called_name(call):
    """호출식의 이름 — `S.home_screen(…)` 이면 `home_screen`, `f(…)` 이면 `f`."""
    return call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")


def is_home_test(node, aliases=()):
    """`…page == "home"` 모양의 조건인가 — 지역 변수에 담아 쓴 것(`aliases`)도 같은 조건으로 본다. 공백·줄 바꿈·괄호·주석은 `ast` 가 이미 걸러 낸다."""
    if isinstance(node, ast.Name):
        return node.id in aliases
    return (isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq) and isinstance(node.left, ast.Attribute) and node.left.attr == "page"
            and len(node.comparators) == 1 and isinstance(node.comparators[0], ast.Constant) and node.comparators[0].value == "home")


def home_aliases(function):
    """홈 조건을 담아 두고 쓰는 지역 변수들 — 그 이름에 값을 넣는 곳이 **모두** 홈 조건일 때만 별칭이다. 같은 이름에 다른 값을 덮어쓰거나(`is_home = page == "settings"`)·조건부로 바꾸거나(`is_home = True`)·
    `+=`·`for`·`with`·`:=` 로 다시 넣으면 별칭이 아니다 — 처음에 홈 조건을 담았다는 이유만으로 '홈 조건' 으로 읽으면 곧바로 덮어쓴 억지 변이에 속는다(독립 검증이 찾은 허점 P10)."""
    stores, homes = {}, {}
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            stores[node.id] = stores.get(node.id, 0) + 1
        if isinstance(node, ast.Assign) and is_home_test(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    homes[target.id] = homes.get(target.id, 0) + 1
    return {name for name, count in homes.items() if stores.get(name) == count}


def home_branches(function, wanted):
    """함수 안에서 `wanted` 를 부르는 곳마다, 그 호출을 감싼 '홈 조건'의 가지를 돌려준다 — `참` = 홈일 때만 실행·`거짓` = 홈이 아닐 때만 실행·빈 집합 = 조건 없이 실행."""
    aliases = home_aliases(function)
    found = []

    def walk(node, branches):
        if isinstance(node, (ast.If, ast.IfExp)) and is_home_test(node.test, aliases):
            for child in (node.body if isinstance(node.body, list) else [node.body]):
                walk(child, branches | {"참"})
            for child in (node.orelse if isinstance(node.orelse, list) else [node.orelse]):
                walk(child, branches | {"거짓"})
            return
        if isinstance(node, ast.Call) and called_name(node) == wanted:
            found.append(branches)
        for child in ast.iter_child_nodes(node):
            walk(child, branches)

    for statement in function.body:
        walk(statement, frozenset())
    return found


def function_named(tree, name):
    found = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(found) == 1, f"함수 `{name}` 이 {len(found)}개다 — 화면 틀을 고쳤다면 이 시험을 의식적으로 고친다"
    return found[0]


def is_section_all(node):
    """`vm["section"]["all"]` — 홈 '전체 보기' 단추의 글."""
    return (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "all" and isinstance(node.value, ast.Subscript)
            and isinstance(node.value.slice, ast.Constant) and node.value.slice.value == "section")


def all_link_targets(tree):
    """`vm["section"]["all"]` 글의 단추를 눌렀을 때 `shell.go("…")` 로 가는 곳들."""
    buttons = {target.id for node in ast.walk(tree) if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and called_name(node.value) == "Button"
               and any(is_section_all(arg) for arg in node.value.args) for target in node.targets if isinstance(target, ast.Name)}
    targets = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and called_name(node) == "connect" and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "clicked"
                and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id in buttons):
            for arg in node.args:
                if isinstance(arg, ast.Lambda) and isinstance(arg.body, ast.Call) and called_name(arg.body) == "go" and arg.body.args and isinstance(arg.body.args[0], ast.Constant):
                    targets.append(arg.body.args[0].value)
    return targets


class ToTopicTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_priority_label_boundaries_reach_the_topic_through_to_topic(self):
        expected = ((None, ""), (0, "낮음"), (39, "낮음"), (39.9, "낮음"), (40, "보통"), (69, "보통"), (69.9, "보통"), (70, "높음"), (100, "높음"))
        for score, label in expected:
            with self.subTest(score=score):
                fields = {} if score is None else {"priority": float(score), "data_date": "2026-11-03"}      # 지표가 있으면 조회일이 있어야 한다
                self.assertEqual(adapters.to_topic(cand(1, **fields)).priority, label)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_label_is_the_candidates_own_priority_and_never_a_computed_score(self):
        # 후보에 사람이 적은(또는 CSV 로 가져온) 우선도가 없으면, 제안 점수를 계산할 수 있어도 라벨은 비어 있다 — 계산 점수는 홈에 오지 않는다.
        found = adapters.to_topic(cand(1, search_demand=100_000, trend="상승", data_date="2026-11-03"))
        self.assertEqual((found.priority, found.demand, found.trend), ("", 100_000, "up"))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_five_candidate_states_become_new_new_selected_hold_and_new(self):
        base = cand(1, ("naver_a", "naver_b"))
        moved = {
            cd.NEW: base,
            cd.REVIEW: base.moved(cd.REVIEW, now="2026-11-03T01:00:00Z"),
            cd.SELECTED: base.moved(cd.SELECTED, blog="naver_a", now="2026-11-03T01:00:00Z"),
            cd.HOLD: base.moved(cd.HOLD, now="2026-11-03T01:00:00Z"),
            cd.REJECTED: base.moved(cd.REJECTED, now="2026-11-03T01:00:00Z"),
        }
        self.assertEqual(list(moved), [cd.NEW, cd.REVIEW, cd.SELECTED, cd.HOLD, cd.REJECTED])
        self.assertEqual({state: adapters.to_topic(item).status for state, item in moved.items()},
                         {cd.NEW: "new", cd.REVIEW: "new", cd.SELECTED: "selected", cd.HOLD: "hold", cd.REJECTED: "new"})
        self.assertEqual(adapters.STATUS, {cd.NEW: "new", cd.REVIEW: "new", cd.SELECTED: "selected", cd.HOLD: "hold"})

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    # KNOWN_DEFECT: 제외(REJECTED)한 후보는 표에 없어 '새 후보(new)' 로 바뀐다 — 홈에서 안 보이는 것은 `load_home` 이 먼저 거르기 때문일 뿐이다. 거르는 곳이 바뀌면 이 시험이 알린다.
    def test_KNOWN_DEFECT_a_rejected_candidate_is_filtered_by_load_home_not_by_the_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            with ctx.store() as store:
                store.add_candidates(lambda existing: [cand(1), cand(2)])
                store.set_candidate_status("cand0002", cd.REJECTED, now="2026-11-03T01:00:00Z")
            data = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx).load_home(lambda *a: None, lambda: False)
        self.assertEqual([item.title for item in data.topics], ["주제 01"])
        rejected = cand(2).moved(cd.REJECTED, now="2026-11-03T01:00:00Z")
        self.assertEqual(adapters.to_topic(rejected).status, "new")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_to_topic_keeps_only_the_two_naver_blogs_in_a_then_b_order(self):
        expected = {
            ("naver_a",): ("A",), ("naver_b",): ("B",), ("naver_a", "naver_b"): ("A", "B"),
            ("github_pages",): (), ("blogger_en",): (), ("blogger_ko",): (), ("blogger_en", "blogger_ko"): (),
            ("github_pages", "naver_b"): ("B",), ("blogger_ko", "naver_a"): ("A",),
            ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"): ("A", "B"),
        }
        for blogs, shown in expected.items():
            with self.subTest(blogs=blogs):
                self.assertEqual(adapters.to_topic(cand(1, blogs)).blogs, shown)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_icons_cycle_by_position_keywords_are_cut_and_the_date_falls_back_to_the_creation_day(self):
        self.assertEqual(len(adapters.ICONS), 6)
        for index in range(8):
            self.assertEqual((adapters.to_topic(cand(1), index).icon, adapters.to_topic(cand(1), index).tone), adapters.ICONS[index % 6], index)
        many = cand(1, sub_keywords=("보조 하나", "보조 둘", "보조 셋"))
        self.assertEqual(adapters.to_topic(many).keywords, ("키워드01", "보조 하나", "보조 둘"))          # 핵심 키워드 + 보조 키워드 앞의 둘
        self.assertEqual(adapters.to_topic(cand(1)).desc, "키워드01")                                      # 추천 이유가 없으면 핵심 키워드
        self.assertEqual(adapters.to_topic(cand(1, reason="이유 한 줄")).desc, "이유 한 줄")
        self.assertEqual(adapters.to_topic(cand(1)).date, "2026-11-03")                                    # 조회일이 없으면 만든 날
        self.assertEqual(adapters.to_topic(cand(1, search_demand=5, data_date="2026-10-20")).date, "2026-10-20")
        late = cd.Candidate.new("늦은 밤 주제", "늦은 밤 키워드", ("naver_a",), candidate_id="late0001", now="2026-11-02T23:30:00Z")
        self.assertEqual(adapters.to_topic(late).date, "2026-11-02", "만든 날은 UTC 날짜 앞 10자다(한국 시간으로는 11월 3일 아침)")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_three_trend_words_become_up_flat_and_down_and_no_trend_stays_empty(self):
        self.assertEqual(adapters.TREND, {"상승": "up", "보합": "flat", "하락": "down"})
        for word, code in (("상승", "up"), ("보합", "flat"), ("하락", "down"), (None, None)):
            with self.subTest(word=word):
                fields = {} if word is None else {"trend": word, "data_date": "2026-11-03"}
                self.assertEqual(adapters.to_topic(cand(1, **fields)).trend, code)
        self.assertEqual(app_state.TREND_ICON, {"up": "trend_up", "flat": "trend_flat", "down": "trend_down"})
        self.assertEqual([app_state.trend_vm(topic("행", trend=code))["label"] for code in ("up", "flat", "down", None)], ["상승", "보통", "하락", "데이터 없음"])


class LoadHomeScenarioTest(unittest.TestCase):
    CHANNELS = {"A만": ("naver_a",), "B만": ("naver_b",), "둘 다": ("naver_a", "naver_b")}

    def load(self, candidates):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            if candidates:
                with ctx.store() as store:
                    store.add_candidates(lambda existing: list(candidates))
            data = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx).load_home(lambda *a: None, lambda: False)
        return data

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_home_data_and_the_home_view_for_zero_one_five_six_and_fifty_candidates_in_each_channel_mix(self):
        for count in (0, 1, 5, 6, 50):
            for label, blogs in self.CHANNELS.items():
                with self.subTest(count=count, channels=label):
                    data = self.load([cand(number, blogs) for number in range(1, count + 1)])
                    self.assertEqual(len(data.topics), count)
                    in_a, in_b = ("naver_a" in blogs) * count, ("naver_b" in blogs) * count
                    self.assertEqual([(blog.key, blog.name, blog.candidates) for blog in data.blogs], [("A", "블로그 A", in_a), ("B", "블로그 B", in_b)])
                    self.assertEqual((data.done, data.pub, data.sample, data.offline, data.partial), (0, 0, False, False, ()))
                    state = app_state.AppState(adapters.ServiceHomeProvider(), today=TODAY)
                    state.apply_home(data)
                    view = state.home_view()
                    self.assertEqual(view["state"], "empty" if count == 0 else "normal")
                    self.assertEqual(len(view["rows"]), min(count, 5))
                    self.assertEqual([chip["count"] for chip in view["chips"]], [count, in_a, in_b, 0, count])      # 전체·A·B·급상승(추세 자료 없음)·신규(전부 새 후보)
                    self.assertEqual(view["cards"][0]["value"], f"{count}개")
                    self.assertEqual(view["cards"][3]["value"], "0개")
                    self.assertEqual(view["selected"], None if count == 0 else "cand0001")
                    self.assertEqual([row["title"] for row in view["rows"]], [f"주제 {number:02d}" for number in range(1, min(count, 5) + 1)])      # 동률이면 먼저 만든 후보가 위

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_candidates_for_channels_other_than_naver_show_under_all_only_and_in_no_blog_count(self):
        data = self.load([cand(1, ("github_pages",)), cand(2, ("blogger_en", "blogger_ko")), cand(3, ("naver_a",)), cand(4, ("github_pages", "naver_b"))])
        self.assertEqual([item.blogs for item in data.topics], [(), (), ("A",), ("B",)])
        self.assertEqual([(blog.key, blog.candidates) for blog in data.blogs], [("A", 1), ("B", 1)])
        state = app_state.AppState(adapters.ServiceHomeProvider(), today=TODAY)
        state.apply_home(data)
        view = state.home_view()
        self.assertEqual([chip["count"] for chip in view["chips"]], [4, 1, 1, 0, 4])
        self.assertEqual([row["blog_label"] for row in view["rows"]], ["", "", "블로그 A", "블로그 B"])      # 네이버가 아닌 채널의 후보는 블로그 배지가 없다
        state.set_home_filter("a")
        self.assertEqual([row["title"] for row in state.home_view()["rows"]], ["주제 03"])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_held_candidates_are_saved_ideas_and_do_not_count_toward_a_blogs_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            with ctx.store() as store:
                store.add_candidates(lambda existing: [cand(1), cand(2), cand(3, ("naver_a", "naver_b"))])
                store.set_candidate_status("cand0002", cd.HOLD, now="2026-11-03T01:00:00Z")
            data = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx).load_home(lambda *a: None, lambda: False)
        self.assertEqual([(item.title, item.status) for item in data.topics], [("주제 01", "new"), ("주제 02", "hold"), ("주제 03", "new")])
        self.assertEqual([(blog.key, blog.candidates) for blog in data.blogs], [("A", 2), ("B", 1)])         # 보류한 것은 센 수에서 빠진다
        state = app_state.AppState(adapters.ServiceHomeProvider(), today=TODAY)
        state.apply_home(data)
        view = state.home_view()
        self.assertEqual([card["value"] for card in view["cards"]], ["2개", "0개", "0개", "1개"])
        self.assertEqual([row["title"] for row in view["rows"]], ["주제 01", "주제 03"])


class HomeViewTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_rows_stop_at_five_but_the_chips_and_the_card_count_every_live_topic(self):
        state = state_with(*[topic(f"주제{number}", priority="높음", date=f"2026-11-{number:02d}") for number in range(1, 9)])
        view = state.home_view()
        self.assertEqual(len(view["rows"]), app_state.HOME_ROWS)
        self.assertEqual([row["title"] for row in view["rows"]], ["주제8", "주제7", "주제6", "주제5", "주제4"])      # 같은 우선도면 최신 날짜 먼저
        self.assertEqual((view["chips"][0]["count"], view["cards"][0]["value"]), (8, "8개"))
        self.assertEqual(view["selected"], "주제8")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_chip_counts_follow_the_blog_trend_and_status_of_each_live_topic_and_never_count_held_ones(self):
        state = state_with(
            topic("에이만", ("A",), trend="up"), topic("비만", ("B",)), topic("둘 다", ("A", "B"), trend="up", status="selected"), topic("블로그 없음", ()),
            topic("보류 급상승", ("A", "B"), trend="up", status="hold"), topic("하락", ("A",), trend="down"), topic("보합", ("B",), trend="flat"))
        view = state.home_view()
        self.assertEqual([(chip["key"], chip["count"]) for chip in view["chips"]], [("all", 6), ("a", 3), ("b", 3), ("hot", 2), ("new", 5)])      # 보류는 모두에서 빠지고, '급상승' 은 상승만, '신규' 에는 선택한 것도 빠진다
        self.assertEqual([chip["active"] for chip in view["chips"]], [True, False, False, False, False])
        self.assertEqual((view["cards"][0]["value"], view["cards"][3]["value"]), ("6개", "1개"))             # 추천 주제 6(보류 뺀 수)·저장된 아이디어 1(보류한 수)
        state.set_home_filter("hot")
        self.assertEqual(sorted(row["title"] for row in state.home_view()["rows"]), ["둘 다", "에이만"])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_equal_priority_and_date_keep_the_input_order_and_an_unknown_priority_comes_last(self):
        state = state_with(topic("셋", priority="보통", date="2026-11-01"), topic("하나", priority="보통", date="2026-11-01"), topic("둘", priority="보통", date="2026-11-01"),
                           topic("라벨 모름", priority="최우선", date="2026-11-05"), topic("낮음", priority="낮음", date="2026-11-01"))
        self.assertEqual([row["title"] for row in state.home_view()["rows"]], ["셋", "하나", "둘", "낮음", "라벨 모름"])      # 입력 순서 그대로, 모르는 라벨은 낮음 뒤

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_chip_with_no_rows_leaves_nothing_selected_and_the_all_chip_restores_the_first_row(self):
        state = state_with(topic("하나", ("A",), priority="높음"), topic("둘", ("A",), priority="보통"))
        self.assertTrue(state.set_home_filter("b"))
        self.assertEqual((state.selected, state.home_view()["rows"], state.home_view()["selected"]), (None, [], None))
        self.assertTrue(state.set_home_filter("all"))
        self.assertEqual((state.selected, state.home_view()["selected"]), ("하나", "하나"))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_home_filter_decides_among_all_live_topics_before_the_five_row_cut(self):
        state = state_with(*[topic(f"에이{number}", ("A",), priority="높음", date=f"2026-11-0{number}") for number in range(1, 6)],
                           topic("비 하나", ("B",), priority="낮음", date="2026-10-01"))
        self.assertEqual(len(state.home_view()["rows"]), 5)
        self.assertNotIn("비 하나", [row["title"] for row in state.home_view()["rows"]])                    # 전체에서는 여섯째라 잘린다
        state.set_home_filter("b")
        self.assertEqual([row["title"] for row in state.home_view()["rows"]], ["비 하나"])                    # 칩으로 거르면 보인다

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_loading_new_data_puts_the_chip_back_to_all_and_selects_the_first_live_row(self):
        state = state_with(topic("에이", ("A",), priority="높음"), topic("비", ("B",), priority="보통"))
        self.assertTrue(state.set_home_filter("b"))
        self.assertEqual((state.home_filter, state.selected), ("b", "비"))
        state.apply_home(services.HomeData(topics=(topic("새 에이", ("A",), priority="높음"), topic("새 비", ("B",), priority="보통"))))
        self.assertEqual((state.home_filter, state.selected), ("all", "새 에이"))
        self.assertEqual([chip["active"] for chip in state.home_view()["chips"]], [True, False, False, False, False])


class ChannelTwoAssumptionTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_blog_tables_hold_exactly_the_two_naver_blogs_and_nothing_else(self):
        self.assertEqual(adapters.BLOG_KEYS, {"naver_a": "A", "naver_b": "B"})
        self.assertEqual(list(adapters.BLOG_KEYS), ["naver_a", "naver_b"])
        self.assertEqual(app_state.BLOG_NAMES, {"A": "블로그 A", "B": "블로그 B"})
        self.assertEqual(set(adapters.BLOG_KEYS.values()), set(app_state.BLOG_NAMES))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_home_chips_are_five_in_this_order_and_only_a_and_b_name_a_blog(self):
        self.assertEqual(app_state.HOME_CHIPS, (("all", "chip_all"), ("a", "chip_a"), ("b", "chip_b"), ("hot", "chip_hot"), ("new", "chip_new")))
        self.assertEqual([text.T[label] for _key, label in app_state.HOME_CHIPS], ["전체", "블로그 A", "블로그 B", "트렌드 급상승", "신규 키워드"])
        self.assertEqual(app_state.HOME_ROWS, 5)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_blog_key_outside_a_and_b_gets_no_badge_in_the_view_model(self):
        shown = app_state.topic_vm(topic("낯선 키", ("A", "C", "B", "github_pages")))
        self.assertEqual([item["key"] for item in shown["blogs"]], ["A", "B"])
        self.assertEqual((shown["blog"], shown["blog_label"]), ("A", "블로그 A"))
        none = app_state.topic_vm(topic("배지 없음", ("C",)))
        self.assertEqual((none["blogs"], none["blog"], none["blog_label"]), ([], "", ""))
        self.assertIn("블로그 미정", none["a11y"])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_provider_always_reports_blogs_a_and_b_even_when_there_is_no_data_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            data = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx).load_home(lambda *a: None, lambda: False)
        self.assertEqual((data.topics, [(blog.key, blog.name, blog.candidates) for blog in data.blogs]), ((), [("A", "블로그 A", 0), ("B", "블로그 B", 0)]))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_only_naver_profiles_can_rename_a_blog_and_other_keys_in_the_settings_are_ignored(self):
        def names(raw):
            ctx = SimpleNamespace(settings=SimpleNamespace(naver_profile_dicts=lambda: raw))
            return adapters.ServiceHomeProvider()._names(ctx)                                  # 비공개 이름 — 바뀌면 이 시험을 고친다

        self.assertEqual(names({}), {"A": "블로그 A", "B": "블로그 B"})
        self.assertEqual(names({"naver_a": {"display_name": "에이 이름"}, "naver_b": {"display_name": "비 이름"}}), {"A": "에이 이름", "B": "비 이름"})
        self.assertEqual(names({"github_pages": {"display_name": "깃허브"}, "blogger_ko": {"display_name": "블로거"}}), {"A": "블로그 A", "B": "블로그 B"})
        self.assertEqual(names({"naver_a": {"display_name": "   "}, "naver_b": {"display_name": 5}}), {"A": "블로그 A", "B": "블로그 B"})


class TopicsPlaceholderTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_menu_keys_and_icons_put_topics_second_and_the_label_says_topic_candidates(self):
        self.assertEqual([key for key, _label, _icon in app_state.NAV], ["home", "topics", "draft", "history", "blogs", "settings"])
        self.assertEqual([icon for _key, _label, icon in app_state.NAV], ["home", "search", "draft", "history", "blogs", "settings"])
        self.assertEqual(text.T["nav_topics"], "주제 후보")
        self.assertEqual(app_state.MAX_NAV, 6)

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_home_cards_for_recommended_topics_and_saved_ideas_go_to_topics_and_the_others_go_nowhere(self):
        cards = {card["key"]: card for card in state_with(topic("하나")).home_view()["cards"]}
        self.assertEqual({key: card["go"] for key, card in cards.items()}, {"topics": "topics", "done": None, "pub": None, "ideas": "topics"})
        self.assertIn(app_state.NAV[1][0], {card["go"] for card in cards.values()})
        self.assertEqual(state_with(topic("하나")).home_view()["section"]["all"], "전체 보기")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_quick_actions_that_move_go_to_topics_history_and_blogs_and_the_rest_only_say_soon(self):
        for key, page in (("saved", "topics"), ("history", "history"), ("blogs", "blogs")):
            state = state_with(topic("하나"))
            with self.subTest(key=key):
                self.assertEqual((state.quick(key), state.page), ("", page))
        state = state_with(topic("하나"))
        self.assertEqual((state.quick("new"), state.page), (text.T["soon_toast"].format(name=text.T["q_new"]), "home"))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_every_screen_but_home_shows_the_same_placeholder_text_with_its_own_name(self):
        for key, label, _icon in app_state.NAV[1:]:
            state = state_with(topic("하나"))
            self.assertTrue(state.nav(key))
            with self.subTest(key=key):
                self.assertEqual(state.page_view(), {"key": key, "name": text.T[label], "title": "이 화면은 아직 만들고 있어요.",
                                                    "desc": "다음 단계에서 이어서 만들어요. 지금은 홈에서 주제 추천을 볼 수 있어요.", "button": "홈으로"})
        state = state_with(topic("하나"))
        self.assertTrue(state.nav("topics"))
        self.assertFalse(state.nav("topics"))                                                                  # 지금 화면으로는 다시 가지 않는다
        self.assertTrue(state.nav("home"))

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_leaving_home_closes_the_drawer_and_a_drawer_opened_on_another_page_is_only_a_view_model_fact(self):
        state = state_with(topic("하나", priority="높음"))
        self.assertTrue(state.open_drawer("하나"))
        self.assertIsNotNone(state.drawer_view())
        self.assertTrue(state.nav("topics"))
        self.assertEqual((state.drawer_id, state.drawer_view()), (None, None))
        self.assertTrue(state.open_drawer("하나"))                                                            # 뷰모델은 어느 화면에서든 연다 — '홈에서만' 은 아래의 Qt 틀이 정한다
        self.assertIsNotNone(state.drawer_view())

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_qt_shell_source_picks_home_or_the_placeholder_and_shows_the_drawer_on_home_only(self):
        # Qt 를 불러오지 않고 소스를 `ast` 로 읽는다(순수 뷰모델에는 '어느 화면을 그릴지' 가 없다) — 글자 모양이 아니라 규칙을 본다: 조건을 변수에 담거나 줄을 바꾸거나 주석을 달아도
        # 같은 규칙이면 통과하고, 서랍이 홈 밖에서도 보이거나 홈 조건이 사라지면 옛 줄을 주석으로 남겨도 깨진다. 다음 묶음(P4)이 화면 표로 바꿀 때 이 시험을 의식적으로 고친다.
        shell = ast.parse((QT_DIR / "shell.py").read_text(encoding="utf-8"))
        screens = ast.parse((QT_DIR / "screens.py").read_text(encoding="utf-8"))
        render, overlays = function_named(shell, "render"), function_named(shell, "_sync_overlays")
        self.assertEqual(home_branches(render, "home_screen"), [frozenset({"참"})], "홈 화면은 홈일 때만 그린다")
        self.assertEqual(home_branches(render, "placeholder_screen"), [frozenset({"거짓"})], "자리표시 화면은 홈이 아닐 때만 그린다")
        self.assertEqual(home_branches(overlays, "drawer_view"), [frozenset({"참"})], "서랍은 홈에서만 연다")
        self.assertEqual(all_link_targets(screens), ["topics"], "홈의 '전체 보기' 는 '주제 후보' 로 간다")


class HomeConditionReaderTest(unittest.TestCase):
    """위 Qt 소스 시험이 쓰는 `ast` 읽개 자체의 시험 — 홈 조건을 변수에 담아 쓴 것은 같은 조건으로 읽되, 그 변수를 다른 값으로 덮어쓴 소스는 홈 조건으로 읽지 않는다(그러면 Qt 소스 시험이 깨진다)."""

    @staticmethod
    def source(*lines):
        """함수 `f` 하나짜리 소스 — 줄마다 들여 써서 붙인다."""
        return "\n".join(("def f(self):", *("    " + line for line in lines))) + "\n"

    def branches(self, *lines):
        return home_branches(function_named(ast.parse(self.source(*lines)), "f"), "drawer")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_home_condition_kept_in_a_variable_and_used_once_is_read_as_the_home_condition(self):
        direct = ('view = self.drawer() if self.state.page == "home" else None',)
        kept = ('is_home = self.state.page == "home"', "view = self.drawer() if is_home else None")
        commented = ("# view = self.drawer()", 'is_home = (self.state.page ==', '           "home")  # 줄을 바꿔도 주석을 달아도', "view = self.drawer() if is_home else None")
        for lines in (direct, kept, commented):
            with self.subTest(lines=lines):
                self.assertEqual(self.branches(*lines), [frozenset({"참"})])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_a_home_condition_variable_that_is_overwritten_is_not_read_as_the_home_condition(self):
        overwritten = ('is_home = self.state.page == "home"', 'is_home = self.state.page == "settings"', "view = self.drawer() if is_home else None")
        by_a_flag = ('is_home = self.state.page == "home"', "if self.flag:", "    is_home = True", "view = self.drawer() if is_home else None")
        augmented = ('is_home = self.state.page == "home"', "is_home |= self.flag", "view = self.drawer() if is_home else None")
        looped = ('is_home = self.state.page == "home"', "for is_home in (True, False):", "    pass", "view = self.drawer() if is_home else None")
        for lines in (overwritten, by_a_flag, augmented, looped):
            with self.subTest(lines=lines):
                self.assertEqual(self.branches(*lines), [frozenset()], "홈 조건이 아닌 변수를 홈 조건으로 읽었다")
        self.assertEqual(home_aliases(function_named(ast.parse(self.source(*overwritten)), "f")), set())


class LegacyDemandLabelTest(unittest.TestCase):
    """기존 절대 횟수 칸(`Candidate.search_demand`)의 화면 이름·단위를 못박는다 — 운영자 조건 1 은 이 칸을 상대지수로 덮어쓰거나 **재해석(재라벨)하지 않는다**. 이 시험이 없으면 '월 검색량' 을 '최근 관심도(상대값)' 로 바꿔도 소리 없이 통과한다."""
    LEGACY_KEYS = ("demand", "d_demand", "unit_demand", "tip_demand")

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_legacy_absolute_count_is_called_monthly_search_volume_and_counted_in_times_in_the_screen_text(self):
        T = text.T
        self.assertEqual((T["demand"], T["d_demand"], T["unit_demand"]), ("월 검색량", "월간 검색량", "회"))                         # 행의 지표 이름·서랍의 항목 이름·단위
        self.assertEqual(T["tip_demand"], "한 달 동안 이 키워드가 검색된 횟수를 어림잡은 값이에요.")                                     # 툴팁은 절대 횟수로 설명한다
        self.assertEqual((T["docs"], T["d_docs"], T["unit_docs"]), ("블로그 문서 수", "관련 블로그 검색 결과 수", "건"))               # 같은 Legacy 지표 묶음의 다른 칸
        self.assertEqual([text.fmt_demand(value) for value in (None, 0, 87, 8600, 1_234_567)], ["데이터 없음", "0회", "87회", "8,600회", "1,234,567회"])
        self.assertEqual([text.fmt_docs(value) for value in (None, 0, 4120)], ["데이터 없음", "0건", "4,120건"])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_none_of_the_legacy_count_labels_borrows_the_relative_interest_wording(self):
        # 새 Trend 칸의 이름 `최근 관심도(상대값)` 는 P4 가 새 문구로 더한다. 기존 절대 횟수 칸의 문구에는 어느 단계에서도 상대값·관심도·지수·트렌드가 들어가면 안 된다(재라벨 금지).
        for key in self.LEGACY_KEYS:
            for word in ("상대", "관심도", "지수", "트렌드", "Trend", "ratio"):
                with self.subTest(key=key, word=word):
                    self.assertNotIn(word, text.T[key])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_screen_text_has_no_relative_interest_label_yet_so_p4_adds_it_as_a_new_key(self):
        # P4 가 새 Trend 문구 `최근 관심도(상대값)` 를 **새 키**로 더하면 이 시험의 빈 목록을 의식적으로 고친다 — 더해도 위 시험이 지키는 네 개 키에는 들어가면 안 된다.
        # 보는 것은 '상대값' 낱말뿐이라, 기존 추세 항목 이름(`d_trend` 의 '최근 트렌드')이 나중에 '최근 관심도 변화' 처럼 바뀌어도 이 시험은 깨지지 않는다.
        self.assertEqual([key for key, value in text.T.items() if "상대값" in value], [])

    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_row_and_the_drawer_show_the_legacy_count_with_the_times_unit_and_the_monthly_label(self):
        row = app_state.topic_vm(topic("행", demand=8600, docs=4120))
        self.assertEqual((row["demand"], row["docs"], row["demand_missing"], row["docs_missing"]), ("8,600회", "4,120건", False, False))
        bare = app_state.topic_vm(topic("빈 행"))
        self.assertEqual((bare["demand"], bare["docs"], bare["demand_missing"], bare["docs_missing"]), ("데이터 없음", "데이터 없음", True, True))
        state = state_with(topic("행", demand=8600, docs=4120))
        self.assertTrue(state.open_drawer("행"))
        fields = state.drawer_view()["fields"]
        self.assertEqual((fields[0]["label"], fields[0]["value"], fields[0]["missing"]), ("월간 검색량", "8,600회", False))        # 서랍의 첫 항목
        shown = {field["label"]: field["value"] for field in fields}
        self.assertEqual((shown["월간 검색량"], shown["관련 블로그 검색 결과 수"]), ("8,600회", "4,120건"))
        self.assertNotIn("상대값", " ".join(shown))                                                                          # 서랍 항목 이름 어디에도 상대값 이름은 없다(기존 추세 항목 `최근 트렌드` 이름 변경은 상관없다)


if __name__ == "__main__":
    unittest.main()
