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


class ChatCompletionsAdapter(BaseAdapter):
    endpoint = "/chat/completions"

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
        del enable_web_search
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend(message.model_dump(exclude_none=True) for message in request.messages)
        for exchange in request.tool_exchanges:
            messages.append(
                {
                    "role": "assistant",
                    "content": exchange.assistant_text or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                    default=str,
                                ),
                            },
                        }
                        for call in exchange.tool_calls
                    ],
                }
            )
            messages.extend(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call.id,
                    "content": serialize_tool_result(result),
                }
                for result in exchange.tool_results
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "reasoning_effort": self.reasoning_effort,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                        "strict": tool.strict,
                    },
                }
                for tool in tools
            ],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.required_tool:
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": request.required_tool},
            }
        if request.response_format is not None:
            payload["response_format"] = request.response_format
        return payload

    def parse_response(self, payload: dict[str, Any]) -> AiResponse:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise AIProviderRequestError("AI provider returned no completion choice")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise AIProviderRequestError("AI provider returned an invalid completion message")
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
            )
        else:
            text = ""
        tool_calls: list[AiToolCall] = []
        for item in message.get("tool_calls") or []:
            if not isinstance(item, dict):
                continue
            function = item.get("function")
            if not isinstance(function, dict):
                continue
            tool_calls.append(
                AiToolCall(
                    id=str(item.get("id") or ""),
                    name=str(function.get("name") or ""),
                    arguments=parse_tool_arguments(function.get("arguments")),
                )
            )
        return AiResponse(
            response_id=payload.get("id"),
            text=text,
            tool_calls=tool_calls,
            usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
            finish_reason=choice.get("finish_reason"),
            raw_status=choice.get("finish_reason"),
        )

    async def normalize_stream(
        self, events: AsyncIterator[tuple[str | None, str]]
    ) -> AsyncIterator[AiEvent]:
        response_id: str | None = None
        started = False
        calls: dict[int, dict[str, str]] = {}
        emitted: set[int] = set()

        async def completed_calls() -> AsyncIterator[AiEvent]:
            for index, stored in calls.items():
                if index in emitted:
                    continue
                emitted.add(index)
                yield AiEvent(
                    type=AiEventType.TOOL_CALL,
                    response_id=response_id,
                    tool_call=AiToolCall(
                        id=stored["id"],
                        name=stored["name"],
                        arguments=parse_tool_arguments(stored["arguments"]),
                    ),
                )

        async for _event_name, data in events:
            if data == "[DONE]":
                async for event in completed_calls():
                    yield event
                yield AiEvent(type=AiEventType.DONE, response_id=response_id)
                return
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise AIProviderRequestError("AI provider returned invalid SSE JSON") from exc
            if not isinstance(payload, dict):
                continue
            response_id = str(payload.get("id") or response_id or "") or None
            if not started:
                started = True
                yield AiEvent(type=AiEventType.START, response_id=response_id, raw_type="chunk")
            usage = payload.get("usage")
            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                if isinstance(usage, dict):
                    yield AiEvent(
                        type=AiEventType.DONE,
                        response_id=response_id,
                        usage=usage,
                        raw_type="chunk",
                    )
                    return
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str) and content:
                    yield AiEvent(
                        type=AiEventType.TEXT_DELTA,
                        response_id=response_id,
                        text=content,
                        raw_type="chunk",
                    )
                for part in delta.get("tool_calls") or []:
                    if not isinstance(part, dict):
                        continue
                    index = int(part.get("index", 0))
                    function = part.get("function")
                    stored = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if part.get("id"):
                        stored["id"] = str(part["id"])
                    if isinstance(function, dict):
                        if function.get("name"):
                            stored["name"] += str(function["name"])
                        arguments_delta = str(function.get("arguments") or "")
                        stored["arguments"] += arguments_delta
                        if arguments_delta:
                            yield AiEvent(
                                type=AiEventType.TOOL_CALL_DELTA,
                                response_id=response_id,
                                arguments_delta=arguments_delta,
                                tool_call=AiToolCall(
                                    id=stored["id"], name=stored["name"], arguments={}
                                ),
                                raw_type="chunk",
                            )
            finish_reason = choice.get("finish_reason")
            if finish_reason:
                async for event in completed_calls():
                    yield event
                yield AiEvent(
                    type=AiEventType.DONE,
                    response_id=response_id,
                    usage=usage if isinstance(usage, dict) else None,
                    finish_reason=str(finish_reason),
                    raw_type="chunk",
                )
                return
