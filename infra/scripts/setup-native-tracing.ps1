#Requires -Version 5.1
<#
.SYNOPSIS
    Creates the approved shared native-tracing resources; previews unless -Apply.
.DESCRIPTION
    Requires the monitoring setup approval recorded in docs/setup.md.
    Existing resources must match the approved configuration; conflicting
    resources or AppInsights connections cause an explicit stop, not an update.
    No keys, agents, models or existing connections are read or changed. The API
    requires Application Insights routing metadata, passed internally without
    printing it; key-based ingestion stays disabled. Reruns verify configuration
    without recreating resources.
.EXAMPLE
    .\infra\scripts\setup-native-tracing.ps1 -UseWsl -Apply
#>
[CmdletBinding()]
param(
    [switch]$UseWsl,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$subscription = 'ME-M365CPI54615665-rwidholm-1'
$group = 'rg-foundry-agentic-pattern'
$account = 'foundry-agentic-R8N3LD'
$project = 'proj-agentic'
$workspaceName = 'log-foundry-agentic'
$appName = 'appi-foundry-agentic'
$location = 'swedencentral'
$connectionApi = '2025-10-01-preview'

function Invoke-Azure {
    param([string[]]$Arguments)
    $cliArguments = $Arguments + @('--subscription', $subscription, '-o', 'json', '--only-show-errors')
    if ($UseWsl) { $raw = & wsl --distribution Ubuntu --exec az @cliArguments }
    else { $raw = & az @cliArguments }
    if ($LASTEXITCODE -ne 0) { throw "Azure operation failed: $($Arguments[0..1] -join ' '). Stop and inspect partial state before retrying." }
    if (-not $raw) { throw 'Expected JSON response from Azure.' }
    $parsed = ($raw -join "`n") | ConvertFrom-Json
    foreach ($item in $parsed) { $item }
}

function Put-Resource {
    param([string]$Id, [string]$Api, [hashtable]$Body, [string]$Query, [string]$Method = 'put')
    $file = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($file, ($Body | ConvertTo-Json -Depth 12), [System.Text.UTF8Encoding]::new($false))
        $bodyPath = $file
        if ($UseWsl) {
            $bodyPath = & wsl --distribution Ubuntu --exec wslpath -a $file
            if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve temporary request file in WSL.' }
        }
        Invoke-Azure @('rest', '--method', $Method, '--url', "https://management.azure.com${Id}?api-version=$Api",
            '--body', "@$bodyPath", '--query', $Query)
    } finally {
        Remove-Item -LiteralPath $file -ErrorAction Stop
    }
}

function Wait-Resource {
    param([string]$Id, [string]$Api, [string]$Query)
    for ($attempt = 0; $attempt -lt 18; $attempt++) {
        $state = Invoke-Azure @('rest', '--method', 'get', '--url',
            "https://management.azure.com${Id}?api-version=$Api", '--query', $Query)
        if ($state.state -eq 'Succeeded') { return $state }
        if ($state.state -notin @('Creating', 'Updating', 'Accepted', 'InProgress')) {
            throw "Resource provisioning returned unexpected state '$($state.state)'."
        }
        Start-Sleep -Seconds 10
    }
    throw 'Resource is still provisioning after three minutes. Inspect partial state before retrying.'
}

$foundry = Invoke-Azure @('cognitiveservices', 'account', 'show', '-g', $group, '-n', $account,
    '--query', '{id:id,location:location}')
if ($foundry.location -ne $location) { throw 'Unexpected Foundry region; approval covers Sweden Central only.' }
$groupId = $foundry.id.Substring(0, $foundry.id.IndexOf('/providers/', [StringComparison]::OrdinalIgnoreCase))
$projectId = "$($foundry.id)/projects/$project"
$projectState = Invoke-Azure @('rest', '--method', 'get', '--url',
    "https://management.azure.com${projectId}?api-version=$connectionApi",
    '--query', '{principalId:identity.principalId,state:properties.provisioningState}')
if (-not $projectState.principalId -or $projectState.state -ne 'Succeeded') {
    throw 'Existing project must have a healthy system-assigned identity; no identity changes are approved.'
}
$workspaceId = "$groupId/providers/Microsoft.OperationalInsights/workspaces/$workspaceName"
$appId = "$groupId/providers/Microsoft.Insights/components/$appName"
$connectionId = "$projectId/connections/$appName"
$resources = @(Invoke-Azure @('resource', 'list', '-g', $group, '--query', '[].{name:name,id:id,type:type}'))
$connections = @(Invoke-Azure @('rest', '--method', 'get', '--url',
    "https://management.azure.com${projectId}/connections?api-version=$connectionApi",
    '--query', 'value[].{name:name,category:properties.category,auth:properties.authType,target:properties.target}'))
$existingConnection = @($connections | Where-Object { $_.category -eq 'AppInsights' })
if ($existingConnection.Count -gt 1 -or ($existingConnection.Count -eq 1 -and
    ($existingConnection[0].name -ne $appName -or $existingConnection[0].auth -ne 'ProjectManagedIdentity' -or
     $existingConnection[0].target -ne $appId))) {
    throw 'A different AppInsights connection exists. No replacement is approved.'
}
if (@($connections | Where-Object { $_.name -eq $appName -and $_.category -ne 'AppInsights' }).Count) {
    throw 'Proposed connection name is already used by another category.'
}

if (-not $Apply) {
    Write-Output 'Preview only: log-foundry-agentic (Sweden Central, PerGB2018, 30 days); appi-foundry-agentic (workspace-based, Entra-only ingestion); project MI Monitoring Metrics Publisher scoped to app; project AppInsights/ProjectManagedIdentity connection. Use -Apply only with approval.'
    return
}

if (-not @($resources | Where-Object { $_.id -eq $workspaceId }).Count) {
    Put-Resource $workspaceId '2023-09-01' @{
        location = $location
        tags = @{ project = 'foundry-agentic-pattern'; owner = 'llandinl' }
        properties = @{ retentionInDays = 30; sku = @{ name = 'PerGB2018' } }
    } '{name:name,state:properties.provisioningState}' | Out-Null
}
$workspace = Wait-Resource $workspaceId '2023-09-01' `
    '{location:location,retention:properties.retentionInDays,sku:properties.sku.name,state:properties.provisioningState}'
if ($workspace.location -ne $location -or $workspace.retention -ne 30 -or
    $workspace.sku -ne 'PerGB2018' -or $workspace.state -ne 'Succeeded') {
    throw 'Workspace does not match approved settings or is still provisioning. Stop; do not overwrite.'
}

if (-not @($resources | Where-Object { $_.id -eq $appId }).Count) {
    Put-Resource $appId '2020-02-02' @{
        location = $location
        kind = 'web'
        tags = @{ project = 'foundry-agentic-pattern'; owner = 'llandinl' }
        properties = @{
            Application_Type = 'web'
            WorkspaceResourceId = $workspaceId
            DisableLocalAuth = $true
        }
    } '{name:name,state:properties.provisioningState}' | Out-Null
}
$app = Wait-Resource $appId '2020-02-02' `
    '{location:location,workspace:properties.WorkspaceResourceId,disableLocalAuth:properties.DisableLocalAuth,state:properties.provisioningState}'
if ($app.location -ne $location -or $app.workspace -ne $workspaceId -or
    $app.disableLocalAuth -ne $true -or $app.state -ne 'Succeeded') {
    throw 'Application Insights does not match approved settings or is still provisioning. Stop; do not overwrite.'
}

$appTables = @('AppAvailabilityResults', 'AppBrowserTimings', 'AppDependencies', 'AppEvents',
    'AppExceptions', 'AppMetrics', 'AppPageViews', 'AppPerformanceCounters', 'AppRequests',
    'AppSystemEvents', 'AppTraces', 'AppGenAIContent')
$tables = @(Invoke-Azure @('rest', '--method', 'get', '--url',
    "https://management.azure.com${workspaceId}/tables?api-version=2022-10-01",
    '--query', 'value[].{name:name,retention:properties.retentionInDays,totalRetention:properties.totalRetentionInDays}'))
foreach ($table in $tables | Where-Object { $_.name -in $appTables }) {
    if ($table.retention -eq 30 -and $table.totalRetention -eq 30) { continue }
    if ($table.retention -ne 90 -or $table.totalRetention -ne 90) {
        throw "Unexpected retention on $($table.name). Stop; do not overwrite."
    }
    # Application Insights tables default to 90 days independently of the workspace.
    Put-Resource "$workspaceId/tables/$($table.name)" '2022-10-01' @{
        properties = @{ retentionInDays = 30; totalRetentionInDays = 30 }
    } '{name:name}' 'patch' | Out-Null
}
$verifiedTables = @(Invoke-Azure @('rest', '--method', 'get', '--url',
    "https://management.azure.com${workspaceId}/tables?api-version=2022-10-01",
    '--query', 'value[].{name:name,retention:properties.retentionInDays,totalRetention:properties.totalRetentionInDays}'))
$presentTables = @($verifiedTables | Where-Object { $_.name -in $appTables })
if ($presentTables.Count -ne $appTables.Count -or @($verifiedTables | Where-Object {
    $_.name -in $appTables -and ($_.retention -ne 30 -or $_.totalRetention -ne 30)
}).Count) { throw 'Application Insights table retention verification failed.' }

$roles = @(Invoke-Azure @('role', 'assignment', 'list', '--scope', $appId,
    '--query', '[].{principalId:principalId,role:roleDefinitionName}'))
if (-not @($roles | Where-Object {
    $_.principalId -eq $projectState.principalId -and $_.role -eq 'Monitoring Metrics Publisher'
}).Count) {
    Invoke-Azure @('role', 'assignment', 'create', '--assignee-object-id', $projectState.principalId,
        '--assignee-principal-type', 'ServicePrincipal', '--role', 'Monitoring Metrics Publisher',
        '--scope', $appId, '--query', '{role:roleDefinitionName}') | Out-Null
}
$roles = @(Invoke-Azure @('role', 'assignment', 'list', '--scope', $appId,
    '--query', '[].{principalId:principalId,role:roleDefinitionName}'))
if (-not @($roles | Where-Object {
    $_.principalId -eq $projectState.principalId -and $_.role -eq 'Monitoring Metrics Publisher'
}).Count) { throw 'Project managed identity ingestion role was not verified. Wait for RBAC propagation and retry.' }
if (-not $existingConnection.Count) {
    $routing = Invoke-Azure @('rest', '--method', 'get', '--url',
        "https://management.azure.com${appId}?api-version=2020-02-02",
        '--query', 'properties.ConnectionString')
    if (-not $routing) { throw 'Application Insights routing metadata is missing.' }
    try {
        Put-Resource $connectionId $connectionApi @{
            properties = @{
                category = 'AppInsights'
                authType = 'ProjectManagedIdentity'
                target = $appId
                isSharedToAll = $true
                metadata = @{
                    ApiType = 'Azure'
                    ResourceId = $appId
                    ApplicationInsightsConnectionString = $routing
                }
            }
        } '{name:name,category:properties.category,auth:properties.authType}' | Out-Null
    } finally {
        Remove-Variable routing
    }
}
$verified = Invoke-Azure @('rest', '--method', 'get', '--url',
    "https://management.azure.com${connectionId}?api-version=$connectionApi",
    '--query', '{name:name,category:properties.category,auth:properties.authType,target:properties.target}')
if ($verified.category -ne 'AppInsights' -or $verified.auth -ne 'ProjectManagedIdentity' -or
    $verified.target -ne $appId) { throw 'Connection verification failed.' }
[pscustomobject]@{
    observedAtUtc = [DateTime]::UtcNow.ToString('o')
    workspace = $workspaceName
    location = $location
    retentionDays = $workspace.retention
    applicationInsightsTableRetentionDays = 30
    applicationInsights = $appName
    disableLocalAuth = $app.disableLocalAuth
    connection = $appName
    auth = $verified.auth
    ingestionRole = 'Monitoring Metrics Publisher'
    ingestionIdentity = 'proj-agentic system-assigned managed identity'
    traceIngestionVerified = $false
} | ConvertTo-Json
