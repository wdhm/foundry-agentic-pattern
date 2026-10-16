#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\setup-native-tracing.ps1'
$root = '/subscriptions/local/resourceGroups/rg-foundry-agentic-pattern'
$projectId = "$root/providers/Microsoft.CognitiveServices/accounts/foundry-agentic-R8N3LD/projects/proj-agentic"
$appId = "$root/providers/Microsoft.Insights/components/appi-foundry-agentic"
$workspaceId = "$root/providers/Microsoft.OperationalInsights/workspaces/log-foundry-agentic"
$testState = @{
    writes = 0
    wrongRetention = $false
    wrongConnection = $false
    assigned = $true
    roleCreates = 0
    connectionExists = $true
    requestFile = $null
    legacyTableDefaults = $false
    patchedTables = New-Object 'System.Collections.Generic.List[string]'
}

function az {
    $global:LASTEXITCODE = 0
    $command = $args -join ' '
    if ($args -contains 'put' -or $args -contains 'patch' -or $args -contains 'create') {
        $testState.writes++
        if ($args -contains 'patch' -and $command -match '/tables/(App\w+)\?api-version=') {
            $tableName = $Matches[1]
            $bodyIndex = [Array]::IndexOf($args, '--body') + 1
            $body = Get-Content -LiteralPath $args[$bodyIndex].Substring(1) -Raw | ConvertFrom-Json
            if ($body.properties.retentionInDays -ne 30 -or $body.properties.totalRetentionInDays -ne 30) {
                throw 'Incorrect telemetry table retention'
            }
            $testState.patchedTables.Add($tableName)
            return '{}'
        }
        if ($command -like '*connections/appi-foundry-agentic?api-version=*') {
            $bodyIndex = [Array]::IndexOf($args, '--body') + 1
            $testState.requestFile = $args[$bodyIndex].Substring(1)
            $body = Get-Content -LiteralPath $testState.requestFile -Raw | ConvertFrom-Json
            if ($body.properties.authType -ne 'ProjectManagedIdentity' -or
                $body.properties.metadata.ApplicationInsightsConnectionString -ne 'test-routing-metadata' -or
                $body.properties.target -ne $appId) { throw 'Incorrect connection body' }
            $testState.connectionExists = $true
            return '{}'
        }
        if ($command -like 'role assignment create *') {
            $testState.assigned = $true
            $testState.roleCreates++
            return '{}'
        }
        throw "Unexpected write: $command"
    }
    if ($command -like 'cognitiveservices account show *') {
        return (@{ id = "$root/providers/Microsoft.CognitiveServices/accounts/foundry-agentic-R8N3LD"; location = 'swedencentral' } | ConvertTo-Json)
    }
    if ($command -like 'resource list *') {
        return (@(@{ id = $workspaceId }, @{ id = $appId }) | ConvertTo-Json)
    }
    if ($command -like '*connections?api-version=*') {
        if (-not $testState.connectionExists) { return '[]' }
        $auth = 'ProjectManagedIdentity'
        if ($testState.wrongConnection) { $auth = 'ApiKey' }
        return (,@{ name = 'appi-foundry-agentic'; category = 'AppInsights'; auth = $auth; target = $appId } | ConvertTo-Json)
    }
    if ($command -like '*connections/appi-foundry-agentic?api-version=*') {
        return (@{ name = 'appi-foundry-agentic'; category = 'AppInsights'; auth = 'ProjectManagedIdentity'; target = $appId } | ConvertTo-Json)
    }
    if ($command -like '*workspaces/log-foundry-agentic?api-version=*') {
        $retention = 30
        if ($testState.wrongRetention) { $retention = 90 }
        return (@{ location = 'swedencentral'; retention = $retention; sku = 'PerGB2018'; state = 'Succeeded' } | ConvertTo-Json)
    }
    if ($command -like '*workspaces/log-foundry-agentic/tables?api-version=*') {
        return (@('AppAvailabilityResults', 'AppBrowserTimings', 'AppDependencies', 'AppEvents',
            'AppExceptions', 'AppMetrics', 'AppPageViews', 'AppPerformanceCounters', 'AppRequests',
            'AppSystemEvents', 'AppTraces', 'AppGenAIContent') | ForEach-Object {
                $retention = 30
                if ($testState.legacyTableDefaults -and -not $testState.patchedTables.Contains($_)) { $retention = 90 }
                @{ name = $_; retention = $retention; totalRetention = $retention }
            } | ConvertTo-Json)
    }
    if ($command -like '*components/appi-foundry-agentic?api-version=*') {
        if ($command -like '*properties.ConnectionString*') { return '"test-routing-metadata"' }
        return (@{ location = 'swedencentral'; workspace = $workspaceId; disableLocalAuth = $true; state = 'Succeeded' } | ConvertTo-Json)
    }
    if ($command -like 'role assignment list *') {
        if (-not $testState.assigned) { return '[]' }
        return '[{"principalId":"project-mi","role":"Monitoring Metrics Publisher"}]'
    }
    if ($command -like "*$projectId`?api-version=*") {
        return '{"principalId":"project-mi","state":"Succeeded"}'
    }
    throw "Unexpected command: $command"
}

& $scriptPath | Out-Null
if ($testState.writes) { throw 'Preview must not write' }
$result = & $scriptPath -Apply | ConvertFrom-Json
if ($testState.writes) { throw 'Matching resources must not be rewritten' }
if ($result.traceIngestionVerified -or $result.auth -ne 'ProjectManagedIdentity') { throw 'Incorrect configuration claim' }

$testState.assigned = $false
& $scriptPath -Apply | Out-Null
if ($testState.roleCreates -ne 1) { throw 'Expected only the missing scoped ingestion role to be created' }
& $scriptPath -Apply | Out-Null
if ($testState.roleCreates -ne 1) { throw 'Role assignment must be idempotent' }

foreach ($scenario in @('wrongRetention', 'wrongConnection')) {
    $testState[$scenario] = $true
    $before = $testState.writes
    try {
        & $scriptPath -Apply | Out-Null
        throw 'Expected configuration conflict'
    } catch {
        if ($_.Exception.Message -notmatch 'Workspace does not match|different AppInsights connection') { throw }
    }
    if ($testState.writes -ne $before) { throw 'Configuration conflict must not mutate resources' }
    $testState[$scenario] = $false
}
$testState.connectionExists = $false
$output = & $scriptPath -Apply
if ($output -match 'test-routing-metadata') { throw 'Routing metadata leaked into output' }
if (-not $testState.connectionExists) { throw 'Missing connection was not created' }
if (Test-Path -LiteralPath $testState.requestFile) { throw 'Temporary request file was not removed' }
$testState.legacyTableDefaults = $true
& $scriptPath -Apply | Out-Null
if ($testState.patchedTables.Count -ne 12) { throw 'All twelve App Insights tables must use approved retention' }
& $scriptPath -Apply | Out-Null
if ($testState.patchedTables.Count -ne 12) { throw 'Table retention updates must be idempotent' }
Write-Output 'PASS: preview, idempotency, scoped role, conflicts, connection cleanup and 30-day table retention'
