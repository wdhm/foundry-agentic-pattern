import logging
import os

from agent_framework_foundry_hosting import ResponsesHostServer

from .agent import DocumentationAgent


def create_server() -> ResponsesHostServer:
    return ResponsesHostServer(DocumentationAgent(), history_source="agent")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    create_server().run(host=os.environ.get("HOST", "127.0.0.1"))


if __name__ == "__main__":
    main()
