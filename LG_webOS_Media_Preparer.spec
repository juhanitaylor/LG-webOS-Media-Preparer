# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from runpy import run_path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

root = Path(SPECPATH)
release_name = run_path(str(root / "scripts" / "windows_release_name.py"))
version = release_name["VERSION"]
exe_name = release_name["EXE_NAME"]
numeric_version = (*map(int, version.split(".")), 0)
title = "LG webOS Media Preparer"
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numeric_version, prodvers=numeric_version, OS=0x40004, fileType=1),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", title),
            StringStruct("FileVersion", version),
            StringStruct("OriginalFilename", exe_name),
            StringStruct("ProductName", title),
            StringStruct("ProductVersion", version),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

payload = root / "build" / "windows-payload"
required = ["ffmpeg.exe", "ffprobe.exe", "ocr/seconv/seconv.exe", "ocr/seconv/libSkiaSharp.dll",
            "ocr/seconv/libHarfBuzzSharp.dll", "ocr/tesseract/tesseract.exe",
            "ocr/tesseract/tessdata/eng.traineddata"]
datas = []
for name in required:
    source = payload / "tools" / name
    if not source.is_file():
        raise SystemExit(f"Missing verified build input {source}")
    datas.append((str(source), (Path("tools") / name).parent.as_posix()))

analysis = Analysis([str(root / "run_gui.py")], pathex=[str(root)], binaries=[], datas=datas)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name=Path(exe_name).stem, console=False, upx=False, version=version_info,
)
