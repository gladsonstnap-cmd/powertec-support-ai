import type { TicketPriority, TicketStatus } from "@/types/ticket";

const priorityClass: Record<TicketPriority, string> = {
  P1: "bg-red-100 text-red-800",
  P2: "bg-amber-100 text-amber-800",
  P3: "bg-sky-100 text-sky-800",
  P4: "bg-slate-100 text-slate-700"
};

export function PriorityBadge({ priority }: { priority: TicketPriority }) {
  return <span className={`rounded px-2 py-1 text-xs font-semibold ${priorityClass[priority]}`}>{priority}</span>;
}

export function StatusBadge({ status }: { status: TicketStatus }) {
  return <span className="rounded border border-slate-300 px-2 py-1 text-xs font-medium">{status.replace("_", " ")}</span>;
}
