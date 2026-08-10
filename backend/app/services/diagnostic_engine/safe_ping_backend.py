"""Minimal single-attempt ICMP backend using the Windows IP Helper API.

No shell, subprocess, DNS lookup, raw socket, retry, or host expansion is used.
"""

import ctypes
import ipaddress
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.services.diagnostic_engine.safe_ping_adapter import PingBackendResult


_IP_SUCCESS = 0
_IP_REQ_TIMED_OUT = 11010
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


@dataclass(frozen=True)
class _PingTransportResult:
    success: bool = False
    timed_out: bool = False
    latency_ms: float | None = None
    remote_ip: str | None = None
    unavailable: bool = False


@runtime_checkable
class _PingTransportProtocol(Protocol):
    def probe(self, *, host: str, timeout_ms: int) -> _PingTransportResult: ...


class _IpOptionInformation(ctypes.Structure):
    _fields_ = [
        ("ttl", ctypes.c_ubyte),
        ("tos", ctypes.c_ubyte),
        ("flags", ctypes.c_ubyte),
        ("options_size", ctypes.c_ubyte),
        ("options_data", ctypes.c_void_p),
    ]


class _IcmpEchoReply(ctypes.Structure):
    _fields_ = [
        ("address", ctypes.c_ulong),
        ("status", ctypes.c_ulong),
        ("round_trip_time", ctypes.c_ulong),
        ("data_size", ctypes.c_ushort),
        ("reserved", ctypes.c_ushort),
        ("data", ctypes.c_void_p),
        ("options", _IpOptionInformation),
    ]


@dataclass(frozen=True)
class _WindowsIcmpTransport:
    """One-call IPv4 transport over documented Windows IP Helper functions."""

    def probe(self, *, host: str, timeout_ms: int) -> _PingTransportResult:
        address = ipaddress.ip_address(host)
        if not isinstance(address, ipaddress.IPv4Address):
            return _PingTransportResult(unavailable=True)
        loader = getattr(ctypes, "windll", None)
        if loader is None:
            return _PingTransportResult(unavailable=True)
        try:
            api = loader.iphlpapi
            create = api.IcmpCreateFile
            send_echo = api.IcmpSendEcho
            close = api.IcmpCloseHandle
            create.argtypes = []
            create.restype = ctypes.c_void_p
            send_echo.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_void_p,
                ctypes.c_ushort,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_ulong,
            ]
            send_echo.restype = ctypes.c_ulong
            close.argtypes = [ctypes.c_void_p]
            close.restype = ctypes.c_bool
            handle = create()
            if handle in (None, _INVALID_HANDLE_VALUE):
                return _PingTransportResult(unavailable=True)
            try:
                payload = ctypes.create_string_buffer(b"PowerTec")
                reply_buffer = ctypes.create_string_buffer(
                    ctypes.sizeof(_IcmpEchoReply) + len(payload) + 64
                )
                destination = ctypes.c_ulong(int.from_bytes(address.packed, "little"))
                reply_count = send_echo(
                    handle,
                    destination,
                    payload,
                    ctypes.c_ushort(len(payload.raw) - 1),
                    None,
                    reply_buffer,
                    ctypes.c_ulong(len(reply_buffer)),
                    ctypes.c_ulong(timeout_ms),
                )
                if reply_count == 0:
                    error_code = loader.kernel32.GetLastError()
                    return _PingTransportResult(timed_out=error_code == _IP_REQ_TIMED_OUT)
                reply = _IcmpEchoReply.from_buffer(reply_buffer)
                if reply.status == _IP_REQ_TIMED_OUT:
                    return _PingTransportResult(timed_out=True)
                if reply.status != _IP_SUCCESS:
                    return _PingTransportResult()
                remote = ipaddress.IPv4Address(
                    int(reply.address).to_bytes(4, "little")
                ).compressed
                return _PingTransportResult(
                    success=True,
                    latency_ms=float(reply.round_trip_time),
                    remote_ip=remote,
                )
            finally:
                close(handle)
        except Exception:
            return _PingTransportResult(unavailable=True)


def _default_transport() -> _PingTransportProtocol | None:
    loader = getattr(ctypes, "windll", None)
    if loader is None:
        return None
    try:
        api = loader.iphlpapi
        if not all(hasattr(api, name) for name in ("IcmpCreateFile", "IcmpSendEcho", "IcmpCloseHandle")):
            return None
    except Exception:
        return None
    return _WindowsIcmpTransport()


@dataclass(frozen=True)
class SafePingBackend:
    """Execute one bounded ICMP attempt against one validated IP literal."""

    transport: _PingTransportProtocol | None = field(default_factory=_default_transport, repr=False)
    max_timeout_ms: int = 5000

    def __post_init__(self) -> None:
        if self.transport is not None and not isinstance(self.transport, _PingTransportProtocol):
            raise ValueError("transport must implement the ping transport protocol")
        if (
            not isinstance(self.max_timeout_ms, int)
            or isinstance(self.max_timeout_ms, bool)
            or not 1 <= self.max_timeout_ms <= 5000
        ):
            raise ValueError("max_timeout_ms must be an integer from 1 through 5000")

    def ping(self, *, host: str, timeout_ms: int) -> PingBackendResult:
        try:
            if not isinstance(host, str) or not host or host != host.strip():
                return PingBackendResult()
            normalized = ipaddress.ip_address(host).compressed.casefold()
        except ValueError:
            return PingBackendResult()
        if (
            not isinstance(timeout_ms, int)
            or isinstance(timeout_ms, bool)
            or timeout_ms <= 0
        ):
            return PingBackendResult()
        if self.transport is None:
            return PingBackendResult(unavailable=True)
        effective_timeout = min(timeout_ms, self.max_timeout_ms)
        try:
            observed = self.transport.probe(host=normalized, timeout_ms=effective_timeout)
            if not isinstance(observed, _PingTransportResult):
                return PingBackendResult()
        except Exception:
            return PingBackendResult()
        if observed.unavailable:
            return PingBackendResult(unavailable=True)
        if observed.timed_out:
            return PingBackendResult(timed_out=True)
        if not observed.success:
            return PingBackendResult()
        if observed.remote_ip is None:
            return PingBackendResult()
        try:
            remote = ipaddress.ip_address(observed.remote_ip).compressed.casefold()
        except ValueError:
            return PingBackendResult()
        if remote != normalized:
            return PingBackendResult()
        return PingBackendResult(
            success=True,
            latency_ms=observed.latency_ms,
            remote_ip=remote,
        )
