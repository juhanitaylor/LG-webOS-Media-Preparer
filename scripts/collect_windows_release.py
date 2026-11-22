"""Collect the audited payload, corresponding sources, and release checksum."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

import pefile

from prepare_windows_native import (BUILD, INPUTS, INPUT_FILE, NATIVE, NATIVE_SOURCES, NOTICE_INPUT_FILE,
                                    RECIPE, ROOT, SCRIPTS, TOOLS, TOOLCHAIN_FILE, asset, build_native,
                                    extract_source, run, sha256)


NOTICE = re.compile(r"^(?:license|licence|copying|copyright|third.?party.?notice|leptonica-license)", re.I)
SECONV_PROJECTS = ("src/seconv", "src/libse", "src/libuilogic")


def copy_notices(files, destination: Path) -> None:
    selected = [path for path in files if path.is_file() and NOTICE.match(path.name)]
    if not selected:
        raise ValueError(f"No licence notice found for {destination.name}")
    destination.mkdir(parents=True, exist_ok=True)
    for path in selected:
        shutil.copyfile(path, destination / path.name)


def package_inventory() -> dict:
    binary = (TOOLS / "ocr" / "seconv" / "seconv.exe").read_bytes()
    start = re.search(rb'\{\s*"runtimeTarget"\s*:', binary)
    if start is None:
        raise ValueError("Could not find the embedded SeConv dependency manifest")
    metadata, _ = json.JSONDecoder().raw_decode(binary[start.start():start.start() + 500_000].decode("utf-8", "replace"))
    return metadata["libraries"]


def stage_seconv_notices(destination: Path) -> dict[str, dict[str, str]]:
    source = BUILD / "seconv-src"
    copy_notices(source.iterdir(), destination / "Subtitle-Edit")
    inventory = {}
    for key, details in package_inventory().items():
        name, version = key.lower().removeprefix("runtimepack.").split("/")
        if name in {"libse", "libuilogic", "seconv"}:
            continue
        package = BUILD / "nuget" / name / version
        nupkg = package / f"{name}.{version}.nupkg"
        hash_file = nupkg.with_suffix(".nupkg.sha512")
        archive_digest = base64.b64encode(hashlib.sha512(nupkg.read_bytes()).digest()).decode("ascii")
        if archive_digest != hash_file.read_text(encoding="utf-8-sig").strip():
            raise ValueError(f"Unexpected NuGet archive checksum for {key}")
        package_metadata = json.loads((package / ".nupkg.metadata").read_text(encoding="utf-8-sig"))
        content = "sha512-" + package_metadata["contentHash"]
        if details.get("sha512") and details["sha512"] != content:
            raise ValueError(f"Unexpected NuGet package checksum for {key}")
        output = destination / f"{name}-{version}"
        output.mkdir(parents=True, exist_ok=True)
        if name in {"spectre.console", "spectre.console.ansi", "spectre.console.cli"}:
            licence = asset("spectre-cli" if name.endswith(".cli") else "spectre")
            shutil.copyfile(licence, output / "LICENSE.md")
        elif name == "utf.unknown":
            mpl_source = BUILD / "utf-unknown-src"
            extract_source(asset("utf-unknown"), mpl_source)
            shutil.copytree(mpl_source / "license", output, dirs_exist_ok=True)
        else:
            copy_notices(package.iterdir(), output)
        inventory[key] = {"content_hash": content, "archive_sha512_base64": archive_digest}
    return inventory


def native_imports() -> dict[str, list[str]]:
    inventory = {}
    windows = Path(os.environ["SystemRoot"]) / "System32"
    for file in sorted(TOOLS.rglob("*")):
        if file.suffix.lower() not in {".exe", ".dll"}:
            continue
        with pefile.PE(str(file), fast_load=True) as pe:
            if pe.FILE_HEADER.Machine != 0x8664:
                raise ValueError(f"Media payload is not x64: {file}")
            pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                       pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
            imports = sorted({entry.dll.decode("ascii").lower()
                              for entries in (getattr(pe, "DIRECTORY_ENTRY_IMPORT", []),
                                              getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []))
                              for entry in entries})
        for dependency in imports:
            if not (dependency.startswith(("api-ms-win-", "ext-ms-win-")) or (windows / dependency).is_file()
                    or (file.parent / dependency).is_file()):
                raise ValueError(f"{file.name} imports an unstaged runtime DLL: {dependency}")
        inventory[file.relative_to(TOOLS).as_posix()] = imports
    return inventory


def zip_sources(output: Path, native: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
        for name in (*NATIVE_SOURCES, "utf-unknown"):
            source = asset(name)
            archive.write(source, "upstream/" + source.name)
        for file in (RECIPE, INPUT_FILE, NOTICE_INPUT_FILE, TOOLCHAIN_FILE,
                     SCRIPTS / "prepare_windows_native.py", SCRIPTS / "seconv-packages.lock.json"):
            archive.write(file, "recipes/" + file.name)
        for file in (native / "source" / "ffmpeg" / "ffbuild" / "config.mak",
                     native / "source" / "x264" / "config.mak"):
            archive.write(file, f"configuration/{file.parent.parent.name}-{file.name}"
                                if file.parent.name == "ffbuild" else "configuration/x264-config.mak")
        seconv = BUILD / "seconv-src"
        archive.write(seconv / "LICENSE", "seconv-5.4.0/LICENSE")
        archive.write(seconv / "Directory.Build.props", "seconv-5.4.0/Directory.Build.props")
        archive.write(seconv / "seconv-no-dictionaries.patch", "seconv-5.4.0/seconv-no-dictionaries.patch")
        archive.write(seconv / "src" / "AssetZips.targets", "seconv-5.4.0/src/AssetZips.targets")
        for subdir in SECONV_PROJECTS:
            for file in (seconv / subdir).rglob("*"):
                path = file.relative_to(seconv)
                if file.is_file() and not {"bin", "obj"} & set(path.parts):
                    archive.write(file, "seconv-5.4.0/" + path.as_posix())


def publish_file(source: Path, destination: Path, *, identical_ok: bool = False) -> None:
    # Let files inherit the destination folder ACL rather than a private staging directory's ACL.
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".release-file-", delete=False) as pending:
        path = Path(pending.name)
        try:
            with source.open("rb") as contents:
                shutil.copyfileobj(contents, pending)
            pending.close()
            try:
                path.replace(destination)
            except PermissionError:
                if not identical_ok or not destination.is_file() or sha256(source) != sha256(destination):
                    raise
        finally:
            pending.close()
            path.unlink(missing_ok=True)


def main() -> None:
    candidate = Path(sys.argv[1]).resolve(strict=True)
    native = build_native()
    dist = ROOT / "dist"
    if dist.resolve() != dist:
        raise ValueError("The release output directory must resolve inside the repository")
    dist.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dist, prefix=".release-") as temp:
        release = Path(temp)
        notices = release / "notices"
        for name in NATIVE_SOURCES:
            copy_notices((native / "source" / name).iterdir(), notices / name)
        toolchain_notices = NATIVE / "msys64" / "ucrt64" / "share" / "licenses"
        for package in ("gcc", "libgcc", "crt", "winpthreads"):
            copy_notices((toolchain_notices / package).iterdir(), notices / f"MinGW-{package}")
        copy_notices(Path(sys.base_prefix).iterdir(), notices / "Python")
        for name in ("tcl-license", "tk-license"):
            licence = asset(name)
            shutil.copyfile(licence, notices / licence.name)
        shutil.copyfile(asset("eng-license"), notices / "tessdata_fast-LICENSE.txt")
        converter = stage_seconv_notices(notices)
        shutil.copyfile(ROOT / "docs" / "WINDOWS_THIRD_PARTY.md", notices / "WINDOWS_THIRD_PARTY.md")
        imports = native_imports()
        payload = {file.relative_to(TOOLS).as_posix(): {"sha256": sha256(file), "bytes": file.stat().st_size}
                   for file in sorted(TOOLS.rglob("*")) if file.is_file()}
        ffmpeg = run(TOOLS / "ffmpeg.exe", "-version", text=True, capture_output=True).stdout
        if "--enable-libx264" not in ffmpeg or "--disable-network" not in ffmpeg:
            raise ValueError("FFmpeg build configuration did not match the portable recipe")
        if "--enable-nonfree" in ffmpeg:
            raise ValueError("FFmpeg build included nonredistributable options")
        (notices / "FFmpeg-build.txt").write_text(ffmpeg, encoding="utf-8")
        manifest = {
            "executable": {"file": candidate.name, "bytes": candidate.stat().st_size, "sha256": sha256(candidate)},
            "python": sys.version,
            "build_inputs": INPUTS,
            "msys2_package_lock": TOOLCHAIN_FILE.read_text(encoding="utf-8").splitlines(),
            "seconv_packages": converter,
            "payload": payload,
            "windows_pe_imports": imports,
        }
        (release / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        with zipfile.ZipFile(release / "third-party-notices.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(notices.rglob("*")):
                if file.is_file():
                    archive.write(file, file.relative_to(notices).as_posix())
        zip_sources(release / "third-party-sources.zip", native)
        checksum = manifest["executable"]["sha256"]
        (release / f"{candidate.name}.sha256").write_text(f"{checksum}  {candidate.name}\n", encoding="ascii")
        publish_file(candidate, dist / candidate.name, identical_ok=True)
        for file in release.iterdir():
            if file.is_file():
                publish_file(file, dist / file.name)
    print(f"{dist / candidate.name} | {candidate.stat().st_size:,} bytes | SHA-256 {checksum}")


if __name__ == "__main__":
    main()
