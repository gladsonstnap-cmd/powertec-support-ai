import { describe, expect, it, vi } from "vitest";
import { createAgentCommand, riskLabel } from "@/lib/agents";

describe("agents frontend helpers", () => {
  it("translates risk labels", () => {
    expect(riskLabel("read_only")).toBe("Somente leitura");
    expect(riskLabel("medium")).toBe("Medio");
  });

  it("creates command without free command field", async () => {
    const storage = new Map<string, string>();
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body));
      expect(body.tool_name).toBe("service_status");
      expect(body.arguments_json).toEqual({ service_name: "Spooler" });
      expect(body.command).toBeUndefined();
      return new Response(JSON.stringify({ id: "cmd-1" }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: () => "req-1" });
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear()
    });
    localStorage.setItem("powertec_access_token", "token");

    await createAgentCommand("agent-1", "service_status", { service_name: "Spooler" });

    expect(fetchMock).toHaveBeenCalledOnce();
    localStorage.clear();
    vi.unstubAllGlobals();
  });
});
