"""콘텐츠 모델·발행 상태 시험 — 상태 흐름 표(문서와 코드가 같은지), 원고 검증, 원고를 고치면 승인이 풀리는 규칙, 전환 규칙, 엄격한 JSON 저장 모양.

지키는 것:
  1) docs/ARCHITECTURE.md §9 의 상태 흐름이 코드(`content/status.py`)와 같고, 운영자가 정한 네이버 상태값이 그대로다.
  2) 공개된 상태는 되돌릴 수 없고, 실패는 올리는 중에만, 승인은 검토 뒤에만 생긴다.
  3) 규칙을 어기면 오류 코드(AppError)로 거절하고 **아무것도 바꾸지 않는다**.
  4) 승인은 현재 판으로 만든 렌더링에만, 원고를 고치면 승인·검토 중이던 변형이 처음부터 다시 검토된다(이미 올라간 상태는 그대로).
  5) 저장 모양(JSON)은 엄격하게 읽는다 — 모르는 칸·빠진 칸·앞뒤가 안 맞는 값은 거절한다.
네트워크·파일 없이 돈다.
"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import Asset, ContentProject, FLOWS, PLATFORMS, PlatformVariant, can_transition, next_statuses, statuses  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError, CATALOG  # noqa: E402

NOW = "2026-10-30T03:00:00Z"
LATER = "2026-10-30T04:30:00Z"
ARCH = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")


def section9():
    start = ARCH.index("## 9. 데이터 모델")
    return ARCH[start:ARCH.index("\n## 10.", start)]


def main_path(family):
    """각 상태에서 첫 번째 다음 상태만 따라가는 '정상 경로'."""
    flow, path, current = FLOWS[family], [], st.NOT_STARTED
    while True:
        if current in path:
            raise AssertionError(f"{family}: 정상 경로가 돌고 돈다 — {path + [current]}")
        path.append(current)
        if not flow[current]:
            return path
        current = flow[current][0]


def project():
    return ContentProject.new("주제가 분명한 제목", "본문 첫 문단입니다.\n\n둘째 문단입니다.", ["https://example.com/source"], [Asset("a.png", "설명", 1)], project_id="p1", now=NOW)


def raises(test, code, callable_, *args, **kwargs):
    with test.assertRaises(AppError) as caught:
        callable_(*args, **kwargs)
    test.assertEqual(caught.exception.code, code, caught.exception.detail)
    return caught.exception


def to_published(proj, platform, url):
    """정상 경로를 끝까지 보낸다(Pages·Blogger·네이버 공통)."""
    proj.set_rendered(platform, f"{platform} 용 글", now=NOW)
    for requested in main_path(st.family(platform))[2:]:
        extra = {"published_url": url} if st.is_published(platform, requested) else {}
        proj.transition(platform, requested, now=LATER, **extra)


class StatusTableTest(unittest.TestCase):
    def test_the_five_platforms_and_their_three_families(self):
        self.assertEqual(PLATFORMS, ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"))
        self.assertEqual({st.family(name) for name in PLATFORMS}, {st.PAGES, st.BLOGGER, st.NAVER})
        self.assertEqual((st.family("naver_a"), st.family("naver_b")), (st.NAVER, st.NAVER))

    def test_the_naver_states_are_exactly_the_operators_list(self):
        self.assertEqual(statuses("naver_a"), ("NOT_STARTED", "DRAFT_GENERATED", "REVIEW_REQUIRED", "READY_TO_COPY", "COPY_COMPLETED", "PUBLISHED_MANUAL", "PUBLISH_FAILED"))
        self.assertEqual(statuses("naver_b"), statuses("naver_a"))

    def test_the_full_transition_table_is_pinned_so_a_change_is_always_a_deliberate_one(self):
        expected = {
            "pages": {
                "NOT_STARTED": ("DRAFT_GENERATED",), "DRAFT_GENERATED": ("REVIEW_REQUIRED",), "REVIEW_REQUIRED": ("APPROVED", "DRAFT_GENERATED"),
                "APPROVED": ("COMMITTED", "REVIEW_REQUIRED", "PUBLISH_FAILED"), "COMMITTED": ("PUSHED", "PUBLISH_FAILED"), "PUSHED": ("PUBLISHED", "PUBLISH_FAILED"),
                "PUBLISHED": (), "PUBLISH_FAILED": ("REVIEW_REQUIRED", "DRAFT_GENERATED"),
            },
            "blogger": {
                "NOT_STARTED": ("DRAFT_GENERATED",), "DRAFT_GENERATED": ("REVIEW_REQUIRED",), "REVIEW_REQUIRED": ("APPROVED", "DRAFT_GENERATED"),
                "APPROVED": ("DRAFT_SAVED", "REVIEW_REQUIRED", "PUBLISH_FAILED"), "DRAFT_SAVED": ("PUBLISHED_MANUAL", "REVIEW_REQUIRED", "PUBLISH_FAILED"),
                "PUBLISHED_MANUAL": (), "PUBLISH_FAILED": ("REVIEW_REQUIRED", "DRAFT_GENERATED"),
            },
            "naver": {
                "NOT_STARTED": ("DRAFT_GENERATED",), "DRAFT_GENERATED": ("REVIEW_REQUIRED",), "REVIEW_REQUIRED": ("READY_TO_COPY", "DRAFT_GENERATED"),
                "READY_TO_COPY": ("COPY_COMPLETED", "REVIEW_REQUIRED", "PUBLISH_FAILED"), "COPY_COMPLETED": ("PUBLISHED_MANUAL", "READY_TO_COPY", "PUBLISH_FAILED"),
                "PUBLISHED_MANUAL": (), "PUBLISH_FAILED": ("REVIEW_REQUIRED", "DRAFT_GENERATED"),
            },
        }
        self.assertEqual({family: {state: tuple(targets) for state, targets in flow.items()} for family, flow in FLOWS.items()}, expected)
        self.assertEqual(st.APPROVED_STATES, {"APPROVED", "READY_TO_COPY"})
        self.assertEqual(st.RESET_ON_EDIT, {"REVIEW_REQUIRED", "APPROVED", "DRAFT_SAVED", "READY_TO_COPY", "COPY_COMPLETED", "PUBLISH_FAILED"})
        self.assertEqual(st.PUBLISHED_STATES, {"pages": "PUBLISHED", "blogger": "PUBLISHED_MANUAL", "naver": "PUBLISHED_MANUAL"})

    def test_the_documented_main_paths_are_what_the_code_does(self):
        text = section9()
        for family in (st.PAGES, st.BLOGGER, st.NAVER):
            path = main_path(family)
            shown = " → ".join(f"`{name}`" for name in path[:-1]) + f" → **`{path[-1]}`**"
            self.assertIn(shown, text, family)

    def test_every_status_is_reachable_from_the_start_and_every_target_is_a_status_of_the_same_flow(self):
        for family, flow in FLOWS.items():
            seen, todo = set(), [st.NOT_STARTED]
            while todo:
                current = todo.pop()
                if current in seen:
                    continue
                seen.add(current)
                for target in flow[current]:
                    self.assertIn(target, flow, f"{family}: {current} → {target}")
                    todo.append(target)
            self.assertEqual(seen, set(flow), family)

    def test_published_states_are_dead_ends(self):
        for family, published in st.PUBLISHED_STATES.items():
            self.assertEqual(FLOWS[family][published], (), family)
            self.assertEqual(sum(1 for targets in FLOWS[family].values() if not targets), 1, "막다른 곳은 공개 상태 하나뿐")

    def test_failure_happens_only_while_publishing_and_leads_back_to_review_or_draft(self):
        before_publishing = {st.NOT_STARTED, st.DRAFT_GENERATED, st.REVIEW_REQUIRED}
        for family, flow in FLOWS.items():
            sources = {state for state, targets in flow.items() if st.PUBLISH_FAILED in targets}
            self.assertTrue(sources, family)
            self.assertFalse(sources & before_publishing, family)
            self.assertNotIn(st.PUBLISHED_STATES[family], sources, family)
            self.assertEqual(set(flow[st.PUBLISH_FAILED]), {st.REVIEW_REQUIRED, st.DRAFT_GENERATED}, family)

    def test_approval_is_reachable_only_from_review(self):
        for family, flow in FLOWS.items():
            for state, targets in flow.items():
                for approved in st.APPROVED_STATES & set(targets):
                    self.assertIn(state, {st.REVIEW_REQUIRED} | ({st.COPY_COMPLETED} if approved == st.READY_TO_COPY else set()), f"{family}: {state} → {approved}")

    def test_the_helpers(self):
        self.assertTrue(can_transition("naver_a", st.REVIEW_REQUIRED, st.READY_TO_COPY))
        self.assertFalse(can_transition("naver_a", st.REVIEW_REQUIRED, st.PUBLISHED_MANUAL))
        self.assertFalse(can_transition("github_pages", st.NOT_STARTED, st.PUBLISHED))
        self.assertEqual(next_statuses("github_pages", st.PUBLISHED), ())
        self.assertEqual(next_statuses("github_pages", "NO_SUCH_STATE"), ())
        self.assertTrue(st.is_published("github_pages", st.PUBLISHED))
        self.assertFalse(st.is_published("github_pages", st.PUBLISHED_MANUAL))

    def test_the_architecture_doc_names_every_status_and_nothing_made_up(self):
        text = section9()
        every_status = {name for family in FLOWS.values() for name in family}
        for name in every_status:
            self.assertIn(f"`{name}`", text, name)
        tokens = set(re.findall(r"`([A-Z]+(?:_[A-Z]+)+)`", text))
        self.assertEqual({token for token in tokens if token not in every_status and token not in CATALOG}, set(), "문서에만 있는 낯선 이름")

    def test_the_documented_rules_are_all_written_down(self):
        text = section9()
        for needle in ("원고를 고치면", "현재 판으로 만든 렌더링", "발행 주소", "오류 코드", "되돌리지 않는다", "STATUS_TRANSITION_INVALID", "PUBLISHED_URL_REQUIRED"):
            self.assertIn(needle, text, needle)


class ProjectBasicsTest(unittest.TestCase):
    def test_a_new_project_starts_at_revision_one_with_all_five_platforms_not_started(self):
        proj = project()
        self.assertEqual((proj.revision, proj.created_at, proj.updated_at), (1, NOW, NOW))
        self.assertEqual(list(proj.variants), list(PLATFORMS))
        self.assertTrue(all(v.status == st.NOT_STARTED and v.rendered == "" and v.published_url is None for v in proj.variants.values()))

    def test_ids_are_generated_when_not_given(self):
        first, second = ContentProject.new("제목", "본문"), ContentProject.new("제목", "본문")
        self.assertRegex(first.project_id, r"^[0-9a-f]{32}$")
        self.assertNotEqual(first.project_id, second.project_id)

    def test_bad_values_are_refused_with_the_name_of_the_field(self):
        bad = {
            "제목": [dict(title=""), dict(title="   "), dict(title="가" * 201), dict(title=None), dict(title=7)],
            "본문": [dict(source_content=""), dict(source_content="\n \t"), dict(source_content=None)],
            "출처 주소": [dict(references=["ftp://example.com/x"]), dict(references=["https://user:pw@example.com/x"]), dict(references=["https://exa mple.com"]),
                      dict(references=["not a url"]), dict(references=["https://"]), dict(references="https://example.com"), dict(references=["https://example.com/x"] * 51),
                      dict(references=[5]), dict(references=["https://[::1"])],
            "이미지": [dict(assets=["a.png"]), dict(assets=[Asset("a.png")] * 101), dict(assets="a.png")],
            "프로젝트 번호": [dict(project_id=""), dict(project_id="a b"), dict(project_id="x" * 65), dict(project_id=5)],
        }
        for item, cases in bad.items():
            for case in cases:
                with self.subTest(item=item, case=str(case)[:40]):
                    kwargs = dict(title="제목", source_content="본문", project_id="p1", now=NOW)
                    kwargs.update(case)
                    error = raises(self, "CONTENT_INVALID", ContentProject.new, kwargs.pop("title"), kwargs.pop("source_content"), **kwargs)
                    self.assertEqual(error.slots["항목"], item)

    def test_bad_timestamps_are_refused(self):
        for stamp in ("2026-10-30", "2026-10-30 03:00:00", "2026-10-30T03:00:00+09:00", ""):
            with self.subTest(stamp=stamp):
                raises(self, "CONTENT_INVALID", ContentProject.new, "제목", "본문", now=stamp)

    def test_assets_are_checked_when_they_are_created(self):
        self.assertEqual(Asset("a.png").to_dict(), {"filename": "a.png", "alt": "", "position": 0})
        for kwargs in (dict(filename=""), dict(filename="a/b.png"), dict(filename="a\\b.png"), dict(filename=".."), dict(filename="x" * 256), dict(filename="a\x00.png"),
                       dict(filename="a.png", alt="가" * 301), dict(filename="a.png", position=-1), dict(filename="a.png", position=True), dict(filename="a.png", position="1")):
            with self.subTest(kwargs=str(kwargs)[:40]):
                raises(self, "CONTENT_INVALID", Asset, **kwargs)

    def test_a_variant_needs_a_known_platform_and_a_status_of_its_family(self):
        raises(self, "CONTENT_INVALID", PlatformVariant, "tistory")
        raises(self, "CONTENT_INVALID", PlatformVariant, "naver_a", st.APPROVED)
        self.assertEqual(PlatformVariant("naver_a", st.READY_TO_COPY).status, st.READY_TO_COPY)
        raises(self, "CONTENT_INVALID", project().variant, "tistory")


class EditTest(unittest.TestCase):
    def test_no_change_means_no_new_revision(self):
        proj = project()
        self.assertFalse(proj.edit(title=proj.title, source_content=proj.source_content, references=list(proj.references), assets=list(proj.assets), now=LATER))
        self.assertFalse(proj.edit())
        self.assertEqual((proj.revision, proj.updated_at), (1, NOW))

    def test_a_change_raises_the_revision_and_the_timestamp(self):
        proj = project()
        self.assertTrue(proj.edit(title="새 제목", now=LATER))
        self.assertEqual((proj.title, proj.revision, proj.updated_at, proj.created_at), ("새 제목", 2, LATER, NOW))
        self.assertTrue(proj.edit(references=[], now=LATER))
        self.assertTrue(proj.edit(assets=[Asset("b.png")], now=LATER))
        self.assertTrue(proj.edit(source_content="새 본문", now=LATER))
        self.assertEqual(proj.revision, 5)

    def test_a_bad_edit_changes_nothing(self):
        proj = project()
        before = proj.to_dict()
        for kwargs in (dict(title=""), dict(source_content=" "), dict(references=["javascript:alert(1)"]), dict(assets=["x"]), dict(title="새 제목", source_content="")):
            with self.subTest(kwargs=str(kwargs)[:40]):
                raises(self, "CONTENT_INVALID", proj.edit, **kwargs)
                self.assertEqual(proj.to_dict(), before)

    def test_editing_sends_reviewed_and_approved_variants_back_to_start_but_leaves_what_already_went_out(self):
        proj = project()
        proj.set_rendered("github_pages", "pages", now=NOW)
        proj.transition("github_pages", st.REVIEW_REQUIRED)
        proj.transition("github_pages", st.APPROVED)
        proj.transition("github_pages", st.COMMITTED)                                   # 이미 commit 됨 — 과거의 사실
        proj.set_rendered("blogger_en", "en", now=NOW)
        proj.transition("blogger_en", st.REVIEW_REQUIRED)
        proj.transition("blogger_en", st.APPROVED)
        proj.transition("blogger_en", st.DRAFT_SAVED, remote_id="post-1")
        to_published(proj, "naver_a", "https://blog.naver.com/me/1")                     # 공개됨
        proj.set_rendered("naver_b", "b", now=NOW)
        proj.transition("naver_b", st.REVIEW_REQUIRED)
        proj.transition("naver_b", st.READY_TO_COPY)
        proj.transition("naver_b", st.COPY_COMPLETED)
        proj.set_rendered("blogger_ko", "ko", now=NOW)
        proj.transition("blogger_ko", st.REVIEW_REQUIRED)
        self.assertTrue(proj.edit(source_content="고친 본문", now=LATER))
        self.assertEqual(proj.variant("github_pages").status, st.COMMITTED)
        self.assertEqual(proj.variant("blogger_en").status, st.DRAFT_GENERATED)
        self.assertEqual(proj.variant("blogger_en").remote_id, "post-1", "플랫폼 쪽 식별자는 지우지 않는다")
        self.assertEqual(proj.variant("naver_a").status, st.PUBLISHED_MANUAL)
        self.assertEqual(proj.variant("naver_b").status, st.DRAFT_GENERATED)
        self.assertEqual(proj.variant("blogger_ko").status, st.DRAFT_GENERATED)
        self.assertEqual(proj.variant("naver_a").published_url, "https://blog.naver.com/me/1")

    def test_a_failed_variant_is_reset_and_loses_its_error_code(self):
        proj = project()
        proj.set_rendered("naver_a", "x")
        proj.transition("naver_a", st.REVIEW_REQUIRED)
        proj.transition("naver_a", st.READY_TO_COPY)
        proj.transition("naver_a", st.PUBLISH_FAILED, error_code="NAVER_PACKAGE_INCOMPLETE")
        proj.edit(title="바뀜")
        self.assertEqual((proj.variant("naver_a").status, proj.variant("naver_a").error_code), (st.DRAFT_GENERATED, None))

    def test_after_an_edit_the_old_rendering_cannot_be_approved_until_it_is_made_again(self):
        proj = project()
        proj.set_rendered("naver_a", "처음 렌더링")
        proj.transition("naver_a", st.REVIEW_REQUIRED)
        proj.edit(title="바뀜")                                                            # 검토 중이던 것이 DRAFT_GENERATED 로
        proj.transition("naver_a", st.REVIEW_REQUIRED)                                    # 검토로는 갈 수 있지만
        error = raises(self, "STATUS_TRANSITION_INVALID", proj.transition, "naver_a", st.READY_TO_COPY)
        self.assertIn("판", error.detail)
        self.assertEqual(proj.variant("naver_a").status, st.REVIEW_REQUIRED)
        proj.transition("naver_a", st.DRAFT_GENERATED)
        proj.set_rendered("naver_a", "새 렌더링")                                           # 다시 만들면
        proj.transition("naver_a", st.REVIEW_REQUIRED)
        proj.transition("naver_a", st.READY_TO_COPY)                                      # 승인할 수 있다
        self.assertEqual(proj.variant("naver_a").rendered_revision, proj.revision)


class TransitionTest(unittest.TestCase):
    def test_each_flow_can_be_walked_to_the_end_and_records_the_address_and_time(self):
        for platform, url in (("github_pages", "https://shine88pc.github.io/post/1/"), ("blogger_en", "https://macat0722.blogspot.com/2026/10/x.html"),
                              ("blogger_ko", "https://kcyoon.blogspot.com/2026/10/y.html"), ("naver_a", "https://blog.naver.com/a/1"), ("naver_b", "https://m.blog.naver.com/b/2")):
            with self.subTest(platform=platform):
                proj = project()
                to_published(proj, platform, url)
                variant = proj.variant(platform)
                self.assertEqual((variant.status, variant.published_url, variant.published_at, variant.error_code), (st.PUBLISHED_STATES[st.family(platform)], url, LATER, None))
                self.assertEqual(proj.updated_at, LATER)

    def test_skipping_a_step_or_going_the_wrong_way_is_refused_and_nothing_changes(self):
        proj = project()
        proj.set_rendered("naver_a", "x")
        proj.transition("naver_a", st.REVIEW_REQUIRED)
        before = copy.deepcopy(proj.to_dict())
        for requested in (st.NOT_STARTED, st.COPY_COMPLETED, st.PUBLISHED_MANUAL, st.PUBLISH_FAILED, st.APPROVED, "NO_SUCH_STATE", "", None):
            with self.subTest(requested=requested):
                error = raises(self, "STATUS_TRANSITION_INVALID", proj.transition, "naver_a", requested, published_url="https://blog.naver.com/a/1")
                self.assertEqual(error.slots["현재 상태"], st.REVIEW_REQUIRED)
                self.assertEqual(proj.to_dict(), before)

    def test_publishing_needs_a_proper_address(self):
        proj = project()
        for platform in ("github_pages", "blogger_en", "naver_a"):
            proj.set_rendered(platform, "x")
        for platform, last_before in (("github_pages", st.PUSHED), ("blogger_en", st.DRAFT_SAVED), ("naver_a", st.COPY_COMPLETED)):
            for requested in main_path(st.family(platform))[2:-1]:
                proj.transition(platform, requested)
            self.assertEqual(proj.variant(platform).status, last_before)
        final = {"github_pages": st.PUBLISHED, "blogger_en": st.PUBLISHED_MANUAL, "naver_a": st.PUBLISHED_MANUAL}
        for platform, (wrong_code, bad_urls) in {
            "github_pages": ("PUBLISHED_URL_INVALID", ["http://shine88pc.github.io/a", "https://user:pw@example.com/a", "example.com/a", "https://", "https://a b.com", "javascript:alert(1)", "ftp://example.com/a"]),
            "blogger_en": ("PUBLISHED_URL_INVALID", ["http://x.blogspot.com/a", "x.blogspot.com", "https://x.blogspot.com/a b"]),
            "naver_a": ("NAVER_PUBLISH_URL_INVALID", ["https://example.com/a", "http://blog.naver.com/a/1", "https://blog.naver.com.evil.example/a", "https://evil.example/blog.naver.com", "https://user:pw@blog.naver.com/a/1"]),
        }.items():
            before = copy.deepcopy(proj.to_dict())
            raises(self, "PUBLISHED_URL_REQUIRED", proj.transition, platform, final[platform])
            raises(self, "PUBLISHED_URL_REQUIRED", proj.transition, platform, final[platform], published_url="")
            for url in bad_urls:
                with self.subTest(platform=platform, url=url):
                    raises(self, wrong_code, proj.transition, platform, final[platform], published_url=url)
            self.assertEqual(proj.to_dict(), before, "거절된 시도는 아무것도 바꾸지 않는다")

    def test_published_states_cannot_be_left(self):
        proj = project()
        to_published(proj, "naver_a", "https://blog.naver.com/a/1")
        for requested in statuses("naver_a"):
            with self.subTest(requested=requested):
                raises(self, "STATUS_TRANSITION_INVALID", proj.transition, "naver_a", requested, published_url="https://blog.naver.com/a/2", error_code="DISK_FULL")
        self.assertEqual(proj.variant("naver_a").published_url, "https://blog.naver.com/a/1")

    def test_failure_needs_a_known_error_code_and_the_way_back_clears_it(self):
        proj = project()
        proj.set_rendered("github_pages", "x")
        for requested in (st.REVIEW_REQUIRED, st.APPROVED, st.COMMITTED):
            proj.transition("github_pages", requested)
        for code in (None, "", "NO_SUCH_CODE", 5):
            with self.subTest(code=code):
                raises(self, "CONTENT_INVALID", proj.transition, "github_pages", st.PUBLISH_FAILED, error_code=code)
        self.assertEqual(proj.variant("github_pages").status, st.COMMITTED)
        proj.transition("github_pages", st.PUBLISH_FAILED, error_code="GIT_PUSH_AUTH")
        self.assertEqual((proj.variant("github_pages").status, proj.variant("github_pages").error_code), (st.PUBLISH_FAILED, "GIT_PUSH_AUTH"))
        proj.transition("github_pages", st.REVIEW_REQUIRED)
        self.assertIsNone(proj.variant("github_pages").error_code)
        self.assertEqual(CATALOG["GIT_PUSH_AUTH"].code, "GIT_PUSH_AUTH")

    def test_the_platform_identifier_is_checked_and_kept(self):
        proj = project()
        proj.set_rendered("blogger_en", "x")
        proj.transition("blogger_en", st.REVIEW_REQUIRED)
        proj.transition("blogger_en", st.APPROVED)
        for bad in ("", " ", "a b", "x" * 201, 5):
            with self.subTest(remote_id=bad):
                raises(self, "CONTENT_INVALID", proj.transition, "blogger_en", st.DRAFT_SAVED, remote_id=bad)
        self.assertEqual((proj.variant("blogger_en").status, proj.variant("blogger_en").remote_id), (st.APPROVED, None))
        proj.transition("blogger_en", st.DRAFT_SAVED, remote_id="1234567890")
        self.assertEqual(proj.variant("blogger_en").remote_id, "1234567890")

    def test_rendering_again_is_allowed_from_review_or_failure_but_not_after_publishing_or_approval(self):
        proj = project()
        proj.set_rendered("naver_a", "처음")
        proj.transition("naver_a", st.REVIEW_REQUIRED)
        proj.set_rendered("naver_a", "다시")                                                # 검토 중에는 되돌아가 다시 만든다
        self.assertEqual((proj.variant("naver_a").status, proj.variant("naver_a").rendered), (st.DRAFT_GENERATED, "다시"))
        proj.transition("naver_a", st.REVIEW_REQUIRED)
        proj.transition("naver_a", st.READY_TO_COPY)
        raises(self, "STATUS_TRANSITION_INVALID", proj.set_rendered, "naver_a", "승인 뒤에 몰래")
        self.assertEqual(proj.variant("naver_a").rendered, "다시")
        for bad in ("", "  ", None):
            with self.subTest(text=bad):
                raises(self, "CONTENT_INVALID", project().set_rendered, "naver_a", bad)


class SerializationTest(unittest.TestCase):
    def finished(self):
        proj = project()
        to_published(proj, "naver_a", "https://blog.naver.com/a/1")
        proj.set_rendered("github_pages", "pages")
        proj.transition("github_pages", st.REVIEW_REQUIRED)
        proj.transition("github_pages", st.APPROVED)
        proj.transition("github_pages", st.PUBLISH_FAILED, error_code="ACTIONS_RUN_FAILED")
        return proj

    def test_the_stored_shape_round_trips_through_json(self):
        proj = self.finished()
        data = json.loads(json.dumps(proj.to_dict(), ensure_ascii=False))
        again = ContentProject.from_dict(data)
        self.assertEqual(again.to_dict(), proj.to_dict())
        self.assertEqual(again.revision, proj.revision)
        self.assertEqual(again.variant("naver_a").published_url, "https://blog.naver.com/a/1")
        self.assertEqual(again.assets, proj.assets)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(list(data["variants"]), list(PLATFORMS))

    def test_a_loaded_project_keeps_working(self):
        again = ContentProject.from_dict(json.loads(json.dumps(self.finished().to_dict())))
        again.edit(title="불러온 뒤 고침")
        self.assertEqual(again.variant("github_pages").status, st.DRAFT_GENERATED)
        self.assertEqual(again.variant("naver_a").status, st.PUBLISHED_MANUAL)

    def test_the_stored_shape_has_no_secrets_or_extra_keys(self):
        data = self.finished().to_dict()
        self.assertEqual(set(data), {"schema", "project_id", "title", "source_content", "references", "assets", "created_at", "updated_at", "revision", "variants"})
        self.assertEqual(set(data["variants"]["naver_a"]), {"status", "rendered", "rendered_revision", "published_url", "published_at", "remote_id", "error_code"})

    def test_anything_that_does_not_fit_is_refused(self):
        def mutate(change):
            data = copy.deepcopy(self.finished().to_dict())
            change(data)
            return data

        cases = {
            "다른 형식 번호": lambda d: d.update(schema=2),
            "형식 번호 없음": lambda d: d.pop("schema"),
            "모르는 칸": lambda d: d.update(extra=1),
            "빠진 칸": lambda d: d.pop("revision"),
            "판 번호 0": lambda d: d.update(revision=0),
            "판 번호 글자": lambda d: d.update(revision="1"),
            "판 번호 참거짓": lambda d: d.update(revision=True),
            "시각 모양": lambda d: d.update(created_at="어제"),
            "제목 비어 있음": lambda d: d.update(title=""),
            "출처 주소 문자열": lambda d: d.update(references="https://example.com"),
            "출처 주소 나쁨": lambda d: d.update(references=["file:///etc/passwd"]),
            "이미지가 문자열": lambda d: d.update(assets=["a.png"]),
            "이미지 칸이 모름": lambda d: d.update(assets=[{"filename": "a.png", "alt": "", "position": 0, "extra": 1}]),
            "이미지 경로": lambda d: d.update(assets=[{"filename": "../a.png", "alt": "", "position": 0}]),
            "플랫폼 빠짐": lambda d: d["variants"].pop("naver_b"),
            "모르는 플랫폼": lambda d: d["variants"].update(tistory=copy.deepcopy(d["variants"]["naver_a"])),
            "변형이 목록": lambda d: d["variants"].update(naver_b=[]),
            "변형 칸 빠짐": lambda d: d["variants"]["naver_b"].pop("status"),
            "변형 칸 더 있음": lambda d: d["variants"]["naver_b"].update(extra=1),
            "다른 플랫폼 상태": lambda d: d["variants"]["naver_b"].update(status=st.APPROVED),
            "공개인데 주소 없음": lambda d: d["variants"]["naver_a"].update(published_url=None),
            "공개인데 시각 없음": lambda d: d["variants"]["naver_a"].update(published_at=None),
            "공개 주소가 남의 사이트": lambda d: d["variants"]["naver_a"].update(published_url="https://example.com/a"),
            "공개 전인데 주소": lambda d: d["variants"]["naver_b"].update(published_url="https://blog.naver.com/b/1"),
            "실패인데 코드 없음": lambda d: d["variants"]["github_pages"].update(error_code=None),
            "실패 코드 모름": lambda d: d["variants"]["github_pages"].update(error_code="NO_SUCH_CODE"),
            "실패 아닌데 코드": lambda d: d["variants"]["naver_b"].update(error_code="DISK_FULL"),
            "렌더링 판이 미래": lambda d: d["variants"]["github_pages"].update(rendered_revision=99),
            "승인인데 낡은 판": lambda d: d["variants"]["blogger_en"].update(status=st.APPROVED, rendered="x", rendered_revision=1) or d.update(revision=2),
            "렌더링이 숫자": lambda d: d["variants"]["naver_b"].update(rendered=5),
            "식별자가 숫자": lambda d: d["variants"]["naver_b"].update(remote_id=5),
        }
        for name, change in cases.items():
            with self.subTest(name):
                raises(self, "CONTENT_INVALID", ContentProject.from_dict, mutate(change))
        for not_a_dict in (None, [], "text", 5):
            with self.subTest(not_a_dict=not_a_dict):
                raises(self, "CONTENT_INVALID", ContentProject.from_dict, not_a_dict)


if __name__ == "__main__":
    unittest.main()
