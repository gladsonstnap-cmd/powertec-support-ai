# AI Orchestrator Intelligence Sprint

## Objective

This sprint evolves the simulated AI Orchestrator from a static diagnostic plan into an adaptive evidence-based workflow. It remains fully deterministic, testable and simulation-only.

No real PowerShell, CMD, shell, remote access, browser automation, database command, file operation or external AI API is executed.

## Core Components

- `classifier.py`: deterministic incident classification.
- `hypothesis_engine.py`: probability normalization, evidence tracking and status updates.
- `planner.py`: initial plan creation and dynamic step drafts.
- `tool_selector.py`: next-tool selection using active hypotheses and tool metadata.
- `evaluator.py`: converts simulated tool results into evidence codes.
- `decision_engine.py`: structured decisions: `CONTINUE`, `WAIT_APPROVAL`, `RESOLVE`, `ESCALATE`.
- `policy.py`: safety policy for risk/autonomy.
- `state_machine.py`: explicit session transitions.
- `tools.py`: central simulated tool registry.
- `service.py`: orchestration, persistence and audit events.

## Classification

The deterministic classifier now recognizes:

- `NETWORK_SERVER`
- `DATABASE`
- `PRINTING`
- `WINDOWS_SERVICE`
- `DISK_STORAGE`
- `DNS`
- `APPLICATION`
- `FISCAL_DOCUMENT`
- `GENERAL_SUPPORT`
- `UNKNOWN`

It chooses specific categories when the message contains enough evidence. For example, "SQL Server nao inicia" becomes `DATABASE` with `WINDOWS_SERVICE` as secondary context, while "Nao resolve o nome do servidor" becomes `DNS`.

## Hypothesis Engine

Hypotheses now support:

- `supporting_evidence`
- `contradicting_evidence`
- `last_updated_reason`
- statuses such as `ACTIVE`, `SUPPORTED`, `CONFIRMED`, `WEAKENED`, `REJECTED`

Probabilities are deterministic, bounded between 0 and 1, normalized after updates and reranked after evidence changes.

Examples:

- `SERVER_REACHABLE` weakens `server_unreachable`.
- `DNS_RESOLVED` weakens `dns_failure`.
- `DB_PORT_CLOSED` strengthens `database_service_stopped` and `database_port_blocked`.
- `SERVICE_STOPPED` confirms `database_service_stopped`.
- `SERVICE_RUNNING` weakens `database_service_stopped`.

## Adaptive Planning

The initial plan prioritizes safe, read-only, high-value diagnostic tools. The restart step is no longer part of the initial `NETWORK_SERVER` plan.

For `sql_service_stopped`, the flow is:

1. `network.ping`
2. `network.dns_lookup`
3. `network.test_port`
4. `windows.service_status`
5. dynamically add `windows.service_restart` only after `SERVICE_STOPPED`
6. require approval
7. execute simulated restart
8. dynamically add post-action verification
9. resolve only after `SERVICE_RUNNING` or `DB_PORT_OPEN`

## Tool Selector

The selector scores pending steps using:

- strongest active hypothesis;
- tool ability to confirm/reject the hypothesis;
- diagnostic value;
- estimated cost;
- duplicate/repetition rules.

Tools cannot be invented because selection is constrained to the central registry. Repetition is allowed only for tools explicitly marked `can_repeat`, such as post-action verification.

## Evidence Evaluator

Tool results include `evidence_codes`, `data`, `evidence`, `message` and `simulation: true`.

The evaluator validates and summarizes results. Technical success means the simulated tool returned correctly; it does not mean the incident is resolved.

## Decision Engine

The engine returns structured decisions:

```json
{
  "decision": "CONTINUE",
  "reason": "Ainda ha etapas seguras pendentes para diferenciar as hipoteses.",
  "confidence": 0.82,
  "next_hypothesis": "database_service_stopped",
  "recommended_tool": "windows.service_status"
}
```

Resolution requires evidence of correction and a post-action verification. DNS failure, port blocked and printer offline are not falsely resolved because no safe correction tool exists in this sprint.

## Persistence

Migration `0005_ai_orchestrator_intelligence.py` adds:

- `ai_diagnostic_sessions.last_decision`
- `ai_diagnostic_sessions.decision_reason`
- `ai_diagnostic_sessions.recommended_tool`
- `ai_diagnostic_sessions.final_confidence`
- `ai_hypotheses.supporting_evidence`
- `ai_hypotheses.contradicting_evidence`
- `ai_hypotheses.last_updated_reason`
- `ai_plan_steps.selection_reason`
- `ai_plan_steps.evidence_result`
- `ai_plan_steps.is_dynamic`

Migration `0004` is not modified.

## Supported Scenarios

- `healthy`
- `sql_service_stopped`
- `dns_failure`
- `port_blocked`
- `disk_low_space`
- `printer_offline`
- `unknown_failure`
- `server_unreachable`
- `sql_service_running_but_port_blocked`
- `printer_spooler_stopped`
- `low_disk_after_cleanup`
- `conflicting_evidence`

## Frontend

The existing ticket expansion panel now shows:

- friendly labels for category, risk, status and decision;
- hypotheses ordered by probability;
- hypothesis status;
- supporting and contradicting evidence;
- last update reason;
- current orchestrator decision;
- decision reason;
- recommended tool;
- adaptive plan;
- dynamically added steps;
- summarized tool evidence;
- final resolution or escalation summary.

It remains operator-focused and continues to show the simulation warning.

## Limitations

- No remote agent exists yet.
- Corrective actions are simulated only.
- Firewall/DNS/printer physical remediation escalates instead of resolving.
- Classifier and planner are deterministic rule-based services.
- External AI providers remain optional future integrations.

## Remote Agent Readiness Risks

Before a real remote agent, the project still needs:

- stronger role-based approvals;
- signed agent protocol;
- command allow-list separate from diagnostics;
- environment attestation;
- tenant-scoped audit export;
- rollback and human override workflows;
- security review for every non-read-only action.
