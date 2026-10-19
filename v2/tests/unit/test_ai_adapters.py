"""The adapter layer: what each provider kind is sent, and how missing capabilities are degraded."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Any

import pytest

from bookkeeper.ai import adapters
from bookkeeper.ai.adapters import Capabilities, Message, Part, Request, Response, Target, ToolSpec, Usage
from bookkeeper.domain.errors import DomainError

SCHEMA = {
    "type": "object",
    "properties": {"total": {"type": "string"}},
    "required": ["total"],
    "additionalProperties": False,
}


def target(**kw: Any) -> Target:
    return Target(None, "t", kw.pop("kind", "anthropic"), "m-1", "key", **kw)


def text_pdf() -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(200, 200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (Total 42.00) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_a_provider_without_pdf_input_gets_the_text_layer() -> None:
    request = Request("s", [Message("user", [Part("pdf", data=text_pdf(), mime=adapters.PDF, name="a.pdf")])])
    adapted = adapters.adapt(request, Capabilities(pdf=False))
    [part] = adapted.messages[0].parts
    assert part.kind == "text" and "Total 42.00" in part.text and "a.pdf" in part.text
    assert adapters.adapt(request, Capabilities(pdf=True)).messages[0].parts[0].kind == "pdf"


def test_an_image_only_pdf_becomes_its_page_images(monkeypatch) -> None:
    monkeypatch.setattr(adapters, "pdf_text", lambda data: "")
    monkeypatch.setattr(adapters, "pdf_images", lambda data: [(b"img1", "image/png"), (b"img2", "image/jpeg")])
    request = Request("s", [Message("user", [Part("pdf", data=b"%PDF", mime=adapters.PDF, name="scan.pdf")])])
    parts = adapters.adapt(request, Capabilities(pdf=False)).messages[0].parts
    assert [(p.kind, p.mime) for p in parts] == [("image", "image/png"), ("image", "image/jpeg")]
    with pytest.raises(DomainError):
        adapters.adapt(request, Capabilities(pdf=False, images=False))


def test_tools_need_a_provider_that_calls_tools() -> None:
    request = Request("s", [Message("user", [Part.of_text("hi")])], tools=[ToolSpec("t", "d", {"type": "object"})])
    with pytest.raises(DomainError):
        adapters.adapt(request, Capabilities(tools=False))


class Answers:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.modes: list[bool] = []

    def complete(self, target: Target, request: Request, *, json_mode: bool) -> Response:
        self.modes.append(json_mode)
        return Response(self.texts.pop(0), [], "end", Usage(10, 5), target.model)

    def list_models(self, target: Target) -> list[str]:
        return []


def test_without_structured_output_json_mode_is_validated_and_repaired_once() -> None:
    backend = Answers('{"total": 42}', '{"total": "42.00"}')
    request = Request("s", [Message("user", [Part.of_text("read")])], schema=SCHEMA)
    response = adapters.complete(target(capabilities=Capabilities(structured=False)), request, backend)
    assert response.data == {"total": "42.00"} and backend.modes == [True, True]
    assert response.usage == Usage(20, 10)
    still_wrong = Answers("not json", "still not json")
    with pytest.raises(DomainError, match="不符合格式"):
        adapters.complete(target(capabilities=Capabilities(structured=False)), request, still_wrong)


def test_with_structured_output_a_wrong_answer_is_not_retried() -> None:
    backend = Answers('{"total": 1}')
    request = Request("s", [Message("user", [Part.of_text("read")])], schema=SCHEMA)
    with pytest.raises(DomainError):
        adapters.complete(target(), request, backend)
    assert backend.modes == [False]


class FakeStream:
    def __init__(self, message: Any) -> None:
        self.message = message

    def __enter__(self) -> FakeStream:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def get_final_message(self) -> Any:
        return self.message


def anthropic_message(**kw: Any) -> Any:
    block = SimpleNamespace(type="text", text='{"total": "1.00"}', model_dump=lambda **_: {"type": "text", "text": "x"})
    return SimpleNamespace(
        content=kw.get("content", [block]),
        stop_reason=kw.get("stop_reason", "end_turn"),
        usage=SimpleNamespace(input_tokens=7, output_tokens=3),
        model="m-1",
    )


def test_anthropic_requests_send_the_fallback_header_only_when_enabled(monkeypatch) -> None:
    sent: dict[str, Any] = {}

    def stream(**params: Any) -> FakeStream:
        sent.clear()
        sent.update(params)
        return FakeStream(anthropic_message())

    client = SimpleNamespace(
        messages=SimpleNamespace(stream=stream), beta=SimpleNamespace(messages=SimpleNamespace(stream=stream))
    )
    backend = adapters.AnthropicBackend()
    monkeypatch.setattr(backend, "client", lambda t: client)
    pdf = Part("pdf", data=b"%PDF-1", mime=adapters.PDF, name="a.pdf")
    request = Request("sys", [Message("user", [pdf, Part.of_text("read")])], schema=SCHEMA)
    response = adapters.complete(target(options={"effort": "medium"}), request, backend)
    assert response.data == {"total": "1.00"} and "betas" not in sent and "fallbacks" not in sent
    assert sent["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert sent["messages"][0]["content"][0]["type"] == "document"
    adapters.complete(target(capabilities=Capabilities(fallback=True)), request, backend)
    assert sent["betas"] == [adapters.FALLBACK_BETA] and sent["fallbacks"] == "default"


def test_openai_compatible_requests_use_chat_completions_shapes(monkeypatch) -> None:
    sent: dict[str, Any] = {}
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="lookup", arguments='{"q": "x"}'))
    reply = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content=None, tool_calls=[call], refusal=None, model_dump=lambda **_: {"role": "assistant"}
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=4),
        model="m-1",
    )

    def create(**params: Any) -> Any:
        sent.update(params)
        return reply

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    backend = adapters.OpenAIBackend()
    monkeypatch.setattr(backend, "client", lambda t: client)
    image = Part("image", data=b"PNG", mime="image/png", name="a.png")
    pdf = Part("pdf", data=b"%PDF", mime=adapters.PDF, name="b.pdf")
    request = Request(
        "sys",
        [Message("user", [image, pdf, Part.of_text("go")])],
        tools=[ToolSpec("lookup", "find", {"type": "object", "properties": {"q": {"type": "string"}}})],
    )
    response = adapters.complete(
        target(kind="openai_compatible", base_url="https://relay.example.com/v1", capabilities=Capabilities(pdf=True)),
        request,
        backend,
    )
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    content = sent["messages"][1]["content"]
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert sent["tools"][0] == {
        "type": "function",
        "function": {"name": "lookup", "description": "find", "parameters": request.tools[0].schema},
    }
    assert sent["max_tokens"] == request.max_tokens
    assert response.stop == "tool_use" and response.tool_calls[0].arguments == {"q": "x"}
    assert response.usage == Usage(11, 4)

    structured = Request("sys", [Message("user", [Part.of_text("go")])], schema=SCHEMA)
    reply.choices[0].message.content = json.dumps({"total": "2.00"})
    reply.choices[0].message.tool_calls = None
    reply.choices[0].finish_reason = "stop"
    out = adapters.complete(target(kind="openai_compatible", base_url="https://r.example.com"), structured, backend)
    assert sent["response_format"]["type"] == "json_schema" and out.data == {"total": "2.00"}
    adapters.complete(
        target(kind="openai_compatible", base_url="https://r.example.com", capabilities=Capabilities(structured=False)),
        structured,
        backend,
    )
    assert sent["response_format"] == {"type": "json_object"}


def test_cost_needs_a_price_for_the_model() -> None:
    priced = target(prices={"m-1": {"input": 3, "output": 15}})
    assert adapters.cost(priced, Usage(1_000_000, 1_000_000)) == pytest.approx(18.0)
    assert adapters.cost(target(), Usage(10, 10)) is None


def test_anthropic_tool_results_and_attachments_share_one_user_turn(monkeypatch) -> None:
    sent: dict[str, Any] = {}

    def stream(**params: Any) -> FakeStream:
        sent.update(params)
        return FakeStream(anthropic_message())

    client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
    backend = adapters.AnthropicBackend()
    monkeypatch.setattr(backend, "client", lambda t: client)
    from bookkeeper.ai.adapters import ToolCall

    messages = [
        Message("user", [Part.of_text("go")]),
        Message("assistant", [], [ToolCall("t1", "read_file", {}), ToolCall("t2", "list_files", {})]),
        Message("tool", [Part.of_text("a")], tool_call_id="t1"),
        Message("tool", [Part.of_text("b")], tool_call_id="t2"),
        Message("user", [Part("image", data=b"PNG", mime="image/png", name="a.png")]),
    ]
    adapters.complete(target(), Request("s", messages), backend)
    roles = [m["role"] for m in sent["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert [b["type"] for b in sent["messages"][2]["content"]] == ["tool_result", "tool_result", "image"]
