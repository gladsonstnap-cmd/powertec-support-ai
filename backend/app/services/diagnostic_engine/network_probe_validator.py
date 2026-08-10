"""Fail-closed structural validator for future active network probes.

This module only validates immutable contracts and builds a request.  It never
resolves a name or performs network I/O.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import ipaddress

from app.services.diagnostic_engine.approval_models import ApprovedActionGrant
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
    parse_host,
)
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy


_ACTION_PROBES = {
    "ping_host": NetworkProbeType.PING,
    "check_port": NetworkProbeType.TCP_PORT_CHECK,
}
_SENSITIVE_METADATA_TERMS = (
    "password", "senha", "token", "secret", "segredo", "credential",
    "credencial", "api_key", "authorization", "bearer", "cookie", "private_key",
)
_SCOPE_METADATA_KEYS = {
    "host", "hosts", "port", "ports", "probe_type", "timeout", "timeout_ms",
    "attempt", "allowlist", "allowed_hosts", "allowed_ports", "permissions",
    "resolved_ip", "cidr", "range",
}


@dataclass(frozen=True)
class NetworkProbeValidationResult:
    success: bool = False
    request: NetworkProbeRequest | None = None
    target: NetworkProbeTarget | None = None
    errors: tuple[str, ...] = ()
    reasoning: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("success must be a boolean")
        if self.success and self.request is None:
            raise ValueError("success=True requires a request")
        if self.request is not None and not isinstance(self.request, NetworkProbeRequest):
            raise ValueError("request must be a NetworkProbeRequest or None")
        if self.target is not None and not isinstance(self.target, NetworkProbeTarget):
            raise ValueError("target must be a NetworkProbeTarget or None")
        if self.request is not None and self.target != self.request.target:
            raise ValueError("target must match the request target")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict")
        object.__setattr__(self, "request", deepcopy(self.request))
        object.__setattr__(self, "target", deepcopy(self.target))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))
        object.__setattr__(self, "reasoning", tuple(deepcopy(self.reasoning)))
        object.__setattr__(self, "metadata", deepcopy(self.metadata))


@dataclass(frozen=True)
class NetworkProbeValidator:
    policy: NetworkProbePolicy = field(default_factory=NetworkProbePolicy)

    def __post_init__(self) -> None:
        if self.policy is None:
            object.__setattr__(self, "policy", NetworkProbePolicy())
        elif not isinstance(self.policy, NetworkProbePolicy):
            raise ValueError("policy must be a NetworkProbePolicy")

    def build_request(
        self,
        *,
        execution_action: ExecutionAction,
        grant: ApprovedActionGrant,
        probe_id: str,
        session_id: str,
        request_id: str,
        probe_type: NetworkProbeType,
        host: str,
        port: int | None = None,
        timeout_ms: int | None = None,
        attempt: int = 1,
        dry_run: bool = True,
        created_at_monotonic: float,
        existing_probe_count: int = 0,
    ) -> NetworkProbeValidationResult:
        if not isinstance(execution_action, ExecutionAction):
            return self._failure("execution_action must be an ExecutionAction.")
        if not isinstance(grant, ApprovedActionGrant):
            return self._failure("A valid ApprovedActionGrant is required.")
        if not isinstance(probe_type, NetworkProbeType):
            return self._failure("probe_type must be a NetworkProbeType.")
        if not isinstance(dry_run, bool):
            return self._failure("dry_run must be a boolean.")
        if not self._valid_time(created_at_monotonic):
            return self._failure("created_at_monotonic must be a non-negative number.")
        if not self._valid_count(existing_probe_count):
            return self._failure("existing_probe_count must be a non-negative integer.")
        if existing_probe_count >= self.policy.max_probes_per_session:
            return self._failure("The session probe limit has been reached.")

        error = self._action_error(execution_action, probe_type)
        if error:
            return self._failure(error)
        metadata_error = self._metadata_error(execution_action.metadata, grant.metadata)
        if metadata_error:
            return self._failure(metadata_error)
        error = self._grant_error(execution_action, grant, session_id, created_at_monotonic)
        if error:
            return self._failure(error)
        if not self.policy.enabled:
            return self._failure("The network probe policy is disabled.")
        if not self.policy.is_probe_type_allowed(probe_type):
            return self._failure(f"Probe type {probe_type.value} is blocked by policy.")

        try:
            target = NetworkProbeTarget(host=host, port=port)
        except (TypeError, ValueError) as exc:
            return self._failure(str(exc))
        _, parsed_host = parse_host(target.host)
        if (
            isinstance(parsed_host, ipaddress.IPv4Address)
            and parsed_host == ipaddress.IPv4Address("255.255.255.255")
            and not self.policy.allow_broadcast
        ):
            return self._failure("Target blocked: BROADCAST_BLOCKED.", target=target)
        target_error = self.policy.validate_target(target)
        if target_error is not None:
            return self._failure(f"Target blocked: {target_error.value}.", target=target)
        if probe_type == NetworkProbeType.PING and port is not None:
            return self._failure("PING must not include a port.", target=target)
        if probe_type == NetworkProbeType.TCP_PORT_CHECK:
            if port is None:
                return self._failure("TCP_PORT_CHECK requires a port.", target=target)
            if not self.policy.is_port_allowed(port):
                return self._failure("The port is invalid or is not in the explicit allowlist.", target=target)

        timeout = self.policy.default_timeout_ms if timeout_ms is None else timeout_ms
        if not self.policy.validate_timeout(timeout):
            return self._failure("timeout_ms is outside the policy limits.", target=target)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or not 1 <= attempt <= self.policy.max_attempts_per_probe:
            return self._failure("attempt is outside the policy limits.", target=target)

        safe_metadata = {
            "approval_id": grant.approval_id,
            "execution_plan_id": grant.execution_plan_id,
        }
        try:
            request = NetworkProbeRequest(
                probe_id=probe_id,
                session_id=session_id,
                request_id=request_id,
                action_id=execution_action.action_id,
                grant_id=grant.grant_id,
                probe_type=probe_type,
                target=target,
                timeout_ms=timeout,
                attempt=attempt,
                dry_run=dry_run,
                created_at_monotonic=created_at_monotonic,
                metadata=safe_metadata,
            )
        except (TypeError, ValueError) as exc:
            return self._failure(str(exc), target=target)

        if not dry_run and not self.policy.can_execute_real_probe(
            request,
            approval_granted=True,
            grant_valid=True,
            session_matches=True,
        ):
            return self._failure("The policy blocks real probes.", target=target)
        return NetworkProbeValidationResult(
            success=True,
            request=request,
            target=target,
            reasoning=(
                "The action and grant snapshots match.",
                "The destination is explicitly authorized by policy.",
                "The request is structural only; no network probe was executed.",
            ),
            metadata={"validation": "structural_only"},
        )

    @staticmethod
    def _action_error(action: ExecutionAction, probe_type: NetworkProbeType) -> str | None:
        expected = _ACTION_PROBES.get(action.action_name)
        if expected is None:
            return "The action is not a supported network probe intention."
        if expected != probe_type:
            return "The probe type does not exactly match the action name."
        if action.target != ExecutionTarget.NETWORK:
            return "ExecutionAction target must be NETWORK."
        if action.status != ExecutionStatus.READY:
            return "ExecutionAction status must be READY."
        if action.risk != ExecutionRisk.LOW:
            return "Only LOW-risk diagnostic probes are supported."
        if action.metadata.get("action_kind") != "read_only":
            return "The action must be explicitly classified as read_only."
        return None

    def _grant_error(
        self,
        action: ExecutionAction,
        grant: ApprovedActionGrant,
        session_id: object,
        now: float,
    ) -> str | None:
        if grant.action_id != action.action_id:
            return "The grant does not correspond to the action."
        bound_plan = action.metadata.get("execution_plan_id")
        if not isinstance(bound_plan, str) or not bound_plan.strip():
            return "The action has no reliable execution_plan_id binding."
        if bound_plan != grant.execution_plan_id:
            return "The grant execution_plan_id does not match the action."
        if not grant.execution_plan_id.strip() or not grant.approval_id.strip():
            return "The grant identifiers are invalid."
        if grant.action_snapshot != action:
            return "The grant snapshot does not match the action."
        if self.policy.require_valid_grant:
            if grant.used:
                return "The grant was already used."
            if grant.expires_at_monotonic is not None and now >= grant.expires_at_monotonic:
                return "The grant expired."
        elif grant.single_use and grant.used:
            return "The single-use grant was already used."
        if self.policy.require_session_match:
            if not isinstance(session_id, str) or not session_id.strip():
                return "session_id must be explicitly provided."
            bound_session = grant.metadata.get("session_id")
            if not isinstance(bound_session, str) or not bound_session.strip():
                return "The grant has no reliable session_id binding."
            if bound_session != session_id:
                return "The grant session_id does not match."
        return None

    @classmethod
    def _metadata_error(
        cls,
        action_metadata: dict[str, object],
        grant_metadata: dict[str, object],
    ) -> str | None:
        def prohibited(value: object, key: str = "") -> bool:
            normalized = key.strip().casefold()
            if any(term in normalized for term in _SENSITIVE_METADATA_TERMS):
                return True
            if normalized in _SCOPE_METADATA_KEYS:
                return True
            if isinstance(value, dict):
                return any(prohibited(item, str(item_key)) for item_key, item in value.items())
            if isinstance(value, (list, tuple, set)):
                return any(prohibited(item) for item in value)
            if isinstance(value, str):
                lowered = value.casefold()
                return any(term in lowered for term in _SENSITIVE_METADATA_TERMS)
            return False

        if prohibited(action_metadata) or prohibited(grant_metadata):
            return "Metadata contains sensitive or scope-expanding data."
        return None

    @staticmethod
    def _valid_time(value: object) -> bool:
        return isinstance(value, int | float) and not isinstance(value, bool) and value >= 0

    @staticmethod
    def _valid_count(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    @staticmethod
    def _failure(
        message: str,
        *,
        target: NetworkProbeTarget | None = None,
    ) -> NetworkProbeValidationResult:
        return NetworkProbeValidationResult(
            success=False,
            target=target,
            errors=(message,),
            reasoning=("Validation failed closed; no network probe was executed.",),
            metadata={"validation": "structural_only"},
        )
