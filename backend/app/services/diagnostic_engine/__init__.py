"""Deterministic diagnostic engine for PowerTec Support AI."""

from app.services.diagnostic_engine.evidence_engine import EvidenceEngine
from app.services.diagnostic_engine.evidence_extractor import EvidenceExtractor
from app.services.diagnostic_engine.evidence_models import Evidence, EvidencePolarity, EvidenceResult, EvidenceType, HypothesisUpdate
from app.services.diagnostic_engine.evidence_scoring import EvidenceScorer
from app.services.diagnostic_engine.decision_engine import DecisionEngine
from app.services.diagnostic_engine.decision_models import Decision, DecisionInput, DecisionPriority, DecisionType
from app.services.diagnostic_engine.decision_policy import DecisionPolicy
from app.services.diagnostic_engine.intent_classifier import IntentClassifier
from app.services.diagnostic_engine.incident_classifier import IncidentClassifier
from app.services.diagnostic_engine.hypothesis_engine import HypothesisEngine
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.knowledge_base import KnowledgeBase
from app.services.diagnostic_engine.knowledge_loader import KnowledgeLoader
from app.services.diagnostic_engine.knowledge_models import KnowledgeIncident, KnowledgeSearchResult, KnowledgeValidationError
from app.services.diagnostic_engine.question_selector import QuestionSelector
from app.services.diagnostic_engine.models import DiagnosticContext, IncidentClassification, IntentClassification
from app.services.diagnostic_engine.workflow_engine import DiagnosticWorkflowEngine
from app.services.diagnostic_engine.workflow_models import WorkflowResult, WorkflowStep
from app.services.diagnostic_engine.session_engine import DiagnosticSessionEngine
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus, SessionTurnResult
from app.services.diagnostic_engine.session_policy import DiagnosticSessionPolicy
from app.services.diagnostic_engine.conversation_engine import DiagnosticConversationEngine
from app.services.diagnostic_engine.conversation_models import ConversationCommand, ConversationInput, ConversationResponse
from app.services.diagnostic_engine.memory_models import MemoryEntry, MemoryFact, MemoryQueryResult, MemorySnapshot
from app.services.diagnostic_engine.memory_policy import DiagnosticMemoryPolicy
from app.services.diagnostic_engine.memory_engine import DiagnosticMemoryEngine
from app.services.diagnostic_engine.planner_models import (
    DiagnosticPlan,
    DiagnosticPlanResult,
    DiagnosticPlanStatus,
    PlanCondition,
    PlanStep,
    PlanStepStatus,
    PlanStepType,
)
from app.services.diagnostic_engine.planner_policy import DiagnosticPlannerPolicy
from app.services.diagnostic_engine.planner_engine import DiagnosticPlannerEngine
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction,
    ExecutionParameter,
    ExecutionPlan,
    ExecutionResult,
    ExecutionRisk,
    ExecutionStatus,
    ExecutionTarget,
)
from app.services.diagnostic_engine.execution_policy import DiagnosticExecutionPolicy
from app.services.diagnostic_engine.execution_engine import DiagnosticExecutionEngine
from app.services.diagnostic_engine.approval_models import (
    ActionApprovalRequest,
    ApprovalActor,
    ApprovalDecision,
    ApprovalResult,
    ApprovalScope,
    ApprovalStatus,
    ApprovalType,
    ApprovedActionGrant,
)
from app.services.diagnostic_engine.approval_policy import DiagnosticApprovalPolicy
from app.services.diagnostic_engine.approval_engine import DiagnosticApprovalEngine
from app.services.diagnostic_engine.executor_models import (
    AuditEvent,
    AuditEventType,
    ExecutionAttempt,
    ExecutionAuditTrail,
    ExecutionContext,
    ExecutorBlockReason,
    ExecutorRequest,
    ExecutorResult,
    ExecutorStatus,
    RollbackPlan,
)
from app.services.diagnostic_engine.executor_policy import DiagnosticExecutorPolicy
from app.services.diagnostic_engine.executor_engine import DiagnosticExecutorEngine
from app.services.diagnostic_engine.local_executor_models import (
    AllowedLocalOperation,
    LocalAdapterType,
    LocalExecutionCommand,
    LocalExecutionContract,
    LocalExecutionState,
    LocalOperationArgument,
    LocalOperationType,
    LocalOutputChunk,
    LocalRawExecutionResult,
    LocalSandboxPolicy,
    LocalSanitizedResult,
    OutputStreamType,
    RedactedValue,
    RedactionReason,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog
from app.services.diagnostic_engine.local_operation_validator import (
    LocalOperationValidationResult,
    SafeLocalOperationValidator,
)
from app.services.diagnostic_engine.local_system_information_adapter import LocalSystemInformationAdapter
from app.services.diagnostic_engine.local_disk_information_adapter import LocalDiskInformationAdapter
from app.services.diagnostic_engine.local_event_log_adapter import LocalEventLogAdapter
from app.services.diagnostic_engine.local_adapter_dispatcher import (
    LocalAdapterDispatcher,
    LocalAdapterDispatchResult,
)

__all__ = [
    "DiagnosticContext",
    "AuditEvent",
    "AuditEventType",
    "DiagnosticApprovalPolicy",
    "DiagnosticApprovalEngine",
    "DiagnosticConversationEngine",
    "DiagnosticExecutionPolicy",
    "DiagnosticExecutionEngine",
    "DiagnosticExecutorPolicy",
    "DiagnosticExecutorEngine",
    "DiagnosticLocalExecutorPolicy",
    "SafeLocalOperationCatalog",
    "LocalOperationValidationResult",
    "SafeLocalOperationValidator",
    "LocalSystemInformationAdapter",
    "LocalDiskInformationAdapter",
    "LocalEventLogAdapter",
    "LocalAdapterDispatcher",
    "LocalAdapterDispatchResult",
    "AllowedLocalOperation",
    "LocalAdapterType",
    "LocalExecutionCommand",
    "LocalExecutionContract",
    "LocalExecutionState",
    "LocalOperationArgument",
    "LocalOperationType",
    "LocalOutputChunk",
    "LocalRawExecutionResult",
    "LocalSandboxPolicy",
    "LocalSanitizedResult",
    "OutputStreamType",
    "RedactedValue",
    "RedactionReason",
    "DiagnosticMemoryPolicy",
    "DiagnosticMemoryEngine",
    "DiagnosticPlan",
    "DiagnosticPlanResult",
    "DiagnosticPlanStatus",
    "DiagnosticPlannerPolicy",
    "DiagnosticPlannerEngine",
    "DiagnosticSession",
    "DiagnosticSessionEngine",
    "DiagnosticSessionPolicy",
    "DiagnosticSessionStatus",
    "DiagnosticWorkflowEngine",
    "ConversationCommand",
    "ConversationInput",
    "ConversationResponse",
    "ActionApprovalRequest",
    "ApprovalActor",
    "ApprovalDecision",
    "ApprovalResult",
    "ApprovalScope",
    "ApprovalStatus",
    "ApprovalType",
    "ApprovedActionGrant",
    "Decision",
    "DecisionEngine",
    "DecisionInput",
    "DecisionPolicy",
    "DecisionPriority",
    "DecisionType",
    "Evidence",
    "EvidenceEngine",
    "EvidenceExtractor",
    "EvidencePolarity",
    "EvidenceResult",
    "EvidenceScorer",
    "EvidenceType",
    "ExecutionAction",
    "ExecutionAttempt",
    "ExecutionAuditTrail",
    "ExecutionContext",
    "ExecutionParameter",
    "ExecutionPlan",
    "ExecutionResult",
    "ExecutionRisk",
    "ExecutionStatus",
    "ExecutionTarget",
    "ExecutorBlockReason",
    "ExecutorRequest",
    "ExecutorResult",
    "ExecutorStatus",
    "Hypothesis",
    "HypothesisEngine",
    "HypothesisUpdate",
    "IncidentClassification",
    "IncidentClassifier",
    "IntentClassification",
    "IntentClassifier",
    "KnowledgeBase",
    "KnowledgeIncident",
    "KnowledgeLoader",
    "KnowledgeSearchResult",
    "KnowledgeValidationError",
    "MemoryEntry",
    "MemoryFact",
    "MemoryQueryResult",
    "MemorySnapshot",
    "PlanCondition",
    "PlanStep",
    "PlanStepStatus",
    "PlanStepType",
    "QuestionSelector",
    "RollbackPlan",
    "SessionTurnResult",
    "WorkflowResult",
    "WorkflowStep",
]
