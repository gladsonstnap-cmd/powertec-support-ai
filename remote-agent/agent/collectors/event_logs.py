from datetime import UTC, datetime


SENSITIVE_KEYS = ("password", "token", "secret", "senha")


def sanitize_event_message(message: str) -> str:
    sanitized = message
    for key in SENSITIVE_KEYS:
        sanitized = sanitized.replace(key, "[redacted]")
    return sanitized[:500]


def collect_event_logs(source: str | None = None, limit: int = 20, simulation: bool = True) -> dict:
    safe_limit = max(1, min(limit, 50))
    events = [
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "source": source or "Application",
            "level": "Information",
            "message": sanitize_event_message("Evento simulado do PowerTec Remote Agent."),
        }
    ][:safe_limit]
    return {"events": events, "simulation": simulation}
