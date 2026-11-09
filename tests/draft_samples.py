"""초안 작성 화면 시험이 함께 쓰는 예문 모음(시험 도구 — 시험 모듈이 아니다). 모두 지어낸 문장이고 실제 블로그·후보·글이 아니다.

  · `OPERATOR_C` — 운영자가 '건강 판정 C(의료·효과 단정 위험)' 로 정한 예시 9개(2026-11-06 확인 요청 002 의 답).
  · `CONTROL` — A·B·일반으로 읽혀야 하는 대조 40개(막으면 안 된다).
  · `DAILY` — 즉시·바로·완전히·확실히·무조건·100%·보장 같은 말을 건강과 상관없이 쓴 일상 문장과 증상·질환 낱말이 든 생활 주제 50개(막으면 안 된다).
  · `NORMAL_ADDRESSES`·`NORMAL_FILE_NAMES` — 정상 주소·파일 이름(긴 글번호·상품번호·해시·하이픈이 긴 글 주소) — 키 모양으로 읽히면 안 된다.
  · `NORMAL_MORE` — 블로그·쇼핑·위키·뉴스·문서·지도·검색 같은 정상 주소·글 88개(추적 인자·긴 해시·한글 글 주소·비밀 낱말이 든 글 제목 포함) — 막히면 안 된다(독립 검증 D1 뒤에도 오탐 0).
  · `SECRET_ADDRESSES` — 주소 안에 든 이름 있는 비밀 인자·웹훅·경로 값·`sk-` 키 같은 비밀 주소 `(이름, 글, 비밀 값)` — 막아야 한다. 값은 이름마다 같게 만든 가짜 글자다(실제 키가 아니다).
  · `KNOWN_LIMITS` — 일부러 막지 않는 모양(경로의 무작위 긴 값·이름이 비밀 낱말이 아닌 인자의 긴 값·인자 값 속 쉼표 목록 — 정상 주소와 모양이 같다). 한계 기록(D-312)을 시험이 못박는다.
"""
import hashlib

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def mixed(label, size, extra=""):
    """이름이 같으면 늘 같은 가짜 값 `size` 글자(영문자와 숫자가 모두 든다) — 규칙 모양만 맞춘 글자이고 실제 키·토큰이 아니다. `extra` 는 더 쓸 글자(`_-` 등)."""
    alphabet = _ALPHABET + extra
    digest = b"".join(hashlib.sha256(f"{label}:{count}".encode()).digest() for count in range(size // 32 + 1))
    text = "".join(alphabet[byte % len(alphabet)] for byte in digest[:size])
    return text if any(ch.isdigit() for ch in text) and any(ch.isalpha() for ch in text) and any(ch.isupper() for ch in text) else mixed(label + "+", size, extra)


def hexed(label, size):
    """이름이 같으면 늘 같은 소문자 16진수 `size` 글자(글번호·해시처럼 생긴 정상 값이나 해시 모양 비밀 값에 쓴다)."""
    return (hashlib.sha256(label.encode()).hexdigest() * 2)[:size]



OPERATOR_C = ("영양제로 불면이 바로 치료됩니다", "당뇨 100% 보장", "암 완치 보장", "이 영양제는 피로를 즉시 없애줍니다", "수면제 바로 끊어도 될까",
              "피로를 즉시 줄이는 방법", "자세를 바로 교정하는 책상 설정", "통증을 완전히 없애는 의자 선택법", "당뇨를 무조건 개선하는 식품")

CONTROL = (
    "영양제 바로 알기", "피로할 때 작업환경을 점검하는 방법", "자세가 불편할 때 책상 높이를 확인하는 기준", "영양제를 식후 바로 먹어도 될까", "피로 회복 영양제를 비교하는 기준",
    "당뇨 관련 공식 표시사항 확인하기", "당뇨 환자의 식품 라벨 확인 기준", "당뇨 환자가 무조건 피해야 할 음식", "암 관련 공식 정보 찾는 방법", "암호 관리자 사용법 비교", "암호화 방식 쉽게 이해하기",
    "눈이 피로할 때 모니터 위치 확인하기", "어깨가 아플 때 의자 높이 확인하기", "건강기능식품 표시사항 읽는 법", "비타민 섭취 시간 기록하는 방법", "수면 환경 점검 체크리스트", "체중 관리 앱 비교하는 기준",
    "홍삼 제품 성분표 확인하는 순서", "피로를 줄이는 업무 일정 짜는 방법", "당뇨 환자 식단 기록 방법", "고혈압 약 복용 시간 기록하기", "무선 청소기 고르는 기준", "노트북 거치대 비교하는 방법",
    "강아지 산책 준비물 정리", "겨울 이불 세탁하는 순서", "냉장고 정리 순서", "이사 체크리스트 만드는 방법", "자세히 알아보는 보험 용어", "즉시 사용 가능한 문서 템플릿 모음", "바로가기 아이콘 만드는 방법",
    "완전히 새로운 공간 정리법", "확실히 알아두면 좋은 절약 팁", "반드시 챙길 여행 준비물", "무조건 저장해 두는 스마트폰 단축키", "100% 환불 규정 확인하는 방법", "보장 범위 비교하는 자동차 보험 용어",
    "통증 없는 신발 고르기 전에 발 크기 재는 방법", "두통이 있을 때 확인할 생활 습관 목록", "감기 기운이 있을 때 집에서 확인할 것", "허리가 불편할 때 책상 높이 맞추는 방법",
)

DAILY = (
    "즉시 사용 가능한 문서 템플릿을 모아 봤어요.", "바로가기 아이콘은 바탕화면에서 마우스 오른쪽을 눌러 만들어요.", "완전히 새로운 공간 정리법을 소개해요.", "확실히 알아두면 좋은 절약 팁이에요.",
    "여행 갈 때 반드시 챙길 준비물을 적어요.", "무조건 저장해 두면 좋은 스마트폰 단축키예요.", "100% 환불 규정은 구매처마다 달라서 확인이 필요해요.", "보장 범위가 넓은 자동차 보험을 비교하는 방법이에요.",
    "냉장고는 칸마다 쓰는 순서를 정해 두면 정리가 쉬워요.", "겨울 이불은 햇볕이 좋은 날 말리면 좋아요.", "강아지 산책 가방에는 물과 배변 봉투를 넣어요.", "이사 전에 해야 할 일을 목록으로 만들어요.",
    "무선 청소기는 배터리 사용 시간을 먼저 확인해요.", "노트북 거치대는 높이 조절이 되는 것이 편해요.", "암호 관리자를 쓰면 비밀번호를 하나씩 외우지 않아도 돼요.", "당뇨 보험은 가입 조건을 꼼꼼히 비교해요.",
    "건강 보험 청구는 영수증을 모아 두면 편해요.", "운동 기록 앱은 알림을 켜 두면 꾸준히 쓰기 좋아요.", "의자 높이를 책상에 맞추는 방법을 정리했어요.", "모니터 위치는 눈높이에 맞추면 좋아요.",
    "눈이 피로할 때는 잠깐 먼 곳을 보는 습관이 도움이 된다고 해요.", "수면 환경은 조명과 온도를 먼저 확인해요.", "비타민 섭취 시간은 제품 표시사항을 읽어 보세요.", "체중 관리 앱은 기록하기 쉬운 것이 오래 가요.",
    "감기 기운이 있으면 따뜻한 물을 마시고 쉬어요.", "허리가 불편할 때는 앉는 자세를 점검해 보세요.", "두통이 계속되면 병원과 상담해 보세요.", "약은 처방받은 대로 먹고 임의로 끊지 않아요.",
    "영양제는 식품이 아니라 보충제라는 점을 기억해요.", "홍삼 제품은 성분표를 확인하고 고르세요.", "즉시 환불이 되는지 약관을 읽어 보세요.", "바로 확인할 수 있는 체크리스트를 만들었어요.",
    "반드시 확인해야 할 서류는 신분증이에요.", "확실한 일정은 달력에 적어 둬요.", "완전히 끝난 일은 목록에서 지워요.", "무조건 따라 하기보다 내 상황에 맞게 고르세요.",
    "100% 맞는 방법은 없어서 비교가 필요해요.", "통증이 없는 신발은 발 크기를 재고 고르세요.", "자세히 알아보려면 공식 안내를 읽어 보세요.", "피로가 쌓이지 않게 일정을 나눠 보세요.",
    "당뇨 환자는 식단 기록을 의사와 함께 보세요.", "고혈압 약은 복용 시간을 기록해 두면 좋아요.", "암 관련 정보는 공식 기관에서 찾으세요.", "비교해 보면 가격 차이가 눈에 보여요.",
    "즉각 반응하는 고객센터를 고르세요.", "단번에 끝내려 하지 말고 나눠서 하세요.", "하루 만에 끝나는 일정이 아니에요.", "한 번에 하나씩 정리하세요.", "잠깐 쉬어 가는 시간도 필요해요.", "물을 자주 마시는 습관을 만들어요.",
)

NORMAL_ADDRESSES = (
    "https://blog.naver.com/exampleaaa/223012345678", "https://www.coupang.com/vp/products/1234567890", "https://www.law.go.kr/lsInfoP.do?lsiSeq=123456",
    "https://example.com/files/d41d8cd98f00b204e9800998ecf8427e", "https://example.com/the-quick-brown-fox-jumps-over-the-lazy-dog-1234567890", "https://example.com/sk-hynix-memory-news-2026",
    "https://www.example.go.kr/policy/view.do?seq=20261109", "https://example.com/a1", "blog.naver.com/exampleaaa/223012345678", "www.example.com/a/b/c1234567890123456789012345",
)
NORMAL_FILE_NAMES = ("IMG_20261109_123456_ABCDEFGHIJKLMNOPQRSTUV.jpg", "report_2026_11_09_ABCDEFGHIJKLMNOPQRSTUV123.pdf",
                     "index_2026_11_09_final_version_ABCDEFG123456.html", "backup_2026_11_09_ABCDEFGHIJKLMNO123.py", "IMG_20261109_123456_ABCDEFGHIJKLMNOP.psd", "screen_recording_2026_11_09_ABCDEFGHIJ123.webm",
                     "sales_report_2026_Q4_ABCDEFGHIJKLMN123.xlsm", "DSC_20261109_ABCDEFGHIJKLMNOPQRST1234.tiff")

NORMAL_MORE = (
    "https://m.blog.naver.com/exampleaaa/223012345678",
    "https://blog.naver.com/PostView.naver?blogId=exampleaaa&logNo=223012345678&categoryNo=12&parentCategoryNo=0&viewDate=&currentPage=1&postListTopCurrentPage=1&from=postList",
    "https://search.naver.com/search.naver?where=nexearch&sm=top_hty&fbm=0&ie=utf8&query=%EC%B2%AD%EC%86%8C%EA%B8%B0+%EC%B6%94%EC%B2%9C",
    "https://search.shopping.naver.com/catalog/12345678901?query=%EB%A1%9C%EB%B4%87&NaPm=ct%3Dlm8abcde%7Cci%3D0z70000wvjs51n0v0000%7Ctr%3Dsls%7Chk%3D" + hexed("hk", 40),
    "https://smartstore.naver.com/examplestore/products/1234567890?nl-query=robot&nl-au=" + hexed("au", 20),
    "https://www.coupang.com/vp/products/1234567890?itemId=1234567890123&vendorItemId=12345678901&q=robot+vacuum&itemsCount=36&searchId=" + hexed("sid", 16) + "&rank=0&isAddedCart=",
    "https://www.coupang.com/np/search?q=%EC%B2%AD%EC%86%8C%EA%B8%B0&channel=user&sorter=scoreDesc&listSize=36&rocketAll=false&searchIndexingToken=1=9&backgroundColor=",
    "https://item.gmarket.co.kr/Item?goodscode=1234567890", "https://www.11st.co.kr/products/1234567890?trTypeCd=PW01&trCtgrNo=585021",
    "https://example.tistory.com/entry/한글-제목-테스트", "https://example.tistory.com/123", "https://velog.io/@exampleuser/한글-제목-시리즈-1편", "https://velog.io/@exampleuser/robot-vacuum-review-2026",
    "https://medium.com/@exampleuser/how-to-choose-a-robot-vacuum-" + hexed("m", 12),
    "https://www.notion.so/Task-" + hexed("n1", 32), "https://www.notion.so/한글-제목-" + hexed("n2", 32) + "?pvs=4", "https://www.notion.so/workspace/Risk-Assessment-" + hexed("n3", 32), "https://www.notion.so/제목-" + hexed("n4", 32),
    "https://docs.google.com/document/d/" + mixed("gd", 44) + "/edit?usp=sharing", "https://docs.google.com/spreadsheets/d/" + mixed("gs", 44) + "/edit#gid=0", "https://drive.google.com/file/d/" + mixed("gf", 33) + "/view?usp=sharing",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL" + mixed("yl", 32) + "&index=3&t=42s", "https://youtu.be/dQw4w9WgXcQ?si=" + mixed("si", 22),
    "https://ko.wikipedia.org/wiki/청소기_고르는_방법_(2026)", "https://en.wikipedia.org/wiki/Robotic_vacuum_cleaner#History",
    "https://github.com/exampleuser/example-repo/blob/" + hexed("b", 40) + "/src/app.py#L10-L20", "https://github.com/exampleuser/example-repo/commit/" + hexed("c", 40),
    "https://github.com/exampleuser/example-repo/compare/" + hexed("c1", 40) + "..." + hexed("c2", 40), "https://www.npmjs.com/package/@example/package-name/v/1.2.3",
    "https://www.amazon.com/dp/B07XYZ1234/ref=sr_1_1?crid=2ABCDEFGHIJKL&keywords=robot+vacuum&qid=1700000000&sprefix=robot%2Caps%2C300&sr=8-1",
    "https://www.google.com/maps/place/Seoul/@37.5665,126.9780,15z/data=!3m1!4b1!4m5!3m4!1s0x357ca2f8d64ca1a1:0x1234567890abcdef!8m2", "https://www.instagram.com/p/Cabc123XYZw/?igsh=MWJ1cHBmYXE3Z3k0Mg==",
    "https://www.facebook.com/permalink.php?story_fbid=pfbid02" + mixed("fb", 58) + "&id=100012345678901", "https://twitter.com/exampleuser/status/1712345678901234567?s=20&t=" + mixed("tw", 22),
    "https://www.reddit.com/r/example/comments/abc123/title_of_the_post_with_a_long_slug/", "https://n.news.naver.com/mnews/article/001/0012345678?sid=100",
    "https://www.law.go.kr/법령/개인정보보호법", "https://www.gov.kr/portal/service/serviceInfo/PTR000123456", "https://doi.org/10.1000/xyz123abcdef", "https://arxiv.org/abs/2301.12345v2",
    "https://scholar.google.com/scholar?q=robot+vacuum&hl=ko&as_sdt=0%2C5",
    "https://example.com/page?utm_source=naver&utm_medium=cpc&utm_campaign=2026_spring_sale_event_longname&utm_content=banner_a",
    "https://example.com/?fbclid=IwAR0" + mixed("fc", 40), "https://example.com/?gclid=Cj0KCQiA" + mixed("gc", 40),
    "https://example.com/blog/risk-management-guide-for-2026-and-beyond", "https://example.com/task-proj-management-tools-for-small-teams-2026", "https://example.com/blog/ask-me-anything-" + hexed("a", 32),
    "https://shop.example.com/compare?products=" + hexed("p1", 32) + "," + hexed("p2", 32), "https://www.example.com/news/article," + hexed("ar", 32) + ".html",
    "https://example.com/docs/webhooks/signatures-2026-update-guide-for-developers", "https://docs.github.com/en/webhooks/webhook-events-and-payloads", "https://react.dev/reference/react/hooks",
    "https://example.com/hooks/rules-of-hooks-2026-update", "https://example.com/verify/how-to-check-2026-edition", "https://example.com/reset-password", "https://example.com/invite",
    "https://example.com/code/9f8e7d6c5b4a3f2e", "https://example.com/session/12345678901234567890",
    "https://example.com/api/docs?access_token=YOUR_TOKEN", "https://example.com/api?api_key=1234567", "https://example.com/page?token=123456", "https://example.com/page?key=value", "https://example.com/download?sig=ok",
    "www.coupang.com/vp/products/1234567890?itemId=1234567890123", "shopping.naver.com/product?query=" + hexed("q", 38),
    "blog.naver.com/PostView.naver?blogId=exampleaaa&logNo=223012345678901234567890", "example.co.kr/가나다/" + mixed("k1", 24), "https://example.com/가나다라마바사/" + mixed("k2", 24),
    "[참고](https://example.com/posts/seoul-gangnam-station-exit-4-restaurant-guide-2026-edition)", "(출처: https://example.com/a/b/c1234567890123456789012345)", "<https://example.com/" + hexed("lt", 32) + ">",
    "https://example.com/a?b=c&d=e&f=g#fragment-with-long-text-and-numbers-2026", "https://example.com/#:" + chr(126) + ":text=This%20is%20a%20long%20highlighted%20sentence%20that%20goes%20on%20and%20on",
    "https://xn--9t4b11yi5a.xn--3e0b707e/path/가나다", "http://localhost:3000/api/users/1234567890abcdef1234",
    "https://cdn.example.com/images/2026/11/09/IMG_20261109_123456_ABCDEFGHIJKLMNOPQRSTUV.jpg", "https://mystorageacct1234567890.blob.core.windows.net/container/file.pdf", "https://d1234567890abc.cloudfront.net/path/to/file.js",
    "https://example.com/search?q=api+key+management+best+practices&page=2", "https://example.com/docs/authentication/oauth2-authorization-code-flow-explained", "https://example.com/tag/token-bucket-algorithm",
    "https://example.com/passwords/how-to-create-strong-passwords-2026-guide", "https://example.com/secret-santa-gift-ideas-2026", "https://example.com/blog/2026/11/09/how-i-built-my-secret-garden-in-a-small-apartment",
    "https://stackoverflow.com/questions/12345678/how-to-store-api-keys-securely-in-python", "https://learn.microsoft.com/en-us/azure/active-directory/develop/access-tokens",
    "참고 https://example.com/" + hexed("t1", 32) + ", https://example.org/p/1234567890123456789012345.", "https://naver.me/abcDEF12",
)

SECRET_ADDRESSES = (
    ("인자 access_token", "https://api.example.com/v1/data?access_token=" + hexed("c1", 32), hexed("c1", 32)),
    ("인자 api_key", "https://api.example.com/v1/data?api_key=" + mixed("c2", 40), mixed("c2", 40)),
    ("인자 token", "https://example.com/cb?token=" + mixed("c3", 32), mixed("c3", 32)),
    ("인자 secret(두 번째)", "https://example.com/a?x=1&secret=" + mixed("c4", 40), mixed("c4", 40)),
    ("인자 sig", "https://cdn.example.com/f.png?sig=" + hexed("c5", 64), hexed("c5", 64)),
    ("디스코드 웹훅", "https://discord.com/api/webhooks/112233445566778899/" + mixed("c6", 68, "_-"), mixed("c6", 68, "_-")),
    ("인자 X-Amz-Signature", "https://bucket.s3.amazonaws.com/f.png?X-Amz-Signature=" + hexed("c7", 64), hexed("c7", 64)),
    ("비밀 이름 아래 경로 값(reset)", "https://example.com/reset/" + mixed("c8", 40), mixed("c8", 40)),
    ("빈 사용자 로그인 정보", "redis://:" + mixed("c9", 18) + "@cache.example.com:6379", mixed("c9", 18)),
    ("점 없는 긴 사이트 이름", "xyz://" + mixed("c10", 40), mixed("c10", 40)),
    ("한글에 붙은 긴 값", "https://example.com/가나다" + mixed("c12", 40), mixed("c12", 40)),
    ("주소 안 텔레그램 짧은 꼴", "https://example.com/?b=123456789:" + mixed("c13", 24, "_-"), mixed("c13", 24, "_-")),
    ("주소 안 sk- 20자", "https://example.com/?k=sk-" + mixed("c14", 20), mixed("c14", 20)),
    ("방식 없는 주소 인자", "example.com/api?token=" + hexed("c15", 32), hexed("c15", 32)),
    ("마크다운 링크 속 인자", "[문서](https://api.example.com/d?access_token=" + hexed("c16", 32) + ")", hexed("c16", 32)),
    ("팀즈 웹훅", "https://contoso.webhook.office.com/webhookb2/" + hexed("s1a", 8) + "-1111-2222-3333-" + hexed("s1b", 12) + "@" + hexed("s1c", 8) + "-1111-2222-3333-" + hexed("s1d", 12) + "/IncomingWebhook/" + hexed("s1e", 32) + "/" + hexed("s1f", 8) + "-1111-2222-3333-" + hexed("s1g", 12), hexed("s1e", 32)),
    ("자피어 웹훅", "https://hooks.zapier.com/hooks/catch/1234567/" + mixed("s2", 7) + "/", mixed("s2", 7)),
    ("이프트 웹훅", "https://maker.ifttt.com/trigger/my_event/with/key/" + mixed("s3", 22), mixed("s3", 22)),
    ("그 밖의 hooks 경로", "https://chat.example.com/hooks/" + mixed("s4", 26), mixed("s4", 26)),
    ("글자 바로 뒤의 sk-proj-", "https://example.com/abc" + "sk-" + "proj-" + mixed("s5", 60, "_-"), mixed("s5", 60, "_-")),
    ("글자 바로 뒤의 sk-ant-", "https://example.com/p/x" + "sk-" + "ant-api03-" + mixed("s6", 93, "_-"), mixed("s6", 93, "_-")),
    ("글자 바로 뒤의 sk-or-", "https://example.com/p/y" + "sk-" + "or-v1-" + hexed("s7", 64), hexed("s7", 64)),
    ("글자 바로 뒤의 구형 sk- 48", "https://example.com/p/z" + "sk-" + mixed("s7b", 48), mixed("s7b", 48)),
    ("디스코드 v10 웹훅", "https://discordapp.com/api/v10/webhooks/112233445566778899/" + mixed("s8", 68, "_-") + "?wait=true", mixed("s8", 68, "_-")),
    ("인자 secret_key", "https://example.com/x?secret_key=" + mixed("s9", 20), mixed("s9", 20)),
    ("인자 client_secret", "https://example.com/oauth?client_id=1234&client_secret=" + mixed("s10", 24), mixed("s10", 24)),
    ("인자 password", "https://example.com/login?user=a&password=" + mixed("s11", 18), mixed("s11", 18)),
    ("조각 access_token", "https://example.com/cb#access_token=" + mixed("s12", 30) + "&token_type=bearer", mixed("s12", 30)),
    ("세미콜론 인자", "https://example.com/p;token=" + mixed("s13", 24), mixed("s13", 24)),
    ("퍼센트로 쓴 등호", "https://example.com/x?token%3D" + mixed("s14", 24), mixed("s14", 24)),
    ("두 겹 퍼센트 등호", "https://example.com/x?token%253D" + mixed("s15", 24), mixed("s15", 24)),
    ("데이터베이스 주소", "postgres://dbuser:" + mixed("s16", 12) + "@db.example.com:5432/app", mixed("s16", 12)),
    ("인자 apiKey", "https://example.com/x?apiKey=" + mixed("s17", 30), mixed("s17", 30)),
    ("인자 sessionid", "https://example.com/x?sessionid=" + mixed("s18", 32), mixed("s18", 32)),
    ("인자 Signature", "https://example.com/x?Signature=" + mixed("s19", 40), mixed("s19", 40)),
    ("방식 없는 api 주소", "api.example.com/v1/x?api_key=" + mixed("s20", 32), mixed("s20", 32)),
    ("꺾쇠로 감싼 주소", "<https://example.com/x?token=" + mixed("s21", 24) + ">", mixed("s21", 24)),
    ("인자 key", "https://maps.example.com/embed?key=" + mixed("s22", 39), mixed("s22", 39)),
    ("경로 끝에 쉼표로 이어 붙은 긴 해시", "https://example.com/page," + hexed("c11", 32), hexed("c11", 32)),
)

KNOWN_LIMITS = (
    ("경로의 무작위 긴 값", "https://example.com/p/" + mixed("l1", 40)),
    ("이름이 비밀 낱말이 아닌 인자의 긴 값", "https://example.com/p?data=" + mixed("l2", 40)),
    ("인자 값 속 쉼표 목록의 해시(상품 번호 목록과 모양이 같다)", "https://shop.example.com/compare?ids=" + hexed("l3", 32) + "," + hexed("l4", 32)),
)
