# PyInstaller spec file for Dossier.
#
# Build on Windows with: python -m PyInstaller dossier.spec --noconfirm   (or build_exe.bat)
# PyInstaller builds for the platform it runs ON: a Windows .exe cannot be made from Linux or macOS.
#
# The program is one exe: the window, and the command line (dossier ls, find, copy..., dossier mcp) in the same file.
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

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
    ],
    # Found by name when they are needed, so the static analysis cannot see them: the whole program (the window loads some parts
    # lazily), the shared Redactor package (the command line), the password store's back ends and the recycle bin's.
    hiddenimports=(collect_submodules("dossier") + collect_submodules("redactor_common") + collect_submodules("keyring.backends")
                   + collect_submodules("send2trash")),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Not used by the program; PyInstaller would bundle them whenever they happen to be installed on the build machine.
    excludes=["numpy", "tkinter", "unittest", "pytest", "py7zr"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="dossier",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # a window program: no console box behind it (output still goes to a pipe or a file)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="dossier/gui/appicon/dossier.ico",
)
