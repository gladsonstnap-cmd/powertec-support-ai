import socket


def collect_network_info() -> dict:
    hostname = socket.gethostname()
    addresses = []
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, None)})
    except socket.gaierror:
        addresses = []
    return {"hostname": hostname, "interfaces": [{"name": "default", "addresses": addresses}], "gateway": None, "dns_servers": []}


def resolve_dns(hostname: str) -> dict:
    try:
        address = socket.gethostbyname(hostname)
        return {"hostname": hostname, "resolved": True, "address": address}
    except socket.gaierror as exc:
        return {"hostname": hostname, "resolved": False, "error": str(exc)}


def test_tcp(host: str, port: int, timeout_seconds: int = 3) -> dict:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return {"host": host, "port": port, "open": True}
    except OSError as exc:
        return {"host": host, "port": port, "open": False, "error": str(exc)}
