"""화면의 실제 서비스 어댑터(`ui/adapters.py`) 시험 — 서비스 층의 후보 목록·글 목록을 읽기 전용으로 화면용 값으로 바꾼다. PySide6 없이 돈다(네트워크·시크릿 없음).

지키는 것: 읽기만 한다(보관함·데이터 폴더를 만들지 않는다) · 후보 → 화면 줄 바꾸기(블로그 A·B·상태·추세·계절성·없는 값은 비움) · 제외한 후보는 홈에 안 나옴 · 작성·발행 완료 수 ·
없는 데이터는 빈 화면 · 서비스 오류는 쉬운 문장 + 오류 코드로(세부·입력한 글이 문구에 안 실림) · 어댑터가 화면 스레드를 안 막도록 작업 스레드에서도 돈다.
"""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT =Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import service_support as support  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import candidates as svc  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402
from chanceblog_desktop.ui import adapters  # noqa: E402
from chanceblog_desktop.ui.core import app_state, jobs, services, text  # noqa: E402

# 가짜 비밀 모양(조각을 이어 만들어 저장소에는 키 문자열이 없다) — 구글 키(39자)·GitHub 토큰(40자). 조각이 하나라도 화면 글에 남으면 샌 것이다.
GOOGLE_KEY = "AI" + "za" + "SyD4e7Kq9ZmW2xV8bN5tR1cY6uH3jL0pGfA1B"[:35]
GITHUB_KEY = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
KEYS = (GOOGLE_KEY, GITHUB_KEY)


def leaks(text, key=GOOGLE_KEY, size=6):
    """text 에 key 의 연속된 size 글자 조각이 남아 있으면 그 조각들(자르기로 반쪽이 된 키도 잡는다). 비어 있어야 한다."""
    return sorted({key[i:i + size] for i in range(len(key) - size + 1) if key[i:i + size] in text})


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = support.make_ctx(self.tmp.name)
        self.provider = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: self.ctx)

    def add(self, topic, blogs=("naver_a",), **fields):
        return svc.add_candidate(self.ctx, topic=topic, keyword=topic + " 키워드", blogs=blogs, **fields)

    def load(self):
        return self.provider.load_home(lambda *a: None, lambda: False)

    def test_no_data_folder_means_an_empty_home_and_nothing_is_created(self):
        before = support.tree_snapshot(self.ctx.workspace.root)
        self.assertFalse(self.ctx.workspace.store_path.exists())
        data = self.load()
        self.assertEqual((data.topics, data.sample, data.offline, data.partial), ((), False, False, ()))
        self.assertEqual((data.done, data.pub), (0, 0))
        self.assertFalse(self.ctx.workspace.store_path.exists())                        # 읽기 전용 — 보관함을 만들지 않는다
        self.assertEqual(support.tree_snapshot(self.ctx.workspace.root), before)        # 파일 하나도 늘거나 바뀌지 않는다

    def test_candidates_become_topics_with_only_the_values_that_exist(self):
        self.add("보일러 점검 순서", blogs=("naver_a", "naver_b"), search_demand=8600, related_blog_results=4120, trend="상승", mobile_share=71.4, seasonality=(11, 12, 1), priority=80.0,
                 data_date="2026-11-02", reason="겨울 전에 많이 찾습니다")
        self.add("그냥 주제")
        data = self.load()
        self.assertFalse(data.sample)
        rich, bare = (next(t for t in data.topics if t.title == name) for name in ("보일러 점검 순서", "그냥 주제"))
        self.assertEqual((rich.blogs, rich.demand, rich.docs, rich.trend, rich.mobile, rich.season, rich.priority), (("A", "B"), 8600, 4120, "up", 71, "1월·11월·12월", "높음"))
        self.assertEqual(rich.desc, "겨울 전에 많이 찾습니다")
        self.assertEqual((bare.demand, bare.docs, bare.trend, bare.mobile, bare.season, bare.written, bare.priority), (None, None, None, None, None, None, ""))      # 지어내지 않는다
        self.assertEqual(bare.desc, "그냥 주제 키워드")
        self.assertEqual(rich.keywords[0], "보일러 점검 순서 키워드")

    def test_topic_ids_are_the_candidate_numbers_but_the_view_model_never_shows_them(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 옛 추천 행(`view["rows"][0]`)의 글에 번호가 없음을 봤다. 옛 후보의 글은 이제 상세 서랍에만 나가므로 서랍의 모든 글과 홈 뷰모델 전체를 본다(번호는 눌렀을 때 누구인지 알려 주는 내부 값)."""
        self.add("번호 시험")
        topic = self.load().topics[0]
        row = svc.list_candidates(self.ctx).rows[0].candidate
        self.assertEqual(topic.id, row.candidate_id)
        state = app_state.AppState(self.provider)
        state.apply_home(self.load())
        self.assertTrue(state.open_drawer(topic.id))
        drawer = state.drawer_view()
        self.assertEqual(drawer["id"], row.candidate_id)                                 # 서랍이 쓰는 열쇠
        for key in ("topic", "reason", "blog_label", "priority"):                        # 화면에 나가는 글에는 번호가 없다(번호는 눌렀을 때 누구인지 알려 주는 내부 값)
            self.assertNotIn(row.candidate_id[:8], str(drawer[key]), key)
        for field in drawer["fields"]:
            self.assertNotIn(row.candidate_id[:8], f"{field['label']} {field['value']}")
        self.assertNotIn(row.candidate_id[:8], repr(state.home_view()))                  # 홈 뷰모델에는 옛 후보의 번호가 아예 없다
        self.assertEqual(drawer["priority"], text.NO_DATA)

    def test_rejected_candidates_are_left_out_and_held_ones_count_as_saved_ideas(self):
        """의도적 갱신(UI-C1d, D-201): 옛 시험은 옛 요약 카드(추천 1·작성 0·발행 0·보류 1)와 추천 행 제목을 봤다(옛 카드·행이 홈에서 없어졌다). 새 KPI 는 같은 수를 센다 — 보류 1은 저장된 아이디어,
        추천 주제는 주제 엔진의 후보라 엔진 보관함이 아직 없는 이 시험에서는 0 이 아니라 `연결 전` 이다. 제외한 후보가 홈에 안 나오는 것은 어댑터가 읽은 후보 목록으로 못박는다."""
        for name in ("살릴 것", "미룰 것", "버릴 것"):
            self.add(name)
        svc.move_candidate(self.ctx, "2", "HOLD")
        svc.move_candidate(self.ctx, "3", "REJECTED")
        data = self.load()
        self.assertEqual(sorted(topic.title for topic in data.topics), ["미룰 것", "살릴 것"])
        state = app_state.AppState(self.provider)
        state.apply_home(data)
        kpi = {item["key"]: item["text"] for item in state.home_view()["board"]["kpi"]}
        self.assertEqual((kpi["done"], kpi["pub"], kpi["ideas"]), ("0개", "0개", "1개"))                    # 작성 완료 0 · 발행 완료 0 · 보류 1
        self.assertEqual(kpi["topics"], "연결 전")                                                          # 주제 엔진 보관함이 없다

    def test_the_blog_names_come_from_the_naver_profiles_and_counts_from_the_candidates(self):
        support.naver_profiles(self.ctx)
        self.add("에이 글", blogs=("naver_a",))
        self.add("비 글", blogs=("naver_b",))
        self.add("둘 다", blogs=("naver_a", "naver_b"))
        self.add("다른 블로그", blogs=("github_pages",))
        data = self.load()
        self.assertEqual([(blog.key, blog.name, blog.candidates, blog.total, blog.month) for blog in data.blogs], [("A", "블로그 에이", 2, None, None), ("B", "블로그 비", 2, None, None)])
        other = next(topic for topic in data.topics if topic.title == "다른 블로그")
        self.assertEqual(other.blogs, ())                                                # A·B 가 아닌 대상은 A·B 배지가 없다
        state = app_state.AppState(self.provider)                                        # 의도적 갱신(UI-C1d, D-201): 옛 `topic_vm` 이 없다 — 같은 값(블로그 라벨이 비어 있다)을 상세 서랍에서 본다
        state.apply_home(data)
        self.assertTrue(state.open_drawer(other.id))
        self.assertEqual(state.drawer_view()["blog_label"], "")

    def save_name(self, name, key="naver_a"):
        """네이버 프로필에 블로그 표시명을 저장한다(명령줄 `naver-profile set` 과 같은 길 — 표시명은 60자까지)."""
        vars(self.ctx.settings).pop("naver_profile_dicts", None)                          # `raw_name` 으로 바꿔 둔 읽기를 되돌린다
        self.ctx.settings.save_naver_profile(NaverProfile(key, name, "https://blog.naver.com/exampleaaa", default_tags=("생활",), min_chars=10, max_chars=20000))

    def raw_name(self, name, key="naver_a"):
        """설정 파일을 손으로 고쳐 60자를 넘긴 이름 흉내 — 어댑터는 설정의 날것 사전(`naver_profile_dicts`)을 읽는다."""
        self.ctx.settings.naver_profile_dicts = lambda: {key: {"display_name": name}}

    def blog_names(self):
        return [blog.name for blog in self.load().blogs]

    def test_a_blog_name_with_a_key_shape_is_masked_before_it_is_cut_and_never_reaches_the_view_model(self):
        """이름을 마스킹 전에 30자로 자르면 키 앞 24~26자가 오른쪽 패널에 그대로 보인다(검증 M-1) — 가리기가 먼저, 자르기가 나중이다."""
        self.save_name("블로그 " + GOOGLE_KEY)
        self.save_name("블로그 비 " + GITHUB_KEY, "naver_b")
        self.add("후보 하나")
        data = self.load()
        for blog, key in zip(data.blogs, KEYS):
            self.assertEqual(leaks(blog.name, key, 5), [], blog.name)
            self.assertLessEqual(len(blog.name), adapters.NAME_LIMIT)
            self.assertIn("가림", blog.name)
        state = app_state.AppState(self.provider)
        state.apply_home(data)
        shown_view = repr(state.home_view())
        self.assertEqual([leaks(shown_view, key, 5) for key in KEYS], [[], []])
        self.assertTrue(data.blogs[0].name.startswith("블로그 "))                           # 키가 아닌 앞부분은 그대로 보인다

    def test_a_key_in_a_blog_name_never_survives_at_any_position_around_the_cut(self):
        for key in KEYS:
            for lead in range(0, 100):
                for glue in ("", " "):                                                   # 한글에 바로 붙은 키도, 띄어 쓴 키도
                    self.raw_name("가" * lead + glue + key)
                    name = self.blog_names()[0]
                    self.assertEqual(leaks(name, key, 5), [], (lead, glue, name))
                    self.assertLessEqual(len(name), adapters.NAME_LIMIT)
        for lead in range(0, 21):                                                        # 명령줄이 받는 길이(60자) 안에서는 진짜 프로필 저장을 거쳐서도
            self.save_name("가" * lead + " " + GOOGLE_KEY)
            self.assertEqual(leaks(self.blog_names()[0], GOOGLE_KEY, 5), [], lead)

    def test_a_blog_name_is_cut_to_thirty_characters_with_an_ellipsis_only_when_it_is_longer(self):
        self.assertEqual(adapters.NAME_LIMIT, 30)
        for length, shown_length, ellipsis in ((1, 1, False), (29, 29, False), (30, 30, False), (31, 30, True), (60, 30, True), (200, 30, True)):
            self.raw_name("가" * length)
            name = self.blog_names()[0]
            self.assertEqual((len(name), name.endswith("…")), (shown_length, ellipsis), length)
            self.assertEqual(name[:min(length, 29)], "가" * min(length, 29))

    def test_a_key_inside_an_error_value_is_masked_before_the_error_layer_cuts_the_value(self):
        """오류 문구의 값 자리(`「경로」`)는 오류 층이 160자에서 자르는데 키가 그 경계에 걸리면 반쪽 키가 안 가려진다 — 어댑터가 자르기 전에 값을 가린다."""
        for key in KEYS:
            for lead in (60, 100, 140, 150, 155, 157, 158, 159, 160, 161, 170):
                path = "C:\\" + "가" * lead + " " + key

                def boom(data_dir=None, path=path, key=key):
                    raise AppError("DATA_DIR_UNSAFE", {"경로": path}, detail="세부 " + key)

                with self.assertRaises(jobs.JobFailure) as caught:
                    adapters.ServiceHomeProvider(context_factory=boom).load_home(lambda *a: None, lambda: False)
                message = caught.exception.user_message
                self.assertEqual(leaks(message, key, 5), [], (lead, message[-60:]))
                self.assertNotIn("세부", message)
                self.assertIn("데이터를 둘 폴더", message)

    def test_candidate_text_is_handed_over_whole_so_that_only_the_view_model_masks_then_cuts(self):
        """어댑터는 후보의 글을 자르지 않는다(자르기는 뷰모델의 `shown` — 가리기 → 자르기). 키가 제목·키워드·보조 키워드·이유의 어느 자리에 있어도(저장소가 받는 길이 안에서 끝까지) 화면 글에 조각이 안 남는다."""
        for index, lead in enumerate((0, 3, 6, 10, 15)):
            support.inject_candidate(self.ctx, topic="가" * (lead * 8) + f" 주제{index} " + GOOGLE_KEY, keyword="나" * lead + f" 키{index} " + GOOGLE_KEY, blogs=("naver_a",),      # 옛 버전이 저장한 것처럼 보관함에 직접(M3)
                                     sub_keywords=("다" * lead + f" 보조{index} " + GITHUB_KEY,), reason="라" * (lead * 12) + f" 이유{index} " + GOOGLE_KEY + " " + GITHUB_KEY)
        data = self.load()
        self.assertEqual(len(data.topics), 5)
        state = app_state.AppState(self.provider)
        state.apply_home(data)
        state.open_drawer(data.topics[0].id)
        pieces = [repr(state.home_view()), repr(state.drawer_view())]
        for topic in data.topics:
            state.open_drawer(topic.id)
            pieces += [repr(state.drawer_view())]                                          # 의도적 갱신(UI-C1d, D-201): 옛 추천 행의 뷰모델(`topic_vm`)이 없어져 그 항목을 뺐다 — 옛 후보의 글은 이제 서랍에만 나간다
        everything = " ".join(pieces)
        self.assertEqual([leaks(everything, key, 5) for key in KEYS], [[], []])
        self.assertIn("가림", everything)

    def test_real_candidates_never_claim_a_field_for_their_image_placeholder(self):
        """분야를 모르는 실제 후보에 장식 아이콘을 돌려 붙이면서 '생활·에너지 주제' 라고 설명하던 값(지어낸 값) — 이제 분야 없이 '이미지 자리 표시' 뿐이다.
        의도적 갱신(UI-C1d, D-201): 옛 시험은 추천 행 썸네일의 설명 글(`topic_vm` 의 `thumb`)까지 봤다 — 그 썸네일이 홈에서 없어졌다. 실제 후보가 분야를 지어 갖지 않는다는 값 자체는 그대로 못박는다."""
        for index in range(8):
            self.add(f"후보 {index}")
        data = self.load()
        self.assertEqual(len(data.topics), 8)
        self.assertEqual({topic.category for topic in data.topics}, {""})
        self.assertGreater(len({topic.icon for topic in data.topics}), 1)                    # 아이콘은 돌려 쓰는 장식이다

    def test_an_explicit_data_folder_that_is_missing_or_a_file_is_an_easy_message_not_an_empty_screen(self):
        root = Path(self.tmp.name)
        missing, a_file, folder = root / "없는 폴더", root / "파일.txt", root / "있는 폴더"
        a_file.write_text("x", encoding="utf-8")
        folder.mkdir()
        before = support.tree_snapshot(root)
        for path in (str(missing), str(a_file), "\x00", str(missing / "아래" / "더 아래"), str(a_file / "안")):
            provider = adapters.ServiceHomeProvider(path, context_factory=lambda data_dir=None: self.fail("폴더가 없으면 데이터를 읽으러 가지 않는다"))
            with self.assertRaises(jobs.JobFailure) as caught:
                provider.load_home(lambda *a: None, lambda: False)
            self.assertEqual((caught.exception.code, caught.exception.user_message), ("DATA_DIR_NOT_FOUND", "지정한 데이터 폴더를 찾지 못했어요. 폴더 이름을 확인한 뒤 다시 열어 주세요."), repr(path))
            self.assertTrue(caught.exception.retryable)
        self.assertEqual(support.tree_snapshot(root), before)                                  # 읽기만 한다 — 폴더를 만들지 않는다
        seen = []
        provider = adapters.ServiceHomeProvider(str(folder), context_factory=lambda data_dir=None: (seen.append(data_dir), self.ctx)[1])
        provider.load_home(lambda *a: None, lambda: False)
        self.assertEqual(seen, [str(folder)])                                                   # 있는 폴더는 그대로 읽는다
        seen.clear()
        adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: (seen.append(data_dir), self.ctx)[1]).load_home(lambda *a: None, lambda: False)
        self.assertEqual(seen, [None])                                                          # 기본 위치는 아직 없어도 오류가 아니다(처음 쓰는 PC — 빈 화면)

    def test_a_data_folder_written_with_a_tilde_is_read_like_the_service_layer_reads_it(self):
        """서비스 층은 `~` 를 사용자 폴더로 풀어 읽는다 — 화면의 '폴더가 있나' 검사도 같아야 한다(안 그러면 멀쩡한 `--data-dir ~\\데이터` 가 없는 폴더로 안내된다)."""
        from unittest import mock
        home = Path(self.tmp.name) / "집"
        (home / "데이터").mkdir(parents=True)
        with mock.patch.dict("os.environ", {"HOME": str(home), "USERPROFILE": str(home), "HOMEDRIVE": "", "HOMEPATH": ""}):
            self.assertTrue(adapters.is_folder("~"))
            self.assertTrue(adapters.is_folder("~/데이터"))
            if os.name == "nt":                                                              # 윈도에서만 역슬래시가 폴더 구분이다
                self.assertTrue(adapters.is_folder("~\\데이터"))
            self.assertFalse(adapters.is_folder("~/없는 폴더"))
            self.assertFalse(adapters.is_folder(str(home / "데이터" / "..\\없음")))
            seen = []
            adapters.ServiceHomeProvider("~/데이터", context_factory=lambda data_dir=None: (seen.append(data_dir), self.ctx)[1]).load_home(lambda *a: None, lambda: False)
            self.assertEqual(seen, ["~/데이터"])                                            # 어댑터는 글을 그대로 서비스 층에 넘긴다(푸는 것은 서비스 층)

    def test_errors_worded_as_saving_are_reworded_for_the_read_only_screen_but_keep_their_code(self):
        for code in ("FILE_WRITE_FAILED", "FILE_IN_USE"):
            def boom(data_dir=None, code=code):
                raise AppError(code, {"경로": "C:\\데이터\\보관함"})

            with self.assertRaises(jobs.JobFailure) as caught:
                adapters.ServiceHomeProvider(context_factory=boom).load_home(lambda *a: None, lambda: False)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.user_message, "데이터 폴더를 읽지 못했어요. 다른 프로그램이 쓰고 있지 않은지 확인한 뒤 다시 시도해 주세요.")
            self.assertNotRegex(caught.exception.user_message, "저장|바꾸지|쓰기 권한")
            self.assertNotIn("C:\\", caught.exception.user_message)
        def other(data_dir=None):
            raise AppError("DATA_DIR_UNSAFE", {"경로": "C:\\데이터"})

        with self.assertRaises(jobs.JobFailure) as caught:
            adapters.ServiceHomeProvider(context_factory=other).load_home(lambda *a: None, lambda: False)
        self.assertIn("데이터를 둘 폴더가 안전하지 않습니다", caught.exception.user_message)         # 다른 오류 문구는 그대로

    def test_only_the_two_write_worded_codes_are_reworded_and_every_other_catalog_code_keeps_its_own_text(self):
        """'저장하지 못했다' 말투 바꾸기가 다른 오류로 번지지 않는다(변이 N04: 다른 코드 하나를 더해도 시험이 통과했다) — 오류 표의 모든 코드에서, 바뀌는 건 단 둘이고 나머지는 표의 문장 그대로다."""
        import re
        from chanceblog_desktop.errors import CATALOG, render
        reworded = frozenset({"FILE_WRITE_FAILED", "FILE_IN_USE"})
        self.assertEqual(adapters.WRITE_WORDED_CODES, reworded)
        self.assertTrue(reworded <= set(CATALOG))
        self.assertGreater(len(CATALOG), 50)
        for code, info in sorted(CATALOG.items()):
            slots = {name: f"{name} 값" for name in re.findall("「([^」]+)」", info.message + " " + info.action)}
            failure = adapters.failure_from(AppError(code, slots))
            self.assertEqual(failure.code, code)
            if code in reworded:
                self.assertEqual(failure.user_message, text.T["data_unreadable"], code)
            else:
                rendered = render(code, slots)
                self.assertEqual(failure.user_message, f"{rendered.message} {rendered.action}".strip(), code)
                self.assertNotEqual(failure.user_message, text.T["data_unreadable"], code)

    def test_a_blog_name_that_is_empty_after_masking_falls_back_to_the_default_name(self):
        """눈에 안 보이는 글자뿐인 이름은 가리면 빈 글이 된다 — 빈 이름이 아니라 기본 이름(변이 N07: 대체를 지워도 시험이 통과했다)."""
        for name in ("\u200b\u200b", "\u2060", "\ufeff", "\x00", "\u200f\u200e", "\U000e0041", "\u200b\u2060\ufeff"):
            self.raw_name(name, "naver_a")
            self.assertEqual(self.blog_names()[0], "블로그 A", repr(name))
            self.raw_name(name, "naver_b")
            self.assertEqual(self.blog_names()[1], "블로그 B", repr(name))
        self.raw_name("   ")                                                                    # 공백뿐인 이름은 처음부터 기본 이름
        self.assertEqual(self.blog_names()[0], "블로그 A")
        self.raw_name("\u200b진짜 이름\u200b")                                                   # 보이지 않는 글자는 지워지고 이름은 남는다
        self.assertEqual(self.blog_names()[0], "진짜 이름")

    def test_the_adapter_cuts_no_text_by_slicing_except_two_known_places(self):
        """글을 가리기 전에 자르는 것(검증 M-1)이 어댑터에 다시 생기지 않게 — 어댑터의 글 자르기는 `shown`(가리기 → 자르기) 한 곳이다. 슬라이스는 보조 키워드 **개수**(`[:2]`)와 시스템이 적은 만든 시각의 날짜 부분(`[:10]`)뿐이다."""
        import re
        source = (ROOT / "src" / "chanceblog_desktop" / "ui" / "adapters.py").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"\[:[^\]\n]*\]", source), ["[:2]", "[:10]"])
        self.assertIn("shown(raw[", source)

    def test_the_adapter_checks_for_a_cancel_between_its_steps(self):
        self.add("취소 시험")
        seen, original = [], self.provider._projects
        self.provider._projects = lambda ctx: (seen.append("projects"), original(ctx))[1]
        with self.assertRaises(jobs.JobCancelled):
            self.provider.load_home(lambda *a: None, lambda: True)
        self.assertEqual(seen, [])                                                       # 첫 단계(후보 목록) 뒤에 멈춘다 — 다음 단계(글 목록)를 읽지 않는다
        answers = iter([False, True])
        with self.assertRaises(jobs.JobCancelled):
            self.provider.load_home(lambda *a: None, lambda: next(answers))
        self.assertEqual(seen, ["projects"])                                             # 마지막 단계 뒤에도 본다 — 취소했으면 결과를 내놓지 않는다
        self.assertEqual(len(self.load().topics), 1)                                     # 취소가 아니면 끝까지 간다

    def test_done_and_published_counts_come_from_the_posts_and_are_unknown_when_unreadable(self):
        project_id = support.make_approved(self.ctx)
        data = self.load()
        self.assertEqual((data.done, data.pub), (1, 0))                                  # 승인까지 된 글 = 작성 완료
        other = projects.new_project(self.ctx, "아직 쓰는 중", support.ko_text())
        self.assertEqual(self.load().done, 1)                                            # 새 글은 아직 완료가 아니다
        self.assertEqual(other.project_id != project_id, True)

    def test_a_broken_settings_file_is_reported_not_hidden(self):
        self.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
        self.ctx.workspace.settings_path.write_text("{ 깨진 파일", encoding="utf-8")
        with self.assertRaises(jobs.JobFailure) as caught:
            self.load()
        self.assertEqual(caught.exception.code, "SETTINGS_INVALID")
        self.assertNotIn("깨진 파일", caught.exception.user_message)                      # 파일 속 글은 문구에 싣지 않는다
        self.assertNotIn("Traceback", caught.exception.user_message)

    def test_an_app_error_becomes_a_friendly_failure_with_only_the_code_for_diagnostics(self):
        def boom(data_dir=None):
            raise AppError("DATA_DIR_UNSAFE", {"경로": "C:\\비밀폴더"}, detail="내부 세부 설명 /secret/path")

        failure = None
        try:
            adapters.ServiceHomeProvider(context_factory=boom).load_home(lambda *a: None, lambda: False)
        except jobs.JobFailure as error:
            failure = error
        self.assertIsNotNone(failure)
        self.assertEqual(failure.code, "DATA_DIR_UNSAFE")
        self.assertNotIn("내부 세부", failure.user_message)
        self.assertNotIn("/secret/path", failure.user_message)
        self.assertTrue(failure.user_message.strip())

    def test_the_adapter_works_on_a_job_thread_and_the_screen_state_follows(self):
        self.add("스레드 시험")
        state = app_state.AppState(self.provider)
        done, results = threading.Event(), []
        job = state.start_load(on_done=lambda data, payload: (results.append(data), done.set()))
        self.assertTrue(done.wait(10))
        job.join(2)
        state.apply_home(results[0])
        self.assertEqual((state.list_state, len(state.data.topics)), ("normal", 1))                # 의도적 갱신(UI-C1d, D-201): 옛 `home_rows()` 가 없다 — 읽은 후보 수로 본다
        self.assertFalse(results[0].sample)

    def test_priority_labels(self):
        self.assertEqual([adapters.priority_label(value) for value in (None, 0, 39.9, 40, 69.9, 70, 100)], ["", "낮음", "낮음", "보통", "보통", "높음", "높음"])

    def test_done_states_are_real_states(self):
        self.assertTrue(adapters.DONE_STATES <= set(st.FLOWS["pages"]) | set(st.FLOWS["blogger"]) | set(st.FLOWS["naver"]))

    def test_the_provider_matches_the_service_interface(self):
        self.assertIsInstance(self.provider, services.HomeProvider)
        self.assertFalse(self.provider.sample)


if __name__ == "__main__":
    unittest.main()
