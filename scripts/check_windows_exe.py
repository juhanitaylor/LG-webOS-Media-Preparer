"""Verify build metadata and launch the windowed EXE from a separate directory."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import pefile

from windows_release_name import EXE_NAME, VERSION


def version_strings(pe: pefile.PE) -> dict[bytes, bytes]:
    return {key: value for group in pe.FileInfo for entry in group
            for table in getattr(entry, "StringTable", []) for key, value in table.entries.items()}


def visible_window(executable: Path, expected_title: str) -> int:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                                   wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found = 0

    @callback_type
    def inspect_window(hwnd, _):
        nonlocal found
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value != expected_title or not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                image = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(image))
                if kernel32.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
                    if Path(image.value).resolve() == executable:
                        found = hwnd
                        return False
            finally:
                kernel32.CloseHandle(handle)
        return True

    user32.EnumWindows(inspect_window, 0)
    return found


def has_visible_desktop() -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.GetUserObjectInformationW.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                 wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    flag_length = wintypes.DWORD()
    flags = (wintypes.DWORD * 3)()
    if not user32.GetUserObjectInformationW(user32.GetProcessWindowStation(), 1, ctypes.byref(flags),
                                             ctypes.sizeof(flags), ctypes.byref(flag_length)):
        raise ctypes.WinError(ctypes.get_last_error())
    return bool(flags[2] & 1)


def check_gui(candidate: Path, version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="LG portable café ") as temp:
        root = Path(temp)
        launch_dir = root / "copied application"
        launch_dir.mkdir()
        exe = launch_dir / candidate.name
        shutil.copyfile(candidate, exe)
        env = os.environ.copy()
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        env["LOCALAPPDATA"] = str(root / "profile")
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        start = time.monotonic()
        with subprocess.Popen([exe], cwd=root, env=env) as process:
            try:
                while process.poll() is None and time.monotonic() - start < 60:
                    hwnd = visible_window(exe.resolve(), f"LG webOS Media Preparer {version}")
                    if hwnd:
                        print(f"Visible packaged GUI in {time.monotonic() - start:.2f}s")
                        ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), 0x10, 0, 0)  # WM_CLOSE
                        if process.wait(timeout=15):
                            raise RuntimeError("The packaged GUI did not exit cleanly")
                        return
                    time.sleep(0.1)
                raise RuntimeError(f"The packaged GUI did not open. Exit status {process.poll()}.")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    import tomllib

    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if version != VERSION:
        raise ValueError(f"Application version {VERSION} differs from project version {version}")
    candidate = Path(sys.argv[1]).resolve()
    if candidate.name != EXE_NAME:
        raise ValueError(f"Expected executable name {EXE_NAME}, got {candidate.name}")
    pe = pefile.PE(str(candidate))
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Subsystem != 2:
        raise ValueError("Expected a Windows x64 GUI subsystem executable")
    strings = version_strings(pe)
    for key in (b"FileVersion", b"ProductVersion"):
        if strings.get(key) != version.encode():
            raise ValueError(f"Unexpected Windows version metadata {strings}")
    if strings.get(b"OriginalFilename") != EXE_NAME.encode():
        raise ValueError(f"Unexpected Windows original filename {strings.get(b'OriginalFilename')}")
    print(f"Verified {EXE_NAME}, Windows x64 GUI subsystem and file/product version {version}")
    if has_visible_desktop():
        check_gui(candidate, version)
    else:
        print("Visible GUI startup check skipped because this Windows session has no visible desktop.")


if __name__ == "__main__":
    main()
