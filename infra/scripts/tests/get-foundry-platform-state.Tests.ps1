#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\get-foundry-platform-state.ps1'
$testState = @{
    calls = New-Object 'System.Collections.Generic.List[object]'
    failRead = $false
}

function az {
    $testState.calls.Add(@($args))
    $global:LASTEXITCODE = 0
    if ($testState.failRead) { $global:LASTEXITCODE = 1; return }
    $command = $args -join ' '
    if ($command -like 'account show *') {
        return '{"name":"test-subscription","state":"Enabled"}'
    }
    if ($command -like 'cognitiveservices account show *') {
        return '{"id":"/subscriptions/local/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/foundry","name":"foundry","location":"swedencentral","kind":"AIServices","state":"Succeeded"}'
    }
    if ($command -like 'cognitiveservices account deployment list *') {
        return '[{"deployment":"chat","model":"chat-model","version":"1","sku":"GlobalStandard","capacity":10,"upgrade":"NoAutoUpgrade","rateLimits":[]}]'
    }
    if ($command -like 'cognitiveservices usage list *') {
        return '[{"name":"OpenAI.GlobalStandard.chat-model","current":10,"limit":20,"unit":"Count"},{"name":"OpenAI.Standard.other","current":0,"limit":100,"unit":"Count"}]'
    }
    if ($command -like 'resource list *') {
        return '[{"name":"appi","type":"microsoft.insights/components"},{"name":"log","type":"Microsoft.OperationalInsights/workspaces"},{"name":"unrelated","type":"Microsoft.Storage/storageAccounts"}]'
    }
    if ($command -like '*connections?api-version=*') {
        return '[]'
    }
    if ($command -like 'rest --method get *') {
        return '{"name":"project","state":"Succeeded"}'
    }
    throw "Unexpected CLI command: $command"
}

function wsl {
    if (($args[0..3] -join ' ') -ne '--distribution Ubuntu --exec az') {
        throw 'Unexpected WSL invocation'
    }
    $azureArguments = $args[4..($args.Count - 1)]
    az @azureArguments
}

foreach ($useWsl in @($false, $true)) {
    $testState.calls.Clear()
    $state = & $scriptPath -Subscription test-subscription -UseWsl:$useWsl | ConvertFrom-Json
    if ($state.deployments.Count -ne 1) { throw 'Deployment array was not preserved' }
    if ($state.regionalSubscriptionQuota.Count -ne 1) { throw 'Quota was not matched by model and SKU' }
    if ($state.monitoringResourcesInGroup.Count -ne 2) { throw 'Monitoring resource filtering failed' }
    if ($state.projectConnections.Count -ne 0) { throw 'Empty connections were not preserved' }
    if ($state.traceIngestionVerified) { throw 'Inventory cannot verify trace ingestion' }
    if ($testState.calls.Count -ne 7) { throw 'Expected seven read-only Azure commands' }
    foreach ($call in $testState.calls) {
        if (($call -join ' ') -notlike '*--subscription test-subscription*') { throw 'Missing explicit subscription' }
        if ($call -contains 'create' -or $call -contains 'update' -or $call -contains 'listKeys') {
            throw 'Mutation or credential retrieval detected'
        }
    }
}

$testState.failRead = $true
$testState.calls.Clear()
try {
    & $scriptPath -Subscription test-subscription | Out-Null
    throw 'Expected read failure'
} catch {
    if ($_.Exception.Message -notlike 'Azure read failed*') { throw }
}
if ($testState.calls.Count -ne 1) { throw 'Script did not stop at first failed read' }
Write-Output 'PASS: native/WSL inventory, filtering, explicit subscription, and fail-fast behavior'
