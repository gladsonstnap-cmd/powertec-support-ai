from agent.collectors.system_info import collect_system_info
from agent.config import AgentConfig


def execute(arguments: dict, config: AgentConfig) -> dict:
    return collect_system_info(config.agent_version)
