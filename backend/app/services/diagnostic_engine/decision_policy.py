from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionPolicy:
    minimum_hypothesis_confidence: float = 0.45
    test_confidence_threshold: float = 0.60
    action_confidence_threshold: float = 0.80
    completion_confidence_threshold: float = 0.90
    ambiguity_margin: float = 0.10
    max_questions: int = 5
    max_tests: int = 4
    require_confirmation_for_actions: bool = True

    def __post_init__(self) -> None:
        values = (
            self.minimum_hypothesis_confidence,
            self.test_confidence_threshold,
            self.action_confidence_threshold,
            self.completion_confidence_threshold,
            self.ambiguity_margin,
        )
        if any(value < 0.0 or value > 1.0 for value in values):
            raise ValueError("DecisionPolicy thresholds must be between 0.0 and 1.0")
        if not (
            self.minimum_hypothesis_confidence
            <= self.test_confidence_threshold
            <= self.action_confidence_threshold
            <= self.completion_confidence_threshold
        ):
            raise ValueError("DecisionPolicy thresholds must be ordered")
        if self.max_questions < 0 or self.max_tests < 0:
            raise ValueError("DecisionPolicy limits must be non-negative")
