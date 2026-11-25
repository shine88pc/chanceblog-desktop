"""chanceblog 의 핵심 코드(pipeline/ 의 일부)를 vendor/pipeline/ 에 '원본 그대로' 가져온다.

    python scripts/sync_core.py --source <chanceblog 를 받아 둔 폴더> --ref <커밋·태그·브랜치>   # 가져와서 vendor/ 와 VENDOR.json 을 다시 쓴다
    python scripts/sync_core.py --check                                                      # vendor/ 가 VENDOR.json 과 같은지만 본다(시험도 같은 검사)

규칙(docs/ARCHITECTURE.md §4): vendor/ 안은 이 저장소에서 고치지 않는다. 고칠 일이 생기면 chanceblog 에서 고쳐 병합한 뒤 다시 가져온다.
가져오는 파일은 아래 FILES 뿐이고(앱이 쓰는 것만), 목록을 바꾸는 것도 이 저장소의 PR 이다. 서브모듈·pip 설치는 쓰지 않는다.
총 요약값(AS-S2 권고-6, D-692): 가져올 때 vendor/ 와 VENDOR.json 에 더해 `src/chanceblog_desktop/vendor_pin.py` 의 `PINNED_DIGEST`(파일 이름·해시·원본 커밋을 한 줄로 요약한 값)도 함께 다시 쓴다.
`--check` 는 vendor/ 와 VENDOR.json 이 서로 맞는 것에 더해 그 요약값이 소스에 고정된 값과 같은지도 본다 — 파일과 목록만 같이 고친 변경은 이 값이 그대로라 걸린다. 소스 나무(`src/chanceblog_desktop`)가 없는 사본(시험용 임시 폴더)은 이 비교를 건너뛴다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_REPO = "https://github.com/shine88pc/chanceblog"
MANIFEST = "VENDOR.json"
# 가져오는 파일(chanceblog 저장소 기준 경로). 의존: gates·verify_pages_deploy → console, 나머지는 표준 라이브러리만 쓴다.
# scripts/verify_pages_deploy.py: 배포 뒤 글이 공개 주소에서 열리는지 확인하는 코드(공개 CDN 이 404 도 보관하는 사정까지 반영된, 클라우드 배포가 쓰는 그대로)
FILES = (
    "pipeline/__init__.py",
    "pipeline/console.py",
    "pipeline/gates.py",
    "pipeline/secret_patterns.py",
    "scripts/verify_pages_deploy.py",
)
FULL_SHA = re.compile(r"[0-9a-f]{40}")          # fullmatch 로 쓴다(`$` 는 끝의 줄바꿈 하나를 봐준다)
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
# --source 폴더의 origin 으로 인정하는 주소(chanceblog 의 https·ssh 주소). 아무 로컬 저장소나 chanceblog 로 기록되지 않게 한다.
SOURCE_ORIGIN = re.compile(r"(?:https://(?:[^/\s]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)shine88pc/chanceblog(?:\.git)?/?", re.IGNORECASE | re.ASCII)
PLAIN_FILE_MODES = ("100644", "100755")        # 링크(120000)·하위 모듈(160000)·폴더는 가져오지 않는다
PIN_RELATIVE = "src/chanceblog_desktop/vendor_pin.py"      # vendor/ 의 총 요약값을 소스에 고정해 둔 파일(앱이 시작할 때 같은 값을 확인한다)
PIN_LINE = re.compile(rb'^PINNED_DIGEST = "([0-9a-f]{64})"', re.MULTILINE)       # 그 파일에서 이 값을 담은 한 줄(꼭 한 줄이어야 한다) — 바이트로 바꿔 줄 끝(CRLF·LF)을 그대로 둔다
_GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


_REPARSE_TAGS = (0xA0000003, 0xA000000C)       # Windows 의 정션(마운트 지점)·심볼릭 링크 재해석 지점. 클라우드 동기화 자리표시 파일 등은 링크가 아니다


def _is_link(path):
    """심볼릭 링크 또는 Windows 정션인가(링크 자체를 보며, 가리키는 곳으로 따라가지 않는다)."""
    try:
        if os.path.islink(path):
            return True
        return getattr(os.lstat(path), "st_reparse_tag", 0) in _REPARSE_TAGS
    except OSError:
        return False


def _no_duplicates(pairs):
    """같은 이름의 칸이 두 번 나오는 JSON 은 거절한다 — `json.loads` 는 마지막 값만 써서, 눈으로 보는 비교(앞 값)와 실제 값이 달라진다(AS-S2 참고, SC-13)."""
    keys = [key for key, _value in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("같은 이름의 칸이 두 번 나온다")
    return dict(pairs)


def _walk(vendor):
    """vendor/ 아래의 모든 항목을 정렬된 (상대 경로, 종류)로. 종류는 'file' 또는 'link'. 링크(심볼릭 링크·정션) 안으로는 들어가지 않는다 —
    링크를 따라가면 vendor/ 밖의 파일을 '관리 대상'으로 세어 지우거나 덮어쓰게 된다."""
    found, stack = [], [Path(vendor)]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            rel = Path(entry.path).relative_to(vendor).as_posix()
            if _is_link(entry.path):
                found.append((rel, "link"))
            elif entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
            else:
                found.append((rel, "file"))
    return sorted(found)


def _is_shared(path):
    """하드 링크(같은 내용을 다른 이름으로도 가리키는 파일)인가 — 그 파일에 쓰면 다른 이름의 파일도 바뀐다."""
    try:
        return os.lstat(path).st_nlink > 1
    except OSError:
        return False


def _managed_files(vendor):
    """vendor/ 안의 모든 파일·링크(컴파일 캐시 `.pyc` 도 포함) — VENDOR.json 만 뺀다. vendor 기준 상대 경로(/ 구분).

    vendor/ 는 import 경로 맨 앞이라 어느 자리의 파일이든(`vendor/json.py`·`sitecustomize.py`·소스 없는 `.pyc`·소스와 수정 시각·크기만 맞춰 만든 `.pyc`)
    앱이 불러올 수 있다. 앱은 컴파일 캐시를 vendor/ 밖에 두므로(core.use_vendored_core) vendor/ 안에는 `.pyc` 가 없어야 한다.
    """
    vendor = Path(vendor)
    if not vendor.is_dir():
        return []
    return [rel for rel, _kind in _walk(vendor) if rel != MANIFEST]


def check(root=ROOT):
    """vendor/ 가 VENDOR.json 과 같은지. 어긋난 곳의 설명 목록(비어 있으면 정상)."""
    vendor = Path(root) / "vendor"
    if vendor.exists() and _is_link(vendor):
        return ["vendor/ 자체가 링크(심볼릭 링크·정션)다"]
    manifest_path = vendor / MANIFEST
    if not manifest_path.is_file():
        return [f"vendor/{MANIFEST} 이 없다"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    except ValueError as error:
        return [f"vendor/{MANIFEST} 을 읽을 수 없다: {error}"]
    if not isinstance(manifest, dict):
        return [f"vendor/{MANIFEST} 의 맨 위가 {{ }} 모양이 아니다"]
    problems = []
    if manifest.get("source") != SOURCE_REPO:
        problems.append(f"source 가 {SOURCE_REPO} 이어야 한다")
    ref = manifest.get("ref")
    if not (isinstance(ref, str) and FULL_SHA.fullmatch(ref)):
        problems.append("ref 는 40자리 커밋 SHA 여야 한다")
    files = manifest.get("files")
    if not isinstance(files, dict):
        return problems + ["files 목록이 없다"]
    if sorted(files) != sorted(FILES):
        problems.append("VENDOR.json 의 파일 목록이 scripts/sync_core.py 의 FILES 와 다르다")
    for rel, digest in sorted(files.items()):
        path = vendor / rel
        if not (isinstance(digest, str) and SHA256_HEX.fullmatch(digest)):
            problems.append(f"{rel}: VENDOR.json 의 해시가 64자리 16진수가 아니다")
        elif _is_link(path):
            problems.append(f"{rel}: 링크(심볼릭 링크·정션)다 — 링크 너머의 파일은 가져온 코드가 아니다")
        elif _is_shared(path):
            problems.append(f"{rel}: 하드 링크(다른 이름과 같은 파일)다 — 가져온 파일이 아닌 곳과 이어져 있을 수 있다")
        elif not path.is_file():
            problems.append(f"{rel}: 파일이 없다")
        elif sha256(path.read_bytes()) != digest:
            problems.append(f"{rel}: 내용이 VENDOR.json 의 해시와 다르다(이 저장소에서 고치지 않는다)")
    for rel in _managed_files(vendor):
        if rel not in files:
            if _is_link(vendor / rel):
                kind = "링크(심볼릭 링크·정션)"
            elif rel.endswith(".pyc") and "__pycache__" in rel.split("/")[:-1]:
                kind = "컴파일 캐시(.pyc — 소스와 수정 시각·크기만 맞으면 파이썬이 소스 대신 실행한다. 앱은 캐시를 vendor/ 밖에 두므로 `__pycache__` 폴더를 지운다)"
            else:
                kind = "파일"
            problems.append(f"{rel}: VENDOR.json 에 없는 {kind}이 vendor/ 에 있다")
    return problems + _pin_problems(root, vendor, manifest, files)


def _load_pin(root):
    """`root` 의 소스에 있는 `vendor_pin.py` 를 **파일 경로로** 불러온다(패키지 `chanceblog_desktop` 은 불러오지 않는다 — 그 안의 다른 모듈과 부수 효과가 없다) → 모듈. 소스 나무(`src/chanceblog_desktop`)가 없는 사본이면 None.
    소스 나무가 있는데 이 파일이 없거나 링크이거나 읽을 수 없으면 RuntimeError."""
    folder = Path(root) / "src" / "chanceblog_desktop"
    if not folder.is_dir():
        return None
    path = folder / "vendor_pin.py"
    if not path.is_file() or _is_link(path) or _is_shared(path):
        raise RuntimeError(f"{PIN_RELATIVE} 가 없거나 링크다 — vendor/ 의 총 요약값을 소스에 고정해 둔 파일이라 이것 없이는 확인하거나 가져오지 않는다")
    module = types.ModuleType("vendor_pin_under_sync")
    module.__file__ = str(path)
    try:
        # 소스 바이트를 읽어 직접 실행한다 — `importlib` 의 파일 경로 불러오기는 바이트 코드 캐시(__pycache__)를 쓰는데, 같은 크기의 고정값 줄을 같은 초 안에 고쳐 쓰면(빠른 파일 시스템)
        # 옛 `.pyc` 가 유효해 보여 옛 PINNED_DIGEST 가 읽힌다(11-25 우분투 검사 빨강의 원인). 이 길은 캐시를 읽지도 쓰지도 않는다.
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    except Exception as error:      # noqa: BLE001 - 어떤 오류든 이 파일을 믿을 수 없다는 뜻이다
        raise RuntimeError(f"{PIN_RELATIVE} 를 불러올 수 없다({type(error).__name__})") from None
    return module


def _pin_problems(root, vendor, manifest, files):
    """vendor/ 의 실제 파일·원본 커밋의 총 요약값이 소스에 고정된 값(`PINNED_DIGEST`)과 같은가 → 문제 글 목록. 다른 문제(파일 없음·링크 …)는 위에서 이미 알렸으므로 읽을 수 없으면 조용히 넘어간다."""
    try:
        pin = _load_pin(root)
    except RuntimeError as error:
        return [str(error)]
    if pin is None:
        return []
    ref = manifest.get("ref")
    actual = {}
    for rel in files:
        path = Path(vendor) / rel
        if not isinstance(rel, str) or _is_link(path) or not path.is_file():
            return []
        actual[rel] = sha256(path.read_bytes())
    if not (isinstance(ref, str) and FULL_SHA.fullmatch(ref)):
        return []
    pinned = PIN_LINE.findall((Path(root) / PIN_RELATIVE).read_bytes())
    if len(pinned) != 1:
        return [f"{PIN_RELATIVE} 에 PINNED_DIGEST 줄이 하나가 아니다({len(pinned)}개)"]
    if pin.total_digest(ref, actual) != pinned[0].decode("ascii"):
        return [f"vendor/ 의 파일 이름·해시·원본 커밋이 {PIN_RELATIVE} 에 고정된 총 요약값과 다르다 — vendor/ 와 {MANIFEST} 를 손으로 같이 고친 것이다(고정값이 그대로라 걸린다). "
                "vendor/ 는 chanceblog 에서 고쳐 병합한 뒤 scripts/sync_core.py 로 다시 가져온다(그러면 이 고정값도 함께 바뀐다)"]
    return []


def _run_git(source, *args):
    env = {key: value for key, value in os.environ.items() if key not in _GIT_ENV_DROP}      # 다른 저장소를 가리키는 환경 변수에 휘둘리지 않게
    return subprocess.run(["git", "-C", str(source), *args], capture_output=True, env=env)


def _git(source, *args):
    done = _run_git(source, *args)
    if done.returncode != 0:
        message = done.stderr.decode("utf-8", "replace").strip() or "git 실행 실패"
        raise RuntimeError(f"git {' '.join(args)}: {message}")
    return done.stdout


def _verify_source(source, commit):
    """원본 폴더가 정말 chanceblog 이고, 가져올 커밋이 거기서 병합된(origin/main 에 들어간) 것인지 본다."""
    urls = [line.strip() for line in _git(source, "remote", "get-url", "--all", "origin").decode("utf-8", "replace").splitlines() if line.strip()]
    if not urls or not all(SOURCE_ORIGIN.fullmatch(url) for url in urls):
        shown = re.sub(r"//[^/\s]*@", "//***@", urls[0]) if urls else "(없음)"
        raise RuntimeError(f"--source 폴더의 origin 이 {SOURCE_REPO} 가 아니다: {shown}")
    done = _run_git(source, "merge-base", "--is-ancestor", commit, "refs/remotes/origin/main")
    if done.returncode == 1:
        raise RuntimeError(f"{commit[:12]} 는 origin/main 에 병합된 커밋이 아니다 — chanceblog 에서 병합한 뒤(필요하면 `git fetch` 로 최신을 받고) 다시 가져온다")
    if done.returncode != 0:
        raise RuntimeError("origin/main 과 비교하지 못했다: " + (done.stderr.decode("utf-8", "replace").strip() or "git 실행 실패"))


def _read_file(source, commit, rel):
    """커밋 안의 일반 파일 하나의 바이트(변환 없음). 없거나 링크·하위 모듈·폴더면 RuntimeError."""
    listing = _git(source, "ls-tree", commit, "--", rel).decode("utf-8", "replace").strip()
    if not listing:
        raise RuntimeError(f"{rel}: 원본 커밋에 없다")
    fields = listing.split(None, 2)
    if len(fields) < 3 or fields[0] not in PLAIN_FILE_MODES or fields[1] != "blob":
        raise RuntimeError(f"{rel}: 일반 파일이 아니다(모드 {fields[0]}, 종류 {fields[1] if len(fields) > 1 else '?'} — 링크·하위 모듈·폴더는 가져오지 않는다)")
    return _git(source, "cat-file", "blob", f"{commit}:{rel}")


def sync(source, ref, root=ROOT):
    """source(chanceblog 를 받아 둔 폴더)의 ref 커밋에서 FILES 를 가져와 vendor/ 를 다시 쓴다. 모두 읽은 뒤에만 쓴다."""
    commit = _git(source, "rev-parse", "--verify", f"{ref}^{{commit}}").decode("ascii").strip()
    _verify_source(source, commit)
    contents = {rel: _read_file(source, commit, rel) for rel in FILES}
    pin = _load_pin(root)                        # 소스 나무가 있는데 총 요약값 파일이 없거나 링크이면 아무것도 쓰기 전에 멈춘다(None 은 소스 나무가 없는 사본)
    vendor = Path(root) / "vendor"
    if vendor.exists() and _is_link(vendor):
        raise RuntimeError("vendor/ 자체가 링크(심볼릭 링크·정션)라 가져오지 않는다")
    strays = [rel for rel in _managed_files(vendor) if rel not in contents]
    links = [rel for rel in strays if _is_link(vendor / rel)]
    if links:                                    # 링크 너머를 지우거나 덮어쓰지 않게, 아무것도 쓰기 전에 멈춘다
        raise RuntimeError("vendor/ 안에 링크(심볼릭 링크·정션)가 있어 가져오지 않는다: " + ", ".join(links[:5]))
    shared = [rel for rel in (*contents, MANIFEST) if os.path.lexists(vendor / rel) and (_is_link(vendor / rel) or _is_shared(vendor / rel))]
    if shared:                                   # 가져올 파일 자리에 링크·하드 링크가 있으면 쓰는 순간 링크 너머(vendor/ 밖)의 파일이 바뀐다 — 아무것도 쓰기 전에 멈춘다
        raise RuntimeError("vendor/ 의 파일이 링크(심볼릭 링크·정션) 또는 하드 링크라 가져오지 않는다: " + ", ".join(shared[:5]))
    real_vendor = os.path.realpath(vendor)
    for rel in strays:
        if not os.path.realpath(vendor / rel).startswith(real_vendor + os.sep):
            raise RuntimeError(f"{rel}: vendor/ 밖을 가리키는 경로라 지우지 않는다")
    manifest = {"source": SOURCE_REPO, "ref": commit, "files": {rel: sha256(data) for rel, data in contents.items()}}
    planned = [(rel, vendor / rel, data) for rel, data in contents.items()]                   # (보일 이름, 쓸 자리, 내용)
    planned.append((MANIFEST, vendor / MANIFEST, (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")))
    if pin is not None:                          # vendor/ 를 바꿀 때 소스에 고정한 총 요약값도 함께 바꾼다 — 같은 임시 파일 → 이름 바꾸기 길을 탄다
        pin_path = Path(root) / PIN_RELATIVE
        old_text = pin_path.read_bytes()
        if len(PIN_LINE.findall(old_text)) != 1:
            raise RuntimeError(f"{PIN_RELATIVE} 에 PINNED_DIGEST 줄이 하나가 아니라 값을 바꾸지 못한다")
        digest = pin.total_digest(commit, manifest["files"]).encode("ascii")
        planned.append((PIN_RELATIVE, pin_path, PIN_LINE.sub(lambda _match: b'PINNED_DIGEST = "' + digest + b'"', old_text, count=1)))
    locked = [shown for shown, path, _data in planned if os.path.lexists(path) and not os.access(path, os.W_OK)]
    if locked:                                   # 읽기 전용이거나 바꿀 수 없는 파일이 있으면 아무것도 바꾸기 전에 멈춘다(일부만 갱신된 vendor/ 를 남기지 않는다)
        raise RuntimeError("vendor/ 의 파일을 바꿀 수 없다(읽기 전용이거나 다른 프로그램이 쓰는 중인지 본다): " + ", ".join(locked[:5]))
    staged = []
    try:
        for _shown, path, data in planned:       # 먼저 전부 같은 폴더의 임시 파일에 쓴다 — 여기서 실패하면(디스크 가득 등) vendor/ 는 아직 그대로다
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + ".sync-tmp")
            staged.append((temp, path))
            temp.write_bytes(data)
        for temp, path in staged:                # 이름을 바꿔 넣는다 — 파일이 반쯤 써진 채 남지 않고, 링크가 있어도 그 너머가 아니라 링크 자리가 바뀐다
            os.replace(temp, path)
        for rel in strays:                       # 목록 밖 파일은 마지막에(옛 임시 파일이 같은 이름이면 위에서 이미 새 파일이 됐다)
            (vendor / rel).unlink(missing_ok=True)
    finally:
        for temp, _path in staged:
            if temp.exists():
                temp.unlink()
    return commit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", help="chanceblog 를 받아 둔 폴더(git 저장소)")
    parser.add_argument("--ref", help="가져올 커밋·태그·브랜치")
    parser.add_argument("--check", action="store_true", help="파일을 쓰지 않고 vendor/ 가 VENDOR.json 과 같은지만 본다")
    args = parser.parse_args(argv)
    if args.check:
        problems = check()
        for problem in problems:
            print(problem, file=sys.stderr)
        if not problems:
            print("vendor/ 가 VENDOR.json 과 같다.")
        return 1 if problems else 0
    if not args.source or not args.ref:
        parser.error("가져오려면 --source 와 --ref 가 모두 필요하다(확인만 하려면 --check)")
    try:
        commit = sync(args.source, args.ref)
    except (RuntimeError, OSError) as error:        # 쓰다 실패한 파일 시스템 오류도 추적 기록(traceback) 대신 한 줄로 알린다
        print(error, file=sys.stderr)
        return 1
    print(f"vendor/ 를 {SOURCE_REPO} 의 {commit[:12]} 로 다시 썼다({len(FILES)}개 파일). 소스에 고정한 총 요약값({PIN_RELATIVE})도 함께 바뀌었다 — 이 파일의 변경도 같은 PR 에 포함한다. 이어서 시험을 돌리고 변경을 PR 로 올린다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
