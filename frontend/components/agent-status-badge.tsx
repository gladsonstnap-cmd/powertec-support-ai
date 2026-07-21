import { agentStatusLabel } from "@/lib/agents";

export function AgentStatusBadge({ status }: { status: string }) {
  const online = status === "online";
  return <span className={`rounded px-2 py-1 text-xs font-medium ${online ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-700"}`}>{agentStatusLabel(status)}</span>;
}
