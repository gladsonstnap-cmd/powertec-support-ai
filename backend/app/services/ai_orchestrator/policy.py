from dataclasses import dataclass

from app.models.ai_orchestrator import AIAutonomyLevel, AIRiskLevel
from app.services.ai_orchestrator.tools import ToolValidationError, get_tool, validate_parameters


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    needs_approval: bool
    reason: str


class PolicyEngine:
    def __init__(self, automatic_safe_tools: set[str] | None = None) -> None:
        self.automatic_safe_tools = automatic_safe_tools or set()

    def decide(self, tool_name: str, parameters: dict, autonomy_level: AIAutonomyLevel | str, risk_level: AIRiskLevel | str) -> PolicyDecision:
        try:
            tool = get_tool(tool_name)
            validate_parameters(tool, parameters)
        except ToolValidationError as exc:
            return PolicyDecision(False, False, str(exc))

        risk = AIRiskLevel(risk_level)
        autonomy = AIAutonomyLevel(autonomy_level)
        if risk == AIRiskLevel.READ_ONLY:
            return PolicyDecision(True, False, "READ_ONLY action allowed automatically.")
        if risk == AIRiskLevel.SAFE_ACTION:
            if autonomy == AIAutonomyLevel.DIAGNOSTIC_ONLY:
                return PolicyDecision(False, False, "SAFE_ACTION is not allowed in DIAGNOSTIC_ONLY mode.")
            if autonomy == AIAutonomyLevel.SAFE_ACTIONS_WITH_APPROVAL:
                return PolicyDecision(False, True, "SAFE_ACTION requires approval.")
            return PolicyDecision(tool_name in self.automatic_safe_tools, False, "SAFE_ACTION automatic policy evaluated.")
        if risk == AIRiskLevel.RESTRICTED:
            return PolicyDecision(False, False, "RESTRICTED actions cannot be executed automatically.")
        return PolicyDecision(False, False, "BLOCKED actions are never allowed.")
