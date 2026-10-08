"""Pass-through to the Microsoft-hosted remote Azure DevOps MCP server.

The caller (already authenticated as the Foundry agent identity) gets its MCP traffic forwarded
to ``https://mcp.dev.azure.com/{org}`` with:

- ``Authorization`` replaced by a token for the agent's *user account* (Azure DevOps does not
  accept agent identity service principals, but does accept the agent user).
- ``X-MCP-*`` tool restriction headers set by this server, never by the caller.

See https://learn.microsoft.com/azure/devops/mcp-server/remote-mcp-server
"""

from __future__ import annotations

import json
import logging

import httpx

from .agent_user_token import AgentUserTokenProvider
from .asgi import Receive, Scope, Send, respond_json

log = logging.getLogger("ado_mcp.proxy")

MCP_PATH = "/mcp"
# Only MCP transport headers are forwarded. Anything else (x-forwarded-*, x-envoy-*, tracing, the
# caller's Authorization or X-MCP-* restrictions) is dropped; the upstream rejects requests with
# ingress headers and this server alone decides identity and tool restrictions.
_FORWARD_REQUEST = {b"content-type", b"accept", b"mcp-session-id", b"mcp-protocol-version", b"last-event-id"}
_DROP_RESPONSE = {b"content-length", b"transfer-encoding", b"connection", b"keep-alive", b"content-encoding"}


class AdoMcpProxy:
    def __init__(self, upstream_url: str, tokens: AgentUserTokenProvider, toolsets: str, readonly: bool) -> None:
        self._upstream = upstream_url
        self._tokens = tokens
        self._enforced = {"X-MCP-Toolsets": toolsets}
        if readonly:
            self._enforced["X-MCP-Readonly"] = "true"
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30, read=300))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope["type"] != "http" or scope["path"].rstrip("/") != MCP_PATH:
            await respond_json(send, 404, {"error": "not found"})
            return

        body = await _read_body(receive)
        _audit(scope["method"], body)
        headers = {k.decode(): v.decode() for k, v in scope["headers"] if k.lower() in _FORWARD_REQUEST}
        headers.update(self._enforced)

        try:
            token = await self._tokens.get_token()
        except Exception:
            log.exception("could not get agent user token")
            await respond_json(send, 502, {"error": "upstream authentication failed"})
            return
        headers["Authorization"] = f"Bearer {token}"

        upstream = self._http.build_request(scope["method"], self._upstream, headers=headers, content=body)
        try:
            resp = await self._http.send(upstream, stream=True)
        except httpx.HTTPError as exc:
            log.error("upstream unreachable: %s", exc)
            await respond_json(send, 502, {"error": "upstream MCP server unreachable"})
            return
        try:
            if resp.status_code == 401:
                self._tokens.invalidate()
                log.warning("upstream rejected agent user token: %s", resp.headers.get("www-authenticate"))
            out_headers = [
                (k.encode(), v.encode()) for k, v in resp.headers.items() if k.lower().encode() not in _DROP_RESPONSE
            ]
            await send({"type": "http.response.start", "status": resp.status_code, "headers": out_headers})
            async for chunk in resp.aiter_bytes():
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b""})
        finally:
            await resp.aclose()

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await self._http.aclose()
                await send({"type": "lifespan.shutdown.complete"})
                return


async def _read_body(receive: Receive) -> bytes:
    chunks = []
    while True:
        message = await receive()
        chunks.append(message.get("body", b""))
        if not message.get("more_body"):
            return b"".join(chunks)


def _audit(method: str, body: bytes) -> None:
    """Log which MCP method/tool the agent called, without logging arguments or content."""
    if not body:
        log.info("mcp %s (no body)", method)
        return
    try:
        msg = json.loads(body)
    except ValueError:
        log.info("mcp %s (non-JSON body)", method)
        return
    for m in msg if isinstance(msg, list) else [msg]:
        tool = (m.get("params") or {}).get("name") if m.get("method") == "tools/call" else None
        log.info("mcp %s rpc=%s%s", method, m.get("method", "response"), f" tool={tool}" if tool else "")
