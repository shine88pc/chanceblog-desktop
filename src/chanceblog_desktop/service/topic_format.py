"""주제 엔진 명령줄 출력 — `service/topics.py` 의 결과를 쉬운 한국어 줄로 바꾼다(P3). 기존 `format.py`(후보·글 출력)는 건드리지 않으려고 따로 둔다.

규칙: 화면 글은 이 모듈의 고정 문장과 `topics.wording`·`topics.notice` 의 표에서만 나온다 — 파이썬 목록 꼴·`Enum` 표기·내부 코드(영문 값 이름·후보 번호의 긴 모양)·`AppError.detail` 이 없다(시험이 모든 출력 줄을 `notice.leaks` 로 훑는다).
후보 번호는 화면에 짧은 번호(16진수 앞 8자)와 순번으로만 보이고, 전체 번호는 `--json` 에서만 나온다. 입력한 글(주제·씨앗 낱말)은 후보와 씨앗 자체의 값이라 그대로 보인다.
"""
from __future__ import annotations

from ..content.candidates import STATUS_KO
from ..topics import slots, wording
from ..topics.channels import FACTOR_LABELS, FACTOR_NAMES
from ..topics.score import BAND_KO, BAND_UNRATED, TREND_STATUS_KO
from .topics import short_ref

FILE_KO = {"channel_profiles.json": ("채널 프로필", "채널"), "seeds.json": ("씨앗", "개"), "calendar.json": ("캘린더", "개")}
STORE_KO = {"missing": "아직 없음(`topics init --yes` 나 `topics generate --yes` 가 만듭니다)", "empty": "비어 있음(0바이트 — 만들다 멈춘 흔적일 수 있습니다. `topics init --yes` 나 `topics generate --yes` 가 새로 만듭니다)", "old_structure": "옛 구조라 아직 읽지 않았습니다(저장하는 명령이 새 구조로 올립니다)",
            "newer": "더 새로운 버전의 프로그램이 만든 것이라 열지 않았습니다(프로그램을 업데이트하세요)", "corrupt": "깨졌거나 이 프로그램의 주제 엔진 파일이 아닙니다(파일은 건드리지 않았습니다 — 백업에서 되돌리세요)",
            "unreadable": "다른 곳에서 쓰는 중이거나 정리 안 된 저장이 있어 지금은 읽지 못했습니다(잠시 뒤 다시 해 보세요)"}
HISTORY_KO = {"read": "읽음", "not_connected": "블로그 저장소가 연결되지 않아 읽지 못함", "missing": "이력 파일이 없음", "unreadable": "읽을 수 없음", "no_store": "글 보관함이 없음"}
SHOWN_PER_CHANNEL = 10                                       # 계획 미리 보기에서 채널마다 보이는 새 후보 수(`--verbose` 는 모두)


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
    lines += ["", "다음: `topics check` 로 씨앗·캘린더를 검사 → `topics plan` 으로 후보 미리 보기 → `topics generate --yes` 로 저장"]
    return lines


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
    lines += ["  (최근 10개만 남기고 오래된 것은 지웁니다. 키·토큰은 어떤 경우에도 담지 않습니다)"]
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


__all__ = ["backup_lines", "check_lines", "init_lines", "list_lines", "plan_lines", "restore_lines", "review_lines", "show_lines", "status_lines", "top_lines"]
