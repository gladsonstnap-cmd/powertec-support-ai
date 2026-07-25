from collections.abc import Iterable

from app.services.diagnostic_engine.enums import ClassifierSource, IncidentCategory, SeverityLevel
from app.services.diagnostic_engine.models import DiagnosticContext, IncidentClassification
from app.services.diagnostic_engine.normalization import normalize_text

CATEGORY_RULES: dict[IncidentCategory, tuple[str, ...]] = {
    IncidentCategory.PDV_STARTUP: ("pdv nao abre", "sistema nao inicia", "aplicativo fecha ao abrir", "tela do sistema nao carrega", "sistema nao abre"),
    IncidentCategory.DATABASE: ("banco nao conecta", "erro de banco", "postgres parado", "postgresql", "firebird", "sql server", "conexao recusada", "timeout do banco", "base indisponivel"),
    IncidentCategory.NETWORK: ("sem rede", "nao comunica com servidor", "servidor nao responde", "cabo desconectado", "sem internet", "perda de conexao", "timeout de rede", "sem comunicacao"),
    IncidentCategory.SERVER: ("servidor desligado", "servidor offline", "servico do servidor parado", "estacao nao encontra servidor"),
    IncidentCategory.FISCAL: ("nf-e", "nfe", "nfce", "nfc-e", "nota fiscal", "cupom fiscal", "sefaz", "rejeicao", "certificado digital", "xml", "contingencia"),
    IncidentCategory.PRINTER: ("impressora nao imprime", "cupom nao sai", "spooler", "impressora termica", "fila de impressao", "impressora"),
    IncidentCategory.TEF: ("tef", "pinpad", "sem comunicacao com operadora", "transacao tef", "pagamento no cartao nao comunica"),
    IncidentCategory.PAYMENT: ("pix", "pagamento duplicado", "cartao", "forma de pagamento"),
    IncidentCategory.INVENTORY: ("estoque incorreto", "estoque negativo", "quantidade errada", "saldo de estoque"),
    IncidentCategory.PRODUCT_REGISTRATION: ("produto nao aparece", "produto nao cadastra", "codigo de barras", "preco incorreto", "cadastro de produto"),
    IncidentCategory.SALES: ("venda duplicada", "nao finaliza venda", "erro ao vender", "venda pendente", "cancelamento de venda", "todos os caixas parados", "loja sem vender", "loja parada"),
    IncidentCategory.CASH_REGISTER: ("caixa nao fecha", "fechamento de caixa", "diferenca de caixa", "caixa bloqueado", "operador de caixa"),
    IncidentCategory.BACKUP: ("backup falhou", "nao fez backup", "restaurar backup", "copia de seguranca"),
    IncidentCategory.UPDATE: ("atualizacao falhou", "sistema desatualizado", "erro depois da atualizacao", "versao incompativel", "depois da atualizacao"),
    IncidentCategory.AUTHENTICATION: ("login invalido", "senha incorreta", "usuario bloqueado", "nao consigo entrar"),
    IncidentCategory.PERMISSION: ("acesso negado", "sem permissao", "usuario nao autorizado"),
    IncidentCategory.WINDOWS: ("servico do windows", "erro do windows", "dll ausente", "arquivo corrompido", "permissao de pasta"),
    IncidentCategory.PERFORMANCE: ("sistema lento", "travando", "demora para abrir", "congelando"),
    IncidentCategory.INTEGRATION: ("integracao nao funciona", "nao sincroniza", "api com erro", "comunicacao com outro sistema"),
    IncidentCategory.HARDWARE: ("computador nao liga", "monitor sem imagem", "memoria ram", "fonte queimada", "placa-mae", "placa mae"),
}

CATEGORY_PRIORITY = (
    IncidentCategory.UPDATE,
    IncidentCategory.DATABASE,
    IncidentCategory.PRINTER,
    IncidentCategory.FISCAL,
    IncidentCategory.TEF,
    IncidentCategory.NETWORK,
    IncidentCategory.SERVER,
    IncidentCategory.SALES,
    IncidentCategory.CASH_REGISTER,
    IncidentCategory.PAYMENT,
    IncidentCategory.INVENTORY,
    IncidentCategory.PRODUCT_REGISTRATION,
    IncidentCategory.BACKUP,
    IncidentCategory.AUTHENTICATION,
    IncidentCategory.PERMISSION,
    IncidentCategory.WINDOWS,
    IncidentCategory.PERFORMANCE,
    IncidentCategory.INTEGRATION,
    IncidentCategory.HARDWARE,
    IncidentCategory.PDV_STARTUP,
)

REMOTE_DIAGNOSTIC_CATEGORIES = {
    IncidentCategory.DATABASE,
    IncidentCategory.NETWORK,
    IncidentCategory.SERVER,
    IncidentCategory.WINDOWS,
    IncidentCategory.PERFORMANCE,
    IncidentCategory.PDV_STARTUP,
    IncidentCategory.UPDATE,
    IncidentCategory.INTEGRATION,
}


def _matched_terms(normalized_text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if term in normalized_text]


class IncidentClassifier:
    def classify(self, message: str | None, context: DiagnosticContext | None = None) -> IncidentClassification:
        normalized = self._message_with_context(message, context)
        if not normalized:
            return self._unknown(normalized)

        matches_by_category = {
            category: _matched_terms(normalized, terms) for category, terms in CATEGORY_RULES.items()
        }
        matched_categories = [category for category, matches in matches_by_category.items() if matches]
        if not matched_categories:
            return self._unknown(normalized)

        category = self._select_category(matched_categories)
        matched_terms = self._all_matched_terms(matches_by_category)
        severity = self._severity(normalized, category)
        confidence = min(0.96, 0.58 + len(matches_by_category[category]) * 0.12 + min(len(matched_categories), 3) * 0.04)
        requires_human = self._requires_human(normalized, category, confidence)
        requires_remote = category in REMOTE_DIAGNOSTIC_CATEGORIES or any(
            term in normalized for term in ("logs", "servico", "porta", "banco", "servidor", "windows", "arquivo")
        )
        rationale = self._rationale(category, severity, matched_categories)
        return IncidentClassification(
            category=category,
            confidence=round(confidence, 2),
            severity=severity,
            source=ClassifierSource.RULE,
            matched_terms=matched_terms,
            normalized_text=normalized,
            requires_human=requires_human,
            requires_remote_diagnostic=requires_remote,
            rationale=rationale,
        )

    @staticmethod
    def _message_with_context(message: str | None, context: DiagnosticContext | None) -> str:
        parts = [message or ""]
        if context:
            parts.extend(
                value or ""
                for value in (
                    context.message,
                    context.pdv_system,
                    context.affected_terminal,
                    context.error_code,
                    context.error_message,
                    context.affected_scope,
                )
            )
        return normalize_text(" ".join(parts))

    @staticmethod
    def _select_category(categories: list[IncidentCategory]) -> IncidentCategory:
        for category in CATEGORY_PRIORITY:
            if category in categories:
                return category
        return categories[0]

    @staticmethod
    def _all_matched_terms(matches_by_category: dict[IncidentCategory, list[str]]) -> list[str]:
        terms: list[str] = []
        for category in CATEGORY_PRIORITY:
            for term in matches_by_category.get(category, []):
                if term not in terms:
                    terms.append(term)
        return terms

    @staticmethod
    def _severity(normalized: str, category: IncidentCategory) -> SeverityLevel:
        if any(term in normalized for term in ("todos os caixas", "loja sem vender", "loja parada", "servidor principal", "perda de dados", "banco corrompido", "fiscal totalmente parada")):
            return SeverityLevel.CRITICAL
        if any(term in normalized for term in ("caixa principal", "emissao fiscal indisponivel", "tef indisponivel", "nao finaliza venda", "fecha repetidamente")):
            return SeverityLevel.HIGH
        if category in {IncidentCategory.DATABASE, IncidentCategory.NETWORK, IncidentCategory.SERVER, IncidentCategory.FISCAL, IncidentCategory.TEF, IncidentCategory.SALES}:
            return SeverityLevel.HIGH
        if category in {IncidentCategory.PRINTER, IncidentCategory.PERFORMANCE, IncidentCategory.PRODUCT_REGISTRATION, IncidentCategory.INVENTORY, IncidentCategory.PAYMENT, IncidentCategory.CASH_REGISTER, IncidentCategory.UPDATE, IncidentCategory.WINDOWS, IncidentCategory.INTEGRATION}:
            return SeverityLevel.MEDIUM
        if category == IncidentCategory.HARDWARE:
            return SeverityLevel.MEDIUM
        return SeverityLevel.LOW

    @staticmethod
    def _requires_human(normalized: str, category: IncidentCategory, confidence: float) -> bool:
        if category == IncidentCategory.HARDWARE or confidence < 0.35:
            return True
        return any(
            term in normalized
            for term in (
                "perda de dados", "banco corrompido", "restaurar backup", "certificado digital", "rejeicao fiscal",
                "acesso indevido", "falha de seguranca", "usuario bloqueado",
            )
        )

    @staticmethod
    def _rationale(category: IncidentCategory, severity: SeverityLevel, categories: list[IncidentCategory]) -> str:
        if len(categories) > 1:
            return f"Categoria {category.value} escolhida por regra de desempate deterministica; severidade {severity.value}."
        return f"Categoria {category.value} identificada por regras deterministicas; severidade {severity.value}."

    @staticmethod
    def _unknown(normalized: str) -> IncidentClassification:
        return IncidentClassification(
            category=IncidentCategory.UNKNOWN,
            confidence=0.15 if normalized else 0.0,
            severity=SeverityLevel.UNKNOWN,
            source=ClassifierSource.FALLBACK,
            matched_terms=[],
            normalized_text=normalized,
            requires_human=True,
            requires_remote_diagnostic=False,
            rationale="Informacoes insuficientes para classificar o incidente.",
        )
