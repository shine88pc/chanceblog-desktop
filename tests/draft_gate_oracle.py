"""복사 전 관문(`ui/core/draft_rules.py`)의 **옛 방식** 사본 — 시험 도구(시험 모듈이 아니다). 감사 AS-S2 권고-4 의 속도 고침(결정 D-681)이 판정을 바꾸지 않았음을 무작위 입력으로 견주는 기준이다.

감사 때의 `secret_spots`·`_place`·`secret_places`(main 9439047)를 그대로 옮겼다 — 같은 `draft_rules` 안의 바뀌지 않은 도우미(`_ADDRESS`·`_address_hit`·`_spot`·`_KEY_RUN`·`_scanner_spans` …)를 부른다. **고치지 않는다**: 이 사본이 바뀌면 '같다' 는 증거가 사라진다.
`old_secret_spots` 는 이름 붙은 값(D-682)을 모른다 — 새 판정과 같은 입력은 이름 낱말이 없는 글이고, 이름 낱말이 든 글에서는 새 판정이 옛 판정을 **포함**한다(더 막을 뿐 덜 막지 않는다).
"""
from chanceblog_desktop.ui.core import draft_rules as rules
from chanceblog_desktop.ui.core.text import T


def old_secret_spots(text):
    from chanceblog_desktop.security.mask import has_key_shape, mask
    from chanceblog_desktop.security.shape import MAX_SCAN_CHARS, looks_secret
    if not isinstance(text, str):
        return ((0, 0),)
    if len(text) > MAX_SCAN_CHARS:
        return ((0, 1),)
    spots, parts, last = [], [], 0
    for found in rules._ADDRESS.finditer(text):
        hit = rules._address_hit(found.group())
        if hit is not None:
            spots.append(rules._spot(found.start(), found.end(), hit))
        parts += [text[last:found.start()], " " * (found.end() - found.start())]
        last = found.end()
    parts.append(text[last:])
    rest = "".join(parts)
    for found in rules._KEY_RUN.finditer(rest):
        run = found.group()
        if "." in run and (run.rpartition(".")[2].lower() in rules.FILE_EXTENSIONS or rules._BARE_ADDRESS.match(run)):
            hit = rules._address_hit(run)
        else:
            hit = (0, None) if looks_secret(run) else None
        if hit is not None:
            spots.append(rules._spot(found.start(), found.end(), hit))
    if not spots and has_key_shape(text):
        at = rules._first_difference(text, mask(text))
        spots.append((at, at + 1))
    for span in rules._scanner_spans(text):
        if not any(span[0] < other[1] and other[0] < span[1] for other in spots):
            spots.append(span)
    return tuple(sorted(spots))


def old_place(name, text, start, end):
    from chanceblog_desktop.security.mask import mask
    before = text[max(0, start - rules.CONTEXT_BEFORE):start]
    hit = text[start:end]
    masked = mask(hit)
    front = T["drf_spot_hidden"] if not hit else (masked if masked != hit else T["drf_spot_hidden"])
    if hit and masked == hit and any(start < other_end and other_start < end for other_start, other_end in rules._scanner_spans(text)):
        front = T["drf_spot_hidden"]
    if hit and masked != hit and before.endswith("="):
        front = T["drf_spot_hidden"]
    return f"{name} — " + ("…" if start > rules.CONTEXT_BEFORE else "") + rules.shown(before + front, rules.PREVIEW)


def old_secret_places(*named):
    places = []
    for name, text in named:
        for start, end in old_secret_spots(text):
            place = old_place(name, text, start, end) if isinstance(text, str) else str(name)
            if place not in places:
                places.append(place)
            if len(places) >= rules.SPOT_LIMIT:
                return tuple(places)
    return tuple(places)


def old_merge(spots, spans):
    """검사기 자리 합치기의 옛 방식 — 자리마다 앞의 모든 자리와 하나씩 견준다(제곱 시간)."""
    spots = list(spots)
    for span in spans:
        if not any(span[0] < other[1] and other[0] < span[1] for other in spots):
            spots.append(span)
    return spots
