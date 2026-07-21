import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.agents import create_command, register_agent, submit_result
from app.models.remote_agent import AgentAuditEvent, AgentCommand, RemoteAgent
from app.schemas.remote_agent import AgentCommandCreate, AgentCommandResultCreate, AgentRegistrationCreate
from app.services.remote_agent_policy import evaluate_tool_request, hash_agent_token, sanitize_payload, verify_agent_token
from app.services.remote_agent_integration import build_agent_command_proposal


class FakeDb:
    def __init__(self):
        self.objects = []
        self.by_id = {}
        self.scalar_result = None

    def scalar(self, stmt):
        return self.scalar_result

    def add(self, obj):
        self.objects.append(obj)

    def flush(self):
        for obj in self.objects:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()
            if isinstance(obj, RemoteAgent):
                self.by_id[obj.id] = obj
            if isinstance(obj, AgentCommand):
                self.by_id[obj.id] = obj

    def commit(self):
        self.flush()

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    def get(self, model, item_id):
        return self.by_id.get(item_id)


def user():
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4())


def test_agent_registration_returns_token_once_and_stores_hash():
    db = FakeDb()
    current_user = user()

    response = register_agent(
        AgentRegistrationCreate(agent_uuid="agent-1", hostname="host", operating_system="Windows", agent_version="0.1.0"),
        db,
        current_user,
    )

    agent = next(obj for obj in db.objects if isinstance(obj, RemoteAgent))
    assert response.agent_token
    assert agent.token_hash != response.agent_token
    assert verify_agent_token(response.agent_token, agent.token_hash) is True
    assert len(agent.token_hash) == 64


def test_server_policy_allows_allowlisted_tool_and_blocks_unknown():
    allowed = evaluate_tool_request("service_status", {"service_name": "Spooler"})
    blocked = evaluate_tool_request("os.run", {})

    assert allowed["allowed"] is True
    assert blocked["allowed"] is False
    assert blocked["reason"] == "Unknown tool."


def test_dangerous_arguments_are_blocked_and_sanitized():
    blocked = evaluate_tool_request("network_test", {"mode": "dns", "hostname": "Invoke-Expression"})
    sanitized = sanitize_payload({"token": "secret", "nested": {"password": "secret"}})

    assert blocked["allowed"] is False
    assert "prohibited" in blocked["reason"].lower()
    assert sanitized["token"] == "[redacted]"
    assert sanitized["nested"]["password"] == "[redacted]"


def test_create_command_is_idempotent_for_same_request_uuid():
    db = FakeDb()
    current_user = user()
    agent = RemoteAgent(
        id=uuid4(),
        tenant_id=current_user.tenant_id,
        agent_uuid="agent-1",
        name="host",
        hostname="host",
        operating_system="Windows",
        agent_version="0.1.0",
        status="online",
        mode="simulation",
        token_hash=hash_agent_token("token"),
        metadata_json={},
    )
    db.by_id[agent.id] = agent
    existing = AgentCommand(
        id=uuid4(),
        tenant_id=current_user.tenant_id,
        agent_id=agent.id,
        request_uuid="req-1",
        tool_name="system_info",
        arguments_json={},
        status="queued",
        risk_level="read_only",
        requires_approval=False,
        result_json={},
    )
    db.scalar_result = existing

    response = create_command(agent.id, AgentCommandCreate(request_uuid="req-1", tool_name="system_info"), db, current_user)

    assert response is existing


def test_create_command_blocks_dangerous_tool_name_and_audits():
    db = FakeDb()
    current_user = user()
    agent = RemoteAgent(
        id=uuid4(),
        tenant_id=current_user.tenant_id,
        agent_uuid="agent-1",
        name="host",
        hostname="host",
        operating_system="Windows",
        agent_version="0.1.0",
        status="online",
        mode="simulation",
        token_hash=hash_agent_token("token"),
        metadata_json={},
    )
    db.by_id[agent.id] = agent

    command = create_command(agent.id, AgentCommandCreate(request_uuid="req-2", tool_name="powershell", arguments_json={}), db, current_user)

    assert command.status == "blocked"
    assert any(isinstance(obj, AgentAuditEvent) and obj.event_type == "command_blocked" for obj in db.objects)


def test_agent_cannot_submit_result_for_another_agent():
    tenant_id = uuid4()
    db = FakeDb()
    command = AgentCommand(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=uuid4(),
        request_uuid="req-3",
        tool_name="system_info",
        arguments_json={},
        status="queued",
        risk_level="read_only",
        requires_approval=False,
        result_json={},
    )
    db.by_id[command.id] = command
    other_agent = RemoteAgent(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_uuid="agent-2",
        name="other",
        hostname="other",
        operating_system="Windows",
        agent_version="0.1.0",
        status="online",
        mode="simulation",
        token_hash=hash_agent_token("token"),
        metadata_json={},
    )

    with pytest.raises(HTTPException) as exc:
        submit_result(command.id, AgentCommandResultCreate(request_uuid="req-3", status="success"), db, other_agent)

    assert exc.value.status_code == 403


def test_agent_result_must_match_request_uuid():
    tenant_id = uuid4()
    db = FakeDb()
    agent_id = uuid4()
    command = AgentCommand(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        request_uuid="req-expected",
        tool_name="system_info",
        arguments_json={},
        status="queued",
        risk_level="read_only",
        requires_approval=False,
        result_json={},
    )
    db.by_id[command.id] = command
    agent = RemoteAgent(
        id=agent_id,
        tenant_id=tenant_id,
        agent_uuid="agent-1",
        name="host",
        hostname="host",
        operating_system="Windows",
        agent_version="0.1.0",
        status="online",
        mode="simulation",
        token_hash=hash_agent_token("token"),
        metadata_json={},
    )

    with pytest.raises(HTTPException) as exc:
        submit_result(command.id, AgentCommandResultCreate(request_uuid="wrong", status="success"), db, agent)

    assert exc.value.status_code == 400


def test_migration_0006_revision_is_short_and_points_to_0005():
    migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "0006_remote_agents.py"
    spec = importlib.util.spec_from_file_location("migration_0006_remote_agents", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "0006_remote_agents"
    assert len(migration.revision) <= 32
    assert migration.down_revision == "0005_ai_intelligence"


def test_ai_orchestrator_recommendation_can_become_agent_command_proposal():
    proposal = build_agent_command_proposal("windows.service_status", {"service_name": "MSSQLSERVER"}, "session-id")

    assert proposal["status"] == "queued"
    assert proposal["tool_name"] == "service_status"
    assert proposal["ai_diagnostic_session_id"] == "session-id"
