from dataclasses import asdict
from typing import Any

from agent.models import ToolResult


class AgentClient:
    def __init__(self, backend_url: str, agent_token: str):
        self.backend_url = backend_url.rstrip("/")
        self.agent_token = agent_token

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.agent_token}", "Content-Type": "application/json"}

    def serialize_result(self, result: ToolResult) -> dict[str, Any]:
        return asdict(result)
