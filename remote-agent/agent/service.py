from time import monotonic
from typing import Any

from agent.audit import AuditStore
from agent.config import AgentConfig
from agent.identity import load_or_create_identity
from agent.models import ToolRequest, ToolResult, utc_now_iso
from agent.policy import evaluate_tool_request, sanitize_output
from agent.registry import build_registry


class RemoteAgentService:
    def __init__(self, config: AgentConfig, audit_store: AuditStore):
        self.config = config
        self.audit_store = audit_store
        self.identity = load_or_create_identity(config)

    def execute(self, request: ToolRequest) -> ToolResult:
        started_at = utc_now_iso()
        started = monotonic()
        policy_decision = evaluate_tool_request(request.tool_name, request.arguments, request.approved, self.config)
        status = "blocked"
        result: dict[str, Any] = {}
        error: str | None = None

        if policy_decision["allowed"]:
            try:
                tool = build_registry(self.config)[request.tool_name]
                result = sanitize_output(tool.executor(request.arguments, self.config), self.config.output_limit_bytes)
                status = "success"
            except TimeoutError as exc:
                status = "timeout"
                error = str(exc)
            except Exception as exc:
                status = "failed"
                error = str(exc)
        else:
            error = policy_decision["reason"]

        finished_at = utc_now_iso()
        duration_ms = int((monotonic() - started) * 1000)
        audit_id = self.audit_store.record(
            agent_id=self.identity.agent_id,
            request_id=request.request_id,
            tool_name=request.tool_name,
            arguments=request.arguments,
            policy_decision=policy_decision,
            approval=request.approved,
            started_at=started_at,
            finished_at=finished_at,
            result=result,
            error=error,
            duration_ms=duration_ms,
            agent_version=self.identity.agent_version,
        )
        return ToolResult(request.request_id, self.identity.agent_id, request.tool_name, status, started_at, finished_at, duration_ms, result, error, audit_id)
