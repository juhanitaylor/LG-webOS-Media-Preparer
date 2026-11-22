# LG webOS Media Preparer v0.4.0

A portable Windows utility that checks and prepares USB videos for **LG webOS TVs**. The repository contains the Python application and Windows build scripts. The build places the portable executable and its redistribution materials in `dist/`.

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
scripts/stage_windows_ocr.py      Stage OCR tools for development from Python source
build_windows.ps1                 Build and test the portable Windows release
LG_webOS_Media_Preparer.spec      PyInstaller one-file configuration
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
5. Choose an **input video or folder**, a **different output folder**, and the `bx` profile. Use **Scan only** first and read the scan results in the terminal. Prepare a small sample and test it on the TV.

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

The portable release build uses source-built Tesseract and a self-contained SeConv with its own native DLLs. Its OCR engine works offline with the bundled English model.

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

## Use the portable Windows EXE

Copy `LG_webOS_Media_Preparer_v0.4.0.exe` to any writable or read-only location and double-click it. The application targets Windows 10 22H2 and Windows 11 on x64. It runs as a regular user, with its own Python, FFmpeg, FFprobe and OCR tools. It needs no network connection to scan or prepare local media.

The local v0.4.0 build was about **82 MiB** and opened in about **1.2 seconds** on the Windows 11 test machine. PyInstaller extracts the payload to Windows’ temporary directory at startup, so slower storage can take longer. The bundled English OCR model accounts for about **1.9 MiB** of the compressed EXE.

The local build passed portable testing on Windows 11 25H2 with development tools removed from PATH. Windows 10 22H2 remains untested. The EXE is unsigned. A clean offline Windows Sandbox blocked its launch under Application Control, so clean-machine compatibility and any signing requirements should be verified against the intended deployment policy.

The app remembers the last paths and TV profile in `%LOCALAPPDATA%\LG webOS Media Preparer\settings.json`. Processing writes only to your chosen output folder. An abrupt shutdown may leave a `.lg-media-*` staging folder inside the output. Scans ignore these folders and the next run uses fresh staging paths.

## Build and test the Windows executable

On an x64 Windows build machine, install [Python 3.14.10 x64](https://www.python.org/downloads/release/python-31410/) including Tkinter. Run this from the repository root in PowerShell.

```powershell
.\build_windows.ps1
```

Use `-Python C:\path\to\python.exe` to specify the pinned interpreter. The build downloads and verifies its inputs, builds the media tools from source, runs the source tests, generates the one-file EXE, and then tests the EXE with a restricted PATH. The first build needs internet access, several gigabytes of workspace, and time to compile the native tools. Later builds reuse the verified build inputs. The build reports the final EXE size and SHA-256, along with the measured startup time when a Windows desktop is available.

The build uses the application version in the EXE filename, currently `dist/LG_webOS_Media_Preparer_v0.4.0.exe`. It also generates the matching `.sha256` file, `provenance.json`, `third-party-notices.zip`, and `third-party-sources.zip`. The source and notice archives accompany distribution. Users only need the EXE to run the app.

## Download or publish a Windows build

1. After the workflow is on the default branch, open **Actions → Build portable Windows EXE → Run workflow** and select the branch to build.
2. Open the successful run and download **lg-webos-media-preparer-windows-x64** from **Artifacts**. Extract the ZIP and compare the output of `Get-FileHash .\LG_webOS_Media_Preparer_v0.4.0.exe -Algorithm SHA256` with the matching checksum file.
3. In **Releases → Draft a new release**, choose your tag and release notes. Attach the EXE, checksum, provenance, notices, and corresponding-source archive. Review the assets before publishing the draft. [Downloading Actions artifacts](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts) · [Managing releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)

## Distribution and licences

The repository owner selects the application’s own licence. The bundled FFmpeg and FFprobe are GPL-enabled builds because the legacy H.264 encode uses x264. Keep the matching source and notices available with the executable. See the [Windows portable build third-party notices](docs/WINDOWS_THIRD_PARTY.md) and [FFmpeg’s redistribution guidance](https://ffmpeg.org/legal.html).

## Project history

v0.4.0 adds portable Windows packaging, per-user settings, and file selection in the GUI. The v0.3 series added optional bitmap OCR and detailed operational logging.
