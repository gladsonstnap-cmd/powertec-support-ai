from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.remote_agent import AgentAuditEvent, AgentCommand, AgentCommandResult, RemoteAgent
from app.models.user import User
from app.schemas.remote_agent import (
    AgentAuditEventRead,
    AgentCommandCreate,
    AgentCommandRead,
    AgentCommandResultCreate,
    AgentHeartbeat,
    AgentRegistrationCreate,
    AgentRegistrationRead,
    AgentToolRead,
    RemoteAgentRead,
)
from app.security.dependencies import bearer_scheme, get_current_user
from app.services.remote_agent_policy import (
    SERVER_TOOL_REGISTRY,
    evaluate_tool_request,
    hash_agent_token,
    make_agent_token,
    sanitize_payload,
    verify_agent_token,
)

router = APIRouter()


def utcnow() -> datetime:
    return datetime.now(UTC)


def _audit(
    db: Session,
    *,
    tenant_id,
    event_type: str,
    agent: RemoteAgent | None = None,
    command: AgentCommand | None = None,
    request_uuid: str | None = None,
    tool_name: str | None = None,
    arguments: dict | None = None,
    policy_decision: dict | None = None,
    approval: dict | None = None,
    result: dict | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    agent_version: str | None = None,
) -> AgentAuditEvent:
    event = AgentAuditEvent(
        tenant_id=tenant_id,
        agent_id=agent.id if agent else None,
        command_id=command.id if command else None,
        request_uuid=request_uuid or (command.request_uuid if command else None),
        event_type=event_type,
        tool_name=tool_name or (command.tool_name if command else None),
        sanitized_arguments=sanitize_payload(arguments or {}),
        policy_decision=policy_decision or {},
        approval=approval or {},
        result_json=sanitize_payload(result or {}),
        error_message=error,
        duration_ms=duration_ms,
        agent_version=agent_version or (agent.agent_version if agent else None),
        created_at=utcnow(),
    )
    db.add(event)
    return event


def get_agent_from_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> RemoteAgent:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent authentication required")
    agents = db.scalars(select(RemoteAgent)).all()
    for agent in agents:
        if verify_agent_token(credentials.credentials, agent.token_hash):
            return agent
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")


@router.get("/tools", response_model=list[AgentToolRead])
def list_agent_tools(current_user: User = Depends(get_current_user)):
    return [
        AgentToolRead(
            name=tool.name,
            description=tool.description,
            risk_level=tool.risk_level,
            requires_approval=tool.requires_approval,
            supported_platforms=list(tool.supported_platforms),
            timeout_seconds=tool.timeout_seconds,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
        )
        for tool in SERVER_TOOL_REGISTRY.values()
    ]


@router.post("/register", response_model=AgentRegistrationRead, status_code=201)
def register_agent(payload: AgentRegistrationCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    existing = db.scalar(select(RemoteAgent).where(RemoteAgent.agent_uuid == payload.agent_uuid, RemoteAgent.tenant_id == current_user.tenant_id))
    token = make_agent_token()
    if existing:
        existing.name = payload.name or payload.hostname
        existing.hostname = payload.hostname
        existing.operating_system = payload.operating_system
        existing.os_version = payload.os_version
        existing.architecture = payload.architecture
        existing.agent_version = payload.agent_version
        existing.mode = payload.mode
        existing.status = "online"
        existing.last_seen_at = utcnow()
        existing.token_hash = hash_agent_token(token)
        existing.metadata_json = payload.metadata_json
        agent = existing
    else:
        agent = RemoteAgent(
            tenant_id=current_user.tenant_id,
            agent_uuid=payload.agent_uuid,
            name=payload.name or payload.hostname,
            hostname=payload.hostname,
            operating_system=payload.operating_system,
            os_version=payload.os_version,
            architecture=payload.architecture,
            agent_version=payload.agent_version,
            status="online",
            mode=payload.mode,
            token_hash=hash_agent_token(token),
            last_seen_at=utcnow(),
            registered_at=utcnow(),
            metadata_json=payload.metadata_json,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(agent)
        db.flush()
    _audit(db, tenant_id=current_user.tenant_id, event_type="agent_registered", agent=agent, result={"agent_uuid": agent.agent_uuid})
    db.commit()
    db.refresh(agent)
    return AgentRegistrationRead(id=agent.id, agent_uuid=agent.agent_uuid, agent_token=token)


@router.post("/heartbeat", response_model=RemoteAgentRead)
def heartbeat(payload: AgentHeartbeat, db: Session = Depends(get_db), agent: RemoteAgent = Depends(get_agent_from_token)):
    if payload.agent_uuid != agent.agent_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent token does not match heartbeat agent_uuid")
    agent.status = payload.status
    agent.last_seen_at = utcnow()
    agent.metadata_json = {**(agent.metadata_json or {}), **payload.metadata_json}
    _audit(db, tenant_id=agent.tenant_id, event_type="agent_heartbeat", agent=agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/", response_model=list[RemoteAgentRead])
def list_agents(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.scalars(select(RemoteAgent).where(RemoteAgent.tenant_id == current_user.tenant_id).order_by(RemoteAgent.hostname)).all()


@router.post("/{agent_id}/commands", response_model=AgentCommandRead, status_code=201)
def create_command(agent_id: UUID, payload: AgentCommandCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    agent = db.get(RemoteAgent, agent_id)
    if agent is None or agent.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    existing = db.scalar(select(AgentCommand).where(AgentCommand.request_uuid == payload.request_uuid, AgentCommand.tenant_id == current_user.tenant_id))
    if existing:
        return existing
    decision = evaluate_tool_request(payload.tool_name, payload.arguments_json)
    status_value = "blocked"
    if decision["requires_approval"]:
        status_value = "pending_approval"
    elif decision["allowed"]:
        status_value = "queued"
    command = AgentCommand(
        tenant_id=current_user.tenant_id,
        agent_id=agent.id,
        ai_diagnostic_session_id=payload.ai_diagnostic_session_id,
        request_uuid=payload.request_uuid,
        tool_name=payload.tool_name,
        arguments_json=payload.arguments_json,
        status=status_value,
        risk_level=decision["risk_level"],
        requires_approval=decision["requires_approval"],
        result_json={},
        error_message=None if decision["allowed"] or decision["requires_approval"] else decision["reason"],
        created_at=utcnow(),
    )
    db.add(command)
    db.flush()
    _audit(db, tenant_id=current_user.tenant_id, event_type="command_created" if status_value != "blocked" else "command_blocked", agent=agent, command=command, arguments=payload.arguments_json, policy_decision=decision, error=command.error_message)
    db.commit()
    db.refresh(command)
    return command


@router.get("/{agent_id}/commands", response_model=list[AgentCommandRead])
def list_commands(agent_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    agent = db.get(RemoteAgent, agent_id)
    if agent is None or agent.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return db.scalars(select(AgentCommand).where(AgentCommand.agent_id == agent.id).order_by(AgentCommand.created_at.desc())).all()


@router.get("/commands/{command_id}", response_model=AgentCommandRead)
def get_command(command_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    command = db.get(AgentCommand, command_id)
    if command is None or command.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Command not found")
    return command


@router.get("/{agent_id}", response_model=RemoteAgentRead)
def get_agent(agent_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    agent = db.get(RemoteAgent, agent_id)
    if agent is None or agent.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/commands/{command_id}/approve", response_model=AgentCommandRead)
def approve_command(command_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    command = db.get(AgentCommand, command_id)
    if command is None or command.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Command not found")
    if command.status != "pending_approval":
        raise HTTPException(status_code=400, detail="Command is not waiting for approval")
    command.status = "queued"
    command.approved_by = current_user.id
    command.approved_at = utcnow()
    _audit(db, tenant_id=current_user.tenant_id, event_type="command_approved", command=command, approval={"approved_by": str(current_user.id)})
    db.commit()
    db.refresh(command)
    return command


@router.post("/commands/{command_id}/result", response_model=AgentCommandRead)
def submit_result(command_id: UUID, payload: AgentCommandResultCreate, db: Session = Depends(get_db), agent: RemoteAgent = Depends(get_agent_from_token)):
    command = db.get(AgentCommand, command_id)
    if command is None or command.agent_id != agent.id:
        raise HTTPException(status_code=403, detail="Agent cannot submit result for this command")
    if payload.request_uuid != command.request_uuid:
        raise HTTPException(status_code=400, detail="Result request_uuid does not match command")
    command.status = payload.status
    command.started_at = payload.started_at or command.started_at
    command.finished_at = payload.finished_at or utcnow()
    command.result_json = sanitize_payload(payload.result_json)
    command.error_message = payload.error_message
    result = AgentCommandResult(
        tenant_id=agent.tenant_id,
        command_id=command.id,
        agent_id=agent.id,
        status=payload.status,
        result_json=command.result_json,
        error_message=payload.error_message,
        duration_ms=payload.duration_ms,
        created_at=utcnow(),
    )
    db.add(result)
    _audit(db, tenant_id=agent.tenant_id, event_type="command_result_received", agent=agent, command=command, result=payload.result_json, error=payload.error_message, duration_ms=payload.duration_ms)
    db.commit()
    db.refresh(command)
    return command


@router.get("/{agent_id}/audit", response_model=list[AgentAuditEventRead])
def list_audit(agent_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    agent = db.get(RemoteAgent, agent_id)
    if agent is None or agent.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return db.scalars(select(AgentAuditEvent).where(AgentAuditEvent.agent_id == agent.id).order_by(AgentAuditEvent.created_at.desc())).all()
