#define AppVersion "1.0.1"
#define AppExe "TikTok Streak.exe"
#define AppModelId "Lwents.TikTokStreak"

[Setup]
AppId={{30C066DC-3175-4F2C-BCAD-0F0C1362988A}
AppName=TikTok Streak
AppVersion={#AppVersion}
AppPublisher=Lwent
DefaultDirName={localappdata}\Programs\TikTok Streak
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\..\assets\streak.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\..\release
OutputBaseFilename=TikTok-Streak-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Files]
Source: "..\..\dist\TikTok Streak\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\build\MicrosoftEdgeWebView2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{userprograms}\TikTok Streak"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppModelId}"
Name: "{userdesktop}\TikTok Streak"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppModelId}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open TikTok Streak"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2Key = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Bootstrapper = 'MicrosoftEdgeWebView2Setup.exe';

function HasRuntimeIn(RootKey: Integer): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, WebView2Key, 'pv', Version) and
    (Version <> '') and (Version <> '0.0.0.0');
end;

function HasWebView2: Boolean;
begin
  Result := HasRuntimeIn(HKLM32) or HasRuntimeIn(HKCU32) or HasRuntimeIn(HKCU64);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if HasWebView2 then
    Exit;
  ExtractTemporaryFile(Bootstrapper);
  WizardForm.PreparingLabel.Caption := 'Installing Microsoft Edge WebView2 Runtime...';
  if not Exec(ExpandConstant('{tmp}\') + Bootstrapper, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or
    not HasWebView2 then
    Result := 'Microsoft Edge WebView2 could not be installed. Connect to the internet and try again.';
end;
