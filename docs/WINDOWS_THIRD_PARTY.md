# Windows portable build third-party notices

The application uses separate FFmpeg, FFprobe, SeConv and Tesseract processes. This inventory covers the distribution build made by `build_windows.ps1`. The generated `provenance.json` records the inputs, input hashes, extracted payload hashes, Windows imports, and exact NuGet dependency hashes. The corresponding-source bundle supplies source archives and the build recipes and configurations used for the native executables.

| Component | Origin and terms |
| --- | --- |
| FFmpeg and FFprobe 9.0.2 | Built from the official source with `--enable-gpl --enable-libx264` and with network protocols disabled. GPL-2.0-or-later as configured. [FFmpeg licence](https://ffmpeg.org/legal.html) |
| x264 | Built from VideoLAN commit `b35605ace3ddf7c1a5d67a2eb553f034aef41d55`. GPL-2.0-or-later. [VideoLAN x264](https://www.videolan.org/developers/x264.html) |
| Tesseract 5.5.3 | Apache 2.0. The OCR CLI is built from source with Leptonica 1.87.0, libpng 1.6.59 and zlib 1.4. Leptonica, libpng and zlib have separate permissive notices. [Tesseract source](https://github.com/tesseract-ocr/tesseract/tree/5.5.3) |
| English OCR model | `tessdata_fast` 4.1.0 under Apache 2.0. [Model and licence](https://github.com/tesseract-ocr/tessdata_fast/tree/4.1.0) |
| Subtitle Edit SeConv 5.4.0 | MIT. Rebuilt as a self-contained Windows x64 tool with the unused spell-check bundle omitted. The corresponding-source archive records the patch. [Subtitle Edit source](https://github.com/SubtitleEdit/subtitleedit/tree/v5.4.0) |
| SeConv dependencies | .NET 10.0.14, SkiaSharp, HarfBuzzSharp, Spectre.Console, CommunityToolkit.Mvvm, WeCantSpell.Hunspell and UTF.Unknown. The notices archive contains their exact build notices, including the MPL 1.1 terms for UTF.Unknown. Its matching source is included in the corresponding-source archive. |
| Windows build runtimes | The native tools use the Windows UCRT and statically linked MinGW/GCC runtime components. Their notices include the GCC Runtime Library Exception and MinGW terms. |
| Python and GUI | CPython 3.14.10 and Tcl/Tk 9.0.4. The build uses the standard PyInstaller 6.22.3 bootloader and its packaging exception. [Python licensing](https://docs.python.org/3.14/license.html) · [PyInstaller licence](https://pyinstaller.org/en/stable/license.html) |

When distributing the executable, make its checksum, `provenance.json`, `third-party-notices.zip`, and `third-party-sources.zip` available with it. Keep the corresponding sources available to recipients of the same build. The repository owner controls the application’s own licence and release process.
