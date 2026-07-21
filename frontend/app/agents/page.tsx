"use client";

import { useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { AgentApprovalDialog } from "@/components/agent-approval-dialog";
import { AgentAuditTimeline } from "@/components/agent-audit-timeline";
import { AgentCommandTable } from "@/components/agent-command-table";
import { AgentDetailsPanel } from "@/components/agent-details-panel";
import { AgentStatusBadge } from "@/components/agent-status-badge";
import { AgentToolSelector } from "@/components/agent-tool-selector";
import { approveAgentCommand, createAgentCommand, listAgentAudit, listAgentCommands, listAgentTools, listAgents } from "@/lib/agents";
import { AgentAuditEvent, AgentCommand, AgentTool, RemoteAgent } from "@/types/agent";

export default function AgentsPage() {
  const [agents, setAgents] = useState<RemoteAgent[]>([]);
  const [tools, setTools] = useState<AgentTool[]>([]);
  const [commands, setCommands] = useState<AgentCommand[]>([]);
  const [audit, setAudit] = useState<AgentAuditEvent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedAgent = useMemo(() => agents.find((agent) => agent.id === selectedId) ?? agents[0] ?? null, [agents, selectedId]);
  const pendingApproval = commands.find((command) => command.status === "pending_approval") ?? null;

  async function refresh(agentId = selectedAgent?.id) {
    const [agentList, toolList] = await Promise.all([listAgents(), listAgentTools()]);
    setAgents(agentList);
    setTools(toolList);
    const activeId = agentId ?? agentList[0]?.id ?? null;
    setSelectedId(activeId);
    if (activeId) {
      const [commandList, auditList] = await Promise.all([listAgentCommands(activeId), listAgentAudit(activeId)]);
      setCommands(commandList);
      setAudit(auditList);
    }
  }

  useEffect(() => {
    refresh().catch((exc) => setError(exc instanceof Error ? exc.message : "Nao foi possivel carregar agentes."));
  }, []);

  async function handleCreate(toolName: string, args: Record<string, unknown>) {
    if (!selectedAgent) return;
    await createAgentCommand(selectedAgent.id, toolName, args);
    await refresh(selectedAgent.id);
  }

  async function handleApprove(commandId: string) {
    await approveAgentCommand(commandId);
    await refresh(selectedAgent?.id);
  }

  return (
    <AppShell title="Agentes remotos">
      <div className="grid gap-5 xl:grid-cols-[360px_1fr]">
        <section className="border border-slate-200 bg-white">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="text-base font-semibold">Agentes</h2>
          </div>
          <div className="divide-y divide-slate-100">
            {agents.map((agent) => (
              <button key={agent.id} className={`flex w-full items-center justify-between gap-3 px-4 py-3 text-left ${selectedAgent?.id === agent.id ? "bg-emerald-50" : "hover:bg-slate-50"}`} onClick={() => refresh(agent.id)}>
                <span>
                  <span className="block font-medium">{agent.hostname}</span>
                  <span className="block text-sm text-slate-500">{agent.operating_system} - {agent.mode}</span>
                </span>
                <AgentStatusBadge status={agent.status} />
              </button>
            ))}
            {agents.length === 0 ? <p className="px-4 py-6 text-sm text-slate-500">Nenhum agente registrado.</p> : null}
          </div>
        </section>

        <div className="space-y-5">
          {error ? <div className="border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
          <AgentDetailsPanel agent={selectedAgent} />
          {selectedAgent ? <AgentToolSelector tools={tools} onSubmit={handleCreate} /> : null}
          <AgentApprovalDialog command={pendingApproval} onApprove={handleApprove} />
          <AgentCommandTable commands={commands} onApprove={handleApprove} />
          <AgentAuditTimeline events={audit} />
        </div>
      </div>
    </AppShell>
  );
}
