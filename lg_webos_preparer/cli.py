"""CLI and GUI entry point. Pass --help to review options."""
from __future__ import annotations
import argparse
from pathlib import Path
from .__init__ import __version__ as APP_VERSION
from .models import PROFILES
from .batch import process_folder
from .ocr import OcrConfig
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
    parser.add_argument("--debug", action="store_true", help="Include debug details in the terminal and log file")
    parser.add_argument("--seconv", help="Override the automatically detected Subtitle Edit SeConv executable")
    parser.add_argument("--tesseract", help="Override the automatically detected Tesseract executable")
    parser.add_argument("--tessdata", help="Override the folder containing Tesseract's eng.traineddata")
    parser.add_argument("--ffmpeg", help="Override the automatically located FFmpeg executable")
    parser.add_argument("--ffprobe", help="Override the automatically located FFprobe executable")
    args = parser.parse_args()
    if not args.input:
        gui(debug=args.debug, ocr_config=OcrConfig(args.seconv, args.tesseract, args.tessdata))
        return 0
    if not args.output:
        parser.error("--output is required when --input is used")
    try:
        rows = process_folder(Path(args.input), Path(args.output), PROFILES[args.profile],
                              args.mode, args.ocr, args.allow_sdr_transcode,
                              args.ffmpeg, args.ffprobe, args.seconv, debug=args.debug,
                              tesseract=args.tesseract, tessdata=args.tessdata)
        return 1 if any(r.status == "error" for r in rows) else 0
    except Exception:
        return 2


