"""변이 시험으로 드러난 빈틈을 막는 시험 — 후기 전제 판정(content/post_types.py)·참고 주소의 비밀 인자 이름(content/draft_options.py)·CSV 블로그 이름 되풀이 숨김(content/candidate_csv.py).

기대값은 코드에서 베끼지 않고 사람이 쓴 낱말·제목으로 직접 적었다(어간·낱말 목록을 한 항목씩 지워도 시험이 알아채도록, 목록 전체를 이 파일에 따로 둔다).
네트워크·파일 없이 돈다.
"""
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.content import candidate_csv as cc  # noqa: E402
from chanceblog_desktop.content import draft_options as do  # noqa: E402
from chanceblog_desktop.content import post_types as pt  # noqa: E402
from chanceblog_desktop.content.draft_options import DraftOptions  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402

# ---------------------------------------------------------------- 참고 주소: 비밀 인자 이름 ----------------------------------------------------------
VALUE = "correcthorsebatterystaple"                 # 숫자 없는 25자 — 이름이 비밀 이름일 때만 거절되어야 한다


def refused_url(url):
    with unittest.TestCase().assertRaises(AppError) as caught:
        DraftOptions(urls=[url])
    return caught.exception


def accepted_url(url):
    return DraftOptions(urls=[url]).urls


class SecretNamesInUrlTest(unittest.TestCase):
    PART_NAMES = {                                   # 더해진 낱말마다 쓰는 이름의 여러 모양(대소문자·밑줄·붙임표·점은 무시하고 읽는다)
        "passphrase": ("passphrase", "pass_phrase", "Pass-Phrase", "PASS.PHRASE"),
        "authcode": ("authcode", "auth_code", "Auth-Code", "AUTHCODE"),
        "codeverifier": ("codeverifier", "code_verifier", "Code-Verifier"),
        "rlkey": ("rlkey", "rl_key", "RLKEY"),
        "sharekey": ("sharekey", "share_key", "Share-Key"),
        "downloadkey": ("downloadkey", "download_key", "Download-Key"),
    }
    SAME_NAMES = ("reset", "Reset", "magic", "MAGIC", "invite", "Invite")

    def assert_secret_param(self, name, shape="https://example.com/p?{n}={v}"):
        error = refused_url(shape.format(n=name, v=VALUE))
        self.assertEqual(error.code, "DRAFT_OPTION_INVALID", name)
        self.assertEqual(error.slots["항목"], "참고 URL", name)
        self.assertIn("인자", error.slots["이유"], name)

    def test_each_added_secret_name_part_is_refused_in_every_spelling(self):
        for part, names in self.PART_NAMES.items():
            for name in names:
                with self.subTest(part=part, name=name):
                    self.assert_secret_param(name)

    def test_each_added_exact_name_is_refused(self):
        for name in self.SAME_NAMES:
            with self.subTest(name=name):
                self.assert_secret_param(name)

    def test_the_names_are_found_in_a_fragment_a_path_parameter_and_after_an_ampersand(self):
        for name in ("passphrase", "authcode", "code_verifier", "rlkey", "share_key", "download_key", "reset", "magic", "invite"):
            for shape in ("https://example.com/p#{n}={v}", "https://example.com/p;{n}={v}", "https://example.com/p?page=2&{n}={v}"):
                with self.subTest(name=name, shape=shape):
                    self.assert_secret_param(name, shape)

    def test_a_percent_written_equal_sign_is_read_up_to_three_layers(self):
        for name in ("passphrase", "authcode", "codeverifier", "rlkey", "sharekey", "downloadkey", "reset", "magic", "invite"):
            for encoded in ("%3D", "%253D", "%25253D"):
                with self.subTest(name=name, encoded=encoded):
                    self.assert_secret_param(name, "https://example.com/p?{n}" + encoded + "{v}")

    def test_the_same_value_under_a_plain_name_is_accepted(self):
        for name in ("country", "category", "page", "q", "lang"):
            with self.subTest(name=name):
                self.assertEqual(accepted_url(f"https://example.com/p?{name}={VALUE}"), (f"https://example.com/p?{name}={VALUE}",))

    def test_exact_only_names_are_not_refused_when_they_only_contain_the_word(self):
        for name in ("resets", "resetcount", "magical", "magicwand", "invited", "invitation", "inviter"):
            with self.subTest(name=name):
                self.assertEqual(len(accepted_url(f"https://example.com/p?{name}={VALUE}")), 1)

    def test_a_short_or_numeric_value_under_a_secret_name_is_accepted(self):
        for name in ("passphrase", "reset", "magic", "invite", "rlkey", "downloadkey"):
            with self.subTest(name=name):
                self.assertEqual(len(accepted_url(f"https://example.com/p?{name}=12345678901234567890")), 1)
                self.assertEqual(len(accepted_url(f"https://example.com/p?{name}=abc")), 1)

    def test_the_value_with_the_same_name_is_not_refused_without_a_value_that_looks_secret(self):
        self.assertEqual(len(accepted_url("https://example.com/p?passphrase=")), 1)

    def test_forms_decode_the_percent_signs_at_most_three_times(self):
        self.assertEqual(do._forms("a"), ["a"])
        self.assertEqual(do._forms("a%3Db"), ["a%3Db", "a=b"])
        self.assertEqual(do._forms("a%253Db"), ["a%253Db", "a%3Db", "a=b"])
        self.assertEqual(do._forms("a%25253Db"), ["a%25253Db", "a%253Db", "a%3Db", "a=b"])
        self.assertEqual(do._forms("a%2525253Db"), ["a%2525253Db", "a%25253Db", "a%253Db", "a%3Db"])
        self.assertEqual(do._forms("a%252525253Db")[-1], "a%253Db")
        self.assertEqual(len(do._forms("a%252525253Db")), 4)


# ---------------------------------------------------------------- CSV: 블로그 이름 되풀이 숨김 ----------------------------------------------------------
KEY_HEADS = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_", "glpat-", "sk-", "sk_", "pk_", "rk_", "akia", "asia", "aiza", "xox", "xapp-", "eyj", "ya29", "npm_", "hf_", "shpat_")
SECRET_WORDS = ("password", "passwd", "passphrase", "pwd", "token", "secret", "apikey", "credential", "bearer", "privatekey", "accesskey")


class ShowableBlogNameTest(unittest.TestCase):
    def test_plain_short_names_are_shown(self):
        for name in ("naver_c", "naver2", "blogger-en", "naver c", "네이버 C", "블로거", "a", "x" * 24, "A1", "a_b", "a-b", "가나다"):
            with self.subTest(name=name):
                self.assertIs(cc._showable(name), True)

    def test_empty_long_or_odd_character_names_are_hidden(self):
        for name in ("", "x" * 25, "naver.c", "naver!", "a/b", "a,b", "naver@c", "a\tb", "naveré", "<b>"):
            with self.subTest(name=name):
                self.assertIs(cc._showable(name), False)

    def test_the_name_must_match_from_start_to_end(self):
        self.assertIs(cc._showable("naver_c!"), False)
        self.assertIs(cc._showable("!naver_c"), False)
        self.assertIs(cc._showable("naver_c\n"), False)

    def test_a_key_head_followed_by_six_or_more_characters_is_hidden_but_five_is_shown(self):
        for head in KEY_HEADS:
            with self.subTest(head=head):
                self.assertIs(cc._showable(head + "abcdef"), False)
                self.assertIs(cc._showable(head + "abcdefghij"), False)
                self.assertIs(cc._showable(head + "abcde"), True)
                self.assertIs(cc._showable(head), True)
                self.assertIs(cc._showable(head.upper() + "Abcdef"), False)          # 대소문자를 가리지 않는다

    def test_a_key_head_only_counts_at_the_start(self):
        for head in KEY_HEADS:
            with self.subTest(head=head):
                self.assertIs(cc._showable("abcdefghij" + head), True)
                self.assertIs(cc._showable("my " + head + "abcdefg"), True)

    def test_each_secret_word_hides_the_name_in_any_case_and_with_any_separator(self):
        for word in SECRET_WORDS:
            with self.subTest(word=word):
                self.assertIs(cc._showable("my " + word + " x1"), False)
                self.assertIs(cc._showable(word.upper()), False)
                self.assertIs(cc._showable(word), False)
                self.assertIs(cc._showable("x" + word), False)

    def test_separators_inside_a_secret_word_do_not_hide_it(self):
        for word, parts in (("password", ("pass", "word")), ("passwd", ("pass", "wd")), ("passphrase", ("pass", "phrase")), ("apikey", ("api", "key")), ("privatekey", ("private", "key")),
                            ("accesskey", ("access", "key")), ("credential", ("cred", "ential")), ("bearer", ("bea", "rer")), ("secret", ("sec", "ret")), ("token", ("tok", "en"))):
            for separator in (" ", "_", "-"):
                with self.subTest(word=word, separator=separator):
                    self.assertIs(cc._showable("my " + parts[0] + separator + parts[1] + " 1"), False)

    def test_a_secret_word_check_looks_at_the_text_without_separators_not_the_raw_text(self):
        self.assertIs(cc._showable("pass word"), False)
        self.assertIs(cc._showable("Pass_Word"), False)
        self.assertIs(cc._showable("PASS-WORD"), False)
        self.assertIs(cc._showable("pass wor"), True)

    def test_a_key_shape_inside_the_name_is_hidden_even_when_it_does_not_start_the_name(self):
        for name in ("my " + "xo" + "xb-1234567890", "id " + "AK" + "IA" + "ABCDEFGHIJKLMNOP"):
            with self.subTest(name=len(name)):
                self.assertIs(cc._showable(name), False)
        self.assertIs(cc._showable("my " + "xo" + "xb-12345"), True)

    def test_a_name_that_only_looks_a_little_like_a_secret_is_shown(self):
        for name in ("naver_a", "naver b", "pass", "word", "se cre", "api", "key", "blogger-ko", "github", "pages"):
            with self.subTest(name=name):
                self.assertIs(cc._showable(name), True)

    def test_parse_blogs_repeats_a_showable_name_and_hides_the_others(self):
        with self.assertRaises(cc.CsvCellError) as shown:
            cc.parse_blogs("naver_c")
        self.assertIn("「naver_c」", shown.exception.reason)
        self.assertIn("알 수 없는 블로그", shown.exception.reason)
        for hidden in ("gh" + "p_abcdefg", "my password", "naver.c", "x" * 30):
            with self.subTest(hidden=hidden):
                with self.assertRaises(cc.CsvCellError) as caught:
                    cc.parse_blogs(hidden)
                self.assertNotIn(hidden, caught.exception.reason)
                self.assertNotIn("「", caught.exception.reason)
                self.assertIn("되풀이해 보여 드리지 않습니다", caught.exception.reason)


# ---------------------------------------------------------------- 글 유형: 후기 전제 판정 ----------------------------------------------------------------
JAMO_LEADS = "".join(chr(code) for code in range(0x1100, 0x1113))
JAMO_VOWELS = "ᅡᅢᅣᅤᅥᅦᅧᅨᅪᅫᅯᅰ"          # ㅏ ㅐ ㅑ ㅒ ㅓ ㅔ ㅕ ㅖ ㅘ ㅙ ㅝ ㅞ

COGNITIVE = ("알아", "찾아", "살펴", "둘러", "훑어", "짚어", "따져", "헤아려", "곱씹어", "바라", "쳐다", "지켜", "들여다", "내려다", "올려다", "돌아", "돌이켜", "되돌아", "떠올려", "되새겨", "뒤져", "들춰", "넘겨",
             "견줘", "세어", "되짚어")
COGNITIVE_COVERED_BY_A_SUFFIX = ("되돌아", "되짚어")                 # '돌아'·'짚어' 로 끝나는 말이라 따로 지워도 같은 결과다(동등)
NEUTRAL = ("확인", "검색", "비교", "계산", "분석", "검토", "정리", "요약", "조사", "생각", "고민", "상상", "가정", "예상", "추정", "점검", "설명", "소개", "분류", "구분", "나열", "구성", "작성", "제안", "준비", "추측",
           "짐작", "대입", "해석", "판단", "추론", "평가", "번역", "수정", "정의", "조회", "탐색", "정돈", "설계", "계획", "시뮬레이션", "모의", "참고", "참조", "인용", "정렬", "측정", "추산", "환산")
TRIAL_END = ("후기", "결과", "소감", "느낌", "경험", "과정", "이유", "점", "내용", "기록", "이야기", "적", "뒤", "후", "것", "사람", "솔직", "리뷰", "장단점", "단점", "장점", "비교", "기간")
DANGLING = ("사용", "이용", "방문", "구매", "구입", "체험", "경험", "착용", "복용", "장기", "결과", "소감", "느낌", "이야기", "과정", "기록", "일기", "총평", "도전")
# 후기 낱말 바로 뒤(4글자 안)에 오면 그 자체로 '후기를 설명하는 글' 인 낱말(① 갈래) — 사진·순위·점수·구성·광고·차이·형식·통계·구조·랭킹은 진짜 후기 제목의 꼬리로도 흔해서 여기서 뺐다(c2-fix)
ABOUT_TAIL = ("쓰는", "쓰기", "쓸때", "작성", "읽는", "읽기", "가려", "거르", "걸러", "구별", "구분", "판별", "조작", "마케팅", "찍는", "표기", "신뢰", "믿어도", "믿을", "가짜", "허위", "알바", "대행",
              "검증", "규정", "정책", "이벤트", "신청", "무엇", "뜻이", "뜻은", "매겨", "문구", "밝혀야", "밝히는", "단서", "따져", "알아보는")
LISTING_NOUNS = ("사진", "순위", "점수", "구성", "광고", "차이", "형식", "통계", "구조", "랭킹")               # 후기 목록·후기 제목의 꼬리로도 흔한 명사(② 갈래)
EXPLAINING_TAIL = ("고르는", "잡는", "찍는", "매기는", "매겨", "계산", "산정", "정하는", "정해", "구하는", "읽는", "보는", "해석", "분석", "방식", "방법", "요령", "이유", "기준", "무엇",
                   "어떻게", "어떤", "왜", "저작권", "주의", "알아보", "구별", "구분", "가려", "거르", "걸러", "조작", "왜곡", "신뢰", "믿")        # 명사 뒤 6글자 안에 이어지면 설명하는 글이 되는 꼬리
LISTING_TAIL = ("모음", "공개", "포함", "정리", "위주", "공유", "비교", "없음", "아님", "확인", "")          # 명사 뒤에 이어져도(또는 아무것도 없어도) 후기 제목으로 남는 목록 꼬리
TOPIC_END = ("원리", "비밀", "함정", "의미", "일까", "할까", "될까", "이란", "차이는", "차이가", "차이를", "차이점은")     # 후기 낱말이 제목 앞머리(앞에 네 글자 이하)에 있고 그 뒤 20글자 안에 오면 후기 자체를 따지는 글(③ 갈래) — 후기가 장소·경험 낱말 뒤에 오는 '광안리 횟집 방문 후기 다시 갈 만할까' 는 진짜 후기 제목이다(`test_c2_fix_round2`)
PARTICLES = ("으로", "에서", "까지", "부터", "이랑", "하고", "을", "를", "와", "과", "은", "는", "에", "로")
ONE_SYLLABLE = ("해", "가", "써", "타", "사", "와")


class ConnectiveTest(unittest.TestCase):
    def test_connective_is_exactly_the_open_syllables_with_the_twelve_vowels(self):
        expected = {unicodedata.normalize("NFC", lead + vowel) for lead in JAMO_LEADS for vowel in JAMO_VOWELS}
        self.assertEqual(len(expected), 19 * 12)
        self.assertEqual(set(pt._CONNECTIVE), expected)
        self.assertEqual(len(pt._CONNECTIVE), 19 * 12)

    def test_syllables_with_a_final_or_another_vowel_are_not_connective(self):
        for char in "각간갈감갑갓강곡곤공구그기고두리먹함본봤했갔온옴":
            with self.subTest(char=char):
                self.assertNotIn(char, pt._CONNECTIVE)
        for char in "가개갸걔거게겨계과괘궈궤하해햐허헤혀혜와왜워웨":
            with self.subTest(char=char):
                self.assertIn(char, pt._CONNECTIVE)

    def test_a_trial_after_each_kind_of_ending_vowel_is_found(self):
        for stem in ("가", "개", "거", "게", "겨", "과", "궈", "해", "와", "써", "먹어", "다녀", "받아", "돌려", "바꿔", "해줘"):
            with self.subTest(stem=stem):
                self.assertTrue(pt._tried(f"서울맛집{stem}본이유"), stem)
        for stem in ("고", "구", "그", "기", "먹은", "갔", "함"):
            with self.subTest(stem=stem):
                self.assertFalse(pt._tried(f"서울맛집{stem}본이유"), stem)


class TrialWordsTest(unittest.TestCase):
    def kind(self, *texts):
        found = pt.premise_of(*texts)
        return None if found is None else found.kind

    def test_each_trial_ending_alone_makes_a_review_premise(self):
        for title in ("아이와 키즈카페 다녀와 보니", "키즈카페 다녀와봤어요", "키즈카페 다녀와 보았습니다", "캠핑 의자 직접 앉아보고 고른 이유", "치과 상담 받아 본 이유", "치과 상담 받아 본 후기 모음"):
            with self.subTest(title=title):
                self.assertEqual(self.kind(title, "키워드"), "review")

    def test_a_trial_that_ends_the_text_counts(self):
        self.assertEqual(self.kind("치과 상담 받아 본"), "review")
        self.assertEqual(self.kind("치과 상담 받아본"), "review")

    def test_a_trial_with_a_noun_after_it_counts_only_for_the_ending_words(self):
        for word in TRIAL_END:
            with self.subTest(word=word):
                found = pt.premise_of(f"후기 작성 방법 받아 본 {word}", "키워드")
                self.assertIsNotNone(found, word)
                self.assertEqual(found.kind, "review", word)
        for word in ("방법", "가이드", "순서", "목록", "정리표", "자료"):
            with self.subTest(word=word):
                self.assertIsNone(pt.premise_of(f"영화 대본 {word}", "키워드"))
                self.assertIsNone(pt.premise_of(f"치과 상담 받아 본 {word}", "키워드"))

    def test_a_report_book_is_not_a_trial(self):
        self.assertIsNone(pt.premise_of("연구해 보고서 쓰는 법", "키워드"))
        self.assertIsNone(pt.premise_of("분기 실적 정리하고 보고서 올리기", "키워드"))

    def test_a_report_book_alone_after_a_verb_stem_is_not_a_trial(self):
        self.assertFalse(pt._tried("연구해보고서쓰는법"))
        self.assertTrue(pt._tried("연구해보고돌아왔다"))

    def test_a_trial_word_at_the_very_start_is_not_a_trial(self):
        self.assertIsNone(pt.premise_of("본 결과 알려줘", "키워드"))
        self.assertIsNone(pt.premise_of("봤 결과 알려줘", "키워드"))
        self.assertFalse(pt._tried("본결과알려줘"))

    def test_the_trial_look_back_window_is_wide_enough_for_the_longest_stem(self):
        self.assertIsNone(pt.premise_of("알아본 결과 정리 방법", "키워드"))
        self.assertIsNone(pt.premise_of("확인해 본 결과 정리 방법", "키워드"))
        self.assertIsNone(pt.premise_of("가격 시뮬레이션해 본 결과", "키워드"))
        self.assertIsNone(pt.premise_of("수익 시뮬레이션해 본 결과 정리", "키워드"))

    def test_a_noun_ending_that_is_not_an_ending_word_is_not_a_trial(self):
        self.assertIsNone(pt.premise_of("영화 대본 쓰는 법", "키워드"))
        self.assertIsNone(pt.premise_of("서류 제본 방법", "키워드"))

    def test_a_trial_in_an_info_article_still_makes_it_a_review(self):
        self.assertEqual(pt.premise_of("후기 작성 방법 받아 본 과정", "키워드").kind, "review")
        self.assertEqual(pt.premise_of("체험단 신청 방법 직접 받아 본 이유", "키워드").kind, "product")

    def test_an_experience_word_in_an_info_article_still_makes_it_a_premise_without_any_trial(self):
        self.assertEqual(pt.premise_of("후기 작성 방법 내돈내산", "키워드").kind, "product")
        self.assertEqual(pt.premise_of("리뷰 작성 요령 다녀온 곳", "키워드").kind, "visit")

    def test_an_info_article_without_any_trial_or_experience_word_is_no_premise(self):
        for title in ("후기 작성 방법", "후기 작성 방법 정리", "리뷰 작성 요령 모음", "체험단 신청 방법 안내"):
            with self.subTest(title=title):
                self.assertIsNone(pt.premise_of(title, "키워드"))

    def test_a_non_info_text_with_no_premise_word_and_no_trial_is_none(self):
        for title in ("겨울 보일러 점검 순서", "서울 한강 야경 명소", "노트북 추천 비교", "에어컨 청소 순서 정리"):
            with self.subTest(title=title):
                self.assertIsNone(pt.premise_of(title, "키워드"))

    def test_the_fallback_for_a_trial_without_a_premise_word_is_the_review_replacement(self):
        for title in ("치과 상담 받아 본 이유", "아이와 키즈카페 다녀와 보니", "수영장 강습 등록해 보니", "캠핑 의자 앉아보고 고른 이유"):
            with self.subTest(title=title):
                found = pt.premise_of(title, "키워드")
                self.assertEqual((found.kind, found.label_from, found.label_to, found.post_type), ("review", "경험형 후기", "정보형 안내 글", None))


class StemListsTest(unittest.TestCase):
    def test_every_look_up_stem_with_a_trial_ending_is_not_a_trial(self):
        for stem in COGNITIVE:
            with self.subTest(stem=stem):
                self.assertIsNone(pt.premise_of(f"가격 {stem}본 결과", "키워드"), stem)
                self.assertIsNone(pt.premise_of(f"가격 {stem} 본 결과", "키워드"), stem)

    def test_every_neutral_verb_followed_by_a_trial_ending_is_not_a_trial(self):
        for stem in NEUTRAL:
            with self.subTest(stem=stem):
                self.assertIsNone(pt.premise_of(f"가격 {stem}해 본 결과", "키워드"), stem)
                self.assertIsNone(pt.premise_of(f"가격 {stem}해 봤어요", "키워드"), stem)
                self.assertIsNone(pt.premise_of(f"가격 {stem}해 보니", "키워드"), stem)

    def test_the_neutral_verb_alone_without_the_ending_syllable_does_not_cancel(self):
        for stem in NEUTRAL:
            with self.subTest(stem=stem):
                self.assertTrue(pt._tried(f"가격{stem}가본결과"), stem)

    def test_a_look_up_is_cut_only_when_the_stem_ends_the_look_back(self):
        self.assertTrue(pt._cut("알아"))
        self.assertTrue(pt._cut("가격알아"))
        self.assertTrue(pt._cut("가격확인해"))
        self.assertFalse(pt._cut("알아가"))
        self.assertFalse(pt._cut("확인해가"))
        self.assertFalse(pt._cut("확인"))
        self.assertFalse(pt._cut("먹어"))
        self.assertFalse(pt._cut(""))

    def test_a_noun_stem_that_only_starts_with_a_look_up_word_is_not_cut(self):
        self.assertFalse(pt._cut("알아가"))
        self.assertFalse(pt._cut("해확인"))
        self.assertFalse(pt._cut("확인하해"))


class TrialTokenTest(unittest.TestCase):
    def test_the_one_syllable_verbs_are_trial_tokens_but_other_one_syllable_stems_are_not(self):
        for verb in ONE_SYLLABLE:
            with self.subTest(verb=verb):
                self.assertTrue(pt._trial_token(verb + "본"), verb)
                self.assertTrue(pt._trial_token(verb + "봤어요"), verb)
        for noun in ("대", "제", "서", "저", "거", "네", "재"):
            with self.subTest(noun=noun):
                self.assertFalse(pt._trial_token(noun + "본"), noun)

    def test_a_one_syllable_stem_that_is_not_a_verb_is_kept_by_strip_premise(self):
        self.assertEqual(pt.strip_premise("영화 대본 쓰는 법"), "영화 대본 쓰는 법")
        self.assertEqual(pt.strip_premise("서류 제본 방법"), "서류 제본 방법")
        self.assertEqual(pt.strip_premise("서울 와본"), "서울")

    def test_a_two_syllable_stem_is_a_trial_token(self):
        self.assertTrue(pt._trial_token("받아본"))
        self.assertTrue(pt._trial_token("앉아봤어요"))
        self.assertEqual(pt.strip_premise("치과 받아본"), "치과")

    def test_a_stem_that_ends_in_a_closed_syllable_is_not_a_trial_token(self):
        self.assertFalse(pt._trial_token("가격원본"))
        self.assertEqual(pt.strip_premise("가격원본 확인"), "가격원본 확인")

    def test_a_look_up_stem_is_not_a_trial_token(self):
        self.assertFalse(pt._trial_token("알아본"))
        self.assertFalse(pt._trial_token("확인해본"))
        self.assertEqual(pt.strip_premise("가격 알아본"), "가격 알아본")
        self.assertEqual(pt.strip_premise("가격 비교해본"), "가격 비교")                 # '해본' 은 낱말 목록이 지운다

    def test_a_word_that_is_not_a_trial_token_shape_is_false(self):
        for word in ("", "봤어요", "대본", "원본", "치과", "받아", "받아보"):
            with self.subTest(word=word):
                self.assertFalse(pt._trial_token(word))
        self.assertEqual(pt.strip_premise("서울 봤어요"), "서울 봤어요")

    def test_each_trial_ending_is_removed_from_a_title(self):
        for ending in ("봤어요", "보았습니다", "보니", "본", "봐서", "보고", "봤다", "봤고", "봤지만", "보니까"):
            with self.subTest(ending=ending):
                self.assertEqual(pt.strip_premise("치과 받아" + ending), "치과", ending)

    def test_each_ending_word_is_read_together_with_three_more_syllables(self):
        for ending in ("어요", "습니다", "더니", "는데", "다", "고", "지만", "으며", "으니", "서"):
            with self.subTest(ending=ending):
                self.assertEqual(pt.strip_premise("치과 받아봤" + ending + "가나다"), "치과", ending)
                self.assertEqual(pt.strip_premise("치과 받아봤" + ending), "치과", ending)

    def test_four_more_syllables_after_the_ending_are_too_many(self):
        self.assertEqual(pt.strip_premise("치과 받아봤어요가나다라"), "치과 받아봤어요가나다라")
        self.assertEqual(pt.strip_premise("치과 받아봤습니다가나다라"), "치과 받아봤습니다가나다라")

    def test_a_stem_of_seven_syllables_is_read_but_eight_is_not(self):
        self.assertTrue(pt._trial_token("가나다라마바사봤어요"))
        self.assertFalse(pt._trial_token("가나다라마바사아봤어요"))
        self.assertEqual(pt.strip_premise("서울 가나다라마바사봤어요"), "서울")
        self.assertEqual(pt.strip_premise("서울 가나다라마바사아봤어요"), "서울 가나다라마바사아봤어요")


class JoinSplitVerbTest(unittest.TestCase):
    def test_a_spaced_trial_is_joined_and_removed_for_every_ending(self):
        for tail in ("봤어요", "보았습니다", "보니", "본", "봐서", "보고", "봤더니"):
            with self.subTest(tail=tail):
                self.assertEqual(pt.strip_premise("제주 맛집 받아 " + tail), "제주 맛집", tail)

    def test_a_spaced_stem_of_up_to_seven_syllables_is_joined_but_not_longer(self):
        self.assertEqual(pt.strip_premise("가나다라마바사 봤습니다"), "")
        self.assertEqual(pt.strip_premise("가나다라마바사아 봤습니다"), "가나다라마바사아 봤습니다")
        self.assertEqual(pt.strip_premise("가나다라마바 봤습니다"), "")

    def test_the_join_only_starts_at_the_start_of_a_word(self):
        self.assertEqual(pt.strip_premise("신형노트북구매해 봤습니다"), "신형노트북구매해 봤습니다")

    def test_a_report_book_after_a_verb_is_not_joined(self):
        self.assertEqual(pt.strip_premise("연구해 보고서 작성"), "연구해 보고서 작성")

    def test_a_visit_verb_split_by_a_space_is_joined(self):
        self.assertEqual(pt.strip_premise("서울 맛집 다녀 왔어요"), "서울 맛집")
        self.assertEqual(pt.strip_premise("서울 맛집 가 봤어요"), "서울 맛집")
        self.assertEqual(pt.strip_premise("노트북 써 봤습니다"), "노트북")
        self.assertEqual(pt.strip_premise("노트북 사용해 보니"), "노트북")
        self.assertEqual(pt.strip_premise("제주 가 와서"), "제주")

    def test_a_felt_point_goes_with_the_review(self):
        for felt in ("느낀 점", "느낀 것", "느낀 부분", "느낀 바", "느낀", "느꼈던 점", "느꼈던 것", "알게 된 점", "알게 됐던 점", "알게된 점", "알게됐던 점", "깨달은 점", "깨달은 것", "배운 점", "배운 부분",
                     "달라진 점", "달라진 바", "느낀점", "배운점", "달라진점"):
            with self.subTest(felt=felt):
                self.assertEqual(pt.strip_premise("에어컨 써 보고 " + felt), "에어컨", felt)

    def test_a_felt_point_followed_by_more_hangul_is_kept(self):
        self.assertEqual(pt.strip_premise("에어컨 써 보고 느낀 점들"), "에어컨 점들")
        self.assertEqual(pt.strip_premise("에어컨 써 보고 배운 점이"), "에어컨 점이")

    def test_a_felt_point_glued_to_the_next_word_splits_the_words(self):
        self.assertEqual(pt.strip_premise("에어컨배운점,장단점"), "에어컨 장단점")
        self.assertEqual(pt.strip_premise("에어컨느낀점,장단점"), "에어컨 장단점")

    def test_a_duration_glued_to_the_word_before_splits_it(self):
        self.assertEqual(pt.strip_premise("노트북한달사용후기"), "노트북")
        self.assertEqual(pt.strip_premise("노트북 한 달 사용 후기"), "노트북")
        self.assertEqual(pt.strip_premise("노트북 6개월 이용 후기"), "노트북")
        self.assertEqual(pt.strip_premise("노트북2주사용후기"), "노트북")


class DanglingWordsTest(unittest.TestCase):
    def test_a_dangling_action_word_before_a_review_word_is_dropped(self):
        for word in DANGLING:
            with self.subTest(word=word):
                self.assertEqual(pt.strip_premise(f"노트북 {word} 후기"), "노트북", word)
                self.assertEqual(pt.strip_premise(f"노트북 {word}후기"), "노트북", word)

    def test_two_dangling_words_in_a_row_are_both_dropped(self):
        self.assertEqual(pt.strip_premise("노트북 이용 구매 후기"), "노트북")
        self.assertEqual(pt.strip_premise("노트북 사용 결과 후기"), "노트북")

    def test_two_dangling_words_in_a_row_before_a_removed_verb_are_both_dropped(self):
        self.assertEqual(pt.strip_premise("노트북 이용 구매 써봤어요"), "노트북")
        self.assertEqual(pt.strip_premise("노트북 사용 이용 구매 받아본"), "노트북")

    def test_dangling_words_stay_when_nothing_was_removed(self):
        for word in [w for w in DANGLING if w not in ("체험", "소감")]:                # 이 둘은 그 자체가 후기 낱말이라 늘 지워진다
            with self.subTest(word=word):
                self.assertEqual(pt.strip_premise(f"노트북 {word}"), f"노트북 {word}", word)

    def test_a_dangling_word_in_the_middle_stays(self):
        self.assertEqual(pt.strip_premise("노트북 사용 방법 후기"), "노트북 사용 방법")
        self.assertEqual(pt.strip_premise("노트북 결과 비교 후기"), "노트북 결과 비교")


class TrailingParticleTest(unittest.TestCase):
    def test_a_particle_left_before_a_removed_verb_is_cut_for_every_particle(self):
        for particle in PARTICLES:
            with self.subTest(particle=particle):
                self.assertEqual(pt.strip_premise("맛집" + particle + " 다녀와 보니"), "맛집", particle)
                self.assertEqual(pt.strip_premise("서울 맛집" + particle + " 받아봤어요"), "서울 맛집", particle)

    def test_only_the_particle_at_the_very_end_is_cut(self):
        self.assertEqual(pt.strip_premise("에어프라이어로 써 보니"), "에어프라이어")
        self.assertEqual(pt.strip_premise("에어컨을 에어프라이어로 써 보니"), "에어컨을 에어프라이어")
        self.assertEqual(pt.strip_premise("에어컨은 은행에서 은행으로 다녀와 보니"), "에어컨은 은행에서 은행")

    def test_a_particle_is_kept_when_cutting_it_would_leave_one_syllable(self):
        self.assertEqual(pt.strip_premise("집으로 다녀와 보니"), "집으로")
        self.assertEqual(pt.strip_premise("집에서 받아봤어요"), "집에서")
        self.assertEqual(pt.strip_premise("집은 써 보니"), "집은")

    def test_a_particle_is_cut_when_two_syllables_are_left(self):
        self.assertEqual(pt.strip_premise("맛집으로 다녀와 보니"), "맛집")
        self.assertEqual(pt.strip_premise("카페는 써 보니"), "카페")

    def test_the_cut_is_on_the_last_word_only(self):
        self.assertEqual(pt.strip_premise("서울 맛집으로 다녀와 보니"), "서울 맛집")
        self.assertEqual(pt.strip_premise("서울로 가는 맛집으로 다녀와 보니"), "서울로 가는 맛집")

    def test_nothing_is_cut_when_nothing_was_removed(self):
        self.assertEqual(pt.strip_premise("서울 맛집으로"), "서울 맛집으로")
        self.assertEqual(pt.strip_premise("겨울철 난방은 보일러로"), "겨울철 난방은 보일러로")
        self.assertEqual(pt.strip_premise("서울 맛집 사용"), "서울 맛집 사용")

    def test_a_last_word_that_is_entirely_removed_leaves_the_one_before_cut(self):
        self.assertEqual(pt.strip_premise("노트북으로 후기"), "노트북")


class ReviewAboutTest(unittest.TestCase):
    def test_each_word_after_a_review_word_makes_it_an_article_about_reviews(self):
        for word in ABOUT_TAIL:
            with self.subTest(word=word):
                self.assertIsNone(pt.premise_of(f"후기 블로그 {word}", "키워드"), word)
                self.assertIsNone(pt.premise_of("제목", f"리뷰 블로그 {word}"), word)

    def test_each_review_word_in_front_opens_an_article_about_reviews(self):
        for head in ("후기", "리뷰", "체험단", "평점", "별점"):
            with self.subTest(head=head):
                self.assertIsNone(pt.premise_of(f"{head} 블로그 조작 후기", "키워드"), head)
                self.assertIsNone(pt.premise_of(f"{head} 블로그 가려 읽는 법", "키워드"), head)

    def test_a_fake_or_ad_review_is_an_article_about_reviews(self):
        for title in ("광고성 후기", "가짜 후기", "허위 후기", "조작된 후기", "광고성 리뷰", "가짜 리뷰", "허위 리뷰", "조작된 리뷰"):
            with self.subTest(title=title):
                self.assertIsNone(pt.premise_of(title, "키워드"), title)

    def test_a_fake_word_without_a_review_word_after_it_is_no_article_about_reviews(self):
        self.assertEqual(pt.premise_of("가짜 모음 후기", "키워드").kind, "review")
        self.assertEqual(pt.premise_of("광고성 모음 리뷰", "키워드").kind, "review")

    def test_the_gap_between_the_review_word_and_the_clear_word_is_at_most_four_syllables(self):
        gap4, gap5 = "가나다라", "가나다라마"
        self.assertEqual(len(gap4), 4)
        self.assertIsNone(pt.premise_of("후기" + gap4 + "조작", "키워드"))
        self.assertEqual(pt.premise_of("후기" + gap5 + "조작", "키워드").kind, "review")

    # ---- c2-fix: 흔한 명사(사진·순위·점수·구성·광고·차이·형식·통계·구조·랭킹)는 진짜 후기 제목의 꼬리로도 흔하다 — 설명하는 꼬리가 없으면 후기다(앞 판은 후기 낱말 14글자 안에 이 명사만 있어도 설명 글로 보고 정답으로 박아 두었다)
    def test_a_common_noun_after_a_review_word_is_still_a_review_title_without_an_explaining_tail(self):
        for head in ("방문 후기", "구매 후기", "사용 후기", "이용 후기", "체험단 후기", "여행 리뷰"):
            for noun in LISTING_NOUNS:
                for tail in LISTING_TAIL:
                    title = f"{head} {noun} {tail}".strip()
                    with self.subTest(title=title):
                        self.assertIsNotNone(pt.premise_of(title, "키워드"), title)
                        self.assertIsNotNone(pt.premise_of("제목", title), title)

    def test_a_common_noun_with_an_explaining_tail_makes_an_article_about_reviews(self):
        for noun in LISTING_NOUNS:
            for tail in EXPLAINING_TAIL:
                title = f"후기 블로그 {noun} {tail}"
                with self.subTest(title=title):
                    self.assertIsNone(pt.premise_of(title, "키워드"), title)

    def test_the_gaps_of_the_common_noun_rule_are_four_and_six_syllables(self):
        gap4, gap5, mid6, mid7 = "가나다라", "가나다라마", "가나다라마바", "가나다라마바사"
        self.assertIsNone(pt.premise_of("후기" + gap4 + "사진" + mid6 + "방법", "키워드"))
        self.assertEqual(pt.premise_of("후기" + gap5 + "사진" + mid6 + "방법", "키워드").kind, "review")
        self.assertEqual(pt.premise_of("후기" + gap4 + "사진" + mid7 + "방법", "키워드").kind, "review")

    def test_every_review_word_opens_the_common_noun_rule(self):
        for head in ("후기", "리뷰", "체험단", "평점", "별점"):
            with self.subTest(head=head):
                self.assertIsNone(pt.premise_of(f"{head} 사진 고르는 요령", "키워드"), head)
        for head in ("후기", "리뷰", "체험단"):                       # 평점·별점은 후기 전제 낱말이 아니라 (설명 글이 아니어도) 전제가 없다
            with self.subTest(head=head, kind="list"):
                self.assertIsNotNone(pt.premise_of(f"{head} 사진 모음", "키워드"), head)

    def test_a_word_that_explains_the_review_itself_makes_an_article_about_reviews(self):
        for word in TOPIC_END:
            with self.subTest(word=word):
                self.assertIsNone(pt.premise_of(f"후기 블로그 속 이야기 {word}", "키워드"), word)

    def test_every_review_word_opens_the_explaining_ending(self):
        for head in ("후기", "리뷰", "별점", "평점", "체험단"):
            with self.subTest(head=head):
                self.assertIsNone(pt.premise_of(f"{head} 선정 과정의 비밀", "키워드"), head)

    def test_a_question_mark_inside_the_gap_does_not_break_the_explaining_ending(self):
        self.assertIsNone(pt.premise_of("후기 블로그 이야기? 숨은 원리", "키워드"))

    def test_the_gap_of_the_explaining_ending_is_twenty_syllables(self):
        gap20, gap21 = "가나다라마바사아자차카타파하거너더러머버", "가나다라마바사아자차카타파하거너더러머버서"
        self.assertEqual(len(gap20), 20)
        self.assertIsNone(pt.premise_of("후기" + gap20 + "원리", "키워드"))
        self.assertEqual(pt.premise_of("후기" + gap21 + "원리", "키워드").kind, "review")

    def test_a_letter_inside_another_word_is_not_a_sign_of_an_article_about_reviews(self):
        for title, kind in (("방문 후기 따뜻한 분위기", "visit"), ("복용 후기 가려움이 사라졌어요", "review"), ("방문 후기 파란 지붕 카페", "visit"), ("카페 방문 후기 2일까지의 여정", "visit"), ("복용 후기 가려운 곳 사진", "review")):
            with self.subTest(title=title):
                self.assertEqual(pt.premise_of(title, "키워드").kind, kind, title)
        self.assertIsNone(pt.premise_of("체험단이란 무엇일까", "키워드"))

    def test_a_real_review_that_has_none_of_the_words_is_still_a_review(self):
        for title, kind in (("후기 모음", "review"), ("블로그 후기", "review"), ("체험단 후기 모음", "product"), ("리뷰 블로그 모음", "review"), ("후기 블로그 장단점", "review")):
            with self.subTest(title=title):
                self.assertEqual(pt.premise_of(title, "키워드").kind, kind, title)


class StripPremiseGuardsTest(unittest.TestCase):
    def test_a_trial_word_made_only_of_one_token_is_removed(self):
        self.assertEqual(pt.strip_premise("제주 맛집 다녀와보니"), "제주 맛집")
        self.assertEqual(pt.strip_premise("치과 상담 받아본 후기"), "치과 상담")
        self.assertEqual(pt.strip_premise("노트북 구매해본 이유"), "노트북 이유")

    def test_a_removed_word_inside_a_token_leaves_the_rest_and_a_trial_token_alone_is_dropped_whole(self):
        self.assertEqual(pt.strip_premise("청소기써본후기"), "청소기")
        self.assertEqual(pt.strip_premise("노트북구매해본"), "노트북")
        self.assertEqual(pt.strip_premise("노트북구매해본 비교"), "노트북 비교")
        self.assertEqual(pt.strip_premise("노트북 사용 구매해본 비교"), "노트북 사용 비교")

    def test_nothing_changes_for_a_title_with_no_premise_word(self):
        for title in ("겨울 보일러 점검 순서", "서울 한강 야경 명소", "에어컨 청소 순서 정리", "영화 대본 쓰는 법", "가격 알아본 방법"):
            with self.subTest(title=title):
                self.assertEqual(pt.strip_premise(title), title)

    def test_a_title_that_is_only_trial_words_becomes_empty(self):
        for title in ("후기", "써봤어요", "받아봤어요", "다녀와보니", "사용 후기", "직접 받아봤어요 후기"):
            with self.subTest(title=title):
                self.assertEqual(pt.strip_premise(title), "")


if __name__ == "__main__":
    unittest.main()
