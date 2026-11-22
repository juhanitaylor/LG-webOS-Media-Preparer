# Windows OCR third-party components

The OCR payload contains separate command-line programs. The stage script records the original asset URLs and SHA-256 values in `notices/ocr-provenance.json`.

| Component | Version and upstream | Licence |
| --- | --- | --- |
| Subtitle Edit SeConv | [5.4.0 Windows x64 release](https://github.com/SubtitleEdit/subtitleedit/releases/tag/v5.4.0) | [MIT](https://github.com/SubtitleEdit/subtitleedit/blob/v5.4.0/LICENSE). The upstream archive includes the licence. |
| Tesseract | [5.5.3 portable x64 runtime](https://github.com/SubtitleEdit/support-files/releases/tag/tesseract553), repacked from the [Tesseract Windows installer](https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3) | [Apache 2.0](https://github.com/tesseract-ocr/tesseract/blob/5.5.3/LICENSE) for Tesseract. The package includes separately licensed DLLs. |
| Tesseract language data | [English tessdata_fast 4.1.0](https://github.com/tesseract-ocr/tessdata_fast/tree/4.1.0); the portable archive supplies its additional orientation data and hOCR config | [Apache 2.0](https://github.com/tesseract-ocr/tessdata_fast/blob/4.1.0/LICENSE) |
| .NET runtime | 10.0.14, embedded in the self-contained SeConv executable | [MIT and .NET dependency notices](https://github.com/dotnet/runtime/blob/v10.0.14/THIRD-PARTY-NOTICES.TXT) |
| Image and text libraries | SeConv includes SkiaSharp, HarfBuzzSharp, and packaged .NET libraries and dictionaries | Preserve their applicable licences, copyright notices, and data attribution from the exact SeConv build. [SeConv source](https://github.com/SubtitleEdit/subtitleedit/tree/v5.4.0/src/seconv) |

## Before redistribution

The OCR staging script preserves the notices from the archives and adds the primary project licences. The portable Tesseract archive supplies runtime binaries and data. It omits licence texts and version metadata for its DLLs. Before distributing it, inventory the exact dependency versions from the [upstream Windows installer build](https://github.com/tesseract-ocr/tesseract/blob/5.5.3/nsis/build.sh), which uses MinGW and MSYS2 packages. Include each component's full copyright and licence texts and provide any corresponding source, build information and relinking materials that its licence requires. In particular, check `libjbig`, `libintl`, `libiconv`, `libidn2`, and `libunistring` for copyleft obligations. Use a traceable replacement build if the corresponding source for the repacked runtime cannot be obtained.

Check the self-contained SeConv package for matching .NET, native Skia and HarfBuzz, managed dependency, and embedded dictionary notices. Include the final notices in an accessible location alongside the distributed executable. FFmpeg, FFprobe and PyInstaller distribution requirements remain part of the separate Windows packaging work.
