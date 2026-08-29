from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.ai.adapters.base import (
    AIProviderRequestError,
    BaseAdapter,
    parse_tool_arguments,
    serialize_tool_result,
)
from app.ai.schemas import AiEvent, AiEventType, AiRequest, AiResponse, AiToolCall
from app.ai.tools import ToolDefinition


class ResponsesAdapter(BaseAdapter):
    endpoint = "/responses"

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        headers.update(self.custom_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def build_payload(
        self,
        request: AiRequest,
        *,
        system_prompt: str,
        tools: tuple[ToolDefinition, ...],
        enable_web_search: bool,
    ) -> dict[str, Any]:
        input_items = [message.model_dump(exclude_none=True) for message in request.messages]
        for exchange in request.tool_exchanges:
            if exchange.assistant_text:
                input_items.append({"role": "assistant", "content": exchange.assistant_text})
            input_items.extend(
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": json.dumps(
                        call.arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ),
                }
                for call in exchange.tool_calls
            )
            input_items.extend(
                {
                    "type": "function_call_output",
                    "call_id": result.tool_call.id,
                    "output": serialize_tool_result(result),
                }
                for result in exchange.tool_results
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_items,
            "instructions": system_prompt,
            "max_output_tokens": request.max_output_tokens,
            "reasoning": {"effort": self.reasoning_effort},
            "metadata": request.metadata,
            "tools": [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                    "strict": tool.strict,
                }
                for tool in tools
            ],
        }
        if enable_web_search:
            payload["tools"].append({"type": "web_search"})
        if request.required_tool:
            payload["tool_choice"] = {"type": "function", "name": request.required_tool}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.response_format is not None:
            payload["text"] = {"format": request.response_format}
        return payload

    def parse_response(self, payload: dict[str, Any]) -> AiResponse:
        error = payload.get("error")
        if error:
            raise AIProviderRequestError("AI provider reported a response error")

        text_parts: list[str] = []
        tool_calls: list[AiToolCall] = []
        for item in payload.get("output", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                tool_calls.append(
                    AiToolCall(
                        id=str(item.get("call_id") or item.get("id") or ""),
                        name=str(item.get("name") or ""),
                        arguments=parse_tool_arguments(item.get("arguments")),
                    )
                )
                continue
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text":
                    text_parts.append(str(content.get("text") or ""))

        if not text_parts and isinstance(payload.get("output_text"), str):
            text_parts.append(payload["output_text"])
        status = payload.get("status")
        return AiResponse(
            response_id=payload.get("id"),
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
            finish_reason=str(status) if status else None,
            raw_status=str(status) if status else None,
        )

    async def normalize_stream(
        self, events: AsyncIterator[tuple[str | None, str]]
    ) -> AsyncIterator[AiEvent]:
        calls: dict[str, dict[str, str]] = {}
        emitted: set[str] = set()
        response_id: str | None = None
        async for event_name, data in events:
            if data == "[DONE]":
                yield AiEvent(type=AiEventType.DONE, response_id=response_id)
                return
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise AIProviderRequestError("AI provider returned invalid SSE JSON") from exc
            if not isinstance(payload, dict):
                continue
            raw_type = str(payload.get("type") or event_name or "")
            response = payload.get("response")
            if isinstance(response, dict):
                response_id = str(response.get("id") or response_id or "") or None

            if raw_type == "response.created":
                yield AiEvent(
                    type=AiEventType.START,
                    response_id=response_id,
                    raw_type=raw_type,
                )
            elif raw_type == "response.output_text.delta":
                yield AiEvent(
                    type=AiEventType.TEXT_DELTA,
                    response_id=response_id,
                    text=str(payload.get("delta") or ""),
                    raw_type=raw_type,
                )
            elif raw_type == "response.output_item.added":
                item = payload.get("item")
                if isinstance(item, dict) and item.get("type") == "function_call":
                    item_id = str(item.get("id") or item.get("call_id") or "")
                    calls[item_id] = {
                        "id": str(item.get("call_id") or item_id),
                        "name": str(item.get("name") or ""),
                        "arguments": str(item.get("arguments") or ""),
                    }
            elif raw_type == "response.function_call_arguments.delta":
                item_id = str(payload.get("item_id") or "")
                delta = str(payload.get("delta") or "")
                call = calls.setdefault(
                    item_id,
                    {"id": item_id, "name": str(payload.get("name") or ""), "arguments": ""},
                )
                call["arguments"] += delta
                yield AiEvent(
                    type=AiEventType.TOOL_CALL_DELTA,
                    response_id=response_id,
                    arguments_delta=delta,
                    tool_call=AiToolCall(id=call["id"], name=call["name"], arguments={}),
                    raw_type=raw_type,
                )
            elif raw_type == "response.output_item.done":
                item = payload.get("item")
                if isinstance(item, dict) and item.get("type") == "function_call":
                    item_id = str(item.get("id") or item.get("call_id") or "")
                    stored = calls.get(item_id, {})
                    tool_call = AiToolCall(
                        id=str(item.get("call_id") or stored.get("id") or item_id),
                        name=str(item.get("name") or stored.get("name") or ""),
                        arguments=parse_tool_arguments(
                            item.get("arguments", stored.get("arguments", ""))
                        ),
                    )
                    emitted.add(item_id)
                    yield AiEvent(
                        type=AiEventType.TOOL_CALL,
                        response_id=response_id,
                        tool_call=tool_call,
                        raw_type=raw_type,
                    )
            elif raw_type == "response.completed":
                for item_id, stored in calls.items():
                    if item_id not in emitted:
                        yield AiEvent(
                            type=AiEventType.TOOL_CALL,
                            response_id=response_id,
                            tool_call=AiToolCall(
                                id=stored["id"],
                                name=stored["name"],
                                arguments=parse_tool_arguments(stored["arguments"]),
                            ),
                            raw_type=raw_type,
                        )
                completed = payload.get("response")
                usage = completed.get("usage") if isinstance(completed, dict) else None
                status = completed.get("status") if isinstance(completed, dict) else None
                yield AiEvent(
                    type=AiEventType.DONE,
                    response_id=response_id,
                    usage=usage if isinstance(usage, dict) else None,
                    finish_reason=str(status) if status else "completed",
                    raw_type=raw_type,
                )
                return
            elif raw_type in {"response.failed", "error"}:
                yield AiEvent(
                    type=AiEventType.ERROR,
                    response_id=response_id,
                    error="AI provider reported a streaming error",
                    raw_type=raw_type,
                )
                return
