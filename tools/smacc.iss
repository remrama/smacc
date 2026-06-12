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

[Tasks]
; Desktop shortcut is opt-in (unchecked by default); the Start menu entry is always created.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

; The EEG Review Tools (#136) are an optional component: the SMACC-EEG.exe
; bundle carries the full MNE/pyqtgraph stack, so labs that only run sessions
; skip it. The first [Types] entry ("standard", without it) is the default for
; a fresh install; on upgrades Inno preselects whatever was chosen before, so
; the pair stays in sync. A silent install adds it with /COMPONENTS="core,eeg",
; and re-running the installer later can add it to an existing install.
[Types]
Name: "standard"; Description: "Standard installation"
Name: "full"; Description: "Full installation (with EEG Review Tools)"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Components]
Name: "core"; Description: "SMACC"; Types: standard full custom; Flags: fixed
Name: "eeg"; Description: "EEG Review Tools (view and annotate recordings)"; Types: full

[Files]
Source: "..\dist\SMACC.exe"; DestDir: "{app}"; Components: core; Flags: ignoreversion
Source: "..\dist\SMACC-EEG.exe"; DestDir: "{app}"; Components: eeg; Flags: ignoreversion

[InstallDelete]
; Inno never removes a *deselected* component's files on an upgrade — without
; this, dropping the EEG component would leave a stale, never-again-updated
; SMACC-EEG.exe behind, which the launcher's availability probe would still
; detect and happily run.
Type: files; Name: "{app}\SMACC-EEG.exe"; Components: not eeg
Type: files; Name: "{autoprograms}\SMACC EEG review.lnk"; Components: not eeg

[Icons]
Name: "{autoprograms}\SMACC"; Filename: "{app}\SMACC.exe"
; The EEG viewer is also launchable from inside SMACC, but a reviewer doing
; daytime analysis shouldn't have to open the session app to get there.
Name: "{autoprograms}\SMACC EEG review"; Filename: "{app}\SMACC-EEG.exe"; Components: eeg
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
