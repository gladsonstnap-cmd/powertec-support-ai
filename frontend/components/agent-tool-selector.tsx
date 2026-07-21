"use client";

import { FormEvent, useMemo, useState } from "react";
import { riskLabel } from "@/lib/agents";
import { AgentTool } from "@/types/agent";

export function AgentToolSelector({ tools, onSubmit }: { tools: AgentTool[]; onSubmit: (toolName: string, args: Record<string, unknown>) => Promise<void> }) {
  const [toolName, setToolName] = useState(tools[0]?.name ?? "");
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const selected = useMemo(() => tools.find((tool) => tool.name === toolName) ?? tools[0], [tools, toolName]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    const args: Record<string, unknown> = {};
    Object.entries(selected.input_schema.properties ?? {}).forEach(([key, schema]) => {
      const value = values[key];
      if (value === undefined || value === "") return;
      args[key] = schema.type === "integer" ? Number(value) : value;
    });
    try {
      await onSubmit(selected.name, args);
      setValues({});
    } finally {
      setBusy(false);
    }
  }

  if (!selected) {
    return <section className="border border-slate-200 bg-white p-4 text-sm text-slate-500">Nenhuma ferramenta cadastrada.</section>;
  }

  return (
    <form onSubmit={submit} className="border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm">
          <span className="font-medium">Ferramenta</span>
          <select className="rounded border border-slate-300 px-3 py-2" value={selected.name} onChange={(event) => setToolName(event.target.value)}>
            {tools.map((tool) => <option key={tool.name} value={tool.name}>{tool.name}</option>)}
          </select>
        </label>
        <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">{riskLabel(selected.risk_level)}</span>
      </div>
      <p className="mt-2 text-sm text-slate-500">{selected.description}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {Object.entries(selected.input_schema.properties ?? {}).map(([key, schema]) => (
          <label key={key} className="grid gap-1 text-sm">
            <span className="font-medium">{key}</span>
            {schema.enum ? (
              <select className="rounded border border-slate-300 px-3 py-2" value={values[key] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))}>
                <option value="">Selecione</option>
                {schema.enum.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            ) : (
              <input className="rounded border border-slate-300 px-3 py-2" type={schema.type === "integer" ? "number" : "text"} value={values[key] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} />
            )}
          </label>
        ))}
      </div>
      <button className="mt-4 rounded bg-slate-950 px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={busy}>{busy ? "Enfileirando..." : "Criar comando"}</button>
    </form>
  );
}
