from typing import Any

from agent.models import ToolDefinition


class BaseTool:
    definition: ToolDefinition

    def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
