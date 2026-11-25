"""`update/ed25519.py` 시험(UPDATE 설계서 3-3·5절, v1update U-1) — **서명 검증기는 수제 암호 코드**라서 '참이어야 할 것이 참인가' 보다 '거짓이어야 할 것이 거짓인가' 를 더 세게 본다.

지키는 것:
  1) RFC 8032 7.1 의 공개 시험 벡터 네 개(길이 0·1·2·64)가 참이고, 기본점·위수가 RFC 의 상수와 같다.
  2) 아핀 좌표로 따로 쓴 참고 서명기(`update_support`)가 만든 무작위 서명 수십 쌍이 참이고, `openssl`(3.x)이 있으면 `openssl` 이 서명한 것도 참, 우리가 만든 것을 `openssl` 도 참으로 본다(없으면 건너뜀).
  3) 서명 64바이트×8비트·공개키 32바이트×8비트·메시지의 모든 비트를 하나씩 바꾸면 거짓이다.
  4) 말랑함: S 에 L 을 더하거나 S 가 L 이상이면 거짓이다(RFC 8.4).
  5) 점 인코딩: y 가 p 이상인 비정규 인코딩·곡선 밖의 y·x 가 0 인데 부호 비트가 1 인 인코딩이 거절된다. 위수 8 이하의 점 여덟 개를 R 이나 A 로 쓴 서명은 거짓이다 —
     그리고 이 방어가 없는 단순 검증기는 그 위조를 참으로 본다(빈 실험이 아니다).
  6) 여덟 배 식: 소수 위수 몫에 작은 위수 성분이 섞인 R 로 만든 서명은 참이고(RFC 8.8) 여덟 배 없는 단순 검증기는 거짓으로 본다(여덟 배 삭제를 잡는다).
  7) 입력 모양: 길이가 틀리거나 바이트가 아닌 값은 예외 없이 거짓이다. 이 모듈은 `hashlib` 외에 아무것도 가져오지 않고 서명 함수가 없다.
네트워크·실제 시크릿 없이 돈다(키는 모두 시험 안의 임시 값).
"""
import ast
import hashlib
import os
import random
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import update_support as us  # noqa: E402

from chanceblog_desktop.update import ed25519  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop" / "update"
OPENSSL = us.openssl_path()
OPENSSL_PAIRS = int(os.environ.get("UPDATE_TEST_OPENSSL_PAIRS", "12"))


def pair(label, message=b"hello update"):
    seed = us.seed_for(label)
    pub = us.public_key(seed)
    return seed, pub, message, us.sign(seed, message)


class KnownAnswerTest(unittest.TestCase):
    def test_the_four_rfc_vectors_verify_and_the_reference_signer_reproduces_them(self):
        for index, (seed, pub, message, signature) in enumerate(us.RFC_VECTORS):
            with self.subTest(vector=index):
                seed, pub, message, signature = (bytes.fromhex(item) for item in (seed, pub, message, signature))
                self.assertTrue(ed25519.verify(pub, message, signature))
                self.assertEqual(us.public_key(seed), pub, "참고 서명기가 RFC 의 공개키를 만든다")
                self.assertEqual(us.sign(seed, message), signature, "참고 서명기가 RFC 의 서명을 만든다")

    def test_base_point_and_group_order_match_the_rfc_constants(self):
        self.assertEqual(us.BASE, (us.RFC_BASE_X, us.RFC_BASE_Y))
        self.assertEqual(ed25519._BASE_ENCODED, us.encode((us.RFC_BASE_X, us.RFC_BASE_Y)))
        self.assertEqual(ed25519.P, 2 ** 255 - 19)
        self.assertEqual(ed25519.L, 2 ** 252 + 27742317777372353535851937790883648493)
        self.assertEqual(us.point_mul(ed25519.L, us.BASE), (0, 1), "기본점에 L 을 곱하면 항등원")
        self.assertNotEqual(us.point_mul(ed25519.L - 1, us.BASE), (0, 1))
        self.assertEqual(pow(2, ed25519.L - 1, ed25519.L), 1, "L 은 소수(페르마 점검)")
        decoded = ed25519._decode(ed25519._BASE_ENCODED)
        self.assertEqual((decoded[0] * pow(decoded[2], -1, ed25519.P) % ed25519.P, decoded[1] * pow(decoded[2], -1, ed25519.P) % ed25519.P), us.BASE)

    def test_the_same_message_with_the_vectors_key_but_another_signature_is_false(self):
        seed, pub, message, signature = (bytes.fromhex(item) for item in us.RFC_VECTORS[1])
        other = bytes.fromhex(us.RFC_VECTORS[2][3])
        self.assertFalse(ed25519.verify(pub, message, other))
        self.assertFalse(ed25519.verify(pub, message + b"\x00", signature))
        self.assertFalse(ed25519.verify(bytes.fromhex(us.RFC_VECTORS[0][1]), message, signature))


class CrossCheckTest(unittest.TestCase):
    def test_random_reference_signatures_verify_for_many_message_lengths(self):
        rng = random.Random(8032)
        for count in range(30):
            seed = bytes(rng.getrandbits(8) for _ in range(32))
            message = bytes(rng.getrandbits(8) for _ in range(rng.choice((0, 1, 2, 31, 32, 33, 63, 64, 65, 127, 128, 129, 255, 300, 1023))))
            with self.subTest(count=count, length=len(message)):
                self.assertTrue(ed25519.verify(us.public_key(seed), message, us.sign(seed, message)))

    def test_one_megabyte_message(self):
        seed = us.seed_for("big")
        message = bytes(range(256)) * 4096
        self.assertTrue(ed25519.verify(us.public_key(seed), message, us.sign(seed, message)))
        self.assertFalse(ed25519.verify(us.public_key(seed), message[:-1], us.sign(seed, message)))

    @unittest.skipIf(OPENSSL is None, "건너뜀: openssl 3.x 가 없다 — 교차 확인은 openssl 이 있는 칸에서만")
    def test_openssl_signatures_verify_here_and_ours_verify_in_openssl(self):
        """무작위 열두 쌍(윈도에서 openssl 을 한 번 띄우는 데 0.4초쯤 걸려 쌍 수를 줄였다 — 200쌍 전수 확인은 `OPENSSL_PAIRS` 를 키워 한 번 돌렸고 증거 파일이 보고서 폴더에 있다)."""
        rng = random.Random(25519)
        for count in range(OPENSSL_PAIRS):
            seed = bytes(rng.getrandbits(8) for _ in range(32))
            message = bytes(rng.getrandbits(8) for _ in range(rng.randint(1, 400)))
            with self.subTest(count=count):
                pub = us.public_key(seed)
                theirs, their_pub = us.openssl_sign(seed, message, OPENSSL)
                self.assertEqual(their_pub, pub, "공개키가 openssl 과 같다")
                self.assertTrue(ed25519.verify(pub, message, theirs), "openssl 이 서명한 것을 우리 검증기가 참으로 본다")
                self.assertEqual(theirs, us.sign(seed, message), "서명은 결정적이라 참고 서명기와 같다")
                self.assertTrue(us.openssl_verify(pub, message, theirs, OPENSSL), "대조 — openssl 은 자기 서명을 참으로 본다")
                if count < 3:
                    bad = bytearray(theirs)
                    bad[count * 7 % 64] ^= 1 << (count % 8)
                    self.assertFalse(ed25519.verify(pub, message, bytes(bad)))
                    self.assertFalse(us.openssl_verify(pub, message, bytes(bad), OPENSSL), "대조 — 바꾼 서명은 openssl 도 거짓")

    @unittest.skipIf(OPENSSL is None, "건너뜀: openssl 3.x 가 없다")
    def test_a_1023_byte_message_signed_by_openssl(self):
        seed = us.seed_for("len1023")
        message = bytes((index * 7 + 3) % 256 for index in range(1023))
        theirs, pub = us.openssl_sign(seed, message, OPENSSL)
        self.assertTrue(ed25519.verify(pub, message, theirs))


class TamperTest(unittest.TestCase):
    def test_every_single_bit_of_the_signature_the_public_key_and_the_message_breaks_it(self):
        message = bytes(range(24))
        seed, pub, _message, signature = pair("tamper", message)
        self.assertTrue(ed25519.verify(pub, message, signature))
        for index in range(len(signature)):
            for bit in range(8):
                bad = bytearray(signature)
                bad[index] ^= 1 << bit
                self.assertFalse(ed25519.verify(pub, message, bytes(bad)), f"서명 바이트 {index} 비트 {bit}")
        for index in range(len(pub)):
            for bit in range(8):
                bad = bytearray(pub)
                bad[index] ^= 1 << bit
                self.assertFalse(ed25519.verify(bytes(bad), message, signature), f"공개키 바이트 {index} 비트 {bit}")
        for index in range(len(message)):
            for bit in range(8):
                bad = bytearray(message)
                bad[index] ^= 1 << bit
                self.assertFalse(ed25519.verify(pub, bytes(bad), signature), f"메시지 바이트 {index} 비트 {bit}")

    def test_swapping_the_two_halves_or_zeroing_a_half_is_false(self):
        seed, pub, message, signature = pair("halves")
        for bad in (signature[32:] + signature[:32], bytes(32) + signature[32:], signature[:32] + bytes(32), bytes(64), b"\xff" * 64):
            self.assertFalse(ed25519.verify(pub, message, bad))


class MalleabilityTest(unittest.TestCase):
    def test_a_scalar_at_or_above_the_group_order_is_false(self):
        seed, pub, message, signature = pair("malleable")
        s = int.from_bytes(signature[32:], "little")
        self.assertLess(s, ed25519.L)
        for shifted in (s + ed25519.L, s + 2 * ed25519.L, ed25519.L, ed25519.L + 1, (1 << 256) - 1):
            bad = signature[:32] + int.to_bytes(shifted, 32, "little")
            self.assertFalse(ed25519.verify(pub, message, bad), shifted)
        self.assertTrue(ed25519.verify(pub, message, signature))

    def test_the_scalar_range_check_is_what_stops_s_plus_l(self):
        """대조(빈 실험이 아님) — S 범위 검사가 없다면 S+L 은 같은 식을 만족한다: 같은 점이다. 범위 검사를 지운 변이가 이 시험을 깬다."""
        seed, pub, message, signature = pair("malleable2")
        s = int.from_bytes(signature[32:], "little")
        a_point, r_point = us.decode(pub), us.decode(signature[:32])
        k = int.from_bytes(hashlib.sha512(signature[:32] + pub + message).digest(), "little") % us.L
        self.assertEqual(us.point_mul(s + us.L, us.BASE), us.point_mul(s, us.BASE))
        self.assertEqual(us.point_mul(s + us.L, us.BASE), us.point_add(r_point, us.point_mul(k, a_point)))


class PointEncodingTest(unittest.TestCase):
    P = ed25519.P

    def test_non_canonical_y_is_refused(self):
        for offset in range(0, 19):
            raw = int.to_bytes(self.P + offset, 32, "little")
            self.assertIsNone(ed25519._decode(raw), offset)
            self.assertIsNone(ed25519._decode(int.to_bytes((self.P + offset) | (1 << 255), 32, "little")), offset)
        self.assertIsNone(ed25519._decode(b"\xff" * 32))
        self.assertIsNone(ed25519._decode(int.to_bytes((1 << 255) - 1, 32, "little")))
        # 대조: 같은 점의 정규 인코딩은 읽힌다(y = 1 은 항등원, y = p - 1 은 위수 2)
        self.assertIsNotNone(ed25519._decode(int.to_bytes(1, 32, "little")))
        self.assertIsNotNone(ed25519._decode(int.to_bytes(self.P - 1, 32, "little")))

    def test_a_point_with_x_zero_and_the_sign_bit_set_is_refused(self):
        self.assertIsNone(ed25519._decode(int.to_bytes(1 | (1 << 255), 32, "little")))
        self.assertIsNone(ed25519._decode(int.to_bytes((self.P - 1) | (1 << 255), 32, "little")))
        self.assertIsNotNone(ed25519._decode(int.to_bytes(1, 32, "little")))

    def test_a_y_that_is_not_on_the_curve_is_refused_and_the_decoders_agree(self):
        off_curve = 0
        for y in range(2, 200):
            raw = int.to_bytes(y, 32, "little")
            ours, reference = ed25519._decode(raw), us.decode(raw)
            self.assertEqual(ours is None, reference is None, y)
            if ours is None:
                off_curve += 1
        self.assertGreater(off_curve, 20, "곡선 밖의 y 가 실제로 걸러졌다(빈 실험이 아니다)")
        self.assertFalse(ed25519.verify(int.to_bytes(self._first_off_curve(), 32, "little"), b"m", bytes(64)))

    @staticmethod
    def _first_off_curve():
        return next(y for y in range(2, 200) if us.decode(int.to_bytes(y, 32, "little")) is None)

    def test_our_decoder_and_the_reference_decoder_agree_on_random_encodings(self):
        rng = random.Random(7)
        for _ in range(120):
            raw = bytes(rng.getrandbits(8) for _ in range(32))
            ours, reference = ed25519._decode(raw), us.decode(raw)
            self.assertEqual(ours is None, reference is None, raw.hex())
            if ours is not None:
                z = pow(ours[2], -1, ed25519.P)
                self.assertEqual((ours[0] * z % ed25519.P, ours[1] * z % ed25519.P), reference)


class SmallOrderTest(unittest.TestCase):
    def setUp(self):
        self.points = us.torsion_points()

    def test_the_eight_small_order_points_are_found_and_recognised(self):
        self.assertEqual(len(self.points), 8)
        self.assertEqual(len(set(self.points)), 8)
        for point in self.points:
            decoded = ed25519._decode(us.encode(point))
            self.assertIsNotNone(decoded, point)
            self.assertTrue(ed25519._small_order(decoded), point)
        self.assertFalse(ed25519._small_order(ed25519._BASE))
        seed, pub, message, signature = pair("order")
        self.assertFalse(ed25519._small_order(ed25519._decode(pub)))

    def test_forged_signatures_with_small_order_points_are_false_while_a_naive_verifier_accepts_them(self):
        """모든 작은 위수 점을 A 로, 항등원·작은 위수 점을 R 로 쓴 '아무 메시지에나 통하는' 위조 — 앱의 검증기는 모두 거짓이고, 방어 없는 단순 검증기는 참으로 본다."""
        message = b"any message at all"
        accepted_by_naive = 0
        for a_point in self.points:
            pub = us.encode(a_point)
            for r_point in self.points:
                signature = us.encode(r_point) + bytes(32)
                self.assertFalse(ed25519.verify(pub, message, signature), (a_point, r_point))
                if us.naive_verify(pub, message, signature, cofactor=True):
                    accepted_by_naive += 1
        self.assertGreater(accepted_by_naive, 0, "대조 — 단순 검증기는 이 위조 가운데 일부를 참으로 본다(방어를 지우면 이 시험이 빨개진다)")
        self.assertTrue(us.naive_verify(us.encode(self.points[0]), message, us.encode(self.points[0]) + bytes(32)), "항등원 공개키 + 항등원 R + S=0 은 단순 검증기가 참")
        self.assertFalse(us.naive_verify(us.encode(self.points[0]), message, us.encode(self.points[0]) + bytes(32), reject_small_order=True))

    def test_a_small_order_r_or_a_with_a_genuine_key_is_false(self):
        seed, pub, message, signature = pair("genuine")
        for point in self.points:
            self.assertFalse(ed25519.verify(pub, message, us.encode(point) + signature[32:]), "작은 위수 R")
            self.assertFalse(ed25519.verify(us.encode(point), message, signature), "작은 위수 A")


class CofactorTest(unittest.TestCase):
    def test_a_signature_whose_r_carries_a_small_order_component_is_true_only_with_the_times_eight_equation(self):
        """RFC 8.8 — R = R0 + T(T 는 위수 8 의 점)로 만든 서명은 [S]B = R + [k]A 를 만족하지 않지만 [8] 배 식은 만족한다. 앱의 검증기는 참, 여덟 배가 없는 단순 검증기는 거짓."""
        seed = us.seed_for("cofactor")
        scalar, prefix = us._expand(seed)
        pub = us.encode(us.point_mul(scalar, us.BASE))
        message = b"mixed order"
        generator = next(point for point in us.torsion_points() if us.point_mul(4, point) != (0, 1))
        r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % us.L
        r_mixed = us.point_add(us.point_mul(r, us.BASE), generator)
        r_enc = us.encode(r_mixed)
        k = int.from_bytes(hashlib.sha512(r_enc + pub + message).digest(), "little") % us.L
        signature = r_enc + int.to_bytes((r + k * scalar) % us.L, 32, "little")
        self.assertFalse(ed25519._small_order(ed25519._decode(r_enc)), "R 은 작은 위수 점이 아니다(섞인 점이다)")
        self.assertTrue(ed25519.verify(pub, message, signature))
        self.assertTrue(us.naive_verify(pub, message, signature, cofactor=True))
        self.assertFalse(us.naive_verify(pub, message, signature, cofactor=False), "대조 — 여덟 배 없는 식은 거짓이다(여덟 배 삭제를 이 시험이 잡는다)")


class InputShapeTest(unittest.TestCase):
    def setUp(self):
        self.seed, self.pub, self.message, self.signature = pair("shape")

    def test_wrong_lengths_are_false_without_an_exception(self):
        for length in list(range(0, 64)) + list(range(65, 70)) + [127, 128, 1000]:
            self.assertFalse(ed25519.verify(self.pub, self.message, (self.signature * 20)[:length]), f"서명 길이 {length}")
        for length in list(range(0, 32)) + list(range(33, 40)) + [64, 100]:
            self.assertFalse(ed25519.verify((self.pub * 4)[:length], self.message, self.signature), f"공개키 길이 {length}")
        self.assertFalse(ed25519.verify(self.pub, self.message, self.signature + bytes(1)))
        self.assertFalse(ed25519.verify(self.pub + bytes(1), self.message, self.signature))
        self.assertTrue(ed25519.verify(self.pub, self.message, self.signature), "대조 — 맞는 길이는 참이다")

    def test_values_that_are_not_bytes_are_false_without_an_exception(self):
        for bad in (None, "text", 0, 1.5, [1, 2], (1,), {"a": 1}, object(), True):
            self.assertFalse(ed25519.verify(bad, self.message, self.signature), repr(bad))
            self.assertFalse(ed25519.verify(self.pub, bad, self.signature), repr(bad))
            self.assertFalse(ed25519.verify(self.pub, self.message, bad), repr(bad))
        self.assertFalse(ed25519.verify(self.pub.hex(), self.message, self.signature))
        self.assertFalse(ed25519.verify(self.pub, self.message, self.signature.hex()))

    def test_bytearray_is_accepted_and_the_input_is_not_modified(self):
        pub, message, signature = bytearray(self.pub), bytearray(self.message), bytearray(self.signature)
        self.assertTrue(ed25519.verify(pub, message, signature))
        self.assertEqual((bytes(pub), bytes(message), bytes(signature)), (self.pub, self.message, self.signature))

    def test_a_valid_signature_is_true_and_the_call_is_fast_enough(self):
        started = time.perf_counter()
        for _ in range(5):
            self.assertTrue(ed25519.verify(self.pub, self.message, self.signature))
        self.assertLess((time.perf_counter() - started) / 5, 1.0, "한 번에 수 밀리초에서 수십 밀리초가 설계 추정이다(여기서는 1초 안이면 통과)")


class SourceShapeTest(unittest.TestCase):
    def tree(self):
        return ast.parse((SRC / "ed25519.py").read_text(encoding="utf-8"))

    def test_the_module_imports_only_hashlib_and_has_no_signing_function(self):
        imports = set()
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
        self.assertEqual(sorted(imports), ["__future__", "hashlib"])
        names = {node.name for node in ast.walk(self.tree()) if isinstance(node, ast.FunctionDef)}
        self.assertEqual(sorted(name for name in names if not name.startswith("_")), ["verify"], "공개 함수는 verify 하나뿐이다(서명 만들기 없음)")
        self.assertFalse([name for name in names if "sign" in name.lower() and name != "_verify"], "서명 만들기 함수가 없다")

    def test_verify_swallows_every_exception_and_never_returns_a_non_bool(self):
        source = ast.unparse(next(node for node in self.tree().body if isinstance(node, ast.FunctionDef) and node.name == "verify"))
        self.assertIn("except Exception", source)
        self.assertIn("is True", source)

    def test_there_is_no_randomness_clock_environment_or_file_access(self):
        text = (SRC / "ed25519.py").read_text(encoding="utf-8")
        for word in ("random", "secrets", "os.environ", "open(", "time.", "socket", "subprocess", "print("):
            self.assertNotIn(word, text, word)


if __name__ == "__main__":
    unittest.main()
