"""Bounded GET-only JSON transport shared by the two isolated source readers."""

import json
from collections.abc import Container
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 200_000


class SandboxError(ValueError):
    """Fixed local diagnostic text, safe to show without upstream payloads."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class JsonGet:
    def __init__(
        self, token: str, allowed: Container[str], requests: int, max_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        self.token, self.allowed, self.remaining, self.max_bytes = token, allowed, requests, max_bytes
        self.opener = build_opener(NoRedirect())

    def get(self, uri: str) -> tuple[dict[str, Any], dict[str, str]]:
        if uri not in self.allowed or self.remaining <= 0:
            raise SandboxError("Read exceeds the approved source boundary or request budget.")
        self.remaining -= 1
        request = Request(uri, headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read(self.max_bytes + 1)
                if len(body) > self.max_bytes:
                    raise SandboxError("Source response exceeds the capture limit.")
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise SandboxError("Source response must be a JSON object.")
                return payload, {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as exc:
            raise SandboxError(f"Azure DevOps GET failed (HTTP {exc.code}); capture stopped.") from None
        except (URLError, TimeoutError, UnicodeError, json.JSONDecodeError):
            raise SandboxError("Azure DevOps GET transport or JSON decoding failed; capture stopped.") from None
