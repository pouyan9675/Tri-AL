"""The FastAPI app (docs/design.md §5.9): one per API worker process.

``tri-al serve`` runs it with uvicorn (``create_app_from_env`` is the factory each worker
calls), beside one job worker process. The OpenAPI schema is at ``/api/openapi.json``;
every other path that isn't under ``/api`` is the built front end (``tri_al.api.web``).
"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tri_al import __version__
from tri_al.access import READ, require
from tri_al.access.browser import BrowserProtection
from tri_al.api.events import EventHub, stream
from tri_al.api.http import NO_STORE, JSONBytes
from tri_al.api.routes import ai, data, jobs, plugins, terms
from tri_al.api.state import ApiState
from tri_al.api.web import add_web
from tri_al.config import Config, config_path, load_config
from tri_al.plugins import LoadedPlugins, load_plugins

log = logging.getLogger(__name__)

GZIP_MIN_BYTES = 1024
GZIP_LEVEL = 5
"""Level 5 compresses JSON nearly as well as 9 at a fraction of the time."""


def _operation_id(route: APIRoute) -> str:
    return route.name


def create_app(
    config: Config | None = None,
    loaded: LoadedPlugins | None = None,
    *,
    config_file: Path | None = None,
    data_dir: Path | None = None,
    use_index: bool = True,
) -> FastAPI:
    """The app for ``config`` (default: ``tri-al.toml``) and its enabled plugins.

    ``use_index`` False answers filtered stats from SQLite alone, without the in-memory index.
    """
    config_file = config_path() if config_file is None else config_file
    config = load_config(config_file) if config is None else config
    loaded = load_plugins(config) if loaded is None else loaded
    state = ApiState.create(
        config, loaded, config_path=config_file, data_dir=data_dir, use_index=use_index
    )
    hub = EventHub(state)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        storage = state.storage()
        if storage is not None and state.use_index:
            with storage.read() as reader:
                state.stats().index_for(reader.data_version())  # builds in the background
        try:
            yield
        finally:
            await hub.close()
            state.close()

    app = FastAPI(
        title="Tri-AL",
        version=__version__,
        summary="ClinicalTrials.gov in a fast local dashboard.",
        lifespan=lifespan,
        default_response_class=JSONBytes,
        generate_unique_id_function=_operation_id,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.tri_al = state
    app.state.access_policy = state.access_policy
    app.state.events = hub
    app.include_router(data.router)
    app.include_router(jobs.router)
    app.include_router(plugins.router)
    app.include_router(ai.router)
    app.include_router(terms.router)

    @app.get(
        "/api/events",
        tags=["events"],
        name="streamEvents",
        response_class=StreamingResponse,
        dependencies=[Depends(require(READ))],
        responses={
            200: {"content": {"text/event-stream": {}}, "description": "Server-sent events"}
        },
    )
    async def events(
        request: Request,
        max_events: Annotated[
            int | None, Query(ge=1, description="Close after this many events (for scripts)")
        ] = None,
    ) -> StreamingResponse:
        """Server-sent events: ``hello``, then ``data_version`` and ``job`` as they change."""
        return StreamingResponse(
            stream(request, hub, max_events),
            media_type="text/event-stream",
            headers={"Cache-Control": NO_STORE, "X-Accel-Buffering": "no"},
        )

    for name, router in loaded.contributions.routes.items():
        app.include_router(router, prefix=f"/api/x/{name}", tags=[f"plugin: {name}"])
    add_web(app, config.server.web_dir)  # last: its catch-all route serves the app's pages

    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL)
    app.add_middleware(ServerTiming)
    app.add_middleware(BrowserProtection, hosts=config.server.hosts())
    return app


class ServerTiming:
    """Adds ``Server-Timing: app;dur=<ms>``: the time until the response starts, gzip included.

    Browsers show it in their developer tools; the benchmarks read it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()

        async def timed(message: Message) -> None:
            if message["type"] == "http.response.start":
                elapsed = (time.perf_counter() - started) * 1000
                MutableHeaders(scope=message).append("Server-Timing", f"app;dur={elapsed:.2f}")
            await send(message)

        await self.app(scope, receive, timed)


def create_app_from_env() -> FastAPI:
    """The factory uvicorn calls in each API worker: config from ``tri-al.toml`` and env."""
    return create_app()
