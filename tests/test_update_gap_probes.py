"""업데이트 갈래 시험 틈 막기(재작업 1, v1update 11) — 독립 검증 안전 S 의 R9 와 시험 Q 의 R1–R6 이 '변이를 일부러 넣어도 시험이 전부 통과한다' 고 짚은 곳을 시험으로 막는다.
제품 코드는 바꾸지 않았다(맞는 코드의 약속을 시험이 지키게 할 뿐이다). 각 묶음 옆에 막으려는 변이의 번호를 적었다(S 보고서 12절 B·Q 보고서 부록 A).

묶음:
  1) 서명 검증기의 마지막 판정식(S R9 가, Q R2 — 변이 N01·N02·E13): 서명 (R, S) 는 참이고 변조한 (R, L−S) 는 거짓이다 — y 하나만 견주면 L−S 도 참이 된다. `_equal`·`_is_identity` 를 직접 시험한다.
  2) 온라인 확인의 기본 채널(S R9 나 — 변이 N92): 가짜 서버가 최신 길에 후보(rc) 매니페스트를 내줘도 `UPDATE_MANIFEST_INVALID`(channel) 로 거절한다.
  3) 안내 글이 거절하는 글자 범주 여섯(S R9 다·R7 — 변이 N22): Cc·Cf·Cs·Co·Zl·Zp 를 한 글자씩.
  4) 파일 이름·패키지 이름 규칙(Q R1 — 변이 A18·A24·A25·A26·A27): 각 규칙을 **그 규칙만** 어기는 값으로 겨냥하고 이유 이름표까지 견준다(예전 시험은 앞선 다른 규칙에 먼저 걸려 엉뚱한 이유로 통과했다).
  5) 한도 상수를 손으로 적은 값으로(Q R3 — 변이 A07·A09·A10·S03·S06·N04): 만료 200일·시계 한계 2일·매니페스트 64 KiB·상태 파일 64 KiB·`boot_attempts` 1000·서명 파일 4096바이트.
  6) 실제 접속 클라이언트 공장(Q R4 — 변이 W01·W02·W03): `service/wiring._update_factory` 본문을 가짜 소켓 위에서 돌려 본다(접속 0).
  7) `report_health` 의 조용한 삼킴과 삼키는 자리의 허용 목록(Q R5 — 변이 Z15): 표식을 못 지워도 `HEALTHY` 를 돌려주고 표식이 남으며, 목록 밖 오류는 삼키지 않는다. `update/` 와 서비스의 삼키는 자리는 목록으로 못박는다.
  8) `UPDATE_TEST_OPENSSL_PAIRS` 해석(Q R6): 빈 값·글자·0 이하는 기본 열두 쌍, 200 을 넘으면 200.
  9) 문서의 사실(S R6·R7): D-803 의 정정·RELEASE 의 거절 범주가 코드와 같음·SECURITY 켜기 전 필수 조건의 다섯 줄.
접속은 한 번도 없다(가짜 소켓·임시 폴더). 가짜 키는 `update_support` 가 시험 안에서 만든 임시 값이고, 글자 표본은 코드 번호로 조립한다(소스에 이스케이프나 비밀 모양 글이 없다).
"""
import ast
import hashlib
import inspect
import os
import re
import string
import sys
import tempfile
import unicodedata
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import test_update_flow as tf  # noqa: E402
import test_update_manifest as tm  # noqa: E402
import test_update_state as ts  # noqa: E402
import update_flow_support as fs  # noqa: E402
import update_support as us  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.net import client as net_client  # noqa: E402
from chanceblog_desktop.service import external, update_flow, wiring  # noqa: E402
from chanceblog_desktop.update import ed25519, health, manifest, source, state  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"
DOCS = ROOT / "docs"
BACKSLASH = chr(92)                                   # 소스에 이스케이프 글자를 직접 적지 않으려고 조립한다
ZERO_DIGEST = "0" * 64


def fields_reason(**changes):
    """서명 확인 뒤의 칸 검사만 돌려 (오류 코드, 이유) 또는 None — 서명을 만들지 않아 가볍다. 서명까지 가는 길은 `tm.signed`·`tm.check` 로 따로 한 번씩 견준다."""
    try:
        manifest.validate_fields(us.manifest_dict(**changes), ZERO_DIGEST)
    except manifest.ManifestError as error:
        return error.code, error.reason
    return None


def parse(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))


# ======================================================================================================================================================
# 1) 서명 검증기의 마지막 판정식 — _equal 과 _is_identity, 그리고 S → L−S 변조
# ======================================================================================================================================================
def _affine(point):
    inverse = pow(point[2], -1, ed25519.P)
    return point[0] * inverse % ed25519.P, point[1] * inverse % ed25519.P


def _extended(x, y, z=1):
    """아핀 (x, y) 를 비율 z 로 늘린 확장 좌표 — 같은 점의 다른 표현이다."""
    return (x * z % ed25519.P, y * z % ed25519.P, z % ed25519.P, x * y * z % ed25519.P)


class PointComparisonTest(unittest.TestCase):
    def test_two_points_sharing_only_one_coordinate_are_not_the_same_point(self):
        base = ed25519._BASE
        x, y = _affine(base)
        same_y_other_x = _extended((-x) % ed25519.P, y)
        same_x_other_y = _extended(x, (-y) % ed25519.P)
        self.assertEqual(_affine(same_y_other_x)[1], y, "빈 실험이 아니다 — y 만 같은 점")
        self.assertNotEqual(_affine(same_y_other_x)[0], x)
        self.assertEqual(_affine(same_x_other_y)[0], x, "x 만 같은 점")
        self.assertNotEqual(_affine(same_x_other_y)[1], y)
        for other in (same_y_other_x, same_x_other_y):
            self.assertFalse(ed25519._equal(base, other))
            self.assertFalse(ed25519._equal(other, base))

    def test_the_same_point_in_another_projective_form_is_equal_and_other_points_are_not(self):
        base = ed25519._BASE
        x, y = _affine(base)
        scaled = _extended(x, y, 7)
        self.assertNotEqual(scaled[:3], base[:3], "표현이 정말 다르다")
        self.assertTrue(ed25519._equal(base, base))
        self.assertTrue(ed25519._equal(base, scaled))
        self.assertTrue(ed25519._equal(scaled, base))
        self.assertFalse(ed25519._equal(base, ed25519._add(base, base)), "두 배 한 점은 다른 점")
        self.assertFalse(ed25519._equal(base, ed25519._IDENTITY))
        self.assertTrue(ed25519._equal(ed25519._IDENTITY, _extended(0, 1, 9)))

    def test_the_identity_test_needs_x_zero_and_y_equal_to_z_together(self):
        modulus = ed25519.P
        self.assertTrue(ed25519._is_identity(ed25519._IDENTITY))
        self.assertTrue(ed25519._is_identity((0, 5, 5, 0)))
        self.assertTrue(ed25519._is_identity((modulus, 3 * modulus + 4, 4, 0)), "법 p 로 같은 값")
        self.assertFalse(ed25519._is_identity((0, modulus - 1, 1, 0)), "x 는 0 이지만 위수 2 인 점이다")
        self.assertFalse(ed25519._is_identity((3, 1, 1, 3)), "y 와 z 는 같지만 x 가 0 이 아니다")
        self.assertFalse(ed25519._is_identity(ed25519._BASE))


class MirroredScalarTest(unittest.TestCase):
    CASES = (("mirror-a", b"first message"), ("mirror-b", b""), ("mirror-c", bytes(range(200))), ("mirror-d", b"x" * 1023))

    def test_the_signature_with_s_replaced_by_l_minus_s_is_refused_and_only_the_original_is_accepted(self):
        for label, message in self.CASES:
            with self.subTest(label=label):
                seed = us.seed_for(label)
                pub = us.public_key(seed)
                signature = us.sign(seed, message)
                s = int.from_bytes(signature[32:], "little")
                mirrored = signature[:32] + int.to_bytes(ed25519.L - s, 32, "little")
                self.assertTrue(0 < s < ed25519.L)
                self.assertTrue(0 < ed25519.L - s < ed25519.L, "바꾼 S 도 범위 안이라 'S 가 L 이상' 검사 때문에 거절되는 것이 아니다")
                self.assertNotEqual(mirrored, signature)
                self.assertTrue(ed25519.verify(pub, message, signature))
                self.assertFalse(ed25519.verify(pub, message, mirrored))

    def test_the_mirrored_scalar_gives_the_mirror_point_so_a_one_coordinate_comparison_would_accept_it(self):
        """빈 실험이 아님을 보인다 — [8][L−S]B 는 [8][S]B 의 거울점(y 는 같고 x 만 부호가 반대)이다. 그래서 y 하나만 견주는 검증기는 이 변조를 참으로 본다."""
        seed, message = us.seed_for("mirror-a"), b"first message"
        pub = us.public_key(seed)
        signature = us.sign(seed, message)
        s = int.from_bytes(signature[32:], "little")
        r_point, a_point = us.decode(signature[:32]), us.decode(pub)
        k = int.from_bytes(hashlib.sha512(signature[:32] + pub + message).digest(), "little") % us.L
        right = us.point_mul(8, us.point_add(r_point, us.point_mul(k, a_point)))
        left = us.point_mul(8, us.point_mul(s, us.BASE))
        mirror = us.point_mul(8, us.point_mul(us.L - s, us.BASE))
        self.assertEqual(left, right, "원래 서명은 식이 맞는다")
        self.assertEqual(mirror[1], right[1], "거울점은 y 가 같다")
        self.assertEqual(mirror[0], (-right[0]) % us.P)
        self.assertNotEqual(mirror[0], right[0], "x 만 다르다")


# ======================================================================================================================================================
# 2) 온라인 확인의 기본 채널은 stable 뿐이다
# ======================================================================================================================================================
class OnlineChannelTest(tf.FlowCase):
    def setUp(self):
        super().setUp()
        self.candidate = fs.Release("1.0.1-rc.1", channel="rc")
        self.candidate.install(self.server)                       # 최신 릴리스 길이 후보를 가리키게 한다(정식 1.0.1 은 가려진다)

    def test_a_candidate_served_on_the_latest_route_is_refused_by_the_online_check_with_the_channel_reason(self):
        with self.assertRaises(AppError) as caught:
            self.check()
        self.assertEqual((caught.exception.code, caught.exception.detail), ("UPDATE_MANIFEST_INVALID", "manifest:channel"))
        recorded = self.state()
        self.assertEqual((recorded.last_check.result, recorded.last_check.code, recorded.last_seq), ("CHECK_FAILED", "UPDATE_MANIFEST_INVALID", 0))

    def test_the_same_candidate_passes_every_other_rule_when_the_caller_opts_in_to_the_offline_channels(self):
        """대조(빈 실험이 아님) — 후보 매니페스트 자체는 서명·칸·버전 규칙을 모두 지킨다. 거절은 채널 때문뿐이다."""
        result = self.check(channels=manifest.CHANNELS_OFFLINE)
        self.assertEqual((result.status, result.manifest.channel, result.manifest.version), ("AVAILABLE", "rc", "1.0.1-rc.1"))

    def test_the_session_check_refuses_the_candidate_too_and_never_opts_in_to_the_candidate_channel(self):
        session = update_flow.UpdateSession(self.ctx, install_kind="inno", current_version="1.0.0", keyring=fs.RING)
        with self.assertRaises(AppError):
            session.check()
        self.assertEqual((session.state, session.error.code), ("CHECK_FAILED", "UPDATE_MANIFEST_INVALID"))
        tree = parse(SRC / "service" / "update_flow.py")
        klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "UpdateSession")
        method = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == "check")
        calls = [node for node in ast.walk(method) if isinstance(node, ast.Call) and ast.unparse(node.func) == "check_for_update"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(sorted(keyword.arg for keyword in calls[0].keywords), ["current_version", "install_kind", "keyring"], "세션의 확인은 채널을 넘기지 않는다 — 기본값이 stable 이어야 한다")

    def test_the_default_channels_of_every_online_entry_are_stable_only(self):
        for function in (update_flow.check_for_update, manifest.verify_manifest, manifest.read_and_verify):
            with self.subTest(function=function.__name__):
                self.assertEqual(inspect.signature(function).parameters["channels"].default, ("stable",))
        self.assertEqual(manifest.CHANNELS_ONLINE, ("stable",))
        self.assertEqual(manifest.CHANNELS_OFFLINE, ("stable", "rc"))


# ======================================================================================================================================================
# 3) 안내 글이 거절하는 글자 범주 여섯
# ======================================================================================================================================================
class HiddenCharacterTest(unittest.TestCase):
    ONE_PER_CATEGORY = (("Cc", chr(0x07)), ("Cf", chr(0x200D)), ("Cs", chr(0xD800)), ("Co", chr(0xE000)), ("Zl", chr(0x2028)), ("Zp", chr(0x2029)))
    MORE = (("Cf", chr(0x200B)), ("Cf", chr(0x202E)), ("Co", chr(0xF0000)), ("Cc", chr(0x85)))
    ORDINARY = ("가", chr(0xE9), chr(0x1F600), chr(0xA0), chr(0x3000), chr(0x301), "7", "-")        # 한글·악센트·그림 문자·줄 안 바뀌는 공백·전각 공백·결합 글자·숫자·붙임표

    def test_the_refused_categories_are_exactly_these_six(self):
        self.assertEqual(manifest._HIDDEN_CATEGORIES, frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"}))

    def test_each_category_has_a_character_that_is_hidden_text_and_the_samples_really_have_those_categories(self):
        for category, char in self.ONE_PER_CATEGORY + self.MORE:
            with self.subTest(category=category, code=hex(ord(char))):
                self.assertEqual(unicodedata.category(char), category, "표본의 범주(이 파이썬의 유니코드 판)")
                self.assertTrue(manifest._unsafe_text(char))
                self.assertTrue(manifest._unsafe_text("a" + char + "b"))

    def test_a_signed_manifest_with_one_such_character_in_the_notes_or_in_a_key_is_refused(self):
        for category, char in self.ONE_PER_CATEGORY + self.MORE:
            if category == "Cs":
                continue                                       # 짝 없는 서러게이트는 파일에 글자로 쓸 수 없다 — 아래 시험이 이스케이프로 적는다
            with self.subTest(category=category, code=hex(ord(char))):
                self.assertEqual(tm.reason_of(tm.check, *tm.signed(notes={"summary": "a" + char + "b"})), ("UPDATE_MANIFEST_INVALID", "control_char"))
                self.assertEqual(tm.reason_of(tm.check, *tm.signed(**{"bad" + char: "x"})), ("UPDATE_MANIFEST_INVALID", "key_text"))

    def test_a_lone_surrogate_written_as_an_escape_is_refused_before_or_by_the_hidden_text_rule(self):
        text = us.encode_manifest(us.manifest_dict(key_id=tm.ID_A, notes={"summary": "aXb"})).decode("utf-8")
        marked = text.replace('"aXb"', '"a' + BACKSLASH + 'ud800b"')
        self.assertNotEqual(marked, text)
        data = marked.encode("utf-8")
        self.assertIn(tm.reason_of(tm.check, data, tm.sign_bytes(data)), (("UPDATE_MANIFEST_INVALID", "json_surrogate"), ("UPDATE_MANIFEST_INVALID", "control_char")))

    def test_ordinary_letters_spaces_and_pictures_are_not_refused(self):
        """대조 — 거절이 글자 하나하나에 맞춰져 있다(범주를 넓게 잡은 변이는 여기서 걸린다)."""
        for char in self.ORDINARY:
            with self.subTest(code=hex(ord(char))):
                self.assertFalse(manifest._unsafe_text("a" + char + "b"))
                summary = "안내 " + char + " 끝"
                self.assertEqual(tm.check(*tm.signed(notes={"summary": summary})).manifest.summary, summary)

    def test_an_emoji_sequence_joined_with_the_zero_width_joiner_is_refused_so_the_signing_tool_must_check_first(self):
        """RELEASE 가 경고하는 릴리스 사고의 모양 — 안내 글에 이모지를 ZWJ 로 이은 글(가족 그림 문자)을 넣어 서명하면 앱은 그 매니페스트를 거절한다."""
        family = chr(0x1F468) + chr(0x200D) + chr(0x1F469) + chr(0x200D) + chr(0x1F467)
        self.assertTrue(manifest._unsafe_text(family))
        self.assertEqual(tm.reason_of(tm.check, *tm.signed(notes={"summary": "새 기능 " + family})), ("UPDATE_MANIFEST_INVALID", "control_char"))
        self.assertFalse(manifest._unsafe_text(chr(0x1F468) + chr(0x1F469) + chr(0x1F467)), "대조 — 이음 글자 없이 늘어놓은 그림 문자는 괜찮다")

    def test_one_newline_is_allowed_in_the_notes_but_not_in_a_key(self):
        self.assertFalse(manifest._unsafe_text("a" + chr(10) + "b", allow_newline=True))
        self.assertTrue(manifest._unsafe_text("a" + chr(10) + "b"))
        self.assertEqual(tm.reason_of(tm.check, *tm.signed(**{"bad" + chr(10): "x"})), ("UPDATE_MANIFEST_INVALID", "key_text"))


# ======================================================================================================================================================
# 4) 파일 이름·패키지 이름 규칙 — 각 규칙을 그 규칙만 어기는 값으로
# ======================================================================================================================================================
LETTERS_DIGITS = string.ascii_letters + string.digits
RESERVED_WORDS = frozenset(["CON", "PRN", "AUX", "NUL"] + [f"COM{number}" for number in range(1, 10)] + [f"LPT{number}" for number in range(1, 10)])
NAME_RULES = {                                            # 앱의 코드와 따로 쓴 규칙 여섯(손으로 쓴 독립 구현) — 값이 정확히 한 규칙만 어기는지 먼저 확인하는 데 쓴다
    "first": lambda name: name[:1] != "" and name[0] in LETTERS_DIGITS,
    "charset": lambda name: all(char in LETTERS_DIGITS + "._-" for char in name),
    "length": lambda name: len(name) <= 100,
    "double_dot": lambda name: ".." not in name,
    "end_dot": lambda name: not name.endswith("."),
    "reserved": lambda name: name.split(".", 1)[0].upper() not in RESERVED_WORDS,
}
BAD_NAMES = {                                             # 모두 .nupkg 로 끝난다 — 역할 접미사 규칙이 대신 걸러 주지 못하고 이름 규칙만이 거절할 수 있다
    "first": ("-flag.nupkg", "_x.nupkg", ".hidden.nupkg", "-.nupkg"),
    "charset": ("a b.nupkg", "a:b.nupkg", "a/b.nupkg", "a" + BACKSLASH + "b.nupkg", "a%2e.nupkg", "a;b.nupkg", "a$b.nupkg", "a" + chr(9) + "b.nupkg", "a" + chr(10) + "b.nupkg", "a" + chr(0) + "b.nupkg",
                "a" + chr(0xE9) + ".nupkg", "a" + chr(0xFF41) + ".nupkg", "a한글.nupkg"),
    "length": ("a" * 95 + ".nupkg", "a" * 200 + ".nupkg"),
    "double_dot": ("a..b.nupkg", "a-..-b.nupkg", "x...nupkg"),
    "reserved": ("CON.nupkg", "con.nupkg", "NUL.nupkg", "aux.nupkg", "PRN.nupkg", "COM1.nupkg", "com9.nupkg", "LPT1.nupkg", "Lpt9.nupkg"),
}
DIRECT_ONLY = {                                           # 끝이 .nupkg 일 수 없는 값 — 역할 접미사에는 닿지 못하므로 `valid_file_name` 을 직접 부른다
    "end_dot": ("x.nupkg.", "a.", "a.b."),
    "first": ("",),
}
OK_NAMES = ("a.nupkg", "A-b_c.1.nupkg", "a" * 94 + ".nupkg", "COM10.nupkg", "console.nupkg", "a.b.c.nupkg", "9.nupkg", "x-.nupkg", "LPT0.nupkg", "CONX.nupkg", "NUL-x.nupkg")


def package_entry(name):
    return {"role": "package", "name": name, "size": 1000, "sha256": us.HASH_A}


class FileNameRulesTest(unittest.TestCase):
    def failing_rules(self, name):
        return [rule for rule, holds in NAME_RULES.items() if not holds(name)]

    def test_every_bad_name_breaks_exactly_the_one_rule_it_is_filed_under_and_every_good_name_breaks_none(self):
        """시험 값 자체의 점검 — 나쁜 값이 앞선 다른 규칙에 먼저 걸려 엉뚱한 이유로 통과하는 일이 없다."""
        for table in (BAD_NAMES, DIRECT_ONLY):
            for rule, names in table.items():
                for name in names:
                    with self.subTest(rule=rule, name=name):
                        self.assertEqual(self.failing_rules(name), [rule])
        for name in OK_NAMES:
            with self.subTest(good=name):
                self.assertEqual(self.failing_rules(name), [])

    def test_the_apps_name_rule_agrees_with_the_hand_written_rules_on_every_listed_name(self):
        for table in (BAD_NAMES, DIRECT_ONLY):
            for rule, names in table.items():
                for name in names:
                    with self.subTest(rule=rule, name=name):
                        self.assertFalse(manifest.valid_file_name(name))
        for name in OK_NAMES:
            with self.subTest(good=name):
                self.assertTrue(manifest.valid_file_name(name))
        self.assertFalse(manifest.valid_file_name(None))
        self.assertFalse(manifest.valid_file_name(5))

    def test_a_package_with_such_a_name_is_refused_by_the_name_rule_itself_and_not_by_a_later_rule(self):
        for rule, names in BAD_NAMES.items():
            for name in names:
                with self.subTest(rule=rule, name=name):
                    self.assertEqual(fields_reason(files=[package_entry(name)]), ("UPDATE_MANIFEST_INVALID", "file_name"))
        for name in OK_NAMES:
            with self.subTest(good=name):
                self.assertIsNone(fields_reason(files=[package_entry(name)]))

    def test_the_same_refusals_hold_on_the_signed_path_for_one_name_per_rule(self):
        for rule, name in (("first", "-flag.nupkg"), ("charset", "a b.nupkg"), ("length", "a" * 95 + ".nupkg"), ("double_dot", "a..b.nupkg"), ("reserved", "CON.nupkg")):
            with self.subTest(rule=rule):
                self.assertEqual(tm.reason_of(tm.check, *tm.signed(files=[package_entry(name)])), ("UPDATE_MANIFEST_INVALID", "file_name"))
        self.assertIsNone(tm.reason_of(tm.check, *tm.signed(files=[package_entry("a" * 94 + ".nupkg")])), "100글자는 허용")

    def test_a_name_that_differs_only_by_case_from_an_earlier_one_is_refused(self):
        first = package_entry("a.nupkg")
        second = {"role": "feed", "name": "A.NUPKG", "size": 10, "sha256": us.HASH_B}
        self.assertEqual(fields_reason(files=[first, second]), ("UPDATE_MANIFEST_INVALID", "file_name"))


PACK_RULES = {
    "first": lambda pack_id: pack_id[:1] != "" and pack_id[0] in LETTERS_DIGITS,
    "charset": lambda pack_id: all(char in LETTERS_DIGITS + "._-" for char in pack_id),
    "length": lambda pack_id: len(pack_id) <= 64,
}
BAD_PACK_IDS = {
    "first": ("-rf", "_x", ".x", ""),
    "charset": ("a/b", "A/../x", "a" + BACKSLASH + "b", "a b", "a:b", "a*b", "a%b", "a;b", "a" + chr(10), "a" + chr(0xE9), "a" + chr(0xFF41)),
    "length": ("a" * 65, "a" * 300),
}
OK_PACK_IDS = ("a", "A", "9", "ChanceBlogDesktopApp", "a" * 64, "A.b_c-d", "x-1.2")


def installer(pack_id):
    return {"kind": "velopack", "pack_id": pack_id}


class PackIdRulesTest(unittest.TestCase):
    def test_every_bad_pack_id_breaks_exactly_the_one_rule_it_is_filed_under_and_every_good_one_breaks_none(self):
        for rule, values in BAD_PACK_IDS.items():
            for value in values:
                with self.subTest(rule=rule, value=value):
                    self.assertEqual([name for name, holds in PACK_RULES.items() if not holds(value)], [rule])
        for value in OK_PACK_IDS:
            with self.subTest(good=value):
                self.assertEqual([name for name, holds in PACK_RULES.items() if not holds(value)], [])

    def test_a_package_id_that_breaks_one_rule_is_refused_with_the_installer_reason_and_a_good_one_is_not(self):
        for rule, values in BAD_PACK_IDS.items():
            for value in values:
                with self.subTest(rule=rule, value=value):
                    self.assertEqual(fields_reason(installer=installer(value)), ("UPDATE_MANIFEST_INVALID", "installer"))
        for value in OK_PACK_IDS:
            with self.subTest(good=value):
                self.assertIsNone(fields_reason(installer=installer(value)))

    def test_the_slash_in_the_middle_is_refused_on_the_signed_path_too(self):
        for value in ("a/b", "A/../x"):
            self.assertEqual(tm.reason_of(tm.check, *tm.signed(installer=installer(value))), ("UPDATE_MANIFEST_INVALID", "installer"), value)
        self.assertIsNone(tm.reason_of(tm.check, *tm.signed(installer=installer("a" * 64))))


# ======================================================================================================================================================
# 5) 한도 상수를 손으로 적은 값으로
# ======================================================================================================================================================
class LimitsTest(unittest.TestCase):
    def test_the_expiry_window_is_exactly_200_days_from_the_issue_time(self):
        self.assertEqual(datetime(2027, 6, 19, 3) - datetime(2026, 12, 1, 3), timedelta(days=200), "아래 글자 값의 근거 — 발행 2026-12-01T03:00:00Z 의 200일 뒤")
        for expires, expected in (("2027-06-18T03:00:00Z", None), ("2027-06-19T03:00:00Z", None), ("2027-06-19T03:00:01Z", ("UPDATE_MANIFEST_INVALID", "time_span")),
                                  ("2027-06-20T03:00:00Z", ("UPDATE_MANIFEST_INVALID", "time_span")), ("2027-06-21T03:00:00Z", ("UPDATE_MANIFEST_INVALID", "time_span"))):
            with self.subTest(expires=expires):
                self.assertEqual(fields_reason(expires_utc=expires), expected)

    def test_the_clock_may_be_up_to_two_days_behind_what_was_seen_before_and_no_more(self):
        high = manifest.read_and_verify(*tm.signed(), keyring=tm.RING)
        for behind, allowed in ((timedelta(hours=36), True), (timedelta(days=2), True), (timedelta(days=2, seconds=1), False), (timedelta(days=3), False)):
            with self.subTest(behind=str(behind)):
                if allowed:
                    self.assertEqual(manifest.evaluate(high, now=tm.NOW, current_version="1.0.0", last_seen=tm.NOW + behind).status, "AVAILABLE")
                else:
                    with self.assertRaises(manifest.ManifestError) as caught:
                        manifest.evaluate(high, now=tm.NOW, current_version="1.0.0", last_seen=tm.NOW + behind)
                    self.assertEqual((caught.exception.code, caught.exception.reason), ("UPDATE_MANIFEST_EXPIRED", "clock_behind"))

    def test_a_manifest_of_exactly_64_kib_is_read_and_one_byte_more_is_refused_as_too_big(self):
        base = us.encode_manifest(us.manifest_dict(key_id=tm.ID_A))
        padded = base[:-1] + b" " * (64 * 1024 - len(base)) + b"\n"
        self.assertEqual(len(padded), 65536)
        self.assertEqual(tm.check(padded, tm.sign_bytes(padded)).status, "AVAILABLE")
        over = padded[:-1] + b" \n"
        self.assertEqual(len(over), 65537)
        self.assertEqual(tm.reason_of(tm.check, over, tm.signed()[1]), ("UPDATE_MANIFEST_INVALID", "size"))

    def test_a_state_file_of_exactly_64_kib_is_read_and_one_byte_more_is_corrupt(self):
        raw = ts.raw_of()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "update"
            folder.mkdir()
            (folder / "state.json").write_bytes(raw + b" " * (65536 - len(raw)))
            self.assertEqual(state.read_state(folder), ts.good_state())
            (folder / "state.json").write_bytes(raw + b" " * (65537 - len(raw)))
            with self.assertRaises(state.StateError) as caught:
                state.read_state(folder)
            self.assertEqual(caught.exception.reason, "corrupt")

    def test_the_boot_attempt_count_is_read_up_to_1000_and_1001_is_corrupt(self):
        pending = state.state_to_dict(ts.good_state())["pending"]
        self.assertEqual(state.parse_state(ts.raw_of(pending={**pending, "boot_attempts": 1000})).pending.boot_attempts, 1000)
        self.assertEqual(state.parse_state(ts.raw_of(pending={**pending, "boot_attempts": 0})).pending.boot_attempts, 0)
        for value in (1001, 10 ** 6, -1):
            with self.subTest(value=value):
                with self.assertRaises(state.StateError) as caught:
                    state.parse_state(ts.raw_of(pending={**pending, "boot_attempts": value}))
                self.assertEqual(caught.exception.reason, "corrupt")

    def test_the_signature_file_read_limit_is_4096_bytes(self):
        self.assertEqual(source.SIGNATURE_LIMIT, 4096)


class FetchLimitTest(tf.FlowCase):
    def test_the_check_asks_for_at_most_64_kib_of_manifest_and_4096_bytes_of_signature(self):
        seen = []
        original = net_client.NetClient.request

        def spy(client_self, use, method, url, **kwargs):
            seen.append((url.rsplit("/", 1)[-1], kwargs.get("limit")))
            return original(client_self, use, method, url, **kwargs)
        with mock.patch.object(net_client.NetClient, "request", spy):
            self.assertEqual(self.check().status, "AVAILABLE")
        self.assertEqual(seen, [("update-manifest.json", 64 * 1024), ("update-manifest.json.sig", 4096)])


# ======================================================================================================================================================
# 6) 실제 접속 클라이언트 공장 — wiring._update_factory 의 본문
# ======================================================================================================================================================
class FactoryBodyTest(tf.FlowCase):
    def test_the_production_factory_that_the_switch_plugs_builds_a_client_that_runs_a_whole_check_over_the_fake_wire(self):
        external.unregister(external.KIND_UPDATE)                # setUp 이 꽂은 시험 공장을 빼고, 스위치가 켜진 빌드가 꽂는 진짜 공장만 쓴다
        self.assertEqual(wiring.register_enabled(), ("update",))
        self.assertIs(external.adapter_factory(external.KIND_UPDATE), wiring._update_factory)
        result = self.check()
        self.assertEqual((result.status, result.manifest.version), ("AVAILABLE", "1.0.1"))
        self.assertEqual(len(self.harness.made), 6, "매니페스트와 서명 각각 최신 길 → 태그 길 → 자산 호스트")
        self.assertIn("User-Agent: ChanceBlogDesktop\r\n", bytes(self.harness.made[0].sent).decode("ascii"))

    def test_the_factory_hands_the_given_usage_counter_to_the_client_and_otherwise_the_session_one(self):
        marker = object()
        client = wiring._update_factory(version="1.2.3", usage=marker)
        self.assertIsInstance(client, net_client.NetClient)
        self.assertIs(client.usage, marker)
        default = wiring._update_factory(version="1.2.3")
        self.assertIsInstance(default, net_client.NetClient)
        self.assertIs(default.usage, net_client.SESSION)


# ======================================================================================================================================================
# 7) report_health 의 조용한 삼킴과 삼키는 자리의 허용 목록
# ======================================================================================================================================================
class ReportHealthSwallowTest(tf.FlowCase):
    switches = ("NET_UPDATE_CHECK", "UPDATE_APPLY")

    def session(self):
        return update_flow.UpdateSession(self.ctx, install_kind="inno", current_version="1.0.1", keyring=fs.RING, adapter=fs.FakeAdapter(self.folder))

    def booted(self):
        """업데이트를 넘긴 뒤 새 판이 처음 켜진 순간까지 — (받아 둔 임시 폴더, 시작 후크의 결과)."""
        first = update_flow.UpdateSession(self.ctx, install_kind="inno", current_version="1.0.0", keyring=fs.RING, adapter=fs.FakeAdapter(self.folder))
        first.check()
        first.download()
        first.apply(confirmed=True)
        return first.staged.folder, state.note_boot(version="1.0.1", folder=self.folder)

    def fresh(self, note):
        session = self.session()
        session.on_boot(note)
        return session

    def test_a_healthy_report_survives_a_marker_that_cannot_be_cleared_and_the_next_start_does_the_job_again(self):
        run, note = self.booted()
        session = self.fresh(note)
        with mock.patch.object(state, "write_state", side_effect=state.StateError("write")):
            self.assertEqual(session.report_health(True), "HEALTHY")
        self.assertEqual(session.state, "HEALTHY")
        left = state.read_state(self.folder)
        self.assertEqual((left.pending.to_version, left.last_good), ("1.0.1", ""), "표식은 그대로 남고 정상 판 기록은 아직이다")
        self.assertTrue(run.exists(), "정리는 시작되지 않았다")
        self.assertFalse(health.keep_dir(self.folder, "1.0.1").exists())
        again = self.fresh(note)
        self.assertEqual(again.report_health(True), "HEALTHY")
        done = state.read_state(self.folder)
        self.assertEqual((done.pending, done.last_good), (None, "1.0.1"))
        self.assertTrue(health.keep_dir(self.folder, "1.0.1").is_dir())
        self.assertFalse(run.exists())

    def test_only_the_state_and_app_errors_are_swallowed_and_anything_else_reaches_the_caller(self):
        run, note = self.booted()
        for error in (state.StateError("unreadable"), AppError("UPDATE_CHECK_FAILED")):
            with self.subTest(swallowed=type(error).__name__):
                with mock.patch.object(health, "mark_healthy", side_effect=error):
                    self.assertEqual(self.fresh(note).report_health(True), "HEALTHY")
                self.assertIsNotNone(state.read_state(self.folder).pending)
        for error in (RuntimeError("boom"), OSError("disk"), fs.Killed()):
            with self.subTest(raised=type(error).__name__):
                with mock.patch.object(health, "mark_healthy", side_effect=error):
                    with self.assertRaises(type(error)):
                        self.fresh(note).report_health(True)

    def test_an_unhealthy_report_never_touches_the_marker(self):
        run, note = self.booted()
        before = (self.folder / "state.json").read_bytes()
        self.assertEqual(self.fresh(note).report_health(False), "RECOVERY_OFFERED")
        self.assertEqual((self.folder / "state.json").read_bytes(), before)
        self.assertEqual(self.fresh(note).report_health(True, probes_ok=False), "RECOVERY_OFFERED")
        self.assertEqual((self.folder / "state.json").read_bytes(), before)


def handlers_of(tree):
    """소스 나무의 모든 except 절 → (감싼 가장 안쪽 함수 이름, 잡는 오류 글, 본문이 pass 뿐인가, 본문 안에 raise 가 있는가)."""
    found = []

    def visit(node, function):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ExceptHandler):
                kind = ast.unparse(child.type) if child.type is not None else "(bare)"
                found.append((function, kind, all(isinstance(item, ast.Pass) for item in child.body), any(isinstance(inner, ast.Raise) for item in child.body for inner in ast.walk(item))))
            visit(child, child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function)
    visit(tree, "")
    return found


UPDATE_FILES = sorted((SRC / "update").glob("*.py"))
FLOW_FILE = SRC / "service" / "update_flow.py"


class SwallowListTest(unittest.TestCase):
    def test_the_package_and_the_service_are_found(self):
        self.assertGreaterEqual(len(UPDATE_FILES), 12)
        self.assertIn("state.py", [path.name for path in UPDATE_FILES])
        self.assertTrue(FLOW_FILE.is_file())

    def test_there_is_no_bare_except_in_the_update_code(self):
        for path in UPDATE_FILES + [FLOW_FILE]:
            with self.subTest(file=path.name):
                self.assertEqual([item for item in handlers_of(parse(path)) if item[1] == "(bare)"], [])

    def test_the_only_except_clauses_whose_body_is_just_pass_are_the_two_known_cleanups(self):
        """조용한 실패 금지(AGENTS 4)를 서비스 층 안전 시험이 못 훑는 `update/` 까지 지킨다 — 둘 다 부수 정리이고 원래 오류를 숨기지 않는다: 임시 파일 지우기 실패(원래 예외를 곧 다시 올린다)와 복구 실패 기록의 실패(원래 실패를 곧 올린다)."""
        found = sorted((path.name, function, kind) for path in UPDATE_FILES + [FLOW_FILE] for function, kind, only_pass, _raises in handlers_of(parse(path)) if only_pass)
        self.assertEqual(found, [("recovery.py", "run_recovery", "Exception"), ("state.py", "write_state", "OSError")])

    def test_the_except_clauses_of_the_service_that_end_without_raising_are_exactly_the_known_four(self):
        """서비스 층에서 오류를 올리지 않고 끝내는 자리는 이 넷뿐이다 — 새로 생기면 여기서 걸려 이유를 적게 한다(`_quietly` 호출 세 자리는 `QuietStepTest` 가 따로 못박는다)."""
        found = sorted((function, kind) for function, kind, _only_pass, raises in handlers_of(parse(FLOW_FILE)) if not raises)
        self.assertEqual(found, sorted([("_quietly", "errors"), ("_kept_installer", "(AppError, OSError, ValueError)"), ("estimate_backup_bytes", "(OSError, KeyError, ValueError)"),
                                        ("report_health", "(state_module.StateError, AppError)")]))

    def test_the_scanner_itself_sees_each_kind_of_clause_in_synthetic_sources(self):
        cases = (
            ("def f():\n    try:\n        g()\n    except OSError:\n        pass\n", [("f", "OSError", True, False)]),
            ("def f():\n    try:\n        g()\n    except OSError:\n        return 1\n", [("f", "OSError", False, False)]),
            ("def f():\n    try:\n        g()\n    except OSError as error:\n        log(error)\n        raise\n", [("f", "OSError", False, True)]),
            ("def f():\n    try:\n        g()\n    except:\n        pass\n", [("f", "(bare)", True, False)]),
            ("def f():\n    def g():\n        try:\n            h()\n        except KeyError:\n            pass\n", [("g", "KeyError", True, False)]),
            ("class C:\n    def m(self):\n        try:\n            h()\n        except (A, B):\n            return None\n", [("m", "(A, B)", False, False)]),
            ("def f():\n    try:\n        g()\n    except OSError:\n        if x:\n            raise\n        return 2\n", [("f", "OSError", False, True)]),
            ("def f():\n    return 1\n", []),
        )
        for source_text, expected in cases:
            with self.subTest(source=source_text.replace("\n", " ; ")[:60]):
                self.assertEqual(handlers_of(ast.parse(source_text)), expected)


# ======================================================================================================================================================
# 8) UPDATE_TEST_OPENSSL_PAIRS 해석
# ======================================================================================================================================================
class OpensslPairsTest(unittest.TestCase):
    def test_unreadable_or_pointless_values_fall_back_to_twelve_and_large_ones_are_capped_at_200(self):
        cases = ((None, 12), ("", 12), ("   ", 12), ("abc", 12), ("0", 12), ("-3", 12), ("1.5", 12), ("1e3", 12), ("0x10", 12), ("5", 5), ("12", 12), (" 30 ", 30), ("200", 200), ("201", 200),
                 ("9" * 30, 200))
        for value, expected in cases:
            with self.subTest(value=value):
                environ = {} if value is None else {"UPDATE_TEST_OPENSSL_PAIRS": value}
                self.assertEqual(us.openssl_pairs(environ), expected)
        self.assertEqual((us.OPENSSL_PAIRS_DEFAULT, us.OPENSSL_PAIRS_MAX), (12, 200))

    def test_without_an_argument_the_real_environment_is_read(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("UPDATE_TEST_OPENSSL_PAIRS", None)
            self.assertEqual(us.openssl_pairs(), 12)
            os.environ["UPDATE_TEST_OPENSSL_PAIRS"] = "7"
            self.assertEqual(us.openssl_pairs(), 7)
            os.environ["UPDATE_TEST_OPENSSL_PAIRS"] = ""
            self.assertEqual(us.openssl_pairs(), 12)

    def test_the_ed25519_test_module_takes_its_pair_count_from_the_helper_and_never_from_a_bare_int_call(self):
        text = (HERE / "test_update_ed25519.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        assigned = [ast.unparse(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "OPENSSL_PAIRS" for target in node.targets)]
        self.assertEqual(assigned, ["us.openssl_pairs()"])
        self.assertNotIn("int(os.environ", text)


# ======================================================================================================================================================
# 9) 문서의 사실
# ======================================================================================================================================================
def section_of(text, start_prefix):
    """`start_prefix` 로 시작하는 줄부터 다음 같은 단계(##) 제목 앞까지."""
    lines = text.splitlines()
    begin = next(index for index, line in enumerate(lines) if line.startswith(start_prefix))
    end = next((index for index in range(begin + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    return "\n".join(lines[begin:end])


class DocFactsTest(unittest.TestCase):
    def read(self, name):
        return (DOCS / name).read_text(encoding="utf-8")

    def decision_row(self, number):
        return next(line for line in self.read("DECISIONS.md").splitlines() if line.startswith(f"| {number} |"))

    def test_release_lists_exactly_the_character_categories_the_app_refuses(self):
        section = section_of(self.read("RELEASE.md"), "## 업데이트 매니페스트 schema 1")
        mentioned = set(re.findall(r"\b(?:C[cfso]|Z[lps])\b", section))
        self.assertEqual(mentioned, set(manifest._HIDDEN_CATEGORIES))
        self.assertIn("서명하기 전에", section)
        self.assertIn("유니코드 데이터베이스", section)

    def test_the_decision_rows_tell_the_true_story_about_the_changed_tests_and_the_rfc_vectors(self):
        changed = self.decision_row("D-803")
        self.assertNotIn("어느 것도 단언을 지우거나 느슨하게 하지 않았고", changed, "개수 못박기가 풀렸다는 사실과 어긋나는 옛 문장")
        for word in ("len(SWITCH_NAMES) == 8", "test_net_switches", "ALL_SWITCHES"):
            self.assertIn(word, changed)
        vectors = self.decision_row("D-791")
        for word in ("다섯", "1023", "update_support"):
            self.assertIn(word, vectors)
        self.assertNotIn("시험 벡터 넷(", vectors, "RFC 벡터는 이제 다섯이다")

    def test_the_security_table_lists_the_five_independent_review_findings_with_the_right_deadline(self):
        section = self.read("SECURITY.md")
        table = section[section.index("### 업데이트를 켜기 전 필수 조건"):]
        rows = [line for line in table.splitlines() if line.startswith("|")]
        for label in ("R1", "R2", "R5"):
            with self.subTest(label=label):
                found = [line for line in rows if f"독립 검증 S {label}" in line]
                self.assertEqual(len(found), 1)
                self.assertIn("켜기 전에 반드시 고친다", found[0])
                self.assertNotIn("U-5 배선 전", found[0])
        for label in ("R3", "R4"):
            with self.subTest(label=label):
                found = [line for line in rows if f"독립 검증 S {label}" in line]
                self.assertEqual(len(found), 1)
                # UPDATE U-4(v1update4, D-852)가 코드로 고쳤다 — 'U-5 배선 전에 고친다' 는 '고쳤다' 로 바뀌었고 그 줄이 묶인 시험 모듈을 말한다(옛 사실·재현·고칠 방향은 그대로 남아 아래 반복이 계속 본다)
                self.assertIn("고쳤다(D-852", found[0])
                self.assertIn("tests/test_update_guards.py", found[0])
                self.assertNotIn("U-5 배선 전에 고친다", found[0], "고쳤으니 아직 고칠 것이라고 적지 않는다")
                self.assertNotIn("켜기 전에 반드시 고친다", found[0])
        for line in rows[2:]:
            if "독립 검증 S R" in line:
                self.assertIn("재현", line)
                self.assertIn("고칠 방향", line)


if __name__ == "__main__":
    unittest.main()
