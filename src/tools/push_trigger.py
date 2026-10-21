"""Azure Pipeline caller: fixed version, federated Azure CLI auth, no approval."""

import argparse
import json
import re
import subprocess
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

from contracts.repositories import azure_repository


class FoundryPushClient:
    def __init__(self, endpoint: str, agent: str) -> None:
        url = urlsplit(endpoint)
        if not re.fullmatch(
            r"https://[a-z0-9-]+\.services\.ai\.azure\.com/api/projects/[A-Za-z0-9_-]+", endpoint
        ) or url.query or url.fragment:
            raise ValueError("Use the reviewed public-cloud Foundry project endpoint.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", agent):
            raise ValueError("Invalid agent name.")
        self.base = endpoint + "/agents/" + agent

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        # AzureCLI@2 establishes the federated workload login. Tokens stay in memory.
        token = subprocess.check_output([
            "az", "account", "get-access-token", "--resource", "https://ai.azure.com",
            "--query", "accessToken", "-o", "tsv",
        ], text=True).strip()
        if not token:
            raise ValueError("Federated Azure CLI token acquisition returned no token.")
        data = json.dumps(body).encode() if body is not None else None
        request = Request(
            self.base + path, data=data, method=method,
            headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
                "Foundry-Features": "HostedAgents=V1Preview",
            },
        )
        try:
            with urlopen(request, timeout=600) as response:
                content = response.read()
                result = json.loads(content) if content else {}
        except HTTPError as exc:
            # Do not echo tokens or upstream source-bearing error bodies.
            raise RuntimeError(
                f"Foundry request returned HTTP {exc.code}; inspect the retained event/session."
            ) from None
        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object from Foundry.")
        return result


def send_push(client: FoundryPushClient, version: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not re.fullmatch(r"[1-9][0-9]*", version):
        raise ValueError("Push automation requires a concrete deployment version.")
    session = client.request("POST", "/endpoint/sessions?api-version=v1", {
        "version_indicator": {"type": "version_ref", "agent_version": version},
    })
    session_id = session.get("agent_session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Missing created session ID.")
    path = "/endpoint/sessions/" + quote(session_id, safe="")
    print(json.dumps({"session_id": session_id, "candidate_version": version}), flush=True)
    try:
        deadline = time.monotonic() + 180
        while True:
            session = client.request("GET", path + "?api-version=v1")
            if session.get("agent_session_id") != session_id or session.get("version_indicator") != {
                "type": "version_ref", "agent_version": version,
            }:
                raise ValueError("GET-confirmed session binding differs from the configured version.")
            if session.get("status") in {"active", "idle"}:
                break
            if session.get("status") not in {"creating", "updating"} or time.monotonic() >= deadline:
                raise ValueError("Push session did not become ready.")
            time.sleep(3)
        result = client.request(
            "POST", "/endpoint/protocols/invocations?api-version=v1&agent_session_id=" + quote(session_id, safe=""),
            payload,
        )
        if payload.get("action") == "preflight":
            if result != {"state": "caller_verified", "assessment_run": False}:
                raise ValueError("Workload authentication preflight did not pass.")
            return result
        if result.get("state") not in {"notified", "opened"} or not isinstance(result.get("duplicate"), bool):
            raise ValueError("Push flow did not confirm notification or an already-opened review.")
        UUID(result["event_id"])
        return result
    finally:
        # This stops only our pipeline-owned compute, never the Teams conversation.
        client.request("POST", path + ":stop?api-version=v1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--agent", default="documentation-agent")
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--pipeline-id", required=True, type=int)
    parser.add_argument("--build-id", required=True, type=int)
    parser.add_argument("--preflight", action="store_true", help="Verify workload identity without assessment/notification")
    args = parser.parse_args()
    repo = azure_repository(args.repository)
    UUID(repo.repository)
    if args.branch != "refs/heads/main" or not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        parser.error("Only an exact main-branch commit is supported.")
    if args.pipeline_id <= 0 or args.build_id <= 0:
        parser.error("Pipeline/build IDs must be positive.")
    payload: dict[str, Any] = {
        "interface_version": "1.0.0", "repository_url": args.repository, "branch": args.branch,
        "pipeline_id": args.pipeline_id, "build_id": args.build_id, "commit_sha": args.commit,
    }
    if args.preflight:
        payload = {"interface_version": "1.0.0", "action": "preflight"}
    result = send_push(FoundryPushClient(args.endpoint, args.agent), args.version, payload)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
