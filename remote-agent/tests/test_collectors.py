from agent.collectors.disk_info import collect_disk_info
from agent.collectors.event_logs import collect_event_logs
from agent.collectors.network_info import collect_network_info, resolve_dns
from agent.collectors.services import collect_service_status
from agent.collectors.system_info import collect_system_info


def test_system_info_collects_safe_fields():
    info = collect_system_info("0.1.0")

    assert info["hostname"]
    assert "password" not in info


def test_disk_info_collects_usage():
    info = collect_disk_info(".")

    assert info["drives"][0]["total_bytes"] > 0


def test_network_summary_and_dns_resolution_are_safe():
    assert "interfaces" in collect_network_info()
    assert resolve_dns("localhost")["resolved"] is True


def test_service_status_validates_name():
    status = collect_service_status("Spooler", simulation=True)

    assert status["service_name"] == "Spooler"


def test_event_logs_are_limited_and_sanitized():
    logs = collect_event_logs(limit=100)

    assert len(logs["events"]) <= 50
