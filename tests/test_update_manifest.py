"""`update/manifest.py` 시험(UPDATE 설계서 3-2·4절 U1–U8·U12, v1update U-1) — 서명 매니페스트의 읽기·서명 확인·규칙 검사.

지키는 것:
  1) 서명이 맞고 모든 칸이 규칙에 맞는 매니페스트는 받아들여진다(현재 키·예비 키 둘 다). 출하 키 목록(비어 있음)으로는 어떤 서명도 '모르는 키' 로 거절된다.
  2) **서명 확인 전에는 값을 믿지 않는다** — 칸이 틀렸고 서명도 틀린 것은 `UPDATE_SIGNATURE_INVALID` 이고(칸 검사는 서명 뒤), 서명이 맞고 칸이 틀린 것은 `UPDATE_MANIFEST_INVALID` 다. 서명은 접두어 + 바이트 그대로다(도메인 분리·바이트 하나·키 이름표·폐기).
  3) 엄격한 읽기: 크기·BOM·CRLF·끝의 줄바꿈·같은 키·모르는 키·빠진 키·깊이·소수·불리언·null·제어 문자·서명 파일 모양.
  4) 칸 규칙: 스키마·제품·채널·버전·태그·`seq`(= 발행 시각 숫자)·시각·유효 기간·최소 버전·`key_id`·`commit`·설치 도구·안내 글·파일 목록(이름 규칙·크기·해시·역할별 이름).
  5) 견주기: 만료(경계)·시계가 뒤로 감·낮은 판·같은 판(적용 직후의 같은 `seq` 도 '최신')·`seq` 는 **커야** 한다(같으면 거절)·최소 버전·설치 종류·휴대용은 확인만·복구 모드의 예외.
  6) 오류에는 매니페스트의 글이 실리지 않는다(카나리 글자를 심어 확인).
네트워크·실제 시크릿 없이 돈다(시험 키는 모두 시험 안의 임시 값).
"""
import base64
import copy
import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import update_support as us  # noqa: E402

from chanceblog_desktop.update import keys, manifest  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 12, 2, 0, 0, 0, tzinfo=UTC)
RING = keys.Keyring([(keys.ROLE_CURRENT, us.SeededTestCase.PUB_A), (keys.ROLE_SPARE, us.SeededTestCase.PUB_B)])
ID_A, ID_B, SEED_A, SEED_B = us.SeededTestCase.ID_A, us.SeededTestCase.ID_B, us.SeededTestCase.SEED_A, us.SeededTestCase.SEED_B
_CACHE = {}


def signed(seed=SEED_A, **changes):
    """(매니페스트 바이트, 서명 파일 바이트) — 같은 입력은 한 번만 서명한다."""
    changes.setdefault("key_id", ID_A if seed == SEED_A else ID_B)
    data = us.encode_manifest(us.manifest_dict(**changes))
    key = (seed, data)
    if key not in _CACHE:
        _CACHE[key] = us.signature_file(seed, data)
    return data, _CACHE[key]


def sign_bytes(data, seed=SEED_A):
    key = (seed, data)
    if key not in _CACHE:
        _CACHE[key] = us.signature_file(seed, data)
    return _CACHE[key]


def check(data, signature, **overrides):
    options = dict(keyring=RING, now=NOW, current_version="1.0.0", last_seq=0, last_seen=None, install_kind="velopack")
    options.update(overrides)
    return manifest.verify_manifest(data, signature, **options)


def reason_of(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except manifest.ManifestError as error:
        return error.code, error.reason
    return None


class AcceptTest(unittest.TestCase):
    def test_a_good_manifest_signed_with_the_current_or_the_spare_key_is_available(self):
        for seed, ident in ((SEED_A, ID_A), (SEED_B, ID_B)):
            data, signature = signed(seed, key_id=ident)
            verdict = check(data, signature)
            self.assertEqual((verdict.status, verdict.apply_possible), ("AVAILABLE", True))
            found = verdict.manifest
            self.assertEqual((found.version, found.tag, found.channel, found.key_id), ("1.0.1", "v1.0.1", "stable", ident))
            self.assertEqual((found.seq, found.min_version, found.installer_kind, found.pack_id), (20261201030000, "1.0.0", "velopack", "ChanceBlogDesktopApp"))
            self.assertEqual((found.issued, found.expires), (datetime(2026, 12, 1, 3, 0, 0, tzinfo=UTC), datetime(2027, 5, 30, 3, 0, 0, tzinfo=UTC)))
            self.assertEqual(found.digest, hashlib.sha256(data).hexdigest())
            self.assertEqual([(item.role, item.name, item.size) for item in found.files], [("setup", "ChanceBlogDesktop-1.0.1-Setup.exe", 46000000), ("package", "ChanceBlogDesktopApp-1.0.1-stable-full.nupkg", 41000000),
                                                                                          ("feed", "releases.stable.json", 800)])
            self.assertEqual(found.file("package").sha256, us.HASH_B)
            self.assertIsNone(found.file("portable"))
            self.assertEqual(found.total_bytes(), 46000000 + 41000000 + 800)
            self.assertEqual(found.summary, "글 목록이 더 빨리 열려요.")

    def test_the_shipped_empty_keyring_refuses_everything_as_an_unknown_key(self):
        data, signature = signed()
        self.assertEqual(reason_of(check, data, signature, keyring=keys.shipped_keyring()), ("UPDATE_SIGNATURE_INVALID", "unknown_key"))

    def test_a_manifest_in_a_different_key_order_is_accepted_because_nothing_is_rewritten(self):
        raw = json.dumps(us.manifest_dict(key_id=ID_A), ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"
        data = raw.encode("utf-8")
        self.assertEqual(check(data, sign_bytes(data)).status, "AVAILABLE")

    def test_a_manifest_at_exactly_the_size_limit_is_read_and_one_byte_more_is_not(self):
        base = us.encode_manifest(us.manifest_dict(key_id=ID_A))
        padded = base[:-1] + b" " * (manifest.MAX_MANIFEST_BYTES - len(base)) + b"\n"
        self.assertEqual(len(padded), manifest.MAX_MANIFEST_BYTES)
        self.assertEqual(check(padded, sign_bytes(padded)).status, "AVAILABLE")
        over = padded[:-1] + b" \n"
        self.assertEqual(reason_of(check, over, sign_bytes(over)), ("UPDATE_MANIFEST_INVALID", "size"))


class SignatureBeforeFieldsTest(unittest.TestCase):
    def test_wrong_fields_with_a_wrong_signature_report_the_signature_not_the_fields(self):
        data, signature = signed(schema=2, product="Other", version="not a version")
        broken = bytearray(base64.b64decode(signature.strip()))
        broken[5] ^= 1
        bad = base64.b64encode(bytes(broken)) + b"\n"
        self.assertEqual(reason_of(check, data, bad), ("UPDATE_SIGNATURE_INVALID", "bad_signature"))
        self.assertEqual(reason_of(check, data, signature), ("UPDATE_MANIFEST_INVALID", "schema"), "서명이 맞으면 그때서야 칸을 본다")

    def test_a_valid_signature_over_a_field_error_is_an_invalid_manifest(self):
        for changes, reason in ((dict(schema=2), "schema"), (dict(product="Other"), "product"), (dict(channel="beta"), "channel"), (dict(version="1.0"), "version"), (dict(tag="v1.0.2"), "tag"),
                                (dict(commit="X" * 40), "commit")):
            data, signature = signed(**changes)
            self.assertEqual(reason_of(check, data, signature), ("UPDATE_MANIFEST_INVALID", reason), changes)

    def test_the_signature_covers_the_prefix_and_the_exact_bytes(self):
        data, signature = signed()
        raw = base64.b64decode(signature.strip())
        self.assertEqual(raw, us.sign(SEED_A, manifest.SIGN_PREFIX + data))
        self.assertEqual(manifest.SIGN_PREFIX, b"ChanceBlogDesktop-update-manifest-v1\n")
        without_prefix = base64.b64encode(us.sign(SEED_A, data)) + b"\n"
        self.assertEqual(reason_of(check, data, without_prefix), ("UPDATE_SIGNATURE_INVALID", "bad_signature"), "접두어 없는 서명은 거절")
        other_domain = base64.b64encode(us.sign(SEED_A, b"ChanceBlogDesktop-update-manifest-v2\n" + data)) + b"\n"
        self.assertEqual(reason_of(check, data, other_domain), ("UPDATE_SIGNATURE_INVALID", "bad_signature"), "다른 도메인의 서명은 거절")
        self.assertEqual(reason_of(check, data, signature), None)

    def test_one_changed_byte_anywhere_in_the_manifest_breaks_the_signature(self):
        data, signature = signed()
        for index in (0, 1, 7, len(data) // 2, len(data) - 3, len(data) - 2):
            bad = bytearray(data)
            bad[index] = bad[index] + 1 if bad[index] < 126 else bad[index] - 1
            result = reason_of(check, bytes(bad), signature)
            self.assertIsNotNone(result, index)
            self.assertIn(result[0], ("UPDATE_SIGNATURE_INVALID", "UPDATE_MANIFEST_INVALID"), index)
        spaced = data.replace(b"{\n", b"{\n ", 1)
        self.assertEqual(reason_of(check, spaced, signature), ("UPDATE_SIGNATURE_INVALID", "bad_signature"), "공백 하나만 달라도 바이트가 달라 거절한다(다시 쓰기 없음)")

    def test_a_signature_by_another_key_or_with_a_wrong_key_id_is_refused(self):
        data = us.encode_manifest(us.manifest_dict(key_id=ID_A))
        self.assertEqual(reason_of(check, data, sign_bytes(data, SEED_B)), ("UPDATE_SIGNATURE_INVALID", "bad_signature"), "B 로 서명하고 key_id 는 A")
        stranger = us.seed_for("stranger")
        data = us.encode_manifest(us.manifest_dict(key_id=us.key_id_of(us.public_key(stranger))))
        self.assertEqual(reason_of(check, data, us.signature_file(stranger, data)), ("UPDATE_SIGNATURE_INVALID", "unknown_key"))

    def test_a_revoked_key_is_refused_even_with_a_valid_signature(self):
        data, signature = signed()
        revoked = keys.Keyring([(keys.ROLE_CURRENT, us.SeededTestCase.PUB_A), (keys.ROLE_SPARE, us.SeededTestCase.PUB_B)], revoked=(ID_A,))
        self.assertEqual(reason_of(check, data, signature, keyring=revoked), ("UPDATE_SIGNATURE_INVALID", "revoked_key"))
        data_b, signature_b = signed(SEED_B)
        self.assertIsNone(reason_of(check, data_b, signature_b, keyring=revoked), "예비 키는 폐기되지 않았다")

    def test_the_key_id_field_must_be_text_of_the_right_shape_before_any_lookup(self):
        for value in ("ABCDEF0123456789", "short", 12345, None, ["a"], "0123456789abcdeg"):
            data = us.encode_manifest(us.manifest_dict(key_id=value))
            result = reason_of(check, data, sign_bytes(data))
            self.assertIn(result, (("UPDATE_MANIFEST_INVALID", "key_id"), ("UPDATE_MANIFEST_INVALID", "value_type")), repr(value))


class SignatureFileTest(unittest.TestCase):
    def test_only_a_canonical_one_line_base64_of_64_bytes_with_one_lf_is_read(self):
        data, signature = signed()
        line = signature.strip()
        self.assertEqual(len(line), 88)
        for bad in (line, line + b"\r\n", line + b"\n\n", b" " + line + b"\n", line[:-1] + b"\n", line[:-3] + b"===" + b"\n", line.decode().replace("A", "-").encode() + b"\n" if b"A" in line else line + b"\n",
                    b"", b"\n", signature * 2, line[:44] + b"\n" + line[44:] + b"\n"):
            self.assertEqual(reason_of(check, data, bad), ("UPDATE_SIGNATURE_INVALID", "sig_shape") if bad != line + b"\n" else None, bad[:20])
        for bad in (None, "text", 5, [b"x"]):
            self.assertEqual(reason_of(check, data, bad), ("UPDATE_SIGNATURE_INVALID", "sig_type"))

    def test_a_non_canonical_base64_tail_is_refused(self):
        data, signature = signed()
        line = bytearray(signature.strip())
        original = line[85:86]
        for replacement in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/":
            if bytes([replacement]) == bytes(original):
                continue
            line[85] = replacement
            result = reason_of(check, data, bytes(line) + b"\n")
            self.assertIsNotNone(result)
            self.assertEqual(result[0], "UPDATE_SIGNATURE_INVALID")


class StructureTest(unittest.TestCase):
    def raw(self, text):
        data = text.encode("utf-8") if isinstance(text, str) else text
        return data, sign_bytes(data)

    def good_text(self, **changes):
        return us.encode_manifest(us.manifest_dict(key_id=ID_A, **changes)).decode("utf-8")

    def test_bom_crlf_and_the_final_newline_rules(self):
        good = self.good_text()
        for label, data, reason in (("BOM", b"\xef\xbb\xbf" + good.encode("utf-8"), "json_bom"), ("CRLF", good.replace("\n", "\r\n").encode("utf-8"), "line_ending"), ("한 줄바꿈 없음", good.rstrip("\n").encode("utf-8"), "final_newline"),
                                    ("두 줄바꿈", (good + "\n").encode("utf-8"), "final_newline"), ("빈 파일", b"", "size"), ("글이 아님", b"\n", "json_syntax"), ("UTF-8 아님", good.encode("utf-8")[:20] + b"\xff\xfe\n", "json_utf8")):
            with self.subTest(label=label):
                data, signature = data, sign_bytes(data)
                self.assertEqual(reason_of(check, data, signature), ("UPDATE_MANIFEST_INVALID", reason))

    def test_duplicate_keys_unknown_keys_and_missing_keys_are_refused_even_with_a_valid_signature(self):
        good = self.good_text()
        duplicate = good.replace('"channel": "stable",', '"channel": "stable",\n  "channel": "stable",', 1)
        self.assertEqual(reason_of(check, *self.raw(duplicate)), ("UPDATE_MANIFEST_INVALID", "json_duplicate_key"))
        data, signature = signed(extra="x")
        self.assertEqual(reason_of(check, data, signature), ("UPDATE_MANIFEST_INVALID", "keys"))
        data, signature = signed(min_version=...)
        self.assertEqual(reason_of(check, data, signature), ("UPDATE_MANIFEST_INVALID", "keys"))
        data, signature = signed(installer={"kind": "velopack", "pack_id": "ChanceBlogDesktopApp", "extra": 1})
        self.assertEqual(reason_of(check, data, signature), ("UPDATE_MANIFEST_INVALID", "installer"))
        data, signature = signed(notes={"summary": "ok", "html": "<b>x</b>"})
        self.assertEqual(reason_of(check, data, signature), ("UPDATE_MANIFEST_INVALID", "notes"))

    def test_nesting_deeper_than_four_is_refused_before_any_field_is_read(self):
        deep = [[[[["x"]]]]]
        data, signature = signed(extra=deep)
        self.assertEqual(reason_of(check, data, signature), ("UPDATE_MANIFEST_INVALID", "depth"), "깊이 검사가 모르는 키 검사보다 먼저다")
        ok_depth = [[["x"]]]
        data, signature = signed(extra=ok_depth)
        self.assertEqual(reason_of(check, data, signature), ("UPDATE_MANIFEST_INVALID", "keys"), "깊이 4 이하는 깊이 때문에 걸리지 않는다(모르는 키 때문에 걸린다)")
        self.assertEqual(reason_of(check, *signed(extra={"a": {"b": {"c": 1}}})), ("UPDATE_MANIFEST_INVALID", "keys"))
        self.assertEqual(manifest.MAX_DEPTH, 4)
        self.assertIsNone(reason_of(check, *signed()), "정상 매니페스트는 깊이 3")

    def test_only_integers_are_allowed_as_numbers_and_no_bool_or_null(self):
        good = self.good_text()
        for label, text in (("소수 seq", good.replace('"seq": 20261201030000', '"seq": 20261201030000.0')), ("지수 크기", good.replace('"size": 800', '"size": 8e2')),
                            ("불리언", good.replace('"schema": 1', '"schema": true')), ("null", good.replace('"min_version": "1.0.0"', '"min_version": null')),
                            ("NaN", good.replace('"schema": 1', '"schema": NaN')), ("큰 정수", good.replace('"size": 800', '"size": 123456789012345678901234567890'))):
            with self.subTest(label=label):
                result = reason_of(check, *self.raw(text))
                self.assertIsNotNone(result, label)
                self.assertEqual(result[0], "UPDATE_MANIFEST_INVALID")

    def test_control_characters_and_invisible_text_are_refused_in_keys_and_values(self):
        for label, changes in (("널 문자", dict(notes={"summary": "a" + chr(0) + "b"})), ("제어 문자", dict(notes={"summary": "a" + chr(7)})), ("탭", dict(notes={"summary": "a" + chr(9) + "b"})),
                               ("글자 방향 바꿈", dict(notes={"summary": "a" + chr(0x202E) + "b"})), ("0 폭 공백", dict(notes={"summary": "a" + chr(0x200B) + "b"})),
                               ("줄 구분자", dict(notes={"summary": "a" + chr(0x2028) + "b"})), ("DEL", dict(notes={"summary": "a" + chr(127)})), ("C1", dict(notes={"summary": "a" + chr(0x85)}))):
            with self.subTest(label=label):
                result = reason_of(check, *signed(**changes))
                self.assertEqual(result[0], "UPDATE_MANIFEST_INVALID")
        data, signature = signed(notes={"summary": "첫 줄\n둘째 줄"})
        self.assertEqual(check(data, signature).manifest.summary, "첫 줄\n둘째 줄", "줄바꿈 하나는 안내 글에서 허용한다")
        self.assertEqual(reason_of(check, *signed(**{"bad" + chr(1): "x"})), ("UPDATE_MANIFEST_INVALID", "key_text"))

    def test_the_top_level_must_be_an_object(self):
        for text in ("[]\n", '"x"\n', "1\n", "null\n", "true\n"):
            result = reason_of(check, *self.raw(text))
            self.assertEqual(result[0], "UPDATE_MANIFEST_INVALID", text)

    def test_the_parser_error_reason_never_contains_manifest_text(self):
        canary = "CANARY_" + "MANIFEST_" + "TEXT"
        for data in (("{" + '"' + canary + '"' + ": 1, " + '"' + canary + '"' + ": 2}\n").encode(), (canary + "\n").encode()):
            try:
                check(data, sign_bytes(data))
            except manifest.ManifestError as error:
                for shown in (str(error), error.detail, error.reason, error.log_line(), error.rendered().message, error.rendered().action):
                    self.assertNotIn(canary, shown)
            else:
                self.fail("거절돼야 한다")


class FieldRulesTest(unittest.TestCase):
    def invalid(self, **changes):
        return reason_of(check, *signed(**changes))

    def assert_invalid(self, reason, **changes):
        self.assertEqual(self.invalid(**changes), ("UPDATE_MANIFEST_INVALID", reason), changes)

    def test_schema_product_channel_version_tag(self):
        for value in (0, 2, "1", 1.0, True, None):
            self.assertIn(self.invalid(schema=value), (("UPDATE_MANIFEST_INVALID", "schema"), ("UPDATE_MANIFEST_INVALID", "value_type")), repr(value))
        self.assert_invalid("product", product="chanceblogdesktop")
        self.assert_invalid("product", product="ChanceBlogDesktop ")
        self.assert_invalid("channel", channel="rc")
        self.assert_invalid("channel", channel="beta")
        self.assert_invalid("channel", channel="STABLE")
        for bad in ("1.0", "v1.0.1", "01.0.1", "1.0.1-rc.1"):
            self.assertIn(self.invalid(version=bad, tag="v" + bad)[0], ("UPDATE_MANIFEST_INVALID",), bad)
        self.assert_invalid("version_channel", version="1.0.1-preview.1", tag="v1.0.1-preview.1")
        self.assert_invalid("version_channel", version="1.0.1+7", tag="v1.0.1+7")
        self.assert_invalid("tag", tag="1.0.1")
        self.assert_invalid("tag", tag="V1.0.1")
        self.assert_invalid("tag", tag="v1.0.1 ")
        self.assert_invalid("tag", tag="v1.0.2")

    def test_the_rc_channel_is_read_only_when_the_caller_allows_it_and_only_for_rc_shaped_versions(self):
        data, signature = signed(channel="rc", version="0.9.0-rc.1", tag="v0.9.0-rc.1", min_version="0.8.0")
        self.assertEqual(reason_of(check, data, signature), ("UPDATE_MANIFEST_INVALID", "channel"), "온라인 확인은 stable 만")
        self.assertEqual(check(data, signature, channels=manifest.CHANNELS_OFFLINE, current_version="0.8.0").manifest.version, "0.9.0-rc.1")
        for bad in ("0.9.0-rc.0", "0.9.0-rc.01", "0.9.0-rc", "0.9.0-rc.1.2", "0.9.0-beta.1", "0.9.0"):
            data, signature = signed(channel="rc", version=bad, tag="v" + bad, min_version="0.8.0")
            self.assertEqual(reason_of(check, data, signature, channels=manifest.CHANNELS_OFFLINE, current_version="0.8.0")[0], "UPDATE_MANIFEST_INVALID", bad)
        data, signature = signed(channel="stable", version="0.9.0-rc.1", tag="v0.9.0-rc.1", min_version="0.8.0")
        self.assertEqual(reason_of(check, data, signature, channels=manifest.CHANNELS_OFFLINE, current_version="0.8.0"), ("UPDATE_MANIFEST_INVALID", "version_channel"))

    def test_seq_issued_and_expires(self):
        for seq in (0, -1, 20261201030001, 2 ** 53, True, 1.5, "20261201030000", None):
            self.assertEqual(self.invalid(seq=seq)[0], "UPDATE_MANIFEST_INVALID", repr(seq))
        self.assert_invalid("seq", seq=20261201030001)
        for bad in ("2026-12-01 03:00:00", "2026-12-01T03:00:00", "2026-12-01T03:00:00+00:00", "2026-13-01T03:00:00Z", "2026-02-30T03:00:00Z", "2026-12-01T25:00:00Z", "2026-12-01T03:00:60Z",
                    "２０２６-12-01T03:00:00Z", "2026-12-01t03:00:00z", " 2026-12-01T03:00:00Z", "2026-12-01T03:00:00Z\n", 20261201, None):
            self.assertEqual(self.invalid(issued_utc=bad)[0], "UPDATE_MANIFEST_INVALID", repr(bad))
            self.assertEqual(self.invalid(expires_utc=bad)[0], "UPDATE_MANIFEST_INVALID", repr(bad))
        self.assert_invalid("time_span", expires_utc="2026-12-01T03:00:00Z")
        self.assert_invalid("time_span", expires_utc="2026-11-30T03:00:00Z")
        self.assert_invalid("time_span", expires_utc="2027-06-30T03:00:00Z")
        self.assertIsNone(reason_of(check, *signed(expires_utc="2027-06-19T03:00:00Z")), "200일 이하는 허용")
        self.assert_invalid("time_span", expires_utc="2027-06-20T03:00:01Z")

    def test_min_version_key_id_commit(self):
        for bad in ("1.0", "", "x", None, 1):
            self.assertEqual(self.invalid(min_version=bad)[0], "UPDATE_MANIFEST_INVALID", repr(bad))
        self.assert_invalid("min_version", min_version="1.0.2")
        self.assertEqual(manifest.read_and_verify(*signed(min_version="1.0.1"), keyring=RING).min_version, "1.0.1", "최소 버전이 자기 버전과 같아도 칸 규칙은 통과한다")
        for bad in ("0123456789ABCDEF01234567890123456789ABCD", "0123456789abcdef", "0123456789abcdef0123456789abcdef0123456", "0123456789abcdef0123456789abcdef012345678", None, 5):
            self.assertEqual(self.invalid(commit=bad)[0], "UPDATE_MANIFEST_INVALID", repr(bad))

    def test_installer_and_notes(self):
        for installer in ({"kind": "msi", "pack_id": "A"}, {"kind": "velopack", "pack_id": ""}, {"kind": "velopack", "pack_id": "../x"}, {"kind": "velopack", "pack_id": "a" * 65}, {"kind": 1, "pack_id": "A"},
                          {"kind": "velopack"}, "velopack", None, [], {"kind": "velopack", "pack_id": "한글"}):
            self.assertEqual(self.invalid(installer=installer)[0], "UPDATE_MANIFEST_INVALID", repr(installer))
        self.assertIsNone(reason_of(check, *signed(installer={"kind": "inno", "pack_id": "ChanceBlogDesktop"}), install_kind="inno"))
        for summary in ("", "x" * 501, "\n".join(["줄"] * 11), 5, None, ["a"]):
            self.assertEqual(self.invalid(notes={"summary": summary})[0], "UPDATE_MANIFEST_INVALID", repr(summary)[:30])
        self.assertIsNone(reason_of(check, *signed(notes={"summary": "x" * 500})))
        self.assertIsNone(reason_of(check, *signed(notes={"summary": "\n".join(["줄"] * 10)})))

    def entry(self, **changes):
        base = {"role": "setup", "name": "ChanceBlogDesktop-1.0.1-Setup.exe", "size": 1000, "sha256": us.HASH_A}
        base.update(changes)
        return base

    def test_the_file_list(self):
        self.assert_invalid("files_count", files=[])
        self.assert_invalid("files_count", files=[self.entry()] * 13)
        self.assert_invalid("files_count", files="x")
        self.assert_invalid("file_keys", files=[{**self.entry(), "url": "x"}])
        self.assert_invalid("file_keys", files=[{"role": "setup", "name": "a", "size": 1}])
        self.assert_invalid("file_keys", files=["setup"])
        self.assert_invalid("file_role", files=[self.entry(role="other")])
        self.assert_invalid("file_role", files=[self.entry(), self.entry(name="Other.exe")])
        self.assert_invalid("file_name", files=[self.entry(), self.entry(role="package", name="CHANCEBLOGDESKTOP-1.0.1-SETUP.EXE")])
        self.assertIsNone(reason_of(check, *signed(files=[self.entry()])))
        self.assertIsNone(reason_of(check, *signed(files=[self.entry()] + [self.entry(role=role, name=name) for role, name in (("package", "a.nupkg"), ("feed", "f.json"), ("portable", "ChanceBlogDesktop-1.0.1-win64.zip"))])))

    def test_file_names(self):
        bad_names = ("../x.exe", "..\\x.exe", "a/b.exe", "a\\b.exe", "a..b.exe", ".hidden.exe", "x.exe.", "x.exe ", "CON", "NUL.txt", "con.exe", "Lpt1.setup", "COM9.nupkg", "한글.exe", "a" * 101 + ".exe", "a b.exe", "a:b.exe",
                     "%2e%2e", "x\x00y", "", "x;y", "$HOME.exe", "-flag.exe", "_x.exe")
        for name in bad_names:
            with self.subTest(name=name):
                self.assertEqual(self.invalid(files=[self.entry(role="package", name=name)])[0], "UPDATE_MANIFEST_INVALID")
        for name in ("a.nupkg", "A-b_c.1.nupkg", "x" * 94 + ".nupkg", "COM10.nupkg", "console.nupkg"):
            self.assertIsNone(reason_of(check, *signed(files=[self.entry(role="package", name=name)])), name)
        self.assertTrue(manifest.valid_file_name("good-1.2.3.exe"))
        self.assertFalse(manifest.valid_file_name(5))
        self.assertTrue(manifest.reserved_name("nul.tar.gz"))
        self.assertFalse(manifest.reserved_name("nulx"))

    def test_file_sizes_hashes_and_role_specific_names(self):
        for size in (0, -1, manifest.MAX_FILE_BYTES + 1, True, 1.5, "100", None):
            self.assertEqual(self.invalid(files=[self.entry(size=size)])[0], "UPDATE_MANIFEST_INVALID", repr(size))
        self.assertIsNone(reason_of(check, *signed(files=[self.entry(size=1)])))
        self.assertIsNone(reason_of(check, *signed(files=[self.entry(size=manifest.MAX_FILE_BYTES)])))
        self.assert_invalid("files_total", files=[self.entry(size=manifest.MAX_FILE_BYTES), self.entry(role="package", name="a.nupkg", size=manifest.MAX_FILE_BYTES),
                                                  self.entry(role="feed", name="f.json", size=1)])
        self.assertIsNone(reason_of(check, *signed(files=[self.entry(size=manifest.MAX_FILE_BYTES), self.entry(role="package", name="a.nupkg", size=manifest.MAX_FILE_BYTES)])))
        for sha in ("A" * 64, "a" * 63, "a" * 65, "g" * 64, "", None, 5, " " + "a" * 63):
            self.assertEqual(self.invalid(files=[self.entry(sha256=sha)])[0], "UPDATE_MANIFEST_INVALID", repr(sha))
        self.assert_invalid("file_name_setup", files=[self.entry(name="ChanceBlogDesktop-1.0.2-Setup.exe")])
        self.assert_invalid("file_name_setup", files=[self.entry(name="Setup.exe")])
        self.assert_invalid("file_name_portable", files=[self.entry(role="portable", name="ChanceBlogDesktop-1.0.1.zip")])
        self.assert_invalid("file_name_package", files=[self.entry(role="package", name="a.exe")])
        self.assert_invalid("file_name_feed", files=[self.entry(role="feed", name="a.txt")])


class EvaluateTest(unittest.TestCase):
    def make(self, **changes):
        return manifest.read_and_verify(*signed(**changes), keyring=RING)

    def test_a_higher_version_is_available_a_lower_one_is_blocked_and_the_same_one_is_up_to_date(self):
        high = self.make()
        self.assertEqual(manifest.evaluate(high, now=NOW, current_version="1.0.0").status, "AVAILABLE")
        self.assertEqual(reason_of(manifest.evaluate, high, now=NOW, current_version="1.0.2"), ("UPDATE_DOWNGRADE_BLOCKED", "lower_version"))
        self.assertEqual(manifest.evaluate(high, now=NOW, current_version="1.0.1").status, "UP_TO_DATE")
        self.assertEqual(manifest.evaluate(high, now=NOW, current_version="1.0.1+3").status, "UP_TO_DATE", "빌드 표시만 달라도 같은 판")
        self.assertFalse(manifest.evaluate(high, now=NOW, current_version="1.0.1").apply_possible)
        self.assertEqual(reason_of(manifest.evaluate, high, now=NOW, current_version="2.0.0"), ("UPDATE_DOWNGRADE_BLOCKED", "lower_version"))

    def test_seq_must_be_greater_and_the_same_version_after_an_apply_is_up_to_date_not_a_downgrade(self):
        high = self.make()
        self.assertEqual(manifest.evaluate(high, now=NOW, current_version="1.0.0", last_seq=high.seq - 1).status, "AVAILABLE")
        for stored in (high.seq, high.seq + 1, high.seq * 2):
            self.assertEqual(reason_of(manifest.evaluate, high, now=NOW, current_version="1.0.0", last_seq=stored), ("UPDATE_DOWNGRADE_BLOCKED", "seq"), stored)
        self.assertEqual(manifest.evaluate(high, now=NOW, current_version="1.0.1", last_seq=high.seq).status, "UP_TO_DATE", "적용 직후 같은 매니페스트를 다시 받아도 '최신이에요'")
        self.assertEqual(manifest.evaluate(high, now=NOW, current_version="1.0.1", last_seq=high.seq + 5).status, "UP_TO_DATE")

    def test_expiry_is_checked_before_the_version_and_the_boundary_is_inclusive(self):
        high = self.make()
        self.assertEqual(manifest.evaluate(high, now=high.expires, current_version="1.0.0").status, "AVAILABLE", "만료 시각 정각까지는 유효")
        late = high.expires + timedelta(seconds=1)
        for current in ("1.0.0", "1.0.1", "2.0.0"):
            self.assertEqual(reason_of(manifest.evaluate, high, now=late, current_version=current), ("UPDATE_MANIFEST_EXPIRED", "expired"), current)

    def test_a_clock_far_behind_what_was_seen_before_is_not_trusted(self):
        high = self.make()
        seen = NOW + timedelta(days=3)
        self.assertEqual(reason_of(manifest.evaluate, high, now=NOW, current_version="1.0.0", last_seen=seen), ("UPDATE_MANIFEST_EXPIRED", "clock_behind"))
        self.assertEqual(manifest.evaluate(high, now=NOW, current_version="1.0.0", last_seen=NOW + timedelta(days=1)).status, "AVAILABLE")
        self.assertEqual(manifest.evaluate(high, now=NOW, current_version="1.0.0", last_seen=NOW + manifest.CLOCK_BEHIND_LIMIT).status, "AVAILABLE", "정확히 한계는 통과")
        self.assertEqual(reason_of(manifest.evaluate, high, now=NOW, current_version="1.0.0", last_seen=NOW + manifest.CLOCK_BEHIND_LIMIT + timedelta(seconds=1)), ("UPDATE_MANIFEST_EXPIRED", "clock_behind"))
        self.assertEqual(manifest.evaluate(high, now=NOW, current_version="1.0.0", last_seen=NOW - timedelta(days=30)).status, "AVAILABLE")

    def test_the_minimum_version_blocks_a_direct_update(self):
        high = self.make(min_version="1.0.1")
        self.assertEqual(reason_of(manifest.evaluate, high, now=NOW, current_version="1.0.0"), ("UPDATE_NEEDS_MANUAL_INSTALL", "min_version"))
        ok = self.make(min_version="1.0.0")
        self.assertEqual(manifest.evaluate(ok, now=NOW, current_version="1.0.0").status, "AVAILABLE")
        self.assertEqual(reason_of(manifest.evaluate, self.make(min_version="0.9.5", version="1.0.1"), now=NOW, current_version="0.9.0"), ("UPDATE_NEEDS_MANUAL_INSTALL", "min_version"))

    def test_install_kinds(self):
        high = self.make()
        self.assertEqual(reason_of(manifest.evaluate, high, now=NOW, current_version="1.0.0", install_kind="inno"), ("UPDATE_NEEDS_MANUAL_INSTALL", "installer_kind"))
        self.assertEqual(manifest.evaluate(high, now=NOW, current_version="1.0.0", install_kind="velopack").apply_possible, True)
        for kind in ("portable", "source", ""):
            verdict = manifest.evaluate(high, now=NOW, current_version="1.0.0", install_kind=kind)
            self.assertEqual((verdict.status, verdict.apply_possible), ("AVAILABLE", False), kind)

    def test_recovery_allows_exactly_the_previous_version_and_nothing_else(self):
        previous = self.make(version="1.0.0", tag="v1.0.0", seq=20260601030000, issued_utc="2026-06-01T03:00:00Z", expires_utc="2026-11-28T03:00:00Z", min_version="0.9.0")
        self.assertEqual(reason_of(manifest.evaluate, previous, now=NOW, current_version="1.0.1"), ("UPDATE_MANIFEST_EXPIRED", "expired"), "대조 — 보통 길에서는 만료된 낮은 판")
        verdict = manifest.evaluate(previous, now=NOW, current_version="1.0.1", last_seq=20261201030000, install_kind="velopack", recovery_target="1.0.0")
        self.assertEqual((verdict.status, verdict.apply_possible), ("AVAILABLE", True))
        for target in ("1.0.2", "0.9.9", "1.0.0-rc.1", "2.0.0"):
            self.assertEqual(reason_of(manifest.evaluate, previous, now=NOW, current_version="1.0.1", recovery_target=target), ("UPDATE_DOWNGRADE_BLOCKED", "recovery_target"), target)
        for bad in ("x", "1.0", "v1.0.0"):
            self.assertEqual(reason_of(manifest.evaluate, previous, now=NOW, current_version="1.0.1", recovery_target=bad), ("UPDATE_DOWNGRADE_BLOCKED", "recovery_target"), bad)
        self.assertEqual(reason_of(manifest.evaluate, previous, now=NOW, current_version="1.0.1", install_kind="inno", recovery_target="1.0.0"), ("UPDATE_NEEDS_MANUAL_INSTALL", "installer_kind"))
        self.assertEqual(manifest.evaluate(previous, now=NOW, current_version="1.0.1", recovery_target="1.0.0+9").status, "AVAILABLE", "빌드 표시는 같은 판")

    def test_recovery_still_needs_a_valid_signature(self):
        data, signature = signed(version="1.0.0", tag="v1.0.0", seq=20260601030000, issued_utc="2026-06-01T03:00:00Z", expires_utc="2026-11-28T03:00:00Z", min_version="0.9.0")
        broken = bytearray(base64.b64decode(signature.strip()))
        broken[0] ^= 1
        self.assertEqual(reason_of(check, data, base64.b64encode(bytes(broken)) + b"\n", current_version="1.0.1", recovery_target="1.0.0"), ("UPDATE_SIGNATURE_INVALID", "bad_signature"))
        self.assertEqual(check(data, signature, current_version="1.0.1", recovery_target="1.0.0").status, "AVAILABLE")

    def test_bad_arguments_are_program_errors_or_check_failures_not_silent_passes(self):
        high = self.make()
        with self.assertRaises(ValueError):
            manifest.evaluate(high, now=datetime(2026, 12, 2), current_version="1.0.0")
        with self.assertRaises(ValueError):
            manifest.evaluate(high, now=NOW, current_version="1.0.0", last_seen=datetime(2026, 12, 2))
        for bad in ("", "x", None, "1.0"):
            self.assertEqual(reason_of(manifest.evaluate, high, now=NOW, current_version=bad), ("UPDATE_CHECK_FAILED", "current_version"), repr(bad))


class TimeParseTest(unittest.TestCase):
    def test_only_the_exact_utc_form_is_read(self):
        self.assertEqual(manifest.parse_time("2026-12-01T03:04:05Z"), datetime(2026, 12, 1, 3, 4, 5, tzinfo=UTC))
        for bad in ("2026-12-01T03:04:05", "2026-12-01 03:04:05Z", "2026-12-1T03:04:05Z", "٢٠٢٦-12-01T03:04:05Z", "2026-02-29T00:00:00Z", None, 5, b"2026-12-01T03:04:05Z"):
            self.assertIsNone(manifest.parse_time(bad), repr(bad))
        self.assertEqual(manifest.parse_time("2028-02-29T23:59:59Z"), datetime(2028, 2, 29, 23, 59, 59, tzinfo=UTC), "윤일")


class ErrorShapeTest(unittest.TestCase):
    def test_every_error_is_an_app_error_with_a_catalog_code_and_a_fixed_reason(self):
        from chanceblog_desktop.errors import CATALOG
        for code in (manifest.CODE_INVALID, manifest.CODE_SIGNATURE, manifest.CODE_EXPIRED, manifest.CODE_DOWNGRADE, manifest.CODE_MANUAL, manifest.CODE_CHECK):
            self.assertIn(code, CATALOG, code)
        error = manifest.ManifestError(manifest.CODE_INVALID, "size")
        self.assertEqual((error.code, error.reason, error.detail), ("UPDATE_MANIFEST_INVALID", "size", "manifest:size"))
        self.assertEqual(error.rendered().retry_kind, "auto")

    def test_the_module_only_imports_pure_things(self):
        import ast
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "update" / "manifest.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(("." * node.level) + (node.module or ""))
        self.assertEqual(sorted(names), [".", "..errors", "..net", ".keys", "__future__", "base64", "binascii", "dataclasses", "datetime", "hashlib", "re", "unicodedata"])
        text = (ROOT / "src" / "chanceblog_desktop" / "update" / "manifest.py").read_text(encoding="utf-8")
        for word in ("open(", "socket", "subprocess", "datetime.now", "utcnow", "time.time", "os.environ"):
            self.assertNotIn(word, text, word)


if __name__ == "__main__":
    unittest.main()
