[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$WithImageTools,
    [switch]$WithArchiveTools,
    [switch]$WithBrowserTools,
    [switch]$WithSecurityTools,
    [switch]$WithYouTube
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

function Require-Command {
    param([Parameter(Mandatory)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Required command was not found: $Name"
    }
    return $command.Source
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$Program,
        [Parameter(ValueFromRemainingArguments)][string[]]$Arguments
    )
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Program $($Arguments -join ' ')"
    }
}

$pyLauncher = Require-Command 'py.exe'
$node = Require-Command 'node.exe'
$npm = Require-Command 'npm.cmd'
$pythonVersionText = & $pyLauncher -3 -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3 could not be executed.'
}
$pythonVersion = [version]$pythonVersionText.Trim()
if ($pythonVersion -lt [version]'3.10') {
    throw "Python 3.10 or newer is required. Current: $pythonVersion"
}

$requiredFiles = @(
    'package.json',
    'package-lock.json',
    'requirements-gui.txt',
    'requirements-archive-tools.txt',
    'requirements-browser-tools.txt',
    'requirements-security.txt',
    'requirements-youtube.txt',
    'toki_app.py',
    'toki_gui.py',
    'youtube_worker.py',
    'down.js'
)
$missingFiles = @(
    $requiredFiles | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $projectRoot $_) -PathType Leaf)
    }
)
if ($missingFiles.Count -gt 0) {
    throw "Required setup files are missing: $($missingFiles -join ', ')"
}

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$puppeteerManifest = Join-Path $projectRoot 'node_modules\puppeteer-real-browser\package.json'

if (-not $CheckOnly) {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Host '[1/4] Creating the Python virtual environment.'
        Invoke-Checked -Program $pyLauncher -Arguments @(
            '-3', '-m', 'venv', (Join-Path $projectRoot '.venv')
        )
    } else {
        Write-Host '[1/4] Reusing the Python virtual environment.'
    }

    Write-Host '[2/4] Installing GUI Python dependencies.'
    Invoke-Checked -Program $venvPython -Arguments @(
        '-m', 'pip', 'install', '--disable-pip-version-check',
        '-r', (Join-Path $projectRoot 'requirements-gui.txt')
    )
    if ($WithImageTools) {
        Invoke-Checked -Program $venvPython -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check',
            '-r', (Join-Path $projectRoot 'requirements-image-tools.txt')
        )
    }
    if ($WithArchiveTools) {
        Invoke-Checked -Program $venvPython -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check',
            '-r', (Join-Path $projectRoot 'requirements-archive-tools.txt')
        )
    }
    if ($WithBrowserTools) {
        Invoke-Checked -Program $venvPython -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check',
            '-r', (Join-Path $projectRoot 'requirements-browser-tools.txt')
        )
    }
    if ($WithSecurityTools) {
        Invoke-Checked -Program $venvPython -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check',
            '-r', (Join-Path $projectRoot 'requirements-security.txt')
        )
    }
    if ($WithYouTube) {
        Invoke-Checked -Program $venvPython -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check',
            '-r', (Join-Path $projectRoot 'requirements-youtube.txt')
        )
    }

    Write-Host '[3/4] Restoring Node.js dependencies from package-lock.json.'
    Invoke-Checked -Program $npm -Arguments @('ci', '--no-audit', '--no-fund')
} else {
    Write-Host '[check] Validating installed files and runtime dependencies.'
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw '.venv is missing. Run setup-gui.cmd first.'
    }
    if (-not (Test-Path -LiteralPath $puppeteerManifest -PathType Leaf)) {
        throw 'Puppeteer is missing. Run setup-gui.cmd first.'
    }
}

Write-Host '[4/4] Running the tokiDownloader dependency doctor.'
$doctorOutput = & $venvPython (Join-Path $projectRoot 'toki_app.py') doctor --json
if ($LASTEXITCODE -ne 0) {
    throw 'The dependency doctor command failed.'
}
$doctor = $doctorOutput | ConvertFrom-Json
if (-not $doctor.ok) {
    throw "Required dependency checks failed: $($doctor.required.missing -join ', ')"
}
if ($WithYouTube) {
    $youtubeCheck = $doctor.checks | Where-Object { $_.name -eq 'yt-dlp' } | Select-Object -First 1
    if (-not $youtubeCheck -or -not $youtubeCheck.available) {
        throw 'yt-dlp is missing. Run setup-gui.cmd -WithYouTube.'
    }
}

Write-Output $doctorOutput
Write-Host "Setup check passed: Python $pythonVersion, Node.js $(& $node --version), required $($doctor.required.passed)/$($doctor.required.total)"
