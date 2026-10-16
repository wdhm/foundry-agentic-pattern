#Requires -Version 7
<#
.SYNOPSIS
    Connects the GitHub MCP server to a Foundry agent as a read-only code source. Idempotent.

.DESCRIPTION
    MVP setup (ADR 0022): GitHub's hosted MCP server in read-only mode, authenticated with a fine-grained personal
    access token stored in a Foundry project connection. Automates the steps in docs/workshop/github-mcp-guide.md.

      1. Creates or updates the project connection (RemoteTool, CustomKeys: Authorization = Bearer <token>).
      2. If -AgentName is given: creates a new agent version with the 'github' MCP tool, limited to read tools.

    The token is read from -GitHubToken, then $env:GITHUB_MCP_TOKEN, else you are prompted. It is never printed.
    Use a fine-grained token with read-only access to the repository (Contents + Pull requests: Read-only).

    Requires: Azure CLI signed in with Foundry Project Manager (or Owner) on the Foundry project.

.EXAMPLE
    ./infra/scripts/setup-github-mcp.ps1 -ResourceGroup rg-foundry-agentic-pattern `
        -FoundryAccount <account> -Project <project> -AgentName doc-agent
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$FoundryAccount,
    [Parameter(Mandatory)][string]$Project,
    [string]$AgentName,
    [securestring]$GitHubToken,
    [string]$ConnectionName = 'github-mcp',
    [string]$ServerUrl = 'https://api.githubcopilot.com/mcp/readonly',
    [string]$Repository = 'wdhm/foundry-agentic-pattern'
)

$ErrorActionPreference = 'Stop'
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

Step "1. Project connection '$ConnectionName'"
if (-not $GitHubToken -and $env:GITHUB_MCP_TOKEN) { $GitHubToken = ConvertTo-SecureString $env:GITHUB_MCP_TOKEN -AsPlainText -Force }
if (-not $GitHubToken) { $GitHubToken = Read-Host 'Fine-grained GitHub token (read-only)' -AsSecureString }
$pat = ConvertFrom-SecureString $GitHubToken -AsPlainText
$projectId = "$(az cognitiveservices account show -g $ResourceGroup -n $FoundryAccount --query id -o tsv)/projects/$Project"
Invoke-Api PUT "https://management.azure.com${projectId}/connections/${ConnectionName}?api-version=2025-10-01-preview" (Get-Token 'https://management.azure.com') @{
    name       = $ConnectionName
    type       = 'Microsoft.MachineLearningServices/workspaces/connections'
    properties = @{
        authType      = 'CustomKeys'
        category      = 'RemoteTool'
        target        = $ServerUrl
        isSharedToAll = $true
        credentials   = @{ keys = @{ Authorization = "Bearer $pat" } }
        metadata      = @{ type = 'custom_MCP' }
    }
} | Out-Null
Remove-Variable pat
Done "connection ready -> $ServerUrl"

if (-not $AgentName) { Step '2. Agent: skipped (no -AgentName)'; return }

Step "2. Add the github tool to agent '$AgentName'"
$projectEndpoint = "https://$($FoundryAccount.ToLower()).services.ai.azure.com/api/projects/$Project"
$aiToken = Get-Token 'https://ai.azure.com'
$headers = @{ 'Foundry-Features' = 'AgentEndpoints=V1Preview' }
$latest = (Invoke-Api GET "$projectEndpoint/agents/${AgentName}?api-version=$AgentApi" $aiToken -Headers $headers).versions.latest
$definition = $latest.definition
$hint = "Use the github tool to read the integration code, configuration and pull request diffs in the GitHub repository $Repository. For git evidence, set the version to the full commit SHA you read from (the PR head SHA for a pull request)."
$allowed = @('get_file_contents', 'get_commit', 'list_commits', 'pull_request_read', 'list_pull_requests')
$current = $definition.tools | Where-Object { $_.server_label -eq 'github' }
if ($current.server_url -eq $ServerUrl -and $definition.instructions.Contains($hint) -and
    -not (Compare-Object @($current.allowed_tools) $allowed)) {
    Done "already has the github tool ($($latest.id))"
    return
}
$tool = [pscustomobject]@{
    type                  = 'mcp'
    server_label          = 'github'
    server_url            = $ServerUrl
    allowed_tools         = $allowed
    require_approval      = 'never'
    project_connection_id = $ConnectionName
}
$definition.tools = @($definition.tools | Where-Object { $_.server_label -ne 'github' }) + $tool
if (-not $definition.instructions.Contains($hint)) { $definition.instructions = "$($definition.instructions)`n`n$hint" }
$version = Invoke-Api POST "$projectEndpoint/agents/$AgentName/versions?api-version=$AgentApi" $aiToken `
    @{ definition = $definition; description = $latest.description; metadata = $latest.metadata } -Headers $headers
Done "created $($version.id)"

Write-Host "`nGitHub MCP ready: '$ConnectionName' (read-only) on agent '$AgentName'" -ForegroundColor Green
