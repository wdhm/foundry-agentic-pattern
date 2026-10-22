"""Offline compiled-template contracts. Requires BICEP_CLI or bicep on PATH; never calls Azure."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def gateway_build(tmp_path_factory):
    cli = os.environ.get("BICEP_CLI") or shutil.which("bicep")
    if not cli:
        pytest.skip("Set BICEP_CLI to run local APIM template compilation contracts.")
    directory = tmp_path_factory.mktemp("ai-gateway-build")
    for path in (ROOT / "infra" / "ai-gateway").iterdir():
        if path.suffix in {".bicep", ".xml"}:
            shutil.copyfile(path, directory / path.name)
    return cli, directory


@pytest.fixture(scope="module")
def templates(gateway_build):
    cli, directory = gateway_build
    result = {}
    for name in (
        "main", "bootstrap-public-developer", "managed-insights-logger", "azure-monitor-diagnostics", "agent-ingress",
    ):
        output = directory / (name + ".json")
        subprocess.run(
            [cli, "build", str(directory / (name + ".bicep")), "--outfile", str(output)],
            check=True, capture_output=True, text=True,
        )
        result[name] = json.loads(output.read_text(encoding="utf-8-sig"))
    return result


@pytest.mark.parametrize("tool_parameters", [
    "",
    "param enableToolRouting = false",
    "param diagnosticType = 'azuremonitor'\nparam enableToolRouting = false",
    "param readToolboxBaseUrl = 'https://offline.invalid/toolboxes/read/versions/1'\n"
    "param toolRequestsPerMinute = 1",
])
def test_required_parameter_shape_supports_model_only_and_legacy_tools(gateway_build, tool_parameters):
    cli, directory = gateway_build
    parameter_file = directory / "offline.bicepparam"
    parameter_file.write_text(
        "using './main.bicep'\n"
        "param apimName = 'offline-validation'\n"
        "param projectEndpoint = 'https://offline.invalid/api/projects/offline'\n"
        "param tenantId = '00000000-0000-0000-0000-000000000001'\n"
        "param callerObjectId = '00000000-0000-0000-0000-000000000002'\n"
        "param loggerResourceId = '/offline/loggers/offline'\n"
        "param modelDeployment = 'offline-model'\n"
        "param tokensPerMinute = 1\n"
        "param dailyTokenQuota = 1\n" + tool_parameters + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [cli, "build-params", str(parameter_file), "--outfile", str(directory / "parameters.json")],
        check=True, capture_output=True, text=True,
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_tool_resources_and_output_are_actually_conditional(templates, enabled):
    template = templates["main"]
    resources = template["resources"]
    tool_symbols = {"toolApi", "toolOperations", "toolPolicy", "toolDiagnostics"}
    for name in tool_symbols:
        assert resources[name]["condition"] == "[parameters('enableToolRouting')]"
    active = {
        name for name, resource in resources.items()
        if resource.get("condition") is None or enabled
    }
    assert tool_symbols.intersection(active) == (tool_symbols if enabled else set())
    for name in {"modelApi", "modelPolicy", "modelDiagnostics"}:
        assert name in active
        assert not tool_symbols.intersection(resources[name].get("dependsOn", []))
    output = template["outputs"]["toolboxGatewayEndpoint"]
    assert output["nullable"] is True
    assert output["value"].startswith("[if(parameters('enableToolRouting'), ")
    assert output["value"].endswith(", null())]")
    assert "enableToolRouting" not in template["outputs"]["modelGatewayEndpoint"]["value"]
    assert not any("agent" in name.lower() for name in resources)


def test_model_only_has_no_tool_configuration_or_required_tool_parameters(templates):
    template = templates["main"]
    parameters = template["parameters"]
    assert parameters["readToolboxBaseUrl"]["nullable"] is True
    assert parameters["toolRequestsPerMinute"]["nullable"] is True
    assert parameters["toolRequestsPerMinute"]["minValue"] == 1
    # Old callers supplying the existing toolbox URL retain their two-route behavior.
    assert parameters["enableToolRouting"]["defaultValue"] == (
        "[not(equals(parameters('readToolboxBaseUrl'), null()))]"
    )
    for name in ("tokensPerMinute", "dailyTokenQuota"):
        assert parameters[name]["minValue"] == 1
        assert "defaultValue" not in parameters[name]
    variables = template["variables"]
    assert not any("tool" in name for name in variables["modelSettings"])
    assert variables["toolSettings"].startswith("[if(parameters('enableToolRouting'), ")
    assert variables["toolSettings"].endswith(", createObject())]")
    assert "fail('Tool routing requires toolRequestsPerMinute.')" in variables["toolSettings"]
    assert "fail('Tool routing requires readToolboxBaseUrl.')" in variables["toolSettings"]
    service_url = template["resources"]["toolApi"]["properties"]["serviceUrl"]
    assert service_url.startswith("[if(parameters('enableToolRouting'), ")
    assert service_url.endswith(", null())]")
    assert variables["settings"] == "[union(variables('modelSettings'), variables('toolSettings'))]"
    assert template["resources"]["namedValues"]["copy"]["count"] == "[length(items(variables('settings')))]"


def test_body_free_diagnostics_cover_only_deployed_apis(templates):
    template = templates["main"]
    settings = template["variables"]["baseDiagnosticsProperties"]
    assert settings["logClientIp"] is False
    for side in ("frontend", "backend"):
        for direction in ("request", "response"):
            assert settings[side][direction] == {"headers": [], "body": {"bytes": 0}}
    for name in ("modelDiagnostics", "toolDiagnostics"):
        assert template["resources"][name]["properties"] == "[variables('diagnosticsProperties')]"
        assert "parameters('diagnosticType')" in template["resources"][name]["name"]
    assert template["parameters"]["diagnosticType"]["allowedValues"] == ["applicationinsights", "azuremonitor"]
    assert template["parameters"]["diagnosticType"]["defaultValue"] == "applicationinsights"
    assert "httpCorrelationProtocol" not in settings
    assert template["variables"]["diagnosticsProperties"] == (
        "[union(variables('baseDiagnosticsProperties'), "
        "if(equals(parameters('diagnosticType'), 'applicationinsights'), "
        "createObject('httpCorrelationProtocol', 'W3C'), createObject()))]"
    )


def test_public_developer_bootstrap_creates_only_service_without_routes_or_grants(templates):
    template = templates["bootstrap-public-developer"]
    resources = {resource["type"]: resource for resource in template["resources"]}
    assert set(resources) == {"Microsoft.ApiManagement/service"}
    service = resources["Microsoft.ApiManagement/service"]
    assert service["sku"] == {"name": "Developer", "capacity": 1}
    assert service["identity"] == {"type": "SystemAssigned"}
    assert service["properties"]["virtualNetworkType"] == "None"
    assert service["properties"]["publicNetworkAccess"] == "Enabled"
    assert service["properties"]["developerPortalStatus"] == "Disabled"
    assert not any(
        key in service["properties"] for key in ("virtualNetworkConfiguration", "privateEndpointConnections")
    )
    assert set(service["properties"]["customProperties"].values()) == {"false"}
    assert set(template["parameters"]) == {"apimName", "location", "publisherName", "publisherEmail"}
    for name in template["parameters"]:
        assert "defaultValue" not in template["parameters"][name]
        assert template["parameters"][name]["minLength"] >= 1
    assert set(template["outputs"]) == {"gatewayUrl", "apimPrincipalId"}


def test_separate_managed_logger_has_only_component_scoped_telemetry_grant(templates):
    template = templates["managed-insights-logger"]
    resources = {resource["type"]: resource for resource in template["resources"]}
    assert set(resources) == {
        "Microsoft.Authorization/roleAssignments",
        "Microsoft.ApiManagement/service/loggers",
    }
    grant = resources["Microsoft.Authorization/roleAssignments"]
    assert grant["scope"] == "[format('Microsoft.Insights/components/{0}', parameters('applicationInsightsName'))]"
    assert "3913510d-42f4-4e42-8a64-420c390055eb" in grant["properties"]["roleDefinitionId"]
    assert "principalId" in grant["properties"]["principalId"]
    logger = resources["Microsoft.ApiManagement/service/loggers"]
    assert logger["properties"]["credentials"] == {
        "identityClientId": "SystemAssigned",
        "connectionString": (
            "[reference(resourceId('Microsoft.Insights/components', "
            "parameters('applicationInsightsName')), '2020-02-02').ConnectionString]"
        ),
    }
    assert logger["properties"]["resourceId"] == (
        "[resourceId('Microsoft.Insights/components', parameters('applicationInsightsName'))]"
    )
    assert set(template["outputs"]) == {"loggerResourceId"}
    assert not any("ConnectionString" in str(output) for output in template["outputs"].values())


def test_azure_monitor_uses_existing_workspace_without_roles_or_payload_categories(templates):
    template = templates["azure-monitor-diagnostics"]
    resources = {resource["type"]: resource for resource in template["resources"]}
    assert set(resources) == {
        "Microsoft.Insights/diagnosticSettings",
        "Microsoft.ApiManagement/service/diagnostics",
        "Microsoft.ApiManagement/service/loggers",
        "Microsoft.ApiManagement/service/policies",
    }
    sink = resources["Microsoft.Insights/diagnosticSettings"]
    assert sink["scope"] == "[format('Microsoft.ApiManagement/service/{0}', parameters('apimName'))]"
    assert sink["properties"] == {
        "workspaceId": (
            "[resourceId('Microsoft.OperationalInsights/workspaces', parameters('logAnalyticsWorkspaceName'))]"
        ),
        "logAnalyticsDestinationType": "Dedicated",
        "logs": [{"category": "GatewayLogs", "enabled": True}],
        "metrics": [],
    }
    defaults = resources["Microsoft.ApiManagement/service/diagnostics"]["properties"]
    logger = resources["Microsoft.ApiManagement/service/loggers"]
    assert logger["name"] == "[format('{0}/{1}', parameters('apimName'), 'azuremonitor')]"
    assert logger["properties"] == {
        "loggerType": "azureMonitor",
        "description": "Credential-free Azure Monitor gateway diagnostics.",
    }
    logger_id = "[resourceId('Microsoft.ApiManagement/service/loggers', parameters('apimName'), 'azuremonitor')]"
    assert defaults["loggerId"] == logger_id
    assert logger_id in resources["Microsoft.ApiManagement/service/diagnostics"]["dependsOn"]
    assert template["outputs"]["loggerResourceId"]["value"] == logger_id
    assert defaults["logClientIp"] is False
    for side in ("frontend", "backend"):
        for direction in ("request", "response"):
            assert defaults[side][direction] == {"headers": [], "body": {"bytes": 0}}
    assert set(template["outputs"]) == {"loggerResourceId"}
    assert "ConnectionString" not in json.dumps(template)
    assert "listKeys" not in json.dumps(template)


def test_setup_denies_unconfigured_routes_before_telemetry_and_owned_policy_overrides(templates):
    template = templates["azure-monitor-diagnostics"]
    resources = {resource["type"]: resource for resource in template["resources"]}
    deny = resources["Microsoft.ApiManagement/service/policies"]
    assert deny["name"] == "[format('{0}/{1}', parameters('apimName'), 'policy')]"
    assert deny["properties"]["format"] == "rawxml"
    policy = ElementTree.fromstring(deny["properties"]["value"])
    assert [node.tag for node in policy.find("inbound")] == ["return-response"]
    assert policy.find("inbound/return-response/set-status").attrib == {
        "code": "403", "reason": "Gateway route not enabled",
    }
    assert all(len(policy.find(section)) == 0 for section in ("backend", "outbound", "on-error"))
    assert policy.find(".//forward-request") is None
    deny_id = "[resourceId('Microsoft.ApiManagement/service/policies', parameters('apimName'), 'policy')]"
    for resource_type in ("Microsoft.ApiManagement/service/loggers", "Microsoft.Insights/diagnosticSettings"):
        assert deny_id in resources[resource_type]["dependsOn"]
    model = ElementTree.parse(ROOT / "infra" / "ai-gateway" / "model-policy.xml").getroot()
    assert model.find(".//base") is None
    assert model.find("inbound")[0].tag == "validate-jwt"
    assert model.find("backend/forward-request") is not None
