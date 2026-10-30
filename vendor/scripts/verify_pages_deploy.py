"""Pages 배포 뒤, 새 글이 공개 사이트에서 실제로 열리는지 확인한다.

배포 워크플로가 초록이어도 "새 글이 공개 주소에서 열린다"는 보장은 없다. 빌드 산출물에서 글이 빠졌을 수도 있고
(`published: false`·미래 날짜·제외 설정) 공개 CDN이 이전 응답을 들고 있을 수도 있다.

확인 방법
1. 저장소 `_posts`에서 공개될 가장 새 글(같은 시각에 만든 KR/EN 쌍)을 고른다. `published: false`와 미래 `date`
   (Jekyll 기본값 future: false)는 사이트에서 빠지므로 제외하고 그다음 새 글을 본다. 전부 제외되면 건너뛴다(종료 0).
2. 그 글의 공개 주소를 `_config.yml`의 `permalink`와 파일명(글 front matter의 permalink·slug·date 포함)으로 계산해
   HTTP 200으로 열리는지 본다(상태만 보고 본문은 읽지 않는다). 계산할 수 없는 패턴이면 공개 `posts.json`의 `absoluteUrl`
   (같은 출처 https만)로 대신한다.
3. 공개 `posts.json`은 보조 정보다(소비자가 읽는 목록에 같은 주소로 실렸는지, 다르면 경고). 목록이 낡았다는 이유로는 실패시키지
   않는다. 다만 계산한 주소가 안 열릴 때 `posts.json`이 알려 준 같은 출처 https 주소가 열리면 그 주소로 확인하고 경고를 남긴다
   (주소 계산이 Jekyll과 달랐을 때의 안전망).
4. 안 열리면 --deadline초(기본 720)까지 다시 확인한다. 대기는 --interval초(기본 10)에서 시작해 2배씩 늘어난다(10·20·40·80·160초,
   최대 interval의 16배). 기본값이면 시도는 0·10·30·70·150·310·470·630초 부근이고, 다음 시도가 마감 뒤에 시작하게 되면 그만둔다.
   마감 뒤에는 새 시도도 새 요청도 시작하지 않는다(첫 시도는 끝까지 확인한다). 요청 하나는 소켓 연산별 15초, 전체 30초가 상한이다.
   끝내 안 열리면 종료 1(::error::)로 배포 실행을 빨갛게 하고, 요약에 시도 기록과 마지막 응답의 상태·X-Cache·Age·Last-Modified를
   남겨 '캐시 지연'과 '진짜 미반영'을 가려 보게 한다.

공개 CDN과 시도마다 바꾸는 요청 모양(2026-10-25 독립 검증 실측): CDN은 200 응답을 `max-age=600`으로 보관하고, 없는 주소의 404도
보관한다(404 응답에는 Cache-Control이 없다). 쿼리 문자열(`?cb=…`)·`Cache-Control: no-cache`·`Pragma` 요청 헤더로는 이 보관을
피하지 못한다. 그래서 첫 요청이 배포 전파 전이라 404를 받으면 같은 주소·같은 모양의 재시도는 그 404를 계속 돌려받는다.
404 보관은 최대 약 18분이다(검증자 1회 측정: Age 963~1078초까지 HIT, 약 1114초에 MISS. 구현자가 같은 날 한 관측은 일부 객체가
136~266초에 새로 바뀌어 차이가 있다 — 보관 시간은 불확실하다). 이 보관을 피하려고 같은 모양으로 다시 요청하지 않는다: 시도마다
캐시 키가 달라지는 요청 모양을 바꾼다(SHAPES). 첫 시도는 정규 주소이고 이후 순서는 끝에 `index.html` → `Accept-Encoding: gzip`
→ `Accept-Encoding: deflate` → 첫 구간 뒤 `//` → 둘째 구간 뒤 `//` → 끝에 `//` → 둘째 구간 뒤 `./` → `index.html`+gzip →
`index.html`+deflate 이다. 검증자가 실제 사이트의 기존 글에서 이 모양마다 HTTP 200과 `X-Cache: MISS`(새 캐시 객체)를 확인했다.
`br`·`identity`·임의 토큰·대문자 호스트·`Accept-Language`·`Cookie`·퍼센트 인코딩은 같은 객체로 돌아와 쓰지 않는다. 성공은 상태
200으로만 판정한다. 모양을 모두 쓴 뒤(기본값에서 8번째 시도 다음)에는 처음 모양으로 돌아가며, 그 모양에 남아 있는 404를 읽을 수 있다.
시도가 다른 모양으로 200을 확인했더라도 앞선 시도의 정규 주소가 404였다면 그 주소를 여는 독자는 CDN 보관이 끝날 때까지 404를 볼 수
있어, 요약에 경고로 남긴다. 배포 때 CDN이 비워지는지는 관측하지 못했다.

한계: 이 확인은 '가장 새 글(공개 가능한 것)이 공개 주소에서 열리는가'만 본다. 글을 추가하지 않은 커밋(이미지 교체·기존 글 수정·설정
변경)의 반영 실패는 이미 공개 중인 최신 글 때문에 통과한다. Jekyll 빌드 자체가 실패하는 경우(D-24형: 문서 속 Liquid 구문)는
build 단계가 먼저 빨강이 되고 이 잡은 건너뛰어지므로(skipped) 이 잡이 새로 잡는 것이 아니다. front matter는 블록 매핑의 한 줄
`키: 값`(키에 따옴표·콜론 앞 공백은 허용)만 읽는다. 따옴표 친 `date: "2026-10-25 09:00:00"`는 Jekyll이 문자열로 읽어 사이트
시간대로 해석하지만(Utils.parse_date → Time.parse, ENV["TZ"]=timezone) 이 스크립트는 따옴표 여부를 구별하지 않고 초까지 있는 시각을
UTC로 읽는다(사이트 시간대가 Asia/Seoul이면 미래 판정이 9시간 어긋난다. 이 저장소의 글에는 이런 `date:`가 없다).
주소의 `:title`(slug)은 글자(L*)·Nd·Nl과 `._~!$&'()+,;=@`만 남기고 결합 문자(Mark) 등은 하이픈으로 바꾼다. Jekyll(Ruby의
`[[:alnum:]]`)과 일부 유니코드 범주가 다를 수 있다(검증자 지적 N-5, 고치지 않음 — 한글·영문 slug에는 영향이 없다).

사용: python scripts/verify_pages_deploy.py --base https://사용자.github.io/저장소/ [--root .] [--deadline 720] [--interval 10]
환경변수: PAGE_URL(--base 대신), GITHUB_SHA(요약에 표시), GITHUB_STEP_SUMMARY(있으면 최종 요약을 한 번 덧붙임)
종료 코드: 0 반영 확인(또는 확인할 글 없음) / 1 반영 안 됨(또는 검사가 예상 못 한 오류로 중단) /
          2 사용법·설정 오류(--base·숫자 옵션·`_posts` 폴더 없음)
표준 라이브러리만 쓴다(ubuntu-latest의 python3에 PyYAML이 없을 수 있다).
"""
import argparse
import http.client
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.console import safe_output  # noqa: E402

POST_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$")
TIME_TAIL = re.compile(r"(\d{6})$")
MAX_BYTES = 20 * 1024 * 1024  # posts.json 이 이보다 크면 읽지 않는다(이상 징후)
PAGE_BYTES = 0  # 글 주소는 상태만 보므로 본문을 읽지 않는다
FRONT_MATTER_BYTES = 64 * 1024  # 글 맨 앞에서 이만큼만 읽어 front matter 를 찾는다
USER_AGENT = "chanceblog-verify-pages"
BOM = chr(0xFEFF)  # 파일 맨 앞에 붙을 수 있는 보이지 않는 문자(UTF-8 BOM)
REQUEST_TIMEOUT = 15  # 소켓 연산(연결·읽기)별 제한
REQUEST_TOTAL = 30  # 요청 하나의 전체 시간 상한. 응답을 찔끔찔끔 보내 소켓 제한을 피하는 서버가 요청을 붙잡지 못하게 한다
DEFAULT_DEADLINE = 720  # 원본이 글을 내놓기까지 기다리는 한도. CDN 의 404 보관은 이 시간으로 넘지 않고 요청 모양을 바꿔 피한다
DEFAULT_INTERVAL = 10  # 첫 대기 초. 이후 대기는 2배씩 늘어 MAX_GAP_FACTOR 배까지(10·20·40·80·160·160…)
MAX_GAP_FACTOR = 16
AGE_TOLERANCE = 5  # CDN 의 Age 와 이쪽 경과 시간을 견줄 때의 여유(초)
MAX_POSTS = 10  # 같은 시각의 글이 이보다 많아도 앞의 10건만 확인한다(요청 수 상한)
MAX_HISTORY = 12  # 요약의 시도 기록에 적는 시도 수 상한

ERROR_LINE = "::error::공개 사이트에 최신 글이 반영되지 않았습니다. 실행 요약을 확인하세요."

# 사이트 시간대(_config.yml timezone). 아는 이름만 고정 오프셋으로 풀고, 나머지는 UTC 로 본다.
KNOWN_ZONES = {"asia/seoul": 9, "utc": 0, "etc/utc": 0, "gmt": 0}
FALSE_WORDS = frozenset({"false", "no", "off", "null", "~"})  # YAML false 와 null: Jekyll(SafeYAML)은 대소문자와 무관하게 둘 다 비공개로 본다
FM_KEYS = ("published", "date", "permalink", "slug")
PRETTY_KEEP = frozenset("._~!$&'()+,;=@")  # Jekyll slugify(mode: pretty)가 남기는 문장부호
PERMALINK_TOKENS = frozenset({"year", "month", "day", "title"})  # 계산할 수 있는 토큰
URL_SAFE = "/-._~!$&'()*+,;=:@"  # Jekyll URL.escape_path 가 남기는 문자

Post = namedtuple("Post", "rel name file_date slug front")
Candidate = namedtuple("Candidate", "key path rel name file_date slug")
Selection = namedtuple("Selection", "posts skipped total")
Resp = namedtuple("Resp", "status body headers error", defaults=(b"", {}, ""))
Index = namedtuple("Index", "status headers entries problem")
PostResult = namedtuple("PostResult", "post url how status headers note shape", defaults=("",))
Shape = namedtuple("Shape", "label path accept")  # 요청 모양: 경로 변형 종류와 Accept-Encoding 값(None 이면 보내지 않는다)
Attempt = namedtuple("Attempt", "ok results problems warnings index deadline_hit")
Result = namedtuple("Result", "ok skipped summary posts")


class ConfigError(Exception):
    """설정·사용법 오류(종료 코드 2)."""


class DeadlineReached(Exception):
    """--deadline 이 지나 새 요청을 보내지 않는다."""


# ---------------------------------------------------------------------------------------------
# 출력 안전
# ---------------------------------------------------------------------------------------------
def fold(text, limit=200):
    """외부에서 온 문자열을 한 줄로 접는다. 개행으로 새 줄을 시작해 로그 줄 머리에 `::error::` 같은 워크플로 명령을 흉내 내거나
    `##[` 를 쓰지 못하게 한다. 러너는 줄 앞 공백을 지우고 `::` 를 찾으므로 공백이 아니라 눈에 보이는 접두 문자로 막는다."""
    folded = " ".join(str(text).split()).replace("##[", "# [")
    if folded.lstrip().startswith("::"):
        folded = "→ " + folded
    return folded[:limit]


def code(text, limit=300):
    """마크다운 코드 스팬. 맨 URL 이 자동 링크가 되거나 마크다운으로 해석되는 것을 막는다."""
    return "`" + (fold(text, limit).replace("`", "'") or "(없음)") + "`"


def log(text):
    """진행 로그 한 줄. 파이프 stdout 에서도 바로 보이도록 flush 한다(Actions 단계는 파이프다)."""
    print(fold(text, 400), flush=True)


# ---------------------------------------------------------------------------------------------
# 글 선정(PyYAML 없이 front matter 를 줄 단위로 읽는다)
# ---------------------------------------------------------------------------------------------
# YAML 은 키를 따옴표로 감싸거나(`"published": false`) 콜론 앞에 공백을 둬도(`published : false`) 같은 키로 읽는다
_FM_LINE = re.compile(r"""^(?P<q>["']?)(?P<key>[A-Za-z_][A-Za-z0-9_-]*)(?P=q)[ \t]*:(?:[ \t]+(?P<value>.*))?$""")


def _scalar(raw):
    """YAML 한 줄 스칼라 값 -> 문자열. 읽을 수 없는 모양(블록·목록·앵커 등)이면 None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    quote = raw[0]
    if quote in "\"'":
        i = 1
        while i < len(raw):
            ch = raw[i]
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                if quote == "'" and raw[i + 1:i + 2] == "'":
                    i += 2
                    continue
                break
            i += 1
        else:
            return None  # 닫는 따옴표가 없다
        inner = raw[1:i]
        if quote == "'":
            return inner.replace("''", "'")
        try:
            return json.loads('"' + inner + '"')  # YAML 큰따옴표 이스케이프(\" \\ \uXXXX)는 JSON 과 같다
        except ValueError:
            return inner
    if quote in "|>[{&*!%@`#":
        return None
    comment = re.search(r"\s#", raw)
    if comment:
        raw = raw[:comment.start()]
    return raw.strip() or None


def _is_blank(raw):
    """값이 없거나 주석뿐인가(YAML null)."""
    return re.sub(r"(?:^|\s)#.*$", "", raw or "").strip() == ""


def read_front_matter(path):
    """글 front matter 에서 published·date·permalink·slug 만 읽는다. front matter 가 없거나 못 읽으면 {}.
    값은 문자열, 읽을 수 없는 모양이면 None. 들여쓴 줄(중첩 값)은 무시한다."""
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(FRONT_MATTER_BYTES)
    except OSError:
        return {}
    lines = chunk.decode("utf-8", "replace").lstrip(BOM).splitlines()
    if not lines or lines[0].rstrip() != "---":
        return {}
    found = {}
    for line in lines[1:]:
        if line.rstrip() in ("---", "..."):
            break
        match = _FM_LINE.match(line)
        if match and match.group("key") in FM_KEYS:
            key, value = match.group("key"), _scalar(match.group("value"))
            if key == "published" and value is None and _is_blank(match.group("value")):
                value = "null"  # `published:` 처럼 값이 비면 YAML null 이고 Jekyll 은 그 글을 공개하지 않는다
            found[key] = value
    return found


def is_unpublished(front):
    """`published: false`(따옴표 없는 false·no·off·null·빈 값, 대소문자 무관). Jekyll 은 따옴표 친 "false" 를 문자열(참)로 보아
    공개하지만, 의심스러우면 이 글이 아니라 다음 글을 확인하는 쪽(거짓 경보 방지)을 고른다."""
    value = front.get("published")
    return value is not None and value.lower() in FALSE_WORDS


_WHEN = re.compile(
    r"^(\d{4})-(\d{1,2})-(\d{1,2})"
    r"(?:[Tt ]\s*(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
    r"\s*(Z|z|UTC|utc|[+-]\d{1,2}(?::?\d{2})?)?$")


def parse_when(text, tz):
    """front matter date 문자열 -> 시간대가 있는 datetime. 못 읽으면 None. 시간대 표기가 없으면 사이트 시간대(tz)로 보되,
    초까지 있는 'YYYY-MM-DD HH:MM:SS'는 Jekyll 이 쓰는 SafeYAML 처럼 UTC 로 본다."""
    match = _WHEN.match((text or "").strip())
    if not match:
        return None
    year, month, day, hour, minute, second, zone = match.groups()
    try:
        offset = tz
        if zone:
            if zone.lower() in ("z", "utc"):
                offset = timezone.utc
            else:
                digits = zone[1:].replace(":", "")
                hours, minutes = (int(digits), 0) if len(digits) <= 2 else (int(digits[:-2]), int(digits[-2:]))
                offset = timezone((-1 if zone[0] == "-" else 1) * timedelta(hours=hours, minutes=minutes))
        elif second is not None:
            offset = timezone.utc  # SafeYAML 은 시간대 없는 'YYYY-MM-DD HH:MM:SS' 를 UTC 로 읽는다(초가 없으면 사이트 시간대)
        return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0),
                        tzinfo=offset)
    except ValueError:
        return None


def post_when(post, tz):
    """Jekyll 이 이 글의 날짜로 쓰는 시각: front matter date, 없으면 파일명 날짜의 자정(사이트 시간대)."""
    parsed = parse_when(post.front.get("date"), tz)
    if parsed is not None:
        return parsed
    return datetime(post.file_date.year, post.file_date.month, post.file_date.day, tzinfo=tz)


def ineligible_reason(post, now, tz):
    """공개 사이트에 올라오지 않을 글이면 이유, 아니면 None."""
    if is_unpublished(post.front):
        return "published: false"
    if post_when(post, tz) > now:
        return "미래 날짜(Jekyll 기본값 future: false)"
    return None


def find_candidates(root):
    """`_posts` 아래 글 파일 목록(최신 키 계산 포함). `_posts` 폴더가 없으면 ConfigError — 조용히 건너뛰면 검증이 꺼진다."""
    root = Path(root)
    posts_dir = root / "_posts"
    if not posts_dir.is_dir():
        raise ConfigError(f"`_posts` 폴더가 없습니다({fold(posts_dir, 120)}). --root 와 checkout 범위를 확인하세요.")
    found = []
    for path in posts_dir.rglob("*.md"):  # 순서는 select_newest 가 정한다
        parts = path.relative_to(posts_dir).parts
        # Jekyll 은 _ . # ~ 로 시작하거나 ~ 로 끝나는 파일·폴더를 읽지 않는다
        if any(part.startswith((".", "_", "#", "~")) or part.endswith("~") for part in parts) or not path.is_file():
            continue
        match = POST_NAME.match(path.name)
        if not match:
            continue
        try:
            file_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue  # 2026-13-45 같은 날짜는 Jekyll 이 빌드 오류로 거절한다
        slug = match.group(4)
        tail = TIME_TAIL.search(slug)
        key = (file_date.isoformat(), tail.group(1) if tail else "000000")
        found.append(Candidate(key, path, path.relative_to(root).as_posix(), path.name, file_date, slug))
    return found


def select_newest(root, now, tz):
    """공개될 가장 새 글. '새롭다'는 파일명의 날짜와 끝의 시각(HHMMSS)으로 정하고, 같은 시각의 KR/EN 쌍이면 둘 다 돌려준다.
    `published: false`·미래 날짜인 글은 건너뛰고 그다음 새 글을 본다. -> Selection(posts, skipped, total)
    posts 가 비면 확인할 글이 없다(전부 제외됐거나 글이 없음)."""
    candidates = find_candidates(root)
    by_key = {}
    for cand in candidates:
        by_key.setdefault(cand.key, []).append(cand)
    skipped = []
    for key in sorted(by_key, reverse=True):
        eligible = []
        for cand in sorted(by_key[key], key=lambda c: c.rel):
            post = Post(cand.rel, cand.name, cand.file_date, cand.slug, read_front_matter(cand.path))
            reason = ineligible_reason(post, now, tz)
            if reason:
                skipped.append((post, reason))
            else:
                eligible.append(post)
        if eligible:
            return Selection(eligible, skipped, len(candidates))
    return Selection([], skipped, len(candidates))


# ---------------------------------------------------------------------------------------------
# 공개 주소 계산(Jekyll permalink)
# ---------------------------------------------------------------------------------------------
_CFG_LINE = re.compile(r"""^(?P<q>["']?)(?P<key>permalink|timezone)(?P=q)[ \t]*:(?:[ \t]+(?P<value>.*))?$""")
_CFG_NESTED = re.compile(r"""^[ \t]+(?P<q>["']?)permalink(?P=q)[ \t]*:""")


def read_site_config(root):
    """`_config.yml` 에서 최상위 permalink·timezone 만 정규식으로 읽는다. 들여쓴 permalink(defaults·collections)가 있으면
    nested_permalink 로 표시한다. 파일이 없으면 {}."""
    try:
        with open(Path(root) / "_config.yml", "rb") as fh:
            text = fh.read(FRONT_MATTER_BYTES * 4).decode("utf-8", "replace").lstrip(BOM)
    except OSError:
        return {}
    config = {}
    for line in text.splitlines():
        match = _CFG_LINE.match(line)
        if match:
            config[match.group("key")] = _scalar(match.group("value"))
        elif _CFG_NESTED.match(line):
            config["nested_permalink"] = True
    return config


def site_timezone(config):
    name = (config.get("timezone") or "").strip().lower()
    return timezone(timedelta(hours=KNOWN_ZONES.get(name, 0)))


def jekyll_slug(text):
    """Jekyll 의 :title 값(Utils.slugify, mode pretty, cased): 글자·숫자([[:alnum:]])와 `._~!$&'()+,;=@` 만 남기고
    나머지 연속 구간(결합 문자 포함)은 하이픈 하나로 바꾼 뒤 양끝 하이픈을 지운다."""
    pieces, gap = [], False
    for ch in text:
        if ch.isalpha() or unicodedata.category(ch) in ("Nd", "Nl") or ch in PRETTY_KEEP:
            if gap:
                pieces.append("-")
                gap = False
            pieces.append(ch)
        else:
            gap = True
    if gap:
        pieces.append("-")
    return "".join(pieces).strip("-")


_TOKEN = re.compile(r":([a-z_]+)")


def render_permalink(template, post, tz):
    """permalink 템플릿 -> (사이트 루트 기준 경로, 이유). 계산할 수 없으면 (None, 이유).
    `/` 로 시작하고 토큰이 :year :month :day :title 뿐일 때만 계산한다."""
    if not template.startswith("/"):
        return None, f"permalink {fold(template, 60)} 은 계산하지 않는 형식"
    unknown = sorted(set(_TOKEN.findall(template)) - PERMALINK_TOKENS)
    if unknown:
        return None, "지원하지 않는 permalink 토큰 " + ", ".join(":" + name for name in unknown)
    when = post_when(post, tz).astimezone(tz)  # Jekyll: Time.parse(...).localtime — 날짜 자리표시자는 사이트 시간대 기준
    slug = jekyll_slug(post.front.get("slug") or post.slug)
    values = {"year": f"{when.year:04d}", "month": f"{when.month:02d}", "day": f"{when.day:02d}", "title": slug}
    if ":title" in template and not slug:
        return None, "slug 가 비어 있음"
    path = _TOKEN.sub(lambda match: values[match.group(1)], template)
    # Jekyll URL#sanitize_url: ".." 는 "/" 로, "./" 는 지우고, 연속 슬래시는 하나로 한다
    path = re.sub(r"/{2,}", "/", ("/" + path).replace("..", "/").replace("./", ""))
    return urllib.parse.quote(path, safe=URL_SAFE), ""


def expected_url(base, post, config, tz):
    """새 글의 공개 주소를 permalink 로 계산한다. -> (주소, 이유). 계산할 수 없으면 (None, 이유).
    글 자신의 front matter permalink 가 있으면 그것이, 없으면 `_config.yml` 의 permalink 가 쓰인다(Jekyll 과 같은 우선순위)."""
    if "permalink" in post.front:
        template = post.front["permalink"]
        if template is None:
            return None, "글의 front matter permalink 를 읽을 수 없음"
    else:
        template = config.get("permalink")
        if not template:
            return None, "_config.yml 에 permalink 가 없음"
        if config.get("nested_permalink"):
            return None, "_config.yml 에 defaults·collections 의 permalink 설정이 있음"
    path, why = render_permalink(template, post, tz)
    if path is None:
        return None, why
    return base + path.lstrip("/"), ""


# ---------------------------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------------------------
_KEEP_HEADERS = ("age", "last-modified", "cache-control", "x-cache")


def _pick_headers(headers):
    """응답 헤더 중 진단에 쓰는 것만(소문자 이름 -> 접은 문자열)."""
    picked = {}
    if headers is None:
        return picked
    for name in _KEEP_HEADERS:
        value = headers.get(name)
        if value:
            picked[name] = fold(value, 80)
    return picked


def _error_name(exc):
    """예외 종류 이름만(메시지는 외부 문자열이라 쓰지 않는다). URLError 는 원인 종류도 덧붙인다."""
    name = type(exc).__name__
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException):
        name += "/" + type(reason).__name__
    return name


def _fetch_once(url, timeout, opener, limit, headers):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache", **(headers or {})})
        with opener(req, timeout=timeout) as resp:
            body = resp.read(limit + 1) if limit > 0 else b""  # limit 0 은 상태만 본다: 본문을 읽지 않는다
            return Resp(resp.status, body, _pick_headers(getattr(resp, "headers", None)), "")
    except urllib.error.HTTPError as exc:
        return Resp(exc.code, b"", _pick_headers(exc.headers), "")
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        return Resp(0, b"", {}, _error_name(exc))


def fetch(url, timeout=REQUEST_TIMEOUT, opener=urllib.request.urlopen, limit=MAX_BYTES, headers=None, total=REQUEST_TOTAL):
    """GET. -> Resp(상태, 본문 바이트, 진단 헤더, 오류 이름). 4xx/5xx 도 예외 대신 상태로 돌려준다.
    네트워크·프로토콜·주소 형식 오류는 상태 0 과 예외 종류 이름으로 돌려준다(예외로 새지 않는다). limit 0 이면 본문을 읽지 않는다.
    요청 전체가 total 초를 넘으면 상태 0 과 'TotalTimeout' 으로 돌려준다 — 소켓 제한(timeout)은 연산별이라 응답을 찔끔찔끔
    보내는 서버가 요청을 오래 붙잡을 수 있다. 넘긴 요청의 작업 스레드는 버려 둔다(데몬 스레드라 소켓 제한이 끝내고
    프로세스 종료를 막지 않는다)."""
    outcome = []

    def work():
        try:
            outcome.append(_fetch_once(url, timeout, opener, limit, headers))
        except BaseException as exc:  # noqa: BLE001 - 호출한 쪽에서 그대로 다시 던진다(KeyboardInterrupt 도 삼키지 않는다)
            outcome.append(exc)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(total)
    if not outcome:
        return Resp(0, b"", {}, "TotalTimeout")
    if isinstance(outcome[0], BaseException):
        raise outcome[0]
    return outcome[0]


def _split(url):
    try:
        return urllib.parse.urlsplit(url)
    except ValueError:  # 닫히지 않은 [ 등
        return None


def valid_base(base):
    """공개 사이트 주소: https, 호스트가 있고, 계정 정보(user@)·쿼리·조각이 없다."""
    parts = _split(base)
    return (parts is not None and parts.scheme == "https" and bool(parts.netloc) and "@" not in parts.netloc
            and not parts.query and not parts.fragment)


def same_origin_https(url, base):
    """posts.json 에서 온 주소를 요청해도 되는가: https 이고 base 와 같은 출처(호스트·포트)이며 공백·제어 문자가 없다."""
    if not isinstance(url, str) or any(ch <= " " or ch == "\x7f" for ch in url):
        return False
    parts, base_parts = _split(url), _split(base)
    if parts is None or base_parts is None or parts.scheme != "https" or "@" in parts.netloc:
        return False
    try:
        return (parts.hostname is not None and parts.hostname == base_parts.hostname
                and (parts.port or 443) == (base_parts.port or 443))
    except ValueError:  # 잘못된 포트
        return False


def same_url(left, right):
    return urllib.parse.unquote(left) == urllib.parse.unquote(right)


def with_cache_buster(url, token):
    """쿼리를 붙인다. 사이트는 쿼리를 무시한다. Pages CDN 캐시는 피하지 못한다(실측, 모듈 설명 참고) — 해롭지 않은 보조일 뿐이다."""
    parts = urllib.parse.urlsplit(url)
    query = (parts.query + "&" if parts.query else "") + "cb=" + urllib.parse.quote(str(token), safe="")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def status_label(status, note=""):
    """'HTTP 404' 또는 '연결 실패(예외 종류)'. note 는 예외 종류 이름이어야 하므로 이름에 쓰이는 문자만 남긴다."""
    if status:
        return f"HTTP {status}"
    return "연결 실패(" + re.sub(r"[^\w./-]", "?", str(note))[:60] + ")" if note else "연결 실패"


# 요청 모양: 시도마다 CDN 캐시 키가 달라지게 한다. 같은 주소를 같은 모양으로 다시 요청하면 CDN 이 보관한 404 를 계속
# 돌려받는다(404 보관은 최대 약 18분 — 모듈 설명). 아래 모양은 2026-10-25 독립 검증이 실제 사이트의 기존 글에서 HTTP 200 과
# X-Cache: MISS(새 캐시 객체)로 확인한 것이다. 쿼리 문자열·no-cache·br·identity·대문자 호스트·Accept-Language·Cookie·
# 퍼센트 인코딩은 같은 객체로 돌아와 넣지 않았다. 첫 모양은 정규 주소다. path 는 경로 변형 종류(''=그대로).
SHAPES = (
    Shape("정규 주소", "", None),
    Shape("끝에 index.html", "index", None),
    Shape("Accept-Encoding: gzip", "", "gzip"),
    Shape("Accept-Encoding: deflate", "", "deflate"),
    Shape("첫 구간 뒤 //", "slash1", None),
    Shape("둘째 구간 뒤 //", "slash2", None),
    Shape("끝에 //", "tail", None),
    Shape("둘째 구간 뒤 ./", "dot2", None),
    Shape("index.html + gzip", "index", "gzip"),
    Shape("index.html + deflate", "index", "deflate"),
)


def shape_url(url, shape):
    """정규 주소를 이 모양의 주소로 바꾼다. 이 주소에는 쓸 수 없는 모양이면 None(예: 슬래시로 끝나지 않는 주소의 index.html)."""
    kind = shape.path
    if not kind:
        return url
    parts = urllib.parse.urlsplit(url)
    path = parts.path
    trailing = path.endswith("/")
    names = [name for name in path.split("/") if name]
    if kind in ("index", "tail"):
        if not trailing:
            return None
        path += "index.html" if kind == "index" else "/"
    else:
        at = 1 if kind == "slash1" else 2
        if len(names) <= at:  # 그 구간 뒤에 이어지는 구간이 있어야 한다
            return None
        names.insert(at, "." if kind == "dot2" else "")
        path = "/" + "/".join(names) + ("/" if trailing else "")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def pick_shape(url, attempt):
    """attempt(1부터)번째 시도에 쓸 모양. 이 주소에 쓸 수 있는 모양을 SHAPES 순서로 돌려 쓴다(첫 시도는 언제나 정규 주소)."""
    usable = [shape for shape in SHAPES if shape_url(url, shape) is not None]
    return usable[(attempt - 1) % len(usable)]


def wait_after(tries, interval):
    """tries 번째 시도 뒤의 대기 초: interval, 2배, 4배 … 최대 interval 의 MAX_GAP_FACTOR 배."""
    return interval * min(2 ** (tries - 1), MAX_GAP_FACTOR)


class Requester:
    """요청 한 건을 보낸다. --deadline 은 요청 '사이'에서만 확인한다: 이미 나간 요청은 기다리고, 마감이 지난 뒤에는
    새 요청을 보내지 않는다(첫 시도는 마감과 무관하게 끝까지 확인해 --deadline 0 이 '한 번 확인'이 되게 한다)."""

    def __init__(self, fetcher, clock, deadline):
        self.fetcher, self.clock, self.deadline = fetcher, clock, deadline
        self.start = clock()
        self.attempt = 1

    def elapsed(self):
        return self.clock() - self.start

    def __call__(self, url, limit=MAX_BYTES, budgeted=True, headers=None):
        if budgeted and self.attempt > 1 and self.elapsed() >= self.deadline:
            raise DeadlineReached()
        return self.fetcher(url, limit=limit, headers=headers)

    def probe(self, url, token):
        """글 주소 하나를 이번 시도의 요청 모양으로 요청한다(상태만 본다). -> (Resp, 모양 이름)"""
        shape = pick_shape(url, self.attempt)
        headers = {"Accept-Encoding": shape.accept} if shape.accept else None
        return self(with_cache_buster(shape_url(url, shape), token), PAGE_BYTES, headers=headers), shape.label


# ---------------------------------------------------------------------------------------------
# 공개 posts.json(보조 정보 · 주소 계산 불가 때의 대체)
# ---------------------------------------------------------------------------------------------
def load_index(request, base, token, budgeted=True):
    """공개 posts.json 을 읽는다. -> Index(상태, 진단 헤더, {path: 항목} 또는 None, 문제 설명). 읽지 못해도 예외로 새지 않는다."""
    resp = request(with_cache_buster(base + "posts.json", token), MAX_BYTES, budgeted)
    if resp.status != 200:
        return Index(resp.status, resp.headers, None, f"posts.json 을 읽지 못함({status_label(resp.status, resp.error)})")
    if len(resp.body) > MAX_BYTES:
        return Index(200, resp.headers, None, "posts.json 이 비정상적으로 큼")
    try:
        data = json.loads(resp.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return Index(200, resp.headers, None, "posts.json 이 올바른 JSON 이 아님")
    if not isinstance(data, list):
        return Index(200, resp.headers, None, "posts.json 의 최상위 값이 목록이 아님")
    entries = {e["path"]: e for e in data if isinstance(e, dict) and isinstance(e.get("path"), str)}
    return Index(200, resp.headers, entries, "")


def index_address(index, post, base):
    """posts.json 이 이 글에 대해 알려 주는 주소. 같은 출처 https 일 때만 쓴다. -> (주소, 이유)"""
    if index.entries is None:
        return None, index.problem
    entry = index.entries.get(post.rel)
    if entry is None:
        return None, "posts.json 에 없음"
    url = entry.get("absoluteUrl")
    if not isinstance(url, str) or not url:
        return None, "posts.json 항목에 주소가 없음"
    if not same_origin_https(url, base):
        return None, "posts.json 의 주소가 다른 출처이거나 https 가 아님"
    return url, ""


# ---------------------------------------------------------------------------------------------
# 확인
# ---------------------------------------------------------------------------------------------
def check_post(base, post, config, tz, request, token, get_index, warnings):
    """새 글 하나의 공개 주소가 열리는지 본다. -> PostResult"""
    url, why = expected_url(base, post, config, tz)
    how = "계산"
    if url is None:  # 계산할 수 없는 패턴이면 posts.json 의 주소로 대신한다
        url, reason = index_address(get_index(), post, base)
        if url is None:
            return PostResult(post, None, "posts.json", None, {}, f"주소를 계산할 수 없고({why}) posts.json 에서도 얻지 못함: {reason}")
        how = "posts.json"
    resp, shape = request.probe(url, token)
    if resp.status == 200:
        return PostResult(post, url, how, 200, resp.headers, "", shape)
    if how == "계산":
        # 계산한 주소가 안 열리면 posts.json 이 다른 주소를 알려 주는지 본다(주소 계산이 틀렸을 때의 안전망: 글이 실제로
        # 그 주소에서 열리면 공개된 것이다). 이 조회가 마감에 걸려도 첫 응답의 판정은 그대로 남긴다.
        try:
            alt, _ = index_address(get_index(), post, base)
            if alt and not same_url(alt, url):
                alt_resp, alt_shape = request.probe(alt, token)
                if alt_resp.status == 200:
                    warnings.append(f"{post.name}: 계산한 주소 {code(url)} 는 열리지 않고 posts.json 주소 {code(alt)} 는 열려 "
                                    "그 주소로 확인함 — 주소 계산 규칙 점검 필요")
                    return PostResult(post, alt, "posts.json", 200, alt_resp.headers, "", alt_shape)
                warnings.append(f"{post.name}: 계산한 주소와 posts.json 주소가 다르고 둘 다 열리지 않음(posts.json 주소 "
                                f"{code(alt)}: {status_label(alt_resp.status, alt_resp.error)})")
        except DeadlineReached:
            pass
    return PostResult(post, url, how, resp.status, resp.headers, resp.error, shape)


def describe_problem(res):
    if res.url is None:
        return f"{res.post.name}: {res.note}"
    age = f", Age {res.headers['age']}" if res.headers.get("age") else ""
    return f"{res.post.name}: 새 글 주소가 열리지 않음({status_label(res.status, res.note)}{age}) {res.url}"


def check_once(base, posts, config, tz, request, token):
    """한 번 확인한다. 어떤 요청 실패도 예외로 새지 않고 그 시도의 문제로 기록한다. -> Attempt"""
    results, problems, warnings = [], [], []
    index = None

    def get_index():
        nonlocal index
        if index is None:
            index = load_index(request, base, token)
        return index

    hit = False
    try:
        for post in posts:
            res = check_post(base, post, config, tz, request, token, get_index, warnings)
            results.append(res)
            if res.status != 200:
                problems.append(describe_problem(res))
    except DeadlineReached:
        hit = True
        problems.append("마감 시각이 지나 나머지 확인을 하지 못함")
    if not problems and index is None:
        # 성공: 보조 정보(공개 posts.json 에 같은 주소로 실렸는지)를 한 번 읽는다. 실패해도 판정은 그대로다.
        try:
            index = load_index(request, base, token, budgeted=False)
        except Exception as exc:  # noqa: BLE001 - 보조 정보라 판정에 영향이 없다. 요약에 한 줄 남겨 숨기지 않는다
            warnings.append(f"posts.json 보조 확인 중 오류({type(exc).__name__}) — 판정에는 영향 없음")
    return Attempt(not problems, results, problems, warnings, index, hit)


def _seconds(text):
    """Age 같은 헤더 값 -> 정수 초. ASCII 숫자만 받는다(str.isdigit 은 '²' 같은 문자도 참이라 int 가 실패한다). 아니면 None."""
    return int(text) if re.fullmatch(r"[0-9]{1,9}", text or "") else None


def interpret(att, elapsed):
    """실패했을 때 마지막 응답으로 '캐시가 들고 있는 응답'과 '원본이 직접 준 404'를 가려 주는 한 줄. elapsed 는 이 검사의 경과 초다:
    응답의 Age 가 그 이내면 이 검사가 앞서 보낸 요청이 남긴 객체일 수 있다(그 요청 때 원본이 404 를 줬다는 뜻이지, 검사 시작 전부터
    캐시가 옛 응답을 들고 있었다는 뜻이 아니다)."""
    failed = [r for r in att.results if r.url is not None and r.status != 200]
    if not failed:
        return "확인을 마치지 못했습니다(마감 또는 예상 못 한 오류). 실행 로그를 확인하세요."
    ages = []  # CDN 이 보관 객체로 돌려준 응답들의 Age
    for res in failed:
        age = _seconds(res.headers.get("age", "")) or 0
        if age > 0 or "HIT" in res.headers.get("x-cache", "").upper():
            ages.append(age)
    if ages and max(ages) > elapsed + AGE_TOLERANCE:
        return (f"마지막 응답의 `Age` {max(ages)}초가 이 검사의 경과 시간({elapsed}초)보다 길어, 이 검사가 시작되기 전부터 공개 CDN 이 들고 "
                "있던 응답입니다 — '캐시 지연'일 수 있습니다. 404도 보관되며(1회 측정으로 최대 약 18분, 불확실) 보관이 끝나면 풀리니 "
                "몇 분 뒤 직접 열어 봅니다.")
    if ages:
        return (f"마지막 응답은 CDN 이 보관한 객체입니다(`X-Cache: HIT` 또는 `Age` {max(ages)}초). `Age` 가 이 검사의 경과 시간({elapsed}초) "
                "이내라 이 검사가 앞서 보낸 요청이 남긴 응답을 다시 읽은 것으로 보입니다. 그 요청 때 원본이 404 를 줬다는 뜻이라 "
                "'캐시 때문에 늦은 것'과 '아직 안 올라온 것'을 이 값만으로는 가를 수 없습니다. 몇 분 뒤 새 글 주소를 직접 열어 봅니다.")
    if all(r.status == 404 for r in failed):
        return ("`X-Cache` 가 MISS 이거나 `Age` 가 없거나 0 이라 CDN 보관이 아니라 원본의 답으로 보입니다. '진짜 미반영'(빌드 산출물에 글이 "
                "없음 — `published`·`date`·permalink 와 build 로그 확인) 가능성이 큽니다.")
    return "사이트에 연결하지 못했거나 서버 오류입니다. GitHub Pages 장애일 수 있습니다(githubstatus.com)."


def _meta(headers):
    parts = []
    if headers.get("x-cache"):
        parts.append(f"X-Cache {code(headers['x-cache'], 40)}")
    if headers.get("age"):
        parts.append(f"Age {code(headers['age'], 40)}")
    if headers.get("last-modified"):
        parts.append(f"Last-Modified {code(headers['last-modified'], 60)}")
    return "".join(", " + part for part in parts)


def index_notes(att):
    """공개 posts.json 에 대한 참고 줄들(판정에는 쓰지 않는다)."""
    index = att.index
    if index is None:
        return []
    head = "- 참고(공개 `posts.json`, 판정에는 쓰지 않음): "
    if index.entries is None:
        return [head + fold(index.problem, 120) + _meta(index.headers)]
    lines = [head + status_label(index.status) + _meta(index.headers)]
    for res in att.results:
        if res.how != "계산":
            continue
        entry = index.entries.get(res.post.rel)
        if entry is None:
            text = "목록에 아직 없음" + ("(캐시 지연일 수 있음)" if res.status == 200 else "")
        else:
            alt = entry.get("absoluteUrl")
            if not isinstance(alt, str) or not alt:
                text = "목록 항목에 주소가 없음"
            elif same_url(alt, res.url):
                text = "목록에 있고 주소가 같음"
            else:
                text = f"경고: 목록의 주소 {code(alt)} 가 계산한 주소와 다름 — 주소 계산 규칙 점검 필요"
        lines.append(f"  - {code(res.post.name)}: {text}")
    return lines


def shapes_of(att):
    """이 시도에서 쓴 요청 모양 이름들(중복 없이, 쓴 순서)."""
    shapes = []
    for res in att.results:
        if res.shape and res.shape not in shapes:
            shapes.append(res.shape)
    return shapes


def attempt_brief(tries, seconds, att):
    """요약의 시도 기록 한 칸: '2회(10초, 끝에 index.html) HTTP 404'."""
    shapes = shapes_of(att)
    head = f"{seconds}초" + (", " + "·".join(shapes) if shapes else "")
    failed = [res for res in att.results if res.status != 200]
    if att.ok:
        state = "HTTP 200"
    elif failed:
        state = status_label(failed[0].status, failed[0].note) if failed[0].url is not None else "주소를 얻지 못함"
    else:
        state = "확인을 마치지 못함"
    return f"{tries}회({head}) {state}"


def render_summary(sha, att, selection, posts, tries, elapsed, deadline, ok, history=()):
    lines = ["### 공개 사이트 반영 확인", f"- 배포 커밋: {code(sha, 40) if sha else '(알 수 없음)'}",
             "- 확인한 최신 글: " + ", ".join(code(p.name) for p in posts)]
    if selection.skipped:
        shown = selection.skipped[:6]
        more = f" 외 {len(selection.skipped) - len(shown)}건" if len(selection.skipped) > len(shown) else ""
        lines.append("- 더 새 글 중 공개되지 않아 건너뜀: " + ", ".join(f"{code(p.name)}({reason})" for p, reason in shown) + more)
    if len(selection.posts) > len(posts):
        lines.append(f"- 같은 시각의 글이 {len(selection.posts)}건이라 앞의 {len(posts)}건만 확인")
    if ok:
        lines.append(f"- 결과: **반영됨** — 새 글 주소가 열림(HTTP 200), 시도 {tries}회·경과 {elapsed}초")
    else:
        lines.append(f"- 결과: **반영 안 됨** — 시도 {tries}회·경과 {elapsed}초(마감 {deadline}초) 동안 새 글 주소가 열리지 않음")
    for res in att.results:
        if res.url is None:
            lines.append(f"  - {code(res.post.name)} — {fold(res.note, 300)}")
        else:
            shape = f", 요청 모양 {code(res.shape, 40)}" if res.shape else ""
            lines.append(f"  - {code(res.url)} — {status_label(res.status, res.note)}{_meta(res.headers)}{shape}")
    if not att.results:  # 글별 결과 없이 끝난 시도(예상 못 한 오류 등)는 문제를 그대로 적는다
        lines += [f"  - {fold(problem, 300)}" for problem in att.problems]
    if att.deadline_hit:
        lines.append(f"  - 마감({deadline}초)이 지나 일부 확인을 하지 못함")
    if len(history) > 1:
        shown = history[-MAX_HISTORY:]
        omitted = f"(앞의 {len(history) - len(shown)}회 생략) " if len(history) > len(shown) else ""
        lines.append("- 시도 기록: " + omitted + " → ".join(shown))
    lines += [f"- 경고: {w}" for w in att.warnings]
    lines += index_notes(att)
    if not ok:
        lines.append("- 해석: " + interpret(att, elapsed))
        lines.append("- 조치: Actions 의 이 실행 로그와 [공통] 사이트 자동 배포 이전 실행을 확인하고, 새 글 주소를 직접 열어 본다")
    lines.append("- 범위: 가장 새 글(공개 가능한 것)의 공개 여부만 본다 — 이미지 교체·기존 글 수정 같은 변경의 반영은 확인하지 않는다")
    return "\n".join(lines)


def skipped_summary(sha, selection):
    lines = ["### 공개 사이트 반영 확인", f"- 배포 커밋: {code(sha, 40) if sha else '(알 수 없음)'}"]
    if selection.total == 0:
        lines.append("- 결과: **건너뜀** — 저장소 `_posts`에 확인할 글이 없음")
    else:
        lines.append(f"- 결과: **건너뜀** — 공개될 글이 없어 확인하지 않음(글 {selection.total}건 모두 `published: false` 또는 미래 날짜)")
        lines += [f"  - {code(p.name)} — {reason}" for p, reason in selection.skipped[:6]]
    return "\n".join(lines)


def verify(base, root, deadline=DEFAULT_DEADLINE, interval=DEFAULT_INTERVAL, fetcher=None, sleep=None, clock=None,
           now=None, token="run"):
    """-> Result(성공 여부, 건너뜀 여부, 요약 마크다운, 확인한 글). `_posts` 폴더가 없으면 ConfigError."""
    fetcher = fetcher or fetch  # 기본값을 인자 자리에 두면 정의 시점의 함수에 묶여 테스트에서 바꿀 수 없다
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    now = now or datetime.now(timezone.utc)
    config = read_site_config(root)
    tz = site_timezone(config)
    selection = select_newest(root, now, tz)
    sha = (os.environ.get("GITHUB_SHA") or "")[:7]
    for post, reason in selection.skipped:
        log(f"건너뜀: {post.name} ({reason}) — 사이트에 올라오지 않는 글이라 확인 대상이 아닙니다.")
    if not selection.posts:
        log("확인할 공개 글이 없어 건너뜁니다.")
        return Result(True, True, skipped_summary(sha, selection), [])
    posts = selection.posts[:MAX_POSTS]
    log("확인 대상: " + ", ".join(p.name for p in posts)
        + f" (마감 {deadline}초, 시도 사이 대기 {interval}초에서 2배씩 최대 {interval * MAX_GAP_FACTOR}초, "
          f"요청 제한시간 {REQUEST_TIMEOUT}초·요청당 전체 {REQUEST_TOTAL}초)")
    request = Requester(fetcher, clock, deadline)
    tries = 0
    history = []
    first_got_404 = False
    while True:
        tries += 1
        request.attempt = tries
        try:
            att = check_once(base, posts, config, tz, request, f"{token}-{tries}")
        except Exception as exc:  # noqa: BLE001 - 시도 하나의 예상 못 한 오류는 그 시도의 문제로 기록하고 재시도한다(로그·요약에 남는다)
            att = Attempt(False, [], [f"확인 중 예상 못 한 오류({type(exc).__name__})"], [], None, False)
        seconds = int(request.elapsed())
        history.append(attempt_brief(tries, seconds, att))
        if tries == 1:
            first_got_404 = any(res.status == 404 for res in att.results)
        shapes = "·".join(shapes_of(att))
        head = f"시도 {tries}(경과 {seconds}초" + (f", {shapes}" if shapes else "") + ")"
        if att.ok:
            log(f"{head}: 반영 확인 — " + ", ".join(r.url for r in att.results))
            break
        log(f"{head}: " + "; ".join(att.problems))
        gap = wait_after(tries, interval)
        if request.elapsed() + gap >= deadline:  # 다음 시도는 마감 뒤에 시작하게 된다
            break
        sleep(gap)
    if att.ok and first_got_404 and SHAPES[0].label not in shapes_of(att):
        # 첫 시도(정규 주소)의 404 를 CDN 이 보관했을 수 있다. 이 검사는 다른 요청 모양으로 200 을 확인했을 뿐이라 독자에게는
        # 보관이 끝날 때까지 404 일 수 있다.
        att = att._replace(warnings=att.warnings + [
            "시도 1(정규 주소)에서 HTTP 404 를 받았습니다. 공개 CDN 이 404 도 보관하므로(1회 측정으로 최대 약 18분, 불확실) 독자가 정규 "
            f"주소를 열면 보관이 끝날 때까지 404 일 수 있습니다. 이 검사는 시도 {tries}({' · '.join(shapes_of(att))})에서 요청 모양을 "
            "바꿔 HTTP 200 을 확인했습니다."])
    elapsed = int(request.elapsed())
    summary = render_summary(sha, att, selection, posts, tries, elapsed, deadline, att.ok, history)
    return Result(att.ok, False, summary, posts)


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------
def _write_summary(markdown):
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    try:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(markdown.rstrip() + "\n\n")
    except OSError as exc:
        log(f"실행 요약 쓰기 실패(점검 결과에는 영향 없음): {exc}")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=os.environ.get("PAGE_URL", ""))
    parser.add_argument("--root", default=".")
    parser.add_argument("--deadline", type=int, default=DEFAULT_DEADLINE,
                        help="이 초가 지나면 새 시도·새 요청을 시작하지 않는다(0 이면 한 번만 확인)")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help="첫 대기 초(1 이상). 이후 대기는 2배씩 늘어 이 값의 16배까지")
    return parser


def main(argv=None):
    safe_output()
    args = build_parser().parse_args(argv)
    base = args.base.strip()
    if not valid_base(base):
        print("::error::--base(또는 PAGE_URL)는 https:// 로 시작하는 공개 사이트 주소여야 합니다.", flush=True)
        return 2
    if not base.endswith("/"):
        base += "/"
    if args.deadline < 0 or args.interval < 1:
        print("::error::--deadline 은 0 이상, --interval 은 1 이상이어야 합니다.", flush=True)
        return 2
    token = (os.environ.get("GITHUB_SHA") or "run")[:12]
    try:
        result = verify(base, args.root, args.deadline, args.interval, token=token)
    except ConfigError as exc:
        _write_summary(f"### 공개 사이트 반영 확인\n- 결과: **설정 오류** — {fold(exc, 300)}")
        print(f"::error::{fold(exc, 300)}", flush=True)
        return 2
    except Exception as exc:  # noqa: BLE001 - 검사 자체가 예상 못 한 오류로 멈추면 조용히 넘기지 않고 요약·주석을 남기고 빨강으로 끝낸다
        _write_summary(f"### 공개 사이트 반영 확인\n- 결과: **검사 중단** — 예상 못 한 오류({type(exc).__name__}: {code(fold(exc, 200))})")
        print(f"::error::공개 사이트 반영 확인이 예상 못 한 오류로 멈췄습니다({type(exc).__name__}). 실행 로그를 확인하세요.", flush=True)
        return 1
    _write_summary(result.summary)
    if not result.ok:
        print(ERROR_LINE, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
