from dataclasses import dataclass

from app.models.ai_orchestrator import AIPlanStep, AIPlanStepStatus, AIHypothesis
from app.services.ai_orchestrator.hypothesis_engine import strongest_hypothesis
from app.services.ai_orchestrator.tools import TOOLS, get_tool


@dataclass(frozen=True)
class ToolSelection:
    step: AIPlanStep | None
    reason: str


def _completed_tools(steps: list[AIPlanStep]) -> set[str]:
    return {step.tool_name for step in steps if step.status == AIPlanStepStatus.COMPLETED.value}


def select_next_step(hypotheses: list[AIHypothesis], steps: list[AIPlanStep]) -> ToolSelection:
    pending = [step for step in steps if step.status in {AIPlanStepStatus.PENDING.value, AIPlanStepStatus.APPROVED.value}]
    if not pending:
        return ToolSelection(None, "Nao ha etapa pendente disponivel.")
    completed = _completed_tools(steps)
    strongest = strongest_hypothesis(hypotheses)
    if strongest is None:
        return ToolSelection(pending[0], "Sem hipotese dominante; selecionando proxima etapa segura.")
    scored: list[tuple[int, AIPlanStep]] = []
    for step in pending:
        tool = get_tool(step.tool_name)
        repeated = step.tool_name in completed and not tool.can_repeat
        score = tool.diagnostic_value - tool.estimated_cost
        if strongest.code in tool.confirms_hypotheses or strongest.code in tool.rejects_hypotheses:
            score += 4
        if repeated:
            score -= 10
        scored.append((score, step))
    selected = max(scored, key=lambda item: item[0])[1]
    return ToolSelection(selected, f"Ferramenta escolhida para testar a hipotese mais provavel: {strongest.code}.")


def can_use_tool(tool_name: str) -> bool:
    return tool_name in TOOLS
