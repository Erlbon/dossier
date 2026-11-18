# PyInstaller spec file for Dossier.
#
# Build on Windows with: python -m PyInstaller dossier.spec --noconfirm   (or build_exe.bat)
# PyInstaller builds for the platform it runs ON: a Windows .exe cannot be made from Linux or macOS.
#
# The program is one exe: the window, and the command line (dossier ls, find, copy..., dossier mcp) in the same file.
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# DOSSIER_BUILD=folder: the one-folder build the installer ships (dist\dossier\dossier.exe and its _internal folder). It starts in about
# a second, against 3.4 s for the one-file exe, which unpacks itself at every start (comparison review 2026-11-05, card 2). The default
# stays the one-file dossier.exe: the portable download, and the file a bare copy's Check for Updates swaps.
#
# On the Mac and on Linux (the hand-started Build workflow, cards 41-43 of 2026-11-18) the build is always a folder: Dossier.app on the
# Mac, dist/dossier for the Linux tarball. Neither updates itself (43A): Check for Updates links to the newer build.
MAC = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")
FOLDER = os.environ.get("DOSSIER_BUILD", "") == "folder" or MAC or LINUX

# The update framework's channel (redactor_common docs/update-framework.md): how this copy updates itself. The one-file exe carries
# "windows-exe" inside (it swaps itself); the folder build gets "windows-zip" beside its exe below, which the installer replaces with
# "windows-installer". The Linux folder says "linux-tarball" (it cannot replace itself, and says so); the Mac app has no channel the
# framework knows yet, so it says it cannot tell and links to the release page.
CHANNEL = os.path.join(workpath, "update-channel")
if not FOLDER:
    os.makedirs(workpath, exist_ok=True)
    with open(CHANNEL, "w", encoding="utf-8") as channel:
        channel.write("windows-exe\n")

a = Analysis(
    ["dossier/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("dossier/gui/icons", "dossier/gui/icons"),          # the Tabler and Lucide icon sets
        ("dossier/gui/appicon", "dossier/gui/appicon"),      # the program's own icon
        ("README.md", "."),
        ("CHANGELOG.md", "."),
        ("CREDITS.md", "."),
        ("LICENSE", "."),
    ] + ([] if FOLDER else [(CHANNEL, ".")]),
    # Found by name when they are needed, so the static analysis cannot see them: the whole program (the window loads some parts
    # lazily), the shared Redactor package (the command line), the password store's back ends and the recycle bin's.
    hiddenimports=(collect_submodules("dossier") + collect_submodules("redactor_common") + collect_submodules("keyring.backends")
                   + collect_submodules("send2trash")),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Not used by the program; PyInstaller would bundle them whenever they happen to be installed on the build machine.
    excludes=["numpy", "tkinter", "unittest", "pytest"],          # py7zr stays in: the exe opens 7z files with nothing else installed
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    *([] if FOLDER else [a.binaries, a.zipfiles, a.datas]),
    [],
    exclude_binaries=FOLDER,
    name="dossier",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX off (2026-11-07, as in the Redactor apps since 2026-10-30): Defender flagged UPX-packed, unsigned releases as malware.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # a window program: no console box behind it (output still goes to a pipe or a file)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="build/dossier.icns" if MAC else "dossier/gui/appicon/dossier.ico",    # the .icns: python tools/make_icons.py --icns build/dossier.icns
)

if FOLDER:
    coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, upx_exclude=[], name="dossier")
    if not MAC:
        with open(os.path.join(DISTPATH, "dossier", "update-channel"), "w", encoding="utf-8") as channel:
            channel.write("linux-tarball\n" if LINUX else "windows-zip\n")

if MAC:
    sys.path.insert(0, SPECPATH)
    from dossier.core.version import APP_VERSION, RELEASE

    app = BUNDLE(
        coll,
        name="Dossier.app",
        icon="build/dossier.icns",
        bundle_identifier="io.github.erlbon.dossier",
        info_plist={
            "CFBundleName": "Dossier",
            "CFBundleDisplayName": "Dossier",
            "CFBundleShortVersionString": RELEASE,
            "CFBundleVersion": APP_VERSION.replace("#", "."),
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,          # follow the Mac's light or dark look
            "NSAppleEventsUsageDescription": "Dossier opens Terminal or iTerm in the folder you choose.",
        },
    )
