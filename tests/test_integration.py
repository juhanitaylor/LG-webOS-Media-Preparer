"""Short real-media tests, automatically skipped if FFmpeg is unavailable."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lg_webos_preparer.models import PROFILES
from lg_webos_preparer.analysis import probe
from lg_webos_preparer.batch import process_folder, find_videos
from lg_webos_preparer.analysis import srt_valid


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe not installed")
class IntegrationTests(unittest.TestCase):
    def test_flac_to_ac3_preserves_video_and_original_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "in"
            target = root / "out"
            source.mkdir()
            subs = source / "source.srt"
            subs.write_text("1\n00:00:00,200 --> 00:00:00,900\nHello LG.\n", encoding="utf-8")
            video = source / "Example.mkv"
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                       "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=2",
                       "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                       "-i", str(subs), "-map", "0:v", "-map", "1:a", "-map", "2:s",
                       "-c:v", "mpeg4", "-c:a", "flac", "-c:s", "srt",
                       "-metadata:s:a:0", "language=eng", "-metadata:s:s:0", "language=eng",
                       "-shortest", str(video)]
            subprocess.run(command, check=True)
            before = sha256(video)
            results = process_folder(source, target, PROFILES["bx"], "prepare", logger=lambda msg: None)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, "needs review")  # MPEG4 video is deliberately unsupported
            generated = target / "Example.mkv"
            self.assertTrue(generated.exists())
            self.assertEqual(before, sha256(video), "Original input was changed")
            result = probe(generated)
            self.assertEqual(next(x for x in result["streams"] if x["codec_type"] == "video")["codec_name"], "mpeg4")
            audios = [x for x in result["streams"] if x["codec_type"] == "audio"]
            self.assertEqual([a["codec_name"] for a in audios], ["ac3", "flac"])
            self.assertEqual(audios[0]["disposition"]["default"], 1)
            self.assertTrue(srt_valid(target / "Example.srt"))
            self.assertTrue(list(target.glob("lg_media_prepare_*.csv")))
            self.assertTrue(list(target.glob("lg_media_prepare_*.json")))
            # No generated copy should be rescanned if output lives inside input tree.
            self.assertEqual(find_videos(source), [video])

    def test_scan_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "videos"
            source.mkdir()
            dst = root / "reports"
            src = source / "Sample.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=1",
                            "-f", "lavfi", "-i", "sine=frequency=550:duration=1",
                            "-c:v", "mpeg4", "-c:a", "aac", str(src)], check=True)
            before = sha256(src)
            result = process_folder(source, dst, PROFILES["modern4k"], "scan", logger=lambda msg: None)
            self.assertEqual(before, sha256(src))
            self.assertEqual(len(result), 1)
            self.assertFalse(list(dst.glob("*.mp4")))
            self.assertTrue(list(dst.glob("*.csv")))

    def test_mixed_batch_scans_in_every_profile_and_continues_after_corrupt_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "videos"
            source.mkdir()
            caption = "1\n00:00:00,200 --> 00:00:00,800\nHello LG.\n"
            original_media = source / "A-compatible.mp4"
            original_caption = original_media.with_suffix(".srt")
            original_caption.write_text(caption, encoding="utf-8")
            embedded_caption = root / "embedded.srt"
            embedded_caption.write_text(caption, encoding="utf-8")
            broken = source / "B-corrupt.mkv"
            broken.write_bytes(b"Not a media container")
            repaired_media = source / "C-repair.mkv"
            fixture = ["ffmpeg", "-v", "error",
                       "-f", "lavfi", "-i", "color=blue:s=160x90:r=24:d=1",
                       "-f", "lavfi", "-i", "sine=frequency=550:duration=1"]
            subprocess.run([*fixture, "-c:v", "libx264", "-c:a", "aac", "-metadata:s:a:0", "language=eng",
                            str(original_media)], check=True)
            subprocess.run([*fixture, "-i", str(embedded_caption), "-map", "0:v", "-map", "1:a", "-map", "2:s",
                            "-c:v", "libx264", "-c:a", "flac", "-c:s", "srt",
                            "-metadata:s:a:0", "language=eng", "-metadata:s:s:0", "language=eng",
                            str(repaired_media)], check=True)
            before = {p.name: (sha256(p), p.stat().st_mtime_ns) for p in source.iterdir()}
            for profile in PROFILES.values():
                with self.subTest(profile=profile.key):
                    dst = root / f"scan-{profile.key}"
                    rows = process_folder(source, dst, profile, "scan", logger=lambda msg: None)
                    self.assertEqual([row.status for row in rows], ["analysed", "error", "needs attention"])
                    self.assertEqual({p.suffix for p in dst.iterdir()}, {".csv", ".json", ".log"})
                    self.assertEqual({p.name: (sha256(p), p.stat().st_mtime_ns) for p in source.iterdir()}, before)

            target = root / "prepared"
            logs = []
            rows = process_folder(source, target, PROFILES["bx"], "prepare", logger=logs.append)
            self.assertEqual([row.status for row in rows], ["prepared", "error", "prepared"])
            self.assertEqual(sha256(Path(rows[0].output)), sha256(original_media))
            self.assertTrue(srt_valid(Path(rows[2].subtitle_output)))
            actual = probe(Path(rows[2].output))
            audios = [s for s in actual["streams"] if s["codec_type"] == "audio"]
            self.assertEqual([a["codec_name"] for a in audios], ["ac3", "flac"])
            self.assertEqual([a["disposition"]["default"] for a in audios], [1, 0])
            self.assertIn("scanned: 2/3 | compatible inputs: 1 | repaired: 1 | skipped repairs: 1 | failed: 1",
                          logs[-1])
            self.assertEqual({p.name: (sha256(p), p.stat().st_mtime_ns) for p in source.iterdir()}, before)

    def test_legacy_opt_in_reencodes_sdr_and_mov_text_converts_during_remux(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "in"
            source.mkdir()
            captions = root / "lines.srt"
            captions.write_text("1\n00:00:00,100 --> 00:00:00,800\nHello LG.\n", encoding="utf-8")
            media = source / "old.mov"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=160x90:d=1",
                            "-f", "lavfi", "-i", "sine=d=1", "-i", str(captions),
                            "-map", "0:v", "-map", "1:a", "-map", "2:s",
                            "-c:v", "mpeg4", "-c:a", "aac", "-c:s", "mov_text",
                            "-metadata:s:a:0", "language=eng", "-metadata:s:s:0", "language=eng", str(media)],
                           check=True)
            for allow, expected_codec in ((False, "mpeg4"), (True, "h264")):
                with self.subTest(allow=allow):
                    row, = process_folder(media, root / f"out-{allow}", PROFILES["legacy"], "prepare",
                                          allow_sdr_video=allow, logger=lambda msg: None)
                    self.assertEqual(row.status, "prepared" if allow else "needs review")
                    tracks = {s["codec_type"]: s["codec_name"] for s in probe(Path(row.output))["streams"]}
                    self.assertEqual(tracks, {"video": expected_codec, "audio": "aac", "subtitle": "subrip"})
                    self.assertTrue(srt_valid(Path(row.subtitle_output)))


if __name__ == "__main__":
    unittest.main()
