import os
from collections.abc import Mapping
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from contracts.models import ContractModel, NonBlank


class AssessmentSettings(ContractModel):
    project_endpoint: NonBlank
    toolbox_endpoint: NonBlank
    model: NonBlank
    model_version: NonBlank
    ado_project: NonBlank
    ado_wiki: NonBlank
    ado_organization: NonBlank | None = None
    auth_mode: Literal["managed_identity", "azure_cli"] = "managed_identity"
    timeout_seconds: int = Field(default=180, gt=0, le=600)

    @model_validator(mode="after")
    def valid_endpoints(self) -> Self:
        for value in (self.project_endpoint, self.toolbox_endpoint):
            url = urlsplit(value)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
                raise ValueError("Project and toolbox endpoints must be HTTPS URLs without credentials or fragments.")
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
            "auth_mode": "DOCUMENTATION_AUTH_MODE",
        }
        return cls.model_validate({field: values[env] for field, env in names.items() if env in values})
