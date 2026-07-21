import { apiJson } from "@/lib/api";
import { AgentAuditEvent, AgentCommand, AgentTool, RemoteAgent } from "@/types/agent";

export function agentStatusLabel(status: string) {
  const labels: Record<string, string> = { online: "Online", offline: "Offline" };
  return labels[status] ?? status;
}

export function riskLabel(risk: string) {
  const labels: Record<string, string> = {
    read_only: "Somente leitura",
    low: "Baixo",
    medium: "Medio",
    high: "Alto",
    prohibited: "Proibido"
  };
  return labels[risk] ?? risk;
}

export async function listAgents() {
  return apiJson<RemoteAgent[]>("/agents/");
}

export async function listAgentTools() {
  return apiJson<AgentTool[]>("/agents/tools");
}

export async function listAgentCommands(agentId: string) {
  return apiJson<AgentCommand[]>(`/agents/${agentId}/commands`);
}

export async function listAgentAudit(agentId: string) {
  return apiJson<AgentAuditEvent[]>(`/agents/${agentId}/audit`);
}

export async function createAgentCommand(agentId: string, toolName: string, args: Record<string, unknown>) {
  return apiJson<AgentCommand>(`/agents/${agentId}/commands`, {
    method: "POST",
    body: JSON.stringify({ request_uuid: crypto.randomUUID(), tool_name: toolName, arguments_json: args })
  });
}

export async function approveAgentCommand(commandId: string) {
  return apiJson<AgentCommand>(`/agents/commands/${commandId}/approve`, { method: "POST" });
}
