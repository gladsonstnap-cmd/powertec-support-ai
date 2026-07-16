import type { TicketPriority } from "@/types/ticket";

export type DashboardTicket = {
  id: string;
  protocol: string;
  customer_name?: string | null;
  contact_name?: string | null;
  company_name?: string | null;
  phone?: string | null;
  product_name?: string | null;
  analysis_product?: string | null;
  system_name?: string | null;
  priority?: TicketPriority | null;
  analysis_priority?: TicketPriority | null;
  status: string;
  created_at: string;
  requires_human: boolean;
};

export type DashboardSummary = {
  open_tickets: number;
  priority_counts: Record<"P1" | "P2" | "P3" | "P4", number>;
  status_counts: Record<string, number>;
  resolved_today: number;
  total_tickets: number;
  human_required: number;
  recent_tickets: DashboardTicket[];
  critical_tickets: DashboardTicket[];
};
