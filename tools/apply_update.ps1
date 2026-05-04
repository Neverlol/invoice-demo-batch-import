$ErrorActionPreference = "Stop"

function Write-LogLine {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    if ($script:LogPath) {
        Add-Content -Path $script:LogPath -Value $line -Encoding UTF8
    }
}

function Get-RelativePathSafe {
    param([string]$BasePath, [string]$FullPath)
    $base = [System.IO.Path]::GetFullPath($BasePath).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $full = [System.IO.Path]::GetFullPath($FullPath)
    if (-not $full.StartsWith($base, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside base directory: $FullPath"
    }
    return $full.Substring($base.Length).TrimStart([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
}

function Assert-SafeRelativePath {
    param([string]$RelativePath)
    $normalized = $RelativePath.Replace("/", "\")
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        throw "Empty path in update package."
    }
    if ([System.IO.Path]::IsPathRooted($normalized) -or $normalized.Contains("..")) {
        throw "Unsafe path in update package: $RelativePath"
    }
    $lower = $normalized.ToLowerInvariant()
    $blockedExact = @(
        "sync_client.local.json",
        "llm_client.local.json",
        "onsite_secrets.local.json",
        "onsite_secrets.json"
    )
    foreach ($blocked in $blockedExact) {
        if ($lower -eq $blocked) {
            throw "Update package must not contain private config: $RelativePath"
        }
    }
    $blockedPrefixes = @(
        ".git\",
        ".venv\",
        "output\",
        "backups\",
        "update_logs\",
        "updates\"
    )
    foreach ($prefix in $blockedPrefixes) {
        if ($lower.StartsWith($prefix)) {
            throw "Update package contains blocked runtime path: $RelativePath"
        }
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$UpdatesDir = Join-Path $Root "updates"
$BackupsDir = Join-Path $Root "backups"
$LogsDir = Join-Path $Root "update_logs"
$UpdateZip = Join-Path $UpdatesDir "latest.zip"

New-Item -ItemType Directory -Force -Path $UpdatesDir, $BackupsDir, $LogsDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$script:LogPath = Join-Path $LogsDir "update-$timestamp.log"
New-Item -ItemType File -Force -Path $script:LogPath | Out-Null

Write-LogLine "Root: $Root"
Write-LogLine "Package: $UpdateZip"

if (-not (Test-Path $UpdateZip)) {
    throw "Missing update package: $UpdateZip"
}

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "invoice-assistant-update-$timestamp"
if (Test-Path $tempDir) { Remove-Item -Recurse -Force $tempDir }
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

try {
    Write-LogLine "Extracting package to temp directory..."
    Expand-Archive -LiteralPath $UpdateZip -DestinationPath $tempDir -Force

    $manifestPath = Join-Path $tempDir "UPDATE_MANIFEST.txt"
    $version = "unknown"
    $packageName = Split-Path -Leaf $UpdateZip
    if (Test-Path $manifestPath) {
        $manifestText = Get-Content -Raw -Path $manifestPath -Encoding UTF8
        $match = [regex]::Match($manifestText, "(?m)^version:\s*(.+?)\s*$")
        if ($match.Success) { $version = $match.Groups[1].Value.Trim() }
        $nameMatch = [regex]::Match($manifestText, "(?m)^name:\s*(.+?)\s*$")
        if ($nameMatch.Success) { $packageName = $nameMatch.Groups[1].Value.Trim() }
    } else {
        Write-LogLine "WARNING: UPDATE_MANIFEST.txt not found in package."
    }

    $safeVersion = ($version -replace "[^A-Za-z0-9_.-]", "_")
    if ([string]::IsNullOrWhiteSpace($safeVersion)) { $safeVersion = "unknown" }
    $backupDir = Join-Path $BackupsDir "backup-$timestamp-$safeVersion"
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

    $files = Get-ChildItem -Path $tempDir -Recurse -File | Sort-Object FullName
    if ($files.Count -eq 0) { throw "Update package has no files." }

    $items = @()
    foreach ($file in $files) {
        $relative = Get-RelativePathSafe -BasePath $tempDir -FullPath $file.FullName
        $relative = $relative.Replace("/", "\")
        Assert-SafeRelativePath -RelativePath $relative
        $target = Join-Path $Root $relative
        $backupTarget = Join-Path $backupDir $relative
        $existed = Test-Path $target
        if ($existed) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupTarget) | Out-Null
            Copy-Item -LiteralPath $target -Destination $backupTarget -Force
            Write-LogLine "Backed up: $relative"
        } else {
            Write-LogLine "New file: $relative"
        }
        $items += [pscustomobject]@{
            path = $relative
            existed = [bool]$existed
        }
    }

    $backupManifest = [pscustomobject]@{
        version = $version
        package = $packageName
        applied_at = (Get-Date).ToString("s")
        root = $Root
        files = $items
    }
    $backupManifestPath = Join-Path $backupDir "BACKUP_MANIFEST.json"
    $backupManifest | ConvertTo-Json -Depth 5 | Set-Content -Path $backupManifestPath -Encoding UTF8

    Write-LogLine "Applying files..."
    foreach ($file in $files) {
        $relative = Get-RelativePathSafe -BasePath $tempDir -FullPath $file.FullName
        $relative = $relative.Replace("/", "\")
        $target = Join-Path $Root $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        Write-LogLine "Applied: $relative"
    }

    $versionText = @(
        "version: $version",
        "package: $packageName",
        "applied_at: $((Get-Date).ToString('s'))",
        "backup: $backupDir",
        "log: $script:LogPath"
    ) -join [Environment]::NewLine
    Set-Content -Path (Join-Path $Root "VERSION.txt") -Value $versionText -Encoding UTF8
    Set-Content -Path (Join-Path $BackupsDir "LAST_BACKUP.txt") -Value $backupDir -Encoding UTF8

    Write-LogLine "Update complete. Version: $version"
    Write-LogLine "Backup: $backupDir"
    Write-LogLine "Restart workbench and press Ctrl+F5 in browser."
}
finally {
    if (Test-Path $tempDir) {
        Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
    }
}
