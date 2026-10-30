# 변경 이력

버전은 [Semantic Versioning](https://semver.org/lang/ko/) 을 따른다. 앱 버전은 `VERSION` 파일이 기준이다. 설치 파일이 있는 릴리스는 `0.1.0` 부터다.

## [0.0.0] — 2026-10-30 (설계 단계, 설치 파일 없음)

- 저장소 뼈대: `AGENTS.md`·`CLAUDE.md`·`docs/`(구조·결정·플랫폼·오류 안내·릴리스·보안·이관)·CI·저장소 구조 시험.
- 결정(`docs/DECISIONS.md`): 티스토리 제외·격리, 새 저장소, 기존 chanceblog 로컬 저장소 연결로 Pages 발행, 파이썬 코어 재사용 + PyInstaller + Velopack, 초안 릴리스 + 운영자 공개, 무서명 + 자체 서명 매니페스트, **AI Router 제외·무료 AI 는 선택 보조(기본 꺼짐)**, 규칙 기반 오류 안내.
- `docs/TROUBLESHOOTING.md`(오류 코드와 하실 일)·`.env.example`(변수 이름만) 추가.
- 첫 코드: `src/chanceblog_desktop/errors/` — 오류 코드 카탈로그(문서의 표에서 `scripts/sync_errors.py` 가 만듦)와 사용자 문구 만들기(`render`·`AppError`), 시험 포함. 설치 파일은 아직 없다.
- 핵심 코드 가져오기: `vendor/pipeline/`(chanceblog 의 `gates`·`console`·`secret_patterns` 를 원본 그대로 — 커밋 `a5af962`)·`vendor/VENDOR.json`(출처·커밋·해시)·`scripts/sync_core.py`·`chanceblog_desktop.core`·`.gitattributes`, 해시·동작·가져오기 시험 포함. 설치 파일은 아직 없다.
- 연결한 chanceblog 저장소 확인: `src/chanceblog_desktop/publish/gitrepo.py` — 폴더·origin·main·변경 확인, 원격 main 빨리감기, 올리기 점검(`--dry-run`), git 실패의 오류 코드 분류. 오류 코드 `PAGES_LOCAL_REPO_NOT_MAIN`·`PAGES_LOCAL_REPO_DIVERGED` 추가, 시험 포함.
- 콘텐츠 모델: `src/chanceblog_desktop/content/` — 하나의 원본 글(`ContentProject`)과 플랫폼별 변형·발행 상태 흐름(Pages·Blogger·네이버), 원고를 고치면 승인이 풀리는 규칙, 공개 상태의 발행 주소 검사, 엄격한 JSON 저장 모양. 오류 코드 4개 추가(`CONTENT_INVALID`·`STATUS_TRANSITION_INVALID`·`PUBLISHED_URL_REQUIRED`·`PUBLISHED_URL_INVALID`), 시험 포함. 저장(SQLite)은 다음 묶음.
- Pages 글 만들기: `src/chanceblog_desktop/render/pages.py` — 원고를 chanceblog 에 넣을 파일(경로·내용)로 만드는 순수 함수와 머리말 검사. 실제 Chance 글 두 편(`tests/fixtures/`)을 글자 단위로 되살리는 시험 포함.
- Markdown ↔ HTML 변환: `src/chanceblog_desktop/render/markdown.py` — 원고(Markdown)를 허용 태그만 있는 HTML 로(`markdown_to_html`), 이미지는 따로 뽑고(`markdown_images`), 기존 글(HTML)을 Markdown 으로 불러온다(`html_to_markdown`). 원고 속 HTML·`javascript:` 링크는 글자로만 보이고 결과는 핵심 코드의 정화기를 한 번 더 거친다. 되돌려 써도 같은 글이 되는지(무작위 문서)·어떤 입력에도 예외 없이 빨리 끝나는지 시험한다. 앞 묶음 파일(`render/pages.py`·`tests/test_pages_render.py`)의 눈에 안 보이는 글자는 `\u` 표기로 바꿨다(동작 변화 없음).
- 네이버 A·B 복사 패키지: `content/profiles.py`(블로그 프로필), `render/naver.py`(`build_package` — 제목 줄이기·태그 정리·짧은 문단·이미지 자리 표시·고지문·체크리스트·금지 표현/글 길이 점검), `check/similarity.py`(두 블로그 글의 유사도, 기준 이상이면 직접 승인 필요), `render/markdown.py` 에 블록별 HTML·이미지 자리(`markdown_blocks`)와 평문 변환(`html_to_text`)을 더했다. 글을 AI 로 다시 쓰지 않는다. 시험 포함.
