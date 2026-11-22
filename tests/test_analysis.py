"""Pure unit tests: run without FFmpeg or Windows."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

from lg_webos_preparer.models import PROFILES
from lg_webos_preparer.analysis import (
    audio_compatible, choose_audio, external_subtitle, is_hdr, inspect,
    srt_valid, subtitle_choice, video_issues,
)
from lg_webos_preparer.repair import (
    resolve_tool, unique_destination, video_reencode_appropriate,
)


class AnalysisTests(unittest.TestCase):
    def test_prefers_compatible_english_audio_to_truehd(self):
        audios = [
            {"index": 1, "codec_name": "truehd", "channels": 8, "tags": {"language": "eng"}},
            {"index": 2, "codec_name": "ac3", "channels": 6, "tags": {"language": "eng"}},
            {"index": 3, "codec_name": "aac", "channels": 2, "tags": {"language": "ita"}},
        ]
        selected, conversion = choose_audio(audios, PROFILES["bx"])
        self.assertEqual(selected["index"], 2)
        self.assertFalse(conversion)

    def test_converts_english_truehd_not_other_language_aac(self):
        audios = [
            {"index": 1, "codec_name": "truehd", "channels": 8, "tags": {"language": "eng"}},
            {"index": 2, "codec_name": "aac", "channels": 2, "tags": {"language": "ita"}},
        ]
        selected, conversion = choose_audio(audios, PROFILES["bx"])
        self.assertEqual(selected["index"], 1)
        self.assertTrue(conversion)

    def test_bx_aac_7_1_is_a_model_specific_assumption(self):
        audio = {"codec_name": "aac", "channels": 8}
        self.assertTrue(audio_compatible(audio, PROFILES["bx"]))
        self.assertFalse(audio_compatible(audio, PROFILES["modern4k"]))
        self.assertFalse(audio_compatible({"codec_name": "ac3", "channels": 0}, PROFILES["bx"]))

    def test_choose_nonforced_english_text_subs(self):
        subs = [
            {"index": 3, "codec_name": "hdmv_pgs_subtitle", "tags": {"language": "eng"}},
            {"index": 4, "codec_name": "subrip", "tags": {"language": "eng"}},
        ]
        self.assertEqual(subtitle_choice(subs)["index"], 4)

    def test_dolby_vision_prevents_sdr_conversion(self):
        v = {"codec_name": "hevc", "width": 3840, "height": 2160,
             "avg_frame_rate": "24000/1001", "side_data_list": [{"side_data_type": "DOVI configuration record"}]}
        self.assertTrue(is_hdr(v))
        self.assertFalse(video_reencode_appropriate({"video": v}, PROFILES["legacy"], True))

    def test_unsupported_10bit_h264_warns(self):
        v = {"codec_name": "h264", "width": 1920, "height": 1080,
             "avg_frame_rate": "24/1", "profile": "High 10"}
        problems, warnings = video_issues(v, {}, PROFILES["bx"])
        self.assertFalse(problems)
        self.assertTrue(any("10-bit" in x for x in warnings))

    def test_frozen_bundle_tool_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "tools" / "ffprobe.exe"
            binary.parent.mkdir()
            binary.write_bytes(b"placeholder")
            with patch.object(sys, "_MEIPASS", temp, create=True):
                self.assertEqual(resolve_tool("ffprobe"), str(binary))

    def test_external_srt_detection_and_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "film.mkv"
            video.write_bytes(b"x")
            srt = Path(temp) / "film.eng.srt"
            srt.write_text("1\n00:00:00,200 --> 00:00:01,000\nCaption\n", encoding="utf-8")
            self.assertEqual(external_subtitle(video), srt)
            self.assertTrue(srt_valid(srt))

    def test_names_do_not_clobber_existing_subtitle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "film.srt").write_text("keep original")
            self.assertEqual(unique_destination(root / "film.mkv"), root / "film (2).mkv")


if __name__ == "__main__":
    unittest.main()
