from dataclasses import dataclass

from app.services.diagnostic_engine.enums import IncidentCategory
from app.services.diagnostic_engine.evidence_models import Evidence, EvidencePolarity, EvidenceType
from app.services.diagnostic_engine.normalization import normalize_text


@dataclass(frozen=True)
class EvidenceRule:
    terms: tuple[str, ...]
    polarity: EvidencePolarity
    related_incident_ids: tuple[str, ...]
    related_categories: tuple[IncidentCategory, ...]
    confidence_delta: float
    field_name: str | None
    field_value: str | None
    reasoning: str


NEUTRAL_TERMS = (
    "nao sei",
    "vou verificar",
    "talvez",
    "ainda nao testei",
    "nao testei",
    "preciso verificar",
)


RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(("postgres parado", "postgres esta parado", "postgresql parado", "postgresql esta parado", "banco parado", "banco esta parado", "servico do banco parado"), EvidencePolarity.SUPPORTING, ("database_service_stopped",), (IncidentCategory.DATABASE,), 0.28, "database_service_status", "stopped", "resposta informa que o PostgreSQL esta parado"),
    EvidenceRule(("postgres iniciado", "postgres esta iniciado", "postgresql iniciado", "postgresql esta iniciado", "banco iniciado", "banco esta iniciado", "servico do banco iniciado"), EvidencePolarity.CONTRADICTING, ("database_service_stopped",), (IncidentCategory.DATABASE,), -0.24, "database_service_status", "running", "resposta informa que o PostgreSQL esta iniciado"),
    EvidenceRule(("servidor nao responde", "servidor sem ping", "nao pinga servidor", "ping falhou"), EvidencePolarity.SUPPORTING, ("server_offline",), (IncidentCategory.SERVER, IncidentCategory.NETWORK), 0.26, "server_ping", "failed", "servidor nao responde ao ping"),
    EvidenceRule(("servidor responde ao ping", "ping respondeu", "servidor responde", "ping ok"), EvidencePolarity.CONTRADICTING, ("server_offline",), (IncidentCategory.SERVER,), -0.22, "server_ping", "ok", "servidor responde ao ping"),
    EvidenceRule(("todos os caixas", "nenhum caixa", "todos sem acesso", "todos parados"), EvidencePolarity.SUPPORTING, ("server_offline", "all_terminals_cannot_reach_server"), (IncidentCategory.SERVER, IncidentCategory.NETWORK), 0.2, "affected_scope", "all", "falha afeta todos os caixas"),
    EvidenceRule(("somente um caixa", "apenas um caixa", "so um caixa", "um terminal"), EvidencePolarity.CONTRADICTING, ("server_offline", "all_terminals_cannot_reach_server"), (IncidentCategory.SERVER, IncidentCategory.NETWORK), -0.18, "affected_scope", "single_terminal", "falha restrita a um caixa"),
    EvidenceRule(("impressora imprime pagina de teste", "imprime pagina de teste", "pagina de teste imprime", "impressora imprime teste"), EvidencePolarity.CONTRADICTING, ("receipt_printer_not_printing", "windows_spooler_stopped"), (IncidentCategory.PRINTER, IncidentCategory.WINDOWS), -0.2, "printer_test_page", "printed", "impressora imprime pagina de teste"),
    EvidenceRule(("impressora nao aparece", "impressora offline", "impressora nao imprime"), EvidencePolarity.SUPPORTING, ("receipt_printer_not_printing",), (IncidentCategory.PRINTER,), 0.18, "printer_status", "unavailable", "impressora indisponivel no ambiente"),
    EvidenceRule(("sefaz indisponivel", "sefaz esta indisponivel", "sefaz fora do ar", "sefaz nao responde"), EvidencePolarity.SUPPORTING, ("sefaz_unavailable",), (IncidentCategory.FISCAL,), 0.28, "sefaz_status", "unavailable", "SEFAZ esta indisponivel"),
    EvidenceRule(("certificado valido", "certificado esta valido"), EvidencePolarity.CONTRADICTING, ("digital_certificate_expired",), (IncidentCategory.FISCAL,), -0.2, "certificate_status", "valid", "certificado digital esta valido"),
    EvidenceRule(("pinpad nao liga", "pinpad desligado", "pinpad offline"), EvidencePolarity.SUPPORTING, ("pinpad_offline",), (IncidentCategory.TEF, IncidentCategory.HARDWARE), 0.24, "pinpad_status", "offline", "pinpad esta desligado ou offline"),
    EvidenceRule(("internet funcionando", "internet esta funcionando", "internet ok"), EvidencePolarity.CONTRADICTING, ("workstation_cannot_reach_server", "all_terminals_cannot_reach_server"), (IncidentCategory.NETWORK,), -0.12, "internet_status", "ok", "internet esta funcionando"),
)


class EvidenceExtractor:
    def extract(self, raw_text: str, source: EvidenceType = EvidenceType.USER_ANSWER) -> Evidence:
        normalized = normalize_text(raw_text)
        if not normalized or any(term in normalized for term in NEUTRAL_TERMS):
            return Evidence.neutral(raw_text, source)

        matched_rules = [rule for rule in RULES if any(term in normalized for term in rule.terms)]
        if not matched_rules:
            return Evidence.neutral(raw_text, source)

        polarity = self._polarity(matched_rules)
        delta = self._delta(matched_rules, polarity)
        matched_terms = self._matched_terms(normalized, matched_rules)
        related_ids = self._related_incident_ids(matched_rules)
        field_name, field_value = self._field(matched_rules)
        reasoning = [rule.reasoning for rule in matched_rules]
        evidence_id = f"{source.value}:{polarity.value}:{'|'.join(matched_terms)}:{normalized}"

        return Evidence(
            evidence_id=evidence_id,
            source=source,
            raw_text=raw_text,
            normalized_text=normalized,
            evidence_type=source,
            polarity=polarity,
            matched_terms=matched_terms,
            related_incident_ids=related_ids,
            confidence_delta=delta,
            field_name=field_name,
            field_value=field_value,
            reasoning=reasoning,
        )

    @staticmethod
    def _polarity(rules: list[EvidenceRule]) -> EvidencePolarity:
        supporting = sum(1 for rule in rules if rule.polarity == EvidencePolarity.SUPPORTING)
        contradicting = sum(1 for rule in rules if rule.polarity == EvidencePolarity.CONTRADICTING)
        if supporting > contradicting:
            return EvidencePolarity.SUPPORTING
        if contradicting > supporting:
            return EvidencePolarity.CONTRADICTING
        return EvidencePolarity.NEUTRAL

    @staticmethod
    def _delta(rules: list[EvidenceRule], polarity: EvidencePolarity) -> float:
        if polarity == EvidencePolarity.NEUTRAL:
            return 0.0
        values = [rule.confidence_delta for rule in rules if rule.polarity == polarity]
        value = sum(values) / max(len(values), 1)
        return round(max(-0.35, min(0.35, value)), 4)

    @staticmethod
    def _matched_terms(normalized: str, rules: list[EvidenceRule]) -> list[str]:
        terms: list[str] = []
        for rule in rules:
            for term in rule.terms:
                if term in normalized and term not in terms:
                    terms.append(term)
        return terms

    @staticmethod
    def _related_incident_ids(rules: list[EvidenceRule]) -> list[str]:
        ids: list[str] = []
        for rule in rules:
            for incident_id in rule.related_incident_ids:
                if incident_id not in ids:
                    ids.append(incident_id)
        return ids

    @staticmethod
    def _field(rules: list[EvidenceRule]) -> tuple[str | None, str | None]:
        for rule in rules:
            if rule.field_name:
                return rule.field_name, rule.field_value
        return None, None

