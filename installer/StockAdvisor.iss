; Inno Setup script for Stock Advisor (one-folder PyInstaller build).
; Version is passed in by build_installer.ps1:  ISCC.exe /DAppVersion=0.1.0 ...
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Stock Advisor"
#define AppExe "StockAdvisor.exe"
#define AppPublisher "Stock Advisor"

[Setup]
AppId={{B2D9F0C2-7A1E-4E8B-9C3A-STOCKADVISOR01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\StockAdvisor
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=StockAdvisor-Setup-{#AppVersion}
SetupIconFile=StockAdvisor.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-user install -> no admin prompt, simplest for a non-technical tester.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The entire PyInstaller one-folder output. Source is resolved relative to this .iss,
; which lives in installer/, so dist is one level up.
Source: "..\dist\StockAdvisor\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Description: "Launch Stock Advisor"; Filename: "{app}\{#AppExe}"; Flags: nowait postinstall skipifsilent
