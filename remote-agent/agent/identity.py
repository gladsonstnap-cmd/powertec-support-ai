import platform
import secrets
import socket
from dataclasses import asdict
from uuid import uuid4

from agent.config import AgentConfig
from agent.models import AgentIdentity, utc_now_iso
from agent.storage import read_json, write_json


def load_or_create_identity(config: AgentConfig) -> AgentIdentity:
    stored = read_json(config.identity_path)
    if stored:
        return AgentIdentity(**stored)

    now = utc_now_iso()
    identity = AgentIdentity(
        agent_id=str(uuid4()),
        hostname=socket.gethostname(),
        operating_system=platform.system() or "unknown",
        os_version=platform.version(),
        architecture=platform.machine(),
        agent_version=config.agent_version,
        registered_at=now,
        local_key=secrets.token_urlsafe(32),
        status="offline",
        last_seen=now,
        mode=config.mode.value,
    )
    write_json(config.identity_path, asdict(identity))
    return identity


def save_identity(config: AgentConfig, identity: AgentIdentity) -> None:
    write_json(config.identity_path, asdict(identity))
