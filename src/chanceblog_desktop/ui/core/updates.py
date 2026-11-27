"""설정 화면 '업데이트' 카드가 그릴 **데이터**(UPDATE 설계서 3-7, v1update U-5 의 순수 층) — 순수 파이썬(화면 도구·서비스·접속을 모른다). 화면(Qt) 코드는 이 값을 그리기만 한다 — 이 갈래에는 Qt 코드가 없다.

한 상태 → 한 장의 카드 데이터(`CardView`): 제목·보이는 줄들·**주 단추 하나(또는 없음)**·그 단추가 눌릴 수 있는가·취소 단추·진행 값·오류 이름·접근성 이름. 규칙(시험이 표로 지킨다):
  · 주 단추는 많아야 하나다. **꺼짐**에는 단추가 없다. 확인 중·진행 중에는 주 단추가 없고 취소는 설치를 시작하기 전(내려받기·검증·준비·백업)까지만 보인다.
  · `check_enabled`(확인 스위치)가 꺼져 있으면 카드는 '꺼짐' 이다 — 어떤 접속도 일어나지 않는다. 확인만 켜고 설치(`apply_enabled`)는 꺼져 있으면 새 버전을 알리되 '릴리스 페이지 열기' 만 둔다(설치 단추 없음).
  · 휴대용·소스 실행은 새 압축 파일 안내와 '릴리스 페이지 열기' 뿐이다(프로그램이 스스로 바뀌지 않는다). 복구 안내가 필요한 상태는 확인 스위치와 상관없이 보인다.
  · 모든 동적 글(안내 글·오류 문구·버전)은 `display_text`(가리기가 먼저, 줄이기가 나중)를 거친다. 영문 상태 이름은 글에 담기지 않는다 — 글은 문구표(`T`)·오류 표에서만 온다.
  · 오류는 오류 표의 문구와 '하실 일'(카드용, 명령줄 꼬리 없음)과 오류 이름(진단용)을 그대로 보인다.
  · '파일에서 업데이트…'(`folder_action`, 폴더에서 업데이트 — 접속이 없어 확인 스위치와 상관없다)는 **설치(`apply_enabled`)가 켜져 있고 설치형(`inno`)이고 조용한 상태**(확인 전·최신·새 버전·실패)일 때만 보인다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ...errors import AppError, render
from .text import T, display_text

ICON_KEYS = ("disabled", "idle", "checking", "up_to_date", "available", "available_manual", "working", "booting", "healthy", "failed", "portable", "recovery", "rolled_back", "rollback_failed")
CANCELLABLE = ("DOWNLOADING", "VERIFYING", "READY", "BACKING_UP")           # 설치 도구에 넘기기 시작하기 전
FOLDER_STATES = ("IDLE", "UP_TO_DATE", "AVAILABLE", "CHECK_FAILED")             # '파일에서 업데이트…' 를 보이는 조용한 상태
WORKING_TEXT = {"DOWNLOADING": "upd_working_download", "VERIFYING": "upd_working_verify", "READY": "upd_working_ready", "BACKING_UP": "upd_working_backup", "APPLYING": "upd_working_apply",
                "HANDED_OFF": "upd_working_apply", "ROLLING_BACK": "upd_working_rollback"}
STATE_NAME = {"IDLE": "확인 전", "CHECKING": "확인 중", "UP_TO_DATE": "최신", "AVAILABLE": "새 버전", "CHECK_FAILED": "실패", "DOWNLOADING": "내려받는 중", "VERIFYING": "확인하는 중", "READY": "준비 중",
              "BACKING_UP": "백업 중", "APPLYING": "설치 시작", "HANDED_OFF": "설치 시작", "POST_UPDATE_BOOT": "새 버전 확인 중", "HEALTH_CHECK": "새 버전 확인 중", "HEALTHY": "업데이트를 마침",
              "UNHEALTHY": "복구 필요", "RECOVERY_OFFERED": "복구 필요", "ROLLING_BACK": "되돌리는 중", "ROLLED_BACK": "되돌림", "ROLLBACK_FAILED": "되돌리지 못함"}


@dataclass(frozen=True)
class CardView:
    key: str                         # ICON_KEYS 중 하나 — 아이콘·색을 고르는 열쇠(글이 아니다)
    title: str
    lines: tuple                     # 보이는 줄들(평문)
    primary: str = ""                # 주 단추 글(없으면 빈 글)
    primary_enabled: bool = False
    secondary: str = ""              # 가벼운 글 단추(복구 안내의 '나중에')
    cancel: bool = False             # 취소 단추가 보이는가
    progress: object = None          # None(알 수 없음 — 빙글빙글) 또는 0.0–1.0
    busy: bool = False               # 진행 표시가 도는가
    folder_action: str = ""          # '파일에서 업데이트…' 단추 글(없으면 빈 글) — 폴더에서 업데이트
    code: str = ""                   # 오류 이름(진단용 — 화면에는 '오류 이름: …' 줄로)
    a11y: str = ""                   # 화면 읽기 프로그램용 이름


def _version_text(version):
    shown = display_text(version, 60) if isinstance(version, str) and version else ""
    return ("v" + shown) if shown and not shown.startswith("v") else shown


def _when(last_check):
    at = getattr(last_check, "at", "") if last_check is not None else ""
    return display_text(at.replace("T", " ").replace("Z", " (UTC)"), 40) if at else ""


def _known_lines(version, last_check, notice):
    lines = [T["upd_version_line"].format(version=_version_text(version)) if version else T["upd_unknown_version"]]
    when = _when(last_check)
    lines.append(T["upd_last_checked"].format(when=when) if when else T["upd_never_checked"])
    if notice == "not_applied":
        lines.append(T["upd_notice_not_applied"])
    return lines


def _error_lines(error):
    """오류 → (줄들, 오류 이름). `AppError` 면 오류 표의 문구·카드용 하실 일, 그 밖이면 고정 문장 하나."""
    if isinstance(error, AppError):
        shown = error.rendered()
        return [display_text(shown.message, 300), display_text(shown.card_action, 400)], shown.code
    if isinstance(error, str) and error:
        shown = render(error)
        return [display_text(shown.message, 300), display_text(shown.card_action, 400)], shown.code
    return [T["upd_failed"]], ""


def _make(key, lines, **options):
    a11y = T["upd_a11y"].format(state=options.pop("a11y_state", ""))
    return CardView(key=key, title=T["upd_title"], lines=tuple(lines), a11y=a11y, **options)


def card_view(*, check_enabled, apply_enabled, install_kind, state, version, last_check=None, available_version="", summary="", error=None, progress=None, notice=""):
    """상태 한 가지 → 카드 데이터 한 장. `state` 는 상태 기계의 상태 이름(`update/machine.py`), `install_kind` 는 inno·portable·source(또는 모르면 빈 글)."""
    name = STATE_NAME.get(state, "")
    installed = install_kind in ("inno",)                       # 설치형은 Inno Setup 하나(결정 D-811 — Velopack 감지는 지웠다. `update/apply.py` 의 `INSTALLED_KINDS` 와 같은 값이고 시험이 같음을 지킨다)
    folder = T["upd_from_folder"] if apply_enabled and installed and state in FOLDER_STATES else ""
    # 복구 안내는 스위치와 상관없이 보인다(이미 깔린 새 판이 안 켜지는 사용자를 막지 않는다)
    if state in ("UNHEALTHY", "RECOVERY_OFFERED"):
        lines, code = _error_lines("UPDATE_RECOVERY_NEEDED")
        return _make("recovery", lines, primary=T["upd_recover"], primary_enabled=bool(apply_enabled), secondary=T["upd_later"], code=code, a11y_state=name)
    if state == "ROLLED_BACK":
        lines, code = _error_lines("UPDATE_ROLLED_BACK")
        return _make("rolled_back", lines, primary=T["upd_ok"], primary_enabled=True, code=code, a11y_state=name)
    if state == "ROLLBACK_FAILED":
        lines, code = _error_lines(error if isinstance(error, AppError) else "UPDATE_ROLLBACK_FAILED")
        return _make("rollback_failed", lines, primary=T["upd_ok"], primary_enabled=True, code=code, a11y_state=name)
    if state == "ROLLING_BACK":
        return _make("working", [T[WORKING_TEXT[state]]], busy=True, a11y_state=name)
    if state in ("POST_UPDATE_BOOT", "HEALTH_CHECK"):
        return _make("booting", [T["upd_booting"]], busy=True, a11y_state=name)
    if state == "HEALTHY":
        return _make("healthy", [T["upd_healthy"].format(version=_version_text(version))], primary=T["upd_ok"], primary_enabled=True, a11y_state=name)
    if state in WORKING_TEXT:
        fraction = progress if isinstance(progress, (int, float)) and not isinstance(progress, bool) and 0.0 <= progress <= 1.0 else None
        return _make("working", [T[WORKING_TEXT[state]]], busy=True, progress=fraction, cancel=state in CANCELLABLE, a11y_state=name)
    if not check_enabled:
        return _make("disabled", [T["upd_disabled"], T["upd_disabled_help"], *_known_lines(version, last_check, notice)[:1]], folder_action=folder, a11y_state=name or STATE_NAME["IDLE"])
    if state == "CHECKING":
        return _make("checking", [T["upd_checking"]], busy=True, cancel=True, a11y_state=name)
    if not installed and install_kind in ("portable", "source"):
        lines = [T["upd_portable"]]
        if state == "AVAILABLE" and available_version:
            lines.insert(0, T["upd_portable_new"].format(version=_version_text(available_version)))
        lines += _known_lines(version, last_check, notice)
        return _make("portable", lines, primary=T["upd_open_release"], primary_enabled=True, a11y_state=name)
    if state == "AVAILABLE":
        lines = [T["upd_available"].format(version=_version_text(available_version))]
        if summary:
            lines.append(display_text(summary, 500))
        if apply_enabled:
            lines.append(T["upd_backup_first"])
            return _make("available", lines, primary=T["upd_install"], primary_enabled=True, folder_action=folder, a11y_state=name)
        lines.append(T["upd_install_off"])
        return _make("available_manual", lines, primary=T["upd_open_release"], primary_enabled=True, a11y_state=name)
    if state == "UP_TO_DATE":
        lines = [T["upd_up_to_date"].format(version=_version_text(version)), *_known_lines(version, last_check, notice)[1:]]
        return _make("up_to_date", lines, primary=T["upd_check"], primary_enabled=True, folder_action=folder, a11y_state=name)
    if state == "CHECK_FAILED":
        problem, code = _error_lines(error)
        lines = [T["upd_failed"], *problem] + ([T["upd_code"].format(code=code)] if code else [])
        return _make("failed", lines, primary=T["upd_retry"], primary_enabled=True, code=code, folder_action=folder, a11y_state=name)
    return _make("idle", _known_lines(version, last_check, notice), primary=T["upd_check"], primary_enabled=True, folder_action=folder, a11y_state=name or STATE_NAME["IDLE"])


__all__ = ["CANCELLABLE", "CardView", "FOLDER_STATES", "ICON_KEYS", "STATE_NAME", "WORKING_TEXT", "card_view"]
