"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  approveAiSession,
  cancelAiSession,
  categoryLabel,
  createAiSession,
  decisionLabel,
  evidenceSummary,
  hypothesisStatusLabel,
  listAiSessions,
  pendingApprovalStep,
  progressLabel,
  rejectAiSession,
  riskLabel,
  runAiSession,
  SIMULATION_NOTICE,
  sortedHypotheses,
  statusLabel
} from "@/lib/ai-sessions";
import type { AIDiagnosticSession } from "@/types/ai-session";
import type { Ticket } from "@/types/ticket";

export function AIDiagnosticPanel({ ticket }: { ticket: Ticket }) {
  const [session, setSession] = useState<AIDiagnosticSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState("");
  const approvalStep = pendingApprovalStep(session);

  useEffect(() => {
    let active = true;
    listAiSessions()
      .then((sessions) => {
        if (!active) return;
        setSession(sessions.find((item) => item.ticket_id === ticket.id) ?? null);
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Nao foi possivel carregar o diagnostico da IA."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [ticket.id]);

  async function perform(action: () => Promise<AIDiagnosticSession>) {
    setError("");
    setActionLoading(true);
    try {
      setSession(await action());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Nao foi possivel atualizar o diagnostico da IA.");
    } finally {
      setActionLoading(false);
    }
  }

  const message = ticket.description || ticket.analysis_summary || `Diagnostico solicitado para o chamado ${ticket.protocol}.`;

  return (
    <section className="mt-5 rounded border border-emerald-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">Diagnostico da IA</h3>
          <p className="mt-1 text-xs font-medium text-emerald-700">{SIMULATION_NOTICE}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {!session ? (
            <button className="rounded bg-brand px-3 py-2 text-sm text-white disabled:opacity-60" disabled={loading || actionLoading} onClick={() => perform(() => createAiSession(ticket.id, message))}>
              {actionLoading ? "Iniciando..." : "Iniciar diagnostico"}
            </button>
          ) : (
            <>
              <button className="rounded border border-slate-300 px-3 py-2 text-sm disabled:opacity-60" disabled={actionLoading || session.status === "WAITING_APPROVAL"} onClick={() => perform(() => runAiSession(session.id))}>
                Executar proxima etapa
              </button>
              <button className="rounded border border-slate-300 px-3 py-2 text-sm disabled:opacity-60" disabled={actionLoading} onClick={() => perform(() => cancelAiSession(session.id))}>
                Cancelar
              </button>
            </>
          )}
        </div>
      </div>

      {loading ? <p className="mt-4 text-sm text-slate-600">Carregando diagnostico...</p> : null}
      {error ? <p className="mt-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}

      {!loading && !session ? (
        <div className="mt-4 rounded border border-dashed border-slate-300 p-4 text-sm text-slate-600">
          Nenhuma sessao iniciada para este chamado.
        </div>
      ) : null}

      {session ? (
        <div className="mt-4 space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <Metric label="Status" value={statusLabel(session.status)} />
            <Metric label="Categoria" value={categoryLabel(session.category)} />
            <Metric label="Prioridade" value={session.priority || "-"} />
            <Metric label="Progresso" value={progressLabel(session)} />
            <Metric label="Confianca" value={session.confidence != null ? `${Math.round(session.confidence * 100)}%` : "-"} />
            <Metric label="Risco atual" value={riskLabel(session.current_risk_level)} />
            <Metric label="Autonomia" value={session.autonomy_level} />
            <Metric label="Cenario" value={session.simulation_scenario} />
          </div>

          <div className="rounded border border-slate-200 bg-slate-50 p-4 text-sm">
            <div className="grid gap-3 md:grid-cols-3">
              <Metric label="Decisao atual" value={decisionLabel(session.last_decision)} />
              <Metric label="Ferramenta recomendada" value={session.recommended_tool || "-"} />
              <Metric label="Confianca final" value={session.final_confidence != null ? `${Math.round(session.final_confidence * 100)}%` : "-"} />
            </div>
            {session.decision_reason ? <p className="mt-3 text-slate-700">{session.decision_reason}</p> : null}
          </div>

          {approvalStep ? (
            <div className="rounded border border-amber-300 bg-amber-50 p-4 text-sm">
              <h4 className="font-semibold text-amber-900">Aprovacao pendente</h4>
              <p className="mt-1 text-amber-900">{approvalStep.title}</p>
              <p className="mt-1 text-amber-800">{approvalStep.description}</p>
              <p className="mt-2 text-xs text-amber-800">Risco: {riskLabel(approvalStep.risk_level)}. Acao simulada: {approvalStep.tool_name}.</p>
              {approvalStep.selection_reason ? <p className="mt-1 text-xs text-amber-800">Motivo: {approvalStep.selection_reason}</p> : null}
              <div className="mt-3 flex gap-2">
                <button className="rounded bg-emerald-600 px-3 py-2 text-white disabled:opacity-60" disabled={actionLoading} onClick={() => perform(() => approveAiSession(session.id))}>Aprovar</button>
                <button className="rounded border border-amber-400 px-3 py-2 disabled:opacity-60" disabled={actionLoading} onClick={() => perform(() => rejectAiSession(session.id))}>Rejeitar</button>
              </div>
            </div>
          ) : null}

          <Panel title="Hipoteses">
            {sortedHypotheses(session).map((hypothesis) => (
              <li key={hypothesis.id} className="rounded border border-slate-200 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium">{hypothesis.rank}. {hypothesis.title} <span className="text-slate-500">({Math.round(hypothesis.probability * 100)}%)</span></div>
                  <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">{hypothesisStatusLabel(hypothesis.status)}</span>
                </div>
                <p className="mt-1 text-slate-600">{hypothesis.description}</p>
                {hypothesis.last_updated_reason ? <p className="mt-2 text-xs text-slate-500">Ultima atualizacao: {hypothesis.last_updated_reason}</p> : null}
                {hypothesis.supporting_evidence?.length ? <EvidenceList title="Evidencias favoraveis" values={hypothesis.supporting_evidence} /> : null}
                {hypothesis.contradicting_evidence?.length ? <EvidenceList title="Evidencias contrarias" values={hypothesis.contradicting_evidence} /> : null}
              </li>
            ))}
          </Panel>

          <Panel title="Plano adaptativo">
            {session.plan_steps.map((step) => (
              <li key={step.id} className={`rounded border p-3 ${step.is_dynamic ? "border-emerald-300 bg-emerald-50" : "border-slate-200"}`}>
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="font-medium">{step.sequence}. {step.title} {step.is_dynamic ? <span className="text-xs text-emerald-700">(adicionado dinamicamente)</span> : null}</span>
                  <span className="text-xs text-slate-500">{step.status} / {riskLabel(step.risk_level)}</span>
                </div>
                <p className="mt-1 text-slate-600">{step.description}</p>
                {step.selection_reason ? <p className="mt-2 text-xs text-slate-500">Selecao: {step.selection_reason}</p> : null}
                <p className="mt-2 text-xs text-slate-500">Resultado: {evidenceSummary(step)}</p>
                {step.error_message ? <p className="mt-2 text-xs text-red-700">Erro: {step.error_message}</p> : null}
              </li>
            ))}
          </Panel>

          <Panel title="Linha do tempo">
            {session.events.map((event) => (
              <li key={event.id} className="rounded border border-slate-200 p-3">
                <div className="font-medium">{event.event_type}</div>
                <p className="mt-1 text-slate-600">{event.message}</p>
              </li>
            ))}
          </Panel>

          {session.resolution_summary ? <p className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{session.resolution_summary}</p> : null}
          {session.escalation_reason ? <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{session.escalation_reason}</p> : null}
          {session.failure_reason ? <p className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{session.failure_reason}</p> : null}
        </div>
      ) : null}
    </section>
  );
}

function EvidenceList({ title, values }: { title: string; values: string[] }) {
  return (
    <div className="mt-2 text-xs text-slate-600">
      <div className="font-medium">{title}</div>
      <ul className="mt-1 list-inside list-disc">
        {values.map((value) => <li key={value}>{value}</li>)}
      </ul>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-200 bg-slate-50 p-3">
      <dt className="text-xs font-medium uppercase text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm font-medium text-slate-800">{value}</dd>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold">{title}</h4>
      <ul className="space-y-2 text-sm">{children}</ul>
    </div>
  );
}
