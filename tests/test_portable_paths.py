"""Portable resource discovery and per-user output protection."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from lg_webos_preparer.batch import find_videos
from lg_webos_preparer.preferences import Preferences, load_preferences, preferences_path, save_preferences
from lg_webos_preparer.repair import available_tool, publish_output, resolve_tool


class PortablePathsTests(unittest.TestCase):
    def test_frozen_tool_paths_keep_missing_binaries_explicit(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(sys, "_MEIPASS", temp, create=True):
            root = Path(temp).resolve()
            decoy = root / "elsewhere" / "ffmpeg.exe"
            decoy.parent.mkdir()
            decoy.touch()
            with patch("shutil.which", return_value=str(decoy)):
                selected = resolve_tool("ffmpeg")
                self.assertEqual(Path(selected), root / "tools" / "ffmpeg.exe")
                self.assertFalse(available_tool(selected))
            self.assertEqual(Path(resolve_tool("ffmpeg", str(decoy))), decoy)

    def test_settings_roundtrip_and_invalid_profile(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, LOCALAPPDATA=temp):
            expected = Preferences("D:/media café", "E:/output", "legacy")
            save_preferences(expected)
            self.assertEqual(load_preferences(), expected)
            self.assertEqual(list(preferences_path().parent.iterdir()), [preferences_path()])
            preferences_path().write_text('{"profile":"old","input_path":42}', encoding="utf-8")
            self.assertEqual(load_preferences(), Preferences())

    def test_publish_will_not_overwrite_and_stale_work_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "video.mkv"
            output.write_bytes(b"verified output")
            staging = root / ".lg-media-interrupted"
            staging.mkdir()
            pending = staging / "video.mkv"
            pending.write_bytes(b"partial video")
            with self.assertRaises(FileExistsError):
                publish_output(pending, output)
            self.assertEqual(output.read_bytes(), b"verified output")
            self.assertEqual(find_videos(root), [output])
