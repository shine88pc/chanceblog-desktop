"""서비스 층 — 미리보기 시험: Pages 글(경로와 내용)·네이버 A·B 패키지·두 블로그 비교를 **만들어 보여 주기만** 한다.

지키는 것:
  1) 아무 파일도 쓰지 않는다 — 연결한 저장소도 데이터 폴더도 앞뒤가 같고, 글의 상태도 그대로다. commit·push·되돌리기는 부르지 않고 네트워크도 쓰지 않는다.
  2) Pages: 지금 시각으로 만든 파일 경로·내용·검사 결과를 보이고, 공개 주소는 연결한 저장소가 있을 때만 읽기로 계산한다(없거나 계산할 수 없으면 이유를 말한다).
  3) 네이버: 프로필이 있는 블로그마다 패키지를 만들고 둘 다 있으면 비교한다(같은 원고는 많이 비슷하다고 알린다). 프로필이 하나도 없으면 NAVER_PROFILE_MISSING.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import previews, projects  # noqa: E402
from chanceblog_desktop.service.naver_flow import NaverOptions  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)
        self.project_id = projects.new_project(self.ctx, "에너지 절약 습관", ss.ko_text()).project_id

    def snapshot(self):
        return ss.tree_snapshot(self.tmp)


class PagesPreviewTest(Base):
    def test_the_preview_shows_path_text_gates_and_address_and_writes_nothing(self):
        (self.tmp / "chanceblog").mkdir()
        before = self.snapshot()
        self.backend.calls.clear()
        preview = previews.preview_pages(self.ctx, self.project_id, ss.KO_PARAMS)
        self.assertEqual((preview.path, preview.category, preview.lang, preview.expected_url, preview.url_note), (ss.KO_PATH, "경제·일", "ko", ss.KO_URL, ""))
        self.assertTrue(preview.text.startswith("---\nlayout: post\n"))
        self.assertEqual(preview.size_bytes, len(preview.text.encode("utf-8")))
        self.assertTrue(preview.gates.ok)
        self.assertEqual(self.snapshot(), before, "저장소 폴더도 데이터 폴더도 그대로다")
        self.assertEqual(self.backend.names(), ["expected_url"], "읽기뿐 — commit·push·되돌리기·배포 확인을 부르지 않는다")
        self.assertEqual(ss.status_of(self.ctx, self.project_id), st.NOT_STARTED)

    def test_a_preview_never_saves_anything_even_when_the_store_is_watched(self):
        from chanceblog_desktop.content.store import Store
        from unittest import mock
        (self.tmp / "chanceblog").mkdir()
        with mock.patch.object(Store, "save", side_effect=AssertionError("미리 보기가 글을 저장했다")), mock.patch.object(Store, "delete", side_effect=AssertionError("미리 보기가 글을 지웠다")):
            previews.preview_pages(self.ctx, self.project_id, ss.KO_PARAMS)
            ss.naver_profiles(self.ctx)
            previews.preview_naver(self.ctx, self.project_id)
        self.assertEqual(sorted(path.name for path in (self.tmp / "chanceblog").iterdir()), [], "연결한 저장소 폴더에도 아무것도 쓰지 않았다")

    def test_a_preview_of_a_changed_post_follows_the_manuscript_and_never_saves_a_rendering(self):
        projects.edit_project(self.ctx, self.project_id, title="바뀐 제목")
        preview = previews.preview_pages(self.ctx, self.project_id[:8], ss.KO_PARAMS)
        self.assertIn('title: "바뀐 제목"', preview.text)
        self.assertFalse(projects.show_project(self.ctx, self.project_id).variant("github_pages").has_rendering)

    def test_without_a_connected_folder_the_address_is_left_out_with_the_reason(self):
        ctx = ss.make_ctx(self.tmp / "other", backend=self.backend, repo=None)
        project_id = projects.new_project(ctx, "글", ss.ko_text()).project_id
        preview = previews.preview_pages(ctx, project_id, ss.KO_PARAMS)
        self.assertEqual(preview.expected_url, "")
        self.assertIn("연결한 chanceblog 폴더가 없어", preview.url_note)

    def test_an_address_that_cannot_be_computed_is_explained_not_raised(self):
        self.backend.url_error = AppError("CONTENT_INVALID", {"항목": "공개 설정"}, detail="이 글은 사이트에 공개되지 않는다")
        preview = previews.preview_pages(self.ctx, self.project_id, ss.KO_PARAMS)
        self.assertEqual(preview.expected_url, "")
        self.assertIn("공개 주소를 계산하지 못했습니다", preview.url_note)

    def test_bad_settings_are_refused_with_the_content_error(self):
        for params in (None, previews.PagesParams("", "ko", "https://x.example/a.jpg"), previews.PagesParams("경제", "ko", "javascript:alert(1)")):
            with self.subTest(params=params):
                self.assertEqual(ss.code_of(previews.preview_pages, self.ctx, self.project_id, params).code, "CONTENT_INVALID")

    def test_gate_problems_are_shown_in_the_preview_not_raised(self):
        short = projects.new_project(self.ctx, "짧은 글", "짧은 글입니다. " * 10).project_id
        preview = previews.preview_pages(self.ctx, short, ss.KO_PARAMS)
        self.assertFalse(preview.gates.ok)

    def test_the_source_and_tags_and_description_reach_the_text(self):
        params = previews.PagesParams("경제·일", "ko", "https://images.example.invalid/a.jpg", ("가", "나"), "직접 쓴 설명", {"name": "한국은행", "url": "https://www.bok.or.kr/x", "title": "보도자료"})
        text = previews.preview_pages(self.ctx, self.project_id, params).text
        for needle in ('tags: ["가", "나"]', 'description: "직접 쓴 설명"', 'source_name: "한국은행"', "## 출처", "[한국은행: 보도자료](https://www.bok.or.kr/x)"):
            self.assertIn(needle, text)

    def test_the_preview_converts_to_plain_data(self):
        preview = previews.preview_pages(self.ctx, self.project_id, ss.KO_PARAMS)
        self.assertNotIn("text", preview.to_dict())
        self.assertIn("text", preview.to_dict(with_text=True))
        json.dumps(preview.to_dict(with_text=True))

    def test_an_unknown_post_is_not_found(self):
        self.assertEqual(ss.code_of(previews.preview_pages, self.ctx, "ffffffff", ss.KO_PARAMS).code, "CONTENT_NOT_FOUND")


class NaverPreviewTest(Base):
    def test_without_any_profile_it_says_which_is_missing(self):
        error = ss.code_of(previews.preview_naver, self.ctx, self.project_id)
        self.assertEqual((error.code, error.slots["블로그"]), ("NAVER_PROFILE_MISSING", "naver_a, naver_b"))

    def test_with_one_profile_only_that_blog_is_built_and_the_other_is_named_as_missing(self):
        ss.naver_profiles(self.ctx, both=False)
        preview = previews.preview_naver(self.ctx, self.project_id)
        self.assertEqual(([item.key for item in preview.items], preview.missing, preview.similarity), (["naver_a"], ("naver_b",), None))

    def test_with_both_profiles_the_same_manuscript_is_reported_as_very_similar(self):
        ss.naver_profiles(self.ctx)
        before = self.snapshot()
        preview = previews.preview_naver(self.ctx, self.project_id)
        self.assertEqual(([item.key for item in preview.items], preview.missing), (["naver_a", "naver_b"], ()))
        self.assertEqual(preview.similarity.level, "high")
        self.assertTrue(preview.similarity.needs_approval)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(ss.status_of(self.ctx, self.project_id, "naver_a"), st.NOT_STARTED, "미리 보기는 상태를 바꾸지 않는다")
        self.assertEqual(self.backend.calls, [])

    def test_per_blog_changes_make_the_two_packages_different_enough(self):
        ss.naver_profiles(self.ctx)
        preview = previews.preview_naver(self.ctx, self.project_id, {"naver_b": NaverOptions(title="전혀 다른 제목의 이야기", body=ss.DIFFERENT, tags=("산책",))})
        self.assertNotEqual(preview.similarity.level, "high")
        self.assertEqual(preview.items[1].package.title, "전혀 다른 제목의 이야기")

    def test_the_preview_converts_to_plain_data_with_or_without_the_text(self):
        ss.naver_profiles(self.ctx)
        preview = previews.preview_naver(self.ctx, self.project_id)
        plain = preview.to_dict()
        self.assertNotIn("body_text", plain["items"][0])
        self.assertEqual(plain["similarity"]["level"], "high")
        self.assertIn("body_text", preview.to_dict(with_text=True)["items"][0])
        json.dumps(preview.to_dict(with_text=True))
        self.assertIsNone(previews.similarity_dict(None))


if __name__ == "__main__":
    unittest.main()
