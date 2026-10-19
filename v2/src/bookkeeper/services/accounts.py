"""Chart of accounts (docs/14-taxonomy-and-copy.md §3)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from bookkeeper.db.models import Account, AccountBalance, Commodity
from bookkeeper.domain import chart
from bookkeeper.domain.errors import DomainError, not_found, version_conflict
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.ledger import AccountInfo
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit
from bookkeeper.services.context import RequestContext

EDITABLE = (
    "name",
    "role",
    "is_default_for_role",
    "allowed_commodities",
    "open_date",
    "close_date",
    "balance_rule",
    "manual_entry_allowed",
    "required_dimensions",
    "forbidden_dimensions",
    "standard_code",
    "is_active",
    "description",
    "is_group",
)


def account_view(item: Account, parent_code: str | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "parent_id": item.parent_id,
        "parent_code": parent_code,
        "level": item.level,
        "is_group": item.is_group,
        "classification": item.classification,
        "normal_side": item.normal_side,
        "role": item.role,
        "is_default_for_role": item.is_default_for_role,
        "allowed_commodities": item.allowed_commodities,
        "open_date": _iso(item.open_date),
        "close_date": _iso(item.close_date),
        "balance_rule": item.balance_rule,
        "manual_entry_allowed": item.manual_entry_allowed,
        "required_dimensions": list(item.required_dimensions),
        "forbidden_dimensions": list(item.forbidden_dimensions),
        "standard_code": item.standard_code,
        "is_system": item.is_system,
        "is_active": item.is_active,
        "description": item.description,
        "version": item.version,
    }


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def to_info(item: Account) -> AccountInfo:
    return AccountInfo(
        id=item.id,
        code=item.code,
        name=item.name,
        classification=item.classification,
        normal_side=item.normal_side,
        role=item.role,
        is_group=item.is_group,
        is_active=item.is_active,
        allowed_commodities=tuple(item.allowed_commodities) if item.allowed_commodities is not None else None,
        open_date=item.open_date,
        close_date=item.close_date,
        manual_entry_allowed=item.manual_entry_allowed,
        required_dimensions=tuple(item.required_dimensions),
        forbidden_dimensions=tuple(item.forbidden_dimensions),
        balance_rule=item.balance_rule,
    )


def _db_error(exc: Exception) -> DomainError:
    orig = getattr(exc, "orig", exc)
    message = str(orig).split("\n")[0]
    if getattr(orig, "sqlstate", None) == "23505":
        return DomainError("CONFLICT", f"科目与现有数据冲突：{message}")
    return DomainError("VALIDATION_FAILED", f"科目设置不符合规则：{message}")


def apply_template(session: Session, ctx: RequestContext, template: str = "small_enterprise_v1") -> list[Account]:
    """Create the template's accounts that do not exist yet (idempotent)."""
    ctx.require(Scope.CONFIG_WRITE)
    if template not in chart.CHART_TEMPLATES:
        raise DomainError("VALIDATION_FAILED", f"未知科目表模板 {template}。")
    book_id = ctx.require_book()
    existing = {a.code: a for a in session.execute(select(Account).where(Account.book_id == book_id)).scalars()}
    default_roles = {a.role for a in existing.values() if a.is_default_for_role}
    created: list[Account] = []
    for spec in chart.CHART_TEMPLATES[template]:
        if spec.code in existing:
            continue
        parent_code = chart.parent_code(spec.code)
        parent = existing.get(parent_code) if parent_code else None
        item = Account(
            id=new_id("acc"),
            book_id=book_id,
            code=spec.code,
            name=spec.name,
            parent_id=parent.id if parent else None,
            is_group=spec.is_group,
            classification=spec.classification,
            normal_side=spec.normal_side,
            role=spec.role,
            is_default_for_role=spec.role is not None and spec.role not in default_roles,
            manual_entry_allowed=spec.manual_entry_allowed,
            standard_code=spec.standard_code,
            is_system=spec.is_system,
            description=spec.description,
        )
        session.add(item)
        session.flush()
        if item.is_default_for_role:
            default_roles.add(spec.role)
        existing[spec.code] = item
        created.append(item)
    if created:
        audit.record(
            session,
            ctx,
            "chart.apply_template",
            "book",
            book_id,
            after={"template": template, "created": [a.code for a in created]},
        )
    return created


def create_account(session: Session, ctx: RequestContext, data: dict[str, Any]) -> Account:
    ctx.require(Scope.CONFIG_WRITE)
    book_id = ctx.require_book()
    code = data["code"]
    if not chart.CODE_RE.match(code):
        raise DomainError("VALIDATION_FAILED", "科目编码格式应为 4 位数字加若干“.两位数字”，如 5401.05。")
    classification = data.get("classification")
    parent = None
    parent_code = chart.parent_code(code)
    if parent_code:
        parent = session.execute(
            select(Account).where(Account.book_id == book_id, Account.code == parent_code)
        ).scalar_one_or_none()
        if parent is None:
            raise DomainError("VALIDATION_FAILED", f"上级科目 {parent_code} 不存在。")
        classification = classification or parent.classification
    if classification not in chart.CLASSIFICATIONS:
        raise DomainError("VALIDATION_FAILED", "必须给出科目分类（asset/liability/equity/revenue/expense）。")
    role = data.get("role")
    if role is not None and role not in chart.ROLES:
        raise DomainError("VALIDATION_FAILED", f"未知科目角色 {role}。")
    if role in chart.SYSTEM_ROLES:
        raise DomainError("VALIDATION_FAILED", f"系统角色 {role} 只能由模板创建。")
    _check_commodities(session, data.get("allowed_commodities"))
    item = Account(
        id=new_id("acc"),
        book_id=book_id,
        code=code,
        name=data["name"].strip(),
        parent_id=parent.id if parent else None,
        classification=classification,
        normal_side=data.get("normal_side") or chart.NORMAL_SIDE[classification],
        role=role,
        standard_code=data.get("standard_code") or code.split(".")[0],
    )
    for key in EDITABLE:
        if key in data and key not in ("role",):
            setattr(item, key, data[key])
    session.add(item)
    try:
        with session.begin_nested():
            session.flush()
    except (IntegrityError, DBAPIError) as exc:
        raise _db_error(exc) from exc
    audit.record(session, ctx, "account.create", "account", item.id, after=account_view(item, parent_code))
    return item


def update_account(
    session: Session,
    ctx: RequestContext,
    account_id: str,
    expected_version: int,
    changes: dict[str, Any],
) -> Account:
    ctx.require(Scope.CONFIG_WRITE)
    item = get_account(session, ctx.require_book(), account_id, lock=True)
    if item.version != expected_version:
        raise version_conflict("科目", expected_version, item.version)
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise DomainError("VALIDATION_FAILED", f"不可修改的字段：{', '.join(sorted(unknown))}。")
    if item.is_system and ({"role", "is_default_for_role", "is_group"} & set(changes)):
        raise DomainError("VALIDATION_FAILED", "系统科目不能修改角色或分组属性。")
    if "role" in changes and changes["role"] is not None and changes["role"] not in chart.ROLES:
        raise DomainError("VALIDATION_FAILED", f"未知科目角色 {changes['role']}。")
    if changes.get("role") in chart.SYSTEM_ROLES:
        raise DomainError("VALIDATION_FAILED", f"系统角色 {changes['role']} 只能由模板创建。")
    _check_commodities(session, changes.get("allowed_commodities"))
    before = account_view(item)
    for key, value in changes.items():
        setattr(item, key, value)
    item.version += 1
    try:
        with session.begin_nested():
            session.flush()
    except (IntegrityError, DBAPIError) as exc:
        raise _db_error(exc) from exc
    audit.record(session, ctx, "account.update", "account", item.id, before=before, after=account_view(item))
    return item


def _check_commodities(session: Session, codes: list[str] | None) -> None:
    if not codes:
        return
    known = set(session.execute(select(Commodity.code)).scalars())
    unknown = set(codes) - known
    if unknown:
        raise DomainError("VALIDATION_FAILED", f"未知币种：{', '.join(sorted(unknown))}。")


def get_account(session: Session, book_id: str, ref: str, *, lock: bool = False) -> Account:
    stmt = select(Account).where(Account.book_id == book_id, or_(Account.id == ref, Account.code == ref))
    if lock:
        stmt = stmt.with_for_update()
    item = session.execute(stmt).scalar_one_or_none()
    if item is None:
        raise not_found("科目", ref)
    return item


def list_accounts(
    session: Session,
    book_id: str,
    *,
    query: str | None = None,
    role: str | None = None,
    classification: str | None = None,
    postable_only: bool = False,
) -> list[Account]:
    stmt = select(Account).where(Account.book_id == book_id)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(or_(Account.code.like(f"{query.strip()}%"), Account.name.ilike(like)))
    if role:
        stmt = stmt.where(Account.role == role)
    if classification:
        stmt = stmt.where(Account.classification == classification)
    if postable_only:
        stmt = stmt.where(Account.is_group.is_(False), Account.is_active.is_(True))
    return list(session.execute(stmt.order_by(Account.code)).scalars())


def default_for_role(session: Session, book_id: str, role: str) -> Account | None:
    return session.execute(
        select(Account).where(Account.book_id == book_id, Account.role == role, Account.is_default_for_role.is_(True))
    ).scalar_one_or_none()


def current_balances(session: Session, account_id: str) -> list[AccountBalance]:
    return list(
        session.execute(
            select(AccountBalance).where(AccountBalance.account_id == account_id).order_by(AccountBalance.commodity)
        ).scalars()
    )
