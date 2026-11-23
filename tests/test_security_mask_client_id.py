"""`?client_id=값` 주소 인자도 가린다 — AS-S1 참고-9(결정 D-612).

감사: 가리기가 이름으로 아는 주소 인자(`_QUERY_NAMES`)에 `client_id` 가 없었다. Unsplash 는 Access Key 를 `client_id` 인자로 받으므로(이 앱의 이미지 공급자 `access_key` 칸) 앞으로 호출 주소를 기록하는 코드가 들어오면
그 주소의 키가 새는 길이다(헤더 `Authorization: Client-ID …` 는 이미 가려진다). 지금은 네트워크 호출이 없어 닿지 않지만 이름만 더해 길을 미리 닫는다.
지키는 것: ① `client_id`(`client-id`·`clientid`·대소문자 무시) 인자의 값이 `mask`·`safe_detail` 에서 가려지고 다른 인자는 그대로다 ② 이름이 비슷한 다른 인자(`client_identifier=`·`client=`)는 건드리지 않는다
③ 알려진 오탐 — OAuth 의 `client_id` 는 비밀이 아니지만 값만 가려지고 이름은 남는다(가리는 쪽으로 틀린다). 가짜 키는 `CANARY_` 로 시작하는 조립 문자열이다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.security import mask  # noqa: E402

KEY = "CANARY_" + "unsplash" + "AccessKey" + "0123456789" + "abcdefXYZ"
MARK = "[가림: 주소 인자]"


class ClientIdQueryTest(unittest.TestCase):
    def urls(self):
        return {
            "맨 앞 인자": "https://api.example.test/photos?client_id={k}",
            "뒤쪽 인자": "https://api.example.test/photos?page=2&client_id={k}&per_page=3",
            "대문자": "https://api.example.test/photos?CLIENT_ID={k}&page=2",
            "붙임표": "https://api.example.test/photos?client-id={k}",
            "밑줄 없음": "https://api.example.test/photos?clientid={k}",
            "세미콜론 구분": "https://api.example.test/photos?a=1;client_id={k}",
            "기록 문장 속": "GET https://api.example.test/photos?client_id={k} 가 429 로 끝났다",
        }

    def test_the_value_of_a_client_id_argument_is_masked_by_both_entry_points_and_the_name_stays(self):
        for label, template in self.urls().items():
            text = template.format(k=KEY)
            for function in (mask.mask, mask.safe_detail):
                with self.subTest(label=label, function=function.__name__):
                    shown = function(text)
                    self.assertNotIn(KEY, shown)
                    self.assertNotIn("0123456789abcdef", shown)
                    self.assertIn(MARK, shown)
                    self.assertRegex(shown.lower(), r"client[_-]?id=\[가림")

    def test_the_other_arguments_and_the_surrounding_text_are_left_alone(self):
        shown = mask.mask("https://api.example.test/photos?page=2&client_id=" + KEY + "&per_page=3")
        self.assertEqual(shown, "https://api.example.test/photos?page=2&client_id=" + MARK + "&per_page=3")
        self.assertEqual(mask.mask("https://api.example.test/a?client=abc&client_identifier=def&page=2"), "https://api.example.test/a?client=abc&client_identifier=def&page=2")

    def test_masking_twice_changes_nothing_and_the_older_names_still_work(self):
        once = mask.mask("https://x.test/p?client_id=" + KEY + "&api_key=" + KEY)
        self.assertEqual(mask.mask(once), once)
        self.assertNotIn(KEY, once)
        self.assertEqual(once.count(MARK), 2)

    def test_the_name_list_names_client_id_and_keeps_every_older_name(self):
        for name in ("token", "key", "client_secret", "client-secret", "api_key", "password", "signature", "x-api-key", "jwt", "access_token", "client_id", "client-id", "clientid"):
            with self.subTest(name=name):
                self.assertRegex("?" + name + "=", "(?i)" + "(?:" + mask._QUERY_NAMES + ")=")


if __name__ == "__main__":
    unittest.main()
