#Requires -Version 7
<#
.SYNOPSIS
    Sets up Foundry IQ for the Documentation Agent: an Azure AI Search knowledge base over data/knowledge/*.md,
    exposed to a Foundry agent as an MCP tool. Idempotent.

.DESCRIPTION
    MVP setup (ADR 0022): a search index knowledge source, minimal retrieval effort, so no embedding or chat model is
    needed. Automates the steps in docs/workshop/foundry-iq-guide.md.

      1. Creates the Azure AI Search service (Basic, system-assigned identity, Entra auth) if it doesn't exist.
      2. Assigns roles: you get Search Service Contributor + Search Index Data Contributor,
         the Foundry project's managed identity gets Search Index Data Reader.
      3. Creates the index and uploads data/knowledge/*.md, one document per '## ' section.
      4. Creates the knowledge source (kind searchIndex) and the knowledge base (minimal effort, extractive data).
      5. Creates the project connection (RemoteTool, ProjectManagedIdentity) to the knowledge base MCP endpoint.
      6. If -AgentName is given: creates a new agent version with the knowledge_base_retrieve MCP tool added.

    Requires: Azure CLI signed in as an Owner (or User Access Administrator + Contributor) on the resource group.

.EXAMPLE
    ./infra/scripts/setup-foundry-iq.ps1 -ResourceGroup rg-foundry-agentic-pattern `
        -FoundryAccount <account> -Project <project> -SearchService <search-name> -AgentName doc-agent
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$FoundryAccount,
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$SearchService,
    [string]$Location = 'francecentral',
    [string]$AgentName,
    [string]$IndexName = 'doc-knowledge',
    [string]$KnowledgeSource = 'ks-doc-knowledge',
    [string]$KnowledgeBase = 'kb-doc-agent',
    [string]$ConnectionName = 'kb-doc-agent-mcp',
    [string]$ContentPath = (Join-Path $PSScriptRoot '../../data/knowledge'),
    [string]$SourceUrlBase = 'https://github.com/wdhm/foundry-agentic-pattern/blob/main/data/knowledge'
)

$ErrorActionPreference = 'Stop'
$SearchApi = '2026-08-01-preview'
$AgentApi = '2025-11-15-preview'

function Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Done([string]$Message) { Write-Host "    $Message" -ForegroundColor Green }

function Get-Token([string]$Resource) {
    $token = az account get-access-token --resource $Resource --query accessToken -o tsv
    if (-not $token) { throw "az account get-access-token failed for $Resource. Run 'az login'." }
    $token
}

function Invoke-Api {
    param([string]$Method, [string]$Uri, [string]$Token, $Body, [hashtable]$Headers = @{})
    $params = @{ Method = $Method; Uri = $Uri; Headers = @{ Authorization = "Bearer $Token" } + $Headers }
    if ($null -ne $Body) { $params.Body = $Body | ConvertTo-Json -Depth 30; $params.ContentType = 'application/json' }
    Invoke-RestMethod @params
}

# Role assignments take a few minutes to apply to the data plane.
function Invoke-WithRetry([scriptblock]$Call, [int]$Attempts = 12, [int]$DelaySeconds = 15) {
    for ($i = 1; ; $i++) {
        try { return & $Call } catch {
            if ($i -ge $Attempts) { throw }
            Write-Host "    retry $i/$Attempts in ${DelaySeconds}s: $($_.Exception.Message)" -ForegroundColor DarkYellow
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

function Set-Role([string]$PrincipalId, [string]$PrincipalType, [string]$Role, [string]$Scope) {
    $exists = az role assignment list --assignee $PrincipalId --role $Role --scope $Scope --query '[0].id' -o tsv
    if ($exists) { Done "exists: $Role"; return }
    az role assignment create --assignee-object-id $PrincipalId --assignee-principal-type $PrincipalType `
        --role $Role --scope $Scope -o none
    if ($LASTEXITCODE) { throw "role assignment failed: $Role" }
    Done "assigned: $Role"
}

Step "1. Azure AI Search '$SearchService'"
$search = az search service show -g $ResourceGroup -n $SearchService -o json 2>$null | ConvertFrom-Json
if ($search) {
    Done "exists in $($search.location)"
} else {
    # Semantic ranker is required for agentic retrieval. Basic is the smallest tier with a managed identity.
    $search = az search service create -g $ResourceGroup -n $SearchService -l $Location --sku basic `
        --identity-type SystemAssigned --auth-options aadOrApiKey --aad-auth-failure-mode http401WithBearerChallenge `
        --semantic-search free -o json | ConvertFrom-Json
    if (-not $search) { throw "Search service creation failed. If the region is out of capacity, try another -Location." }
    Done "created in $($search.location)"
}
$searchEndpoint = "https://$SearchService.search.windows.net"

Step '2. Roles'
$me = az ad signed-in-user show --query id -o tsv
$projectId = "$(az cognitiveservices account show -g $ResourceGroup -n $FoundryAccount --query id -o tsv)/projects/$Project"
$projectPrincipal = az resource show --ids $projectId --query identity.principalId -o tsv
if (-not $projectPrincipal) { throw "Project $Project has no system-assigned managed identity." }
Set-Role $me 'User' 'Search Service Contributor' $search.id
Set-Role $me 'User' 'Search Index Data Contributor' $search.id
Set-Role $projectPrincipal 'ServicePrincipal' 'Search Index Data Reader' $search.id

$searchToken = Get-Token 'https://search.azure.com'

Step "3. Index '$IndexName' + content from $ContentPath"
$index = @{
    name     = $IndexName
    fields   = @(
        @{ name = 'id'; type = 'Edm.String'; key = $true; filterable = $true }
        @{ name = 'title'; type = 'Edm.String'; searchable = $true }
        @{ name = 'content'; type = 'Edm.String'; searchable = $true }
        @{ name = 'source'; type = 'Edm.String'; filterable = $true }
        @{ name = 'url'; type = 'Edm.String' }
    )
    semantic = @{
        defaultConfiguration = 'default'
        configurations       = @(@{
                name              = 'default'
                prioritizedFields = @{ titleField = @{ fieldName = 'title' }; prioritizedContentFields = @(@{ fieldName = 'content' }) }
            })
    }
}
Invoke-WithRetry { Invoke-Api PUT "$searchEndpoint/indexes/${IndexName}?api-version=$SearchApi" $searchToken $index | Out-Null }
Done 'index ready'

# One document per '## ' section keeps chunks small and citations precise.
$docs = foreach ($file in Get-ChildItem $ContentPath -Filter *.md) {
    $base = $file.BaseName
    $docTitle = (Select-String -Path $file -Pattern '^# (.+)$' | Select-Object -First 1).Matches.Groups[1].Value
    $sections = ((Get-Content $file -Raw) -replace "`r", '') -split '(?m)^(?=## )'
    foreach ($section in $sections | Where-Object { $_.Trim() }) {
        $heading = if ($section -match '^## (.+)') { $Matches[1].Trim() } else { 'Introduction' }
        $slug = ($heading.ToLower() -replace '[^a-z0-9]+', '-').Trim('-')
        @{
            '@search.action' = 'mergeOrUpload'
            id               = "$base-$slug"
            title            = "$docTitle - $heading"
            content          = $section.Trim()
            source           = $file.Name
            url              = "$SourceUrlBase/$($file.Name)#$slug"
        }
    }
}
Invoke-Api POST "$searchEndpoint/indexes/$IndexName/docs/index?api-version=$SearchApi" $searchToken @{ value = @($docs) } | Out-Null
Done "uploaded $(@($docs).Count) sections"

Step "4. Knowledge source '$KnowledgeSource' + knowledge base '$KnowledgeBase'"
Invoke-Api PUT "$searchEndpoint/knowledgesources/${KnowledgeSource}?api-version=$SearchApi" $searchToken @{
    name                  = $KnowledgeSource
    kind                  = 'searchIndex'
    description           = 'Documentation standard and other stable knowledge for the Documentation Agent.'
    searchIndexParameters = @{
        searchIndexName  = $IndexName
        sourceDataFields = @(@{ name = 'title' }, @{ name = 'source' }, @{ name = 'url' })
    }
} | Out-Null
Invoke-Api PUT "$searchEndpoint/knowledgebases/${KnowledgeBase}?api-version=$SearchApi" $searchToken @{
    name                     = $KnowledgeBase
    description              = 'Stable knowledge for the Documentation Agent: the documentation standard.'
    knowledgeSources         = @(@{ name = $KnowledgeSource })
    outputMode               = 'extractiveData'
    retrievalReasoningEffort = @{ kind = 'minimal' }
} | Out-Null
$mcpEndpoint = "$searchEndpoint/knowledgebases/$KnowledgeBase/mcp?api-version=$SearchApi"
Done $mcpEndpoint

Step "5. Project connection '$ConnectionName'"
Invoke-Api PUT "https://management.azure.com${projectId}/connections/${ConnectionName}?api-version=2025-10-01-preview" (Get-Token 'https://management.azure.com') @{
    name       = $ConnectionName
    type       = 'Microsoft.MachineLearningServices/workspaces/connections'
    properties = @{
        authType     = 'ProjectManagedIdentity'
        category     = 'RemoteTool'
        target       = $mcpEndpoint
        isSharedToAll = $true
        audience     = 'https://search.azure.com/'
        metadata     = @{ ApiType = 'Azure' }
    }
} | Out-Null
Done 'connection ready'

if (-not $AgentName) { Step '6. Agent: skipped (no -AgentName)'; return }

Step "6. Add the knowledge tool to agent '$AgentName'"
$projectEndpoint = "https://$($FoundryAccount.ToLower()).services.ai.azure.com/api/projects/$Project"
$aiToken = Get-Token 'https://ai.azure.com'
$headers = @{ 'Foundry-Features' = 'AgentEndpoints=V1Preview' }
$latest = (Invoke-Api GET "$projectEndpoint/agents/${AgentName}?api-version=$AgentApi" $aiToken -Headers $headers).versions.latest
$definition = $latest.definition
$legacyHint = 'Use the knowledge tool (knowledge_base_retrieve) to retrieve the documentation standard before assessing documentation, and cite its rule IDs (for example DS-14) in findings and missing information.'
$hint = "$legacyHint The standard is a rule set, not evidence: don't add it to the evidence array."
$current = $definition.tools | Where-Object { $_.server_label -eq 'knowledge' }
if ($current.server_url -eq $mcpEndpoint -and $definition.instructions.Contains($hint)) {
    Done "already has the knowledge tool ($($latest.id))"
    Write-Host "`nFoundry IQ ready: knowledge base '$KnowledgeBase' at $mcpEndpoint" -ForegroundColor Green
    return
}
$tool = [pscustomobject]@{
    type                  = 'mcp'
    server_label          = 'knowledge'
    server_url            = $mcpEndpoint
    allowed_tools         = @('knowledge_base_retrieve')
    require_approval      = 'never'
    project_connection_id = $ConnectionName
}
$definition.tools = @($definition.tools | Where-Object { $_.server_label -ne 'knowledge' }) + $tool
if (-not $definition.instructions.Contains($hint)) {
    $definition.instructions = if ($definition.instructions.Contains($legacyHint)) {
        $definition.instructions.Replace($legacyHint, $hint)
    } else { "$($definition.instructions)`n`n$hint" }
}
$version = Invoke-Api POST "$projectEndpoint/agents/$AgentName/versions?api-version=$AgentApi" $aiToken `
    @{ definition = $definition; description = $latest.description; metadata = $latest.metadata } -Headers $headers
Done "created $($version.id)"

Write-Host "`nFoundry IQ ready: knowledge base '$KnowledgeBase' at $mcpEndpoint" -ForegroundColor Green
