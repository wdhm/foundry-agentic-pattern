"""Inbound authentication: only the configured Foundry agent identity may call this server.

Foundry Agent Service sends an Entra access token for the connection's audience, issued to the
agent identity (project connection authType ``AgenticIdentityToken``).
"""

from __future__ import annotations

import logging
from typing import Any

import anyio
import jwt
from jwt import PyJWKClient

from .asgi import ASGIApp, Receive, Scope, Send, respond_json

log = logging.getLogger("ado_mcp.auth")

PUBLIC_PATHS = {"/healthz"}


class AuthError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class TokenValidator:
    def __init__(self, tenant_id: str, audience_client_id: str, required_role: str, allowed_caller_id: str) -> None:
        self._issuers = [
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            f"https://sts.windows.net/{tenant_id}/",
        ]
        self._audiences = [audience_client_id, f"api://{audience_client_id}"]
        self._required_role = required_role
        self._allowed_caller_id = allowed_caller_id
        self._jwks = PyJWKClient(f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys")

    def validate(self, token: str) -> dict[str, Any]:
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audiences,
                issuer=self._issuers,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(401, f"invalid token: {exc}") from exc
        if self._required_role not in claims.get("roles", []):
            raise AuthError(403, f"token lacks app role {self._required_role}")
        caller = claims.get("azp") or claims.get("appid")
        if caller != self._allowed_caller_id:
            raise AuthError(403, f"caller {caller} is not the allowed agent identity")
        return claims


class BearerAuthMiddleware:
    """Pure ASGI middleware so it does not interfere with MCP streaming responses."""

    def __init__(self, app: ASGIApp, validator: TokenValidator) -> None:
        self._app = app
        self._validator = validator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        if scope["path"] in PUBLIC_PATHS:
            await respond_json(send, 200, {"status": "ok"})
            return
        auth = dict(scope["headers"]).get(b"authorization", b"").decode()
        if not auth.lower().startswith("bearer "):
            await respond_json(send, 401, {"error": "missing bearer token"}, challenge=True)
            return
        try:
            claims = await anyio.to_thread.run_sync(self._validator.validate, auth[7:])
        except AuthError as exc:
            log.warning("rejected call: %s", exc)
            await respond_json(send, exc.status, {"error": str(exc)}, challenge=exc.status == 401)
            return
        log.info("authorized caller oid=%s azp=%s", claims.get("oid"), claims.get("azp") or claims.get("appid"))
        await self._app(scope, receive, send)
