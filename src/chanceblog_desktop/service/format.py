"""명령줄에 보여 줄 글(쉬운 한국어) — 서비스 함수의 결과를 줄 목록으로 바꾼다. 화면에 나가기 전에 부르는 쪽(cli)이 모든 줄을 `security.mask` 에 통과시킨다.

영문 약어에는 설명을 붙인다(예: 기록(commit), 올리기(push)). 상태 이름(APPROVED 등)은 한국어 뜻과 함께 보여 준다.
"""
from __future__ import annotations

from ..content import candidates as cd
from ..content import draft_plan as dp
from ..content import status as st
from ..content.profiles import NaverProfile
from ..errors import AppError, render
from ..security.mask import safe_detail
from . import naver_flow
from .candidates import DELETE_PREFIX, MAX_ORDINAL_DIGITS, kst

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


def candidate_list_lines(result, *, verbose=False):
    if result.total == 0:
        if result.store_state != "ready":
            return ["아직 후보가 없습니다(쓰는 명령을 처음 실행하면 보관함이 올라갑니다). " + EMPTY_HINT]
        return ["아직 후보가 없습니다. " + EMPTY_HINT]
    filters = [item for item in (f"상태: {cd.STATUS_KO[result.status]}" if result.status else "", f"블로그: {PLATFORM_KO[result.blog]}" if result.blog else "") if item]
    if not result.rows:
        return [f"조건에 맞는 후보가 없습니다(전체 {result.total}개 — {' · '.join(filters)})."]
    head = f"주제 후보 {len(result.rows)}개" + (f"(전체 {result.total}개 중 — {' · '.join(filters)})" if filters else "")
    lines = [head] + [candidate_line(row, verbose=verbose) for row in result.rows]
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


def candidate_show_lines(result, *, verbose=False):
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
        lines += [f"    {cd.LABELS[name]}: {metric_text(name, getattr(candidate, name))}" for name in cd.METRIC_FIELDS]
    else:
        lines.append("  지표: 데이터 없음")
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
