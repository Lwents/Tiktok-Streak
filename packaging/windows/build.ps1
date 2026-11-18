$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$BuildPython = Join-Path $Root '.venv\Scripts\python.exe'
$InnoPaths = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
)
$Inno = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($Inno) { $Inno = $Inno.Source }
else { $Inno = $InnoPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1 }
if (-not $Inno) { throw 'Install Inno Setup 6 before building the installer.' }
if (-not (Test-Path -LiteralPath $BuildPython)) { throw 'Run setup.bat before building.' }

Push-Location $Root
try {
    & $BuildPython -m pip install -r requirements-build.txt
    if ($LASTEXITCODE) { throw 'Could not install the build dependencies.' }

    New-Item -ItemType Directory -Path 'build' -Force | Out-Null
    $Bootstrapper = Join-Path $Root 'build\MicrosoftEdgeWebView2Setup.exe'
    if (-not (Test-Path -LiteralPath $Bootstrapper)) {
        Invoke-WebRequest -UseBasicParsing -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $Bootstrapper
    }
    $Signature = Get-AuthenticodeSignature -LiteralPath $Bootstrapper
    if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'CN=Microsoft Corporation(?:,|$)') {
        throw 'The WebView2 bootstrapper does not have a valid Microsoft signature.'
    }

    $Icon = Join-Path $Root 'assets\streak.ico'
    & $BuildPython -m PyInstaller --noconfirm --clean --windowed --noupx --name 'TikTok Streak' `
        --specpath build --icon $Icon --add-data "$($Icon):assets" `
        --add-data "$Root\browser:browser" --add-data "$Root\web:web" windows_app.py
    if ($LASTEXITCODE) { throw 'Could not build the Windows application.' }

    & $Inno (Join-Path $PSScriptRoot 'TikTokStreak.iss')
    if ($LASTEXITCODE) { throw 'Could not build the installer.' }
    Write-Host "Installer: $Root\release\TikTok-Streak-Setup.exe"
}
finally {
    Pop-Location
}
