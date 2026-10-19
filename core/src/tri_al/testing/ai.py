"""Stand-ins for models in tests: no server, instant, deterministic."""

import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tri_al.ai import Message, ModelError, ModelInfo
from tri_al.config import AiConfig


@dataclass
class FakeChatModel:
    """Answers an annotation prompt with each of ``terms`` (term → label) found in the text.

    ``replies`` overrides that with fixed replies, one per call in turn; ``error`` makes every
    call fail. ``calls`` records the messages of each call, and ``thought`` whether each
    asked for thinking.
    """

    terms: Mapping[str, str] = field(default_factory=dict)
    id: str = "fake-model"
    replies: list[str] = field(default_factory=list)
    error: str | None = None
    calls: list[list[Message]] = field(default_factory=list)
    thought: list[bool] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        thinking: bool = False,
    ) -> str:
        with self._lock:
            self.calls.append(list(messages))
            self.thought.append(thinking)
            reply = self.replies.pop(0) if self.replies else None
        if self.error is not None:
            raise ModelError(self.error)
        if reply is not None:
            return reply
        text = messages[-1]["content"].casefold()
        found = [{"text": t, "label": lb} for t, lb in self.terms.items() if t.casefold() in text]
        return json.dumps({"entities": found})


@dataclass
class FakeModelBackend:
    """A backend named ``fake`` that offers ``model``; ``error`` makes it unreachable."""

    model: FakeChatModel = field(default_factory=FakeChatModel)
    name: str = "fake"
    title: str = "Fake models"
    error: str | None = None
    closed: bool = False

    def models(self, config: AiConfig) -> list[ModelInfo]:
        if self.error is not None:
            raise ModelError(self.error)
        return [ModelInfo(id=self.model.id, kind="llm", loaded=True)]

    def open(self, config: AiConfig) -> FakeChatModel:
        if self.error is not None:
            raise ModelError(self.error)
        return self.model

    def close(self) -> None:
        self.closed = True
