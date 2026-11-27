"""설치 종류별 적용 어댑터(UPDATE 설계서 3-8) — 앱이 **설치 도구를 띄우는 유일한 파일**이다(U-4). 설치 도구는 Inno Setup 이다(결정 D-811, 설치 도구 시험 2차 결과) — Velopack 어댑터는 만들지 않는다.

여기 있는 것:
  · `ApplyAdapter` — 어댑터가 지킬 모양. `apply` 의 **첫 문장은 스위치 관문**(`capabilities.require_update_apply`)이고 하위 클래스는 `_apply` 만 채운다 — 꺼져 있으면 `UPDATE_DISABLED` 로 하위 프로세스·파일 쓰기 전에 끝난다.
  · `InnoAdapter`(`inno`) — 서명·해시를 확인한 Setup 을 `launch_setup` 으로 **끊어서** 띄운다(`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CLOSEAPPLICATIONS /LOG=…` 고정 목록). 앱은 곧바로 정상 종료하고 Setup 이 닫기·교체를 맡는다.
    복구(`recovery=True`)는 보관한 이전 Setup 을 같은 방식으로(낮은 판이라 방향 검사만 반대).
  · `UnsupportedKindAdapter`(휴대용·소스 실행·모르는 종류) — 프로세스가 스스로 바뀌지 않는다. `UPDATE_NOT_INSTALLED_KIND`.
  · `NotSupportedAdapter`(`velopack`) — 매니페스트는 읽지만(이미 서명된 매니페스트의 모양을 갑자기 깨지 않으려고) 적용 어댑터는 없다. 아무것도 실행하지 않고 `UPDATE_APPLY_FAILED`(이유 `kind_not_supported`).
  · `launch_setup` — **하위 프로세스를 띄우는 호출이 있는 함수는 이것 하나**다(허용 목록 시험이 이 한 곳만 센다). 어댑터에만 기대지 않도록 Setup 의 파일 이름(`SETUP_NAME`)·네트워크(UNC) 경로 여부도 여기서 한 번 더 본다(`_checked_paths`).
  · `setup_for` — 받은 파일 묶음이 이 설치 종류의 이 판의 것인지 보는 순수 확인. 어댑터가 부르고, 흐름(`apply_update`)도 백업을 만들기 전에 같은 함수를 부른다.

규칙(시험이 소스를 훑어 지킨다): 인자는 **고정 목록**이고 셸을 거치지 않는다(`shell=False`, 명령은 문자열 한 줄이 아니라 목록 하나). 경로는 우리가 만든 임시 폴더의 우리가 정한 이름뿐이다(Setup 은 매니페스트가 정한 이름 — `ChanceBlogDesktop-<이 판>-Setup.exe`, 로그는 같은 폴더의 고정 이름 둘 중 하나).
이 파일의 가져오기는 `subprocess` 를 **별칭 없이 `import subprocess` 한 줄**로만 가져오고(`from subprocess import …`·`import subprocess as …` 0) 하위 프로세스 호출은 `launch_setup` 안의 `subprocess.Popen` 하나뿐이다 — 시험이 별칭표를 풀어 호출 글을 모두 본다.
하위 프로세스의 출력은 읽지 않고(표준 입출력은 모두 NUL), **종료 코드도 기다리지 않는다** — 앱이 먼저 끝나므로 볼 수 없다. 그래서 어댑터가 판정하는 것은 '띄웠다/못 띄웠다'(실행 파일 없음·`OSError`) 하나이고,
Setup 이 조용히 실패한 경우는 다음 시작의 시작 점검(`update/state.note_boot` 의 '적용되지 않았어요'·연속 두 번 정상 표식 없음 → 복구 안내)이 잡는다. 실패는 모두 `UPDATE_APPLY_FAILED` 이고 기록에는 이유 이름 하나뿐이다(경로·입력값·오류 글 0).
`InnoAdapter` 는 띄우기 **직전에 파일을 다시 해시**한다(검증과 실행 사이의 파일 교체 — 설계서 U3·U4 — 와 복구 경로의 빈 틈, 독립 검증 S I8) — 호출하는 흐름(`apply_update`)이 백업 전에 한 번 더 확인하지만 백업은 시간이 걸린다.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .. import capabilities
from ..errors import AppError
from . import source, versions
from . import manifest as manifest_module

INSTALLED_KINDS = ("inno",)                         # 적용 어댑터가 있는 설치 종류(결정 D-811 — Inno Setup)
READ_ONLY_INSTALLER_KINDS = ("velopack",)           # 매니페스트가 이름으로 부를 수는 있지만(읽기) 이 앱에는 적용 어댑터가 없다 — 적용은 UPDATE_APPLY_FAILED(kind_not_supported)
UNSUPPORTED_KINDS = ("portable", "source", "")
# 설치 종류마다 내려받아야 하는 파일의 역할: Inno 는 설치 파일 하나(`setup`). 휴대용 압축 파일은 앱이 받지 않는다. (`package`·`feed` 는 Velopack 용이라 Inno 릴리스에는 필요 없다 — 있어도 앱은 받지 않는다.)
REQUIRED_ROLES = {"inno": ("setup",)}

# Inno Setup 무음 실행 인자(설계서 3-8) — **고정 목록**이다. 설치 구현 갈래(`packaging/pkgcommon.py` 의 `INNO_SILENT_UPDATE_ARGS` — 같은 다섯 인자, 같은 순서)와 같은 값이어야 하고, 그 짝 시험(`test_update_inno`)이 둘이 같음을 지킨다.
#   /VERYSILENT 진행 창도 띄우지 않음 · /SUPPRESSMSGBOXES 안내 상자 0(기본 답) · /NORESTART 운영체제 재시작 0 · /SP- 시작 확인창('이 프로그램을 설치합니다. 계속하시겠습니까?')을 끈다(러너 측정 M05·M09·M19 이 모두 넣은 인자 — 설치 쪽과 같게) ·
#   /CLOSEAPPLICATIONS 아직 켜져 있는 앱은 Setup 이 닫는다(앱이 먼저 끝나는 것이 1차, 이것은 2차 — 효과 재측정은 릴리스 갈래 러너 시험 몫).
INNO_SILENT_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CLOSEAPPLICATIONS")
LOG_SWITCH = "/LOG="                                # Inno 가 로그 파일을 우리가 정한 경로에 쓰게 한다(우리는 읽지 않는다 — 사람이 진단할 때 쓴다)
UPDATE_LOG_NAME = "setup-update.log"                # Setup 과 같은 폴더의 고정 이름 둘 — 업데이트와 복구가 서로의 로그를 덮어쓰지 않게 갈린다
RECOVERY_LOG_NAME = "setup-recovery.log"
SETUP_NAME = re.compile(r"ChanceBlogDesktop-[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[1-9][0-9]*)?-Setup\.exe", re.ASCII)      # 매니페스트 검사(`manifest._check_files`)의 Setup 이름 모양과 같다
DETACHED_PROCESS = 0x00000008                       # 윈도 프로세스 생성 플래그: 부모의 콘솔에 붙지 않는다
CREATE_NEW_PROCESS_GROUP = 0x00000200               # 부모의 Ctrl+C 가 따라가지 않는다
IS_WINDOWS = os.name == "nt"                        # 시험이 `mock.patch.object` 로 바꿔 두 모양을 다 본다


def _refuse(reason):
    return AppError("UPDATE_APPLY_FAILED", detail=reason)


class ApplyAdapter:
    """설치 종류 하나의 적용 방법. 하위 클래스는 `_apply` 만 채운다 — `apply` 의 첫 문장(스위치 관문)은 바꾸지 않는다."""
    kind = ""

    def apply(self, staged, *, from_version, to_version, recovery=False):
        """검증된 파일(`staged`)을 설치 도구에 넘긴다. 성공하면 앱은 곧 정상 종료한다. 실패는 `AppError`(`UPDATE_APPLY_FAILED` 등)."""
        capabilities.require_update_apply("업데이트 설치")
        return self._apply(staged, from_version=from_version, to_version=to_version, recovery=recovery)

    def _apply(self, staged, *, from_version, to_version, recovery):
        raise NotImplementedError


class UnsupportedKindAdapter(ApplyAdapter):
    """휴대용·소스 실행 — 프로그램이 스스로 바뀌지 않는다. 새 압축 파일을 받아 풀어 쓰는 안내만 한다."""

    def __init__(self, kind=""):
        self.kind = kind if kind in UNSUPPORTED_KINDS else ""

    def _apply(self, staged, *, from_version, to_version, recovery):
        raise AppError("UPDATE_NOT_INSTALLED_KIND", detail=f"kind:{self.kind or 'unknown'}")


class NotSupportedAdapter(ApplyAdapter):
    """매니페스트가 이름으로 부르지만 이 앱에 적용 어댑터가 없는 설치 도구(`velopack`) — 아무것도 실행하지 않고 거절한다(fail closed)."""

    def __init__(self, kind):
        self.kind = kind

    def _apply(self, staged, *, from_version, to_version, recovery):
        raise _refuse("kind_not_supported")


# ---- Inno Setup ----------------------------------------------------------------------------------------------------------------------------------
def spawn_options():
    """끊어서 띄우는 옵션 — 앱이 곧 끝나도 Setup 이 이어지게 하고(윈도: 새 프로세스 그룹·콘솔에 붙지 않음, 그 밖: 새 세션) 아무것도 상속·읽지 않게 한다(핸들 상속 끊김·표준 입출력 모두 NUL)."""
    options = {"shell": False, "close_fds": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WINDOWS:
        options["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return options


def _same_place(left, right):
    return os.path.normcase(os.path.normpath(os.fspath(left))) == os.path.normcase(os.path.normpath(os.fspath(right)))


def _is_path_text(value):
    """경로 글로 쓸 수 있는 값인가 — 글(또는 글을 내는 `PathLike`)이고 비어 있지 않고 널 문자가 없다(그 밖의 값은 거절하는 쪽)."""
    try:
        text = os.fspath(value)
    except TypeError:
        return False
    return isinstance(text, str) and bool(text) and "\x00" not in text


def _is_network_or_device_path(text):
    """윈도 네트워크(UNC)·장치 이름 공간 꼴인가 — 앞 두 글자가 모두 경로 구분자(`\\\\서버\\공유`·`\\\\?\\`·`\\\\.\\`·`//`). 설치 도구는 이 PC 의 데이터 폴더 안에서만 띄운다."""
    return len(text) >= 2 and text[0] in "\\/" and text[1] in "\\/"


def _checked_paths(setup_path, log_path):
    """띄우기 직전의 경로 모양 검사 → `(Setup, 로그)` 의 글. 둘 다 절대 경로이고(UNC·장치 이름 공간 아님) Setup 의 파일 이름은 `SETUP_NAME` 규칙 그대로이며(이름 변형·끝의 점·공백·`:` 스트림·다른 확장자 거절) 로그는 Setup 과 같은 폴더의 고정 이름 둘 중 하나이고
    Setup 은 링크가 아닌 보통 파일이다(그 밖은 `UPDATE_APPLY_FAILED`, 이유 이름 하나). 이름 규칙은 어댑터(`setup_for`)가 이미 보는 것을 **여기서도** 본다 — `launch_setup` 이 'Setup 파일 하나만' 띄운다는 보증이 어댑터 하나에만 기대지 않게 하는 방어 한 겹(독립 검증 S R6)."""
    try:
        setup, log = os.fspath(setup_path), os.fspath(log_path)
    except TypeError:
        raise _refuse("path_type") from None
    if not isinstance(setup, str) or not isinstance(log, str) or not setup or not log or "\x00" in setup or "\x00" in log:
        raise _refuse("path_type")
    if not os.path.isabs(setup) or not os.path.isabs(log):
        raise _refuse("path_not_absolute")
    if _is_network_or_device_path(setup) or _is_network_or_device_path(log):
        raise _refuse("path_unc")
    if SETUP_NAME.fullmatch(os.path.basename(setup)) is None:
        raise _refuse("setup_name")
    if os.path.basename(log) not in (UPDATE_LOG_NAME, RECOVERY_LOG_NAME) or not _same_place(os.path.dirname(setup), os.path.dirname(log)):
        raise _refuse("log_path")
    if source._regular_size(setup) is None:
        raise _refuse("setup_not_a_file")
    return setup, log


def inno_command(setup_path, log_path):
    """Setup 을 띄우는 명령 — **목록 하나**: 실행 파일, 고정 인자들, 로그 인자 하나(`/LOG=` + 우리가 정한 경로). 문자열 한 줄로 이어 붙이지 않는다."""
    setup, log = _checked_paths(setup_path, log_path)
    return [setup, *INNO_SILENT_ARGS, LOG_SWITCH + log]


def launch_setup(setup_path, log_path):
    """검증된 Setup 을 끊어서 띄운다 — **앱이 하위 프로세스로 설치 도구를 띄우는 유일한 곳**(허용 목록 시험이 이 한 곳을 센다). 첫 문장은 스위치 관문이라 꺼져 있으면 `UPDATE_DISABLED` 로 아무것도 하지 않는다.
    프로세스 개체는 쓰지 않는다: 출력을 읽지 않고 기다리지도 않으며 종료 코드를 보지 않는다(앱이 먼저 끝난다). 띄우지 못하면(`OSError`·`ValueError`) `UPDATE_APPLY_FAILED`(이유 `launch_failed`, 오류 글·경로 0)."""
    capabilities.require_update_apply("업데이트 설치 도구 띄우기")
    command = inno_command(setup_path, log_path)
    try:
        subprocess.Popen(command, **spawn_options())
    except (OSError, ValueError):
        raise _refuse("launch_failed") from None


def setup_for(staged, from_version, to_version, recovery=False):
    """받은 파일 묶음이 정말 **이 설치 종류의 이 판**이고 방향(올림·복구는 내림)이 맞으며 Setup 이 우리가 만든 폴더의 매니페스트가 정한 이름(그 이름 속 판도 이 판)이고 받은 파일의 값이 모두 경로 글이다 → Setup 경로. 순수 확인이라 아무것도 쓰거나 띄우지 않는다.
    어댑터가 믿기 전에 하는 마지막 검사이고, 흐름(`apply_update`)도 **백업을 만들기 전에** 같은 함수를 부른다(독립 검증 S R3 — 받은 파일의 경로·값 모양 어긋남이 백업과 표식 뒤에야 걸리거나 생 예외로 새던 틈). 어긋나면 `UPDATE_APPLY_FAILED`(이유 이름 하나)."""
    if (not isinstance(staged, source.StagedUpdate) or not isinstance(staged.files, dict) or not isinstance(staged.manifest, manifest_module.Manifest)
            or not isinstance(staged.folder, (str, os.PathLike))):
        raise _refuse("staged_invalid")
    manifest = staged.manifest
    if manifest.installer_kind != "inno":
        raise _refuse("kind_mismatch")
    if manifest.version != to_version:
        raise _refuse("version_mismatch")
    try:
        order = versions.compare(to_version, from_version)
    except ValueError:
        raise _refuse("version_invalid") from None
    if (order >= 0) if recovery else (order <= 0):
        raise _refuse("direction")
    entry = manifest.file("setup")
    path = staged.files.get("setup")
    if entry is None or path is None:
        raise _refuse("setup_missing")
    if not isinstance(path, (str, os.PathLike)):
        raise _refuse("setup_path")
    try:
        shown = os.fspath(path)
        well_placed = isinstance(shown, str) and SETUP_NAME.fullmatch(entry.name) is not None and Path(shown).name == entry.name and _same_place(Path(shown).parent, staged.folder)
    except (TypeError, ValueError):
        shown, well_placed = "", False
    if not well_placed:
        raise _refuse("setup_path")
    if _is_network_or_device_path(shown):
        raise _refuse("path_unc")                                 # 받은 폴더가 네트워크(UNC) 꼴이면 백업을 만들기 전에 거절한다 — 어차피 `launch_setup` 이 거절할 것이다
    if entry.name != f"ChanceBlogDesktop-{to_version}-Setup.exe":
        raise _refuse("setup_version")                           # 이름이 규칙 모양이어도 이 판의 이름이어야 한다(다른 판의 Setup 을 이 판으로 띄우지 않는다 — 독립 검증 Q R3)
    for item in manifest.files:
        other = staged.files.get(item.role)
        if item.role != "setup" and other is not None and not _is_path_text(other):
            raise _refuse("staged_invalid")                       # 재해시가 읽을 다른 역할의 값도 경로 글이어야 한다(아니면 `verify_staged` 에서 생 예외)
    return path


class InnoAdapter(ApplyAdapter):
    """Inno Setup 적용 — 검증된 Setup 을 무음으로 끊어 띄운다(설계서 3-8). 앱은 곧 정상 종료해야 한다(그 일은 호출하는 화면 쪽 U-5 의 몫이고, 못 끝나도 `/CLOSEAPPLICATIONS` 가 Setup 쪽에서 닫는다)."""
    kind = "inno"

    def _apply(self, staged, *, from_version, to_version, recovery):
        setup = setup_for(staged, from_version, to_version, recovery)
        source.verify_staged(staged)                         # 띄우기 **직전**의 재해시 — 틀리면 `UPDATE_SIGNATURE_INVALID`(복구 경로도 같다)
        launch_setup(setup, Path(setup).with_name(RECOVERY_LOG_NAME if recovery else UPDATE_LOG_NAME))
        return True


def adapter_for(kind):
    """설치 종류 → 어댑터. 모르는 종류는 지원하지 않는 쪽(`UnsupportedKindAdapter`)으로 닫는다."""
    if isinstance(kind, str) and kind in INSTALLED_KINDS:
        return InnoAdapter()
    if isinstance(kind, str) and kind in READ_ONLY_INSTALLER_KINDS:
        return NotSupportedAdapter(kind)
    return UnsupportedKindAdapter(kind if isinstance(kind, str) and kind in UNSUPPORTED_KINDS else "")


__all__ = ["ApplyAdapter", "INNO_SILENT_ARGS", "INSTALLED_KINDS", "InnoAdapter", "LOG_SWITCH", "NotSupportedAdapter", "READ_ONLY_INSTALLER_KINDS", "RECOVERY_LOG_NAME", "REQUIRED_ROLES", "SETUP_NAME",
           "UNSUPPORTED_KINDS", "UPDATE_LOG_NAME", "UnsupportedKindAdapter", "adapter_for", "inno_command", "launch_setup", "setup_for", "spawn_options"]
