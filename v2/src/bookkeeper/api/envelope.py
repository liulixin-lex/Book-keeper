"""Success envelope: {"data": …, "meta": {…}, "warnings": […]}."""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder

from bookkeeper.services.context import RequestContext


def envelope(
    data: Any,
    ctx: RequestContext | None = None,
    *,
    meta: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if ctx is not None:
        merged["request_id"] = ctx.request_id
        if ctx.change_set_id:
            merged["change_set_id"] = ctx.change_set_id
        if ctx.idempotency_key:
            merged["idempotency_key"] = ctx.idempotency_key
        if ctx.dry_run:
            merged["dry_run"] = True
    if meta:
        merged.update(meta)
    result: dict[str, Any] = jsonable_encoder({"data": data, "meta": merged, "warnings": warnings or []})
    return result
