"""연결 설정 — 용도별 키 항목(여러 개)의 목록·모양 검사·보관·상태(docs/SECURITY.md §7, 결정 D-30·D-31).

**비밀은 비밀 보관소(`security.keystore`)에만** 있고, 이 모듈이 데이터 폴더의 `connections.json` 에 두는 것은 비밀이 아닌 메타데이터뿐이다: 항목 번호(난수)·용도·제공자·이름·소속 프로젝트·순서·상태·
만든·확인 시각·확인 결과·한도 묶음 이름(비밀이 아닌 칸 — 클라이언트 ID·고객 ID — 의 해시이거나 프로젝트 이름)·약관 확인 시각. **비밀 칸의 값에서 유도한 것(해시·지문·끝 글자)은 이 파일에 하나도 없다**
(키의 끝 4자·앞부분·길이 같은 일부 글자는 어디에도 만들지 않는다 — 목록은 제공자·항목 번호·등록 여부·마지막 연결 시험·등록 시각만 보인다, PCSEC1 H2).

규칙(모두 시험이 지킨다):
  · 입력 오류 문구·세부·로그에 **입력한 값을 넣지 않는다**(모양 검사는 이유만 돌려준다 — `security.shape`).
  · 항목 수 상한은 둘이다. ① **읽을 때의 천장** — 용도마다 최대 `MAX_ENTRIES_PER_PURPOSE`(3)개(키를 하나만 두는 NAVER API HUB 는 1개)이고 넘는 파일은 깨진 파일이다(무제한 키 돌려쓰기를 구조로 막는다).
    ② **더할 때의 상한(운영자 정책 표)** — 제공자마다 `Provider.max_entries`(Unsplash·기타 1개, AI 제공자 3개, Blogger 는 채널마다 1개라 2개)이고 넘기면 `KEY_ENTRY_LIMIT` 로 거절한다 — 읽기는 그대로라 상한을 낮춰도 옛 파일·옛 항목은 지우거나 막지 않는다.
    같은 서비스에 둘째 키를 더할 때는 약관 확인(`terms_ack`)이 있어야 하고(Blogger 처럼 둘째가 다른 채널의 연결이면 아니다) 그 사실과 시각을 항목에 적는다.
  · 같은 값(보관소에 있는 값과 직접 비교한다 — 값에서 만든 지문을 파일에 두지 않는다)·같은 이름은 같은 용도에 두 번 넣지 못한다.
  · 쓰기는 연결 설정 잠금 안에서 '읽고 → 바꾸고 → 쓴다'. 지울 때는 보관소의 값을 **먼저** 지우고(남은 항목은 '확인 필요' 로 보여 다시 지울 수 있다) 그다음 메타데이터를 지운다.
  · 읽기 명령(`list_entries`·`purpose_overview`)은 데이터 폴더·보관소를 만들거나 바꾸지 않는다.
  · `connections.json` 은 구조 버전·낯선 칸을 검사한다. 깨졌으면(`CONNECTIONS_FILE_INVALID`) 고치거나 지우지 않고 알린다 — 쓸 때마다 직전의 올바른 내용을 `connections.json.bak` 에 남긴다.
  · 상태 문구는 한 곳의 표(`STATUS_TEXT`)에서만 나오고 사용자 화면에는 영문 코드를 보이지 않는다.
"""
from __future__ import annotations

import contextlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import capabilities
from ..errors import AppError
from ..security import shape
from ..security.keystore import encode_fields
from .context import write_json
from .lock import PublishLock

KST = timezone(timedelta(hours=9), "KST")
SCHEMA = 1
FILE_NAME = "connections.json"
MAX_ENTRIES_PER_PURPOSE = 3            # 용도마다 키 항목은 3개까지 — 키를 끝없이 돌려 쓰는 구조를 막는 장치(시험이 값을 못박는다)
MAX_NAME_CHARS = 40
MAX_PROJECT_CHARS = 60
CHECK_VALID_HOURS = 24                 # 연결 시험 성공이 '연결됨' 으로 인정되는 시간
TEST_MIN_INTERVAL = 60                 # 같은 키를 이 초 안에 다시 시험하지 않는다
KEYS_LOCK_WAIT = 10.0                  # 연결 설정 잠금을 기다리는 시간(초)
MIN_PREFIX = 4                         # 항목 번호 앞부분으로 고를 때 최소 글자 수
DELETE_PREFIX = 8                      # 지울 때 받는 번호 앞부분의 최소 글자 수 — 목록에 보이는 '번호 앞 8자'
MAX_ORDINAL_DIGITS = 2                 # 순번은 1~99
CLIENT_SCOPE = "이 PC 전용 — 클라우드 자동 발행(GitHub Actions)의 시크릿과는 따로 둡니다. 같은 값을 다시 쓰지 않습니다"
TERMS_NOTICE = ("같은 서비스의 무료 한도를 여러 계정·프로젝트로 나눠 쓰는 것은 서비스 약관에서 금지될 수 있습니다. 본인 소유의 정당한 키(예: 유료 키와 예비 키, 다른 용도의 키)에만 쓰세요. "
                "키를 끝없이 돌려 쓰는 기능은 이 프로그램에 없습니다(용도마다 3개까지이고, 다른 앱의 키로 넘어가는 것은 한도·일시 오류일 때뿐입니다).")

ACTIVE, STANDBY, OFF = "active", "standby", "off"
STATES = (ACTIVE, STANDBY, OFF)
STATE_TEXT = {ACTIVE: "사용", STANDBY: "예비", OFF: "꺼짐"}
CHECK_NONE, CHECK_OK, CHECK_AUTH, CHECK_ERROR = "", "ok", "auth_failed", "error"
CHECK_RESULTS = (CHECK_NONE, CHECK_OK, CHECK_AUTH, CHECK_ERROR)
ON_SAVE, ON_FAILOVER = "save", "failover"
ON_LIMIT = (ON_SAVE, ON_FAILOVER)
ON_LIMIT_TEXT = {ON_SAVE: "절약 모드만(다른 키로 넘어가지 않음)", ON_FAILOVER: "허용된 다음 키로 전환(한도·일시 오류일 때만)"}
ENTRY_LIMIT_DETAIL = "이 용도는 키를 하나만 둡니다 — 한도를 늘리려고 여러 키·계정을 돌려 쓰지 않습니다(키를 바꾸려면 기존 항목을 `keys remove 번호 --yes` 로 지운 뒤 새로 넣습니다)"
ROLLBACK_FAILED_DETAIL = "항목을 저장하지 못했고 보관소에 넣은 값도 지우지 못했다"                  # `_rollback` 이 보관소 값을 못 지웠을 때 오류 세부의 앞부분 — 화면 어댑터가 이 앞부분으로 '키가 보관소에 남았을 수 있다' 를 알아본다(시험이 못박는다)
PROVIDER_LIMIT_DETAIL = "이 서비스는 키를 하나만 둡니다 — 한도를 늘리려고 여러 키·계정을 돌려 쓰지 않습니다(키를 바꾸려면 기존 항목을 `keys remove 번호 --yes` 로 지운 뒤 새로 넣습니다)"
ROTATION_NEVER, ROTATION_LIMITED = "never", "limited"     # never: 어떤 오류에도 다른 항목으로 자동 전환하지 않는다(Unsplash) · limited: 한도·일시 오류 네 가지에만 허용된 다음 항목으로

CONNECTED, NEEDS_CHECK, RATE_LIMITED, AUTH_ERROR, NOT_CONNECTED = "connected", "needs_check", "rate_limited", "auth_error", "not_connected"
STATUS_TEXT = {CONNECTED: "연결됨", NEEDS_CHECK: "연결 확인 필요", RATE_LIMITED: "요청 한도 도달", AUTH_ERROR: "인증 정보 오류", NOT_CONNECTED: "연결 안 됨"}      # 상태 문구는 이 표 한 곳에서만


# ---- 용도 레지스트리(데이터) -----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Field:
    name: str                  # 영문 소문자 칸 이름(`--stdin` JSON 의 키)
    label: str                 # 화면에 보이는 한국어 이름
    secret: bool               # 화면에 값을 보이지 않는 칸(원문도 일부 글자(끝 4자·앞부분·길이)도 보이지 않는다)
    min_len: int
    max_len: int
    example: str               # 모양 안내(실제 값이 아니다)
    charset: str = ""          # '' 는 기본 글자(영문·숫자와 `_ - + / = . ~ :`) · 'alnum' 은 영문·숫자와 `_ -` 만 — 공식 문서에 모양이 없는 값(NAVER API HUB)을 느슨하게 검사한다


@dataclass(frozen=True)
class Window:
    name: str                  # 'day' · 'hour' · 'month' 처럼 기록에 쓰는 이름
    kind: str                  # 'day'(하루 — 한국 시간 초기화 시각에 0 으로) · 'month'(한국 시간 달력 월 — 다음 달 1일 00:00 에 0 으로, 라벨 `YYYY-MM`) · 'sliding'(최근 `minutes` 분)
    limit: int
    minutes: int = 0
    header_sync: bool = False  # 응답 머리글의 남은 횟수로 로컬 계수를 보정하는 창


STAGE_NOTICE, STAGE_LIMITED, STAGE_CLOSED = "notice", "limited", "closed"


@dataclass(frozen=True)
class Stage:
    """한도 단계 — 이번 달 사용량이 `Provider.console_limit`(콘솔 월 한도)의 `percent`% 를 **넘기면**(이 호출을 하고 난 뒤의 사용량 기준) 이 단계다. 단계는 비율이 높은 것이 이긴다."""
    name: str                  # STAGE_NOTICE(안내만) · STAGE_LIMITED(자동 새로고침 중지) · STAGE_CLOSED(신규 호출 중지) — 코드용 이름이라 화면에는 `text` 만 보인다
    percent: int
    text: str                  # 쉬운 한국어 안내
    deny: tuple = ()           # 이 단계에서 거절하는 우선순위(`bulk_refresh` · `new_candidate` · `selected_candidate` · `critical`)
    manual_max_calls: int = 0  # 이 단계에서 `new_candidate`(직접 시작한 분석)가 한 번에 부를 수 있는 횟수의 상한(0 = 상한 없음)


@dataclass(frozen=True)
class Provider:
    key: str                   # 제공자 이름(없으면 '')
    label: str
    rotation: str              # ROTATION_NEVER · ROTATION_LIMITED
    tiers: tuple               # ((등급 이름, (Window, …)), …) — 한도를 모르면 빈 튜플
    default_tier: str
    note: str = ""
    ledger: bool = False       # 참이면 창마다 시도·성공을 따로 세고 호출 장부를 남긴다(실패한 호출도 시도로 센다 — 공식 사용량에 들어가는지 모르는 제공자)
    fail_closed: bool = False  # 참이면 사용량·시계·계수·인증 상태를 확인할 수 없을 때 신규 호출을 막는다(다른 제공자는 지금 동작 그대로)
    console_limit: int = 0     # 서비스 콘솔의 월 한도(참고 값 — 단계 비율의 기준). 프로그램 안 한도는 `tiers` 의 창이다
    stages: tuple = ()         # (Stage, …) — 비어 있으면 기존 규칙(`quota.FLOOR_PERCENT`·`RESERVE_PERCENT`)을 쓴다
    stop_text: str = ""        # 신규 호출을 멈췄을 때 사용자에게 보이는 고정 문구(기술 오류 코드는 보이지 않는다)
    max_entries: int = 0       # 이 제공자의 키 항목을 **더할 때** 상한(운영자 정책 표) — 0 은 '용도의 상한을 따른다'(표에 없는 시험용 제공자의 옛 동작). 실제 표의 제공자는 모두 양수를 직접 적는다(시험이 못박는다)
    second_key_needs_terms: bool = True     # 거짓이면 같은 제공자의 둘째 항목이 '같은 서비스의 한도를 나누는 키' 가 아니라 다른 채널의 연결이라 약관 확인을 묻지 않는다(Blogger)

    def windows(self, tier=""):
        wanted = tier or self.default_tier
        for name, windows in self.tiers:
            if name == wanted:
                return windows
        return ()

    def tier_names(self):
        return tuple(name for name, _ in self.tiers)


@dataclass(frozen=True)
class Purpose:
    key: str
    label: str
    summary: str
    fields: tuple
    providers: tuple
    fallback_providers: tuple = ()      # 운영자가 켠 다음 제공자(기본은 비어 있다 — 지금은 자리만 있다)
    implemented: bool = False           # 실제 호출 코드가 있나 — 없으면 '연결됨' 이 될 수 없다
    optional: bool = True
    works_without_key: bool = True      # 키가 없어도 핵심 기능이 그대로 된다(키 없음은 오류가 아니다)
    takes_keys: bool = True
    identity_field: str = ""            # 한도 묶음을 정하는 칸(같은 값이면 같은 앱 — 한도를 함께 쓴다)
    reset_hour: int = 0                 # 하루 한도가 0 으로 돌아가는 한국 시각(시)
    client_scope: str = CLIENT_SCOPE
    note: str = ""
    max_entries: int = MAX_ENTRIES_PER_PURPOSE      # 이 용도의 항목 수 상한 — 기본 3, 키를 하나만 두는 용도(NAVER API HUB)는 1
    legacy_to: str = ""                 # 비어 있지 않으면 '옛 용도' — 새 용도 이름. 옛 파일에 남은 항목은 읽고 보여 주지만 새 항목은 더하지 못한다(키는 지우지 않는다)

    def field(self, name):
        return next((item for item in self.fields if item.name == name), None)

    def provider(self, key=""):
        wanted = key or self.providers[0].key
        return next((item for item in self.providers if item.key == wanted), None)

    def provider_keys(self):
        return tuple(item.key for item in self.providers)

    def entry_cap(self, provider=""):
        """이 용도의 그 제공자에 키 항목을 더할 때 상한 — 제공자 표의 값, 0 이면 용도의 상한. 모르는 제공자는 용도의 상한이다(부르는 쪽이 제공자 이름을 먼저 검사한다)."""
        chosen = self.provider(provider)
        return (chosen.max_entries if chosen is not None else 0) or self.max_entries

    def primary_secret(self):
        return next((item.name for item in self.fields if item.secret), "")


APIHUB_STOP_TEXT = "NAVER API HUB의 새로운 데이터 조회를 사용할 수 없습니다. 저장된 정보와 기본 주제 선정 규칙으로 후보 생성을 계속합니다."     # 고정 문구 — 사유(기술 오류 코드 없이 쉬운 한국어)는 따로 덧붙인다
APIHUB_INTERNAL_DAY, APIHUB_INTERNAL_MONTH, APIHUB_CONSOLE_MONTH = 100, 27000, 30000      # 프로그램 안 기준(하루·월)과 콘솔 월 한도 — 안 기준 월 27,000 은 콘솔 30,000 의 90%
APIHUB_NEW_CALL_CAP = 5                # 80% 를 넘은 뒤 직접 시작한 분석이 한 번에 부를 수 있는 횟수(기본값 — 운영자가 바꿀 수 있는 정책 값)
APIHUB_STAGES = (
    Stage(STAGE_NOTICE, 70, "이번 달 사용량이 NAVER API HUB 콘솔 한도의 70%를 넘었습니다 — 아직 정상이지만 사용량을 살펴 주세요."),
    Stage(STAGE_LIMITED, 80, f"이번 달 사용량이 80%를 넘어 자동 새로고침과 자동 배치를 멈췄습니다 — 직접 시작한 분석만 한 번에 {APIHUB_NEW_CALL_CAP}회까지 부릅니다.", ("bulk_refresh",), APIHUB_NEW_CALL_CAP),
    Stage(STAGE_CLOSED, 90, "이번 달 사용량이 90%(프로그램 안 월 한도)를 넘어 새 데이터 조회를 모두 멈췄습니다 — 저장된 정보와 기본 규칙으로 계속하고 다음 달 1일에 다시 열립니다.",
          ("bulk_refresh", "new_candidate", "selected_candidate", "critical")),
)


def _purposes():
    day_naver = (("default", (Window("day", "day", 25000),)),)
    unsplash = Provider("unsplash", "Unsplash", ROTATION_NEVER, (("demo", (Window("hour", "sliding", 50, 60, True),)), ("production", (Window("hour", "sliding", 1000, 60, True),))), "demo",
                        "데모 앱은 시간당 50회, 승인된 앱은 시간당 1,000회입니다. `api.unsplash.com` 요청만 세고 사진 파일(`images.unsplash.com`) 요청은 세지 않습니다. 자동으로 다른 키로 넘어가지 않습니다", max_entries=1)
    apihub = Provider("", "NAVER API HUB", ROTATION_NEVER, (("default", (Window("day", "day", APIHUB_INTERNAL_DAY), Window("month", "month", APIHUB_INTERNAL_MONTH))),), "default",
                      "프로그램 안 기준은 하루 100회·이번 달 27,000회이고 서비스 콘솔의 월 한도(30,000회 — 계정 설정에 따라 최대 50,000회, 100% 에서 호출이 차단됩니다)는 마지막 안전장치입니다. "
                      "실패한 호출도 시도로 세고 월 경계는 한국 시간 달력 월로 잡습니다(실패한 호출이 공식 사용량에 들어가는지·월 초기화 시각은 공개 문서에 없어 안전한 쪽으로 가정했습니다). "
                      "키는 하나만 쓰고 429 가 나도 다른 키로 넘어가지 않습니다",
                      ledger=True, fail_closed=True, console_limit=APIHUB_CONSOLE_MONTH, stages=APIHUB_STAGES, stop_text=APIHUB_STOP_TEXT, max_entries=1)
    return (
        Purpose("naver_apihub", "NAVER API HUB 검색어 트렌드", "네이버 데이터랩 '검색어 트렌드' 로 키워드의 관심도 변화를 조회해 후보의 지표를 보정하는 데 씁니다(준비 중 — 안전 장치만 있고 호출 코드는 아직 없습니다). "
                "키는 하나만 두고 한도를 늘리려고 돌려 쓰지 않습니다.",
                (Field("client_id", "클라이언트 ID", False, 8, 128, "영문·숫자·-·_ 8~128자(공식 문서에 모양이 없어 느슨하게 확인합니다)", "alnum"),
                 Field("client_secret", "클라이언트 시크릿", True, 8, 128, "영문·숫자·-·_ 8~128자(공식 문서에 모양이 없어 느슨하게 확인합니다)", "alnum")),
                (apihub,), identity_field="client_id", max_entries=1),
        Purpose("naver_searchad", "네이버 검색광고 API", "키워드 도구의 월간 검색 수 같은 지표를 조회하는 데 씁니다(준비 중).",
                (Field("customer_id", "고객 ID", False, 3, 20, "숫자 7자리 안팎"), Field("access_license", "액세스 라이선스", True, 16, 128, "영문·숫자 40~64자"), Field("secret_key", "비밀 키", True, 16, 128, "영문·숫자·기호 40자 안팎")),
                (Provider("", "네이버 검색광고", ROTATION_LIMITED, (("default", ()),), "default", "한도를 아직 확인하지 못했습니다 — 한도 오류 응답으로만 감지합니다", max_entries=1),), identity_field="customer_id"),
        Purpose("image_provider", "이미지 공급자", "글 대표 이미지를 찾는 데 씁니다(첫 공급자는 Unsplash — 사진 파일은 원본 주소로만 보여 줍니다). 데스크톱용으로 따로 등록한 앱의 키를 쓰고 "
                "클라우드 자동 발행(GitHub Actions)의 키와 같은 값을 쓰지 않습니다(같은 값이면 한도를 함께 쓰게 됩니다).",
                (Field("access_key", "Access Key", True, 16, 128, "영문·숫자·기호 40자 안팎"),),
                (unsplash, Provider("pexels", "Pexels", ROTATION_LIMITED, (("default", ()),), "default", "자리만 있고 아직 코드가 없습니다", max_entries=1),
                 Provider("pixabay", "Pixabay", ROTATION_LIMITED, (("default", ()),), "default", "자리만 있고 아직 코드가 없습니다", max_entries=1))),
        Purpose("ai_assist", "AI 보조(선택)", "요약·설명 같은 보조 기능에 씁니다. 기본은 꺼짐이고 키가 없어도 모든 핵심 기능이 그대로 됩니다.",
                (Field("key", "API 키", True, 16, 256, "영문·숫자·기호 40자 안팎"),),
                (Provider("gemini", "Gemini", ROTATION_LIMITED, (("default", ()),), "default", "한도는 모델·계정마다 달라 확인하지 못했습니다 — 한도 오류 응답으로만 감지합니다", max_entries=3),)),
        Purpose("blogger", "Blogger", "Blogger 초안 저장에 씁니다(준비 중 — 로그인 방식이 정해지면 이 칸들을 맞춥니다).",
                (Field("client_id", "클라이언트 ID", False, 20, 128, "영문·숫자·점·하이픈 70자 안팎"), Field("client_secret", "클라이언트 시크릿", True, 8, 128, "영문·숫자·하이픈 35자 안팎"),
                 Field("refresh_token", "갱신용 인증 값", True, 20, 512, "영문·숫자·기호 100자 안팎")),
                (Provider("", "Google", ROTATION_LIMITED, (("default", ()),), "default", "한도를 아직 확인하지 못했습니다", max_entries=2, second_key_needs_terms=False),), identity_field="client_id"),
        Purpose("github_repo", "GitHub 저장소", "글을 올릴 때 쓰는 저장소 권한입니다.", (), (Provider("", "GitHub", ROTATION_NEVER, (("default", ()),), "default"),), takes_keys=False,
                note="이 앱은 키를 받지 않습니다 — 컴퓨터의 Git 로그인(Git 자격 증명 관리자)을 씁니다. 터미널에서 `git push` 를 한 번 해 로그인을 마칩니다."),
        Purpose("naver_openapi", "옛 항목 — 네이버 오픈 API(검색·데이터랩)", "예전 버전이 만든 용도입니다. 이 용도의 항목은 읽기만 하고(새 항목은 더하지 못합니다) 키는 지우지 않았습니다. "
                "NAVER API HUB 검색어 트렌드(naver_apihub)에 새로 넣은 뒤 이 항목은 `keys remove` 로 지웁니다.",
                (Field("client_id", "클라이언트 ID", False, 8, 64, "영문·숫자 20자 안팎"), Field("client_secret", "클라이언트 시크릿", True, 8, 64, "영문·숫자 10자 안팎")),
                (Provider("", "네이버", ROTATION_LIMITED, day_naver, "default", "옛 용도입니다 — 호출하지 않습니다"),),
                identity_field="client_id", legacy_to="naver_apihub"),
    )


PURPOSES = {item.key: item for item in _purposes()}
PURPOSE_ORDER = tuple(PURPOSES)


# ---- 항목(메타데이터) ----------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Entry:
    entry_id: str
    purpose: str
    provider: str
    name: str
    project: str
    order: int
    state: str
    created_at: str
    checked_at: str
    last_ok_at: str
    check_result: str
    bucket: str
    terms_ack_at: str

    @property
    def ref(self):
        return f"{self.purpose}:{self.entry_id}"

    def to_dict(self):
        return {"entry_id": self.entry_id, "purpose": self.purpose, "provider": self.provider, "name": self.name, "project": self.project, "order": self.order, "state": self.state,
                "created_at": self.created_at, "checked_at": self.checked_at, "last_ok_at": self.last_ok_at, "check_result": self.check_result,
                "bucket": self.bucket, "terms_ack_at": self.terms_ack_at}


ENTRY_KEYS = frozenset(Entry.__dataclass_fields__)
_ID = re.compile(r"[0-9a-f]{32}")
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_BUCKET = re.compile(r"(?:id|p)-.{1,80}")


def _is_stamp(value):
    if value == "":
        return True
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _entry_from(raw, registry):
    """파일의 항목 하나 → Entry. 모양이 틀리면 None(무엇이 틀렸는지는 부르는 쪽이 파일 이름으로만 알린다)."""
    if not isinstance(raw, dict) or set(raw) != ENTRY_KEYS:
        return None
    spec = registry.get(raw["purpose"]) if isinstance(raw["purpose"], str) else None
    if spec is None or not spec.takes_keys:
        return None
    provider = raw["provider"]
    if not isinstance(provider, str) or spec.provider(provider) is None or (provider == "" and spec.providers[0].key != ""):
        return None
    texts = ("entry_id", "name", "project", "state", "created_at", "checked_at", "last_ok_at", "check_result", "bucket", "terms_ack_at")
    if not all(isinstance(raw[key], str) for key in texts) or isinstance(raw["order"], bool) or not isinstance(raw["order"], int) or not 0 <= raw["order"] <= 1000:
        return None
    if (not _ID.fullmatch(raw["entry_id"]) or not _BUCKET.fullmatch(raw["bucket"]) or raw["state"] not in STATES
            or raw["check_result"] not in CHECK_RESULTS or not all(_is_stamp(raw[key]) for key in ("created_at", "checked_at", "last_ok_at", "terms_ack_at")) or raw["created_at"] == ""):
        return None
    if shape.label_problem(raw["name"], max_len=MAX_NAME_CHARS) or not raw["name"] or shape.label_problem(raw["project"], max_len=MAX_PROJECT_CHARS):
        return None
    return Entry(**raw)


@dataclass(frozen=True)
class Policy:
    on_limit: str = ON_FAILOVER
    tier: str = ""
    changed_at: str = ""

    def to_dict(self):
        return {"on_limit": self.on_limit, "tier": self.tier, "changed_at": self.changed_at}


@dataclass(frozen=True)
class Data:
    entries: tuple = ()
    policies: tuple = ()          # ((용도, Policy), …)

    def policy(self, purpose):
        return dict(self.policies).get(purpose) or Policy()

    def of_purpose(self, purpose):
        return sorted((item for item in self.entries if item.purpose == purpose), key=lambda item: (item.order, item.entry_id))

    def to_dict(self):
        return {"schema": SCHEMA, "entries": [item.to_dict() for item in self.entries], "policies": {key: value.to_dict() for key, value in sorted(self.policies)}}


def _bad_file(ctx, why):
    return AppError("CONNECTIONS_FILE_INVALID", {"파일": FILE_NAME}, detail=why)


def parse(ctx, raw, registry=PURPOSES):
    """파일 내용(JSON 으로 읽은 것) → Data. 모양이 틀리거나 낯선 칸이 있으면 CONNECTIONS_FILE_INVALID(내용은 문구에 담지 않는다)."""
    if not isinstance(raw, dict) or set(raw) != {"schema", "entries", "policies"} or raw["schema"] != SCHEMA or isinstance(raw["schema"], bool):
        raise _bad_file(ctx, "칸이 올바르지 않다(구조 버전이나 최상위 칸)")
    if not isinstance(raw["entries"], list) or not isinstance(raw["policies"], dict):
        raise _bad_file(ctx, "칸이 올바르지 않다(항목 목록이나 정책)")
    entries = []
    for item in raw["entries"]:
        found = _entry_from(item, registry)
        if found is None:
            raise _bad_file(ctx, "항목 하나의 칸이 올바르지 않다")
        entries.append(found)
    if len({item.entry_id for item in entries}) != len(entries):
        raise _bad_file(ctx, "같은 항목 번호가 겹친다")
    for purpose, found_spec in registry.items():
        if len([item for item in entries if item.purpose == purpose]) > found_spec.max_entries:
            raise _bad_file(ctx, f"한 용도의 항목이 {found_spec.max_entries}개를 넘는다")
    policies = []
    for purpose, item in raw["policies"].items():
        spec = registry.get(purpose) if isinstance(purpose, str) else None
        if (spec is None or not isinstance(item, dict) or set(item) != {"on_limit", "tier", "changed_at"} or item["on_limit"] not in ON_LIMIT or not isinstance(item["tier"], str)
                or not _is_stamp(item["changed_at"]) or (item["tier"] and not any(item["tier"] in provider.tier_names() for provider in spec.providers))):
            raise _bad_file(ctx, "정책 칸이 올바르지 않다")
        policies.append((purpose, Policy(item["on_limit"], item["tier"], item["changed_at"])))
    return Data(tuple(entries), tuple(sorted(policies)))


def load(ctx, registry=PURPOSES):
    """연결 설정을 읽는다(파일이 없으면 빈 설정 — 아무것도 만들지 않는다)."""
    path = ctx.workspace.connections_path
    if not path.exists():
        return Data()
    try:
        raw = _read_json(path)
    except (OSError, ValueError, RecursionError) as error:       # RecursionError: 깊게 겹친 JSON
        raise _bad_file(ctx, f"읽을 수 없다: {type(error).__name__}") from None
    return parse(ctx, raw, registry)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(ctx, data, registry=PURPOSES):
    """쓰기 전에 직전의 올바른 내용을 `.bak` 에 남기고 새 내용을 원자적으로 쓴다."""
    path = ctx.workspace.connections_path
    if path.exists():
        previous = load(ctx, registry)                      # 지금 파일이 올바를 때만 .bak 으로 남긴다(깨진 파일은 load 가 이미 멈췄다)
        write_json(path.with_name(FILE_NAME + ".bak"), previous.to_dict())
    write_json(path, data.to_dict())


class KeysLock(PublishLock):
    busy_code = "KEYS_BUSY"
    what = "연결 설정을 바꾸다"


@contextlib.contextmanager
def locked(ctx, name="connections", *, wait=KEYS_LOCK_WAIT):
    """연결 설정(또는 사용량 기록)을 바꾸는 동안의 잠금 — 다른 명령이 쥐고 있으면 `wait` 초 기다리고 못 잡으면 KEYS_BUSY(아무것도 바꾸지 않았다)."""
    lock = KeysLock(ctx.workspace.locks_dir, name, now=ctx.now)
    lock.acquire_waiting(wait)
    try:
        yield lock
    finally:
        lock.release()


# ---- 항목 고르기 ------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Row:
    ordinal: int
    entry: Entry


def numbered(entries, registry=PURPOSES):
    """항목들 → 순번을 붙인 줄들(용도 순서 → 항목 순서). 순번은 항목을 지우면 뒤가 당겨진다."""
    position = {key: index for index, key in enumerate(registry)}
    ordered = sorted(entries, key=lambda item: (position.get(item.purpose, 999), item.order, item.entry_id))
    return [Row(index, item) for index, item in enumerate(ordered, start=1)]


def short_id(entry_id):
    return entry_id[:DELETE_PREFIX]


def label_of(entry):
    return f"{entry.name}({entry.purpose}, 번호 {short_id(entry.entry_id)})"


def _not_found(what, detail=""):
    return AppError("CONNECTION_NOT_FOUND", {"항목": what}, detail=detail)


def resolve(rows, text):
    """순번(1~99)이나 항목 번호(전체, 또는 앞 4자 이상 — 겹치지 않을 때) → 그 줄. 없거나 앞부분이 둘 이상과 맞으면 CONNECTION_NOT_FOUND."""
    wanted = text.strip() if isinstance(text, str) else ""
    if not wanted:
        raise _not_found("(비어 있음)", "항목 번호를 적는다 — 목록의 순번이나 번호의 앞 4자 이상")
    if re.fullmatch(r"[1-9][0-9]{0,%d}" % (MAX_ORDINAL_DIGITS - 1), wanted):
        number = int(wanted)
        if number > len(rows):
            raise _not_found(f"순번 {number}", f"항목은 {len(rows)}개뿐이다 — `keys list` 로 순번을 확인한다")
        return rows[number - 1]
    exact = [row for row in rows if row.entry.entry_id == wanted.lower()]
    if exact:
        return exact[0]
    if len(wanted) < MIN_PREFIX:
        raise _not_found("번호가 너무 짧음", f"번호는 목록의 순번이거나 번호의 앞 {MIN_PREFIX}자 이상으로 적는다")
    found = [row for row in rows if row.entry.entry_id.startswith(wanted.lower())]
    if not found:
        raise _not_found("번호에 맞는 항목 없음")
    if len(found) > 1:
        raise _not_found("번호가 여러 항목과 겹침", "겹치는 항목: " + " · ".join(f"순번 {row.ordinal} {label_of(row.entry)}" for row in found) + " — 더 긴 번호를 적는다")
    return found[0]


# ---- 상태 ---------------------------------------------------------------------------------------------------------------------------
def _parse_stamp(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def entry_status(entry, spec, *, now, secret_present=True, valid_hours=CHECK_VALID_HOURS):
    """항목 하나의 상태(5종 중 하나). 한도에 걸린 것(`rate_limited`)은 사용량 기록을 아는 쪽(quota)이 덧붙인다.
    `connected` 는 이 용도의 실제 호출 코드가 있고(`spec.implemented`), 시험 성공 기록이 있고, 유효 기간 안이고, 보관소에 값이 있을 때만이다."""
    if entry.state == OFF:
        return NOT_CONNECTED
    if entry.check_result == CHECK_AUTH:
        return AUTH_ERROR
    if not secret_present:
        return NEEDS_CHECK
    if spec.implemented and entry.check_result == CHECK_OK and entry.last_ok_at:
        if now - _parse_stamp(entry.last_ok_at) <= timedelta(hours=valid_hours):
            return CONNECTED
    return NEEDS_CHECK


def primary_entry(data, purpose):
    """이 용도에서 가장 먼저 쓰이는 항목(순서대로 첫 `사용` 항목) 또는 None."""
    return next((item for item in data.of_purpose(purpose) if item.state == ACTIVE), None)


AUTH_CLEAR, AUTH_BAD, AUTH_UNCLEAR = "clear", "auth_failed", "unclear"


def auth_state(entry, *, now, valid_hours=CHECK_VALID_HOURS):
    """항목의 인증 상태(Fail-Closed 가 신규 호출을 열어도 되는지) — `clear`(시험 성공 기록이 유효 기간 안) · `auth_failed`(인증 실패로 멈춤) · `unclear`(시험 성공 기록이 없거나 오래됐다 — '연결 확인 필요').
    `entry_status` 와 달리 `implemented` 는 보지 않는다(호출 코드가 생기기 전에는 아무도 이 판정으로 호출하지 않는다 — 틀만 있다)."""
    if entry.check_result == CHECK_AUTH:
        return AUTH_BAD
    if entry.check_result == CHECK_OK and entry.last_ok_at and now - _parse_stamp(entry.last_ok_at) <= timedelta(hours=valid_hours):
        return AUTH_CLEAR
    return AUTH_UNCLEAR


def listed_purposes(data, registry=PURPOSES):
    """화면에 보일 용도 이름들 — 옛 용도는 그 용도의 항목이 남아 있을 때만 보인다."""
    return tuple(key for key, spec in registry.items() if not spec.legacy_to or data.of_purpose(key))


def stage_threshold(provider, stage):
    """단계가 시작되는 월 사용량의 경계 — 콘솔 월 한도 × 비율. 호출 뒤 사용량이 이 값을 **넘으면** 그 단계다(같으면 아직 아니다)."""
    return provider.console_limit * stage.percent // 100


def stage_of(provider, used_after):
    """호출을 하고 난 뒤의 이번 달 사용량이 `used_after` 일 때의 단계(비율이 가장 높은 것) 또는 None."""
    found = None
    for stage in sorted(provider.stages, key=lambda item: item.percent):
        if used_after > stage_threshold(provider, stage):
            found = stage
    return found


def secret_present(ctx, entry, keystore):
    """보관소에 이 항목의 값이 있나(True/False) — 보관소를 못 열면 None. 값 자체는 꺼내지 않는다."""
    if keystore is None:
        return None
    try:
        return keystore.exists(entry.ref)
    except AppError:
        return None


def purpose_status(ctx, data, purpose, registry=PURPOSES, keystore=None):
    """용도의 상태(5종 중 하나) — 첫 `사용` 항목의 상태. 항목이 없으면 `연결 안 됨`(키가 없는 것은 오류가 아니다)."""
    first = primary_entry(data, purpose)
    if first is None:
        return NOT_CONNECTED
    present = secret_present(ctx, first, keystore)
    return entry_status(first, registry[purpose], now=ctx.now(), secret_present=bool(present))


# ---- 목록(마스크된 표시만) -------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class EntryView:
    ordinal: int
    entry: Entry
    status: str

    def to_dict(self):
        entry = self.entry
        return {"ordinal": self.ordinal, "entry_id": entry.entry_id, "purpose": entry.purpose, "provider": entry.provider, "name": entry.name, "project": entry.project, "order": entry.order,
                "state": entry.state, "state_text": STATE_TEXT[entry.state], "status": self.status, "status_text": STATUS_TEXT[self.status],
                "created_at": entry.created_at, "checked_at": entry.checked_at, "last_ok_at": entry.last_ok_at, "check_result": entry.check_result,
                "terms_ack_at": entry.terms_ack_at}


def list_entries(ctx, *, purpose=None, registry=PURPOSES, keystore=None):
    """키 항목 목록(읽기만 한다) — 보이는 것은 제공자·항목 번호·등록 여부(상태)·마지막 연결 시험·등록 시각뿐이다(PCSEC1 H2). 키 원문·일부 글자(끝 4자·앞부분·접두어·길이)는 만들지도 읽지도 않는다. `keystore` 를 주면 값이 보관소에 **있는지만** 묻는다(`exists`) — 못 읽으면 그 항목은 `연결 확인 필요`."""
    data = load(ctx, registry)
    now = ctx.now()
    views = []
    for row in numbered(data.entries, registry):
        if purpose is not None and row.entry.purpose != purpose:
            continue
        spec = registry[row.entry.purpose]
        present = secret_present(ctx, row.entry, keystore)
        views.append(EntryView(row.ordinal, row.entry, entry_status(row.entry, spec, now=now, secret_present=bool(present))))
    return views


# ---- 추가 ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class AddResult:
    entry: Entry
    notes: tuple               # 쉬운 한국어 안내(예: 같은 묶음이라 한도가 늘지 않는다)


def _labelled_secret(value):
    """`client_secret=값`·`Cookie: …`·`Authorization: Bearer …` 처럼 가리기 규칙이 가릴 글이 이름·소속 프로젝트에 들어 있나(PCSEC1V — 이 두 칸은 비밀이 아닌 칸이라 `connections.json` 에 평문으로 남는다).
    참·거짓만 돌려주고 값은 이 함수 밖으로 나가지 않는다."""
    from ..security.mask import mask                       # 늦게 가져온다(가리기 모듈은 vendor/ 를 먼저 불러온다)
    return isinstance(value, str) and mask(value) != value


def _check_label(what, value, *, max_len, required):
    problem = shape.label_problem(value, max_len=max_len)
    if not problem and required and not value:
        problem = "비어 있습니다"
    if not problem and _labelled_secret(value):
        problem = "키나 토큰처럼 보이는 글이 들어 있습니다(이름에는 키를 적지 않습니다)"
    if problem:
        raise AppError("KEY_INVALID_SHAPE", {"항목": what, "이유": problem})


def _bucket_of(spec, fields, project):
    """한도 묶음 이름 — 클라이언트 ID 같은 '앱을 가리키는 칸'이 있으면 그 값의 해시(같은 앱이면 같은 묶음), 없으면 소속 프로젝트 이름(비워 두면 '미지정' 하나로 본다 — 한도가 늘지 않는다고 보는 쪽이 안전하다)."""
    if spec.identity_field and spec.identity_field in fields:
        return "id-" + shape.short_digest(fields[spec.identity_field])
    folded = " ".join(project.split()).casefold() or "(미지정)"
    if len(folded) > 70:                                       # 소문자로 바꾸면 길어지는 글자(ß 등)가 있어도 파일의 묶음 이름 길이 제한을 넘지 않게
        folded = folded[:60] + "~" + shape.short_digest(folded)
    return "p-" + folded


def check_fields(spec, fields):
    """칸 이름·모양 검사. 어떤 오류에도 입력한 값은 담지 않는다(칸 이름은 레지스트리의 것만 적는다)."""
    if not isinstance(fields, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in fields.items()):
        raise AppError("KEY_INVALID_SHAPE", {"항목": "입력", "이유": "칸 이름과 값이 모두 글이어야 합니다"})
    expected = [item.name for item in spec.fields]
    if set(fields) != set(expected):
        missing = [name for name in expected if name not in fields]
        why = ("빠진 칸이 있습니다: " + ", ".join(missing)) if missing else "이 용도에 없는 칸이 있습니다"
        raise AppError("KEY_INVALID_SHAPE", {"항목": "입력 칸", "이유": f"{why}(이 용도의 칸: {', '.join(expected)})"})
    for item in spec.fields:
        problem = shape.value_problem(fields[item.name], min_len=item.min_len, max_len=item.max_len, charset=item.charset)
        if problem:
            raise AppError("KEY_INVALID_SHAPE", {"항목": item.label, "이유": problem})
    encode_fields(fields)                                      # 보관소 한도(2,560바이트)를 먼저 확인한다 — KEY_TOO_LONG


def refuse_legacy(spec, registry=PURPOSES):
    """옛 용도(`legacy_to`)에는 새 항목을 더하지 않는다 — 옛 항목은 읽기만 하고 키는 지우지 않는다. 새 키는 새 용도에 넣으라고 쉬운 한국어로 알린다. 아니면 아무것도 하지 않는다(명령줄은 키를 묻기 전에 이것을 먼저 부른다)."""
    if spec.legacy_to:
        target = registry.get(spec.legacy_to)
        raise AppError("KEY_INVALID_SHAPE", {"항목": "용도", "이유": f"옛 용도라 새 항목을 더하지 못합니다 — 새 키는 '{target.label if target else spec.legacy_to}'({spec.legacy_to})에 넣습니다. 옛 항목의 키는 지우지 않았습니다"})


BLOGGER_PURPOSE = "blogger"
BLOGGER_INPUT_OFF = "이 시험 버전에서는 Blogger 로그인 정보를 받지 않습니다 — Blogger 초안 기능을 만들 때 따로 검증한 뒤에 열립니다(저장된 항목은 `keys remove` 로 지웁니다)"      # 오류 문구 칸(160자)에 다 들어가게 짧게


def accepts_input(spec):
    """이 빌드에서 그 용도에 새 키 입력을 받는가 — 키를 받는 용도(`takes_keys`)이고, Blogger 는 입력이 열려 있을 때(`capabilities.BLOGGER_OAUTH_INPUT`, 이 빌드는 False — 호출 코드가 없다)만이다.
    저장 구조(자격 증명 관리자·`connections.json`)와 이미 저장된 항목의 읽기·지우기는 그대로이고 **새 입력만** 막는다(PCSEC1 — 운영자 결정 2026-11-11)."""
    if not spec.takes_keys:
        return False
    return spec.key != BLOGGER_PURPOSE or capabilities.blogger_oauth_input_enabled()


GITHUB_OFF_NOTE = "이 시험 버전은 글을 GitHub 에 올리지 않아요 — 이 앱은 키를 받지 않고 컴퓨터의 Git 로그인도 쓰지 않습니다(외부 게시가 꺼져 있습니다)."      # 오류 문구 칸(160자)을 넘지 않는다


def purpose_note(spec):
    """용도의 안내 글 — GitHub 저장소는 외부 게시가 꺼진 빌드에서 'Git 로그인을 쓴다' 대신 '올리지 않는다' 고 사실대로 말한다(PCSEC1 D7). 그 밖의 용도는 표의 안내 그대로다."""
    if spec.key == "github_repo" and not capabilities.external_write_enabled():
        return GITHUB_OFF_NOTE
    return spec.note


def refuse_unavailable(spec):
    """이 빌드에서 입력을 받지 않는 용도(Blogger)에 키를 넣으려 하면 **키를 묻기 전에** 같은 안내로 거절한다(`add_entry`·`keys add` 가 같은 규칙을 쓴다)."""
    if spec.takes_keys and not accepts_input(spec):
        raise AppError("KEY_INVALID_SHAPE", {"항목": "용도", "이유": BLOGGER_INPUT_OFF})


def check_room(spec, chosen, mine):
    """이 제공자에 키 항목을 하나 더할 자리가 있는지 — 없으면 `KEY_ENTRY_LIMIT`(화면·명령줄·`add_entry` 가 같은 규칙을 쓴다). `mine` 은 이 용도의 항목들이다.
    ① 같은 제공자의 항목 수가 제공자 상한(`Purpose.entry_cap`, 운영자 정책 표)에 닿았거나 ② 용도의 항목 수가 읽을 때의 천장(`Purpose.max_entries`)에 닿았으면 거절한다 — 더하기만 막고 이미 있는 항목은 건드리지 않는다."""
    cap = spec.entry_cap(chosen.key)
    if len([item for item in mine if item.provider == chosen.key]) >= cap:
        shown = cap
    elif len(mine) >= spec.max_entries:
        shown = spec.max_entries
    else:
        return
    detail = (ENTRY_LIMIT_DETAIL if spec.max_entries == 1 else PROVIDER_LIMIT_DETAIL) if shown == 1 else ""
    raise AppError("KEY_ENTRY_LIMIT", {"용도": spec.label, "개수": str(shown)}, detail=detail)


def add_entry(ctx, purpose, *, name, fields, project="", provider="", state=ACTIVE, terms_ack=False, keystore=None, registry=PURPOSES, new_id=None):
    """항목 하나를 더한다 — 값은 보관소에, 메타데이터는 `connections.json` 에. 모든 검사를 마친 뒤에야 보관소에 쓴다. 오류 문구에 입력한 값은 없다."""
    spec = registry.get(purpose) if isinstance(purpose, str) else None
    if spec is None:
        raise _not_found("용도 이름")
    if not spec.takes_keys:
        raise AppError("KEY_INVALID_SHAPE", {"항목": "용도", "이유": purpose_note(spec) or "이 용도는 앱이 키를 받지 않습니다"})
    refuse_legacy(spec, registry)
    refuse_unavailable(spec)                                  # Blogger 입력은 이 빌드에서 받지 않는다(서비스·명령줄·화면이 같은 규칙)
    chosen = spec.provider(provider)
    if chosen is None:
        raise AppError("KEY_INVALID_SHAPE", {"항목": "제공자", "이유": "이 용도의 제공자는 " + ", ".join(spec.provider_keys()) + " 중에서 고릅니다"})
    provider = chosen.key
    if state not in STATES:
        raise AppError("KEY_INVALID_SHAPE", {"항목": "상태", "이유": "사용·예비·꺼짐 중에서 고릅니다"})
    _check_label("이름", name, max_len=MAX_NAME_CHARS, required=True)
    _check_label("소속 프로젝트", project, max_len=MAX_PROJECT_CHARS, required=False)
    check_fields(spec, fields)
    for item in spec.fields:                                  # 이름·프로젝트에 키 값이 그대로 들어 있으면(칸을 잘못 넣음) 파일에 남기 전에 거절한다
        value = fields[item.name]
        if len(value) >= 6 and (value in name or value in project):
            raise AppError("KEY_INVALID_SHAPE", {"항목": "이름", "이유": "키 값이 이름이나 소속 프로젝트에 들어 있습니다"})
    keystore = ctx.get_keystore() if keystore is None else keystore
    with locked(ctx):
        data = load(ctx, registry)
        mine = data.of_purpose(purpose)
        check_room(spec, chosen, mine)
        same = [item for item in mine if item.provider == provider]                 # 둘째 키 약관 확인은 같은 서비스(제공자)의 둘째 키에만이다
        asks_terms = bool(same) and chosen.second_key_needs_terms
        if asks_terms and not terms_ack:
            raise AppError("KEY_FAILOVER_TERMS_REQUIRED", {"용도": spec.label})
        if any(item.name == name for item in mine):
            raise AppError("KEY_DUPLICATE", {"항목": "같은 이름", "이유": "같은 용도에 같은 이름의 항목이 이미 있습니다"})
        for item in mine:
            if _same_value(keystore, item, fields):
                raise AppError("KEY_DUPLICATE", {"항목": "같은 값", "이유": f"같은 값이 이미 있습니다(항목 {item.name})"})
        entry_id = new_id() if new_id else secrets.token_hex(16)
        stamp = ctx.stamp()
        bucket = _bucket_of(spec, fields, project)
        entry = Entry(entry_id, purpose, provider, name, project, max((item.order for item in mine), default=0) + 1, state, stamp, "", "", CHECK_NONE, bucket, stamp if asks_terms else "")
        notes = []
        if any(item.bucket == bucket and item.provider == provider for item in mine):
            notes.append("같은 앱(소속 프로젝트)의 키라서 한도가 늘지 않습니다 — 한도에 걸렸을 때 이 키로는 넘어가지 않습니다.")
        keystore.put(entry.ref, fields)
        try:
            save(ctx, replace_data(data, entries=data.entries + (entry,)), registry)
        except AppError:
            _rollback(keystore, entry)
            raise
    if asks_terms:
        notes.append(TERMS_NOTICE)
    return AddResult(entry, tuple(notes))


def replace_data(data, **changes):
    return Data(changes.get("entries", data.entries), changes.get("policies", data.policies))


def _rollback(keystore, entry):
    """메타데이터를 쓰지 못했을 때 방금 보관소에 넣은 값을 되돌린다 — 못 지우면 숨기지 않고 오류로 알린다."""
    try:
        keystore.delete(entry.ref)
    except AppError as error:
        raise AppError("KEY_STORE_UNAVAILABLE", detail=f"{ROLLBACK_FAILED_DETAIL}({error.code}) — `keys list` 에서 '연결 확인 필요' 로 보이면 지운다") from None


def _same_value(keystore, entry, fields):
    """이미 있는 항목의 보관된 값이 지금 넣으려는 값과 같은지 **보관소의 값을 직접 비교**한다(파일에는 값에서 만든 지문이 없다). 값이 보관소에 없으면(지워졌다) 같지 않다.
    보관소를 읽을 수 없으면 중복인지 알 수 없으니 **저장을 멈추고** 보관소의 오류를 그대로 알린다(막는 쪽 — 중복이라고 잘못 말하지도, 확인 없이 저장하지도 않는다)."""
    found = keystore.get(entry.ref)
    if found is None:
        return False
    return found.to_dict() == dict(fields)


# ---- 바꾸기 ----------------------------------------------------------------------------------------------------------------------------
def _update_entry(data, entry_id, **changes):
    items = tuple(Entry(**{**item.to_dict(), **changes}) if item.entry_id == entry_id else item for item in data.entries)
    return Data(items, data.policies)


def _name_holds_value(fields, name):
    """보관된 값 중 6글자 이상인 것이 이름에 그대로 들어 있나(칸을 잘못 붙여 넣음) — 참·거짓만 돌려주고 값은 이 함수 밖으로 나가지 않는다."""
    return any(len(value) >= 6 and value in name for value in fields.to_dict().values())


def rename_entry(ctx, text, name, *, keystore=None, registry=PURPOSES):
    """항목의 이름(별칭)만 바꾼다 — 값·상태·순서는 그대로다. 이름 모양은 더할 때와 같은 검사(키처럼 보이는 글 거절)이고, 같은 용도의 **다른** 항목과 이름이 같으면 `KEY_DUPLICATE`,
    보관된 값이 이름에 그대로 들어 있으면 `KEY_INVALID_SHAPE`(값은 문구에 없다)로 거절한다 — 키를 이름 칸에 잘못 붙여 넣어 이 파일에 남는 일을 막는다. 보관소를 열 수 없으면(`KEY_STORE_UNAVAILABLE`) 그 확인을 못 하므로 바꾸지 않는다.
    같은 이름이면 바뀐 것이 없다. → (항목, 이전 이름)"""
    _check_label("이름", name, max_len=MAX_NAME_CHARS, required=True)
    keystore = ctx.get_keystore() if keystore is None else keystore
    with locked(ctx):
        data = load(ctx, registry)
        entry = resolve(numbered(data.entries, registry), text).entry
        before = entry.name
        if before == name:
            return entry, before
        if any(item.name == name and item.entry_id != entry.entry_id for item in data.of_purpose(entry.purpose)):
            raise AppError("KEY_DUPLICATE", {"항목": "같은 이름", "이유": "같은 용도에 같은 이름의 항목이 이미 있습니다"})
        stored = keystore.get(entry.ref)
        if stored is not None and _name_holds_value(stored, name):
            raise AppError("KEY_INVALID_SHAPE", {"항목": "이름", "이유": "키 값이 이름이나 소속 프로젝트에 들어 있습니다"})
        data = _update_entry(data, entry.entry_id, name=name)
        save(ctx, data, registry)
        return next(item for item in data.entries if item.entry_id == entry.entry_id), before


def set_state(ctx, text, state, *, registry=PURPOSES):
    """항목의 상태를 바꾼다(사용·예비·꺼짐). 같은 상태면 바꾼 것이 없다. → (항목, 이전 상태)"""
    if state not in STATES:
        raise AppError("KEY_INVALID_SHAPE", {"항목": "상태", "이유": "사용·예비·꺼짐 중에서 고릅니다"})
    with locked(ctx):
        data = load(ctx, registry)
        row = resolve(numbered(data.entries, registry), text)
        before = row.entry.state
        if before != state:
            data = _update_entry(data, row.entry.entry_id, state=state)
            save(ctx, data, registry)
        return next(item for item in data.entries if item.entry_id == row.entry.entry_id), before


def reorder(ctx, purpose, texts, *, registry=PURPOSES):
    """이 용도의 항목 순서를 정한다 — 적은 것이 앞에 오고 안 적은 것은 원래 순서대로 뒤에 온다. 다른 용도의 항목이나 같은 항목을 두 번 적으면 거절."""
    if purpose not in registry:
        raise _not_found("용도 이름")
    with locked(ctx):
        data = load(ctx, registry)
        rows = numbered(data.entries, registry)
        chosen = []
        for text in texts:
            row = resolve(rows, text)
            if row.entry.purpose != purpose:
                raise AppError("KEY_INVALID_SHAPE", {"항목": "순서", "이유": "다른 용도의 항목이 들어 있습니다"})
            if row.entry.entry_id in chosen:
                raise AppError("KEY_INVALID_SHAPE", {"항목": "순서", "이유": "같은 항목을 두 번 적었습니다"})
            chosen.append(row.entry.entry_id)
        rest = [item.entry_id for item in data.of_purpose(purpose) if item.entry_id not in chosen]
        position = {entry_id: index for index, entry_id in enumerate(chosen + rest, start=1)}
        items = tuple(replace_order(item, position[item.entry_id]) if item.entry_id in position else item for item in data.entries)
        save(ctx, Data(items, data.policies), registry)
        return [item for item in sorted(items, key=lambda value: value.order) if item.purpose == purpose]


def replace_order(entry, order):
    return Entry(**{**entry.to_dict(), "order": order})


@dataclass(frozen=True)
class RemoveResult:
    entry: Entry
    keep_cache: bool           # 지운 뒤 캐시를 남길지 — 사용자가 고른 값(캐시 자체는 나중의 '이미지 서비스' 묶음이 만든다)
    purpose_label: str


def _confirm_remove(what, number, confirmed):
    if confirmed is not True:
        raise AppError("CONFIRMATION_REQUIRED", {"항목": what}, detail=f"지우면 보관소의 키도 함께 지워지고 되돌릴 수 없습니다 — 이 항목이 맞으면 번호 앞 {DELETE_PREFIX}자로 지웁니다: "
                                                                    f"`keys remove {number} --yes` (순번은 지울 때마다 당겨지므로 순번으로는 지우지 않습니다)")


def remove_entry(ctx, text, *, confirmed, keep_cache=False, keystore=None, registry=PURPOSES):
    """항목을 지운다 — 보관소의 값을 먼저 지우고 메타데이터를 지운다. `confirmed` 가 True 가 아니면 아무것도 지우지 않고, 순번이나 짧은 앞부분으로는 지우지 않는다(번호 앞 8자 이상)."""
    keystore = ctx.get_keystore() if keystore is None else keystore
    with locked(ctx):
        data = load(ctx, registry)
        row = resolve(numbered(data.entries, registry), text)
        entry = row.entry
        what = f"키 항목 지우기 — {entry.name}({registry[entry.purpose].label}, 순번 {row.ordinal}, 번호 {short_id(entry.entry_id)})"
        _confirm_remove(what, short_id(entry.entry_id), confirmed)
        wanted = text.strip().lower()
        if not (len(wanted) >= DELETE_PREFIX or wanted == entry.entry_id):
            raise AppError("CONNECTION_DELETE_NEEDS_NUMBER", {"항목": what}, detail=f"아무것도 지우지 않았습니다 — 이 항목을 지우려면: `keys remove {short_id(entry.entry_id)} --yes`")
        keystore.delete(entry.ref)
        rest = [item for item in data.of_purpose(entry.purpose) if item.entry_id != entry.entry_id]
        renumber = {item.entry_id: index for index, item in enumerate(rest, start=1)}
        items = tuple(replace_order(item, renumber[item.entry_id]) if item.entry_id in renumber else item for item in data.entries if item.entry_id != entry.entry_id)
        save(ctx, Data(items, data.policies), registry)
    return RemoveResult(entry, bool(keep_cache), registry[entry.purpose].label)


def set_policy(ctx, purpose, *, on_limit=None, tier=None, registry=PURPOSES):
    """용도의 한도 정책을 바꾼다(`on_limit`: 절약 모드만/허용된 다음 키로 전환, `tier`: 한도 등급). 바꾼 시각을 적는다. → 새 Policy"""
    spec = registry.get(purpose) if isinstance(purpose, str) else None
    if spec is None:
        raise _not_found("용도 이름")
    if on_limit is not None and on_limit not in ON_LIMIT:
        raise AppError("KEY_INVALID_SHAPE", {"항목": "한도 정책", "이유": "save 나 failover 중에서 고릅니다"})
    if tier is not None and tier != "" and not any(tier in provider.tier_names() and len(provider.tier_names()) > 1 for provider in spec.providers):
        raise AppError("KEY_INVALID_SHAPE", {"항목": "한도 등급", "이유": "이 용도에는 고를 수 있는 한도 등급이 없거나 이름이 다릅니다"})
    with locked(ctx):
        data = load(ctx, registry)
        before = data.policy(purpose)
        after = Policy(before.on_limit if on_limit is None else on_limit, before.tier if tier is None else tier, ctx.stamp())
        policies = tuple(sorted({**dict(data.policies), purpose: after}.items()))
        save(ctx, Data(data.entries, policies), registry)
    return after


def mark_check(ctx, entry_id, result, *, registry=PURPOSES):
    """연결 시험·실제 호출의 결과를 항목에 적는다(`ok`·`auth_failed`·`error`). 인증 실패면 그 항목은 '인증 정보 오류' 로 사용이 멈춘다(다른 키로 넘어가지 않는다). → 바뀐 항목 또는 None"""
    if result not in (CHECK_OK, CHECK_AUTH, CHECK_ERROR):
        raise ValueError("확인 결과는 ok·auth_failed·error 중 하나여야 한다")
    with locked(ctx):
        data = load(ctx, registry)
        entry = next((item for item in data.entries if item.entry_id == entry_id), None)
        if entry is None:
            return None
        stamp = ctx.stamp()
        changes = {"checked_at": stamp, "check_result": result}
        if result == CHECK_OK:
            changes["last_ok_at"] = stamp
        data = _update_entry(data, entry_id, **changes)
        save(ctx, data, registry)
        return next(item for item in data.entries if item.entry_id == entry_id)


def mark_call_ok(ctx, entry_id, *, registry=PURPOSES):
    """성공한 실제 호출을 항목에 적는다 — 마지막 성공 시각(`last_ok_at`)을 지금으로, 확인 결과를 `ok` 로 해서 인증 '맑음'(`auth_state`)의 24시간 창을 이어 준다(호출이 계속 성공하는 동안 '연결 확인 필요' 로 떨어지지 않는다).
    `checked_at`(마지막 시험 시각)은 건드리지 않는다 — 연결 시험의 60초 규칙은 시험 호출만 센다. 인증 실패로 멈춘 항목(`auth_failed`)은 되살리지 않는다(멈춘 뒤에 도착한 성공 보고가 멈춤을 풀지 못하게).
    실패·모호한 결과로는 부르지 않는다(부르는 쪽 `quota` 가 가린다). → 바뀐 항목 또는 None(항목이 없거나 되살리지 않음)"""
    with locked(ctx):
        data = load(ctx, registry)
        entry = next((item for item in data.entries if item.entry_id == entry_id), None)
        if entry is None or entry.check_result == CHECK_AUTH:
            return None
        data = _update_entry(data, entry_id, check_result=CHECK_OK, last_ok_at=ctx.stamp())
        save(ctx, data, registry)
        return next(item for item in data.entries if item.entry_id == entry_id)


# ---- 연결 시험(제공자 시험 함수를 주입받는다) -------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ProviderResult:
    outcome: str               # ok · auth_failed · rate_limited · error
    headers: object = None     # 응답 머리글(남은 횟수 보정용) — 없을 수 있다


@dataclass(frozen=True)
class TestResult:
    __test__ = False           # 시험 모음이 이 이름을 시험 클래스로 오해하지 않게
    ran: bool
    reason: str                # ran 이 False 일 때 이유 코드: not_ready · too_soon · no_value
    outcome: str = ""
    entry: object = None
    wait_seconds: int = 0
    message: str = ""


def test_entry(ctx, text, tester=None, *, keystore=None, guard=None, registry=PURPOSES):
    """연결 시험 — **최소 호출 한 번**. 이 용도에 실제 호출 코드가 없거나(`implemented` 가 거짓) 시험 함수가 없으면 아무것도 하지 않는다('준비 중').
    같은 키는 `TEST_MIN_INTERVAL` 초 안에 다시 시험하지 않는다. 인증 실패면 그 항목을 '인증 정보 오류' 로 두고 사용을 멈춘다(재시도하지 않는다).
    `guard`(사용량 기록)를 주면 시험 호출도 한도에 센다."""
    data = load(ctx, registry)
    row = resolve(numbered(data.entries, registry), text)
    entry, spec = row.entry, registry[row.entry.purpose]
    if tester is None or not spec.implemented:
        return TestResult(False, "not_ready", entry=entry, message="시험 기능 준비 중 — 이 용도는 아직 실제 호출을 하지 않습니다")
    now = ctx.now()
    if entry.checked_at:
        waited = (now - _parse_stamp(entry.checked_at)).total_seconds()
        if 0 <= waited < TEST_MIN_INTERVAL:
            return TestResult(False, "too_soon", entry=entry, wait_seconds=int(TEST_MIN_INTERVAL - waited) + 1, message="같은 키는 60초 안에 다시 시험하지 않습니다")
    keystore = ctx.get_keystore() if keystore is None else keystore
    fields = keystore.get(entry.ref)
    if fields is None:
        return TestResult(False, "no_value", entry=entry, message="보관소에 키가 없습니다 — 항목을 지우고 다시 추가합니다")
    lease = None
    if guard is not None:
        lease = guard.acquire_entry(entry, calls=1, priority="critical")
        if not hasattr(lease, "entry_id"):                      # 한도에 걸려 시험 호출을 할 수 없다(Denied)
            return TestResult(False, "not_ready", entry=entry, message=getattr(lease, "reason", "지금은 시험할 수 없습니다"))
    try:
        found = tester(spec, entry, fields)
        outcome = found.outcome if isinstance(found, ProviderResult) else CHECK_ERROR
    except Exception as problem:                                # 시험 함수의 어떤 실패도 키 값 없이 '오류' 로만 적는다
        found, outcome = None, CHECK_ERROR
        detail = type(problem).__name__
    else:
        detail = ""
    result = {"ok": CHECK_OK, "auth_failed": CHECK_AUTH}.get(outcome, CHECK_ERROR)
    if lease is not None:
        guard.report(lease, {"ok": "ok", "auth_failed": "auth_failed", "rate_limited": "rate_limited"}.get(outcome, "other_error"), headers=getattr(found, "headers", None))
    changed = mark_check(ctx, entry.entry_id, result, registry=registry)
    return TestResult(True, "", outcome, changed, message=detail)


# ---- 진단 정보(비밀·끝 4자 없음) -------------------------------------------------------------------------------------------------------
def diagnostic_summary(ctx, registry=PURPOSES):
    """진단 보고서·내보내기에 실을 수 있는 요약 — 용도별 항목 수·상태 이름뿐이다. 값·끝 4자·번호·이름·프로젝트는 싣지 않는다."""
    data = load(ctx, registry)
    return {"purposes": [{"purpose": key, "entries": len(data.of_purpose(key)), "active": len([item for item in data.of_purpose(key) if item.state == ACTIVE])} for key in listed_purposes(data, registry)]}
