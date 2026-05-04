$ErrorActionPreference = "Stop"

function Write-LogLine {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    if ($script:LogPath) {
        Add-Content -Path $script:LogPath -Value $line -Encoding UTF8
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$BackupsDir = Join-Path $Root "backups"
$LogsDir = Join-Path $Root "update_logs"
New-Item -ItemType Directory -Force -Path $BackupsDir, $LogsDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$script:LogPath = Join-Path $LogsDir "restore-$timestamp.log"
New-Item -ItemType File -Force -Path $script:LogPath | Out-Null

$lastFile = Join-Path $BackupsDir "LAST_BACKUP.txt"
if (Test-Path $lastFile) {
    $backupDir = (Get-Content -Raw -Path $lastFile -Encoding UTF8).Trim()
} else {
    $latest = Get-ChildItem -Path $BackupsDir -Directory -Filter "backup-*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $latest) { throw "No backup directory found." }
    $backupDir = $latest.FullName
}

if (-not (Test-Path $backupDir)) { throw "Backup directory not found: $backupDir" }
$manifestPath = Join-Path $backupDir "BACKUP_MANIFEST.json"
if (-not (Test-Path $manifestPath)) { throw "Backup manifest not found: $manifestPath" }

$manifest = Get-Content -Raw -Path $manifestPath -Encoding UTF8 | ConvertFrom-Json
Write-LogLine "Root: $Root"
Write-LogLine "Restoring backup: $backupDir"
Write-LogLine "Backup version: $($manifest.version)"

foreach ($item in $manifest.files) {
    $relative = [string]$item.path
    $target = Join-Path $Root $relative
    $backupFile = Join-Path $backupDir $relative
    if ($item.existed -eq $true) {
        if (-not (Test-Path $backupFile)) {
            throw "Expected backup file missing: $backupFile"
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $backupFile -Destination $target -Force
        Write-LogLine "Restored: $relative"
    } else {
        if (Test-Path $target) {
            Remove-Item -LiteralPath $target -Force
            Write-LogLine "Removed newly created file: $relative"
        }
    }
}

$versionText = @(
    "version: restored-from-$($manifest.version)",
    "restored_at: $((Get-Date).ToString('s'))",
    "restored_backup: $backupDir",
    "log: $script:LogPath"
) -join [Environment]::NewLine
Set-Content -Path (Join-Path $Root "VERSION.txt") -Value $versionText -Encoding UTF8
Write-LogLine "Restore complete. Restart workbench and press Ctrl+F5 in browser."
