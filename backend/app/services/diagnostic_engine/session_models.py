from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.services.diagnostic_engine.decision_models import Decision
from app.services.diagnostic_engine.approval_models import (
    ActionApprovalRequest,
    ApprovalDecision,
    ApprovalResult,
    ApprovedActionGrant,
)
from app.services.diagnostic_engine.evidence_models import Evidence
from app.services.diagnostic_engine.execution_models import ExecutionPlan, ExecutionResult
from app.services.diagnostic_engine.executor_models import (
    ExecutionAttempt,
    ExecutionAuditTrail,
    ExecutorRequest,
    ExecutorResult,
)
from app.services.diagnostic_engine.local_executor_models import (
    LocalExecutionContract,
    LocalRawExecutionResult,
    LocalSanitizedResult,
)
from app.services.diagnostic_engine.network_probe_dispatcher import NetworkProbeDispatchResult
from app.services.diagnostic_engine.network_probe_audit import NetworkProbeAuditTrail
from app.services.diagnostic_engine.network_probe_models import NetworkProbeRequest, NetworkProbeResult
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.knowledge_models import KnowledgeSearchResult
from app.services.diagnostic_engine.memory_models import MemorySnapshot
from app.services.diagnostic_engine.models import IncidentClassification, IntentClassification
from app.services.diagnostic_engine.planner_models import DiagnosticPlan, DiagnosticPlanResult
from app.services.diagnostic_engine.workflow_models import WorkflowResult


class DiagnosticSessionStatus(StrEnum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    WAITING_USER = "WAITING_USER"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    READY_FOR_TEST = "READY_FOR_TEST"
    READY_FOR_ACTION = "READY_FOR_ACTION"
    ESCALATED = "ESCALATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class DiagnosticSession:
    """Immutable session snapshot. The initial interaction count is zero."""

    session_id: str
    status: DiagnosticSessionStatus
    original_message: str
    last_message: str
    intent: IntentClassification | None = None
    incident: IncidentClassification | None = None
    knowledge_result: tuple[KnowledgeSearchResult, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    evidence_history: tuple[Evidence, ...] = ()
    decisions: tuple[Decision, ...] = ()
    questions_asked: tuple[str, ...] = ()
    answers: tuple[str, ...] = ()
    known_information: dict[str, object] = field(default_factory=dict)
    memory_snapshot: MemorySnapshot = field(default_factory=MemorySnapshot)
    diagnostic_plan: DiagnosticPlan | None = None
    planner_result: DiagnosticPlanResult | None = None
    execution_plan: ExecutionPlan | None = None
    execution_result: ExecutionResult | None = None
    approval_requests: tuple[ActionApprovalRequest, ...] = ()
    approval_decisions: tuple[ApprovalDecision, ...] = ()
    approval_grants: tuple[ApprovedActionGrant, ...] = ()
    approval_result: ApprovalResult | None = None
    executor_requests: tuple[ExecutorRequest, ...] = ()
    execution_attempts: tuple[ExecutionAttempt, ...] = ()
    executor_results: tuple[ExecutorResult, ...] = ()
    execution_audit_trails: tuple[ExecutionAuditTrail, ...] = ()
    current_executor_result: ExecutorResult | None = None
    local_execution_contracts: tuple[LocalExecutionContract, ...] = ()
    local_raw_results: tuple[LocalRawExecutionResult, ...] = ()
    local_sanitized_results: tuple[LocalSanitizedResult, ...] = ()
    current_local_execution_contract: LocalExecutionContract | None = None
    current_local_raw_result: LocalRawExecutionResult | None = None
    current_local_sanitized_result: LocalSanitizedResult | None = None
    network_probe_requests: tuple[NetworkProbeRequest, ...] = ()
    network_probe_results: tuple[NetworkProbeResult, ...] = ()
    network_probe_dispatch_results: tuple[NetworkProbeDispatchResult, ...] = ()
    current_network_probe_request: NetworkProbeRequest | None = None
    current_network_probe_result: NetworkProbeResult | None = None
    current_network_probe_dispatch_result: NetworkProbeDispatchResult | None = None
    unresolved_information: tuple[str, ...] = ()
    current_question: str | None = None
    user_confirmation: bool | None = None
    created_at_monotonic: float = 0.0
    updated_at_monotonic: float = 0.0
    interaction_count: int = 0
    metadata: dict[str, object] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    network_probe_audit_trail: NetworkProbeAuditTrail | None = None

    def __post_init__(self) -> None:
        for name in (
            "knowledge_result",
            "hypotheses",
            "evidence_history",
            "decisions",
            "questions_asked",
            "answers",
            "approval_requests",
            "approval_decisions",
            "approval_grants",
            "executor_requests",
            "execution_attempts",
            "executor_results",
            "execution_audit_trails",
            "local_execution_contracts",
            "local_raw_results",
            "local_sanitized_results",
            "network_probe_requests",
            "network_probe_results",
            "network_probe_dispatch_results",
            "unresolved_information",
            "errors",
        ):
            object.__setattr__(self, name, tuple(deepcopy(getattr(self, name))))
        object.__setattr__(self, "known_information", deepcopy(dict(self.known_information)))
        object.__setattr__(self, "memory_snapshot", deepcopy(self.memory_snapshot))
        object.__setattr__(self, "diagnostic_plan", deepcopy(self.diagnostic_plan))
        object.__setattr__(self, "planner_result", deepcopy(self.planner_result))
        object.__setattr__(self, "execution_plan", deepcopy(self.execution_plan))
        object.__setattr__(self, "execution_result", deepcopy(self.execution_result))
        object.__setattr__(self, "approval_result", deepcopy(self.approval_result))
        object.__setattr__(self, "current_executor_result", deepcopy(self.current_executor_result))
        object.__setattr__(self, "current_local_execution_contract", deepcopy(self.current_local_execution_contract))
        object.__setattr__(self, "current_local_raw_result", deepcopy(self.current_local_raw_result))
        object.__setattr__(self, "current_local_sanitized_result", deepcopy(self.current_local_sanitized_result))
        object.__setattr__(self, "current_network_probe_request", deepcopy(self.current_network_probe_request))
        object.__setattr__(self, "current_network_probe_result", deepcopy(self.current_network_probe_result))
        object.__setattr__(self, "current_network_probe_dispatch_result", deepcopy(self.current_network_probe_dispatch_result))
        trail = self.network_probe_audit_trail
        if trail is None:
            trail = NetworkProbeAuditTrail(self.session_id)
        elif not isinstance(trail, NetworkProbeAuditTrail) or trail.session_id != self.session_id:
            raise ValueError("network_probe_audit_trail must belong to the session")
        object.__setattr__(self, "network_probe_audit_trail", deepcopy(trail))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))


@dataclass(frozen=True)
class SessionTurnResult:
    session: DiagnosticSession
    workflow_result: WorkflowResult | None
    response_message: str
    next_expected_input: str | None
    state_changed: bool
    previous_status: DiagnosticSessionStatus
    current_status: DiagnosticSessionStatus
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", tuple(self.errors))
