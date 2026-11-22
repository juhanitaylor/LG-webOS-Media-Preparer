"""Stage the pinned OCR payload for source runs and the Windows PyInstaller build."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "build" / "ocr-inputs"
OUTPUT = ROOT / "build" / "ocr"
ASSETS = {
    "SeConv-Windows-x64.zip": (
        "https://github.com/SubtitleEdit/subtitleedit/releases/download/v5.4.0/SeConv-Windows-x64.zip",
        "aea19664f460fcfb84e8ba8eca72419091818c6005d4e063d9950c41ea81062d",
    ),
    "Tesseract553.zip": (
        "https://github.com/SubtitleEdit/support-files/releases/download/tesseract553/Tesseract553.zip",
        "fef2dbb1de8f25d660301c17aff107c0d9b0dc99e0d4f0eee938eb7238d7d2dc",
    ),
    "eng.traineddata": (
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/eng.traineddata",
        "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    ),
}
NOTICE_URLS = {
    "Tesseract-LICENSE.txt": "https://raw.githubusercontent.com/tesseract-ocr/tesseract/5.5.3/LICENSE",
    "tessdata_fast-LICENSE.txt": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/LICENSE",
    "dotnet-10.0.14-LICENSE.txt": "https://raw.githubusercontent.com/dotnet/runtime/v10.0.14/LICENSE.TXT",
    "dotnet-10.0.14-ThirdPartyNotices.txt":
        "https://raw.githubusercontent.com/dotnet/runtime/v10.0.14/THIRD-PARTY-NOTICES.TXT",
}


def fetch(url: str, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as pending:
        partial = Path(pending.name)
        try:
            with urlopen(url, timeout=90) as download:
                shutil.copyfileobj(download, pending)
        except BaseException:
            pending.close()
            partial.unlink()
            raise
    partial.replace(destination)


def verified_asset(name: str, url: str, expected: str) -> Path:
    path = INPUTS / name
    if not path.is_file():
        fetch(url, path)
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path}. Expected {expected}, got {actual}.")
    return path


def stage() -> None:
    if (ROOT / "build").resolve() != ROOT / "build":
        raise ValueError("The build directory must resolve inside the repository")
    INPUTS.mkdir(parents=True, exist_ok=True)
    assets = {name: verified_asset(name, *asset) for name, asset in ASSETS.items()}
    with tempfile.TemporaryDirectory(dir=OUTPUT.parent, prefix="ocr-stage-") as temp:
        payload = Path(temp)
        for name, subdir in (("SeConv-Windows-x64.zip", "seconv"), ("Tesseract553.zip", "tesseract")):
            with ZipFile(assets[name]) as archive:
                archive.extractall(payload / subdir)
        shutil.copyfile(assets["eng.traineddata"], payload / "tesseract" / "tessdata" / "eng.traineddata")
        notices = payload / "notices"
        notices.mkdir()
        for name, url in NOTICE_URLS.items():
            cached = INPUTS / name
            if not cached.is_file():
                fetch(url, cached)
            shutil.copyfile(cached, notices / name)
        shutil.copyfile(ROOT / "docs" / "OCR_THIRD_PARTY.md", notices / "OCR_THIRD_PARTY.md")
        provenance = {name: {"url": url, "sha256": digest} for name, (url, digest) in ASSETS.items()}
        (notices / "ocr-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        if not (payload / "seconv" / "seconv.exe").is_file() or not (payload / "tesseract" / "tesseract.exe").is_file():
            raise ValueError("The pinned archives did not produce the expected OCR layout")
        # Refresh the exact payload, without retaining files from an older version.
        if OUTPUT.exists():
            if OUTPUT.resolve() != OUTPUT or OUTPUT.is_symlink() or getattr(OUTPUT, "is_junction", lambda: False)():
                raise ValueError(f"Unexpected OCR staging directory: {OUTPUT}")
            shutil.rmtree(OUTPUT)
        shutil.copytree(payload, OUTPUT)


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("This payload is for Windows x64.")
    try:
        stage()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    sys.stdout.write(f"OCR payload staged in {OUTPUT}\n")
