# v1.0 릴리스 점검표 — 올리기 전에 고쳐야 할 낡은 문장 (초안, 2026-11-24)

> 한 줄: **버전을 `1.0.0` 으로 올리기 전에 문서·화면 글·이름 가운데 '아직 미리보기다·설치 파일이 없다' 처럼 낡아질 문장을 파일·줄·현재 문장·바꿀 문장 초안으로 모은 표**다. 완료 기준 [`DECISIONS.md`](DECISIONS.md) '1.0.0 완료 기준'의 1번(새 clone 으로 빌드·시험)·2번(문서만으로 구조 이해)·12번(버전·변경 이력이 화면과 Release 에서 일치)을 채우는 문서 쪽 준비다.

> **이 표는 지금 아무것도 고치지 않는다.** 2026-11-24 에 `grep` 으로 찾은 줄을 적었고, 고치는 일은 버전을 올리는 마지막 묶음(DOCS(b))과 각 기능 갈래(PUBPR·BLOGGER·UPDATE·INSTALLER·RELEASE·GUI)가 한다. **'바꿀 문장 초안'은 초안이다** — 릴리스 때의 사실로 확정하며, 설치 도구·태그 규칙·라이선스·서명 같은 정해지지 않은 것은 정해진 뒤의 사실로 쓴다(그 전에는 쓰지 않는다).

## 1. 읽는 법

- **줄 번호는 표를 쓴 때의 값**이라 다른 갈래가 문서를 고치면 밀린다. 찾을 때는 줄이 아니라 **'찾는 조각'**(현재 문장의 한 토막)을 검색한다. 시험(`tests/test_v1_docs.py`)이 '대기' 행의 조각이 그 파일에 지금도 있는지 본다 — 고쳤다면 그 행의 상태를 `고침` 으로 바꾸고, 시험은 반대로 '고침' 행의 조각이 더는 없는지 본다.
- 상태: `대기`(아직 낡은 문장) · `고침`(고쳤다 — 조각이 파일에서 사라져야 한다) · `고치지 않음`(옛 결정·옛 변경의 기록이라 과거 행 원문은 고치지 않는다 — 조각이 그대로 있어야 한다).
- **같이 볼 시험**: 그 문장·문서를 못박거나 훑는 시험 모듈이다. 고친 뒤 이 모듈을 돌려 보고, 문장을 못박은 단언은 **약화가 아니라 새 사실로 바꾼다**(바꾼 시험은 목록으로 남긴다). `—` 는 그 조각을 직접 못박는 시험을 grep 으로 찾지 못했다는 뜻이다(문서 시험이 훑는 다른 단언은 있을 수 있어 고친 뒤 `test_docs_entrance`·`test_repo_layout`·`test_packaging_docs` 는 늘 돌린다).
- 담당은 격차 조사의 갈래 이름이다: DOCS(b)(문서·버전 마무리)·FINAL(릴리스 후보 종합 검증)·GUI(화면의 글 흐름)·NET(네트워크 틀)·PUBPR(Pages 가지 올리기)·BLOGGER(Blogger 초안)·UPDATE(업데이트)·INSTALLER(설치 도구)·RELEASE(릴리스 워크플로).
- 결정 기록·변경 이력 안의 **과거 행 원문은 고치지 않는다**(바꾸려면 새 행으로 덮는다). 아래 `고치지 않음` 행은 '왜 안 고치나' 를 남긴 것이다.

## 2. 낡은 문장 표

### 2-1. 입구 문서 — README·AGENTS·MIGRATION

| 번호 | 파일:줄 | 찾는 조각 | 바꿀 문장 초안 | 같이 볼 시험 | 담당 | 상태 |
|---|---|---|---|---|---|---|
| A01 | `README.md:5` | `설치 파일과 자동 업데이트는 아직 없습니다` | 상태 줄을 '정식 1.0 입니다. 설치 파일(Setup)과 휴대용 압축 파일을 릴리스 페이지에서 받을 수 있고 앱 안의 업데이트 확인 단추로 새 버전을 알아봅니다' 꼴로(릴리스 때의 사실로 확정). 끝의 '첫 설치 파일은 0.1.0 부터 … 올라올 예정입니다' 도 함께 | test_docs_entrance(상태 줄 단언과 VERSION 의 preview 단언) | DOCS(b) | 대기 |
| A02 | `README.md:20` | `설치 파일은 아직 없고 화면은 일부뿐입니다` | '설치 파일로 설치해 화면에서 글 만들기부터 내보내기까지 쓸 수 있습니다. 아래는 명령줄(개발자·고급 사용) 설명입니다' — 화면 범위는 GUI 갈래의 결과에 맞춘다 | — | GUI·DOCS(b) | 대기 |
| A03 | `README.md:34` | `이 시험 버전은 외부 게시가 완전히 꺼져 있습니다` | 이 버전에서 실제로 켠 외부 쓰기(Pages 가지 올리기·Blogger 초안 중 켠 것만)와 꺼 둔 것을 사실대로 나눠 적는다 | test_external_write_gate | PUBPR·BLOGGER | 대기 |
| A04 | `README.md:69` | `아직 어느 서비스도 실제로 부르지 않습니다` | 실제로 부르는 서비스(켠 것만)와 아직 부르지 않는 서비스를 나눠 적는다 | — | NET·UPDATE | 대기 |
| A05 | `README.md:82` | `Blogger 로그인 정보(OAuth)는 이 시험 버전이 받지 않습니다` | Blogger 로그인(OAuth) 연결과 초안 저장 방법(BLOGGER 갈래의 결과) | — | BLOGGER | 대기 |
| A06 | `README.md:129` | `화면은 아직 일부뿐입니다` | 화면 목록을 릴리스 때의 화면 범위로 다시 적는다 | — | GUI | 대기 |
| A07 | `README.md:129` | `사이드바의 흐린 '다음 단계' 목록에 이름만 보이고 누를 수 없습니다` | 발행 기록 화면이 메뉴로 올라온 사실로(GUI 갈래가 만들지 않으면 그대로 둔다) | — | GUI | 대기 |
| A08 | `README.md:39` | `초안을 쓰는 일은 아직 없습니다` | **이미 낡았다**: 같은 문서의 `draft body`(규칙 기반 초안 본문) 설명과 어긋난다. '네이버 검색 데이터를 모으는 일(키가 필요합니다)은 아직 없습니다' 로 줄인다 | — | DOCS(b) | 대기 |
| A09 | `README.md:168` | `**설치 파일은 아직 없습니다**` | 새 PC 절(2026-11-24 에 덧붙인 것)의 첫머리를 '설치 파일로 설치하는 길' 안내와 '소스로 실행하는 개발자용' 으로 나눠 바꾼다 | — | DOCS(b) | 대기 |
| A10 | `README.md:183` | `새 PC 에서 처음부터 끝까지 따라 해 본 기록은 아직 없습니다` | 운영자나 새 clone 검증자가 따라 해 본 날짜와 결과를 적는다(해 보지 않았다면 이 문장을 그대로 둔다) | — | FINAL | 대기 |
| A11 | `README.md:150` | `개인 PC 제한 시험용 Package 만들기(개발자용)와 운영자가 개인 PC 에서 해 보는 시험지` | 문서 표의 이 줄을 휴대용 Package 만들기(개발자용)와 릴리스 시험지로 | test_docs_entrance(표에 문서 이름이 있는지만 본다) | DOCS(b) | 대기 |
| A12 | `AGENTS.md:7` | `지금은 다음 PC(개인 PC 또는 빈 공용 PC — 운영자 확인 대기)로의 이전을 준비 중이다` | PC 이전이 끝났거나 정해진 사실로(릴리스와 별개 — 이전이 끝나면 고친다) | test_docs_entrance(AGENTS 단언) | 총괄 | 대기 |
| A13 | `docs/MIGRATION.md:5` | `다음 PC(개인 PC 또는 빈 공용 PC — 운영자 확인 대기)로의 이전을 준비하고 있다` | 같은 사실로(위 A12 와 함께) | — | 총괄 | 대기 |
| A14 | `docs/MIGRATION.md:1` | `# 회사 PC → 개인 PC 이관과 새 PC 준비` | 제목이 처음 이관만 말한다. 새 PC 마다 쓰는 문서이니 '새 PC 준비와 이관' 처럼(README 문서 표의 설명도 함께) | test_repo_layout(문서가 있는지만 본다) | DOCS(b) | 대기 |
| A15 | `docs/MIGRATION.md:176` | `설치 파일(Setup)·자동 업데이트·시작 메뉴·제거 프로그램이 아직 없다` | §6-3 알려 둔 한계를 설치 도구 결정 뒤의 사실로(설치형·휴대용의 차이 표) | — | INSTALLER·DOCS(b) | 대기 |
| A16 | `docs/MIGRATION.md:62` | `새 PC 에서 처음부터 끝까지 따라 해 본 기록은 아직 없다` | §6 머리말을 따라 해 본 날짜와 결과로(위 A10 과 함께) | — | FINAL | 대기 |
| A17 | `README.md:87` | `초안 문장은 아직 만들지 않습니다` | **이미 낡았다**(A08 과 같은 뿌리): 작성 기반(`draft plan`)은 뼈대만 만들고 초안 문장은 아래의 `draft body` 가 규칙으로 만든다고 적는다 | — | DOCS(b) | 대기 |

### 2-2. 버전·변경 이력

| 번호 | 파일:줄 | 찾는 조각 | 바꿀 문장 초안 | 같이 볼 시험 | 담당 | 상태 |
|---|---|---|---|---|---|---|
| B01 | `VERSION:1` | `0.1.0-preview.1` | `1.0.0` 한 줄(확인 C 와 릴리스 직전). 올린 뒤 화면 '정보' 카드·`PACKAGE_INFO` 의 버전도 같은 값이어야 한다 | test_repo_layout(VersionTest — CHANGELOG 맨 위와 같아야 한다)·test_docs_entrance(VERSION 에 preview 가 있다는 단언)·test_packaging_docs(시험지 제목에 `tests/packaging_support.py` 의 VERSION 상수가 든다는 단언) | DOCS(b) | 대기 |
| B02 | `CHANGELOG.md:3` | `설치 파일이 있는 릴리스는` | '설치 파일이 있는 첫 릴리스는 1.0.0 이다.' | — | DOCS(b) | 대기 |
| B03 | `CHANGELOG.md:5` | `## [0.1.0-preview.1] — 2026-11-11` | 맨 위에 새 절 `## [1.0.0] — 날짜`(사용자용 릴리스 노트 — [`RELEASE.md`](RELEASE.md) 의 '릴리스 노트 규칙'). 이 옛 절은 지우지 않고 아래로 내려간다 | test_repo_layout(VersionTest)·test_packaging_docs(첫 절이 VERSION 과 같다는 단언) | DOCS(b) | 대기 |
| B04 | `CHANGELOG.md:32` | `(설계 단계, 설치 파일 없음)` | 옛 변경(0.0.0)의 기록이라 고치지 않는다 | — | — | 고치지 않음 |
| B05 | `docs/DECISIONS.md:19` | `**라이선스**: 아직 정하지 않았다` | D-13 은 과거 행이라 고치지 않는다. 확인 C 가 라이선스를 정하면 새 결정 행으로 덮고 `LICENSE` 파일을 더한다 | — | DOCS(b) | 고치지 않음 |

### 2-3. 구조·보안·오류 안내 문서

| 번호 | 파일:줄 | 찾는 조각 | 바꿀 문장 초안 | 같이 볼 시험 | 담당 | 상태 |
|---|---|---|---|---|---|---|
| C01 | `docs/ARCHITECTURE.md:47` | `## 5. 코드 구성(예정` | '## 5. 코드 구성 — `src/chanceblog_desktop/`' (예정 표시를 지운다) | test_topics_rules(이 제목 줄을 글자 그대로 못박는다 — 같이 고친다) | DOCS(b) | 대기 |
| C02 | `docs/ARCHITECTURE.md:61` | `업데이트 확인·서명 검증·백업·적용·롤백([` | `update/` 줄을 실제로 만든 모양(모듈 이름·하는 일)으로 | — | UPDATE | 대기 |
| C03 | `docs/ARCHITECTURE.md:102` | `Blogger·예약 작업·자동 업데이트·설치 파일·보조 AI` | '하지 않는 것' 목록을 v1.0 사실로(Blogger·자동 업데이트·설치 파일을 만들었다면 지우고 앱이 하지 않는 것만 남긴다) | — | UPDATE·BLOGGER·INSTALLER | 대기 |
| C04 | `docs/ARCHITECTURE.md:133` | `발행 기록)은 아직 없고 사이드바` | 알려 둔 한계의 화면 목록을 릴리스 때의 화면으로 | — | GUI | 대기 |
| C05 | `docs/ARCHITECTURE.md:83` | `이 시험 버전은 이 칸들을 받지 않는다` | 용도 표의 `blogger` 줄 — BLOGGER 가 입력을 연 뒤의 사실로 | — | BLOGGER | 대기 |
| C06 | `docs/ARCHITECTURE.md:84` | `이 시험 버전은 외부 게시가 꺼져 있어` | 용도 표의 `github_repo` 줄 — PUBPR 가 가지 올리기를 연 뒤의 사실로 | — | PUBPR | 대기 |
| C07 | `docs/ARCHITECTURE.md:183` | `설치 프로그램·자동 업데이트가 아니다` | Package 절의 첫 문단을 '휴대용 묶음과 설치 파일을 함께 만드는 도구' 로(절 제목은 시험이 못박는다) | test_packaging_docs(ARCHITECTURE 의 이 절 제목·필요한 낱말 단언) | INSTALLER·DOCS(b) | 대기 |
| C08 | `docs/ARCHITECTURE.md:193` | `설정 화면과 GitHub Release 에서 같게 보인다` | '화면 버전 = CHANGELOG 맨 위 = Release 제목' 을 지키는 규칙·시험을 가리키는 문장으로([`RELEASE.md`](RELEASE.md) 릴리스 노트 규칙) | test_repo_layout(VersionTest) | RELEASE·FINAL | 대기 |
| C09 | `docs/SECURITY.md:18` | `미구현 설계다 — 이 시험 버전에는 업데이트 경로가 없다` | §1 의 업데이트 서명 개인키 문단을 구현된 사실(공개키 위치·서명 대상)로 | test_security_as2b_docs | UPDATE | 대기 |
| C10 | `docs/SECURITY.md:30` | `이 시험 버전에는 업데이트 경로가 없다(미구현 설계)` | §3 업데이트 보안을 구현된 내려받기·서명·해시 검증·다운그레이드 거부 설명으로 | test_security_as2b_docs(옛 §3 문장과 이 문장을 단언한다 — 새 사실로 바꾼다) | UPDATE | 대기 |
| C11 | `docs/SECURITY.md:10` | `이 시험 버전은 입력 칸이 없고` | Blogger OAuth 줄 — BLOGGER 가 입력을 연 뒤의 사실로 | test_external_write_gate | BLOGGER | 대기 |
| C12 | `docs/SECURITY.md:130` | `이 시험 버전에는 글을 외부로 쓰는 길이` | PCSEC1 절의 '네 겹으로 막혀 있다' 를 PUBPR·BLOGGER 가 연 범위의 사실로(켠 길과 막힌 길을 나눠) | test_external_write_gate·test_external_write_zero | PUBPR·BLOGGER | 대기 |
| C13 | `docs/TROUBLESHOOTING.md:130` | `이 시험 버전은 외부 쓰기가 소스 상수로 완전히 꺼져 있고` | `EXTERNAL_WRITE_DISABLED` 행을 켠 범위의 사실로. 표를 고치면 `python scripts/sync_errors.py` 로 `errors/catalog.py` 를 다시 만든다 | test_errors_catalog·test_errors_wording | PUBPR | 대기 |
| C14 | `docs/TROUBLESHOOTING.md:100` | `UPDATE_SIGNATURE_INVALID` | §7 의 `UPDATE_*` 행은 표에만 있고 일으키는 코드가 없다 — UPDATE 가 실제로 일으키는 곳을 이어 행 문구를 확정한다. `UPDATE_DOWNGRADE_BLOCKED` 의 안내는 `RELEASE.md` 를 가리킨다(복구 모드 설명이 그 문서에 남아야 한다) | test_errors_catalog·test_errors_wording | UPDATE | 대기 |
| C15 | `docs/UI_STATES.md:489` | `꼴 · 버전 파일을 못 읽은 개발 화면은` | 앱 버전 칸의 예시 글(v0.1.0-preview.1 꼴)을 'v1.0.0 꼴' 로(낮은 우선) | — | DOCS(b) | 대기 |
| C16 | `docs/UI_IMAGES.md:54` | `설치 마무리 단계의 시험 항목` | §4 '설치 파일에서 확인할 것' 에 실제로 확인한 결과(날짜·환경)를 더한다 | — | INSTALLER·FINAL | 대기 |

### 2-4. 릴리스·Package·시험지 문서

| 번호 | 파일:줄 | 찾는 조각 | 바꿀 문장 초안 | 같이 볼 시험 | 담당 | 상태 |
|---|---|---|---|---|---|---|
| D01 | `docs/RELEASE.md:3` | `장래 설계(미구현)` | 배너 두 줄을 지우고 문서를 구현된 흐름의 사실로 바꾼다(확인하지 못한 것 절은 시험으로 닫은 것만 '확인함' 으로) | test_docs_entrance(배너 단언 — 새 첫 줄로 바꿔 강화)·test_errors_wording(`UPDATE_DOWNGRADE_BLOCKED` 가 이 문서를 가리킨다) | RELEASE·DOCS(b) | 대기 |
| D02 | `docs/RELEASE.md:14` | `BlogPublisher-Setup-x.y.z.exe` | 산출물 이름을 실제 제품 이름(`ChanceBlogDesktop-…`, 확인 C 추천: 유지)으로 | — | RELEASE·INSTALLER | 대기 |
| D03 | `docs/RELEASE.md:14` | `채널은 Stable·Beta·Dev` | 확인 C 가 정한 채널 수와 태그 규칙(추천: Stable 하나, `vX.Y.Z`)으로 | — | RELEASE | 대기 |
| D04 | `docs/RELEASE.md:40` | `## 확인하지 못한 것` | 설치 도구 시험(spike) 결과로 '확인함·확인 못 함' 을 갱신한다 | — | INSTALLER | 대기 |
| D05 | `docs/PACKAGE.md:1` | `# 개인 PC 제한 시험용 Package — 만들기·구성·점검` | 제목과 굵은 안내 줄(공개 배포용이 아닙니다)을 v1.0 휴대용 Package 설명으로 | test_packaging_docs(제목·둘째 줄을 글자 그대로 단언)·test_docs_entrance | INSTALLER·DOCS(b) | 대기 |
| D06 | `docs/PACKAGE.md:9` | `자동 업데이트·서비스 등록이 **없다**` | 휴대용과 설치형 둘의 차이 표로(설치 위치·시작 메뉴·제거·업데이트) | — | INSTALLER | 대기 |
| D07 | `docs/PACKAGE.md:113` | `아이콘이 없다` | 아이콘이 들어갔다면 사실로 | test_packaging_docs(§10 에 이 낱말이 있다는 단언) | INSTALLER | 대기 |
| D08 | `docs/PACKAGE.md:115` | `업데이트·롤백·마이그레이션 코드가 없다` | UPDATE 가 만든 사실(내려받기·백업·적용·롤백)과 남은 한계로 | test_packaging_docs(§10 에 '업데이트·롤백' 이 있다는 단언) | UPDATE | 대기 |
| D09 | `docs/PACKAGE.md:33` | `ChanceBlogDesktop-0.1.0-preview.1-win64.zip` | 예시 파일 이름의 버전(`VERSION` 을 따른다). 같은 이름이 시험지·시험에도 있다 | test_docs_entrance·test_packaging_docs | DOCS(b) | 대기 |
| D10 | `docs/PERSONAL_PC_TEST.md:1` | `개인 PC 제한 시험 안내서 — ChanceBlog Desktop 0.1.0-preview.1` | 새 시험지로 바꾼다(초안은 [`PERSONAL_PC_TEST_V1_DRAFT.md`](PERSONAL_PC_TEST_V1_DRAFT.md)). 단계 번호·제목·보고 표 행 이름을 못박는 시험도 새 시험지에 맞춰 강화한다 | test_packaging_docs·test_docs_entrance(화면 배치·0-0 단계 단언) | FINAL | 대기 |
| D11 | `docs/PACKAGE_OCR.md:3` | `개인 PC 제한 시험용, 미서명 추가 도구` | 글자 읽기 추가 도구는 v1.0 에 넣지 않는 것이 추천이라(확인 D) 고치지 않는다. 넣기로 하면 그때 따로 | test_ocr_addon_docs_facts | — | 고치지 않음 |

### 2-5. 제품 코드 안의 문구와 이름 (T2 — 이 갈래는 만지지 않는다)

| 번호 | 파일:줄 | 찾는 조각 | 바꿀 문장 초안 | 같이 볼 시험 | 담당 | 상태 |
|---|---|---|---|---|---|---|
| E01 | `src/chanceblog_desktop/ui/core/version.py:6` | `개인 PC 제한 시험용, 미서명 Package` | 화면 '정보' 카드의 안내 한 줄을 v1.0 의 사실(설치형·휴대용·서명 여부)로 | test_packaging_version_info·test_packaging_common | INSTALLER·RELEASE | 대기 |
| E02 | `packaging/pkgcommon.py:16` | `personal-pc-preview` | 묶음 정보의 채널 이름(`PACKAGE_INFO.json` 의 channel)을 정식 채널 이름으로. 화면의 `version.py` 와 같은 값이어야 한다(시험이 지킨다) | test_packaging_common·test_packaging_manifest·test_packaging_version_info | INSTALLER·RELEASE | 대기 |
| E03 | `packaging/pkgcommon.py:17` | `개인 PC 제한 시험용, 미서명 Package` | 묶음 정보·윈도 버전 정보의 안내 문구(NOTICE) | test_packaging_common·test_packaging_manifest·test_packaging_qt | INSTALLER·RELEASE | 대기 |
| E04 | `packaging/make_manifest.py:63` | `공개 배포용이 아닙니다. 앱 자체의 라이선스는 아직 정해지지 않았습니다` | 라이선스 결정(확인 C) 뒤의 사실로 | test_packaging_manifest | DOCS(b) | 대기 |
| E05 | `packaging/make_manifest.py:463` | `정식 0.1.0 이 아닙니다` | 정식 판이면 이 설명 줄을 지우거나 바꾼다 | test_packaging_manifest | DOCS(b) | 대기 |
| E06 | `src/chanceblog_desktop/ui/core/text.py:97` | `이 시험 버전은 글을 GitHub 에 올리지 않아 Git 로그인도 안 써요` | 외부 게시를 켠 범위에 맞는 안내 글로(`nokey_note_off`) | test_ui_settings·test_ui_qt_keys | PUBPR | 대기 |
| E07 | `src/chanceblog_desktop/ui/core/text.py:99` | `이 시험 버전은 Blogger 로 글을 보내지 않아요` | Blogger 를 연 뒤의 안내 글로(`purpose_blogger_off`) | test_blogger_input_off·test_ui_qt_settings | BLOGGER | 대기 |

### 2-6. 워크플로 (`.github/` — T3 라서 운영자 승인 뒤에만)

| 번호 | 파일:줄 | 찾는 조각 | 바꿀 문장 초안 | 같이 볼 시험 | 담당 | 상태 |
|---|---|---|---|---|---|---|
| F01 | `.github/workflows/package.yml:1` | `Package — 개인 PC 제한 시험용 빌드(수동)` | 릴리스 워크플로가 이것을 대신하거나 이름을 바꾸면 시험지 0-0·`PACKAGE.md`·`MIGRATION.md` 가 이 이름을 그대로 부르는 곳도 같이 고친다 | test_docs_entrance(워크플로 이름과 문서를 맞춘다)·test_packaging_workflow | RELEASE | 대기 |
| F02 | `.github/workflows/package.yml:52` | `ChanceBlogDesktop-preview` | 올림 꾸러미 이름(`name:`)을 바꾸면 위와 같은 곳을 같이 고친다 | test_workflow_artifacts·test_packaging_workflow·test_docs_entrance | RELEASE | 대기 |
| F03 | `.github/workflows/package-ocr.yml:67` | `ChanceBlogDesktop-OCR-preview` | 글자 읽기 추가 도구는 v1.0 제외 추천이라 고치지 않는다 | test_workflow_artifacts | — | 고치지 않음 |

## 3. 문장이 아닌 점검 — 릴리스 직전에 사실로 확인할 것

문장을 고치는 일이 아니라 **있는지·같은지 확인**하는 것들이다. FINAL 의 점검 스크립트(`scripts/release_check.py` — 아직 없다)가 읽을 수 있게 확인 방법을 한 줄씩 적었다.

| 번호 | 점검 | 확인 방법 | 담당 |
|---|---|---|---|
| G01 | `LICENSE` 파일이 저장소 맨 위에 있다(지금은 없다 — D-13, 확인 C) | 파일이 있고 `LICENSES/` 의 제3자 고지와 어긋나지 않는다 | DOCS(b) |
| G02 | `VERSION` = `CHANGELOG.md` 맨 위 절 = 화면 '정보' 의 버전 = 묶음 정보의 버전 = Release 제목 | `RELEASE.md` 의 '릴리스 노트 규칙' 대로 시험·점검 스크립트가 같은 값인지 본다 | FINAL·RELEASE |
| G03 | 티스토리가 `src`·`packaging`·`.github` 에 한 글자도 없다(완료 기준 8) | 낱말 검색 0건(`D-01`) | FINAL |
| G04 | 후보 산출물(설치 파일·휴대용 zip·로그·백업·진단 복사)에 키 모양이 없다 | `security/scan.py` 로 훑는다 | FINAL |
| G05 | 만든 결정 색인이 최신이다 | `python scripts/gen_decision_index.py --check` | 모든 갈래 |
| G06 | 오류 카탈로그·핵심 코드가 문서·기록과 같다 | `python scripts/sync_errors.py --check`·`python scripts/sync_core.py --check` | 모든 갈래 |
| G07 | SmartScreen·스마트 앱 컨트롤 안내 글이 운영자 PC 시험 결과와 같다 | 운영자 시험지의 결과 표 | FINAL |
| G08 | PySide6(LGPL)를 동적으로 연결한 상태이고 고지문이 최신이다(D-407) | 묶음의 `LICENSES/` 와 `--selftest` 의 `licenses` 항목 | INSTALLER |
| G09 | 운영자 시험지 결과 표의 빈 칸이 0 이다(설치·제거·이전 판에서 업데이트·롤백·휴대용·Pages 시험 글·Blogger 초안) | 초안은 [`PERSONAL_PC_TEST_V1_DRAFT.md`](PERSONAL_PC_TEST_V1_DRAFT.md) | FINAL |
| G10 | 위 2번 표의 `대기` 가 0 이다 | 이 문서의 시험이 상태 낱말과 조각을 확인한다 | DOCS(b) |

## 4. 고치는 순서 제안

1. 기능 갈래가 먼저 자기 문장을 고친다(GUI → NET → PUBPR → UPDATE → BLOGGER → INSTALLER → RELEASE 의 병합 순서). 고친 갈래는 이 표의 자기 행을 `고침` 으로 바꾼다(시험이 조각이 사라졌는지 본다).
2. 마지막 DOCS(b) 가 남은 `대기` 를 고치고 `VERSION`·`CHANGELOG.md` 의 `1.0.0` 절·`LICENSE`(확인 C 뒤)를 올린다. 이때 위의 '같이 볼 시험' 가운데 문장을 못박은 단언을 새 사실로 바꾼다 — **약하게 하거나 지우지 않는다**.
3. FINAL 이 3번 표를 한 번에 확인하고 `대기` 가 0 인지 본 뒤 후보 빌드를 시험한다.
