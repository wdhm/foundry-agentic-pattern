"""Client for the remote Visualization Agent, using bounded A2A 1.0 JSON-RPC calls."""

import asyncio
import json
from typing import Any, Literal, Protocol
from uuid import uuid4

import httpx
from pydantic import ValidationError

from contracts.visualization import VisualizationOutput, VisualizationRequest

from .visualization_settings import VisualizationSettings

MAX_RESPONSE_BYTES = 128000


class VisualizationClient(Protocol):
    async def review(self, request: VisualizationRequest) -> VisualizationOutput: ...


class FoundryVisualizationClient:
    def __init__(
        self, settings: VisualizationSettings, auth_mode: Literal["managed_identity", "azure_cli"],
    ) -> None:
        self.settings = settings
        self.auth_mode = auth_mode

    async def review(self, request: VisualizationRequest) -> VisualizationOutput:
        from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential

        credential = AzureCliCredential() if self.auth_mode == "azure_cli" else ManagedIdentityCredential()
        async with asyncio.timeout(self.settings.timeout_seconds), credential:
            token = await credential.get_token("https://ai.azure.com/.default")
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {token.token}", "A2A-Version": "1.0"},
                timeout=self.settings.timeout_seconds, follow_redirects=False,
            ) as client:
                return await self.exchange(client, request)

    async def _json(
        self, client: httpx.AsyncClient, method: str, url: str, body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with client.stream(method, url, json=body) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise ValueError("Visualization A2A response exceeds the size limit.")
        try:
            value = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Visualization A2A returned invalid JSON.") from None
        if not isinstance(value, dict):
            raise ValueError("Visualization A2A returned a non-object response.")
        return value

    async def exchange(self, client: httpx.AsyncClient, request: VisualizationRequest) -> VisualizationOutput:
        card = await self._json(client, "GET", self.settings.endpoint + "/agentCard/v1.0")
        if card.get("name") != self.settings.agent_name or card.get("version") != self.settings.card_version:
            raise ValueError("Visualization agent card does not match the reviewed name/version.")
        interfaces = card.get("supportedInterfaces", [])
        if not isinstance(interfaces, list) or not any(
            isinstance(item, dict) and item.get("protocolBinding") == "JSONRPC"
            and item.get("protocolVersion") == "1.0" and isinstance(item.get("url"), str)
            and httpx.URL(item["url"]) == httpx.URL(self.settings.endpoint)
            and not item.get("tenant")
            for item in interfaces
        ):
            raise ValueError("Visualization card must advertise A2A 1.0 JSONRPC at the configured endpoint.")
        skills = card.get("skills", [])
        if not isinstance(skills, list) or not any(
            isinstance(skill, dict) and skill.get("id") == "architecture-visualization" for skill in skills
        ):
            raise ValueError("Visualization card is missing the architecture-visualization skill.")
        rpc_id = str(uuid4())
        payload = {"input": request.model_dump(mode="json"), "input_sha256": request.input_sha256}
        response = await self._json(client, "POST", self.settings.endpoint, {
            "jsonrpc": "2.0", "id": rpc_id, "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": str(uuid4()), "role": "ROLE_USER",
                    "parts": [{"text": json.dumps(payload)}],
                },
                "configuration": {"returnImmediately": False, "historyLength": 0},
                "metadata": {
                    "request_id": str(request.request_id), "correlation_id": str(request.correlation_id),
                },
            },
        })
        if response.get("jsonrpc") != "2.0" or response.get("id") != rpc_id:
            raise ValueError("Visualization A2A response does not match the request.")
        if "error" in response:
            raise ValueError("Visualization A2A returned a protocol error; no diagram was accepted.")
        result = response.get("result")
        if not isinstance(result, dict) or ("task" in result) == ("message" in result):
            raise ValueError("Visualization A2A must return exactly one task or message.")
        if "task" in result:
            task = result["task"]
            if (
                not isinstance(task, dict) or not isinstance(task.get("status"), dict)
                or task["status"].get("state") != "TASK_STATE_COMPLETED"
            ):
                raise ValueError("Visualization A2A task did not complete; no automatic resubmission.")
            artifacts = task.get("artifacts")
            if not isinstance(artifacts, list) or len(artifacts) != 1 or not isinstance(artifacts[0], dict):
                raise ValueError("Visualization requires exactly one completed artifact.")
            parts = artifacts[0].get("parts")
        else:
            message = result["message"]
            if not isinstance(message, dict) or message.get("role") != "ROLE_AGENT":
                raise ValueError("Visualization requires an agent response.")
            parts = message.get("parts")
        if not isinstance(parts, list) or len(parts) != 1 or not isinstance(parts[0], dict):
            raise ValueError("Visualization requires exactly one JSON content part.")
        part = parts[0]
        if ("text" in part) == ("data" in part) or any(key in part for key in ("url", "raw")):
            raise ValueError("Visualization content must be JSON text or structured data, not a file.")
        try:
            if "text" in part:
                return VisualizationOutput.model_validate_json(part["text"])
            return VisualizationOutput.model_validate(part["data"])
        except (ValidationError, TypeError):
            raise ValueError("Visualization agent returned an invalid output contract.") from None
