import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    NetworkProbeRateLimitBlockReason,
    NetworkProbeRateLimiter,
    NetworkProbeRateLimitPolicy,
    NetworkProbeRateLimitResult,
)
from app.services.diagnostic_engine.network_probe_audit import (
    NetworkProbeAuditEvent,
    NetworkProbeAuditEventType,
    NetworkProbeAuditTrail,
)
from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeBlockReason,
    NetworkProbeRequest,
    NetworkProbeResult,
    NetworkProbeState,
    NetworkProbeTarget,
    NetworkProbeType,
)


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
RATE_FILE = ROOT / "app/services/diagnostic_engine/network_probe_rate_limit.py"
PACKAGE_FILE = RATE_FILE.with_name("__init__.py")
HOST = "192.0.2.10"


def request(index=1, *, host=HOST, session_id="session-1", dry_run=True,
            action_id="action-1", grant_id="grant-1", created=None):
    return NetworkProbeRequest(
        probe_id=f"probe-{index}", session_id=session_id, request_id=f"request-{index}",
        action_id=action_id, grant_id=grant_id, probe_type=NetworkProbeType.PING,
        target=NetworkProbeTarget(host), timeout_ms=3000, attempt=1,
        dry_run=dry_run, created_at_monotonic=float(index if created is None else created),
    )


def result(index=1, state=NetworkProbeState.SUCCESS, *, started=None, finished=None):
    success = state == NetworkProbeState.SUCCESS
    return NetworkProbeResult(
        probe_id=f"probe-{index}", state=state, success=success,
        block_reason=NetworkProbeBlockReason.VALIDATION_FAILED if state == NetworkProbeState.BLOCKED else None,
        message="structural result",
        started_at_monotonic=float(index if started is None else started),
        finished_at_monotonic=float(index if finished is None else finished),
    )


def event(index=1, event_type=NetworkProbeAuditEventType.REQUEST_CREATED, *, host=HOST, timestamp=None):
    return NetworkProbeAuditEvent(
        event_id=f"event-{index}-{event_type.value}", probe_id=f"blocked-{index}",
        session_id="session-1", request_id=f"blocked-request-{index}", action_id="action-1",
        probe_type=NetworkProbeType.PING, host=host, port=None, event_type=event_type,
        timestamp_monotonic=float(index if timestamp is None else timestamp), message="audit event",
    )


def evaluate(candidate=None, *, policy=None, requests=(), results=(), trail=None, now=100):
    return NetworkProbeRateLimiter(policy).evaluate(
        request=request(99, created=0) if candidate is None else candidate,
        existing_requests=requests,
        existing_results=results,
        audit_trail=trail,
        now_monotonic=now,
    )


@pytest.mark.parametrize("field,expected", [
    ("enabled", True), ("max_probes_per_session", 10), ("max_probes_per_target", 3),
    ("minimum_interval_ms", 1000), ("minimum_same_target_interval_ms", 3000),
    ("block_duplicate_pending_request", True), ("block_duplicate_inflight_probe", True),
    ("count_dry_runs", True), ("count_failed_probes", True),
    ("count_timeouts", True), ("count_blocked_attempts", False), ("fail_closed", True),
])
def test_default_policy_is_conservative(field, expected):
    assert getattr(NetworkProbeRateLimitPolicy(), field) == expected


def test_policy_limiter_and_result_are_frozen():
    with pytest.raises(FrozenInstanceError): NetworkProbeRateLimitPolicy().enabled = False
    with pytest.raises(FrozenInstanceError): NetworkProbeRateLimiter().policy = NetworkProbeRateLimitPolicy()
    with pytest.raises(FrozenInstanceError): NetworkProbeRateLimitResult(True).allowed = False


@pytest.mark.parametrize("field", ["max_probes_per_session", "max_probes_per_target"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "10"])
def test_limits_require_positive_integers(field, value):
    with pytest.raises(ValueError): NetworkProbeRateLimitPolicy(**{field: value})


@pytest.mark.parametrize("field", ["minimum_interval_ms", "minimum_same_target_interval_ms"])
@pytest.mark.parametrize("value", [-1, True, 1.5, "1000"])
def test_cooldowns_require_non_negative_integers(field, value):
    with pytest.raises(ValueError): NetworkProbeRateLimitPolicy(**{field: value})


@pytest.mark.parametrize("field", [
    "enabled", "block_duplicate_pending_request", "block_duplicate_inflight_probe",
    "count_dry_runs", "count_failed_probes", "count_timeouts",
    "count_blocked_attempts", "fail_closed",
])
def test_boolean_policy_fields_require_boolean(field):
    with pytest.raises(ValueError): NetworkProbeRateLimitPolicy(**{field: 1})


def test_target_cooldown_cannot_be_shorter_than_global():
    with pytest.raises(ValueError):
        NetworkProbeRateLimitPolicy(minimum_interval_ms=1001, minimum_same_target_interval_ms=1000)


@pytest.mark.parametrize("member", list(NetworkProbeRateLimitBlockReason))
def test_block_reason_values_are_stable(member):
    assert member.value == member.name


def test_empty_history_is_allowed_with_zero_counts():
    decision = evaluate()
    assert decision.allowed and decision.current_session_count == 0
    assert decision.current_target_count == 0 and decision.block_reason is None


def test_disabled_rate_policy_blocks_fail_closed():
    decision = evaluate(policy=NetworkProbeRateLimitPolicy(enabled=False))
    assert not decision.allowed and decision.block_reason == NetworkProbeRateLimitBlockReason.POLICY_DISABLED


@pytest.mark.parametrize("count", range(0, 10))
def test_session_count_under_limit_is_allowed_when_cooldowns_disabled(count):
    items = tuple(request(index, host=f"192.0.2.{index + 1}", action_id=f"existing-{index}") for index in range(1, count + 1))
    configured = NetworkProbeRateLimitPolicy(minimum_interval_ms=0, minimum_same_target_interval_ms=0)
    decision = evaluate(policy=configured, requests=items)
    assert decision.allowed and decision.current_session_count == count


@pytest.mark.parametrize("count", [10, 11, 12, 20])
def test_session_limit_blocks_at_or_above_limit(count):
    items = tuple(request(index, host=f"192.0.2.{index + 1}") for index in range(1, count + 1))
    configured = NetworkProbeRateLimitPolicy(minimum_interval_ms=0, minimum_same_target_interval_ms=0)
    decision = evaluate(policy=configured, requests=items)
    assert not decision.allowed
    assert decision.block_reason == NetworkProbeRateLimitBlockReason.SESSION_LIMIT_REACHED
    assert decision.current_session_count == count


def test_requests_from_other_session_are_ignored():
    others = tuple(request(index, session_id="session-2") for index in range(1, 11))
    configured = NetworkProbeRateLimitPolicy(minimum_interval_ms=0, minimum_same_target_interval_ms=0)
    decision = evaluate(policy=configured, requests=others)
    assert decision.allowed and decision.current_session_count == 0


@pytest.mark.parametrize("count", [0, 1, 2])
def test_same_target_under_target_limit_is_allowed(count):
    items = tuple(request(index, action_id=f"existing-{index}") for index in range(1, count + 1))
    configured = NetworkProbeRateLimitPolicy(minimum_interval_ms=0, minimum_same_target_interval_ms=0)
    decision = evaluate(policy=configured, requests=items)
    assert decision.allowed and decision.current_target_count == count


@pytest.mark.parametrize("count", [3, 4, 5])
def test_target_limit_blocks_same_target(count):
    items = tuple(request(index) for index in range(1, count + 1))
    configured = NetworkProbeRateLimitPolicy(minimum_interval_ms=0, minimum_same_target_interval_ms=0)
    decision = evaluate(policy=configured, requests=items)
    assert decision.block_reason == NetworkProbeRateLimitBlockReason.TARGET_LIMIT_REACHED


def test_different_target_does_not_increment_candidate_target_count():
    items = tuple(request(index, host="192.0.2.11") for index in range(1, 3))
    configured = NetworkProbeRateLimitPolicy(minimum_interval_ms=0, minimum_same_target_interval_ms=0)
    decision = evaluate(policy=configured, requests=items)
    assert decision.allowed and decision.current_target_count == 0


@pytest.mark.parametrize("elapsed_ms", [0, 1, 500, 999])
def test_global_cooldown_blocks_before_interval(elapsed_ms):
    existing = request(1, host="192.0.2.11", created=10)
    candidate = request(99, host=HOST, created=10 + elapsed_ms / 1000)
    decision = evaluate(candidate, requests=(existing,), now=10 + elapsed_ms / 1000)
    assert decision.block_reason == NetworkProbeRateLimitBlockReason.GLOBAL_COOLDOWN
    assert decision.next_allowed_at_monotonic == 11


@pytest.mark.parametrize("elapsed_ms", [1000, 1001, 2000, 5000])
def test_global_cooldown_allows_at_or_after_boundary(elapsed_ms):
    existing = request(1, host="192.0.2.11", created=10)
    candidate = request(99, host=HOST, created=10 + elapsed_ms / 1000)
    decision = evaluate(candidate, requests=(existing,), now=10 + elapsed_ms / 1000)
    assert decision.allowed


@pytest.mark.parametrize("elapsed_ms", [0, 1, 1000, 2999])
def test_target_cooldown_blocks_same_target_before_interval(elapsed_ms):
    existing = request(1, created=10, action_id="other")
    candidate = request(99, created=10 + elapsed_ms / 1000)
    decision = evaluate(candidate, requests=(existing,), now=10 + elapsed_ms / 1000)
    assert decision.block_reason == NetworkProbeRateLimitBlockReason.TARGET_COOLDOWN
    assert decision.next_allowed_at_monotonic == 13


@pytest.mark.parametrize("elapsed_ms", [3000, 3001, 5000])
def test_target_cooldown_allows_at_boundary(elapsed_ms):
    existing = request(1, created=10, action_id="other")
    candidate = request(99, created=10 + elapsed_ms / 1000)
    decision = evaluate(candidate, requests=(existing,), now=10 + elapsed_ms / 1000)
    assert decision.allowed


def test_equivalent_pending_request_blocks_even_with_different_probe_id():
    existing = request(1, created=1)
    candidate = request(99, created=100)
    decision = evaluate(candidate, requests=(existing,), now=100)
    assert decision.block_reason == NetworkProbeRateLimitBlockReason.DUPLICATE_PENDING_REQUEST


@pytest.mark.parametrize("difference", ["host", "action", "grant", "dry_run"])
def test_non_equivalent_pending_request_does_not_trigger_duplicate(difference):
    values = dict(host=HOST, action_id="action-1", grant_id="grant-1", dry_run=True)
    if difference == "host": values["host"] = "192.0.2.11"
    if difference == "action": values["action_id"] = "action-2"
    if difference == "grant": values["grant_id"] = "grant-2"
    if difference == "dry_run": values["dry_run"] = False
    existing = request(1, created=1, **values)
    configured = NetworkProbeRateLimitPolicy(minimum_interval_ms=0, minimum_same_target_interval_ms=0)
    assert evaluate(request(99, created=100), policy=configured, requests=(existing,), now=100).allowed


def test_duplicate_pending_can_be_explicitly_allowed():
    configured = NetworkProbeRateLimitPolicy(
        block_duplicate_pending_request=False, minimum_interval_ms=0,
        minimum_same_target_interval_ms=0,
    )
    assert evaluate(request(99, created=100), policy=configured, requests=(request(1),), now=100).allowed


@pytest.mark.parametrize("state", [NetworkProbeState.PENDING, NetworkProbeState.VALIDATED])
def test_duplicate_inflight_is_blocked(state):
    existing = request(1, created=1)
    decision = evaluate(request(99, created=100), requests=(existing,), results=(result(1, state),), now=100)
    assert decision.block_reason == NetworkProbeRateLimitBlockReason.DUPLICATE_INFLIGHT_PROBE


@pytest.mark.parametrize("count_dry_runs,expected", [(True, 1), (False, 0)])
def test_dry_run_counting_is_configurable(count_dry_runs, expected):
    configured = NetworkProbeRateLimitPolicy(
        count_dry_runs=count_dry_runs, minimum_interval_ms=0, minimum_same_target_interval_ms=0,
    )
    decision = evaluate(policy=configured, requests=(request(1, action_id="other"),))
    assert decision.current_session_count == expected


@pytest.mark.parametrize("state,flag", [
    (NetworkProbeState.FAILED, "count_failed_probes"),
    (NetworkProbeState.TIMED_OUT, "count_timeouts"),
    (NetworkProbeState.BLOCKED, "count_blocked_attempts"),
])
@pytest.mark.parametrize("enabled", [False, True])
def test_terminal_result_counting_is_configurable(state, flag, enabled):
    configured = replace(
        NetworkProbeRateLimitPolicy(minimum_interval_ms=0, minimum_same_target_interval_ms=0),
        **{flag: enabled},
    )
    existing = request(1, action_id="other")
    decision = evaluate(policy=configured, requests=(existing,), results=(result(1, state),))
    assert decision.current_session_count == int(enabled)


def test_blocked_audit_attempts_are_unique_and_configurable():
    events = (
        event(1, NetworkProbeAuditEventType.RATE_LIMITED),
        event(2, NetworkProbeAuditEventType.COOLDOWN_BLOCKED),
        replace(event(2, NetworkProbeAuditEventType.DUPLICATE_BLOCKED), probe_id="blocked-1"),
    )
    trail = NetworkProbeAuditTrail("session-1", events)
    configured = NetworkProbeRateLimitPolicy(
        count_blocked_attempts=True, minimum_interval_ms=0, minimum_same_target_interval_ms=0,
    )
    decision = evaluate(policy=configured, trail=trail)
    assert decision.current_session_count == 2


@pytest.mark.parametrize("requests,results,trail,now", [
    ([], (), None, 100), ((), [], None, 100), ((), (), "trail", 100),
    ((), (), None, -1), ((), (), None, True),
    ((request(1), request(1)), (), None, 100),
    ((request(1),), (result(2),), None, 100),
])
def test_malformed_history_blocks_fail_closed(requests, results, trail, now):
    decision = evaluate(requests=requests, results=results, trail=trail, now=now)
    assert decision.block_reason == NetworkProbeRateLimitBlockReason.INVALID_HISTORY


def test_audit_session_mismatch_blocks_fail_closed():
    trail = NetworkProbeAuditTrail("session-2")
    assert evaluate(trail=trail).block_reason == NetworkProbeRateLimitBlockReason.INVALID_HISTORY


def test_regressive_and_future_request_timestamps_block_fail_closed():
    regressive = (request(1, created=2), request(2, created=1))
    assert evaluate(requests=regressive, now=100).block_reason == NetworkProbeRateLimitBlockReason.INVALID_HISTORY
    future = (request(1, created=101),)
    assert evaluate(requests=future, now=100).block_reason == NetworkProbeRateLimitBlockReason.INVALID_HISTORY


def test_fail_open_discards_invalid_history_only_when_explicit():
    configured = NetworkProbeRateLimitPolicy(fail_closed=False)
    decision = evaluate(policy=configured, requests=[], now=100)
    assert decision.allowed and decision.current_session_count == 0


def test_inputs_are_not_mutated():
    candidate = request(99, created=100)
    requests = (request(1, host="192.0.2.11"),)
    results = (result(1),)
    trail = NetworkProbeAuditTrail("session-1", (event(1),))
    originals = deepcopy((candidate, requests, results, trail))
    evaluate(candidate, requests=requests, results=results, trail=trail, now=100)
    assert (candidate, requests, results, trail) == originals


@pytest.mark.parametrize("forbidden", [
    "socket", "subprocess", "requests", "httpx", "urllib", "os", "time", "datetime",
])
def test_rate_limiter_has_no_network_sleep_or_clock_imports(forbidden):
    tree = ast.parse(RATE_FILE.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert all(name != forbidden and not name.startswith(forbidden + ".") for name in imports)


@pytest.mark.parametrize("forbidden", ["ping(", "sleep(", "getaddrinfo", "gethostbyname", "connect(", "send("])
def test_rate_limiter_contains_no_network_or_wait_primitive(forbidden):
    assert forbidden not in RATE_FILE.read_text(encoding="utf-8").casefold()


@pytest.mark.parametrize("name", [
    "NetworkProbeRateLimitBlockReason", "NetworkProbeRateLimiter",
    "NetworkProbeRateLimitPolicy", "NetworkProbeRateLimitResult",
])
def test_public_exports(name):
    namespace = {}; exec(f"from app.services.diagnostic_engine import {name}", namespace)
    assert namespace[name].__name__ == name


@pytest.mark.parametrize("path", [RATE_FILE, HERE, PACKAGE_FILE])
def test_files_are_utf8_without_bom(path):
    data = path.read_bytes(); assert not data.startswith(b"\xef\xbb\xbf"); data.decode("utf-8")


@pytest.mark.parametrize("session_limit,target_limit,existing_count", [
    (session_limit, target_limit, existing_count)
    for session_limit in (3, 5, 10)
    for target_limit in (1, 2, 3)
    for existing_count in (0, 1, 2, 3)
])
def test_limit_matrix_is_deterministic(session_limit, target_limit, existing_count):
    configured = NetworkProbeRateLimitPolicy(
        max_probes_per_session=session_limit, max_probes_per_target=target_limit,
        minimum_interval_ms=0, minimum_same_target_interval_ms=0,
    )
    items = tuple(request(index, action_id=f"existing-{index}") for index in range(1, existing_count + 1))
    decision = evaluate(policy=configured, requests=items)
    expected = existing_count < session_limit and existing_count < target_limit
    assert decision.allowed is expected
