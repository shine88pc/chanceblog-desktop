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

- **확인 없이는 올리지 않습니다.** `publish-pages` 는 `--yes` 가 없으면 무엇을 할지 보여 주기만 하고, 글 지우기(`delete`)도 `--yes` 가 있어야 합니다. 올리다 멈추면 같은 명령을 다시 실행하면 이어서 하고, 올리지 않고 되돌리려면 `publish-pages 글번호 --cancel --yes` 입니다. 다른 창에서 같은 글을 올리는 중이면 `PUBLISH_IN_PROGRESS` 로 멈추고 아무것도 바꾸지 않습니다(작업이 죽어 남은 잠금은 그 프로세스가 끝났으면 바로, 아니면 30분 뒤 넘겨받습니다). **다른 글**이 같은 저장소에 올라가는 중이면 끝나기를 기다렸다가(최대 2분) 이어서 올리고(이 잠금은 저장소의 `.git` 폴더 안에 있어서 `--data-dir` 을 다르게 준 다른 앱도 서로를 압니다 — `.git` 에 잠금 파일을 못 만들면 올리지 않고 멈춥니다), 끝내 안 끝나면 `PUBLISH_REPO_BUSY` 로 아무것도 바꾸지 않고 물러납니다 — 같은 명령을 다시 실행하면 됩니다. 올리지 않은 commit 이 이미 있으면(앱이 올리다 멈춘 글·직접 만든 commit) 새 글을 올리지 않고, 어느 글을 어떻게 하면 되는지(이어서 올리기·나중 글부터 `--cancel --yes`·직접 확인) 한 가지를 알려 줍니다. 올리고 나서 멈춘 글에 `--cancel` 을 쓰면 `PUBLISH_ALREADY_PUSHED` — `--cancel` 없이 같은 명령을 실행하면 마무리합니다. 기록(commit) 직후에 멈춘 경우에도 같은 명령이 이어받고 `--cancel --yes` 가 되돌립니다(`doctor` 가 알려 줍니다). 글에 HTML 태그·`javascript:` 주소·`{% %}`/`{{ }}`·광고 스크립트·눈에 안 보이는 글자가 있으면 검사가 막습니다(글자의 표시 방향을 바꾸는 제어 문자는 한 개만 있어도 막습니다) — 제목·분야·태그·이미지 주소·설명 같은 머리말 값도 같고, 제목은 글을 만들 때(`new`)·고칠 때(`edit`)부터 막습니다. `delete` 는 `--yes` 가 없으면 어느 글인지만 보여 주고, 지울 때는 먼저 백업합니다. 올렸지만 공개 확인이 끝나지 않은 글(`PUSHED`)은 먼저 `check-deploy` 로 마쳐야 지울 수 있습니다(지우면 발행 기록이 함께 지워져 공개 확인을 이어갈 수 없게 됩니다). `restore` 도 `--yes` 가 없으면 어느 백업인지만 보여 주고 아무것도 바꾸지 않으며(`restore --latest --yes`), 바꾸기 직전 상태를 따로 백업해 둡니다.
- 네이버: `naver-profile set naver_a --name 표시명 --url https://blog.naver.com/아이디` 로 블로그 프로필을 정한 뒤 `review 글번호 --platform naver_a` → `naver-package 글번호 --blog naver_a`(복사용 제목·본문·태그·이미지 자리) → 직접 발행 → `naver-done 글번호 --blog naver_a --url 발행한_주소`. 네이버 A·B 글이 많이 비슷하면 `--similarity-approved` 로 직접 승인해야 합니다. 앱은 네이버에 로그인하거나 글을 대신 올리지 않습니다.
- **주제 후보**(쓸 글감): 후보를 직접 적거나 CSV 로 가져와 목록에서 고르고, 고른 후보를 쓰고 있는 글과 잇습니다. 후보를 자동으로 모으거나 초안을 쓰는 일은 아직 없습니다.

```text
python -m chanceblog_desktop candidates add --topic "겨울 보일러 점검 순서" --keyword "보일러 점검" --blog naver_a   # 후보 직접 추가(--blog 는 여러 번 또는 쉼표로)
python -m chanceblog_desktop candidates import-csv 후보.csv --blog naver_a --data-date 2026-11-02            # CSV 가져오기(다시 가져와도 겹치지 않습니다)
python -m chanceblog_desktop candidates list --status 선택됨 --blog naver_a                                  # 목록(읽기만 합니다 — 거르기는 선택)
python -m chanceblog_desktop candidates show 3                                                              # 하나를 자세히(지표·연결한 글)
python -m chanceblog_desktop candidates select 3 --blog naver_a                                             # 그 블로그용으로 고르기(같은 키워드를 최근에 골랐다면 경고만 합니다)
python -m chanceblog_desktop candidates hold 3        # 보류      (reject 3 = 제외, review 3 = 검토 중, restore 3 = 제외한 후보 되살리기)
python -m chanceblog_desktop candidates link 3 글번호 # 후보 3번과 쓰고 있는 글을 잇기(unlink 3 으로 끊기)
python -m chanceblog_desktop candidates delete 1a2b3c4d --yes # 지우기 — 순번이 아니라 list 에 보이는 '번호'(앞 8자)로(되돌릴 수 없으니 다시 볼 후보는 reject — --yes 가 없으면 아무것도 지우지 않습니다)
```

- 후보는 `list` 에 보이는 **순번**(만든 시각 순, 1~999)이나 **번호**(앞 4자 이상 — `list` 의 '번호 1a2b3c4d' 는 앞 8자입니다)로 고르고, 앞부분이 여러 후보와 겹치면 어느 후보들인지 알려 줍니다. 순번은 후보를 지우면 뒤가 하나씩 당겨지므로 **지울 때는 번호 앞 8자만** 받습니다 — 순번이나 짧은 앞부분과 `--yes` 를 주면 아무것도 지우지 않고 지울 명령(`candidates delete 번호 --yes`)을 후보 제목과 함께 알려 줍니다(같은 명령을 되풀이해도 다른 후보가 지워지지 않습니다). 1000번 이상은 순번으로 고를 수 없어 번호로 고릅니다. 시각과 '며칠 전' 은 한국 시간으로 보입니다(저장은 UTC). 번호 전체와 영문 상태 코드는 `--json`·`--verbose` 에서만 보입니다. `list`·`show` 는 보관함을 만들거나 바꾸지 않고, 보관함이 없거나 옛 구조면 '아직 후보가 없습니다' 로 알립니다(쓰는 명령을 처음 실행하면 보관함이 올라갑니다). 앱이 쓰다 꺼져 끝내지 못한 저장이 남았으면 읽기만 하는 명령은 멈추고, `list`(글 목록)나 `candidates add …` 를 한 번 실행하면 정리됩니다.
- CSV 는 UTF-8(BOM 있어도)이나 엑셀의 cp949 파일(5MB·2000줄 이하, '다른 이름으로 저장 → CSV UTF-8' 도 됩니다)이고 **첫 줄에 열 이름**이 있어야 합니다 — `주제`·`핵심 키워드`·`대상 블로그`(없으면 `--blog`)와 선택 열(`보조 키워드`·`글 유형`·`월간 검색 수요`·`관련 블로그 검색 결과 수`·`최근 관심도 변화`·`모바일 비중`·`계절성`·`기존 글 중복 여부`·`블로그 프로필 적합도`·`콘텐츠 작성 우선도`·`키워드 기회도`·`추천 이유`·`데이터 조회일`, 영어 이름도 됩니다). 모르는 열은 무시하고 알려 줍니다. **지표가 하나라도 있는 줄에는 조회일이 필요**하고(열이 없으면 `--data-date`, 오늘보다 하루 뒤까지만 받습니다), 잘못된 줄은 줄 번호와 이유를 보이고 그 줄만 거절하며 나머지는 저장합니다. 마지막 줄의 `N개 추가·M개 건너뜀·K개 거절` 이 결과이고, 거절한 줄이 있으면 종료 코드가 1 입니다(이미 들어간 줄은 다시 가져와도 건너뜁니다). 가져오기는 한꺼번에 저장하므로 같은 파일을 두 곳에서 동시에 가져와도 겹치지 않고, 도중에 멈추면 아무것도 저장되지 않으니 같은 명령을 다시 실행합니다. 폴더나 `CON` 같은 장치 이름은 읽지 않습니다.
- 네이버 프로필에는 글을 만들 때 쓰는 선택 항목이 있습니다 — `naver-profile set naver_a --intro-style … --subheading-min 3 --subheading-max 5 --difficulty … --ending-style … --excluded-topics 주식,코인 --topic-reuse-days 90 --post-type 정보형`(모두 기본값이 있어 비워 둬도 됩니다). 소제목 수가 범위를 벗어나거나 제외 주제가 제목·본문에 있으면 미리 보기와 복사용 글의 `[주의]` 에 경고만 나오고 막지 않으며, 같은 주제 재사용 기준은 후보를 고를 때 씁니다. 도입부 스타일·설명 난이도·마무리 방식·기본 글 유형은 아래 작성 기반(`draft plan`)이 읽습니다.
- **작성 기반**(글을 쓰기 전의 뼈대): 후보를 고르면 제목 후보 3개·권장 목차와 소제목·포함할 핵심 내용·주의사항·태그·확인 권장을 규칙으로 만들어 보여 줍니다(AI·네트워크 없이, **읽기만 하고 아무것도 저장하지 않습니다**). 초안 문장은 아직 만들지 않습니다.

```text
python -m chanceblog_desktop draft plan 3 --blog naver_a                  # 후보 3번의 네이버 A 용 작성 기반(선택 입력은 하나도 필요 없습니다)
python -m chanceblog_desktop draft plan 3 --blog naver_b --verbose        # 네이버 B 용 — 값이 어느 층에서 왔는지도 보입니다
python -m chanceblog_desktop draft plan 3 --blog naver_a --experience "지난달부터 써 왔고 만족합니다" --exclude 광고,가격 --length 2500+ --title-direction 질문형 --url https://example.com/guide --conclusion "필요한 것만 고르세요"
```

- 선택 입력(모두 선택, 틀린 값만 `DRAFT_OPTION_INVALID` 로 알립니다 — 비밀번호·키·토큰처럼 보이는 글(한글에 바로 붙은 키도), 그리고 이름이 token·secret·password 등을 품거나 sid·ticket·code 와 같고 값이 16자 이상인 주소 인자(퍼센트로 쓴 것도 풀어서 봅니다)는 받지 않고 오류에는 입력한 글을 적지 않습니다. 안전을 먼저 해서 `password: required` 같은 ‘이름: 값’ 꼴의 일반 글도 비밀로 보여 받지 않으니 문장으로 바꿔 써 주세요): `--message`(전하고 싶은 내용)·`--experience`(실제 사용 경험)·`--opinion`·`--must-include`(여러 번)·`--exclude`(쉼표나 여러 번)·`--audience`·`--length`(`1500-2000` 또는 `2500+`)·`--title-direction`·`--url`(https 공개 주소, 여러 번 — **열어 보거나 가져오지 않고 글자 그대로 적습니다**)·`--price-date`·`--conclusion`, 글 유형은 `--type`. 적용 순서는 **사용자 입력 → 블로그 프로필 → 글 유형 틀 → 후보 → 공통 기본값**입니다(글 길이를 기본 1,500~2,000자 대신 `--length 2500+` 로 주면 2,500자 이상).
- 후기·방문·체험처럼 경험을 전제한 후보를 **경험 입력 없이** 만들면 경험담을 지어내지 않고 정보형 안내 글(방문 후기→위치·이용 정보와 방문 전 확인사항, 제품 체험 후기는 ‘공개된 제품 정보와 구매 전 확인사항’ 안내 글로, 직접 사용 후기→기능과 선택 기준 정리)로 바꾸고 그 사실을 '확인 권장' 에 적습니다. 경험을 입력하면 목차에 경험 단락이 더해집니다. '지어내지 않기' 검사(`check/claims.py`)는 한국어 낱말 규칙이라 놓치거나 잘못 걸 수 있습니다 — 낱말이 없는 체감 표현('배터리가 오래 갔습니다'), 한자를 섞거나 글자 사이에 숫자·자음을 끼운 문장, 영어('I tried' 같은 1인칭 기본 꼴만 잡습니다), '좋았던 점은 소음이 적다는 것입니다' 처럼 꾸밈꼴로 쓴 경험은 못 잡을 수 있고, 반대로 '써 보니 어떠셨나요?'·'알려 주시겠어요?' 같은 높임 질문이나 따옴표로 가리키기만 하는 말은 일부러 통과시킵니다(예문 목록이 시험으로 고정). 다만 끝에 물음표만 붙이거나 꼬리 질문을 단 서술('편했어요?'·'만족했습니다 아닌가요?')과 높임 없는 구어 질문('써 봤어요?')은 겪은 일을 말하는 것과 같은 모양이라 걸립니다('써 보셨나요?' 로 바꿔 쓰세요). 후보가 네이버 A·B 둘 다를 대상으로 하면 두 블로그용 계획이 서로 너무 비슷한지도 알려 줍니다(제목·소제목·도입 방향·태그가 블로그마다 다르게 만들어집니다).
- 글·설정·백업은 PC 의 사용자 데이터 폴더(Windows: `%LOCALAPPDATA%\ChanceblogDesktop`)에만 두고 저장소 안에는 두지 않습니다(`--data-dir` 로 바꿀 수 있지만 저장소 폴더 안은 거절합니다). `backup`·`restore` 로 백업과 복구를 합니다(`restore` 는 지금 글 저장소를 그 백업의 내용으로 통째로 바꾸므로 `--yes` 가 있어야 합니다 — `restore --latest` 만 쓰면 `CONFIRMATION_REQUIRED` 와 함께 어느 백업인지 알려 주니 맞으면 같은 명령 끝에 `--yes` 를 붙입니다). 키·토큰은 읽지도 보이지도 않고, 화면에 나가는 모든 글은 비밀 모양을 가립니다(영문·숫자에 바로 붙은 `abcAKIA…` 와 밑줄·하이픈 앞의 JWT 는 알아보지 못합니다 — 기준이 되는 가리기 규칙과 같은 한계입니다).
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
