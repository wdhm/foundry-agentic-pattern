"""Offline role/scope contracts; BICEP_CLI enables compilation without Azure calls."""

import copy
import json
import os
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest

INFRA = Path(__file__).parents[2] / "infra" / "isolated-evaluation"
checks = runpy.run_path(str(INFRA / "assert-template.py"))
verify = checks["verify"]
verify_config = checks["verify_config"]


@pytest.fixture(scope="module")
def template():
    cli = os.environ.get("BICEP_CLI") or shutil.which("bicep")
    if not cli:
        pytest.skip("Set BICEP_CLI to compile isolated evaluation IAM contracts.")
    result = subprocess.run(
        [cli, "build", str(INFRA / "main.bicep"), "--stdout"],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def test_exact_compiled_isolated_roles(template):
    assert verify(template)


@pytest.mark.parametrize("mutation", [
    "parent", "model", "version", "sku", "capacity", "upgrade", "identity", "judge_model", "mini_capacity",
])
def test_compiled_assertions_reject_model_or_identity_drift(template, mutation):
    value = copy.deepcopy(template)
    models = [r for r in value["resources"] if r["type"].endswith("/deployments")]
    full = next(r for r in models if "copy" not in r)
    mini = next(r for r in models if "copy" in r)
    if mutation == "parent":
        full["name"] = "foundry-agentic-R8N3LD/eval-candidate-full"
    elif mutation == "model":
        full["properties"]["model"]["name"] = "gpt-6-luna"
    elif mutation == "version":
        full["properties"]["model"]["version"] = "latest"
    elif mutation == "sku":
        full["sku"]["name"] = "DataZoneStandard"
    elif mutation == "capacity":
        full["sku"]["capacity"] = 100
    elif mutation == "upgrade":
        full["properties"]["versionUpgradeOption"] = "OnceNewDefaultVersionAvailable"
    elif mutation == "identity":
        full["identity"] = {"type": "SystemAssigned"}
    elif mutation == "judge_model":
        mini["properties"]["model"]["name"] = "gpt-5.4"
    else:
        mini["sku"]["capacity"] = 100
    with pytest.raises(AssertionError):
        verify(value)


def test_full_supplied_configuration_lineage():
    verify_config(json.loads((INFRA / "supplied-demo-config.json").read_text()))


@pytest.mark.parametrize("field,value", [
    ("observed_model", "gpt-5.4-mini-2026-03-17"),
    ("evaluator_version", "2026-03-05"), ("optimizer_version", "2026-03-05"),
    ("evaluator_deployment", "eval-candidate-full"), ("optimizer_deployment", "eval-candidate-full"),
    ("AZURE_AI_MODEL_DEPLOYMENT_NAME", "eval-candidate"), ("DOCUMENTATION_MODEL_VERSION", "2026-03-17"),
    ("DOCUMENTATION_PROJECT_ENDPOINT", "https://foundry-agentic-r8n3ld.services.ai.azure.com/api/projects/proj-agentic"),
    ("reasoning_effort", "low"),
])
def test_configuration_assertions_reject_lineage_routing_or_option_changes(field, value):
    config = json.loads((INFRA / "supplied-demo-config.json").read_text())
    target = config if field in config else config["settings"]
    target[field] = value
    with pytest.raises(AssertionError):
        verify_config(config)


@pytest.mark.parametrize("mutation", [
    "account_scope", "production_scope", "project_identity", "other_principal", "subscription_assignable",
    "assets_read", "assets_delete", "assets_wildcard", "management_action", "top_level_agents",
    "prior_child_patterns", "account_role_assets", "inference_assets",
])
def test_compiled_assertions_reject_permission_or_identity_expansion(template, mutation):
    value = copy.deepcopy(template)
    roles = [r for r in value["resources"] if r["type"] == "Microsoft.Authorization/roleDefinitions"]
    role = next(r for r in roles if "isolated-eval-project-assets" in r["name"])
    assignment = next(
        r for r in value["resources"]
        if r["type"] == "Microsoft.Authorization/roleAssignments"
        and "isolated-eval-project-assets" in r["properties"]["roleDefinitionId"]
    )
    permissions = role["properties"]["permissions"][0]
    if mutation == "account_scope":
        assignment["scope"] = "[resourceId('Microsoft.CognitiveServices/accounts', variables('accountName'))]"
    elif mutation == "production_scope":
        assignment["scope"] = "/subscriptions/example/resourceGroups/production/providers/example/projects/proj-agentic"
    elif mutation == "project_identity":
        assignment["properties"]["principalId"] = "[reference('evaluation-ci').identity.principalId]"
    elif mutation == "other_principal":
        assignment["properties"]["principalId"] = "00000000-0000-0000-0000-000000000000"
    elif mutation == "subscription_assignable":
        role["properties"]["assignableScopes"] = ["[subscription().id]"]
    elif mutation == "management_action":
        permissions["actions"] = ["Microsoft.CognitiveServices/accounts/write"]
    elif mutation == "prior_child_patterns":
        storage = next(r for r in roles if "isolated-eval-project-storage" in r["name"])
        storage["properties"]["permissions"][0]["dataActions"].append(
            "Microsoft.CognitiveServices/accounts/AIServices/agents/write",
        )
    elif mutation == "account_role_assets":
        runner = next(r for r in roles if "isolated-eval-runner" in r["name"])
        runner["properties"]["permissions"][0]["dataActions"] = permissions["dataActions"]
    elif mutation == "inference_assets":
        value["variables"]["inferenceDataActions"].extend(permissions["dataActions"])
    else:
        action = {
            "assets_read": "assets/read", "assets_delete": "assets/delete",
            "assets_wildcard": "assets/*", "top_level_agents": "agents/write",
        }[mutation]
        permissions["dataActions"].append("Microsoft.CognitiveServices/accounts/AIServices/" + action)
    with pytest.raises(AssertionError):
        verify(value)
