param([switch]$Repair)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pinRoot = Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
$appId = 'EtaSwCwj.tokiDownloader.GUI.1'
$target = Join-Path $repoRoot '.venv\Scripts\pythonw.exe'
$launcher = Join-Path $repoRoot 'toki_launcher.py'
$arguments = '"' + $launcher + '" launch'
$icon = (Join-Path $repoRoot 'assets\toki-downloader.ico') + ',0'
$wsh = New-Object -ComObject WScript.Shell
$shellApp = New-Object -ComObject Shell.Application
$results = @()
if (Test-Path -LiteralPath $pinRoot) {
    $folder = $shellApp.Namespace($pinRoot)
    foreach ($file in Get-ChildItem -LiteralPath $pinRoot -Filter '*.lnk' -File) {
        $item = $folder.ParseName($file.Name)
        # The name 'Python' alone proves nothing: never touch another Python app.
        if ($item.ExtendedProperty('System.AppUserModel.ID') -ne $appId) { continue }
        $link = $wsh.CreateShortcut($file.FullName)
        $before = @{target=$link.TargetPath; arguments=$link.Arguments; workingDirectory=$link.WorkingDirectory; icon=$link.IconLocation}
        $needsRepair = $link.TargetPath -ne $target -or $link.Arguments -ne $arguments -or $link.WorkingDirectory -ne $repoRoot -or $link.IconLocation -ne $icon
        $backup = $null
        if ($Repair -and $needsRepair) {
            foreach ($required in @($target, $launcher, ($icon -replace ',0$', ''))) {
                if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing launcher dependency: $required" }
            }
            $backupRoot = Join-Path $repoRoot ('logs\shortcut-backups\' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss-fffffff'))
            New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
            $backup = Join-Path $backupRoot $file.Name
            Copy-Item -LiteralPath $file.FullName -Destination $backup
            try {
                $link.TargetPath = $target
                $link.Arguments = $arguments
                $link.WorkingDirectory = $repoRoot
                $link.IconLocation = $icon
                $link.Description = 'tokiDownloader'
                $link.WindowStyle = 7
                $link.Save()
                $link = $wsh.CreateShortcut($file.FullName)
                $verifiedItem = $shellApp.Namespace($pinRoot).ParseName($file.Name)
                if ($link.TargetPath -ne $target -or $link.Arguments -ne $arguments -or $link.WorkingDirectory -ne $repoRoot -or $link.IconLocation -ne $icon -or $verifiedItem.ExtendedProperty('System.AppUserModel.ID') -ne $appId) {
                    throw 'Shortcut verification failed'
                }
            } catch {
                Copy-Item -LiteralPath $backup -Destination $file.FullName -Force
                throw
            }
        }
        $results += @{path=$file.FullName; appId=$appId; needsRepair=($needsRepair -and -not $Repair); repaired=($needsRepair -and [bool]$Repair); backup=$backup; before=$before; target=$link.TargetPath; arguments=$link.Arguments; workingDirectory=$link.WorkingDirectory; icon=$link.IconLocation}
    }
}
@{ok=$true; repairRequested=[bool]$Repair; matchedCount=$results.Count; shortcuts=$results} | ConvertTo-Json -Depth 6
