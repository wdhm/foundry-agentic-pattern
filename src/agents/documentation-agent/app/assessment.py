import asyncio
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from agent_framework import AgentRunInputs
from agent_framework.exceptions import AgentInvalidRequestException
from pydantic import ValidationError

from contracts.evaluation import EvaluationResponse, ExecutionRecord
from contracts.evidence import trace_evidence_problems
from contracts.v1 import CONTRACT_VERSION, AgentRequest, AgentResult, AnalysisOutput, Provenance, assemble_result

from .agent import DocumentationAgent, request_text
from .execution import CaptureModel
from .read_policy import READ_TOOLS, ReadOnlyPolicy, parse_read_result
from .settings import AssessmentSettings

APP_VERSION = "0.4.0"
APP_DIR = Path(__file__).parent

Check = Callable[[str], list[str]]


def repair_message(problems: list[str]) -> str:
    return (
        "Verification of your previous AnalysisOutput failed: " + "; ".join(problems) + ". "
        "Return a corrected AnalysisOutput. Copy every evidence excerpt verbatim from the exact tool output "
        "or supplied source it cites, with that source's exact URI and version. "
        "Remove any evidence you cannot quote exactly."
    )


async def run_with_repair(agent: Any, message: str, check: Check | None) -> Any:
    """Run once; if verification finds problems, give the model one corrected attempt in the same session."""
    session = agent.create_session()
    response = await agent.run(message, session=session)
    problems = check(response.text) if check is not None else []
    if problems:
        response = await agent.run(repair_message(problems), session=session)
    return response


class AnalysisRunner(Protocol):
    async def analyze(
        self, request: AgentRequest, instructions: str, guard: ReadOnlyPolicy, check: Check | None = None
    ) -> str: ...


class FoundryAnalysisRunner:
    def __init__(self, settings: AssessmentSettings) -> None:
        self.settings = settings

    async def analyze(
        self, request: AgentRequest, instructions: str, guard: ReadOnlyPolicy, check: Check | None = None
    ) -> str:
        from agent_framework import Agent
        from agent_framework.foundry import FoundryChatClient
        from agent_framework_foundry_hosting import FoundryToolbox
        from azure.ai.projects.aio import AIProjectClient
        from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential

        credential = AzureCliCredential() if self.settings.auth_mode == "azure_cli" else ManagedIdentityCredential()
        async with (
            credential,
            AIProjectClient(endpoint=self.settings.project_endpoint, credential=credential) as project,
            FoundryToolbox(
                credential,
                url=self.settings.toolbox_endpoint,
                allowed_tools=READ_TOOLS,
                tool_name_prefix="",
                approval_mode="never_require",
                parse_tool_results=parse_read_result,
            ) as toolbox,
        ):
            available = {function.name for function in toolbox.functions}
            missing = set(READ_TOOLS) - available
            if missing:
                raise RuntimeError(f"P2 toolbox is missing required read tools: {', '.join(sorted(missing))}")
            if guard.record is not None:
                guard.record.tool_schemas = [
                    {"name": function.name, "description": function.description, "parameters": function.parameters()}
                    for function in toolbox.functions
                ]
            client = FoundryChatClient(
                project_client=project,
                model=self.settings.model,
                middleware=[CaptureModel(guard.record)] if guard.record is not None else None,
                function_invocation_configuration={
                    "max_iterations": 20,
                    "max_function_calls": 30,
                    "max_consecutive_errors_per_request": 1,
                    "terminate_on_unknown_calls": True,
                    "include_detailed_errors": False,
                    "allow_concurrent_invocation": False,
                },
            )
            async with client.client:
                agent = Agent(
                    client=client,
                    name="documentation-analysis",
                    instructions=instructions,
                    tools=toolbox.functions,
                    middleware=[guard],
                    default_options={"store": False, "response_format": AnalysisOutput},
                )
                response = await run_with_repair(agent, request.model_dump_json(), check)
                if response.user_input_requests:
                    raise RuntimeError("Assessment requested approval; no approvals are submitted by this runtime.")
                if response.finish_reason in {"length", "content_filter"}:
                    raise RuntimeError("Model response was incomplete or filtered.")
                return response.text


class AssessmentAgent(DocumentationAgent):
    result_model = AgentResult

    def __init__(self, settings: AssessmentSettings, runner: AnalysisRunner | None = None) -> None:
        super().__init__()
        self.description = "Read-only documentation gap analysis with contract v1."
        self.settings = settings
        self.runner = runner if runner is not None else FoundryAnalysisRunner(settings)
        prompt = (APP_DIR / "prompts" / "gap-analysis-v1.1.txt").read_text(encoding="utf-8").strip()
        policy = (APP_DIR / "policies" / "documentation-analysis-v1.txt").read_text(encoding="utf-8").strip()
        self.instructions = "\n\n".join(
            [
                prompt,
                policy,
                "The input is a validated AgentRequest. Follow request.task.question and "
                "request.task.scope when present, within the system policy and existing source restrictions. "
                "Only when task is omitted or null, assess changed_paths and context; "
                "if changed_paths is empty, assess the supplied sources. "
                "The full commit_sha is already provided: do not resolve a newer PR head. "
                "Use the tools named " + ", ".join(READ_TOOLS) + ". "
                "Git get_file_contents accepts a directory path for discovery and a file path for content; "
                "use sha=<request commit_sha> on every read. "
                "Use ado wiki action=get_page with includeContent=true, or wit_work_item action=get. "
                "Pass the configured project on every ADO call, including wit_work_item get, "
                "and the configured wikiIdentifier on every wiki call. "
                "Only pages and work items listed in the request are available. "
                "If necessary context is omitted, report missing_information rather than expanding source access.",
                "ADO source configuration: "
                + json.dumps(
                    {
                        "project": settings.ado_project,
                        "wikiIdentifier": settings.ado_wiki,
                    }
                ),
            ]
        )
        self.provenance = Provenance(
            contract_version=CONTRACT_VERSION,
            agent_name="documentation-agent",
            agent_version=APP_VERSION,
            model=settings.model,
            model_version=settings.model_version,
            prompt_version="sha256:" + hashlib.sha256(self.instructions.encode()).hexdigest(),
            policy_version="sha256:" + hashlib.sha256(policy.encode()).hexdigest(),
        )

    async def evaluate(self, messages: AgentRunInputs | None) -> AgentResult:
        try:
            request = AgentRequest.model_validate_json(request_text(messages))
        except ValidationError as exc:
            raise AgentInvalidRequestException(
                f"Invalid AgentRequest v1: {exc.errors(include_input=False, include_url=False)}"
            ) from None
        return await self.assess(request)

    async def evaluate_report(self, request: AgentRequest) -> EvaluationResponse:
        from azure.ai.agentserver.core import get_request_context

        context = get_request_context()
        record = ExecutionRecord(
            execution_id=uuid4(),
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            source_mode="live_sources",
            instructions=self.instructions,
            platform_call_id=context.call_id,
            platform_session_id=context.session_id,
        )
        result = await self.assess(request, record)
        if not record.model_calls or not record.tool_schemas:
            raise ValueError("Live evaluation did not capture model calls and discovered tool schemas.")
        if any(call.get("status") != "completed" for call in record.model_calls):
            raise ValueError("Live evaluation includes an incomplete model call.")
        record.status = "completed"
        return EvaluationResponse(result=result, execution=record)

    @staticmethod
    def analysis_problems(request: AgentRequest, guard: ReadOnlyPolicy, text: str) -> list[str]:
        try:
            output = AnalysisOutput.model_validate_json(text)
        except ValidationError:
            return []
        problems = [
            f"evidence {evidence.id} Git version must be the request commit_sha"
            for evidence in output.evidence
            if evidence.source == "git" and evidence.version != request.subject.commit_sha
        ]
        return problems + trace_evidence_problems({"output": guard.calls}, output.model_dump(mode="json"))

    async def assess(self, request: AgentRequest, record: ExecutionRecord | None = None) -> AgentResult:
        guard = ReadOnlyPolicy(request, self.settings, record)
        async with asyncio.timeout(self.settings.timeout_seconds):
            text = await self.runner.analyze(
                request, self.instructions, guard, lambda answer: self.analysis_problems(request, guard, answer)
            )
        try:
            output = AnalysisOutput.model_validate_json(text)
        except ValidationError as exc:
            raise ValueError(
                f"Invalid model AnalysisOutput: {exc.errors(include_input=False, include_url=False)}"
            ) from None
        for evidence in output.evidence:
            if evidence.source == "git" and evidence.version != request.subject.commit_sha:
                raise ValueError("Git evidence does not match the requested commit.")
        problems = trace_evidence_problems({"output": guard.calls}, output.model_dump(mode="json"))
        if problems:
            raise ValueError("Evidence verification failed: " + "; ".join(problems))
        return assemble_result(request, output, self.provenance)
