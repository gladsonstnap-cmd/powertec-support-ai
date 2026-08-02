from copy import deepcopy
from dataclasses import dataclass, field

from app.services.diagnostic_engine.evidence_models import Evidence
from app.services.diagnostic_engine.hypothesis_models import Hypothesis


@dataclass(frozen=True)
class MemoryFact:
    id: str
    category: str
    key: str
    value: object
    confidence: float
    created_at: float
    source: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        object.__setattr__(self, "value", deepcopy(self.value))


@dataclass(frozen=True)
class MemoryEntry:
    facts: tuple[MemoryFact, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    evidences: tuple[Evidence, ...] = ()
    questions: tuple[str, ...] = ()
    answers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("facts", "hypotheses", "evidences", "questions", "answers"):
            object.__setattr__(self, name, tuple(deepcopy(getattr(self, name))))


@dataclass(frozen=True)
class MemorySnapshot:
    entries: tuple[MemoryEntry, ...] = ()
    known_information: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(deepcopy(self.entries)))
        object.__setattr__(self, "known_information", deepcopy(dict(self.known_information)))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))


@dataclass(frozen=True)
class MemoryQueryResult:
    matches: tuple[MemoryFact, ...] = ()
    total: int = 0
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.total < 0:
            raise ValueError("total must be non-negative")
        object.__setattr__(self, "matches", tuple(deepcopy(self.matches)))
