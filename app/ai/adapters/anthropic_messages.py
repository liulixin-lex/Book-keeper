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

_ANTHROPIC_EFFORT = {
    "none": "low",
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "max",
    "max": "max",
    "ultra": "max",
}


class AnthropicMessagesAdapter(BaseAdapter):
    endpoint = "/messages"

    def headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        headers.update(self.custom_headers)
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def build_payload(
        self,
        request: AiRequest,
        *,
        system_prompt: str,
        tools: tuple[ToolDefinition, ...],
        enable_web_search: bool,
    ) -> dict[str, Any]:
        del enable_web_search
        extra_system: list[str] = []
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            if message.role in {"system", "developer"}:
                if isinstance(message.content, str):
                    extra_system.append(message.content)
                continue
            role = "assistant" if message.role == "assistant" else "user"
            messages.append({"role": role, "content": message.content})
        for exchange in request.tool_exchanges:
            assistant_content: list[dict[str, Any]] = []
            if exchange.assistant_text:
                assistant_content.append({"type": "text", "text": exchange.assistant_text})
            assistant_content.extend(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.arguments,
                }
                for call in exchange.tool_calls
            )
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.tool_call.id,
                            "content": serialize_tool_result(result),
                        }
                        for result in exchange.tool_results
                    ],
                }
            )
        complete_system = system_prompt
        if extra_system:
            complete_system = f"{complete_system}\n\n" + "\n\n".join(extra_system)
        payload: dict[str, Any] = {
            "model": self.model,
            "system": complete_system,
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.required_tool:
            payload["tool_choice"] = {"type": "tool", "name": request.required_tool}
        if self.capabilities.get("reasoning_effort", False):
            payload["thinking"] = {"type": "adaptive"}
            payload["output_config"] = {
                "effort": _ANTHROPIC_EFFORT.get(self.reasoning_effort, "medium")
            }
        return payload

    def parse_response(self, payload: dict[str, Any]) -> AiResponse:
        if payload.get("type") == "error" or payload.get("error"):
            raise AIProviderRequestError("AI provider reported a response error")
        content = payload.get("content")
        if not isinstance(content, list):
            raise AIProviderRequestError("AI provider returned invalid message content")
        text_parts: list[str] = []
        tool_calls: list[AiToolCall] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    AiToolCall(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments=parse_tool_arguments(block.get("input")),
                    )
                )
        return AiResponse(
            response_id=payload.get("id"),
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
            finish_reason=payload.get("stop_reason"),
            raw_status=payload.get("stop_reason"),
        )

    async def normalize_stream(
        self, events: AsyncIterator[tuple[str | None, str]]
    ) -> AsyncIterator[AiEvent]:
        response_id: str | None = None
        calls: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        finish_reason: str | None = None
        async for event_name, data in events:
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise AIProviderRequestError("AI provider returned invalid SSE JSON") from exc
            if not isinstance(payload, dict):
                continue
            raw_type = str(payload.get("type") or event_name or "")
            if raw_type == "message_start":
                message = payload.get("message")
                if isinstance(message, dict):
                    response_id = str(message.get("id") or "") or None
                    if isinstance(message.get("usage"), dict):
                        usage.update(message["usage"])
                yield AiEvent(
                    type=AiEventType.START,
                    response_id=response_id,
                    raw_type=raw_type,
                )
            elif raw_type == "content_block_start":
                block = payload.get("content_block")
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    index = int(payload.get("index", 0))
                    calls[index] = {
                        "id": str(block.get("id") or ""),
                        "name": str(block.get("name") or ""),
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False)
                        if block.get("input")
                        else "",
                    }
            elif raw_type == "content_block_delta":
                delta = payload.get("delta")
                if not isinstance(delta, dict):
                    continue
                if delta.get("type") == "text_delta":
                    yield AiEvent(
                        type=AiEventType.TEXT_DELTA,
                        response_id=response_id,
                        text=str(delta.get("text") or ""),
                        raw_type=raw_type,
                    )
                elif delta.get("type") == "input_json_delta":
                    index = int(payload.get("index", 0))
                    stored = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    arguments_delta = str(delta.get("partial_json") or "")
                    stored["arguments"] += arguments_delta
                    yield AiEvent(
                        type=AiEventType.TOOL_CALL_DELTA,
                        response_id=response_id,
                        arguments_delta=arguments_delta,
                        tool_call=AiToolCall(id=stored["id"], name=stored["name"], arguments={}),
                        raw_type=raw_type,
                    )
            elif raw_type == "content_block_stop":
                index = int(payload.get("index", 0))
                if index in calls:
                    stored = calls.pop(index)
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
            elif raw_type == "message_delta":
                delta = payload.get("delta")
                if isinstance(delta, dict) and delta.get("stop_reason"):
                    finish_reason = str(delta["stop_reason"])
                if isinstance(payload.get("usage"), dict):
                    usage.update(payload["usage"])
            elif raw_type == "message_stop":
                for stored in calls.values():
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
                yield AiEvent(
                    type=AiEventType.DONE,
                    response_id=response_id,
                    usage=usage,
                    finish_reason=finish_reason,
                    raw_type=raw_type,
                )
                return
            elif raw_type == "error":
                yield AiEvent(
                    type=AiEventType.ERROR,
                    response_id=response_id,
                    error="AI provider reported a streaming error",
                    raw_type=raw_type,
                )
                return
