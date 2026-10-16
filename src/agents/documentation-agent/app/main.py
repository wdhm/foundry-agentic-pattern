import logging
import os

from agent_framework_foundry_hosting import ResponsesHostServer

from .agent import DocumentationAgent


def create_server() -> ResponsesHostServer:
    mode = os.environ.get("DOCUMENTATION_MODE", "stub")
    agent: DocumentationAgent
    if mode == "stub":
        agent = DocumentationAgent()
    elif mode == "assessment":
        from .assessment import AssessmentAgent
        from .settings import AssessmentSettings

        agent = AssessmentAgent(AssessmentSettings.from_environment())
    else:
        raise ValueError("DOCUMENTATION_MODE must be 'stub' or 'assessment'.")
    return ResponsesHostServer(agent, history_source="agent")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    create_server().run(host=os.environ.get("HOST", "127.0.0.1"))


if __name__ == "__main__":
    main()
