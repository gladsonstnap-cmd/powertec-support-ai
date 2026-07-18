"""ai orchestrator adaptive intelligence

Revision ID: 0005_ai_intelligence
Revises: 0004_ai_orchestrator
Create Date: 2026-07-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_ai_intelligence"
down_revision = "0004_ai_orchestrator"
branch_labels = None
depends_on = None

JSON_EMPTY_OBJECT = sa.text("'{}'::json")
JSON_EMPTY_ARRAY = sa.text("'[]'::json")


def upgrade() -> None:
    op.add_column("ai_diagnostic_sessions", sa.Column("last_decision", sa.String(40)))
    op.add_column("ai_diagnostic_sessions", sa.Column("decision_reason", sa.Text()))
    op.add_column("ai_diagnostic_sessions", sa.Column("recommended_tool", sa.String(120)))
    op.add_column("ai_diagnostic_sessions", sa.Column("final_confidence", sa.Float()))
    op.add_column("ai_hypotheses", sa.Column("supporting_evidence", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY))
    op.add_column("ai_hypotheses", sa.Column("contradicting_evidence", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY))
    op.add_column("ai_hypotheses", sa.Column("last_updated_reason", sa.Text()))
    op.add_column("ai_plan_steps", sa.Column("selection_reason", sa.Text()))
    op.add_column("ai_plan_steps", sa.Column("evidence_result", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT))
    op.add_column("ai_plan_steps", sa.Column("is_dynamic", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("ai_plan_steps", "is_dynamic")
    op.drop_column("ai_plan_steps", "evidence_result")
    op.drop_column("ai_plan_steps", "selection_reason")
    op.drop_column("ai_hypotheses", "last_updated_reason")
    op.drop_column("ai_hypotheses", "contradicting_evidence")
    op.drop_column("ai_hypotheses", "supporting_evidence")
    op.drop_column("ai_diagnostic_sessions", "final_confidence")
    op.drop_column("ai_diagnostic_sessions", "recommended_tool")
    op.drop_column("ai_diagnostic_sessions", "decision_reason")
    op.drop_column("ai_diagnostic_sessions", "last_decision")
