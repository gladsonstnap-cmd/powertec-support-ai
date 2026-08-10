import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    NetworkProbeAuditEvent,
    NetworkProbeAuditEventType,
    NetworkProbeAuditTrail,
    append_event,
)
from app.services.diagnostic_engine.network_probe_models import NetworkProbeType


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
AUDIT_FILE = ROOT / "app/services/diagnostic_engine/network_probe_audit.py"
PACKAGE_FILE = AUDIT_FILE.with_name("__init__.py")


def event(index=1, event_type=NetworkProbeAuditEventType.REQUEST_CREATED, **changes):
    values = dict(
        event_id=f"event-{index}", probe_id=f"probe-{index}", session_id="session-1",
        request_id=f"request-{index}", action_id="action-1", probe_type=NetworkProbeType.PING,
        host="192.0.2.10", port=None, event_type=event_type,
        timestamp_monotonic=float(index), message="Evento estrutural de probe.",
        metadata={"source": "test"},
    )
    values.update(changes)
    return NetworkProbeAuditEvent(**values)


@pytest.mark.parametrize("member", list(NetworkProbeAuditEventType))
def test_event_type_has_stable_string_value(member):
    assert member.value == member.name


@pytest.mark.parametrize("event_type", list(NetworkProbeAuditEventType))
@pytest.mark.parametrize("host", ["192.0.2.10", "203.0.113.1", "2001:db8::1", "TEST.INVALID"])
def test_event_construction_for_each_type_and_structural_host(event_type, host):
    item = event(event_type=event_type, host=host)
    assert item.event_type is event_type and item.host == host.casefold()


@pytest.mark.parametrize("field", ["event_id", "probe_id", "session_id", "request_id", "action_id", "message"])
@pytest.mark.parametrize("value", ["", " "])
def test_text_fields_reject_empty_or_whitespace(field, value):
    with pytest.raises(ValueError):
        event(**{field: value})


@pytest.mark.parametrize("timestamp", [-1, True, False, "1", None, object()])
def test_timestamp_must_be_non_negative_monotonic_number(timestamp):
    with pytest.raises(ValueError):
        event(timestamp_monotonic=timestamp)


@pytest.mark.parametrize("timestamp", [0, 0.0, 1, 1.5, 999999])
def test_valid_timestamp_is_preserved(timestamp):
    assert event(timestamp_monotonic=timestamp).timestamp_monotonic == timestamp


@pytest.mark.parametrize("host", [
    "", " host", "host ", "192.0.2.0/24", "192.0.2.1-254", "192.0.2.*",
    "host1,host2", "host1;host2", "host1 host2", "*",
])
def test_audit_never_accepts_expanding_host_syntax(host):
    with pytest.raises(ValueError):
        event(host=host)


@pytest.mark.parametrize("port", [0, -1, 1, 80, 443, 65535, 65536, True, "443"])
def test_ping_event_rejects_every_port(port):
    with pytest.raises(ValueError):
        event(port=port)


@pytest.mark.parametrize("key", [
    "password", "senha", "token", "secret", "credential", "api_key", "authorization",
    "bearer", "cookie", "private_key", "username", "environment", "command_line",
    "stack", "traceback", "host", "port", "limit", "cooldown", "policy",
    "probe_type", "counts", "max_probes_per_session", "max_probes_per_target",
    "minimum_interval_ms",
])
def test_metadata_rejects_sensitive_or_control_keys(key):
    with pytest.raises(ValueError):
        event(metadata={key: "value"})


@pytest.mark.parametrize("metadata", [
    {"source": "test"}, {"nested": {"safe": 1}}, {"values": [1, 2]},
    {"flag": True}, {}, {"code": "RATE_LIMITED"},
])
def test_safe_metadata_is_defensively_copied(metadata):
    original = deepcopy(metadata)
    item = event(metadata=metadata)
    assert item.metadata is not metadata
    assert metadata == original
    if "values" in metadata:
        assert item.metadata["values"] == tuple(metadata["values"])
    else:
        assert item.metadata == original


def test_event_and_trail_are_frozen():
    item = event()
    trail = NetworkProbeAuditTrail("session-1", (item,))
    with pytest.raises(FrozenInstanceError): item.message = "changed"
    with pytest.raises(FrozenInstanceError): trail.events = ()


def test_empty_trail_is_valid_and_immutable_tuple():
    trail = NetworkProbeAuditTrail("session-1")
    assert trail.events == () and isinstance(trail.events, tuple)


def test_trail_orders_equal_timestamps_by_event_id():
    second = event(2, timestamp_monotonic=1, event_id="event-b")
    first = event(1, timestamp_monotonic=1, event_id="event-a")
    trail = NetworkProbeAuditTrail("session-1", (second, first))
    assert tuple(item.event_id for item in trail.events) == ("event-a", "event-b")


def test_trail_rejects_regressive_timestamps():
    with pytest.raises(ValueError, match="regress"):
        NetworkProbeAuditTrail("session-1", (event(1, timestamp_monotonic=2), event(2, timestamp_monotonic=1)))


def test_trail_rejects_duplicate_event_ids():
    with pytest.raises(ValueError, match="unique"):
        NetworkProbeAuditTrail("session-1", (event(1), event(2, event_id="event-1")))


def test_trail_rejects_event_from_other_session():
    with pytest.raises(ValueError, match="session"):
        NetworkProbeAuditTrail("session-1", (event(session_id="session-2"),))


@pytest.mark.parametrize("events", [[], {}, "events", None, 1])
def test_trail_requires_tuple(events):
    with pytest.raises(ValueError):
        NetworkProbeAuditTrail("session-1", events)


def test_append_returns_new_trail_and_preserves_original():
    original = NetworkProbeAuditTrail("session-1", (event(1),))
    appended = append_event(original, event(2))
    assert len(original.events) == 1 and len(appended.events) == 2
    assert appended.events[0] == original.events[0]


def test_append_rejects_duplicate_regressive_and_other_session_events():
    original = NetworkProbeAuditTrail("session-1", (event(1),))
    with pytest.raises(ValueError): append_event(original, event(2, event_id="event-1"))
    with pytest.raises(ValueError): append_event(original, event(2, timestamp_monotonic=0))
    with pytest.raises(ValueError): append_event(original, event(2, session_id="session-2"))


@pytest.mark.parametrize("invalid", [None, object(), "trail", 1])
def test_append_rejects_invalid_trail(invalid):
    with pytest.raises(ValueError): append_event(invalid, event())


@pytest.mark.parametrize("invalid", [None, object(), "event", 1])
def test_append_rejects_invalid_event(invalid):
    with pytest.raises(ValueError): append_event(NetworkProbeAuditTrail("session-1"), invalid)


def test_multiple_probe_events_remain_deterministic():
    events = tuple(event(index) for index in range(1, 11))
    trail = NetworkProbeAuditTrail("session-1", events)
    assert trail.events == events
    assert len({item.probe_id for item in trail.events}) == 10


@pytest.mark.parametrize("forbidden", ["socket", "subprocess", "requests", "httpx", "urllib", "os", "time"])
def test_audit_module_has_no_network_or_clock_imports(forbidden):
    tree = ast.parse(AUDIT_FILE.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert all(name != forbidden and not name.startswith(forbidden + ".") for name in imports)


@pytest.mark.parametrize("path", [AUDIT_FILE, HERE, PACKAGE_FILE])
def test_files_are_utf8_without_bom(path):
    data = path.read_bytes(); assert not data.startswith(b"\xef\xbb\xbf"); data.decode("utf-8")
