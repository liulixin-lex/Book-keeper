from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Engine, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.ai.schemas import AiToolCall
from app.ai.tools import ToolDefinition, canonical_tool_signature, tools_for_mode
from app.amounts import from_e8, to_e8
from app.enums import (
    ActorType,
    AIMode,
    ApprovalStatus,
    CategoryKind,
    RecordStatus,
    RecordType,
)
from app.models import (
    AIRun,
    AIToolCall,
    ApprovalRequest,
    AuditEvent,
    BusinessRecord,
    Counterparty,
    User,
    Workspace,
)
from app.schemas import (
    DraftRecordUpdate,
    ExpenseCreate,
    IncomeCreate,
    MoneyInput,
    RefundCreate,
    TopupCreate,
)
from app.services.accounting import (
    create_expense,
    create_income,
    create_refund,
    create_topup,
    resolve_category,
    resolve_counterparty,
)
from app.services.reports import daily_report, grouped_ledger_report, overview


class DomainToolError(ValueError):
    pass


def _record_dict(record: BusinessRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "type": str(record.record_type),
        "status": str(record.status),
        "accounting_date": record.accounting_date.isoformat(),
        "description": record.description,
        "channel": record.source_channel,
        "external_id": record.external_id,
        "version": record.version,
        "amounts": [
            {
                "role": str(item.role),
                "currency": item.currency,
                "amount": from_e8(item.amount_e8),
                "amount_cny": from_e8(item.amount_cny_e8),
            }
            for item in record.amounts
        ],
    }


def _definition(mode: AIMode, name: str) -> ToolDefinition:
    item = next(
        (tool for tool in tools_for_mode(mode) if tool.name == name),
        None,
    )
    if item is None:
        raise DomainToolError(f"Tool is not allowed in {mode}: {name}")
    return item


class SQLDomainToolExecutor:
    """Executes a fixed domain-tool allowlist; it never accepts SQL from a model."""

    def __init__(
        self,
        session: Session,
        user: User,
        run: AIRun,
        *,
        defer_writes: bool = False,
        resume_write_signatures: frozenset[str] | None = None,
    ):
        self.session = session
        self.user = user
        self.run = run
        self.defer_writes = defer_writes
        self.resume_write_signatures = resume_write_signatures
        workspace = session.get(Workspace, user.workspace_id)
        if workspace is None:
            raise DomainToolError("Workspace not found")
        self.workspace = workspace

    def execute_all(self, calls: list[AiToolCall]) -> list[dict[str, Any]]:
        return [self.execute(call) for call in calls]

    def execute(self, call: AiToolCall) -> dict[str, Any]:
        signature = canonical_tool_signature(call.name, call.arguments)
        if self.defer_writes and self.resume_write_signatures is not None:
            try:
                definition = _definition(AIMode(self.run.mode), call.name)
            except DomainToolError:
                definition = None
            if (
                definition is not None
                and not definition.readonly
                and signature not in self.resume_write_signatures
            ):
                return {
                    "ok": False,
                    "error": "resume_write_mismatch",
                    "message": "A resumed run cannot introduce a different write command.",
                }
        existing = self.session.scalar(
            select(AIToolCall).where(
                AIToolCall.run_id == self.run.id,
                AIToolCall.signature == signature,
            )
        )
        if existing is not None and existing.status in {
            "completed",
            "deferred",
            "pending_approval",
        }:
            return existing.result_json
        if existing is not None and existing.status == "running":
            return {"ok": False, "error": "Tool call is already running"}

        provider_call = self.session.scalar(
            select(AIToolCall).where(
                AIToolCall.run_id == self.run.id,
                AIToolCall.provider_call_id == call.id,
            )
        )
        if provider_call is not None and provider_call.signature != signature:
            return {"ok": False, "error": "Provider tool call id was reused with new arguments"}

        row = existing or AIToolCall(
            run_id=self.run.id,
            provider_call_id=call.id,
            name=call.name,
            signature=signature,
            arguments_json=call.arguments,
            result_json={},
            status="running",
        )
        if existing is not None:
            row.status = "running"
            row.result_json = {}
        try:
            if existing is None:
                self.session.add(row)
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            winner = self.session.scalar(
                select(AIToolCall).where(
                    AIToolCall.run_id == self.run.id,
                    AIToolCall.signature == signature,
                )
            )
            if winner is not None and winner.status in {
                "completed",
                "deferred",
                "pending_approval",
            }:
                return winner.result_json
            if winner is not None:
                return {"ok": False, "error": "Tool call is already running"}
            return {"ok": False, "error": "Provider tool call id was reused"}

        try:
            definition = _definition(AIMode(self.run.mode), call.name)
            if self.defer_writes and not definition.readonly:
                result = {
                    "ok": True,
                    "status": "deferred",
                    "message": "Write will be committed after the final AI response.",
                }
                row.status = "deferred"
            elif definition.requires_approval:
                result = self._request_approval(call)
                row.status = "pending_approval"
            else:
                result = self._dispatch(call.name, call.arguments)
                row.status = "completed"
            row.result_json = result
            row.executed_at = datetime.now(UTC)
            self.session.commit()
            return result
        except Exception as exc:
            self.session.rollback()
            row = self.session.scalar(
                select(AIToolCall).where(
                    AIToolCall.run_id == self.run.id,
                    AIToolCall.signature == signature,
                )
            ) or AIToolCall(
                run_id=self.run.id,
                provider_call_id=call.id,
                name=call.name,
                signature=signature,
                arguments_json=call.arguments,
                result_json={},
                status="failed",
            )
            row.status = "failed"
            row.result_json = {"ok": False, "error": str(exc)}
            row.executed_at = datetime.now(UTC)
            self.session.add(row)
            self.session.commit()
            return row.result_json

    def finalize_deferred(self) -> list[dict[str, Any]]:
        """Execute every staged write in one caller-controlled transaction."""
        rows = list(
            self.session.scalars(
                select(AIToolCall)
                .where(
                    AIToolCall.run_id == self.run.id,
                    AIToolCall.status == "deferred",
                )
                .order_by(AIToolCall.executed_at, AIToolCall.id)
            )
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            definition = _definition(AIMode(self.run.mode), row.name)
            if definition.readonly:
                raise DomainToolError("A readonly tool cannot be finalized as a write")
            call = AiToolCall(
                id=row.provider_call_id,
                name=row.name,
                arguments=row.arguments_json,
            )
            if definition.requires_approval:
                result = self._request_approval(call)
                row.status = "pending_approval"
            else:
                result = self._dispatch(call.name, call.arguments)
                if not isinstance(result, dict):
                    raise DomainToolError("Tool returned an invalid result")
                row.status = "completed"
                result = {**result, "status": "committed"}
            row.result_json = result
            row.executed_at = datetime.now(UTC)
            results.append(result)
        self.session.flush()
        return results

    def _dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            raise DomainToolError(f"No executor is configured for {name}")
        if AIMode(self.run.mode) == AIMode.CHAT:
            return self._dispatch_readonly(handler, arguments)
        return handler(arguments)

    def _dispatch_readonly(self, handler: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        bind = self.session.get_bind()
        engine = bind.engine if isinstance(bind, Connection) else bind
        assert isinstance(engine, Engine)
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA query_only=ON")
            original_session = self.session
            try:
                with Session(bind=connection, expire_on_commit=False) as readonly_session:
                    self.session = readonly_session
                    return handler(arguments)
            finally:
                self.session = original_session
                connection.exec_driver_sql("PRAGMA query_only=OFF")

    def _request_approval(self, call: AiToolCall) -> dict[str, Any]:
        approval = ApprovalRequest(
            workspace_id=self.user.workspace_id,
            kind=f"ai_tool:{call.name}",
            status=ApprovalStatus.PENDING,
            payload_json={
                "tool_call_id": call.id,
                "tool_name": call.name,
                "arguments": call.arguments,
                "ai_run_id": self.run.id,
            },
            requested_by_user_id=self.user.id,
            requested_by_ai_run_id=self.run.id,
        )
        self.session.add(approval)
        self.session.flush()
        return {"ok": True, "status": "pending_approval", "approval_id": approval.id}

    def tool_get_overview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = overview(
            self.session,
            self.workspace,
            date.fromisoformat(arguments["date_from"]),
            date.fromisoformat(arguments["date_to"]),
        )
        return {"ok": True, "data": result.model_dump(mode="json")}

    def tool_list_records(self, arguments: dict[str, Any]) -> dict[str, Any]:
        statement = (
            select(BusinessRecord)
            .options(selectinload(BusinessRecord.amounts))
            .where(BusinessRecord.workspace_id == self.user.workspace_id)
            .order_by(BusinessRecord.accounting_date.desc())
            .limit(min(int(arguments.get("limit", 100)), 200))
        )
        if arguments.get("date_from"):
            statement = statement.where(
                BusinessRecord.accounting_date >= date.fromisoformat(arguments["date_from"])
            )
        if arguments.get("date_to"):
            statement = statement.where(
                BusinessRecord.accounting_date <= date.fromisoformat(arguments["date_to"])
            )
        for key, column in (
            ("record_type", BusinessRecord.record_type),
            ("status", BusinessRecord.status),
            ("category_id", BusinessRecord.category_id),
            ("provider_id", BusinessRecord.counterparty_id),
        ):
            if arguments.get(key):
                statement = statement.where(column == arguments[key])
        return {
            "ok": True,
            "records": [_record_dict(item) for item in self.session.scalars(statement)],
        }

    def tool_summarize_ledger(self, arguments: dict[str, Any]) -> dict[str, Any]:
        date_from = date.fromisoformat(arguments["date_from"])
        date_to = date.fromisoformat(arguments["date_to"])
        group_by = arguments["group_by"]
        if group_by in {"day", "month"}:
            rows = daily_report(self.session, self.workspace, date_from, date_to)
            if group_by == "day":
                return {"ok": True, "rows": [row.model_dump(mode="json") for row in rows]}
            monthly: dict[str, dict[str, int]] = {}
            for row in rows:
                item = monthly.setdefault(
                    row.date.strftime("%Y-%m"), {"gross_e8": 0, "expense_e8": 0}
                )
                item["gross_e8"] += to_e8(row.gross_revenue)
                item["expense_e8"] += to_e8(row.operating_expenses)
            return {
                "ok": True,
                "rows": [
                    {
                        "month": month,
                        "gross_revenue": from_e8(amounts["gross_e8"]),
                        "operating_expenses": from_e8(amounts["expense_e8"]),
                    }
                    for month, amounts in sorted(monthly.items())
                ],
            }

        return {
            "ok": True,
            "rows": grouped_ledger_report(
                self.session,
                self.workspace,
                date_from,
                date_to,
                group_by,
            ),
        }

    def tool_get_trends(self, arguments: dict[str, Any]) -> dict[str, Any]:
        rows = daily_report(
            self.session,
            self.workspace,
            date.fromisoformat(arguments["date_from"]),
            date.fromisoformat(arguments["date_to"]),
        )
        field = {
            "income": "gross_revenue",
            "expense": "operating_expenses",
            "operating_net": "operating_net",
            "cash_net": "net_cash",
        }[arguments["metric"]]
        return {
            "ok": True,
            "metric": arguments["metric"],
            "points": [
                {"date": row.date.isoformat(), "value": getattr(row, field)} for row in rows
            ],
        }

    def tool_get_record_source(self, arguments: dict[str, Any]) -> dict[str, Any]:
        record = self._record(arguments["record_id"])
        return {
            "ok": True,
            "record_id": record.id,
            "source_document_id": record.source_document_id,
            "source": record.source_locator_json,
        }

    def tool_create_income(self, arguments: dict[str, Any]) -> dict[str, Any]:
        currency = str(arguments.get("currency", "CNY")).upper()
        record = create_income(
            self.session,
            self.workspace,
            IncomeCreate(
                accounting_date=date.fromisoformat(arguments["accounting_date"]),
                description=arguments["description"],
                channel=arguments.get("channel", "ai"),
                external_id=arguments.get("external_id"),
                gross=MoneyInput(
                    currency=currency,
                    amount=arguments["gross"],
                    amount_cny=arguments.get("gross_cny"),
                ),
                fee=MoneyInput(
                    currency=currency,
                    amount=arguments.get("fee", "0"),
                    amount_cny=arguments.get("fee_cny"),
                ),
                cash_received=bool(arguments.get("cash_received", False)),
                category_id=arguments.get("category_id"),
                counterparty_id=arguments.get("provider_id"),
                post=bool(arguments.get("post", True)),
                metadata={"ai_run_id": self.run.id},
            ),
            actor_id=self.run.id,
            actor_type=ActorType.AI,
            commit=False,
        )
        return {"ok": True, "record": _record_dict(record)}

    def tool_create_expense(self, arguments: dict[str, Any]) -> dict[str, Any]:
        currency = str(arguments.get("currency", "CNY")).upper()
        cash = (
            MoneyInput(
                currency=currency,
                amount=arguments["cash"],
                amount_cny=arguments.get("cash_cny"),
            )
            if arguments.get("cash") is not None
            else None
        )
        record = create_expense(
            self.session,
            self.workspace,
            ExpenseCreate(
                accounting_date=date.fromisoformat(arguments["accounting_date"]),
                description=arguments["description"],
                cost=MoneyInput(
                    currency=currency,
                    amount=arguments["cost"],
                    amount_cny=arguments.get("cost_cny"),
                ),
                cash=cash,
                category_id=arguments.get("category_id"),
                counterparty_id=arguments.get("provider_id"),
                post=bool(arguments.get("post", True)),
                metadata={"ai_run_id": self.run.id},
            ),
            actor_id=self.run.id,
            actor_type=ActorType.AI,
            commit=False,
        )
        return {"ok": True, "record": _record_dict(record)}

    def tool_create_upstream_topup(self, arguments: dict[str, Any]) -> dict[str, Any]:
        upstream = self.session.scalar(
            select(Counterparty).where(
                Counterparty.id == arguments["upstream_id"],
                Counterparty.workspace_id == self.user.workspace_id,
            )
        )
        if upstream is None:
            raise DomainToolError("Upstream provider not found")
        record = create_topup(
            self.session,
            self.workspace,
            TopupCreate(
                accounting_date=date.fromisoformat(arguments["accounting_date"]),
                upstream_name=upstream.name,
                amount_cny=arguments["amount_cny"],
                note=arguments.get("description"),
                post=bool(arguments.get("post", True)),
                metadata={"ai_run_id": self.run.id},
            ),
            actor_id=self.run.id,
            actor_type=ActorType.AI,
            commit=False,
        )
        return {"ok": True, "record": _record_dict(record)}

    def tool_create_refund(self, arguments: dict[str, Any]) -> dict[str, Any]:
        currency = str(arguments.get("currency", "CNY")).upper()

        def money(name: str) -> MoneyInput | None:
            value = arguments.get(name)
            if value is None:
                return None
            return MoneyInput(
                currency=currency,
                amount=value,
                amount_cny=arguments.get(f"{name}_cny"),
            )

        refund_money = money("refund")
        assert refund_money is not None
        record = create_refund(
            self.session,
            self.workspace,
            RefundCreate(
                original_record_id=arguments["original_record_id"],
                accounting_date=date.fromisoformat(arguments["accounting_date"]),
                description=arguments.get("description"),
                refund=refund_money,
                fee_refund=money("fee_refund"),
                cash_out=money("cash_out"),
                external_id=arguments.get("external_id"),
                metadata={"ai_run_id": self.run.id},
                post=bool(arguments.get("post", True)),
            ),
            actor_id=self.run.id,
            actor_type=ActorType.AI,
            commit=False,
        )
        return {"ok": True, "record": _record_dict(record)}

    def tool_update_draft_record(self, arguments: dict[str, Any]) -> dict[str, Any]:
        record = self._draft(arguments["record_id"], int(arguments["expected_version"]))
        raw_changes = dict(arguments["changes"])
        if "provider_id" in raw_changes:
            raw_changes["counterparty_id"] = raw_changes.pop("provider_id")
        changes = DraftRecordUpdate(expected_version=arguments["expected_version"], **raw_changes)
        values: dict[str, Any] = {}
        for field in changes.model_fields_set - {
            "expected_version",
            "category_id",
            "counterparty_id",
        }:
            values[field] = getattr(changes, field)
        if "category_id" in changes.model_fields_set:
            if changes.category_id:
                allowed = (
                    {CategoryKind.INCOME, CategoryKind.BOTH}
                    if record.record_type in {RecordType.INCOME, RecordType.REFUND}
                    else {CategoryKind.EXPENSE, CategoryKind.BOTH}
                )
                values["category_id"] = resolve_category(
                    self.session,
                    self.user.workspace_id,
                    changes.category_id,
                    allowed,
                ).id
            else:
                values["category_id"] = None
        if "counterparty_id" in changes.model_fields_set:
            values["counterparty_id"] = (
                resolve_counterparty(
                    self.session, self.user.workspace_id, changes.counterparty_id
                ).id
                if changes.counterparty_id
                else None
            )
        updated = self._cas_draft_update(
            record,
            changes.expected_version,
            values,
            action="ai.record.update",
        )
        return {"ok": True, "record": _record_dict(updated)}

    def tool_categorize_record(self, arguments: dict[str, Any]) -> dict[str, Any]:
        record = self._draft(arguments["record_id"], int(arguments["expected_version"]))
        allowed = (
            {CategoryKind.INCOME, CategoryKind.BOTH}
            if record.record_type in {RecordType.INCOME, RecordType.REFUND}
            else {CategoryKind.EXPENSE, CategoryKind.BOTH}
        )
        category = resolve_category(
            self.session,
            self.user.workspace_id,
            arguments["category_id"],
            allowed,
        )
        updated = self._cas_draft_update(
            record,
            int(arguments["expected_version"]),
            {"category_id": category.id},
            action="ai.record.categorize",
        )
        return {"ok": True, "record": _record_dict(updated)}

    def _record(self, record_id: str) -> BusinessRecord:
        record = self.session.scalar(
            select(BusinessRecord)
            .options(selectinload(BusinessRecord.amounts))
            .where(
                BusinessRecord.id == record_id,
                BusinessRecord.workspace_id == self.user.workspace_id,
            )
        )
        if record is None:
            raise DomainToolError("Record not found")
        return record

    def _draft(self, record_id: str, expected_version: int) -> BusinessRecord:
        record = self._record(record_id)
        if RecordStatus(record.status) != RecordStatus.DRAFT:
            raise DomainToolError("Only draft records can be edited")
        if record.version != expected_version:
            raise DomainToolError("Record version conflict")
        return record

    def _cas_draft_update(
        self,
        record: BusinessRecord,
        expected_version: int,
        values: dict[str, Any],
        *,
        action: str,
    ) -> BusinessRecord:
        result = self.session.connection().execute(
            update(BusinessRecord)
            .where(
                BusinessRecord.id == record.id,
                BusinessRecord.workspace_id == self.user.workspace_id,
                BusinessRecord.status == RecordStatus.DRAFT,
                BusinessRecord.version == expected_version,
            )
            .values(**values, version=expected_version + 1)
        )
        if result.rowcount != 1:
            raise DomainToolError("Record version conflict or record is no longer a draft")
        self.session.expire(record)
        updated = self.session.scalar(
            select(BusinessRecord)
            .options(selectinload(BusinessRecord.amounts))
            .where(BusinessRecord.id == record.id)
            .execution_options(populate_existing=True)
        )
        assert updated is not None
        self._audit(updated, action)
        self.session.flush()
        return updated

    def _audit(self, record: BusinessRecord, action: str) -> None:
        self.session.add(
            AuditEvent(
                workspace_id=self.user.workspace_id,
                actor_type=ActorType.AI,
                actor_id=self.run.id,
                ai_run_id=self.run.id,
                action=action,
                entity_type="business_record",
                entity_id=record.id,
                after_json={"version": record.version},
            )
        )
