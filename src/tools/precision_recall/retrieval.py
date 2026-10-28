"""Deterministic local retrieval across every declared repository, with exact line maps."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .models import Category, Quote


@dataclass
class Evidence:
    text: str
    lines: dict[tuple[str, int], str]
    files: list[str]
    truncated: bool


def identifiers(text: str) -> list[str]:
    tokens = re.findall(r'`([^`]+)`|"([^"]+)"|\'([^\']+)\'|(\b[A-Z][A-Z0-9_]{2,}\b)|(\b\d[\d */:.-]*)', text)
    return sorted({part.strip() for token in tokens for part in token if part.strip()})


def retrieve(
    text: str, category: Category, files: dict[str, str], touched: list[str], diff: str,
    max_bytes: int = 24000,
) -> Evidence:
    tokens = identifiers(text)
    hits: list[tuple[int, str, int]] = []
    for name, content in sorted(files.items()):
        path = name.split(":", 1)[-1]
        implied = (
            category in {"config", "infra", "auth", "error_handling"}
            and (PurePosixPath(path).match("appsettings*.json")
                 or path.endswith((".bicep", ".tf", ".tfvars", ".yaml", ".yml", "settings.json")))
        )
        for line, value in enumerate(content.splitlines(), 1):
            if any(token in value for token in tokens):
                hits.append((0, name, line))
        if implied:
            hits.append((1, name, 1))
    if not any(rank == 0 for rank, _, _ in hits):
        hits.extend((2, name, 1) for name in sorted(touched) if name in files)
    ranges: dict[str, list[tuple[int, int]]] = {}
    for _, name, line in sorted(hits):
        length = len(files[name].splitlines())
        start, end = max(1, line - 20), min(length, line + 20)
        ranges.setdefault(name, []).append((start, end))
    parts, line_map, included = [], {}, []
    size, truncated = 0, False
    for name, spans in ranges.items():
        lines = files[name].splitlines()
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        for start, end in merged:
            part = f"=== {name} (lines {start}-{end}) ===\n" + "\n".join(
                f"{i}: {lines[i - 1]}" for i in range(start, end + 1)
            )
            if size + len(part.encode()) > max_bytes:
                truncated = True
                continue
            parts.append(part)
            size += len(part.encode())
            included.append(name)
            line_map.update({(name, i): lines[i - 1] for i in range(start, end + 1)})
    if not any(rank == 0 for rank, _, _ in hits) and diff:
        part = "=== pinned merge diff (context only; cite source file lines) ===\n" + diff
        if size + len(part.encode()) <= max_bytes:
            parts.append(part)
        else:
            truncated = True
    return Evidence("\n\n".join(parts), line_map, sorted(set(included)), truncated)


def citations_ok(quotes: list[Quote], evidence: Evidence, *, allow_empty: bool) -> bool:
    return (bool(quotes) or allow_empty) and all(
        evidence.lines.get((q.file, q.line)) == q.text for q in quotes
    )
