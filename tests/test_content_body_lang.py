"""규칙 기반 본문 생성의 한국어 도우미(`content/body_lang.py`) 시험.

지키는 것:
  1) **받침에 맞는 조사**: 받침 있는 낱말 60개·없는 낱말 60개·ㄹ 받침 낱말(으로/로 가 '로')·숫자(영·일·삼·육·칠·팔 은 받침 있음)·영문 약어(엘·엠·엔·알 만 받침)·알려진 영문 낱말을 다섯 조사 쌍 모두로 손으로 센 정답과
     견준다. 정답은 코드의 식이 아니라 낱말마다 사람이 정한 값이다. 확실하게 읽을 수 없는 끝(`C++`·기호)은 틀린 조사를 붙이지 않고 `은(는)`·`(으)로` 꼴로 둔다.
  2) **틀 채우기·목록 잇기**: `{이름}`·`{이름:을/를}` 자리, 한 개·두 개(받침에 맞춘 와/과)·세 개 이상 목록.
  3) **해요체 → 합니다체**: 표(`ENDINGS`)와 규칙 활용(받침 뒤 -아요·-어요)을 바꾸고 `~세요`·`~까요?` 는 두 말투 공통이라 그대로 둔다. 두 번 바꿔도 같다. 끝 부호는 보존한다.
  4) 말투 읽기·`skeleton`·`collapse`. 순수 계산이다(파일·네트워크·시계·난수 모듈을 가져오지 않는다).
"""
import ast
import sys
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import body_bank as bb  # noqa: E402
from chanceblog_desktop.content import body_lang as bl  # noqa: E402

# 낱말 목록(은행의 확인할 항목·상황·몇 가지 흔한 낱말) — 정답은 코드의 식(`% 28`)과 다른 방법(유니코드 분해 — 한글 글자를 초성·중성·종성으로 풀어 종성이 있는지)으로 구한다.
# 손으로 센 값은 `HAND_COUNTED`(낱말 → 받침 있음)에 따로 적어 두 방법이 같은 사실을 말하는지도 본다.
HAND_COUNTED = {"책": True, "밥": True, "집": True, "물": True, "산": True, "강": True, "창문": True, "노트북": True, "서울": True, "연필": True, "나무": False, "하늘": True, "바다": False, "의자": False, "제습기": False,
                "청소기": False, "모니터": False, "카페": False, "서비스": False, "키보드": False, "무선 청소기": False, "예약과 취소 규정": True, "소음 표기 방식": True, "설치 공간": True, "사용자": False, "비교 기준": True}
RIEUL_WORDS = ("물", "말", "길", "칼", "달", "불", "서울", "연필", "거울", "일", "얼굴", "하늘", "주변 시설", "작은 별")
EXTRA_WORDS = ("책", "밥", "집", "물", "말", "길", "칼", "달", "불", "산", "강", "방", "문", "창문", "연필", "서울", "노트북", "나무", "하늘", "바다", "의자", "제습기", "청소기", "노트", "자료", "비교", "정보", "소개",
               "가이드", "서비스", "이미지", "메모", "표", "차이", "카페", "주차", "지도", "무선 청소기", "에어프라이어", "공기청정기", "로봇청소기", "모니터", "스피커", "프린터", "라우터", "소프트웨어", "하드웨어", "컴퓨터",
               "설치", "관리자", "개발자", "운영자", "구매자", "독자", "사용자", "기준표", "점검표", "체크리스트", "공지", "그림", "사진", "음식", "공원", "도서관", "식당", "국물", "이름", "마음", "생각", "얼음", "선물",
               "방문", "설명", "주문", "상품", "시간", "공간", "환경", "성능", "용량", "거울", "일", "얼굴", "칼럼")
PAIRS = (("은", "는"), ("이", "가"), ("을", "를"), ("과", "와"), ("으로", "로"))
DIGIT_FINAL = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True, "8": True, "9": False}
DIGIT_RIEUL = {"1", "7", "8"}
TAIL_RIEUL = chr(0x11AF)


def last_syllable(word):
    return [ch for ch in unicodedata.normalize("NFC", word) if "가" <= ch <= "힣"][-1]


def oracle_final(word):
    """한글 낱말의 마지막 글자에 받침이 있는가 — 유니코드 분해로(초성+중성+종성 = 3 글자)."""
    return len(unicodedata.normalize("NFD", last_syllable(word))) == 3


def oracle_rieul(word):
    decomposed = unicodedata.normalize("NFD", last_syllable(word))
    return len(decomposed) == 3 and decomposed[2] == TAIL_RIEUL


def bank_words():
    found = set(EXTRA_WORDS)
    for banks in bb.BANKS.values():
        for role, items in banks.items():
            for item in items:
                found.update(item if isinstance(item, tuple) else (item,))
    return sorted(found)


def expected(word_final, rieul, pair):
    with_final, without_final = pair
    if not word_final or (pair == ("으로", "로") and rieul):
        return without_final
    return with_final


class ParticleTest(unittest.TestCase):
    def test_every_word_gets_the_right_particle_for_all_five_pairs_by_an_independent_oracle(self):
        words = bank_words()
        self.assertGreaterEqual(len(words), 200)
        with_final = [word for word in words if oracle_final(word)]
        without_final = [word for word in words if not oracle_final(word)]
        self.assertGreaterEqual(len(with_final), 100)
        self.assertGreaterEqual(len(without_final), 100)
        for word in words:
            for pair in PAIRS:
                with self.subTest(word=word, pair=pair):
                    self.assertEqual(bl.particle(word, *pair), expected(oracle_final(word), oracle_rieul(word), pair))

    def test_hand_counted_words_agree_with_both_the_oracle_and_the_code(self):
        for word, final in HAND_COUNTED.items():
            with self.subTest(word=word):
                self.assertEqual(oracle_final(word), final)
                self.assertEqual(bl.particle(word, "은", "는"), "은" if final else "는")
                self.assertEqual(bl.particle(word, "이", "가"), "이" if final else "가")
                self.assertEqual(bl.particle(word, "을", "를"), "을" if final else "를")
        self.assertGreaterEqual(len(HAND_COUNTED), 25)

    def test_the_rieul_words_are_really_rieul_by_the_oracle(self):
        for word in RIEUL_WORDS:
            with self.subTest(word=word):
                self.assertTrue(oracle_rieul(word))

    def test_rieul_final_takes_ro_not_euro(self):
        for word in RIEUL_WORDS:
            with self.subTest(word=word):
                self.assertEqual(bl.particle(word, "으로", "로"), "로")
                self.assertEqual(bl.particle(word, "은", "는"), "은")

    def test_digits_are_read_by_their_korean_sound(self):
        for digit, has_final in DIGIT_FINAL.items():
            for pair in PAIRS:
                with self.subTest(digit=digit, pair=pair):
                    self.assertEqual(bl.particle(digit, *pair), expected(has_final, digit in DIGIT_RIEUL, pair))
        for text, has_final, rieul in (("2026", True, False), ("아이폰 15", False, False), ("RTX 4060", True, False), ("Windows 11", True, True), ("10", True, False), ("100", True, False), ("Python 3", True, False)):
            with self.subTest(text=text):
                self.assertEqual(bl.particle(text, "을", "를"), "을" if has_final else "를")
                self.assertEqual(bl.particle(text, "으로", "로"), "로" if rieul or not has_final else "으로")

    def test_english_acronyms_are_read_by_letter_names(self):
        for word in ("GPU", "SSD", "AI", "PC", "API", "USB", "HDMI", "TV", "OS", "CPU", "NAS", "SaaS", "UI", "UX", "SNS", "ERP"):
            with self.subTest(word=word):
                self.assertEqual(bl.particle(word, "을", "를"), "를", word)
                self.assertEqual(bl.particle(word, "은", "는"), "는", word)
        for word in ("LLM", "RAM", "VRAM", "VPN", "CRM", "DRAM", "SRAM", "BGM", "PWM", "AR", "VR", "XR", "DVR", "URL", "HTML", "SQL", "SSN"):         # 엠·엔·알·엘 로 끝나는 약어(변이 점검이 알 을 빠뜨린 것을 잡으려고 R·L 로 끝나는 약어를 더했다)
            with self.subTest(word=word):
                self.assertEqual(bl.particle(word, "을", "를"), "을", word)

    def test_known_english_words_use_their_korean_reading(self):
        with_final = ("Git", "Notion", "Python", "Google", "Slack", "Samsung", "iPhone", "Excel", "Chrome", "Zoom", "Outlook", "MacBook", "Linkedin", "Tablet", "Laptop")
        without_final = ("GitHub", "Gemini", "ChatGPT", "Windows", "Claude", "Docker", "Linux", "Android", "Kakao", "Naver", "Wi-Fi", "iPad", "Word", "Cloud", "Bluetooth")
        for word in with_final:
            with self.subTest(word=word):
                self.assertEqual(bl.particle(word, "이", "가"), "이", word)
        for word in without_final:
            with self.subTest(word=word):
                self.assertEqual(bl.particle(word, "이", "가"), "가", word)

    def test_trailing_marks_and_spaces_do_not_change_the_reading(self):
        for text, final in (("노트북)", True), ("노트북 ", True), ("의자.", False), ("제습기?", False), ("책상 )", True), ("‘의자’", False)):
            with self.subTest(text=text):
                self.assertEqual(bl.particle(text, "은", "는"), "은" if final else "는")

    def test_an_end_that_cannot_be_read_gets_the_both_forms_and_never_a_wrong_one(self):
        for text in ("C++", "C#", "…", "???", "★", "😀", "", "   "):
            with self.subTest(text=text):
                self.assertIsNone(bl.final_of(text))
                self.assertEqual(bl.particle(text, "은", "는"), "은(는)")
                self.assertEqual(bl.particle(text, "이", "가"), "이(가)")
                self.assertEqual(bl.particle(text, "을", "를"), "을(를)")
                self.assertEqual(bl.particle(text, "과", "와"), "과(와)")
                self.assertEqual(bl.particle(text, "으로", "로"), "(으)로")
                self.assertEqual(bl.particle(text, "이라도", "라도"), "(이)라도")
                self.assertEqual(bl.particle(text, "이에요", "예요"), "(이)에요")

    def test_final_of_is_total_it_never_raises_for_odd_input(self):
        for text in ("", " ", chr(0xFEFF), "한", "a", "Z", "9", "漢字", "ㅋㅋ", "ｱｲｳ", "ＡＩ", "１２３", "a" * 5000, "가" * 5000, "😀한"):
            with self.subTest(text=text[:10]):
                bl.final_of(text)
                bl.particle(text, "은", "는")

    def test_full_width_digits_and_letters_are_read_like_ascii(self):
        self.assertEqual(bl.final_of("１２３"), bl.final_of("123"))
        self.assertEqual(bl.final_of("ＡＩ"), bl.final_of("AI"))
        self.assertEqual(bl.final_of("ＬＬＭ"), bl.final_of("LLM"))


class FillAndListTest(unittest.TestCase):
    def test_plain_and_particle_slots_are_filled(self):
        self.assertEqual(bl.fill("{a}은 {b}예요.", {"a": "책", "b": "의자"}), "책은 의자예요.")
        self.assertEqual(bl.fill("{a:은/는} {b:을/를} 봐요.", {"a": "책", "b": "의자"}), "책은 의자를 봐요.")
        self.assertEqual(bl.fill("{a:은/는} {b:을/를} 봐요.", {"a": "의자", "b": "책"}), "의자는 책을 봐요.")
        self.assertEqual(bl.fill("{a:으로/로} 가요.", {"a": "서울"}), "서울로 가요.")
        self.assertEqual(bl.fill("{a:으로/로} 가요.", {"a": "책상"}), "책상으로 가요.")
        self.assertEqual(bl.fill("{k:이에요/예요}.", {"k": "의자"}), "의자예요.")
        self.assertEqual(bl.fill("{k:이에요/예요}.", {"k": "책상"}), "책상이에요.")
        self.assertEqual(bl.fill("{k:이라면/라면} 좋아요.", {"k": "혼자 사는 집"}), "혼자 사는 집이라면 좋아요.")
        self.assertEqual(bl.fill("{k:이라면/라면} 좋아요.", {"k": "써 보는 분"}), "써 보는 분이라면 좋아요.")
        self.assertEqual(bl.fill("{k:이라도/라도} 같아요.", {"k": "의자"}), "의자라도 같아요.")

    def test_a_missing_name_is_a_key_error_and_slots_of_lists_names_in_order(self):
        self.assertEqual(bl.slots_of("{a} {b:은/는} {a}"), ["a", "b", "a"])
        self.assertEqual(bl.slots_of("자리가 없어요."), [])
        with self.assertRaises(KeyError):
            bl.fill("{missing}", {})
        self.assertEqual(bl.fill("{한글}", {}), "{한글}")                  # 이름은 영문·숫자·밑줄만 — 그 밖의 `{…}` 는 자리가 아니라 글이다

    def test_a_value_with_braces_or_slot_like_text_is_not_filled_again(self):
        self.assertEqual(bl.fill("{a} 예요.", {"a": "{b}"}), "{b} 예요.")

    def test_skeleton_removes_the_slots_and_keeps_the_fixed_text(self):
        self.assertEqual(bl.skeleton("{kw:을/를} 고르는 기준은 {C:이에요/예요}."), " 고르는 기준은 .")

    def test_listing(self):
        self.assertEqual(bl.listing([]), "")
        self.assertEqual(bl.listing(["책"]), "책")
        self.assertEqual(bl.listing(["책", "의자"]), "책과 의자")
        self.assertEqual(bl.listing(["의자", "책"]), "의자와 책")
        self.assertEqual(bl.listing(["책", "의자", "책상"]), "책, 의자, 책상")
        self.assertEqual(bl.listing(["a", "", "b"]), "a와 b")
        self.assertEqual(bl.listing(["C++", "책"]), "C++과(와) 책")

    def test_collapse_merges_a_repeated_or_prefixed_word(self):
        self.assertEqual(bl.collapse("노트북 비교 비교라면 고르세요"), "노트북 비교라면 고르세요")
        self.assertEqual(bl.collapse("점검 점검법"), "점검법")
        self.assertEqual(bl.collapse("정보 정보를 봐요"), "정보를 봐요")
        self.assertEqual(bl.collapse("무선 청소기 비교"), "무선 청소기 비교")
        self.assertEqual(bl.collapse("가 가방"), "가 가방")                     # 한 글자 낱말은 앞 낱말로 보지 않는다

    def test_collapse_does_not_merge_a_word_that_ends_with_a_mark_into_the_next_one(self):
        """앞 낱말 끝에 쉼표 같은 부호가 있으면 목록의 칸 구분이라 합치지 않는다 — 합치면 '설치 공간이, 공간이 좁은 집이라면' 이 '설치 공간이 좁은 집이라면' 이 되어 뜻이 바뀐다.
        뒤 낱말에 부호가 붙은 경우('비교 비교,')는 이전처럼 뒤의 것을 남긴다."""
        self.assertEqual(bl.collapse("혼자 사는 집이라면 놓을 자리와 설치 공간이, 공간이 좁은 집이라면 크기가 중요해요."), "혼자 사는 집이라면 놓을 자리와 설치 공간이, 공간이 좁은 집이라면 크기가 중요해요.")
        self.assertEqual(bl.collapse("정리, 정리를 해요"), "정리, 정리를 해요")
        self.assertEqual(bl.collapse("노트북 비교 비교, 선택"), "노트북 비교, 선택")
        self.assertEqual(bl.collapse("점검 점검법"), "점검법")
        self.assertEqual(bl.tidy("  비교  ,  기준 .  "), "비교, 기준.")


class EndingTest(unittest.TestCase):
    def test_every_table_row_converts_and_keeps_the_end_mark(self):
        for haeyo, hapsyo in bl.ENDINGS:
            for mark in (".", "?", "!", ""):
                with self.subTest(haeyo=haeyo, mark=mark):
                    self.assertEqual(bl.to_hapsyo("그래서 " + haeyo + mark), "그래서 " + hapsyo + mark)

    def test_the_table_has_no_duplicate_rows_and_every_hapsyo_form_is_formal(self):
        keys = [haeyo for haeyo, _hapsyo in bl.ENDINGS]
        self.assertEqual(len(keys), len(set(keys)))
        for haeyo, hapsyo in bl.ENDINGS:
            self.assertTrue(haeyo.endswith("요"), haeyo)
            self.assertTrue(hapsyo.endswith(("니다", "습니다")), hapsyo)

    def test_the_regular_rule_changes_a_after_a_final_consonant_but_not_after_rieul_or_a_vowel(self):
        for haeyo, hapsyo in (("오해하지 않아요.", "오해하지 않습니다."), ("기준으로 삼아요.", "기준으로 삼습니다."), ("자세히 짚어요.", "자세히 짚습니다."), ("밥을 먹어요.", "밥을 먹습니다.")):
            with self.subTest(haeyo=haeyo):
                self.assertEqual(bl.to_hapsyo(haeyo), hapsyo)
        self.assertEqual(bl.to_hapsyo("답을 알아요."), "답을 압니다.")                          # 표
        self.assertEqual(bl.to_hapsyo("아주 예뻐요."), "아주 예뻐요.")                           # 규칙 밖은 그대로 둔다 — 시험(라이브러리 시험)이 이런 끝을 틀에 못 쓰게 한다

    def test_neutral_endings_are_left_alone(self):
        for sentence in ("이렇게 확인해 보세요.", "이것부터 하세요.", "섞지 마세요.", "어디서 확인할까요?", "무엇이 맞을까요?", "도와 주세요.", "확인해 주세요."):
            with self.subTest(sentence=sentence):
                self.assertEqual(bl.to_hapsyo(sentence), sentence)

    def test_conversion_twice_is_the_same_as_once_and_other_styles_pass_through(self):
        for haeyo, _hapsyo in bl.ENDINGS:
            once = bl.to_hapsyo("문장이 " + haeyo + ".")
            self.assertEqual(bl.to_hapsyo(once), once)
        self.assertEqual(bl.in_style("확인해요.", bl.STYLE_HAEYO), "확인해요.")
        self.assertEqual(bl.in_style("확인해요.", bl.STYLE_HAPSYO), "확인합니다.")
        self.assertEqual(bl.in_style("확인해요.", "아무거나"), "확인해요.")

    def test_ending_of_finds_the_longest_table_ending(self):
        self.assertEqual(bl.ending_of("이것은 좋아요."), "좋아요")
        self.assertEqual(bl.ending_of("이것은 아니에요."), "아니에요")
        self.assertIsNone(bl.ending_of("이렇게 해 보세요."))
        self.assertEqual(bl.split_ending("확인해요?!"), ("확인해요", "?!"))
        self.assertEqual(bl.split_ending("끝"), ("끝", ""))


class ToneTest(unittest.TestCase):
    def test_haeyo_is_the_default_and_hapsyo_needs_a_formal_word(self):
        self.assertEqual(bl.style_of_tone(), bl.STYLE_HAEYO)
        self.assertEqual(bl.style_of_tone("", None), bl.STYLE_HAEYO)
        self.assertEqual(bl.style_of_tone("담백하게"), bl.STYLE_HAEYO)
        for text in ("합니다체", "정중한 말투", "전문적이고 격식 있는 문체", "쉬운 존댓말 설명체", "공식적인 안내문", "차분하고 신뢰가 가는"):
            with self.subTest(text=text):
                self.assertEqual(bl.style_of_tone(text), bl.STYLE_HAPSYO)
        for text in ("친근한 해요체", "부드럽고 다정한 말투", "이웃에게 말하듯", "편안한 대화체"):
            with self.subTest(text=text):
                self.assertEqual(bl.style_of_tone(text), bl.STYLE_HAEYO)

    def test_the_first_text_that_says_something_wins_and_haeyo_words_come_first_within_a_text(self):
        self.assertEqual(bl.style_of_tone("", "정중한 말투", "친근한"), bl.STYLE_HAPSYO)
        self.assertEqual(bl.style_of_tone("친근한", "정중한 말투"), bl.STYLE_HAEYO)
        self.assertEqual(bl.style_of_tone("친근하지만 정중한"), bl.STYLE_HAEYO)


class PurityTest(unittest.TestCase):
    def test_the_module_imports_nothing_that_touches_files_the_network_the_clock_or_randomness(self):
        tree = ast.parse((ROOT / "src" / "chanceblog_desktop" / "content" / "body_lang.py").read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0}
        self.assertLessEqual(imported, {"__future__", "re", "unicodedata"})

    def test_the_module_text_has_no_backslash_escape_the_editing_tools_could_turn_into_a_control_character(self):
        text = (ROOT / "src" / "chanceblog_desktop" / "content" / "body_lang.py").read_text(encoding="utf-8")
        self.assertNotIn(chr(92), text)


if __name__ == "__main__":
    unittest.main()
