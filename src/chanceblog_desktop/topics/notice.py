"""사용자 메시지 `Notice` — 내부 코드와 화면 문구를 나눈다(P2b 보완, D-53 — 순수 계산: 파일·화면·네트워크·시계·난수·AI 없음). UI 는 P4 이므로 여기서는 ViewModel 수준의 **순수 표시 모델**까지만 만든다.

`Notice(code·level·title·message·action·details)` 하나가 '알림 카드' 하나다. `code` 는 내부 코드(카탈로그의 열쇠 — 화면에 내지 않는다)이고 **화면 글에는 `title`·`message`·`action`·`details` 만** 쓴다.
`level` 은 INFO(참고 정보·진행 가능)·WARNING(확인 필요·조건에 따라 진행 가능)·ERROR(작업 실패 또는 자동 진행 중지) 셋이다. 알림 목록은 수준이 높은 것 먼저, 같으면 카탈로그 순서다.
`topics/` 가 사용자에게 보일 수 있는 알림(안전 표시·진단·보류·브랜드)은 이 카탈로그의 **고정 문장**에서만 나온다 — `title`·`message`·`action` 에는 자리표시자나 입력 글이 들어가지 않는다.
바뀌는 값(걸린 낱말·이득 종류·건수·날짜·진단의 첫 사례 문장)은 `details`(글머리표 줄)로만 나가고, 입력 글은 곡선 따옴표 `‘ ’` 안에만 있다. 모든 글은 `leaks` 검사(파이썬 목록 꼴·내부 식별자·`Enum` 표기가 없는지)를 통과해야 한다.
변환기는 받은 객체의 속성만 읽는다(덕 타이핑) — `safety`·`generate`·`brand`·`concepts` 를 가져오지 않는다. 모르는 코드·수준을 받으면 `ValueError` 다.
**카탈로그의 문장은 모두 초기값 — 전략 원문 확인 전이다**(요청서의 세 표시 예문 — 주제 구체화 필요·건강 정보 확인 필요·경제적 이해관계 확인 필요 — 는 글자 그대로다).
"""
from __future__ import annotations

import dataclasses
import re
from types import MappingProxyType

from . import wording

LEVEL_INFO, LEVEL_WARNING, LEVEL_ERROR = "INFO", "WARNING", "ERROR"
LEVELS = (LEVEL_INFO, LEVEL_WARNING, LEVEL_ERROR)                                  # 낮은 것 → 높은 것
MAX_LINE = 300                                                                    # 제목·설명·행동·세부 한 줄의 상한(후보의 선정 이유 한 줄 한도와 같다)

# 알림 카탈로그(초기값) — 코드(내부) → (수준, 제목, 설명, 권장 행동). 순서가 곧 같은 수준 안의 정렬 순서다.
_CATALOG_ROWS = (
    # 안전 표시 10 — `ECONOMIC_CONFLICT` 는 전략 맞춤 1차(D-102)에서 더했다: 저장된 상태가 ‘없음’인데 글에서 협찬이 추정될 때 `ECONOMIC_CHECK` 대신 이것 하나만 낸다
    # 건강 세 단계(D-105): A 표시만 = HEALTH_TOPIC(건강 대상 낱말이 있는 주제) · B 근거 확인 필요 = HEALTH_EFFECT(근거가 필요한 건강 표현) · C 의료·효과 단정 위험 = HEALTH_STOP(효과·치료 단정). 문장은 단계 뜻에 맞춘다(수정 1차).
    # B 문장은 D-134 에서 한 문장만 고쳤다: 질환 단독(운영자 2026-11-06 ~19:55 ③)과 복용·섭취·중단 허용 질문(D-131)도 B 가 되어 '효과를 말하는 표현' 만으로는 카드가 어긋난다.
    # HEALTH_CLAIM 은 이 단계표에서 쓰이는 곳이 없다 — 코드 이름 목록(카탈로그)을 위해서만 남겼다
    ("HEALTH_TOPIC", LEVEL_WARNING, "건강 정보 확인 필요", "증상·질환·건강 제품이나 치료 같은 의료 용어가 들어 있는 주제입니다.", "공식 근거를 확인하고, 효과를 단정하지 않는 표현으로 써 주세요."),
    ("HEALTH_EFFECT", LEVEL_WARNING, "건강 정보 확인 필요", "질환이나 복용을 다루거나 건강에 도움이 된다고 읽힐 수 있는 표현이 있어 근거 확인이 필요합니다.", "공식 근거를 확인하고, 효과를 단정하지 않는 표현으로 써 주세요."),
    ("HEALTH_CLAIM", LEVEL_WARNING, "건강 정보 확인 필요", "효과를 단정하는 표현이 포함되어 있습니다.", "공식 근거를 확인하거나 일반 생활정보 표현으로 수정해 주세요."),            # 쓰이는 곳 없음(D-105)
    ("HEALTH_STOP", LEVEL_ERROR, "의료·효과 단정 위험", "건강 효과나 치료를 단정하는 표현이 있어 자동 초안을 만들지 않습니다.", "표현을 바꾸거나 공식 근거를 확인한 뒤 직접 검토해 주세요."),
    ("EXPERIENCE_CLAIM", LEVEL_WARNING, "직접 겪은 경험 확인 필요", "직접 사용하거나 방문하거나 구매한 경험을 이미 한 것처럼 쓴 표현이 있습니다.", "직접 겪은 일이 아니면 주제에서 빼거나 바꿔 주세요."),
    ("ECONOMIC_CHECK", LEVEL_WARNING, "경제적 이해관계 확인 필요", "제품·서비스 제공 또는 제휴 보상이 있는지 확인해 주세요.", "대가가 있다면 본문 첫 부분에 표시 문구가 필요합니다."),
    ("ECONOMIC_CONFLICT", LEVEL_WARNING, "경제적 이해관계 확인 필요", "저장된 상태는 ‘없음’인데 글에는 협찬이나 광고로 보이는 표현이 있어 서로 맞지 않습니다.", "협찬·광고 여부를 다시 확인해 저장된 상태를 고치거나 표현을 바꿔 주세요."),
    ("ECONOMIC_CONFIRMED", LEVEL_WARNING, "경제적 이해관계 표시 필요", "등록된 협찬 정보가 있어 이 글에는 경제적 이해관계가 있습니다.", "본문 첫 부분에 표시 문구가 필요합니다. 표시 문구는 다음 단계에서 정합니다."),
    ("COLLAB_POSSIBLE", LEVEL_INFO, "협업 가능성 참고", "협업할 수 있는 주제로 분류된 후보입니다. 아직 협찬이 확정된 것은 아닙니다.", "실제로 제품·서비스·대가를 받기로 했다면 협찬 정보를 입력해 주세요."),
    ("RESULT_PROMISE", LEVEL_ERROR, "결과 약속 표현", "결과를 약속하는 표현이 있어 이 글로는 후보를 만들 수 없습니다.", "약속하는 말을 빼고, 확인할 수 있는 내용으로 바꿔 주세요."),
    # 브랜드 단독 3
    ("BRAND_ONLY", LEVEL_WARNING, "주제 구체화 필요", "브랜드명만으로는 작성 방향을 판단하기 어렵습니다.", "제품, 기능 또는 비교 목적을 선택해 주세요."),
    ("BRAND_UNFEASIBLE", LEVEL_WARNING, "작성 기반 부족", "구체화한 하위 주제로는 소제목을 충분히 채우기 어렵습니다.", "글 종류나 비교 대상을 더 구체적으로 정해 주세요."),
    ("BRAND_SPECIFIED", LEVEL_INFO, "주제 구체화 완료", "브랜드명만 있던 씨앗을 제품·서비스 유형에 맞는 하위 주제로 넓혔습니다.", "마음에 드는 하위 주제를 골라 주세요."),
    # 진단 15 — `generate.DROP_REASONS` 와 1:1(브랜드 둘은 위 두 코드)
    ("DROP_COMBINATION", LEVEL_INFO, "조합 제외", "씨앗의 종류와 맞지 않는 방향이라 후보로 만들지 않았습니다.", "필요하면 씨앗 종류를 바꿔 다시 만들어 주세요."),
    ("DROP_EXCLUDED_KEYWORD", LEVEL_INFO, "제외 키워드", "씨앗에 정해 둔 제외 키워드가 들어 있어 후보로 만들지 않았습니다.", "제외 키워드를 바꾸면 다시 만들 수 있습니다."),
    ("DROP_TOO_LONG", LEVEL_INFO, "키워드가 너무 김", "핵심 키워드가 길이 한도를 넘어 후보로 만들지 않았습니다.", "씨앗 낱말을 더 짧게 적어 주세요."),
    ("DROP_LANGUAGE", LEVEL_INFO, "언어가 맞지 않음", "영어 채널에는 한글 씨앗으로 후보를 만들지 않습니다.", "영어 씨앗을 따로 등록해 주세요."),
    ("DROP_NO_SEED", LEVEL_WARNING, "쓸 수 있는 씨앗 없음", "이 채널에서 쓸 수 있는 씨앗(사용 중이고 공통이거나 이 채널 전용)이 없습니다.", "씨앗을 등록하거나 사용 중으로 바꿔 주세요."),
    ("DROP_NOT_DUE", LEVEL_INFO, "발행 시기 아님", "계절 씨앗이 아직 발행 기간이 아니거나 이어지는 캘린더 항목이 없습니다.", "캘린더의 발행 기간을 확인해 주세요."),
    ("DROP_NO_KEYWORD", LEVEL_WARNING, "후속 후보를 만들 수 없음", "기존 글에 키워드가 없어 후속 후보를 만들 수 없습니다.", "기존 글에 키워드를 적어 주세요."),
    ("DROP_INVALID", LEVEL_WARNING, "후보 규칙에 맞지 않음", "만든 후보가 후보 규칙(길이·글자·관심도 값 등)에 맞지 않아 쓰지 않았습니다.", "안내된 칸의 값을 확인해 주세요."),
    ("DROP_RESULT_PROMISE", LEVEL_ERROR, "결과 약속 표현", "결과를 약속하는 표현이 있어 이 후보는 만들지 않았습니다.", "약속하는 말을 빼고 다시 만들어 주세요."),
    ("DROP_ALREADY_EXISTS", LEVEL_INFO, "이미 있는 후보", "같은 번호의 후보가 이미 있어 다시 만들지 않았습니다.", "새 후보가 필요하면 씨앗이나 방향을 바꿔 주세요."),
    ("DROP_OVER_TARGET", LEVEL_INFO, "목표 개수 초과", "목표 개수를 넘어 점수가 낮은 후보는 쓰지 않았습니다.", "더 보려면 목표 개수를 늘려 주세요."),
    ("DROP_PER_SEED_KEEP", LEVEL_INFO, "씨앗당 남길 수 초과", "씨앗 하나에서는 점수가 높은 후보만 남깁니다.", "다른 방향의 후보가 필요하면 씨앗을 나눠 등록해 주세요."),
    ("DROP_OTHER_CHANNEL", LEVEL_INFO, "다른 채널용 이슈", "다른 채널용으로 넣은 이슈는 이 채널의 후보로 쓰지 않습니다.", "이슈의 채널을 확인해 주세요."),
    ("DROP_SOURCES", LEVEL_WARNING, "출처 조건 부족", "공식 출처 1개 이상이거나 서로 독립인 출처 2곳 이상이어야 합니다.", "출처를 더해 주세요."),
    ("DROP_UNSTABLE", LEVEL_INFO, "안정화 시간 대기", "처음 알려진 뒤 48시간이 지난 뒤에 씁니다.", "48시간이 지난 뒤 다시 만들어 주세요."),
    # 한 번 돌린 결과 전체·보류 2
    ("SHORTAGE", LEVEL_INFO, "목표에 모자란 경로", "일부 경로의 후보가 목표보다 적습니다. 모자란 자리는 다른 경로가 채우지 않았습니다.", "씨앗·이력·이슈를 더하면 늘어납니다."),
    ("HOLD_BAND", LEVEL_INFO, "보류 구간", "점수가 보류 구간이라 일정 기간 보류함에 둡니다.", "그 사이 관심도나 시기가 바뀌면 다시 평가합니다."),
)
CATALOG = MappingProxyType({row[0]: row[1:] for row in _CATALOG_ROWS})
CODES = tuple(row[0] for row in _CATALOG_ROWS)

# `generate.Dropped.reason` → 알림 코드(계산이 아니라 명시한 표 — 시험이 `generate.DROP_REASONS` 와 같은 열쇠인지 본다). 브랜드 둘만 요청서가 코드 이름을 정해서 `DROP_` 접두가 없다.
DROP_REASON_NOTICE = MappingProxyType({
    "combination": "DROP_COMBINATION", "excluded_keyword": "DROP_EXCLUDED_KEYWORD", "too_long": "DROP_TOO_LONG", "language": "DROP_LANGUAGE", "no_seed": "DROP_NO_SEED", "not_due": "DROP_NOT_DUE",
    "no_keyword": "DROP_NO_KEYWORD", "invalid": "DROP_INVALID", "result_promise": "DROP_RESULT_PROMISE", "already_exists": "DROP_ALREADY_EXISTS", "over_target": "DROP_OVER_TARGET",
    "per_seed_keep": "DROP_PER_SEED_KEEP", "other_channel": "DROP_OTHER_CHANNEL", "sources": "DROP_SOURCES", "unstable": "DROP_UNSTABLE", "brand_only": "BRAND_ONLY", "brand_unfeasible": "BRAND_UNFEASIBLE",
})

# ---- 내부 식별자·파이썬 자료형 표기가 화면 글로 새는지 보는 검사 -----------------------------------------------------------------------------------
_INPUT_QUOTE = re.compile("‘[^’]*’")                               # 곡선 따옴표로 묶은 입력 인용 — 검사 전에 지운다
_LEAK_PATTERNS = (
    ("대괄호·중괄호", re.compile(r"[\[\]{}]")),
    ("홑따옴표 낱말", re.compile(r"(?<![A-Za-z0-9])'[^'\s][^']*'(?![A-Za-z0-9])")),
    ("밑줄이 든 영문 이름", re.compile(r"(?<![A-Za-z0-9_])[a-z]+_[a-z0-9_]+")),
    ("대문자 밑줄 코드", re.compile(r"(?<![A-Za-z0-9_])[A-Z]{2,}_[A-Z0-9_]+")),
    ("파이썬 낱말", re.compile(r"(?<![A-Za-z0-9_])(?:None|True|False|Enum|dict|tuple|frozenset|Notice)(?![A-Za-z0-9_])")),
    ("태그 모양", re.compile(r"<[A-Za-z/!]")),
    ("이스케이프 글자", re.compile(r"\\[nt]")),
)


def leaks(text):
    """글이 파이썬 목록 꼴·내부 식별자 같은 개발자용 표기를 품고 있으면 그 종류 이름의 튜플을, 깨끗하면 빈 튜플을 돌려준다(곡선 따옴표 `‘…’` 로 묶은 입력 인용은 지우고 본다). 빈 튜플이 '통과' 다."""
    shown = _INPUT_QUOTE.sub("", str(text))
    return tuple(name for name, pattern in _LEAK_PATTERNS if pattern.search(shown))


def is_clean(text):
    """`leaks(text)` 가 비었는가."""
    return not leaks(text)


def _one_line(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_LINE or "\n" in value or "\r" in value:
        raise ValueError(f"알림의 {name} 는 {MAX_LINE}자 이하의 한 줄 글이어야 한다")
    found = leaks(value)
    if found:
        raise ValueError(f"알림의 {name} 에 개발자용 표기가 있다: " + ", ".join(found))
    return value


@dataclasses.dataclass(frozen=True, kw_only=True)
class Notice:
    code: str                                                 # 내부 코드(카탈로그의 열쇠) — 화면에 내지 않는다
    level: str                                                # INFO · WARNING · ERROR
    title: str                                                # 사용자에게 보일 제목
    message: str                                              # 무슨 일인지(설명)
    action: str                                               # 권장 행동
    details: tuple = ()                                       # 글머리표로 보일 줄 — 고정 표의 낱말·건수·날짜·진단의 첫 사례 문장

    def __post_init__(self):
        if not isinstance(self.code, str) or self.code not in CATALOG:
            raise ValueError("알림 코드는 카탈로그에 있는 것이어야 한다")
        if not isinstance(self.level, str) or self.level not in LEVELS:
            raise ValueError("알림 수준은 INFO·WARNING·ERROR 중 하나여야 한다")
        for name in ("title", "message", "action"):
            _one_line(getattr(self, name), name)
        if not isinstance(self.details, tuple):
            raise ValueError("알림의 details 는 글의 tuple 이어야 한다(list 는 받지 않는다)")
        for line in self.details:
            _one_line(line, "details")

    def to_dict(self):
        """요청서 §8 의 JSON 모양 — 키는 정확히 여섯 개이고 details 는 list 다."""
        return {"code": self.code, "level": self.level, "title": self.title, "message": self.message, "action": self.action, "details": list(self.details)}

    def lines(self):
        """카드의 줄들 — 제목, 빈 줄, 설명, 행동, (세부가 있으면) 빈 줄과 글머리표 줄."""
        rows = [self.title, "", self.message, self.action]
        if self.details:
            rows.append("")
            rows.extend("- " + line for line in self.details)
        return tuple(rows)

    def text(self):
        """카드 하나(줄바꿈으로 이은 글)."""
        return "\n".join(self.lines())

    def one_line(self):
        """`제목 — 설명 행동` 한 줄(후보의 선정 이유 칸 용)."""
        return f"{self.title} — {self.message} {self.action}"


def level_of(code):
    """카탈로그의 코드 → 수준. 모르는 코드는 `ValueError`."""
    if not isinstance(code, str) or code not in CATALOG:
        raise ValueError("알림 코드는 카탈로그에 있는 것이어야 한다")
    return CATALOG[code][0]


def make(code, details=()):
    """카탈로그의 코드로 알림 하나를 만든다 — `details` 의 줄 가운데 개발자용 표기가 있는 줄은 뺀다(알림 전체가 깨지지 않게)."""
    level, title, message, action = CATALOG[code] if isinstance(code, str) and code in CATALOG else (None,) * 4
    if level is None:
        raise ValueError("알림 코드는 카탈로그에 있는 것이어야 한다")
    rows = tuple(line for line in (str(item) for item in details) if line.strip() and "\n" not in line and len(line) <= MAX_LINE and is_clean(line))
    return Notice(code=code, level=level, title=title, message=message, action=action, details=rows)


def sort_notices(notices):
    """수준이 높은 것 먼저, 같으면 카탈로그 순서(그다음은 들어온 순서)."""
    return tuple(sorted(notices, key=lambda item: (-LEVELS.index(item.level), CODES.index(item.code))))


def _word(text):
    return str(text).rstrip("*")                                # 표 항목의 끝 `*`(그 글자로 시작) 표기는 화면에 내지 않는다


def _finding_details(finding):
    code, matched, groups = finding.code, tuple(finding.matched), tuple(getattr(finding, "groups", ()))
    if code.startswith("HEALTH_"):
        return tuple(f"{groups[index]} — {_word(word)}" if index < len(groups) and groups[index] else _word(word) for index, word in enumerate(matched))
    if code in ("ECONOMIC_CHECK", "ECONOMIC_CONFLICT", "ECONOMIC_CONFIRMED"):
        return tuple(dict.fromkeys(groups))
    if code in ("EXPERIENCE_CLAIM", "RESULT_PROMISE"):
        return tuple(_word(word) for word in matched)
    return ()


def from_report(report):
    """안전 표시 결과(`safety.SafetyReport`) → 알림들(수준이 높은 것 먼저). 읽는 속성: `findings` 각각의 `code`·`matched`·`groups`."""
    return sort_notices(make(finding.code, _finding_details(finding)) for finding in report.findings)


def notes(report):
    """선정 이유용 한 줄들 — WARNING·ERROR 알림만(INFO 는 화면 알림으로만). `제목 — 설명 행동` 뒤에 `(걸린 말: …)` 을 쉼표로 이은 글로 붙인다. 결과 약속 줄에는 걸린 말을 붙이지 않는다."""
    lines = []
    for finding in report.findings:
        if level_of(finding.code) == LEVEL_INFO:
            continue
        line = make(finding.code).one_line()
        shown = tuple(_word(word) for word in (finding.matched or getattr(finding, "groups", ()))) if finding.code != "RESULT_PROMISE" else ()
        shown = tuple(word for word in shown if is_clean(word))
        lines.append(line + (f"(걸린 말: {', '.join(shown)})" if shown else ""))
    return tuple(lines)


def from_dropped(rows):
    """`generate.Dropped` 행들 → 알림들. 읽는 속성: `route`·`reason`·`count`·`detail`. 세부 줄은 `경로 이름 · N건` 과(`leaks` 를 통과할 때만) 첫 사례 문장이다. 모르는 이유는 `ValueError`."""
    found = []
    for row in rows:
        if row.reason not in DROP_REASON_NOTICE:
            raise ValueError("모르는 진단 이유다")
        route = wording.SOURCE_TYPE_KO.get(row.route, "")
        first = f"{route} · {row.count}건" if route else f"{row.count}건"
        found.append(make(DROP_REASON_NOTICE[row.reason], (first, row.detail)))
    return sort_notices(found)


def from_generated(result):
    """`generate.Generated` → 진단 알림들 + 모자란 경로가 있으면 `SHORTAGE`. 읽는 것: `dropped` 와 `shortages()`."""
    found = list(from_dropped(result.dropped))
    short = result.shortages()
    if short:
        found.append(make("SHORTAGE", tuple(f"{wording.SOURCE_TYPE_KO.get(route, '')} {number}개".strip() for route, number in short.items())))
    return sort_notices(found)


def from_brand(view):
    """`brand.BrandView` → 알림들. 읽는 속성: `state`·`outcome`·`notes`·`count`(·`skipped` 의 `reason`). 브랜드 단독이 아니면(`NOT_BRAND`) 빈 튜플이다."""
    if view.state != "BRAND_ONLY":
        return ()
    extra = tuple(view.notes) + ((f"하위 후보 {view.count}개",) if view.count else ())
    if view.outcome == "ready":
        found = [make("BRAND_SPECIFIED", extra)]
        if any(getattr(item, "reason", "") == "brand_unfeasible" for item in getattr(view, "skipped", ())):
            found.append(make("BRAND_UNFEASIBLE", tuple(f"{item.detail}" for item in view.skipped if item.reason == "brand_unfeasible")[:1]))
        return sort_notices(found)
    if view.outcome == "needs_topic":
        return (make("BRAND_ONLY", extra),)
    if view.outcome == "low_foundation":
        return (make("BRAND_UNFEASIBLE", extra),)
    raise ValueError("모르는 브랜드 구체화 결과다")


def hold_notice(candidate):
    """보류 구간(`HOLD`) 후보면 `HOLD_BAND`(세부: 검토 기한 날짜), 아니면 None. 읽는 속성: `recommendation_band`·`review_expires_at`."""
    if getattr(candidate, "recommendation_band", None) != "HOLD":
        return None
    due = getattr(candidate, "review_expires_at", None)
    return make("HOLD_BAND", (f"검토 기한 {str(due)[:10]}",) if due else ())


def for_candidate(candidate, report):
    """후보 하나의 화면 알림 — 안전 표시 알림들 + (보류 구간이면) 보류 알림."""
    found = list(from_report(report))
    held = hold_notice(candidate)
    if held is not None:
        found.append(held)
    return sort_notices(found)


def cards(notices):
    """알림 카드들을 빈 줄 하나씩 두고 이은 글."""
    return "\n\n".join(item.text() for item in notices)


def bullet_lines(notices):
    """한 알림당 한 줄 — `- 제목: 설명 행동`."""
    return tuple(f"- {item.title}: {item.message} {item.action}" for item in notices)


__all__ = [
    "CATALOG", "CODES", "DROP_REASON_NOTICE", "LEVELS", "LEVEL_ERROR", "LEVEL_INFO", "LEVEL_WARNING", "MAX_LINE", "Notice", "bullet_lines", "cards", "for_candidate", "from_brand", "from_dropped",
    "from_generated", "from_report", "hold_notice", "is_clean", "leaks", "level_of", "make", "notes", "sort_notices",
]
