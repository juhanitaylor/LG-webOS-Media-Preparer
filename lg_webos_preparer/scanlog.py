"""Human-readable scan details. CSV and JSON keep the Inspection schema."""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from .analysis import audio_compatible, frame_rate, is_dolby_vision, is_english, ratio_float, stream_bitrate, stream_label
from .models import BITMAP_SUBS, TEXT_SUBS, Inspection, Profile

if TYPE_CHECKING:
    from .repair import RepairPlan


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size:,} B"
    value = float(size)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024
        if value < 1024 or unit == "TiB":
            return f"{value:.2f} {unit} ({size:,} bytes)"
    raise AssertionError("Missing file size unit")


def bit_depth(video: dict) -> str:
    bits = ratio_float(video.get("bits_per_raw_sample")) or ratio_float(video.get("bits_per_sample"))
    if bits > 0:
        return f"{bits:g}-bit"
    pixel_format = str(video.get("pix_fmt", ""))
    depth = re.search(r"(?:p|gray)(9|10|12|14|16)(?:le|be)$", pixel_format)
    if not depth:
        depth = re.search(r"^[py][024](10|12|16)(?:le|be)$", pixel_format)
    if depth:
        return f"{depth[1]}-bit"
    if pixel_format in {"yuv420p", "yuv422p", "yuv444p", "yuvj420p", "yuvj422p", "yuvj444p",
                        "nv12", "nv21", "rgb24", "bgr24", "gray"}:
        return "8-bit"
    return "unknown"


def hdr_format(video: dict) -> str:
    transfer = str(video.get("color_transfer", "")).lower()
    metadata = " ".join(
        str(entry.get("side_data_type", "")) for entry in video.get("side_data_list") or []
    ).lower()
    if is_dolby_vision(video):
        return "Dolby Vision"
    if "hdr10+" in metadata or "smpte2094-40" in metadata:
        return "HDR10+"
    if transfer == "smpte2084":
        return "HDR10 / PQ" if video.get("color_primaries") == "bt2020" else "PQ (SMPTE ST 2084)"
    if transfer == "arib-std-b67":
        return "HLG"
    if transfer in {"", "unknown", "unspecified", "reserved"}:
        return "unknown (no HDR signalled)"
    return f"SDR ({transfer})"


def bitrate(stream: dict) -> str:
    rate, from_tag = stream_bitrate(stream)
    if rate > 0:
        return f"{rate / 1000:,.1f} kb/s" + (" (track tag)" if from_tag else "")
    return "unknown"


def _flag(stream: dict, name: str) -> str:
    value = (stream.get("disposition") or {}).get(name)
    return "yes" if value == 1 else "no" if value == 0 else "unknown"


def format_scan(row: Inspection, data: dict, info: dict, profile: Profile, plan: RepairPlan) -> str:
    path = Path(row.path)
    container = data.get("format") or {}
    video = info["video"]
    fps = frame_rate(video)
    video_bitrate = bitrate(video)
    container_rate = ratio_float(container.get("bit_rate"))
    if video_bitrate == "unknown" and container_rate > 0:
        video_bitrate = f"unknown ({container_rate / 1000:,.1f} kb/s whole-file estimate)"
    lines = [
        f"Scan results for {path.name}",
        f"  File: {path} | {format_size(path.stat().st_size)}",
        f"  Container: {container.get('format_long_name') or container.get('format_name') or 'unknown'}",
        f"  LG profile: {profile.title} ({profile.key})",
        "  Video",
        f"    {stream_label(video)} | {video.get('width', '?')}x{video.get('height', '?')}"
        f" | {f'{fps:.3f} fps' if fps > 0 else 'frame rate unknown'} | {bit_depth(video)}"
        f" | {hdr_format(video)} | {video_bitrate}",
        f"  Audio tracks ({len(info['audios'])})",
    ]
    for audio in info["audios"]:
        assessment = "compatible" if audio_compatible(audio, profile) else "outside profile"
        lines.append(f"    {stream_label(audio)} | {audio.get('channels') or '?'} channels"
                     f" | {bitrate(audio)} | default: {_flag(audio, 'default')} | {assessment}")
    if not info["audios"]:
        lines.append("    None detected")
    lines.append(f"  Subtitle tracks ({len(info['subs'])})")
    for subtitle in info["subs"]:
        codec = subtitle.get("codec_name")
        kind = "text" if codec in TEXT_SUBS else "bitmap" if codec in BITMAP_SUBS else "unverified format"
        lines.append(f"    {stream_label(subtitle)} | {kind} | default: {_flag(subtitle, 'default')}"
                     f" | forced: {_flag(subtitle, 'forced')}")
    if not info["subs"]:
        lines.append("    None detected")

    selected = info["audio"]
    if selected is None:
        audio_result = "no audio track found"
    elif info["audio_convert"]:
        audio_result = f"{stream_label(selected)} needs a compatible {profile.preferred_audio.upper()} fallback"
    else:
        audio_result = f"{stream_label(selected)} compatible" + ("" if is_english(selected) else " (no English audio tagged)")
    subtitles = {
        "external": f"use matching external SRT {info['external_subtitle'].name}" if info["external_subtitle"] else "",
        "text": "selected embedded text can be extracted to SRT",
        "ocr": "selected bitmap requires OCR for a compatible sidecar",
        "ocr_disabled": "selected bitmap requires OCR (off for this job)",
        "none": "no usable tagged English subtitle or matching SRT",
    }
    video_result = ("outside profile" if info["video_problems"] else "compatible with warnings"
                    if info["video_warnings"] else "within profile")
    lines.extend(("  Compatibility", f"    Video: {video_result}", f"    Audio: {audio_result}",
                  f"    Subtitles: {subtitles[plan.subtitle]}"))
    if info["subtitle"] and plan.subtitle != "external":
        lines.append(f"    Selected subtitle: {stream_label(info['subtitle'])}")
    for heading, messages in (("Problems", row.problems), ("Warnings", row.warnings),
                              ("Recommended actions", plan.recommendations)):
        lines.append(f"  {heading}")
        lines.extend(f"    {message}" for message in (messages or ["None"]))
    return "\n".join(lines)
