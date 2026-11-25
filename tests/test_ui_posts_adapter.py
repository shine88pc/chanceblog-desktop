"""글 검토 화면의 실제 공급자(`ui/posts_adapter.py`) 시험 — **진짜 서비스**를 임시 데이터 폴더에서 돌린다(네트워크·git·실제 키 없음, PySide6 없이 돈다).

지키는 것:
  1) 가져오기(Markdown·HTML·파일)가 서비스의 검사(비밀 모양·크기·제목)를 그대로 거치고, 걸리면 아무것도 저장하지 않으며 입력한 글을 되풀이하지 않는 고정 문장으로 알린다(M02·M03).
  2) 읽기(목록·글·파일)는 데이터 폴더를 한 바이트도 바꾸지 않고 파일이나 폴더도 만들지 않는다.
  3) 검토 시작이 서비스의 관문 결과·네이버 경고·유사도를 `ReviewReport` 로 옮기고, 글에 이미 저장된 키 모양·건강 효과 단정도 잡는다(M08–M11·M14).
  4) 승인은 글이 바뀌었으면 하지 않고 서비스가 승인 순간 관문을 다시 검사한다. 승인 취소는 검토 중으로 되돌린다(M12·M13).
  5) 끝까지 돌려도 데이터 폴더 밖에 아무것도 생기지 않고 git·네트워크·하위 프로세스를 부르지 않으며 외부 쓰기 어댑터가 없다.
  6) 가짜 공급자와 같은 일을 하면 같은 상태 순서를 낸다(가짜가 실제와 다르게 굴지 않는다).
가짜 비밀은 조립한 문자열이고 실제 글·블로그 이름은 어디에도 없다.
"""
import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402
from chanceblog_desktop.ui import adapters, posts_adapter  # noqa: E402
from chanceblog_desktop.ui.core import app_state, post_fake, posts, text  # noqa: E402

T = text.T
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
KEY = ss.KEY
NL = chr(10)
VALUES = posts.PagesValues("경제·일", "ko", "https://images.example.invalid/a.jpg", ("에너지", "생활"), "")


def tree_stats(root):
    """폴더 안 모든 파일의 (경로, 크기, 수정 시각, 내용 지문) — 읽기가 아무것도 안 바꿨음을 본다."""
    root = Path(root)
    return {path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) for path in sorted(root.rglob("*")) if path.is_file()}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = ss.make_ctx(self.tmp.name, repo="")
        self.provider = posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: self.ctx)
        self.root = Path(self.tmp.name)

    def do_import(self, title="에너지 절약 습관", body=None, kind="markdown"):
        return self.provider.import_post(posts.ImportRequest(kind, title, body if body is not None else ss.ko_text()), SAFE, NEVER)

    def do_review(self, project_id, platform=posts.PAGES, values=VALUES):
        return self.provider.review_post(posts.ReviewRequest(project_id, platform, values if platform == posts.PAGES else None), SAFE, NEVER)

    def do_approve(self, project_id, revision, platform=posts.PAGES):
        return self.provider.approve_post(posts.ApproveRequest(project_id, platform, revision), SAFE, NEVER)

    def failure_of(self, call, *args, **kwargs):
        with self.assertRaises(posts.PostFailure) as raised:
            call(*args, **kwargs)
        return raised.exception

    def status(self, project_id, platform=posts.PAGES):
        return ss.status_of(self.ctx, project_id, platform)


class PostsAdapterImportTest(Base):
    def test_a_markdown_post_is_saved_and_comes_back_with_its_preview_and_all_states_not_started(self):
        outcome = self.do_import()
        detail = outcome.detail
        self.assertEqual(outcome.kind, "imported")
        self.assertEqual((detail.revision, detail.title, detail.sample), (1, "에너지 절약 습관", False))
        self.assertEqual([(item.platform, item.status) for item in detail.platforms], [(key, st.NOT_STARTED) for key in posts.PLATFORMS])
        self.assertGreater(detail.preview.total, 3)
        self.assertEqual(projects.show_project(self.ctx, detail.project_id).source_content, ss.ko_text())
        listing = self.provider.load_posts(SAFE, NEVER)
        self.assertEqual([(row.project_id, row.title, row.statuses) for row in listing.rows], [(detail.project_id, "에너지 절약 습관", tuple((key, st.NOT_STARTED) for key in posts.PLATFORMS))])

    def test_the_title_is_trimmed_and_the_body_is_saved_as_typed(self):
        outcome = self.do_import("  가나다  ", "## 소제목\n\n문단.")
        view = projects.show_project(self.ctx, outcome.detail.project_id)
        self.assertEqual((view.title, view.source_content), ("가나다", "## 소제목\n\n문단."))

    def test_an_html_post_becomes_markdown_with_scripts_and_attributes_gone(self):
        html = "<h2>소제목</h2><p onclick='x()'>문단 <strong>굵게</strong></p><script>alert(1)</script>"
        outcome = self.do_import("옛 글", html, kind="html")
        saved = projects.show_project(self.ctx, outcome.detail.project_id).source_content
        for banned in ("script", "onclick", "alert"):
            self.assertNotIn(banned, saved.lower() if banned != "alert" else saved)
        self.assertIn("소제목", saved)
        self.assertIn("**굵게**", saved)

    def test_a_key_shaped_post_is_refused_with_place_and_kind_and_nothing_is_saved(self):
        failure = self.failure_of(self.do_import, "키 글", "첫 줄" + NL + "둘째 " + KEY + " 줄")
        self.assertEqual((failure.kind, failure.code), ("secret", "SECRET_SHAPE_FOUND"))
        self.assertIn("본문 2번째 줄", failure.user_message)
        self.assertIn("Google API 키", failure.user_message)
        self.assertNotIn(KEY[:10], failure.user_message + repr(failure.__dict__))
        self.assertFalse(self.ctx.workspace.store_path.exists() and projects.list_projects(self.ctx), "저장하지 않았다")

    def test_a_key_shaped_title_is_refused_too(self):
        failure = self.failure_of(self.do_import, "제목 " + KEY, ss.ko_text())
        self.assertEqual(failure.kind, "secret")
        self.assertIn("제목", failure.user_message)

    def test_a_title_with_a_tag_is_refused_with_a_title_sentence(self):
        failure = self.failure_of(self.do_import, "<b>굵은</b> 제목", ss.ko_text())
        self.assertEqual((failure.kind, failure.code), ("check", "CHECK_FAILED"))
        self.assertEqual(failure.user_message, T["post_fail_check"])

    def test_a_too_long_title_names_the_field(self):
        failure = self.failure_of(self.do_import, "가" * 201, ss.ko_text())
        self.assertEqual(failure.kind, "input")
        self.assertIn("제목", failure.user_message)

    def test_pasted_text_gets_the_same_limits_as_a_file_with_the_same_sentences(self):
        for body in ("본문" + chr(0) + "널 글자", "가" * 100_001, "\u200b \u200b  "):
            with self.subTest(length=len(body)):
                failure = self.failure_of(self.do_import, "글", body)
                self.assertEqual(failure.kind, "input")
                self.assertTrue(failure.user_message.startswith("붙여 넣은 글을 받지 못했어요"), failure.user_message)
        self.assertFalse(self.ctx.workspace.store_path.exists())

    def test_the_hundred_thousand_character_limit_is_exact(self):
        body = ("가" * 99_999 + NL)[:100_000]
        self.assertEqual(self.do_import("경계 글", body).kind, "imported")

    def test_a_file_is_read_with_its_encoding_and_a_title_suggestion(self):
        path = self.root / "내 글.md"
        path.write_bytes(("## 소제목" + NL + NL + "한글 문단이에요.").encode("utf-8"))
        outcome = self.provider.read_import_file(str(path), SAFE, NEVER)
        self.assertEqual((outcome.kind, outcome.file.name, outcome.file.encoding, outcome.file.chars), ("file", "내 글", "utf-8", len("## 소제목" + NL + NL + "한글 문단이에요.")))
        self.assertIn("한글 문단이에요", outcome.file.text)
        old = self.root / "옛 글.txt"
        old.write_bytes("한글 문단이에요 옛 메모장".encode("cp949"))
        self.assertEqual(self.provider.read_import_file(str(old), SAFE, NEVER).file.encoding, "cp949")

    def test_reading_a_file_never_changes_it_or_creates_anything(self):
        path = self.root / "글.md"
        path.write_bytes("문단".encode("utf-8"))
        before = tree_stats(self.root)
        self.provider.read_import_file(str(path), SAFE, NEVER)
        self.assertEqual(tree_stats(self.root), before)

    def test_a_file_that_is_not_a_text_post_is_refused_with_the_services_fixed_sentence(self):
        cases = {"그림.exe": b"MZ", "큰 글.md": b"a" * (2 * 1024 * 1024 + 1), "빈 글.md": b"", "널 글.md": b"a" + bytes(1) + b"b", "UTF16 글.md": "가나다".encode("utf-16")}
        for name, data in cases.items():
            path = self.root / name
            path.write_bytes(data)
            with self.subTest(name=name):
                failure = self.failure_of(self.provider.read_import_file, str(path), SAFE, NEVER)
                self.assertEqual((failure.kind, failure.code), ("file", "CONTENT_INVALID"))
                self.assertTrue(failure.user_message.startswith("파일을 읽지 못했어요: "))
                self.assertNotIn(name.split(".")[0], failure.user_message, "파일 이름을 되풀이하지 않는다")
                self.assertNotIn(str(self.root), failure.user_message)
        self.assertEqual(self.failure_of(self.provider.read_import_file, str(self.root / "없는 글.md"), SAFE, NEVER).kind, "file")
        self.assertEqual(self.failure_of(self.provider.read_import_file, "https://example.invalid/a.md", SAFE, NEVER).kind, "file", "인터넷 주소는 읽지 않는다")


class PostsAdapterReadTest(Base):
    def test_reading_an_empty_data_folder_is_an_empty_list_and_creates_nothing(self):
        before = tree_stats(self.root) if self.root.exists() else {}
        data = self.provider.load_posts(SAFE, NEVER)
        self.assertEqual((data.state, data.rows, data.profiles, data.sample, data.offline), ("missing", (), (), False, False))
        self.assertEqual(tree_stats(self.root) if self.root.exists() else {}, before)
        self.assertFalse(self.ctx.workspace.root.exists() and self.ctx.workspace.store_path.exists(), "읽기만 하므로 글 저장소 파일을 만들지 않는다")

    def test_listing_and_opening_posts_never_change_a_byte_of_the_data_folder(self):
        first = self.do_import("첫 글").detail
        self.do_import("둘째 글")
        self.do_review(first.project_id)
        before = tree_stats(self.ctx.workspace.root)
        listing = self.provider.load_posts(SAFE, NEVER)
        self.provider.load_post(first.project_id, SAFE, NEVER)
        self.assertEqual(len(listing.rows), 2)
        self.assertEqual(tree_stats(self.ctx.workspace.root), before)

    def test_the_list_is_newest_first_and_carries_only_the_three_platforms(self):
        ids = []
        for title in ("가", "나", "다"):
            ids.append(self.do_import(title).detail.project_id)
            self.ctx.clock.advance(seconds=5)
        listing = self.provider.load_posts(SAFE, NEVER)
        self.assertEqual([row.project_id for row in listing.rows], list(reversed(ids)))
        for row in listing.rows:
            self.assertEqual([key for key, _status in row.statuses], list(posts.PLATFORMS))

    def test_a_broken_row_is_listed_as_unreadable_and_does_not_stop_the_others(self):
        good = self.do_import("멀쩡한 글").detail.project_id
        bad = self.do_import("깨질 글").detail.project_id
        import sqlite3
        connection = sqlite3.connect(str(self.ctx.workspace.store_path))
        connection.execute("UPDATE projects SET data = ? WHERE project_id = ?", ("not json", bad))
        connection.commit()
        connection.close()
        listing = self.provider.load_posts(SAFE, NEVER)
        found = {row.project_id: row for row in listing.rows}
        self.assertEqual(found[good].error, "")
        self.assertTrue(found[bad].error)
        self.assertEqual(found[bad].statuses, ())

    def test_naver_profiles_are_known_only_when_the_settings_have_them_and_a_broken_file_turns_them_off(self):
        self.do_import("글")
        self.assertEqual(self.provider.load_posts(SAFE, NEVER).profiles, ())
        ss.naver_profiles(self.ctx, both=False)
        self.assertEqual(self.provider.load_posts(SAFE, NEVER).profiles, ("naver_a",))
        ss.naver_profiles(self.ctx)
        self.assertEqual(self.provider.load_posts(SAFE, NEVER).profiles, ("naver_a", "naver_b"))
        self.ctx.workspace.settings_path.write_text("not json", encoding="utf-8")
        self.assertEqual(self.provider.load_posts(SAFE, NEVER).profiles, (), "설정 파일을 못 읽어도 글 목록은 읽힌다")

    def test_a_post_that_does_not_exist_is_not_found_with_an_easy_sentence(self):
        self.do_import("글")
        failure = self.failure_of(self.provider.load_post, "없는번호가한참길다", SAFE, NEVER)
        self.assertEqual((failure.kind, failure.code), ("notfound", "CONTENT_NOT_FOUND"))
        self.assertEqual(failure.user_message, T["post_fail_notfound"])

    def test_an_unreadable_store_is_an_easy_sentence_with_the_code_kept_apart(self):
        self.do_import("글")
        self.ctx.workspace.store_path.write_bytes(b"this is not a database at all" * 20)
        failure = self.failure_of(self.provider.load_posts, SAFE, NEVER)
        self.assertEqual(failure.kind, "corrupt")
        self.assertEqual(failure.user_message, T["post_fail_corrupt"])
        self.assertTrue(failure.code)
        self.assertNotIn(failure.code, failure.user_message)

    def test_a_data_folder_that_was_chosen_but_is_missing_is_an_easy_sentence(self):
        provider = posts_adapter.ServicePostsProvider(str(self.root / "없는 폴더"))
        failure = self.failure_of(provider.load_posts, SAFE, NEVER)
        self.assertEqual((failure.user_message, failure.kind), (T["data_dir_missing"], "io"))

    def test_an_unsafe_data_folder_is_an_easy_sentence_without_the_path(self):
        def refuse(data_dir=None):
            raise AppError("DATA_DIR_UNSAFE", {"경로": "C:/비밀 경로/폴더"}, detail="git 저장소 안이다")
        provider = posts_adapter.ServicePostsProvider(context_factory=refuse)
        failure = self.failure_of(provider.load_posts, SAFE, NEVER)
        self.assertEqual((failure.kind, failure.user_message), ("io", T["post_fail_io_read"]), "목록을 읽다가 난 문제는 '쓰지 못했어요' 가 아니라 읽기 문장이다")
        self.assertNotIn("비밀 경로", failure.user_message)


class PostsAdapterReviewTest(Base):
    def test_a_pages_review_moves_the_state_and_reports_the_gate_the_summary_and_the_two_checks(self):
        project_id = self.do_import().detail.project_id
        outcome = self.do_review(project_id)
        report = outcome.review
        self.assertEqual(outcome.kind, "reviewed")
        self.assertEqual((report.project_id, report.platform, report.revision, report.status), (project_id, posts.PAGES, 1, st.REVIEW_REQUIRED))
        self.assertEqual((report.gate_ok, report.gate_codes, report.warnings, report.spots, report.similarity, report.sample), (True, (), (), (), None, False))
        self.assertEqual(report.health.stage, "general")
        self.assertEqual(len(report.summary), 1)
        self.assertIn("경제·일", report.summary[0])
        self.assertIn("한국어", report.summary[0])
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)
        self.assertEqual(outcome.detail.platform(posts.PAGES).status, st.REVIEW_REQUIRED)
        self.assertEqual(outcome.detail.platform(posts.PAGES).rendered_revision, 1)
        self.assertTrue(outcome.detail.platform(posts.PAGES).has_rendering)

    def test_a_blocked_gate_is_reported_with_codes_and_the_folded_reasons(self):
        project_id = self.do_import("짧은 글", "## 짧음" + NL + NL + "<div>태그</div>").detail.project_id
        report = self.do_review(project_id).review
        self.assertFalse(report.gate_ok)
        self.assertLessEqual({"LEN_SHORT", "LEN_BODY", "RAW_HTML"}, set(report.gate_codes))
        self.assertTrue(all(reason.startswith("[") for reason in report.gate_details))
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED, "검토 요청은 막지 않고 결과를 보여 준다")

    def test_the_review_values_the_service_refuses_become_an_easy_sentence_and_change_nothing(self):
        project_id = self.do_import().detail.project_id
        before = tree_stats(self.ctx.workspace.root)
        failure = self.failure_of(self.do_review, project_id, values=posts.PagesValues("<b>분야</b>", "ko", "https://images.example.invalid/a.jpg", (), ""))
        self.assertEqual((failure.kind, failure.code), ("check", "CHECK_FAILED"))
        self.assertEqual(failure.user_message, T["post_gate_header_value"])
        self.assertEqual(tree_stats(self.ctx.workspace.root), before)
        key_failure = self.failure_of(self.do_review, project_id, values=posts.PagesValues("분야 " + KEY, "ko", "https://images.example.invalid/a.jpg", (), ""))
        self.assertEqual(key_failure.kind, "secret")
        self.assertNotIn(KEY[:10], key_failure.user_message)

    def test_a_stored_key_shape_and_a_stored_health_claim_are_caught_by_the_review(self):
        project_id = self.do_import().detail.project_id
        ss.inject_text(self.ctx, project_id, text=ss.ko_text() + NL + NL + "이 영양제를 먹으면 통증이 완전히 사라집니다. 맨 끝에 " + KEY)
        report = self.do_review(project_id).review
        self.assertEqual(report.health.stage, "stop")
        self.assertEqual(report.spots[0][0], T["drf_where_body"])
        self.assertEqual(report.spots[0][2], "Google API 키")
        self.assertNotIn(KEY, repr(report), "검토 결과에는 키 글이 없다")
        self.assertNotIn(KEY[:10], repr(report.health.places))

    def test_a_stored_key_shape_in_an_image_description_is_caught_by_the_review_and_by_the_last_check_at_approval(self):
        from chanceblog_desktop.content.model import Asset
        project_id = self.do_import().detail.project_id
        self.do_review(project_id)
        with ctx_store(self.ctx, project_id) as (store, project):
            project.assets = (Asset("a.png", alt="설명 " + KEY),)                      # 옛 버전이 저장한 것처럼 보관함에 직접 — 서비스의 쓰기 길은 이제 이 칸도 거절한다
            store.save(project)
        report = self.do_review(project_id).review
        self.assertEqual((report.spots[0][0], report.spots[0][2]), (T["post_where_assets"], "Google API 키"))
        self.assertNotIn(KEY[:10], repr(report))
        failure = self.failure_of(self.do_approve, project_id, 1)
        self.assertEqual((failure.kind, failure.code, failure.user_message), ("gate", "REVIEW_BLOCKED", T["post_fail_blocked"]))
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED, "승인되지 않았다")

    def test_a_stored_key_shape_in_a_reference_is_caught_by_the_review_and_by_the_last_check_at_approval(self):
        """출처(references) 칸(독립 검증 Q 권고-3) — 이미지 칸 시험과 같은 방식: 옛 버전이 저장한 것처럼 보관함에 직접 넣는다(서비스의 쓰기 길은 이 칸도 거절한다)."""
        project_id = self.do_import().detail.project_id
        self.do_review(project_id)
        with ctx_store(self.ctx, project_id) as (store, project):
            project.references = (f"https://example.invalid/page?k={KEY}",)
            store.save(project)
        report = self.do_review(project_id).review
        self.assertEqual((report.spots[0][0], report.spots[0][2]), (T["post_where_refs"], "Google API 키"))
        self.assertNotIn(KEY[:10], repr(report))
        failure = self.failure_of(self.do_approve, project_id, 1)
        self.assertEqual((failure.kind, failure.code, failure.user_message), ("gate", "REVIEW_BLOCKED", T["post_fail_blocked"]))
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED, "승인되지 않았다")

    def test_the_detail_preview_of_a_stored_key_shape_is_masked(self):
        project_id = self.do_import().detail.project_id
        ss.inject_text(self.ctx, project_id, text="앞 글 " + KEY + " 뒤 글" + NL + NL + ss.ko_text())
        detail = self.provider.load_post(project_id, SAFE, NEVER)
        joined = NL.join(block.text for block in detail.preview.blocks)
        self.assertNotIn(KEY[:10], joined + repr(detail))
        self.assertIn("가림", joined)
        listing = self.provider.load_posts(SAFE, NEVER)
        ss.inject_text(self.ctx, project_id, title="제목 " + KEY)
        self.assertNotIn(KEY[:10], repr(self.provider.load_posts(SAFE, NEVER)), "목록 값에는 원래 제목이 있어도 repr 에 글이 나오지 않는다")
        self.assertEqual(len(listing.rows), 1)

    def test_a_naver_review_needs_a_profile_then_reports_warnings_and_a_package_summary(self):
        project_id = self.do_import().detail.project_id
        failure = self.failure_of(self.do_review, project_id, posts.NAVER_A)
        self.assertEqual((failure.kind, failure.code, failure.user_message), ("profile", "NAVER_PROFILE_MISSING", T["post_fail_profile"]))
        ss.naver_profiles(self.ctx)
        outcome = self.do_review(project_id, posts.NAVER_A)
        report = outcome.review
        self.assertEqual((report.platform, report.gate_ok, report.gate_codes, report.status), (posts.NAVER_A, True, (), st.REVIEW_REQUIRED))
        self.assertIsNone(report.similarity, "다른 블로그에 검토한 글이 없으면 비교하지 않는다")
        self.assertTrue(report.warnings, "프로필에 맞춰 알려 주는 경고(소제목 수 …)")
        self.assertIn("에너지 절약 습관", report.summary[0])
        second = self.do_review(project_id, posts.NAVER_B).review
        self.assertEqual((second.similarity.level, second.similarity.blocks), ("high", True), "같은 글을 두 블로그에 그대로 두면 막는다")
        self.assertTrue(second.similarity.reasons)

    def test_re_reviewing_an_approved_post_puts_it_back_to_review(self):
        project_id = self.do_import().detail.project_id
        self.do_review(project_id)
        self.do_approve(project_id, 1)
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.assertEqual(self.do_review(project_id).detail.platform(posts.PAGES).status, st.REVIEW_REQUIRED)

    def test_a_published_post_cannot_be_reviewed_again_and_says_the_state_does_not_allow_it(self):
        project_id = self.do_import().detail.project_id
        self.do_review(project_id)
        self.do_approve(project_id, 1)
        with ctx_store(self.ctx) as (store, project):
            project.transition(posts.PAGES, st.COMMITTED, now=self.ctx.stamp())
            project.transition(posts.PAGES, st.PUSHED, now=self.ctx.stamp())
            store.save(project)
        failure = self.failure_of(self.do_review, project_id)
        self.assertEqual((failure.kind, failure.code), ("state", "STATUS_TRANSITION_INVALID"))
        self.assertEqual(failure.user_message, T["post_fail_state"])
        self.assertEqual(self.status(project_id), st.PUSHED)


class ctx_store:
    """글 하나를 열어 고치고 저장하는 시험용 도우미 — 시험이 '다른 곳(명령줄)이 글을 바꿨다' 를 흉내 낼 때 쓴다."""

    def __init__(self, ctx, project_id=None):
        self.ctx, self.project_id = ctx, project_id

    def __enter__(self):
        self.store = self.ctx.store().__enter__()
        self.project = self.store.load(self.project_id or self.store.list()[0].project_id)
        return self.store, self.project

    def __exit__(self, *exc):
        self.store.__exit__(*exc)


class PostsAdapterApproveTest(Base):
    def reviewed(self, markdown=None, title="승인할 글", platform=posts.PAGES):
        project_id = self.do_import(title, markdown).detail.project_id
        self.do_review(project_id, platform)
        return project_id

    def test_approve_moves_a_reviewed_pages_post_to_approved_and_revoke_moves_it_back(self):
        project_id = self.reviewed()
        outcome = self.do_approve(project_id, 1)
        self.assertEqual((outcome.kind, self.status(project_id), outcome.detail.platform(posts.PAGES).status), ("approved", st.APPROVED, st.APPROVED))
        revoked = self.provider.revoke_post(posts.RevokeRequest(project_id, posts.PAGES), SAFE, NEVER)
        self.assertEqual((revoked.kind, self.status(project_id)), ("revoked", st.REVIEW_REQUIRED))

    def test_naver_approval_is_ready_to_copy(self):
        ss.naver_profiles(self.ctx)
        project_id = self.reviewed(platform=posts.NAVER_A)
        self.assertEqual(self.do_approve(project_id, 1, posts.NAVER_A).detail.platform(posts.NAVER_A).status, st.READY_TO_COPY)

    def test_the_service_checks_the_gate_again_at_the_moment_of_approval(self):
        project_id = self.reviewed(markdown="## 짧음" + NL + NL + "짧아요.")
        failure = self.failure_of(self.do_approve, project_id, 1)
        self.assertEqual((failure.kind, failure.code, failure.user_message), ("gate", "CHECK_FAILED", T["post_fail_gate"]))
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)

    def test_a_high_naver_similarity_is_refused_at_approval_without_the_override(self):
        ss.naver_profiles(self.ctx)
        project_id = self.reviewed(platform=posts.NAVER_A)
        self.do_review(project_id, posts.NAVER_B)
        failure = self.failure_of(self.do_approve, project_id, 1, posts.NAVER_B)
        self.assertEqual((failure.kind, failure.code), ("similarity", "NAVER_SIMILARITY_HIGH"))
        self.assertEqual(self.status(project_id, posts.NAVER_B), st.REVIEW_REQUIRED, "알고도 승인하기는 1a 에 없다")

    def test_a_post_changed_after_the_review_is_not_approved(self):
        project_id = self.reviewed()
        projects.edit_project(self.ctx, project_id, markdown="## 그 사이 고침" + NL + NL + ss.ko_text())
        failure = self.failure_of(self.do_approve, project_id, 1)
        self.assertEqual((failure.kind, failure.user_message), ("stale", T["post_fail_stale"]))
        self.assertEqual(self.status(project_id), st.DRAFT_GENERATED)

    def test_a_saved_rendering_of_an_older_revision_is_refused_as_stale_even_when_the_screen_names_the_current_revision(self):
        """승인 직전의 두 번째 낡음 검사(독립 검증 Q 권고-1): 요청한 판이 지금 판이어도 저장된 렌더링의 판이 다르면 '낡았다' 로 거절한다. 이 검사를 지워도 서비스가 막지만 '상태가 맞지 않는다' 로 다른 문장이 나온다."""
        project_id = self.reviewed()
        with ctx_store(self.ctx, project_id) as (store, project):
            project.revision = 2                                                          # 판만 올리고 상태는 그대로 둔 모양 — 서비스의 고치기 길은 검토 중 상태를 되돌리므로 보관함에 직접 쓴다
            store.save(project)
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)
        failure = self.failure_of(self.do_approve, project_id, 2)
        self.assertEqual((failure.kind, failure.code, failure.user_message), ("stale", "STALE", T["post_fail_stale"]))
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED, "승인되지 않았다")

    def test_a_health_claim_that_appeared_after_the_review_is_refused_by_the_last_check_at_approval(self):
        """승인 직전 재검사의 건강 효과 단정(독립 검증 Q 권고-3) — 비밀 모양은 시험이 있었고 이 칸은 없었다. 판·상태는 그대로이고 본문만 바뀐 모양이라 낡음 검사는 지나간다."""
        project_id = self.reviewed()
        with ctx_store(self.ctx, project_id) as (store, project):
            project.source_content = project.source_content + NL + NL + "이 영양제를 먹으면 통증이 완전히 사라집니다."
            store.save(project)
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)
        failure = self.failure_of(self.do_approve, project_id, 1)
        self.assertEqual((failure.kind, failure.code, failure.user_message), ("gate", "REVIEW_BLOCKED", T["post_fail_blocked"]))
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED, "승인되지 않았다")

    def test_the_lower_health_stages_are_approved_and_only_the_stop_stage_is_refused(self):
        """건강 판정의 아래쪽 경계(독립 검증 Q 권고-5)를 진짜 서비스로도: 표시 권장·근거 필요 단계의 글은 검토 결과가 막지 않고 승인된다."""
        for stage, sentence in (("mark", "피로 회복에 도움이 될 수 있어요."), ("evidence", "당뇨 환자에게 좋은 식단을 소개해요.")):
            with self.subTest(stage=stage):
                project_id = self.do_import(f"건강 {stage}", ss.ko_text() + NL + NL + sentence).detail.project_id
                report = self.do_review(project_id).review
                self.assertEqual(report.health.stage, stage)
                self.assertEqual(self.do_approve(project_id, 1).kind, "approved")
                self.assertEqual(self.status(project_id), st.APPROVED)

    def test_approving_a_post_that_was_never_reviewed_says_the_state_does_not_allow_it(self):
        project_id = self.do_import().detail.project_id
        failure = self.failure_of(self.do_approve, project_id, 1)
        self.assertEqual(failure.kind, "state")
        self.assertEqual(self.status(project_id), st.NOT_STARTED)

    def test_a_wrong_revision_or_platform_or_post_is_refused(self):
        project_id = self.reviewed()
        self.assertEqual(self.failure_of(self.do_approve, project_id, 2).kind, "stale")
        self.assertEqual(self.failure_of(self.do_approve, project_id, 1, "blogger_ko").kind, "stale")
        self.assertEqual(self.failure_of(self.do_approve, "없는글번호입니다", 1).kind, "notfound")
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)

    def test_revoke_of_a_post_that_is_not_approved_is_a_state_failure(self):
        project_id = self.reviewed()
        failure = self.failure_of(self.provider.revoke_post, posts.RevokeRequest(project_id, posts.PAGES), SAFE, NEVER)
        self.assertEqual(failure.kind, "state")
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)


class PostsAdapterFailureTest(Base):
    def test_every_service_code_maps_to_a_kind_with_one_fixed_easy_sentence(self):
        for code, kind in posts_adapter.KIND_OF_CODE.items():
            failure = posts_adapter.failure_of(AppError(code, {"항목": "제목", "위치": "본문 1번째 줄", "유형": "Google API 키"}), action="import")
            with self.subTest(code=code):
                self.assertEqual((failure.code, failure.kind in posts.KINDS_OF_FAILURE), (code, True))
                self.assertNotIn(code, failure.user_message)
                self.assertTrue(failure.user_message)
        unknown = posts_adapter.failure_of(AppError("NOT_A_REAL_CODE_AT_ALL"))
        self.assertEqual((unknown.kind, unknown.user_message), ("other", T["post_fail_other"]))

    def test_the_sentence_never_repeats_the_input_text_or_path_from_the_error(self):
        error = AppError("CONTENT_INVALID", {"항목": "제목"}, detail="입력한 글 " + KEY + " C:/비밀/경로")
        failure = posts_adapter.failure_of(error, action="import")
        self.assertNotIn(KEY[:10], failure.user_message)
        self.assertNotIn("비밀", failure.user_message)
        masked = posts_adapter.failure_of(AppError("CONTENT_INVALID", {"항목": "값 " + KEY}), action="import")
        self.assertNotIn(KEY[:10], masked.user_message)

    def test_reading_never_says_an_input_problem(self):
        failure = posts_adapter.failure_of(AppError("CONTENT_INVALID", {"항목": "제목"}), action="read")
        self.assertEqual(failure.kind, "corrupt")
        self.assertEqual(posts_adapter.failure_of(AppError("STATUS_TRANSITION_INVALID"), action="read").kind, "other")

    def test_a_problem_found_while_reading_never_says_it_could_not_write(self):
        for code in ("FILE_WRITE_FAILED", "DISK_FULL", "FILE_IN_USE", "STORE_RECOVERY_PENDING"):
            with self.subTest(code=code):
                failure = posts_adapter.failure_of(AppError(code), action="read")
                self.assertEqual((failure.kind in ("io", "disk"), failure.user_message, failure.code), (True, T["post_fail_io_read"], code))
        self.assertEqual(posts_adapter.failure_of(AppError("FILE_WRITE_FAILED"), action="import").user_message, T["post_fail_io"], "쓰다가 난 문제는 그대로 쓰기 문장이다")
        self.assertEqual(posts_adapter.failure_of(AppError("DISK_FULL"), action="approve").user_message, T["post_fail_disk"])
        self.assertNotIn("쓰지 못했어요", T["post_fail_io_read"])

    def test_a_check_failure_at_approval_is_a_gate_sentence_and_at_review_a_value_sentence(self):
        error = AppError("CHECK_FAILED", {"걸린 항목 목록": "RAW_HTML"})
        self.assertEqual(posts_adapter.failure_of(error, action="approve").kind, "gate")
        self.assertEqual(posts_adapter.failure_of(error, action="review").user_message, T["post_gate_header_value"])
        self.assertEqual(posts_adapter.failure_of(error, action="import").user_message, T["post_fail_check"])


class PostsAdapterOutsideTest(Base):
    def test_a_whole_flow_writes_only_inside_the_data_folder_and_calls_no_git_network_or_process(self):
        ctx = ss.make_ctx(self.tmp.name)                                       # 연결한 chanceblog 폴더가 있는 문맥 — 읽기(공개 주소 계산)는 해도 쓰기는 없다
        provider = posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: ctx)
        git_calls = []
        ctx.git = lambda *a, **k: git_calls.append(a)
        outside_before = {path: data for path, data in ss.tree_snapshot(self.root).items() if not path.startswith("data/")}

        def refuse(*args, **kwargs):
            raise AssertionError("바깥과 닿는 호출이 불렸다")

        with mock.patch.object(socket.socket, "connect", refuse), mock.patch.object(subprocess, "Popen", refuse), mock.patch.object(os, "system", refuse):
            ss.naver_profiles(ctx)
            first = provider.import_post(posts.ImportRequest("markdown", "에너지 절약 습관", ss.ko_text()), SAFE, NEVER).detail.project_id
            provider.review_post(posts.ReviewRequest(first, posts.PAGES, VALUES), SAFE, NEVER)
            provider.approve_post(posts.ApproveRequest(first, posts.PAGES, 1), SAFE, NEVER)
            provider.revoke_post(posts.RevokeRequest(first, posts.PAGES), SAFE, NEVER)
            provider.review_post(posts.ReviewRequest(first, posts.NAVER_A, None), SAFE, NEVER)
            provider.approve_post(posts.ApproveRequest(first, posts.NAVER_A, 1), SAFE, NEVER)
            provider.load_posts(SAFE, NEVER)
            provider.load_post(first, SAFE, NEVER)
        self.assertEqual(git_calls, [], "git 을 부르지 않는다")
        self.assertEqual([name for name in ctx.backend.calls if name[0] not in ("inspect", "expected_url")], [], "글 올리기·공개 확인 같은 일은 하나도 없다")
        outside_after = {path: data for path, data in ss.tree_snapshot(self.root).items() if not path.startswith("data/")}
        self.assertEqual(outside_after, outside_before, "데이터 폴더 밖(연결한 저장소 폴더 포함)은 한 바이트도 안 바뀐다")
        inside = sorted(path.relative_to(ctx.workspace.root).as_posix() for path in ctx.workspace.root.rglob("*") if path.is_file())
        self.assertTrue({"chanceblog.db", "settings.json"} <= set(inside), inside)
        self.assertFalse((ctx.workspace.root / "publish").exists(), "발행 기록 폴더도 만들지 않는다")
        self.assertEqual([path for path in inside if path.startswith("backups")], [], "백업도 만들지 않는다")

    def test_the_adapter_has_no_write_to_a_file_other_than_through_the_services(self):
        import ast
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "ui" / "posts_adapter.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                self.assertNotIn(name, {"write_text", "write_bytes", "unlink", "mkdir", "rmtree", "copy2", "open", "write_json"})

    def test_the_real_home_provider_pairs_this_adapter_and_the_example_provider_pairs_the_fake(self):
        pair = adapters.ServiceHomeProvider(data_dir=self.tmp.name).posts_provider()
        self.assertIsInstance(pair, posts_adapter.ServicePostsProvider)
        self.assertFalse(pair.sample)
        self.assertIsInstance(app_state.AppState(adapters.ServiceHomeProvider(data_dir=self.tmp.name)).posts_provider, posts_adapter.ServicePostsProvider)
        self.assertIsInstance(app_state.AppState().posts_provider, post_fake.FakePostsProvider)
        self.assertTrue(app_state.AppState().posts_provider.sample)


class PostsFakeMatchesRealTest(Base):
    def run_flow(self, provider, markdown):
        """같은 일을 하고 단계마다의 상태를 모은다(가짜와 실제가 같은 상태 순서를 내야 한다)."""
        steps = []
        detail = provider.import_post(posts.ImportRequest("markdown", "글", markdown), SAFE, NEVER).detail
        project_id = detail.project_id
        steps.append(detail.platform(posts.PAGES).status)
        outcome = provider.review_post(posts.ReviewRequest(project_id, posts.PAGES, VALUES), SAFE, NEVER)
        steps.append((outcome.detail.platform(posts.PAGES).status, outcome.review.gate_ok, outcome.review.health.stage, bool(outcome.review.spots)))
        try:
            steps.append(provider.approve_post(posts.ApproveRequest(project_id, posts.PAGES, detail.revision), SAFE, NEVER).detail.platform(posts.PAGES).status)
        except posts.PostFailure as failure:
            steps.append(("refused", failure.kind))
            return steps
        steps.append(provider.revoke_post(posts.RevokeRequest(project_id, posts.PAGES), SAFE, NEVER).detail.platform(posts.PAGES).status)
        return steps

    def test_the_fake_and_the_real_provider_give_the_same_state_sequence(self):
        for markdown in (ss.ko_text(), "## 짧음" + NL + NL + "짧아요.", ss.ko_text() + NL + NL + "이 영양제를 먹으면 통증이 완전히 사라집니다."):
            with self.subTest(markdown=markdown[:10]):
                with tempfile.TemporaryDirectory() as tmp:
                    ctx = ss.make_ctx(tmp, repo="")
                    real = self.run_flow(posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: ctx), markdown)
                fake = self.run_flow(post_fake.FakePostsProvider("empty"), markdown)
                self.assertEqual(real, fake)


if __name__ == "__main__":
    unittest.main()
