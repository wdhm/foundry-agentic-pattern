"""Runtime settings, read from environment variables (no secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    # Inbound: the Entra app registration that represents this MCP server (the token audience).
    mcp_app_client_id: str
    mcp_required_role: str
    # Outbound: the agent identity chain (blueprint -> agent identity -> agent user).
    agent_blueprint_client_id: str
    agent_identity_client_id: str
    agent_user_upn: str
    managed_identity_client_id: str
    # Upstream: the Microsoft-hosted remote Azure DevOps MCP server and the tool restrictions we enforce.
    ado_org: str
    ado_mcp_toolsets: str
    ado_mcp_readonly: bool

    @property
    def upstream_url(self) -> str:
        return f"https://mcp.dev.azure.com/{self.ado_org}"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            tenant_id=_env("AZURE_TENANT_ID"),
            mcp_app_client_id=_env("MCP_APP_CLIENT_ID"),
            mcp_required_role=_env("MCP_REQUIRED_ROLE", "Mcp.Tools.ReadWrite.All"),
            agent_blueprint_client_id=_env("AGENT_BLUEPRINT_CLIENT_ID"),
            agent_identity_client_id=_env("AGENT_IDENTITY_CLIENT_ID"),
            agent_user_upn=_env("AGENT_USER_UPN"),
            managed_identity_client_id=_env("MANAGED_IDENTITY_CLIENT_ID"),
            ado_org=_env("ADO_ORG"),
            ado_mcp_toolsets=_env("ADO_MCP_TOOLSETS", "wit,wiki"),
            ado_mcp_readonly=_env("ADO_MCP_READONLY", "false").lower() == "true",
        )
