; The Windows installer of Dossier (Inno Setup 6): dist\dossier.exe into the user's own programs folder, with a Start menu entry.
;
; Build:   iscc /DAppRelease=0.5 /DAppBuild=2026-11-05#01 installer\dossier.iss      (or build_installer.bat, which reads both)
; Output:  dist\dossier-setup.exe
;
; Per user, no administrator rights: %LOCALAPPDATA%\Programs\Dossier. That folder stays writable, so Help > Check for Updates can
; swap dossier.exe in place as it does for the bare exe (redactor_common selfupdate). Settings are not here but in the user's
; AppData (dossier.ini), so uninstalling leaves them, and a new install finds them again.

#ifndef AppRelease
  #define AppRelease "0.0"
#endif
#ifndef AppBuild
  #define AppBuild "0000-00-00#00"
#endif

[Setup]
AppId={{C61A77AD-D4A2-44EB-8CFB-B15A58A735F3}
AppName=Dossier
AppVersion={#AppRelease} (build {#AppBuild})
AppVerName=Dossier {#AppRelease}
AppPublisher=Erlbon
AppPublisherURL=https://github.com/Erlbon/dossier
AppSupportURL=https://github.com/Erlbon/dossier/issues
AppUpdatesURL=https://github.com/Erlbon/dossier/releases
VersionInfoVersion=0.0.0.0
VersionInfoProductTextVersion={#AppRelease} (build {#AppBuild})
PrivilegesRequired=lowest
DefaultDirName={autopf}\Dossier
DefaultGroupName=Dossier
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\dossier.exe
UninstallDisplayName=Dossier
SetupIconFile=..\dossier\gui\appicon\dossier.ico
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=dossier-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=yes

[Tasks]
Name: "desktopicon"; Description: "A shortcut on the desktop"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "addtopath"; Description: "Add Dossier to PATH, so ""dossier ls"", ""dossier find"" and the other commands work in any terminal"; GroupDescription: "Command line:"; Flags: unchecked

[Files]
Source: "..\dist\dossier.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CREDITS.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Dossier"; Filename: "{app}\dossier.exe"
Name: "{autodesktop}\Dossier"; Filename: "{app}\dossier.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\dossier.exe"; Description: "Start Dossier"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; what Help > Check for Updates leaves beside the exe: the old exe after a swap, and a download that did not finish
Type: files; Name: "{app}\dossier.exe.old"
Type: files; Name: "{app}\dossier.exe.new"
Type: files; Name: "{app}\dossier.exe.new.part"

[Code]
// Per user only (no "for all users" choice): under Program Files the updater could not swap dossier.exe. So PATH is the user's own.
const
  PathKeyRoot = HKEY_CURRENT_USER;
  PathKeyName = 'Environment';

function PathHasApp(const Path, Dir: String): Boolean;
begin
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Path) + ';') > 0;
end;

procedure AddAppToPath;
var
  Path, Dir: String;
begin
  Dir := ExpandConstant('{app}');
  if not RegQueryStringValue(PathKeyRoot, PathKeyName, 'Path', Path) then
    Path := '';
  if PathHasApp(Path, Dir) then
    exit;
  // a PATH that ends with ';' keeps ending with one, so the uninstall (which takes ';<dir>' out) gives back the PATH as it was
  if Path = '' then
    Path := Dir
  else if Copy(Path, Length(Path), 1) = ';' then
    Path := Path + Dir + ';'
  else
    Path := Path + ';' + Dir;
  RegWriteExpandStringValue(PathKeyRoot, PathKeyName, 'Path', Path);
end;

procedure RemoveAppFromPath;
var
  Path, Dir: String;
  P: Integer;
begin
  Dir := ExpandConstant('{app}');
  if not RegQueryStringValue(PathKeyRoot, PathKeyName, 'Path', Path) then
    exit;
  Path := ';' + Path + ';';
  P := Pos(';' + Uppercase(Dir) + ';', Uppercase(Path));
  if P = 0 then
    exit;
  Delete(Path, P, Length(Dir) + 1);
  Path := Copy(Path, 2, Length(Path) - 2);
  RegWriteExpandStringValue(PathKeyRoot, PathKeyName, 'Path', Path);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    AddAppToPath;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveAppFromPath;
end;
