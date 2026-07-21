from agent.audit import get_audit_store
from agent.client import AgentClient
from agent.config import AgentConfig
from agent.identity import load_or_create_identity
from agent.models import ToolRequest
from agent.service import RemoteAgentService


def test_identity_is_persistent(tmp_path):
    config = AgentConfig(data_dir=tmp_path)

    first = load_or_create_identity(config)
    second = load_or_create_identity(config)

    assert first.agent_id == second.agent_id
    assert first.local_key


def test_client_builds_bearer_header():
    client = AgentClient("http://localhost:8000/api/v1", "agent-token")

    assert client.auth_headers()["Authorization"] == "Bearer agent-token"


def test_read_only_execution_records_audit(tmp_path):
    config = AgentConfig(data_dir=tmp_path)
    service = RemoteAgentService(config, get_audit_store(config))

    result = service.execute(ToolRequest(tool_name="system_info", arguments={}))

    assert result.status == "success"
    assert result.audit_id


def test_medium_or_blocked_request_does_not_execute(tmp_path):
    config = AgentConfig(data_dir=tmp_path)
    service = RemoteAgentService(config, get_audit_store(config))

    result = service.execute(ToolRequest(tool_name="service_status", arguments={"service_name": "cmd.exe"}))

    assert result.status == "blocked"
