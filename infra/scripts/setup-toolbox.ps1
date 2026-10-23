#Requires -Version 7
<#
.SYNOPSIS
    Creates the read-only Foundry toolbox the hosted documentation-agent uses (or, with -Write, its write toolbox). Idempotent.

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

    -AzureRepos opts into the additional read tool ado___repo_file. Existing toolboxes require -NewVersion.
    This does not grant repository access, extend gateway toolsets/consent or deploy the runtime. Review those
    separately, and set DOCUMENTATION_ADO_ORGANIZATION on the new runtime to enable its commit-pinned read guard.

    -Write creates the separate write toolbox 'documentation-agent-write' instead. It exposes exactly one tool,
    ado___wiki_upsert_page (connection ado-mcp-proxy), and is used only by the exact-call approval runtime
    (src/agents/documentation-agent/TOOL_APPROVAL.md), whose reviewed policy pins its versioned endpoint. The
    approval runtime, not the toolbox, gates the call, so require_approval is never here as well.

    Requires: Azure CLI signed in with Azure AI User (or higher) on the Foundry project.

.EXAMPLE
    ./infra/scripts/setup-toolbox.ps1 -ProjectEndpoint https://<account>.services.ai.azure.com/api/projects/<project>

.EXAMPLE
    ./infra/scripts/setup-toolbox.ps1 -ProjectEndpoint https://<account>.services.ai.azure.com/api/projects/<project> -Write
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProjectEndpoint,
    [string]$ToolboxName,
    [string]$KnowledgeConnection = 'kb-doc-agent-mcp',
    [string]$GitHubConnection = 'github-mcp',
    [string]$AdoConnection = 'ado-mcp-proxy',
    [switch]$AzureRepos,
    [switch]$Write,
    [switch]$NewVersion
)

$ErrorActionPreference = 'Stop'
if ($AzureRepos -and $Write) { throw '-AzureRepos is for the read toolbox only, not the write toolbox.' }
if (-not $ToolboxName) { $ToolboxName = $Write ? 'documentation-agent-write' : 'documentation-agent-readonly' }
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
    if ($AzureRepos) { throw 'Use -AzureRepos -NewVersion to publish a separately reviewed read-tool version.' }
    $version = $existing.default_version ?? $existing.versions.latest.version ?? '1'
    Write-Host "Toolbox '$ToolboxName' exists (default version $version); use -NewVersion to publish a new one." -ForegroundColor Yellow
} else {
    $sources = if ($Write) {
        @(@{ label = 'ado'; connection = $AdoConnection; names = @('wiki_upsert_page')
             description = 'Azure DevOps wiki page create/replace (agent user). Called only by the approval runtime.' })
    } else {
        @(
            @{ label = 'knowledge'; connection = $KnowledgeConnection; names = @('knowledge_base_retrieve')
               description = 'Foundry IQ knowledge base kb-doc-agent: the Integration Documentation Standard (DS-xx rules), ' +
                   'indexed in Azure AI Search from data/knowledge/ in GitHub. Called with the project managed identity.' }
            @{ label = 'github'; connection = $GitHubConnection; names = @('get_file_contents')
               description = 'GitHub read-only MCP server: repository file contents at an exact commit.' }
            @{ label = 'ado'; connection = $AdoConnection
               names = @('wiki', 'wit_work_item') + $(if ($AzureRepos) { @('repo_file') } else { @() })
               description = 'Azure DevOps through the agent gateway ca-doc-agent-mcp, called as the agent''s own identity: ' +
                   "$(if ($AzureRepos) { 'wiki pages, work items and repository files at a pinned commit' } else { 'wiki pages and work items' }). Read tools only." }
        )
    }
    $tools = $sources | ForEach-Object {
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
    $description = if ($Write) {
        'Approval-gated wiki write for the hosted documentation-agent: only Azure DevOps wiki_upsert_page.'
    } else {
        'Read-only tools for the hosted documentation-agent, one endpoint for every source it reads: the documentation ' +
        'standard (Foundry IQ), GitHub files at a commit, and Azure DevOps ' +
        $(if ($AzureRepos) { 'wiki pages, work items and repository files at a pinned commit' } else { 'wiki pages and work items' }) +
        '. Chat, push reviews and ' +
        'assessments use it. Writes are in documentation-agent-write, used only after approval on the Teams card.'
    }
    $body = @{ description = $description; tools = @($tools) } | ConvertTo-Json -Depth 10
    $created = Invoke-RestMethod -Method Post "$ProjectEndpoint/toolboxes/$ToolboxName/versions?api-version=$Api" `
        -Headers $headers -Body $body -ContentType 'application/json'
    $version = $created.version
    # The default version is what Foundry tools list; the runtime always pins an explicit version.
    Invoke-RestMethod -Method Patch "$ProjectEndpoint/toolboxes/$($ToolboxName)?api-version=$Api" -Headers $headers `
        -Body (@{ default_version = $version } | ConvertTo-Json) -ContentType 'application/json' | Out-Null
    Write-Host "Created toolbox '$ToolboxName' version $version (default)." -ForegroundColor Green
}

Write-Host "TOOLBOX_ENDPOINT=$ProjectEndpoint/toolboxes/$ToolboxName/versions/$version/mcp?api-version=$Api"
