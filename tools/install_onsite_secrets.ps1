param(
  [string]$ProjectRoot = "",
  [string]$SecretDir = ""
)

$ErrorActionPreference = "Stop"

function Require-Value([object]$value, [string]$name) {
  if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
    throw "Missing required config: $name"
  }
}

function Value-OrDefault([object]$value, [string]$defaultValue) {
  if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
    return $defaultValue
  }
  return [string]$value
}

function Int-OrDefault([object]$value, [int]$defaultValue) {
  if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
    return $defaultValue
  }
  try {
    return [int]$value
  } catch {
    return $defaultValue
  }
}

function Get-ChineseSecretFolderName {
  # Build "_现场私密配置" without non-ASCII source text for Windows PowerShell 5.1 encoding safety.
  return "_" + ([char]0x73B0) + ([char]0x573A) + ([char]0x79C1) + ([char]0x5BC6) + ([char]0x914D) + ([char]0x7F6E)
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
  $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

# Defend against cmd.exe quoted trailing-backslash argument issues.
$ProjectRoot = [string]$ProjectRoot
$ProjectRoot = $ProjectRoot.Trim().Trim('"')
$ProjectRoot = $ProjectRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

if ([string]::IsNullOrWhiteSpace($SecretDir)) {
  $AsciiSecretDir = Join-Path $ProjectRoot "_onsite_private_config"
  $ChineseSecretDir = Join-Path $ProjectRoot (Get-ChineseSecretFolderName)
  if (Test-Path -LiteralPath (Join-Path $AsciiSecretDir "onsite_secrets.json")) {
    $SecretDir = $AsciiSecretDir
  } elseif (Test-Path -LiteralPath (Join-Path $ChineseSecretDir "onsite_secrets.json")) {
    $SecretDir = $ChineseSecretDir
  } else {
    $SecretDir = $AsciiSecretDir
  }
} else {
  $SecretDir = [string]$SecretDir
  $SecretDir = $SecretDir.Trim().Trim('"')
  $SecretDir = $SecretDir.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
}

$secretPath = Join-Path $SecretDir "onsite_secrets.json"

if (-not (Test-Path -LiteralPath $secretPath)) {
  Write-Host "Missing private config file." -ForegroundColor Red
  Write-Host "Expected one of:" -ForegroundColor Yellow
  Write-Host (Join-Path (Join-Path $ProjectRoot "_onsite_private_config") "onsite_secrets.json") -ForegroundColor Yellow
  Write-Host (Join-Path (Join-Path $ProjectRoot (Get-ChineseSecretFolderName)) "onsite_secrets.json") -ForegroundColor Yellow
  exit 1
}

try {
  $cfg = Get-Content -LiteralPath $secretPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
  Write-Host "Failed to parse onsite_secrets.json: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
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

$llmProvider = Value-OrDefault $cfg.mimo_provider "mimo_openai"
$llmRegion = Value-OrDefault $cfg.mimo_region "cn"
$llmEndpoint = Value-OrDefault $cfg.mimo_endpoint "https://api.xiaomimimo.com/v1/chat/completions"
$llmModel = Value-OrDefault $cfg.mimo_model "mimo-v2-omni"
$llmTimeout = Int-OrDefault $cfg.mimo_timeout_seconds 25
$llmRetries = Int-OrDefault $cfg.mimo_max_retries 1
$syncTimeout = Int-OrDefault $cfg.sync_timeout_seconds 8
$rulesEndpoint = Value-OrDefault $cfg.rules_endpoint ""
$profileImportEndpoint = Value-OrDefault $cfg.profile_import_endpoint ""
$customerProfilesEndpoint = Value-OrDefault $cfg.customer_profiles_endpoint ""

$llmConfig = [ordered]@{
  enabled = $true
  provider = $llmProvider
  region = $llmRegion
  endpoint = $llmEndpoint
  model = $llmModel
  api_key = [string]$cfg.mimo_api_key
  timeout_seconds = $llmTimeout
  max_retries = $llmRetries
}

$syncConfig = [ordered]@{
  enabled = $true
  endpoint = [string]$cfg.sync_endpoint
  rules_endpoint = $rulesEndpoint
  profile_import_endpoint = $profileImportEndpoint
  customer_profiles_endpoint = $customerProfilesEndpoint
  token = [string]$cfg.sync_token
  tenant = [string]$cfg.sync_tenant
  timeout_seconds = $syncTimeout
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
  Remove-Item -LiteralPath $secretPath -Force
  Write-Host "Deleted source private config file." -ForegroundColor Yellow
} else {
  Write-Host "Source private config file remains at private config folder." -ForegroundColor Yellow
  Write-Host "After onsite installation is verified, delete the private config folder manually." -ForegroundColor Yellow
}

Write-Host "Created: llm_client.local.json" -ForegroundColor Green
Write-Host "Created: sync_client.local.json" -ForegroundColor Green
Write-Host "Private config installed." -ForegroundColor Green
exit 0
