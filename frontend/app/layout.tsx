import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PowerTec Support AI",
  description: "Painel operacional de suporte tecnico automatizado"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
