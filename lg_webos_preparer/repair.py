"""Conservative remux, audio fallback, external text subtitles, optional OCR.

Inputs are never overwritten. Video conversion is opt-in, SDR only, legacy profile.
"""
from __future__ import annotations
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable
from .models import (Profile, PROFILES, MediaError, TEXT_SUBS, BITMAP_SUBS)
from .analysis import (probe, cmd_run, ratio_float, lang, is_hdr, inspect, audio_compatible, external_subtitle, srt_valid)

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


def run_ffmpeg(args: list[str], ffmpeg: str = "ffmpeg") -> None:
    cmd_run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n", *args])


def remux(input_file: Path, dest: Path, info: dict, profile: Profile, *, convert_video: bool,
          ffmpeg: str, ffprobe: str) -> None:
    """Safe streams-only remux with a fresh compatible audio track if required.

    With convert_video=True, only SDR material is encoded to H.264. HDR sources
    never undergo automatic SDR conversion (would need controlled tone mapping).
    """
    v = info["video"]
    audio = info["audio"]
    new_audio = info["audio_convert"] and audio is not None
    audio_streams = info["audios"]
    subs = info["subs"]
    data = probe(input_file, ffprobe)
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
    args = ["-i", str(input_file), *maps, "-map_metadata", "0", "-map_chapters", "0", "-c", "copy"]
    # The MP4 timed-text codec cannot be copied into MKV: transcode just that
    # subtitle track to SubRip, leaving all video/audio bits untouched.
    for sub_index, stream in enumerate(subs):
        if stream.get("codec_name") == "mov_text":
            args += [f"-c:s:{sub_index}", "srt"]
    if convert_video:
        args += ["-c:v:0", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                 "-vf", "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                 ]
        if ratio_float(v.get("avg_frame_rate")) > profile.max_fps + 0.3:
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
    # Include attached cover artwork only if present as standard video? Unusual cases are reported, not silently destroyed.
    args += [str(dest)]
    run_ffmpeg(args, ffmpeg)


def extract_text_srt(source: Path, stream: dict, output: Path, ffmpeg: str) -> None:
    run_ffmpeg(["-i", str(source), "-map", f"0:{stream['index']}", "-c:s", "srt", str(output)], ffmpeg)
    if not srt_valid(output):
        raise MediaError("Extracted subtitles are empty or not valid SRT")


def ocr_subtitle(source: Path, stream: dict, tmp_folder: Path, seconv: str) -> Path:
    """Invoke Subtitle Edit 5 seconv. OCR text should always be reviewed."""
    before = set(tmp_folder.glob("*.srt"))
    cmd_run([seconv, str(source), "subrip", f"--track-number:{stream['index']}",
             "--ocr-engine:tesseract", "--ocr-language:eng",
             f"--output-folder:{tmp_folder}", "--overwrite"])
    candidates = [p for p in tmp_folder.glob("*.srt") if p not in before and srt_valid(p)]
    if not candidates:
        raise MediaError("Subtitle Edit OCR did not produce a valid SRT; check seconv/Tesseract and track numbering")
    if len(candidates) > 1:
        english = [p for p in candidates if re.search(r"(^|[._-])(eng|en)([._-]|$)", p.stem.lower())]
        if len(english) != 1:
            raise MediaError("OCR yielded multiple subtitle tracks; unable to select one safely")
        return english[0]
    return candidates[0]


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
            or ratio_float(v.get("avg_frame_rate")) > profile.max_fps + 0.3)


def unique_destination(dest: Path) -> Path:
    if not dest.exists() and not dest.with_suffix(".srt").exists():
        return dest
    for n in range(2, 9999):
        attempt = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        if not attempt.exists() and not attempt.with_suffix(".srt").exists():
            return attempt
    raise MediaError(f"Too many existing output files for {dest.name}")


def prepare_one(source: Path, input_root: Path, output_root: Path, profile: Profile, *,
                ffmpeg: str, ffprobe: str, ocr_enabled: bool, seconv: str,
                allow_sdr_video: bool, log: Callable[[str], None]) -> Inspection:
    row, data, info = inspect(source, profile, ffprobe)
    rel = source.relative_to(input_root)
    target_dir = output_root / rel.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(target_dir).free
    estimated_required = int(source.stat().st_size * 1.04) + 16 * 1024 * 1024
    if free_bytes < estimated_required:
        raise MediaError(f"Not enough free space in output location: need roughly {estimated_required / 1024**3:.2f} GiB")
    convertible = video_reencode_appropriate(info, profile, allow_sdr_video)
    video_problems = [x for x in row.problems if x.startswith(("Video codec", "Resolution", "Frame rate", "HDR"))]
    if video_problems and not convertible:
        row.warnings.append("Video unsupported or unverified: no automatic video conversion; output may not play")
    make_mkv = info["audio_convert"] or convertible or source.suffix.lower() not in {".mkv", ".mp4", ".m4v"}
    # If a compatible audio track exists but isn't the default, remux just to select it.
    preferred = info["audio"]
    if preferred and not make_mkv:
        default_audio = next((a for a in info["audios"] if a.get("disposition", {}).get("default")), None)
        if default_audio is None or default_audio.get("index") != preferred.get("index"):
            make_mkv = True
    # Preserve all inputs, output a new video only if necessary. For straight copies, use original name.
    suggested = source.with_suffix(".mkv").name if make_mkv else source.name
    dest = unique_destination(target_dir / suggested)
    subtitle_dst = dest.with_suffix(".srt")
    with tempfile.TemporaryDirectory(prefix="lg_media_") as workspace:
        tmp = Path(workspace)
        partial = target_dir / (dest.name + ".partial.mkv") if make_mkv else target_dir / (dest.name + ".partial")
        if partial.exists():
            raise MediaError(f"Previous partial output exists: {partial}. Remove manually if unneeded")
        try:
            if make_mkv:
                remux(source, partial, info, profile, convert_video=convertible,
                      ffmpeg=ffmpeg, ffprobe=ffprobe)
                actual = probe(partial, ffprobe)
                new_v = next((x for x in actual.get("streams", []) if x.get("codec_type") == "video"), None)
                if not new_v:
                    raise MediaError("Verification failed: output video stream missing")
                if not convertible and new_v.get("codec_name") != info["video"].get("codec_name"):
                    raise MediaError("Verification failed: video codec changed unexpectedly")
                audios_out = [x for x in actual["streams"] if x.get("codec_type") == "audio"]
                if info["audio_convert"]:
                    if not audios_out or audios_out[0].get("codec_name") != profile.preferred_audio:
                        raise MediaError("Verification failed: compatible audio was not created")
                if info["audio"] and (not any(x.get("disposition", {}).get("default") and audio_compatible(x, profile)
                                               for x in audios_out)):
                    raise MediaError("Verification failed: a compatible audio track was not selected as default")
                os.replace(partial, dest)
                if info["audio_convert"]:
                    row.action.append(f"Added {profile.preferred_audio.upper()} track; kept original streams")
                elif convertible:
                    row.action.append("Encoded SDR video to H.264 for legacy profile")
                else:
                    row.action.append("Remuxed container / selected compatible audio as default")
            else:
                shutil.copy2(source, partial)
                # Verify stream metadata after copying, and ensure file size matches.
                if partial.stat().st_size != source.stat().st_size:
                    raise MediaError("Verification failed: copied file size mismatch")
                os.replace(partial, dest)
                row.action.append("Copied original video unchanged")
        finally:
            # Leave failed partial outputs for debugging? No; never leave misleading files.
            if partial.exists():
                partial.unlink()

        external = external_subtitle(source)
        chosen = info["subtitle"]
        if external:
            if srt_valid(external):
                shutil.copy2(external, subtitle_dst)
                row.subtitle_output = str(subtitle_dst)
                row.action.append("Copied existing external SRT")
            else:
                row.warnings.append("External SRT exists but could not be validated")
        elif chosen and chosen.get("codec_name") in TEXT_SUBS:
            try:
                extract_text_srt(source, chosen, subtitle_dst, ffmpeg)
                row.subtitle_output = str(subtitle_dst)
                row.action.append("Extracted English SRT from embedded text subtitles")
            except Exception as exc:
                row.warnings.append(f"Subtitle extraction failed: {exc}")
                if subtitle_dst.exists():
                    subtitle_dst.unlink()
        elif chosen and chosen.get("codec_name") in BITMAP_SUBS:
            if ocr_enabled and available_tool(seconv) and available_tool("tesseract"):
                try:
                    generated = ocr_subtitle(source, chosen, tmp, seconv)
                    shutil.copy2(generated, subtitle_dst)
                    row.subtitle_output = str(subtitle_dst)
                    row.action.append("Converted bitmap subtitles to SRT with OCR (review text and sync)")
                    row.warnings.append("OCR is not perfect: proofread subtitles; bitmap positioning/formatting is lost")
                except Exception as exc:
                    row.warnings.append(f"Subtitle OCR failed: {exc}")
            else:
                row.warnings.append("Bitmap subtitles remain unavailable; install seconv + Tesseract and enable OCR")
        else:
            row.warnings.append("No English subtitles to prepare; no subtitles created")
        row.output = str(dest)
        missing_audio = info["audio"] is None
        subtitles_unavailable = not row.subtitle_output
        unsupported_video = bool(video_problems) and not convertible
        if unsupported_video or missing_audio or subtitles_unavailable:
            row.status = "needs review"
        else:
            row.status = "prepared"
        # final ffprobe after move verifies output is a parseable media file
        result = probe(dest, ffprobe)
        if not any(x.get("codec_type") == "video" for x in result.get("streams", [])):
            row.status = "needs review"
            row.warnings.append("Output validation failed: video track is missing")
        log(f"{row.status.upper()}: {source.name}")
        return row


