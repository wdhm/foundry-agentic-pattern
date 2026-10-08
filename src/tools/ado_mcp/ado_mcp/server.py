"""Entry point: agent-identity gateway in front of the remote Azure DevOps MCP server.

Foundry agent --(agent identity token)--> this server --(agent user token)--> mcp.dev.azure.com

Run locally: ``uvicorn ado_mcp.server:app --host 0.0.0.0 --port 8000``. The MCP endpoint is ``/mcp``.
"""

from __future__ import annotations

import logging

from .agent_user_token import AgentUserTokenProvider
from .inbound_auth import BearerAuthMiddleware, TokenValidator
from .proxy import AdoMcpProxy
from .settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = Settings.from_env()

app = BearerAuthMiddleware(
    AdoMcpProxy(
        upstream_url=settings.upstream_url,
        tokens=AgentUserTokenProvider(
            tenant_id=settings.tenant_id,
            blueprint_client_id=settings.agent_blueprint_client_id,
            agent_identity_client_id=settings.agent_identity_client_id,
            agent_user_upn=settings.agent_user_upn,
            managed_identity_client_id=settings.managed_identity_client_id,
        ),
        toolsets=settings.ado_mcp_toolsets,
        readonly=settings.ado_mcp_readonly,
    ),
    TokenValidator(
        tenant_id=settings.tenant_id,
        audience_client_id=settings.mcp_app_client_id,
        required_role=settings.mcp_required_role,
        allowed_caller_id=settings.agent_identity_client_id,
    ),
)
