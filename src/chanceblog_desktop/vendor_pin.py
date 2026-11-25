"""vendor/ 의 '총 요약값'을 소스에 고정해 두고 앱을 열 때 확인한다 — AS-S2 권고-6(결정 D-692).

왜: `vendor/VENDOR.json` 의 파일 해시는 같은 폴더의 `vendor/` 파일과만 견주는 '자기 일관성'이라, 변조한 쪽이 파일과 목록(`VENDOR.json`)을 **같이** 고치면 CI 의 확인(`scripts/sync_core.py --check`)도 시험도 통과한다.
설치본은 시작할 때 vendor/ 를 아예 확인하지 않아서(자가 점검 `--selftest` 만 해시를 봤다) 압축을 푼 폴더에 쓸 수 있는 프로그램이 비밀 패턴 목록을 비우거나 `json.py` 같은 파일로 표준 모듈을 가려도 앱은 말없이 썼다.

이 모듈은 자기참조의 높이를 한 단 올린다: `PINNED_DIGEST`(파일 이름·해시·원본 커밋을 한 줄로 요약한 값) 한 개를 **소스 코드 안에** 고정한다. 이 값을 바꾸는 것은 `scripts/sync_core.py` 가 `vendor/` 를 가져올 때뿐이다 —
그래서 vendor/ 와 VENDOR.json 만 같이 고치고 이 값을 안 고친 변경은 CI(`sync_core.py --check`)·시험·자가 점검·앱 시작에서 빨개진다. 이 값까지 같이 고친 변경은 '코드 한 줄이 바뀐 변경' 으로 눈에 띄므로 사람이 검토한다.
완전한 해결은 VENDOR.json 의 원본 커밋에서 같은 파일을 받아 대조하는 CI 인데 그것은 새 외부 접속이라 운영자 승인(T3)이 필요하다 — 여기서는 제안만 한다(`docs/SECURITY.md`·`docs/DECISIONS.md` D-692).

확인하는 것(`problems`): ① VENDOR.json 이 읽히고(같은 이름의 칸이 두 번 나오면 거절 — `json.loads` 는 마지막 값만 써서 눈으로 보는 비교와 달라진다) 이름·해시가 모양대로이며
② 목록의 파일이 보통 파일이고(링크·하드 링크 아님 — OneDrive 같은 클라우드 자리표시 파일은 괜찮다) 실제 내용의 해시가 목록과 같고 ③ 이름·해시·원본 커밋을 요약한 값이 `PINNED_DIGEST` 와 같고
④ (`strict`) 목록에 없는 파일이 vendor/ 에 하나도 없다(vendor/ 는 import 경로 맨 앞이라 `json.py` 같은 파일이 표준 모듈을 가린다 — 운영체제가 폴더에 스스로 만드는 `desktop.ini` 같은 것만 뺀다).
`start_problem()` 은 앱을 열 때 한 번 부른다: 설치본(`sys.frozen`)은 ①–④, 소스 실행은 ①–③(개발 PC 의 vendor/ 에 남은 캐시 같은 것으로 화면이 안 열리지 않게). 어긋나면 화면을 열지 않고 경로·값 없는 쉬운 한 문장으로 알린다.
수 KB 의 파일 여섯 개를 읽는 일이라 시작 시간에 영향이 없다. 표준 라이브러리만 쓰고 읽기만 한다. **패키지 밖에서 파일 경로로도 불러올 수 있게**(`sync_core.py` 가 이 값을 읽고 다시 쓴다) 맨 위에서는 표준 라이브러리만 가져오고,
앱 안의 다른 모듈(`fslink`·`core`)은 필요한 함수 안에서 가져온다.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath

PINNED_DIGEST = "6647c57f67481171cf8fee2f78e22bc9337aa0461459780463716f62b62e656e"     # sync_core.py 가 vendor/ 를 가져올 때만 이 줄을 다시 쓴다 — 손으로 고치지 않는다
MANIFEST = "VENDOR.json"
IGNORED_NAMES = frozenset({"desktop.ini", "Thumbs.db", ".DS_Store"})                    # 운영체제가 폴더에 스스로 만드는 파일 — 불러와지지 않는 이름이라 낯선 파일로 세지 않는다
START_MESSAGE = ("프로그램에 들어 있는 검사 규칙 파일(vendor 폴더)이 원래와 달라서 열지 않았어요. 압축을 다시 풀어 새로 설치해 주세요. "
                 "(다른 곳에서 받은 파일을 섞었거나 보안 프로그램·다른 프로그램이 파일을 바꿨을 수 있어요.)")
HEX_DIGITS = frozenset("0123456789abcdef")


def total_digest(ref, digests):
    """원본 커밋(`ref`)과 {상대 경로: 파일 내용의 sha256 16진} 을 한 값으로 — 첫 줄 `ref 커밋`, 이어서 이름 순으로 `이름 해시` 줄을 잇고 sha256. 이름·해시·커밋 중 하나라도 바뀌면 값이 달라진다."""
    lines = [f"ref {ref}"] + [f"{rel} {digests[rel]}" for rel in sorted(digests)]
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _no_duplicates(pairs):
    keys = [key for key, _value in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("같은 이름의 칸이 두 번 나온다")
    return dict(pairs)


def read_manifest(vendor):
    """VENDOR.json → (원본 커밋, {상대 경로: 해시}). 읽을 수 없거나 모양이 틀리면 ValueError — 같은 이름의 칸이 두 번 나와도, 파일 이름이 vendor/ 밖을 가리켜도(절대 경로·`..`·역슬래시·콜론)·해시가 64자리 16진수가 아니어도."""
    try:
        manifest = json.loads((Path(vendor) / MANIFEST).read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    except (OSError, ValueError, RecursionError) as error:
        raise ValueError(f"{MANIFEST} 을 읽을 수 없다") from error
    ref = manifest.get("ref") if isinstance(manifest, dict) else None
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not (isinstance(ref, str) and isinstance(files, dict) and files):
        raise ValueError(f"{MANIFEST} 의 모양이 맞지 않다")
    for rel, digest in files.items():
        pure = PurePosixPath(rel) if isinstance(rel, str) and rel else None
        if (pure is None or pure.as_posix() != rel or pure.is_absolute() or ".." in pure.parts or "\\" in rel or ":" in rel
                or not (isinstance(digest, str) and len(digest) == 64 and set(digest) <= HEX_DIGITS)):
            raise ValueError(f"{MANIFEST} 의 파일 이름이나 해시가 모양이 아니다")
    return ref, dict(files)


def _plain_file_problem(path):
    """보통 파일이 아니거나(링크) 다른 이름과 같은 파일(하드 링크)이면 이유 글, 아니면 None."""
    from . import fslink
    try:
        info = os.lstat(path)
    except OSError:
        return "파일이 없거나 읽을 수 없다"
    if fslink.is_link(path):
        return "링크다"
    if not stat.S_ISREG(info.st_mode):
        return "보통 파일이 아니다"
    if info.st_nlink > 1:
        return "하드 링크(다른 이름과 같은 파일)다"
    return None


def _extras(vendor, listed):
    """vendor/ 안의 목록 밖 항목(상대 경로 글) — 링크 안으로는 들어가지 않는다. 읽을 수 없는 폴더가 있으면 그것도 알린다(숨은 것이 없다는 보장이 없다)."""
    from . import fslink
    allowed = set(listed) | {MANIFEST}
    found, unreadable = [], []
    for folder, names, files in os.walk(vendor, followlinks=False, onerror=unreadable.append):
        base = Path(folder)
        relative = base.relative_to(vendor).as_posix()
        prefix = "" if relative == "." else relative + "/"
        for name in list(names):
            if fslink.is_link(base / name):
                found.append(f"{prefix}{name}: 링크다")
                names.remove(name)
        for name in files:
            rel = prefix + name
            if rel in allowed or name in IGNORED_NAMES:
                continue
            found.append(f"{rel}: 목록에 없는 " + ("링크다" if fslink.is_link(base / name) else "파일이다"))
    if unreadable:
        found.append("읽을 수 없는 폴더가 있다")
    return sorted(found)


def problems(vendor, *, strict=True, pinned=None):
    """`vendor` 폴더의 문제 글 목록(비어 있으면 정상) — 위 머리말의 ①–④. 읽기만 한다. `pinned` 는 시험이 다른 값을 줄 때만 쓴다."""
    from . import fslink
    vendor = Path(vendor)
    pinned = PINNED_DIGEST if pinned is None else pinned
    if fslink.is_link(vendor):
        return ["vendor 폴더 자신이 링크다"]
    try:
        ref, files = read_manifest(vendor)
    except ValueError as error:
        return [str(error)]
    found, actual = [], {}
    for rel in sorted(files):
        path = vendor.joinpath(*PurePosixPath(rel).parts)
        why = _plain_file_problem(path)
        if why:
            found.append(f"{rel}: {why}")
            continue
        try:
            actual[rel] = sha256_file(path)
        except OSError:
            found.append(f"{rel}: 읽을 수 없다")
            continue
        if actual[rel] != files[rel]:
            found.append(f"{rel}: 내용이 {MANIFEST} 의 해시와 다르다")
    if len(actual) == len(files) and total_digest(ref, actual) != pinned:
        found.append("vendor 의 이름·해시·원본 커밋이 소스에 고정된 총 요약값과 다르다(vendor/ 와 VENDOR.json 만 같이 고쳤다면 고정값이 그대로라 이렇게 걸린다)")
    if strict:
        found += _extras(vendor, files)
    return found


def start_problem(*, vendor=None, frozen=None, pinned=None):
    """앱을 열 때 한 번 — 문제가 있으면 쉬운 한 문장(`START_MESSAGE` — 경로·값 없음), 없으면 None. 확인 자체가 어떤 이유로든 실패하면 문제로 본다(의심스러우면 열지 않는다).
    설치본(`sys.frozen`)은 낯선 파일까지 보고(strict), 소스 실행은 해시·고정값만 본다."""
    try:
        if vendor is None:
            from . import core
            vendor = core.vendor_dir()
        strict = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        return START_MESSAGE if problems(vendor, strict=strict, pinned=pinned) else None
    except Exception:       # noqa: BLE001 - 어떤 실패든 '확인하지 못함' 은 열지 않는 쪽이다
        return START_MESSAGE


__all__ = ["PINNED_DIGEST", "START_MESSAGE", "problems", "read_manifest", "start_problem", "total_digest"]
