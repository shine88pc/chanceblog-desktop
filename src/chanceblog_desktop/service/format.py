"""명령줄에 보여 줄 글(쉬운 한국어) — 서비스 함수의 결과를 줄 목록으로 바꾼다. 화면에 나가기 전에 부르는 쪽(cli)이 모든 줄을 `security.mask` 에 통과시킨다.

영문 약어에는 설명을 붙인다(예: 기록(commit), 올리기(push)). 상태 이름(APPROVED 등)은 한국어 뜻과 함께 보여 준다.
"""
from __future__ import annotations

from ..content import candidates as cd
from ..content import draft_plan as dp
from ..content import status as st
from ..content import suggest as sg
from ..content.profiles import NaverProfile
from ..errors import AppError, render
from ..security.mask import safe_detail
from . import connections, naver_flow
from .candidates import DELETE_PREFIX, MAX_ORDINAL_DIGITS, kst

CMD = "python -m chanceblog_desktop"
HAND_WRITTEN_FIELDS = ("profile_fit", "priority", "keyword_opportunity")              # 사람이 적거나 CSV 로 가져온 점수 칸 — 제안·우선도 계산에는 쓰이지 않는다
HAND_WRITTEN = "(이전에 적어 둔 값 — 아래 계산값과 따로이고 계산에는 쓰이지 않습니다)"
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


# ---- 주제 후보 -------------------------------------------------------------------------------------------------------------------
LISTED_NOTES = 30                       # 가져오기 결과에서 건너뜀·거절을 줄마다 보이는 최대 수(전체는 --json)
EMPTY_HINT = "`candidates add` 로 직접 적거나 `candidates import-csv 파일` 로 가져옵니다."
METRIC_UNITS = {"search_demand": "{:,}회", "related_blog_results": "{:,}건", "mobile_share": "{}%"}


def blogs_text(blogs):
    return ", ".join(PLATFORM_KO[blog] for blog in blogs)


def candidate_status_text(candidate):
    """상태의 한국어 이름 — '선택됨' 이면 어느 블로그용으로 골랐는지도(영문 상태 코드는 보이지 않는다)."""
    name = cd.STATUS_KO[candidate.status]
    if candidate.status == cd.SELECTED and candidate.selections:
        return f"{name}({blogs_text(candidate.selected_blogs)})"
    return name


def metric_text(name, value):
    if value is None:
        return "데이터 없음"
    if name == "seasonality":
        return "·".join(f"{month}월" for month in value)
    if name == "duplicate":
        return "예" if value else "아니오"
    return METRIC_UNITS.get(name, "{}").format(value)


def local_time(stamp):
    """저장된 시각(UTC) → 한국 시간의 `2026-11-02 12:00`(저장은 UTC 그대로이고 화면만 한국 시간이다)."""
    return kst(stamp).strftime("%Y-%m-%d %H:%M")


def candidate_ref(row):
    """`[3] 주제 (번호 1a2b3c4d)` — 순번은 지우면 뒤가 당겨져 바뀔 수 있어, 바뀌지 않는 번호 앞 8자를 함께 보인다."""
    return f"[{row.ordinal}] {row.candidate.topic} (번호 {cd.short_id(row.candidate.candidate_id)})"


def candidate_line(row, *, verbose=False):
    candidate = row.candidate
    line = f"  [{row.ordinal}] {candidate_status_text(candidate)} — {candidate.topic} · 핵심 키워드: {candidate.keyword} · 대상: {blogs_text(candidate.blogs)}"
    if candidate.project_id:
        line += " · 글 연결됨"
    return line + f" · 번호 {candidate.candidate_id if verbose else cd.short_id(candidate.candidate_id)}"


def candidate_list_lines(result, *, verbose=False, assessments=None, notes=()):
    if result.total == 0:
        if result.store_state != "ready":
            return ["아직 후보가 없습니다(쓰는 명령을 처음 실행하면 보관함이 올라갑니다). " + EMPTY_HINT]
        return ["아직 후보가 없습니다. " + EMPTY_HINT]
    filters = [item for item in (f"상태: {cd.STATUS_KO[result.status]}" if result.status else "", f"블로그: {PLATFORM_KO[result.blog]}" if result.blog else "") if item]
    if not result.rows:
        return [f"조건에 맞는 후보가 없습니다(전체 {result.total}개 — {' · '.join(filters)})."]
    head = f"주제 후보 {len(result.rows)}개" + (f"(전체 {result.total}개 중 — {' · '.join(filters)})" if filters else "")
    lines = [head] + [candidate_line(row, verbose=verbose) + ("" if assessments is None else priority_suffix(assessments[row.candidate.candidate_id])) for row in result.rows]
    if assessments is not None:
        lines.append("우선도는 보관함에 저장된 값이 아니라 프로필·기존 글·달력(가져온 지표가 있으면 함께)으로 지금 계산한 작성 순서의 참고값입니다 — 이유는 `candidates show 순번` 에 있습니다.")
        lines += [f"참고: {note}" for note in notes]
    lines.append(f"자세히 보려면 `{CMD} candidates show 순번` (순번은 전체 목록 기준이고, 후보를 지우면 뒤의 순번이 하나씩 당겨집니다).")
    lines.append(f"지울 때는 순번이 아니라 번호 앞 {DELETE_PREFIX}자를 씁니다: `{CMD} candidates delete 번호 --yes`.")
    if any(row.ordinal >= 10 ** MAX_ORDINAL_DIGITS for row in result.rows):
        lines.append(f"순번 {10 ** MAX_ORDINAL_DIGITS} 이상은 순번으로 고를 수 없습니다 — 그 후보들은 번호 앞 {DELETE_PREFIX}자로 고릅니다(예: `{CMD} candidates show 번호`).")
    return lines


def candidate_next_lines(row):
    candidate, number = row.candidate, row.ordinal
    base = f"{CMD} candidates"
    if candidate.status == cd.REJECTED:
        return [f"  다음: `{base} restore {number}` 로 검토 중으로 되살릴 수 있습니다."]
    lines = []
    if candidate.status != cd.SELECTED:
        lines.append(f"  다음: `{base} select {number} --blog 블로그` 로 고르거나 `{base} hold {number}`(보류)·`{base} reject {number}`(제외) 합니다.")
    elif not candidate.project_id:
        lines.append(f"  다음: `{base} link {number} 글번호` 로 쓰고 있는 글과 이을 수 있습니다.")
    return lines


def candidate_show_lines(result, *, verbose=False, assessment=None, notes=()):
    row = result.row
    candidate = row.candidate
    number = candidate.candidate_id if verbose else cd.short_id(candidate.candidate_id)
    lines = [f"후보 [{row.ordinal}]: {candidate.topic}", f"  번호: {number}   (순번은 후보를 지우면 바뀔 수 있고 번호는 바뀌지 않습니다)", f"  상태: {candidate_status_text(candidate)}",
             f"  {cd.LABELS['keyword']}: {candidate.keyword}"]
    if candidate.sub_keywords:
        lines.append(f"  {cd.LABELS['sub_keywords']}: {', '.join(candidate.sub_keywords)}")
    lines += [f"  {cd.LABELS['blogs']}: {blogs_text(candidate.blogs)}", f"  {cd.LABELS['post_type']}: {candidate.post_type}"]
    if candidate.reason:
        lines.append(f"  {cd.LABELS['reason']}: {candidate.reason}")
    if candidate.has_data():
        lines.append(f"  지표({cd.LABELS['data_date']} {candidate.data_date}):")
        lines += [f"    {cd.LABELS[name]}: {metric_text(name, getattr(candidate, name))}" + (HAND_WRITTEN if name in HAND_WRITTEN_FIELDS and getattr(candidate, name) is not None else "") for name in cd.METRIC_FIELDS]
    else:
        lines.append("  지표: 데이터 없음")
    if assessment is not None:
        lines += assessment_lines(assessment, notes)
    for blog, stamp in candidate.selections:
        lines.append(f"  {PLATFORM_KO[blog]} 용으로 고른 때: {local_time(stamp)}")
    project = result.project
    if project is not None:
        if project.error:
            lines.append(f"  연결한 글: 읽을 수 없습니다(오류 코드 {project.error}, 글번호 {short_id(project.project_id)})")
        else:
            states = " · ".join(f"{PLATFORM_KO[name]}: {STATUS_KO.get(value, value)}" for name, value in project.statuses)
            lines.append(f"  연결한 글: {project.title}(글번호 {short_id(project.project_id)})" + (f" — {states}" if states else " — 아직 어느 곳에도 내보내지 않았습니다"))
    lines.append(f"  만든 때: {local_time(candidate.created_at)}   고친 때: {local_time(candidate.updated_at)}   (한국 시간)")
    if verbose:
        lines.append(f"  판: {candidate.revision}")
    return lines + candidate_next_lines(row)


def candidate_add_lines(result):
    if result.row is None:
        return [f"같은 핵심 키워드·주제·블로그의 후보가 이미 있어 추가하지 않았습니다(순번 {result.twin.ordinal}).", candidate_line(result.twin)]
    return ["후보를 추가했습니다.", candidate_line(result.row)] + candidate_next_lines(result.row)


def candidate_move_lines(result, verb):
    after = result.row.candidate
    return [f"{verb}: {candidate_ref(result.row)} — {cd.STATUS_KO[result.before]} → {cd.STATUS_KO[after.status]}"] + candidate_next_lines(result.row)


def candidate_select_lines(result):
    after = result.row.candidate
    blog = PLATFORM_KO[result.blog]
    if result.again:
        lines = [f"{blog} 용으로도 골랐습니다: {candidate_ref(result.row)} — 이미 선택됨이어서 선택 기록만 더했습니다"]
    else:
        lines = [f"{blog} 용으로 골랐습니다: {candidate_ref(result.row)} — {cd.STATUS_KO[result.before]} → {cd.STATUS_KO[after.status]}"]
    for item in result.warnings:
        lines.append(f"주의: 같은 핵심 키워드 「{after.keyword}」 을(를) {PLATFORM_KO[item.blog]} 용으로 {item.days_ago}일 전({kst(item.picked_at).strftime('%Y-%m-%d')})에 이미 골랐습니다"
                     f"(순번 {item.other.ordinal}: {item.other.candidate.topic}, 번호 {cd.short_id(item.other.candidate.candidate_id)}). 이 블로그의 같은 주제 재사용 기준은 {item.days}일입니다 — 선택은 그대로 기록했습니다.")
    if result.outside:
        lines.append(f"참고: {blog} 은(는) 이 후보의 추천 대상 블로그({blogs_text(after.blogs)})가 아니지만 요청대로 기록했습니다.")
    return lines + candidate_next_lines(result.row)


def candidate_delete_lines(result):
    where = f"[{result.ordinal}] " if result.ordinal is not None else ""
    number = cd.short_id(result.candidate_id)
    shown = f"{result.topic} (번호 {number})" if result.topic else f"번호 {number}"
    return [f"후보를 지웠습니다: {where}{shown}", "  연결한 글이 있었다면 글은 그대로 남아 있습니다.", "  뒤의 후보들은 순번이 하나씩 당겨졌을 수 있습니다 — `candidates list` 로 다시 확인합니다."]


def candidate_link_lines(result, *, unlinking=False):
    row = result.row
    if unlinking:
        if not result.changed:
            return [f"이어진 글이 없어 바뀐 것이 없습니다: {candidate_ref(row)}"]
        return [f"연결을 끊었습니다(글은 그대로입니다): {candidate_ref(row)}"]
    project = result.project
    shown = f"{project.title}(글번호 {short_id(project.project_id)})" if project is not None and not project.error else f"글번호 {short_id(row.candidate.project_id)}"
    if not result.changed:
        return [f"이미 같은 글과 이어져 있습니다: {candidate_ref(row)} ↔ {shown}"]
    lines = [f"후보와 글을 이었습니다: {candidate_ref(row)} ↔ {shown}"]
    if result.previous:
        lines.append(f"  전에는 다른 글(글번호 {short_id(result.previous)})과 이어져 있었습니다 — 새 글로 바꿨습니다.")
    return lines


def _ranges(numbers):
    """12 13 14 17 → '12~14, 17'."""
    groups = []
    for number in sorted(numbers):
        if groups and number == groups[-1][1] + 1:
            groups[-1][1] = number
        else:
            groups.append([number, number])
    return ", ".join(str(low) if low == high else f"{low}~{high}" for low, high in groups)


def candidate_import_lines(result):
    lines = [f"가져오기를 마쳤습니다: {result.file}", result.summary()]
    if result.added:
        lines.append(f"  추가한 후보(순번): {_ranges([row.ordinal for row in result.added])}")
    for label, notes in (("건너뜀", result.skipped), ("거절", result.rejected)):
        lines += [f"  {label}: 줄 {note.line} — {note.reason}" for note in notes[:LISTED_NOTES]]
        if len(notes) > LISTED_NOTES:
            lines.append(f"  {label}: … 외 {len(notes) - LISTED_NOTES}개(전체는 --json)")
    if result.unknown_columns:
        lines.append(f"모르는 열 {len(result.unknown_columns)}개는 무시했습니다: {', '.join(result.unknown_columns[:10])}")
    if result.blank_lines:
        lines.append(f"빈 줄 {result.blank_lines}개는 무시했습니다.")
    if result.rejected:
        lines.append("일부 줄을 거절했습니다 — 이유를 고쳐 같은 파일을 다시 가져오면 이미 들어간 줄은 건너뜁니다(겹치지 않습니다).")
    return lines


# ---- 작성 기반(draft plan) -------------------------------------------------------------------------------------------------------------------
SOURCE_ITEMS = {
    "post_type": "글 유형", "audience": "대상 독자", "tone": "문체", "length": "글 길이", "subheadings": "소제목 수", "title_limit": "제목 길이 상한", "tag_limit": "태그 수 상한",
    "paragraph": "문단 길이", "intro_style": "도입부 방식", "difficulty": "설명 난이도", "ending_style": "마무리 방식", "category": "카테고리", "tags": "태그", "title_direction": "제목 방향",
    "conclusion": "결론", "intent": "예상 검색 의도", "outline": "권장 목차", "titles": "제목 후보", "cautions": "주의사항", "topic": "추천 주제", "keyword": "핵심 키워드", "sub_keywords": "보조 키워드",
}


def draft_plan_lines(result, *, verbose=False):
    """작성 기반을 사람이 읽는 줄로. 값이 어느 층에서 왔는지는 `--verbose`(와 `--json`)에서만 보인다."""
    plan, row = result.plan, result.row
    lines = [f"작성 기반 — 후보 [{row.ordinal}] {plan.topic} · {PLATFORM_KO[plan.blog]} 용 · 기준 날짜 {plan.base_date} (계획만 보여 주고 아무것도 저장하지 않았습니다)"]
    lines += [f"  글 유형: {plan.post_type}   글 길이 목표: {dp.length_korean(plan.length)}", f"  예상 검색 의도: {plan.intent}", f"  대상 독자: {plan.audience}", f"  핵심 키워드: {plan.keyword}" + (f"   보조 키워드: {', '.join(plan.sub_keywords)}" if plan.sub_keywords else "")]
    if plan.replaced:
        lines.append(f"  ※ 후보의 ‘{plan.replaced[0]}’ 형식은 ‘{plan.replaced[1]}’{dp.particle(plan.replaced[1], '으로', '로')} 바꿔 구성했습니다(경험을 지어내지 않습니다).")
    lines += ["제목 후보:"] + [f"  {number}. {title}" for number, title in enumerate(plan.titles, 1)]
    lines += ["본문 작성 방향:"] + [f"  - {label}: {text}" for label, text in plan.direction]
    lines.append("권장 목차와 소제목:")
    lines += [f"  {number}. {name} — {heading}" for number, (name, heading) in enumerate(zip(plan.outline, plan.subheadings), 1)]
    lines += ["포함할 핵심 내용:"] + [f"  - {text}" for text in plan.key_points]
    lines += ["주의사항:"] + [f"  - {text}" for text in plan.cautions]
    lines.append(f"추천 카테고리: {plan.category or '정하지 못했습니다'}")
    lines.append("추천 태그: " + (" ".join("#" + tag for tag in plan.tags) if plan.tags else "없음"))
    if plan.references:
        lines += ["참고할 수 있는 공개 자료(입력한 주소만 — 앱은 열어 보거나 가져오지 않았습니다):"] + [f"  - {url}" for url in plan.references]
    else:
        lines.append("참고할 수 있는 공개 자료: 입력한 주소가 없습니다(앱이 자료를 찾아 주지는 않습니다)")
    lines += ["확인 권장(있어도 계획은 이대로 쓸 수 있습니다):"] + [f"  - {text}" for text in plan.checks]
    for note in result.notes:
        lines.append(f"참고: {note}")
    if result.comparison is not None:
        lines.append(f"다른 네이버 블로그({PLATFORM_KO[result.other_blog]}) 용 계획과 견줘 봤습니다.")
        lines += similarity_lines(result.comparison.report)
    if verbose:
        lines.append("값이 온 곳(적용 순서: " + " → ".join(dp.LAYER_KO[layer] for layer in dp.LAYERS) + ", 글 유형만 사용자 → 후보 → 프로필 → 기본값):")
        lines += [f"  - {SOURCE_ITEMS.get(item, item)}: {dp.LAYER_KO[layer]}" for item, layer in plan.sources]
    return lines


# ---- 네이버 프로필의 '글 만들 때 쓰는 항목' ------------------------------------------------------------------------------------------------
def _option_pairs(profile, base):
    """(항목 이름, 바꾼 값의 글)을 화면 순서대로 — 기본값에서 바꾸지 않았으면 글이 ''."""
    def changed(*names):
        return any(getattr(profile, name) != getattr(base, name) for name in names)

    reuse = f"{profile.topic_reuse_days}일" + ("(경고하지 않음)" if profile.topic_reuse_days == 0 else "")
    return (
        ("도입부 스타일", profile.intro_style if changed("intro_style") else ""),
        ("소제목 수", f"{profile.subheading_min}~{profile.subheading_max}개" if changed("subheading_min", "subheading_max") else ""),
        ("설명 난이도", profile.difficulty if changed("difficulty") else ""),
        ("마무리 방식", profile.ending_style if changed("ending_style") else ""),
        ("제외 주제", ", ".join(profile.excluded_topics) if changed("excluded_topics") else ""),
        ("같은 주제 재사용 기준", reuse if changed("topic_reuse_days") else ""),
        ("기본 글 유형", profile.post_type if changed("post_type") else ""),
    )


def profile_option_lines(raw):
    """저장된 프로필 한 개의 '글 만들 때 쓰는 항목' 줄들 — 하나라도 기본값에서 바꿨으면 항목마다 한 줄(바꾸지 않은 것은 '기본값'). 하나도 안 바꿨으면 줄을 더하지 않는다 —
    이 항목을 쓰지 않는 프로필의 `show` 출력은 예전과 한 글자도 다르지 않다."""
    try:
        profile = NaverProfile.from_dict(raw)
    except AppError:
        return ["  글 만들 때 쓰는 항목: 읽을 수 없습니다(저장된 값이 올바르지 않습니다 — `naver-profile set` 으로 다시 정합니다)"]
    base = NaverProfile(profile.key, profile.display_name, profile.blog_url)
    pairs = _option_pairs(profile, base)
    if not any(value for _name, value in pairs):
        return []
    defaults = {"도입부 스타일": "정하지 않음", "소제목 수": f"{base.subheading_min}~{base.subheading_max}개", "설명 난이도": "정하지 않음", "마무리 방식": "정하지 않음", "제외 주제": "없음",
                "같은 주제 재사용 기준": f"{base.topic_reuse_days}일", "기본 글 유형": base.post_type}
    return ["  글 만들 때 쓰는 항목:"] + [f"    {name}: {value or '기본값(' + defaults[name] + ')'}" for name, value in pairs]


def profile_saved_options_text(profile):
    """`naver-profile set` 으로 저장한 프로필에서 기본값과 다른 항목들(없으면 '')."""
    base = NaverProfile(profile.key, profile.display_name, profile.blog_url)
    return " · ".join(f"{name} {value}" for name, value in _option_pairs(profile, base) if value)


# ---- 연결 설정(keys) ---------------------------------------------------------------------------------------------------------------
def _limit_text(provider):
    """제공자의 한도 한 줄 — 모르면 '한도를 확인하지 못했습니다'. 서비스 콘솔의 월 한도(`console_limit`)를 아는 제공자는 뒤에 참고로 붙인다."""
    parts = []
    for tier, windows in provider.tiers:
        if windows:
            text = " · ".join(f"{'하루' if window.kind == 'day' else '이번 달' if window.kind == 'month' else f'최근 {window.minutes}분'} {window.limit:,}회" for window in windows)
            parts.append(text if len(provider.tiers) == 1 else f"{tier} 등급 {text}")
    if not parts:
        return "한도를 확인하지 못했습니다(한도 오류 응답으로만 감지합니다)"
    return ", ".join(parts) + (f"(서비스 콘솔 월 한도 {provider.console_limit:,}회)" if provider.console_limit else "")


def _stage_lines(provider):
    """한도 단계표(콘솔 월 한도 기준) — 단계 비율과 그때의 사용량·하는 일."""
    return [f"    {stage.percent}%({connections.stage_threshold(provider, stage):,}회)를 넘으면: {stage.text}" for stage in sorted(provider.stages, key=lambda item: item.percent)]


def keys_purpose_dict(spec):
    accepts = connections.accepts_input(spec)                                  # 이 빌드가 새 키 입력을 받는 용도인가(Blogger 는 꺼져 있다 — 입력 칸을 알리지 않는다)
    found = {"purpose": spec.key, "label": spec.label, "summary": spec.summary, "takes_keys": accepts, "implemented": spec.implemented, "works_without_key": spec.works_without_key,
             "client_scope": spec.client_scope, "fields": [{"name": item.name, "label": item.label, "masked": item.secret, "min_len": item.min_len, "max_len": item.max_len, "example": item.example} for item in spec.fields] if accepts else [],
             "providers": [{"provider": item.key, "label": item.label, "rotation": item.rotation, "limits": _limit_text(item), "default_tier": item.default_tier, "tiers": list(item.tier_names())} for item in spec.providers],
             "fallback_providers": list(spec.fallback_providers), "note": connections.purpose_note(spec) if spec.takes_keys is False or accepts else connections.BLOGGER_INPUT_OFF}
    if spec.max_entries != connections.MAX_ENTRIES_PER_PURPOSE:           # 키를 하나만 두는 용도만 이 칸이 더해진다(다른 용도의 출력은 그대로)
        found["max_entries"] = spec.max_entries
    for item, shown in zip(spec.providers, found["providers"]):
        if item.console_limit:
            shown.update({"console_limit": item.console_limit, "stages": [{"name": stage.name, "percent": stage.percent, "above": connections.stage_threshold(item, stage), "text": stage.text, "denies": list(stage.deny)}
                                                                          for stage in sorted(item.stages, key=lambda value: value.percent)]})
    return found


def keys_purposes_lines(registry):
    lines = ["연결 설정의 용도(키는 Windows 자격 증명 관리자에만 보관하고, 키가 없어도 모든 핵심 기능은 그대로 됩니다)"]
    for spec in registry.values():
        lines.append(f"[{spec.key}] {spec.label}")
        lines.append(f"  쓰임: {spec.summary}")
        if not connections.accepts_input(spec):
            lines.append(f"  안내: {connections.purpose_note(spec) if not spec.takes_keys else connections.BLOGGER_INPUT_OFF}")
            continue
        lines.append("  받는 칸: " + ", ".join(f"{item.name}({item.label}{' — 화면에 보이지 않음' if item.secret else ''}, {item.min_len}~{item.max_len}자, 예: {item.example})" for item in spec.fields))
        for provider in spec.providers:
            title = f"제공자 {provider.key}({provider.label})" if provider.key else f"제공자 {provider.label}"
            auto = "어떤 오류에도 다른 키로 자동 전환하지 않음" if provider.rotation == connections.ROTATION_NEVER else "한도·일시 오류일 때만 허용된 다음 키로 전환"
            lines.append(f"  {title}: 한도 {_limit_text(provider)} — {auto}" + (f" — {provider.note}" if provider.note else ""))
            if provider.stages:
                lines.append("  한도 단계(이번 달 시도 수 기준):")
                lines += _stage_lines(provider)
        if spec.max_entries < connections.MAX_ENTRIES_PER_PURPOSE:
            lines.append(f"  항목 수: 이 용도는 키를 {spec.max_entries}개만 둡니다 — 한도를 늘리려고 키를 돌려 쓰지 않습니다(키를 바꾸려면 기존 항목을 지운 뒤 새로 넣습니다)")
        lines.append("  준비 상태: " + ("실제 호출 코드가 있어 연결 시험을 할 수 있습니다" if spec.implemented else "아직 실제 호출 코드가 없어 연결 시험을 하지 않습니다(키를 저장해 둘 수는 있습니다)"))
        lines.append(f"  범위: {spec.client_scope}")
    lines.append(f"용도마다 키 항목은 {connections.MAX_ENTRIES_PER_PURPOSE}개까지입니다" + ("(예외: " + ", ".join(f"{item.label} {item.max_entries}개" for item in registry.values() if item.max_entries < connections.MAX_ENTRIES_PER_PURPOSE) + ")." if any(
        item.max_entries < connections.MAX_ENTRIES_PER_PURPOSE for item in registry.values()) else "."))
    return lines


def _entry_line(view):
    entry = view.entry
    parts = [f"{connections.STATE_TEXT[entry.state]}", connections.STATUS_TEXT[view.status]]
    legacy = connections.PURPOSES[entry.purpose].legacy_to if entry.purpose in connections.PURPOSES else ""
    if legacy:
        parts.append(f"옛 항목 — 새 키는 {connections.PURPOSES[legacy].label}({legacy})에 넣고 이 항목은 지웁니다(키는 지우지 않았습니다)")
    spec = connections.PURPOSES.get(entry.purpose)
    provider = spec.provider(entry.provider) if spec is not None else None
    provider_name = provider.label if provider is not None and provider.label else entry.provider
    if provider_name:
        parts.append(f"제공자 {provider_name}")
    if entry.project:
        parts.append(f"소속 {entry.project}")
    parts.append("등록 " + (local_time(entry.created_at) if entry.created_at else "없음"))                  # 키에 대해 보이는 것은 제공자·항목 번호·등록 여부(상태)·마지막 연결 시험·등록 시각뿐이다(PCSEC1 H2)
    parts.append("마지막 확인 " + (local_time(entry.checked_at) if entry.checked_at else "없음"))
    return f"  [{view.ordinal}] {entry.name} — " + " · ".join(parts) + f" · 번호 {connections.short_id(entry.entry_id)}"


def keys_list_lines(views, statuses):
    lines = ["용도별 상태:"]
    for key, status in statuses.items():
        lines.append(f"  {connections.PURPOSES[key].label}: {connections.STATUS_TEXT[status]}")
    if not views:
        lines.append("키 항목이 아직 없습니다 — 키가 없어도 핵심 기능은 그대로 됩니다. 넣으려면 `keys add 용도 --name 이름` (용도는 `keys purposes`).")
        return lines
    lines.append(f"키 항목 {len(views)}개(키 원문은 보이지 않습니다):")
    lines += [_entry_line(view) for view in views]
    lines.append(f"지울 때는 순번이 아니라 번호 앞 {connections.DELETE_PREFIX}자를 씁니다: `{CMD} keys remove 번호 --yes`.")
    return lines


def keys_add_lines(view, notes, *, fake=False):
    lines = (["주의: 시험 전용 가짜 보관소를 쓰는 중입니다 — 실제 키를 넣지 마세요"] if fake else []) + ["키 항목을 추가했습니다(키는 보관소에만 저장했고 화면과 기록에는 남기지 않았습니다).", _entry_line(view)]
    lines += [f"안내: {note}" for note in notes]
    if view.entry.state == connections.ACTIVE:
        lines.append(f"참고: 연결 시험은 아직 준비 중이라 '{connections.STATUS_TEXT[view.status]}' 로 보입니다. 키가 없어도 핵심 기능은 그대로 됩니다.")
    return lines


def keys_remove_lines(result):
    lines = [f"키 항목을 지웠습니다: {result.entry.name}({result.purpose_label}) — 보관소의 키도 함께 지웠습니다.", "  뒤의 항목은 순번이 당겨졌을 수 있습니다 — `keys list` 로 다시 확인합니다."]
    lines.append("  저장해 둔 조회 결과(캐시)는 남기도록 표시했습니다(캐시는 나중 묶음이 다룹니다)." if result.keep_cache else "  저장해 둔 조회 결과(캐시)를 남기려면 지울 때 `--keep-cache` 를 붙입니다(캐시는 나중 묶음이 다룹니다).")
    return lines


def keys_state_lines(entry, before):
    if before == entry.state:
        return [f"바뀐 것이 없습니다: {entry.name} 은(는) 이미 '{connections.STATE_TEXT[entry.state]}' 입니다."]
    return [f"상태를 바꿨습니다: {entry.name} — {connections.STATE_TEXT[before]} → {connections.STATE_TEXT[entry.state]}"]


def keys_order_lines(purpose, items):
    lines = [f"순서를 정했습니다({connections.PURPOSES[purpose].label}) — 첫 `사용` 항목부터 쓰입니다:"]
    lines += [f"  {index}. {item.name}({connections.STATE_TEXT[item.state]})" for index, item in enumerate(items, start=1)]
    return lines


_OUTCOME_TEXT = {"rate_limited": "한도 초과 응답", "quota_exhausted": "기간 한도 소진 응답", "transient_error": "서버 일시 오류", "timeout": "시간 초과", "auth_failed": "인증 실패",
                 "bad_request": "요청 형식 오류", "policy_blocked": "정책 차단", "content_blocked": "콘텐츠 차단", "other_error": "그 밖의 오류"}      # 장부의 결과 종류 → 쉬운 한국어(영문 코드는 화면에 보이지 않는다)


def keys_ledger_lines(view):
    """장부 제공자(NAVER API HUB)의 설정 화면용 값 — 오늘·이번 달 시도/성공, 내부·콘솔 한도, 마지막 성공·오류, 단계, 호출 중지와 그 사유(멈췄을 때는 고정 문구)."""
    ledger = view.ledger
    lines = [f"  오늘 시도 {ledger.day_attempts:,}회 · 성공 {ledger.day_successes:,}회 / 내부 한도 {ledger.day_limit:,}회",
             f"  이번 달 시도 {ledger.month_attempts:,}회 · 성공 {ledger.month_successes:,}회 / 내부 한도 {ledger.month_limit:,}회(서비스 콘솔 월 한도 {ledger.console_limit:,}회 — 마지막 안전장치)",
             "  마지막 성공 호출: " + (local_time(ledger.last_success) if ledger.last_success else "없음")]
    if ledger.last_error:
        error = ledger.last_error
        status = f", 상태 {error['status']}" if error["status"] else ""
        lines.append(f"  마지막 오류: {local_time(error['at'])} — {_OUTCOME_TEXT.get(error['outcome'], '그 밖의 오류')}{status}")
    else:
        lines.append("  마지막 오류: 없음")
    if ledger.stage != "ok":
        lines.append(f"  한도 단계: {ledger.stage_text}")
    if ledger.stopped:
        lines.append(f"  호출 중지: {ledger.stop_text}")
        lines.append(f"    사유: {ledger.stop_cause}")
    else:
        lines.append("  호출 중지: 아니요(지금은 새 조회를 할 수 있습니다)")
    return lines


def keys_usage_lines(views, statuses):
    lines = []
    for view in views:
        status = statuses.get(view.purpose, connections.NOT_CONNECTED)
        lines.append(f"{view.label} — {connections.STATUS_TEXT[status]}")
        if view.notice:
            lines.append(f"  주의: {view.notice}")
        if view.entries == 0:
            lines.append("  키가 없습니다 — 키가 없어도 핵심 기능은 그대로 됩니다.")
            continue
        if not view.rows:
            lines.append("  한도를 확인하지 못했습니다 — 한도 오류 응답으로만 감지하고 사용량은 세지 않습니다.")
        if view.ledger is not None:                                  # 장부 제공자는 창마다 시도·성공을 따로 보인다
            lines += keys_ledger_lines(view)
        else:
            for row in view.rows:
                percent = f" ({row.used * 100 // row.limit}%)" if row.limit else ""
                when = "오늘" if row.window == "day" else row.span
                lines.append(f"  {row.entry}({row.provider}) {when} {row.used:,} / {row.limit:,}{percent}" + (" — 한도에 가까워 절약 모드" if row.near_limit else ""))
        if view.blocked and view.resume_text:
            lines.append(f"  {view.resume_text}")
        lines += [f"  최근 키 전환: {item}" for item in view.switches]
    return lines or ["보여 줄 용도가 없습니다."]


def keys_policy_lines(spec, policy, *, changed, view=None):
    first = "키가 하나뿐이라 다른 키로 넘어가지 않음(절약·중단만)" if spec.max_entries == 1 else connections.ON_LIMIT_TEXT[policy.on_limit]            # 키를 하나만 두는 용도는 전환 정책 글이 거짓이 되지 않게
    lines = [("정책을 바꿨습니다" if changed else "지금 정책") + f"({spec.label}): " + first]
    lines.append("  한도 등급: " + (policy.tier or "기본") + (f"(바꾼 때 {local_time(policy.changed_at)})" if policy.changed_at else ""))
    for provider in spec.providers:
        if provider.rotation == connections.ROTATION_NEVER:
            if spec.max_entries == 1:
                lines.append(f"  {provider.label or spec.label}: 키는 하나만 쓰고 어떤 오류(429 포함)에도 다른 키로 넘어가지 않습니다(한도를 늘리려고 키·계정을 돌려 쓰지 않습니다).")
            else:
                lines.append(f"  {provider.label or spec.label}: 어떤 오류에도 다른 키로 자동 전환하지 않습니다(키가 여러 개여도 개발용·운영용 구분이나 직접 고른 전환에만 씁니다).")
        if provider.stages:
            lines.append(f"  한도 단계(서비스 콘솔 월 한도 {provider.console_limit:,}회 기준):")
            lines += _stage_lines(provider)
    if spec.max_entries == 1:
        lines.append("  전환은 하지 않습니다 — 인증·잘못된 요청·정책 차단·한도 응답은 숨기지 않고 안내만 하고, 사용량·시계·인증 상태를 확인할 수 없으면 새 호출을 하지 않습니다(저장된 정보로 계속합니다).")
    else:
        lines.append("  전환은 한도(429·기간 한도)·일시 오류(500·502·503·504)·시간 초과일 때만, 허용된 다음 키(같은 용도·제공자의 사용·예비 항목)로, 한 요청에 한 바퀴를 넘지 않게 합니다. 인증·잘못된 요청·정책 차단은 숨기지 않고 안내만 합니다.")
    if view is not None and view.ledger is not None:
        lines.append("지금 사용량:")
        lines += keys_ledger_lines(view)
    return lines


def keys_test_lines(result):
    if result.ran:
        return [f"연결 시험을 마쳤습니다: {result.outcome}"]
    return [result.message or "시험하지 않았습니다.", "  (아무것도 바꾸지 않았고 키를 보내지도 않았습니다)"]


# ---- 자동 후보 제안·콘텐츠 작성 우선도 --------------------------------------------------------------------------------------------------------
SCORE_NOTE = "점수는 이 프로그램이 가진 정보로 정한 작성 순서의 참고값입니다 — 검색 결과나 방문자 수를 약속하지 않습니다. 계절표와 글 틀은 일반적인 시기 주제와 틀일 뿐 검색 수요를 보증하지 않습니다."


def priority_text(priority):
    return f"{priority.level} {sg.num(priority.score)}점"


SHORT_FACTORS = {"fit": "적합도", "season": "시기", "freshness": "신선도", "balance": "균형", "opportunity": "키워드 기회도"}


def priority_suffix(assessment):
    """`candidates list --priority` 의 한 줄 뒤에 덧붙이는 글 — 계산한 우선도·프로필 적합도·이유(요인별 점수)·(조회일). 보관함 값은 바뀌지 않는다."""
    if assessment.priority is None:
        return " · 콘텐츠 작성 우선도: 계산할 정보 없음"
    fit = "데이터 없음" if assessment.fit is None else sg.num(assessment.fit)
    text = f" · 콘텐츠 작성 우선도 {priority_text(assessment.priority)}(블로그 프로필 적합도 {fit})"
    why = "·".join(f"{SHORT_FACTORS[part.name]} {sg.num(part.value)}" for part in assessment.parts if part.name != "fit")
    text += f" · 이유: {why}" if why else ""
    return text + ("" if assessment.data_age.data_date is None else f" · {assessment.data_age.text()}")


def assessment_lines(assessment, notes=()):
    """`candidates show` 에 덧붙이는 '왜 이 우선도인지' 줄들."""
    if assessment.priority is None:
        lines = ["  계산한 콘텐츠 작성 우선도: 계산할 정보가 없습니다"]
    else:
        lines = [f"  계산한 콘텐츠 작성 우선도: {priority_text(assessment.priority)} — 보관함에 저장된 값은 바뀌지 않습니다", f"    왜 이 우선도인지: {assessment.reason}"]
    lines.append(f"  블로그 프로필 적합도(계산): {'데이터 없음' if assessment.fit is None else sg.num(assessment.fit)}")
    if assessment.data_age.data_date is not None:
        lines.append(f"  지표 조회: {assessment.data_age.text()}")
    if assessment.similar:
        lines.append("  기존 글과 비슷합니다 — 이미 쓴 글과 제목이나 키워드가 많이 겹칩니다.")
    lines += [f"  참고: {note}" for note in (*assessment.notes, *notes)]
    return lines


def suggestion_lines(item, *, verbose=False):
    data = "데이터 없음" if item.data_date is None else item.data_age.text()
    lines = [f"  [{item.rank}] 콘텐츠 작성 우선도 {priority_text(item.priority)} · 블로그 프로필 적합도 {sg.num(item.fit)} · {item.post_type} · {data}",
             f"      주제: {item.topic}",
             f"      핵심 키워드: {item.keyword}" + (f" · 보조 키워드: {', '.join(item.sub_keywords)}" if item.sub_keywords else ""),
             f"      이유: {item.reason}"]
    if item.data_date is not None:
        shown = [f"{cd.LABELS[name]} {metric_text(name, getattr(item.metrics, name))}" for name in ("search_demand", "related_blog_results", "trend") if getattr(item.metrics, name) is not None]
        lines.append("      외부 지표: " + (" · ".join(shown) if shown else "검색 수요·관련 블로그 검색 결과 수·최근 관심도 변화는 데이터 없음"))
    if verbose:
        lines.append(f"      계산 내역: 씨앗 「{item.seed}」({item.seed_source}) · 글 틀 {item.frame_id} · " + " · ".join(f"{part.name} {sg.num(part.value)}×{sg.num(part.share * 100)}%" for part in item.factors))
    return lines


def suggest_group_lines(group, *, verbose=False):
    report = group.report
    name = PLATFORM_KO[group.blog] + (f"({group.profile_name})" if group.profile_name else "")
    lines = [f"{name} 주제 제안 — {report.month}월 기준 · 계산일 {report.today}"]
    if report.guidance:
        return lines + [report.guidance] + [f"참고: {note}" for note in report.notes]      # 씨앗이 전부 버려진 화면에도 몇 개를 왜 버렸는지 알린다(독립 검증 2차)
    lines.append("  프로필의 주제·카테고리·기본 태그와 기존 글·최근 선택·달력으로 계산했습니다 — 월간 검색 수요·관련 블로그 검색 결과 수·최근 관심도 변화 같은 외부 데이터가 없는 칸은 '데이터 없음' 이고 점수에 넣지 않습니다.")
    lines.append("  씨앗: " + " · ".join(f"{seed.text}({seed.source})" for seed in report.seeds))
    if not report.suggestions:
        lines.append("  보여 줄 제안이 없습니다.")
    for item in report.suggestions:
        lines += suggestion_lines(item, verbose=verbose)
    removed = [f"{label} {number}" for _code, label, number, kept in report.filtered if not kept]
    hidden = [f"{label} {number}" for _code, label, number, kept in report.filtered if kept]
    if removed:
        lines.append(f"걸러낸 조합(만든 {report.generated}개 중): " + " · ".join(removed))
    if hidden:
        lines.append("숨긴 제안(번호는 그대로입니다): " + " · ".join(hidden))
    lines += [f"참고: {note}" for note in report.notes]
    if report.suggestions:
        first = report.suggestions[0]
        low, high = first.rank, report.suggestions[-1].rank
        span = f"{low}-{high}" if high > low else str(low)
        flags = (f" --count {report.count}" if report.count != sg.DEFAULT_COUNT else "") + (f" --month {report.month}" if report.month != int(report.today[5:7]) else "") + (f' --type "{report.post_type}"' if report.post_type and " " in report.post_type else f" --type {report.post_type}" if report.post_type else "")
        lines.append(f"넣으려면: `{CMD} candidates suggest --blog {group.blog}{flags} --add {','.join(str(item.rank) for item in report.suggestions[:3])} --yes` — 이 화면의 제안을 모두 넣으려면 `--add {span}`(처음 보이던 번호 1~{report.count} 전부는 `all` 로도 넣을 수 있습니다). 번호는 같은 입력이면 같은 순서이지만 보관함이 바뀌면 달라질 수 있어, "
                     f"확실하게 하려면 키워드로 적습니다(예: `--add \"{first.keyword}\"`).")
    return lines


def suggest_lines(result, *, verbose=False):
    lines = []
    for group in result.groups:
        lines += ([""] if lines else []) + suggest_group_lines(group, verbose=verbose)
    return lines + ["", SCORE_NOTE] + [f"알려 둔 한계: {note}" for note in result.limits]


def suggest_add_lines(result):
    """`candidates suggest --add` 의 출력 — `--yes` 가 없으면 넣을 목록만(아무것도 넣지 않았다), 있으면 넣은 후보들."""
    name = PLATFORM_KO[result.blog]
    adding = [item for item in result.items if item.action == "add"]
    skips = [item for item in (*result.items, *result.late_skips) if item.action == "skip"]
    if not result.confirmed:
        lines = [f"제안 넣기 미리 보기 — {name}(아무것도 넣지 않았습니다)"]
        lines += [f"  넣을 제안 [{item.suggestion.rank or '목록 밖'}] {item.suggestion.topic} (핵심 키워드: {item.suggestion.keyword}, {item.suggestion.post_type})" for item in adding]
        if not adding:
            lines.append("  넣을 제안이 없습니다.")
    elif result.added:
        lines = [f"제안 {len(result.added)}개를 새 후보(출처: {sg.SOURCE_MARK})로 보관함에 넣었습니다 — {name}"]
        lines += [candidate_line(row) for row in result.added]
    else:
        lines = [f"넣은 제안이 없습니다 — {name}(고른 제안이 모두 이미 보관함에 있거나 건너뛴 것입니다)"]
    seen = set()
    for item in skips:
        text = f"  건너뜀 {item.label}: {item.reason}" if item.suggestion is None else f"  건너뜀 [{item.suggestion.rank or '목록 밖'}] {item.suggestion.topic}: {item.reason}"
        if text not in seen:
            seen.add(text)
            lines.append(text)
    if not result.confirmed and adding:
        lines.append("같은 명령 끝에 --yes 를 붙이면 위 제안을 '새 후보' 로 보관함에 넣습니다(같은 키워드·같은 블로그의 후보가 이미 있으면 넣지 않습니다 — 되풀이해도 겹치지 않습니다).")
    if result.confirmed and result.added:
        lines.append(f"다음: `{CMD} candidates list` 로 보고 `{CMD} candidates select 순번 --blog {result.blog}` 로 고릅니다.")
    return lines
