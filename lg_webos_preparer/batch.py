"""Recursive folder batch processing and CSV/JSON reporting."""
from __future__ import annotations
import os
import csv
import json
import logging
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable
from .models import Profile, Inspection, MediaError, VIDEO_EXTENSIONS
from .analysis import inspect
from .joblog import CallbackHandler, file_log, job_logger
from .ocr import OcrConfig, OcrSession
from .repair import prepare_one, unique_destination, resolve_tool, available_tool, plan_repair
from .scanlog import format_scan

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
                   ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", seconv: str | None = None,
                   logger: logging.Logger | Callable[[str], None] | None = None,
                   progress: Callable[[int, int], None] | None = None, *,
                   debug: bool = False, tesseract: str | None = None, tessdata: str | None = None) -> list[Inspection]:
    if not isinstance(logger, logging.Logger):
        handler = CallbackHandler(logger, formatted=False) if logger is not None else None
        logger = job_logger(debug, handler)
    with ExitStack() as stack:
        try:
            input_folder = input_folder.expanduser().resolve()
            output_folder = output_folder.expanduser().resolve()
            single_video = input_folder.is_file() and input_folder.suffix.lower() in VIDEO_EXTENSIONS
            if not input_folder.is_dir() and not single_video:
                raise MediaError("Choose an existing video file or input folder")
            source_root = input_folder.parent if single_video else input_folder
            if source_root == output_folder:
                raise MediaError("Source and destination must be different folders")
            if mode == "prepare" and input_folder.is_relative_to(output_folder):
                raise MediaError("Output folder cannot be an ancestor of input folder")
            stack.enter_context(file_log(logger, output_folder, mode))
            return _run_batch(input_folder, source_root, output_folder, single_video, profile, mode, ocr,
                              allow_sdr_video, ffmpeg, ffprobe, OcrConfig(seconv, tesseract, tessdata),
                              logger, progress)
        except Exception as exc:
            logger.error("Job failed: %s", exc)
            logger.debug("Job failure details", exc_info=True)
            raise


def _run_batch(input_path: Path, source_root: Path, output_folder: Path, single_video: bool,
               profile: Profile, mode: str, ocr: bool, allow_sdr_video: bool, ffmpeg: str, ffprobe: str,
               ocr_config: OcrConfig, logger: logging.Logger,
               progress: Callable[[int, int], None] | None) -> list[Inspection]:
    ffmpeg, ffprobe = resolve_tool(ffmpeg), resolve_tool(ffprobe)
    if not available_tool(ffprobe):
        raise MediaError("ffprobe not found: use a build with bundled FFmpeg or install it")
    if mode == "prepare" and not available_tool(ffmpeg):
        raise MediaError("ffmpeg not found: use a build with bundled FFmpeg or install it")
    videos = [input_path] if single_video else find_videos(input_path, output_folder)
    logger.info("%s | %s | %d file(s) | OCR preference: %s",
                mode.upper(), profile.title, len(videos), "on" if ocr else "off")
    logger.debug("Input: %s | Output: %s | FFprobe: %s | FFmpeg: %s", input_path, output_folder, ffprobe, ffmpeg)
    if not videos:
        logger.warning("No video files found")

    results: list[Inspection] = []
    scanned = compatible = repaired = skipped = 0
    ocr_session = OcrSession(ocr_config) if mode == "prepare" and ocr else None
    for i, path in enumerate(videos, 1):
        logger.info("[%d/%d] %s", i, len(videos), path.name)
        row = Inspection(path=str(path), profile=profile.title)
        try:
            row, data, info = inspect(path, profile, ffprobe)
            scanned += 1
            compatible += not row.problems
            plan = plan_repair(path, info, profile, ocr, allow_sdr_video)
            logger.info("%s", format_scan(row, data, info, profile, plan))
            logger.debug("FFprobe metadata for %s: %r", path.name, data)
            if mode == "prepare":
                prepare_one(path, source_root, output_folder, profile, ffmpeg=ffmpeg, ffprobe=ffprobe,
                            ocr_enabled=ocr, allow_sdr_video=allow_sdr_video, logger=logger,
                            ocr_session=ocr_session, inspection=(row, data, info), plan=plan)
                if any(not action.startswith("Copied") for action in row.action):
                    repaired += 1
                else:
                    skipped += 1
        except Exception as exc:
            row.status = "error"
            row.error = str(exc)
            logger.error("  %s: %s", path.name, exc)
            logger.debug("File failure details", exc_info=True)
        results.append(row)
        if progress:
            progress(i, len(videos))
    report_json, report_csv = save_report(results, output_folder, mode)
    logger.info("Compatibility reports: %s | %s", report_csv, report_json)
    failed = sum(r.status == "error" for r in results)
    review = sum(r.status == "needs review" for r in results)
    subtitle_failures = sum(any(w.startswith("Subtitle ") and " failed:" in w for w in r.warnings) for r in results)
    logger.info("Summary | scanned: %d/%d | compatible inputs: %d | repaired: %d | skipped repairs: %d"
                " | failed: %d | needs review: %d | subtitle failures: %d",
                scanned, len(videos), compatible, repaired, skipped, failed, review, subtitle_failures)
    return results


