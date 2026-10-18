"""``tri-al serve`` and ``tri-al worker`` (docs/design.md §3, §5.4 and §5.10).

``serve`` applies pending migrations, starts one job worker process, then runs the API in
uvicorn with ``server.workers`` processes. ``worker`` runs the job worker on its own, for
running the API elsewhere or debugging jobs.
"""

import logging
import multiprocessing
import os
import signal
import threading
from pathlib import Path
from types import FrameType
from typing import Annotated

import typer

from tri_al.config import Config, ConfigError, load_config
from tri_al.doctor import exposed_warning
from tri_al.jobs import JobQueue, Worker
from tri_al.plugins import LoadedPlugins, PluginError, load_plugins
from tri_al.storage import SQLiteStorage, StorageError, open_app_db

log = logging.getLogger("tri_al")


def serve(
    host: Annotated[
        str | None, typer.Option(help="Address to listen on. Default: server.host (127.0.0.1).")
    ] = None,
    port: Annotated[int | None, typer.Option(help="Default: server.port (8000).")] = None,
    workers: Annotated[
        int | None, typer.Option(min=1, help="API processes. Default: server.workers (1).")
    ] = None,
    job_worker: Annotated[
        bool, typer.Option("--job-worker/--no-job-worker", help="Run the job worker too.")
    ] = True,
    data_dir: Annotated[
        Path | None, typer.Option("--data-dir", file_okay=False, help="Default: data.dir.")
    ] = None,
) -> None:
    """Start the API and the job worker."""
    # API workers read their config from the environment, so overrides go there.
    for key, value in (
        ("TRI_AL_SERVER__HOST", host),
        ("TRI_AL_SERVER__PORT", port),
        ("TRI_AL_SERVER__WORKERS", workers),
        ("TRI_AL_DATA__DIR", None if data_dir is None else data_dir.resolve()),
    ):
        if value is not None:
            os.environ[key] = str(value)
    config, loaded = _setup()
    _warn_if_exposed(config, loaded)
    _prepare(config, loaded)

    import uvicorn

    process = None
    if job_worker:
        process = multiprocessing.get_context("spawn").Process(
            target=run_worker_process, name="tri-al-worker"
        )
        process.start()
    server = config.server
    typer.echo(f"Tri-AL on http://{_display(server.host)}:{server.port} (API docs at /api/docs)")
    try:
        uvicorn.run(
            "tri_al.api.app:create_app_from_env",
            factory=True,
            host=server.host,
            port=server.port,
            workers=server.workers,
            log_level="info",
            server_header=False,
            timeout_graceful_shutdown=5,  # open event streams never finish by themselves
        )
    finally:
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=30)


def worker() -> None:
    """Run the job worker on its own."""
    _setup()
    run_worker_process()


def run_worker_process() -> None:
    """The job worker's main loop, until SIGTERM or Ctrl-C."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config, loaded = _setup()
    engine = open_app_db(
        config.data.app_db,
        extensions=list(loaded.contributions.sqlite_extensions.values()),
        plugin_migrations=loaded.contributions.migrations_for("app"),
    )
    stop = threading.Event()

    def on_term(signum: int, frame: FrameType | None) -> None:
        # Stop between jobs; a job running now is interrupted like Ctrl-C would.
        stop.set()
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_term)
    worker = Worker.from_plugins(JobQueue(engine), config, loaded)
    log.info("job worker %s started (schedule: %s)", worker.name, config.update.schedule)
    try:
        worker.run(stop)
    except KeyboardInterrupt:
        log.info("job worker stopped")
    finally:
        engine.dispose()


def _setup() -> tuple[Config, LoadedPlugins]:
    try:
        config = load_config()
        return config, load_plugins(config)
    except (ConfigError, PluginError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None


def _prepare(config: Config, loaded: LoadedPlugins) -> None:
    """Apply pending migrations once, before any worker opens the databases."""
    contributions = loaded.contributions
    extensions = list(contributions.sqlite_extensions.values())
    try:
        open_app_db(
            config.data.app_db,
            extensions=extensions,
            plugin_migrations=contributions.migrations_for("app"),
        ).dispose()
        if config.data.trials_db.exists():
            SQLiteStorage.open(
                config.data.trials_db,
                extensions=extensions,
                plugin_migrations=contributions.migrations_for("trials"),
                starting=lambda component, migration: typer.echo(
                    f"Migrating trials.db: {component} {migration.version} "
                    f"({migration.description}); this may take a few minutes"
                ),
            ).close()
    except StorageError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None


def _warn_if_exposed(config: Config, loaded: LoadedPlugins) -> None:
    if warning := exposed_warning(config, loaded):
        typer.echo(typer.style(f"warning: {warning}", fg="yellow"), err=True)


def _display(host: str) -> str:
    return "localhost" if host in ("127.0.0.1", "0.0.0.0", "::", "") else host
