"""주제 엔진(`topics/`) 시험 도우미 — 시험마다 쓰는 후보·점수 만들기(시험 모듈이 아니다). 네트워크·파일·시계 없이 돈다."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.topics import model, score  # noqa: E402
from chanceblog_desktop.topics.channels import FACTOR_NAMES, default_profiles  # noqa: E402

PROFILES = {profile.key: profile for profile in default_profiles()}
STAMP = "2026-11-04T09:56:00Z"
TOPICS = ROOT / "src" / "chanceblog_desktop" / "topics"


def card(final=None, **parts):
    """여섯 항목(이름으로 일부만 줘도 된다)과 최종 점수로 점수 묶음을 만든다."""
    return score.ScoreCard(score.Factors(**parts), final)


def flat_card(value):
    """여섯 항목이 모두 `value` 이고 최종도 `value` 인 점수 묶음(가중 평균이 항상 `value` 라서 어느 채널 가중치에서도 어긋나지 않는다)."""
    return card(value, **{name: value for name in FACTOR_NAMES})


def make(**overrides):
    """검증을 모두 통과하는 엔진 후보(네이버 B). 바꿀 칸만 이름으로 준다."""
    values = {
        "candidate_id": "cand0001", "source_type": "seed", "candidate_type": "evergreen", "channel": "naver_b", "language": "ko", "topic": "개인 PC 에서 로컬 AI 를 돌릴 때 확인할 사양",
        "primary_keyword": "로컬 AI 사양", "search_intent": "selection_guide", "content_type": "buying_guide", "topic_cluster": "local-ai", "topic_angle": "memory-requirements",
        "target_reader": "개인 PC 에서 로컬 AI 를 써 보려는 일반 사용자", "created_at": STAMP,
    }
    values.update(overrides)
    return model.TopicCandidate(**values)


def rated(final, *, cluster="local-ai", candidate_id=None, channel="naver_b", created_at=STAMP, **more):
    """최종 점수가 `final` 인 후보(여섯 항목이 모두 `final`)."""
    return make(candidate_id=candidate_id or f"c{final}-{cluster}", topic_cluster=cluster, channel=channel, language="en" if channel == "blogger_en" else "ko", created_at=created_at,
                scores=flat_card(final), **more)


def full(**overrides):
    """모든 칸에 서로 다른 값이 들어 있는 후보 — '빠짐 없음'·왕복 시험용."""
    values = {
        "source_topic_id": "src-local-ai", "seed_id": "seed-gpu", "secondary_keywords": ("GPU 메모리", "로컬 LLM"),
        "scores": card(85, channel_fit=92, feasibility=85, differentiation=78, timing=80, evidence=82, monetization=88),
        "trend_status": "rising", "trend_ratio": 73, "trend_period": "2025-11-04~2026-11-04", "trend_compared_group": ("로컬 AI", "클라우드 AI"), "trend_queried_on": "2026-11-04",
        "search_demand_count": 4200, "search_demand_source": "검색광고 키워드 도구", "data_status": "sufficient", "duplicate_status": "different_angle_needed",
        "similar_post_ids": ("2026-10-01-KR-120000",), "monetization_tags": ("pc_parts", "affiliate"), "selection_reasons": ("공식 사양으로 쓸 수 있다", "부품 협업 가능"),
        "processing_errors": ("관심도 조회 한 번 실패 후 재시도", ), "work_status": "REVIEW", "review_expires_at": "2027-02-02T09:56:00Z",
    }
    values.update(overrides)
    return make(**values)
