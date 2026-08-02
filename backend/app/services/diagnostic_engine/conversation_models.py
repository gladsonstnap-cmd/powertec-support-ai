from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum

from app.services.diagnostic_engine.decision_models import Decision
from app.services.diagnostic_engine.models import DiagnosticContext
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus
from app.services.diagnostic_engine.workflow_models import WorkflowResult


class ConversationCommand(StrEnum):
    NORMAL = "NORMAL"
    STATUS = "STATUS"
    RESTART = "RESTART"
    CANCEL = "CANCEL"
    ESCALATE = "ESCALATE"
    HELP = "HELP"


@dataclass(frozen=True)
class ConversationInput:
    message: str
    session: DiagnosticSession | None = None
    context: DiagnosticContext | None = None


@dataclass(frozen=True)
class ConversationResponse:
    response: str
    session: DiagnosticSession | None
    workflow_result: WorkflowResult | None
    decision: Decision | None
    status: DiagnosticSessionStatus | None
    finished: bool
    waiting_user: bool
    waiting_confirmation: bool
    metadata: dict[str, object] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))
        object.__setattr__(self, "errors", tuple(self.errors))
