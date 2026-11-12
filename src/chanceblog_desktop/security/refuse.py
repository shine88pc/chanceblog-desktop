"""본문 속 Secret 형태가 있으면 저장·백업을 멈추는 **공통 거절**(PCSEC1 M3 — 운영자 결정 2026-11-11 4항, 스캐너는 `security/scan.py`).

글에 붙여 넣은 키·토큰 모양(Google API 키·GitHub 토큰·Bearer 토큰·OAuth 토큰·AWS 액세스 키·개인 키)이 발견되면 **아무것도 쓰기 전에** `SECRET_SHAPE_FOUND` 로 멈춘다:
  · 알리는 것은 발견 **위치(칸 이름·줄)와 유형**뿐이다 — 토큰 글자·앞뒤 일부·길이를 문구·세부·`--json`·기록 어디에도 싣지 않는다(`scan.SecretFinding` 에 글 내용이 없다).
  · **기본 동작은 저장·백업 중지**이고 앱은 글을 자동으로 지우거나 바꾸지 않는다. **'무시하고 저장' 선택지는 이 코드 어디에도 없다**(시험이 소스에서 못박는다 — 건너뛰는 인자·환경 변수·설정이 없다).
  · 명령줄은 오류 문구 아래 `참고:` 줄로 칸·유형별 안내(`scan.summarize`)를 보인다(`AppError.notes`).
이 모듈은 스캐너를 **부르기만** 한다 — 모양을 알아보는 규칙은 `security/scan.py` 한 곳에 있다. 호출하는 곳: 옛 명령줄 쓰기 길(원고 제목·본문·후보·네이버 프로필)과 백업 전 검사(글 보관함 백업 `backup`·주제 엔진 백업).
글 보관함 전체를 훑는 `store_findings` 는 **읽기만** 한다(글·판 기록·초안·후보를 `Store` 의 공개 읽기 함수로 읽는다 — 보관함 파일·`Store.backup` 은 건드리지 않는다).
"""
from __future__ import annotations

import re

from ..echo import NUMBER_REF
from ..errors import AppError
from . import scan

LEGACY_KIND = "키·토큰 모양"                       # 여섯 유형 밖의 옛 정본 패턴(`security/mask.has_key_shape`)만 알아본 것 — 유형 이름을 말할 수 없다
_TABLE_NAME = re.compile(r"[a-z_][a-z0-9_]{0,40}")  # 표 이름으로 보여도 되는 모양(앱이 만든 이름) — 그 밖은 '표' 로만 말한다


def place_of(findings):
    """발견 목록 → 위치 한 구절: '본문 3번째 줄' · '본문 3번째 줄 외 2건'. 칸 이름·줄 번호뿐이다."""
    findings = tuple(findings)
    first = findings[0]
    return (f"{first.where} " if first.where else "") + f"{first.line}번째 줄" + (f" 외 {len(findings) - 1}건" if len(findings) > 1 else "")


def kinds_of(findings):
    """발견 목록 → 유형 한 구절: 'GitHub 토큰·Google API 키'(처음 나온 순서, 같은 유형은 한 번)."""
    return "·".join(dict.fromkeys(scan.KIND_LABELS[item.kind] for item in findings))


def secret_shape_error(findings, action="저장"):
    """발견 목록(`scan.SecretFinding` 들, 비어 있지 않다) → `SECRET_SHAPE_FOUND` 오류. 칸·줄·유형만 싣는다. `action` 은 '저장'·'백업' 같은 동작 이름이다."""
    findings = tuple(findings)
    error = AppError("SECRET_SHAPE_FOUND", {"위치": place_of(findings), "유형": kinds_of(findings)})
    error.notes = tuple(scan.summarize(findings, action).splitlines())
    error.findings = findings
    return error


def refuse_secret_shapes(fields, action="저장"):
    """칸 이름 → 글 을 모두 검사해 Secret 형태가 있으면 `SECRET_SHAPE_FOUND` 를 일으킨다(없으면 아무 일도 없다). 글이 아닌 값·None 은 건너뛴다. 쓰기 **전에** 부른다."""
    texts = {name: text for name, text in fields.items() if isinstance(text, str) and text}
    findings = scan.scan_fields(texts) if texts else ()
    if findings:
        raise secret_shape_error(findings, action)


def secret_reason(fields):
    """칸 이름 → 글 을 훑어 Secret 형태가 있으면 **한 줄 사유**(칸 이름·유형만 — 글·줄 번호 없음), 없으면 None. 줄 단위로 거절하는 곳(후보 CSV 가져오기)이 쓴다 — 다른 줄은 계속 처리한다."""
    texts = {name: text for name, text in fields.items() if isinstance(text, str) and text}
    findings = scan.scan_fields(texts) if texts else ()
    if not findings:
        return None
    names = "·".join(dict.fromkeys(item.where for item in findings))
    return f"{names}에 {kinds_of(findings)}처럼 보이는 글이 있어 저장하지 않았습니다 — 그 글을 지운 뒤 다시 가져옵니다"


def text_of(value):
    """칸 값 하나를 검사할 글로 — 글은 그대로, 목록·튜플은 안의 글을 공백으로 이은 글(중첩·dict 의 값 포함), 그 밖은 빈 글."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(part for part in (text_of(item) for item in value) if part)
    return ""


def locate(text, where):
    """글 하나에서 찾은 곳 → `(위치 구절, 유형 구절)`. 여섯 유형이 아무것도 못 찾으면 None(옛 정본 패턴만 알아본 모양일 수 있다 — 부른 쪽이 `LEGACY_KIND` 로 말한다)."""
    found = scan.scan_secrets(text, where)
    return (place_of(found), kinds_of(found)) if found else None


def table_label(name):
    """보관함 표 이름 → 보여 줄 말('후보 표' 꼴). 앱이 만든 이름 모양이 아니면 그냥 '표'."""
    return f"{name} 표" if isinstance(name, str) and _TABLE_NAME.fullmatch(name) else "표"


# ---- 글 보관함 전체 훑기(백업 전 검사) ------------------------------------------------------------------------------------------------------
def ref_label(identifier, position):
    """번호 → 칸 이름에 넣을 짧은 번호(앞 8자가 16진수일 때) — 아니면 순서(`#3`). 키를 번호 자리에 잘못 넣은 보관함도 칸 이름에 글을 싣지 않는다."""
    head = identifier[:8] if isinstance(identifier, str) else ""
    return head if NUMBER_REF.fullmatch(head) else f"#{position}"


def _scan(found, name, text):
    if isinstance(text, str) and text:
        found.extend(scan.scan_secrets(text, name))


def _project_texts(ref, project):
    yield f"글 {ref} 제목", project.title
    yield f"글 {ref} 본문", project.source_content
    yield f"글 {ref} 출처", text_of(list(project.references))
    yield f"글 {ref} 이미지", text_of([[asset.filename, asset.alt] for asset in project.assets])
    for platform, variant in project.variants.items():
        yield f"글 {ref} {platform} 렌더링", variant.rendered
        yield f"글 {ref} {platform} 주소", text_of([variant.published_url, variant.remote_id])


def _old_revision_texts(ref, revision, snapshot):
    yield f"글 {ref} {revision}판 제목", snapshot.title
    yield f"글 {ref} {revision}판 본문", snapshot.source_content
    yield f"글 {ref} {revision}판 출처", text_of(list(snapshot.references))
    yield f"글 {ref} {revision}판 이미지", text_of([[asset.filename, asset.alt] for asset in snapshot.assets])


def _candidate_texts(ref, candidate):
    yield f"후보 {ref} 주제", candidate.topic
    yield f"후보 {ref} 핵심 키워드", candidate.keyword
    yield f"후보 {ref} 보조 키워드", text_of(list(candidate.sub_keywords))
    yield f"후보 {ref} 추천 이유", candidate.reason


def _saved_draft_texts(draft):
    """저장한 초안(`dd-` 번호 — 초안 저장 기능, LOCALSAVE D-373) 한 편을 풀어 `{칸 이름: 글}` 로 — 그 기록은 글칸을 ASCII 로 이스케이프한 JSON 한 줄로 두므로(`\\n`·`\\t`·`\\uXXXX`) 날것 그대로 훑으면
    줄 맨 앞·탭 뒤·한글 바로 뒤의 키 모양이 앞 글자와 붙어 보여 놓친다(독립 검증 D6). `SavedDraft.from_text` 가 풀고, 풀 수 없는 기록(깨졌거나 더 새로운 판)은 None 이다."""
    from ..content import saved_draft
    try:
        record = saved_draft.SavedDraft.from_text(draft.text, draft.project_id)
    except AppError:
        return None
    return {**record.text_fields(), **record.base_fields()}


def _scan_saved_draft(found, number, draft):
    """저장한 초안 한 편을 칸별로 훑는다 — 위치는 '저장한 초안 N번째 · 칸 이름'(줄은 `place_of` 가 붙인다). 풀 수 없는 기록도 날것으로나마 훑는다(죽지 않는다)."""
    fields = _saved_draft_texts(draft)
    if fields is None:
        _scan(found, f"저장한 초안 {number}번째 · 읽을 수 없는 기록", draft.text)
        return
    for name, text in fields.items():
        _scan(found, f"저장한 초안 {number}번째 · {name}", text)


def store_findings(store):
    """글 보관함(`content.store.Store`)의 모든 사용자 글 — 글(제목·본문·출처·이미지·플랫폼별 렌더링·주소)·옛 판 기록·자동 저장 초안·저장한 초안(풀어서 칸별로)·주제 후보 — 을 훑은 발견 목록(없으면 빈 튜플). **읽기만 한다.**
    읽을 수 없는 글(`STORE_CORRUPT` 등)은 건너뛴다 — 백업 자체의 점검(`Store.backup` 의 무결성 검사)이 따로 막는다. 칸 이름은 짧은 번호와 칸 이름뿐이다(글 내용 없음)."""
    found = []
    for position, summary in enumerate(store.list(), start=1):
        ref = ref_label(summary.project_id, position)
        try:
            project = store.load(summary.project_id)
        except AppError:
            continue
        for name, text in _project_texts(ref, project):
            _scan(found, name, text)
        for revision, _saved in store.history(summary.project_id):
            if revision == project.revision:
                continue                                           # 지금 판은 위에서 훑었다(판 기록의 같은 사본)
            try:
                snapshot = store.snapshot(summary.project_id, revision)
            except AppError:
                continue
            for name, text in _old_revision_texts(ref, revision, snapshot):
                _scan(found, name, text)
    from ..content import saved_draft
    saved_number = 0
    for position, draft in enumerate(store.drafts(), start=1):
        if saved_draft.is_draft_id(draft.project_id):                  # 저장한 초안은 풀어서 칸별로(위 `_scan_saved_draft`) — 번호는 저장한 초안끼리만 센다
            saved_number += 1
            _scan_saved_draft(found, saved_number, draft)
            continue
        _scan(found, f"초안 {ref_label(draft.project_id, position)}", draft.text)
    for position, candidate in enumerate(store.list_candidates(), start=1):
        for name, text in _candidate_texts(ref_label(candidate.candidate_id, position), candidate):
            _scan(found, name, text)
    return tuple(found)


def refuse_store_secret_shapes(store, action="백업"):
    """글 보관함에 Secret 형태가 하나라도 있으면 `SECRET_SHAPE_FOUND` — 백업을 만들기 **전에** 부른다(읽기만 한다)."""
    findings = store_findings(store)
    if findings:
        raise secret_shape_error(findings, action)
