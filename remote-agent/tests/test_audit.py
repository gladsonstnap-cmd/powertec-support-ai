from agent.audit import AuditStore


def test_audit_records_sanitized_event(tmp_path):
    store = AuditStore(tmp_path / "audit.sqlite3")
    audit_id = store.record(
        agent_id="agent",
        request_id="request",
        tool_name="system_info",
        arguments={"token": "secret"},
        policy_decision={"allowed": True},
        approval=False,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z",
        result={"ok": True},
        error=None,
        duration_ms=1,
        agent_version="0.1.0",
    )

    events = store.list_events()
    assert events[0]["audit_id"] == audit_id
    assert events[0]["policy_decision"]["allowed"] is True
