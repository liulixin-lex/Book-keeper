"""Write operations shared by REST and MCP: one implementation, each with a dry run.

An operation takes JSON arguments (validated by the shared input models), runs inside the caller's
transaction and returns a JSON view. ``run_dry`` executes it and rolls back, so a client sees the
exact outcome (lines, fees, warnings) before writing anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from bookkeeper.domain.errors import DomainError, FieldError
from bookkeeper.services import imports, rules, transactions, undo
from bookkeeper.services.context import RequestContext
from bookkeeper.services.inputs import (
    ApplyRulesIn,
    BatchIn,
    CommitImportIn,
    DeleteArgs,
    EditArgs,
    RepostIn,
    RestoreArgs,
    RevertImportIn,
    TransactionIn,
    UndoIn,
    change_data,
    create_data,
)

Run = Callable[[Session, RequestContext, Any], dict[str, Any]]


@dataclass(frozen=True)
class Operation:
    name: str
    model: type[BaseModel]
    run: Run

    def parse(self, raw: dict[str, Any]) -> BaseModel:
        try:
            return self.model.model_validate(raw)
        except ValidationError as exc:
            errors = [FieldError(".".join(str(p) for p in e["loc"]), "INPUT_INVALID", e["msg"]) for e in exc.errors()]
            raise DomainError(
                "VALIDATION_FAILED",
                f"参数有 {len(errors)} 处问题：{errors[0].path} {errors[0].message}。",
                errors=errors,
            ) from exc


REGISTRY: dict[str, Operation] = {}


def register(name: str, model: type[BaseModel], run: Run) -> None:
    REGISTRY[name] = Operation(name, model, run)


def get(name: str) -> Operation:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise DomainError("NOT_FOUND", f"未知操作 {name}。") from exc


def run_dry(session: Session, ctx: RequestContext, op: Operation, args: BaseModel) -> dict[str, Any]:
    """Execute and roll back. ``session`` must not be inside a transaction."""
    ctx.dry_run = True
    tx = session.begin()
    try:
        return op.run(session, ctx, args)
    finally:
        tx.rollback()
        ctx.change_set_id = None


# ------------------------------------------------------------------ transactions


def _view(session: Session, ctx: RequestContext, ref: str) -> dict[str, Any]:
    txn, code = transactions.load(session, ctx, ref)
    return transactions.full_view(session, txn, code)


def _brief(view: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "number", "type", "status", "effective_date", "description", "amount", "is_estimate")
    computed = view.get("computed") or {}
    return {k: view.get(k) for k in keys} | {
        "entry_number": computed.get("entry_number"),
        "warnings": view.get("warnings", computed.get("warnings", [])),
    }


def create_one(session: Session, ctx: RequestContext, body: TransactionIn) -> dict[str, Any]:
    txn, _entry, plan = transactions.create(session, ctx, create_data(body))
    return _view(session, ctx, txn.id) | {"warnings": plan.warnings}


def _batch(session: Session, ctx: RequestContext, args: BatchIn) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for index, item in enumerate(args.items):
        if args.atomic:
            try:
                view = create_one(session, ctx, item)
            except DomainError as exc:
                exc.detail = f"第 {index + 1} 条：{exc.detail}"
                exc.extra = exc.extra | {"index": index}
                raise
            results.append({"index": index, "ok": True, "transaction": _brief(view)})
            continue
        savepoint = session.begin_nested()
        try:
            view = create_one(session, ctx, item)
            savepoint.commit()
            results.append({"index": index, "ok": True, "transaction": _brief(view)})
        except DomainError as exc:
            savepoint.rollback()
            results.append(
                {
                    "index": index,
                    "ok": False,
                    "error": {"code": exc.code, "detail": exc.detail, "errors": [e.__dict__ for e in exc.errors]},
                }
            )
    ok = sum(1 for r in results if r["ok"])
    return {"created": ok, "failed": len(results) - ok, "results": results}


def _edit(session: Session, ctx: RequestContext, args: EditArgs) -> dict[str, Any]:
    changes = change_data(args, {"ref", "expected_version"})
    txn, plan = transactions.edit(session, ctx, args.ref, changes, args.expected_version)
    warnings = plan.warnings if plan else txn.computed.get("warnings", [])
    return _view(session, ctx, txn.id) | {"warnings": warnings}


def _delete(session: Session, ctx: RequestContext, args: DeleteArgs) -> dict[str, Any]:
    txn, entry = transactions.delete(session, ctx, args.ref, args.reason, args.expected_version)
    return _view(session, ctx, txn.id) | {"reversal_number": entry.number}


def _restore(session: Session, ctx: RequestContext, args: RestoreArgs) -> dict[str, Any]:
    txn, _entry = transactions.restore(session, ctx, args.ref, args.expected_version)
    return _view(session, ctx, txn.id)


register("transactions.create", TransactionIn, create_one)
register("transactions.batch", BatchIn, _batch)
register("transactions.edit", EditArgs, _edit)
register("transactions.delete", DeleteArgs, _delete)
register("transactions.restore", RestoreArgs, _restore)
register("transactions.repost", RepostIn, lambda s, c, a: transactions.repost(s, c, **a.model_dump()))
register("change_sets.undo", UndoIn, lambda s, c, a: undo.undo(s, c, a.change_set_id, a.reason))

# ------------------------------------------------------------------ imports


def _commit_import(session: Session, ctx: RequestContext, args: CommitImportIn) -> dict[str, Any]:
    return imports.commit_batch(
        session, ctx, args.batch_id, accept_row_errors=args.accept_row_errors, exclude=args.exclude
    )


register("imports.commit", CommitImportIn, _commit_import)
register("imports.revert", RevertImportIn, lambda s, c, a: imports.revert_batch(s, c, a.batch_id, a.reason))
register(
    "rules.apply",
    ApplyRulesIn,
    lambda s, c, a: rules.apply_rules(s, c, batch_id=a.batch_id, record_ids=a.record_ids),
)

__all__ = ["REGISTRY", "Operation", "create_one", "get", "run_dry"]
