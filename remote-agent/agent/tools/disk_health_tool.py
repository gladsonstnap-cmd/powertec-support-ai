from agent.collectors.disk_info import collect_disk_info


def execute(arguments: dict, config) -> dict:
    return collect_disk_info(arguments.get("path", "."))
