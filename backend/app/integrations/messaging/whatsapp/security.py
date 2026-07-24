"""Signature validation stubs for a future official WhatsApp Cloud API integration."""
import hashlib
import hmac


def verify_meta_signature(body: bytes, signature: str | None, app_secret: str | None) -> bool:
    if not app_secret:
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
