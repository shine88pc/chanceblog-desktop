# 변경 이력

버전은 [Semantic Versioning](https://semver.org/lang/ko/) 을 따른다. 앱 버전은 `VERSION` 파일이 기준이다. 설치 파일이 있는 릴리스는 `0.1.0` 부터다.

## [0.0.0] — 2026-10-30 (설계 단계, 설치 파일 없음)

- 저장소 뼈대: `AGENTS.md`·`CLAUDE.md`·`docs/`(구조·결정·플랫폼·오류 안내·릴리스·보안·이관)·CI·저장소 구조 시험.
- 결정(`docs/DECISIONS.md`): 티스토리 제외·격리, 새 저장소, 기존 chanceblog 로컬 저장소 연결로 Pages 발행, 파이썬 코어 재사용 + PyInstaller + Velopack, 초안 릴리스 + 운영자 공개, 무서명 + 자체 서명 매니페스트, **AI Router 제외·무료 AI 는 선택 보조(기본 꺼짐)**, 규칙 기반 오류 안내.
- `docs/TROUBLESHOOTING.md`(오류 코드와 하실 일)·`.env.example`(변수 이름만) 추가.
- 첫 코드: `src/chanceblog_desktop/errors/` — 오류 코드 카탈로그(문서의 표에서 `scripts/sync_errors.py` 가 만듦)와 사용자 문구 만들기(`render`·`AppError`), 시험 포함. 설치 파일은 아직 없다.
- 핵심 코드 가져오기: `vendor/pipeline/`(chanceblog 의 `gates`·`console`·`secret_patterns` 를 원본 그대로 — 커밋 `a5af962`)·`vendor/VENDOR.json`(출처·커밋·해시)·`scripts/sync_core.py`·`chanceblog_desktop.core`·`.gitattributes`, 해시·동작·가져오기 시험 포함. 설치 파일은 아직 없다.
- 연결한 chanceblog 저장소 확인: `src/chanceblog_desktop/publish/gitrepo.py` — 폴더·origin·main·변경 확인, 원격 main 빨리감기, 올리기 점검(`--dry-run`), git 실패의 오류 코드 분류. 오류 코드 `PAGES_LOCAL_REPO_NOT_MAIN`·`PAGES_LOCAL_REPO_DIVERGED` 추가, 시험 포함.
