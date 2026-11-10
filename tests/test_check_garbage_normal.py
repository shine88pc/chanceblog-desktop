"""'글 모양 점검' 규칙의 **정상 글 대조** — 정상으로 읽혀야 하는 글 402개(짧은 정상 글 196 + 실제 모양 글 2 + 앱이 만든 초안 204)에서 **걸림 0**. 걸리면 규칙의 오탐이거나 생성기의 틈이니 원인을 고친다(시험을 풀지 않는다).
운영자 병합 조건(2026-11-10): 정상 글 402개 오탐 0 — 새 코드 영역 제외 규칙을 넣은 뒤에도. 네트워크·파일 없이 돈다(실제 모양 글은 저장소의 시험 자료다).
"""
import sys
import unittest
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import garbage_samples as S  # noqa: E402
from draft_samples import CONTROL, DAILY, NORMAL_ADDRESSES, NORMAL_FILE_NAMES, NORMAL_MORE  # noqa: E402

from chanceblog_desktop.check import garbage as g  # noqa: E402
from chanceblog_desktop.content.profiles import POST_TYPES  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402

STATIC = {"CONTROL": CONTROL, "DAILY": DAILY, "NORMAL_MORE": NORMAL_MORE, "NORMAL_ADDRESSES": NORMAL_ADDRESSES, "NORMAL_FILE_NAMES": NORMAL_FILE_NAMES}
EXPECTED_STATIC_COUNT = 196                      # 40 + 50 + 88 + 10 + 8
EXPECTED_GENERATED_COUNT = 204                   # 후보 18 × 블로그 2 × 글 유형 6 중 거절 12 를 뺀 것


def outcome(title, body):
    return [(item.kind, item.sub, S.caught(body, item, title=title)) for item in g.scan(title, body).findings]


@lru_cache(maxsize=1)
def generated_drafts():
    """앱의 규칙 기반 생성기가 만든 초안 — (제목 후보 셋, 선택 제목, 본문). 거절돼 못 만든 것은 건너뛴다."""
    import test_ui_drafts_core as core
    rows = list(core.ROWS) + [core.GENERIC, core.SOFTWARE, core.APPLIANCE, core.HEALTH]
    made, skipped = [], 0
    for row in rows:
        for blog in ("naver_a", "naver_b"):
            for post_type in (None, *POST_TYPES):
                try:
                    body = core.body_of(row.topic, row.primary_keyword, tuple(row.secondary_keywords), blog=blog, post_type=post_type)
                except AppError:
                    skipped += 1
                    continue
                made.append((tuple(body.titles), body.selected_title, body.body_text))
    return tuple(made), skipped


class StaticCorporaTest(unittest.TestCase):
    def test_the_static_corpora_have_the_counted_sizes(self):
        self.assertEqual({name: len(items) for name, items in STATIC.items()}, {"CONTROL": 40, "DAILY": 50, "NORMAL_MORE": 88, "NORMAL_ADDRESSES": 10, "NORMAL_FILE_NAMES": 8})
        self.assertEqual(sum(len(items) for items in STATIC.values()), EXPECTED_STATIC_COUNT)

    def test_no_short_normal_text_is_caught_as_a_body(self):
        for name, items in STATIC.items():
            for index, text in enumerate(items):
                with self.subTest(name, index=index):
                    self.assertEqual(outcome("", text), [], text[:60])

    def test_no_short_normal_text_is_caught_as_a_title(self):
        for name, items in STATIC.items():
            for index, text in enumerate(items):
                with self.subTest(name, index=index):
                    self.assertEqual([(item.kind, item.sub) for item in g.scan(text, "").findings], [], text[:60])

    def test_the_hand_made_normal_texts_are_not_caught(self):
        for index, text in enumerate(S.NORMAL_TEXTS):
            with self.subTest(index):
                self.assertEqual(outcome("", text), [], text[:60])

    def test_all_the_static_texts_joined_into_one_long_body_are_not_caught_except_by_the_repeats_between_them(self):
        """모두 한 글로 이어 붙이면 서로 겹치는 문장이 생길 수 있다 — 글자 모양 규칙(깨진 문자·보이지 않는 글자·제어 문자·HTML·자리표시)은 그래도 걸리지 않는다."""
        joined = "\n\n".join(text for items in STATIC.values() for text in items)
        kinds = {item.kind for item in g.scan("", joined).findings}
        self.assertEqual(kinds - {"dup_sentence", "dup_word"}, set())


class PunctuatedShapesTest(unittest.TestCase):
    """D-323 — 문장부호·괄호·쉼표가 낱말 사이에 낀 같은 낱말(실제 글에서 되풀이로 오탐되던 모양)의 **지어낸** 문장 모음 — 본문·제목 어디서도 걸림 0 이고, 사이의 부호를 뺀 같은 글은 같은 낱말 반복으로 걸린다(이 모음이 새 규칙을 실제로 시험한다). 병합 조건 1 의 402개에 더하는 대조군이다."""

    MARKS = str.maketrans("", "", ".!?:;,()[]{}" + chr(0x2026))

    def test_the_collection_has_the_counted_size(self):
        self.assertEqual(len(S.PUNCTUATED_SHAPES), 22)
        self.assertEqual(len(set(S.PUNCTUATED_SHAPES)), 22)

    def test_no_shape_is_caught_as_a_body_and_none_as_a_title(self):
        for index, text in enumerate(S.PUNCTUATED_SHAPES):
            with self.subTest(index):
                self.assertEqual(outcome("", text), [], text[:60])
                self.assertEqual([(item.kind, item.sub) for item in g.scan(text, "").findings], [], text[:60])

    def test_the_same_words_with_the_marks_taken_out_are_caught_as_a_repeat(self):
        for index, text in enumerate(S.PUNCTUATED_SHAPES):
            plain = text.translate(self.MARKS)
            with self.subTest(index):
                self.assertIn("dup_word", {item.kind for item in g.scan("", plain).findings}, plain[:60])


class RealShapePostsTest(unittest.TestCase):
    def test_the_two_real_shaped_posts_are_not_caught_as_files_or_as_bodies(self):
        for name in ("chance_post_ko.md", "chance_post_en.md"):
            raw = (ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8")
            body = raw.split("\n---\n", 1)[1] if raw.startswith("---") else raw
            with self.subTest(name):
                self.assertEqual(outcome("", raw), [], "머리말이 붙은 파일 그대로")
                self.assertEqual(outcome("", body), [], "본문만")
                self.assertGreater(len(body), 1000)


class GeneratedDraftsTest(unittest.TestCase):
    def test_the_app_made_drafts_are_the_counted_number(self):
        made, skipped = generated_drafts()
        self.assertEqual((len(made), skipped), (EXPECTED_GENERATED_COUNT, 12))

    def test_no_app_made_draft_is_caught_and_neither_is_any_of_its_titles(self):
        made, _skipped = generated_drafts()
        for index, (titles, selected, body) in enumerate(made):
            with self.subTest(index):
                self.assertEqual(outcome(selected, body), [], f"{selected[:40]}")
                for title in titles:
                    self.assertEqual(g.scan(title, "").findings, ())

    def test_the_total_of_the_checked_normal_texts_is_four_hundred_and_two(self):
        made, _skipped = generated_drafts()
        self.assertEqual(EXPECTED_STATIC_COUNT + 2 + len(made), 402)


if __name__ == "__main__":
    unittest.main()
