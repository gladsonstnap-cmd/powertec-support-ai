from dataclasses import dataclass

from app.models.ai_orchestrator import AIHypothesis


ACTIVE_STATUSES = {"ACTIVE", "SUPPORTED", "CONFIRMED", "WEAKENED", "INCONCLUSIVE", "OPEN"}


@dataclass(frozen=True)
class HypothesisAdjustment:
    code: str
    delta: float
    supporting: list[str]
    contradicting: list[str]
    reason: str
    status: str | None = None


EVIDENCE_RULES: dict[str, list[HypothesisAdjustment]] = {
    "SERVER_REACHABLE": [HypothesisAdjustment("server_unreachable", -0.12, [], ["Servidor respondeu ao ping."], "Ping bem-sucedido enfraquece servidor inacessivel.", "WEAKENED")],
    "SERVER_UNREACHABLE": [HypothesisAdjustment("server_unreachable", 0.28, ["Servidor nao respondeu ao ping."], [], "Ping sem resposta sustenta servidor inacessivel.", "SUPPORTED")],
    "DNS_RESOLVED": [HypothesisAdjustment("dns_failure", -0.18, [], ["DNS resolveu o nome do servidor."], "DNS resolvido enfraquece falha de DNS.", "WEAKENED")],
    "DNS_FAILED": [HypothesisAdjustment("dns_failure", 0.35, ["DNS nao resolveu o nome do servidor."], [], "Falha de DNS confirmada por lookup.", "CONFIRMED")],
    "DB_PORT_CLOSED": [
        HypothesisAdjustment("database_service_stopped", 0.18, ["Porta 1433 indisponivel."], [], "Porta fechada sustenta servico parado.", "SUPPORTED"),
        HypothesisAdjustment("database_port_blocked", 0.18, ["Porta 1433 indisponivel."], [], "Porta fechada sustenta bloqueio de porta.", "SUPPORTED"),
    ],
    "DB_PORT_OPEN": [
        HypothesisAdjustment("database_port_blocked", -0.18, [], ["Porta 1433 respondeu."], "Porta aberta enfraquece bloqueio de porta.", "WEAKENED"),
        HypothesisAdjustment("database_service_stopped", -0.12, [], ["Porta 1433 respondeu."], "Porta aberta enfraquece servico parado.", "WEAKENED"),
    ],
    "SERVICE_STOPPED": [
        HypothesisAdjustment("database_service_stopped", 0.35, ["Servico SQL aparece parado."], [], "Servico parado confirma causa provavel.", "CONFIRMED"),
        HypothesisAdjustment("database_port_blocked", -0.12, [], ["Servico parado explica porta fechada."], "Servico parado reduz probabilidade de bloqueio externo.", "WEAKENED"),
    ],
    "SERVICE_RUNNING": [
        HypothesisAdjustment("database_service_stopped", -0.25, [], ["Servico SQL aparece em execucao."], "Servico ativo enfraquece servico parado.", "WEAKENED"),
        HypothesisAdjustment("database_port_blocked", 0.12, ["Servico ativo com conectividade ainda pode indicar porta bloqueada."], [], "Servico ativo aumenta suspeita de porta bloqueada quando porta falha.", None),
    ],
    "PRINTER_OFFLINE": [HypothesisAdjustment("printer_offline", 0.3, ["Impressora aparece offline."], [], "Impressora offline confirmada.", "CONFIRMED")],
    "PRINTER_ONLINE": [HypothesisAdjustment("printer_offline", -0.25, [], ["Impressora aparece online."], "Impressora online enfraquece falha fisica/offline.", "WEAKENED")],
    "DISK_LOW_SPACE": [HypothesisAdjustment("disk_low_space", 0.3, ["Espaco livre abaixo do limite."], [], "Pouco espaco em disco confirmado.", "CONFIRMED")],
    "DISK_OK": [HypothesisAdjustment("disk_low_space", -0.25, [], ["Espaco livre suficiente."], "Disco saudavel enfraquece falta de espaco.", "WEAKENED")],
    "SERVICE_RESTARTED": [HypothesisAdjustment("database_service_stopped", 0.08, ["Reinicio simulado concluido."], [], "Reinicio simulado sustenta causa em servico parado.", "SUPPORTED")],
}


def normalize_probabilities(hypotheses: list[AIHypothesis]) -> None:
    total = sum(max(item.probability, 0.01) for item in hypotheses)
    if total <= 0:
        even = 1 / max(len(hypotheses), 1)
        for item in hypotheses:
            item.probability = even
        return
    for item in hypotheses:
        item.probability = round(max(item.probability, 0.01) / total, 4)


def rerank_hypotheses(hypotheses: list[AIHypothesis]) -> None:
    for rank, item in enumerate(sorted(hypotheses, key=lambda hypothesis: hypothesis.probability, reverse=True), start=1):
        item.rank = rank


def update_hypotheses_from_evidence(hypotheses: list[AIHypothesis], evidence_codes: list[str]) -> None:
    by_code = {item.code: item for item in hypotheses}
    for evidence_code in evidence_codes:
        for adjustment in EVIDENCE_RULES.get(evidence_code, []):
            hypothesis = by_code.get(adjustment.code)
            if hypothesis is None:
                continue
            hypothesis.probability = min(1.0, max(0.01, hypothesis.probability + adjustment.delta))
            hypothesis.supporting_evidence = [*hypothesis.supporting_evidence, *adjustment.supporting]
            hypothesis.contradicting_evidence = [*hypothesis.contradicting_evidence, *adjustment.contradicting]
            hypothesis.last_updated_reason = adjustment.reason
            if adjustment.status:
                hypothesis.status = adjustment.status
    for hypothesis in hypotheses:
        if hypothesis.status == "OPEN":
            hypothesis.status = "ACTIVE"
        if hypothesis.probability <= 0.05 and hypothesis.status not in {"CONFIRMED", "REJECTED"}:
            hypothesis.status = "REJECTED"
        elif hypothesis.probability < 0.15 and hypothesis.status not in {"CONFIRMED", "SUPPORTED"}:
            hypothesis.status = "WEAKENED"
    normalize_probabilities(hypotheses)
    rerank_hypotheses(hypotheses)


def strongest_hypothesis(hypotheses: list[AIHypothesis]) -> AIHypothesis | None:
    active = [item for item in hypotheses if item.status in ACTIVE_STATUSES]
    return max(active, key=lambda item: item.probability, default=None)
