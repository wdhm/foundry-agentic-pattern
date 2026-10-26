"""Check the compiled ARM template supplied on stdin; performs no Azure calls."""

import json
import sys


def verify(template):
    resources = template["resources"]
    assert template["variables"]["accountName"] == "foundry-eval-ci-r8n3ld"
    assert template["variables"]["projectName"] == "evaluation-ci"
    assert template["variables"]["identityName"] == "id-gh-isolated-eval"
    assert template["variables"]["inferenceDataActions"] == [
        "Microsoft.CognitiveServices/accounts/OpenAI/deployments/read",
        "Microsoft.CognitiveServices/accounts/AIServices/deployments/read",
        "Microsoft.CognitiveServices/accounts/OpenAI/responses/write",
        "Microsoft.CognitiveServices/accounts/OpenAI/responses/read",
        "Microsoft.CognitiveServices/accounts/AIServices/responses/write",
        "Microsoft.CognitiveServices/accounts/AIServices/responses/read",
        "Microsoft.CognitiveServices/accounts/OpenAI/deployments/chat/completions/action",
    ]
    roles = [r for r in resources if r["type"] == "Microsoft.Authorization/roleDefinitions"]
    assignments = [r for r in resources if r["type"] == "Microsoft.Authorization/roleAssignments"]
    assert len(roles) == len(assignments) == 4
    storage_role = next(r for r in roles if "isolated-eval-project-storage" in r["name"])
    assert storage_role["properties"]["assignableScopes"] == ["[resourceGroup().id]"]
    assert storage_role["properties"]["permissions"] == [{
        "actions": [], "notActions": [], "notDataActions": [],
        "dataActions": [
            "Microsoft.CognitiveServices/accounts/AIServices/agents/*/read",
            "Microsoft.CognitiveServices/accounts/AIServices/agents/*/write",
        ],
    }]
    storage_assignment = next(
        r for r in assignments if "isolated-eval-project-storage" in r["properties"]["roleDefinitionId"]
    )
    assert storage_assignment["scope"] == (
        "[resourceId('Microsoft.CognitiveServices/accounts/projects', "
        "variables('accountName'), variables('projectName'))]"
    )
    assert storage_assignment["properties"]["principalId"] == (
        "[reference(resourceId('Microsoft.ManagedIdentity/userAssignedIdentities', "
        "variables('identityName')), '2023-01-31').principalId]"
    )
    assert storage_assignment["properties"]["principalType"] == "ServicePrincipal"
    assets_role = next(r for r in roles if "isolated-eval-project-assets" in r["name"])
    assert assets_role["properties"]["type"] == "CustomRole"
    assert assets_role["properties"]["assignableScopes"] == ["[resourceGroup().id]"]
    assert assets_role["properties"]["permissions"] == [{
        "actions": [], "notActions": [], "notDataActions": [],
        "dataActions": ["Microsoft.CognitiveServices/accounts/AIServices/assets/write"],
    }]
    assets_assignment = next(
        r for r in assignments if "isolated-eval-project-assets" in r["properties"]["roleDefinitionId"]
    )
    assert assets_assignment["scope"] == storage_assignment["scope"]
    assert assets_assignment["properties"]["principalId"] == storage_assignment["properties"]["principalId"]
    assert assets_assignment["properties"]["principalType"] == "ServicePrincipal"
    for role in roles:
        if role is storage_role or role is assets_role:
            continue
        assert role["properties"]["assignableScopes"] == ["[resourceGroup().id]"]
        runner = "isolated-eval-runner" in role["name"]
        assert runner or "isolated-eval-model-inference" in role["name"]
        actions = ["Microsoft.CognitiveServices/accounts/deployments/read"]
        if runner:
            actions = [
                "Microsoft.CognitiveServices/accounts/read",
                "Microsoft.CognitiveServices/accounts/projects/read",
                *actions,
            ]
        assert role["properties"]["permissions"] == [{
            "actions": actions, "notActions": [], "notDataActions": [],
            "dataActions": (
                "[concat(variables('inferenceDataActions'), createArray("
                "'Microsoft.CognitiveServices/accounts/OpenAI/evals/read', "
                "'Microsoft.CognitiveServices/accounts/OpenAI/evals/write', "
                "'Microsoft.CognitiveServices/accounts/AIServices/evaluations/read', "
                "'Microsoft.CognitiveServices/accounts/AIServices/evaluations/write'))]"
                if runner else "[variables('inferenceDataActions')]"
            ),
        }]
    for assignment in assignments:
        if assignment is not storage_assignment and assignment is not assets_assignment:
            assert assignment["scope"] == (
                "[resourceId('Microsoft.CognitiveServices/accounts', variables('accountName'))]"
            )
    return "Compiled role/principal/project scope and unchanged account-role boundaries verified"


if __name__ == "__main__":
    print(verify(json.load(sys.stdin)))
