"""Initial content of a new book: chart, channels, transaction types."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bookkeeper.db.models import DimensionType, DimensionValue, TransactionType
from bookkeeper.domain import chart
from bookkeeper.domain.ids import new_id
from bookkeeper.services import accounts
from bookkeeper.services.context import Actor, RequestContext


def initialize_book(session: Session, ctx: RequestContext, template: str | None = "small_enterprise_v1") -> None:
    book_id = ctx.require_book()
    setup_ctx = RequestContext(
        actor=Actor(
            type=ctx.actor.type,
            user_id=ctx.actor.user_id,
            token_id=ctx.actor.token_id,
            role=ctx.actor.role,
            scopes=ctx.actor.scopes | Actor.system().scopes,
            is_superadmin=True,
        ),
        channel=ctx.channel,
        book_id=book_id,
        request_id=ctx.request_id,
        ip=ctx.ip,
        user_agent=ctx.user_agent,
        change_set_id=ctx.change_set_id,
    )
    if template:
        accounts.apply_template(session, setup_ctx, template)
    ctx.change_set_id = setup_ctx.change_set_id
    for definition in chart.TRANSACTION_TYPES:
        session.execute(
            insert(TransactionType)
            .values(
                id=new_id("tty"),
                book_id=book_id,
                code=definition.code,
                name=definition.name,
                category=definition.category,
                description=definition.description,
                is_system=True,
            )
            .on_conflict_do_nothing(index_elements=["book_id", "code"])
        )
    channel = session.execute(
        select(DimensionType).where(DimensionType.book_id == book_id, DimensionType.code == "channel")
    ).scalar_one_or_none()
    if channel is None:
        channel = DimensionType(id=new_id("dmt"), book_id=book_id, code="channel", name="渠道")
        session.add(channel)
        session.flush()
    for code, name in chart.CHANNELS:
        session.execute(
            insert(DimensionValue)
            .values(
                id=new_id("dmv"),
                book_id=book_id,
                type_id=channel.id,
                code=code,
                name=name,
                metadata_={"aliases": list(chart.CHANNEL_ALIASES[code])} if code in chart.CHANNEL_ALIASES else {},
            )
            .on_conflict_do_nothing(index_elements=["type_id", "code"])
        )
    session.flush()
