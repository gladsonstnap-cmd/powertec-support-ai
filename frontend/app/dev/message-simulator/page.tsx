"use client";

import { Paperclip, RefreshCcw, Send } from "lucide-react";
import { useMemo, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { attachSimulatorDemo, resetSimulatorConversation, sendSimulatorMessage } from "@/lib/simulator";
import type { Conversation } from "@/types/conversation";

const contacts = [
  { name: "Joao da Silva", company: "Supermercado Modelo", phone: "+5594999990001", known: true },
  { name: "Contato desconhecido", company: "Cadastro temporario", phone: "+5594999990002", known: false }
];

const samples = [
  "Meu PDV nao abre.",
  "Todos os caixas estao parados.",
  "A impressora nao imprime.",
  "A NFC-e esta sendo rejeitada.",
  "O caixa nao conecta no servidor."
];

export default function MessageSimulatorPage() {
  const [selectedPhone, setSelectedPhone] = useState(contacts[0].phone);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [text, setText] = useState(samples[0]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const selected = useMemo(() => contacts.find((item) => item.phone === selectedPhone) ?? contacts[0], [selectedPhone]);

  async function sendMessage(message = text) {
    setError("");
    setLoading(true);
    try {
      setConversation(await sendSimulatorMessage(selectedPhone, message));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Nao foi possivel enviar a mensagem.");
    } finally {
      setLoading(false);
    }
  }

  async function resetConversation() {
    if (!conversation) return;
    setError("");
    setLoading(true);
    try {
      setConversation(await resetSimulatorConversation(conversation.id));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Nao foi possivel reiniciar a conversa.");
    } finally {
      setLoading(false);
    }
  }

  async function attachDemo() {
    if (!conversation) return;
    setError("");
    setLoading(true);
    try {
      setConversation(await attachSimulatorDemo(conversation.id));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Nao foi possivel anexar o arquivo.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AppShell title="Simulador">
    <div className="grid min-h-[calc(100vh-112px)] grid-cols-1 overflow-hidden rounded border border-slate-200 bg-panel text-ink lg:grid-cols-[280px_1fr_320px]">
      <aside className="border-r border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-lg font-semibold">Simulador</h1>
        </div>
        {error ? <p className="mt-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}
        <div className="mt-4 space-y-2">
          {contacts.map((contact) => (
            <button
              key={contact.phone}
              onClick={() => setSelectedPhone(contact.phone)}
              className={`w-full rounded border p-3 text-left text-sm ${selectedPhone === contact.phone ? "border-brand bg-emerald-50" : "border-slate-200 bg-white"}`}
            >
              <div className="font-medium">{contact.name}</div>
              <div className="text-slate-600">{contact.phone}</div>
              <div className="text-xs text-slate-500">{contact.known ? contact.company : "desconhecido"}</div>
            </button>
          ))}
        </div>
        <button disabled={loading} className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded bg-brand px-3 py-2 text-sm text-white disabled:opacity-60" onClick={() => sendMessage("iniciar")}>
          <Send size={16} /> {loading ? "Enviando..." : "Iniciar conversa"}
        </button>
        <button disabled={loading} className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded border border-slate-300 px-3 py-2 text-sm disabled:opacity-60" onClick={resetConversation}>
          <RefreshCcw size={16} /> Reiniciar
        </button>
      </aside>

      <section className="flex flex-col">
        <header className="border-b border-slate-200 bg-white px-5 py-4">
          <p className="text-sm text-slate-600">{selected.company}</p>
          <h2 className="text-xl font-semibold">{selected.phone}</h2>
        </header>
        <div className="flex-1 space-y-3 overflow-auto p-5">
          {conversation?.messages.map((message) => (
            <div key={message.id} className={`max-w-xl rounded border p-3 text-sm ${message.direction === "inbound" ? "ml-auto border-emerald-200 bg-emerald-50" : "border-slate-200 bg-white"}`}>
              <p>{message.text_content ?? `[${message.message_type}]`}</p>
              <span className="mt-2 block text-xs text-slate-500">{message.status}</span>
            </div>
          ))}
        </div>
        <div className="border-t border-slate-200 bg-white p-4">
          <div className="mb-2 flex gap-2">
            {samples.map((sample) => (
              <button key={sample} className="rounded border border-slate-300 px-2 py-1 text-xs" onClick={() => setText(sample)}>{sample}</button>
            ))}
          </div>
          <div className="flex gap-2">
            <input className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm" value={text} onChange={(event) => setText(event.target.value)} />
            <button disabled={loading} className="rounded border border-slate-300 p-2 disabled:opacity-60" onClick={attachDemo} title="Anexar arquivo demo"><Paperclip size={18} /></button>
            <button disabled={loading} className="rounded bg-brand px-4 py-2 text-sm text-white disabled:opacity-60" onClick={() => sendMessage()}>Enviar</button>
          </div>
        </div>
      </section>

      <aside className="border-l border-slate-200 bg-white p-4 text-sm">
        <h2 className="text-lg font-semibold">Estado</h2>
        <dl className="mt-4 space-y-3">
          <div><dt className="text-slate-500">Atual</dt><dd className="font-medium">{conversation?.current_state ?? "-"}</dd></div>
          <div><dt className="text-slate-500">Prioridade</dt><dd>{conversation?.preliminary_priority ?? "-"}</dd></div>
          <div><dt className="text-slate-500">Protocolo</dt><dd>{conversation?.protocol ?? "-"}</dd></div>
          <div><dt className="text-slate-500">Chamado</dt><dd>{conversation?.ticket_id ?? "-"}</dd></div>
          <div><dt className="text-slate-500">Regras</dt><dd>{conversation?.priority_rules.join(", ") || "-"}</dd></div>
        </dl>
        <pre className="mt-4 max-h-80 overflow-auto rounded bg-slate-100 p-3 text-xs">{JSON.stringify(conversation?.collected_data ?? {}, null, 2)}</pre>
      </aside>
    </div>
    </AppShell>
  );
}
