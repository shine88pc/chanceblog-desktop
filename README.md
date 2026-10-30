# chanceblog-desktop

여러 블로그(GitHub Pages·Blogger·네이버)의 글을 **한 곳에서 쓰고·검수하고·플랫폼별로 내보내는 개인용 Windows 데스크톱 프로그램**입니다. 한국어 화면이 기본이고, **AI 없이도 모든 핵심 기능이 동작합니다**(무료 AI 는 선택 보조이고 기본은 꺼짐).

> **상태: 설계 단계입니다. 아직 설치할 수 있는 버전이 없습니다.** 첫 설치 파일은 `0.1.0` 부터 [Releases](../../releases) 에 올라옵니다.

## 이 저장소와 `chanceblog` 의 관계

| | [`chanceblog`](https://github.com/shine88pc/chanceblog) | 이 저장소(`chanceblog-desktop`) |
|---|---|---|
| 역할 | **GitHub Pages 콘텐츠와 클라우드 자동 발행·감시** — GitHub Actions 가 PC·AI 없이 매일 글을 만들어 올린다(GitHub Pages 자동, Blogger 초안, 네이버 초안 이슈), 감시·텔레그램 알림, 운영자 요청 채널 | **개인 PC 작업대** — 원고를 직접 쓰거나 불러와 검사·미리보기·승인 뒤 플랫폼별로 내보낸다. 설치 파일·버전·업데이트·플랫폼 연동을 GitHub Releases 로 배포한다 |
| 둘의 연결 | 앱이 **기존 `chanceblog` 로컬 저장소를 연결**해 GitHub Pages 용 글·이미지를 만들고 push → **기존 자동 배포 흐름**을 그대로 쓴다 | |
| 규칙의 정본 | `AGENTS.md`·`docs/CHARTER.md`·`docs/SECURITY_GUARDRAILS.md`·`docs/AGENT_RUNBOOK.md` | `AGENTS.md`(이 저장소에만 필요한 것만 적고 나머지는 위를 따른다) |
| 운영자 호출 | 텔레그램 알림(요청 파일 `인수인계/요청함/R-nnn_*.md` 를 `ai/claude/**` 브랜치로 push) | **이 저장소에는 알림 워크플로·시크릿이 없다.** 운영자에게 알릴 일은 `chanceblog` 로 보낸다 |

글을 만드는 **핵심 코드(검사 규칙·프로필·Blogger 어댑터 등)는 `chanceblog` 의 것을 정해진 버전으로 가져다 쓴다**([`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §4). 프로그램 코드의 수정·유지보수는 운영자가 필요할 때 Claude Code 나 다른 AI 코딩 에이전트를 직접 실행하는 방식이며, 무료 AI 로 세션형 개발을 대신하지 않습니다.

## 읽을 문서

| 문서 | 내용 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | AI 코딩 도구 공통 작업 규칙(어느 AI 든 먼저 읽는다) · [`CLAUDE.md`](CLAUDE.md) 는 Claude Code 용 진입 지침 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 구조·Pages 연결·데이터 모델·오류 안내·선택 보조 AI·AI 없이 되는 기능 |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 설계 결정 기록(날짜·근거·기본값) |
| [`docs/PLATFORM_POLICY.md`](docs/PLATFORM_POLICY.md) | 플랫폼별로 하는 것·하지 않는 것 |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | 오류 코드와 하실 일(규칙 기반) |
| [`docs/RELEASE.md`](docs/RELEASE.md) | 설치 파일·자동 업데이트·릴리스 절차 |
| [`docs/SECURITY.md`](docs/SECURITY.md) | 키·로그·업데이트 보안 |
| [`docs/MIGRATION.md`](docs/MIGRATION.md) | 회사 PC → 개인 PC 이관과 새 PC 준비 |
| [`CHANGELOG.md`](CHANGELOG.md) · `VERSION` | 변경 이력과 현재 버전 |

## 개발 방식

사람(운영자)은 비개발자이고, 코드는 AI 도구가 작성하고 다른 주체가 검증합니다. 모든 변경은 브랜치 `ai/<도구>/<주제>` → PR → **운영자 병합** 순서이고, 시험(`python -m unittest discover -s tests`)과 CI 가 통과해야 합니다. 승인이 필요한 일(시크릿·계정·서명 키·새 플랫폼·삭제·정책)은 번호 있는 요청으로 묻습니다. 키는 저장소에 두지 않습니다(`.env.example` 에는 변수 이름만 있습니다).
