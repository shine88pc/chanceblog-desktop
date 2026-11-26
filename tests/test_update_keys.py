"""`update/keys.py` 시험(UPDATE 설계서 3-1·질문 Q3, v1update U-1) — 내장 공개키 목록과 폐기 목록.

지키는 것:
  1) **출하 키 자리는 비어 있다**(`SHIPPED_KEYS` · `REVOKED_KEY_IDS`) — 소스에 공개키가 하나도 없고(개인키는 어디에도 없다) 출하 키로 만든 `Keyring` 은 비어 있다. 그래서 어떤 서명도 '모르는 키' 로 거절된다.
  2) 이름표(`key_id`)는 공개키 32바이트의 SHA-256 앞 8바이트를 16진수 16글자로 쓴 값이고, 목록에 넣을 때 키에서 스스로 계산한다(짝이 어긋난 값을 따로 받지 않는다).
  3) 목록의 규칙: 키는 32바이트, 같은 키·같은 역할 둘 없음, 최대 둘(현재 + 예비), 폐기한 이름표는 키가 목록에 있어도 찾아지지 않고 모양이 틀린 이름표·글이 아닌 값도 찾아지지 않는다.
네트워크·실제 시크릿 없이 돈다(시험 키는 모두 시험 안의 임시 값).
"""
import ast
import base64
import hashlib
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import update_support as us  # noqa: E402

from chanceblog_desktop.update import keys  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop" / "update"


class ShippedKeysTest(unittest.TestCase):
    def test_the_shipped_slots_are_empty_and_the_keyring_made_from_them_is_empty(self):
        self.assertEqual(keys.SHIPPED_KEYS, ())
        self.assertEqual(keys.REVOKED_KEY_IDS, ())
        ring = keys.shipped_keyring()
        self.assertEqual((len(ring), ring.ids()), (0, ()))
        self.assertIsNone(ring.lookup("0123456789abcdef"))
        self.assertIsNone(ring.lookup(us.key_id_of(us.public_key(us.seed_for("any")))))

    def test_the_source_holds_no_key_material_at_all(self):
        """공개키 글(base64 44글자·16진수 64글자)도 개인키 모양도 소스에 없다 — 키를 넣는 변경은 따로 온다."""
        import re
        for path in sorted(SRC.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"[0-9a-fA-F]{64}", text), path.name)
            self.assertIsNone(re.search(r"[A-Za-z0-9+/]{43}=", text), path.name)
            self.assertNotIn("PRIVATE KEY", text, path.name)

    def test_the_module_never_signs_or_reads_a_seed(self):
        tree = ast.parse((SRC / "keys.py").read_text(encoding="utf-8"))
        names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        self.assertFalse({name for name in names if "sign" in name.lower() or "seed" in name.lower() or "private" in name.lower()})


class KeyIdTest(unittest.TestCase):
    def test_the_id_is_the_first_eight_bytes_of_the_sha256_in_hex(self):
        pub = us.public_key(us.seed_for("id"))
        self.assertEqual(keys.key_id_of(pub), hashlib.sha256(pub).hexdigest()[:16])
        self.assertRegex(keys.key_id_of(pub), r"^[0-9a-f]{16}$")
        self.assertEqual(keys.key_id_of(bytearray(pub)), keys.key_id_of(pub))


class KeyringTest(unittest.TestCase):
    def setUp(self):
        self.pub_a, self.pub_b = us.public_key(us.seed_for("ring-a")), us.public_key(us.seed_for("ring-b"))
        self.id_a, self.id_b = keys.key_id_of(self.pub_a), keys.key_id_of(self.pub_b)

    def test_both_keys_are_found_by_their_own_ids_and_roles_are_kept(self):
        ring = keys.Keyring([(keys.ROLE_CURRENT, self.pub_a), (keys.ROLE_SPARE, self.pub_b)])
        self.assertEqual((ring.lookup(self.id_a), ring.lookup(self.id_b)), (self.pub_a, self.pub_b))
        self.assertEqual((ring.role_of(self.id_a), ring.role_of(self.id_b)), ("current", "spare"))
        self.assertEqual(ring.ids(), tuple(sorted((self.id_a, self.id_b))))
        self.assertEqual(len(ring), 2)

    def test_a_revoked_id_is_not_found_even_if_the_key_is_listed(self):
        ring = keys.Keyring([(keys.ROLE_CURRENT, self.pub_a), (keys.ROLE_SPARE, self.pub_b)], revoked=(self.id_a,))
        self.assertIsNone(ring.lookup(self.id_a))
        self.assertTrue(ring.is_revoked(self.id_a))
        self.assertEqual(ring.lookup(self.id_b), self.pub_b)

    def test_unknown_malformed_and_non_text_ids_are_not_found(self):
        ring = keys.Keyring([(keys.ROLE_CURRENT, self.pub_a)])
        for bad in ("0" * 16, self.id_a.upper(), self.id_a[:-1], self.id_a + "0", " " + self.id_a, self.id_a + "\n", None, 5, b"abc", ["x"], "", "g" * 16):
            self.assertIsNone(ring.lookup(bad), repr(bad))
        self.assertEqual(ring.lookup(self.id_a), self.pub_a)

    def test_a_wrong_list_is_refused_when_it_is_built(self):
        good = (keys.ROLE_CURRENT, self.pub_a)
        for entries in ([("other", self.pub_a)], [(keys.ROLE_CURRENT, self.pub_a[:31])], [(keys.ROLE_CURRENT, self.pub_a + b"\x01")], [(keys.ROLE_CURRENT, "text")], [good, (keys.ROLE_SPARE, self.pub_a)],
                        [good, (keys.ROLE_CURRENT, self.pub_b)]):
            with self.assertRaises(keys.KeyringError, msg=repr(entries)[:60]):
                keys.Keyring(entries)
        for revoked in (("zz",), (5,), ("0123456789ABCDEF",), ("0123456789abcde",)):
            with self.assertRaises(keys.KeyringError):
                keys.Keyring([good], revoked=revoked)

    def test_more_than_two_keys_are_refused(self):
        pubs = [us.public_key(us.seed_for(f"many-{index}")) for index in range(3)]
        with self.assertRaises(keys.KeyringError):
            keys.Keyring([(keys.ROLE_CURRENT, pubs[0]), (keys.ROLE_SPARE, pubs[1]), ("spare", pubs[2])])
        self.assertEqual(keys.MAX_KEYS, 2)

    def test_decoding_the_shipped_shape_checks_base64_and_shape(self):
        encoded = base64.b64encode(self.pub_a).decode("ascii")
        self.assertEqual(keys.decode_entries([(keys.ROLE_CURRENT, encoded)]), [(keys.ROLE_CURRENT, self.pub_a)])
        for bad in ([("current", "***not base64***")], [("current",)], ["current"], [("current", 5)], [("current", encoded[:-2])]):
            with self.assertRaises(keys.KeyringError):
                keys.Keyring(keys.decode_entries(bad))


if __name__ == "__main__":
    unittest.main()
