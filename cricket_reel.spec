# PyInstaller spec for the Cricket Reel desktop app. Build with build_desktop.bat.
# -*- mode: python ; coding: utf-8 -*-
import os
import shutil

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ff = shutil.which("ffmpeg")
fp = shutil.which("ffprobe")
if not ff or not fp:
    raise SystemExit("FFmpeg not found on PATH. Install it with: winget install -e --id Gyan.FFmpeg")

datas = [
    ("static", "static"),
    ("config/tokens.json", "config"),
    (ff, "ffmpeg"),
    (fp, "ffmpeg"),
    ("assets/icon.ico", "assets"),
]
datas += collect_data_files("webview")

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("app")
    + ["multipart", "python_multipart", "webview.platforms.edgechromium", "clr_loader", "pythonnet"]
)

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    # Not used at run time: librosa and its JIT stack were replaced by numpy/scipy (hits.py); uvicorn's reload and
    # websocket extras aren't needed by the desktop app.
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "PyQt5", "PyQt6", "PySide2", "PySide6", "librosa", "numba",
              "llvmlite", "sklearn", "joblib", "soundfile", "soxr", "pooch", "watchfiles", "websockets", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Cricket Reel",
    icon="assets/icon.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Cricket Reel", upx=False)
