import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    NetworkProbePolicy,
    NetworkProbeValidationResult,
    NetworkProbeValidator,
)
from app.services.diagnostic_engine.approval_models import (
    ApprovalActor,
    ApprovalType,
    ApprovedActionGrant,
)
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction,
    ExecutionRisk,
    ExecutionStatus,
    ExecutionTarget,
)
from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeRequest,
    NetworkProbeTarget,
    NetworkProbeType,
)


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
VALIDATOR_FILE = ROOT / "app/services/diagnostic_engine/network_probe_validator.py"
PACKAGE_FILE = VALIDATOR_FILE.with_name("__init__.py")


def action(probe_type=NetworkProbeType.PING, **changes):
    values = dict(
        action_id="action-1",
        action_name="ping_host" if probe_type == NetworkProbeType.PING else "check_port",
        title="Network probe",
        description="Structural diagnostic intention only.",
        target=ExecutionTarget.NETWORK,
        status=ExecutionStatus.READY,
        risk=ExecutionRisk.LOW,
        parameters=(),
        timeout_seconds=5,
        requires_confirmation=True,
        requires_human=False,
        metadata={"action_kind": "read_only", "execution_plan_id": "plan-1"},
    )
    values.update(changes)
    return ExecutionAction(**values)


def grant(item=None, **changes):
    selected = action() if item is None else item
    values = dict(
        grant_id="grant-1",
        approval_id="approval-1",
        execution_plan_id="plan-1",
        action_id=selected.action_id,
        action_snapshot=selected,
        approved_by=ApprovalActor("actor-1", ApprovalType.USER_CONFIRMATION),
        approved_at_monotonic=1,
        expires_at_monotonic=100,
        single_use=True,
        used=False,
        metadata={"session_id": "session-1"},
    )
    values.update(changes)
    return ApprovedActionGrant(**values)


def policy(probe_type=NetworkProbeType.PING, host="8.8.8.8", port=None, **changes):
    values = dict(
        enabled=True,
        allow_ping=probe_type == NetworkProbeType.PING,
        allow_tcp_port_check=probe_type == NetworkProbeType.TCP_PORT_CHECK,
        allowed_hosts=(host,),
        allowed_ports=() if port is None else (port,),
    )
    values.update(changes)
    return NetworkProbePolicy(**values)


def build(probe_type=NetworkProbeType.PING, *, item=None, approved=None,
          configured=None, host="8.8.8.8", port=None, **changes):
    selected = action(probe_type) if item is None else item
    approved = grant(selected) if approved is None else approved
    configured = policy(probe_type, host, port) if configured is None else configured
    values = dict(
        execution_action=selected,
        grant=approved,
        probe_id="probe-1",
        session_id="session-1",
        request_id="request-1",
        probe_type=probe_type,
        host=host,
        port=port,
        created_at_monotonic=10,
    )
    values.update(changes)
    return NetworkProbeValidator(configured).build_request(**values)


def test_default_constructor_uses_deny_policy():
    assert NetworkProbeValidator().policy == NetworkProbePolicy()


def test_none_constructor_uses_default_policy():
    assert NetworkProbeValidator(None).policy == NetworkProbePolicy()


def test_custom_policy_is_preserved():
    configured = policy()
    assert NetworkProbeValidator(configured).policy is configured


def test_validator_and_result_are_frozen():
    with pytest.raises(FrozenInstanceError):
        NetworkProbeValidator().policy = policy()
    with pytest.raises(FrozenInstanceError):
        NetworkProbeValidationResult().success = True


@pytest.mark.parametrize("probe_type,port", [
    (NetworkProbeType.PING, None),
    (NetworkProbeType.TCP_PORT_CHECK, 443),
])
def test_supported_action_mapping_builds_request(probe_type, port):
    result = build(probe_type, port=port)
    assert result.success and result.request.probe_type == probe_type


@pytest.mark.parametrize("name", [
    "ping", "PING_HOST", "ping_host_extra", "check", "check_ports", "restart_service",
    "unsupported", " ping_host", "ping_host ", "network_ping", "tcp_port_check", "unknown",
])
def test_unknown_actions_fail_closed(name):
    result = build(item=action(action_name=name))
    assert not result.success and result.request is None


@pytest.mark.parametrize("name,probe_type", [
    ("ping_host", NetworkProbeType.TCP_PORT_CHECK),
    ("check_port", NetworkProbeType.PING),
])
def test_probe_type_mismatch_is_blocked(name, probe_type):
    item = action(probe_type, action_name=name)
    assert not build(probe_type, item=item, port=443 if probe_type == NetworkProbeType.TCP_PORT_CHECK else None).success


@pytest.mark.parametrize("field,value", [
    ("target", ExecutionTarget.WINDOWS),
    ("target", ExecutionTarget.LOCAL_MACHINE),
    ("target", ExecutionTarget.UNKNOWN),
    ("status", ExecutionStatus.PENDING),
    ("status", ExecutionStatus.BLOCKED),
    ("risk", ExecutionRisk.MEDIUM),
    ("risk", ExecutionRisk.HIGH),
    ("risk", ExecutionRisk.CRITICAL),
])
def test_incompatible_action_contract_is_blocked(field, value):
    assert not build(item=action(**{field: value})).success


@pytest.mark.parametrize("kind", [None, "state_changing", "destructive", "READ_ONLY", "read-only", True])
def test_action_must_be_explicitly_read_only(kind):
    metadata = {"action_kind": kind, "execution_plan_id": "plan-1"}
    assert not build(item=action(metadata=metadata)).success


def test_wrong_action_grant_is_blocked():
    item = action()
    other = action(action_id="other")
    assert not build(item=item, approved=grant(other)).success


def test_wrong_snapshot_is_blocked():
    item = action()
    changed = action(title="changed")
    assert not build(item=item, approved=grant(changed)).success


@pytest.mark.parametrize("plan_binding,grant_plan", [
    (None, "plan-1"), ("", "plan-1"), ("plan-2", "plan-1"),
])
def test_plan_binding_must_match(plan_binding, grant_plan):
    metadata = {"action_kind": "read_only", "execution_plan_id": plan_binding}
    item = action(metadata=metadata)
    approved = grant(item, execution_plan_id=grant_plan)
    assert not build(item=item, approved=approved).success


@pytest.mark.parametrize("used,single_use", [(True, True), (True, False)])
def test_used_grant_is_blocked_when_valid_grant_required(used, single_use):
    item = action()
    assert not build(item=item, approved=grant(item, used=used, single_use=single_use)).success


@pytest.mark.parametrize("expiration,now", [(9, 10), (10, 10), (10.0, 11)])
def test_expired_grant_is_blocked(expiration, now):
    item = action()
    assert not build(item=item, approved=grant(item, expires_at_monotonic=expiration), created_at_monotonic=now).success


@pytest.mark.parametrize("metadata,session", [
    ({}, "session-1"), ({"session_id": ""}, "session-1"),
    ({"session_id": "session-2"}, "session-1"), ({"session_id": "session-1"}, "session-2"),
])
def test_session_binding_is_required(metadata, session):
    item = action()
    assert not build(item=item, approved=grant(item, metadata=metadata), session_id=session).success


def test_grant_is_not_consumed_or_changed():
    item = action()
    approved = grant(item)
    before = deepcopy(approved)
    assert build(item=item, approved=approved).success
    assert approved == before and not approved.used


@pytest.mark.parametrize("changes", [
    {}, {"allow_ping": False}, {"enabled": False},
])
def test_policy_gates_ping(changes):
    configured = policy(**changes)
    result = build(configured=configured)
    assert result.success is (configured.enabled and configured.allow_ping)


def test_default_policy_fails_closed():
    assert not build(configured=NetworkProbePolicy()).success


INVALID_HOSTS = (
    "192.168.1.0/24", "192.168.1.1-254", "192.168.1.*", "host1,host2",
    "host1;host2", "host1 host2", "*", "", " host", "host ", "a..b", "host/path",
)


@pytest.mark.parametrize("host", INVALID_HOSTS)
@pytest.mark.parametrize("probe_type,port", [
    (NetworkProbeType.PING, None),
    (NetworkProbeType.TCP_PORT_CHECK, 443),
])
def test_scanning_and_multi_host_syntax_is_never_interpreted(host, probe_type, port):
    configured = policy(probe_type, "8.8.8.8", port)
    assert not build(probe_type, configured=configured, host=host, port=port).success


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.1.1", "224.0.0.1", "0.0.0.0", "240.0.0.1", "10.0.0.1"])
def test_special_or_private_addresses_are_blocked_by_default(host):
    assert not build(configured=policy(host=host), host=host).success


@pytest.mark.parametrize("host,flag", [
    ("127.0.0.1", "allow_loopback"),
    ("169.254.1.1", "allow_link_local"),
    ("224.0.0.1", "allow_multicast"),
    ("0.0.0.0", "allow_unspecified"),
    ("240.0.0.1", "allow_reserved"),
    ("10.0.0.1", "allow_private_addresses"),
])
def test_special_address_requires_exact_policy_flag(host, flag):
    assert build(configured=policy(host=host, **{flag: True}), host=host).success


def test_limited_broadcast_requires_broadcast_and_reserved_flags():
    host = "255.255.255.255"
    blocked = policy(host=host, allow_reserved=True)
    allowed = policy(host=host, allow_reserved=True, allow_broadcast=True)
    assert not build(configured=blocked, host=host).success
    assert build(configured=allowed, host=host).success


def test_private_ip_is_not_implicitly_allowlisted():
    configured = policy(host="10.0.0.1", allow_private_addresses=True)
    assert not build(configured=configured, host="10.0.0.2").success


@pytest.mark.parametrize("allow_hostnames,allow_dns", [(False, False), (True, False), (False, True)])
def test_hostname_is_blocked_without_both_explicit_flags(allow_hostnames, allow_dns):
    configured = policy(host="server.example", allow_hostnames=allow_hostnames, allow_dns_resolution=allow_dns)
    assert not build(configured=configured, host="server.example").success


def test_structural_hostname_never_gets_resolved_ip():
    configured = policy(host="server.example", allow_hostnames=True, allow_dns_resolution=True)
    result = build(configured=configured, host="server.example")
    assert result.success and result.request.target.resolved_ip is None


INVALID_PORTS = (None, True, False, 0, -1, 65536, "443", "1-1024", "80,443", "*", (), [443])


@pytest.mark.parametrize("port", INVALID_PORTS)
def test_tcp_requires_one_valid_integer_port(port):
    configured = policy(NetworkProbeType.TCP_PORT_CHECK, port=443)
    assert not build(NetworkProbeType.TCP_PORT_CHECK, configured=configured, port=port).success


@pytest.mark.parametrize("port", [1, 53, 80, 443, 8080, 65535])
def test_exact_allowlisted_port_is_allowed(port):
    assert build(NetworkProbeType.TCP_PORT_CHECK, port=port).success


@pytest.mark.parametrize("port", [1, 53, 80, 444, 8080, 65535])
def test_non_allowlisted_port_is_blocked(port):
    configured = policy(NetworkProbeType.TCP_PORT_CHECK, port=443)
    assert not build(NetworkProbeType.TCP_PORT_CHECK, configured=configured, port=port).success


@pytest.mark.parametrize("port", [1, 80, 443, 65535])
def test_ping_rejects_every_port(port):
    configured = policy(allowed_ports=(port,))
    assert not build(configured=configured, port=port).success


@pytest.mark.parametrize("timeout", [0, -1, 5001, True, False, 1.5, "3000"])
def test_invalid_timeout_is_blocked(timeout):
    assert not build(timeout_ms=timeout).success


@pytest.mark.parametrize("timeout", [1, 100, 2999, 3000, 5000])
def test_valid_timeout_is_preserved(timeout):
    result = build(timeout_ms=timeout)
    assert result.success and result.request.timeout_ms == timeout


def test_default_timeout_comes_from_policy():
    result = build(configured=policy(default_timeout_ms=1234))
    assert result.request.timeout_ms == 1234


@pytest.mark.parametrize("attempt", [0, -1, 2, True, False, 1.5, "1"])
def test_invalid_attempt_is_blocked(attempt):
    assert not build(attempt=attempt).success


def test_attempt_one_is_preserved():
    assert build(attempt=1).request.attempt == 1


@pytest.mark.parametrize("count", [0, 1, 8, 9])
def test_session_count_under_limit_is_allowed(count):
    assert build(existing_probe_count=count).success


@pytest.mark.parametrize("count", [10, 11, 100])
def test_session_count_at_or_above_limit_is_blocked(count):
    assert not build(existing_probe_count=count).success


@pytest.mark.parametrize("count", [-1, True, False, 1.5, "0"])
def test_invalid_session_count_is_blocked(count):
    assert not build(existing_probe_count=count).success


def test_dry_run_is_default_and_preserved():
    result = build()
    assert result.success and result.request.dry_run is True


def test_real_probe_is_blocked_by_default():
    assert not build(dry_run=False).success


@pytest.mark.parametrize("probe_type,port", [(NetworkProbeType.PING, None), (NetworkProbeType.TCP_PORT_CHECK, 443)])
def test_fully_enabled_real_probe_builds_structure_only(probe_type, port):
    configured = policy(probe_type, port=port, allow_real_probe=True)
    result = build(probe_type, configured=configured, port=port, dry_run=False)
    assert result.success and result.request.dry_run is False
    assert "no network probe was executed" in result.reasoning[-1].lower()


def test_request_preserves_correlations_and_values():
    result = build(timeout_ms=2000, created_at_monotonic=12.5)
    request = result.request
    assert (request.probe_id, request.session_id, request.request_id) == ("probe-1", "session-1", "request-1")
    assert (request.action_id, request.grant_id) == ("action-1", "grant-1")
    assert request.target == NetworkProbeTarget("8.8.8.8")
    assert (request.timeout_ms, request.attempt, request.created_at_monotonic) == (2000, 1, 12.5)


@pytest.mark.parametrize("field,value", [
    ("probe_id", ""), ("session_id", ""), ("request_id", ""),
    ("created_at_monotonic", -1), ("created_at_monotonic", True),
])
def test_invalid_request_structure_returns_domain_failure(field, value):
    assert not build(**{field: value}).success


def test_only_selected_safe_metadata_reaches_request():
    item = action(metadata={"action_kind": "read_only", "execution_plan_id": "plan-1", "note": "ignored"})
    approved = grant(item, metadata={"session_id": "session-1", "note": "ignored"})
    result = build(item=item, approved=approved)
    assert result.request.metadata == {"approval_id": "approval-1", "execution_plan_id": "plan-1"}


@pytest.mark.parametrize("key,value", [
    ("host", "1.1.1.1"), ("port", 80), ("probe_type", "PING"),
    ("timeout_ms", 1), ("attempt", 1), ("allowed_hosts", ("1.1.1.1",)),
    ("password", "value"), ("authorization", "value"),
])
def test_action_metadata_cannot_expand_scope_or_carry_secrets(key, value):
    metadata = {"action_kind": "read_only", "execution_plan_id": "plan-1", key: value}
    item = action(metadata=metadata)
    assert not build(item=item, approved=grant(item)).success


def test_inputs_are_not_mutated_and_outputs_are_defensive():
    item = action()
    approved = grant(item)
    configured = policy()
    originals = deepcopy((item, approved, configured))
    result = build(item=item, approved=approved, configured=configured)
    result.metadata["changed"] = True
    assert (item, approved, configured) == originals
    assert "changed" not in build(item=item, approved=approved, configured=configured).metadata


def test_validation_result_success_requires_request():
    with pytest.raises(ValueError):
        NetworkProbeValidationResult(success=True)


@pytest.mark.parametrize("forbidden", [
    "socket", "subprocess", "requests", "httpx", "urllib.request", "psutil",
])
def test_forbidden_modules_are_not_imported(forbidden):
    tree = ast.parse(VALIDATOR_FILE.read_text(encoding="utf-8"))
    imports = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert all(name != forbidden and not name.startswith(forbidden + ".") for name in imports)


@pytest.mark.parametrize("forbidden", [
    "getaddrinfo", "gethostbyname", "connect", "connect_ex", "send", "sendto", "recv",
    "ping", "test-netconnection", "powershell", "cmd",
])
def test_forbidden_execution_calls_are_absent(forbidden):
    source = VALIDATOR_FILE.read_text(encoding="utf-8").casefold()
    if forbidden == "ping":
        assert "ping(" not in source
    else:
        assert forbidden not in source


def test_public_exports():
    namespace = {}
    exec("from app.services.diagnostic_engine import NetworkProbeValidator, NetworkProbeValidationResult", namespace)
    assert namespace["NetworkProbeValidator"] is NetworkProbeValidator
    assert namespace["NetworkProbeValidationResult"] is NetworkProbeValidationResult


@pytest.mark.parametrize("path", [VALIDATOR_FILE, HERE, PACKAGE_FILE])
def test_files_are_utf8_without_bom(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    data.decode("utf-8")
