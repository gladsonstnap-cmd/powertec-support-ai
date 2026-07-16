"use client";

import { LogOut } from "lucide-react";
import { logout } from "@/lib/auth";

export function LogoutButton() {
  return (
    <button
      type="button"
      onClick={logout}
      className="inline-flex items-center gap-2 rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700"
    >
      <LogOut size={16} aria-hidden="true" />
      Sair
    </button>
  );
}
