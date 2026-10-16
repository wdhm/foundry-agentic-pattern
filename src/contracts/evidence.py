"""Match assessment evidence to observed read-tool outputs, not model assertions."""

import html
import json
import re
from typing import Any


def source_records(raw: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for call in raw.get("output", []):
        if call.get("type") != "mcp_call" or call.get("status") != "completed" or call.get("error"):
            continue
        tool = (call.get("server_label"), call.get("name"))
        if tool not in {("github", "get_file_contents"), ("ado", "wiki"), ("ado", "wit_work_item")}:
            continue
        args = json.loads(call["arguments"])
        # Directory listings may be followed by a duplicate structuredResponse.
        payload, _ = json.JSONDecoder().raw_decode(call["output"].lstrip())
        if not isinstance(payload, dict):
            continue
        if tool == ("github", "get_file_contents"):
            version = args.get("sha", args.get("ref", ""))
            if not re.fullmatch(r"[a-fA-F0-9]{40}", version):
                continue
            for doc in payload.get("documents", []):
                records.append(
                    {
                        "source": "git",
                        "version": version,
                        "uris": [f"https://github.com/{args['owner']}/{args['repo']}/blob/{version}/{args['path']}"],
                        "content": doc["content"],
                    }
                )
        elif tool == ("ado", "wiki") and args.get("action") == "get_page":
            page = payload.get("page", {})
            etags = payload.get("eTag", [])
            if isinstance(etags, str):
                etags = [etags]
            for etag in etags:
                records.append(
                    {
                        "source": "wiki",
                        "version": etag.strip('"'),
                        "uris": [page.get("url", ""), page.get("remoteUrl", "")],
                        "content": page.get("content", ""),
                    }
                )
        elif tool == ("ado", "wit_work_item") and args.get("action") == "get":
            fields = payload.get("fields", {})
            api_url = payload.get("url", "")
            html_url = re.sub(r"/_apis/wit/workItems/([0-9]+)$", r"/_workitems/edit/\1", api_url)
            records.append(
                {
                    "source": "work_item",
                    "version": str(payload.get("rev", "")),
                    "uris": [api_url, html_url, payload.get("_links", {}).get("html", {}).get("href", "")],
                    "content": "\n".join(
                        str(fields.get(key, ""))
                        for key in ("System.Title", "System.Description", "Microsoft.VSTS.Common.AcceptanceCriteria")
                    ),
                }
            )
    return records


def trace_evidence_problems(raw: dict[str, Any], result: dict[str, Any]) -> list[str]:
    records = source_records(raw)
    problems = []
    calls = [item for item in raw.get("output", []) if item.get("type") == "mcp_call"]
    if not any(
        item.get("server_label") == "knowledge"
        and item.get("name") == "knowledge_base_retrieve"
        and item.get("status") == "completed"
        and not item.get("error")
        for item in calls
    ):
        problems.append("the documentation standard was not retrieved through Foundry IQ")
    for call in calls:
        if call.get("name") == "wiki_upsert_page":
            problems.append("assessment trace contains a wiki write call")
        if call.get("server_label") == "ado":
            action = json.loads(call["arguments"]).get("action", "")
            if action in {"create", "update", "delete", "create_page", "update_page", "delete_page"}:
                problems.append(f"assessment trace contains an ADO write action: {action}")
    for item in result.get("evidence", []):
        matches = [
            record
            for record in records
            if record["source"] == item["source"]
            and record["version"] == item["version"].strip('"')
            and item["uri"] in record["uris"]
        ]
        if not matches:
            problems.append(f"evidence {item['id']} URI/version does not match an actual source read")
        elif not any(
            " ".join(item["excerpt"].split()) in " ".join(html.unescape(record["content"]).split())
            for record in matches
        ):
            problems.append(f"evidence {item['id']} excerpt is not a verbatim passage from the source read")
    return problems
