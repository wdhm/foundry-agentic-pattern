#Requires -Version 7
<#
.SYNOPSIS
    Workshop demo (P2): asks the Foundry IQ knowledge base a question and prints the rules it returns. Read-only.

.DESCRIPTION
    Calls the knowledge base retrieve API directly, the same retrieval the agent reaches as the MCP tool
    knowledge_base_retrieve. The knowledge base uses minimal reasoning effort, so no model is called: only
    the search index and semantic ranker run. Nothing is created or changed.

    Requires: Azure CLI signed in with Search Index Data Reader (or higher) on the search service.

.EXAMPLE
    ./infra/scripts/demo-foundry-iq.ps1 -SearchService srch-foundry-agentic-r8n3ld

.EXAMPLE
    ./infra/scripts/demo-foundry-iq.ps1 -SearchService srch-foundry-agentic-r8n3ld -Query 'What must the change log contain?'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SearchService,
    [string]$KnowledgeBase = 'kb-doc-agent',
    [string]$Query = 'What must an integration page document about error handling and retries?',
    [int]$MaxChars = 900
)

$ErrorActionPreference = 'Stop'
$api = '2026-08-01-preview'
$token = az account get-access-token --resource https://search.azure.com --query accessToken -o tsv
if (-not $token) { throw "az account get-access-token failed. Run 'az login'." }

$uri = "https://$SearchService.search.windows.net/knowledgebases/$KnowledgeBase/retrieve?api-version=$api"
$body = @{ intents = @(@{ type = 'semantic'; search = $Query }) } | ConvertTo-Json -Depth 5

Write-Host "Knowledge base: $KnowledgeBase" -ForegroundColor Cyan
Write-Host "Question:       $Query`n" -ForegroundColor Cyan

$result = Invoke-RestMethod -Method Post $uri -Headers @{ Authorization = "Bearer $token" } -Body $body -ContentType 'application/json'
$refs = $result.response[0].content[0].text | ConvertFrom-Json

foreach ($ref in $refs) {
    Write-Host "[$($ref.ref_id)] $($ref.title)" -ForegroundColor Yellow
    $text = $ref.content.Length -gt $MaxChars ? $ref.content.Substring(0, $MaxChars) + ' ...' : $ref.content
    Write-Host $text
    $ids = [regex]::Matches($ref.content, 'DS-\d+') | ForEach-Object Value | Select-Object -Unique
    if ($ids) { Write-Host "Rule IDs: $($ids -join ', ')`n" -ForegroundColor Green } else { Write-Host '' }
}

$activity = $result.activity | Where-Object type -eq 'searchIndex' | Select-Object -First 1
if ($activity) {
    Write-Host "Source: $($activity.knowledgeSourceName), $($refs.Count) references, no model call (minimal effort)." -ForegroundColor DarkGray
}
