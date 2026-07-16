import { ArrowUpRight, Building2, Package, TicketCheck, Users } from "lucide-react";
import Link from "next/link";

const metrics = [
  { label: "Chamados abertos", value: "12", icon: TicketCheck },
  { label: "Clientes ativos", value: "8", icon: Users },
  { label: "Estabelecimentos", value: "21", icon: Building2 },
  { label: "Produtos", value: "5", icon: Package }
];

export default function Home() {
  return (
    <main className="min-h-screen">
      <section className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <div>
            <h1 className="text-2xl font-semibold tracking-normal">PowerTec Support AI</h1>
            <p className="mt-1 text-sm text-slate-600">Painel operacional da Etapa 1</p>
          </div>
          <Link href="/tickets" className="inline-flex items-center gap-2 rounded bg-brand px-3 py-2 text-sm font-medium text-white">
            Chamados
            <ArrowUpRight size={16} aria-hidden="true" />
          </Link>
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl gap-4 px-6 py-6 md:grid-cols-4">
        {metrics.map((metric) => (
          <div key={metric.label} className="rounded border border-slate-200 bg-white p-4">
            <metric.icon className="mb-4 text-brand" size={22} aria-hidden="true" />
            <p className="text-sm text-slate-600">{metric.label}</p>
            <p className="mt-2 text-3xl font-semibold">{metric.value}</p>
          </div>
        ))}
      </section>
    </main>
  );
}
