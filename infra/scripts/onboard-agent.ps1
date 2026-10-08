#Requires -Version 7
<#
.SYNOPSIS
    Onboards a Foundry agent's identity to Azure DevOps through the ado_mcp gateway. Idempotent.

.DESCRIPTION
    Run after you create a Foundry agent. Every new agent gets its own Entra agent identity and blueprint, so this must
    be repeated per agent. Automates steps 2, 3, 4, 5.2 and 6.2 of docs/workshop/agent-identity-guide.md, then re-points
    the single-agent gateway to the agent.

      1. Reads the agent's instance identity and blueprint from Foundry.
      2. Creates the agent user <AgentName>@<default domain> (Graph beta agentUser).
      3. Adds the agent user to Azure DevOps (Basic + project Contributors).
      4. Grants delegated consent to the Azure DevOps MCP app for the agent user only (consentType Principal).
      5. Adds the gateway's managed identity as a federated credential on the agent's blueprint.
      6. Assigns the gateway app role to the agent identity.
      7. Re-points the gateway (Container App env vars) to this agent and waits until it is healthy.

    Requires: Azure CLI signed in as an account that can create users and grants in Entra and add users in Azure DevOps.
    The agent must already have the MCP tool that uses the gateway connection (guide step 8).

.EXAMPLE
    ./infra/scripts/onboard-agent.ps1 -AgentName doc-agent `
        -ProjectEndpoint https://<account>.services.ai.azure.com/api/projects/<project> `
        -ResourceGroup rg-foundry-agentic-pattern -GatewayAppId <gateway-app-id> `
        -AdoOrg foundry-agentic -AdoProject integration-team
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AgentName,
    [Parameter(Mandatory)][string]$ProjectEndpoint,
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$GatewayAppId,
    [Parameter(Mandatory)][string]$AdoOrg,
    [Parameter(Mandatory)][string]$AdoProject,
    [string]$ContainerApp = 'ca-doc-agent-mcp',
    [string]$ManagedIdentity = 'id-doc-agent-mcp',
    [string]$GatewayRole = 'Mcp.Tools.ReadWrite.All',
    [string]$AdoScopes = 'Ado.Mcp.Tools wit.read wiki.read wiki.write',
    [switch]$SkipGateway
)

$ErrorActionPreference = 'Stop'
$AdoMcpAppId = '2a72489c-aab2-4b65-b93a-a91edccf33b8'   # Microsoft "Azure DevOps MCP" application
$AdoResource = '499b84ac-1321-427f-aa17-267ca6975798'   # Azure DevOps
$Graph = 'https://graph.microsoft.com'

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
    if ($null -ne $Body) { $params.Body = $Body | ConvertTo-Json -Depth 10; $params.ContentType = 'application/json' }
    Invoke-RestMethod @params
}

function Get-OrNull([scriptblock]$Call) {
    try { & $Call } catch { if ($_.Exception.Response.StatusCode -eq [System.Net.HttpStatusCode]::NotFound) { $null } else { throw } }
}

# Newly created Entra objects take a moment to replicate to Graph and Azure DevOps.
function Invoke-WithRetry([scriptblock]$Call, [int]$Attempts = 8, [int]$DelaySeconds = 10) {
    for ($i = 1; ; $i++) {
        try { return & $Call } catch {
            if ($i -ge $Attempts) { throw }
            Write-Host "    retry $i/$Attempts in ${DelaySeconds}s: $($_.Exception.Message)" -ForegroundColor DarkYellow
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

$graphToken = Get-Token $Graph
$tenantId = az account show --query tenantId -o tsv

Step "1. Read agent '$AgentName'"
$agent = Invoke-Api GET "$ProjectEndpoint/agents/${AgentName}?api-version=2025-11-15-preview" (Get-Token 'https://ai.azure.com') `
    -Headers @{ 'Foundry-Features' = 'AgentEndpoints=V1Preview' }
if (-not $agent.instance_identity) {
    throw "Agent '$AgentName' has no instance_identity (legacy agent on the shared project identity). Recreate it: https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-agent-applications"
}
$identityId = $agent.instance_identity.principal_id
$identityClientId = $agent.instance_identity.client_id
$blueprintAppId = $agent.blueprint.client_id
Done "agent identity $identityId, blueprint $blueprintAppId"

Step '2. Agent user'
$domain = ((Invoke-Api GET "$Graph/v1.0/organization?`$select=verifiedDomains" $graphToken).value[0].verifiedDomains |
    Where-Object isDefault).name
$upn = "$AgentName@$domain"
$user = Get-OrNull { Invoke-Api GET "$Graph/beta/users/${upn}?`$select=id,userPrincipalName,identityParentId" $graphToken }
if ($user) {
    if ($user.identityParentId -ne $identityId) {
        throw "$upn exists but belongs to agent identity $($user.identityParentId), not $identityId (agent recreated?). Delete the old agent user first."
    }
    Done "exists: $upn"
} else {
    $user = Invoke-Api POST "$Graph/beta/users" $graphToken @{
        '@odata.type'     = 'microsoft.graph.agentUser'
        displayName       = "$AgentName (agent user)"
        userPrincipalName = $upn
        mailNickname      = $AgentName
        accountEnabled    = $true
        identityParentId  = $identityId
    }
    Done "created: $upn ($($user.id))"
}

Step '3. Azure DevOps membership (Basic + Contributors)'
$adoToken = Get-Token $AdoResource
$entitlementsUri = "https://vsaex.dev.azure.com/$AdoOrg/_apis/userentitlements"
$existing = (Invoke-Api GET "${entitlementsUri}?`$filter=name eq '$upn'&api-version=7.1-preview.3" $adoToken).members |
    Where-Object { $_.user.principalName -eq $upn }
if ($existing) {
    Done "exists: access level $($existing.accessLevel.accountLicenseType)"
} else {
    $project = Invoke-Api GET "https://dev.azure.com/$AdoOrg/_apis/projects/${AdoProject}?api-version=7.1" $adoToken
    Invoke-WithRetry {
        $result = Invoke-Api POST "${entitlementsUri}?api-version=7.1-preview.3" $adoToken @{
            accessLevel         = @{ accountLicenseType = 'express' }
            user                = @{ principalName = $upn; subjectKind = 'user' }
            projectEntitlements = @(@{ group = @{ groupType = 'projectContributor' }; projectRef = @{ id = $project.id } })
        }
        if (-not $result.isSuccess) { throw "Azure DevOps: $($result.operationResult.errors | ConvertTo-Json -Compress)" }
    }
    Done "added to $AdoOrg with Basic, Contributors in $AdoProject"
}

Step '4. Delegated consent to Azure DevOps MCP for the agent user only'
$adoMcpSp = (Invoke-Api GET "$Graph/v1.0/servicePrincipals?`$filter=appId eq '$AdoMcpAppId'" $graphToken).value | Select-Object -First 1
if (-not $adoMcpSp) {
    $adoMcpSp = Invoke-Api POST "$Graph/v1.0/servicePrincipals" $graphToken @{ appId = $AdoMcpAppId }
    Done "created Azure DevOps MCP service principal $($adoMcpSp.id)"
}
$grant = (Invoke-Api GET "$Graph/v1.0/oauth2PermissionGrants?`$filter=clientId eq '$identityId'" $graphToken).value |
    Where-Object { $_.principalId -eq $user.id -and $_.resourceId -eq $adoMcpSp.id }
if ($grant -and $grant.scope -eq $AdoScopes) {
    Done "exists: $AdoScopes"
} elseif ($grant) {
    Invoke-Api PATCH "$Graph/v1.0/oauth2PermissionGrants/$($grant.id)" $graphToken @{ scope = $AdoScopes } | Out-Null
    Done "updated scope: $AdoScopes"
} else {
    Invoke-WithRetry {
        Invoke-Api POST "$Graph/v1.0/oauth2PermissionGrants" $graphToken @{
            clientId = $identityId; consentType = 'Principal'; principalId = $user.id; resourceId = $adoMcpSp.id; scope = $AdoScopes
        } | Out-Null
    }
    Done "granted: $AdoScopes"
}

Step "5. Gateway managed identity '$ManagedIdentity' as blueprint credential"
$mi = az identity show -g $ResourceGroup -n $ManagedIdentity --query '{principalId:principalId,clientId:clientId}' -o json | ConvertFrom-Json
$ficUri = "$Graph/beta/applications(appId='$blueprintAppId')/federatedIdentityCredentials"
if ((Invoke-Api GET $ficUri $graphToken).value | Where-Object subject -eq $mi.principalId) {
    Done 'exists'
} else {
    Invoke-Api POST $ficUri $graphToken @{
        name      = 'ado-mcp-gateway'
        issuer    = "https://login.microsoftonline.com/$tenantId/v2.0"
        subject   = $mi.principalId
        audiences = @('api://AzureADTokenExchange')
    } | Out-Null
    Done 'added federated credential ado-mcp-gateway'
}

Step "6. Gateway app role '$GatewayRole' for the agent identity"
$gatewaySp = (Invoke-Api GET "$Graph/v1.0/servicePrincipals?`$filter=appId eq '$GatewayAppId'&`$select=id,appRoles" $graphToken).value[0]
$roleId = ($gatewaySp.appRoles | Where-Object value -eq $GatewayRole).id
if (-not $roleId) { throw "App role $GatewayRole not found on gateway app $GatewayAppId" }
$assigned = (Invoke-Api GET "$Graph/v1.0/servicePrincipals/$($gatewaySp.id)/appRoleAssignedTo" $graphToken).value |
    Where-Object { $_.principalId -eq $identityId -and $_.appRoleId -eq $roleId }
if ($assigned) {
    Done 'exists'
} else {
    Invoke-Api POST "$Graph/v1.0/servicePrincipals/$($gatewaySp.id)/appRoleAssignedTo" $graphToken @{
        principalId = $identityId; resourceId = $gatewaySp.id; appRoleId = $roleId
    } | Out-Null
    Done 'assigned'
}

if ($SkipGateway) { Step '7. Gateway: skipped'; return }

Step "7. Re-point gateway '$ContainerApp' to this agent"
$desired = [ordered]@{ AGENT_BLUEPRINT_CLIENT_ID = $blueprintAppId; AGENT_IDENTITY_CLIENT_ID = $identityClientId; AGENT_USER_UPN = $upn }
$app = az containerapp show -g $ResourceGroup -n $ContainerApp -o json | ConvertFrom-Json
$current = @{}; $app.properties.template.containers[0].env | ForEach-Object { $current[$_.name] = $_.value }
$changes = $desired.Keys | Where-Object { $current[$_] -ne $desired[$_] }
if (-not $changes) {
    Done 'already points to this agent'
} else {
    az containerapp update -g $ResourceGroup -n $ContainerApp -o none --set-env-vars ($desired.Keys | ForEach-Object { "$_=$($desired[$_])" })
    if ($LASTEXITCODE) { throw 'az containerapp update failed' }
    $revision = az containerapp show -g $ResourceGroup -n $ContainerApp --query properties.latestRevisionName -o tsv
    Invoke-WithRetry -Attempts 18 {
        $state = az containerapp revision show -g $ResourceGroup -n $ContainerApp --revision $revision --query properties.runningState -o tsv
        if ($state -notlike 'Running*') { throw "revision $revision is $state" }
    }
    Done "revision $revision running"
}
$fqdn = $app.properties.configuration.ingress.fqdn
Invoke-WithRetry { Invoke-RestMethod "https://$fqdn/healthz" | Out-Null }
Done "https://$fqdn/healthz OK"

Write-Host "`nOnboarded '$AgentName': agent user $upn can use Azure DevOps through https://$fqdn/mcp" -ForegroundColor Green
