"""Books (账套) and membership."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookkeeper.db.models import Book, BookMember, Commodity, User
from bookkeeper.domain.errors import DomainError, not_found, version_conflict
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Role, Scope
from bookkeeper.services import audit, setup
from bookkeeper.services.context import RequestContext

EDITABLE_FIELDS = (
    "name",
    "timezone",
    "rounding_mode",
    "fiscal_year_start_month",
    "journal_codes",
    "rounding_tolerance_per_line",
    "fx_lookback_days",
    "settings",
)


def book_view(book: Book) -> dict[str, Any]:
    return {
        "id": book.id,
        "name": book.name,
        "base_commodity": book.base_commodity,
        "timezone": book.timezone,
        "rounding_mode": book.rounding_mode,
        "fiscal_year_start_month": book.fiscal_year_start_month,
        "journal_codes": list(book.journal_codes),
        "rounding_tolerance_per_line": book.rounding_tolerance_per_line,
        "fx_lookback_days": book.fx_lookback_days,
        "settings": book.settings,
        "status": book.status,
        "version": book.version,
    }


def _check_timezone(name: str) -> None:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DomainError("VALIDATION_FAILED", f"时区 {name} 无效。") from exc


def create_book(
    session: Session,
    ctx: RequestContext,
    *,
    name: str,
    base_commodity: str = "CNY",
    timezone: str = "Asia/Shanghai",
    owner_user_id: str | None = None,
    template: str | None = "small_enterprise_v1",
) -> Book:
    ctx.require_superadmin()
    _check_timezone(timezone)
    commodity = session.get(Commodity, base_commodity)
    if commodity is None or commodity.kind != "fiat":
        raise DomainError("VALIDATION_FAILED", f"本位币 {base_commodity} 必须是已定义的法币。")
    owner_id = owner_user_id or ctx.actor.user_id
    if owner_id is None or session.get(User, owner_id) is None:
        raise DomainError("VALIDATION_FAILED", "必须指定账套所有者。")
    book = Book(id=new_id("bk"), name=name.strip(), base_commodity=base_commodity, timezone=timezone)
    session.add(book)
    session.flush()
    session.add(BookMember(book_id=book.id, user_id=owner_id, role=Role.OWNER.value))
    session.flush()
    ctx.book_id = book.id
    audit.record(session, ctx, "book.create", "book", book.id, after=book_view(book))
    audit.record(session, ctx, "member.set", "book_member", owner_id, after={"role": "owner"})
    setup.initialize_book(session, ctx, template)
    return book


def get_book(session: Session, book_id: str) -> Book:
    book = session.get(Book, book_id)
    if book is None:
        raise not_found("账套", book_id)
    return book


def list_books_for_user(session: Session, user_id: str) -> list[tuple[Book, str]]:
    rows = session.execute(
        select(Book, BookMember.role)
        .join(BookMember, BookMember.book_id == Book.id)
        .where(BookMember.user_id == user_id)
        .order_by(Book.created_at)
    ).all()
    return [(row[0], row[1]) for row in rows]


def update_book(session: Session, ctx: RequestContext, expected_version: int, changes: dict[str, Any]) -> Book:
    ctx.require(Scope.ADMIN)
    book = session.get(Book, ctx.require_book(), with_for_update=True)
    if book is None:
        raise not_found("账套", ctx.require_book())
    if book.version != expected_version:
        raise version_conflict("账套", expected_version, book.version)
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise DomainError("VALIDATION_FAILED", f"不可修改的字段：{', '.join(sorted(unknown))}。")
    if "timezone" in changes:
        _check_timezone(changes["timezone"])
    before = book_view(book)
    for field, value in changes.items():
        setattr(book, field, value)
    book.version += 1
    session.flush()
    audit.record(session, ctx, "book.update", "book", book.id, before=before, after=book_view(book))
    return book


def list_members(session: Session, ctx: RequestContext) -> list[tuple[BookMember, User]]:
    ctx.require(Scope.ADMIN_READ)
    rows = session.execute(
        select(BookMember, User)
        .join(User, User.id == BookMember.user_id)
        .where(BookMember.book_id == ctx.require_book())
        .order_by(BookMember.created_at)
    ).all()
    return [(row[0], row[1]) for row in rows]


def _owner_count(session: Session, book_id: str) -> int:
    return session.execute(
        select(func.count()).where(BookMember.book_id == book_id, BookMember.role == "owner")
    ).scalar_one()


def set_member(session: Session, ctx: RequestContext, user_id: str, role: Role) -> BookMember:
    ctx.require(Scope.ADMIN)
    book_id = ctx.require_book()
    if session.get(User, user_id) is None:
        raise not_found("用户", user_id)
    if role is Role.OWNER and ctx.actor.role is not Role.OWNER:
        raise DomainError("FORBIDDEN_SCOPE", "只有所有者可以授予所有者角色。")
    member = session.get(BookMember, (book_id, user_id), with_for_update=True)
    before = {"role": member.role} if member else None
    if member is None:
        member = BookMember(book_id=book_id, user_id=user_id, role=role.value)
        session.add(member)
    else:
        if member.role == "owner" and role is not Role.OWNER:
            if ctx.actor.role is not Role.OWNER:
                raise DomainError("FORBIDDEN_SCOPE", "只有所有者可以变更所有者的角色。")
            if _owner_count(session, book_id) <= 1:
                raise DomainError("INVALID_STATE", "账套至少需要一位所有者。")
        member.role = role.value
    session.flush()
    audit.record(
        session,
        ctx,
        "member.set",
        "book_member",
        user_id,
        before=before,
        after={"role": role.value},
    )
    return member


def remove_member(session: Session, ctx: RequestContext, user_id: str) -> None:
    ctx.require(Scope.ADMIN)
    book_id = ctx.require_book()
    member = session.get(BookMember, (book_id, user_id), with_for_update=True)
    if member is None:
        raise not_found("成员", user_id)
    if member.role == "owner":
        if ctx.actor.role is not Role.OWNER:
            raise DomainError("FORBIDDEN_SCOPE", "只有所有者可以移除所有者。")
        if _owner_count(session, book_id) <= 1:
            raise DomainError("INVALID_STATE", "账套至少需要一位所有者。")
    session.delete(member)
    session.flush()
    audit.record(session, ctx, "member.remove", "book_member", user_id, before={"role": member.role})
