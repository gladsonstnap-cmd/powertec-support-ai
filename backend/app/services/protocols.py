from datetime import UTC, datetime
from secrets import randbelow


def generate_ticket_protocol() -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    return f"PT-{today}-{randbelow(1_000_000):06d}"
