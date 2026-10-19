"""Privileges for the application role and the integrity objects it relies on (docs/04 §17).

Run after every migration (``bookkeeper migrate`` does this) so new tables are covered.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

APP_ROLE = "bk_app"

APPEND_ONLY_TABLES = ("audit_events", "journal_lines", "journal_line_dimensions")
READ_ONLY_TABLES = ("alembic_version",)
NO_DELETE_TABLES = ("commodities",)  # added and edited in the app; never deleted (amounts reference them)
COLUMN_UPDATE_TABLES: dict[str, tuple[str, ...]] = {
    "journal_entries": ("reversed_by_entry_id",),
}

REQUIRED_TRIGGERS: tuple[str, ...] = (
    "audit_events_immutable",
    "audit_events_no_truncate",
    "journal_lines_balanced",
    "journal_entries_balanced",
    "journal_entries_immutable",
    "journal_lines_immutable",
    "journal_entries_no_truncate",
    "journal_lines_no_truncate",
    "journal_line_dimensions_immutable",
    "journal_entries_insert",
    "journal_lines_insert",
    "accounts_guard",
    "commodities_guard",
)


def grant_app_role(conn: Connection, role: str = APP_ROLE) -> bool:
    """Apply grants if the role exists; returns whether it did."""
    exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
    if not exists:
        return False
    quoted = conn.dialect.identifier_preparer.quote(role)
    conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted}"))
    conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted}"))
    conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted}"))
    for table in APPEND_ONLY_TABLES:
        conn.execute(text(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM {quoted}"))
    for table in READ_ONLY_TABLES:
        conn.execute(text(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {table} FROM {quoted}"))
    for table in NO_DELETE_TABLES:
        conn.execute(text(f"REVOKE DELETE, TRUNCATE ON {table} FROM {quoted}"))
    for table, columns in COLUMN_UPDATE_TABLES.items():
        conn.execute(text(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM {quoted}"))
        conn.execute(text(f"GRANT UPDATE ({', '.join(columns)}) ON {table} TO {quoted}"))
    return True
