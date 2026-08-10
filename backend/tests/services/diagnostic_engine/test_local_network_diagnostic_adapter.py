import ast
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.diagnostic_engine import LocalNetworkDiagnosticAdapter
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalOperationArgument, LocalOperationType,
    LocalRawExecutionResult, LocalSandboxPolicy, LocalSanitizedResult, OutputStreamType,
)
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ADAPTER_FILE = ROOT / "app/services/diagnostic_engine/local_network_diagnostic_adapter.py"
PACKAGE_FILE = ADAPTER_FILE.with_name("__init__.py")
DRY_MESSAGE = "Dry-run: operação de configuração de rede validada; nenhuma consulta real foi realizada."


def contract(*, dry_run=True, sandbox=None):
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1",
        execution_plan_id="plan-1", action_id="action-1", grant_id="grant-1",
        operation_name="check_network_configuration", command_id="command-1",
        dry_run=dry_run, sandbox_policy=sandbox,
    )


def family(name, value):
    return SimpleNamespace(name=name, value=value)


def address(family_value, value, netmask=None, **extra):
    return SimpleNamespace(family=family_value, address=value, netmask=netmask, **extra)


def stat(isup=True, mtu=1500, **extra):
    return SimpleNamespace(isup=isup, mtu=mtu, **extra)


_UNSET = object()


class FakeBackend:
    def __init__(self, addresses=_UNSET, stats=_UNSET, addrs_error=None, stats_error=None):
        self.addresses = {} if addresses is _UNSET else addresses
        self.stats = {} if stats is _UNSET else stats
        self.addrs_error = addrs_error
        self.stats_error = stats_error
        self.calls = []

    def net_if_addrs(self):
        self.calls.append("net_if_addrs")
        if self.addrs_error:
            raise self.addrs_error
        return self.addresses

    def net_if_stats(self):
        self.calls.append("net_if_stats")
        if self.stats_error:
            raise self.stats_error
        return self.stats


def execute_real(monkeypatch, *, addresses=_UNSET, stats=_UNSET, addrs_error=None,
                 stats_error=None, sandbox=None):
    backend = FakeBackend(addresses, stats, addrs_error, stats_error)
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_network_diagnostic_adapter._network_backend",
        backend,
    )
    result = LocalNetworkDiagnosticAdapter().execute(
        contract(dry_run=False, sandbox=sandbox), 10
    )
    return backend, result


def payload(result):
    return json.loads(result.stdout)


def test_adapter_is_public_frozen_and_stateless():
    first = LocalNetworkDiagnosticAdapter(); second = LocalNetworkDiagnosticAdapter()
    assert first == second and first is not second and vars(first) == {}
    with pytest.raises(FrozenInstanceError):
        first.MAX_INTERFACES = 1


def test_dry_run_succeeds_without_backend(monkeypatch):
    class ForbiddenBackend:
        def __getattr__(self, name):
            raise AssertionError("backend must not be called")
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_network_diagnostic_adapter._network_backend",
        ForbiddenBackend(),
    )
    result = LocalNetworkDiagnosticAdapter().execute(contract(), 10)
    assert result.state == LocalExecutionState.SUCCESS and result.stdout == DRY_MESSAGE
    assert result.started_at_monotonic == result.finished_at_monotonic == 10
    assert result.exit_code == 0 and result.stderr == ""
    assert len(result.output_chunks) == 1
    assert result.output_chunks[0].stream == OutputStreamType.STDOUT
    assert result.output_chunks[0].content == DRY_MESSAGE


def test_backend_absent_real_execution_has_exact_failure(monkeypatch):
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_network_diagnostic_adapter._network_backend", None
    )
    result = LocalNetworkDiagnosticAdapter().execute(contract(dry_run=False), 10)
    assert result.state == LocalExecutionState.FAILED
    assert result.stderr == "Backend seguro de configuração de rede indisponível."
    assert result.stdout == "" and result.output_chunks == ()


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("name", [
    "ping_host", "check_port", "validate_configuration", "list_processes",
    "read_system_information", "unknown",
])
def test_wrong_operations_fail_closed(field, name):
    item = contract(); object.__setattr__(getattr(item, field), "operation_name", name)
    assert LocalNetworkDiagnosticAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("adapter_type", [
    LocalAdapterType.UNKNOWN, LocalAdapterType.SYSTEM_INFORMATION,
    LocalAdapterType.DISK_INFORMATION, LocalAdapterType.PROCESS,
    LocalAdapterType.WINDOWS_EVENT_LOG, LocalAdapterType.WINDOWS_SERVICE,
])
def test_wrong_adapter_types_fail_closed(field, adapter_type):
    item = contract(); object.__setattr__(getattr(item, field), "adapter_type", adapter_type)
    assert LocalNetworkDiagnosticAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("target", [
    ExecutionTarget.WINDOWS, ExecutionTarget.LOCAL_MACHINE, ExecutionTarget.LINUX,
    ExecutionTarget.REMOTE_AGENT, ExecutionTarget.UNKNOWN,
])
def test_wrong_targets_fail_closed(target):
    item = contract(); object.__setattr__(item.command, "target", target)
    assert LocalNetworkDiagnosticAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_wrong_risks_fail_closed(risk):
    item = contract(); object.__setattr__(item.command, "risk", risk)
    assert LocalNetworkDiagnosticAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("kind", [LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE])
def test_non_read_only_types_fail_closed(field, kind):
    item = contract(); object.__setattr__(getattr(item, field), "operation_type", kind)
    assert LocalNetworkDiagnosticAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("state", [
    LocalExecutionState.VALIDATED, LocalExecutionState.READY, LocalExecutionState.BLOCKED,
    LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS, LocalExecutionState.FAILED,
    LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_only_pending_state_is_accepted(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert LocalNetworkDiagnosticAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("timeout", [0, -1, 31, 61, True, "30", None])
def test_invalid_timeouts_fail_closed(timeout):
    item = contract(); object.__setattr__(item.command, "timeout_seconds", timeout)
    assert LocalNetworkDiagnosticAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("now", [-1, True, "10", None, object()])
def test_invalid_monotonic_values_fail_closed(now):
    assert LocalNetworkDiagnosticAdapter().execute(contract(), now).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field", [
    "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
    "allow_network_access", "allow_filesystem_write", "allow_registry_write",
    "allow_service_state_change", "allow_process_termination", "allow_elevation",
    "allow_child_processes",
])
def test_unsafe_sandbox_fails_closed(field):
    item = contract(sandbox=replace(LocalSandboxPolicy(), **{field: True}))
    assert LocalNetworkDiagnosticAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("argument", [
    LocalOperationArgument("interface", "Ethernet"),
    LocalOperationArgument("host", "localhost"),
    LocalOperationArgument("port", 80),
])
def test_any_argument_fails_closed(argument):
    item = contract(); object.__setattr__(item.command, "arguments", (argument,))
    assert LocalNetworkDiagnosticAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("addresses,stats", [({}, {}), ({"Ethernet": []}, {}), ({}, {"Ethernet": stat()})])
def test_empty_and_partial_backend_data_is_safe(monkeypatch, addresses, stats):
    backend, result = execute_real(monkeypatch, addresses=addresses, stats=stats)
    data = payload(result)
    assert result.state == LocalExecutionState.SUCCESS
    assert data["operation"] == "check_network_configuration"
    assert data["address_count"] == 0
    assert backend.calls == ["net_if_addrs", "net_if_stats"]


@pytest.mark.parametrize("is_up,mtu", [(True, 1500), (False, 0), (True, 9000), (False, 1280)])
def test_interface_state_and_mtu_are_projected(monkeypatch, is_up, mtu):
    addresses = {"Ethernet": [address(family("AF_INET", 2), "10.0.0.2", "255.255.255.0")]}
    _, result = execute_real(monkeypatch, addresses=addresses, stats={"Ethernet": stat(is_up, mtu)})
    interface = payload(result)["interfaces"][0]
    assert interface["interface_name"] == "Ethernet"
    assert interface["is_up"] is is_up and interface["mtu"] == mtu


@pytest.mark.parametrize("family_value,expected", [
    (family("AF_INET", 2), "ipv4"), (family("AF_INET6", 23), "ipv6"),
    (family("", 2), "ipv4"), (family("", 10), "ipv6"),
    (family("", 23), "ipv6"), (2, "ipv4"), (10, "ipv6"), (23, "ipv6"),
])
def test_ipv4_and_ipv6_families_are_normalized(monkeypatch, family_value, expected):
    addresses = {"if0": [address(family_value, "2001:db8::1" if expected == "ipv6" else "10.0.0.1")]}
    _, result = execute_real(monkeypatch, addresses=addresses, stats={"if0": stat()})
    assert payload(result)["interfaces"][0]["addresses"][0]["address_family"] == expected


@pytest.mark.parametrize("family_value", [
    family("AF_LINK", -1), family("AF_PACKET", 17), family("UNKNOWN", 999), -1, 17, 999, None,
])
def test_mac_and_unknown_families_are_omitted(monkeypatch, family_value):
    addresses = {"if0": [address(family_value, "AA-BB-CC-DD-EE-FF")]}
    _, result = execute_real(monkeypatch, addresses=addresses, stats={"if0": stat()})
    assert payload(result)["interfaces"][0]["addresses"] == []
    assert "AA-BB" not in result.stdout


def test_interfaces_and_addresses_are_sorted(monkeypatch):
    addresses = {
        "zeta": [address(family("AF_INET6", 23), "fe80::2"), address(family("AF_INET", 2), "10.0.0.2")],
        "Alpha": [address(family("AF_INET", 2), "10.0.0.1")],
    }
    stats = {"zeta": stat(), "Alpha": stat(False, 1400)}
    _, result = execute_real(monkeypatch, addresses=addresses, stats=stats)
    data = payload(result)
    assert [item["interface_name"] for item in data["interfaces"]] == ["Alpha", "zeta"]
    assert [item["address_family"] for item in data["interfaces"][1]["addresses"]] == ["ipv4", "ipv6"]


def test_interface_limit_is_enforced_deterministically(monkeypatch):
    addresses = {f"if-{index:03}": [] for index in range(LocalNetworkDiagnosticAdapter.MAX_INTERFACES + 10)}
    stats = {name: stat() for name in addresses}
    _, result = execute_real(monkeypatch, addresses=addresses, stats=stats)
    data = payload(result)
    assert data["interface_count"] == LocalNetworkDiagnosticAdapter.MAX_INTERFACES
    assert data["interfaces"][0]["interface_name"] == "if-000"


def test_address_limit_is_enforced(monkeypatch):
    records = [address(family("AF_INET", 2), f"10.0.{index // 255}.{index % 255}") for index in range(300)]
    _, result = execute_real(monkeypatch, addresses={"if0": records}, stats={"if0": stat()})
    data = payload(result)
    assert data["address_count"] == LocalNetworkDiagnosticAdapter.MAX_ADDRESSES


@pytest.mark.parametrize("bad_addresses,bad_stats", [
    (None, {}), ([], {}), ("bad", {}), ({}, None), ({}, []), ({}, "bad"),
    (1, {}), ({}, 1), (object(), {}),
])
def test_malformed_global_backend_data_fails_generically(monkeypatch, bad_addresses, bad_stats):
    _, result = execute_real(monkeypatch, addresses=bad_addresses, stats=bad_stats)
    assert result.state == LocalExecutionState.FAILED
    assert result.stderr == "Falha ao consultar configuração de rede."


@pytest.mark.parametrize("error", [RuntimeError("secret stack"), ValueError("private path"), OSError("hostname")])
@pytest.mark.parametrize("stage", ["addresses", "stats"])
def test_backend_exceptions_are_generic_and_leak_free(monkeypatch, error, stage):
    values = {"addrs_error": error} if stage == "addresses" else {"stats_error": error}
    _, result = execute_real(monkeypatch, **values)
    assert result.stderr == "Falha ao consultar configuração de rede."
    assert "secret" not in result.stderr and "private" not in result.stderr


def test_only_allowlisted_fields_are_emitted(monkeypatch):
    record = address(
        family("AF_INET", 2), "10.0.0.1", "255.255.255.0",
        broadcast="10.0.0.255", ptp=None, hostname="secret", username="private",
    )
    _, result = execute_real(
        monkeypatch, addresses={"if0": [record]},
        stats={"if0": stat(True, 1500, speed=1000, duplex=2)},
    )
    interface = payload(result)["interfaces"][0]
    assert set(interface) == {"addresses", "interface_name", "is_up", "mtu"}
    assert set(interface["addresses"][0]) == {"address", "address_family", "netmask"}
    for forbidden in ("hostname", "username", "broadcast", "speed", "duplex", "mac", "ssid", "bssid"):
        assert forbidden not in result.stdout.lower()


def test_sanitize_redacts_paths_and_all_secret_labels_without_backend_call():
    text = (
        r'C:\Users\Private \\server\share /home/private/file '
        "password=p token=t secret=s api_key=k authorization=a cookie=c"
    )
    source = LocalRawExecutionResult(
        command_id="command-1", state=LocalExecutionState.FAILED,
        started_at_monotonic=1, finished_at_monotonic=1, exit_code=None,
        stdout=text, stderr=text, output_chunks=(), timed_out=False, cancelled=False,
        errors=("generic",), metadata={"max_output_bytes": 4096},
    )
    before = deepcopy(source); result = LocalNetworkDiagnosticAdapter().sanitize(source)
    assert source == before and isinstance(result, LocalSanitizedResult)
    for leaked in ("Private", "server", "password=p", "token=t", "secret=s", "api_key=k", "authorization=a", "cookie=c"):
        assert leaked not in result.stdout_summary
    assert result.redactions


@pytest.mark.parametrize("limit", [1, 5, 16, 32, 64, 128, 256])
def test_sanitize_truncates_utf8_safely_and_counts_bytes(limit):
    source = LocalRawExecutionResult(
        command_id="command-1", state=LocalExecutionState.SUCCESS,
        started_at_monotonic=1, finished_at_monotonic=1, exit_code=0,
        stdout="interface-ção-" * 40, stderr="", output_chunks=(),
        timed_out=False, cancelled=False, metadata={"max_output_bytes": limit},
    )
    result = LocalNetworkDiagnosticAdapter().sanitize(source)
    assert result.output_bytes <= limit and result.truncated
    result.stdout_summary.encode("utf-8")


@pytest.mark.parametrize("invalid", [None, object(), "raw", 1, True])
def test_sanitize_rejects_invalid_inputs(invalid):
    with pytest.raises(ValueError, match="raw_result"):
        LocalNetworkDiagnosticAdapter().sanitize(invalid)


@pytest.mark.parametrize("subject", ["contract", "operation", "command", "arguments", "sandbox", "metadata"])
def test_execute_does_not_mutate_contract_graph(subject):
    item = contract()
    selected = {
        "contract": item, "operation": item.operation, "command": item.command,
        "arguments": item.command.arguments, "sandbox": item.sandbox_policy,
        "metadata": item.metadata,
    }[subject]
    before = deepcopy(selected); LocalNetworkDiagnosticAdapter().execute(item, 10)
    assert selected == before


@pytest.mark.parametrize("name", ["subprocess", "requests", "httpx", "aiohttp", "socket", "urllib"])
def test_adapter_has_no_forbidden_imports(name):
    tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "net_connections", "socket.connect", "create_connection", ".send(", ".sendto(",
    ".recv(", "requests.", "httpx.", "aiohttp.", "urllib.", "os.system",
    "subprocess", "powershell", "cmd.exe", "ipconfig", "netsh", "wmic", " wmi",
    "ping_host", "check_port", "tracert", "traceroute", "nslookup",
    "resolve-dnsname", "test-netconnection", "set_ip", "set_dns", "set_gateway",
    "enable_adapter", "disable_adapter", "renew_dhcp", "release_dhcp", "flush_dns",
    "add_route", "delete_route", "firewall", "proxy modification", "vpn modification",
])
def test_adapter_has_no_active_probe_shell_or_mutation(text):
    assert text not in ADAPTER_FILE.read_text(encoding="utf-8").lower()


def test_operation_set_is_exact_and_immutable():
    assert LocalNetworkDiagnosticAdapter.operation_names == frozenset({"check_network_configuration"})


@pytest.mark.parametrize("path", [ADAPTER_FILE, PACKAGE_FILE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf")
    content.decode("utf-8")
