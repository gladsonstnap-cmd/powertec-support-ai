from agent.collectors.network_info import collect_network_info, resolve_dns, test_tcp


def execute(arguments: dict, config) -> dict:
    mode = arguments.get("mode", "summary")
    if mode == "dns":
        return resolve_dns(arguments["hostname"])
    if mode == "tcp":
        host = arguments["host"]
        port = int(arguments["port"])
        if host not in config.allowed_tcp_hosts or port not in config.allowed_tcp_ports:
            raise ValueError("TCP target is not allowed by policy.")
        return test_tcp(host, port)
    return collect_network_info()
