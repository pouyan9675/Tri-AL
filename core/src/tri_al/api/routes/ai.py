"""The AI engine (docs/design.md §12): its settings, the models it can use, and annotation.

Settings are ``[ai]`` in ``tri-al.toml``; unlike plugin settings, a change applies to the
next request, with no restart (``tri_al.ai.AiService``).
"""

import os
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from tri_al.access import EDIT_AI, READ, USE_AI, require
from tri_al.ai import ModelError
from tri_al.ai.annotate import colored
from tri_al.api.http import NO_STORE, live_json
from tri_al.api.models import (
    AiModelsIn,
    AiModelsOut,
    AiSettingsOut,
    AiSettingsPatch,
    AnnotateIn,
    AnnotationEvent,
    ErrorOut,
)
from tri_al.api.routes.data import State, _find
from tri_al.api.state import ApiState
from tri_al.config import LABEL_COLORS, AiConfig, ConfigError, edit_ai_section

router = APIRouter(prefix="/api", tags=["ai"])


class NDJSONResponse(StreamingResponse):
    """A stream of JSON lines; the class names the media type in the OpenAPI schema."""

    media_type = "application/x-ndjson"


def _error(description: str) -> dict[str, Any]:
    """An error response, which is JSON: with ``model``, FastAPI would file it under the
    stream's media type."""
    schema = {"$ref": "#/components/schemas/ErrorOut"}
    return {"description": description, "content": {"application/json": {"schema": schema}}}


ENV_PREFIX = "TRI_AL_AI__"


def _settings_json(state: ApiState, config: AiConfig) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "backend": config.backend,
        "backends": [
            {"name": backend.name, "title": backend.title} for backend in state.ai.backends.values()
        ],
        "server": config.server,
        "model": config.model,
        "labels": [label.model_dump() for label in colored(config.annotation.labels)],
        "colors": list(LABEL_COLORS),
        "locked": _locked(),
    }


def _locked() -> list[str]:
    """The settings ``TRI_AL_AI__*`` variables set: ``server``, ``model``, ``labels``, ..."""
    keys = set()
    for var in os.environ:
        if var.startswith(ENV_PREFIX):
            parts = var.removeprefix(ENV_PREFIX).lower().split("__")
            keys.add(parts[1] if parts[0] == "annotation" and len(parts) > 1 else parts[0])
    return sorted(keys)


def _validated(data: dict[str, Any]) -> AiConfig:
    try:
        return AiConfig.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(map(str, error['loc'])) or '(settings)'}: {error['msg']}"
            for error in exc.errors()
        )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problems) from None


@router.get(
    "/ai",
    response_model=AiSettingsOut,
    dependencies=[Depends(require(READ))],
    name="getAiSettings",
)
def get_settings(state: State) -> Response:
    """The AI engine's settings: the model server, the model and the annotation labels."""
    return live_json(_settings_json(state, state.ai.config()))


@router.patch(
    "/ai",
    response_model=AiSettingsOut,
    responses={422: {"model": ErrorOut}},
    dependencies=[Depends(require(EDIT_AI))],
    name="updateAiSettings",
)
def update_settings(state: State, patch: AiSettingsPatch) -> Response:
    """Change the AI settings in ``tri-al.toml``. They apply at once.

    Everything is checked before anything is written; ``labels`` replaces every label.
    """
    current = state.ai.config()
    changes = patch.model_dump(exclude_unset=True, exclude={"labels"})
    data = current.model_dump() | changes
    if patch.labels is not None:
        data["annotation"]["labels"] = [label.model_dump() for label in patch.labels]
    config = _validated(data)
    if config.backend not in state.ai.backends:
        names = ", ".join(sorted(state.ai.backends))
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"backend: no model backend named {config.backend!r}; there are {names}",
        )
    written = {key: getattr(config, key) for key in changes}
    if written.get("model") == "":
        written["model"] = None  # the default; leave it out of the file
    labels = None
    if patch.labels is not None:
        labels = [label.model_dump() for label in config.annotation.labels]
    try:
        edit_ai_section(state.config_path, written, labels)
    except ConfigError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from None
    return live_json(_settings_json(state, state.ai.config()))


@router.post(
    "/ai/models",
    response_model=AiModelsOut,
    responses={422: {"model": ErrorOut}},
    dependencies=[Depends(require(USE_AI))],
    name="listAiModels",
)
def list_models(state: State, body: Annotated[AiModelsIn | None, Body()] = None) -> Response:
    """The models a server offers: the saved one, or one being tried before it's saved.

    A POST, though it changes nothing, because it makes this server reach the address the
    request names: the browser protections then keep other websites from making it do so.
    """
    current = state.ai.config()
    changes = {} if body is None else body.model_dump(exclude_none=True)
    config = _validated(current.model_dump() | changes)
    result: dict[str, Any] = {"backend": config.backend, "server": config.server}
    try:
        models = state.ai.models(config)
    except ModelError as exc:
        return live_json(result | {"models": [], "error": str(exc)})
    listed = [{"id": m.id, "kind": m.kind, "loaded": m.loaded, "detail": m.detail} for m in models]
    return live_json(result | {"models": listed, "error": None})


@router.post(
    "/trials/{source_id}/annotate",
    response_class=NDJSONResponse,
    responses={
        200: {
            "model": AnnotationEvent,
            "description": "Newline-delimited JSON, one event a line: "
            "start, then spans for each piece of text as the model finishes it, then done "
            "(or error).",
        },
        404: _error("No such trial."),
        409: _error("AI is turned off."),
        422: _error("No labels, or no text to annotate."),
        502: _error("The model couldn't be reached."),
        503: _error("There's no data yet."),
    },
    dependencies=[Depends(require(USE_AI))],
    name="annotateTrial",
)
def annotate(
    state: State,
    source_id: str,
    body: AnnotateIn,
    source: Annotated[
        str | None, Query(description="The registry, if the id is in several")
    ] = None,
) -> NDJSONResponse:
    """Mark the terms of each annotation label in one of the trial's texts, as it runs.

    Nothing is stored: a text seen before with the same model and labels comes back at once
    from memory.
    """
    config = state.ai.config()
    if not config.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "AI is turned off in Settings")
    with state.read() as reader:
        _, trial_id = _find(reader, source_id, source)
        record = reader.get_trial(trial_id, raw=False)
        assert record is not None
        text = getattr(record, body.field) or ""
    if not text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"the trial has no {body.field}")
    try:
        events = state.ai.annotate(text, config)
    except ModelError as exc:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT if not config.annotation.labels else 502
        raise HTTPException(code, str(exc)) from None
    return NDJSONResponse(
        (orjson.dumps(event) + b"\n" for event in events),
        headers={"Cache-Control": NO_STORE, "X-Accel-Buffering": "no"},
    )
