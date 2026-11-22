"""Windows OCR smoke tests using synthetic bitmap tracks and the staged runtime."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lg_webos_preparer.analysis import probe
from lg_webos_preparer.batch import process_folder
from lg_webos_preparer.models import MediaError, PROFILES
from lg_webos_preparer.ocr import discover_ocr, read_cues


CAPTIONS = (
    "1\n00:00:02,000 --> 00:00:03,500\n{first}\n\n"
    "2\n00:00:04,000 --> 00:00:05,500\n{second}\n"
)
ENGLISH_TEXT = ("HELLO WORLD", "THE QUICK BROWN FOX")


@unittest.skipUnless(sys.platform == "win32" and shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "Windows with FFmpeg and FFprobe is required")
class WindowsOCRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ocr = discover_ocr()
        except MediaError as exc:
            raise unittest.SkipTest(f"Stage the Windows OCR tools first: {exc}") from exc
        workspace = tempfile.TemporaryDirectory(prefix="lg OCR smoke ")
        cls.addClassCleanup(workspace.cleanup)
        cls.root = Path(workspace.name)
        cls.movies = cls.root / "inputs, café"
        cls.movies.mkdir()
        cls.ffmpeg = shutil.which("ffmpeg")
        cls.ffprobe = shutil.which("ffprobe")
        cls.make_samples()

    @classmethod
    def make_samples(cls):
        subtitles = (
            ("en", "eng", ENGLISH_TEXT),
            ("fr", "fra", ("BONJOUR A TOUS", "AUTRE PISTE")),
        )
        for stem, _, text in subtitles:
            (cls.root / f"{stem}.srt").write_text(CAPTIONS.format(first=text[0], second=text[1]), encoding="utf-8")
            for format_name, suffix, options in (
                ("bluraysup", "sup", ["--font-size:60"]),
                ("vobsub", "sub", ["--resolution:720x480", "--font-size:34"]),
            ):
                subprocess.run([cls.ocr.seconv, f"{stem}.srt", format_name, "--font-name:Arial", *options,
                                f"--output-filename:{stem}.{suffix}"], env=cls.ocr.env, cwd=cls.root,
                               capture_output=True, check=True, timeout=45)
        for extension, name, audio, flags in (
            ("sup", "PGS.mkv", "aac", "default"),
            ("idx", "DVD.mkv", "flac", "0"),
        ):
            target = cls.movies / name
            subprocess.run([
                cls.ffmpeg, "-v", "error", "-copyts",
                "-f", "lavfi", "-i", "color=blue:s=320x180:r=25:d=7",
                "-f", "lavfi", "-i", "sine=d=7",
                "-i", str(cls.root / f"fr.{extension}"), "-i", str(cls.root / f"en.{extension}"),
                "-map", "0:v", "-map", "1:a", "-map", "2:s", "-map", "3:s",
                "-c:v", "libx264", "-c:a", audio, "-c:s", "copy",
                "-disposition:a:0", flags, "-metadata:s:a:0", "language=eng",
                "-metadata:s:s:0", "language=fra", "-disposition:s:0", "default+forced",
                "-metadata:s:s:1", "language=eng", "-disposition:s:1", "0",
                "-output_ts_offset", "4", str(target),
            ], check=True, capture_output=True, timeout=45)

    def assert_ocr_results(self, output, rows):
        self.assertEqual(len(rows), 2)
        for row in rows:
            if not isinstance(row, dict):
                row = vars(row)
            with self.subTest(path=row["path"]):
                self.assertEqual(row["status"], "needs review")
                self.assertTrue(row["subtitle_output"], row["warnings"])
                prepared_media = Path(row["output"])
                subtitle = Path(row["subtitle_output"])
                self.assertEqual(prepared_media.with_suffix(".srt"), subtitle)
                tracks = [s for s in probe(prepared_media, self.ffprobe)["streams"] if s["codec_type"] == "subtitle"]
                self.assertEqual([s["tags"]["language"] for s in tracks], ["fra", "eng"])
                self.assertEqual([s["disposition"]["forced"] for s in tracks], [1, 0])
                cues = read_cues(subtitle)
                self.assertEqual(len(cues), 2)
                for cue, phrase, (start, end) in zip(cues, ENGLISH_TEXT, [(2000, 3500), (4000, 5500)], strict=True):
                    self.assertEqual(re.sub(r"[^A-Z ]", "", cue.text.upper()), phrase)
                    self.assertLessEqual(abs(cue.start_ms - start), 40, cue)
                    self.assertLessEqual(abs(cue.end_ms - end), 40, cue)
        log = next(output.glob("*.log")).read_text(encoding="utf-8")
        self.assertIn("OCR runtime ready: SeConv", log)
        self.assertIn("OCR verification passed", log)

    def test_windows_pgs_and_vobsub_selected_text_and_sync(self):
        output = self.root / "source-mode-results"
        before = {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                  for p in self.movies.iterdir()}
        rows = process_folder(self.movies, output, PROFILES["bx"], "prepare", ocr=True, logger=lambda msg: None)
        self.assert_ocr_results(output, rows)
        self.assertEqual({p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                          for p in self.movies.iterdir()}, before)

    def test_disabled_or_missing_ocr_keeps_video_without_a_sidecar(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                output = self.root / f"ocr-unavailable-{enabled}"
                rows = process_folder(self.movies, output, PROFILES["bx"], "prepare", ocr=enabled,
                                      seconv=str(self.root / "missing.exe"), logger=lambda msg: None)
                self.assertEqual([row.status for row in rows], ["needs review", "needs review"])
                self.assertTrue(all(Path(row.output).is_file() and not row.subtitle_output for row in rows))
                self.assertFalse(list(output.glob("*.srt")))
                log = next(output.glob("*.log")).read_text(encoding="utf-8")
                self.assertIn("Subtitle OCR failed" if enabled else "Subtitle OCR skipped", log)

    @unittest.skipUnless(os.environ.get("LG_MEDIA_OCR_SMOKE_EXE"), "No local PyInstaller OCR smoke executable supplied")
    def test_one_file_discovers_and_uses_its_own_ocr_tools(self):
        exe = Path(os.environ["LG_MEDIA_OCR_SMOKE_EXE"]).resolve()
        output = self.root / "frozen-results"
        env = os.environ.copy()
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        env.pop("TESSDATA_PREFIX", None)
        subprocess.run([
            str(exe), "--input", str(self.movies), "--output", str(output), "--mode", "prepare", "--ocr", "--debug",
            "--ffmpeg", self.ffmpeg, "--ffprobe", self.ffprobe,
        ], env=env, cwd=self.root, check=True, timeout=120)
        rows = json.loads(next(output.glob("*.json")).read_text(encoding="utf-8"))
        self.assert_ocr_results(output, rows)
        log = next(output.glob("*.log")).read_text(encoding="utf-8")
        self.assertRegex(log, r"OCR tools: .*_MEI[^\\]+\\tools\\ocr\\seconv\\seconv\.exe")
