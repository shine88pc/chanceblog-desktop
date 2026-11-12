# 개인 PC 제한 시험용 Package — 만들기·구성·점검 (개발자용)

**개인 PC 제한 시험용, 미서명 Package — 공개 배포용이 아닙니다**

운영자 2026-11-11 결정 8·9항에 따라 첫 Package 를 **재현 가능하게 만드는 도구**(`packaging/`)와 그 사용법을 적는다. 운영자가 개인 PC 에서 직접 해 보는 순서는 [`PERSONAL_PC_TEST.md`](PERSONAL_PC_TEST.md) 에 있다. 이 문서와 도구는 Package 를 **제안**하는 것이 아니라 시험용 빌드와 시험지를 준비하는 것이다 — 제안은 운영자의 Package Gate 12항목(H1 수정·H2 제거·H3 외부 Write 완전 비활성·M3 Secret 저장 방지·표준 사용자 실행·다른 일반 계정 데이터 접근 차단·Backup Secret 0·Log Secret 0·Credential 사용자 범위 확인·SHA-256 제공·외부 게시 0 증명·전체 시험과 독립 검증)를 모두 통과한 뒤에만 한다. 결정 기록은 D-400 이후다.

## 1. 무엇이고 무엇이 아닌가

- **한 폴더(`--onedir`) 휴대용 묶음**이다: 압축을 풀어 `ChanceBlogDesktop.exe` 를 열면 된다. 설치 프로그램·시작 메뉴 항목·레지스트리 기록·자동 업데이트·서비스 등록이 **없다**. 지우려면 폴더(와 데이터 폴더·자격 증명 항목)만 지우면 된다(§9).
- **화면(GUI) 전용**이다. 시작 파일 `packaging/gui_entry.py` 는 명령줄 부명령(`publish-pages`·`doctor`·`keys` …)과 `--yes` 계열 옵션을 열지 않는다. 인자가 오면 값을 되풀이하지 않는 고정 문장으로 거절하고 종료 코드 2 로 끝낸다. 개발자용 명령줄은 **소스 실행**(`python -m chanceblog_desktop …`)에서만 쓴다.
- **서명이 없다**(코드 서명 인증서를 사지 않았다 — D-05). 그래서 Windows SmartScreen 의 파란 경고가 처음 한 번 뜰 수 있고, 스마트 앱 컨트롤이 켜져 있는 PC 에서는 막힐 수 있다(§10).
- 키·토큰·사용자 데이터를 **담지 않는다**. 키는 Windows 자격 증명 관리자에만 저장되고 데이터는 사용자별 `%LOCALAPPDATA%\ChanceblogDesktop` 에만 생긴다(폴더 이름은 운영자 결정으로 유지 — 소문자 b).
- 앱 코드(`src/`)는 거의 고치지 않고 묶는다. 이 묶음이 앱에 더한 것은 '정보' 카드의 커밋 앞 7자리와 미서명 표시 한 줄뿐이다 — `ui/core/version.py` 가 묶음 안 정보 파일을 읽고, 카드를 만드는 `ui/core/settings_view.py`·`ui/qt/screens.py` 에 작은 변경이 이어진다(세 파일, D-401).

## 2. 만드는 방법

조건: Windows 10/11 64비트(다른 운영체제에서는 빌드가 처음에 거절한다), Python 3.12(64비트), **깨끗한 작업 트리**(커밋되지 않은 변경·새 파일이 없어야 하고, 빌드 입력 폴더 `src`·`vendor`·`packaging` 안에 git 이 무시하는 파일도 없어야 한다 — 있으면 빌드가 거절한다. 바이트코드 캐시는 괜찮다. git 설정(`status.showUntrackedFiles`)이나 `skip-worktree`·`assume-unchanged` 표시로 `git status` 에 안 보이게 가려진 변경도 거절한다 — 입력 폴더의 실제 파일 목록을 `git ls-files` 와 대조한다, D-441), 잠금 파일의 도구가 정확한 버전으로 설치된 환경. **가상환경은 저장소 밖에 만든다** — 저장소 안에 만들면(`.venv-package` 처럼 git 이 무시하지 않는 이름) 깨끗한 작업 트리 검사에 걸려 거절된다. 아래 `..` 는 저장소 폴더의 부모이고 명령은 저장소 맨 위 폴더에서 친다(D-417).

```text
python -m venv ..\chanceblog-package-venv
..\chanceblog-package-venv\Scripts\python -m pip install -r packaging/requirements-package.txt
..\chanceblog-package-venv\Scripts\python packaging/build_package.py
```

| 옵션 | 뜻 |
|---|---|
| `--out-dir 폴더` | 출력 폴더(기본: 저장소의 `dist/package` — git 이 무시하는 곳). 저장소 자신·저장소를 품은 폴더·드라이브 맨 위(다른 드라이브 포함)·빌드 입력 폴더(`src`·`vendor`·`packaging`)와 `.git` 안·git 이 무시하지 않는 저장소 안 폴더는 거절한다. 경로의 이름이 공백이나 점으로 끝나거나(윈도가 그 글자를 지워 다른 폴더가 된다)·쓸 수 없는 글자(꺾쇠·따옴표·세로줄·물음표·별표·콜론·제어 문자)가 있거나·예약 이름(`CON`·`NUL`·`COM1` 등)이거나·경로 전체가 130자를 넘으면 거절 문장으로 알린다(D-440). 이미 있는 폴더가 비어 있지 않은데 이 도구의 표지 파일(`.chanceblog-package-out`)이 없으면 아무것도 지우지 않고 거절한다(이미 있는 파일 경로도 거절 — 옛 도구가 만든 폴더는 표지가 없으니 새 폴더를 쓴다). 지우는 곳은 표지가 있는 폴더 안의 `work`·`spec`·`dist`·`bundle`·`release` 뿐이다 |
| `--skip-scan` | Windows Defender 읽기 전용 검사를 건너뛴다(정보 파일에 '검사 안 함'으로 적힌다) |
| `--allow-missing-gate` | 외부 쓰기 관문(`chanceblog_desktop.capabilities`) 모듈이 **아직 없는** 소스로 **시험 빌드**를 만든다 — **압축 파일·묶음 폴더 이름에 `TESTBUILD` 가 붙고**(`ChanceBlogDesktop-0.1.0-preview.1-TESTBUILD-win64.zip`) 정보 파일(안·밖) 맨 위 배너·Build 방법·자가 점검 줄·윈도 버전 정보·화면 '정보' 카드에도 시험 빌드라고 적히며 `release_eligible` 이 거짓이다(D-416). 넘기는 것은 '모듈이 **없음**' 하나뿐이다 — 모듈은 있는데 열려 있거나(`True`) 안에서 가져오기가 실패하는 경우는 이 옵션으로도 넘기지 않는다(D-419). 모듈 소스가 있는 소스에 이 옵션을 붙이면 아무 효과가 없고 정식 빌드가 된다 |

순서(스크립트가 한 줄씩 알린다): ① 작업 트리·잠금 파일·VERSION 확인 → ② PyInstaller(`--onedir --windowed`, `--python-option "X utf8"`, 앱이 쓰지 않는 `--exclude-module PySide6.QtNetwork`, GUI 전용 시작 파일, 윈도 버전 정보 파일) → ③ 실행 파일 **옆**에 `vendor/`·`VERSION`·`LICENSES/` 배치 → 묶음 점검(PyInstaller 가 남긴 묶음 목록의 모든 DLL·확장 모듈이 이 가상환경·기본 Python·Windows 폴더에서 왔는지, 앱이 쓰지 않는 네트워크 부품 — QtNetwork 모듈·TLS 플러그인·`-x64` OpenSSL — 이 없는지, 비밀 모양 이름·글과 앱이 정의한 사용자 데이터 파일 이름(보관함·설정·백업 표지와 그 `.bak`·`.tmp` 사본 — D-446)이 없는지; 어긋나면 거절 — D-415) → ④ 묶음 안 `PACKAGE_INFO.*` → ⑤ 묶음 실행 파일의 `--selftest`(**실패하면 압축 파일과 정보 파일을 만들지 않는다**) → ⑥ 결정적 zip → ⑦ 압축 파일 옆 `PACKAGE_INFO.*`·`SHA256SUMS`(+ 읽기 전용 악성코드 검사) → ⑧ 요약.

산출물(출력 폴더의 `release`): 압축 파일 `ChanceBlogDesktop-0.1.0-preview.1-win64.zip`(시험 빌드는 `ChanceBlogDesktop-0.1.0-preview.1-TESTBUILD-win64.zip`), `SHA256SUMS`, `PACKAGE_INFO.md`, `PACKAGE_INFO.json`. **이 넷만** 밖으로 내보낸다(빌드 로그 `build.log`·`work`·`spec` 에는 이 PC 의 경로가 들어 있어 내보내지 않는다).

경로 가정을 코드로 고치지 않았다: 앱은 `vendor/`(`core.py`)와 `VERSION`(`ui/core/version.py`)을 **실행 파일 옆**에서 찾는다(PyInstaller 6 의 `_internal` 안 모듈 위치에서 계산). 빌드가 정확히 그 자리에 놓고, `--selftest` 가 '앱이 찾는 자리와 실제 자리가 같은가'를 확인한다. 없으면 `No module named pipeline` 으로 시작하지 못한다(조사에서 확인).

## 3. 산출물 구성

압축을 풀면 폴더 하나(`ChanceBlogDesktop-0.1.0-preview.1`)가 생긴다. 데이터 폴더 `ChanceblogDesktop` 과 이름이 달라 같은 곳에 풀어도 겹치지 않는다.

| 위치 | 내용 |
|---|---|
| `ChanceBlogDesktop.exe` | 시작 파일과 앱 코드(컴파일된 `chanceblog_desktop`·`gui_entry`·`pkgcommon` 이 이 파일 안에 있다 — 창 없음, 더블클릭용, 일반 사용자 권한 `asInvoker`, 서명 없음) |
| `_internal/` | PyInstaller 가 모은 Python 런타임(`python312.dll`·표준 모듈 `.pyd`)·PySide6(Qt DLL·플러그인: `platforms/qwindows.dll`·`imageformats/qjpeg·qwebp·qsvg`) — 전부 별개 파일이다 |
| `vendor/` | chanceblog 에서 한 글자도 바꾸지 않고 가져온 파일(`VENDOR.json` 해시와 같다) |
| `VERSION` | 버전 번호 한 줄(줄 끝 LF) |
| `LICENSES/` | `LGPL-3.0.txt`·`GPL-3.0.txt`·`PYTHON-LICENSE.txt`·`PYINSTALLER-COPYING.txt`·`THIRD_PARTY_NOTICES.md` |
| `PACKAGE_INFO.md`·`PACKAGE_INFO.json` | 묶음 안 사본(§4) |

## 4. 정보 파일 — 운영자가 요구한 여덟 가지

`packaging/make_manifest.py` 가 만든다. **두 갈래**다 — 같은 입력이면 같은 바이트의 압축 파일이 나오게 하려고 묶음 안 사본에는 시계·압축 파일 해시·검사 결과를 넣지 않는다.

| 갈래 | 어디에 | 더 들어 있는 것 |
|---|---|---|
| inner | 묶음 폴더 안 | 아래 여덟 가지 중 시계가 없는 것 + 묶음 안 모든 파일의 SHA-256 목록(`files`). 화면 '정보' 카드와 `--selftest` 가 읽는다 |
| outer | 압축 파일 옆 | inner + 압축 파일의 SHA-256·크기, Defender 읽기 전용 검사 결과(또는 '검사 안 함 — 이유'), 만든 시각, 자가 점검 결과, `release_eligible` |

여덟 가지: ① **Version**(`VERSION` 과 같은 `0.1.0-preview.1`) ② **Git Commit**(전체 해시·트리 해시·작업 트리가 깨끗한지·커밋 시각) ③ **SHA-256**(압축 파일과 묶음 안 모든 파일) ④ **Dependency 목록**(`pip freeze` 모양의 정확한 버전·역할·라이선스 표기·설치 내용 지문) ⑤ **Build 방법**(재현 명령 그대로·환경 변수) ⑥ **Malware 검사 결과** ⑦ **서명 여부**(실행 파일의 Authenticode 보안 디렉터리를 읽어 '미서명'을 사실로 확인) ⑧ **SmartScreen 예상 동작**. 맨 위에 굵게 '개인 PC 제한 시험용, 미서명 Package — 공개 배포용이 아닙니다' 가 있다. `SHA256SUMS` 는 `sha256sum -c` 로 확인할 수 있는 한 줄(`<해시>  <압축 파일 이름>`)이다. **시험 빌드**(`--allow-missing-gate`)면 두 사본 모두 `trial` 이 참이고 맨 위 배너가 '이 빌드는 시험 빌드(TESTBUILD)입니다' 로 시작하며 Build 방법에 `--allow-missing-gate` 명령 한 줄이 적히고, 밖 사본의 자가 점검 줄은 '허용된 관문 실패 1' 을 숫자에서 빼지 않고 따로 적는다(D-416).

**악성코드 검사**: 이 PC 의 Windows Defender 가 쓸 수 있으면 `MpCmdRun.exe -Scan -ScanType 3 -File <대상> -DisableRemediation`(읽기 전용 — 치료·격리·삭제를 끈다)로 압축 파일과 묶음 폴더를 검사하고 종료 코드·엔진·서명 정의 버전·시각을 적는다. 서비스가 꺼져 있거나 도구가 없으면 `검사 안 함 — 이유` 로 정직하게 적는다. 시스템·보안 설정은 바꾸지 않는다. 운영자 개인 PC 의 직접 검사는 시험지 0단계다.

**화면 '정보' 카드**: 묶음 안 `PACKAGE_INFO.json` 이 있고 `version` 이 `VERSION` 과 같고 `channel` 이 `personal-pc-preview`·`signing.signed` 가 `false` 이면 `버전 v0.1.0-preview.1 · 커밋 abc1234` 와 `개인 PC 제한 시험용, 미서명 Package` 한 줄이 보인다. 파일 안의 글을 그대로 보이지 않는다(커밋은 40자리 16진수일 때만 앞 7자리, 안내 문장은 코드의 고정 문장). 파일이 없거나 틀리면 아무것도 더하지 않는다(개발 화면은 그대로).

## 5. 결정적(재현 가능한) 빌드

같은 커밋·같은 잠금 파일의 도구·같은 Python 이고 **묶음에 들어가는 DLL 이 같은 곳(이 가상환경·기본 Python·Windows 폴더)에서 오면** 같은 압축 파일이 나오게 최선을 다했다. 독립 검증이 찾은 틈: 빌드 PC 의 PATH 에 따라 묶음이 달라졌다 — PyInstaller 의 Qt 훅이 앱이 쓰지 않는 QtNetwork 용 OpenSSL `-x64` DLL 을 PATH 에서 처음 찾은 폴더(이 PC 에서는 Git for Windows 나 사내 프로그램 폴더)에서 가져와 묶음에 넣었다. 그래서 ① 앱이 쓰지 않는 `PySide6.QtNetwork` 를 PyInstaller 에서 빼고 ② 묶음 목록의 모든 DLL·확장 모듈의 출처가 허용된 뿌리인지 빌드가 확인해 어긋나면 거절하며 ③ 앱이 쓰지 않는 네트워크 부품이 묶음에 있으면 거절한다(D-415 — PATH 가 다른 두 셸에서 빌드한 압축 파일 비교 측정값도 거기에 있다). 쓴 방법: 환경 변수 `PYTHONHASHSEED=0`·`SOURCE_DATE_EPOCH=<커밋 시각>`·`PYTHONUTF8=1`·`PYTHONDONTWRITEBYTECODE=1`(PyInstaller 를 부를 때), PyInstaller `--clean`, zip 은 항목을 경로 순으로 쓰고 모든 항목의 시각을 커밋 시각(UTC, 2초 단위)으로·속성과 압축 수준(9)을 고정, 묶음 안 정보 파일에 시계를 넣지 않음, `vendor/`·라이선스 전문은 바이트 그대로 복사(`.gitattributes` 의 `-text`). 같은 입력으로 두 번 만들어 비교한 결과와 남은 차이는 결정 기록과 작업 보고서에 있다. **한계**: 다른 PC 에서 같은 해시가 나오는지는 시험하지 못했다(Windows 시스템 폴더의 DLL 버전·zlib·Python 패치 버전이 다르면 달라질 수 있다 — 출처 확인은 '어느 폴더에서 왔는가' 만 본다). 정보 파일에 zlib 버전·Python 버전·도구 버전을 적어 차이를 설명할 수 있게 했다.

의존성 잠금 `packaging/requirements-package.txt` 는 정확한 버전(`==`)만 쓴다. 설치된 버전이 다르면 빌드가 거절한다. **배포 파일(wheel)의 `--hash` 는 담지 못했다**(이 파일을 만든 PC 에서 네트워크를 쓰지 않았다) — 네트워크가 있는 곳에서 `python -m pip hash` 나 `pip-compile --generate-hashes` 로 해시를 더하면 `--require-hashes` 로 설치할 수 있다. 대신 설치된 배포본의 `RECORD`(파일 경로·해시 목록)를 요약한 **설치 내용 지문**을 `PACKAGE_INFO.json` 에 적는다.

## 6. 자가 점검 `--selftest`

숨은 옵션이다(정확히 `ChanceBlogDesktop.exe --selftest` 한 단어일 때만 — 다른 인자는 모두 거절). 창 없는 실행 파일이라 콘솔에서 열면 그 콘솔에 쓰고, 더블클릭이면 메시지 상자로 보인다. 파일로 받으려면 `ChanceBlogDesktop.exe --selftest > 결과.txt`. 종료 코드 0 이 정상이다. **데이터 폴더를 만들지 않으려고** 점검 안에서만 `LOCALAPPDATA` 를 임시 폴더로 바꾸고 `.pyc` 를 쓰지 않으며, 끝에 그 폴더가 비어 있는지 확인한다. 묶음(frozen)에서는 건너뜀도 실패로 센다.

| 이름 | 확인하는 것 |
|---|---|
| `utf8_mode` | 파이썬 UTF-8 모드(빌드 옵션 `X utf8`) — 묶음 실행 파일은 `PYTHONUTF8` 환경 변수를 무시하므로 옵션으로 켠다(cp949 인코딩 오류 방지) |
| `version_file` | `VERSION` 이 앱이 찾는 자리(실행 파일 옆)에 있고 번호 모양이며 정보 파일의 버전과 같다 |
| `package_info` | `PACKAGE_INFO.json`·`.md` 가 있고 채널·미서명·`trial`(참·거짓)·커밋 40자리·깨끗함·문구·파일 목록이 맞다 |
| `file_hashes` | 정보 파일의 파일별 SHA-256 목록과 실제 파일이 모두 같다(압축 해제 실패·백신 격리로 빠진 파일을 찾는다) |
| `licenses` | `LICENSES/` 의 다섯 파일이 있고 LGPL·GPL 전문과 고지문의 핵심 문장이 있다 |
| `vendor_core` | 앱이 찾는 `vendor/` 자리가 실제 자리와 같고 `VENDOR.json` 해시가 같고 모듈이 불러와지며 그 파일들이 쓰는 표준 모듈이 묶음에 있다 |
| `capabilities` | 외부 쓰기 관문 `EXTERNAL_WRITE`·`BLOGGER_OAUTH_INPUT` 이 둘 다 `False`(모듈이 없어도 실패 — '모듈이 없음'과 '모듈은 있는데 안에서 가져오기 실패'는 다른 글로 알리고 `--allow-missing-gate` 는 앞의 것만 넘긴다) |
| `uac_manifest` | 실행 파일 매니페스트가 `asInvoker`(관리자 권한 요구 0) |
| `qt_plugins` | `platforms/qwindows.dll`·`imageformats/qjpeg·qwebp·qsvg` 가 있고 `QImageReader` 가 jpeg·png·webp·svg 를 읽는다 |
| `qt_screens` | 창 없이(offscreen) 화면 여섯(홈·후보·초안·Seed·블로그·설정)이 열리고 처리 못 한 예외가 없다 |
| `gui_only_entry` | 인자 일곱 가지를 모두 거절하고(고정 문장만 — 입력값 되풀이 0) 명령줄 모듈을 불러오지 않았다 |
| `data_dir_untouched` | 점검이 데이터 폴더에 아무것도 만들지 않았다 |

소스 실행(`python packaging/gui_entry.py --selftest`)에서는 묶음에만 있는 것(정보 파일·파일 해시 목록·라이선스·UAC 매니페스트, PySide6 가 없으면 Qt 두 점검도)을 '건너뜀'으로 센다.

## 7. 외부 쓰기 경계

이 Package 는 외부로 쓰는 길이 없어야 한다(운영자 결정 5항). 이 묶음이 하는 일은 **빌드·시작 쪽의 경계**다: 시작 파일이 명령줄을 열지 않고, `--selftest` 가 `capabilities` 상수를 확인하며, 빌드가 관문 없는 소스를 거절한다(`--allow-missing-gate` 는 시험 빌드 표시를 남긴다). 앱 안의 외부 쓰기 차단(외부 쓰기 서비스 비활성·어댑터 미등록·실행 시점 관문·Network Write 0 시험)은 보안 수정 묶음의 몫이다. 묶음 안에는 네트워크를 쓸 수 있는 표준 모듈(`ssl`·`socket`·`urllib` 등)과 `publish/` 코드가 **들어 있을 수 있다**(앱의 서비스 층이 가져오므로) — 화면은 그 길을 부르지 않는다는 것이 보안 묶음의 시험이 지키는 사실이다. 빌드의 관문 점검(`--selftest` 의 `capabilities`)은 상수 두 개(`EXTERNAL_WRITE`·`BLOGGER_OAUTH_INPUT`)가 `False` 로 적혀 있는지만 읽는다 — 환경 변수로 값을 정하는 코드나 `require_external_write` 함수가 없는 경우를 이 점검이 잡는다고 보지 않는다(실제 차단은 보안 수정 묶음의 시험 몫, D-443).

## 8. 제3자 고지 (법률 판단이 아니다)

묶음 안 `LICENSES/THIRD_PARTY_NOTICES.md` 에 구성 요소 표가 있고, 전문은 같은 폴더에 있다.

- **PySide6(Qt for Python)·Shiboken6·Qt 6 는 LGPL 이다.** 패키지의 라이선스 표기는 `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` 이고 이 묶음은 **LGPL-3.0 조건**으로 쓴다. 지키는 것: 라이선스 전문(`LGPL-3.0.txt`, LGPL-3.0 이 GPL-3.0 의 조건을 포함하므로 `GPL-3.0.txt` 도) 동봉 · **동적 링크**(Qt DLL·PySide6 모듈이 `_internal/PySide6` 안에 별개 파일로 있어 같은 버전의 파일로 바꿔 끼울 수 있다 — 한 파일로 합치지 않았다) · 소스를 얻는 방법 안내(Qt 프로젝트·PySide 프로젝트) · 이 앱이 Qt·PySide6 를 고치지 않았다는 사실.
- **OpenSSL**: Python 이 싣는 `libssl-3.dll`·`libcrypto-3.dll`(Apache-2.0)뿐이다. Qt 네트워크 파이썬 모듈(QtNetwork)·TLS 플러그인과 그 `-x64` OpenSSL 은 묶음에서 뺐다(앱이 쓰지 않는다 — 독립 검증 전에는 빌드 PC 의 PATH 에 있던 다른 프로그램의 DLL 이 들어 있었다, D-415).
- **Python 런타임**(PSF License)·**PyInstaller 부트로더**(GPL-2.0 와 '비공개 프로그램도 만들 수 있게 하는' 예외)의 라이선스 전문도 동봉한다.
- 전문의 출처: 이 PC 에 설치된 Git for Windows 의 라이선스 폴더에 있던 FSF 원문을 한 글자도 바꾸지 않고 복사했다(`packaging/LICENSES/SOURCES.txt` 에 크기·SHA-256). 공식 배포처의 원문과 대조는 하지 못했다.
- **알려진 한계**: Qt 안의 제3자 구성 요소(libpng·FreeType·HarfBuzz 등)와 Python 이 싣는 DLL(OpenSSL 등)의 개별 고지는 각 프로젝트 문서를 따르며 이 묶음이 모두 담았다고 보장하지 않는다. 앱 자체의 라이선스는 아직 정해지지 않았다(D-13) — 그래서 개인 시험용이며 공개 배포하지 않는다.

## 9. 지우는 방법

설치 프로그램이 아니므로 아래 셋이 전부다(시험지 8단계와 같다): ① 압축을 푼 폴더 지우기 ② `%LOCALAPPDATA%\ChanceblogDesktop`(데이터·백업) 지우기 — 계정마다 따로 ③ Windows 자격 증명 관리자의 `ChanceBlogDesktop:` 로 시작하는 항목 지우기(앱의 키 `삭제` 단추로 이미 지웠다면 없다).

## 10. 한계와 다음 일

- **서명이 없다.** SmartScreen 평판은 서명해도 수 주가 걸리며, 스마트 앱 컨트롤은 서명 없는 프로그램을 막을 수 있다. 서명 서비스(SignPath 등)는 D-13(라이선스 결정)을 기다린다. 이 묶음을 만든 PC 와 운영자 PC 의 스마트 앱 컨트롤 상태는 확인하지 못했다.
- **아이콘이 없다**(PyInstaller 기본 아이콘). 윈도 버전 정보(속성 → 자세히)에는 제품 이름·버전·'개인 PC 제한 시험용, 미서명 Package' 가 들어 있다.
- **묶음 점검의 한계**: DLL 출처 검사는 PyInstaller 가 적은 출처 글을 `..`·슬래시·대소문자를 풀어 견줄 뿐(D-443) 바로가기·정션을 따라가 실제 위치를 확인하지 않고, 금지 이름 점검은 정확한 이름(OpenSSL `-x64` 쌍은 이름 꼴)만 봐서 낯선 이름은 걸러 내지 못한다 — 넓은 그물은 출처 검사 몫이다. 깨끗함 검사(D-441)도 파일의 크기·수정 시각을 같게 맞춰 git 의 상태 캐시를 속이는 수정은 보지 않는다.
- 업데이트·롤백·마이그레이션 코드가 없다(새 버전은 새로 풀어서 쓴다 — 데이터 폴더는 같고, 백업·복원 화면이 있는 Package 에서는 그 기능으로 옮긴다).
- **빌드 워크플로**(`.github/workflows/package.yml`)는 T3 라 이 가지에 없다. 별도 가지에 초안만 있고 운영자 승인 뒤에 병합한다: 수동 실행만(`workflow_dispatch`)·`windows-latest`·Python 3.12·잠금 파일로 설치·위 스크립트 실행·**압축 파일·`SHA256SUMS`·`PACKAGE_INFO.*` 만** 14일 보존으로 올림·비밀 값 0·서명 단계 없음. 병합되면 이 문서의 §2 명령이 그 워크플로의 본문이 된다.
- PySide6·PyInstaller 는 CI(Linux·Windows 시험 칸)에 없으므로(D-32) 이 도구의 시험은 PyInstaller 없이 도는 부분(`tests/test_packaging_*.py`)이고, 실제 빌드는 개발 PC 에서 돌려 결과를 보고서에 남긴다.
