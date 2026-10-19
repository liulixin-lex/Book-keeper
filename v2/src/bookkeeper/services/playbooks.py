"""Scenario playbooks (docs/19 §5): one source for MCP prompts and the in-app AI assistant.

Each says when it applies, the steps, the tools in order, the scopes it needs and when it is done. The built-in
ones live in ai/playbooks.json; a book can change one or add its own (ai_playbooks), and reset it to the built-in.
The scopes are worked out from the tools, so a playbook is offered only to a caller who can run all of it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.db.models import AiPlaybook
from bookkeeper.domain.errors import DomainError, version_conflict
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit
from bookkeeper.services.context import RequestContext

BUILT_IN: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent.parent / "ai" / "playbooks.json").read_text(encoding="utf-8")
)
CODE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
RUNTIME_TOOLS = {"ask_user"}  # the assistant's own, not in the shared registry


def needed_scopes(tools: list[str]) -> list[str]:
    """What running every tool takes (for a tool usable with any of several scopes, the first)."""
    from bookkeeper.mcp_api.tools import TOOLS

    found: set[Scope] = set()
    for name in tools:
        tool = TOOLS.get(name)
        if tool is None:
            continue
        found |= set(tool.scopes)
        if tool.any_of:
            found.add(tool.any_of[0])
    return sorted(s.value for s in found)


def clean(data: dict[str, Any], code: str) -> dict[str, Any]:
    """Check a playbook and fill in its scopes. Tools must exist; text fields are required."""
    from bookkeeper.mcp_api.tools import TOOLS

    title = str(data.get("title") or "").strip()
    when = str(data.get("when") or "").strip()
    done = str(data.get("done") or "").strip()
    steps = [str(s).strip() for s in data.get("steps") or [] if str(s).strip()]
    tools = [str(t).strip() for t in data.get("tools") or [] if str(t).strip()]
    if not CODE.match(code):
        raise DomainError("VALIDATION_FAILED", "场景代码用小写英文、数字和下划线，2–48 个字符。")
    if not title or not when or not done or not steps or not tools:
        raise DomainError("VALIDATION_FAILED", "场景需要名称、适用条件、步骤、工具和完成标准。")
    unknown = [t for t in tools if t not in TOOLS and t not in RUNTIME_TOOLS]
    if unknown:
        raise DomainError("VALIDATION_FAILED", f"没有这些工具：{'、'.join(unknown)}。")
    arguments = []
    for arg in data.get("arguments") or []:
        name = str(arg.get("name") or "").strip()
        if not re.match(r"^[a-z][a-z0-9_]{0,31}$", name):
            raise DomainError("VALIDATION_FAILED", f"参数名“{name}”用小写英文。")
        arguments.append(
            {
                "name": name,
                "description": str(arg.get("description") or "")[:120],
                "required": bool(arg.get("required")),
            }
        )
    return {
        "code": code,
        "title": title[:40],
        "when": when[:300],
        "arguments": arguments,
        "steps": [s[:400] for s in steps[:12]],
        "tools": tools,
        "scopes": needed_scopes(tools),
        "done": done[:300],
    }


def _overrides(session: Session, book_id: str) -> dict[str, AiPlaybook]:
    rows = session.execute(select(AiPlaybook).where(AiPlaybook.book_id == book_id)).scalars()
    return {r.code: r for r in rows}


def all_for(session: Session, book_id: str) -> list[dict[str, Any]]:
    """The book's playbooks: built-ins (changed ones as changed) and its own, each marked."""
    own = _overrides(session, book_id)
    out = []
    for base in BUILT_IN:
        row = own.pop(base["code"], None)
        data = clean(row.data if row else base, base["code"])
        out.append(data | {"built_in": True, "changed": row is not None, "version": row.version if row else 0})
    for code, row in sorted(own.items()):
        out.append(clean(row.data, code) | {"built_in": False, "changed": True, "version": row.version})
    return out


def get(session: Session, book_id: str, code: str) -> dict[str, Any]:
    for item in all_for(session, book_id):
        if item["code"] == code:
            return item
    raise DomainError("NOT_FOUND", f"没有场景 {code}。")


def usable(item: dict[str, Any], scopes: frozenset[Scope]) -> bool:
    return {Scope(s) for s in item["scopes"]} <= scopes


def save(
    session: Session, ctx: RequestContext, code: str, data: dict[str, Any], expected_version: int
) -> dict[str, Any]:
    """Change a built-in playbook or add one; ``expected_version`` 0 = the first change."""
    ctx.require(Scope.RULES_WRITE)
    book_id = ctx.require_book()
    cleaned = clean(data, code)
    row = _overrides(session, book_id).get(code)
    current = row.version if row else 0
    if expected_version != current:
        raise version_conflict(f"场景 {code}", expected_version, current)
    before = dict(row.data) if row else None
    if row is None:
        row = AiPlaybook(id=new_id("pbk"), book_id=book_id, code=code, data=cleaned, updated_by=ctx.actor.user_id)
        session.add(row)
    else:
        row.data, row.version, row.updated_by = cleaned, row.version + 1, ctx.actor.user_id
    session.flush()
    audit.ensure_change_set(session, ctx, "playbook.save")
    audit.record(session, ctx, "ai_playbook.save", "ai_playbook", row.id, before=before, after=cleaned)
    return get(session, book_id, code)


def reset(session: Session, ctx: RequestContext, code: str) -> dict[str, Any] | None:
    """Back to the built-in version (a book's own playbook is removed)."""
    ctx.require(Scope.RULES_WRITE)
    book_id = ctx.require_book()
    row = _overrides(session, book_id).get(code)
    if row is None:
        raise DomainError("NOT_FOUND", f"场景 {code} 没有改过。")
    audit.ensure_change_set(session, ctx, "playbook.reset")
    audit.record(session, ctx, "ai_playbook.reset", "ai_playbook", row.id, before=dict(row.data))
    session.delete(row)
    session.flush()
    return next((p for p in all_for(session, book_id) if p["code"] == code), None)


def render(item: dict[str, Any], arguments: dict[str, str] | None = None) -> str:
    """The playbook as instructions, with the given arguments filled in (blank ones say 未指定)."""
    values = {a["name"]: (arguments or {}).get(a["name"]) or "未指定" for a in item["arguments"]}

    def fill(text: str) -> str:
        return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), text)

    lines = [f"# 场景：{item['title']}", f"适用：{item['when']}"]
    given = [f"{a['name']} = {values[a['name']]}" for a in item["arguments"] if (arguments or {}).get(a["name"])]
    if given:
        lines.append("参数：" + "；".join(given))
    lines += ["步骤：", *(f"{i}. {fill(s)}" for i, s in enumerate(item["steps"], 1))]
    lines += [f"工具顺序：{' → '.join(item['tools'])}", f"需要的权限：{'、'.join(item['scopes'])}"]
    lines.append(f"完成标准：{item['done']}")
    return "\n".join(lines)
