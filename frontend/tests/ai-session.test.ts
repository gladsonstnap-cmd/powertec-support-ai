import { describe, expect, it } from "vitest";
import { pendingApprovalStep, progressLabel, SIMULATION_NOTICE, statusLabel } from "../lib/ai-sessions";
import type { AIDiagnosticSession } from "../types/ai-session";

describe("ai diagnostic frontend contract", () => {
  it("renders expected status labels", () => {
    expect(statusLabel("WAITING_APPROVAL")).toBe("Aguardando aprovacao");
    expect(statusLabel("RESOLVED")).toBe("Resolvido");
    expect(statusLabel("ESCALATED")).toBe("Escalado");
    expect(statusLabel("FAILED")).toBe("Falhou");
    expect(statusLabel("CANCELLED")).toBe("Cancelado");
  });

  it("keeps the simulation warning visible", () => {
    expect(SIMULATION_NOTICE).toContain("nenhum comando real foi executado");
  });

  it("shows progress using executed and maximum steps", () => {
    expect(progressLabel(session({ executed_steps: 3, max_steps: 12 }))).toBe("3/12 etapas");
  });

  it("detects pending approval step", () => {
    const current = session({
      status: "WAITING_APPROVAL",
      plan_steps: [
        step({ id: "step-1", status: "COMPLETED" }),
        step({ id: "step-2", status: "WAITING_APPROVAL", title: "Reiniciar SQL Server" })
      ]
    });

    expect(pendingApprovalStep(current)?.title).toBe("Reiniciar SQL Server");
  });

  it("returns no pending approval for running sessions", () => {
    expect(pendingApprovalStep(session({ status: "RUNNING" }))).toBeNull();
  });
});

function session(overrides: Partial<AIDiagnosticSession>): AIDiagnosticSession {
  return {
    id: "session-1",
    ticket_id: "ticket-1",
    customer_message: "Todos os caixas perderam conexao com o servidor.",
    channel: "portal",
    autonomy_level: "SAFE_ACTIONS_WITH_APPROVAL",
    status: "READY",
    category: "NETWORK_SERVER",
    priority: "HIGH",
    confidence: 0.91,
    current_risk_level: "READ_ONLY",
    max_steps: 12,
    executed_steps: 0,
    consecutive_failures: 0,
    simulation_scenario: "sql_service_stopped",
    hypotheses: [],
    plan_steps: [],
    approvals: [],
    events: [],
    ...overrides
  };
}

function step(overrides: Record<string, unknown>) {
  return {
    id: "step",
    session_id: "session-1",
    sequence: 1,
    tool_name: "network.ping",
    title: "Verificar conectividade",
    description: "Simula ping.",
    parameters: {},
    risk_level: "READ_ONLY",
    requires_approval: false,
    status: "PENDING",
    attempt_count: 0,
    max_attempts: 2,
    result: {},
    ...overrides
  } as AIDiagnosticSession["plan_steps"][number];
}
