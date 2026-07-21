import { RemoteAgent } from "@/types/agent";
import { AgentStatusBadge } from "@/components/agent-status-badge";

export function AgentDetailsPanel({ agent }: { agent: RemoteAgent | null }) {
  if (!agent) {
    return <section className="border border-slate-200 bg-white p-4 text-sm text-slate-500">Selecione um agente para ver os detalhes.</section>;
  }
  return (
    <section className="border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{agent.hostname}</h2>
          <p className="text-sm text-slate-500">{agent.operating_system} {agent.os_version}</p>
        </div>
        <AgentStatusBadge status={agent.status} />
      </div>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="text-slate-500">Versao</dt><dd className="font-medium">{agent.agent_version}</dd></div>
        <div><dt className="text-slate-500">Modo</dt><dd className="font-medium">{agent.mode}</dd></div>
        <div><dt className="text-slate-500">Arquitetura</dt><dd className="font-medium">{agent.architecture || "-"}</dd></div>
        <div><dt className="text-slate-500">Ultimo contato</dt><dd className="font-medium">{agent.last_seen_at ? new Date(agent.last_seen_at).toLocaleString("pt-BR") : "-"}</dd></div>
      </dl>
    </section>
  );
}
