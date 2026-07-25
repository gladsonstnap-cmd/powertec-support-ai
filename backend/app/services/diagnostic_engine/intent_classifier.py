from collections.abc import Iterable

from app.services.diagnostic_engine.enums import ClassifierSource, IntentType
from app.services.diagnostic_engine.models import IntentClassification
from app.services.diagnostic_engine.normalization import normalize_text


def _matched_terms(normalized_text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if term in normalized_text]


class IntentClassifier:
    COMMAND_RULES: list[tuple[IntentType, tuple[str, ...], float]] = [
        (IntentType.HUMAN_REQUEST, ("falar com um tecnico", "falar com tecnico", "suporte humano", "quero um tecnico", "atendente", "humano"), 0.98),
        (IntentType.STATUS_REQUEST, ("acompanhar chamado", "situacao do chamado", "como esta meu chamado", "status", "protocolo"), 0.96),
        (IntentType.CANCEL_REQUEST, ("cancelar atendimento", "encerrar atendimento", "fechar chamado", "cancelar"), 0.97),
        (IntentType.RESTART_REQUEST, ("novo atendimento", "comecar novamente", "recomecar", "reiniciar"), 0.95),
    ]
    SIMPLE_RULES: list[tuple[IntentType, tuple[str, ...], float]] = [
        (IntentType.GREETING, ("bom dia", "boa tarde", "boa noite", "ola", "oi"), 0.86),
        (IntentType.DENIAL, ("nao resolveu", "continua com erro", "ainda nao funciona", "deu errado", "nao"), 0.9),
        (IntentType.CONFIRMATION, ("voltou a funcionar", "deu certo", "funcionou", "resolveu", "sim"), 0.9),
    ]
    INCIDENT_TERMS = (
        "pdv", "sistema", "travou", "erro", "falha", "nao abre", "nao consigo emitir", "banco nao conecta",
        "impressora nao imprime", "tef sem comunicacao", "estoque incorreto", "caixa nao fecha", "sistema lento",
        "erro ao vender", "produto nao aparece", "servidor offline", "nota", "cupom", "venda",
    )
    INFORMATION_TERMS = (
        "acontece apenas", "comecou hoje", "servidor esta ligado", "aparece o erro", "erro ", "uso o sistema",
        "caixa 1", "caixa 2", "caixa 3", "terminal", "loja", "filial",
    )

    def classify(self, message: str | None) -> IntentClassification:
        normalized = normalize_text(message)
        if not normalized:
            return IntentClassification(IntentType.UNKNOWN, 0.0, ClassifierSource.FALLBACK, [], normalized)

        for intent, terms, confidence in self.COMMAND_RULES:
            matched = _matched_terms(normalized, terms)
            if matched:
                return IntentClassification(intent, confidence, ClassifierSource.RULE, matched, normalized)

        for intent, terms, confidence in self.SIMPLE_RULES:
            matched = _matched_terms(normalized, terms)
            if not matched:
                continue
            if intent == IntentType.DENIAL and matched == ["nao"] and normalized != "nao":
                continue
            if normalized in matched or len(normalized.split()) <= 5:
                return IntentClassification(intent, confidence, ClassifierSource.RULE, matched, normalized)

        incident_matches = _matched_terms(normalized, self.INCIDENT_TERMS)
        if incident_matches and self._has_problem_signal(normalized):
            confidence = min(0.92, 0.62 + len(incident_matches) * 0.08)
            return IntentClassification(IntentType.INCIDENT, confidence, ClassifierSource.RULE, incident_matches, normalized)

        info_matches = _matched_terms(normalized, self.INFORMATION_TERMS)
        if info_matches:
            confidence = min(0.85, 0.55 + len(info_matches) * 0.08)
            return IntentClassification(IntentType.INFORMATION, confidence, ClassifierSource.RULE, info_matches, normalized)

        return IntentClassification(IntentType.UNKNOWN, 0.2, ClassifierSource.FALLBACK, [], normalized)

    @staticmethod
    def _has_problem_signal(normalized: str) -> bool:
        return any(signal in normalized for signal in ("nao", "erro", "falha", "trav", "lento", "offline", "parado", "sem ", "incorreto"))
