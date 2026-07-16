from app.agents.support.schemas import SupportAnalysis
from app.integrations.ai.base import AIProvider
from app.integrations.ai.schemas import AIRequest, AIResponse


class MockAIProvider(AIProvider):
    provider_name = "mock"

    async def analyze_support(self, request: AIRequest) -> AIResponse:
        context = request.context
        extracted = context.get("extracted", {})
        priority = context["deterministic_priority"]
        text = context.get("text", "")
        lower = text.lower()
        possible_causes = ["Falha de comunicacao ou configuracao local"]
        actions = ["Confirmar internet", "Coletar mensagem de erro", "Verificar se o aplicativo abre em outro terminal"]
        if "impressora" in lower:
            possible_causes = ["Impressora sem comunicacao", "Fila de impressao parada", "Impressora padrao incorreta"]
            actions = ["Confirmar se a impressora esta ligada", "Verificar impressora padrao", "Coletar status da fila de impressao"]
        elif "tef" in lower:
            possible_causes = ["Servico TEF indisponivel", "Falha de internet", "Pinpad sem comunicacao"]
            actions = ["Confirmar internet", "Verificar se outros pagamentos funcionam", "Coletar mensagem exibida no TEF"]
        elif "nfc" in lower or "rejeitada" in lower:
            possible_causes = ["Rejeicao fiscal", "Certificado ou configuracao fiscal inconsistente"]
            actions = ["Coletar codigo de rejeicao", "Confirmar se outras notas emitem", "Verificar validade do certificado na tela do sistema"]

        analysis = SupportAnalysis(
            summary=f"Triagem mock para: {text[:180]}",
            category="suporte_tecnico",
            subcategory="triagem_inicial",
            product=extracted.get("product") or context.get("product") or "",
            module="PDV" if "caixa" in lower or "pdv" in lower else "",
            version=extracted.get("version") or context.get("version") or "",
            device=extracted.get("device") or "",
            error_message=extracted.get("error_message") or "",
            impact="Loja parada" if context.get("store_stopped") else "Impacto a confirmar",
            affected_users=999 if context.get("store_stopped") else 1,
            store_stopped=bool(context.get("store_stopped")),
            fiscal_risk=bool(context.get("fiscal_risk")),
            data_loss_risk=bool(context.get("data_loss_risk")),
            priority=priority,
            confidence=0.86 if priority in {"P1", "P2"} else 0.74,
            missing_information=context.get("missing_information", []),
            suggested_questions=context.get("suggested_questions", []),
            possible_causes=possible_causes,
            recommended_actions=actions,
            knowledge_sources=context.get("knowledge_sources", []),
            requires_human=priority == "P1" or bool(context.get("requires_human")),
            requires_authorization=bool(context.get("data_loss_risk")),
            safety_notes=["Modo mock: nenhuma acao remota ou correcao automatica foi executada."],
            triggered_rules=context.get("triggered_rules", []),
        )
        return AIResponse(analysis=analysis, provider=self.provider_name, model="mock-support-v1")
