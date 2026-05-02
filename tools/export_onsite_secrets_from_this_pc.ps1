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
    throw "缺少必填配置：$name"
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
  Require-Value $mimoApiKey "Windows 环境变量 TAX_INVOICE_MIMO_API_KEY"
} catch {
  Write-Host $_.Exception.Message -ForegroundColor Red
  Write-Host "请先在这台电脑配置 MiMo Key，或从已可用的电脑导出。" -ForegroundColor Yellow
  exit 1
}

$syncPath = Join-Path $ProjectRoot "sync_client.local.json"
if (-not (Test-Path $syncPath)) {
  Write-Host "未找到 sync_client.local.json：$syncPath" -ForegroundColor Red
  exit 1
}

try {
  $sync = Get-Content -Path $syncPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
  Write-Host "sync_client.local.json 解析失败：$($_.Exception.Message)" -ForegroundColor Red
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
  $currentUserGrant = "${env:USERNAME}:(R,W)"
  icacls $secretPath /grant:r $currentUserGrant "Administrators:(F)" "SYSTEM:(F)" | Out-Null
} catch {
  Write-Host "权限收紧失败，但私密配置文件已写入。" -ForegroundColor Yellow
}

Write-Host "已生成：$secretPath" -ForegroundColor Green
Write-Host "请把 _onsite_private_config 文件夹单独保存，现场复制到新安装目录。" -ForegroundColor Green
exit 0
