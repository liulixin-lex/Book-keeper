"""Add deterministic AI workbench and knowledge indexing tables.

Revision ID: 0012_ai_workbench
Revises: 0011_add_usernames
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_ai_workbench"
down_revision: str | None = "0011_add_usernames"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "ai_workflows" in existing_tables:
        if bind.dialect.name == "sqlite":
            op.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
                "document_id UNINDEXED, workspace_id UNINDEXED, content_text, "
                "tokenize='unicode61')"
            )
        return
    op.create_table(
        "ai_workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("provider_id", sa.String(36), sa.ForeignKey("ai_providers.id")),
        sa.Column("command", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("canonical_hash", sa.String(64)),
        sa.Column("selected_proposal_ids", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("confirmed_by_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_ai_workflows_expires_at", "ai_workflows", ["expires_at"])
    op.create_index(
        "ix_ai_workflow_scope_status",
        "ai_workflows",
        ["workspace_id", "created_by_id", "status"],
    )
    op.create_table(
        "ai_workflow_inputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("ai_workflows.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("text_content", sa.Text()),
        sa.Column("filename", sa.String(500)),
        sa.Column("mime_type", sa.String(200)),
        sa.Column("sha256", sa.String(64)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("temporary_path", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("workflow_id", "sequence", name="uq_ai_workflow_input_sequence"),
    )
    op.create_table(
        "document_extractions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workflow_input_id",
            sa.String(36),
            sa.ForeignKey("ai_workflow_inputs.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("parser", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("structure_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "ledger_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("ai_workflows.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("record_type", sa.String(32)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("fields_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("journal_preview_json", sa.JSON(), nullable=False),
        sa.Column("duplicate_json", sa.JSON(), nullable=False),
        sa.Column("entity_versions_json", sa.JSON(), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("canonical_hash", sa.String(64)),
        sa.Column("committed_record_id", sa.String(36), sa.ForeignKey("business_records.id")),
        sa.Column("approval_id", sa.String(36), sa.ForeignKey("approval_requests.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("workflow_id", "sequence", name="uq_ledger_proposal_sequence"),
    )
    op.create_table(
        "ai_workflow_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("ai_workflows.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("workflow_id", "sequence", name="uq_ai_workflow_event_sequence"),
    )
    op.create_table(
        "ai_plugin_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("plugin_id", sa.String(160), nullable=False),
        sa.Column("plugin_version", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("health_status", sa.String(32), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("updated_by_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("workspace_id", "plugin_id", name="uq_ai_plugin_state"),
    )
    op.create_table(
        "ai_embedding_providers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("base_url", sa.String(1024), nullable=False),
        sa.Column("model", sa.String(240), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("encrypted_api_key", sa.Text()),
        sa.Column("api_key_source", sa.String(24), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.Column("pending_index_version", sa.Integer()),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("last_test_status", sa.String(40)),
        sa.Column("last_test_error", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("dimension > 0", name="ck_ai_embedding_dimension_positive"),
        sa.CheckConstraint("batch_size > 0", name="ck_ai_embedding_batch_positive"),
        sa.CheckConstraint(
            "api_key_source IN ('none', 'database', 'environment')",
            name="ck_ai_embedding_provider_key_source",
        ),
        sa.UniqueConstraint("workspace_id", "name", name="uq_ai_embedding_provider_name"),
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(80), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("acl_scope", sa.String(40), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "workspace_id", "entity_type", "entity_id", name="uq_knowledge_document_entity"
        ),
    )
    op.create_index("ix_knowledge_documents_deleted_at", "knowledge_documents", ["deleted_at"])
    op.create_index(
        "ix_knowledge_document_scope",
        "knowledge_documents",
        ["workspace_id", "entity_type", "deleted_at"],
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id", sa.String(36), sa.ForeignKey("knowledge_documents.id"), nullable=False
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("embedding_index_version", sa.Integer()),
        sa.Column("embedding_json", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_index"),
    )
    op.create_table(
        "knowledge_index_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(80), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("target_index_version", sa.Integer()),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_knowledge_index_jobs_available_at", "knowledge_index_jobs", ["available_at"]
    )
    op.create_index(
        "ix_knowledge_job_queue", "knowledge_index_jobs", ["status", "available_at", "created_at"]
    )
    if bind.dialect.name == "sqlite":
        op.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
            "document_id UNINDEXED, workspace_id UNINDEXED, content_text, tokenize='unicode61')"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TABLE IF EXISTS knowledge_fts")
    op.drop_table("knowledge_index_jobs")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("ai_embedding_providers")
    op.drop_table("ai_plugin_states")
    op.drop_table("ai_workflow_events")
    op.drop_table("ledger_proposals")
    op.drop_table("document_extractions")
    op.drop_table("ai_workflow_inputs")
    op.drop_table("ai_workflows")
