"""사진을 초안 본문의 어디에 어떤 줄로 넣을지 정한다(사진 연동 3단계, 설계 4-2·4-6) — **순수 함수**(파일·네트워크·시계·난수·화면 없음, 같은 입력은 늘 같은 결과).
입력은 규칙으로 만든 본문 블록들(`draft_body.BodyBlock`)과 **확정한 사진만** 담은 `DraftPhoto` 들(`photo_manifest.draft_inputs` — 경로·파일 이름이 없다)이고, 돌려주는 것은 사진 줄이 들어간 새 블록들과 알림 글들이다.

한 사진이 만드는 줄(최대 넷, 이 순서):
  ① `{{사진 N}}`(틀로 만든 글 — 번호 N 은 화면의 사진 번호) ② 설명 글이 있으면 그 글 그대로(사용자 글) ③ 대상이 있으면 `<대상> 사진이에요.`(사용자 글 — 사용자의 말로 만든 문장이라 '지어내지 않기' 검사에서 빼고, 입력할 때 이미 '결과를 약속하는 표현' 검사를 거쳤다)
  ④ 메모가 있으면 그대로 한 문단(사용자 글). 대상이 없으면 틀 문장을 만들지 않는다 — 종류 이름만으로는 문장을 만들지 않는다(사용자가 만든 종류 이름이 섞일 수 있다).
사용자 글은 한 글자도 고치지 않는다(문장 사이에서 갈라 넣을 때 갈라지는 자리의 공백만 사라진다). 본문을 몰래 고치지 않는다 — 못 찾은 자리나 옮긴 자리는 알림 글에 **사진 번호로만** 적는다(글·경로 없음).

자리 규칙(설계 4-2):
  · 들어갈 곳(`preferred_section`): `도입`=도입 블록 · `내용 소제목`=내용 블록들(소제목이 있는 블록 — 경험 단락 포함) · `분위기 소제목`=소제목에 `분위기` 가 들어간 블록(없으면 내용 블록들로 옮기고 알린다) · `마무리`=마무리 블록 ·
    그 밖의 글은 정확히 같은 소제목(공백을 접어 견준다) → 별칭(`주의`·`경험`·`intro`·`closing`·`cautions`·`experience`) → 못 찾으면 `자동` 으로 두고 알린다. 비어 있으면(`자동`) 내용 블록들이다.
  · 후보 블록이 여럿이면 같은 후보를 쓰는 사진들을 `display_order` 순으로 **고르게** 나눈다(소제목 S 개·사진 P 장이면 k 번째 사진은 floor((k-1)·S/P) 번째 블록).
  · 블록 안의 자리(`placement`): `자동`=첫 문단 뒤 · `맨 앞`=본문 맨 앞(도입 블록의 첫 문단 앞, 들어갈 곳과 상관없이) · `소제목 바로 뒤`=소제목 바로 뒤(도입처럼 소제목이 없으면 첫 문단 앞) ·
    `n 번째 문단 뒤`=n 번째 문단 뒤(모자라면 마지막 문단 뒤에 넣고 알린다) · `n 번째 문장 뒤`=그 블록 **첫 문단**의 n 번째 문장 뒤(문장 끝은 `.`·`!`·`?`·`…` 로만 본다 — 모자라면 첫 문단 뒤에 넣고 알린다).
  · 같은 자리의 사진은 `맨 앞` 사진이 먼저이고 나머지는 `display_order` 순서대로 잇는다.
"""
from __future__ import annotations

import dataclasses
import re

from . import photo_manifest as pm

INTRO, SECTION, EXPERIENCE, CAUTIONS, CLOSING, REFERENCES = "intro", "section", "experience", "cautions", "closing", "references"      # `draft_body.KINDS` 와 같은 글(시험이 견준다 — 이 모듈이 그쪽을 가져오지 않으려고 글자로 적는다)
CONTENT_KINDS = (SECTION, EXPERIENCE)
SECTION_INTRO, SECTION_CONTENT, SECTION_MOOD, SECTION_CLOSING = "도입", "내용 소제목", "분위기 소제목", "마무리"
MOOD_WORD = "분위기"
KIND_ALIASES = {"주의": CAUTIONS, "경험": EXPERIENCE, "intro": INTRO, "closing": CLOSING, "cautions": CAUTIONS, "experience": EXPERIENCE}
SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s|$)")
SENTENCE_FORMS = ("에요", "예요", "입니다", "습니다", "해요", "어요", "아요")                      # 이미 문장으로 끝난 대상 — `사진이에요.` 를 더 붙이지 않는다
FRAME = "{subject} 사진이에요."
NOTE_SECTION = "사진 {n}번은 고른 들어갈 곳을 찾지 못해 내용 소제목에 넣었어요."
NOTE_MOOD = "사진 {n}번은 분위기 소제목을 찾지 못해 내용 소제목에 넣었어요."
NOTE_PARAGRAPH = "사진 {n}번은 문단이 모자라 그 소제목의 마지막 문단 뒤에 넣었어요."
NOTE_SENTENCE = "사진 {n}번은 첫 문단에 문장이 모자라 첫 문단 뒤에 넣었어요."
MAX_NOTES = 30


def subject_sentence(subject):
    """대상 → 본문 문장. 이미 문장으로 끝났으면 그대로, 아니면 `<대상> 사진이에요.` — 대상은 한 글자도 고치지 않는다."""
    text = subject.strip()
    if text.endswith((".", "!", "?", "…")) or text.endswith(SENTENCE_FORMS):
        return text
    return FRAME.format(subject=text)


def photo_lines(photo):
    """사진 한 장이 본문에 만드는 줄들 → `((글, 틀로 만든 글인가), …)` — 자리표시자·설명 글·대상 문장·메모 순서."""
    lines = [(pm.placeholder(photo.number), True)]
    if photo.caption:
        lines.append((photo.caption, False))
    if photo.user_subject:
        lines.append((subject_sentence(photo.user_subject), False))
    if photo.user_note:
        lines.append((photo.user_note, False))
    return tuple(lines)


def sentence_ends(text):
    """문단 속 문장 끝 위치들(글자 번호, 끝 글자 다음) — 문장은 `.`·`!`·`?`·`…` 와 그 뒤의 닫는 따옴표·괄호로 끝나고 뒤에 공백이나 글의 끝이 올 때만 끝으로 본다."""
    return tuple(found.end() for found in SENTENCE_END.finditer(text))


def _heading_key(text):
    return "".join(text.split())


@dataclasses.dataclass(frozen=True)
class _Target:
    group: tuple            # 후보 블록 번호들(고르게 나누는 대상 — 같은 후보를 쓰는 사진끼리 나눈다)
    note: str = ""          # 알림 글 틀('' 이면 없음)


def _candidates(blocks):
    """블록 번호 묶음들 — 도입·내용·마무리·글 모양별."""
    by_kind = {}
    for index, block in enumerate(blocks):
        by_kind.setdefault(block.kind, []).append(index)
    return {kind: tuple(indices) for kind, indices in by_kind.items()}


def _target(section, blocks, by_kind):
    """들어갈 곳 글 → `_Target`. 비어 있으면 내용 블록들."""
    content = tuple(by_kind.get(SECTION, ()) + by_kind.get(EXPERIENCE, ())) or tuple(by_kind.get(INTRO, ()) or (0,))
    content = tuple(sorted(content))
    text = section.strip()
    if not text:
        return _Target(content)
    if text == SECTION_INTRO:
        return _Target(tuple(by_kind.get(INTRO, ())) or content)
    if text == SECTION_CONTENT:
        return _Target(content)
    if text == SECTION_CLOSING:
        return _Target(tuple(by_kind.get(CLOSING, ())) or content)
    if text == SECTION_MOOD:
        mood = tuple(index for index in content if MOOD_WORD in blocks[index].heading)
        return _Target(mood) if mood else _Target(content, NOTE_MOOD)
    key = _heading_key(text)
    exact = tuple(index for index, block in enumerate(blocks) if block.heading and _heading_key(block.heading) == key)
    if exact:
        return _Target(exact[:1])
    kind = KIND_ALIASES.get(text)
    if kind is not None and by_kind.get(kind):
        return _Target(tuple(by_kind[kind][:1]))
    return _Target(content, NOTE_SECTION)


def _spread(count, groups):
    """같은 후보 묶음의 k 번째(1부터) 사진이 갈 블록 — floor((k-1)·S/P)."""
    return [groups[(k - 1) * len(groups) // count] for k in range(1, count + 1)]


def place_photos(blocks, photos):
    """블록들에 확정한 사진 줄을 넣는다 → `(새 블록들, 알림 글들)`. 사진이 없으면 같은 블록들을 그대로 돌려준다(아무것도 바꾸지 않는다).
    `blocks` 는 `draft_body.BodyBlock` 모양(kind·key·heading·paragraphs·generated)이고 처음 블록이 도입이다. 입력은 바꾸지 않는다."""
    blocks = tuple(blocks)
    photos = tuple(sorted(photos, key=lambda item: (item.display_order, item.number)))
    if not photos or not blocks:
        return blocks, ()
    by_kind = _candidates(blocks)
    notes = []
    inserts = {}          # 블록 번호 → [(문단 번호, 문장 끝 번호, 맨 앞 순위, 사진 순서, 줄들)]
    groups = {}           # 후보 묶음 → 그 묶음을 쓰는 (사진 위치 번호, 알림 글 틀)
    for position, photo in enumerate(photos):
        if photo.placement.kind == "top":
            target = _Target((0,))
        else:
            target = _target(photo.preferred_section, blocks, by_kind)
        groups.setdefault(target.group, []).append((position, target.note))
    chosen = {}
    for group, members in groups.items():
        homes = _spread(len(members), group)
        for (position, note), home in zip(members, homes):
            chosen[position] = (home, note)
    for position, photo in enumerate(photos):
        home, note = chosen[position]
        if note:
            notes.append(note.format(n=photo.number))
        block = blocks[home]
        count = len(block.paragraphs)
        kind, nth = photo.placement.kind, photo.placement.nth
        paragraph, cut = (1 if count else 0), 0
        if kind == "top":
            paragraph = 0
        elif kind == "after_heading":
            paragraph = 0
        elif kind == "after_paragraph":
            paragraph = min(nth, count)
            if nth > count:
                notes.append(NOTE_PARAGRAPH.format(n=photo.number))
        elif kind == "between_sentences":
            ends = sentence_ends(block.paragraphs[0]) if count else ()
            if nth < len(ends):
                paragraph, cut = 0, nth
            else:
                paragraph = 1 if count else 0
                if nth > len(ends):
                    notes.append(NOTE_SENTENCE.format(n=photo.number))
        inserts.setdefault(home, []).append((paragraph, cut, 0 if kind == "top" else 1, position, photo_lines(photo)))
    result = list(blocks)
    for home, items in inserts.items():
        result[home] = _rebuilt(blocks[home], items)
    return tuple(result), tuple(dict.fromkeys(notes))[:MAX_NOTES]


def _rebuilt(block, items):
    """한 블록에 사진 줄을 끼워 넣은 새 블록."""
    items = sorted(items, key=lambda item: item[:4])
    texts, flags = [], []
    count = len(block.paragraphs)
    for index in range(count + 1):
        for paragraph, cut, _rank, _position, lines in items:
            if paragraph == index and cut == 0:
                for text, made in lines:
                    texts.append(text)
                    flags.append(made)
        if index == count:
            break
        text, made = block.paragraphs[index], block.generated[index]
        cuts = [item for item in items if item[0] == index and item[1] > 0]
        if not cuts:
            texts.append(text)
            flags.append(made)
            continue
        ends = sentence_ends(text)
        start = 0
        for _paragraph, cut, _rank, _position, lines in cuts:
            end = ends[cut - 1]
            piece = text[start:end].strip()
            if piece:                                                                # 같은 자리에 사진이 여럿이면 두 번째부터는 앞 조각이 비어 있다
                texts.append(piece)
                flags.append(made)
            for line, line_made in lines:
                texts.append(line)
                flags.append(line_made)
            start = end
        texts.append(text[start:].strip())
        flags.append(made)
    return dataclasses.replace(block, paragraphs=tuple(texts), generated=tuple(flags))


__all__ = ["place_photos", "photo_lines", "subject_sentence", "sentence_ends"]
