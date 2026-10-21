#Requires -Version 7
<#
.SYNOPSIS
    Workshop demo (P2): compares the read-only and write toolboxes, then shows that the Azure DevOps tools only
    work as the agent's own identity. Read-only.

.DESCRIPTION
    1. Reads both toolbox definitions and prints each tool source: connection, allowed tools, approval mode.
    2. With -TryAsMe, connects to the read-only toolbox's MCP endpoint as the signed-in person and runs
       tools/list. Foundry IQ and GitHub answer. Azure DevOps refuses, because connection ado-mcp-proxy uses
       AgenticIdentityToken: only the agent's identity can use it, never a person's token.

    tools/list only lists tools; no tool is called, nothing is written and no model is invoked.

    Requires: Azure CLI signed in with Azure AI User (or higher) on the Foundry project.

.EXAMPLE
    ./infra/scripts/demo-toolbox.ps1 -ProjectEndpoint https://<account>.services.ai.azure.com/api/projects/<project> -TryAsMe
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProjectEndpoint,
    [string[]]$Toolbox = @('documentation-agent-readonly', 'documentation-agent-write'),
    [switch]$TryAsMe
)

$ErrorActionPreference = 'Stop'
$ProjectEndpoint = $ProjectEndpoint.TrimEnd('/')
$token = az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv
if (-not $token) { throw "az account get-access-token failed. Run 'az login'." }
$headers = @{ Authorization = "Bearer $token" }

foreach ($name in $Toolbox) {
    $box = Invoke-RestMethod "$ProjectEndpoint/toolboxes/$($name)?api-version=v1" -Headers $headers
    $version = $box.default_version ?? $box.versions.latest.version ?? '1'
    $def = Invoke-RestMethod "$ProjectEndpoint/toolboxes/$name/versions/$($version)?api-version=v1" -Headers $headers
    $count = ($def.tools | ForEach-Object { $_.allowed_tools.tool_names.Count } | Measure-Object -Sum).Sum
    Write-Host "`n$name (version $version): $count tool(s)" -ForegroundColor Cyan
    foreach ($t in $def.tools) {
        '  {0,-10} connection {1,-18} {2}' -f $t.server_label, $t.project_connection_id, ($t.allowed_tools.tool_names -join ', ')
    }
}

if (-not $TryAsMe) { return }

$name = $Toolbox[0]
$box = Invoke-RestMethod "$ProjectEndpoint/toolboxes/$($name)?api-version=v1" -Headers $headers
$version = $box.default_version ?? $box.versions.latest.version ?? '1'
$mcp = "$ProjectEndpoint/toolboxes/$name/versions/$version/mcp?api-version=v1"
$mcpHeaders = @{ Authorization = "Bearer $token"; Accept = 'application/json, text/event-stream' }

Write-Host "`ntools/list on '$name' as $(az account show --query user.name -o tsv) (a person, not the agent):" -ForegroundColor Cyan
$init = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"p2-demo","version":"1"}}}'
$session = Invoke-WebRequest -Method Post $mcp -Headers $mcpHeaders -Body $init -ContentType 'application/json'
if ($session.Headers['Mcp-Session-Id']) { $mcpHeaders['Mcp-Session-Id'] = "$($session.Headers['Mcp-Session-Id'])" }
$list = Invoke-RestMethod -Method Post $mcp -Headers $mcpHeaders -Body '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' -ContentType 'application/json'

if ($list.result.tools) {
    $list.result.tools | ForEach-Object { "  OK      $($_.name)" }
} elseif ($list.error) {
    $detail = $list.error.message
    if ($detail -match '(\d+) tool source\(s\), succeeded for (\d+)') {
        Write-Host "  Sources that answered: $($Matches[2]). Sources refused: $($Matches[1])." -ForegroundColor Yellow
    }
    if ($detail -match '\{.*\}$') {
        foreach ($e in ($Matches[0] | ConvertFrom-Json).errors) {
            Write-Host "  REFUSED $($e.name): $($e.error.message)" -ForegroundColor Red
        }
    } else { Write-Host "  $detail" -ForegroundColor Red }
    Write-Host "`nThe Azure DevOps connection only accepts the agent's own identity (AgenticIdentityToken)." -ForegroundColor Green
}
