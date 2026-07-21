from agent.collectors.services import collect_service_status
from agent.models import AgentMode


def execute(arguments: dict, config) -> dict:
    return collect_service_status(arguments["service_name"], simulation=config.mode == AgentMode.SIMULATION)
