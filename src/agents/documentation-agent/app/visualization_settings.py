from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from contracts.models import ContractModel, NonBlank


class VisualizationSettings(ContractModel):
    endpoint: NonBlank
    agent_name: NonBlank
    card_version: NonBlank
    guidelines_version: NonBlank
    target_page: NonBlank
    target_section: Literal["Architecture diagram"] = "Architecture diagram"
    timeout_seconds: int = Field(default=90, gt=0, le=180)

    @model_validator(mode="after")
    def valid_endpoint(self) -> Self:
        url = urlsplit(self.endpoint)
        if (
            url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.port not in (None, 443)
            or not url.path.endswith("/endpoint/protocols/a2a")
        ):
            raise ValueError("Visualization requires a reviewed HTTPS Foundry A2A endpoint on port 443.")
        return self
