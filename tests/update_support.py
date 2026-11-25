"""업데이트 시험 도우미(시험이 아니다 — UPDATE 설계서 5절, v1update U-1).

**서명 만들기는 앱에 없다**(릴리스 도구 몫). 시험이 서명된 매니페스트를 만들려면 서명기가 필요해서, 이 파일에 **앱의 검증기(`update/ed25519.py`)와 다른 방식**으로 쓴 참고 서명기를 둔다 —
점 계산을 확장 좌표가 아니라 **아핀 좌표와 모듈러 역원**으로 하고 기본점도 y = 4/5 에서 따로 구한다(두 구현이 같은 실수를 하지 않게). 시험 키는 모두 시험 안에서 이름 글자의 해시로 만든 임시 씨앗이다
(비밀이 아니고 어떤 실제 키와도 관계없다). RFC 8032 7.1 의 시험 벡터는 공개 값이다. 가능하면 `openssl`(3.x)로 교차 확인한다 — 없으면 그 시험은 건너뛴다(건너뜀 이유를 시험 이름에 남긴다).
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)

# RFC 8032 7.1 (Ed25519) — 공개 시험 벡터. (씨앗, 공개키, 메시지, 서명) 16진수. 같은 값을 `openssl` 로도 만들어 확인했다.
RFC_VECTORS = (
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60", "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb", "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7", "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
    ("833fe62409237b9d62ec77587520911e9a759cec1d19755b7da901b96dca3d42", "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf",
     "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
     "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b58909351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704"),
)
# RFC 8032 5.1 의 기본점 B 의 아핀 좌표 — 공개 상수
RFC_BASE_X = 15112221349535400772501151409588531511454012693041857206046113283949847762202
RFC_BASE_Y = 46316835694926478169428394003475163141307993866256225615783033603165251855960


def seed_for(label):
    """시험 안의 임시 씨앗 — 이름 글자의 해시(비밀이 아니다)."""
    return hashlib.sha256(("v1update-test-seed:" + label).encode("utf-8")).digest()


# ---- 아핀 좌표 참고 구현(검증기와 다른 방식) ---------------------------------------------------------------------------------------------------------------
def _inv(value):
    return pow(value, -1, P)


def point_add(first, second):
    """아핀 점 덧셈(항등원은 (0, 1)) — 완전한 공식이라 두 배도 같다."""
    x1, y1 = first
    x2, y2 = second
    cross = D * x1 % P * x2 % P * y1 % P * y2 % P
    return ((x1 * y2 + y1 * x2) * _inv(1 + cross) % P, (y1 * y2 + x1 * x2) * _inv(1 - cross) % P)


def point_mul(scalar, point):
    result = (0, 1)
    addend = point
    while scalar:
        if scalar & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        scalar >>= 1
    return result


def recover_x(y, sign):
    """y 로 x 를 구한다(없으면 None) — 검증기의 `_decode` 와 다른 길(제곱근 후보 두 개를 직접 시험)."""
    numerator = (y * y - 1) % P
    denominator = (D * y * y + 1) % P
    square = numerator * _inv(denominator) % P
    root = pow(square, (P + 3) // 8, P)
    if root * root % P != square:
        root = root * SQRT_M1 % P
    if root * root % P != square:
        return None
    if root == 0 and sign:
        return None
    return root if (root & 1) == sign else (P - root) % P


def encode(point):
    x, y = point
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def decode(data):
    value = int.from_bytes(data, "little")
    y = value & ((1 << 255) - 1)
    if y >= P:
        return None
    x = recover_x(y, value >> 255)
    return None if x is None else (x, y)


BASE_Y = 4 * _inv(5) % P
BASE = (recover_x(BASE_Y, 0), BASE_Y)


def _expand(seed):
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar, digest[32:]


def public_key(seed):
    scalar, _prefix = _expand(seed)
    return encode(point_mul(scalar, BASE))


def sign(seed, message):
    """RFC 8032 5.1.6 — 참고 서명기(시험 전용)."""
    scalar, prefix = _expand(seed)
    pub = encode(point_mul(scalar, BASE))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % L
    r_enc = encode(point_mul(r, BASE))
    k = int.from_bytes(hashlib.sha512(r_enc + pub + message).digest(), "little") % L
    return r_enc + int.to_bytes((r + k * scalar) % L, 32, "little")


def naive_verify(pub, message, signature, *, cofactor=True, reject_small_order=False):
    """아핀 좌표의 단순 검증기 — 시험이 '이 방어가 없으면 위조가 통과한다' 를 보이는 데 쓴다(앱의 검증기가 아니다)."""
    a_point, r_point = decode(pub), decode(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if a_point is None or r_point is None or s >= L:
        return False
    if reject_small_order and (point_mul(8, a_point) == (0, 1) or point_mul(8, r_point) == (0, 1)):
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + pub + message).digest(), "little") % L
    left = point_mul(s, BASE)
    right = point_add(r_point, point_mul(k, a_point))
    if cofactor:
        return point_mul(8, left) == point_mul(8, right)
    return left == right


def torsion_points():
    """위수가 8 이하인 점 여덟 개(항등원 포함) — 임의의 점에 L 을 곱해(소수 위수 몫을 없애) 위수 8 의 점을 찾고 그 배수를 모은다."""
    y = 2
    while True:
        point = decode(int.to_bytes(y, 32, "little"))
        y += 1
        if point is None:
            continue
        generator = point_mul(L, point)
        if point_mul(4, generator) != (0, 1):               # 위수 8(4 배가 항등원이 아님)
            found = [(0, 1)]
            current = generator
            while current != (0, 1):
                found.append(current)
                current = point_add(current, generator)
            return found


# ---- openssl 교차 확인 ------------------------------------------------------------------------------------------------------------------------------------
def openssl_path():
    found = shutil.which("openssl")
    if not found:
        return None
    try:
        done = subprocess.run([found, "version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return found if done.returncode == 0 and done.stdout.startswith("OpenSSL 3") else None


PKCS8_ED25519_PREFIX = bytes.fromhex("302e020100300506032b657004220420")
SPKI_ED25519_PREFIX = bytes.fromhex("302a300506032b6570032100")


def openssl_sign(seed, message, exe):
    """`openssl pkeyutl -sign -rawin` 으로 서명한 64바이트와 공개키(32바이트). 빈 메시지는 이 명령이 받지 않는다."""
    with tempfile.TemporaryDirectory() as folder:
        key, data, out = (os.path.join(folder, name) for name in ("k.der", "m.bin", "s.bin"))
        with open(key, "wb") as handle:
            handle.write(PKCS8_ED25519_PREFIX + seed)
        with open(data, "wb") as handle:
            handle.write(message)
        pub = subprocess.run([exe, "pkey", "-inform", "DER", "-in", key, "-pubout", "-outform", "DER"], capture_output=True, check=True, timeout=60).stdout[-32:]
        subprocess.run([exe, "pkeyutl", "-sign", "-inkey", key, "-keyform", "DER", "-rawin", "-in", data, "-out", out], capture_output=True, check=True, timeout=60)
        with open(out, "rb") as handle:
            return handle.read(), pub


def openssl_verify(pub, message, signature, exe):
    with tempfile.TemporaryDirectory() as folder:
        key, data, sig = (os.path.join(folder, name) for name in ("p.der", "m.bin", "s.bin"))
        with open(key, "wb") as handle:
            handle.write(SPKI_ED25519_PREFIX + pub)
        with open(data, "wb") as handle:
            handle.write(message)
        with open(sig, "wb") as handle:
            handle.write(signature)
        done = subprocess.run([exe, "pkeyutl", "-verify", "-pubin", "-inkey", key, "-keyform", "DER", "-rawin", "-in", data, "-sigfile", sig], capture_output=True, timeout=60)
        return done.returncode == 0


# ---- 매니페스트 만들기(시험 전용 — 앱의 읽기 규칙과 따로 적은 값) --------------------------------------------------------------------------------------
SIGN_PREFIX = b"ChanceBlogDesktop-update-manifest-v1\n"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def key_id_of(pub):
    return hashlib.sha256(pub).hexdigest()[:16]


def manifest_dict(**changes):
    """설계서 3-2 의 예(가짜 값)에 `changes` 를 덮어쓴 사전. 값이 `...`(Ellipsis) 이면 그 칸을 뺀다."""
    base = {
        "schema": 1, "product": "ChanceBlogDesktop", "channel": "stable", "version": "1.0.1", "tag": "v1.0.1", "seq": 20261201030000,
        "issued_utc": "2026-12-01T03:00:00Z", "expires_utc": "2027-05-30T03:00:00Z", "min_version": "1.0.0",
        "key_id": "0123456789abcdef", "commit": "0123456789abcdef0123456789abcdef01234567",
        "installer": {"kind": "velopack", "pack_id": "ChanceBlogDesktopApp"},
        "notes": {"summary": "글 목록이 더 빨리 열려요."},
        "files": [
            {"role": "setup", "name": "ChanceBlogDesktop-1.0.1-Setup.exe", "size": 46000000, "sha256": HASH_A},
            {"role": "package", "name": "ChanceBlogDesktopApp-1.0.1-stable-full.nupkg", "size": 41000000, "sha256": HASH_B},
            {"role": "feed", "name": "releases.stable.json", "size": 800, "sha256": HASH_C},
        ],
    }
    for name, value in changes.items():
        if value is ...:
            base.pop(name, None)
        else:
            base[name] = value
    if "files" not in changes and base["version"] != "1.0.1":                # 버전만 바꾼 시험은 버전이 든 파일 이름도 함께 따라간다
        for item in base["files"]:
            item["name"] = item["name"].replace("1.0.1", base["version"])
        if base.get("channel") != "stable":
            base["files"][1]["name"] = base["files"][1]["name"].replace("-stable-", "-" + str(base["channel"]) + "-")
    return base


def encode_manifest(data):
    """사전 → 매니페스트 바이트: UTF-8·BOM 없음·LF·마지막 줄바꿈 한 개(설계서 3-2)."""
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def signature_file(seed, manifest_bytes):
    """서명 파일 바이트 — 접두어 + 매니페스트 바이트에 서명한 64바이트를 base64 한 줄(88글자) + LF 로."""
    return base64.b64encode(sign(seed, SIGN_PREFIX + manifest_bytes)) + b"\n"


class SeededTestCase(unittest.TestCase):
    """시험 키 둘(현재·예비)을 만들어 두는 바탕 — 모든 값이 시험 안에서 만든 임시 값이다."""
    SEED_A = seed_for("A")
    SEED_B = seed_for("B")
    PUB_A = public_key(SEED_A)
    PUB_B = public_key(SEED_B)
    ID_A = key_id_of(PUB_A)
    ID_B = key_id_of(PUB_B)
