#define MyAppName "AccountPilot Helper"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "AccountPilot"
#define MyAppExeName "AccountPilotHelper.exe"

[Setup]
AppId={{8D0D5961-68B3-4DF4-9D80-ACC0A1107001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AccountPilot Helper
DefaultGroupName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=AccountPilotHelperSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AccountPilotHelper"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--backend-url ""{param:BACKEND_URL|}"" --setup-token ""{param:SETUP_TOKEN|}"" --tally-url ""{param:TALLY_URL|http://127.0.0.1:9000}"" --configure-only"; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Start AccountPilot Helper"; Flags: nowait postinstall skipifsilent
