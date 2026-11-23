# 회사 PC → 개인 PC 이관과 새 PC 준비

> 한 줄: **저장소(GitHub)가 단일 진실원천이라 옮길 파일이 없다.** 새 PC 에서 clone 하면 끝이다. 이관 대상·제외 대상은 아래 표, 준비 순서는 §2. 운영자(비개발자)가 하는 일과 AI 가 하는 일을 나눠 적었다.

> **현황(2026-11-23 덧붙임)**: 이 문서는 2026-10-30 에 '회사 PC → 개인 PC' 로 썼다. 실제 이관은 2026-11-15 에 AI 의 작업 PC 를 옛 공용 PC 에서 새 공용 PC 로 한 번 옮긴 것이고(옛 PC 의 로컬 파일 없이 저장소와 인수 문서로 이어받았다), 2026-11-23 에는 개인 PC 로의 이전을 준비하고 있다. 아래 §2 의 절차(clone·작성자 설정·환경·push 점검)는 어느 새 PC 에도 그대로 맞는다. 새 세션이 읽는 순서·AI 기억 사본·도구 모음은 블로그 저장소 `chanceblog` 의 `docs/SESSION_START.md` 2-4 와 `인수인계/AI_기억/README.md`·`인수인계/도구/README.md` 에 있다(§5).

## 1. 옮기는 것 / 옮기지 않는 것

| 구분 | 항목 | 어떻게 |
|---|---|---|
| **이관(저장소에 이미 있음)** | 소스·브랜치·변경 이력, 규칙 문서(`AGENTS.md`·`CLAUDE.md`·`docs/`), 시험·샘플, 워크플로, 버전·변경 이력 | `git clone` 두 개: `chanceblog`(클라우드 파이프라인·요청 채널)와 `chanceblog-desktop`(이 저장소) |
| 이관 불필요 | 회사 PC 의 미커밋 변경 | 2026-10-30 확인: `chanceblog` 작업 사본은 깨끗하고 stash 도 없다 |
| **이관하지 않음** | 회사 PC 의 로그인 세션·브라우저 쿠키, 개인 API 키 원문, 회사 내부 자료, 게시 전 비공개 원고, 로컬 절대경로, 임시 파일·캐시 | 새 PC 에서 새로 로그인하고 키는 새로 발급해 앱의 보안 저장소에만 넣는다 |
| AI 도구의 **개인 기억** | 옛 PC 의 Claude 세션 메모리(운영 메모) | 기억 **파일 자체는 옮기지 않는다.** 필요한 규칙은 이미 `chanceblog`(`AGENTS.md`·`docs/`)와 이 저장소 문서에 있고, 새 세션이 읽을 상시 지시·정책의 **기록 사본**은 블로그 저장소 `chanceblog` 의 `인수인계/AI_기억/` 에 있다(2026-11-04 이전 준비 때 올림 — 정본이 아니라서 문서와 다르면 문서가 이긴다). 회사 PC 한정 사항(GitHub 화면 접속 차단, PPTX 환경)은 개인 PC 에는 해당 없다 |

보안 확인(2026-10-30): `chanceblog` 전체 이력(모든 브랜치)에서 키 모양 문자열 9종 0건, 로컬 절대경로·회사 식별자 0건. 키는 GitHub Actions 시크릿에만 있다.

## 2. 새 PC 준비 순서

**운영자가 하는 일(한 번)**
1. **Git for Windows** 설치(https://git-scm.com — 기본 옵션). **Python 3.12** 설치(https://www.python.org — 설치 화면에서 'Add python.exe to PATH' 체크). 가능하면 Python 3.10 도 함께(호환 시험용, 선택).
2. **GitHub 로그인**: 터미널에서 `git clone https://github.com/shine88pc/chanceblog-desktop.git` 후 처음 `git push` 를 할 때 브라우저 로그인 창이 뜨면 로그인(Git Credential Manager). 비밀번호·토큰을 AI 에게 알려 주지 않는다.
3. **AI 코딩 도구 설치·로그인**: 프로그램 코드의 수정·유지보수는 필요할 때 운영자가 직접 실행하는 Claude Code 나 다른 AI 코딩 에이전트로 합니다(D-06). 어느 도구든 이 저장소의 문서만으로 이어받을 수 있게 만든다. 무료 AI 로 세션형 개발 전체를 대신하지 않는다(D-14). 작은 수정(T0·T1)에 쓸 무료 도구와 코드 수정이 안 되는 알림·글쓰기용 AI 의 구분, DeepSeek-Coder 판단은 `chanceblog` 저장소의 `docs/AI_MODEL_GUIDE.md`(D-20)를 따른다.
4. **Smart App Control 확인**: Windows 보안 → 앱 및 브라우저 컨트롤 → 스마트 앱 컨트롤 — 켬/평가/끔 중 무엇인지 AI 에게 알려 준다(켜져 있으면 서명 없는 프로그램이 차단된다 — [`RELEASE.md`](RELEASE.md)).

**AI 가 하는 일(새 세션의 첫 30분)**
1. 두 저장소를 새 작업 폴더에 clone: `git clone https://github.com/shine88pc/chanceblog.git` · `git clone https://github.com/shine88pc/chanceblog-desktop.git`. 앱이 나오면 `python -m chanceblog_desktop connect 앞의 폴더경로` 로 앞의 폴더를 연결한다(화면에는 이 연결을 정하는 칸이 아직 없다 — GitHub Pages 글을 만들고 push 하는 연결, [`ARCHITECTURE.md`](ARCHITECTURE.md) §3).
2. 작성자 설정은 **각 clone 안에서만**: `git config user.name "<표시할 이름>"` · `git config user.email "<공개해도 되는 이메일 — GitHub 설정의 noreply 주소 권장>"`(값은 운영자가 정해 알려 준다. 이 저장소에는 실명·이메일을 적지 않는다 — AGENTS.md 규칙 2. 전역 설정은 건드리지 않는다). 시스템 `core.autocrlf=true` 는 끄지 않는다.
3. 환경: `python -m venv .venv` → `.venv\Scripts\pip install -r requirements-dev.txt`(있으면). 파이썬은 `PYTHONUTF8=1` 로 실행한다(한국어 Windows 콘솔 cp949 문제).
4. 기준선: `python -m unittest discover -s tests` 가 통과하는지(`chanceblog` 는 추가로 `python scripts/validate_repo.py`).
5. **push 가 되는지 아무것도 만들지 않고 점검**: `GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=false git push --dry-run --porcelain origin HEAD:refs/heads/ai/<이름>/preflight` — 종료 코드 0 과 `[new branch]` 줄이 보이면 된다. `could not read Username`(종료 128)이면 자격 증명이 없는 것이니 운영자에게 로그인을 부탁한다(AI 가 자격을 만들지 않는다).
6. 한글 커밋 메시지는 UTF-8 파일에 쓰고 `git commit -F 파일`.

## 3. 새 AI 세션에 붙여 넣는 시작 문구

```text
저장소 https://github.com/shine88pc/chanceblog-desktop 을 이 작업 폴더에 clone(이미 있으면 git pull)해서 AGENTS.md → docs/ARCHITECTURE.md 순서로 읽고 docs/DECISIONS.md 는 마지막 10행과 필요한 번호만 읽어줘(AGENTS.md 0절 — 1MB 가 넘어 전체를 읽지 않는다).
같은 폴더에 https://github.com/shine88pc/chanceblog 도 clone 해서 그 저장소 CLAUDE.md 가 가리키는 순서(인수인계/작업내용.md 맨 위 30초 카드와 이어가기 순서, 새 PC 면 이어서 docs/SESSION_START.md 2-4)로 읽어줘 — 운영자 호출·승인 요청은 그 저장소의 요청 채널로 보낸다.
먼저 push 가 되는지 `git push --dry-run` 으로 확인하고, 현재 상태를 10줄 이내로 보고한 뒤 [맡길 일]을 시작해줘. 브랜치는 ai/<네 이름>/<주제>, 한 일은 한 커밋, push 만 해줘 — 병합할 가지(ai/claude/M번호-이름)는 검사가 끝나면 봇(auto-pr.yml)이 PR 을 만들고 병합은 운영자만 한다.
승인(T3)·비밀·서명 키는 건드리지 말고, 막히면 멈춰서 무엇이 필요한지만 알려줘.
```

## 4. 회사 PC 정리

작업 사본에 올리지 않은 변경이 없고, 세션 메모리 파일은 옮기지 않으며 기록 사본은 저장소에 있으므로 회사 PC 의 사본은 그대로 폐기해도 된다. 회사 PC 에서 개인 블로그 계정에 로그인하는 자동화는 하지 않는다(회사 보안 규정과 부딪힐 수 있음 — 이슈 #83 판단).

## 5. 이관 기록과 새 PC 에서 읽을 곳 (2026-11-23 덧붙임)

| 날짜 | 일 | 근거(블로그 저장소 `chanceblog` 의 문서) |
|---|---|---|
| 2026-10-30 | '회사 PC → 개인 PC' 이관 준비 — 이 문서를 씀(저장소가 단일 진실원천이라 옮길 파일이 없다) | 위 §1·§2 |
| 2026-11-04 | 새 PC 에서 이어받는 절차와 AI 기억 **기록 사본**을 저장소에 올림 | `docs/SESSION_START.md` 2-4 · `인수인계/AI_기억/README.md` |
| 2026-11-15 | AI 의 작업 PC 를 옛 공용 PC 에서 새 공용 PC 로 한 번 옮김(옛 PC 의 로컬 파일 없이 저장소와 인수 문서로 이어받음) | `인수인계/작업내용.md`(확인 017) |
| 2026-11-23 | 개인 PC 로의 이전을 준비 중 — 빈 PC 에서 이어받는 도구·읽는 순서를 저장소에 모아 두는 중(이관 번들) | `인수인계/도구/README.md` |

새 세션이 읽는 순서는 그 저장소 `CLAUDE.md` 가 정한다: `인수인계/작업내용.md` 맨 위 30초 카드와 이어가기 순서 → (PC 를 바꾼 새 세션이면) `docs/SESSION_START.md` 2-4 → `인수인계/도구/README.md` → `인수인계/AI_기억/README.md`. 이 앱 저장소의 일은 위 §2 의 준비 다음에 `AGENTS.md` 0절의 순서로 읽으면 된다. 이 절의 사실이 바뀌면 이 표에 줄을 덧붙인다(기존 줄은 고치지 않는다).
