; -- cvat_installer.iss --
; Inno Setup Script for CVAT Dense Segmentation Studio
; Packs the standalone application executable and portable zip into a Windows installer.
; Default installation destination: D:\CVAT_Application

#define MyAppName "CVAT Dense Segmentation Studio"
#define MyAppVersion "2.76.1"
#define MyAppPublisher "CVAT.ai"
#define MyAppURL "https://github.com/cvat-ai/cvat"
#define MyAppExeName "CVAT_App.exe"
#define MyZipName "CVAT_App_Portable.zip"

[Setup]
; Unique application GUID
AppId={{D8A13B45-F7E2-4C2E-8E99-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Default installation directory in D: drive as requested
DefaultDirName=D:\CVAT_Application
DisableDirPage=no
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; Installer output configuration
OutputDir=installer_output
OutputBaseFilename=CVAT_Studio_Setup_v1
; SetupIconFile=cvat-ui\dist\favicon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; Privileges
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Primary application executable built by PyInstaller
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Bundled portable zip package
Source: "dist\{#MyZipName}"; DestDir: "{app}"; Flags: ignoreversion

; Configuration and documentation
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion; DestName: "README.txt"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Automatically extract the zip package into the same application folder on D drive during setup
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Expand-Archive -Path '{app}\{#MyZipName}' -DestinationPath '{app}' -Force"""; Flags: runhidden waituntilterminated; StatusMsg: "Extracting package components to D drive..."

; Optional checkbox to launch application immediately after installation
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
