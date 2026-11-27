"""서명 키 쌍 만들기 — 업데이트 서명용 Ed25519 키(RELEASE 설계서 3-5·3-9 의 순서 1, V1REL12·R-1). **운영자가 자기 PC 에서 오프라인으로 돌린다. 이 저장소의 시험은 임시 폴더에서만 돌린다(진짜 키를 만들지 않는다).**

쓰는 법(저장소 밖 폴더의 파일로):
    python -X utf8 scripts/update_keygen.py --out D:/키보관/update_signing_key.txt          현재 키 쌍
    python -X utf8 scripts/update_keygen.py --out E:/예비/update_signing_key_spare.txt --spare   예비 키 쌍(현재 키와 다른 곳에, 다른 파일로)
    python -X utf8 scripts/update_keygen.py --public-of 파일                                  이미 만든 비밀 파일의 공개키·지문만 보인다(두 곳의 사본이 같은지 비밀을 보이지 않고 견주는 방법)

하는 일: 운영체제의 난수로 씨앗 32바이트를 뽑아 `--out` 파일에 **base64 한 줄(44글자) + 줄바꿈 하나**로 쓴다. 화면에는 **공개키(base64)와 지문(공개키의 SHA-256 앞 16글자 — 앱 매니페스트의 `key_id` 와 같은 값)만** 보인다 —
터미널 기록·화면 공유에 비밀이 남지 않게. 비밀 파일의 내용을 채팅·이슈·메일·메신저·클라우드 드라이브에 붙이지 않고, 공개키와 지문만 운영자 `[답변]` 에 적는다.

지키는 것(시험이 지킨다):
  · 이미 있는 이름(파일·폴더·끊어진 링크 포함)은 덮어쓰지 않고 거절한다. **git 작업 폴더 안(`.git` 폴더나 워크트리의 `.git` 파일이 위쪽 어딘가에 있는 곳)이면 거절한다** — 비밀이 저장소에 올라가지 않게.
  · 거절할 때는 난수를 뽑지도 파일을 만들지도 않는다. 파일은 배타적으로 만들고(POSIX 에서는 현재 사용자만 읽는 권한 — **윈도에서는 `0o600` 이 접근 권한을 좁히지 않는다**: 파일은 놓이는 폴더의 상속 권한을 그대로 따르므로
    본인 계정만 읽는 폴더에 두고 여러 사람이 쓰는 PC 에서는 폴더 권한을 따로 확인한다 — 화면 경고 셋째 줄) 디스크에 내보낸 뒤, 쓰기에 실패하면 반쯤 쓴 파일을 지우고, 만든 뒤 다시 읽어 같은 공개키가 나오는지 확인한다.
  · 화면 글은 고정 문장과 공개 값뿐이고 폴더 경로는 보이지 않는다(파일 이름만). 이 파일은 `logging`·`traceback` 을 가져오지 않는다. 오류 글에는 인자·파일 내용이 없다.

OpenSSL(Git for Windows 에 들어 있다)로 같은 키를 만드는 법은 `docs/RELEASE.md` 의 '서명 도구와 릴리스 점검' 절에 있다 — 서명 도구가 OpenSSL 의 PKCS#8 PEM 도 읽는다.
종료 코드: 0 성공 · 1 만들지 못함(난수·쓰기·다시 읽기) · 2 사용법·거절 · 3 `--public-of` 파일을 못 읽음 · 4 키 파일은 만들었고 다시 읽어 맞지만 공개 값을 화면에 쓰지 못함
(재작업 1·Q 의 R2 — 출력 인코딩이 한글·긴 줄표를 못 쓰면 못 쓰는 글자만 물음표로 바꿔 쓰므로 보통은 0 이고, 닫힌 파이프처럼 아예 못 쓸 때만 4 와 ASCII 고정 문장 — 공개 값은 `--public-of 파일` 로 다시 본다).
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import update_sign  # noqa: E402

SEED_BYTES = 32
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_UNREADABLE, EXIT_OUTPUT = 0, 1, 2, 3, 4
MAX_KEY_FILE_BYTES = 4096

MSG_USAGE = "사용법 오류: --out 파일 [--spare] 또는 --public-of 파일 만 쓴다. 비밀 값은 화면에 보이지 않는다."
MSG_EXISTS = "만들지 않았다: 그 이름의 파일이 이미 있다(덮어쓰지 않는다)."
MSG_IN_GIT = "만들지 않았다: git 작업 폴더 안이다 — 비밀 파일은 저장소 밖에 둔다."
MSG_NO_FOLDER = "만들지 않았다: 파일을 둘 폴더가 없다."
MSG_NO_ENTROPY = "만들지 못했다: 난수를 얻지 못했다."
MSG_WRITE_FAILED = "만들지 못했다: 파일을 쓰다 운영체제가 거절했다."
MSG_READ_BACK = "만들지 못했다: 쓴 파일을 다시 읽으니 맞지 않다."
MSG_OUTPUT_FAILED = ("key file created, but the public values could not be printed (output encoding or a closed pipe) - "
                     "show them again with --public-of FILE; run with PYTHONUTF8=1 and a UTF-8 console.")      # ASCII 고정 문장 — 어떤 출력 인코딩으로도 쓸 수 있다
MSG_UNREADABLE = "읽지 못했다: 파일이 없거나 서명 키의 형식을 알아볼 수 없다."
LINE_CREATED = "새 서명 키 쌍을 만들었다 — 역할: %s"
LINE_FILE = "비밀 파일: %s (내용을 어디에도 붙이지 않는다)"
LINE_PUBLIC = "공개키(base64): %s"
LINE_FINGERPRINT = "지문(SHA-256 앞 16글자): %s"
LINE_VERIFIED = "파일을 다시 읽어 같은 공개키가 나오는 것을 확인했다."
ROLE_CURRENT = "현재 키(current)"
ROLE_SPARE = "예비 키(spare)"
WARNINGS = ("[주의] 비밀 파일의 내용을 채팅·이슈·메일·메신저·클라우드 드라이브에 붙이지 않는다. 이 화면의 공개키와 지문만 [답변] 에 적는다.",
            "[주의] 비밀 파일은 저장소·클라우드 동기화 폴더 밖의 서로 다른 오프라인 곳 두 군데에 복사하고, --public-of 로 두 곳의 지문이 같은지 확인한다.",
            "[주의] 윈도에서는 파일 권한 비트(0o600)가 접근 권한을 좁히지 않는다 — 비밀 파일은 본인 계정만 읽는 폴더(사용자 프로필 아래)에 두고, 여러 사람이 쓰는 PC 라면 폴더 권한을 따로 확인한다(icacls).")


def inside_git_work_tree(path, *, exists=os.path.exists, realpath=os.path.realpath):
    """`path` 가 어떤 git 작업 폴더 안인가 — 자기와 위쪽 폴더들에서 `.git`(폴더 또는 워크트리의 파일)을 찾는다. 심볼릭 링크는 실제 위치로 따라간다."""
    current = realpath(path)
    while True:
        if exists(os.path.join(current, ".git")):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def _opener(name, flags):
    return os.open(name, flags, 0o600)                     # 현재 사용자만 읽고 쓴다(POSIX — 윈도는 권한 비트로 접근을 좁히지 않는다: 폴더의 상속 권한을 따른다)


def _write_new_file(path, data):
    """배타적으로 만들어(이미 있으면 `FileExistsError`) 쓰고 디스크에 내보낸다. 쓰다 실패하면 반쯤 쓴 파일을 지우고 오류를 다시 던진다."""
    with open(path, "xb", opener=_opener) as handle:
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            handle.close()
            try:
                os.unlink(path)
            except OSError:
                pass
            raise


def _read_back(path):
    """쓴 파일을 다시 읽어 씨앗으로 푼다(서명 도구와 같은 읽기 규칙)."""
    with open(path, "rb") as handle:
        return update_sign.parse_signing_key(handle.read(MAX_KEY_FILE_BYTES).decode("ascii"))


def _fail(err, code, message):
    update_sign.say(err, message + "\n")
    return code


def _generate(out_path, spare, entropy, stdout, stderr):
    folder = os.path.dirname(os.path.abspath(out_path))
    if os.path.lexists(out_path):
        return _fail(stderr, EXIT_USAGE, MSG_EXISTS)
    if not os.path.isdir(folder):
        return _fail(stderr, EXIT_USAGE, MSG_NO_FOLDER)
    if inside_git_work_tree(folder):
        return _fail(stderr, EXIT_USAGE, MSG_IN_GIT)
    seed = entropy(SEED_BYTES)
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != SEED_BYTES:
        return _fail(stderr, EXIT_FAILED, MSG_NO_ENTROPY)
    seed = bytes(seed)
    public = update_sign.public_key(seed)
    try:
        _write_new_file(out_path, base64.b64encode(seed) + b"\n")
    except FileExistsError:
        return _fail(stderr, EXIT_USAGE, MSG_EXISTS)
    except OSError:
        return _fail(stderr, EXIT_FAILED, MSG_WRITE_FAILED)
    try:
        matches = _read_back(out_path) == seed
    except (OSError, ValueError):
        matches = False
    if not matches:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        return _fail(stderr, EXIT_FAILED, MSG_READ_BACK)
    lines = [LINE_CREATED % (ROLE_SPARE if spare else ROLE_CURRENT), LINE_FILE % os.path.basename(out_path), LINE_PUBLIC % base64.b64encode(public).decode("ascii"),
             LINE_FINGERPRINT % update_sign.key_id_of(public), LINE_VERIFIED, *WARNINGS]
    if not update_sign.say(stdout, "\n".join(lines) + "\n"):                  # 키 파일은 이미 있고 다시 읽어 맞다 — 공개 값을 못 쓴 것은 파일 쓰기 실패와 다른 코드·ASCII 문장으로 알린다
        update_sign.say(stderr, MSG_OUTPUT_FAILED + "\n")
        return EXIT_OUTPUT
    return EXIT_OK


def _public_of(path, stdout, stderr):
    try:
        with open(path, "rb") as handle:
            seed = update_sign.parse_signing_key(handle.read(MAX_KEY_FILE_BYTES).decode("ascii"))
    except (OSError, ValueError):
        return _fail(stderr, EXIT_UNREADABLE, MSG_UNREADABLE)
    public = update_sign.public_key(seed)
    shown = LINE_PUBLIC % base64.b64encode(public).decode("ascii") + "\n" + LINE_FINGERPRINT % update_sign.key_id_of(public) + "\n"
    if not update_sign.say(stdout, shown):
        update_sign.say(stderr, MSG_OUTPUT_FAILED + "\n")
        return EXIT_OUTPUT
    return EXIT_OK


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError()                                # 인자 글을 되풀이하지 않는다


def _parser():
    parser = _Parser(add_help=False, allow_abbrev=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--out")
    group.add_argument("--public-of")
    parser.add_argument("--spare", action="store_true")
    return parser


def main(argv=None, *, entropy=os.urandom, stdout=None, stderr=None):
    """명령줄 진입점. 시험이 `entropy`(바이트 수 → 바이트)·`stdout`·`stderr` 를 바꿔 끼운다. 어떤 예외도 밖으로 내보내지 않는다."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    try:
        args = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))
        if args.public_of is not None:
            if args.spare:
                return _fail(err, EXIT_USAGE, MSG_USAGE)
            return _public_of(args.public_of, out, err)
        return _generate(args.out, args.spare, entropy, out, err)
    except _UsageError:
        return _fail(err, EXIT_USAGE, MSG_USAGE)
    except Exception as error:      # noqa: BLE001 - 무슨 일이든 종류 이름만 알리고 멈춘다(예외 글에는 값이 들 수 있다)
        update_sign.say(err, "예상하지 못한 오류로 멈췄다(종류: %s). 키 파일을 확인해 주세요.\n" % type(error).__name__)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(update_sign.entry(main))
