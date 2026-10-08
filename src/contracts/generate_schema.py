import argparse
import json
from pathlib import Path

from .models import AgentRequest, AgentResult


def generate_schemas(output_dir: Path, *, check: bool = False) -> bool:
    schemas_match = True
    for model in (AgentRequest, AgentResult):
        path = output_dir / f"{model.__name__}.schema.json"
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        content = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                print(f"Schema missing or out of date: {path}")
                schemas_match = False
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            print(f"Generated: {path}")
    return schemas_match


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JSON Schema from the Pydantic contract models.")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "schema")
    parser.add_argument("--check", action="store_true", help="Fail on schema drift without writing files.")
    args = parser.parse_args()
    if not generate_schemas(args.output_dir, check=args.check):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
