"""Add S3-compatible backup configuration and run history.

Revision ID: 0014_backup_storage
Revises: 0013_soft_delete_users
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_backup_storage"
down_revision: str | None = "0013_soft_delete_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "backup_settings" not in table_names:
        op.create_table(
            "backup_settings",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("storage_type", sa.String(length=16), nullable=False),
            sa.Column("endpoint_url", sa.String(length=1024)),
            sa.Column("region", sa.String(length=120), nullable=False),
            sa.Column("bucket", sa.String(length=255), nullable=False),
            sa.Column("access_key_id", sa.String(length=512), nullable=False),
            sa.Column("encrypted_secret_access_key", sa.Text()),
            sa.Column("prefix", sa.String(length=512), nullable=False),
            sa.Column("force_path_style", sa.Boolean(), nullable=False),
            sa.Column("schedule_enabled", sa.Boolean(), nullable=False),
            sa.Column("cron_expression", sa.String(length=120), nullable=False),
            sa.Column("retain_days", sa.Integer(), nullable=False),
            sa.Column("retain_count", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("updated_by_id", sa.String(length=36)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "storage_type IN ('s3', 'r2')", name="ck_backup_storage_type"
            ),
            sa.CheckConstraint("retain_days >= 0", name="ck_backup_retain_days"),
            sa.CheckConstraint("retain_count >= 0", name="ck_backup_retain_count"),
            sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "backup_runs" not in table_names:
        op.create_table(
            "backup_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("trigger", sa.String(length=24), nullable=False),
            sa.Column("active_slot", sa.String(length=40)),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("object_key", sa.String(length=1024)),
            sa.Column("size_bytes", sa.Integer()),
            sa.Column("checksum_sha256", sa.String(length=64)),
            sa.Column("error_message", sa.String(length=1000)),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True)),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.CheckConstraint(
                "status IN ('running', 'completed', 'failed')",
                name="ck_backup_run_status",
            ),
            sa.CheckConstraint(
                "trigger IN ('manual', 'scheduled')", name="ck_backup_run_trigger"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("active_slot"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("backup_runs")}
    if "ix_backup_runs_started_at" not in indexes:
        op.create_index("ix_backup_runs_started_at", "backup_runs", ["started_at"])


def downgrade() -> None:
    bind = op.get_bind()
    table_names = set(sa.inspect(bind).get_table_names())
    if "backup_runs" in table_names:
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("backup_runs")}
        if "ix_backup_runs_started_at" in indexes:
            op.drop_index("ix_backup_runs_started_at", table_name="backup_runs")
        op.drop_table("backup_runs")
    if "backup_settings" in table_names:
        op.drop_table("backup_settings")
