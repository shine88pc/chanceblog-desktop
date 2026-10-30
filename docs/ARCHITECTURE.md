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
- **구현(연결 확인)**: `src/chanceblog_desktop/publish/gitrepo.py` — `inspect_repo`(폴더·`origin`·`main` 브랜치·저장하지 않은 변경 확인, 새 파일은 변경으로 보지 않음)·`sync_latest`(원격 `main` 을 받아 빨리감기로만 맞춤 — 로컬이 앞서거나 갈라져 있으면 건드리지 않고 `PAGES_LOCAL_REPO_DIVERGED`)·`check_push_access`(`git push --dry-run`, 실제로는 올리지 않음). 앱은 사용자의 커밋·변경을 지우거나 되돌리지 않고 브랜치를 바꾸지 않으며, git 이 대화창을 띄우지 않게(`GIT_TERMINAL_PROMPT=0`·입력 장치를 막아 둔다) 영어 메시지로 실행하고(사용자 PC 의 `GIT_DIR` 같은 다른 저장소 설정은 지우되, 사용자의 ssh·자격 증명 설정은 건드리지 않는다), 시간(기본 90초)이 넘으면 git 과 그 손자 프로세스까지 끄고 `NETWORK_TIMEOUT` 으로 알린다(출력은 파이프가 아닌 임시 파일로 받아, 끝난 git 의 손자가 연결을 붙잡고 있어도 기다리며 매달리지 않는다)(받기 뒤 git 이 정리(gc)를 시작하지 않게 `gc.auto=0`). 실패는 출력 문구로 오류 코드(`GIT_PUSH_AUTH`·`GIT_PUSH_NETWORK`·`GIT_PUSH_REJECTED`·`FILE_WRITE_FAILED`·`DISK_FULL` 등)로 나누고, 세부(detail)는 끝 400자만 남기되 자르기 전에 `security/mask.py` 로 가린다. `origin` 은 받는 주소와 올리는 주소(`pushurl` 포함)를 **모두** 확인한다. `sync_latest` 는 원격 main 을 명시한 refspec 으로 받고, 받을 파일과 겹치는 내 파일(추적하지 않는 새 파일·무시(`.gitignore`)한 파일)이 있으면 병합을 시도하지 않고 `PAGES_LOCAL_FILE_IN_THE_WAY`(겹치는 파일 이름을 보여 준다)로 멈추며, git 이 내 변경·내 파일을 지키려고 병합을 거절하면(`PAGES_LOCAL_REPO_DIRTY`·`PAGES_LOCAL_FILE_IN_THE_WAY`) 아무것도 되돌리지 않고, 병합이 파일을 쓰다 멈추면(다른 프로그램이 쓰는 중·디스크 가득·시간 초과) **병합이 쓴 것만**(내용이 원격 main 과 똑같은 파일·그 색인 항목·원격이 지웠거나 이름을 바꾼 파일) 병합 전으로 되돌리고 내가 고친 파일은 건드리지 않는다(원격이 정한 파일 이름이 저장소 밖을 가리키면 무시하고, 경로 인자는 글자 그대로 읽는다 — `GIT_LITERAL_PATHSPECS`). 받기·올리기에서 사용자가 ssh 명령을 따로 정하지 않았으면 `ssh -o BatchMode=yes` 로 질문을 입력 없이 기다리며 멈추는 일을 막는다. `check_push_access` 는 사용자의 `pre-push` 훅을 돌리지 않는다(`--no-verify`).
- **글**: `chanceblog` 의 Chance 글과 같은 형식으로 만든다(2026-10-30 실제 글·생성기 `generator.py` 확인) — 파일 `_posts/<분야 폴더>/YYYY-MM-DD-KR|EN-HHMMSS.md`(한국 시각; 날짜는 파일 이름에서, 주소는 사이트 설정의 `permalink` 가 만든다), 머리말은 한 줄 한 키로 `layout: post`·`title`·`category`·`tags`·`lang`(ko|en)·`image`(필수)와 `description`·`source_name`·`source_url`·`source_domain`(있을 때) 순서이고 값은 한 줄 JSON, 본문에는 대표 이미지 줄(`![Thumbnail]` 에 이미지 주소를 괄호로 붙인 것)이 한 번은 있다. **구현**: `src/chanceblog_desktop/render/pages.py` 의 `render_pages_post`(순수 함수 — 원고(ContentProject)와 분야·언어·대표 이미지·태그·설명·출처 → 경로와 파일 내용, 파일은 쓰지 않는다)와 머리말 검사 `front_matter_problems`. 시험이 `tests/fixtures/` 의 **실제 글 두 편(영어·한글)을 글자 단위로 되살리고** 설명 자동 추출도 같은지 확인한다. 폴더 이름은 생성기의 `safe_category_dir` 규칙에 Windows 에서 만들 수 없는 글자(`<>:"|?*`)와 끝의 점·공백 정리를 더했다. `chanceblog` 쪽 규칙(`generator.py`)이 바뀌면 이쪽도 같은 PR 에서 맞춘다.
- **이미지**: 지금 Chance 는 외부 이미지 주소(Unsplash)를 `image:` 에 쓴다. 앱은 같은 방식과 함께 사용자가 고른 이미지 파일을 저장소 안 정해진 폴더에 두는 방식을 지원한다(폴더·크기 규칙은 첫 구현에서 정한다, 사이트 설정 `_config.yml` 은 건드리지 않는다).
- **발행**: 미리보기에서 승인하면 앱이 **항상 최신 `main` 을 먼저 가져온 뒤**(봇이 같은 `main` 에 직접 커밋한다) 파일을 만들고 commit·push 한다. 이후는 기존 흐름이다: `main` push → `pages.yml` 이 Jekyll 빌드·배포 → 배포 확인. 앱은 Actions 실행 상태를 읽어 성공·실패를 보이고(§6 오류 안내), 발행 주소를 기록한다.
- 클라우드 자동 발행(하루 3슬롯)과 겹치지 않게 같은 날 자동 글 수와 slug 중복을 확인한다. `history.json`(자동 발행 이력) 기록 여부는 첫 구현에서 `chanceblog` 쪽 소비자(감시·상한)를 읽고 정한다.

## 4. 핵심 코드 재사용 — '정해진 버전으로 가져다 쓴다'

`chanceblog` 의 `pipeline/` 에는 이미 시험 4,000여 개로 고정된 코드(검사 `gates.py`, 비밀 패턴 `secret_patterns.py`, 상태 `state.py`, 실패 분류·마스킹 `llm.py` 의 일부, Blogger 어댑터 `publishers/blogger.py`, 복사 패키지 `publishers/issue_package.py`)가 있다. 파이썬 그대로 가져다 쓰면 다시 시험하지 않아도 된다.
- 방식: `vendor/pipeline/` 에 **원본과 한 글자도 다르지 않게** 복사하고 `vendor/VENDOR.json` 에 가져온 저장소·커밋 SHA(40자리)·파일별 SHA-256 을 적는다. 앱은 시작할 때 `chanceblog_desktop.core.use_vendored_core()` 로 `vendor/` 를 `sys.path` 맨 앞에 올려(이미 있어도 맨 앞으로 옮기고, 같은 이름의 다른 `pipeline` 이 먼저 불려 와 있으면 멈춘다) `from pipeline import gates` 처럼 쓴다. 갱신은 `python scripts/sync_core.py --source <chanceblog 를 받아 둔 폴더> --ref <커밋·태그·브랜치>`(먼저 원본 폴더의 `origin` 이 chanceblog 이고 가져올 커밋이 `origin/main` 에 병합된 것이며 대상이 일반 파일(링크·하위 모듈·폴더 아님)인지 확인하고, 원본 커밋의 바이트를 그대로 쓰며, 읽기에 실패하면 아무것도 쓰지 않는다). `--check` 와 시험이 `vendor/` 해시와 `VENDOR.json` 이 같은지, `vendor/` **전체**에 목록 밖 파일이 없는지(컴파일 캐시 `.pyc` 도 포함 — `vendor/` 는 import 경로 맨 앞이라 어느 자리의 파일이든 앱이 불러올 수 있고, 소스와 수정 시각·크기만 맞춘 `.pyc` 는 소스 대신 실행된다. 앱은 컴파일 캐시를 사용자 폴더(`sys.pycache_prefix`)에 두므로 `vendor/` 안에는 없어야 한다). 목록의 파일 자리에 링크·하드 링크가 있으면 `--check` 가 알리고 가져오기는 쓰기 전에 멈춘다(링크 너머를 덮어쓰지 않게) 확인한다. `.gitattributes` 의 `vendor/** -text` 가 줄바꿈 변환(Windows autocrlf 포함)을 막는다. 코어를 고칠 일이 생기면 `chanceblog` 에서 고쳐 병합한 뒤 다시 가져온다(이 저장소에서 `vendor/` 를 고치지 않는다).
- 지금 가져오는 파일(앱이 쓰는 것만, 목록은 `scripts/sync_core.py` 의 `FILES`): `pipeline/__init__.py`·`console.py`·`gates.py`(발행 전 검사)·`secret_patterns.py`(비밀 모양 검사). 모두 표준 라이브러리만 쓴다. Blogger 어댑터·복사 패키지·상태 등은 그 기능을 만드는 묶음에서 목록에 더한다.
- 서브모듈·패키지 설치 방식은 비개발자 운영과 PC 이관에 부담이라 쓰지 않는다.

## 5. 코드 구성(예정 — `src/chanceblog_desktop/`)

| 모듈 | 하는 일 |
|---|---|
| `app/` | 화면(대시보드·편집기·블로그 프로필·발행 센터·설정·로그). 화면 틀은 PySide6 또는 pywebview 로 첫 구현에서 비교해 정한다(D-04) |
| `content/` | ContentProject·플랫폼 변형·원고 Revision·SQLite 저장·자동 저장·복구·스키마 마이그레이션·기존 원고 불러오기. **구현**: `model.py`(자료·검증)·`status.py`(상태 흐름)·`store.py`(SQLite 저장소, §10)·`profiles.py`(네이버 A·B 블로그 프로필 — 표시명·주소·주제·대상 독자·말투·카테고리 매핑·기본 태그·금지 표현·이미지 규격·글 길이·고지문, 엄격한 검사와 JSON) |
| `render/` | 플랫폼별 변환(Markdown↔HTML, Pages Front Matter, Blogger HTML, 네이버 패키지)과 미리보기. **구현**: `pages.py`(Pages 글, §3)·`markdown.py`(Markdown↔HTML — 제목·문단·줄바꿈·4단계 목록·인용·굵게/기울임·링크(https·허용 주소만)·이미지(HTML 밖에서 따로 목록으로), 원고 속 HTML 은 해석하지 않고 글자로 보이며 결과는 핵심 코드의 정화기를 거쳐 허용 태그만 나간다, 기존 글(HTML)을 Markdown 으로 불러오기·평문 변환·블록별 HTML 과 이미지 자리 포함)·`naver.py`(네이버 복사 패키지 — 블로그 프로필에 맞춰 제목 줄이기·태그 정리·짧은 문단 나누기·이미지 `[이미지 N]` 자리 표시·AI 활용 고지문·체크리스트·금지 표현/글 길이 점검을 만든다. 글을 AI 로 다시 쓰지 않고 파일·네트워크도 쓰지 않는다) |
| `publish/` | Pages(연결한 로컬 저장소에 쓰기·commit·push·배포 확인), Blogger 초안 저장·수정, 네이버 복사 패키지·상태 |
| `check/` | 발행 전 검사(핵심 코드 `pipeline/gates.py` 를 감싸고 앱 전용 검사 — 두 네이버 블로그 중복 등 — 추가). **구현**: `similarity.py`(네이버 A·B 유사도 — 제목·도입부·본문·문단 구성·이미지·태그·발행일을 글자 3개씩 묶음·편집 거리로 재고, 기준 이상이면 `NAVER_SIMILARITY_HIGH` 로 직접 승인이 있어야 복사 단계로 넘어간다. 기준값은 기본값이고 인자로 바꾼다) |
| `errors/` | **오류 코드와 안내 문구 카탈로그**(규칙 기반). 모든 실패는 코드 하나로 모이고 사용자에게 원인·하실 일을 보인다 |
| `update/` | 업데이트 확인·서명 검증·백업·적용·롤백([`RELEASE.md`](RELEASE.md)), 프로그램 버전·변경 이력 |
| `security/` | OS 보안 저장소(Windows 자격 증명 관리자) 접근(예정), **로그 마스킹**(구현: `mask.py` — [`SECURITY.md`](SECURITY.md) §2) |
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
  └─ PlatformVariant × 플랫폼(github_pages · blogger_en · blogger_ko · naver_a · naver_b): rendered · rendered_revision · status · published_url · published_at · remote_id · error_code
JobLog: job_id · kind · started_at · finished_at · result · error_code · detail(마스킹됨)
```

- API 키 원문은 데이터베이스·프로젝트 파일·로그에 저장하지 않는다.
- **상태 흐름**(코드 `content/status.py` 의 `FLOWS` 가 이 표와 같고 시험이 확인한다. 굵게 쓴 공개 상태는 되돌리지 않는다 — 공개 취소는 사람이 플랫폼에서 한다):
  - GitHub Pages: `NOT_STARTED` → `DRAFT_GENERATED` → `REVIEW_REQUIRED` → `APPROVED` → `COMMITTED` → `PUSHED` → **`PUBLISHED`**
  - Blogger(영문·한글): `NOT_STARTED` → `DRAFT_GENERATED` → `REVIEW_REQUIRED` → `APPROVED` → `DRAFT_SAVED` → **`PUBLISHED_MANUAL`** (공개는 운영자가 Blogger 에서)
  - 네이버 A·B: `NOT_STARTED` → `DRAFT_GENERATED` → `REVIEW_REQUIRED` → `READY_TO_COPY` → `COPY_COMPLETED` → **`PUBLISHED_MANUAL`**
  - 어느 플랫폼이든 승인 단계에서 `REVIEW_REQUIRED` 로, 검토 단계에서 `DRAFT_GENERATED` 로 물러설 수 있고, 올리는 중에 실패하면 `PUBLISH_FAILED`(오류 코드 필수)로 갔다가 `REVIEW_REQUIRED` 나 `DRAFT_GENERATED` 로 돌아가 다시 한다.
- **상태 규칙**: ① 원고를 고치면(판 번호 `revision` 이 오른다) 검토·승인·초안 저장·복사 중이던 변형은 `DRAFT_GENERATED` 로 돌아가 처음부터 다시 검토한다 — 이미 올라간 `COMMITTED`·`PUSHED`·공개 상태는 과거의 사실이라 그대로 둔다. ② 승인(`APPROVED`·`READY_TO_COPY`)은 **현재 판으로 만든 렌더링**에만 줄 수 있다. ③ 공개 상태로 바꿀 때는 **발행 주소**(https, 로그인 정보 없음, 네이버는 `blog.naver.com` 주소)가 있어야 한다. ④ `PUBLISH_FAILED` 로 바꿀 때는 **오류 코드**가 있어야 한다. 규칙을 어기면 오류 코드(`STATUS_TRANSITION_INVALID`·`PUBLISHED_URL_REQUIRED`·`PUBLISHED_URL_INVALID`·`NAVER_PUBLISH_URL_INVALID`·`CONTENT_INVALID`)로 거절하고 아무것도 바꾸지 않는다.
- 네이버: 두 네이버 블로그는 같은 주제여도 **제목·도입부·문단 구성·태그를 각자 프로필에 맞게 변환하고 각각 검수**하며, 유사도가 기준을 넘으면 경고하고 운영자가 명시 승인해야 `READY_TO_COPY` 가 된다. 같은 원고를 그대로 복제하는 기능은 기본값으로 두지 않는다. 네이버 A·B 는 표시명·URL·주제·대상 독자·말투·카테고리 매핑·기본 태그·금지 표현·이미지 규격·글 길이·발행 주기·발행 이력을 **각자 독립 프로필**로 관리한다.

## 10. 로컬 데이터와 백업

사용자 데이터는 `%LOCALAPPDATA%\ChanceblogDesktop\`(설정·SQLite·이미지·백업·로그)에 둔다. 설치 폴더 밖이라 업데이트가 `current` 만 교체해도 데이터가 남는다. 업데이트 전에 SQLite backup API 로 스냅샷하고 최근 N개를 보관하며, 스키마는 `PRAGMA user_version` 으로 순방향 마이그레이션, 실패하면 백업 복원.

**구현**: `src/chanceblog_desktop/content/store.py`(`Store`) — 파일 하나에 `projects`·`revisions`(원고의 판 기록, 프로젝트마다 기본 50개)·`drafts`(자동 저장 초안) 세 표. 열 때 `application_id`(이 프로그램의 파일인가)·`user_version`(더 새로운 버전이 만든 것은 아닌가)·`quick_check`(깨지지 않았나)를 보고, 아니면 **파일을 한 바이트도 바꾸지 않고** `STORE_CORRUPT`·`STORE_VERSION_UNSUPPORTED` 로 멈춘다. 옛 구조는 사본(`<파일>.v<번호>.bak`)을 둔 뒤 한 트랜잭션으로 올리고 실패하면 원래대로 둔다(`MIGRATION_FAILED`). 쓰는 일은 모두 한 트랜잭션이고 저장된 판보다 낮은 판으로는 덮어쓰지 않는다(`STORE_CONFLICT`). 읽을 때 `ContentProject.from_dict` 의 엄격한 검사를 다시 거치고, 여러 스레드가 함께 써도 한 번에 하나씩 실행한다. `backup()` 은 SQLite backup API 로 점검한 사본(`<이름>-YYYYMMDD-HHMMSS.db`)을 만들고 최근 10개만 남기며, `restore_from()` 은 이 프로그램의 온전한 백업이 아니면 아무것도 바꾸지 않는다(원하면 바꾸기 직전 상태를 먼저 따로 백업한다).

## 11. 버전

Semantic Versioning. 앱·DB 스키마·핵심 코드(`vendor/` 커밋)·플랫폼 어댑터·템플릿 버전을 따로 기록하고 설정 화면과 GitHub Release 에서 같게 보인다. 개발 순서는 운영자 우선순위를 따른다([`DECISIONS.md`](DECISIONS.md) D-12).
