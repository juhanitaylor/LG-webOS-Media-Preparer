"""Data models and deliberately conservative LG compatibility profiles.

Profiles represent heuristics, not certifications of every LG firmware version.
"""
from __future__ import annotations
from dataclasses import dataclass, field

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".ts", ".m2ts", ".mts"}
TEXT_SUBS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
BITMAP_SUBS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}
ENGLISH = {"en", "eng", "english", "en-gb", "en-us", "en_uk"}
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}

@dataclass(frozen=True)
class Profile:
    key: str
    title: str
    description: str
    video_codecs: frozenset[str]
    max_width: int
    max_height: int
    max_fps: float
    max_average_mbps: float | None
    hdr: bool
    preferred_audio: str  # ac3 or aac
    preferred_channels: int


PROFILES: dict[str, Profile] = {
    "bx": Profile("bx", "LG OLED BX 2020 (OLED55BX6LB)",
                  "4K HEVC Main/Main10, HDR10; 5.1 AC3 preferred. Validated on a sample TV only.",
                  frozenset({"hevc", "h264"}), 3840, 2160, 60, 60, True, "ac3", 6),
    "modern4k": Profile("modern4k", "LG webOS 4K (broad, approximate)",
                        "Conservative 4K HDR10 path. Actual support varies by model and firmware.",
                        frozenset({"hevc", "h264"}), 3840, 2160, 30, 45, True, "ac3", 6),
    "legacy": Profile("legacy", "Older LG webOS / 1080p SDR (approximate)",
                      "Best-effort H.264 1080p SDR, AAC stereo, external SRT.",
                      frozenset({"h264"}), 1920, 1080, 30, 20, False, "aac", 2),
}

@dataclass
class Inspection:
    path: str
    profile: str
    video: str = ""
    audio: list[str] = field(default_factory=list)
    subtitles: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    action: list[str] = field(default_factory=list)
    status: str = "analysed"
    output: str = ""
    subtitle_output: str = ""
    error: str = ""


class MediaError(RuntimeError):
    pass


