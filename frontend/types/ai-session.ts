export type AISessionStatus =
  | "RECEIVED"
  | "CLASSIFYING"
  | "PLANNING"
  | "READY"
  | "RUNNING"
  | "WAITING_TOOL"
  | "ANALYZING_RESULT"
  | "WAITING_APPROVAL"
  | "RESOLVED"
  | "ESCALATED"
  | "FAILED"
  | "CANCELLED";

export type AIPlanStepStatus = "PENDING" | "RUNNING" | "WAITING_APPROVAL" | "APPROVED" | "REJECTED" | "COMPLETED" | "FAILED" | "SKIPPED" | "CANCELLED";
export type AIRiskLevel = "READ_ONLY" | "SAFE_ACTION" | "RESTRICTED" | "BLOCKED";
export type AIAutonomyLevel = "DIAGNOSTIC_ONLY" | "SAFE_ACTIONS_WITH_APPROVAL" | "SAFE_ACTIONS_AUTOMATIC";
export type AIHypothesisStatus = "ACTIVE" | "SUPPORTED" | "CONFIRMED" | "WEAKENED" | "REJECTED" | "INCONCLUSIVE" | "OPEN" | string;

export type AIHypothesis = {
  id: string;
  code: string;
  title: string;
  description: string;
  probability: number;
  rank: number;
  status: AIHypothesisStatus;
  evidence: Record<string, unknown>;
  supporting_evidence?: string[];
  contradicting_evidence?: string[];
  last_updated_reason?: string | null;
};

export type AIPlanStep = {
  id: string;
  sequence: number;
  tool_name: string;
  title: string;
  description: string;
  parameters: Record<string, unknown>;
  risk_level: AIRiskLevel;
  requires_approval: boolean;
  status: AIPlanStepStatus;
  attempt_count: number;
  max_attempts: number;
  result: Record<string, unknown>;
  selection_reason?: string | null;
  evidence_result?: {
    evidence_codes?: string[];
    summary?: string;
    conclusive?: boolean;
    needs_followup?: boolean;
  } | Record<string, unknown>;
  is_dynamic?: boolean;
  error_message?: string | null;
};

export type AISessionEvent = {
  id: string;
  event_type: string;
  message: string;
  metadata: Record<string, unknown>;
  actor_type: string;
  created_at: string;
};

export type AIApproval = {
  id: string;
  plan_step_id: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  requested_at: string;
  decided_at?: string | null;
  decision_reason?: string | null;
};

export type AIDiagnosticSession = {
  id: string;
  ticket_id: string;
  customer_message: string;
  channel: string;
  autonomy_level: AIAutonomyLevel;
  status: AISessionStatus;
  category?: string | null;
  priority?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | null;
  confidence?: number | null;
  current_risk_level: AIRiskLevel;
  resolution_summary?: string | null;
  escalation_reason?: string | null;
  failure_reason?: string | null;
  max_steps: number;
  executed_steps: number;
  consecutive_failures: number;
  simulation_scenario: string;
  hypotheses: AIHypothesis[];
  plan_steps: AIPlanStep[];
  approvals: AIApproval[];
  events: AISessionEvent[];
  last_decision?: string | null;
  decision_reason?: string | null;
  recommended_tool?: string | null;
  final_confidence?: number | null;
};
