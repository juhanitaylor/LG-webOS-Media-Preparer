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


if __name__ == "__main__":
    unittest.main()
