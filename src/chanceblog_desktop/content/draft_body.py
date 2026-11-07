"""규칙 기반 초안 본문(`DraftBody`) — 후보 하나·블로그 프로필(선택)·선택 입력(선택)으로 **AI 없이** 네이버에 복사해 직접 고쳐 쓸 수 있는 정보형 초안을 만든다
(운영자 확정 답변 2026-11-06 1절: AI Key 가 없어도 제목·본문·키워드·태그·카테고리까지 복사 가능한 초안). 순수 함수다 — 파일·네트워크·시계·난수를 쓰지 않고 같은 입력은 글자까지 같은 초안이다(`zlib.crc32` 시드로 문장 변형을 돌려 고른다).

구성(최소 13가지): 제목 후보 3개·선택 제목 1개·도입부·소제목 4개 이상과 소제목별 문단(2~3개)·주의사항·마무리·핵심 키워드·보조 키워드·태그·추천 카테고리·한 줄 요약·확인 권장 항목.
글 유형·안전 대체·제목·태그·확인 권장은 `build_plan`(작성 기반)의 결과를 그대로 쓰고, 본문은 그 위에 문단 틀(`body_library`·`body_blocks`)로 쓴다.

**지어내지 않는다**(이 모듈에서 가장 큰 규칙):
  · 문단 틀은 '무엇을 확인할지·어떻게 고를지'만 말한다 — 사실·수치·가격·날짜·평가·효과·최상급·1인칭 경험·협찬 낱말이 없다(시험이 전수 확인한다).
  · 완성한 문장마다 `check/claims.py` 의 `find_claims` 로 검사한다 — 위반은 다른 변형으로 바꾸고 안 되면 뺀다(확인 권장 낱말은 후보의 글에서 온 것만 남긴다). 마지막에 본문 전체를 한 번 더 검사하고 걸리면 멈춘다.
  · 사용자가 입력한 글(경험·의견·전하고 싶은 내용·반드시 넣을 문장·결론·가격·날짜·참고 주소)은 **그대로** 먼저 쓴다. 경험은 입력했을 때만 경험 단락이 들어간다.
  · 협찬 가능 분야(프로필)에 해당하는 후보에는 협찬 사실을 알릴 **자리 안내만** 확인 권장에 둔다(본문에 협찬 문구 없음). 건강·금융·법률 낱말이 있으면 주의사항에 전문가·공식 기관 확인 문단을 더한다.
  · 실제 블로그 이름·ID·주소는 쓰지 않는다 — 프로필의 표시 이름·별명·블로그 ID 는 읽지도 않는다. 후보·프로필·선택 입력의 글에 키 모양(`security.mask` 가 가리는 것과 `security.shape` 가 찾는 것 모두)이 있으면 만들지 않는다(`CONTENT_INVALID`).
  · **분야는 후보의 낱말에서 확실히 읽을 때만 읽는다**(`body_bank.domain_of`) — 못 읽으면 일반 틀만 쓴다. 채널 프로필의 주제·역할·소개글로 분야를 짐작하지 않는다(독립 검증 H1).
  · **안전 판정**(`safety`): 호출하는 쪽(서비스)이 주제 엔진의 안전 판정(`topics.safety.check_text` 의 결과)을 주면 — 자동 초안 중지(`stop`)는 만들지 않고 거절하고, 근거 확인 필요 단계는 확인 권장 맨 위에 경고를 둔다.
    이 모듈은 `topics/` 를 가져오지 않고 결과의 속성(`stop`·`stage`·`relationship`)만 읽는다. 후보의 글에 단정·최상급·효과 낱말(`body_bank.ASSERTION_WORDS`)이 있으면 판정과 상관없이 확인 권장 맨 위에 경고를 둔다.
분량: 공백을 뺀 글자 수 1,880자 이상·공백을 포함해 2,740자 이하를 목표로 선택 문단·문장을 켜고 끄며 맞춘다(시험 기준은 1,800~2,800자 — 시험은 숫자를 직접 적는다). 소제목은 4~6개.
`channel`(주제 엔진의 채널 프로필 — `topics/channels.py` 의 `ChannelProfile`)은 이 모듈이 `topics/` 를 가져오지 않게 속성만 읽는다(말투·대상 독자·카테고리·협찬 가능 분야). 채널 프로필의 제외 키워드 칸은 읽지 않는다 — 화면이 그 칸을 '저장만 된다' 고 말하고 그 사실을 못박은 시험이 있어서, 읽게 하려면 화면 문구를 함께 고치는 별도 묶음이 필요하다(D-262·D-269).
"""
from __future__ import annotations

import dataclasses
import re
import zlib
from dataclasses import dataclass

from ..check import claims as claim_check
from ..errors import AppError
from . import body_bank as bb
from . import body_blocks as blocks
from . import body_lang as bl
from . import body_library as lib
from . import draft_plan as dp
from . import post_types as pt
from .draft_options import LABELS, DraftOptions, squash

LOW_CHARS = 1880                 # 공백을 뺀 글자 수 하한 목표(시험 기준 1,800자에 여유)
HIGH_SPACED = 2740               # 공백을 포함한 글자 수 상한 목표(시험 기준 2,800자에 여유)
MAX_AUX_KEYWORDS = 5             # 보조 키워드 최대 개수
MIN_TAGS = 5                     # 태그가 이보다 적으면 보조 키워드로 채운다
MAX_TAG = 30                     # 태그 한 개의 최대 글자 수(복사 패키지와 같다)
MAX_PARAGRAPH = 180              # 사용자 글을 문단으로 나눌 때의 길이(문장 끝에서 나눈다)
MIN_PARAGRAPH_LIMIT = 120        # 프로필의 문단 길이 상한이 이보다 짧아도 틀로 만든 문단은 이 길이까지는 늘린다(필수 문장만으로 이미 넘는 문단은 그대로)
NL = chr(10)
INTRO, SECTION, EXPERIENCE, CAUTIONS, CLOSING, REFERENCES = "intro", "section", "experience", "cautions", "closing", "references"
KINDS = (INTRO, SECTION, EXPERIENCE, CAUTIONS, CLOSING, REFERENCES)
REFERENCES_HEADING = "참고한 자료"
# 작성 기반(`draft plan`)의 확인 권장 가운데 '계획' 말로 쓰인 일반 안내 — 본문에서는 아래 `checks` 가 본문 말로 다시 쓰므로 그대로 옮기지 않는다(시험이 이 낱말들이 아직 작성 기반에 있는지 본다)
PLAN_GENERIC_CHECKS = ("직접 겪은 경험이 있으면", "이 제품을 직접 이용해 본 경험이 있다면", "가격·날짜 같은 수치는 계획에 넣지 않았습니다", "참고 자료를 입력하지 않았습니다")
STAGE_STOP, STAGE_EVIDENCE, STAGE_MARK = "stop", "evidence", "mark"        # `topics.safety.STAGE_*` 와 같은 값(이 모듈이 `topics/` 를 가져오지 않으려고 글자로 적고, 서비스 시험이 같은지 본다)
RELATION_SUSPECTED = "suspected"                                          # `topics.safety.RELATION_SUSPECTED`
STOP_ITEM = "후보(안전 판정에서 자동 초안 중지 후보라 본문을 만들지 않았습니다 — 후보 보기에서 이유를 확인해 주세요)"
EVIDENCE_NOTE = "후보의 제목·키워드가 건강 효과를 근거 없이 말하기 쉬운 주제입니다(안전 판정: 근거 확인 필요) — 본문은 일반적인 확인 순서만 담았으니, 효과나 결과를 말하는 문장은 공식·전문 자료로 확인한 것만 직접 보태 주세요."
SPONSOR_WORD_NOTE = "후보의 글에 협찬·광고를 뜻하는 말이 들어 있어 본문 곳곳에 그대로 되풀이됩니다 — 실제로 협찬이나 제공을 받았는지 확인해 글 앞부분에 직접 밝히거나, 아니라면 키워드에서 그 말을 덜어 주세요."
ASSERTION_NOTE = "후보의 제목·키워드에 단정·최상급·효과를 말하는 표현({words})이 있어 본문 곳곳에 그대로 되풀이됩니다 — 근거를 확인하지 못했다면 후보의 키워드를 바꾸거나 본문에서 그 표현을 덜어 주세요."
PRICE_LEAD = "참고로 확인한 내용은 다음과 같아요."
PRICE_TAIL = "값은 바뀔 수 있으니 올리는 날 한 번 더 확인해 주세요."
USER_ITEMS = ("message", "experience", "opinion", "must_include", "price_date", "conclusion", "urls")
# 참고 주소 칸에서 찾는 키 접두사 — `security.shape` 가 찾는 모양 가운데 `security.mask` 가 가리지 못하는 것(구글 OAuth 계열 3종·깃허브 세분화 접두사·깃허브 토큰 접두사·32자 이상 16진 글자).
# 주소 칸에는 영숫자 덩어리 규칙을 쓸 수 없다(정상 주소도 `/`·`.` 로 이어져 24자를 넘고 글자와 숫자가 섞여 있다) — 접두사만 앞 글자가 영숫자가 아닐 때 본다('task-management' 속의 'sk-' 는 키가 아니다).
URL_KEY_SHAPES = re.compile("(?<![A-Za-z0-9])AQ[.][0-9A-Za-z_-]{10,}" "|(?<![A-Za-z0-9])GOCSPX-[0-9A-Za-z_-]{8,}" "|(?<![A-Za-z0-9])1//0[0-9A-Za-z_-]{10,}" "|(?<![A-Za-z0-9])ya29[.][0-9A-Za-z_-]{10,}"
                            "|(?<![A-Za-z0-9])gh[pousr]_[0-9A-Za-z]{10,}" "|(?<![A-Za-z0-9])github_pat_[0-9A-Za-z_]{10,}" "|(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")
FREE_OPTION_TEXTS = ("message", "experience", "opinion", "must_include", "price_date", "conclusion", "audience", "title_direction", "exclude")          # 키 모양을 보는 선택 입력 칸(주소 칸은 따로)
CHANNEL_TEXT = ("tone", "audience", "channel_role")
CHANNEL_LISTS = ("categories", "monetization_focus", "main_topics")


def _invalid(item, detail=""):
    return AppError("CONTENT_INVALID", {"항목": item}, detail=detail or item)


@dataclass(frozen=True)
class BodyBlock:
    kind: str                       # intro·section·experience·cautions·closing·references
    key: str                        # 소제목 단계 열쇠('' 이면 단계가 없는 블록)
    heading: str                    # 소제목('' 이면 도입부)
    paragraphs: tuple               # 문단들(글)
    generated: tuple                # 문단마다 True(틀로 만든 글)·False(사용자가 입력한 글)

    def to_dict(self):
        return {"kind": self.kind, "key": self.key, "heading": self.heading, "paragraphs": list(self.paragraphs), "generated": list(self.generated)}


@dataclass(frozen=True)
class DraftBody:
    blog: str
    keyword: str
    topic: str
    post_type: str
    style: str                      # haeyo·hapsyo
    domain: str                     # 후보의 낱말에서 읽은 분야(body_bank.DOMAINS)
    audience: str
    titles: tuple                   # 제목 후보 3개
    selected_title: str
    blocks: tuple                   # BodyBlock — 도입부·소제목들·(경험)·주의사항·마무리·(참고 자료) 순서
    core_keywords: tuple            # 핵심 키워드
    sub_keywords: tuple             # 보조 키워드
    tags: tuple
    category: str                   # '' 이면 정하지 못했다
    summary: str                    # 한 줄 요약
    checks: tuple                   # 확인 권장
    title_text: str                 # 복사용: 제목만
    body_text: str                  # 복사용: 본문만(제목 없음)
    plain_text: str                 # 복사용: 제목 + 본문
    tags_text: str                  # 복사용: 태그만(`#태그 #태그`)
    chars: int                      # 본문 글자 수(공백·줄바꿈 제외)
    chars_with_spaces: int          # 본문 글자 수(공백 포함, 줄바꿈 제외)
    used: tuple                     # 반영한 사용자 입력 칸 이름(USER_ITEMS 중)
    sponsor_slot: bool              # 협찬 사실을 알릴 자리 안내가 확인 권장에 있는가(본문에는 협찬 문구가 없다)
    sensitive: object               # 'health'·'finance'·'legal' 또는 None
    dropped: int                    # 제외할 낱말·검사에 걸려 쓰지 못한 문장 칸의 수
    replaced: object                # `DraftPlan.replaced`(후기·방문 전제를 정보형으로 바꿨으면 (이전, 이후))

    # ---- 읽기 ------------------------------------------------------------------------------------------------------
    @property
    def intro(self):
        return self.blocks[0]

    @property
    def sections(self):
        """소제목이 있는 내용 블록들(경험 단락 포함, 주의사항·마무리·참고 자료 제외) — 4~6개."""
        return tuple(block for block in self.blocks if block.kind in (SECTION, EXPERIENCE))

    @property
    def cautions(self):
        return next(block for block in self.blocks if block.kind == CAUTIONS)

    @property
    def closing(self):
        return next(block for block in self.blocks if block.kind == CLOSING)

    def generated_texts(self):
        """틀로 만든 글(제목·한 줄 요약·소제목·문단) — '지어내지 않기' 검사를 돌릴 때 쓴다. 사용자가 입력한 문단은 뺀다."""
        found = [*self.titles, self.summary]
        for block in self.blocks:
            if block.heading:
                found.append(block.heading)
            found += [text for text, made in zip(block.paragraphs, block.generated) if made]
        return tuple(found)

    def user_paragraphs(self):
        return tuple(text for block in self.blocks for text, made in zip(block.paragraphs, block.generated) if not made)

    def to_dict(self):
        return {
            "blog": self.blog, "keyword": self.keyword, "topic": self.topic, "post_type": self.post_type, "style": self.style, "domain": self.domain, "audience": self.audience,
            "titles": list(self.titles), "selected_title": self.selected_title, "blocks": [block.to_dict() for block in self.blocks], "core_keywords": list(self.core_keywords),
            "sub_keywords": list(self.sub_keywords), "tags": list(self.tags), "category": self.category, "summary": self.summary, "checks": list(self.checks),
            "title_text": self.title_text, "body_text": self.body_text, "plain_text": self.plain_text, "tags_text": self.tags_text, "chars": self.chars, "chars_with_spaces": self.chars_with_spaces,
            "used": list(self.used), "sponsor_slot": self.sponsor_slot, "sensitive": self.sensitive, "dropped": self.dropped,
            "replaced": None if self.replaced is None else {"from": self.replaced[0], "to": self.replaced[1]},
        }


# ---- 평문 렌더링 ---------------------------------------------------------------------------------------------------------------------
def render_body(block_list):
    """블록들 → 평문 본문. 소제목·문단은 한 줄씩이고 사이에는 빈 줄 하나뿐이다(마크다운·HTML 기호 없음, 처음과 끝에 빈 줄 없음)."""
    parts = []
    for block in block_list:
        if block.heading:
            parts.append(block.heading)
        parts += list(block.paragraphs)
    return (NL + NL).join(parts)


def count_chars(text):
    """(공백·줄바꿈을 뺀 글자 수, 줄바꿈을 뺀 글자 수 — 공백 포함)."""
    return len("".join(text.split())), len(text.replace(NL, ""))


class _Item:
    """문단 하나의 재료 — 필수 문장과 길이가 모자랄 때만 더하는 선택 문장, 문단 전체가 선택인지(`group`)."""
    __slots__ = ("required", "optional", "group", "use_group", "use_optional")

    def __init__(self, required, optional, group):
        self.required, self.optional, self.group = required, optional, group
        self.use_group, self.use_optional = not group, False

    def sentences(self):
        if not self.use_group:
            return ()
        return (*self.required, *(self.optional if self.use_optional else ()))

    def text(self):
        return " ".join(self.sentences())


class _Part:
    """블록 하나의 재료 — 앞에 오는 사용자 문단(`lead`)·틀로 만든 문단들(`items`)·뒤에 오는 사용자 문단(`trail`)."""
    def __init__(self, kind, key, heading, items=(), lead=(), trail=()):
        self.kind, self.key, self.heading, self.items, self.lead, self.trail = kind, key, heading, list(items), list(lead), list(trail)

    def paragraphs(self):
        made = [(item.text(), True) for item in self.items if item.sentences()]
        return [(text, False) for text in self.lead] + made + [(text, False) for text in self.trail]

    def block(self):
        pairs = self.paragraphs()
        return BodyBlock(self.kind, self.key, self.heading, tuple(text for text, _made in pairs), tuple(made for _text, made in pairs))


def _split_user(texts):
    """사용자가 입력한 글 → 문단들(글은 그대로이고 긴 글만 문장 끝에서 나눈다)."""
    paragraphs = []
    for text in texts:
        if len(text) <= MAX_PARAGRAPH:
            paragraphs.append(text)
            continue
        current = ""
        for sentence in claim_check.split_sentences(text):
            if current and len(current) + 1 + len(sentence) > MAX_PARAGRAPH:
                paragraphs.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            paragraphs.append(current)
    return paragraphs


def _fit(parts, limit):
    """분량 맞추기 — 필수 문장만으로 시작해 공백을 뺀 글자 수가 목표에 모자라면 선택 문단(셋째 문단)·선택 문장을 차례로 켜고(문단이 `limit` 자를 넘기게 되는 선택 문장은 켜지 않는다), 공백 포함 글자 수가 넘치면 거꾸로 끈다."""
    switches = []
    for part in parts:
        switches += [(item, "group") for item in part.items if item.group and item.required]
    for part in parts:
        switches += [(item, "optional") for item in part.items if item.optional and not item.group]
    for part in parts:
        switches += [(item, "optional") for item in part.items if item.optional and item.group]

    def flip(item, which, on):
        if which == "group":
            item.use_group = on
        else:
            item.use_optional = on

    def measure():
        return count_chars(render_body([part.block() for part in parts]))

    for item, which in switches:
        if measure()[0] >= LOW_CHARS:
            break
        flip(item, which, True)
        if which == "optional" and len(item.text()) > limit:
            flip(item, which, False)
    for item, which in reversed(switches):
        if measure()[1] <= HIGH_SPACED:
            break
        flip(item, which, False)


class _Writer:
    def __init__(self, candidate, profile, channel, options, plan, safety=None):
        self.candidate, self.profile, self.channel, self.options, self.plan, self.safety = candidate, profile, channel, options, plan, safety
        self.keyword, self.topic, self.subs = plan.keyword, plan.topic, plan.sub_keywords
        self.post_type, self.voice = plan.post_type, pt.VOICE[plan.blog]
        raw_texts = self.raw_texts = (candidate.keyword, candidate.topic, *candidate.sub_keywords)
        self.stage = getattr(safety, "stage", "") if safety is not None else ""
        words = [*options.exclude, *(getattr(profile, "excluded_topics", ()) or ())]
        self.blocked_terms = tuple(term for term in (squash(word) for word in words) if term)
        self.forbidden_terms = tuple(term for term in (squash(word) for word in (getattr(profile, "forbidden_phrases", ()) or ())) if term)
        self.domain = bb.domain_of(raw_texts)                                                 # 후보의 낱말만으로 — 못 읽으면 일반(채널 프로필의 주제·역할은 분야 짐작에 쓰지 않는다)
        self.bank = {role: tuple(item for item in items if not self.blocked(" ".join(item) if isinstance(item, tuple) else item)) for role, items in bb.bank_of(self.domain).items()}      # 제외할 낱말이 든 확인할 항목은 쓰지 않는다
        self.sensitive = bb.sensitive_kind(raw_texts) or ("health" if self.stage in (STAGE_MARK, STAGE_EVIDENCE) else None)           # 주제 엔진이 건강 주제로 판정했으면 낱말 목록에 없어도 건강
        self.style = bl.style_of_tone(getattr(channel, "tone", ""), getattr(profile, "tone", ""))
        self.audience = options.audience or getattr(channel, "audience", "") or plan.audience
        self.seed = zlib.crc32(f"{plan.blog}|{plan.keyword}|{plan.post_type}".encode("utf-8"))
        self.counter = 0
        self.used_sentences = set()
        self.last_start = ""                                     # 바로 앞 문단의 첫 두 낱말 — 같은 틀로 연달아 시작하지 않으려고 본다
        self.dropped = 0
        self.renamed = 0                                         # 제외할 낱말 때문에 키워드로 대신한 소제목 수
        self.input_flat = claim_check.flat(" ".join((self.keyword, self.topic, *self.subs, self.audience)))
        self.sponsor_slot = bool(channel is not None and bb.focus_hit(self.domain, getattr(channel, "monetization_focus", ())))

    # ---- 입력 읽기 ----------------------------------------------------------------------------------------------------------------
    def blocked(self, skeleton):
        """틀의 고정 글(후보의 낱말 자리를 뺀 것)에 제외할 낱말·금지 표현이 있는가."""
        plain = squash(skeleton)
        return any(term in plain for term in (*self.blocked_terms, *self.forbidden_terms))

    # ---- 문장 만들기 ----------------------------------------------------------------------------------------------------------------
    def passes(self, text):
        """완성한 문장이 '지어내지 않기' 검사를 통과하는가 — 위반은 모두 막고, 확인 권장(가격·날짜·시각·통계)은 후보의 글에서 온 낱말일 때만 둔다."""
        for claim in claim_check.find_claims([text]):
            if claim_check.is_violation(claim.category) or claim.word not in self.input_flat:
                return False
        return True

    def render(self, template, values):
        if self.blocked(bl.skeleton(template)):
            return None
        text = bl.tidy(bl.in_style(bl.collapse(bl.fill(template, values)), self.style))
        return text if self.passes(text) else None

    def choose(self, variants, values, first=False):
        """문장 칸 하나 → 문장(쓸 수 있는 변형 가운데 시드로 돌려 고른다). 쓸 수 있는 변형이 없으면 None. 문단의 첫 문장(`first`)은 바로 앞 문단과 첫 두 낱말이 같은 변형을 피한다(다른 변형이 있을 때)."""
        options = (variants,) if isinstance(variants, str) else tuple(variants)
        usable = [template for template in options if all(values.get(name) for name in bl.slots_of(template))]
        self.counter += 1
        if not usable:
            return None                                                                        # 보조 키워드가 없어 쓸 수 없는 칸 — 쓰지 못한 문장이 아니다
        start = (self.seed + self.counter * 7) % len(usable)
        for offset in range(len(usable)):
            text = self.render(usable[(start + offset) % len(usable)], values)
            if text is None:
                continue
            key = squash(text)
            if key in self.used_sentences:
                continue
            head = " ".join(text.split(" ")[:2])
            if first and head == self.last_start and offset < len(usable) - 1:
                continue
            if first:
                self.last_start = head
            self.used_sentences.add(key)
            return text
        self.dropped += 1
        return None

    def item(self, slots, values, group=False):
        required, optional = [], []
        for index, variants in enumerate(slots):
            text = self.choose(variants, values, first=index == 0)
            if text is not None:
                (optional if index >= 2 else required).append(text)
        return _Item(required, optional, group)

    def items(self, paragraphs, values):
        return [self.item(slots, values, group=index >= 2) for index, slots in enumerate(paragraphs)]

    # ---- 값 자리 -------------------------------------------------------------------------------------------------------------------
    def values(self, offset):
        """틀의 `{…}` 자리에 들어갈 값 — 소제목마다(`offset`) 목록의 시작 자리를 달리해 같은 항목이 되풀이되지 않게 한다."""
        bank, seed = self.bank, self.seed
        found = {"kw": self.keyword, "aud": self.audience, "thing": bb.THING[self.domain]}
        for index, sub in enumerate(self.subs[:2], 1):
            found[f"sub{index}"] = sub
        for role, prefix, count in (("C", "c", 4), ("M", "m", 3), ("Z", "z", 3), ("W", "w", 3), ("P", "p", 3), ("I", "i", 3), ("B", "b", 3)):
            if not bank[role]:
                continue                                                                      # 제외할 낱말 때문에 항목이 다 빠졌으면 그 자리를 쓰는 틀은 못 쓴다
            picker = bb.pick_ordered if role == "Z" else bb.pick                              # 원인 후보(Z)는 목록에 적힌 '쉬운 것에서 어려운 것' 순서 그대로(끝에서 돌아 골라도 앞뒤가 뒤바뀌지 않게)
            chosen = picker(bank[role], seed + offset * 2 + ord(role), count)
            for number, text in enumerate(chosen, 1):
                found[f"{prefix}{number}"] = text
            found[role] = bl.listing(chosen[:3])
        if bank["F"]:
            for number, (situation, criterion) in enumerate(bb.pick(bank["F"], seed + offset * 2 + ord("F"), 3), 1):          # 상황과 그 상황에서 먼저 볼 기준은 짝으로 간다
                found[f"f{number}"], found[f"g{number}"] = situation, criterion
        if bank["C"]:
            found["K"] = bl.listing(bb.pick(bank["C"], seed + 5 + offset, 4))
        return found

    # ---- 소제목 ---------------------------------------------------------------------------------------------------------------------
    def heading(self, step):
        for voice in (self.voice, 1 - self.voice):
            template = step.heads[voice]
            if self.blocked(template.replace("{kw}", "")) or bl.clashes_with_style(template, self.style):                  # 합니다체 소제목이 해요체 글에 섞이지 않게
                continue
            text = bl.collapse(template.replace("{kw}", self.keyword))
            if self.passes(text):
                return text
        return self.named(step.name)

    def named(self, name):
        """고정 소제목 이름 — 제외할 낱말·금지 표현이 들어 있으면 쓰지 않고 키워드로 대신한다(소제목에서도 제외한 낱말은 빠진다)."""
        if not self.blocked(name):
            return name
        self.renamed += 1
        return self.keyword

    def body_steps(self):
        keys = list(lib.BODY_STEPS[self.post_type])
        if self.options.experience:
            keys = [key for key in keys if key != lib.DROPPED_FOR_EXPERIENCE.get(self.post_type)]
        steps = [lib.step_of(self.post_type, key) for key in keys]
        return [step for step in steps if not self.blocked(step.name)]

    # ---- 블록 만들기 ----------------------------------------------------------------------------------------------------------------
    def intro_part(self, names):
        profile = self.profile
        style = (dp.style_of(profile.intro_style, dp.INTRO_STYLES) if profile is not None and profile.intro_style else None) or dp.DEFAULT_INTRO[self.voice]
        difficulty = (dp.style_of(profile.difficulty, dp.DIFFICULTY_STYLES) if profile is not None and profile.difficulty else None) or dp.DEFAULT_DIFFICULTY
        values = self.values(0)
        values["N"] = bl.listing(names[:3])
        first = self.item(blocks.INTRO_FIRST[self.post_type][style], values)
        order = (0, 2, 1) if self.options.audience else (0, 1, 2)                              # 사용자가 독자를 입력했으면 그 문장을 꼭 넣고 설명 난이도 문장은 길이가 모자랄 때만 넣는다
        pieces = (blocks.INTRO_SECOND[0], blocks.INTRO_SECOND[1][difficulty], blocks.INTRO_SECOND[2])
        second = self.item(tuple(pieces[index] for index in order), values)
        return _Part(INTRO, "", "", [first, second], trail=_split_user([self.options.message] if self.options.message else []))

    def section_parts(self, steps):
        must = list(self.options.must_include)
        parts = []
        for number, step in enumerate(steps):
            part = _Part(SECTION, step.key, self.heading(step), self.items(lib.section_texts(self.post_type, step.key), self.values(number + 1)))
            part.trail += [sentence for index, sentence in enumerate(must) if index % len(steps) == number]          # 반드시 넣을 문장은 소제목마다 돌아가며 문단 하나로
            if number == min(1, len(steps) - 1) and self.options.price_date:
                part.trail.append(self.price_paragraph())
            parts.append(part)
        return parts

    def price_paragraph(self):
        """사용자가 확인한 가격·날짜 — 입력한 글을 그대로 잇고 앞뒤에 틀 문장을 붙인다."""
        items = [text if text.endswith((".", "?", "!")) else text + "." for text in self.options.price_date]
        lead = [] if self.blocked(PRICE_LEAD) else [bl.in_style(PRICE_LEAD, self.style)]                 # 앞뒤 안내 문장도 제외할 낱말이 있으면 쓰지 않는다
        tail = [] if self.blocked(PRICE_TAIL) else [bl.in_style(PRICE_TAIL, self.style)]
        return " ".join([*lead, *items, *tail])

    def experience_part(self):
        step = pt.EXPERIENCE_STEPS[self.post_type]
        return _Part(EXPERIENCE, step.key, self.heading(step), trail=_split_user([self.options.experience]))

    def cautions_part(self, offset):
        values = self.values(offset)
        items = self.items(blocks.CAUTIONS[self.post_type], values)
        if self.sensitive:
            items.insert(2, self.item(blocks.SENSITIVE[self.sensitive], values))                  # 건강·금융·법률 안내는 꼭 들어간다(필수 문단)
        return _Part(CAUTIONS, "caution", self.heading(lib.caution_step()), items)

    def closing_part(self, offset):
        profile = self.profile
        values = self.values(offset)
        style = (dp.style_of(profile.ending_style, dp.ENDING_STYLES) if profile is not None and profile.ending_style else None) or dp.DEFAULT_ENDING
        items = [self.item(blocks.CLOSING_FIRST[self.post_type], values), self.item(blocks.CLOSING_SECOND[style], values)]
        lead = _split_user([text for text in (self.options.opinion, self.options.conclusion) if text])
        return _Part(CLOSING, "summary", self.heading(lib.closing_step(self.post_type)), items, lead=lead)

    def references_part(self):
        return _Part(REFERENCES, "", self.named(REFERENCES_HEADING), trail=list(self.options.urls)) if self.options.urls else None

    def parts(self):
        steps = self.body_steps()
        names = [step.name for step in steps[1:]] or [step.name for step in steps]
        built = [self.intro_part(names), *self.section_parts(steps)]
        if self.options.experience:
            built.append(self.experience_part())
        built += [self.cautions_part(len(steps) + 1), self.closing_part(len(steps) + 2)]
        references = self.references_part()
        if references is not None:
            built.append(references)
        limit = max(self.profile.paragraph_max_chars if self.profile is not None else dp.DEFAULT_PARAGRAPH, MIN_PARAGRAPH_LIMIT)
        _fit(built, limit)
        return built

    # ---- 키워드·태그·카테고리·한 줄 요약 ------------------------------------------------------------------------------------------------
    def aux_keywords(self):
        found = list(self.subs)
        seen = {squash(self.keyword), *(squash(text) for text in found)}
        for tail in (blocks.SENSITIVE_TAILS if self.sensitive else blocks.KEYWORD_TAILS[self.post_type]):          # 건강·금융·법률 키워드에 '해결 방법'·'예방' 같은 꼬리를 붙이지 않는다
            if len(found) >= MAX_AUX_KEYWORDS:
                break
            text = bl.collapse(f"{self.keyword} {tail}")
            if squash(text) in seen or self.blocked(tail) or not self.safe_short(text):
                continue
            seen.add(squash(text))
            found.append(text)
        return tuple(found[:MAX_AUX_KEYWORDS])

    def safe_short(self, text):
        return not any(claim_check.is_violation(claim.category) for claim in claim_check.find_claims([text]))

    def tags(self, aux):
        found = [tag for tag in self.plan.tags if not (self.sensitive and tag.endswith(blocks.CURE_TAG_TAILS))]         # 건강·금융·법률 키워드에는 '…해결'·'…예방' 태그를 두지 않는다(작성 기반의 태그에서 덜어 낸다)
        seen = {squash(tag) for tag in found}
        limit = self.profile.max_tags if self.profile is not None else dp.DEFAULT_TAG_LIMIT
        for text in (*aux, *(blocks.SENSITIVE_TAGS if self.sensitive else blocks.GENERIC_TAGS[self.post_type])):
            if len(found) >= min(limit, MIN_TAGS + 3):
                break
            tag = "".join(text.split()).replace("#", "").strip(",;")
            if not tag or len(tag) > MAX_TAG or squash(tag) in seen or not self.safe_short(tag) or self.blocked(squash(tag).replace(squash(self.keyword), "")):
                continue
            seen.add(squash(tag))
            found.append(tag)
        return tuple(found[:limit])

    def category(self):
        """추천 카테고리 — 작성 기반이 프로필의 매핑으로 정한 것, 없으면 채널 프로필의 카테고리 가운데 ① 이름이 후보의 글에 들어 있는 것 ② 이름에 후보의 분야 낱말(`body_bank.TRIGGERS_KO`)이 든 것
        ③ 하나뿐이면 그것. 못 정하면 ''(확인 권장에 직접 고르라고 적는다)."""
        if self.plan.category:
            return self.plan.category
        names = [name for name in (getattr(self.channel, "categories", ()) or ()) if name]
        plain = squash(" ".join((self.keyword, self.topic, *self.subs)))
        for name in names:
            if squash(name) in plain:
                return name
        triggers = [squash(word) for word in bb.TRIGGERS_KO.get(self.domain, ())]
        for name in names:
            if any(word and word in squash(name) for word in triggers):
                return name
        return names[0] if len(names) == 1 else ""

    def summary(self):
        """한 줄 요약 — 글 유형의 틀 둘 가운데 시드로 하나를 고르고 안 되면 다른 것, 둘 다 안 되면 키워드만 적는다."""
        values, templates = self.values(0), blocks.SUMMARY[self.post_type]
        for number in range(len(templates)):
            text = self.render(templates[(self.seed + number) % len(templates)], values)
            if text:
                return text
        return bl.in_style(f"{self.keyword}." if self.blocked("정리") else f"{self.keyword} 정리.", self.style)

    def selected_title(self):
        titles = self.plan.titles
        head = squash(self.keyword)
        return next((title for title in titles if squash(title).startswith(head)), titles[0])

    # ---- 확인 권장 -------------------------------------------------------------------------------------------------------------------
    def warnings(self):
        """확인 권장 맨 위에 두는 경고 — 후보의 글이 본문 곳곳에 그대로 되풀이되는데 단정·효과를 말할 수 있는 경우. 걸린 말은 고정 표의 낱말이고 입력한 글을 되풀이하지 않는다.
        ① 주제 엔진이 근거 확인 필요로 판정한 건강 주제 ② 협찬 낱말 추정 ③ 단정·최상급·효과 낱말(`body_bank.ASSERTION_WORDS`)."""
        found = []
        if self.stage == STAGE_EVIDENCE:
            found.append(EVIDENCE_NOTE)
        if getattr(self.safety, "relationship", "") == RELATION_SUSPECTED:
            found.append(SPONSOR_WORD_NOTE)
        hits = bb.assertion_hits(self.raw_texts)
        if hits:
            found.append(ASSERTION_NOTE.format(words=", ".join(f"‘{word}’" for word in hits)))
        return found

    def checks(self, category, block_count, chars):
        found = [*self.warnings(), "본문은 입력하신 내용과 일반적인 확인 순서만으로 만든 기본 글입니다 — 제품·서비스·장소의 실제 사양, 가격, 운영 정보는 넣지 않았으니 공식 자료에서 확인한 값을 직접 보태 주세요."]
        if not self.options.experience:
            found.append("직접 사용하거나 방문하거나 구매한 경험은 본문에 넣지 않았습니다 — 경험이 있다면 ‘실제 사용 경험’ 칸에 적어 경험 단락을 더해 주세요(적지 않아도 초안은 완성됩니다).")
        if not self.options.price_date:
            found.append("가격·날짜·수치는 본문에 넣지 않았습니다 — 필요하면 공식 자료에서 확인한 값만 직접 적고, 올리는 날 한 번 더 맞는지 살펴 주세요.")
        if not self.options.urls:
            found.append("참고 자료를 입력하지 않았습니다 — 사실 관계는 공식·공개 자료로 확인한 뒤 주소를 글 끝에 적어 두면 좋습니다(앱은 자료를 자동으로 찾거나 열지 않습니다).")
        if self.sponsor_slot:
            found.append("협찬·광고·제휴로 제품이나 서비스를 받았거나 대가를 받았다면 그 사실을 글 앞부분에 직접 밝혀 주세요 — 이 초안에는 협찬 문구를 넣지 않았고 표시 문구를 적을 자리만 알려 드립니다.")
        if self.sensitive:
            found.append(f"{bb.SENSITIVE_KO[self.sensitive]}처럼 개인 상황에 따라 판단이 달라지는 주제라 일반 정보만 다뤘습니다 — 주의사항에 전문가·공식 기관 확인 문단을 넣었으니 내용을 한 번 더 살펴 주세요.")
        if not category and not any("카테고리" in text for text in self.plan.checks):
            found.append("추천 카테고리를 정하지 못했습니다 — 블로그에서 직접 골라 주세요.")
        if self.dropped:
            found.append(f"제외할 내용이나 금지 표현 때문에 문장 {self.dropped}개를 쓰지 못했습니다 — 본문이 짧거나 어색하면 직접 보태 주세요.")
        if self.renamed:
            found.append(f"제외할 내용 때문에 소제목 {self.renamed}개를 키워드로 대신했습니다 — 직접 소제목을 달아 주세요.")
        if block_count < lib.MIN_SECTIONS:
            found.append(f"소제목이 {block_count}개뿐입니다 — 제외할 내용 때문에 단계가 빠졌습니다. 직접 소제목을 더해 주세요.")
        if self.profile is not None and not self.profile.subheading_min <= block_count <= self.profile.subheading_max:
            found.append(f"소제목이 {block_count}개입니다 — 이 블로그 프로필의 소제목 수({self.profile.subheading_min}~{self.profile.subheading_max}개)와 다릅니다.")
        if self.plan.source_of("length") in (dp.LAYER_USER, dp.LAYER_PROFILE):
            low, high = self.plan.length
            if chars < low:
                found.append(f"본문은 {chars:,}자로 원하시는 글 길이({dp.length_korean(self.plan.length)})보다 짧은 기본 글입니다 — 직접 내용을 더해 주세요(앱은 길이를 채우려고 없는 내용을 지어내지 않습니다).")
            elif high is not None and chars > high:
                found.append(f"본문은 {chars:,}자로 원하시는 글 길이({dp.length_korean(self.plan.length)})보다 깁니다 — 덜어 내고 싶은 부분을 직접 골라 주세요.")
        return tuple(dict.fromkeys([*found, *(text for text in self.plan.checks if not text.startswith(PLAN_GENERIC_CHECKS))]))


def _check_channel(channel, blog):
    """채널 프로필(속성만 읽는다)의 모양을 확인한다 — 없으면 None. 글칸은 글, 목록 칸은 글의 목록이어야 하고 채널 구분이 대상 블로그와 같아야 한다."""
    if channel is None:
        return None
    for name in CHANNEL_TEXT:
        if not isinstance(getattr(channel, name, ""), str):
            raise _invalid("채널 프로필", f"{name} 이 글이 아니다")
    for name in CHANNEL_LISTS:
        value = getattr(channel, name, ())
        if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
            raise _invalid("채널 프로필", f"{name} 이 글의 목록이 아니다")
    if getattr(channel, "key", blog) != blog:
        raise _invalid("채널 프로필", f"프로필({channel.key})과 대상 블로그({blog})가 다르다")
    return channel


def _refuse_key_shapes(candidate, channel, options):
    """후보·채널 프로필·선택 입력의 글(그대로 본문·제목·태그에 되풀이된다)에 키 모양이 있으면 만들지 않는다 — `security.mask` 가 가리는 모양과 `security.shape` 가 찾는 모양(구글 계열 접두사·깃허브 세분화 접두사·32자 16진 해시 같은 긴 영숫자 덩어리)을 모두 본다.
    선택 입력의 주소 칸은 긴 글자가 든 정상 주소가 많아 영숫자 덩어리 규칙은 쓰지 않고 키 접두사만 본다(`URL_KEY_SHAPES` — 주소 모양 자체는 `DraftOptions` 가 따로 거른다). 오류 문구는 어느 칸인지만 적고 입력한 글을 되풀이하지 않는다."""
    from ..security.mask import mask                              # 늦게 가져온다(보안 패키지는 가져올 때 vendor/ 를 먼저 올린다)
    from ..security.shape import looks_secret as shaped_like_a_key
    named = [("후보의 핵심 키워드", candidate.keyword), ("후보의 주제", candidate.topic), *(("후보의 보조 키워드", text) for text in candidate.sub_keywords),
             ("채널 프로필의 대상 독자", getattr(channel, "audience", "")), *(("채널 프로필의 카테고리", text) for text in getattr(channel, "categories", ()) or ())]
    for name in FREE_OPTION_TEXTS:
        value = getattr(options, name, "")
        named += [(LABELS[name], text) for text in ((value,) if isinstance(value, str) else tuple(value))]
    for what, text in named:
        if text and (mask(text) != text or shaped_like_a_key(text)):
            raise _invalid(what, "키처럼 보이는 글이 들어 있어 본문을 만들지 않았다(값은 적지 않는다)")
    for text in getattr(options, "urls", ()) or ():
        if mask(text) != text or URL_KEY_SHAPES.search(text):
            raise _invalid(LABELS["urls"], "키처럼 보이는 글이 들어 있어 본문을 만들지 않았다(값은 적지 않는다)")


def _tidy_candidate(candidate):
    """후보의 키워드·주제·보조 키워드에서 마크다운 표시와 HTML 엔티티를 걷어 낸 후보(걷어 낼 것이 없으면 같은 후보) — 그 글이 제목·소제목·문단에 그대로 되풀이되기 때문이다.
    후보가 아닌 값은 그대로 두어 `build_plan` 이 같은 오류로 거절하게 한다."""
    if not (dataclasses.is_dataclass(candidate) and not isinstance(candidate, type) and all(hasattr(candidate, name) for name in ("keyword", "topic", "sub_keywords"))):
        return candidate
    keyword, topic = bl.plain_text(candidate.keyword), bl.plain_text(candidate.topic)
    subs = tuple(bl.plain_text(text) for text in candidate.sub_keywords)
    if (keyword, topic, subs) == (candidate.keyword, candidate.topic, tuple(candidate.sub_keywords)):
        return candidate
    return dataclasses.replace(candidate, keyword=keyword, topic=topic, sub_keywords=tuple(text for text in subs if text))


def _refuse_stopped(safety):
    """주제 엔진이 '자동 초안 중지' 로 판정한 후보는 본문을 만들지 않는다 — 입력한 글을 되풀이하지 않는 쉬운 오류(`CONTENT_INVALID`)로 거절한다."""
    if safety is not None and getattr(safety, "stop", False):
        raise _invalid(STOP_ITEM, "안전 판정이 자동 초안 중지인 후보라 본문 초안을 만들지 않았다(입력한 글은 적지 않는다)")


def build_body(candidate, profile=None, options=None, *, today, blog=None, post_type=None, channel=None, safety=None):
    """후보 하나·블로그 프로필(없으면 None)·채널 프로필(없으면 None)·(선택) 사용자 입력·(선택) 안전 판정으로 규칙 기반 초안 한 개를 만든다 — 순수 함수(파일·네트워크·시계·난수 없음).
    사용자 입력이 비어 있어도 초안은 만들어지고, 입력이 있으면 그것이 프로필·기본값보다 먼저 적용된다. 틀린 값은 `build_plan` 과 같은 오류(`CONTENT_INVALID`·`DRAFT_OPTION_INVALID`).
    `safety` 는 주제 엔진의 안전 판정 결과(`topics.safety.check_text` — 속성 `stop`·`stage`·`relationship` 만 읽는다): 자동 초안 중지면 만들지 않고, 근거 확인 필요 단계·협찬 낱말 추정이면 확인 권장 맨 위에 경고를 둔다.
    서비스(`service.draft_body.make_body`)가 늘 이 판정을 계산해서 준다 — 주지 않으면 이 모듈의 낱말 목록만으로 만든다."""
    _refuse_stopped(safety)
    original = candidate
    candidate = _tidy_candidate(candidate)
    plan = dp.build_plan(candidate, profile, options, today=today, blog=blog, post_type=post_type)
    options = options if options is not None else DraftOptions()
    channel = _check_channel(channel, plan.blog)
    _refuse_key_shapes(original, channel, options)
    if candidate is not original:
        _refuse_key_shapes(candidate, channel, options)                                              # 걷어 낸 뒤에 이어 붙어 생긴 모양도 본다
    writer = _Writer(candidate, profile, channel, options, plan, safety)
    parts = writer.parts()
    block_list = [part.block() for part in parts]
    body_text = render_body(block_list)
    chars, spaced = count_chars(body_text)
    sections = [block for block in block_list if block.kind in (SECTION, EXPERIENCE)]
    aux = writer.aux_keywords()
    tags = writer.tags(aux)
    category = writer.category()
    selected = writer.selected_title()
    summary = writer.summary()
    checks = writer.checks(category, len(sections), chars)
    plain_text = selected + NL + NL + body_text
    used = tuple(name for name in USER_ITEMS if getattr(options, name))
    body = DraftBody(plan.blog, plan.keyword, plan.topic, plan.post_type, writer.style, writer.domain, writer.audience, plan.titles, selected, tuple(block_list), (plan.keyword,), aux, tags,
                     category, summary, checks, selected, body_text, plain_text, " ".join("#" + tag for tag in tags), chars, spaced, used, writer.sponsor_slot, writer.sensitive,
                     writer.dropped, plan.replaced)
    _final_guard(body)
    return body


def _final_guard(body):
    """마지막 관문 — 틀로 만든 글 전체를 한 번 더 `find_violations` 로 검사하고, 비밀처럼 보이는 모양이 본문에 있으면 멈춘다(걸리면 내보내지 않는다 — fail closed)."""
    if claim_check.find_violations(list(body.generated_texts())):
        raise _invalid("본문", "틀로 만든 글에서 지어낸 것으로 보이는 말이 나와 만들지 않았다")
    from ..security.mask import mask
    if mask(body.plain_text) != body.plain_text:
        raise _invalid("본문", "비밀처럼 보이는 글이 본문에 들어 있어 만들지 않았다(값은 적지 않는다)")


__all__ = ["BodyBlock", "DraftBody", "KINDS", "LOW_CHARS", "HIGH_SPACED", "build_body", "count_chars", "render_body"]
