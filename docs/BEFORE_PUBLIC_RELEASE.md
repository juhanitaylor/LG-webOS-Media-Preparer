# Before publishing this repository or an EXE

- [ ] Inspect all code and choose a project software licence. No source licence has been selected in this starter package.
- [ ] Confirm the model-specific LG profiles against test hardware or manufacturer documentation. Avoid claiming universal LG compatibility.
- [ ] Run Python unit and FFmpeg integration tests; smoke test the Windows GUI.
- [ ] Produce a Windows-built EXE, then smoke test with no Python/FFmpeg installed on the test machine.
- [ ] Include the precise FFmpeg version, binary origin, checksum and LGPL/GPL obligations; offer corresponding source as required.
- [ ] Check the status and licensing of any OCR binaries/language data if bundled.
- [ ] Check EXE SHA-256, antivirus results, Windows SmartScreen considerations and whether the build is signed.
- [ ] Mark OCR limitations, Dolby Vision uncertainty, and no HDR tone mapping prominently in release notes.
- [ ] Keep GitHub Actions as a manual artifact generator; review generated files before manually publishing a release.
