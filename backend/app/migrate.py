"""Bring the application database to the latest Alembic revision."""

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.database import engine


BASELINE_REVISION = "0001_initial"
MANAGED_TABLES = {"simulation_sessions", "session_events"}


def main() -> None:
    tables = set(inspect(engine).get_table_names())
    managed_tables = tables & MANAGED_TABLES
    has_revision_table = "alembic_version" in tables

    if not has_revision_table and managed_tables:
        if managed_tables != MANAGED_TABLES:
            missing = sorted(MANAGED_TABLES - managed_tables)
            raise RuntimeError(
                "Cannot adopt a partially initialized legacy database; "
                f"missing tables: {", ".join(missing)}"
            )
        print(
            "Adopting legacy database schema at Alembic revision "
            f"{BASELINE_REVISION}."
        )
        command.stamp(Config("alembic.ini"), BASELINE_REVISION)

    command.upgrade(Config("alembic.ini"), "head")
    engine.dispose()


if __name__ == "__main__":
    main()
