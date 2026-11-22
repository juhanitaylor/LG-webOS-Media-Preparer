"""Build the pinned Windows media payload from source, then stage build evidence."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
CACHE = BUILD / "native-inputs"
TOOLS = BUILD / "windows-payload" / "tools"
NATIVE = BUILD / "native"
SCRIPTS = ROOT / "scripts"
INPUT_FILE = SCRIPTS / "windows-inputs.json"
NOTICE_INPUT_FILE = SCRIPTS / "windows-notices-inputs.json"
TOOLCHAIN_FILE = SCRIPTS / "msys2-packages.lock"
RECIPE = SCRIPTS / "build_native_windows.sh"
INPUTS = json.loads(INPUT_FILE.read_text(encoding="utf-8")) | json.loads(NOTICE_INPUT_FILE.read_text(encoding="utf-8"))
NATIVE_SOURCES = ("ffmpeg", "x264", "tesseract", "leptonica", "libpng", "zlib")
DOTNET_VERSION = "10.0.14"
SECONV_VERSION = "5.4.0"


def run(*command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def sha256(path: Path) -> str:
    with path.open("rb") as contents:
        return hashlib.file_digest(contents, "sha256").hexdigest()


def fetch(name: str, url: str, expected: str, *, cache: Path = CACHE) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / name
    if not path.is_file():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as pending:
            temp = Path(pending.name)
        try:
            run("curl.exe", "--fail", "--location", "--silent", "--show-error", "--retry", "2",
                "--max-time", "300", "--proto", "=https", "--proto-redir", "=https", url, "--output", temp)
            if sha256(temp) != expected:
                raise ValueError(f"SHA-256 mismatch for {url}")
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    if sha256(path) != expected:
        raise ValueError(f"SHA-256 mismatch for {path}. Expected {expected}.")
    return path


def asset(name: str) -> Path:
    return fetch(*INPUTS[name])


def msys2() -> Path:
    root = NATIVE / "msys64"
    marker = root / ".lg-ucrt64-sha256"
    lock_hash = sha256(TOOLCHAIN_FILE)
    if marker.is_file() and marker.read_text(encoding="ascii").strip() == lock_hash:
        return root / "usr" / "bin" / "bash.exe"
    NATIVE.mkdir(parents=True, exist_ok=True)
    run("tar.exe", "-xf", asset("msys2"), "-C", NATIVE)
    rows = [line.split() for line in TOOLCHAIN_FILE.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")]

    def fetch_package(row: list[str]) -> Path:
        digest, url = row
        return fetch(urlsplit(url).path.rsplit("/", 1)[-1], url, digest, cache=CACHE / "packages")

    with ThreadPoolExecutor(max_workers=8) as pool:
        packages = list(pool.map(fetch_package, rows))
    for package in packages:
        run("tar.exe", "-xf", package, "-C", root, "--exclude=.BUILDINFO", "--exclude=.MTREE",
            "--exclude=.PKGINFO", "--exclude=.INSTALL")
    marker.write_text(lock_hash, encoding="ascii")
    return root / "usr" / "bin" / "bash.exe"


def extract_source(archive: Path, destination: Path) -> None:
    ready = destination / ".lg-source-sha256"
    digest = sha256(archive)
    if ready.is_file() and ready.read_text(encoding="ascii") == digest:
        return
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        for member in source:
            root, _, name = member.name.partition("/")
            if name:
                linkname = member.linkname.removeprefix(root + "/") if member.islnk() else member.linkname
                source.extract(member.replace(name=name, linkname=linkname), destination, filter="data")
    ready.write_text(digest, encoding="ascii")


@contextmanager
def short_path(path: Path):
    """Give Unix configure scripts a path without Windows spaces or long prefixes."""
    used = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in "ZYXWVUTSRQP":
        if not used & (1 << (ord(letter) - ord("A"))):
            break
    else:
        raise RuntimeError("No free drive letter for the Windows native build")
    drive = f"{letter}:"
    run("subst.exe", drive, path)
    try:
        yield f"/{letter.lower()}"
    finally:
        run("subst.exe", drive, "/D")


def build_native() -> Path:
    fingerprint = hashlib.sha256((sha256(RECIPE) + sha256(TOOLCHAIN_FILE) + sha256(INPUT_FILE)).encode()).hexdigest()
    work = NATIVE / f"work-{fingerprint[:12]}"
    payload = work / "payload"
    if all((payload / name).is_file() for name in ("ffmpeg.exe", "ffprobe.exe", "tesseract.exe")):
        return work
    for name in NATIVE_SOURCES:
        extract_source(asset(name), work / "source" / name)
    shell = msys2()
    shutil.copyfile(RECIPE, work / "compile.sh")
    env = dict(os.environ, MSYSTEM="UCRT64", CHERE_INVOKING="1", MSYS2_PATH_TYPE="strict")
    with short_path(work) as path:
        run(shell, f"{path}/compile.sh", path, str(min(8, os.cpu_count() or 2)), env=env)
    return work


def build_seconv() -> tuple[Path, Path]:
    sdk = BUILD / "dotnet-10.0.403"
    dotnet = sdk / "dotnet.exe"
    if not dotnet.is_file() or run(dotnet, "--version", capture_output=True, text=True).stdout.strip() != "10.0.403":
        sdk.mkdir(parents=True, exist_ok=True)
        run("tar.exe", "-xf", asset("dotnet"), "-C", sdk)
    source = BUILD / "seconv-src"
    extract_source(asset("seconv"), source)
    published = BUILD / "seconv-publish"
    locks = SCRIPTS / "seconv-packages.lock.json"
    marker = published / ".lg-publish-sha256"
    fingerprint = hashlib.sha256((INPUTS["seconv"][2] + INPUTS["dotnet"][2] + sha256(locks)).encode()).hexdigest()
    if (published / "seconv.exe").is_file() and marker.is_file() and marker.read_text(encoding="ascii") == fingerprint:
        return source, published
    project = source / "src" / "seconv" / "SeConv.csproj"
    original = project.read_text(encoding="utf-8-sig")
    patched, count = re.subn(r"\n  <!-- Bundle the dictionaries.*?</Target>\n", "\n", original, flags=re.S)
    patch = source / "seconv-no-dictionaries.patch"
    if count == 1:
        import difflib

        patch.write_text("".join(difflib.unified_diff(original.splitlines(True), patched.splitlines(True),
                                                     "a/src/seconv/SeConv.csproj", "b/src/seconv/SeConv.csproj")),
                         encoding="utf-8")
        project.write_text(patched, encoding="utf-8")
    elif not patch.is_file():
        raise ValueError("Could not identify the bundled dictionary asset in SeConv")
    for project_dir, lock in json.loads(locks.read_text(encoding="utf-8")).items():
        (source / "src" / project_dir / "packages.lock.json").write_text(
            json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    config = BUILD / "SeConv.NuGet.Config"
    config.write_text('<configuration><packageSources><clear/><add key="nuget.org" '
                      'value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>\n', encoding="utf-8")
    env = dict(os.environ, DOTNET_CLI_HOME=str(BUILD / "dotnet-home"), NUGET_PACKAGES=str(BUILD / "nuget"),
               DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
               DOTNET_GENERATE_ASPNET_CERTIFICATE="false")
    options = ("-r", "win-x64", "-p:SelfContained=true", "-p:PublishSingleFile=true",
               f"-p:RuntimeFrameworkVersion={DOTNET_VERSION}", "-p:TargetLatestRuntimePatch=false",
               f"-p:Version={SECONV_VERSION}")
    run(dotnet, "restore", project, "--configfile", config, "--locked-mode", *options, cwd=source, env=env)
    run(dotnet, "publish", project, "--no-restore", "-c", "Release", "-o", published,
        *options, cwd=source, env=env)
    marker.write_text(fingerprint, encoding="ascii")
    return source, published


def stage_payload(native: Path, seconv: Path) -> None:
    media = TOOLS
    converter = TOOLS / "ocr" / "seconv"
    tesseract = TOOLS / "ocr" / "tesseract"
    language = tesseract / "tessdata"
    for destination in (media, converter, language):
        destination.mkdir(parents=True, exist_ok=True)
    files = {
        media / "ffmpeg.exe": native / "payload" / "ffmpeg.exe",
        media / "ffprobe.exe": native / "payload" / "ffprobe.exe",
        converter / "seconv.exe": seconv / "seconv.exe",
        converter / "libSkiaSharp.dll": seconv / "libSkiaSharp.dll",
        converter / "libHarfBuzzSharp.dll": seconv / "libHarfBuzzSharp.dll",
        tesseract / "tesseract.exe": native / "payload" / "tesseract.exe",
        language / "eng.traineddata": asset("eng"),
    }
    for destination, source in files.items():
        if not destination.is_file() or sha256(destination) != sha256(source):
            shutil.copyfile(source, destination)
    for tool in (media / "ffmpeg.exe", media / "ffprobe.exe", converter / "seconv.exe", tesseract / "tesseract.exe"):
        switch = "-version" if tool.parent == media else "--version"
        print(run(tool, switch, text=True, capture_output=True).stdout.splitlines()[0], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=["native", "seconv", "all"], default="all")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        parser.error("Use a Windows x64 Python interpreter")
    if BUILD.resolve() != BUILD:
        parser.error("The build directory must resolve inside the repository")
    if args.component == "native":
        print(f"Native media tools built in {build_native()}", flush=True)
    elif args.component == "seconv":
        print(f"Headless SeConv built in {build_seconv()[1]}", flush=True)
    else:
        native = build_native()
        _, converter = build_seconv()
        stage_payload(native, converter)


if __name__ == "__main__":
    main()
