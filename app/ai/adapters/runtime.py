from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.ai.adapters.anthropic_messages import AnthropicMessagesAdapter
from app.ai.adapters.base import BaseAdapter
from app.ai.adapters.chat_completions import ChatCompletionsAdapter
from app.ai.adapters.responses import ResponsesAdapter
from app.enums import AIProtocol


@dataclass(slots=True)
class ProviderRuntime:
    protocol: AIProtocol
    base_url: str
    model: str
    api_key: str | None
    reasoning_effort: str
    timeout_seconds: int = 120
    custom_headers: dict[str, str] = field(default_factory=dict)
    capabilities: dict[str, bool] = field(default_factory=dict)


def adapter_for(runtime: ProviderRuntime, client: httpx.AsyncClient | None = None) -> BaseAdapter:
    adapter_type: type[BaseAdapter]
    if runtime.protocol == AIProtocol.RESPONSES:
        adapter_type = ResponsesAdapter
    elif runtime.protocol == AIProtocol.CHAT_COMPLETIONS:
        adapter_type = ChatCompletionsAdapter
    elif runtime.protocol == AIProtocol.ANTHROPIC_MESSAGES:
        adapter_type = AnthropicMessagesAdapter
    else:
        raise ValueError(f"unsupported AI protocol: {runtime.protocol}")
    return adapter_type(
        base_url=runtime.base_url,
        model=runtime.model,
        api_key=runtime.api_key,
        reasoning_effort=runtime.reasoning_effort,
        timeout_seconds=runtime.timeout_seconds,
        custom_headers=runtime.custom_headers,
        capabilities=runtime.capabilities,
        client=client,
    )
