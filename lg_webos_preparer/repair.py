"""Conservative remux, audio fallback, external text subtitles, optional OCR.

Inputs are never overwritten. Video conversion is opt-in, SDR only, legacy profile.
"""
from __future__ import annotations
import os
import logging
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .models import Profile, Inspection, MediaError, TEXT_SUBS, BITMAP_SUBS
from .analysis import audio_compatible, frame_rate, inspect, is_hdr, lang, probe, ratio_float, srt_valid, stream_label
from .joblog import CallbackHandler, job_logger
from .ocr import OcrConfig, OcrSession, ocr_subtitle
from .processes import run_ffmpeg
from .scanlog import format_size

def resolve_tool(name: str) -> str:
    """Find a bundled PyInstaller tool before any installed executable.

    In --onefile builds, sys._MEIPASS is the temporary extraction directory;
    in --onedir builds, it is the application data directory. Both should
    contain tools/ffmpeg.exe and tools/ffprobe.exe.
    """
    supplied = Path(name)
    if supplied.is_file():
        return str(supplied.resolve())
    # Do not silently replace an explicitly supplied missing path.
    if supplied.parent != Path("."):
        return name
    executable = name if name.lower().endswith(".exe") else name + ".exe"
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "tools" / executable
        if candidate.is_file():
            return str(candidate)
    # Also permit running a portable --onedir folder without PyInstaller.
    nearby = Path(sys.executable).resolve().parent / "tools" / executable
    if nearby.is_file():
        return str(nearby)
    return shutil.which(name) or name


def available_tool(name: str) -> bool:
    found = resolve_tool(name)
    return bool(Path(found).is_file() or shutil.which(found))


def remux(input_file: Path, dest: Path, info: dict, profile: Profile, *, convert_video: bool,
          ffmpeg: str, ffprobe: str, data: dict | None = None, logger: logging.Logger | None = None) -> None:
    """Safe streams-only remux with a fresh compatible audio track if required.

    With convert_video=True, only SDR material is encoded to H.264. HDR sources
    never undergo automatic SDR conversion (would need controlled tone mapping).
    """
    v = info["video"]
    audio = info["audio"]
    new_audio = info["audio_convert"] and audio is not None
    audio_streams = info["audios"]
    subs = info["subs"]
    data = data if data is not None else probe(input_file, ffprobe)
    attachments = [s for s in data.get("streams", []) if s.get("codec_type") == "attachment"]
    maps = ["-map", f"0:{v['index']}"]
    if new_audio:
        maps += ["-map", f"0:{audio['index']}"]
    for a in audio_streams:
        maps += ["-map", f"0:{a['index']}"]
    for s in subs:
        maps += ["-map", f"0:{s['index']}"]
    for a in attachments:
        maps += ["-map", f"0:{a['index']}"]
    args = ["-i", str(input_file), *maps, "-map_metadata", "0", "-map_chapters", "0",
            "-c:v:0", "libx264" if convert_video else "copy"]
    if attachments:
        args += ["-c:t", "copy"]
    for index in range(len(audio_streams)):
        args += [f"-c:a:{index + int(new_audio)}", "copy"]
    # The MP4 timed-text codec cannot be copied into MKV: transcode just that
    # subtitle track to SubRip, leaving all video/audio bits untouched.
    for sub_index, stream in enumerate(subs):
        args += [f"-c:s:{sub_index}", "srt" if stream.get("codec_name") == "mov_text" else "copy"]
    if convert_video:
        args += ["-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                 "-vf", "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                 ]
        if frame_rate(v) > profile.max_fps + 0.3:
            args += ["-r", str(int(profile.max_fps))]
    if new_audio:
        count = min(int(audio.get("channels") or 2), profile.preferred_channels)
        codec = profile.preferred_audio
        args += ["-c:a:0", codec, "-ac:a:0", str(count), "-ar:a:0", "48000",
                 "-b:a:0", ("640k" if codec == "ac3" and count > 2 else "192k" if codec == "ac3" else "192k")]
        args += ["-metadata:s:a:0", f"language={lang(audio)}",
                 "-metadata:s:a:0", f"title=LG compatible {codec.upper()} {count}ch"]
    # Assign exactly one default audio. Keep original tracks for non-LG playback.
    for index in range(len(audio_streams) + int(new_audio)):
        args += [f"-disposition:a:{index}", "default" if ((new_audio and index == 0) or (not new_audio and audio_streams[index].get("index") == audio.get("index"))) else "0"]
    args += [str(dest)]
    run_ffmpeg(args, ffmpeg, logger=logger, duration=ratio_float(data.get("format", {}).get("duration")),
               operation="FFmpeg preparation")


def extract_text_srt(source: Path, stream: dict, output: Path, ffmpeg: str,
                     logger: logging.Logger | None = None) -> None:
    run_ffmpeg(["-i", str(source), "-map", f"0:{stream['index']}", "-c:s", "srt", str(output)], ffmpeg,
               logger=logger, operation="FFmpeg text extraction")
    if not srt_valid(output):
        raise MediaError("Extracted subtitles are empty or not valid SRT")


def video_reencode_appropriate(info: dict, profile: Profile, allow: bool) -> bool:
    if not allow:
        return False
    v = info["video"]
    if is_hdr(v):
        return False
    if profile.key != "legacy":
        return False
    return (v.get("codec_name") not in profile.video_codecs
            or int(v.get("width", 0)) > profile.max_width
            or int(v.get("height", 0)) > profile.max_height
            or frame_rate(v) > profile.max_fps + 0.3)


@dataclass(frozen=True)
class RepairPlan:
    convert_video: bool
    remux_reasons: list[str]
    subtitle: str
    recommendations: list[str]


def plan_repair(source: Path, info: dict, profile: Profile, ocr: bool, allow_sdr_video: bool) -> RepairPlan:
    convertible = video_reencode_appropriate(info, profile, allow_sdr_video)
    audio = info["audio"]
    default_audio = next((a for a in info["audios"] if a.get("disposition", {}).get("default")), None)
    reasons = []
    if source.suffix.lower() not in {".mkv", ".mp4", ".m4v"}:
        reasons.append("use a preferred LG USB container")
    if info["audio_convert"]:
        reasons.append(f"add a compatible {profile.preferred_audio.upper()} audio fallback")
    elif audio is not None and audio != default_audio:
        reasons.append("set the preferred audio track as default")
    if convertible:
        reasons.append("store the legacy H.264 encode")

    recommendations = []
    if convertible:
        recommendations.append("Re-encode SDR video to H.264 for the legacy profile.")
    elif info["video_problems"]:
        if video_reencode_appropriate(info, profile, True):
            recommendations.append("Enable legacy SDR conversion to encode H.264 for this video.")
        else:
            recommendations.append("Check playback or use a compatible source for the video issues above.")
    if not convertible:
        recommendations.append("Stream-copy video during remux." if reasons else "Keep video unchanged.")
    if reasons:
        recommendations.append(f"Remux to MKV to {' and '.join(reasons)}.")
    if audio is None:
        recommendations.append("Use a source with an audio track if audio is expected.")

    selected = info["subtitle"]
    codec = selected.get("codec_name") if selected else None
    if info["external_subtitle"]:
        subtitle = "external"
        recommendations.append(f"Copy matching SRT {info['external_subtitle'].name} and check its sync.")
    elif codec in TEXT_SUBS:
        subtitle = "text"
        recommendations.append(f"Extract {stream_label(selected)} to a matching SRT.")
    elif codec in BITMAP_SUBS:
        subtitle = "ocr" if ocr else "ocr_disabled"
        recommendations.append(f"OCR {stream_label(selected)} to a matching SRT and proofread it."
                               if ocr else "Enable bitmap OCR or supply a matching English SRT.")
    else:
        subtitle = "none"
        recommendations.append("Supply a matching English SRT if subtitles are needed.")
    return RepairPlan(convertible, reasons, subtitle, recommendations)


def unique_destination(dest: Path) -> Path:
    if not dest.exists() and not dest.with_suffix(".srt").exists():
        return dest
    for n in range(2, 9999):
        attempt = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        if not attempt.exists() and not attempt.with_suffix(".srt").exists():
            return attempt
    raise MediaError(f"Too many existing output files for {dest.name}")


def prepare_one(source: Path, input_root: Path, output_root: Path, profile: Profile, *,
                ffmpeg: str, ffprobe: str, ocr_enabled: bool, seconv: str | None = None,
                allow_sdr_video: bool, log: Callable[[str], None] | None = None,
                logger: logging.Logger | None = None, ocr_session: OcrSession | None = None,
                inspection: tuple[Inspection, dict, dict] | None = None,
                plan: RepairPlan | None = None) -> Inspection:
    if logger is None:
        logger = job_logger(handler=CallbackHandler(log, formatted=False) if log is not None else None)
    row, data, info = inspection if inspection is not None else inspect(source, profile, ffprobe)
    plan = plan if plan is not None else plan_repair(source, info, profile, ocr_enabled, allow_sdr_video)
    initial_warnings = len(row.warnings)

    rel = source.relative_to(input_root)
    target_dir = output_root / rel.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    estimated_required = int(source.stat().st_size * 1.04) + 16 * 1024 * 1024
    if shutil.disk_usage(target_dir).free < estimated_required:
        raise MediaError(f"Not enough free space in output location: need roughly {estimated_required / 1024**3:.2f} GiB")

    unsupported_video = bool(info["video_problems"]) and not plan.convert_video
    if unsupported_video:
        row.warnings.append("Video remains outside the selected profile. Check playback before use.")
    if info["audio"]:
        logger.info("  Selected audio: %s | %s", stream_label(info["audio"]),
                    f"create {profile.preferred_audio.upper()} fallback with up to {profile.preferred_channels} channels"
                    if info["audio_convert"] else "keep existing track as default")
    else:
        logger.info("  Audio repair skipped: no audio track found")
    if plan.subtitle == "external":
        logger.info("  Selected subtitle: matching external SRT %s", info["external_subtitle"])
    elif info["subtitle"]:
        logger.info("  Selected subtitle: %s", stream_label(info["subtitle"]))

    make_mkv = bool(plan.remux_reasons)
    suggested = source.with_suffix(".mkv").name if make_mkv else source.name
    dest = unique_destination(target_dir / suggested)
    subtitle_dst = dest.with_suffix(".srt")
    partial = target_dir / (dest.name + (".partial.mkv" if make_mkv else ".partial"))
    if partial.exists():
        raise MediaError(f"Previous partial output exists: {partial}. Remove manually if unneeded")

    try:
        if make_mkv:
            logger.info("  Remuxing to MKV to %s", " and ".join(plan.remux_reasons))
            logger.info("  %s. Mapping %d original audio and %d original subtitle track(s).",
                        "Re-encoding SDR video to H.264" if plan.convert_video else "Stream-copying video",
                        len(info["audios"]), len(info["subs"]))
            for subtitle in info["subs"]:
                if subtitle.get("codec_name") == "mov_text":
                    logger.info("  Converting subtitle %s to SubRip for the MKV container", stream_label(subtitle))
            remux(source, partial, info, profile, convert_video=plan.convert_video,
                  ffmpeg=ffmpeg, ffprobe=ffprobe, data=data, logger=logger)
        else:
            logger.info("  Copying file unchanged. Container, video and default audio already match the repair plan.")
            shutil.copy2(source, partial)
            if partial.stat().st_size != source.stat().st_size:
                raise MediaError("Verification failed: copied file size mismatch")

        verified = probe(partial, ffprobe)
        streams = verified.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"
                      and not s.get("disposition", {}).get("attached_pic")), None)
        if video is None:
            raise MediaError("Verification failed: output video stream missing")
        expected_codec = "h264" if plan.convert_video else info["video"].get("codec_name")
        if video.get("codec_name") != expected_codec:
            raise MediaError(f"Verification failed: expected video codec {expected_codec}")
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        if info["audio_convert"] and (not audios or audios[0].get("codec_name") != profile.preferred_audio):
            raise MediaError("Verification failed: compatible audio was not created")
        default_audio = next((s for s in audios if s.get("disposition", {}).get("default")
                              and audio_compatible(s, profile)), None)
        if info["audio"] and default_audio is None:
            raise MediaError("Verification failed: a compatible audio track was not selected as default")
        logger.info("  FFprobe verification passed | video: %s | default audio: %s | audio tracks: %d | subtitle tracks: %d",
                    stream_label(video), stream_label(default_audio) if default_audio else "none",
                    len(audios), sum(s.get("codec_type") == "subtitle" for s in streams))
        os.replace(partial, dest)
    finally:
        if partial.exists():
            partial.unlink()

    if info["audio_convert"]:
        row.action.append(f"Added {profile.preferred_audio.upper()} track and kept original audio")
    if plan.convert_video:
        row.action.append("Encoded SDR video to H.264 for legacy profile")
    if make_mkv and not row.action:
        row.action.append("Remuxed container / selected compatible audio as default")
    if not make_mkv:
        row.action.append("Copied original video unchanged")
    row.output = str(dest)
    logger.info("  Video output: %s | %s", dest, format_size(dest.stat().st_size))

    with tempfile.TemporaryDirectory(prefix="lg_media_") as workspace:
        tmp = Path(workspace)
        sidecar = None
        action = ""
        label = "preparation"
        try:
            if plan.subtitle == "external":
                logger.info("  Copying the matching external SRT")
                sidecar = info["external_subtitle"]
                action = "Copied existing external SRT"
            elif plan.subtitle == "text":
                label = "extraction"
                sidecar = tmp / "extracted.srt"
                logger.info("  Extracting selected embedded text to SRT")
                extract_text_srt(source, info["subtitle"], sidecar, ffmpeg, logger)
                action = "Extracted English SRT from embedded text subtitles"
            elif plan.subtitle == "ocr":
                label = "OCR"
                session = ocr_session if ocr_session is not None else OcrSession(OcrConfig(seconv=seconv))
                sidecar, count, questionable = ocr_subtitle(dest, verified, info["subs"], info["subtitle"],
                                                           tmp, session, ffmpeg, ffprobe, logger)
                action = "Converted English bitmap subtitles to SRT with OCR"
                logger.info("  OCR verification passed | %d cue(s) match the bitmap timing | %d questionable cue(s)",
                            count, questionable)
                row.warnings.append(f"OCR requires proofreading and a sync check. {questionable} of {count} cue(s) "
                                    "flagged for questionable text. Original bitmap layout may be lost.")
            elif plan.subtitle == "ocr_disabled":
                row.warnings.append("Subtitle OCR skipped: disabled for this job. Bitmap track retained in the video.")
            else:
                row.warnings.append("Subtitle preparation skipped: no usable English subtitles selected")

            if sidecar:
                with sidecar.open("rb") as original:
                    output = subtitle_dst.open("xb")
                    try:
                        with output:
                            shutil.copyfileobj(original, output)
                    except OSError:
                        subtitle_dst.unlink(missing_ok=True)
                        raise
                row.subtitle_output = str(subtitle_dst)
                row.action.append(action)
                logger.info("  SRT output: %s | %s", subtitle_dst, format_size(subtitle_dst.stat().st_size))
        except (OSError, MediaError) as exc:
            row.warnings.append(f"Subtitle {label} failed: {exc}")
            logger.debug("Subtitle failure details", exc_info=True)

    subtitles_unavailable = not row.subtitle_output
    if unsupported_video or info["audio"] is None or subtitles_unavailable or plan.subtitle == "ocr":
        row.status = "needs review"
    else:
        row.status = "prepared"
    for warning in row.warnings[initial_warnings:]:
        logger.warning("  %s", warning)
    logger.info("  %s: %s", row.status.upper(), source.name)
    return row


