from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.agents.support.classifier import classify_priority
from app.agents.support.extractor import extract_context, missing_information_for
from app.agents.support.knowledge_search import find_relevant_sources
from app.agents.support.prompts import SYSTEM_PROMPT
from app.agents.support.response_builder import next_question
from app.agents.support.safety import detect_prompt_injection, filter_safe_actions, mask_secrets
from app.agents.support.schemas import AgentContext, SupportAnalysis
from app.integrations.ai.factory import get_ai_provider
from app.integrations.ai.schemas import AIRequest


AGENT_VERSION = "support-agent-3.0-mock-safe"


class SupportAgent:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db
        self.provider = get_ai_provider()

    async def analyze_ticket(self, ticket, messages, customer_context) -> SupportAnalysis:
        text = self._build_context_text(ticket, messages)
        sanitized_text = mask_secrets(text)
        extraction = extract_context(sanitized_text)
        rules = classify_priority(sanitized_text)
        missing = missing_information_for(sanitized_text, extraction)
        previous_questions = list((customer_context or {}).get("previous_questions", []))
        question = next_question(missing, previous_questions, int((customer_context or {}).get("question_count", 0)))
        suggested_questions = [question] if question else []
        sources = []
        if self.db is not None:
            sources = find_relevant_sources(
                self.db,
                ticket.tenant_id,
                sanitized_text,
                product=extraction.get("product") or (customer_context or {}).get("product"),
                version=extraction.get("version") or (customer_context or {}).get("version"),
            )
        injection = detect_prompt_injection(sanitized_text)
        context = AgentContext(
            text=sanitized_text,
            product=extraction.get("product") or (customer_context or {}).get("product"),
            version=extraction.get("version") or (customer_context or {}).get("version"),
            previous_questions=previous_questions,
            knowledge_sources=sources,
            deterministic_priority=rules.priority,
            triggered_rules=rules.rules,
            missing_information=missing,
            extracted=extraction,
        )
        request = AIRequest(
            prompt=SYSTEM_PROMPT,
            context={
                **context.model_dump(),
                "store_stopped": rules.store_stopped,
                "fiscal_risk": rules.fiscal_risk,
                "data_loss_risk": rules.data_loss_risk,
                "requires_human": rules.requires_human,
            },
        )
        try:
            response = await self.provider.analyze_support(request)
            analysis = SupportAnalysis.model_validate(response.analysis)
        except Exception:
            analysis = self._fallback_analysis(sanitized_text, extraction, rules, missing, suggested_questions, sources)
            analysis.safety_notes.append("Fallback deterministico aplicado por retorno invalido da IA.")
        if injection:
            analysis.requires_human = True
            analysis.requires_authorization = True
            analysis.safety_notes.append("Possivel prompt injection detectado e tratado como dado nao confiavel.")
        analysis.priority = self._stricter_priority(analysis.priority, rules.priority)
        analysis.triggered_rules = sorted(set([*analysis.triggered_rules, *rules.rules]))
        analysis.store_stopped = analysis.store_stopped or rules.store_stopped
        analysis.fiscal_risk = analysis.fiscal_risk or rules.fiscal_risk
        analysis.data_loss_risk = analysis.data_loss_risk or rules.data_loss_risk
        analysis.requires_human = analysis.requires_human or rules.requires_human or analysis.priority == "P1"
        actions, notes, requires_authorization = filter_safe_actions(analysis.recommended_actions)
        analysis.recommended_actions = actions
        analysis.safety_notes = sorted(set([*analysis.safety_notes, *notes]))
        analysis.requires_authorization = analysis.requires_authorization or requires_authorization or analysis.data_loss_risk
        analysis.suggested_questions = suggested_questions or analysis.suggested_questions[:1]
        return analysis

    def _build_context_text(self, ticket, messages) -> str:
        parts = [getattr(ticket, "description", "") or ""]
        for message in messages[-30:]:
            text = getattr(message, "text_content", None) or getattr(message, "body", None) or ""
            if text:
                parts.append(text)
        return "\n".join(parts)[:30000]

    def _fallback_analysis(self, text, extraction, rules, missing, questions, sources) -> SupportAnalysis:
        return SupportAnalysis(
            summary=f"Triagem deterministica: {text[:180]}",
            category="suporte_tecnico",
            subcategory="fallback",
            product=extraction.get("product") or "",
            version=extraction.get("version") or "",
            device=extraction.get("device") or "",
            error_message=extraction.get("error_message") or "",
            impact="Loja parada" if rules.store_stopped else "Impacto a confirmar",
            affected_users=999 if rules.store_stopped else 0,
            store_stopped=rules.store_stopped,
            fiscal_risk=rules.fiscal_risk,
            data_loss_risk=rules.data_loss_risk,
            priority=rules.priority,
            confidence=0.65,
            missing_information=missing,
            suggested_questions=questions,
            possible_causes=["Necessario coletar mais informacoes com seguranca."],
            recommended_actions=["Coletar mensagem de erro", "Confirmar impacto", "Pedir captura de tela"],
            knowledge_sources=sources,
            requires_human=rules.requires_human,
            requires_authorization=rules.data_loss_risk,
            safety_notes=["Fallback sem execucao de comandos remotos."],
            triggered_rules=rules.rules,
        )

    def _stricter_priority(self, left: str, right: str) -> str:
        rank = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
        return left if rank[left] <= rank[right] else right


def analysis_to_record_kwargs(analysis: SupportAnalysis, tenant_id: UUID, ticket_id: UUID, provider: str) -> dict:
    now = datetime.now(UTC)
    return {
        "tenant_id": tenant_id,
        "ticket_id": ticket_id,
        "provider": provider,
        "agent_version": AGENT_VERSION,
        "summary": analysis.summary,
        "category": analysis.category,
        "subcategory": analysis.subcategory,
        "product": analysis.product,
        "module": analysis.module,
        "version": analysis.version,
        "device": analysis.device,
        "operating_system": analysis.operating_system,
        "error_message": analysis.error_message,
        "impact": analysis.impact,
        "affected_users": analysis.affected_users,
        "store_stopped": analysis.store_stopped,
        "fiscal_risk": analysis.fiscal_risk,
        "data_loss_risk": analysis.data_loss_risk,
        "priority": analysis.priority,
        "confidence": int(round(analysis.confidence * 100)),
        "missing_information": analysis.missing_information,
        "suggested_questions": analysis.suggested_questions,
        "possible_causes": analysis.possible_causes,
        "recommended_actions": analysis.recommended_actions,
        "knowledge_sources": [item.model_dump() for item in analysis.knowledge_sources],
        "triggered_rules": analysis.triggered_rules,
        "requires_human": analysis.requires_human,
        "requires_authorization": analysis.requires_authorization,
        "safety_notes": analysis.safety_notes,
        "technician_feedback": {},
        "created_at": now,
        "updated_at": now,
    }
