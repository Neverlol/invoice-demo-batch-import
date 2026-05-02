param(
  [string]$ProjectRoot = "",
  [string]$SecretDir = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
  $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if ([string]::IsNullOrWhiteSpace($SecretDir)) {
  $SecretDir = Join-Path $ProjectRoot "_onsite_private_config"
  if (-not (Test-Path (Join-Path $SecretDir "onsite_secrets.json"))) {
    $SecretDir = Join-Path $ProjectRoot "_现场私密配置"
  }
}
$secretDir = $SecretDir
$secretPath = Join-Path $secretDir "onsite_secrets.json"

if (-not (Test-Path $secretPath)) {
  Write-Host "Missing private config file: $secretPath" -ForegroundColor Red
  exit 1
}

try {
  $cfg = Get-Content -Path $secretPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
  Write-Host "Failed to parse onsite_secrets.json: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}

function Require-Value([object]$value, [string]$name) {
  if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
    throw "Missing required config: $name"
  }
}

try {
  Require-Value $cfg.mimo_api_key "mimo_api_key"
  Require-Value $cfg.sync_token "sync_token"
  Require-Value $cfg.sync_tenant "sync_tenant"
  Require-Value $cfg.sync_endpoint "sync_endpoint"
} catch {
  Write-Host $_.Exception.Message -ForegroundColor Red
  exit 1
}

$llmConfig = [ordered]@{
  enabled = $true
  provider = if ($cfg.mimo_provider) { [string]$cfg.mimo_provider } else { "mimo_openai" }
  region = if ($cfg.mimo_region) { [string]$cfg.mimo_region } else { "cn" }
  endpoint = if ($cfg.mimo_endpoint) { [string]$cfg.mimo_endpoint } else { "https://api.xiaomimimo.com/v1/chat/completions" }
  model = if ($cfg.mimo_model) { [string]$cfg.mimo_model } else { "mimo-v2-omni" }
  api_key = [string]$cfg.mimo_api_key
  timeout_seconds = if ($cfg.mimo_timeout_seconds) { [int]$cfg.mimo_timeout_seconds } else { 25 }
  max_retries = if ($cfg.mimo_max_retries) { [int]$cfg.mimo_max_retries } else { 1 }
}

$syncConfig = [ordered]@{
  enabled = $true
  endpoint = [string]$cfg.sync_endpoint
  rules_endpoint = if ($cfg.rules_endpoint) { [string]$cfg.rules_endpoint } else { "" }
  profile_import_endpoint = if ($cfg.profile_import_endpoint) { [string]$cfg.profile_import_endpoint } else { "" }
  customer_profiles_endpoint = if ($cfg.customer_profiles_endpoint) { [string]$cfg.customer_profiles_endpoint } else { "" }
  token = [string]$cfg.sync_token
  tenant = [string]$cfg.sync_tenant
  timeout_seconds = if ($cfg.sync_timeout_seconds) { [int]$cfg.sync_timeout_seconds } else { 8 }
}

$llmPath = Join-Path $ProjectRoot "llm_client.local.json"
$syncPath = Join-Path $ProjectRoot "sync_client.local.json"

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($llmPath, ($llmConfig | ConvertTo-Json -Depth 8), $utf8NoBom)
[System.IO.File]::WriteAllText($syncPath, ($syncConfig | ConvertTo-Json -Depth 8), $utf8NoBom)

foreach ($path in @($llmPath, $syncPath)) {
  try {
    icacls $path /inheritance:r | Out-Null
    $currentUserGrant = $env:USERNAME + ':(R,W)'
    icacls $path /grant:r $currentUserGrant "Administrators:(F)" "SYSTEM:(F)" | Out-Null
  } catch {
    Write-Host "Warning: failed to tighten permissions for $path" -ForegroundColor Yellow
  }
}

[Environment]::SetEnvironmentVariable("TAX_INVOICE_MIMO_API_KEY", [string]$cfg.mimo_api_key, "User")
[Environment]::SetEnvironmentVariable("TAX_INVOICE_SYNC_TOKEN", [string]$cfg.sync_token, "User")
[Environment]::SetEnvironmentVariable("TAX_INVOICE_SYNC_TENANT", [string]$cfg.sync_tenant, "User")
[Environment]::SetEnvironmentVariable("TAX_INVOICE_SYNC_ENDPOINT", [string]$cfg.sync_endpoint, "User")

if ($cfg.delete_source_after_install -eq $true) {
  Remove-Item -Path $secretPath -Force
  Write-Host "Deleted source private config file: $secretPath" -ForegroundColor Yellow
} else {
  Write-Host "Source private config file remains at: $secretPath" -ForegroundColor Yellow
  Write-Host "After onsite installation is verified, delete the private config folder manually." -ForegroundColor Yellow
}

Write-Host "Created: llm_client.local.json" -ForegroundColor Green
Write-Host "Created: sync_client.local.json" -ForegroundColor Green
Write-Host "MiMo, sync center, and customer profile config installed." -ForegroundColor Green
exit 0
