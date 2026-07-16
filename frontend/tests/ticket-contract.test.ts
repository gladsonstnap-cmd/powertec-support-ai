import { describe, expect, it } from "vitest";
import { displayCustomer, displayPriority, displayProduct, displayStatus } from "../lib/tickets";
import type { Ticket } from "../types/ticket";

const priorities = ["P1", "P2", "P3", "P4"] as const;

describe("ticket contract", () => {
  it("keeps priority order aligned with backend", () => {
    expect(priorities).toEqual(["P1", "P2", "P3", "P4"]);
  });

  it("displays registered customer name before any fallback", () => {
    expect(displayCustomer(ticket({ customer_name: "Supermercado Modelo", phone: "+5594" }))).toBe("Supermercado Modelo");
  });

  it("displays contact name when there is no customer name", () => {
    expect(displayCustomer(ticket({ customer_name: null, contact_name: "Joao" }))).toBe("Joao");
  });

  it("displays company name and phone fallbacks without exposing UUIDs", () => {
    expect(displayCustomer(ticket({ customer_name: null, contact_name: null, company_name: "Empresa Demo" }))).toBe("Empresa Demo");
    expect(displayCustomer(ticket({ customer_name: null, contact_name: null, company_name: null, phone: "+5594999990002" }))).toBe("+5594999990002");
  });

  it("displays product using direct, analysis, system and empty fallbacks", () => {
    expect(displayProduct(ticket({ product_name: "Produto direto", analysis_product: "Produto analise", system_name: "Sistema" }))).toBe("Produto direto");
    expect(displayProduct(ticket({ product_name: null, analysis_product: "PDV PowerVarejo", system_name: "Sistema" }))).toBe("PDV PowerVarejo");
    expect(displayProduct(ticket({ product_name: null, analysis_product: null, system_name: "Sistema coletado" }))).toBe("Sistema coletado");
    expect(displayProduct(ticket({ product_name: null, analysis_product: null, system_name: null }))).toBe("Nao informado");
  });

  it("displays ticket priority before analysis priority", () => {
    expect(displayPriority(ticket({ priority: "P1", analysis_priority: "P2" }))).toBe("P1");
    expect(displayPriority(ticket({ priority: null, analysis_priority: "P2" }))).toBe("P2");
  });

  it("translates known statuses and preserves unknown values safely", () => {
    expect(displayStatus("new")).toBe("Novo");
    expect(displayStatus("triage")).toBe("Triagem");
    expect(displayStatus("waiting_customer")).toBe("Aguardando cliente");
    expect(displayStatus("waiting_attendant")).toBe("Aguardando tecnico");
    expect(displayStatus("in_progress")).toBe("Em atendimento");
    expect(displayStatus("resolved")).toBe("Resolvido");
    expect(displayStatus("closed")).toBe("Encerrado");
    expect(displayStatus("custom_status")).toBe("custom status");
  });
});

function ticket(overrides: Partial<Ticket>): Ticket {
  return {
    id: "ticket-id",
    protocol: "PWT-2026-000003",
    status: "novo",
    opened_at: "2026-07-15T00:00:00Z",
    ...overrides
  };
}
