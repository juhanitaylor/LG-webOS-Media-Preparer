# LG webOS Media Preparer (source-first starter, v0.3.0)

**Review this Python code in VS Code before building or publishing it.** It is a conservative USB video compatibility checker and batch preparer for **LG webOS TVs only**. The repository tracks source code. Local OCR tools and smoke builds live under the ignored `build/` directory.

The default profile is **LG OLED55BX6LB (BX series, 2020)**. Two *approximate* profiles cover broader 4K LG televisions and older 1080p LG webOS TVs. These are heuristics, **not certification that playback will work on every LG model/firmware**.

## Source code layout

```text
run_gui.py                         Python entry point for GUI and CLI
lg_webos_preparer/
  __init__.py                     Version
  __main__.py                     python -m entry point
  models.py                       Profiles, constants and report record
  analysis.py                     FFprobe metadata parsing and compatibility checks
  repair.py                       Repair planning, FFmpeg remux, and output verification
  ocr.py                          OCR tool discovery, bitmap conversion, and SRT validation
  scanlog.py, joblog.py            Scan formatting and batch log routing
  processes.py                    FFmpeg and OCR progress and diagnostics
  batch.py                        Folder/file processing and CSV/JSON reports
  gui.py                          Tkinter Windows desktop interface
  cli.py                          Command-line arguments
tests/                            Unit, FFmpeg batch and Windows bitmap OCR tests
scripts/stage_windows_ocr.py      Verify and stage the OCR runtime for a Windows build
.vscode/launch.json               VS Code run/debug configurations
pyproject.toml                    Package metadata (no runtime Python packages needed)
docs/CODEX_BUILD_PROMPT.md        Copy into Codex when ready to build an EXE
```

## Features included in source

- Scan individual video files or recursively scan folders (`.mkv`, `.mp4`, `.mov`, `.avi`, `.ts`, `.m2ts`, ...).
- Identify likely video codec/resolution/frame-rate/HDR incompatibilities and audio/subtitle issues using FFprobe.
- Choose an existing compatible English audio track where possible; otherwise add a compatible AC3 or AAC track from the existing audio stream, retaining the originals.
- Copy/remux the video bitstream without video re-encoding in normal 4K modes.
- Use a matching external SRT, extract English text subtitles from embedded tracks, or run offline English bitmap OCR with staged or bundled Subtitle Edit SeConv and Tesseract.
- Optional **explicit** SDR-to-H.264 conversion in the older/1080p profile. No automatic HDR-to-SDR or Dolby Vision conversion.
- Show scan results, repair decisions, progress, warnings and verification in the terminal. Save a persistent operational log and independent CSV/JSON compatibility reports.
- Use unique filenames; original video files are **never overwritten or deleted**. Large files need enough free disk space for another copy.

## Open and run in VS Code

1. Extract this ZIP to a normal folder and choose **File > Open Folder** in VS Code.
2. Install Python **3.11 or newer on the development PC**, and select it with VS Code's Python extension if needed.
3. For scanning and preparing media **from Python source**, install FFmpeg and FFprobe on your development PC. On Windows, `winget install -e --id Gyan.FFmpeg` is one option, or obtain binaries via [FFmpeg](https://ffmpeg.org/download.html). Restart VS Code after installing it. Verify `ffmpeg -version` and `ffprobe -version` in a terminal.
4. Run `python run_gui.py` from the project folder, or use **Run > Start Debugging** in VS Code and choose the GUI configuration.
5. Choose an **input folder**, a **different output folder**, and the `bx` profile. Use **Scan only** first and read the scan results in the terminal. Prepare a small sample and test it on the TV.

CLI examples (PowerShell):

```powershell
python -m lg_webos_preparer --help
python -m lg_webos_preparer --input "D:\Videos" --output "D:\LG_Ready" --profile bx --mode scan
python -m lg_webos_preparer --input "D:\Videos\film.mkv" --output "D:\LG_Ready" --profile bx --mode prepare
python -m lg_webos_preparer --input "D:\Videos" --output "D:\LG_Ready" --profile modern4k --mode prepare
python -m lg_webos_preparer --input "D:\Videos" --output "D:\LG_Ready" --profile bx --mode scan --debug
```

Test the source:

```powershell
python -m unittest discover -s tests -v
```

Unit tests run without FFmpeg. FFmpeg integration tests use synthetic clips. Windows OCR tests also need the staged tools below and use synthetic PGS and VobSub tracks with known timing and a competing subtitle track.

## Scan and preparation logs

Each job writes `lg_media_<mode>_<timestamp>.log` in its output folder and shows the same timestamped messages in the GUI terminal or the CLI console. Scan results include the container, file size, video properties, every audio and subtitle track, and the selected profile. Problems, warnings and recommended repair steps appear below each file.

During Prepare, the log shows the selected tracks, why each operation runs, FFmpeg and OCR progress, output locations and sizes, and verification. The final summary counts successful scans against files found. **Compatible inputs** had no reported profile problems and may still have warnings. **Repaired** means at least one corrective operation was completed. **Skipped repairs** include copy-only results during Prepare. Subtitle failures and files needing review are counted separately.

Enable **Debug logging** in the GUI or pass `--debug` in the CLI to include tool arguments, raw FFprobe metadata and extra diagnostics. Normal scan details appear at INFO without this option. FFmpeg progress is throttled and repeated diagnostics are summarised. The CSV and JSON files retain their compatibility-report format. Scan only reads source media and writes the log and reports to the selected output folder.

## Optional bitmap subtitle OCR

Enable **OCR English bitmap subtitles** for the job or pass `--ocr` in Prepare mode. The app prefers a valid matching SRT, then a tagged English text track, then a tagged English bitmap track. OCR supports Blu-ray PGS and DVD/VobSub tracks. The app isolates the chosen track, checks its timestamps against the prepared video, and compares the resulting SRT with the bitmap cue timings. The prepared video retains the original subtitle tracks and their language metadata.

Readable OCR results with valid cue timing are saved beside the video under the matching `.srt` name and marked **Needs review**. The log reports any questionable text it detects. Proofread the text and check timing at the beginning, middle and end. OCR can misread words and lose positioning and formatting. If OCR fails or the output fails validation, the log reports the reason and the prepared video is still available. The bundled model recognises English. DVB and XSUB are best-effort when the track and its timing can be verified.

Windows source developers can stage the pinned tools and model from the repository root. The command verifies the downloaded archives and English model against SHA-256 hashes. It needs network access on the first run.

```powershell
python scripts/stage_windows_ocr.py
python -m lg_webos_preparer --input "D:\Videos" --output "D:\LG_Ready" --profile bx --mode prepare --ocr
```

The app automatically finds the staged payload. Advanced source runs can use compatible tools on PATH or pass `--seconv`, `--tesseract` and `--tessdata` overrides. The Tesseract executable must have its conventional name so SeConv can find it. The app checks capabilities and loads the English model before OCR. [SeConv 5.4 command-line reference](https://github.com/SubtitleEdit/subtitleedit/blob/v5.4.0/docs/reference/command-line.md)

### Add OCR to a Windows x64 PyInstaller build

Stage the OCR payload, then add `--add-data 'build\ocr:tools/ocr'` to the Windows build command. Use an absolute source path if the PyInstaller spec is written outside the repository root. The one-file executable locates and runs the extracted SeConv and Tesseract tools with their DLLs and model. End users can enable OCR without installing those tools or accessing the internet. FFmpeg and FFprobe packaging is covered by the separate Windows build work.

To verify OCR from within a one-file executable on a development PC, build a local smoke executable with that data tree, point `LG_MEDIA_OCR_SMOKE_EXE` at it, and rerun `python -m unittest discover -s tests -v` with FFmpeg and FFprobe available. The frozen test gives the executable the development FFmpeg paths explicitly and strips the system OCR tools from PATH.

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

## Building a Windows executable, after code review

See **[`docs/CODEX_BUILD_PROMPT.md`](docs/CODEX_BUILD_PROMPT.md)**. It asks Codex to produce and test a **portable Windows 10/11 `.exe`** using PyInstaller, bundling its own Python runtime, FFmpeg and FFprobe. End users should need no Python or FFmpeg installations, and there should be no installer. Packaging must be done and tested **on Windows**. A one-file PyInstaller build temporarily extracts files on launch, which is normal and still requires no installation.

The Codex prompt **does not authorise publishing to GitHub, creating a release or pushing commits**. You will inspect the changes in VS Code, upload your repository and create a release yourself.

## Distribution and licences

This starter source is provided for review; **no open-source licence has been chosen on your behalf**. Select and add a suitable `LICENSE` before publishing it publicly. Bundled FFmpeg binaries may be LGPL or GPL depending on their build configuration; GPL-enabled builds have redistributor obligations, including corresponding source. See [FFmpeg's legal guidance](https://ffmpeg.org/legal.html) and [PyInstaller's documentation](https://pyinstaller.org/en/stable/usage.html). Do not assume that adding a link to FFmpeg is sufficient for compliance.

The Windows OCR payload adds MIT and Apache 2.0 components, the .NET runtime and third-party DLLs with separate terms. The staging step includes the primary licences and records binary provenance. Before redistributing a build, complete the notices and source requirements for the exact runtime dependencies. See [Windows OCR third-party components](docs/OCR_THIRD_PARTY.md).

## Project history

This v0.3 source package refactors and revises the earlier v0.2 single-file starter code. Notable fixes include awareness of existing SRTs during scanning, default audio selection and filename collision avoidance. The same conservative core workflows remain. It is an **early reviewable implementation**, not a production-certified release.
