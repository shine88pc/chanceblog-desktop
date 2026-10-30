# 변경 이력

버전은 [Semantic Versioning](https://semver.org/lang/ko/) 을 따른다. 앱 버전은 `VERSION` 파일이 기준이다. 설치 파일이 있는 릴리스는 `0.1.0` 부터다.

## [0.0.0] — 2026-10-30 (설계 단계, 설치 파일 없음)

- 저장소 뼈대: `AGENTS.md`·`CLAUDE.md`·`docs/`(구조·결정·플랫폼·오류 안내·릴리스·보안·이관)·CI·저장소 구조 시험.
- 결정(`docs/DECISIONS.md`): 티스토리 제외·격리, 새 저장소, 기존 chanceblog 로컬 저장소 연결로 Pages 발행, 파이썬 코어 재사용 + PyInstaller + Velopack, 초안 릴리스 + 운영자 공개, 무서명 + 자체 서명 매니페스트, **AI Router 제외·무료 AI 는 선택 보조(기본 꺼짐)**, 규칙 기반 오류 안내.
- `docs/TROUBLESHOOTING.md`(오류 코드와 하실 일)·`.env.example`(변수 이름만) 추가.
- 첫 코드: `src/chanceblog_desktop/errors/` — 오류 코드 카탈로그(문서의 표에서 `scripts/sync_errors.py` 가 만듦)와 사용자 문구 만들기(`render`·`AppError`), 시험 포함. 설치 파일은 아직 없다.
- 핵심 코드 가져오기: `vendor/pipeline/`(chanceblog 의 `gates`·`console`·`secret_patterns` 를 원본 그대로 — 커밋 `a5af962`)·`vendor/VENDOR.json`(출처·커밋·해시)·`scripts/sync_core.py`·`chanceblog_desktop.core`·`.gitattributes`, 해시·동작·가져오기 시험 포함. 설치 파일은 아직 없다.
- 연결한 chanceblog 저장소 확인: `src/chanceblog_desktop/publish/gitrepo.py` — 폴더·origin·main·변경 확인, 원격 main 빨리감기, 올리기 점검(`--dry-run`), git 실패의 오류 코드 분류. 오류 코드 `PAGES_LOCAL_REPO_NOT_MAIN`·`PAGES_LOCAL_REPO_DIVERGED` 추가, 시험 포함.
- 콘텐츠 모델: `src/chanceblog_desktop/content/` — 하나의 원본 글(`ContentProject`)과 플랫폼별 변형·발행 상태 흐름(Pages·Blogger·네이버), 원고를 고치면 승인이 풀리는 규칙, 공개 상태의 발행 주소 검사, 엄격한 JSON 저장 모양. 오류 코드 4개 추가(`CONTENT_INVALID`·`STATUS_TRANSITION_INVALID`·`PUBLISHED_URL_REQUIRED`·`PUBLISHED_URL_INVALID`), 시험 포함.
- 콘텐츠 저장소(SQLite): `src/chanceblog_desktop/content/store.py` — 프로젝트 저장·불러오기·목록·삭제, 판 기록(기본 50개), 자동 저장 초안, 전체 점검, 백업(점검한 사본·오래된 것 정리)·복구, 구조 올리기(사본을 두고 한 트랜잭션, 실패하면 원래대로). 깨진·낯선·더 새로운 파일은 한 바이트도 바꾸지 않고 거절하고, 저장된 것보다 낮은 판으로는 덮어쓰지 못한다. 오류 코드 5개 추가(`CONTENT_NOT_FOUND`·`STORE_CORRUPT`·`STORE_LOCKED`·`STORE_VERSION_UNSUPPORTED`·`STORE_CONFLICT`)하고 `BACKUP_FAILED` 문구를 업데이트 밖 백업에도 맞게 고쳤다, 시험 포함.
