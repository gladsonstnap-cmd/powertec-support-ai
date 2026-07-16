export type ConversationMessage = {
  id: string;
  direction: "inbound" | "outbound";
  sender: string;
  recipient: string;
  message_type: string;
  text_content: string | null;
  status: string;
  created_at: string;
};

export type Conversation = {
  id: string;
  phone: string;
  current_state: string;
  collected_data: Record<string, unknown>;
  preliminary_priority: string | null;
  priority_rules: string[];
  protocol: string | null;
  ticket_id: string | null;
  customer_id: string | null;
  contact_id: string | null;
  unread_count: number;
  created_at: string;
  messages: ConversationMessage[];
};
