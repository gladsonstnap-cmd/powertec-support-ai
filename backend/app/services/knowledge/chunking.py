from app.core.config import get_settings


def chunk_text(text: str) -> list[str]:
    settings = get_settings()
    size = settings.knowledge_chunk_size
    overlap = min(settings.knowledge_chunk_overlap, size // 2)
    if len(text) <= size:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start : start + size].strip()
        if chunk:
            chunks.append(chunk)
        start += size - overlap
    return chunks
