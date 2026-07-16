from app.models.ticket import TicketPriority, TicketStatus
from app.services.protocols import generate_ticket_protocol


def test_ticket_priority_contract():
    assert [priority.value for priority in TicketPriority] == ["P1", "P2", "P3", "P4"]


def test_initial_ticket_statuses_include_stage_1_flow():
    assert TicketStatus.NEW.value == "novo"
    assert TicketStatus.IN_SERVICE.value == "em_atendimento"
    assert TicketStatus.CLOSED.value == "encerrado"


def test_protocol_shape():
    protocol = generate_ticket_protocol()
    assert protocol.startswith("PT-")
    assert len(protocol.split("-")) == 3
