; ChanceBlogSpike.iss - 설치 도구 시험(spike) 갈래 C(Inno Setup)의 스크립트(결정 D-705).
; 작은 앱 묶음과 실제 묶음을 같은 줄로 컴파일한다 - 아래 값은 모두 ISCC 의 /D 정의로 받는다(run_spike.py 의 pack 단계가 만든다).
;   AppVersion 버전 / SourceDir 묶음 폴더 / AppExe 실행 파일 이름 / AppDirName 설치 폴더 이름 / OutputDir 설치 파일을 둘 폴더 / OutBase 설치 파일 이름(확장자 없이) / AppIdText 앱 식별 글
; 규칙(설계서 3-3): 관리자 권한 없이(PrivilegesRequired=lowest) 사용자 폴더에 설치하고, 한국어 안내(공식 Korean.isl)를 넣고, 제거할 때 데이터 폴더와 자격 증명은 지우지 않는다(UninstallDelete 항목 0).
; 시작 메뉴 바로가기만 만들고(바탕화면 0), 설치 뒤 앱 실행은 조용히 설치할 때(skipifsilent) 건너뛴다. 시작 자동 실행과 예약 작업을 만들지 않는다.
; AppId 는 중괄호 없는 고정 글이다(시험용 - 실제 설치 파일의 GUID 는 확인 C 뒤에 정한다).
; 이 파일의 실제 코드 줄은 모두 ASCII 다(한글은 주석뿐) - 한국어 확인은 Korean.isl 의 안내 글을 로그에 적어서 본다(SetupMessage).

#ifndef AppVersion
  #define AppVersion "0.0.1"
#endif
#ifndef SourceDir
  #error SourceDir must be defined (/DSourceDir=bundle folder)
#endif
#ifndef AppExe
  #define AppExe "SpikeApp.exe"
#endif
#ifndef AppDirName
  #define AppDirName "ChanceBlogSpikeC"
#endif
#ifndef OutputDir
  #define OutputDir "Output"
#endif
#ifndef OutBase
  #define OutBase "ChanceBlogSpike-" + AppVersion + "-Setup"
#endif
#ifndef AppIdText
  #define AppIdText "ChanceBlogSpikeInnoV1"
#endif

[Setup]
AppId={#AppIdText}
AppName=ChanceBlog Spike
AppVersion={#AppVersion}
AppPublisher=ChanceBlog
DefaultDirName={autopf}\{#AppDirName}
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#OutBase}
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ChanceBlog Spike C"; Filename: "{app}\{#AppExe}"

[Run]
Filename: "{app}\{#AppExe}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Log('SPIKE_LANG=' + ActiveLanguage);
  Log('SPIKE_NEXT=' + SetupMessage(msgButtonNext));
  Result := True;
end;

procedure InitializeWizard();
begin
  Log('SPIKE_WIZARD_LANG=' + ActiveLanguage);
end;
