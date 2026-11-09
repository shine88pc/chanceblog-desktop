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
STAMP = "2026-11-03T00:{minute:02d}:00Z"          # 후보마다 만든 시각을 1분씩 달리해 순서를 정한다(같은 날)


def cand(index, blogs=("naver_a",), **fields):
    """보관함에 넣을 후보 하나 — 번호·만든 시각을 index 로 정해 순서가 늘 같다(실제 시계 없음)."""
    return cd.Candidate.new(f"주제 {index:02d}", f"키워드{index:02d}", tuple(blogs), candidate_id=f"cand{index:04d}", now=STAMP.format(minute=index % 60), **fields)


def topic(name, blogs=("A",), **fields):
    return services.Topic(id=name, title=name, blogs=tuple(blogs), **fields)


def state_with(*topics):
    state = app_state.AppState(services.FakeHomeProvider())
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


def builder_table(tree, name="SCREEN_BUILDERS"):
    """`screens.py` 의 '메뉴 → 화면 만드는 함수' 표 — 모듈 맨 위의 `SCREEN_BUILDERS = {"메뉴 열쇠": 함수 이름, …}` 를 `ast` 로 읽어 {열쇠: 함수 이름}. 표가 없거나 줄 모양이 다르면 그 자리에서 실패한다."""
    found = [node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    assert len(found) == 1 and isinstance(found[0].value, ast.Dict), f"`{name}` 표가 모듈 맨 위에 하나 있어야 한다 — 화면 틀을 고쳤다면 이 시험을 의식적으로 고친다"
    table = {}
    for key, value in zip(found[0].value.keys, found[0].value.values, strict=True):
        assert isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(value, ast.Name), "표의 줄은 '메뉴 열쇠': 함수 이름 이어야 한다"
        assert key.value not in table, f"메뉴 `{key.value}` 가 두 번 나온다"
        table[key.value] = value.id
    return table


def calls_in(function):
    """함수 안에서 부르는 것들의 이름(`S.home_screen(…)` 이면 `home_screen`)."""
    return [called_name(node) for node in ast.walk(function) if isinstance(node, ast.Call)]


def viewmodel_of(function, screen):
    """화면 만드는 함수가 `screen(shell, shell.state.<뷰모델>())` 꼴로 화면 함수에 넘기는 뷰모델 만드는 이름(`home_view` 등). 꼴이 다르면 그 자리에서 실패한다."""
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call) and called_name(node) == screen]
    assert len(calls) == 1 and len(calls[0].args) == 2, f"`{screen}` 은 `{screen}(shell, 뷰모델)` 꼴로 한 번만 불려야 한다 — 화면 틀을 고쳤다면 이 시험을 의식적으로 고친다"
    view = calls[0].args[1]
    assert isinstance(view, ast.Call) and isinstance(view.func, ast.Attribute), "뷰모델은 `shell.state.<이름>()` 으로 만들어 넘긴다"
    owner = view.func.value
    assert isinstance(owner, ast.Attribute) and owner.attr == "state" and isinstance(owner.value, ast.Name) and owner.value.id == "shell", "뷰모델은 이 창의 상태(`shell.state`)에서 온다"
    return view.func.attr


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

    def test_home_data_and_the_home_view_for_zero_one_five_six_and_fifty_candidates_in_each_channel_mix(self):
        """의도적 갱신(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 2·5): 옛 시험은 옛 후보 저장소의 후보가 홈의 추천 행(최대 5)·칩 다섯·요약 카드에 어떻게 나타나는지 못박았다. 새 홈은 추천을 **주제 엔진 후보**에서 읽고
        옛 후보 저장소의 후보는 홈에 행으로 나오지 않는다(옛 행·칩·카드가 없어졌다). 어댑터가 읽는 값(`data`)은 그대로 못박고, 홈 뷰모델에서는 KPI(작성·발행 0, 저장된 아이디어 0 — 보류 없음, 추천 주제는 엔진 보관함이 없어 `연결 전`)와
        '옛 후보의 제목이 홈 뷰모델에 나오지 않는다' 를 같은 시나리오마다 본다."""
        for count in (0, 1, 5, 6, 50):
            for label, blogs in self.CHANNELS.items():
                with self.subTest(count=count, channels=label):
                    data = self.load([cand(number, blogs) for number in range(1, count + 1)])
                    self.assertEqual(len(data.topics), count)
                    in_a, in_b = ("naver_a" in blogs) * count, ("naver_b" in blogs) * count
                    self.assertEqual([(blog.key, blog.name, blog.candidates) for blog in data.blogs], [("A", "블로그 A", in_a), ("B", "블로그 B", in_b)])
                    self.assertEqual((data.done, data.pub, data.sample, data.offline, data.partial), (0, 0, False, False, ()))
                    state = app_state.AppState(adapters.ServiceHomeProvider())
                    state.apply_home(data)
                    view = state.home_view()
                    self.assertEqual(view["state"], "empty" if count == 0 else "normal")
                    kpi = {item["key"]: item["text"] for item in view["board"]["kpi"]}
                    self.assertEqual((kpi["topics"], kpi["done"], kpi["pub"], kpi["ideas"]), ("연결 전", "0개", "0개", "0개"))
                    self.assertEqual(view["board"]["state"], "ready")
                    self.assertEqual([item["state"] for item in view["board"]["recommend"]], ["empty", "empty"])              # 엔진 보관함이 없으면 정상 빈 상태(쓰기 단추 없음)
                    self.assertNotIn("주제 01", repr(view))                                                                     # 옛 후보 저장소의 후보는 홈에 나오지 않는다
    def test_candidates_for_channels_other_than_naver_show_under_all_only_and_in_no_blog_count(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험의 데이터 쪽(후보의 블로그 열쇠·블로그별 후보 수)은 그대로 못박는다. 칩 수·행의 블로그 배지·칩 거르기(옛 추천 목록)는 홈에서 없어져 뺐다 —
        네이버가 아닌 채널의 후보에 블로그 배지가 없다는 규칙은 상세 서랍으로 옮겨 본다(서랍의 블로그 라벨·초안 단추)."""
        data = self.load([cand(1, ("github_pages",)), cand(2, ("blogger_en", "blogger_ko")), cand(3, ("naver_a",)), cand(4, ("github_pages", "naver_b"))])
        self.assertEqual([item.blogs for item in data.topics], [(), (), ("A",), ("B",)])
        self.assertEqual([(blog.key, blog.candidates) for blog in data.blogs], [("A", 1), ("B", 1)])
        state = app_state.AppState(adapters.ServiceHomeProvider())
        state.apply_home(data)
        labels = []
        for item in data.topics:
            state.open_drawer(item.id)
            labels.append((state.drawer_view()["blog_label"], [button["key"] for button in state.drawer_view()["drafts"]]))
        self.assertEqual(labels, [("", []), ("", []), ("블로그 A", ["A"]), ("블로그 B", ["B"])])                              # 네이버가 아닌 채널의 후보는 블로그 배지·초안 단추가 없다
    def test_held_candidates_are_saved_ideas_and_do_not_count_toward_a_blogs_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = support.make_ctx(tmp)
            with ctx.store() as store:
                store.add_candidates(lambda existing: [cand(1), cand(2), cand(3, ("naver_a", "naver_b"))])
                store.set_candidate_status("cand0002", cd.HOLD, now="2026-11-03T01:00:00Z")
            data = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: ctx).load_home(lambda *a: None, lambda: False)
        self.assertEqual([(item.title, item.status) for item in data.topics], [("주제 01", "new"), ("주제 02", "hold"), ("주제 03", "new")])
        self.assertEqual([(blog.key, blog.candidates) for blog in data.blogs], [("A", 2), ("B", 1)])         # 보류한 것은 센 수에서 빠진다
        state = app_state.AppState(adapters.ServiceHomeProvider())
        state.apply_home(data)
        view = state.home_view()
        kpi = {item["key"]: item["text"] for item in view["board"]["kpi"]}
        self.assertEqual((kpi["topics"], kpi["done"], kpi["pub"], kpi["ideas"]), ("연결 전", "0개", "0개", "1개"))      # 의도적 갱신(UI-C1d, D-201): 옛 요약 카드(`cards`)가 KPI 로 — 보류 1개는 저장된 아이디어
        self.assertNotIn("주제 01", repr(view))                                                                 # 옛 추천 행이 없어져 옛 후보의 제목은 홈에 나오지 않는다


class HomeViewTest(unittest.TestCase):
    """의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5): 옛 `HomeViewTest` 의 여섯 시험(`test_rows_stop_at_five_but_the_chips_and_the_card_count_every_live_topic` ·
    `test_chip_counts_follow_the_blog_trend_and_status_of_each_live_topic_and_never_count_held_ones` · `test_equal_priority_and_date_keep_the_input_order_and_an_unknown_priority_comes_last` ·
    `test_a_chip_with_no_rows_leaves_nothing_selected_and_the_all_chip_restores_the_first_row` · `test_the_home_filter_decides_among_all_live_topics_before_the_five_row_cut` ·
    `test_loading_new_data_puts_the_chip_back_to_all_and_selects_the_first_live_row`)은 옛 추천 목록의 5줄 한도·칩 수·정렬·칩 거르기·선택을 못박았다. 그 목록(칩·선택·옛 후보 행)이 홈에서 없어졌으므로(추천은 이제 주제 엔진 후보 —
    Naver A·B 각 최대 5) 같은 자리에 **새 홈에서 같은 질문**의 답을 못박는다: 줄 수 한도·순서·보류의 셈·새 데이터가 오면 서랍이 어떻게 되는지."""

    @staticmethod
    def board_state(*channels, **fields):
        state = app_state.AppState(services.FakeHomeProvider())
        state.apply_home(services.HomeData(board=services.BoardData(tuple(channels), services.ListRead(), services.ListRead()), **fields))
        return state

    @staticmethod
    def rows(prefix, count):
        return tuple(services.RecommendRow(f"{prefix}{number}", f"{prefix} 주제 {number}", 90 - number, None, None) for number in range(1, count + 1))

    def test_each_channel_stops_at_five_rows_and_the_recommended_count_counts_only_what_is_shown(self):
        state = self.board_state(services.ChannelRead("A", "에이", True, "ok", "", self.rows("a", 8)), services.ChannelRead("B", "비", True, "ok", "", self.rows("b", 2)))
        board = state.home_view()["board"]
        self.assertEqual([(item["key"], len(item["rows"]), item["count_text"]) for item in board["recommend"]], [("A", 5, "후보 5개"), ("B", 2, "후보 2개")])
        self.assertEqual([row["title"] for row in board["recommend"][0]["rows"]], ["a 주제 1", "a 주제 2", "a 주제 3", "a 주제 4", "a 주제 5"])       # 엔진이 정한 순서의 앞 다섯
        self.assertEqual({item["key"]: item["text"] for item in board["kpi"]}["topics"], "7개")                                                   # 보이는 줄의 합(5+2) — 여덟 개가 아니다

    def test_held_old_candidates_are_saved_ideas_only_and_never_appear_as_recommendations(self):
        state = state_with(topic("에이만", ("A",), trend="up"), topic("둘 다", ("A", "B"), status="selected"), topic("보류 급상승", ("A", "B"), trend="up", status="hold"), topic("블로그 없음", ()), topic("보류 둘", ("B",), status="hold"))
        view = state.home_view()
        self.assertEqual({item["key"]: item["text"] for item in view["board"]["kpi"]}["ideas"], "2개")                                           # 보류한 것만 저장된 아이디어로 센다
        self.assertEqual({item["key"]: item["text"] for item in view["board"]["kpi"]}["topics"], "연결 전")                                        # 옛 후보는 추천 주제가 아니다(추천은 주제 엔진 후보)
        for title in ("에이만", "둘 다", "보류 급상승", "블로그 없음", "보류 둘"):
            self.assertNotIn(title, repr(view), title)

    def test_the_recommendation_order_is_the_engines_whatever_the_scores_or_the_old_priorities_are(self):
        low_first = (services.RecommendRow("x1", "낮은 점수가 먼저", 40, None, None), services.RecommendRow("x2", "높은 점수가 나중", 95, None, None), services.RecommendRow("x3", "점수 없음", None, None, None))
        state = self.board_state(services.ChannelRead("A", "에이", True, "ok", "", low_first), services.ChannelRead("B", "비", True, "ok", "", ()), topics=(topic("높음", priority="높음"),))
        self.assertEqual([(row["rank"], row["title"]) for row in state.home_view()["board"]["recommend"][0]["rows"]], [(1, "낮은 점수가 먼저"), (2, "높은 점수가 나중"), (3, "점수 없음")])

    def test_a_channel_with_no_rows_is_a_normal_empty_section_and_the_other_channel_is_untouched(self):
        state = self.board_state(services.ChannelRead("A", "에이", True, "ok", "", ()), services.ChannelRead("B", "비", True, "ok", "", self.rows("b", 3)))
        board = state.home_view()["board"]
        self.assertEqual([(item["key"], item["state"], len(item["rows"])) for item in board["recommend"]], [("A", "empty", 0), ("B", "normal", 3)])

    def test_new_home_data_keeps_the_drawer_only_when_the_row_is_still_there(self):
        first = self.board_state(services.ChannelRead("A", "에이", True, "ok", "", self.rows("a", 3)), services.ChannelRead("B", "비", True, "ok", "", ()))
        self.assertTrue(first.open_drawer("a2"))
        self.assertEqual(first.drawer_view()["topic"], "a 주제 2")
        again = services.HomeData(board=services.BoardData((services.ChannelRead("A", "에이", True, "ok", "", self.rows("a", 3)), services.ChannelRead("B", "비", True, "ok", "", ())), services.ListRead(), services.ListRead()))
        first.apply_home(again)
        self.assertEqual(first.drawer_view()["topic"], "a 주제 2")                                              # 같은 줄이 아직 있으면 서랍이 그대로
        first.apply_home(services.HomeData(board=services.BoardData((services.ChannelRead("A", "에이", True, "ok", "", self.rows("z", 3)), services.ChannelRead("B", "비", True, "ok", "", ())), services.ListRead(), services.ListRead())))
        self.assertIsNone(first.drawer_view())                                                                  # 그 줄이 사라지면 서랍은 보이지 않는다(다른 줄로 바뀌어 보이지 않는다)


class ChannelTwoAssumptionTest(unittest.TestCase):
    # 특성 시험(P0): 현재 동작을 못박는다. 바꾸려면 새 결정(D-nn)을 쓰고 이 시험을 의식적으로 고친다.
    def test_the_blog_tables_hold_exactly_the_two_naver_blogs_and_nothing_else(self):
        self.assertEqual(adapters.BLOG_KEYS, {"naver_a": "A", "naver_b": "B"})
        self.assertEqual(list(adapters.BLOG_KEYS), ["naver_a", "naver_b"])
        self.assertEqual(app_state.BLOG_NAMES, {"A": "블로그 A", "B": "블로그 B"})
        self.assertEqual(set(adapters.BLOG_KEYS.values()), set(app_state.BLOG_NAMES))

    def test_the_home_has_exactly_the_two_naver_channels_in_this_order_and_five_rows_each(self):
        """의도적 교체(UI-C1d, D-201): 옛 `test_the_home_chips_are_five_in_this_order_and_only_a_and_b_name_a_blog` 는 필터 칩 다섯(전체·A·B·급상승·신규)과 추천 행 5개(`HOME_ROWS`)를 못박았다 — 칩이 홈에서 없어졌다.
        새 홈의 채널 가정(둘뿐·A 다음 B·각 최대 5)을 같은 자리에 못박는다."""
        self.assertEqual((services.HOME_CHANNELS, services.HOME_LIMIT), (("A", "B"), 5))
        self.assertEqual([text.T[key] for key in ("blog_a", "blog_b")], ["블로그 A", "블로그 B"])
        state = app_state.AppState(services.FakeHomeProvider())
        state.apply_home(services.HomeData(board=services.sample_board()))
        self.assertEqual([item["key"] for item in state.home_view()["board"]["recommend"]], ["A", "B"])
        for gone in ("HOME_CHIPS", "HOME_ROWS"):
            self.assertFalse(hasattr(app_state, gone), gone)
    def test_a_blog_key_outside_a_and_b_gets_no_badge_in_the_view_model(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 옛 추천 행의 뷰모델(`topic_vm` 의 `blogs`·`blog`·`blog_label`)을 봤다 — 그 행이 없어졌다. 같은 규칙(A·B 만 블로그로 센다, 그 밖의 열쇠는 배지가 없다)을 이 후보가 나가는 곳인
        상세 서랍(블로그 라벨·초안 단추)에서 본다."""
        state = state_with(topic("낯선 키", ("A", "C", "B", "github_pages")), topic("배지 없음", ("C",)))
        state.open_drawer("낯선 키")
        shown = state.drawer_view()
        self.assertEqual((shown["blog_label"], [item["key"] for item in shown["drafts"]]), ("블로그 A", ["A", "B"]))
        state.open_drawer("배지 없음")
        none = state.drawer_view()
        self.assertEqual((none["blog_label"], none["drafts"]), ("", []))
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


class CompletedScreensOnlyTest(unittest.TestCase):
    """의식적으로 다시 씀(UI-C1a, D-172): 옛 `TopicsPlaceholderTest` 는 '메뉴 6개·주제 후보가 둘째·홈 카드와 전체 보기와 빠른 작업이 주제 후보·발행 기록·블로그 관리로 간다·자리표시 네 화면' 을 **그때 모습 그대로** 못박았다.
    운영자 2026-11-06 확인 요청 004 의 답 — 완성된 화면(홈·설정)만 실제 Navigation 이고 미완성 화면으로 가는 이동 경로는 0개다. 아래는 같은 자리에 새 규칙을 못박는다(서랍은 홈에서만 열린다는 규칙은 그대로)."""
    PLACEHOLDERS = ("topics", "draft", "history", "blogs")                                                     # 옛 자리표시 화면 넷 — 의도적 갱신(P4b, D-210): 'blogs' 는 이제 완성된 화면이라 열리고, 나머지 셋은 지금도 열 수 없다(다음 단계 목록에 이름만 있다). 의도적 갱신(P4d, D-270): 'topics' 도 완성돼 열리고 이제 열 수 없는 것은 둘(초안 작성·발행 기록)이다 — 이 낱말 모음은 쓰이지 않아 옛 모습 그대로 둔다

    def test_the_menu_keys_and_icons_are_home_and_settings_only_and_the_label_still_says_topic_candidates(self):
        # 의도적 갱신(P4b, D-210): 블로그 관리 화면이 완성돼 메뉴에 올랐다 — 홈·블로그 관리(책 아이콘)·설정
        # 의도적 갱신(Seed 관리, D-230): Seed 관리 화면이 완성돼 메뉴에 올랐다 — 홈·Seed 관리(씨앗 아이콘)·블로그 관리·설정
        # 의도적 갱신(P4d, D-270): 주제 후보 화면이 완성돼 메뉴에 올랐다 — 홈·주제 후보(돋보기 아이콘)·Seed 관리·블로그 관리·설정
        # 의도적 갱신(P4e, D-282): 초안 작성 화면이 완성돼 메뉴에 올랐다 — 홈·주제 후보·초안 작성(연필 아이콘 `draft`)·Seed 관리·블로그 관리·설정
        self.assertEqual([key for key, _label, _icon in app_state.NAV], ["home", "topics", "drafts", "seed", "blogs", "settings"])
        self.assertEqual([icon for _key, _label, icon in app_state.NAV], ["home", "search", "draft", "sprout", "book", "settings"])
        self.assertEqual(text.T["nav_topics"], "주제 후보")                                                       # 이름은 실제 메뉴 항목이 쓴다(P4d 부터 '다음 단계' 목록이 아니다)
        self.assertFalse(hasattr(app_state, "MAX_NAV"))

    def test_the_home_cards_and_the_section_have_no_route_any_more(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 요약 카드의 `go`(모두 None)와 구역 머리의 `전체 보기` 가 없음을 봤다 — 요약 카드는 KPI 가, 구역 머리는 추천 구역 머리가 되었다. 새 규칙: 홈 뷰모델 어디에도
        화면으로 가는 칸(`go`·`all`)이 없고 `전체 보기` 글도 없다."""
        view = state_with(topic("하나")).home_view()
        self.assertEqual([item["key"] for item in view["board"]["kpi"]], ["topics", "done", "pub", "ideas"])
        for item in view["board"]["kpi"]:
            self.assertNotIn("go", item)
        for gone in ("section", "cards"):
            self.assertNotIn(gone, view)
        self.assertNotIn("전체 보기", repr(view))
        self.assertNotIn("'all'", repr(view))

    def test_the_quick_actions_that_moved_are_gone_and_the_rest_only_says_soon(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 빠른 작업이 '새 초안 만들기' 하나만 남고 눌러도 안내뿐임을 못박았다. 운영자 2026-11-06 확인 요청 004 의 답 5 — 빠른 작업(오른쪽 패널)은 홈에서 완전히 없어졌다.
        뷰모델에 `rail` 이 없고 상태에 `quick` 이 없으며 홈의 어떤 글에도 빠른 작업·활용 팁·새 초안 만들기가 없다. 상세 서랍의 초안 단추가 하는 안내는 그대로다."""
        state = state_with(topic("하나"))
        view = state.home_view()
        self.assertNotIn("rail", view)
        self.assertFalse(hasattr(state, "quick"))
        for word in ("빠른 작업", "활용 팁", "새 초안 만들기", "고른 주제로 바로 시작"):
            self.assertNotIn(word, repr(view), word)
            self.assertNotIn(word, " ".join(text.T.values()), word)
        self.assertEqual((state.draft_requested("하나", "A"), state.page), (text.T["soon_toast"].format(name=text.T["make_small"]), "home"))

    def test_the_next_steps_list_names_the_five_unfinished_screens_and_none_of_them_can_be_opened(self):
        # 의도적 갱신(P4b, D-210): '블로그 관리' 는 완성돼 실제 메뉴로 올라갔다 — 아직 열 수 없는 화면은 넷이다(이름과 규칙 — 열 수 없다 — 은 그대로)
        # 의도적 갱신(Seed 관리, D-230): 'Seed 관리' 도 완성돼 실제 메뉴로 올라갔다 — 아직 열 수 없는 화면은 셋이다(주제 후보·초안 작성·발행 기록)
        # 의도적 갱신(P4d, D-270): '주제 후보' 도 완성돼 실제 메뉴로 올라갔다 — 아직 열 수 없는 화면은 둘이다(초안 작성·발행 기록). 이름과 규칙 — 열 수 없다 — 은 그대로다.
        # 의도적 갱신(P4e, D-282): '초안 작성' 도 완성돼 실제 메뉴로 올라갔다 — 아직 열 수 없는 화면은 하나다(발행 기록). 이름과 규칙 — 열 수 없다 — 은 그대로다.
        self.assertEqual([key for key, _label, _icon in app_state.NEXT_STEPS], ["history"])
        self.assertEqual([text.T[label] for _key, label, _icon in app_state.NEXT_STEPS], ["발행 기록"])
        self.assertEqual([icon for _key, _label, icon in app_state.NEXT_STEPS], ["calendar_check"])
        self.assertFalse({key for key, _label, _icon in app_state.NEXT_STEPS} & {key for key, _label, _icon in app_state.NAV}, "다음 단계 항목은 실제 메뉴에 없다")
        for key, _label, _icon in app_state.NEXT_STEPS:
            state = state_with(topic("하나"))
            self.assertFalse(state.nav(key), key)
            self.assertEqual(state.page, "home", key)

    def test_groups_show_a_name_only_when_they_have_a_real_menu(self):
        self.assertEqual([(key, label, [item[0] for item in items]) for key, label, items in app_state.nav_groups()],
                         [("core", "nav_group_core", ["home", "topics", "drafts"]), ("data", "nav_group_data", ["seed", "blogs"]), ("system", "nav_group_system", ["settings"])],
                         "의도적 갱신(P4b, D-210): 데이터·관리 묶음에 블로그 관리가 올라 이름이 보인다 — 묶음 이름은 실제 메뉴가 있을 때만 보인다는 규칙은 그대로. 의도적 갱신(Seed 관리, D-230): 같은 묶음에 Seed 관리가 블로그 관리 앞에 올랐다. 의도적 갱신(P4d, D-270): 핵심 작업 묶음에 주제 후보가 홈 다음에 올랐다. 의도적 갱신(P4e, D-282): 같은 묶음에 초안 작성이 주제 후보 다음에 올랐다")
        self.assertEqual([text.T[label] for _key, label, _menus in app_state.NAV_GROUPS], ["핵심 작업", "데이터·관리", "시스템"])
        in_groups = [menu for _key, _label, menus in app_state.NAV_GROUPS for menu in menus]
        self.assertEqual(sorted(in_groups), sorted(key for key, _label, _icon in app_state.NAV), "모든 실제 메뉴가 묶음 하나에 한 번씩 있다")

    # 특성 시험(P0, UI-C1a 에서 '주제 후보' → '설정' 으로 옮김): 서랍은 홈에서만 열리고 홈을 떠나면 닫힌다.
    def test_leaving_home_closes_the_drawer_and_a_drawer_opened_on_another_page_is_only_a_view_model_fact(self):
        state = state_with(topic("하나", priority="높음"))
        self.assertTrue(state.open_drawer("하나"))
        self.assertIsNotNone(state.drawer_view())
        self.assertTrue(state.nav("settings"))
        self.assertEqual((state.drawer_id, state.drawer_view()), (None, None))
        self.assertTrue(state.open_drawer("하나"))                                                            # 뷰모델은 어느 화면에서든 연다 — '홈에서만' 은 아래의 Qt 틀이 정한다
        self.assertIsNotNone(state.drawer_view())

    # 의식적으로 다시 씀(P4a, D-90): 옛 시험은 `render` 가 '홈이면 홈, 아니면 자리표시' 로 가르는지를 읽었다. 이제 `render` 는 '메뉴 → 화면 만드는 함수' 표 한 곳만 거치고 표가 홈·설정·자리표시 넷을 정한다
    # (홈 화면은 한 글자도 안 바뀌었다 — 아래 `HomeOutputUnchangedTest`). 서랍은 여전히 홈에서만 열고 홈의 '전체 보기' 는 여전히 '주제 후보' 로 간다.
    def test_the_qt_shell_draws_every_menu_through_one_table_and_shows_the_drawer_on_home_only(self):
        # Qt 를 불러오지 않고 소스를 `ast` 로 읽는다(순수 뷰모델에는 '어느 화면을 그릴지' 가 없다) — 글자 모양이 아니라 규칙을 본다.
        shell = ast.parse((QT_DIR / "shell.py").read_text(encoding="utf-8"))
        screens = ast.parse((QT_DIR / "screens.py").read_text(encoding="utf-8"))
        table = builder_table(screens)
        self.assertEqual(list(table), [key for key, _label, _icon in app_state.NAV], "표의 줄은 실제 메뉴(완성된 화면)와 같은 열쇠·같은 순서다 — 빠진 메뉴가 없고 표에만 있는 화면도 없다(자리표시 화면은 없앴다)")
        self.assertEqual(table, {"home": "_home_builder", "topics": "_topics_builder", "drafts": "_drafts_builder", "seed": "_seed_builder", "blogs": "_blogs_builder", "settings": "_settings_builder"},
                         "의도적 갱신(P4b, D-210): 블로그 관리 줄이 더해졌다. 의도적 갱신(Seed 관리, D-230): Seed 관리 줄이 더해졌다. 의도적 갱신(P4d, D-270): 주제 후보 줄이 더해졌다. 의도적 갱신(P4e, D-282): 초안 작성 줄이 더해졌다")
        for builder, screen in (("_home_builder", "home_screen"), ("_topics_builder", "candidates_screen"), ("_drafts_builder", "drafts_screen"), ("_seed_builder", "seeds_screen"), ("_blogs_builder", "blogs_screen"), ("_settings_builder", "settings_screen")):
            self.assertEqual([name for name in calls_in(function_named(screens, builder)) if name.endswith("_screen")], [screen], f"{builder} 는 자기 화면 함수 하나만 부른다")
        # 점검 M3 — CI 에는 Qt 가 없어 이 시험이 유일한 방어선이다: 빌더마다 자기 뷰모델을 연결하고(설정 화면에 홈 뷰모델을 넘기면 안 된다) 표는 현재 화면 열쇠(`state.page`)로 찾는다.
        self.assertEqual({builder: viewmodel_of(function_named(screens, builder), screen) for builder, screen in (("_home_builder", "home_screen"), ("_topics_builder", "candidates_screen"), ("_drafts_builder", "drafts_screen"), ("_seed_builder", "seeds_screen"), ("_blogs_builder", "blogs_screen"), ("_settings_builder", "settings_screen"))},
                         {"_home_builder": "home_view", "_topics_builder": "candidates_view", "_drafts_builder": "drafts_view", "_seed_builder": "seeds_view", "_blogs_builder": "blogs_view", "_settings_builder": "settings_view"}, "빌더가 다른 화면의 뷰모델을 넘긴다")
        render, overlays = function_named(shell, "render"), function_named(shell, "_sync_overlays")
        self.assertEqual([name for name in calls_in(render) if name.endswith("_screen")], [], "render 는 화면 함수를 직접 부르지 않고 표만 거친다(표를 건너뛰는 길이 없다)")
        lookups = [node for node in ast.walk(render) if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "SCREEN_BUILDERS"]
        self.assertEqual(len(lookups), 1, "render 는 표를 한 번 찾는다")
        key = lookups[0].slice
        self.assertTrue(isinstance(key, ast.Attribute) and key.attr == "page" and isinstance(key.value, ast.Name) and key.value.id == "state", "표는 현재 화면 열쇠(`state.page`)로 찾는다 — 늘 홈만 그리면 안 된다")
        self.assertEqual([node.args[0].id for node in ast.walk(render) if isinstance(node, ast.Call) and isinstance(node.func, ast.Subscript) and node.func is lookups[0] and node.args],
                         ["self"], "찾은 화면 만드는 함수에는 이 창(`self`)을 넘긴다")
        self.assertEqual(home_branches(overlays, "drawer_view"), [frozenset({"참"})], "서랍은 홈에서만 연다")
        self.assertEqual(all_link_targets(screens), [], "의도적 갱신(UI-C1a, D-172): 홈의 '전체 보기' 단추는 아직 만들지 않은 '주제 후보' 로 가던 길이라 없앴다 — 어느 단추도 화면으로 가지 않는다")


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
    LEGACY_KEYS = ("d_demand", "unit_demand", "d_docs", "unit_docs")                                                  # 의도적 갱신(UI-C1d, D-201): 옛 추천 행의 지표 이름(`demand`·`docs`)과 설명(`tip_demand`·`tip_docs`)은 홈에서 없어졌다 — 남은 곳은 상세 서랍

    def test_the_legacy_absolute_count_is_called_monthly_search_volume_and_counted_in_times_in_the_screen_text(self):
        """의도적 갱신(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5·추천 후보 2): 옛 시험은 추천 행의 지표 이름(`월 검색량`·`블로그 문서 수`)과 설명(`tip_demand`)까지 못박았다. 홈의 행에서 월 검색량·문서 수를 없앴으므로
        그 글(`demand`·`docs`·`tip_demand`·`tip_docs`)도 없앴다. 상세 서랍(기존 그대로)이 쓰는 이름·단위와 서식은 그대로 못박는다."""
        T = text.T
        for gone in ("demand", "docs", "tip_demand", "tip_docs"):
            self.assertNotIn(gone, T, gone)
        self.assertEqual((T["d_demand"], T["unit_demand"]), ("월간 검색량", "회"))                                             # 서랍의 항목 이름·단위
        self.assertEqual((T["d_docs"], T["unit_docs"]), ("관련 블로그 검색 결과 수", "건"))                                     # 같은 Legacy 지표 묶음의 다른 칸
        self.assertEqual([text.fmt_demand(value) for value in (None, 0, 87, 8600, 1_234_567)], ["데이터 없음", "0회", "87회", "8,600회", "1,234,567회"])
        self.assertEqual([text.fmt_docs(value) for value in (None, 0, 4120)], ["데이터 없음", "0건", "4,120건"])
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
        # 의도적 갱신(P4d, D-270): 주제 후보 화면이 새 Trend 문구를 **새 키**로 더했다 — 상세 창의 머리 `최근 관심도(상대값)`(`cand_sec_trend`)와 값 글 `{n} (0~100 사이의 상대값)`(`cand_trend_value`). 위 두 시험이 지키는 옛 절대 횟수 칸의 네 키에는 여전히 들어가지 않는다.
        self.assertEqual([key for key, value in text.T.items() if "상대값" in value], ["cand_sec_trend", "cand_trend_value"])

    def test_the_drawer_shows_the_legacy_count_with_the_times_unit_and_the_monthly_label_and_the_home_shows_none(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 추천 행(`topic_vm` 의 `demand`·`docs`)과 서랍 둘 다에서 옛 절대 횟수를 봤다. 행에서는 없앴다 — 서랍은 그대로(첫 항목 `월간 검색량` `8,600회`)이고, 홈 뷰모델에는 그 수가 아예 없다."""
        state = state_with(topic("행", demand=8600, docs=4120))
        self.assertNotIn("8,600", repr(state.home_view()))                                                                  # 홈에는 월 검색량도 문서 수도 없다
        self.assertNotIn("4,120", repr(state.home_view()))
        self.assertTrue(state.open_drawer("행"))
        fields = state.drawer_view()["fields"]
        self.assertEqual((fields[0]["label"], fields[0]["value"], fields[0]["missing"]), ("월간 검색량", "8,600회", False))        # 서랍의 첫 항목
        shown = {field["label"]: field["value"] for field in fields}
        self.assertEqual((shown["월간 검색량"], shown["관련 블로그 검색 결과 수"]), ("8,600회", "4,120건"))
        self.assertNotIn("상대값", " ".join(shown))                                                                          # 서랍 항목 이름 어디에도 상대값 이름은 없다(기존 추세 항목 `최근 트렌드` 이름 변경은 상관없다)


class HomeOutputUnchangedTest(unittest.TestCase):
    """홈 화면 뷰모델의 지문(뷰모델 전체를 JSON 으로 만들어 SHA-256 앞 16자). 홈을 일부러 바꾸는 묶음은 어느 줄이 왜 바뀌는지 적고 이 값을 의식적으로 고친다. 값이 다르면 아래 `diff` 로 어느 시나리오인지 먼저 본다.
    의도적 갱신(UI-C1a, D-171·D-172): 홈 뷰모델은 **정확히 다섯 곳**만 바뀌었다(기준 = UI-C0 가지 `754cf97` — `date` 삭제·요약 카드 둘의 `go` 를 `None` 으로·`section.all` 삭제·`rail.quick` 4→1). 상세 서랍은 한 글자도 안 바뀌었다.
    의도적 갱신(UI-C1c, D-190): 새 홈 구역의 값이 새 키 `board` 하나로 **더해졌다**(옛 키는 한 글자도 안 바뀜 — 그때는 `board` 를 뺀 지문이 UI-C1a 의 옛 지문과 같음까지 못박았다).
    의도적 교체(UI-C1d, D-201 — 운영자 2026-11-06 확인 요청 004 의 답 5·홈 구성): UI-C1d 가 `board` 를 그리고 **옛 키(요약 카드·칩·추천 행·선택·구역 머리·오른쪽 패널·옛 빈 상태)를 홈 뷰모델에서 없앴다** — 그래서 '`board` 를 뺀 값이 옛 지문과 같다' 는 시험(`LEGACY_BASELINE`)은
    의미가 없어져 아래 '키 목록' 시험(홈 뷰모델이 정확히 열한 칸이고 옛 칸이 없다)으로 바꿨다. 지문 값은 새 뷰모델의 값으로 다시 못박았다 — 시나리오는 정상·빈·일부만·오프라인·오류·읽는 중·연결 전(새 구역을 안 읽는 공급자). 옛 칩 거르기 시나리오(`home_filter_b`)는 칩이 없어져 뺐다.
    **옛 후보의 상세 서랍(`drawer_s1`)의 지문은 UI-C1a 가 못박은 값 그대로다**(서랍은 한 글자도 안 바뀌었다) — 추천 줄의 서랍(`drawer_rA1`·`drawer_rA5`)이 새 지문이다."""
    BASELINE = {"home_normal": "c3e41489dd84b42b", "home_empty": "9b8a476a0ff4a861", "home_partial": "3708e0a1323f6af0", "home_offline": "f06bf1c1b6be80fe", "home_error": "2900e031bc3fc98e", "home_loading": "1bc77e56c2fbf6b5", "home_before_connect": "51647256831381fb"}
    DRAWERS = {"drawer_s1": "7e6ccf32dcb04a58", "drawer_rA1": "c941cf939e238add", "drawer_rA5": "a67e6f142d9507e7"}                    # `drawer_s1` 은 UI-C1a 의 값 그대로(서랍은 안 바뀌었다)
    WHEN = datetime.datetime(2026, 11, 3, 10, 0, 0)

    @staticmethod
    def digest(value):
        import hashlib
        import json
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def loaded(scenario, **options):
        provider = services.FakeHomeProvider(scenario, **options)
        state = app_state.AppState(provider)
        state.apply_home(provider.load_home(lambda *a: None, lambda: False))
        return state

    def views(self):
        """일곱 시나리오의 홈 뷰모델(딕셔너리)과 상세 서랍들 — 지문은 이 값들로 만든다."""
        out = {f"home_{scenario}": self.loaded(scenario).home_view() for scenario in ("normal", "empty", "partial", "offline")}
        state = app_state.AppState(services.FakeHomeProvider("error"))
        state.apply_failure(services.ServiceFailure("후보를 불러오는 중 연결이 끊겼어요.", code="SAMPLE_NETWORK_DOWN"), self.WHEN)
        out["home_error"] = state.home_view()
        out["home_loading"] = app_state.AppState(services.FakeHomeProvider(delay=5)).home_view()
        out["home_before_connect"] = self.loaded("normal", board=None).home_view()
        state = self.loaded("normal")
        drawers = {}
        for name, topic_id in (("drawer_s1", "s1"), ("drawer_rA1", "rA1"), ("drawer_rA5", "rA5")):
            state.open_drawer(topic_id)
            drawers[name] = state.drawer_view()
        return out, drawers

    def current(self):
        homes, drawers = self.views()
        return {name: self.digest(view) for name, view in {**homes, **drawers}.items()}

    def test_the_home_view_models_are_exactly_what_the_home_shape_bundle_made_them(self):
        got = self.current()
        expected = {**self.BASELINE, **self.DRAWERS}
        self.assertEqual({key: (expected[key], got[key]) for key in expected if got[key] != expected[key]}, {}, "홈의 출력이 바뀌었다 — 의도한 변경이면 이유를 적고 지문을 고친다")
        self.assertEqual(set(got), set(expected))

    def test_the_drawer_of_an_old_candidate_is_byte_identical_to_the_one_the_c1a_shell_made(self):
        """상세 서랍은 이 묶음에서 한 글자도 안 바뀌었다(서랍 내용·동작은 그대로 — 운영자 결정 5). 옛 후보 하나(`s1`)의 서랍 지문은 UI-C1a 가 못박은 값 그대로다."""
        self.assertEqual(self.current()["drawer_s1"], "7e6ccf32dcb04a58")

    def test_every_home_view_model_has_exactly_the_eleven_keys_and_none_of_the_old_ones(self):
        """UI-C1c 가 `board` 를 더하며 옛 키는 그대로 두었던 것을 UI-C1d 가 정리했다 — 일곱 시나리오 모두 아래 열한 칸뿐이다(옛 칸이 하나라도 있으면 실패)."""
        homes, _drawers = self.views()
        for name, view in homes.items():
            self.assertEqual(sorted(view), sorted(["title", "sub", "sample", "sample_tag", "state", "fetched", "refresh", "banner", "loading", "error", "board"]), name)
            for gone in ("cards", "chips", "section", "rows", "selected", "empty", "rail", "date"):
                self.assertNotIn(gone, view, f"{name}: {gone}")
            self.assertEqual(sorted(view["board"]), sorted(["state", "sample", "sample_tag", "kpi", "recommend", "drafts", "recent", "connection"]), name)


if __name__ == "__main__":
    unittest.main()
