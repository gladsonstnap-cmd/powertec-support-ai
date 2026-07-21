from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AgentRegistrationCreate(BaseModel):
    agent_uuid: str
    name: str | None = None
    hostname: str
    operating_system: str
    os_version: str | None = None
    architecture: str | None = None
    agent_version: str
    mode: str = "simulation"
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class AgentRegistrationRead(BaseModel):
    id: UUID
    agent_uuid: str
    agent_token: str

    model_config = {"from_attributes": True}


class AgentHeartbeat(BaseModel):
    agent_uuid: str
    status: str = "online"
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RemoteAgentRead(BaseModel):
    id: UUID
    agent_uuid: str
    name: str
    hostname: str
    operating_system: str
    os_version: str | None
    architecture: str | None
    agent_version: str
    status: str
    mode: str
    last_seen_at: datetime | None
    registered_at: datetime
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentCommandCreate(BaseModel):
    request_uuid: str
    tool_name: str
    arguments_json: dict[str, Any] = Field(default_factory=dict)
    ai_diagnostic_session_id: UUID | None = None


class AgentCommandRead(BaseModel):
    id: UUID
    agent_id: UUID
    request_uuid: str
    tool_name: str
    arguments_json: dict[str, Any]
    status: str
    risk_level: str
    requires_approval: bool
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result_json: dict[str, Any]
    error_message: str | None

    model_config = {"from_attributes": True}


class AgentCommandResultCreate(BaseModel):
    request_uuid: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    result_json: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    audit_id: str | None = None


class AgentAuditEventRead(BaseModel):
    id: UUID
    agent_id: UUID | None
    command_id: UUID | None
    request_uuid: str | None
    event_type: str
    tool_name: str | None
    sanitized_arguments: dict[str, Any]
    policy_decision: dict[str, Any]
    approval: dict[str, Any]
    result_json: dict[str, Any]
    error_message: str | None
    duration_ms: int | None
    agent_version: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentToolRead(BaseModel):
    name: str
    description: str
    risk_level: str
    requires_approval: bool
    supported_platforms: list[str]
    timeout_seconds: int
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
