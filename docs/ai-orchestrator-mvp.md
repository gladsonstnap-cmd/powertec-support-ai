# AI Orchestrator MVP

## Objective

The first AI Orchestrator delivery adds a deterministic, simulation-only diagnostic workflow for support tickets. It classifies a customer problem, creates hypotheses, builds a diagnostic plan, executes simulated tools, records audit events and decides whether to continue, wait for approval, resolve, escalate, fail or cancel.

No command is executed on a customer computer in this MVP.

## Architecture

- FastAPI routes live in `backend/app/api/v1/endpoints/ai_sessions.py`.
- SQLAlchemy models live in `backend/app/models/ai_orchestrator.py`.
- Pydantic schemas live in `backend/app/schemas/ai_orchestrator.py`.
- Business logic lives in `backend/app/services/ai_orchestrator/`.
- The frontend ticket integration lives in `frontend/components/ai-diagnostic-panel.tsx`.
- The ticket list embeds the panel inside the existing expanded ticket row.

## Entities

- `ai_diagnostic_sessions`: session lifecycle, classification, risk, counters and final decision.
- `ai_hypotheses`: ranked deterministic hypotheses with probabilities.
- `ai_plan_steps`: simulated tool steps, parameters, attempts, result and status.
- `ai_session_events`: immutable audit timeline.
- `ai_approvals`: approval decisions for safe simulated actions.

All entities are tenant-scoped and tied to the current authenticated user's tenant.

## State Machine

Valid session states include `RECEIVED`, `CLASSIFYING`, `PLANNING`, `READY`, `RUNNING`, `WAITING_TOOL`, `ANALYZING_RESULT`, `WAITING_APPROVAL`, `RESOLVED`, `ESCALATED`, `FAILED` and `CANCELLED`.

Invalid transitions such as `RESOLVED -> RUNNING` are rejected by the explicit state machine in `state_machine.py`. Every accepted transition writes an audit event.

## Security Policies

The policy engine enforces:

- `READ_ONLY` tools may run automatically.
- `SAFE_ACTION` tools are blocked in `DIAGNOSTIC_ONLY`.
- `SAFE_ACTION` tools require approval in `SAFE_ACTIONS_WITH_APPROVAL`.
- `SAFE_ACTIONS_AUTOMATIC` only permits explicitly allow-listed safe actions.
- `RESTRICTED` and `BLOCKED` actions never run through this flow.
- Unknown tools are rejected.
- Dangerous parameters such as `command`, `shell`, `powershell`, `cmd`, `bash`, `script`, `eval` and `executable` are rejected.
- Unsupported parameters are rejected.

## Simulated Tools

The central tool registry exposes:

- `system.inventory`
- `network.ping`
- `network.dns_lookup`
- `network.test_port`
- `windows.service_status`
- `windows.event_logs`
- `printer.list`
- `disk.health`
- `knowledge.search`
- `windows.service_restart`

All tools return standardized simulated results and accept only controlled scenarios: `healthy`, `sql_service_stopped`, `dns_failure`, `port_blocked`, `disk_low_space`, `printer_offline` and `unknown_failure`.

## Approval Flow

When a step such as `windows.service_restart` is reached under `SAFE_ACTIONS_WITH_APPROVAL`, the session moves to `WAITING_APPROVAL`, a pending `ai_approvals` record is created and the frontend shows the action, risk and evidence. Approval executes the simulated tool; rejection escalates the session.

## Endpoints

- `POST /api/v1/ai-sessions`
- `GET /api/v1/ai-sessions`
- `GET /api/v1/ai-sessions/{session_id}`
- `POST /api/v1/ai-sessions/{session_id}/run`
- `POST /api/v1/ai-sessions/{session_id}/approve`
- `POST /api/v1/ai-sessions/{session_id}/reject`
- `POST /api/v1/ai-sessions/{session_id}/cancel`
- `GET /api/v1/ai-sessions/{session_id}/events`

## Migrations

Run:

```bash
cd backend
alembic upgrade head
```

The migration is `0004_ai_orchestrator.py` and includes upgrade/downgrade, indexes for tenant, ticket, session, status and created timestamps, plus foreign keys.

## Tests

Run backend tests:

```bash
python -m pytest -q
```

Run frontend tests:

```bash
pnpm --dir frontend test
pnpm --dir frontend exec tsc --noEmit
```

## Current Limitations

- The classifier and planner are deterministic rule-based implementations.
- No real remote agent exists.
- No real PowerShell, CMD, service restart, file operation, browser automation or OS access is executed.
- The frontend starts sessions from the ticket row using the existing ticket context.

## Next Steps

- Add a real remote-agent protocol after explicit security review.
- Add richer technician permissions.
- Add asynchronous orchestration with Celery if sessions become long-running.
- Add real AI provider planning behind the same validated schemas.
