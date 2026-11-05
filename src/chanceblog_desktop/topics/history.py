"""발행 이력 읽기 — 5채널의 기존 글(제목·핵심 키워드·날짜·주소)을 공통 모양 `HistoryRecord` 로 **관대하게** 읽는 순수 파서(파일·네트워크·시계·난수 없음).

이 모듈은 파일을 열지 않는다 — 서비스 층(P3)이 파일을 읽어 **이미 읽은 값**(JSON 으로 해석한 목록, 글 머리말 텍스트)을 넘긴다. 못 읽은 항목은 예외로 멈추지 않고 건너뛰며 '경고'(`HistoryWarning`)로 모아 돌려준다.
읽는 모양 다섯(블로그 저장소 사본에서 확인한 실제 모양 — 시험 자료는 모양만 같은 짧은 가짜다):
  · `read_posts_json`   — GitHub Pages 의 `posts.json`(사이트를 만든 **결과** 배열: path·url·absoluteUrl·name·title·category·lang(kr·en)·date·tags… `content` 는 읽지 않는다).
                         저장소의 `posts.json` 파일 자체는 Jekyll 틀(Liquid 표기)이라 JSON 이 아니다 — 만든 결과나 배포된 `/posts.json` 을 읽어 넘긴다.
  · `read_front_matter` — `_posts/**/*.md` 한 편의 머리말(`---` 사이: title·tags·lang·date). 날짜는 머리말에 없으면 파일 이름 앞의 `YYYY-MM-DD` 에서 읽는다.
  · `read_history_entries` — Blogger 영문·한글 이력(`blogger_history.json`·`blogger_ko_history.json`)과 네이버 발행 이력(`naver_history.json`)처럼 date·topic·title·labels·url·post_id 를 가진 항목 목록.
  · `read_titles`      — GitHub Pages 생성기의 `history.json`(제목 글자와 kr_title·en_title 을 가진 항목이 섞인 목록).
  · `read_naver_items` — 네이버 A·B 이력의 **틀**: 이력은 데스크톱 보관함에서 오므로(P3) 이 함수는 보관함을 읽지 않고 '제목·키워드·날짜·주소·글 번호' 를 가진 항목만 받는다.
'모름 ≠ 0': 날짜·주소·언어·글 번호를 모르면 지어내지 않고 `None` 이다(제목이 없으면 그 항목을 건너뛴다). 같은 입력은 늘 같은 결과다.
**같은 글은 어느 길로 읽어도 같은 글 번호(`ref`)를 낸다**(P2b, 독립 검증 M5): 글 번호는 글 파일 이름에서 `.md` 를 뗀 모양이다(`read_posts_json` 의 `name` 과 `read_front_matter` 의 파일 이름이 같은 글에 같은 번호).
머리말의 제목이 `>`·`|`(여러 줄 값 표시)·`null`·`~`·`true`·`false` 처럼 따옴표 없는 YAML 표시이면 제목으로 읽지 않고 건너뛴다. 머리말 날짜를 읽지 못하면 경고를 남긴다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

from ..content.profiles import clean_line
from .channels import CHANNELS, LANGUAGES
from .model import _REF

ORIGIN_POSTS, ORIGIN_FRONT_MATTER, ORIGIN_ENTRIES, ORIGIN_TITLES, ORIGIN_NAVER = "posts_json", "front_matter", "history_entries", "history_titles", "naver_items"
ORIGINS = (ORIGIN_POSTS, ORIGIN_FRONT_MATTER, ORIGIN_ENTRIES, ORIGIN_TITLES, ORIGIN_NAVER)
NAVER_CHANNELS = ("naver_a", "naver_b")

MAX_ITEMS = 20_000                    # 한 번에 읽을 항목 수의 상한(이보다 많으면 앞에서부터 읽고 경고)
MAX_TITLE = 300
MAX_KEYWORDS = 20
MAX_KEYWORD = 60
MAX_URL = 500
MAX_TOPIC = 300
MIN_YEAR = 2000
_DAY = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_LANG = {"kr": "ko", "ko": "ko", "en": "en"}                       # 사이트가 쓰는 `kr` 도 한국어(`ko`)로 읽는다


@dataclass(frozen=True, kw_only=True)
class HistoryRecord:
    channel: str                                    # 채널 코드 키
    title: str                                      # 글 제목(한 줄, 길면 앞 300자)
    keywords: tuple = ()                            # 핵심 키워드(태그·라벨) — 모르면 빈 튜플
    date: str | None = None                         # 발행(또는 생성) 날짜 YYYY-MM-DD — 모르면 None
    url: str | None = None                          # 글 주소(http·https 또는 사이트 안 `/` 로 시작하는 주소) — 없으면 None
    language: str | None = None                     # ko·en — 모르면 None
    topic: str | None = None                        # 글을 만들 때 쓴 원천 주제(있으면)
    ref: str | None = None                          # 글 번호(영문·숫자로 시작하는 120자 이하 — 후보의 `similar_post_ids` 에 쓸 수 있다) — 없으면 None
    origin: str = ORIGIN_NAVER                      # 어느 모양에서 읽었나(`ORIGINS`)

    def __post_init__(self):
        if not isinstance(self.channel, str) or self.channel not in CHANNELS:
            raise ValueError("채널은 코드의 채널 이름이어야 한다: " + ", ".join(CHANNELS))
        if not isinstance(self.title, str) or not self.title or self.title != clean_line(self.title) or len(self.title) > MAX_TITLE:
            raise ValueError(f"제목은 비어 있지 않은 한 줄이고 {MAX_TITLE}자 이하여야 한다")
        if not isinstance(self.keywords, tuple) or not all(isinstance(word, str) and word and len(word) <= MAX_KEYWORD for word in self.keywords) or len(self.keywords) > MAX_KEYWORDS:
            raise ValueError(f"키워드는 {MAX_KEYWORD}자 이하의 글 {MAX_KEYWORDS}개까지의 튜플이어야 한다")
        if self.date is not None and valid_day(self.date) is None:
            raise ValueError("날짜는 2026-11-05 같은 모양이거나 None 이어야 한다")
        if self.url is not None and _clean_url(self.url) != self.url:
            raise ValueError("주소는 http·https 주소나 `/` 로 시작하는 사이트 안 주소이거나 None 이어야 한다")
        if self.language is not None and self.language not in LANGUAGES:
            raise ValueError("언어는 ko·en 이거나 None 이어야 한다")
        if self.topic is not None and (not isinstance(self.topic, str) or not self.topic or self.topic != clean_line(self.topic) or len(self.topic) > MAX_TOPIC):
            raise ValueError("원천 주제는 비어 있지 않은 한 줄이거나 None 이어야 한다")
        if self.ref is not None and (not isinstance(self.ref, str) or not _REF.fullmatch(self.ref)):
            raise ValueError("글 번호는 영문·숫자로 시작하는 120자 이하이거나 None 이어야 한다")
        if not isinstance(self.origin, str) or self.origin not in ORIGINS:
            raise ValueError("읽은 곳은 다음 중 하나여야 한다: " + ", ".join(ORIGINS))

    def to_dict(self):
        return {"channel": self.channel, "title": self.title, "keywords": list(self.keywords), "date": self.date, "url": self.url, "language": self.language, "topic": self.topic,
                "ref": self.ref, "origin": self.origin}


class HistoryWarning(NamedTuple):
    origin: str                                     # `ORIGINS` 중 하나
    where: str                                      # 어느 항목인지('항목 3'·'머리말'·'목록 전체')
    reason: str                                     # 쉬운 한국어 이유
    skipped: bool                                   # True 면 그 항목을 건너뛰었고, False 면 일부 칸만 비우거나 줄이고 나머지는 읽었다

    def message(self):
        return f"{self.where}: {self.reason}" + (" — 건너뜁니다" if self.skipped else " — 나머지는 그대로 읽습니다")


class HistoryResult(NamedTuple):
    records: tuple                                  # 읽은 `HistoryRecord` — 입력 순서대로
    warnings: tuple                                 # `HistoryWarning` — 못 읽은 항목과 비워 둔 칸


class _Skip(Exception):
    """항목 하나를 읽을 수 없다는 내부 신호 — 경고로 바뀌고 밖으로 새지 않는다."""


# ---- 칸 하나씩 읽기(관대하게: 못 읽으면 None 이고 경고만 남긴다) -----------------------------------------------------------------------------
def valid_day(text):
    """`YYYY-MM-DD` 이고 달력에 있으며 2000년 이후이면 그 글, 아니면 None."""
    match = _DAY.fullmatch(text) if isinstance(text, str) else None
    if not match or int(match.group(1)) < MIN_YEAR:
        return None
    try:
        date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return text


def _clean_url(value):
    """http·https 주소이거나 `/`(두 개가 아닌)로 시작하는 사이트 안 주소이면 그대로, 아니면 None. 공백·제어 문자가 있거나 길면 None."""
    if not isinstance(value, str) or not value or len(value) > MAX_URL or any(ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf") for ch in value):
        return None
    lowered = value.lower()
    if lowered.startswith(("https://", "http://")) and len(value.split("://", 1)[1]) > 0:
        return value
    if value.startswith("/") and not value.startswith("//"):
        return value
    return None


def _title(value, notes):
    if value is None:
        raise _Skip("제목이 없습니다")
    if not isinstance(value, str):
        raise _Skip("제목이 글이 아닙니다")
    text = clean_line(value)
    if not text:
        raise _Skip("제목이 비어 있습니다")
    if len(text) > MAX_TITLE:
        notes.append("제목이 너무 길어 앞 300자만 씁니다")
        text = text[:MAX_TITLE].rstrip()
    return text


def _day_of(value, notes):
    if value is None or value == "":
        return None
    day = valid_day(value.strip()) if isinstance(value, str) else None
    if day is None:
        notes.append("날짜를 읽지 못했습니다")
    return day


def _day_prefix(value):
    """`2026-10-30T22:10:58+09:00`·`2026-10-18 09:00:00 +0900` 처럼 날짜로 시작하는 글에서 앞 10자(날짜)를, 아니면 None."""
    return valid_day(value[:10]) if isinstance(value, str) else None


def _url_of(value, notes):
    if value is None or value == "":
        return None
    url = _clean_url(value)
    if url is None:
        notes.append("주소 모양을 알 수 없습니다")
    return url


def _keywords_of(values, notes):
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        notes.append("키워드가 목록이 아닙니다")
        return ()
    kept, seen, dropped = [], set(), False
    for item in values:
        word = clean_line(item) if isinstance(item, str) else ""
        if not word or len(word) > MAX_KEYWORD:
            dropped = True                                  # 글이 아니거나 비었거나 너무 길다
            continue
        key = unicodedata.normalize("NFKC", word).casefold()
        if key in seen:
            continue                                        # 같은 키워드가 또 나오면 한 번만(경고할 일이 아니다)
        if len(kept) >= MAX_KEYWORDS:
            dropped = True
            break
        seen.add(key)
        kept.append(word)
    if dropped:
        notes.append("키워드 일부를 건너뜁니다(글이 아니거나 비었거나 너무 길거나 개수를 넘었습니다)")
    return tuple(kept)


def _language_of(value):
    return _LANG.get(value.strip().lower()) if isinstance(value, str) else None


def _topic_of(value, notes):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        notes.append("원천 주제가 글이 아닙니다")
        return None
    text = clean_line(value)
    if not text:
        return None
    if len(text) > MAX_TOPIC:
        notes.append("원천 주제가 너무 길어 앞 300자만 씁니다")
        text = text[:MAX_TOPIC].rstrip()
    return text


def _ref_of(value, notes):
    if value is None or value == "":
        return None
    text = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not _REF.fullmatch(text):
        notes.append("글 번호 모양을 알 수 없습니다")
        return None
    return text


def _stem_of(name):
    """글 파일 이름(경로가 붙어 있어도 마지막 조각)에서 `.md` 를 뗀 글 번호 모양 — 두 길(`posts.json`·머리말)이 같은 글에 같은 번호를 내게 한다."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    return base[:-3] if base.lower().endswith(".md") else base


def _make(channel, origin, title, **values):
    return HistoryRecord(channel=channel, title=title, origin=origin, **values)


def _collect(items, origin, convert):
    """항목 목록을 하나씩 `convert(index, item, notes)` 로 읽는다 — 읽은 기록들과 경고를 모은다. 목록이 아니면 빈 결과와 경고 하나."""
    if not isinstance(items, (list, tuple)):
        return HistoryResult((), (HistoryWarning(origin, "목록 전체", "항목이 들어 있는 목록이 아니라서 읽지 않았습니다", True),))
    records, warnings = [], []
    if len(items) > MAX_ITEMS:
        warnings.append(HistoryWarning(origin, "목록 전체", f"항목이 {len(items)}개라 앞의 {MAX_ITEMS}개만 읽습니다", False))
    for index, item in enumerate(items[:MAX_ITEMS], start=1):
        notes = []
        try:
            made = convert(item, notes)
        except _Skip as skip:
            warnings.append(HistoryWarning(origin, f"항목 {index}", str(skip), True))
            continue
        except ValueError:                                  # 기록의 마지막 검사(`HistoryRecord`)가 거절한 값 — 읽는 쪽이 놓친 모양이어도 멈추지 않고 경고로 남긴다
            warnings.append(HistoryWarning(origin, f"항목 {index}", "읽은 값이 이력 기록의 규칙에 맞지 않습니다", True))
            continue
        records.extend(made)
        warnings.extend(HistoryWarning(origin, f"항목 {index}", note, False) for note in notes)
    return HistoryResult(tuple(records), tuple(warnings))


def _mapping(item):
    if not isinstance(item, dict):
        raise _Skip("항목이 칸이 있는 묶음(객체)이 아닙니다")
    return item


# ---- 읽는 모양 다섯 ----------------------------------------------------------------------------------------------------------------------
def read_posts_json(items):
    """GitHub Pages `posts.json`(사이트를 만든 결과의 배열)을 `github_pages` 채널의 기록으로 읽는다. 제목이 없는 항목은 건너뛰고 `content` 같은 큰 칸은 읽지 않는다."""
    def convert(item, notes):
        data = _mapping(item)
        title = _title(data.get("title"), notes)
        absolute, relative = _clean_url(data.get("absoluteUrl")), _clean_url(data.get("url"))
        url = absolute or relative
        if url is None and (data.get("absoluteUrl") or data.get("url")):
            notes.append("주소 모양을 알 수 없습니다")
        name = data.get("name")
        return [_make("github_pages", ORIGIN_POSTS, title, keywords=_keywords_of(data.get("tags"), notes), date=_day_of(data.get("date"), notes), url=url,
                      language=_language_of(data.get("lang")), ref=_ref_of(_stem_of(name) if isinstance(name, str) else name, []) if name else None)]

    return _collect(items, ORIGIN_POSTS, convert)


_FENCE = re.compile(r"---[ \t]*")
_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:[ \t]*(.*)")
_FILE_DAY = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})-")
_UNQUOTE = {'"': '"', "'": "'"}
_YAML_NOT_TEXT = frozenset({">", "|", ">-", "|-", ">+", "|+", "~", "null", "true", "false"})       # 따옴표 없는 머리말 값 중 글이 아니라 YAML 표시인 것(여러 줄 값·없음·참거짓)


def _unquote(raw):
    """머리말 값 한 줄의 따옴표를 벗긴다(큰따옴표 안의 `\\"`·`\\\\` 와 작은따옴표 안의 `''` 만 풀고 그 밖의 이스케이프는 그대로 둔다)."""
    text = raw.strip()
    if len(text) >= 2 and text[0] in _UNQUOTE and text[-1] == text[0]:
        inner = text[1:-1]
        if text[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner.replace("''", "'")
    return text


def _flow_list(raw):
    """`[a, "b, c", 'd']` 모양을 낱말 목록으로(따옴표 안의 쉼표는 구분자가 아니다). 대괄호가 닫히지 않았으면 None."""
    text = raw.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    words, current, quote = [], [], ""
    for ch in text[1:-1]:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
        elif ch in _UNQUOTE:
            quote = ch
            current.append(ch)
        elif ch == ",":
            words.append("".join(current))
            current = []
        else:
            current.append(ch)
    words.append("".join(current))
    return [_unquote(word) for word in words if word.strip()]


def read_front_matter(text, *, filename=""):
    """글 한 편(`_posts/**/*.md`)의 머리말 텍스트를 `github_pages` 채널의 기록 하나로 읽는다 — 결과는 `HistoryResult`(기록 0개 또는 1개).
    머리말은 첫 줄의 `---` 부터 다음 `---` 까지의 `키: 값` 줄이다(`tags` 는 `[a, b]` 한 줄이나 `- a` 줄 목록). 날짜는 머리말의 `date` → 없으면 `filename`(파일 이름) 앞의 `YYYY-MM-DD-`.
    언어는 `lang` 이 `kr`·`ko`·`en` 일 때 읽고, 없으면 파일 이름에 `-EN-` 이 있을 때만 영어로 본다(사이트의 규칙과 같다 — 나머지는 모름(None)). 제목이 없거나 머리말이 없으면 건너뛰고 경고한다."""
    where = "머리말"
    if not isinstance(text, str):
        return HistoryResult((), (HistoryWarning(ORIGIN_FRONT_MATTER, where, "글이 아니라서 읽지 않았습니다", True),))
    lines = text.lstrip(chr(0xFEFF)).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or not _FENCE.fullmatch(lines[0]):
        return HistoryResult((), (HistoryWarning(ORIGIN_FRONT_MATTER, where, "첫 줄이 --- 가 아니라 머리말이 없습니다", True),))
    end = next((index for index in range(1, len(lines)) if _FENCE.fullmatch(lines[index])), None)
    if end is None:
        return HistoryResult((), (HistoryWarning(ORIGIN_FRONT_MATTER, where, "머리말을 닫는 --- 줄이 없습니다", True),))
    values, tags_block, current = {}, [], None
    for line in lines[1:end]:
        stripped = line.strip()
        if current == "tags" and stripped.startswith("- "):
            tags_block.append(_unquote(stripped[2:]))
            continue
        match = _KEY.fullmatch(line) if line[:1] not in (" ", "\t") else None
        if match:
            current = match.group(1)
            values[current] = match.group(2)
        elif stripped and not stripped.startswith("#"):
            current = None
    notes = []
    if "title" not in values:
        return HistoryResult((), (HistoryWarning(ORIGIN_FRONT_MATTER, where, "머리말에 title 줄이 없습니다", True),))
    if values["title"].strip().casefold() in _YAML_NOT_TEXT:
        return HistoryResult((), (HistoryWarning(ORIGIN_FRONT_MATTER, where, "제목이 글이 아니라 ‘>’·‘null’ 같은 YAML 표시라서 읽을 수 없습니다(여러 줄 제목은 지원하지 않습니다)", True),))
    try:
        title = _title(_unquote(values["title"]), notes)
    except _Skip as skip:
        return HistoryResult((), (HistoryWarning(ORIGIN_FRONT_MATTER, where, str(skip), True),))
    raw_tags = values.get("tags", "")
    tags = _flow_list(raw_tags) if raw_tags.strip() else (tags_block if tags_block else [])
    if tags is None:
        notes.append("tags 가 [a, b] 모양이 아닙니다")
        tags = []
    base = filename.replace("\\", "/").rsplit("/", 1)[-1] if isinstance(filename, str) else ""
    header_day = _day_prefix(_unquote(values["date"])) if "date" in values else None
    file_match = _FILE_DAY.match(base)
    file_day = valid_day(file_match.group(1)) if file_match else None
    if "date" in values and _unquote(values["date"]).strip() and header_day is None:
        notes.append("머리말 날짜를 읽지 못했습니다" + ("(파일 이름의 날짜를 씁니다)" if file_day else ""))
    language = _language_of(_unquote(values.get("lang", "")))
    if language is None and "-en-" in base.lower():
        language = "en"
    stem = _stem_of(base)
    keywords = _keywords_of(tags, notes)
    try:
        record = _make("github_pages", ORIGIN_FRONT_MATTER, title, keywords=keywords, date=header_day or file_day, language=language, ref=_ref_of(stem, []) if stem else None)
    except ValueError:
        return HistoryResult((), (HistoryWarning(ORIGIN_FRONT_MATTER, where, "읽은 값이 이력 기록의 규칙에 맞지 않습니다", True),))
    return HistoryResult((record,), tuple(HistoryWarning(ORIGIN_FRONT_MATTER, where, note, False) for note in notes))


def read_history_entries(items, channel):
    """date·topic·title·labels·url·post_id 를 가진 항목 목록(Blogger 영문·한글 이력과 네이버 발행 이력의 모양)을 `channel` 채널의 기록으로 읽는다.
    날짜는 `date` → 없으면 `generated_at` 의 앞 10자. `labels` 가 키워드다. `status`·`model`·`attempts` 같은 칸은 읽지 않는다."""
    _check_channel(channel)

    def convert(item, notes):
        data = _mapping(item)
        title = _title(data.get("title"), notes)
        day = _day_of(data.get("date"), notes) if data.get("date") else None
        if day is None:
            day = _day_prefix(data.get("generated_at"))                  # `date` 가 없거나 읽을 수 없어도 만든 시각의 날짜가 멀쩡하면 그것을 쓴다
        return [_make(channel, ORIGIN_ENTRIES, title, keywords=_keywords_of(data.get("labels"), notes), date=day, url=_url_of(data.get("url"), notes), topic=_topic_of(data.get("topic"), notes),
                      ref=_ref_of(data.get("post_id"), notes))]

    return _collect(items, ORIGIN_ENTRIES, convert)


def read_titles(items):
    """GitHub Pages 생성기의 `history.json` — 제목 글자이거나 kr_title·en_title(·topic·date)을 가진 항목이 섞인 목록. 항목마다 한국어 제목과 영어 제목이 있으면 기록 둘이 된다.
    `source_url`·`kr_image` 같은 칸(원문 주소·그림)은 읽지 않는다 — 원문 주소는 블로그 글의 주소가 아니다."""
    def convert(item, notes):
        if isinstance(item, str):
            return [_make("github_pages", ORIGIN_TITLES, _title(item, notes))]
        data = _mapping(item)
        day, topic = _day_of(data.get("date"), notes), _topic_of(data.get("topic"), notes)
        made = []
        for key, language in (("kr_title", "ko"), ("en_title", "en")):
            if isinstance(data.get(key), str) and clean_line(data[key]):
                made.append(_make("github_pages", ORIGIN_TITLES, _title(data[key], notes), date=day, language=language, topic=topic))
        if not made and topic:
            made.append(_make("github_pages", ORIGIN_TITLES, _title(topic, notes), date=day))
        if not made:
            raise _Skip("제목(kr_title·en_title·topic)이 하나도 없습니다")
        return made

    return _collect(items, ORIGIN_TITLES, convert)


def read_naver_items(items, channel):
    """네이버 A·B 이력의 **틀** — 보관함(P3)에서 서비스가 만든 항목(`title`·`keywords`·`date`·`url`·`ref`·`topic`)을 `channel`(naver_a·naver_b)의 기록으로 읽는다.
    이 함수는 보관함이나 파일을 읽지 않는다. 채널이 네이버 A·B 가 아니면 `ValueError`."""
    _check_channel(channel)
    if channel not in NAVER_CHANNELS:
        raise ValueError("네이버 항목은 naver_a·naver_b 채널로만 읽는다")

    def convert(item, notes):
        data = _mapping(item)
        return [_make(channel, ORIGIN_NAVER, _title(data.get("title"), notes), keywords=_keywords_of(data.get("keywords"), notes), date=_day_of(data.get("date"), notes),
                      url=_url_of(data.get("url"), notes), topic=_topic_of(data.get("topic"), notes), ref=_ref_of(data.get("ref"), notes))]

    return _collect(items, ORIGIN_NAVER, convert)


def _check_channel(channel):
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise ValueError("채널은 코드의 채널 이름이어야 한다: " + ", ".join(CHANNELS))


__all__ = [
    "HistoryRecord", "HistoryResult", "HistoryWarning", "MAX_ITEMS", "MAX_KEYWORDS", "MAX_TITLE", "NAVER_CHANNELS", "ORIGINS", "ORIGIN_ENTRIES", "ORIGIN_FRONT_MATTER", "ORIGIN_NAVER", "ORIGIN_POSTS",
    "ORIGIN_TITLES", "read_front_matter", "read_history_entries", "read_naver_items", "read_posts_json", "read_titles", "valid_day",
]
