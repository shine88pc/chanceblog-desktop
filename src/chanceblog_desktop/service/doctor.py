"""doctor — 지금 상태를 점검한다. **읽기만 한다**(저장소·데이터 파일·설정을 바꾸지 않고, 없는 파일을 새로 만들지도 않는다. 네트워크는 `online=True` 일 때 올리기 권한 점검(`git push --dry-run`) 하나뿐).

점검마다 한 줄 결과(쉬운 한국어)와 오류 코드(문제일 때)를 돌려준다. 상태는 ok(정상) · warn(주의 — 쓰는 데는 지장 없음) · fail(고쳐야 함) · skip(점검하지 않음)이다.
점검 항목: 프로그램 버전 · Python · git · 데이터 폴더 · 설정 파일 · 글 저장소(기존 `Store.check`) · 백업 · 가져온 핵심 코드(vendor/, `scripts/sync_core.py` 의 `check` 와 같은 함수) ·
연결한 chanceblog 저장소(`inspect_repo`, 올리지 않은 commit 이 무엇인지 — `service/unpushed.py` 의 상황별 안내 한 가지) · (선택) 올리기 권한 · 네이버 블로그 프로필 · 이어서 처리할 글(COMMITTED·PUSHED)·공개된 글에 남은 발행 기록.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ..content import status as st
from ..content.profiles import KEYS as NAVER_KEYS
from ..content.store import Store
from ..errors import AppError, render
from . import unpushed
from .journal import Journal
from .projects import list_backups, list_projects

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Check:
    name: str
    status: str           # ok · warn · fail · skip
    code: str             # 문제일 때의 오류 코드('' 이면 없음)
    message: str          # 한 줄 결과
    action: str = ""      # 문제일 때 하실 일(오류 표의 문구)

    def to_dict(self):
        return {"name": self.name, "status": self.status, "code": self.code, "message": self.message, "action": self.action}


def check(name, status, code, message, action=None):
    """점검 결과 한 줄. 문제(주의·실패)에 오류 코드가 있으면 하실 일을 오류 표(TROUBLESHOOTING.md)에서 붙인다.
    `action` 을 주면(빈 글이어도) 표의 일반 문구 대신 그 말을 쓴다 — 지금 상황에 맞는 한 가지 안내가 일반 문구와 어긋나 보이지 않게."""
    if action is None:
        action = render(code).action if code and status in ("warn", "fail") else ""
    return Check(name, status, code, message, action)


def app_version():
    try:
        return (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip() or "알 수 없음"
    except OSError:
        return "알 수 없음"


def _load_sync_core():
    """`scripts/sync_core.py` 를 파일 경로로 불러온다(같은 검사 함수를 쓰려고). 설치본처럼 그 파일이 없으면 None."""
    path = REPO_ROOT / "scripts" / "sync_core.py"
    if not path.is_file():
        return None
    name = "chanceblog_desktop_sync_core"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return module


def _vendor_ref():
    try:
        ref = json.loads((REPO_ROOT / "vendor" / "VENDOR.json").read_text(encoding="utf-8")).get("ref", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return ref[:12] if isinstance(ref, str) else ""


def _guard(name, work):
    try:
        return work()
    except AppError as error:
        shown = error.rendered()
        return Check(name, "fail", error.code, shown.message, shown.action)


def _check_version():
    return check("프로그램 버전", "ok", "", f"버전 {app_version()}")


def _check_python():
    found = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info < (3, 10):
        return check("Python", "fail", "UNEXPECTED_ERROR", f"Python {found} 은 너무 낮습니다 — 3.10 이상이 필요합니다.")
    return check("Python", "ok", "", f"Python {found}")


def _check_git(ctx):
    done = ctx.git(os.getcwd(), ["--version"])
    if done.returncode != 0:
        return check("git", "fail", "GIT_NOT_INSTALLED", "git 을 실행하지 못했습니다.")
    return check("git", "ok", "", done.stdout.strip() or "git 사용 가능")


def _check_data_dir(ctx):
    root = ctx.workspace.root
    if not root.exists():
        return check("데이터 폴더", "ok", "", f"아직 없습니다 — 처음 글을 만들 때 만들어집니다: {root}")
    if not os.access(root, os.W_OK):
        return check("데이터 폴더", "fail", "FILE_WRITE_FAILED", f"쓸 수 없는 폴더입니다: {root}")
    return check("데이터 폴더", "ok", "", f"쓸 수 있습니다: {root}")


def _check_settings(ctx):
    path = ctx.settings.path
    if not path.exists():
        return check("설정 파일", "ok", "", "아직 없습니다 — 저장소를 연결하거나 블로그 프로필을 정하면 만들어집니다.")
    ctx.settings.repo_path()
    ctx.settings.naver_profile_dicts()
    return check("설정 파일", "ok", "", "읽을 수 있습니다.")


def _store_exists(ctx):
    """글 저장소 파일이 있고 비어 있지 않은가. 없거나 빈 파일이면 열 때 저장소가 새로 만들어지므로(쓰기) 점검은 열지 않는다."""
    path = ctx.workspace.store_path
    return path.exists() and path.stat().st_size > 0


def _check_store(ctx):
    path = ctx.workspace.store_path
    if not _store_exists(ctx):
        return check("글 저장소", "ok", "", "아직 없습니다 — 처음 글을 만들면 생깁니다.")
    with Store.open(path) as store:                              # 파일이 이 프로그램의 것이 아니거나 깨졌거나 더 새로우면 여기서 AppError(파일은 건드리지 않는다)
        problems = store.check()
        count = len(store.list())
    if problems:
        return check("글 저장소", "fail", "STORE_CORRUPT", f"점검에서 문제 {len(problems)}개를 찾았습니다: {problems[0]}")
    return check("글 저장소", "ok", "", f"글 {count}개, 이상 없습니다.")


def _check_backups(ctx):
    found = list_backups(ctx)
    if not found:
        return check("백업", "warn", "", "백업이 아직 없습니다 — `backup` 으로 만들 수 있습니다.")
    return check("백업", "ok", "", f"백업 {len(found)}개(가장 최근: {found[0].name})")


def _check_core():
    module = _load_sync_core()
    if module is None:
        return check("핵심 코드(vendor/)", "skip", "", "점검 도구(scripts/sync_core.py)가 없어 점검하지 않았습니다.")
    problems = module.check()
    if problems:
        return check("핵심 코드(vendor/)", "fail", "CORE_CODE_MISMATCH", f"가져온 핵심 코드가 기록과 다릅니다({len(problems)}곳): {problems[0]}")
    ref = _vendor_ref()
    return check("핵심 코드(vendor/)", "ok", "", "가져온 핵심 코드가 기록(VENDOR.json)과 같습니다" + (f" — 가져온 커밋 {ref}" if ref else "") + ".")


def _check_repo(ctx):
    repo = ctx.repo_path_or_none()
    if repo is None:
        return check("연결한 chanceblog 저장소", "warn", "PAGES_LOCAL_REPO_INVALID", "연결한 저장소가 없습니다 — GitHub Pages 에 올리려면 `connect 폴더` 로 연결합니다.")
    info = ctx.backend.inspect(repo)
    situation = unpushed.describe(ctx, repo)
    if situation.ahead:                                       # 올리지 않은 commit — 앱이 올리다 멈춘 글인지·글이 겹쳤는지·앱이 모르는 commit 인지 가려 한 가지 안내만 한다
        return check("연결한 chanceblog 저장소", "warn", "PAGES_LOCAL_REPO_DIVERGED", f"연결됨({info.branch} 브랜치) — 그런데 올리지 않은 commit 이 {situation.ahead}개 있습니다.", unpushed.action_text(situation))
    return check("연결한 chanceblog 저장소", "ok", "", f"연결됨 — {info.branch} 브랜치, 저장하지 않은 변경 없음.")


def _check_push_access(ctx, online):
    if not online:
        return check("올리기 권한", "skip", "", "점검하지 않았습니다 — 네트워크를 쓰므로 `doctor --online` 으로 합니다(실제로 올리지는 않습니다).")
    repo = ctx.repo_path_or_none()
    if repo is None:
        return check("올리기 권한", "skip", "", "연결한 저장소가 없어 점검하지 않았습니다.")
    ctx.backend.check_push_access(repo)
    return check("올리기 권한", "ok", "", "올릴 수 있습니다(`git push --dry-run` — 실제로는 올리지 않았습니다).")


def _check_naver(ctx):
    checks = []
    for key in NAVER_KEYS:
        label = "네이버 " + key[-1].upper()
        try:
            profile = ctx.settings.naver_profile(key)
        except AppError as error:
            if error.code != "NAVER_PROFILE_MISSING":
                raise
            checks.append(check(label + " 프로필", "skip", "", "프로필이 없습니다 — 필요할 때 `naver-profile set` 으로 정합니다."))
            continue
        checks.append(check(label + " 프로필", "ok", "", f"{profile.display_name} — {profile.blog_url}"))
    return checks


def _check_pending(ctx):
    if not _store_exists(ctx):
        return []
    notes = []
    repo = ctx.repo_path_or_none()
    situation = unpushed.describe(ctx, repo) if repo is not None else unpushed.Situation(0, ())
    entries = {entry.project_id: entry for entry in situation.entries}
    journal = Journal(ctx.workspace.journal_dir)
    for row in list_projects(ctx):
        status = row.statuses.get("github_pages")
        short = row.project_id[:8]
        entry = entries.get(row.project_id)
        if status == st.APPROVED and entry is not None:
            notes.append(check("이어서 처리할 글", "warn", "PAGES_LOCAL_REPO_DIVERGED",
                               f"{row.title} — 올리다가 기록(commit) 직후에 멈춘 흔적이 있습니다(이 글의 commit 하나가 기록 없이 남음, 번호 {short}). {unpushed.entry_text(situation, entry)}", ""))
        elif status == st.COMMITTED:
            try:
                record = journal.read(row.project_id)
            except AppError:
                record = None
            if record is not None and repo is not None and ctx.backend.on_remote(repo, record.path):
                notes.append(check("이어서 처리할 글", "warn", "PAGES_DEPLOY_NOT_VISIBLE",
                                   f"{row.title} — 이미 원격 main 에 올라가 있는데 올림 기록을 마치기 전에 멈췄습니다(번호 {short}). `publish-pages {short} --yes` 로 기록을 마치고 공개 확인을 합니다(되돌리지 않습니다).", ""))
            elif entry is not None:
                notes.append(check("이어서 처리할 글", "warn", "PAGES_LOCAL_REPO_DIVERGED", f"{row.title} — 글 기록은 있지만 아직 올리지 않았습니다(번호 {short}). {unpushed.entry_text(situation, entry)}", ""))
            else:
                notes.append(check("이어서 처리할 글", "warn", "PAGES_LOCAL_REPO_DIVERGED",
                                   f"{row.title} — 글 기록은 있지만 아직 올리지 않았습니다(번호 {short}). `publish-pages {short} --yes` 로 이어서 올리거나 올리지 않고 되돌리려면 `publish-pages {short} --cancel --yes` 합니다.", ""))
        elif status == st.PUSHED:
            notes.append(check("이어서 처리할 글", "warn", "PAGES_DEPLOY_NOT_VISIBLE", f"{row.title} — 올렸지만 공개 확인이 남았습니다. `check-deploy {short}` 로 확인합니다."))
        elif status == st.PUBLISHED and _leftover_record(journal, row.project_id):
            notes.append(check("남은 발행 기록", "warn", "", f"{row.title} — 공개된 글인데 발행 기록 파일이 남아 있습니다(기록을 지우기 직전에 멈춘 흔적 — 해롭지 않습니다). `check-deploy {short}` 를 한 번 실행하면 그 기록만 정리합니다."))
        elif row.error:
            notes.append(check("글 읽기", "fail", row.error, f"{row.title} — 이 글을 읽을 수 없습니다(번호 {short})."))
    return notes


def _leftover_record(journal, project_id):
    """그 글의 발행 기록이 남아 있는가(읽을 수 없는 기록은 '있다' 로 보지 않는다 — 건드리지 않는 것과 같다)."""
    try:
        return journal.read(project_id) is not None
    except AppError:
        return False


def run_doctor(ctx, *, online=False):
    """모든 점검을 돌려 Check 목록으로 돌려준다. 점검 하나가 AppError 로 막혀도 나머지는 계속한다."""
    results = []
    for name, work in (("프로그램 버전", _check_version), ("Python", _check_python), ("git", lambda: _check_git(ctx)), ("데이터 폴더", lambda: _check_data_dir(ctx)),
                       ("설정 파일", lambda: _check_settings(ctx)), ("글 저장소", lambda: _check_store(ctx)), ("백업", lambda: _check_backups(ctx)), ("핵심 코드(vendor/)", _check_core),
                       ("연결한 chanceblog 저장소", lambda: _check_repo(ctx)), ("올리기 권한", lambda: _check_push_access(ctx, online)), ("네이버 프로필", lambda: _check_naver(ctx)),
                       ("이어서 처리할 글", lambda: _check_pending(ctx))):
        found = _guard(name, work)
        results.extend(found if isinstance(found, list) else [found])
    return results


def doctor_ok(results):
    return not any(item.status == "fail" for item in results)
