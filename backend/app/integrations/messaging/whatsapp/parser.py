from app.integrations.messaging.schemas import NormalizedWebhookMessage


def normalize_meta_webhook(payload: dict) -> list[NormalizedWebhookMessage]:
    messages: list[NormalizedWebhookMessage] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            recipient = metadata.get("display_phone_number") or metadata.get("phone_number_id") or "unknown"
            contacts = {contact.get("wa_id"): (contact.get("profile") or {}).get("name") for contact in value.get("contacts", []) or []}
            for raw_message in value.get("messages", []) or []:
                message_id = raw_message.get("id")
                sender = raw_message.get("from")
                message_type = raw_message.get("type", "unknown")
                if not message_id or not sender:
                    messages.append(
                        NormalizedWebhookMessage(
                            provider="meta",
                            external_message_id=message_id or "unknown",
                            sender=sender or "unknown",
                            recipient=recipient,
                            message_type=message_type,
                            raw_payload=raw_message,
                            supported=False,
                            unsupported_reason="missing required message id or sender",
                        )
                    )
                    continue
                text = None
                supported = message_type == "text"
                reason = None
                if supported:
                    text = (raw_message.get("text") or {}).get("body")
                    if text is None:
                        supported = False
                        reason = "text message without body"
                else:
                    reason = f"unsupported message type: {message_type}"
                messages.append(
                    NormalizedWebhookMessage(
                        provider="meta",
                        external_message_id=message_id,
                        sender=sender,
                        recipient=recipient,
                        message_type=message_type,
                        text=text,
                        timestamp=raw_message.get("timestamp"),
                        contact_name=contacts.get(sender),
                        raw_payload=raw_message,
                        supported=supported,
                        unsupported_reason=reason,
                    )
                )
    return messages
