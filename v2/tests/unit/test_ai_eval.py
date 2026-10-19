"""`bookkeeper ai-eval` on the synthetic sample set with recorded answers: no provider is called."""

from __future__ import annotations

import json
from pathlib import Path

from bookkeeper import cli

SAMPLES = Path(__file__).resolve().parent.parent / "fixtures" / "ai_eval"


def test_ai_eval_scores_each_model_field_by_field(tmp_path, capsys) -> None:
    out = tmp_path / "scores.json"
    code = cli.main(
        [
            "ai-eval",
            "--gold",
            str(SAMPLES),
            "--replay",
            str(SAMPLES / "recorded"),
            "--today",
            "2026-10-19",
            "--json",
            str(out),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert printed.splitlines()[0].startswith("目标 | 文件 | 页面类型 | 召回 | 准确 | occurred_at")
    scores = {s["target"]: s for s in json.loads(out.read_text())}
    perfect, sloppy = scores["model-a · model-a"], scores["model-b · model-b"]
    assert perfect["page_type"] == perfect["recall"] == perfect["precision"] == 1.0
    assert set(perfect["fields"].values()) == {1.0}  # years filled in from --today, as the import does
    assert perfect["input_tokens"] + perfect["output_tokens"] == 3450

    assert sloppy["page_type"] == 0.5 and sloppy["recall"] == 0.75 and sloppy["precision"] == 1.0
    assert sloppy["fields"] == {
        "occurred_at": 0.667,
        "direction": 1.0,
        "amount": 0.667,
        "currency": 0.667,
        "order_no": 1.0,
        "counterparty": 1.0,
        "face": 1.0,
    }
    assert sloppy["unreadable"] == 1 and sloppy["failed"] == []


def test_the_real_gold_set_stays_out_of_the_repository() -> None:
    ignored = (Path(__file__).resolve().parents[2] / ".gitignore").read_text()
    assert "/.local/" in ignored  # the default --gold folder
    readme = (SAMPLES / "README.md").read_text()
    assert "合成样本" in readme
