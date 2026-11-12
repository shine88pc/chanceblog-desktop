"""저장한 초안의 기록 모양 — 초안 작성 화면에서 `저장` 을 누른 글 한 편 = 글 보관함(`chanceblog.db`)의 `drafts` 표 한 행이고, 그 행의 `text` 칸에 아래 기록이 JSON 한 덩어리로 들어간다
(docs/ARCHITECTURE.md `content/saved_draft.py`, 결정 D-360). 표를 새로 만들지 않으므로 파일 구조(판 번호)는 그대로이고, 글 보관함 백업(`Store.backup`)은 파일 통째라 저장한 초안도 자동으로 들어간다.

순수 파이썬이다 — 파일·시계·무작위·네트워크를 쓰지 않는다(시각은 부르는 쪽이 `ctx.stamp()` 로 준다). 같은 입력은 늘 같은 글자다.

지키는 것:
  ① **글자 그대로 돌아온다** — 제목·본문 같은 글칸은 정규화·줄바꿈 바꾸기·공백 다듬기를 하지 않는다. 기록은 `ensure_ascii=True` 인 JSON 이라 줄 끝(CRLF·LF·CR)·이모지·결합 글자·널 글자·짝 없는 서로게이트까지 파이썬 글(`str`)이 글자 하나도 바뀌지 않고
     돌아오고, 보관함에는 ASCII 만 들어간다(SQLite 글 칸이 받지 못하는 글자가 없다). 읽을 때는 모든 칸의 종류·길이·글 모양을 엄격하게 본다 — 사람이 고쳤거나 깨졌으면 `DRAFT_CORRUPT`(그 초안 하나만 막힌다).
  ② **한도가 있다**(`MAX_*`) — 제목 1,000자·본문 150,000자·키워드·태그 50개씩·확인 권장 50줄 …. 넘으면 `DRAFT_LIMIT` 이고 앱이 자르거나 고쳐 받지 않는다.
  ③ **비밀을 담지 않는다** — 이 모듈은 검사를 하지 않는다(검사는 저장 직전 `service/draft_store.py` 가 `security/scan.py` 로 한다 — 이 모듈은 찾은 자리로 안내 글을 만드는 `secret_advice` 만 가진다). 기록에는 AI·네트워크·키·계정 정보를 넣을 칸이 없고, 글이 아닌 칸(분야·생성기·글 유형·블로그·후보 번호)은 정해진 모양만 받는다.
  ④ 번호(`draft_id`)는 `dd-` + 저장 시각·후보·블로그·제목·본문의 지문 20자(16진수)다 — 시계와 무작위를 새로 쓰지 않는다. 같은 글을 같은 초에 두 번 저장하면 같은 번호(같은 글)가 된다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from ..errors import AppError
from .draft_options import KEYS as OPTION_KEYS
from .draft_options import LABELS as OPTION_LABELS
from .profiles import POST_TYPES

SCHEMA = 1
KIND = "desktop_draft"                         # 이 기록의 종류 표지 — `drafts` 표에 다른 글이 있어도(자동 저장 초안 등) 섞이지 않는다
ID_PREFIX = "dd-"
GENERATOR = "rule-v1"                          # 규칙 기반 초안 생성기(AI 없음)의 판 — 생성 규칙(`content/draft_body.py`)을 바꾸면 올린다. 기록에 적을 뿐 동작은 바꾸지 않는다
SHORT_ID = 11                                  # 화면·오류에 보이는 번호의 길이(`dd-` + 16진수 8자)
MAX_TITLE_CHARS = 1_000
MAX_BODY_CHARS = 150_000                       # 이모지 하나가 이스케이프하면 12글자(글자 둘을 짝으로 쓴다)라, 모두 이모지여도 보관함 칸 한도(200만 자) 가까이에 들어가는 크기
MAX_BASE_BODY_CHARS = 30_000                   # 처음 만든 초안의 본문(생성기는 3,000자 안팎을 만든다)
MAX_SHORT_CHARS = 2_000                        # 카테고리·요약·주제·선택 입력 한 칸
MAX_ITEM_CHARS = 200                           # 키워드·태그·바꾼 글 유형 한 개
MAX_LIST_ITEMS = 50
MAX_CHECKS = 50
MAX_CHECK_CHARS = 1_000
MAX_SAVED = 300                                # 저장한 초안의 가장 많은 수 — 넘으면 새 초안은 저장하지 않는다(오래된 초안을 앱이 스스로 지우지 않는다)
MAX_TEXT_CHARS = 2_000_000                     # `Store.save_draft` 의 칸 한도(`MAX_DRAFT_CHARS`와 같다 — 시험이 견준다). 이스케이프한 기록이 이 크기를 넘으면 `DRAFT_LIMIT`
BLOGS = ("naver_a", "naver_b")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_CANDIDATE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_DRAFT_ID = re.compile(r"dd-[0-9a-f]{20}")
_NAME = re.compile(r"[A-Za-z0-9._-]{0,40}")                       # 분야·생성기처럼 정해진 이름만 받는 칸(글이 아니다)
_ID_SEPARATOR = chr(0x1f)
_SURROGATE_PAIR = re.compile("[" + chr(0xD800) + "-" + chr(0xDBFF) + "][" + chr(0xDC00) + "-" + chr(0xDFFF) + "]")      # 앞 반쪽 바로 뒤에 뒤 반쪽 — JSON 이 읽을 때 한 글자(이모지 같은 글자)로 합쳐 버려 글자 그대로 돌아오지 못하는 모양

_KEYS = ("schema", "kind", "draft_id", "revision", "created_at", "updated_at", "generator", "candidate_id", "topic", "blog", "post_type_choice", "post_type", "title", "body",
         "core_keywords", "sub_keywords", "tags", "category", "summary", "options", "base")
_BASE_KEYS = ("title", "titles", "body", "checks", "domain", "replaced")
LABELS = {"title": "제목", "body": "본문", "core_keywords": "핵심 키워드", "sub_keywords": "보조 키워드", "tags": "태그", "category": "카테고리", "summary": "요약", "topic": "후보 주제",
          "candidate_id": "후보 번호", "blog": "블로그", "post_type": "글 유형", "options": "선택 입력", "base": "만든 초안", "revision": "저장 횟수", "created_at": "만든 시각", "updated_at": "고친 시각",
          "generator": "생성기", "domain": "분야", "draft_id": "번호"}


MADE_DRAFT_HEAD = LABELS["base"]               # '만든 초안' — 처음 만든 글(`base`)의 칸 이름이 이 말로 시작한다(예: `만든 초안 본문`)
MADE_DRAFT_ADVICE = ("만든 초안(처음 만든 글)에서 찾았어요 — 이 글은 화면에서 고칠 수 없는 칸이라, 후보·블로그 프로필(대상 독자·카테고리 같은 칸)과 선택 입력에서 키나 토큰처럼 보이는 글을 지운 뒤 ‘다시 만들기’ 를 해 주세요. "
                     "다시 만들면 지금 고친 글이 사라지니 먼저 복사해 두세요 — 앱은 자동으로 지우거나 바꾸지 않아요")


def is_made_draft_place(where):
    """발견한 자리(칸 이름)가 '만든 초안' 쪽인가."""
    return isinstance(where, str) and where.startswith(MADE_DRAFT_HEAD)


def secret_advice(findings):
    """키·토큰 모양을 찾았을 때의 안내 — 위치(칸·줄)와 종류와 고치는 법뿐이고 찾은 글은 없다. 고친 글칸에서 찾은 것은 그 줄을 지우라고 하고, '만든 초안' 칸에서 찾은 것(화면에서 못 고치는 칸)은 후보·블로그 프로필·선택 입력을
    고쳐 다시 만들라는 전용 문구를 붙인다(다시 만들면 고친 글이 사라지니 먼저 복사하라는 말과 함께). 둘 다 있으면 둘 다 말한다."""
    from ..security import scan                                    # 늦게 가져온다(저장소 안 다른 content 모듈과 같은 방식)
    items = tuple(findings)
    edited = tuple(item for item in items if not is_made_draft_place(item.where))
    made = tuple(item for item in items if is_made_draft_place(item.where))
    parts = []
    if edited:
        parts.append(scan.summarize(edited, "저장"))                # 위치·종류 줄과 고치는 법(마지막 줄)
    if made:
        parts.append("\n".join(scan.summarize(made, "저장").split("\n")[:-1] + [MADE_DRAFT_ADVICE]))      # 위치·종류 줄 + 전용 문구(요약의 마지막 줄 '고치는 법' 은 이 칸에 맞지 않아 뺀다)
    return "\n".join(parts)


def short_id(draft_id):
    """화면·오류에 보일 번호 — 앞 11자(`dd-` + 8자). 긴 번호를 그대로 싣지 않는다."""
    text = str(draft_id)
    return text if len(text) <= SHORT_ID else text[:SHORT_ID]


def make_draft_id(stamp, candidate_id, blog, title, body):
    """새 초안의 번호 — 저장 시각·후보·블로그·제목·본문의 지문. 시계·무작위를 쓰지 않는다(같은 글을 같은 초에 다시 저장하면 같은 번호 = 같은 글)."""
    raw = _ID_SEPARATOR.join((str(stamp), str(candidate_id), str(blog), str(title), str(body))).encode("utf-8", "surrogatepass")
    return ID_PREFIX + hashlib.sha256(raw).hexdigest()[:20]


def is_draft_id(value):
    return isinstance(value, str) and _DRAFT_ID.fullmatch(value) is not None


def _limit(reason):
    return AppError("DRAFT_LIMIT", {"이유": reason}, detail=reason)


def _bad(item, detail=""):
    return AppError("CONTENT_INVALID", {"항목": f"초안 {item}"}, detail=detail or item)


def _text(value, name, high, *, label=None, each=False):
    """글칸 하나 — 글(`str`)이어야 하고 `high` 자까지다. 글자는 하나도 바꾸지 않는다. `each` 는 목록 칸의 항목 하나일 때(문구가 '칸의 항목 하나가' 가 된다 — 조사는 칸 이름 뒤에 '칸이' 로 붙여 받침을 가리지 않는다, D-371)."""
    item = label or LABELS.get(name, name)
    if not isinstance(value, str):
        raise _bad(item, "글이어야 한다")
    if len(value) > high:
        raise _limit(f"{item} 칸의 항목 하나가 {high:,}자를 넘어요" if each else f"{item} 칸이 {high:,}자를 넘어요")
    if _SURROGATE_PAIR.search(value):
        raise _bad(item, "서로게이트 두 글자가 짝으로 이어져 있다(보통 글자가 아니라 읽을 때 한 글자로 합쳐진다)")
    return value


def _texts(value, name, count, high, *, label=None):
    """글 목록 칸 — 글들의 목록이고 `count` 개까지, 한 개가 `high` 자까지."""
    item = label or LABELS.get(name, name)
    if not isinstance(value, (list, tuple)):
        raise _bad(item, "목록이어야 한다")
    if len(value) > count:
        raise _limit(f"{item} 칸의 항목이 {count}개를 넘어요")
    return tuple(_text(entry, name, high, label=item, each=True) for entry in value)


def _named(value, name, *, nonempty=False):
    """글이 아니라 정해진 이름만 받는 칸(분야·생성기)."""
    item = LABELS.get(name, name)
    if not isinstance(value, str) or _NAME.fullmatch(value) is None or (nonempty and not value):
        raise _bad(item, "영문·숫자와 . _ - 만 쓴 40자까지의 이름이어야 한다")
    return value


def _post_type(value, *, choice):
    """글 유형 칸 — `choice`(화면에서 고른 값)면 None(후보 기준)이거나 알려진 글 유형, 아니면 알려진 글 유형이거나 빈 글. 그 밖의 글은 받지 않는다."""
    if choice and value is None:
        return None
    if isinstance(value, str) and (value in POST_TYPES or (not choice and value == "")):
        return value
    raise _bad(LABELS["post_type"], "알려진 글 유형이어야 한다")


def _stamp(value, name):
    if not isinstance(value, str) or _STAMP.fullmatch(value) is None:
        raise _bad(LABELS[name], "시각 모양이 아니다")
    return value


def _count(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 1_000_000:
        raise _bad(LABELS[name], "1 이상의 정수여야 한다")
    return value


@dataclass(frozen=True)
class BaseDraft:
    """처음 만들었을 때의 초안 — 고친 정도·제목 후보·확인 권장을 다시 열었을 때도 계산할 수 있게 함께 둔다(`replaced` 는 후기 형식을 바꿨을 때의 (이전, 이후) 한 쌍 또는 None)."""
    title: str
    titles: tuple
    body: str
    checks: tuple
    domain: str
    replaced: object

    def to_dict(self):
        return {"title": self.title, "titles": list(self.titles), "body": self.body, "checks": list(self.checks), "domain": self.domain,
                "replaced": None if self.replaced is None else list(self.replaced)}

    @classmethod
    def build(cls, title, titles, body, checks, domain, replaced):
        label = LABELS["base"]
        pair = None
        if replaced is not None:
            if not isinstance(replaced, (list, tuple)) or len(replaced) != 2:
                raise _bad(label, "바꾼 형식은 (이전, 이후) 한 쌍이어야 한다")
            pair = (_text(replaced[0], "base", MAX_ITEM_CHARS, label=label), _text(replaced[1], "base", MAX_ITEM_CHARS, label=label))
        return cls(_text(title, "base", MAX_TITLE_CHARS, label=label), _texts(titles, "base", MAX_LIST_ITEMS, MAX_TITLE_CHARS, label=label), _text(body, "base", MAX_BASE_BODY_CHARS, label=label),
                   _texts(checks, "base", MAX_CHECKS, MAX_CHECK_CHARS, label=label), _named(domain, "domain"), pair)


@dataclass(frozen=True)
class SavedDraft:
    """저장한 초안 한 편 — 고른 제목·편집한 본문·키워드·태그·카테고리·요약·원본 후보·블로그·생성기 판·시각(+ 다시 열 때 쓰는 선택 입력과 처음 만든 초안). 글칸은 글자 그대로다."""
    draft_id: str
    revision: int                    # 저장한 횟수 — 처음 저장이 1
    created_at: str
    updated_at: str
    generator: str
    candidate_id: str                # 원본 후보(주제 엔진 보관함의 번호) — ''(없음)일 수 있다
    topic: str                       # 후보 주제(목록에 보이는 이름 — 후보가 지워져도 남는다)
    blog: str                        # 채널 프로필 슬롯(`naver_a`·`naver_b`)
    post_type_choice: object         # 화면에서 고른 글 유형(None = 후보 기준)
    post_type: str                   # 만든 글 유형
    title: str
    body: str
    core_keywords: tuple
    sub_keywords: tuple
    tags: tuple
    category: str
    summary: str
    options: tuple                   # ((칸 이름, 글), …) — 만들 때 반영한 선택 입력(`OPTION_KEYS` 순서)
    base: object                     # BaseDraft 또는 None

    def options_dict(self):
        return dict(self.options)

    def text_fields(self):
        """저장 직전 비밀 모양 검사가 훑는 글칸들 — `{칸 이름: 글}`(목록 칸은 줄바꿈으로 이은 글 — 줄 번호가 항목 번호가 된다). 만든 초안(`base`)은 따로 본다(`base_fields`)."""
        found = {LABELS["title"]: self.title, LABELS["body"]: self.body, LABELS["core_keywords"]: "\n".join(self.core_keywords), LABELS["sub_keywords"]: "\n".join(self.sub_keywords),
                 LABELS["tags"]: "\n".join(self.tags), LABELS["category"]: self.category, LABELS["summary"]: self.summary, LABELS["topic"]: self.topic, LABELS["candidate_id"]: self.candidate_id}
        for name, value in self.options:
            found[f"{LABELS['options']}({OPTION_LABELS.get(name, name)})"] = value
        return found

    def base_fields(self):
        if self.base is None:
            return {}
        head = LABELS["base"]
        found = {f"{head} 제목": self.base.title, f"{head} 제목 후보": "\n".join(self.base.titles), f"{head} 본문": self.base.body, f"{head} 확인 권장": "\n".join(self.base.checks),
                 f"{head} 분야": self.base.domain}
        if self.base.replaced is not None:
            found[f"{head} 바꾼 형식"] = "\n".join(self.base.replaced)
        return found

    def to_dict(self):
        return {"schema": SCHEMA, "kind": KIND, "draft_id": self.draft_id, "revision": self.revision, "created_at": self.created_at, "updated_at": self.updated_at, "generator": self.generator,
                "candidate_id": self.candidate_id, "topic": self.topic, "blog": self.blog, "post_type_choice": self.post_type_choice, "post_type": self.post_type, "title": self.title,
                "body": self.body, "core_keywords": list(self.core_keywords), "sub_keywords": list(self.sub_keywords), "tags": list(self.tags), "category": self.category,
                "summary": self.summary, "options": {name: value for name, value in self.options}, "base": None if self.base is None else self.base.to_dict()}

    def to_text(self):
        """보관함 글 칸에 넣을 글 — 정렬한 JSON(ASCII 만). 모든 글칸이 글자 그대로 되돌아온다. 보관함 칸의 크기를 넘으면 `DRAFT_LIMIT`."""
        text = json.dumps(self.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        if len(text) > MAX_TEXT_CHARS:
            raise _limit("글이 너무 길어요(이모지가 많으면 한도가 더 줄어요)")
        return text

    @classmethod
    def build(cls, *, draft_id, revision, created_at, updated_at, title, body, core_keywords=(), sub_keywords=(), tags=(), category="", summary="", candidate_id="", topic="", blog="",
              post_type_choice=None, post_type="", options=None, base=None, generator=GENERATOR):
        """칸마다 종류·길이를 보고 기록을 만든다 — 글칸은 글자 하나도 바꾸지 않는다. 틀리면 `CONTENT_INVALID`(종류)·`DRAFT_LIMIT`(크기)."""
        if not isinstance(draft_id, str) or _DRAFT_ID.fullmatch(draft_id) is None:
            raise _bad(LABELS["draft_id"], "dd- 로 시작하는 번호 모양이 아니다")
        if not isinstance(candidate_id, str) or (candidate_id and _CANDIDATE_ID.fullmatch(candidate_id) is None):
            raise _bad(LABELS["candidate_id"], "영문·숫자·밑줄·붙임표 1자에서 64자이거나 비어 있어야 한다")
        if not isinstance(blog, str) or blog not in ("", *BLOGS):
            raise _bad(LABELS["blog"], "naver_a·naver_b 또는 비어 있어야 한다")
        if options is None:
            options = {}
        if not isinstance(options, dict) or not set(options) <= set(OPTION_KEYS):
            raise _bad(LABELS["options"], "알려진 입력 칸만 있어야 한다")
        if base is not None and not isinstance(base, BaseDraft):
            raise _bad(LABELS["base"], "만든 초안 모양이 아니다")
        pairs = tuple((name, _text(options[name], "options", MAX_SHORT_CHARS)) for name in OPTION_KEYS if name in options)
        return cls(draft_id, _count(revision, "revision"), _stamp(created_at, "created_at"), _stamp(updated_at, "updated_at"), _named(generator, "generator", nonempty=True),
                   candidate_id, _text(topic, "topic", MAX_SHORT_CHARS), blog, _post_type(post_type_choice, choice=True), _post_type(post_type, choice=False),
                   _text(title, "title", MAX_TITLE_CHARS), _text(body, "body", MAX_BODY_CHARS), _texts(core_keywords, "core_keywords", MAX_LIST_ITEMS, MAX_ITEM_CHARS),
                   _texts(sub_keywords, "sub_keywords", MAX_LIST_ITEMS, MAX_ITEM_CHARS), _texts(tags, "tags", MAX_LIST_ITEMS, MAX_ITEM_CHARS), _text(category, "category", MAX_SHORT_CHARS),
                   _text(summary, "summary", MAX_SHORT_CHARS), pairs, base)

    @classmethod
    def from_text(cls, text, draft_id):
        """보관함에서 읽은 글 → 기록. 이 프로그램이 만든 모양이 아니면 `DRAFT_CORRUPT`(번호만 알린다 — 글은 알리지 않는다), 더 새로운 판이 만든 것이면 `STORE_VERSION_UNSUPPORTED`."""
        corrupt = AppError("DRAFT_CORRUPT", {"번호": short_id(draft_id)}, detail="기록의 모양이 올바르지 않다")
        try:
            raw = json.loads(text)
        except (ValueError, TypeError, RecursionError):
            raise corrupt from None
        if not isinstance(raw, dict) or raw.get("kind") != KIND:
            raise corrupt
        schema = raw.get("schema")
        if isinstance(schema, int) and not isinstance(schema, bool) and schema > SCHEMA:
            raise AppError("STORE_VERSION_UNSUPPORTED", {"파일": f"저장한 초안 {short_id(draft_id)}"}, detail=f"초안 기록 판 {schema} > 지원 {SCHEMA}")
        if type(schema) is not int or schema != SCHEMA or set(raw) != set(_KEYS) or raw["draft_id"] != draft_id:
            raise corrupt
        try:
            base = raw["base"]
            if base is not None:
                if not isinstance(base, dict) or set(base) != set(_BASE_KEYS):
                    raise corrupt
                base = BaseDraft.build(base["title"], base["titles"], base["body"], base["checks"], base["domain"], base["replaced"])
            return cls.build(draft_id=raw["draft_id"], revision=raw["revision"], created_at=raw["created_at"], updated_at=raw["updated_at"], title=raw["title"], body=raw["body"],
                             core_keywords=raw["core_keywords"], sub_keywords=raw["sub_keywords"], tags=raw["tags"], category=raw["category"], summary=raw["summary"], candidate_id=raw["candidate_id"],
                             topic=raw["topic"], blog=raw["blog"], post_type_choice=raw["post_type_choice"], post_type=raw["post_type"], options=raw["options"], base=base, generator=raw["generator"])
        except AppError as error:
            if error is corrupt:
                raise
            raise corrupt from None
        except (TypeError, KeyError, ValueError):
            raise corrupt from None


def body_chars(text):
    """목록에 보이는 글자 수 — 공백·줄바꿈을 뺀 글자 수(화면 편집기 아래 줄의 앞 숫자와 같다)."""
    return len("".join(text.split()))


__all__ = ["BLOGS", "BaseDraft", "GENERATOR", "ID_PREFIX", "KIND", "LABELS", "MADE_DRAFT_ADVICE", "MADE_DRAFT_HEAD", "MAX_BODY_CHARS", "MAX_SAVED", "MAX_TITLE_CHARS", "OPTION_KEYS", "SCHEMA", "SavedDraft", "body_chars",
           "is_draft_id", "is_made_draft_place", "make_draft_id", "secret_advice", "short_id"]
