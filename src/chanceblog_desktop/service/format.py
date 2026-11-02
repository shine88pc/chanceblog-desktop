"""명령줄에 보여 줄 글(쉬운 한국어) — 서비스 함수의 결과를 줄 목록으로 바꾼다. 화면에 나가기 전에 부르는 쪽(cli)이 모든 줄을 `security.mask` 에 통과시킨다.

영문 약어에는 설명을 붙인다(예: 기록(commit), 올리기(push)). 상태 이름(APPROVED 등)은 한국어 뜻과 함께 보여 준다.
"""
from __future__ import annotations

from ..content import status as st
from ..errors import render
from ..security.mask import safe_detail
from . import naver_flow

CMD = "python -m chanceblog_desktop"
STATUS_KO = {
    st.NOT_STARTED: "시작 전", st.DRAFT_GENERATED: "글 만듦", st.REVIEW_REQUIRED: "검토 중", st.APPROVED: "승인됨", st.COMMITTED: "이 PC 에 기록함(아직 안 올림)",
    st.PUSHED: "올림(공개 확인 전)", st.PUBLISHED: "공개됨", st.DRAFT_SAVED: "초안 저장됨", st.READY_TO_COPY: "복사 준비됨", st.COPY_COMPLETED: "복사함",
    st.PUBLISHED_MANUAL: "직접 발행함", st.PUBLISH_FAILED: "실패",
}
PLATFORM_KO = {"github_pages": "GitHub Pages", "blogger_en": "Blogger 영문", "blogger_ko": "Blogger 한글", "naver_a": "네이버 A", "naver_b": "네이버 B"}
CHECK_MARK = {"ok": "정상", "warn": "주의", "fail": "실패", "skip": "건너뜀"}


def status_text(status):
    return f"{STATUS_KO.get(status, status)} ({status})"


def short_id(project_id):
    return project_id[:8]


def shown_error(error):
    """오류의 화면 문구. 문구 속 상태 이름 자리(현재 상태·요청 상태)는 영어 이름만이 아니라 '승인됨 (APPROVED)' 처럼 한국어 뜻과 함께 보인다."""
    if error.code == "STATUS_TRANSITION_INVALID" and error.slots:
        return render(error.code, {key: status_text(value) if isinstance(value, str) and value in STATUS_KO else value for key, value in error.slots.items()})
    return error.rendered()


def error_lines(error, *, verbose=False):
    """AppError → 코드·원인·하실 일·(다시 시도)·세부. 원인과 하실 일은 TROUBLESHOOTING.md 의 문구 그대로다."""
    shown = shown_error(error)
    lines = [f"오류: {shown.message}", f"  코드: {shown.code}", f"  하실 일: {shown.action}", f"  다시 시도: {shown.retry_text}"]
    detail = " ".join(str(error.detail or "").split())
    if detail:
        if shown.code in ("CHECK_FAILED", "NAVER_SIMILARITY_HIGH"):
            lines.append("  걸린 항목:")
            lines += [f"    - {safe_detail(item, 300)}" for item in str(error.detail).split("; ") if item.strip()]
        else:
            lines.append(f"  세부: {safe_detail(detail, 700)}")
    if verbose:
        lines.append(f"  기록용 한 줄: {error.log_line()}")
    return lines


def project_row_lines(rows):
    if not rows:
        return ["글이 아직 없습니다. `new` 로 만들거나 `import-html` 로 기존 글을 불러옵니다."]
    lines = [f"글 {len(rows)}개"]
    for row in rows:
        if row.error:
            lines.append(f"  [{short_id(row.project_id)}] {row.title} — 읽을 수 없습니다(오류 코드 {row.error})")
            continue
        parts = [f"{PLATFORM_KO[name]}: {STATUS_KO.get(value, value)}" for name, value in row.statuses.items() if value != st.NOT_STARTED]
        lines.append(f"  [{short_id(row.project_id)}] {row.title} (판 {row.revision}) — " + (" · ".join(parts) if parts else "아직 어느 곳에도 내보내지 않았습니다"))
    return lines


def next_step_lines(view):
    pid = short_id(view.project_id)
    lines = []
    for item in view.variants:
        name, status = PLATFORM_KO[item.platform], item.status
        base = CMD
        if item.platform == "github_pages":
            hint = {
                st.DRAFT_GENERATED: f"{base} review {pid} --platform pages --category 분야 --lang ko --image-url https://… (글을 다시 만들어 검토를 시작합니다)",
                st.REVIEW_REQUIRED: f"{base} approve {pid} --platform pages (읽어 보고 올려도 좋으면 승인합니다)",
                st.APPROVED: f"{base} publish-pages {pid} (먼저 미리 보기 — 실제로 올리려면 --yes)",
                st.COMMITTED: f"{base} publish-pages {pid} --yes (이어서 올림) — 올리지 않고 되돌리려면 --cancel --yes",
                st.PUSHED: f"{base} check-deploy {pid} (공개 주소가 열리는지 확인)",
                st.PUBLISH_FAILED: f"{base} review {pid} --platform pages … (글을 다시 만들어 검토·승인합니다)",
            }.get(status)
        else:
            hint = {
                st.DRAFT_GENERATED: f"{base} review {pid} --platform {item.platform} (복사 패키지를 만들어 검토를 시작합니다)",
                st.REVIEW_REQUIRED: f"{base} naver-package {pid} --blog {item.platform} (승인하고 복사용 글을 받습니다)",
                st.READY_TO_COPY: f"{base} naver-package {pid} --blog {item.platform} (복사용 글 다시 보기) — 네이버에 직접 발행한 뒤 naver-done 으로 주소를 기록합니다",
                st.COPY_COMPLETED: f"{base} naver-done {pid} --blog {item.platform} --url https://blog.naver.com/… (발행한 글의 주소를 기록)",
                st.PUBLISH_FAILED: f"{base} review {pid} --platform {item.platform} (패키지를 다시 만듭니다)",
            }.get(status)
        if hint:
            lines.append(f"  {name}: {hint}")
    return lines


def project_lines(view, *, full=False):
    lines = [f"글: {view.title}", f"번호: {view.project_id}  (앞 {len(short_id(view.project_id))}자만 써도 됩니다)", f"판: {view.revision}   만든 때: {view.created_at}   고친 때: {view.updated_at}",
             f"본문: {len(view.source_content)}자   출처 주소: {len(view.references)}개   이미지: {len(view.assets)}개", "상태:"]
    for item in view.variants:
        if item.platform.startswith("blogger") and item.status == st.NOT_STARTED:
            continue                                       # Blogger 는 이 묶음에서 다루지 않는다 — 쓰지 않은 칸은 보이지 않는다
        line = f"  {PLATFORM_KO[item.platform]}: {status_text(item.status)}"
        if item.published_url:
            line += f"  공개 주소: {item.published_url}"
        if item.error_code:
            line += f"  실패 코드: {item.error_code}"
        lines.append(line)
    hints = next_step_lines(view)
    if hints:
        lines += ["다음에 할 일:"] + hints
    elif all(item.status == st.NOT_STARTED for item in view.variants):
        lines += ["다음에 할 일:", f"  {CMD} preview {short_id(view.project_id)} --platform pages --category 분야 --lang ko --image-url https://… (미리 보기)"]
    if full:
        lines += ["", "[본문]", view.source_content.rstrip()]
    return lines


def gate_lines(report):
    if report is None:
        return []
    if report.ok:
        lines = [f"검사: 통과 (본문 {report.chars}자)"]
    else:
        lines = ["검사: 통과하지 못했습니다 — 이대로는 승인·발행할 수 없습니다."] + [f"  - {item}" for item in report.reasons]
    lines += [f"  참고: {item}" for item in report.warnings]
    return lines


def pages_preview_lines(preview, *, full=False):
    lines = ["[GitHub Pages 미리 보기 — 아무 파일도 쓰지 않았습니다]", f"만들 파일(지금 시각 기준): {preview.path}", f"분야: {preview.category}   언어: {preview.lang}   크기: {preview.size_bytes}바이트"]
    lines += [f"공개 주소(예상): {preview.expected_url}" if preview.expected_url else f"공개 주소: {preview.url_note}"]
    lines += gate_lines(preview.gates)
    text = preview.text.rstrip().split("\n")
    shown = text if full else text[:30]
    lines += ["", "[글 내용]"] + shown
    if len(shown) < len(text):
        lines.append(f"… (전체 {len(text)}줄 중 {len(shown)}줄만 보였습니다 — 전체는 --full)")
    return lines


def similarity_lines(report):
    if report is None:
        return []
    label = {"ok": "괜찮음", "warn": "주의", "high": "많이 비슷함 — 직접 승인이 필요합니다"}[report.level]
    lines = [f"두 블로그 비교: 전체 {report.overall:.0%} (본문 {report.body:.0%} · 제목 {report.title:.0%} · 도입부 {report.intro:.0%} · 태그 {report.tags:.0%}) — {label}"]
    return lines + [f"  - {item}" for item in report.reasons]


def naver_item_lines(item, *, full=False):
    package = item.package
    lines = [f"[{PLATFORM_KO[item.key]}] 제목: {package.title}", f"  본문 {package.chars}자 · 문단 {package.paragraphs}개 · 태그: {package.tags_text}" + (f" · 카테고리: {package.category}" if package.category else "")]
    lines += [f"  주의: {note}" for note in package.warnings]
    if full:
        lines += ["", package.body_text.rstrip(), ""]
    return lines


def naver_preview_lines(preview, *, full=False):
    lines = ["[네이버 복사 패키지 미리 보기 — 아무 파일도 쓰지 않았습니다]"]
    for item in preview.items:
        lines += naver_item_lines(item, full=full)
    lines += [f"  프로필이 아직 없는 블로그: {', '.join(PLATFORM_KO[key] for key in preview.missing)} (`naver-profile set` 으로 정합니다)"] if preview.missing else []
    lines += similarity_lines(preview.similarity)
    return lines


def review_lines(result):
    lines = [f"{PLATFORM_KO[result.platform]}: 검토 중으로 보냈습니다. 상태 {status_text(result.status)}"]
    if result.pages is not None:
        lines += pages_preview_lines(result.pages)[1:]
        lines += [f"다음: {CMD} approve {short_id(result.project_id)} --platform pages   (읽어 보고 올려도 좋으면)"]
    if result.naver is not None:
        lines += naver_item_lines(result.naver, full=True) + similarity_lines(result.similarity)
        lines += [f"다음: {CMD} naver-package {short_id(result.project_id)} --blog {result.platform}   (승인하고 복사용 글을 받습니다)"]
    return lines


def approval_lines(result, verb):
    lines = [f"{PLATFORM_KO[result.platform]}: {verb} 상태 {status_text(result.status)}"]
    lines += gate_lines(result.gates) if result.gates is not None else []
    lines += similarity_lines(result.similarity)
    return lines


def naver_issue_lines(issue):
    lines = [f"{PLATFORM_KO[issue.platform]}: 복사용 글입니다. 상태 {status_text(issue.status)}", "아래를 네이버 글쓰기 화면에 직접 붙여 넣어 발행하세요(앱은 네이버에 로그인하거나 글을 대신 올리지 않습니다).", ""]
    lines += similarity_lines(issue.similarity)
    lines += naver_flow.copy_text(issue.package).rstrip().split("\n")
    lines += ["", f"발행한 뒤: {CMD} naver-done {short_id(issue.project_id)} --blog {issue.platform} --url 발행한_글의_주소"]
    return lines


def publish_report_lines(report):
    plan = report.plan
    lines = []
    if report.dry_run:
        lines.append("[GitHub Pages 올리기 미리 보기 — 아직 아무것도 하지 않았습니다]")
    lines += [f"글: {plan.title}", f"지금 상태: {status_text(plan.status)}"]
    if plan.path:
        lines += [f"파일: {plan.path}  ({plan.size_bytes}바이트, 분야 {plan.category}, 언어 {plan.lang})", f"연결한 저장소: {plan.repo}"]
    if plan.expected_url:
        lines.append(f"공개 주소(예상): {plan.expected_url}" if not report.verified else f"공개 주소: {plan.expected_url}")
    lines += gate_lines(plan.gates)
    if report.dry_run:
        lines += ["할 일:"] + [f"  - {item}" for item in plan.actions]
    else:
        lines += ["한 일:"] + [f"  - {item}" for item in report.steps]
        lines.append(f"지금 상태: {status_text(report.status)}")
    if report.pending_verification:
        lines.append("올라갔지만 공개 확인은 아직 끝나지 않았습니다(글은 안전하게 올라가 있습니다).")
    lines += [f"  참고: {item}" for item in report.notes]
    lines += [f"다음: {item}" for item in report.next_steps]
    return lines


def doctor_lines(results):
    lines = ["점검 결과:"]
    for item in results:
        lines.append(f"  [{CHECK_MARK[item.status]}] {item.name} — {item.message}" + (f" (오류 코드 {item.code})" if item.code else ""))
        if item.action:
            lines.append(f"      하실 일: {item.action}")
    failed = sum(1 for item in results if item.status == "fail")
    warned = sum(1 for item in results if item.status == "warn")
    lines.append(f"고쳐야 할 것 {failed}개, 주의 {warned}개." if failed or warned else "모두 정상입니다.")
    return lines
