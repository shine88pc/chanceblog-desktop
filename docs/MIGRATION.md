# 회사 PC → 개인 PC 이관과 새 PC 준비

> 한 줄: **저장소(GitHub)가 단일 진실원천이라 옮길 파일이 없다.** 새 PC 에서 clone 하면 끝이다. 이관 대상·제외 대상은 아래 표, 준비 순서는 §2. 운영자(비개발자)가 하는 일과 AI 가 하는 일을 나눠 적었다.

## 1. 옮기는 것 / 옮기지 않는 것

| 구분 | 항목 | 어떻게 |
|---|---|---|
| **이관(저장소에 이미 있음)** | 소스·브랜치·변경 이력, 규칙 문서(`AGENTS.md`·`CLAUDE.md`·`docs/`), 시험·샘플, 워크플로, 버전·변경 이력 | `git clone` 두 개: `chanceblog`(클라우드 파이프라인·요청 채널)와 `chanceblog-desktop`(이 저장소) |
| 이관 불필요 | 회사 PC 의 미커밋 변경 | 2026-10-30 확인: `chanceblog` 작업 사본은 깨끗하고 stash 도 없다 |
| **이관하지 않음** | 회사 PC 의 로그인 세션·브라우저 쿠키, 개인 API 키 원문, 회사 내부 자료, 게시 전 비공개 원고, 로컬 절대경로, 임시 파일·캐시 | 새 PC 에서 새로 로그인하고 키는 새로 발급해 앱의 보안 저장소에만 넣는다 |
| AI 도구의 **개인 기억** | 회사 PC 의 Claude 세션 메모리(운영 메모) | **이관하지 않는다.** 필요한 규칙은 이미 `chanceblog`(`AGENTS.md`·`docs/`)와 이 저장소 문서에 있다. 회사 PC 한정 사항(GitHub 화면 접속 차단, PPTX 환경)은 개인 PC 에는 해당 없다 |

보안 확인(2026-10-30): `chanceblog` 전체 이력(모든 브랜치)에서 키 모양 문자열 9종 0건, 로컬 절대경로·회사 식별자 0건. 키는 GitHub Actions 시크릿에만 있다.

## 2. 새 PC 준비 순서

**운영자가 하는 일(한 번)**
1. **Git for Windows** 설치(https://git-scm.com — 기본 옵션). **Python 3.12** 설치(https://www.python.org — 설치 화면에서 'Add python.exe to PATH' 체크). 가능하면 Python 3.10 도 함께(호환 시험용, 선택).
2. **GitHub 로그인**: 터미널에서 `git clone https://github.com/shine88pc/chanceblog-desktop.git` 후 처음 `git push` 를 할 때 브라우저 로그인 창이 뜨면 로그인(Git Credential Manager). 비밀번호·토큰을 AI 에게 알려 주지 않는다.
3. **AI 코딩 도구 설치·로그인**: 프로그램 코드의 수정·유지보수는 필요할 때 운영자가 직접 실행하는 Claude Code 나 다른 AI 코딩 에이전트로 합니다(D-06). 어느 도구든 이 저장소의 문서만으로 이어받을 수 있게 만든다. 무료 AI 로 대신하지 않는다(D-14).
4. **Smart App Control 확인**: Windows 보안 → 앱 및 브라우저 컨트롤 → 스마트 앱 컨트롤 — 켬/평가/끔 중 무엇인지 AI 에게 알려 준다(켜져 있으면 서명 없는 프로그램이 차단된다 — [`RELEASE.md`](RELEASE.md)).

**AI 가 하는 일(새 세션의 첫 30분)**
1. 두 저장소를 새 작업 폴더에 clone: `git clone https://github.com/shine88pc/chanceblog.git` · `git clone https://github.com/shine88pc/chanceblog-desktop.git`. 앱이 나오면 설정의 'chanceblog 로컬 저장소' 칸에 앞의 폴더를 지정한다(GitHub Pages 글을 만들고 push 하는 연결, [`ARCHITECTURE.md`](ARCHITECTURE.md) §3).
2. 작성자 설정은 **각 clone 안에서만**: `git config user.name "<표시할 이름>"` · `git config user.email "<공개해도 되는 이메일 — GitHub 설정의 noreply 주소 권장>"`(값은 운영자가 정해 알려 준다. 이 저장소에는 실명·이메일을 적지 않는다 — AGENTS.md 규칙 2. 전역 설정은 건드리지 않는다). 시스템 `core.autocrlf=true` 는 끄지 않는다.
3. 환경: `python -m venv .venv` → `.venv\Scripts\pip install -r requirements-dev.txt`(있으면). 파이썬은 `PYTHONUTF8=1` 로 실행한다(한국어 Windows 콘솔 cp949 문제).
4. 기준선: `python -m unittest discover -s tests` 가 통과하는지(`chanceblog` 는 추가로 `python scripts/validate_repo.py`).
5. **push 가 되는지 아무것도 만들지 않고 점검**: `GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=false git push --dry-run --porcelain origin HEAD:refs/heads/ai/<이름>/preflight` — 종료 코드 0 과 `[new branch]` 줄이 보이면 된다. `could not read Username`(종료 128)이면 자격 증명이 없는 것이니 운영자에게 로그인을 부탁한다(AI 가 자격을 만들지 않는다).
6. 한글 커밋 메시지는 UTF-8 파일에 쓰고 `git commit -F 파일`.

## 3. 새 AI 세션에 붙여 넣는 시작 문구

```text
저장소 https://github.com/shine88pc/chanceblog-desktop 을 이 작업 폴더에 clone(이미 있으면 git pull)해서 AGENTS.md → docs/ARCHITECTURE.md → docs/DECISIONS.md 순서로 읽어줘.
같은 폴더에 https://github.com/shine88pc/chanceblog 도 clone 해서 AGENTS.md 와 docs/AGENT_RUNBOOK.md(J1~J12)를 읽어줘 — 운영자 호출·승인 요청은 그 저장소의 요청 채널로 보낸다.
먼저 push 가 되는지 `git push --dry-run` 으로 확인하고, 현재 상태를 10줄 이내로 보고한 뒤 [맡길 일]을 시작해줘. 브랜치는 ai/<네 이름>/<주제>, 한 일은 한 커밋, push 만 하고 PR 은 운영자가 만든다.
승인(T3)·비밀·서명 키는 건드리지 말고, 막히면 멈춰서 무엇이 필요한지만 알려줘.
```

## 4. 회사 PC 정리

작업 사본에 올리지 않은 변경이 없고, 세션 메모리는 이관하지 않으므로 회사 PC 의 사본은 그대로 폐기해도 된다. 회사 PC 에서 개인 블로그 계정에 로그인하는 자동화는 하지 않는다(회사 보안 규정과 부딪힐 수 있음 — 이슈 #83 판단).
