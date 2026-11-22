"""Recursive folder batch processing and CSV/JSON reporting."""
from __future__ import annotations
import os
import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable
from .models import Profile, PROFILES, Inspection, MediaError, VIDEO_EXTENSIONS
from .analysis import inspect
from .repair import prepare_one, unique_destination, resolve_tool, available_tool

def find_videos(folder: Path, output_root: Path | None = None) -> list[Path]:
    found: list[Path] = []
    for root, dirs, files in os.walk(folder):
        r = Path(root)
        # Ignore output folder if nested anywhere below input.
        if output_root is not None:
            dirs[:] = [d for d in dirs if (r / d).resolve() != output_root.resolve()]
        for name in files:
            p = r / name
            if p.suffix.lower() in VIDEO_EXTENSIONS and not p.name.startswith(".") and ".partial" not in p.name:
                found.append(p)
    return sorted(found, key=lambda p: str(p).lower())


def save_report(rows: list[Inspection], folder: Path, mode: str) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"lg_media_{mode}_{timestamp}"
    output_json = unique_destination(folder / (stem + ".json"))
    output_csv = unique_destination(folder / (stem + ".csv"))
    output_json.write_text(json.dumps([asdict(r) for r in rows], ensure_ascii=False, indent=2), encoding="utf-8")
    with output_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(Inspection.__dataclass_fields__))
        writer.writeheader()
        for row in rows:
            d = asdict(row)
            for k, v in d.items():
                if isinstance(v, list):
                    d[k] = " | ".join(v)
            writer.writerow(d)
    return output_json, output_csv


def process_folder(input_folder: Path, output_folder: Path, profile: Profile,
                   mode: str, ocr: bool = False, allow_sdr_video: bool = False,
                   ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", seconv: str = "seconv",
                   logger: Callable[[str], None] = print,
                   progress: Callable[[int, int], None] | None = None) -> list[Inspection]:
    input_folder = input_folder.expanduser().resolve()
    output_folder = output_folder.expanduser().resolve()
    single_video = input_folder.is_file() and input_folder.suffix.lower() in VIDEO_EXTENSIONS
    if not input_folder.is_dir() and not single_video:
        raise MediaError("Choose an existing video file or input folder")
    source_root = input_folder.parent if single_video else input_folder
    if source_root == output_folder:
        raise MediaError("Source and destination must be different folders")
    # Resolve once so bundled executables are used for every subprocess.
    ffmpeg, ffprobe = resolve_tool(ffmpeg), resolve_tool(ffprobe)
    if not available_tool(ffprobe):
        raise MediaError("ffprobe not found: use a build with bundled FFmpeg or install it")
    if mode == "prepare" and not available_tool(ffmpeg):
        raise MediaError("ffmpeg not found: use a build with bundled FFmpeg or install it")
    if mode == "prepare" and input_folder.is_relative_to(output_folder):
        raise MediaError("Output folder cannot be an ancestor of input folder")
    videos = [input_folder] if single_video else find_videos(input_folder, output_folder)
    if not videos:
        logger("No video files found")
    logger(f"{mode.upper()} | profile: {profile.title} | {len(videos)} file(s)")
    results: list[Inspection] = []
    for i, path in enumerate(videos, 1):
        logger(f"[{i}/{len(videos)}] {path.name}")
        try:
            if mode == "scan":
                row, _, _ = inspect(path, profile, ffprobe)
                logger(f"  {len(row.problems)} issue(s), {len(row.warnings)} warning(s)")
            else:
                row = prepare_one(path, source_root, output_folder, profile,
                                  ffmpeg=ffmpeg, ffprobe=ffprobe, ocr_enabled=ocr,
                                  seconv=seconv, allow_sdr_video=allow_sdr_video, log=logger)
            results.append(row)
        except Exception as exc:
            logger(f"  ERROR: {exc}")
            results.append(Inspection(path=str(path), profile=profile.title,
                                      status="error", error=str(exc)))
        if progress:
            progress(i, len(videos))
    reports = save_report(results, output_folder, mode)
    logger(f"Reports saved to: {reports[1]}")
    logger(f"Finished. {sum(r.status == 'error' for r in results)} error(s); "
           f"{sum(r.status == 'needs review' for r in results)} requiring review")
    return results


