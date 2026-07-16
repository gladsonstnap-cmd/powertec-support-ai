from dataclasses import dataclass


@dataclass(frozen=True)
class ClassificationResult:
    priority: str
    rules: list[str]
    preliminary: bool = True


P1_RULES = {
    "todos os caixas parados": "all_pos_down",
    "nao consigo vender": "cannot_sell",
    "não consigo vender": "cannot_sell",
    "loja parada": "store_down",
    "sistema nao abre em nenhum caixa": "system_not_opening_all_pos",
    "sistema não abre em nenhum caixa": "system_not_opening_all_pos",
    "servidor parado": "server_down",
    "perda de dados": "data_loss",
    "banco corrompido": "corrupt_database",
    "emissao fiscal totalmente parada": "fiscal_down",
    "emissão fiscal totalmente parada": "fiscal_down",
}

P2_RULES = {
    "nfc-e nao emite": "nfce_not_issuing",
    "nfc-e não emite": "nfce_not_issuing",
    "tef nao funciona": "tef_down",
    "tef não funciona": "tef_down",
    "impressora fiscal parada": "fiscal_printer_down",
    "fechamento de caixa com erro": "cash_closing_error",
    "sistema muito lento": "system_slow",
    "erro de conexao recorrente": "recurring_connection_error",
    "erro de conexão recorrente": "recurring_connection_error",
}


def classify_problem(text: str) -> ClassificationResult:
    normalized = text.lower()
    p1 = [code for phrase, code in P1_RULES.items() if phrase in normalized]
    if p1:
        return ClassificationResult(priority="P1", rules=p1)
    p2 = [code for phrase, code in P2_RULES.items() if phrase in normalized]
    if p2:
        return ClassificationResult(priority="P2", rules=p2)
    return ClassificationResult(priority="P4", rules=[])
