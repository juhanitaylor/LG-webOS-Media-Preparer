"""Derive the portable Windows executable name from the application version."""

from pathlib import Path
from runpy import run_path

root = Path(__file__).resolve().parents[1]
VERSION = run_path(str(root / "lg_webos_preparer" / "__init__.py"))["__version__"]
EXE_NAME = f"LG_webOS_Media_Preparer_v{VERSION}.exe"

if __name__ == "__main__":
    print(EXE_NAME)
