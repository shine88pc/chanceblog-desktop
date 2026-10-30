# 설치 파일·자동 업데이트·릴리스

> 2026-10-30 조사(조사 에이전트가 공식 문서·릴리스 API 를 읽은 보고, `chanceblog` 의 `docs/analysis/2026-10-30_desktop-release-update.md`)를 이 저장소에 맞춰 줄인 것이다. **세부 수치는 요약 도구를 거친 것이라 시행 전에 원문과 대조한다.** 결정은 [`DECISIONS.md`](DECISIONS.md) D-04·D-05.

## 방식

**PyInstaller(`--onedir`) + Velopack(파이썬 SDK) + GitHub Releases 초안.** `vpk` 한 번으로 설치 파일(`Setup.exe`)·휴대용 ZIP·차등 업데이트·채널이 나온다. 직접 얹는 것은 둘: **Ed25519 서명 매니페스트**(업데이트 무결성)와 **앱 안의 백업·마이그레이션·롤백**(Velopack 문서에 자동 롤백이 없다). 2순위는 Inno Setup(사용자 단위) + tufup.

## 공개되는 파일(릴리스마다)

`BlogPublisher-Setup-x.y.z.exe` · `BlogPublisher-Portable-x.y.z.zip` · full/delta 패키지 · 채널 매니페스트 · `SHA256SUMS.txt`(+서명) · `CHANGELOG.md` · `MIGRATION_NOTES.md`. 채널은 Stable·Beta·Dev(태그 `vX.Y.Z`, `vX.Y.Z-beta.N`, `vX.Y.Z-dev.N`).

## 릴리스 절차

1. **버전 올리기(AI)**: PR 로 `VERSION`·`CHANGELOG.md`·이관 노트·DB 마이그레이션 갱신 → 시험·CI 통과 → 운영자 병합 → 태그(운영자 승인 뒤에만 만든다. 릴리스 태그는 T3).
2. **Actions 빌드**(`windows-latest`): 시험 → PyInstaller → 자가 점검(`--selftest`) → `vpk pack --channel` → SHA256SUMS + Ed25519 서명 → **초안 릴리스**로 업로드(`--publish` 를 쓰지 않는다).
3. **운영자 공개**: 텔레그램 요청의 안내대로 'Publish release' 한 번. 저장소 설정에서 **불변 릴리스(Enable release immutability)** 를 켜 두면 공개 뒤 자산·태그를 바꿀 수 없다(운영자 설정, T3).
4. **앱의 확인**: 채널별로 확인, 서명 매니페스트의 서명·version·seq·expires 를 검증, 다운그레이드 거부.
5. **다운로드·검증**: Velopack 의 크기·해시 검증 + 서명된 해시 대조. 불일치하면 폐기.
6. **백업 → 적용 → 마이그레이션 → 점검**: SQLite backup API 로 스냅샷 → `apply_updates_and_restart` → 첫 실행에서 `PRAGMA user_version` 순방향 마이그레이션 → 자체 점검 통과 시 '정상' 표식.
7. **롤백**: 점검 실패나 연속 기동 실패 2회면 백업 복원 + 이전 릴리스 재설치(직접 구현·시험). 다운그레이드는 복구 모드에서만.
8. **업데이트 시험**: Actions 에서 (n-1) 설치 → (n) 업데이트 → 롤백 시뮬레이션.

## 워크플로 규칙

기본 권한 전부 차단(`permissions: {}`), 시험 잡은 `contents: read`, 빌드 잡은 환경 시크릿(`environment: release`, 필수 검토자)과 `contents: write`(초안 업로드)만. 액션은 전체 SHA 로 고정, `pip --require-hashes`, `vpk` 버전 = 파이썬 SDK 버전. 시크릿은 자동 `GITHUB_TOKEN` 과 `UPDATE_SIGNING_KEY`(Ed25519 개인키)뿐이다. **업데이트·서명·워크플로·공개키를 바꾸는 PR 은 T3 로 표시하고 승인 전에 병합하지 않는다.**

## 코드 서명

지금은 **무서명으로 시작**한다(유료 인증서는 사지 않는다). 앱이 받은 업데이트 파일에는 '인터넷에서 받음' 표식이 붙지 않아 SmartScreen 창이 뜨지 않고, 경고는 **첫 설치에만** 나온다. **Smart App Control(SAC)이 켜져 있으면 무서명 프로그램이 차단된다** — 먼저 개인 PC 에서 Windows 보안 → 앱 및 브라우저 컨트롤 → 스마트 앱 컨트롤 상태를 확인한다(끄거나 서명 도입). 서명이 필요해지면 SignPath(무료, OSI 라이선스·공개 저장소 등 조건 충족 시, 라이선스는 D-13) → 사업자등록이 있으면 Azure Artifact Signing(월 $9.99) → 인증서 구매 순. 서명해도 SmartScreen 평판은 수 주 걸리므로 1인 도구에서 서명의 실익은 주로 SAC 통과다. 서명하려면 번들 안 모든 PE(.exe/.dll/.pyd)와 제거기까지 서명해야 한다.

## 운영자만 하는 일 / AI 가 하는 일

- **운영자**: GitHub 패스키·2FA, 저장소 설정(불변 릴리스·Environment `release`·태그 보호·Actions 권한), 시크릿 값 입력(`UPDATE_SIGNING_KEY` — 키 생성 스크립트는 AI 가 쓰되 개인키 값은 운영자만 보관), 서명 계정 가입·결제, PC 점검(SAC), 최초 설치(경고 클릭), 릴리스마다 Publish.
- **AI**: 앱·시험·워크플로 PR, 업데이트 클라이언트·서명 검증·백업·마이그레이션·롤백, 릴리스·이관 노트·복구 안내, 의존성 잠금·점검.

## 확인하지 못한 것

Velopack 의 롤백·서명 검증은 '문서에 없음'일 뿐 코드는 미확인(정적 `latest/download` URL 방식 시험 필요), 파이썬 SDK 레퍼런스가 얇음, 설치기 한국어 지원, 토스트 알림용 앱 식별자, PyInstaller 오탐 빈도, 설치 크기·빌드 시간 실측, 서명 서비스의 한국 개인 자격. 점검 시점: 2026-11 말(서명 서비스 지역·자격), 2026-12(Velopack 1.3 정식·파이썬 SDK).
