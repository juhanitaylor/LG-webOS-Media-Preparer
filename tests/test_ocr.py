"""Dependency discovery and validation for English subtitle OCR."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from lg_webos_preparer.models import MediaError
from lg_webos_preparer.ocr import OcrConfig, OcrTools, check_capabilities, discover_ocr, read_cues, validate_ocr


class OcrTests(unittest.TestCase):
    def test_frozen_runtime_discovery_configures_only_child_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "tools" / "ocr"
            converter = root / "seconv" / "seconv.exe"
            model = root / "tesseract" / "tessdata" / "eng.traineddata"
            converter.parent.mkdir(parents=True)
            model.parent.mkdir(parents=True)
            converter.touch()
            model.touch()
            (model.parent.parent / "tesseract.exe").touch()
            path_before = os.environ["PATH"]
            with patch.object(sys, "_MEIPASS", temp, create=True), patch("shutil.which") as which:
                tools = discover_ocr()
                which.assert_not_called()
            self.assertEqual(Path(tools.seconv), converter.resolve())
            self.assertEqual(Path(tools.env["TESSDATA_PREFIX"]), model.parent.resolve())
            self.assertEqual(Path(tools.env["PATH"].split(os.pathsep)[0]), model.parent.parent.resolve())
            self.assertEqual(os.environ["PATH"], path_before)

    def test_frozen_runtime_rejects_an_absent_model_and_honors_override(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(sys, "_MEIPASS", temp, create=True):
            root = Path(temp)
            converter = root / "other-seconv.exe"
            tess = root / "tools" / "ocr" / "tesseract" / "tesseract.exe"
            tess.parent.mkdir(parents=True)
            converter.touch()
            tess.touch()
            with self.assertRaisesRegex(MediaError, "Bundled English OCR model is missing"):
                discover_ocr(OcrConfig(seconv=str(converter)))
            data = root / "languages"
            data.mkdir()
            (data / "eng.traineddata").touch()
            tools = discover_ocr(OcrConfig(seconv=str(converter), tesseract=str(tess), tessdata=str(data)))
            self.assertEqual(Path(tools.seconv), converter.resolve())
            self.assertEqual(Path(tools.tesseract), tess.resolve())
            self.assertEqual(Path(tools.env["TESSDATA_PREFIX"]), data.resolve())

    def test_missing_explicit_converter_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(MediaError, "override for seconv was not found"):
                discover_ocr(OcrConfig(seconv=str(Path(temp) / "absent.exe")))

    def test_converter_name_does_not_establish_ocr_capability(self):
        tools = OcrTools("seconv.exe", "tesseract.exe", {})
        args = ["seconv.exe", "--help-json"]
        with patch("lg_webos_preparer.ocr.cmd_run", return_value=CompletedProcess(args, 0, "{}")):
            with self.assertRaisesRegex(MediaError, "does not advertise"):
                check_capabilities(tools)
        help_response = " ".join(("--ocr-engine", "--ocr-language", "--time-codes-only", "--output-filename"))
        engines = json.dumps({"engines": [{"id": "tesseract", "ready": False}]})
        with patch("lg_webos_preparer.ocr.cmd_run", side_effect=[CompletedProcess(args, 0, help_response),
                                                               CompletedProcess([], 0, engines)]):
            with self.assertRaisesRegex(MediaError, "did not find a usable Tesseract"):
                check_capabilities(tools)

    def test_valid_timing_and_questionable_cue(self):
        with tempfile.TemporaryDirectory() as temp:
            timing = Path(temp) / "timing.srt"
            out = Path(temp) / "output.srt"
            timing.write_text("1\n00:00:02,100 --> 00:00:03,001\n\n\n"
                              "2\n00:00:04,123 --> 00:00:05,250\n\n", encoding="utf-8-sig")
            out.write_text("1\n00:00:02,100 --> 00:00:03,001\n<i>Hello world</i>\n\n"
                           "2\n00:00:04,123 --> 00:00:05,250\n***\n", encoding="utf-8")
            self.assertEqual(validate_ocr(out, timing), (2, 1))
            self.assertEqual(read_cues(out)[0].end_ms, 3001)

    def test_rejects_invalid_or_shifted_ocr_output(self):
        cue = "1\n00:00:02,100 --> 00:00:03,001\n"
        with tempfile.TemporaryDirectory() as temp:
            timing = Path(temp) / "timing.srt"
            timing.write_text(cue, encoding="utf-8")
            out = Path(temp) / "output.srt"
            for text, error in (
                ("", "contains no cues"),
                (cue + "***\n", "no readable"),
                (cue + "Words\n\n2\nbad\nWords", "malformed SRT cue 2"),
                (cue.replace("03,001", "02,000") + "Words\n", "invalid or out-of-order"),
                (cue.replace("02,100", "02,200") + "Words\n", "changed the bitmap timing"),
                (cue + "Words\n\n2\n00:00:04,000 --> 00:00:05,000\nMore words", "2 cues for 1 bitmap"),
            ):
                with self.subTest(error=error):
                    out.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(MediaError, error):
                        validate_ocr(out, timing)
