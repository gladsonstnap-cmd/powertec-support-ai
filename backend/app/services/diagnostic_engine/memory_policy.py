from dataclasses import dataclass


@dataclass(frozen=True)
class DiagnosticMemoryPolicy:
    max_entries: int = 100
    max_facts_per_entry: int = 50
    max_query_results: int = 20
    max_known_information_items: int = 100
    minimum_fact_confidence: float = 0.40
    duplicate_confidence_tolerance: float = 0.05
    retain_hypotheses: bool = True
    retain_evidences: bool = True
    retain_questions: bool = True
    retain_answers: bool = True
    merge_duplicate_facts: bool = True
    prefer_higher_confidence_fact: bool = True
    preserve_metadata: bool = True

    def __post_init__(self) -> None:
        positive_limits = {
            "max_entries": self.max_entries,
            "max_facts_per_entry": self.max_facts_per_entry,
            "max_query_results": self.max_query_results,
        }
        for name, value in positive_limits.items():
            self._validate_integer(name, value)
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        self._validate_integer("max_known_information_items", self.max_known_information_items)
        if self.max_known_information_items < 0:
            raise ValueError("max_known_information_items must be non-negative")

        self._validate_probability("minimum_fact_confidence", self.minimum_fact_confidence)
        self._validate_probability("duplicate_confidence_tolerance", self.duplicate_confidence_tolerance)

    @staticmethod
    def _validate_integer(name: str, value: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} must be an integer")

    @staticmethod
    def _validate_probability(name: str, value: float) -> None:
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueError(f"{name} must be a number between 0.0 and 1.0")
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0.0 and 1.0")
