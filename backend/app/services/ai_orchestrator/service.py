from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ai_orchestrator import (
    AIApproval,
    AIApprovalStatus,
    AIDiagnosticSession,
    AIAutonomyLevel,
    AIHypothesis,
    AIPlanStep,
    AIPlanStepStatus,
    AIRiskLevel,
    AISessionEvent,
    AISessionStatus,
)
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ai_orchestrator import (
    AIApprovalRead,
    AIDiagnosticSessionCreate,
    AIDiagnosticSessionRead,
    AIHypothesisRead,
    AIPlanStepRead,
    AISessionEventRead,
)
from app.services.ai_orchestrator.classifier import classify_incident
from app.services.ai_orchestrator.decision_engine import OrchestratorDecision, decide_next
from app.services.ai_orchestrator.evaluator import completed_result_from_step_status, evaluate_tool_result, has_resolution_evidence, should_escalate_after_failures
from app.services.ai_orchestrator.hypothesis_engine import update_hypotheses_from_evidence
from app.services.ai_orchestrator.planner import PlanStepDraft, build_plan, dynamic_step
from app.services.ai_orchestrator.policy import PolicyEngine
from app.services.ai_orchestrator.state_machine import InvalidStateTransition, assert_transition
from app.services.ai_orchestrator.tool_selector import select_next_step
from app.services.ai_orchestrator.tools import execute_tool


TERMINAL_STATUSES = {AISessionStatus.RESOLVED.value, AISessionStatus.ESCALATED.value, AISessionStatus.FAILED.value, AISessionStatus.CANCELLED.value}


def now_utc() -> datetime:
    return datetime.now(UTC)


class AIOrchestratorService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.policy = PolicyEngine()

    def create_session(self, payload: AIDiagnosticSessionCreate, user: User) -> AIDiagnosticSessionRead:
        self._ensure_enabled()
        ticket = self.db.scalar(select(Ticket).where(Ticket.id == payload.ticket_id, Ticket.tenant_id == user.tenant_id))
        if ticket is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
        session = AIDiagnosticSession(
            tenant_id=user.tenant_id,
            ticket_id=ticket.id,
            customer_message=payload.customer_message,
            channel=payload.channel,
            autonomy_level=payload.autonomy_level.value,
            status=AISessionStatus.RECEIVED.value,
            current_risk_level=AIRiskLevel.READ_ONLY.value,
            max_steps=self.settings.ai_orchestrator_max_steps,
            created_by=user.id,
            simulation_scenario=payload.simulation_scenario,
        )
        self.db.add(session)
        self.db.flush()
        self._event(session, "SESSION_CREATED", "Sessao de diagnostico recebida.", {"ticket_id": str(ticket.id)}, "user")
        self._transition(session, AISessionStatus.CLASSIFYING)
        classification = classify_incident(payload.customer_message)
        session.category = classification.category
        session.priority = classification.priority.value
        session.confidence = classification.confidence
        for rank, hypothesis in enumerate(classification.hypotheses, start=1):
            self.db.add(
                AIHypothesis(
                    tenant_id=user.tenant_id,
                    session_id=session.id,
                    code=hypothesis.code,
                    title=hypothesis.title,
                    description=hypothesis.description,
                    probability=hypothesis.probability,
                    rank=rank,
                    status="ACTIVE",
                    evidence={},
                    supporting_evidence=[],
                    contradicting_evidence=[],
                    last_updated_reason="Hipotese inicial gerada pelo classificador deterministico.",
                )
            )
        self._event(session, "CLASSIFIED", "Incidente classificado por regras deterministicas.", {"category": classification.category})
        self._transition(session, AISessionStatus.PLANNING)
        plan = build_plan(classification, payload.simulation_scenario)
        if len(plan) > session.max_steps:
            session.status = AISessionStatus.FAILED.value
            session.failure_reason = "Generated plan exceeds max steps."
            self._event(session, "PLAN_REJECTED", "Plano excedeu limite maximo de etapas.", {"max_steps": session.max_steps})
        else:
            for step in plan:
                self.db.add(
                    AIPlanStep(
                        tenant_id=user.tenant_id,
                        session_id=session.id,
                        sequence=step.sequence,
                        tool_name=step.tool_name,
                        title=step.title,
                        description=step.description,
                        parameters=step.parameters,
                        risk_level=step.risk_level.value,
                        requires_approval=step.requires_approval,
                        max_attempts=self.settings.ai_orchestrator_max_tool_attempts,
                        selection_reason=step.selection_reason,
                        is_dynamic=step.is_dynamic,
                    )
                )
            self._event(session, "PLAN_CREATED", "Plano de diagnostico simulado criado.", {"steps": len(plan)})
            self._transition(session, AISessionStatus.READY)
            self._apply_decision(session, OrchestratorDecision("CONTINUE", "Plano inicial criado com ferramentas seguras de maior valor diagnostico.", classification.confidence, classification.hypotheses[0].code if classification.hypotheses else None, plan[0].tool_name if plan else None))
        self.db.commit()
        return self.get_session(session.id, user)

    def list_sessions(self, user: User) -> list[AIDiagnosticSessionRead]:
        sessions = list(
            self.db.scalars(
                select(AIDiagnosticSession).where(AIDiagnosticSession.tenant_id == user.tenant_id).order_by(AIDiagnosticSession.created_at.desc())
            )
        )
        return [self._read(session) for session in sessions]

    def get_session(self, session_id: UUID, user: User) -> AIDiagnosticSessionRead:
        return self._read(self._get_session_model(session_id, user))

    def run_next(self, session_id: UUID, user: User) -> AIDiagnosticSessionRead:
        session = self._get_session_model(session_id, user)
        if session.status in TERMINAL_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI session is terminal")
        if session.status == AISessionStatus.WAITING_APPROVAL.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI session is waiting approval")
        self._maybe_replan(session)
        hypotheses = self._hypotheses(session)
        steps = self._steps(session)
        selection = select_next_step(hypotheses, steps)
        step = selection.step
        if step is None:
            self._apply_decision(session, decide_next(hypotheses, steps, session.max_steps, session.executed_steps))
            self._apply_terminal_decision(session)
            self.db.commit()
            return self._read(session)
        if session.executed_steps >= session.max_steps:
            session.status = AISessionStatus.ESCALATED.value
            session.escalation_reason = "Maximum diagnostic steps reached."
            session.finished_at = now_utc()
            self._event(session, "ESCALATED", session.escalation_reason)
            self.db.commit()
            return self._read(session)
        decision = self.policy.decide(step.tool_name, step.parameters, session.autonomy_level, step.risk_level)
        step.selection_reason = selection.reason
        session.current_risk_level = step.risk_level
        if decision.needs_approval:
            step.status = AIPlanStepStatus.WAITING_APPROVAL.value
            session.status = AISessionStatus.WAITING_APPROVAL.value
            self.db.add(AIApproval(tenant_id=session.tenant_id, session_id=session.id, plan_step_id=step.id))
            self._event(session, "APPROVAL_REQUESTED", decision.reason, {"step_id": str(step.id), "tool_name": step.tool_name})
            self._apply_decision(session, OrchestratorDecision("WAIT_APPROVAL", decision.reason, step.attempt_count / max(step.max_attempts, 1), None, step.tool_name))
            self.db.commit()
            return self._read(session)
        if not decision.allowed:
            step.status = AIPlanStepStatus.FAILED.value
            step.error_message = decision.reason
            session.consecutive_failures += 1
            self._event(session, "POLICY_REJECTED", decision.reason, {"tool_name": step.tool_name})
            self._evaluate_failure(session, decision.reason)
            self.db.commit()
            return self._read(session)
        self._execute_step(session, step)
        self._evaluate_after_step(session, step)
        self.db.commit()
        return self._read(session)

    def approve(self, session_id: UUID, user: User, reason: str | None = None) -> AIDiagnosticSessionRead:
        session = self._get_session_model(session_id, user)
        step = self._current_approval_step(session)
        approval = self._pending_approval(session, step)
        approval.status = AIApprovalStatus.APPROVED.value
        approval.decided_at = now_utc()
        approval.decided_by = user.id
        approval.decision_reason = reason
        step.status = AIPlanStepStatus.APPROVED.value
        self._transition(session, AISessionStatus.RUNNING)
        self._event(session, "APPROVAL_APPROVED", "Acao simulada aprovada pelo usuario.", {"step_id": str(step.id)}, "user")
        self._execute_step(session, step)
        self._evaluate_after_step(session, step)
        self.db.commit()
        return self._read(session)

    def reject(self, session_id: UUID, user: User, reason: str | None = None) -> AIDiagnosticSessionRead:
        session = self._get_session_model(session_id, user)
        step = self._current_approval_step(session)
        approval = self._pending_approval(session, step)
        approval.status = AIApprovalStatus.REJECTED.value
        approval.decided_at = now_utc()
        approval.decided_by = user.id
        approval.decision_reason = reason
        step.status = AIPlanStepStatus.REJECTED.value
        session.status = AISessionStatus.ESCALATED.value
        session.escalation_reason = "A acao simulada foi rejeitada; atendimento tecnico necessario."
        session.finished_at = now_utc()
        self._event(session, "APPROVAL_REJECTED", session.escalation_reason, {"step_id": str(step.id)}, "user")
        self.db.commit()
        return self._read(session)

    def cancel(self, session_id: UUID, user: User) -> AIDiagnosticSessionRead:
        session = self._get_session_model(session_id, user)
        if session.status in TERMINAL_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI session is terminal")
        session.status = AISessionStatus.CANCELLED.value
        session.finished_at = now_utc()
        for step in self._steps(session):
            if step.status in {AIPlanStepStatus.PENDING.value, AIPlanStepStatus.WAITING_APPROVAL.value, AIPlanStepStatus.RUNNING.value}:
                step.status = AIPlanStepStatus.CANCELLED.value
        self._event(session, "CANCELLED", "Sessao cancelada pelo usuario.", {}, "user")
        self.db.commit()
        return self._read(session)

    def events(self, session_id: UUID, user: User) -> list[AISessionEvent]:
        session = self._get_session_model(session_id, user)
        return list(self.db.scalars(select(AISessionEvent).where(AISessionEvent.session_id == session.id).order_by(AISessionEvent.created_at)))

    def _ensure_enabled(self) -> None:
        if not self.settings.ai_orchestrator_enabled:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI orchestrator disabled")
        if not self.settings.ai_orchestrator_simulation_only:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Remote actions are disabled in this MVP")

    def _get_session_model(self, session_id: UUID, user: User) -> AIDiagnosticSession:
        session = self.db.scalar(select(AIDiagnosticSession).where(AIDiagnosticSession.id == session_id, AIDiagnosticSession.tenant_id == user.tenant_id))
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI session not found")
        return session

    def _transition(self, session: AIDiagnosticSession, target: AISessionStatus) -> None:
        try:
            assert_transition(session.status, target)
        except InvalidStateTransition as exc:
            self._event(session, "INVALID_TRANSITION", str(exc))
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        source = session.status
        session.status = target.value
        if target == AISessionStatus.RUNNING and session.started_at is None:
            session.started_at = now_utc()
        self._event(session, "STATE_CHANGED", f"Estado alterado: {source} -> {target.value}", {"from": source, "to": target.value})

    def _execute_step(self, session: AIDiagnosticSession, step: AIPlanStep) -> None:
        if step.attempt_count >= step.max_attempts:
            step.status = AIPlanStepStatus.FAILED.value
            step.error_message = "Maximum attempts reached."
            self._evaluate_failure(session, step.error_message)
            return
        if session.status in {AISessionStatus.READY.value, AISessionStatus.ANALYZING_RESULT.value}:
            self._transition(session, AISessionStatus.RUNNING)
        if session.status == AISessionStatus.RUNNING.value:
            self._transition(session, AISessionStatus.WAITING_TOOL)
        step.status = AIPlanStepStatus.RUNNING.value
        step.started_at = now_utc()
        step.attempt_count += 1
        try:
            result = execute_tool(step.tool_name, step.parameters)
            step.result = result
            evidence = evaluate_tool_result(step.tool_name, result)
            step.evidence_result = {
                "evidence_codes": evidence.evidence_codes,
                "summary": evidence.summary,
                "conclusive": evidence.conclusive,
                "needs_followup": evidence.needs_followup,
            }
            step.error_message = None if result["success"] else result["message"]
            step.status = AIPlanStepStatus.COMPLETED.value if result["success"] else AIPlanStepStatus.FAILED.value
        except ValueError as exc:
            step.result = {}
            step.error_message = str(exc)
            step.status = AIPlanStepStatus.FAILED.value
        step.finished_at = now_utc()
        session.executed_steps += 1
        self._transition(session, AISessionStatus.ANALYZING_RESULT)
        self._event(session, "TOOL_EXECUTED", "Ferramenta simulada executada.", {"step_id": str(step.id), "tool_name": step.tool_name, "success": step.status == AIPlanStepStatus.COMPLETED.value, "evidence_codes": step.evidence_result.get("evidence_codes", [])})

    def _evaluate_after_step(self, session: AIDiagnosticSession, step: AIPlanStep) -> None:
        if step.status == AIPlanStepStatus.FAILED.value:
            session.consecutive_failures += 1
            self._evaluate_failure(session, step.error_message or "Tool failed.")
            return
        session.consecutive_failures = 0
        evidence_codes = [str(code) for code in step.evidence_result.get("evidence_codes", [])]
        hypotheses = self._hypotheses(session)
        update_hypotheses_from_evidence(hypotheses, evidence_codes)
        self._event(session, "EVIDENCE_EVALUATED", step.evidence_result.get("summary", "Evidencia avaliada."), {"step_id": str(step.id), "evidence_codes": evidence_codes})
        self._maybe_replan(session)
        decision = decide_next(hypotheses, self._steps(session), session.max_steps, session.executed_steps)
        self._apply_decision(session, decision)
        self._apply_terminal_decision(session)

    def _evaluate_failure(self, session: AIDiagnosticSession, reason: str) -> None:
        if should_escalate_after_failures(session.consecutive_failures, self.settings.ai_orchestrator_failure_threshold):
            session.status = AISessionStatus.ESCALATED.value
            session.escalation_reason = "Tres falhas consecutivas em ferramentas simuladas."
            session.finished_at = now_utc()
            self._event(session, "ESCALATED", session.escalation_reason, {"reason": reason})
        else:
            session.status = AISessionStatus.ANALYZING_RESULT.value
            self._event(session, "STEP_FAILED", reason)

    def _evaluate_completion(self, session: AIDiagnosticSession) -> None:
        pending = self._next_executable_step(session)
        if pending is not None:
            if session.status == AISessionStatus.ANALYZING_RESULT.value:
                self._transition(session, AISessionStatus.RUNNING)
            return
        completed_results = [result for step in self._steps(session) if (result := completed_result_from_step_status(step.status, step.result))]
        if has_resolution_evidence(completed_results):
            session.status = AISessionStatus.RESOLVED.value
            session.resolution_summary = "Diagnostico simulado concluido com evidencias registradas. Nenhum comando real foi executado."
            session.finished_at = now_utc()
            self._event(session, "RESOLVED", session.resolution_summary)
        else:
            session.status = AISessionStatus.ESCALATED.value
            session.escalation_reason = "Nao ha evidencias suficientes para marcar como resolvido."
            session.finished_at = now_utc()
            self._event(session, "ESCALATED", session.escalation_reason)

    def _hypotheses(self, session: AIDiagnosticSession) -> list[AIHypothesis]:
        return list(self.db.scalars(select(AIHypothesis).where(AIHypothesis.session_id == session.id).order_by(AIHypothesis.rank)))

    def _has_step(self, session: AIDiagnosticSession, tool_name: str, title: str | None = None) -> bool:
        steps = self._steps(session)
        return any(step.tool_name == tool_name and (title is None or step.title == title) for step in steps)

    def _add_step(self, session: AIDiagnosticSession, draft: PlanStepDraft) -> None:
        self.db.add(
            AIPlanStep(
                tenant_id=session.tenant_id,
                session_id=session.id,
                sequence=draft.sequence,
                tool_name=draft.tool_name,
                title=draft.title,
                description=draft.description,
                parameters=draft.parameters,
                risk_level=draft.risk_level.value,
                requires_approval=draft.requires_approval,
                max_attempts=self.settings.ai_orchestrator_max_tool_attempts,
                selection_reason=draft.selection_reason,
                is_dynamic=draft.is_dynamic,
            )
        )
        self._event(session, "PLAN_REPLANNED", f"Etapa dinamica adicionada: {draft.tool_name}.", {"tool_name": draft.tool_name, "reason": draft.selection_reason})

    def _maybe_replan(self, session: AIDiagnosticSession) -> None:
        steps = self._steps(session)
        if len(steps) >= session.max_steps:
            return
        codes = {code for step in steps for code in step.result.get("evidence_codes", [])}
        next_sequence = max([step.sequence for step in steps], default=0) + 1
        if "SERVICE_STOPPED" in codes and not self._has_step(session, "windows.service_restart"):
            self._add_step(session, dynamic_step(next_sequence, "windows.service_restart", session.simulation_scenario, "Servico parado confirmou a necessidade de acao segura simulada."))
            return
        if "SERVICE_RESTARTED" in codes and not any(step.is_dynamic and step.tool_name == "windows.service_status" and step.status != AIPlanStepStatus.COMPLETED.value for step in steps) and not self._has_step(session, "network.test_port", "Confirmar porta SQL apos acao"):
            self._add_step(session, dynamic_step(next_sequence, "windows.service_status", "healthy", "Verificacao posterior obrigatoria apos reinicio simulado."))
            return
        if "SERVICE_RUNNING" in codes and "DB_PORT_CLOSED" in codes and not self._has_step(session, "network.test_port", "Confirmar porta SQL apos acao"):
            return

    def _apply_decision(self, session: AIDiagnosticSession, decision: OrchestratorDecision) -> None:
        session.last_decision = decision.decision
        session.decision_reason = decision.reason
        session.recommended_tool = decision.recommended_tool
        session.final_confidence = decision.confidence
        self._event(
            session,
            "DECISION_UPDATED",
            decision.reason,
            {
                "decision": decision.decision,
                "confidence": decision.confidence,
                "next_hypothesis": decision.next_hypothesis,
                "recommended_tool": decision.recommended_tool,
            },
        )

    def _apply_terminal_decision(self, session: AIDiagnosticSession) -> None:
        if session.last_decision == "RESOLVE":
            session.status = AISessionStatus.RESOLVED.value
            session.resolution_summary = "Diagnostico adaptativo simulado concluiu causa e verificacao posterior. Nenhum comando real foi executado."
            session.finished_at = now_utc()
            self._event(session, "RESOLVED", session.resolution_summary)
        elif session.last_decision == "ESCALATE":
            session.status = AISessionStatus.ESCALATED.value
            session.escalation_reason = session.decision_reason
            session.finished_at = now_utc()
            self._event(session, "ESCALATED", session.escalation_reason or "Escalonado pelo motor de decisao.")

    def _next_executable_step(self, session: AIDiagnosticSession) -> AIPlanStep | None:
        return self.db.scalar(
            select(AIPlanStep)
            .where(
                AIPlanStep.session_id == session.id,
                AIPlanStep.status.in_([AIPlanStepStatus.PENDING.value, AIPlanStepStatus.APPROVED.value]),
            )
            .order_by(AIPlanStep.sequence)
        )

    def _current_approval_step(self, session: AIDiagnosticSession) -> AIPlanStep:
        step = self.db.scalar(
            select(AIPlanStep)
            .where(AIPlanStep.session_id == session.id, AIPlanStep.status == AIPlanStepStatus.WAITING_APPROVAL.value)
            .order_by(AIPlanStep.sequence)
        )
        if step is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No step waiting approval")
        if step.risk_level != AIRiskLevel.SAFE_ACTION.value:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only SAFE_ACTION can be approved")
        return step

    def _pending_approval(self, session: AIDiagnosticSession, step: AIPlanStep) -> AIApproval:
        approval = self.db.scalar(
            select(AIApproval).where(
                AIApproval.session_id == session.id,
                AIApproval.plan_step_id == step.id,
                AIApproval.status == AIApprovalStatus.PENDING.value,
            )
        )
        if approval is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval not found")
        return approval

    def _steps(self, session: AIDiagnosticSession) -> list[AIPlanStep]:
        return list(self.db.scalars(select(AIPlanStep).where(AIPlanStep.session_id == session.id).order_by(AIPlanStep.sequence)))

    def _event(self, session: AIDiagnosticSession, event_type: str, message: str, metadata: dict | None = None, actor_type: str = "system") -> None:
        self.db.add(
            AISessionEvent(
                tenant_id=session.tenant_id,
                session_id=session.id,
                event_type=event_type,
                message=message,
                metadata_json=metadata or {},
                actor_type=actor_type,
            )
        )

    def _read(self, session: AIDiagnosticSession) -> AIDiagnosticSessionRead:
        hypotheses = list(self.db.scalars(select(AIHypothesis).where(AIHypothesis.session_id == session.id).order_by(AIHypothesis.rank)))
        steps = self._steps(session)
        approvals = list(self.db.scalars(select(AIApproval).where(AIApproval.session_id == session.id).order_by(AIApproval.requested_at)))
        events = list(self.db.scalars(select(AISessionEvent).where(AISessionEvent.session_id == session.id).order_by(AISessionEvent.created_at)))
        return AIDiagnosticSessionRead.model_validate(session).model_copy(
            update={
                "hypotheses": [AIHypothesisRead.model_validate(item) for item in hypotheses],
                "plan_steps": [AIPlanStepRead.model_validate(item) for item in steps],
                "approvals": [AIApprovalRead.model_validate(item) for item in approvals],
                "events": [AISessionEventRead.model_validate(item) for item in events],
            }
        )
