[CmdletBinding()]
param(
    [string]$Output = '',
    [switch]$KeepWorkspace
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$workspace = Join-Path $tempRoot ("toki-clean-install-" + [guid]::NewGuid().ToString('N'))
$source = Join-Path $workspace 'source'
$archive = Join-Path $workspace 'source.zip'
$reportPath = if ($Output) {
    if ([IO.Path]::IsPathRooted($Output)) {
        [IO.Path]::GetFullPath($Output)
    } else {
        [IO.Path]::GetFullPath((Join-Path $projectRoot $Output))
    }
} else {
    Join-Path $projectRoot 'logs\clean-install-smoke.json'
}
$started = Get-Date
$report = [ordered]@{
    ok = $false
    startedAt = $started.ToString('o')
    finishedAt = $null
    durationMs = 0
    source = 'git archive HEAD'
    workspaceRemoved = $false
    setup = $null
    doctor = $null
    selfTest = $null
    error = ''
}

try {
    New-Item -ItemType Directory -Path $workspace -Force | Out-Null
    & git -C $projectRoot archive --format=zip --output=$archive HEAD
    if ($LASTEXITCODE -ne 0) {
        throw 'git archive failed.'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $source -Force
    $setupStarted = Get-Date
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $setupOutput = & (Join-Path $source 'setup-gui.cmd') 2>&1 |
        ForEach-Object { $_.ToString() } | Out-String
    $setupExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorPreference
    if ($setupExitCode -ne 0) {
        throw "setup-gui.cmd failed.`n$setupOutput"
    }
    $report.setup = [ordered]@{
        ok = $true
        durationMs = [math]::Round(((Get-Date) - $setupStarted).TotalMilliseconds)
    }

    $doctorRaw = & (Join-Path $source 'toki-cli.cmd') doctor --json | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw 'doctor failed in the clean workspace.'
    }
    $doctor = $doctorRaw | ConvertFrom-Json
    $report.doctor = [ordered]@{
        ok = [bool]$doctor.ok
        requiredPassed = [int]$doctor.required.passed
        requiredTotal = [int]$doctor.required.total
        appVersion = [string]$doctor.platform.appVersion
    }

    $selfTestRaw = & (Join-Path $source 'toki-cli.cmd') self-test --json | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw 'self-test failed in the clean workspace.'
    }
    $selfTest = $selfTestRaw | ConvertFrom-Json
    $guiCheck = $selfTest.checks | Where-Object { $_.name -eq 'gui_ipc' } | Select-Object -First 1
    $report.selfTest = [ordered]@{
        ok = [bool]$selfTest.ok
        passed = [int]$selfTest.summary.passed
        total = [int]$selfTest.summary.total
        guiIpc = [bool]$guiCheck.ok
    }
    $report.ok = [bool]($doctor.ok -and $selfTest.ok -and $guiCheck.ok)
} catch {
    $report.error = $_.Exception.Message
} finally {
    if (-not $KeepWorkspace -and (Test-Path -LiteralPath $workspace)) {
        $resolvedWorkspace = [IO.Path]::GetFullPath($workspace)
        if (
            $resolvedWorkspace.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $resolvedWorkspace).StartsWith('toki-clean-install-')
        ) {
            Remove-Item -LiteralPath $resolvedWorkspace -Recurse -Force
        }
    }
    $report.workspaceRemoved = -not (Test-Path -LiteralPath $workspace)
    $finished = Get-Date
    $report.finishedAt = $finished.ToString('o')
    $report.durationMs = [math]::Round(($finished - $started).TotalMilliseconds)
    $reportDirectory = Split-Path -Parent $reportPath
    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
    $temporaryReport = "$reportPath.tmp"
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryReport -Encoding UTF8
    Move-Item -LiteralPath $temporaryReport -Destination $reportPath -Force
}

$report | ConvertTo-Json -Depth 8
if (-not $report.ok) {
    exit 1
}
