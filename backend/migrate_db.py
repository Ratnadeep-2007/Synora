"""Lightweight schema migration helper for local/dev deployments.

Production should use a real migration tool once the schema stabilizes. This script
keeps existing SQLite and PostgreSQL databases compatible with the current Synora
schema without dropping data.
"""
from sqlalchemy import inspect, text

from app.core.database import engine
import app.models  # noqa: F401  # register all models with SQLAlchemy metadata


def add_column_if_missing(conn, table: str, column: str, ddl: str) -> None:
    inspector = inspect(conn)
    if table not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns(table)}
    if column not in columns:
        print(f"Adding {table}.{column} ...")
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def main() -> None:
    with engine.begin() as conn:
        add_column_if_missing(conn, "meetings", "workspace_id", "VARCHAR(64) DEFAULT 'ws_default'")
        add_column_if_missing(conn, "meetings", "source_connection_id", "VARCHAR(64)")

        add_column_if_missing(conn, "candidate_knowledge", "context_status", "VARCHAR(32) DEFAULT 'resolved'")
        add_column_if_missing(conn, "candidate_knowledge", "context_confidence", "FLOAT DEFAULT 1.0")
        add_column_if_missing(conn, "candidate_knowledge", "context_model", "VARCHAR(128)")

        add_column_if_missing(conn, "agent_runs", "source", "VARCHAR(64)")
        add_column_if_missing(conn, "agent_runs", "context_status", "VARCHAR(32)")

    # Create tables that were introduced after the original database bootstrap.
    app.models  # noqa: B018
    from app.core.database import Base
    Base.metadata.create_all(bind=engine)
    print("Synora database migration complete.")


if __name__ == "__main__":
    main()
