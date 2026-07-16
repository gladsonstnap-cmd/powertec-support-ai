"use client";

import { Fragment, useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PriorityBadge } from "@/components/status-badge";
import { apiJson } from "@/lib/api";
import { displayCustomer, displayPriority, displayProduct, displayStatus, formatBoolean } from "@/lib/tickets";
import type { Ticket } from "@/types/ticket";

function TicketsContent() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  useEffect(() => {
    apiJson<Ticket[]>("/tickets")
      .then(setTickets)
      .catch(() => setError("Nao foi possivel carregar os chamados. Verifique sua sessao e tente novamente."))
      .finally(() => setLoading(false));
  }, []);

  const filteredTickets = tickets.filter((ticket) => {
    const query = search.trim().toLowerCase();
    const searchable = [
      ticket.protocol,
      displayCustomer(ticket),
      displayProduct(ticket),
      displayStatus(ticket.status)
    ].join(" ").toLowerCase();
    const matchesSearch = !query || searchable.includes(query);
    const matchesPriority = priorityFilter === "all" || displayPriority(ticket) === priorityFilter;
    const matchesStatus = statusFilter === "all" || ticket.status === statusFilter;
    return matchesSearch && matchesPriority && matchesStatus;
  });
  const statusOptions = Array.from(new Set(tickets.map((ticket) => ticket.status)));

  return (
    <div className="mx-auto max-w-7xl">
      <header className="mb-5">
        <div>
          <p className="mt-1 text-sm text-slate-600">Fila operacional com dados consolidados do cliente, produto e analise.</p>
        </div>
      </header>

      <section className="mb-4 grid gap-3 rounded border border-slate-200 bg-white p-4 lg:grid-cols-[1fr_180px_220px_auto]">
        <input className="rounded border border-slate-300 px-3 py-2 text-sm" placeholder="Buscar por protocolo, cliente, produto ou status" value={search} onChange={(event) => setSearch(event.target.value)} />
        <select className="rounded border border-slate-300 px-3 py-2 text-sm" value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}>
          <option value="all">Todas prioridades</option>
          {["P1", "P2", "P3", "P4"].map((priority) => <option key={priority} value={priority}>{priority}</option>)}
        </select>
        <select className="rounded border border-slate-300 px-3 py-2 text-sm" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
          <option value="all">Todos status</option>
          {statusOptions.map((status) => <option key={status} value={status}>{displayStatus(status)}</option>)}
        </select>
        <button className="rounded border border-slate-300 px-3 py-2 text-sm" onClick={() => { setSearch(""); setPriorityFilter("all"); setStatusFilter("all"); }}>
          Limpar
        </button>
      </section>

      {loading ? <p className="rounded border border-slate-200 bg-white p-4 text-sm text-slate-600">Carregando chamados...</p> : null}
      {error ? <p className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</p> : null}

      {!loading && !error ? (
        <div className="overflow-hidden rounded border border-slate-200 bg-white">
          <table className="w-full table-fixed text-left text-sm">
            <thead className="bg-slate-100 text-slate-700">
              <tr>
                <th className="w-40 px-4 py-3">Protocolo</th>
                <th className="px-4 py-3">Cliente</th>
                <th className="px-4 py-3">Produto</th>
                <th className="w-24 px-4 py-3">Prioridade</th>
                <th className="w-44 px-4 py-3">Status</th>
                <th className="w-28 px-4 py-3">Detalhes</th>
              </tr>
            </thead>
            <tbody>
              {filteredTickets.map((ticket) => {
                const expanded = expandedId === ticket.id;
                return (
                  <Fragment key={ticket.id}>
                    <tr className="border-t border-slate-200 align-top">
                      <td className="px-4 py-3 font-medium">{ticket.protocol}</td>
                      <td className="px-4 py-3">{displayCustomer(ticket)}</td>
                      <td className="px-4 py-3">{displayProduct(ticket)}</td>
                      <td className="px-4 py-3"><PriorityBadge priority={displayPriority(ticket)} /></td>
                      <td className="px-4 py-3">{displayStatus(ticket.status)}</td>
                      <td className="px-4 py-3">
                        <button className="rounded border border-slate-300 px-2 py-1 text-xs" onClick={() => setExpandedId(expanded ? null : ticket.id)}>
                          {expanded ? "Fechar" : "Abrir"}
                        </button>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr className="border-t border-slate-200 bg-slate-50">
                        <td colSpan={6} className="px-4 py-4">
                          <div className="grid gap-4 md:grid-cols-3">
                            <Detail label="Cliente" value={displayCustomer(ticket)} />
                            <Detail label="Empresa" value={ticket.company_name || ticket.customer_name || "Cliente nao identificado"} />
                            <Detail label="Telefone" value={ticket.phone || "Nao informado"} />
                            <Detail label="Produto" value={displayProduct(ticket)} />
                            <Detail label="Modulo" value={ticket.module || "Nao informado"} />
                            <Detail label="Equipamento" value={ticket.device || "Nao informado"} />
                            <Detail label="Prioridade" value={displayPriority(ticket)} />
                            <Detail label="Status" value={displayStatus(ticket.status)} />
                            <Detail label="Protocolo" value={ticket.protocol} />
                            <Detail label="Confianca" value={ticket.analysis_confidence != null ? `${ticket.analysis_confidence}%` : "Nao informado"} />
                            <Detail label="Necessita humano" value={formatBoolean(ticket.analysis_requires_human)} />
                            <Detail label="Necessita autorizacao" value={formatBoolean(ticket.analysis_requires_authorization)} />
                          </div>
                          <div className="mt-4 grid gap-4 md:grid-cols-2">
                            <Detail label="Resumo da analise" value={ticket.analysis_summary || "Sem analise"} />
                            <Detail label="Regras acionadas" value={ticket.analysis_triggered_rules?.join(", ") || "Nenhuma regra registrada"} />
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
              {filteredTickets.length === 0 ? (
                <tr>
                  <td className="border-t border-slate-200 px-4 py-6 text-center text-slate-500" colSpan={6}>
                    Nenhum chamado encontrado.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm text-slate-800">{value}</dd>
    </div>
  );
}

export default function TicketsPage() {
  return (
    <AppShell title="Chamados">
      <TicketsContent />
    </AppShell>
  );
}
