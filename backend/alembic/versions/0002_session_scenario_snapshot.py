"""Pin sessions to immutable compiled scenario snapshots.

Revision ID: 0002_session_scenario_snapshot
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_session_scenario_snapshot"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "simulation_sessions",
        sa.Column("scenario_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "simulation_sessions",
        sa.Column(
            "scenario_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("simulation_sessions", "scenario_snapshot")
    op.drop_column("simulation_sessions", "scenario_version")
