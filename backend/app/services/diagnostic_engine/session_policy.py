from dataclasses import dataclass


@dataclass(frozen=True)
class DiagnosticSessionPolicy:
    max_interactions: int = 20
    max_questions: int = 5
    max_tests: int = 4
    max_repeated_answers: int = 2
    auto_complete_on_decision_complete: bool = True
    auto_escalate_on_human_decision: bool = True
    allow_restart_after_completion: bool = False

    def __post_init__(self) -> None:
        integer_fields = (
            self.max_interactions,
            self.max_questions,
            self.max_tests,
            self.max_repeated_answers,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in integer_fields):
            raise ValueError("DiagnosticSessionPolicy limits must be integers")
        if self.max_interactions <= 0:
            raise ValueError("max_interactions must be greater than zero")
        if self.max_questions < 0 or self.max_tests < 0 or self.max_repeated_answers < 0:
            raise ValueError("session limits must be non-negative")
        if self.max_questions > self.max_interactions or self.max_tests > self.max_interactions:
            raise ValueError("question and test limits cannot exceed max_interactions")
