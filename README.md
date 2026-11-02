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

## 명령줄로 써 보기

아직 화면(GUI)과 설치 파일은 없습니다. 대신 **명령줄**로 글을 만들고 검토해 GitHub Pages(연결한 `chanceblog`)에 올릴 수 있습니다(Python 3.10 이상과 Git 이 필요하고, AI 는 쓰지 않습니다). 저장소 폴더에서 처음 한 번 `set PYTHONPATH=src`(PowerShell 은 `$env:PYTHONPATH = "src"`)를 실행한 뒤 아래 명령을 씁니다. 글번호는 앞 4자만 써도 되고, 모든 명령에 `--json`(프로그램이 읽는 출력)을 붙일 수 있으며, 종료 코드는 0(정상)·1(처리된 오류 — 오류 코드와 하실 일을 보여 줍니다)·2(사용법 오류)입니다.

```text
python -m chanceblog_desktop doctor                          # 상태 점검(읽기만 합니다)
python -m chanceblog_desktop connect C:\work\chanceblog      # 올릴 chanceblog 폴더를 연결(한 번)
python -m chanceblog_desktop new --title "제목" --file 원고.md  # 글 만들기(기존 HTML 글은 import-html)
python -m chanceblog_desktop list                            # 글 목록과 상태
python -m chanceblog_desktop review 글번호 --platform pages --category 경제·일 --lang ko --image-url https://… --tags 태그1,태그2
python -m chanceblog_desktop approve 글번호 --platform pages   # 미리 보기를 읽고 직접 승인(검사를 다시 통과해야 합니다)
python -m chanceblog_desktop publish-pages 글번호              # 먼저 미리 보기 — 아직 아무것도 하지 않습니다
python -m chanceblog_desktop publish-pages 글번호 --yes        # 정말로 기록(commit)하고 올립니다(push)
python -m chanceblog_desktop check-deploy 글번호               # 공개 주소가 열리는지 확인(열리면 '공개됨')
```

- **확인 없이는 올리지 않습니다.** `publish-pages` 는 `--yes` 가 없으면 무엇을 할지 보여 주기만 하고, 글 지우기(`delete`)도 `--yes` 가 있어야 합니다. 올리다 멈추면 같은 명령을 다시 실행하면 이어서 하고, 올리지 않고 되돌리려면 `publish-pages 글번호 --cancel --yes` 입니다. 다른 창에서 같은 글을 올리는 중이면 `PUBLISH_IN_PROGRESS` 로 멈추고 아무것도 바꾸지 않습니다(작업이 죽어 남은 잠금은 그 프로세스가 끝났으면 바로, 아니면 30분 뒤 넘겨받습니다). **다른 글**이 같은 저장소에 올라가는 중이면 끝나기를 기다렸다가(최대 2분) 이어서 올리고, 끝내 안 끝나면 `PUBLISH_REPO_BUSY` 로 아무것도 바꾸지 않고 물러납니다 — 같은 명령을 다시 실행하면 됩니다. 올리지 않은 commit 이 이미 있으면(앱이 올리다 멈춘 글·직접 만든 commit) 새 글을 올리지 않고, 어느 글을 어떻게 하면 되는지(이어서 올리기·나중 글부터 `--cancel --yes`·직접 확인) 한 가지를 알려 줍니다. 올리고 나서 멈춘 글에 `--cancel` 을 쓰면 `PUBLISH_ALREADY_PUSHED` — `--cancel` 없이 같은 명령을 실행하면 마무리합니다. 기록(commit) 직후에 멈춘 경우에도 같은 명령이 이어받고 `--cancel --yes` 가 되돌립니다(`doctor` 가 알려 줍니다). 글에 HTML 태그·`javascript:` 주소·`{% %}`/`{{ }}`·광고 스크립트·눈에 안 보이는 글자가 있으면 검사가 막습니다 — 제목·분야·태그·이미지 주소·설명 같은 머리말 값도 같고, 제목은 글을 만들 때(`new`)·고칠 때(`edit`)부터 막습니다. `delete` 는 `--yes` 가 없으면 어느 글인지만 보여 주고, 지울 때는 먼저 백업합니다. `restore` 도 `--yes` 가 없으면 어느 백업인지만 보여 주고 아무것도 바꾸지 않으며(`restore --latest --yes`), 바꾸기 직전 상태를 따로 백업해 둡니다.
- 네이버: `naver-profile set naver_a --name 표시명 --url https://blog.naver.com/아이디` 로 블로그 프로필을 정한 뒤 `review 글번호 --platform naver_a` → `naver-package 글번호 --blog naver_a`(복사용 제목·본문·태그·이미지 자리) → 직접 발행 → `naver-done 글번호 --blog naver_a --url 발행한_주소`. 네이버 A·B 글이 많이 비슷하면 `--similarity-approved` 로 직접 승인해야 합니다. 앱은 네이버에 로그인하거나 글을 대신 올리지 않습니다.
- 글·설정·백업은 PC 의 사용자 데이터 폴더(Windows: `%LOCALAPPDATA%\ChanceblogDesktop`)에만 두고 저장소 안에는 두지 않습니다(`--data-dir` 로 바꿀 수 있지만 저장소 폴더 안은 거절합니다). `backup`·`restore` 로 백업과 복구를 합니다. 키·토큰은 읽지도 보이지도 않고, 화면에 나가는 모든 글은 비밀 모양을 가립니다.
- 모든 명령과 옵션은 `python -m chanceblog_desktop --help` 와 `명령 --help` 에 한국어로 설명되어 있습니다. 구현 범위와 한계는 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §5 `service/`, 오류 코드는 [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) 에 있습니다.

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
