"""제안 시험 도우미(시험이 아니다) — 고정 날짜·프로필·후보 만들기·독립 재검사.

시험 파일들이 `import suggest_support as sp` 로 쓴다(`python -m unittest discover -s tests` 는 tests/ 를 import 경로에 올린다).
"""
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content import suggest as sg  # noqa: E402
from chanceblog_desktop.content import suggest_text as tx  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile, find_markup  # noqa: E402

TODAY = date(2026, 11, 3)                                  # 한국 달력의 화요일, 11월
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)     # 자식 프로세스의 콘솔 창을 띄우지 않는다(Windows 에서만 값이 있다 — 다른 곳에서는 0)
RICH = dict(topic="생활 절약, 보일러 난방, 가계부", categories=(("경제·일", "재테크"), ("생활", "살림")), default_tags=("절약", "보험"))


def profile(key="naver_a", **fields):
    return NaverProfile(key, "블로그 에이" if key == "naver_a" else "블로그 비", f"https://blog.naver.com/example{key[-1] * 3}", **fields)


def rich(key="naver_a", **fields):
    return profile(key, **{**RICH, **fields})


def kst_stamp(days_ago, today=TODAY, hour=12):
    """오늘(한국 달력)에서 `days_ago` 일 전 한국 시간 `hour` 시의 저장 시각(UTC)."""
    day = today - timedelta(days=days_ago)
    local = f"{day.isoformat()}T{hour:02d}:00:00"
    from datetime import datetime
    return (datetime.strptime(local, "%Y-%m-%dT%H:%M:%S") - timedelta(hours=9)).strftime(cd.STAMP_FORMAT)


def make(keyword, blogs=("naver_a",), *, topic=None, status=cd.NEW, picked=None, number=1, **fields):
    """보관함에 있는 것 같은 후보 하나. `picked` 는 {블로그: 고른 시각} — 있으면 '선택됨' 으로 옮겨 선택 기록을 남긴다."""
    base = cd.Candidate.new(topic or f"{keyword} 글감", keyword, tuple(blogs), candidate_id=f"cand{number:04d}", now="2026-10-01T00:00:00Z", **fields)
    if picked:
        for blog, stamp in picked.items():
            base = base.moved(cd.SELECTED, blog=blog, now=stamp)
        return base
    if status != cd.NEW:
        base = base.moved(status, now="2026-10-02T00:00:00Z")
    return base


def run(prof=None, **kwargs):
    kwargs.setdefault("today", TODAY)
    return sg.suggest(rich() if prof is None else prof, **kwargs)


def shown(report):
    return report.suggestions


def keywords(report):
    return [item.keyword for item in report.suggestions]


def texts_of(item):
    """제안에 보이는 글 모두(제목·키워드·보조 키워드·추천 이유)."""
    return [item.topic, item.keyword, *item.sub_keywords, item.reason]


def independent_problems(report, prof, blog="naver_a"):
    """보여 준 제안 하나하나를 **밖에서 다시** 검사한다 — 제외어·금지 표현·위험한 표기·후보로 저장할 수 있는 모양·중복 키워드. 문제 문장 목록(비어 있어야 한다)."""
    problems, seen = [], set()
    excluded = [tx.squash(item) for item in getattr(prof, "excluded_topics", ()) if tx.squash(item)]
    forbidden = [tx.squash(item) for item in getattr(prof, "forbidden_phrases", ()) if tx.squash(item)]
    for item in report.suggestions:
        for text in texts_of(item):
            flat = tx.squash(text)
            problems += [f"제외어 {word}: {text}" for word in excluded if word in flat]
            problems += [f"금지 표현 {word}: {text}" for word in forbidden if word in flat]
            if cd.forbidden_claim(text) or find_markup(text):
                problems.append(f"약속·위험 표기: {text}")
        key = cd.keyword_key(item.keyword)
        if key in seen:
            problems.append(f"같은 키워드가 둘: {item.keyword}")
        seen.add(key)
        try:
            cd.Candidate.new(item.topic, item.keyword, (blog,), candidate_id="x", now="2026-11-03T00:00:00Z", sub_keywords=item.sub_keywords, post_type=item.post_type, reason=item.stored_reason)
        except Exception as error:  # noqa: BLE001
            problems.append(f"후보로 저장할 수 없다: {item.keyword}: {error}")
    return problems
