import logging
import os

from agent_framework import BaseAgent
from agent_framework_foundry_hosting import ResponsesHostServer

from .agent import DocumentationAgent


def create_server() -> ResponsesHostServer:
    mode = os.environ.get("DOCUMENTATION_MODE", "stub")
    chat_enabled = os.environ.get("DOCUMENTATION_ENABLE_CHAT") == "true"
    if os.environ.get("DOCUMENTATION_ENABLE_CHANNEL_REVIEWS") == "true" and (
        mode != "approval" or os.environ.get("DOCUMENTATION_ENABLE_TEAMS") != "true"
        or os.environ.get("DOCUMENTATION_ENABLE_PUSH_FLOW") != "true"
    ):
        raise ValueError("Channel reviews require Teams, push flow and approval mode.")
    if chat_enabled and mode != "approval":
        raise ValueError("Conversational chat requires approval mode; assessment/evaluation remain unchanged.")
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
        from .approval import ToolApprovalAgent, ToolApprovalPolicy, wiki_reader_from_environment

        policy = ToolApprovalPolicy.from_environment()
        agent = ToolApprovalAgent(policy, wiki_reader=wiki_reader_from_environment(policy))
        from .conversation import ConversationRouter, ConversationService

        conversation = ConversationService.from_environment() if chat_enabled else None
        if os.environ.get("DOCUMENTATION_ENABLE_TEAMS") == "true":
            from .teams import create_teams_server

            return create_teams_server(agent, conversation=conversation)
        if conversation is not None:
            agent = ConversationRouter(agent, conversation)
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
