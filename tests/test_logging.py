"""Scan presentation, operational log routing, and subprocess progress."""
import csv
import json
import logging
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from lg_webos_preparer.analysis import inspect
from lg_webos_preparer.batch import process_folder
from lg_webos_preparer.joblog import CallbackHandler, job_logger
from lg_webos_preparer.models import Inspection, MediaError, PROFILES
from lg_webos_preparer.processes import run_ffmpeg, stream_command
from lg_webos_preparer.repair import plan_repair
from lg_webos_preparer.scanlog import format_scan


METADATA = {
    "format": {"format_name": "matroska,webm", "format_long_name": "Matroska / WebM", "bit_rate": "68000000"},
    "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160,
         "avg_frame_rate": "0/0", "r_frame_rate": "24000/1001", "pix_fmt": "yuv420p10le",
         "color_transfer": "smpte2084", "color_primaries": "bt2020"},
        {"index": 1, "codec_type": "audio", "codec_name": "truehd", "channels": 8,
         "bit_rate": "2400000", "tags": {"language": "eng"}, "disposition": {"default": 1}},
        {"index": 2, "codec_type": "audio", "codec_name": "ac3", "channels": 6,
         "tags": {"language": "fra", "BPS": "640000"}, "disposition": {"default": 0}},
        {"index": 3, "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle",
         "tags": {"language": "eng"}, "disposition": {"default": 1, "forced": 0}},
        {"index": 4, "codec_type": "subtitle", "codec_name": "subrip",
         "tags": {"language": "fra"}, "disposition": {"default": 0, "forced": 1}},
    ],
}


class LoggingTests(unittest.TestCase):
    def test_scan_shows_every_track_and_the_repair_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "Example.mkv"
            path.write_bytes(b"\0" * 2048)
            profile = PROFILES["bx"]
            with patch("lg_webos_preparer.analysis.probe", return_value=METADATA):
                row, metadata, info = inspect(path, profile)
            plan = plan_repair(path, info, profile, ocr=True, allow_sdr_video=False)
            report = format_scan(row, metadata, info, profile, plan)
        for line in (
            "Scan results for Example.mkv", "2.00 KiB (2,048 bytes)", "Container: Matroska / WebM",
            "LG profile: LG OLED BX", "3840x2160 | 23.976 fps | 10-bit | HDR10 / PQ",
            "whole-file estimate", "#1 truehd (eng) | 8 channels | 2,400.0 kb/s | default: yes | outside profile",
            "#2 ac3 (fra) | 6 channels | 640.0 kb/s (track tag) | default: no | compatible",
            "#3 hdmv_pgs_subtitle (eng) | bitmap | default: yes | forced: no",
            "#4 subrip (fra) | text | default: no | forced: yes", "Video: compatible with warnings",
            "needs a compatible AC3 fallback",
            "Subtitles: selected bitmap requires OCR", "Recommended actions", "Stream-copy video",
            "Remux to MKV", "OCR #3 hdmv_pgs_subtitle",
        ):
            with self.subTest(line=line):
                self.assertIn(line, report)

    def test_job_log_routes_via_queue_and_keeps_reports_independent(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch("lg_webos_preparer.analysis.probe", return_value=METADATA), \
                patch("lg_webos_preparer.batch.available_tool", return_value=True):
            root = Path(temp)
            video = root / "Example.mkv"
            video.touch()
            for debug in (False, True):
                with self.subTest(debug=debug):
                    out = root / str(debug)
                    events = queue.Queue()
                    logger = job_logger(debug, CallbackHandler(events.put))
                    worker = threading.Thread(target=process_folder,
                                              args=(video, out, PROFILES["bx"], "scan"),
                                              kwargs={"logger": logger})
                    worker.start()
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive())
                    terminal_messages = []
                    while not events.empty():
                        terminal_messages.append(events.get_nowait())
                    text = next(out.glob("*.log")).read_text(encoding="utf-8")
                    self.assertEqual(text, "\n".join(terminal_messages) + "\n")
                    self.assertRegex(text, r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d INFO +Scan results")
                    self.assertIn("Summary | scanned: 1/1", text)
                    self.assertEqual("DEBUG" in text, debug)
                    record = json.loads(next(out.glob("*.json")).read_text(encoding="utf-8"))[0]
                    expected = list(Inspection.__dataclass_fields__)
                    self.assertEqual(list(record), expected)
                    with next(out.glob("*.csv")).open(newline="", encoding="utf-8-sig") as output:
                        self.assertEqual(next(csv.reader(output)), expected)
                    self.assertEqual(len(logger.handlers), 1)

    def test_job_failure_is_logged_and_releases_file_handler(self):
        with tempfile.TemporaryDirectory() as temp, patch("lg_webos_preparer.batch.available_tool", return_value=False):
            root = Path(temp)
            out = root / "out"
            messages = []
            logger = job_logger(handler=CallbackHandler(messages.append))
            with self.assertRaisesRegex(MediaError, "ffprobe not found"):
                process_folder(root, out, PROFILES["bx"], "scan", logger=logger)
            text = next(out.glob("*.log")).read_text(encoding="utf-8")
            self.assertIn("ERROR   Job failed: ffprobe not found", text)
            self.assertEqual(text, "\n".join(messages) + "\n")
            self.assertEqual(len(logger.handlers), 1)

    def test_ffmpeg_progress_is_throttled(self):
        messages = []
        logger = job_logger(handler=CallbackHandler(messages.append, formatted=False))

        def fake_command(args, log, update, **kwargs):
            self.assertIn("-nostats", args)
            self.assertIn("pipe:1", args)
            for stamp, status in ((1, "continue"), (3, "continue"), (7, "continue"), (9, "end")):
                update(f"out_time_us={stamp * 1000000}")
                update(f"out_time=00:00:0{stamp}.000000")
                update("speed=2x")
                update(f"progress={status}")

        with patch("lg_webos_preparer.processes.stream_command", side_effect=fake_command), \
                patch("lg_webos_preparer.processes.time.monotonic", side_effect=[0, 1, 3, 7, 9]):
            run_ffmpeg(["test.mkv"], logger=logger, duration=10)
        self.assertEqual(len(messages), 2)
        self.assertIn("70%", messages[0])
        self.assertIn("final progress", messages[1])

    def test_subprocess_warnings_are_deduplicated(self):
        messages = []
        lines = []
        logger = job_logger(handler=CallbackHandler(messages.append))
        stream_command([sys.executable, "-c",
                        "import sys; print('progress'); sys.stderr.write('[warning] repeated\\n' * 1000)"],
                       logger, lines.append, label="Test subprocess", timeout=10)
        self.assertEqual(lines, ["progress"])
        self.assertEqual(sum("[warning] repeated" in line for line in messages), 1)
        self.assertIn("suppressed 999", messages[-1])
        self.assertEqual(logger.level, logging.INFO)
