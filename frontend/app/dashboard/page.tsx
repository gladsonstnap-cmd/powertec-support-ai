"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PriorityBadge } from "@/components/status-badge";
import { apiJson } from "@/lib/api";
import { displayCustomer, displayPriority, displayProduct, displayStatus } from "@/lib/tickets";
import type { DashboardSummary, DashboardTicket } from "@/types/dashboard";

const priorityOrder = ["P1", "P2", "P3", "P4"] as const;

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    apiJson<DashboardSummary>("/dashboard/summary")
      .then(setSummary)
      .catch(() => setError("Nao foi possivel carregar o dashboard. Tente novamente."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <AppShell title="Visao geral">
      {loading ? <DashboardSkeleton /> : null}
      {error ? <p className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</p> : null}
      {!loading && !error && summary ? <DashboardContent summary={summary} /> : null}
    </AppShell>
  );
}

function DashboardContent({ summary }: { summary: DashboardSummary }) {
  const maxPriority = Math.max(...priorityOrder.map((priority) => summary.priority_counts[priority]), 1);
  if (summary.total_tickets === 0) {
    return (
      <section className="rounded border border-slate-200 bg-white p-8 text-center">
        <h2 className="text-xl font-semibold">Nenhum chamado encontrado</h2>
        <p className="mt-2 text-sm text-slate-600">Use o simulador para abrir um chamado de desenvolvimento e validar a triagem.</p>
        <Link className="mt-5 inline-flex rounded bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950" href="/dev/message-simulator">
          Abrir simulador
        </Link>
      </section>
    );
  }
  return (
    <div className="space-y-5">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Chamados abertos" value={summary.open_tickets} />
        <Metric label="Prioridade P1" value={summary.priority_counts.P1} tone="danger" />
        <Metric label="Prioridade P2" value={summary.priority_counts.P2} tone="warning" />
        <Metric label="Em atendimento" value={summary.status_counts.in_progress ?? 0} />
        <Metric label="Aguardando cliente" value={summary.status_counts.waiting_customer ?? 0} tone="warning" />
        <Metric label="Resolvidos hoje" value={summary.resolved_today} tone="success" />
        <Metric label="Total de chamados" value={summary.total_tickets} />
        <Metric label="Precisam de humano" value={summary.human_required} tone="danger" />
      </section>

      <section className="grid gap-5 xl:grid-cols-[360px_1fr]">
        <div className="rounded border border-slate-200 bg-white p-4">
          <h2 className="font-semibold">Distribuicao por prioridade</h2>
          <div className="mt-4 space-y-3">
            {priorityOrder.map((priority) => (
              <div key={priority}>
                <div className="mb-1 flex items-center justify-between text-sm">
                  <span>{priority}</span>
                  <span className="font-medium">{summary.priority_counts[priority]}</span>
                </div>
                <div className="h-2 rounded bg-slate-100">
                  <div className="h-2 rounded bg-emerald-500" style={{ width: `${(summary.priority_counts[priority] / maxPriority) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
        <TicketPanel title="Chamados criticos" tickets={summary.critical_tickets} empty="Nenhum chamado P1 em aberto." />
      </section>

      <TicketPanel title="Chamados recentes" tickets={summary.recent_tickets} empty="Nenhum chamado recente." />
    </div>
  );
}

function Metric({ label, value, tone = "default" }: { label: string; value: number; tone?: "default" | "danger" | "warning" | "success" }) {
  const tones = {
    default: "border-slate-200",
    danger: "border-red-200",
    warning: "border-amber-200",
    success: "border-emerald-200"
  };
  return (
    <div className={`rounded border bg-white p-4 ${tones[tone]}`}>
      <p className="text-sm text-slate-600">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
    </div>
  );
}

function TicketPanel({ title, tickets, empty }: { title: string; tickets: DashboardTicket[]; empty: string }) {
  return (
    <section className="rounded border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="font-semibold">{title}</h2>
      </div>
      {tickets.length === 0 ? <p className="p-4 text-sm text-slate-600">{empty}</p> : <TicketList tickets={tickets} />}
    </section>
  );
}

function TicketList({ tickets }: { tickets: DashboardTicket[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="px-4 py-3">Protocolo</th>
            <th className="px-4 py-3">Cliente</th>
            <th className="px-4 py-3">Produto</th>
            <th className="px-4 py-3">Prioridade</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3">Data</th>
            <th className="px-4 py-3">Acao</th>
          </tr>
        </thead>
        <tbody>
          {tickets.map((ticket) => (
            <tr key={ticket.id} className="border-t border-slate-200">
              <td className="px-4 py-3 font-medium">{ticket.protocol}</td>
              <td className="px-4 py-3">{displayCustomer(ticket)}</td>
              <td className="px-4 py-3">{displayProduct(ticket)}</td>
              <td className="px-4 py-3"><PriorityBadge priority={displayPriority(ticket)} /></td>
              <td className="px-4 py-3">{displayStatus(ticket.status)}</td>
              <td className="px-4 py-3">{new Date(ticket.created_at).toLocaleDateString("pt-BR")}</td>
              <td className="px-4 py-3"><Link className="rounded border border-slate-300 px-2 py-1 text-xs" href="/tickets">Ver chamado</Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }).map((_, index) => <div key={index} className="h-28 animate-pulse rounded border border-slate-200 bg-white" />)}
      </div>
      <div className="h-72 animate-pulse rounded border border-slate-200 bg-white" />
    </div>
  );
}
