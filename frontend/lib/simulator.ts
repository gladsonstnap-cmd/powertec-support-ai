import { apiJson } from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import type { Conversation } from "@/types/conversation";

function requireSimulatorAuth() {
  if (isAuthenticated()) return;
  if (typeof window !== "undefined") {
    window.location.href = "/login";
  }
  throw new Error("Autenticacao necessaria para usar o simulador.");
}

export async function sendSimulatorMessage(phone: string, text: string) {
  requireSimulatorAuth();
  return apiJson<Conversation>("/dev/messaging/simulate", {
    method: "POST",
    body: JSON.stringify({ phone, text, message_type: "text" })
  });
}

export async function resetSimulatorConversation(conversationId: string) {
  requireSimulatorAuth();
  return apiJson<Conversation>(`/dev/messaging/conversations/${conversationId}/reset`, {
    method: "POST",
    body: "{}"
  });
}

export async function attachSimulatorDemo(conversationId: string) {
  requireSimulatorAuth();
  return apiJson<Conversation>(`/dev/messaging/conversations/${conversationId}/attach`, {
    method: "POST",
    body: JSON.stringify({
      filename: "erro-demo.txt",
      mime_type: "text/plain",
      content_base64: "TG9nIGZpY3RpY2lvIGRvIHNpbXVsYWRvci4="
    })
  });
}
