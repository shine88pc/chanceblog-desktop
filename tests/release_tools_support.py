"""릴리스 도구 시험 도우미(시험이 아니다) — 서명 도구(`scripts/update_sign.py`·`update_keygen.py`)·매니페스트 도구(`update_manifest.py`)·릴리스 사슬(`packaging/release_chain.py`)·
사전 점검(`scripts/release_preflight.py`) 시험이 함께 쓴다(V1REL12, R-1·R-2).

가짜 비밀은 **시험이 도는 때 조립**한다 — 소스에 키·씨앗 글을 적지 않는다(`CANARY_` 로 시작하는 바이트로 만든 임시 씨앗이고 어떤 실제 키와도 관계없다). RFC 8032 의 공개 시험 벡터는 `update_support` 에 있다.
가짜 `release/` 폴더·가짜 변경 이력·가짜 `gh`·가짜 환경을 만든다. 네트워크·실제 시크릿·`.github` 없이 돈다.
"""
import hashlib
import io
import json
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _folder in (HERE, ROOT / "src", ROOT / "scripts", ROOT / "packaging"):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import update_support as us  # noqa: E402

PEM_WORD = "PRIVATE KEY"
CANARY_PREFIX = b"CANARY_"


def temp_dir():
    """임시 폴더 — 윈도에서 백신·색인기가 막 만든 파일을 잠깐 잡고 있으면 지우기가 실패하므로 치우기 실패는 넘긴다."""
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def canary_seed(label="a"):
    """32바이트 임시 씨앗 — 맨 앞이 `CANARY_` 이고 나머지는 이름 글자의 해시다(시험이 도는 때 조립, 비밀이 아니다)."""
    return CANARY_PREFIX + hashlib.sha256(("v1rel12-canary:" + label).encode("utf-8")).digest()[:25]


def seed_b64(seed):
    import base64
    return base64.b64encode(seed).decode("ascii")


def seed_pem(seed, *, crlf=False):
    """OpenSSL 이 만드는 PKCS#8 개인키 PEM — 머리 줄은 소스에 한 덩어리로 적지 않고 조립한다."""
    import base64
    der = bytes.fromhex("302e020100300506032b657004220420") + seed
    body = base64.b64encode(der).decode("ascii")
    newline = "\r\n" if crlf else "\n"
    return newline.join(["-----BEGIN " + PEM_WORD + "-----", body, "-----END " + PEM_WORD + "-----"]) + newline


def leak_needles(seed):
    """어떤 출력·오류·로그·파일에도 나오면 안 되는 글 — 씨앗의 base64·16진수·원문 바이트 모양과 그 안의 여덟 글자 조각들."""
    forms = [seed_b64(seed), seed.hex(), seed.decode("latin-1"), repr(seed), "CANARY_"]
    needles = list(forms)
    for form in forms[:2]:
        needles += [form[index:index + 8] for index in range(0, len(form) - 7)]
    return needles


def assert_no_leak(case, seed, *texts):
    """`texts` 어디에도 씨앗의 흔적이 없다."""
    needles = leak_needles(seed)
    for text in texts:
        if isinstance(text, bytes):
            text = text.decode("latin-1")
        for needle in needles:
            case.assertNotIn(needle, text, "비밀 값의 일부가 출력에 있다")


def public_of(seed):
    """시험 안의 참고 구현(아핀 좌표)으로 구한 공개키 — 도구의 구현과 따로 쓴 값이다."""
    return us.public_key(seed)


def key_id(public):
    return hashlib.sha256(public).hexdigest()[:16]


def manifest_bytes(seed, **changes):
    """앱이 받아들이는 가짜 매니페스트 바이트 — `key_id` 는 `seed` 의 공개키 이름표(`...` 로 칸을 뺀다)."""
    changes.setdefault("key_id", key_id(public_of(seed)))
    changes.setdefault("installer", {"kind": "inno", "pack_id": "ChanceBlogDesktop"})
    changes.setdefault("files", [
        {"role": "setup", "name": "ChanceBlogDesktop-1.0.1-Setup.exe", "size": 4600, "sha256": us.HASH_A},
        {"role": "portable", "name": "ChanceBlogDesktop-1.0.1-win64.zip", "size": 4100, "sha256": us.HASH_B},
    ])
    return us.encode_manifest(us.manifest_dict(**changes))


class Capture:
    """`main(argv, stdout=…, stderr=…)` 모양의 도구를 불러 (종료 코드, 표준 출력, 표준 오류)를 돌려준다."""

    def __init__(self, main):
        self.main = main

    def __call__(self, argv, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        code = self.main(list(argv), stdout=out, stderr=err, **kwargs)
        return code, out.getvalue(), err.getvalue()


class FakeProcess:
    """`subprocess.run` 이 돌려주는 값의 모양 — 결과 코드와 바이트 출력."""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class FakeRun:
    """`subprocess.run` 자리에 끼우는 가짜 — 부른 인자와(있으면) 그때 임시 파일에 있던 내용을 적어 둔다. 응답은 `reply`(인자 목록 → FakeProcess)."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.file_texts = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        for part in command:
            path = Path(str(part))
            if path.is_file():
                self.file_texts.append(path.read_bytes())
        return self.reply(list(command))


def ok_process(command):
    return FakeProcess(0, b"Signature Verified Successfully\n", b"")


def failing_process(command):
    return FakeProcess(1, b"Signature Verification Failure\n", b"")


# ---- 변경 이력(CHANGELOG)·릴리스 노트 ----------------------------------------------------------------------------------------------------------------
def notes_section(version="1.0.0", date="2026-12-10", *, summary=("- 첫 정식 판이에요.", "- 글 목록이 빨라졌어요.", "- 백업이 더 안전해졌어요."), details=("- 자세한 변화 한 가지.",), migration=("- 달라지는 것 없음.",),
                  heading=None):
    """`docs/RELEASE.md` 릴리스 노트 규칙의 새 모양 절 하나(머리 줄 + 요약·자세히·이관 노트)."""
    head = heading if heading is not None else f"## [{version}] — {date}"
    return "\n".join([head, "", "### 요약", *summary, "", "### 자세히", *details, "", "### 이관 노트", *migration, ""])


def changelog_text(version="1.0.0", **kwargs):
    old = "## [0.1.0-preview.1] — 2026-11-11 (개인 PC 제한 시험용, 미서명 Package 준비)\n\n- 옛 절이다.\n"
    return "# 변경 이력\n\n" + notes_section(version, **kwargs) + "\n" + old


# ---- 가짜 release/ 폴더 --------------------------------------------------------------------------------------------------------------------------------
FAKE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
SETUP_BYTES = b"setup-bytes-" * 90
ZIP_BYTES = b"zip-bytes-" * 130


def setup_name(version):
    return f"ChanceBlogDesktop-{version}-Setup.exe"


def zip_name(version):
    return f"ChanceBlogDesktop-{version}-win64.zip"


def sums_text(entries):
    return "".join(f"{digest}  {name}\n" for name, digest in sorted(entries))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def package_info(version, zip_data, *, commit=FAKE_COMMIT, **extra):
    """묶음 빌드가 압축 파일 옆에 쓰는 바깥 정보의 모양(필요한 칸만) — 시험이 손으로 적은 값이다."""
    info = {"schema": 1, "product": "ChanceBlog Desktop", "channel": "personal-pc-preview", "trial": False, "variant": "outer", "version": version,
            "git": {"repository": "owner/repo", "commit": commit, "tree": OTHER_COMMIT, "clean": True, "committed_utc": "2026-11-26T00:00:00Z"},
            "package": {"name": zip_name(version), "sha256": hashlib.sha256(zip_data).hexdigest(), "bytes": len(zip_data)}, "release_eligible": True}
    info.update(extra)
    return info


def fake_release(folder, version="1.0.0", *, commit=FAKE_COMMIT, with_candidate=True, setup_data=SETUP_BYTES, zip_data=ZIP_BYTES, info_extra=None):
    """일관된 `release/` 폴더를 손으로 만든다(설치 파일·압축 파일·묶음 정보 둘·해시 목록·후보 기록) → 폴더 경로. 도구의 `assemble` 을 쓰지 않는다 — 도구와 따로 적은 기대값이다."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    write(folder / setup_name(version), setup_data)
    write(folder / zip_name(version), zip_data)
    info = package_info(version, zip_data, commit=commit, **(info_extra or {}))
    write(folder / "PACKAGE_INFO.json", json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    write(folder / "PACKAGE_INFO.md", f"# ChanceBlog Desktop 묶음 정보\n\n- 버전: `{version}`\n")
    names = [setup_name(version), zip_name(version), "PACKAGE_INFO.json", "PACKAGE_INFO.md"]
    write(folder / "SHA256SUMS", sums_text([(name, hashlib.sha256((folder / name).read_bytes()).hexdigest()) for name in names]))
    if with_candidate:
        write_candidate(folder, version, commit=commit)
    return folder


def candidate_dict(folder, version, *, commit=FAKE_COMMIT, kind="inno"):
    folder = Path(folder)
    roles = {setup_name(version): "setup", zip_name(version): "portable", "SHA256SUMS": "sums", "PACKAGE_INFO.json": "info_json", "PACKAGE_INFO.md": "info_md"}
    assets = []
    for name in (setup_name(version), zip_name(version), "SHA256SUMS", "PACKAGE_INFO.json", "PACKAGE_INFO.md"):
        data = (folder / name).read_bytes()
        assets.append({"role": roles[name], "name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    channel = "rc" if "-rc." in version else "stable"
    return {"candidate_schema": 1, "product": "ChanceBlogDesktop", "version": version, "tag": "v" + version, "channel": channel, "commit": commit,
            "image": {"name": "win25", "version": "20261101.1.0"}, "installer": {"kind": kind, "pack_id": "ChanceBlogDesktop"}, "assets": assets}


def write_candidate(folder, version, *, commit=FAKE_COMMIT, change=None):
    data = candidate_dict(folder, version, commit=commit)
    if change:
        change(data)
    write(Path(folder) / "release_candidate.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return data


# ---- 가짜 gh·환경 ------------------------------------------------------------------------------------------------------------------------------------
class FakeGh:
    """`gh` 자리에 끼우는 가짜 — 부른 인자를 적어 두고 응답은 `routes`(인자 글에 들어 있는 낱말 → (결과 코드, 표준 출력, 표준 오류))에서 처음 맞는 것. 네트워크를 쓰지 않는다."""

    def __init__(self, routes=None, default=(1, "", "unrouted")):          # 길을 정하지 않은 호출은 성공이 아니라 실패 — 경로 낱말이 틀려도 조용히 초록이 되지 않는다(Q 의 참고 N3)
        self.routes = list(routes or [])
        self.default = default
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        joined = " ".join(args)
        for needle, reply in self.routes:
            if needle in joined:
                return types.SimpleNamespace(returncode=reply[0], stdout=reply[1], stderr=reply[2])
        return types.SimpleNamespace(returncode=self.default[0], stdout=self.default[1], stderr=self.default[2])
