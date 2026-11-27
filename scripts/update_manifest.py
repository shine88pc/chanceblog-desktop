"""릴리스 매니페스트 도구 — 후보 폴더를 검증하고(`verify-candidate`) 서명할 매니페스트(`update-manifest.json`, schema 1)를 만든다(`build`) (RELEASE 설계서 3-3 서명 잡 단계 4·5, V1REL12·R-1).

쓰는 법(저장소 맨 위 폴더에서):
    python -X utf8 scripts/update_manifest.py verify-candidate --dir release [--version-file VERSION]
    python -X utf8 scripts/update_manifest.py build --dir release --min-version 0.0.0 [--key-id 16자리] [--issued-utc 2026-12-01T03:00:00Z] [--out 파일]
                                                     [--changelog CHANGELOG.md] [--version-file VERSION]

`verify-candidate`: `release_candidate.json` 을 읽고 폴더의 파일이 그 기록과 **정확히** 같은지 본다 — 자산 파일을 **다시 해시**해 이름·크기·SHA-256 을 대조하고, 이름 규칙·크기 상한을 보고, 알 수 없는 파일·빠진 파일·링크가 있으면 거절한다.
`build`: 먼저 사슬 전체(`packaging/release_chain.py` 의 `check_chain`: 후보 대조·묶음 정보·해시 목록·변경 이력 맨 위 절과 릴리스 노트 모양)를 확인하고, 그 값으로 매니페스트를 만든다.
  · 칸은 UPDATE 설계서 3-2 의 열네 개: `schema`(1)·`product`·`channel`(정식 `stable`·후보 `rc`)·`version`·`tag`(`v` + 버전)·`seq`(**발행 시각의 숫자 열네 자리 `YYYYMMDDhhmmss`**)·`issued_utc`·`expires_utc`(**발행 + 180일** — 앱은 200일까지 받아들인다)·
    `min_version`(꼭 주는 인자 — 이 판으로 바로 올릴 수 있는 가장 낮은 판, 버전 이하여야 한다)·`key_id`(서명 키의 지문 — 안 주면 앱에 내장된 **현재 키**의 이름표, 내장 목록이 비어 있으면 꼭 준다)·`commit`·`installer`(설치 도구 Inno Setup)·
    `notes.summary`(변경 이력의 `### 요약` 을 그대로)·`files`(설치 파일·휴대용 압축 파일의 이름·크기·SHA-256).
  · 시각은 `--issued-utc` 로 주입한다(시험의 결정성). 안 주면 러너의 시계(UTC, 초 단위)를 쓴다. 어느 쪽이든 발행 시각은 **허용 범위** 안이어야 한다(재작업 1·S-2): 2020년 1월 1일 이후·2100년 1월 1일 전이고
    지금(시계)보다 24시간 넘게 앞서지 않는다 — 앱은 적용한 `seq` 를 영구 기록하므로 미래 시각으로 서명하면 이후 정상 릴리스가 막힌다. 밖이면 고정 문장·종료 코드 2·파일 없음이고 시계가 쓸 수 없는 값이어도 같다. 주소는 매니페스트에 적지 않는다(앱이 상수로 만든다).
  · 만든 바이트는 앱과 **같은 코드**(`manifest.read_structure`·`validate_fields`)로 읽어 보고 받아들여질 때만 쓴다 — 앱이 거절할 매니페스트는 만들지 않는다. 파일은 UTF-8·BOM 없음·줄 끝 LF·끝의 줄바꿈 하나(바이트로 쓴다 — 윈도 글 모드의 CRLF 변환 없음).
이 도구는 서명 키를 모른다(키는 `scripts/update_sign.py` 만 환경 변수로 받는다). 종료 코드: 0 성공 · 1 후보·사슬 검사에서 문제가 있음 · 2 사용법·파일 오류 · 4 앱이 받아들이지 않을 매니페스트.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT / "src", ROOT / "packaging"):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import release_chain as rc  # noqa: E402
from chanceblog_desktop.update import keys as app_keys  # noqa: E402
from chanceblog_desktop.update import manifest as app_manifest  # noqa: E402
from chanceblog_desktop.update import versions as app_versions  # noqa: E402

VALID_DAYS = 180
SCHEMA = 1
# 발행 시각의 허용 범위(재작업 1·S-2): 앱은 적용에 성공하면 `seq`(= 발행 시각 숫자)를 `last_seq` 로 영구 기록하고 그보다 작은 `seq` 는 받지 않으므로, 미래 시각으로 서명하면 이후 정상 릴리스가 막힌다.
EARLIEST_ISSUED = datetime(2020, 1, 1, tzinfo=timezone.utc)
LATEST_ISSUED = datetime(2100, 1, 1, tzinfo=timezone.utc)         # 이 이후는 시계가 틀렸다고 본다(그리고 만료 계산이 넘치지 않게 한다)
FUTURE_SLACK = timedelta(hours=24)                                # 지금(주입한 시계)보다 이만큼보다 더 앞서면 거절
EXIT_OK, EXIT_PROBLEMS, EXIT_USAGE, EXIT_MANIFEST = 0, 1, 2, 4
_KEY_ID = re.compile(r"[0-9a-f]{16}", re.ASCII)

MSG_USAGE = ("사용법 오류: verify-candidate --dir 폴더 [--version-file 파일] · build --dir 폴더 --min-version 버전 [--key-id 지문] [--issued-utc 시각] [--out 파일] "
             "[--changelog 파일] [--version-file 파일] 중 하나를 쓴다.")
MSG_NO_VERSION = "읽지 못했다: VERSION 을 읽지 못했거나 버전 글이 정식(X.Y.Z)·후보(X.Y.Z-rc.N) 모양이 아니다."
MSG_NO_CHANGELOG = "읽지 못했다: 변경 이력 파일을 읽지 못했다."
MSG_BAD_TIME = "만들지 않았다: --issued-utc 는 YYYY-MM-DDThh:mm:ssZ 꼴의 실제 있는 시각이어야 한다."
MSG_ISSUED_RANGE = ("만들지 않았다: 발행 시각이 허용 범위를 벗어났다 — 2020년 1월 1일 이후 2100년 1월 1일 전이어야 하고 이 PC 시계보다 하루 넘게 앞서면 안 된다"
                    "(PC 시계나 --issued-utc 를 확인한다).")
MSG_BAD_KEY_ID = "만들지 않았다: key_id 는 소문자 16진수 16글자(서명 키의 지문)여야 한다."
MSG_NO_KEY_ID = "만들지 않았다: 앱에 내장된 현재 키가 없어 key_id 를 정할 수 없다 — 서명 키의 지문을 --key-id 로 준다."
MSG_BAD_MIN = "만들지 않았다: --min-version 은 버전 글이어야 하고 이번 버전 이하여야 한다."
MSG_EXISTS = "만들지 않았다: 매니페스트 파일이 이미 있다 — 후보 폴더를 새로 모아 다시 만든다."
MSG_WRITE = "만들지 못했다: 매니페스트 파일을 쓰지 못했다."
MSG_REFUSED = "만들지 않았다: 앱이 받아들이지 않을 매니페스트다(이유 이름표: %s)."
MSG_PROBLEMS = "후보 폴더에 문제가 있다."
MSG_CHAIN_PROBLEMS = "사슬 확인에서 문제가 있어 매니페스트를 만들지 않았다."


# ---- 순수 부품 -----------------------------------------------------------------------------------------------------------------------------------
def seq_of(issued):
    """발행 시각 → `seq`(시각의 숫자 열네 자리). 앱은 `seq` 가 이 값과 정확히 같아야 받아들인다."""
    return int(issued.strftime("%Y%m%d%H%M%S"))


def expiry_of(issued):
    """발행 + 180일."""
    return issued + timedelta(days=VALID_DAYS)


def time_text(moment):
    """UTC 시각 → `YYYY-MM-DDThh:mm:ssZ`."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def issued_in_range(issued, moment):
    """발행 시각이 허용 범위 안인가 — `EARLIEST_ISSUED` 이상·`LATEST_ISSUED` 미만이고 지금(`moment`)보다 `FUTURE_SLACK` 넘게 앞서지 않는다.
    시각이 시각이 아니거나 시간대가 없거나 계산이 넘치면(`moment` 가 쓸 수 없는 시계일 때) 거짓이다(의심스러우면 거절). 범위를 먼저 보므로 `expiry_of` 가 넘칠 값은 여기까지 오지 못한다."""
    try:
        return EARLIEST_ISSUED <= issued < LATEST_ISSUED and issued <= moment + FUTURE_SLACK
    except (OverflowError, ValueError, TypeError):
        return False


def default_key_id(keyring):
    """앱에 내장된 키 목록의 **현재 키**(역할 `current`) 이름표 — 없으면 None."""
    found = [ident for ident in keyring.ids() if keyring.role_of(ident) == app_keys.ROLE_CURRENT and keyring.lookup(ident) is not None]
    return found[0] if len(found) == 1 else None


def build_manifest(candidate, *, summary, key_id, issued, min_version):
    """후보 기록과 값들 → 매니페스트 사전(설계서 3-2 의 칸 순서). 앱의 규칙에 맞는지는 만드는 쪽(`build_bytes`)이 앱의 코드로 본다."""
    wanted = {item["role"]: item for item in candidate["assets"]}
    files = [{"role": role, "name": wanted[role]["name"], "size": wanted[role]["size"], "sha256": wanted[role]["sha256"]} for role in rc.MANIFEST_ROLES]
    return {
        "schema": SCHEMA, "product": app_manifest.PRODUCT, "channel": candidate["channel"], "version": candidate["version"], "tag": candidate["tag"], "seq": seq_of(issued),
        "issued_utc": time_text(issued), "expires_utc": time_text(expiry_of(issued)), "min_version": min_version, "key_id": key_id, "commit": candidate["commit"],
        "installer": {"kind": candidate["installer"]["kind"], "pack_id": candidate["installer"]["pack_id"]}, "notes": {"summary": summary}, "files": files,
    }


def encode_manifest(obj):
    """사전 → 매니페스트 바이트: UTF-8·BOM 없음·줄 끝 LF·마지막 줄바꿈 하나(바이트로 만든다 — 글 모드의 줄 끝 변환이 끼지 않게)."""
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_bytes(candidate, *, summary, key_id, issued, min_version):
    """매니페스트 바이트를 만들고 앱의 코드(`read_structure`·`validate_fields`)로 읽어 본다 → (바이트, 앱의 `Manifest`). 앱이 거절하면 `ManifestError`."""
    data = encode_manifest(build_manifest(candidate, summary=summary, key_id=key_id, issued=issued, min_version=min_version))
    found = app_manifest.validate_fields(app_manifest.read_structure(data), hashlib.sha256(data).hexdigest(), channels=app_manifest.CHANNELS_OFFLINE)
    return data, found


# ---- 명령줄 -----------------------------------------------------------------------------------------------------------------------------------------
class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError()


def _build_parser():
    parser = _Parser(add_help=False, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    default_version, default_changelog = str(ROOT / "VERSION"), str(ROOT / "CHANGELOG.md")
    first = sub.add_parser("verify-candidate")
    first.add_argument("--dir", required=True)
    first.add_argument("--version-file", default=default_version)
    second = sub.add_parser("build")
    second.add_argument("--dir", required=True)
    second.add_argument("--min-version", required=True)
    second.add_argument("--key-id", default=None)
    second.add_argument("--issued-utc", default=None)
    second.add_argument("--out", default=None)
    second.add_argument("--changelog", default=default_changelog)
    second.add_argument("--version-file", default=default_version)
    return parser


def _version_of(path):
    try:
        return rc.read_version_file(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError):
        return None


def _print_problems(problems, err):
    for item in problems:
        err.write("문제: " + rc.describe(item) + "\n")


def verify_folder(folder, version, *, limits=rc.DEFAULT_LIMITS):
    """후보 폴더 검증 → (후보 기록 또는 None, 문제들): 파일을 **다시 해시해** 기록과 대조하고 이름 규칙·크기 상한·알 수 없는 파일을 보며 기록의 버전이 `VERSION` 과 같은지 본다."""
    candidate, problems = rc.verify_candidate(folder, limits=limits)
    if candidate is not None and candidate["version"] != version:
        problems.append(rc.Problem("version_mismatch", "VERSION"))
    return candidate, problems


def _cmd_verify(args, out, err):
    version = _version_of(args.version_file)
    if version is None:
        err.write(MSG_NO_VERSION + "\n")
        return EXIT_USAGE
    candidate, problems = verify_folder(args.dir, version)
    if problems:
        err.write(MSG_PROBLEMS + "\n")
        _print_problems(problems, err)
        return EXIT_PROBLEMS
    out.write(f"후보가 맞다: 버전 {candidate['version']} · 태그 {candidate['tag']} · 커밋 {candidate['commit'][:7]} · 자산 {len(candidate['assets'])}개를 다시 해시해 기록과 대조했다\n")
    for item in candidate["assets"]:
        out.write(f"- {item['name']} {item['size']}바이트 {item['sha256']}\n")
    return EXIT_OK


def _write_manifest(path, data):
    """매니페스트를 **배타적으로**(`O_EXCL`) 만든다 — 이미 있으면 `FileExistsError`(검사와 쓰기 사이에 파일이 생겨도 덮어쓰지 않는다). 쓰다 실패하면 반쯤 쓴 파일을 지우고 오류를 다시 던진다."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def _cmd_build(args, now, out, err):
    version = _version_of(args.version_file)
    if version is None:
        err.write(MSG_NO_VERSION + "\n")
        return EXIT_USAGE
    try:
        changelog = Path(args.changelog).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        err.write(MSG_NO_CHANGELOG + "\n")
        return EXIT_USAGE
    try:
        moment = now().astimezone(timezone.utc).replace(microsecond=0)
    except (OverflowError, ValueError, OSError):
        moment = None                                                  # 쓸 수 없는 시계 — 아래 범위 검사가 거절한다
    if args.issued_utc is None:
        issued = moment
    else:
        issued = app_manifest.parse_time(args.issued_utc)
        if issued is None:
            err.write(MSG_BAD_TIME + "\n")
            return EXIT_USAGE
    if moment is None or issued is None or not issued_in_range(issued, moment):
        err.write(MSG_ISSUED_RANGE + "\n")
        return EXIT_USAGE
    key_id = args.key_id if args.key_id is not None else default_key_id(app_keys.shipped_keyring())
    if key_id is None:
        err.write(MSG_NO_KEY_ID + "\n")
        return EXIT_USAGE
    if _KEY_ID.fullmatch(key_id) is None:
        err.write(MSG_BAD_KEY_ID + "\n")
        return EXIT_USAGE
    if app_versions.parse_version(args.min_version) is None or app_versions.compare(args.min_version, version) > 0:
        err.write(MSG_BAD_MIN + "\n")
        return EXIT_USAGE
    target = args.out if args.out is not None else os.path.join(args.dir, rc.MANIFEST_NAME)
    if os.path.lexists(target):
        err.write(MSG_EXISTS + "\n")
        return EXIT_USAGE
    candidate, _problems = rc.verify_candidate(args.dir)
    problems = rc.check_chain(args.dir, version, commit=candidate["commit"] if candidate is not None else None, changelog_text=changelog)
    if candidate is None or problems:
        err.write(MSG_CHAIN_PROBLEMS + "\n")
        _print_problems(problems, err)
        return EXIT_PROBLEMS
    summary = rc.summary_of(rc.notes_section(changelog, version)[1])
    try:
        data, found = build_bytes(candidate, summary=summary, key_id=key_id, issued=issued, min_version=args.min_version)
    except app_manifest.ManifestError as error:
        err.write(MSG_REFUSED % error.reason + "\n")
        return EXIT_MANIFEST
    try:
        _write_manifest(target, data)
    except FileExistsError:
        err.write(MSG_EXISTS + "\n")
        return EXIT_USAGE
    except OSError:
        err.write(MSG_WRITE + "\n")
        return EXIT_USAGE
    out.write(f"매니페스트를 만들었다: {os.path.basename(target)} · 버전 {found.version} · 태그 {found.tag} · 채널 {found.channel} · seq {found.seq}\n")
    out.write(f"발행 {time_text(found.issued)} · 만료 {time_text(found.expires)} · 최소 버전 {found.min_version} · key_id {found.key_id} · 커밋 {found.commit[:7]}\n")
    for item in found.files:
        out.write(f"- {item.role} {item.name} {item.size}바이트 {item.sha256}\n")
    out.write("서명은 scripts/update_sign.py 가 한다(이 도구는 키를 모른다).\n")
    return EXIT_OK


def main(argv=None, *, now=None, stdout=None, stderr=None):
    """명령줄 진입점. 시험이 `now`(시각을 돌려주는 함수)·`stdout`·`stderr` 를 바꿔 끼운다."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    clock = now if now is not None else (lambda: datetime.now(timezone.utc))
    try:
        args = _build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    except _UsageError:
        err.write(MSG_USAGE + "\n")
        return EXIT_USAGE
    if args.command == "verify-candidate":
        return _cmd_verify(args, out, err)
    return _cmd_build(args, clock, out, err)


if __name__ == "__main__":
    sys.exit(main())
