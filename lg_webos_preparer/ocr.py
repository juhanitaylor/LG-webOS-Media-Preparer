"""Offline OCR for one verified English bitmap subtitle track."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .analysis import is_english, lang, probe, ratio_float, stream_label
from .models import MediaError
from .processes import cmd_run, run_ffmpeg, stream_command


@dataclass(frozen=True)
class OcrConfig:
    seconv: str | None = None
    tesseract: str | None = None
    tessdata: str | None = None


@dataclass(frozen=True)
class OcrTools:
    seconv: str
    tesseract: str
    env: dict[str, str]


def _resolve_executable(tool: str, override: str | None, roots: list[Path], frozen: bool) -> Path:
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        found = shutil.which(override)
        if found:
            return Path(found).resolve()
        raise MediaError(f"OCR executable override for {tool} was not found: {override}")

    for root in roots:
        for filename in (f"{tool}.exe", tool):
            candidate = root / tool / filename
            if candidate.is_file():
                return candidate.resolve()
    if not frozen:
        found = shutil.which(tool)
        if found:
            return Path(found).resolve()
    raise MediaError(f"OCR component {tool} is missing from the {'application bundle' if frozen else 'staged tools and PATH'}")


def discover_ocr(config: OcrConfig = OcrConfig()) -> OcrTools:
    extraction = getattr(sys, "_MEIPASS", None)
    frozen = bool(extraction or getattr(sys, "frozen", False))
    roots = [Path(extraction) / "tools" / "ocr"] if extraction else []
    if frozen:
        roots.append(Path(sys.executable).resolve().parent / "tools" / "ocr")
    else:
        source_root = Path(__file__).resolve().parents[1]
        roots.extend((source_root / "build" / "windows-payload" / "tools" / "ocr",
                      source_root / "tools" / "ocr", source_root / "build" / "ocr"))
    seconv = _resolve_executable("seconv", config.seconv, roots, frozen)
    tesseract = _resolve_executable("tesseract", config.tesseract, roots, frozen)
    if tesseract.name.lower() not in {"tesseract", "tesseract.exe"}:
        raise MediaError("The Tesseract executable must be named tesseract or tesseract.exe for SeConv to find it")

    env = os.environ.copy()
    env["PATH"] = str(tesseract.parent) + os.pathsep + env.get("PATH", "")
    nearby_data = tesseract.parent / "tessdata"
    data = Path(config.tessdata).expanduser() if config.tessdata else None
    if data is None and (nearby_data / "eng.traineddata").is_file():
        data = nearby_data
    if data is None and frozen and not config.tesseract:
        raise MediaError(f"Bundled English OCR model is missing: {nearby_data / 'eng.traineddata'}")
    if data is not None:
        if not (data / "eng.traineddata").is_file():
            raise MediaError(f"English OCR model not found in {data}")
        env["TESSDATA_PREFIX"] = str(data.resolve())
    return OcrTools(str(seconv), str(tesseract), env)


class OcrSession:
    """Check the dependencies once, when a job encounters an eligible track."""

    def __init__(self, config: OcrConfig):
        self.config = config
        self.tools: OcrTools | None = None
        self.error: str | None = None

    def checked_tools(self, logger: logging.Logger) -> OcrTools:
        if self.error:
            raise MediaError(self.error)
        if self.tools is None:
            try:
                tools = discover_ocr(self.config)
                logger.debug("  OCR tools: %s | %s | tessdata=%s",
                             tools.seconv, tools.tesseract, tools.env.get("TESSDATA_PREFIX", "system default"))
                seconv_version, tesseract_version = check_capabilities(tools)
            except MediaError as exc:
                self.error = str(exc)
                raise
            self.tools = tools
            logger.info("  OCR runtime ready: %s | %s | English model loaded", seconv_version, tesseract_version)
        return self.tools


def check_capabilities(tools: OcrTools) -> tuple[str, str]:
    seconv_help = cmd_run([tools.seconv, "--help-json"], env=tools.env, timeout=20).stdout
    if any(option not in seconv_help for option in ("--ocr-engine", "--ocr-language", "--time-codes-only",
                                                     "--output-filename")):
        raise MediaError("SeConv does not advertise the required OCR and timing options")
    engines = cmd_run([tools.seconv, "list-ocr-engines", "--json"], env=tools.env, timeout=20).stdout
    try:
        ready = any(engine.get("id") == "tesseract" and engine.get("ready") is True
                    for engine in json.loads(engines)["engines"])
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise MediaError("SeConv did not return a valid OCR-engine capability list") from exc
    if not ready:
        raise MediaError("SeConv did not find a usable Tesseract engine")
    tesseract_version = cmd_run([tools.tesseract, "--version"], env=tools.env, timeout=15).stdout
    if not tesseract_version.lower().startswith("tesseract "):
        raise MediaError("The selected Tesseract executable did not return a Tesseract version")
    languages = cmd_run([tools.tesseract, "--list-langs"], env=tools.env, timeout=15).stdout
    if "eng" not in languages.splitlines():
        raise MediaError("Tesseract did not list an English language model (eng)")
    with tempfile.TemporaryDirectory(prefix="lg_ocr_check_") as temp:
        # Listing languages only checks filenames. Starting OCR also checks the model can load.
        image = Path(temp) / "model-check.pgm"
        image.write_bytes(b"P5\n128 64\n255\n" + b"\xff" * (128 * 64))
        cmd_run([tools.tesseract, str(image), "stdout", "-l", "eng", "--psm", "7"],
                env=tools.env, timeout=20)
    seconv_version = cmd_run([tools.seconv, "--version"], env=tools.env, timeout=15).stdout.strip()
    return f"SeConv {seconv_version}", tesseract_version.splitlines()[0]


_TIME = r"(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})"
_RANGE = re.compile(rf"{_TIME}\s+-->\s+{_TIME}")
_MARKUP = re.compile(r"<[^>]*>|\{\\[^}]*\}")


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str


def read_cues(path: Path) -> list[Cue]:
    try:
        contents = path.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError) as exc:
        raise MediaError(f"Could not read {path.name}: {exc}") from exc
    if not contents:
        raise MediaError(f"{path.name} contains no cues")
    if "\x00" in contents:
        raise MediaError(f"{path.name} contains a NUL character")
    cues: list[Cue] = []

    def milliseconds(parts: tuple[str, ...]) -> int:
        hours, minutes, seconds, fraction = map(int, parts)
        return ((hours * 60 + minutes) * 60 + seconds) * 1000 + fraction

    for number, block in enumerate(re.split(r"\n(?:[ \t]*\n)+", contents), 1):
        lines = block.splitlines()
        timing = _RANGE.fullmatch(lines[1].strip()) if len(lines) >= 2 else None
        if not lines or not lines[0].strip().isascii() or not lines[0].strip().isdigit() or not timing:
            raise MediaError(f"{path.name} has malformed SRT cue {number}")
        start, end = milliseconds(timing.groups()[:4]), milliseconds(timing.groups()[4:])
        if end <= start or (cues and start < cues[-1].start_ms):
            raise MediaError(f"{path.name} has invalid or out-of-order timing at cue {number}")
        cues.append(Cue(start, end, "\n".join(lines[2:])))
    return cues


def validate_ocr(output: Path, timing: Path) -> tuple[int, int]:
    cues, baseline = read_cues(output), read_cues(timing)
    if len(cues) != len(baseline):
        raise MediaError(f"OCR produced {len(cues)} cues for {len(baseline)} bitmap cues")
    questionable = 0
    readable = 0
    for number, (cue, reference) in enumerate(zip(cues, baseline, strict=True), 1):
        if abs(cue.start_ms - reference.start_ms) > 2 or abs(cue.end_ms - reference.end_ms) > 2:
            raise MediaError(f"OCR changed the bitmap timing at cue {number}")
        text = _MARKUP.sub("", cue.text).strip()
        meaningful = any(char.isalnum() for char in text)
        readable += meaningful
        questionable += not meaningful or "\ufffd" in text or bool(re.search(r"[?*]{2,}", text))
    if not readable:
        raise MediaError("OCR produced no readable cue text")
    return len(cues), questionable


def _packets(path: Path, stream: int, ffprobe: str) -> list[float]:
    result = cmd_run([ffprobe, "-v", "error", "-select_streams", str(stream), "-show_packets",
                      "-show_entries", "packet=pts_time", "-of", "json", str(path)])
    try:
        packets = [float(packet["pts_time"]) for packet in json.loads(result.stdout)["packets"]]
    except (ValueError, KeyError, TypeError) as exc:
        raise MediaError(f"Could not verify bitmap packet timestamps in {path.name}") from exc
    if not packets or not all(map(math.isfinite, packets)):
        raise MediaError(f"No usable bitmap packet timestamps in {path.name}")
    return packets


def _convert(tools: OcrTools, source: Path, output: str, options: list[str], logger: logging.Logger,
             label: str) -> None:
    def update(line: str) -> None:
        if re.search(r"\bOCR\s+\d+\s*/\s*\d+", line, re.IGNORECASE):
            logger.info("  %s", line)
        elif re.search(r"\b(warning|error|failed)\b", line, re.IGNORECASE):
            logger.warning("  %s: %s", label, line)
        else:
            logger.debug("  %s: %s", label, line)

    # ASCII filenames relative to the private working directory avoid SeConv's input glob syntax.
    stream_command([tools.seconv, source.name, "subrip", "--encoding:utf-8",
                    f"--output-filename:{output}", *options], logger, update, cwd=source.parent,
                   label=label, env=tools.env, timeout=3600)


def ocr_subtitle(video: Path, metadata: dict, source_subtitles: list[dict], selected: dict,
                 workspace: Path, session: OcrSession, ffmpeg: str, ffprobe: str,
                 logger: logging.Logger) -> tuple[Path, int, int]:
    output_subtitles = [stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "subtitle"]
    ordinal = source_subtitles.index(selected)
    if len(output_subtitles) != len(source_subtitles):
        raise MediaError("Prepared subtitle tracks could not be matched to the source")
    track = output_subtitles[ordinal]
    codec = selected.get("codec_name")
    if track.get("codec_name") != codec or not is_english(track):
        raise MediaError(f"Selected bitmap codec or English language changed in prepared track #{track.get('index')}")
    formats = {"hdmv_pgs_subtitle": ("matroska", "mkv"), "dvd_subtitle": ("matroska", "mkv"),
               "dvb_subtitle": ("mpegts", "ts"), "xsub": ("avi", "avi")}
    if codec not in formats:
        raise MediaError(f"No verified extraction path for bitmap codec {codec}")

    tools = session.checked_tools(logger)
    container, extension = formats[codec]
    isolated = workspace / f"bitmap.{extension}"
    logger.info("  OCR: isolating prepared track %s for English recognition", stream_label(track))
    run_ffmpeg(["-copyts", "-start_at_zero", "-i", str(video), "-map", f"0:{track['index']}", "-c:s", "copy",
                "-map_chapters", "-1", "-metadata:s:s:0", f"language={lang(track)}",
                "-avoid_negative_ts", "disabled", "-f", container, str(isolated)],
               ffmpeg, logger=logger, operation="FFmpeg bitmap extraction")
    isolated_streams = probe(isolated, ffprobe).get("streams", [])
    if len(isolated_streams) != 1 or isolated_streams[0].get("codec_name") != codec:
        raise MediaError("The isolated file did not contain exactly the selected bitmap codec")
    original_pts = _packets(video, track["index"], ffprobe)
    isolated_pts = _packets(isolated, isolated_streams[0]["index"], ffprobe)
    origin = ratio_float(metadata.get("format", {}).get("start_time"))
    if len(original_pts) != len(isolated_pts) or any(
        abs((before - origin) - after) > 0.002 for before, after in zip(original_pts, isolated_pts)
    ):
        raise MediaError("Bitmap extraction changed packet timestamps relative to the prepared video")
    logger.info("  OCR: verified %d bitmap packet timestamps against the prepared video", len(original_pts))

    _convert(tools, isolated, "timing.srt", ["--time-codes-only"], logger, "Bitmap timing reference")
    timing = workspace / "timing.srt"
    if read_cues(timing)[0].start_ms + 20 < min(isolated_pts) * 1000:
        raise MediaError("The converter moved a bitmap cue before the first subtitle packet")
    logger.info("  OCR: recognising English text with Tesseract")
    _convert(tools, isolated, "recognised.srt", ["--ocr-engine:tesseract", "--ocr-language:eng"], logger, "SeConv OCR")
    output = workspace / "recognised.srt"
    count, questionable = validate_ocr(output, timing)
    return output, count, questionable
