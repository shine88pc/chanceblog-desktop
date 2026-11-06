"""'옛 규칙' 회귀 시험(P3b-1) — 대상 유형이 없는 판 1 씨앗의 확장·후보 조립 결과가 **P3 병합 시점(기준 커밋 `43489446`)과 한 글자도 안 다르다**는 것을 지문으로 못박는다.

지문의 기준값은 P3b-1 을 시작하기 전의 코드로 한 번 계산해 적어 둔 것이다(`topics_p3b1_support.py` 의 입력 묶음 — 시험용으로 지어낸 예시 씨앗 12개·예시 캘린더 1개). 이 시험이 빨개지면 '옛 규칙의 결과가 바뀌었다'
는 뜻이다 — 의도한 변경이면 이유를 적고 기준값을 함께 고치고, 아니면 고친 코드를 되돌린다. 기본 채널 프로필의 판 1 모양(`profiles_to_dict` 의 판 1 칸들)도 같은 방식으로 못박는다.
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_p3b1_support as sup  # noqa: E402

from chanceblog_desktop.topics import channels as ch  # noqa: E402

EXPAND_DIGEST = ("4cc1590102ecdbe4", 240)         # 예시 씨앗 12 × 기본 프로필 5 × as_type 2 × 한도 2
GENERATE_DIGEST = ("6051c9ca30c7adfb", 21)        # 켜진 채널(네이버 A·B)이 만든 후보 21개의 번호·주제·점수·경로·후보 종류와 쓰지 않은 이유
PROFILE_V1_DIGEST = "22772b23931e943b"            # 기본 채널 프로필 다섯 개의 판 1 저장 모양(칸 16개 × 5)
PROFILE_V1_KEYS = ("key", "display_name", "language", "generation_enabled", "history_enabled", "evergreen_pct", "realtime_pct", "weights", "top_n", "cluster_cap", "subheading_min", "trend_use",
                   "dup_cutoffs", "topic_clusters", "expansion_directions", "monetization_focus")


class LegacyRulesUnchangedTest(unittest.TestCase):
    def test_legacy_expansion_results_are_identical_to_the_p3_merge_point(self):
        self.assertEqual(sup.expand_digest(), EXPAND_DIGEST)

    def test_legacy_candidate_assembly_is_identical_to_the_p3_merge_point(self):
        self.assertEqual(sup.generate_digest(), GENERATE_DIGEST)

    def test_the_default_profiles_old_fields_are_unchanged_by_the_new_profile_fields(self):
        data = ch.profiles_to_dict(ch.default_profiles())
        old = {"schema": 1, "profiles": [{key: value for key, value in item.items() if key in PROFILE_V1_KEYS} for item in data["profiles"]]}
        self.assertEqual(hashlib.sha256(json.dumps(old, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16], PROFILE_V1_DIGEST)


if __name__ == "__main__":
    unittest.main()
