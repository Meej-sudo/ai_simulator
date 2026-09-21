"""Add persisted real-time simulation clock state.

Revision ID: 0003_session_clock
Revises: 0002_session_scenario_snapshot
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_session_clock"
down_revision = "0002_session_scenario_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "simulation_sessions",
        sa.Column(
            "clock_running",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "simulation_sessions",
        sa.Column("clock_last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "simulation_sessions",
        sa.Column(
            "clock_remainder_seconds",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("simulation_sessions", "clock_remainder_seconds")
    op.drop_column("simulation_sessions", "clock_last_synced_at")
    op.drop_column("simulation_sessions", "clock_running")
