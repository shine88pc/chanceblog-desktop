; ChanceBlogDesktop.iss - ChanceBlog Desktop 설치 파일(Inno Setup)의 스크립트 (V1INSTALL, 결정 D-830 이후).
; 이 파일은 packaging/build_installer.py 가 ISCC(Inno Setup 컴파일러)로 컴파일한다. 앞선 설치 도구 시험(spike)에서 러너가 실제로 컴파일한 스크립트(ChanceBlogSpike.iss)를 바탕으로 줄 모양을 맞췄다.
; 그 스크립트에 없던 새 모양이 셋 있고 러너가 아직 컴파일해 본 적이 없다(앱 검사의 윈도 칸이 처음 컴파일한다): AppId 줄(여는 중괄호를 두 번 겹쳐 쓰는 규칙 - 스파이크는 이 값을 정의 글로 넣었다),
;   [Setup] 끝의 '#ifdef IconFile' 로 싼 SetupIconFile 줄(아이콘이 있을 때만 켜진다), 버전 정의가 없으면 멈추는 '#error AppVersion' 줄(스파이크의 #error 는 SourceDir 용이었고 버전은 기본값을 넣었다).
;   뺀 것: 시험용 [Code](로그용)와 설치 확인 쪽을 건너뛰던 설정(마지막 확인 쪽이 설치 위치를 보여 준다), 정의로 받던 실행 파일·설치 폴더 이름(스크립트에 글자로 적는다). 컴파일러는 /Q 없이 부른다(컴파일 출력에서 판을 읽으려고).
; 값은 ISCC 의 /D 정의로 받는다(build_installer.py 가 넘긴다):
;   AppVersion 버전(필수) / SourceDir 묶음 폴더(필수, 압축 파일의 입력과 같은 폴더) / OutputDir 설치 파일을 둘 폴더 / OutBase 설치 파일 이름(확장자 없이) / IconFile 아이콘 파일(있을 때만)
; 이름과 ID 는 정의로 받지 않고 이 파일에 적는다(제품 이름·실행 파일·설치 폴더 이름은 packaging/pkgcommon.py 의 상수와 같고 시험이 같음을 지킨다).
; 규칙(설계서 INSTALLER 3-3): 관리자 권한 없이(PrivilegesRequired=lowest) 사용자 폴더에 설치하고, 한국어 안내(공식 Korean.isl)를 넣고, 제거할 때 데이터 폴더와 자격 증명은 지우지 않는다.
;   그래서 [UninstallDelete]·[Registry]·[Tasks]·[Code] 구역이 없다. 시작 메뉴 바로가기만 만들고(바탕화면 0), 설치 뒤 앱 실행은 조용히 설치할 때(skipifsilent) 건너뛴다.
;   시작 자동 실행과 예약 작업을 만들지 않는다. 점검 함수(build_installer.iss_problems)가 이 규칙을 컴파일 전에 건다.
; AppId 는 이 갈래가 한 번 만들어 영구 고정한 GUID 다(바꾸면 같은 앱의 새 판이 아니라 별개 앱이 된다). 여는 중괄호는 두 번 쓰는 규칙(Inno 가 글자 하나로 읽는다)이다.
; CloseApplications=yes 와 RestartApplications=yes 의 뜻: 설치 도중 이 앱이 켜져 있으면 Setup 이 윈도 다시 시작 관리자(Restart Manager)에 닫아 달라고 요청하고, 끝난 뒤 다시 켜 달라고 요청한다.
;   조용한 설치에서 앱을 닫게 하려면 Setup 을 /CLOSEAPPLICATIONS 인자로 부른다(업데이트 호출 - 설계에서 가져온 호출이고 러너에서 재 본 적은 없다). 켜진 앱이 닫히지 않으면 새 판은 적용되지 않고 옛 판이 그대로다(측정 M09 - 그 측정은 이 인자 없이 했다).
; 이 파일의 실제 코드 줄은 모두 ASCII 다(한글은 주석뿐) - 한국어 화면은 Korean.isl 이 맡는다.

#ifndef AppVersion
  #error AppVersion must be defined (/DAppVersion=version)
#endif
#ifndef SourceDir
  #error SourceDir must be defined (/DSourceDir=bundle folder)
#endif
#ifndef OutputDir
  #define OutputDir "Output"
#endif
#ifndef OutBase
  #define OutBase "ChanceBlogDesktop-" + AppVersion + "-Setup"
#endif

[Setup]
AppId={{CF5B18A9-6CBC-4916-9978-7729E88B70C8}
AppName=ChanceBlog Desktop
AppVersion={#AppVersion}
AppPublisher=ChanceBlog
DefaultDirName={autopf}\ChanceBlogDesktop
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#OutBase}
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ChanceBlogDesktop.exe
ArchitecturesInstallIn64BitMode=x64compatible
#ifdef IconFile
SetupIconFile={#IconFile}
#endif

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ChanceBlog Desktop"; Filename: "{app}\ChanceBlogDesktop.exe"

[Run]
Filename: "{app}\ChanceBlogDesktop.exe"; Flags: nowait postinstall skipifsilent
