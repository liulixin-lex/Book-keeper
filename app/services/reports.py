from collections import defaultdict
from datetime import date
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.amounts import RATE_SCALE, convert_cny_e8, from_e8, from_e12, to_e8
from app.enums import AccountType, JournalStatus, RecordType
from app.models import (
    Account,
    BusinessRecord,
    Category,
    Counterparty,
    JournalEntry,
    JournalLine,
    User,
    Workspace,
)
from app.schemas import (
    DailyReportRow,
    DashboardRateRead,
    DashboardReportRead,
    ExpenseUserSummary,
    OverviewRead,
)
from app.services.fx import DisplayRate

LedgerKey = tuple[date, str | None, str, str | None]
LedgerValue = tuple[int, int]

_CASH_IN_RECORD_TYPES = {RecordType.INCOME.value}
_CASH_OUT_RECORD_TYPES = {RecordType.EXPENSE.value, RecordType.REFUND.value}


def _aggregate(
    session: Session, workspace_id: str, start_date: date, end_date: date
) -> tuple[dict[LedgerKey, LedgerValue], int]:
    rows = session.execute(
        select(
            JournalEntry.entry_date,
            BusinessRecord.record_type,
            Account.account_type,
            Account.subtype,
            func.coalesce(func.sum(JournalLine.debit_cny_e8), 0),
            func.coalesce(func.sum(JournalLine.credit_cny_e8), 0),
        )
        .select_from(JournalEntry)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .join(Account, Account.id == JournalLine.account_id)
        .outerjoin(BusinessRecord, BusinessRecord.id == JournalEntry.record_id)
        .where(
            JournalEntry.workspace_id == workspace_id,
            JournalEntry.status == JournalStatus.POSTED,
            JournalEntry.entry_date.between(start_date, end_date),
        )
        .group_by(
            JournalEntry.entry_date,
            BusinessRecord.record_type,
            Account.account_type,
            Account.subtype,
        )
    ).all()
    values = {
        (
            row[0],
            str(row[1]) if row[1] is not None else None,
            str(row[2]),
            row[3],
        ): (int(row[4]), int(row[5]))
        for row in rows
    }
    count = session.scalar(
        select(func.count(JournalEntry.id)).where(
            JournalEntry.workspace_id == workspace_id,
            JournalEntry.status == JournalStatus.POSTED,
            JournalEntry.entry_date.between(start_date, end_date),
        )
    )
    return values, int(count or 0)


def _metrics_for_day(values: dict[LedgerKey, LedgerValue], target: date) -> dict[str, int]:
    metrics = _empty_metrics()

    for (entry_date, record_type, account_type, subtype), (debit, credit) in values.items():
        if entry_date != target:
            continue
        _apply_ledger_amount(metrics, record_type, account_type, subtype, debit, credit)

    return _finalize_metrics(metrics)


def _empty_metrics() -> dict[str, int]:
    return {
        "gross": 0,
        "revenue": 0,
        "fees": 0,
        "expenses": 0,
        "cash_in": 0,
        "cash_out": 0,
    }


def _apply_ledger_amount(
    metrics: dict[str, int],
    record_type: str | None,
    account_type: str,
    subtype: str | None,
    debit: int,
    credit: int,
) -> None:
    if account_type == AccountType.REVENUE.value:
        revenue_change = credit - debit
        metrics["revenue"] += revenue_change
        if record_type == RecordType.INCOME.value:
            metrics["gross"] += revenue_change
        return

    if account_type == AccountType.EXPENSE.value:
        expense_change = debit - credit
        target = (
            "fees"
            if subtype == "processing_fee"
            and record_type in {RecordType.INCOME.value, RecordType.REFUND.value}
            else "expenses"
        )
        metrics[target] += expense_change
        return

    if account_type != AccountType.ASSET.value:
        return
    if subtype == "pending_difference":
        return
    if record_type in _CASH_IN_RECORD_TYPES:
        metrics["cash_in"] += debit - credit
    elif record_type in _CASH_OUT_RECORD_TYPES:
        metrics["cash_out"] += credit - debit


def _finalize_metrics(metrics: dict[str, int]) -> dict[str, int]:
    net = metrics["revenue"] - metrics["fees"]
    return {
        "gross": metrics["gross"],
        "fees": metrics["fees"],
        "net": net,
        "expenses": metrics["expenses"],
        "operating_net": net - metrics["expenses"],
        "cash_in": metrics["cash_in"],
        "cash_out": metrics["cash_out"],
        "net_cash": metrics["cash_in"] - metrics["cash_out"],
    }


def grouped_ledger_report(
    session: Session,
    workspace: Workspace,
    start_date: date,
    end_date: date,
    group_by: Literal["category", "provider", "channel"],
) -> list[dict[str, str]]:
    dimension: Any
    if group_by == "category":
        dimension = Category.name
    elif group_by == "provider":
        dimension = Counterparty.name
    else:
        dimension = BusinessRecord.source_channel

    rows = session.execute(
        select(
            func.coalesce(dimension, "未分类"),
            BusinessRecord.record_type,
            Account.account_type,
            Account.subtype,
            func.coalesce(func.sum(JournalLine.debit_cny_e8), 0),
            func.coalesce(func.sum(JournalLine.credit_cny_e8), 0),
        )
        .select_from(JournalEntry)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .join(Account, Account.id == JournalLine.account_id)
        .outerjoin(BusinessRecord, BusinessRecord.id == JournalEntry.record_id)
        .outerjoin(Category, Category.id == BusinessRecord.category_id)
        .outerjoin(Counterparty, Counterparty.id == BusinessRecord.counterparty_id)
        .where(
            JournalEntry.workspace_id == workspace.id,
            JournalEntry.status == JournalStatus.POSTED,
            JournalEntry.entry_date.between(start_date, end_date),
        )
        .group_by(
            dimension,
            BusinessRecord.record_type,
            Account.account_type,
            Account.subtype,
        )
    ).all()
    grouped: dict[str, dict[str, int]] = defaultdict(_empty_metrics)
    for label, record_type, account_type, subtype, debit, credit in rows:
        _apply_ledger_amount(
            grouped[str(label)],
            str(record_type) if record_type is not None else None,
            str(account_type),
            subtype,
            int(debit),
            int(credit),
        )
    output: list[dict[str, str]] = []
    for label in sorted(grouped):
        metrics = _finalize_metrics(grouped[label])
        output.append(
            {
                "group": label,
                "gross_revenue": from_e8(metrics["gross"]),
                "channel_fees": from_e8(metrics["fees"]),
                "net_revenue": from_e8(metrics["net"]),
                "operating_expenses": from_e8(metrics["expenses"]),
                "operating_net": from_e8(metrics["operating_net"]),
                "cash_in": from_e8(metrics["cash_in"]),
                "cash_out": from_e8(metrics["cash_out"]),
                "net_cash": from_e8(metrics["net_cash"]),
            }
        )
    return output


def daily_report(
    session: Session, workspace: Workspace, start_date: date, end_date: date
) -> list[DailyReportRow]:
    values, _ = _aggregate(session, workspace.id, start_date, end_date)
    dates = sorted({key[0] for key in values})
    output: list[DailyReportRow] = []
    for target in dates:
        metrics = _metrics_for_day(values, target)
        output.append(
            DailyReportRow(
                date=target,
                gross_revenue=from_e8(metrics["gross"]),
                channel_fees=from_e8(metrics["fees"]),
                net_revenue=from_e8(metrics["net"]),
                operating_expenses=from_e8(metrics["expenses"]),
                operating_net=from_e8(metrics["operating_net"]),
                cash_in=from_e8(metrics["cash_in"]),
                cash_out=from_e8(metrics["cash_out"]),
                net_cash=from_e8(metrics["net_cash"]),
            )
        )
    return output


def _expense_breakdown(
    session: Session, workspace_id: str, start_date: date, end_date: date
) -> list[ExpenseUserSummary]:
    rows = session.execute(
        select(
            User.id,
            func.coalesce(User.username, "历史/系统"),
            BusinessRecord.record_type,
            Account.account_type,
            Account.subtype,
            func.coalesce(func.sum(JournalLine.debit_cny_e8), 0),
            func.coalesce(func.sum(JournalLine.credit_cny_e8), 0),
        )
        .select_from(JournalEntry)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .join(Account, Account.id == JournalLine.account_id)
        .outerjoin(BusinessRecord, BusinessRecord.id == JournalEntry.record_id)
        .outerjoin(User, User.id == BusinessRecord.created_by_user_id)
        .where(
            JournalEntry.workspace_id == workspace_id,
            JournalEntry.status == JournalStatus.POSTED,
            JournalEntry.entry_date.between(start_date, end_date),
            Account.account_type == AccountType.EXPENSE,
        )
        .group_by(
            User.id,
            User.username,
            BusinessRecord.record_type,
            Account.account_type,
            Account.subtype,
        )
    ).all()
    grouped: dict[tuple[str | None, str], dict[str, int]] = defaultdict(_empty_metrics)
    for user_id, username, record_type, account_type, subtype, debit, credit in rows:
        _apply_ledger_amount(
            grouped[(user_id, str(username))],
            str(record_type) if record_type is not None else None,
            str(account_type),
            subtype,
            int(debit),
            int(credit),
        )
    return [
        ExpenseUserSummary(
            user_id=user_id,
            username=username,
            amount=from_e8(metrics["expenses"]),
        )
        for (user_id, username), metrics in sorted(
            grouped.items(), key=lambda item: (-item[1]["expenses"], item[0][1])
        )
        if metrics["expenses"] != 0
    ]


def overview(
    session: Session, workspace: Workspace, start_date: date, end_date: date
) -> OverviewRead:
    values, count = _aggregate(session, workspace.id, start_date, end_date)
    total: dict[str, int] = defaultdict(int)
    for target in sorted({key[0] for key in values}):
        day = _metrics_for_day(values, target)
        for key, amount in day.items():
            total[key] += amount
    return OverviewRead(
        start_date=start_date,
        end_date=end_date,
        gross_revenue=from_e8(total["gross"]),
        channel_fees=from_e8(total["fees"]),
        net_revenue=from_e8(total["net"]),
        operating_expenses=from_e8(total["expenses"]),
        operating_net=from_e8(total["operating_net"]),
        cash_in=from_e8(total["cash_in"]),
        cash_out=from_e8(total["cash_out"]),
        net_cash=from_e8(total["net_cash"]),
        posted_records=count,
        expense_by_user=_expense_breakdown(session, workspace.id, start_date, end_date),
    )


_REPORT_AMOUNT_FIELDS = (
    "gross_revenue",
    "channel_fees",
    "net_revenue",
    "operating_expenses",
    "operating_net",
    "cash_in",
    "cash_out",
    "net_cash",
)


def _convert_report_amount(value: str, cny_per_unit_e12: int) -> str:
    return from_e8(convert_cny_e8(to_e8(value), cny_per_unit_e12))


def _convert_overview(report: OverviewRead, cny_per_unit_e12: int) -> OverviewRead:
    updates: dict[str, object] = {
        field: _convert_report_amount(getattr(report, field), cny_per_unit_e12)
        for field in _REPORT_AMOUNT_FIELDS
    }
    updates["expense_by_user"] = [
        item.model_copy(update={"amount": _convert_report_amount(item.amount, cny_per_unit_e12)})
        for item in report.expense_by_user
    ]
    return report.model_copy(update=updates)


def _convert_daily_rows(rows: list[DailyReportRow], cny_per_unit_e12: int) -> list[DailyReportRow]:
    return [
        row.model_copy(
            update={
                field: _convert_report_amount(getattr(row, field), cny_per_unit_e12)
                for field in _REPORT_AMOUNT_FIELDS
            }
        )
        for row in rows
    ]


def dashboard_report(
    session: Session,
    workspace: Workspace,
    start_date: date,
    end_date: date,
    display_rate: DisplayRate,
) -> DashboardReportRead:
    overview_result = overview(session, workspace, start_date, end_date)
    daily_result = daily_report(session, workspace, start_date, end_date)
    if display_rate.cny_per_unit_e12 != RATE_SCALE:
        overview_result = _convert_overview(overview_result, display_rate.cny_per_unit_e12)
        daily_result = _convert_daily_rows(daily_result, display_rate.cny_per_unit_e12)
    return DashboardReportRead(
        display_currency=display_rate.currency,
        rate=DashboardRateRead(
            cny_per_unit=from_e12(display_rate.cny_per_unit_e12),
            source=display_rate.source,
            effective_at=display_rate.effective_at,
            fetched_at=display_rate.fetched_at,
            is_stale=display_rate.is_stale,
        ),
        overview=overview_result,
        daily=daily_result,
    )
