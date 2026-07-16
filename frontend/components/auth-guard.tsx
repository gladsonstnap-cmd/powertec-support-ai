"use client";

import { ReactNode, useEffect, useState } from "react";
import { isAuthenticated } from "@/lib/auth";

export function AuthGuard({ children }: { children: ReactNode }) {
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      window.location.replace("/login");
      return;
    }
    setAllowed(true);
  }, []);

  if (!allowed) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-panel text-sm text-slate-600">
        Verificando sessao...
      </main>
    );
  }

  return children;
}
