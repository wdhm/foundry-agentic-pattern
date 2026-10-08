"""Outbound authentication: get a token for the Azure DevOps MCP server *as the agent's user account*.

Implements the Entra Agent ID agent-user flow, with no secrets:

  0. Managed identity token for ``api://AzureADTokenExchange`` (this server's user-assigned MI,
     registered as a federated identity credential on the agent identity blueprint).
  1. T1 = blueprint token (client_credentials, client_assertion = MI token, fmi_path = agent identity).
  2. T2 = agent identity token (client_credentials, client_assertion = T1).
  3. Resource token for the agent user (grant_type = user_fic, user_federated_identity_credential = T2).

See https://learn.microsoft.com/entra/agent-id/agent-user-oauth-flow
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import anyio
import httpx
from azure.identity import ManagedIdentityCredential

log = logging.getLogger("ado_mcp.token")

# Entra app behind https://mcp.dev.azure.com ("Azure DevOps MCP"); scopes such as wit.read, wiki.write.
AZURE_DEVOPS_MCP_RESOURCE = "2a72489c-aab2-4b65-b93a-a91edccf33b8"
TOKEN_EXCHANGE_SCOPE = "api://AzureADTokenExchange/.default"
JWT_BEARER = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


class AgentUserTokenProvider:
    def __init__(
        self,
        tenant_id: str,
        blueprint_client_id: str,
        agent_identity_client_id: str,
        agent_user_upn: str,
        managed_identity_client_id: str,
        resource: str = AZURE_DEVOPS_MCP_RESOURCE,
    ) -> None:
        self._token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        self._blueprint = blueprint_client_id
        self._agent_identity = agent_identity_client_id
        self._agent_user = agent_user_upn
        self._scope = f"{resource}/.default"
        self._mi = ManagedIdentityCredential(client_id=managed_identity_client_id)
        self._cached: tuple[str, float] | None = None
        self._lock = anyio.Lock()

    async def get_token(self) -> str:
        async with self._lock:
            if self._cached and self._cached[1] - 300 > time.time():
                return self._cached[0]
            token = await self._acquire()
            self._cached = (token, float(_claims(token)["exp"]))
            return token

    def invalidate(self) -> None:
        self._cached = None

    async def _acquire(self) -> str:
        mi_token = (await anyio.to_thread.run_sync(self._mi.get_token, TOKEN_EXCHANGE_SCOPE)).token
        async with httpx.AsyncClient(timeout=30) as http:
            t1 = await self._post(http, "T1 blueprint", {
                "client_id": self._blueprint,
                "scope": TOKEN_EXCHANGE_SCOPE,
                "grant_type": "client_credentials",
                "client_assertion_type": JWT_BEARER,
                "client_assertion": mi_token,
                "fmi_path": self._agent_identity,
            })
            t2 = await self._post(http, "T2 agent identity", {
                "client_id": self._agent_identity,
                "scope": TOKEN_EXCHANGE_SCOPE,
                "grant_type": "client_credentials",
                "client_assertion_type": JWT_BEARER,
                "client_assertion": t1,
            })
            t3 = await self._post(http, "T3 agent user", {
                "client_id": self._agent_identity,
                "scope": self._scope,
                "grant_type": "user_fic",
                "client_assertion_type": JWT_BEARER,
                "client_assertion": t1,
                "user_federated_identity_credential": t2,
                "username": self._agent_user,
                "requested_token_use": "on_behalf_of",
            })
        c = _claims(t3)
        log.info("acquired agent user token oid=%s idtyp=%s scp=%s", c.get("oid"), c.get("idtyp"), c.get("scp"))
        return t3

    async def _post(self, http: httpx.AsyncClient, step: str, form: dict[str, str]) -> str:
        r = await http.post(self._token_url, data=form)
        if r.status_code != 200:
            detail = r.json().get("error_description", r.text).splitlines()[0]
            raise RuntimeError(f"{step} token request failed: {detail}")
        return str(r.json()["access_token"])


def _claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    return dict(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))))
