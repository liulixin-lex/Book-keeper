"""A model backend for tests: answers are recorded or computed in Python, nothing goes to a real API."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from bookkeeper.ai import adapters
from bookkeeper.ai.adapters import Request, Response, Target, ToolCall, Usage


class FileBackend:
    """For 识别: ``answer(file_name, mime, prompt_text)`` returns the model's JSON (it may carry ``_usage`` and
    ``_model``) or raises a DomainError like a failing provider."""

    def __init__(self, answer: Callable[[str, str, str], dict[str, Any]]) -> None:
        self.answer = answer
        self.requests: list[tuple[Target, Request, bool]] = []

    def complete(self, target: Target, request: Request, *, json_mode: bool) -> Response:
        self.requests.append((target, request, json_mode))
        part = next(p for m in request.messages for p in m.parts if p.kind in ("image", "pdf"))
        text = " ".join(p.text for m in request.messages for p in m.parts if p.kind == "text")
        result = dict(self.answer(part.name, part.mime, text))
        usage = result.pop("_usage", {"input_tokens": 0, "output_tokens": 0})
        model = result.pop("_model", target.model)
        return Response(json.dumps(result, ensure_ascii=False), [], "end", Usage(**usage), model)

    def list_models(self, target: Target) -> list[str]:
        return [target.model]


class ScriptBackend:
    """For agent runs: each call returns the next scripted turn: text, or tool calls as (name, arguments)."""

    def __init__(self, turns: list[str | list[tuple[str, dict[str, Any]]]]) -> None:
        self.turns = list(turns)
        self.requests: list[Request] = []

    def complete(self, target: Target, request: Request, *, json_mode: bool) -> Response:
        self.requests.append(request)
        turn = self.turns.pop(0) if self.turns else "完成。"
        if isinstance(turn, str):
            return Response(turn, [], "end", Usage(100, 20), target.model)
        calls = [ToolCall(f"call_{len(self.requests)}_{i}", name, args) for i, (name, args) in enumerate(turn)]
        return Response("", calls, "tool_use", Usage(100, 20), target.model)

    def list_models(self, target: Target) -> list[str]:
        return [target.model]


def install(monkeypatch: Any, backend: Any) -> Any:
    monkeypatch.setattr(adapters, "backend_for", lambda target: backend)
    return backend
