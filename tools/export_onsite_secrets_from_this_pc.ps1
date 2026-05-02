param(
  [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
  $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

function Require-Value([object]$value, [string]$name) {
  if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
    throw "Missing required config: $name"
  }
}

$mimoApiKey = [Environment]::GetEnvironmentVariable("TAX_INVOICE_MIMO_API_KEY", "User")
if ([string]::IsNullOrWhiteSpace($mimoApiKey)) {
  $mimoApiKey = [Environment]::GetEnvironmentVariable("TAX_INVOICE_MIMO_API_KEY", "Machine")
}
if ([string]::IsNullOrWhiteSpace($mimoApiKey)) {
  $mimoApiKey = [Environment]::GetEnvironmentVariable("TAX_INVOICE_MIMO_API_KEY", "Process")
}

try {
  Require-Value $mimoApiKey "Windows environment variable TAX_INVOICE_MIMO_API_KEY"
} catch {
  Write-Host $_.Exception.Message -ForegroundColor Red
  Write-Host "Please run this exporter on a PC where MiMo is already configured." -ForegroundColor Yellow
  exit 1
}

$syncPath = Join-Path $ProjectRoot "sync_client.local.json"
if (-not (Test-Path $syncPath)) {
  Write-Host "Missing sync_client.local.json: $syncPath" -ForegroundColor Red
  exit 1
}

try {
  $sync = Get-Content -Path $syncPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
  Write-Host "Failed to parse sync_client.local.json: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}

try {
  Require-Value $sync.endpoint "sync_client.local.json.endpoint"
  Require-Value $sync.token "sync_client.local.json.token"
  Require-Value $sync.tenant "sync_client.local.json.tenant"
} catch {
  Write-Host $_.Exception.Message -ForegroundColor Red
  exit 1
}

$secretDir = Join-Path $ProjectRoot "_onsite_private_config"
New-Item -ItemType Directory -Force -Path $secretDir | Out-Null
$secretPath = Join-Path $secretDir "onsite_secrets.json"

$cfg = [ordered]@{
  mimo_api_key = [string]$mimoApiKey
  mimo_provider = "mimo_openai"
  mimo_region = "cn"
  mimo_endpoint = "https://api.xiaomimimo.com/v1/chat/completions"
  mimo_model = "mimo-v2-omni"
  mimo_timeout_seconds = 25
  mimo_max_retries = 1

  sync_endpoint = [string]$sync.endpoint
  sync_token = [string]$sync.token
  sync_tenant = [string]$sync.tenant
  sync_timeout_seconds = if ($sync.timeout_seconds) { [int]$sync.timeout_seconds } else { 8 }

  rules_endpoint = if ($sync.rules_endpoint) { [string]$sync.rules_endpoint } else { "" }
  profile_import_endpoint = if ($sync.profile_import_endpoint) { [string]$sync.profile_import_endpoint } else { "" }
  customer_profiles_endpoint = if ($sync.customer_profiles_endpoint) { [string]$sync.customer_profiles_endpoint } else { "" }

  delete_source_after_install = $true
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($secretPath, ($cfg | ConvertTo-Json -Depth 8), $utf8NoBom)

try {
  icacls $secretPath /inheritance:r | Out-Null
  $currentUserGrant = $env:USERNAME + ':(R,W)'
  icacls $secretPath /grant:r $currentUserGrant "Administrators:(F)" "SYSTEM:(F)" | Out-Null
} catch {
  Write-Host "Warning: failed to tighten file permissions, but the secret file was created." -ForegroundColor Yellow
}

Write-Host "Created: $secretPath" -ForegroundColor Green
Write-Host "Save the _onsite_private_config folder separately and copy it to the new PC install directory." -ForegroundColor Green
exit 0
