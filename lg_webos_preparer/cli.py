"""CLI and GUI entry point. Pass --help to review options."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .__init__ import __version__ as APP_VERSION
from .models import PROFILES
from .batch import process_folder
from .repair import resolve_tool, available_tool
from .gui import gui

def main() -> int:
    parser = argparse.ArgumentParser(description="LG webOS Media Preparer: scan or prepare video folders")
    parser.add_argument("--version", action="version", version=APP_VERSION)
    parser.add_argument("--input", help="Video file or folder; omitted launches the GUI")
    parser.add_argument("--output", help="Folder for videos and reports")
    parser.add_argument("--profile", choices=PROFILES, default="bx")
    parser.add_argument("--mode", choices=["scan", "prepare"], default="scan")
    parser.add_argument("--ocr", action="store_true", help="OCR bitmap English subtitles with seconv + Tesseract")
    parser.add_argument("--allow-sdr-transcode", action="store_true", help="Allow H.264 encode for legacy profile SDR videos")
    parser.add_argument("--seconv", default="seconv", help="Path to Subtitle Edit's seconv executable")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    if not args.input:
        gui()
        return 0
    if not args.output:
        parser.error("--output is required when --input is used")
    try:
        rows = process_folder(Path(args.input), Path(args.output), PROFILES[args.profile],
                              args.mode, args.ocr, args.allow_sdr_transcode,
                              args.ffmpeg, args.ffprobe, args.seconv)
        return 1 if any(r.status == "error" for r in rows) else 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


