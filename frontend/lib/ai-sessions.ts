import { apiJson } from "@/lib/api";
import type { AIDiagnosticSession, AIHypothesis, AIPlanStep, AISessionStatus } from "@/types/ai-session";

export const SIMULATION_NOTICE = "Ambiente de simulacao - nenhum comando real foi executado.";

const STATUS_LABELS: Record<AISessionStatus, string> = {
  RECEIVED: "Recebido",
  CLASSIFYING: "Classificando",
  PLANNING: "Planejando",
  READY: "Pronto",
  RUNNING: "Executando",
  WAITING_TOOL: "Aguardando ferramenta",
  ANALYZING_RESULT: "Analisando resultado",
  WAITING_APPROVAL: "Aguardando aprovacao",
  RESOLVED: "Resolvido",
  ESCALATED: "Escalado",
  FAILED: "Falhou",
  CANCELLED: "Cancelado"
};

export function statusLabel(status: AISessionStatus) {
  return STATUS_LABELS[status] ?? status;
}

const CATEGORY_LABELS: Record<string, string> = {
  NETWORK_SERVER: "Rede / Servidor",
  DATABASE: "Banco de dados",
  PRINTING: "Impressao",
  WINDOWS_SERVICE: "Servico Windows",
  DISK_STORAGE: "Armazenamento",
  DNS: "DNS",
  APPLICATION: "Aplicacao",
  FISCAL_DOCUMENT: "Documento fiscal",
  GENERAL_SUPPORT: "Suporte geral",
  UNKNOWN: "Nao identificado"
};

const RISK_LABELS: Record<string, string> = {
  READ_ONLY: "Somente leitura",
  SAFE_ACTION: "Acao segura",
  RESTRICTED: "Restrita",
  BLOCKED: "Bloqueada"
};

const HYPOTHESIS_STATUS_LABELS: Record<string, string> = {
  ACTIVE: "Ativa",
  SUPPORTED: "Sustentada",
  CONFIRMED: "Confirmada",
  WEAKENED: "Enfraquecida",
  REJECTED: "Rejeitada",
  INCONCLUSIVE: "Inconclusiva",
  OPEN: "Ativa"
};

const DECISION_LABELS: Record<string, string> = {
  CONTINUE: "Continuar investigando",
  WAIT_APPROVAL: "Aguardar aprovacao",
  RESOLVE: "Resolver",
  ESCALATE: "Escalar",
  FAIL: "Falhar",
  CANCEL: "Cancelar"
};

export function categoryLabel(category?: string | null) {
  if (!category) return "-";
  return CATEGORY_LABELS[category] ?? category;
}

export function riskLabel(risk?: string | null) {
  if (!risk) return "-";
  return RISK_LABELS[risk] ?? risk;
}

export function hypothesisStatusLabel(status?: string | null) {
  if (!status) return "-";
  return HYPOTHESIS_STATUS_LABELS[status] ?? status;
}

export function decisionLabel(decision?: string | null) {
  if (!decision) return "-";
  return DECISION_LABELS[decision] ?? decision;
}

export function sortedHypotheses(session: AIDiagnosticSession): AIHypothesis[] {
  return [...(session.hypotheses ?? [])].sort((left, right) => right.probability - left.probability);
}

export function pendingApprovalStep(session: AIDiagnosticSession | null): AIPlanStep | null {
  if (!session || session.status !== "WAITING_APPROVAL") return null;
  return session.plan_steps.find((step) => step.status === "WAITING_APPROVAL") ?? null;
}

export function progressLabel(session: AIDiagnosticSession) {
  return `${session.executed_steps}/${session.max_steps} etapas`;
}

export function evidenceSummary(step: AIPlanStep) {
  const evidenceResult = step.evidence_result as { summary?: string; evidence_codes?: string[] } | undefined;
  if (evidenceResult?.summary) return evidenceResult.summary;
  if (step.result?.message) return String(step.result.message);
  return "Sem resultado registrado.";
}

export async function listAiSessions() {
  return apiJson<AIDiagnosticSession[]>("/ai-sessions");
}

export async function createAiSession(ticketId: string, customerMessage: string, scenario = "sql_service_stopped") {
  return apiJson<AIDiagnosticSession>("/ai-sessions", {
    method: "POST",
    body: JSON.stringify({
      ticket_id: ticketId,
      customer_message: customerMessage,
      channel: "portal",
      autonomy_level: "SAFE_ACTIONS_WITH_APPROVAL",
      simulation_scenario: scenario
    })
  });
}

export async function runAiSession(sessionId: string) {
  return apiJson<AIDiagnosticSession>(`/ai-sessions/${sessionId}/run`, { method: "POST" });
}

export async function approveAiSession(sessionId: string) {
  return apiJson<AIDiagnosticSession>(`/ai-sessions/${sessionId}/approve`, {
    method: "POST",
    body: JSON.stringify({ reason: "Aprovado no painel do chamado." })
  });
}

export async function rejectAiSession(sessionId: string) {
  return apiJson<AIDiagnosticSession>(`/ai-sessions/${sessionId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason: "Rejeitado no painel do chamado." })
  });
}

export async function cancelAiSession(sessionId: string) {
  return apiJson<AIDiagnosticSession>(`/ai-sessions/${sessionId}/cancel`, { method: "POST" });
}
