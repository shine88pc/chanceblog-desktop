"""주제 후보 화면의 규칙 — 카드·상세에 보일 글 만들기·거르기·찾기·정렬·개수 요약·배지·키워드 칩. 순수 계산(파일·시계·화면 도구 없음).

  · **점수·구간은 홈과 같은 두 함수**(`gauges.clean_score`·`gauges.score_band`)가 정한다 — 이 파일은 새 점수·새 구간 규칙을 만들지 않는다(점수가 없으면 구간은 `none` = `점수 계산 전`, 0점이 아니다).
  · 카드: 배지 **최대 둘**(작업 상태 하나 + 안전 표시 하나), 키워드 칩 **최대 셋**(나머지는 `+N`), 추천 이유 요약 **120자 이내**(비밀 모양을 가린 뒤에 줄인다). 상세: 같은 후보의 모든 값을 있는 그대로.
  · **거르기**는 채널·작업 상태·점수 구간·주제 묶음·글 검색이고 모두 읽기뿐이다(파일을 바꾸지 않는다). 글 검색은 제목·키워드에서 공백으로 나눈 조각이 **모두** 들어 있는 후보를 찾는다(대소문자는 가리지 않는다) — 친 글은 어디에도 남기지 않는다.
  · 정렬은 점수가 높은 것부터(점수 없음은 맨 뒤)이고 같으면 보관함에 먼저 들어온 것이 앞이다. 관심도(Trend)는 `최근 관심도(상대값)` 이고 검색한 횟수가 아니다 — 그런 칸도 글도 없다.
  · 안전 표시 문장은 엔진의 고정 문장(`notice`)이 그대로 나오고 이 파일은 줄 수·순서만 고른다. 보류 기한은 한국 날짜로 한 번만 보인다(엔진 안내 속의 UTC 날짜 줄은 뺀다 — 두 날짜가 어긋나 보이지 않게).
"""
from __future__ import annotations

from ...content import candidates as legacy
from ...topics import channels as ch
from ...topics import notice, safety, wording
from ...topics import score as sc
from . import gauges as G
from .board_view import date_text, time_text
from .text import T, display_text

PAGE = 24                                                  # 한 번에 그리는 카드 수 — 3열·2열 모두 나누어떨어진다. 더 보려면 '더 보기'
SUMMARY_MAX = 120                                          # 카드의 추천 이유 요약 글자 수 상한(C-Type §7.4: 설명 80~120자 이내)
CHIPS_MAX = 3                                              # 카드의 키워드 칩 수 상한 — 나머지는 `+N`
BADGES_MAX = 2                                             # 카드의 배지 수 상한(C-Type §7.4)
TITLE_LIMIT = 200
CHIP_LIMIT = 14                                            # 카드의 칩 하나의 글자 수 상한(넘으면 …) — 가장 좁은 카드(230)의 안쪽 폭에 들어가는 길이
BAND_KEYS = tuple(band.key for band in G.BANDS) + ("none",)             # high · good · mid · low · none(점수 계산 전)
STATUS_KEYS = ("all", *legacy.STATUSES)
STATUS_TONE = {legacy.NEW: "info", legacy.REVIEW: "info", legacy.SELECTED: "ok", legacy.HOLD: "muted", legacy.REJECTED: "muted"}      # 상태 배지의 바탕 — 색만이 아니라 늘 글자가 함께 있다
LEVEL_TONE = {notice.LEVEL_INFO: "info", notice.LEVEL_WARNING: "warning", notice.LEVEL_ERROR: "danger"}
LEVEL_TEXT = {notice.LEVEL_INFO: "cand_level_info", notice.LEVEL_WARNING: "cand_level_warning", notice.LEVEL_ERROR: "cand_level_error"}
TOPIC_ICONS = (("t_spark", "blue"), ("t_bolt", "orange"), ("t_laptop", "purple"), ("t_calc", "green"), ("t_box", "blue"), ("t_droplet", "green"), ("t_headphones", "purple"), ("t_coffee", "orange"))    # 장식 — 분야를 뜻하지 않는다
SAFETY_TITLES = tuple(sorted({row[1] for row in notice.CATALOG.values() if row[0] in (notice.LEVEL_WARNING, notice.LEVEL_ERROR)}, key=len, reverse=True))      # 선정 이유 줄 중 안전 표시 안내(`제목 — 설명 행동`)를 가려내는 데 쓴다
HOLD_DETAIL = "검토 기한"                                    # 엔진의 보류 안내 속 UTC 날짜 줄의 머리 — 한국 날짜 줄이 따로 있어 뺀다


def shown(value, limit=300):
    """화면에 나가는 외부 글(후보 제목·키워드·이유 …)에서 비밀 모양을 가리고 한 줄로 줄인다 — **가리기가 먼저, 자르기가 나중이다**(홈·Seed 관리와 같은 규칙)."""
    return display_text(value, limit)


# ---- 점수·구간(홈과 같은 규칙) ---------------------------------------------------------------------------------------------------------
def score_of(candidate):
    """후보의 최종 점수(0~100 정수) 또는 None(점수 계산 전). 홈의 추천 줄과 같은 `gauges.clean_score` 다."""
    return G.clean_score(candidate.scores.final)


def band_key(candidate):
    """후보의 점수 구간 열쇠 — 홈 링과 같은 `gauges.score_band`(`high`·`good`·`mid`·`low`), 점수가 없으면 `none`."""
    band = G.score_band(score_of(candidate))
    return band.key if band is not None else "none"


def band_name(key):
    for band in G.BANDS:
        if band.key == key:
            return band.name
    return T["cand_band_none"] if key == "none" else ""


def status_name(status):
    return legacy.STATUS_KO.get(status, "")


def type_name(candidate):
    """후보 종류(지속형·계절형·실시간·후속·협찬 준비형·월별 반복형)의 한국어 이름 — 서비스의 쉬운 이름 표 그대로."""
    return wording.CANDIDATE_TYPE_KO.get(candidate.candidate_type, "")


# ---- 거르기·찾기·정렬 ---------------------------------------------------------------------------------------------------------------------
def query_words(text):
    """검색 글 → 찾을 조각들(한 줄로 다듬고 공백으로 나눠 소문자로)."""
    return tuple(piece for piece in " ".join(text.split()).casefold().split(" ") if piece) if isinstance(text, str) else ()


def haystack(candidate):
    return " ".join((candidate.topic, candidate.primary_keyword, *candidate.secondary_keywords)).casefold()


def matches(row, channel="all", status="all", band="all", cluster="all", words=()):
    """이 후보가 거르기 조건에 맞는가 — 모든 조건을 지켜야 하고 검색 조각은 제목·키워드에 모두 있어야 한다."""
    item = row.candidate
    if channel != "all" and item.channel != channel:
        return False
    if status != "all" and item.work_status != status:
        return False
    if band != "all" and band_key(item) != band:
        return False
    if cluster != "all" and item.topic_cluster != cluster:
        return False
    if words:
        hay = haystack(item)
        return all(word in hay for word in words)
    return True


def sort_rows(rows):
    """점수가 높은 것부터(점수 없음은 맨 뒤), 같으면 보관함에 먼저 들어온 것이 앞."""
    def order(row):
        score = score_of(row.candidate)
        return (score is None, -(score or 0), row.ordinal)
    return sorted(rows, key=order)


def counts_by(rows, getter, keys):
    """한 가지 기준의 값마다 후보 수(`all` 은 전체) — 다른 거르기와 상관없이 전체 후보 기준이다."""
    counts = {key: 0 for key in keys}
    counts["all"] = 0
    for row in rows:
        counts["all"] += 1
        value = getter(row.candidate)
        if value in counts:
            counts[value] += 1
    return counts


def cluster_keys(rows):
    """있는 주제 묶음들(처음 나온 순서) — 이름이 없는 묶음은 식별자 그대로 보인다."""
    seen = []
    for row in rows:
        if row.candidate.topic_cluster not in seen:
            seen.append(row.candidate.topic_cluster)
    return tuple(seen)


def cluster_name(slug):
    return wording.CLUSTER_KO.get(slug) or slug


# ---- 카드 글 ------------------------------------------------------------------------------------------------------------------------------
def reason_lines(candidate):
    """선정 이유 줄들을 (추천 이유 줄들, 안전 표시 안내 줄들) 로 가른다 — 안전 표시 안내는 `제목 — 설명 행동` 모양이라 카드의 추천 이유에서는 빼고 상세 `안전 표시` 에서 따로 보인다."""
    main, safe = [], []
    for line in candidate.selection_reasons:
        (safe if any(line.startswith(title + " — ") for title in SAFETY_TITLES) else main).append(line)
    return main, safe


def summary(candidate):
    """카드의 추천 이유 요약 — 안전 안내를 뺀 이유 줄을 ` · ` 로 이어 **120자 이내**로(가린 뒤 줄인다). 줄 하나가 120자보다 길면 그 줄을 줄이고, 이유가 없으면 빈 글이다."""
    lines = [display_text(line, 10_000) for line in reason_lines(candidate)[0]]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    text = ""
    for line in lines:
        joined = line if not text else text + " · " + line
        if len(joined) > SUMMARY_MAX:
            break
        text = joined
    return text or display_text(lines[0], SUMMARY_MAX)


def keyword_chips(candidate):
    """카드의 키워드 칩 — (보이는 글 최대 셋, 가려진 개수). 핵심 키워드가 먼저다."""
    words = [candidate.primary_keyword, *candidate.secondary_keywords]
    return [shown(word, CHIP_LIMIT) for word in words[:CHIPS_MAX]], max(0, len(words) - CHIPS_MAX)


def avatar_text(key, name):
    """채널 아바타 안의 글자 하나 — 네이버 A·B 는 A·B, 그 밖은 표시 이름의 첫 글자."""
    fixed = {"naver_a": "A", "naver_b": "B"}.get(key)
    if fixed:
        return fixed
    for char in str(name):
        if not char.isspace():
            return char.upper()
    return "?"


def topic_icon(cluster):
    """이미지 자리의 주제 아이콘·계열 — 주제 묶음 이름으로 늘 같은 것을 고른다(장식이라 분야를 뜻하지 않는다)."""
    index = sum(ord(char) for char in str(cluster)) % len(TOPIC_ICONS)
    return TOPIC_ICONS[index]


def notices_of(candidate):
    """후보 하나의 화면 안내들(안전 표시 + 보류 구간 안내) — 엔진의 같은 순수 함수가 정한다. 안전 평가가 후보 하나에 1~2ms 라 보이는 카드·열린 상세에서만 부른다(컨트롤러가 기억한다)."""
    return notice.for_candidate(candidate, safety.assess(candidate))


def card_badges(candidate, stop, notices):
    """카드의 배지 — 작업 상태 하나는 늘 있고, 안전 표시가 있으면 하나 더(`자동 초안 중지`가 `주의`보다 앞선다). **최대 둘**이다."""
    badges = [{"kind": "status", "tone": STATUS_TONE.get(candidate.work_status, "muted"), "text": status_name(candidate.work_status)}]
    if stop:
        badges.append({"kind": "caution", "tone": "danger", "text": T["cand_badge_stop"]})
    elif any(item.level in (notice.LEVEL_WARNING, notice.LEVEL_ERROR) for item in notices):
        badges.append({"kind": "caution", "tone": "warning", "text": T["cand_badge_caution"]})
    return badges[:BADGES_MAX]


# ---- 상세 글 ------------------------------------------------------------------------------------------------------------------------------
def factor_rows(candidate, weights=()):
    """점수 구성 — 엔진의 여섯 항목 점수를 있는 그대로(새 점수를 만들지 않는다). 평가하지 못한 항목은 0점이 아니라 `평가 전` 이고 막대가 없다. `weights` 는 `((항목, 가중치), …)`."""
    factors, weight_of = candidate.scores.factors, dict(weights)
    rows = []
    for name in ch.FACTOR_NAMES:
        value, label = getattr(factors, name), ch.FACTOR_LABELS[name]
        weight = weight_of.get(name)
        weight_text = T["cand_factor_weight"].format(n=weight) if isinstance(weight, int) else ""
        if value is None:
            text, fraction = T["cand_factor_missing"], 0.0
        else:
            text, fraction = T["cand_factor_value"].format(n=value), value / 100
        spoken = T["cand_factor_row_a11y_weight"].format(name=label, value=text, n=weight) if weight_text else T["cand_factor_row_a11y"].format(name=label, value=text)
        rows.append({"name": label, "missing": value is None, "value": value, "text": text, "fraction": fraction, "weight_text": weight_text, "a11y": spoken})
    return rows


def trend_rows(candidate):
    """최근 관심도(상대값) 칸들 — 값이 있으면 값·변화·비교 기간·비교 키워드·조회일, 없으면 `데이터 부족`(또는 조회하지 못했을 때 `조회하지 못했어요`). 월 검색량 같은 칸은 없다."""
    ratio = candidate.trend_ratio
    if ratio is None:
        text = T["cand_trend_unavailable"] if candidate.data_status == sc.DATA_UNAVAILABLE else T["cand_trend_missing"]
        return [(T["cand_trend_label_value"], text, True)], T["cand_trend_note_missing"]
    rows = [(T["cand_trend_label_value"], T["cand_trend_value"].format(n=ratio), False)]
    if candidate.trend_status in sc.DETERMINATE_TRENDS:
        rows.append((T["cand_trend_label_change"], sc.TREND_STATUS_KO[candidate.trend_status], False))
    if candidate.trend_period:
        rows.append((T["cand_trend_label_period"], shown(candidate.trend_period, 60), False))
    if candidate.trend_compared_group:
        rows.append((T["cand_trend_label_group"], ", ".join(shown(word, 30) for word in candidate.trend_compared_group), False))
    if candidate.trend_queried_on:
        rows.append((T["cand_trend_label_day"], shown(candidate.trend_queried_on, 12), False))
    return rows, T["cand_trend_note"]


def seed_rows(candidate, seed=None):
    """Seed 출처 — 후보가 생긴 경로와 그 Seed(낱말·분류). Seed 번호는 글에 나가지 않는다 — 찾지 못했으면 그렇게 말한다."""
    rows = [(T["cand_seed_route"], wording.SOURCE_TYPE_KO.get(candidate.source_type, ""), False)]
    if seed is not None:
        path = T["cand_seed_path"].format(major=shown(seed.major, 30), minor=shown(seed.minor, 30)) if seed.major or seed.minor else ""
        word = wording.quote(shown(seed.keyword, 60), 40)
        rows.append((T["cand_seed_word"], word + (" · " + path if path else ""), False))
    elif candidate.seed_id:
        rows.append((T["cand_seed_word"], T["cand_seed_unknown"], True))
    else:
        rows.append((T["cand_seed_word"], T["cand_seed_none"], True))
    return rows


def safety_cards(notices, stop):
    """안전 표시 카드들 — 엔진의 고정 문장(제목·설명·권장 행동·세부 줄)을 그대로. 보류 안내의 UTC 날짜 줄은 뺀다(한국 날짜는 `다시 볼 기한` 에 한 번만 보인다)."""
    cards = []
    for item in notices:
        details = tuple(line for line in item.details if not line.startswith(HOLD_DETAIL))
        cards.append({"tone": LEVEL_TONE[item.level], "level": T[LEVEL_TEXT[item.level]], "title": item.title, "message": item.message, "action": item.action, "details": list(details)})
    return cards, (T["cand_safety_stop"] if stop else "")


def hold_row(candidate):
    """보류 구간 후보의 다시 볼 기한(한국 날짜) — 기한이 없으면 None."""
    day = date_text(candidate.review_expires_at) if candidate.review_expires_at else ""
    return {"label": T["cand_sec_hold"], "value": T["cand_hold_text"].format(date=day), "note": T["cand_hold_note"]} if day else None


def info_rows(candidate, channel_name):
    """기본 정보 — 채널·후보 종류·검색 의도·글 종류·주제 묶음·대상 독자·언어·만든 때(한국 시각)·중복 판정·비슷한 글 수."""
    none = T["cand_info_none"]
    rows = [(T["cand_info_channel"], shown(channel_name, 40) or wording.CHANNEL_KO.get(candidate.channel, "")), (T["cand_info_type"], wording.CANDIDATE_TYPE_KO.get(candidate.candidate_type, none)),
            (T["cand_info_intent"], wording.SEARCH_INTENT_KO.get(candidate.search_intent, none)), (T["cand_info_content"], wording.CONTENT_TYPE_KO.get(candidate.content_type, none)),
            (T["cand_info_cluster"], shown(cluster_name(candidate.topic_cluster), 40)), (T["cand_info_reader"], shown(candidate.target_reader, 80)), (T["cand_info_lang"], wording.LANGUAGE_KO.get(candidate.language, none)),
            (T["cand_info_created"], time_text(candidate.created_at) or none), (T["cand_info_dup"], wording.DUPLICATE_STATUS_KO.get(candidate.duplicate_status, none))]
    if candidate.similar_post_ids:
        rows.append((T["cand_info_similar"], T["cand_info_similar_value"].format(n=len(candidate.similar_post_ids))))
    return [{"label": label, "value": value, "missing": value == none} for label, value in rows]


def tag_names(candidate):
    """협업 가능 유형의 한국어 이름들(표에 없는 태그는 쓴 사람의 글 그대로 — 가린 뒤 줄인다)."""
    return [wording.TAG_KO.get(tag) or shown(tag, 30) for tag in candidate.monetization_tags]
