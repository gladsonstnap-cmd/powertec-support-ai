export type RemoteAgent = {
  id: string;
  agent_uuid: string;
  name: string;
  hostname: string;
  operating_system: string;
  os_version: string | null;
  architecture: string | null;
  agent_version: string;
  status: string;
  mode: string;
  last_seen_at: string | null;
  registered_at: string;
  metadata_json: Record<string, unknown>;
};

export type AgentTool = {
  name: string;
  description: string;
  risk_level: string;
  requires_approval: boolean;
  supported_platforms: string[];
  timeout_seconds: number;
  input_schema: {
    properties?: Record<string, { type: string; enum?: string[]; minimum?: number; maximum?: number; maxLength?: number }>;
    required?: string[];
  };
  output_schema: Record<string, unknown>;
};

export type AgentCommand = {
  id: string;
  agent_id: string;
  request_uuid: string;
  tool_name: string;
  arguments_json: Record<string, unknown>;
  status: string;
  risk_level: string;
  requires_approval: boolean;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result_json: Record<string, unknown>;
  error_message: string | null;
};

export type AgentAuditEvent = {
  id: string;
  event_type: string;
  tool_name: string | null;
  sanitized_arguments: Record<string, unknown>;
  policy_decision: Record<string, unknown>;
  result_json: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
};
