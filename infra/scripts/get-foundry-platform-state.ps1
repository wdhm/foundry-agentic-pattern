#Requires -Version 5.1
<#
.SYNOPSIS
    Reads model, quota and native-tracing configuration without changing Azure.
.DESCRIPTION
    Requires an existing Azure CLI login. Projects only non-secret metadata;
    never retrieves connection credentials or invokes a model or agent.
    Quota is subscription-wide for the account's region, not project headroom.
.EXAMPLE
    .\infra\scripts\get-foundry-platform-state.ps1 -UseWsl
#>
[CmdletBinding()]
param(
    [string]$Subscription = 'ME-M365CPI54615665-rwidholm-1',
    [string]$ResourceGroup = 'rg-foundry-agentic-pattern',
    [string]$FoundryAccount = 'foundry-agentic-R8N3LD',
    [string]$Project = 'proj-agentic',
    [switch]$UseWsl
)

$ErrorActionPreference = 'Stop'

function Invoke-AzureJson {
    param([string[]]$Arguments)
    $cliArguments = $Arguments + @('--subscription', $Subscription, '--output', 'json', '--only-show-errors')
    if ($UseWsl) {
        $raw = & wsl --distribution Ubuntu --exec az @cliArguments
    } else {
        $raw = & az @cliArguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Azure read failed ($($Arguments[0])). Check the selected CLI's login and read permissions. No Azure changes were made."
    }
    if (-not $raw) { throw "Azure read returned no JSON ($($Arguments[0])). No Azure changes were made." }
    $parsed = ($raw -join "`n") | ConvertFrom-Json
    foreach ($item in $parsed) { $item }
}

$account = Invoke-AzureJson @('account', 'show', '--query', '{name:name,state:state}')
$foundry = Invoke-AzureJson @(
    'cognitiveservices', 'account', 'show', '-g', $ResourceGroup, '-n', $FoundryAccount,
    '--query', '{id:id,name:name,location:location,kind:kind,state:properties.provisioningState}'
)
$projectId = "$($foundry.id)/projects/$Project"
$projectState = Invoke-AzureJson @(
    'rest', '--method', 'get', '--url',
    "https://management.azure.com${projectId}?api-version=2025-10-01-preview",
    '--query', '{name:name,state:properties.provisioningState}'
)
$deployments = @(Invoke-AzureJson @(
    'cognitiveservices', 'account', 'deployment', 'list', '-g', $ResourceGroup, '-n', $FoundryAccount,
    '--query',
    '[].{deployment:name,model:properties.model.name,version:properties.model.version,format:properties.model.format,upgrade:properties.versionUpgradeOption,sku:sku.name,capacity:sku.capacity,state:properties.provisioningState,rateLimits:properties.rateLimits}'
))
$quota = @(Invoke-AzureJson @(
    'cognitiveservices', 'usage', 'list', '-l', $foundry.location,
    '--query', '[].{name:name.value,current:currentValue,limit:limit,unit:unit}'
))
$modelQuota = @($quota | Where-Object {
    $quotaName = $_.name
    @($deployments | Where-Object { $quotaName -eq "OpenAI.$($_.sku).$($_.model)" }).Count -gt 0
})
$monitoring = @(Invoke-AzureJson @(
    'resource', 'list', '-g', $ResourceGroup,
    '--query', '[].{name:name,type:type,location:location}'
) | Where-Object {
    $_.type -ieq 'Microsoft.Insights/components' -or
    $_.type -ieq 'Microsoft.OperationalInsights/workspaces'
})
$connections = @(Invoke-AzureJson @(
    'rest', '--method', 'get', '--url',
    "https://management.azure.com${projectId}/connections?api-version=2025-10-01-preview",
    '--query', 'value[].{name:name,category:properties.category,authType:properties.authType}'
))

[pscustomobject]@{
    observedAtUtc = [DateTime]::UtcNow.ToString('o')
    cli = $(if ($UseWsl) { 'WSL Ubuntu az' } else { 'az' })
    subscription = $account
    resourceGroup = $ResourceGroup
    foundry = [pscustomobject]@{
        name = $foundry.name
        location = $foundry.location
        kind = $foundry.kind
        state = $foundry.state
    }
    project = $projectState
    deployments = $deployments
    regionalSubscriptionQuota = $modelQuota
    monitoringResourcesInGroup = $monitoring
    projectConnections = $connections
    traceIngestionVerified = $false
} | ConvertTo-Json -Depth 12
