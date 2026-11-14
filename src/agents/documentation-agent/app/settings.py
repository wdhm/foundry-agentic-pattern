import os
from collections.abc import Mapping
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from contracts.models import ContractModel, NonBlank

from .visualization_settings import VisualizationSettings


class AssessmentSettings(ContractModel):
    project_endpoint: NonBlank
    toolbox_endpoint: NonBlank
    model: NonBlank
    model_version: NonBlank
    ado_project: NonBlank
    ado_wiki: NonBlank
    ado_organization: NonBlank | None = None
    model_gateway_endpoint: NonBlank | None = None
    toolbox_gateway_endpoint: NonBlank | None = None
    auth_mode: Literal["managed_identity", "azure_cli"] = "managed_identity"
    timeout_seconds: int = Field(default=180, gt=0, le=600)
    visualization: VisualizationSettings | None = None

    @model_validator(mode="after")
    def valid_endpoints(self) -> Self:
        for value in (self.project_endpoint, self.toolbox_endpoint):
            url = urlsplit(value)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
                raise ValueError("Project and toolbox endpoints must be HTTPS URLs without credentials or fragments.")
        for gateway_endpoint in (self.model_gateway_endpoint, self.toolbox_gateway_endpoint):
            if gateway_endpoint is None:
                continue
            url = urlsplit(gateway_endpoint)
            if (
                url.scheme != "https" or not url.hostname or url.username or url.password
                or url.fragment or url.port not in (None, 443)
            ):
                raise ValueError("Gateway endpoints must be HTTPS URLs without credentials or fragments, on port 443.")
        if self.model_gateway_endpoint is not None:
            url = urlsplit(self.model_gateway_endpoint)
            if url.query or not url.path.endswith("/documentation-model/"):
                raise ValueError("Model gateway endpoint must end in /documentation-model/ without a query.")
        if self.toolbox_gateway_endpoint is not None:
            url = urlsplit(self.toolbox_gateway_endpoint)
            if not url.path.endswith("/documentation-tools/mcp") or url.query != "api-version=v1":
                raise ValueError("Toolbox gateway endpoint must end in /documentation-tools/mcp?api-version=v1.")
        return self

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> Self:
        values = os.environ if environ is None else environ
        names = {
            "project_endpoint": "DOCUMENTATION_PROJECT_ENDPOINT",
            "toolbox_endpoint": "TOOLBOX_ENDPOINT",
            "model": "AZURE_AI_MODEL_DEPLOYMENT_NAME",
            "model_version": "DOCUMENTATION_MODEL_VERSION",
            "ado_project": "DOCUMENTATION_ADO_PROJECT",
            "ado_wiki": "DOCUMENTATION_ADO_WIKI",
            "ado_organization": "DOCUMENTATION_ADO_ORGANIZATION",
            "model_gateway_endpoint": "DOCUMENTATION_MODEL_GATEWAY_ENDPOINT",
            "toolbox_gateway_endpoint": "DOCUMENTATION_TOOLBOX_GATEWAY_ENDPOINT",
            "auth_mode": "DOCUMENTATION_AUTH_MODE",
        }
        settings = cls.model_validate({field: values[env] for field, env in names.items() if env in values})
        enabled = values.get("DOCUMENTATION_ENABLE_VISUALIZATION", "false")
        if enabled not in {"true", "false"}:
            raise ValueError("DOCUMENTATION_ENABLE_VISUALIZATION must be true or false.")
        if enabled == "true":
            settings.visualization = VisualizationSettings.model_validate({
                field: values[env]
                for field, env in {
                    "endpoint": "DOCUMENTATION_VISUALIZATION_ENDPOINT",
                    "agent_name": "DOCUMENTATION_VISUALIZATION_AGENT_NAME",
                    "card_version": "DOCUMENTATION_VISUALIZATION_CARD_VERSION",
                    "guidelines_version": "DOCUMENTATION_VISUALIZATION_GUIDELINES_VERSION",
                    "target_page": "DOCUMENTATION_VISUALIZATION_TARGET_PAGE",
                }.items()
                if env in values
            })
        return settings
