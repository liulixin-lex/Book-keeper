"""Import sources read printed redeem pages (PDF) and, with a key configured, screenshots through AI.

An AI read runs on the worker: its batch is ``extracting`` until the records arrive, ``failed`` if the read
failed (it can be retried or set aside).

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "kind IN ('wechat_bill','alipay_bill','stripe_balance','card_shop_orders','upstream_usage_log',"
    "'generic_tabular','records')"
)
NEW = (
    "kind IN ('wechat_bill','alipay_bill','stripe_balance','card_shop_orders','upstream_usage_log',"
    "'generic_tabular','records','redeem_page','ai_extract')"
)


BATCH_OLD = "status IN ('parsed','committed','reverted')"
BATCH_NEW = "status IN ('extracting','failed','parsed','committed','reverted')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_import_sources_kind"), "import_sources", type_="check")
    op.create_check_constraint(op.f("ck_import_sources_kind"), "import_sources", NEW)
    op.drop_constraint(op.f("ck_import_batches_status"), "import_batches", type_="check")
    op.create_check_constraint(op.f("ck_import_batches_status"), "import_batches", BATCH_NEW)


def downgrade() -> None:
    op.execute("UPDATE import_batches SET status = 'reverted' WHERE status IN ('extracting', 'failed')")
    op.drop_constraint(op.f("ck_import_batches_status"), "import_batches", type_="check")
    op.create_check_constraint(op.f("ck_import_batches_status"), "import_batches", BATCH_OLD)
    op.execute(
        "DELETE FROM import_sources WHERE kind IN ('redeem_page','ai_extract') AND NOT EXISTS ("
        "SELECT 1 FROM import_batches b WHERE b.source_id = import_sources.id)"
    )
    op.drop_constraint(op.f("ck_import_sources_kind"), "import_sources", type_="check")
    op.create_check_constraint(op.f("ck_import_sources_kind"), "import_sources", OLD)
