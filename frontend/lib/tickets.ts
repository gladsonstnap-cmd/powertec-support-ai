import type { Ticket, TicketPriority } from "@/types/ticket";

const STATUS_LABELS: Record<string, string> = {
  new: "Novo",
  novo: "Novo",
  triage: "Triagem",
  triagem: "Triagem",
  waiting_customer: "Aguardando cliente",
  aguardando_cliente: "Aguardando cliente",
  waiting_attendant: "Aguardando tecnico",
  in_progress: "Em atendimento",
  em_atendimento: "Em atendimento",
  resolved: "Resolvido",
  resolvido: "Resolvido",
  closed: "Encerrado",
  encerrado: "Encerrado",
  canceled: "Cancelado",
  cancelado: "Cancelado"
};

function firstFilled(...values: Array<string | null | undefined>) {
  return values.find((value) => value && value.trim().length > 0)?.trim();
}

export function displayCustomer(ticket: Pick<Ticket, "customer_name" | "contact_name" | "company_name" | "phone">) {
  return firstFilled(ticket.customer_name, ticket.contact_name, ticket.company_name, ticket.phone) ?? "Cliente nao identificado";
}

export function displayProduct(ticket: Pick<Ticket, "product_name" | "analysis_product" | "system_name">) {
  return firstFilled(ticket.product_name, ticket.analysis_product, ticket.system_name) ?? "Nao informado";
}

export function displayPriority(ticket: Pick<Ticket, "priority" | "analysis_priority">): TicketPriority {
  return (ticket.priority ?? ticket.analysis_priority ?? "P4") as TicketPriority;
}

export function displayStatus(status: string) {
  return STATUS_LABELS[status] ?? status.replaceAll("_", " ");
}

export function formatBoolean(value: boolean | null | undefined) {
  return value ? "sim" : "nao";
}
