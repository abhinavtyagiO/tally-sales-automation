# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None
project_root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
helper_app = os.path.abspath(os.path.join(SPECPATH, "..", "helper_app.py"))

a = Analysis(
    [helper_app],
    pathex=[project_root],
    binaries=[],
    datas=[],
    hiddenimports=[
        "backend.services.tally_client",
        "pystray",
        "pystray._win32",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="AccountPilotHelper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
