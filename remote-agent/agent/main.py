from agent.audit import get_audit_store
from agent.config import AgentConfig
from agent.models import ToolRequest
from agent.service import RemoteAgentService


def main() -> None:
    config = AgentConfig()
    service = RemoteAgentService(config, get_audit_store(config))
    result = service.execute(ToolRequest(tool_name="system_info", arguments={}))
    print(result)


if __name__ == "__main__":
    main()
