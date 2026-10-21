"""Opt-in routing of the existing Foundry model client; identity stays end-to-end."""

from agent_framework.foundry import FoundryChatClient

from .settings import AssessmentSettings


def route_model_client(client: FoundryChatClient, settings: AssessmentSettings) -> None:
    if settings.model_gateway_endpoint is not None:
        # OpenAI's public URL setter retains the SDK's renewable Foundry token provider.
        client.client.base_url = settings.model_gateway_endpoint
        client.client.max_retries = 0
