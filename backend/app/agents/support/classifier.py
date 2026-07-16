from dataclasses import dataclass


@dataclass(frozen=True)
class PriorityResult:
    priority: str
    rules: list[str]
    store_stopped: bool = False
    fiscal_risk: bool = False
    data_loss_risk: bool = False
    requires_human: bool = False


RULES = [
    ("P1", "all_pos_down", ["todos os caixas", "loja sem vender", "sem vender", "todos os terminais"], {"store_stopped": True, "requires_human": True}),
    ("P1", "server_down", ["servidor principal", "servidor indisponivel", "servidor indisponível"], {"store_stopped": True, "requires_human": True}),
    ("P1", "data_loss", ["perda de dados", "banco corrompido", "base corrompida"], {"data_loss_risk": True, "requires_human": True}),
    ("P1", "fiscal_stopped", ["emissao fiscal parada", "emissão fiscal parada", "nfce completamente parada", "nfc-e completamente parada"], {"fiscal_risk": True, "requires_human": True}),
    ("P2", "nfce_issue", ["nfc-e nao emite", "nfce nao emite", "nfc-e não emite", "rejeitada", "codigo de rejeicao", "código de rejeição"], {"fiscal_risk": True}),
    ("P2", "tef_down", ["tef indisponivel", "tef indisponível", "cartao nao passa", "cartão não passa"], {}),
    ("P2", "cash_closing_error", ["fechamento de caixa", "erro no fechamento"], {}),
    ("P2", "critical_printer", ["impressora critica", "impressora crítica", "impressora fiscal"], {}),
    ("P2", "system_slow", ["muito lento", "lentidao geral", "lentidão geral"], {}),
    ("P3", "single_terminal", ["caixa 1", "caixa 2", "terminal unico", "terminal único", "um unico terminal", "um único terminal"], {}),
    ("P3", "partial_print", ["impressao parcial", "impressão parcial", "relatorio nao gera", "relatório não gera"], {}),
    ("P3", "localized_slow", ["lentidao localizada", "lentidão localizada"], {}),
    ("P4", "question", ["duvida", "dúvida", "treinamento", "melhoria", "configuracao", "configuração", "informacao", "informação"], {}),
]

PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def classify_priority(text: str) -> PriorityResult:
    normalized = text.lower()
    matched: list[tuple[str, str, dict]] = []
    for priority, rule, terms, flags in RULES:
        if any(term in normalized for term in terms):
            matched.append((priority, rule, flags))
    if not matched:
        return PriorityResult(priority="P4", rules=["default_information_request"])
    best = min(matched, key=lambda item: PRIORITY_RANK[item[0]])
    flags = {"store_stopped": False, "fiscal_risk": False, "data_loss_risk": False, "requires_human": False}
    for _, _, item_flags in matched:
        flags.update({key: flags[key] or bool(item_flags.get(key)) for key in flags})
    return PriorityResult(
        priority=best[0],
        rules=[rule for _, rule, _ in matched],
        store_stopped=flags["store_stopped"],
        fiscal_risk=flags["fiscal_risk"],
        data_loss_risk=flags["data_loss_risk"],
        requires_human=flags["requires_human"],
    )
