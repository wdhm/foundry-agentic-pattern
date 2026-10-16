#Requires -Version 7
<#
.SYNOPSIS
    Creates the read-only Foundry toolbox the hosted documentation-agent uses. Idempotent.

.DESCRIPTION
    Bundles the three existing project connections into one toolbox, exposing only the four read tools the hosted
    runtime allows (src/agents/documentation-agent/README.md):

      knowledge___knowledge_base_retrieve   connection kb-doc-agent-mcp  (Foundry IQ, setup-foundry-iq.ps1)
      github___get_file_contents            connection github-mcp        (GitHub read-only MCP, github-mcp-guide.md)
      ado___wiki, ado___wit_work_item       connection ado-mcp-proxy     (agent-identity gateway, onboard-agent.ps1)

    Server URLs are read from the connections, so nothing environment-specific is hard-coded. Every tool is
    require_approval=never; the runtime's action guard still rejects write actions (ADR 0024).

    If the toolbox already has a version, nothing is changed unless -NewVersion is given. Prints the version-pinned
    MCP endpoint to set as TOOLBOX_ENDPOINT on the hosted agent.

    Requires: Azure CLI signed in with Azure AI User (or higher) on the Foundry project.

.EXAMPLE
    ./infra/scripts/setup-toolbox.ps1 -ProjectEndpoint https://<account>.services.ai.azure.com/api/projects/<project>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProjectEndpoint,
    [string]$ToolboxName = 'documentation-agent-readonly',
    [string]$KnowledgeConnection = 'kb-doc-agent-mcp',
    [string]$GitHubConnection = 'github-mcp',
    [string]$AdoConnection = 'ado-mcp-proxy',
    [switch]$NewVersion
)

$ErrorActionPreference = 'Stop'
$Api = 'v1'
$ProjectEndpoint = $ProjectEndpoint.TrimEnd('/')

$token = az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv
if (-not $token) { throw "az account get-access-token failed. Run 'az login'." }
$headers = @{ Authorization = "Bearer $token" }

function Get-ConnectionTarget([string]$Name) {
    (Invoke-RestMethod "$ProjectEndpoint/connections/$($Name)?api-version=$Api" -Headers $headers).target
}

$existing = $null
try {
    $existing = Invoke-RestMethod "$ProjectEndpoint/toolboxes/$($ToolboxName)?api-version=$Api" -Headers $headers
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
}

if ($existing -and -not $NewVersion) {
    $version = $existing.default_version ?? $existing.versions.latest.version ?? '1'
    Write-Host "Toolbox '$ToolboxName' exists (default version $version); use -NewVersion to publish a new one." -ForegroundColor Yellow
} else {
    $tools = @(
        @{ label = 'knowledge'; connection = $KnowledgeConnection; names = @('knowledge_base_retrieve')
           description = 'Documentation standard knowledge base (Foundry IQ). Retrieve rules by query.' }
        @{ label = 'github'; connection = $GitHubConnection; names = @('get_file_contents')
           description = 'GitHub repository files at an exact commit (read-only).' }
        @{ label = 'ado'; connection = $AdoConnection; names = @('wiki', 'wit_work_item')
           description = 'Azure DevOps wiki pages and work items (read-only gateway, agent user).' }
    ) | ForEach-Object {
        @{
            type                  = 'mcp'
            server_label          = $_.label
            server_url            = Get-ConnectionTarget $_.connection
            project_connection_id = $_.connection
            allowed_tools         = @{ tool_names = $_.names }
            require_approval      = 'never'
            description           = $_.description
        }
    }
    $body = @{
        description = 'Read-only sources for the hosted documentation-agent: documentation standard (Foundry IQ), GitHub file at commit, Azure DevOps wiki page and work item.'
        tools       = $tools
    } | ConvertTo-Json -Depth 10
    $created = Invoke-RestMethod -Method Post "$ProjectEndpoint/toolboxes/$ToolboxName/versions?api-version=$Api" `
        -Headers $headers -Body $body -ContentType 'application/json'
    $version = $created.version
    Write-Host "Created toolbox '$ToolboxName' version $version." -ForegroundColor Green
}

Write-Host "TOOLBOX_ENDPOINT=$ProjectEndpoint/toolboxes/$ToolboxName/versions/$version/mcp?api-version=$Api"
