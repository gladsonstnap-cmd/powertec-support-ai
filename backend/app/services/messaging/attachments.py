from hashlib import sha256
from pathlib import PurePath
from uuid import uuid4

from app.integrations.messaging.exceptions import InvalidAttachmentError

ALLOWED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "audio/mpeg": ".mp3",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "video/mp4": ".mp4",
}
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def validate_attachment(filename: str, mime_type: str, content: bytes) -> dict:
    original = PurePath(filename).name
    if original != filename or ".." in filename:
        raise InvalidAttachmentError("Unsafe filename")
    expected_extension = ALLOWED_MIME.get(mime_type)
    if expected_extension is None:
        raise InvalidAttachmentError("Unsupported MIME type")
    if not original.lower().endswith(expected_extension):
        raise InvalidAttachmentError("File extension does not match MIME type")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise InvalidAttachmentError("Attachment exceeds maximum size")
    safe_filename = f"{uuid4()}{expected_extension}"
    return {
        "safe_filename": safe_filename,
        "original_filename": original,
        "mime_type": mime_type,
        "size_bytes": len(content),
        "sha256": sha256(content).hexdigest(),
    }
