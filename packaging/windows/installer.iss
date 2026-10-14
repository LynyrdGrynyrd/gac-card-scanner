; Inno Setup script: builds GAC-Card-Scanner-Setup-<version>.exe from the PyInstaller onedir output.
; iscc /DMyAppVersion=0.2.0 packaging\windows\installer.iss
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "GAC Card Scanner"
#define MyAppExe "GAC Card Scanner.exe"

[Setup]
AppId={{6C7B1E0A-2F51-4C1B-9B7E-6A1C0D5E9A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=GAC Card Scanner contributors
AppPublisherURL=https://github.com/LynyrdGrynyrd/gac-card-scanner
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=GAC-Card-Scanner-Setup-{#MyAppVersion}
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2 runtime..."; Flags: waituntilterminated; Check: NeedsWebView2
Filename: "{app}\{#MyAppExe}"; Description: "Start {#MyAppName} now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM ""{#MyAppExe}"" /T & taskkill /F /IM llama-server.exe /T"; Flags: runhidden; RunOnceId: "StopApp"
; Card data in %LOCALAPPDATA%\GAC Card Scanner is intentionally kept on uninstall (delete that folder to remove it).

[Code]
const WV2 = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
function HasPv(Root: Integer; Key: String): Boolean;
var V: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', V) and (V <> '') and (V <> '0.0.0.0');
end;
function NeedsWebView2: Boolean;
begin
  Result := not (HasPv(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WV2) or
                 HasPv(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WV2) or
                 HasPv(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + WV2));
end;
