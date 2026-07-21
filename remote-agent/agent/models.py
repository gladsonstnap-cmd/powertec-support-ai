from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class AgentMode(StrEnum):
    SIMULATION = "simulation"
    LOCAL_SAFE = "local_safe"


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PROHIBITED = "prohibited"


class CommandStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    PENDING_APPROVAL = "pending_approval"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    risk_level: RiskLevel
    requires_approval: bool
    supported_platforms: tuple[str, ...]
    timeout_seconds: int
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    executor: Any


@dataclass
class AgentIdentity:
    agent_id: str
    hostname: str
    operating_system: str
    os_version: str
    architecture: str
    agent_version: str
    registered_at: str
    local_key: str
    status: str
    last_seen: str
    mode: str


@dataclass
class ToolRequest:
    tool_name: str
    arguments: dict[str, Any]
    request_id: str = field(default_factory=lambda: str(uuid4()))
    approved: bool = False


@dataclass
class ToolResult:
    request_id: str
    agent_id: str
    tool_name: str
    status: str
    started_at: str
    finished_at: str
    duration_ms: int
    result: dict[str, Any]
    error: str | None
    audit_id: str


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
