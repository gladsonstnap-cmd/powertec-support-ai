import pytest

from app.services.diagnostic_engine.enums import ClassifierSource, IncidentCategory, IntentType, SeverityLevel
from app.services.diagnostic_engine.incident_classifier import IncidentClassifier
from app.services.diagnostic_engine.intent_classifier import IntentClassifier
from app.services.diagnostic_engine.models import DiagnosticContext
from app.services.diagnostic_engine.normalization import normalize_text


def test_normalize_text_handles_accents_uppercase_spaces_empty_and_none():
    assert normalize_text("  O PDV N\u00c3O ABRE  ") == "o pdv nao abre"
    assert normalize_text("Impressora n\u00e3o est\u00e1 imprimindo") == "impressora nao esta imprimindo"
    assert normalize_text("  muitos    espa\u00e7os ") == "muitos espacos"
    assert normalize_text("") == ""
    assert normalize_text(None) == ""


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("quero falar com um t\u00e9cnico", IntentType.HUMAN_REQUEST),
        ("status do chamado", IntentType.STATUS_REQUEST),
        ("cancelar atendimento", IntentType.CANCEL_REQUEST),
        ("come\u00e7ar novamente", IntentType.RESTART_REQUEST),
        ("bom dia", IntentType.GREETING),
        ("sim, funcionou", IntentType.CONFIRMATION),
        ("n\u00e3o resolveu", IntentType.DENIAL),
        ("o pdv n\u00e3o abre", IntentType.INCIDENT),
        ("acontece apenas no caixa 2", IntentType.INFORMATION),
        ("banana azul", IntentType.UNKNOWN),
    ],
)
def test_intent_classifier_core_intents(message, expected):
    result = IntentClassifier().classify(message)

    assert result.intent == expected
    assert 0.0 <= result.confidence <= 1.0
    assert result.normalized_text == normalize_text(message)


def test_intent_classifier_global_command_priority_over_incident():
    result = IntentClassifier().classify("Quero falar com um t\u00e9cnico porque o PDV n\u00e3o abre")

    assert result.intent == IntentType.HUMAN_REQUEST
    assert "falar com um tecnico" in result.matched_terms


def test_intent_classifier_status_priority_over_incident():
    result = IntentClassifier().classify("Status do chamado do PDV")

    assert result.intent == IntentType.STATUS_REQUEST


def test_intent_classifier_matched_terms_confidence_and_empty_message():
    incident = IntentClassifier().classify("impressora n\u00e3o imprime")
    empty = IntentClassifier().classify("")

    assert incident.matched_terms
    assert incident.source == ClassifierSource.RULE
    assert 0.0 <= incident.confidence <= 1.0
    assert empty.intent == IntentType.UNKNOWN
    assert empty.confidence == 0.0


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("pdv n\u00e3o abre", IncidentCategory.PDV_STARTUP),
        ("banco n\u00e3o conecta", IncidentCategory.DATABASE),
        ("sem rede no caixa", IncidentCategory.NETWORK),
        ("servidor offline", IncidentCategory.SERVER),
        ("nfc-e com rejei\u00e7\u00e3o", IncidentCategory.FISCAL),
        ("impressora n\u00e3o imprime", IncidentCategory.PRINTER),
        ("tef sem comunica\u00e7\u00e3o", IncidentCategory.TEF),
        ("pix duplicado", IncidentCategory.PAYMENT),
        ("estoque incorreto", IncidentCategory.INVENTORY),
        ("produto n\u00e3o aparece", IncidentCategory.PRODUCT_REGISTRATION),
        ("erro ao vender", IncidentCategory.SALES),
        ("caixa n\u00e3o fecha", IncidentCategory.CASH_REGISTER),
        ("backup falhou", IncidentCategory.BACKUP),
        ("erro depois da atualiza\u00e7\u00e3o", IncidentCategory.UPDATE),
        ("login inv\u00e1lido", IncidentCategory.AUTHENTICATION),
        ("acesso negado", IncidentCategory.PERMISSION),
        ("dll ausente no Windows", IncidentCategory.WINDOWS),
        ("sistema lento", IncidentCategory.PERFORMANCE),
        ("integra\u00e7\u00e3o n\u00e3o funciona", IncidentCategory.INTEGRATION),
        ("computador n\u00e3o liga", IncidentCategory.HARDWARE),
    ],
)
def test_incident_classifier_categories(message, category):
    result = IncidentClassifier().classify(message)

    assert result.category == category
    assert result.source == ClassifierSource.RULE
    assert result.matched_terms
    assert 0.0 <= result.confidence <= 1.0


def test_incident_classifier_handles_accented_and_unaccented_messages():
    classifier = IncidentClassifier()

    assert classifier.classify("conex\u00e3o recusada no banco").category == IncidentCategory.DATABASE
    assert classifier.classify("conexao recusada no banco").category == IncidentCategory.DATABASE


def test_incident_conflict_database_beats_pdv_startup():
    result = IncidentClassifier().classify("PDV n\u00e3o abre porque o banco n\u00e3o conecta")

    assert result.category == IncidentCategory.DATABASE
    assert "pdv nao abre" in result.matched_terms
    assert "banco nao conecta" in result.matched_terms
    assert "desempate" in result.rationale


def test_incident_conflict_update_beats_pdv_startup():
    result = IncidentClassifier().classify("Depois da atualiza\u00e7\u00e3o o sistema n\u00e3o abre")

    assert result.category == IncidentCategory.UPDATE
    assert result.severity == SeverityLevel.MEDIUM


def test_printer_with_fiscal_term_prefers_printing_problem_but_keeps_fiscal_terms():
    result = IncidentClassifier().classify("Impressora n\u00e3o imprime a NFC-e")

    assert result.category == IncidentCategory.PRINTER
    assert "impressora nao imprime" in result.matched_terms
    assert "nfc-e" in result.matched_terms


def test_hardware_requires_human():
    result = IncidentClassifier().classify("computador n\u00e3o liga")

    assert result.category == IncidentCategory.HARDWARE
    assert result.requires_human is True


def test_all_registers_down_is_critical():
    result = IncidentClassifier().classify("todos os caixas parados e loja sem vender")

    assert result.severity == SeverityLevel.CRITICAL


def test_one_main_register_down_is_high():
    result = IncidentClassifier().classify("caixa principal parado e n\u00e3o finaliza venda")

    assert result.severity == SeverityLevel.HIGH


def test_performance_for_slow_system():
    result = IncidentClassifier().classify("sistema lento e travando")

    assert result.category == IncidentCategory.PERFORMANCE


@pytest.mark.parametrize("message", ["banco n\u00e3o conecta", "sem rede", "servidor offline", "erro do Windows"])
def test_remote_diagnostic_required_for_infrastructure_cases(message):
    assert IncidentClassifier().classify(message).requires_remote_diagnostic is True


def test_unknown_low_confidence_and_empty_message():
    classifier = IncidentClassifier()
    unknown = classifier.classify("preciso de ajuda")
    empty = classifier.classify("")

    assert unknown.category == IncidentCategory.UNKNOWN
    assert unknown.confidence < 0.35
    assert unknown.requires_human is True
    assert empty.category == IncidentCategory.UNKNOWN
    assert empty.confidence == 0.0


def test_diagnostic_context_is_used_optionally():
    context = DiagnosticContext(message="", error_message="timeout do banco", affected_terminal="caixa 2")
    result = IncidentClassifier().classify("aparece erro", context)

    assert result.category == IncidentCategory.DATABASE
    assert "timeout do banco" in result.normalized_text
