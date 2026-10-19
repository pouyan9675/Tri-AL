"""The AI engine (docs/design.md §12): a model layer, and the tasks built on it.

- **Models** (``tri_al.ai.models``): ``ChatModel`` is what a task prompts and
  ``ModelBackend`` is how models are reached. The core's backend is ``openai``, any
  OpenAI-compatible server such as LM Studio; plugins add others with
  ``registry.add_model_backend`` (a fine-tuned model running in this process, say).
- **Tasks**: ``tri_al.ai.annotate`` marks terms of user-defined labels in trial text.

``AiService`` is what the API runs them with. Settings are ``[ai]`` in ``tri-al.toml``, and
changes apply without a restart.
"""

from tri_al.ai.annotate import Span
from tri_al.ai.models import ChatModel, Message, ModelBackend, ModelError, ModelInfo
from tri_al.ai.openai import OpenAICompatible
from tri_al.ai.service import AiService

__all__ = [
    "AiService",
    "ChatModel",
    "Message",
    "ModelBackend",
    "ModelError",
    "ModelInfo",
    "OpenAICompatible",
    "Span",
]
