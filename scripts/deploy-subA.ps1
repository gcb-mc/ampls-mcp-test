#requires -Version 7
<#
.SYNOPSIS
  Deploys Log Analytics workspace, workspace-based Application Insights, and a
  Data Collection Endpoint into Subscription A. Writes the resource IDs to
  ./outputs/subA-outputs.json so the Sub B owner can consume them.

.DESCRIPTION
  Hand the contents of outputs/subA-outputs.json to the Sub B owner. They will
  pass those three resource IDs into deploy-subB.ps1.

.PARAMETER SubA
  Subscription ID for Subscription A.

.PARAMETER Location
  Azure region for all resources. Default: eastus2.

.EXAMPLE
  az login --tenant <your-tenant-id>
  ./deploy-subA.ps1 -SubA "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
#>

param(
  [Parameter(Mandatory)]
  [string] $SubA,

  [string] $Location      = 'eastus2',
  [string] $DeploymentTag = ('ampls-' + (Get-Date -Format 'yyyyMMddHHmm'))
)

$ErrorActionPreference = 'Stop'

Write-Host "==> Setting subscription context: $SubA" -ForegroundColor Cyan
az account set --subscription $SubA | Out-Null

$current = (az account show --query id -o tsv)
if ($current -ne $SubA) {
  throw "Failed to set subscription context. Current: $current, expected: $SubA"
}

Write-Host "==> Deploying observability resources to Sub A" -ForegroundColor Cyan
$out = az deployment sub create `
  --name "obs-$DeploymentTag" `
  --location $Location `
  --template-file "$PSScriptRoot/../infra/subA-observability.bicep" `
  --parameters location=$Location `
  --output json | ConvertFrom-Json

if (-not $out) { throw "Deployment returned no output." }

$result = [ordered]@{
  tenantId           = (az account show --query tenantId -o tsv)
  subscriptionId     = $SubA
  location           = $Location
  resourceGroupName  = $out.properties.outputs.rgName.value
  workspaceName      = $out.properties.outputs.workspaceName.value
  appInsightsName    = $out.properties.outputs.appInsightsName.value
  dceName            = $out.properties.outputs.dceName.value
  workspaceId        = $out.properties.outputs.workspaceId.value
  appInsightsId      = $out.properties.outputs.appInsightsId.value
  dceId              = $out.properties.outputs.dceId.value
  generatedUtc       = (Get-Date).ToUniversalTime().ToString('o')
}

$outputsDir = Join-Path $PSScriptRoot '../outputs'
New-Item -ItemType Directory -Force -Path $outputsDir | Out-Null
$outputsFile = Join-Path $outputsDir 'subA-outputs.json'
$result | ConvertTo-Json -Depth 4 | Set-Content -Path $outputsFile -Encoding utf8

Write-Host ""
Write-Host "==> Sub A deployment complete." -ForegroundColor Green
Write-Host "Resource IDs written to: $outputsFile" -ForegroundColor Green
Write-Host ""
Write-Host "Send the following three resource IDs to the Sub B owner:" -ForegroundColor Yellow
Write-Host "  workspaceId   = $($result.workspaceId)"
Write-Host "  appInsightsId = $($result.appInsightsId)"
Write-Host "  dceId         = $($result.dceId)"
Write-Host ""
Write-Host "After Sub B finishes their deployment, the AMPLS private endpoint connection" -ForegroundColor Yellow
Write-Host "should auto-approve (same tenant). Verify in: AMPLS resource -> Private endpoint connections."
