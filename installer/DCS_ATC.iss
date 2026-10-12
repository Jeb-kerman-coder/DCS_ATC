; Inno Setup script - compiled by build_installer.bat (needs Inno Setup 6)

#define AppName "DCS ATC"
#ifndef AppVersion
#define AppVersion "1.0.0"
#endif
#define AppExe "DCS ATC.exe"

[Setup]
AppId={{6F0B8E52-3C1D-4D8A-9B71-DC5A7C0A0A71}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=DCS ATC
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\assets\icon.ico
OutputDir=..\installer_output
OutputBaseFilename=DCS_ATC_Setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
InfoAfterFile=INSTALL_NOTES.txt
CloseApplications=yes

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "--restore-missionscripting"; Flags: runhidden waituntilterminated; RunOnceId: "RestoreMissionScripting"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\DCS ATC\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\en_US-ryan-high.onnx"; DestDir: "{app}\voices"; Flags: ignoreversion
Source: "..\en_US-ryan-high.onnx.json"; DestDir: "{app}\voices"; Flags: ignoreversion
Source: "..\dcs_lua\*.lua"; DestDir: "{app}\dcs_lua"; Flags: ignoreversion
Source: "..\docs\NOTES.md"; DestDir: "{app}"; DestName: "README.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Settings and logs folder"; Filename: "{userappdata}\{#AppName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "--patch-missionscripting"; Flags: runhidden waituntilterminated; StatusMsg: "Enabling sockets for DCS mission scripts..."
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
