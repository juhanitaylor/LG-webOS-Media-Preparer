"""Probe and evaluate container streams without changing the source file."""
from __future__ import annotations
import json
import re
from pathlib import Path
from .models import (Profile, Inspection, MediaError, TEXT_SUBS, BITMAP_SUBS, ENGLISH, HDR_TRANSFERS)
from .processes import cmd_run


def probe(path: Path, ffprobe: str = "ffprobe") -> dict:
    result = cmd_run([ffprobe, "-v", "error", "-show_format", "-show_streams",
                      "-of", "json", str(path)])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(f"FFprobe did not return valid JSON for {path.name}") from exc


def ratio_float(value: object) -> float:
    try:
        if value is None or str(value) in {"N/A", "0/0"}:
            return 0.0
        s = str(value)
        return float(s.split("/")[0]) / float(s.split("/")[1]) if "/" in s else float(s)
    except (ValueError, ZeroDivisionError, TypeError):
        return 0.0


def lang(stream: dict) -> str:
    return str(stream.get("tags", {}).get("language", "und")).strip().lower()


def is_english(stream: dict) -> bool:
    value = lang(stream)
    return value in ENGLISH or value.startswith("en-")


def stream_label(s: dict) -> str:
    x = f"#{s.get('index', '?')} {s.get('codec_name', '?')} ({lang(s)})"
    return x


def video_issues(video: dict, metadata: dict, profile: Profile) -> tuple[list[str], list[str]]:
    problems, warnings = [], []
    codec = str(video.get("codec_name", "")).lower()
    w, h = int(video.get("width", 0)), int(video.get("height", 0))
    fps = frame_rate(video)
    hdr = is_hdr(video)
    if codec not in profile.video_codecs:
        problems.append(f"Video codec {codec or 'unknown'} is outside the selected profile")
    if w > profile.max_width or h > profile.max_height:
        problems.append(f"Resolution {w}x{h} exceeds {profile.max_width}x{profile.max_height}")
    if fps > profile.max_fps + 0.3:
        problems.append(f"Frame rate {fps:.2f} exceeds {profile.max_fps:g} fps")
    if hdr and not profile.hdr:
        problems.append("HDR video is outside this SDR profile")
    bitrate, _ = stream_bitrate(video)
    if not bitrate:
        bitrate = ratio_float(metadata.get("format", {}).get("bit_rate"))
        if bitrate:
            warnings.append("Using whole-file bitrate as a video bitrate approximation")
    if profile.max_average_mbps and bitrate > profile.max_average_mbps * 1e6:
        warnings.append(f"Average bitrate ~{bitrate / 1e6:.1f} Mbps exceeds profile guide; peak bitrate may be higher")
    if str(video.get("codec_name")) == "h264" and str(video.get("profile", "")).lower() in {"high 10", "high 4:2:2", "high 4:4:4 predictive"}:
        warnings.append("H.264 10-bit or 4:2:2/4:4:4 detected; TV USB support is uncertain")
    if str(video.get("codec_name")) == "hevc" and (str(video.get("profile", "")).lower() not in {"main", "main 10", ""}):
        warnings.append(f"Unusual HEVC profile ({video.get('profile')}); playback may fail")
    # Metadata alone cannot prove that the Dolby Vision profile works in a TV USB player.
    if is_dolby_vision(video):
        warnings.append("Dolby Vision detected: the exact profile and HDR10 fallback need playback testing")
    return problems, warnings


def is_hdr(video: dict) -> bool:
    # Dolby Vision can have a transfer tag that is incomplete or misleading.
    return (str(video.get("color_transfer", "")).lower() in HDR_TRANSFERS
            or is_dolby_vision(video))


def is_dolby_vision(video: dict) -> bool:
    if str(video.get("codec_tag_string", "")).lower() in {"dvhe", "dvh1", "dvav", "dva1"}:
        return True
    tags_and_side = json.dumps(video, default=str).lower()
    return "dovi" in tags_and_side or "dolby vision" in tags_and_side


def frame_rate(video: dict) -> float:
    return ratio_float(video.get("avg_frame_rate")) or ratio_float(video.get("r_frame_rate"))


def stream_bitrate(stream: dict) -> tuple[float, bool]:
    rate = ratio_float(stream.get("bit_rate"))
    if rate > 0:
        return rate, False
    for name, value in (stream.get("tags") or {}).items():
        if name.upper() == "BPS" or name.upper().startswith("BPS-"):
            rate = ratio_float(value)
            if rate > 0:
                return rate, True
    return 0, False


def audio_compatible(s: dict, profile: Profile) -> bool:
    codec = str(s.get("codec_name", "")).lower()
    channels = int(s.get("channels") or 0)
    if codec == "ac3":
        return 1 <= channels <= 6
    if codec == "eac3":
        return 1 <= channels <= 6 and profile.key != "legacy"
    if codec == "aac":
        # AAC 7.1 has been observed playing on the BX; on untested LG models
        # cap to six channels for this conservative profile.
        max_channels = 2 if profile.key == "legacy" else 8 if profile.key == "bx" else 6
        return 1 <= channels <= max_channels
    if codec == "mp3":
        return 1 <= channels <= 2
    return False


def audio_priority(s: dict, profile: Profile) -> tuple[int, int, int, int]:
    c = str(s.get("codec_name", ""))
    return (0 if is_english(s) else 1,
            0 if audio_compatible(s, profile) else 1,
            0 if c == profile.preferred_audio else 1,
            int(s.get("index", 9999)))


def choose_audio(streams: list[dict], profile: Profile) -> tuple[dict | None, bool]:
    """Choose an English track if possible. Return (stream, conversion required)."""
    if not streams:
        return None, False
    english = [s for s in streams if is_english(s)]
    available = english or streams
    compatible = [s for s in available if audio_compatible(s, profile)]
    if compatible:
        return sorted(compatible, key=lambda s: audio_priority(s, profile))[0], False
    return sorted(available, key=lambda s: (0 if is_english(s) else 1, s.get("index", 9999)))[0], True


def subtitle_choice(streams: list[dict]) -> dict | None:
    english = [s for s in streams if is_english(s)]
    if not english:
        return None
    # Prefer non-SDH, non-forced full text. Forced subtitles alone are not full dialogue.
    def score(s: dict) -> tuple:
        flags = s.get("disposition") or {}
        name = str(s.get("tags", {}).get("title", "")).lower()
        return (0 if s.get("codec_name") in TEXT_SUBS else 1,
                1 if flags.get("forced") or "forced" in name else 0,
                1 if "sdh" in name or "hearing" in name else 0,
                s.get("index", 9999))
    return sorted(english, key=score)[0]


def inspect(path: Path, profile: Profile, ffprobe: str = "ffprobe") -> tuple[Inspection, dict, dict]:
    data = probe(path, ffprobe)
    streams = data.get("streams", [])
    videos = [x for x in streams if x.get("codec_type") == "video" and not x.get("disposition", {}).get("attached_pic")]
    audios = [x for x in streams if x.get("codec_type") == "audio"]
    subs = [x for x in streams if x.get("codec_type") == "subtitle"]
    row = Inspection(path=str(path), profile=profile.title)
    if not videos:
        raise MediaError(f"No video stream in {path.name}")
    v = videos[0]
    row.video = f"{stream_label(v)} {v.get('width','?')}x{v.get('height','?')} @ {frame_rate(v):.2f}fps"
    row.audio = [stream_label(x) for x in audios]
    row.subtitles = [stream_label(x) for x in subs]
    issues, warns = video_issues(v, data, profile)
    row.problems.extend(issues)
    row.warnings.extend(warns)
    audio, convert = choose_audio(audios, profile)
    if audio is None:
        row.problems.append("No audio track found")
    elif convert:
        row.problems.append(f"No compatible {'English ' if is_english(audio) else ''}audio track: add {profile.preferred_audio.upper()}")
    if audio and not is_english(audio):
        row.warnings.append("No English audio tagged; only the existing language can be used")
    sc = subtitle_choice(subs)
    if sc is None:
        row.warnings.append("No tagged English subtitle track found; an external SRT may still exist")
    elif sc.get("codec_name") in BITMAP_SUBS:
        row.problems.append("English subtitles are bitmap-based; OCR is required for reliable LG USB playback")
    elif sc.get("codec_name") not in TEXT_SUBS:
        row.warnings.append(f"Unknown English subtitle codec: {sc.get('codec_name')}")
    external = external_subtitle(path)
    valid_external = None
    if external:
        valid_external = external if srt_valid(external) else external_subtitle(path, require_valid=True)
    if valid_external:
        # A matching external SRT is preferable to converting embedded bitmap subtitles.
        row.problems = [issue for issue in row.problems if not issue.startswith("English subtitles are bitmap")]
        row.warnings = [warning for warning in row.warnings if not warning.startswith("No tagged English subtitle track")]
        row.warnings.append(f"External SRT detected: {external.name}; check timing on TV")
    elif external:
        row.warnings.append(f"External SRT could not be validated: {external.name}; consider an embedded track")
    if path.suffix.lower() not in {".mkv", ".mp4", ".m4v"}:
        row.warnings.append("Container is not a preferred LG USB format; remux to MKV may help")
    if path.stat().st_size > 4 * 1024**3:
        row.warnings.append("Over 4 GiB: USB drive must use a filesystem that supports large files (e.g. exFAT/NTFS)")
    row.status = "needs attention" if row.problems else "analysed"
    return row, data, {"video": v, "audios": audios, "subs": subs, "audio": audio, "audio_convert": convert,
                       "subtitle": sc, "external_subtitle": valid_external, "video_problems": issues,
                       "video_warnings": warns}


def external_subtitle(source: Path, *, require_valid: bool = False) -> Path | None:
    """Find pre-existing English SRT next to source, without confusing other titles."""
    for suffix in (".srt", ".eng.srt", ".en.srt", ".English.srt"):
        candidate = source.with_name(source.stem + suffix)
        if candidate.is_file() and candidate.stat().st_size > 10 and (not require_valid or srt_valid(candidate)):
            return candidate
    return None


def srt_valid(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 12:
        return False
    with path.open("rb") as f:
        head = f.read(8192)
    return b"-->" in head and re.search(rb"\d{2}:\d{2}:\d{2}[,.]\d{3}", head) is not None


