from agent.registry import build_registry, get_tool


def test_registry_contains_only_allowlisted_tools():
    registry = build_registry()

    assert set(registry) == {"system_info", "disk_health", "network_test", "service_status", "event_logs", "windows_update_status"}
    assert registry["system_info"].risk_level.value == "read_only"


def test_unknown_tool_is_not_registered():
    try:
        get_tool("powershell")
    except KeyError as exc:
        assert "Unknown tool" in str(exc)
    else:
        raise AssertionError("unknown tool should fail")
