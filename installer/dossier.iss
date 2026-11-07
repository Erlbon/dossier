; The Windows installer of Dossier (Inno Setup 6): the one-folder build (dist\dossier\, built with DOSSIER_BUILD=folder) into the user's
; own programs folder, with a Start menu entry. The one-folder build starts in about a second; the one-file dossier.exe unpacks itself at
; every start and takes over three (comparison review 2026-11-05, card 2), so it stays the portable download only.
;
; Build:   build_installer.bat (it builds the folder too and passes /DUpdateContract), or by hand:
;          iscc /DAppRelease=0.8 /DAppBuild=2026-11-07#01 /DUpdateContract=<python -m redactor_common.release contract-path> installer\dossier.iss
; Output:  dist\dossier-setup.exe
;
; Per user, no administrator rights: %LOCALAPPDATA%\Programs\Dossier. Updating goes through the family's update framework
; (redactor_common docs/update-framework.md): its installer contract, included at the end, writes {app}\update-channel =
; windows-installer, so Help > Check for Updates runs the new dossier-setup.exe the release's update-manifest.json names, silently with
; /relaunch=yes, and the contract starts Dossier again. Copies from before the contract (0.7 and older) pass /RESTARTAPP=1, which the
; contract honours too. Settings are not here but in the user's AppData (dossier.ini), so uninstalling leaves them, and a new install
; finds them again.

#ifndef AppRelease
  #define AppRelease "0.0"
#endif
#ifndef AppBuild
  #define AppBuild "0000-00-00#00"
#endif
#ifndef UpdateContract
  #error Pass /DUpdateContract (build_installer.bat does: python -m redactor_common.release contract-path)
#endif

; The family's installer contract (included at the end): starting Dossier again after an update, update-channel, and waiting until a
; running Dossier has let go of its exe before files are replaced (Dossier has no --quit: Windows' close request ends it, saving first).
#define UpdateExe "dossier.exe"

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
Source: "..\dist\dossier\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CREDITS.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Dossier"; Filename: "{app}\dossier.exe"
Name: "{autodesktop}\Dossier"; Filename: "{app}\dossier.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\dossier.exe"; Description: "Start Dossier"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; a copy installed before the one-folder build had the one-file exe; its leftovers of an update go
Type: files; Name: "{app}\dossier.exe.old"

[UninstallDelete]
; what Help > Check for Updates leaves beside the exe: the old exe after a swap, and a download that did not finish
Type: files; Name: "{app}\dossier.exe.old"
Type: files; Name: "{app}\dossier.exe.new"
Type: files; Name: "{app}\dossier.exe.new.part"

[Code]
// Per user only (no "for all users" choice): the program stays where the user can write. So PATH is the user's own.
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

#include UpdateContract
