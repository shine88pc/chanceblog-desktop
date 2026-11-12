"""주제 엔진 명령줄 출력 — `service/topics.py` 의 결과를 쉬운 한국어 줄로 바꾼다(P3). 기존 `format.py`(후보·글 출력)는 건드리지 않으려고 따로 둔다.

규칙: 화면 글은 이 모듈의 고정 문장과 `topics.wording`·`topics.notice` 의 표에서만 나온다 — 파이썬 목록 꼴·`Enum` 표기·내부 코드(영문 값 이름·후보 번호의 긴 모양)·`AppError.detail` 이 없다(시험이 모든 출력 줄을 `notice.leaks` 로 훑는다).
후보 번호는 화면에 짧은 번호(16진수 앞 8자)와 순번으로만 보이고, 전체 번호는 `--json` 에서만 나온다. 입력한 글(주제·씨앗 낱말)은 후보와 씨앗 자체의 값이라 그대로 보인다.
"""
from __future__ import annotations

from ..content.candidates import STATUS_KO
from ..topics import hold, slots, wording
from ..topics.channels import FACTOR_LABELS, FACTOR_NAMES
from ..topics.score import BAND_KO, BAND_UNRATED, TREND_STATUS_KO
from .topics import short_ref

CREDENTIAL_LINE = "키는 백업에 들어 있지 않아요 — 복원 뒤 다시 등록하세요"             # 명령줄 백업 출력에 한 줄로 알린다(PCSEC1 M4 — 글 보관함·주제 엔진 백업이 같은 줄을 쓴다. 저장 계층은 목록 문장만 갖는다)

FILE_KO = {"channel_profiles.json": ("채널 프로필", "채널"), "seeds.json": ("씨앗", "개"), "calendar.json": ("캘린더", "개")}
STORE_KO = {"missing": "아직 없음(`topics init --yes` 나 `topics generate --yes` 가 만듭니다)", "empty": "비어 있음(0바이트 — 만들다 멈춘 흔적일 수 있습니다. `topics init --yes` 나 `topics generate --yes` 가 새로 만듭니다)", "old_structure": "옛 구조라 아직 읽지 않았습니다(저장하는 명령이 새 구조로 올립니다)",
            "newer": "더 새로운 버전의 프로그램이 만든 것이라 열지 않았습니다(프로그램을 업데이트하세요)", "corrupt": "깨졌거나 이 프로그램의 주제 엔진 파일이 아닙니다(파일은 건드리지 않았습니다 — 백업에서 되돌리세요)",
            "unreadable": "다른 곳에서 쓰는 중이거나 정리 안 된 저장이 있어 지금은 읽지 못했습니다(잠시 뒤 다시 해 보세요)"}
HISTORY_KO = {"read": "읽음", "not_connected": "블로그 저장소가 연결되지 않아 읽지 못함", "missing": "이력 파일이 없음", "unreadable": "읽을 수 없음", "no_store": "글 보관함이 없음"}
SHOWN_PER_CHANNEL = 10                                       # 계획 미리 보기에서 채널마다 보이는 새 후보 수(`--verbose` 는 모두)
MAX_SHOWN_IMPORT = 10                                          # 씨앗 불러오기에서 건너뜀·거절 줄을 이만큼까지 보인다


def _score_text(candidate):
    final = candidate.scores.final
    return "점수 없음" if final is None else f"{final}점·{BAND_KO[candidate.recommendation_band]}"


MAX_DETAILS = 4                                              # 같은 알림 아래 보이는 세부 줄 수(넘으면 '그 밖에 N건')


def _notice_lines(notices, indent="  "):
    """알림들을 같은 코드끼리 묶어 한 줄씩(`- 제목: 설명 행동`) 보이고 세부(경로·건수·첫 사례)는 그 아래에 모은다 — 같은 알림이 경로마다 되풀이되어 보이지 않게."""
    grouped = {}
    for item in notices:
        grouped.setdefault(item.code, (item, []))[1].extend(item.details)
    lines = []
    for item, details in grouped.values():
        lines.append(f"{indent}- {item.title}: {item.message} {item.action}")
        shown = list(dict.fromkeys(details))
        lines += [f"{indent}    · {line}" for line in shown[:MAX_DETAILS]]
        if len(shown) > MAX_DETAILS:
            lines.append(f"{indent}    · 그 밖에 {len(shown) - MAX_DETAILS}건")
    return lines


def file_line(item):
    name, unit = FILE_KO[item.name]
    if item.state == "missing":
        return f"  - {name}: 파일이 없습니다 — 기본값을 씁니다" + ("(다섯 채널)" if item.name == "channel_profiles.json" else "(비어 있음)")
    if item.state == "ok":
        return f"  - {name}: 읽을 수 있습니다({item.count}{unit})"
    return f"  - {name}: 읽을 수 없습니다 — {item.reason}"


def history_line(item):
    return f"  - {wording.CHANNEL_KO[item.channel]}: {HISTORY_KO[item.state]}" + (f"({item.count}개)" if item.state == "read" else "")


def status_lines(result):
    lines = ["주제 엔진 상태", "", "설정 파일(사용자 데이터 폴더의 주제 엔진 폴더 안)"]
    lines += [file_line(item) for item in result.files]
    lines += ["", f"후보 보관함: {STORE_KO.get(result.store_state, '읽을 수 있습니다' + (f'(구조 {result.store_version}판)' if result.store_version else ''))}"]
    if result.store_state == "ready":
        lines += [f"  - {wording.CHANNEL_KO[channel]}: 후보 {number}개" + (" (후보 생성 켜짐)" if channel in result.enabled else " (후보 생성 꺼짐)") for channel, number in result.counts]
    lines += ["", "블로그 발행 이력(읽기만 합니다 — 블로그 저장소는 바꾸지 않습니다)"] + [history_line(item) for item in result.history.channels]
    lines += [f"  주의: {text}" for text in result.history.warnings]
    lines += ["", "후보 생성이 켜진 채널: " + (", ".join(wording.CHANNEL_KO[channel] for channel in result.enabled) or "없음")]
    if result.reviews:
        lines += ["", "다음 점검일(자동으로 돌지 않습니다 — 주제 분석 `topics generate --yes` 를 실행하는 날 점검일이 기록됩니다)"] + [review_line(item) for item in result.reviews]
    lines += ["", "다음: `topics check` 로 씨앗·캘린더를 검사 → `topics plan` 으로 후보 미리 보기 → `topics generate --yes` 로 저장"]
    return lines


def review_line(item):
    """점검 하나의 다음 점검일 한 줄 — 기한이 지나도 표시만 한다(아무것도 자동으로 하지 않는다)."""
    head = f"  - {wording.REVIEW_KIND_KO[item.kind]}({item.period_days}일마다): "
    if item.state == "never":
        return head + "아직 점검한 적이 없어 지금 점검할 수 있습니다"
    when = f"마지막 점검 {item.last_run_on}"
    if item.state == "due":
        return head + f"오늘이 점검일입니다({when})"
    if item.state == "overdue":
        return head + f"점검 기한이 {-item.days_left}일 지났습니다(다음 점검일은 {item.next_due_on} 이었습니다 — 표시만 하고 아무것도 바꾸지 않았습니다)"
    return head + f"다음 점검일 {item.next_due_on}({item.days_left}일 뒤 — {when})"


def init_lines(result):
    lines = ["주제 엔진 폴더와 설정 파일을 " + ("만들었습니다." if result.confirmed else "만들지 않았습니다(미리 보기 — 만들려면 같은 명령 끝에 --yes 를 붙입니다).")]
    for name in result.made:
        lines.append(f"  - {FILE_KO[name][0]}: " + ("새로 만들었습니다" if result.confirmed else "없어서 만들 예정입니다") + (" — 기본 다섯 채널" if name == "channel_profiles.json" else " — 비어 있는 틀"))
    for name in result.kept:
        lines.append(f"  - {FILE_KO[name][0]}: 이미 있어서 그대로 두었습니다")
    lines.append("  - 후보 보관함: " + (("새로 만들었습니다" if result.confirmed else "없어서 만들 예정입니다") if result.store_created else "이미 있어서 그대로 두었습니다"))
    if result.confirmed:
        lines.append("씨앗은 `seeds.json` 에 직접 적습니다(실제 씨앗은 이 PC 에만 두고 저장소에는 올리지 않습니다). 다음: `topics check`")
    return lines


def check_lines(result):
    lines = ["주제 엔진 설정 검사(읽기만 합니다)", ""] + [file_line(item) for item in result.files]
    lines += ["", f"씨앗 {result.seeds}개 · 캘린더 항목 {result.entries}개"]
    lines += [f"  - {text}" for text in result.proposals]
    lines += [f"  - {text}" for text in result.evaluations]
    if result.keyed:
        lines += ["", "키·토큰처럼 보이는 글이 든 곳(낱말은 되풀이하지 않습니다)"] + [f"  - {text}" for text in result.keyed]
        lines.append("  그 글을 지우세요 — 지우기 전에는 그 씨앗의 후보를 저장하지 않고(후보는 한 번 저장되면 지울 수 없습니다) 백업도 막힙니다")
    if result.public_keyed:
        lines += ["", "발행한 글(블로그)에 키·토큰처럼 보이는 글이 든 곳(낱말은 되풀이하지 않습니다)"] + [f"  - {text}" for text in result.public_keyed]
        lines.append("  이미 공개된 글이라 후보 저장과 백업은 막지 않습니다 — 다만 그 글이 실제 키라면 이미 드러난 것이니 다시 발급하는 것이 안전합니다")
    if result.notices:
        lines += ["", "브랜드 이름만 있는 씨앗(저장 없이 미리 본 결과)"]
        for item in result.notices:
            lines += [f"  - {item.title}: {item.message} {item.action}"] + [f"      {detail}" for detail in item.details]
    done = "검사를 통과했습니다." if not result.keyed else "검사를 통과했습니다(다만 위 키·토큰 모양 글을 지우기 전에는 그 씨앗의 후보 저장과 백업이 막힙니다)."
    lines += ["", done if result.ok else "읽을 수 없는 파일이 있습니다 — 위 이유대로 고친 뒤 다시 검사하세요(파일은 고치거나 덮어쓰지 않았습니다)."]
    return lines


def _plan_channel_lines(plan, verbose):
    if not plan.enabled:
        return [f"■ {plan.name} — 후보 생성이 꺼져 있어 만들지 않았습니다(이력 읽기·중복 검사만 합니다)"]
    info = plan.slots
    lines = [f"■ {plan.name} — 목표 {plan.target}개 · 이미 있는 후보 중 활성 {info.active_existing}개·검토 대기 {info.pending_review}개 · 남은 자리 {info.remaining}개"]
    if info.ignored:
        lines.append("  자리를 차지하지 않는 후보: " + ", ".join(f"{slots.REASON_KO[why]} {count}개" for why, count in info.ignored))
    if info.remaining == 0:
        lines.append("  남은 자리가 없어 새 후보를 만들지 않았습니다")
        return lines
    extra = (f"같은 후보라 뺀 것 {plan.duplicates}개" if plan.duplicates else "") + (", " if plan.duplicates and plan.stopped else "") + (f"자동 초안 중지 후보 {plan.stopped}개" if plan.stopped else "")
    lines.append(f"  새 후보 {len(plan.candidates)}개" + (f" ({extra})" if extra else ""))
    shown = plan.candidates if verbose else plan.candidates[:SHOWN_PER_CHANNEL]
    for number, candidate in enumerate(shown, start=1):
        lines.append(f"   {number}. ({_score_text(candidate)}) {candidate.topic} — {wording.SOURCE_TYPE_KO[candidate.source_type]} 경로")
    if len(plan.candidates) > len(shown):
        lines.append(f"   … 그 밖에 {len(plan.candidates) - len(shown)}개(`--verbose` 로 모두 봅니다)")
    lines += _notice_lines(plan.notices)
    lines += [f"  관심도: {text}" for text in plan.trend_notes]
    if plan.needs_region:
        names = "·".join(f"‘{name}’" for name in dict.fromkeys(plan.needs_region))
        lines.append(f"  - 지역 값이 필요한 씨앗 {len(plan.needs_region)}개(씨앗 {names})는 후보를 만들지 않았습니다 — 채널 프로필에 상시 이동권이나 당일 이동권 지역을 적으면 만들 수 있습니다(오류가 아니라 알림입니다)")
    if plan.withheld:
        names = "·".join(f"‘{name}’" for name in dict.fromkeys(plan.withheld))
        lines.append(f"  - 키·토큰처럼 보이는 글이 든 후보 {len(plan.withheld)}개는 저장하지 않았습니다(씨앗 {names}) — 그 씨앗의 글에서 키처럼 보이는 낱말을 지운 뒤 다시 하세요. 후보는 한 번 저장되면 지울 수 없고 백업이 막히기 때문입니다")
    return lines


def plan_lines(result, *, verbose=False):
    head = f"후보를 저장했습니다 — 새 후보 {result.total}개(기준일 {result.today})" if result.saved else f"후보 계획 미리 보기 — 아무것도 저장하지 않았습니다(기준일 {result.today})"
    lines = [head, ""]
    for plan in result.plans:
        lines += _plan_channel_lines(plan, verbose) + [""]
    lines += [f"안내: {text}" for text in result.notes]
    if not result.saved:
        lines.append("저장하려면 `topics generate --yes` 를 실행합니다(그때 남은 자리를 다시 세어 저장합니다).")
    return [line for number, line in enumerate(lines) if line or (number and lines[number - 1])]


def cleanup_lines(result):
    """보류 후보 90일 뒤 상세 정리의 쉬운 말 출력 — 기본은 미리 보기이고 무엇이 남고 무엇이 지워지는지 보인다. 옛 구조의 보관함에 `--yes` 를 주면 구조만 올리고 멈췄다고 알린다(미리 본 적 없는 후보를 지우지 않는다)."""
    if result.upgraded:
        return ["보류 후보 상세 정리 — 이번에는 아무것도 정리하지 않았습니다(후보 보관함이 옛 구조라 새 구조로 올리기만 했습니다 — 옛 구조의 사본을 보관함 옆에 남겨 두었습니다)",
                "구조를 올렸습니다. 다시 미리 보기(`topics hold cleanup`)를 실행해 정리할 후보와 확인 번호를 본 뒤 `--yes --confirm 확인번호` 로 정리해 주세요. 미리 본 적 없는 후보는 지우지 않습니다."]
    if result.refused == "token_missing":
        return ["보류 후보 상세 정리 — 확인 번호가 없어 아무것도 정리하지 않았습니다",
                "먼저 `topics hold cleanup` 으로 미리 보기를 하고 그때 보인 확인 번호를 `--yes --confirm 확인번호` 로 함께 주세요(미리 볼 때 `--today` 를 썼다면 같은 값을 함께 줍니다)."]
    if result.refused == "token_mismatch":
        return ["보류 후보 상세 정리 — 확인 번호가 지금 정리 대상과 맞지 않아 아무것도 정리하지 않았습니다(미리 본 뒤 대상이 바뀌었거나 번호를 잘못 썼습니다)",
                "다시 미리 보기를 해 주세요 — 지금 대상과 새 확인 번호가 나옵니다." + (f" 정리 직전 사본은 만들어 두었습니다: {result.copy}" if result.copy else "")]
    if result.store_state in ("missing", "empty", "old_structure"):
        return ["보류 후보 상세 정리 — 정리할 것이 없습니다(후보 보관함이 " + {"missing": "아직 없습니다", "empty": "비어 있습니다", "old_structure": "옛 구조라 아직 읽지 않았습니다"}[result.store_state] + ")",
                *(["구조를 올리려면 같은 명령 끝에 --yes 를 붙입니다 — 구조만 올리고 정리는 하지 않으니, 올린 뒤 다시 미리 보기를 해 주세요."] if result.store_state == "old_structure" else [])]
    if result.rows and not result.applied:
        return ["보류 후보 상세 정리 — 정리된 후보가 없습니다(아래 이유로 모두 정리하지 않았습니다)", "", *_not_cleaned_lines(result),
                *([f"정리 직전의 보관함 사본은 만들어 두었습니다: {result.copy}"] if result.copy else [])]
    if result.applied:
        head = f"보류 후보 {len(result.items)}개의 상세 데이터를 정리했습니다 — 이력 {len(hold_fields())}칸만 남았습니다(지금 남은 보류 이력 {result.history_total}개)"
    elif not result.items:
        return ["보류 후보 상세 정리 — 지금 정리할 후보가 없습니다(최초로 보류함에 든 지 90일이 지나고 그 뒤 변화가 없는 후보만 정리합니다)", f"  지금 남은 보류 이력 {result.history_total}개"]
    else:
        head = f"보류 후보 상세 정리 미리 보기 — 아무것도 지우지 않았습니다(정리할 수 있는 후보 {len(result.items)}개)"
    lines = [head, ""]
    for number, item in enumerate(result.items[:MAX_SHOWN_IMPORT], start=1):
        lines.append(f"  {number:>2}. {short_ref(item.candidate_id)}  {wording.CHANNEL_KO[item.channel]:<9}  기한 {item.expires_at[:10]}  {item.topic}")
    if len(result.items) > MAX_SHOWN_IMPORT:
        lines.append(f"  … 그 밖에 {len(result.items) - MAX_SHOWN_IMPORT}개")
    lines += ["", "남기는 이력 " + f"{len(hold_fields())}칸: " + ", ".join(hold.HISTORY_FIELD_KO[name] for name in hold_fields())]
    lines += ["지워지는 것: " + " · ".join(what for _table, _column, what in hold_erases())]
    if result.applied:
        lines += [f"정리 직전의 보관함 사본을 남겼습니다: {result.copy} (지우려던 상세를 그대로 담고 있으니 필요 없어지면 직접 지워 주세요)",
                  "정리한 후보는 목록에서 사라지고(남은 후보의 순번은 다시 매겨집니다 — 번호는 그대로) 이력으로만 남습니다. 같은 후보가 다시 만들어지지는 않고 정리한 번호는 다시 쓰지 않습니다."]
        if result.not_cleaned:
            lines += ["", *_not_cleaned_lines(result)]
    else:
        lines += ["정리하면 되돌릴 수 없습니다(점수·선정 이유가 사라집니다) — 정리 직전에 보관함 사본을 자동으로 남기고, `topics backup` 으로 따로 백업해 둘 수도 있습니다.",
                  "정리 대상은 사람이 한 번도 손대지 않았고 초안과 이어지지 않은 후보뿐입니다(검토·선택·보류·제외한 후보와 초안에 쓴 후보는 정리하지 않습니다).",
                  f"확인 번호: {result.token}",
                  f"정리하려면 같은 명령 끝에 --yes --confirm {result.token} 을 붙입니다(미리 볼 때 `--today` 를 썼다면 같은 값을 함께 줍니다). 미리 본 뒤 대상이 바뀌면 번호가 달라져 정리하지 않습니다. 자동으로는 절대 정리하지 않습니다."]
    return lines


def _not_cleaned_lines(result):
    """정리하지 않은 행(건너뜀·충돌·실패)의 개수와 후보별 이유 — 한 후보의 충돌·실패가 나머지 정리를 막지 않았다."""
    counts = result.counts
    lines = [f"정리하지 않은 후보 {len(result.not_cleaned)}개 — 건너뜀 {counts['skipped']} · 충돌 {counts['conflict']} · 실패 {counts['failed']}"]
    for row in result.not_cleaned[:MAX_SHOWN_IMPORT]:
        lines.append(f"  - {short_ref(row.candidate_id)}: {row.detail}")
    if len(result.not_cleaned) > MAX_SHOWN_IMPORT:
        lines.append(f"  - 그 밖에 {len(result.not_cleaned) - MAX_SHOWN_IMPORT}개")
    return lines


def hold_fields():
    return hold.HISTORY_FIELDS


def hold_erases():
    return hold.CLEANUP_ERASES


def import_lines(result):
    """씨앗 제안 불러오기의 쉬운 말 출력 — 개수·건너뜀·거절 사유·채널별 허용 씨앗 수. 파일 안의 낱말은 되풀이하지 않고 씨앗 번호와 이유만 보인다."""
    if result.applied:
        head = f"씨앗 제안을 불러왔습니다 — 새로 등록한 씨앗 {len(result.new)}개(모두 승인 전)"
    elif result.blocked:
        head = "씨앗 제안 불러오기 — 읽을 수 없는 씨앗이 있어 저장하지 않았습니다(아무것도 바뀌지 않았습니다)"
    elif not result.new:
        head = "씨앗 제안 불러오기 — 새로 등록할 씨앗이 없습니다(저장할 것이 없어 아무것도 바뀌지 않았습니다)"
    else:
        head = "씨앗 제안 불러오기 미리 보기 — 아무것도 저장하지 않았습니다"
    lines = [head, "", f"  파일 안 씨앗 {result.total}개 · 새로 등록할 씨앗 {len(result.new)}개 · 이미 있어 건너뜀 {len(result.skipped)}개 · 읽을 수 없어 뺀 씨앗 {len(result.rejected)}개(지금 등록된 씨앗 {result.existing}개)"]
    for title, rows in (("이미 있어 건너뜀", result.skipped), ("읽을 수 없어 뺌", result.rejected)):
        if rows:
            lines += ["", f"{title}"] + [f"  - 씨앗 ‘{name}’: {reason}" for name, reason in rows[:MAX_SHOWN_IMPORT]]
            if len(rows) > MAX_SHOWN_IMPORT:
                lines.append(f"  - 그 밖에 {len(rows) - MAX_SHOWN_IMPORT}건")
    if result.new:
        lines += ["", "새 씨앗이 승인되면 채널마다 쓸 수 있는 수(허용 채널 기준)"]
        lines += [f"  - {wording.CHANNEL_KO[channel]}: {number}개 — " + ("후보 생성 켜짐" if enabled else "후보 생성 꺼짐(씨앗은 등록·승인할 수 있고 후보 생성만 꺼져 있습니다)") for channel, number, enabled in result.per_channel]
    if result.kept_copy:
        lines += ["", f"옛 모양(판 1)의 씨앗 파일은 지우지 않고 사본으로 남겼습니다: {result.kept_copy}"]
    lines += ["", *[f"안내: {text}" for text in result.notes]]
    lines.append("승인 전 씨앗은 후보 생성에 쓰이지 않습니다 — 승인하면 사용 중이 됩니다.")
    if not result.applied and not result.blocked and result.new:
        lines.append("저장하려면 같은 명령 끝에 --yes 를 붙입니다.")
    return [line for number, line in enumerate(lines) if line or (number and lines[number - 1])]


def _row_line(row, *, with_channel=True):
    candidate = row.candidate
    return (f"{row.ordinal:>3}  {short_ref(candidate.candidate_id)}  " + (f"{wording.CHANNEL_KO[candidate.channel]:<9}  " if with_channel else "") +
            f"{STATUS_KO[candidate.work_status]}  ({_score_text(candidate)})" + ("  (자동 초안 중지)" if row.stop else "") + f"  {candidate.topic}")


def top_lines(result):
    if result.store_state == "missing":
        return ["후보 보관함이 아직 없습니다 — `topics generate --yes` 로 후보를 만든 뒤 봅니다."]
    lines = []
    for item in result.channels:
        if not item.enabled:
            lines.append(f"■ {item.name} — 후보 생성이 꺼져 있어 우수 후보가 없습니다")
            continue
        lines.append(f"■ {item.name} — 우수 후보 {len(item.rows)}개")
        lines += ["  " + _row_line(row, with_channel=False) for row in item.rows]
        if item.shortfall:
            lines.append(f"  이번 분석에서 기준을 충족한 주제는 {len(item.rows)}개입니다(우선 추천과 일반 후보만 올리고 보류함 이하로는 채우지 않습니다)")
        lines += [f"  주의: {text}" for text in item.problems]
        lines.append("")
    return lines[:-1] if lines and not lines[-1] else lines


def list_lines(result):
    if not result.rows:
        return ["저장된 후보가 없습니다." if result.total == 0 else f"조건에 맞는 후보가 없습니다(전체 {result.total}개)."]
    lines = [f"후보 {len(result.rows)}개" + (f"(전체 {result.total}개 중)" if len(result.rows) != result.total else ""), "순번  번호      채널       상태  (점수·구간)  주제"]
    lines += [_row_line(row) for row in result.rows]
    lines.append("자세히 보기: `topics show 순번`")
    return lines


def show_lines(result):
    row, candidate = result.row, result.row.candidate
    card = candidate.scores
    lines = [f"후보 {row.ordinal}번(번호 {short_ref(candidate.candidate_id)}) — {wording.CHANNEL_KO[candidate.channel]}", f"  주제: {candidate.topic}", f"  핵심 키워드: {candidate.primary_keyword}"]
    if candidate.secondary_keywords:
        lines.append("  보조 키워드: " + ", ".join(candidate.secondary_keywords))
    lines += [f"  작업 상태: {STATUS_KO[candidate.work_status]} · 추천 구간: {BAND_KO[candidate.recommendation_band]}" + ("  (자동 초안 중지)" if row.stop else ""),
              f"  경로: {wording.SOURCE_TYPE_KO[candidate.source_type]} · 종류: {wording.CANDIDATE_TYPE_KO[candidate.candidate_type]} · 글 종류: {wording.CONTENT_TYPE_KO[candidate.content_type]}",
              f"  검색 의도: {wording.SEARCH_INTENT_KO[candidate.search_intent]} · 대상 독자: {candidate.target_reader}",
              f"  만든 시각: {candidate.created_at}"]
    if candidate.recommendation_band == BAND_UNRATED:
        lines.append("  점수: 아직 없음(모르는 값은 0점이 아닙니다)")
    else:
        parts = [f"{FACTOR_LABELS[name]} {value}" if value is not None else f"{FACTOR_LABELS[name]} 모름" for name, value in ((name, getattr(card.factors, name)) for name in FACTOR_NAMES)]
        lines.append(f"  점수: 최종 {card.final}점 — " + " · ".join(parts))
    lines.append(f"  관심도: {TREND_STATUS_KO[candidate.trend_status]}" + (f"(상대값 {candidate.trend_ratio} — 검색 횟수가 아닙니다)" if candidate.trend_ratio is not None else "") + f" · 자료 상태: {wording.DATA_STATUS_KO[candidate.data_status]}")
    if candidate.duplicate_status:
        lines.append(f"  중복 판정: {wording.DUPLICATE_STATUS_KO[candidate.duplicate_status]}")
    if candidate.safety_flags:
        lines.append("  안전 표시: " + ", ".join(wording.SAFETY_FLAG_KO[flag] for flag in candidate.safety_flags))
    if result.stay is not None:
        lines.append(f"  보류함: {result.stay.entered_at[:10]} 에 들어왔고 기한은 {result.stay.expires_at[:10]} 입니다")
    lines += ["  선정 이유:"] + [f"    - {text}" for text in candidate.selection_reasons]
    if result.notices:
        lines += ["", "알림"] + _notice_lines(result.notices)
    lines.append(f"  점수 기록 {result.snapshots}번" + (" · 기존 후보·초안과 이어져 있음" if result.link is not None else " · 아직 기존 후보·초안과 이어지지 않음"))
    return lines


def review_lines(result):
    if not result.items:
        return ["보류 중인 후보가 없습니다."]
    lines = [f"보류 후보 {len(result.items)}개 — 기한이 지난 것 {result.expired}개(지우거나 바꾸지 않았습니다 — 정리할지는 운영자가 정합니다)", "순번  번호      채널       기한        남은 날  주제"]
    for item in result.items:
        candidate = item.row.candidate
        due = "기한 없음(사람이 보류)" if item.expires_at is None else item.expires_at[:10]
        left = "-" if item.days_left is None else ("지남" if item.expired else f"{item.days_left}일")
        lines.append(f"{item.row.ordinal:>3}  {short_ref(candidate.candidate_id)}  {wording.CHANNEL_KO[candidate.channel]:<9}  {due:<10}  {left:<6}  {candidate.topic}")
    return lines


def backup_lines(result):
    lines = [f"주제 엔진 백업을 만들었습니다: {result.path}", "  담은 파일: " + ", ".join(FILE_KO.get(name, ("후보 보관함",))[0] for name in result.files)]
    if result.missing:
        lines.append("  지금 없어서 담지 못한 파일: " + ", ".join(FILE_KO.get(name, ("후보 보관함",))[0] for name in result.missing))
    lines += ["  (최근 10개만 남기고 오래된 것은 지웁니다. 키·토큰은 어떤 경우에도 담지 않습니다)", f"  {CREDENTIAL_LINE}"]
    return lines


def restore_lines(result):
    lines = [f"주제 엔진 백업으로 되돌렸습니다: {result.source}", "  바꾼 파일: " + ", ".join(FILE_KO.get(name, ("후보 보관함",))[0] for name in result.restored)]
    if result.kept:
        lines.append("  백업에 없어서 지금 것을 그대로 둔 파일: " + ", ".join(FILE_KO.get(name, ("후보 보관함",))[0] for name in result.kept))
    if result.safety is not None:
        lines.append(f"  되돌리기 직전의 상태는 따로 백업해 두었습니다: {result.safety}")
    if result.moved_aside is not None:
        lines.append(f"  깨져 있던 지금 후보 보관함은 지우지 않고 옆으로 옮겨 두었습니다: {result.moved_aside}")
    for moved in result.moved_json:
        lines.append(f"  읽을 수 없던 지금 설정 파일은 지우지 않고 옆으로 옮겨 두었습니다: {moved}")
    return lines


__all__ = ["backup_lines", "check_lines", "cleanup_lines", "import_lines", "init_lines", "list_lines", "plan_lines", "restore_lines", "review_line", "review_lines", "show_lines", "status_lines", "top_lines"]
