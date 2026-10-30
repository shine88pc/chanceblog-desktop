# 구조 — 데스크톱 작업대와 클라우드 파이프라인 (기술 구조의 단일 기준 문서)

> 이 문서는 설계다. 구현이 따라가며 바뀌면 같은 PR 에서 이 문서를 고친다. 결정과 근거는 [`DECISIONS.md`](DECISIONS.md). 어느 AI 코딩 도구든 이 문서와 `AGENTS.md` 만으로 같은 구조·규칙으로 일할 수 있어야 한다.

## 1. 무엇을 만드나

개인용 Windows PC 에서 **하나의 원본 글**을 쓰고(직접 쓰거나 기존 원고를 불러와서), 검사하고, 플랫폼별로 **변환·미리보기·승인**한 뒤 내보내는 프로그램이다. **AI 없이 모든 핵심 기능이 동작한다**(§8). 무료 AI 는 몇 가지 선택 보조 기능에 한정하고 기본값은 꺼짐이다(§7).

| 플랫폼 | 내보내는 방식 | 사람이 하는 일 |
|---|---|---|
| GitHub Pages(Chance 블로그) | **연결해 둔 기존 `chanceblog` 로컬 저장소**에 글·이미지를 만들고, 승인 뒤 commit·push → **기존 자동 배포 흐름**(`pages.yml`)이 사이트를 배포 | 미리보기에서 승인 |
| Google Blogger(영문·한글) | 공식 API 로 **초안 저장·수정**(자동 공개 없음) | Blogger 화면에서 발행 |
| 네이버 블로그 A·B | **복사 패키지**(제목·본문·이미지 위치·태그) 제공, 글쓰기 페이지 열기 | 에디터에 붙여넣고 발행, 발행 주소 입력 |
| 티스토리 | **제외·격리**(D-01) | — |

## 2. 큰 그림 — 두 저장소

```text
[클라우드 — chanceblog(별도 저장소), PC 가 꺼져 있어도 AI 없이 돈다]
  GitHub Actions 정기 실행 → pipeline(생성·게이트·발행) → GitHub Pages 자동 · Blogger 초안 · 초안 이슈(네이버)
  감시: 발행 중단 감시 · 확인 필요 모음 · 배포 확인 · 요청 알림(텔레그램)  ← 운영자 호출은 여기로만
        ▲ 이 저장소가 기존 chanceblog 로컬 저장소를 '연결'해 글·이미지를 넣고 push → 기존 자동 배포
[개인 PC — chanceblog-desktop(이 저장소)]
  원고(직접/불러오기) → 검사 → 플랫폼별 변환 → 미리보기·승인 → 내보내기 → 상태·이력
  설치·업데이트: GitHub Releases(초안 → 운영자 공개) → 앱이 확인·백업·검증·적용·롤백
```

원칙: ① 클라우드 자동 발행·감시·알림은 앱이 없어도 **지금 구조 그대로** 계속된다 ② 앱은 사람이 검수하는 경로를 편하게 하는 도구다 ③ 승인(T0~T3)·독립 검증·텔레그램 요청 규칙은 `chanceblog` 의 것을 따른다 ④ 로그인·쿠키·탐지 회피 자동화 없음 ⑤ 유료 호출 없음 ⑥ 오류 안내는 AI 가 아니라 **규칙(오류 코드 + 안내 문구)** 으로 한다([`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)).

## 3. GitHub Pages — 기존 `chanceblog` 로컬 저장소 연결

앱은 설정에 **로컬 `chanceblog` 저장소 경로**를 가진다. 연결할 때 확인한다: 폴더가 git 저장소인가, `origin` 이 `shine88pc/chanceblog` 인가, 작업 트리가 깨끗한가, push 자격(Git 로그인)이 있는가(`git push --dry-run`). 실패하면 이유와 하실 일을 보인다(`PAGES_LOCAL_REPO_INVALID` 등).
- **구현(연결 확인)**: `src/chanceblog_desktop/publish/gitrepo.py` — `inspect_repo`(폴더·`origin`·`main` 브랜치·저장하지 않은 변경 확인, 새 파일은 변경으로 보지 않음)·`sync_latest`(원격 `main` 을 받아 빨리감기로만 맞춤 — 로컬이 앞서거나 갈라져 있으면 건드리지 않고 `PAGES_LOCAL_REPO_DIVERGED`)·`check_push_access`(`git push --dry-run`, 실제로는 올리지 않음). 앱은 사용자의 커밋·변경을 지우거나 되돌리지 않고 브랜치를 바꾸지 않으며, git 이 대화창을 띄우지 않게(`GIT_TERMINAL_PROMPT=0`) 영어 메시지로 실행해 실패를 오류 코드(`GIT_PUSH_AUTH`·`GIT_PUSH_NETWORK`·`GIT_PUSH_REJECTED` 등)로 나눈다.
- **글**: `chanceblog` 의 Chance 글과 같은 형식으로 만든다 — `_posts/<카테고리>/YYYY-MM-DD-<언어>-<시각>.md`, Front Matter 키 `layout`·`date`·`permalink`·`title`·`description`·`category`·`tags`·`lang`·`source_url`·`source_name`·`image`(2026-10-30 저장소 확인). 형식은 첫 구현에서 시험으로 고정하고, `chanceblog` 쪽 규칙(`docs/ARCHITECTURE.md` 와 `pipeline/drafts.py`)이 바뀌면 이쪽도 같은 PR 에서 맞춘다.
- **이미지**: 지금 Chance 는 외부 이미지 주소(Unsplash)를 `image:` 에 쓴다. 앱은 같은 방식과 함께 사용자가 고른 이미지 파일을 저장소 안 정해진 폴더에 두는 방식을 지원한다(폴더·크기 규칙은 첫 구현에서 정한다, 사이트 설정 `_config.yml` 은 건드리지 않는다).
- **발행**: 미리보기에서 승인하면 앱이 **항상 최신 `main` 을 먼저 가져온 뒤**(봇이 같은 `main` 에 직접 커밋한다) 파일을 만들고 commit·push 한다. 이후는 기존 흐름이다: `main` push → `pages.yml` 이 Jekyll 빌드·배포 → 배포 확인. 앱은 Actions 실행 상태를 읽어 성공·실패를 보이고(§6 오류 안내), 발행 주소를 기록한다.
- 클라우드 자동 발행(하루 3슬롯)과 겹치지 않게 같은 날 자동 글 수와 slug 중복을 확인한다. `history.json`(자동 발행 이력) 기록 여부는 첫 구현에서 `chanceblog` 쪽 소비자(감시·상한)를 읽고 정한다.

## 4. 핵심 코드 재사용 — '정해진 버전으로 가져다 쓴다'

`chanceblog` 의 `pipeline/` 에는 이미 시험 4,000여 개로 고정된 코드(검사 `gates.py`, 비밀 패턴 `secret_patterns.py`, 상태 `state.py`, 실패 분류·마스킹 `llm.py` 의 일부, Blogger 어댑터 `publishers/blogger.py`, 복사 패키지 `publishers/issue_package.py`)가 있다. 파이썬 그대로 가져다 쓰면 다시 시험하지 않아도 된다.
- 방식: `vendor/pipeline/` 에 **원본과 한 글자도 다르지 않게** 복사하고 `vendor/VENDOR.json` 에 가져온 저장소·커밋 SHA(40자리)·파일별 SHA-256 을 적는다. 앱은 시작할 때 `chanceblog_desktop.core.use_vendored_core()` 로 `vendor/` 를 `sys.path` 에 올려 `from pipeline import gates` 처럼 쓴다. 갱신은 `python scripts/sync_core.py --source <chanceblog 를 받아 둔 폴더> --ref <커밋·태그·브랜치>`(원본 커밋의 바이트를 그대로 쓰고, 읽기에 실패하면 아무것도 쓰지 않는다). `--check` 와 시험이 `vendor/` 해시와 `VENDOR.json` 이 같은지, 목록 밖 파일이 없는지 확인한다. `.gitattributes` 의 `vendor/** -text` 가 줄바꿈 변환(Windows autocrlf 포함)을 막는다. 코어를 고칠 일이 생기면 `chanceblog` 에서 고쳐 병합한 뒤 다시 가져온다(이 저장소에서 `vendor/` 를 고치지 않는다).
- 지금 가져오는 파일(앱이 쓰는 것만, 목록은 `scripts/sync_core.py` 의 `FILES`): `pipeline/__init__.py`·`console.py`·`gates.py`(발행 전 검사)·`secret_patterns.py`(비밀 모양 검사). 모두 표준 라이브러리만 쓴다. Blogger 어댑터·복사 패키지·상태 등은 그 기능을 만드는 묶음에서 목록에 더한다.
- 서브모듈·패키지 설치 방식은 비개발자 운영과 PC 이관에 부담이라 쓰지 않는다.

## 5. 코드 구성(예정 — `src/chanceblog_desktop/`)

| 모듈 | 하는 일 |
|---|---|
| `app/` | 화면(대시보드·편집기·블로그 프로필·발행 센터·설정·로그). 화면 틀은 PySide6 또는 pywebview 로 첫 구현에서 비교해 정한다(D-04) |
| `content/` | ContentProject·플랫폼 변형·원고 Revision·SQLite 저장·자동 저장·복구·스키마 마이그레이션·기존 원고 불러오기 |
| `render/` | 플랫폼별 변환(Markdown↔HTML, Pages Front Matter, Blogger HTML, 네이버 패키지)과 미리보기 |
| `publish/` | Pages(연결한 로컬 저장소에 쓰기·commit·push·배포 확인), Blogger 초안 저장·수정, 네이버 복사 패키지·상태 |
| `check/` | 발행 전 검사(핵심 코드 `pipeline/gates.py` 를 감싸고 앱 전용 검사 — 두 네이버 블로그 중복 등 — 추가) |
| `errors/` | **오류 코드와 안내 문구 카탈로그**(규칙 기반). 모든 실패는 코드 하나로 모이고 사용자에게 원인·하실 일을 보인다 |
| `update/` | 업데이트 확인·서명 검증·백업·적용·롤백([`RELEASE.md`](RELEASE.md)), 프로그램 버전·변경 이력 |
| `security/` | OS 보안 저장소(Windows 자격 증명 관리자) 접근, 로그 마스킹([`SECURITY.md`](SECURITY.md)) |
| `jobs/` | 예약 작업(발행 예약·배포 확인 반복), 작업 로그 |
| `assist/` | **선택 보조 AI(기본 꺼짐)** — 최소 인터페이스와 아무 일도 안 하는 기본 구현(§7) |

## 6. 오류 안내 — 규칙 기반이 먼저다

실패는 AI 가 아니라 **오류 코드 → 플랫폼별 안내 문구**로 설명한다. 예: Blogger HTTP 401 → `BLOGGER_AUTH_EXPIRED`(인증 만료·다시 로그인 안내), Git push 실패 → `GIT_PUSH_AUTH`/`GIT_PUSH_NETWORK`/`GIT_PUSH_REJECTED`(저장소 인증·네트워크·최신 상태 확인), Actions 실패 → `ACTIONS_RUN_FAILED`(실패한 워크플로·잡 이름과 링크 표시), 파일 생성 실패 → `FILE_WRITE_FAILED`(저장 경로·권한 확인), API 호출 제한 → `API_RATE_LIMITED`(재시도 가능 시간 표시). 코드 목록과 문구는 [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) 가 정본이고, `errors/catalog.py` 는 그 표에서 `scripts/sync_errors.py` 가 **만든 파일**이며 **시험이 둘이 같은지 확인**한다(표만 고치고 다시 만들지 않으면 실패). 표에 없는 코드는 `UNEXPECTED_ERROR` 로 안내해 오류 안내가 또 실패하지 않게 한다. 로그와 오류 보고서에는 키·토큰을 쓰지 않는다.

## 7. 선택 보조 AI — 기본 꺼짐, 최소 인터페이스

범위(필요성이 확인됐을 때만 추가): ① 감시 결과 한 줄 요약 ② 긴 오류 로그의 간단한 설명 ③ 사용자가 확인할 조치 추천 ④ 주간 운영 결과 요약.
- `assist/` 는 작은 인터페이스(`is_configured()`·`summarize(text, task)`)와 아무 일도 하지 않는 기본 구현(`NullAssistant`)만 둔다. **여러 공급자를 두거나 한도 소진 시 자동 전환하는 구조(AI Router)는 만들지 않는다**(D-15). 새 공급자가 필요해지면 그때 새 결정으로 연다.
- **AI 가 없어도 모든 핵심 기능이 동작한다.** AI 연결 실패·키 없음·시간 초과는 그 보조 기능만 건너뛰고(`ASSIST_UNAVAILABLE`) 프로그램 전체 오류로 번지지 않는다. 입력은 소독·마스킹하고 비공개 원고는 보내지 않는다. 출력은 '보조 의견(미검증)'으로 표시하고 어떤 결정·게시에도 직접 쓰지 않는다.
- 기존 Gemini 기능(`chanceblog` 클라우드 파이프라인)은 그대로 두고, 이 앱에서는 선택 기능으로만 연결한다.

## 8. AI 없이 반드시 동작해야 하는 기능 (시험으로 지킨다)

콘텐츠 직접 작성·수정 · 기존 원고 불러오기 · Markdown·HTML 변환 · 플랫폼별 미리보기 · GitHub Pages 게시물 생성·배포 · Blogger 초안 생성·수정 · 네이버 A/B 발행 패키지 생성 · 제목·본문·태그 복사 · 네이버 글쓰기 페이지 열기 · 이미지 파일과 삽입 위치 관리 · 발행 상태와 URL 기록 · 예약 작업 · 배포 성공·실패 감지 · 규칙 기반 오류 안내 · 작업 로그 · 백업·복구 · 프로그램 버전 확인·업데이트.

## 9. 데이터 모델

```text
ContentProject: project_id · title · source_content · references · assets · created_at · updated_at · revision
  └─ PlatformVariant × 플랫폼(github_pages · blogger_en · blogger_ko · naver_a · naver_b): rendered · status · published_url · published_at · error_code
JobLog: job_id · kind · started_at · finished_at · result · error_code · detail(마스킹됨)
```

- API 키 원문은 데이터베이스·프로젝트 파일·로그에 저장하지 않는다.
- 네이버 상태값: `NOT_STARTED` → `DRAFT_GENERATED` → `REVIEW_REQUIRED` → `READY_TO_COPY` → `COPY_COMPLETED` → `PUBLISHED_MANUAL` (`PUBLISH_FAILED`). 두 네이버 블로그는 같은 주제여도 **제목·도입부·문단 구성·태그를 각자 프로필에 맞게 변환하고 각각 검수**하며, 유사도가 기준을 넘으면 경고하고 운영자가 명시 승인해야 `READY_TO_COPY` 가 된다. 같은 원고를 그대로 복제하는 기능은 기본값으로 두지 않는다. 네이버 A·B 는 표시명·URL·주제·대상 독자·말투·카테고리 매핑·기본 태그·금지 표현·이미지 규격·글 길이·발행 주기·발행 이력을 **각자 독립 프로필**로 관리한다.

## 10. 로컬 데이터와 백업

사용자 데이터는 `%LOCALAPPDATA%\ChanceblogDesktop\`(설정·SQLite·이미지·백업·로그)에 둔다. 설치 폴더 밖이라 업데이트가 `current` 만 교체해도 데이터가 남는다. 업데이트 전에 SQLite backup API 로 스냅샷하고 최근 N개를 보관하며, 스키마는 `PRAGMA user_version` 으로 순방향 마이그레이션, 실패하면 백업 복원.

## 11. 버전

Semantic Versioning. 앱·DB 스키마·핵심 코드(`vendor/` 커밋)·플랫폼 어댑터·템플릿 버전을 따로 기록하고 설정 화면과 GitHub Release 에서 같게 보인다. 개발 순서는 운영자 우선순위를 따른다([`DECISIONS.md`](DECISIONS.md) D-12).
