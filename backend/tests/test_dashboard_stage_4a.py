from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.api.v1.endpoints.dashboard import build_dashboard_summary
from app.schemas.ticket import TicketSummaryRead


def make_ticket(**overrides):
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    data = {
        "id": uuid4(),
        "protocol": "PWT-2026-000001",
        "status": "new",
        "created_at": now,
        "updated_at": now,
        "customer_name": "Supermercado Modelo",
        "contact_name": "Joao da Silva",
        "company_name": "Empresa Demo",
        "phone": "+5594999990001",
        "product_name": "PDV PowerVarejo",
        "analysis_product": None,
        "system_name": None,
        "priority": "P3",
        "analysis_priority": None,
        "module": None,
        "device": None,
        "analysis_summary": None,
        "analysis_confidence": None,
        "analysis_requires_human": False,
        "analysis_requires_authorization": False,
        "analysis_triggered_rules": [],
    }
    data.update(overrides)
    return TicketSummaryRead(**data)


def test_dashboard_empty_state_contract():
    summary = build_dashboard_summary([], now=datetime(2026, 7, 16, tzinfo=UTC))

    assert summary.total_tickets == 0
    assert summary.open_tickets == 0
    assert summary.priority_counts == {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    assert summary.recent_tickets == []
    assert summary.critical_tickets == []


def test_dashboard_counts_priorities_statuses_and_human_required():
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    tickets = [
        make_ticket(protocol="PWT-1", priority="P1", status="new", analysis_requires_human=True),
        make_ticket(protocol="PWT-2", priority=None, analysis_priority="P2", status="waiting_customer"),
        make_ticket(protocol="PWT-3", priority="P4", status="resolved", updated_at=now),
        make_ticket(protocol="PWT-4", priority="P3", status="closed", updated_at=now - timedelta(days=1)),
    ]

    summary = build_dashboard_summary(tickets, now=now)

    assert summary.total_tickets == 4
    assert summary.open_tickets == 2
    assert summary.priority_counts == {"P1": 1, "P2": 1, "P3": 1, "P4": 1}
    assert summary.status_counts["new"] == 1
    assert summary.status_counts["waiting_customer"] == 1
    assert summary.status_counts["resolved"] == 1
    assert summary.resolved_today == 1
    assert summary.human_required == 1


def test_dashboard_limits_recent_and_critical_lists():
    base = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    tickets = [
        make_ticket(protocol=f"PWT-{index}", priority="P1", status="new", created_at=base - timedelta(minutes=index))
        for index in range(12)
    ]

    summary = build_dashboard_summary(tickets, now=base)

    assert [ticket.protocol for ticket in summary.recent_tickets] == [f"PWT-{index}" for index in range(8)]
    assert [ticket.protocol for ticket in summary.critical_tickets] == [f"PWT-{index}" for index in range(5)]


def test_dashboard_ignores_resolved_p1_in_critical_list():
    base = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    tickets = [
        make_ticket(protocol="PWT-OPEN", priority="P1", status="new", created_at=base),
        make_ticket(protocol="PWT-RESOLVED", priority="P1", status="resolved", created_at=base + timedelta(minutes=1)),
    ]

    summary = build_dashboard_summary(tickets, now=base)

    assert [ticket.protocol for ticket in summary.critical_tickets] == ["PWT-OPEN"]
