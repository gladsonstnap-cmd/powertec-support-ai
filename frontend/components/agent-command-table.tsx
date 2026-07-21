import { AgentCommand } from "@/types/agent";

export function AgentCommandTable({ commands, onApprove }: { commands: AgentCommand[]; onApprove: (commandId: string) => void }) {
  return (
    <section className="border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-base font-semibold">Comandos</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-slate-500">
            <tr><th className="px-4 py-2">Ferramenta</th><th className="px-4 py-2">Status</th><th className="px-4 py-2">Risco</th><th className="px-4 py-2">Resultado</th><th className="px-4 py-2"></th></tr>
          </thead>
          <tbody>
            {commands.map((command) => (
              <tr key={command.id} className="border-t border-slate-100">
                <td className="px-4 py-2 font-medium">{command.tool_name}</td>
                <td className="px-4 py-2">{command.status}</td>
                <td className="px-4 py-2">{command.risk_level}</td>
                <td className="max-w-xs truncate px-4 py-2 text-slate-500">{command.error_message || JSON.stringify(command.result_json)}</td>
                <td className="px-4 py-2 text-right">{command.status === "pending_approval" ? <button className="rounded border border-amber-300 px-3 py-1 text-amber-800" onClick={() => onApprove(command.id)}>Aprovar</button> : null}</td>
              </tr>
            ))}
            {commands.length === 0 ? <tr><td className="px-4 py-6 text-slate-500" colSpan={5}>Nenhum comando criado.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
