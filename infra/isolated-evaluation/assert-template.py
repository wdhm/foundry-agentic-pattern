"""Check the compiled ARM template supplied on stdin; performs no Azure calls."""

import json
import sys


def verify(template):
    resources = template["resources"]
    assert template["variables"]["accountName"] == "foundry-eval-ci-r8n3ld"
    assert template["variables"]["projectName"] == "evaluation-ci"
    assert template["variables"]["identityName"] == "id-gh-isolated-eval"
    for action in template["variables"]["inferenceDataActions"]:
        assert "*" not in action and "/agents/" not in action
    roles = [r for r in resources if r["type"] == "Microsoft.Authorization/roleDefinitions"]
    assignments = [r for r in resources if r["type"] == "Microsoft.Authorization/roleAssignments"]
    assert len(roles) == len(assignments) == 3
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
    for role in roles:
        if role is storage_role:
            continue
        assert role["properties"]["assignableScopes"] == ["[resourceGroup().id]"]
        for permission in role["properties"]["permissions"]:
            data = permission["dataActions"]
            if isinstance(data, str):
                assert data in (
                    "[variables('inferenceDataActions')]",
                    "[concat(variables('inferenceDataActions'), createArray("
                    "'Microsoft.CognitiveServices/accounts/OpenAI/evals/read', "
                    "'Microsoft.CognitiveServices/accounts/OpenAI/evals/write', "
                    "'Microsoft.CognitiveServices/accounts/AIServices/evaluations/read', "
                    "'Microsoft.CognitiveServices/accounts/AIServices/evaluations/write'))]",
                )
                data = [data]
            for action in permission["actions"] + data:
                assert "*" not in action
                assert "/agents/" not in action
    for assignment in assignments:
        if assignment is not storage_assignment:
            assert assignment["scope"] == (
                "[resourceId('Microsoft.CognitiveServices/accounts', variables('accountName'))]"
            )
    return "Compiled role/principal/project scope and unchanged account-role boundaries verified"


if __name__ == "__main__":
    print(verify(json.load(sys.stdin)))
