"""Interface contracts: OpenAPI and MCP tool snapshots plus the generated interface index (docs/16).

    uv run python scripts/contracts.py           # regenerate after an intended interface change
    uv run python scripts/contracts.py --check   # exit 1 when the code and the snapshots differ (also a test)

A contract change shows up in review as a diff of contracts/*.json; docs/16 is regenerated from the same data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bookkeeper.config import Settings  # noqa: E402
from bookkeeper.main import create_app  # noqa: E402
from bookkeeper.mcp_api.server import tool_schema  # noqa: E402
from bookkeeper.mcp_api.tools import TOOLS  # noqa: E402

OPENAPI = ROOT / "contracts" / "openapi.json"
MCP_TOOLS = ROOT / "contracts" / "mcp-tools.json"
INDEX = ROOT.parent / "docs" / "16-interface-index.md"
PREFIX = "/api/v1/books/{book_id}"
KIND = {"read": "只读", "write": "写", "high": "高影响"}


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def openapi() -> dict[str, Any]:
    app = create_app(
        Settings(database_url="postgresql+psycopg://contracts@localhost/none", mcp_write_enabled=True),
        configure_logs=False,
    )
    schema: dict[str, Any] = app.openapi()
    app.state.engine.dispose()
    return schema


def mcp_tools() -> list[dict[str, Any]]:
    out = []
    for tool in TOOLS.values():
        schema = tool_schema(tool)
        out.append(
            {
                "name": tool.name,
                "title": tool.title,
                "kind": tool.kind,
                "scopes": sorted(str(s) for s in tool.scopes),
                "any_of": sorted(str(s) for s in tool.any_of),
                "operation": tool.operation,
                "rest": tool.rest,
                "input_schema": schema.input_schema,
            }
        )
    return sorted(out, key=lambda t: t["name"])


def _first_line(text: str | None) -> str:
    return (text or "").strip().split("\n")[0].strip()


def index(schema: dict[str, Any], tools: list[dict[str, Any]]) -> str:
    lines = [
        "# 16 接口索引（由代码生成）",
        "",
        "> 由 `v2/scripts/contracts.py` 根据 OpenAPI 与 MCP 工具注册表生成，请勿手工修改。",
        f"> 版本 {schema['info']['version']}；REST 账套接口前缀 `{PREFIX}`（表中以 `…` 表示）。"
        "设计说明见 08（REST）与 09（MCP）号文档。",
        "",
        "## REST",
        "",
    ]
    by_tag: dict[str, list[tuple[str, str, str]]] = {}
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            tag = (op.get("tags") or ["other"])[0]
            short = "…" + path[len(PREFIX) :] if path.startswith(PREFIX) else path
            text = _first_line(op.get("description")) or op.get("summary", "")
            by_tag.setdefault(tag, []).append((method.upper(), short, text))
    total = 0
    for tag in sorted(by_tag):
        lines += [f"### {tag}", "", "| 方法 | 路径 | 说明 |", "|---|---|---|"]
        for method, path, text in sorted(by_tag[tag], key=lambda r: (r[1], r[0])):
            lines.append(f"| {method} | `{path}` | {text.replace('|', '/')} |")
            total += 1
        lines.append("")
    lines += [f"共 {total} 个 REST 操作。", "", "## MCP 工具", ""]
    lines += ["| 工具 | 名称 | 类型 | 所需 scope | 共享操作 / REST |", "|---|---|---|---|---|"]
    for t in tools:
        scopes = "、".join(t["scopes"]) + (f"（任一：{'、'.join(t['any_of'])}）" if t["any_of"] else "")
        link = t["operation"] or t["rest"] or ""
        lines.append(f"| `{t['name']}` | {t['title']} | {KIND[t['kind']]} | {scopes or '—'} | {link} |")
    lines += ["", f"共 {len(tools)} 个工具；写工具另有 `dry_run` 与 `idempotency_key` 参数。", ""]
    return "\n".join(lines)


def build() -> dict[Path, str]:
    schema = openapi()
    tools = mcp_tools()
    outputs = {OPENAPI: _dump(schema), MCP_TOOLS: _dump(tools)}
    if INDEX.parent.is_dir():  # the design docs sit next to v2/ in the working repository
        outputs[INDEX] = index(schema, tools)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args()
    outputs = build()
    if args.check:
        stale = [
            str(p.relative_to(ROOT.parent))
            for p, text in outputs.items()
            if not p.exists() or p.read_text(encoding="utf-8") != text
        ]
        if stale:
            print("interface snapshots are stale: " + ", ".join(stale) + " — run scripts/contracts.py", file=sys.stderr)
            return 1
        return 0
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
