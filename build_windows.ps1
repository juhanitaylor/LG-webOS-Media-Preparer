[CmdletBinding()]
param([string]$Python)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildRoot = Join-Path $PSScriptRoot 'build'
if (!$Python) {
    $localPython = Join-Path $buildRoot 'python314\python.exe'
    $Python = if (Test-Path -LiteralPath $localPython) { $localPython } else { 'python.exe' }
}

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    # Windows PowerShell can turn redirected native stderr into ErrorRecords, including unittest output.
    $ErrorActionPreference = 'Continue'
    $PSNativeCommandUseErrorActionPreference = $false
    & $Program @Arguments 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message }
        else { $_ }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$Program exited with code $LASTEXITCODE"
    }
}

$previousPath = $env:PATH
$previousSmoke = $env:LG_MEDIA_PORTABLE_EXE
$previousCache = $env:PYINSTALLER_CONFIG_DIR
try {
    Invoke-Checked $Python @('-B', '-c', 'import sys,platform; assert sys.version_info[:3] == (3,14,10) and platform.machine() == ''AMD64'', (sys.version, platform.machine()); import tkinter')
    $venv = Join-Path $buildRoot 'packaging-venv'
    $buildPython = Join-Path $venv 'Scripts\python.exe'
    if (!(Test-Path -LiteralPath $buildPython)) {
        Invoke-Checked $Python @('-B', '-m', 'venv', $venv)
    }
    Invoke-Checked $buildPython @('-B', '-m', 'pip', '--disable-pip-version-check', 'install',
        '--only-binary=:all:', '--require-hashes', '-r', 'requirements-build.txt')
    Invoke-Checked $buildPython @('-B', 'scripts\prepare_windows_native.py')

    $env:PATH = (Join-Path $buildRoot 'windows-payload\tools') + ';' + $previousPath
    $env:LG_MEDIA_PORTABLE_EXE = $null
    Invoke-Checked $buildPython @('-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v')

    $env:PYINSTALLER_CONFIG_DIR = Join-Path $buildRoot 'pyinstaller-cache'
    $candidateDir = Join-Path $buildRoot 'windows-candidate'
    $exeName = Invoke-Checked $buildPython @('-B', 'scripts\windows_release_name.py')
    Invoke-Checked $buildPython @('-B', '-m', 'PyInstaller', '--noconfirm',
        '--distpath', $candidateDir, '--workpath', (Join-Path $buildRoot 'pyinstaller-work'),
        'LG_webOS_Media_Preparer.spec')

    $env:LG_MEDIA_PORTABLE_EXE = Join-Path $candidateDir $exeName
    Invoke-Checked $buildPython @('-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_windows_ocr.py', '-v')
    Invoke-Checked $buildPython @('-B', 'scripts\check_windows_exe.py', $env:LG_MEDIA_PORTABLE_EXE)
    Invoke-Checked $buildPython @('-B', 'scripts\collect_windows_release.py', $env:LG_MEDIA_PORTABLE_EXE)
}
finally {
    $env:PATH = $previousPath
    $env:LG_MEDIA_PORTABLE_EXE = $previousSmoke
    $env:PYINSTALLER_CONFIG_DIR = $previousCache
}
