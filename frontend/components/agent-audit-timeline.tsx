import { AgentAuditEvent } from "@/types/agent";

export function AgentAuditTimeline({ events }: { events: AgentAuditEvent[] }) {
  return (
    <section className="border border-slate-200 bg-white p-4">
      <h2 className="text-base font-semibold">Auditoria</h2>
      <div className="mt-3 space-y-3">
        {events.map((event) => (
          <div key={event.id} className="border-l-2 border-slate-300 pl-3 text-sm">
            <p className="font-medium">{event.event_type}</p>
            <p className="text-xs text-slate-500">{new Date(event.created_at).toLocaleString("pt-BR")} {event.tool_name ? `- ${event.tool_name}` : ""}</p>
            {event.error_message ? <p className="mt-1 text-red-700">{event.error_message}</p> : null}
          </div>
        ))}
        {events.length === 0 ? <p className="text-sm text-slate-500">Nenhum evento de auditoria.</p> : null}
      </div>
    </section>
  );
}
