"""서비스 층 — 글 흐름 1b(화면)가 더한 작은 함수 여섯의 시험(D-644·D-648·D-649·D-650). 네트워크·git 없음, 임시 폴더.

지키는 것:
  1) `review.read_naver_package` 는 저장된 복사용 패키지를 **읽기만** 한다 — 복사 준비됨·복사함에서만 나오고, 검토 중에는 **승인하지 않고** 거절한다(기존 `issue_naver_package` 는 검토 중이면 승인까지 해 버린다).
     네이버 A·B 의 패키지는 각자 독립이다. 아무것도 쓰지 않는다(데이터 폴더가 한 바이트도 안 바뀐다).
  2) `review.mark_naver_copied` 는 복사 준비됨 ↔ 복사함 한 칸만 옮기고 다른 상태·값이 이상한 표시는 거절하며 글·렌더링·발행 주소를 건드리지 않는다. 그 뒤 발행 주소 기록이 이어진다.
  3) `naver_profiles.profile_for` 는 설정 파일의 프로필이 먼저이고 없으면 블로그 관리에 등록한 것에서 합쳐 읽는다(읽기만 — 파일을 만들지 않고, 깨진 설정 파일은 숨기지 않는다).
  4) `history.list_history` 는 글 저장소를 한 번 열어 승인 이후 단계의 (글, 플랫폼) 쌍을 읽는다(검토 전 상태만 빼고 모두 — 모르는 새 상태도).
  5) `worklog.read_work_log` 는 작업 로그를 칸으로 쪼개 글자표를 통과한 줄만 내고(키 모양이 든 줄은 건너뛴다) 읽기만 한다.
     (재작업 1, 독립 검증 S 권고-1·3) `logs` 폴더 자신이 링크(정션·심볼릭)이면 따라가지 않고, 영문·숫자·밑줄·붙임표가 24자 이상 이어지는 덩어리가 든 줄(엔진이 모르는 모양의 키를 낱말에 붙여 손으로 고친 줄)은 건너뛴다.
"""
import ast
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop import fslink  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.service import blog_profiles, history, naver_flow, naver_profiles, previews, projects, review, worklog  # noqa: E402
from chanceblog_desktop.security import errorlog  # noqa: E402
from chanceblog_desktop.service.naver_flow import NaverOptions  # noqa: E402

COPY_TIME = "2026-11-02T02:00:00Z"
NAVER_URL = "https://blog.naver.com/exampleaaa/223000000001"


def tree_hashes(root):
    root = Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*")) if path.is_file()}


def remove_link(path):
    """링크 자체를 지운다(목적지는 건드리지 않는다) — 이미 없으면 그대로 둔다. 정션은 `rmdir`, 심볼릭 링크는 `unlink` 다."""
    if not os.path.lexists(path):
        return
    try:
        os.unlink(path)
    except OSError:
        os.rmdir(path)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, repo="")
        ss.naver_profiles(self.ctx)
        self.project_id = projects.new_project(self.ctx, "에너지 절약 습관", ss.ko_text()).project_id

    def variant(self, platform="naver_a", project_id=None):
        return projects.show_project(self.ctx, project_id or self.project_id).variant(platform)

    def ready(self, platform="naver_a", options=None, project_id=None):
        """검토 요청 → 승인(복사 준비됨)까지 해 두고 검토 때 만든 패키지를 돌려준다."""
        project_id = project_id or self.project_id
        package = review.request_review(self.ctx, project_id, platform, naver_options=options).naver.package
        review.grant_approval(self.ctx, project_id, platform, similarity_approved=True)
        return package


class NaverPackageReadTest(Base):
    def test_it_reads_the_stored_package_when_ready_to_copy_and_again_after_the_copy_was_marked(self):
        package = self.ready()
        issue = review.read_naver_package(self.ctx.reading_only(), self.project_id, "naver_a")
        self.assertEqual((issue.status, issue.package, issue.similarity, issue.platform, issue.project_id), (st.READY_TO_COPY, package, None, "naver_a", self.project_id))
        self.assertEqual(issue.copy_text, naver_flow.copy_text(package), "복사용 글 전체는 서비스가 만든 그대로다")
        self.assertIn("[제목]", issue.copy_text)
        review.mark_naver_copied(self.ctx, self.project_id, "naver_a")
        again = review.read_naver_package(self.ctx.reading_only(), self.project_id, "naver_a")
        self.assertEqual((again.status, again.package), (st.COPY_COMPLETED, package))

    def test_reading_writes_nothing_not_even_a_byte(self):
        self.ready()
        before = tree_hashes(self.ctx.workspace.root)
        reading = self.ctx.reading_only()
        for _ in range(3):
            review.read_naver_package(reading, self.project_id, "naver_a")
        self.assertEqual(tree_hashes(self.ctx.workspace.root), before)

    def test_a_package_that_is_still_in_review_is_refused_and_is_not_approved_by_reading(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        error = ss.code_of(review.read_naver_package, self.ctx.reading_only(), self.project_id, "naver_a")
        self.assertEqual(error.code, "STATUS_TRANSITION_INVALID")
        self.assertEqual(self.variant().status, st.REVIEW_REQUIRED, "읽는 것만으로 승인되지 않는다")
        error = ss.code_of(review.read_naver_package, self.ctx, self.project_id, "naver_a")
        self.assertEqual((error.code, self.variant().status), ("STATUS_TRANSITION_INVALID", st.REVIEW_REQUIRED), "쓸 수 있는 컨텍스트로 읽어도 같다")

    def test_the_old_issue_function_would_have_approved_which_is_why_the_screen_does_not_use_it(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        review.issue_naver_package(self.ctx, self.project_id, "naver_a")
        self.assertEqual(self.variant().status, st.READY_TO_COPY)

    def test_other_states_are_refused(self):
        self.assertEqual(ss.code_of(review.read_naver_package, self.ctx, self.project_id, "naver_a").code, "STATUS_TRANSITION_INVALID", "시작 전")
        self.ready()
        review.record_naver_published(self.ctx, self.project_id, "naver_a", NAVER_URL)
        self.assertEqual(self.variant().status, st.PUBLISHED_MANUAL)
        self.assertEqual(ss.code_of(review.read_naver_package, self.ctx, self.project_id, "naver_a").code, "STATUS_TRANSITION_INVALID", "직접 발행함")

    def test_an_unknown_blog_or_post_is_refused(self):
        for blog in ("github_pages", "naver_c", "", None):
            with self.subTest(blog=blog):
                self.assertEqual(ss.code_of(review.read_naver_package, self.ctx, self.project_id, blog).code, "CONTENT_INVALID")
        self.assertEqual(ss.code_of(review.read_naver_package, self.ctx, "zzzzzzzzzzzz", "naver_a").code, "CONTENT_NOT_FOUND")

    def test_blog_a_and_blog_b_keep_their_own_independent_packages(self):
        a = self.ready("naver_a", NaverOptions(title="에이 블로그 제목", tags=("에이태그",)))
        b = self.ready("naver_b", NaverOptions(title="비 블로그 제목", body=ss.DIFFERENT, tags=("비태그",)))
        read_a = review.read_naver_package(self.ctx.reading_only(), self.project_id, "naver_a")
        read_b = review.read_naver_package(self.ctx.reading_only(), self.project_id, "naver_b")
        self.assertEqual((read_a.package, read_b.package), (a, b))
        self.assertEqual((read_a.package.title, read_b.package.title), ("에이 블로그 제목", "비 블로그 제목"))
        self.assertEqual((read_a.package.profile_key, read_b.package.profile_key), ("naver_a", "naver_b"))
        self.assertNotIn("비 블로그 제목", read_a.copy_text)
        self.assertNotIn("에이 블로그 제목", read_b.copy_text)

    def test_a_damaged_stored_package_stops_the_read(self):
        self.ready()
        with self.ctx.store() as store:
            project = store.load(self.project_id)
            project.variant("naver_a").rendered = "{"
            store.save(project)
        self.assertEqual(ss.code_of(review.read_naver_package, self.ctx, self.project_id, "naver_a").code, "CONTENT_INVALID")


class NaverCopiedTest(Base):
    def test_a_ready_post_is_marked_copied_and_can_be_taken_back(self):
        self.ready()
        before = self.variant()
        result = review.mark_naver_copied(self.ctx, self.project_id, "naver_a")
        self.assertEqual((result.status, result.platform, result.project_id), (st.COPY_COMPLETED, "naver_a", self.project_id))
        after = self.variant()
        self.assertEqual((after.status, after.rendered_revision, after.published_url, after.published_at, after.has_rendering), (st.COPY_COMPLETED, before.rendered_revision, None, None, True))
        back = review.mark_naver_copied(self.ctx, self.project_id, "naver_a", copied=False)
        self.assertEqual(back.status, st.READY_TO_COPY)
        self.assertEqual(self.variant().rendered_revision, before.rendered_revision)

    def test_it_moves_exactly_one_step_and_other_states_are_refused_without_changing_anything(self):
        review.request_review(self.ctx, self.project_id, "naver_a")
        for copied in (True, False):
            with self.subTest(state="검토 중", copied=copied):
                self.assertEqual(ss.code_of(review.mark_naver_copied, self.ctx, self.project_id, "naver_a", copied=copied).code, "STATUS_TRANSITION_INVALID")
                self.assertEqual(self.variant().status, st.REVIEW_REQUIRED)
        review.grant_approval(self.ctx, self.project_id, "naver_a", similarity_approved=True)
        self.assertEqual(ss.code_of(review.mark_naver_copied, self.ctx, self.project_id, "naver_a", copied=False).code, "STATUS_TRANSITION_INVALID", "복사 준비됨에서 복사 표시를 취소할 수는 없다")
        review.mark_naver_copied(self.ctx, self.project_id, "naver_a")
        self.assertEqual(ss.code_of(review.mark_naver_copied, self.ctx, self.project_id, "naver_a").code, "STATUS_TRANSITION_INVALID", "두 번 표시하지 않는다")
        self.assertEqual(self.variant().status, st.COPY_COMPLETED)
        review.record_naver_published(self.ctx, self.project_id, "naver_a", NAVER_URL)
        for copied in (True, False):
            with self.subTest(state="직접 발행함", copied=copied):
                self.assertEqual(ss.code_of(review.mark_naver_copied, self.ctx, self.project_id, "naver_a", copied=copied).code, "STATUS_TRANSITION_INVALID")
        self.assertEqual(self.variant().status, st.PUBLISHED_MANUAL)

    def test_the_copy_flag_must_be_a_real_boolean(self):
        self.ready()
        for bad in (1, 0, "yes", "True", None, [], 1.0):
            with self.subTest(copied=bad):
                self.assertEqual(ss.code_of(review.mark_naver_copied, self.ctx, self.project_id, "naver_a", copied=bad).code, "CONTENT_INVALID")
                self.assertEqual(self.variant().status, st.READY_TO_COPY)

    def test_an_unknown_blog_or_post_is_refused(self):
        self.ready()
        for blog in ("github_pages", "blogger_en", "naver_c", None):
            with self.subTest(blog=blog):
                self.assertEqual(ss.code_of(review.mark_naver_copied, self.ctx, self.project_id, blog).code, "CONTENT_INVALID")
        self.assertEqual(ss.code_of(review.mark_naver_copied, self.ctx, "zzzzzzzzzzzz", "naver_a").code, "CONTENT_NOT_FOUND")

    def test_the_published_address_is_recorded_after_the_copy_mark_and_also_still_without_it(self):
        self.ready()
        review.mark_naver_copied(self.ctx, self.project_id, "naver_a")
        self.assertEqual(review.record_naver_published(self.ctx, self.project_id, "naver_a", NAVER_URL).status, st.PUBLISHED_MANUAL)
        done = self.variant()
        self.assertEqual((done.published_url, done.published_at), (NAVER_URL, "2026-11-02T01:30:12Z"))
        other = projects.new_project(self.ctx, "다른 글", ss.ko_text()).project_id
        self.ready(project_id=other)
        self.assertEqual(review.record_naver_published(self.ctx, other, "naver_a", NAVER_URL).status, st.PUBLISHED_MANUAL, "기존 길(복사 표시 없이)은 그대로다")

    def test_editing_the_manuscript_withdraws_the_copied_mark_like_every_other_approval(self):
        self.ready()
        review.mark_naver_copied(self.ctx, self.project_id, "naver_a")
        projects.edit_project(self.ctx, self.project_id, markdown=ss.ko_text(extra="고친 문단입니다."))
        self.assertEqual(self.variant().status, st.DRAFT_GENERATED)
        self.assertEqual(ss.code_of(review.read_naver_package, self.ctx, self.project_id, "naver_a").code, "STATUS_TRANSITION_INVALID")

    def test_marking_one_blog_does_not_touch_the_other(self):
        self.ready("naver_a")
        self.ready("naver_b", NaverOptions(body=ss.DIFFERENT))
        review.mark_naver_copied(self.ctx, self.project_id, "naver_a")
        self.assertEqual((self.variant("naver_a").status, self.variant("naver_b").status), (st.COPY_COMPLETED, st.READY_TO_COPY))

    def test_only_the_data_folders_store_file_changes(self):
        self.ready()
        before = tree_hashes(self.ctx.workspace.root)
        review.mark_naver_copied(self.ctx, self.project_id, "naver_a")
        changed = {name for name, digest in tree_hashes(self.ctx.workspace.root).items() if before.get(name) != digest}
        self.assertTrue(changed <= {"chanceblog.db", "chanceblog.db-wal", "chanceblog.db-shm", "chanceblog.db-journal"} | {name for name in before if name.startswith("backups/")}, changed)


class ChannelFile:
    """블로그 관리 화면이 쓰는 채널 프로필 파일에 슬롯을 등록해 두는 도우미(진짜 서비스 함수로 쓴다)."""

    @staticmethod
    def register(ctx, key, **fields):
        version = blog_profiles.read_snapshot(ctx).version
        return blog_profiles.save_slot(ctx, key, fields, expected_version=version)


class NaverProfilesMergeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, repo="")

    def settings_file(self):
        return self.ctx.workspace.settings_path

    def test_a_blog_registered_only_in_the_blog_screen_gives_a_profile(self):
        ChannelFile.register(self.ctx, "naver_a", display_name="에이 블로그", blog_ref="exampleid", main_topics=["생활", "절약"], audience="직장인", tone="차분한 말투")
        profile = naver_profiles.profile_for(self.ctx, "naver_a")
        self.assertEqual((profile.key, profile.display_name, profile.blog_url, profile.topic, profile.audience, profile.tone),
                         ("naver_a", "에이 블로그", "https://blog.naver.com/exampleid", "생활, 절약", "직장인", "차분한 말투"))
        self.assertFalse(self.settings_file().exists(), "합쳐 읽기만 하고 설정 파일을 만들지 않는다")

    def test_a_full_naver_address_in_the_blog_ref_is_used_as_it_is(self):
        ChannelFile.register(self.ctx, "naver_b", display_name="비 블로그", blog_ref="https://blog.naver.com/examplebbb")
        self.assertEqual(naver_profiles.profile_for(self.ctx, "naver_b").blog_url, "https://blog.naver.com/examplebbb")

    def test_the_settings_profile_wins_over_the_blog_screen(self):
        ss.naver_profiles(self.ctx)
        ChannelFile.register(self.ctx, "naver_a", display_name="다른 이름", blog_ref="otherid")
        profile = naver_profiles.profile_for(self.ctx, "naver_a")
        self.assertEqual((profile.display_name, profile.blog_url), ("블로그 에이", "https://blog.naver.com/exampleaaa"), "명령줄로 정한 값이 먼저다")

    def test_a_slot_without_a_blog_id_or_address_gives_no_profile(self):
        ChannelFile.register(self.ctx, "naver_a", display_name="이름만 있는 블로그")
        error = ss.code_of(naver_profiles.profile_for, self.ctx, "naver_a")
        self.assertEqual((error.code, error.slots["블로그"]), ("NAVER_PROFILE_MISSING", "naver_a"))

    def test_an_address_that_is_not_a_naver_blog_gives_no_profile(self):
        ChannelFile.register(self.ctx, "naver_a", display_name="다른 곳", blog_ref="https://example.invalid/somewhere")
        self.assertEqual(ss.code_of(naver_profiles.profile_for, self.ctx, "naver_a").code, "NAVER_PROFILE_MISSING")

    def test_a_damaged_blog_screen_file_means_missing_but_a_damaged_settings_file_is_not_hidden(self):
        folder = self.ctx.workspace.root / "topic_engine"
        folder.mkdir(parents=True)
        (folder / "channel_profiles.json").write_bytes(b"{broken")
        self.assertEqual(ss.code_of(naver_profiles.profile_for, self.ctx, "naver_a").code, "NAVER_PROFILE_MISSING")
        self.assertEqual(naver_profiles.profile_keys(self.ctx), ())
        self.ctx.workspace.settings_path.write_text("{broken", encoding="utf-8")
        self.assertEqual(ss.code_of(naver_profiles.profile_for, self.ctx, "naver_a").code, "SETTINGS_INVALID")
        self.assertEqual(ss.code_of(naver_profiles.profile_keys, self.ctx).code, "SETTINGS_INVALID")

    def test_the_profile_keys_follow_both_places_in_order(self):
        self.assertEqual(naver_profiles.profile_keys(self.ctx), ())
        ChannelFile.register(self.ctx, "naver_b", display_name="비 블로그", blog_ref="examplebbb")
        self.assertEqual(naver_profiles.profile_keys(self.ctx), ("naver_b",))
        ss.naver_profiles(self.ctx, both=False)
        self.assertEqual(naver_profiles.profile_keys(self.ctx), ("naver_a", "naver_b"))

    def test_reading_creates_no_file_or_folder(self):
        for _ in range(2):
            self.assertEqual(naver_profiles.profile_keys(self.ctx), ())
        self.assertFalse(self.ctx.workspace.root.exists() and any(self.ctx.workspace.root.rglob("*")), "데이터 폴더에 아무것도 생기지 않았다")

    def test_a_review_works_for_someone_who_only_uses_the_screen_and_the_cli_preview_agrees(self):
        ChannelFile.register(self.ctx, "naver_a", display_name="에이 블로그", blog_ref="exampleid", main_topics=["생활", "절약"])
        project_id = projects.new_project(self.ctx, "에너지 절약 습관", ss.ko_text()).project_id
        result = review.request_review(self.ctx, project_id, "naver_a")
        self.assertEqual((result.status, result.naver.package.profile_key, result.naver.package.tags), (st.REVIEW_REQUIRED, "naver_a", ("생활", "절약")), "주요 주제 낱말이 기본 태그다")
        shown = previews.preview_naver(self.ctx, project_id)
        self.assertEqual(([item.key for item in shown.items], list(shown.missing)), (["naver_a"], ["naver_b"]))
        self.assertEqual(ss.code_of(review.request_review, self.ctx, project_id, "naver_b").code, "NAVER_PROFILE_MISSING", "등록하지 않은 블로그는 예전처럼 막힌다")

    def test_without_any_main_topic_there_is_no_tag_and_the_review_stops_with_the_missing_item_named(self):
        ChannelFile.register(self.ctx, "naver_a", display_name="에이 블로그", blog_ref="exampleid")
        project_id = projects.new_project(self.ctx, "에너지 절약 습관", ss.ko_text()).project_id
        error = ss.code_of(review.request_review, self.ctx, project_id, "naver_a")
        self.assertEqual((error.code, error.slots["항목"]), ("NAVER_PACKAGE_INCOMPLETE", "태그"))
        self.assertEqual(projects.show_project(self.ctx, project_id).variant("naver_a").status, st.NOT_STARTED, "멈추면 아무것도 저장하지 않는다")

    def test_the_three_saved_only_fields_of_the_blog_screen_never_reach_the_naver_profile(self):
        """CI 빨강 고치기(GUI1b): 블로그 관리 화면은 우선 키워드·제외 키워드·선호 글 유형을 '지금 저장만 해요' 라고 말한다(결정 D-241 — `test_ui_blogs_topic` 의 꼬리표 시험이 엔진 코드의 읽기를 막는다).
        합쳐 읽은 네이버 프로필의 '제외 주제' 는 복사 패키지의 주의 문장을 만들므로, 세 칸의 값이 실리면 그 말이 거짓이 된다 — 세 칸을 채워도 합친 프로필은 한 칸도 달라지지 않고 글에 제외 키워드가 있어도 주의 문장이 생기지 않는다."""
        from chanceblog_desktop.content.profiles import POST_TYPES
        ChannelFile.register(self.ctx, "naver_a", display_name="에이 블로그", blog_ref="exampleid", main_topics=["생활", "절약"], audience="직장인", tone="차분한 말투")
        without = naver_profiles.profile_for(self.ctx, "naver_a")
        kinds = [kind for kind in POST_TYPES if kind != without.post_type][:2]                      # 프로필의 기본 글 유형과 다른 것 — 기본값과 같으면 옮겨 읽어도 티가 나지 않는다
        self.assertEqual(len(kinds), 2)
        ChannelFile.register(self.ctx, "naver_a", priority_keywords=["난방비", "전기요금"], exclude_keywords=["에너지", "절약"], preferred_post_types=kinds)
        channel = next(item for item in blog_profiles.read_snapshot(self.ctx).profiles if item.key == "naver_a")
        self.assertEqual((channel.priority_keywords, channel.exclude_keywords, channel.preferred_post_types), (("난방비", "전기요금"), ("에너지", "절약"), tuple(kinds)), "세 칸은 저장돼 있다")
        merged = naver_profiles.profile_for(self.ctx, "naver_a")
        self.assertEqual(merged, without, "세 칸을 채워도 합친 프로필은 그대로다")
        self.assertEqual(merged.excluded_topics, (), "프로필의 제외 주제는 설정 파일의 프로필을 쓰는 사람만 채운다")
        self.assertEqual(naver_profiles.from_channel(channel), without)
        project_id = projects.new_project(self.ctx, "에너지 절약 습관", ss.ko_text()).project_id
        package = review.request_review(self.ctx, project_id, "naver_a").naver.package
        self.assertEqual([line for line in package.warnings if "제외 주제" in line], [], "제목에 제외 키워드가 있어도 주의 문장이 생기지 않는다")


class HistoryServiceTest(Base):
    def test_a_fresh_store_has_no_rows_and_review_stages_are_not_rows(self):
        self.assertEqual(history.list_history(self.ctx.reading_only()), history.History((), 0))
        review.request_review(self.ctx, self.project_id, "naver_a")
        self.assertEqual(history.list_history(self.ctx.reading_only()).rows, (), "검토 중은 발행 기록이 아니다")

    def test_after_the_approval_every_step_is_a_row_with_its_status_and_address(self):
        self.ready()
        rows = history.list_history(self.ctx.reading_only()).rows
        self.assertEqual([(row.platform, row.status, row.published_url, row.published_at) for row in rows], [("naver_a", st.READY_TO_COPY, "", "")])
        review.mark_naver_copied(self.ctx, self.project_id, "naver_a")
        review.record_naver_published(self.ctx, self.project_id, "naver_a", NAVER_URL)
        pages_id = ss.make_approved(self.ctx, title="두 번째 글")
        rows = {(row.project_id, row.platform): row for row in history.list_history(self.ctx.reading_only()).rows}
        self.assertEqual(set(rows), {(self.project_id, "naver_a"), (pages_id, "github_pages")})
        done = rows[(self.project_id, "naver_a")]
        self.assertEqual((done.status, done.published_url, done.published_at, done.title, done.revision), (st.PUBLISHED_MANUAL, NAVER_URL, "2026-11-02T01:30:12Z", "에너지 절약 습관", 1))
        self.assertEqual((rows[(pages_id, "github_pages")].status, rows[(pages_id, "github_pages")].published_url), (st.APPROVED, ""))

    def test_the_rows_carry_small_values_only_never_the_manuscript(self):
        self.ready()
        data = history.list_history(self.ctx.reading_only()).to_dict()
        self.assertNotIn(ss.KO_SENTENCE[:20], json.dumps(data, ensure_ascii=False))
        self.assertEqual(set(data["rows"][0]), {"project_id", "title", "platform", "status", "revision", "updated_at", "published_url", "published_at"})

    def test_an_unreadable_post_is_counted_and_does_not_block_the_others(self):
        self.ready()
        bad = projects.new_project(self.ctx, "깨질 글", ss.ko_text()).project_id
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path))) as db:
            db.execute("UPDATE projects SET data = ? WHERE project_id = ?", ("{깨짐", bad))
            db.commit()
        result = history.list_history(self.ctx.reading_only())
        self.assertEqual((result.unreadable, [row.project_id for row in result.rows]), (1, [self.project_id]))

    def test_a_state_the_table_does_not_know_yet_is_still_listed(self):
        """서비스에 새 상태가 생겨도(PUBPR 의 병합 대기 …) 화면이 죽지 않게 — 닫힌 목록으로 못박지 않았다. 새 상태를 시험이 직접 만들어 쓴다."""
        pages_id = ss.make_approved(self.ctx, title="새 상태 글")
        extra = {"MERGE_PENDING": ()}
        with mock.patch.dict(st.FLOWS[st.PAGES], {**extra, st.APPROVED: st.FLOWS[st.PAGES][st.APPROVED] + ("MERGE_PENDING",)}):
            with self.ctx.store() as store:
                project = store.load(pages_id)
                project.transition("github_pages", "MERGE_PENDING", now=COPY_TIME)
                store.save(project)
            rows = history.list_history(self.ctx.reading_only()).rows
            self.assertEqual([(row.platform, row.status) for row in rows], [("github_pages", "MERGE_PENDING")])

    def test_a_missing_store_file_is_not_created_by_reading(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ctx = ss.make_ctx(tmp.name, repo="")
        self.assertEqual(ss.code_of(history.list_history, ctx.reading_only()).code, "CONTENT_NOT_FOUND")
        self.assertFalse(ctx.workspace.root.exists())

    def test_the_store_is_opened_once_however_many_posts_there_are(self):
        for number in range(4):
            self.ready(project_id=projects.new_project(self.ctx, f"글 {number}", ss.ko_text()).project_id)
        with mock.patch.object(Store, "open", wraps=Store.open) as spy:
            self.assertEqual(len(history.list_history(self.ctx.reading_only()).rows), 4)
        self.assertEqual(spy.call_count, 1)

    def test_listing_changes_nothing(self):
        self.ready()
        before = tree_hashes(self.ctx.workspace.root)
        history.list_history(self.ctx.reading_only())
        self.assertEqual(tree_hashes(self.ctx.workspace.root), before)


class WorkLogServiceTest(unittest.TestCase):
    GOOD = ["2026-11-24T05:30:12Z slot KeyError post_view.py:123 < shell.py:45",
            "2026-11-24T05:31:00Z thread ValueError -",
            "2026-11-24T05:32:00Z qt QtCriticalMsg qt.qpa.xcb < plugin.cpp:99"]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, repo="")
        self.folder = self.ctx.workspace.root / "logs"

    def write(self, name, lines):
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_a_missing_log_is_an_empty_result_and_nothing_is_created(self):
        result = worklog.read_work_log(self.ctx)
        self.assertEqual((result.lines, result.files, result.skipped, result.older), ((), 0, 0, 0))
        self.assertFalse(self.ctx.workspace.root.exists())

    def test_the_lines_come_back_newest_first_split_into_fields(self):
        self.write("errors.log", self.GOOD)
        result = worklog.read_work_log(self.ctx)
        self.assertEqual([line.at for line in result.lines], ["2026-11-24T05:32:00Z", "2026-11-24T05:31:00Z", "2026-11-24T05:30:12Z"])
        self.assertEqual((result.lines[2].source, result.lines[2].name, result.lines[2].places), ("slot", "KeyError", ("post_view.py:123", "shell.py:45")))
        self.assertEqual((result.lines[1].places, result.lines[0].places), ((), ("qt.qpa.xcb", "plugin.cpp:99")))
        self.assertEqual((result.files, result.skipped, result.older), (1, 0, 0))

    def test_the_three_files_are_read_oldest_to_newest_and_come_back_newest_first(self):
        self.write("errors.log.2", [self.GOOD[0]])
        self.write("errors.log.1", [self.GOOD[1]])
        self.write("errors.log", [self.GOOD[2]])
        result = worklog.read_work_log(self.ctx)
        self.assertEqual(([line.name for line in result.lines], result.files), (["QtCriticalMsg", "ValueError", "KeyError"], 3))

    def test_a_line_that_is_not_in_the_writers_shape_is_skipped_and_only_counted(self):
        self.write("errors.log", self.GOOD[:1] + ["손으로 쓴 줄 — 비밀번호는 한 줄 안에", "2026-11-24T05:31:00Z unknown KeyError a.py:1", "2026-11-24T05:31:00Z slot Key.Error a.py:1", "", "   "] + self.GOOD[1:2])
        result = worklog.read_work_log(self.ctx)
        self.assertEqual((len(result.lines), result.skipped), (2, 3))
        self.assertNotIn("비밀번호", json.dumps(result.to_dict(), ensure_ascii=False))

    def test_a_key_shaped_name_in_a_hand_edited_line_is_never_given_out_even_though_it_passes_the_character_table(self):
        fake_key = "AI" + "za" + "A" * 35                 # 구글 API 키 모양(영문·숫자뿐이라 글자표는 통과한다)
        self.write("errors.log", self.GOOD[:1] + [f"2026-11-24T05:31:00Z slot {fake_key} a.py:1", f"2026-11-24T05:32:00Z slot KeyError {fake_key}.py:2"])
        result = worklog.read_work_log(self.ctx)
        self.assertEqual((len(result.lines), result.skipped), (1, 2))
        blob = json.dumps(result.to_dict(), ensure_ascii=False)
        for start in range(0, len(fake_key) - 5, 3):
            self.assertNotIn(fake_key[start:start + 6], blob)

    def test_only_the_most_recent_lines_are_given_and_the_rest_are_counted(self):
        lines = [f"2026-11-24T05:{number // 60:02d}:{number % 60:02d}Z main Error{number} a.py:{number}" for number in range(12)]
        self.write("errors.log", lines)
        result = worklog.read_work_log(self.ctx, limit=5)
        self.assertEqual(([line.name for line in result.lines], result.older), (["Error11", "Error10", "Error9", "Error8", "Error7"], 7))

    def test_a_huge_file_is_skipped_and_a_link_is_not_followed(self):
        self.write("errors.log", self.GOOD[:1])
        (self.folder / "errors.log.1").write_bytes(b"x" * (worklog.MAX_FILE_BYTES + 1))
        result = worklog.read_work_log(self.ctx)
        self.assertEqual((len(result.lines), result.files, result.skipped), (1, 1, 1))
        outside = self.tmp / "outside.log"
        outside.write_text(self.GOOD[1] + "\n", encoding="utf-8")
        link = self.folder / "errors.log.2"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("이 PC 는 링크를 만들 수 없다")
        self.assertEqual([line.name for line in worklog.read_work_log(self.ctx).lines], ["KeyError"], "링크 너머의 줄은 읽지 않는다")

    def test_reading_changes_no_file(self):
        self.write("errors.log", self.GOOD)
        self.write("errors.log.1", self.GOOD[:1])
        before = tree_hashes(self.ctx.workspace.root)
        worklog.read_work_log(self.ctx)
        self.assertEqual(tree_hashes(self.ctx.workspace.root), before)

    def test_non_utf8_bytes_do_not_stop_the_read(self):
        self.folder.mkdir(parents=True)
        (self.folder / "errors.log").write_bytes(self.GOOD[0].encode("utf-8") + b"\n\xff\xfe\x80 \xed\xa0\x80\n" + self.GOOD[1].encode("utf-8") + b"\n")
        result = worklog.read_work_log(self.ctx)
        self.assertEqual((len(result.lines), result.skipped), (2, 1))

    # ---- 재작업 1(독립 검증 S 권고-1): `logs` 폴더 자신이 링크이면 따라가지 않는다 — 윈도 정션은 `Path.is_symlink()` 가 거짓이라 파일 링크만 보던 옛 검사가 놓쳤다 -------------------------------------
    def outside_log(self):
        """데이터 폴더 밖에 좋은 줄이 든 기록 폴더를 만든다(링크의 목적지) → (폴더, 파일 글)."""
        outside = self.tmp / "outside_logs"
        outside.mkdir()
        text = "\n".join(self.GOOD) + "\n"
        (outside / "errors.log").write_text(text, encoding="utf-8")
        self.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
        return outside, text

    @unittest.skipUnless(sys.platform == "win32", "정션(junction)은 윈도에서만 만들 수 있다 — 다른 운영체제는 바로 아래 심볼릭 링크 시험이 같은 일을 본다")
    def test_a_logs_folder_that_is_a_windows_junction_is_not_followed(self):
        outside, text = self.outside_log()
        try:
            import _winapi
            _winapi.CreateJunction(str(outside), str(self.folder))
        except (ImportError, AttributeError, OSError) as error:
            self.skipTest(f"이 환경에서는 정션을 만들 수 없다({type(error).__name__})")
        self.addCleanup(remove_link, self.folder)
        self.assertFalse(self.folder.is_symlink(), "윈도 정션은 `Path.is_symlink()` 가 거짓이다 — 옛 검사가 놓친 까닭")
        self.assertTrue(self.folder.is_dir())
        self.assertTrue(fslink.is_link(self.folder), "공용 링크 판정은 정션도 링크로 본다")
        result = worklog.read_work_log(self.ctx)
        self.assertEqual((result.lines, result.files, result.skipped, result.older), ((), 0, 0, 0), "정션 너머의 기록은 읽지 않는다")
        self.assertEqual((outside / "errors.log").read_text(encoding="utf-8"), text, "목적지는 그대로다")

    def test_a_logs_folder_that_is_a_symbolic_link_is_not_followed(self):
        outside, text = self.outside_log()
        try:
            os.symlink(outside, self.folder, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"이 환경에서는 심볼릭 링크를 만들 수 없다({type(error).__name__})")
        self.addCleanup(remove_link, self.folder)
        result = worklog.read_work_log(self.ctx)
        self.assertEqual((result.lines, result.files, result.skipped, result.older), ((), 0, 0, 0), "폴더 심볼릭 링크 너머의 기록은 읽지 않는다")
        self.assertEqual((outside / "errors.log").read_text(encoding="utf-8"), text)

    def test_the_folder_and_every_file_are_checked_with_the_shared_link_test(self):
        """링크 판정은 `fslink.is_link` 한 곳이다(백업·주제 DB 와 같은 기준). 폴더 하나와 파일 셋을 모두 그것으로 본다 — 소스가 옛 `is_symlink()` 반쪽 검사로 돌아오면 알린다."""
        self.write("errors.log", self.GOOD[:1])
        seen, real = [], fslink.is_link
        with mock.patch.object(fslink, "is_link", side_effect=lambda path: seen.append(Path(path).name) or real(path)):
            result = worklog.read_work_log(self.ctx)
        self.assertEqual(len(result.lines), 1)
        self.assertEqual(set(seen), {"logs", "errors.log", "errors.log.1", "errors.log.2"})
        tree = ast.parse(Path(worklog.__file__).read_text(encoding="utf-8"))
        self.assertEqual([node.lineno for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "is_symlink"], [], "옛 반쪽 검사(`Path.is_symlink`)가 소스에 돌아오지 않는다")

    def test_a_folder_the_link_test_calls_a_link_is_not_read_at_all_and_a_file_it_calls_a_link_is_left_out(self):
        for name, line in (("errors.log.2", self.GOOD[0]), ("errors.log.1", self.GOOD[1]), ("errors.log", self.GOOD[2])):
            self.write(name, [line])
        with mock.patch.object(fslink, "is_link", side_effect=lambda path: Path(path).name == "logs"):
            self.assertEqual(worklog.read_work_log(self.ctx).lines, (), "폴더가 링크면 아무것도 읽지 않는다")
        with mock.patch.object(fslink, "is_link", side_effect=lambda path: Path(path).name == "errors.log.1"):
            result = worklog.read_work_log(self.ctx)
        self.assertEqual(([line.name for line in result.lines], result.files), (["QtCriticalMsg", "KeyError"], 2), "링크인 파일 하나만 빠진다")

    # ---- 재작업 1(독립 검증 S 권고-3): 글자표를 통과하고 엔진도 건드리지 않는 모양 — 엔진이 모르는 키를 낱말에 붙여 손으로 고친 줄 — 은 긴 영숫자 덩어리로 건너뛴다 ---------------------------------------
    @staticmethod
    def glued_keys():
        """낱말 바로 뒤에 붙은 키 모양들 — 엔진은 키 앞이 영숫자면 키로 읽지 않아 가리지 않는다(독립 검증 S 의 탐침 모양). 실행 때 조립한다(소스에 키 글자 0)."""
        keys = {"github": "gh" + "p_" + "A" * 36, "groq": "gs" + "k_" + "I" * 44, "huggingface": "hf" + "_" + "N" * 36, "stripe": "sk" + "_live_" + "K" * 28, "aws": "AK" + "IA" + "D" * 16, "nvidia": "nv" + "api-" + "J1" * 25,
                "google": "AI" + "za" + "B" * 35, "openai-project": "sk-" + "proj-" + "F" * 30, "anthropic": "sk-" + "ant-api03-" + "G" * 30, "slack": "xo" + "xb-" + "1234567890-" + "E" * 20, "slack-real": "xo" + "xb-" + "123456789012-" + "1234567890123-" + "E" * 24,
                "jwt": "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkw" + "." + "abcdefghijklmnop"}
        return {name: "word" + key for name, key in keys.items()}

    def test_a_key_glued_to_a_word_in_a_hand_edited_line_is_skipped_wherever_it_sits(self):
        stamp = "2026-11-24T05:30:12Z"
        lines = list(self.GOOD)
        for glued in self.glued_keys().values():
            lines += [f"{stamp} main {glued[:64]} a.py:1", f"{stamp} main KeyError {glued[:64]}", f"{stamp} main KeyError a.py:1 < {glued[:64]}"]
        self.write("errors.log", lines)
        result = worklog.read_work_log(self.ctx)
        self.assertEqual((len(result.lines), result.skipped), (3, len(lines) - 3), "손으로 고친 줄은 모두 건너뛰고 개수만 안다")
        blob = json.dumps(result.to_dict(), ensure_ascii=False)
        for name, glued in self.glued_keys().items():
            for start in range(0, len(glued) - 7, 4):
                self.assertNotIn(glued[start:start + 8], blob, f"{name}: 키의 조각이 결과에 남았다")

    def test_the_limit_is_a_run_of_letters_digits_underscores_and_hyphens_and_dots_colons_and_spaces_end_a_run(self):
        limit = worklog.MAX_CHUNK
        self.assertEqual(limit, 24)
        stamp = "2026-11-24T05:30:12Z"
        short, long_ = "a" * (limit - 1), "a" * limit
        kept = [f"{stamp} main {name} {place}" for name, place in ((short, "-"), ("KeyError", short + ".py:1"), ("KeyError", "-"), ("KeyError", ".".join(["abcdefgh"] * 5)), ("KeyError", "_".join(["abcdefgh"] * 2) + ".py:1"),
                                                                   ("KeyError", "a" * 11 + "_" + "b" * 11 + ".py:1"), ("KeyError", "a" * 11 + "-" + "b" * 11 + ".py:1"), ("KeyError", "abcdefgh.py:1 < abcdefgh.py:2 < " + "x" * (limit - 1) + ".py:3"),
                                                                   ("Q" + "9" * (limit - 2), "a.py:1"))]
        skipped = [f"{stamp} main {name} {place}" for name, place in ((long_, "-"), ("KeyError", long_ + ".py:1"), ("KeyError", "x.py:1 < " + long_ + ".py:2"), ("Q" + "9" * (limit - 1), "a.py:1"), ("KeyError", "A1" * 20 + ".py:3"),
                                                                      ("KeyError", "_".join(["abcdefgh"] * 3) + ".py:1"), ("KeyError", "-".join(["abcdefgh"] * 3)), ("KeyError", "a" * 11 + "_" + "b" * 12 + ".py:1"),
                                                                      ("KeyError", "a" * 11 + "-" + "b" * 12 + ".py:1"), ("Qt_" + "9" * (limit - 3), "a.py:1"))]
        self.write("errors.log", kept + skipped)
        result = worklog.read_work_log(self.ctx)
        self.assertEqual((len(result.lines), result.skipped), (len(kept), len(skipped)))

    def test_real_looking_names_are_kept(self):
        """이 앱의 실제 줄 — 클래스 이름과 파일 이름은 영문·숫자가 24자 이상 이어지지 않는다(밑줄·점·붙임표가 끊는다). 쓰는 쪽은 메시지·값을 읽지 않고 클래스 이름과 파일 이름만 쓴다."""
        stamp = "2026-11-24T05:30:12Z"
        real = ["UnicodeDecodeError post_history_flow.py:120 < post_package_parts.py:88", "ConnectionRefusedError shell.py:45", "SSLError qt.qpa.fonts", "QtCriticalMsg qt.qpa.xcb < xcberror.cpp:99", "NotImplementedError test_ui_qt_posts_1b.py:5"]
        self.write("errors.log", [f"{stamp} slot {item}" for item in real])
        result = worklog.read_work_log(self.ctx)
        self.assertEqual((len(result.lines), result.skipped), (len(real), 0))

    def test_what_the_real_writer_writes_is_read_back_and_none_of_it_is_skipped(self):
        """쓰는 쪽(`errorlog.ErrorLog`)이 실제 예외로 쓴 줄은 읽는 쪽의 글자표와 긴 덩어리 검사를 모두 지난다 — 읽는 쪽의 거름이 정상 기록을 건너뛰지 않는다(쓰는 쪽은 그런 줄을 만들지 않는다)."""
        writer = errorlog.ErrorLog(lambda: self.ctx.workspace.root)
        raised = [lambda: {}["missing"], lambda: int("x"), lambda: [][1], lambda: 1 / 0, lambda: open(self.tmp / "no_such_folder" / "x.txt"), lambda: bytes([255]).decode("utf-8"), lambda: (_ for _ in ()).throw(NotImplementedError("x")),
                  lambda: (_ for _ in ()).throw(ConnectionRefusedError("x"))]
        names = []
        for make in raised:
            try:
                make()
            except BaseException as error:
                self.assertTrue(writer.record("slot", type(error), error, error.__traceback__))
                names.append(type(error).__name__)
        result = worklog.read_work_log(self.ctx)
        self.assertEqual(([line.name for line in result.lines], result.skipped), (names[::-1], 0))
        self.assertTrue(all(line.places and line.places[0].startswith("test_service_naver_1b.py:") for line in result.lines), "코드 위치는 파일 이름만이고 폴더가 없다")

    def test_only_ascii_digits_are_part_of_the_character_table(self):
        """글자표의 '숫자' 는 ASCII 숫자뿐이다(쓰는 쪽도 그렇다) — 다른 글자 체계의 숫자로 쓴 시각·줄 번호는 손으로 고친 줄이다."""
        arabic = "".join(chr(0x660 + int(char)) if char.isdigit() else char for char in "2026-11-24T05:30:12Z")
        self.write("errors.log", [arabic + " slot KeyError a.py:1", "2026-11-24T05:30:12Z slot KeyError a.py:" + chr(0x661) + chr(0x662), self.GOOD[1]])
        result = worklog.read_work_log(self.ctx)
        self.assertEqual(([line.name for line in result.lines], result.skipped), (["ValueError"], 2))


if __name__ == "__main__":
    unittest.main()
