from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.ai_orchestrator import AIDiagnosticSessionCreate, AIDiagnosticSessionRead, AIApprovalDecision, AISessionEventRead
from app.security.dependencies import get_current_user
from app.services.ai_orchestrator.service import AIOrchestratorService

router = APIRouter()


def service(db: Session = Depends(get_db)) -> AIOrchestratorService:
    return AIOrchestratorService(db)


@router.post("/", response_model=AIDiagnosticSessionRead, status_code=201)
def create_ai_session(
    payload: AIDiagnosticSessionCreate,
    orchestrator: AIOrchestratorService = Depends(service),
    current_user: User = Depends(get_current_user),
):
    return orchestrator.create_session(payload, current_user)


@router.get("/", response_model=list[AIDiagnosticSessionRead])
def list_ai_sessions(orchestrator: AIOrchestratorService = Depends(service), current_user: User = Depends(get_current_user)):
    return orchestrator.list_sessions(current_user)


@router.get("/{session_id}", response_model=AIDiagnosticSessionRead)
def get_ai_session(session_id: UUID, orchestrator: AIOrchestratorService = Depends(service), current_user: User = Depends(get_current_user)):
    return orchestrator.get_session(session_id, current_user)


@router.post("/{session_id}/run", response_model=AIDiagnosticSessionRead)
def run_ai_session(session_id: UUID, orchestrator: AIOrchestratorService = Depends(service), current_user: User = Depends(get_current_user)):
    return orchestrator.run_next(session_id, current_user)


@router.post("/{session_id}/approve", response_model=AIDiagnosticSessionRead)
def approve_ai_session(
    session_id: UUID,
    payload: AIApprovalDecision,
    orchestrator: AIOrchestratorService = Depends(service),
    current_user: User = Depends(get_current_user),
):
    return orchestrator.approve(session_id, current_user, payload.reason)


@router.post("/{session_id}/reject", response_model=AIDiagnosticSessionRead)
def reject_ai_session(
    session_id: UUID,
    payload: AIApprovalDecision,
    orchestrator: AIOrchestratorService = Depends(service),
    current_user: User = Depends(get_current_user),
):
    return orchestrator.reject(session_id, current_user, payload.reason)


@router.post("/{session_id}/cancel", response_model=AIDiagnosticSessionRead)
def cancel_ai_session(session_id: UUID, orchestrator: AIOrchestratorService = Depends(service), current_user: User = Depends(get_current_user)):
    return orchestrator.cancel(session_id, current_user)


@router.get("/{session_id}/events", response_model=list[AISessionEventRead])
def list_ai_session_events(session_id: UUID, orchestrator: AIOrchestratorService = Depends(service), current_user: User = Depends(get_current_user)):
    return orchestrator.events(session_id, current_user)
