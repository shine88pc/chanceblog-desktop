"""P3b-1 시험 도우미(시험이 아니다) — '옛 규칙(판 1 씨앗)의 결과가 P3 병합 시점과 한 글자도 안 다르다' 를 못박는 입력 묶음과 지문(digest).

지문의 기준값은 **P3 병합 시점의 코드(기준 커밋 `43489446`)로 한 번 계산해 시험에 적어 둔 것**이다. 입력은 모두 시험용으로 지어낸 예시이고 실제 씨앗·블로그 값이 아니다.
같은 입력 → 같은 지문이어야 하고, 확장·후보 조립 규칙을 바꾸면(의도한 변경이든 아니든) 이 지문이 달라진다 — 달라지면 '옛 규칙이 바뀌었다' 는 뜻이니 의식적으로 확인한다.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.topics import expand, generate, schedule, seeds  # noqa: E402
from chanceblog_desktop.topics.channels import default_profiles  # noqa: E402

TODAY = "2026-11-10"
EXAMPLE_ENTRY = dict(entry_id="ex-cal-due", name="예시 가을 시기", keywords=("예시가을",), prep_start="10-15", publish_from="11-01", publish_to="11-30", peak="11-20", repeat="yearly")


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def legacy_seeds():
    """판 1 모양의 예시 씨앗들(대상 유형 없음) — 다섯 유형·채널 전용·공통·제외 키워드·영문·묶음 이름이 표에 있는 것과 없는 것."""
    def make(seed_id, major, minor, keyword, seed_type="general", scope="common", **more):
        values = dict(seed_id=seed_id, major=major, minor=minor, keyword=keyword, seed_type=seed_type, scope=scope, registered_on="2026-05-01", state="active")
        if seed_type == "sponsorable":
            values["sponsor_tag"] = more.pop("sponsor_tag", "pc_parts")
        values.update(more)
        return seeds.Seed(**values)

    return (
        make("ex-g-001", "예시 대분류", "소형가전", "예시 제습기"),
        make("ex-g-002", "예시 대분류", "숙박", "예시 호텔", scope="naver_a"),
        make("ex-g-003", "예시 대분류", "생산성", "예시 일정표", excluded_keywords=("비교",)),
        make("ex-p-001", "예시 대분류", "PC 부품", "예시 그래픽카드", seed_type="priority", scope="naver_b", priority=True),
        make("ex-p-002", "예시 대분류", "지역", "예시 동네 산책", seed_type="priority", scope="naver_a"),
        make("ex-s-001", "예시 대분류", "계절", "예시가을 여행", seed_type="seasonal", scope="naver_a"),
        make("ex-s-002", "예시 대분류", "계절", "예시겨울 점검", seed_type="seasonal"),
        make("ex-r-001", "예시 대분류", "AI 서비스", "예시 서비스 개편", seed_type="realtime", scope="naver_b"),
        make("ex-c-001", "예시 대분류", "PC 주변기기", "예시 마우스", seed_type="sponsorable", scope="naver_a", sponsor_tag="pc_peripheral"),
        make("ex-c-002", "예시 대분류", "AI 서비스", "예시 노트 서비스", seed_type="sponsorable", scope="naver_b", sponsor_tag="ai_service"),
        make("ex-e-001", "example group", "simple habits", "example weekly reset", scope="blogger_en"),
        make("ex-k-001", "예시 대분류", "정리", "예시 책상 정리", scope="blogger_ko"),
    )


def expand_digest():
    """옛 규칙(대상 유형 없음) 확장 결과 전체의 지문 — 예시 씨앗 12개 × 기본 채널 프로필 5개 × `as_type` 두 가지 + 한도 두 가지."""
    rows = []
    for seed in legacy_seeds():
        for profile in default_profiles():
            for as_type in (None, "sponsorable"):
                for limit in (None, 20):
                    found = expand.expand(seed, profile, limit=limit, as_type=as_type)
                    rows.append([seed.seed_id, profile.key, as_type, limit, [list(item) for item in found.items], [list(item) for item in found.blocked], found.capped])
    return _digest(rows), len(rows)


def generate_digest():
    """옛 규칙 씨앗들로 후보를 조립한 결과의 지문 — 후보 번호·주제·점수·경로·후보 종류와 쓰지 않은 이유까지(네이버 A·B 켜짐, 다른 채널은 꺼짐)."""
    entries = (schedule.CalendarEntry(**EXAMPLE_ENTRY),)
    rows = []
    for profile in default_profiles():
        found = generate.generate(profile, legacy_seeds(), entries, (), TODAY, target=20)
        rows.append([profile.key, [[item.candidate_id, item.topic, item.scores.final, item.source_type, item.candidate_type, item.topic_cluster, item.topic_angle, item.language] for item in found.candidates],
                     [list(item) for item in found.routes], [list(item) for item in found.dropped], list(found.notes)])
    return _digest(rows), sum(len(row[1]) for row in rows)


if __name__ == "__main__":
    print("expand", expand_digest())
    print("generate", generate_digest())
