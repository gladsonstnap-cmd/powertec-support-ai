from dataclasses import dataclass
from pathlib import Path

from agent.models import AgentMode


@dataclass(frozen=True)
class AgentConfig:
    backend_url: str = "http://localhost:8000/api/v1"
    data_dir: Path = Path.home() / ".powertec-agent"
    mode: AgentMode = AgentMode.SIMULATION
    agent_version: str = "0.1.0"
    allow_low_risk_auto: bool = False
    output_limit_bytes: int = 32_768
    audit_retention_days: int = 90
    allowed_tcp_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "servidor")
    allowed_tcp_ports: tuple[int, ...] = (80, 443, 1433, 5432, 6379)

    @property
    def identity_path(self) -> Path:
        return self.data_dir / "identity.json"

    @property
    def audit_db_path(self) -> Path:
        return self.data_dir / "audit.sqlite3"
