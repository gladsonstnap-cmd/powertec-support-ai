"use client";

import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/auth-guard";
import { LogoutButton } from "@/components/logout-button";
import { apiJson } from "@/lib/api";
import type { Conversation } from "@/types/conversation";

function ConversationsContent() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiJson<Conversation[]>("/conversations")
      .then(setConversations)
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Nao foi possivel carregar conversas."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="min-h-screen bg-panel px-6 py-6 text-ink">
      <header className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Conversas</h1>
          <p className="mt-1 text-sm text-slate-600">Acompanhamento operacional das conversas e chamados vinculados.</p>
        </div>
        <LogoutButton />
      </header>

      {loading ? <p className="rounded border border-slate-200 bg-white p-4 text-sm text-slate-600">Carregando conversas...</p> : null}
      {error ? <p className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</p> : null}

      {!loading && !error ? (
        <div className="overflow-hidden rounded border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-100 text-slate-700">
              <tr>
                <th className="px-4 py-3">Telefone</th>
                <th className="px-4 py-3">Estado</th>
                <th className="px-4 py-3">Prioridade</th>
                <th className="px-4 py-3">Protocolo</th>
                <th className="px-4 py-3">Nao lidas</th>
              </tr>
            </thead>
            <tbody>
              {conversations.map((conversation) => (
                <tr key={conversation.id} className="border-t border-slate-200">
                  <td className="px-4 py-3 font-medium">{conversation.phone}</td>
                  <td className="px-4 py-3">{conversation.current_state}</td>
                  <td className="px-4 py-3">{conversation.preliminary_priority ?? "-"}</td>
                  <td className="px-4 py-3">{conversation.protocol ?? "-"}</td>
                  <td className="px-4 py-3">{conversation.unread_count}</td>
                </tr>
              ))}
              {conversations.length === 0 ? (
                <tr>
                  <td className="border-t border-slate-200 px-4 py-6 text-center text-slate-500" colSpan={5}>
                    Nenhuma conversa encontrada.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
    </main>
  );
}

export default function ConversationsPage() {
  return (
    <AuthGuard>
      <ConversationsContent />
    </AuthGuard>
  );
}
