"""본문 속 Secret 형태 검사기 시험(`security/scan.py`, 설계 D-420–D-429) — 초안 저장·백업·옛 명령줄·화면 쓰기 길이 같은 API 를 부른다.

지키는 것:
  1) API: 이름·서명·`SecretFinding`(불변·슬롯·해시 가능·칸 다섯)·유형 이름 여섯과 한글 이름표·나쁜 인자(글 아님·나쁜 칸 이름)는 고정 문구 예외.
  2) 발견과 위치: 유형마다 대표 표본이 정확한 줄·열에서 한 건. CRLF·LF·CR·섞인 줄바꿈, 결합 글자·이모지·BOM·보이지 않는 글자 앞뒤, 길이가 바뀌는 호환 글자 앞뒤에서도 열이 밀리지 않는다.
     발견한 줄의 `[열 시작 - 1:열 끝]` 이 곧 표본이다(검사기와 따로 세는 `locate`).
  3) 겹침: `Bearer` 뒤의 GitHub 토큰은 GitHub 토큰 한 건 — 더 구체적인 유형이 이기고, 맞닿기만 한 것은 따로 센다.
  4) 칸 여러 개: 건넨 순서, `None` 건너뛰기, 글 아닌 값 거절.
  5) **카나리**: 토큰 글자가 `repr`·`str`·`dataclasses.asdict`·`astuple`·JSON·피클·`describe`·`summarize`·예외 문구·칸 이름 어디에도 없다(실패 출력에도 토큰을 찍지 않는 `leaked` 사용).
  6) 쉬운 한국어 문장의 정확한 모양(여러 건·칸 둘·줄 번호 5개 제한·동작 이름·빈 입력).
  7) 결정성(같은 입력 같은 출력, 해시 씨앗이 달라도), 병적 입력 10만 자 × 여러 모양이 0.5초 안, 소스 규칙(표준 라이브러리 네 개·파일·네트워크·시계·무작위·전역 상태 0, 물결표·웹 주소 없음,
     '무시하고 저장' 인자·함수 없음, 정규식은 선형 시간 모양).
오탐 표·미탐 표·경계값은 `test_security_scan_shapes.py`, 문서는 `test_security_scan_docs.py` 가 지킨다. 키 모양은 실행할 때 조각을 이어 붙여 만든다. 네트워크·실제 비밀 없이 돈다.
"""
import ast
import copy
import dataclasses
import inspect
import json
import os
import pickle
import re
import subprocess
import sys
import time
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_samples as S  # noqa: E402

from chanceblog_desktop.security import scan  # noqa: E402

SCAN_FILE = ROOT / "src" / "chanceblog_desktop" / "security" / "scan.py"
LIMIT_SECONDS = 0.5               # 10만 자 병적 입력 한 건의 시간 상한(운영자 지시서 — 느린 CI 에서도 같은 값, 세 번 재서 빠른 쪽)
LABELS = {"google_api_key": "Google API 키", "github_token": "GitHub 토큰", "bearer_token": "Bearer 토큰", "oauth_token": "OAuth 토큰", "aws_access_key": "AWS 액세스 키", "pem_private_key": "개인 키(PEM)"}
FIX_LINE = "해당 줄을 {target} 지운 뒤 다시 {action}해 주세요 — 앱은 자동으로 지우거나 바꾸지 않아요"


def finding(kind="github_token", where="본문", line=3, col_start=5, col_end=44):
    return scan.SecretFinding(kind, where, line, col_start, col_end)


class ApiTest(unittest.TestCase):
    def test_the_public_names_are_exactly_the_agreed_ones(self):
        self.assertEqual(sorted(scan.__all__), sorted(["KINDS", "KIND_LABELS", "MAX_WHERE_CHARS", "SecretFinding", "describe", "has_secret", "scan_fields", "scan_secrets", "summarize"]))
        for name in scan.__all__:
            self.assertTrue(hasattr(scan, name), name)

    def test_signatures_are_the_agreed_ones_and_have_no_way_to_switch_a_finding_off(self):
        for function, expected in ((scan.scan_secrets, "(text, where='')"), (scan.scan_fields, "(mapping)"), (scan.has_secret, "(text)"), (scan.describe, "(finding)"),
                                   (scan.summarize, "(findings, action='저장')")):
            with self.subTest(function.__name__):
                self.assertEqual(str(inspect.signature(function)), expected)

    def test_the_six_kinds_have_fixed_english_keys_and_korean_labels(self):
        self.assertEqual(scan.KINDS, tuple(LABELS))
        self.assertEqual(S.KINDS, scan.KINDS)
        self.assertEqual(dict(scan.KIND_LABELS), LABELS)
        self.assertEqual(list(scan.KIND_LABELS), list(scan.KINDS))
        with self.assertRaises(TypeError):
            scan.KIND_LABELS["google_api_key"] = "바꿈"
        with self.assertRaises(TypeError):
            del scan.KIND_LABELS["google_api_key"]

    def test_a_finding_is_immutable_slotted_hashable_and_has_five_fields_in_order(self):
        item = finding()
        self.assertEqual([field.name for field in dataclasses.fields(scan.SecretFinding)], ["kind", "where", "line", "col_start", "col_end"])
        self.assertEqual(tuple(scan.SecretFinding.__slots__), ("kind", "where", "line", "col_start", "col_end"))
        self.assertFalse(hasattr(item, "__dict__"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            item.line = 4
        with self.assertRaises((AttributeError, TypeError)):
            item.extra = 1
        self.assertEqual(item, finding())
        self.assertEqual(hash(item), hash(finding()))
        self.assertEqual(len({item, finding(), finding(line=4)}), 2)

    def test_a_finding_refuses_nonsense_values_with_fixed_sentences(self):
        for kwargs in ({"kind": "other"}, {"kind": ""}, {"kind": None}, {"line": 0}, {"line": -1}, {"line": 1.0}, {"line": True}, {"col_start": 0}, {"col_end": 0}, {"col_start": 9, "col_end": 8},
                       {"where": 5}, {"where": "줄\n바꿈"}, {"where": "가" * 81}):
            with self.subTest(kwargs):
                with self.assertRaises(ValueError):
                    finding(**kwargs)
        self.assertEqual(finding(where="가" * 80).where, "가" * 80)
        self.assertEqual(finding(col_start=7, col_end=7).col_end, 7)

    def test_results_are_tuples_and_a_clean_text_gives_the_empty_tuple(self):
        self.assertEqual(scan.scan_secrets("평범한 글이에요"), ())
        self.assertEqual(scan.scan_secrets(""), ())
        self.assertIsInstance(scan.scan_secrets(""), tuple)
        token, line = S.sample("github_token")
        result = scan.scan_secrets(line)
        self.assertIsInstance(result, tuple)
        self.assertIsInstance(result[0], scan.SecretFinding)
        self.assertIsInstance(scan.scan_fields({"본문": line}), tuple)
        self.assertIs(scan.has_secret(line), True)
        self.assertIs(scan.has_secret("평범한 글"), False)

    def test_a_value_that_is_not_text_is_a_type_error_with_a_fixed_sentence(self):
        token, line = S.sample("google_api_key")
        for bad in (None, 5, 1.5, b"abc", bytearray(b"abc"), line.encode("utf-8"), ["a"], ("a",), {"a": 1}, object()):
            for function in (scan.scan_secrets, scan.has_secret):
                with self.subTest(type(bad).__name__, function=function.__name__):
                    with self.assertRaises(TypeError) as caught:
                        function(bad)
                    self.assertEqual(str(caught.exception), "검사할 수 있는 것은 글(str)뿐이에요")
        with self.assertRaises(TypeError):
            scan.scan_secrets("글", where=None)
        with self.assertRaises(TypeError):
            scan.scan_secrets("글", where=5)

    def test_a_label_must_be_short_one_line_and_not_look_like_a_secret(self):
        token, line = S.sample("github_token")
        for bad in ("가" * 81, "줄\n바꿈", "탭\t", "제어" + chr(1), "투명" + chr(0x200B), line):
            with self.subTest(len(bad)):
                with self.assertRaises(ValueError):
                    scan.scan_secrets("글", where=bad)
        self.assertEqual(scan.scan_secrets("글", where="가" * 80), ())
        self.assertEqual(scan.scan_secrets(line, where="가" * 80)[0].where, "가" * 80)
        self.assertEqual(scan.scan_secrets(line, where="초안 3 · 본문")[0].where, "초안 3 · 본문")
        self.assertEqual(scan.scan_secrets(line)[0].where, "")


class DetectionAndPositionTest(unittest.TestCase):
    def test_each_kind_sample_is_one_finding_at_the_exact_line_and_columns(self):
        for kind in scan.KINDS:
            with self.subTest(kind):
                token, line = S.sample(kind)
                text = "첫 줄이에요\n" + line + "\n마지막 줄이에요"
                result = scan.scan_secrets(text, "본문")
                self.assertEqual(S.triples(result), [(kind, *S.locate(text, token))])
                self.assertEqual({item.where for item in result}, {"본문"})
                self.assertTrue(scan.has_secret(text))

    def test_the_found_text_is_exactly_the_sample_for_every_newline_style_and_position(self):
        for newline in ("\n", "\r\n", "\r", "\n\n", "\r\n\r\n"):
            for kind in scan.KINDS:
                token, line = S.sample(kind)
                lines = ["첫째 줄", "둘째 줄", line, "넷째 줄"]
                text = newline.join(lines)
                result = scan.scan_secrets(text)
                with self.subTest(newline=repr(newline), kind=kind):
                    self.assertEqual(len(result), 1)
                    cut = re.split(r"\r\n|\n|\r", text)
                    item = result[0]
                    self.assertTrue(cut[item.line - 1][item.col_start - 1:item.col_end] == token, "발견 자리의 글이 표본과 다르다")
                    self.assertEqual((item.line, item.col_start, item.col_end), S.locate(text, token))

    def test_a_crlf_is_one_line_break_and_a_lone_cr_is_one_too_but_other_separators_are_plain_characters(self):
        token = S.github()
        self.assertEqual(S.triples(scan.scan_secrets("a\r\nb\r\n " + token)), [("github_token", 3, 2, 1 + len(token))])
        self.assertEqual(S.triples(scan.scan_secrets("a\rb\r " + token)), [("github_token", 3, 2, 1 + len(token))])
        self.assertEqual(S.triples(scan.scan_secrets("a\n\rb " + token)), [("github_token", 3, 3, 2 + len(token))], "LF 다음 CR 은 줄바꿈 둘이다")
        for code in (0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029):
            with self.subTest(hex(code)):
                text = "가" + chr(code) + "나 " + token
                self.assertEqual(S.triples(scan.scan_secrets(text)), [("github_token", 1, 5, 4 + len(token))])

    def test_columns_count_python_characters_around_combining_marks_emoji_bom_and_invisible_characters(self):
        token = S.google()
        for label, lead in (("결합 글자", "e" + chr(0x301) * 5 + " "), ("한글 결합 자모", chr(0x1112) + chr(0x1161) + chr(0x11AB) + " "), ("이모지", "😀😀 "), ("가족 이모지", "👨" + chr(0x200D) + "👩" + " "),
                            ("BOM", chr(0xFEFF) + "key="), ("폭 없는 공백", chr(0x200B) * 3 + " "), ("방향 표시", chr(0x202E) + chr(0x200F) + " "), ("전각 공백", chr(0x3000) * 2), ("탭", "\t\t")):
            with self.subTest(label):
                text = "앞줄\n" + lead + token + " 뒤"
                self.assertEqual(S.triples(scan.scan_secrets(text)), [("google_api_key", 2, *S.locate(text, token)[1:])])
                self.assertEqual(S.locate(text, token)[1], len(lead) + 1)

    def test_a_character_that_folds_to_several_letters_does_not_shift_the_columns(self):
        token = S.github()
        for label, lead in (("줄임표", "기다려요" + chr(0x2026) + " "), ("합자 fi", "pro" + chr(0xFB01) + "le "), ("ffi 합자", chr(0xFB03) + " "), ("kg 기호", chr(0x338F) + " "), ("긴 풀이 글자", chr(0xFDFA) + " "),
                            ("로마 숫자 8", chr(0x2167) + " "), ("전화 기호", chr(0x2121) + " "), ("낱글자 전각 숫자", chr(0xFF11) + chr(0xFF12) + " ")):
            with self.subTest(label):
                text = lead + token
                self.assertEqual(S.triples(scan.scan_secrets(text)), [("github_token", 1, len(lead) + 1, len(lead) + len(token))])

    def test_findings_come_in_text_order_across_lines_and_inside_a_line(self):
        google, github, aws = S.google(), S.github(), S.aws()
        text = f"{aws}\nx {github} y {google}\n\n{github}"
        result = scan.scan_secrets(text)
        self.assertEqual([(item.kind, item.line) for item in result], [("aws_access_key", 1), ("github_token", 2), ("google_api_key", 2), ("github_token", 4)])
        self.assertEqual([item.col_start for item in result if item.line == 2], [3, 3 + len(github) + 3])
        self.assertEqual(list(result), sorted(result, key=lambda item: (item.line, item.col_start)))

    def test_a_secret_at_the_very_start_the_very_end_and_alone(self):
        token = S.aws()
        for text, expected in ((token, (1, 1, 20)), (token + "\n", (1, 1, 20)), ("\n" + token, (2, 1, 20)), ("끝 " + token, (1, 3, 22))):
            with self.subTest(repr(text[:3])):
                self.assertEqual(S.triples(scan.scan_secrets(text)), [("aws_access_key", *expected)])

    def test_thousands_of_lines_and_many_findings_keep_exact_positions(self):
        github = S.github()
        text = "\n".join(f"{number}번째 줄 token={github}" for number in range(1, 3001))
        result = scan.scan_secrets(text, "본문")
        self.assertEqual(len(result), 3000)
        for number, item in enumerate(result, 1):
            self.assertEqual((item.line, item.kind), (number, "github_token"))
        first = text.split("\n")[0]
        self.assertEqual((result[0].col_start, result[0].col_end), (first.index(github) + 1, first.index(github) + len(github)))
        crlf = scan.scan_secrets(text.replace("\n", "\r\n"), "본문")
        self.assertEqual([(item.line, item.col_start, item.col_end) for item in crlf], [(item.line, item.col_start, item.col_end) for item in result])

    def test_a_wide_text_shaped_secret_in_fullwidth_letters_is_found_with_the_same_columns(self):
        token = S.github()
        wide = "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= chr(126) else ch for ch in token)
        self.assertNotEqual(wide, token)
        text = "앞 " + wide + " 뒤"
        self.assertEqual(S.triples(scan.scan_secrets(text)), [("github_token", 1, 3, 2 + len(token))])
        self.assertTrue(scan.has_secret(text))

    def test_random_mixtures_of_noise_newlines_and_secrets_are_found_exactly_where_they_were_put(self):
        """고정 씨앗으로 만든 글 300개 — 잡음(한글·영문·이모지·결합 글자·보이지 않는 글자·전각 글자·줄임표)과 줄바꿈 여섯 가지 사이에 비밀 1–6개를 넣고, 검사기와 따로 센 줄·열과 같은지 본다."""
        import random
        rng = random.Random(20261111)
        pool = [("google_api_key", "", S.google()), ("github_token", "", S.github("p")), ("github_token", "", S.github_pat()), ("bearer_token", "Bearer ", S.bearer_value()), ("oauth_token", "", S.ya29()),
                ("oauth_token", "", S.refresh()), ("oauth_token", "", S.jwt()), ("oauth_token", "", S.gocspx()), ("oauth_token", "access_token=", S.body(30, S.B64URL, 8)), ("aws_access_key", "", S.aws()),
                ("pem_private_key", "", S.pem("RSA "))]
        atoms = ["가나다", "hello world", " ", "\t", "😀", chr(0x301), chr(0x200B), chr(0xFF0C), "…", chr(0xFF21) + chr(0xFF22) + chr(0xFF23), "한글 문장입니다", chr(0x2014), ".", ",", "(", ")", '"', "'", "토큰", "Bearer"]
        separators = [" ", "\n", "\r\n", "\r", "\t", "가", "😀", chr(0x3000), chr(0xFF0C), "\n\n", " \r\n "]
        for round_number in range(300):
            parts, expected, length = [], [], 0
            for _ in range(rng.randint(1, 6)):
                noise = "".join(rng.choice(atoms) for _ in range(rng.randint(0, 5)))
                before, after = rng.choice(separators), rng.choice(separators)
                kind, lead, token = rng.choice(pool)
                parts += [noise, before, lead, token, after]
                length += len(noise) + len(before) + len(lead)
                expected.append((kind, length, token))
                length += len(token) + len(after)
            parts.append("".join(rng.choice(atoms) for _ in range(rng.randint(0, 5))))
            text = "".join(parts)
            want = []
            for kind, offset, token in expected:
                line, col = S.position(text, offset)
                want.append((kind, line, col, col + len(token) - 1))
            with self.subTest(round_number):
                self.assertEqual(S.triples(scan.scan_secrets(text)), want)

    def test_the_fold_keeps_the_length_of_every_text(self):
        for text in ("", "abc", "가나다", "ＡＢＣ", "…", chr(0xFDFA), "e" + chr(0x301), "😀", "𝐀𝐁𝐂", chr(0xD800) + " x", chr(0x3000) + chr(0xA0)):
            with self.subTest(len(text)):
                self.assertEqual(len(scan._fold(text)), len(text))
        self.assertEqual(scan._fold("ＡＢ１２"), "AB12")
        self.assertEqual(scan._fold(chr(0xA0) + chr(0x3000) + chr(0x2003)), "   ")
        self.assertEqual(scan._fold("…"), "…", "여러 글자로 풀리는 글자는 그대로 둔다(길이를 지킨다)")
        self.assertEqual(scan._fold("가나"), "가나")
        self.assertEqual(scan._fold("abc"), "abc")


class OverlapTest(unittest.TestCase):
    def kinds(self, text):
        return [(item.kind, item.col_start, item.col_end) for item in scan.scan_secrets(text)]

    def test_a_bearer_prefix_in_front_of_a_more_specific_secret_is_one_finding_of_the_specific_kind(self):
        for kind, token in (("github_token", S.github()), ("google_api_key", S.google()), ("aws_access_key", S.aws()), ("oauth_token", S.jwt()), ("oauth_token", S.ya29())):
            with self.subTest(kind + " " + token[:3]):
                text = "Authorization: Bearer " + token
                self.assertEqual(self.kinds(text), [(kind, 23, 22 + len(token))])

    def test_a_named_oauth_value_that_is_a_known_shape_is_one_finding_of_the_known_kind(self):
        google, ya29 = S.google(), S.ya29()
        self.assertEqual(self.kinds("access_token=" + google), [("google_api_key", 14, 13 + len(google))])
        self.assertEqual(self.kinds("access_token=" + ya29), [("oauth_token", 14, 13 + len(ya29))])
        self.assertEqual(self.kinds('{"refresh_token": "' + S.refresh() + '"}'), [("oauth_token", 20, 19 + len(S.refresh()))])

    def test_two_secrets_inside_one_wide_bearer_run_are_both_reported(self):
        github, aws = S.github(), S.aws()
        text = "Bearer " + github + "." + aws
        self.assertEqual(self.kinds(text), [("github_token", 8, 7 + len(github)), ("aws_access_key", 9 + len(github), 8 + len(github) + len(aws))])

    def test_spans_that_only_touch_are_not_merged(self):
        google, aws = S.google(), S.aws()
        text = aws + "\n" + google
        self.assertEqual([item.kind for item in scan.scan_secrets(text)], ["aws_access_key", "google_api_key"])
        github = S.github()
        text = github + " " + S.github("o")
        self.assertEqual([item.kind for item in scan.scan_secrets(text)], ["github_token", "github_token"])

    def test_spans_that_touch_end_to_start_are_both_kept_in_either_order(self):
        pem, aws = S.pem("RSA "), S.aws()
        for label, text in (("PEM 다음 AWS", pem + aws), ("AWS 다음 PEM", aws + pem), ("PEM 줄 끝에 AWS", pem + "\n" + aws)):
            with self.subTest(label):
                self.assertEqual(sorted(item.kind for item in scan.scan_secrets(text)), ["aws_access_key", "pem_private_key"])
        first = scan.scan_secrets(pem + aws)
        self.assertEqual([(item.kind, item.col_start, item.col_end) for item in first], [("pem_private_key", 1, len(pem)), ("aws_access_key", len(pem) + 1, len(pem) + len(aws))])
        second = scan.scan_secrets(aws + pem)
        self.assertEqual([(item.kind, item.col_start, item.col_end) for item in second], [("aws_access_key", 1, len(aws)), ("pem_private_key", len(aws) + 1, len(aws) + len(pem))])

    def test_a_weaker_span_that_starts_inside_a_stronger_one_is_dropped_even_when_it_runs_past_its_end(self):
        text = "github_" + "pat_" + "A" * 22 + "_" + "AI" + "za" + "B" * 34 + "-"
        result = scan.scan_secrets(text)
        self.assertEqual([item.kind for item in result], ["github_token"])
        self.assertEqual((result[0].col_start, result[0].col_end), (1, len(text) - 1))
        self.assertEqual([item.kind for item in scan.scan_secrets(text + "\n" + S.aws())], ["github_token", "aws_access_key"])

    def test_the_priority_order_is_pem_aws_github_google_oauth_bearer(self):
        self.assertEqual(scan._SPECIFIC_FIRST, ("pem_private_key", "aws_access_key", "github_token", "google_api_key", "oauth_token", "bearer_token"))
        self.assertEqual(sorted(scan._SPECIFIC_FIRST), sorted(scan.KINDS))
        self.assertEqual([scan._RANK[kind] for kind in scan._SPECIFIC_FIRST], list(range(6)))

    def test_same_kind_alternatives_never_double_count_one_secret(self):
        for token in (S.jwt(), S.ya29(), S.refresh()):
            with self.subTest(token[:3]):
                self.assertEqual(len(scan.scan_secrets("access_token=" + token)), 1)
                self.assertEqual(len(scan.scan_secrets("Bearer " + token)), 1)
                self.assertEqual(len(scan.scan_secrets(token)), 1)


class FieldsTest(unittest.TestCase):
    def test_fields_are_scanned_in_the_order_given_with_their_own_names_and_line_numbers(self):
        github, google = S.github(), S.google()
        fields = {"제목": "평범", "본문": "첫 줄\nkey=" + google, "요약": None, "태그": "x " + github + "\n둘째 " + github}
        result = scan.scan_fields(fields)
        self.assertEqual([(item.where, item.kind, item.line) for item in result], [("본문", "google_api_key", 2), ("태그", "github_token", 1), ("태그", "github_token", 2)])

    def test_none_values_are_skipped_and_an_empty_mapping_gives_nothing(self):
        self.assertEqual(scan.scan_fields({}), ())
        self.assertEqual(scan.scan_fields({"a": None, "b": ""}), ())
        self.assertEqual(scan.scan_fields({"a": None, "b": S.sample("aws_access_key")[1]})[0].where, "b")

    def test_a_non_mapping_or_a_non_text_value_or_a_bad_name_is_refused(self):
        for bad in (None, [], [("a", "b")], "본문", 5, ("a", "b")):
            with self.subTest(type(bad).__name__):
                with self.assertRaises(TypeError):
                    scan.scan_fields(bad)
        for value in (5, b"x", ["a"], 1.5):
            with self.subTest(repr(value)):
                with self.assertRaises(TypeError):
                    scan.scan_fields({"본문": value})
        with self.assertRaises(TypeError):
            scan.scan_fields({5: "글"})
        with self.assertRaises(ValueError):
            scan.scan_fields({"줄\n바꿈": "글"})
        with self.assertRaises(ValueError):
            scan.scan_fields({S.github(): "글"})

    def test_a_read_only_mapping_and_an_ordered_dict_work(self):
        from collections import OrderedDict
        from types import MappingProxyType
        text = S.sample("github_token")[1]
        self.assertEqual(len(scan.scan_fields(MappingProxyType({"본문": text}))), 1)
        self.assertEqual([item.where for item in scan.scan_fields(OrderedDict([("나", text), ("가", text)]))], ["나", "가"])


class CanaryTest(unittest.TestCase):
    """토큰 글자가 어디에도 남지 않는다 — 결과 객체의 모든 표현·직렬화·문장·예외·추적·복사본·칸 이름."""

    def outputs(self, results, texts=()):
        found = []
        for item in results:
            found += [repr(item), str(item), json.dumps(dataclasses.asdict(item), ensure_ascii=False), repr(dataclasses.astuple(item)), repr(item.__reduce_ex__(2)), scan.describe(item),
                      repr(copy.deepcopy(item)), repr(copy.copy(item)), pickle.dumps(item, 2).decode("latin-1"), pickle.dumps(item, pickle.HIGHEST_PROTOCOL).decode("latin-1"),
                      " ".join(str(getattr(item, name)) for name in scan.SecretFinding.__slots__), repr({item: 1}), repr(sorted([item], key=lambda x: x.line))]
        found += [repr(results), str(results), scan.summarize(results), scan.summarize(results, "백업")]
        found += [repr(scan.KIND_LABELS), repr(scan.KINDS)]
        return found

    def test_no_output_of_a_finding_contains_any_four_letters_of_the_token(self):
        for kind in scan.KINDS:
            token, line = S.sample(kind)
            text = "앞 줄 " + line + " 뒷 줄"
            results = scan.scan_secrets(text, "본문")
            self.assertEqual(len(results), 1, kind)
            for number, haystack in enumerate(self.outputs(results)):
                with self.subTest(kind, number=number):
                    self.assertFalse(S.leaked(haystack, token), "토큰 글자가 새었다")
            fields = scan.scan_fields({"본문": text, "제목": line})
            for number, haystack in enumerate(self.outputs(fields)):
                with self.subTest(kind, fields=number):
                    self.assertFalse(S.leaked(haystack, token), "토큰 글자가 새었다")

    def test_the_lead_in_words_are_not_leaked_either(self):
        token, line = S.sample("bearer_token")
        results = scan.scan_secrets(line, "본문")
        text = " ".join(self.outputs(results))
        self.assertFalse(S.leaked(text, token))
        self.assertNotIn("Authorization", text)

    def test_every_exception_message_is_a_fixed_sentence_without_the_secret(self):
        token, line = S.sample("github_token")
        raw = line.encode("utf-8")
        attempts = (lambda: scan.scan_secrets(raw), lambda: scan.has_secret(raw), lambda: scan.scan_secrets("글", where=line), lambda: scan.scan_secrets("글", where=token),
                    lambda: scan.scan_fields({line: "글"}), lambda: scan.scan_fields({"본문": raw}), lambda: scan.scan_fields(raw), lambda: scan.describe(line),
                    lambda: scan.summarize([line]), lambda: scan.summarize([finding()], action=line), lambda: scan.summarize([raw]),
                    lambda: scan.SecretFinding("github_token", line, 1, 1, 2), lambda: scan.SecretFinding(line, "본문", 1, 1, 2))
        for number, attempt in enumerate(attempts):
            with self.subTest(number):
                with self.assertRaises((TypeError, ValueError)) as caught:
                    attempt()
                error = caught.exception
                full = "".join(traceback.format_exception(type(error), error, error.__traceback__)) + repr(error) + str(error) + repr(error.args)
                self.assertFalse(S.leaked(full, token), "예외에 토큰 글자가 새었다")
                self.assertIsNone(error.__cause__)
                self.assertEqual(len(error.args), 1)
                self.assertTrue(re.fullmatch(r"[가-힣 ·()A-Za-z,:]+", error.args[0]), "예외 문구는 고정된 한국어 문장이다: " + str(len(error.args[0])))

    def test_the_label_is_echoed_exactly_and_is_never_taken_from_the_text(self):
        token, line = S.sample("google_api_key")
        for where in ("", "본문", "제목", "초안 12 · 본문", "chanceblog.db projects.body"):
            with self.subTest(where):
                self.assertEqual({item.where for item in scan.scan_secrets(line, where)}, {where})
        self.assertEqual({item.where for item in scan.scan_secrets(line)}, {""})
        for item in scan.scan_secrets("제목은 이래요\n" + line, "본문"):
            self.assertFalse(S.leaked(item.where, token))

    def test_the_sentences_carry_no_column_range_so_the_length_of_the_secret_is_not_told(self):
        for kind in scan.KINDS:
            token, line = S.sample(kind)
            item = scan.scan_secrets("  " + line, "본문")[0]
            length = item.col_end - item.col_start + 1
            for text in (scan.describe(item), scan.summarize([item])):
                with self.subTest(kind):
                    self.assertNotIn(str(length) + "자", text)
                    self.assertNotIn(str(length) + "글자", text)
                    self.assertNotIn(str(item.col_start), text.replace(str(item.line), ""), "열 번호도 말하지 않는다")
                    self.assertNotIn(str(item.col_end), text.replace(str(item.line), ""))

    def test_a_secret_text_object_is_not_kept_alive_by_the_result(self):
        import gc
        import weakref

        class Text(str):
            pass
        token, line = S.sample("github_token")
        text = Text("앞 " + line)
        result = scan.scan_secrets(text, "본문")
        reference = weakref.ref(text)
        del text
        gc.collect()
        self.assertIsNone(reference(), "결과가 글 객체를 붙들고 있다")
        self.assertEqual(len(result), 1)


class SentenceTest(unittest.TestCase):
    def test_describe_is_the_agreed_sentence_for_every_kind(self):
        for kind, label in LABELS.items():
            with self.subTest(kind):
                self.assertEqual(scan.describe(finding(kind)), f"본문 3번째 줄에 {label}처럼 보이는 글이 있어요")
        self.assertEqual(scan.describe(finding("github_token", "본문", 3)), "본문 3번째 줄에 GitHub 토큰처럼 보이는 글이 있어요")
        self.assertEqual(scan.describe(finding("aws_access_key", "", 1, 1, 20)), "1번째 줄에 AWS 액세스 키처럼 보이는 글이 있어요")

    def test_describe_refuses_what_is_not_a_finding(self):
        for bad in (None, "본문", 5, ("github_token", "본문", 1, 1, 2), {"kind": "github_token"}):
            with self.subTest(type(bad).__name__):
                with self.assertRaises(TypeError):
                    scan.describe(bad)

    def test_summarize_groups_by_field_and_kind_and_ends_with_how_to_fix_it(self):
        items = [finding("github_token", "본문", 3), finding("google_api_key", "본문", 7)]
        expected = "본문에서 2건(GitHub 토큰 1·Google API 키 1) — 3번째 줄·7번째 줄\n" + FIX_LINE.format(target="본문에서", action="저장")
        self.assertEqual(scan.summarize(items), expected)
        self.assertTrue(scan.summarize(items).endswith("해당 줄을 본문에서 지운 뒤 다시 저장해 주세요 — 앱은 자동으로 지우거나 바꾸지 않아요"))

    def test_summarize_counts_each_kind_and_lists_each_line_once_in_order(self):
        items = [finding("github_token", "본문", 9), finding("github_token", "본문", 2, 1, 40), finding("github_token", "본문", 2, 50, 90), finding("aws_access_key", "본문", 4)]
        self.assertEqual(scan.summarize(items).splitlines()[0], "본문에서 4건(GitHub 토큰 3·AWS 액세스 키 1) — 2번째 줄·4번째 줄·9번째 줄")

    def test_summarize_with_two_fields_names_each_and_says_each_field(self):
        items = [finding("bearer_token", "제목", 1), finding("github_token", "본문", 3), finding("oauth_token", "본문", 5)]
        lines = scan.summarize(items).splitlines()
        self.assertEqual(lines, ["제목에서 1건(Bearer 토큰 1) — 1번째 줄", "본문에서 2건(GitHub 토큰 1·OAuth 토큰 1) — 3번째 줄·5번째 줄", FIX_LINE.format(target="각 칸에서", action="저장")])

    def test_summarize_shows_at_most_five_lines_then_the_rest_as_a_count(self):
        items = [finding("github_token", "본문", number) for number in range(1, 8)]
        self.assertEqual(scan.summarize(items).splitlines()[0], "본문에서 7건(GitHub 토큰 7) — 1번째 줄·2번째 줄·3번째 줄·4번째 줄·5번째 줄 외 2줄")
        five = [finding("github_token", "본문", number) for number in range(1, 6)]
        self.assertNotIn("외", scan.summarize(five))
        self.assertEqual(scan.MAX_LINES_SHOWN, 5)
        six = [finding("github_token", "본문", number) for number in range(1, 7)]
        self.assertIn("외 1줄", scan.summarize(six))

    def test_summarize_names_an_empty_field_as_text_and_takes_the_action_name(self):
        items = [finding("pem_private_key", "", 2, 1, 31)]
        self.assertEqual(scan.summarize(items), "글에서 1건(개인 키(PEM) 1) — 2번째 줄\n" + FIX_LINE.format(target="글에서", action="저장"))
        self.assertTrue(scan.summarize(items, "백업").endswith("다시 백업해 주세요 — 앱은 자동으로 지우거나 바꾸지 않아요"))
        self.assertTrue(scan.summarize(items, action="복사").endswith("다시 복사해 주세요 — 앱은 자동으로 지우거나 바꾸지 않아요"))

    def test_summarize_of_nothing_is_empty_and_of_a_generator_works(self):
        self.assertEqual(scan.summarize(()), "")
        self.assertEqual(scan.summarize([]), "")
        self.assertEqual(scan.summarize(item for item in [finding("github_token", "본문", 1)]).splitlines()[0], "본문에서 1건(GitHub 토큰 1) — 1번째 줄")

    def test_summarize_refuses_a_bad_action_and_things_that_are_not_findings(self):
        for action in ("", "가" * 21, "줄\n바꿈", 5, None, "투명" + chr(0x200B)):
            with self.subTest(repr(action)):
                with self.assertRaises(ValueError):
                    scan.summarize([finding()], action=action)
        self.assertTrue(scan.summarize([finding()], action="가" * 20).endswith("해 주세요 — 앱은 자동으로 지우거나 바꾸지 않아요"))
        for bad in ([None], ["github_token"], [finding(), "x"], [("github_token", "본문", 1, 1, 2)]):
            with self.subTest(repr(bad)[:20]):
                with self.assertRaises(TypeError):
                    scan.summarize(bad)

    def test_the_sentences_have_no_tilde_and_no_web_address(self):
        every = [scan.describe(finding(kind)) for kind in scan.KINDS] + [scan.summarize([finding(kind, "본문", number + 1) for number, kind in enumerate(scan.KINDS)] * 3)]
        for text in every:
            self.assertNotIn(S.TILDE, text)
            self.assertNotRegex(text, r"(?i)(https?|ftp)://|www[.]")


class DeterminismTest(unittest.TestCase):
    CODE = (
        "import sys\n"
        "sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])\n"
        "import scan_samples as S\n"
        "from chanceblog_desktop.security import scan\n"
        "text = '\\n'.join(['가나다 ＡＢＣ 😀 ' + S.github(), 'Bearer ' + S.bearer_value(), chr(0xFDFA) + chr(0x2026) + S.jwt(), S.aws() + ' ' + S.pem(), 'access_token=' + S.ya29()])\n"
        "print(repr(scan.scan_secrets(text, '본문')))\n"
        "print(scan.summarize(scan.scan_secrets(text, '본문')))\n"
    )

    def run_with_seed(self, seed):
        env = dict(os.environ, PYTHONHASHSEED=str(seed), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-X", "utf8", "-c", self.CODE, str(ROOT / "src"), str(ROOT / "tests")], capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-400:])
        return done.stdout

    def test_the_same_input_gives_the_same_output_whatever_the_hash_seed(self):
        outputs = {self.run_with_seed(seed) for seed in (0, 1, 4242)}
        self.assertEqual(len(outputs), 1)
        self.assertIn("SecretFinding(kind='github_token'", outputs.pop())

    def test_scanning_twice_in_one_process_gives_equal_results_and_changes_nothing(self):
        text = S.sample("github_token")[1] + "\n" + S.sample("pem_private_key")[1]
        before = (scan.KINDS, dict(scan.KIND_LABELS), scan._RULES)
        first, second = scan.scan_secrets(text, "본문"), scan.scan_secrets(text, "본문")
        self.assertEqual(first, second)
        self.assertEqual(before, (scan.KINDS, dict(scan.KIND_LABELS), scan._RULES))
        self.assertEqual(scan.scan_secrets(text, "본문"), first)


class PerformanceTest(unittest.TestCase):
    """병적 입력 10만 자 × 여러 모양이 0.5초 안(세 번 재서 빠른 쪽) — 정규식이 선형이라는 증거. 표는 결정 기록·보고서에 있다."""

    @staticmethod
    def shapes():
        size = 100_000
        yield "같은 글자 a", "a" * size
        yield "같은 글자 A", "A" * size
        yield "같은 글자 숫자", "7" * size
        yield "같은 글자 밑줄", "_" * size
        yield "같은 글자 붙임표", "-" * size
        yield "같은 글자 점", "." * size
        yield "같은 글자 등호", "=" * size
        yield "같은 글자 공백", " " * size
        yield "같은 글자 한글", "가" * size
        yield "긴 한 줄 영문 숫자", S.body(size, S.ALNUM)
        yield "긴 한 줄 토큰 글자", S.body(size, S.B64URL)
        yield "줄바꿈만", "\n" * size
        yield "CRLF 만", "\r\n" * (size // 2)
        yield "CR 만", "\r" * size
        yield "Bearer 반복", "Bearer " * (size // 7)
        yield "Bearer 붙여 반복", "Bearer" * (size // 6)
        yield "Bearer 뒤 공백 아주 긺", "Bearer" + " " * size
        yield "Bearer 퍼센트 20 반복", "Bearer" + "%20" * (size // 3)
        yield "AIza 반복", "AIza" * (size // 4)
        yield "AIza 와 짧은 몸", ("AI" + "za" + "A" * 34 + " ") * (size // 39)
        yield "ghp 반복", ("gh" + "p_") * (size // 4)
        yield "ghp 와 짧은 몸", ("gh" + "p_" + "A" * 35 + " ") * (size // 40)
        yield "github_pat 반복", ("github_" + "pat_") * (size // 11)
        yield "ya29 반복", ("ya" + "29.") * (size // 5)
        yield "ya29 와 짧은 몸", ("ya" + "29." + "A" * 19 + " ") * (size // 25)
        yield "1// 반복", ("1/" + "/") * (size // 3)
        yield "eyJ 반복", "eyJ" * (size // 3)
        yield "eyJ 점 반복", "eyJ." * (size // 4)
        yield "eyJ 세 덩어리 반복", ("eyJ" + "a" * 20 + ".eyJ" + "a" * 20 + ".") * (size // 48)
        yield "eyJ 긴 머리 점 없음", "eyJ" + "a" * size
        yield "access_token 반복", "access_token=" * (size // 13)
        yield "access_token 뒤 점 아주 긺", "access_token=" + "." * size
        yield "access_token 뒤 긴 값 점 끝", "access_token=" + "a" * (size - 16) + ".."
        yield "refresh_token 따옴표 반복", "refresh_token\"': \"'" * (size // 20)
        yield "AKIA 반복", "AKIA" * (size // 4)
        yield "AKIA 와 짧은 몸", ("AK" + "IA" + "A" * 15 + " ") * (size // 20)
        yield "AKIA 와 긴 몸", ("AK" + "IA" + "A" * 17 + " ") * (size // 22)
        yield "BEGIN 반복", "-----BEGIN" * (size // 10)
        yield "BEGIN 과 공백", "-----BEGIN" + " " * size
        yield "BEGIN 과 낱말 반복", "-----BEGIN " + "A " * (size // 2)
        yield "BEGIN PRIVATE 반복", "-----BEGIN PRIVATE " * (size // 19)
        yield "붙임표만", "-----" * (size // 5)
        yield "결합 글자 U+0301", chr(0x301) * size
        yield "결합 글자 e 와 U+0301", ("e" + chr(0x301)) * (size // 2)
        yield "결합 글자 U+0F73", chr(0xF73) * size
        yield "풀이가 긴 글자 U+FDFA", chr(0xFDFA) * size
        yield "전각 A", chr(0xFF21) * size
        yield "전각 토큰 모양", ("".join(chr(ord(ch) + 0xFEE0) for ch in "AI" + "za" + "A" * 36)) * (size // 40)
        yield "서로 다른 글자 많음", "".join(chr(0x4E00 + number) for number in range(size))
        yield "이모지", "😀" * size
        yield "한글 산문", "오늘은 날씨가 좋아서 산책을 했어요. " * (size // 19)
        yield "영문 산문", "The quick brown fox jumps over the lazy dog. " * (size // 45)
        yield "토큰 낱말 산문", "Bearer 토큰과 access token, API 키, ghp 접두어를 설명하는 글이에요. " * (size // 40)
        yield "진짜 발견이 아주 많음", ("AK" + "IA" + "A" * 16 + " ") * (size // 21)
        yield "Bearer 와 GitHub 겹침 많음", ("Bearer gh" + "p_" + "A" * 36 + "\n") * (size // 50)

    def measure(self, text):
        """`scan_secrets` 와 `has_secret` 를 따로 세 번씩 재서 각각 빠른 쪽을 구하고 둘 중 느린 값을 돌려준다."""
        worst = 0.0
        for call in (lambda: scan.scan_secrets(text, "본문"), lambda: scan.has_secret(text)):
            best = None
            for _ in range(3):
                started = time.perf_counter()
                call()
                spent = time.perf_counter() - started
                best = spent if best is None else min(best, spent)
            worst = max(worst, best)
        return worst

    def test_every_pathological_shape_of_a_hundred_thousand_characters_is_fast(self):
        count = 0
        for name, text in self.shapes():
            with self.subTest(name):
                self.assertGreaterEqual(len(text), 90_000, "표본이 너무 짧다")
                self.assertLess(self.measure(text), LIMIT_SECONDS)
            count += 1
        self.assertGreaterEqual(count, 50)

    def test_a_hundred_thousand_characters_of_findings_are_all_reported_and_fast(self):
        text = ("AK" + "IA" + "A" * 16 + " ") * 4000
        started = time.perf_counter()
        result = scan.scan_secrets(text, "본문")
        self.assertLess(time.perf_counter() - started, LIMIT_SECONDS)
        self.assertEqual(len(result), 4000)
        self.assertEqual([item.col_start for item in result[:3]], [1, 22, 43])


class SourceRuleTest(unittest.TestCase):
    """검사기 소스가 지키는 규칙 — 표준 라이브러리만, 파일·네트워크·하위 프로세스·시계·무작위·전역 상태 0, '무시하고 저장' 길 없음, 정규식은 선형 시간 모양."""
    ALLOWED_IMPORTS = {"bisect", "re", "unicodedata", "collections.abc", "dataclasses", "types"}
    FORBIDDEN_NAMES = {"open", "print", "input", "exec", "eval", "compile", "__import__", "globals", "locals", "setattr", "delattr", "breakpoint", "exit", "quit"}
    FORBIDDEN_MODULES = {"os", "sys", "io", "time", "datetime", "random", "secrets", "subprocess", "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "shutil", "pathlib", "tempfile", "logging", "threading",
                         "multiprocessing", "asyncio", "ctypes", "pickle", "json", "sqlite3", "functools", "itertools", "builtins", "importlib", "webbrowser", "winreg", "uuid", "hashlib", "hmac", "base64"}
    ALLOWED_MODULE_CALLS = {"re.compile", "MappingProxyType", "frozenset", "tuple", "enumerate"}

    @classmethod
    def setUpClass(cls):
        cls.source = SCAN_FILE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_it_imports_only_the_four_standard_modules_plus_two_helpers(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "상대 가져오기가 있다 — 이 검사기는 다른 모듈을 몰라야 한다")
                imported.add(node.module)
        self.assertEqual(imported, self.ALLOWED_IMPORTS)
        self.assertFalse({name.split(".")[0] for name in imported} & self.FORBIDDEN_MODULES)

    def test_no_name_in_the_source_reaches_files_network_processes_clock_or_randomness(self):
        names = {node.id for node in ast.walk(self.tree) if isinstance(node, ast.Name)} | {node.value.id for node in ast.walk(self.tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)}
        self.assertFalse(names & self.FORBIDDEN_NAMES, sorted(names & self.FORBIDDEN_NAMES))
        self.assertFalse(names & self.FORBIDDEN_MODULES, sorted(names & self.FORBIDDEN_MODULES))
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute):
                self.assertFalse(node.attr in {"read_text", "write_text", "read_bytes", "write_bytes", "urlopen", "system", "popen", "startfile", "now", "time", "random", "sleep", "getenv", "environ"}, node.attr)

    def test_there_is_no_global_or_nonlocal_statement_and_module_level_values_are_immutable(self):
        self.assertFalse([node for node in ast.walk(self.tree) if isinstance(node, (ast.Global, ast.Nonlocal))])

        def immutable(node):
            if isinstance(node, (ast.Constant, ast.Name)):
                return True
            if isinstance(node, ast.Tuple):
                return all(immutable(item) for item in node.elts)
            if isinstance(node, ast.BinOp):
                return immutable(node.left) and immutable(node.right)
            if isinstance(node, ast.JoinedStr):
                return True
            if isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else f"{node.func.value.id}.{node.func.attr}" if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) else ""
                return called in self.ALLOWED_MODULE_CALLS
            return False
        checked = 0
        for node in self.tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                self.assertTrue(immutable(value), f"모듈 맨 위에 바뀔 수 있는 값이 있다(줄 {node.lineno})")
                checked += 1
            elif isinstance(node, (ast.Expr, ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
                continue
            else:
                self.fail(f"모듈 맨 위에 알 수 없는 문장이 있다(줄 {node.lineno})")
        self.assertGreater(checked, 15)

    def test_every_regular_expression_is_compiled_once_at_import_never_inside_a_function(self):
        for function in (node for node in ast.walk(self.tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "re":
                    self.fail(f"함수 {function.name} 안에서 re.{node.func.attr} 를 부른다 — 정규식은 가져올 때 한 번만 만든다")
        module_level = [node for node in self.tree.body if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "compile"]
        self.assertEqual(len(module_level), 7, "정규식 일곱 개(유형 여섯 + 줄바꿈 하나)가 아니다")

    def test_function_parameters_have_no_switch_ignore_force_or_skip_and_the_names_are_the_agreed_ones(self):
        allowed = {"text", "where", "mapping", "finding", "findings", "action", "value", "limit", "self"}
        for function in (node for node in ast.walk(self.tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            args = function.args
            names = [arg.arg for arg in args.posonlyargs + args.args + args.kwonlyargs] + ([args.vararg.arg] if args.vararg else []) + ([args.kwarg.arg] if args.kwarg else [])
            for name in names:
                self.assertTrue(name in allowed, f"{function.name}({name}) — 허용한 인자 이름이 아니다")
            for default in args.defaults + args.kw_defaults:
                if default is not None:
                    self.assertIsInstance(default, ast.Constant, f"{function.name}: 바뀔 수 있는 기본값")
        public = {node.name for node in self.tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_")}
        self.assertEqual(public, {"SecretFinding", "describe", "has_secret", "scan_fields", "scan_secrets", "summarize"})
        wanted_words = re.compile(r"(?i)ignore|force|skip|bypass|override|allow|unsafe|disable|suppress|무시|건너|끄기")
        identifiers = {node.id for node in ast.walk(self.tree) if isinstance(node, ast.Name)} | {node.name for node in ast.walk(self.tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        identifiers |= {node.arg for node in ast.walk(self.tree) if isinstance(node, ast.arg)} | {node.attr for node in ast.walk(self.tree) if isinstance(node, ast.Attribute)}
        self.assertEqual([name for name in sorted(identifiers) if wanted_words.search(name)], [], "발견을 끄는 이름이 생겼다 — 운영자 결정: 무시하고 저장 없음")

    def test_the_source_has_no_tilde_no_web_address_and_no_complete_key_shape(self):
        self.assertNotIn(S.TILDE, self.source)
        self.assertNotRegex(self.source, r"(?i)(https?|ftp)://|www[.]")
        key_shapes = (r"AIza[0-9A-Za-z_-]{35}", r"(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}", r"github_pat_[A-Za-z0-9_]{40,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"AKIA[0-9A-Z]{16}")
        for pattern in key_shapes:
            self.assertIsNone(re.search(pattern, self.source), pattern)

    def test_a_non_breaking_python_310_syntax_and_a_docstring_on_the_module_and_the_public_functions(self):
        ast.parse(self.source, feature_version=(3, 10))
        self.assertTrue(ast.get_docstring(self.tree))
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
                self.assertTrue(ast.get_docstring(node), node.name)

    def test_the_module_object_holds_only_the_three_standard_modules_it_uses_and_no_project_module(self):
        import types
        held = sorted(name for name, value in vars(scan).items() if isinstance(value, types.ModuleType))
        self.assertEqual(held, ["bisect", "re", "unicodedata"])
        for name, value in vars(scan).items():
            module = getattr(value, "__module__", "") or ""
            self.assertFalse(module.startswith("chanceblog_desktop") and module != scan.__name__, f"{name} 은 다른 프로젝트 모듈에서 왔다")


def regex_trees():
    try:
        import re._parser as parser                       # 3.11 부터
    except ImportError:                                   # 3.10
        import sre_parse as parser
    return parser


def repeat_violations(pattern, flags=0, limit=8):
    """선형 시간을 해치는 모양: 최대 반복이 `limit` 를 넘는 반복 안의 또 다른 반복(중첩 수량자)·갈래(겹칠 수 있는 대안)."""
    parser = regex_trees()
    problems = []

    def walk(sub, inside_big):
        for op, args in sub:
            name = str(op)
            if name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
                low, high, body = args
                if inside_big:
                    problems.append("큰 반복 안의 반복")
                walk(body, inside_big or high > limit)
            elif name == "BRANCH":
                if inside_big:
                    problems.append("큰 반복 안의 갈래")
                for branch in args[1]:
                    walk(branch, inside_big)
            elif name == "SUBPATTERN":
                walk(args[-1], inside_big)
            elif name in ("ASSERT", "ASSERT_NOT"):
                walk(args[1], inside_big)
            elif name == "ATOMIC_GROUP":
                walk(args, inside_big)
    walk(parser.parse(pattern, flags), False)
    return problems


class RegexShapeTest(unittest.TestCase):
    def test_the_checker_itself_finds_nested_quantifiers_and_overlapping_alternatives(self):
        for bad in (r"(a+)+", r"(?:a*)*", r"(?:a|a)*", r"(?:ab|a)+b", r"(?:[a-z]+[ ]+){0,20}", r"(a+){9}", r"(?:ab|abc|x)+"):
            with self.subTest(bad):
                self.assertTrue(repeat_violations(bad), bad)
        for good in (r"a+b+", r"[a-z]{35,}", r"(?:[a-z]+[ ]+){0,3}x", r"(?:ab|cd)x", r"(?<![A-Za-z0-9])(AIza[A-Za-z0-9_-]{35,})"):
            with self.subTest(good):
                self.assertEqual(repeat_violations(good), [], good)

    def test_no_rule_has_a_nested_quantifier_or_an_alternative_inside_a_big_repeat(self):
        self.assertEqual(len(scan._RULES), 6)
        for kind, rule in scan._RULES:
            with self.subTest(kind):
                self.assertEqual(repeat_violations(rule.pattern, rule.flags), [])
        self.assertEqual(repeat_violations(scan._NEWLINE.pattern), [])

    def test_every_rule_has_exactly_the_groups_that_name_the_secret_span(self):
        expected = {"google_api_key": 1, "github_token": 1, "bearer_token": 1, "oauth_token": 5, "aws_access_key": 1, "pem_private_key": 1}
        self.assertEqual({kind: rule.groups for kind, rule in scan._RULES}, expected)
        self.assertEqual([kind for kind, _ in scan._RULES], list(scan.KINDS))


if __name__ == "__main__":
    unittest.main()
