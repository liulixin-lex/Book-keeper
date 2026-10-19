"""OAuth 2.1 for remote MCP clients: registered clients, pending requests, codes, refresh tokens.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=True),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column("registration", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False),
        sa.Column("registered_ip", postgresql.INET(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("client_id", name=op.f("pk_oauth_clients")),
    )
    op.create_table(
        "oauth_requests",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False),
        sa.Column("csrf", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"], ["oauth_clients.client_id"], name=op.f("fk_oauth_requests_client_id_oauth_clients")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_oauth_requests_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_requests")),
    )
    op.create_table(
        "oauth_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("preset", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("preset IN ('reader','bookkeeper','admin')", name=op.f("ck_oauth_codes_preset")),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_oauth_codes_book_id_books")),
        sa.ForeignKeyConstraint(
            ["client_id"], ["oauth_clients.client_id"], name=op.f("fk_oauth_codes_client_id_oauth_clients")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_oauth_codes_user_id_users")),
        sa.PrimaryKeyConstraint("code_hash", name=op.f("pk_oauth_codes")),
    )
    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("preset", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("api_token_id", sa.Text(), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("preset IN ('reader','bookkeeper','admin')", name=op.f("ck_oauth_refresh_tokens_preset")),
        sa.ForeignKeyConstraint(
            ["api_token_id"], ["api_tokens.id"], name=op.f("fk_oauth_refresh_tokens_api_token_id_api_tokens")
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_oauth_refresh_tokens_book_id_books")),
        sa.ForeignKeyConstraint(
            ["client_id"], ["oauth_clients.client_id"], name=op.f("fk_oauth_refresh_tokens_client_id_oauth_clients")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_oauth_refresh_tokens_user_id_users")),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_oauth_refresh_tokens")),
    )
    op.create_index(
        op.f("ix_oauth_refresh_tokens_api_token_id"), "oauth_refresh_tokens", ["api_token_id"], unique=False
    )
    op.create_index(op.f("ix_oauth_refresh_tokens_family_id"), "oauth_refresh_tokens", ["family_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_oauth_refresh_tokens_family_id"), table_name="oauth_refresh_tokens")
    op.drop_index(op.f("ix_oauth_refresh_tokens_api_token_id"), table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_table("oauth_codes")
    op.drop_table("oauth_requests")
    op.drop_table("oauth_clients")
