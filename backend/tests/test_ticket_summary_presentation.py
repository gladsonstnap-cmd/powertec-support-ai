from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.api.v1.endpoints.tickets import _summary_from_row


class Row:
    def __init__(self, ticket, **values):
        self.ticket = ticket
        self.values = values

    def __getitem__(self, index):
        if index == 0:
            return self.ticket
        raise IndexError(index)

    def __getattr__(self, name):
        return self.values.get(name)


def make_ticket(**overrides):
    data = {
        "id": uuid4(),
        "protocol": "PWT-2026-000003",
        "customer_id": uuid4(),
        "product_id": None,
        "module": None,
        "priority": "P1",
        "status": "novo",
        "opened_at": datetime.now(UTC),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_row(ticket=None, **overrides):
    defaults = {
        "customer_name": "Supermercado Modelo",
        "contact_name": "Joao da Silva",
        "company_name": "Empresa temporaria",
        "phone": "+5594999990001",
        "product_name": "PDV PowerVarejo",
        "analysis_product": "Retaguarda PowerVarejo",
        "analysis_module": "PDV",
        "analysis_device": "CAIXA-02",
        "analysis_priority": "P2",
        "analysis_summary": "Resumo seguro",
        "analysis_confidence": 90,
        "analysis_requires_human": True,
        "analysis_requires_authorization": False,
        "analysis_triggered_rules": ["all_pos_down"],
        "analysis_updated_at": None,
        "system_name": "PowerVarejo",
    }
    defaults.update(overrides)
    return Row(ticket or make_ticket(), **defaults)


def test_ticket_summary_returns_registered_customer_name():
    summary = _summary_from_row(make_row(customer_name="Cliente Cadastrado"))
    assert summary.customer_name == "Cliente Cadastrado"
    assert str(summary.customer_id) not in (summary.customer_name or "")


def test_ticket_summary_allows_contact_without_customer_display_data():
    summary = _summary_from_row(make_row(customer_name=None, contact_name="Contato Demo"))
    assert summary.customer_name is None
    assert summary.contact_name == "Contato Demo"


def test_ticket_summary_unknown_customer_keeps_phone_fallback():
    summary = _summary_from_row(make_row(customer_name=None, contact_name=None, company_name=None, phone="+5594999990002"))
    assert summary.phone == "+5594999990002"


def test_ticket_summary_direct_product_preferred():
    summary = _summary_from_row(make_row(product_name="Produto direto", analysis_product="Produto analise"))
    assert summary.product_name == "Produto direto"
    assert summary.analysis_product == "Produto analise"


def test_ticket_summary_analysis_product_available_when_direct_missing():
    summary = _summary_from_row(make_row(product_name=None, analysis_product="PDV PowerVarejo"))
    assert summary.product_name is None
    assert summary.analysis_product == "PDV PowerVarejo"


def test_ticket_summary_system_name_available_when_product_missing():
    summary = _summary_from_row(make_row(product_name=None, analysis_product=None, system_name="Sistema coletado"))
    assert summary.system_name == "Sistema coletado"


def test_ticket_summary_uses_ticket_priority_and_analysis_fallback_field():
    summary = _summary_from_row(make_row(ticket=make_ticket(priority="P1"), analysis_priority="P2"))
    assert summary.priority == "P1"
    assert summary.analysis_priority == "P2"


def test_ticket_summary_without_analysis_does_not_break_listing():
    summary = _summary_from_row(
        make_row(
            analysis_product=None,
            analysis_priority=None,
            analysis_summary=None,
            analysis_confidence=None,
            analysis_requires_human=None,
            analysis_requires_authorization=None,
            analysis_triggered_rules=None,
        )
    )
    assert summary.analysis_summary is None
    assert summary.analysis_triggered_rules == []
