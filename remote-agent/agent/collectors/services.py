import platform
import re


SAFE_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_. -]{1,80}$")


def validate_service_name(service_name: str) -> None:
    if not SAFE_SERVICE_NAME.fullmatch(service_name):
        raise ValueError("Invalid service name.")


def collect_service_status(service_name: str, simulation: bool = True) -> dict:
    validate_service_name(service_name)
    if simulation or platform.system().lower() != "windows":
        simulated_status = "running" if service_name.lower() not in {"badservice", "stopped"} else "stopped"
        return {"service_name": service_name, "status": simulated_status, "simulation": True}
    return {"service_name": service_name, "status": "unknown", "simulation": False}
