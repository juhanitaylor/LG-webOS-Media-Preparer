# Codex prompt: Build and validate portable Windows EXE

I have opened this repository, **LG webOS Media Preparer v0.3.0**, in VS Code. Please work only in this local project. I will review all edits before putting the project on GitHub and creating a release myself.

## Goal

Turn this reviewable Python source project into a **single portable Windows 10/11 `.exe`** named `LG_webOS_Media_Preparer.exe` that launches the Tkinter GUI with no installer and needs **no Python, FFmpeg or FFprobe installation on the end user's computer**. Preserve the CLI for development and diagnostics. Focus only on LG webOS television profiles, with `OLED55BX6LB` as default.

## First inspect, then implement

1. Read `README.md`, `lg_webos_preparer/*.py`, and `tests/*.py` in full. Explain any bugs or fragile assumptions you find, especially selection of audio/subtitle tracks, stream mapping, subtitle timing, Dolby Vision flags, file overwrite protection and Python-package imports. Make targeted changes, not an unrelated rewrite.
2. Run `python -m unittest discover -s tests -v` in a fresh environment. Add tests for changes. Test representative synthetic samples covering a compatible file, unsupported TrueHD audio converted to AC3 (or FLAC if generating TrueHD is impractical), an existing compatible AC3 default or non-default track, English embedded text subtitle extraction, external SRT, bitmap/PGS detection, and an unsupported video that must not be silently re-encoded. Check SHA-256 of original input before and after conversion. Never operate on personal media files without permission.
3. Implement a reproducible **Windows-only PyInstaller build** (prefer a PowerShell build script plus a human-readable README). Pin and document build dependencies in a build requirements file. Use `--onefile` and `--windowed` for the end-user GUI, or an equivalent spec file, and bundle working `ffmpeg.exe` and `ffprobe.exe` using PyInstaller binary resources. The existing `resolve_tool()` must locate them via `sys._MEIPASS` or its modern equivalent, even on PCs with no FFmpeg on PATH.
4. Fetch FFmpeg binaries from a reputable publisher over HTTPS, **verify a pinned SHA-256** before building, record the exact FFmpeg version/source URL/build flags and licences, and do not trust an unverified latest download. Reproducible version pinning is preferable to a moving link.
5. Package a **single EXE** without requiring installation, admin rights, Python, FFmpeg, or FFprobe on the destination PC. Test on a clean Windows virtual machine or equivalent environment, with no development tools on PATH. Test launch, GUI selection, `Scan only`, `Prepare`, report generation and a short file with FFmpeg audio repair. Check Windows 10 and 11 compatibility where practical. If true clean-machine validation is unavailable, say so clearly and do not claim success.
6. Maintain the key product properties: preserve video and HDR streams where supported; copy rather than re-encode by default; add AC3/AAC audio only when needed; retain original audio tracks; prefer external or extracted SRT; optional OCR for bitmap subtitles; profiles for LG BX / broad 4K / older 1080p; input files never modified or deleted; unique output paths; CSV and JSON reports; warnings for uncertainty; no silent HDR-to-SDR conversion.
7. **OCR:** The source uses optional Subtitle Edit `seconv` + Tesseract. Assess whether bundling both (including OCR language data) in the single EXE is realistic, technically stable and legally redistributable. If yes, bundle and test end-to-end. If no, keep OCR clearly labelled as optional external tools; the EXE must still perform all core scanning, text-subtitle and audio features without them. Never claim OCR is self-contained unless tested.
8. Add a manual GitHub Actions Windows workflow using a pinned or appropriately controlled runner and Python version, with tests before PyInstaller and a downloadable **Actions artifact** for the built EXE and licences. Include a SHA-256 of the resulting EXE. A `workflow_dispatch` trigger is sufficient. **Do not automatically publish GitHub Releases or upload anything outside this working repository.**
9. Check FFmpeg (LGPL/GPL, configuration-dependent), Subtitle Edit/Tesseract if redistributed, and PyInstaller licence and source redistribution obligations. Place full third-party licence notices, build provenance and source-availability instructions next to the release artifact as needed. Do not assume a project licence for my own source; note that I will decide one before making the repository public.
10. Improve error handling for nontechnical users: missing tools, interrupted conversions, insufficient disk space, incompatible file formats, corrupt media, permission errors, OCR failures and cancellation where feasible. Avoid arbitrary deletion or overwriting. Do not disable Microsoft Defender or ask users to bypass malware checks.

## Required deliverables in the working tree

- Source fixes and automated tests, with a list of changes.
- A deterministic Windows build script and/or PyInstaller spec with FFmpeg/FFprobe bundling.
- A Windows GitHub Actions workflow that creates **artifacts only**, not a release.
- A licence/provenance manifest for third-party binaries.
- An updated `README.md` explaining how to build, test, run and later publish via GitHub Releases.
- A `dist/LG_webOS_Media_Preparer.exe` if working on Windows, plus its SHA-256, and evidence of Windows and clean-machine checks. If on Linux/macOS and Windows build is unavailable, do not fake the EXE; provide the scripts and report this limitation.

## Acceptance criteria

- `python -m unittest discover -s tests -v` passes.
- The portable EXE starts the GUI on a Windows PC without Python or FFmpeg installed.
- `Scan only` leaves media untouched and writes reports.
- `Prepare` creates non-overwriting output, preserves the original file, and produces a playable compatible audio fallback and SRT in representative test clips.
- If the input has already-compatible audio, it is not re-encoded unnecessarily.
- 4K video/HDR is stream-copied in the normal LG profiles.
- Onefile EXE requires no installation (temporary runtime extraction is fine).
- OCR external dependencies, any unverified playback paths and untested Windows versions are explicitly stated.

Before changing anything, show me a brief implementation plan and tell me what parts of the existing code need attention. After implementing and running tests, report exact commands, test results, output filenames, SHA-256 hashes and remaining caveats. **Do not commit, push, create a repository, create a GitHub Release or publish anything. I will do those steps myself after reviewing the code.**
