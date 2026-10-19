"""One way to talk to any model: messages with text / images / PDFs, tools, and structured output.

Two backends: Anthropic through the official ``anthropic`` SDK, and every OpenAI-compatible endpoint (OpenAI itself,
an owner's relay, other vendors) through the official ``openai`` SDK's Chat Completions. A provider says what it can
do (``Capabilities``); what it can't is degraded here, not by callers:

- no PDF input → the PDF's text layer as text, or, for image-only PDFs, its page images;
- no structured output → JSON mode, validated against the schema, with one repair round;
- no server-side fallback → the beta header is never sent.
"""

from __future__ import annotations

import base64
import io
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

import jsonschema

from bookkeeper.domain.errors import DomainError

PDF = "application/pdf"
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_PDF_IMAGES = 20


@dataclass(frozen=True)
class Capabilities:
    images: bool = True
    pdf: bool = True
    structured: bool = True
    tools: bool = True
    fallback: bool = False

    @classmethod
    def of(cls, data: dict[str, Any] | None) -> Capabilities:
        data = data or {}
        return cls(**{k: bool(data[k]) for k in ("images", "pdf", "structured", "tools", "fallback") if k in data})

    def as_dict(self) -> dict[str, bool]:
        return {k: getattr(self, k) for k in ("images", "pdf", "structured", "tools", "fallback")}


@dataclass(frozen=True)
class Target:
    """A provider and model, with the key already unsealed (never logged, never returned to clients)."""

    provider_id: str | None
    provider_name: str
    kind: Literal["anthropic", "openai_compatible"]
    model: str
    api_key: str
    base_url: str | None = None
    timeout: float = 120.0
    capabilities: Capabilities = field(default_factory=Capabilities)
    options: dict[str, Any] = field(default_factory=dict)  # effort, max_tokens_param
    prices: dict[str, Any] = field(default_factory=dict)  # model → {"input": $/Mtok, "output": $/Mtok}


@dataclass
class Part:
    kind: Literal["text", "image", "pdf"]
    text: str = ""
    data: bytes = b""
    mime: str = ""
    name: str = ""

    @staticmethod
    def of_text(text: str) -> Part:
        return Part("text", text=text)

    @staticmethod
    def of_file(name: str, data: bytes, mime: str) -> Part:
        if mime == PDF:
            return Part("pdf", data=data, mime=mime, name=name)
        if mime in IMAGE_TYPES:
            return Part("image", data=data, mime=mime, name=name)
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", f"{name}：AI 只读截图（PNG / JPEG / WebP）和 PDF。")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    invalid: str | None = None  # arguments that were not valid JSON


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    parts: list[Part] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # for role="tool"
    is_error: bool = False
    native: Any = None  # the provider's own assistant content, replayed verbatim (e.g. thinking blocks)
    native_kind: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]


@dataclass
class Request:
    system: str
    messages: list[Message]
    tools: Sequence[ToolSpec] = ()
    schema: dict[str, Any] | None = None  # structured output
    max_tokens: int = 8000


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Response:
    text: str
    tool_calls: list[ToolCall]
    stop: Literal["end", "tool_use", "max_tokens", "refusal"]
    usage: Usage
    model: str
    data: Any = None  # parsed JSON when the request had a schema
    native: Any = None
    native_kind: str | None = None
    seconds: float = 0.0

    def assistant_message(self) -> Message:
        return Message(
            "assistant",
            [Part.of_text(self.text)] if self.text else [],
            list(self.tool_calls),
            native=self.native,
            native_kind=self.native_kind,
        )


class Backend(Protocol):
    def complete(self, target: Target, request: Request, *, json_mode: bool) -> Response: ...
    def list_models(self, target: Target) -> list[str]: ...


# ------------------------------------------------------------------ degradation


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        return "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages).strip()
    except Exception:
        return ""


def pdf_images(data: bytes) -> list[tuple[bytes, str]]:
    """The images on each page of an image-only PDF (a print of a screen), in page order."""
    from pypdf import PdfReader

    found: list[tuple[bytes, str]] = []
    try:
        for page in PdfReader(io.BytesIO(data)).pages:
            for image in page.images:
                name = image.name.lower()
                mime = "image/png" if name.endswith(".png") else "image/jpeg"
                found.append((image.data, mime))
                if len(found) >= MAX_PDF_IMAGES:
                    return found
    except Exception:
        return found
    return found


def adapt(request: Request, caps: Capabilities) -> Request:
    """What this provider can actually take: PDFs it can't read become text or images; refuses what's left."""
    if request.tools and not caps.tools:
        raise DomainError("AI_UNAVAILABLE", "这个提供商不支持工具调用，不能用于 agent。请在 设置 → AI 换一个。")
    messages = []
    for message in request.messages:
        parts: list[Part] = []
        for part in message.parts:
            if part.kind == "pdf" and not caps.pdf:
                text = pdf_text(part.data)
                if text:
                    parts.append(Part.of_text(f"〔PDF《{part.name}》的文字层〕\n{text}"))
                    continue
                images = pdf_images(part.data)
                if not images or not caps.images:
                    raise DomainError("AI_UNAVAILABLE", f"{part.name}：这个提供商不读 PDF，且无法把它转成文字或图片。")
                parts += [Part("image", data=d, mime=m, name=part.name) for d, m in images]
                continue
            if part.kind == "image" and not caps.images:
                raise DomainError("AI_UNAVAILABLE", f"{part.name}：这个提供商不支持图片输入。")
            parts.append(part)
        messages.append(replace(message, parts=parts))
    return replace(request, messages=messages)


def validate(data: Any, schema: dict[str, Any]) -> str | None:
    """The first schema violation as a sentence, or None."""
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "（根）"
        return f"{where}: {exc.message}"
    return None


def complete(target: Target, request: Request, backend: Backend | None = None) -> Response:
    """One call, degraded to what the provider supports. With a schema, the answer is parsed and validated; in
    JSON mode a wrong answer gets one repair round."""
    backend = backend or backend_for(target)
    request = adapt(request, target.capabilities)
    json_mode = request.schema is not None and not target.capabilities.structured
    started = time.monotonic()
    response = backend.complete(target, request, json_mode=json_mode)
    if request.schema is not None and response.stop not in ("refusal", "max_tokens"):
        problem = _parse(response, request.schema)
        if problem and json_mode:
            repair = replace(
                request,
                messages=[
                    *request.messages,
                    response.assistant_message(),
                    Message("user", [Part.of_text(f"上面的 JSON 不符合要求（{problem}）。只输出修正后的完整 JSON。")]),
                ],
            )
            second = backend.complete(target, repair, json_mode=True)
            second.usage = Usage(
                response.usage.input_tokens + second.usage.input_tokens,
                response.usage.output_tokens + second.usage.output_tokens,
            )
            response = second
            problem = _parse(response, request.schema) if response.stop not in ("refusal", "max_tokens") else None
        if problem:
            raise DomainError("AI_UNAVAILABLE", f"AI 返回的结果不符合格式（{problem}），请重试或换一个模型。")
    response.seconds = time.monotonic() - started
    return response


def _parse(response: Response, schema: dict[str, Any]) -> str | None:
    text = response.text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        response.data = json.loads(text)
    except json.JSONDecodeError, ValueError:
        return "不是有效的 JSON"
    return validate(response.data, schema)


def cost(target: Target, usage: Usage) -> float | None:
    price = target.prices.get(target.model) if isinstance(target.prices, dict) else None
    if not isinstance(price, dict):
        return None
    try:
        return (usage.input_tokens * float(price["input"]) + usage.output_tokens * float(price["output"])) / 1e6
    except KeyError, TypeError, ValueError:
        return None


def backend_for(target: Target) -> Backend:
    return ANTHROPIC if target.kind == "anthropic" else OPENAI


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()


# ------------------------------------------------------------------ Anthropic


class AnthropicBackend:
    """Messages API through the official SDK; streamed (long outputs), the final message assembled by the SDK."""

    def client(self, target: Target) -> Any:
        import anthropic

        return anthropic.Anthropic(
            api_key=target.api_key, base_url=target.base_url or None, timeout=target.timeout, max_retries=2
        )

    def list_models(self, target: Target) -> list[str]:
        import anthropic

        try:
            return [m.id for m in self.client(target).models.list(limit=100)]
        except anthropic.APIError as exc:
            raise _anthropic_error(exc) from exc

    def complete(self, target: Target, request: Request, *, json_mode: bool) -> Response:
        import anthropic

        official = not target.base_url
        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.schema}
            | ({"eager_input_streaming": True} if official else {})
            for t in request.tools
        ]
        output_config: dict[str, Any] = {}
        if target.options.get("effort"):
            output_config["effort"] = target.options["effort"]
        system = request.system
        if request.schema is not None:
            if json_mode:
                system += "\n\n只输出一个 JSON 对象，符合这个 JSON Schema，不要任何其他文字：\n" + json.dumps(
                    request.schema, ensure_ascii=False
                )
            else:
                output_config["format"] = {"type": "json_schema", "schema": request.schema}
        params: dict[str, Any] = {
            "model": target.model,
            "max_tokens": request.max_tokens,
            "system": system,
            "messages": [self._message(m) for m in request.messages],
        }
        if tools:
            params["tools"] = tools
        if output_config:
            params["output_config"] = output_config
        try:
            if target.capabilities.fallback:
                params |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
                with self.client(target).beta.messages.stream(**params) as stream:
                    message = stream.get_final_message()
            else:
                with self.client(target).messages.stream(**params) as stream:
                    message = stream.get_final_message()
        except anthropic.APIError as exc:
            raise _anthropic_error(exc) from exc
        text = "".join(b.text for b in message.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input or {})) for b in message.content if b.type == "tool_use"]
        stop = {"tool_use": "tool_use", "max_tokens": "max_tokens", "refusal": "refusal"}.get(
            str(message.stop_reason), "end"
        )
        return Response(
            text=text,
            tool_calls=calls,
            stop=stop,  # type: ignore[arg-type]
            usage=Usage(message.usage.input_tokens or 0, message.usage.output_tokens or 0),
            model=message.model,
            native=[b.model_dump(mode="json", exclude_none=True) for b in message.content],
            native_kind="anthropic",
        )

    def _message(self, m: Message) -> dict[str, Any]:
        if m.role == "tool":
            body = "\n".join(p.text for p in m.parts if p.kind == "text")
            block: dict[str, Any] = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": body}
            if m.is_error:
                block["is_error"] = True
            return {"role": "user", "content": [block]}
        if m.role == "assistant":
            if m.native_kind == "anthropic" and m.native:
                return {"role": "assistant", "content": m.native}
            blocks: list[dict[str, Any]] = [{"type": "text", "text": p.text} for p in m.parts if p.text]
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in m.tool_calls]
            return {"role": "assistant", "content": blocks}
        content: list[dict[str, Any]] = []
        for p in m.parts:
            if p.kind == "text":
                content.append({"type": "text", "text": p.text})
            elif p.kind == "image":
                content.append(
                    {"type": "image", "source": {"type": "base64", "media_type": p.mime, "data": _b64(p.data)}}
                )
            else:
                content.append(
                    {"type": "document", "source": {"type": "base64", "media_type": PDF, "data": _b64(p.data)}}
                )
        return {"role": "user", "content": content}


def _anthropic_error(exc: Exception) -> DomainError:
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return DomainError("AI_UNAVAILABLE", "AI 提供商拒绝了密钥：请在 设置 → AI 检查密钥与地址。")
    if isinstance(exc, anthropic.RateLimitError):
        return DomainError("AI_UNAVAILABLE", "AI 服务正忙（请求过多），请稍后再试。")
    if isinstance(exc, anthropic.NotFoundError):
        return DomainError("AI_UNAVAILABLE", "AI 提供商找不到这个模型或地址：请检查模型名与 Base URL。")
    if isinstance(exc, anthropic.BadRequestError):
        return DomainError("INPUT_INVALID", f"AI 无法处理这个请求（{exc.message}）。")
    return DomainError("AI_UNAVAILABLE", "AI 服务暂时连不上，请稍后再试。")


# ------------------------------------------------------------------ OpenAI-compatible


class OpenAIBackend:
    """Chat Completions through the official ``openai`` SDK: the API OpenAI-compatible relays and vendors share."""

    def client(self, target: Target) -> Any:
        import openai

        return openai.OpenAI(
            api_key=target.api_key, base_url=target.base_url or None, timeout=target.timeout, max_retries=2
        )

    def list_models(self, target: Target) -> list[str]:
        import openai

        try:
            return sorted(m.id for m in self.client(target).models.list())
        except openai.APIError as exc:
            raise _openai_error(exc) from exc

    def complete(self, target: Target, request: Request, *, json_mode: bool) -> Response:
        import openai

        messages: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
        messages += [self._message(m) for m in request.messages]
        params: dict[str, Any] = {"model": target.model, "messages": messages}
        params[str(target.options.get("max_tokens_param") or "max_tokens")] = request.max_tokens
        if request.tools:
            params["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}}
                for t in request.tools
            ]
        if request.schema is not None:
            if json_mode:
                params["response_format"] = {"type": "json_object"}
                messages[0]["content"] += "\n\n只输出一个 JSON 对象，符合这个 JSON Schema：\n" + json.dumps(
                    request.schema, ensure_ascii=False
                )
            else:
                params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": request.schema, "strict": True},
                }
        try:
            completion = self.client(target).chat.completions.create(**params)
        except openai.APIError as exc:
            raise _openai_error(exc) from exc
        choice = completion.choices[0]
        message = choice.message
        calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            raw = getattr(getattr(call, "function", None), "arguments", "") or ""
            try:
                parsed = json.loads(raw) if raw else {}
                calls.append(ToolCall(call.id, call.function.name, parsed if isinstance(parsed, dict) else {}))
            except json.JSONDecodeError:
                calls.append(ToolCall(call.id, call.function.name, {}, invalid=raw[:500]))
        refusal = getattr(message, "refusal", None)
        stop = (
            "refusal"
            if refusal or choice.finish_reason == "content_filter"
            else "max_tokens"
            if choice.finish_reason == "length"
            else "tool_use"
            if calls
            else "end"
        )
        usage = completion.usage
        return Response(
            text=message.content or "",
            tool_calls=calls,
            stop=stop,  # type: ignore[arg-type]
            usage=Usage(getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0),
            model=completion.model or target.model,
            native=message.model_dump(mode="json", exclude_none=True),
            native_kind="openai",
        )

    def _message(self, m: Message) -> dict[str, Any]:
        if m.role == "tool":
            return {"role": "tool", "tool_call_id": m.tool_call_id, "content": "\n".join(p.text for p in m.parts)}
        if m.role == "assistant":
            if m.native_kind == "openai" and m.native:
                native = dict(m.native)
                native.setdefault("role", "assistant")
                return native
            out: dict[str, Any] = {"role": "assistant", "content": "\n".join(p.text for p in m.parts) or None}
            if m.tool_calls:
                out["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
                    }
                    for c in m.tool_calls
                ]
            return out
        content: list[dict[str, Any]] = []
        for p in m.parts:
            if p.kind == "text":
                content.append({"type": "text", "text": p.text})
            elif p.kind == "image":
                content.append({"type": "image_url", "image_url": {"url": f"data:{p.mime};base64,{_b64(p.data)}"}})
            else:
                content.append(
                    {
                        "type": "file",
                        "file": {"filename": p.name or "file.pdf", "file_data": f"data:{PDF};base64,{_b64(p.data)}"},
                    }
                )
        return {"role": "user", "content": content}


def _openai_error(exc: Exception) -> DomainError:
    import openai

    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return DomainError("AI_UNAVAILABLE", "AI 提供商拒绝了密钥：请在 设置 → AI 检查密钥与地址。")
    if isinstance(exc, openai.RateLimitError):
        return DomainError("AI_UNAVAILABLE", "AI 服务正忙（请求过多），请稍后再试。")
    if isinstance(exc, openai.NotFoundError):
        return DomainError("AI_UNAVAILABLE", "AI 提供商找不到这个模型或地址：请检查模型名与 Base URL。")
    if isinstance(exc, openai.BadRequestError):
        return DomainError("INPUT_INVALID", f"AI 无法处理这个请求（{getattr(exc, 'message', exc)}）。")
    return DomainError("AI_UNAVAILABLE", "AI 服务暂时连不上，请稍后再试。")


ANTHROPIC = AnthropicBackend()
OPENAI = OpenAIBackend()
