"""The committed interface snapshots (contracts/*.json, docs/16) match the code."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "contracts.py"


def test_interface_snapshots_are_current() -> None:
    spec = importlib.util.spec_from_file_location("contracts", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stale = [p.name for p, text in module.build().items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    assert not stale, f"interface changed: run `uv run python scripts/contracts.py` and commit {stale}"
