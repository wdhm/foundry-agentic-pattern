"""Build a local Foundry prompt-agent definition; never contacts or changes Azure."""

import argparse
import json
from pathlib import Path
from typing import Any

from contracts.visualization import VisualizationOutput

ROOT = Path(__file__).parent


def definition(model: str) -> dict[str, Any]:
    if not model.strip():
        raise ValueError("An explicit model deployment name is required.")
    return {
        "kind": "prompt",
        "model": model,
        "instructions": (
            (ROOT / "instructions.txt").read_text(encoding="utf-8").strip() + "\n\n"
            + (ROOT / "guidelines.txt").read_text(encoding="utf-8").strip()
        ),
        "tools": [],
        "text": {"format": {
            "type": "json_schema", "name": "architecture_visualization_v1",
            "strict": True, "schema": VisualizationOutput.model_json_schema(),
        }},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Model deployment name for the future prompt agent.")
    args = parser.parse_args()
    print(json.dumps(definition(args.model), indent=2))


if __name__ == "__main__":
    main()
