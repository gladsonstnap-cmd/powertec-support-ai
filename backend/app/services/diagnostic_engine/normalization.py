import re
import unicodedata

_SPACE_RE = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    lowered = value.strip().lower()
    without_accents = "".join(
        char for char in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(char)
    )
    return _SPACE_RE.sub(" ", without_accents).strip()
