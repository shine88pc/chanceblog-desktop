"""사진을 초안 본문의 어디에 어떤 줄로 넣을지 정한다(사진 연동 3단계, 설계 4-2·4-6) — **순수 함수**(파일·네트워크·시계·난수·화면 없음, 같은 입력은 늘 같은 결과).
입력은 규칙으로 만든 본문 블록들(`draft_body.BodyBlock`)과 **확정한 사진만** 담은 `DraftPhoto` 들(`photo_manifest.draft_inputs` — 경로·파일 이름이 없다)이고, 돌려주는 것은 사진 줄이 들어간 새 블록들과 알림 글들이다.

한 사진이 만드는 줄(최대 여섯, 이 순서):
  ① `{{사진 N}}`(틀로 만든 글 — 번호 N 은 화면의 사진 번호) ② 설명 글이 있으면 그 글 그대로(사용자 글) ③ 대상이 있으면 `<대상> 사진이에요.`(사용자 글 — 사용자의 말로 만든 문장이라 '지어내지 않기' 검사에서 빼고, 입력할 때 이미 '결과를 약속하는 표현' 검사를 거쳤다)
  ④ 메모가 있으면 그대로 한 문단(사용자 글). 대상이 없으면 틀 문장을 만들지 않는다 — 종류 이름만으로는 문장을 만들지 않는다(사용자가 만든 종류 이름이 섞일 수 있다).
  ⑤⑥ 확정한 글자(`DraftPhoto.confirmed_texts` — 글자 읽기에서 사용자가 줄마다 확인한 글, 결정 D-520)가 있으면 맨 끝에 둘이 더해진다: ⑤ 틀 문장 한 줄 `사진에 적힌 글이에요.`(합니다체 글에서는 `사진에 적힌 글입니다.` — 틀로 만든 글 — 사실이 없는 한 줄이라 '지어내지 않기' 검사와 마지막 관문이 본다)
    ⑥ 확정한 줄들을 줄바꿈 그대로 이은 문단 하나(사용자 글 — 입구 검사 `photo_manifest.check_text` 를 이미 거쳤고, 한 글자도 고치지 않으며, 가격·메뉴 이름·상호를 뽑거나 해석하지 않는다). 확정한 글자가 없으면 ⑤⑥ 은 없고 줄은 지금과 한 글자도 다르지 않다.
    ⑤ 와 ⑥ 이 서로 다른 문단인 까닭: 문단마다 '틀로 만든 글인가' 깃발이 하나뿐이라, 한 문단에 섞으면 틀 문장이 검사를 받지 못하거나 사용자 글이 그 검사에 걸려 초안이 거절된다. ⑥ 이 줄마다 한 문단이 아닌 까닭(결정 D-521): 초안 본문은 평문이라
    글 모양 점검(`check/garbage`)이 문단 속 줄을 이미 다루고(경고만) 복사 변환(`to_copy_text`)은 줄바꿈을 건드리지 않으며, 줄마다 한 문단이면 메뉴판·영수증 한 장이 빈 줄 수십 개로 늘어난다. 줄이 합쳐지는 곳은 마크다운 길(`render/naver` — 원고 전용)뿐이고 초안 본문은 그 길을 지나지 않는다.
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
SENTENCE_END = re.compile(r"(?<![.!?…])[.!?…]+[\"'”’)\]]*(?=\s|$)")                # 부호 덩어리의 맨 앞에서만 시작한다 — 덩어리 가운데서 다시 시작하면 구두점이 아주 길게 이어진 글에서 제곱 시간이었다(POLISH-1 PS-10, 마침표 2만 개 + 글자 하나 → 약 9초). 찾는 결과는 같다
SENTENCE_FORMS = ("에요", "예요", "입니다", "습니다", "해요", "어요", "아요")                      # 이미 문장으로 끝난 대상 — `사진이에요.` 를 더 붙이지 않는다
FRAME = "{subject} 사진이에요."
TEXT_FRAME = "사진에 적힌 글이에요."                                                       # 확정한 글자 문단의 틀 문장(결정 D-520) — 사실이 없는 한 줄. 공백·부호를 뺀 길이가 9 라 `check/garbage` 의 '같은 문장' 기준(10)에 못 미쳐 사진마다 되풀이돼도 경고가 나지 않는다(시험이 지킨다)
TEXT_FRAME_HAPSYO = "사진에 적힌 글입니다."                                                    # 합니다체 글의 틀 문장(결정 D-520 — 공백·부호를 뺀 길이 9 로 되풀이 경고 기준에 못 미친다, 시험이 지킨다)
STYLE_HAEYO, STYLE_HAPSYO = "haeyo", "hapsyo"                                  # `body_lang.STYLES` 와 같은 글(시험이 견준다 — 이 모듈이 그쪽을 가져오지 않으려고 글자로 적는다)
NL = chr(10)
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


def text_frame(style=STYLE_HAEYO):
    """확정한 글자 문단의 틀 문장 — 글의 문체를 따른다(`hapsyo` 면 합니다체, 그 밖에는 해요체 — 모르는 문체도 해요체다)."""
    return TEXT_FRAME_HAPSYO if style == STYLE_HAPSYO else TEXT_FRAME


def photo_lines(photo, style=STYLE_HAEYO):
    """사진 한 장이 본문에 만드는 줄들 → `((글, 틀로 만든 글인가), …)` — 자리표시자·설명 글·대상 문장·메모 순서이고, 확정한 글자가 있으면 맨 끝에 틀 문장(`text_frame` — 틀로 만든 글, 글의 문체를 따른다)과
    확정한 줄들을 줄바꿈으로 이은 문단 하나(사용자 글 — 한 글자도 고치지 않는다)가 더해진다. 확정한 글자가 없으면 지금과 한 글자도 다르지 않다(문체와 상관없이)."""
    lines = [(pm.placeholder(photo.number), True)]
    if photo.caption:
        lines.append((photo.caption, False))
    if photo.user_subject:
        lines.append((subject_sentence(photo.user_subject), False))
    if photo.user_note:
        lines.append((photo.user_note, False))
    if photo.confirmed_texts:
        lines.append((text_frame(style), True))
        lines.append((NL.join(photo.confirmed_texts), False))
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


def place_photos(blocks, photos, style=STYLE_HAEYO):
    """블록들에 확정한 사진 줄을 넣는다 → `(새 블록들, 알림 글들)`. 사진이 없으면 같은 블록들을 그대로 돌려준다(아무것도 바꾸지 않는다).
    `blocks` 는 `draft_body.BodyBlock` 모양(kind·key·heading·paragraphs·generated)이고 처음 블록이 도입이다. 입력은 바꾸지 않는다. `style` 은 글의 문체(`haeyo`·`hapsyo`)로 확정한 글자 문단의 틀 문장을 정한다."""
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
        inserts.setdefault(home, []).append((paragraph, cut, 0 if kind == "top" else 1, position, photo_lines(photo, style)))
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


def to_copy_text(text):
    """복사용 글 — 정확한 `{{사진 N}}` 만 `[이미지 N]` 으로 바꾼다(네이버 편집기에서 그 자리에 사진을 올리고 표시 글을 지운다 — 기존 `[이미지 N]` 표시와 같은 모양). 그 밖의 글은 한 글자도 안 바꾼다. 정확한 자리 바깥에 붙은 중괄호는 저장 형식 규칙(`photo_manifest.find_placeholders`·`stray_braces`)처럼 남은 글자로 보고 건드리지 않는다 — 그런 글(`{{사진 1}}}`)은 글 모양 점검이 `{{ … }}` 자리표시로 걸러 낸다(POLISH-1 PS-10)."""
    return pm.PLACEHOLDER.sub(lambda found: f"[이미지 {found.group(1)}]", text) if isinstance(text, str) else text


__all__ = ["TEXT_FRAME", "TEXT_FRAME_HAPSYO", "place_photos", "photo_lines", "subject_sentence", "sentence_ends", "text_frame", "to_copy_text"]
