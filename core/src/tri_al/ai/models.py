"""The model layer: what an AI task asks a model, and how models are reached.

Tasks (``tri_al.ai.annotate``) are written against ``ChatModel`` alone, so the model behind
one can change without the task knowing: a server such as LM Studio today (the ``openai``
backend), and later a fine-tuned model running in this process, which a plugin adds with
``registry.add_model_backend``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

from tri_al.config import AiConfig


class ModelError(Exception):
    """The model couldn't be reached, or its answer couldn't be used; the message says why."""


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """A model a backend offers."""

    id: str
    kind: str | None = None  # llm, vlm or embeddings, when the backend knows
    loaded: bool | None = None  # whether it's in memory now, when the backend knows
    detail: str | None = None  # a short description, such as "mlx · 8bit"


@runtime_checkable
class ChatModel(Protocol):
    """A language model the tasks prompt. Implementations must be safe to call from threads."""

    @property
    def id(self) -> str: ...

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        thinking: bool = False,
    ) -> str:
        """The model's reply to ``messages``: JSON matching ``schema`` when one is given.

        A model that can think first does so only with ``thinking``: tasks such as annotation
        need the answer fast and within ``max_tokens``. The reply never includes the thinking.
        Raises ``ModelError`` when the model can't answer.
        """
        ...


@runtime_checkable
class ModelBackend(Protocol):
    """How models are reached. The ``[ai]`` settings are passed on each call, since the app
    can change them while it runs."""

    name: str  # what [ai] backend names
    title: str  # for the settings page

    def models(self, config: AiConfig) -> list[ModelInfo]:
        """The models available with these settings; raises ``ModelError`` if it can't tell."""
        ...

    def open(self, config: AiConfig) -> ChatModel:
        """The model ``config.model`` names, or the backend's choice if it's empty."""
        ...

    def close(self) -> None: ...
