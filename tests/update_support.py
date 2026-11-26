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
# RFC 8032 7.1 의 다섯째 시험 벡터 TEST 1024(메시지 1023바이트) — 위 `RFC_VECTORS`(길이 0·1·2·64)와 같은 모양(씨앗, 공개키, 메시지, 서명). 값은 옮겨 적은 것이라 원문과 글자 대조는 못 했지만(접속 금지),
# 씨앗에서 공개키와 서명을 이 저장소의 참고 서명기와 OpenSSL 3 이 그대로 만들고 앱의 검증기가 참으로 본다는 것을 시험(`test_update_ed25519`)이 지킨다.
RFC_VECTOR_1023 = (
    "f5e5767cf153319517630f226876b86c8160cc583bc013744c6bf255f5cc0ee5", "278117fc144c72340f67d0f2316e8386ceffbf2b2428c9c51fef7c597f1d426e",
    "".join((
        "08b8b2b733424243760fe426a4b54908632110a66c2f6591eabd3345e3e4eb98fa6e264bf09efe12ee50f8f54e9f77b1",
        "e355f6c50544e23fb1433ddf73be84d879de7c0046dc4996d9e773f4bc9efe5738829adb26c81b37c93a1b270b20329d",
        "658675fc6ea534e0810a4432826bf58c941efb65d57a338bbd2e26640f89ffbc1a858efcb8550ee3a5e1998bd177e93a",
        "7363c344fe6b199ee5d02e82d522c4feba15452f80288a821a579116ec6dad2b3b310da903401aa62100ab5d1a36553e",
        "06203b33890cc9b832f79ef80560ccb9a39ce767967ed628c6ad573cb116dbefefd75499da96bd68a8a97b928a8bbc10",
        "3b6621fcde2beca1231d206be6cd9ec7aff6f6c94fcd7204ed3455c68c83f4a41da4af2b74ef5c53f1d8ac70bdcb7ed1",
        "85ce81bd84359d44254d95629e9855a94a7c1958d1f8ada5d0532ed8a5aa3fb2d17ba70eb6248e594e1a2297acbbb39d",
        "502f1a8c6eb6f1ce22b3de1a1f40cc24554119a831a9aad6079cad88425de6bde1a9187ebb6092cf67bf2b13fd65f270",
        "88d78b7e883c8759d2c4f5c65adb7553878ad575f9fad878e80a0c9ba63bcbcc2732e69485bbc9c90bfbd62481d9089b",
        "eccf80cfe2df16a2cf65bd92dd597b0707e0917af48bbb75fed413d238f5555a7a569d80c3414a8d0859dc65a46128ba",
        "b27af87a71314f318c782b23ebfe808b82b0ce26401d2e22f04d83d1255dc51addd3b75a2b1ae0784504df543af8969b",
        "e3ea7082ff7fc9888c144da2af58429ec96031dbcad3dad9af0dcbaaaf268cb8fcffead94f3c7ca495e056a9b47acdb7",
        "51fb73e666c6c655ade8297297d07ad1ba5e43f1bca32301651339e22904cc8c42f58c30c04aafdb038dda0847dd988d",
        "cda6f3bfd15c4b4c4525004aa06eeff8ca61783aacec57fb3d1f92b0fe2fd1a85f6724517b65e614ad6808d6f6ee34df",
        "f7310fdc82aebfd904b01e1dc54b2927094b2db68d6f903b68401adebf5a7e08d78ff4ef5d63653a65040cf9bfd4aca7",
        "984a74d37145986780fc0b16ac451649de6188a7dbdf191f64b5fc5e2ab47b57f7f7276cd419c17a3ca8e1b939ae49e4",
        "88acba6b965610b5480109c8b17b80e1b7b750dfc7598d5d5011fd2dcc5600a32ef5b52a1ecc820e308aa342721aac09",
        "43bf6686b64b2579376504ccc493d97e6aed3fb0f9cd71a43dd497f01f17c0e2cb3797aa2a2f256656168e6c496afc5f",
        "b93246f6b1116398a346f1a641f3b041e989f7914f90cc2c7fff357876e506b50d334ba77c225bc307ba537152f3f161",
        "0e4eafe595f6d9d90d11faa933a15ef1369546868a7f3a45a96768d40fd9d03412c091c6315cf4fde7cb68606937380d",
        "b2eaaa707b4c4185c32eddcdd306705e4dc1ffc872eeee475a64dfac86aba41c0618983f8741c5ef68d3a101e8a3b8ca",
        "c60c905c15fc910840b94c00a0b9d0",
    )),
    "0aab4c900501b3e24d7cdf4663326a3a87df5e4843b2cbdb67cbf6e460fec350aa5371b1508f9f4528ecea23c436d94b5e8fcd4f681e30a6ac00a9704a188a03",
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


OPENSSL_PAIRS_DEFAULT = 12
OPENSSL_PAIRS_MAX = 200


def openssl_pairs(environ=None):
    """openssl 교차 확인에 쓸 쌍의 수 — 기본 열두 쌍이고 환경 변수 `UPDATE_TEST_OPENSSL_PAIRS` 로 늘린다(최대 200). 빈 값·글자·0 이하처럼 **읽을 수 없거나 뜻이 없는 값은 기본값**이다
    (예전에는 빈 값이 시험 파일을 모듈을 불러올 때 통째로 실패시키고 0 은 교차 확인을 빈 실험으로 만들었다). `environ` 은 시험이 넘기는 사전(없으면 진짜 환경)이다."""
    source = os.environ if environ is None else environ
    try:
        count = int(str(source.get("UPDATE_TEST_OPENSSL_PAIRS", "")).strip())
    except ValueError:
        return OPENSSL_PAIRS_DEFAULT
    if count < 1:
        return OPENSSL_PAIRS_DEFAULT
    return min(count, OPENSSL_PAIRS_MAX)


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
