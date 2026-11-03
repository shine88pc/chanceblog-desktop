"""주제 후보 CSV 가져오기의 순수한 부분 시험 — 글자 판별(UTF-8·BOM·cp949)·표 읽기(머리줄·열 이름·구분 글자·따옴표 속 쉼표와 줄바꿈)·칸 값(숫자·점수·날짜·블로그·글 유형)·`safe_cell`.

지키는 것:
  1) 파일 전체가 안 되는 경우(너무 큼·UTF-16·NUL·읽을 수 없는 글자·빈 파일·머리줄 없음·필요한 열 없음·같은 뜻의 열 둘·줄이 너무 많음)는 CANDIDATE_CSV_INVALID 로 거절한다.
  2) 한 줄만 안 되는 경우(칸 값을 바꿀 수 없음·열이 너무 많음·칸이 너무 김)는 그 줄의 CsvCellError/problem 이고 다른 줄은 영향이 없다.
  3) 열 이름은 한국어·영어, 띄어쓰기·밑줄·대소문자 무관이고 모르는 열은 무시하되 알린다. 같은 뜻의 열 이름 두 개가 한 열을 가리키지 않는다.
  4) 지표가 하나라도 있으면 조회일이 있어야 한다는 규칙(후보 자료의 규칙)을 줄 단위로 지키고, 조회일 날짜 검사는 후보 자료의 검사와 같은 값에서 같은 결과를 낸다.
네트워크·파일 없이 돈다.
"""
import csv
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import Candidate  # noqa: E402
from chanceblog_desktop.content import candidate_csv as c  # noqa: E402
from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content.status import PLATFORMS  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service.format import PLATFORM_KO  # noqa: E402

HEAD = "주제,핵심 키워드,대상 블로그"


class FakeReader:
    """`csv.reader` 흉내 — 줄마다 칸 목록을 주거나, 예외 값이면 그 예외를 낸다(읽기 도구가 읽을 수 없는 줄을 만난 경우를 만들려고)."""

    def __init__(self, items):
        self.items, self.line_num = iter(items), 0

    def __iter__(self):
        return self

    def __next__(self):
        item = next(self.items)
        self.line_num += 1
        if isinstance(item, Exception):
            raise item
        return item


def table(text, **kwargs):
    return c.parse_table(text, **kwargs)


def fields(text, index=0, **kwargs):
    parsed = c.parse_table(text, blogs_given=bool(kwargs.get("default_blogs")))
    return c.row_fields(parsed, parsed.records[index], **kwargs)


class Refused(unittest.TestCase):
    def file_error(self, callable_, *args, **kwargs):
        with self.assertRaises(AppError) as caught:
            callable_(*args, **kwargs)
        self.assertEqual(caught.exception.code, "CANDIDATE_CSV_INVALID", caught.exception.detail)
        shown = caught.exception.rendered()
        self.assertNotIn("알 수 없음", shown.message, "이유 자리표시자가 채워져야 한다")
        return caught.exception

    def cell_error(self, callable_, *args, **kwargs):
        with self.assertRaises(c.CsvCellError) as caught:
            callable_(*args, **kwargs)
        return caught.exception


class DecodeTest(Refused):
    def test_utf8_with_and_without_a_byte_order_mark_and_cp949_are_all_read(self):
        text = "주제,핵심 키워드,대상 블로그\n겨울 보일러,보일러 점검,네이버 A\n"
        self.assertEqual(c.decode(text.encode("utf-8")), text)
        self.assertEqual(c.decode(b"\xef\xbb\xbf" + text.encode("utf-8")), text, "BOM 은 읽을 때 떼어 낸다")
        self.assertEqual(c.decode(text.encode("cp949")), text)

    def test_utf8_is_tried_before_cp949(self):
        self.assertEqual(c.decode("가나다".encode("utf-8")), "가나다")
        latin = "Zoë café ñ ü ß"
        self.assertNotEqual(latin.encode("utf-8").decode("cp949"), latin, "이 글자들의 UTF-8 바이트는 cp949 로도 읽히지만 다른 글자가 된다")
        self.assertEqual(c.decode(latin.encode("utf-8")), latin)

    def test_utf16_is_refused_with_advice(self):
        for data in ("a,b\n1,2\n".encode("utf-16"), b"\xfe\xff\x00a", "주제,키워드\n".encode("utf-16-be")[:0] + b"\xff\xfe" + "주제".encode("utf-16-le")):
            with self.subTest(data=data[:4]):
                error = self.file_error(c.decode, data)
                self.assertIn("UTF-16", error.rendered().message)
        self.assertIn("NUL", self.file_error(c.decode, "a,b".encode("utf-16-le")).rendered().message, "표지(BOM)가 없는 UTF-16 은 NUL 글자로 걸린다")

    def test_a_file_with_a_nul_character_is_not_text(self):
        self.file_error(c.decode, b"a,b\n1\x002,3\n")

    def test_bytes_that_are_neither_utf8_nor_cp949_are_refused(self):
        error = self.file_error(c.decode, b"\xff\xff\xff\xff,\x81\x20\n")
        self.assertIn("UTF-8", error.rendered().message)

    def test_an_empty_file_a_lone_mark_and_whitespace_are_empty(self):
        for data in (b"", b"\xef\xbb\xbf", b"  \n\r\n \t\n"):
            with self.subTest(data=data):
                self.assertIn("비어", self.file_error(c.decode, data).rendered().message)

    def test_the_size_limit_is_five_megabytes_exactly(self):
        self.assertEqual(c.MAX_CSV_BYTES, 5 * 1024 * 1024)
        self.assertEqual(len(c.decode(b"a" * c.MAX_CSV_BYTES)), c.MAX_CSV_BYTES)
        self.assertIn("5MB", self.file_error(c.decode, b"a" * (c.MAX_CSV_BYTES + 1)).rendered().message)


class HeaderTest(Refused):
    BASE = {"topic": "주제", "keyword": "핵심 키워드", "blogs": "대상 블로그"}

    def test_every_accepted_name_works_in_korean_and_english_whatever_the_spacing_case_or_underscores(self):
        for field, aliases in c.FIELD_ALIASES.items():
            for alias in aliases:
                for variant in (alias, alias.upper(), alias.replace(" ", "_"), alias.replace(" ", ""), "  " + alias + "  ", alias.title()):
                    with self.subTest(field=field, name=variant):
                        names = {**self.BASE, field: variant}
                        columns = list(names.values())
                        found = table(",".join(columns) + "\n" + ",".join("x" for _ in columns) + "\n")
                        self.assertEqual(found.columns[field], columns.index(variant), "그 이름이 그 필드의 열이 된다")
                        self.assertEqual(found.unknown, ())

    def test_every_field_has_its_own_names_and_no_two_fields_share_one(self):
        seen = {}
        for field, aliases in c.FIELD_ALIASES.items():
            self.assertIn(field, cd.LABELS, "화면에 보일 이름이 있어야 한다")
            for alias in aliases:
                key = c.flat(alias)
                self.assertNotIn(key, seen, f"{alias!r} 이(가) {seen.get(key)} 와 {field} 에 모두 있다")
                seen[key] = field
        self.assertEqual(set(c.FIELD_ALIASES), {"topic", "keyword", "sub_keywords", "blogs", "post_type", *cd.METRIC_FIELDS, "reason", "data_date"})
        self.assertEqual(len(c._FIELD_OF), len(seen))

    def test_unknown_columns_are_ignored_and_listed(self):
        found = table("번호,주제,핵심 키워드,대상 블로그,메모,\n1,가,나,naver_a,x,\n")
        self.assertEqual(found.unknown, ("번호", "메모"))
        self.assertEqual(set(found.columns), {"topic", "keyword", "blogs"})

    def test_a_header_without_the_needed_columns_names_what_is_missing(self):
        for text, missing in (("주제,대상 블로그\n", ["핵심 키워드"]), ("핵심 키워드,대상 블로그\n", ["추천 포스팅 주제"]), ("메모,번호\n1,2\n", ["추천 포스팅 주제", "핵심 키워드", "추천 대상 블로그"]),
                              ("주제,핵심 키워드\n가,나\n", ["추천 대상 블로그"])):
            with self.subTest(text=text):
                message = self.file_error(table, text).rendered().message
                for name in missing:
                    self.assertIn(name, message)

    def test_the_blog_column_may_be_left_out_when_a_default_blog_is_given(self):
        self.assertEqual(set(table("주제,핵심 키워드\n가,나\n", blogs_given=True).columns), {"topic", "keyword"})
        message = self.file_error(table, "주제,핵심 키워드\n가,나\n").rendered().message
        self.assertIn("--blog", message)

    def test_a_file_whose_first_line_is_data_has_no_header(self):
        self.file_error(table, "겨울 보일러 점검,보일러 점검,naver_a\n전기장판,전기장판,naver_b\n")

    def test_two_columns_with_the_same_meaning_are_refused(self):
        for head in ("주제,핵심 키워드,대상 블로그,topic", "주제,핵심 키워드,키워드,대상 블로그", "주제,핵심 키워드,블로그,Blog", "주제,핵심 키워드,대상 블로그,월간 검색 수요,검색량"):
            with self.subTest(head=head):
                self.assertIn("같은 뜻", self.file_error(table, head + "\n").rendered().message)

    def test_duplicate_unknown_columns_are_fine(self):
        found = table("주제,핵심 키워드,대상 블로그,메모,메모\n가,나,naver_a,1,2\n")
        self.assertEqual(found.unknown, ("메모", "메모"))

    def test_leading_blank_lines_before_the_header_are_skipped_and_the_line_numbers_stay_true(self):
        found = table("\n\n" + HEAD + "\n가,나,naver_a\n")
        self.assertEqual((found.header_line, found.records[0].line), (3, 4))

    def test_column_and_blog_names_are_compared_after_folding_compatibility_characters(self):
        """한글 입력기·엑셀에서 전각 글자(`ＴＯＰＩＣ`)나 전각 공백이 섞여도 같은 이름으로 본다(NFKC)."""
        self.assertEqual(c.flat("ＴＯＰＩＣ"), "topic")
        self.assertEqual(c.flat("Ｋｅｙ　Ｗｏｒｄ"), "keyword")
        self.assertEqual(c.flat("㈜주제"), c.flat("(주)주제"))
        found = table("ＴＯＰＩＣ,ｋｅｙ　ｗｏｒｄ,ｂｌｏｇ\n가,나,naver_a\n")
        self.assertEqual((set(found.columns), found.unknown), ({"topic", "keyword", "blogs"}, ()))
        self.assertEqual(c.parse_blogs("ＮＡＶＥＲ　Ａ"), ("naver_a",))
        self.assertEqual(c.parse_blogs("ｎａｖｅｒ＿ｂ"), ("naver_b",))

    def test_a_header_with_only_a_few_columns_but_a_leading_mark_still_maps(self):
        text = c.decode(b"\xef\xbb\xbf" + (HEAD + "\n가,나,naver_a\n").encode("utf-8"))
        self.assertEqual(set(table(text).columns), {"topic", "keyword", "blogs"})


class DelimiterAndQuotesTest(Refused):
    def test_tab_and_semicolon_separated_files_are_read(self):
        for mark in ("\t", ";"):
            with self.subTest(mark=repr(mark)):
                found = table(mark.join(("주제", "핵심 키워드", "대상 블로그")) + "\n" + mark.join(("가", "나", "naver_a")) + "\n")
                self.assertEqual(found.records[0].cells, ("가", "나", "naver_a"))

    def test_the_delimiter_with_the_most_marks_in_the_header_wins_and_a_tie_goes_to_the_comma(self):
        found = table("주제,핵심 키워드;\n가,나;\n", blogs_given=True)                      # 쉼표 1 · 세미콜론 1 — 같으면 쉼표(열 이름의 끝 구두점은 무시된다)
        self.assertEqual((found.names, set(found.columns), found.records[0].cells), (("주제", "핵심 키워드;"), {"topic", "keyword"}, ("가", "나;")))
        found = table("주제;핵심 키워드;대상 블로그;메모,\n가;나;naver_a;x,\n")               # 세미콜론 3 · 쉼표 1
        self.assertEqual((found.records[0].cells, found.unknown), (("가", "나", "naver_a", "x,"), ("메모,",)))
        found = table("주제\t핵심 키워드\t대상 블로그;,\n가\t나\tnaver_a;,\n")                    # 탭 2 · 세미콜론 1 · 쉼표 1
        self.assertEqual((found.names, found.records[0].cells), (("주제", "핵심 키워드", "대상 블로그;,"), ("가", "나", "naver_a;,")))

    def test_the_delimiter_is_chosen_from_the_first_line_that_has_text_even_after_blank_lines(self):
        for mark in ("\t", ";"):
            with self.subTest(mark=repr(mark)):
                found = table("\n   \n\n" + mark.join(("주제", "핵심 키워드", "대상 블로그")) + "\n" + mark.join(("가", "나", "naver_a")) + "\n")
                self.assertEqual((found.header_line, found.records[0].cells), (4, ("가", "나", "naver_a")))

    def test_a_comma_inside_quotes_stays_in_the_cell_and_a_newline_inside_quotes_too(self):
        found = table(HEAD + '\n"겨울, 보일러\n점검 순서",보일러 점검,"naver_a, naver_b"\n두번째,키워드,naver_a\n')
        first, second = found.records
        self.assertEqual(first.cells, ("겨울, 보일러\n점검 순서", "보일러 점검", "naver_a, naver_b"))
        self.assertEqual((first.line, first.span, second.line, second.span), (2, 2, 4, 1), "줄 번호는 따옴표 속 줄바꿈을 센다")
        values = c.row_fields(found, first)
        self.assertEqual((values["topic"], values["blogs"]), ("겨울, 보일러 점검 순서", ("naver_a", "naver_b")), "칸 속 줄바꿈은 한 칸 공백이 된다")

    def test_an_escaped_double_quote_inside_quotes(self):
        found = table(HEAD + '\n"""겨울"" 보일러",키워드,naver_a\n')
        self.assertEqual(found.records[0].cells[0], '"겨울" 보일러')

    def test_windows_unix_and_old_mac_line_endings_all_work(self):
        for ending in ("\r\n", "\n", "\r"):
            with self.subTest(ending=repr(ending)):
                found = table(HEAD + ending + "가,나,naver_a" + ending + "다,라,naver_b" + ending)
                self.assertEqual([record.cells[0] for record in found.records], ["가", "다"])
                self.assertEqual([record.line for record in found.records], [2, 3])

    def test_blank_lines_and_lines_of_only_commas_are_ignored_and_counted(self):
        found = table(HEAD + "\n\n가,나,naver_a\n,,\n   ,  ,\n다,라,naver_b\n\n")
        self.assertEqual([record.cells[0] for record in found.records], ["가", "다"])
        self.assertEqual(found.blank, 4)

    def test_a_cell_beyond_the_default_reader_limit_is_read_whole_for_the_candidate_rules_to_judge(self):
        giant = "가" * 200_000
        found = table(HEAD + f'\n"{giant}",나,naver_a\n다,라,naver_b\n')
        self.assertEqual(len(found.records), 2)
        self.assertEqual((found.records[0].problem, len(found.records[0].cells[0])), ("", 200_000))
        self.assertEqual(found.records[1].cells, ("다", "라", "naver_b"))
        self.assertEqual(len(c.row_fields(found, found.records[0])["topic"]), 200_000, "너무 긴 주제는 후보 자료가 그 줄만 거절한다")

    def test_a_quoted_cell_of_many_short_lines_beyond_the_limit_never_turns_its_inner_lines_into_records(self):
        """읽기 도구의 기본 칸 크기 한도(128KB)에서 읽기가 끊기면 큰따옴표 속 줄들이 '새 자료 줄'(유령 후보)로 읽혔다."""
        filler = "\n".join("x" * 100 for _ in range(1500))                 # 약 150KB, 줄마다 짧다
        text = HEAD + ",추천 이유\n" + '진짜 첫 줄,kw1,naver_a,"' + filler + '\n유령 줄 주제,ghostkw,naver_a,내용\n끝 따옴표 뒤"\n진짜 마지막 줄,kw3,naver_a,ok\n'
        found = table(text)
        self.assertEqual([record.cells[0] for record in found.records], ["진짜 첫 줄", "진짜 마지막 줄"], "따옴표 속 줄은 새 자료 줄이 아니다")
        first = found.records[0]
        self.assertEqual((first.problem, first.line, first.span), ("", 2, 1502))
        self.assertIn("유령 줄 주제,ghostkw,naver_a,내용", first.cells[3])
        self.assertEqual((found.records[1].line, found.records[1].span), (1504, 1))

    def test_the_reader_limit_is_raised_only_while_reading_and_put_back_after_an_error_or_a_file_error_too(self):
        before = csv.field_size_limit()
        table(HEAD + "\n가,나,naver_a\n")
        self.assertEqual(csv.field_size_limit(), before)
        self.file_error(table, "")                                                          # 빈 글 — 머리줄 없음
        self.assertEqual(csv.field_size_limit(), before)
        with mock.patch.object(c.csv, "reader", return_value=FakeReader([["주제", "핵심 키워드", "대상 블로그"], csv.Error("시험용 읽기 오류"), ["다", "라", "naver_a"]])):
            found = table(HEAD + "\n가,나,naver_a\n")
        self.assertEqual(csv.field_size_limit(), before, "읽다가 오류가 나도 한도를 되돌린다")
        self.assertEqual([record.problem for record in found.records], ["CSV 모양이 올바르지 않습니다(시험용 읽기 오류)", ""])
        self.assertEqual(found.records[1].cells, ("다", "라", "naver_a"), "읽을 수 없는 줄 다음 줄은 읽는다")
        with mock.patch.object(c.csv, "reader", return_value=FakeReader([csv.Error("머리줄 오류")])):
            error = self.file_error(table, HEAD + "\n")
        self.assertIn("머리줄", error.rendered().message)
        self.assertEqual(csv.field_size_limit(), before)

    def test_a_limit_someone_else_set_is_put_back_exactly_not_reset_to_the_default(self):
        before = csv.field_size_limit()
        try:
            csv.field_size_limit(before * 4)
            table(HEAD + "\n가,나,naver_a\n")
            self.assertEqual(csv.field_size_limit(), before * 4, "다른 곳에서 정해 둔 한도는 그대로 돌려 놓는다")
        finally:
            csv.field_size_limit(before)

    def test_a_long_but_readable_cell_passes_through_for_the_candidate_rules_to_judge(self):
        found = table(HEAD + "\n" + "가" * 100_000 + ",나,naver_a\n")
        self.assertEqual(len(c.row_fields(found, found.records[0])["topic"]), 100_000)

    def test_a_line_with_more_cells_than_the_header_is_refused_but_empty_extras_are_fine(self):
        found = table(HEAD + "\n가,나,naver_a,남는칸\n다,라,naver_a,,\n")
        error = self.cell_error(c.row_fields, found, found.records[0])
        self.assertEqual(error.item, "열 수")
        self.assertIn("큰따옴표", error.reason)
        self.assertEqual(c.row_fields(found, found.records[1])["topic"], "다")

    def test_a_line_with_fewer_cells_reads_the_rest_as_empty(self):
        found = table(HEAD + ",월간 검색 수요\n가,나\n")
        error = self.cell_error(c.row_fields, found, found.records[0])
        self.assertEqual(error.item, cd.LABELS["blogs"], "대상 블로그 칸이 빈 줄은 거절한다")

    def test_the_row_limit_is_two_thousand_data_lines_and_blank_lines_do_not_count(self):
        self.assertEqual(c.MAX_CSV_ROWS, 2000)
        rows = "\n".join(f"주제{n},키워드{n},naver_a" for n in range(c.MAX_CSV_ROWS))
        self.assertEqual(len(table(HEAD + "\n" + rows + "\n\n\n").records), 2000)
        error = self.file_error(table, HEAD + "\n" + rows + "\n마지막,키워드,naver_a\n")
        self.assertIn("2000", error.rendered().message)

    def test_a_header_line_the_reader_cannot_parse_is_a_file_error(self):
        self.file_error(table, '"' + "가" * 200_000 + HEAD + "\n")


class ValueParsersTest(Refused):
    def test_counts_take_thousands_separators_and_whole_float_forms_and_missing_markers(self):
        for text, expected in (("12000", 12000), ("12,000", 12000), (" 1 200 ", 1200), ("1200.0", 1200), ("1200.00", 1200), ("0", 0), ("", None), ("-", None), ("N/A", None), ("n/a", None),
                               ("데이터 없음", None), ("null", None), ("None", None), ("—", None)):
            with self.subTest(text=text):
                self.assertEqual(c.parse_count(text, "월간 검색 수요", 1_000_000_000), expected)

    def test_counts_that_are_not_non_negative_whole_numbers_are_refused_with_the_column_name(self):
        for text in ("-5", "1.5", "12a", "만", "1e3", "NaN", "inf", "１２", "9" * 16, "+5", "1,2,3.5"):
            with self.subTest(text=text):
                error = self.cell_error(c.parse_count, text, "월간 검색 수요", 1_000_000_000)
                self.assertEqual(error.item, "월간 검색 수요")
        self.assertEqual(c.parse_count("1000000000", "x", 1_000_000_000), 1_000_000_000)
        self.assertIn("1,000,000,000", self.cell_error(c.parse_count, "1000000001", "x", 1_000_000_000).reason)

    def test_a_huge_digit_string_is_refused_not_converted(self):
        self.cell_error(c.parse_count, "9" * 6000, "x", 10 ** 12)

    def test_scores_take_percent_and_stay_within_zero_and_one_hundred(self):
        for text, expected in (("72.5", 72.5), ("72.5%", 72.5), ("100", 100), ("0", 0), ("0.0", 0), ("65 %", 65), ("5", 5), ("", None), ("-", None)):
            with self.subTest(text=text):
                self.assertEqual(c.parse_score(text, "모바일 비중"), expected)
        self.assertIsInstance(c.parse_score("72", "x"), int)
        self.assertIsInstance(c.parse_score("72.5", "x"), float)
        for text in ("100.1", "101", "-1", "abc", "nan", "inf", "1e2", "50%%", "%", "1,5", "1000"):
            with self.subTest(text=text):
                self.assertEqual(self.cell_error(c.parse_score, text, "모바일 비중").item, "모바일 비중")

    def test_trend_takes_korean_and_english_words(self):
        for text, expected in (("상승", "상승"), ("보합", "보합"), ("하락", "하락"), ("UP", "상승"), ("Flat", "보합"), ("down", "하락"), ("rising", "상승"), ("", None), ("-", None)):
            with self.subTest(text=text):
                self.assertEqual(c.parse_trend(text), expected)
        error = self.cell_error(c.parse_trend, "폭등")
        self.assertIn("상승", error.reason)
        self.assertEqual(error.item, cd.LABELS["trend"])

    def test_months_take_several_spellings_and_leave_the_range_check_to_the_candidate(self):
        for text, expected in (("11,12,1", (11, 12, 1)), ("11월 12월 1월", (11, 12, 1)), ("11;12;1", (11, 12, 1)), ("11 / 12", (11, 12)), ("3", (3,)), ("", None), ("-", None), ("13", (13,)), ("1,1", (1, 1))):
            with self.subTest(text=text):
                self.assertEqual(c.parse_months(text), expected)
        for text in ("봄", "11월-12월", "1.5", "일월"):
            with self.subTest(text=text):
                self.cell_error(c.parse_months, text)

    def test_yes_and_no_in_several_words(self):
        for text in ("예", "네", "Yes", "TRUE", "1", "O", "중복", "있음"):
            self.assertIs(c.parse_bool(text), True, text)
        for text in ("아니오", "아니요", "No", "false", "0", "X", "중복 아님", "없음"):
            self.assertIs(c.parse_bool(text), False, text)
        self.assertIsNone(c.parse_bool(""))
        self.assertIsNone(c.parse_bool("N/A"))
        self.cell_error(c.parse_bool, "글쎄")

    def test_blogs_take_codes_and_the_names_shown_on_screen_in_any_spacing(self):
        self.assertEqual(set(c._BLOG_OF.values()), set(PLATFORMS))
        for code, name in PLATFORM_KO.items():
            with self.subTest(code=code):
                self.assertEqual(c.parse_blogs(name), (code,), "화면에 보이는 이름을 그대로 가져올 수 있어야 한다")
                self.assertEqual(c.parse_blogs(code), (code,))
                self.assertEqual(c.parse_blogs(code.upper()), (code,))
                self.assertEqual(c.parse_blogs(name.replace(" ", "").lower()), (code,))
        self.assertEqual(c.parse_blogs("pages"), ("github_pages",))
        self.assertEqual(c.parse_blogs("네이버 A, 네이버 B"), ("naver_a", "naver_b"))
        self.assertEqual(c.parse_blogs("naver_b;naver_a|naver_b / pages"), ("naver_b", "naver_a", "github_pages"), "겹치는 것은 하나로, 처음 나온 순서")
        self.assertEqual(c.parse_blogs(""), ())
        self.assertEqual(c.parse_blogs(" , ; "), ())
        error = self.cell_error(c.parse_blogs, "네이버 A, 티스토리")
        self.assertIn("티스토리", error.reason)
        self.assertIn("naver_a", error.reason, "고를 수 있는 것을 알려 준다")

    def test_post_type_takes_the_exact_name_or_the_name_without_the_suffix(self):
        for text, expected in (("정보형", "정보형"), ("정보", "정보형"), ("비교", "비교형"), ("문제 해결", "문제 해결형"), ("문제해결형", "문제 해결형"), ("제품·서비스 소개형", "제품·서비스 소개형"),
                               ("장소·업체 정보", "장소·업체 정보형"), ("", None)):
            with self.subTest(text=text):
                self.assertEqual(c.parse_post_type(text), expected)
        for text in ("후기", "경험담", "방문 후기", "info", "형"):
            with self.subTest(text=text):
                self.assertEqual(self.cell_error(c.parse_post_type, text).item, cd.LABELS["post_type"])

    def test_sub_keywords_drop_the_main_keyword_and_repeats_but_keep_everything_else(self):
        self.assertEqual(c.parse_sub_keywords("보일러 에러, 난방비 절약", "보일러 점검"), ("보일러 에러", "난방비 절약"))
        self.assertEqual(c.parse_sub_keywords("보일러 점검, 보일러-점검, 난방비, 난방비", "보일러 점검"), ("난방비",))
        self.assertEqual(c.parse_sub_keywords("a;b|c,d", "x"), ("a", "b", "c", "d"))
        self.assertEqual(c.parse_sub_keywords(" , ;", "x"), ())
        self.assertEqual(c.parse_sub_keywords("C++, C#, C", "c"), ("C++", "C#"), "C 와 C++ 와 C# 은 다른 키워드다")

    def test_the_date_check_gives_the_same_answer_as_the_candidate_for_every_value(self):
        for text in ("2026-11-02", "2000-01-01", "1999-12-31", "2026-02-29", "2024-02-29", "2026-13-01", "2026-00-10", "2026-11-31", "2026-1-2", "26-11-02", "2026/11/02", "20261102",
                     "2026-11-02 ", "٢٠٢٦-١١-٠٢", "2026-11-02T00:00:00Z", "", "오늘", "9999-12-31", "0000-01-01"):
            with self.subTest(text=text):
                try:
                    Candidate.new("주제", "키워드", ("naver_a",), now="2026-11-02T00:00:00Z", search_demand=1, data_date=text)
                    accepted = True
                except AppError:
                    accepted = False
                try:
                    c.check_day(text)
                    mine = True
                except c.CsvCellError:
                    mine = False
                self.assertEqual(mine, accepted, text)
        self.assertEqual(c.check_day("2026-11-02"), "2026-11-02")
        self.assertEqual(self.cell_error(c.check_day, "2026-11-31").reason, "달력에 없는 날짜입니다")
        self.assertIn("2000년", self.cell_error(c.check_day, "1999-12-31").reason)
        self.assertIn("2026-11-02 같은 모양", self.cell_error(c.check_day, "11/2").reason)


class RowFieldsTest(Refused):
    def test_a_full_row_becomes_the_arguments_of_a_candidate_and_builds_one(self):
        text = ("주제,핵심 키워드,보조 키워드,대상 블로그,글 유형,월간 검색 수요,관련 블로그 검색 결과 수,최근 관심도 변화,모바일 비중,계절성,기존 글 중복 여부,블로그 프로필 적합도,"
                "콘텐츠 작성 우선도,키워드 기회도,추천 이유,데이터 조회일\n"
                '겨울 보일러 점검,보일러 점검,"보일러 에러, 난방비",네이버 A,문제 해결,"12,000","34,500",상승,72.5%,"11,12,1,2",아니오,81,76.5,64,겨울 전에 찾는 사람이 늘어요,2026-11-01\n')
        values = fields(text)
        topic, keyword, blogs = values.pop("topic"), values.pop("keyword"), values.pop("blogs")
        self.assertEqual(values, {"sub_keywords": ("보일러 에러", "난방비"), "post_type": "문제 해결형", "search_demand": 12000, "related_blog_results": 34500, "trend": "상승", "mobile_share": 72.5,
                                  "seasonality": (11, 12, 1, 2), "duplicate": False, "profile_fit": 81, "priority": 76.5, "keyword_opportunity": 64, "reason": "겨울 전에 찾는 사람이 늘어요",
                                  "data_date": "2026-11-01"})
        candidate = Candidate.new(topic, keyword, blogs, now="2026-11-02T00:00:00Z", **values)
        self.assertEqual((candidate.duplicate, candidate.seasonality, candidate.search_demand), (False, (1, 2, 11, 12), 12000))

    def test_a_false_value_is_kept_while_a_missing_one_is_dropped(self):
        values = fields(HEAD + ",기존 글 중복 여부,월간 검색 수요,데이터 조회일\n가,나,naver_a,아니오,0,2026-11-01\n")
        self.assertIs(values["duplicate"], False)
        self.assertEqual(values["search_demand"], 0)
        values = fields(HEAD + ",기존 글 중복 여부,월간 검색 수요\n가,나,naver_a,,\n")
        self.assertNotIn("duplicate", values)
        self.assertNotIn("search_demand", values)

    def test_metrics_need_a_date_and_the_message_says_how_to_give_one(self):
        text = HEAD + ",월간 검색 수요\n가,나,naver_a,500\n"
        error = self.cell_error(fields, text)
        self.assertEqual(error.item, cd.LABELS["data_date"])
        self.assertIn("--data-date", error.reason)
        self.assertEqual(fields(text, default_day="2026-11-01")["data_date"], "2026-11-01")

    def test_a_row_without_metrics_needs_no_date_and_a_date_alone_is_kept(self):
        self.assertNotIn("data_date", fields(HEAD + "\n가,나,naver_a\n"))
        self.assertNotIn("data_date", fields(HEAD + ",월간 검색 수요,데이터 조회일\n가,나,naver_a,,\n"))
        self.assertEqual(fields(HEAD + ",데이터 조회일\n가,나,naver_a,2026-11-01\n")["data_date"], "2026-11-01")
        self.assertEqual(fields(HEAD + "\n가,나,naver_a\n", default_day="2026-11-01")["data_date"], "2026-11-01")

    def test_the_date_in_the_row_wins_over_the_default(self):
        text = HEAD + ",월간 검색 수요,데이터 조회일\n가,나,naver_a,5,2026-10-30\n다,라,naver_a,5,\n"
        self.assertEqual(fields(text, 0, default_day="2026-11-01")["data_date"], "2026-10-30")
        self.assertEqual(fields(text, 1, default_day="2026-11-01")["data_date"], "2026-11-01")

    def test_a_badly_formed_date_in_the_row_is_refused_even_when_a_default_exists(self):
        for bad in ("2026/11/01", "11월 1일", "2026-11-31", "20261101"):
            with self.subTest(bad=bad):
                error = self.cell_error(fields, HEAD + f",월간 검색 수요,데이터 조회일\n가,나,naver_a,5,{bad}\n", default_day="2026-11-01")
                self.assertEqual(error.item, cd.LABELS["data_date"])

    def test_the_default_blog_fills_a_missing_or_empty_blog_cell_but_never_replaces_one(self):
        self.assertEqual(fields("주제,핵심 키워드\n가,나\n", default_blogs=("naver_b",))["blogs"], ("naver_b",))
        text = HEAD + "\n가,나,\n다,라,naver_a\n"
        self.assertEqual(fields(text, 0, default_blogs=("naver_b",))["blogs"], ("naver_b",))
        self.assertEqual(fields(text, 1, default_blogs=("naver_b",))["blogs"], ("naver_a",))
        error = self.cell_error(fields, text, 0)
        self.assertEqual(error.item, cd.LABELS["blogs"])
        self.assertIn("--blog", error.reason)

    def test_an_unknown_blog_or_value_names_the_column_and_does_not_stop_the_other_rows(self):
        text = HEAD + ",월간 검색 수요,데이터 조회일\n가,나,티스토리,,\n다,라,naver_a,abc,2026-11-01\n마,바,naver_a,5,2026-11-01\n"
        parsed = table(text)
        self.assertEqual(self.cell_error(c.row_fields, parsed, parsed.records[0]).item, cd.LABELS["blogs"])
        self.assertEqual(self.cell_error(c.row_fields, parsed, parsed.records[1]).item, cd.LABELS["search_demand"])
        self.assertEqual(c.row_fields(parsed, parsed.records[2])["search_demand"], 5)

    def test_cells_are_cleaned_like_one_line_text(self):
        text = HEAD + '\n"겨울\u200b 보일러\n\t점검 ",  키\u200b워드  ,naver_a\n'
        values = fields(text)
        self.assertEqual((values["topic"], values["keyword"]), ("겨울 보일러 점검", "키워드"), "줄바꿈·탭·겹친 공백은 한 칸 공백으로, 보이지 않는 글자는 지운다")

    def test_the_text_columns_are_passed_on_unchanged_for_the_candidate_rules_to_judge(self):
        values = fields(HEAD + ",추천 이유\n상위노출 보장 방법,나,naver_a,확실한 상위노출\n")
        self.assertEqual((values["topic"], values["reason"]), ("상위노출 보장 방법", "확실한 상위노출"))
        with self.assertRaises(AppError) as caught:
            Candidate.new(values.pop("topic"), values.pop("keyword"), values.pop("blogs"), now="2026-11-02T00:00:00Z", **values)
        self.assertEqual(caught.exception.code, "CANDIDATE_INVALID")


class FuzzTest(unittest.TestCase):
    """어떤 입력에도 예상한 오류(CANDIDATE_CSV_INVALID·CsvCellError·CANDIDATE_INVALID) 말고는 예외가 나지 않는다 — 고정한 씨앗으로 만든 무작위 파일 수백 개(항상 같은 입력)."""

    PIECES = ["주제", "핵심 키워드", "대상 블로그", "월간 검색 수요", "데이터 조회일", "naver_a", "네이버 A", "2026-11-01", "12,000", "72.5%", "상승", "11,12", "예", "가", "나다", "keyword", "a b",
              ",", ",,", ";", "\t", '"', '""', "'", "\n", "\r\n", "\r", "\x00", "\x07", "​", "﻿", "ㅤ", "=1+1", "<script>", "{{ x }}", "😀", "ｆｕｌｌ", "é", " ", "   "]

    def text(self, rng):
        header = rng.choice([HEAD, HEAD + ",월간 검색 수요,데이터 조회일", "topic,keyword,blog", "".join(rng.choice(self.PIECES) for _ in range(rng.randint(1, 8))), ""])
        rows = ["".join(rng.choice(self.PIECES) for _ in range(rng.randint(0, 12))) for _ in range(rng.randint(0, 8))]
        return rng.choice(["\n", "\r\n"]).join([header, *rows])

    def run_all(self, data, blogs_given):
        try:
            text = c.decode(data)
        except AppError as error:
            self.assertEqual(error.code, "CANDIDATE_CSV_INVALID")
            return "거절"
        try:
            parsed = c.parse_table(text, blogs_given=blogs_given)
        except AppError as error:
            self.assertEqual(error.code, "CANDIDATE_CSV_INVALID")
            return "거절"
        for record in parsed.records:
            try:
                made = c.row_fields(parsed, record, default_blogs=("naver_a",) if blogs_given else (), default_day="2026-11-01")
                Candidate.new(made.pop("topic"), made.pop("keyword"), made.pop("blogs"), now="2026-11-02T00:00:00Z", **made)
            except c.CsvCellError:
                pass
            except AppError as error:
                self.assertEqual(error.code, "CANDIDATE_INVALID")
        return "읽음"

    def test_random_texts_in_three_encodings_never_raise_anything_unexpected(self):
        import random
        rng, seen = random.Random(20261103), {"거절": 0, "읽음": 0}
        for _ in range(400):
            text = self.text(rng)
            for encoding in ("utf-8", "cp949", "utf-16"):
                try:
                    data = text.encode(encoding)
                except UnicodeEncodeError:
                    continue
                seen[self.run_all(data, rng.random() < 0.5)] += 1
        self.assertGreater(seen["거절"], 50)
        self.assertGreater(seen["읽음"], 50, "시험이 헛돌지 않게 — 읽히는 입력도 충분히 만들어졌다")

    def test_random_bytes_never_raise_anything_unexpected(self):
        import random
        rng = random.Random(7)
        for _ in range(300):
            data = bytes(rng.randrange(256) for _ in range(rng.randint(0, 200)))
            self.run_all(data, rng.random() < 0.5)

    def test_a_valid_file_with_random_rows_always_reads_every_row_or_names_why(self):
        import random
        rng = random.Random(11)
        for _ in range(100):
            rows = [",".join(rng.choice(self.PIECES).replace("\n", " ").replace("\r", " ").replace('"', "") for _ in range(3)) for _ in range(rng.randint(1, 10))]
            parsed = c.parse_table(HEAD + "\n" + "\n".join(rows) + "\n")
            for record in parsed.records:
                try:
                    c.row_fields(parsed, record)
                except c.CsvCellError as error:
                    self.assertTrue(error.item and error.reason)


class SafeCellTest(unittest.TestCase):
    def test_a_cell_that_a_spreadsheet_could_read_as_a_formula_gets_a_leading_apostrophe(self):
        for text in ("=1+1", "+82 로밍", "-5도 한파", "@merge", "\t탭으로 시작", "\r줄 처음으로", "=HYPERLINK(\"http://x\")", "-", "+", "="):
            with self.subTest(text=text):
                self.assertEqual(c.safe_cell(text), "'" + text)

    def test_other_cells_are_left_alone(self):
        for text in ("겨울 보일러", "", " =앞에 공백", "a=b", "1+1", "x-y", "'이미 작은따옴표", "#제목", "5", "한글+영문"):
            with self.subTest(text=text):
                self.assertEqual(c.safe_cell(text), text)

    def test_none_and_numbers_become_text_and_a_negative_number_would_be_prefixed_so_it_is_for_text_cells_only(self):
        self.assertEqual(c.safe_cell(None), "")
        self.assertEqual(c.safe_cell(5), "5")
        self.assertEqual(c.safe_cell(-5), "'-5")

    def test_it_never_changes_the_text_beyond_the_prefix(self):
        text = "=" + "가" * 500
        self.assertEqual(c.safe_cell(text), "'" + text)


if __name__ == "__main__":
    unittest.main()
