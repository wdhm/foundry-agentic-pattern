"""Dataset-v1 adapters. Editorial answers never become agent input."""

import hashlib
import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from contracts.evidence import source_records, trace_evidence_problems
from contracts.v1 import AgentRequest, AgentResult


def blob_id(text: str) -> str:
    data = text.encode()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def load_cases(suite_path: Path, root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    if suite["dataset_version"] != "1.0.0" or suite["contract_version"] != "1.0.0":
        raise ValueError("Unsupported dataset/contract version.")
    if len(suite["cases"]) != 5 or len({case["id"] for case in suite["cases"]}) != 5:
        raise ValueError("The reviewed MVP suite requires five unique cases.")
    standard = suite["documentation_standard"]
    rules = (root / standard["path"]).read_text(encoding="utf-8")
    if blob_id(rules) != standard["git_blob_sha"]:
        raise ValueError("Documentation standard has drifted from the pinned dataset.")
    sources = {}
    for source in suite["sources"]:
        text = (suite_path.parent / source["snapshot"]).read_text(encoding="utf-8")
        if source["source"] == "wiki":
            snapshot = json.loads(text)
            if snapshot["etag"] != source["version"]:
                raise ValueError("Wiki snapshot version mismatch.")
            content = snapshot["content"]
        elif source["source"] == "work_item":
            snapshot = json.loads(text)
            if str(snapshot["rev"]) != source["version"]:
                raise ValueError("Work-item snapshot revision mismatch.")
            content = "\n".join(
                str(snapshot["fields"].get(key, ""))
                for key in ("System.Title", "System.Description", "Microsoft.VSTS.Common.AcceptanceCriteria")
            )
        elif source["source"] == "git":
            content = text
        else:
            raise ValueError("Unknown source type.")
        if source["git_blob_sha"] and blob_id(content) != source["git_blob_sha"]:
            raise ValueError(f"Source snapshot drift: {source['id']}.")
        sources[source["id"]] = {
            "source": source["source"],
            "uri": source["uri"],
            "version": source["version"],
            "content": content,
        }
    prepared = []
    for case in suite["cases"]:
        if case["input_mode"] not in {"live_sources", "supplied_sources"}:
            raise ValueError("Unsupported input mode.")
        request = AgentRequest.model_validate(case["request"]).model_copy(
            update={"request_id": uuid4(), "correlation_id": uuid4()}
        )
        scenario = json.loads((suite_path.parent / case["scenario_file"]).read_text(encoding="utf-8"))
        allowed = [sources[source_id] for source_id in case["source_ids"]]
        payload = {
            "prompt": scenario["prompt"],
            "request": request.model_dump(mode="json"),
            "documentation_rules": rules,
            "source_allowlist": [
                {key: value for key, value in source.items() if key != "content"} for source in allowed
            ],
        }
        if case["input_mode"] == "supplied_sources":
            payload["sources"] = allowed
            payload["source_policy"] = (
                "Use only these supplied sources. Tools are disabled; other sources are unavailable."
            )
        else:
            payload["source_policy"] = (
                "Read only the allowlisted sources at their pinned versions and the documentation standard. "
                "Assess only; never write or publish. References outside this allowlist are unavailable."
            )
        prepared.append(
            {
                "id": case["id"],
                "mode": case["input_mode"],
                "request": request,
                "sources": allowed,
                "input": json.dumps(payload),
                "expected_status": scenario["expected_status"],
            }
        )
    return suite, prepared


def normalized(text: str) -> str:
    return " ".join(html.unescape(text).split())


def verify_sources(case: dict[str, Any], raw: dict[str, Any], result: AgentResult) -> None:
    allowed = case["sources"]
    if case["mode"] == "live_sources":
        problems = trace_evidence_problems(raw, result.model_dump(mode="json"))
        if problems:
            raise ValueError("Live evidence verification: " + "; ".join(problems))
        observed = source_records(raw)
        for item in raw.get("output", []):
            if item.get("type") == "mcp_call" and (item.get("server_label"), item.get("name")) == ("ado", "wiki"):
                payload, _ = json.JSONDecoder().raw_decode(item["output"].lstrip())
                page = payload.get("page", {})
                for source in allowed:
                    path = parse_qs(urlparse(source["uri"]).query).get("path", [None])[0]
                    if source["source"] == "wiki" and path and page.get("path") == path:
                        for record in observed:
                            if record["source"] == "wiki" and page.get("url") in record["uris"]:
                                record["uris"].append(source["uri"])
        for record in observed:
            if not any(
                record["source"] == source["source"]
                and record["version"] == source["version"]
                and source["uri"] in record["uris"]
                and normalized(record["content"]) == normalized(source["content"])
                for source in allowed
            ):
                raise ValueError("Live evidence drift or source outside case allowlist.")
        if not all(
            any(
                record["source"] == source["source"]
                and record["version"] == source["version"]
                and source["uri"] in record["uris"]
                for record in observed
            )
            for source in allowed
        ):
            raise ValueError("Not every pinned live source was read.")
    elif any(item.get("type", "").startswith("mcp_") for item in raw.get("output", [])):
        raise ValueError("Supplied-source response unexpectedly used or discovered tools.")
    for evidence in result.evidence:
        if not any(
            evidence.source == source["source"]
            and evidence.version == source["version"]
            and (
                evidence.uri == source["uri"]
                or (
                    case["mode"] == "live_sources"
                    and any(source["uri"] in record["uris"] and evidence.uri in record["uris"] for record in observed)
                )
            )
            and normalized(evidence.excerpt) in normalized(source["content"])
            for source in allowed
        ):
            raise ValueError("Evidence URI/version/excerpt is not grounded in this case's sources.")
    if result.documentation_status != case["expected_status"]:
        raise ValueError("Documentation status does not match the unchanged case expectation.")


def evaluator_item(case: dict[str, Any], raw: dict[str, Any], result: AgentResult, instructions: str) -> dict[str, Any]:
    calls = []
    definitions: dict[str, dict[str, Any]] = {}
    conversation: list[dict[str, Any]] = []
    for item in raw["output"]:
        if item["type"] == "mcp_list_tools":
            for tool in item.get("tools", []):
                name = item["server_label"] + "." + tool["name"]
                definition = {
                    "type": "function",
                    "name": name,
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                }
                if name in definitions and definitions[name] != definition:
                    raise ValueError("Conflicting discovered tool definitions.")
                definitions[name] = definition
        elif item["type"] == "mcp_call":
            call = {
                "type": "tool_call",
                "tool_call_id": item["id"],
                "name": item["server_label"] + "." + item["name"],
                "arguments": json.loads(item["arguments"]),
            }
            calls.append(call)
            conversation.extend(
                [
                    {"role": "assistant", "content": [call]},
                    {
                        "role": "tool",
                        "tool_call_id": item["id"],
                        "content": [{"type": "tool_result", "tool_result": item["output"]}],
                    },
                ]
            )
    conversation.append({"role": "assistant", "content": [{"type": "text", "text": result.model_dump_json()}]})
    if case["mode"] == "live_sources" and (not calls or not definitions):
        raise ValueError("Live tool-call scoring requires actual calls and discovered tool schemas.")
    return {
        "case_id": case["id"],
        "query": [{"role": "system", "content": instructions}, {"role": "user", "content": case["input"]}],
        "response": conversation,
        "context": json.dumps(case["sources"]),
        "tool_calls": calls,
        "tool_definitions": list(definitions.values()),
    }
