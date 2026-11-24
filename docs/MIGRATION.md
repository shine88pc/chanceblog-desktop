# 회사 PC → 개인 PC 이관과 새 PC 준비

> 한 줄: **저장소(GitHub)가 단일 진실원천이라 옮길 파일이 없다.** 새 PC 에서 clone 하면 끝이다. 이관 대상·제외 대상은 아래 표, 준비 순서는 §2. 운영자(비개발자)가 하는 일과 AI 가 하는 일을 나눠 적었다.

> **현황(2026-11-23 덧붙임)**: 이 문서는 2026-10-30 에 '회사 PC → 개인 PC' 로 썼다. 실제 이관은 2026-11-15 에 AI 의 작업 PC 를 옛 공용 PC 에서 새 공용 PC 로 한 번 옮긴 것이고(옛 PC 의 로컬 파일 없이 저장소와 인수 문서로 이어받았다), 2026-11-23 에는 다음 PC(개인 PC 또는 빈 공용 PC — 운영자 확인 대기)로의 이전을 준비하고 있다. 아래 §2 의 절차(clone·작성자 설정·환경·push 점검)는 어느 새 PC 에도 그대로 맞는다. 새 세션이 읽는 순서·AI 기억 사본·도구 모음은 블로그 저장소 `chanceblog` 의 `docs/SESSION_START.md` 2-4 와 `인수인계/AI_기억/README.md`·`인수인계/도구/README.md` 에 있다(§5).

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
저장소 github.com/shine88pc/chanceblog-desktop 을 이 작업 폴더에 clone(이미 있으면 git pull)해서 AGENTS.md → docs/ARCHITECTURE.md 순서로 읽고 docs/DECISIONS.md 는 마지막 10행과 필요한 번호만 읽어줘(AGENTS.md 0절 — 1MB 가 넘어 전체를 읽지 않는다).
같은 폴더에 github.com/shine88pc/chanceblog 도 clone 해서 그 저장소 CLAUDE.md 가 가리키는 순서(인수인계/작업내용.md 맨 위 30초 카드와 이어가기 순서, 새 PC 면 이어서 docs/SESSION_START.md 2-4)로 읽어줘 — 운영자 호출·승인 요청은 그 저장소의 요청 채널로 보낸다.
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
| 2026-11-23 | 다음 PC(개인 PC 또는 빈 공용 PC — 운영자 확인 대기)로의 이전을 준비 중 — 빈 PC 에서 이어받는 도구·읽는 순서를 저장소에 모아 두는 중(이관 번들) | `인수인계/도구/README.md` |

새 세션이 읽는 순서는 그 저장소 `CLAUDE.md` 가 정한다: `인수인계/작업내용.md` 맨 위 30초 카드와 이어가기 순서 → (PC 를 바꾼 새 세션이면) `docs/SESSION_START.md` 2-4 → `인수인계/도구/README.md` → `인수인계/AI_기억/README.md`. 이 앱 저장소의 일은 위 §2 의 준비 다음에 `AGENTS.md` 0절의 순서로 읽으면 된다. 이 절의 사실이 바뀌면 이 표에 줄을 덧붙인다(기존 줄은 고치지 않는다).

## 6. 새 clone 에서 처음부터 — 개발자 시작 순서 (v1.0 준비, 2026-11-24 덧붙임)

> 한 줄: **저장소 받기 → 가상환경(저장소 밖) → 잠금 파일로 설치 → 빠른 확인 → 시험 → 화면 열기 → 시험용 Package 만들기** 순서다. 사람이 읽어도 AI 코딩 도구가 읽어도 같은 순서를 쓴다. 위 §2 는 '새 PC 를 준비하는 일' 이고, 이 절은 '받은 소스를 실제로 돌려 보는 명령' 이다.

> **이 절을 어떻게 확인했나(사실대로).** 아래 명령은 이 저장소의 소스·`--help`·잠금 파일·워크플로를 읽어 대조했다. 설치가 필요 없는 명령(`--help`·`doctor`·`scripts/sync_errors.py --check`·`scripts/sync_core.py --check`·`packaging/gui_entry.py --selftest`·`scripts/ci_shard.py 1 3 --list`)은 2026-11-24 에 실제로 실행해 아래와 같은 결과를 보았다. **새 PC 에서 처음부터 끝까지 따라 해 본 기록은 아직 없다**(v1.0 완료 기준 1번에 남은 일 — 운영자 PC 에서 한 번 해 보기). 설치·빌드·화면 실행은 이 절을 쓰면서 하지 않았고, 그런 곳은 '확인 못 함' 이라고 적었다. 따라 하다 다른 결과가 나오면 그 사실을 알려 달라 — 그때 이 절을 고친다.

### 6-1. 준비물

| 준비물 | 조건 | 어디서 확인했나 |
|---|---|---|
| 운영체제 | Windows 10/11 64비트. 시험과 명령줄은 Linux 에서도 돈다(CI 에 Ubuntu 칸이 있다). 화면·키 보관·Package 빌드는 Windows 에서만 의미가 있다 | `.github/workflows/ci.yml` 의 칸 목록, `packaging/build_package.py`(윈도가 아니면 빌드를 거절) |
| Git | Git for Windows(기본 옵션). 소스를 받을 때와 Package 빌드의 '깨끗한 작업 트리' 검사에 쓴다 | 위 §2, `packaging/build_package.py` |
| Python | **3.12(64비트)** — Package 빌드는 3.12(64비트) 기준이다(잠금 파일·빌드 방법 글이 그렇게 적혀 있다). 소스 실행·시험은 3.10 과 3.12 를 CI 가 둘 다 돌린다(코드는 3.10 문법). 3.11·3.13 은 CI 가 돌리지 않아 **확인 못 함** | `packaging/make_manifest.py` 의 빌드 방법 글, `ci.yml`, `AGENTS.md` §4 |
| 쉘 | PowerShell(Windows 에 들어 있는 것으로 충분하다) | — |
| 인터넷 | 소스를 받을 때와 잠금 파일을 설치할 때만. 시험과 화면은 인터넷 없이 돈다 | `AGENTS.md` §4(시험은 네트워크 없이) |

### 6-2. 순서

명령은 PowerShell 에서 **저장소 맨 위 폴더**(받으면 생기는 `chanceblog-desktop` 폴더)에서 친다. 아래 `..` 는 그 폴더의 부모 폴더다.

**1) 저장소 받기**

```text
git clone <저장소 주소>
cd chanceblog-desktop
git status --short
```

- `<저장소 주소>` 는 GitHub 의 저장소 첫 화면에서 초록색 `Code` 단추를 눌러 복사한다(이 문서에는 웹 주소를 적지 않는다 — 같은 명령이 위 §2 의 'AI 가 하는 일' 1번에 있다). 받은 가지는 `main` 이다.
- 마지막 `git status --short` 에는 아무것도 나오지 않아야 한다(깨끗한 작업 트리).
- 커밋할 사람은 이 clone **안에서만** `user.name`·`user.email` 을 정한다(§2 의 2번). 시스템의 `core.autocrlf=true` 는 끄지 않는다.

**2) 가상환경 만들고 잠금 파일로 설치하기**

```text
python -m venv ..\chanceblog-venv
..\chanceblog-venv\Scripts\python -m pip install -r packaging/requirements-package.txt
```

- 가상환경은 저장소 **밖**에 만든다(저장소 안에 git 이 무시하지 않는 이름으로 만들면 Package 빌드의 '깨끗한 작업 트리' 검사에 걸린다 — [`PACKAGE.md`](PACKAGE.md) §2). 이 절은 활성화 스크립트(`Activate.ps1`)를 쓰지 않고 가상환경의 `python` 을 경로로 직접 부른다(PowerShell 실행 정책 때문에 활성화가 막히는 PC 에서도 같게 되도록).
- 잠금 파일 `packaging/requirements-package.txt` 는 정확한 버전(`==`)만 적는다. `[runtime]` 은 화면 도구 PySide6_Essentials 6.12.0 과 shiboken6 6.12.0, `[build]` 는 PyInstaller 를 비롯한 Package 만드는 도구다. 설치된 버전이 잠금과 다르면 Package 빌드가 거절한다.
- 이 저장소에는 `requirements-dev.txt` 가 **없다**(§2 의 'AI 가 하는 일' 3번의 '(있으면)' 은 없는 경우다). **앱 코드가 쓰는 바깥 패키지는 PySide6 하나뿐이다** — 소스·스크립트·시험의 `import` 를 훑어 확인했고 나머지는 모두 표준 라이브러리다.
- PySide6 를 깔지 않아도 명령줄과 대부분의 시험은 돈다(화면 시험 파일은 PySide6 가 없으면 통째로 건너뛴다). 앱이 PySide6 가 없을 때 알려 주는 설치법은 `python -m pip install PySide6` 이고 버전이 잠기지 않는다 — 잠금 파일 쪽을 권한다.
- 한계: 배포 파일(wheel)의 해시가 잠금에 없어 `--require-hashes` 로는 설치할 수 없다(잠금 파일 머리 주석). **이 설치 명령은 이 절을 쓰면서 실행하지 않았다(확인 못 함)**. 다만 PySide6_Essentials 6.12.0 과 shiboken6 6.12.0 만 설치한 가상환경에서 소스 점검(아래 4번)의 화면 항목 둘이 통과하는 것은 확인했다.

**3) 이 창에서만 쓰는 설정**

```text
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "src"
```

- `PYTHONUTF8=1`: 한국어 Windows 콘솔의 cp949 문제를 피한다(§2 의 3번과 같다).
- `PYTHONPATH=src`: 소스에서 `python -m chanceblog_desktop …` 을 부를 때만 필요하다. 설치되는 패키지가 아니라서 이것이 없으면 `No module named chanceblog_desktop` 이 나온다(확인함). 시험·`scripts/`·`packaging/` 도구는 스스로 `src` 를 경로에 넣으므로 필요 없다.
- **Package 를 만들 때는 이 두 줄을 치지 않은 새 PowerShell 창에서** 한다(빌드 도구가 PyInstaller 를 부를 때 `PYTHONPATH` 등은 빼지만 — `packaging/build_package.py` 의 `pyinstaller_env` — 깨끗하게 시작하는 쪽이 안전하다).

**4) 가장 빠른 확인 — 읽기만 한다(몇 초)**

```text
..\chanceblog-venv\Scripts\python -m chanceblog_desktop --help
..\chanceblog-venv\Scripts\python -m chanceblog_desktop doctor
..\chanceblog-venv\Scripts\python scripts/sync_errors.py --check
..\chanceblog-venv\Scripts\python scripts/sync_core.py --check
..\chanceblog-venv\Scripts\python packaging/gui_entry.py --selftest
```

| 명령 | 이렇게 나오면 정상 | 확인 |
|---|---|---|
| `--help` | 명령 목록(`doctor`·`connect`·`new`·… `topics`)과 맨 끝의 '처음이라면: doctor → connect 폴더 → new → …' 줄. `gui` 는 이 목록에 나오지 않는다(아래 6번에서 따로 연다) | 실행함 |
| `doctor` | 점검 결과 목록과 끝 줄 `고쳐야 할 것 0개, 주의 N개`. 새 PC 에는 백업·연결한 chanceblog 저장소가 없어 '주의' 가 나오는 것이 정상이다. 읽기만 한다 | 실행함 |
| `sync_errors.py --check` | `errors/catalog.py 가 문서와 같다.` | 실행함 |
| `sync_core.py --check` | `vendor/ 가 VENDOR.json 과 같다.` | 실행함 |
| `gui_entry.py --selftest` | 12항목 점검. 소스 실행에서는 묶음에만 있는 항목이 '건너뜀' 이고 마지막 줄이 `모두 정상`. PySide6 가 있으면 `통과 8 · 실패 0 · 건너뜀 4`, 없으면 `통과 6 · 실패 0 · 건너뜀 6` | 실행함(두 경우 모두) |

**5) 시험**

```text
..\chanceblog-venv\Scripts\python scripts/ci_shard.py 1 3
..\chanceblog-venv\Scripts\python scripts/ci_shard.py 2 3
..\chanceblog-venv\Scripts\python scripts/ci_shard.py 3 3
```

- CI 가 쓰는 방식이다(세 조각 — 시험 파일 사이를 겹치지 않게 나눈다). 조각 하나를 돌리기 전에 `… ci_shard.py 1 3 --list` 로 그 조각의 시험 파일 이름만 볼 수 있다(조각마다 시험 파일이 몇 개인지는 시험이 늘면 달라지므로 문서에 적지 않고 `--list` 의 줄 수로 센다). 하나라도 실패하면 종료 코드가 0 이 아니다.
- 한 번에 다 돌리는 `python -m unittest discover -s tests`(`README.md` 의 '개발 방식' 절과 위 §2 의 'AI 가 하는 일' 4번에 적힌 기본 명령)도 같은 시험이다. 시험이 많아(수천 개이고 계속 늘어난다 — 개수는 문서에 적지 않는다) **오래 걸린다 — 처음에는 한 파일씩 해 보라**: `..\chanceblog-venv\Scripts\python -m unittest discover -s tests -p "test_repo_layout.py"`.
- 시험은 네트워크와 실제 비밀 없이 돌아야 한다(`AGENTS.md` §4). 화면(Qt) 시험은 PySide6 가 있을 때만 돌고(창은 뜨지 않는다 — offscreen) 없으면 통째로 건너뛴다. **정식 CI 에는 PySide6 가 없어 화면 시험이 CI 에서는 건너뛰어진다**(D-32) — 화면 시험은 개발 PC 에서 따로 돌린다.
- 전체 시험은 이 절을 쓰면서 돌리지 않았다(**확인 못 함**). 새 PC 에서 처음 돌릴 때 실패가 나오면 시험 이름과 메시지를 그대로 알려 달라 — 환경 탓인지 코드 탓인지 가려야 한다. 한 건만 실패하면 그 시험 파일만 다시 돌려 본다.

**6) 화면 열기**

```text
..\chanceblog-venv\Scripts\python -m chanceblog_desktop gui --sample
..\chanceblog-venv\Scripts\python -m chanceblog_desktop gui --data-dir C:\work\data
```

- `--sample` 은 내 데이터 대신 **예시 데이터**로 화면을 보여 주고 아무 파일에도 쓰지 않는다. 옵션 없이 `gui` 만 치면 명령줄과 같은 사용자 데이터 폴더(`%LOCALAPPDATA%\ChanceblogDesktop`)를 읽는다 — 시험 삼아 열 때는 `--sample` 이나 저장소 밖의 `--data-dir` 폴더를 쓴다(저장소 폴더 안은 거절한다).
- PySide6 가 없으면 설치 방법만 알리고 끝난다(종료 코드 1, 확인함). 같은 데이터 폴더로 이미 열려 있으면 새 창 없이 열려 있는 창을 앞으로 가져오고 끝난다(SINGLEWIN — `--sample` 은 따로 열 수 있다).
- 창이 실제로 뜬 모습은 **확인 못 함**(이 절을 쓰면서 화면을 띄우지 않았다). 창 없이(offscreen) 화면 여섯(홈·후보·초안·Seed·블로그·설정)이 열리는 것은 4번의 `--selftest` 가 확인한다.

**7) 시험용 Package 만들기**

방법 하나(Windows PC 에서 직접):

```text
git status --short
..\chanceblog-venv\Scripts\python packaging/build_package.py
```

- 새 PowerShell 창에서, 작업 트리가 깨끗한 상태로 한다(`git status --short` 가 비어 있어야 한다. 커밋하지 않은 변경·새 파일이 있거나 `src`·`vendor`·`packaging` 안에 git 이 무시하는 파일이 있으면 빌드가 아무것도 만들지 않고 멈춘다).
- 결과는 `dist\package\release` 에 네 파일이다: 압축 파일(`ChanceBlogDesktop-<VERSION>-win64.zip`)·`SHA256SUMS`·`PACKAGE_INFO.md`·`PACKAGE_INFO.json`. 빌드는 끝에 묶음 실행 파일의 `--selftest` 12항목이 모두 통과해야 압축 파일을 만든다. 옵션 `--out-dir`·`--skip-scan`·`--allow-missing-gate` 는 [`PACKAGE.md`](PACKAGE.md) §2 에 있다(`--allow-missing-gate` 는 시험 빌드 전용이라 쓰지 않는다).
- 멈추면 `빌드를 멈췄어요: …` 한 문장이 나오고 종료 코드가 2 이다. 문장 읽는 법은 [`PACKAGE.md`](PACKAGE.md) 의 '실패 문장 읽는 법'.
- **확인 못 함**: 로컬 빌드는 이 절을 쓰면서 돌리지 않았다(PyInstaller 를 설치하지 않았다). 같은 순서로 GitHub Actions 의 수동 빌드가 만든 묶음을 운영자가 2026-11-13 에 개인 PC 에서 시험지로 한 번 시험해 보고했다(블로그 저장소 이슈 #190 — 그 보고로 고친 것이 CHANGELOG 의 SINGLEWIN 줄이다). 그 뒤 앱 소스가 많이 바뀌어 새 빌드로 다시 시험해야 한다.

방법 둘(PC 에 도구를 깔지 않고): GitHub 의 `Actions` 탭 → `Package — 개인 PC 제한 시험용 빌드(수동)` → `Run workflow` 는 **운영자가 직접 누른다**(AI 는 워크플로를 실행하지 않는다). 끝난 실행의 `Artifacts` 에서 받는 법은 [`PERSONAL_PC_TEST.md`](PERSONAL_PC_TEST.md) 0-0 에 있다(보관 14일).

만든 묶음은 풀어서 `ChanceBlogDesktop.exe --selftest` 로 다시 점검할 수 있다([`PACKAGE.md`](PACKAGE.md) §6).

### 6-3. 지금 상태 — 알려 둔 한계 (v1.0 전)

- **설치 파일(Setup)·자동 업데이트·시작 메뉴·제거 프로그램이 아직 없다.** 지금은 압축을 풀어 쓰는 휴대용 Package 하나뿐이고 새 버전은 새로 풀어서 쓴다([`RELEASE.md`](RELEASE.md) 는 장래 설계다).
- Package 는 **미서명**이다. SmartScreen 의 파란 창이나 스마트 앱 컨트롤 차단이 나올 수 있다([`PACKAGE.md`](PACKAGE.md) §10).
- 잠금 파일에 wheel 해시가 없다(위 2번).
- 정식 CI 에 PySide6 가 없어 화면 시험은 CI 에서 건너뛰어진다(위 5번).
- 외부 게시(GitHub Pages 올리기·Blogger·네이버 자동화)는 소스 상수로 완전히 꺼져 있다 — clone 한 앱에서 `connect` 로 chanceblog 폴더를 연결해도 글 올리기는 `EXTERNAL_WRITE_DISABLED` 로 멈춘다([`README.md`](../README.md) '명령줄로 써 보기').
- **새 PC 에서 처음부터 따라 해 본 기록이 없다**(위 머리말).

### 6-4. 도구 표 (`scripts/`·`packaging/`)

| 도구 | 하는 일 | 확인 |
|---|---|---|
| `scripts/ci_shard.py` | 시험을 N조각으로 나눠 한 조각만 돌린다(CI 와 같은 방식). `--list` 는 파일 이름만 보여 준다 | 실행함 |
| `scripts/sync_errors.py` | `TROUBLESHOOTING.md` 의 오류 코드 표에서 `errors/catalog.py` 를 만든다. `--check` 는 쓰지 않고 견주기만 한다 | 실행함 |
| `scripts/sync_core.py` | chanceblog 의 핵심 코드를 `vendor/` 에 원본 그대로 가져온다. `--check` 는 견주기만 한다([`ARCHITECTURE.md`](ARCHITECTURE.md) §4) | 실행함(`--check`) |
| `scripts/gen_decision_index.py` | `DECISIONS.md` 에서 결정 색인 [`DECISIONS_INDEX.md`](DECISIONS_INDEX.md) 를 만든다. `--check` 는 견주기만 한다. `--out` 이 결정 기록과 같은 파일이거나 이 도구가 만든 색인이 아닌 기존 파일이면 쓰지 않고 거절한다(종료 코드 2) | 시험이 지킴 |
| `scripts/ui_capture.py`·`ui_gallery.py`·`ui_image_check.py`·`ui_bench.py`·`ui_offscreen.py` | 화면 사진·부품 모음·사진 형식 점검·성능(창 없이, PySide6 필요) | 머리글만 읽음 |
| `packaging/build_package.py` | 시험용 Package 만들기 | `--help` 실행함 |
| `packaging/gui_entry.py` | 묶음의 시작 파일. 소스에서는 `--selftest` 만 쓴다 | 실행함 |
| `ocr_addon/` | 사진 글자 읽기 추가 도구(선택 기능, 별도 압축 파일) — [`PACKAGE_OCR.md`](PACKAGE_OCR.md) | 이 절에서는 다루지 않음 |

### 6-5. 막혔을 때

| 보이는 것 | 이유와 할 일 |
|---|---|
| `No module named chanceblog_desktop` | `PYTHONPATH=src` 를 안 쳤다(위 3번) |
| 한글이 깨지거나 `UnicodeEncodeError` | `$env:PYTHONUTF8 = "1"` 을 안 쳤다 |
| 빌드가 '설치된 도구가 잠금 파일과 달라요' 로 멈춤 | 잠금 파일로 다시 설치한다(위 2번). 가상환경이 다른 것이면 그 가상환경의 `python` 으로 부른다 |
| 빌드가 깨끗하지 않다고 멈춤 | `git status --short` 로 보이는 변경·새 파일을 정리한다. `src`·`vendor`·`packaging` 안의 git 이 무시하는 파일도 지운다(바이트코드 캐시는 괜찮다) |
| `Activate.ps1` 이 막힘 | 활성화를 쓰지 않는다 — 이 절은 가상환경의 `python` 경로를 직접 부른다 |
| `git push` 가 인증을 못 읽음 | §2 의 'AI 가 하는 일' 5번(`git push --dry-run` 으로 미리 점검)과 운영자에게 로그인 부탁 |
