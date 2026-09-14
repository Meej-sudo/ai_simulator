"""Create simulation session and append-only event tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulation_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scenario_id", sa.String(length=100), nullable=False),
        sa.Column("variant_id", sa.String(length=100), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("simulation_time", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_simulation_sessions_scenario_id",
        "simulation_sessions",
        ["scenario_id"],
    )
    op.create_table(
        "session_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("simulation_time", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("actor_role", sa.String(length=100), nullable=True),
        sa.Column("target_role", sa.String(length=100), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["simulation_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_session_event_sequence"),
    )
    op.create_index("ix_session_events_event_type", "session_events", ["event_type"])
    op.create_index("ix_session_events_session_id", "session_events", ["session_id"])
    op.create_index(
        "ix_session_events_replay", "session_events", ["session_id", "sequence"]
    )


def downgrade() -> None:
    op.drop_table("session_events")
    op.drop_table("simulation_sessions")
