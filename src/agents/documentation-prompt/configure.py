"""Attach versioned assessment instructions to an existing Foundry prompt agent."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from contracts.prompt import configured_definition

ASSESSMENT_PATH = Path(__file__).parent.parent / "documentation-agent" / "app"
PROMPT_PATH = ASSESSMENT_PATH / "prompts" / "gap-analysis-v1.txt"
POLICY_PATH = ASSESSMENT_PATH / "policies" / "documentation-analysis-v1.txt"
START = "[BEGIN documentation-gap-analysis]"
END = "[END documentation-gap-analysis]"


def assessment_definition(definition: dict[str, Any], prompt: str, policy: str) -> dict[str, Any]:
    if not prompt.strip() or not policy.strip():
        raise ValueError("Both the versioned prompt and policy must contain instructions.")
    updated = configured_definition(definition)
    instructions = updated["instructions"]
    if START in instructions or END in instructions:
        if instructions.count(START) != 1 or instructions.count(END) != 1:
            raise ValueError("Ambiguous assessment instruction markers; review the existing definition.")
        before, rest = instructions.split(START, 1)
        if END not in rest:
            raise ValueError("Assessment instruction markers are out of order.")
        _, after = rest.split(END, 1)
        updated["instructions"] = before + START + "\n" + prompt + "\n\n" + policy + "\n" + END + after
    else:
        updated["instructions"] = instructions + "\n\n" + START + "\n" + prompt + "\n\n" + policy + "\n" + END
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-endpoint", required=True)
    parser.add_argument("--agent-name", required=True)
    parser.add_argument("--base-version", required=True)
    parser.add_argument(
        "--apply", action="store_true", help="Create a version; otherwise preview the local definition."
    )
    args = parser.parse_args()

    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition
    from azure.identity import AzureCliCredential

    prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    policy = POLICY_PATH.read_text(encoding="utf-8").strip()
    with (
        AzureCliCredential() as credential,
        AIProjectClient(endpoint=args.project_endpoint, credential=credential) as project,
    ):
        latest = project.agents.get(args.agent_name).as_dict()["versions"]["latest"]["version"]
        if latest != args.base_version:
            raise ValueError(f"Latest is {latest}, not base {args.base_version}; review it before configuring.")
        agent = project.agents.get_version(args.agent_name, args.base_version)
        definition = agent.definition.as_dict()
        updated = assessment_definition(definition, prompt, policy)
        if not args.apply:
            print(json.dumps(updated, indent=2))
            return
        if updated == definition:
            print(json.dumps({"name": agent.name, "version": agent.version, "changed": False}))
            return
        version = project.agents.create_version(
            agent_name=agent.name,
            definition=PromptAgentDefinition(updated),
            description=agent.description,
            metadata={
                **(agent.metadata or {}),
                "gap_analysis_prompt": "1.0.0",
                "gap_analysis_policy": "1.0.0",
                "gap_analysis_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "gap_analysis_policy_sha256": hashlib.sha256(policy.encode()).hexdigest(),
            },
        )
        print(json.dumps({"name": version.name, "version": version.version, "changed": True}))


if __name__ == "__main__":
    main()
