from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.adapters import (
    AnthropicMessagesAdapter,
    ChatCompletionsAdapter,
    ProviderRuntime,
    ResponsesAdapter,
)
from app.ai.crypto import decrypt_api_key, encrypt_api_key
from app.ai.schemas import (
    AiEventType,
    AIProviderCreate,
    AiRequest,
    AiToolCall,
    AiToolExchange,
    AiToolResult,
)
from app.ai.service import web_search_allowed
from app.ai.tools import tools_for_mode
from app.api.ai import _probe_provider_runtime
from app.api.ai import router as ai_router
from app.api.approvals import router as approvals_router
from app.api.auth import router as auth_router
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.enums import AIMode, AIProtocol
from app.models import AIProvider


def request() -> AiRequest:
    return AiRequest(messages=[{"role": "user", "content": "Summarize today."}])


@pytest.mark.asyncio
async def test_provider_save_probe_is_enabled_by_default(monkeypatch) -> None:
    calls: list[tuple[AiRequest, str]] = []

    class ProbeAdapter:
        async def complete(self, request, *, system_prompt, tools, enable_web_search):
            del tools, enable_web_search
            calls.append((request, system_prompt))
            return SimpleNamespace()

    monkeypatch.setattr("app.api.ai.adapter_for", lambda runtime: ProbeAdapter())
    runtime = ProviderRuntime(
        protocol=AIProtocol.RESPONSES,
        base_url="https://example.test/v1",
        model="probe-model",
        api_key="probe-token",
        reasoning_effort="medium",
        timeout_seconds=5,
        custom_headers={},
        capabilities={},
    )
    await _probe_provider_runtime(runtime)

    create = AIProviderCreate(
        name="Probe provider",
        protocol=AIProtocol.RESPONSES,
        base_url="https://example.test/v1",
        model="probe-model",
    )
    assert create.probe_before_save is True
    assert calls[0][0].max_output_tokens == 8
    assert calls[0][1] == "Return only OK."


def json_client(response_body: dict[str, Any], captured: list[httpx.Request]) -> httpx.AsyncClient:
    async def handler(incoming: httpx.Request) -> httpx.Response:
        captured.append(incoming)
        return httpx.Response(200, json=response_body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def stream_client(sse: str) -> httpx.AsyncClient:
    async def handler(_incoming: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=sse.encode(),
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def sse_event(name: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, separators=(",", ":"))
    return f"event: {name}\ndata: {data}\n\n"


def sse_data(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, separators=(",", ":"))
    return f"data: {data}\n\n"


@pytest.mark.asyncio
async def test_responses_nonstream_and_web_search_injection() -> None:
    captured: list[httpx.Request] = []
    client = json_client(
        {
            "id": "resp_test",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Done"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "get_overview",
                    "arguments": '{"date_from":"2026-08-28","date_to":"2026-08-28"}',
                },
            ],
            "usage": {"input_tokens": 10, "output_tokens": 2},
        },
        captured,
    )
    adapter = ResponsesAdapter(
        base_url="https://example.test/v1",
        model="test-model",
        api_key="test-token-not-a-real-key",
        reasoning_effort="high",
        timeout_seconds=5,
        client=client,
    )
    result = await adapter.complete(
        request(),
        system_prompt="rules",
        tools=tools_for_mode(AIMode.CHAT),
        enable_web_search=True,
    )
    await client.aclose()

    assert result.text == "Done"
    assert result.tool_calls[0].name == "get_overview"
    assert result.tool_calls[0].arguments["date_from"] == "2026-08-28"
    sent = json.loads(captured[0].content)
    assert sent["reasoning"] == {"effort": "high"}
    assert {tool["type"] for tool in sent["tools"]} == {"function", "web_search"}
    assert captured[0].headers["Authorization"] == "Bearer test-token-not-a-real-key"


@pytest.mark.asyncio
async def test_responses_sse_is_normalized() -> None:
    sse = "".join(
        [
            sse_event(
                "response.created",
                {"type": "response.created", "response": {"id": "resp_1"}},
            ),
            sse_event(
                "response.output_text.delta",
                {"type": "response.output_text.delta", "delta": "Hello"},
            ),
            sse_event(
                "response.output_item.added",
                {
                    "type": "response.output_item.added",
                    "item": {
                        "type": "function_call",
                        "id": "item_1",
                        "call_id": "call_1",
                        "name": "get_overview",
                    },
                },
            ),
            sse_event(
                "response.function_call_arguments.delta",
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "item_1",
                    "delta": '{"date_from":"2026-08-28"}',
                },
            ),
            sse_event(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "function_call",
                        "id": "item_1",
                        "call_id": "call_1",
                        "name": "get_overview",
                        "arguments": '{"date_from":"2026-08-28"}',
                    },
                },
            ),
            sse_event(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_1",
                        "status": "completed",
                        "usage": {"input_tokens": 1},
                    },
                },
            ),
        ]
    )
    client = stream_client(sse)
    adapter = ResponsesAdapter(
        base_url="https://example.test/v1",
        model="test-model",
        api_key=None,
        reasoning_effort="medium",
        timeout_seconds=5,
        client=client,
    )
    events = [
        event
        async for event in adapter.stream(
            request(), system_prompt="rules", tools=tools_for_mode(AIMode.CHAT)
        )
    ]
    await client.aclose()

    assert [event.type for event in events] == [
        AiEventType.START,
        AiEventType.TEXT_DELTA,
        AiEventType.TOOL_CALL_DELTA,
        AiEventType.TOOL_CALL,
        AiEventType.DONE,
    ]
    assert events[3].tool_call is not None
    assert events[3].tool_call.arguments["date_from"] == "2026-08-28"


@pytest.mark.asyncio
async def test_chat_completions_nonstream_and_sse() -> None:
    captured: list[httpx.Request] = []
    client = json_client(
        {
            "id": "chat_1",
            "choices": [
                {
                    "message": {
                        "content": "Answer",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "list_records",
                                    "arguments": '{"limit":10}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        },
        captured,
    )
    adapter = ChatCompletionsAdapter(
        base_url="https://example.test/v1",
        model="chat-model",
        api_key="test-token",
        reasoning_effort="low",
        timeout_seconds=5,
        client=client,
    )
    result = await adapter.complete(
        request(),
        system_prompt="rules",
        tools=tools_for_mode(AIMode.CHAT),
        enable_web_search=True,
    )
    await client.aclose()
    sent = json.loads(captured[0].content)
    assert result.text == "Answer"
    assert result.tool_calls[0].arguments == {"limit": 10}
    assert sent["reasoning_effort"] == "low"
    assert all(tool.get("type") != "web_search" for tool in sent["tools"])

    sse_client_instance = stream_client(
        sse_data(
            {
                "id": "chat_2",
                "choices": [{"delta": {"content": "Hi"}, "finish_reason": None}],
            }
        )
        + sse_data(
            {
                "id": "chat_2",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 1},
            }
        )
    )
    streaming_adapter = ChatCompletionsAdapter(
        base_url="https://example.test/v1",
        model="chat-model",
        api_key=None,
        reasoning_effort="medium",
        timeout_seconds=5,
        client=sse_client_instance,
    )
    events = [
        event
        async for event in streaming_adapter.stream(request(), system_prompt="rules", tools=())
    ]
    await sse_client_instance.aclose()
    assert [event.type for event in events] == [
        AiEventType.START,
        AiEventType.TEXT_DELTA,
        AiEventType.DONE,
    ]
    assert events[1].text == "Hi"


@pytest.mark.asyncio
async def test_anthropic_messages_nonstream_and_sse() -> None:
    captured: list[httpx.Request] = []
    client = json_client(
        {
            "id": "msg_1",
            "content": [
                {"type": "text", "text": "Result"},
                {"type": "tool_use", "id": "tool_1", "name": "get_overview", "input": {}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 4, "output_tokens": 3},
        },
        captured,
    )
    adapter = AnthropicMessagesAdapter(
        base_url="https://example.test/v1",
        model="messages-model",
        api_key="test-token",
        reasoning_effort="xhigh",
        timeout_seconds=5,
        capabilities={"reasoning_effort": True},
        client=client,
    )
    result = await adapter.complete(
        request(), system_prompt="rules", tools=tools_for_mode(AIMode.CHAT)
    )
    await client.aclose()
    sent = json.loads(captured[0].content)
    assert result.text == "Result"
    assert result.tool_calls[0].name == "get_overview"
    assert sent["output_config"] == {"effort": "max"}
    assert captured[0].headers["x-api-key"] == "test-token"

    sse_client_instance = stream_client(
        sse_event(
            "message_start",
            {
                "type": "message_start",
                "message": {"id": "msg_2", "usage": {"input_tokens": 1}},
            },
        )
        + sse_event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello"},
            },
        )
        + sse_event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 1},
            },
        )
        + sse_event("message_stop", {"type": "message_stop"})
    )
    streaming_adapter = AnthropicMessagesAdapter(
        base_url="https://example.test/v1",
        model="messages-model",
        api_key=None,
        reasoning_effort="medium",
        timeout_seconds=5,
        client=sse_client_instance,
    )
    events = [
        event
        async for event in streaming_adapter.stream(request(), system_prompt="rules", tools=())
    ]
    await sse_client_instance.aclose()
    assert [event.type for event in events] == [
        AiEventType.START,
        AiEventType.TEXT_DELTA,
        AiEventType.DONE,
    ]
    assert events[-1].usage == {"input_tokens": 1, "output_tokens": 1}


def test_tool_permissions_crypto_and_web_toggle() -> None:
    chat_tools = tools_for_mode(AIMode.CHAT)
    edit_tools = tools_for_mode(AIMode.EDIT)
    assert chat_tools
    assert all(tool.readonly for tool in chat_tools)
    assert any(not tool.readonly for tool in edit_tools)
    assert all("sql" not in tool.name.casefold() for tool in edit_tools)
    assert "get_import_batch" not in {tool.name for tool in edit_tools}
    assert "set_import_candidate" not in {tool.name for tool in edit_tools}

    encrypted = encrypt_api_key("unit-test-token", "unit-test-application-secret")
    assert "unit-test-token" not in encrypted
    assert decrypt_api_key(encrypted, "unit-test-application-secret") == "unit-test-token"

    provider = SimpleNamespace(
        protocol=AIProtocol.RESPONSES,
        capabilities_json={"web_search": True},
    )
    assert web_search_allowed(
        provider,
        SimpleNamespace(web_access_enabled=True),  # type: ignore[arg-type]
    )
    assert not web_search_allowed(
        provider,
        SimpleNamespace(web_access_enabled=True),  # type: ignore[arg-type]
        AIMode.EDIT,
    )
    edit_payload = ResponsesAdapter(
        base_url="https://example.test/v1",
        model="test-model",
        api_key=None,
        reasoning_effort="medium",
        timeout_seconds=5,
    ).build_payload(
        AiRequest(
            mode=AIMode.EDIT,
            messages=[{"role": "user", "content": "记录一笔费用"}],
        ),
        system_prompt="rules",
        tools=edit_tools,
        enable_web_search=web_search_allowed(
            provider,
            SimpleNamespace(web_access_enabled=True),  # type: ignore[arg-type]
            AIMode.EDIT,
        ),
    )
    assert all(tool.get("type") != "web_search" for tool in edit_payload["tools"])
    assert not web_search_allowed(
        provider,
        SimpleNamespace(web_access_enabled=False),  # type: ignore[arg-type]
    )
    provider.protocol = AIProtocol.CHAT_COMPLETIONS
    assert not web_search_allowed(
        provider,
        SimpleNamespace(web_access_enabled=True),  # type: ignore[arg-type]
    )


def test_tool_results_use_each_protocols_native_message_format() -> None:
    call = AiToolCall(id="call-1", name="get_overview", arguments={"date_from": "2026-08-28"})
    result = AiToolResult(
        tool_call=call,
        result={"ok": True, "data": {"gross_revenue": "100.00"}},
    )
    followup = AiRequest(
        messages=[{"role": "user", "content": "查询收入"}],
        tool_exchanges=[
            AiToolExchange(
                assistant_text="我来查询。",
                tool_calls=[call],
                tool_results=[result],
            )
        ],
    )

    responses = ResponsesAdapter(
        base_url="https://example.test/v1",
        model="model",
        api_key=None,
        reasoning_effort="medium",
        timeout_seconds=5,
    ).build_payload(followup, system_prompt="rules", tools=(), enable_web_search=False)
    response_output = next(
        item for item in responses["input"] if item.get("type") == "function_call_output"
    )
    assert response_output["call_id"] == "call-1"
    assert "UNTRUSTED_TOOL_DATA" in response_output["output"]

    chat = ChatCompletionsAdapter(
        base_url="https://example.test/v1",
        model="model",
        api_key=None,
        reasoning_effort="medium",
        timeout_seconds=5,
    ).build_payload(followup, system_prompt="rules", tools=(), enable_web_search=False)
    assert chat["messages"][-1]["role"] == "tool"
    assert chat["messages"][-1]["tool_call_id"] == "call-1"
    assert "UNTRUSTED_TOOL_DATA" in chat["messages"][-1]["content"]

    anthropic = AnthropicMessagesAdapter(
        base_url="https://example.test/v1",
        model="model",
        api_key=None,
        reasoning_effort="medium",
        timeout_seconds=5,
    ).build_payload(followup, system_prompt="rules", tools=(), enable_web_search=False)
    tool_result = anthropic["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "call-1"
    assert "UNTRUSTED_TOOL_DATA" in tool_result["content"]


def test_provider_secret_is_write_only_and_workspace_settings_are_editable() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    settings = Settings(
        app_env="test",
        app_secret_key="ai-layer-test-application-secret",
        database_url="sqlite://",
        session_cookie_secure=False,
    )

    def override_db():  # type: ignore[no-untyped-def]
        with testing_session() as session:
            yield session

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(ai_router, prefix="/api/v1")
    app.include_router(approvals_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        bootstrapped = client.post(
            "/api/v1/auth/bootstrap",
            json={
                "workspace_name": "AI test workspace",
                "email": "admin@example.com",
                "display_name": "Admin",
                "password": "correct horse battery staple",
            },
        )
        assert bootstrapped.status_code == 201
        csrf = client.cookies.get("ledger_csrf")
        assert csrf
        headers = {"X-CSRF-Token": csrf}

        created = client.post(
            "/api/v1/ai/providers",
            headers=headers,
            json={
                "name": "Compatible provider",
                "protocol": "responses",
                "base_url": "https://example.test/v1/",
                "model": "test-model",
                "api_key": "unit-test-provider-token",
                "reasoning_effort": "high",
                "capabilities_json": {"web_search": True},
                "probe_before_save": False,
            },
        )
        assert created.status_code == 202, created.text
        approval = created.json()
        assert approval["kind"] == "config.ai_provider.create"
        assert approval["status"] == "pending"
        assert approval["payload"]["configuration"]["encrypted_api_key"] == "[redacted]"
        assert "unit-test-provider-token" not in created.text
        assert client.get("/api/v1/ai/providers").json() == []

        approved = client.post(
            f"/api/v1/approvals/{approval['id']}/approve",
            headers=headers,
            json={"reason": "provider reviewed"},
        )
        assert approved.status_code == 200, approved.text
        body = client.get("/api/v1/ai/providers").json()[0]
        assert body["has_api_key"] is True
        assert "api_key" not in body
        assert "encrypted_api_key" not in body
        assert body["base_url"] == "https://example.test/v1"

        listed = client.get("/api/v1/ai/providers")
        assert listed.status_code == 200
        assert "unit-test-provider-token" not in listed.text

        initial_settings = client.get("/api/v1/ai/settings")
        assert initial_settings.status_code == 200
        assert initial_settings.json()["web_access_enabled"] is False
        assert "Chat 模式只允许读取和分析" in initial_settings.json()["agents_md"]

        updated_settings = client.patch(
            "/api/v1/ai/settings",
            headers=headers,
            json={
                "agents_md": "Custom accounting instructions",
                "web_access_enabled": True,
                "version": initial_settings.json()["version"],
            },
        )
        assert updated_settings.status_code == 202
        approval = updated_settings.json()
        assert approval["kind"] == "config.ai_settings.update"
        assert approval["status"] == "pending"
        assert client.get("/api/v1/ai/settings").json() == initial_settings.json()

        approved = client.post(
            f"/api/v1/approvals/{approval['id']}/approve",
            headers=headers,
            json={"reason": "settings reviewed"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert client.get("/api/v1/ai/settings").json() == {
            "agents_md": "Custom accounting instructions",
            "web_access_enabled": True,
            "version": 2,
        }

    with testing_session() as session:
        provider = session.scalar(select(AIProvider))
        assert provider is not None
        assert provider.encrypted_api_key != "unit-test-provider-token"
        assert (
            decrypt_api_key(provider.encrypted_api_key, settings.app_secret_key)
            == "unit-test-provider-token"
        )
    Base.metadata.drop_all(engine)
    engine.dispose()
