"""가리기 규칙(`security/mask.py`) 증거 시험의 입력표(시험 도구 — 시험 모듈이 아니다). PCSEC1 H1.

보안 조사(`secaudit`, 2026-11-11)의 적대적 입력 163건(A01–I12)을 **그대로** 옮겼다: 운영자 목록(Authorization·serviceKey·api_key·access/refresh token·Cookie·URL 질의·URL 사용자 정보)을
여러 모양으로 쓴 입력에서 가짜 비밀이 출력에 남는지 본다. 가짜 비밀은 전부 `CANARY_<라벨>_<해시 16진수>` 로 **실행 중에 만든다**(저장소 비밀 스캐너가 소스 글자를 훑으므로 키 모양 글을 한 덩어리로 쓰지 않는다).
눈에 안 보이거나 헷갈리는 글자(폭 없는 공백·키릴 문자·전각 글자·글자 방향 덮어쓰기 …)는 소스에 직접 쓰지 않고 `chr()` 로 만든다.

범위(scope):
  · `list`  — 운영자 목록 항목(Authorization·serviceKey·api_key·access/refresh token·Cookie·URL 질의·URL 사용자 정보) — **새는 것 0** 이어야 한다.
  · `adv`   — 고의 눈속임(키릴·전각·퍼센트 이름, 이스케이프 JSON, base64 로 감쌈, 쪼갠 값 …) — 목표는 0.
  · `extra` — 목록 밖의 알려진 모양(다른 나라 API 의 `authKey`·`crtfc_key`·키 모양 글) — 가능한 만큼(목표 0).
  · `limit` — **알려진 한계**: 이름 표지가 없어(경로 속 값·라벨 없는 값) 모양만으로는 정상 글과 가를 수 없는 것 — 일부러 가리지 않으며 시험이 그 사실을 못박는다(오탐 표의 64자 16진수 해시가 가려지면 안 되기 때문이다).
"""
import base64
import hashlib
import urllib.parse
from collections import namedtuple

Case = namedtuple("Case", "cid cat scope desc template values")

ZWSP, NBSP, RTL, CYR_A, FW_EQ, DOTTED_I, LONE_SURROGATE = (chr(code) for code in (0x200B, 0x00A0, 0x202E, 0x0430, 0xFF1D, 0x0130, 0xD800))
SCOPES = ("list", "adv", "extra", "limit")


def sec(label, size=20):
    """가짜 비밀 — CANARY 로 시작하고 뒤는 라벨에서 계산한 16진수."""
    return f"CANARY_{label}_" + hashlib.sha256(("e2:" + label).encode()).hexdigest()[:size]


def hex64(label):
    return hashlib.sha256(("e2hex:" + label).encode()).hexdigest()           # 64자 16진수(공공데이터 서비스 키 모양) — CANARY 문구에서 계산한 값


def b64(text):
    return base64.b64encode(text.encode()).decode()


def b64url(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def fullwidth(text):
    """ASCII 글자를 전각 글자로(`api_key` → 전각 영문·밑줄)."""
    return "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= chr(0x7E) else ch for ch in text)


def build_cases():
    cases = []

    def case(cid, cat, scope, desc, template, **values):
        """template 안의 {이름} 을 values 로 채운다. values 의 모든 값이 '숨겨져야 하는 비밀'이다."""
        assert scope in SCOPES, scope
        cases.append(Case(cid, cat, scope, desc, template, values))

    # ---- A. Authorization 헤더 ---------------------------------------------------------------------------------------------------
    v = sec("AUTH")
    case("A01", "Authorization", "list", "Bearer 기본", "Authorization: Bearer {v}", v=v)
    case("A02", "Authorization", "list", "소문자 헤더·bearer", "authorization: bearer {v}", v=v)
    case("A03", "Authorization", "list", "대문자 AUTHORIZATION·BEARER", "AUTHORIZATION: BEARER {v}", v=v)
    case("A04", "Authorization", "list", "콜론 뒤 공백 없음", "Authorization:Bearer {v}", v=v)
    case("A05", "Authorization", "list", "탭 구분", "Authorization: Bearer\t{v}", v=v)
    case("A06", "Authorization", "list", "공백 여러 칸", "Authorization:   Bearer     {v}", v=v)
    case("A07", "Authorization", "list", "JSON 헤더 묶음", '{{"Authorization": "Bearer {v}", "Accept": "application/json"}}', v=v)
    case("A08", "Authorization", "list", "파이썬 repr 헤더", "{{'Authorization': 'Bearer {v}'}}", v=v)
    case("A09", "Authorization", "list", "curl -H", 'curl -H "Authorization: Bearer {v}" https://example.invalid/x', v=v)
    case("A10", "Authorization", "list", "Basic(긴 base64, 대문자·숫자 포함)", "Authorization: Basic {b}", b=b64("CANARY_USER_01:CANARY_PASS_" + hashlib.sha256(b"e2basic").hexdigest()[:12]))
    case("A11", "Authorization", "list", "Basic(짧은 자격: bob:pw1)", "Authorization: Basic {b}", b=b64("bob:pw1"))
    case("A12", "Authorization", "list", "Token 스킴(DRF 방식)", "Authorization: Token {v}", v=v)
    case("A13", "Authorization", "list", "token 스킴(GitHub 방식, 소문자)", "authorization: token {v}", v=v)
    case("A14", "Authorization", "list", "ApiKey 스킴", "Authorization: ApiKey {v}", v=v)
    case("A15", "Authorization", "list", "key= 스킴(구글 방식)", "Authorization: key={v}", v=v)
    case("A16", "Authorization", "list", "GoogleLogin auth=", "Authorization: GoogleLogin auth={v}", v=v)
    case("A17", "Authorization", "list", "OAuth 1.0 헤더", 'Authorization: OAuth oauth_consumer_key="x", oauth_token="{v}", oauth_signature="y"', v=v)
    case("A18", "Authorization", "list", "AWS4 서명 헤더", "Authorization: AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261111/us-east-1/s3/aws4_request, SignedHeaders=host, Signature={h}", h=hex64("A18"))
    case("A19", "Authorization", "list", "스킴 없는 값", "Authorization: {v}", v=v)
    case("A20", "Authorization", "list", "Proxy-Authorization Basic", "Proxy-Authorization: Basic {b}", b=b64("CANARY_PROXY_USER:CANARY_PROXY_PASS_" + hashlib.sha256(b"e2proxy").hexdigest()[:10]))
    case("A21", "Authorization", "list", "줄 접기(다음 줄에 이어짐)", "Authorization: Bearer\r\n    {v}", v=v)
    case("A22", "Authorization", "list", "짧은 Bearer(8자)", "Authorization: Bearer {v}", v="CANARY_B")
    case("A23", "Authorization", "list", "등호 구분", "Authorization = Bearer {v}", v=v)
    case("A24", "Authorization", "list", "따옴표 없는 JSON 한 줄", '"authorization":"bearer {v}"', v=v)
    case("A25", "Authorization", "list", "여러 헤더 줄 사이", "GET /x HTTP/1.1\nHost: example.invalid\nAuthorization: Bearer {v}\nAccept: */*\n", v=v)
    case("A26", "Authorization", "list", "퍼센트 인코딩된 헤더 줄", "Authorization%3A%20Bearer%20{v}", v=v)
    case("A27", "Authorization", "list", "Bearer + NBSP", "Authorization: Bearer" + NBSP + "{v}", v=v)
    case("A28", "Authorization", "list", "Bearer 토큰에 점·슬래시·물결표", "Authorization: Bearer {v}", v="CANARY_TILDE." + chr(0x7E) + "/+=_" + hashlib.sha256(b"e2tilde").hexdigest()[:16])
    case("A29", "Authorization", "list", "X-Naver-Client-Secret 헤더(10자 비밀)", "X-Naver-Client-Secret: {v}", v="CANARY_Ns01")
    case("A30", "Authorization", "list", "X-NCP-APIGW-API-KEY 헤더", "X-NCP-APIGW-API-KEY: {v}", v=sec("NCPKEY"))

    # ---- B. serviceKey(공공데이터 API) -------------------------------------------------------------------------------------------
    h = hex64("SK1")
    case("B01", "serviceKey", "list", "질의 serviceKey=(64자 16진수)", "https://apis.data.go.kr/1234/getX?serviceKey={v}&pageNo=1&numOfRows=10", v=h)
    case("B02", "serviceKey", "list", "질의 ServiceKey=", "https://apis.data.go.kr/1234/getX?ServiceKey={v}&pageNo=1", v=h)
    case("B03", "serviceKey", "list", "질의 &servicekey=(소문자)", "https://apis.data.go.kr/1234/getX?pageNo=1&servicekey={v}", v=h)
    case("B04", "serviceKey", "list", "질의 SERVICEKEY=(대문자)", "https://apis.data.go.kr/1234/getX?SERVICEKEY={v}", v=h)
    kb64 = b64("CANARY_DECODING_KEY_" + hashlib.sha256(b"e2dk").hexdigest()[:28] + "++//==")
    case("B05", "serviceKey", "list", "질의 serviceKey=(디코딩 키: + / = 포함 base64)", "https://apis.data.go.kr/x?serviceKey={v}&a=1", v=kb64)
    case("B06", "serviceKey", "list", "질의 serviceKey=(인코딩 키: %2B %2F %3D)", "https://apis.data.go.kr/x?serviceKey={v}&a=1", v=urllib.parse.quote(kb64, safe=""))
    case("B07", "serviceKey", "list", 'JSON {"serviceKey": ...}', '{{"serviceKey": "{v}"}}', v=h)
    case("B08", "serviceKey", "list", "파이썬 serviceKey='...'", "params = dict(serviceKey='{v}', pageNo=1)", v=h)
    case("B09", "serviceKey", "list", "service_key= 환경변수식", "SERVICE_KEY={v}", v=h)
    case("B10", "serviceKey", "list", "serviceKey: 헤더 모양", "serviceKey: {v}", v=h)
    case("B11", "serviceKey", "list", "requests 예외 문구(재시도 초과)", "HTTPSConnectionPool(host='apis.data.go.kr', port=443): Max retries exceeded with url: /1234/getX?serviceKey={v}&pageNo=1 (Caused by NewConnectionError('x'))", v=h)
    case("B12", "serviceKey", "list", "XML <serviceKey>", "<serviceKey>{v}</serviceKey>", v=h)
    case("B13", "serviceKey", "list", "세미콜론 구분 ;serviceKey=", "https://x/y;serviceKey={v};z=1", v=h)
    case("B14", "serviceKey", "list", "공공데이터 키 + 따옴표 안 url", "url = \"https://apis.data.go.kr/x?serviceKey={v}\"", v=h)
    case("B15", "serviceKey", "extra", "authKey= (다른 한국 API)", "https://x/y?authKey={v}&a=1", v=h)
    case("B16", "serviceKey", "extra", "crtfc_key= (DART)", "https://opendart.fss.or.kr/api/x.json?crtfc_key={v}", v=hex64("B16"))
    case("B17", "serviceKey", "extra", "apiKey= (KOSIS 등)", "https://kosis.kr/openapi/x?apiKey={v}&format=json", v=h)
    case("B18", "serviceKey", "extra", "key= 만 있는 질의", "https://x/y?key={v}", v=h)
    case("B19", "serviceKey", "extra", "appkey= 질의", "https://x/y?appkey={v}", v=h)
    case("B20", "serviceKey", "extra", "secretKey= 질의", "https://x/y?secretKey={v}", v=h)

    # ---- C. api_key ----------------------------------------------------------------------------------------------------------------
    v = sec("APIK")
    rows = [
        ("질의 ?api_key=", "https://x/y?api_key={v}&a=1", "list"), ("질의 ?apikey=", "https://x/y?apikey={v}", "list"), ("질의 ?api-key=", "https://x/y?api-key={v}", "list"),
        ("질의 ?API_KEY=", "https://x/y?API_KEY={v}", "list"), ("헤더 x-api-key:", "x-api-key: {v}", "list"), ("헤더 X-API-KEY:", "X-API-KEY: {v}", "list"),
        ('JSON "api_key"', '{{"api_key": "{v}"}}', "list"), ("파이썬 api_key = '…'", "api_key = '{v}'", "list"), ("camelCase apiKey:", "apiKey: {v}", "list"),
        ("JSON apiKey", '{{"apiKey":"{v}"}}', "list"), ("x-goog-api-key", "x-goog-api-key: {v}", "list"), ("질의 ?key=", "https://x/y?key={v}", "list"),
        ("질의 &key=", "https://x/y?a=1&key={v}", "list"), ("본문 속 Key=", "request failed Key={v} retry", "list"), ("환경 변수 GEMINI_API_KEY=", "GEMINI_API_KEY={v}", "list"),
        ("YAML api_key:", "api_key: {v}", "list"), ("TOML api_key = \"…\"", 'api_key = "{v}"', "list"), ("명령줄 --api-key=", "tool --api-key={v} run", "list"),
        ("명령줄 --api-key 값(공백)", "tool --api-key {v} run", "list"), ("export TOKEN=", "export TOKEN={v}", "list"), ("XML <api_key>", "<api_key>{v}</api_key>", "list"),
        ("HTML data-token", '<div data-token="{v}">', "list"), ("client_secret= 폼 본문", "grant_type=client_credentials&client_id=abc&client_secret={v}", "list"),
        ("clientSecret: ", "clientSecret: {v}", "list"), ("경로 속 키(이름 없음)", "https://x/v1/{v}/data", "limit"), ("Naver client secret 라벨 없는 한 줄", "naver secret value {v}", "limit"),
        ("INI 섹션", "[naver]\napi_key={v}\n", "list"),
    ]
    for index, (desc, template, scope) in enumerate(rows, start=1):
        case(f"C{index:02d}", "api_key", scope, desc, template, v=v)

    # ---- D. access_token / refresh_token ------------------------------------------------------------------------------------------
    v = sec("TOK")
    rows = [
        ("질의 ?access_token=", "https://x/y?access_token={v}"), ("질의 &access_token=", "https://x/y?a=1&access_token={v}"), ("폼 본문 access_token=", "access_token={v}&token_type=bearer"),
        ("JSON access_token", '{{"access_token": "{v}", "expires_in": 3599}}'), ("파이썬 'access_token'", "{{'access_token': '{v}'}}"), ("refresh_token= 폼 본문", "refresh_token={v}"),
        ("grant_type=refresh_token&refresh_token=", "grant_type=refresh_token&refresh_token={v}&client_id=x"), ("JSON refresh_token", '{{"refresh_token":"{v}"}}'),
        ("camelCase refreshToken:", "refreshToken: {v}"), ("camelCase accessToken=", "accessToken={v}"), ("id_token=", "id_token={v}"), ("token=", "token={v}"),
        ("헤더 Access-Token:", "Access-Token: {v}"), ("헤더 X-Access-Token:", "X-Access-Token: {v}"), ("조각 #access_token= (URL 조각)", "https://x/cb#access_token={v}&state=1"),
        ("짧은 값 access_token=abc123", "access_token=CANARY"), ("OAuth 응답 줄바꿈 JSON", '{{\n  "access_token": "{v}",\n  "refresh_token": "{v}"\n}}'),
        ("퍼센트 인코딩 이름 access%5Ftoken=", "access%5Ftoken={v}"), ("대시 이름 access-token=", "access-token={v}"), ("점 이름 oauth.access_token=", "oauth.access_token={v}"),
    ]
    for index, (desc, template) in enumerate(rows, start=1):
        case(f"D{index:02d}", "access/refresh_token", "list", desc, template, v=v)
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + b64url('{"sub":"CANARY_JWT_SUBJECT_0001"}') + "." + b64url("CANARY_JWT_SIGNATURE_" + hashlib.sha256(b"e2jwt").hexdigest()[:20])
    case("D21", "access/refresh_token", "extra", "JWT 모양(라벨 없음)", "got {v} from server", v=jwt)
    case("D22", "access/refresh_token", "extra", "구글 access token 모양 ya29.", "token is {v}", v="ya29." + "CANARY_Y29_" + hashlib.sha256(b"e2y29").hexdigest()[:30])
    case("D23", "access/refresh_token", "extra", "구글 refresh token 모양 1//0", "found {v} in response", v="1//0" + "CANARY_R_" + hashlib.sha256(b"e2r").hexdigest()[:40])

    # ---- E. Cookie ---------------------------------------------------------------------------------------------------------------
    v = sec("CKY")
    rows = [
        ("Cookie: sessionid=", "Cookie: sessionid={v}"), ("Cookie: session=", "Cookie: session={v}"), ("Cookie: 네이버 NID_AUT·NID_SES", "Cookie: NID_AUT={v}; NID_SES={v}"),
        ("Cookie: 여러 쿠키 가운데 하나", "Cookie: a=1; b={v}; c=3"), ("Cookie: JSESSIONID=", "Cookie: JSESSIONID={v}"), ("Set-Cookie: auth=… HttpOnly", "Set-Cookie: auth={v}; Path=/; HttpOnly; Secure"),
        ("Set-Cookie: SID=", "Set-Cookie: SID={v}; Domain=.x"), ("소문자 cookie: foo=", "cookie: foo={v}"), ("JSON 헤더 Cookie", '{{"Cookie": "foo={v}"}}'),
        ("파이썬 cookies 딕셔너리", "cookies = {{'sess': '{v}'}}"), ("document.cookie", 'document.cookie = "sid={v}"'), ("Cookie: NNB= (네이버 방문자 쿠키)", "Cookie: _ga=GA1.2.3; NNB={v}"),
        ("curl -b", 'curl -b "sid={v}" https://x'), ("Cookie: token=", "Cookie: token={v}"), ("Cookie: 구글 SAPISID", "Cookie: SAPISID={v}; HSID=x"),
        ("Cookie 값에 따옴표", 'Cookie: sid="{v}"'), ("쿠키 이름만 다른 로그인 쿠키", "Cookie: logged_in={v}"), ("쿠키 이름이 key", "Cookie: key={v}"),
    ]
    for index, (desc, template) in enumerate(rows, start=1):
        case(f"E{index:02d}", "Cookie", "list", desc, template, v=v)

    # ---- F. 주소의 사용자 정보·질의 -----------------------------------------------------------------------------------------------
    v = sec("URLPW")
    rows = [
        ("https://사용자:토큰@", "https://user:{v}@github.com/shine88pc/chanceblog.git"), ("x-access-token:토큰@", "https://x-access-token:{v}@github.com/o/r.git"),
        ("토큰만 사용자 자리", "https://{v}@github.com/o/r.git"), ("oauth2:토큰@", "git push https://oauth2:{v}@host/o/r.git main"),
        ("비밀번호에 @ 가 든 주소", "https://user:CANARY@pw@host.example/path"), ("?sig=", "https://x/y?a=1&sig={v}"), ("?signature=", "https://x/y?signature={v}"),
        ("?code= (긴 OAuth 코드)", "https://x/cb?code={v}&state=1"), ("?client_secret=", "https://x/y?client_secret={v}"), ("?password=", "https://x/y?password={v}"),
        ("JSON 이스케이프 주소 https:\\/\\/", "https:\\/\\/user:{v}@host\\/x"),
    ]
    for index, (desc, template) in enumerate(rows, start=1):
        case(f"F{index:02d}", "URL", "list", desc, template, v=v)

    # ---- G. 눈속임·인코딩 -------------------------------------------------------------------------------------------------------
    v = sec("EVADE")
    case("G01", "evasion", "list", "이름 사이 폭 없는 공백", "api" + ZWSP + "_key={v}", v=v)
    case("G02", "evasion", "list", "값 사이 폭 없는 공백", "api_key=" + v[:12] + ZWSP + v[12:], v=v)
    case("G03", "evasion", "adv", "키릴 문자 а 로 쓴 api_key", CYR_A + "pi_key={v}", v=v)
    case("G04", "evasion", "adv", "전각 등호 api_key＝", "api_key" + FW_EQ + "{v}", v=v)
    case("G05", "evasion", "adv", "전각 문자 이름 ａｐｉ＿ｋｅｙ=", fullwidth("api_key") + "={v}", v=v)
    case("G06", "evasion", "adv", "퍼센트 인코딩 이름 api%5Fkey=", "api%5Fkey={v}", v=v)
    case("G07", "evasion", "adv", "토큰을 줄바꿈으로 둘로 쪼갬", "Authorization: Bearer " + v[:14] + "\n" + v[14:], v=v)
    case("G08", "evasion", "adv", "토큰을 공백으로 둘로 쪼갬", "api_key=" + v[:14] + " " + v[14:], v=v)
    case("G09", "evasion", "list", "RTL 덮어쓰기 문자 삽입", "api_key=" + RTL + "{v}", v=v)
    case("G10", "evasion", "adv", "base64 로 감싼 헤더 줄", "payload={b}", b=b64("Authorization: Bearer " + v))
    case("G11", "evasion", "adv", "이스케이프 JSON 문자열 속 api_key", '"{{\\"api_key\\": \\"{v}\\"}}"', v=v)
    case("G12", "evasion", "adv", "이중 JSON(문자열 안의 문자열) access_token", '{{"body": "{{\\"access_token\\": \\"{v}\\"}}"}}', v=v)
    case("G13", "evasion", "adv", "탭 구분 이름 값", "api_key\t{v}", v=v)
    case("G14", "evasion", "list", "이름 대문자 터키 İ(API_KEY 대신 APİ_KEY)", "AP" + DOTTED_I + "_KEY={v}", v=v)
    case("G15", "evasion", "adv", "값 앞에 따옴표 두 겹", 'api_key=""{v}""', v=v)
    case("G16", "evasion", "list", "서러게이트 짝 없는 글자", "api_key={v}" + LONE_SURROGATE, v=v)

    # ---- H. 길이·구조 -----------------------------------------------------------------------------------------------------------
    v = sec("BIG")
    case("H01", "length", "list", "20만 자 안쪽 15만 자 위치", ("x " * 75000) + "api_key={v} tail", v=v)
    case("H02", "length", "list", "20만 자 경계에 걸친 위치", ("y " * 99990) + "api_key={v}", v=v)
    case("H03", "length", "list", "20만 자 뒤(잘려 나가야 함)", ("z " * 100500) + "api_key={v}", v=v)
    case("H04", "length", "list", "= 만 5만 개 뒤 값", ("=" * 50000) + " api_key={v}", v=v)
    case("H05", "length", "list", "개인 키 블록 본문", "-----BEGIN " + "PRIVATE KEY-----\n{v}\n-----END PRIVATE KEY-----", v=v)
    case("H06", "length", "list", "개인 키 블록(끝 없음)", "-----BEGIN " + "PRIVATE KEY-----\n{v}\nmore", v=v)

    # ---- I. 알려진 키 모양(라벨 없음) ---------------------------------------------------------------------------------------------
    case("I01", "key-shape", "extra", "Google API 키 AIza+35", "key leaked {v} oops", v="AI" + "za" + ("CANARY_GEMINI_" + hashlib.sha256(b"e2ai").hexdigest())[:35])
    case("I02", "key-shape", "extra", "Google 새 형식 AQ.", "see {v}.", v="AQ" + "." + ("CANARY_AQ_" + hashlib.sha256(b"e2aq").hexdigest())[:44])
    case("I03", "key-shape", "extra", "GOCSPX 시크릿", "client {v}", v="GOC" + "SPX-" + ("CANARY_GX_" + hashlib.sha256(b"e2gx").hexdigest())[:26])
    case("I04", "key-shape", "extra", "GitHub ghp_", "token {v}", v="gh" + "p_" + hashlib.sha256(b"e2ghp").hexdigest()[:36])
    case("I05", "key-shape", "extra", "GitHub PAT github_pat_", "token {v}", v="github_" + "pat_" + ("CANARY_PAT_" + hashlib.sha256(b"e2pat").hexdigest())[:45])
    case("I06", "key-shape", "extra", "텔레그램 봇 토큰", "url https://api.telegram.org/bot{v}/sendMessage", v="123456789:" + ("CANARY_TG_" + hashlib.sha256(b"e2tg").hexdigest())[:35])
    case("I07", "key-shape", "extra", "sk-proj- 키", "key {v}", v="sk-" + "proj-" + ("CANARY_SKP_" + hashlib.sha256(b"e2skp").hexdigest())[:50])
    case("I08", "key-shape", "extra", "한글 바로 옆의 AIza 키", "키는{v}를 쓴다", v="AI" + "za" + ("CANARY_GEMINI_" + hashlib.sha256(b"e2ai2").hexdigest())[:35])
    case("I09", "key-shape", "extra", "Gemini 키 앞뒤에 영문 붙음", "xAIza{v}x", v=("CANARY_GEMINI_" + hashlib.sha256(b"e2ai3").hexdigest())[:35])
    case("I10", "key-shape", "limit", "라벨 없는 네이버 시크릿 10자", "value is {v} done", v="CANARY_N10")
    case("I11", "key-shape", "limit", "라벨 없는 64자 16진수(공공데이터 키 모양)", "value is {v} done", v=hex64("I11"))
    case("I12", "key-shape", "limit", "라벨 없는 Unsplash 43자 모양", "value is {v} done", v=("CANARY_UNSPLASH_" + hashlib.sha256(b"e2un").hexdigest())[:43])
    return cases


CASES = build_cases()


def text_of(case):
    return case.template.format(**case.values)


def leaks(case, output):
    """output 에 남은 비밀 — [(값 이름, 'full'|'part')]. 값 전체가 있으면 full, 8글자(값이 더 짧으면 그 길이) 조각이 하나라도 있으면 part. **값 자체는 돌려주지 않는다.**"""
    found = []
    for name, value in case.values.items():
        if value in output:
            found.append((name, "full"))
            continue
        width = 8 if len(value) >= 8 else len(value)
        if width and any(value[index:index + width] in output for index in range(0, len(value) - width + 1)):
            found.append((name, "part"))
    return found


# ---- 정상 출력 표(오탐 표) -------------------------------------------------------------------------------------------------------------
# 앱이 실제로 내거나 운영자가 흔히 보는 **평범한 글** — 비밀이 아니므로 `mask()` 가 한 글자도 바꾸면 안 된다. 해시류는 실행 중에 만든다(커밋 해시 40자·SHA-256 64자(MANIFEST)·MD5 32자 — 모양만으로 가리는 규칙은 두지 않는다).
SHA1 = hashlib.sha1(b"pcsec1-normal").hexdigest()
SHA256 = hashlib.sha256(b"pcsec1-normal").hexdigest()
MD5 = hashlib.md5(b"pcsec1-normal").hexdigest()
NORMAL_TEXTS = (
    # 해시·MANIFEST·커밋
    "commit " + SHA1, "6d74857 Merge pull request #49 from shine88pc/ai/claude/M046-own-posts-reader", "Merge: 6d74857 c3b99d3", "git rev-parse HEAD -> " + SHA1,
    '"sha256": "' + SHA256 + '"', "sha256 " + SHA256 + "  chanceblog-20261111-090000.db", "SHA-256: " + SHA256, "파일 해시(MD5) " + MD5, '{"size": 4096, "sha256": "' + SHA256 + '"}',
    "원격 main 은 " + SHA1[:12] + " 에서 " + SHA1[:7] + " 로 옮겨졌습니다.",
    # 경로
    "C:" + chr(92) + "Users" + chr(92) + "운영자" + chr(92) + "AppData" + chr(92) + "Local" + chr(92) + "ChanceblogDesktop" + chr(92) + "chanceblog.db",
    "C:" + chr(92) + "work" + chr(92) + "ai" + chr(92) + "cd_repo" + chr(92) + "src" + chr(92) + "chanceblog_desktop" + chr(92) + "security" + chr(92) + "mask.py:154",
    "/home/runner/work/chanceblog-desktop/chanceblog-desktop/tests/test_security_mask.py", "%LOCALAPPDATA%" + chr(92) + "ChanceblogDesktop" + chr(92) + "backups" + chr(92) + "chanceblog-20261111-090000.db",
    "backups/topic_engine/topic-20261111-090000/MANIFEST.json", "_posts/ai/2026-11-11-KR-090000.md",
    # 주소
    "https://github.com/shine88pc/chanceblog-desktop/pull/49", "https://github.com/shine88pc/chanceblog/actions?query=branch%3Aai%2Fclaude%2FM046-own-posts-reader",
    "https://example.com/a?page=2&sort=asc", "https://blog.naver.com/exampleaaa/223456789012", "https://x.example/search?keyword=블로그&monkey=1", "https://x.example/?tokenizer=bpe",
    "https://docs.example.com/guide/authorization-and-cookies#overview", "https://example.com/cookie-policy", "https://www.google.com/search?q=api+key+발급+방법",
    "https://example.com/a?code=200&x=1", "https://example.com/posts/2026/11/11/token-economy-explained/",
    # 한글 문장 — 비밀 낱말이 든 평범한 말
    "토큰 발급 방법을 알려 드립니다.", "비밀번호는 저장하지 않습니다.", "쿠키 설정은 브라우저에서 직접 합니다.", "키는 Windows 자격 증명 관리자에만 보관합니다.", "인증 정보는 이 앱이 다루지 않습니다.",
    "연결 설정: 키가 없어도 모든 핵심 기능은 그대로 됩니다.", "이 글에는 비밀(secret) 이야기가 나오지만 값은 없습니다.", "Authorization 헤더는 쓰지 않습니다.", "Cookie 와 세션은 저장하지 않습니다.",
    "API 키를 발급받는 순서: 콘솔에 들어가서 새 키 만들기를 누릅니다.", "서비스 키 신청은 공공데이터포털에서 합니다.", "Key 가 든 평범한 문장입니다 — Key 는 열쇠라는 뜻입니다.",
    "토큰 버킷 방식으로 호출 횟수를 나눕니다.", "자격 증명 관리자에서 항목을 지우면 키도 함께 지워집니다.", "쿠키 허용 안내 문구를 글 끝에 적습니다.",
    # 영어 문장
    "The token expired yesterday, so the job was skipped.", "Keep your secret safe and never paste it into a chat.", "An API key is required for this feature.", "Authorization failed (401) — check your sign-in.",
    "Cookie policy updates are announced on the blog.", "Set the cookie banner text in the settings page.", "Key points: speed, safety and simplicity.", "The password manager stores long phrases.",
    "Bearer of good news", "Basic internationalization of the app", "We rotate the key every quarter.", "Please send the report by Friday.", "The secret to good posts is a clear first paragraph.",
    # 이름=값 모양이지만 비밀이 아닌 것
    "key=value", "sort key=name", "hotkey=ctrl+k", "primary_key=id", "monkey=1", "keyword=블로그", "PWD=C:/Users/me/work", "pwd=/home/me", "page=2&limit=50", "state=open&label=bug",
    "max_retries=3", "tokenizer=bpe", "cache_key=abc123", "timeout=30", "api_key = 짧음", "token", "AIza", "ghp_", "AQ.짧음", "key 입력", "pwd 명령으로 위치를 본다", "토큰=",
    # 명령줄·헤더 줄
    "python -m chanceblog_desktop keys add gemini --name 기본 --stdin", "python -m chanceblog_desktop keys remove 1a2b3c4d --yes", "python -m chanceblog_desktop doctor", "git push origin main",
    "git checkout -b feature/new-post", 'curl -H "Accept: application/json" https://example.com/api', "curl -b cookies.txt https://example.com", "Content-Type: application/json",
    "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Host: example.com", "Accept-Language: ko-KR,ko;q=0.9", "Cache-Control: no-cache", "Set-Cookie 규칙은 문서를 봅니다.",
    # 로그·번호·표·링크
    "2026-11-11T09:00:00Z INFO backup created", "123e4567-e89b-12d3-a456-426614174000", "ISBN 978-3-16-148410-0", "전화 010-1234-5678", "사업자등록번호 123-45-67890", "me@example.com",
    "File " + chr(34) + "C:" + chr(92) + "x" + chr(92) + "y.py" + chr(34) + ", line 12, in <module>", "[문서](docs/SECURITY.md)", "| 번호 | 이름 | 상태 |", "- 항목 하나: 값 하나",
    '{"name": "홍길동", "count": 12, "ok": true}', '{"status": "ok", "items": [1, 2, 3]}', "<title>블로그 제목</title>", "<p>본문 문단입니다.</p>",
    # 데이터 덩어리 — 풀어도 비밀이 없다
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "Zm9vYmFyYmF6cXV4IQ==" + " 이 글은 평범한 데이터입니다.",
    # 긴 평범한 글
    "가나다라마바사 " * 400, "The quick brown fox jumps over the lazy dog. " * 300, "줄 하나" + chr(10) + "줄 둘" + chr(10) + "줄 셋 token 은 짧다" + chr(10),
    # 공백·점이 낀 이름(`API key`)을 이름으로 읽게 된 뒤에도 '이름: 값' 이 아닌 평범한 글은 가리지 않는다(PCSEC1V D4)
    "the api key is stored safely", "Where is my API key?", "secret keys are hard to guess", "monkey key: value1", "turkey = dinner time", "API key 발급 방법을 설명합니다", "app key 입력란",
    "service key: 필요 없음", "access key rotation", "the secret key to success is practice", "keyboard key = a", "Basic information about the app", "Basic usage: run the tool",
)
