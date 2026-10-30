"""생성물 게이트: 파싱 → HTML 정화 → 정책·중복 검사.

원칙(fail closed): LLM 출력은 '데이터'이지 명령이 아니다. 형식이 맞지 않거나 하나라도 규칙을
어기면 게시하지 않고 사유를 남긴다. 이 모듈은 네트워크·파일 I/O가 없는 순수 함수만 둔다.
설명: docs/SECURITY_GUARDRAILS.md (G-L*, G-C*)
"""
import html as html_lib
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from html.parser import HTMLParser
from urllib.parse import urlsplit

from pipeline.console import one_line

# 글 언어 검사(check_post)가 지원하는 프로필 language 값. 레지스트리(validate_profile)가 이 밖의 값을 오류로 막는다 —
# 모르는 언어는 언어 검사가 조용히 꺼지기 때문이다.
SUPPORTED_LANGUAGES = ("ko", "en")


class GateError(ValueError):
    """생성물을 형식대로 파싱할 수 없을 때(제목/라벨/내용 누락 등)."""


@dataclass
class GateResult:
    ok: bool
    reasons: list = field(default_factory=list)   # 게시를 막는 사유. "[코드] 설명" 형식
    warnings: list = field(default_factory=list)  # 참고 사항(게시는 막지 않음)

    def codes(self):
        return [r.split("]", 1)[0].lstrip("[") for r in self.reasons if r.startswith("[")]


# ----------------------------------------------------------------------------
# HTML 정화 (허용 목록 방식)
# ----------------------------------------------------------------------------
ALLOWED_TAGS = frozenset({"p", "h2", "h3", "h4", "ul", "ol", "li", "strong", "b", "em", "i", "br", "blockquote"})
VOID_TAGS = frozenset({"br"})
# 내용까지 통째로 버리는 태그(스크립트·임베드·폼 등)
DROP_WITH_CONTENT = frozenset({
    "script", "style", "iframe", "object", "embed", "form", "svg", "math", "noscript",
    "template", "head", "title", "textarea", "select", "button", "canvas", "audio", "video",
})


class _Sanitizer(HTMLParser):
    def __init__(self, allow_links=False, allowed_hosts=()):
        super().__init__(convert_charrefs=True)
        self.allow_links = allow_links
        self.allowed_hosts = tuple(h.lower() for h in allowed_hosts)
        self.out = []
        self.open_tags = []  # 실제로 출력한 열린 태그
        self.skip = []       # 내용째 버리는 태그 스택
        self.stats = {"dropped_blocks": 0, "unwrapped_tags": 0, "links_removed": 0}

    def _href_ok(self, href):
        href = (href or "").strip()
        if not href or re.search(r"[\s\x00-\x1f]", href):
            return False
        try:
            parts = urlsplit(href)
        except ValueError:
            return False
        if parts.scheme != "https" or not parts.netloc:
            return False
        host = (parts.hostname or "").lower()
        if self.allowed_hosts and not any(host == h or host.endswith("." + h) for h in self.allowed_hosts):
            return False
        return True

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in DROP_WITH_CONTENT:
                self.skip.append(tag)
            return
        if tag in DROP_WITH_CONTENT:
            self.skip.append(tag)
            self.stats["dropped_blocks"] += 1
            return
        if tag == "a":
            href = dict(attrs).get("href")
            if self.allow_links and self._href_ok(href):
                self.out.append('<a href="%s" rel="nofollow noopener">' % html_lib.escape(href.strip(), quote=True))
                self.open_tags.append("a")
            else:
                self.stats["links_removed"] += 1
            return
        if tag in ALLOWED_TAGS:
            self.out.append(f"<{tag}>")  # 속성은 전부 버린다
            if tag not in VOID_TAGS:
                self.open_tags.append(tag)
            return
        self.stats["unwrapped_tags"] += 1  # 모르는 태그는 벗기고 텍스트만 남긴다

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag in VOID_TAGS:
            return
        if (tag == "a" or tag in ALLOWED_TAGS) and tag in self.open_tags:
            while self.open_tags:
                top = self.open_tags.pop()
                self.out.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html_lib.escape(data, quote=False))

    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        pass


def sanitize_html(raw_html, allow_links=False, allowed_hosts=()):
    """허용 태그만 남긴 안전한 HTML과 정화 통계를 돌려준다. 모든 속성은 제거된다(a[href] 예외)."""
    parser = _Sanitizer(allow_links=allow_links, allowed_hosts=allowed_hosts)
    parser.feed(raw_html or "")
    parser.close()
    while parser.open_tags:
        parser.out.append(f"</{parser.open_tags.pop()}>")
    return "".join(parser.out).strip(), parser.stats


def plain_text(clean_html):
    """정화된 HTML에서 텍스트를 뽑는다(블록 경계는 줄바꿈). 정화 이후에만 사용할 것."""
    s = re.sub(r"</?(?:p|h[2-4]|ul|ol|li|blockquote)\b[^>]*>|<br\s*/?>", "\n", clean_html or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_lib.unescape(s)
    s = re.sub(r"[ \t\r\f\v\xa0]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s)
    return s.strip()


def text_length(text):
    return len(re.sub(r"\s+", " ", text or "").strip())


# ----------------------------------------------------------------------------
# 파싱
# ----------------------------------------------------------------------------
def strip_code_fences(text):
    text = re.sub(r"^\s*```[a-zA-Z0-9_-]*\s*\n", "", text or "")
    text = re.sub(r"\n\s*```\s*$", "", text)
    return text.replace("```html", "").replace("```", "")


def _clean_title(value):
    value = re.sub(r"[*_`#]+", "", value or "")
    return value.strip().strip("\"'“”‘’「」『』").strip()


# 응답 머리표. 한국어 프롬프트는 '제목:/라벨:/내용:', 영어 프롬프트는 'Title:/Labels:/Content:'로 답하게 한다.
# 한국어 머리표를 먼저 본다 — 한국어 응답의 파싱 결과와 오류 문구는 영어 머리표를 받기 전과 같고, 한국어 머리표가 하나라도
# 온전히 갖춰지지 않았을 때만 영어 머리표를 시도한다. (표시 이름, 정규식 조각, 플래그)
_MARKER_SETS = (
    (("제목", "라벨", "내용"), ("제목", "라벨", "내용"), 0),
    (("Title", "Labels", "Content"), ("Title", "Labels?|Tags?", "Content|Body"), re.IGNORECASE),
)


def _find_sections(text, patterns, flags):
    title_p, labels_p, body_p = patterns
    return (re.search(rf"^\s*(?:{title_p})\s*:\s*(.+?)\s*$", text, re.M | flags),
            re.search(rf"^\s*(?:{labels_p})\s*:\s*(.+?)\s*$", text, re.M | flags),
            re.search(rf"^\s*(?:{body_p})\s*:[ \t]*\n?([\s\S]+)$", text, re.M | flags))


def parse_labeled_post(raw):
    """'제목:/라벨:/내용:'(또는 'Title:/Labels:/Content:') 형식의 응답을 파싱한다. 하나라도 없으면 GateError(기본값으로 채우지 않는다)."""
    text = strip_code_fences(raw).strip()
    if not text:
        raise GateError("응답이 비어 있음")
    closest = None
    for names, patterns, flags in _MARKER_SETS:
        found = _find_sections(text, patterns, flags)
        if all(found):
            m_title, m_labels, m_body = found
            break
        score = sum(1 for m in found if m)
        if closest is None or score > closest[0]:  # 동점이면 먼저 본 한국어 머리표 기준으로 안내한다
            closest = (score, names, found)
    else:
        _, names, found = closest
        missing = [name for name, m in zip(names, found) if not m]
        raise GateError("형식 오류: 누락된 항목 " + ", ".join(missing))
    labels = []
    for item in re.split(r"[,，、#]+", m_labels.group(1)):
        item = item.strip()
        if item and item not in labels:
            labels.append(item)
    title = _clean_title(m_title.group(1))
    body = m_body.group(1).strip()
    if not title or not body:
        raise GateError("형식 오류: 제목 또는 내용이 비어 있음")
    return {"title": title, "labels": labels, "content": body}


# ----------------------------------------------------------------------------
# 유사도(중복 방지)
# ----------------------------------------------------------------------------
def norm_title(value):
    value = re.sub(r"[^\w\s]", " ", (value or "").casefold())
    return re.sub(r"\s+", " ", value).strip()


def similarity(a, b):
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def most_similar(text, candidates):
    """(점수, 후보). 후보가 없으면 (0.0, None)."""
    best_score, best = 0.0, None
    for cand in candidates:
        score = similarity(text, cand)
        if score > best_score:
            best_score, best = score, cand
    return best_score, best


# ----------------------------------------------------------------------------
# 정책·품질 검사
# ----------------------------------------------------------------------------
def _compiled(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns or []]


# 곧은 따옴표·하이픈으로 바꿀 문자(굽은 작은따옴표 U+2018·U+2019, 굽은 큰따옴표 U+201C·U+201D, 특수 하이픈 U+2010·U+2011·U+2013 등).
# 모델은 영어 글에 굽은 따옴표를 자주 쓰는데(don't 의 따옴표가 U+2019), 패턴은 곧은 따옴표(n't)로 쓰므로 맞춰 준다.
_PUNCT_FOLD = str.maketrans({"\u2018": "'", "\u2019": "'", "\u02bc": "'", "\uff07": "'", "\u201c": '"', "\u201d": '"',
                             "\u2010": "-", "\u2011": "-", "\u2013": "-"})


def _normalized(text):
    """금지 목록과 비교하기 전에 글을 고른다(화면에 나가는 글은 바뀌지 않는다).

    ① NFKC: 전각 영문·합자·풀어 쓴 한글 자모를 보통 글자로 합친다. ② 눈에 안 보이는 서식 문자(너비 0 공백·소프트 하이픈·방향 표시 등,
    유니코드 범주 Cf)를 뺀다 — 모델이 낱말 사이에 끼워 넣어도(supple + 너비 0 공백 + ment) 놓치지 않게 한다. ③ 굽은 따옴표·특수 하이픈을 곧은 것으로 바꾼다
    (굽은 따옴표로 쓴 isn't a substitute 가 면책 문장으로 인정되고, 특수 하이픈으로 쓴 weight-loss 가 막히도록). 키릴·그리스 문자로 바꿔치기한 낱말(동형 문자)은
    다루지 않는다 — 이 가드레일은 모델이 흐르는 것을 막는 것이지 일부러 피해 가는 입력을 막는 것이 아니다.
    """
    text = unicodedata.normalize("NFKC", text or "")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf").translate(_PUNCT_FOLD)


def matches_any(patterns, text):
    """text에서 처음 맞는 패턴 문자열을 돌려준다(없으면 None)."""
    text = _normalized(text)
    for raw, rx in zip(patterns or [], _compiled(patterns)):
        if rx.search(text):
            return raw
    return None


def first_match(patterns, text):
    """(패턴, 맞은 낱말). 없으면 (None, None). 사유에 '어떤 낱말이 걸렸는지'를 보여 줄 때 쓴다(재작성 지침이 된다)."""
    text = _normalized(text)
    for raw, rx in zip(patterns or [], _compiled(patterns)):
        found = rx.search(text)
        if found:
            return raw, found.group(0) or raw
    return None, None


def topic_allowed(topic, profile):
    """주제가 금지 주제 패턴에 걸리지 않으면 True."""
    return matches_any(profile.get("banned_topic_patterns"), topic) is None


# ----------------------------------------------------------------------------
# 주제 가드레일(docs/SECURITY_GUARDRAILS.md G-C4). 같은 위험 영역(질병·치료·약·보충제·진단·임신·영유아·체중 감량)을 세 곳에서 막는다.
#   (a) 주제 후보(시드·LLM 확장)  — topic_allowed(): banned_topic_patterns
#   (b) 생성된 제목·라벨          — check_post(): 같은 banned_topic_patterns 를 예외 없이(엄격하게) 적용 → TITLE_TOPIC · LABELS
#   (c) 생성된 본문               — body_risk_hit(): body_banned_patterns, 전문가 상담·면책 절은 body_safe_patterns 로 건너뛴다 → BODY_TOPIC
# 제목·라벨은 짧고 우리가 정하는 자리라 '그 낱말이 있으면 탈락'으로 엄격하게 한다. 본문은 길고, '진단이나 치료를 대신하지 않습니다'
# 같은 안전한 면책·상담 안내 문장에도 위험 낱말이 정상적으로 들어가므로(검사는 append_disclosure 가 붙이기 전이지만 모델이 같은 문장을 쓸 수 있다)
# 낱말 목록을 '단정·조언 문맥'에만 건다: ① 일상어와 겹치는 낱말(treat·heal·remedy 같은 것)은 본문 목록에서 빼거나 의료 문맥으로 좁히고,
# ② 전문가 상담 안내·'의학적 조언이 아님' 구절은 건너뛴다. 효능 단정(완치·기적·부작용 없음 등)은 이 예외 없이
# banned_patterns 가 제목·본문 전체에 따로 건다. 오탐으로 모든 글이 탈락하면(재시도 3회 → ALL_REJECTED) 하루 발행을 잃으므로 이 구분이 필요하다.
#
# 면제는 '문장'이 아니라 '절' 단위다. "마그네슘 보충제가 잠에 도움이 될 수 있지만 먼저 의사와 상담하세요"처럼 위험한 권유 뒤에 상담 구절을 붙인
# 문장이 통째로 면제되면 안 되기 때문이다(D-64 ⑥ a). 문장을 문장부호(; : — -- 띄어 쓴 하이픈)와 프로필의 body_clause_split_patterns(영어 ', but'·', so'·
# '지만' 같은 접속어)에서 절로 더 쪼개고, 상담 구절이 없는 절은 따로 검사한다. 또 body_safe_veto_patterns(용량 같은 것)에 맞는 절은 상담 구절이
# 있어도 면제하지 않는다. 접속어는 앞뒤의 쉼표가 있든 없든("…may lower your blood pressure so ask your doctor"·"…, therefore, ask your doctor") 바로 뒤에 상담 구절이
# (도입구 'you might want to'·'people should'나 상담 부사가 끼어도) 올 때 가른다(D-64 ⑦ N-1, ⑧ N2-1·N2-4). 한국어 '~에 대해서'·'~위해서'처럼 후치사로 쓰인 '~서'는 접속 어미가
# 아니라서 가르지 않는다(⑧ N2-3). 접속어 없이 쉼표로만 이은 경우("…를 챙기세요, 의사와 상담한 뒤에")는 여전히 면제된다 — 'If you are pregnant, talk to your doctor'와
# 구별할 수 없는 알려진 한계다.
# ----------------------------------------------------------------------------
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|\n+")
# 모든 언어에 공통인 절 경계: ; : — ― 줄표(--)와 양쪽에 공백이 있는 하이픈(엔 대시는 비교 전에 하이픈으로 바뀐다). 낱말 안의 하이픈(high-dose)은 가르지 않는다
_CLAUSE_PUNCTUATION = r"\s*[;:—―]\s*|\s*-{2,}\s*|\s+-\s+"


def _clause_splitter(profile):
    """절 경계 정규식 목록: 공통 문장부호 + 프로필의 body_clause_split_patterns. 패턴마다 따로 컴파일한다 — `(?:p1)|(?:p2)`로 합치면
    `(?i)` 같은 전역 플래그는 앞 패턴 뒤에서 오류가 되고, 같은 이름의 묶음·역참조 번호는 다른 패턴과 얽힌다. 레지스트리는 패턴을 하나씩
    컴파일해 검사하므로, 합치면 검증을 통과한 설정이 실행 중에 re.error 로 터질 수 있다(D-64 ⑦ N-4)."""
    parts = [_CLAUSE_PUNCTUATION] + [p for p in (profile.get("body_clause_split_patterns") or []) if isinstance(p, str)]
    return [re.compile(p, re.IGNORECASE) for p in parts]


def _split_clauses(sentence, splitters):
    """문장을 절 경계에서 자른다. 경계는 패턴마다 따로 찾고 겹치거나 맞닿은 것은 하나로 합친다. re.split 은 패턴 안의 묶음 괄호 내용까지
    조각으로 돌려주므로 경계 위치만 써서 직접 자른다."""
    spans = sorted((m.start(), m.end()) for rx in splitters for m in rx.finditer(sentence) if m.end() > m.start())  # 길이 0 경계는 무시(레지스트리가 막지만 방어한다)
    merged = []
    for begin, end in spans:
        if merged and begin <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([begin, end])
    pieces, start = [], 0
    for begin, end in merged:
        pieces.append(sentence[start:begin])
        start = end
    pieces.append(sentence[start:])
    return pieces


def body_risk_hit(text, profile):
    """본문(정화된 글의 텍스트)에서 위험 표현을 찾는다 → (패턴, 맞은 낱말) 또는 (None, None).

    body_banned_patterns 가 없으면 검사하지 않는다. 문장을 절로 나눠 절마다 보고, body_safe_patterns 에 맞는 절
    (전문가 상담 안내·'의학적 조언이 아님' 면책)은 위험 낱말이 있어도 건너뛴다. 다만 body_safe_veto_patterns 에도 맞는 절은 건너뛰지 않는다.
    """
    patterns = profile.get("body_banned_patterns")
    if not patterns:
        return None, None
    banned = list(zip(patterns, _compiled(patterns)))
    safe = _compiled(profile.get("body_safe_patterns"))
    veto = _compiled(profile.get("body_safe_veto_patterns"))
    splitter = _clause_splitter(profile)
    for sentence in _SENTENCE_SPLIT.split(_normalized(text)):
        for clause in _split_clauses(sentence, splitter):
            if not clause.strip():
                continue
            if any(rx.search(clause) for rx in safe) and not any(rx.search(clause) for rx in veto):
                continue
            for raw, rx in banned:
                found = rx.search(clause)
                if found:
                    return raw, found.group(0) or raw
    return None, None


def check_post(post, profile, recent_titles=(), other_titles=(), sanitize_stats=None):
    """정화된 post({title, labels, content})를 프로필 기준으로 검사한다."""
    reasons, warnings = [], []
    title = post.get("title", "")
    content = post.get("content", "")
    labels = post.get("labels", [])
    text = plain_text(content)
    n = text_length(text)

    t_cfg = profile.get("title", {})
    if not t_cfg.get("min_chars", 1) <= len(title) <= t_cfg.get("max_chars", 200):
        reasons.append(f"[TITLE_LEN] 제목 길이 {len(title)}자 (허용 {t_cfg.get('min_chars')}~{t_cfg.get('max_chars')}자)")
    hit = matches_any(profile.get("title_banned_patterns"), title)
    if hit:
        reasons.append(f"[TITLE_BANNED] 자극적/금지 제목 표현: {hit}")
    raw, word = first_match(profile.get("banned_topic_patterns"), title)
    if raw is not None:  # 주제 가드레일 (b): 주제 후보와 같은 목록을 제목에도 예외 없이 건다
        reasons.append("[TITLE_TOPIC] 제목에 금지 주제 낱말(질병·치료·약·보충제·진단·임신·영유아·체중 감량 등)이 있음: "
                       f"'{one_line(word, 40)}'")

    l_cfg = profile.get("length", {})
    if n < l_cfg.get("min_chars", 0):
        reasons.append(f"[LEN_SHORT] 본문 {n}자 (최소 {l_cfg['min_chars']}자)")
    if n > l_cfg.get("max_chars", 10 ** 9):
        reasons.append(f"[LEN_LONG] 본문 {n}자 (최대 {l_cfg['max_chars']}자)")

    if profile.get("language") == "ko":
        letters = re.findall(r"[A-Za-z가-힣]", text)
        hangul = re.findall(r"[가-힣]", text)
        ratio = (len(hangul) / len(letters)) if letters else 0.0
        if ratio < profile.get("min_hangul_ratio", 0.5):
            reasons.append(f"[LANG] 한글 비율 {ratio:.0%} (최소 {profile.get('min_hangul_ratio', 0.5):.0%})")
    elif profile.get("language") == "en":
        # 글자(숫자·기호 제외) 중 라틴 문자(기본 라틴~라틴 확장-B: é·ñ 포함)의 비율. 한글·한자·키릴 문자가 섞이면 낮아진다.
        letters = [ch for ch in text if ch.isalpha()]
        latin = [ch for ch in letters if ord(ch) < 0x250]
        ratio = (len(latin) / len(letters)) if letters else 0.0
        min_ratio = profile.get("min_latin_ratio", 0.9)
        if ratio < min_ratio:
            reasons.append(f"[LANG] 라틴 문자 비율 {ratio:.0%} (최소 {min_ratio:.0%})")
        if any(ch.isalpha() and ord(ch) >= 0x250 for ch in title):
            reasons.append("[LANG] 제목에 영어(라틴 문자)가 아닌 글자가 있음")

    s_cfg = profile.get("structure", {})
    h3_count = len(re.findall(r"<h[23]>", content))
    if h3_count < s_cfg.get("min_h3", 0):
        reasons.append(f"[STRUCT_H3] 소제목 {h3_count}개 (최소 {s_cfg['min_h3']}개)")
    if s_cfg.get("require_list") and not re.search(r"<(?:ul|ol)>", content):
        reasons.append("[STRUCT_LIST] 체크리스트/목록이 없음")

    hit = matches_any(profile.get("banned_patterns"), title + "\n" + text)
    if hit:
        reasons.append(f"[BANNED] 금지 표현(과장·의학적 단정): {hit}")
    hit = matches_any(profile.get("leak_patterns"), title + "\n" + text)
    if hit:
        reasons.append(f"[LEAK] 프롬프트/AI 메타 문구·마크다운 잔여물: {hit}")
    raw, word = body_risk_hit(text, profile)
    if raw is not None:  # 주제 가드레일 (c): 본문 — 전문가 상담·면책 문장은 건너뛰고 나머지에서 위험 표현을 찾는다
        reasons.append("[BODY_TOPIC] 본문에 질병·치료·약·보충제·진단·임신·영유아·체중 감량 관련 표현이 있음: "
                       f"'{one_line(word, 40)}' — 그 문장을 빼고 일상 습관 팁만 쓴다(전문가 상담 안내 문장은 괜찮다)")

    lab_cfg = profile.get("labels", {})
    if not lab_cfg.get("min", 1) <= len(labels) <= lab_cfg.get("max", 5):
        reasons.append(f"[LABELS] 라벨 {len(labels)}개 (허용 {lab_cfg.get('min', 1)}~{lab_cfg.get('max', 5)}개)")
    elif any(len(x) > lab_cfg.get("max_chars", 20) for x in labels):
        reasons.append("[LABELS] 너무 긴 라벨이 있음")
    banned_label = next((x for x in labels if not topic_allowed(x, profile)), None)
    if banned_label is not None:  # 주제 가드레일 (b): 라벨. 어떤 라벨이 걸렸는지 알려 줘야 모델이 그 라벨만 바꾼다
        reasons.append(f"[LABELS] 금지 주제 라벨이 있음: '{one_line(banned_label, 30)}'")

    # 비교 대상 제목은 이력 파일에서 온 문자열이다(다른 블로그 이력의 제목은 피드·LLM 유래). 사유는 로그·실행 요약·이력·
    # 재작성 프롬프트에 그대로 들어가므로 개행·'::' 가 섞이지 않게 한 줄로 접어 넣는다.
    sim = profile.get("similarity", {})
    score, other = most_similar(title, recent_titles)
    if score >= sim.get("same_blog", 1.1):
        reasons.append(f"[DUP_SAME] 이 블로그의 기존 글과 제목이 비슷함({score:.2f}): {one_line(other, 100)}")
    score, other = most_similar(title, other_titles)
    if score >= sim.get("other_blogs", 1.1):
        reasons.append(f"[DUP_OTHER] 다른 블로그 글과 제목이 비슷함({score:.2f}): {one_line(other, 100)}")

    if sanitize_stats:
        removed = {k: v for k, v in sanitize_stats.items() if v}
        if removed:
            warnings.append(f"[SANITIZED] HTML 정화로 제거됨: {removed}")
    return GateResult(ok=not reasons, reasons=reasons, warnings=warnings)


def append_disclosure(clean_html, profile):
    """프로필의 AI 사용·면책 문구를 본문 뒤에 붙인다(작성자가 빼먹을 수 없게 게시 직전에 붙인다)."""
    block = (profile.get("disclosure_html") or "").strip()
    return f"{clean_html}\n{block}" if block else clean_html
