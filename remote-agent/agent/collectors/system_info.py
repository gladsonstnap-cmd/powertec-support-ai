import getpass
import os
import platform
import socket
import sys
import time


def collect_system_info(agent_version: str) -> dict:
    boot_time = time.time() - (time.monotonic() if hasattr(time, "monotonic") else 0)
    return {
        "hostname": socket.gethostname(),
        "operating_system": platform.system() or "unknown",
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "cpu": platform.processor() or "unknown",
        "cpu_cores": os.cpu_count() or 1,
        "memory_total_bytes": None,
        "memory_available_bytes": None,
        "uptime_seconds": int(time.time() - boot_time),
        "current_user": getpass.getuser(),
        "python_version": sys.version.split()[0],
        "agent_version": agent_version,
    }
