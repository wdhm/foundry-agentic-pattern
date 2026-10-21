import logging
import os

from agent_framework import BaseAgent
from agent_framework_foundry_hosting import ResponsesHostServer

from .agent import DocumentationAgent


def create_server() -> ResponsesHostServer:
    mode = os.environ.get("DOCUMENTATION_MODE", "stub")
    if os.environ.get("DOCUMENTATION_ENABLE_TEAMS") == "true" and mode != "approval":
        raise ValueError("Teams cards require approval mode; assessment/evaluation remain unchanged.")
    if os.environ.get("DOCUMENTATION_ENABLE_PUSH_FLOW") == "true" and (
        mode != "approval" or os.environ.get("DOCUMENTATION_ENABLE_TEAMS") != "true"
    ):
        raise ValueError("Push flow requires explicitly enabled Teams approval mode.")
    agent: BaseAgent
    if mode == "stub":
        agent = DocumentationAgent()
    elif mode == "assessment":
        from .assessment import AssessmentAgent
        from .settings import AssessmentSettings

        agent = AssessmentAgent(AssessmentSettings.from_environment())
    elif mode == "evaluation":
        if os.environ.get("DOCUMENTATION_ENABLE_EVALUATION") != "true":
            raise ValueError("Evaluation mode requires explicit DOCUMENTATION_ENABLE_EVALUATION=true.")
        from .evaluation import EvaluationAgent
        from .settings import AssessmentSettings

        agent = EvaluationAgent(AssessmentSettings.from_environment())
    elif mode == "approval":
        if os.environ.get("DOCUMENTATION_ENABLE_APPROVAL") != "true":
            raise ValueError("Approval mode requires explicit DOCUMENTATION_ENABLE_APPROVAL=true.")
        from .approval import ToolApprovalAgent, ToolApprovalPolicy

        agent = ToolApprovalAgent(ToolApprovalPolicy.from_environment())
        if os.environ.get("DOCUMENTATION_ENABLE_TEAMS") == "true":
            from .teams import create_teams_server

            return create_teams_server(agent)
    else:
        raise ValueError(
            "DOCUMENTATION_MODE must be 'stub', 'assessment' or explicitly enabled 'evaluation'/'approval'."
        )
    return ResponsesHostServer(agent, history_source="agent")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    create_server().run(host=os.environ.get("HOST", "127.0.0.1"))


if __name__ == "__main__":
    main()
