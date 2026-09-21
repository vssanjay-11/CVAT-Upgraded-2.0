# -*- mode: python ; coding: utf-8 -*-
# Copyright (C) CVAT.ai Corporation
# SPDX-License-Identifier: MIT

import os
from pathlib import Path

block_cipher = None

# Root directory of the CVAT repository
REPO_ROOT = os.path.abspath(SPECPATH)

# Source path of compiled static UI files
UI_DIST_DIR = os.path.join(REPO_ROOT, 'cvat-ui', 'dist')

datas = []
if os.path.exists(UI_DIST_DIR):
    datas.append((UI_DIST_DIR, 'cvat_dist'))
else:
    print(f"[!] Warning: UI dist folder not found at {UI_DIST_DIR}.")
    print("    Make sure to run 'yarn workspace cvat-ui run build' before packaging.")

a = Analysis(
    ['cvat_app_launcher.py'],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'http.server',
        'urllib.request',
        'urllib.error',
        'socket',
        'threading',
        'webbrowser',
        'mimetypes',
        'pathlib',
        'json',
        'email',
        'email.message',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CVAT_App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
