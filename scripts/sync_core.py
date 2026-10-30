"""chanceblog 의 핵심 코드(pipeline/ 의 일부)를 vendor/pipeline/ 에 '원본 그대로' 가져온다.

    python scripts/sync_core.py --source <chanceblog 를 받아 둔 폴더> --ref <커밋·태그·브랜치>   # 가져와서 vendor/ 와 VENDOR.json 을 다시 쓴다
    python scripts/sync_core.py --check                                                      # vendor/ 가 VENDOR.json 과 같은지만 본다(시험도 같은 검사)

규칙(docs/ARCHITECTURE.md §4): vendor/ 안은 이 저장소에서 고치지 않는다. 고칠 일이 생기면 chanceblog 에서 고쳐 병합한 뒤 다시 가져온다.
가져오는 파일은 아래 FILES 뿐이고(앱이 쓰는 것만), 목록을 바꾸는 것도 이 저장소의 PR 이다. 서브모듈·pip 설치는 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_REPO = "https://github.com/shine88pc/chanceblog"
MANIFEST = "VENDOR.json"
# 가져오는 파일(chanceblog 저장소 기준 경로). 의존: gates → console, 나머지는 표준 라이브러리만 쓴다.
FILES = (
    "pipeline/__init__.py",
    "pipeline/console.py",
    "pipeline/gates.py",
    "pipeline/secret_patterns.py",
)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _managed_files(vendor):
    """vendor/pipeline 안의 실제 파일(캐시 폴더 제외), vendor 기준 상대 경로(/ 구분)."""
    base = vendor / "pipeline"
    if not base.is_dir():
        return []
    return sorted(
        path.relative_to(vendor).as_posix()
        for path in base.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def check(root=ROOT):
    """vendor/ 가 VENDOR.json 과 같은지. 어긋난 곳의 설명 목록(비어 있으면 정상)."""
    vendor = Path(root) / "vendor"
    manifest_path = vendor / MANIFEST
    if not manifest_path.is_file():
        return [f"vendor/{MANIFEST} 이 없다"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as error:
        return [f"vendor/{MANIFEST} 을 읽을 수 없다: {error}"]
    problems = []
    if manifest.get("source") != SOURCE_REPO:
        problems.append(f"source 가 {SOURCE_REPO} 이어야 한다")
    if not FULL_SHA.match(str(manifest.get("ref", ""))):
        problems.append("ref 는 40자리 커밋 SHA 여야 한다")
    files = manifest.get("files")
    if not isinstance(files, dict):
        return problems + ["files 목록이 없다"]
    if sorted(files) != sorted(FILES):
        problems.append("VENDOR.json 의 파일 목록이 scripts/sync_core.py 의 FILES 와 다르다")
    for rel, digest in sorted(files.items()):
        path = vendor / rel
        if not path.is_file():
            problems.append(f"{rel}: 파일이 없다")
        elif sha256(path.read_bytes()) != digest:
            problems.append(f"{rel}: 내용이 VENDOR.json 의 해시와 다르다(이 저장소에서 고치지 않는다)")
    for rel in _managed_files(vendor):
        if rel not in files:
            problems.append(f"{rel}: VENDOR.json 에 없는 파일이 vendor/ 에 있다")
    return problems


def _git(source, *args):
    done = subprocess.run(["git", "-C", str(source), *args], capture_output=True)
    if done.returncode != 0:
        message = done.stderr.decode("utf-8", "replace").strip() or "git 실행 실패"
        raise RuntimeError(f"git {' '.join(args)}: {message}")
    return done.stdout


def sync(source, ref, root=ROOT):
    """source(chanceblog 를 받아 둔 폴더)의 ref 커밋에서 FILES 를 가져와 vendor/ 를 다시 쓴다. 모두 읽은 뒤에만 쓴다."""
    commit = _git(source, "rev-parse", "--verify", f"{ref}^{{commit}}").decode("ascii").strip()
    contents = {rel: _git(source, "show", f"{commit}:{rel}") for rel in FILES}
    vendor = Path(root) / "vendor"
    for rel in _managed_files(vendor):
        if rel not in contents:
            (vendor / rel).unlink()
    for rel, data in contents.items():
        path = vendor / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {"source": SOURCE_REPO, "ref": commit, "files": {rel: sha256(data) for rel, data in contents.items()}}
    (vendor / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
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
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"vendor/ 를 {SOURCE_REPO} 의 {commit[:12]} 로 다시 썼다({len(FILES)}개 파일). 이어서 시험을 돌리고 변경을 PR 로 올린다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
