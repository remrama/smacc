; Inno Setup script for the SMACC installer (#116).
;
; Compiled by the release workflow after PyInstaller has produced dist\SMACC.exe:
;
;   ISCC /DAppVersion=<version> tools\smacc.iss
;
; Installs per-user by default (no admin rights, no UAC prompt), matching the
; per-user HKCU file association in src/smacc/winassoc.py. IT departments that
; block per-user installs (e.g. AppLocker on %LOCALAPPDATA%) can run the same
; installer machine-wide with /ALLUSERS, which elevates and installs to Program
; Files instead.

#ifndef AppVersion
  #error Pass the app version on the command line: ISCC /DAppVersion=x.y.z tools\smacc.iss
#endif

[Setup]
; Fixed AppId so a newer installer upgrades the existing install in place.
AppId={{3F14E584-7D0C-457A-8041-B8982ADEC19D}
AppName=SMACC
AppVersion={#AppVersion}
AppPublisher=Remington Mallett
AppPublisherURL=https://github.com/remrama/smacc
AppSupportURL=https://github.com/remrama/smacc/issues
; Per-user by default: with PrivilegesRequired=lowest, {autopf} resolves to
; {localappdata}\Programs and nothing needs elevation. The commandline override
; allows /ALLUSERS for an IT-managed machine-wide install (Program Files + HKLM).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
DefaultDirName={autopf}\SMACC
DisableProgramGroupPage=yes
; SMACC ships only a 64-bit build (Windows 10+, set by Qt 6).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=SMACC-Setup
SetupIconFile=..\src\smacc\assets\icon.ico
UninstallDisplayIcon={app}\SMACC.exe
; Without this, Inno defaults the Installed-apps entry to "SMACC version x.y.z"
; even though Windows shows the version (from AppVersion) in its own column.
UninstallDisplayName=SMACC
; Tells Windows to refresh Explorer's file-association cache after (un)install.
ChangesAssociations=yes
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
; Disable Inno's Restart Manager (#234). On a second, in-place install (an
; upgrade over an existing install) it enumerates processes holding handles to
; the exes it's about to replace and can block on a lingering OS/Defender scan
; handle to a just-written binary even under /VERYSILENT /SUPPRESSMSGBOXES.
; SMACC is a small per-user tool with no need to gracefully close running apps
; mid-upgrade; users close it before updating (the manual update-check flow
; prompts them). This also turns RM off in the uninstaller: uninstalling while
; SMACC is running falls back to the legacy file-in-use path instead of RM's
; close-and-restart page.
CloseApplications=no

[Tasks]
; Desktop shortcut is opt-in (unchecked by default); the Start menu entry is always created.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole onedir build: SMACC.exe plus its bundled Python/Qt/MNE runtime. The
; EEG Annotator is a mode of SMACC.exe (re-exec'd with --eeg), not a separate
; exe, so there are no installer components — every install is the full app.
Source: "..\dist\SMACC\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SMACC"; Filename: "{app}\SMACC.exe"
Name: "{autodesktop}\SMACC"; Filename: "{app}\SMACC.exe"; Tasks: desktopicon

[Registry]
; The .smacc file association — the installer is the primary owner (#187); the
; portable exe can opt in via the Launcher's File menu (smacc.winassoc). These
; entries mirror winassoc.association_entries() exactly (tests/test_winassoc.py
; cross-checks them), so an installed build passes winassoc.is_registered(). HKA
; is HKCU for the default per-user install and HKLM for an /ALLUSERS install.
Root: HKA; Subkey: "Software\Classes\.smacc"; ValueType: string; ValueName: ""; ValueData: "SMACC.Study"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.smacc"; ValueType: string; ValueName: "Content Type"; ValueData: "application/x-smacc"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SMACC.Study"; ValueType: string; ValueName: ""; ValueData: "SMACC study configuration"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SMACC.Study\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\SMACC.exe"",0"
Root: HKA; Subkey: "Software\Classes\SMACC.Study\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SMACC.exe"" ""%1"""

[Run]
Filename: "{app}\SMACC.exe"; Description: "{cm:LaunchProgram,SMACC}"; Flags: nowait postinstall skipifsilent

[Code]
{ Uninstalling never deletes the SMACC data folder (#189): it holds real study
  data (recordings, logs, SMACC files) mixed with app-managed seeds, so an
  automatic delete is never safe. Instead, say so at the end of uninstall —
  whoever uninstalls and finds the folder later shouldn't be left wondering
  whether removal failed. Skipped on a silent uninstall (no popups to hang an
  unattended run). }
function SmaccDataDir(): String;
begin
  { Mirrors smacc.utils.get_smacc_directory: $SMACC_DIRECTORY, else ~/SMACC. }
  Result := GetEnv('SMACC_DIRECTORY');
  if Result = '' then
    Result := ExpandConstant('{%USERPROFILE}\SMACC');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
    MsgBox('SMACC was removed, but your SMACC data folder was kept:'#13#10#13#10
      + SmaccDataDir() + #13#10#13#10
      + 'It holds your SMACC files, recordings, and logs. If you no longer '
      + 'need them, delete the folder manually.', mbInformation, MB_OK);
end;
