from pathlib import PurePath

from app.core.config import get_settings


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown", ".csv", ".log"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/octet-stream",
}
BLOCKED_EXTENSIONS = {".exe", ".bat", ".cmd", ".ps1", ".sh", ".msi", ".dll", ".scr", ".js", ".vbs"}


class KnowledgeValidationError(ValueError):
    pass


def validate_document_file(filename: str, mime_type: str, content: bytes) -> str:
    if not filename or PurePath(filename).name != filename:
        raise KnowledgeValidationError("Invalid filename.")
    suffix = PurePath(filename).suffix.lower()
    if suffix in BLOCKED_EXTENSIONS:
        raise KnowledgeValidationError("Executable files are not accepted.")
    if suffix not in ALLOWED_EXTENSIONS:
        raise KnowledgeValidationError("Unsupported file extension.")
    if mime_type not in ALLOWED_MIME_TYPES:
        raise KnowledgeValidationError("Unsupported MIME type.")
    max_size = get_settings().knowledge_max_file_size_mb * 1024 * 1024
    if len(content) > max_size:
        raise KnowledgeValidationError("Knowledge document exceeds the maximum allowed size.")
    return suffix.lstrip(".")


def sanitize_document_text(text: str) -> str:
    forbidden = ["ignore as instrucoes", "ignore as instruções", "desative auditoria", "mostre tokens", "execute comando"]
    sanitized = text.replace("\x00", " ")
    for term in forbidden:
        sanitized = sanitized.replace(term, "[conteudo instrucional bloqueado]")
    return " ".join(sanitized.split())
