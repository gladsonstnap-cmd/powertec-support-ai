import html
import re
from pathlib import PurePath

MAX_MESSAGE_LENGTH = 2000


def sanitize_text(value: str | None) -> str:
    if not value:
        return ""
    clean = html.escape(value.strip(), quote=True)
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", clean)
    return clean[:MAX_MESSAGE_LENGTH]


def validate_safe_filename(filename: str) -> str:
    name = PurePath(filename).name
    if name != filename or ".." in filename:
        raise ValueError("Unsafe filename")
    return name
