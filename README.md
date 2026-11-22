# LG webOS Media Preparer (source-first starter, v0.3.0)

**Review this Python code in VS Code before building or publishing it.** It is a conservative USB video compatibility checker and batch preparer for **LG webOS TVs only**. Source files are the deliverable; there is deliberately **no Windows executable in this repository yet**.

The default profile is **LG OLED55BX6LB (BX series, 2020)**. Two *approximate* profiles cover broader 4K LG televisions and older 1080p LG webOS TVs. These are heuristics, **not certification that playback will work on every LG model/firmware**.

## Source code layout

```text
run_gui.py                         Python entry point for GUI and CLI
lg_webos_preparer/
  __init__.py                     Version
  __main__.py                     python -m entry point
  models.py                       Profiles, constants and report record
  analysis.py                     FFprobe metadata parsing and compatibility checks
  repair.py                       FFmpeg remux, audio, SRT and optional OCR
  batch.py                        Folder/file processing and CSV/JSON reports
  gui.py                          Tkinter Windows desktop interface
  cli.py                          Command-line arguments
  tests/
    test_analysis.py              Pure Python tests
    test_integration.py           Tiny real-media FFmpeg tests
.vscode/launch.json               VS Code run/debug configurations
pyproject.toml                    Package metadata (no runtime Python packages needed)
docs/CODEX_BUILD_PROMPT.md        Copy into Codex when ready to build an EXE
```

## Features included in source

- Scan individual video files or recursively scan folders (`.mkv`, `.mp4`, `.mov`, `.avi`, `.ts`, `.m2ts`, ...).
- Identify likely video codec/resolution/frame-rate/HDR incompatibilities and audio/subtitle issues using FFprobe.
- Choose an existing compatible English audio track where possible; otherwise add a compatible AC3 or AAC track from the existing audio stream, retaining the originals.
- Copy/remux the video bitstream without video re-encoding in normal 4K modes.
- Use a matching external SRT, extract English text subtitles from embedded tracks, or optionally call Subtitle Edit `seconv` and Tesseract for OCR of bitmap subtitles.
- Optional **explicit** SDR-to-H.264 conversion in the older/1080p profile. No automatic HDR-to-SDR or Dolby Vision conversion.
- Verify the generated file with FFprobe, report warnings, and save CSV/JSON reports in the output directory.
- Use unique filenames; original video files are **never overwritten or deleted**. Large files need enough free disk space for another copy.

## Open and run in VS Code

1. Extract this ZIP to a normal folder and choose **File > Open Folder** in VS Code.
2. Install Python **3.11 or newer on the development PC**, and select it with VS Code's Python extension if needed.
3. For scanning and preparing media **from Python source**, install FFmpeg and FFprobe on your development PC. On Windows, `winget install -e --id Gyan.FFmpeg` is one option, or obtain binaries via [FFmpeg](https://ffmpeg.org/download.html). Restart VS Code after installing it. Verify `ffmpeg -version` and `ffprobe -version` in a terminal.
4. Run `python run_gui.py` from the project folder, or use **Run > Start Debugging** in VS Code and choose the GUI configuration.
5. Choose an **input folder**, a **different output folder**, and the `bx` profile. Use **Scan only** first. Inspect the CSV/JSON report, then prepare a small sample and test it on the TV.

CLI examples (PowerShell):

```powershell
python -m lg_webos_preparer --help
python -m lg_webos_preparer --input "D:\Videos" --output "D:\LG_Ready" --profile bx --mode scan
python -m lg_webos_preparer --input "D:\Videos\film.mkv" --output "D:\LG_Ready" --profile bx --mode prepare
python -m lg_webos_preparer --input "D:\Videos" --output "D:\LG_Ready" --profile modern4k --mode prepare
```

Test the source:

```powershell
python -m unittest discover -s tests -v
```

Pure unit tests run without FFmpeg; integration tests automatically skip when FFmpeg is unavailable. These tests use synthetic clips, **not your large real movie files**, and are not a guarantee of playback on a TV. A real Windows GUI smoke test is still required.

## Optional bitmap subtitle OCR

The program can invoke **Subtitle Edit `seconv`** and **Tesseract**, but these are **not bundled** and are **not necessary for core scanning/remuxing/audio fixes** in the current source edition. For source execution, install the tools separately, confirm `seconv --help` and `tesseract --version`, tick the OCR option, and set the `seconv` path if it is not on PATH. CLI example:

```powershell
python -m lg_webos_preparer --input "D:\Videos" --output "D:\LG_Ready" --profile bx --mode prepare --ocr --seconv "C:\Tools\Subtitle Edit\seconv.exe"
```

The OCR command is based on [Subtitle Edit's seconv documentation](https://github.com/SubtitleEdit/subtitleedit/blob/main/docs/reference/command-line.md). **MKV track numbering may not match FFprobe's global stream index**, so verify the selected track, output text and timing. OCR can introduce spelling errors and lose subtitle positioning/formatting. If OCR fails, the program reports it without modifying the source movie.

## Known limitations, by design

- No complete codec compatibility database for every LG webOS TV or every firmware release. Profiles are conservative and editable in `models.py`.
- Dolby Vision may not work with a particular MKV/USB combination even if the TV advertises Dolby Vision. The program flags it and avoids destructive conversions.
- Other factors include HEVC bit depth/profile, peak bitrate, USB drive filesystem/throughput, frame timing, firmware and container features.
- Existing SRT files are checked for basic syntax, **not subtitle synchronisation**. Please check the beginning, middle and end of each film.
- Missing dialogue/subtitles cannot be created or translated from nothing. English detection relies primarily on stream language tags.
- Audio conversion is lossy (AC3/AAC) but original audio tracks remain; video is not re-encoded in 4K modes.
- The optional legacy SDR video conversion loses video quality and is opt-in. HDR-to-SDR tone mapping is not implemented.
- Video remuxes do not guarantee preservation of every rare proprietary attachment, chapter tag or unsupported stream. Keep your originals.
- File integrity is checked via FFprobe parsing, presence of video/audio, and metadata checks. **It is not an end-to-end picture/audio playback test.**
- OCR tools are not part of the standalone EXE design until separately bundled and fully tested, including licence obligations.

## Building a Windows executable, after code review

See **[`docs/CODEX_BUILD_PROMPT.md`](docs/CODEX_BUILD_PROMPT.md)**. It asks Codex to produce and test a **portable Windows 10/11 `.exe`** using PyInstaller, bundling its own Python runtime, FFmpeg and FFprobe. End users should need no Python or FFmpeg installations, and there should be no installer. Packaging must be done and tested **on Windows**. A one-file PyInstaller build temporarily extracts files on launch, which is normal and still requires no installation.

The Codex prompt **does not authorise publishing to GitHub, creating a release or pushing commits**. You will inspect the changes in VS Code, upload your repository and create a release yourself.

## Distribution and licences

This starter source is provided for review; **no open-source licence has been chosen on your behalf**. Select and add a suitable `LICENSE` before publishing it publicly. Bundled FFmpeg binaries may be LGPL or GPL depending on their build configuration; GPL-enabled builds have redistributor obligations, including corresponding source. See [FFmpeg's legal guidance](https://ffmpeg.org/legal.html) and [PyInstaller's documentation](https://pyinstaller.org/en/stable/usage.html). Do not assume that adding a link to FFmpeg is sufficient for compliance.

## Project history

This v0.3 source package refactors and revises the earlier v0.2 single-file starter code. Notable fixes include awareness of existing SRTs during scanning, default audio selection and filename collision avoidance. The same conservative core workflows remain. It is an **early reviewable implementation**, not a production-certified release.
