import { AgentCommand } from "@/types/agent";

export function AgentApprovalDialog({ command, onApprove }: { command: AgentCommand | null; onApprove: (commandId: string) => void }) {
  if (!command) return null;
  return (
    <div className="border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
      <p className="font-semibold">Aprovacao necessaria</p>
      <p className="mt-1">Confirme visualmente a execucao da ferramenta cadastrada {command.tool_name}.</p>
      <button className="mt-3 rounded bg-amber-500 px-3 py-2 font-medium text-slate-950" onClick={() => onApprove(command.id)}>Confirmar aprovacao</button>
    </div>
  );
}
