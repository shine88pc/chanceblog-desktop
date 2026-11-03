"""작업 공간(사용자 데이터 폴더)·설정 파일·시험에서 바꿔 끼우는 부품 묶음(Context).

사용자 데이터(원고·설정·백업·발행 기록)는 PC 의 사용자 데이터 폴더에만 둔다 — Windows 는 `%LOCALAPPDATA%/ChanceblogDesktop`(docs/ARCHITECTURE.md §10).
저장소(이 프로그램의 저장소든 연결한 chanceblog 든) 안에는 절대 두지 않는다: 고른 폴더가 git 저장소 안이거나 프로그램 폴더 안이면 DATA_DIR_UNSAFE 로 멈춘다(AGENTS.md 규칙 2).
설정 파일(`settings.json`)에는 키·토큰을 두지 않는다 — 연결한 chanceblog 폴더 경로와 네이버 블로그 프로필뿐이고, 이 파일은 저장소 밖에 있으므로 절대경로를 적어도 된다.
이 모듈이 읽는 환경 변수는 `CHANCEBLOG_DESKTOP_DATA`·`CHANCEBLOG_LOCAL_REPO` 와 폴더 위치(`LOCALAPPDATA`·`XDG_DATA_HOME`)뿐이다(키는 읽지 않는다 — 시험이 지킨다).
"""
from __future__ import annotations

import errno
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from ..content.profiles import KEYS as NAVER_KEYS
from ..content.profiles import NaverProfile
from ..content.store import Store
from ..core import vendor_dir
from ..errors import AppError
from ..publish import gitrepo

APP_DIR_NAME = "ChanceblogDesktop"
ENV_DATA_DIR = "CHANCEBLOG_DESKTOP_DATA"
ENV_REPO = "CHANCEBLOG_LOCAL_REPO"
SETTINGS_SCHEMA = 1
STORE_NAME = "chanceblog.db"


def utc_now():
    return datetime.now(timezone.utc)


def default_data_dir(env=None, *, windows=None, home=None):
    """사용자 데이터 폴더의 기본 위치 — Windows 는 %LOCALAPPDATA%/ChanceblogDesktop, 그 밖은 XDG 데이터 폴더(시험·개발용)."""
    env = os.environ if env is None else env
    windows = (os.name == "nt") if windows is None else windows
    home = Path(home) if home else Path.home()
    base = (env.get("LOCALAPPDATA") or str(home / "AppData" / "Local")) if windows else (env.get("XDG_DATA_HOME") or str(home / ".local" / "share"))
    return Path(base) / APP_DIR_NAME


def unsafe_reason(path):
    """그 폴더를 사용자 데이터 폴더로 쓰면 안 되는 이유(없으면 ''). git 저장소 안이거나 프로그램 폴더 안이면 원고·설정이 저장소에 올라갈 수 있다."""
    target = Path(os.path.realpath(path))
    app_root = Path(os.path.realpath(vendor_dir().parent))
    if target == app_root or app_root in target.parents:
        return "프로그램 폴더 안이다"
    for parent in (target, *target.parents):
        if (parent / ".git").exists():
            return "git 저장소 안이다"
    return ""


def _write_error(error, path):
    number = getattr(error, "errno", None)
    return AppError("DISK_FULL" if number == errno.ENOSPC else "FILE_WRITE_FAILED", {"경로": str(path)}, detail=f"{type(error).__name__}: {error.strerror or error}"[:200])


def _write_durably(temp, payload):
    """임시 파일에 다 쓰고 디스크까지 내려보낸(`fsync`) 뒤에 닫는다 — 이름을 바꾼 직후 전원이 나가도(매일 23:00 강제 재부팅) 내용이 비어 있는 파일이 남지 않게. 줄바꿈은 그대로(`O_BINARY`)."""
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path, data):
    """JSON 파일을 임시 파일에 쓰고 디스크에 내려보낸 뒤(`fsync`) 이름을 바꿔 넣는다 — 쓰다 멈추거나 전원이 나가도 옛 파일이 그대로 남고, 새 파일은 내용이 다 쓰인 것만 자리를 차지한다."""
    path = Path(path)
    temp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_durably(temp, (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        os.replace(temp, path)
    except OSError as error:
        problem = _write_error(error, path)
        try:
            temp.unlink(missing_ok=True)
        except OSError as leftover:                       # 못 지운 임시 파일도 숨기지 않고 오류 세부에 적는다
            problem.detail += f" | 임시 파일도 지우지 못했다({type(leftover).__name__})"
        raise problem from None


def keep_bad_copy(path):
    """읽을 수 없는 파일을 지우지 않고 `.bak` 이름으로 옮겨 둔다(그 위에 새로 쓰기 전에). 옮겼으면 True, 파일이 없었으면 False. 못 옮기면 FILE_WRITE_FAILED."""
    path = Path(path)
    target = path.with_name(path.name + ".bak")
    try:
        os.replace(path, target)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise _write_error(error, path) from None
    return True


class Workspace:
    """사용자 데이터 폴더와 그 안의 파일 위치."""

    def __init__(self, root):
        self.root = Path(root)

    @classmethod
    def resolve(cls, data_dir=None, *, env=None):
        """`--data-dir` > 환경 변수 CHANCEBLOG_DESKTOP_DATA > 기본 위치. 저장소 안이면 DATA_DIR_UNSAFE."""
        env = os.environ if env is None else env
        chosen = data_dir or env.get(ENV_DATA_DIR) or default_data_dir(env)
        root = Path(os.path.expanduser(str(chosen)))
        reason = unsafe_reason(root)
        if reason:
            raise AppError("DATA_DIR_UNSAFE", {"경로": str(root)}, detail=reason)
        return cls(root)

    @property
    def store_path(self):
        return self.root / STORE_NAME

    @property
    def settings_path(self):
        return self.root / "settings.json"

    @property
    def connections_path(self):
        return self.root / "connections.json"            # 연결 설정(키 항목의 이름·상태 같은 메타데이터만 — 키 값은 보관소에만 있다)

    @property
    def quota_path(self):
        return self.root / "quota_state.json"            # 한도 사용량 기록(묶음별 창·막힘 해제 시각 — 키 값 없음)

    @property
    def locks_dir(self):
        return self.root / "locks"

    @property
    def backups_dir(self):
        return self.root / "backups"

    @property
    def journal_dir(self):
        return self.root / "publish"

    def ensure(self):
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise _write_error(error, self.root) from None


def _bad_settings(path, why):
    return AppError("SETTINGS_INVALID", {"파일": Path(path).name}, detail=why)


class Settings:
    """설정 파일 — 연결한 chanceblog 폴더 경로와 네이버 블로그 프로필(A·B). 모르는 칸이 있거나 모양이 틀리면 읽지 않고 SETTINGS_INVALID(파일은 건드리지 않는다)."""

    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        if not self.path.exists():
            return {"schema": SETTINGS_SCHEMA, "repo_path": "", "naver_profiles": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:             # UnicodeDecodeError 는 ValueError 다
            raise _bad_settings(self.path, f"읽을 수 없다: {type(error).__name__}") from None
        profiles = raw.get("naver_profiles") if isinstance(raw, dict) else None
        if (not isinstance(raw, dict) or set(raw) != {"schema", "repo_path", "naver_profiles"} or raw["schema"] != SETTINGS_SCHEMA or not isinstance(raw["repo_path"], str)
                or not isinstance(profiles, dict) or not set(profiles) <= set(NAVER_KEYS) or not all(isinstance(value, dict) for value in profiles.values())):
            raise _bad_settings(self.path, "칸이 올바르지 않다")
        return raw

    def repo_path(self):
        return self._read()["repo_path"]

    def save_repo_path(self, path):
        data = self._read()
        data["repo_path"] = str(path)
        write_json(self.path, data)

    def naver_profile(self, key):
        """저장된 블로그 프로필. 없으면 NAVER_PROFILE_MISSING, 저장된 값이 올바르지 않으면 SETTINGS_INVALID."""
        raw = self._read()["naver_profiles"].get(key)
        if raw is None:
            raise AppError("NAVER_PROFILE_MISSING", {"블로그": key})
        try:
            profile = NaverProfile.from_dict(raw)
        except AppError:
            raise _bad_settings(self.path, f"프로필 {key} 의 값이 올바르지 않다") from None
        if profile.key != key:
            raise _bad_settings(self.path, f"프로필 {key} 의 구분이 다르다")
        return profile

    def naver_profile_dicts(self):
        return dict(self._read()["naver_profiles"])

    def save_naver_profile(self, profile):
        if not isinstance(profile, NaverProfile):
            raise AppError("CONTENT_INVALID", {"항목": "블로그 프로필"})
        data = self._read()
        data["naver_profiles"][profile.key] = profile.to_dict()
        write_json(self.path, data)


@dataclass
class Context:
    """서비스 함수들이 받는 부품 묶음. 경로·저장소·시계·git·배포 확인을 바꿔 끼울 수 있어 시험에 네트워크가 필요 없다."""
    workspace: Workspace
    settings: Settings
    backend: object
    git: object = gitrepo.run_git
    expected_origin: object = gitrepo.EXPECTED_ORIGIN
    clock: object = utc_now
    repo_override: str = ""
    env: object = None
    lock_wait: float = 120.0       # 다른 글이 같은 저장소에 올라가는 중이면 이 만큼(초) 기다리고 그래도 안 끝나면 PUBLISH_REPO_BUSY 로 물러난다(0 이면 기다리지 않고 바로)
    read_only_store: bool = False  # 참이면 `store()` 가 읽기 전용으로 연다(파일을 만들지도 구조를 올리지도 않는다) — `reading_only()` 로 만든다
    keystore: object = None        # 비밀 보관소(`security.keystore.KeyStore`) — 시험은 가짜를 넣고, 비워 두면 처음 쓸 때 `default_keystore` 로 연다(Windows 자격 증명 관리자)

    def now(self):
        """지금(시간대가 있는 UTC 시각). 시계가 시간대 없는 시각을 내면 멈춘다 — 파일 이름의 한국 시각이 어긋나지 않게."""
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise AppError("CONTENT_INVALID", {"항목": "시각"}, detail="시계가 시간대 없는 시각을 냈다")
        return value.astimezone(timezone.utc)

    def stamp(self):
        return self.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    def store(self):
        """글 저장소를 연다(`with ctx.store() as store:`). 데이터 폴더가 없으면 만들고, 옛 구조의 파일은 사본(`.v<판>.bak`)을 남기고 올린다.
        `reading_only()` 로 만든 사본은 **읽기 전용**으로 연다(`Store.open(migrate=False)`) — 폴더·파일을 만들지 않고 옛 구조도 올리지 않으며, 파일이 없으면 CONTENT_NOT_FOUND."""
        if self.read_only_store:
            return Store.open(self.workspace.store_path, migrate=False)
        self.workspace.ensure()
        return Store.open(self.workspace.store_path)

    def get_keystore(self):
        """비밀 보관소. 주입한 것이 없으면 프로그램의 보관소(`default_keystore` — 환경 변수가 없으면 언제나 Windows 자격 증명 관리자)를 연다. 못 열면 KEY_STORE_UNAVAILABLE."""
        if self.keystore is not None:
            return self.keystore
        from ..security.keystore import default_keystore       # 늦게 가져온다 — 키를 안 쓰는 명령이 ctypes 를 불러오지 않게
        return default_keystore(os.environ if self.env is None else self.env)

    def reading_only(self):
        """같은 부품에 '글 저장소는 읽기만' 표시를 한 사본 — 점검(doctor)처럼 읽기만 하는 일이 쓴다. 이 사본의 `store()` 는 파일을 만들지도, 옛 구조를 올리지도, 사본을 남기지도 않는다."""
        return replace(self, read_only_store=True)

    def repo_path(self):
        """연결한 chanceblog 폴더: `--repo` > 저장해 둔 설정 > 환경 변수 CHANCEBLOG_LOCAL_REPO. 아무것도 없으면 PAGES_LOCAL_REPO_INVALID."""
        env = os.environ if self.env is None else self.env
        chosen = self.repo_override or self.settings.repo_path() or env.get(ENV_REPO) or ""
        if not chosen.strip():
            raise AppError("PAGES_LOCAL_REPO_INVALID", detail="연결한 chanceblog 폴더가 없다(connect 로 연결한다)")
        return Path(os.path.expanduser(chosen))

    def repo_path_or_none(self):
        """연결한 폴더, 아직 연결하지 않았으면 None. 설정 파일이 깨진 것까지 '연결 안 함' 으로 숨기지 않는다(SETTINGS_INVALID 는 그대로 낸다)."""
        try:
            return self.repo_path()
        except AppError as error:
            if error.code != "PAGES_LOCAL_REPO_INVALID":
                raise
            return None

    def local_paths(self):
        """글에 들어가면 안 되는 이 PC 의 폴더 경로들(데이터 폴더·연결한 저장소) — 글 검사가 찾는다."""
        found = [str(self.workspace.root)]
        repo = self.repo_path_or_none()
        if repo is not None:
            found.append(str(repo))
        return tuple(found)


def make_context(*, data_dir=None, repo=None, env=None, git=None, expected_origin=None, clock=None, fetcher=None, sleep=None, monotonic=None, backend=None):
    """실제 실행용 Context 를 만든다. 시험은 git·시계·요청기·backend 를 바꿔 넣는다."""
    from .backend import GitPagesBackend
    workspace = Workspace.resolve(data_dir, env=env)
    git = git or gitrepo.run_git
    expected = expected_origin or gitrepo.EXPECTED_ORIGIN
    backend = backend or GitPagesBackend(git=git, expected_origin=expected, fetcher=fetcher, sleep=sleep, monotonic=monotonic)
    return Context(workspace, Settings(workspace.settings_path), backend, git, expected, clock or utc_now, repo or "", env)
