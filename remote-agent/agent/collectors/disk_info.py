import shutil
from pathlib import Path


def collect_disk_info(path: str = ".") -> dict:
    usage = shutil.disk_usage(Path(path).resolve())
    used_percent = round(((usage.total - usage.free) / usage.total) * 100, 2) if usage.total else 0
    return {
        "drives": [
            {
                "path": str(Path(path).resolve().anchor or Path(path).resolve()),
                "total_bytes": usage.total,
                "free_bytes": usage.free,
                "used_percent": used_percent,
                "filesystem": "unknown",
                "low_space": used_percent >= 90,
                "smart_available": False,
                "smart_status": "unavailable",
            }
        ]
    }
