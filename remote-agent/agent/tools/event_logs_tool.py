from agent.collectors.event_logs import collect_event_logs


def execute(arguments: dict, config) -> dict:
    return collect_event_logs(arguments.get("source"), int(arguments.get("limit", 20)), simulation=config.mode.value == "simulation")
