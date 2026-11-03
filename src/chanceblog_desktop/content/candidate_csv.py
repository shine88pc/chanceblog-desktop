"""주제 후보 CSV 가져오기의 **순수한 부분** — 파일 바이트 → 글자(UTF-8·UTF-8 BOM·cp949) → 표(머리줄·자료 줄) → 칸 값(숫자·날짜·블로그·글 유형 …) → `Candidate.new` 인자.
파일·저장소·네트워크는 건드리지 않는다(읽고 저장하는 것은 `service/candidates.py`). 후보 자료의 규칙(결과를 약속하는 표현 거절·지표가 있으면 조회일 필요 …)은 여기서 다시 만들지 않고
`Candidate` 가 그대로 거절하게 둔다 — 여기서는 칸 글자를 알맞은 값으로 바꾸고, 바꿀 수 없으면 왜 안 되는지 쉬운 말로 알린다(`CsvCellError`).

규칙:
  · 파일은 UTF-8(BOM 있어도)이나 cp949(예전 엑셀·메모장)로 저장한 것만 받고 5MB 이하여야 한다. UTF-16·NUL 이 든 파일·빈 파일은 거절한다.
  · 첫 줄(머리줄)이 있어야 한다. 열 이름은 한국어·영어 모두 받고(`FIELD_ALIASES` — 띄어쓰기·대소문자·밑줄을 무시하고 비교), 모르는 열은 무시하되 알려 준다. 같은 뜻의 열이 둘이면 거절한다.
  · 쉼표가 기본 구분이고 머리줄에 탭(`\\t`)이나 세미콜론이 더 많으면 그것을 쓴다(엑셀의 지역 설정에 따라 다르다).
  · 자료 줄은 최대 `MAX_CSV_ROWS` 줄이다(한 줄마다 보관함에 한 번씩 저장하므로 — 더 많으면 나눠서 가져온다). 빈 줄은 세지 않고 무시한다.
  · 칸은 `clean_line` 으로 정리한 뒤 읽는다(줄바꿈·겹친 공백은 한 칸 공백으로, 제어·보이지 않는 글자는 지운다).
  · 지표 칸이 '없음'(빈 칸·`-`·`N/A`·`데이터 없음` …)이면 데이터 없음이다. 숫자 칸의 천 단위 쉼표(`12,000`)·점수의 `%` 는 받는다.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from ..errors import AppError
from . import candidates as cd
from .profiles import POST_TYPES, clean_line
from .status import PLATFORMS

MAX_CSV_BYTES = 5 * 1024 * 1024            # 가져올 파일의 최대 크기
MAX_CSV_ROWS = 2000                        # 한 번에 가져올 자료 줄(빈 줄 제외)의 최대 수
DELIMITERS = (",", "\t", ";")
_UTF16_MARKS = (b"\xff\xfe", b"\xfe\xff")
_MISSING = frozenset({"", "-", "—", "–", "n/a", "na", "null", "none", "데이터 없음"})            # 지표 칸이 이 글이면 '데이터 없음'
_COUNT = re.compile(r"[0-9]{1,15}(?:\.0+)?")
_SCORE = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,6})?")
_MONTH = re.compile(r"([0-9]{1,2})월?")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MONTH_SPLIT = re.compile(r"[,;/|\s]+")
_LIST_SPLIT = re.compile(r"[,;|]")
_BLOG_SPLIT = re.compile(r"[,;|/]")

# 열 이름(머리줄) — 필드 이름 → 받아들이는 이름들. 비교는 `flat`(띄어쓰기·구두점·밑줄·대소문자 무시)으로 한다. 순위·노출·수익을 약속하는 말은 이름으로 쓰지 않는다(`ALLOWED_TERMS` 와 같은 정신).
FIELD_ALIASES = {
    "topic": ("주제", "추천 포스팅 주제", "포스팅 주제", "추천 주제", "topic", "post topic", "suggested topic"),
    "keyword": ("핵심 키워드", "키워드", "메인 키워드", "대표 키워드", "keyword", "main keyword", "primary keyword", "focus keyword"),
    "sub_keywords": ("보조 키워드", "연관 키워드", "관련 키워드", "sub keywords", "sub keyword", "secondary keywords", "related keywords"),
    "blogs": ("추천 대상 블로그", "대상 블로그", "블로그", "대상", "blog", "blogs", "target blog", "target blogs", "platform"),
    "post_type": ("추천 글 유형", "글 유형", "유형", "post type", "article type"),
    "search_demand": ("월간 검색 수요", "월간 검색량", "검색 수요", "검색량", "search demand", "monthly search volume", "monthly searches", "search volume"),
    "related_blog_results": ("관련 블로그 검색 결과 수", "블로그 검색 결과 수", "관련 블로그 수", "검색 결과 수", "related blog results", "blog results"),
    "trend": ("최근 관심도 변화", "관심도 변화", "추세", "트렌드", "trend", "interest trend"),
    "mobile_share": ("모바일 비중", "모바일 비율", "mobile share", "mobile ratio"),
    "seasonality": ("계절성", "성수기", "seasonality", "peak months"),
    "duplicate": ("기존 글 중복 여부", "기존 글 중복", "중복 여부", "duplicate", "is duplicate", "duplicated"),
    "profile_fit": ("블로그 프로필 적합도", "프로필 적합도", "적합도", "profile fit", "fit"),
    "priority": ("콘텐츠 작성 우선도", "작성 우선도", "우선도", "priority"),
    "keyword_opportunity": ("키워드 기회도", "기회도", "keyword opportunity", "opportunity"),
    "reason": ("추천 이유", "이유", "사유", "reason", "why"),
    "data_date": ("데이터 조회일", "조회일", "데이터 기준일", "기준일", "data date", "queried at", "date"),
}
# 블로그 칸 — 구분 코드와 사람이 쓰는 이름들(비교는 `flat`). `service/format.py` 의 `PLATFORM_KO` 이름이 모두 여기 있어야 한다(시험이 확인한다).
BLOG_NAMES = {
    "github_pages": ("GitHub Pages", "github", "pages", "깃허브 페이지", "깃허브"),
    "blogger_en": ("Blogger 영문", "Blogger English", "블로거 영문"),
    "blogger_ko": ("Blogger 한글", "Blogger Korean", "블로거 한글"),
    "naver_a": ("네이버 A", "Naver A", "네이버 에이"),
    "naver_b": ("네이버 B", "Naver B", "네이버 비"),
}
TRENDS = {"상승": "상승", "보합": "보합", "하락": "하락", "up": "상승", "rising": "상승", "increase": "상승", "flat": "보합", "stable": "보합", "steady": "보합",
          "down": "하락", "falling": "하락", "decrease": "하락"}
YES = frozenset({"예", "네", "y", "yes", "true", "1", "중복", "있음", "o"})
NO = frozenset({"아니오", "아니요", "n", "no", "false", "0", "중복 아님", "없음", "x"})
REQUIRED = ("topic", "keyword")                       # 꼭 있어야 하는 열(대상 블로그 열은 `--blog` 로 대신할 수 있다)


def flat(text):
    """열 이름·블로그 이름을 비교하는 모양 — 호환 문자를 풀고(NFKC) 소문자로 하고 글자·숫자만 남긴다(띄어쓰기·밑줄·붙임표 무시)."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(text)).casefold() if ch.isalnum())


_FIELD_OF = {flat(name): field for field, names in FIELD_ALIASES.items() for name in names}
_BLOG_OF = {flat(name): code for code, names in BLOG_NAMES.items() for name in (code, *names)}


def csv_invalid(reason, detail=""):
    """CSV 파일 전체를 가져올 수 없을 때의 오류(`CANDIDATE_CSV_INVALID`) — 한 줄만 틀린 것은 이 오류가 아니라 그 줄만 거절한다."""
    return AppError("CANDIDATE_CSV_INVALID", {"이유": reason}, detail=detail or reason)


class CsvCellError(ValueError):
    """한 줄의 한 칸을 값으로 바꿀 수 없다 — 그 줄만 거절한다. `item` 은 칸 이름, `reason` 은 쉬운 말의 이유."""

    def __init__(self, item, reason):
        super().__init__(f"{item}: {reason}")
        self.item = item
        self.reason = reason


# ---- 바이트 → 글자 ------------------------------------------------------------------------------------------------------------
def decode(data):
    """파일 바이트를 글자로 — UTF-8(BOM 있어도)을 먼저 시도하고 안 되면 cp949. 못 읽으면 CANDIDATE_CSV_INVALID."""
    if len(data) > MAX_CSV_BYTES:
        raise csv_invalid(f"파일이 너무 큽니다(최대 {MAX_CSV_BYTES // (1024 * 1024)}MB)")
    if data[:2] in _UTF16_MARKS:
        raise csv_invalid("UTF-16 으로 저장된 파일입니다 — 엑셀에서 'CSV UTF-8' 이나 'CSV(쉼표로 분리)' 로 다시 저장합니다")
    if b"\x00" in data:
        raise csv_invalid("글자 파일이 아닙니다(NUL 글자가 들어 있습니다)")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        break
    else:
        raise csv_invalid("UTF-8 이나 cp949 로 읽을 수 없습니다 — 엑셀에서 'CSV UTF-8' 로 다시 저장합니다")
    if not text.strip():
        raise csv_invalid("파일이 비어 있습니다 — 첫 줄에 열 이름(주제·핵심 키워드 …)이 있어야 합니다")
    return text


# ---- 글자 → 표 ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CsvRecord:
    line: int                      # 파일에서 이 자료 줄이 시작하는 줄 번호(머리줄이 1 줄이면 첫 자료 줄은 2)
    cells: tuple                   # 칸의 글(정리하기 전 원문)
    problem: str = ""              # 이 줄을 읽지 못한 이유(CSV 읽기 도구가 거절한 줄 — 있으면 cells 는 비어 있다)
    span: int = 1                  # 이 자료 줄이 파일의 몇 줄에 걸쳐 있는가(따옴표 속 줄바꿈이 있으면 1 보다 크다)


@dataclass(frozen=True)
class CsvTable:
    columns: dict                  # 필드 이름 → 열 번호(0부터)
    names: tuple                   # 머리줄의 열 이름(정리한 것)
    unknown: tuple                 # 알아듣지 못해 무시한 열 이름
    records: tuple                 # CsvRecord — 자료 줄(빈 줄 제외)
    blank: int                     # 무시한 빈 줄 수
    header_line: int               # 머리줄의 줄 번호


def _sniff(text):
    """구분 글자 — 머리줄(첫 글이 있는 줄)에 쉼표·탭·세미콜론 중 가장 많은 것(같으면 쉼표 먼저)."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    return max(DELIMITERS, key=lambda mark: (first.count(mark), -DELIMITERS.index(mark)))


def _why(error):
    return f"CSV 모양이 올바르지 않습니다({' '.join(str(error).split())[:80]})"


def _read_records(text):
    """[(시작 줄 번호, 끝 줄 번호, 칸들, 읽지 못한 이유), …] — 따옴표 속 쉼표·줄바꿈은 한 칸의 글이다. 읽지 못한 줄이 있어도 멈추지 않고 다음 줄로 간다.
    읽기 도구의 칸 크기 한도(기본 128KB)는 이 파일 안에서는 파일 크기까지 올려 둔다 — 한도에서 읽기가 끊기면 큰따옴표 속 여러 줄이 '새 자료 줄' 로 읽히는(유령 후보) 일이 생긴다.
    칸이 너무 긴 것은 칸마다 후보 규칙(주제 200자·핵심 키워드 60자 …)이 그 줄만 거절한다. 읽고 나면 한도를 원래대로 돌려 둔다(읽기 도구의 한도는 프로세스 전체에 걸린 값이다)."""
    found, previous = [], 0
    old_limit = csv.field_size_limit(len(text) + 1)                 # 칸은 글 전체보다 클 수 없다
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=_sniff(text))
        while True:
            try:
                cells, problem = next(reader), ""
            except StopIteration:
                return found
            except csv.Error as error:                              # 그 밖에 읽을 수 없는 줄 — 멈추지 않고 그 줄만 알린다
                cells, problem = [], _why(error)
            found.append((previous + 1, reader.line_num, tuple(cells), problem))
            previous = reader.line_num
    finally:
        csv.field_size_limit(old_limit)


def _is_blank(cells):
    return not any(clean_line(cell) for cell in cells)


def parse_table(text, *, blogs_given=False):
    """글 → 표. 머리줄이 없거나 필요한 열(주제·핵심 키워드·대상 블로그 — 블로그는 `blogs_given` 이면 생략 가능)이 없거나 같은 뜻의 열이 둘이거나 자료 줄이 너무 많으면 CANDIDATE_CSV_INVALID."""
    header, records, blank = None, [], 0
    for line, end, cells, problem in _read_records(text):
        if header is None:
            if problem:
                raise csv_invalid(f"머리줄(첫 줄)을 읽을 수 없습니다: {problem}", detail=f"줄 {line}: {problem}")
            if not _is_blank(cells):
                header = (line, cells)
            continue
        if not problem and _is_blank(cells):
            blank += 1
            continue
        records.append(CsvRecord(line, cells, problem, end - line + 1))
        if len(records) > MAX_CSV_ROWS:
            raise csv_invalid(f"자료 줄이 너무 많습니다(최대 {MAX_CSV_ROWS}줄) — 파일을 나눠서 가져옵니다(이미 들어간 줄은 다시 가져와도 건너뜁니다)")
    if header is None:
        raise csv_invalid("머리줄(첫 줄의 열 이름)이 없습니다")
    header_line, names = header[0], tuple(clean_line(cell) for cell in header[1])
    columns, unknown = {}, []
    for index, name in enumerate(names):
        field = _FIELD_OF.get(flat(name))
        if field is None:
            if name:
                unknown.append(name)
            continue
        if field in columns:
            raise csv_invalid(f"같은 뜻의 열이 둘 이상입니다: {cd.LABELS[field]}(열 {columns[field] + 1}번과 {index + 1}번)")
        columns[field] = index
    needed = (*REQUIRED, *(() if blogs_given else ("blogs",)))
    missing = [cd.LABELS[field] for field in needed if field not in columns]
    if missing:
        hint = "" if blogs_given or "blogs" in columns else " — 대상 블로그 열이 없으면 --blog 로 정할 수 있습니다"
        raise csv_invalid("머리줄(첫 줄)에 필요한 열이 없습니다: " + ", ".join(missing) + hint, detail="찾은 열: " + (", ".join(name for name in names if name)[:200] or "(없음)"))
    return CsvTable(columns, names, tuple(unknown), tuple(records), blank, header_line)


# ---- 칸 값 -------------------------------------------------------------------------------------------------------------------
def _missing(text):
    return text.casefold() in _MISSING


def parse_count(text, item, high):
    """0 이상의 정수(천 단위 쉼표·`1200.0` 모양 허용) 또는 없음(None)."""
    if _missing(text):
        return None
    cleaned = text.replace(",", "").replace(" ", "")
    if not _COUNT.fullmatch(cleaned):
        raise CsvCellError(item, "0 이상의 정수여야 합니다(예: 12000 또는 12,000)")
    number = int(cleaned.split(".")[0])
    if number > high:
        raise CsvCellError(item, f"{high:,} 이하여야 합니다")
    return number


def parse_score(text, item):
    """0~100 사이의 수(`65%` 모양 허용) 또는 없음(None). 정수로 떨어지면 정수로 돌려준다."""
    if _missing(text):
        return None
    cleaned = text.replace(" ", "")
    cleaned = cleaned[:-1] if cleaned.endswith("%") else cleaned
    if not _SCORE.fullmatch(cleaned) or float(cleaned) > 100:
        raise CsvCellError(item, "0~100 사이의 숫자여야 합니다(예: 72.5)")
    value = float(cleaned)
    return int(value) if value.is_integer() else value


def parse_trend(text, item=None):
    if _missing(text):
        return None
    found = TRENDS.get(text.casefold())
    if found is None:
        raise CsvCellError(item or cd.LABELS["trend"], "다음 중 하나여야 합니다: " + ", ".join(cd.TRENDS))
    return found


def parse_months(text, item=None):
    """관심이 몰리는 달 — `11,12,1`·`11월 12월 1월` 같은 모양, 또는 없음(None). 겹침·범위는 후보 자료가 거절한다."""
    name = item or cd.LABELS["seasonality"]
    if _missing(text):
        return None
    months = []
    for token in _MONTH_SPLIT.split(text.strip()):
        found = _MONTH.fullmatch(token)
        if not found:
            raise CsvCellError(name, "달(1~12)을 쉼표나 공백으로 나눠 적어야 합니다(예: 11,12,1)")
        months.append(int(found.group(1)))
    return tuple(months)


def parse_bool(text, item=None):
    if _missing(text):
        return None
    lowered = text.casefold()
    if lowered in YES:
        return True
    if lowered in NO:
        return False
    raise CsvCellError(item or cd.LABELS["duplicate"], "예·아니오 중 하나여야 합니다")


def parse_blogs(text, item=None):
    """블로그 칸 → 구분 코드 튜플(겹치면 하나만). 이름은 `github_pages` 같은 코드도, `네이버 A` 같은 이름도 받는다. 모르는 이름이 있으면 CsvCellError."""
    name = item or cd.LABELS["blogs"]
    found = []
    for token in _BLOG_SPLIT.split(text):
        if not token.strip():
            continue
        code = _BLOG_OF.get(flat(token))
        if code is None:
            raise CsvCellError(name, f"알 수 없는 블로그 「{clean_line(token)[:30]}」 입니다 — 다음 중에서 고릅니다: " + ", ".join(f"{code}({BLOG_NAMES[code][0]})" for code in PLATFORMS))
        if code not in found:
            found.append(code)
    return tuple(found)


def parse_post_type(text, item=None):
    """글 유형 — 정확한 이름이나 '형' 을 뺀 이름(정보·비교·문제 해결 …). 비어 있으면 None(기본 유형)."""
    if not text:
        return None
    wanted = flat(text)
    for kind in POST_TYPES:
        if wanted in (flat(kind), flat(kind.removesuffix("형"))):
            return kind
    raise CsvCellError(item or cd.LABELS["post_type"], "다음 중 하나여야 합니다: " + ", ".join(POST_TYPES))


def parse_sub_keywords(text, main_keyword):
    """보조 키워드 칸 → 낱말 튜플. 쉼표·세미콜론·`|` 로 나누고, 핵심 키워드와 같거나 앞에 나온 것과 겹치는 낱말은 뺀다(같은 말을 되풀이해 적는 일이 흔하다)."""
    seen = {cd.keyword_key(main_keyword)}
    words = []
    for token in _LIST_SPLIT.split(text):
        word = clean_line(token)
        key = cd.keyword_key(word)
        if word and (key not in seen or not key):
            words.append(word)
            seen.add(key)
    return tuple(words)


def check_day(text, item=None):
    """`2026-11-02` 모양의 달력에 있는 날(2000년 이후)만. 아니면 CsvCellError. 후보 자료의 조회일 규칙과 같다(시험이 같은 값들로 확인한다)."""
    name = item or cd.LABELS["data_date"]
    if not _DAY.fullmatch(text):
        raise CsvCellError(name, "2026-11-02 같은 모양이어야 합니다")
    try:
        day = datetime.strptime(text, cd.DAY_FORMAT)
    except ValueError:
        raise CsvCellError(name, "달력에 없는 날짜입니다") from None
    if day.year < cd.MIN_YEAR:
        raise CsvCellError(name, f"{cd.MIN_YEAR}년 이후여야 합니다")
    return text


# ---- 줄 → 후보 인자 ------------------------------------------------------------------------------------------------------------
def _values(table, record):
    if record.problem:
        raise CsvCellError("줄", record.problem)
    extra = record.cells[len(table.names):]
    if any(clean_line(cell) for cell in extra):
        raise CsvCellError("열 수", f"머리줄은 열이 {len(table.names)}개인데 이 줄은 {len(record.cells)}개입니다 — 쉼표가 든 값은 큰따옴표(\")로 감싸야 합니다")
    return {field: clean_line(record.cells[index]) if index < len(record.cells) else "" for field, index in table.columns.items()}


def row_fields(table, record, *, default_blogs=(), default_day=None):
    """자료 줄 하나 → `Candidate.new` 에 넘길 인자들(`topic`·`keyword`·`blogs` 와 나머지 칸). 칸을 값으로 바꿀 수 없으면 CsvCellError. 값의 나머지 규칙은 `Candidate` 가 거절한다."""
    values = _values(table, record)
    fields = {"topic": values["topic"], "keyword": values["keyword"]}
    blogs = parse_blogs(values.get("blogs", "")) if values.get("blogs") else ()
    fields["blogs"] = blogs or tuple(default_blogs)
    if not fields["blogs"]:
        raise CsvCellError(cd.LABELS["blogs"], "비어 있습니다 — 칸을 채우거나 --blog 로 정해 줍니다")
    if values.get("sub_keywords"):
        fields["sub_keywords"] = parse_sub_keywords(values["sub_keywords"], values["keyword"])
    kind = parse_post_type(values.get("post_type", ""))
    if kind is not None:
        fields["post_type"] = kind
    metrics = {
        "search_demand": parse_count(values.get("search_demand", ""), cd.LABELS["search_demand"], cd.MAX_SEARCH_DEMAND),
        "related_blog_results": parse_count(values.get("related_blog_results", ""), cd.LABELS["related_blog_results"], cd.MAX_RELATED_RESULTS),
        "trend": parse_trend(values.get("trend", "")),
        "mobile_share": parse_score(values.get("mobile_share", ""), cd.LABELS["mobile_share"]),
        "seasonality": parse_months(values.get("seasonality", "")),
        "duplicate": parse_bool(values.get("duplicate", "")),
        "profile_fit": parse_score(values.get("profile_fit", ""), cd.LABELS["profile_fit"]),
        "priority": parse_score(values.get("priority", ""), cd.LABELS["priority"]),
        "keyword_opportunity": parse_score(values.get("keyword_opportunity", ""), cd.LABELS["keyword_opportunity"]),
    }
    metrics = {name: value for name, value in metrics.items() if value is not None}
    fields.update(metrics)
    day = values.get("data_date") or default_day                      # 줄의 조회일이 먼저, 칸이 비었거나 열이 없으면 --data-date
    if day:
        fields["data_date"] = check_day(day)
    elif metrics:
        raise CsvCellError(cd.LABELS["data_date"], "지표 값이 있으면 조회일도 있어야 합니다 — 칸을 채우거나 --data-date 로 정해 줍니다")
    if values.get("reason"):
        fields["reason"] = values["reason"]
    return fields


# ---- 나중에 내보내기를 만들 때 쓸 것 --------------------------------------------------------------------------------------------------
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    """CSV 로 내보낼 칸 글 — 엑셀이 수식으로 읽을 수 있는 시작(`=`·`+`·`-`·`@`·탭·줄 처음으로)이면 앞에 작은따옴표(`'`)를 붙여 글로 보이게 한다. 숫자 칸에는 쓰지 않는다(`-5` 가 글이 된다).
    지금은 가져오기만 있어 이 앱이 CSV 를 쓰지 않는다 — 규칙만 먼저 시험으로 고정해 둔 것이다."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


__all__ = [
    "BLOG_NAMES", "CsvCellError", "CsvRecord", "CsvTable", "FIELD_ALIASES", "MAX_CSV_BYTES", "MAX_CSV_ROWS", "check_day", "csv_invalid", "decode", "flat", "parse_blogs", "parse_bool", "parse_count",
    "parse_months", "parse_post_type", "parse_score", "parse_sub_keywords", "parse_table", "parse_trend", "row_fields", "safe_cell",
]
