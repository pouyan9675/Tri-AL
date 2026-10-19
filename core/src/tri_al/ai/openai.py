"""The ``openai`` backend: any server that speaks OpenAI's chat completions API.

LM Studio, Ollama, llama.cpp's server, MLX's and vLLM all do, so one client covers the
models people run locally. Replies are held to a JSON schema with ``response_format``
(constrained decoding on those servers), so a small model can't answer in prose.

Thinking is off unless a task asks for it. Servers turn it off differently, so a request
carries both switches: ``reasoning_effort: "none"`` (LM Studio, which ignores the other) and
``chat_template_kwargs.enable_thinking`` (llama.cpp, vLLM, SGLang). A server that refuses one
gets the request again without it, and isn't sent it again.
"""

import re
from collections.abc import Sequence
from typing import Any

import httpx

from tri_al.ai.models import Message, ModelError, ModelInfo
from tri_al.config import AiConfig

LIST_TIMEOUT = 10.0
"""Listing models should be quick; a server that takes longer is in trouble."""

CHAT_KINDS = ("llm", "vlm")

NO_THINKING: dict[str, Any] = {
    "reasoning_effort": "none",
    "chat_template_kwargs": {"enable_thinking": False},
}
"""What turns thinking off, by request field; each server reads the one it knows."""

_THINK = re.compile(r"^\s*<think>.*?(</think>\s*|$)", re.DOTALL)
"""Thinking a server left in the answer, as some do instead of ``reasoning_content``."""


class _Refused(ModelError):
    """The server refused the request (4xx); ``detail`` is its reason."""

    def __init__(self, message: str, status: int, detail: str) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


class OpenAICompatible:
    """Reaches models through an OpenAI-compatible server, ``[ai] server``."""

    name = "openai"
    title = "OpenAI-compatible server (LM Studio, Ollama, llama.cpp, vLLM)"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(transport=transport)
        self._refused: dict[str, set[str]] = {}  # by server: NO_THINKING fields it refused

    def models(self, config: AiConfig) -> list[ModelInfo]:
        """The server's chat models, loaded ones first; embedding models are left out."""
        timeout = min(config.timeout, LIST_TIMEOUT)
        models = self._lmstudio_models(config.server, timeout)
        if models is None:
            body = self._request("GET", f"{config.server}/models", config.server, timeout)
            models = [
                ModelInfo(id=str(item["id"]))
                for item in _items(body)
                if isinstance(item, dict) and item.get("id")
            ]
        chat = [m for m in models if m.kind in (None, *CHAT_KINDS) and "embed" not in m.id]
        return sorted(chat, key=lambda m: m.loaded is not True)

    def open(self, config: AiConfig) -> "ServerModel":
        model = config.model
        if not model:
            models = self.models(config)
            if not models:
                raise ModelError(f"the server at {config.server} lists no models")
            model = models[0].id
        return ServerModel(self, config.server, model, config.timeout)

    def close(self) -> None:
        self._client.close()

    def _lmstudio_models(self, server: str, timeout: float) -> list[ModelInfo] | None:
        """LM Studio's own API says which models are loaded; None from other servers."""
        root = server.removesuffix("/v1")
        if root == server:
            return None
        try:
            body = self._request("GET", f"{root}/api/v0/models", server, timeout)
        except ModelError:
            return None
        models = []
        for item in _items(body):
            if not isinstance(item, dict) or not item.get("id"):
                return None
            detail = " · ".join(
                str(item[key]) for key in ("compatibility_type", "quantization") if item.get(key)
            )
            models.append(
                ModelInfo(
                    id=str(item["id"]),
                    kind=item.get("type"),
                    loaded=item.get("state") == "loaded" if "state" in item else None,
                    detail=detail or None,
                )
            )
        return models

    def _request(self, method: str, url: str, server: str, timeout: float, json: Any = None) -> Any:
        try:
            response = self._client.request(method, url, json=json, timeout=timeout)
        except httpx.TimeoutException:
            raise ModelError(f"the model server didn't answer within {timeout:g} s") from None
        except httpx.HTTPError:
            raise ModelError(f"can't reach the model server at {server}; is it running?") from None
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.is_error:
            detail = _error_text(body, response)
            message = f"the model server answered {response.status_code}: {detail}"
            if 400 <= response.status_code < 500:
                raise _Refused(message, response.status_code, detail)
            raise ModelError(message)
        if body is None:
            raise ModelError("the model server's answer wasn't JSON")
        return body


class ServerModel:
    """One model on an OpenAI-compatible server."""

    def __init__(self, backend: OpenAICompatible, server: str, model: str, timeout: float) -> None:
        self._backend = backend
        self._server = server
        self._model = model
        self._timeout = timeout

    @property
    def id(self) -> str:
        return self._model

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        thinking: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": list(messages),
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "strict": True, "schema": schema},
            }
        refused = self._backend._refused.setdefault(self._server, set())
        while True:
            if not thinking:
                payload |= {k: v for k, v in NO_THINKING.items() if k not in refused}
            try:
                body = self._backend._request(
                    "POST", f"{self._server}/chat/completions", self._server, self._timeout, payload
                )
                break
            except _Refused as exc:
                field = next((f for f in NO_THINKING if f in payload and f in exc.detail), None)
                if field is None:
                    raise
                refused.add(field)
                del payload[field]
        try:
            choice = body["choices"][0]
            message = choice["message"]
            content = _THINK.sub("", message.get("content") or "")
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ModelError("the model server's answer had no message") from None
        if not content.strip():
            thought = message.get("reasoning_content") or message.get("reasoning")
            if thought or (message.get("content") or "").lstrip().startswith("<think>"):
                why = f"{self._model} spent its {max_tokens} tokens thinking and never answered"
                if not thinking:
                    why += "; its server didn't turn thinking off, so choose another model"
                raise ModelError(why)
            if choice.get("finish_reason") == "length":
                raise ModelError(f"{self._model} ran out of tokens before it answered")
            raise ModelError(f"{self._model} gave an empty answer")
        return str(content)


def _items(body: Any) -> list[Any]:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise ModelError("the model server's list of models wasn't in the expected shape")
    return data


def _error_text(body: Any, response: httpx.Response) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        error = error.get("message")
    if isinstance(error, str) and error.strip():
        return error.strip()
    return response.reason_phrase or "an error"
