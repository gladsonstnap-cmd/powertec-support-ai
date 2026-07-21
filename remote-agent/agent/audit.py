import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.config import AgentConfig
from agent.models import utc_now_iso
from agent.policy import sanitize_output
from agent.storage import ensure_data_dir


class AuditStore:
    def __init__(self, path: Path):
        self.path = path
        ensure_data_dir(path.parent)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    audit_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    sanitized_arguments TEXT NOT NULL,
                    policy_decision TEXT NOT NULL,
                    approval TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    result TEXT,
                    error TEXT,
                    duration_ms INTEGER,
                    agent_version TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def record(self, *, agent_id: str, request_id: str, tool_name: str, arguments: dict[str, Any], policy_decision: dict[str, Any], approval: bool, started_at: str, finished_at: str | None, result: dict[str, Any] | None, error: str | None, duration_ms: int | None, agent_version: str) -> str:
        audit_id = str(uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    audit_id, agent_id, request_id, tool_name, sanitized_arguments,
                    policy_decision, approval, started_at, finished_at, result,
                    error, duration_ms, agent_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    agent_id,
                    request_id,
                    tool_name,
                    json.dumps(sanitize_output(arguments), sort_keys=True),
                    json.dumps(policy_decision, sort_keys=True),
                    json.dumps({"approved": approval}),
                    started_at,
                    finished_at,
                    json.dumps(sanitize_output(result or {}), sort_keys=True),
                    error,
                    duration_ms,
                    agent_version,
                    utc_now_iso(),
                ),
            )
        return audit_id

    def list_events(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT audit_id, agent_id, request_id, tool_name, policy_decision, error, created_at FROM audit_events ORDER BY created_at").fetchall()
        return [
            {"audit_id": row[0], "agent_id": row[1], "request_id": row[2], "tool_name": row[3], "policy_decision": json.loads(row[4]), "error": row[5], "created_at": row[6]}
            for row in rows
        ]


def get_audit_store(config: AgentConfig) -> AuditStore:
    return AuditStore(config.audit_db_path)
