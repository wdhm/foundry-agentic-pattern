"""Opt-in routing of the existing Foundry model client; identity stays end-to-end."""

from typing import TypeVar

from agent_framework.foundry import FoundryChatClient
from agent_framework.openai import OpenAIChatOptions
from pydantic import BaseModel

from .settings import AssessmentSettings

ResponseT = TypeVar("ResponseT", bound=BaseModel | None)


def route_model_client(
    client: FoundryChatClient[OpenAIChatOptions[ResponseT]], settings: AssessmentSettings
) -> None:
    if settings.model_gateway_endpoint is not None:
        # OpenAI's public URL setter retains the SDK's renewable Foundry token provider.
        client.client.base_url = settings.model_gateway_endpoint
        client.client.max_retries = 0
