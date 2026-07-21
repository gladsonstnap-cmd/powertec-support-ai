"use client";

import { BookOpen, Bot, Gauge, LogOut, Menu, MonitorCog, PanelLeftClose, TicketCheck, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useMemo, useState } from "react";
import { AuthGuard } from "@/components/auth-guard";
import { getCurrentUser, logout } from "@/lib/auth";

const navItems = [
  { href: "/dashboard", label: "Visao geral", icon: Gauge },
  { href: "/tickets", label: "Chamados", icon: TicketCheck },
  { href: "/agents", label: "Agentes", icon: MonitorCog },
  { href: "/dev/message-simulator", label: "Simulador", icon: Bot },
  { href: "/knowledge", label: "Base de conhecimento", icon: BookOpen }
];

export function AppShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <AuthGuard>
      <ShellContent title={title}>{children}</ShellContent>
    </AuthGuard>
  );
}

function ShellContent({ title, children }: { title: string; children: ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const user = useMemo(() => getCurrentUser(), []);
  const tenantLabel = user?.tenant_name || "PowerTec";

  return (
    <div className="min-h-screen bg-slate-100 text-slate-950">
      <aside className={`fixed inset-y-0 left-0 z-40 hidden border-r border-slate-800 bg-slate-950 text-white shadow-xl transition-all lg:block ${collapsed ? "w-20" : "w-72"}`}>
        <SideNav pathname={pathname} collapsed={collapsed} onNavigate={() => undefined} />
        <button
          type="button"
          className="absolute bottom-4 right-4 rounded border border-slate-700 p-2 text-slate-300 hover:bg-slate-900"
          onClick={() => setCollapsed((value) => !value)}
          aria-label="Recolher menu"
        >
          <PanelLeftClose size={18} />
        </button>
      </aside>

      {drawerOpen ? (
        <div className="fixed inset-0 z-50 bg-slate-950/50 lg:hidden">
          <aside className="h-full w-80 max-w-[86vw] bg-slate-950 text-white shadow-xl">
            <div className="flex justify-end p-3">
              <button className="rounded border border-slate-700 p-2" onClick={() => setDrawerOpen(false)} aria-label="Fechar menu">
                <X size={18} />
              </button>
            </div>
            <SideNav pathname={pathname} collapsed={false} onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      ) : null}

      <div className={`min-h-screen transition-all ${collapsed ? "lg:pl-20" : "lg:pl-72"}`}>
        <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
          <div className="flex items-center justify-between gap-4 px-4 py-4 sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <button className="rounded border border-slate-300 p-2 lg:hidden" onClick={() => setDrawerOpen(true)} aria-label="Abrir menu">
                <Menu size={18} />
              </button>
              <div>
                <h1 className="truncate text-xl font-semibold">{title}</h1>
                <p className="text-xs text-slate-500">Ambiente: <span className="font-medium text-emerald-700">Desenvolvimento</span></p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="hidden text-right text-sm sm:block">
                <p className="font-medium">{user?.email || "Usuario autenticado"}</p>
                <p className="text-xs text-slate-500">{tenantLabel}</p>
              </div>
              <button className="inline-flex items-center gap-2 rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700" onClick={logout}>
                <LogOut size={16} />
                Sair
              </button>
            </div>
          </div>
        </header>
        <main className="px-4 py-5 sm:px-6">{children}</main>
      </div>
    </div>
  );
}

function SideNav({ pathname, collapsed, onNavigate }: { pathname: string; collapsed: boolean; onNavigate: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-800 px-5 py-5">
        <div className="text-lg font-semibold tracking-normal">{collapsed ? "PT" : "PowerTec"}</div>
        {!collapsed ? <p className="mt-1 text-xs text-slate-400">Support AI</p> : null}
      </div>
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navItems.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={`flex items-center gap-3 rounded px-3 py-2 text-sm transition ${active ? "bg-emerald-500 text-slate-950" : "text-slate-300 hover:bg-slate-900 hover:text-white"}`}
            >
              <Icon size={18} />
              {!collapsed ? <span>{item.label}</span> : null}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-slate-800 p-3">
        <button onClick={logout} className="flex w-full items-center gap-3 rounded px-3 py-2 text-sm text-slate-300 hover:bg-slate-900 hover:text-white">
          <LogOut size={18} />
          {!collapsed ? <span>Sair</span> : null}
        </button>
      </div>
    </div>
  );
}
