# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the SmartDocs desktop sidecar (ONE-DIRECTORY build).

One-dir is deliberate: one-file would unpack to a temp dir on every launch
(slow, and antivirus-hostile on Windows) and has not been proven to work with
the OCR/ML/database dependency set — per the desktop architecture mandate,
one-dir stays until one-file is proven.

Build (from repo root):  scripts/build-sidecar.sh
Output:                  desktop/sidecar/dist/smartdocs-sidecar/
The Tauri bundle picks the output up via tauri.conf.json → bundle.resources.
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]   # repo root (desktop/sidecar/../..)

datas = [
    (str(ROOT / "static"), "static"),        # SPA + agent workspace, read-only
    (str(ROOT / "templates"), "templates"),  # server-rendered admin pages
]

hiddenimports = [
    # SQLAlchemy's sqlite dialect is imported by string name at runtime.
    "sqlalchemy.dialects.sqlite",
    # keyring discovers its platform backend dynamically.
    "keyring.backends.SecretService",
    "keyring.backends.macOS",
    "keyring.backends.Windows",
    "keyring.backends.chainer",
    "keyring.backends.fail",
]

a = Analysis(
    [str(ROOT / "desktop_server.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Never drag half an ML stack in by accident; these are the lazy,
        # optional imports the core build intentionally leaves out.
        "torch", "torchvision", "transformers", "sentence_transformers",
        "faiss", "paddle", "paddleocr", "paddlex", "vietocr",
        "argostranslate", "underthesea", "sklearn", "scipy", "nltk",
        "matplotlib", "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="smartdocs-sidecar",
    debug=False,
    bootloader_ignore_signals=False,   # Tauri's SIGTERM must reach Python
    strip=False,
    upx=False,
    console=True,                      # stdout carries the JSON handshake
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="smartdocs-sidecar",
)
