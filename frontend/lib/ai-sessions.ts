import { apiJson } from "@/lib/api";
import type { AIDiagnosticSession, AIPlanStep, AISessionStatus } from "@/types/ai-session";

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

export function pendingApprovalStep(session: AIDiagnosticSession | null): AIPlanStep | null {
  if (!session || session.status !== "WAITING_APPROVAL") return null;
  return session.plan_steps.find((step) => step.status === "WAITING_APPROVAL") ?? null;
}

export function progressLabel(session: AIDiagnosticSession) {
  return `${session.executed_steps}/${session.max_steps} etapas`;
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
